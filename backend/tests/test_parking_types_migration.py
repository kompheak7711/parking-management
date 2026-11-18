"""PostgreSQL tests for the Parking Type seeds (Parking Step 3b, migration 255; Step 6: 431).

Owner answers of 2026-10-29: a new Property starts with the four Parking Types (Covered,
Uncovered, Motorbike, Tuk-Tuk/Food Cart) with the owner's Khmer names; a Property that already
exists gets the four added and keeps what it has. The default Rent itself comes from Property
Rental's migration 251 (V1-061) and is tested in test_unit_rent_terms_migration.py.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection

from test_unit_migration import insert_actor
from test_unit_setup_lists_migration import create_item, property_for

REVISION = "20270808_431"
HEAD = "20270811_434_parking"
PARKING_TYPES = [
    ("UNIT_TYPE", "COVERED", "Covered", "ចំណតមានដំបូល"),
    ("UNIT_TYPE", "UNCOVERED", "Uncovered", "ចំណតគ្មានដំបូល"),
    ("UNIT_TYPE", "MOTORBIKE", "Motorbike", "ម៉ូតូ"),
    ("UNIT_TYPE", "TUK_TUK_FOOD_CART", "Tuk-Tuk/Food Cart", "តុកតុក/រទេះលក់ម្ហូប"),
]
TYPES_OF = """
    SELECT list_kind, code, name_en, name_km
    FROM app.unit_setup_items
    WHERE property_id = %s AND list_kind = 'UNIT_TYPE' AND removed_at IS NULL
    ORDER BY sort_order, code
"""


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


def test_a_new_property_gets_the_four_parking_types_and_nothing_else(
    connection: Connection[tuple[object, ...]],
) -> None:
    """The one Property (app.properties is a singleton) is made by a test after the migrations,
    so the trigger seeds it with the four Parking Types, no Unit Types and no Balcony feature."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)

    assert connection.execute(TYPES_OF, (property_id,)).fetchall() == PARKING_TYPES
    assert connection.execute(
        "SELECT count(*) FROM app.unit_setup_items"
        " WHERE property_id = %s AND list_kind = 'FEATURE'",
        (property_id,),
    ).fetchone() == (0,)
    assert connection.execute(
        """
        SELECT count(*) FROM app.audit_events AS event
        JOIN app.unit_setup_items AS item ON item.id = event.entity_id
        WHERE item.property_id = %s AND event.action = 'unit_setup_item.created'
          AND item.code IN ('COVERED', 'UNCOVERED', 'MOTORBIKE', 'TUK_TUK_FOOD_CART')
        """,
        (property_id,),
    ).fetchone() == (4,)


def test_a_new_property_gets_property_rentals_v1_1_lists_without_balcony(
    connection: Connection[tuple[object, ...]],
) -> None:
    """Parking Step 6: the seed is Property Rental's V1.1 seed (Feature types, Unit features,
    Item types; hidden on Parking) with the four Parking Types and no Balcony anywhere."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    rows = connection.execute(
        "SELECT list_kind, code FROM app.unit_setup_items WHERE property_id = %s",
        (property_id,),
    ).fetchall()
    codes = {(str(kind), str(code)) for kind, code in rows}
    assert {
        ("FEATURE_TYPE", "ROOM"),
        ("FEATURE_TYPE", "BUILT_IN"),
        ("UNIT_FEATURE", "BEDROOM"),
        ("UNIT_FEATURE", "WALL_AIR_CONDITIONER"),
        ("ITEM_TYPE", "KEYS"),
    } <= codes
    assert not {code for code in codes if code[1] == "BALCONY"}
    assert not {code for code in codes if code[0] == "UNIT_TYPE"} - {
        ("UNIT_TYPE", row[1]) for row in PARKING_TYPES
    }


def test_parking_migrations_run_again_change_nothing(migrated_database_url: str) -> None:
    """Parking Step 6: the Parking database pkm ran 431-433 under their old ids (255-257), so it
    runs them again after Property Rental's migrations; each must then change nothing."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    count = """
        SELECT (SELECT count(*) FROM app.unit_setup_items),
               (SELECT count(*) FROM app.audit_events),
               to_regclass('app.vehicles') IS NOT NULL,
               pg_catalog.pg_get_functiondef(
                   'app.final_settlement_preview(uuid,uuid,uuid,text[])'::regprocedure)
    """
    with psycopg.connect(migrated_database_url) as connection:
        before = connection.execute(count).fetchone()
    command.stamp(config, "20270807_424")
    command.upgrade(config, "head")
    with psycopg.connect(migrated_database_url) as connection:
        after = connection.execute(count).fetchone()
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
    assert after == before
    assert before is not None and "IF false AND v_moved_in" in str(before[3])


def test_seeding_a_property_again_adds_only_what_is_missing_and_changes_nothing(
    connection: Connection[tuple[object, ...]],
) -> None:
    """What the migration does for a Property made before it: seeding again adds only the
    missing Parking Types and leaves every existing item as it is (same id, same version)."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    _, studio, _ = create_item(connection, property_id, actor_id, "UNIT_TYPE", "Studio")
    assert studio == "STUDIO"
    before = connection.execute(
        "SELECT id, code, version FROM app.unit_setup_items WHERE property_id = %s ORDER BY code",
        (property_id,),
    ).fetchall()

    connection.execute("SELECT app.seed_unit_setup_items(%s, %s)", (property_id, actor_id))

    # Other suites may have committed their own items to the one Property, so only what this
    # test can see is compared: the five codes are there, and no item changed or was added.
    codes = {row[1] for row in connection.execute(TYPES_OF, (property_id,)).fetchall()}
    assert {"STUDIO", "COVERED", "UNCOVERED", "MOTORBIKE", "TUK_TUK_FOOD_CART"} <= codes
    assert (
        connection.execute(
            "SELECT id, code, version FROM app.unit_setup_items"
            " WHERE property_id = %s ORDER BY code",
            (property_id,),
        ).fetchall()
        == before
    )


def test_the_parking_types_migration_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == HEAD
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / f"{REVISION}_parking_types.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "20270808_431_parking"' in source
    assert 'down_revision = "20270807_424"' in source
    assert 'raise RuntimeError("Parking Type seeds migration is forward-only")' in source
