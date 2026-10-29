"""Post-settlement correction: PAYMENT_MOVE (V1-056 sub-slice 10g).

Owner answer 4 to Q-2026-10-06-36 and answers 1 and 5 to Q-2026-10-06-37: after the Lease's Final
Settlement is closed, a wrong-Unit allocation that the Settlement relied on is moved only inside a
correction of that Settlement, prepared under final_settlements.prepare and confirmed only by
financial.approve (BR-PAY-042, BR-SETTLE-013, BR-AUTH-010). The confirm writes the slice 7 move,
the reversal and the new allocation linked to the correction; the debt comes back on the
Settlement obligation and stays with its Customer (BR-SETTLE-016), and what the correct Invoice
does not take stays on the Payment. A record that another closed Settlement relied on changes only
through that Settlement's own correction.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.financial_draft import FinancialDraftService
from property_rental.payment_allocation import AllocationConflictError, ReverseAllocationCommand
from property_rental.payment_move import (
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveKeyReused,
    PaymentMoveService,
    PaymentMoveStaleDraftError,
    RecordPaymentMoveCommand,
    RecordSettlementPaymentMoveCommand,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of, this_month
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
from test_final_settlement_migration import outstanding, preparer
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import allocation_ids, person, rows, value
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_correction_migration import settlement_row
from test_settlement_extra_charge_migration import approving

RECORD = (
    "app.record_settlement_payment_move_draft(uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text)"
)
CONFIRM = "app.confirm_settlement_payment_move(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_payment_move_source(uuid,uuid,uuid,uuid)",
    "app.settlement_payment_move_allowed(uuid,uuid,uuid,uuid,uuid)",
    "app.settlement_payment_move_result(uuid)",
)
PATCHED = {"app.validate_payment_move()"}
REVISION = "20261222_148"
REASON = "Paid on the first Lease's Parking by mistake; meant for the second Lease's Parking"
SOURCE_ACK = "Sok Dara (first Lease), 2026-10-16, in person at the office"
TARGET_ACK = "Chea Vanna (second Lease), 2026-10-16, by telephone"
WAITING = "A move draft for this allocation is already waiting"
OTHER_SETTLEMENT = (
    "A correction of another Final Settlement wrote this allocation; this correction cannot move it"
)
NOTHING_OWED = "The correct Invoice has nothing outstanding"
OTHER_LEASE = "The allocation does not pay an Invoice of this Final Settlement's Lease"
AFTER_CLOSURE = "An allocation made after the closure moves through the ordinary move draft"
REVERSED = "The allocation is already reversed"
OPEN = "A post-settlement correction needs a closed Final Settlement"
# Sub-slice 10h-1: the slice 7 move draft refuses an allocation a closed Settlement relied on.
RELIED_ON = (
    "A closed Final Settlement relied on this allocation; move it through a correction of that "
    "Final Settlement"
)
LINKS = ("payment_allocation_reversal_id", "payment_allocation_id")


def moves() -> PaymentMoveService:
    return PaymentMoveService(financial_database_url())


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def close(case: dict[str, Any], owed: int = 11_500) -> None:
    """The real closure (sub-slice 8e-3) of a Lease whose other damage line owes 11,500 (or
    owed): Credit 400, the Pet Deposit pays the pet damage line (12,500), the Security Deposit
    (10,000) and the rest of that line from the Pet Deposit (1,100) pay the other damage line, and
    the Pet Deposit's rest (6,400) is refunded."""
    assert outstanding(case["url"], case["other_line"]) == owed
    rest = owed - 10_400
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
                SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
                SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], rest),
                settlement_refund(case, "pet", 7_500 - rest),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = correction_approver(case["url"])


def pay(case: dict[str, Any], line: str, amount: int) -> UUID:
    """A Payment of the case's Customer of exactly amount, allocated to the named line."""
    url, prop, human = case["url"], case["prop"], case["human"]
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=case["customer"],
            amount=amount,
        )
    posted = allocations().post(
        prop,
        payment,
        designated(invoice_of(url, case[line]), case[line], amount),
        actor=allocation_actor(human, prop),
    )
    return allocation_ids(posted)[0]


