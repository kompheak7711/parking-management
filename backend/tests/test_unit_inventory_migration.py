"""PostgreSQL tests for the Unit inventory with dated history (V1-058 R2b; DL-078 answer 2)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection
from psycopg.types.json import Jsonb

from property_rental.unit import UnitStatus
from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnitDetails,
    UnitResourceInvalid,
    UnitResourceNotFound,
    UnitVersionConflict,
)
from property_rental.unit_inventory_api import (
    PostgresUnitInventoryFlow,
    UnitInventoryItemName,
    UnitInventoryLine,
)
from test_unit_setup_lists_migration import create_unit, setup, sqlstate_of

REVISION = "20270217_205"
RECORD = "SELECT record_number, lines FROM app.record_unit_inventory(%s, %s, %s, %s, %s)"


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


def a_unit(connection: Connection[tuple[object, ...]]) -> tuple[UUID, UUID]:
    actor_id, property_id, floor_id = setup(connection)
    unit = create_unit(
        connection, property_id=property_id, actor_id=actor_id, floor_item_id=floor_id
    )
    return actor_id, UUID(str(unit[0]))


def line(group: str, name: str, quantity: int) -> dict[str, object]:
    return {"item_group": group, "item_name": name, "quantity": quantity}


def test_saves_are_numbered_records_and_each_is_in_the_unit_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, unit_id = a_unit(connection)
    first = connection.execute(
        RECORD,
        (
            uuid4(),
            unit_id,
            0,
            Jsonb([line("KITCHEN", " Kettle ", 1), line("FURNITURE", "Bed", 2)]),
            actor_id,
        ),
    ).fetchone()
    stale = connection.execute(RECORD, (uuid4(), unit_id, 0, Jsonb([]), actor_id)).fetchone()
    second = connection.execute(
        RECORD, (uuid4(), unit_id, 1, Jsonb([line("FURNITURE", "Bed", 1)]), actor_id)
    ).fetchone()
    events = connection.execute(
        """
        SELECT action, entity_type, previous_state, resulting_state
        FROM app.audit_events
        WHERE unit_id = %s AND action = 'unit.inventory_updated'
        ORDER BY (resulting_state ->> 'record_number')::integer
        """,
        (unit_id,),
    ).fetchall()
    stored = connection.execute(
        "SELECT count(*) FROM app.unit_inventory_records WHERE unit_id = %s", (unit_id,)
    ).fetchone()

    assert first == (
        1,
        [
            {"item_group": "FURNITURE", "item_name": "Bed", "quantity": 2},
            {"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 1},
        ],
    )
    assert stale is None
    assert second == (2, [{"item_group": "FURNITURE", "item_name": "Bed", "quantity": 1}])
    assert stored == (2,)
    assert [event[:2] for event in events] == [("unit.inventory_updated", "unit")] * 2
    assert events[0][2] is None
    assert events[1][2] == {"record_number": 1, "lines": first[1]}
    assert events[1][3] == {"record_number": 2, "lines": second[1]}


def test_bad_lines_and_unknown_units_are_refused(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, unit_id = a_unit(connection)

    def refusal(unit: UUID, lines: object) -> str | None:
        return sqlstate_of(connection, RECORD, (uuid4(), unit, 0, Jsonb(lines), actor_id))

    assert refusal(unit_id, [line("GARDEN", "Hose", 1)]) == "23514"
    assert refusal(unit_id, [line("KITCHEN", "Kettle", 0)]) == "23514"
    assert refusal(unit_id, [line("KITCHEN", "   ", 1)]) == "23514"
    assert refusal(unit_id, [line("KITCHEN", "Kettle", 1), line("KITCHEN", "KETTLE", 1)]) == (
        "23505"
    )
    assert refusal(unit_id, [line("KITCHEN", f"Item {n}", 1) for n in range(201)]) == "22023"
    assert refusal(unit_id, {"item_group": "KITCHEN"}) == "22023"
    assert refusal(unit_id, [{"item_group": "KITCHEN", "item_name": "Kettle"}]) == "22023"
    assert refusal(unit_id, [line("KITCHEN", "Kettle", 1) | {"item_name": None}]) == "22023"
    assert sqlstate_of(connection, RECORD, (uuid4(), unit_id, None, Jsonb([]), actor_id)) == "22023"
    assert refusal(uuid4(), []) == "P0002"
    assert connection.execute(
        "SELECT count(*) FROM app.unit_inventory_records WHERE unit_id = %s", (unit_id,)
    ).fetchone() == (0,)


def test_inventory_history_is_append_only(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, unit_id = a_unit(connection)
    connection.execute(
        RECORD, (uuid4(), unit_id, 0, Jsonb([line("BATHROOM", "Mirror", 1)]), actor_id)
    )

    assert (
        sqlstate_of(
            connection,
            "UPDATE app.unit_inventory_lines SET quantity = 2 WHERE item_name = 'Mirror'",
            (),
        )
        == "55000"
    )
    assert (
        sqlstate_of(
            connection, "DELETE FROM app.unit_inventory_records WHERE unit_id = %s", (unit_id,)
        )
        == "55000"
    )
    assert (
        sqlstate_of(
            connection,
            "UPDATE app.unit_inventory_records SET record_number = 9 WHERE unit_id = %s",
            (unit_id,),
        )
        == "55000"
    )
    for table in ("app.unit_inventory_lines", "app.unit_inventory_records"):
        assert sqlstate_of(connection, f"TRUNCATE {table} CASCADE", ()) == "55000"


def test_runtime_role_reads_the_inventory_and_saves_only_through_the_function(
    migrated_database_url: str,
) -> None:
    del migrated_database_url
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    with psycopg.connect(runtime_url) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege('app.unit_inventory_records', 'SELECT'),
                has_table_privilege('app.unit_inventory_records', 'INSERT'),
                has_table_privilege('app.unit_inventory_lines', 'SELECT'),
                has_table_privilege('app.unit_inventory_lines', 'INSERT'),
                has_function_privilege(
                    'app.record_unit_inventory(uuid,uuid,integer,jsonb,uuid)', 'EXECUTE'
                ),
                has_function_privilege('app.unit_inventory_lines_json(uuid)', 'EXECUTE'),
                has_function_privilege('app.reject_unit_inventory_change()', 'EXECUTE')
            """
        ).fetchone()
        runtime.rollback()

    assert privileges == (True, False, True, False, True, True, False)


