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
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/health/live", headers=headers)

    return asyncio.run(request())


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
