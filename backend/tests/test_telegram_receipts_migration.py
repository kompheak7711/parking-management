"""Receipts go to linked tenants on Telegram (migration 20270713_385, DL-215).

Owner (11 Nov 2026): CHETANA Residence support sends Receipts too, the first of "Receipts, then
notices, then warnings". The pull job queues each new Receipt for the people linked to the Lease
or stay it paid, once, with what the money paid.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from payment_test_support import database_instant, seed_method, seed_payment
from property_rental.payment_confirmation import ConfirmUsdPaymentCommand
from property_rental.receive_payment import PaysTarget, ReceivePaymentCommand, ReceivePaymentService
from test_credit_migration import actor
from test_hr_employees_migration import HrDatabase, make_hr_database, run
from test_invoice_migration import create_recurring_rent_invoice
from test_khr_payment_confirmation import provider
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item, refused

LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
QUEUE = "SELECT app.telegram_receipts_queue(%s, %s)"
PAGE = "SELECT app.telegram_receipts_page(%s, %s)"
TENANT = 8860001


@pytest.fixture(scope="module")
def receipt_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_receipt")


@pytest.fixture(scope="module")
def lease(receipt_database: HrDatabase) -> dict[str, Any]:
    db = receipt_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, 'Unit 407', '4', 'ONE_BEDROOM', 'VACANT', "
            "%s, %s)",
            (unit_id, db.property_id, db.owner, db.owner),
        )
        for person, name in ((customer_id, "Keo Sreymom"), (other, "Lim Bora")):
            connection.execute(
                "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
                "VALUES (%s, %s, '012 777 666', %s, %s)",
                (person, name, db.owner, db.owner),
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
    body = json.loads(item("item-receipt-0001", None))
    body.update(
        telegram_user_id=TENANT, chat_id=TENANT, account={"language": "en", "phone": "+85512777666"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'en', %s)",
        db.property_id,
        TENANT,
        db.manager,
    )
    linked = run(db.runtime_url, LINK, db.property_id, TENANT, "sreymom keo", "407", db.manager)
    assert linked["result"] == "LINKED"
    first = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    with psycopg.connect(db.owner_url) as connection:
        invoice_id, _ = create_recurring_rent_invoice(
            connection,
            actor_id=db.owner,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=first,
            issue=True,
        )
    return {"customer": customer_id, "other": other, "lease": lease_id, "invoice": invoice_id}


def receipts(db: HrDatabase, payment: str) -> list[tuple[str, int, str, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT outbox.text_code, outbox.chat_id, outbox.language, outbox.details "
            "FROM app.telegram_receipt_notices AS notice "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
            "JOIN app.receipts AS receipt ON receipt.id = notice.receipt_id "
            "WHERE receipt.payment_id = %s ORDER BY notice.created_at",
            (payment,),
        ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def test_a_payment_sends_its_receipt_with_what_it_paid_once(
    receipt_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = receipt_database
    with psycopg.connect(db.owner_url) as connection:
        method = seed_method(connection, db.owner)
        at = database_instant(connection) - timedelta(seconds=1)
        number = connection.execute(
            "SELECT invoice_number FROM app.invoices WHERE id = %s", (lease["invoice"],)
        ).fetchone()
    assert number is not None
    command = ReceivePaymentCommand(
        ConfirmUsdPaymentCommand(uuid.uuid4(), lease["customer"], method, 90_000, at, "Desk"),
        "OLDEST_FIRST",
        (PaysTarget("INVOICE", lease["invoice"], 80_000),),
    )
    made = ReceivePaymentService(db.financial_url, provider()).receive(
        db.property_id,
        command,
        actor=actor(db.owner, db.property_id, "payments.record", "payments.allocate"),
    )
    payment = str(made["payment"]["id"])  # type: ignore[index]
    # Nothing is sent before the pull job runs, then once.
    assert receipts(db, payment) == []
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 1
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0
    sent = receipts(db, payment)
    assert [(code, chat, language) for code, chat, language, _ in sent] == [
        ("tenant.receipt", TENANT, "en")
    ]
    details = sent[0][3]
    assert details["amount"] == "$900.00" and details["unit"] == "Unit 407"
    assert details["list"] == (
        f"• Invoice {number[0]}: $800.00\n• Not used yet (kept for you): $100.00"
    )
    with psycopg.connect(db.owner_url) as connection:
        payment_number = connection.execute(
            "SELECT payment_number FROM app.payments WHERE id = %s", (payment,)
        ).fetchone()
        receipt = connection.execute(
            "SELECT id FROM app.receipts WHERE payment_id = %s", (payment,)
        ).fetchone()
        assert receipt is not None
        khmer = connection.execute(
            "SELECT app.telegram_receipt_details(%s, 'km')", (receipt[0],)
        ).fetchone()
    assert payment_number is not None and details["number"] == payment_number[0]
    assert khmer is not None and khmer[0]["list"].startswith("• វិក្កយបត្រ ")
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    row = next(one for one in page["receipts"] if one["number"] == payment_number[0])
    assert [person["telegram_user_id"] for person in row["sent"]] == [TENANT]
    assert row["sent"][0]["state"] == "WAITING" and page["rules"] == {"days": 45}


def test_a_receipt_of_someone_not_linked_is_not_sent(
    receipt_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = receipt_database
    with psycopg.connect(db.owner_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=db.owner,
            property_id=db.property_id,
            customer_id=lease["other"],
            amount=5_000,
        )
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0
    assert receipts(db, str(payment)) == []


def test_receipts_need_the_telegram_rights_and_stay_as_sent(
    receipt_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = receipt_database
    assert lease
    refused(db.runtime_url, "42501", QUEUE, db.property_id, db.staff)
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.telegram_receipt_notices")
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM app.telegram_receipt_notices")
