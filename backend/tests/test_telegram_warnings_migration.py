"""Warnings go to the tenants linked to the Lease when staff record them (migration 387, DL-217).

Owner (card of 11 Nov 2026, "When staff record it"): the day-20 and day-30 late Rent letters and
Lease warnings go to the tenant on Telegram as soon as staff record them; paper stays official.
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
from test_invoice_migration import create_recurring_rent_invoice
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, item, refused

LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
QUEUE = "SELECT app.telegram_warnings_queue(%s, %s)"
PAGE = "SELECT app.telegram_warnings_page(%s, %s)"
TENANT = 8880001


@pytest.fixture(scope="module")
def warning_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_warning")


@pytest.fixture(scope="module")
def lease(warning_database: HrDatabase) -> dict[str, Any]:
    db = warning_database
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, 'Unit 512', '5', 'ONE_BEDROOM', 'VACANT', "
            "%s, %s)",
            (unit_id, db.property_id, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, 'Heng Dara', '012 888 777', %s, %s)",
            (customer_id, db.owner, db.owner),
        )
        lease_id = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=day - timedelta(days=120),
            end_date=day + timedelta(days=240),
        )
        sign_lease(connection, lease_id, db.owner)
    body = json.loads(item("item-warning-0001", None))
    body.update(
        telegram_user_id=TENANT, chat_id=TENANT, account={"language": "km", "phone": "+85512888777"}
    )
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.manager)
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'km', %s)",
        db.property_id,
        TENANT,
        db.manager,
    )
    linked = run(db.runtime_url, LINK, db.property_id, TENANT, "dara heng", "512", db.manager)
    assert linked["result"] == "LINKED", linked
    # A Rent Invoice due more than 30 days ago and not paid.
    period = (day - timedelta(days=70)).replace(day=1)
    with psycopg.connect(db.owner_url) as connection:
        invoice_id, line_id = create_recurring_rent_invoice(
            connection,
            actor_id=db.owner,
            customer_id=customer_id,
            lease_id=lease_id,
            period_start=period,
            issue=True,
        )
    return {"lease": lease_id, "customer": customer_id, "invoice": invoice_id, "line": line_id}


def sent(db: HrDatabase) -> list[tuple[str, int, str, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT outbox.text_code, outbox.chat_id, outbox.language, outbox.details "
            "FROM app.telegram_warning_notices AS notice "
            "JOIN app.telegram_outbox AS outbox ON outbox.id = notice.outbox_id "
            "ORDER BY notice.created_at"
        ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def rent_event(db: HrDatabase, case: uuid.UUID, kind: str) -> None:
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.rent_nonpayment_events (rent_nonpayment_case_id, event_kind, "
            "event_date, remaining_rent_usd_cents, notice_document_reference, reason, "
            "occurred_at, actor_id) "
            "SELECT rent_case.id, %s, timezone('Asia/Phnom_Penh', moment)::date, "
            "app.invoice_line_outstanding(rent_case.rent_invoice_line_id), 'Letter A-7', "
            "'Rent not paid', moment, %s "
            "FROM app.rent_nonpayment_cases AS rent_case, "
            "(SELECT clock_timestamp() AS moment) AS now WHERE rent_case.id = %s",
            (kind, db.owner, case),
        )


def lease_warning(db: HrDatabase, lease_id: uuid.UUID, number: int, days_ago: int) -> None:
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.lease_violation_warnings (id, lease_id, warning_sequence, "
            "violation_date, warning_date, violation_description, lease_provision, "
            "communication_record, occurred_at, actor_id) "
            "VALUES (%s, %s, %s, current_date - %s - 2, current_date - %s, "
            "'Loud music after 22:00.', 'Clause 12: quiet hours', 'Letter given by hand', "
            "clock_timestamp() - make_interval(days => %s), %s)",
            (uuid.uuid4(), lease_id, number, days_ago, days_ago, days_ago, db.owner),
        )


def test_the_late_rent_letters_go_to_the_linked_tenant_once(
    warning_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = warning_database
    case = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.rent_nonpayment_cases (id, lease_id, customer_id, invoice_id, "
            "rent_invoice_line_id, due_date_snapshot, opened_at, opened_by) "
            "SELECT %s, %s, %s, invoice.id, %s, invoice.due_date, clock_timestamp(), %s "
            "FROM app.invoices AS invoice WHERE invoice.id = %s",
            (case, lease["lease"], lease["customer"], lease["line"], db.owner, lease["invoice"]),
        )
        found = connection.execute(
            "SELECT invoice_number, to_char(due_date, 'DD/MM/YYYY') FROM app.invoices "
            "WHERE id = %s",
            (lease["invoice"],),
        ).fetchone()
    assert found is not None
    number, due = found
    # Opening the case is not a warning: nothing is sent.
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0
    rent_event(db, case, "TWENTY_DAY_WARNING")
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 1
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0
    rent_event(db, case, "THIRTY_DAY_SERIOUS_DEFAULT")
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 1
    messages = sent(db)
    assert [(code, chat, language) for code, chat, language, _ in messages] == [
        ("tenant.rent_warning", TENANT, "km"),
        ("tenant.rent_default", TENANT, "km"),
    ]
    details = messages[0][3]
    assert details["unit"] == "Unit 512" and details["invoice"] == number
    assert details["due"] == due and details["amount"] == "$800.00"
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    kinds = [row["kind"] for row in page["warnings"]]
    assert kinds[:2] == ["RENT_30", "RENT_20"] and page["rules"] == {"days": 90}
    newest = page["warnings"][0]
    assert newest["unit_number"] == "Unit 512" and newest["customer"] == "Heng Dara"
    assert [person["telegram_user_id"] for person in newest["sent"]] == [TENANT]
    assert newest["sent"][0]["state"] == "WAITING"


def test_a_lease_warning_goes_with_the_words_staff_wrote(
    warning_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = warning_database
    before = len(sent(db))
    lease_warning(db, lease["lease"], 1, 0)
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 1
    code, chat, language, details = sent(db)[before]
    assert (code, chat, language) == ("tenant.lease_warning", TENANT, "km")
    assert details["sequence"] == 1 and details["text"] == "Loud music after 22:00."
    assert details["rule"] == "Clause 12: quiet hours" and details["unit"] == "Unit 512"
    # A warning recorded before the last days is history, not news: it is not sent.
    lease_warning(db, lease["lease"], 2, 5)
    assert run(db.runtime_url, QUEUE, db.property_id, db.manager) == 0


def test_warnings_need_the_telegram_rights_and_stay_as_sent(
    warning_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = warning_database
    assert lease
    refused(db.runtime_url, "42501", QUEUE, db.property_id, db.staff)
    refused(db.runtime_url, "42501", PAGE, db.property_id, db.staff)
    with psycopg.connect(db.owner_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.telegram_warning_notices")
    with psycopg.connect(db.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM app.telegram_warning_notices")
