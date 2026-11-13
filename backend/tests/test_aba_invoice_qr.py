"""ABA QR on every Invoice (DL-180): the Invoice PDF of the approved Brand kit sample and the
PayWay calls (QR with the amount, check, close)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from property_rental import payway
from property_rental.invoice_pdf import (
    InvoicePdfError,
    InvoiceQr,
    amount_to_pay,
    invoice_html,
    invoice_pdf,
    usd,
)

NOW = datetime(2026, 11, 11, 3, 4, 5, tzinfo=UTC)
CONFIG = payway.PayWayConfig(
    host=payway.SANDBOX_HOST,
    merchant_id="ec000001",
    api_key="test-api-key-not-real",
    callback_url="https://relay.example.workers.dev/aba/payway",
)
QR_TEXT = "00020101021230510016sample@abaa5204599953038405406353.005802KH6304ABCD"


def money(cents: int) -> dict[str, Any]:
    return {"minor_units": cents, "currency": "USD"}


def rent_invoice(**changes: Any) -> dict[str, Any]:
    invoice: dict[str, Any] = {
        "status": "UNPAID",
        "invoice_number": "INV260015",
        "invoice_date": "2026-10-25",
        "due_date": "2026-11-05",
        "category": "RENT",
        "billing_period": {"start": "2026-11-01", "end": "2026-11-30"},
        "adjusted_total": money(35300),
        "outstanding_balance": money(35300),
        "active_application_total": money(0),
        "lines": [
            {
                "sequence": 2,
                "category": "SERVICE_CHARGES",
                "description": "Trash Collection",
                "adjusted_amount": money(300),
                "calculation_evidence": {},
            },
            {
                "sequence": 1,
                "category": "RENT",
                "description": "Rent",
                "adjusted_amount": money(35000),
                "calculation_evidence": {},
            },
        ],
    }
    invoice.update(changes)
    return invoice


def qr(amount: int = 35300) -> InvoiceQr:
    import qrcode  # type: ignore[import-untyped]

    image = qrcode.make(QR_TEXT)
    data = io.BytesIO()
    image.save(data, format="PNG")
    return InvoiceQr(png=data.getvalue(), amount_cents=amount, valid_until=date(2026, 11, 10))


def page(invoice: dict[str, Any], amount: int = 35300) -> str:
    return invoice_html(
        invoice, customer_name="Sok Dara", customer_phone="010 000 000", unit="U203", qr=qr(amount)
    )


def test_the_page_is_the_approved_sample_filled_with_the_invoice() -> None:
    html = page(rent_invoice())
    # The template's header, parties, lines (in order), totals, late note and footer.
    for text in (
        "CHETANA Residence",
        "វិក្កយបត្រ",
        "INV260015",
        "25/10/2026",
        "05/11/2026",
        "Sok Dara",
        "Phone 010 000 000",
        "Unit U203",
        "01/11/2026 - 30/11/2026",
        "ថ្លៃឈ្នួល</span>Rent",
        "$350.00",
        "$353.00",
        "a late-payment charge of 10% of the unpaid balance may be added",
        "Live with intention.",
        "Page 1 of 1",
    ):
        assert text in html, text
    assert html.index(">Rent<") < html.index("Trash Collection")
    # The QR box: the amount is already in the QR; no "enter the amount" words, no sample label.
    assert "Scan this QR code to pay" in html
    assert "This QR code works until 10/11/2026" in html
    assert "Enter" not in html and "SAMPLE" not in html
    assert "Paid so far" not in html


def test_a_part_paid_utility_invoice_shows_what_is_paid_and_the_readings() -> None:
    invoice = rent_invoice(
        invoice_number="INV260021",
        category="UTILITIES",
        adjusted_total=money(6480),
        outstanding_balance=money(4480),
        active_application_total=money(2000),
        lines=[
            {
                "sequence": 1,
                "category": "UTILITIES",
                "description": "Electricity",
                "adjusted_amount": money(6000),
                "calculation_evidence": {
                    "utility_type": "ELECTRICITY",
                    "consumption_quantity": 240,
                    "rate_usd_per_unit": "0.25",
                },
            }
        ],
    )
    html = page(invoice, 4480)
    assert "ថ្លៃភ្លើង" in html and "240 kWh \u00d7 $0.25" in html
    assert "Paid so far" in html and "\u2212 $20.00" in html and "$44.80" in html
    assert "late-payment" not in html  # the note is for recurring Rent only


def test_names_are_escaped() -> None:
    html = invoice_html(
        rent_invoice(),
        customer_name="<b>Dara</b>",
        customer_phone=None,
        unit="U203",
        qr=qr(),
    )
    assert "&lt;b&gt;Dara&lt;/b&gt;" in html and "<b>Dara</b>" not in html


@pytest.mark.parametrize(
    ("changes", "amount", "code"),
    [
        ({"status": "DRAFT"}, 35300, "invoice_not_issued"),
        ({"status": "VOID"}, 35300, "invoice_not_issued"),
        ({"status": "PAID", "outstanding_balance": money(0)}, 35300, "invoice_nothing_to_pay"),
        ({}, 35000, "qr_amount_not_balance"),
    ],
)
def test_no_page_without_an_amount_to_pay_in_the_qr(
    changes: dict[str, Any], amount: int, code: str
) -> None:
    with pytest.raises(InvoicePdfError, match=code):
        page(rent_invoice(**changes), amount)


def test_money_is_read_in_cents() -> None:
    assert usd(123450) == "$1,234.50" and usd(5) == "$0.05"
    assert (
        amount_to_pay({"status": "UNPAID", "outstanding_balance": {"minor_units": "4480"}}) == 4480
    )
    assert amount_to_pay({"status": "VOID", "outstanding_balance": money(4480)}) == 0


def test_the_pdf_is_one_a4_page() -> None:
    document = invoice_pdf(
        rent_invoice(), customer_name="Sok Dara", customer_phone=None, unit="U203", qr=qr()
    )
    assert document.startswith(b"%PDF-")
    from weasyprint import HTML  # type: ignore[import-untyped]

    pages = HTML(string=page(rent_invoice())).render().pages
    assert len(pages) == 1
    assert (round(pages[0].width * 25.4 / 96), round(pages[0].height * 25.4 / 96)) == (210, 297)


class FakeAba:
    def __init__(self, *answers: tuple[int, dict[str, Any] | bytes]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        self.calls.append((address, body))
        status, answer = self.answers.pop(0)
        return status, answer if isinstance(answer, bytes) else json.dumps(answer).encode()


def expected_hash(*values: str) -> str:
    digest = hmac.new(CONFIG.api_key.encode(), "".join(values).encode(), hashlib.sha512).digest()
    return base64.b64encode(digest).decode()


def test_the_qr_request_is_signed_in_payways_order() -> None:
    aba = FakeAba(
        (
            200,
            {
                "status": {"code": "0", "message": "Success."},
                "qrString": QR_TEXT,
                "amount": 353,
                "currency": "USD",
            },
        )
    )
    made = payway.generate_qr(
        CONFIG,
        tran_id="INV260015-1",
        amount_cents=35300,
        lifetime_minutes=60,
        now=NOW,
        post_json=aba,
    )
    assert made == payway.PayWayQr("INV260015-1", QR_TEXT, 35300, "USD")
    address, body = aba.calls[0]
    assert address == "https://checkout-sandbox.payway.com.kh" + payway.QR_PATH
    callback = base64.b64encode(CONFIG.callback_url.encode()).decode()  # type: ignore[union-attr]
    assert body["amount"] == "353.00" and body["currency"] == "USD"
    assert body["payment_option"] == "abapay_khqr" and body["lifetime"] == 60
    assert body["hash"] == expected_hash(
        "20261111030405",
        "ec000001",
        "INV260015-1",
        "353.00",
        "abapay_khqr",
        callback,
        "USD",
        "60",
        "template3_color",
    )
    assert CONFIG.api_key not in json.dumps(body)


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        ((200, {"status": {"code": "1"}}), "payway_refused_1"),
        ((200, {"status": {"code": "0"}, "qrString": "nope"}), "payway_bad_answer"),
        (
            (200, {"status": {"code": "0"}, "qrString": QR_TEXT, "amount": "350.00"}),
            "payway_qr_amount_differs",
        ),
        ((500, b""), "payway_http_500"),
        ((429, b""), "payway_too_many"),
        ((200, b"<html>"), "payway_bad_answer"),
    ],
)
def test_a_refused_or_odd_qr_answer_is_a_fixed_code(
    answer: tuple[int, dict[str, Any] | bytes], code: str
) -> None:
    with pytest.raises(payway.PayWayError) as error:
        payway.generate_qr(
            CONFIG,
            tran_id="INV260015-1",
            amount_cents=35300,
            lifetime_minutes=60,
            now=NOW,
            post_json=FakeAba(answer),
        )
    assert error.value.code == code


def test_the_lifetime_stays_within_payways_limits() -> None:
    aba = FakeAba(*[(200, {"status": {"code": "0"}, "qrString": QR_TEXT})] * 2)
    for asked in (1, 10**9):
        payway.generate_qr(
            CONFIG,
            tran_id="INV1",
            amount_cents=35300,
            lifetime_minutes=asked,
            now=NOW,
            post_json=aba,
        )
    assert [body["lifetime"] for _, body in aba.calls] == [3, 43200]


def test_check_reads_what_aba_says_was_paid() -> None:
    aba = FakeAba(
        (
            200,
            {
                "data": {
                    "payment_status_code": 0,
                    "payment_amount": 353.0,
                    "payment_currency": "USD",
                    "apv": "753786",
                    "payment_status": "APPROVED",
                    "transaction_date": "2026-11-11 10:24:00",
                },
                "status": {"code": "00", "message": "Success!", "tran_id": "INV260015-1"},
            },
        ),
        (
            200,
            {
                "data": {
                    "payment_status_code": 2,
                    "payment_status": "PENDING",
                    "payment_amount": 0,
                    "payment_currency": "",
                    "apv": "",
                },
                "status": {"code": "00", "tran_id": "INV260015-2"},
            },
        ),
        (200, {"status": {"code": "6", "message": "tran_id not found"}}),
    )
    paid = payway.check_transaction(CONFIG, "INV260015-1", now=NOW, post_json=aba)
    assert paid.paid and paid.amount_cents == 35300 and paid.currency == "USD"
    assert paid.apv == "753786"
    waiting = payway.check_transaction(CONFIG, "INV260015-2", now=NOW, post_json=aba)
    assert not waiting.paid and waiting.status == "PENDING" and waiting.currency is None
    missing = payway.check_transaction(CONFIG, "INV260015-3", now=NOW, post_json=aba)
    assert missing.status == "NOT_FOUND" and not missing.paid
    assert aba.calls[0][1]["hash"] == expected_hash("20261111030405", "ec000001", "INV260015-1")


def test_close_cancels_an_old_qr() -> None:
    aba = FakeAba((200, {"status": {"code": "00"}}), (200, {"status": {"code": "26"}}))
    assert payway.close_transaction(CONFIG, "INV260015-1", now=NOW, post_json=aba)
    assert not payway.close_transaction(CONFIG, "INV260015-1", now=NOW, post_json=aba)
    assert aba.calls[0][0].endswith(payway.CLOSE_PATH)


@pytest.mark.parametrize(
    ("given", "cents"),
    [
        (0.1, 10),
        ("353.00", 35300),
        (353, 35300),
        ("1.5", 150),
        ("1.005", None),
        ("-1", None),
        (True, None),
        (None, None),
    ],
)
def test_abas_amounts_become_exact_cents(given: Any, cents: int | None) -> None:
    assert payway.cents_of(given) == cents


def test_a_bad_transaction_id_or_amount_never_leaves() -> None:
    with pytest.raises(payway.PayWayError, match="payway_tran_id_invalid"):
        payway.check_transaction(CONFIG, "INV 1; drop", post_json=FakeAba())
    with pytest.raises(payway.PayWayError, match="payway_amount_invalid"):
        payway.amount_text(0)
