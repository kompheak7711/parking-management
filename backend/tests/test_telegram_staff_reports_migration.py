"""Staff bot Report a problem, Close job and the urgent alert (migration 20270621_332, DL-175).

Owner rules (3 Nov 2026, staff forms mock-up v14): every linked staff member reports a problem
on the walk-round with at least one photo and a text or voice note; the Technician closes a
planned repair with the after photo and the cost (No cost, or parts and outside workers with a
receipt photo); an urgent report reaches the caretaker on shift and the Authorizers at once.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from test_hr_attendance_migration import link, zone
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item

REPORT = "SELECT app.telegram_staff_problem_report(%s, %s, %s::jsonb, %s::jsonb, %s)"
CLOSE = "SELECT app.telegram_staff_close_job(%s, %s, %s::jsonb, %s::jsonb, %s)"
FORM_DATA = "SELECT app.telegram_staff_form_data(%s, %s)"
STEP = "SELECT app.problem_report_step(%s, %s, %s, %s, %s::jsonb, %s, NULL)"
ADD = "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)"

CLEANER, TECHNICIAN, CARETAKER, OFF_SHIFT, BOSS = 8830001, 8830002, 8830003, 8830004, 8830005


@pytest.fixture(scope="module")
def reports_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_reports")


def ids(db: HrDatabase) -> dict[str, str]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute("SELECT code, id FROM app.problem_types").fetchall()
        places = connection.execute("SELECT 'PLACE_' || code, id FROM app.problem_places")
        return {str(code): str(value) for code, value in [*rows, *places.fetchall()]}


def add_unit(db: HrDatabase, number: str) -> str:
    unit_id = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, %s, '2', 'ONE_BEDROOM', 'VACANT', %s, %s)",
            (unit_id, db.property_id, number, db.owner, db.owner),
        )
    return str(unit_id)


def file(
    name: str, content_type: str = "image/jpeg", duration: int | None = None
) -> dict[str, Any]:
    sha = hashlib.sha256(name.encode()).hexdigest()
    return {
        "sha256": sha,
        "content_type": content_type,
        "size_bytes": 2048,
        "storage_path": f"{sha[:2]}/{sha}",
        "duration_seconds": duration,
    }


def send(
    db: HrDatabase,
    sql: str,
    user: int,
    relay_id: str,
    form: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    answer = run(
        db.runtime_url,
        sql,
        db.property_id,
        saved["inbound_id"],
        json.dumps(form),
        json.dumps(saved.get("media_ids", [])),
        db.manager,
    )
    assert isinstance(answer, dict)
    return answer


def alerts(db: HrDatabase) -> list[tuple[int, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT chat_id, details FROM app.telegram_outbox WHERE bot_code = 'STAFF' "
            "AND text_code = 'staff.urgent' ORDER BY created_at, chat_id"
        ).fetchall()
    return [(int(chat), details) for chat, details in rows]


def report(db: HrDatabase, number: str) -> dict[str, Any]:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT id, status, source, urgent, reported_by, version, unit_id, joined_to_id "
            "FROM app.problem_reports WHERE report_number = %s",
            (number,),
        ).fetchone()
        assert row is not None
        media = connection.execute(
            "SELECT stage, kind, position FROM app.problem_report_media WHERE report_id = %s "
            "ORDER BY stage, position",
            (row[0],),
        ).fetchall()
    keys = ("id", "status", "source", "urgent", "reported_by", "version", "unit_id", "joined")
    return dict(zip(keys, row, strict=True)) | {"media": [tuple(entry) for entry in media]}


def on_shift_now(db: HrDatabase) -> list[tuple[str, int]]:
    """The shift (and the day it started, 0 today or -1 yesterday) that covers this moment."""
    clock = datetime.now(zone(db)).strftime("%H:%M")
    shifts: list[tuple[str, int]] = []
    if "06:30" <= clock < "15:30":
        shifts.append(("MORNING", 0))
    if "14:30" <= clock < "23:30":
        shifts.append(("AFTERNOON", 0))
    if clock >= "22:30":
        shifts.append(("NIGHT", 0))
    if clock < "07:30":
        shifts.append(("NIGHT", -1))
    return shifts


def plan(db: HrDatabase, employee: uuid.UUID, offset: int, shift: str | None) -> None:
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.shift_plan_entries (employee_id, work_date, shift_code, is_day_off, "
            "reason, created_by) VALUES (%s, %s, %s, %s, 'Test', %s)",
            (employee, db.today + timedelta(days=offset), shift, shift is None, db.owner),
        )


@pytest.fixture(scope="module")
def staff(reports_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = reports_database
    people = {
        "cleaner": add_employee(db, name_en="Yon Dane", name_km="យ៉ន់ ដានេ"),
        "technician": add_employee(
            db,
            name_en="Son Sokhen",
            name_km="សន សុខខេន",
            job_title_id=job_id(db, "TECHNICIAN"),
            usual_day_off=db.today.isoweekday() % 7 + 1,
        ),
        "caretaker": add_employee(
            db, name_en="Pich Pheakdey", name_km="ពេជ ភក្ដី", job_title_id=job_id(db, "CARETAKER")
        ),
        "off_shift": add_employee(
            db, name_en="Pang Phai", name_km="ប៉ាង ផៃ", job_title_id=job_id(db, "CARETAKER")
        ),
        "boss": add_employee(db, name_en="Manager", name_km="អ្នកគ្រប់គ្រង"),
    }
    link(db, people["cleaner"], CLEANER)
    link(db, people["technician"], TECHNICIAN, "TECHNICIAN")
    link(db, people["caretaker"], CARETAKER, "CARETAKER")
    link(db, people["off_shift"], OFF_SHIFT, "CARETAKER")
    link(db, people["boss"], BOSS, "AUTHORIZER")
    shifts = on_shift_now(db)
    for offset in (0, -1):
        plan(db, people["caretaker"], offset, next((s for s, o in shifts if o == offset), None))
        plan(db, people["off_shift"], offset, None)
    return people


def test_staff_report_a_problem_with_a_photo(
    reports_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = reports_database
    known = ids(db)
    unit = add_unit(db, "A102")
    form = {
        "type": "REPORT",
        "kind": "UNIT",
        "unit_id": unit,
        "problem_type_id": known["AIR_CONDITIONER"],
        "description": "Air conditioner drips water",
    }
    saved = send(db, REPORT, CLEANER, "item-sr-01", form, [file("ac-1"), file("ac-2")])
    assert saved["result"] == "ADDED" and saved["repeated"] is False
    assert saved["kind"] == "UNIT" and saved["urgent"] is False
    number = saved["report_number"]
    kept = report(db, number)
    assert kept["source"] == "STAFF_BOT" and kept["status"] == "RECEIVED"
    assert kept["reported_by"] == "យ៉ន់ ដានេ"
    assert kept["media"] == [("REPORTED", "PHOTO", 1), ("REPORTED", "PHOTO", 2)]
    # Not urgent: nobody is alerted.
    assert alerts(db) == []

    # A photo is needed; text or a voice note too; only linked staff; only a real Unit.
    refused = [
        (CLEANER, form, []),
        (CLEANER, form | {"description": ""}, [file("ac-3")]),
        (CLEANER, form | {"unit_id": str(uuid.uuid4())}, [file("ac-4")]),
        (CLEANER, form | {"problem_type_id": "x"}, [file("ac-5")]),
        (CLEANER, form, [file(f"many-{n}") for n in range(5)]),
    ]
    for number_of, (user, body, files) in enumerate(refused):
        answer = send(db, REPORT, user, f"item-sr-r{number_of}", body, files)
        assert answer["result"] == "INVALID", body
    assert send(db, REPORT, 8839999, "item-sr-nobody", form, [file("ac-6")]) == {
        "result": "NOT_LINKED"
    }
    # A voice note alone is enough with the photo.
    voice = send(
        db,
        REPORT,
        CLEANER,
        "item-sr-voice",
        form | {"description": None},
        [file("ac-7"), file("voice-1", "audio/ogg", 20)],
    )
    assert voice["result"] == "ADDED"
    assert report(db, voice["report_number"])["media"][-1] == ("REPORTED", "VOICE", 2)


def test_urgent_reports_alert_the_caretaker_on_shift_and_the_authorizers(
    reports_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = reports_database
    known = ids(db)
    before = len(alerts(db))
    form = {
        "type": "REPORT",
        "kind": "BUILDING",
        "problem_place_id": known["PLACE_PARKING"],
        "floor": "B1",
        "problem_type_id": known["SAFETY"],
        "description": "Smoke near the generator",
    }
    saved = send(db, REPORT, TECHNICIAN, "item-sr-safety", form, [file("smoke")])
    assert saved["urgent"] is True and saved["kind"] == "BUILDING"
    sent = alerts(db)[before:]
    # The caretaker on shift and the Authorizer; not the caretaker off shift, not the sender.
    assert [chat for chat, _ in sent] == [CARETAKER, BOSS]
    assert sent[0][1]["number"] == saved["report_number"]
    assert sent[0][1]["where"].endswith("· B1") and sent[0][1]["type"]

    # "Same problem" joins the open report and alerts nobody again.
    same = send(
        db,
        REPORT,
        CLEANER,
        "item-sr-same",
        form | {"same_as": str(report(db, saved["report_number"])["id"]), "description": ""},
        [file("smoke-2")],
    )
    assert same["joined_to"] == saved["report_number"]
    assert report(db, same["report_number"])["status"] == "JOINED"
    assert len(alerts(db)) == before + 2

    # A report the caretaker sends: the caretaker is not told, the Authorizer is.
    send(db, REPORT, CARETAKER, "item-sr-shock", form | {"floor": None}, [file("smoke-3")])
    assert [chat for chat, _ in alerts(db)[before + 2 :]] == [BOSS]

    # An urgent report typed in the app alerts them too.
    with psycopg.connect(db.runtime_url) as connection:
        connection.execute(
            ADD,
            (
                db.property_id,
                json.dumps(
                    {
                        "kind": "BUILDING",
                        "source": "PHONE",
                        "urgent": True,
                        "problem_type_id": known["WATER"],
                        "problem_place_id": known["PLACE_PARKING"],
                        "description": "Water on the floor",
                    }
                ),
                db.manager,
            ),
        )
    assert [chat for chat, _ in alerts(db)[before + 3 :]] == [CARETAKER, BOSS]


def planned_repair(db: HrDatabase, unit: str) -> tuple[str, str]:
    known = ids(db)
    with psycopg.connect(db.runtime_url) as connection:
        row = connection.execute(
            ADD,
            (
                db.property_id,
                json.dumps(
                    {
                        "kind": "UNIT",
                        "source": "SEEN",
                        "urgent": False,
                        "unit_id": unit,
                        "problem_type_id": known["AIR_CONDITIONER"],
                        "description": "Not cold",
                    }
                ),
                db.manager,
            ),
        ).fetchone()
        assert row is not None
        report_id = str(row[0])
        version = 1
        visit = str(db.today + timedelta(days=1))
        for step, body in (
            ("PLAN", {"technician": "Son Sokhen", "visit_on": visit, "visit_at": "09:00"}),
            ("CHECKED", {"cause": "WEAR"}),
            ("DECIDE", {"pays": "OWNER"}),
        ):
            done = connection.execute(
                STEP,
                (db.property_id, report_id, version, step, json.dumps(body), db.manager),
            ).fetchone()
            assert done is not None
            version = int(done[0])
        number = connection.execute(
            "SELECT app.problem_report_read(%s, %s, %s)", (db.property_id, report_id, db.manager)
        ).fetchone()
    assert number is not None
    return report_id, str(number[0]["report_number"])


def test_the_technician_closes_a_job_with_the_after_photo_and_cost(
    reports_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = reports_database
    unit = add_unit(db, "B105")
    report_id, number = planned_repair(db, unit)
    # The Technician sees the open job in the form; a cleaner does not.
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    people = {person["id"]: person["data"] for person in data["users"]}
    jobs = people[TECHNICIAN]["jobs"]
    assert [job["report_number"] for job in jobs] == [number]
    assert jobs[0]["unit"] == "B105" and jobs[0]["type_km"]
    assert "jobs" not in people[CLEANER]
    assert {"A102", "B105"} <= {unit["number"] for unit in data["choices"]["units"]}

    form = {
        "type": "CLOSE",
        "report_id": report_id,
        "after_photos": 1,
        "cost": "PAID",
        "parts_usd_cents": 1250,
        "outside_usd_cents": 0,
    }
    # Only the Technician; the after photo and the receipt are needed.
    assert send(db, CLOSE, CLEANER, "item-cj-cleaner", form, [file("after"), file("receipt")]) == {
        "result": "NOT_TECHNICIAN"
    }
    for relay_id, body, files in (
        ("item-cj-r1", form, [file("after")]),
        ("item-cj-r2", form | {"after_photos": 0}, [file("receipt")]),
        ("item-cj-r3", form | {"parts_usd_cents": 0}, [file("after"), file("receipt")]),
        ("item-cj-r4", form | {"parts_usd_cents": 12.5}, [file("after"), file("receipt")]),
        ("item-cj-r5", form | {"cost": "NONE"}, [file("after"), file("receipt")]),
    ):
        assert send(db, CLOSE, TECHNICIAN, relay_id, body, files)["result"] == "INVALID", body

    done = send(db, CLOSE, TECHNICIAN, "item-cj-ok", form, [file("after"), file("receipt")])
    assert done == {
        "result": "DONE",
        "repeated": False,
        "report_number": number,
        "cost": "PAID",
        "total_usd_cents": 1250,
    }
    kept = report(db, number)
    assert kept["status"] == "DONE"
    assert kept["media"] == [("DONE", "PHOTO", 1), ("RECEIPT", "PHOTO", 1)]
    with psycopg.connect(db.owner_url) as connection:
        lines = connection.execute(
            "SELECT line.kind, line.currency, line.amount_minor FROM "
            "app.problem_report_cost_lines AS line JOIN app.problem_report_cost_sets AS cost_set "
            "ON cost_set.id = line.set_id WHERE cost_set.report_id = %s",
            (report_id,),
        ).fetchall()
    assert lines == [("PARTS", "USD", 1250)]
    # Done already: a second close says so; the jobs list is empty again.
    again = send(db, CLOSE, TECHNICIAN, "item-cj-again", form, [file("after-2"), file("rc-2")])
    assert again == {"result": "NOT_OPEN", "report_number": number}
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    people = {person["id"]: person["data"] for person in data["users"]}
    assert people[TECHNICIAN]["jobs"] == []

    # No cost: the after photo only.
    other_id, other = planned_repair(db, unit)
    free = send(
        db,
        CLOSE,
        TECHNICIAN,
        "item-cj-free",
        {"type": "CLOSE", "report_id": other_id, "after_photos": 2, "cost": "NONE"},
        [file("after-3"), file("after-4")],
    )
    assert free["result"] == "DONE" and free["cost"] == "NONE"
    assert report(db, other)["media"] == [("DONE", "PHOTO", 1), ("DONE", "PHOTO", 2)]


def test_the_new_functions_are_behind_the_telegram_right(
    reports_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = reports_database
    for sql in (REPORT, CLOSE):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            run(db.runtime_url, sql, db.property_id, uuid.uuid4(), "{}", "[]", db.staff)
    with psycopg.connect(db.runtime_url) as connection:
        for table in ("staff_problem_report_sources", "staff_job_closures"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT 1 FROM app.{table}")
            connection.rollback()