def wrong_at_closure(url: str, *, reversed_before: bool = False) -> dict[str, Any]:
    """Two Leases on two Units. A Payment of the first Lease's Customer paid 1,000 of the first
    Lease's other damage line, but was meant for the second Lease's other damage line (12,500).
    The first Settlement then closes for real and relies on that allocation; the second Lease's
    Settlement stays open. With reversed_before, a second allocation of 500 on the same line is
    reversed by the one-call reversal before the closure."""
    first = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    second = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    allocation = pay(first, "other_line", 1_000)
    found: dict[str, Any] = {"first": first, "second": second, "allocation": allocation}
    if reversed_before:
        earlier = pay(first, "other_line", 500)
        allocations().reverse_allocation(
            first["prop"],
            earlier,
            ReverseAllocationCommand(uuid4(), "Posted twice"),
            actor=person(first["human"], first["prop"], "payments.allocations.reverse"),
        )
        found["reversed"] = earlier
    close(first)
    found["payment"] = UUID(
        str(value(url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", allocation))
    )
    found["target"] = invoice_of(url, second["other_line"])
    return found


def command(
    settlement: UUID, allocation: UUID, target: UUID, **changes: Any
) -> RecordSettlementPaymentMoveCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "settlement_id": settlement,
        "allocation_id": allocation,
        "target_invoice_id": target,
        "reason": REASON,
        "source_acknowledgement": SOURCE_ACK,
        "target_acknowledgement": TARGET_ACK,
        **changes,
    }
    return RecordSettlementPaymentMoveCommand(**values)


def record(case: dict[str, Any], request: RecordSettlementPaymentMoveCommand) -> dict[str, Any]:
    return moves().record_correction(
        case["prop"], request, actor=preparer(case["human"], case["prop"])
    )


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return moves().confirm_correction(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def draft_of(result: dict[str, Any]) -> UUID:
    return UUID(str(result["draft_id"]))


def hand_built_move_draft(case: dict[str, Any], allocation: UUID, target: UUID) -> UUID:
    """A waiting slice 7 move draft of an allocation a closed Settlement relied on, written by the
    owner connection through app.insert_financial_draft: since sub-slice 10h-1 the slice 7
    recorder refuses such an allocation, so only a hand-built draft reaches the checks that see a
    waiting or withdrawn slice 7 draft (as the owner answer to Q-2026-10-18-131 allowed). Its
    source and digest are the ones the recorder would store, from the slice 7 body
    app.wrong_unit_move_source (review round 1, independent S2 and security should-fix 1)."""
    draft = uuid4()
    payload = {
        "variant": "WRONG_UNIT_MOVE",
        "source_allocation_id": str(allocation),
        "target_invoice_id": str(target),
        "source_acknowledgement": SOURCE_ACK,
        "target_acknowledgement": TARGET_ACK,
    }
    with psycopg.connect(case["url"]) as connection:
        connection.execute(
            "WITH source AS (SELECT app.wrong_unit_move_source(%s,%s,%s,false) AS value) "
            "SELECT app.insert_financial_draft(%s,%s,%s,'PAYMENT_MOVE',"
            "'payments.allocations.reverse',%s||jsonb_build_object('source',source.value),"
            "'payment-move:'||encode(sha256(convert_to(source.value::text,'UTF8')),'hex'),%s) "
            "FROM source",
            (
                case["prop"],
                allocation,
                target,
                case["prop"],
                case["human"],
                draft,
                Jsonb(payload),
                REASON,
            ),
        )
    return draft


def cause(failure: pytest.ExceptionInfo[Exception]) -> tuple[Any, Any]:
    error = failure.value.__cause__
    assert isinstance(error, psycopg.Error)
    return error.sqlstate, error.diag.message_primary


def state(url: str, draft: UUID) -> str:
    """PENDING while no decision exists, otherwise the decision."""
    return str(
        value(
            url,
            "SELECT COALESCE((SELECT decision FROM app.financial_draft_decisions "
            "WHERE draft_id=%s),'PENDING')",
            draft,
        )
    )


def effect_links(url: str, correction: object) -> list[tuple[str, str]]:
    """Each effect's one link and its record, in order."""
    found = rows(
        url,
        f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
        correction,
    )
    linked = []
    for row in found:
        index = [item is not None for item in row].index(True)
        linked.append((LINKS[index], str(row[index])))
    return linked


def draft_count(url: str) -> int:
    return int(value(url, "SELECT count(*) FROM app.financial_drafts"))


def reconciled(url: str, *customers: UUID) -> None:
    with psycopg.connect(url) as connection:
        for customer in customers:
            assert_reconciled(connection, customer)


def test_a_wrong_allocation_the_settlement_relied_on_moves_through_a_correction(
    migrated_database_url: str,
) -> None:
    """The 1,000 allocation the closed Settlement relied on moves to the second Lease's line: the
    first Lease's line owes 1,000 again on its Customer's ledger, the second line owes 11,500, the
    reversal and the new allocation are linked to the correction, the closure snapshot is
    unchanged, Staff cannot confirm, a replay returns the same and the moved allocation still
    refuses the one-call reversal (slice 7)."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    prop, human, allocation = first["prop"], first["human"], found["allocation"]
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        0,
        12_500,
    )
    before = settlement_row(url, first["settlement"])
    recorded = record(first, command(first["settlement"], allocation, found["target"]))
    payload = cast(dict[str, Any], recorded["payload"])
    source = cast(dict[str, Any], payload["source"])
    assert (
        recorded["kind"],
        recorded["state"],
        recorded["prepare_capability"],
        payload["variant"],
        payload["lease_id"],
        payload["source_acknowledgement"],
        payload["target_acknowledgement"],
    ) == (
        "SETTLEMENT_CORRECTION",
        "PENDING",
        "final_settlements.prepare",
        "PAYMENT_MOVE",
        str(first["lease"]),
        SOURCE_ACK,
        TARGET_ACK,
    )
    assert (
        source["final_settlement_id"],
        source["payment_id"],
        source["source_invoice_id"],
        source["source_customer_id"],
        source["target_customer_id"],
        source["source_amount_usd_cents"],
        source["moved_usd_cents"],
        source["source_reversed"],
        [(item["invoice_line_id"], item["amount_usd_cents"]) for item in source["details"]],
    ) == (
        str(first["settlement"]),
        str(found["payment"]),
        str(invoice_of(url, first["other_line"])),
        str(first["customer"]),
        str(second["customer"]),
        1_000,
        1_000,
        False,
        [(str(second["other_line"]), 1_000)],
    )
    draft = draft_of(recorded)
    with pytest.raises(PaymentMoveAuthorizationError):
        moves().confirm_correction(prop, draft, actor=preparer(human, prop))
    # The database refuses a confirm under the preparer's capability (42501); nothing is written.
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as staff_confirm:
            connection.execute(
                "SELECT app.confirm_settlement_payment_move(%s,%s,%s,'final_settlements.prepare')",
                (prop, human, draft),
            )
        connection.rollback()
    assert (staff_confirm.value.sqlstate, staff_confirm.value.diag.message_primary) == (
        "42501",
        "Only financial.approve may confirm a post-settlement correction",
    )
    assert state(url, draft) == "PENDING"
    result = confirm(first, draft)
    assert "transaction_id" not in json.dumps(result)
    move = cast(dict[str, Any], result["move"])
    correction = cast(dict[str, Any], result["settlement_correction"])
    assert (
        move["source_allocation_id"],
        move["moved_usd_cents"],
        move["left_on_payment_usd_cents"],
        correction["final_settlement_id"],
        correction["reason"],
        correction["authorization_reference"],
    ) == (str(allocation), 1_000, 0, str(first["settlement"]), REASON, "financial.approve")
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        1_000,
        11_500,
    )
    assert effect_links(url, correction["id"]) == [
        ("payment_allocation_reversal_id", move["source_reversal_id"]),
        ("payment_allocation_id", move["target_allocation_id"]),
    ]
    assert rows(
        url,
        "SELECT draft_id,source_reversed_by_move,moved_usd_cents,source_acknowledgement,"
        "target_acknowledgement FROM app.payment_moves WHERE id=%s",
        move["payment_move_id"],
    ) == [(draft, True, 1_000, SOURCE_ACK, TARGET_ACK)]
    assert rows(
        url,
        "SELECT payment_id,invoice_id,amount_usd_cents,between_invoice_basis,posted_by "
        "FROM app.payment_allocations WHERE id=%s",
        move["target_allocation_id"],
    ) == [(found["payment"], found["target"], 1_000, "WRONG_UNIT_MOVE", first["person"])]
    assert (
        value(
            url,
            "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s "
            "AND action='payment_move.confirmed' AND entity_id=%s",
            draft,
            move["payment_move_id"],
        ),
        value(
            url,
            "SELECT count(*) FROM app.audit_events WHERE entity_id=%s "
            "AND action='final_settlement.correction.confirmed'",
            correction["id"],
        ),
    ) == (1, 1)
    assert settlement_row(url, first["settlement"]) == before
    assert confirm(first, draft) == result
    assert value(url, "SELECT app.payment_available_value(%s)", found["payment"]) == 0
    reconciled(url, first["customer"], second["customer"])
    # Q-2026-10-05-17: the moved allocation changes only through another move. Sub-slice 10h-1:
    # the first Settlement's correction wrote it, so it changes only through a correction of that
    # Settlement and its closed-Settlement refusal comes first (P5S01).
    with pytest.raises(AllocationConflictError) as one_call:
        allocations().reverse_allocation(
            prop,
            UUID(str(move["target_allocation_id"])),
            ReverseAllocationCommand(uuid4(), "Undo the move"),
            actor=person(human, prop, "payments.allocations.reverse"),
        )
    assert cast(psycopg.Error, one_call.value.__cause__).sqlstate == "P5S01"


def test_only_what_the_correct_invoice_owes_moves_and_the_rest_stays_on_the_payment(
    migrated_database_url: str,
) -> None:
    """The second Lease's line owes only 300 (its Customer paid 12,200): the correction moves 300
    and the other 700 stays unallocated on the Payment (plan Q16); the first line owes the whole
    1,000 again."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    pay(second, "other_line", 12_200)
    assert outstanding(url, second["other_line"]) == 300
    recorded = record(first, command(first["settlement"], found["allocation"], found["target"]))
    assert cast(dict[str, Any], recorded["payload"])["source"]["moved_usd_cents"] == 300
    move = cast(dict[str, Any], confirm(first, draft_of(recorded))["move"])
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (300, 700)
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        1_000,
        0,
    )
    assert value(url, "SELECT app.payment_available_value(%s)", found["payment"]) == 700
    reconciled(url, first["customer"], second["customer"])


def test_a_record_another_closed_settlement_relied_on_is_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer 5 to Q-2026-10-06-37: after the first Settlement's correction moved the 1,000
    to the second Lease, the second Settlement closes relying on the moved allocation. A correction
    of the second Settlement that would move it again is refused, because the first Settlement's
    correction linked it; the first Settlement's correction cannot name it either (it pays another
    Lease's Invoice). Nothing is recorded."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    result = confirm(
        first,
        draft_of(record(first, command(first["settlement"], found["allocation"], found["target"]))),
    )
    moved = UUID(str(cast(dict[str, Any], result["move"])["target_allocation_id"]))
    close(second)
    back = invoice_of(url, first["other_line"])
    assert outstanding(url, first["other_line"]) == 1_000
    before = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as other:
        record(second, command(second["settlement"], moved, back))
    assert cause(other) == ("55000", OTHER_SETTLEMENT)
    with pytest.raises(PaymentMoveConflictError) as first_settlement:
        record(first, command(first["settlement"], moved, found["target"]))
    assert cause(first_settlement) == ("55000", OTHER_LEASE)
    assert draft_count(url) == before


