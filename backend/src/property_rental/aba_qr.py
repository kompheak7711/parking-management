"""ABA QR on every Invoice (DL-180; owner 11 Nov 2026, all recommended answers).

1. ``invoice_document``: for an Invoice message of the Tenant bot, the A4 PDF of the approved
   Invoice sample with an ABA PayWay QR that holds what is still to pay. An open QR of that amount
   is used again; otherwise PayWay makes a new one and the older open QRs of the Invoice are
   closed (answer 1: a part payment gets a new QR). A QR works until 5 days after the Due Date
   (answer 3); an Invoice sent later gets 3 days.
2. ``check_payments``: asks ABA about open QRs. When ABA says APPROVED for exactly the QR's
   amount in USD, the Payment is recorded by itself (answer 4) into the Invoice as named ticks,
   with ABA's approval code as its reference; any other answer is saved as NEEDS_CHECK for the
   staff. The QR's transaction id makes the Payment's key, so a payment is never saved twice.

Late-payment charges are not in the QR (answer 2). Every Invoice the Tenant bot sends gets one
(answer 5). The office jobs run this; ABA's message to the relay only says "look at this one":
the money is always taken from ABA's own answer to our check.
"""

from __future__ import annotations

import io
import json
import math
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from property_rental import payway
from property_rental.invoice_pdf import InvoiceQr, amount_to_pay, invoice_pdf

DAYS_AFTER_DUE: Final = 5  # owner answer 3
LATE_SEND_DAYS: Final = 3  # an Invoice sent after that still gets a QR for 3 days
INVOICE_MESSAGES: Final = frozenset({"tenant.invoice", "tenant.invoice_reminder"})
# The Payment key of a QR payment: the same transaction always gives the same key.
PAYMENT_KEYS: Final = uuid.UUID("6f1d0c5e-6a0e-4b5e-9a35-1b0f2b6c4a80")


class AbaStore(Protocol):
    def invoice_for_outbox(self, outbox_id: str) -> dict[str, Any] | None: ...

    def record_qr(
        self,
        invoice_id: str,
        tran_id: str,
        amount_cents: int,
        qr_string: str,
        expires_at: datetime,
    ) -> None: ...

    def record_event(self, tran_id: str, kind: str, details: Mapping[str, Any]) -> bool: ...

    def to_check(self) -> list[dict[str, Any]]: ...

    def payment_method_id(self, code: str) -> UUID | None: ...


class PostgresAbaStore:
    def __init__(self, database_url: str, *, property_id: UUID, actor_id: UUID) -> None:
        self._url = database_url
        self._property = property_id
        self._actor = actor_id

    def __repr__(self) -> str:
        return f"PostgresAbaStore(property={self._property})"

    def _one(self, query: str, *values: object) -> Any:
        with psycopg.connect(self._url, autocommit=True) as connection:
            row = connection.execute(query, values).fetchone()
        return None if row is None else row[0]

    def invoice_for_outbox(self, outbox_id: str) -> dict[str, Any] | None:
        result = self._one(
            "SELECT app.aba_invoice_for_outbox(%s, %s, %s)",
            self._property,
            UUID(outbox_id),
            self._actor,
        )
        return result if isinstance(result, dict) else None

    def record_qr(
        self,
        invoice_id: str,
        tran_id: str,
        amount_cents: int,
        qr_string: str,
        expires_at: datetime,
    ) -> None:
        self._one(
            "SELECT app.aba_record_qr(%s, %s, %s, %s, %s, %s, %s)",
            self._property,
            UUID(invoice_id),
            tran_id,
            amount_cents,
            qr_string,
            expires_at,
            self._actor,
        )

    def record_event(self, tran_id: str, kind: str, details: Mapping[str, Any]) -> bool:
        return (
            self._one(
                "SELECT app.aba_record_qr_event(%s, %s, %s, %s::jsonb, %s)",
                self._property,
                tran_id,
                kind,
                json.dumps(dict(details)),
                self._actor,
            )
            is not None
        )

    def to_check(self) -> list[dict[str, Any]]:
        result = self._one("SELECT app.aba_qr_to_check(%s, %s)", self._property, self._actor)
        return result if isinstance(result, list) else []

    def payment_method_id(self, code: str) -> UUID | None:
        result = self._one(
            "SELECT app.aba_payment_method(%s, %s, %s)", self._property, code, self._actor
        )
        return result if isinstance(result, UUID) else None


