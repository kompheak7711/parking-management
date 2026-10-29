"""V1-056 slice 7: wrong-Unit Payment move drafts confirmed by financial.approve (BR-PAY-042)."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.credit import CreditConflictError, ReverseCreditCommand
from property_rental.financial_draft import FinancialDraftAuthorizationError, FinancialDraftService
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import DecisionOutcome, FinalizeLatePaymentDecisionCommand
from property_rental.payment_allocation import (
    AllocationConflictError,
    AllocationUnavailableError,
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)
from property_rental.payment_move import (
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveKeyReused,
    PaymentMoveNotFoundError,
    PaymentMoveService,
    RecordPaymentMoveCommand,
    payment_move_draft_id,
)
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundConflictError,
    RefundInvalidError,
    RefundService,
    RefundUnavailableError,
)
from refund_test_support import create_usd_refund
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_adjustment_excess_migration import credit as credit_adjustment
from test_credit_adjustment_excess_migration import history
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
    setup_signed_lease,
)
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_refund_service_migration import refund_id, returned
from test_reservation_migration import migrated_database_url  # noqa: F401

RECORD = "app.record_payment_move_draft(uuid,uuid,uuid,uuid,uuid,text,text,text,text)"
CONFIRM = "app.confirm_payment_move_draft(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.payment_move_source(uuid,uuid,uuid)",
    "app.validate_payment_move()",
    "app.validate_payment_move_confirmed()",
    "app.validate_wrong_unit_move_allocation()",
    "app.validate_wrong_unit_move_reversal()",
    "app.reject_payment_move_mutation()",
    "app.validate_moved_credit_reversal()",
)
MOVE_REASON = "Wrong-Unit Payment move confirmed (BR-PAY-042)"
SOURCE_ACK = "Sok Dara (Parking 203), 2026-10-04, in person at the office"
TARGET_ACK = "Chea Vanna (Parking 201), 2026-10-04, by telephone"


@dataclass(frozen=True)
class WrongAllocation:
    """A Payment of the Unit 203 Customer posted on Unit 203 but meant for Unit 201."""

    human: UUID
    approver: UUID
    prop: UUID
    customer_wrong: UUID
    customer_right: UUID
    lease_wrong: UUID
    invoice_wrong: UUID
    line_wrong: UUID
    invoice_right: UUID
    line_right: UUID
    payment: UUID
    allocation: UUID


def person(identity: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(identity),
        frozenset(CapabilityGrant(value, frozenset({str(prop)})) for value in capabilities),
    )


def preparer(case: WrongAllocation) -> AuthenticatedActor:
    return person(
        case.human,
        case.prop,
        "payments.allocations.reverse",
        "payments.allocate",
        "payments.reverse",
    )


def approver(case: WrongAllocation) -> AuthenticatedActor:
    return person(case.approver, case.prop, "financial.approve")


def moves() -> PaymentMoveService:
    return PaymentMoveService(financial_database_url())


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def rows(url: str, query: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(query, parameters).fetchall()


def value(url: str, query: str, *parameters: object) -> Any:
    found = rows(url, query, *parameters)
    assert len(found) == 1
    return found[0][0]


def statuses(url: str, *invoices: UUID) -> dict[UUID, str]:
    return dict(rows(url, "SELECT id,status FROM app.invoices WHERE id=ANY(%s)", list(invoices)))


def allocation_ids(result: object) -> list[UUID]:
    return [
        UUID(str(item)) for item in cast(list[str], cast(dict[str, Any], result)["allocation_ids"])
    ]


def wrong_allocation(
    url: str,
    *,
    amount: int = 80_000,
    scope: str = "NORMAL_CUSTOMER",
    allocated: int = 80_000,
    payer_is_right: bool = False,
) -> WrongAllocation:
    with psycopg.connect(url) as connection:
        human, prop, customer_wrong, lease_wrong = setup_signed_lease(connection)
        other, _, customer_right, lease_right = setup_signed_lease(connection)
        invoice_wrong, line_wrong = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=customer_wrong, lease_id=lease_wrong
        )
        invoice_right, line_right = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=customer_right, lease_id=lease_right
        )
        payer = customer_wrong
        if payer_is_right:
            # A third-party Payment by the Customer of the correct Invoice.
            payer = customer_right
        elif scope == "THIRD_PARTY_IDENTIFIED":
            payer = uuid4()
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,'Third-party payer',%s,%s)",
                (payer, human, human),
            )
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=payer,
            amount=amount,
            scope=scope,
            lease_id=lease_wrong if scope == "THIRD_PARTY_IDENTIFIED" else None,
        )
    posted = allocations().post(
        prop,
        payment,
        designated(invoice_wrong, line_wrong, allocated),
        actor=person(human, prop, "payments.allocate"),
    )
    return WrongAllocation(
        human,
        other,
        prop,
        customer_wrong,
        customer_right,
        lease_wrong,
        invoice_wrong,
        line_wrong,
        invoice_right,
        line_right,
        payment,
        allocation_ids(posted)[0],
    )


def move(case: WrongAllocation, **changes: Any) -> RecordPaymentMoveCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "allocation_id": case.allocation,
        "target_invoice_id": case.invoice_right,
        "reason": "Paid on Parking 203 by mistake; meant for Parking 201",
        "source_acknowledgement": SOURCE_ACK,
        "target_acknowledgement": TARGET_ACK,
        **changes,
    }
    return RecordPaymentMoveCommand(**values)


def draft_id(result: dict[str, object]) -> UUID:
    return UUID(str(result["draft_id"]))


def nothing_moved(url: str, case: WrongAllocation) -> None:
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "PAID",
        case.invoice_right: "UNPAID",
    }
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE payment_id=%s", case.payment) == 0
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s "
            "AND between_invoice_basis='WRONG_UNIT_MOVE'",
            case.payment,
        )
        == 0
    )


def test_wrong_unit_move_is_a_draft_until_an_approver_confirms(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    payment_before = rows(url, "SELECT to_jsonb(p) FROM app.payments p WHERE p.id=%s", case.payment)
    receipts_before = rows(
        url, "SELECT to_jsonb(r) FROM app.receipts r WHERE r.payment_id=%s", case.payment
    )
    request = move(case)
    draft = moves().record(case.prop, request, actor=preparer(case))
    assert draft_id(draft) == payment_move_draft_id(case.prop, case.human, request.idempotency_key)
    assert draft["kind"] == "PAYMENT_MOVE" and draft["state"] == "PENDING"
    assert draft["prepared_by"] == str(case.human)
    assert draft["prepare_capability"] == "payments.allocations.reverse"
    payload = cast(dict[str, Any], draft["payload"])
    assert payload["source_acknowledgement"] == SOURCE_ACK
    assert payload["target_acknowledgement"] == TARGET_ACK
    source = payload["source"]
    assert source["moved_usd_cents"] == 80_000 and source["source_reversed"] is False
    assert source["payer_customer_id"] == str(case.customer_wrong)
    assert source["target_customer_id"] == str(case.customer_right)
    assert source["details"] == [
        {
            "invoice_line_id": str(case.line_right),
            "category": "RENT",
            "amount_usd_cents": 80_000,
            "attribution_basis": "RENT_FIRST_PROPOSAL",
        }
    ]
    assert moves().record(case.prop, request, actor=preparer(case)) == draft
    # A draft has no financial effect.
    nothing_moved(url, case)
    # Staff cannot confirm, and the database refuses any reference but financial.approve.
    with pytest.raises(PaymentMoveAuthorizationError):
        moves().confirm(case.prop, draft_id(draft), actor=preparer(case))
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,%s)",
                (case.prop, case.human, draft_id(draft), "payments.allocations.reverse"),
            )
    nothing_moved(url, case)

    result = moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    assert moves().confirm(case.prop, draft_id(draft), actor=approver(case)) == result
    outcome = cast(dict[str, Any], result["move"])
    assert outcome["moved_usd_cents"] == 80_000 and outcome["source_reversed_by_move"] is True
    assert outcome["payment_available_usd_cents"] == 0
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "UNPAID",
        case.invoice_right: "PAID",
    }
    assert rows(
        url,
        "SELECT actor_id,reason,authorization_reference FROM app.payment_allocation_reversals "
        "WHERE payment_allocation_id=%s",
        case.allocation,
    ) == [
        (
            case.approver,
            "Paid on Parking 203 by mistake; meant for Parking 201",
            "payments.allocations.reverse",
        )
    ]
    target = UUID(str(outcome["target_allocation_id"]))
    assert rows(
        url,
        "SELECT payment_id,target_customer_id,invoice_id,amount_usd_cents,between_invoice_basis,"
        "within_invoice_basis,posted_by,authorization_reference FROM app.payment_allocations "
        "WHERE id=%s",
        target,
    ) == [
        (
            case.payment,
            case.customer_right,
            case.invoice_right,
            80_000,
            "WRONG_UNIT_MOVE",
            "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
            case.approver,
            "payments.allocate",
        )
    ]
    assert rows(
        url,
        "SELECT invoice_line_id,posted_amount_usd_cents,attribution_basis "
        "FROM app.payment_allocation_details WHERE payment_allocation_id=%s",
        target,
    ) == [(case.line_right, 80_000, "RENT_FIRST_PROPOSAL")]
    assert rows(
        url,
        "SELECT draft_id,source_allocation_id,target_allocation_id,source_invoice_id,"
        "target_invoice_id,moved_usd_cents,source_acknowledgement,target_acknowledgement,"
        "confirmed_by,source_reversed_by_move FROM app.payment_moves WHERE payment_id=%s",
        case.payment,
    ) == [
        (
            draft_id(draft),
            case.allocation,
            target,
            case.invoice_wrong,
            case.invoice_right,
            80_000,
            SOURCE_ACK,
            TARGET_ACK,
            case.approver,
            True,
        )
    ]
    assert rows(
        url,
        "SELECT d.prepared_by,c.decision,c.decided_by,c.authorization_reference "
        "FROM app.financial_drafts d JOIN app.financial_draft_decisions c ON c.draft_id=d.id "
        "WHERE d.id=%s",
        draft_id(draft),
    ) == [(case.human, "CONFIRMED", case.approver, "financial.approve")]
    assert (
        value(
            url,
            "SELECT reason FROM app.audit_events WHERE entity_type='payment_allocation' "
            "AND entity_id=%s AND action='payment_allocation.posted'",
            target,
        )
        == MOVE_REASON
    )
    # One audit event for the whole move, correlated with the draft; one shared instant.
    assert rows(
        url,
        "SELECT actor_id,authorization_reference,correlation_id,"
        "resulting_state->>'prepared_by_actor_id' "
        "FROM app.audit_events WHERE action='payment_move.confirmed' AND entity_id=%s",
        UUID(str(outcome["payment_move_id"])),
    ) == [(case.approver, "financial.approve", draft_id(draft), str(case.human))]
    assert rows(
        url,
        "SELECT r.occurred_at=a.posted_at FROM app.payment_allocation_reversals r "
        "JOIN app.payment_allocations a ON a.id=%s WHERE r.payment_allocation_id=%s",
        target,
        case.allocation,
    ) == [(True,)]
    # The Payment record and its Receipt never change; no Credit moves between Customers.
    assert (
        rows(url, "SELECT to_jsonb(p) FROM app.payments p WHERE p.id=%s", case.payment)
        == payment_before
    )
    assert (
        rows(url, "SELECT to_jsonb(r) FROM app.receipts r WHERE r.payment_id=%s", case.payment)
        == receipts_before
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
            case.payment,
        )
        == 0
    )
    # The decided draft cannot be confirmed by another approver.
    other = person(case.human, case.prop, "financial.approve")
    with pytest.raises(PaymentMoveConflictError):
        moves().confirm(case.prop, draft_id(draft), actor=other)


def test_move_refuses_wrong_targets_reused_keys_and_a_second_waiting_draft(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    staff = preparer(case)
    with psycopg.connect(url) as connection:
        same_unit, _ = create_recurring_rent_invoice(
            connection,
            actor_id=case.human,
            customer_id=case.customer_wrong,
            lease_id=case.lease_wrong,
            period_start=date(2027, 3, 1),
        )
    for target in (same_unit, case.invoice_wrong):
        with pytest.raises(PaymentMoveInvalidError):
            moves().record(case.prop, move(case, target_invoice_id=target), actor=staff)
    for change in ({"allocation_id": uuid4()}, {"target_invoice_id": uuid4()}):
        with pytest.raises(PaymentMoveNotFoundError):
            moves().record(case.prop, move(case, **change), actor=staff)
    request = move(case)
    moves().record(case.prop, request, actor=staff)
    with pytest.raises(PaymentMoveKeyReused):
        moves().record(
            case.prop,
            move(case, idempotency_key=request.idempotency_key, reason="Other"),
            actor=staff,
        )
    # Only one draft per wrong allocation may wait.
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=staff)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    case.prop,
                    case.human,
                    uuid4(),
                    case.allocation,
                    case.invoice_right,
                    "Reason",
                    SOURCE_ACK,
                    TARGET_ACK,
                    "payments.allocate",
                ),
            )
    nothing_moved(url, case)


def test_correct_invoice_with_nothing_outstanding_is_a_conflict(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    with psycopg.connect(url) as connection:
        other_payment = seed_payment(
            connection,
            actor_id=case.human,
            property_id=case.prop,
            customer_id=case.customer_right,
            amount=80_000,
        )
    allocations().post(
        case.prop,
        other_payment,
        designated(case.invoice_right, case.line_right, 80_000),
        actor=person(case.human, case.prop, "payments.allocate"),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=preparer(case))
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='PAYMENT_MOVE' "
            "AND payload->>'source_allocation_id'=%s",
            str(case.allocation),
        )
        == 0
    )


def test_stale_draft_stays_pending_and_the_rest_stays_unallocated_on_the_payer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    stale = moves().record(case.prop, move(case), actor=preparer(case))
    # The correct Invoice changes after the draft was recorded: Unit 201 pays 30,000 itself.
    with psycopg.connect(url) as connection:
        own = seed_payment(
            connection,
            actor_id=case.human,
            property_id=case.prop,
            customer_id=case.customer_right,
            amount=30_000,
        )
    allocations().post(
        case.prop,
        own,
        designated(case.invoice_right, case.line_right, 30_000),
        actor=person(case.human, case.prop, "payments.allocate"),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().confirm(case.prop, draft_id(stale), actor=approver(case))
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s",
            draft_id(stale),
        )
        == 0
    )
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE payment_id=%s", case.payment) == 0
    )
    # The preparer withdraws the stale draft; a new draft moves only what Unit 201 still owes.
    withdrawn = drafts().withdraw(
        case.prop,
        draft_id(stale),
        "Correct Invoice changed",
        prepare_capability="payments.allocations.reverse",
        actor=preparer(case),
    )
    assert withdrawn["state"] == "WITHDRAWN"
    fresh = moves().record(case.prop, move(case), actor=preparer(case))
    assert cast(dict[str, Any], fresh["payload"])["source"]["moved_usd_cents"] == 50_000
    result = cast(
        dict[str, Any], moves().confirm(case.prop, draft_id(fresh), actor=approver(case))["move"]
    )
    assert result["moved_usd_cents"] == 50_000
    # The rest stays unallocated on the recorded payer (plan Q16); it is not Credit.
    assert result["payment_available_usd_cents"] == 30_000
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 30_000
    assert (
        value(
            url,
            "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
            case.payment,
        )
        == 0
    )
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "UNPAID",
        case.invoice_right: "PAID",
    }


def test_rejected_draft_moves_nothing_and_a_new_draft_may_follow(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    first = moves().record(case.prop, move(case), actor=preparer(case))
    with pytest.raises(FinancialDraftAuthorizationError):
        drafts().reject(case.prop, draft_id(first), "Not acknowledged", actor=preparer(case))
    rejected = drafts().reject(case.prop, draft_id(first), "Not acknowledged", actor=approver(case))
    assert rejected["state"] == "REJECTED"
    with pytest.raises(PaymentMoveConflictError):
        moves().confirm(case.prop, draft_id(first), actor=approver(case))
    nothing_moved(url, case)
    second = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(second), actor=approver(case))
    assert statuses(url, case.invoice_wrong)[case.invoice_wrong] == "UNPAID"


def test_customer_credit_or_refund_from_the_payment_blocks_the_move(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    # Credit: 20,000 of the Payment was kept as the payer's Credit.
    case = wrong_allocation(url, amount=100_000)
    credit = credit_id(recognize(case.prop, case.payment, case.human, 20_000))
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=preparer(case))
    credits().reverse(
        case.prop,
        credit,
        ReverseCreditCommand(uuid4(), "Kept by mistake"),
        actor=person(case.human, case.prop, "credits.reverse"),
    )
    allowed = moves().record(case.prop, move(case), actor=preparer(case))
    assert allowed["state"] == "PENDING"
    # Refund: 20,000 of another Payment was refunded to its payer.
    refunded = wrong_allocation(url, amount=100_000)
    paid = create_usd_refund(
        RefundService(runtime_database_url(), financial_database_url()),
        refunded.prop,
        CreateUsdRefundCommand(uuid4(), "PAYMENT", refunded.payment, 20_000, "Return excess"),
        actor=person(refunded.human, refunded.prop, "refunds.create", "refunds.read"),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().record(refunded.prop, move(refunded), actor=preparer(refunded))
    nothing_moved(url, refunded)
    # Once the Refund is verified as fully returned, it no longer blocks the move.
    refunds = RefundService(runtime_database_url(), financial_database_url())
    refunds.verify_usd_return(
        refunded.prop,
        refund_id(paid),
        returned(20_000),
        actor=person(refunded.human, refunded.prop, "refunds.correct"),
    )
    assert moves().record(refunded.prop, move(refunded), actor=preparer(refunded))["state"] == (
        "PENDING"
    )


def test_credit_adjustment_release_never_moves_and_its_replacement_waits_for_the_credit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    # A credit Adjustment on the wrong Invoice released 5,000 as that Customer's Credit.
    credit_adjustment(url, case.human, case.prop, case.invoice_wrong, case.line_wrong, 5_000)
    replacement = value(
        url,
        "SELECT replacement_payment_allocation_id FROM app.invoice_credit_excess_releases "
        "WHERE reversed_payment_allocation_id=%s",
        case.allocation,
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=preparer(case))
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case, allocation_id=replacement), actor=preparer(case))
    # The released Credit belongs to the payer here, so it may be reversed; afterwards the
    # released allocation is still refused on its own and its replacement may be drafted.
    released = value(
        url,
        "SELECT customer_credit_id FROM app.invoice_credit_excess_releases "
        "WHERE reversed_payment_allocation_id=%s",
        case.allocation,
    )
    credits().reverse(
        case.prop,
        released,
        ReverseCreditCommand(uuid4(), "Credit Adjustment was a mistake"),
        actor=person(case.human, case.prop, "credits.reverse"),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=preparer(case))
    drafted = moves().record(case.prop, move(case, allocation_id=replacement), actor=preparer(case))
    assert cast(dict[str, Any], drafted["payload"])["source"]["moved_usd_cents"] == 75_000


def test_already_reversed_allocation_moves_while_the_payment_holds_its_value(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    staff = preparer(case)
    reversal = allocations().reverse_allocation(
        case.prop, case.allocation, ReverseAllocationCommand(uuid4(), "Wrong Parking"), actor=staff
    )
    draft = moves().record(case.prop, move(case), actor=staff)
    assert cast(dict[str, Any], draft["payload"])["source"]["source_reversed"] is True
    outcome = cast(
        dict[str, Any], moves().confirm(case.prop, draft_id(draft), actor=approver(case))["move"]
    )
    assert outcome["source_reversed_by_move"] is False
    assert outcome["source_reversal_id"] == reversal["reversal_id"]
    assert (
        value(
            url,
            "SELECT count(*) FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s",
            case.allocation,
        )
        == 1
    )
    assert statuses(url, case.invoice_right)[case.invoice_right] == "PAID"
    # The moved allocation cannot move again from the same source.
    with pytest.raises(PaymentMoveConflictError):
        moves().record(case.prop, move(case), actor=staff)

    # When the released value was used elsewhere, the reversed allocation cannot move.
    spent = wrong_allocation(url)
    allocations().reverse_allocation(
        spent.prop,
        spent.allocation,
        ReverseAllocationCommand(uuid4(), "Wrong line"),
        actor=preparer(spent),
    )
    allocations().post(
        spent.prop,
        spent.payment,
        designated(spent.invoice_wrong, spent.line_wrong, 80_000),
        actor=preparer(spent),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().record(spent.prop, move(spent), actor=preparer(spent))


def test_one_call_reversal_cannot_undo_a_move_but_another_move_can(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    first = moves().record(case.prop, move(case), actor=preparer(case))
    moved = UUID(
        str(
            cast(
                dict[str, Any],
                moves().confirm(case.prop, draft_id(first), actor=approver(case))["move"],
            )["target_allocation_id"]
        )
    )
    # Q-2026-10-05-17: the one-call reversal refuses a moved allocation, so the value cannot go
    # back to the recorded payer's own Invoice without a draft and an approver.
    with pytest.raises(AllocationConflictError):
        allocations().reverse_allocation(
            case.prop,
            moved,
            ReverseAllocationCommand(uuid4(), "Undo the move"),
            actor=preparer(case),
        )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s",
            moved,
        )
        == 0
    )
    # While the moved allocation is active the Payment cannot be reversed (BR-PAY-012).
    # (The existing allocation service reports this definite refusal as unresolved; the
    # mapping is not part of this slice, so only the refusal itself is asserted.)
    with pytest.raises((AllocationConflictError, AllocationUnavailableError)):
        allocations().reverse_payment(
            case.prop,
            case.payment,
            ReversePaymentCommand(uuid4(), "Transfer returned"),
            actor=preparer(case),
        )
    assert value(url, "SELECT status FROM app.payments WHERE id=%s", case.payment) == "RECEIVED"
    # Another approved move takes it back to the first Invoice.
    back = moves().record(
        case.prop,
        move(case, allocation_id=moved, target_invoice_id=case.invoice_wrong),
        actor=preparer(case),
    )
    moves().confirm(case.prop, draft_id(back), actor=approver(case))
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "PAID",
        case.invoice_right: "UNPAID",
    }
    assert rows(
        url,
        "SELECT source_allocation_id,source_reversed_by_move FROM app.payment_moves "
        "WHERE payment_id=%s ORDER BY confirmed_at",
        case.payment,
    ) == [(case.allocation, True), (moved, True)]


def test_credit_adjustment_on_the_correct_invoice_reposts_a_moved_allocation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moved = cast(
        dict[str, Any], moves().confirm(case.prop, draft_id(draft), actor=approver(case))["move"]
    )
    credit_adjustment(url, case.human, case.prop, case.invoice_right, case.line_right, 5_000)
    # The released value is the correct Invoice Customer's Credit (BR-CREDIT-014); the re-post
    # keeps the move basis.
    assert rows(
        url,
        "SELECT r.released_usd_cents,c.customer_id,a.between_invoice_basis,a.amount_usd_cents "
        "FROM app.invoice_credit_excess_releases r "
        "JOIN app.customer_credits c ON c.id=r.customer_credit_id "
        "JOIN app.payment_allocations a ON a.id=r.replacement_payment_allocation_id "
        "WHERE r.reversed_payment_allocation_id=%s",
        UUID(str(moved["target_allocation_id"])),
    ) == [(5_000, case.customer_right, "WRONG_UNIT_MOVE", 75_000)]


def test_third_party_payment_moves_outside_its_identified_lease(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url, scope="THIRD_PARTY_IDENTIFIED")
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    assert statuses(url, case.invoice_right)[case.invoice_right] == "PAID"
    assert (
        value(
            url,
            "SELECT target_customer_id FROM app.payment_allocations WHERE payment_id=%s "
            "AND between_invoice_basis='WRONG_UNIT_MOVE'",
            case.payment,
        )
        == case.customer_right
    )


def test_late_payment_charge_allocation_does_not_move(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        # A past Due Date so that a Late-payment Decision is possible.
        human, prop, customer, invoice, _ = setup_invoice(connection, period_start=date(2026, 5, 1))
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=10_000
        )
        _, _, other_customer, other_lease = setup_signed_lease(connection)
        target, _ = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=other_customer, lease_id=other_lease
        )
    late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, 8_000, "Default"
        ),
        actor=late_payment_actor(human, prop),
    )
    charge = value(
        url, "SELECT id FROM app.late_payment_charges WHERE source_invoice_id=%s", invoice
    )
    posted = allocations().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(charge),
                "amount_usd_cents": 4_000,
            },
        ),
        actor=person(human, prop, "payments.allocate"),
    )
    with pytest.raises(PaymentMoveInvalidError):
        moves().record(
            prop,
            RecordPaymentMoveCommand(
                uuid4(), allocation_ids(posted)[0], target, "Wrong Parking", SOURCE_ACK, TARGET_ACK
            ),
            actor=person(human, prop, "payments.allocations.reverse"),
        )


def test_move_changes_no_late_payment_or_nonpayment_record_and_the_normal_rules_apply(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    before = history(url, case.lease_wrong, case.payment, case.invoice_wrong)
    review = late_service().review(
        case.invoice_wrong, actor=late_payment_actor(case.human, case.prop)
    )
    assert "INVOICE_NOT_UNPAID" in cast(list[str], review["blocking_conditions"])
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    after = history(url, case.lease_wrong, case.payment, case.invoice_wrong)
    for name in ("decisions", "charges", "payment", "receipts", "cases", "events"):
        assert after[name] == before[name], name
    # The first Invoice is simply unpaid again; the usual late-payment review sees it so.
    review = late_service().review(
        case.invoice_wrong, actor=late_payment_actor(case.human, case.prop)
    )
    assert "INVOICE_NOT_UNPAID" not in cast(list[str], review["blocking_conditions"])


def test_one_customer_two_unit_one_call_path_stays_an_ordinary_correction(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    with psycopg.connect(url) as connection:
        _, _, unit, _, _ = setup_sources(connection)
        lease = create_draft(
            connection, actor_id=case.human, unit_id=unit, primary_tenant_id=case.customer_wrong
        )
        sign_lease(connection, lease, case.human)
        second, second_line = create_recurring_rent_invoice(
            connection, actor_id=case.human, customer_id=case.customer_wrong, lease_id=lease
        )
    staff = preparer(case)
    allocations().reverse_allocation(
        case.prop,
        case.allocation,
        ReverseAllocationCommand(uuid4(), "Meant for the other Parking"),
        actor=staff,
    )
    allocations().post(
        case.prop, case.payment, designated(second, second_line, 80_000), actor=staff
    )
    assert statuses(url, case.invoice_wrong, second) == {
        case.invoice_wrong: "UNPAID",
        second: "PAID",
    }
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE payment_id=%s", case.payment) == 0
    )


def test_database_guards_need_a_confirmed_move_and_keep_moves_append_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    staff = preparer(case)
    allocations().reverse_allocation(
        case.prop, case.allocation, ReverseAllocationCommand(uuid4(), "Wrong Parking"), actor=staff
    )
    # Even the database owner cannot post a WRONG_UNIT_MOVE allocation without a confirmed move.
    with psycopg.connect(url) as connection:
        allocation = uuid4()
        connection.execute(
            "INSERT INTO app.payment_allocations(id,payment_id,target_customer_id,target_kind,"
            "invoice_id,amount_usd_cents,between_invoice_basis,within_invoice_basis,posted_at,posted_by,"
            "authorization_reference) VALUES (%s,%s,%s,'INVOICE',%s,80000,'WRONG_UNIT_MOVE',"
            "'OTHER_APPLICABLE_OBLIGATION',clock_timestamp(),%s,'payments.allocate')",
            (allocation, case.payment, case.customer_right, case.invoice_right, case.human),
        )
        connection.execute(
            "INSERT INTO app.payment_allocation_details(id,payment_allocation_id,invoice_line_id,"
            "obligation_kind,invoice_line_category_snapshot,posted_amount_usd_cents,attribution_basis,"
            "detail_sequence,calculation_trace) VALUES (%s,%s,%s,'INVOICE_LINE','RENT',80000,"
            "'OTHER_CONFIRMED',1,'{}'::jsonb)",
            (uuid4(), allocation, case.line_right),
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="needs a confirmed move draft"):
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.rollback()
    draft = moves().record(case.prop, move(case), actor=staff)
    moved = UUID(
        str(
            cast(
                dict[str, Any],
                moves().confirm(case.prop, draft_id(draft), actor=approver(case))["move"],
            )["target_allocation_id"]
        )
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,"
            "occurred_at,actor_id,authorization_reference) "
            "VALUES (%s,%s,'Direct',clock_timestamp(),%s,'payments.allocations.reverse')",
            (uuid4(), moved, case.human),
        )
        with pytest.raises(psycopg.Error) as refused:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert refused.value.sqlstate == "P4904"
        connection.rollback()
        for statement in (
            "UPDATE app.payment_moves SET moved_usd_cents=1 WHERE payment_id=%s",
            "DELETE FROM app.payment_moves WHERE payment_id=%s",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(statement, (case.payment,))
            connection.rollback()
    assert statuses(url, case.invoice_right)[case.invoice_right] == "PAID"


def test_payment_move_roles_and_grants(migrated_database_url: str) -> None:  # noqa: F811
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "public"):
            for function in INTERNAL:
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.payment_moves','SELECT,INSERT,UPDATE,DELETE')",
                (role,),
            ).fetchone() == (False,), role
        for function in (RECORD, CONFIRM):
            assert connection.execute(
                "SELECT has_function_privilege('prm_financial',%s,'EXECUTE'),"
                "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
                "has_function_privilege('public',%s,'EXECUTE')",
                (function, function, function),
            ).fetchone() == (True, False, False), function
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig FROM pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, ["search_path=pg_catalog"])


def test_unknown_property_is_not_found_and_moves_nothing(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    # V1 holds one Property (properties_singleton_key_unique): any other Property id is unknown
    # and refused first (P4501); the Payment, Invoice and draft Property checks stay as defence.
    other = uuid4()
    with pytest.raises(PaymentMoveNotFoundError):
        moves().record(
            other, move(case), actor=person(case.human, other, "payments.allocations.reverse")
        )
    with pytest.raises(PaymentMoveNotFoundError):
        moves().confirm(
            other, draft_id(draft), actor=person(case.approver, other, "financial.approve")
        )
    nothing_moved(url, case)
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s",
            draft_id(draft),
        )
        == 0
    )


def test_moved_amount_follows_the_rent_then_service_order(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        billing_human, prop, customer, lease, _ = setup_billing_source(connection)
    invoice = (
        PostgresRentBillingService(financial_database_url(), prop, billing_human)
        .generate(initial_command(lease, uuid4()), actor=authenticated(billing_human, prop))
        .invoice_id
    )
    lines = rows(
        url,
        "SELECT category,id,app.invoice_line_outstanding(id),line_sequence FROM app.invoice_lines "
        "WHERE invoice_id=%s",
        invoice,
    )
    rank = {"RENT": 0, "SERVICE_CHARGES": 1}
    ordered = sorted(lines, key=lambda line: (rank.get(str(line[0]), 2), int(line[3])))
    assert [str(line[0]) for line in ordered][:2] == ["RENT", "SERVICE_CHARGES"]
    full_rent, service_due = int(ordered[0][2]), int(ordered[1][2])
    assert full_rent > 10_000 and service_due >= 2
    # The Customer of the correct Invoice already paid all but 10,000 of its Rent line, so a
    # wrong allocation of 10,001 covers the Rent and one cent of the Service line.
    with psycopg.connect(url) as connection:
        own = seed_payment(
            connection,
            actor_id=billing_human,
            property_id=prop,
            customer_id=customer,
            amount=full_rent - 10_000,
        )
    allocations().post(
        prop,
        own,
        designated(invoice, ordered[0][1], full_rent - 10_000),
        actor=person(billing_human, prop, "payments.allocate"),
    )
    rent_due = 10_000
    # Rent covered in full, the Service line by one cent, any other line untouched.
    case = wrong_allocation(url, allocated=rent_due + 1)
    draft = moves().record(case.prop, move(case, target_invoice_id=invoice), actor=preparer(case))
    assert cast(dict[str, Any], draft["payload"])["source"]["details"] == [
        {
            "invoice_line_id": str(ordered[0][1]),
            "category": "RENT",
            "amount_usd_cents": rent_due,
            "attribution_basis": "RENT_FIRST_PROPOSAL",
        },
        {
            "invoice_line_id": str(ordered[1][1]),
            "category": "SERVICE_CHARGES",
            "amount_usd_cents": 1,
            "attribution_basis": "SERVICE_PROPOSAL",
        },
    ]
    before = rows(url, "SELECT status,version FROM app.invoices WHERE id=%s", invoice)
    outcome = cast(
        dict[str, Any], moves().confirm(case.prop, draft_id(draft), actor=approver(case))["move"]
    )
    # The status stays PARTIALLY_PAID, but the version advances, so a command prepared before
    # the move (for example a credit Adjustment) is refused as stale.
    after_header = rows(url, "SELECT status,version FROM app.invoices WHERE id=%s", invoice)
    assert before[0][0] == after_header[0][0] == "PARTIALLY_PAID"
    assert int(after_header[0][1]) > int(before[0][1])
    assert rows(
        url,
        "SELECT invoice_line_id,posted_amount_usd_cents,attribution_basis,detail_sequence "
        "FROM app.payment_allocation_details WHERE payment_allocation_id=%s "
        "ORDER BY detail_sequence",
        UUID(str(outcome["target_allocation_id"])),
    ) == [
        (ordered[0][1], rent_due, "RENT_FIRST_PROPOSAL", 1),
        (ordered[1][1], 1, "SERVICE_PROPOSAL", 2),
    ]
    after = {
        line: int(due)
        for _, line, due, _ in rows(
            url,
            "SELECT category,id,app.invoice_line_outstanding(id),line_sequence "
            "FROM app.invoice_lines WHERE invoice_id=%s",
            invoice,
        )
    }
    assert after[ordered[0][1]] == 0 and after[ordered[1][1]] == service_due - 1
    for other in ordered[2:]:
        assert after[other[1]] == int(other[2])


def test_credit_or_refund_after_the_draft_blocks_confirmation(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url, amount=100_000)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    recognize(case.prop, case.payment, case.human, 20_000)
    with pytest.raises(PaymentMoveConflictError):
        moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    refunded = wrong_allocation(url, amount=100_000)
    refund_draft = moves().record(refunded.prop, move(refunded), actor=preparer(refunded))
    create_usd_refund(
        RefundService(runtime_database_url(), financial_database_url()),
        refunded.prop,
        CreateUsdRefundCommand(uuid4(), "PAYMENT", refunded.payment, 20_000, "Return excess"),
        actor=person(refunded.human, refunded.prop, "refunds.create", "refunds.read"),
    )
    with pytest.raises(PaymentMoveConflictError):
        moves().confirm(refunded.prop, draft_id(refund_draft), actor=approver(refunded))
    for blocked, pending in ((case, draft), (refunded, refund_draft)):
        nothing_moved(url, blocked)
        assert (
            value(
                url,
                "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s",
                draft_id(pending),
            )
            == 0
        )


def test_two_drafts_recorded_at_once_for_one_allocation_leave_one_waiting(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    barrier = Barrier(2)

    def attempt(_: int) -> object:
        barrier.wait()
        try:
            return moves().record(case.prop, move(case), actor=preparer(case))
        except PaymentMoveConflictError as error:
            return error

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(isinstance(result, PaymentMoveConflictError) for result in results) == 1
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='PAYMENT_MOVE' "
            "AND payload->>'source_allocation_id'=%s",
            str(case.allocation),
        )
        == 1
    )


def test_two_approvers_confirming_at_once_move_the_payment_once(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    barrier = Barrier(2)

    def attempt(actor: AuthenticatedActor) -> object:
        barrier.wait()
        try:
            return moves().confirm(case.prop, draft_id(draft), actor=actor)
        except PaymentMoveConflictError as error:
            return error

    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(attempt, (approver(case), person(case.human, case.prop, "financial.approve")))
        )
    assert sum(isinstance(result, PaymentMoveConflictError) for result in results) == 1
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE payment_id=%s", case.payment) == 1
    )
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "UNPAID",
        case.invoice_right: "PAID",
    }


def released_credit(url: str, payment: UUID) -> UUID:
    """The Credit a credit Adjustment released from the Payment's moved allocation."""
    return UUID(
        str(
            value(
                url,
                "SELECT release.customer_credit_id FROM app.invoice_credit_excess_releases release "
                "JOIN app.payment_moves move ON move.target_allocation_id="
                "release.reversed_payment_allocation_id WHERE move.payment_id=%s",
                payment,
            )
        )
    )


