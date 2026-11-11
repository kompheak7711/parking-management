"""The office side of the Telegram bots: the pull job, the send job, the relay calls, phone
numbers, the fixed texts and the health warnings (bots plan 03/11/2026, step 1)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from property_rental import telegram_relay_client
from property_rental.operations_status import evaluate_warnings
from property_rental.telegram_phone import normalize_phone
from property_rental.telegram_pull_job import ITEMS_EVERY_SECONDS, items_due, note_items, run_pull
from property_rental.telegram_relay_client import RelayClient, RelayError, signature
from property_rental.telegram_seal import seal_for_tests
from property_rental.telegram_send_job import load_bot_tokens, run_send
from property_rental.telegram_store import StaffBotUnavailable
from property_rental.telegram_texts import TextError, render

PULL_KEY = bytes.fromhex("11" * 32)
NOW = 1_793_000_000
TOKEN = "123456:" + "A" * 35


@pytest.fixture(scope="module")
def office_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


class FakeRelay:
    """The relay's office API, checking every signature like the real one."""

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        self.public = key.public_key()
        self.items: dict[str, dict[str, Any]] = {}
        self.media: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.fail_confirm = False
        self.pushed: list[tuple[str, Any]] = []

    def add(
        self, item_id: str, plain: dict[str, Any], media: dict[str, bytes] | None = None
    ) -> None:
        media = media or {}
        for media_id, data in media.items():
            self.media[media_id] = seal_for_tests(self.public, data, media_id)
        self.items[item_id] = {
            "id": item_id,
            "bot": "TENANT",
            "kind": "update",
            "received_at": "2026-11-04T09:00:00+00:00",
            "sealed": base64.b64encode(
                seal_for_tests(self.public, json.dumps(plain).encode(), item_id)
            ).decode(),
            "media": list(media),
        }

    def transport(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        path = url.removeprefix("https://relay.example.workers.dev")
        moment = int(headers["X-Office-Time"])
        expected = signature(PULL_KEY, moment, method, path, body)
        if not hmac.compare_digest(expected, headers["X-Office-Signature"]):
            return 401, b""
        self.calls.append(f"{method} {path}")
        if path.startswith("/office/items"):
            answer = {
                "items": list(self.items.values()),
                "waiting": len(self.items),
                "oldest_at": None,
                "dropped": 2,
            }
            return 200, json.dumps(answer).encode()
        if path.startswith("/office/media/"):
            return 200, self.media[path.rsplit("/", 1)[1]]
        if (
            path.startswith(("/office/access/", "/office/choices/", "/office/offline/"))
            and method == "PUT"
        ):
            self.pushed.append((path, json.loads(body)))
            return 200, b'{"count": 1}'
        if path == "/office/confirm":
            if self.fail_confirm:
                return 503, b""
            ids = json.loads(body)["ids"]
            for item_id in ids:
                self.items.pop(item_id, None)
            return 200, json.dumps({"deleted": len(ids)}).encode()
        return 404, b""


class FakeStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.runs: list[dict[str, Any]] = []
        self.queued: list[dict[str, Any]] = []
        self.due: list[dict[str, Any]] = []
        self.attempts: list[tuple[str, str, str | None, int | None]] = []
        # The Tenant bot side (migration 20270520_282), kept in memory.
        self.languages: dict[int, str] = {}
        self.steps: dict[int, tuple[str, dict[str, Any]]] = {}
        self.replies: list[dict[str, Any]] = []
        self.reply_to: list[str | None] = []
        self.phones: set[int] = set()
        self.links: dict[int, dict[str, Any]] = {}
        self.link_answers: list[dict[str, Any]] = []
        self.link_tries: list[tuple[int, str, str]] = []
        # The Problem report forms (migration 20270521_283).
        self.form_data: dict[str, Any] = {"choices": {"types": []}, "users": []}
        self.report_answers: list[dict[str, Any]] = []
        self.reports: list[tuple[str, dict[str, Any], list[str]]] = []
        # The Tenant bot while the office is away (migration 20270708_380, DL-210).
        self.offline_data: dict[str, Any] = {"people": [], "units": {}, "alert": {}}
        self.relay_alerted: list[bool] = []
        # The tenant's check and My requests (migration 20270523_285).
        self.check_answers: list[dict[str, Any]] = []
        self.checks: list[tuple[int, bool]] = []
        self.my_reports: dict[str, Any] = {"result": "OK", "unit_number": "", "reports": []}
        # Contact office and FAQ (migration 20270524_286).
        self.contacts: list[tuple[str, str, int, int, str, str | None, str]] = []
        self.faq: list[dict[str, Any]] = []
        # The Customer bot (migration 20270525_287).
        self.choices: dict[str, Any] = {"today": "2026-11-05", "unit_types": [], "phone": None}
        self.inquiries: list[tuple[str, int, int, str, dict[str, Any]]] = []
        self.inquiry_answers: list[dict[str, Any]] = []
        self.reminder_runs = 0
        self.invoice_reminder_runs = 0
        self.receipt_runs = 0
        self.warning_runs = 0
        self.blocked = False
        # The Staff bot (migration 20270620_331); None is a job given no service actor.
        self.staff_ready = True
        self.staff: dict[int, dict[str, Any]] = {}
        self.staff_waiting: set[int] = set()
        self.staff_joins: list[tuple[int, str, str]] = []
        self.staff_scans: list[tuple[str, int, dict[str, Any], str]] = []
        self.staff_answers: list[dict[str, Any]] = []
        self.staff_data: dict[str, Any] = {"choices": {}, "users": []}
        self.photos_due: list[dict[str, Any]] = []
        self.photos_removed: list[str] = []
        # The Customer and Staff bots while the office is away (migration 20270711_383, DL-213).
        self.clock: dict[str, Any] = {"timezone_name": "Asia/Phnom_Penh", "utc_offset_minutes": 420}
        self.staff_join_state = "WAITING"
        # The one-time QR (migration 20270712_384, DL-214).
        self.code_answers: list[dict[str, Any]] = []
        self.code_tries: list[tuple[int, str]] = []
        self.start_codes: list[dict[str, Any]] = []
        self.bot_names: dict[str, str] = {}

    def record_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if item["relay_item_id"] in self.items:
            return {"saved": False}
        self.items[item["relay_item_id"]] = item
        return {"saved": True, "inbound_id": item["relay_item_id"]}

    def record_run(self, run: dict[str, Any]) -> None:
        self.runs.append(run)

    def queue(self, message: dict[str, Any]) -> None:
        self.queued.append(message)

    def remove_old_payloads(self) -> int:
        return 0

    def outbox_due(self, limit: int) -> list[dict[str, Any]]:
        return self.due[:limit]

    def record_attempt(
        self, outbox_id: str, outcome: str, error_code: str | None, message_id: int | None
    ) -> str:
        self.attempts.append((outbox_id, outcome, error_code, message_id))
        return outcome

    def health(self) -> dict[str, Any]:
        return {}

    def bot_state(self, bot: str, user: int) -> dict[str, Any]:
        step, data = self.steps.get(user, (None, {}))
        return {
            "language": self.languages.get(user),
            "has_phone": user in self.phones,
            "step": step,
            "data": data,
            "link": self.links.get(user),
            "blocked_until": None,
        }

    def bot_reply(
        self,
        bot: str,
        user: int,
        chat: int,
        step: str | None,
        data: dict[str, Any] | None,
        language: str,
        messages: list[dict[str, Any]],
        reply_to: str | None = None,
    ) -> None:
        self.reply_to.append(reply_to)
        if step is not None:
            self.steps[user] = (step, data or {})
        for message in messages:
            self.replies.append({"bot": bot, "chat_id": chat, "language": language, **message})

    def choose_language(self, bot: str, user: int, language: str) -> None:
        self.languages[user] = language

    def tenant_link(self, user: int, name: str, unit: str) -> dict[str, Any]:
        self.link_tries.append((user, name, unit))
        answer = self.link_answers.pop(0)
        if answer["result"] == "LINKED":
            self.links[user] = {"name": answer["name"], "unit_number": answer["unit_number"]}
        return answer

    def tenant_end_finished_links(self) -> int:
        return 0

    def remove_old_link_attempts(self) -> int:
        return 0

    def visit_reminders(self) -> int:
        self.reminder_runs += 1
        return 0

    def invoice_reminders(self) -> int:
        self.invoice_reminder_runs += 1
        return 0

    def receipts_queue(self) -> int:
        self.receipt_runs += 1
        return 0

    def warnings_queue(self) -> int:
        self.warning_runs += 1
        return 0

    def visit_requests_remove_old(self) -> int:
        return 0

    def tenant_form_data(self) -> dict[str, Any]:
        return self.form_data

    def tenant_offline_data(self) -> dict[str, Any]:
        return self.offline_data

    def offline_clock(self) -> dict[str, Any]:
        return self.clock

    def tenant_link_code(self, user: int, code: str) -> dict[str, Any]:
        self.code_tries.append((user, code))
        answer = self.code_answers.pop(0)
        if answer["result"] == "LINKED":
            self.links[user] = {"name": answer["name"], "unit_number": answer["unit_number"]}
        return answer

    def link_codes_offline(self) -> list[dict[str, Any]]:
        return self.start_codes

    def bot_name_set(self, bot: str, username: str) -> bool:
        changed = self.bot_names.get(bot) != username
        self.bot_names[bot] = username
        return changed

    def tenant_problem_report(
        self,
        inbound_id: str,
        form: dict[str, Any],
        media_ids: list[str],
        relay_alerted: bool = False,
    ) -> dict[str, Any]:
        self.reports.append((inbound_id, form, media_ids))
        self.relay_alerted.append(relay_alerted)
        return self.report_answers.pop(0)

    def tenant_report_check(self, user: int, fixed: bool) -> dict[str, Any]:
        self.checks.append((user, fixed))
        return self.check_answers.pop(0)

    def tenant_my_reports(self, user: int) -> dict[str, Any]:
        return self.my_reports

    def contact_add(
        self,
        bot: str,
        inbound_id: str,
        user: int,
        chat: int,
        language: str,
        name: str | None,
        message: str,
    ) -> dict[str, Any]:
        self.contacts.append((bot, inbound_id, user, chat, language, name, message))
        return {"result": "BLOCKED"} if self.blocked else {"result": "SAVED", "id": "c1"}

    def faq_for_bot(self, bot: str) -> list[dict[str, Any]]:
        return self.faq

    def customer_choices(self, user: int) -> dict[str, Any]:
        return self.choices

    def visit_request_add(
        self, inbound_id: str, user: int, chat: int, language: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        self.inquiries.append((inbound_id, user, chat, language, dict(request)))
        return self.inquiry_answers.pop(0)

    def _staff_ready(self) -> None:
        if not self.staff_ready:
            raise StaffBotUnavailable("no service actor")

    def staff_who(self, user: int) -> dict[str, Any]:
        self._staff_ready()
        if user in self.staff:
            return {"linked": True, **self.staff[user]}
        return {"linked": False, "waiting": user in self.staff_waiting}

    def staff_join(self, user: int, name: str, phone: str) -> dict[str, Any]:
        self._staff_ready()
        self.staff_joins.append((user, name, phone))
        if self.staff_join_state == "LINKED":
            self.staff[user] = {"name_km": name}
            return {"ok": True, "state": "LINKED"}
        self.staff_waiting.add(user)
        return {"ok": True, "state": "WAITING", "request_id": "r1"}

    def staff_check(self, user: int, scan: dict[str, Any], at: str) -> dict[str, Any]:
        self._staff_ready()
        self.staff_scans.append(("CHECK", user, scan, at))
        return self.staff_answers.pop(0)

    def staff_card(self, user: int, scan: dict[str, Any], at: str) -> dict[str, Any]:
        self._staff_ready()
        self.staff_scans.append(("CARD", user, scan, at))
        return self.staff_answers.pop(0)

    def staff_photos_due(self) -> list[dict[str, Any]]:
        return self.photos_due

    def staff_photo_removed(self, file_id: str) -> None:
        self.photos_removed.append(file_id)

    def staff_form_data(self) -> dict[str, Any]:
        return self.staff_data

    def staff_problem_report(
        self,
        inbound_id: str,
        form: dict[str, Any],
        media_ids: list[str],
        relay_alerted: bool = False,
    ) -> dict[str, Any]:
        self.relay_alerted.append(relay_alerted)
        self.staff_scans.append(("REPORT", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_close_job(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("CLOSE", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_meter_readings(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("METER", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_meter_check(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("METER_CHECK", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_checklist(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("CHECKLIST", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_patrol(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("PATROL", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_daily_summary(self) -> int:
        return 0

    def staff_unit_check(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("UNIT_CHECK", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)

    def staff_maintenance_check(
        self, inbound_id: str, form: dict[str, Any], media_ids: list[str]
    ) -> dict[str, Any]:
        self.staff_scans.append(("MAINT_CHECK", 0, {"form": form, "media": media_ids}, inbound_id))
        return self.staff_answers.pop(0)


def _client(relay: FakeRelay) -> RelayClient:
    return RelayClient(
        "relay.example.workers.dev", PULL_KEY, transport=relay.transport, clock=lambda: NOW
    )


def _update(text: str, update_id: int = 10, **message: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "update_id": update_id,
        "telegram_user_id": 777,
        "chat_id": 777,
        "language_code": "km",
        "payload": {
            "update_id": update_id,
            "message": {"from": {"id": 777}, "chat": {"id": 777}, "text": text, **message},
        },
        "media": [],
    }


def test_pull_saves_each_item_once_keeps_photos_and_confirms(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay, store = FakeRelay(office_key), FakeStore()
    photo = b"\xff\xd8\xff photo bytes"
    plain = _update("water leak", 11)
    plain["media"] = [
        {
            "id": "media-0001",
            "content_type": "image/jpeg",
            "sha256": hashlib.sha256(photo).hexdigest(),
            "size": len(photo),
            "width": 1280,
            "height": 960,
            "file_unique_id": "AQADabc",
        }
    ]
    relay.add("item-0001", plain, {"media-0001": photo})
    relay.add("item-0002", _update("ping", 12))
    result = run_pull(
        client=_client(relay), key=office_key, store=store, media_directory=tmp_path, log=print
    )
    assert (result.received, result.saved, result.refused) == (2, 2, 0)
    assert relay.items == {}
    saved = store.items["item-0001"]
    assert saved["media"][0]["storage_path"].endswith(hashlib.sha256(photo).hexdigest())
    assert (tmp_path / saved["media"][0]["storage_path"]).read_bytes() == photo
    assert saved["account"] == {"language": "km", "phone": None}
    # "ping" is the owner's setup test: the bot answers that the connection works.
    assert store.queued == [
        {
            "bot": "TENANT",
            "chat_id": 777,
            "text_code": "base.ping_reply",
            "language": "km",
            "details": {"bot": "CHETANA Residence support"},
            # The answer names the message it answers, so the outbox keeps it once (DL-202 (B)).
            "dedupe_key": "ping:item-0002",
        }
    ]
    run = store.runs[-1]
    assert run["outcome"] == "OK" and run["relay_dropped"] == 2 and run["items_saved"] == 2

    # The same items again (the office was not able to confirm): saved once, no new reply.
    relay.add("item-0002", _update("ping", 12))
    again = run_pull(client=_client(relay), key=office_key, store=store, media_directory=tmp_path)
    assert (again.saved, again.repeated) == (0, 1)
    assert len(store.queued) == 1


def test_an_item_that_cannot_be_opened_or_whose_photo_changed_stays_in_the_relay(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay, store = FakeRelay(office_key), FakeStore()
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    stranger = FakeRelay(other)
    stranger.add("item-0009", _update("hi"))
    relay.items["item-0009"] = stranger.items["item-0009"]
    plain = _update("photo", 13)
    plain["media"] = [
        {"id": "media-0002", "content_type": "image/jpeg", "sha256": "0" * 64, "size": 5}
    ]
    relay.add("item-0003", plain, {"media-0002": b"12345"})
    result = run_pull(client=_client(relay), key=office_key, store=store, media_directory=tmp_path)
    assert result.refused == 2
    assert sorted(result.refused_codes) == ["cannot_open", "media_fingerprint_differs"]
    assert set(relay.items) == {"item-0009", "item-0003"}
    assert store.items == {}
    assert not any(tmp_path.rglob("*"))


def test_a_shared_phone_counts_only_when_it_is_the_persons_own(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay, store = FakeRelay(office_key), FakeStore()
    relay.add(
        "item-0004",
        _update("", 14, contact={"user_id": 777, "phone_number": "855 12 345 678"}),
    )
    relay.add(
        "item-0005",
        _update("", 15, contact={"user_id": 999, "phone_number": "+85599111222"}),
    )
    run_pull(client=_client(relay), key=office_key, store=store, media_directory=tmp_path)
    assert store.items["item-0004"]["account"]["phone"] == "+85512345678"
    assert store.items["item-0005"]["account"]["phone"] is None


def test_a_failed_pull_or_confirm_is_recorded_with_a_fixed_code(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay, store = FakeRelay(office_key), FakeStore()
    wrong = RelayClient(
        "relay.example.workers.dev",
        bytes.fromhex("22" * 32),
        transport=relay.transport,
        clock=lambda: NOW,
    )
    with pytest.raises(RelayError) as refused:
        run_pull(client=wrong, key=office_key, store=store, media_directory=tmp_path)
    assert refused.value.code == "relay_refused_signature"
    assert store.runs[-1]["outcome"] == "FAILED"
    assert store.runs[-1]["error_code"] == "relay_refused_signature"

    relay.add("item-0006", _update("hello", 16))
    relay.fail_confirm = True
    with pytest.raises(RelayError):
        run_pull(client=_client(relay), key=office_key, store=store, media_directory=tmp_path)
    assert "item-0006" in store.items
    assert store.runs[-1]["error_code"] == "relay_http_503"


def test_send_job_sends_records_and_reports_fixed_codes() -> None:
    store = FakeStore()
    store.due = [
        {
            "id": "m1",
            "bot": "TENANT",
            "chat_id": 777,
            "text_code": "base.ping_reply",
            "language": "en",
            "details": {"bot": "CHETANA Residence support"},
            "buttons": None,
        },
        {
            "id": "m2",
            "bot": "TENANT",
            "chat_id": 778,
            "text_code": "base.ping_reply",
            "language": "km",
            "details": {"bot": "x"},
            "buttons": None,
        },
        {
            "id": "m3",
            "bot": "STAFF",
            "chat_id": 779,
            "text_code": "base.ping_reply",
            "language": "km",
            "details": {"bot": "x"},
            "buttons": None,
        },
        {
            "id": "m4",
            "bot": "TENANT",
            "chat_id": 780,
            "text_code": "no.such_text",
            "language": "km",
            "details": {},
            "buttons": None,
        },
    ]
    posts: list[tuple[str, dict[str, Any]]] = []

    def post(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        posts.append((address, body))
        if body["chat_id"] == 778:
            return 403, b""
        return 200, json.dumps({"ok": True, "result": {"message_id": 55}}).encode()

    result = run_send(
        store=store,
        api_host="api.telegram.org",
        tokens={"TENANT": TOKEN},
        post_json=post,
        log=print,
    )
    assert (result.sent, result.failed, result.skipped) == (1, 2, 1)
    assert store.attempts == [
        ("m1", "SENT", None, 55),
        ("m2", "FAILED", "telegram_blocked_by_person", None),
        ("m4", "FAILED", "text_unknown", None),
    ]
    assert posts[0][0] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert posts[0][1]["text"].startswith("✅ The office app got your message")


def test_an_invoice_and_its_reminder_read_as_the_tenant_gets_them() -> None:
    """DL-211: the Invoice message and the reminder, from what the database queues."""
    details = {
        "number": "INV-2026-0042",
        "unit": "Unit 305",
        "list": "• Monthly Rent: $350.00\n• Water: $4.50",
        "total": "$354.50",
        "to_pay": "$354.50",
        "due": "05/12/2026",
    }
    store = FakeStore()
    store.due = [
        {
            "id": f"i{number}",
            "bot": "TENANT",
            "chat_id": 777,
            "text_code": code,
            "language": language,
            "details": details,
            "buttons": None,
        }
        for number, (code, language) in enumerate(
            [
                ("tenant.invoice", "en"),
                ("tenant.invoice_reminder", "en"),
                ("tenant.invoice_paid", "en"),
                ("tenant.invoice", "km"),
            ]
        )
    ]
    posts: list[dict[str, Any]] = []

    def post(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        posts.append(body)
        return 200, json.dumps({"ok": True, "result": {"message_id": 9}}).encode()

    result = run_send(
        store=store, api_host="api.telegram.org", tokens={"TENANT": TOKEN}, post_json=post
    )
    assert result.sent == 4
    invoice, reminder, paid, khmer = (body["text"] for body in posts)
    assert invoice.startswith("🧾 New Invoice INV-2026-0042\nUnit 305")
    assert "• Water: $4.50" in invoice and "To pay: $354.50" in invoice
    assert "Due date: 05/12/2026" in invoice
    assert reminder.startswith("⏰ Reminder: Invoice INV-2026-0042 for Unit 305 is due on 05/12")
    assert "Already paid in full" in paid and "To pay" not in paid
    assert "INV-2026-0042" in khmer and "$354.50" in khmer
    assert all("reply_markup" not in body for body in posts)


def test_bot_keys_are_read_only_when_they_look_like_keys(tmp_path: Path) -> None:
    good, placeholder = tmp_path / "tenant", tmp_path / "staff"
    good.write_text(TOKEN + "\n")
    placeholder.write_text("REPLACE_ME")
    tokens = load_bot_tokens(
        {"TENANT": good, "STAFF": placeholder, "CUSTOMER": tmp_path / "missing"}
    )
    assert tokens == {"TENANT": TOKEN}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("012 345 678", "+85512345678"),
        ("+855 12 345 678", "+85512345678"),
        ("85512345678", "+85512345678"),
        ("+855012345678", "+85512345678"),
        ("0085512345678", "+85512345678"),
        ("+66 81 234 5678", "+66812345678"),
        ("hello", None),
        ("", None),
        ("+12", None),
    ],
)
def test_phone_numbers_in_one_format(given: str, expected: str | None) -> None:
    assert normalize_phone(given) == expected


def test_texts_fill_only_their_own_fields() -> None:
    text = render("base.ping_reply", "km", {"bot": "CHETANA", "phone": "+85512345678"})
    assert "CHETANA" in text and "+855" not in text
    with pytest.raises(TextError):
        render("base.ping_reply", "km", {})
    with pytest.raises(TextError):
        render("missing.code", "km", {})


def test_signed_calls_match_the_relay_format() -> None:
    body = b'{"ids":[]}'
    expected = hmac.new(
        PULL_KEY,
        f"{NOW}\nPOST\n/office/confirm\n{hashlib.sha256(body).hexdigest()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature(PULL_KEY, NOW, "POST", "/office/confirm", body) == expected
    with pytest.raises(RelayError):
        RelayClient("not a host!", PULL_KEY)


def test_bot_warnings_show_only_when_the_bots_are_on() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    fresh = (now - timedelta(minutes=1)).isoformat()
    old = (now - timedelta(minutes=30)).isoformat()
    base: dict[str, dict[str, object] | None] = {"checks": {"checked_at": fresh}}

    def codes(files: dict[str, dict[str, object] | None]) -> set[str]:
        return {
            warning.code
            for warning in evaluate_warnings({**base, **files}, now)
            if warning.code.startswith("telegram_bots")
        }

    assert codes({}) == set()
    healthy: dict[str, dict[str, object] | None] = {
        "telegram-pull": {"last_run_at": fresh, "last_success_at": fresh, "relay_dropped": 0},
        "telegram-send": {"last_run_at": fresh, "outbox_failing_12h": 0, "outbox_gave_up_7d": 0},
    }
    assert codes(healthy) == set()
    assert codes(
        {
            "telegram-pull": {"last_run_at": fresh, "last_success_at": old, "relay_dropped": 3},
            "telegram-send": {"last_run_at": old, "outbox_failing_12h": 1, "outbox_gave_up_7d": 1},
        }
    ) == {
        "telegram_bots_jobs_stale",
        "telegram_bots_not_pulled",
        "telegram_bots_relay_dropped",
        "telegram_bots_send_failing",
        "telegram_bots_send_gave_up",
    }


def test_the_office_names_itself_to_the_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloudflare refuses Python's default name with 403 (owner's Mac test run, 07/11/2026)."""
    seen: dict[str, Any] = {}

    class Answer:
        status = 200

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"{}"

    def urlopen(request: Any, **_: Any) -> Answer:
        seen["agent"] = request.get_header("User-agent")
        seen["signed"] = request.get_header("X-office-signature")
        return Answer()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    status, _ = telegram_relay_client._urllib_transport(
        "GET", "https://relay.example/office/items", {"X-Office-Signature": "s"}, b""
    )
    assert status == 200
    assert seen == {"agent": "CHETANA-Residence-office/1", "signed": "s"}


def test_the_items_are_collected_every_150_seconds(tmp_path: Path) -> None:
    # DL-219: the relay answers at once; the job runs every 10 seconds but collects every 150.
    start = datetime(2026, 11, 11, 7, 0, tzinfo=UTC)
    assert ITEMS_EVERY_SECONDS == 150
    assert items_due(tmp_path, start, 150) is True
    note_items(tmp_path, start)
    assert items_due(tmp_path, start + timedelta(seconds=10), 150) is False
    assert items_due(tmp_path, start + timedelta(seconds=149), 150) is False
    assert items_due(tmp_path, start + timedelta(seconds=150), 150) is True
    # A clock set back, or 0 seconds, collects at once.
    assert items_due(tmp_path, start - timedelta(seconds=5), 150) is True
    assert items_due(tmp_path, start + timedelta(seconds=10), 0) is True
