"""One confirm for every waiting financial draft (V1-056 slice 11b).

The "Waiting for approval" list confirms any draft through one route. This module reads the
draft's kind and variant and calls that kind's own confirm command, which checks
``financial.approve`` and every business rule again. A draft that is confirmed only inside
another command (a return reversal's companion) has no confirm here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from property_rental.adjustment_reversal import (
    AdjustmentReversalAuthorizationError,
    AdjustmentReversalConflictError,
    AdjustmentReversalInvalidError,
    AdjustmentReversalNotFoundError,
    AdjustmentReversalService,
    AdjustmentReversalStaleDraftError,
    AdjustmentReversalUnavailableError,
)
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalAuthorizationError,
    DepositReceiptReversalConflictError,
    DepositReceiptReversalInvalidError,
    DepositReceiptReversalNotFoundError,
    DepositReceiptReversalService,
    DepositReceiptReversalUnavailableError,
)
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementNotFoundError,
    FinalSettlementService,
    FinalSettlementStaleDraftError,
    FinalSettlementUnavailableError,
)
from property_rental.identity import AuthenticatedActor
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureService,
    LeaseDepositForfeitureUnavailableError,
)
from property_rental.payment_move import (
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveNotFoundError,
    PaymentMoveService,
    PaymentMoveStaleDraftError,
    PaymentMoveUnavailableError,
)
from property_rental.payment_return import (
    PaymentReturnAuthorizationError,
    PaymentReturnConflictError,
    PaymentReturnInvalidError,
    PaymentReturnNotFoundError,
    PaymentReturnService,
    PaymentReturnStaleDraftError,
    PaymentReturnUnavailableError,
)
from property_rental.refund import (
    RefundAuthorizationError,
    RefundConflictError,
    RefundInvalidError,
    RefundNotFoundError,
    RefundService,
    RefundUnavailableError,
)
from property_rental.reservation_deposit_draft import (
    ReservationDepositDraftAuthorizationError,
    ReservationDepositDraftConflictError,
    ReservationDepositDraftInvalidError,
    ReservationDepositDraftNotFoundError,
    ReservationDepositDraftService,
    ReservationDepositDraftUnavailableError,
)
from property_rental.settlement_correction import SettlementCorrectionService

NOT_FOUND_ERRORS: Final = (
    AdjustmentReversalNotFoundError,
    DepositReceiptReversalNotFoundError,
    FinalSettlementNotFoundError,
    LeaseDepositForfeitureNotFoundError,
    PaymentMoveNotFoundError,
    PaymentReturnNotFoundError,
    RefundNotFoundError,
    ReservationDepositDraftNotFoundError,
)
AUTHORIZATION_ERRORS: Final = (
    AdjustmentReversalAuthorizationError,
    DepositReceiptReversalAuthorizationError,
    FinalSettlementAuthorizationError,
    LeaseDepositForfeitureAuthorizationError,
    PaymentMoveAuthorizationError,
    PaymentReturnAuthorizationError,
    RefundAuthorizationError,
    ReservationDepositDraftAuthorizationError,
)
INVALID_ERRORS: Final = (
    AdjustmentReversalInvalidError,
    DepositReceiptReversalInvalidError,
    FinalSettlementInvalidError,
    LeaseDepositForfeitureInvalidError,
    PaymentMoveInvalidError,
    PaymentReturnInvalidError,
    RefundInvalidError,
    ReservationDepositDraftInvalidError,
)
STALE_ERRORS: Final = (
    AdjustmentReversalStaleDraftError,
    FinalSettlementStaleDraftError,
    PaymentMoveStaleDraftError,
    PaymentReturnStaleDraftError,
)
CONFLICT_ERRORS: Final = (
    AdjustmentReversalConflictError,
    DepositReceiptReversalConflictError,
    FinalSettlementConflictError,
    LeaseDepositForfeitureConflictError,
    PaymentMoveConflictError,
    PaymentReturnConflictError,
    RefundConflictError,
    ReservationDepositDraftConflictError,
)
UNAVAILABLE_ERRORS: Final = (
    AdjustmentReversalUnavailableError,
    DepositReceiptReversalUnavailableError,
    FinalSettlementUnavailableError,
    LeaseDepositForfeitureUnavailableError,
    PaymentMoveUnavailableError,
    PaymentReturnUnavailableError,
    RefundUnavailableError,
    ReservationDepositDraftUnavailableError,
)

Confirm = Callable[[UUID, UUID, AuthenticatedActor], dict[str, object]]


class DraftConfirmNotAvailable(RuntimeError):
    """The draft's kind and variant have no confirm through the shared route."""


class DraftPayloadInvalid(RuntimeError):
    """A stored draft lacks an identifier its confirm needs (a server contract error)."""


def _payload_id(payload: dict[str, object], key: str) -> UUID:
    value = payload.get(key)
    try:
        identity = UUID(str(value))
    except ValueError as exc:
        raise DraftPayloadInvalid(f"Draft payload has no {key}") from exc
    if not isinstance(value, str) or identity.int == 0:
        raise DraftPayloadInvalid(f"Draft payload has no {key}")
    return identity


