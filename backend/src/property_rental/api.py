"""Versioned HTTP API routes."""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from property_rental.identity import ActorResolver
from property_rental.settings import Settings


class HealthResponse(BaseModel):
    """Stable, deliberately minimal unauthenticated liveness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    version: str


class ReadinessResponse(BaseModel):
    """Stable, deliberately minimal unauthenticated readiness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "unavailable"]


class ActorIdentity(BaseModel):
    """Opaque stable identity for the current authenticated actor."""

    model_config = ConfigDict(frozen=True)

    actor_id: str


class ResponseMeta(BaseModel):
    """Canonical response correlation metadata."""

    model_config = ConfigDict(frozen=True)

    request_id: str


class IdentityResponse(BaseModel):
    """Canonical resource envelope for the current authenticated actor."""

    model_config = ConfigDict(frozen=True)

    data: ActorIdentity
    meta: ResponseMeta


def create_api_router(
    settings: Settings,
    readiness_check: Callable[[str], None],
    actor_resolver: ActorResolver,
) -> APIRouter:
    """Create API routes with explicit configuration dependencies."""
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/health/live",
        response_model=HealthResponse,
        response_model_exclude_none=True,
        tags=["health"],
        summary="Process liveness",
    )
    def liveness() -> HealthResponse:
        return HealthResponse(version=settings.build_version)

    @router.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["health"],
        summary="Database-backed readiness",
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    )
    def readiness(response: Response) -> ReadinessResponse:
        database_url = settings.database_url
        if database_url is None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="unavailable")

        try:
            readiness_check(database_url.get_secret_value())
        except Exception:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="unavailable")
        return ReadinessResponse(status="ok")

    @router.get(
        "/identity/me",
        response_model=IdentityResponse,
        tags=["identity"],
        summary="Current authenticated actor identity",
    )
    def current_identity(request: Request) -> IdentityResponse:
        actor = actor_resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return IdentityResponse(
            data=ActorIdentity(actor_id=actor.actor_id),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    return router
