"""Operational logging and lifecycle tests (DEPLOY-009/024, SEC-043)."""

import asyncio
import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import Logger

import httpx
from fastapi import FastAPI

from property_rental.app import create_app
from property_rental.logging import create_application_logger
from property_rental.settings import Settings


def parse_logs(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_request_log_is_structured_correlated_and_omits_sensitive_input() -> None:
    stream = io.StringIO()
    logger = create_application_logger(
        service="property-rental-backend",
        environment="test",
        level="INFO",
        stream=stream,
    )
    app = create_app(Settings(environment="test"), application_logger=logger)

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v1/health/live?token=customer-financial-secret",
                headers={
                    "Authorization": "Bearer credential-secret",
                    "X-Request-ID": "safe-correlation-id",
                },
            )

    response = asyncio.run(request())
    logs = parse_logs(stream)

    assert response.status_code == 200
    assert len(logs) == 1
    assert (
        logs[0].items()
        >= {
            "event": "request.completed",
            "service": "property-rental-backend",
            "environment": "test",
            "severity": "INFO",
            "request_id": "safe-correlation-id",
            "method": "GET",
            "status_code": 200,
        }.items()
    )
    assert isinstance(logs[0]["timestamp"], str)
    assert isinstance(logs[0]["duration_ms"], int | float)
    serialized = stream.getvalue()
    assert "token" not in serialized
    assert "customer-financial-secret" not in serialized
    assert "Authorization" not in serialized
    assert "credential-secret" not in serialized
    assert "/api/v1/health/live" not in serialized


def test_unexpected_exception_log_uses_safe_type_without_exception_diagnostic() -> None:
    stream = io.StringIO()
    logger = create_application_logger(
        service="property-rental-backend",
        environment="test",
        level="INFO",
        stream=stream,
    )
    app = create_app(Settings(environment="test"), application_logger=logger)

    @app.get("/_test/private-customer")
    def internal_error() -> None:
        raise RuntimeError("password=credential-secret customer=known financial_amount=999")

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/_test/private-customer",
                headers={"X-Request-ID": "exception-correlation-id"},
            )

    response = asyncio.run(request())
    logs = parse_logs(stream)

    assert response.status_code == 500
    assert [entry["event"] for entry in logs] == ["request.exception", "request.completed"]
    assert (
        logs[0].items()
        >= {
            "severity": "ERROR",
            "request_id": "exception-correlation-id",
            "status_code": 500,
            "exception_type": "RuntimeError",
        }.items()
    )
    serialized = stream.getvalue()
    diagnostic_fields = [
        {key: value for key, value in entry.items() if key not in {"timestamp", "duration_ms"}}
        for entry in logs
    ]
    assert "credential-secret" not in serialized
    assert "known" not in serialized
    assert "999" not in json.dumps(diagnostic_fields)
    assert "private-customer" not in serialized
    assert "Traceback" not in serialized


def test_log_formatter_ignores_non_allowlisted_extra_fields() -> None:
    stream = io.StringIO()
    logger = create_application_logger(
        service="property-rental-backend",
        environment="test",
        level="INFO",
        stream=stream,
    )

    logger.info(
        "unsafe message credential-secret",
        extra={
            "event": "safe.event",
            "request_id": "safe-correlation-id",
            "request_body": {"customer": "known", "amount": 999},
            "authorization": "Bearer credential-secret",
        },
    )

    assert (
        parse_logs(stream)[0].items()
        >= {
            "event": "safe.event",
            "request_id": "safe-correlation-id",
        }.items()
    )
    serialized = stream.getvalue()
    assert "unsafe message" not in serialized
    assert "credential-secret" not in serialized
    assert "customer" not in serialized
    assert "999" not in serialized
    assert "authorization" not in serialized


def test_lifespan_closes_owned_resources_and_logs_shutdown() -> None:
    stream = io.StringIO()
    logger: Logger = create_application_logger(
        service="property-rental-backend",
        environment="test",
        level="INFO",
        stream=stream,
    )
    lifecycle_events: list[str] = []

    @asynccontextmanager
    async def owned_resource() -> AsyncIterator[object]:
        lifecycle_events.append("opened")
        try:
            yield object()
        finally:
            lifecycle_events.append("closed")

    app: FastAPI = create_app(
        Settings(environment="test"),
        lifecycle_resources=[owned_resource()],
        application_logger=logger,
    )

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            lifecycle_events.append("serving")

    asyncio.run(run_lifespan())

    assert lifecycle_events == ["opened", "serving", "closed"]
    assert [entry["event"] for entry in parse_logs(stream)] == [
        "application.started",
        "application.stopping",
    ]
