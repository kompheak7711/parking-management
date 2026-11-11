"""The bots while the office app is closed (DL-210, owner 7 Nov 2026 "Bot answers by itself";
DL-213, owner 11 Nov 2026, the Customer and Staff bots too): what the office sends the relay, and
how the app saves what the relay answered without answering twice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from property_rental.telegram_customer_bot import handle_customer_update
from property_rental.telegram_offline import (
    CUSTOMER_MESSAGES,
    MESSAGES,
    STAFF_MESSAGES,
    LinkKeyError,
    customer_offline_texts,
    link_code,
    offline_links,
    offline_texts,
    push_offline,
    read_link_key,
    staff_offline_texts,
)
from property_rental.telegram_staff_bot import handle_staff_form, handle_staff_update
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
    assert [path for path, _ in relay.pushed] == [
        "/office/offline/tenant",
        "/office/offline/customer",
        "/office/offline/staff",
    ]
    path, body = relay.pushed[0]
    assert path == "/office/offline/tenant" and len(body["links"]["codes"]) == 6
    # A new FAQ answer sends only the Customer bot's body again.
    store.faq = [{"number": 1, "question_en": "Parking?", "answer_en": "Yes"}]
    assert push_offline(**kwargs) is True
    assert [path for path, _ in relay.pushed[3:]] == ["/office/offline/customer"]
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


TYPES = [{"code": "STUDIO", "name_en": "Studio", "name_km": "ស្ទូឌីយោ"}, {"name_en": "no code"}]
CLOCK = {"timezone_name": "Asia/Phnom_Penh", "utc_offset_minutes": 420}


def test_the_customer_body_has_every_step_the_unit_types_the_faq_and_the_clock() -> None:
    faq: list[dict[str, Any]] = [
        {"number": 2, "question_en": "Pets?", "question_km": "សត្វ?", "answer_en": "No"},
        {"number": "x"},
    ]
    texts = customer_offline_texts(TYPES, faq, CLOCK, RELAY)
    assert set(texts["messages"]) == set(CUSTOMER_MESSAGES)
    for name, languages in texts["messages"].items():
        assert set(languages) == {"km", "en"}, name
    # The choice keyboards get their choice rows from the relay, in front of the fixed rows.
    assert texts["messages"]["ask_type"]["en"]["choices"] is True
    assert "choices" not in texts["messages"]["ask_name"]["en"]
    phone = texts["messages"]["ask_phone"]["km"]["markup"]["keyboard"][0][0]
    assert phone["request_contact"] is True
    assert texts["unit_types"] == [TYPES[0]]
    assert texts["faq"] == [
        {
            "number": 2,
            "question_en": "Pets?",
            "question_km": "សត្វ?",
            "answer_en": "No",
            "answer_km": "",
        }
    ]
    assert texts["utc_offset_minutes"] == 420
    assert texts["rules"]["first_day"] == 2 and texts["rules"]["last_day"] == 30
    assert texts["buttons"]["button.english"] == ["English"]
    assert texts["weekdays"]["en"][0] == "Mon" and texts["months"]["en"][11] == "December"
    # No phone, name or other person's data goes to the relay in this body.
    assert "855" not in str(texts)


def test_the_staff_body_is_khmer_with_the_alert_list() -> None:
    texts = staff_offline_texts(DATA, RELAY)
    assert set(texts["messages"]) == set(STAFF_MESSAGES)
    for languages in texts["messages"].values():
        assert languages["km"]["text"] == languages["en"]["text"]
    assert texts["alert"] == {"always": [9001], "shifts": [[9002, 100, 200]]}
    assert "{type}" in texts["staff_urgent"] and "{where}" in texts["staff_urgent"]


CUSTOMER = 4040
OWN_PHONE = {"user_id": CUSTOMER, "phone_number": "85512800200"}


def customer_said(
    store: FakeStore, relay: dict[str, Any], text: str | None = None, **extra: Any
) -> list[dict[str, Any]]:
    before = len(store.replies)
    body: dict[str, Any] = {
        "from": {"id": CUSTOMER, "first_name": "Sokha"},
        "chat": {"id": CUSTOMER, "type": "private"},
        **extra,
    }
    if text is not None:
        body["text"] = text
    plain = {
        "telegram_user_id": CUSTOMER,
        "chat_id": CUSTOMER,
        "payload": {"message": body},
        "relay": relay,
    }
    handle_customer_update("CUSTOMER", plain, {"saved": True, "inbound_id": "in-7"}, store)
    return store.replies[before:]


def test_a_customer_inquiry_the_relay_took_is_saved_and_only_the_number_is_sent() -> None:
    store = FakeStore()
    assert customer_said(store, {"answered": True, "step": "language"}, "/start") == []
    assert (
        customer_said(store, {"answered": True, "step": "menu", "language": "en"}, "English") == []
    )
    assert store.languages[CUSTOMER] == "en"
    step = {"answered": True, "step": "ask.name", "request": {"contact_by": "TELEGRAM"}}
    assert customer_said(store, step, contact=OWN_PHONE) == []
    assert store.steps[CUSTOMER] == ("ask.name", {"contact_by": "TELEGRAM"})
    request = {
        "contact_by": "TELEGRAM",
        "name": "Sokha Chan",
        "unit_type": "STUDIO",
        "visit_on": "2026-11-13",
        "visit_part": "MORNING",
        "move_in": "2026-12",
        "note": None,
        "extra": "not kept",
    }
    store.inquiry_answers.append({"result": "ADDED", "number": "VR260012"})
    sent = customer_said(
        store, {"answered": True, "step": "menu", "request": {}, "inquiry": request}, "Send"
    )
    assert [reply["text_code"] for reply in sent] == ["customer.request_received"]
    assert sent[0]["details"] == {"number": "VR260012"} and sent[0]["language"] == "en"
    kept = dict(request)
    kept.pop("extra")
    assert store.inquiries == [("in-7", CUSTOMER, CUSTOMER, "en", kept)]
    assert store.steps[CUSTOMER][0] == "menu" and store.reply_to[-1] == "in-7"


def test_a_customer_contact_message_the_relay_took_is_saved_without_an_answer() -> None:
    store = FakeStore()
    store.languages[CUSTOMER] = "km"
    relay = {"answered": True, "step": "menu", "contact": True}
    assert customer_said(store, relay, "Do you have parking?") == []
    assert store.contacts[-1][0] == "CUSTOMER" and store.contacts[-1][-1] == "Do you have parking?"
    # An inquiry the database refuses is answered by the office.
    store.blocked = False
    store.inquiry_answers.append({"result": "BLOCKED"})
    request = {"contact_by": "PHONE", "name": "S", "unit_type": "STUDIO", "move_in": "LATER"}
    sent = customer_said(store, {"answered": True, "step": "menu", "inquiry": request}, "Send")
    assert [reply["text_code"] for reply in sent] == ["customer.blocked"]


STAFF_USER = 6161


def staff_said(store: FakeStore, relay: dict[str, Any], **extra: Any) -> list[dict[str, Any]]:
    before = len(store.replies)
    body: dict[str, Any] = {
        "from": {"id": STAFF_USER, "first_name": "Dane"},
        "chat": {"id": STAFF_USER, "type": "private"},
        **extra,
    }
    plain = {
        "telegram_user_id": STAFF_USER,
        "chat_id": STAFF_USER,
        "payload": {"message": body},
        "relay": relay,
    }
    handle_staff_update("STAFF", plain, {"saved": True, "inbound_id": "in-3"}, store)
    return store.replies[before:]


def test_a_staff_join_the_relay_took_is_saved_and_hello_only_when_approved_at_once() -> None:
    store = FakeStore()
    relay = {"answered": True, "step": "menu"}
    assert staff_said(store, relay, text="/start") == []
    own = {"user_id": STAFF_USER, "phone_number": "85517000222"}
    assert staff_said(store, relay, contact=own) == []
    assert store.staff_joins == [(STAFF_USER, "Dane", "+85517000222")]
    # A person the database links at once gets the hello the relay could not give.
    store.staff_waiting.clear()
    store.staff_join_state = "LINKED"
    second = 6262
    plain = {
        "telegram_user_id": second,
        "chat_id": second,
        "payload": {
            "message": {
                "from": {"id": second, "first_name": "Sok"},
                "chat": {"id": second, "type": "private"},
                "contact": {"user_id": second, "phone_number": "85517000333"},
            }
        },
        "relay": relay,
    }
    handle_staff_update("STAFF", plain, {"saved": True, "inbound_id": "in-4"}, store)
    assert [reply["text_code"] for reply in store.replies] == ["staff.hello"]
    # A linked person's hello was the relay's; the office does not say it again.
    store.staff[STAFF_USER] = {"name_km": "ដានេ"}
    assert staff_said(store, relay, contact=own) == []
    # Without the service actor the office stays quiet: the relay already answered.
    store.staff_ready = False
    assert staff_said(store, relay, contact=own) == []


def test_a_staff_report_the_relay_alerted_is_saved_without_a_second_alert() -> None:
    store = FakeStore()
    for relay in ({"answered": True, "alerted": True}, {"answered": True}, None):
        store.staff_answers.append(
            {"result": "ADDED", "repeated": False, "report_number": "BP260003", "urgent": True}
        )
        plain: dict[str, Any] = {
            "telegram_user_id": STAFF_USER,
            "chat_id": STAFF_USER,
            "payload": {"form": {"type": "REPORT", "kind": "BUILDING"}, "role": "STAFF"},
            "office": {"received_at": "2026-11-11T03:00:00+00:00"},
        }
        if relay is not None:
            plain["relay"] = relay
        handle_staff_form("STAFF", plain, {"saved": True, "inbound_id": "in-5"}, store)
    assert store.relay_alerted == [True, False, False]
    # The office still sends the report's number.
    assert [reply["text_code"] for reply in store.replies] == ["staff.report_urgent"] * 3
