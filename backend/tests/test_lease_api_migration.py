"""Real HTTP-to-PostgreSQL coverage for V1-036 Lease and move-in resources."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient

from payment_test_support import seed_deposit_payment
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_api import PostgresLeaseResourceFlow
from test_lease_lifecycle_migration import database_now
from test_lease_migration import setup_sources
from test_move_in_migration import setup_move_in


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    alembic_command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def authenticated(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    capabilities = {
        "leases.read",
        "leases.draft",
        "lease_signers.manage",
        "leases.sign",
        "leases.terminate",
        "reservations.complete",
    }
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def api(database_url: str, actor: AuthenticatedActor) -> TestClient:
    value = TestClient(
        create_app(
            actor_resolver=lambda _: actor,
            lease_resource_flow=PostgresLeaseResourceFlow(database_url),
        )
    )
    value.cookies.set("__Host-prm_csrf", "csrf")
    return value


def headers(version: int | None = None) -> dict[str, str]:
    result = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    if version is not None:
        result["If-Match"] = f'"{version}"'
    return result


def test_http_create_update_sign_and_replay_use_runtime_role(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, property_id, unit_id, primary_tenant_id, joint_signer_id = setup_sources(
            connection
        )
        late_signer_customer_id = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Late Joint Signer',%s,%s)",
            (late_signer_customer_id, actor_id, actor_id),
        )
        service_id = uuid4()
        approval_id = uuid4()
        connection.execute(
            "INSERT INTO app.property_services("
            "id,property_id,service_code,display_name,configured_by,created_by,updated_by) "
            "VALUES (%s,%s,%s,'Parking Service',%s,%s,%s)",
            (
                service_id,
                property_id,
                f"parking-{service_id.hex[:8]}",
                actor_id,
                actor_id,
                actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.property_service_approval_periods("
            "id,property_service_id,effective_from,effective_through,approval_reference,"
            "approved_at,approved_by,reason) "
            "VALUES (%s,%s,'2027-01-01',NULL,'owner-approval',clock_timestamp(),%s,"
            "'Approved fixed term')",
            (approval_id, service_id, actor_id),
        )
        connection.commit()

    client = api(runtime_database_url(), authenticated(actor_id, property_id))
    lease_id = uuid4()
    create_key = str(uuid4())
    create_payload = {
        "lease_id": str(lease_id),
        "unit_id": str(unit_id),
        "primary_tenant_id": str(primary_tenant_id),
        "primary_signer_id": str(uuid4()),
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
        "monthly_rent_usd_cents": 80000,
        "predecessor_lease_id": None,
        "additional_signers": [{"signer_id": str(uuid4()), "customer_id": str(joint_signer_id)}],
        "planned_occupant_customer_ids": [str(primary_tenant_id), str(joint_signer_id)],
        "service_terms": [
            {
                "term_id": str(uuid4()),
                "property_service_id": str(service_id),
                "applicable_from": "2027-01-01",
                "applicable_through": "2027-12-31",
                "service_approval_period_id": str(approval_id),
                "terms_reference": "Owner-approved fixed Parking Service",
            }
        ],
        "pet_term": {
            "approval_id": str(uuid4()),
            "approved_date": "2027-01-01",
            "deposit_required_by_signed_terms": False,
            "pet_description": "One approved indoor cat",
        },
        "security_deposit_id": None,
        "event_id": str(uuid4()),
        "reason": "Approved Lease source terms",
    }
    create_headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": create_key,
    }
    created = client.post(
        f"/api/v1/properties/{property_id}/leases",
        json=create_payload,
        headers=create_headers,
    )
    replayed = client.post(
        f"/api/v1/properties/{property_id}/leases",
        json=create_payload,
        headers=create_headers,
    )
    updated = client.patch(
        f"/api/v1/leases/{lease_id}",
        headers=headers(1),
        json={
            "event_id": str(uuid4()),
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
            "monthly_rent_usd_cents": 85000,
            "reason": "Authorized Rent correction",
        },
    )
    partial = client.patch(
        f"/api/v1/leases/{lease_id}",
        headers=headers(2),
        json={
            "event_id": str(uuid4()),
            "monthly_rent_usd_cents": 90000,
            "reason": "Rent-only correction preserves contractual dates",
        },
    )
    signer_id = uuid4()
    added = client.post(
        f"/api/v1/leases/{lease_id}/signers",
        headers=headers(3),
        json={
            "signer_id": str(signer_id),
            "customer_id": str(late_signer_customer_id),
            "event_id": str(uuid4()),
            "reason": "Joint responsibility recorded",
        },
    )
    signers = added.json()["data"]["signers"]
    version = 4
    for signer in signers:
        signed = client.patch(
            f"/api/v1/lease-signers/{signer['signer_id']}?lease_id={lease_id}",
            headers=headers(version),
            json={
                "event_id": str(uuid4()),
                "reason": "Signer completed attributed signature",
            },
        )
        assert signed.status_code == 200, signed.text
        version += 1
    completed = client.post(
        f"/api/v1/leases/{lease_id}/sign",
        headers=headers(version),
        json={
            "event_id": str(uuid4()),
            "reason": "All required Signers and source terms validated",
        },
    )

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["data"]["lease_id"] == str(lease_id)
    assert replayed.headers["location"] == f"/api/v1/leases/{lease_id}"
    assert replayed.json()["data"]["planned_occupant_customer_ids"] == [
        str(primary_tenant_id),
        str(joint_signer_id),
    ]
    assert replayed.json()["data"]["service_terms"][0]["property_service_id"] == str(service_id)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["monthly_rent_usd_cents"] == 85000
    assert partial.status_code == 200, partial.text
    assert partial.json()["data"]["start_date"] == "2027-01-01"
    assert partial.json()["data"]["end_date"] == "2027-12-31"
    assert partial.json()["data"]["monthly_rent_usd_cents"] == 90000
    assert added.status_code == 201, added.text
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "SIGNED"
    listed = client.get(f"/api/v1/properties/{property_id}/leases?status=SIGNED&limit=1")
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.json()["data"][0]["lease_id"] == str(lease_id)
    approaching = client.get(
        f"/api/v1/properties/{property_id}/leases"
        "?period=approaching_end&as_of=2027-12-01&approaching_days=31&limit=1"
    )
    assert approaching.status_code == 200, approaching.text
    assert approaching.json()["data"][0]["lease_id"] == str(lease_id)

    notice_id = uuid4()
    warning_id = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.termination_notices("
            "id,lease_id,notice_date,intended_termination_date,notice_text,"
            "governing_lease_provision,occurred_at,actor_id) "
            "VALUES (%s,%s,'2027-11-01','2027-12-31','Authorized notice',"
            "'Lease clause 10',clock_timestamp(),%s)",
            (notice_id, lease_id, actor_id),
        )
        connection.execute(
            "INSERT INTO app.lease_violation_warnings("
            "id,lease_id,warning_sequence,violation_date,warning_date,"
            "violation_description,lease_provision,communication_record,occurred_at,actor_id) "
            "VALUES (%s,%s,1,'2027-08-01','2027-08-02','Documented violation',"
            "'Lease clause 12','Delivered letter',clock_timestamp(),%s)",
            (warning_id, lease_id, actor_id),
        )
        connection.commit()
    detail = client.get(f"/api/v1/leases/{lease_id}")
    assert detail.status_code == 200, detail.text
    timeline = {item["event_kind"]: item for item in detail.json()["data"]["timeline"]}
    assert timeline["lease.termination_notice"]["source_reference"] == str(notice_id)
    assert timeline["lease.violation_warning"]["source_reference"] == str(warning_id)
    for event_kind in ("lease.termination_notice", "lease.violation_warning"):
        source_href = timeline[event_kind]["source_href"]
        assert source_href.endswith(str(timeline[event_kind]["event_id"]))
        assert client.get(source_href.partition("#")[0]).status_code == 200

    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT action FROM app.lease_commands WHERE lease_id=%s ORDER BY occurred_at",
            (lease_id,),
        ).fetchall() == [
            ("lease.draft",),
            ("lease.draft.update",),
            ("lease.draft.update",),
            ("lease.signer.add",),
            ("lease.signer.sign",),
            ("lease.signer.sign",),
            ("lease.signer.sign",),
            ("lease.sign",),
        ]
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20270207_195",
        )
        assert connection.execute(
            "SELECT has_function_privilege('prm_runtime',"
            "'app.update_lease_draft(uuid,uuid,text,uuid,uuid,integer,date,date,bigint,text,text,uuid)',"
            "'EXECUTE')"
        ).fetchone() == (True,)


def test_http_signing_time_is_the_database_time(migrated_database_url: str) -> None:
    """Q-2026-10-14-110: a signing time is the database's own time, never a device clock."""
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, property_id, unit_id, primary_tenant_id, joint_signer_id = setup_sources(
            connection
        )
        connection.commit()

    client = api(runtime_database_url(), authenticated(actor_id, property_id))
    lease_id = uuid4()
    created = client.post(
        f"/api/v1/properties/{property_id}/leases",
        headers=headers(),
        json={
            "lease_id": str(lease_id),
            "unit_id": str(unit_id),
            "primary_tenant_id": str(primary_tenant_id),
            "primary_signer_id": str(uuid4()),
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
            "monthly_rent_usd_cents": 80000,
            "predecessor_lease_id": None,
            "additional_signers": [
                {"signer_id": str(uuid4()), "customer_id": str(joint_signer_id)}
            ],
            "planned_occupant_customer_ids": [str(primary_tenant_id)],
            "service_terms": [],
            "pet_term": None,
            "security_deposit_id": None,
            "event_id": str(uuid4()),
            "reason": "Approved Lease source terms",
        },
    )
    assert created.status_code == 201, created.text
    signers = created.json()["data"]["signers"]
    assert len(signers) == 2
    paths = [
        f"/api/v1/lease-signers/{signer['signer_id']}?lease_id={lease_id}" for signer in signers
    ]

    before = database_now()
    backdated = client.patch(
        paths[0],
        headers=headers(1),
        json={"event_id": str(uuid4()), "signed_at": "2020-01-01T00:00:00Z", "reason": "Backdated"},
    )
    assert backdated.status_code == 422
    assert backdated.json()["error"]["fields"] == ["body.signed_at"]
    first_headers = headers(1)
    first_body = {"event_id": str(uuid4()), "reason": "Signer completed attributed signature"}
    first = client.patch(paths[0], headers=first_headers, json=first_body)
    retried = client.patch(paths[0], headers=first_headers, json=first_body)
    second = client.patch(
        paths[1],
        headers=headers(2),
        json={"event_id": str(uuid4()), "reason": "Signer completed attributed signature"},
    )
    sign_headers = headers(3)
    sign_body = {"event_id": str(uuid4()), "reason": "All required Signers and terms validated"}
    completed = client.post(f"/api/v1/leases/{lease_id}/sign", headers=sign_headers, json=sign_body)
    # The Lease is now at version 4, so only a replay can answer If-Match "3" with 200.
    sign_retried = client.post(
        f"/api/v1/leases/{lease_id}/sign", headers=sign_headers, json=sign_body
    )
    after = database_now()

    assert first.status_code == 200, first.text
    assert retried.status_code == 200, retried.text
    assert second.status_code == 200, second.text
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "SIGNED"
    assert sign_retried.status_code == 200, sign_retried.text
    assert completed.json()["data"]["signed_at"] is not None
    assert sign_retried.json()["data"]["signed_at"] == completed.json()["data"]["signed_at"]
    first_signed = {
        item["signer_id"]: item["signed_at"] for item in first.json()["data"]["signers"]
    }
    retried_signed = {
        item["signer_id"]: item["signed_at"] for item in retried.json()["data"]["signers"]
    }
    assert first_signed[signers[0]["signer_id"]] is not None
    assert retried_signed == first_signed
    with psycopg.connect(migrated_database_url) as connection:
        signer_times = [
            row[0]
            for row in connection.execute(
                "SELECT signed_at FROM app.lease_signers WHERE lease_id=%s ORDER BY signed_at",
                (lease_id,),
            ).fetchall()
        ]
        signature_command_times = [
            row[0]
            for row in connection.execute(
                "SELECT occurred_at FROM app.lease_commands "
                "WHERE lease_id=%s AND action='lease.signer.sign' ORDER BY occurred_at",
                (lease_id,),
            ).fetchall()
        ]
        signing = connection.execute(
            "SELECT lease.signed_at, outcome.occurred_at FROM app.leases AS lease "
            "JOIN app.lease_signing_outcomes AS outcome ON outcome.lease_id=lease.id "
            "WHERE lease.id=%s",
            (lease_id,),
        ).fetchall()
        sign_command_count = connection.execute(
            "SELECT count(*) FROM app.lease_commands WHERE lease_id=%s AND action='lease.sign'",
            (lease_id,),
        ).fetchone()
    # A signature command row and the signing outcome row are stamped with the
    # statement time by the database itself (the lease.sign command row stores the
    # signing time it was given, so it proves nothing here); the retries wrote no row.
    assert len(signer_times) == 2
    assert signer_times == signature_command_times
    assert len(signing) == 1
    assert signing[0][0] == signing[0][1]
    assert sign_command_count == (1,)
    assert all(before <= value <= after for value in [*signer_times, signing[0][0]])


