"""Migration 20270401_251 (V1-061, owner 2026-10-29, DL-110): a Unit's default Rent and its
required Services.

- A Manager or the Owner sets the default Rent and the required Services at the Unit's version;
  each change is kept in the Unit's History.
- A new Lease draft that leaves out a required Service is refused ("Ticked and locked").
- A Rent below the default Rent needs the right `rent.below_default`, which the default Owner and
  Manager bundles hold ("Lower Rent needs a Manager").
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_api import PostgresLeaseResourceFlow
from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnitResourceInvalid,
    UnitVersionConflict,
)
from test_lease_api_migration import headers, runtime_database_url
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_migration import setup_sources


def _service(connection: psycopg.Connection[tuple[object, ...]], prop: UUID, actor: UUID) -> UUID:
    service_id = uuid4()
    connection.execute(
        "INSERT INTO app.property_services("
        "id,property_id,service_code,display_name,configured_by,created_by,updated_by) "
        "VALUES (%s,%s,%s,'Parking Service',%s,%s,%s)",
        (service_id, prop, f"parking-{service_id.hex[:8]}", actor, actor, actor),
    )
    return service_id


def _approval(
    connection: psycopg.Connection[tuple[object, ...]], service: UUID, actor: UUID
) -> UUID:
    approval_id = uuid4()
    connection.execute(
        "INSERT INTO app.property_service_approval_periods("
        "id,property_service_id,effective_from,effective_through,approval_reference,"
        "approved_at,approved_by,reason) "
        "VALUES (%s,%s,'2027-01-01',NULL,'owner-approval',clock_timestamp(),%s,"
        "'Approved fixed term')",
        (approval_id, service, actor),
    )
    return approval_id


def _setup(url: str) -> dict[str, UUID]:
    with psycopg.connect(url) as connection:
        actor, prop, unit, tenant, _ = setup_sources(connection)
        required = _service(connection, prop, actor)
        approval = _approval(connection, required, actor)
        connection.commit()
    return {
        "actor": actor,
        "prop": prop,
        "unit": unit,
        "tenant": tenant,
        "required": required,
        "approval": approval,
    }


def _who(case: dict[str, UUID], *extra: str) -> AuthenticatedActor:
    scope = frozenset({str(case["prop"])})
    return AuthenticatedActor(
        actor_id=str(case["actor"]),
        capability_grants=frozenset(
            CapabilityGrant(value, scope) for value in ("leases.read", "leases.draft", *extra)
        ),
    )


def _client(actor: AuthenticatedActor) -> TestClient:
    value = TestClient(
        create_app(
            actor_resolver=lambda _: actor,
            lease_resource_flow=PostgresLeaseResourceFlow(runtime_database_url()),
        )
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def _set(case: dict[str, UUID], rent: int | None, services: tuple[UUID, ...]) -> None:
    flow = PostgresUnitResourceFlow(runtime_database_url())
    unit = flow.get(case["unit"])
    flow.set_rent_terms(
        case["unit"],
        default_monthly_rent_usd_cents=rent,
        required_service_ids=services,
        expected_version=unit.version,
        actor_id=str(case["actor"]),
    )


def _draft(case: dict[str, UUID], rent: int, *, with_service: bool) -> dict[str, object]:
    terms = (
        [
            {
                "term_id": str(uuid4()),
                "property_service_id": str(case["required"]),
                "applicable_from": "2027-01-01",
                "applicable_through": "2027-12-31",
                "service_approval_period_id": str(case["approval"]),
                "terms_reference": "Required Parking Service",
            }
        ]
        if with_service
        else []
    )
    return {
        "lease_id": str(uuid4()),
        "unit_id": str(case["unit"]),
        "primary_tenant_id": str(case["tenant"]),
        "primary_signer_id": str(uuid4()),
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
        "monthly_rent_usd_cents": rent,
        "predecessor_lease_id": None,
        "additional_signers": [],
        "planned_occupant_customer_ids": [str(case["tenant"])],
        "service_terms": terms,
        "pet_term": None,
        "security_deposit_id": None,
        "event_id": str(uuid4()),
        "reason": "Lease draft for the Unit",
    }


def test_rent_terms_are_set_at_the_unit_version_and_kept_in_history(
    migrated_database_url: str,
) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    before = flow.get(case["unit"])
    assert (before.default_monthly_rent_usd_cents, before.required_service_ids) == (None, ())
    updated = flow.set_rent_terms(
        case["unit"],
        default_monthly_rent_usd_cents=45_000,
        required_service_ids=(case["required"],),
        expected_version=before.version,
        actor_id=str(case["actor"]),
    )
    assert updated.version == before.version + 1
    assert updated.default_monthly_rent_usd_cents == 45_000
    assert updated.required_service_ids == (case["required"],)
    # A stale version changes nothing.
    with pytest.raises(UnitVersionConflict):
        flow.set_rent_terms(
            case["unit"],
            default_monthly_rent_usd_cents=1,
            required_service_ids=(),
            expected_version=before.version,
            actor_id=str(case["actor"]),
        )
    # A Service of another Property, or one that is not there, is refused.
    with pytest.raises(UnitResourceInvalid):
        flow.set_rent_terms(
            case["unit"],
            default_monthly_rent_usd_cents=45_000,
            required_service_ids=(uuid4(),),
            expected_version=updated.version,
            actor_id=str(case["actor"]),
        )
    cleared = flow.set_rent_terms(
        case["unit"],
        default_monthly_rent_usd_cents=None,
        required_service_ids=(),
        expected_version=updated.version,
        actor_id=str(case["actor"]),
    )
    assert (cleared.default_monthly_rent_usd_cents, cleared.required_service_ids) == (None, ())
    with psycopg.connect(migrated_database_url) as connection:
        changes = connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE entity_id=%s AND action='unit.rent_terms_changed'",
            (case["unit"],),
        ).fetchone()
    assert changes is not None and changes[0] == 2


def test_runtime_role_cannot_write_required_services_directly(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "INSERT INTO app.unit_required_services(unit_id,property_service_id,added_by) "
            "VALUES (%s,%s,%s)",
            (case["unit"], case["required"], case["actor"]),
        )


def test_a_lease_draft_must_hold_every_required_service(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    _set(case, None, (case["required"],))
    client = _client(_who(case))
    url = f"/api/v1/properties/{case['prop']}/leases"
    missing = client.post(url, json=_draft(case, 80_000, with_service=False), headers=headers())
    assert missing.status_code == 409, missing.text
    assert missing.json()["error"]["code"] == "LEASE_REQUIRED_SERVICE_MISSING"
    held = client.post(url, json=_draft(case, 80_000, with_service=True), headers=headers())
    assert held.status_code == 201, held.text


def test_a_rent_below_the_default_needs_a_manager(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    _set(case, 80_000, ())
    url = f"/api/v1/properties/{case['prop']}/leases"
    staff = _client(_who(case))
    lower = staff.post(url, json=_draft(case, 79_999, with_service=False), headers=headers())
    assert lower.status_code == 403, lower.text
    assert lower.json()["error"]["code"] == "RENT_BELOW_UNIT_DEFAULT"
    higher = staff.post(url, json=_draft(case, 90_000, with_service=False), headers=headers())
    assert higher.status_code == 201, higher.text
    manager = _client(_who(case, "rent.below_default"))
    agreed = manager.post(url, json=_draft(case, 70_000, with_service=False), headers=headers())
    assert agreed.status_code == 201, agreed.text


def test_default_owner_and_manager_bundles_hold_the_new_right(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(
            "SELECT bool_and(EXISTS (SELECT 1 FROM app.role_bundle_capabilities AS held "
            "WHERE held.role_bundle_id = bundle.role_bundle_id "
            "AND held.version = bundle.version AND held.capability_id = 'rent.below_default')) "
            "FROM app.default_role_bundles AS seeded JOIN app.role_bundles AS bundle "
            "ON bundle.role_bundle_id IN (seeded.owner_bundle_id, seeded.manager_bundle_id)"
        ).fetchone()
        staff = connection.execute(
            "SELECT count(*) FROM app.default_role_bundles AS seeded "
            "JOIN app.role_bundles AS bundle ON bundle.role_bundle_id = seeded.staff_bundle_id "
            "JOIN app.role_bundle_capabilities AS held "
            "ON held.role_bundle_id = bundle.role_bundle_id AND held.version = bundle.version "
            "WHERE held.capability_id = 'rent.below_default'"
        ).fetchone()
    assert rows is not None and rows[0] in (True, None)
    assert staff is not None and staff[0] == 0
