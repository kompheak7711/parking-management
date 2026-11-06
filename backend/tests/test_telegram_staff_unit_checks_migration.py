"""Staff bot Unit Check and Maintenance check (migration 20270624_335, DL-178).

Owner rules (staff forms mock-up v14, 3 Nov 2026; DL-115): the Technician marks each area of a
Unit Good, Broken or Missing, and each Broken or Missing area becomes a Unit Problem with its
photos; the Technician checks a planned visit (how staff entered, the cause, fixed at once only
when urgent) and the report is Checked. A check never makes a charge.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from test_hr_attendance_migration import link
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_staff_reports_migration import ADD, STEP, add_unit, file, ids, report, send

UNIT_CHECK = "SELECT app.telegram_staff_unit_check(%s, %s, %s::jsonb, %s::jsonb, %s)"
MAINT_CHECK = "SELECT app.telegram_staff_maintenance_check(%s, %s, %s::jsonb, %s::jsonb, %s)"
FORM_DATA = "SELECT app.telegram_staff_form_data(%s, %s)"

CLEANER, TECHNICIAN, BOSS = 8860001, 8860002, 8860003
AREAS = ["LIVING", "BEDROOM", "BATHROOM", "KITCHEN", "BALCONY", "AIR_CONDITIONER", "KEYS"]


@pytest.fixture(scope="module")
def checks_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_unit_checks")


@pytest.fixture(scope="module")
def staff(checks_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = checks_database
    people = {
        "cleaner": add_employee(db, name_en="Yon Dane", name_km="យ៉ន់ ដានេ"),
        "technician": add_employee(
            db,
            name_en="Son Sokhen",
            name_km="សន សុខខេន",
            job_title_id=job_id(db, "TECHNICIAN"),
            usual_day_off=db.today.isoweekday() % 7 + 1,
        ),
        "boss": add_employee(db, name_en="Kuy Sopheak", name_km="គុយ សុភ័ក្រ"),
    }
    link(db, people["cleaner"], CLEANER, "CLEANER")
    link(db, people["technician"], TECHNICIAN, "TECHNICIAN")
    link(db, people["boss"], BOSS, "AUTHORIZER")
    return people


def planned_visit(db: HrDatabase, unit: str, *, urgent: bool = False) -> tuple[str, str]:
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
                        "urgent": urgent,
                        "unit_id": unit,
                        "problem_type_id": known["WATER"],
                        "description": "Bathroom tap leaks",
                    }
                ),
                db.manager,
            ),
        ).fetchone()
        assert row is not None
        report_id = str(row[0])
        visit = str(db.today + timedelta(days=1))
        done = connection.execute(
            STEP,
            (
                db.property_id,
                report_id,
                1,
                "PLAN",
                json.dumps({"technician": "Son Sokhen", "visit_on": visit, "visit_at": "09:00"}),
                db.manager,
            ),
        ).fetchone()
        assert done is not None
        number = connection.execute(
            "SELECT app.problem_report_read(%s, %s, %s)", (db.property_id, report_id, db.manager)
        ).fetchone()
    assert number is not None
    return report_id, str(number[0]["report_number"])


def checked(db: HrDatabase, number: str) -> dict[str, Any]:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT status, cause, cause_note, fixed_at_check FROM app.problem_reports "
            "WHERE report_number = %s",
            (number,),
        ).fetchone()
    assert row is not None
    return dict(zip(("status", "cause", "note", "fixed"), row, strict=True))


def test_the_forms_show_the_planned_visits_and_the_unit_check_areas(
    checks_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = checks_database
    unit = add_unit(db, "C301")
    _, number = planned_visit(db, unit)
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    assert isinstance(data, dict)
    visits = data["choices"]["visits"]
    assert [visit["report_number"] for visit in visits] == [number]
    assert visits[0]["unit"] == "C301" and visits[0]["visit_at"] == "09:00"
    assert visits[0]["visit_on"] == (db.today + timedelta(days=1)).strftime("%d/%m")
    assert [area["code"] for area in data["choices"]["unit_areas"]] == AREAS
    assert data["choices"]["unit_areas"][0]["km"] == "បន្ទប់ទទួលភ្ញៀវ"
    # The visits are shared, not in each person's data (the relay keeps 8 KB per person).
    assert all("visits" not in person["data"] for person in data["users"])


def test_a_unit_check_makes_a_unit_problem_for_each_finding(
    checks_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = checks_database
    unit = add_unit(db, "C302")
    form: dict[str, Any] = {
        "type": "UNIT_CHECK",
        "unit_id": unit,
        "kind": "REGULAR",
        "areas": {
            "LIVING": "GOOD",
            "BEDROOM": "BROKEN",
            "BATHROOM": "GOOD",
            "AIR_CONDITIONER": "BROKEN",
            "KEYS": "MISSING",
        },
        "findings": {
            "BEDROOM": {"text": "Wardrobe door off", "photos": 2},
            "AIR_CONDITIONER": {"text": "Remote does not work", "photos": 1},
            "KEYS": {"text": "One key card missing", "photos": 1},
        },
        "note": "Balcony: none in this Unit",
    }
    photos = [file("uc-1"), file("uc-2"), file("uc-3"), file("uc-4")]
    # Only a Technician or an Authorizer.
    assert send(db, UNIT_CHECK, CLEANER, "item-uc-cleaner", form, photos) == {"result": "NOT_ROLE"}
    for relay_id, body, files in (
        ("item-uc-r1", form | {"unit_id": str(uuid.uuid4())}, photos),
        ("item-uc-r2", form | {"kind": "MONTHLY"}, photos),
        ("item-uc-r3", form | {"areas": {}}, photos),
        ("item-uc-r4", form | {"areas": form["areas"] | {"GARDEN": "GOOD"}}, photos),
        ("item-uc-r5", form | {"areas": form["areas"] | {"KITCHEN": "DIRTY"}}, photos),
        # A finding for a Good area, or a Broken area with no finding.
        (
            "item-uc-r6",
            form | {"findings": form["findings"] | {"LIVING": {"text": "x", "photos": 1}}},
            [*photos, file("uc-5")],
        ),
        (
            "item-uc-r7",
            form | {"areas": form["areas"] | {"KITCHEN": "BROKEN"}},
            photos,
        ),
        (
            "item-uc-r8",
            form | {"findings": form["findings"] | {"KEYS": {"text": " ", "photos": 1}}},
            photos,
        ),
        (
            "item-uc-r9",
            form | {"findings": form["findings"] | {"KEYS": {"text": "Gone", "photos": 0}}},
            photos[:3],
        ),
        ("item-uc-r10", form, photos[:3]),
        ("item-uc-r11", form, [*photos[:3], file("uc-voice", "audio/ogg", 10)]),
        ("item-uc-r12", form | {"note": "x" * 501}, photos),
    ):
        answer = send(db, UNIT_CHECK, TECHNICIAN, relay_id, body, files)
        assert answer["result"] == "INVALID", (relay_id, answer)

    sent = send(db, UNIT_CHECK, TECHNICIAN, "item-uc-ok", form, photos)
    assert sent["result"] == "SENT" and sent["repeated"] is False
    assert sent["findings"] == 3 and len(sent["numbers"]) == 3
    # The same form again saves nothing more.
    assert send(db, UNIT_CHECK, TECHNICIAN, "item-uc-ok", form, photos) == sent | {"repeated": True}
    bedroom, aircon, keys = (report(db, number) for number in sent["numbers"])
    assert bedroom["status"] == "RECEIVED" and bedroom["source"] == "STAFF_BOT"
    assert bedroom["reported_by"] == "សន សុខខេន" and str(bedroom["unit_id"]) == unit
    assert bedroom["media"] == [("REPORTED", "PHOTO", 1), ("REPORTED", "PHOTO", 2)]
    assert aircon["media"] == [("REPORTED", "PHOTO", 1)]
    assert keys["media"] == [("REPORTED", "PHOTO", 1)]
    known = ids(db)
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT report_number, problem_type_id, description FROM app.problem_reports "
            "WHERE report_number = ANY(%s) ORDER BY report_number",
            (sent["numbers"],),
        ).fetchall()
        saved = connection.execute(
            "SELECT kind, findings, note, areas FROM app.staff_unit_checks "
            "WHERE inbound_event_id = (SELECT id FROM app.telegram_inbound_events "
            "WHERE relay_item_id = 'item-uc-ok')"
        ).fetchone()
    types = {str(number): (str(kind), str(text)) for number, kind, text in rows}
    assert types[sent["numbers"][0]] == (
        known["OTHER"],
        "Unit Check: Bedroom, broken. Wardrobe door off",
    )
    assert types[sent["numbers"][1]][0] == known["AIR_CONDITIONER"]
    assert types[sent["numbers"][2]] == (
        known["DOOR_LOCK"],
        "Unit Check: Keys, key cards and remotes, missing. One key card missing",
    )
    assert saved == ("REGULAR", 3, "Balcony: none in this Unit", form["areas"])

    # An Authorizer may send it too; all Good makes no Unit Problem.
    good = send(
        db,
        UNIT_CHECK,
        BOSS,
        "item-uc-good",
        {
            "type": "UNIT_CHECK",
            "unit_id": unit,
            "kind": "AFTER_REPAIR",
            "areas": {"BEDROOM": "GOOD"},
        },
    )
    assert good == {"result": "SENT", "repeated": False, "findings": 0, "numbers": []}


def test_a_maintenance_check_moves_the_visit_to_checked(
    checks_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = checks_database
    unit = add_unit(db, "C303")
    report_id, number = planned_visit(db, unit)
    form: dict[str, Any] = {
        "type": "MAINT_CHECK",
        "report_id": report_id,
        "entry": "TENANT_OK",
        "cause": "DAMAGE",
        "note": "Tap handle broken off",
    }
    assert send(db, MAINT_CHECK, CLEANER, "item-mc-cleaner", form, [file("mc-1")]) == {
        "result": "NOT_ROLE"
    }
    for relay_id, body, files in (
        ("item-mc-r1", form | {"report_id": "nope"}, [file("mc-1")]),
        ("item-mc-r2", form | {"report_id": str(uuid.uuid4())}, [file("mc-1")]),
        ("item-mc-r3", form | {"entry": "KEY"}, [file("mc-1")]),
        ("item-mc-r4", form | {"cause": "TENANT"}, [file("mc-1")]),
        ("item-mc-r5", form | {"fixed": "yes"}, [file("mc-1")]),
        # Fixed at once only for an urgent report.
        ("item-mc-r6", form | {"fixed": True}, [file("mc-1")]),
        ("item-mc-r7", form, []),
        ("item-mc-r8", form, [file(f"mc-many-{index}") for index in range(6)]),
        ("item-mc-r9", form | {"note": "x" * 401}, [file("mc-1")]),
    ):
        answer = send(db, MAINT_CHECK, TECHNICIAN, relay_id, body, files)
        assert answer["result"] == "INVALID", (relay_id, answer)
    assert checked(db, number)["status"] == "PLANNED"

    done = send(db, MAINT_CHECK, TECHNICIAN, "item-mc-ok", form, [file("mc-1"), file("mc-2")])
    assert done == {
        "result": "CHECKED",
        "repeated": False,
        "report_number": number,
        "cause": "DAMAGE",
        "fixed": False,
    }
    assert send(db, MAINT_CHECK, TECHNICIAN, "item-mc-ok", form, [file("mc-1")]) == done | {
        "repeated": True
    }
    assert checked(db, number) == {
        "status": "CHECKED",
        "cause": "DAMAGE",
        "note": "Checked in the Staff bot by សន សុខខេន. Entered: the tenant agreed. "
        "Tap handle broken off",
        "fixed": False,
    }
    assert report(db, number)["media"] == [("CHECK", "PHOTO", 1), ("CHECK", "PHOTO", 2)]
    # Checked already: a second check says so; the visit leaves the list.
    again = send(db, MAINT_CHECK, TECHNICIAN, "item-mc-again", form, [file("mc-3")])
    assert again == {"result": "NOT_PLANNED", "report_number": number}
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)
    assert number not in [visit["report_number"] for visit in data["choices"]["visits"]]

    # An urgent visit fixed at once, checked by an Authorizer.
    urgent_id, urgent = planned_visit(db, unit, urgent=True)
    fixed = send(
        db,
        MAINT_CHECK,
        BOSS,
        "item-mc-urgent",
        {
            "type": "MAINT_CHECK",
            "report_id": urgent_id,
            "entry": "URGENT",
            "cause": "WEAR",
            "fixed": True,
        },
        [file("mc-4")],
    )
    assert fixed["result"] == "CHECKED" and fixed["fixed"] is True
    assert checked(db, urgent) == {
        "status": "CHECKED",
        "cause": "WEAR",
        "note": "Checked in the Staff bot by គុយ សុភ័ក្រ. Entered: urgent.",
        "fixed": True,
    }


def test_the_unit_check_functions_are_behind_the_telegram_right(
    checks_database: HrDatabase, staff: dict[str, uuid.UUID]
) -> None:
    db = checks_database
    for sql in (UNIT_CHECK, MAINT_CHECK):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            run(db.runtime_url, sql, db.property_id, uuid.uuid4(), "{}", "[]", db.staff)
    with psycopg.connect(db.runtime_url) as connection:
        for table in ("staff_unit_checks", "staff_unit_check_findings", "staff_maintenance_checks"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT 1 FROM app.{table}")
            connection.rollback()
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("DELETE FROM app.staff_unit_checks")
