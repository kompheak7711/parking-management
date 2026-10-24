"""Tests for the authorized, versioned Property HTTP resource."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import ActorResolver, AuthenticatedActor, CapabilityGrant
from property_rental.property_api import (
    PaymentMethodConfiguration,
    PostgresPropertyResourceFlow,
    PropertyResource,
    PropertyVersionConflict,
)


@dataclass(slots=True)
class InMemoryPropertyResourceFlow:
    """Deterministic Property application-flow double."""

    resource: PropertyResource
    patch_calls: int = 0

    def get(self, property_id: UUID) -> PropertyResource:
        if property_id != self.resource.property_id:
            from property_rental.property_api import PropertyResourceNotFound

            raise PropertyResourceNotFound("not found")
        return self.resource

    def patch_source(
        self,
        property_id: UUID,
        *,
        name: str,
        address_text: str | None,
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        del actor_id
        if expected_version != self.resource.version:
            raise PropertyVersionConflict(self.resource.version)
        self.patch_calls += 1
        self.resource = PropertyResource(
            property_id=property_id,
            name=name,
            address_text=address_text,
            timezone_name=self.resource.timezone_name,
            payment_methods=self.resource.payment_methods,
            version=self.resource.version + 1,
        )
        return self.resource

    def patch_configuration(
        self,
        property_id: UUID,
        *,
        payment_methods: tuple[PaymentMethodConfiguration, ...],
        expected_version: int,
        actor_id: str,
    ) -> PropertyResource:
        del actor_id
        if expected_version != self.resource.version:
            raise PropertyVersionConflict(self.resource.version)
        self.patch_calls += 1
        self.resource = PropertyResource(
            property_id=property_id,
            name=self.resource.name,
            address_text=self.resource.address_text,
            timezone_name=self.resource.timezone_name,
            payment_methods=payment_methods,
            version=self.resource.version + 1,
        )
        return self.resource


def property_resource(property_id: UUID, *, version: int = 1) -> PropertyResource:
    return PropertyResource(
        property_id=property_id,
        name="Riverside",
        address_text="Phnom Penh",
        timezone_name="Asia/Phnom_Penh",
        payment_methods=(PaymentMethodConfiguration(uuid4(), "BANK", "Bank transfer", True),),
        version=version,
    )


def resolving(actor: AuthenticatedActor) -> ActorResolver:
    return lambda _: actor


def actor_with(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id="property-actor",
        capability_grants=frozenset(
            CapabilityGrant(capability=capability, property_ids=frozenset({str(property_id)}))
            for capability in capabilities
        ),
    )


def actor_with_settings_access(property_id: UUID) -> AuthenticatedActor:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): the Property update and its
    configuration are Settings, so they need `settings.manage`."""
    return actor_with(property_id, "settings.manage")


def browser_headers(if_match: str | None = None) -> dict[str, str]:
    headers = {
        "Origin": "https://localhost",
        "Cookie": "__Host-prm_csrf=csrf-test-token",
        "X-CSRF-Token": "csrf-test-token",
    }
    if if_match is not None:
        headers["If-Match"] = if_match
    return headers


def test_get_property_returns_identity_timezone_version_and_etag() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=3))
    client = TestClient(
        create_app(
            # Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): reading needs
            # `property.read` for this Property.
            actor_resolver=lambda _: actor_with(property_id, "property.read"),
            property_resource_flow=flow,
        )
    )

    response = client.get(f"/properties/{property_id}")

    assert response.status_code == 200
    assert response.headers["etag"] == '"3"'
    assert response.json()["data"] == {
        "property_id": str(property_id),
        "name": "Riverside",
        "address_text": "Phnom Penh",
        "timezone_name": "Asia/Phnom_Penh",
        "version": 3,
        "configuration": {
            "timezone_name": "Asia/Phnom_Penh",
            "accepted_payment_methods": [{"code": "BANK", "display_name": "Bank transfer"}],
        },
    }