def test_v1_058_r2b_is_forward_only_and_follows_r2a() -> None:
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / f"{REVISION}_unit_inventory.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20270216_204"' in source
    assert 'raise RuntimeError("Unit inventory migration is forward-only")' in source


def test_postgres_inventory_flow_reads_saves_and_offers_used_items(
    migrated_database_url: str,
) -> None:
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id = uuid4()
    property_id = uuid4()
    with psycopg.connect(migrated_database_url, autocommit=True) as admin:
        admin.execute(
            """
            INSERT INTO app.user_accounts (
                actor_id, normalized_username, display_name, audit_name,
                lifecycle_state, mfa_policy_class, provenance
            ) VALUES (%s, %s, 'Inventory', 'Inventory', 'active', 'optional', 'test')
            """,
            (actor_id, f"inventory-{actor_id}"),
        )
        existing = admin.execute("SELECT id FROM app.properties").fetchone()
        if existing is None:
            admin.execute(
                "INSERT INTO app.properties (id, name, created_by, updated_by) "
                "VALUES (%s, 'Inventory Property', %s, %s)",
                (property_id, actor_id, actor_id),
            )
        else:
            property_id = UUID(str(existing[0]))
    units = PostgresUnitResourceFlow(runtime_url)
    floor = units.create_setup_item(
        property_id,
        list_kind="FLOOR",
        name_en=f"Floor {uuid4().hex[:6]}",
        name_km=None,
        sort_order=1,
        actor_id=str(actor_id),
    )
    unit = units.create(
        property_id,
        unit_number=f"INV-{uuid4().hex[:8]}",
        floor_item_id=floor.item_id,
        unit_type="STUDIO",
        unit_status=UnitStatus.VACANT,
        details=UnitDetails(),
        actor_id=str(actor_id),
    )
    flow = PostgresUnitInventoryFlow(runtime_url)
    rare = f"Rocking chair {uuid4().hex[:6]}"

    empty = flow.current(unit.unit_id)
    saved = flow.record(
        unit.unit_id,
        lines=[UnitInventoryLine("FURNITURE", rare, 1)],
        expected_record_number=0,
        actor_id=str(actor_id),
    )
    with pytest.raises(UnitVersionConflict) as conflict:
        flow.record(unit.unit_id, lines=[], expected_record_number=0, actor_id=str(actor_id))
    with pytest.raises(UnitResourceInvalid):
        flow.record(
            unit.unit_id,
            lines=[UnitInventoryLine("GARDEN", "Hose", 1)],
            expected_record_number=1,
            actor_id=str(actor_id),
        )
    with pytest.raises(UnitResourceNotFound):
        flow.current(uuid4())
    known = flow.known_items(property_id)
    timeline = units.timeline(unit.unit_id, limit=10, cursor=None)
    # V1-058 R2: Change status writes the person's reason to the Unit's History.
    cleaning = units.patch(
        unit.unit_id,
        floor_item_id=floor.item_id,
        unit_type="STUDIO",
        unit_status=UnitStatus.CLEANING,
        details=UnitDetails(),
        expected_version=unit.version,
        actor_id=str(actor_id),
        reason="Deep clean before viewing",
    )
    status_event = units.timeline(unit.unit_id, limit=1, cursor=None).items[0]

    assert (empty.record_number, empty.lines, empty.recorded_by) == (0, (), None)
    assert (saved.record_number, saved.recorded_by) == (1, actor_id)
    assert saved.lines == (UnitInventoryLine("FURNITURE", rare, 1),)
    assert flow.current(unit.unit_id) == saved
    assert conflict.value.current_version == 1
    assert UnitInventoryItemName("FURNITURE", rare) in known
    assert UnitInventoryItemName("KITCHEN", "Kettle") in known
    assert timeline.items[0].action == "unit.inventory_updated"
    assert cleaning.status == UnitStatus.CLEANING
    assert (status_event.action, status_event.reason) == (
        "unit.status_changed",
        "Deep clean before viewing",
    )
