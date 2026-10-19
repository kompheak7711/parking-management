"""The Final Settlement preview's waiting drafts (V1-056 sub-slice 10h-3).

Owner answer (a) to Q-2026-10-17-120 point 3 (BR-SETTLE-002, BR-SETTLE-012, BR-SETTLE-013,
BR-PAY-042, DL-032): the preview's pending-draft check also lists another Lease's waiting
PAYMENT_MOVE correction draft whose correct Invoice is on the Lease, a waiting Payment return
draft whose Payment has an active record on the Lease's sources (an allocation on its
obligations, a Credit held by a Lease person, a Credit application on its obligations, or a
receipt into one of its Deposits), and a waiting Adjustment reversal draft of an Adjustment on an
Invoice of the Lease. While one waits the Settlement is neither recorded nor confirmed, and a
closed Settlement takes no correction step.
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

from payment_test_support import seed_payment
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from test_adjustment_reversal_migration import preparer as reversal_preparer
from test_adjustment_reversal_migration import request as reversal_request
from test_adjustment_reversal_migration import reversals
from test_credit_migration import credit_id, recognize
from test_final_settlement_confirm_migration import BLOCKED, invoice_of, this_month
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import state as settlement_state
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    leaving_case,
    refusal,
    two_signer_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import outstanding
from test_final_settlement_preview_migration import (
    APPROVE,
    HIDDEN,
    issues,
    pay,
    person,
    preview,
    shown,
)
from test_migrations import _temporary_migration_database
from test_payment_move_migration import rows, value
from test_payment_return_migration import drafts, returns
from test_payment_return_migration import preparer as return_preparer
from test_payment_return_migration import request as return_request
from test_reservation_migration import migrated_database_url as migrated_database_url
from test_settlement_extra_charge_migration import cause
from test_settlement_late_charge_refund_migration import command as charge_refund
from test_settlement_late_charge_refund_migration import pay_charge, pay_other_debt, settled_case
from test_settlement_late_charge_refund_migration import record as record_charge_refund
from test_settlement_payment_move_migration import command as move_command
from test_settlement_payment_move_migration import record as record_move
from test_settlement_payment_move_migration import wrong_at_closure
from test_settlement_returned_payment_migration import command as returned_command
from test_settlement_returned_payment_migration import record as record_returned
from test_settlement_returned_payment_migration import two_settlements_case

REVISION = "20270111_168"
PREVIEW = "app.final_settlement_preview(uuid,uuid,uuid,text[])"
WAITING = "A draft on a source of this Final Settlement is waiting"
SETTLEMENT_DRAFTS = "SELECT count(*) FROM app.financial_drafts WHERE kind='FINAL_SETTLEMENT'"
# Relations and their privileges, constraints, and table columns of the app schema.
STRUCTURE = (
    "SELECT c.oid::regclass::text,c.relacl::text FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')",
    "SELECT con.conrelid::regclass::text,con.conname,"
    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace WHERE n.nspname='app'",
    "SELECT a.attrelid::regclass::text,a.attname,"
    "pg_catalog.format_type(a.atttypid,a.atttypmod) FROM pg_catalog.pg_attribute a "
    "JOIN pg_catalog.pg_class c ON c.oid=a.attrelid "
    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='app' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped",
)


def close_plan(case: dict[str, Any], owed: int) -> tuple[Any, ...]:
    """The closure of sub-slice 10g's close(): Credit 400, the Pet Deposit pays the pet damage line,
    the Security Deposit and the Pet Deposit's rest pay the other damage line, and the rest of the
    Pet Deposit is refunded."""
    rest = owed - 10_400
    return (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], rest),
        settlement_refund(case, "pet", 7_500 - rest),
    )


def withdraw(case: dict[str, Any], draft: object, capability: str) -> None:
    drafts().withdraw(
        case["prop"],
        UUID(str(draft)),
        "Recorded by mistake",
        prepare_capability=capability,
        actor=person(case["human"], case["prop"], capability),
    )


def no_variant(draft: dict[str, object], kind: str) -> dict[str, object]:
    """The shown issue of a draft kind whose payload has no variant."""
    return {**shown(draft, kind, ""), "variant": None}


def blocked_only_by(case: dict[str, Any], issue: dict[str, object]) -> None:
    """The waiting draft is the preview's only blocking issue (review round 1)."""
    view = preview(case["prop"], case["human"], case["settlement"], APPROVE)
    assert view["ready"] is False and view["blocking_issues"] == [issue]


