"""Owner's review of 16 Nov 2026 (migration 430): the short-stay booking page names the person.

History names the person for every step on every page (owner's rule). The booking read now gives
each History step the person who did it (or the cleaner who reported it in the Staff bot), says
when the app did a step by itself, and names who did the Unit check or found a problem.
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url

REVISION = "20270806_430"
BOOK = "SELECT app.make_short_stay_booking(%s, %s::jsonb, %s, NULL)"
READ = "SELECT app.short_stay_booking_read(%s, %s, %s)"


@pytest.fixture(scope="module")
def names_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_housekeeping_names")


def booked(db: HrDatabase) -> str:
    """A walk-in booking for tomorrow on a new Unit, made by the manager in the app."""
    unit, guest = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "default_monthly_rent_usd_cents, created_by, updated_by) "
            "VALUES (%s, %s, %s, '1', 'STUDIO', 'VACANT', 29900, %s, %s)",
            (unit, db.property_id, f"HN{unit.hex[:6].upper()}", db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, created_by, updated_by) "
            "VALUES (%s, 'Lim Dara', %s, %s)",
            (guest, db.owner, db.owner),
        )
    check_in = db.today + datetime.timedelta(days=1)
    body = {
        "unit_id": str(unit),
        "customer_id": str(guest),
        "guest_count": 1,
        "check_in_on": str(check_in),
        "check_out_on": str(check_in + datetime.timedelta(days=2)),
        "source": "WALK_IN",
    }
    return str(run(db.runtime_url, BOOK, db.property_id, json.dumps(body), db.manager))


def read(db: HrDatabase, booking: str) -> dict[str, Any]:
    found = run(db.runtime_url, READ, db.property_id, booking, db.manager)
    assert isinstance(found, dict)
    return found


def test_migration_430_follows_415() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270804_415"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_history_and_the_unit_check_name_the_person(names_database: HrDatabase) -> None:
    db = names_database
    booking = booked(db)
    cleaner = add_employee(
        db, name_en="Chan Thida", name_km="ចាន់ ធីតា", job_title_id=job_id(db, "CLEANER")
    )
    service = db.bot  # the Staff bot's service actor (no user account)
    with psycopg.connect(db.owner_url) as connection:
        manager = connection.execute(
            "SELECT display_name FROM app.user_accounts WHERE actor_id = %s", (db.manager,)
        ).fetchone()
        # A step the cleaner reported in the Staff bot (DL-242), and one the app did by itself.
        connection.execute(
            "SELECT app.short_stay_event(%s, 'UNIT_PROBLEM_FOUND', %s, NULL, %s::jsonb)",
            (booking, service, json.dumps({"employee_id": str(cleaner)})),
        )
        connection.execute(
            "SELECT app.short_stay_event(%s, 'REVIEW_ASKED', %s, NULL, '{}'::jsonb)",
            (booking, service),
        )
        # The Unit check of the stay, with the problem the cleaner found.
        unit = connection.execute(
            "SELECT unit_id FROM app.short_stay_bookings WHERE id = %s", (booking,)
        ).fetchone()
        assert manager is not None and unit is not None
        task = connection.execute(
            "INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind, "
            "created_by) VALUES (%s, %s, %s, %s, 'ROOM_CHECK', %s) RETURNING id",
            (db.property_id, unit[0], booking, db.today, db.owner),
        ).fetchone()
        assert task is not None
        connection.execute(
            "UPDATE app.housekeeping_tasks SET problem_found_at = statement_timestamp(), "
            "problem_found_by = %s, version = version + 1 WHERE id = %s",
            (cleaner, task[0]),
        )

    found = read(db, booking)
    steps = [(step["kind"], step["by_name"], step["by_app"]) for step in found["history"]]
    assert steps == [
        ("BOOKED", manager[0], False),
        ("UNIT_PROBLEM_FOUND", "Chan Thida", False),
        ("REVIEW_ASKED", None, True),
    ]
    check = found["room_check"]
    assert (check["task_id"], check["done_by_name"], check["problem_found_by_name"]) == (
        str(task[0]),
        None,
        "Chan Thida",
    )
    # Everything else the page reads is as before.
    assert found["status"] == "BOOKED" and found["nights"] == 2
    assert found["lines"] and "problems" in found and "damage_due" in found
