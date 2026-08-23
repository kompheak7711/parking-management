"""PostgreSQL constraint tests for the single Property configuration migration."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.sql import SQL
from psycopg.types.json import Jsonb


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Apply forward migrations to the disposable PostgreSQL test database."""
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")

    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    """Provide an isolated transaction against migrated PostgreSQL."""
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


@pytest.fixture
def runtime_connection(
    migrated_database_url: str,
) -> Iterator[Connection[tuple[object, ...]]]:
    del migrated_database_url
    database_url = os.environ.get("APP_DATABASE_URL")
    if database_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    with psycopg.connect(database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def insert_configuration(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    *,
    timezone_name: str = "Asia/Phnom_Penh",
    singleton_key: bool = True,
) -> None:
    """Insert one Property configuration for a constraint test."""
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id,
            normalized_username,
            display_name,
            audit_name,
            lifecycle_state,
            mfa_policy_class,
            provenance
        )
        VALUES (%s, %s, 'Property Tester', 'Property Tester', 'active', 'optional', 'test')
        """,
        (actor_id, f"property-{actor_id}"),
    )
    connection.execute(
        """
        INSERT INTO app.property_configuration (
            singleton_key,
            property_id,
            name,
            timezone_name,
            created_by,
            updated_by
        )
        VALUES (%s, %s, 'Riverside', %s, %s, %s)
        """,
        (singleton_key, property_id, timezone_name, actor_id, actor_id),
    )


def test_migration_persists_property_identity_and_timezone(
    connection: Connection[tuple[object, ...]],
) -> None:
    property_id = uuid4()

    insert_configuration(connection, property_id)
    stored = connection.execute(
        """
        SELECT property_id, name, address_text, timezone_name, version
        FROM app.property_configuration
        """
    ).fetchone()

    assert stored == (property_id, "Riverside", None, "Asia/Phnom_Penh", 1)


def test_migration_rejects_a_second_property(
    connection: Connection[tuple[object, ...]],
) -> None:
    insert_configuration(connection, uuid4())

    with pytest.raises(Error) as raised:
        insert_configuration(connection, uuid4())

    assert raised.value.sqlstate == "23505"


def test_migration_rejects_non_authoritative_timezone(
    connection: Connection[tuple[object, ...]],
) -> None:
    with pytest.raises(Error) as raised:
        insert_configuration(connection, uuid4(), timezone_name="UTC")

    assert raised.value.sqlstate == "23514"


def test_migration_rejects_false_singleton_key(
    connection: Connection[tuple[object, ...]],
) -> None:
    with pytest.raises(Error) as raised:
        insert_configuration(connection, uuid4(), singleton_key=False)

    assert raised.value.sqlstate == "23514"


def test_migration_rejects_nil_property_identity(
    connection: Connection[tuple[object, ...]],
) -> None:
    with pytest.raises(Error) as raised:
        insert_configuration(connection, UUID(int=0))

    assert raised.value.sqlstate == "23514"


@pytest.mark.parametrize(
    "statement",
    [
        SQL("UPDATE app.property_configuration SET property_id = %s"),
        SQL(
            "UPDATE app.property_configuration "
            "SET created_at = created_at + interval '1 second', version = version + 1"
        ),
        SQL("DELETE FROM app.property_configuration WHERE singleton_key"),
        SQL("TRUNCATE app.property_configuration"),
    ],
)
def test_migration_rejects_mutation_of_property_configuration(
    connection: Connection[tuple[object, ...]],
    statement: SQL,
) -> None:
    insert_configuration(connection, uuid4())

    with pytest.raises(Error) as raised:
        parameters = (uuid4(),) if statement.as_string().find("%s") >= 0 else ()
        connection.execute(statement, parameters)

    assert raised.value.sqlstate == "55000"


def test_migration_allows_versioned_configuration_update(
    connection: Connection[tuple[object, ...]],
) -> None:
    property_id = uuid4()
    insert_configuration(connection, property_id)

    updated = connection.execute(
        """
        UPDATE app.property_configuration
        SET name = %s,
            version = version + 1
        WHERE property_id = %s
          AND version = %s
        RETURNING name, version
        """,
        ("Riverside Apartments", property_id, 1),
    ).fetchone()

    assert updated == ("Riverside Apartments", 2)


def test_runtime_initializes_property_only_through_protected_defaults(
    migrated_database_url: str,
    runtime_connection: Connection[tuple[object, ...]],
) -> None:
    property_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id,
                normalized_username,
                display_name,
                audit_name,
                lifecycle_state,
                mfa_policy_class,
                provenance
            )
            VALUES (%s, %s, 'Setup Actor', 'Setup Actor', 'active', 'optional', 'test')
            """,
            (actor_id, f"setup-{actor_id}"),
        )

    with pytest.raises(Error) as raised:
        runtime_connection.execute(
            """
            INSERT INTO app.property_configuration (
                property_id,
                name,
                timezone_name,
                version,
                created_at,
                created_by,
                updated_by
            )
            VALUES (
                %s,
                'Forged',
                %s,
                %s,
                CURRENT_TIMESTAMP - interval '1 year',
                %s,
                %s
            )
            """,
            (property_id, "Asia/Phnom_Penh", 99, actor_id, actor_id),
        )
    assert raised.value.sqlstate == "42501"
    runtime_connection.rollback()

    initialized = runtime_connection.execute(
        """
        SELECT property_id, name, address_text, timezone_name, version
        FROM app.initialize_property(%s, %s, %s, %s)
        """,
        (property_id, "Riverside", "Phnom Penh", actor_id),
    ).fetchone()
    stored = runtime_connection.execute(
        """
        SELECT
            property_id,
            name,
            address_text,
            timezone_name,
            version,
            created_at <= CURRENT_TIMESTAMP
        FROM app.property_configuration
        """
    ).fetchone()
    privileges = runtime_connection.execute(
        """
        SELECT
            has_table_privilege(current_user, 'app.property_configuration', 'INSERT'),
            has_table_privilege(current_user, 'app.property_configuration', 'UPDATE'),
            has_table_privilege(current_user, 'app.payment_methods', 'INSERT'),
            has_table_privilege(current_user, 'app.payment_methods', 'UPDATE')
        """
    ).fetchone()
    configured = runtime_connection.execute(
        """
        SELECT property_id, version
        FROM app.replace_property_payment_methods(%s, %s, %s, %s)
        """,
        (
            property_id,
            Jsonb(
                [
                    {
                        "id": str(uuid4()),
                        "code": "BANK",
                        "display_name": "Bank transfer",
                        "accepted": True,
                    }
                ]
            ),
            1,
            actor_id,
        ),
    ).fetchone()
    methods = runtime_connection.execute(
        "SELECT code, display_name, accepted FROM app.payment_methods"
    ).fetchall()

    assert initialized == (
        property_id,
        "Riverside",
        "Phnom Penh",
        "Asia/Phnom_Penh",
        1,
    )
    assert stored == (
        property_id,
        "Riverside",
        "Phnom Penh",
        "Asia/Phnom_Penh",
        1,
        True,
    )
    assert privileges == (False, False, False, False)
    assert configured == (property_id, 2)
    assert methods == [("BANK", "Bank transfer", True)]