def test_http_draft_requires_security_deposit_from_the_same_reservation_unit(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, property_id, unit_id, customer_id, _ = setup_sources(connection)
        other_unit_id = uuid4()
        connection.execute(
            "INSERT INTO app.units("
            "id,property_id,unit_number,floor,unit_type,status,created_by,updated_by) "
            "VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
            (other_unit_id, property_id, f"LEASE-{other_unit_id.hex[:12]}", actor_id, actor_id),
        )
        deposit_by_unit: dict[UUID, UUID] = {}
        for source_unit_id in (unit_id, other_unit_id):
            reservation_id = uuid4()
            deposit_id = uuid4()
            connection.execute(
                "INSERT INTO app.reservations("
                "id,unit_id,customer_id,reservation_date,agreed_monthly_rent_usd_cents,"
                "original_expiration_date,effective_expiration_date,status,created_by,updated_by) "
                "VALUES (%s,%s,%s,'2026-12-20',80000,'2027-01-05','2027-01-05',"
                "'ACTIVE',%s,%s)",
                (reservation_id, source_unit_id, customer_id, actor_id, actor_id),
            )
            connection.execute(
                "INSERT INTO app.reservation_deposit_acceptances("
                "id,reservation_id,suggested_rate_basis_points,suggested_amount_usd_cents,"
                "accepted_required_amount_usd_cents,acceptance_kind,accepted_at,accepted_by,"
                "reason,authorization_reference,calculation_trace) "
                "VALUES (%s,%s,2000,16000,80000,'AUTHORIZED_VARIANCE',"
                "clock_timestamp(),%s,'Approved full Security Deposit','reservations.manage',"
                "%s::jsonb)",
                (
                    uuid4(),
                    reservation_id,
                    actor_id,
                    '{"agreed_monthly_rent_usd_cents":80000,'
                    '"suggested_rate_basis_points":2000,'
                    '"suggested_amount_usd_cents":16000}',
                ),
            )
            connection.execute(
                "INSERT INTO app.deposits("
                "id,deposit_type,customer_id,reservation_id,required_usd_cents,"
                "required_effective_date,created_by,updated_by) "
                "VALUES (%s,'SECURITY',%s,%s,80000,'2026-12-20',%s,%s)",
                (deposit_id, customer_id, reservation_id, actor_id, actor_id),
            )
            connection.execute(
                "INSERT INTO app.deposit_receipts("
                "id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id) "
                "VALUES (%s,%s,%s,80000,clock_timestamp(),%s)",
                (
                    uuid4(),
                    deposit_id,
                    seed_deposit_payment(
                        connection, deposit_id=deposit_id, actor_id=actor_id, amount=80_000
                    ),
                    actor_id,
                ),
            )
            connection.execute(
                "UPDATE app.units SET status='RESERVED',version=version+1,"
                "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                (actor_id, source_unit_id),
            )
            deposit_by_unit[source_unit_id] = deposit_id
        connection.commit()

    client = api(runtime_database_url(), authenticated(actor_id, property_id))

    def payload(lease_id: UUID, deposit_id: UUID) -> dict[str, object]:
        return {
            "lease_id": str(lease_id),
            "unit_id": str(unit_id),
            "primary_tenant_id": str(customer_id),
            "primary_signer_id": str(uuid4()),
            "start_date": "2027-01-10",
            "end_date": "2028-01-31",
            "monthly_rent_usd_cents": 80000,
            "predecessor_lease_id": None,
            "additional_signers": [],
            "planned_occupant_customer_ids": [str(customer_id)],
            "service_terms": [],
            "pet_term": None,
            "security_deposit_id": str(deposit_id),
            "event_id": str(uuid4()),
            "reason": "Approved Reservation Security Deposit continuity",
        }

    rejected_lease_id = uuid4()
    rejected = client.post(
        f"/api/v1/properties/{property_id}/leases",
        json=payload(rejected_lease_id, deposit_by_unit[other_unit_id]),
        headers=headers(),
    )
    assert rejected.status_code == 404
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.leases WHERE id=%s", (rejected_lease_id,)
        ).fetchone() == (0,)

    lease_id = uuid4()
    created = client.post(
        f"/api/v1/properties/{property_id}/leases",
        json=payload(lease_id, deposit_by_unit[unit_id]),
        headers=headers(),
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["security_deposit_id"] == str(deposit_by_unit[unit_id])
    with psycopg.connect(migrated_database_url) as connection:
        for index in range(19):
            signer_customer_id = uuid4()
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,%s,%s,%s)",
                (signer_customer_id, f"Bounded Signer {index}", actor_id, actor_id),
            )
            connection.execute(
                "INSERT INTO app.lease_signers(id,lease_id,customer_id,added_by) "
                "VALUES (%s,%s,%s,%s)",
                (uuid4(), lease_id, signer_customer_id, actor_id),
            )
        connection.commit()
        overflow_customer_id = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Overflow Signer',%s,%s)",
            (overflow_customer_id, actor_id, actor_id),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO app.lease_signers(id,lease_id,customer_id,added_by) "
                    "VALUES (%s,%s,%s,%s)",
                    (uuid4(), lease_id, overflow_customer_id, actor_id),
                )


