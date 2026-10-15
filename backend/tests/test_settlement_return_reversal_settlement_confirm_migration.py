"""Post-settlement correction: another Lease's own Final Settlement confirm that used a returned
Credit counts against the return, and the return's reversal undoes that use through the companion
correction of that Lease's Settlement (sub-slice 10e-3d-2d-2c).

Owner answer (a) to Q-2026-10-15-113: when the Customer's other Lease closes after a return and
its own Final Settlement confirm (not a correction) lets the returned Credit pay its debt (DL-032:
each Customer's Credit pays that Customer's open debt first), that use counts too, in the same
time order as the corrections' uses. The confirm's Credit applications carry the Settlement and
no correction link; the walk takes that Settlement as a walker while some return's money is left,
and a reversal of the return reverses such an application whole and puts back its rest through
the companion correction of that Settlement (sub-slice 10e-3d-2d-2a).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
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
from property_rental.settlement_correction import settlement_correction_draft_id
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    leaving_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import setup_reservation_sources
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    COUNTS,
    NOTHING_LEFT,
    credit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_return_migration import available, net
from test_settlement_return_reversal_companion_migration import STATE, companion_of
from test_settlement_return_reversal_migration import (
    REASON,
    app_catalog,
    confirm_reversal,
    lease_of,
    record_reversal,
    reversal_command,
)
from test_settlement_return_reversal_other_refund_follow_migration import (
    RECOVERY,
    expected_recovery,
    refunding_case,
)
from test_settlement_return_reversal_other_refunding_take_migration import rows
from test_settlement_returned_payment_migration import closed_case
from test_settlement_returned_value_left_migration import CHANGED, counted

REVISION = "20261215_141"
WALK = (
    "SELECT walk_kind,walk_correction_id,walk_entry_id,walk_amount_usd_cents,"
    "walk_offset_usd_cents,walk_swept FROM app.settlement_returned_value_walk(%s,'CREDIT',%s,NULL) "
    "ORDER BY walk_position"
)


def walk(url: str, settlement: object, credit: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        rows = connection.execute(WALK, (settlement, credit)).fetchall()
    return [(row[0], str(row[1]), str(row[2]) if row[2] else None, *row[3:]) for row in rows]


def closing_after(
    url: str, monkeypatch: pytest.MonkeyPatch, customer: UUID, credit: UUID, amount: int
) -> dict[str, Any]:
    """The Customer's second Lease B in the shared test Property (a new Unit), built by the same
    leaving fixture and closed after the returns: B's own Final Settlement confirm lets the
    returned Credit pay `amount` of B's other damage line first (DL-032), then B's own Initial
    Rent Credit 400; the Deposits pay the damage lines, and the Pet Deposit's rest (5,400 plus
    `amount`) is refunded."""

    def same_customer(connection: psycopg.Connection[tuple[object, ...]]) -> tuple[Any, ...]:
        actor_id, prop, unit, _ = setup_reservation_sources(connection)
        return actor_id, prop, unit, customer

    with monkeypatch.context() as patched:
        patched.setattr(initial_fixture, "setup_reservation_sources", same_customer)
        case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    assert case["customer"] == customer
    # The fixture names the Customer's first Credit; this Lease's own is the only other one
    # with value.
    with psycopg.connect(url) as connection:
        [(own_credit,)] = connection.execute(
            "SELECT id FROM app.customer_credits "
            "WHERE customer_id=%s AND id<>%s AND app.credit_available_value(id)>0",
            (customer, credit),
        ).fetchall()
    case["credit"] = UUID(str(own_credit))
    steps = (
        SettlementCreditStep(credit, LINE, case["other_line"], amount),
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 2_100 - amount),
        settlement_refund(case, "pet", 5_400 + amount),
    )
    confirm_settlement(case, record_settlement(case, steps, pet_remainder=STAFF))
    case["person"] = correction_approver(url)
    return case


def confirm_case(
    url: str, monkeypatch: pytest.MonkeyPatch, returns: tuple[int, ...]
) -> dict[str, Any]:
    """The owner's Q-2026-10-15-113 example on the real path. The first Lease A closes; a REFUND
    correction of its Initial Rent line refunds 2,000 of released Payment value from a new Credit
    to the Customer; return-only corrections of A bring back `returns` of that Refund into the
    Credit, in order; then the Customer's second Lease B closes, its own confirm applying all
    the returned money to B's debt."""
    first = {**closed_case(url), "url": url}
    rent, _ = initial_fixture.rent_line(url, first["initial"])
    [paid] = confirm_refund(first, record_refund(first, refund_command(first, rent, 2_000)))[
        "refunds"
    ]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    assert available(url, credit) == 0
    earlier = [return_only(first, refund, amount) for amount in returns]
    returned = sum(returns)
    assert available(url, credit) == returned
    second = closing_after(url, monkeypatch, first["customer"], credit, returned)
    with psycopg.connect(url) as connection:
        [(application, amount)] = connection.execute(
            "SELECT id,amount_usd_cents FROM app.customer_credit_applications "
            "WHERE final_settlement_id=%s AND customer_credit_id=%s",
            (second["settlement"], credit),
        ).fetchall()
    assert (amount, available(url, credit), outstanding(url, second["other_line"])) == (
        returned,
        0,
        0,
    )
    return {
        "first": first,
        "second": second,
        "refund": refund,
        "credit": credit,
        "earlier": earlier,
        "application": str(application),
    }