def test_a_move_correction_s_refusals_waiting_drafts_stale_drafts_and_withdrawal(
    migrated_database_url: str,
) -> None:
    """An open Settlement, a waiting move draft of either kind, a reused key, a stale draft (it
    stays pending), the preparer's withdrawal, an allocation made after the closure (the slice 7
    move draft still records it) and an allocation reversed before the closure."""
    url = migrated_database_url
    found = wrong_at_closure(url, reversed_before=True)
    first, second = found["first"], found["second"]
    prop, human = first["prop"], first["human"]
    allocation, target = found["allocation"], found["target"]
    before = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as open_settlement:
        record(second, command(second["settlement"], allocation, target))
    assert cause(open_settlement) == ("55000", OPEN)
    with pytest.raises(PaymentMoveConflictError) as reversed_before:
        record(first, command(first["settlement"], found["reversed"], target))
    assert cause(reversed_before) == ("55000", REVERSED)
    assert draft_count(url) == before
    mover = person(human, prop, "payments.allocations.reverse")
    # Sub-slice 10h-1: the slice 7 recorder refuses an allocation the closure relied on, so the
    # waiting slice 7 draft is written by hand to keep the waiting-draft check.
    with pytest.raises(PaymentMoveConflictError) as relied_on:
        moves().record(
            prop,
            RecordPaymentMoveCommand(uuid4(), allocation, target, REASON, SOURCE_ACK, TARGET_ACK),
            actor=mover,
        )
    assert cause(relied_on) == ("55000", RELIED_ON)
    ordinary = hand_built_move_draft(first, allocation, target)
    with pytest.raises(PaymentMoveConflictError) as ordinary_waits:
        record(first, command(first["settlement"], allocation, target))
    assert cause(ordinary_waits) == ("55000", WAITING)
    drafts().withdraw(
        prop,
        ordinary,
        "Moved through the correction",
        prepare_capability="payments.allocations.reverse",
        actor=mover,
    )
    request = command(first["settlement"], allocation, target)
    recorded = record(first, request)
    assert record(first, request) == recorded
    with pytest.raises(PaymentMoveKeyReused):
        record(first, replace(request, reason="Another reason"))
    with pytest.raises(PaymentMoveConflictError) as correction_waits:
        record(first, command(first["settlement"], allocation, target))
    assert cause(correction_waits) == ("55000", WAITING)
    # The second Lease's Customer pays 100 of the correct line: the draft is stale and stays
    # pending.
    pay(second, "other_line", 100)
    with pytest.raises(PaymentMoveStaleDraftError) as stale:
        confirm(first, draft_of(recorded))
    assert cause(stale)[0] == "P5S02"
    assert state(url, draft_of(recorded)) == "PENDING"
    drafts().withdraw(
        prop,
        draft_of(recorded),
        "The correct Invoice changed",
        prepare_capability="final_settlements.prepare",
        actor=preparer(human, prop),
    )
    assert state(url, draft_of(recorded)) == "WITHDRAWN"
    again = record(first, command(first["settlement"], allocation, target))
    move = cast(dict[str, Any], confirm(first, draft_of(again))["move"])
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (1_000, 0)
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        1_000,
        11_400,
    )
    # An allocation made after the closure is not one the Settlement relied on.
    later = pay(first, "other_line", 500)
    with pytest.raises(PaymentMoveConflictError) as after_closure:
        record(first, command(first["settlement"], later, target))
    assert cause(after_closure) == ("55000", AFTER_CLOSURE)
    plain = moves().record(
        prop,
        RecordPaymentMoveCommand(uuid4(), later, target, REASON, SOURCE_ACK, TARGET_ACK),
        actor=mover,
    )
    assert plain["state"] == "PENDING"
    drafts().withdraw(
        prop,
        draft_of(plain),
        "Not needed",
        prepare_capability="payments.allocations.reverse",
        actor=mover,
    )
    reconciled(url, first["customer"], second["customer"])


