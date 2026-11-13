"""The Invoice as an A4 PDF (ABA QR plan, owner 11 Nov 2026): the owner-approved Invoice sample of
the Brand kit (05_Templates/invoice-template.html, approved 12 and 17 Oct 2026), made on the
office computer so the Tenant bot can send it.

The page is the template's own markup and styles; only the sample label is left out. The QR box
holds the PayWay QR of this Invoice, with the amount to pay already inside, so its words say
"scan" instead of "enter the amount". WeasyPrint draws the page because it joins Khmer letters
(reportlab does not). Nothing here reads the database: the caller passes the Invoice resource
(``app.invoice_resource_snapshot``) and the Customer, Unit and QR.
"""

from __future__ import annotations

import base64
import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

ASSETS: Final = Path(__file__).with_name("invoice_pdf_assets")
TIMES: Final = "\u00d7"  # the template's multiplication sign
MINUS: Final = "\u2212"  # the template's minus sign before "Paid so far"

# The template's styles (invoice-template.html), with the font files of this package. The grey
# page around the sheet and the "SAMPLE" label are for the sample file only.
STYLE: Final = (ASSETS / "invoice.css").read_text(encoding="utf-8")

# Khmer before each line, by what the line bills (frontend InvoiceDocument.tsx, same words).
KHMER_CATEGORY: Final = {
    "RENT": "ថ្លៃឈ្នួល",
    "SERVICE_CHARGES": "ថ្លៃសេវា",
    "MISCELLANEOUS_CHARGES": "ថ្លៃផ្សេងៗ",
    "DAMAGE_CHARGES": "ថ្លៃខូចខាត",
}


class InvoicePdfError(ValueError):
    """The Invoice cannot be made into a PDF to send (a draft, a void, or nothing to pay)."""


@dataclass(frozen=True)
class InvoiceQr:
    """The PayWay QR of this Invoice: its picture (PNG), the amount inside it and its last day."""

    png: bytes
    amount_cents: int
    valid_until: date


