"""DL-226 (D2), migration 20270722_377: the late-payment charge in Settings is at most 10%.

The owner decided on 12 Nov 2026 that Settings refuse a late-payment charge above 10% (Lease
Article 2.3). Before this migration Settings took any value up to 100%, but the record of a
late-payment charge (``app.late_payment_decisions``, DL-085) holds only a whole percent from 0
to 10. So a value such as 15% or 7.5% was saved in Settings, but the charge record refuses it,
and the automatic late-payment charge could then not be saved.

Now Settings take only what the charge can hold: a whole percent from 0 to 10. A value saved
before this migration stays in the history; the program reads it as at most 10%, in whole
percent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.business_rules_api import BusinessRuleInvalid, _refusal
from test_business_settings_migration import SET_RULE, refused, scalar, today
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_unit_migration import insert_actor, insert_property

Connection = psycopg.Connection[Any]
REVISION = "20270722_377"
RATE = "SELECT app.late_payment_rate_basis_points(%s, %s)"


@pytest.fixture
def owner(migrated_database_url: str) -> Iterator[tuple[Connection, UUID, UUID]]:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id = insert_actor(connection)
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        property_id = UUID(str(existing[0])) if existing else insert_property(connection, actor_id)
        yield connection, property_id, actor_id
        connection.rollback()


def test_migration_377_follows_376_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270721_376"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_settings_take_a_whole_percent_from_0_to_10(
    owner: tuple[Connection, UUID, UUID],
) -> None:
    connection, property_id, actor_id = owner
    day = today(connection, property_id)
    for offset, value in enumerate((0, 500, 1000), start=1):
        on = day + timedelta(days=offset)
        connection.execute(
            SET_RULE, (property_id, "LATE_PAYMENT_PERCENT", value, on, "x", actor_id)
        )
        assert scalar(connection, RATE, (property_id, on)) == value


@pytest.mark.parametrize("value", [1001, 1100, 1500, 10000, 750, 50, 999])
def test_settings_refuse_more_than_10_percent_and_a_part_of_a_percent(
    owner: tuple[Connection, UUID, UUID], value: int
) -> None:
    connection, property_id, actor_id = owner
    on = today(connection, property_id) + timedelta(days=1)
    before = scalar(connection, RATE, (property_id, on))
    refused(
        connection,
        psycopg.errors.InvalidParameterValue,
        SET_RULE,
        (property_id, "LATE_PAYMENT_PERCENT", value, on, "x", actor_id),
    )
    assert scalar(connection, RATE, (property_id, on)) == before


def test_the_refusal_says_the_limit(owner: tuple[Connection, UUID, UUID]) -> None:
    connection, property_id, actor_id = owner
    on = today(connection, property_id) + timedelta(days=1)
    with pytest.raises(psycopg.errors.InvalidParameterValue) as caught:
        with connection.transaction():
            connection.execute(
                SET_RULE, (property_id, "LATE_PAYMENT_PERCENT", 1500, on, "x", actor_id)
            )
    answer = _refusal(caught.value)
    assert isinstance(answer, BusinessRuleInvalid)
    assert str(answer) == "The late-payment charge is a whole percent from 0 to 10"


@pytest.mark.parametrize(("saved", "read"), [(2000, 1000), (10000, 1000), (750, 700), (50, 0)])
def test_a_value_saved_before_is_read_as_at_most_10_percent_in_whole_percent(
    owner: tuple[Connection, UUID, UUID], saved: int, read: int
) -> None:
    """A row from before this migration cannot be changed (append-only): the program reads
    it as a value the charge record can hold, never as more than was saved."""
    connection, property_id, _ = owner
    on = today(connection, property_id) + timedelta(days=1)
    connection.execute(
        "ALTER TABLE app.business_rules DISABLE TRIGGER business_rules_program_range_row"
    )
    connection.execute(
        "INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason) "
        "SELECT name.id, %s, %s, 'Saved before migration 377' FROM app.business_rule_names AS name "
        "WHERE name.code = 'LATE_PAYMENT_PERCENT'",
        (saved, on),
    )
    connection.execute(
        "ALTER TABLE app.business_rules ENABLE TRIGGER business_rules_program_range_row"
    )
    assert scalar(connection, RATE, (property_id, on)) == read


def test_the_other_rules_keep_their_ranges(owner: tuple[Connection, UUID, UUID]) -> None:
    connection, property_id, actor_id = owner
    on = today(connection, property_id) + timedelta(days=1)
    connection.execute(SET_RULE, (property_id, "RENT_DUE_DAY", 28, on, "x", actor_id))
    refused(
        connection,
        psycopg.errors.InvalidParameterValue,
        SET_RULE,
        (property_id, "RENT_DUE_DAY", 29, on + timedelta(days=1), "x", actor_id),
    )
