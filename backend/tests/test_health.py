"""API contract tests for liveness (API-001, API-007, API-081, TEST-011)."""

import asyncio
from collections.abc import Mapping
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from property_rental.app import create_app, normalize_request_id
from property_rental.settings import Settings


def get_liveness(app: FastAPI, headers: Mapping[str, str] | None = None) -> httpx.Response:
    return get_health(app, "/api/v1/health/live", headers)


def get_health(
    app: FastAPI,
    path: str,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

    return asyncio.run(request())


def test_readiness_returns_minimal_success_when_database_accepts_check() -> None:
    checked_urls: list[str] = []

    def database_check(database_url: str) -> None:
        checked_urls.append(database_url)

    response = get_health(
        create_app(
            Settings(database_url="postgresql://runtime:***@database/prm"),
            readiness_check=database_check,
        ),
        "/api/v1/health/ready",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert checked_urls == ["postgresql://runtime:***@database/prm"]


def test_readiness_returns_minimal_503_when_configuration_is_missing() -> None:
    def unexpected_check(database_url: str) -> None:
        raise AssertionError(f"readiness check called without configuration: {database_url}")

    response = get_health(
        create_app(Settings(database_url=None), readiness_check=unexpected_check),
        "/api/v1/health/ready",
    )

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readiness_returns_minimal_503_when_database_check_fails() -> None:
    def failed_check(database_url: str) -> None:
        raise RuntimeError("database unavailable")

    response = get_health(
        create_app(
            Settings(database_url="postgresql://runtime:***@database/prm"),
            readiness_check=failed_check,
        ),
        "/api/v1/health/ready",
    )

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_readiness_always_returns_request_id(outcome: str) -> None:
    def database_check(database_url: str) -> None:
        if outcome == "failure":
            raise RuntimeError("database unavailable")

    response = get_health(
        create_app(
            Settings(database_url="postgresql://runtime:***@database/prm"),
            readiness_check=database_check,
        ),
        "/api/v1/health/ready",
        {"X-Request-ID": "readiness-request"},
    )

    assert response.headers["x-request-id"] == "readiness-request"


@pytest.mark.parametrize(
    "diagnostic",
    [
        "SELECT secret FROM internal_table",
        "postgresql://runtime:***@database.internal/prm",
        "/protected/config/runtime.env",
        "database.internal",
        "connection refused for prm_runtime",
    ],
)
def test_readiness_failure_redacts_diagnostics(diagnostic: str) -> None:
    def failed_check(database_url: str) -> None:
        raise RuntimeError(diagnostic)

    response = get_health(
        create_app(
            Settings(database_url="postgresql://runtime:***@database.internal/prm"),
            readiness_check=failed_check,
        ),
        "/api/v1/health/ready",
    )

    assert response.status_code == 503
    assert response.text == '{"status":"unavailable"}'
    assert diagnostic not in response.text


def test_liveness_returns_minimal_stable_contract_and_request_id() -> None:
    settings = Settings(build_version="test-build")

    response = get_liveness(create_app(settings))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    UUID(response.headers["x-request-id"])
    assert response.json() == {"status": "ok", "version": "test-build"}


@pytest.mark.parametrize(
    ("caller_value", "expected"),
    [
        ("caller-request_123", "caller-request_123"),
        ("  caller-request_123  ", "caller-request_123"),
    ],
)
def test_liveness_normalizes_and_returns_safe_caller_request_id(
    caller_value: str,
    expected: str,
) -> None:
    response = get_liveness(
        create_app(Settings(build_version="test-build")),
        {"X-Request-ID": caller_value},
    )

    assert response.headers["x-request-id"] == expected


@pytest.mark.parametrize(
    "caller_value",
    ["", "contains spaces", "not/safe", "x" * 129],
)
def test_liveness_replaces_unsafe_caller_request_id(caller_value: str) -> None:
    response = get_liveness(
        create_app(Settings(build_version="test-build")),
        {"X-Request-ID": caller_value},
    )

    generated = response.headers["x-request-id"]
    UUID(generated)
    assert generated != caller_value


def test_request_id_normalization_replaces_non_ascii_value() -> None:
    generated = normalize_request_id("éxternal")

    UUID(generated)
    assert generated != "éxternal"


def test_unversioned_liveness_path_is_not_exposed() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/health/live",
                headers={"X-Request-ID": "not-found-request"},
            )

    response = asyncio.run(request())

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "not-found-request"


def test_liveness_does_not_expose_other_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "must-not-appear"
    monkeypatch.setenv("SECRET_KEY", secret)

    response = get_liveness(create_app(Settings(build_version="safe-build")))

    assert secret not in response.text
    assert response.json() == {"status": "ok", "version": "safe-build"}
