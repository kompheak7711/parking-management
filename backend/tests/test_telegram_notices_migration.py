"""Notices from the office go to linked tenants and guests (migration 20270714_386, DL-216).

Owner (11 Nov 2026): CHETANA Residence support sends notices too ("All three, in that order"). A
Manager writes a notice in English and/or Khmer for everyone, some floors or some Units; each
linked person gets it once, in their language.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item, refused

LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
SEND = "SELECT app.telegram_notice_send(%s, %s::jsonb, %s)"
PAGE = "SELECT app.telegram_notices_page(%s, %s)"
THIRD, FIFTH = 8870001, 8870002


@pytest.fixture(scope="module")
def notice_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_notice")


def tenant(
    db: HrDatabase, number: str, floor: str, name: str, user: int, language: str
) -> uuid.UUID:
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, %s, %s, 'ONE_BEDROOM', 'VACANT', %s, %s)",
            (unit_id, db.property_id, number, floor, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, %s, '012 555 444', %s, %s)",
            (customer_id, name, db.owner, db.owner),
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
    body = json.loads(item(f"item-notice-{user}", None))
    body.update(
        telegram_user_id=user, chat_id=user, account={"language": language, "phone": "+85512555444"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, %s, %s)",
        db.property_id,
        user,
        language,
        db.manager,
    )
    typed = " ".join(reversed(name.lower().split()))
    linked = run(db.runtime_url, LINK, db.property_id, user, typed, number, db.manager)
    assert linked["result"] == "LINKED", linked
    return unit_id


@pytest.fixture(scope="module")
def units(notice_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = notice_database
    return {
        "third": tenant(db, "N301", "3", "Sok Vanna", THIRD, "en"),
        "fifth": tenant(db, "N501", "5", "Chea Lina", FIFTH, "km"),
    }


def outbox(db: HrDatabase, notice: str) -> list[tuple[int, str, str, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT outbox.chat_id, outbox.text_code, outbox.language, outbox.details "
            "FROM app.telegram_notice_deliveries AS delivery "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = delivery.outbox_id "
            "WHERE delivery.notice_id = %s ORDER BY outbox.chat_id",
            (notice,),
        ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def test_a_notice_for_everyone_goes_to_each_person_in_their_language(
    notice_database: HrDatabase, units: dict[str, uuid.UUID]
) -> None:
    db = notice_database
    body = {"audience": "ALL", "text_en": "No water 9-11 tomorrow.", "text_km": "គ្មានទឹក"}
    sent = run(db.runtime_url, SEND, db.property_id, json.dumps(body), db.manager)
    assert sent["queued"] == 2
    assert outbox(db, sent["notice_id"]) == [
        (THIRD, "tenant.notice", "en", {"notice": "No water 9-11 tomorrow."}),
        (FIFTH, "tenant.notice", "km", {"notice": "គ្មានទឹក"}),
    ]
    # Written in one language only: everyone gets that.
    only = {"audience": "ALL", "text_en": "Lift work on Monday."}
    sent = run(db.runtime_url, SEND, db.property_id, json.dumps(only), db.manager)
    assert [row[3]["notice"] for row in outbox(db, sent["notice_id"])] == [
        "Lift work on Monday.",
        "Lift work on Monday.",
    ]


def test_a_notice_for_floors_or_units_goes_only_there(
    notice_database: HrDatabase, units: dict[str, uuid.UUID]
) -> None:
    db = notice_database
    floors = {"audience": "FLOORS", "floors": ["5"], "text_km": "ជាន់ទី៥"}
    sent = run(db.runtime_url, SEND, db.property_id, json.dumps(floors), db.manager)
    assert [row[0] for row in outbox(db, sent["notice_id"])] == [FIFTH]
    chosen = {"audience": "UNITS", "unit_ids": [str(units["third"])], "text_en": "Your Unit."}
    sent = run(db.runtime_url, SEND, db.property_id, json.dumps(chosen), db.manager)
    assert [row[0] for row in outbox(db, sent["notice_id"])] == [THIRD]
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    newest = page["notices"][0]
    assert newest["audience"] == "UNITS" and newest["units"] == ["N301"]
    assert newest["people"] == 1 and newest["sent"] == 0 and newest["failed"] == 0
    assert {"3", "5"} <= set(page["floors"])
    assert {"N301", "N501"} <= {unit["unit_number"] for unit in page["units"]}
    assert page["rules"] == {"days": 90, "max": 1500}


def test_a_notice_needs_words_a_real_audience_and_the_operate_right(
    notice_database: HrDatabase, units: dict[str, uuid.UUID]
) -> None:
    db = notice_database
    assert units
    good = {"audience": "ALL", "text_en": "Hello"}
    refused(db.runtime_url, "42501", SEND, db.property_id, json.dumps(good), db.staff)
    for wrong in (
        {"audience": "ALL"},
        {"audience": "ALL", "text_en": "  "},
        {"audience": "EVERYONE", "text_en": "Hi"},
        {"audience": "FLOORS", "floors": ["99"], "text_en": "Hi"},
        {"audience": "FLOORS", "floors": [], "text_en": "Hi"},
        {"audience": "UNITS", "unit_ids": [str(uuid.uuid4())], "text_en": "Hi"},
        {"audience": "UNITS", "unit_ids": ["not-a-unit"], "text_en": "Hi"},
        {"audience": "ALL", "text_en": "x" * 1501},
    ):
        refused(db.runtime_url, "22023", SEND, db.property_id, json.dumps(wrong), db.manager)
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE app.telegram_notices SET text_en = 'changed'")
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM app.telegram_notices")
