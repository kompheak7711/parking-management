"""PostgreSQL tests for the Unit setup lists and Unit details (V1-058 R2a).

DL-075 answer 10 and DL-078 answer 1, with the owner's 2026-10-24 19:24 go-ahead for the two
stricter checks: the Unit number cannot change and a Unit Type must be in the Unit Types list.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error

from test_migrations import _temporary_migration_database
from test_unit_migration import insert_actor, insert_property, insert_unit

REVISION = "20270308_227"
CREATE_UNIT = (
    "SELECT * FROM app.create_unit(%s, %s, %s, %s, %s, 'VACANT', %s, %s, %s, %s, %s, %s, %s, %s)"
)
UPDATE_UNIT = "SELECT * FROM app.update_unit(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
CREATE_ITEM = "SELECT * FROM app.create_unit_setup_item(%s, %s, %s, %s, %s, %s, %s)"


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


def create_item(
    connection: Connection[tuple[object, ...]],
    property_id: UUID,
    actor_id: UUID,
    list_kind: str,
    name_en: str,
    name_km: str | None = None,
) -> tuple[UUID, str, int]:
    row = connection.execute(
        CREATE_ITEM, (uuid4(), property_id, list_kind, name_en, name_km, 5, actor_id)
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), str(row[3]), int(str(row[8]))


def create_unit(
    connection: Connection[tuple[object, ...]],
    *,
    property_id: UUID,
    actor_id: UUID,
    floor_item_id: UUID,
    unit_type: str = "STUDIO",
    unit_number: str | None = None,
    size: Decimal | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    view_item_id: UUID | None = None,
    kitchen_item_id: UUID | None = None,
    notes: str | None = None,
    room_feature_ids: list[UUID] | None = None,
) -> tuple[object, ...]:
    row = connection.execute(
        CREATE_UNIT,
        (
            uuid4(),
            property_id,
            unit_number or f"U-{uuid4().hex[:8]}",
            floor_item_id,
            unit_type,
            actor_id,
            size,
            bedrooms,
            bathrooms,
            view_item_id,
            kitchen_item_id,
            notes,
            room_feature_ids or [],
        ),
    ).fetchone()
    assert row is not None
    return tuple(row)


def property_for(connection: Connection[tuple[object, ...]], actor_id: UUID) -> UUID:
    """The one Property: other suites may already have committed it."""
    existing = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing is None:
        return insert_property(connection, actor_id)
    return UUID(str(existing[0]))


def setup(connection: Connection[tuple[object, ...]]) -> tuple[UUID, UUID, UUID]:
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    floor_id, _, _ = create_item(connection, property_id, actor_id, "FLOOR", "Ground floor")
    return actor_id, property_id, floor_id


def sqlstate_of(
    connection: Connection[tuple[object, ...]], statement: str, parameters: tuple[object, ...]
) -> str | None:
    connection.execute("SAVEPOINT expected_refusal")
    try:
        connection.execute(statement, parameters)
    except Error as error:
        connection.execute("ROLLBACK TO SAVEPOINT expected_refusal")
        return error.sqlstate
    connection.execute("RELEASE SAVEPOINT expected_refusal")
    return None


def test_every_property_gets_the_default_unit_types_and_balcony(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)

    rows = connection.execute(
        """
        SELECT list_kind, code, name_en, name_km IS NOT NULL
        FROM app.unit_setup_items
        WHERE property_id = %s AND code IN (
            'STUDIO', 'ONE_BEDROOM', 'TWO_BEDROOM', 'THREE_BEDROOM', 'BALCONY'
        )
        ORDER BY list_kind, sort_order
        """,
        (property_id,),
    ).fetchall()
    trigger = connection.execute(
        """
        SELECT tgenabled FROM pg_trigger
        WHERE tgrelid = 'app.properties'::regclass AND tgname = 'properties_seed_unit_setup_items'
        """
    ).fetchone()

    assert rows == [
        ("ROOM_FEATURE", "BALCONY", "Balcony", True),
        ("UNIT_TYPE", "STUDIO", "Studio", True),
        ("UNIT_TYPE", "ONE_BEDROOM", "1 bedroom", True),
        ("UNIT_TYPE", "TWO_BEDROOM", "2 bedrooms", True),
        ("UNIT_TYPE", "THREE_BEDROOM", "3 bedrooms", True),
    ]
    assert trigger == ("O",)
    assert connection.execute(
        """
        SELECT count(*) FROM app.unit_setup_items AS item
        WHERE item.property_id = %s AND item.code IN ('STUDIO', 'BALCONY')
          AND EXISTS (
              SELECT 1 FROM app.audit_events AS event
              WHERE event.entity_id = item.id AND event.action = 'unit_setup_item.created'
          )
        """,
        (property_id,),
    ).fetchone() == (2,)


def test_list_items_get_codes_from_their_names_and_are_audited(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, _ = setup(connection)
    tag = uuid4().hex[:6].upper()
    first = create_item(
        connection, property_id, actor_id, "VIEW", f"  City view {tag} ", "ទិដ្ឋភាពក្រុង"
    )
    second = create_item(connection, property_id, actor_id, "VIEW", f"City-view {tag}")
    penthouse = create_item(connection, property_id, actor_id, "UNIT_TYPE", f"Penthouse {tag}")

    updated = connection.execute(
        "SELECT * FROM app.update_unit_setup_item(%s, 'River view', NULL, 9, 1, %s)",
        (first[0], actor_id),
    ).fetchone()
    stale = connection.execute(
        "SELECT * FROM app.update_unit_setup_item(%s, 'Late', NULL, 9, 1, %s)",
        (first[0], actor_id),
    ).fetchone()
    events = connection.execute(
        """
        SELECT action, previous_state ->> 'name_en', resulting_state ->> 'name_en'
        FROM app.audit_events
        WHERE entity_type = 'unit_setup_item' AND entity_id = %s ORDER BY occurred_at, action
        """,
        (first[0],),
    ).fetchall()

    assert (first[1], second[1], penthouse[1]) == (
        f"CITY_VIEW_{tag}",
        f"CITY_VIEW_{tag}_2",
        f"PENTHOUSE_{tag}",
    )
    assert updated is not None
    assert (updated[3], updated[4], updated[5], updated[6], updated[8]) == (
        f"CITY_VIEW_{tag}",
        "River view",
        None,
        9,
        2,
    )
    assert stale is None
    assert events == [
        ("unit_setup_item.created", None, f"City view {tag}"),
        ("unit_setup_item.updated", f"City view {tag}", "River view"),
    ]


def test_units_save_keep_and_clear_details_and_room_features(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, floor_id = setup(connection)
    view_id, _, _ = create_item(connection, property_id, actor_id, "VIEW", "Pool view")
    kitchen_id, _, _ = create_item(connection, property_id, actor_id, "KITCHEN", "Open kitchen")
    balcony_id = connection.execute(
        "SELECT id FROM app.unit_setup_items WHERE property_id = %s AND code = 'BALCONY'",
        (property_id,),
    ).fetchone()
    assert balcony_id is not None
    desk_id, _, _ = create_item(connection, property_id, actor_id, "ROOM_FEATURE", "Desk")

    created = create_unit(
        connection,
        property_id=property_id,
        actor_id=actor_id,
        floor_item_id=floor_id,
        unit_type="ONE_BEDROOM",
        size=Decimal("42.50"),
        bedrooms=1,
        bathrooms=1,
        view_item_id=view_id,
        kitchen_item_id=kitchen_id,
        notes="  Corner Unit  ",
        room_feature_ids=[UUID(str(balcony_id[0])), desk_id],
    )
    unit_id = created[0]
    updated = connection.execute(
        UPDATE_UNIT,
        (
            unit_id,
            floor_id,
            "TWO_BEDROOM",
            "CLEANING",
            1,
            actor_id,
            None,
            2,
            None,
            None,
            kitchen_id,
            None,
            [desk_id],
        ),
    ).fetchone()

    assert created[3] == "Ground floor"
    assert created[7:14] == (floor_id, Decimal("42.50"), 1, 1, view_id, kitchen_id, "Corner Unit")
    assert isinstance(created[14], list)
    assert set(created[14]) == {balcony_id[0], desk_id}
    assert updated is not None
    assert updated[4:7] == ("TWO_BEDROOM", "CLEANING", 2)
    assert updated[8:15] == (None, 2, None, None, kitchen_id, None, [desk_id])


def test_unit_types_and_items_must_come_from_the_property_lists(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, floor_id = setup(connection)
    view_id, _, _ = create_item(connection, property_id, actor_id, "VIEW", "Garden")
    unit_id = create_unit(
        connection, property_id=property_id, actor_id=actor_id, floor_item_id=floor_id
    )[0]

    def unit_refusal(floor: UUID, unit_type: str, view: UUID | None, feature: UUID | None) -> str:
        state = sqlstate_of(
            connection,
            CREATE_UNIT,
            (
                uuid4(),
                property_id,
                f"X-{uuid4().hex[:8]}",
                floor,
                unit_type,
                actor_id,
                None,
                None,
                None,
                view,
                None,
                None,
                [feature] if feature else [],
            ),
        )
        assert state is not None
        return state

    assert unit_refusal(floor_id, "PENTHOUSE", None, None) == "22023"
    assert unit_refusal(floor_id, "commercial", None, None) == "22023"
    assert unit_refusal(uuid4(), "STUDIO", None, None) == "22023"
    assert unit_refusal(view_id, "STUDIO", None, None) == "22023"
    assert unit_refusal(floor_id, "STUDIO", floor_id, None) == "22023"
    assert unit_refusal(floor_id, "STUDIO", None, view_id) == "22023"
    assert (
        sqlstate_of(
            connection,
            "UPDATE app.units SET unit_type = 'PENTHOUSE', version = version + 1 WHERE id = %s",
            (unit_id,),
        )
        == "22023"
    )


def test_the_unit_number_never_changes_after_creation(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, floor_id = setup(connection)
    number = f"NUM-{uuid4().hex[:8]}"
    unit_id = insert_unit(
        connection, actor_id=actor_id, property_id=property_id, unit_number=number
    )

    old_update = sqlstate_of(
        connection,
        "SELECT * FROM app.update_unit(%s, %s, '1', 'STUDIO', 'VACANT', 1, %s)",
        (unit_id, f"{number}-B", actor_id),
    )
    direct = sqlstate_of(
        connection,
        "UPDATE app.units SET unit_number = 'NUM-3', version = version + 1 WHERE id = %s",
        (unit_id,),
    )
    same_number = connection.execute(
        "SELECT version FROM app.update_unit(%s, %s, '2', 'STUDIO', 'CLEANING', 1, %s)",
        (unit_id, number, actor_id),
    ).fetchone()
    linked = create_unit(
        connection, property_id=property_id, actor_id=actor_id, floor_item_id=floor_id
    )
    connection.execute(
        "SELECT * FROM app.update_unit(%s, %s, 'Roof', 'STUDIO', 'VACANT', 1, %s)",
        (linked[0], linked[2], actor_id),
    )
    unlinked = connection.execute(
        "SELECT floor, floor_item_id FROM app.unit_with_details(%s)", (linked[0],)
    ).fetchone()

    assert (old_update, direct) == ("55000", "55000")
    assert same_number == (2,)
    assert unlinked == ("Roof", None)
    assert connection.execute(
        "SELECT unit_number FROM app.units WHERE id = %s", (unit_id,)
    ).fetchone() == (number,)


def test_items_in_use_cannot_be_removed_and_removed_items_cannot_be_picked(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, floor_id = setup(connection)
    spare_floor, _, _ = create_item(connection, property_id, actor_id, "FLOOR", "Roof")
    feature_id, _, _ = create_item(connection, property_id, actor_id, "ROOM_FEATURE", "Bathtub")
    create_unit(
        connection,
        property_id=property_id,
        actor_id=actor_id,
        floor_item_id=floor_id,
        room_feature_ids=[feature_id],
    )
    studio = connection.execute(
        """
        SELECT id, version FROM app.unit_setup_items
        WHERE property_id = %s AND list_kind = 'UNIT_TYPE' AND code = 'STUDIO'
        """,
        (property_id,),
    ).fetchone()
    loft_id, loft_code, _ = create_item(
        connection, property_id, actor_id, "UNIT_TYPE", f"Loft {uuid4().hex[:6]}"
    )
    assert studio is not None
    remove = "SELECT * FROM app.remove_unit_setup_item(%s, %s, %s)"

    in_use = [
        sqlstate_of(connection, remove, (item, version, actor_id))
        for item, version in ((floor_id, 1), (feature_id, 1), (studio[0], studio[1]))
    ]
    removed_floor = connection.execute(remove, (spare_floor, 1, actor_id)).fetchone()
    removed_type = connection.execute(remove, (loft_id, 1, actor_id)).fetchone()
    pick_floor = sqlstate_of(
        connection,
        CREATE_UNIT,
        (
            uuid4(),
            property_id,
            f"PICK-{uuid4().hex[:8]}",
            spare_floor,
            "STUDIO",
            actor_id,
            None,
            None,
            None,
            None,
            None,
            None,
            [],
        ),
    )
    pick_type = sqlstate_of(
        connection,
        CREATE_UNIT,
        (
            uuid4(),
            property_id,
            f"PICK-{uuid4().hex[:8]}",
            floor_id,
            loft_code,
            actor_id,
            None,
            None,
            None,
            None,
            None,
            None,
            [],
        ),
    )
    remove_again = sqlstate_of(connection, remove, (spare_floor, 2, actor_id))
    change_removed = sqlstate_of(
        connection,
        "SELECT * FROM app.update_unit_setup_item(%s, 'Top', NULL, 1, 2, %s)",
        (spare_floor, actor_id),
    )
    delete = sqlstate_of(
        connection, "DELETE FROM app.unit_setup_items WHERE id = %s", (spare_floor,)
    )
    code_change = sqlstate_of(
        connection,
        "UPDATE app.unit_setup_items SET code = 'TOP', version = version + 1 WHERE id = %s",
        (feature_id,),
    )

    assert in_use == ["55000", "55000", "55000"]
    assert removed_floor is not None and removed_floor[7] is not None
    assert removed_type is not None and removed_type[8] == 2
    assert (pick_floor, pick_type, change_removed, remove_again) == ("22023",) * 4
    assert (delete, code_change) == ("55000", "55000")


def test_runtime_role_reads_lists_and_writes_only_through_functions(
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
                has_table_privilege('app.unit_setup_items', 'SELECT'),
                has_table_privilege('app.unit_setup_items', 'INSERT'),
                has_table_privilege('app.unit_setup_items', 'UPDATE'),
                has_table_privilege('app.unit_setup_items', 'DELETE'),
                has_table_privilege('app.unit_room_features', 'SELECT'),
                has_table_privilege('app.unit_room_features', 'INSERT'),
                has_function_privilege(
                    'app.create_unit_setup_item(uuid,uuid,text,text,text,integer,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    'app.update_unit_setup_item(uuid,text,text,integer,integer,uuid)', 'EXECUTE'
                ),
                has_function_privilege('app.remove_unit_setup_item(uuid,integer,uuid)', 'EXECUTE'),
                has_function_privilege('app.unit_with_details(uuid)', 'EXECUTE'),
                has_function_privilege('app.seed_unit_setup_items(uuid,uuid)', 'EXECUTE'),
                has_function_privilege(
                    'app.replace_unit_room_features(uuid,uuid[])', 'EXECUTE'
                ),
                has_function_privilege(
                    'app.assert_unit_setup_item(uuid,text,uuid)', 'EXECUTE'
                ),
                has_function_privilege(
                    'app.create_unit(uuid,uuid,text,uuid,text,text,uuid,numeric,smallint,'
                    'smallint,uuid,uuid,text,uuid[])',
                    'EXECUTE'
                ),
                has_function_privilege(
                    'app.update_unit(uuid,uuid,text,text,integer,uuid,numeric,smallint,'
                    'smallint,uuid,uuid,text,uuid[])',
                    'EXECUTE'
                )
            """
        ).fetchone()
        runtime.rollback()

    assert privileges == (
        True,
        False,
        False,
        False,
        True,
        False,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        True,
    )


