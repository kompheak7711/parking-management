"""Attendance, overtime and QR check-in on the real database (migration 20270502_302).

PR-HR-050..068: the daily sheet and its fixes, the weekly plan, overtime asked before it is
worked and approved by someone else, the staff bot's phone scan and the caretaker's card scan,
and the month lock once the payroll is sent. Days not worked and approved overtime reach the
payroll list.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from test_hr_employees_migration import (
    HrDatabase,
    add_employee,
    job_id,
    make_hr_database,
    refused,
    run,
    step,
)
from test_hr_payroll_migration import last_month, salary
from test_move_in_migration import migrated_database_url as migrated_database_url

SCAN = "SELECT app.record_staff_check_scan(%s, %s, %s::jsonb, %s, %s)"
CARD_LOOKUP = "SELECT app.hr_card_lookup(%s, %s, %s, %s)"
CARD_SCAN = "SELECT app.record_card_check_scan(%s, %s, %s::jsonb, %s, %s)"
PLACE_QR = "SELECT app.hr_new_place_qr(%s, %s, %s, %s, NULL)"
CARD_QR = "SELECT app.hr_new_card_qr(%s, %s, %s, %s, NULL)"
PIN = "SELECT app.hr_set_place_pin(%s, %s, %s, %s, %s, %s, NULL)"
DAY = "SELECT app.hr_attendance_day(%s, %s, %s)"
WEEK = "SELECT app.hr_attendance_week(%s, %s, %s)"
MONTH = "SELECT app.hr_attendance_month(%s, %s, %s)"
ENTRY = "SELECT app.hr_attendance_entry(%s, %s::jsonb, %s, NULL)"
PLAN = "SELECT app.hr_plan_day(%s, %s::jsonb, %s, NULL)"
ASK_OT = "SELECT app.hr_request_overtime(%s, %s::jsonb, %s, NULL)"
DECIDE_OT = "SELECT app.hr_decide_overtime(%s, %s, %s::jsonb, %s, NULL)"
READ_OT = "SELECT app.hr_overtime_read(%s, %s, %s)"
ACCEPT = "SELECT app.hr_accept_scan(%s, %s, %s, %s, NULL)"
PHOTO = "SELECT app.hr_scan_photo_file(%s, %s, %s)"
GUARD_POST = (11.5564, 104.9282)
FAR_AWAY = (11.5664, 104.9282)  # about 1.1 km north


@pytest.fixture(scope="module")
def att_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_hr_att")


def zone(db: HrDatabase) -> ZoneInfo:
    name = run(
        db.owner_url, "SELECT timezone_name FROM app.properties WHERE id = %s", db.property_id
    )
    return ZoneInfo(str(name))


def at(db: HrDatabase, day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), tzinfo=zone(db))


def working_days(start: date, count: int, step_days: int = 1) -> list[date]:
    """The next days from start (moving by step_days) that are not Sunday, the usual day off."""
    found: list[date] = []
    day = start
    while len(found) < count:
        if day.isoweekday() != 7:
            found.append(day)
        day += timedelta(days=step_days)
    return found


def call(db: HrDatabase, sql: str, *params: Any) -> Any:
    return run(db.runtime_url, sql, *params)


def do(db: HrDatabase, sql: str, *params: Any) -> None:
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(sql, params)


def place(db: HrDatabase, code: str) -> uuid.UUID:
    found = run(db.owner_url, "SELECT id FROM app.attendance_places WHERE code = %s", code)
    return uuid.UUID(str(found))


def link(db: HrDatabase, employee: uuid.UUID, telegram: int, role: str = "CLEANER") -> None:
    step(db, employee, "TELEGRAM_LINK", telegram_user_id=telegram, report_role=role, reason="Test")


def scan(
    db: HrDatabase,
    telegram: int,
    mode: str,
    qr: str,
    when: datetime,
    spot: tuple[float, float] | None = GUARD_POST,
    status: str = "OK",
) -> dict[str, Any]:
    body: dict[str, Any] = {"mode": mode, "qr": qr, "location": {"status": status}}
    if spot is not None:
        body["location"] |= {"latitude": spot[0], "longitude": spot[1]}
    result = call(db, SCAN, db.property_id, telegram, json.dumps(body), when, db.bot)
    assert isinstance(result, dict)
    return result


def person(day: dict[str, Any], employee: uuid.UUID) -> dict[str, Any]:
    return next(row for row in day["people"] if row["employee_id"] == str(employee))


def test_phone_scans_follow_the_rules(att_database: HrDatabase) -> None:
    db = att_database
    guard = place(db, "GUARD_POST")
    day = working_days(db.today - timedelta(days=3), 1, -1)[0]
    worker = add_employee(db, name_en="Sample Guard", name_km="គំរូ យាម")
    late = add_employee(db, name_en="Sample Late", name_km="គំរូ យឺត")
    nobody_in = add_employee(db, name_en="Sample Out", name_km="គំរូ ចេញ")

    # Only the Owner makes the printed QR; the code text comes back once.
    refused(db.runtime_url, "42501", PLACE_QR, db.property_id, guard, "First print", db.manager)
    qr = str(call(db, PLACE_QR, db.property_id, guard, "First print", db.owner))
    assert qr.startswith("CHETANA-P-")
    stored = run(
        db.owner_url,
        "SELECT count(*) FROM app.attendance_place_qr_codes WHERE code_sha256 = sha256(%s)",
        qr.encode(),
    )
    assert stored == 1

    # The bot is a service actor; a person cannot call the scan.
    refused(
        db.runtime_url,
        "42501",
        SCAN,
        db.property_id,
        7001,
        json.dumps({"mode": "IN", "qr": qr}),
        at(db, day, "06:35"),
        db.owner,
    )
    assert scan(db, 7001, "IN", qr, at(db, day, "06:35"))["reason"] == "NOT_LINKED"
    link(db, worker, 7001)
    link(db, late, 7002)
    link(db, nobody_in, 7003)
    assert scan(db, 7001, "SIDEWAYS", qr, at(db, day, "06:35"))["reason"] == "BAD_SCAN"
    off = scan(db, 7001, "IN", qr, at(db, day, "06:35"), None, "OFF")
    assert off == {"ok": False, "reason": "LOCATION_OFF", "reply_key": "check_refused_location_off"}
    assert scan(db, 7001, "IN", "CHETANA-P-nothing", at(db, day, "06:35"))["reason"] == (
        "QR_UNKNOWN"
    )
    early = scan(db, 7001, "IN", qr, at(db, day, "05:59"))
    assert early["reason"] == "TOO_EARLY"
    assert early["shift_starts_at"] is not None

    # Without a pin the scan is kept but shows Needs check.
    first = scan(db, 7002, "IN", qr, at(db, day, "06:50"))
    assert first["ok"] is True
    assert first["needs_check"] is True
    assert first["reply_key"] == "check_in_needs_check"
    assert first["late_minutes"] == 20
    assert first["distance_m"] is None

    refused(db.runtime_url, "42501", PIN, db.property_id, guard, *GUARD_POST, "Set", db.manager)
    do(db, PIN, db.property_id, guard, *GUARD_POST, "Owner stood at the post", db.owner)
    came = scan(db, 7001, "IN", qr, at(db, day, "06:35"))
    assert came["ok"] is True
    assert came["reply_key"] == "check_in_ok"
    assert came["work_date"] == str(day)
    assert came["distance_m"] == 0
    assert came["needs_check"] is False
    assert came["late_minutes"] is None
    assert scan(db, 7001, "IN", qr, at(db, day, "06:40"))["reason"] == "ALREADY_IN"
    went = scan(db, 7001, "OUT", qr, at(db, day, "15:40"), FAR_AWAY)
    assert went["ok"] is True
    assert went["reply_key"] == "check_out_ok"
    assert went["needs_check"] is True
    assert went["distance_m"] > 1000
    assert scan(db, 7003, "OUT", qr, at(db, day, "15:40"))["reason"] == "NOT_CHECKED_IN"

    # A new print stops the old QR at once.
    newer = str(call(db, PLACE_QR, db.property_id, guard, "Old QR torn", db.owner))
    assert scan(db, 7003, "IN", qr, at(db, day, "06:30"))["reason"] == "QR_REPLACED"
    assert scan(db, 7003, "IN", newer, at(db, day, "06:30"))["ok"] is True

    sheet = call(db, DAY, db.property_id, day, db.manager)
    row = person(sheet, worker)
    assert row["status"] == "WORKED"
    assert row["source"] == "QR_PHONE"
    assert [item["direction"] for item in row["scans"]] == ["IN", "OUT"]
    assert [item["needs_check"] for item in row["scans"]] == [False, True]
    assert person(sheet, late)["late_minutes"] == 20

    # Someone else accepts a Needs check scan, once.
    out_scan = went["scan_id"]
    refused(db.runtime_url, "42501", ACCEPT, db.property_id, out_scan, "ok", db.staff)
    do(db, ACCEPT, db.property_id, out_scan, "Was at the shop next door", db.manager)
    refused(db.runtime_url, "55000", ACCEPT, db.property_id, out_scan, "again", db.manager)
    row = person(call(db, DAY, db.property_id, day, db.manager), worker)
    assert row["scans"][1]["accepted"] is True
    assert row["scans"][1]["needs_check"] is False

    # History is never typed over.
    with psycopg.connect(db.owner_url) as connection, pytest.raises(psycopg.Error):
        connection.execute("UPDATE app.attendance_scans SET needs_check = false")


def test_night_shift_crosses_midnight(att_database: HrDatabase) -> None:
    db = att_database
    guard = place(db, "GUARD_POST")
    qr = str(call(db, PLACE_QR, db.property_id, guard, "Night test", db.owner))
    day = working_days(db.today - timedelta(days=3), 1, -1)[0]
    night = add_employee(db, name_en="Sample Night", name_km="គំរូ យប់", shift_code="NIGHT")
    sleepy = add_employee(db, name_en="Sample Sleepy", name_km="គំរូ ងងុយ", shift_code="NIGHT")
    link(db, night, 7011)
    link(db, sleepy, 7012)

    came = scan(db, 7011, "IN", qr, at(db, day, "22:20"))
    assert came["work_date"] == str(day)
    assert came["reply_key"] == "check_in_ok"
    went = scan(db, 7011, "OUT", qr, at(db, day + timedelta(days=1), "07:35"))
    assert went["ok"] is True
    assert went["work_date"] == str(day)

    # After midnight, a late check-in still belongs to the shift that began the day before.
    late = scan(db, 7012, "IN", qr, at(db, day + timedelta(days=1), "00:30"))
    assert late["work_date"] == str(day)
    assert late["reply_key"] == "check_in_late"
    assert late["late_minutes"] == 120


def test_card_scan_needs_reason_and_photo(att_database: HrDatabase) -> None:
    db = att_database
    day = working_days(db.today - timedelta(days=2), 1, -1)[0]
    caretaker = add_employee(
        db, name_en="Sample Caretaker", name_km="គំរូ អ្នកថែ", job_title_id=job_id(db, "CARETAKER")
    )
    no_phone = add_employee(db, name_en="Sample NoPhone", name_km="គំរូ គ្មានទូរស័ព្ទ")
    cleaner = add_employee(db, name_en="Sample Cleaner", name_km="គំរូ អ្នកសម្អាត")
    link(db, caretaker, 7021, "CARETAKER")
    link(db, cleaner, 7022)

    refused(db.runtime_url, "42501", CARD_QR, db.property_id, no_phone, "First card", db.staff)
    lost = str(call(db, CARD_QR, db.property_id, no_phone, "First card", db.manager))
    card = str(call(db, CARD_QR, db.property_id, no_phone, "Card lost", db.manager))
    own = str(call(db, CARD_QR, db.property_id, caretaker, "First card", db.manager))
    assert card.startswith("CHETANA-E-")
    shown = call(
        db, "SELECT app.hr_employee_card(%s, %s, %s)", db.property_id, no_phone, db.manager
    )
    assert [item["number"] for item in shown["cards"]] == [2, 1]
    assert shown["cards"][0]["reason"] == "Card lost"
    assert shown["works"] is True
    refused(
        db.runtime_url,
        "42501",
        "SELECT app.hr_employee_card(%s, %s, %s)",
        db.property_id,
        no_phone,
        db.staff,
    )

    def lookup(telegram: int, code: str) -> dict[str, Any]:
        found = call(db, CARD_LOOKUP, db.property_id, telegram, code, db.bot)
        assert isinstance(found, dict)
        return found

    assert lookup(7022, card)["reason"] == "NOT_CARETAKER"
    assert lookup(7021, "CHETANA-E-nothing")["reason"] == "CARD_UNKNOWN"
    assert lookup(7021, lost)["reason"] == "CARD_STOPPED"
    assert lookup(7021, own)["reason"] == "OWN_CARD"
    seen = lookup(7021, card)
    assert seen["ok"] is True
    assert seen["name_en"] == "Sample NoPhone"

    photo = {
        "sha256": "a" * 64,
        "byte_size": 52000,
        "media_type": "image/jpeg",
        "storage_key": "hr/card-photos/sample-0001.jpg",
    }

    def card_scan(when: datetime, **body: Any) -> dict[str, Any]:
        form = {"mode": "IN", "card": card, "reason": "PHONE_BROKEN", "photo": photo} | body
        result = call(db, CARD_SCAN, db.property_id, 7021, json.dumps(form), when, db.bot)
        assert isinstance(result, dict)
        return result

    when = at(db, day, "06:35")
    assert card_scan(when, photo=None)["reason"] == "NEED_PHOTO"
    assert card_scan(when, reason="OTHER")["reason"] == "NEED_REASON"
    assert card_scan(when, photo=photo | {"sha256": "bad"})["reason"] == "NEED_PHOTO"
    done = card_scan(when)
    assert done["ok"] is True
    assert done["employee_id"] == str(no_phone)
    assert done["reply_key"] == "check_in_ok"
    # A refused card scan keeps no photo row.
    again = card_scan(at(db, day, "06:40"), photo=photo | {"storage_key": "hr/card-photos/x-2.jpg"})
    assert again["reason"] == "ALREADY_IN"
    kept = run(
        db.owner_url,
        "SELECT count(*) FROM app.stored_files WHERE storage_key LIKE 'hr/card-photos/%%'",
    )
    assert kept == 1

    row = person(call(db, DAY, db.property_id, day, db.manager), no_phone)
    assert row["source"] == "QR_CARD"
    assert row["scans"][0]["scanned_by_en"] == "Sample Caretaker"
    assert row["scans"][0]["has_photo"] is True
    refused(db.runtime_url, "42501", PHOTO, db.property_id, done["scan_id"], db.staff)
    file = call(db, PHOTO, db.property_id, done["scan_id"], db.manager)
    assert file["storage_key"] == photo["storage_key"]

    # The daily job lists old photos (none yet) and records each removal.
    refused(db.runtime_url, "42501", "SELECT app.hr_photos_due(%s, %s)", db.property_id, db.owner)
    assert call(db, "SELECT app.hr_photos_due(%s, %s)", db.property_id, db.bot) == []
    file_id = run(
        db.owner_url,
        "SELECT photo_file_id FROM app.attendance_scans WHERE id = %s",
        done["scan_id"],
    )
    do(db, "SELECT app.hr_record_photo_removal(%s, %s, %s)", db.property_id, file_id, db.bot)
    refused(db.runtime_url, "22023", PHOTO, db.property_id, done["scan_id"], db.manager)


def test_sheet_plan_and_overtime(att_database: HrDatabase) -> None:
    db = att_database
    worker = add_employee(db, name_en="Sample Sheet", name_km="គំរូ តារាង")
    past = working_days(db.today - timedelta(days=1), 1, -1)[0]
    entry = {
        "employee_id": str(worker),
        "work_date": str(past),
        "status": "WORKED",
        "check_in": "06:30",
        "check_out": "15:30",
        "reason": "Phone broken",
    }
    refused(db.runtime_url, "42501", ENTRY, db.property_id, json.dumps(entry), db.staff)
    refused(
        db.runtime_url,
        "22023",
        ENTRY,
        db.property_id,
        json.dumps(entry | {"reason": None}),
        db.manager,
    )
    refused(
        db.runtime_url,
        "22023",
        ENTRY,
        db.property_id,
        json.dumps(entry | {"work_date": str(db.today + timedelta(days=1))}),
        db.manager,
    )
    first = call(db, ENTRY, db.property_id, json.dumps(entry), db.manager)
    fixed = call(
        db,
        ENTRY,
        db.property_id,
        json.dumps(entry | {"status": "LEAVE_SICK", "reason": "Was sick, said later"}),
        db.manager,
    )
    assert first != fixed
    row = person(call(db, DAY, db.property_id, past, db.manager), worker)
    assert row["status"] == "LEAVE_SICK"
    assert row["fixed"] is True
    assert row["check_in_at"] is None

    # The weekly plan: a day off on a usual working day.
    ahead = working_days(db.today + timedelta(days=2), 2)
    do(
        db,
        PLAN,
        db.property_id,
        json.dumps({"employee_id": str(worker), "work_date": str(ahead[1]), "reason": "Swap"}),
        db.manager,
    )
    week = call(db, WEEK, db.property_id, ahead[1], db.manager)
    days = next(item for item in week["people"] if item["employee_id"] == str(worker))["days"]
    planned = next(item for item in days if item["work_date"] == str(ahead[1]))
    assert planned["day_off"] is True
    assert planned["planned"] is True

    # Overtime is asked before it is worked and approved by someone else.
    ask = {
        "employee_id": str(worker),
        "work_date": str(ahead[0]),
        "starts_at": "18:00",
        "ends_at": "23:00",
        "reason": "Big check-out day",
    }
    refused(
        db.runtime_url,
        "22023",
        ASK_OT,
        db.property_id,
        json.dumps(ask | {"work_date": str(past)}),
        db.manager,
    )
    refused(db.runtime_url, "42501", ASK_OT, db.property_id, json.dumps(ask), db.staff)
    overtime = call(db, ASK_OT, db.property_id, json.dumps(ask), db.manager)
    approve = json.dumps({"decision": "APPROVED"})
    refused(db.runtime_url, "42501", DECIDE_OT, db.property_id, overtime, approve, db.manager)
    do(db, DECIDE_OT, db.property_id, overtime, approve, db.owner)
    refused(db.runtime_url, "55000", DECIDE_OT, db.property_id, overtime, approve, db.owner)
    second = call(
        db,
        ASK_OT,
        db.property_id,
        json.dumps(ask | {"starts_at": "05:00", "ends_at": "06:00"}),
        db.manager,
    )
    refused(
        db.runtime_url,
        "22023",
        DECIDE_OT,
        db.property_id,
        second,
        json.dumps({"decision": "REFUSED"}),
        db.owner,
    )
    do(
        db,
        DECIDE_OT,
        db.property_id,
        second,
        json.dumps({"decision": "REFUSED", "reason": "Not needed"}),
        db.owner,
    )
    listed = call(db, READ_OT, db.property_id, ahead[0], db.manager)["requests"]
    approved = next(item for item in listed if item["request_id"] == str(overtime))
    assert approved["overtime_number"].startswith("OT")
    assert (approved["normal_hours"], approved["night_hours"]) == (4, 1)
    assert approved["counts"] is True
    declined = next(item for item in listed if item["request_id"] == str(second))
    assert (declined["normal_hours"], declined["night_hours"]) == (1, 0)
    assert declined["counts"] is False


def test_payroll_takes_the_sheet_and_locks_the_month(att_database: HrDatabase) -> None:
    db = att_database
    month = last_month(db.today)
    worker = add_employee(
        db,
        name_en="Sample Payroll",
        name_km="គំរូ ប្រាក់ខែ",
        start_date=str(month - timedelta(days=40)),
        pay=salary(31000),
    )
    absent, unpaid, sick, extra, spare = working_days(month, 5)
    for day, status in ((absent, "ABSENT"), (unpaid, "LEAVE_UNPAID"), (sick, "LEAVE_SICK")):
        do(
            db,
            ENTRY,
            db.property_id,
            json.dumps(
                {
                    "employee_id": str(worker),
                    "work_date": str(day),
                    "status": status,
                    "reason": "Sample",
                }
            ),
            db.manager,
        )
    # Overtime of a past month cannot be asked any more, so it is written straight in here.
    with psycopg.connect(db.owner_url) as connection:
        request = connection.execute(
            "INSERT INTO app.overtime_requests (property_id, overtime_number, employee_id, "
            "work_date, starts_at, ends_at, reason, created_by) "
            "VALUES (%s, 'OT99000001', %s, %s, %s, %s, 'Sample', %s) RETURNING id",
            (
                db.property_id,
                worker,
                extra,
                at(db, extra, "18:00"),
                at(db, extra, "23:00"),
                db.manager,
            ),
        ).fetchone()
        assert request is not None
        connection.execute(
            "INSERT INTO app.overtime_decisions (overtime_request_id, decision, decided_by) "
            "VALUES (%s, 'APPROVED', %s)",
            (request[0], db.owner),
        )

    summary = call(db, MONTH, db.property_id, month, db.manager)
    mine = next(item for item in summary["people"] if item["employee_id"] == str(worker))
    assert (mine["days_absent"], mine["leave_unpaid"], mine["leave_sick"]) == (1, 1, 1)
    assert (mine["overtime_hours"], mine["overtime_night_hours"]) == (4, 1)
    assert summary["locked"] is False

    payroll = call(
        db, "SELECT app.hr_make_payroll(%s, %s, %s, NULL)", db.property_id, month, db.accountant
    )
    with psycopg.connect(db.owner_url) as connection:
        lines: dict[str, int] = dict(
            connection.execute(
                "SELECT component_code, amount_usd_cents FROM app.payroll_lines "
                "WHERE payroll_run_id = %s AND employee_id = %s",
                (payroll, worker),
            ).fetchall()
        )
    days = ((month.replace(day=28) + timedelta(days=4)).replace(day=1) - month).days
    cut = (Decimal(2 * 31000) / days).quantize(Decimal(1), ROUND_HALF_UP)
    hourly = Decimal(31000) / 208
    overtime = (hourly * (4 * 15000 + 1 * 20000) / 10000).quantize(Decimal(1), ROUND_HALF_UP)
    assert lines == {"BASE_SALARY": 31000, "DAYS_NOT_WORKED": int(cut), "OVERTIME": int(overtime)}

    # Once sent for approval the month's sheet is locked.
    link(db, worker, 7031)
    qr = str(call(db, PLACE_QR, db.property_id, place(db, "OFFICE"), "Office QR", db.owner))
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            "SELECT app.hr_payroll_step(%s, %s, 'SEND', '{}'::jsonb, %s, NULL)",
            (db.property_id, payroll, db.accountant),
        )
    assert call(db, MONTH, db.property_id, month, db.manager)["locked"] is True
    refused(
        db.runtime_url,
        "55000",
        ENTRY,
        db.property_id,
        json.dumps(
            {
                "employee_id": str(worker),
                "work_date": str(spare),
                "status": "ABSENT",
                "reason": "Late fix",
            }
        ),
        db.manager,
    )
    assert scan(db, 7031, "IN", qr, at(db, spare, "06:35"))["reason"] == "MONTH_LOCKED"


def test_the_api_calls_only_runtime_functions_with_their_arguments(
    att_database: HrDatabase,
) -> None:
    from property_rental.hr_api import FUNCTIONS, PostgresHrFlow

    db = att_database
    with psycopg.connect(db.owner_url) as connection:
        found: dict[str, int] = dict(
            connection.execute(
                "SELECT proc.proname::text, proc.pronargs::integer FROM pg_catalog.pg_proc AS proc "
                "WHERE proc.pronamespace = 'app'::regnamespace AND proc.proname = ANY(%s) "
                "AND has_function_privilege('prm_runtime', proc.oid, 'EXECUTE')",
                (list(FUNCTIONS),),
            ).fetchall()
        )
    assert found == FUNCTIONS
    choices = PostgresHrFlow(db.runtime_url).call("hr_choices", (db.property_id, db.manager))
    assert isinstance(choices, dict)
