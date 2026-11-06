"""Staff bot daily checklists, patrol rounds and the 18:00 summary (migration 20270623_334, DL-177).

Owner rules (24-25 Oct 2026 staff checklists, staff forms mock-up v14): Cleaning daily check,
Caretaker shift check (one per shift, the shift from HR) and Technical daily check; each task
Done or Not done; caretakers send each patrol round; at 18:00 the Authorizers get one summary.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from test_hr_attendance_migration import link
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_staff_meter_readings_migration import send
from test_telegram_staff_reports_migration import file

CHECKLIST = "SELECT app.telegram_staff_checklist(%s, %s, %s::jsonb, %s::jsonb, %s)"
PATROL = "SELECT app.telegram_staff_patrol(%s, %s, %s::jsonb, %s::jsonb, %s)"
SUMMARY_AT = "SELECT app.staff_daily_summary_at(%s, %s, %s)"
SUMMARY = "SELECT app.telegram_staff_daily_summary(%s, %s)"
FORM_DATA = "SELECT app.telegram_staff_form_data(%s, %s)"

DANE, ENG_TAY, KHEN, PICH, BOSS = 8850001, 8850002, 8850003, 8850004, 8850005
ZONE = ZoneInfo("Asia/Phnom_Penh")
SHIFT_STARTS = {"MORNING": "06:30", "AFTERNOON": "14:30", "NIGHT": "22:30"}


def shift_now() -> tuple[str, date]:
    """A shift whose time holds this moment, and the day it started on."""
    now = datetime.now(ZONE)
    clock = now.time()
    if time(6, 30) <= clock < time(14, 30):
        return "MORNING", now.date()
    if time(14, 30) <= clock < time(22, 30):
        return "AFTERNOON", now.date()
    return "NIGHT", now.date() if clock >= time(22, 30) else now.date() - timedelta(days=1)


def other_day(day: date) -> int:
    """A usual day off that is not ``day`` (nor the day before)."""
    return (day.isoweekday() + 2) % 7 + 1


@pytest.fixture(scope="module")
def checklists_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_checklists")


@pytest.fixture(scope="module")
def people(checklists_database: HrDatabase) -> dict[str, Any]:
    db = checklists_database
    shift, shift_day = shift_now()
    off = other_day(shift_day)
    ids = {
        "dane": add_employee(db, name_en="Yon Dane", name_km="យ៉ន់ ដានេ", usual_day_off=off),
        "engtay": add_employee(db, name_en="Chea Eng Tay", name_km="ជា អេងតាយ", usual_day_off=off),
        "khen": add_employee(
            db,
            name_en="Son Sokhen",
            name_km="សន សុខខេន",
            job_title_id=job_id(db, "TECHNICIAN"),
            usual_day_off=off,
        ),
        "pich": add_employee(
            db,
            name_en="Pich Pheakdey",
            name_km="ពេជ ភក្ដី",
            job_title_id=job_id(db, "CARETAKER"),
            shift_code=shift,
            usual_day_off=off,
        ),
        "boss": add_employee(db, name_en="Kuy Sopheak", name_km="គុយ សុភ័ក្រ", usual_day_off=off),
    }
    link(db, ids["dane"], DANE, "CLEANER")
    link(db, ids["engtay"], ENG_TAY, "CLEANER")
    link(db, ids["khen"], KHEN, "TECHNICIAN")
    link(db, ids["pich"], PICH, "CARETAKER")
    link(db, ids["boss"], BOSS, "AUTHORIZER")
    # A version 2 of the caretaker list whose first round is the start of each shift, so a
    # round is always due while the shift runs.
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            """
            INSERT INTO app.staff_checklists (code, version, kind, name_km, extras, patrol_times,
                patrol_places, sort_order)
            SELECT code, 2, kind, name_km, extras, %s::jsonb, patrol_places, sort_order
            FROM app.staff_checklists WHERE code = 'CARETAKER' AND version = 1
            """,
            (
                json.dumps(
                    {
                        code: [start, "23:59" if code != "NIGHT" else "06:00"]
                        for code, start in SHIFT_STARTS.items()
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO app.staff_checklist_items (checklist_id, item_key, section_number,
                section_km, sort_order, text_km, iso_days, months, month_days, shifts, asks_floor)
            SELECT two.id, item.item_key, item.section_number, item.section_km, item.sort_order,
                item.text_km, item.iso_days, item.months, item.month_days, item.shifts,
                item.asks_floor
            FROM app.staff_checklist_items AS item
            JOIN app.staff_checklists AS one ON one.id = item.checklist_id AND one.version = 1
            JOIN app.staff_checklists AS two ON two.code = one.code AND two.version = 2
            WHERE one.code = 'CARETAKER'
            """
        )
    return {"ids": ids, "shift": shift, "shift_day": shift_day}


