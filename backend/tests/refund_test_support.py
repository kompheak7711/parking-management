"""Create a Refund the V1-056 way: a refunds.create draft confirmed under financial.approve.

Earlier tests created a Refund in one call. Since slice 3a a Refund is a draft that takes effect
only when a financial.approve holder confirms it (BR-AUTH-010). These helpers keep the earlier
call shape: the same person prepares and confirms (allowed when they hold financial.approve),
the draft id is derived from the preparer and the command key, and the confirmed Refund resource is
returned exactly as the earlier create call returned it. A repeated call replays both steps.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.refund import (
    CreatePetRefundCommand,
    CreateUsdRefundCommand,
    RefundMethodChoice,
    RefundService,
)

CASH_REFERENCE_NOTE = "Cash handed over at the Property office"


def approver(actor: AuthenticatedActor, property_id: UUID) -> AuthenticatedActor:
    """The same person, also holding financial.approve for the Property."""
    return AuthenticatedActor(
        actor_id=actor.actor_id,
        capability_grants=actor.capability_grants
        | {CapabilityGrant("financial.approve", frozenset({str(property_id)}))},
    )


def method_id(
    service: RefundService, property_id: UUID, actor: AuthenticatedActor, code: str = "CASH"
) -> UUID:
    items = cast(list[dict[str, object]], service.refund_methods(property_id, actor=actor)["items"])
    return UUID(str(next(item["id"] for item in items if item["code"] == code)))


def cash(
    service: RefundService, property_id: UUID, actor: AuthenticatedActor
) -> RefundMethodChoice:
    return RefundMethodChoice(method_id(service, property_id, actor), CASH_REFERENCE_NOTE)


def create_usd_refund(
    service: RefundService,
    property_id: UUID,
    command: CreateUsdRefundCommand,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    draft = service.record_usd_draft(
        property_id, command, cash(service, property_id, actor), actor=actor
    )
    confirmed = service.confirm_draft(
        property_id, UUID(str(draft["draft_id"])), actor=approver(actor, property_id)
    )
    return cast(dict[str, object], confirmed["refund"])


def create_pet_refund(
    service: RefundService,
    property_id: UUID,
    command: CreatePetRefundCommand,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    draft = service.record_pet_draft(
        property_id, command, cash(service, property_id, actor), actor=actor
    )
    confirmed = service.confirm_draft(
        property_id, UUID(str(draft["draft_id"])), actor=approver(actor, property_id)
    )
    return cast(dict[str, object], confirmed["refund"])
