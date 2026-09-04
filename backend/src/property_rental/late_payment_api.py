"""Protected late-payment review, Decision, Charge, and correction routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from property_rental.api import require_billing_actor
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.late_payment import (
    LATE_PAYMENT_CORRECTION_CAPABILITY,
    LATE_PAYMENT_DECISION_CAPABILITY,
    LATE_PAYMENT_REVIEW_CAPABILITY,
    MAX_USD_MINOR_UNITS,
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
    LatePaymentAuthorizationError,
    LatePaymentCommandResponse,
    LatePaymentConflictError,
    LatePaymentIdempotencyKeyReused,
    LatePaymentInvalidError,
    LatePaymentNotFoundError,
    LatePaymentServiceUnavailableError,
)
from property_rental.settings import Settings


class LatePaymentFlow(Protocol):
    def property_for_invoice(self, invoice_id: UUID) -> UUID: ...

    def property_for_charge(self, charge_id: UUID) -> UUID: ...

    def review(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]: ...

    def get_decision(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]: ...

    def get_charge(self, charge_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]: ...

    def decision_conflict_state(
        self, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...

    def charge_conflict_state(
        self, charge_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...

    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse: ...

    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse: ...


class UnavailableLatePaymentFlow:
    def __getattr__(self, _: str) -> object:
        raise LatePaymentServiceUnavailableError("Late-payment persistence is unavailable")


class MoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(pattern=r"^USD$")
    minor_units: int = Field(strict=True, ge=0, le=MAX_USD_MINOR_UNITS)


class FinalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: DecisionOutcome
    approved_amount: MoneyInput
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class ChargeCorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CorrectionKind
    amount: MoneyInput | None = None
    reverses_correction_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")

    @model_validator(mode="after")
    def validate_shape(self) -> ChargeCorrectionInput:
        if self.kind is CorrectionKind.REDUCTION:
            if (
                self.amount is None
                or self.amount.minor_units == 0
                or self.reverses_correction_id is not None
            ):
                raise ValueError("REDUCTION requires only a positive amount")
        elif self.kind is CorrectionKind.CHARGE_REVERSAL:
            if self.amount is not None or self.reverses_correction_id is not None:
                raise ValueError("CHARGE_REVERSAL derives its amount")
        elif self.amount is not None or self.reverses_correction_id is None:
            raise ValueError("REDUCTION_REVERSAL requires only its source correction")
        return self


def late_payment_idempotency_key_reused_response(request: Request) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was already used for different input.",
                "fields": [],
                "rule_ids": ["API-016"],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def application_reversal_required_response(request: Request) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "APPLICATION_REVERSAL_REQUIRED",
                "message": "Active applications must be reversed explicitly first.",
                "fields": [],
                "rule_ids": ["BR-LATE-005", "API-091"],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def late_payment_conflict_response(
    request: Request, current_state: dict[str, object]
) -> JSONResponse:
    """Return only the already-authorized public resource state for a conflict."""
    request_id = request.state.request_id
    candidate_version = current_state.get("version")
    current_version = candidate_version if type(candidate_version) is int else None
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "CONFLICT",
                "message": "The command conflicted with the current resource state.",
                "fields": [],
                "rule_ids": ["API-018"],
                "current_version": current_version,
                "current_state": current_state,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if request.method in {"POST", "PATCH"}:
        require_billing_actor(request, actor)
    return actor


def _authorize(
    actor: AuthenticatedActor, property_id: UUID, capability: str, *, hide: bool = False
) -> None:
    if is_authorized(
        actor,
        AuthorizationRequirement(capability=capability, property_id=str(property_id)),
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND if hide else status.HTTP_403_FORBIDDEN
    )


InvokeResult = TypeVar("InvokeResult")


def _invoke(
    command: Callable[[], InvokeResult], *, preserve_conflict: bool = False
) -> InvokeResult:
    try:
        return command()
    except LatePaymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except LatePaymentAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except (LatePaymentIdempotencyKeyReused, LatePaymentApplicationReversalRequired):
        raise
    except LatePaymentConflictError as exc:
        if preserve_conflict:
            raise
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except (LatePaymentInvalidError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except LatePaymentServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _envelope(resource: dict[str, object], request: Request) -> dict[str, object]:
    return {"data": resource, "meta": {"request_id": request.state.request_id}}


def create_late_payment_router(
    resolver: ActorResolver,
    flow: LatePaymentFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["late-payments"])

    def invoice_context(
        invoice_id: UUID, request: Request, capability: str, *, mutation: bool
    ) -> tuple[AuthenticatedActor, UUID]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_for_invoice(invoice_id)
        except (LatePaymentNotFoundError, LatePaymentAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except LatePaymentServiceUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        _authorize(actor, property_id, capability, hide=True)
        if mutation:
            require_browser_mutation(request, settings)
        return actor, property_id

    def charge_context(
        charge_id: UUID, request: Request, capability: str, *, mutation: bool
    ) -> tuple[AuthenticatedActor, UUID]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_for_charge(charge_id)
        except (LatePaymentNotFoundError, LatePaymentAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except LatePaymentServiceUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        _authorize(actor, property_id, capability, hide=True)
        if mutation:
            require_browser_mutation(request, settings)
        return actor, property_id

    @router.get("/invoices/{invoice_id}/late-payment-review")
    def review(invoice_id: UUID, request: Request) -> dict[str, object]:
        actor, _ = invoice_context(
            invoice_id, request, LATE_PAYMENT_REVIEW_CAPABILITY, mutation=False
        )
        return _envelope(_invoke(lambda: flow.review(invoice_id, actor=actor)), request)

    @router.post(
        "/invoices/{invoice_id}/late-payment-decision",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def finalize_decision(
        invoice_id: UUID,
        body: FinalDecisionInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object] | JSONResponse:
        actor, property_id = invoice_context(
            invoice_id, request, LATE_PAYMENT_DECISION_CAPABILITY, mutation=True
        )
        try:
            resource = _invoke(
                lambda: flow.finalize_decision(
                    property_id,
                    invoice_id,
                    FinalizeLatePaymentDecisionCommand(
                        idempotency_key,
                        body.outcome,
                        body.approved_amount.minor_units,
                        body.reason,
                    ),
                    actor=actor,
                    request_id=request.state.request_id,
                ),
                preserve_conflict=True,
            )
        except (LatePaymentIdempotencyKeyReused, LatePaymentApplicationReversalRequired):
            raise
        except LatePaymentConflictError:
            current_state = _invoke(lambda: flow.decision_conflict_state(invoice_id, actor=actor))
            return late_payment_conflict_response(request, current_state)
        response.status_code = resource.status_code
        response.headers["Location"] = f"/api/v1/invoices/{invoice_id}/late-payment-decision"
        return resource.body

    @router.get("/invoices/{invoice_id}/late-payment-decision")
    def get_decision(invoice_id: UUID, request: Request) -> dict[str, object]:
        actor, _ = invoice_context(
            invoice_id, request, LATE_PAYMENT_REVIEW_CAPABILITY, mutation=False
        )
        return _envelope(_invoke(lambda: flow.get_decision(invoice_id, actor=actor)), request)

    @router.get("/late-payment-charges/{charge_id}")
    def get_charge(charge_id: UUID, request: Request) -> dict[str, object]:
        actor, _ = charge_context(
            charge_id, request, LATE_PAYMENT_REVIEW_CAPABILITY, mutation=False
        )
        return _envelope(_invoke(lambda: flow.get_charge(charge_id, actor=actor)), request)

    @router.post(
        "/late-payment-charges/{charge_id}/corrections",
        status_code=status.HTTP_200_OK,
        response_model=None,
    )
    def correct_charge(
        charge_id: UUID,
        body: ChargeCorrectionInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object] | JSONResponse:
        actor, property_id = charge_context(
            charge_id, request, LATE_PAYMENT_CORRECTION_CAPABILITY, mutation=True
        )
        try:
            resource = _invoke(
                lambda: flow.correct_charge(
                    property_id,
                    charge_id,
                    CorrectLatePaymentChargeCommand(
                        idempotency_key,
                        body.kind,
                        body.reason,
                        body.amount.minor_units if body.amount is not None else None,
                        body.reverses_correction_id,
                    ),
                    actor=actor,
                    request_id=request.state.request_id,
                ),
                preserve_conflict=True,
            )
        except (LatePaymentIdempotencyKeyReused, LatePaymentApplicationReversalRequired):
            raise
        except LatePaymentConflictError:
            current_state = _invoke(lambda: flow.charge_conflict_state(charge_id, actor=actor))
            return late_payment_conflict_response(request, current_state)
        response.status_code = resource.status_code
        return resource.body

    return router
