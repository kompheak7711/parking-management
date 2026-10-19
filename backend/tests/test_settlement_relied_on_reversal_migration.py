"""Refusals after closure of what a closed Final Settlement relied on (V1-056 sub-slice 10h-1).

Owner answers 3 and 4 to Q-2026-10-06-36, answer 5 to Q-2026-10-06-37, the answer to
Q-2026-10-07-39, the owner note of 2026-10-16 on the 10f-2 report and owner answer (a) to
Q-2026-10-17-120 point 2: once a Final Settlement is closed, an allocation or Credit application
it relied on (made at or before the closure on an obligation of its Lease, or linked to one of its
corrections) changes only through a post-settlement correction of that Settlement (BR-SETTLE-012,
BR-SETTLE-013, BR-PAY-042). The one-call reversals and the slice 7 move draft are refused, so the
debt the Settlement saw paid cannot reopen outside a correction and a charge reduction cannot then
remove it; a correction of that Settlement still reverses and moves what it links.
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

from property_rental.credit import CreditConflictError, ReverseCreditApplicationCommand
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.invoice import AdjustInvoiceCommand, AdjustmentType, InvoiceConflictError
from property_rental.payment_allocation import AllocationConflictError, ReverseAllocationCommand
from property_rental.payment_move import PaymentMoveConflictError, RecordPaymentMoveCommand
from test_credit_application_migration import application_id
from test_credit_application_migration import designated as designated_credit
from test_credit_migration import actor as credit_actor
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import outstanding
from test_invoice_migration import invoice_api_actor
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import person, value
from test_returned_payment_after_closure_migration import allocate as allocate_line
from test_returned_payment_after_closure_migration import customer_payment
from test_settlement_adjustment_reversal_migration import closed_case, lease_adjustment
from test_settlement_adjustment_reversal_migration import confirm as confirm_adjustment_reversal
from test_settlement_adjustment_reversal_migration import draft_of as adjustment_reversal_draft
from test_settlement_adjustment_reversal_migration import record as record_adjustment_reversal
from test_settlement_charge_reduction_migration import RELEASE, reduction
from test_settlement_charge_reduction_migration import record as record_reduction
from test_settlement_late_charge_reduction_migration import RELEASES_PAID, unpaid
from test_settlement_late_charge_reduction_migration import command as charge_reduction
from test_settlement_late_charge_reduction_migration import record as record_charge_reduction
from test_settlement_late_charge_refund_migration import pay_charge
from test_settlement_payment_move_credit_migration import (
    allocate,
    close_other_line_paid,
    paid_by,
    two_leases,
)
from test_settlement_payment_move_migration import (
    REASON,
    REVERSED,
    SOURCE_ACK,
    TARGET_ACK,
    cause,
    command,
    draft_count,
    draft_of,
    drafts,
    hand_built_move_draft,
    moves,
    reconciled,
    record,
    state,
    wrong_at_closure,
)
from test_settlement_payment_move_migration import close as close_owing
from test_settlement_payment_move_migration import confirm as confirm_move
from test_settlement_real_path_migration import extra_charge_line
from test_settlement_refund_correction_migration import apply_credit, available, unpaid_charge
from test_settlement_refund_correction_migration import confirm as confirm_refund_correction
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import record as record_refund_correction
from test_settlement_returned_payment_migration import closed_case as returned_payment_case

REVISION = "20270108_165"
SLICE_7_SOURCE = "app.payment_move_source(uuid,uuid,uuid)"
INTERNAL = (
    "app.closed_settlements_relying_on_allocation(uuid)",
    "app.closed_settlements_relying_on_credit_application(uuid)",
    "app.refuse_relied_on_allocation_reversal()",
    "app.refuse_relied_on_credit_application_reversal()",
)
TRIGGERS = {
    "app.payment_allocation_reversals:a0_payment_allocation_reversals_relied_on",
    "app.customer_credit_application_reversals:a1_customer_credit_application_reversals_relied_on",
}
CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
RELIED_ON = (
    "A closed Final Settlement relied on this allocation; move it through a correction of that "
    "Final Settlement"
)


def settled(url: str) -> dict[str, Any]:
    """Two Leases on two Units (sub-slice 10g). Before the closure a Payment of the first Lease's
    Customer pays the whole 12,500 of the first Lease's other damage line, and the Customer's 400
    Credit pays 400 of the pet damage line by an ordinary designated application; the first
    Lease's Final Settlement then closes for real: the Pet Deposit pays the pet damage line's
    12,100 rest and both Deposits' rests are refunded. The second Lease's other damage line
    (12,500) stays open."""
    first, second = two_leases(url)
    payment = paid_by(first, 12_500)
    wrong = allocate(first, payment, "other_line", 12_500)
    applied = apply_credit(
        first, first["credit"], invoice_of(url, first["pet_line"]), first["pet_line"], 400
    )
    assert outstanding(url, first["pet_line"]) == 12_100
    close_other_line_paid(first, ())
    return {"first": first, "second": second, "wrong": wrong, "applied": applied}


def reversals_of(url: str, table: str, column: str, record_id: UUID) -> int:
    return int(value(url, f"SELECT count(*) FROM app.{table} WHERE {column}=%s", record_id))


def test_an_allocation_the_settlement_relied_on_is_not_reversed_or_moved_outside_a_correction(
    migrated_database_url: str,
) -> None:
    """The 12,500 allocation the closure saw paid: its one-call reversal is refused as a conflict
    and writes nothing, so the line cannot owe again and a charge reduction still refuses to
    release its paid value (the 10c-1a path); the slice 7 move draft is refused at record, and a
    hand-built waiting one at confirm (it stays pending), and points to the correction, which
    still records the move."""
    url = migrated_database_url
    found = settled(url)
    first, second, wrong = found["first"], found["second"], found["wrong"]
    prop, human, line = first["prop"], first["human"], first["other_line"]
    assert outstanding(url, line) == 0
    with pytest.raises(AllocationConflictError) as one_call:
        allocations().reverse_allocation(
            prop,
            wrong,
            ReverseAllocationCommand(uuid4(), "Posted on the wrong Lease"),
            actor=allocation_actor(human, prop),
        )
    assert str(one_call.value) == CLOSED
    assert cause(one_call) == ("P5S01", CLOSED)
    assert reversals_of(url, "payment_allocation_reversals", "payment_allocation_id", wrong) == 0
    assert outstanding(url, line) == 0
    with pytest.raises(FinalSettlementConflictError) as reduced:
        record_reduction(first, reduction(first["settlement"], invoice_of(url, line), line, 100))
    assert cause(reduced) == ("55000", RELEASE)
    target = invoice_of(url, second["other_line"])
    before = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as slice_7:
        moves().record(
            prop,
            RecordPaymentMoveCommand(uuid4(), wrong, target, REASON, SOURCE_ACK, TARGET_ACK),
            actor=person(human, prop, "payments.allocations.reverse"),
        )
    assert cause(slice_7) == ("55000", RELIED_ON)
    assert draft_count(url) == before
    # Review round 1 (note): the slice 7 confirm refuses a waiting draft of the same allocation
    # too; only a hand-built draft reaches it, and it stays pending.
    mover = person(human, prop, "payments.allocations.reverse")
    waiting = hand_built_move_draft(first, wrong, target)
    with pytest.raises(PaymentMoveConflictError) as at_confirm:
        moves().confirm(prop, waiting, actor=person(first["person"], prop, "financial.approve"))
    assert cause(at_confirm) == ("55000", RELIED_ON)
    assert state(url, waiting) == "PENDING"
    drafts().withdraw(
        prop,
        waiting,
        "Moved through the correction",
        prepare_capability="payments.allocations.reverse",
        actor=mover,
    )
    recorded = record(first, command(first["settlement"], wrong, target))
    assert (recorded["state"], draft_count(url)) == ("PENDING", before + 2)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, first["customer"])


def test_a_credit_application_the_settlement_relied_on_is_not_reversed_with_one_call(
    migrated_database_url: str,
) -> None:
    """The ordinary 400 Credit application on the pet damage line, made before the closure, is
    not a Final Settlement application, but the closure relied on it: its one-call reversal is
    refused with the closed-Settlement text and writes nothing."""
    url = migrated_database_url
    found = settled(url)
    first, applied = found["first"], found["applied"]
    prop, human = first["prop"], first["human"]
    assert (available(url, first["credit"]), outstanding(url, first["pet_line"])) == (0, 0)
    with pytest.raises(CreditConflictError) as one_call:
        credits().reverse_application(
            prop,
            applied,
            ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
            actor=credit_actor(human, prop, "credits.applications.reverse"),
        )
    assert str(one_call.value) == CLOSED
    assert cause(one_call) == ("P5S01", CLOSED)
    assert (
        reversals_of(url, "customer_credit_application_reversals", "credit_application_id", applied)
        == 0
    )
    assert (available(url, first["credit"]), outstanding(url, first["pet_line"])) == (0, 0)


def test_a_late_payment_charge_paid_at_closure_stays_paid(
    migrated_database_url: str,
) -> None:
    """The overdue two-Signer Lease (sub-slice 8c): before the closure the Primary Tenant pays
    the whole 8,000 Late-payment Charge directly; the closure relies on that allocation. Its
    one-call reversal is refused and writes nothing, so a charge reduction of the Charge still
    refuses to release paid value (the 10c-3a path)."""
    url = migrated_database_url
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    allocation = pay_charge(case, 8_000)
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    prop, human, charge = case["prop"], case["human"], case["charge"]
    assert unpaid(url, charge) == 0
    with pytest.raises(AllocationConflictError) as one_call:
        allocations().reverse_allocation(
            prop,
            allocation,
            ReverseAllocationCommand(uuid4(), "Paid on the wrong Charge"),
            actor=allocation_actor(human, prop),
        )
    assert cause(one_call) == ("P5S01", CLOSED)
    assert (
        reversals_of(url, "payment_allocation_reversals", "payment_allocation_id", allocation) == 0
    )
    assert unpaid(url, charge) == 0
    with pytest.raises(FinalSettlementConflictError) as reduced:
        record_charge_reduction(case, charge_reduction(case, 1_000))
    assert cause(reduced) == ("55000", RELEASES_PAID)


def test_an_adjustment_reversal_correction_s_put_back_is_not_reversed_with_one_call(
    migrated_database_url: str,
) -> None:
    """The owner note of 2026-10-16 on the 10f-2 report: the ADJUSTMENT_REVERSAL correction puts
    the Signer's 400 back on the Adjustment's line after the closure, linked to the correction,
    with no Final Settlement on the row. Its one-call reversal is refused, so the line keeps what
    the correction restored."""
    url = migrated_database_url
    case = closed_case(url, signer_paid=1_000, credit_used=0)
    prop, human, credit = case["prop"], case["human"], case["credit"]
    adjustment, _invoice, line = lease_adjustment(url, case["lease"])
    result = confirm_adjustment_reversal(
        case, adjustment_reversal_draft(record_adjustment_reversal(case, adjustment))
    )
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    application = UUID(str(put_back["credit_application_id"]))
    assert (available(url, credit), outstanding(url, line)) == (0, 0)
    assert (
        value(
            url,
            "SELECT final_settlement_id FROM app.customer_credit_applications WHERE id=%s",
            application,
        )
        is None
    )
    with pytest.raises(CreditConflictError) as one_call:
        credits().reverse_application(
            prop,
            application,
            ReverseCreditApplicationCommand(uuid4(), "Applied to the wrong line"),
            actor=credit_actor(human, prop, "credits.applications.reverse"),
        )
    assert cause(one_call) == ("P5S01", CLOSED)
    assert (
        reversals_of(
            url, "customer_credit_application_reversals", "credit_application_id", application
        )
        == 0
    )
    assert (available(url, credit), outstanding(url, line)) == (0, 0)


def test_an_allocation_a_move_correction_wrote_on_the_open_lease_changes_only_through_it(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-17-120 point 2: the first Settlement's PAYMENT_MOVE correction moves 1,000 onto
    the second Lease's other damage line, whose Settlement is still open. The new allocation is
    linked to the first Settlement's correction, so its one-call reversal, an ordinary credit
    Adjustment of 12,000 on that line (which would release 500 of it as Credit) and a slice 7 move
    draft of it are each refused and write nothing; so is a slice 7 move draft of the wrong
    allocation the correction reversed after the closure."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    prop, human, line = first["prop"], first["human"], second["other_line"]
    recorded = record(first, command(first["settlement"], found["allocation"], found["target"]))
    move = cast(dict[str, Any], confirm_move(first, draft_of(recorded))["move"])
    moved = UUID(str(move["target_allocation_id"]))
    assert outstanding(url, line) == 11_500
    # Review round 2 (independent S-1): the wrong allocation, reversed by the correction after
    # the closure, is still one the first Settlement relied on, so the slice 7 two-step move of
    # it is refused too and writes nothing.
    before = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as reversed_after:
        moves().record(
            prop,
            RecordPaymentMoveCommand(
                uuid4(), found["allocation"], found["target"], REASON, SOURCE_ACK, TARGET_ACK
            ),
            actor=person(human, prop, "payments.allocations.reverse"),
        )
    assert cause(reversed_after) == ("55000", RELIED_ON)
    assert draft_count(url) == before
    with pytest.raises(AllocationConflictError) as one_call:
        allocations().reverse_allocation(
            prop,
            moved,
            ReverseAllocationCommand(uuid4(), "Undo the move"),
            actor=person(human, prop, "payments.allocations.reverse"),
        )
    assert cause(one_call) == ("P5S01", CLOSED)
    invoice = found["target"]
    version = int(value(url, "SELECT version FROM app.invoices WHERE id=%s", invoice))
    with pytest.raises(InvoiceConflictError) as adjusted:
        invoices().adjust(
            prop,
            invoice,
            AdjustInvoiceCommand(
                uuid4(),
                line,
                AdjustmentType.CREDIT,
                12_000,
                f"approved-credit/{uuid4()}",
                "Approved credit",
                version,
            ),
            actor=invoice_api_actor(human, prop),
        )
    assert cause(adjusted) == ("P5S01", CLOSED)
    adjustments = "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_line_id=%s"
    assert int(value(url, adjustments, line)) == 0
    before = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as slice_7:
        moves().record(
            prop,
            RecordPaymentMoveCommand(
                uuid4(),
                moved,
                invoice_of(url, first["other_line"]),
                REASON,
                SOURCE_ACK,
                TARGET_ACK,
            ),
            actor=person(human, prop, "payments.allocations.reverse"),
        )
    assert cause(slice_7) == ("55000", RELIED_ON)
    assert draft_count(url) == before
    assert reversals_of(url, "payment_allocation_reversals", "payment_allocation_id", moved) == 0
    assert outstanding(url, line) == 11_500


def test_another_lease_s_refund_correction_cannot_release_an_allocation_a_move_correction_wrote(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S3, security should-fix 2; Q-2026-10-17-120 point 2), on the
    security reviewer's set-up with the second Lease closed first: both Settlements close for
    real; an EXTRA_CHARGE correction of the second Settlement bills 1,500 after its closure; the
    first Settlement's PAYMENT_MOVE correction moves the 1,000 onto that charge, which then owes
    500. A REFUND correction of the second Settlement of 1,500 on that charge would release the
    moved 1,000 (the paid value), which the first Settlement's correction wrote: its confirm is
    refused (P5S01), the draft stays pending and nothing is written."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    close_owing(second, 12_500)
    invoice, line = unpaid_charge(url, second, second["person"])
    recorded = record(first, command(first["settlement"], found["allocation"], invoice))
    move = cast(dict[str, Any], confirm_move(first, draft_of(recorded))["move"])
    moved = UUID(str(move["target_allocation_id"]))
    assert outstanding(url, line) == 500
    draft = record_refund_correction(second, refund_correction(second, invoice, line, 1_500))
    with pytest.raises(FinalSettlementConflictError) as refused:
        confirm_refund_correction(second, second["person"], draft)
    assert cause(refused) == ("P5S01", CLOSED)
    # Review round 3 (independent note 2): the 8e-1 refusal has the same code and text, so the
    # refusal's context shows it came from the 10h-1 allocation trigger.
    context = cast(psycopg.Error, refused.value.__cause__).diag.context
    assert "app.refuse_relied_on_allocation_reversal()" in str(context)
    assert state(url, draft) == "PENDING"
    assert reversals_of(url, "payment_allocation_reversals", "payment_allocation_id", moved) == 0
    adjustments = "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_line_id=%s"
    assert int(value(url, adjustments, line)) == 0
    assert outstanding(url, line) == 500
    reconciled(url, first["customer"], second["customer"])


def test_an_allocation_reversed_before_the_closure_keeps_the_slice_7_move(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S1): a Settlement did not rely on an allocation reversed before
    its closure. The 500 allocation reversed with one call before the closure left its value on
    the Payment; after the closure the PAYMENT_MOVE correction refuses it, and the slice 7 move
    draft still records and confirms its move to the second Lease's line (the two-step move,
    owner answer 5 to Q-2026-10-05-16)."""
    url = migrated_database_url
    found = wrong_at_closure(url, reversed_before=True)
    first, second = found["first"], found["second"]
    prop, human, earlier, target = first["prop"], first["human"], found["reversed"], found["target"]
    with pytest.raises(PaymentMoveConflictError) as correction:
        record(first, command(first["settlement"], earlier, target))
    assert cause(correction) == ("55000", REVERSED)
    plain = moves().record(
        prop,
        RecordPaymentMoveCommand(uuid4(), earlier, target, REASON, SOURCE_ACK, TARGET_ACK),
        actor=person(human, prop, "payments.allocations.reverse"),
    )
    assert plain["state"] == "PENDING"
    result = moves().confirm(
        prop, draft_of(plain), actor=person(first["person"], prop, "financial.approve")
    )
    move = cast(dict[str, Any], result["move"])
    assert (move["moved_usd_cents"], move["source_reversed_by_move"]) == (500, False)
    assert outstanding(url, second["other_line"]) == 12_000
    reconciled(url, first["customer"], second["customer"])


