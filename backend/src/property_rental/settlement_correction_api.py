"""Record routes for post-settlement corrections and the Adjustment reversal draft (V1-056 slices
11e-2 and 11e-3; API-072, DB-SETTLE-003).

Each correction route records one ``SETTLEMENT_CORRECTION`` draft of a closed Final Settlement
(``final_settlements.prepare``); it has no financial effect until a ``financial.approve`` holder
confirms it through the shared draft routes (``financial_draft_api.py``).

- An extra charge (``EXTRA_CHARGE``): a Damage or Miscellaneous charge found after closure.
- A charge reduction (``CHARGE_REDUCTION``) of an unpaid Invoice line or Late-payment Charge.
- A returned Payment (``RETURNED_PAYMENT``) whose records the Settlement relied on.
- A wrong-Unit Payment move (``PAYMENT_MOVE``) of an allocation the Settlement relied on.
- An Adjustment reversal (``ADJUSTMENT_REVERSAL``) of a credit Adjustment of the Lease.

Slice 11e-3 adds the corrections whose released value follows a DL-032 plan (``steps`` and
``pet_remainder`` as in the Final Settlement draft): a Refund of a paid wrong charge or
Late-payment Charge (``REFUND``), a pet damage classification (``PET_DAMAGE_RECLASSIFICATION``), a
returned Refund (``REFUND_RETURN``), a held-value Refund (``HELD_VALUE_REFUND``), a forfeiture
reversal (``FORFEITURE_REVERSAL``) and a Deposit receipt correction
(``DEPOSIT_RECEIPT_CORRECTION``), plus the return reversal (``RETURN_REVERSAL``) with no plan.

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
    CORRECTION_FORFEITURE_ALREADY_REVERSED,
    CORRECTION_FORFEITURE_NOT_FOUND,
    CORRECTION_FORFEITURE_OTHER_ACTIVE,
    CORRECTION_HELD_FROM_NOT_FOUND,
    CORRECTION_HELD_FROM_NOT_RETURN_ONLY,
    CORRECTION_HELD_VALUE_NOTHING_LEFT,
    CORRECTION_HELD_VALUE_OVER,
    CORRECTION_INVOICE_LINE_NOT_FOUND,
    CORRECTION_LATE_CHARGE_NOT_OF_SETTLEMENT,
    CORRECTION_NEW_CUSTOMER_CHOICE,
    CORRECTION_NEW_REFUND_METHOD_OFF,
    CORRECTION_ONE_REFUND_CHOICE,
    CORRECTION_PAID_BY_DEPOSIT,
    CORRECTION_PET_LINE_NOT_DAMAGE,
    CORRECTION_PET_SAME,
    CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT,
    CORRECTION_REFUND_METHOD_OFF,
    CORRECTION_REFUND_NOT_FOUND,
    CORRECTION_REFUND_NOT_RETURNABLE,
    CORRECTION_REFUND_OVER_CHARGE,
    CORRECTION_REFUND_OVER_PAID,
    CORRECTION_REFUND_RELEASES_NOTHING,
    CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT,
    CORRECTION_RELEASED_CREDIT_FIRST,
    CORRECTION_RETURN_DATE,
    CORRECTION_RETURN_ONLY_NO_STEPS,
    CORRECTION_RETURN_OVER_REFUND,
    CORRECTION_RETURNED_DEPOSIT_OFF_PATH,
    CORRECTION_RETURNED_MONEY_PAYS_DEBT,
    CORRECTION_SETTLEMENT_NOT_CLOSED,
    CORRECTION_SOURCE_DRAFT_WAITING,
    CORRECTION_STEP_OUTSIDE_SETTLEMENT,
    CORRECTION_WOULD_RELEASE_PAID,
    FINAL_SETTLEMENT_LEASE_NOT_TERMINATED,
    FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT,
    FINAL_SETTLEMENT_RECORD_UNCLEAR,
    FINAL_SETTLEMENT_STEP_ORDER,
    IDEMPOTENCY_KEY_REUSED,
    MOVE_CORRECTION_ALLOCATION_NOT_FOUND,
    MOVE_CORRECTION_ALLOCATION_REVERSED,
    MOVE_CORRECTION_NOT_OF_SETTLEMENT,
    MOVE_CORRECTION_OTHER_SETTLEMENT,
    MOVE_CORRECTION_USE_MOVE_DRAFT,
    PAYMENT_MOVE_TOO_LARGE,
    PAYMENT_RETURN_FORFEITURE_ACTIVE,
    PAYMENT_RETURN_TOO_LARGE,
    RECEIPT_CORRECTION_ALREADY_REVERSED,
    RECEIPT_CORRECTION_CREDIT_AFTER_REAPPLY,
    RECEIPT_CORRECTION_DEPOSIT_HAS_RECEIPT,
    RECEIPT_CORRECTION_DEPOSIT_KEPT,
    RECEIPT_CORRECTION_DEPOSIT_NOT_EMPTY,
    RECEIPT_CORRECTION_DEPOSIT_NOT_FOUND,
    RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE,
    RECEIPT_CORRECTION_DRAFT_WAITING,
    RECEIPT_CORRECTION_FORFEIT_NEW_MONEY_ONLY,
    RECEIPT_CORRECTION_FORFEITURE_ACTIVE,
    RECEIPT_CORRECTION_HELD_MONEY_FIRST,
    RECEIPT_CORRECTION_MIXED_DEPOSIT,
    RECEIPT_CORRECTION_NO_CHANGE,
    RECEIPT_CORRECTION_NO_RECOVERY,
    RECEIPT_CORRECTION_NOT_FOUND,
    RECEIPT_CORRECTION_NOT_OF_SETTLEMENT,
    RECEIPT_CORRECTION_NOTHING_TO_FORFEIT,
    RECEIPT_CORRECTION_OTHER_SETTLEMENT_USE,
    RECEIPT_CORRECTION_OUTCOME_NEEDED,
    RECEIPT_CORRECTION_OUTCOME_NOT_TAKEN,
    RECEIPT_CORRECTION_OVER_REQUIRED,
    RECEIPT_CORRECTION_PAYMENT_CANNOT_FUND,
    RECEIPT_CORRECTION_PAYMENT_NOT_RECEIVED,
    RECEIPT_CORRECTION_RECEIPTS_OVER,
    RECEIPT_CORRECTION_RECOVERY_ON_CLOSED_LEASE,
    RECEIPT_CORRECTION_RESERVATION_REFUND,
    RECEIPT_CORRECTION_SHARED_DEPOSIT_REFUND,
    RECEIPT_CORRECTION_STEP_BEFORE_REAPPLY,
    RECEIPT_CORRECTION_STEP_REPEATS_REAPPLY,
    RECEIPT_CORRECTION_TOO_LARGE,
    RETURN_REVERSAL_ALREADY_REVERSED,
    RETURN_REVERSAL_DRAFT_WAITING,
    RETURN_REVERSAL_FORFEITED,
    RETURN_REVERSAL_NOT_FOUND,
    RETURN_REVERSAL_REFUND_RETURNED_FIRST,
    RETURN_REVERSAL_TOO_LARGE,
    RETURN_REVERSAL_VALUE_USED,
    RETURN_REVERSAL_WAITS_FOR_OWNER,
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
    MAX_SETTLEMENT_STEPS,
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementUnavailableError,
    PetRemainderBasis,
    PetRemainderDecision,
    SettlementStep,
)
from property_rental.final_settlement_api import (
    FINAL_SETTLEMENT_PLAN_REFUSALS,
    PetRemainderInput,
    StepInput,
    _step,
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
    Instant,
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
    CorrectionDepositReceipt,
    ExtraChargeCategory,
    RecordChargeReductionCorrectionCommand,
    RecordDepositReceiptCorrectionCommand,
    RecordExtraChargeCorrectionCommand,
    RecordForfeitureReversalCorrectionCommand,
    RecordHeldValueRefundCorrectionCommand,
    RecordLateChargeReductionCorrectionCommand,
    RecordLateChargeRefundCorrectionCommand,
    RecordPetClassificationCorrectionCommand,
    RecordRefundCorrectionCommand,
    RecordRefundReturnCorrectionCommand,
    RecordReturnedPaymentCorrectionCommand,
    RecordReturnReversalCorrectionCommand,
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


# Slice 11e-3: the corrections with a DL-032 plan for the value they release, in the Final
# Settlement plan format of slice 11e-1. Every text these records keep is at most 500 characters.
class PlanInput(StrictInput):
    steps: Annotated[list[StepInput], Field(max_length=MAX_SETTLEMENT_STEPS)] = Field(
        default_factory=list
    )
    pet_remainder: PetRemainderInput | None = None


class RefundCorrectionInput(PlanInput):
    invoice_id: Identity
    invoice_line_id: Identity
    amount_usd_cents: MinorUnits
    refund_method_id: Identity
    reference_note: Evidence
    reason: Evidence


class LateChargeRefundCorrectionInput(PlanInput):
    late_payment_charge_id: Identity
    amount_usd_cents: MinorUnits
    refund_method_id: Identity
    reference_note: Evidence
    reason: Evidence


class PetClassificationCorrectionInput(PlanInput):
    invoice_id: Identity
    invoice_line_id: Identity
    pet_related: Annotated[bool, Field(strict=True)]
    evidence_reference: Evidence
    reason: Evidence


class RefundReturnCorrectionInput(PlanInput):
    """A new Refund is paid only when its method and reference note come together."""

    refund_id: Identity
    returned_amount_usd_cents: MinorUnits
    returned_at: Instant
    return_method_reference: Evidence
    evidence_reference: Evidence
    reason: Evidence
    new_refund_method_id: Identity | None = None
    new_refund_reference_note: Annotated[Evidence | None, Field(validate_default=True)] = None

    @field_validator("new_refund_reference_note")
    @classmethod
    def _note_with_method(cls, value: str | None, info: ValidationInfo) -> str | None:
        if "new_refund_method_id" in info.data and (info.data["new_refund_method_id"] is None) != (
            value is None
        ):
            raise ValueError("the new Refund method and its reference note come together")
        return value


class HeldValueRefundCorrectionInput(PlanInput):
    held_from_correction_id: Identity
    reason: Evidence
    new_refund_method_id: Identity
    new_refund_reference_note: Evidence


class ForfeitureReversalCorrectionInput(PlanInput):
    deposit_disposition_id: Identity
    reason: Evidence
    evidence_reference: Evidence
    refund_method_id: Identity
    reference_note: Evidence


class CorrectionReceiptInput(StrictInput):
    """A right receipt; the outcome and its reason come together."""

    deposit_id: Identity
    amount_usd_cents: MinorUnits
    outcome: Literal["DL_032", "FORFEIT"] | None = None
    outcome_reason: Annotated[Evidence | None, Field(validate_default=True)] = None

    @field_validator("outcome_reason")
    @classmethod
    def _reason_with_outcome(cls, value: str | None, info: ValidationInfo) -> str | None:
        if "outcome" in info.data and (info.data["outcome"] is None) != (value is None):
            raise ValueError("the outcome and its reason come together")
        return value


class DepositReceiptCorrectionInput(PlanInput):
    deposit_receipt_id: Identity
    reason: Evidence
    evidence_reference: Evidence
    receipts: Annotated[list[CorrectionReceiptInput], Field(max_length=2)] = Field(
        default_factory=list, validate_default=True
    )

    @field_validator("receipts")
    @classmethod
    def _receipts_fit_the_plan(
        cls, value: list[CorrectionReceiptInput], info: ValidationInfo
    ) -> list[CorrectionReceiptInput]:
        if len({receipt.deposit_id for receipt in value}) != len(value):
            raise ValueError("each new receipt goes into a different Deposit")
        if not value and (info.data.get("steps") or info.data.get("pet_remainder") is not None):
            raise ValueError("a DL-032 plan needs a new receipt")
        return value


class ReturnReversalCorrectionInput(StrictInput):
    earlier_correction_id: Identity
    reason: Evidence
    evidence_reference: Evidence


def _plan(body: PlanInput) -> tuple[tuple[SettlementStep, ...], PetRemainderDecision | None]:
    remainder = body.pet_remainder
    return (
        tuple(_step(step) for step in body.steps),
        None
        if remainder is None
        else PetRemainderDecision(
            PetRemainderBasis(remainder.basis), remainder.staff_reason, remainder.customer_choice
        ),
    )


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

    def refund(
        self,
        property_id: UUID,
        command: RecordRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def late_charge_refund(
        self,
        property_id: UUID,
        command: RecordLateChargeRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def pet_classification(
        self,
        property_id: UUID,
        command: RecordPetClassificationCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def refund_return(
        self,
        property_id: UUID,
        command: RecordRefundReturnCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def held_value_refund(
        self,
        property_id: UUID,
        command: RecordHeldValueRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordForfeitureReversalCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def deposit_receipt_correction(
        self,
        property_id: UUID,
        command: RecordDepositReceiptCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def return_reversal(
        self,
        property_id: UUID,
        command: RecordReturnReversalCorrectionCommand,
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

    def refund(
        self,
        property_id: UUID,
        command: RecordRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_refund(
            property_id, command, actor=actor
        )

    def late_charge_refund(
        self,
        property_id: UUID,
        command: RecordLateChargeRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_late_charge_refund(
            property_id, command, actor=actor
        )

    def pet_classification(
        self,
        property_id: UUID,
        command: RecordPetClassificationCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_pet_classification(
            property_id, command, actor=actor
        )

    def refund_return(
        self,
        property_id: UUID,
        command: RecordRefundReturnCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_refund_return(
            property_id, command, actor=actor
        )

    def held_value_refund(
        self,
        property_id: UUID,
        command: RecordHeldValueRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_held_value_refund(
            property_id, command, actor=actor
        )

    def forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordForfeitureReversalCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_forfeiture_reversal(
            property_id, command, actor=actor
        )

    def deposit_receipt_correction(
        self,
        property_id: UUID,
        command: RecordDepositReceiptCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_deposit_receipt_correction(
            property_id, command, actor=actor
        )

    def return_reversal(
        self,
        property_id: UUID,
        command: RecordReturnReversalCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return SettlementCorrectionService(self._url()).record_return_reversal(
            property_id, command, actor=actor
        )


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

# Slice 11e-3. Every plan correction refuses an open Settlement, waits for a draft on its sources
# and checks its DL-032 plan as the Final Settlement draft does (422 on the form field), with the
# correction's own plan rules; the two Final Settlement draft messages it never raises are left out.
PLAN_CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        "The Lease is not terminated": FINAL_SETTLEMENT_LEASE_NOT_TERMINATED,
        # Also raised for a receipt's Deposit of another Lease with an unclear record; the text
        # cannot tell which Lease, so it keeps the Final Settlement answer.
        "The termination record is ambiguous": FINAL_SETTLEMENT_RECORD_UNCLEAR,
        **{
            message: refusal
            for message, refusal in FINAL_SETTLEMENT_PLAN_REFUSALS.items()
            if message
            not in {
                "Final Settlement steps must follow the DL-032 order",
                "A Deposit has at most one Refund in a Final Settlement draft",
            }
        },
        "A draft on a source of this Final Settlement is waiting": CORRECTION_SOURCE_DRAFT_WAITING,
        "Post-settlement correction steps must follow the DL-032 order": (
            FINAL_SETTLEMENT_STEP_ORDER
        ),
        "A Deposit has at most one Refund in a post-settlement correction": (
            FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT
        ),
        "A post-settlement correction has one Refund method, reference note, recipient and "
        "agreement": CORRECTION_ONE_REFUND_CHOICE,
        "A Deposit keeps returned money only when no open debt can take it": (
            CORRECTION_RETURNED_MONEY_PAYS_DEBT
        ),
        "Customer Credit the correction releases pays its own Customer's open debt on this Lease "
        "before any Refund": CORRECTION_RELEASED_CREDIT_FIRST,
        "A correction needs the Customer's choice for this correction; an earlier correction's "
        "choice is not reused": CORRECTION_NEW_CUSTOMER_CHOICE,
        "A correction needs the Customer's choice for this correction; the Final Settlement's "
        "choice is not reused": CORRECTION_NEW_CUSTOMER_CHOICE,
        "A held-value correction uses at most what its earlier correction left in each Deposit": (
            CORRECTION_HELD_VALUE_OVER
        ),
        "The overlay names a Customer Credit outside this Final Settlement": (
            CORRECTION_STEP_OUTSIDE_SETTLEMENT
        ),
        "The overlay names a Deposit outside this Final Settlement": (
            CORRECTION_STEP_OUTSIDE_SETTLEMENT
        ),
        "The overlay names an obligation outside this Final Settlement": (
            CORRECTION_STEP_OUTSIDE_SETTLEMENT
        ),
    }
)
# A route whose form names the Refund method answers on that field; the pet classification and the
# receipt correction name a method only in a step, so they keep the Final Settlement answer.
METHOD_FIELD: Final[Mapping[str, Refusal]] = MappingProxyType(
    {"Refund Method is not active": CORRECTION_REFUND_METHOD_OFF}
)
NEW_METHOD_FIELD: Final[Mapping[str, Refusal]] = MappingProxyType(
    {"Refund Method is not active": CORRECTION_NEW_REFUND_METHOD_OFF}
)
REFUND_CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        **METHOD_FIELD,
        "Invoice line was not found": CORRECTION_INVOICE_LINE_NOT_FOUND,
        "The corrected Invoice is not an Invoice of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The corrected Invoice is not an issued obligation of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The Refund correction exceeds the charge on the line": CORRECTION_REFUND_OVER_CHARGE,
        "Credit excess exceeds the applied value of the line": CORRECTION_REFUND_OVER_PAID,
        "The Refund correction releases no paid value; an unpaid charge is removed by a charge "
        "reduction": CORRECTION_REFUND_RELEASES_NOTHING,
    }
)
LATE_CHARGE_REFUND_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        **METHOD_FIELD,
        "The corrected Late-payment Charge is not a Charge of this Final Settlement": (
            CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT
        ),
        "The corrected Late-payment Charge is not an open obligation of this Final Settlement": (
            CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT
        ),
        "The Refund correction exceeds the Late-payment Charge": CORRECTION_REFUND_OVER_CHARGE,
        "Credit excess exceeds the applied value of the Late-payment Charge": (
            CORRECTION_REFUND_OVER_PAID
        ),
        "The Refund correction releases no paid value; an unpaid charge is removed by a charge "
        "reduction": CORRECTION_REFUND_RELEASES_NOTHING,
    }
)
PET_CLASSIFICATION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        "Invoice line was not found": CORRECTION_INVOICE_LINE_NOT_FOUND,
        "The corrected Invoice is not an Invoice of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "The corrected Invoice is not an issued obligation of this Final Settlement": (
            CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT
        ),
        "A pet classification correction corrects only a Damage line billed from a finding of a "
        "move-out inspection of this Lease": CORRECTION_PET_LINE_NOT_DAMAGE,
        "The line already has this pet classification": CORRECTION_PET_SAME,
    }
)
REFUND_RETURN_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        **NEW_METHOD_FIELD,
        "Refund was not found": CORRECTION_REFUND_NOT_FOUND,
        "The returned Refund is not a Refund this correction may return": (
            CORRECTION_REFUND_NOT_RETURNABLE
        ),
        "The returned amount exceeds the Refund's net value": CORRECTION_RETURN_OVER_REFUND,
        "The return is dated before the Refund or in the future": CORRECTION_RETURN_DATE,
        "A return-only Deposit Refund correction has no DL-032 step": (
            CORRECTION_RETURN_ONLY_NO_STEPS
        ),
        "A returned Deposit pays debt or is refunded again only on the DL-032 path": (
            CORRECTION_RETURNED_DEPOSIT_OFF_PATH
        ),
    }
)
HELD_VALUE_REFUND_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        **NEW_METHOD_FIELD,
        "Post-settlement correction was not found": CORRECTION_HELD_FROM_NOT_FOUND,
        "Only a return-only returned-Refund correction leaves value for a later Refund": (
            CORRECTION_HELD_FROM_NOT_RETURN_ONLY
        ),
        "Nothing the earlier correction returned is left to refund": (
            CORRECTION_HELD_VALUE_NOTHING_LEFT
        ),
        "The Credit holds no returned value to refund": CORRECTION_HELD_VALUE_NOTHING_LEFT,
        "The Deposit holds no returned money to refund": CORRECTION_HELD_VALUE_NOTHING_LEFT,
        "The held value Refund correction would write nothing": CORRECTION_HELD_VALUE_NOTHING_LEFT,
        "A returned Deposit pays debt or is refunded again only on the DL-032 path": (
            CORRECTION_RETURNED_DEPOSIT_OFF_PATH
        ),
    }
)
FORFEITURE_REVERSAL_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        **METHOD_FIELD,
        "Lease Deposit forfeiture was not found": CORRECTION_FORFEITURE_NOT_FOUND,
        "The forfeiture is already reversed": CORRECTION_FORFEITURE_ALREADY_REVERSED,
        "Another forfeiture of this Deposit stays active; the reversal would not put the Deposit "
        "on the DL-032 path": CORRECTION_FORFEITURE_OTHER_ACTIVE,
    }
)
RECEIPT_CORRECTION_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **PLAN_CORRECTION_REFUSALS,
        "Deposit receipt was not found": RECEIPT_CORRECTION_NOT_FOUND,
        "This Deposit receipt is not of a Deposit of this Final Settlement's Lease": (
            RECEIPT_CORRECTION_NOT_OF_SETTLEMENT
        ),
        "This Deposit receipt is already reversed": RECEIPT_CORRECTION_ALREADY_REVERSED,
        "Only a received Payment's Deposit receipt can be corrected": (
            RECEIPT_CORRECTION_PAYMENT_NOT_RECEIVED
        ),
        "A draft that names this Deposit receipt, its Deposit or its Payment is waiting": (
            RECEIPT_CORRECTION_DRAFT_WAITING
        ),
        "A receipt correction must change the Deposit or the amount": RECEIPT_CORRECTION_NO_CHANGE,
        "The Deposit of a new receipt was not found": RECEIPT_CORRECTION_DEPOSIT_NOT_FOUND,
        "A new receipt goes only into a Deposit of this Final Settlement's Lease": (
            RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE
        ),
        # The target check reads every named Deposit's Lease first: a Reservation Deposit or a
        # Deposit of another Lease that is not terminated stops there.
        "Lease Deposit was not found": RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE,
        "The Lease is not terminated": RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE,
        "A new receipt cannot go into a Deposit the Property keeps": (
            RECEIPT_CORRECTION_DEPOSIT_KEPT
        ),
        "The Deposit already holds an active receipt from this Payment": (
            RECEIPT_CORRECTION_DEPOSIT_HAS_RECEIPT
        ),
        "A new receipt would exceed the Deposit's required amount": (
            RECEIPT_CORRECTION_OVER_REQUIRED
        ),
        "The new receipts take more than the corrected receipt frees": (
            RECEIPT_CORRECTION_RECEIPTS_OVER
        ),
        "The corrected receipt's Payment cannot fund this Deposit": (
            RECEIPT_CORRECTION_PAYMENT_CANNOT_FUND
        ),
        "A new receipt into a Deposit whose forfeiture was reversed needs a choice: DL-032 or a "
        "forfeiture again": RECEIPT_CORRECTION_OUTCOME_NEEDED,
        "Only a Deposit whose forfeiture was reversed takes a choice of outcome": (
            RECEIPT_CORRECTION_OUTCOME_NOT_TAKEN
        ),
        "A forfeiture in a receipt correction takes only the new receipt's money": (
            RECEIPT_CORRECTION_FORFEIT_NEW_MONEY_ONLY
        ),
        "Nothing beyond the Customer's pay-back money is left to forfeit; choose DL-032": (
            RECEIPT_CORRECTION_NOTHING_TO_FORFEIT
        ),
        "A new receipt into a Deposit that also holds another Payment's money and the Customer's "
        "pay-back money is not supported": RECEIPT_CORRECTION_MIXED_DEPOSIT,
        "A Customer Credit step cannot follow a Deposit application this correction writes "
        "again; refund or apply the Customer's Credit first, or correct the receipt without new "
        "receipts": RECEIPT_CORRECTION_CREDIT_AFTER_REAPPLY,
        "A Deposit step of this plan comes before, in the DL-032 order, a Deposit application "
        "this correction writes again": RECEIPT_CORRECTION_STEP_BEFORE_REAPPLY,
        "A Deposit step of this plan repeats a Deposit application this correction writes again; "
        "split the step": RECEIPT_CORRECTION_STEP_REPEATS_REAPPLY,
        "The Deposit would not end empty after this receipt correction": (
            RECEIPT_CORRECTION_DEPOSIT_NOT_EMPTY
        ),
        "The Deposit would not end holding only the other Payments' money after this receipt "
        "correction": RECEIPT_CORRECTION_DEPOSIT_NOT_EMPTY,
        "The corrected receipt's Deposit would still hold other money after this correction; pay "
        "it out with a held-value Refund correction first": RECEIPT_CORRECTION_HELD_MONEY_FIRST,
        "A Deposit this Payment funded also holds another Payment's money and has a Refund that "
        "is not fully returned": RECEIPT_CORRECTION_SHARED_DEPOSIT_REFUND,
        "A Reservation Deposit Refund paid from this Payment's value is not fully returned": (
            RECEIPT_CORRECTION_RESERVATION_REFUND
        ),
        "A Refund paid from this Payment's value would be charged on a Lease whose Final "
        "Settlement is closed; return the Payment through a returned-Payment correction of that "
        "Final Settlement": RECEIPT_CORRECTION_RECOVERY_ON_CLOSED_LEASE,
        "A Refund paid from this Payment's value would be charged on a Lease whose closed Final "
        "Settlement this return cannot correct": RECEIPT_CORRECTION_RECOVERY_ON_CLOSED_LEASE,
        "A Refund paid from this Deposit has no planned recovery": RECEIPT_CORRECTION_NO_RECOVERY,
        "The Deposit has a Deposit application of another Final Settlement": (
            RECEIPT_CORRECTION_OTHER_SETTLEMENT_USE
        ),
        "The Deposit has an active forfeiture; reverse it with a forfeiture reversal correction "
        "first": RECEIPT_CORRECTION_FORFEITURE_ACTIVE,
        "The Deposit receipt correction draft exceeds the stored draft size of 16000 bytes": (
            RECEIPT_CORRECTION_TOO_LARGE
        ),
    }
)
# The return reversal has no plan: staff enter no DL-032 step.
RETURN_REVERSAL_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **CORRECTION_REFUSALS,
        "The returned-Refund correction to reverse was not found": RETURN_REVERSAL_NOT_FOUND,
        "The return of this correction is already reversed": RETURN_REVERSAL_ALREADY_REVERSED,
        "A return reversal draft of this correction is already waiting": (
            RETURN_REVERSAL_DRAFT_WAITING
        ),
        "A Refund paid from the returned value has its own return; reverse that return first": (
            RETURN_REVERSAL_REFUND_RETURNED_FIRST
        ),
        "A forfeiture kept this return's money; the return cannot be reversed": (
            RETURN_REVERSAL_FORFEITED
        ),
        "The returned value is no longer available; undo its other use first": (
            RETURN_REVERSAL_VALUE_USED
        ),
        "A Credit reversal or a Deposit receipt reversal paid out this return's money in a way "
        "this reversal cannot follow yet; reversing it waits for the owner": (
            RETURN_REVERSAL_WAITS_FOR_OWNER
        ),
        "A correction of another Lease's Final Settlement used this return's money in a way this "
        "reversal cannot undo; reversing it waits for the owner": RETURN_REVERSAL_WAITS_FOR_OWNER,
        "A later correction changed a payment made with this return's money in a way this "
        "reversal cannot follow yet; reversing it waits for the owner": (
            RETURN_REVERSAL_WAITS_FOR_OWNER
        ),
        "This return's own corrections also paid out another return's money; reversing it waits "
        "for sub-slice 10e-3d-2b": RETURN_REVERSAL_WAITS_FOR_OWNER,
        "The return reversal correction draft exceeds the stored draft size of 16000 bytes": (
            RETURN_REVERSAL_TOO_LARGE
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

    # Slice 11e-3: the corrections with a DL-032 plan, the Deposit receipt correction and the
    # return reversal.

    @router.post(f"{base}/refunds", status_code=201, dependencies=[Depends(_financial_json)])
    def record_refund(
        property_id: Identity,
        settlement_id: Identity,
        body: RefundCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A paid charge that was wrong: a credit Adjustment releases the paid value by the plan."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordRefundCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.invoice_id,
                body.invoice_line_id,
                body.amount_usd_cents,
                body.refund_method_id,
                body.reference_note,
                body.reason,
                *_plan(body),
            ),
            REFUND_CORRECTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.refund(property_id, command, actor=actor), REFUND_CORRECTION_REFUSALS
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "REFUND",
                {("target_kind",): None, ("refund", "invoice_line_id"): str(body.invoice_line_id)},
            ),
        )

    @router.post(
        f"{base}/late-charge-refunds", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_late_charge_refund(
        property_id: Identity,
        settlement_id: Identity,
        body: LateChargeRefundCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A paid Late-payment Charge that was wrong, released by the plan."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordLateChargeRefundCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.late_payment_charge_id,
                body.amount_usd_cents,
                body.refund_method_id,
                body.reference_note,
                body.reason,
                *_plan(body),
            ),
            LATE_CHARGE_REFUND_REFUSALS,
        )
        result = _invoke(
            lambda: flow.late_charge_refund(property_id, command, actor=actor),
            LATE_CHARGE_REFUND_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "REFUND",
                {
                    ("target_kind",): "LATE_PAYMENT_CHARGE",
                    ("refund", "late_payment_charge_id"): str(body.late_payment_charge_id),
                },
            ),
        )

    @router.post(
        f"{base}/pet-classifications", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_pet_classification(
        property_id: Identity,
        settlement_id: Identity,
        body: PetClassificationCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A Damage line whose pet classification was wrong; the Deposit value given back
        follows the plan."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordPetClassificationCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.invoice_id,
                body.invoice_line_id,
                body.pet_related,
                body.evidence_reference,
                body.reason,
                *_plan(body),
            ),
            PET_CLASSIFICATION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.pet_classification(property_id, command, actor=actor),
            PET_CLASSIFICATION_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "PET_DAMAGE_RECLASSIFICATION",
                {("classification", "invoice_line_id"): str(body.invoice_line_id)},
            ),
        )

    @router.post(f"{base}/refund-returns", status_code=201, dependencies=[Depends(_financial_json)])
    def record_refund_return(
        property_id: Identity,
        settlement_id: Identity,
        body: RefundReturnCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A Refund of the Settlement or a correction whose money came back."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordRefundReturnCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.refund_id,
                body.returned_amount_usd_cents,
                body.returned_at,
                body.return_method_reference,
                body.evidence_reference,
                body.reason,
                body.new_refund_method_id,
                body.new_refund_reference_note,
                *_plan(body),
            ),
            REFUND_RETURN_REFUSALS,
        )
        result = _invoke(
            lambda: flow.refund_return(property_id, command, actor=actor), REFUND_RETURN_REFUSALS
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "REFUND_RETURN",
                {("refund_return", "refund_id"): str(body.refund_id)},
            ),
        )

    @router.post(
        f"{base}/held-value-refunds", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_held_value_refund(
        property_id: Identity,
        settlement_id: Identity,
        body: HeldValueRefundCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Refund the value an earlier return-only correction held."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordHeldValueRefundCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.held_from_correction_id,
                body.reason,
                body.new_refund_method_id,
                body.new_refund_reference_note,
                *_plan(body),
            ),
            HELD_VALUE_REFUND_REFUSALS,
        )
        result = _invoke(
            lambda: flow.held_value_refund(property_id, command, actor=actor),
            HELD_VALUE_REFUND_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "HELD_VALUE_REFUND",
                {("held_from_settlement_correction_id",): str(body.held_from_correction_id)},
            ),
        )

    @router.post(
        f"{base}/forfeiture-reversals", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_forfeiture_reversal(
        property_id: Identity,
        settlement_id: Identity,
        body: ForfeitureReversalCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reverse a confirmed Deposit forfeiture of the Lease; the Deposit follows the plan."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordForfeitureReversalCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.deposit_disposition_id,
                body.reason,
                body.evidence_reference,
                body.refund_method_id,
                body.reference_note,
                *_plan(body),
            ),
            FORFEITURE_REVERSAL_REFUSALS,
        )
        result = _invoke(
            lambda: flow.forfeiture_reversal(property_id, command, actor=actor),
            FORFEITURE_REVERSAL_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "FORFEITURE_REVERSAL",
                {("deposit_disposition_id",): str(body.deposit_disposition_id)},
            ),
        )

    @router.post(
        f"{base}/deposit-receipt-corrections",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_deposit_receipt_correction(
        property_id: Identity,
        settlement_id: Identity,
        body: DepositReceiptCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """A Deposit receipt that is wrong while its Payment is real; the right receipts
        follow the plan."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordDepositReceiptCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.deposit_receipt_id,
                body.reason,
                body.evidence_reference,
                tuple(
                    CorrectionDepositReceipt(
                        receipt.deposit_id,
                        receipt.amount_usd_cents,
                        receipt.outcome,
                        receipt.outcome_reason,
                    )
                    for receipt in body.receipts
                ),
                *_plan(body),
            ),
            RECEIPT_CORRECTION_REFUSALS,
        )
        result = _invoke(
            lambda: flow.deposit_receipt_correction(property_id, command, actor=actor),
            RECEIPT_CORRECTION_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "DEPOSIT_RECEIPT_CORRECTION",
                {("deposit_receipt_id",): str(body.deposit_receipt_id)},
            ),
        )

    @router.post(
        f"{base}/return-reversals", status_code=201, dependencies=[Depends(_financial_json)]
    )
    def record_return_reversal(
        property_id: Identity,
        settlement_id: Identity,
        body: ReturnReversalCorrectionInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Reverse a return an earlier returned-Refund correction recorded by mistake."""
        actor = context(request, property_id, prepare)
        command = _invoke(
            lambda: RecordReturnReversalCorrectionCommand(
                idempotency_key,
                settlement_id,
                body.earlier_correction_id,
                body.reason,
                body.evidence_reference,
            ),
            RETURN_REVERSAL_REFUSALS,
        )
        result = _invoke(
            lambda: flow.return_reversal(property_id, command, actor=actor),
            RETURN_REVERSAL_REFUSALS,
        )
        return envelope(
            request,
            _correction(
                result,
                property_id,
                settlement_id,
                "RETURN_REVERSAL",
                {("held_from_settlement_correction_id",): str(body.earlier_correction_id)},
            ),
        )

    return router
