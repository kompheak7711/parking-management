"""PostgreSQL constraint tests for stable Property-scoped Unit storage."""

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

from property_rental.unit import (
    PostgresUnitRepository,
    Unit,
    UnitIdentityAlreadyExistsError,
    UnitStatus,
    UnitType,
)
from property_rental.unit_api import PostgresUnitResourceFlow, UnitDetails


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


def insert_actor(connection: Connection[tuple[object, ...]]) -> UUID:
    """Create an auditable actor for Unit persistence tests."""
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
        VALUES (%s, %s, 'Unit Tester', 'Unit Tester', 'active', 'optional', 'test')
        """,
        (actor_id, f"unit-{actor_id}"),
    )
    return actor_id


def insert_property(connection: Connection[tuple[object, ...]], actor_id: UUID) -> UUID:
    """Create the single Property required by Unit foreign keys."""
    property_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.properties (
            id,
            name,
            created_by,
            updated_by
        )
        VALUES (%s, 'Unit Test Property', %s, %s)
        """,
        (property_id, actor_id, actor_id),
    )
    return property_id


def test_units_reference_canonical_properties_table(
    connection: Connection[tuple[object, ...]],
) -> None:
    target = connection.execute(
        """
        SELECT c.confrelid::regclass::text, c.confdeltype
        FROM pg_constraint AS c
        WHERE c.conrelid = 'app.units'::regclass
          AND c.contype = 'f'
          AND c.conname = 'units_property_id_fkey'
        """
    ).fetchone()

    assert target == ("app.properties", "r")


