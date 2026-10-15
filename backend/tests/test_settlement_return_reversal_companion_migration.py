"""Post-settlement correction: a return reversal undoes another Lease's correction's Credit
payment through a companion correction of that Lease's Final Settlement (sub-slice 10e-3d-2d-2a).

Owner answers (a) to Q-2026-10-13-100 point 2 ("when a reversal undoes a payment on that other
Lease, that Lease's history must show which correction undid it") and (a) to Q-2026-10-13-103
point 3 (a companion correction of the other Lease's Settlement, recorded and confirmed together
with the reversal in one step). The reversal of a return whose money a correction of the
Customer's other closed Lease paid out through a Credit application reverses that application
whole and puts back the part that was not the return's money on its own line, every record on the
other Lease linked to a companion correction of its Settlement: a `RETURN_REVERSAL_COMPANION` draft
of that Settlement recorded and confirmed by the reversal's approver in the reversal's
transaction. The reversal names the companion and the companion names the reversal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

import test_unpaid_initial_termination_migration as initial_fixture
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, extra_charge
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_settlement_held_value_refund_migration import (
    COUNTS,
    confirm_held,
    credit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    return_command,
)
from test_settlement_return_reversal_migration import (
    app_catalog,
    confirm_reversal,
    lease_of,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_payment_migration import closed_case
from test_settlement_returned_value_left_migration import CHANGED, counted
from test_settlement_returned_value_other_settlements_migration import (
    second_lease,
    two_lease_case,
)

REVISION = "20261212_138"
OWNER = "app.settlement_credit_application_owner(uuid)"
GUARD = "A Final Settlement Credit application changes only through a post-settlement correction"
STATE = "SELECT app.settlement_return_reversal_source_state(%s,%s)"
INCOMPLETE = "The return reversal source is incomplete"
COMPANION_ID = "app.settlement_correction_companion_id(uuid,uuid)"
COMPANION_SOURCE = "app.settlement_return_reversal_companion_source(jsonb,uuid)"


def applications_of(url: str, correction: object) -> list[tuple[str, UUID, int]]:
    """The Credit applications a correction wrote: id, invoice line, amount."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT application.id,detail.invoice_line_id,application.amount_usd_cents "
            "FROM app.settlement_correction_effects effect "
            "JOIN app.customer_credit_applications application "
            "ON application.id=effect.customer_credit_application_id "
            "JOIN app.customer_credit_application_details detail "
            "ON detail.customer_credit_application_id=application.id "
            "WHERE effect.settlement_correction_id=%s ORDER BY effect.effect_sequence",
            (correction,),
        ).fetchall()
    return [(str(row[0]), UUID(str(row[1])), int(row[2])) for row in rows]


def companion_of(url: str, draft: UUID, settlement: object) -> dict[str, Any]:
    """The companion of a return reversal draft on another Final Settlement: its draft, decision,
    header, effects and audit event."""
    with psycopg.connect(url) as connection:
        [(companion_draft,)] = connection.execute(
            "SELECT app.settlement_correction_companion_id(%s,%s)", (draft, settlement)
        ).fetchall()
        drafted = connection.execute(
            "SELECT kind,prepare_capability,prepared_by,reason,payload "
            "FROM app.financial_drafts WHERE id=%s",
            (companion_draft,),
        ).fetchone()
        decided = connection.execute(
            "SELECT decision,decided_by,authorization_reference "
            "FROM app.financial_draft_decisions WHERE draft_id=%s",
            (companion_draft,),
        ).fetchone()
        header = connection.execute(
            "SELECT id,final_settlement_id,actor_id,reason,authorization_reference "
            "FROM app.settlement_corrections WHERE correlation_id=%s",
            (companion_draft,),
        ).fetchone()
        assert drafted is not None and decided is not None and header is not None
        effects = connection.execute(
            "SELECT credit_application_reversal_id,customer_credit_application_id "
            "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
            "ORDER BY effect_sequence",
            (header[0],),
        ).fetchall()
        audits = connection.execute(
            "SELECT lease_id,resulting_state FROM app.audit_events "
            "WHERE entity_type='settlement_correction' AND entity_id=%s",
            (header[0],),
        ).fetchall()
    return {
        "draft_id": str(companion_draft),
        "draft": drafted,
        "decision": decided,
        "header": header,
        "effects": [
            (str(row[0]) if row[0] else None, str(row[1]) if row[1] else None) for row in effects
        ],
        "audits": audits,
    }


