"""DL-236 (owner 14 Nov 2026): a Housekeeping task is given to one cleaner, who gets it and ticks
it in the Staff bot (migration 410).

The front desk gives a task still to do to a cleaner from the staff list (HR), to another, or to
nobody; the Staff bot sends the cleaner the task with Cleaned and Not cleaned; the cleaner's tap
finishes it, and the day's list names who it is given to and who finished it.
"""

from __future__ import annotations

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
from test_short_stay_booking_migration import refused

REVISION = "20270725_410"
LIST = "SELECT app.short_stay_housekeeping(%s, %s, %s)"
FINISH = "SELECT app.finish_housekeeping_task(%s, %s, %s::jsonb, %s, NULL)"
ASSIGN = "SELECT app.assign_housekeeping_task(%s, %s, %s::jsonb, %s, NULL)"
TAP = "SELECT app.telegram_staff_task_tap(%s, %s, %s, %s, %s, %s, %s)"
THIDA, MONY = 7_236_001, 7_236_002


@pytest.fixture(scope="module")
def hk_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_housekeeping_assign")


@pytest.fixture(scope="module")
def cleaners(hk_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = hk_database
    off = (db.today.isoweekday() + 2) % 7 + 1  # a usual day off that is not today
    found = {
        # A Cleaner by job with the Staff bot, a Caretaker who reports as Cleaner, a Cleaner
        # with no Telegram, and a Technician (not a cleaner).
        "thida": add_employee(
            db,
            name_en="Chan Thida",
            name_km="ចាន់ ធីតា",
            job_title_id=job_id(db, "CLEANER"),
            usual_day_off=off,
        ),
        "mony": add_employee(db, name_en="Sok Mony", name_km="សុខ មុនី", usual_day_off=off),
        "vanna": add_employee(
            db,
            name_en="Keo Vanna",
            name_km="កែវ វណ្ណា",
            job_title_id=job_id(db, "CLEANER"),
            usual_day_off=off,
        ),
        "rith": add_employee(
            db,
            name_en="Heng Rith",
            name_km="ហេង រិទ្ធ",
            job_title_id=job_id(db, "TECHNICIAN"),
            usual_day_off=off,
        ),
    }
    link(db, found["thida"], THIDA, "CLEANER")
    link(db, found["mony"], MONY, "CLEANER")
    return found


def task(db: HrDatabase, kind: str = "DAILY_CLEAN") -> tuple[str, str]:
    """A task for today on a new Unit; answers the task id and the Unit number."""
    unit = uuid.uuid4()
    number = f"HK{unit.hex[:6].upper()}"
    with psycopg.connect(db.owner_url) as connection:
        # Since C2 (DL-241) the stored status is only the condition; who holds the Unit comes
        # from its records, so a new Unit is stored ready (VACANT).
        connection.execute(
            "INSERT INTO app.units(id,property_id,unit_number,floor,unit_type,status,created_by,"
            "updated_by) VALUES (%s,%s,%s,'1','STUDIO','VACANT',%s,%s)",
            (unit, db.property_id, number, db.owner, db.owner),
        )
        made = connection.execute(
            "INSERT INTO app.housekeeping_tasks (property_id, unit_id, task_on, kind, created_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (db.property_id, unit, db.today, kind, db.owner),
        ).fetchone()
    assert made is not None
    return str(made[0]), number


def only(found: dict[str, Any], task_id: str) -> dict[str, Any]:
    return dict(next(item for item in found["tasks"] if item["task_id"] == task_id))


def give(db: HrDatabase, task_id: str, employee: uuid.UUID | None) -> dict[str, Any]:
    body = {"employee_id": None if employee is None else str(employee)}
    day = run(db.runtime_url, ASSIGN, db.property_id, task_id, json.dumps(body), db.manager)
    return only(day, task_id)


def tap(db: HrDatabase, user: int, data: str, inbound: str | None = None) -> dict[str, Any]:
    answer = run(
        db.runtime_url,
        TAP,
        db.property_id,
        inbound or uuid.uuid4().hex,
        user,
        user,
        data,
        db.bot,
        db.manager,
    )
    assert isinstance(answer, dict)
    return answer


def outbox(db: HrDatabase, chat: int) -> list[tuple[str, dict[str, Any], Any]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT text_code, details, buttons FROM app.telegram_outbox "
            "WHERE bot_code = 'STAFF' AND chat_id = %s AND text_code LIKE 'staff.task_%%' "
            "ORDER BY created_at, id",
            (chat,),
        ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def test_migration_410_follows_the_ui_v81_join_402() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270725_402"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_front_desk_gives_a_task_to_a_cleaner_from_the_staff_list(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    task_id, number = task(db)
    day = run(db.runtime_url, LIST, db.property_id, db.today, db.staff)
    first = only(day, task_id)
    assert (first["assigned_to"], first["assigned_name"], first["done_by_name"]) == (None,) * 3
    # The cleaners: Cleaner by job or by Staff bot role, with Telegram or not; no Technician.
    assert [(person["name"], person["telegram"]) for person in day["cleaners"]] == [
        ("Chan Thida", True),
        ("Keo Vanna", False),
        ("Sok Mony", True),
    ]

    given = give(db, task_id, cleaners["thida"])
    assert (given["assigned_to"], given["assigned_name"]) == (str(cleaners["thida"]), "Chan Thida")
    assert given["version"] == first["version"] + 1
    # The Staff bot tells Chan Thida, with the two buttons of a clean.
    assert outbox(db, THIDA) == [
        (
            "staff.task_given",
            {"unit": number, "task": "សម្អាតប្រចាំថ្ងៃ", "day": db.today.strftime("%d/%m/%Y")},
            [
                [
                    {"text": "✅ បានសម្អាត", "callback_data": f"hk:done:{task_id}"},
                    {"text": "❌ មិនបានសម្អាត", "callback_data": f"hk:skip:{task_id}"},
                ]
            ],
        )
    ]
    # Someone not a cleaner, an unknown person and a bad answer are refused.
    for body in (
        {"employee_id": str(cleaners["rith"])},
        {"employee_id": str(uuid.uuid4())},
        {"employee_id": "not a person"},
        {"employee_id": str(cleaners["thida"]), "note": "x"},
    ):
        refused(
            db.runtime_url, "22023", ASSIGN, db.property_id, task_id, json.dumps(body), db.manager
        )
    # To a cleaner with no Telegram (no message), then to nobody; the History keeps each change.
    assert give(db, task_id, cleaners["vanna"])["assigned_name"] == "Keo Vanna"
    nobody = give(db, task_id, None)
    assert (nobody["assigned_to"], nobody["assigned_name"]) == (None, None)
    with psycopg.connect(db.owner_url) as connection:
        changes = connection.execute(
            "SELECT previous_state ->> 'assigned_to', resulting_state ->> 'assigned_to' "
            "FROM app.audit_events WHERE action = 'short_stay.task_assigned' "
            "AND entity_id = %s ORDER BY occurred_at",
            (task_id,),
        ).fetchall()
    assert changes == [
        (None, str(cleaners["thida"])),
        (str(cleaners["thida"]), str(cleaners["vanna"])),
        (str(cleaners["vanna"]), None),
    ]
    assert len(outbox(db, THIDA)) == 1

    # Anyone with the housekeeping right still finishes it in the app; then it is given no more.
    done = only(run(db.runtime_url, FINISH, db.property_id, task_id, "{}", db.staff), task_id)
    assert done["status"] == "DONE" and done["done_by_name"] is not None
    assert "already done" in refused(
        db.runtime_url,
        "55000",
        ASSIGN,
        db.property_id,
        task_id,
        json.dumps({"employee_id": str(cleaners["thida"])}),
        db.manager,
    )


def test_the_cleaner_ticks_the_task_in_the_staff_bot(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    clean, clean_unit = task(db, "CHANGE_OVER")
    skipped, skipped_unit = task(db)
    give(db, clean, cleaners["thida"])
    give(db, skipped, cleaners["thida"])
    before = len(outbox(db, THIDA))

    # Sok Mony may not tick Chan Thida's task; a strange button is not a task.
    assert tap(db, MONY, f"hk:done:{clean}")["result"] == "NOT_YOURS"
    assert tap(db, THIDA, "hk:what:x")["result"] == "NOT_A_TASK"

    # Cleaned: the task is done and names Chan Thida; the same tap again answers nothing new.
    inbound = uuid.uuid4().hex
    assert tap(db, THIDA, f"hk:done:{clean}", inbound)["result"] == "DONE"
    assert tap(db, THIDA, f"hk:done:{clean}", inbound)["result"] == "CLOSED"
    finished = only(run(db.runtime_url, LIST, db.property_id, db.today, db.manager), clean)
    assert (finished["status"], finished["done_by_name"]) == ("DONE", "Chan Thida")

    # Not cleaned asks why with three reasons; a reason finishes it as not cleaned.
    assert tap(db, THIDA, f"hk:skip:{skipped}")["result"] == "ASKED_WHY"
    waiting = only(run(db.runtime_url, LIST, db.property_id, db.today, db.manager), skipped)
    assert waiting["status"] == "TO_DO"
    assert tap(db, THIDA, f"hk:no2:{skipped}")["result"] == "SKIPPED"
    not_cleaned = only(run(db.runtime_url, LIST, db.property_id, db.today, db.manager), skipped)
    assert (not_cleaned["status"], not_cleaned["note"], not_cleaned["done_by_name"]) == (
        "SKIPPED",
        "Guest did not open the door",
        "Chan Thida",
    )
    assert tap(db, THIDA, f"hk:done:{skipped}")["result"] == "CLOSED"

    answers = outbox(db, THIDA)[before:]
    assert [(code, details) for code, details, _ in answers] == [
        ("staff.task_done", {"unit": clean_unit}),
        ("staff.task_why", {"unit": skipped_unit}),
        ("staff.task_skipped", {"unit": skipped_unit}),
        ("staff.task_closed", {"unit": skipped_unit}),
    ]
    reasons = answers[1][2]
    assert [row[0]["callback_data"] for row in reasons] == [
        f"hk:no1:{skipped}",
        f"hk:no2:{skipped}",
        f"hk:no3:{skipped}",
    ]
    assert [code for code, _, _ in outbox(db, MONY)] == ["staff.task_not_yours"]
    with psycopg.connect(db.owner_url) as connection:
        audit = connection.execute(
            "SELECT resulting_state ->> 'status' FROM app.audit_events "
            "WHERE action = 'short_stay.cleaned' AND entity_id IN (%s, %s) ORDER BY occurred_at",
            (clean, skipped),
        ).fetchall()
    assert audit == [("DONE",), ("SKIPPED",)]


def test_a_room_check_is_given_without_buttons_and_cannot_be_ticked(
    hk_database: HrDatabase, cleaners: dict[str, uuid.UUID]
) -> None:
    db = hk_database
    check, _ = task(db, "ROOM_CHECK")
    give(db, check, cleaners["mony"])
    code, details, buttons = outbox(db, MONY)[-1]
    assert (code, details["task"], buttons) == ("staff.task_given", "ពិនិត្យបន្ទប់", None)
    assert tap(db, MONY, f"hk:done:{check}")["result"] == "NOT_YOURS"
