"""FastAPI application factory."""

import re
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Request, Response

from property_rental.api import create_api_router
from property_rental.settings import Settings

REQUEST_ID_HEADER: Final = "X-Request-ID"
REQUEST_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DATABASE_TIMEOUT_SECONDS: Final = 2


def check_database_readiness(database_url: str) -> None:
    """Confirm PostgreSQL accepts one bounded authenticated query."""
    with psycopg.connect(
        database_url,
        connect_timeout=DATABASE_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={DATABASE_TIMEOUT_SECONDS * 1000}",
    ) as connection:
        result = connection.execute("SELECT 1").fetchone()
        if result != (1,):
            raise RuntimeError("database readiness check returned an unexpected result")


def normalize_request_id(value: str | None) -> str:
    """Return a safe caller correlation ID or a generated fallback."""
    if value is not None:
        normalized = value.strip()
        if REQUEST_ID_PATTERN.fullmatch(normalized):
            return normalized
    return str(uuid4())


def create_app(
    settings: Settings | None = None,
    readiness_check: Callable[[str], None] = check_database_readiness,
) -> FastAPI:
    """Build an application instance from validated settings."""
    resolved_settings = settings or Settings()
    app = FastAPI(title=resolved_settings.service_name, version=resolved_settings.build_version)

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.include_router(create_api_router(resolved_settings, readiness_check))
    return app


app = create_app()