def test_the_move_check_needs_this_transaction_s_decision_and_both_links(
    migrated_database_url: str,
) -> None:
    """app.settlement_payment_move_allowed, called directly as the owner inside the confirm's own
    transaction (always rolled back): true for the stored move, false for another move id, another
    reversal, another allocation, another approver or another draft; after the transaction it is
    false."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first = found["first"]
    draft = draft_of(
        record(first, command(first["settlement"], found["allocation"], found["target"]))
    )
    check = "SELECT app.settlement_payment_move_allowed(%s,%s,%s,%s,%s)"
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_payment_move(%s,%s,%s,'financial.approve')",
            (first["prop"], first["person"], draft),
        )
        stored = connection.execute(
            "SELECT id,source_reversal_id,target_allocation_id FROM app.payment_moves "
            "WHERE draft_id=%s",
            (draft,),
        ).fetchone()
        assert stored is not None
        move, reversal, allocation = stored
        results = [
            connection.execute(check, values).fetchone()
            for values in (
                (draft, first["person"], move, reversal, allocation),
                (draft, first["person"], uuid4(), reversal, allocation),
                (draft, first["person"], move, uuid4(), allocation),
                (draft, first["person"], move, reversal, uuid4()),
                (draft, first["human"], move, reversal, allocation),
                (uuid4(), first["person"], move, reversal, allocation),
            )
        ]
        connection.rollback()
    assert results == [(True,), (False,), (False,), (False,), (False,), (False,)]
    result = confirm(first, draft)
    confirmed = cast(dict[str, Any], result["move"])
    assert (
        value(
            url,
            check,
            draft,
            first["person"],
            confirmed["payment_move_id"],
            confirmed["source_reversal_id"],
            confirmed["target_allocation_id"],
        )
        is False
    )


def test_the_move_check_refuses_a_move_row_outside_its_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1 (both reviewers): the patched insert check on the real insert path, as the
    owner, always rolled back. Inside the confirm's own transaction a copy of the stored move
    passes the check and meets the primary key (23505); with another approver, another id, or
    under a copy of the draft of another variant it is refused (23514). In a later transaction the
    stored move itself, with its own id, is refused before the primary key (23514: its decision is
    of another transaction; review round 2), and so is the same move under a withdrawn slice 7
    draft of the same allocation and Invoices (that draft has a decision)."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first = found["first"]
    prop, human = first["prop"], first["human"]
    mover = person(human, prop, "payments.allocations.reverse")
    # Sub-slice 10h-1: the slice 7 recorder refuses an allocation the closure relied on, so the
    # withdrawn slice 7 draft of the same allocation and Invoices is written by hand.
    ordinary = hand_built_move_draft(first, found["allocation"], found["target"])
    drafts().withdraw(
        prop,
        ordinary,
        "Moved through the correction",
        prepare_capability="payments.allocations.reverse",
        actor=mover,
    )
    draft = draft_of(
        record(first, command(first["settlement"], found["allocation"], found["target"]))
    )
    copy = (
        "INSERT INTO app.payment_moves SELECT (jsonb_populate_record(NULL::app.payment_moves,"
        "to_jsonb(m)||%s)).* FROM app.payment_moves m WHERE m.draft_id=%s"
    )

    def attempt(connection: psycopg.Connection[Any], changes: dict[str, Any]) -> Any:
        connection.execute("SAVEPOINT attempt")
        try:
            connection.execute(copy, (Jsonb(changes), draft))
        except psycopg.Error as refused:
            connection.execute("ROLLBACK TO SAVEPOINT attempt")
            return refused.sqlstate, refused.diag.message_primary
        connection.execute("ROLLBACK TO SAVEPOINT attempt")
        return None

    mismatch = ("23514", "Payment move does not match its draft")
    other_variant = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_payment_move(%s,%s,%s,'financial.approve')",
            (prop, first["person"], draft),
        )
        connection.execute(
            "INSERT INTO app.financial_drafts SELECT (jsonb_populate_record("
            "NULL::app.financial_drafts,"
            "to_jsonb(d)||jsonb_build_object('id',%s::uuid,'payload',"
            "jsonb_set(d.payload,'{variant}','\"CHARGE_REDUCTION\"')))).* "
            "FROM app.financial_drafts d WHERE d.id=%s",
            (other_variant, draft),
        )
        inside = [
            attempt(connection, {}),
            attempt(connection, {"confirmed_by": str(human)}),
            attempt(connection, {"id": str(uuid4())}),
            attempt(connection, {"id": str(uuid4()), "draft_id": str(other_variant)}),
        ]
        connection.rollback()
    assert inside[0] is not None and inside[0][0] == "23505"
    assert inside[1:] == [mismatch, mismatch, mismatch]
    confirm(first, draft)
    with psycopg.connect(url) as connection:
        later = [
            attempt(connection, {}),
            attempt(connection, {"id": str(uuid4()), "draft_id": str(ordinary)}),
        ]
        connection.rollback()
    assert later == [mismatch, mismatch]


def test_a_correct_invoice_on_a_closed_lease_takes_the_move(
    migrated_database_url: str,
) -> None:
    """Security review round 1: the correct Invoice may belong to a Lease whose Final Settlement
    is closed (the slice 10 design note; allocations to a closed Settlement's obligations stay
    open, owner answer 7 to Q-2026-10-05-20). The second Lease's Customer paid 500 of the second
    Lease's line before its closure, meant for the first Lease; after the first Settlement's
    correction moved its 1,000 there, the second Settlement closes owing 11,000 on that line. The
    second Settlement's correction then moves the 500 to the first Lease's line, which owes 1,000
    again: that line owes 500, the second line owes 500 again, and the first Settlement's closure
    snapshot is unchanged."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    wrong = pay(second, "other_line", 500)
    confirm(
        first,
        draft_of(record(first, command(first["settlement"], found["allocation"], found["target"]))),
    )
    close(second, 11_000)
    before = settlement_row(url, first["settlement"])
    back = invoice_of(url, first["other_line"])
    assert outstanding(url, first["other_line"]) == 1_000
    move = cast(
        dict[str, Any],
        confirm(
            second,
            draft_of(record(second, command(second["settlement"], wrong, back))),
        )["move"],
    )
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (500, 0)
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        500,
        500,
    )
    assert settlement_row(url, first["settlement"]) == before
    reconciled(url, first["customer"], second["customer"])


