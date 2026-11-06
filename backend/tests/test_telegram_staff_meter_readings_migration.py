"""Staff bot Utility reading and Meter check request (migration 20270622_333, DL-176).

Owner rules (22 Oct 2026, staff forms mock-up v14): the meter reader types each Unit's
Electricity and Water reading, no photo; a reading lower than last month or Electricity more than
300 kWh above it is flagged; the readings wait until a Manager confirms them in Utilities, and a
confirmed reading is a normal meter reading. A flag beside a Unit asks the Technical team to check
a meter.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from test_hr_attendance_migration import link
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item
from test_telegram_staff_reports_migration import add_unit, file

READINGS = "SELECT app.telegram_staff_meter_readings(%s, %s, %s::jsonb, %s::jsonb, %s)"
CHECK = "SELECT app.telegram_staff_meter_check(%s, %s, %s::jsonb, %s::jsonb, %s)"
WAITING = "SELECT app.staff_meter_readings_waiting(%s, %s)"
DECIDE = "SELECT app.decide_staff_meter_readings(%s, %s::jsonb, %s, %s)"
FORM_DATA = "SELECT app.telegram_staff_form_data(%s, %s)"

READER, CARETAKER = 8840001, 8840002


@pytest.fixture(scope="module")
def meters_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_meters")


def add_meter(db: HrDatabase, unit: str, kind: str, last: str | None) -> str:
    meter = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.utility_meters (id, unit_id, serial_number, utility_type, "
            "measurement_unit_code, installed_date, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                meter,
                unit,
                f"SN-{meter}",
                kind,
                "KWH" if kind == "ELECTRICITY" else "M3",
                db.today - timedelta(days=90),
                db.owner,
                db.owner,
            ),
        )
        if last is not None:
            connection.execute(
                "INSERT INTO app.utility_readings (id, meter_id, reading_date, reading_value, "
                "validated_at, validated_by, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s, statement_timestamp(), %s, %s, %s)",
                (
                    uuid.uuid4(),
                    meter,
                    db.today - timedelta(days=30),
                    last,
                    db.owner,
                    db.owner,
                    db.owner,
                ),
            )
    return str(meter)


def send(
    db: HrDatabase,
    sql: str,
    user: int,
    relay_id: str,
    form: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    body = item(
        relay_id,
        None,
        bot="STAFF",
        kind="form",
        telegram_user_id=user,
        chat_id=user,
        summary={"kind": "form", "media": len(files or [])},
        payload={"form": form, "role": "STAFF"},
        media=files or [],
    )
    saved = run(db.runtime_url, RECORD, db.property_id, body, db.manager)
    media = [str(media_id) for media_id in saved.get("media_ids", [])]
    answer = run(
        db.runtime_url,
        sql,
        db.property_id,
        saved["inbound_id"],
        json.dumps(form),
        json.dumps(media),
        db.manager,
    )
    assert isinstance(answer, dict)
    return answer, str(saved["inbound_id"]), media


def decide(db: HrDatabase, proposals: list[str], decision: str) -> dict[str, Any]:
    answer = run(
        db.runtime_url, DECIDE, db.property_id, json.dumps(proposals), decision, db.manager
    )
    assert isinstance(answer, dict)
    return answer


def waiting(db: HrDatabase) -> list[dict[str, Any]]:
    found = run(db.runtime_url, WAITING, db.property_id, db.manager)
    assert isinstance(found, list)
    return found


def runs(db: HrDatabase) -> int:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute("SELECT count(*) FROM app.staff_meter_reading_runs").fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture(scope="module")
def setup(meters_database: HrDatabase) -> dict[str, str]:
    db = meters_database
    reader = add_employee(
        db,
        name_en="Son Sokhen",
        name_km="សន សុខខេន",
        job_title_id=job_id(db, "TECHNICIAN"),
        usual_day_off=db.today.isoweekday() % 7 + 1,
    )
    caretaker = add_employee(
        db, name_en="Pich Pheakdey", name_km="ពេជ ភក្ដី", job_title_id=job_id(db, "CARETAKER")
    )
    link(db, reader, READER, "METER_READER")
    link(db, caretaker, CARETAKER, "CARETAKER")
    units = {number: add_unit(db, number) for number in ("A201", "A202", "A203")}
    return units | {
        "A201_E": add_meter(db, units["A201"], "ELECTRICITY", "4120"),
        "A201_W": add_meter(db, units["A201"], "WATER", "612.5"),
        "A202_E": add_meter(db, units["A202"], "ELECTRICITY", "3875"),
    }


def test_the_form_shows_the_meters_and_their_last_readings(
    meters_database: HrDatabase, setup: dict[str, str]
) -> None:
    db = meters_database
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    meters = {row["n"]: row for row in data["choices"]["meters"]}
    # A203 has no meter; A202 has no Water meter; the last reading of each type; no names.
    assert set(meters) == {"A201", "A202"}
    assert meters["A201"] == {
        "id": setup["A201"],
        "n": "A201",
        "e": {"last": 4120},
        "w": {"last": 612.5},
    }
    assert meters["A202"] == {"id": setup["A202"], "n": "A202", "e": {"last": 3875}}
    reader = next(user for user in data["users"] if user["id"] == READER)
    assert reader["data"]["roles"] == ["METER_READER"]


def test_readings_wait_for_the_manager_who_confirms_or_asks_again(
    meters_database: HrDatabase, setup: dict[str, str]
) -> None:
    db = meters_database
    first: dict[str, Any] = {"unit_id": setup["A201"], "electricity": 5000, "water": 619}
    form: dict[str, Any] = {
        "type": "METER",
        "readings": [
            first,
            {"unit_id": setup["A202"], "electricity": 3800, "water": None},
            {"unit_id": setup["A203"], "electricity": None, "water": None},
        ],
    }
    sent, inbound, _ = send(db, READINGS, READER, "item-mr-01", form)
    assert sent == {
        "result": "SENT",
        "repeated": False,
        "count": 3,
        "flagged": 2,
        "reading_date": db.today.isoformat(),
    }
    # The same form twice is saved once.
    again = run(
        db.runtime_url, READINGS, db.property_id, inbound, json.dumps(form), "[]", db.manager
    )
    assert again["repeated"] is True and again["count"] == 3
    assert runs(db) == 1

    # Only the meter reader (or an Authorizer); a wrong row refuses the whole form.
    assert send(db, READINGS, CARETAKER, "item-mr-care", form)[0] == {"result": "NOT_METER_READER"}
    assert send(db, READINGS, 8849999, "item-mr-nobody", form)[0] == {"result": "NOT_LINKED"}
    refused: dict[str, list[dict[str, Any]]] = {
        "meter": [{"unit_id": setup["A202"], "water": 5}],
        "value": [first | {"electricity": -1}],
        "unit": [first, first],
        "not_a_form": [],
        "empty": [{"unit_id": setup["A201"]}],
    }
    for number_of, (reason, bad) in enumerate(refused.items()):
        answer = send(db, READINGS, READER, f"item-mr-r{number_of}", {"readings": bad})[0]
        assert answer == {"result": "INVALID", "reason": reason}, bad
    for number_of, wrong in enumerate(("5000", 1.23456, True)):
        answer = send(
            db,
            READINGS,
            READER,
            f"item-mr-v{number_of}",
            {"readings": [first | {"electricity": wrong}]},
        )[0]
        assert answer == {"result": "INVALID", "reason": "value"}, wrong
    photo = send(db, READINGS, READER, "item-mr-photo", form, [file("meter-1")])[0]
    assert photo == {"result": "INVALID", "reason": "no_photo"}
    assert runs(db) == 1

    # The Manager sees them in Utilities, flagged.
    [run_body] = waiting(db)
    rows: dict[tuple[str, str], dict[str, Any]] = {
        (row["unit"], row["utility_type"]): row for row in run_body["readings"]
    }
    assert run_body["sent_by"] == "Son Sokhen"
    assert run_body["reading_date"] == db.today.isoformat()
    assert rows[("A201", "ELECTRICITY")]["flag"] == "HIGH"
    assert rows[("A201", "ELECTRICITY")]["last_value"] == "4120"
    assert rows[("A201", "WATER")]["flag"] is None
    assert rows[("A201", "WATER")]["reading_value"] == "619"
    assert rows[("A202", "ELECTRICITY")]["flag"] == "LOWER"
    assert all(row["already"] is False for row in rows.values())

    # Confirm A201: two normal meter readings on the day they were read.
    a201 = [rows[("A201", kind)]["proposal_id"] for kind in ("ELECTRICITY", "WATER")]
    assert decide(db, a201, "CONFIRMED") == {"decision": "CONFIRMED", "done": 2, "already": []}
    with psycopg.connect(db.owner_url) as connection:
        saved = connection.execute(
            "SELECT meter_id, reading_date, reading_value, source_kind, created_by "
            "FROM app.utility_readings WHERE reading_date = %s ORDER BY reading_value",
            (db.today,),
        ).fetchall()
    assert [(str(meter), value, kind) for meter, _, value, kind, _ in saved] == [
        (setup["A201_W"], Decimal("619"), "MANUAL"),
        (setup["A201_E"], Decimal("5000"), "MANUAL"),
    ]
    assert all(by == db.manager for *_, by in saved)
    # The same tap twice changes nothing.
    assert decide(db, a201, "CONFIRMED")["done"] == 0

    # Ask to read A202 again: the reader hears it in the Staff bot.
    a202 = rows[("A202", "ELECTRICITY")]["proposal_id"]
    assert decide(db, [a202], "ASK_AGAIN")["done"] == 1
    with psycopg.connect(db.owner_url) as connection:
        asked = connection.execute(
            "SELECT chat_id, details FROM app.telegram_outbox WHERE text_code = 'staff.meter_again'"
        ).fetchall()
    assert asked == [(READER, {"units": "A202 ភ្លើង"})]
    assert waiting(db) == []

    # A meter that already has a reading that day stays waiting until it is not used.
    later, _, _ = send(
        db,
        READINGS,
        READER,
        "item-mr-02",
        {"type": "METER", "readings": [{"unit_id": setup["A201"], "electricity": 5003}]},
    )
    assert later["count"] == 1 and later["flagged"] == 1
    [second] = waiting(db)
    [row] = second["readings"]
    assert row["already"] is True and row["last_value"] == "4120"
    assert decide(db, [row["proposal_id"]], "CONFIRMED") == {
        "decision": "CONFIRMED",
        "done": 0,
        "already": ["A201"],
    }
    assert decide(db, [row["proposal_id"]], "NOT_USED")["done"] == 1
    assert waiting(db) == []

    for wrong, error in (
        (([str(uuid.uuid4())], "CONFIRMED"), psycopg.errors.InvalidParameterValue),
        (([row["proposal_id"]], "MAYBE"), psycopg.errors.InvalidParameterValue),
        (([], "CONFIRMED"), psycopg.errors.InvalidParameterValue),
    ):
        with pytest.raises(error):
            decide(db, *wrong)


def test_a_meter_check_request_is_a_unit_problem(
    meters_database: HrDatabase, setup: dict[str, str]
) -> None:
    db = meters_database
    form = {
        "type": "METER_CHECK",
        "unit_id": setup["A202"],
        "meter": "WATER",
        "problem": "CANNOT_READ",
        "note": "The screen is dark",
    }
    saved, inbound, _ = send(db, CHECK, CARETAKER, "item-mc-01", form, [file("dark")])
    assert saved["result"] == "ADDED" and saved["repeated"] is False
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT report.kind, report.unit_id, kind.code, report.description, report.source, "
            "report.urgent, (SELECT count(*) FROM app.problem_report_media AS media "
            "WHERE media.report_id = report.id) FROM app.problem_reports AS report "
            "JOIN app.problem_types AS kind ON kind.id = report.problem_type_id "
            "WHERE report.report_number = %s",
            (saved["report_number"],),
        ).fetchone()
    assert row == (
        "UNIT",
        uuid.UUID(setup["A202"]),
        "WATER",
        "Meter check request: Water meter, cannot read the number. The screen is dark",
        "STAFF_BOT",
        False,
        1,
    )
    again = run(
        db.runtime_url,
        CHECK,
        db.property_id,
        inbound,
        json.dumps(form),
        json.dumps([]),
        db.manager,
    )
    assert again == {"result": "ADDED", "repeated": True, "report_number": saved["report_number"]}

    # No photo is fine; "Other" needs a note; photos only, at most 2.
    plain = send(db, CHECK, READER, "item-mc-02", form | {"problem": "BROKEN", "note": None})
    assert plain[0]["result"] == "ADDED"
    refused = [
        (form | {"problem": "OTHER", "note": ""}, [], "say_what"),
        (form | {"meter": "GAS"}, [], "meter"),
        (form | {"unit_id": str(uuid.uuid4())}, [], "unit"),
        (form, [file("m1"), file("m2"), file("m3")], "photo"),
        (form, [file("m4", "audio/ogg", 5)], "files"),
    ]
    for number_of, (body, files, reason) in enumerate(refused):
        answer = send(db, CHECK, READER, f"item-mc-r{number_of}", body, files)[0]
        assert answer == {"result": "INVALID", "reason": reason}, body


def test_the_new_functions_are_behind_their_rights(
    meters_database: HrDatabase, setup: dict[str, str]
) -> None:
    db = meters_database
    for sql in (READINGS, CHECK):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            run(db.runtime_url, sql, db.property_id, uuid.uuid4(), "{}", "[]", db.staff)
    # Utilities: whoever may record readings (the Accountant here may not).
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run(db.runtime_url, WAITING, db.property_id, db.accountant)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run(db.runtime_url, DECIDE, db.property_id, "[]", "CONFIRMED", db.accountant)
    with psycopg.connect(db.runtime_url) as connection:
        for table in (
            "staff_meter_reading_runs",
            "staff_meter_reading_proposals",
            "staff_meter_reading_decisions",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT 1 FROM app.{table}")
            connection.rollback()
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE app.staff_meter_reading_runs SET reading_date = reading_date"
            )
