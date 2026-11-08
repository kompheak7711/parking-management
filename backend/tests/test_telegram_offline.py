"""The Tenant bot while the office app is closed (DL-210, owner 7 Nov 2026 "Bot answers by
itself"): what the office sends the relay, and how the app saves what the relay answered without
answering twice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from property_rental.telegram_offline import (
    MESSAGES,
    LinkKeyError,
    link_code,
    offline_links,
    offline_texts,
    push_offline,
    read_link_key,
)
from property_rental.telegram_tenant_bot import handle_tenant_form, handle_tenant_update
from test_telegram_jobs import FakeRelay, FakeStore, _client
from test_telegram_jobs import office_key as office_key

USER = 777
KEY = "ab" * 32
RELAY = "relay.example.workers.dev"
DATA: dict[str, Any] = {
    "people": [
        {
            "unit_id": "u-305",
            "phones": ["+85512345678", "+85517000111"],
            "names": ["s:dara kim", "c:darakim", "c:kimdara"],
        },
        {"unit_id": "u-gone", "phones": ["+85599000000"], "names": ["s:sok"]},
    ],
    "units": {"u-305": {"unit": "Unit 305", "unit_key": "305", "places": [{"item_id": "i-1"}]}},
    "types": {"t-1": {"name_kh": "ទឹក", "always_urgent": False}},
    "places": {"p-1": "ចំណតរថយន្ត"},
    "alert": {"always": [9001], "shifts": [[9002, 100, 200]]},
}


def test_the_hash_is_the_relays() -> None:
    # The same inputs give the same code in relay/test/offline.test.ts.
    assert link_code(KEY, "+85512345678", "305", "s:dara kim") == "fdfb978fb36198ac88c66beaa0b94a1d"


def test_the_check_list_holds_hashes_and_units_but_no_name_or_phone() -> None:
    links = offline_links(DATA, KEY)
    assert links["units"] == [{"unit": "Unit 305", "places": [{"item_id": "i-1"}]}]
    assert len(links["codes"]) == 6 and set(links["codes"].values()) == {0}
    assert link_code(KEY, "+85517000111", "305", "c:kimdara") in links["codes"]
    text = str(links)
    assert "dara" not in text and "855" not in text


def test_the_relay_texts_are_the_bots_own_in_both_languages() -> None:
    texts = offline_texts(DATA, RELAY)
    assert set(texts["messages"]) == set(MESSAGES)
    for name, languages in texts["messages"].items():
        assert set(languages) == {"km", "en"}, name
    ask = texts["messages"]["ask_phone"]["en"]
    assert ask["markup"]["keyboard"][0][0]["request_contact"] is True
    kind = texts["messages"]["report_kind"]["km"]["markup"]["inline_keyboard"]
    assert kind[0][0]["web_app"]["url"].startswith(f"https://{RELAY}/app/tenant?form=unit")
    assert "{tries_left}" in texts["messages"]["no_match"]["en"]["text"]
    assert "{unit}" in texts["messages"]["linked"]["en"]["text"]
    assert texts["buttons"]["button.english"] == ["English"]
    assert "{type}" in texts["staff_urgent"] and "{where}" in texts["staff_urgent"]
    assert texts["alert"] == {"always": [9001], "shifts": [[9002, 100, 200]]}


def test_the_offline_body_is_sent_once_and_again_only_when_it_changes(
    tmp_path: Path, office_key: Any
) -> None:
    relay = FakeRelay(office_key)
    store = FakeStore()
    store.offline_data = DATA
    key_file = tmp_path / "link-check.key"
    key_file.write_text(KEY + "\n")
    kwargs: dict[str, Any] = {
        "client": _client(relay),
        "store": store,
        "relay_host": RELAY,
        "link_key_file": key_file,
        "status_directory": tmp_path,
    }
    assert push_offline(**kwargs) is True
    assert push_offline(**kwargs) is False
    path, body = relay.pushed[0]
    assert path == "/office/offline/tenant" and len(body["links"]["codes"]) == 6
    store.offline_data = DATA | {"alert": {"always": [9001, 9005], "shifts": []}}
    assert push_offline(**kwargs) is True
    # Without the key the relay still answers but links nobody.
    lines: list[str] = []
    key_file.write_text("not a key")
    assert push_offline(**kwargs | {"log": lines.append}) is True
    assert relay.pushed[-1][1]["links"] == {"units": [], "codes": {}}
    assert lines == ["telegram_pull:offline_link_key_not_set"]
    with pytest.raises(LinkKeyError):
        read_link_key(tmp_path / "missing.key")


def relay_said(
    store: FakeStore, relay: dict[str, Any], text: str | None = None, **extra: Any
) -> None:
    body: dict[str, Any] = {
        "from": {"id": USER, "first_name": "Dara", "last_name": "Kim"},
        "chat": {"id": USER, "type": "private"},
        **extra,
    }
    if text is not None:
        body["text"] = text
    plain = {
        "telegram_user_id": USER,
        "chat_id": USER,
        "payload": {"message": body},
        "relay": relay,
    }
    handle_tenant_update("TENANT", plain, {"saved": True, "inbound_id": "in-1"}, store)


def test_what_the_relay_answered_is_saved_without_answering_again() -> None:
    store = FakeStore()
    relay_said(store, {"answered": True, "step": "menu", "language": "en"}, "English")
    assert store.languages[USER] == "en" and store.replies == []
    relay_said(store, {"answered": True, "step": "link.unit", "name": "kim dara"}, "kim dara")
    assert store.steps[USER] == ("link.unit", {"name": "kim dara"})
    store.link_answers.append({"result": "LINKED", "name": "Dara Kim", "unit_number": "305"})
    link = {"outcome": "LINKED", "name": "kim dara", "unit": "Unit 305"}
    relay_said(store, {"answered": True, "step": "menu", "link": link}, "Unit 305")
    assert store.link_tries == [(USER, "kim dara", "Unit 305")]
    assert store.replies == [] and store.steps[USER][0] == "menu"
    relay_said(store, {"answered": True, "step": "menu", "contact": True}, "The lift is noisy")
    assert store.contacts[-1][-1] == "The lift is noisy" and store.replies == []


def test_when_the_database_disagrees_with_the_relay_the_tenant_hears_the_database() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    store.link_answers.append({"result": "NO_MATCH", "tries_left": 4})
    link = {"outcome": "LINKED", "name": "kim dara", "unit": "305"}
    relay_said(store, {"answered": True, "step": "menu", "link": link}, "305")
    assert [reply["text_code"] for reply in store.replies] == ["tenant.no_match"]
    store.link_answers.append({"result": "LINKED", "name": "Dara Kim", "unit_number": "305"})
    link = {"outcome": "NO_MATCH", "name": "Dara Kim", "unit": "305"}
    relay_said(store, {"answered": True, "step": "menu", "link": link}, "305")
    assert store.replies[-1]["text_code"] == "tenant.linked"


def test_a_message_the_relay_only_held_is_answered_by_the_office() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    store.links[USER] = {"name": "Dara Kim", "unit_number": "305"}
    relay_said(store, {"answered": False}, "My requests")
    assert [reply["text_code"] for reply in store.replies] == ["tenant.my_none"]


def test_a_report_the_relay_alerted_is_saved_without_a_second_alert() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    for relay in ({"answered": True, "alerted": True}, {"answered": True, "alerted": False}, None):
        store.report_answers.append(
            {"result": "ADDED", "report_number": "UP260001", "kind": "UNIT", "urgent": True}
        )
        plain: dict[str, Any] = {
            "telegram_user_id": USER,
            "chat_id": USER,
            "payload": {"form": {"kind": "UNIT"}, "role": "TENANT"},
        }
        if relay is not None:
            plain["relay"] = relay
        handle_tenant_form("TENANT", plain, {"saved": True, "inbound_id": "in-1"}, store)
    assert store.relay_alerted == [True, False, False]
    # The office still tells the tenant the report's number.
    assert [reply["text_code"] for reply in store.replies] == ["tenant.report_urgent"] * 3