def test_get_property_requires_an_authenticated_actor() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id))
    client = TestClient(create_app(property_resource_flow=flow))

    response = client.get(f"/properties/{property_id}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_postgres_property_read_uses_one_snapshot_statement() -> None:
    property_id = uuid4()
    method_id = uuid4()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = [
        (
            property_id,
            "Riverside",
            "Phnom Penh",
            "Asia/Phnom_Penh",
            3,
            method_id,
            "BANK",
            "Bank transfer",
            True,
        )
    ]

    with patch(
        "property_rental.property_api.psycopg.connect",
        return_value=connection,
    ):
        resource = PostgresPropertyResourceFlow("postgresql://runtime").get(property_id)

    connection.execute.assert_called_once()
    statement = connection.execute.call_args.args[0]
    assert "LEFT JOIN app.payment_methods" in statement
    assert resource.version == 3
    assert resource.payment_methods == (
        PaymentMethodConfiguration(method_id, "BANK", "Bank transfer", True),
    )


def test_get_property_needs_property_read_for_this_property() -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): a signed-in user without
    `property.read`, or with it for another Property only, is refused."""
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id))
    for actor in (
        AuthenticatedActor(actor_id="reader"),
        actor_with(uuid4(), "property.read"),
        actor_with(property_id, "property.manage", "settings.manage"),
    ):
        client = TestClient(
            create_app(actor_resolver=resolving(actor), property_resource_flow=flow)
        )
        assert client.get(f"/properties/{property_id}").status_code == 403


def test_patch_property_requires_scoped_property_manage() -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): `property.manage` alone, or
    `settings.manage` for another Property, no longer changes the Property. The name describes
    the check before L5; it is kept because its traceability entry is among the entries that are
    never edited (docs/010, updated tests of L5)."""
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id))
    for actor in (
        AuthenticatedActor(actor_id="reader"),
        actor_with(property_id, "property.manage", "property.read"),
        actor_with(uuid4(), "settings.manage"),
    ):
        client = TestClient(
            create_app(actor_resolver=resolving(actor), property_resource_flow=flow)
        )
        response = client.patch(
            f"/properties/{property_id}",
            headers=browser_headers('"1"'),
            json={"name": "Riverside Apartments", "address_text": "Phnom Penh"},
        )
        assert response.status_code == 403
    assert flow.patch_calls == 0


def test_get_property_configuration_requires_scoped_property_manage() -> None:
    """Login sub-slice L5 (Q-2026-10-24-186): the configuration is read by a person who may
    change it (`settings.manage`) or, as before, a Property manager (`property.manage`). The
    name is kept (its traceability entry is never edited)."""
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id))
    for actor, status_code in (
        (AuthenticatedActor(actor_id="reader"), 403),
        (actor_with(property_id, "property.read"), 403),
        (actor_with(uuid4(), "settings.manage"), 403),
        (actor_with(property_id, "settings.manage"), 200),
        (actor_with(property_id, "property.manage"), 200),
    ):
        client = TestClient(
            create_app(actor_resolver=resolving(actor), property_resource_flow=flow)
        )
        response = client.get(f"/properties/{property_id}/configuration")
        assert response.status_code == status_code


def test_patch_property_applies_matching_version_precondition() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=4))
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with_settings_access(property_id),
            property_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/properties/{property_id}",
        headers=browser_headers('"4"'),
        json={"name": "Riverside Apartments", "address_text": "New address"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Riverside Apartments"
    assert response.json()["data"]["version"] == 5
    assert response.headers["etag"] == '"5"'
    assert flow.patch_calls == 1


def test_patch_property_reports_current_version_for_missing_precondition() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=7))
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with_settings_access(property_id),
            property_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/properties/{property_id}",
        headers=browser_headers(),
        json={"name": "Riverside", "address_text": None},
    )

    assert response.status_code == 412
    assert response.json()["error"]["current_version"] == 7
    assert flow.patch_calls == 0


@pytest.mark.parametrize("if_match", ['"6"', '"999999999999999999999999999999"'])
def test_patch_property_rejects_mismatched_or_out_of_range_precondition(
    if_match: str,
) -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=7))
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with_settings_access(property_id),
            property_resource_flow=flow,
        )
    )

    response = client.patch(
        f"/properties/{property_id}",
        headers=browser_headers(if_match),
        json={"name": "Riverside", "address_text": None},
    )

    assert response.status_code == 412
    assert response.json()["error"]["current_version"] == 7
    assert flow.patch_calls == 0


def test_property_configuration_routes_share_authorization_and_versioning() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=2))
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with_settings_access(property_id),
            property_resource_flow=flow,
        )
    )

    get_response = client.get(f"/properties/{property_id}/configuration")
    patch_response = client.patch(
        f"/properties/{property_id}/configuration",
        headers=browser_headers("2"),
        json={
            "timezone_name": "Asia/Phnom_Penh",
            "payment_methods": [
                {
                    "code": "BANK",
                    "display_name": "Bank transfer",
                    "accepted": False,
                },
                {"code": "CASH", "display_name": "Cash", "accepted": True},
            ],
        },
    )

    assert get_response.status_code == 200
    assert get_response.json()["data"]["version"] == 2
    assert get_response.json()["data"]["payment_methods"] == [
        {"code": "BANK", "display_name": "Bank transfer", "accepted": True}
    ]
    assert patch_response.status_code == 200
    assert patch_response.json()["data"]["version"] == 3
    assert patch_response.json()["data"]["payment_methods"] == [
        {"code": "BANK", "display_name": "Bank transfer", "accepted": False},
        {"code": "CASH", "display_name": "Cash", "accepted": True},
    ]


def test_property_mutations_require_browser_origin_and_csrf() -> None:
    property_id = uuid4()
    flow = InMemoryPropertyResourceFlow(property_resource(property_id, version=2))
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with_settings_access(property_id),
            property_resource_flow=flow,
        )
    )
    response = client.patch(
        f"/properties/{property_id}/configuration",
        headers={"If-Match": "2"},
        json={
            "timezone_name": "Asia/Phnom_Penh",
            "payment_methods": [],
        },
    )
    assert response.status_code == 403
    assert flow.patch_calls == 0