def parts(source: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            item["settlement_correction_id"],
            item["record_kind"],
            item["record_id"],
            item["amount_usd_cents"],
            item["part_usd_cents"],
        )
        for item in source["swept"]
    ]


def test_another_lease_s_own_settlement_confirm_counts_and_is_undone_through_the_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X1 brings back 300; the second Lease's own confirm, after X1, lets the Credit pay 300 of
    its damage line. X1 has nothing left, read from either Settlement (before this sub-slice it
    kept 300 while the Credit held nothing), and a held-value Refund naming X1 is refused with
    nothing written. The walk takes the second Settlement as a walker that takes X1's 300; a
    confirm of a Credit with no return's money left (the second Lease's own Credit) gives no
    walk row. X1's source
    lists the confirm's application (part 300 of 300) with no open part, nothing to put back and
    the second Settlement as its one companion. X1's reversal reverses that application through
    the companion: the line owes 300 again, the Credit ends empty, X1's Refund's net is 2,000
    again, and the ledger reconciles."""
    url = migrated_database_url
    found = confirm_case(url, monkeypatch, (300,))
    first, second, credit, [earlier] = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
    )
    application, settlement = found["application"], str(second["settlement"])
    expected = {str(earlier): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    assert credit_left(url, earlier, credit) == 0
    assert [row for row in walk(url, first["settlement"], credit) if row[1] == settlement] == [
        ("DRAW", settlement, None, 300, 0, False),
        ("TAKE", settlement, str(earlier), 300, 0, True),
    ]
    assert walk(url, second["settlement"], second["credit"]) == []
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as nothing_left:
        record_held(first, held_command(first, earlier))
    assert cause(nothing_left) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == unchanged
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == [] and source["swept_usd_cents"] == 300
    assert parts(source) == [(settlement, "CREDIT_APPLICATION", application, 300, 300)]
    assert [item["id"] for item in source["credit_applications"]] == [application]
    assert source["reapply"] == [] and source["recoveries"] == []
    assert [item["final_settlement_id"] for item in source["companions"]] == [settlement]
    draft = record_reversal(first, reversal_command(first, earlier))
    result = confirm_reversal(first, draft)
    assert result["credit_application_reversals"] == [] and result["reapplied"] == []
    [named] = result["companions"]
    [undone] = named["credit_application_reversals"]
    assert (
        named["final_settlement_id"],
        undone["credit_application_id"],
        undone["amount_usd_cents"],
        named["reapplied"],
    ) == (settlement, application, 300, [])
    companion = companion_of(url, draft, second["settlement"])
    header = companion["header"]
    assert (str(header[0]), str(header[1])) == (named["settlement_correction_id"], settlement)
    payload = companion["draft"][4]
    assert payload["source"]["credit_applications"] == source["credit_applications"]
    assert payload["plan"] == {"steps": []}
    assert one(url, COUNTS) == (unchanged[0] + 2, unchanged[1] + 2, *unchanged[2:])
    assert (
        outstanding(url, second["other_line"]),
        available(url, credit),
        net(url, found["refund"]),
    ) == (300, 0, 2_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_confirm_application_is_put_back_through_the_companion_and_a_later_return_waits(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X1 and X3 bring back 300 each; the second Lease's own confirm, after both, lets the
    Credit pay 600 of its damage line: X1's 300 first, then X3's. X1's reversal reverses the
    600 application whole and puts back 300 on the same line through the companion's step; the
    line owes 300, the Credit ends empty, X1's Refund's net is 1,700 (X3's return stands). X3
    has nothing left, and its money now sits in the companion's put-back, a payment that a
    correction of another Settlement changed: X3's reversal is refused (`CHANGED_APPLICATION`,
    the 10e-3d-2d-2a limit, fail closed) with nothing written; the ledger reconciles."""
    url = migrated_database_url
    found = confirm_case(url, monkeypatch, (300, 300))
    first, second, credit, [earlier, later] = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
    )
    application, settlement = found["application"], str(second["settlement"])
    expected = {str(earlier): (300, 300, 300, 0), str(later): (300, 300, 300, 0)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == [] and source["swept_usd_cents"] == 300
    assert parts(source) == [(settlement, "CREDIT_APPLICATION", application, 600, 300)]
    assert [(item["application_id"], item["amount_usd_cents"]) for item in source["reapply"]] == [
        (application, 300)
    ]
    assert [item["final_settlement_id"] for item in source["companions"]] == [settlement]
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
    ) == (str(second["other_line"]), 300, "OTHER_APPLICABLE_OBLIGATION")
    payload = companion_of(url, draft, second["settlement"])["draft"][4]
    assert len(payload["plan"]["steps"]) == 1
    assert one(url, COUNTS) == (before[0] + 2, before[1] + 2, *before[2:4], before[4] + 1)
    assert (
        outstanding(url, second["other_line"]),
        available(url, credit),
        net(url, found["refund"]),
    ) == (300, 0, 1_700)
    assert counted(url, first["settlement"], "CREDIT", credit)[str(later)] == (300, 300, 300, 0)
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as waits:
        record_reversal(first, reversal_command(first, later))
    assert cause(waits) == ("55000", CHANGED)
    assert one(url, COUNTS) == unchanged
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_return_after_the_other_lease_s_confirm_keeps_its_money(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 1 (independent set-up S-1, security SF1): the time order. X1 brings back
    300, the second Lease's own confirm lets the Credit pay 300, and X3 brings back 300 after
    that confirm. The confirm takes only X1's money (its walker comes before X3): X1 has nothing
    left and X3 keeps 300, read from either Settlement, and a held-value Refund naming X1 is
    refused (before this sub-slice it would have paid out X3's 300). X3's source undoes nothing.
    X1's reversal reverses the confirm's 300 application through the companion: the line owes
    300 again, the Credit holds X3's 300, X1's Refund's net is 1,700 and X3 keeps 300 left.
    X3's reversal then takes its 300 from the Credit with no companion: the Credit ends empty,
    the Refund's net is 2,000, and the ledger reconciles."""
    url = migrated_database_url
    found = confirm_case(url, monkeypatch, (300,))
    first, second, credit, [earlier] = (
        found["first"],
        found["second"],
        found["credit"],
        found["earlier"],
    )
    application, settlement = found["application"], str(second["settlement"])
    later = return_only(first, found["refund"], 300)
    assert available(url, credit) == 300
    expected = {str(earlier): (300, 300, 300, 0), str(later): (300, 0, 0, 300)}
    assert counted(url, first["settlement"], "CREDIT", credit) == expected
    assert counted(url, second["settlement"], "CREDIT", credit) == expected
    assert (credit_left(url, earlier, credit), credit_left(url, later, credit)) == (0, 300)
    assert [row for row in walk(url, first["settlement"], credit) if row[1] == settlement] == [
        ("DRAW", settlement, None, 300, 0, False),
        ("TAKE", settlement, str(earlier), 300, 0, True),
    ]
    # Review round 2 (independent SF-1): the confirm's walker comes before X3's entry in the
    # walk (oldest first, a walker after X3 would also take X1's money).
    walked = walk(url, first["settlement"], credit)
    entry = next(index for index, row in enumerate(walked) if row[:2] == ("ENTRY", str(later)))
    assert walked.index(("TAKE", settlement, str(earlier), 300, 0, True)) < entry
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as nothing_left:
        record_held(first, held_command(first, earlier))
    assert cause(nothing_left) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == unchanged
    [later_source] = one(url, STATE, first["settlement"], later)
    assert (
        later_source["swept"],
        later_source["swept_open"],
        later_source["companions"],
    ) == ([], [], [])
    [source] = one(url, STATE, first["settlement"], earlier)
    assert source["swept_open"] == [] and source["swept_usd_cents"] == 300
    assert parts(source) == [(settlement, "CREDIT_APPLICATION", application, 300, 300)]
    assert source["reapply"] == []
    assert [item["final_settlement_id"] for item in source["companions"]] == [settlement]
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, earlier)))
    [named] = result["companions"]
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in named["credit_application_reversals"]
    ] == [(application, 300)]
    assert named["reapplied"] == []
    assert one(url, COUNTS) == (unchanged[0] + 2, unchanged[1] + 2, *unchanged[2:])
    assert (
        outstanding(url, second["other_line"]),
        available(url, credit),
        net(url, found["refund"]),
    ) == (300, 300, 1_700)
    assert counted(url, first["settlement"], "CREDIT", credit)[str(later)] == (300, 0, 0, 300)
    assert credit_left(url, later, credit) == 300
    result = confirm_reversal(first, record_reversal(first, reversal_command(first, later)))
    assert result["companions"] == []
    assert (
        outstanding(url, second["other_line"]),
        available(url, credit),
        net(url, found["refund"]),
    ) == (300, 0, 2_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


TRIGGERS = (
    "SELECT trigger.tgname,trigger.tgenabled FROM pg_catalog.pg_trigger trigger "
    "WHERE trigger.tgrelid=%s::regclass AND NOT trigger.tgisinternal ORDER BY trigger.tgname"
)
ALLOWED = (
    "SELECT app.refund_recovery_allowed(correction),"
    "app.settlement_return_reversal_recovery_amount(correction) "
    "FROM app.refund_corrections correction WHERE correction.id=%s"
)
LINKED = (
    "SELECT effect.settlement_correction_id FROM app.refund_corrections correction "
    "JOIN app.settlement_correction_effects effect "
    "ON effect.refund_correction_id=correction.id "
    "OR effect.authorized_nonrecurring_obligation_id=correction.recovery_obligation_id "
    "OR effect.invoice_id=(SELECT line.invoice_id FROM app.invoice_lines line "
    "WHERE line.authorized_obligation_id=correction.recovery_obligation_id) "
    "WHERE correction.id=%s ORDER BY effect.effect_sequence"
)


def test_a_charge_back_on_no_lease_of_another_lease_s_refund_goes_through_its_companion(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner note of 2026-10-16 on the 10e-3d-2d-2b-2 limits; set-up (i) of the 10e-3d-2d-2c
    review round 1 independent reviewer. On the real path the recipient of another Lease's
    Refund is always a signed Customer of that Lease, so its charge-back goes on that Lease. In
    an owner transaction that is always rolled back, the recipient's signature on the second
    Lease is cleared by hand: X0's source (set-up R1 with the whole 1,500 on the other Lease's
    Refund) then charges the 1,500 back on no Lease and names no Settlement, the refusals allow
    it, and the reversal, recorded and confirmed in that transaction, writes the charge-back
    through the companion of the second Lease's Settlement: the charge-back, its charge and its
    Invoice are linked to the companion, and the Invoice has no Lease and bills the Customer;
    the other Refund's net is 0, X0's Refund's net 2,000 again and the Credit empty. Afterwards
    every trigger is as before and nothing was written."""
    url = migrated_database_url
    found = refunding_case(url, monkeypatch, 1_500)
    first, second, earlier, other_refund = (
        found["first"],
        found["second"],
        found["earlier"],
        found["other_refund"],
    )
    settlement = str(second["settlement"])
    lease, before = lease_of(second), rows(url, TRIGGERS, "app.lease_signers")
    key = uuid4()
    draft = settlement_correction_draft_id(first["prop"], first["human"], key)
    request = reversal_command(first, earlier, idempotency_key=key).return_reversal()
    # Review round 2 (both reviewers): built before the block, because the helper opens a
    # connection of its own.
    expected = {
        **expected_recovery(found, 1_500),
        "lease_id": None,
        "charge": "NO_LEASE",
        "closed_final_settlement_id": None,
    }
    signed = "SELECT signed_at FROM app.lease_signers WHERE lease_id=%s AND customer_id=%s"
    was_signed, unchanged = rows(url, signed, lease, first["customer"]), one(url, COUNTS)
    with psycopg.connect(url) as connection:
        try:
            # Nothing inside this block may open another connection: it would not see this
            # transaction's changes, and it would wait on the ALTER's lock.
            connection.execute("ALTER TABLE app.lease_signers DISABLE TRIGGER USER")
            cleared = connection.execute(
                "UPDATE app.lease_signers SET signed_at=NULL WHERE lease_id=%s AND customer_id=%s",
                (lease, first["customer"]),
            )
            assert cleared.rowcount == 1
            [(source,)] = connection.execute(STATE, (first["settlement"], earlier)).fetchall()
            assert source["recoveries"] == [expected]
            assert [item["final_settlement_id"] for item in source["companions"]] == [settlement]
            connection.execute(
                "SELECT app.assert_settlement_return_reversal_allowed(%s)", (Jsonb(source),)
            )
            connection.execute(
                "SELECT app.record_settlement_return_reversal_draft(%s,%s,%s,%s,%s,%s,"
                "'final_settlements.prepare')",
                (first["prop"], first["human"], draft, first["settlement"], Jsonb(request), REASON),
            )
            [(result,)] = connection.execute(
                "SELECT app.confirm_settlement_return_reversal(%s,%s,%s,'financial.approve')",
                (first["prop"], first["person"], draft),
            ).fetchall()
            # Review round 2 (independent SF-3, security N-1): the checks deferred to the commit
            # run here too.
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            assert result["recoveries"] == []
            [named] = result["companions"]
            [recovery] = named["recoveries"]
            assert (
                recovery["refund_id"],
                recovery["lease_id"],
                recovery["amount_usd_cents"],
            ) == (str(other_refund), None, 1_500)
            linked = connection.execute(LINKED, (recovery["refund_correction_id"],)).fetchall()
            assert [str(row[0]) for row in linked] == [named["settlement_correction_id"]] * 3
            billed = connection.execute(
                "SELECT invoice.lease_id,invoice.customer_id "
                "FROM app.refund_corrections correction JOIN app.invoice_lines line "
                "ON line.authorized_obligation_id=correction.recovery_obligation_id "
                "JOIN app.invoices invoice ON invoice.id=line.invoice_id WHERE correction.id=%s",
                (recovery["refund_correction_id"],),
            ).fetchone()
            assert billed is not None
            assert (billed[0], str(billed[1])) == (None, str(first["customer"]))
            assert connection.execute(
                "SELECT app.refund_net_value_at(%s,'infinity'),"
                "app.refund_net_value_at(%s,'infinity'),app.credit_available_value(%s)",
                (other_refund, found["refund"], found["credit"]),
            ).fetchone() == (0, 2_000, 0)
            assert_reconciled(connection, first["customer"])
        finally:
            connection.rollback()
    assert rows(url, TRIGGERS, "app.lease_signers") == before
    assert rows(url, signed, lease, first["customer"]) == was_signed
    assert (rows(url, RECOVERY, other_refund), one(url, COUNTS)) == ([], unchanged)


def test_the_return_reversal_s_own_branch_alone_refuses_another_settlement_s_refund(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner note of 2026-10-16 on the 10e-3d-2d-2b-2 limits; set-up (ii) of the 10e-3d-2d-2c
    review round 1 independent reviewer. A charge-back of another Lease's Refund linked to the
    return reversal alone is refused twice over (sub-slice 10e-3d-2d-2b-2, security review round
    2 N-2). In an owner transaction that is always rolled back, after the confirm of X0's
    reversal of set-up R1, the second Lease's Final Settlement is made open again by hand: the
    companion's row is still allowed (600); moved to the return reversal, which still lists the
    Refund, the row is refused, and now only by the reversal's own branch (it takes no Refund of
    another Final Settlement), because no closed Final Settlement's link can refuse it.
    Afterwards every trigger and the closure are as before and nothing was written."""
    url = migrated_database_url
    found = refunding_case(url, monkeypatch, 600)
    first, second, earlier, other_refund = (
        found["first"],
        found["second"],
        found["earlier"],
        found["other_refund"],
    )
    draft = record_reversal(first, reversal_command(first, earlier))
    closure = (
        "SELECT closed_at,closed_by,source_snapshot,closing_balance_due_usd_cents "
        "FROM app.final_settlements WHERE id=%s"
    )
    closed = rows(url, closure, second["settlement"])
    tables = ("app.settlement_correction_effects", "app.final_settlements")
    before, unchanged = [rows(url, TRIGGERS, table) for table in tables], one(url, COUNTS)
    with psycopg.connect(url) as connection:
        try:
            # Nothing inside this block may open another connection (as above).
            connection.execute(
                "SELECT app.confirm_settlement_return_reversal(%s,%s,%s,'financial.approve')",
                (first["prop"], first["person"], draft),
            )
            [(recovery,)] = connection.execute(RECOVERY, (other_refund,)).fetchall()
            assert connection.execute(ALLOWED, (recovery,)).fetchone() == (True, 600)
            connection.execute("ALTER TABLE app.final_settlements DISABLE TRIGGER USER")
            reopened = connection.execute(
                "UPDATE app.final_settlements SET closed_at=NULL,closed_by=NULL,"
                "source_snapshot=NULL,closing_balance_due_usd_cents=NULL WHERE id=%s",
                (second["settlement"],),
            )
            assert reopened.rowcount == 1
            assert connection.execute(ALLOWED, (recovery,)).fetchone() == (True, 600)
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
            assert connection.execute(ALLOWED, (recovery,)).fetchone() == (False, 600)
            assert connection.execute(
                "SELECT app.settlement_return_reversal_refund(%s,%s)", (draft, other_refund)
            ).fetchone() == (True,)
        finally:
            connection.rollback()
    assert [rows(url, TRIGGERS, table) for table in tables] == before
    assert rows(url, closure, second["settlement"]) == closed
    assert (rows(url, RECOVERY, other_refund), one(url, COUNTS)) == ([], unchanged)


def test_the_settlement_confirm_count_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 141 adds no function and changes only the listed functions (each body exactly
    the old one with the module's replacements, each anchor found as often as listed;
    privileges, owner, definer and settings kept); no constraint or trigger changes; it is
    forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261214_140"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_returned_value_settlement_confirm") as temporary:
        alembic_command.upgrade(config, "20261214_140")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
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
