"""The Payments page period read over HTTP (V1-058 R5c-3a; DESIGN.md Summary cards)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from property_rental.identity import AuthenticatedActor
from property_rental.payment_read import PaymentReadNotFoundError, PaymentReadUnavailableError
from test_invoice import actor
from test_payment_api import api
from test_receive_payment_api import ReceiveFlow


@dataclass
class SummaryFlow(ReceiveFlow):
    def summary(
        self, property_id: UUID, start: date, end: date, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((property_id, start, end, actor))
        self.fail()
        return {"from": start.isoformat(), "to": end.isoformat(), "rows": [], "truncated": False}

    def receipt_lines(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((property_id, payment_id, actor))
        self.fail()
        return {"payment_id": str(payment_id), "lines": []}

    def late_charge_card(
        self, property_id: UUID, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object] | None:
        self.calls.append((property_id, invoice_id, actor))
        self.fail()
        return None if invoice_id == self.no_charge else {"invoice_id": str(invoice_id)}

    no_charge: UUID | None = None


def test_the_period_read_needs_payments_read_and_two_dates() -> None:
    flow = SummaryFlow()
    path = f"/api/v1/properties/{flow.property_id}/payments/summary"
    allowed = api(flow, actor(flow.property_id, "payments.read"))
    result = allowed.get(path, params={"from": "2026-10-01", "to": "2026-10-25"})
    assert result.status_code == 200
    assert result.json()["data"]["from"] == "2026-10-01"
    assert flow.calls[-1][:3] == (flow.property_id, date(2026, 10, 1), date(2026, 10, 25))
    before = len(flow.calls)
    assert allowed.get(path, params={"from": "2026-10-01"}).status_code == 422
    assert allowed.get(path, params={"from": "01/10/2026", "to": "2026-10-25"}).status_code == 422
    assert allowed.get(path, params={"from": "2026-10-26", "to": "2026-10-25"}).status_code == 422
    assert allowed.get(path, params={"from": "2024-10-23", "to": "2026-10-25"}).status_code == 422
    extra = {"from": "2026-10-01", "to": "2026-10-25", "x": "1"}
    assert allowed.get(path, params=extra).status_code == 400
    recorder = api(flow, actor(flow.property_id, "payments.record"))
    assert recorder.get(path, params={"from": "2026-10-01", "to": "2026-10-25"}).status_code == 403
    assert len(flow.calls) == before


def test_the_period_read_hides_database_failures() -> None:
    flow = SummaryFlow(error=PaymentReadUnavailableError("private SQL"))
    path = f"/api/v1/properties/{flow.property_id}/payments/summary"
    result = api(flow, actor(flow.property_id, "payments.read")).get(
        path, params={"from": "2026-10-01", "to": "2026-10-25"}
    )
    assert result.status_code == 503 and "private SQL" not in result.text


def test_the_receipt_lines_need_receipts_read_and_hide_a_missing_payment() -> None:
    flow = SummaryFlow()
    payment = uuid4()
    path = f"/api/v1/properties/{flow.property_id}/payments/{payment}/receipt-lines"
    allowed = api(flow, actor(flow.property_id, "receipts.read"))
    result = allowed.get(path)
    assert result.status_code == 200 and result.json()["data"]["payment_id"] == str(payment)
    assert flow.calls[-1][:2] == (flow.property_id, payment)
    before = len(flow.calls)
    assert allowed.get(path, params={"x": "1"}).status_code == 400
    assert api(flow, actor(flow.property_id, "payments.read")).get(path).status_code == 403
    assert len(flow.calls) == before
    missing = SummaryFlow(error=PaymentReadNotFoundError("private SQL"))
    path = f"/api/v1/properties/{missing.property_id}/payments/{payment}/receipt-lines"
    result = api(missing, actor(missing.property_id, "receipts.read")).get(path)
    assert result.status_code == 404 and "private SQL" not in result.text


def test_the_late_charge_card_needs_invoices_read_and_is_null_without_a_charge() -> None:
    """V1-058 R5d: the late-payment card of one Invoice."""
    flow = SummaryFlow()
    invoice = uuid4()
    path = f"/api/v1/properties/{flow.property_id}/invoices/{invoice}/late-charge"
    allowed = api(flow, actor(flow.property_id, "invoices.read"))
    result = allowed.get(path)
    assert result.status_code == 200 and result.json()["data"]["invoice_id"] == str(invoice)
    assert flow.calls[-1][:2] == (flow.property_id, invoice)
    flow.no_charge = invoice
    assert allowed.get(path).json()["data"] is None
    before = len(flow.calls)
    assert allowed.get(path, params={"x": "1"}).status_code == 400
    assert api(flow, actor(flow.property_id, "payments.read")).get(path).status_code == 403
    assert len(flow.calls) == before
    broken = SummaryFlow(error=PaymentReadUnavailableError("private SQL"))
    path = f"/api/v1/properties/{broken.property_id}/invoices/{invoice}/late-charge"
    result = api(broken, actor(broken.property_id, "invoices.read")).get(path)
    assert result.status_code == 503 and "private SQL" not in result.text
