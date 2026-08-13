"""Versioned HTTP API routes."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from property_rental.settings import Settings


class HealthResponse(BaseModel):
    """Stable, deliberately minimal unauthenticated liveness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    version: str


def create_api_router(settings: Settings) -> APIRouter:
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

    return router