def charge(url: str, case: dict[str, Any], amount: int) -> UUID:
    """After closure, an EXTRA_CHARGE correction issues an unpaid charge of `amount`; its line."""
    draft = record_extra_charge(case, extra_charge(case["settlement"], amount_usd_cents=amount))
    result = corrections().confirm_extra_charge(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )
    invoice = UUID(str(cast(dict[str, Any], result["invoice"])["id"]))
    return UUID(str(one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", invoice)[0]))


def corrections_of(url: str, settlement: object) -> list[str]:
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT id FROM app.settlement_corrections WHERE final_settlement_id=%s "
            "ORDER BY occurred_at,id",
            (settlement,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_a_reversal_undoes_another_lease_s_credit_payment_through_a_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's Q-2026-10-13-103 point 3 example confirmed: X1 of the first Lease brought back
    300 of a Credit Refund and a correction of the Customer's second Lease paid 300 of a charge
    there from that Credit. X1's reversal reverses that application whole through a companion of
    the second Settlement (the charge owes 300 again, the Credit ends empty, the Refund's net is
    the whole 2,000 again, X1 has nothing left from either Settlement): the companion is a
    confirmed RETURN_REVERSAL_COMPANION draft of the second Settlement, prepared and confirmed by
    the reversal's approver under final_settlements.prepare and financial.approve with the
    reversal's reason, names the reversal's draft and correction, and has one header, one effect
    (the application reversal) and its own audit event on the second Lease; the reversal names the
    companion in its result and audit event and links none of the second Lease's records; the
    second Settlement's correction list shows the companion; an exact repeat replays; the ledger
    reconciles."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch)
    first, second, credit, earlier, taker = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
        found["taker"],
    )
    [(application, charge_line, amount)] = applications_of(url, taker)
    assert amount == 300 and outstanding(url, charge_line) == 0
    # Security review round 1: the second Settlement's own rule is unchanged; a reversal of its
    # correction's application that no correction of it links is refused.
    with pytest.raises(psycopg.Error) as guarded, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,"
            "reason,occurred_at,actor_id,authorization_reference) "
            "VALUES (gen_random_uuid(),%s,'Not linked',clock_timestamp(),%s,"
            "'credits.applications.reverse')",
            (application, first["person"]),
        )
    assert (guarded.value.sqlstate, guarded.value.diag.message_primary) == ("P5S01", GUARD)
    before = one(url, COUNTS)
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    reversal = UUID(str(result["settlement_correction"]["id"]))
    assert result["credit_application_reversals"] == [] and result["reapplied"] == []
    [named] = result["companions"]
    [undone] = named["credit_application_reversals"]
    assert (named["final_settlement_id"], undone["credit_application_id"]) == (
        str(second["settlement"]),
        application,
    )
    assert undone["amount_usd_cents"] == 300 and named["reapplied"] == []
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:])
    assert (outstanding(url, charge_line), available(url, credit)) == (300, 0)
    assert net(url, found["refund"]) == 2_000
    expected = {str(earlier): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    companion = companion_of(url, draft, second["settlement"])
    approver = str(first["person"])
    kind, capability, preparer, reason, payload = companion["draft"]
    assert (kind, capability, str(preparer)) == (
        "SETTLEMENT_CORRECTION",
        "final_settlements.prepare",
        approver,
    )
    assert (
        payload["variant"],
        payload["final_settlement_id"],
        payload["lease_id"],
        payload["return_reversal_draft_id"],
        payload["return_reversal_correction_id"],
        payload["plan"],
    ) == (
        "RETURN_REVERSAL_COMPANION",
        str(second["settlement"]),
        str(lease_of(second)),
        str(draft),
        str(reversal),
        {"steps": []},
    )
    assert [item["id"] for item in payload["source"]["credit_applications"]] == [application]
    assert payload["source"]["reapply"] == []
    assert [str(value) for value in companion["decision"]] == [
        "CONFIRMED",
        approver,
        "financial.approve",
    ]
    header, settlement_id, actor, header_reason, authorization = companion["header"]
    assert (str(settlement_id), str(actor), header_reason, authorization) == (
        str(second["settlement"]),
        approver,
        reason,
        "financial.approve",
    )
    assert named["settlement_correction_id"] == str(header)
    assert named["draft_id"] == companion["draft_id"]
    assert companion["effects"] == [(undone["id"], None)]
    [(audit_lease, state)] = companion["audits"]
    assert (
        str(audit_lease),
        state["variant"],
        state["return_reversal_settlement_correction_id"],
    ) == (
        str(lease_of(second)),
        "RETURN_REVERSAL_COMPANION",
        str(reversal),
    )
    with psycopg.connect(url) as connection:
        [(reversal_state,)] = connection.execute(
            "SELECT resulting_state FROM app.audit_events "
            "WHERE entity_type='settlement_correction' AND entity_id=%s",
            (reversal,),
        ).fetchall()
        linked = connection.execute(
            "SELECT count(*) FROM app.settlement_correction_effects effect "
            "JOIN app.customer_credit_application_reversals reversal "
            "ON reversal.id=effect.credit_application_reversal_id "
            "WHERE effect.settlement_correction_id=%s",
            (reversal,),
        ).fetchone()
    assert reversal_state["companions"] == [str(header)] and linked == (0,)
    # The charge on the second Lease after closure is its own earlier correction.
    assert corrections_of(url, second["settlement"])[-2:] == [str(taker), str(header)]
    assert confirm_reversal(first, draft) == result
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def two_return_case(url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """As the 10e-3d-2d-1 two-Lease case, but two return-only corrections of the first Lease, X1
    then X3, each bring back 300 before the second Lease's correction lets the Credit pay 600 of
    its 1,500 charge (both returns' money, oldest first), the Pet Deposit 900, and refunds
    4,500."""
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    second = second_lease(url, monkeypatch, first["customer"])
    earlier = return_only(first, refund, 300)
    later = return_only(first, refund, 300)
    assert available(url, credit) == 600
    _, charge_line = unpaid_charge(url, second, second["person"])
    pet = second["pet"]
    result = confirm(
        second,
        record(
            second,
            return_command(
                second,
                pet_refund(second),
                5_400,
                SettlementCreditStep(credit, LINE, charge_line, 600),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 900),
                settlement_refund(second, "pet", 4_500),
                pet_remainder=STAFF,
            ),
        ),
    )
    assert (available(url, credit), outstanding(url, charge_line), held(url, pet)) == (0, 0, 0)
    return {
        "first": first,
        "second": second,
        "refund": refund,
        "credit": credit,
        "earlier": earlier,
        "later": later,
        "charge_line": charge_line,
        "taker": UUID(str(result["settlement_correction"]["id"])),
    }


def test_the_rest_of_another_lease_s_payment_is_put_back_through_the_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X1 and X3 each brought back 300 and the second Lease's correction paid 600 of a charge from
    the Credit (X1's 300, then 300 of X3's). X1's reversal reverses that 600 whole and puts the
    300 that was X3's money back on the same line through the companion's one-step plan, written
    on the second Settlement and linked to the companion, naming the payment it restores (the
    charge has no Rent or Service line, so its label is the other applicable obligation): the
    charge owes 300, the Credit stays empty, X1 and X3 have nothing left (X3's money is in the
    put-back). X3's later reversal is refused (the payment holding its money was changed by the
    other Lease's companion: fail closed) and writes nothing; the ledger reconciles."""
    url = migrated_database_url
    found = two_return_case(url, monkeypatch)
    first, second, credit, earlier, later, charge_line, taker = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
        found["later"],
        found["charge_line"],
        found["taker"],
    )
    [(application, line, amount)] = applications_of(url, taker)
    assert (line, amount) == (charge_line, 600)
    before = one(url, COUNTS)
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    [named] = result["companions"]
    [undone] = named["credit_application_reversals"]
    [restored] = named["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (application, 600)
    assert (
        restored["invoice_line_id"],
        restored["amount_usd_cents"],
        restored["within_invoice_basis"],
    ) == (str(charge_line), 300, "OTHER_APPLICABLE_OBLIGATION")
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:4], before[4] + 1)
    assert (outstanding(url, charge_line), available(url, credit)) == (300, 0)
    companion = companion_of(url, draft, second["settlement"])
    payload = companion["draft"][4]
    assert [item["application_id"] for item in payload["source"]["reapply"]] == [application]
    assert [(step["kind"], step["amount_usd_cents"]) for step in payload["plan"]["steps"]] == [
        ("CUSTOMER_CREDIT", 300)
    ]
    assert companion["effects"] == [(undone["id"], None), (None, restored["id"])]
    with psycopg.connect(url) as connection:
        put_back = connection.execute(
            "SELECT application.final_settlement_id,detail.calculation_trace "
            "FROM app.customer_credit_applications application "
            "JOIN app.customer_credit_application_details detail "
            "ON detail.customer_credit_application_id=application.id WHERE application.id=%s",
            (restored["id"],),
        ).fetchone()
    assert put_back is not None and str(put_back[0]) == str(second["settlement"])
    assert (put_back[1]["restores_credit_application_id"], put_back[1]["draft_id"]) == (
        application,
        companion["draft_id"],
    )
    # Review round 1: the put-back rule reads the companion's own draft; another step or more
    # than the reversed payment is refused.
    with psycopg.connect(url) as connection:
        checked = connection.execute(
            "SELECT app.settlement_correction_put_back_allowed(%(k)s,application,detail,1),"
            "app.settlement_correction_put_back_allowed(%(k)s,application,detail,2),"
            "app.settlement_correction_put_back_allowed(%(k)s,application,jsonb_populate_record("
            "detail,jsonb_build_object('applied_amount_usd_cents',601)),1) "
            "FROM app.customer_credit_applications application "
            "JOIN app.customer_credit_application_details detail "
            "ON detail.customer_credit_application_id=application.id "
            "WHERE application.id=%(put_back)s",
            {"k": named["settlement_correction_id"], "put_back": restored["id"]},
        ).fetchone()
    assert checked == (True, False, False)
    expected = {str(earlier): (300, 300, 300, 0), str(later): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as waits:
        record_reversal(first, reversal_command(first, later))
    assert cause(waits) == ("55000", CHANGED)
    assert one(url, COUNTS) == unchanged
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_reversal_undoes_another_lease_s_whole_payment_and_a_later_return_keeps_its_money(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 10e-3d-2d-1 harm case, now confirmed: X1 brought back 1,700, the second Lease's
    correction paid the whole 1,500 charge from the Credit (all X1's money), and a later return X3
    brought back 300. X1's reversal reverses the 1,500 whole through the companion (nothing put
    back), and takes back X1's 1,700 (the 200 X1 had left and the 1,500): the charge owes 1,500
    again, the Credit holds X3's 300, X1 has nothing left and X3 keeps 300, read from either
    Settlement; a held-value Refund naming X3 then refunds exactly 300; the ledger reconciles."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch, returned=1_700, credit_paid=1_500)
    first, second, refund, credit, earlier, taker = (
        found["first"],
        found["second"],
        found["refund"],
        found["credit"],
        found["earlier"],
        found["taker"],
    )
    later = return_only(first, refund, 300)
    [(application, charge_line, _)] = applications_of(url, taker)
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, earlier)))
    [named] = result["companions"]
    [undone] = named["credit_application_reversals"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"], named["reapplied"]) == (
        application,
        1_500,
        [],
    )
    assert (outstanding(url, charge_line), available(url, credit)) == (1_500, 300)
    assert net(url, refund) == 1_700
    expected = {str(earlier): (1_700, 1_700, 1_500, 0), str(later): (300, 0, 0, 300)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    [paid] = confirm_held(first, record_held(first, held_command(first, later)))["refunds"]
    assert (paid["source_customer_credit_id"], paid["amount_usd_cents"]) == (str(credit), 300)
    assert (available(url, credit), credit_left(url, later, credit)) == (0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_source_s_companions_must_match_its_other_settlements(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X1's source lists the second Settlement as its one companion (closed, the second Lease, the
    same Property) and the refusal function allows it; with no companion, a second entry for the
    same Settlement, an entry that is not closed, an entry for the reversal's own Settlement, an
    entry with another Lease, or companions that are not a list, the refusal function refuses
    the source as incomplete (fail closed)."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch)
    first, second, earlier = found["first"], found["second"], found["earlier"]
    [source] = one(url, STATE, first["settlement"], earlier)
    [entry] = source["companions"]
    assert entry == {
        "final_settlement_id": str(second["settlement"]),
        "lease_id": str(lease_of(second)),
        "property_id": str(second["prop"]),
        "closed": True,
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
    for companions in (
        [],
        [entry, entry],
        [{**entry, "closed": False}],
        [{**entry, "final_settlement_id": str(first["settlement"])}],
        [{**entry, "lease_id": str(lease_of(first))}],
        # Security review round 1: an entry of another Property.
        [{**entry, "property_id": str(uuid4())}],
        {"0": entry},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb({**source, "companions": companions}),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            INCOMPLETE,
        ), companions


def test_a_take_whose_correction_also_refunded_from_the_credit_is_undone_through_the_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 1 set-up: X0 of the first Lease brought back 1,500 and the second
    Lease's correction paid the whole 1,500 charge from the Credit; a later return X1 brings back
    300. A REFUND correction of the second Lease refunds 200 of that charge line: it releases the
    1,500 payment, writes 1,300 again, lets the Credit pay a new 300 charge first and refunds 200
    from the Credit, so it draws 300 more than it brought back, all X1's money. Its draw comes
    after the money it brought back, laid over its Refund and then its applications, the newest
    first, so X1's 300 sits on the 1,300 written again (sub-slice 10e-3d-2d-2b-1; renamed from
    `..._stays_one_open_part`: until then the whole take was one open part because the correction
    also paid a Refund). X1's reversal reverses that application whole and puts 1,000 back on its
    line, both through the companion of the second Settlement: the charge owes 300 again, the
    Credit ends empty, the Refund's net is 500, nothing is charged back to the other Lease's 200
    Refund; the ledger reconciles. X0's money, on the other Lease's 1,500 payment that its REFUND
    correction changed, is followed into that correction's Refund and payments (sub-slice
    10e-3d-2d-2b-2; until then it stopped as a changed payment and X0's reversal was refused,
    review round 1)."""
    url = migrated_database_url
    found = two_lease_case(url, monkeypatch, returned=1_500, credit_paid=1_500)
    first, second, refund, credit, earlier, taker = (
        found["first"],
        found["second"],
        found["refund"],
        found["credit"],
        found["earlier"],
        found["taker"],
    )
    [(paid_first, first_charge, _)] = applications_of(url, taker)
    later = return_only(first, refund, 300)
    assert available(url, credit) == 300
    second_charge = charge(url, second, 300)
    result = confirm_refund(
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
    refunding = UUID(str(result["settlement_correction"]["id"]))
    assert (
        available(url, credit),
        outstanding(url, first_charge),
        outstanding(url, second_charge),
    ) == (0, 0, 0)
    with psycopg.connect(url) as connection:
        refunds = connection.execute(
            "SELECT refund.source_customer_credit_id,refund.usd_accounting_value_cents,refund.id "
            "FROM app.settlement_correction_effects effect "
            "JOIN app.refunds refund ON refund.id=effect.refund_id "
            "WHERE effect.settlement_correction_id=%s",
            (refunding,),
        ).fetchall()
    assert [(str(row[0]), int(row[1])) for row in refunds] == [(str(credit), 200)]
    other_refund = refunds[0][2]
    assert net(url, other_refund) == 200
    expected = {str(earlier): (1_500, 1_500, 1_500, 0), str(later): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    [(rest, rest_line, rest_amount)] = [
        written for written in applications_of(url, refunding) if written[1] == first_charge
    ]
    assert rest_amount == 1_300
    [source] = one(url, STATE, first["settlement"], later)
    assert source["swept_open"] == [] and source["swept_usd_cents"] == 300
    assert [
        (item["record_kind"], item["record_id"], item["amount_usd_cents"], item["part_usd_cents"])
        for item in source["swept"]
    ] == [("CREDIT_APPLICATION", rest, 1_300, 300)]
    assert [item["id"] for item in source["credit_applications"]] == [rest]
    assert [(item["application_id"], item["amount_usd_cents"]) for item in source["reapply"]] == [
        (rest, 1_000)
    ]
    assert [item["final_settlement_id"] for item in source["companions"]] == [
        str(second["settlement"])
    ]
    # Review round 1 (independent N2): nothing is charged back to the other Lease's Refund.
    assert source["recoveries"] == []
    # Review round 1 (independent SF3, set-up R1): X0's money sat on the other Lease's 1,500
    # payment, which that Lease's REFUND correction changed. Sub-slice 10e-3d-2d-2b-2 (owner
    # answer 4 of 2026-10-16 and answer (a) to Q-2026-10-13-103 point 3) follows it into that
    # correction's 200 Refund, its 300 payment and 1,000 of the 1,300 written again; until then
    # it stopped there (CHANGED_APPLICATION) and X0's reversal was refused.
    [(step, _, _)] = [
        written for written in applications_of(url, refunding) if written[1] == second_charge
    ]
    [earlier_source] = one(url, STATE, first["settlement"], earlier)
    assert earlier_source["swept_open"] == []
    assert sorted(
        (item["record_kind"], item["record_id"], item["part_usd_cents"])
        for item in earlier_source["swept"]
    ) == sorted(
        [
            ("REFUND", str(other_refund), 200),
            ("CREDIT_APPLICATION", step, 300),
            ("CREDIT_APPLICATION", rest, 1_000),
        ]
    )
    assert paid_first not in [item["record_id"] for item in earlier_source["swept"]]
    before = one(url, COUNTS)
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, later)))
    assert result["credit_application_reversals"] == [] and result["reapplied"] == []
    assert result["recoveries"] == []
    [named] = result["companions"]
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in named["credit_application_reversals"]
    ] == [(rest, 1_300)]
    assert [(item["invoice_line_id"], item["amount_usd_cents"]) for item in named["reapplied"]] == [
        (str(rest_line), 1_000)
    ]
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:4], before[4] + 1)
    assert (
        outstanding(url, first_charge),
        outstanding(url, second_charge),
        available(url, credit),
        net(url, refund),
        net(url, other_refund),
    ) == (300, 0, 0, 500, 200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_an_own_put_back_listed_after_a_companion_s_is_followed_by_a_later_reversal(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review round 2 set-up (the successor and follow ranking): X0 brings back 200
    and X1 300; the second Lease's correction pays its 300 charge from the Credit (X0's 200 and
    100 of X1's); X3 brings back 300; a correction of the first Lease pays its 400 charge from
    the Credit (X1's last 200 and 200 of X3's). X1's reversal lists the second Lease's payment
    first and the first Lease's second: it puts 200 back on each line, the first through the
    companion, the second as its own first put-back. The successor function, called directly
    (it has had no caller since migration 134; round 3 should-fix, owner answer (a) to
    Q-2026-10-15-114), finds that own put-back for the first Lease's 400 payment. X3's reversal
    then follows X3's money into that own put-back through the follow function (both rank only
    the first Settlement's entries) and is confirmed: it reverses the 200 put-back whole, the
    first Lease's charge owes 400 again, the Credit ends empty and the Refund's net is 1,800; the
    ledger reconciles."""
    url = migrated_database_url
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    second = second_lease(url, monkeypatch, first["customer"])
    return_only(first, refund, 200)
    earlier = return_only(first, refund, 300)
    owed_second = charge(url, second, 300)
    confirm(
        second,
        record(
            second,
            return_command(
                second,
                pet_refund(second),
                5_400,
                SettlementCreditStep(credit, LINE, owed_second, 300),
                settlement_refund(second, "pet", 5_400),
            ),
        ),
    )
    later = return_only(first, refund, 300)
    owed_first = charge(url, first, 400)
    confirm(
        first,
        record(
            first,
            return_command(
                first,
                pet_refund(first),
                5_400,
                SettlementCreditStep(credit, LINE, owed_first, 400),
                settlement_refund(first, "pet", 5_400),
            ),
        ),
    )
    assert (available(url, credit), outstanding(url, owed_first)) == (100, 0)
    [source] = one(url, STATE, first["settlement"], earlier)
    assert [(item["target_id"], item["amount_usd_cents"]) for item in source["reapply"]] == [
        (str(owed_second), 200),
        (str(owed_first), 200),
    ]
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, earlier)))
    [named] = result["companions"]
    assert [item["amount_usd_cents"] for item in named["reapplied"]] == [200]
    assert [item["amount_usd_cents"] for item in result["reapplied"]] == [200]
    assert (outstanding(url, owed_first), outstanding(url, owed_second)) == (200, 100)
    assert available(url, credit) == 100
    # Round 3 should-fix: the successor function's ranking (NULL under the old ranking).
    assert one(
        url,
        "SELECT app.settlement_returned_value_successor('CREDIT',%s)",
        source["reapply"][1]["application_id"],
    ) == (UUID(result["reapplied"][0]["id"]),)
    followed = confirm_reversal(first, record_reversal(first, reversal_command(first, later)))
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in followed["credit_application_reversals"]
    ] == [(result["reapplied"][0]["id"], 200)]
    assert followed["companions"] == [] and followed["reapplied"] == []
    assert (outstanding(url, owed_first), available(url, credit)) == (400, 0)
    assert net(url, refund) == 1_800
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_the_return_reversal_companion_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 138 adds only the three internal functions (the owner of a Credit application
    and the two companion functions), which no application role may call, and changes only the
    listed functions (each body exactly the old one with the module's replacements, each
    anchor found as often as listed; privileges, owner, definer and settings kept); no
    constraint or trigger changes; it is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (OWNER, COMPANION_ID, COMPANION_SOURCE):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261211_137"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_companion") as temporary:
        alembic_command.upgrade(config, "20261211_137")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {OWNER, COMPANION_ID, COMPANION_SOURCE}
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
