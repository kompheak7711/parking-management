"""PostgreSQL tests for the Parking default monthly price and the Parking Type seeds (Step 3).

Owner brief of 2026-10-29 (docs/replica/step-3-brief.md): a Parking has a default monthly price
in whole USD cents that fills a new Lease's price; changing it never changes a Lease. A new
Property starts with the four Parking Types (Covered, Uncovered, Motorbike, Tuk-Tuk/Food Cart).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection

from property_rental.unit_api import PostgresUnitResourceFlow
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_unit_migration import insert_actor
from test_unit_setup_lists_migration import create_item, create_unit, property_for, sqlstate_of

REVISION = "20270401_251"
SET_RENT = "SELECT * FROM app.set_unit_default_rent(%s, %s, %s, %s)"
WITH_DETAILS = "SELECT * FROM app.unit_with_details(%s)"
VERSION = 6
RENT = 15


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


def parking(connection: Connection[tuple[object, ...]]) -> tuple[UUID, UUID]:
    """One actor and one Parking of the Covered type on the one Property."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)
    floor_id, _, _ = create_item(connection, property_id, actor_id, "FLOOR", "Ground floor")
    row = create_unit(
        connection,
        property_id=property_id,
        actor_id=actor_id,
        floor_item_id=floor_id,
        unit_type="COVERED",
    )
    return actor_id, UUID(str(row[0]))


def test_a_default_rent_is_set(connection: Connection[tuple[object, ...]]) -> None:
    actor_id, unit_id = parking(connection)

    row = connection.execute(SET_RENT, (unit_id, 4500, 1, actor_id)).fetchone()
    details = connection.execute(WITH_DETAILS, (unit_id,)).fetchone()

    assert row is not None and details is not None
    assert (int(str(row[RENT])), int(str(row[VERSION]))) == (4500, 2)
    assert int(str(details[RENT])) == 4500
    assert details[:RENT] == row[:RENT]


def test_a_parking_starts_with_no_price(connection: Connection[tuple[object, ...]]) -> None:
    _, unit_id = parking(connection)

    details = connection.execute(WITH_DETAILS, (unit_id,)).fetchone()

    assert details is not None and details[RENT] is None


def test_a_stale_version_sets_nothing(connection: Connection[tuple[object, ...]]) -> None:
    actor_id, unit_id = parking(connection)
    connection.execute(SET_RENT, (unit_id, 4500, 1, actor_id))

    stale = connection.execute(SET_RENT, (unit_id, 3500, 1, actor_id)).fetchone()
    details = connection.execute(WITH_DETAILS, (unit_id,)).fetchone()

    assert stale is None
    assert details is not None
    assert (int(str(details[RENT])), int(str(details[VERSION]))) == (4500, 2)


def test_zero_and_negative_prices_are_refused(connection: Connection[tuple[object, ...]]) -> None:
    actor_id, unit_id = parking(connection)

    assert sqlstate_of(connection, SET_RENT, (unit_id, 0, 1, actor_id)) == "23514"
    assert sqlstate_of(connection, SET_RENT, (unit_id, -1, 1, actor_id)) == "23514"
    details = connection.execute(WITH_DETAILS, (unit_id,)).fetchone()
    assert details is not None
    assert (details[RENT], int(str(details[VERSION]))) == (None, 1)


