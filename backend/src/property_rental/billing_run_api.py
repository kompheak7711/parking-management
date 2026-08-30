"""Protected HTTP resources for scheduled billing commands and run evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from property_rental.billing_run import (
    BILLING_GENERATE_CAPABILITY,
    BillingRunAttempt,
    BillingRunAuthorizationError,
    BillingRunCommand,
    BillingRunConflict,
    BillingRunDetail,
    BillingRunInvalid,
    BillingRunItem,
    BillingRunNotFound,
    BillingRunUnavailable,
)
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings


class BillingRunFlow(Protocol):
    def execute(
        self,
        command: BillingRunCommand,
        *,
        actor: AuthenticatedActor,
        invocation_source: str,
    ) -> BillingRunDetail: ...

    def get(self, run_id: UUID, *, actor: AuthenticatedActor) -> BillingRunDetail: ...


class UnavailableBillingRunFlow:
    def execute(
        self,
        command: BillingRunCommand,
        *,
        actor: AuthenticatedActor,
        invocation_source: str,
    ) -> BillingRunDetail:
        del command, actor, invocation_source
        raise BillingRunUnavailable("Billing run persistence is unavailable")

    def get(self, run_id: UUID, *, actor: AuthenticatedActor) -> BillingRunDetail:
        del run_id, actor
        raise BillingRunUnavailable("Billing run persistence is unavailable")


class BillingRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_run_key: str = Field(min_length=1, max_length=200)
    business_date: date
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def period_is_bounded(self) -> BillingRunInput:
        if self.period_end < self.period_start:
            raise ValueError("period_end must not precede period_start")
        if (self.period_end - self.period_start).days > 62:
            raise ValueError("billing period exceeds the bounded window")
        return self


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _authorize(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=BILLING_GENERATE_CAPABILITY,
            property_id=str(property_id),
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _item_body(item: BillingRunItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "attempt_id": str(item.attempt_id),
        "attempt_number": item.attempt_number,
        "source_kind": item.source_kind,
        "source_id": str(item.source_id),
        "period_start": item.period_start.isoformat(),
        "period_end": item.period_end.isoformat(),
        "outcome": item.outcome,
        "invoice_id": str(item.invoice_id) if item.invoice_id is not None else None,
        "diagnostic_code": item.diagnostic_code,
        "recorded_at": item.recorded_at.isoformat(),
        "source_evidence": item.source_evidence,
    }


def _attempt_body(attempt: BillingRunAttempt) -> dict[str, object]:
    return {
        "id": str(attempt.id),
        "attempt_number": attempt.attempt_number,
        "started_at": attempt.started_at.isoformat(),
        "completed_at": (
            attempt.completed_at.isoformat() if attempt.completed_at is not None else None
        ),
        "outcome": attempt.outcome,
        "diagnostic_code": attempt.diagnostic_code,
        "items": [_item_body(item) for item in attempt.items],
    }


def billing_run_body(run: BillingRunDetail) -> dict[str, object]:
    return {
        "id": str(run.id),
        "property_id": str(run.property_id),
        "run_kind": run.run_kind,
        "logical_run_key": run.logical_run_key,
        "business_date": run.business_date.isoformat(),
        "period": {
            "start": run.period_start.isoformat(),
            "end": run.period_end.isoformat(),
        },
        "idempotency_key": str(run.idempotency_key),
        "request_digest": run.request_digest,
        "correlation_id": str(run.correlation_id),
        "invocation_source": run.invocation_source,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at is not None else None,
        "failure_code": run.failure_code,
        "attempts": [_attempt_body(attempt) for attempt in run.attempts],
    }


def _invoke(command: Callable[[], BillingRunDetail]) -> BillingRunDetail:
    try:
        return command()
    except BillingRunNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except BillingRunAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except BillingRunConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except BillingRunInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except BillingRunUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def create_billing_run_router(
    resolver: ActorResolver,
    flow: BillingRunFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["billing-runs"])

    def execute(
        property_id: UUID,
        run_kind: str,
        body: BillingRunInput,
        request: Request,
        idempotency_key: UUID,
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id)
        require_browser_mutation(request, settings)
        try:
            command = BillingRunCommand(
                property_id=property_id,
                run_kind=run_kind,
                logical_run_key=body.logical_run_key,
                business_date=body.business_date,
                period_start=body.period_start,
                period_end=body.period_end,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        result = _invoke(lambda: flow.execute(command, actor=actor, invocation_source="API"))
        return {
            "data": billing_run_body(result),
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/properties/{property_id}/billing-runs/rent")
    def run_rent(
        property_id: UUID,
        body: BillingRunInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        return execute(property_id, "RENT", body, request, idempotency_key)

    @router.post("/properties/{property_id}/billing-runs/utilities")
    def run_utilities(
        property_id: UUID,
        body: BillingRunInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        return execute(property_id, "UTILITIES", body, request, idempotency_key)

    @router.get("/billing-runs/{run_id}")
    def get_run(run_id: UUID, request: Request) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        result = _invoke(lambda: flow.get(run_id, actor=actor))
        return {
            "data": billing_run_body(result),
            "meta": {"request_id": request.state.request_id},
        }

    return router