def test_http_complete_move_in_preserves_atomic_postgresql_result(
    migrated_database_url: str,
) -> None:
    _, move_in_actor, command, deposit_id = setup_move_in(migrated_database_url)
    property_id = next(iter(next(iter(move_in_actor.capability_grants)).property_ids))
    client = api(runtime_database_url(), move_in_actor)
    response = client.post(
        f"/api/v1/reservations/{command.reservation_id}/complete-move-in",
        headers=headers(command.expected_reservation_version),
        json={
            "event_id": str(command.event_id),
            "lease_id": str(command.lease_id),
            "expected_lease_version": command.expected_lease_version,
            "expected_unit_version": command.expected_unit_version,
            "actual_move_in_date": command.actual_move_in_date.isoformat(),
            "occupants": [
                {
                    "occupancy_id": str(value.occupancy_id),
                    "customer_id": str(value.customer_id),
                }
                for value in command.occupants
            ],
            "reason": command.reason,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["property_id"] == property_id
    assert response.json()["data"]["deposit_id"] == str(deposit_id)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM app.reservations WHERE id=%s", (command.reservation_id,)
        ).fetchone() == ("COMPLETED",)
        assert connection.execute(
            "SELECT count(*) FROM app.occupancies WHERE lease_id=%s", (command.lease_id,)
        ).fetchone() == (len(command.occupants),)
        assert connection.execute(
            "SELECT count(*) FROM app.deposits WHERE id=%s", (deposit_id,)
        ).fetchone() == (1,)
