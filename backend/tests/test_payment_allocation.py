"""Non-database Payment command validation and capability boundaries."""

from uuid import UUID, uuid4

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationInvalidError,
    PaymentAllocationService,
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)


@pytest.mark.parametrize("amount", [1.1, True, False, float("nan"), 9_000_000_000_000_001])
def test_allocation_intent_rejects_inexact_or_unbounded_money(amount: object) -> None:
    with pytest.raises(AllocationInvalidError):
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Approved instruction",
                "targets": [{"amount_usd_cents": amount}],
            },
        )


@pytest.mark.parametrize("reason", ["", " ", " leading", "trailing ", "x" * 1001])
def test_allocation_reversals_require_normalized_reason(reason: str) -> None:
    with pytest.raises(AllocationInvalidError):
        ReverseAllocationCommand(uuid4(), reason)
    with pytest.raises(AllocationInvalidError):
        ReversePaymentCommand(uuid4(), reason)


def test_allocation_snapshot_and_posted_amount_have_distinct_exact_limits() -> None:
    proposal = {"outstanding_usd_cents": 9_223_372_036_854_775_807, "amount_usd_cents": 1}
    PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal})
    for invalid in (
        {**proposal, "outstanding_usd_cents": 9_223_372_036_854_775_808},
        {**proposal, "outstanding_usd_cents": True},
        {**proposal, "amount_usd_cents": 9_000_000_000_000_001},
        {**proposal, "amount_usd_cents": 1.0},
    ):
        with pytest.raises(AllocationInvalidError):
            PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": invalid})


def test_allocation_payment_reversal_requires_expected_state() -> None:
    with pytest.raises(AllocationInvalidError):
        ReversePaymentCommand(uuid4(), "Correct duplicate", "REVERSED")
    with pytest.raises(AllocationInvalidError):
        ReverseAllocationCommand(UUID(int=0), "Correct duplicate")


@pytest.mark.parametrize(
    "grant", ["", "payments.record", "payments.allocate", "payments.allocations.reverse"]
)
def test_allocation_reverse_payment_has_distinct_capability(grant: str) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(grant, frozenset({str(prop)}))})
    )
    with pytest.raises(AllocationAuthorizationError):
        PaymentAllocationService("unused", "unused").reverse_payment(
            prop, uuid4(), ReversePaymentCommand(uuid4(), "Duplicate receipt"), actor=actor
        )


@pytest.mark.parametrize("grant", ["", "payments.record", "payments.allocate", "payments.reverse"])
def test_allocation_reversal_has_distinct_capability(grant: str) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(grant, frozenset({str(prop)}))})
    )
    with pytest.raises(AllocationAuthorizationError):
        PaymentAllocationService("unused", "unused").reverse_allocation(
            prop, uuid4(), ReverseAllocationCommand(uuid4(), "Wrong assignment"), actor=actor
        )


def test_allocation_reversal_scope_is_checked_before_database_access() -> None:
    actor = AuthenticatedActor(
        str(uuid4()),
        frozenset({CapabilityGrant("payments.allocations.reverse", frozenset({str(uuid4())}))}),
    )
    with pytest.raises(AllocationAuthorizationError):
        PaymentAllocationService("unused", "unused").reverse_allocation(
            uuid4(), uuid4(), ReverseAllocationCommand(uuid4(), "Wrong assignment"), actor=actor
        )


def test_allocation_scope_is_checked_before_database_access() -> None:
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant("payments.allocate", frozenset({str(uuid4())}))})
    )
    with pytest.raises(AllocationAuthorizationError):
        PaymentAllocationService("unused", "unused").proposal(uuid4(), uuid4(), actor=actor)


@pytest.mark.parametrize(
    "intent",
    [
        {},
        {"mode": "AUTO"},
        {"mode": "PROPOSAL", "proposal": {}, "post": True},
        {"mode": "DESIGNATED", "targets": [], "designation_reference": ""},
    ],
)
def test_allocation_command_requires_explicit_supported_intent(intent: dict[str, object]) -> None:
    with pytest.raises(AllocationInvalidError):
        PostAllocationsCommand(uuid4(), intent)
