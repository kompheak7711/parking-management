"""ABA QR on every Invoice, step 2 (DL-180): the QR of each Invoice message, the PDF sent on
Telegram, ABA's "paid" hint from the relay and the check that records the Payment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from property_rental import aba_qr, payway
from property_rental.operations_config import OperationsConfigError, _aba_payway
from property_rental.telegram_pull_job import run_pull
from property_rental.telegram_send_job import caption_of, run_send
from test_aba_invoice_qr import CONFIG, QR_TEXT, money, rent_invoice
from test_telegram_jobs import TOKEN, FakeRelay, FakeStore, _client, _update

NOW = datetime(2026, 11, 11, 3, 4, 5, tzinfo=UTC)
INVOICE_ID = "6d0f6a59-79a5-4d43-8f3c-3b0d7b6f2a11"
CUSTOMER_ID = "0b1f86c4-1bd4-4b8a-9b60-46b55a1f6c01"


class FakeAba:
    """The office database side of the QRs, kept in lists."""

    def __init__(self, info: dict[str, Any] | None = None) -> None:
        self.info = info
        self.qrs: list[dict[str, Any]] = []
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.checks: list[dict[str, Any]] = []

    def invoice_for_outbox(self, outbox_id: str) -> dict[str, Any] | None:
        return self.info

    def record_qr(
        self, invoice_id: str, tran_id: str, amount_cents: int, qr_string: str, expires_at: datetime
    ) -> None:
        self.qrs.append(
            {
                "invoice_id": invoice_id,
                "tran_id": tran_id,
                "amount_usd_cents": amount_cents,
                "qr_string": qr_string,
                "expires_at": expires_at,
            }
        )

    def record_event(self, tran_id: str, kind: str, details: Mapping[str, Any]) -> bool:
        self.events.append((tran_id, kind, dict(details)))
        return True

    def to_check(self) -> list[dict[str, Any]]:
        return self.checks

    def payment_method_id(self, code: str | None) -> UUID | None:
        return None


def invoice_info(to_pay: int = 35300, **changes: Any) -> dict[str, Any]:
    paid = money(35300 - to_pay)
    info: dict[str, Any] = {
        "invoice_id": INVOICE_ID,
        "invoice": rent_invoice(
            outstanding_balance=money(to_pay),
            active_application_total=paid,
            status="UNPAID" if to_pay == 35300 else "PARTIALLY_PAID" if to_pay else "PAID",
        ),
        "customer_name": "Sok Dara",
        "customer_phone": "012 888 999",
        "unit": "U306",
        "to_pay_usd_cents": to_pay,
        "due_date": "2026-11-05",
        "today": "2026-11-11",
        "timezone": "Asia/Phnom_Penh",
        "qr_count": 0,
        "open_qrs": [],
    }
    info.update(changes)
    return info


class FakePayWay:
    """ABA's PayWay answers, by the path asked."""

    def __init__(self, check: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.check = check

    def __call__(self, address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        path = address.removeprefix(f"https://{payway.SANDBOX_HOST}")
        self.calls.append((path, body))
        if path == payway.QR_PATH:
            answer = {
                "status": {"code": "0", "message": "Success."},
                "qrString": QR_TEXT,
                "amount": body["amount"],
                "currency": "USD",
            }
        elif path == payway.CLOSE_PATH:
            answer = {"status": {"code": "00"}}
        elif path in (payway.CHECK_PATH, payway.DETAIL_PATH):
            answer = self.check or {"status": {"code": "6"}}
        else:
            return 404, b""
        return 200, json.dumps(answer).encode()

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]


def test_the_qr_works_until_5_days_after_the_due_date_and_at_least_3_days() -> None:
    # Due 05/11: works to the end of 10/11 in Phnom Penh (17:00 UTC is midnight there).
    end = aba_qr.qr_expiry(date(2026, 11, 5), date(2026, 11, 1), "Asia/Phnom_Penh", NOW)
    assert end == datetime(2026, 11, 10, 16, 59, 59, tzinfo=UTC)
    # Sent on 11/11, after that: 3 more days.
    late = aba_qr.qr_expiry(date(2026, 11, 5), date(2026, 11, 11), "Asia/Phnom_Penh", NOW)
    assert late == datetime(2026, 11, 14, 16, 59, 59, tzinfo=UTC)
    # Never longer than PayWay allows (30 days).
    far = aba_qr.qr_expiry(date(2027, 3, 1), date(2026, 11, 11), "Asia/Phnom_Penh", NOW)
    assert far == NOW + timedelta(days=30)


def test_an_invoice_message_gets_a_new_qr_with_the_amount_to_pay() -> None:
    store, aba = FakeAba(invoice_info()), FakePayWay()
    made = aba_qr.invoice_document("m1", store=store, config=CONFIG, now=NOW, post_json=aba)
    assert made is not None
    assert made.pdf.startswith(b"%PDF") and made.file_name == "INV260015.pdf"
    assert made.tran_id == "INV260015-1"
    assert aba.paths() == [payway.QR_PATH]
    sent = aba.calls[0][1]
    assert (sent["tran_id"], sent["amount"], sent["currency"]) == ("INV260015-1", "353.00", "USD")
    # Sent 11/11, after the Due Date + 5: works 3 more days.
    assert sent["lifetime"] == pytest.approx(int((store_end() - NOW).total_seconds() / 60), abs=1)
    assert store.qrs == [
        {
            "invoice_id": INVOICE_ID,
            "tran_id": "INV260015-1",
            "amount_usd_cents": 35300,
            "qr_string": QR_TEXT,
            "expires_at": store_end(),
        }
    ]
    assert store.events == []


def store_end() -> datetime:
    return datetime(2026, 11, 14, 16, 59, 59, tzinfo=UTC)


def test_an_open_qr_of_the_same_amount_is_used_again() -> None:
    open_qr = {
        "tran_id": "INV260015-1",
        "amount_usd_cents": 35300,
        "qr_string": QR_TEXT,
        "expires_at": "2026-11-14T16:59:59+00:00",
    }
    store, aba = FakeAba(invoice_info(qr_count=1, open_qrs=[open_qr])), FakePayWay()
    made = aba_qr.invoice_document("m1", store=store, config=CONFIG, now=NOW, post_json=aba)
    assert made is not None and made.tran_id == "INV260015-1"
    assert aba.calls == [] and store.qrs == []


def test_after_a_part_payment_a_new_qr_replaces_the_old_one() -> None:
    open_qr = {
        "tran_id": "INV260015-1",
        "amount_usd_cents": 35300,
        "qr_string": QR_TEXT,
        "expires_at": "2026-11-14T16:59:59+00:00",
    }
    store = FakeAba(invoice_info(15300, qr_count=1, open_qrs=[open_qr]))
    aba = FakePayWay()
    made = aba_qr.invoice_document("m1", store=store, config=CONFIG, now=NOW, post_json=aba)
    assert made is not None and made.tran_id == "INV260015-2"
    assert aba.paths() == [payway.QR_PATH, payway.CLOSE_PATH]
    assert aba.calls[0][1]["amount"] == "153.00"
    assert aba.calls[1][1]["tran_id"] == "INV260015-1"
    assert store.events == [("INV260015-1", "CLOSED", {"replaced_by": "INV260015-2"})]


def test_no_pdf_for_a_paid_invoice_or_another_message() -> None:
    aba = FakePayWay()
    for info in (None, invoice_info(0)):
        made = aba_qr.invoice_document(
            "m1", store=FakeAba(info), config=CONFIG, now=NOW, post_json=aba
        )
        assert made is None
    assert aba.calls == []


def test_a_payway_refusal_is_raised_so_the_message_waits() -> None:
    def refuse(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        return 200, json.dumps({"status": {"code": "1", "message": "Wrong hash"}}).encode()

    store = FakeAba(invoice_info())
    with pytest.raises(payway.PayWayError, match="payway_refused_1"):
        aba_qr.invoice_document("m1", store=store, config=CONFIG, now=NOW, post_json=refuse)
    assert store.qrs == []


def to_check(
    tran_id: str = "INV260015-1",
    amount: int = 35300,
    created_at: str = "2026-11-10T03:00:00+00:00",
    expires_at: str = "2026-11-14T16:59:59+00:00",
) -> dict[str, Any]:
    return {
        "tran_id": tran_id,
        "invoice_id": INVOICE_ID,
        "customer_id": CUSTOMER_ID,
        "lease_id": None,
        "amount_usd_cents": amount,
        "created_at": created_at,
        "expires_at": expires_at,
        "paid": False,
    }


def aba_says(status: str, code: int, amount: Any = 353.0, currency: str = "USD") -> FakePayWay:
    return FakePayWay(
        {
            "status": {"code": "00", "tran_id": "INV260015-1"},
            "data": {
                "payment_status": status,
                "payment_status_code": code,
                "payment_amount": amount,
                "payment_currency": currency,
                "apv": "654321",
                "transaction_date": "2026-11-11 10:24:00",
            },
        }
    )


def test_an_approved_qr_of_the_right_amount_is_recorded_once() -> None:
    store = FakeAba()
    store.checks = [to_check()]
    recorded: list[tuple[Mapping[str, Any], payway.PayWayTransaction]] = []

    def record(qr: Mapping[str, Any], answer: payway.PayWayTransaction) -> dict[str, Any]:
        recorded.append((qr, answer))
        return {"payment_id": "p-1"}

    result = aba_qr.check_payments(
        store=store,
        config=CONFIG,
        record_payment=record,
        now=NOW,
        post_json=aba_says("APPROVED", 0),
    )
    assert (result.checked, result.recorded, result.needs_check) == (1, 1, 0)
    assert recorded[0][1].apv == "654321" and recorded[0][1].amount_cents == 35300
    assert [kind for _, kind, _ in store.events] == ["PAID", "PAYMENT_RECORDED"]
    assert store.events[1][2] == {"payment_id": "p-1"}
    # The Payment's key comes from the transaction: a second try saves nothing new.
    assert aba_qr.payment_key("INV260015-1") == aba_qr.payment_key("INV260015-1")
    assert aba_qr.payment_key("INV260015-1") != aba_qr.payment_key("INV260015-2")


@pytest.mark.parametrize(
    ("amount", "currency", "recorder", "reason"),
    [
        (100.0, "USD", True, "amount_differs"),
        (353.0, "KHR", True, "amount_differs"),
        (353.0, "USD", False, "not_recorded_here"),
    ],
)
def test_a_payment_not_as_the_qr_asked_waits_for_the_staff(
    amount: float, currency: str, recorder: bool, reason: str
) -> None:
    store = FakeAba()
    store.checks = [to_check()]
    called: list[str] = []

    def record(qr: Mapping[str, Any], answer: payway.PayWayTransaction) -> dict[str, Any]:
        called.append(answer.tran_id)
        return {"payment_id": "p-1"}

    result = aba_qr.check_payments(
        store=store,
        config=CONFIG,
        record_payment=record if recorder else None,
        now=NOW,
        post_json=aba_says("APPROVED", 0, amount, currency),
    )
    assert (result.recorded, result.needs_check) == (0, 1)
    assert called == []
    assert [kind for _, kind, _ in store.events] == ["PAID", "NEEDS_CHECK"]
    assert store.events[1][2]["reason"] == reason


def test_a_payment_the_ledger_refuses_waits_for_the_staff() -> None:
    store = FakeAba()
    store.checks = [to_check()]

    def refuse(qr: Mapping[str, Any], answer: payway.PayWayTransaction) -> dict[str, Any]:
        raise RuntimeError("closed period")

    result = aba_qr.check_payments(
        store=store,
        config=CONFIG,
        record_payment=refuse,
        now=NOW,
        post_json=aba_says("APPROVED", 0),
    )
    assert result.needs_check == 1
    assert store.events[-1][1:] == (
        "NEEDS_CHECK",
        {
            "amount_usd_cents": 35300,
            "currency": "USD",
            "apv": "654321",
            "paid_at": "2026-11-11 10:24:00",
            "reason": "RuntimeError",
        },
    )


def test_unpaid_expired_and_failed_checks() -> None:
    store = FakeAba()
    store.checks = [to_check()]
    waiting = aba_qr.check_payments(
        store=store,
        config=CONFIG,
        record_payment=None,
        now=NOW,
        post_json=aba_says("PENDING", 2),
    )
    assert (waiting.checked, waiting.recorded, waiting.needs_check) == (1, 0, 0)
    assert store.events == []
    # After the QR stopped working, an unpaid one is closed in our records.
    later = NOW + timedelta(days=4)
    aba_qr.check_payments(
        store=store, config=CONFIG, record_payment=None, now=later, post_json=FakePayWay()
    )
    assert store.events == [("INV260015-1", "EXPIRED", {"status": "NOT_FOUND"})]
    # ABA cannot be reached: counted with a fixed code, tried again later.

    def down(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        return 503, b""

    failed = aba_qr.check_payments(
        store=store, config=CONFIG, record_payment=None, now=NOW, post_json=down
    )
    assert (failed.failed, failed.codes) == (1, ["payway_http_503"])


def test_a_qr_older_than_abas_check_window_is_read_with_transaction_details() -> None:
    # Sent 10 days before its Due Date: the QR works for 15 days, ABA's Check knows 7.
    old = (NOW - timedelta(days=9)).isoformat()
    lasts = (NOW + timedelta(days=6)).isoformat()
    store = FakeAba()
    store.checks = [
        to_check(f"INV2600{n:02d}-1", created_at=old, expires_at=lasts) for n in range(10)
    ]
    store.checks.append(to_check("INV260099-1"))
    aba = aba_says("APPROVED", 0)

    def answer(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        assert aba.check is not None
        aba.check["status"]["tran_id"] = body["tran_id"]
        return aba(address, body)

    result = aba_qr.check_payments(
        store=store, config=CONFIG, record_payment=None, now=NOW, post_json=answer
    )
    # Eight older ones a run (ABA allows 10 a minute), the new one by Check; the rest next run.
    assert aba.paths().count(payway.DETAIL_PATH) == 8
    assert aba.paths().count(payway.CHECK_PATH) == 1
    assert result.checked == 9 and result.needs_check == 9
    assert {kind for _, kind, _ in store.events} == {"PAID", "NEEDS_CHECK"}


def test_a_qr_abas_never_answers_for_goes_to_the_staff_after_it_expires() -> None:
    def down(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        return 503, b""

    store = FakeAba()
    store.checks = [to_check(expires_at=(NOW - timedelta(days=1)).isoformat())]
    aba_qr.check_payments(store=store, config=CONFIG, record_payment=None, now=NOW, post_json=down)
    assert store.events == [], "tried again while ABA may still answer"
    store.checks = [to_check(expires_at=(NOW - timedelta(days=3)).isoformat())]
    late = aba_qr.check_payments(
        store=store, config=CONFIG, record_payment=None, now=NOW, post_json=down
    )
    assert (late.failed, late.needs_check) == (1, 1)
    assert store.events == [("INV260015-1", "NEEDS_CHECK", {"reason": "no_answer_after_expiry"})]


def test_only_the_hinted_transactions_are_checked() -> None:
    store = FakeAba()
    store.checks = [to_check("INV260015-1"), to_check("INV260016-1")]
    aba = FakePayWay()
    result = aba_qr.check_payments(
        store=store,
        config=CONFIG,
        record_payment=None,
        only=["INV260016-1"],
        now=NOW,
        post_json=aba,
    )
    assert result.checked == 1
    assert [body["tran_id"] for _, body in aba.calls] == ["INV260016-1"]


def test_abas_time_is_phnom_penh_time() -> None:
    assert aba_qr.moment_of("2026-11-11 10:24:00") == datetime(2026, 11, 11, 3, 24, tzinfo=UTC)
    assert aba_qr.moment_of("11/11/2026") is None and aba_qr.moment_of(None) is None


def test_the_full_check_runs_every_10_minutes(tmp_path: Path) -> None:
    marker = tmp_path / "aba-payway-check.time"
    assert aba_qr.check_due(marker, NOW)
    aba_qr.mark_checked(marker, NOW)
    assert not aba_qr.check_due(marker, NOW + timedelta(minutes=9))
    assert aba_qr.check_due(marker, NOW + timedelta(minutes=10))


def invoice_message(message_id: str = "i1") -> dict[str, Any]:
    return {
        "id": message_id,
        "bot": "TENANT",
        "chat_id": 777,
        "text_code": "tenant.invoice",
        "language": "en",
        "details": {
            "number": "INV260015",
            "unit": "U306",
            "list": "• Monthly Rent: $350.00\n• Trash Collection: $3.00",
            "total": "$353.00",
            "to_pay": "$353.00",
            "due": "05/11/2026",
        },
        "buttons": None,
    }


def test_an_invoice_goes_as_the_pdf_with_the_message_as_caption() -> None:
    store = FakeStore()
    store.due = [
        invoice_message("i1"),
        {**invoice_message("i2"), "text_code": "tenant.invoice_paid"},
    ]
    documents: list[tuple[str, dict[str, str], tuple[str, bytes]]] = []
    texts: list[dict[str, Any]] = []
    asked: list[str] = []

    def make(outbox_id: str) -> aba_qr.InvoiceDocument | None:
        asked.append(outbox_id)
        return aba_qr.InvoiceDocument(b"%PDF-1.7 test", "INV260015.pdf", "INV260015-1")

    def post_document(
        address: str, fields: dict[str, str], document: tuple[str, bytes]
    ) -> tuple[int, bytes]:
        documents.append((address, fields, document))
        return 200, json.dumps({"ok": True, "result": {"message_id": 70}}).encode()

    def post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        texts.append(body)
        return 200, json.dumps({"ok": True, "result": {"message_id": 71}}).encode()

    result = run_send(
        store=store,
        api_host="api.telegram.org",
        tokens={"TENANT": TOKEN},
        post_json=post_json,
        invoice_documents=make,
        post_document=post_document,
    )
    assert result.sent == 2
    assert asked == ["i1"], "only Invoice messages get the PDF"
    address, fields, document = documents[0]
    assert address == f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    assert fields["chat_id"] == "777"
    assert fields["caption"].startswith("🧾 New Invoice INV260015")
    assert document == ("INV260015.pdf", b"%PDF-1.7 test")
    assert len(texts) == 1 and "Already paid in full" in texts[0]["text"]
    assert store.attempts == [("i1", "SENT", None, 70), ("i2", "SENT", None, 71)]


def test_an_invoice_waits_while_its_qr_cannot_be_made() -> None:
    store = FakeStore()
    store.due = [invoice_message()]
    posts: list[Any] = []

    def post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        posts.append(body)
        return 200, b""

    def post_document(
        address: str, fields: dict[str, str], document: tuple[str, bytes]
    ) -> tuple[int, bytes]:
        posts.append(fields)
        return 200, b""

    def not_ready(outbox_id: str) -> aba_qr.InvoiceDocument | None:
        raise payway.PayWayError("payway_not_ready")

    def broken(outbox_id: str) -> aba_qr.InvoiceDocument | None:
        raise OSError("font missing")

    for make, code in ((not_ready, "payway_not_ready"), (broken, "invoice_pdf_failed")):
        result = run_send(
            store=store,
            api_host="api.telegram.org",
            tokens={"TENANT": TOKEN},
            post_json=post_json,
            invoice_documents=make,
            post_document=post_document,
        )
        assert result.failed == 1 and result.sent == 0
        assert store.attempts[-1] == ("i1", "FAILED", code, None)
    assert posts == [], "never sent without its QR"


def test_a_long_message_is_cut_to_telegrams_caption_limit() -> None:
    assert caption_of("short") == "short"
    cut = caption_of("x" * 2000)
    assert len(cut) == 1024 and cut.endswith("…")


def test_abas_hint_from_the_relay_is_only_a_transaction_to_check(
    tmp_path: Path,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    relay, store = FakeRelay(key), FakeStore()
    relay.add("item-aba-1", {"v": 1, "payload": {"tran_id": "INV260015-1"}, "media": []})
    relay.items["item-aba-1"]["kind"] = "aba"
    relay.add("item-aba-2", {"v": 1, "payload": {"tran_id": "not ok;"}, "media": []})
    relay.items["item-aba-2"]["kind"] = "aba"
    relay.add("item-0003", _update("hello", 13))
    result = run_pull(client=_client(relay), key=key, store=store, media_directory=tmp_path)
    assert result.aba_tran_ids == ["INV260015-1"]
    assert result.refused_codes == ["aba_unreadable"]
    assert list(store.items) == ["item-0003"], "a hint is never saved as a chat message"
    assert relay.items == {}, "all three are confirmed"


def test_the_operations_file_names_payway_by_its_host_and_secret_files() -> None:
    aba = _aba_payway(
        {
            "enabled": True,
            "host": payway.SANDBOX_HOST,
            "merchant_id_file": "/run/secrets/prm_aba_merchant_id",
            "api_key_file": "/run/secrets/prm_aba_api_key",
            "payment_method_code": "ABA_KHQR",
        }
    )
    assert aba is not None and aba.enabled and aba.payment_method_code == "ABA_KHQR"
    assert aba.api_key_file == Path("/run/secrets/prm_aba_api_key")
    assert _aba_payway(None) is None
    with pytest.raises(OperationsConfigError, match="sandbox or live"):
        _aba_payway({"enabled": True, "host": "evil.example.com"})


def test_payway_turned_on_without_keys_stops_invoice_messages(tmp_path: Path) -> None:
    class Operations:
        aba_payway = _aba_payway(
            {
                "enabled": True,
                "host": payway.SANDBOX_HOST,
                "merchant_id_file": str(tmp_path / "missing-merchant"),
                "api_key_file": str(tmp_path / "missing-key"),
                "payment_method_code": "ABA_KHQR",
            }
        )

        class telegram_bots:
            relay_host = "relay.example.workers.dev"

    with pytest.raises(payway.PayWayError, match="payway_keys_missing"):
        aba_qr.load_job(
            Operations(),
            database_url="postgresql://unused",
            financial_database_url=None,
            property_id=UUID(int=1),
            actor_id=UUID(int=2),
        )

    class Off:
        aba_payway = None
        telegram_bots = Operations.telegram_bots

    assert (
        aba_qr.load_job(
            Off(),
            database_url="postgresql://unused",
            financial_database_url=None,
            property_id=UUID(int=1),
            actor_id=UUID(int=2),
        )
        is None
    )


def test_the_pdf_never_says_unit_twice() -> None:
    from property_rental.invoice_pdf import invoice_html
    from test_aba_invoice_qr import qr

    for unit in ("U306", "Unit U306"):
        page = invoice_html(
            rent_invoice(), customer_name="Sok Dara", customer_phone=None, unit=unit, qr=qr()
        )
        assert "Unit U306" in page and "Unit Unit" not in page
