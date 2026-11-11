"""The Property's clock for the relay while the office is away (migration 20270711_383, DL-213).

Owner (11 Nov 2026): the Customer bot and the Staff bot answer by themselves while the office app
is closed. The relay offers the visit days and move-in months from the Property's own date, so the
office sends it the Property's time zone and its distance from UTC.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import refused

CLOCK = "SELECT app.telegram_offline_clock(%s, %s)"


@pytest.fixture(scope="module")
def clock_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_clock")


def test_the_clock_is_the_propertys_time_zone_and_offset(clock_database: HrDatabase) -> None:
    db = clock_database
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT timezone_name, round(extract(epoch FROM timezone(timezone_name, now()) "
            "- timezone('UTC', now())) / 60)::integer FROM app.properties WHERE id = %s",
            (db.property_id,),
        ).fetchone()
    assert row is not None
    clock = run(db.runtime_url, CLOCK, db.property_id, db.manager)
    assert clock == {"timezone_name": row[0], "utc_offset_minutes": row[1]}
    assert isinstance(clock["utc_offset_minutes"], int)


def test_the_clock_is_behind_the_telegram_right(clock_database: HrDatabase) -> None:
    db = clock_database
    refused(db.runtime_url, "42501", CLOCK, db.property_id, db.staff)
    refused(db.runtime_url, "22023", CLOCK, uuid.uuid4(), db.manager)
