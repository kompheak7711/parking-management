"""The Problem report Home card and Monthly report (migration 20270511_291, DL-131).

The Home card counts open, urgent and late reports and lists each cost still waiting for a
Manager's check. The Monthly report counts one month's reports (joined ones apart), who pays,
the reports by type and place, and the repair cost by Unit and by type.
"""

from __future__ import annotations

from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_problem_report_costs_migration import LINES, check, costs, done_repair, enter
from test_problem_reports_migration import (
    ProblemDatabase,
    add,
    read,
    refused,
    run,
    type_id,
    unit_problem,
)
from test_problem_reports_migration import problem_database as problem_database

REVISION = "20270511_291"
SUMMARY = "SELECT app.problem_report_summary(%s, %s)"
MONTH = "SELECT app.problem_report_month(%s, %s, %s)"

__all__ = ["costs", "migrated_database_url", "problem_database"]


def test_migration_291_follows_the_repair_cost_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270510_290"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def summary(db: ProblemDatabase) -> dict[str, Any]:
    found = run(db.runtime_url, SUMMARY, db.property_id, db.staff)
    assert isinstance(found, dict)
    return found


def month(db: ProblemDatabase) -> dict[str, Any]:
    found = run(db.runtime_url, MONTH, db.property_id, db.manager, db.today.replace(day=1))
    assert isinstance(found, dict)
    return found


def test_the_home_card_and_the_monthly_report(costs: ProblemDatabase) -> None:
    db = costs
    before = summary(db)
    urgent = unit_problem(db, urgent=True, description="No water at all")
    add(
        db,
        db.staff,
        kind="UNIT",
        unit_id=str(db.leased_unit),
        problem_type_id=type_id(db, "WATER"),
        description="Same: no water",
        same_as=str(urgent),
    )
    repaired = done_repair(db)
    enter(db, repaired, db.staff, lines=LINES)
    now = summary(db)
    assert now["open"] == before["open"] + 1 and now["urgent"] == before["urgent"] + 1
    waiting = [item for item in now["costs_to_check"] if item["report_id"] == str(repaired)]
    assert len(waiting) == 1
    assert waiting[0]["unit_number"] == "U101"
    assert waiting[0]["totals"] == [
        {"currency": "USD", "amount_minor": 1400},
        {"currency": "KHR", "amount_minor": 40000},
    ]
    check(db, repaired, db.manager, receipt_seen=True, spent_on=str(db.today), paid_how="CASH",
          paid_from_code="1030")  # fmt: skip
    assert all(item["report_id"] != str(repaired) for item in summary(db)["costs_to_check"])

    report = month(db)
    assert report["month"] == str(db.today.replace(day=1))
    assert report["received"] >= 2 and report["joined"] >= 1
    assert report["urgent"] >= 1 and report["owner_pays"] >= 1
    assert report["done"] >= 1 and report["average_days_to_fix"] is not None
    water = next(item for item in report["by_type"] if item["code"] == "WATER")
    assert water["reports"] == report["unit_problems"]
    unit = next(item for item in report["cost_by_unit"] if item["unit_number"] == "U101")
    assert unit["parts_usd_cents"] >= 1400 and unit["outside_khr"] >= 40000
    assert any(item["code"] == "WATER" for item in report["cost_by_type"])
    assert read(db, urgent)["urgent"]
    # Staff see the Home card, not the Monthly report; a month is its first day, not later.
    refused(db.runtime_url, "42501", MONTH, db.property_id, db.staff, db.today.replace(day=1))
    refused(db.runtime_url, "22023", MONTH, db.property_id, db.manager, db.today.replace(day=2))
