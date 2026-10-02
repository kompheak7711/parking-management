"""HTTP routes for the explicit follow-up after a termination for an unpaid Initial obligation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.settings import Settings
from property_rental.unpaid_initial_termination import (
    CreditMovedInInitialRentCommand,
    PostgresUnpaidInitialTerminationService,
    ResolveNeverMovedInCommand,
    UnpaidInitialTerminationAuthorizationError,
    UnpaidInitialTerminationConflictError,
    UnpaidInitialTerminationInvalidError,
    UnpaidInitialTerminationNotFoundError,
    UnpaidInitialTerminationUnavailableError,
)


class UnpaidInitialFlow(Protocol):
    def resolve_never_moved_in(
        self,
        property_id: UUID,
        command: ResolveNeverMovedInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def credit_moved_in_initial_rent(
        self,
        property_id: UUID,
        command: CreditMovedInInitialRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


class PostgresUnpaidInitialFlow:
    """Bind the Property-scoped service to the Property named in the route."""

    def __init__(self, financial_database_url: str) -> None:
        self._financial_database_url = financial_database_url

    def _service(self, property_id: UUID) -> PostgresUnpaidInitialTerminationService:
        return PostgresUnpaidInitialTerminationService(self._financial_database_url, property_id)

    def resolve_never_moved_in(
        self,
        property_id: UUID,
        command: ResolveNeverMovedInCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._service(property_id).resolve_never_moved_in(command, actor=actor)

    def credit_moved_in_initial_rent(
        self,
        property_id: UUID,
        command: CreditMovedInInitialRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._service(property_id).credit_moved_in_initial_rent(command, actor=actor)


class UnavailableUnpaidInitialFlow:
    def __getattr__(self, _: str) -> object:
        raise UnpaidInitialTerminationUnavailableError("Persistence is unavailable")


class NeverMovedInInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_id: UUID
    unit_status: Literal["VACANT", "CLEANING"]
    unit_status_reason: str | None = Field(
        default=None, min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$"
    )
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class MovedInCreditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_id: UUID
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


def _invoke(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except UnpaidInitialTerminationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except UnpaidInitialTerminationAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except UnpaidInitialTerminationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except (UnpaidInitialTerminationInvalidError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except UnpaidInitialTerminationUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def create_unpaid_initial_termination_router(
    resolver: ActorResolver,
    flow: UnpaidInitialFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["unpaid-initial-termination"])

    def mutation_actor(request: Request) -> AuthenticatedActor:
        actor = resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        require_browser_mutation(request, settings)
        return actor

    def envelope(request: Request, resource: dict[str, object]) -> dict[str, object]:
        return {"data": resource, "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/properties/{property_id}/lease-terminations/{termination_event_id}"
        "/unpaid-initial-never-moved-in",
        status_code=status.HTTP_201_CREATED,
    )
    def resolve_never_moved_in(
        property_id: UUID,
        termination_event_id: UUID,
        body: NeverMovedInInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = mutation_actor(request)

        def call() -> dict[str, object]:
            return flow.resolve_never_moved_in(
                property_id,
                ResolveNeverMovedInCommand(
                    idempotency_key=idempotency_key,
                    resolution_id=body.resolution_id,
                    termination_event_id=termination_event_id,
                    unit_status=body.unit_status,
                    reason=body.reason,
                    unit_status_reason=body.unit_status_reason,
                ),
                actor=actor,
            )

        return envelope(request, _invoke(call))

    @router.post(
        "/properties/{property_id}/lease-terminations/{termination_event_id}"
        "/unpaid-initial-moved-in-credit",
        status_code=status.HTTP_201_CREATED,
    )
    def credit_moved_in_initial_rent(
        property_id: UUID,
        termination_event_id: UUID,
        body: MovedInCreditInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = mutation_actor(request)

        def call() -> dict[str, object]:
            return flow.credit_moved_in_initial_rent(
                property_id,
                CreditMovedInInitialRentCommand(
                    idempotency_key=idempotency_key,
                    resolution_id=body.resolution_id,
                    termination_event_id=termination_event_id,
                    reason=body.reason,
                ),
                actor=actor,
            )

        return envelope(request, _invoke(call))

    return router