def usd(cents: int) -> str:
    """$1,234.50, the way the template writes dollars."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{part:02d}"


def day_text(value: str | date | None) -> str:
    """dd/mm/yyyy (owner 12 Oct 2026)."""
    if value is None or value == "":
        return "—"
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return day.strftime("%d/%m/%Y")


def _cents(value: Any) -> int:
    """A money object of the resource ({"amount": "12.50"} or {"minor_units": 1250}) in cents."""
    if isinstance(value, Mapping):
        minor = value.get("minor_units")
        if isinstance(minor, int) and not isinstance(minor, bool):
            return minor
        if isinstance(minor, str) and minor.lstrip("-").isdigit():
            return int(minor)
        value = value.get("amount")
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).strip()
    negative = text.startswith("-")
    whole, _, part = text.lstrip("-").partition(".")
    cents = int(whole or "0") * 100 + int((part + "00")[:2])
    return -cents if negative else cents


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() != "" else None


def _number(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return str(value)
    return value.strip() if isinstance(value, str) and value.strip() != "" else None


def _period(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    start, end = _text(value.get("start")), _text(value.get("end"))
    return None if start is None or end is None else f"{day_text(start)} - {day_text(end)}"


def _khmer(line: Mapping[str, Any], short_stay: Any) -> str:
    if short_stay == "SHORT_STAY":
        return "ថ្លៃស្នាក់នៅ"
    if short_stay == "SHORT_STAY_DAMAGE":
        return "ថ្លៃខូចខាត"
    evidence = line.get("calculation_evidence") or {}
    if line.get("category") == "UTILITIES":
        kind = evidence.get("utility_type")
        return {"WATER": "ថ្លៃទឹក", "ELECTRICITY": "ថ្លៃភ្លើង"}.get(str(kind), "ថ្លៃទឹកភ្លើង")
    return KHMER_CATEGORY.get(str(line.get("category")), "ថ្លៃផ្សេងៗ")


def _detail(line: Mapping[str, Any]) -> str | None:
    evidence = line.get("calculation_evidence") or {}
    if line.get("category") == "UTILITIES":
        quantity, rate = (
            _number(evidence.get("consumption_quantity")),
            _number(evidence.get("rate_usd_per_unit")),
        )
        if quantity is None or rate is None:
            return None
        unit = "m³" if evidence.get("utility_type") == "WATER" else "kWh"
        try:
            quantity = f"{float(quantity):,.10g}"
        except ValueError:
            return None
        return f"{quantity} {unit} {TIMES} ${rate}"
    if line.get("category") == "MISCELLANEOUS_CHARGES":
        quantity, price = evidence.get("quantity"), evidence.get("unit_price_usd_cents")
        if isinstance(quantity, int) and isinstance(price, int):
            if not isinstance(quantity, bool) and not isinstance(price, bool):
                return f"{quantity:,} {TIMES} {usd(price)}"
    return None


def _initial_rent(lines: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        line.get("category") == "RENT"
        and (line.get("calculation_evidence") or {}).get("billing_kind") == "INITIAL"
        for line in lines
    )


def _label(kh: str, en: str) -> str:
    return f'<span class="lbl"><span class="kh">{kh}</span><span class="en">{en}</span></span>'


def amount_to_pay(invoice: Mapping[str, Any]) -> int:
    """What is still to pay on an issued Invoice, in cents (0 for drafts and voids)."""
    if invoice.get("status") in ("DRAFT", "VOID"):
        return 0
    return max(0, _cents(invoice.get("outstanding_balance")))


def invoice_html(
    invoice: Mapping[str, Any],
    *,
    customer_name: str | None,
    customer_phone: str | None,
    unit: str | None,
    qr: InvoiceQr,
) -> str:
    """The page as HTML: the approved template filled with this Invoice."""
    status = invoice.get("status")
    if status in ("DRAFT", "VOID"):
        raise InvoicePdfError("invoice_not_issued")
    owed = amount_to_pay(invoice)
    if owed <= 0:
        raise InvoicePdfError("invoice_nothing_to_pay")
    if qr.amount_cents != owed:
        raise InvoicePdfError("qr_amount_not_balance")
    e = html.escape
    number = e(str(invoice.get("invoice_number") or "—"))
    lines = sorted(invoice.get("lines") or [], key=lambda line: int(line.get("sequence") or 0))
    period = _period(invoice.get("billing_period")) or next(
        (found for found in (_period(line.get("period")) for line in lines) if found), None
    )
    total = _cents(invoice.get("adjusted_total"))
    # "Paid so far" as the Invoice page shows it (invoicesData paidOf).
    paid = max(0, min(total, _cents(invoice.get("active_application_total"))))
    rows = []
    for line in lines:
        detail = _detail(line)
        rows.append(
            '<tr><td><div class="cat"><span class="kh">'
            f"{_khmer(line, invoice.get('short_stay'))}</span>"
            f"{e(str(line.get('description') or ''))}"
            "</div>"
            + (f'<div class="det">{e(detail)}</div>' if detail else "")
            + f'</td><td class="r">{usd(_cents(line.get("adjusted_amount")))}</td></tr>'
        )
    paid_row = (
        f'<div class="row">{_label("បានបង់រួច", "Paid so far")}'
        f'<span class="n">{MINUS} {usd(paid)}</span></div>'
        if paid > 0
        else ""
    )
    # The approved late-payment note: recurring Rent only, never the Initial Rent (BR-RENT-009).
    note = (
        '<p class="note"><span class="kh">ប្រសិនបើមិនបង់ទាន់ថ្ងៃកំណត់ អាចមានការគិតថ្លៃបង់យឺត ១០% '
        "នៃសមតុល្យមិនទាន់បង់។</span>If this Invoice is not paid by the Due Date, a late-payment "
        "charge of 10% of the unpaid balance may be added.</p>"
        if invoice.get("category") == "RENT" and not _initial_rent(lines)
        else ""
    )
    qr_src = "data:image/png;base64," + base64.b64encode(qr.png).decode("ascii")
    amount = usd(owed)
    until = day_text(qr.valid_until)
    phone = f"<small>Phone {e(customer_phone)}</small>" if customer_phone else ""
    period_html = f"<small>{e(period)}</small>" if period else ""
    # A Unit number may be kept as "U203" or as "Unit 203": the page says "Unit" once.
    unit_name = unit.strip().removeprefix("Unit ").strip() if unit else ""
    unit_html = f"Unit {e(unit_name)}" if unit_name else ""
    style = STYLE.replace("FONT_DIR", ASSETS.as_uri())
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{number}</title><style>{style}</style></head><body>"
        '<article class="doc a4" lang="en">'
        '<div class="top"><div><img class="logo" src="'
        f'{(ASSETS / "CHETANA_Logo_Horizontal_FullColor.svg").as_uri()}" alt="CHETANA">'
        '<div class="biz"><b>CHETANA Residence</b></div></div>'
        '<div class="title"><span class="kh">វិក្កយបត្រ</span><span class="en">Invoice</span>'
        '<table class="meta">'
        f'<tr><td>{_label("លេខវិក្កយបត្រ", "Invoice No.")}</td><td class="dd">{number}</td></tr>'
        f"<tr><td>{_label('កាលបរិច្ឆេទ', 'Invoice date')}</td>"
        f'<td class="dd">{day_text(invoice.get("invoice_date"))}</td></tr>'
        f"<tr><td>{_label('ថ្ងៃកំណត់បង់', 'Due date')}</td>"
        f'<td class="dd">{day_text(invoice.get("due_date"))}</td></tr>'
        "</table></div></div><hr>"
        f'<div class="parties"><div><div class="v">{e(customer_name or "—")}{phone}</div></div>'
        f'<div><div class="v">{unit_html}{period_html}</div></div></div>'
        f"<table><thead><tr><th>{_label('ការពិពណ៌នា', 'Description')}</th>"
        f'<th class="r">{_label("ចំនួនទឹកប្រាក់", "Amount (USD)")}</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
        f'<div class="sum"><div class="row">{_label("សរុប", "Total")}'
        f'<span class="n">{usd(total)}</span>'
        f"</div>{paid_row}"
        f'<div class="due">{_label("សមតុល្យត្រូវបង់", "Balance due")}<span class="n">{amount}</span>'
        f"</div></div>{note}"
        '<div class="push"></div>'
        f'<section class="pay"><img src="{qr_src}" alt="ABA KHQR code for {number}">'
        "<div><p>"
        # The Khmer of the scan words waits for the native check like the other new texts.
        f'<span class="kh">សូមស្កេនឃ្យូអកូដនេះដើម្បីបង់ប្រាក់។ ទឹកប្រាក់ <b>{amount}</b> '
        f'សម្រាប់ <span class="ref">{number}</span> មាននៅក្នុងឃ្យូអកូដរួចហើយ។</span>'
        f"Scan this QR code to pay. The amount <b>{amount}</b> for "
        f'<span class="ref">{number}</span> '
        "is already in the QR code."
        f'<span class="until"><span class="kh">ឃ្យូអកូដនេះប្រើបានដល់ថ្ងៃ {until}</span>'
        f"This QR code works until {until}.</span>"
        "</p></div></section>"
        f'<div class="foot"><span>{number} · Page 1 of 1</span>'
        '<span class="tag">Live with intention.</span></div>'
        "</article></body></html>"
    )


def invoice_pdf(
    invoice: Mapping[str, Any],
    *,
    customer_name: str | None,
    customer_phone: str | None,
    unit: str | None,
    qr: InvoiceQr,
) -> bytes:
    """The A4 PDF of the Invoice (one page)."""
    # Imported here: it loads Pango, which only the sender needs.
    from weasyprint import HTML  # type: ignore[import-untyped]

    page = invoice_html(
        invoice, customer_name=customer_name, customer_phone=customer_phone, unit=unit, qr=qr
    )
    document = HTML(string=page, base_url=ASSETS.as_uri()).write_pdf()
    if not isinstance(document, bytes):  # pragma: no cover - write_pdf without a target
        raise InvoicePdfError("pdf_not_made")
    return document
