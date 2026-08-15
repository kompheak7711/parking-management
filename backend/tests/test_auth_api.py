"""API tests for the provider-neutral authenticated actor boundary."""

import asyncio

import httpx
from fastapi import FastAPI, Request

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.settings import Settings


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers)

    return asyncio.run(send())


def test_identity_endpoint_denies_by_default_with_canonical_correlation() -> None:
    response = request(
        create_app(Settings()),
        "GET",
        "/api/v1/identity/me",
        headers={"X-Request-ID": "identity-denied"},
    )

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "identity-denied"
    assert response.json() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "Authentication is required.",
            "fields": [],
            "rule_ids": [],
            "current_version": None,
        },
        "meta": {"request_id": "identity-denied"},
    }


def test_health_remains_public_and_minimal_without_an_actor_provider() -> None:
    response = request(
        create_app(Settings(build_version="test-build")),
        "GET",
        "/api/v1/health/live",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "test-build"}


def test_injected_provider_establishes_stable_opaque_actor_identity() -> None:
    actor = AuthenticatedActor(actor_id="opaque-actor-7")

    def resolve_actor(request: Request) -> AuthenticatedActor:
        assert request.url.path == "/api/v1/identity/me"
        return actor

    app = create_app(Settings(), actor_resolver=resolve_actor)

    first = request(
        app,
        "GET",
        "/api/v1/identity/me",
        headers={"X-Request-ID": "identity-success-1"},
    )
    second = request(
        app,
        "GET",
        "/api/v1/identity/me",
        headers={"X-Request-ID": "identity-success-2"},
    )

    assert first.status_code == 200
    assert first.headers["X-Request-ID"] == "identity-success-1"
    assert first.json() == {
        "data": {"actor_id": "opaque-actor-7"},
        "meta": {"request_id": "identity-success-1"},
    }
    assert second.json()["data"] == first.json()["data"]
    assert second.json()["meta"] == {"request_id": "identity-success-2"}


def test_client_supplied_identity_assertions_cannot_bypass_default_denial() -> None:
    response = request(
        create_app(Settings()),
        "GET",
        "/api/v1/identity/me",
        headers={
            "Authorization": "Bearer client-asserted-token",
            "X-Actor-ID": "client-asserted-actor",
            "X-Authenticated-Actor": "client-asserted-actor",
            "X-Request-ID": "identity-header-bypass",
        },
    )

    assert response.status_code == 401
    assert response.json()["meta"] == {"request_id": "identity-header-bypass"}
    assert "client-asserted" not in response.text
