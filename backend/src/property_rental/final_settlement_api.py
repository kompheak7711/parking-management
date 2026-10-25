"""Final Settlement start, preview and draft routes (V1-056 slice 11e-1; API-070 to API-072).

- ``POST /properties/{p}/leases/{lease_id}/final-settlement`` (``final_settlements.prepare``)
  opens the one Final Settlement of a terminated Lease, or returns the one that exists.
- ``GET /properties/{p}/final-settlements/{settlement_id}/preview`` (``final_settlements.prepare``
  or ``financial.approve``) reads the obligations, Credit, Deposits, the DL-032 steps and the
  blocking issues; it writes nothing.
- ``POST /properties/{p}/final-settlements/{settlement_id}/drafts`` (``final_settlements.prepare``)
  records the Settlement draft: the DL-032 steps in order. It has no financial effect until a
  ``financial.approve`` holder confirms it through the shared draft routes
  (``financial_draft_api.py``), which close the Settlement in one transaction.

A refusal of the chosen steps answers 422 on its form field; the state of the Lease or the
Settlement answers 409 with its own code. No answer shows database text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Final, Literal, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, model_validator

from property_rental.allocation_receipt_api import Reason, _mutation
from property_rental.api_refusals import (
    DRAFT_OUT_OF_DATE,
    FINAL_SETTLEMENT_BLOCKING_ISSUES,
    FINAL_SETTLEMENT_CLOSED,
    FINAL_SETTLEMENT_CREDIT_FIRST,
    FINAL_SETTLEMENT_CREDIT_NOT_AVAILABLE,
    FINAL_SETTLEMENT_CREDIT_OTHER_CUSTOMER,
    FINAL_SETTLEMENT_CREDIT_OVER,
    FINAL_SETTLEMENT_CREDIT_RENT_FIRST,
    FINAL_SETTLEMENT_DEPOSIT_LEFT,
    FINAL_SETTLEMENT_DEPOSIT_NOT_USABLE,
    FINAL_SETTLEMENT_DEPOSIT_OVER,
    FINAL_SETTLEMENT_DEPOSIT_WRONG_STEP,
    FINAL_SETTLEMENT_DRAFT_WAITING,
    FINAL_SETTLEMENT_LEASE_NOT_TERMINATED,
    FINAL_SETTLEMENT_NO_AGREEMENT_FOR_PRIMARY,
    FINAL_SETTLEMENT_OBLIGATION_OVER,
    FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT,
    FINAL_SETTLEMENT_PET_DAMAGE_FIRST,
    FINAL_SETTLEMENT_PET_DAMAGE_ONLY,
    FINAL_SETTLEMENT_PET_REMAINDER_AFTER_SECURITY,
    FINAL_SETTLEMENT_PET_REMAINDER_CUSTOMER_ONLY,
    FINAL_SETTLEMENT_PET_REMAINDER_NO_STEP,
    FINAL_SETTLEMENT_PET_REMAINDER_REASON,
    FINAL_SETTLEMENT_RECORD_UNCLEAR,
    FINAL_SETTLEMENT_REFUND_METHOD_OFF,
    FINAL_SETTLEMENT_REFUND_RECIPIENT,
    FINAL_SETTLEMENT_REFUND_WHILE_DEBT,
    FINAL_SETTLEMENT_SIGNER_AGREEMENT,
    FINAL_SETTLEMENT_STEP_ORDER,
    FINAL_SETTLEMENT_TARGET_NOT_OPEN,
    FINAL_SETTLEMENT_TOO_LARGE,
    IDEMPOTENCY_KEY_REUSED,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.credit_refund_api import CreditRefundRequestRoute, Key, _financial_json
from property_rental.final_settlement import (
    MAX_SETTLEMENT_STEPS,
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementReadService,
    FinalSettlementService,
    FinalSettlementUnavailableError,
    PetRemainderBasis,
    PetRemainderDecision,
    RecordFinalSettlementDraftCommand,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementStep,
    SettlementTargetKind,
)
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.financial_draft import (
    FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
    FINANCIAL_APPROVE_CAPABILITY,
)
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
from property_rental.settings import Settings

T = TypeVar("T")

TargetKind = Literal["INVOICE_LINE", "LATE_PAYMENT_CHARGE"]


class CreditStepInput(StrictInput):
    """DL-032 step 2: a Customer's Credit pays one of that Customer's obligations."""

    kind: Literal["CUSTOMER_CREDIT"]
    customer_credit_id: Identity
    target_kind: TargetKind
    target_id: Identity
    amount_usd_cents: MinorUnits
    customer_designation: Evidence | None = None


class DepositStepInput(StrictInput):
    """DL-032 steps 3 to 5: a Deposit pays one obligation of the Lease."""

    kind: Literal["PET_DEPOSIT_PET_DAMAGE", "SECURITY_DEPOSIT", "PET_DEPOSIT_REMAINDER"]
    deposit_id: Identity
    target_kind: TargetKind
    target_id: Identity
    amount_usd_cents: MinorUnits


class DepositRefundStepInput(StrictInput):
    """DL-032 step 7: the Refund of what remains in one Deposit."""

    kind: Literal["DEPOSIT_REFUNDS"]
    deposit_id: Identity
    amount_usd_cents: MinorUnits
    refund_method_id: Identity
    reference_note: Evidence
    recipient_customer_id: Identity
    signer_agreement: Memo | None = None


StepInput = Annotated[
    CreditStepInput | DepositStepInput | DepositRefundStepInput, Field(discriminator="kind")
]


class PetRemainderInput(StrictInput):
    """Why the rest of the Pet Deposit pays other debt: the Customer's choice (who, the date and
    how) with the staff reason, or only the staff reason."""

    basis: Literal["CUSTOMER_CHOICE", "STAFF_REASON"]
    staff_reason: Reason
    customer_choice: Memo | None = None

    @model_validator(mode="after")
    def _choice_matches_basis(self) -> PetRemainderInput:
        if (self.basis == "CUSTOMER_CHOICE") != (self.customer_choice is not None):
            raise ValueError("customer_choice is given exactly with the CUSTOMER_CHOICE basis")
        return self


class FinalSettlementDraftInput(StrictInput):
    steps: Annotated[list[StepInput], Field(max_length=MAX_SETTLEMENT_STEPS)]
    reason: Reason
    pet_remainder: PetRemainderInput | None = None


def _step(value: CreditStepInput | DepositStepInput | DepositRefundStepInput) -> SettlementStep:
    if isinstance(value, CreditStepInput):
        return SettlementCreditStep(
            value.customer_credit_id,
            SettlementTargetKind(value.target_kind),
            value.target_id,
            value.amount_usd_cents,
            value.customer_designation,
        )
    if isinstance(value, DepositStepInput):
        return SettlementDepositStep(
            SettlementDepositStepKind(value.kind),
            value.deposit_id,
            SettlementTargetKind(value.target_kind),
            value.target_id,
            value.amount_usd_cents,
        )
    return SettlementDepositRefund(
        value.deposit_id,
        value.amount_usd_cents,
        value.refund_method_id,
        value.reference_note,
        value.recipient_customer_id,
        value.signer_agreement,
    )


def draft_command(
    key: UUID, settlement_id: UUID, body: FinalSettlementDraftInput
) -> RecordFinalSettlementDraftCommand:
    remainder = body.pet_remainder
    return RecordFinalSettlementDraftCommand(
        key,
        settlement_id,
        tuple(_step(step) for step in body.steps),
        body.reason,
        None
        if remainder is None
        else PetRemainderDecision(
            PetRemainderBasis(remainder.basis), remainder.staff_reason, remainder.customer_choice
        ),
    )


class FinalSettlementFlow(Protocol):
    def start(
        self, property_id: UUID, lease_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...

    def preview(
        self, property_id: UUID, settlement_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...

    def record_draft(
        self,
        property_id: UUID,
        command: RecordFinalSettlementDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PostgresFinalSettlementFlow:
    database_url: str | None
    financial_database_url: str | None

    def _runtime(self) -> str:
        if self.database_url is None:
            raise FinalSettlementUnavailableError("Final Settlement reads are unavailable")
        return self.database_url

    def _financial(self) -> str:
        if self.financial_database_url is None:
            raise FinalSettlementUnavailableError("Final Settlement commands are unavailable")
        return self.financial_database_url

    def start(
        self, property_id: UUID, lease_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return FinalSettlementService(self._financial()).start(property_id, lease_id, actor=actor)

    def preview(
        self, property_id: UUID, settlement_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return FinalSettlementReadService(self._runtime()).preview(
            property_id, settlement_id, actor=actor
        )

    def record_draft(
        self,
        property_id: UUID,
        command: RecordFinalSettlementDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return FinalSettlementService(self._financial()).record_draft(
            property_id, command, actor=actor
        )


# The state of the Lease or the Settlement (409), at every route and at the shared confirm.
FINAL_SETTLEMENT_STATE_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "A Final Settlement starts only for a TERMINATED Lease": (
            FINAL_SETTLEMENT_LEASE_NOT_TERMINATED
        ),
        "The Lease is not terminated": FINAL_SETTLEMENT_LEASE_NOT_TERMINATED,
        "The current move-out record is ambiguous": FINAL_SETTLEMENT_RECORD_UNCLEAR,
        "The termination record is ambiguous": FINAL_SETTLEMENT_RECORD_UNCLEAR,
        "The Final Settlement has blocking issues": FINAL_SETTLEMENT_BLOCKING_ISSUES,
        "A closed Final Settlement is never reopened or changed": FINAL_SETTLEMENT_CLOSED,
    }
)
# The chosen steps break a DL-032 rule (422 on the form field).
FINAL_SETTLEMENT_PLAN_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        "Final Settlement steps must follow the DL-032 order": FINAL_SETTLEMENT_STEP_ORDER,
        "A Customer Credit pays only its own Customer's obligations": (
            FINAL_SETTLEMENT_CREDIT_OTHER_CUSTOMER
        ),
        "Each Customer's Credit must pay that Customer's open debt, up to what it can pay, "
        "before any Deposit pays": FINAL_SETTLEMENT_CREDIT_FIRST,
        "Credit on an Invoice with Rent or Service lines follows the Rent-first proposal unless "
        "the Customer designated the line": FINAL_SETTLEMENT_CREDIT_RENT_FIRST,
        "The Customer Credit is not available to this Final Settlement": (
            FINAL_SETTLEMENT_CREDIT_NOT_AVAILABLE
        ),
        "The amount exceeds the available Customer Credit": FINAL_SETTLEMENT_CREDIT_OVER,
        "Only a Deposit that follows DL-032 and holds money may be applied": (
            FINAL_SETTLEMENT_DEPOSIT_NOT_USABLE
        ),
        "Only a Deposit that follows DL-032 and holds money may be refunded": (
            FINAL_SETTLEMENT_DEPOSIT_NOT_USABLE
        ),
        "The Deposit type does not match the DL-032 step": FINAL_SETTLEMENT_DEPOSIT_WRONG_STEP,
        "The amount exceeds what the Deposit holds": FINAL_SETTLEMENT_DEPOSIT_OVER,
        "The amount exceeds what the obligation still owes": FINAL_SETTLEMENT_OBLIGATION_OVER,
        "The target is not an open obligation of this Final Settlement": (
            FINAL_SETTLEMENT_TARGET_NOT_OPEN
        ),
        "The Pet Deposit first pays only valid pet damage": FINAL_SETTLEMENT_PET_DAMAGE_ONLY,
        "The Pet Deposit pays open pet damage before any other use or Refund": (
            FINAL_SETTLEMENT_PET_DAMAGE_FIRST
        ),
        "The remaining Pet Deposit pays only debt still open after the Security Deposit has been "
        "used": FINAL_SETTLEMENT_PET_REMAINDER_AFTER_SECURITY,
        "At this termination only the Customer may choose to use the remaining Pet Deposit": (
            FINAL_SETTLEMENT_PET_REMAINDER_CUSTOMER_ONLY
        ),
        "The remaining Pet Deposit needs the Customer's choice or the staff reason": (
            FINAL_SETTLEMENT_PET_REMAINDER_REASON
        ),
        "A remaining Pet Deposit basis needs a remaining Pet Deposit step": (
            FINAL_SETTLEMENT_PET_REMAINDER_NO_STEP
        ),
        "Every remaining Deposit balance must be applied or refunded": (
            FINAL_SETTLEMENT_DEPOSIT_LEFT
        ),
        "No Deposit Refund while the Lease still has open debt that the Deposit could pay": (
            FINAL_SETTLEMENT_REFUND_WHILE_DEBT
        ),
        "A Deposit has at most one Refund in a Final Settlement draft": (
            FINAL_SETTLEMENT_ONE_REFUND_PER_DEPOSIT
        ),
        "The Refund recipient must be a Signer of the Lease": FINAL_SETTLEMENT_REFUND_RECIPIENT,
        "A Refund to another Signer needs the written agreement of all Signers": (
            FINAL_SETTLEMENT_SIGNER_AGREEMENT
        ),
        "The Primary Tenant needs no Signer agreement": FINAL_SETTLEMENT_NO_AGREEMENT_FOR_PRIMARY,
        "Refund Method is not active": FINAL_SETTLEMENT_REFUND_METHOD_OFF,
    }
)
FINAL_SETTLEMENT_DRAFT_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **FINAL_SETTLEMENT_STATE_REFUSALS,
        **FINAL_SETTLEMENT_PLAN_REFUSALS,
        "A Final Settlement draft is already waiting": FINAL_SETTLEMENT_DRAFT_WAITING,
        "The Final Settlement draft exceeds the stored draft size of 16000 bytes": (
            FINAL_SETTLEMENT_TOO_LARGE
        ),
    }
)
# At the shared confirm the steps were checked at record, so a step the plan now refuses means
# the records changed: the draft is out of date (the stale refusal P5S02 answers so already).
FINAL_SETTLEMENT_CONFIRM_REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType(
    {
        **FINAL_SETTLEMENT_STATE_REFUSALS,
        **{message: DRAFT_OUT_OF_DATE for message in FINAL_SETTLEMENT_PLAN_REFUSALS},
    }
)

NOT_FOUND_ERRORS: Final = (FinalSettlementNotFoundError,)
AUTHORIZATION_ERRORS: Final = (FinalSettlementAuthorizationError,)
INVALID_ERRORS: Final = (FinalSettlementInvalidError,)
CONFLICT_ERRORS: Final = (FinalSettlementConflictError,)


def _invoke(call: Callable[[], T], refusals: Mapping[str, Refusal]) -> T:
    try:
        return call()
    except (*NOT_FOUND_ERRORS, *AUTHORIZATION_ERRORS, *INVALID_ERRORS, *CONFLICT_ERRORS) as exc:
        refusal = database_refusal(exc, refusals)
        if refusal is not None:
            raise RefusedRequest(refusal) from exc
        if isinstance(exc, FinalSettlementKeyReused):
            raise RefusedRequest(IDEMPOTENCY_KEY_REUSED) from exc
        if isinstance(exc, NOT_FOUND_ERRORS):
            raise HTTPException(404) from exc
        if isinstance(exc, AUTHORIZATION_ERRORS):
            raise HTTPException(403) from exc
        if isinstance(exc, INVALID_ERRORS):
            raise HTTPException(422) from exc
        raise HTTPException(409) from exc
    except FinalSettlementUnavailableError as exc:
        raise HTTPException(503) from exc


def _settlement(value: object, property_id: UUID, **expected: UUID) -> dict[str, object]:
    """The Settlement as read, checked against the path before it is shown."""
    if not isinstance(value, dict) or value.get("property_id") != str(property_id):
        raise HTTPException(503)
    if any(value.get(key) != str(identity) for key, identity in expected.items()):
        raise HTTPException(503)
    return value


def _preview(value: object, property_id: UUID, settlement_id: UUID) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HTTPException(503)
    _settlement(value.get("settlement"), property_id, id=settlement_id)
    return value


def _pending_draft(value: object, property_id: UUID, settlement_id: UUID) -> dict[str, object]:
    """The recorded Settlement draft, checked against the path before it is shown."""
    payload = value.get("payload") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("property_id") != str(property_id)
        or value.get("kind") != "FINAL_SETTLEMENT"
        or not isinstance(payload, dict)
        or payload.get("variant") != "FINAL_SETTLEMENT"
        or payload.get("final_settlement_id") != str(settlement_id)
    ):
        raise HTTPException(503)
    return value


def create_final_settlement_router(
    resolver: ActorResolver, flow: FinalSettlementFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["final-settlements"], route_class=CreditRefundRequestRoute
    )

    def context(
        request: Request, property_id: UUID, capabilities: tuple[str, ...]
    ) -> AuthenticatedActor:
        _queries(request, set())
        actor = _actor(request, resolver)
        if request.method == "POST":
            _mutation(request, settings)
        # A Property the person may not work on Settlements in is hidden.
        if not any(
            is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))
            for capability in capabilities
        ):
            raise HTTPException(404)
        bind_financial_property(request, property_id)
        return actor

    def envelope(request: Request, result: object) -> dict[str, object]:
        return {"data": result, "meta": financial_metadata(request)}

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/final-settlement",
        dependencies=[Depends(_financial_json)],
    )
    def start_settlement(
        property_id: Identity,
        lease_id: Identity,
        request: Request,
        response: Response,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Open the Lease's one Final Settlement, or return the one that exists. The Lease is the
        idempotency identity: the header is required as on every financial command but is not
        stored."""
        del idempotency_key
        actor = context(request, property_id, (FINAL_SETTLEMENTS_PREPARE_CAPABILITY,))
        result = _invoke(
            lambda: flow.start(property_id, lease_id, actor=actor),
            FINAL_SETTLEMENT_STATE_REFUSALS,
        )
        settlement = _settlement(result, property_id, lease_id=lease_id)
        if settlement.get("created") is True:
            response.status_code = 201
        return envelope(request, settlement)

    @router.get("/properties/{property_id}/final-settlements/{settlement_id}/preview")
    def preview_settlement(
        property_id: Identity, settlement_id: Identity, request: Request
    ) -> dict[str, object]:
        actor = context(
            request,
            property_id,
            (FINAL_SETTLEMENTS_PREPARE_CAPABILITY, FINANCIAL_APPROVE_CAPABILITY),
        )
        result = _invoke(
            lambda: flow.preview(property_id, settlement_id, actor=actor),
            FINAL_SETTLEMENT_STATE_REFUSALS,
        )
        return envelope(request, _preview(result, property_id, settlement_id))

    @router.post(
        "/properties/{property_id}/final-settlements/{settlement_id}/drafts",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def record_settlement_draft(
        property_id: Identity,
        settlement_id: Identity,
        body: FinalSettlementDraftInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        """Record the Settlement draft (BR-AUTH-010); it closes nothing until confirmed."""
        actor = context(request, property_id, (FINAL_SETTLEMENTS_PREPARE_CAPABILITY,))
        command = _invoke(
            lambda: draft_command(idempotency_key, settlement_id, body),
            FINAL_SETTLEMENT_DRAFT_REFUSALS,
        )
        result = _invoke(
            lambda: flow.record_draft(property_id, command, actor=actor),
            FINAL_SETTLEMENT_DRAFT_REFUSALS,
        )
        return envelope(request, _pending_draft(result, property_id, settlement_id))

    return router