def test_credit_released_from_a_moved_allocation_stays_with_the_invoice_customer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    # A credit Adjustment on the correct Invoice releases moved value as that Customer's Credit.
    credit_adjustment(url, case.human, case.prop, case.invoice_right, case.line_right, 5_000)
    credit = released_credit(url, case.payment)
    assert (
        value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit)
        == case.customer_right
    )
    # Q-2026-10-05-18: reversing it would return the value to the payer's Payment for a one-call
    # allocation on the payer's own Invoice, so the one-call Credit reversal refuses it.
    with pytest.raises(CreditConflictError):
        credits().reverse(
            case.prop,
            credit,
            ReverseCreditCommand(uuid4(), "Return the value to the payer"),
            actor=person(case.human, case.prop, "credits.reverse"),
        )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            credit,
        )
        == 0
    )
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 0


def test_third_party_payers_own_released_credit_is_not_reversed_back_to_the_identified_lease(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    # The Unit 201 Customer paid as a third party for the Unit 203 Lease; the money was meant for
    # their own Unit 201 Invoice and is moved there.
    case = wrong_allocation(url, scope="THIRD_PARTY_IDENTIFIED", payer_is_right=True)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    credit_adjustment(url, case.human, case.prop, case.invoice_right, case.line_right, 5_000)
    credit = released_credit(url, case.payment)
    assert (
        value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit)
        == case.customer_right
    )
    # The Credit is the payer's own, but reversing it would let a one-call third-party allocation
    # or Deposit receipt send the value to the identified Unit 203 Lease (Q-2026-10-05-19).
    with pytest.raises(CreditConflictError):
        credits().reverse(
            case.prop,
            credit,
            ReverseCreditCommand(uuid4(), "Return the value to the Payment"),
            actor=person(case.human, case.prop, "credits.reverse"),
        )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            credit,
        )
        == 0
    )
    assert value(url, "SELECT app.payment_available_value(%s)", case.payment) == 0
    assert statuses(url, case.invoice_wrong)[case.invoice_wrong] == "UNPAID"