def test_a_source_refusal_at_confirm_leaves_the_draft_pending(
    migrated_database_url: str,
) -> None:
    """Independent review round 1: the correct Invoice is paid in full after the draft was
    recorded; the confirm runs the source again and is refused (55000), the draft stays pending
    and nothing is written."""
    url = migrated_database_url
    found = wrong_at_closure(url)
    first, second = found["first"], found["second"]
    draft = draft_of(
        record(first, command(first["settlement"], found["allocation"], found["target"]))
    )
    pay(second, "other_line", 12_500)
    with pytest.raises(PaymentMoveConflictError) as refused:
        confirm(first, draft)
    assert cause(refused) == ("55000", NOTHING_OWED)
    assert state(url, draft) == "PENDING"
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE draft_id=%s", draft),
        value(
            url,
            "SELECT count(*) FROM app.settlement_corrections WHERE correlation_id=%s",
            draft,
        ),
        outstanding(url, first["other_line"]),
    ) == (0, 0, 0)


def test_settlement_payment_moves_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; the
    migration adds only its functions, patches only the slice 7 move check, keeps its privileges
    and settings, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
            definer = connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert definer == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261221_147"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
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
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
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
        return functions, relations, triggers

    with _temporary_migration_database("settlement_payment_move") as temporary:
        alembic_command.upgrade(config, "20261221_147")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # The patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