def test_a_price_change_leaves_leases_untouched(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id, primary_tenant_id, _ = setup_sources(connection)
    lease_id = create_draft(
        connection, actor_id=actor_id, unit_id=unit_id, primary_tenant_id=primary_tenant_id
    )
    sign_lease(connection, lease_id, actor_id)
    version = connection.execute("SELECT version FROM app.units WHERE id = %s", (unit_id,))
    current = version.fetchone()
    assert current is not None

    connection.execute(SET_RENT, (unit_id, 4500, int(str(current[0])), actor_id))

    lease = connection.execute(
        "SELECT monthly_rent_usd_cents, version FROM app.leases WHERE id = %s", (lease_id,)
    ).fetchone()
    assert lease is not None
    assert (int(str(lease[0])), int(str(lease[1]))) == (80000, 2)


def test_the_property_gets_the_four_parking_types(
    connection: Connection[tuple[object, ...]],
) -> None:
    """The one Property (app.properties is a singleton) is made by a test after the migrations,
    so the trigger seeds it with the four Parking Types and nothing else."""
    actor_id = insert_actor(connection)
    property_id = property_for(connection, actor_id)

    rows = connection.execute(
        """
        SELECT list_kind, code, name_en, name_km
        FROM app.unit_setup_items
        WHERE property_id = %s AND list_kind = 'UNIT_TYPE'
        ORDER BY sort_order
        """,
        (property_id,),
    ).fetchall()

    assert rows == [
        ("UNIT_TYPE", "COVERED", "Covered", "ចំណតមានដំបូល"),
        ("UNIT_TYPE", "UNCOVERED", "Uncovered", "ចំណតគ្មានដំបូល"),
        ("UNIT_TYPE", "MOTORBIKE", "Motorbike", "ម៉ូតូ"),
        ("UNIT_TYPE", "TUK_TUK_FOOD_CART", "Tuk-Tuk/Food Cart", "តុកតុក/រទេះលក់ម្ហូប"),
    ]
    assert connection.execute(
        """
        SELECT count(*) FROM app.audit_events AS event
        JOIN app.unit_setup_items AS item ON item.id = event.entity_id
        WHERE item.property_id = %s AND event.action = 'unit_setup_item.created'
          AND item.code IN ('COVERED', 'UNCOVERED', 'MOTORBIKE', 'TUK_TUK_FOOD_CART')
        """,
        (property_id,),
    ).fetchone() == (4,)


def test_runtime_role_sets_the_price_only_through_the_function(
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
                has_table_privilege('app.units', 'UPDATE'),
                has_function_privilege(
                    'app.set_unit_default_rent(uuid,bigint,integer,uuid)', 'EXECUTE'
                )
            """
        ).fetchone()
    assert privileges == (False, True)


def test_step_3_migration_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == REVISION
    source = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / f"{REVISION}_parking_default_rent.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20270331_250"' in source
    assert 'raise RuntimeError("Parking default price migration is forward-only")' in source


def test_the_change_is_in_the_history_with_who_and_why(
    connection: Connection[tuple[object, ...]],
) -> None:
    """Owner, 2026-10-29: a price change is a money action; History shows who, when, the old
    price, the new price and the reason."""
    runtime_url = os.environ.get("APP_DATABASE_URL")
    if runtime_url is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    actor_id, unit_id = parking(connection)
    connection.commit()
    # The flow opens its own connection, so the Parking is committed; it stays (Unit rows and
    # their History cannot be deleted) and its number is unique.
    flow = PostgresUnitResourceFlow(runtime_url)
    first = flow.set_default_rent(
        unit_id, cents=3500, expected_version=1, actor_id=str(actor_id), reason="Opening price"
    )
    second = flow.set_default_rent(
        unit_id, cents=4500, expected_version=2, actor_id=str(actor_id), reason="New price list"
    )
    events = flow.timeline(unit_id, limit=5, cursor=None).items
    rows = connection.execute(
        """
        SELECT action, actor_id, reason,
               previous_state->>'default_monthly_rent_usd_cents',
               resulting_state->>'default_monthly_rent_usd_cents'
        FROM app.audit_events WHERE unit_id = %s AND action = 'unit.default_rent_changed'
        ORDER BY occurred_at
        """,
        (unit_id,),
    ).fetchall()
    who = connection.execute(
        "SELECT display_name FROM app.user_accounts WHERE actor_id = %s", (actor_id,)
    ).fetchone()

    assert (first.default_monthly_rent_usd_cents, second.default_monthly_rent_usd_cents) == (
        3500,
        4500,
    )
    assert rows == [
        ("unit.default_rent_changed", actor_id, "Opening price", None, "3500"),
        ("unit.default_rent_changed", actor_id, "New price list", "3500", "4500"),
    ]
    assert who is not None
    assert [(event.action, event.actor_name, event.reason) for event in events[:2]] == [
        ("unit.default_rent_changed", str(who[0]), "New price list"),
        ("unit.default_rent_changed", str(who[0]), "Opening price"),
    ]