def test_records_made_after_the_closure_still_reverse_with_one_call(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-06-36: records made after the closure and not linked to a
    correction are not ones the Settlement relied on. After the closure the Customer's 10,000
    Payment becomes Credit (nothing is owed yet), then a Payment of 30,000 and that Credit pay a
    40,000 EXTRA_CHARGE Invoice of the closed Lease; both one-call reversals still pass, and the
    40,000 is owed again."""
    url = migrated_database_url
    case = returned_payment_case(url)
    prop, human = case["prop"], case["human"]
    credit = credit_id(recognize(prop, customer_payment(case, 10_000), human, 10_000))
    line = extra_charge_line(case, amount_usd_cents=40_000)
    allocation = allocate_line(case, customer_payment(case, 30_000), line, 30_000)
    applied = application_id(
        credits().apply(
            prop,
            credit,
            designated_credit(invoice_of(url, line), line, 10_000),
            actor=credit_actor(human, prop, "credits.apply"),
        )
    )
    assert outstanding(url, line) == 0
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Posted on the wrong Invoice"),
        actor=person(human, prop, "payments.allocations.reverse"),
    )
    credits().reverse_application(
        prop,
        applied,
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert (
        reversals_of(url, "payment_allocation_reversals", "payment_allocation_id", allocation) == 1
    )
    assert (
        reversals_of(url, "customer_credit_application_reversals", "credit_application_id", applied)
        == 1
    )
    assert (outstanding(url, line), available(url, credit)) == (40_000, 10_000)
    reconciled(url, case["customer"])


def test_the_relied_on_refusals_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The new functions have no grant and the definer settings; the two triggers are row-level
    BEFORE INSERT triggers that run before the insert check (the Credit one after the 8e-2 and
    10c-1b refusals); the migration adds only them, changes only the slice 7 move source (which
    keeps its owner, privileges and settings) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
            assert connection.execute(
                "SELECT prosecdef,proconfig::text FROM pg_catalog.pg_proc "
                "WHERE oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "{search_path=pg_catalog}"), function
        triggers = connection.execute(
            "SELECT t.tgrelid::regclass::text || ':' || t.tgname,(t.tgtype & 1)=1,"
            "(t.tgtype & 2)=2,(t.tgtype & 4)=4,t.tgenabled FROM pg_catalog.pg_trigger t "
            "WHERE t.tgname IN ('a0_payment_allocation_reversals_relied_on',"
            "'a1_customer_credit_application_reversals_relied_on') ORDER BY 1"
        ).fetchall()
        # Review round 1 (note): BEFORE INSERT triggers run in name order, so each new one runs
        # before the insert check, and the Credit one after the 8e-2 and 10c-1b refusals.
        order = connection.execute(
            "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
            "WHERE t.tgrelid IN ('app.payment_allocation_reversals'::regclass,"
            "'app.customer_credit_application_reversals'::regclass) AND NOT t.tgisinternal "
            'AND (t.tgtype & 7)=7 ORDER BY 1,t.tgname COLLATE "C"'
        ).fetchall()
    assert {row[0] for row in triggers} == TRIGGERS
    # FOR EACH ROW, BEFORE, INSERT and enabled.
    assert all(row[1:] == (True, True, True, "O") for row in triggers)
    assert order == [
        ("app.customer_credit_application_reversals", name)
        for name in (
            "a0_customer_credit_application_reversals_final_settlement",
            "a0_customer_credit_application_reversals_settlement_remainder",
            "a1_customer_credit_application_reversals_relied_on",
            "customer_credit_application_reversals_validate",
        )
    ] + [
        ("app.payment_allocation_reversals", name)
        for name in (
            "a0_payment_allocation_reversals_relied_on",
            "payment_allocation_reversals_validate",
        )
    ]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270107_164"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
            structure = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT c.oid::regclass::text,c.relacl::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            } | {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT con.conrelid::regclass::text,con.conname,"
                    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace "
                    "WHERE n.nspname='app'"
                ).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_relied_on_reversals") as temporary:
        alembic_command.upgrade(config, "20270107_164")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {SLICE_7_SOURCE}
    # Owner, privileges, definer and settings stay; only the body changes.
    assert after_functions[SLICE_7_SOURCE][1:] == before_functions[SLICE_7_SOURCE][1:]
    body = str(after_functions[SLICE_7_SOURCE][0])
    assert "app.closed_settlements_relying_on_allocation(p_allocation)" in body
    assert "app.wrong_unit_move_source(p_property,p_allocation,p_target_invoice,false)" in body
    assert after_triggers - before_triggers == TRIGGERS
    assert before_triggers <= after_triggers
    assert after_structure == before_structure
