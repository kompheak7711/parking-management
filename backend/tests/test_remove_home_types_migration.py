"""PostgreSQL tests for the removal of the home Unit Types and Balcony (Parking Step 7, 434).

Owner, 18 Nov 2026 ("yes start the code fix"): Parking itself removes the home Unit Types
(Studio, 1 bedroom, 2 bedrooms, 3 bedrooms) and the Balcony item that Property Rental's
migrations 227 and 255 put into a Property that already existed, the same way Settings Remove
does (removed_at, removed_by, version + 1, a `unit_setup_item.removed` audit row). Nothing is
deleted. An item still used by a Parking space is left as it is, with a note in the upgrade
output (owner's choice A, 18 Nov 2026).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection

from test_parking_types_migration import PARKING_TYPES, TYPES_OF
from test_parking_types_migration import connection as connection
from test_parking_types_migration import migrated_database_url as migrated_database_url
from test_unit_migration import insert_actor
from test_unit_setup_lists_migration import create_item, create_unit, property_for

REVISION = "20270811_434_parking"
SOURCE = Path(__file__).parents[1] / "migrations" / "versions" / "20270811_434_remove_home_types.py"
HOME_ITEMS = [
    ("ROOM_FEATURE", "BALCONY"),
    ("UNIT_FEATURE", "BALCONY"),
    ("UNIT_TYPE", "ONE_BEDROOM"),
    ("UNIT_TYPE", "STUDIO"),
    ("UNIT_TYPE", "THREE_BEDROOM"),
    ("UNIT_TYPE", "TWO_BEDROOM"),
]


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("remove_home_types", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_home_items(connection: Connection[tuple[object, ...]], property_id: UUID) -> None:
    """What Property Rental's 227 and 255 left in a Property made before Parking Step 3b."""
    actor_id = connection.execute(
        "SELECT created_by FROM app.properties WHERE id = %s", (property_id,)
    ).fetchone()
    assert actor_id is not None
    outdoor = connection.execute(
        "SELECT id FROM app.unit_setup_items"
        " WHERE property_id = %s AND list_kind = 'FEATURE_TYPE' AND code = 'OUTDOOR'",
        (property_id,),
    ).fetchone()
    assert outdoor is not None
    for list_kind, code in HOME_ITEMS:
        connection.execute(
            """
            INSERT INTO app.unit_setup_items (
                id, property_id, list_kind, code, name_en, sort_order, created_by, updated_by,
                feature_type_item_id
            ) VALUES (%s, %s, %s, %s, %s, 90, %s, %s, %s)
            ON CONFLICT (property_id, list_kind, code) DO NOTHING
            """,
            (
                uuid4(),
                property_id,
                list_kind,
                code,
                code.title(),
                actor_id[0],
                actor_id[0],
                outdoor[0] if list_kind == "UNIT_FEATURE" else None,
            ),
        )


def home_rows(
    connection: Connection[tuple[object, ...]], property_id: UUID
) -> list[tuple[object, ...]]:
    return connection.execute(
        """
        SELECT item.list_kind, item.code, item.removed_at IS NOT NULL,
               item.removed_by = property.created_by, item.version
        FROM app.unit_setup_items AS item
        JOIN app.properties AS property ON property.id = item.property_id
        WHERE item.property_id = %s
          AND (item.list_kind, item.code) IN (
              ('ROOM_FEATURE', 'BALCONY'), ('UNIT_FEATURE', 'BALCONY'),
              ('UNIT_TYPE', 'STUDIO'), ('UNIT_TYPE', 'ONE_BEDROOM'),
              ('UNIT_TYPE', 'TWO_BEDROOM'), ('UNIT_TYPE', 'THREE_BEDROOM'))
        ORDER BY item.list_kind, item.code
        """,
        (property_id,),
    ).fetchall()


def removed_audit_count(connection: Connection[tuple[object, ...]], property_id: UUID) -> int:
    row = connection.execute(
        """
        SELECT count(*) FROM app.audit_events AS event
        JOIN app.unit_setup_items AS item ON item.id = event.entity_id
        WHERE item.property_id = %s AND event.action = 'unit_setup_item.removed'
          AND item.code IN ('BALCONY', 'STUDIO', 'ONE_BEDROOM', 'TWO_BEDROOM', 'THREE_BEDROOM')
        """,
        (property_id,),
    ).fetchone()
    assert row is not None
    return int(str(row[0]))


def test_the_home_types_and_balcony_are_marked_removed_with_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    add_home_items(connection, property_id)
    count = "SELECT count(*) FROM app.unit_setup_items WHERE property_id = %s"
    items_before = connection.execute(count, (property_id,)).fetchone()

    connection.execute(migration().REMOVE_HOME_ITEMS)

    assert home_rows(connection, property_id) == [
        (list_kind, code, True, True, 2) for list_kind, code in HOME_ITEMS
    ]
    assert removed_audit_count(connection, property_id) == len(HOME_ITEMS)
    # Nothing is deleted, and the four Parking Types stay.
    assert connection.execute(count, (property_id,)).fetchone() == items_before
    assert connection.execute(TYPES_OF, (property_id,)).fetchall() == PARKING_TYPES


def test_running_the_removal_again_changes_nothing(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    add_home_items(connection, property_id)
    connection.execute(migration().REMOVE_HOME_ITEMS)
    before = (home_rows(connection, property_id), removed_audit_count(connection, property_id))

    connection.execute(migration().REMOVE_HOME_ITEMS)

    assert (home_rows(connection, property_id), removed_audit_count(connection, property_id)) == (
        before
    )


def test_a_home_type_used_by_a_parking_space_is_left_with_a_note_and_the_rest_are_removed(
    connection: Connection[tuple[object, ...]],
) -> None:
    """Owner's choice A (18 Nov 2026): the used one stays, the upgrade output names it, the
    other five are removed and the upgrade carries on."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    add_home_items(connection, property_id)
    floor_id, _, _ = create_item(connection, property_id, actor_id, "FLOOR", "Ground floor")
    create_unit(
        connection,
        property_id=property_id,
        actor_id=actor_id,
        floor_item_id=floor_id,
        unit_type="STUDIO",
    )
    notes: list[str] = []
    connection.add_notice_handler(lambda notice: notes.append(str(notice.message_primary)))

    connection.execute(migration().REMOVE_HOME_ITEMS)

    assert notes == ["Parking Step 7: home items still in use, left as they are: UNIT_TYPE STUDIO"]
    assert home_rows(connection, property_id) == [
        (list_kind, code, False, None, 1) if code == "STUDIO" else (list_kind, code, True, True, 2)
        for list_kind, code in HOME_ITEMS
    ]
    assert removed_audit_count(connection, property_id) == len(HOME_ITEMS) - 1


def test_a_new_property_never_gets_home_items_from_the_seed(
    connection: Connection[tuple[object, ...]],
) -> None:
    """Sync guard: a later Property Rental migration that replaces the seed function with its
    home lists fails here, so Parking's seed (431) is put back on top before release."""
    definition = connection.execute(
        "SELECT pg_catalog.pg_get_functiondef('app.seed_unit_setup_items(uuid,uuid)'::regprocedure)"
    ).fetchone()
    assert definition is not None
    for code in ("'STUDIO'", "'ONE_BEDROOM'", "'TWO_BEDROOM'", "'THREE_BEDROOM'", "'BALCONY'"):
        assert code not in str(definition[0])
    for _, code, _, _ in PARKING_TYPES:
        assert f"'{code}'" in str(definition[0])


def test_the_removal_migration_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == REVISION
    revision = script.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270810_433_parking"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration().downgrade()
