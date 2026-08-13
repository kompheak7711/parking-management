"""Versioned HTTP API routes."""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

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


def create_api_router(settings: Settings, readiness_check: Callable[[str], None]) -> APIRouter:
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

    return router