def due(db: HrDatabase, code: str, day: date, shift: str | None = None) -> list[str]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT item.item_key FROM app.staff_checklist_items AS item "
            "JOIN app.staff_live_checklists() AS checklist ON checklist.id = item.checklist_id "
            "WHERE checklist.code = %s AND app.staff_item_due(item, %s, %s) "
            "ORDER BY item.sort_order",
            (code, day, shift),
        ).fetchall()
    return [str(row[0]) for row in rows]


def answers(keys: list[str], *bad: str) -> dict[str, str]:
    return {key: "NOT_OK" if key in bad else "OK" for key in keys}


def test_the_forms_show_the_checklists_and_each_persons_state(
    checklists_database: HrDatabase, people: dict[str, Any]
) -> None:
    db = checklists_database
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    assert isinstance(data, dict)
    lists = {row["code"]: row for row in data["choices"]["checklists"]}
    assert list(lists) == ["CLEAN_BUILDING", "CLEAN_HOUSE", "CARETAKER", "TECHNICAL"]
    assert [row["k"] for row in lists["CLEAN_BUILDING"]["items"]] == due(
        db, "CLEAN_BUILDING", db.today
    )
    assert lists["CARETAKER"]["patrols"]["NIGHT"] == ["22:30", "06:00"]
    assert [place["k"] for place in lists["CARETAKER"]["places"]] == [
        "CHETANA",
        "RENTAL",
        "PARKING",
    ]
    assert lists["CLEAN_HOUSE"]["extras"] == ["MARKET_RIEL", "PROBLEMS"]
    users = {row["id"]: row["data"] for row in data["users"]}
    assert users[PICH]["duty"] == {
        "shift": people["shift"],
        "date": people["shift_day"].isoformat(),
        "shift_km": {"MORNING": "វេនព្រឹក", "AFTERNOON": "វេនរសៀល", "NIGHT": "វេនយប់"}[
            people["shift"]
        ],
        "rounds": [],
    }
    assert "duty" not in users[DANE] and "sent" not in users[DANE]
    # Wednesday and Friday ask which floor; Monday has the bedrooms.
    wednesday = date(2026, 11, 4)
    assert due(db, "CLEAN_BUILDING", wednesday)[-1] == "b4"
    assert "b1" in due(db, "CLEAN_BUILDING", wednesday - timedelta(days=2))
    # A caretaker task only for some shifts shows only on those shifts.
    assert "g1" in due(db, "CARETAKER", wednesday, "NIGHT")
    assert "g1" not in due(db, "CARETAKER", wednesday, "MORNING")


