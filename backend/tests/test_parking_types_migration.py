"""PostgreSQL tests for the Parking Type seeds (Parking Step 3b, migration 255).

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

REVISION = "20270405_255"
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
    assert ScriptDirectory.from_config(config).get_current_head() == "20270406_256"
    source = (
        Path(__file__).parents[1] / "migrations" / "versions" / f"{REVISION}_parking_types.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20270404_254"' in source
    assert 'raise RuntimeError("Parking Type seeds migration is forward-only")' in source
