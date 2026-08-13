"""FastAPI application factory."""

import re
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import uuid4

import psycopg
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from property_rental.api import create_api_router
from property_rental.settings import Settings

REQUEST_ID_HEADER: Final = "X-Request-ID"
REQUEST_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DATABASE_TIMEOUT_SECONDS: Final = 2
ERROR_STATUS_DETAILS: Final = {
    status.HTTP_400_BAD_REQUEST: ("BAD_REQUEST", "The request could not be processed."),
    status.HTTP_401_UNAUTHORIZED: ("UNAUTHORIZED", "Authentication is required."),
    status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "The request is not permitted."),
    status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "The requested resource was not found."),
    status.HTTP_409_CONFLICT: (
        "CONFLICT",
        "The request conflicts with the current resource state.",
    ),
    status.HTTP_412_PRECONDITION_FAILED: (
        "PRECONDITION_FAILED",
        "A required request precondition was not met.",
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: (
        "VALIDATION_ERROR",
        "The request did not match the required schema.",
    ),
    status.HTTP_429_TOO_MANY_REQUESTS: ("RATE_LIMITED", "Too many requests."),
    status.HTTP_500_INTERNAL_SERVER_ERROR: (
        "INTERNAL_ERROR",
        "An unexpected internal error occurred.",
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: (
        "SERVICE_UNAVAILABLE",
        "A required service is temporarily unavailable.",
    ),
}


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


def error_response(
    status_code: int,
    request_id: str,
    *,
    fields: list[str] | None = None,
) -> JSONResponse:
    """Build a canonical error envelope without accepting exception details."""
    code, message = ERROR_STATUS_DETAILS.get(
        status_code,
        ("HTTP_ERROR", "The request could not be processed."),
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or [],
                "rule_ids": [],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


def safe_validation_fields(exc: RequestValidationError) -> list[str]:
    """Return bounded field locations while excluding rejected values and diagnostics."""
    fields: set[str] = set()
    for error in exc.errors():
        location = error.get("loc")
        if not isinstance(location, tuple):
            continue
        components = [component for component in location if isinstance(component, str)]
        if components and all(REQUEST_ID_PATTERN.fullmatch(component) for component in components):
            fields.add(".".join(components))
    return sorted(fields)[:50]


def validation_status_code(exc: RequestValidationError) -> int:
    """Classify malformed JSON using only framework error type and location."""
    for error in exc.errors():
        location = error.get("loc")
        if error.get("type") == "json_invalid" and isinstance(location, tuple):
            if location and location[0] == "body":
                return status.HTTP_400_BAD_REQUEST
    return status.HTTP_422_UNPROCESSABLE_CONTENT


def create_app(
    settings: Settings | None = None,
    readiness_check: Callable[[str], None] = check_database_readiness,
) -> FastAPI:
    """Build an application instance from validated settings."""
    resolved_settings = settings or Settings()
    app = FastAPI(title=resolved_settings.service_name, version=resolved_settings.build_version)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        status_code = validation_status_code(exc)
        return error_response(
            status_code,
            request.state.request_id,
            fields=(
                safe_validation_fields(exc)
                if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
                else None
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, request.state.request_id)

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            return error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, request_id)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.include_router(create_api_router(resolved_settings, readiness_check))
    return app


app = create_app()
