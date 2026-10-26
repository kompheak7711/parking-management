"""Versioned HTTP API routes."""

from collections.abc import Callable
from typing import Final, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    ObjectScope,
    is_authorized,
)
from property_rental.settings import Settings

IDENTITY_READ_SELF_CAPABILITY: Final = "identity.read_self"


def require_billing_actor(request: Request, actor: AuthenticatedActor) -> None:
    """Bind opted-in billing transmissions to the actor who confirmed the intent.

    Resolve once at the authenticated command boundary and pass that same actor
    to the service. Legacy clients without the header retain their contract.
    """
    expected = request.headers.get("X-Billing-Actor-ID")
    if expected is not None and expected != actor.actor_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


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


class CapabilityAccess(BaseModel):
    """One capability of the current actor and the Properties it covers (V1-058 R1b)."""

    model_config = ConfigDict(frozen=True)

    capability: str
    property_ids: list[str]


class ActorAccess(BaseModel):
    """What the current actor may use, so the screens show only those menu items.

    It repeats the actor's own grants for display only; every route still checks them."""

    model_config = ConfigDict(frozen=True)

    actor_id: str
    capabilities: list[CapabilityAccess]


class ActorAccessResponse(BaseModel):
    """Canonical resource envelope for the current actor's access."""

    model_config = ConfigDict(frozen=True)

    data: ActorAccess
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
        requirement = AuthorizationRequirement(
            capability=IDENTITY_READ_SELF_CAPABILITY,
            object_scope=ObjectScope(object_type="actor", object_id=actor.actor_id),
        )
        if not is_authorized(actor, requirement):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return IdentityResponse(
            data=ActorIdentity(actor_id=actor.actor_id),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.get(
        "/identity/me/access",
        response_model=ActorAccessResponse,
        tags=["identity"],
        summary="The current actor's capabilities and their Properties, for the menu",
    )
    def current_access(request: Request, response: Response) -> ActorAccessResponse:
        actor = actor_resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        requirement = AuthorizationRequirement(
            capability=IDENTITY_READ_SELF_CAPABILITY,
            object_scope=ObjectScope(object_type="actor", object_id=actor.actor_id),
        )
        if not is_authorized(actor, requirement):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        merged: dict[str, set[str]] = {}
        for grant in actor.capability_grants:
            merged.setdefault(grant.capability, set()).update(grant.property_ids)
        response.headers["Cache-Control"] = "no-store"
        return ActorAccessResponse(
            data=ActorAccess(
                actor_id=actor.actor_id,
                capabilities=[
                    CapabilityAccess(capability=name, property_ids=sorted(merged[name]))
                    for name in sorted(merged)
                ],
            ),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    return router