def ready_again(case: dict[str, Any]) -> None:
    """After the withdrawal nothing blocks the Settlement (review round 1)."""
    view = preview(case["prop"], case["human"], case["settlement"], APPROVE)
    assert view["ready"] is True and view["blocking_issues"] == []


def records(url: str, payment: object) -> tuple[int, int, int]:
    """The Payment's active allocations, active Customer Credits and active Deposit receipts."""
    found = rows(
        url,
        "SELECT (SELECT count(*) FROM app.payment_allocations allocation WHERE "
        "allocation.payment_id=%s AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals "
        "reversal WHERE reversal.payment_allocation_id=allocation.id)),"
        "(SELECT count(*) FROM app.customer_credits credit WHERE credit.source_payment_id=%s "
        "AND NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal "
        "WHERE reversal.customer_credit_id=credit.id)),"
        "(SELECT count(*) FROM app.deposit_receipts receipt WHERE receipt.payment_id=%s "
        "AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal "
        "WHERE reversal.deposit_receipt_id=receipt.id))",
        payment,
        payment,
        payment,
    )
    return (int(found[0][0]), int(found[0][1]), int(found[0][2]))


def pending(case: dict[str, Any], *capabilities: str) -> list[dict[str, Any]]:
    view = preview(case["prop"], case["human"], case["settlement"], *capabilities)
    return issues(view, "PENDING_DRAFT")


