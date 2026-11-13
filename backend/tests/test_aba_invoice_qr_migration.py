"""ABA QR records (migration 20270717_340, DL-180): the QR of each Invoice message, its events,
the QRs to check with ABA and a QR payment saved through Receive payment."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from property_rental import aba_qr, payway
from test_aba_invoice_qr import CONFIG, QR_TEXT
from test_aba_qr_jobs import FakePayWay
from test_hr_employees_migration import HrDatabase, make_hr_database, refused, run
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_tenant_invoices_migration import invoice, lease

__all__ = ["lease", "migrated_database_url"]


@pytest.fixture(scope="module")
def invoice_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_aba_qr")


def outbox_of(db: HrDatabase, invoice_id: uuid.UUID) -> uuid.UUID:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT outbox_id FROM app.telegram_invoice_notices WHERE invoice_id = %s "
            "AND kind = 'ISSUED'",
            (invoice_id,),
        ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def store(db: HrDatabase) -> aba_qr.PostgresAbaStore:
    return aba_qr.PostgresAbaStore(db.runtime_url, property_id=db.property_id, actor_id=db.manager)


def test_a_qr_is_kept_with_its_invoice_and_its_events_once(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 4, issue=True)
    outbox = outbox_of(db, invoice_id)
    office = store(db)

    info = office.invoice_for_outbox(str(outbox))
    assert info is not None
    assert info["invoice_id"] == str(invoice_id)
    assert info["to_pay_usd_cents"] == 80000
    assert info["customer_name"] == "Sok Dara" and info["unit"] == "Unit 306"
    assert (info["qr_count"], info["open_qrs"]) == (0, [])
    assert info["invoice"]["invoice_number"] and info["timezone"]
    assert office.invoice_for_outbox(str(uuid.uuid4())) is None

    # The send job makes the PDF: PayWay is asked once, the QR is kept.
    aba = FakePayWay()
    made = aba_qr.invoice_document(str(outbox), store=office, config=CONFIG, post_json=aba)
    assert made is not None and made.pdf.startswith(b"%PDF")
    number = info["invoice"]["invoice_number"]
    assert made.tran_id == f"{number}-1"
    assert aba.calls[0][1]["amount"] == "800.00"
    again = office.invoice_for_outbox(str(outbox))
    assert again is not None and again["qr_count"] == 1
    assert [qr["tran_id"] for qr in again["open_qrs"]] == [made.tran_id]
    # The reminder uses the same QR: PayWay is not asked again.
    aba_qr.invoice_document(str(outbox), store=office, config=CONFIG, post_json=aba)
    assert len(aba.calls) == 1

    waiting = [qr for qr in office.to_check() if qr["tran_id"] == made.tran_id]
    assert waiting and waiting[0]["customer_id"] == str(lease["customer"])
    assert waiting[0]["lease_id"] == str(lease["lease"]) and waiting[0]["paid"] is False

    # A QR stays on the list for its whole life, also after ABA's 7-day Check window.
    with psycopg.connect(db.owner_url) as owner:
        owner.execute("ALTER TABLE app.aba_qr_requests DISABLE TRIGGER USER")
        owner.execute(
            "UPDATE app.aba_qr_requests SET created_at = created_at - interval '9 days' "
            "WHERE tran_id = %s",
            (made.tran_id,),
        )
        owner.execute("ALTER TABLE app.aba_qr_requests ENABLE TRIGGER USER")
    assert made.tran_id in [qr["tran_id"] for qr in office.to_check()]

    assert office.record_event(made.tran_id, "PAID", {"apv": "654321"}) is True
    assert office.record_event(made.tran_id, "PAID", {"apv": "654321"}) is False, "kept once"
    assert [qr["paid"] for qr in office.to_check() if qr["tran_id"] == made.tran_id] == [True]
    assert office.record_event(made.tran_id, "NEEDS_CHECK", {"reason": "amount_differs"})
    assert made.tran_id not in [qr["tran_id"] for qr in office.to_check()]
    closed = office.invoice_for_outbox(str(outbox))
    assert closed is not None and closed["open_qrs"] == []

    with psycopg.connect(db.owner_url) as owner:
        with pytest.raises(psycopg.Error, match="append-only"):
            owner.execute("UPDATE app.aba_qr_requests SET amount_usd_cents = 1")
    with psycopg.connect(db.owner_url) as owner:
        with pytest.raises(psycopg.Error, match="append-only"):
            owner.execute("DELETE FROM app.aba_qr_events")


def test_only_the_office_jobs_reach_the_qr_records(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 5, issue=True)
    expires = datetime.now(UTC) + timedelta(days=3)
    record = "SELECT app.aba_record_qr(%s, %s, %s, %s, %s, %s, %s)"
    # A bad transaction id or a QR text that is not a KHQR is refused by the table.
    refused(
        db.runtime_url,
        "23514",
        record,
        db.property_id,
        invoice_id,
        "bad id;",
        100,
        QR_TEXT,
        expires,
        db.manager,
    )
    refused(
        db.runtime_url,
        "23514",
        record,
        db.property_id,
        invoice_id,
        "INVX-1",
        100,
        "not a qr",
        expires,
        db.manager,
    )
    # Only people with the Telegram right: Staff have none.
    refused(
        db.runtime_url,
        "42501",
        record,
        db.property_id,
        invoice_id,
        "INVX-1",
        100,
        QR_TEXT,
        expires,
        db.staff,
    )
    unknown = "SELECT app.aba_record_qr_event(%s, %s, 'PAID', '{}'::jsonb, %s)"
    refused(db.runtime_url, "P0002", unknown, db.property_id, "NOPE-1", db.manager)
    with psycopg.connect(db.runtime_url) as runtime:
        assert runtime.execute(
            "SELECT has_table_privilege('prm_runtime', 'app.aba_qr_requests', 'SELECT'),"
            "has_table_privilege('prm_runtime', 'app.aba_qr_events', 'INSERT'),"
            "has_function_privilege('prm_runtime', 'app.aba_qr_open(uuid)', 'EXECUTE')"
        ).fetchone() == (False, False, False)
    assert store(db).payment_method_id("NO-SUCH-METHOD") is None


def test_an_approved_qr_is_saved_as_a_payment_into_its_invoice_once(
    invoice_database: HrDatabase, lease: dict[str, Any]
) -> None:
    db = invoice_database
    invoice_id = invoice(db, lease, 6, issue=True)
    outbox = outbox_of(db, invoice_id)
    office = store(db)
    made = aba_qr.invoice_document(str(outbox), store=office, config=CONFIG, post_json=FakePayWay())
    assert made is not None
    code = f"ABA-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(db.owner_url) as owner:
        owner.execute(
            "INSERT INTO app.payment_methods(id,code,display_name,accepted,created_by,updated_by) "
            "VALUES (%s,%s,'ABA KHQR',true,%s,%s)",
            (uuid.uuid4(), code, db.owner, db.owner),
        )
    method = office.payment_method_id(code)
    assert method is not None
    recorder = aba_qr.receive_payment_recorder(
        db.financial_url, property_id=db.property_id, actor_id=db.manager, payment_method_id=method
    )
    paid_at = (datetime.now(UTC) - timedelta(minutes=5)).astimezone(ZoneInfo("Asia/Phnom_Penh"))
    aba = FakePayWay(
        {
            "status": {"code": "00", "tran_id": made.tran_id},
            "data": {
                "payment_status": "APPROVED",
                "payment_status_code": 0,
                "payment_amount": 800.0,
                "payment_currency": "USD",
                "apv": "654321",
                "transaction_date": paid_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
    )
    result = aba_qr.check_payments(
        store=office, config=CONFIG, record_payment=recorder, only=[made.tran_id], post_json=aba
    )
    assert (result.recorded, result.needs_check, result.failed) == (1, 0, 0), result
    with psycopg.connect(db.owner_url) as owner:
        payment = owner.execute(
            "SELECT payment.received_amount_minor, payment.channel_transaction_reference, "
            "invoice.status FROM app.payments AS payment "
            "JOIN app.payment_allocations AS allocation ON allocation.payment_id = payment.id "
            "JOIN app.invoices AS invoice ON invoice.id = allocation.invoice_id "
            "WHERE allocation.invoice_id = %s",
            (invoice_id,),
        ).fetchall()
        events = owner.execute(
            "SELECT event.kind FROM app.aba_qr_events AS event "
            "JOIN app.aba_qr_requests AS request ON request.id = event.request_id "
            "WHERE request.tran_id = %s ORDER BY event.created_at",
            (made.tran_id,),
        ).fetchall()
    assert payment == [(80000, made.tran_id, "PAID")]
    assert [row[0] for row in events] == ["PAID", "PAYMENT_RECORDED"]
    # Saved again with the same key (no answer the first time): still one Payment.
    qr = {
        "tran_id": made.tran_id,
        "invoice_id": str(invoice_id),
        "customer_id": str(lease["customer"]),
        "lease_id": str(lease["lease"]),
        "amount_usd_cents": 80000,
    }
    answer = payway.check_transaction(CONFIG, made.tran_id, post_json=aba)
    assert recorder(qr, answer)["payment_id"]
    assert (
        run(
            db.owner_url,
            "SELECT count(*) FROM app.payments WHERE channel_transaction_reference = %s",
            made.tran_id,
        )
        == 1
    )
