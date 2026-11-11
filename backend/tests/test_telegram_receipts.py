"""Receipts on Telegram (DL-215, owner 11 Nov 2026): the Receipt message as the tenant reads it."""

from __future__ import annotations

import json
from typing import Any

from property_rental.telegram_send_job import run_send
from test_telegram_jobs import TOKEN, FakeStore

DETAILS = {
    "number": "R2611-0007",
    "unit": "Unit 407",
    "date": "11/11/2026",
    "amount": "410,000 ៛ ($100.00)",
    "method": "Cash",
    "list": "• Invoice INV-2026-0042: $80.00\n• Not used yet (kept for you): $20.00",
}


def test_a_receipt_reads_as_the_tenant_gets_it_in_english_and_khmer() -> None:
    store = FakeStore()
    store.due = [
        {
            "id": f"r{number}",
            "bot": "TENANT",
            "chat_id": 778,
            "text_code": "tenant.receipt",
            "language": language,
            "details": DETAILS,
            "buttons": None,
        }
        for number, language in enumerate(("en", "km"))
    ]
    posts: list[dict[str, Any]] = []

    def post(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        posts.append(body)
        return 200, json.dumps({"ok": True, "result": {"message_id": 9}}).encode()

    result = run_send(
        store=store, api_host="api.telegram.org", tokens={"TENANT": TOKEN}, post_json=post
    )
    assert result.sent == 2
    english, khmer = (body["text"] for body in posts)
    assert english.startswith("✅ Receipt R2611-0007\nUnit 407\nDate: 11/11/2026\n")
    assert "Received: 410,000 ៛ ($100.00) (Cash)" in english
    assert "• Invoice INV-2026-0042: $80.00" in english
    assert english.endswith("Thank you for your payment.")
    assert khmer.startswith("✅ បង្កាន់ដៃ R2611-0007") and "410,000 ៛" in khmer
    assert all("reply_markup" not in body for body in posts)