def test_a_waiting_move_correction_blocks_the_lease_of_its_correct_invoice(
    migrated_database_url: str,
) -> None:
    """The first Lease is closed and relied on a 1,000 allocation meant for the second Lease's
    damage line. While the first Settlement's PAYMENT_MOVE correction draft waits, the second
    Lease's preview lists it as its only blocking issue (to an approver and to a
    final_settlements.prepare holder, the draft's preparer capability), the second Settlement
    draft is not recorded, and one recorded before the correction is refused at its confirm and
    stays pending with nothing written; after the withdrawal nothing blocks and it confirms."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    owed = outstanding(url, second["other_line"])
    # While the correction waits, the second Settlement draft is not recorded (review round 1).
    early = record_move(
        first, move_command(first["settlement"], found["allocation"], found["target"])
    )
    blocked_only_by(second, shown(early, "SETTLEMENT_CORRECTION", "PAYMENT_MOVE"))
    before = rows(url, SETTLEMENT_DRAFTS)
    assert refusal(record_settlement, second, close_plan(second, owed), pet_remainder=STAFF) == (
        "55000",
        BLOCKED,
    )
    assert rows(url, SETTLEMENT_DRAFTS) == before
    withdraw(first, early["draft_id"], "final_settlements.prepare")
    settlement_draft = record_settlement(second, close_plan(second, owed), pet_remainder=STAFF)
    correction = record_move(
        first, move_command(first["settlement"], found["allocation"], found["target"])
    )
    issue = shown(correction, "SETTLEMENT_CORRECTION", "PAYMENT_MOVE")
    blocked_only_by(second, issue)
    assert pending(second) == [issue]
    assert pending(first, APPROVE) == []
    assert refusal(confirm_settlement, second, settlement_draft) == ("55000", BLOCKED)
    assert settlement_state(url, settlement_draft) == "PENDING"
    assert (
        value(url, "SELECT closed_at FROM app.final_settlements WHERE id=%s", second["settlement"])
        is None
    )
    assert outstanding(url, second["other_line"]) == owed
    withdraw(first, correction["draft_id"], "final_settlements.prepare")
    ready_again(second)
    confirm_settlement(second, settlement_draft)
    assert settlement_state(url, settlement_draft) == "CONFIRMED"


def test_a_waiting_payment_return_blocks_the_closure_through_each_record_of_the_lease(
    migrated_database_url: str,
) -> None:
    """A Payment return draft blocks the preview and the Settlement record (55000, nothing
    written) while its Payment has an allocation on the Lease's damage line, a Credit held by the
    Customer of the Lease (recognized from a Payment confirmed for the paid Rent Invoice), or a
    receipt into the Lease's Security Deposit (each Payment has only that one record); the draft
    is the only blocking issue, and its identity is shown to an approver and a payments.reverse
    holder only; each withdrawal unblocks it. A return draft of the Customer's unallocated
    Payment, which has no record on the Lease, does not block."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    prop, human, customer = case["prop"], case["human"], case["customer"]
    allocated = pay(
        url, prop, human, customer, invoice_of(url, case["other_line"]), case["other_line"], 1_000
    )
    [(rent_invoice,)] = rows(
        url,
        "SELECT DISTINCT allocation.invoice_id FROM app.payment_allocations allocation "
        "JOIN app.customer_credits credit ON credit.source_payment_id=allocation.payment_id "
        "WHERE credit.id=%s AND allocation.invoice_id IS NOT NULL",
        case["credit"],
    )
    with psycopg.connect(url) as connection:
        credited = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=500,
            invoice_id=UUID(str(rent_invoice)),
        )
        unallocated = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=300
        )
    credit = credit_id(recognize(prop, credited, human, 500))
    assert value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == (
        customer
    )
    [(receipt_payment,)] = rows(
        url,
        "SELECT DISTINCT payment_id FROM app.deposit_receipts WHERE deposit_id=%s",
        case["security"],
    )
    # Each Payment reaches the Lease through one record only (review round 1).
    assert [records(url, payment) for payment in (allocated, credited, receipt_payment)] == [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
    ]
    for payment in (allocated, credited, UUID(str(receipt_payment))):
        draft = returns().record(prop, return_request(payment), actor=return_preparer(human, prop))
        issue = no_variant(draft, "PAYMENT_RETURN")
        blocked_only_by(case, issue)
        assert pending(case) == [HIDDEN]
        assert pending(case, "final_settlements.prepare", "payments.reverse") == [issue]
        before = rows(url, SETTLEMENT_DRAFTS)
        assert refusal(record_settlement, case, ()) == ("55000", BLOCKED)
        assert rows(url, SETTLEMENT_DRAFTS) == before
        withdraw(case, draft["draft_id"], "payments.reverse")
        ready_again(case)
    returns().record(prop, return_request(unallocated), actor=return_preparer(human, prop))
    ready_again(case)


def test_a_waiting_adjustment_reversal_draft_blocks_only_its_own_lease(
    migrated_database_url: str,
) -> None:
    """A 10f-1 reversal draft of the two-Signer Lease's credit Adjustment blocks that Lease's
    preview (its only blocking issue; its identity shown to an approver and an invoices.adjust
    holder only) and Settlement record (55000) and is not listed by another Lease's preview; its
    withdrawal unblocks it."""
    url = migrated_database_url
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    other = leaving_case(url)
    prop, human = case["prop"], case["human"]
    [(adjustment,)] = rows(
        url,
        "SELECT a.id FROM app.invoice_adjustments a JOIN app.invoices i ON i.id=a.invoice_id "
        "WHERE i.lease_id=%s AND a.adjustment_type='CREDIT'",
        case["lease"],
    )
    draft = reversals().record(
        prop, reversal_request(UUID(str(adjustment))), actor=reversal_preparer(human, prop)
    )
    issue = no_variant(draft, "ADJUSTMENT_REVERSAL")
    blocked_only_by(case, issue)
    assert pending(case) == [HIDDEN]
    assert pending(case, "final_settlements.prepare", "invoices.adjust") == [issue]
    assert pending(other, APPROVE) == []
    assert refusal(record_settlement, case, ()) == ("55000", BLOCKED)
    withdraw(case, draft["draft_id"], "invoices.adjust")
    ready_again(case)