def qr_expiry(due: date, today: date, zone: str, now: datetime) -> datetime:
    """The end of the 5th day after the Due Date (Property time); at least 3 days from now."""
    local = ZoneInfo(zone)
    last_day = max(due + timedelta(days=DAYS_AFTER_DUE), today + timedelta(days=LATE_SEND_DAYS))
    end = datetime.combine(last_day + timedelta(days=1), time(0), tzinfo=local) - timedelta(
        seconds=1
    )
    return min(end, now + timedelta(minutes=payway.MAX_LIFETIME_MINUTES))


def qr_png(qr_string: str) -> bytes:
    import qrcode  # type: ignore[import-untyped]
    from qrcode.constants import ERROR_CORRECT_M  # type: ignore[import-untyped]

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=0)
    code.add_data(qr_string)
    code.make(fit=True)
    data = io.BytesIO()
    code.make_image().save(data, format="PNG")
    return data.getvalue()


def _date(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


CHECK_WINDOW: Final = timedelta(days=7) - timedelta(hours=1)
DETAIL_CALLS_PER_RUN: Final = 8
NO_ANSWER_AFTER_EXPIRY: Final = timedelta(days=2)


def _instant(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class InvoiceDocument:
    pdf: bytes
    file_name: str
    tran_id: str


def invoice_document(
    outbox_id: str,
    *,
    store: AbaStore,
    config: payway.PayWayConfig,
    now: datetime | None = None,
    post_json: payway.PostJson | None = None,
) -> InvoiceDocument | None:
    """The PDF for an Invoice message, or None when the message is not about an Invoice to pay
    (a paid Invoice's message goes as text). PayWay problems raise ``payway.PayWayError``: the
    send job tries again later, so no Invoice goes without its QR."""
    info = store.invoice_for_outbox(outbox_id)
    if info is None:
        return None
    invoice = info["invoice"]
    # The QR asks for exactly the Balance due the page shows (late charges are not in it).
    to_pay = amount_to_pay(invoice)
    if to_pay <= 0:
        return None
    moment = now or datetime.now(UTC)
    calls: dict[str, Any] = {} if post_json is None else {"post_json": post_json}
    open_qrs: list[dict[str, Any]] = list(info.get("open_qrs") or [])
    same = next((qr for qr in open_qrs if int(qr["amount_usd_cents"]) == to_pay), None)
    if same is not None:
        tran_id, qr_string, expires = (
            same["tran_id"],
            same["qr_string"],
            _instant(same["expires_at"]),
        )
    else:
        expires = qr_expiry(
            _date(info["due_date"]), _date(info["today"]), str(info["timezone"]), moment
        )
        tran_id = f"{invoice['invoice_number']}-{int(info.get('qr_count') or 0) + 1}"
        made = payway.generate_qr(
            config,
            tran_id=tran_id,
            amount_cents=to_pay,
            lifetime_minutes=math.ceil((expires - moment).total_seconds() / 60),
            now=moment,
            **calls,
        )
        store.record_qr(str(info["invoice_id"]), tran_id, to_pay, made.qr_string, expires)
        qr_string = made.qr_string
        # The older QRs ask for an amount that is no longer right: ABA closes them. If ABA
        # cannot, they stay open and checked, and a payment on one is a Needs check item.
        for old in open_qrs:
            try:
                if payway.close_transaction(config, old["tran_id"], now=moment, **calls):
                    store.record_event(old["tran_id"], "CLOSED", {"replaced_by": tran_id})
            except payway.PayWayError:
                continue
    zone = ZoneInfo(str(info["timezone"]))
    pdf = invoice_pdf(
        invoice,
        customer_name=info.get("customer_name"),
        customer_phone=info.get("customer_phone"),
        unit=info.get("unit"),
        qr=InvoiceQr(qr_png(qr_string), to_pay, expires.astimezone(zone).date()),
    )
    return InvoiceDocument(pdf, f"{invoice['invoice_number']}.pdf", tran_id)


# Records a Payment from ABA: (customer, lease, invoice, cents, paid at, tran_id, approval code)
# -> the saved result. Tests replace it.
RecordPayment = Callable[[Mapping[str, Any], payway.PayWayTransaction], dict[str, Any]]


@dataclass
class CheckResult:
    checked: int = 0
    recorded: int = 0
    needs_check: int = 0
    failed: int = 0
    codes: list[str] = field(default_factory=list)


def check_payments(
    *,
    store: AbaStore,
    config: payway.PayWayConfig,
    record_payment: RecordPayment | None,
    only: Iterable[str] | None = None,
    now: datetime | None = None,
    post_json: payway.PostJson | None = None,
) -> CheckResult:
    """Ask ABA about the QRs to check (``only``: just these transaction ids)."""
    result = CheckResult()
    moment = now or datetime.now(UTC)
    calls: dict[str, Any] = {} if post_json is None else {"post_json": post_json}
    wanted = None if only is None else set(only)
    detail_calls = 0
    for qr in store.to_check():
        tran_id = str(qr["tran_id"])
        if wanted is not None and tran_id not in wanted:
            continue
        # A QR lives until its Due Date + 5 days, longer than ABA's 7-day Check window.
        older = _instant(qr["created_at"]) < moment - CHECK_WINDOW
        if older:
            if detail_calls >= DETAIL_CALLS_PER_RUN:
                continue  # the rest wait for the next run (ABA allows 10 a minute)
            detail_calls += 1
        result.checked += 1
        try:
            answer = payway.check_transaction(config, tran_id, now=moment, older=older, **calls)
        except payway.PayWayError as error:
            result.failed += 1
            result.codes.append(error.code)
            if _instant(qr["expires_at"]) + NO_ANSWER_AFTER_EXPIRY < moment:
                # Never silently dropped: the staff look it up in PayWay.
                store.record_event(tran_id, "NEEDS_CHECK", {"reason": "no_answer_after_expiry"})
                result.needs_check += 1
            continue
        if not answer.paid:
            if answer.status in ("NOT_FOUND", "PENDING") and _instant(qr["expires_at"]) < moment:
                store.record_event(tran_id, "EXPIRED", {"status": answer.status})
            elif answer.status in ("CANCELLED", "DECLINED", "REFUNDED"):
                store.record_event(tran_id, "EXPIRED", {"status": answer.status})
            continue
        seen = {
            "amount_usd_cents": answer.amount_cents,
            "currency": answer.currency,
            "apv": answer.apv,
            "paid_at": answer.paid_at,
        }
        store.record_event(tran_id, "PAID", seen)
        if answer.currency != "USD" or answer.amount_cents != int(qr["amount_usd_cents"]):
            store.record_event(tran_id, "NEEDS_CHECK", seen | {"reason": "amount_differs"})
            result.needs_check += 1
            continue
        if record_payment is None:
            # No money database for this job: the staff record it from Needs check.
            store.record_event(tran_id, "NEEDS_CHECK", seen | {"reason": "not_recorded_here"})
            result.needs_check += 1
            continue
        try:
            saved = record_payment(qr, answer)
        except Exception as error:  # the staff record it from Needs check
            code = getattr(error, "code", None) or type(error).__name__
            store.record_event(tran_id, "NEEDS_CHECK", seen | {"reason": str(code)[:60]})
            result.needs_check += 1
            continue
        store.record_event(tran_id, "PAYMENT_RECORDED", {"payment_id": saved.get("payment_id")})
        result.recorded += 1
    return result


def payment_key(tran_id: str) -> UUID:
    return uuid.uuid5(PAYMENT_KEYS, tran_id)


def receive_payment_recorder(
    financial_database_url: str,
    *,
    property_id: UUID,
    actor_id: UUID,
    payment_method_id: UUID,
) -> RecordPayment:
    """Record a QR payment as staff would in Receive payment: the payer's own USD money, named to
    the QR's Invoice, with ABA's approval code as the reference."""
    from property_rental.identity import AuthenticatedActor, CapabilityGrant
    from property_rental.payment_confirmation import ConfirmUsdPaymentCommand
    from property_rental.receive_payment import (
        PaysTarget,
        ReceivePaymentCommand,
        ReceivePaymentService,
    )

    scope = frozenset({str(property_id)})
    actor = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(capability=capability, property_ids=scope)
            for capability in ("payments.record", "payments.allocate")
        ),
    )
    service = ReceivePaymentService(financial_database_url)

    def record(qr: Mapping[str, Any], answer: payway.PayWayTransaction) -> dict[str, Any]:
        cents = int(qr["amount_usd_cents"])
        paid_at = moment_of(answer.paid_at) or datetime.now(UTC)
        reference = f"ABA KHQR {answer.tran_id}" + (f" APV {answer.apv}" if answer.apv else "")
        command = ReceivePaymentCommand(
            confirmation=ConfirmUsdPaymentCommand(
                idempotency_key=payment_key(answer.tran_id),
                payer_customer_id=UUID(str(qr["customer_id"])),
                payment_method_id=payment_method_id,
                received_amount_minor=cents,
                received_at=paid_at,
                evidence_reference=reference,
                lease_id=UUID(str(qr["lease_id"])) if qr.get("lease_id") else None,
                channel_transaction_reference=answer.tran_id,
            ),
            mode="NAMED",
            targets=(PaysTarget("INVOICE", UUID(str(qr["invoice_id"])), cents),),
        )
        saved = service.receive(property_id, command, actor=actor)
        payment = saved.get("payment")
        payment_id = payment.get("id") if isinstance(payment, dict) else None
        return {"payment_id": str(payment_id) if payment_id else None}

    return record


