"""The Tenant bot while the app is closed, on the real database (migration 20270708_380, DL-210).

Owner (7 Nov 2026, card "Bot answers by itself"): the relay links a new tenant at night with the
scrambled check list, takes the Problem report and alerts the caretaker on shift at once; the app
collects every report when it opens, without a second alert.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from test_hr_attendance_migration import link
from test_hr_employees_migration import HrDatabase, add_employee, job_id, make_hr_database, run
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item, refused
from test_telegram_staff_reports_migration import alerts, ids, on_shift_now, plan

OFFLINE = "SELECT app.telegram_tenant_offline_data(%s, %s)"
FORM_DATA = "SELECT app.telegram_tenant_form_data(%s, %s)"
LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
ADD = "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)"
CARETAKER, BOSS, TENANT = 8840001, 8840002, 8840003


@pytest.fixture(scope="module")
def offline_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_offline")


@pytest.fixture(scope="module")
def lease(offline_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = offline_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, 'Unit 305', '3', 'ONE_BEDROOM', 'VACANT', "
            "%s, %s)",
            (unit_id, db.property_id, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, 'Dara Kim', '012 345 678 / 017 000 111', %s, %s)",
            (customer_id, db.owner, db.owner),
        )
        lease_id = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=day - timedelta(days=30),
            end_date=day + timedelta(days=300),
        )
        sign_lease(connection, lease_id, db.owner)
    people = {
        "caretaker": add_employee(
            db, name_en="Pich Pheakdey", name_km="ពេជ ភក្ដី", job_title_id=job_id(db, "CARETAKER")
        ),
        "boss": add_employee(db, name_en="Manager", name_km="អ្នកគ្រប់គ្រង"),
    }
    link(db, people["caretaker"], CARETAKER, "CARETAKER")
    link(db, people["boss"], BOSS, "AUTHORIZER")
    shifts = on_shift_now(db)
    for offset in (0, -1):
        plan(db, people["caretaker"], offset, next((s for s, o in shifts if o == offset), None))
    return {"unit": unit_id, "customer": customer_id, "lease": lease_id}


def test_the_relay_gets_name_forms_phones_units_and_who_gets_an_alert(
    offline_database: HrDatabase, lease: dict[str, uuid.UUID]
) -> None:
    db = offline_database
    data = run(db.runtime_url, OFFLINE, db.property_id, db.manager)
    person = next(row for row in data["people"] if row["unit_id"] == str(lease["unit"]))
    assert sorted(person["phones"]) == ["+85512345678", "+85517000111"]
    # The forms app.tenant_names_match accepts: any order, together, and together backwards.
    assert person["names"] == ["s:dara kim", "c:darakim", "c:kimdara"]
    unit = data["units"][str(lease["unit"])]
    assert unit["unit"] == "Unit 305" and unit["unit_key"] == "305"
    assert isinstance(unit["places"], list)
    known = ids(db)
    assert data["types"][known["WATER"]]["name_kh"]
    assert data["types"][known["SAFETY"]]["always_urgent"] is True
    assert data["places"][known["PLACE_PARKING"]]
    assert data["alert"]["always"] == [BOSS]
    now = datetime.now(UTC).timestamp()
    covering = [person for person, starts, ends in data["alert"]["shifts"] if starts <= now < ends]
    assert covering == [CARETAKER]
    # No name or phone number of a person reaches the relay except through the office's hash.
    assert "Dara" not in json.dumps(data)


def test_a_linked_tenants_form_data_says_their_unit(
    offline_database: HrDatabase, lease: dict[str, uuid.UUID]
) -> None:
    db = offline_database
    body = json.loads(item("item-offline-0001", None))
    body.update(
        telegram_user_id=TENANT, chat_id=TENANT, account={"language": "en", "phone": "+85512345678"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    linked = run(db.runtime_url, LINK, db.property_id, TENANT, "kim dara", "305", db.manager)
    assert linked["result"] == "LINKED"
    users = run(db.runtime_url, FORM_DATA, db.property_id, db.manager)["users"]
    mine = next(user for user in users if user["id"] == TENANT)
    assert mine["data"]["unit"] == "Unit 305"
    assert "places" in mine["data"]


def test_a_report_the_relay_already_alerted_is_not_alerted_again(
    offline_database: HrDatabase, lease: dict[str, uuid.UUID]
) -> None:
    db = offline_database
    known = ids(db)
    report: dict[str, Any] = {
        "kind": "BUILDING",
        "source": "PHONE",
        "urgent": True,
        "problem_type_id": known["WATER"],
        "problem_place_id": known["PLACE_PARKING"],
        "description": "Water on the floor",
    }
    before = len(alerts(db))
    with psycopg.connect(db.runtime_url, autocommit=True) as connection:
        connection.execute(
            ADD + " FROM (SELECT set_config('prm.relay_alerted', 'on', true)) AS flag",
            (db.property_id, json.dumps(report), db.manager),
        )
    assert len(alerts(db)) == before
    # The flag lasts only for that change: the next urgent report alerts as before.
    with psycopg.connect(db.runtime_url, autocommit=True) as connection:
        connection.execute(ADD, (db.property_id, json.dumps(report), db.manager))
    assert [chat for chat, _ in alerts(db)[before:]] == [CARETAKER, BOSS]


def test_the_offline_data_is_behind_the_telegram_right(offline_database: HrDatabase) -> None:
    db = offline_database
    refused(db.runtime_url, "42501", OFFLINE, db.property_id, db.staff)