def insert_unit(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    unit_id: UUID | None = None,
    unit_number: str = "101",
    floor: str = "1",
    unit_type: str = "STUDIO",
    status: str = "VACANT",
) -> UUID:
    """Insert a Unit directly as the migration owner for constraint tests."""
    stored_unit_id = uuid4() if unit_id is None else unit_id
    connection.execute(
        """
        INSERT INTO app.units (
            id,
            property_id,
            unit_number,
            floor,
            unit_type,
            status,
            created_by,
            updated_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            stored_unit_id,
            property_id,
            unit_number,
            floor,
            unit_type,
            status,
            actor_id,
            actor_id,
        ),
    )
    return stored_unit_id


def test_migration_persists_unit_identity_type_status_and_provenance(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)
    unit_id = insert_unit(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_type="TWO_BEDROOM",
        status="CLEANING",
    )

    stored = connection.execute(
        """
        SELECT
            id,
            property_id,
            unit_number,
            floor,
            unit_type,
            status,
            version,
            created_by,
            updated_by
        FROM app.units
        """
    ).fetchone()

    assert stored == (
        unit_id,
        property_id,
        "101",
        "1",
        "TWO_BEDROOM",
        "CLEANING",
        1,
        actor_id,
        actor_id,
    )


@pytest.mark.parametrize(
    "unit_type",
    ["STUDIO", "ONE_BEDROOM", "TWO_BEDROOM", "THREE_BEDROOM"],
)
def test_migration_accepts_supported_unit_types(
    connection: Connection[tuple[object, ...]], unit_type: str
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)

    insert_unit(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_type=unit_type,
    )


@pytest.mark.parametrize(
    "status",
    [
        "VACANT",
        "OCCUPIED",
        "UNDER_MAINTENANCE",
        "CLEANING",
        "OUT_OF_SERVICE",
    ],
)
def test_migration_accepts_supported_unit_statuses(
    connection: Connection[tuple[object, ...]], status: str
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)

    insert_unit(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        status=status,
    )


@pytest.mark.parametrize(
    ("overrides", "sqlstate"),
    [
        ({"unit_id": UUID(int=0)}, "23514"),
        ({"unit_number": ""}, "23514"),
        ({"unit_number": "\t\n"}, "23514"),
        ({"unit_number": " 101 "}, "23514"),
        ({"unit_number": "\t101\n"}, "23514"),
        ({"unit_number": "\u00a0101\u00a0"}, "23514"),
        ({"floor": ""}, "23514"),
        ({"floor": "\t\n"}, "23514"),
        ({"floor": "\r1\f"}, "23514"),
        # V1-058 R2a (owner 2026-10-24): a Unit Type must be in the Property's Unit Types list.
        ({"unit_type": "COMMERCIAL"}, "22023"),
        ({"status": "AVAILABLE"}, "23514"),
        # A Property that does not exist has no Unit Types list, so the list check refuses first.
        ({"property_id": uuid4()}, "22023"),
    ],
)
def test_migration_rejects_invalid_unit_values(
    connection: Connection[tuple[object, ...]],
    overrides: dict[str, object],
    sqlstate: str,
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)
    values: dict[str, object] = {
        "actor_id": actor_id,
        "property_id": property_id,
    }
    values.update(overrides)

    with pytest.raises(Error) as raised:
        insert_unit(connection, **values)  # type: ignore[arg-type]

    assert raised.value.sqlstate == sqlstate


def test_migration_rejects_duplicate_unit_number_within_property(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)
    insert_unit(connection, actor_id=actor_id, property_id=property_id)

    with pytest.raises(Error) as raised:
        insert_unit(connection, actor_id=actor_id, property_id=property_id)

    assert raised.value.sqlstate == "23505"


@pytest.mark.parametrize(
    "statement",
    [
        SQL("UPDATE app.units SET id = %s, version = version + 1"),
        SQL("UPDATE app.units SET property_id = %s, version = version + 1"),
        SQL(
            "UPDATE app.units "
            "SET created_at = created_at + interval '1 second', version = version + 1"
        ),
        SQL("DELETE FROM app.units"),
        SQL("TRUNCATE app.units"),
    ],
)
def test_migration_rejects_unit_identity_mutation_and_history_loss(
    connection: Connection[tuple[object, ...]], statement: SQL
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)
    insert_unit(connection, actor_id=actor_id, property_id=property_id)

    with pytest.raises(Error) as raised:
        parameters = (uuid4(),) if statement.as_string().find("%s") >= 0 else ()
        connection.execute(statement, parameters)

    assert raised.value.sqlstate in {"55000", "0A000"}


def test_migration_allows_versioned_state_change_without_replacing_identity(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = insert_property(connection, actor_id)
    unit_id = insert_unit(connection, actor_id=actor_id, property_id=property_id)

    updated = connection.execute(
        """
        UPDATE app.units
        SET status = 'UNDER_MAINTENANCE',
            updated_at = statement_timestamp(),
            updated_by = %s,
            version = version + 1
        WHERE id = %s
        RETURNING id, property_id, status, version
        """,
        (actor_id, unit_id),
    ).fetchone()

    assert updated == (unit_id, property_id, "UNDER_MAINTENANCE", 2)


def test_runtime_creates_units_only_through_protected_function(
    migrated_database_url: str,
    runtime_connection: Connection[tuple[object, ...]],
) -> None:
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
            VALUES (%s, %s, 'Unit Runtime', 'Unit Runtime', 'active', 'optional', 'test')
            """,
            (actor_id, f"unit-runtime-{actor_id}"),
        )

    property_id = uuid4()
    runtime_connection.execute(
        "SELECT property_id FROM app.initialize_property(%s, %s, %s, %s)",
        (property_id, "Runtime Property", "", actor_id),
    ).fetchone()
    unit_id = uuid4()

    with pytest.raises(Error) as raised:
        runtime_connection.execute(
            """
            INSERT INTO app.units (
                id, property_id, unit_number, floor, unit_type, status,
                created_by, updated_by
            )
            VALUES (%s, %s, 'FORGED', '1', 'STUDIO', 'VACANT', %s, %s)
            """,
            (uuid4(), property_id, actor_id, actor_id),
        )
    assert raised.value.sqlstate == "42501"
    runtime_connection.rollback()

    runtime_connection.execute(
        "SELECT property_id FROM app.initialize_property(%s, %s, %s, %s)",
        (property_id, "Runtime Property", "", actor_id),
    ).fetchone()
    created = runtime_connection.execute(
        """
        SELECT id, property_id, unit_number, floor, unit_type, status, version
        FROM app.create_unit(%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            unit_id,
            property_id,
            "\t101\n",
            "\r1\f",
            "ONE_BEDROOM",
            "VACANT",
            actor_id,
        ),
    ).fetchone()
    privileges = runtime_connection.execute(
        """
        SELECT
            has_table_privilege(current_user, 'app.units', 'SELECT'),
            has_table_privilege(current_user, 'app.units', 'INSERT'),
            has_table_privilege(current_user, 'app.units', 'UPDATE'),
            has_table_privilege(current_user, 'app.units', 'DELETE')
        """
    ).fetchone()

    assert created == (
        unit_id,
        property_id,
        "101",
        "1",
        "ONE_BEDROOM",
        "VACANT",
        1,
    )
    assert privileges == (True, False, False, False)


def test_postgres_repository_distinguishes_duplicate_unit_identity(
    migrated_database_url: str,
) -> None:
    actor_id = uuid4()
    property_id = uuid4()
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
            VALUES (%s, %s, 'Unit Identity', 'Unit Identity', 'active', 'optional', 'test')
            """,
            (actor_id, f"unit-identity-{actor_id}"),
        )
        admin.execute(
            """
            INSERT INTO app.properties (id, name, created_by, updated_by)
            VALUES (%s, 'Identity Test Property', %s, %s)
            """,
            (property_id, actor_id, actor_id),
        )

    repository = PostgresUnitRepository(migrated_database_url, actor_id)
    unit_id = uuid4()
    repository.add(
        Unit(
            unit_id=unit_id,
            property_id=property_id,
            unit_number="101",
            floor="1",
            unit_type=UnitType.STUDIO,
            status=UnitStatus.VACANT,
        )
    )

    with pytest.raises(UnitIdentityAlreadyExistsError):
        repository.add(
            Unit(
                unit_id=unit_id,
                property_id=property_id,
                unit_number="102",
                floor="1",
                unit_type=UnitType.ONE_BEDROOM,
                status=UnitStatus.VACANT,
            )
        )