def moment_of(text: str | None) -> datetime | None:
    """ABA's transaction time ("2026-11-11 10:24:00", Phnom Penh time) as an instant."""
    if not text:
        return None
    try:
        local = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return local.replace(tzinfo=ZoneInfo("Asia/Phnom_Penh")).astimezone(UTC)


CHECK_EVERY: Final = timedelta(minutes=10)


@dataclass(frozen=True)
class AbaJob:
    """PayWay as the office jobs use it: the store, the PayWay keys and the Payment recorder."""

    store: AbaStore
    config: payway.PayWayConfig
    record_payment: RecordPayment | None


def load_job(
    operations: Any,
    *,
    database_url: str,
    financial_database_url: str | None,
    property_id: UUID,
    actor_id: UUID,
) -> AbaJob | None:
    """The PayWay job from the operations file, or None while it is off."""
    aba = getattr(operations, "aba_payway", None)
    bots = getattr(operations, "telegram_bots", None)
    if aba is None or not aba.enabled or bots is None:
        return None
    config = payway.load_config(
        host=aba.host,
        merchant_id_file=aba.merchant_id_file,
        api_key_file=aba.api_key_file,
        callback_url=f"https://{bots.relay_host}/aba/payway",
    )
    if config is None:
        # Turned on without readable keys: Invoice messages wait (never sent without a QR).
        raise payway.PayWayError("payway_keys_missing")
    store = PostgresAbaStore(database_url, property_id=property_id, actor_id=actor_id)
    recorder: RecordPayment | None = None
    method = store.payment_method_id(aba.payment_method_code)
    if financial_database_url and method is not None:
        recorder = receive_payment_recorder(
            financial_database_url,
            property_id=property_id,
            actor_id=actor_id,
            payment_method_id=method,
        )
    return AbaJob(store, config, recorder)


def check_due(status_file: Path, now: datetime) -> bool:
    """True when the last full check is older than 10 minutes (the time is kept in a file)."""
    try:
        last = datetime.fromisoformat(status_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return now - last >= CHECK_EVERY


def mark_checked(status_file: Path, now: datetime) -> None:
    try:
        status_file.write_text(now.isoformat(), encoding="utf-8")
    except OSError:
        pass
