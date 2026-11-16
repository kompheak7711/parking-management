"""UI v81 (migration 20270714_365): the Home page read gets back the four earlier fixes that
migration 20270710_361 dropped, and keeps the "Paid on time" and "Birthdays" cards.

Migration 361 replaced `app.home_page` with a text written from migration 222, so the changes of
migrations 238 (a Unit with no Meter), 242 (a draft the read does not understand), 243 (speed)
and 258 (a Unit not for rent) were lost. Migration 365 puts them back from the text the database
holds. Their own tests (`test_final_settlement_preview_migration`, `test_v1_060_release_migration`
and `test_unit_for_rent_migration`) check what each one does; these tests check the step itself.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.unit_api import PostgresUnitResourceFlow
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_api_migration import runtime_database_url
from test_lease_migration import setup_sources
from test_migrations import _run_alembic, _temporary_migration_database

REVISION = "20270714_365"
PREVIOUS = "20270713_364"
HOME = "app.home_page(uuid,uuid,uuid[],text[])"
DEFINITION = "SELECT pg_catalog.pg_get_functiondef(%s::regprocedure)"
FACTS = (
    "SELECT proowner::regrole::text, proacl::text, prosecdef, provolatile, proconfig "
    "FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure"
)


def _migration(name: str = REVISION) -> ModuleType:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(name)
    assert revision is not None
    return revision.module


def _definition(connection: psycopg.Connection[Any]) -> str:
    row = connection.execute(DEFINITION, (HOME,)).fetchone()
    assert row is not None
    return str(row[0])


def _units_total(actor: UUID, prop: UUID) -> int:
    with psycopg.connect(runtime_database_url()) as connection:
        row = connection.execute(
            "SELECT app.home_page(%s,%s,%s::uuid[],%s::text[])", (actor, prop, [prop], ["units"])
        ).fetchone()
    assert row is not None
    return int(row[0]["cards"]["units_occupied"]["total"])


def test_migration_365_follows_the_payments_paid_for_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    assert scripts.get_heads() == ["20270804_422"]
    with pytest.raises(NotImplementedError, match="forward-only"):
        revision.module.downgrade()


def test_the_migration_puts_the_four_fixes_back_and_keeps_the_ui_v81_cards() -> None:
    """Before the step the function has none of the four fixes; after it, it is the same text
    with each of the seven old texts changed once, the two UI v81 parts still there, and the
    same owner, privileges and settings."""
    module = _migration()
    replacements = cast(tuple[tuple[str, str], ...], module.REPLACEMENTS)
    assert len(replacements) == 7
    with _temporary_migration_database("prm_home_fixes") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        with psycopg.connect(temporary) as connection:
            before = _definition(connection)
            facts_before = connection.execute(FACTS, (HOME,)).fetchone()
        for old, new in replacements:
            assert before.count(old) == 1 and new not in before
        result = _run_alembic("upgrade", REVISION)
        assert result.returncode == 0, result.stderr
        with psycopg.connect(temporary) as connection:
            after = _definition(connection)
            facts_after = connection.execute(FACTS, (HOME,)).fetchone()
    expected = before
    for old, new in replacements:
        expected = expected.replace(old, new)
    assert after == expected
    for old, new in replacements:
        assert after.count(new) == 1 and old not in after
    for kept in cast(tuple[str, ...], module.KEPT):
        assert before.count(kept) == 1 and after.count(kept) == 1
    assert facts_before is not None and facts_after == facts_before
    assert facts_after[0] == "prm_migrator" and "prm_runtime=X/prm_migrator" in facts_after[1]


def test_the_home_page_at_the_head_holds_every_fix_once(migrated_database_url: str) -> None:
    module = _migration()
    with psycopg.connect(migrated_database_url) as connection:
        definition = _definition(connection)
    # Main's 421 (C2, DL-241; joined by 417) reads who holds each Unit for the Units card, so the
    # card reads a worked-out status instead of app.units; the for-rent rule stays.
    held = _migration("20270803_417")
    definition = definition.replace(cast(str, held.UNITS_AFTER), cast(str, held.UNITS_BEFORE))
    for old, new in cast(tuple[tuple[str, str], ...], module.REPLACEMENTS):
        assert definition.count(new) == 1 and old not in definition
    for kept in cast(tuple[str, ...], module.KEPT):
        assert definition.count(kept) == 1


def test_a_unit_not_for_rent_is_not_counted_in_the_home_units_card(
    migrated_database_url: str,
) -> None:
    """Owner 2026-10-31 (migration 258): a Unit not for rent is not counted. Setting one Unit not
    for rent takes one from the Units total; setting it back for rent adds it again."""
    with psycopg.connect(migrated_database_url) as connection:
        actor, prop, unit, _, _ = setup_sources(connection)
        connection.commit()
    flow = PostgresUnitResourceFlow(runtime_database_url())
    total = _units_total(actor, prop)
    assert total >= 1
    start = flow.get(unit)
    kept = flow.set_for_rent(
        unit, for_rent=False, expected_version=start.version, actor_id=str(actor)
    )
    assert _units_total(actor, prop) == total - 1
    flow.set_for_rent(unit, for_rent=True, expected_version=kept.version, actor_id=str(actor))
    assert _units_total(actor, prop) == total
