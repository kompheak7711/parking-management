"""Post-settlement correction: a return's money on a payment that another Lease's REFUND correction
changed is followed into that correction's Refund and payments and undone through the companion
correction of that Lease's Settlement (sub-slice 10e-3d-2d-2b-2).

Owner answers (a) to Q-2026-10-13-103 point 3 and Q-2026-10-13-107, and owner answer 4 of
2026-10-16: a stretch of the returned money on a payment that another Lease's REFUND correction Q
reversed is followed into Q's Refunds (the oldest first) and payments (the newest first), as for a
REFUND correction of the return's own Settlement. A part on Q's Refund is charged back to its
recipient on Q's Lease when the recipient is that Lease's signed Customer; a part on Q's payment is
reversed. Both go through the companion correction of Q's Settlement, which links the charge, as
that closed Settlement's guards require. Set-up R1 of the 10e-3d-2d-2b-1 review record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import FinalSettlementConflictError, SettlementCreditStep
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import COUNTS, return_only
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    return_command,
)
from test_settlement_return_reversal_companion_migration import (
    INCOMPLETE,
    STATE,
    applications_of,
    charge,
    companion_of,
)
from test_settlement_return_reversal_migration import (
    app_catalog,
    charge_open,
    confirm_reversal,
    lease_of,
    record_reversal,
    reversal_command,
)
from test_settlement_return_reversal_other_refunding_take_migration import TRIGGERS, rows
from test_settlement_returned_payment_migration import closed_case
from test_settlement_returned_value_left_migration import CHANGED
from test_settlement_returned_value_other_settlements_migration import (
    second_lease,
    two_lease_case,
)

REVISION = "20261214_140"
REFUND_OWNER = "app.settlement_refund_owner(uuid)"
RECOVERY = (
    "SELECT correction.id FROM app.refund_corrections correction "
    "WHERE correction.refund_id=%s AND correction.correction_kind='RECOVERED_BY_CHARGE'"
)


def refunding_case(url: str, monkeypatch: pytest.MonkeyPatch, refunded: int) -> dict[str, Any]:
    """Set-up R1: X0 of the first Lease brings back 1,500 and the second Lease's correction C1
    pays the whole 1,500 charge from the Credit; a REFUND correction Q of the second Lease then
    refunds `refunded` of that charge line: it lowers the charge by `refunded`, reverses C1's
    1,500 payment, writes the rest again and refunds `refunded` from the Credit to the Customer,
    so the line owes nothing."""
    found = two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)
    second, credit = found["second"], found["credit"]
    [(_, line, paid)] = applications_of(url, found["taker"])
    assert paid == 1_500
    result = confirm_refund(second, record_refund(second, refund_command(second, line, refunded)))
    refunding = UUID(str(result["settlement_correction"]["id"]))
    [(other_refund, other_credit, other_amount, other_number)] = rows(
        url,
        "SELECT refund.id,refund.source_customer_credit_id,refund.usd_accounting_value_cents,"
        "refund.refund_number "
        "FROM app.settlement_correction_effects effect "
        "JOIN app.refunds refund ON refund.id=effect.refund_id "
        "WHERE effect.settlement_correction_id=%s",
        refunding,
    )
    assert (other_credit, other_amount) == (credit, refunded)
    assert (available(url, credit), outstanding(url, line)) == (0, 0)
    return {
        **found,
        "line": line,
        "refunding": refunding,
        "other_refund": other_refund,
        "other_refund_number": other_number,
        "rest": applications_of(url, refunding),
    }


def expected_recovery(found: dict[str, Any], amount: int) -> dict[str, Any]:
    """The source's charge-back entry of the other Lease's Refund: on that Lease, named by its
    closed Final Settlement (owner answer 4)."""
    second = found["second"]
    return {
        "refund_id": str(found["other_refund"]),
        "refund_number": found["other_refund_number"],
        "source_kind": "CREDIT",
        "source_id": str(found["credit"]),
        "recipient_customer_id": str(found["first"]["customer"]),
        "amount_usd_cents": amount,
        "net_usd_cents": amount,
        "lease_id": str(lease_of(second)),
        "charge": "CLOSED_SETTLEMENT_LEASE",
        "closed_final_settlement_id": str(second["settlement"]),
        "reservation_outcome": False,
        "shared_deposit": False,
        "deposit_customer": True,
        "returns": 0,
    }


def linked_to(url: str, recovery: object) -> list[str]:
    """The correction each effect row of a recovery, its charge and its Invoice is linked to."""
    linked = rows(
        url,
        "SELECT effect.settlement_correction_id FROM app.refund_corrections correction "
        "JOIN app.settlement_correction_effects effect "
        "ON effect.refund_correction_id=correction.id "
        "OR effect.authorized_nonrecurring_obligation_id=correction.recovery_obligation_id "
        "OR effect.invoice_id=(SELECT line.invoice_id FROM app.invoice_lines line "
        "WHERE line.authorized_obligation_id=correction.recovery_obligation_id) "
        "WHERE correction.id=%s ORDER BY effect.effect_sequence",
        recovery,
    )
    return [str(row[0]) for row in linked]


def test_a_return_s_money_on_a_payment_another_lease_s_refund_correction_changed_is_undone(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set-up R1: Q refunds 600 and writes 900 again, so X0's 1,500 sits 600 on Q's Refund and
    900 on the 900 written again. X0's source lists both parts, no open part, the second
    Settlement as its one companion and one charge-back of Q's Refund on the second Lease. X0's
    reversal reverses the 900 payment and charges the 600 back to the Customer on the second
    Lease, both through the companion: the charge line owes 900 again, the Credit ends empty,
    Q's Refund's net is 0, X0's Refund's net 2,000 again; the charge-back, its charge and its
    Invoice are linked to the companion, which names them in the result and its audit event,
    and outside the confirming transaction the recovery check allows the row no more;
    the ledger reconciles."""
    url = migrated_database_url
    found = refunding_case(url, monkeypatch, 600)
    first, second, credit, earlier, line = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
        found["line"],
    )
    refunding, other_refund = found["refunding"], found["other_refund"]
    [(rest, rest_line, rest_amount)] = found["rest"]
    assert (rest_line, rest_amount) == (line, 900)
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == [] and source["swept_usd_cents"] == 1_500
    assert sorted(
        (
            item["settlement_correction_id"],
            item["record_kind"],
            item["record_id"],
            item["amount_usd_cents"],
            item["part_usd_cents"],
        )
        for item in source["swept"]
    ) == [
        (str(refunding), "CREDIT_APPLICATION", rest, 900, 900),
        (str(refunding), "REFUND", str(other_refund), 600, 600),
    ]
    assert [item["id"] for item in source["credit_applications"]] == [rest]
    assert source["reapply"] == []
    assert [item["final_settlement_id"] for item in source["companions"]] == [
        str(second["settlement"])
    ]
    assert source["recoveries"] == [expected_recovery(found, 600)]
    before = one(url, COUNTS)
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    assert result["credit_application_reversals"] == [] and result["recoveries"] == []
    [named] = result["companions"]
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in named["credit_application_reversals"]
    ] == [(rest, 900)]
    assert named["reapplied"] == []
    [recovery] = named["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["lease_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (str(other_refund), str(first["customer"]), str(lease_of(second)), 600, "EXTRA_CHARGE")
    assert charge_open(url, recovery) == 600
    # Security review round 1 (SF2): outside the confirming transaction the companion branch
    # allows nothing.
    assert one(
        url,
        "SELECT app.refund_recovery_allowed(c) FROM app.refund_corrections c WHERE c.id=%s",
        recovery["refund_correction_id"],
    ) == (False,)
    companion = companion_of(url, draft, second["settlement"])
    header = str(companion["header"][0])
    assert named["settlement_correction_id"] == header
    payload = companion["draft"][4]
    assert payload["source"]["recoveries"] == source["recoveries"]
    assert payload["plan"] == {"steps": []}
    assert linked_to(url, recovery["refund_correction_id"]) == [header, header, header]
    [(audit_lease, state)] = companion["audits"]
    assert (str(audit_lease), state["recoveries"]) == (str(lease_of(second)), [recovery])
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:])
    assert (
        outstanding(url, line),
        available(url, credit),
        net(url, other_refund),
        net(url, found["refund"]),
    ) == (900, 0, 0, 2_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_return_s_money_wholly_on_another_lease_s_refund_is_charged_back_through_its_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set-up R1 with 1,500: Q refunds the whole 1,500 and writes nothing again, so X0's 1,500
    sits wholly on Q's Refund. The refusal function allows X0's source and refuses it as
    incomplete when its companions miss the second Settlement, when the charge-back belongs to no
    listed companion, names the first Settlement or the first Lease, or when a charge on a Lease
    names no Settlement or no Lease names one (fail closed). X0's reversal writes a companion with
    only the charge-back (no payment reversed, an empty plan): the charge line still owes nothing,
    the Credit ends empty, Q's Refund's net is 0 and X0's Refund's net 2,000 again; the ledger
    reconciles."""
    url = migrated_database_url
    found = refunding_case(url, monkeypatch, 1_500)
    first, second, credit, earlier, line = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
        found["line"],
    )
    other_refund = found["other_refund"]
    assert found["rest"] == []
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == []
    assert [
        (item["record_kind"], item["record_id"], item["part_usd_cents"]) for item in source["swept"]
    ] == [("REFUND", str(other_refund), 1_500)]
    assert source["credit_applications"] == [] and source["reapply"] == []
    [entry] = source["companions"]
    assert entry["final_settlement_id"] == str(second["settlement"])
    assert source["recoveries"] == [expected_recovery(found, 1_500)]
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
    for built in (
        {**source, "companions": []},
        {
            **source,
            "recoveries": [
                {
                    **expected_recovery(found, 1_500),
                    "lease_id": str(lease_of(first)),
                    "closed_final_settlement_id": str(first["settlement"]),
                }
            ],
        },
        # Security review round 1 (SF1): a charge on a Lease must name that Lease's Settlement,
        # and no Lease no Settlement.
        {
            **source,
            "recoveries": [
                {
                    **expected_recovery(found, 1_500),
                    "lease_id": str(lease_of(first)),
                    "closed_final_settlement_id": None,
                }
            ],
        },
        {
            **source,
            "recoveries": [{**expected_recovery(found, 1_500), "lease_id": None}],
        },
        # Security and independent review round 2: the Lease branch alone (the second
        # Settlement named, the first Lease charged), and the companion-membership branch alone
        # (no Refund part, no swept total, no companion, the charge-back kept).
        {
            **source,
            "recoveries": [{**expected_recovery(found, 1_500), "lease_id": str(lease_of(first))}],
        },
        {
            **source,
            "swept": [],
            "swept_usd_cents": 0,
            "swept_undone_usd_cents": 0,
            "companions": [],
        },
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            INCOMPLETE,
        )
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    assert result["recoveries"] == []
    [named] = result["companions"]
    assert named["credit_application_reversals"] == [] and named["reapplied"] == []
    [recovery] = named["recoveries"]
    assert (recovery["refund_id"], recovery["lease_id"], recovery["amount_usd_cents"]) == (
        str(other_refund),
        str(lease_of(second)),
        1_500,
    )
    companion = companion_of(url, draft, second["settlement"])
    payload = companion["draft"][4]
    assert (payload["plan"], payload["source"]["credit_applications"]) == ({"steps": []}, [])
    assert payload["source"]["recoveries"] == source["recoveries"]
    assert linked_to(url, recovery["refund_correction_id"]) == [str(companion["header"][0])] * 3
    assert (
        outstanding(url, line),
        charge_open(url, recovery),
        available(url, credit),
        net(url, other_refund),
        net(url, found["refund"]),
    ) == (0, 1_500, 0, 0, 2_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_two_returns_charge_back_their_shares_of_another_lease_s_refund_in_turn(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 set-up S-A: two return-only corrections of the first Lease,
    X0 then X0b, bring back 700 and 800; the second Lease's correction C1 pays its whole 1,500
    charge from the Credit (X0's 700 first, then X0b's 800) and refunds its Pet Deposit; a REFUND
    correction Q of the second Lease refunds the whole 1,500 from the Credit. X0's reversal charges
    back only its 700 share of Q's 1,500 Refund on the second Lease through a companion (a share of
    the net, which the companion's draft lists); X0b's reversal then charges back the other 800
    through a second companion of the same Settlement; the Credit stays empty, Q's Refund's net
    ends at 0 and the first Lease's Refund's net at 2,000; the ledger reconciles."""
    url = migrated_database_url
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    second = second_lease(url, monkeypatch, first["customer"])
    x0 = return_only(first, refund, 700)
    x0b = return_only(first, refund, 800)
    assert available(url, credit) == 1_500
    _, line = unpaid_charge(url, second, second["person"])
    confirm(
        second,
        record(
            second,
            return_command(
                second,
                pet_refund(second),
                5_400,
                SettlementCreditStep(credit, LINE, line, 1_500),
                settlement_refund(second, "pet", 5_400),
            ),
        ),
    )
    released = confirm_refund(second, record_refund(second, refund_command(second, line, 1_500)))
    refunding = UUID(str(released["settlement_correction"]["id"]))
    [q_refund] = [UUID(str(item["id"])) for item in released["refunds"]]
    assert (available(url, credit), outstanding(url, line), net(url, q_refund)) == (0, 0, 1_500)
    for earlier, share, remaining, returned_net in ((x0, 700, 800, 1_200), (x0b, 800, 0, 2_000)):
        [source] = one(url, STATE, first["settlement"], earlier)
        assert source["swept_open"] == []
        assert [
            (
                item["settlement_correction_id"],
                item["record_kind"],
                item["record_id"],
                item["amount_usd_cents"],
                item["part_usd_cents"],
            )
            for item in source["swept"]
        ] == [(str(refunding), "REFUND", str(q_refund), 1_500, share)]
        [entry] = source["recoveries"]
        assert (
            entry["amount_usd_cents"],
            entry["net_usd_cents"],
            entry["lease_id"],
            entry["closed_final_settlement_id"],
            entry["returns"],
        ) == (share, share + remaining, str(lease_of(second)), str(second["settlement"]), 0)
        draft = record_reversal(first, reversal_command(first, earlier))
        result = confirm_reversal(first, draft)
        [named] = result["companions"]
        [recovery] = named["recoveries"]
        assert (recovery["refund_id"], recovery["lease_id"], recovery["amount_usd_cents"]) == (
            str(q_refund),
            str(lease_of(second)),
            share,
        )
        assert charge_open(url, recovery) == share
        header = str(companion_of(url, draft, second["settlement"])["header"][0])
        assert named["settlement_correction_id"] == header
        assert linked_to(url, recovery["refund_correction_id"]) == [header] * 3
        assert (available(url, credit), net(url, q_refund), net(url, refund)) == (
            0,
            remaining,
            returned_net,
        )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_one_companion_charges_back_reverses_two_payments_and_puts_back_a_rest(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 set-up S-B, the set-up of the committed
    `test_a_take_whose_correction_also_refunded_from_the_credit_is_undone_through_the_companion`:
    X0 brought back 1,500 and the second Lease's correction paid the whole 1,500 charge from the
    Credit; X1 brings back 300; a REFUND correction of the second Lease refunds 200 of that line,
    writes 1,300 again and lets the Credit pay a new 300 charge first. X0's reversal (instead of
    X1's) goes through one companion that charges the 200 Refund back on the second Lease,
    reverses the 300 payment and the 1,300 written again and puts 300 back on the 1,300's line:
    the first charge owes 1,000, the new charge 300, the Credit ends empty, X0's Refund's net is
    1,700; X1's reversal afterwards stops at the payment the companion changed (fail closed); the
    ledger reconciles."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)
    first, second, refund, credit, earlier = (
        found["first"],
        found["second"],
        found["refund"],
        found["credit"],
        found["earlier"],
    )
    [(_, first_charge, _)] = applications_of(url, found["taker"])
    later = return_only(first, refund, 300)
    second_charge = charge(url, second, 300)
    released = confirm_refund(
        second,
        record_refund(
            second,
            refund_command(
                second,
                first_charge,
                200,
                SettlementCreditStep(credit, LINE, second_charge, 300),
            ),
        ),
    )
    [other_refund] = [UUID(str(item["id"])) for item in released["refunds"]]
    written = applications_of(url, UUID(str(released["settlement_correction"]["id"])))
    [(rest, rest_line, _)] = [item for item in written if item[1] == first_charge]
    [(step, _, _)] = [item for item in written if item[1] == second_charge]
    [source] = one(url, STATE, first["settlement"], earlier)
    assert [(item["application_id"], item["amount_usd_cents"]) for item in source["reapply"]] == [
        (rest, 300)
    ]
    assert [(entry["refund_id"], entry["amount_usd_cents"]) for entry in source["recoveries"]] == [
        (str(other_refund), 200)
    ]
    assert [item["final_settlement_id"] for item in source["companions"]] == [
        str(second["settlement"])
    ]
    before = one(url, COUNTS)
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, earlier)))
    [named] = result["companions"]
    assert sorted(
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in named["credit_application_reversals"]
    ) == sorted([(step, 300), (rest, 1_300)])
    assert [(item["invoice_line_id"], item["amount_usd_cents"]) for item in named["reapplied"]] == [
        (str(rest_line), 300)
    ]
    [recovery] = named["recoveries"]
    assert (recovery["refund_id"], recovery["lease_id"], recovery["amount_usd_cents"]) == (
        str(other_refund),
        str(lease_of(second)),
        200,
    )
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:4], before[4] + 1)
    assert (
        outstanding(url, first_charge),
        outstanding(url, second_charge),
        available(url, credit),
        net(url, other_refund),
        net(url, refund),
        charge_open(url, recovery),
    ) == (1_000, 300, 0, 0, 1_700, 200)
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as stops:
        record_reversal(first, reversal_command(first, later))
    assert cause(stops) == ("55000", CHANGED)
    assert one(url, COUNTS) == unchanged
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_charge_back_of_another_lease_s_refund_is_allowed_only_through_its_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X0's recorded reversal of set-up R1 lists the other Lease's Refund, not X0's own Refund.
    In an owner transaction that is always rolled back, the reversal is confirmed; its
    charge-back of the other Lease's Refund, linked to the companion, is allowed for the 600 the
    companion's draft lists. Linked instead to the return reversal itself, the same row is
    refused twice over: the reversal's own branch takes no Refund of another Settlement (security
    review round 2), and the other Lease's closed Final Settlement no longer links it (the return
    reversal's own draft lists the same 600). Afterwards every trigger is as before and nothing
    was written."""
    url = migrated_database_url
    found = refunding_case(url, monkeypatch, 600)
    first, earlier, other_refund = found["first"], found["earlier"], found["other_refund"]
    draft = record_reversal(first, reversal_command(first, earlier))
    # Security review round 1 (SF2): the reversal's draft lists the other Lease's Refund and not
    # X0's own Refund.
    scope = "SELECT app.settlement_return_reversal_refund(%s,%s)"
    assert (one(url, scope, draft, other_refund), one(url, scope, draft, found["refund"])) == (
        (True,),
        (False,),
    )
    triggers = rows(url, TRIGGERS)
    allowed = (
        "SELECT app.refund_recovery_allowed(correction),"
        "app.settlement_return_reversal_recovery_amount(correction) "
        "FROM app.refund_corrections correction WHERE correction.id=%s"
    )
    with psycopg.connect(url) as connection:
        try:
            # Nothing inside this block may open another connection: it would not see this
            # transaction's confirm, and a record or confirm would wait on the ALTER's lock.
            connection.execute(
                "SELECT app.confirm_settlement_return_reversal(%s,%s,%s,'financial.approve')",
                (first["prop"], first["person"], draft),
            )
            [(recovery,)] = connection.execute(RECOVERY, (other_refund,)).fetchall()
            assert connection.execute(allowed, (recovery,)).fetchone() == (True, 600)
            [(reversal,)] = connection.execute(
                "SELECT app.settlement_correction_id(%s)", (draft,)
            ).fetchall()
            connection.execute("ALTER TABLE app.settlement_correction_effects DISABLE TRIGGER USER")
            connection.execute(
                "UPDATE app.settlement_correction_effects SET settlement_correction_id=%s,"
                "effect_sequence=(SELECT max(other.effect_sequence)+1 "
                "FROM app.settlement_correction_effects other "
                "WHERE other.settlement_correction_id=%s) WHERE refund_correction_id=%s",
                (reversal, reversal, recovery),
            )
            assert connection.execute(allowed, (recovery,)).fetchone() == (False, 600)
            # Independent review round 1 (note 2): the reversal still lists the Refund, so the
            # scope check is not what refuses the row; since security review round 2 the
            # reversal's own branch (no Refund of another Settlement) and the other Lease's
            # closed Final Settlement's link both refuse it.
            assert connection.execute(scope, (draft, other_refund)).fetchone() == (True,)
        finally:
            connection.rollback()
    assert rows(url, TRIGGERS) == triggers
    assert rows(url, RECOVERY, other_refund) == []


def test_the_other_refund_follow_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 140 adds only the internal owner of a Refund, which no application role may
    call, and changes only the listed functions (each body exactly the old one with the module's
    replacements, each anchor found as often as listed; privileges, owner, definer and settings
    kept); no constraint or trigger changes; it is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, REFUND_OWNER)
            ).fetchone() == (False,), role
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261213_139"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database(
        "settlement_return_reversal_other_refund_follow"
    ) as temporary:
        alembic_command.upgrade(config, "20261213_139")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {REFUND_OWNER}
    assert set(before_functions) <= set(after_functions)
    patched = dict(revision.module.PATCHES)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(patched)
    for name, replacements in patched.items():
        assert after_functions[name][1:] == before_functions[name][1:], name
        body = str(before_functions[name][0])
        for anchor, replacement, count in replacements:
            assert body.count(anchor) == count, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
