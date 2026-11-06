"""The Staff bot's database calls (migration 20270620_331, DL-174).

Staff join with Start and their own phone, and hear the answer; check-in and card scans go
through the Telegram jobs' account and the HR service actor; the relay gets who may open the
Staff forms. The HR rules themselves are tested in test_hr_attendance_migration.py.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from test_hr_attendance_migration import GUARD_POST, PLACE_QR, at, link, place, working_days
from test_hr_employees_migration import (
    HrDatabase,
    add_employee,
    job_id,
    make_hr_database,
    refused,
    run,
)
from test_move_in_migration import migrated_database_url as migrated_database_url

WHO = "SELECT app.telegram_staff_who(%s, %s, %s, %s)"
JOIN = "SELECT app.telegram_staff_join(%s, %s, %s, %s, NULL, %s, %s)"
CHECK = "SELECT app.telegram_staff_check(%s, %s, %s::jsonb, %s, %s, %s)"
CARD = "SELECT app.telegram_staff_card(%s, %s, %s::jsonb, %s, %s, %s)"
FORM_DATA = "SELECT app.telegram_staff_form_data(%s, %s)"
DUE = "SELECT app.telegram_staff_photos_due(%s, %s, %s)"
DECIDE = "SELECT app.hr_decide_staff_request(%s, %s, %s::jsonb, %s, NULL)"
CARD_QR = "SELECT app.hr_new_card_qr(%s, %s, %s, %s, NULL)"


@pytest.fixture(scope="module")
def staff_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_staff")


def call(db: HrDatabase, sql: str, *params: Any) -> Any:
    return run(db.runtime_url, sql, *params)


def outbox(db: HrDatabase, user: int) -> list[tuple[str, str | None]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT text_code, keyboard FROM app.telegram_outbox WHERE bot_code = 'STAFF' "
            "AND chat_id = %s ORDER BY created_at",
            (user,),
        ).fetchall()
    return [(str(code), keyboard) for code, keyboard in rows]


def test_join_answer_and_who(staff_database: HrDatabase) -> None:
    db = staff_database
    worker = add_employee(db, name_en="Yon Dane", name_km="យ៉ន់ ដានេ")
    user = 8810001
    # The jobs' account needs the Telegram rights; the HR call needs the service actor.
    refused(db.runtime_url, "42501", WHO, db.property_id, user, db.bot, db.staff)
    refused(db.runtime_url, "42501", WHO, db.property_id, user, db.owner, db.owner)
    assert call(db, WHO, db.property_id, user, db.bot, db.manager) == {
        "linked": False,
        "waiting": False,
    }
    asked = call(db, JOIN, db.property_id, user, "Dane", "+85512345678", db.bot, db.manager)
    assert asked["state"] == "WAITING"
    assert call(db, WHO, db.property_id, user, db.bot, db.manager)["waiting"] is True

    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            DECIDE,
            (
                db.property_id,
                asked["request_id"],
                json.dumps(
                    {"decision": "LINKED", "employee_id": str(worker), "roles": ["CLEANER"]}
                ),
                db.owner,
            ),
        )
    assert outbox(db, user) == [("staff.approved", "staff.open")]
    who = call(db, WHO, db.property_id, user, db.bot, db.manager)
    assert who["linked"] is True and who["name_km"] == "យ៉ន់ ដានេ"
    assert who["roles"] == ["CLEANER"]

    refused_user = 8810002
    other = call(db, JOIN, db.property_id, refused_user, "Who", None, db.bot, db.manager)
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            DECIDE,
            (
                db.property_id,
                other["request_id"],
                json.dumps({"decision": "REFUSED", "reason": "Not our staff"}),
                db.manager,
            ),
        )
    assert outbox(db, refused_user) == [("staff.refused", None)]

    # The relay list: linked staff only, with their name, roles and shift.
    refused(db.runtime_url, "42501", FORM_DATA, db.property_id, db.staff)
    data = call(db, FORM_DATA, db.property_id, db.manager)
    people = {person["id"]: person for person in data["users"]}
    assert set(people) == {user}
    assert people[user]["role"] == "STAFF"
    assert people[user]["data"]["roles"] == ["CLEANER"]
    assert people[user]["data"]["shift_code"] == "MORNING"
    assert people[user]["data"]["shift_km"]
    assert set(data["choices"]) >= {"types", "places"}


def test_check_and_card_scans_answer_in_property_time(staff_database: HrDatabase) -> None:
    db = staff_database
    guard = place(db, "GUARD_POST")
    qr = str(call(db, PLACE_QR, db.property_id, guard, "First print", db.owner))
    call(
        db,
        "SELECT app.hr_set_place_pin(%s, %s, %s, %s, %s, %s, NULL) IS NULL",
        db.property_id,
        guard,
        GUARD_POST[0],
        GUARD_POST[1],
        "Pin",
        db.owner,
    )
    day = working_days(db.today - timedelta(days=3), 1, -1)[0]
    guard_person = add_employee(db, name_en="Sample Guard", name_km="គំរូ យាម")
    caretaker = add_employee(
        db, name_en="Sample Caretaker", name_km="គំរូ អ្នកថែ", job_title_id=job_id(db, "CARETAKER")
    )
    no_phone = add_employee(db, name_en="Sample NoPhone", name_km="គំរូ គ្មានទូរស័ព្ទ")
    link(db, guard_person, 8820001)
    link(db, caretaker, 8820002, "CARETAKER")

    scan = {
        "mode": "IN",
        "qr": qr,
        "location": {"status": "OK", "latitude": GUARD_POST[0], "longitude": GUARD_POST[1]},
    }
    refused(
        db.runtime_url,
        "42501",
        CHECK,
        db.property_id,
        8820001,
        json.dumps(scan),
        at(db, day, "06:35"),
        db.bot,
        db.staff,
    )
    early = call(
        db, CHECK, db.property_id, 8820001, json.dumps(scan), at(db, day, "05:00"), db.bot,
        db.manager,
    )  # fmt: skip
    assert early["reason"] == "TOO_EARLY" and early["starts"] == "06:30"
    done = call(
        db, CHECK, db.property_id, 8820001, json.dumps(scan), at(db, day, "06:35"), db.bot,
        db.manager,
    )  # fmt: skip
    assert done["ok"] is True and done["time"] == "06:35" and done["shift_km"]
    assert done["reply_key"] == "check_in_ok"

    card = str(call(db, CARD_QR, db.property_id, no_phone, "First card", db.manager))
    photo = {
        "sha256": "b" * 64,
        "byte_size": 52000,
        "media_type": "image/jpeg",
        "storage_key": "card-photos/" + "b" * 64 + ".jpg",
    }
    form = {"mode": "IN", "card": card, "reason": "NO_PHONE", "photo": photo}
    saved = call(
        db, CARD, db.property_id, 8820002, json.dumps(form), at(db, day, "06:40"), db.bot,
        db.manager,
    )  # fmt: skip
    assert saved["ok"] is True and saved["time"] == "06:40"
    assert saved["name_km"] == "គំរូ គ្មានទូរស័ព្ទ"
    assert call(db, DUE, db.property_id, db.bot, db.manager) == []
    refused(db.runtime_url, "42501", DUE, db.property_id, db.bot, db.staff)
    assert uuid.UUID(saved["scan_id"])
