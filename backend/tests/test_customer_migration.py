"""PostgreSQL tests for canonical Customer identity and audit history."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.sql import SQL

from property_rental.customer import (
    CustomerReuseRequired,
    CustomerService,
    PostgresCustomerRepository,
)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def actor_and_property(connection: Connection[tuple[object, ...]]) -> tuple[UUID, UUID]:
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s, %s, 'Customer Tester', 'Customer Tester', 'active', 'optional', 'test')
        """,
        (actor_id, f"customer-{actor_id}"),
    )
    existing = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing is not None:
        return actor_id, UUID(str(existing[0]))
    property_id = uuid4()
    connection.execute(
        "INSERT INTO app.properties (id, name, created_by, updated_by) "
        "VALUES (%s, 'Customer Test Property', %s, %s)",
        (property_id, actor_id, actor_id),
    )
    return actor_id, property_id


def insert_customer(
    connection: Connection[tuple[object, ...]],
    actor_id: UUID,
    *,
    customer_id: UUID | None = None,
    legal_name: str = "Dara Sok",
    phone_number: str | None = None,
    email_address: str | None = None,
) -> UUID:
    stored_id = uuid4() if customer_id is None else customer_id
    connection.execute(
        """
        INSERT INTO app.customers (
            id, legal_name, phone_number, email_address, created_by, updated_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (stored_id, legal_name, phone_number, email_address, actor_id, actor_id),
    )
    return stored_id


def test_migration_persists_canonical_customer_without_fixed_type(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = insert_customer(connection, actor_id)

    columns = {
        row[0]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'app' AND table_name = 'customers'"
        ).fetchall()
    }
    stored = connection.execute(
        "SELECT id, legal_name, phone_number, email_address, version "
        "FROM app.customers WHERE id = %s",
        (customer_id,),
    ).fetchone()

    assert stored == (customer_id, "Dara Sok", None, None, 1)
    assert "customer_type" not in columns
    assert "category" not in columns


@pytest.mark.parametrize("legal_name", ["", "   ", " Dara Sok "])
def test_migration_rejects_invalid_customer_name(
    connection: Connection[tuple[object, ...]], legal_name: str
) -> None:
    actor_id, _ = actor_and_property(connection)

    with pytest.raises(Error) as raised:
        insert_customer(connection, actor_id, legal_name=legal_name)

    assert raised.value.sqlstate == "23514"


@pytest.mark.parametrize(
    "statement",
    [
        SQL("UPDATE app.customers SET id = %s, version = version + 1"),
        SQL(
            "UPDATE app.customers "
            "SET created_at = created_at + interval '1 second', version = version + 1"
        ),
        SQL("DELETE FROM app.customers"),
        SQL("TRUNCATE app.customers"),
    ],
)
def test_migration_rejects_customer_identity_or_history_loss(
    connection: Connection[tuple[object, ...]], statement: SQL
) -> None:
    actor_id, _ = actor_and_property(connection)
    insert_customer(connection, actor_id)

    with pytest.raises(Error) as raised:
        parameters = (uuid4(),) if "%s" in statement.as_string() else ()
        connection.execute(statement, parameters)

    assert raised.value.sqlstate == "55000"


def test_protected_update_preserves_previous_and_resulting_contact_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = uuid4()
    created_event = uuid4()
    updated_event = uuid4()
    created = connection.execute(
        "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Dara Sok", "012345678", None, None, None, actor_id, created_event),
    ).fetchone()
    updated = connection.execute(
        "SELECT * FROM app.update_customer(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            customer_id,
            "Dara Sok",
            "098765432",
            "dara@example.com",
            None,
            None,
            1,
            actor_id,
            updated_event,
        ),
    ).fetchone()
    audit = connection.execute(
        "SELECT action, previous_state, resulting_state FROM app.audit_events "
        "WHERE customer_id = %s ORDER BY occurred_at, id",
        (customer_id,),
    ).fetchall()

    assert created is not None and created[-1] == 1
    assert updated is not None and updated[-1] == 2
    assert [row[0] for row in audit] == ["customer.created", "customer.updated"]
    previous = cast(dict[str, object], audit[1][1])
    resulting = cast(dict[str, object], audit[1][2])
    assert previous["phone_number"] == "012345678"
    assert resulting["phone_number"] == "098765432"
    assert previous["customer_id"] == str(customer_id)


def test_version_conflict_changes_neither_customer_nor_audit(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    customer_id = uuid4()
    connection.execute(
        "SELECT * FROM app.create_customer(%s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Dara Sok", None, None, None, None, actor_id, uuid4()),
    )

    rejected = connection.execute(
        "SELECT * FROM app.update_customer(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (customer_id, "Changed", None, None, None, None, 9, actor_id, uuid4()),
    ).fetchone()
    stored = connection.execute(
        "SELECT legal_name, version FROM app.customers WHERE id = %s", (customer_id,)
    ).fetchone()
    count = connection.execute(
        "SELECT count(*) FROM app.audit_events WHERE customer_id = %s", (customer_id,)
    ).fetchone()

    assert rejected is None
    assert stored == ("Dara Sok", 1)
    assert count == (1,)


def test_runtime_repository_requires_reuse_decision_and_preserves_update_history(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Customer Runtime', 'Customer Runtime', 'active', 'optional', 'test')
            """,
            (actor_id, f"customer-runtime-{actor_id}"),
        )
        if admin.execute("SELECT id FROM app.properties").fetchone() is None:
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Customer Runtime Property', %s, %s)",
                (uuid4(), actor_id, actor_id),
            )

    repository = PostgresCustomerRepository(runtime_url, actor_id)
    service = CustomerService(repository)
    email = f"{uuid4()}@example.com"
    created = service.create(uuid4(), legal_name="Dara Sok", email_address=email)
    with pytest.raises(CustomerReuseRequired):
        service.create(uuid4(), legal_name="Dara S.", email_address=email.upper())
    updated = service.update(
        created,
        legal_name="Dara Sok",
        phone_number="012345678",
        email_address=email,
        contact_address="Phnom Penh",
        memo=None,
    )

    assert updated.customer_id == created.customer_id
    assert updated.version == 2
    with psycopg.connect(runtime_url) as runtime:
        with pytest.raises(Error) as raised:
            runtime.execute("DELETE FROM app.customers WHERE id = %s", (created.customer_id,))
        assert raised.value.sqlstate == "42501"
        runtime.rollback()
        actions = runtime.execute(
            "SELECT action FROM app.audit_events WHERE customer_id = %s ORDER BY occurred_at, id",
            (created.customer_id,),
        ).fetchall()
    assert [row[0] for row in actions] == ["customer.created", "customer.updated"]


def test_migration_is_forward_only(migrated_database_url: str) -> None:
    del migrated_database_url
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "20260824_14")
