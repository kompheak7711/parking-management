"""Deposit receipt reversals in tests after V1-056 sub-slice 8r (BR-AUTH-010).

Since migration 20261022_87 a Deposit receipt reversal is a draft that takes effect only when a
financial.approve holder confirms it, and the financial role can no longer execute the one-call
reversal function (owner answer to Q-2026-10-05-22).

- ``reverse_receipt_through_draft`` uses the real path: the person records the draft under
  deposits.correct and, holding financial.approve, confirms it.
- ``reverse_receipt_as_owner`` calls the earlier one-call database function as the database
  owner, with the same parameters and error mapping the service used. It is only for tests
  where the receipt reversal is setup for another subject, and tests of the earlier function's
  own rules, which the draft confirmation runs unchanged.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from lease_deposit_forfeiture_test_support import _as_owner
from property_rental.deposit import (
    DEPOSIT_CORRECT_CAPABILITY,
    DepositSnapshot,
    PostgresDepositService,
    ReverseDepositReceiptCommand,
    deposit_request_digest,
)
from property_rental.deposit_receipt_reversal import (
    FINANCIAL_APPROVE_CAPABILITY,
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def reverse_receipt_as_owner(
    service: PostgresDepositService,
    command: ReverseDepositReceiptCommand,
    *,
    actor: AuthenticatedActor,
) -> DepositSnapshot:
    """The one-call receipt reversal the service sent before sub-slice 8r, run as the owner."""
    service._authorize(actor, DEPOSIT_CORRECT_CAPABILITY, command.authorization_reference)
    return _as_owner(service)._execute(
        "SELECT app.reverse_deposit_receipt_v2(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            service.property_id,
            service.actor_id,
            command.idempotency_key,
            deposit_request_digest("deposit.receipt.reverse", command),
            command.reversal_id,
            command.receipt_id,
            command.reason,
            command.authorization_reference,
        ),
    )


def approver(actor_id: UUID, property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(actor_id),
        frozenset(
            CapabilityGrant(capability, frozenset({str(property_id)}))
            for capability in capabilities
            or (DEPOSIT_CORRECT_CAPABILITY, FINANCIAL_APPROVE_CAPABILITY)
        ),
    )


def reverse_receipt_through_draft(
    financial_database_url: str,
    property_id: UUID,
    actor_id: UUID,
    receipt_id: UUID,
    *,
    reason: str = "Transfer returned by the bank",
    reversal_id: UUID | None = None,
) -> dict[str, object]:
    """Record the draft under deposits.correct and confirm it as a financial.approve holder."""
    service = DepositReceiptReversalService(financial_database_url)
    person = approver(actor_id, property_id)
    recorded = service.record(
        property_id,
        RecordDepositReceiptReversalCommand(uuid4(), receipt_id, reversal_id or uuid4(), reason),
        actor=person,
    )
    return service.confirm(property_id, receipt_id, UUID(str(recorded["draft_id"])), actor=person)