def test_credit_of_another_customer_from_a_moved_payment_is_not_refunded_to_the_payer(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    draft = moves().record(case.prop, move(case), actor=preparer(case))
    moves().confirm(case.prop, draft_id(draft), actor=approver(case))
    credit_adjustment(url, case.human, case.prop, case.invoice_right, case.line_right, 5_000)
    credit = released_credit(url, case.payment)
    # Existing Refund rules pay a Credit Refund only to the Payment's payer, who must also own the
    # Credit; the Refund to the Invoice Customer is the CREDIT_CUSTOMER draft of V1-056 sub-slice 8f
    # (Q-2026-10-05-19).
    with pytest.raises((RefundConflictError, RefundInvalidError, RefundUnavailableError)):
        create_usd_refund(
            RefundService(runtime_database_url(), financial_database_url()),
            case.prop,
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 5_000, "Return Customer Credit"),
            actor=person(case.human, case.prop, "refunds.create", "refunds.read"),
        )
    assert (
        value(url, "SELECT count(*) FROM app.refunds WHERE source_customer_credit_id=%s", credit)
        == 0
    )


def test_normal_payment_identified_invoice_moves_only_through_a_draft(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, customer, lease = setup_signed_lease(connection)
        approving, _, _, _ = setup_signed_lease(connection)
        first, first_line = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=customer, lease_id=lease
        )
        _, _, unit, _, _ = setup_sources(connection)
        other_lease = create_draft(
            connection, actor_id=human, unit_id=unit, primary_tenant_id=customer
        )
        sign_lease(connection, other_lease, human)
        second, second_line = create_recurring_rent_invoice(
            connection, actor_id=human, customer_id=customer, lease_id=other_lease
        )
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=80_000,
            invoice_id=first,
        )
    staff = person(human, prop, "payments.allocate", "payments.allocations.reverse")
    allocation = allocation_ids(
        allocations().post(prop, payment, designated(first, first_line, 80_000), actor=staff)
    )[0]
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Meant for the other Parking"),
        actor=staff,
    )
    # The Payment names the first Invoice, so an ordinary allocation to the other Unit's Invoice
    # is refused even for the same Customer (identified intent, BR-PAY-025 amendment).
    with pytest.raises((AllocationConflictError, AllocationUnavailableError)):
        allocations().post(prop, payment, designated(second, second_line, 80_000), actor=staff)
    assert statuses(url, first, second) == {first: "UNPAID", second: "UNPAID"}
    draft = moves().record(
        prop,
        RecordPaymentMoveCommand(
            uuid4(), allocation, second, "Meant for the other Parking", SOURCE_ACK, TARGET_ACK
        ),
        actor=staff,
    )
    moves().confirm(prop, draft_id(draft), actor=person(approving, prop, "financial.approve"))
    assert statuses(url, first, second) == {first: "UNPAID", second: "PAID"}
    assert (
        value(
            url,
            "SELECT between_invoice_basis FROM app.payment_allocations WHERE invoice_id=%s",
            second,
        )
        == "WRONG_UNIT_MOVE"
    )
    # A one-Customer move: a Credit released from it belongs to the payer and may be reversed.
    credit_adjustment(url, human, prop, second, second_line, 5_000)
    credit = released_credit(url, payment)
    credits().reverse(
        prop,
        credit,
        ReverseCreditCommand(uuid4(), "Credit Adjustment was a mistake"),
        actor=person(human, prop, "credits.reverse"),
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            credit,
        )
        == 1
    )


def test_payment_move_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261020_85")
    assert revision is not None and revision.down_revision == "20261019_84"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
