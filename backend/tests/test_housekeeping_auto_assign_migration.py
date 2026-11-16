"""DL-242 (owner 16 Nov 2026): Housekeeping tasks are given out by themselves, and the cleaner
reports every task, the Unit check too, in the Staff bot (migration 415).

Each task due today that was never given to anyone goes to the cleaner the Staff bot can reach who
has the fewest tasks today; staff may still change it. The Unit check has Unit OK (the Unit is
ready again) and Problem found (the front desk writes the problem on the booking).
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

from test_hr_attendance_migration import link
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url

REVISION = "20270804_415"
LIST = "SELECT app.short_stay_housekeeping(%s, %s, %s)"
ASSIGN = "SELECT app.assign_housekeeping_task(%s, %s, %s::jsonb, %s, NULL)"
AUTO = "SELECT app.housekeeping_auto_assign(%s, %s)"
TAP = "SELECT app.telegram_staff_task_tap(%s, %s, %s, %s, %s, %s, %s)"
THIDA, MONY = 7_239_001, 7_239_002


@pytest.fixture(scope="module")
def hk_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_housekeeping_auto")


@pytest.fixture(scope="module")
def cleaners(hk_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = hk_database
    off = (db.today.isoweekday() + 2) % 7 + 1  # a usual day off that is not today
    cleaner = job_id(db, "CLEANER")
    found = {
        # Two cleaners the Staff bot reaches and one it cannot.
        "thida": add_employee(
            db, name_en="Chan Thida", name_km="ចាន់ ធីតា", job_title_id=cleaner, usual_day_off=off
        ),
        "vanna": add_employee(
            db, name_en="Keo Vanna", name_km="កែវ វណ្ណា", job_title_id=cleaner, usual_day_off=off
        ),
        "mony": add_employee(
            db, name_en="Sok Mony", name_km="សុខ មុនី", job_title_id=cleaner, usual_day_off=off
        ),
    }
    link(db, found["thida"], THIDA, "CLEANER")
    link(db, found["mony"], MONY, "CLEANER")
    return found


def task(
    db: HrDatabase, kind: str = "DAILY_CLEAN", day: datetime.date | None = None
) -> tuple[str, uuid.UUID, str]:
    """A task on a new Unit (Cleaning for a Unit check): the task, the Unit, its number."""
    unit = uuid.uuid4()
    number = f"HA{unit.hex[:6].upper()}"
    status = "CLEANING" if kind == "ROOM_CHECK" else "VACANT"
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,created_by,"
            "updated_by) VALUES (%s,%s,%s,'1','STUDIO',%s,%s,%s)",
            (unit, db.property_id, number, status, db.owner, db.owner),
        )
        made = connection.execute(
            "INSERT INTO app.housekeeping_tasks (property_id, unit_id, task_on, kind, created_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (db.property_id, unit, day or db.today, kind, db.owner),
        ).fetchone()
    assert made is not None
    return str(made[0]), unit, number


def listed(db: HrDatabase, task_id: str) -> dict[str, Any]:
    day = run(db.runtime_url, LIST, db.property_id, db.today, db.manager)
    return dict(next(item for item in day["tasks"] if item["task_id"] == task_id))


def auto(db: HrDatabase) -> int:
    given = run(db.runtime_url, AUTO, db.property_id, db.manager)
    assert isinstance(given, int)
    return given


def tap(db: HrDatabase, user: int, data: str) -> str:
    answer = run(
        db.runtime_url, TAP, db.property_id, uuid.uuid4().hex, user, user, data, db.bot, db.manager
    )
    assert isinstance(answer, dict)
    return str(answer["result"])


def outbox(db: HrDatabase, chat: int) -> list[tuple[str, dict[str, Any], Any]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT text_code, details, buttons FROM app.telegram_outbox "
            "WHERE bot_code = 'STAFF' AND chat_id = %s ORDER BY created_at, id",
            (chat,),
        ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def unit_status(db: HrDatabase, unit: uuid.UUID) -> str:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute("SELECT status FROM app.units WHERE id = %s", (unit,)).fetchone()
    assert row is not None
    return str(row[0])


def test_migration_415_follows_the_ui_v81_join_417() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270803_417"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_each_task_due_goes_by_itself_to_the_cleaner_with_the_fewest_tasks(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    made = [task(db), task(db), task(db, "ROOM_CHECK")]
    later, _, _ = task(db, day=db.today + datetime.timedelta(days=1))
    kept, _, _ = task(db)
    # Staff gave one task to a cleaner, then to nobody: it stays with nobody.
    for person in (str(cleaners["vanna"]), None):
        run(
            db.runtime_url,
            ASSIGN,
            db.property_id,
            kept,
            json.dumps({"employee_id": person}),
            db.manager,
        )

    assert auto(db) == 3
    given = [listed(db, task_id)["assigned_name"] for task_id, _, _ in made]
    # Turn by turn to the cleaner with fewest tasks, a tie by name; Keo Vanna has no Telegram.
    assert sorted(given) == ["Chan Thida", "Chan Thida", "Sok Mony"]
    assert listed(db, kept)["assigned_name"] is None
    with psycopg.connect(db.owner_url) as connection:
        tomorrow = connection.execute(
            "SELECT assigned_to FROM app.housekeeping_tasks WHERE id = %s", (later,)
        ).fetchone()
        reasons = connection.execute(
            "SELECT DISTINCT reason FROM app.audit_events "
            "WHERE action = 'short_stay.task_assigned' AND entity_id = ANY(%s::uuid[])",
            ([task_id for task_id, _, _ in made],),
        ).fetchall()
    assert tomorrow == (None,)
    assert reasons == [("Housekeeping task given to a cleaner by itself",)]
    # Each cleaner got their tasks; the Unit check comes with Unit OK and Problem found.
    sent = outbox(db, THIDA) + outbox(db, MONY)
    assert [code for code, _, _ in sent] == ["staff.task_given"] * 3
    check = made[2][0]
    assert [buttons for _, details, buttons in sent if details["task"] == "ពិនិត្យបន្ទប់"] == [
        [
            [
                {"text": "✅ បន្ទប់ល្អ", "callback_data": f"hk:ok:{check}"},
                {"text": "⚠️ មានបញ្ហា", "callback_data": f"hk:bad:{check}"},
            ]
        ]
    ]
    # Nothing is left to give; staff can still move a task to another cleaner.
    assert auto(db) == 0
    moved = made[0][0]
    to = cleaners["vanna"]
    run(
        db.runtime_url,
        ASSIGN,
        db.property_id,
        moved,
        json.dumps({"employee_id": str(to)}),
        db.manager,
    )
    assert listed(db, moved)["assigned_name"] == "Keo Vanna"


def test_the_cleaner_reports_unit_ok_and_the_unit_is_ready_again(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    check, unit, number = task(db, "ROOM_CHECK")
    clean, _, _ = task(db)
    for task_id in (check, clean):
        run(
            db.runtime_url,
            ASSIGN,
            db.property_id,
            task_id,
            json.dumps({"employee_id": str(cleaners["mony"])}),
            db.manager,
        )
    # A clean's buttons do not fit a Unit check, and the other way round.
    assert tap(db, MONY, f"hk:done:{check}") == "NOT_YOURS"
    assert tap(db, MONY, f"hk:ok:{clean}") == "NOT_YOURS"
    assert tap(db, THIDA, f"hk:ok:{check}") == "NOT_YOURS"

    assert unit_status(db, unit) == "CLEANING"
    assert tap(db, MONY, f"hk:ok:{check}") == "DONE"
    done = listed(db, check)
    assert (done["status"], done["done_by_name"], done["problem_found_at"]) == (
        "DONE",
        "Sok Mony",
        None,
    )
    assert unit_status(db, unit) == "VACANT"
    assert outbox(db, MONY)[-1][:2] == ("staff.unit_ok", {"unit": number})
    assert tap(db, MONY, f"hk:bad:{check}") == "CLOSED"


def test_problem_found_waits_for_the_front_desk(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    check, unit, number = task(db, "ROOM_CHECK")
    run(
        db.runtime_url,
        ASSIGN,
        db.property_id,
        check,
        json.dumps({"employee_id": str(cleaners["thida"])}),
        db.manager,
    )
    assert tap(db, THIDA, f"hk:bad:{check}") == "PROBLEM_FOUND"
    found = listed(db, check)
    assert (found["status"], found["problem_found_by_name"]) == ("TO_DO", "Chan Thida")
    assert found["problem_found_at"] is not None
    # The Unit stays Cleaning; Unit OK now changes nothing, the front desk finishes the check.
    assert unit_status(db, unit) == "CLEANING"
    assert tap(db, THIDA, f"hk:ok:{check}") == "PROBLEM_FOUND"
    assert listed(db, check)["status"] == "TO_DO"
    assert [code for code, _, _ in outbox(db, THIDA)[-2:]] == [
        "staff.unit_problem",
        "staff.unit_problem",
    ]
    assert outbox(db, THIDA)[-1][1] == {"unit": number}
    with psycopg.connect(db.owner_url) as connection:
        audit = connection.execute(
            "SELECT count(*) FROM app.audit_events "
            "WHERE action = 'short_stay.unit_problem_found' AND entity_id = %s",
            (check,),
        ).fetchone()
    assert audit == (1,)