def confirm_key(draft: dict[str, object]) -> tuple[str, str, str | None]:
    """The draft's kind, variant and, for a Late-payment Charge correction, its target kind."""
    kind, payload = draft.get("kind"), draft.get("payload")
    if not isinstance(kind, str) or not isinstance(payload, dict):
        raise DraftPayloadInvalid("Draft has no kind or payload")
    variant = payload.get("variant")
    target = payload.get("target_kind")
    return (
        kind,
        variant if isinstance(variant, str) else "",
        target if target == "LATE_PAYMENT_CHARGE" else None,
    )


@dataclass(frozen=True, slots=True)
class PostgresDraftConfirmer:
    database_url: str
    financial_database_url: str

    def confirm(
        self, property_id: UUID, draft: dict[str, object], *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        kind, variant, target = confirm_key(draft)
        payload = cast(dict[str, object], draft["payload"])
        draft_id = _payload_id(draft, "draft_id")
        financial = self.financial_database_url
        corrections = SettlementCorrectionService(financial)
        if kind == "REFUND" and variant in {"USD", "PET", "CREDIT_CUSTOMER"}:
            return RefundService(self.database_url, financial).confirm_draft(
                property_id, draft_id, actor=actor
            )
        if kind in {"REFUND", "DEPOSIT_FORFEITURE"} and variant in {
            "RESERVATION_OUTCOME",
            "RESERVATION_CORRECTION",
        }:
            return ReservationDepositDraftService(self.database_url, financial).confirm(
                property_id, _payload_id(payload, "reservation_id"), draft_id, actor=actor
            )
        if kind == "DEPOSIT_FORFEITURE" and variant == "LEASE_FORFEITURE":
            return LeaseDepositForfeitureService(financial).confirm(
                property_id, _payload_id(payload, "deposit_id"), draft_id, actor=actor
            )
        if kind == "DEPOSIT_FORFEITURE" and variant == "LEASE_FORFEITURE_REVERSAL":
            return LeaseDepositForfeitureService(financial).confirm_reversal(
                property_id, _payload_id(payload, "disposition_id"), draft_id, actor=actor
            )
        if kind == "DEPOSIT_FORFEITURE" and variant == "DEPOSIT_RECEIPT_REVERSAL":
            return DepositReceiptReversalService(financial).confirm(
                property_id, _payload_id(payload, "receipt_id"), draft_id, actor=actor
            )
        if kind == "PAYMENT_MOVE":
            return PaymentMoveService(financial).confirm(property_id, draft_id, actor=actor)
        if kind == "FINAL_SETTLEMENT":
            return FinalSettlementService(financial).confirm(property_id, draft_id, actor=actor)
        if kind == "PAYMENT_RETURN":
            return PaymentReturnService(financial).confirm(property_id, draft_id, actor=actor)
        if kind == "ADJUSTMENT_REVERSAL":
            return AdjustmentReversalService(financial).confirm(property_id, draft_id, actor=actor)
        if kind == "SETTLEMENT_CORRECTION":
            correction: dict[tuple[str, str | None], Confirm] = {
                ("EXTRA_CHARGE", None): lambda p, d, a: corrections.confirm_extra_charge(
                    p, d, actor=a
                ),
                ("CHARGE_REDUCTION", None): lambda p, d, a: corrections.confirm_charge_reduction(
                    p, d, actor=a
                ),
                (
                    "CHARGE_REDUCTION",
                    "LATE_PAYMENT_CHARGE",
                ): lambda p, d, a: corrections.confirm_late_charge_reduction(p, d, actor=a),
                ("REFUND", None): lambda p, d, a: corrections.confirm_refund(p, d, actor=a),
                (
                    "REFUND",
                    "LATE_PAYMENT_CHARGE",
                ): lambda p, d, a: corrections.confirm_late_charge_refund(p, d, actor=a),
                (
                    "PET_DAMAGE_RECLASSIFICATION",
                    None,
                ): lambda p, d, a: corrections.confirm_pet_classification(p, d, actor=a),
                ("REFUND_RETURN", None): lambda p, d, a: corrections.confirm_refund_return(
                    p, d, actor=a
                ),
                (
                    "HELD_VALUE_REFUND",
                    None,
                ): lambda p, d, a: corrections.confirm_held_value_refund(p, d, actor=a),
                (
                    "FORFEITURE_REVERSAL",
                    None,
                ): lambda p, d, a: corrections.confirm_forfeiture_reversal(p, d, actor=a),
                (
                    "RETURNED_PAYMENT",
                    None,
                ): lambda p, d, a: corrections.confirm_returned_payment(p, d, actor=a),
                (
                    "DEPOSIT_RECEIPT_CORRECTION",
                    None,
                ): lambda p, d, a: corrections.confirm_deposit_receipt_correction(p, d, actor=a),
                ("RETURN_REVERSAL", None): lambda p, d, a: corrections.confirm_return_reversal(
                    p, d, actor=a
                ),
                ("PAYMENT_MOVE", None): lambda p, d, a: PaymentMoveService(
                    financial
                ).confirm_correction(p, d, actor=a),
                ("ADJUSTMENT_REVERSAL", None): lambda p, d, a: AdjustmentReversalService(
                    financial
                ).confirm_correction(p, d, actor=a),
            }
            chosen = correction.get((variant, target))
            if chosen is not None:
                return chosen(property_id, draft_id, actor)
        raise DraftConfirmNotAvailable("This draft has no confirm through the shared route")