def test_a_cleaner_sends_the_daily_check(
    checklists_database: HrDatabase, people: dict[str, Any]
) -> None:
    db = checklists_database
    keys = due(db, "CLEAN_BUILDING", db.today)
    form: dict[str, Any] = {
        "type": "CHECKLIST",
        "code": "CLEAN_BUILDING",
        "answers": answers(keys, "d2"),
        "notes": {"d2": "No water on the ground floor"},
        "extras": {"OUT_UNITS": "B204", "PROBLEMS": "", "SUPPLIES": None},
    }
    if "b4" in keys:
        form["floor"] = "3"
    sent, inbound, _ = send(db, CHECKLIST, DANE, "item-cl-01", form)
    assert sent == {
        "result": "SENT",
        "repeated": False,
        "again": False,
        "done": len(keys) - 1,
        "problems": 1,
        "total": len(keys),
    }
    again = run(
        db.runtime_url,
        CHECKLIST,
        db.property_id,
        inbound,
        json.dumps(form),
        "[]",
        db.manager,
    )
    assert again["repeated"] is True and again["problems"] == 1
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT work_date, shift_code, answers -> 'd2', extras, done_count "
            "FROM app.staff_checklist_reports WHERE inbound_event_id = %s",
            (inbound,),
        ).fetchone()
    assert row == (
        db.today,
        None,
        {"a": "NOT_OK", "note": "No water on the ground floor"},
        {"OUT_UNITS": "B204"},
        len(keys) - 1,
    )
    # Sent again the same day: kept as a new row, the newest counts.
    second = send(db, CHECKLIST, DANE, "item-cl-02", form | {"answers": answers(keys)})[0]
    assert second["again"] is True and second["problems"] == 0

    # The house list takes the market money in whole riel.
    house = due(db, "CLEAN_HOUSE", db.today)
    market = {
        "type": "CHECKLIST",
        "code": "CLEAN_HOUSE",
        "answers": answers(house),
        "extras": {"MARKET_RIEL": 85000},
    }
    assert send(db, CHECKLIST, ENG_TAY, "item-cl-03", market)[0]["result"] == "SENT"

    # Refused: the wrong person, a task missing or unknown, wrong answers and boxes.
    assert send(db, CHECKLIST, PICH, "item-cl-04", form)[0] == {
        "result": "NOT_ROLE",
        "kind": "CLEANING",
    }
    assert send(db, CHECKLIST, 8859999, "item-cl-05", form)[0] == {"result": "NOT_LINKED"}
    wrong: list[tuple[dict[str, Any], str]] = [
        ({"code": "NOPE"}, "checklist"),
        ({"answers": answers(keys[1:])}, "answers"),
        ({"answers": answers(keys) | {"zz": "OK"}}, "answers"),
        ({"answers": {key: "MAYBE" for key in keys}}, "answers"),
        ({"notes": {"zz": "x"}}, "notes"),
        ({"notes": {keys[0]: "x" * 201}}, "notes"),
        ({"extras": {"MARKET_RIEL": 5}}, "extras"),
        ({"extras": {"OUT_UNITS": 5}}, "extras"),
        ({"floor": "3"} if "b4" not in keys else {"floor": "x" * 21}, "floor"),
    ]
    for number_of, (change, reason) in enumerate(wrong):
        answer = send(db, CHECKLIST, DANE, f"item-cl-r{number_of}", form | change)[0]
        assert answer == {"result": "INVALID", "reason": reason}, change
    bad_market = market | {"extras": {"MARKET_RIEL": 1.5}}
    assert send(db, CHECKLIST, ENG_TAY, "item-cl-r9", bad_market)[0]["reason"] == "extras"
    photo = send(db, CHECKLIST, DANE, "item-cl-photo", form, [file("clean")])[0]
    assert photo == {"result": "INVALID", "reason": "no_photo"}


def test_a_caretaker_sends_the_shift_check_and_patrol_rounds(
    checklists_database: HrDatabase, people: dict[str, Any]
) -> None:
    db = checklists_database
    shift, shift_day = people["shift"], people["shift_day"]
    keys = due(db, "CARETAKER", shift_day, shift)
    form = {
        "type": "CHECKLIST",
        "code": "CARETAKER",
        "answers": answers(keys, "h2"),
        "extras": {"VISITORS": 4, "INCIDENT": "A car blocked the gate"},
        # A caretaker cannot pick another shift: HR decides.
        "shift": "NIGHT" if shift != "NIGHT" else "MORNING",
    }
    sent = send(db, CHECKLIST, PICH, "item-ct-01", form)[0]
    assert sent["result"] == "SENT" and sent["problems"] == 1
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT work_date, shift_code FROM app.staff_checklist_reports AS report "
            "JOIN app.telegram_inbound_events AS event ON event.id = report.inbound_event_id "
            "WHERE report.employee_id = %s",
            (people["ids"]["pich"],),
        ).fetchone()
    assert row == (shift_day, shift)
    # The Authorizer picks the shift.
    picked = send(db, CHECKLIST, BOSS, "item-ct-02", form | {"shift": shift})[0]
    assert picked["result"] == "SENT"
    assert send(db, CHECKLIST, BOSS, "item-ct-03", form | {"shift": None})[0] == {
        "result": "NO_SHIFT"
    }

    start = SHIFT_STARTS[shift]
    patrol: dict[str, Any] = {
        "type": "PATROL",
        "round": start,
        "places": ["CHETANA", "PARKING", "CHETANA"],
    }
    first = send(db, PATROL, PICH, "item-pt-01", patrol)[0]
    assert first["result"] == "SENT" and first["round"] == start
    done = send(db, PATROL, BOSS, "item-pt-02", patrol | {"shift": shift})[0]
    assert done == {"result": "ROUND_DONE", "round": start, "at": first["at"]}
    refused: list[tuple[dict[str, Any], str]] = [
        ({"round": "12:34"}, "round"),
        ({"places": []}, "places"),
        ({"places": ["GARDEN"]}, "places"),
    ]
    for number_of, (change, reason) in enumerate(refused):
        answer = send(db, PATROL, PICH, f"item-pt-r{number_of}", patrol | change)[0]
        assert answer == {"result": "INVALID", "reason": reason}, change
    assert send(db, PATROL, DANE, "item-pt-04", patrol)[0] == {
        "result": "NOT_ROLE",
        "kind": "CARETAKER",
    }
    with psycopg.connect(db.owner_url) as connection:
        places = connection.execute(
            "SELECT places FROM app.staff_patrol_rounds WHERE employee_id = %s",
            (people["ids"]["pich"],),
        ).fetchone()
    assert places is not None and sorted(places[0]) == ["CHETANA", "PARKING"]
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    pich = next(row["data"] for row in data["users"] if row["id"] == PICH)
    assert pich["duty"]["rounds"] == [start] and pich["sent"] == ["CARETAKER"]
    # A round that falls after the shift's next start is not due yet.
    with psycopg.connect(db.owner_url) as connection:
        at = connection.execute(
            "SELECT app.staff_round_at(%s, 'NIGHT', '06:00')", (date(2026, 11, 4),)
        ).fetchone()
    assert at is not None and at[0] == datetime(2026, 11, 5, 6, 0, tzinfo=ZONE)


