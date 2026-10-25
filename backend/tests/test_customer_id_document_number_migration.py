"""Real PostgreSQL coverage for the Customer ID number / Passport number.

DL-071 answer 11 with the owner's 2026-10-21 answer, SEC-006, BR-CUST-002, DB-CUST-001,
TCD-DB-001 (V1-059 part B, migration `20270206_194`).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Error

from property_rental.customer import (
    CustomerIdNumberInUse,
    CustomerService,
    PostgresCustomerRepository,
)
from property_rental.customer_api import PostgresCustomerResourceFlow
from test_customer_migration import actor_and_property, insert_customer, migrated_database_url

__all__ = ["migrated_database_url"]


def runtime_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def committed_actor(migrated_database_url: str) -> tuple[UUID, UUID]:
    with psycopg.connect(migrated_database_url) as admin:
        actor_id, property_id = actor_and_property(admin)
        admin.commit()
    return actor_id, property_id


def unique_number() -> str:
    return f"N {uuid4().hex[:6]}-{uuid4().hex[:6]}"


def test_runtime_create_stores_the_number_and_refuses_the_same_number_in_any_form(
    migrated_database_url: str,
) -> None:
    actor_id, _ = committed_actor(migrated_database_url)
    service = CustomerService(PostgresCustomerRepository(runtime_url(), actor_id))
    number = unique_number()
    created = service.create(uuid4(), legal_name="Dara Sok", id_document_number=number)
    assert created.id_document_number == number
    for same in (number.lower(), number.replace(" ", "").replace("-", ""), f" {number.upper()} "):
        with pytest.raises(CustomerIdNumberInUse) as refused:
            service.create(
                uuid4(), legal_name="Dara S.", id_document_number=same, confirmed_distinct=True
            )
        assert refused.value.existing is not None
        assert refused.value.existing.customer_id == created.customer_id
    with psycopg.connect(runtime_url()) as runtime:
        audit = runtime.execute(
            "SELECT resulting_state FROM app.audit_events WHERE customer_id = %s",
            (created.customer_id,),
        ).fetchone()
    assert audit is not None and isinstance(audit[0], dict)
    assert audit[0]["id_document_number_recorded"] is True
    assert number not in str(audit[0])


def test_the_unique_index_decides_two_creates_with_one_number_at_once(
    migrated_database_url: str,
) -> None:
    actor_id, _ = committed_actor(migrated_database_url)
    number = unique_number()
    barrier = Barrier(2)

    # The repository is a frozen dataclass with slots, so which ones already waited is kept
    # outside it (setting an attribute on it fails on Python 3.11).
    waited: set[int] = set()

    class RaceRepository(PostgresCustomerRepository):
        def find_by_id_document_number(self, id_document_number: str):  # type: ignore[no-untyped-def]
            # Both creates pass the friendly check before either saves; the later look-up of the
            # Customer that holds the number (after the refusal) does not wait.
            if id(self) not in waited:
                waited.add(id(self))
                barrier.wait(timeout=30)
            return super().find_by_id_document_number(id_document_number)

    def create(name: str) -> str:
        try:
            CustomerService(RaceRepository(runtime_url(), actor_id)).create(
                uuid4(), legal_name=name, id_document_number=number
            )
        except CustomerIdNumberInUse:
            return "refused"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(create, ("First Racer", "Second Racer")))
    assert outcomes == ["created", "refused"]


def test_a_legacy_customer_gets_a_number_by_update_and_it_is_never_cleared(
    migrated_database_url: str,
) -> None:
    actor_id, property_id = committed_actor(migrated_database_url)
    with psycopg.connect(migrated_database_url) as admin:
        legacy_id = insert_customer(admin, actor_id, legal_name="Legacy Customer")
        admin.commit()
    flow = PostgresCustomerResourceFlow(runtime_url())
    legacy = flow.get(legacy_id)
    assert legacy.customer.id_document_number is None
    number = unique_number()
    updated = flow.update(
        legacy_id,
        legal_name="Legacy Customer",
        phone_number=None,
        email_address=None,
        contact_address=None,
        memo=None,
        confirmed_distinct=False,
        expected_version=legacy.customer.version,
        actor_id=str(actor_id),
        idempotency_key=uuid4(),
        request_digest="d" * 64,
        id_document_number=number,
    )
    assert updated.customer.id_document_number == number
    assert flow.get(legacy_id).customer.id_document_number == number
    with psycopg.connect(runtime_url()) as runtime:
        with pytest.raises(Error) as cleared:
            runtime.execute(
                "SELECT * FROM app.update_customer(%s, %s, NULL, NULL, NULL, NULL, %s, %s, %s, '')",
                (legacy_id, "Legacy Customer", updated.customer.version, actor_id, uuid4()),
            )
        assert cleared.value.sqlstate == "22023"
        runtime.rollback()
        with pytest.raises(Error) as missing:
            runtime.execute(
                "SELECT * FROM app.create_customer(%s, 'No Number', NULL, NULL, NULL, NULL,"
                " %s, %s, NULL)",
                (uuid4(), actor_id, uuid4()),
            )
        assert missing.value.sqlstate == "22023"
    del property_id


def test_the_number_is_kept_in_the_command_replay(migrated_database_url: str) -> None:
    actor_id, property_id = committed_actor(migrated_database_url)
    flow = PostgresCustomerResourceFlow(runtime_url())
    number = unique_number()
    key = uuid4()
    customer_id = uuid4()
    arguments: dict[str, object] = {
        "customer_id": customer_id,
        "legal_name": "Replay Customer",
        "phone_number": None,
        "email_address": None,
        "contact_address": None,
        "memo": None,
        "confirmed_distinct": False,
        "actor_id": str(actor_id),
        "idempotency_key": key,
        "request_digest": "e" * 64,
        "id_document_number": number,
    }
    created = flow.create(property_id, **arguments)  # type: ignore[arg-type]
    replayed = flow.create(property_id, **arguments)  # type: ignore[arg-type]
    assert replayed == created
    assert replayed.customer.id_document_number == number


def test_the_runtime_role_cannot_create_a_customer_without_the_number(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as admin:
        rows = admin.execute(
            "SELECT p.oid::regprocedure::text, "
            "has_function_privilege('prm_runtime', p.oid, 'EXECUTE') "
            "FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'app' "
            "AND p.proname IN ('create_customer', 'execute_customer_create')"
        ).fetchall()
    allowed = {str(name): bool(granted) for name, granted in rows}
    assert allowed == {
        "app.create_customer(uuid,text,text,text,text,text,uuid,uuid)": False,
        "app.create_customer(uuid,text,text,text,text,text,uuid,uuid,text)": True,
        "app.execute_customer_create(uuid,uuid,text,uuid,text,text,text,text,text,uuid)": False,
        "app.execute_customer_create(uuid,uuid,text,uuid,text,text,text,text,text,uuid,text)": True,
        # V1-058 R2c (20270215_203) adds the details overloads; the number stays required.
        "app.create_customer(uuid,text,text,text,text,text,uuid,uuid,text,date,text,text)": True,
        "app.execute_customer_create("
        "uuid,uuid,text,uuid,text,text,text,text,text,uuid,text,date,text,text)": True,
    }
