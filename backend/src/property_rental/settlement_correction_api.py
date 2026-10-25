"""Record routes for post-settlement corrections with no DL-032 plan, and the Adjustment
reversal draft (V1-056 slice 11e-2; API-072, DB-SETTLE-003).

Each correction route records one ``SETTLEMENT_CORRECTION`` draft of a closed Final Settlement
(``final_settlements.prepare``); it has no financial effect until a ``financial.approve`` holder
confirms it through the shared draft routes (``financial_draft_api.py``).

- An extra charge (``EXTRA_CHARGE``): a Damage or Miscellaneous charge found after closure.
- A charge reduction (``CHARGE_REDUCTION``) of an unpaid Invoice line or Late-payment Charge.
- A returned Payment (``RETURNED_PAYMENT``) whose records the Settlement relied on.
- A wrong-Unit Payment move (``PAYMENT_MOVE``) of an allocation the Settlement relied on.
- An Adjustment reversal (``ADJUSTMENT_REVERSAL``) of a credit Adjustment of the Lease.

The plain Adjustment reversal draft (kind ``ADJUSTMENT_REVERSAL``, ``invoices.adjust``) reverses a
credit Adjustment recorded by mistake before closure.

A record the form chose that does not fit answers 422 on its field; a named business-state
refusal answers 409 with its own code. No answer shows database text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Annotated, Final, Literal, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationInfo, field_validator

from property_rental.adjustment_reversal import (
    ADJUSTMENT_REVERSAL_PREPARE_CAPABILITY,
    AdjustmentReversalAuthorizationError,
    AdjustmentReversalConflictError,
    AdjustmentReversalInvalidError,
    AdjustmentReversalKeyReused,
    AdjustmentReversalNotFoundError,
    AdjustmentReversalService,
    AdjustmentReversalUnavailableError,
    RecordAdjustmentReversalCommand,
    RecordSettlementAdjustmentReversalCommand,
)
from property_rental.allocation_receipt_api import Reason, _mutation
from property_rental.api_refusals import (
    ADJUSTMENT_REVERSAL_ALREADY_REVERSED,
    ADJUSTMENT_REVERSAL_BY_RESOLUTION,
    ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND,
    ADJUSTMENT_REVERSAL_DRAFT_WAITING,
    ADJUSTMENT_REVERSAL_INVOICE_NOT_ISSUED,
    ADJUSTMENT_REVERSAL_NOT_CREDIT,
    ADJUSTMENT_REVERSAL_NOT_OF_SETTLEMENT,
    ADJUSTMENT_REVERSAL_OF_CORRECTION,
    ADJUSTMENT_REVERSAL_ONLY_CHARGE_REDUCTION,
    ADJUSTMENT_REVERSAL_THROUGH_CORRECTION,
    ADJUSTMENT_REVERSAL_TOO_LARGE,
    CORRECTION_CORRECTED_INVOICE_NOT_OF_SETTLEMENT,
    CORRECTION_DAMAGE_TO_PRIMARY,
    CORRECTION_DUE_DATE_BEFORE_ISSUE,
    CORRECTION_FINDING_BILLED,
    CORRECTION_FINDING_NOT_CURRENT,
    CORRECTION_INVOICE_LINE_NOT_FOUND,
    CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT,
    CORRECTION_PAID_BY_DEPOSIT,
    CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT,
    CORRECTION_SETTLEMENT_NOT_CLOSED,
    CORRECTION_WOULD_RELEASE_PAID,
    IDEMPOTENCY_KEY_REUSED,
    MOVE_CORRECTION_ALLOCATION_NOT_FOUND,
    MOVE_CORRECTION_ALLOCATION_REVERSED,
    MOVE_CORRECTION_NOT_OF_SETTLEMENT,
    MOVE_CORRECTION_OTHER_SETTLEMENT,
    MOVE_CORRECTION_USE_MOVE_DRAFT,
    PAYMENT_MOVE_TOO_LARGE,
    PAYMENT_RETURN_FORFEITURE_ACTIVE,
    PAYMENT_RETURN_TOO_LARGE,
    RETURNED_PAYMENT_DEPOSIT_LEFT,
    RETURNED_PAYMENT_DEPOSIT_MIXED,
    RETURNED_PAYMENT_NOT_FOUND,
    RETURNED_PAYMENT_OTHER_SETTLEMENT,
    RETURNED_PAYMENT_OTHER_SETTLEMENT_USE,
    RETURNED_PAYMENT_PAY_BACK_HELD,
    RETURNED_PAYMENT_TWO_SETTLEMENTS,
    RETURNED_PAYMENT_USE_RETURN_DRAFT,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.credit_refund_api import CreditRefundRequestRoute, Key, _financial_json
from property_rental.draft_record_api import PAYMENT_MOVE_REFUSALS, PAYMENT_RETURN_REFUSALS
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementUnavailableError,
)
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.financial_draft import FINAL_SETTLEMENTS_PREPARE_CAPABILITY
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import (
    Evidence,
    Identity,
    Memo,
    MinorUnits,
    StrictInput,
    _actor,
    _queries,
)
from property_rental.payment_move import (
    PaymentMoveAuthorizationError,
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveKeyReused,
    PaymentMoveNotFoundError,
    PaymentMoveService,
    PaymentMoveUnavailableError,
    RecordSettlementPaymentMoveCommand,
)
from property_rental.settings import Settings
from property_rental.settlement_correction import (
    ExtraChargeCategory,
    RecordChargeReductionCorrectionCommand,
    RecordExtraChargeCorrectionCommand,
    RecordLateChargeReductionCorrectionCommand,
    RecordReturnedPaymentCorrectionCommand,
    SettlementCorrectionService,
)

T = TypeVar("T")


class ExtraChargeInput(StrictInput):
    """A Damage charge names its inspection finding; a Miscellaneous charge names none. The
    reason, the evidence reference and the Due Date reason are at most 500 characters, because
    the one-time charge record keeps them. The Due Date override and its reason come together.
    Each mismatch is refused on its field (review round 1)."""

    category: Literal["MISCELLANEOUS_CHARGES", "DAMAGE_CHARGES"]
    description: Reason
    amount_usd_cents: MinorUnits
    evidence_reference: Evidence
    reason: Evidence
    inspection_damage_finding_id: Annotated[Identity | None, Field(validate_default=True)] = None
    corrects_invoice_id: Identity | None = None
    due_date: date | None = None
    due_date_reason: Annotated[Evidence | None, Field(validate_default=True)] = None

    @field_validator("inspection_damage_finding_id")
    @classmethod
    def _finding_fits_category(cls, value: UUID | None, info: ValidationInfo) -> UUID | None:
        if "category" in info.data and (info.data["category"] == "DAMAGE_CHARGES") != (
            value is not None
        ):
            raise ValueError("a Damage charge names its finding; a Miscellaneous charge none")
        return value

    @field_validator("due_date_reason")
    @classmethod
    def _reason_with_due_date(cls, value: str | None, info: ValidationInfo) -> str | None:
        if "due_date" in info.data and (info.data["due_date"] is None) != (value is None):
            raise ValueError("the Due Date override and its reason come together")
        return value


class ChargeReductionInput(StrictInput):
    invoice_id: Identity
    invoice_line_id: Identity
    amount_usd_cents: MinorUnits
    reason: Evidence


class LateChargeReductionInput(StrictInput):
    late_payment_charge_id: Identity
    amount_usd_cents: MinorUnits
    reason: Evidence


class ReturnedPaymentInput(StrictInput):
    payment_id: Identity
    reason: Evidence
    evidence_reference: Evidence


class MoveCorrectionInput(StrictInput):
    allocation_id: Identity
    target_invoice_id: Identity
    reason: Reason
    source_acknowledgement: Memo
    target_acknowledgement: Memo


class AdjustmentReversalCorrectionInput(StrictInput):
    adjustment_id: Identity
    reason: Reason


class AdjustmentReversalInput(StrictInput):
    reason: Reason


class CorrectionFlow(Protocol):
    def extra_charge(
        self,
        property_id: UUID,
        command: RecordExtraChargeCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def charge_reduction(
        self,
        property_id: UUID,
        command: RecordChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def late_charge_reduction(
        self,
        property_id: UUID,
        command: RecordLateChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def returned_payment(
        self,
        property_id: UUID,
        command: RecordReturnedPaymentCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def payment_move(
        self,
        property_id: UUID,
        command: RecordSettlementPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def adjustment_reversal_correction(
        self,
        property_id: UUID,
        command: RecordSettlementAdjustmentReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def adjustment_reversal(
        self,
        property_id: UUID,
        command: RecordAdjustmentReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


class CorrectionUnavailable(RuntimeError):
    """The financial database is not configured."""


@dataclass(frozen=True, slots=True)
class PostgresCorrectionFlow:
    financial_database_url: str | None

    def _url(self) -> str:
        if self.financial_database_url is None:
            raise CorrectionUnavailable("Post-settlement corrections are unavailable")
        return self.financial_database_url

    def extra_charge(
        self,
        property_id: UUID,
        command: RecordExtraChargeCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_extra_charge(
            property_id, command, actor=actor
        )

    def charge_reduction(
        self,
        property_id: UUID,
        command: RecordChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_charge_reduction(
            property_id, command, actor=actor
        )

    def late_charge_reduction(
        self,
        property_id: UUID,
        command: RecordLateChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_late_charge_reduction(
            property_id, command, actor=actor
        )

    def returned_payment(
        self,
        property_id: UUID,
        command: RecordReturnedPaymentCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_returned_payment(
            property_id, command, actor=actor
        )

    def payment_move(
        self,
        property_id: UUID,
        command: RecordSettlementPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentMoveService(self._url()).record_correction(property_id, command, actor=actor)

    def adjustment_reversal_correction(
        self,
        property_id: UUID,
        command: RecordSettlementAdjustmentReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return AdjustmentReversalService(self._url()).record_correction(
            property_id, command, actor=actor
        )

    def adjustment_reversal(
        self,
        property_id: UUID,
        command: RecordAdjustmentReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return AdjustmentReversalService(self._url()).record(property_id, command, actor=actor)


NOT_FOUND_ERRORS: Final = (
    FinalSettlementNotFoundError,
    PaymentMoveNotFoundError,
    AdjustmentReversalNotFoundError,
)
AUTHORIZATION_ERRORS: Final = (
    FinalSettlementAuthorizationError,
    PaymentMoveAuthorizationError,
    AdjustmentReversalAuthorizationError,
)
INVALID_ERRORS: Final = (
    FinalSettlementInvalidError,
    PaymentMoveInvalidError,
    AdjustmentReversalInvalidError,
)
KEY_REUSED_ERRORS: Final = (
    FinalSettlementKeyReused,
    PaymentMoveKeyReused,
    AdjustmentReversalKeyReused,
)
CONFLICT_ERRORS: Final = (
    FinalSettlementConflictError,
    PaymentMoveConflictError,
    AdjustmentReversalConflictError,
)
UNAVAILABLE_ERRORS: Final = (
    FinalSettlementUnavailableError,
    PaymentMoveUnavailableError,
    AdjustmentReversalUnavailableError,
    CorrectionUnavailable,
)

# Every correction recorder refuses an open Settlement. (The waiting-source refusal of the
# DL-032 plan recorders belongs to slice 11e-3; these recorders never raise it, review round 1.)
CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "A post-settlement correction needs a closed Final Settlement": (
            CORRECTION_SETTLEMENT_NOT_CLOSED
        ),
    }
)
EXTRA_CHARGE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        "A Damage charge goes to the Primary Tenant": CORRECTION_DAMAGE_TO_PRIMARY,
        "The corrected Invoice is not an Invoice of this Final Settlement": (
            CORRECTION_CORRECTED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The corrected Invoice is not an issued obligation of this Final Settlement": (
            CORRECTION_CORRECTED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The damage finding is already billed": CORRECTION_FINDING_BILLED,
        "The damage finding is not on the current inspection": CORRECTION_FINDING_NOT_CURRENT,
        "Inspection damage finding was not found": CORRECTION_FINDING_NOT_CURRENT,
        "The extra charge Due Date precedes the issue date": CORRECTION_DUE_DATE_BEFORE_ISSUE,
    }
)
REDUCTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        "A Deposit application paid this obligation at Final Settlement": (
            CORRECTION_PAID_BY_DEPOSIT
        ),
        "The charge reduction would release paid value": CORRECTION_WOULD_RELEASE_PAID,
        "The reduced Invoice is not an Invoice of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The reduced Invoice is not an issued obligation of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "Invoice line was not found": CORRECTION_INVOICE_LINE_NOT_FOUND,
        "The reduced Late-payment Charge is not a Charge of this Final Settlement": (
            CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT
        ),
        "The reduced Late-payment Charge is not an open obligation of this Final Settlement": (
            CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT
        ),
    }
)
RETURNED_PAYMENT_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        **PAYMENT_RETURN_REFUSALS,
        "A Deposit this Payment funded also holds another Payment's money and keeps a forfeiture "
        "beside a Deposit application; this correction cannot return the Payment": (
            RETURNED_PAYMENT_DEPOSIT_MIXED
        ),
        "A Deposit this Payment funded has a Deposit application of another Final Settlement": (
            RETURNED_PAYMENT_OTHER_SETTLEMENT_USE
        ),
        "A Deposit this Payment funded has an active forfeiture outside this Final Settlement's "
        "Lease; reverse the forfeiture first": PAYMENT_RETURN_FORFEITURE_ACTIVE,
        "A Deposit this Payment funded holds the Customer's pay-back money beside a forfeiture; "
        "this correction cannot return the Payment": RETURNED_PAYMENT_PAY_BACK_HELD,
        "A Deposit this Payment funded would still hold money after the return": (
            RETURNED_PAYMENT_DEPOSIT_LEFT
        ),
        "Another closed Final Settlement relied on this Payment's records; a Payment that two "
        "closed Final Settlements relied on cannot be returned": RETURNED_PAYMENT_TWO_SETTLEMENTS,
        "This Final Settlement did not rely on this Payment's records; return it through a "
        "correction of the Final Settlement that did": RETURNED_PAYMENT_OTHER_SETTLEMENT,
        "This Final Settlement did not rely on this Payment's records; return it with a Payment "
        "return draft": RETURNED_PAYMENT_USE_RETURN_DRAFT,
        "The returned-Payment correction draft exceeds the stored draft size of 16000 bytes (the "
        "Payment's records)": PAYMENT_RETURN_TOO_LARGE,
        "Payment was not found": RETURNED_PAYMENT_NOT_FOUND,
    }
)
MOVE_CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        **PAYMENT_MOVE_REFUSALS,
        "A correction of another Final Settlement wrote this allocation; this correction cannot "
        "move it": MOVE_CORRECTION_OTHER_SETTLEMENT,
        "An allocation made after the closure moves through the ordinary move draft": (
            MOVE_CORRECTION_USE_MOVE_DRAFT
        ),
        "The allocation does not pay an Invoice of this Final Settlement's Lease": (
            MOVE_CORRECTION_NOT_OF_SETTLEMENT
        ),
        "The allocation is already reversed": MOVE_CORRECTION_ALLOCATION_REVERSED,
        "Payment allocation was not found": MOVE_CORRECTION_ALLOCATION_NOT_FOUND,
        "The Payment move correction draft exceeds the stored draft size of 16000 bytes "
        "(acknowledgements and the line split of the correct Invoice)": PAYMENT_MOVE_TOO_LARGE,
    }
)
# The Adjustment's own state, before and after closure (migrations 145 and 147).
ADJUSTMENT_STATE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "Only a credit Adjustment is reversed by an Adjustment reversal draft": (
            ADJUSTMENT_REVERSAL_NOT_CREDIT
        ),
        "The Adjustment is already reversed": ADJUSTMENT_REVERSAL_ALREADY_REVERSED,
        "The Adjustment's Invoice is not an issued Invoice": ADJUSTMENT_REVERSAL_INVOICE_NOT_ISSUED,
        "An Adjustment that a resolution wrote is not reversed by an Adjustment reversal draft": (
            ADJUSTMENT_REVERSAL_BY_RESOLUTION
        ),
        "Another Adjustment reversal draft of this Adjustment is waiting": (
            ADJUSTMENT_REVERSAL_DRAFT_WAITING
        ),
    }
)
ADJUSTMENT_REVERSAL_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **ADJUSTMENT_STATE_REFUSALS,
        "An Adjustment of a post-settlement correction is not reversed by an Adjustment reversal "
        "draft": ADJUSTMENT_REVERSAL_OF_CORRECTION,
        "The Lease's Final Settlement is closed; the Adjustment is reversed through a correction "
        "of that Final Settlement": ADJUSTMENT_REVERSAL_THROUGH_CORRECTION,
        "The Adjustment reversal draft exceeds the stored draft size of 16000 bytes": (
            ADJUSTMENT_REVERSAL_TOO_LARGE
        ),
    }
)
ADJUSTMENT_CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        **ADJUSTMENT_STATE_REFUSALS,
        "The Adjustment is not on an Invoice of this Final Settlement's Lease": (
            ADJUSTMENT_REVERSAL_NOT_OF_SETTLEMENT
        ),
        # The id is a body field here, so an unknown one is 422 on it (review round 1).
        "Invoice Adjustment was not found": ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND,
        "Of the Adjustments of post-settlement corrections, only a charge reduction's is "
        "reversed by an Adjustment reversal correction": ADJUSTMENT_REVERSAL_ONLY_CHARGE_REDUCTION,
        "The Adjustment reversal correction draft exceeds the stored draft size of 16000 bytes": (
            ADJUSTMENT_REVERSAL_TOO_LARGE
        ),
    }
)


def _invoke(call: Callable[[], T], refusals: Mapping[str, Refusal]) -> T:
    try:
        return call()
    except (*NOT_FOUND_ERRORS, *AUTHORIZATION_ERRORS, *INVALID_ERRORS, *CONFLICT_ERRORS) as exc:
        refusal = database_refusal(exc, refusals)
        if refusal is not None:
            raise RefusedRequest(refusal) from exc
        if isinstance(exc, KEY_REUSED_ERRORS):
            raise RefusedRequest(IDEMPOTENCY_KEY_REUSED) from exc
        if isinstance(exc, NOT_FOUND_ERRORS):
            raise HTTPException(404) from exc
        if isinstance(exc, AUTHORIZATION_ERRORS):
            raise HTTPException(403) from exc
        if isinstance(exc, INVALID_ERRORS):
            raise HTTPException(422) from exc
        raise HTTPException(409) from exc
    except UNAVAILABLE_ERRORS as exc:
        raise HTTPException(503) from exc


def _at(payload: Mapping[str, object], path: tuple[str, ...]) -> object:
    value: object = payload
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _correction(
    value: object,
    property_id: UUID,
    settlement_id: UUID,
    variant: str,
    subject: Mapping[tuple[str, ...], object],
) -> dict[str, object]:
    """The recorded correction draft, checked against the path and the form before it is
    shown: its Property, kind, variant, Settlement and the records the form names (each
    ``subject`` path of the payload holds its value; ``None`` means the key is absent)."""
    payload = value.get("payload") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("property_id") != str(property_id)
        or value.get("kind") != "SETTLEMENT_CORRECTION"
        or not isinstance(payload, dict)
        or payload.get("variant") != variant
        or payload.get("final_settlement_id") != str(settlement_id)
        or any(_at(payload, path) != expected for path, expected in subject.items())
    ):
        raise HTTPException(503)
    return value


def _adjustment_draft(value: object, property_id: UUID, adjustment_id: UUID) -> dict[str, object]:
    payload = value.get("payload") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("property_id") != str(property_id)
        or value.get("kind") != "ADJUSTMENT_REVERSAL"
        or not isinstance(payload, dict)
        or payload.get("invoice_adjustment_id") != str(adjustment_id)
    ):
        raise HTTPException(503)
    return value


def create_settlement_correction_router(
    resolver: ActorResolver, flow: CorrectionFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["financial-drafts"], route_class=CreditRefundRequestRoute
    )

    def context(request: Request, property_id: UUID, capability: str) -> AuthenticatedActor:
        _queries(request, set())
        actor = _actor(request, resolver)
        _mutation(request, settings)
        # A Property the person may not prepare this draft in is hidden.
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise HTTPException(404)
        bind_financial_property(request, property_id)
        return actor

    def envelope(request: Request, result: object) -> dict[str, object]:
        return {"data": result, "meta": financial_metadata(request)}

    base = "/properties/{property_id}/final-settlements/{settlement_id}/corrections"
    prepare = FINAL_SETTLEMENTS_PREPARE_CAPABILITY

    @router.post(f"{base}/extra-charges", status_code=201, dependencies=[Depends(_financial_json)])
    def record_extra_charge(
        property_id: Identity,
        settlement_id: Identity,
        body: ExtraChargeInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A charge found after closure, billed to the Customer of the corrected obligation."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordExtraChargeCorrectionCommand(
                idempotency_key,
                settlement_id,
                ExtraChargeCategory(body.category),
                body.description,
                body.amount_usd_cents,
                body.evidence_reference,
                body.reason,
                body.inspection_damage_finding_id,
                body.corrects_invoice_id,
                body.due_date,
                body.due_date_reason,
            ),
            EXTRA_CHARGE_REFUSALS,
        )
        result = _invoke(
            lambda: flow.extra_charge(property_id, command, actor=actor), EXTRA_CHARGE_REFUSALS
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "EXTRA_CHARGE",
                {("charge", "amount_usd_cents"): body.amount_usd_cents},
            ),
        )

    @router.post(
        f"{base}/charge-reductions", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_charge_reduction(
        property_id: Identity,
        settlement_id: Identity,
        body: ChargeReductionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reduce an unpaid Invoice line of the Settlement's Lease by a credit Adjustment."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordChargeReductionCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.invoice_id,
                body.invoice_line_id,
                body.amount_usd_cents,
                body.reason,
            ),
            REDUCTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.charge_reduction(property_id, command, actor=actor), REDUCTION_REFUSALS
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "CHARGE_REDUCTION",
                {
                    ("target_kind",): None,
                    ("reduction", "invoice_line_id"): str(body.invoice_line_id),
                },
            ),
        )

    @router.post(
        f"{base}/late-charge-reductions", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_late_charge_reduction(
        property_id: Identity,
        settlement_id: Identity,
        body: LateChargeReductionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reduce an unpaid Late-payment Charge of the Settlement's Lease."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordLateChargeReductionCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.late_payment_charge_id,
                body.amount_usd_cents,
                body.reason,
            ),
            REDUCTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.late_charge_reduction(property_id, command, actor=actor),
            REDUCTION_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "CHARGE_REDUCTION",
                {
                    ("target_kind",): "LATE_PAYMENT_CHARGE",
                    ("reduction", "late_payment_charge_id"): str(body.late_payment_charge_id),
                },
            ),
        )

    @router.post(
        f"{base}/returned-payments", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_returned_payment(
        property_id: Identity,
        settlement_id: Identity,
        body: ReturnedPaymentInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Return a bounced Payment whose records the Settlement relied on (BR-SETTLE-013)."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordReturnedPaymentCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.payment_id,
                body.reason,
                body.evidence_reference,
            ),
            RETURNED_PAYMENT_REFUSALS,
        )
        result = _invoke(
            lambda: flow.returned_payment(property_id, command, actor=actor),
            RETURNED_PAYMENT_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "RETURNED_PAYMENT",
                {("payment_id",): str(body.payment_id)},
            ),
        )

    @router.post(f"{base}/payment-moves", status_code=201, dependencies=[Depends(_financial_json)])
    def record_payment_move(
        property_id: Identity,
        settlement_id: Identity,
        body: MoveCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Move an allocation the Settlement relied on to the correct Invoice on another Unit
        (BR-PAY-042)."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordSettlementPaymentMoveCommand(
                idempotency_key,
                settlement_id,
                body.allocation_id,
                body.target_invoice_id,
                body.reason,
                body.source_acknowledgement,
                body.target_acknowledgement,
            ),
            MOVE_CORRECTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.payment_move(property_id, command, actor=actor),
            MOVE_CORRECTION_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "PAYMENT_MOVE",
                {("source_allocation_id",): str(body.allocation_id)},
            ),
        )

    @router.post(
        f"{base}/adjustment-reversals", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_adjustment_reversal_correction(
        property_id: Identity,
        settlement_id: Identity,
        body: AdjustmentReversalCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reverse a credit Adjustment of the Settlement's Lease after closure."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordSettlementAdjustmentReversalCommand(
                idempotency_key, settlement_id, body.adjustment_id, body.reason
            ),
            ADJUSTMENT_CORRECTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.adjustment_reversal_correction(property_id, command, actor=actor),
            ADJUSTMENT_CORRECTION_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "ADJUSTMENT_REVERSAL",
                {("invoice_adjustment_id",): str(body.adjustment_id)},
            ),
        )

    @router.post(
        "/properties/{property_id}/invoice-adjustments/{adjustment_id}/reversal-drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_adjustment_reversal(
        property_id: Identity,
        adjustment_id: Identity,
        body: AdjustmentReversalInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reverse a credit Adjustment recorded by mistake (``invoices.adjust``; BR-INV-044)."""
        actor = context(request, property_id, ADJUSTMENT_REVERSAL_PREPARE_CAPABILITY)
        command = _invoke(
            lambda: RecordAdjustmentReversalCommand(idempotency_key, adjustment_id, body.reason),
            ADJUSTMENT_REVERSAL_REFUSALS,
        )
        result = _invoke(
            lambda: flow.adjustment_reversal(property_id, command, actor=actor),
            ADJUSTMENT_REVERSAL_REFUSALS,
        )
        return envelope(request, _adjustment_draft(result, property_id, adjustment_id))

    return router
