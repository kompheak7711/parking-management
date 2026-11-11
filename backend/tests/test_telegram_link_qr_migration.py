"""The one-time Telegram QR on the real database (migration 20270712_384, DL-214).

Owner (11 Nov 2026, "Yes, QR for tenants and guests"): staff show a QR at Lease signing or guest
check-in; the scan links the person at once. A guest's link ends at check-out, and guests get no
Invoices on Telegram.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import refused

PEOPLE = "SELECT app.telegram_link_people(%s, %s, %s, %s)"
CREATE = "SELECT app.telegram_link_code_create(%s, %s, %s, %s, %s)"
SCAN = "SELECT app.telegram_tenant_link_code(%s, %s, %s, %s)"
OFFLINE = "SELECT app.telegram_link_codes_offline(%s, %s)"
NAME = "SELECT app.telegram_bot_name_set(%s, %s, %s, %s)"
TENANT, GUEST, OTHER = 7710001, 7710002, 7710003


@pytest.fixture(scope="module")
def qr_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_qr")


def add_unit(db: HrDatabase, number: str) -> uuid.UUID:
    unit_id = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, %s, '3', 'ONE_BEDROOM', 'VACANT', %s, %s)",
            (unit_id, db.property_id, number, db.owner, db.owner),
        )
    return unit_id


def add_customer(db: HrDatabase, name: str) -> uuid.UUID:
    customer_id = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, %s, '012 345 678', %s, %s)",
            (customer_id, name, db.owner, db.owner),
        )
    return customer_id


@pytest.fixture(scope="module")
def stays(qr_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = qr_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    lease_unit, guest_unit = add_unit(db, "U302"), add_unit(db, "U508")
    tenant, guest = add_customer(db, "Sao Rina"), add_customer(db, "Chan Dara")
    booking = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        lease = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=lease_unit,
            primary_tenant_id=tenant,
            start_date=day - timedelta(days=30),
            end_date=day + timedelta(days=300),
        )
        sign_lease(connection, lease, db.owner)
    # A new transaction: sign_lease makes the deferred checks immediate for its own.
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.short_stay_bookings (id, property_id, unit_id, booking_number, "
            "customer_id, guest_count, check_in_on, check_out_on, source, total_usd_cents, "
            "created_by) VALUES (%s, %s, %s, 'ST269901', %s, 1, %s, %s, 'WALK_IN', 9000, %s)",
            (booking, db.property_id, guest_unit, guest, day, day + timedelta(days=3), db.owner),
        )
        connection.execute(
            "INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, "
            "kind, quantity, unit_price_usd_cents, amount_usd_cents) "
            "VALUES (%s, 1, 1, 'NIGHTS', 3, 3000, 9000)",
            (booking,),
        )
    return {"lease": lease, "booking": booking, "tenant": tenant, "guest": guest}


def code_of(made: dict[str, Any]) -> str:
    return str(made["url"]).rsplit("=", 1)[-1]


def test_no_qr_before_the_send_job_knows_the_bot_name(
    qr_database: HrDatabase, stays: dict[str, uuid.UUID]
) -> None:
    db = qr_database
    people = run(db.runtime_url, PEOPLE, db.property_id, stays["lease"], None, db.manager)
    assert people["bot_ready"] is False and people["hours"] == 24
    assert people["people"] == [
        {"customer_id": str(stays["tenant"]), "name": "Sao Rina", "unit_number": "U302"}
    ]
    refused(
        db.runtime_url,
        "55000",
        CREATE,
        db.property_id,
        stays["lease"],
        None,
        stays["tenant"],
        db.manager,
    )
    assert run(db.runtime_url, NAME, db.property_id, "TENANT", "ChetanaSupportBot", db.manager)
    assert not run(db.runtime_url, NAME, db.property_id, "TENANT", "ChetanaSupportBot", db.manager)
    refused(db.runtime_url, "22023", NAME, db.property_id, "TENANT", "a b", db.manager)


def test_a_tenant_scans_once_and_is_linked_to_the_lease(
    qr_database: HrDatabase, stays: dict[str, uuid.UUID]
) -> None:
    db = qr_database
    run(db.runtime_url, NAME, db.property_id, "TENANT", "ChetanaSupportBot", db.manager)
    made = run(
        db.runtime_url, CREATE, db.property_id, stays["lease"], None, stays["tenant"], db.manager
    )
    assert made["url"].startswith("https://t.me/ChetanaSupportBot?start=")
    code = code_of(made)
    assert len(code) == 40 and made["name"] == "Sao Rina" and made["unit_number"] == "U302"
    # Only the hash is kept, and the relay gets it with the Unit while unused.
    with psycopg.connect(db.owner_url) as connection:
        kept = connection.execute(
            "SELECT count(*) FROM app.telegram_link_codes WHERE code_hash = %s",
            (hashlib.sha256(code.encode()).hexdigest(),),
        ).fetchone()
        assert kept == (1,)
        assert connection.execute(
            "SELECT count(*) FROM app.telegram_link_codes WHERE code_hash = %s", (code,)
        ).fetchone() == (0,)
    offline = run(db.runtime_url, OFFLINE, db.property_id, db.manager)
    assert hashlib.sha256(code.encode()).hexdigest() in [row["code_hash"] for row in offline]
    linked = run(db.runtime_url, SCAN, db.property_id, TENANT, code, db.manager)
    assert linked["result"] == "LINKED" and linked["unit_number"] == "U302"
    assert linked["guest"] is False
    again = run(db.runtime_url, SCAN, db.property_id, TENANT, code, db.manager)
    assert again["result"] == "LINKED" and again["repeated"] is True
    assert run(db.runtime_url, SCAN, db.property_id, OTHER, code, db.manager) == {"result": "USED"}
    wrong = run(db.runtime_url, SCAN, db.property_id, OTHER, "0" * 40, db.manager)
    assert wrong == {"result": "NOT_FOUND"}
    assert run(db.runtime_url, SCAN, db.property_id, OTHER, "x", db.manager) == {
        "result": "NOT_FOUND"
    }
    offline = run(db.runtime_url, OFFLINE, db.property_id, db.manager)
    assert hashlib.sha256(code.encode()).hexdigest() not in [row["code_hash"] for row in offline]
    state = run(
        db.runtime_url, "SELECT app.telegram_bot_state(%s, 'TENANT', %s, %s)", db.property_id,
        TENANT, db.manager,
    )  # fmt: skip
    assert state["link"]["lease_id"] == str(stays["lease"])


def test_a_guest_is_linked_until_the_stay_is_over_and_gets_no_invoice(
    qr_database: HrDatabase, stays: dict[str, uuid.UUID]
) -> None:
    db = qr_database
    run(db.runtime_url, NAME, db.property_id, "TENANT", "ChetanaSupportBot", db.manager)
    people = run(db.runtime_url, PEOPLE, db.property_id, None, stays["booking"], db.staff)
    assert [person["name"] for person in people["people"]] == ["Chan Dara"]
    made = run(
        db.runtime_url, CREATE, db.property_id, None, stays["booking"], stays["guest"], db.staff
    )
    linked = run(db.runtime_url, SCAN, db.property_id, GUEST, code_of(made), db.manager)
    assert linked["result"] == "LINKED" and linked["guest"] is True
    access = run(db.runtime_url, "SELECT app.telegram_tenant_access_list(%s, %s)",
                 db.property_id, db.manager)  # fmt: skip
    assert {"id": GUEST, "role": "TENANT"} in access
    page = run(db.runtime_url, "SELECT app.telegram_links_page(%s, %s)", db.property_id, db.manager)
    row = next(item for item in page["linked"] if item["telegram_user_id"] == GUEST)
    assert row["booking_number"] == "ST269901" and row["lease_id"] is None
    # An Invoice of the guest without a Lease does not go to the guest's link.
    with psycopg.connect(db.owner_url) as connection:
        for signature in ("telegram_invoice_people(uuid)", "telegram_invoice_reminders(uuid,uuid)"):
            definition = connection.execute(
                "SELECT pg_get_functiondef(%s::regprocedure)", (f"app.{signature}",)
            ).fetchone()
            assert definition is not None and "link.booking_id IS NULL" in definition[0]
        connection.execute(
            "UPDATE app.short_stay_bookings SET status = 'CANCELLED', cancelled_at = now(), "
            "version = version + 1, cancelled_by = %s, cancel_reason = 'test' WHERE id = %s",
            (db.owner, stays["booking"]),
        )
    ended = run(db.runtime_url, "SELECT app.telegram_tenant_end_finished_links(%s, %s)",
                db.property_id, db.manager)  # fmt: skip
    assert ended >= 1
    with psycopg.connect(db.owner_url) as connection:
        reason = connection.execute(
            "SELECT ending.reason FROM app.tenant_telegram_link_endings AS ending "
            "JOIN app.tenant_telegram_links AS link ON link.id = ending.link_id "
            "WHERE link.telegram_user_id = %s",
            (GUEST,),
        ).fetchone()
    assert reason == ("STAY_ENDED",)
    refused(
        db.runtime_url,
        "22023",
        CREATE,
        db.property_id,
        None,
        stays["booking"],
        stays["guest"],
        db.staff,
    )


def test_the_qr_rights_and_the_one_stay_rule(
    qr_database: HrDatabase, stays: dict[str, uuid.UUID]
) -> None:
    db = qr_database
    refused(db.runtime_url, "22023", PEOPLE, db.property_id, None, None, db.manager)
    refused(
        db.runtime_url, "22023", PEOPLE, db.property_id, stays["lease"], stays["booking"],
        db.manager,
    )  # fmt: skip
    refused(db.runtime_url, "42501", SCAN, db.property_id, TENANT, "0" * 40, db.staff)
    refused(db.runtime_url, "42501", OFFLINE, db.property_id, db.staff)
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.telegram_link_codes")