def test_the_existing_property_gets_the_defaults_and_its_floors_linked() -> None:
    if os.environ.get("MIGRATION_DATABASE_URL") is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    with _temporary_migration_database("unit_setup_backfill") as temporary:
        url = temporary.replace("postgresql+psycopg://", "postgresql://", 1)
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "20270307_226")
        with psycopg.connect(url) as connection:
            actor_id = insert_actor(connection)
            property_id = insert_property(connection, actor_id)
            first = insert_unit(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                unit_number="101",
                floor="1",
            )
            second = insert_unit(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                unit_number="102",
                floor="1",
                unit_type="TWO_BEDROOM",
            )
            third = insert_unit(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                unit_number="201",
                floor="2",
            )
            long_floor = "L" * 99 + " " + "tail"
            fourth = insert_unit(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                unit_number="301",
                floor=long_floor,
            )
            connection.commit()
            before = connection.execute(
                "SELECT id, version, updated_at FROM app.units ORDER BY id"
            ).fetchall()

        command.upgrade(config, REVISION)

        with psycopg.connect(url) as connection:
            floors = connection.execute(
                """
                SELECT code, name_en, sort_order FROM app.unit_setup_items
                WHERE property_id = %s AND list_kind = 'FLOOR' ORDER BY code
                """,
                (property_id,),
            ).fetchall()
            links: dict[object, object] = dict(
                connection.execute(
                    """
                    SELECT unit.id, item.code FROM app.units AS unit
                    JOIN app.unit_setup_items AS item ON item.id = unit.floor_item_id
                    """
                ).fetchall()
            )
            types = connection.execute(
                """
                SELECT count(*) FROM app.unit_setup_items
                WHERE property_id = %s AND list_kind = 'UNIT_TYPE'
                """,
                (property_id,),
            ).fetchone()
            after = connection.execute(
                "SELECT id, version, updated_at FROM app.units ORDER BY id"
            ).fetchall()
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            created_events = connection.execute(
                """
                SELECT count(*) FROM app.audit_events
                WHERE entity_type = 'unit_setup_item' AND action = 'unit_setup_item.created'
                  AND previous_state IS NULL
                """
            ).fetchone()
            item_count = connection.execute("SELECT count(*) FROM app.unit_setup_items").fetchone()

    assert floors == [("F001", "1", 10), ("F002", "2", 20), ("F003", "L" * 99, 30)]
    assert links == {first: "F001", second: "F001", third: "F002", fourth: "F003"}
    assert created_events == item_count == (8,)
    assert types == (4,)
    assert after == before
    assert version == (REVISION,)


def test_v1_058_r2a_is_forward_only_and_follows_r2c() -> None:
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / f"{REVISION}_unit_setup_lists.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20270307_226"' in source
    assert 'raise RuntimeError("Unit setup lists migration is forward-only")' in source
