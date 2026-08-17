"""API tests for the provider-neutral authenticated actor boundary."""

import asyncio

import httpx
from fastapi import FastAPI, Request

from property_rental.api import IDENTITY_READ_SELF_CAPABILITY
from property_rental.app import create_app
from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    CapabilityGrant,
    ObjectScope,
    is_authorized,
)
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
    actor = AuthenticatedActor(
        actor_id="opaque-actor-7",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability=IDENTITY_READ_SELF_CAPABILITY,
                    object_scopes=frozenset(
                        {ObjectScope(object_type="actor", object_id="opaque-actor-7")}
                    ),
                )
            }
        ),
    )

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


def test_authenticated_actor_without_required_capability_is_forbidden() -> None:
    app = create_app(
        Settings(),
        actor_resolver=lambda _: AuthenticatedActor(actor_id="opaque-actor-no-capability"),
    )

    response = request(
        app,
        "GET",
        "/api/v1/identity/me",
        headers={"X-Request-ID": "identity-missing-capability"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["meta"] == {"request_id": "identity-missing-capability"}


def test_authorization_denies_a_capability_grant_for_the_wrong_property_scope() -> None:
    actor = AuthenticatedActor(
        actor_id="opaque-actor-property",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability="units.read",
                    property_ids=frozenset({"property-other"}),
                )
            }
        ),
    )

    assert not is_authorized(
        actor,
        AuthorizationRequirement(capability="units.read", property_id="property-required"),
    )


def test_identity_endpoint_denies_the_wrong_exact_actor_object_scope() -> None:
    actor = AuthenticatedActor(
        actor_id="opaque-actor-object",
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability=IDENTITY_READ_SELF_CAPABILITY,
                    object_scopes=frozenset(
                        {ObjectScope(object_type="actor", object_id="different-actor")}
                    ),
                )
            }
        ),
    )

    response = request(
        create_app(Settings(), actor_resolver=lambda _: actor),
        "GET",
        "/api/v1/identity/me",
        headers={"X-Request-ID": "identity-wrong-object"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_role_and_capability_headers_do_not_grant_an_authenticated_actor_access() -> None:
    app = create_app(
        Settings(),
        actor_resolver=lambda _: AuthenticatedActor(actor_id="opaque-actor-role-header"),
    )

    response = request(
        app,
        "GET",
        "/api/v1/identity/me",
        headers={
            "X-Role": "administrator",
            "X-Capabilities": IDENTITY_READ_SELF_CAPABILITY,
            "X-Property-Scope": "property-client-asserted",
            "X-Object-Scope": "actor:opaque-actor-role-header",
            "X-Request-ID": "identity-role-independent",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_client_supplied_identity_assertions_cannot_bypass_default_denial() -> None:
    response = request(
        create_app(Settings()),
        "GET",
        "/api/v1/identity/me",
        headers={
            "Authorization": "Bearer client-asserted-token",
            "X-Actor-ID": "client-asserted-actor",
            "X-Authenticated-Actor": "client-asserted-actor",
            "X-Capabilities": IDENTITY_READ_SELF_CAPABILITY,
            "X-Property-Scope": "property-client-asserted",
            "X-Object-Scope": "actor:client-asserted-actor",
            "X-Request-ID": "identity-header-bypass",
        },
    )

    assert response.status_code == 401
    assert response.json()["meta"] == {"request_id": "identity-header-bypass"}
    assert "client-asserted" not in response.text
