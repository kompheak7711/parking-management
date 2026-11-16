"""UI v81 (owner 08/11/2026 08:14, migration 20270712_363): the Lease number and History names.

A Lease drafted through the API gets the Property's next running number with its Unit number in
front (U101L0026); the number is written once and never changes; the counter only moves up by
one; the Lease read carries the number; and the Lease History names the person of each step.
Rows on the shared test database belong to this module's own Units and Leases.
"""

from __future__ import annotations

import re
from uuid import UUID, uuid4

import psycopg
import pytest

from test_lease_api_migration import api, authenticated, runtime_database_url
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_migration import setup_sources

REVISION = "20270712_363"


def draft(client_actor: UUID, property_id: UUID, unit_id: UUID, tenant: UUID) -> UUID:
    client = api(runtime_database_url(), authenticated(client_actor, property_id))
    lease_id = uuid4()
    created = client.post(
        f"/api/v1/properties/{property_id}/leases",
        json={
            "lease_id": str(lease_id),
            "unit_id": str(unit_id),
            "primary_tenant_id": str(tenant),
            "primary_signer_id": str(uuid4()),
            "start_date": "2027-03-01",
            "end_date": "2028-02-29",
            "monthly_rent_usd_cents": 30000,
            "predecessor_lease_id": None,
            "additional_signers": [],
            "planned_occupant_customer_ids": [str(tenant)],
            "service_terms": [],
            "pet_term": None,
            "security_deposit_id": None,
            "event_id": str(uuid4()),
            "reason": "Lease number check",
        },
        headers={
            "Origin": "https://localhost",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert created.status_code == 201, created.text
    return lease_id


def test_a_drafted_lease_gets_the_next_number_and_the_read_names_the_person(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
        connection.commit()
        before = connection.execute(
            "SELECT last_number FROM app.lease_number_counters WHERE property_id=%s",
            (property_id,),
        ).fetchone()
        unit = connection.execute(
            "SELECT unit_number FROM app.units WHERE id=%s", (unit_id,)
        ).fetchone()
        account = connection.execute(
            "SELECT display_name FROM app.user_accounts WHERE actor_id=%s", (actor_id,)
        ).fetchone()
    assert unit is not None and account is not None
    expected = (0 if before is None else int(before[0])) + 1

    lease_id = draft(actor_id, property_id, unit_id, tenant_id)

    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT running_number,lease_number,property_id FROM app.lease_numbers "
            "WHERE lease_id=%s",
            (lease_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == expected and row[2] == property_id
    assert row[1] == f"{unit[0]}L{expected:04d}"
    assert re.fullmatch(r".+L[0-9]{4,}", str(row[1]))

    client = api(runtime_database_url(), authenticated(actor_id, property_id))
    read = client.get(f"/api/v1/leases/{lease_id}")
    assert read.status_code == 200, read.text
    body = read.json()["data"]
    assert body["lease_number"] == row[1]
    drafted = [event for event in body["timeline"] if event["event_kind"] == "lease.draft"]
    assert drafted and drafted[0]["actor_name"] == account[0]
    assert drafted[0]["subject_name"] is None


def test_a_lease_number_is_written_once_and_the_counter_only_moves_up_by_one(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, property_id, unit_id, tenant_id, _ = setup_sources(connection)
        connection.commit()
    lease_id = draft(actor_id, property_id, unit_id, tenant_id)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            connection.execute(
                "UPDATE app.lease_numbers SET lease_number='X1L0001' WHERE lease_id=%s",
                (lease_id,),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            connection.execute("DELETE FROM app.lease_numbers WHERE lease_id=%s", (lease_id,))
        connection.rollback()
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            connection.execute(
                "UPDATE app.lease_number_counters SET last_number=last_number+5 "
                "WHERE property_id=%s",
                (property_id,),
            )
        connection.rollback()


def test_the_runtime_role_reads_the_numbers_but_cannot_write_them(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute("SELECT count(*) FROM app.lease_numbers").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO app.lease_numbers(lease_id,property_id,running_number,lease_number) "
                "VALUES (%s,%s,1,'U1L0001')",
                (uuid4(), uuid4()),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM app.lease_number_counters").fetchone()
