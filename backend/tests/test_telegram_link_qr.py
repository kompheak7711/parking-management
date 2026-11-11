"""The one-time Telegram QR (DL-214, owner 11 Nov 2026 "Yes, QR for tenants and guests"): the
Tenant bot links a person from the code in Start, the office tells the relay the codes' hashes,
and the send job learns the bot's user name for the t.me link."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from property_rental.telegram_offline import offline_links
from property_rental.telegram_send_job import learn_bot_names
from property_rental.telegram_tenant_bot import handle_tenant_update
from property_rental.totp_qr import telegram_link_qr_svg
from test_telegram_jobs import FakeStore

USER = 5050
CODE = "0123456789abcdef0123456789abcdef01234567"
LINKED = {"result": "LINKED", "name": "Sao Rina", "unit_number": "U302", "link_id": "l-1"}


def say(store: FakeStore, text: str, relay: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    before = len(store.replies)
    plain: dict[str, Any] = {
        "telegram_user_id": USER,
        "chat_id": USER,
        "payload": {
            "message": {
                "from": {"id": USER, "first_name": "Rina"},
                "chat": {"id": USER, "type": "private"},
                "text": text,
            }
        },
    }
    if relay is not None:
        plain["relay"] = relay
    handle_tenant_update("TENANT", plain, {"saved": True, "inbound_id": "in-1"}, store)
    return store.replies[before:]


def test_a_scan_links_a_new_person_at_once_then_asks_the_language() -> None:
    store = FakeStore()
    store.code_answers.append(LINKED)
    sent = say(store, f"/start {CODE}")
    assert store.code_tries == [(USER, CODE)]
    assert [reply["text_code"] for reply in sent] == ["tenant.linked_code", "tenant.welcome"]
    assert sent[0]["details"] == {"name": "Sao Rina", "unit": "U302"}
    assert store.steps[USER][0] == "language"


def test_a_scan_by_a_person_who_chose_a_language_shows_the_menu() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    store.code_answers.append(LINKED)
    sent = say(store, f"/start   {CODE}")
    assert [(reply["text_code"], reply["keyboard"]) for reply in sent] == [
        ("tenant.linked_code", "tenant.menu")
    ]
    assert sent[0]["language"] == "en" and store.steps[USER][0] == "menu"


@pytest.mark.parametrize(
    ("result", "text_code"),
    [
        ("USED", "tenant.code_bad"),
        ("EXPIRED", "tenant.code_bad"),
        ("NOT_FOUND", "tenant.code_bad"),
        ("ENDED", "tenant.code_ended"),
    ],
)
def test_a_code_that_does_not_work_says_why(result: str, text_code: str) -> None:
    store = FakeStore()
    store.languages[USER] = "km"
    store.code_answers.append({"result": result})
    assert [reply["text_code"] for reply in say(store, f"/start {CODE}")] == [text_code]


def test_a_plain_start_or_a_wrong_code_is_not_a_scan() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    for text in ("/start", "/start ABC", f"/start {CODE}0", f"/start {CODE.upper()}"):
        assert [reply["text_code"] for reply in say(store, text)] == ["tenant.welcome"]
    assert store.code_tries == []


def test_a_scan_the_relay_answered_is_linked_again_without_a_second_answer() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    store.code_answers.append(LINKED)
    relay = {"answered": True, "step": "menu", "code": {"outcome": "LINKED"}}
    assert say(store, f"/start {CODE}", relay) == []
    assert store.code_tries == [(USER, CODE)] and store.steps[USER][0] == "menu"
    # When the database disagrees with the relay, the person hears the database.
    store.code_answers.append({"result": "USED"})
    sent = say(store, f"/start {CODE}", relay)
    assert [reply["text_code"] for reply in sent] == ["tenant.code_bad"]
    store.code_answers.append(LINKED)
    sent = say(store, f"/start {CODE}", {"answered": True, "code": {"outcome": "BAD"}})
    assert [reply["text_code"] for reply in sent] == ["tenant.linked_code"]


def test_the_relay_gets_each_unused_codes_hash_and_unit_even_without_the_link_key() -> None:
    codes: list[dict[str, Any]] = [
        {
            "code_hash": "f" * 64,
            "unit_id": "u-1",
            "unit": "U302",
            "places": [{"item_id": "i-1"}],
            "expires_at": 1_800_000_000,
        },
        {"code_hash": "e" * 64, "unit_id": "u-1", "unit": "U302", "expires_at": 1_800_000_100},
        {"code_hash": "d" * 64, "unit_id": "u-2", "unit": "B5"},  # no expiry: left out
    ]
    links = offline_links({"people": [], "units": {}}, None, codes)
    assert links["units"] == [{"unit": "U302", "places": [{"item_id": "i-1"}]}]
    assert links["start_codes"] == {"f" * 64: [0, 1_800_000_000], "e" * 64: [0, 1_800_000_100]}
    assert links["codes"] == {}
    assert offline_links({"people": [], "units": {}}, None) == {"units": [], "codes": {}}


def test_the_send_job_learns_the_bot_names_once_a_day(tmp_path: Path) -> None:
    store = FakeStore()
    asked: list[str] = []

    def post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        asked.append(address.rsplit("/", 1)[-1])
        if "777:" in address:
            return 401, b""
        return 200, json.dumps({"ok": True, "result": {"username": "ChetanaSupportBot"}}).encode()

    kwargs: dict[str, Any] = {
        "store": store,
        "api_host": "api.telegram.org",
        "tokens": {"TENANT": "123456:" + "a" * 35},
        "status_directory": tmp_path,
        "post_json": post_json,
        "log": lambda line: None,
    }
    assert learn_bot_names(today="2026-11-11", **kwargs) == 1
    assert store.bot_names == {"TENANT": "ChetanaSupportBot"} and asked == ["getMe"]
    assert learn_bot_names(today="2026-11-11", **kwargs) == 0
    assert asked == ["getMe"]  # not asked again the same day
    assert learn_bot_names(today="2026-11-12", **kwargs) == 0
    assert asked == ["getMe", "getMe"]
    # A bot Telegram refuses is asked again on the next run.
    lines: list[str] = []
    bad = kwargs | {"tokens": {"STAFF": "777:" + "b" * 35}, "log": lines.append}
    learn_bot_names(today="2026-11-13", **bad)
    learn_bot_names(today="2026-11-13", **bad)
    assert lines == ["telegram_send:bot_name_unknown:STAFF"] * 2


def test_the_qr_picture_is_only_for_a_one_time_telegram_link() -> None:
    picture = telegram_link_qr_svg(f"https://t.me/ChetanaSupportBot?start={CODE}")
    assert picture.startswith("<svg") and 'fill="#000"' in picture
    for wrong in (
        f"https://evil.example/ChetanaSupportBot?start={CODE}",
        f"https://t.me/ChetanaSupportBot?start={CODE}&x=1",
        "https://t.me/ChetanaSupportBot?start=abc",
    ):
        with pytest.raises(ValueError):
            telegram_link_qr_svg(wrong)
