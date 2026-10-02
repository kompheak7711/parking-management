"""HTTP routes for the Utility baseline, final Utility inputs, final and catch-up Invoices."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.final_utility_invoice import (
    CatchUpUtilityInvoice,
    CreateFinalUtilityInvoice,
    FinalUtilityInvoiceAuthorizationError,
    FinalUtilityInvoiceConflictError,
    FinalUtilityInvoiceInvalidError,
    FinalUtilityInvoiceKeyReused,
    FinalUtilityInvoiceNotFoundError,
    FinalUtilityInvoiceUnavailableError,
    PostgresFinalUtilityInvoiceService,
    PostgresUnbilledUtilityPeriodsService,
    UtilityInvoiceResponse,
)
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.move_out_final_inputs import (
    FinalInputItem,
    MoveOutFinalInputsAuthorizationError,
    MoveOutFinalInputsConflictError,
    MoveOutFinalInputsInvalidError,
    MoveOutFinalInputsKeyReused,
    MoveOutFinalInputsNotFoundError,
    MoveOutFinalInputsResponse,
    MoveOutFinalInputsUnavailableError,
    PostgresMoveOutFinalInputsService,
    RecordMoveOutFinalInputs,
)
from property_rental.settings import Settings
from property_rental.utility_baseline import (
    BaselineItem,
    PostgresUtilityBaselineService,
    RecordUtilityBaseline,
    UtilityBaselineAuthorizationError,
    UtilityBaselineConflictError,
    UtilityBaselineInvalidError,
    UtilityBaselineKeyReused,
    UtilityBaselineNotFoundError,
    UtilityBaselineResponse,
    UtilityBaselineUnavailableError,
)

Text = Annotated[str, Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")]
T = TypeVar("T")

NOT_FOUND = (
    UtilityBaselineNotFoundError,
    MoveOutFinalInputsNotFoundError,
    FinalUtilityInvoiceNotFoundError,
)
FORBIDDEN = (
    UtilityBaselineAuthorizationError,
    MoveOutFinalInputsAuthorizationError,
    FinalUtilityInvoiceAuthorizationError,
)
KEY_REUSED = (UtilityBaselineKeyReused, MoveOutFinalInputsKeyReused, FinalUtilityInvoiceKeyReused)
CONFLICT = (
    UtilityBaselineConflictError,
    MoveOutFinalInputsConflictError,
    FinalUtilityInvoiceConflictError,
)
INVALID = (
    UtilityBaselineInvalidError,
    MoveOutFinalInputsInvalidError,
    FinalUtilityInvoiceInvalidError,
)
UNAVAILABLE = (
    UtilityBaselineUnavailableError,
    MoveOutFinalInputsUnavailableError,
    FinalUtilityInvoiceUnavailableError,
)


class UtilityLeaseFlow(Protocol):
    def baseline_read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int,
        offset: int,
    ) -> dict[str, object]: ...

    def baseline_record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordUtilityBaseline,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityBaselineResponse: ...

    def final_inputs_read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int,
        offset: int,
    ) -> dict[str, object]: ...

    def final_inputs_record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordMoveOutFinalInputs,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> MoveOutFinalInputsResponse: ...

    def create_final(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CreateFinalUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse: ...

    def catch_up(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CatchUpUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse: ...

    def unbilled_periods(
        self, property_id: UUID, *, actor: AuthenticatedActor, limit: int, offset: int
    ) -> dict[str, object]: ...


class PostgresUtilityLeaseFlow:
    """Compose the four Property-scoped services over the runtime and financial roles."""

    def __init__(self, database_url: str, financial_database_url: str | None) -> None:
        self._baseline = PostgresUtilityBaselineService(database_url, financial_database_url)
        self._inputs = PostgresMoveOutFinalInputsService(database_url, financial_database_url)
        self._unbilled = PostgresUnbilledUtilityPeriodsService(database_url)
        self._invoices = (
            PostgresFinalUtilityInvoiceService(financial_database_url)
            if financial_database_url is not None
            else None
        )

    def baseline_read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        return self._baseline.read(property_id, lease_id, actor=actor, limit=limit, offset=offset)

    def baseline_record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordUtilityBaseline,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityBaselineResponse:
        return self._baseline.record(
            property_id, lease_id, command, actor=actor, request_id=request_id
        )

    def final_inputs_read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        return self._inputs.read(property_id, lease_id, actor=actor, limit=limit, offset=offset)

    def final_inputs_record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordMoveOutFinalInputs,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> MoveOutFinalInputsResponse:
        return self._inputs.record(
            property_id, lease_id, command, actor=actor, request_id=request_id
        )

    def _invoice_service(self) -> PostgresFinalUtilityInvoiceService:
        if self._invoices is None:
            raise FinalUtilityInvoiceUnavailableError("Persistence is unavailable")
        return self._invoices

    def create_final(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CreateFinalUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse:
        return self._invoice_service().create_final(
            property_id, lease_id, command, actor=actor, request_id=request_id
        )

    def catch_up(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CatchUpUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse:
        return self._invoice_service().catch_up(
            property_id, lease_id, command, actor=actor, request_id=request_id
        )

    def unbilled_periods(
        self, property_id: UUID, *, actor: AuthenticatedActor, limit: int, offset: int
    ) -> dict[str, object]:
        return self._unbilled.read(property_id, actor=actor, limit=limit, offset=offset)


class UnavailableUtilityLeaseFlow:
    def __getattr__(self, _: str) -> object:
        raise UtilityBaselineUnavailableError("Persistence is unavailable")


class BaselineItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meter_id: UUID
    reading_id: UUID


class BaselineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    supersedes_event_id: UUID | None = None
    baseline_date: date
    reason: Text
    evidence_reference: Text
    items: Annotated[list[BaselineItemInput], Field(min_length=1, max_length=20)]


class FinalInputItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meter_id: UUID
    resolution: Literal["READING", "ESTIMATE", "UNRESOLVED"]
    reading_id: UUID | None = None
    estimate_id: UUID | None = None
    unresolved_reason: str | None = Field(default=None, min_length=1, max_length=100)


class FinalInputsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    move_out_event_id: UUID
    supersedes_event_id: UUID | None = None
    reason: Text
    authorization_reference: Text
    evidence_reference: Text
    items: Annotated[list[FinalInputItemInput], Field(min_length=1, max_length=20)]


class DueDateOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_date: date | None = None
    due_date_reason: Text | None = None


class FinalInvoiceInput(DueDateOverride):
    invoice_id: UUID
    final_input_event_id: UUID


class CatchUpInput(DueDateOverride):
    invoice_id: UUID
    consumption_period_id: UUID


def _problem(request: Request, http_status: int, code: str) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": code,
                "message": "The Utility request could not be completed.",
                "fields": [],
                "rule_ids": [],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def create_utility_lease_router(
    resolver: ActorResolver,
    flow: UtilityLeaseFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["utility-lease"])

    def actor_for(
        request: Request, *, mutation: bool, allowed: frozenset[str]
    ) -> AuthenticatedActor:
        actor = resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if any(name not in allowed for name in request.query_params):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        if mutation:
            require_browser_mutation(request, settings)
        return actor

    def invoke(request: Request, call: Callable[[], T]) -> T | JSONResponse:
        try:
            return call()
        except KEY_REUSED:
            return _problem(request, status.HTTP_409_CONFLICT, "IDEMPOTENCY_KEY_REUSED")
        except NOT_FOUND:
            return _problem(request, status.HTTP_404_NOT_FOUND, "NOT_FOUND")
        except FORBIDDEN:
            return _problem(request, status.HTTP_403_FORBIDDEN, "FORBIDDEN")
        except CONFLICT as exc:
            return _problem(request, status.HTTP_409_CONFLICT, _reason(exc, "CONFLICT"))
        except INVALID as exc:
            return _problem(
                request, status.HTTP_422_UNPROCESSABLE_CONTENT, _reason(exc, "VALIDATION_ERROR")
            )
        except ValueError:
            return _problem(request, status.HTTP_422_UNPROCESSABLE_CONTENT, "VALIDATION_ERROR")
        except UNAVAILABLE:
            return _problem(request, status.HTTP_503_SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE")

    def reply(request: Request, outcome: object) -> object:
        if isinstance(outcome, JSONResponse):
            return outcome
        if isinstance(
            outcome, (UtilityBaselineResponse, MoveOutFinalInputsResponse, UtilityInvoiceResponse)
        ):
            return JSONResponse(status_code=outcome.status_code, content=outcome.body)
        return {"data": outcome, "meta": {"request_id": request.state.request_id}}

    @router.get("/properties/{property_id}/leases/{lease_id}/utility-baseline", response_model=None)
    def read_baseline(
        property_id: UUID,
        lease_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> object:
        actor = actor_for(request, mutation=False, allowed=frozenset({"limit", "offset"}))
        return reply(
            request,
            invoke(
                request,
                lambda: flow.baseline_read(
                    property_id, lease_id, actor=actor, limit=limit, offset=offset
                ),
            ),
        )

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/utility-baseline",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def record_baseline(
        property_id: UUID,
        lease_id: UUID,
        body: BaselineInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> object:
        actor = actor_for(request, mutation=True, allowed=frozenset())

        def call() -> UtilityBaselineResponse:
            return flow.baseline_record(
                property_id,
                lease_id,
                RecordUtilityBaseline(
                    idempotency_key=idempotency_key,
                    event_id=body.event_id,
                    baseline_date=body.baseline_date,
                    items=tuple(BaselineItem(i.meter_id, i.reading_id) for i in body.items),
                    reason=body.reason,
                    evidence_reference=body.evidence_reference,
                    supersedes_event_id=body.supersedes_event_id,
                ),
                actor=actor,
                request_id=request.state.request_id,
            )

        return reply(request, invoke(request, call))

    @router.get(
        "/properties/{property_id}/leases/{lease_id}/move-out-final-utility-inputs",
        response_model=None,
    )
    def read_final_inputs(
        property_id: UUID,
        lease_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=20)] = 20,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> object:
        actor = actor_for(request, mutation=False, allowed=frozenset({"limit", "offset"}))
        return reply(
            request,
            invoke(
                request,
                lambda: flow.final_inputs_read(
                    property_id, lease_id, actor=actor, limit=limit, offset=offset
                ),
            ),
        )

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/move-out-final-utility-inputs",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def record_final_inputs(
        property_id: UUID,
        lease_id: UUID,
        body: FinalInputsInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> object:
        actor = actor_for(request, mutation=True, allowed=frozenset())

        def call() -> MoveOutFinalInputsResponse:
            return flow.final_inputs_record(
                property_id,
                lease_id,
                RecordMoveOutFinalInputs(
                    idempotency_key=idempotency_key,
                    event_id=body.event_id,
                    move_out_event_id=body.move_out_event_id,
                    items=tuple(
                        FinalInputItem(
                            meter_id=i.meter_id,
                            resolution=i.resolution,
                            reading_id=i.reading_id,
                            estimate_id=i.estimate_id,
                            unresolved_reason=i.unresolved_reason,
                        )
                        for i in body.items
                    ),
                    reason=body.reason,
                    authorization_reference=body.authorization_reference,
                    evidence_reference=body.evidence_reference,
                    supersedes_event_id=body.supersedes_event_id,
                ),
                actor=actor,
                request_id=request.state.request_id,
            )

        return reply(request, invoke(request, call))

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/final-utility-invoice",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def create_final_invoice(
        property_id: UUID,
        lease_id: UUID,
        body: FinalInvoiceInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> object:
        actor = actor_for(request, mutation=True, allowed=frozenset())

        def call() -> UtilityInvoiceResponse:
            return flow.create_final(
                property_id,
                lease_id,
                CreateFinalUtilityInvoice(
                    idempotency_key=idempotency_key,
                    invoice_id=body.invoice_id,
                    final_input_event_id=body.final_input_event_id,
                    due_date=body.due_date,
                    due_date_reason=body.due_date_reason,
                ),
                actor=actor,
                request_id=request.state.request_id,
            )

        return reply(request, invoke(request, call))

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/utility-catch-up-invoice",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def create_catch_up_invoice(
        property_id: UUID,
        lease_id: UUID,
        body: CatchUpInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> object:
        actor = actor_for(request, mutation=True, allowed=frozenset())

        def call() -> UtilityInvoiceResponse:
            return flow.catch_up(
                property_id,
                lease_id,
                CatchUpUtilityInvoice(
                    idempotency_key=idempotency_key,
                    invoice_id=body.invoice_id,
                    consumption_period_id=body.consumption_period_id,
                    due_date=body.due_date,
                    due_date_reason=body.due_date_reason,
                ),
                actor=actor,
                request_id=request.state.request_id,
            )

        return reply(request, invoke(request, call))

    @router.get("/properties/{property_id}/unbilled-utility-periods", response_model=None)
    def list_unbilled_periods(
        property_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> object:
        actor = actor_for(request, mutation=False, allowed=frozenset({"limit", "offset"}))
        return reply(
            request,
            invoke(
                request,
                lambda: flow.unbilled_periods(property_id, actor=actor, limit=limit, offset=offset),
            ),
        )

    return router


def _reason(error: Exception, default: str) -> str:
    reason = getattr(error, "reason", None)
    return reason if isinstance(reason, str) and reason else default
