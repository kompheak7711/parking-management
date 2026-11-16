"""Migration 20270804_422 (owner 16/11/2026): the Inspections page reads the Property's move-out
inspections and the Staff bot's Unit checks in one call, behind "Read Units"."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_hr_attendance_migration import link
from test_hr_employees_migration import (
    HrDatabase,
    add_employee,
    job_id,
    make_hr_database,
    refused,
    run,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_staff_reports_migration import add_unit, file, send

REVISION = "20270804_422"
READ = "SELECT app.property_inspections_read(%s, %s)"
UNIT_CHECK = "SELECT app.telegram_staff_unit_check(%s, %s, %s::jsonb, %s::jsonb, %s)"
TECHNICIAN = 8870002


def test_migration_422_follows_430_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270806_430"
    assert scripts.get_heads() == [REVISION]
    with pytest.raises(NotImplementedError, match="forward-only"):
        revision.module.downgrade()


@pytest.fixture(scope="module")
def inspections_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_inspections_read")


def test_the_inspections_page_lists_the_unit_checks_with_their_problem_reports(
    inspections_database: HrDatabase,
) -> None:
    db = inspections_database
    empty = run(db.runtime_url, READ, db.property_id, db.manager)
    assert empty == {"as_of": str(db.today), "move_outs": [], "unit_checks": []}

    technician = add_employee(
        db,
        name_en="Son Sokhen",
        name_km="សន សុខខេន",
        job_title_id=job_id(db, "TECHNICIAN"),
        usual_day_off=db.today.isoweekday() % 7 + 1,
    )
    link(db, technician, TECHNICIAN, "TECHNICIAN")
    unit = add_unit(db, "I201")
    form: dict[str, Any] = {
        "type": "UNIT_CHECK",
        "unit_id": unit,
        "kind": "REGULAR",
        "areas": {"LIVING": "GOOD", "BEDROOM": "BROKEN", "KEYS": "MISSING"},
        "findings": {
            "BEDROOM": {"text": "Wardrobe door off", "photos": 1},
            "KEYS": {"text": "One key card missing", "photos": 1},
        },
    }
    sent = send(db, UNIT_CHECK, TECHNICIAN, "item-insp-1", form, [file("i-1"), file("i-2")])
    assert sent["result"] == "SENT"

    found = run(db.runtime_url, READ, db.property_id, db.manager)
    assert found["move_outs"] == []
    [check] = found["unit_checks"]
    assert check["unit_number"] == "I201" and check["unit_id"] == unit
    assert check["check_date"] == str(db.today) and check["kind"] == "REGULAR"
    assert check["findings"] == 2
    assert (check["checked_by_en"], check["checked_by_km"]) == ("Son Sokhen", "សន សុខខេន")
    assert sorted(report["report_number"] for report in check["reports"]) == sorted(sent["numbers"])


def test_the_inspections_read_needs_the_read_units_right(
    inspections_database: HrDatabase,
) -> None:
    db = inspections_database
    refused(db.runtime_url, "42501", READ, db.property_id, db.bot)
    refused(db.runtime_url, "42501", READ, db.property_id, uuid.uuid4())