def test_after_closure_a_waiting_return_draft_holds_the_settlement_s_corrections(
    migrated_database_url: str,
) -> None:
    """After the closure the Primary Tenant pays the 8,000 Late-payment Charge; while the return
    draft of that Payment waits (owner answer (a) to Q-2026-10-19-140 keeps it), the closed
    Settlement's Late-payment Charge REFUND correction is refused (55000, the pending-draft rule
    of every correction plan) with nothing written; after the withdrawal it is recorded."""
    url = migrated_database_url
    case = settled_case(url)
    prop, human = case["prop"], case["human"]
    pay_other_debt(case)
    allocation = pay_charge(case, 8_000)
    [(payment,)] = rows(
        url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", allocation
    )
    draft = returns().record(
        prop, return_request(UUID(str(payment))), actor=return_preparer(human, prop)
    )
    before = rows(url, "SELECT count(*) FROM app.financial_drafts")
    with pytest.raises(FinalSettlementConflictError) as waiting:
        record_charge_refund(case, charge_refund(case, 3_000))
    assert cause(waiting) == ("55000", WAITING)
    assert rows(url, "SELECT count(*) FROM app.financial_drafts") == before
    withdraw(case, draft["draft_id"], "payments.reverse")
    record_charge_refund(case, charge_refund(case, 3_000))


def test_a_waiting_returned_payment_correction_blocks_the_other_lease_of_its_payment(
    migrated_database_url: str,
) -> None:
    """Review round 2 (security should-fix 1): one Payment of the first Lease's Customer pays
    1,000 of the first Lease's damage line, which its closed Settlement relied on, and (moved by a
    confirmed wrong-Unit move) 1,000 of the open second Lease's damage line. While the first
    Settlement's RETURNED_PAYMENT correction of that Payment waits, the second Lease's preview
    lists it as its only blocking issue and its Settlement draft is not recorded (55000, nothing
    written); the first Lease's own preview does not list it, so its own corrections are not held;
    after the withdrawal nothing blocks the second Lease."""
    url = migrated_database_url
    found = two_settlements_case(url, close_second=False)
    first, second, payment = found["first"], found["second"], found["payment"]
    draft = record_returned(first, returned_command(first, payment))
    issue = shown({"draft_id": str(draft)}, "SETTLEMENT_CORRECTION", "RETURNED_PAYMENT")
    blocked_only_by(second, issue)
    assert pending(second) == [issue]
    assert pending(first, APPROVE) == []
    before = rows(url, SETTLEMENT_DRAFTS)
    owed = outstanding(url, second["other_line"])
    assert refusal(record_settlement, second, close_plan(second, owed), pet_remainder=STAFF) == (
        "55000",
        BLOCKED,
    )
    assert rows(url, SETTLEMENT_DRAFTS) == before
    withdraw(first, draft, "final_settlements.prepare")
    ready_again(second)


def test_the_waiting_drafts_check_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the preview's body (its owner, privileges, definer flag and
    settings stay), adds no function, trigger, table, column or constraint, and is
    forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270110_167"
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
                f"{index}:" + ":".join(str(item) for item in row)
                for index, query in enumerate(STRUCTURE)
                for row in connection.execute(query).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_preview_waiting_drafts") as temporary:
        alembic_command.upgrade(config, "20270110_167")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PREVIEW}
    # Owner, privileges, definer and settings stay; only the body changes.
    assert after_functions[PREVIEW][1:] == before_functions[PREVIEW][1:]
    body = str(after_functions[PREVIEW][0])
    for branch in (
        "draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='PAYMENT_MOVE'",
        "OR ((draft.kind='PAYMENT_RETURN'",
        "draft.kind='SETTLEMENT_CORRECTION' AND draft.payload->>'variant'='RETURNED_PAYMENT'",
        "draft.payload->>'final_settlement_id' IS DISTINCT FROM p_settlement::text",
        "draft.kind='ADJUSTMENT_REVERSAL' AND draft.payload->>'invoice_adjustment_id' IN (",
        # The Deposit branch keeps its three earlier kinds (review round 2).
        "AND ((draft.kind IN ('REFUND','DEPOSIT_FORFEITURE','PAYMENT_MOVE')\n"
        "                      AND draft.payload->>'deposit_id' IN (",
    ):
        assert body.count(branch) == 1, branch
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