def test_the_1800_summary_goes_to_the_authorizers_once(
    checklists_database: HrDatabase, people: dict[str, Any]
) -> None:
    db = checklists_database
    technical = due(db, "TECHNICAL", db.today)
    fix = {
        "type": "CHECKLIST",
        "code": "TECHNICAL",
        "answers": answers(technical, "a2"),
        "notes": {"a2": "Pump is loud"},
    }
    assert send(db, CHECKLIST, KHEN, "item-tc-01", fix)[0]["problems"] == 1
    evening = datetime.combine(db.today, time(18, 5), tzinfo=ZONE)
    with psycopg.connect(db.owner_url) as connection:
        early = connection.execute(
            SUMMARY_AT, (db.property_id, evening - timedelta(hours=1), db.bot)
        )
        assert early.fetchone() == (0,)
        connection.commit()
        sent = connection.execute(SUMMARY_AT, (db.property_id, evening, db.bot)).fetchone()
        connection.commit()
        again = connection.execute(SUMMARY_AT, (db.property_id, evening, db.bot)).fetchone()
        outbox = connection.execute(
            "SELECT chat_id, details FROM app.telegram_outbox "
            "WHERE text_code = 'staff.daily_summary'"
        ).fetchall()
    assert sent == (1,) and again == (0,)
    [(chat, details)] = outbox
    assert chat == BOSS and details["date"] == db.today.strftime("%d/%m/%Y")
    text = details["list"]
    assert "🧹 សម្អាត៖ ផ្ញើ 2/2 នាក់" in text
    assert "🔧 បច្ចេកទេស៖ ផ្ញើ 1/1 នាក់" in text
    assert "ត្រូវជួសជុល៖ ម៉ាស៊ីនបូមទឹក (សំឡេង និងសម្ពាធ) (Pump is loud)" in text
    # Dane's newest check counts: everything was done.
    assert "មិនបានធ្វើ" not in text
    # The job asks every run; the day already has its summary.
    assert run(db.runtime_url, SUMMARY, db.property_id, db.manager) == 0


def test_the_new_functions_and_tables_are_behind_their_rights(
    checklists_database: HrDatabase, people: dict[str, Any]
) -> None:
    db = checklists_database
    for sql in (CHECKLIST, PATROL):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            run(db.runtime_url, sql, db.property_id, uuid.uuid4(), "{}", "[]", db.staff)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run(db.runtime_url, SUMMARY, db.property_id, db.staff)
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(SUMMARY_AT, (db.property_id, datetime.now(ZONE), db.manager))
        connection.rollback()
        for table in (
            "staff_checklists",
            "staff_checklist_items",
            "staff_checklist_reports",
            "staff_patrol_rounds",
            "staff_summary_runs",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT 1 FROM app.{table}")
            connection.rollback()
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("UPDATE app.staff_checklist_items SET text_km = text_km")
