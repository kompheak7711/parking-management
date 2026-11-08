"""Invoices and a reminder go to linked tenants on Telegram (migration 20270709_381, DL-211).

Owner (8 Nov 2026, card "Build sending Invoices to tenants on Telegram?"): "Invoice + reminder":
each issued Invoice goes to every tenant linked to its Lease, and one reminder goes 3 days before
the due date while it is not fully paid.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_invoice_migration import create_recurring_rent_invoice
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item, refused

LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
REMIND = "SELECT app.telegram_invoice_reminders(%s, %s)"
PAGE = "SELECT app.telegram_invoices_page(%s, %s)"
TENANT = 8850001


@pytest.fixture(scope="module")
def invoice_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_invoice")


@pytest.fixture(scope="module")
def lease(invoice_database: HrDatabase) -> dict[str, uuid.UUID]:
    db = invoice_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, 'Unit 306', '3', 'ONE_BEDROOM', 'VACANT', "
            "%s, %s)",
            (unit_id, db.property_id, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, 'Sok Dara', '012 888 999', %s, %s)",
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
    body = json.loads(item("item-invoice-0001", None))
    body.update(
        telegram_user_id=TENANT, chat_id=TENANT, account={"language": "en", "phone": "+85512888999"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'en', %s)",
        db.property_id,
        TENANT,
        db.manager,
    )
    linked = run(db.runtime_url, LINK, db.property_id, TENANT, "dara sok", "306", db.manager)
    assert linked["result"] == "LINKED"
    return {"unit": unit_id, "customer": customer_id, "lease": lease_id, "day": day}


def invoice(db: HrDatabase, lease: dict[str, Any], months: int, *, issue: bool) -> uuid.UUID:
    first = lease["day"].replace(day=1)
    for _ in range(months):
        first = (first + timedelta(days=32)).replace(day=1)
    with psycopg.connect(db.owner_url) as connection:
        invoice_id, _ = create_recurring_rent_invoice(
            connection,
            actor_id=db.owner,
            customer_id=lease["customer"],
            lease_id=lease["lease"],
            period_start=first,
            issue=issue,
        )
    return invoice_id


def messages(db: HrDatabase, invoice_id: uuid.UUID) -> list[tuple[str, str, int, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT notice.kind, outbox.text_code, outbox.chat_id, outbox.details, outbox.language "
            "FROM app.telegram_invoice_notices AS notice "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
            "WHERE notice.invoice_id = %s ORDER BY notice.created_at",
            (invoice_id,),
        ).fetchall()
    return [(row[0], row[1], row[2], {**row[3], "language": row[4]}) for row in rows]


def test_an_issued_invoice_goes_to_the_linked_tenant_once(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 2, issue=True)
    sent = messages(db, invoice_id)
    assert [(kind, code, chat) for kind, code, chat, _ in sent] == [
        ("ISSUED", "tenant.invoice", TENANT)
    ]
    details = sent[0][3]
    assert details["language"] == "en"
    assert details["unit"] == "Unit 306"
    assert details["total"] == details["to_pay"] == "$800.00"
    assert details["list"] == "• Monthly Rent: $800.00"
    assert details["number"].strip()
    assert len(details["due"]) == 10 and details["due"][2] == "/"
    # Queued again, nobody gets it a second time.
    assert (
        run(
            db.owner_url,
            "SELECT app.telegram_queue_invoice(%s, 'ISSUED', %s)",
            invoice_id,
            db.owner,
        )
        == 0
    )
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    shown = next(row for row in page["invoices"] if row["id"] == str(invoice_id))
    assert [person["telegram_user_id"] for person in shown["sent"]] == [TENANT]
    assert shown["sent"][0]["state"] == "WAITING"
    assert shown["unit_number"] == "Unit 306" and shown["to_pay_usd_cents"] == 80000
    assert page["rules"] == {"remind_days": 3, "days": 45}


def test_a_draft_is_never_sent(invoice_database: HrDatabase, lease: dict[str, Any]) -> None:
    db = invoice_database
    draft = invoice(db, lease, 3, issue=False)
    assert messages(db, draft) == []
    assert (
        run(db.owner_url, "SELECT app.telegram_queue_invoice(%s, 'ISSUED', %s)", draft, db.owner)
        == 0
    )


def test_the_reminder_goes_once_3_days_before_the_due_date(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 4, issue=True)
    day = lease["day"]
    earlier = datetime.now().astimezone() - timedelta(days=2)
    with psycopg.connect(db.owner_url) as owner:
        owner.execute("ALTER TABLE app.invoices DISABLE TRIGGER USER")
        owner.execute(
            "UPDATE app.invoices SET invoice_date = %s, due_date = %s, created_at = %s, "
            "issued_at = %s, updated_at = %s WHERE id = %s",
            (day, day + timedelta(days=2), earlier, earlier, earlier, invoice_id),
        )
        owner.execute("ALTER TABLE app.invoices ENABLE TRIGGER USER")
    after_eight = run(
        db.owner_url,
        "SELECT extract(hour FROM timezone(property.timezone_name, statement_timestamp())) >= 8 "
        "FROM app.properties AS property WHERE property.id = %s",
        db.property_id,
    )
    queued = run(db.runtime_url, REMIND, db.property_id, db.manager)
    if not after_eight:
        # Before 08:00 Property time nothing goes; the next run after 08:00 sends it.
        assert queued == 0
        return
    assert queued == 1
    reminder = [row for row in messages(db, invoice_id) if row[0] == "REMINDER"]
    assert [(code, chat) for _, code, chat, _ in reminder] == [("tenant.invoice_reminder", TENANT)]
    assert reminder[0][3]["to_pay"] == "$800.00"
    assert run(db.runtime_url, REMIND, db.property_id, db.manager) == 0
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    shown = next(row for row in page["invoices"] if row["id"] == str(invoice_id))
    assert shown["reminded_at"] is not None


def test_a_reminder_waits_for_an_invoice_due_later(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 5, issue=True)
    run(db.runtime_url, REMIND, db.property_id, db.manager)
    assert [row[0] for row in messages(db, invoice_id)] == ["ISSUED"]


def test_the_invoice_list_and_reminders_need_the_telegram_rights(
    invoice_database: HrDatabase,
) -> None:
    db = invoice_database
    refused(db.runtime_url, "42501", PAGE, db.property_id, db.staff)
    refused(db.runtime_url, "42501", REMIND, db.property_id, db.staff)