def test_runtime_unit_flow_creates_updates_and_returns_immutable_timeline(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    property_id = uuid4()
    unit_number = f"API-{uuid4()}"
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Unit API', 'Unit API', 'active', 'optional', 'test')
            """,
            (actor_id, f"unit-api-{actor_id}"),
        )
        existing_property = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing_property is None:
            admin.execute(
                """
                INSERT INTO app.properties (id, name, created_by, updated_by)
                VALUES (%s, 'Unit API Property', %s, %s)
                """,
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing_property[0]))

    flow = PostgresUnitResourceFlow(runtime_url)
    # V1-058 R2a: the Floor comes from the Floors list (DL-075 answer 10, DL-078 answer 1).
    first_floor = flow.create_setup_item(
        property_id,
        list_kind="FLOOR",
        name_en=f"Floor {uuid4().hex[:6]}",
        name_km=None,
        sort_order=1,
        actor_id=str(actor_id),
    )
    second_floor = flow.create_setup_item(
        property_id,
        list_kind="FLOOR",
        name_en=f"Floor {uuid4().hex[:6]}",
        name_km=None,
        sort_order=2,
        actor_id=str(actor_id),
    )
    created = flow.create(
        property_id,
        unit_number=unit_number,
        floor_item_id=first_floor.item_id,
        unit_type=UnitType.STUDIO,
        unit_status=UnitStatus.VACANT,
        details=UnitDetails(),
        actor_id=str(actor_id),
    )
    updated = flow.patch(
        created.unit_id,
        floor_item_id=second_floor.item_id,
        unit_type=UnitType.ONE_BEDROOM,
        unit_status=UnitStatus.CLEANING,
        details=UnitDetails(),
        expected_version=1,
        actor_id=str(actor_id),
    )
    timeline = flow.timeline(created.unit_id, limit=10, cursor=None)

    assert updated.version == 2
    assert updated.floor == second_floor.name_en
    assert updated.status is UnitStatus.CLEANING
    assert [event.action for event in timeline.items] == ["unit.updated", "unit.created"]
    assert timeline.items[0].previous_state == {
        "unit_id": str(created.unit_id),
        "property_id": str(property_id),
        "unit_number": unit_number,
        "floor": first_floor.name_en,
        "unit_type": "STUDIO",
        "status": "VACANT",
        "version": 1,
        "floor_item_id": str(first_floor.item_id),
        "size_square_metres": None,
        "bedrooms": None,
        "bathrooms": None,
        "view_item_id": None,
        "kitchen_item_id": None,
        "notes": None,
        "room_feature_ids": [],
        "default_monthly_rent_usd_cents": None,
        "required_service_ids": [],
    }


def test_migration_is_forward_only(migrated_database_url: str) -> None:
    del migrated_database_url
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(alembic_config, "20260823_12")
