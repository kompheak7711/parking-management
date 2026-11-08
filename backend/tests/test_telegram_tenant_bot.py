"""The Tenant bot conversation: Start, language and linking (DL-126, step 2a), the Problem
report form (DL-127, step 2b), Fixed / Not fixed and My requests (DL-129, step 2d), and
Contact office and FAQ (DL-170, step 2d part 2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from property_rental.telegram_pull_job import push_form_data
from property_rental.telegram_relay_client import RelayClient
from property_rental.telegram_send_job import run_send
from property_rental.telegram_tenant_bot import handle_tenant_form, handle_tenant_update
from property_rental.telegram_texts import TextError, keyboard_markup, render
from test_telegram_jobs import NOW, PULL_KEY, FakeRelay, FakeStore, _client
from test_telegram_jobs import office_key as office_key

USER = 777


def say(store: FakeStore, text: str | None = None, **message: Any) -> list[dict[str, Any]]:
    before = len(store.replies)
    body: dict[str, Any] = {
        "from": {"id": USER, "first_name": "Dara", "last_name": "Kim"},
        "chat": {"id": USER, "type": message.pop("chat_type", "private")},
        **message,
    }
    if text is not None:
        body["text"] = text
    plain = {"telegram_user_id": USER, "chat_id": USER, "payload": {"message": body}}
    handle_tenant_update("TENANT", plain, {"saved": True, "inbound_id": "in-1"}, store)
    return store.replies[before:]


def codes(replies: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(reply["text_code"], reply.get("keyboard")) for reply in replies]


def test_start_asks_for_the_language_then_offers_only_linking() -> None:
    store = FakeStore()
    assert codes(say(store, "/start")) == [("tenant.welcome", "tenant.language")]
    # Anything before a language is chosen asks again.
    assert codes(say(store, "hello")) == [("tenant.welcome", "tenant.language")]
    answer = say(store, "English")
    assert codes(answer) == [("tenant.hello", "tenant.start")]
    assert answer[0]["language"] == "en" and store.languages[USER] == "en"
    assert codes(say(store, "My requests")) == [("tenant.link_first", "tenant.start")]
    khmer = say(store, "ភាសាខ្មែរ")
    assert khmer[0]["language"] == "km"


def test_linking_asks_for_the_own_phone_then_name_then_unit() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    assert codes(say(store, "Link my Lease")) == [("tenant.ask_phone", "tenant.share_phone")]
    # Typing a number, or sharing someone else's contact, does not count.
    assert codes(say(store, "012345678")) == [("tenant.ask_phone_again", "tenant.share_phone")]
    other = {"user_id": 999, "phone_number": "85512345678"}
    assert codes(say(store, contact=other)) == [("tenant.ask_phone_again", "tenant.share_phone")]
    store.phones.add(USER)
    own = {"user_id": USER, "phone_number": "85512345678"}
    assert codes(say(store, contact=own)) == [("tenant.ask_name", "remove")]
    assert codes(say(store, "Kim Dara")) == [("tenant.ask_unit", None)]
    store.link_answers.append({"result": "NO_MATCH", "tries_left": 4})
    wrong = say(store, "306")
    assert codes(wrong) == [("tenant.no_match", "tenant.reject")]
    assert wrong[0]["details"] == {"tries_left": 4}
    assert store.link_tries == [(USER, "Kim Dara", "306")]

    say(store, "Link my Lease")
    say(store, contact=own)
    say(store, "Kim Dara")
    store.link_answers.append({"result": "LINKED", "name": "Dara Kim", "unit_number": "305"})
    linked = say(store, "305")
    assert codes(linked) == [("tenant.linked", "tenant.menu")]
    assert linked[0]["details"] == {"name": "Dara Kim", "unit": "305"}
    assert codes(say(store, "Problem report")) == [("tenant.report_kind", "tenant.report_kind")]
    assert codes(say(store, "FAQ")) == [("tenant.faq_none", "tenant.menu")]
    assert codes(say(store, "anything")) == [("tenant.menu", "tenant.menu")]


def test_the_fifth_wrong_try_says_linking_is_blocked() -> None:
    store = FakeStore()
    store.languages[USER] = "km"
    store.phones.add(USER)
    store.steps[USER] = ("link.unit", {"name": "Dara"})
    store.link_answers.append({"result": "NO_MATCH", "tries_left": 0})
    assert codes(say(store, "305")) == [("tenant.blocked", "tenant.reject")]


def test_groups_other_bots_and_the_test_message_are_left_alone() -> None:
    store = FakeStore()
    assert say(store, "/start", chat_type="group") == []
    assert say(store, "ping") == []
    plain = {"telegram_user_id": USER, "chat_id": USER, "payload": {"message": {}}}
    handle_tenant_update("STAFF", plain, {"saved": True}, store)
    assert store.replies == []


def test_the_send_job_shows_the_keyboard_in_the_persons_language() -> None:
    store = FakeStore()
    store.due = [
        {
            "id": "m1",
            "bot": "TENANT",
            "chat_id": USER,
            "text_code": "tenant.ask_phone",
            "language": "en",
            "details": {},
            "keyboard": "tenant.share_phone",
        },
        {
            "id": "m2",
            "bot": "TENANT",
            "chat_id": USER,
            "text_code": "tenant.ask_name",
            "language": "km",
            "details": {},
            "keyboard": "remove",
        },
        {
            "id": "m3",
            "bot": "TENANT",
            "chat_id": USER,
            "text_code": "tenant.menu",
            "language": "km",
            "details": {},
            "keyboard": "no.such_keyboard",
        },
    ]
    sent: list[dict[str, Any]] = []

    def post(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        sent.append(body)
        return 200, b'{"ok": true, "result": {"message_id": 5}}'

    result = run_send(
        store=store,
        api_host="api.telegram.org",
        tokens={"TENANT": "1:x"},
        post_json=post,
        log=lambda line: None,
    )
    assert result.sent == 2
    assert sent[0]["reply_markup"] == {
        "keyboard": [[{"text": "Share my phone number", "request_contact": True}]],
        "resize_keyboard": True,
    }
    assert sent[1]["reply_markup"] == {"remove_keyboard": True}
    assert store.attempts[-1] == ("m3", "FAILED", "text_unknown", None)


def send_form(store: FakeStore, answer: dict[str, Any], bot: str = "TENANT") -> list[Any]:
    before = len(store.replies)
    store.report_answers.append(answer)
    plain = {
        "telegram_user_id": USER,
        "chat_id": USER,
        "payload": {"form": {"kind": "UNIT"}, "role": "TENANT"},
    }
    handle_tenant_form(
        bot, plain, {"saved": True, "inbound_id": "in-1", "media_ids": ["m-1"]}, store
    )
    return [(reply["text_code"], reply.get("details")) for reply in store.replies[before:]]


def test_a_saved_form_is_answered_with_its_number_in_the_persons_language() -> None:
    store = FakeStore()
    store.languages[USER] = "en"
    added = {"result": "ADDED", "report_number": "UP260231", "kind": "UNIT", "urgent": False}
    assert send_form(store, added | {"plan_workdays": 1}) == [
        ("tenant.report_received", {"number": "UP260231", "days": 1})
    ]
    assert store.reports == [("in-1", {"kind": "UNIT"}, ["m-1"])]
    assert store.replies[-1]["language"] == "en" and store.replies[-1]["keyboard"] == "tenant.menu"
    assert send_form(store, added | {"plan_workdays": 2})[0][0] == "tenant.report_received_days"
    urgent = added | {"urgent": True, "urgent_hours": 1}
    assert send_form(store, urgent)[0] == (
        "tenant.report_urgent",
        {"number": "UP260231", "hours": 1},
    )
    assert send_form(store, urgent | {"urgent_hours": 3})[0][0] == "tenant.report_urgent_hours"
    building = added | {"kind": "BUILDING", "report_number": "BP260045"}
    assert send_form(store, building)[0][0] == "tenant.report_building"
    assert send_form(store, building | {"urgent": True})[0][0] == "tenant.report_building_urgent"
    assert send_form(store, building | {"joined_to": "BP260044"}) == [
        ("tenant.report_joined", {"number": "BP260045", "main": "BP260044"})
    ]
    assert send_form(store, {"result": "NOT_LINKED"})[0][0] == "tenant.report_not_linked"
    assert send_form(store, {"result": "INVALID", "reason": "say_what"})[0][0] == (
        "tenant.report_invalid"
    )
    # The same form again, or a form to another bot, gets no second answer.
    assert send_form(store, added | {"repeated": True}) == []
    assert send_form(store, added, bot="STAFF") == []


def test_the_report_buttons_open_the_form_on_the_relay() -> None:
    markup = keyboard_markup("tenant.report_kind", "km", "relay.example.workers.dev")
    assert markup == {
        "inline_keyboard": [
            [
                {
                    "text": "បញ្ហាក្នុងបន្ទប់",
                    "web_app": {
                        "url": "https://relay.example.workers.dev/app/tenant?form=unit&lang=km"
                    },
                }
            ],
            [
                {
                    "text": "បញ្ហាអគារ",
                    "web_app": {
                        "url": "https://relay.example.workers.dev/app/tenant?form=building&lang=km"
                    },
                }
            ],
        ]
    }
    with pytest.raises(TextError):
        keyboard_markup("tenant.report_kind", "en", None)


def test_the_access_list_and_choices_go_to_the_relay_only_when_they_change(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay = FakeRelay(office_key)
    store = FakeStore()
    store.form_data = {
        "choices": {"types": [{"code": "WATER"}]},
        "users": [{"id": USER, "role": "TENANT", "data": {"places": []}}],
    }
    client = _client(relay)
    assert push_form_data(client=client, store=store, status_directory=tmp_path) is True
    # Each bot's list goes once; the Staff bot list too (step 4a).
    assert [path for path, _ in relay.pushed] == [
        "/office/access/tenant",
        "/office/choices/tenant",
        "/office/access/staff",
        "/office/choices/staff",
    ]
    assert relay.pushed[0][1] == {"users": store.form_data["users"]}
    assert push_form_data(client=client, store=store, status_directory=tmp_path) is False
    store.form_data = store.form_data | {"users": []}
    assert push_form_data(client=client, store=store, status_directory=tmp_path) is True
    assert len(relay.pushed) == 6
    # A relay that cannot be reached is tried again next time.
    store.form_data = store.form_data | {"choices": {"types": []}}
    lines: list[str] = []
    broken = RelayClient(
        "relay.example.workers.dev", PULL_KEY, transport=lambda *_: (503, b""), clock=lambda: NOW
    )
    assert (
        push_form_data(client=broken, store=store, status_directory=tmp_path, log=lines.append)
        is False
    )
    assert lines == ["telegram_pull:form_data_not_sent:TENANT:relay_http_503"]
    assert push_form_data(client=client, store=store, status_directory=tmp_path) is True


def linked_store(language: str = "en") -> FakeStore:
    store = FakeStore()
    store.languages[USER] = language
    store.links[USER] = {"name": "Dara Kim", "unit_number": "305"}
    return store


def test_fixed_and_not_fixed_answer_the_tenants_check_of_the_repair() -> None:
    store = linked_store()
    store.check_answers.append({"result": "CLOSED", "report_number": "UP260007"})
    fixed = say(store, "Fixed")
    assert codes(fixed) == [("tenant.check_fixed", "tenant.menu")]
    assert fixed[0]["details"] == {"number": "UP260007"}
    store.check_answers.append({"result": "REOPENED", "report_number": "UP260007"})
    assert codes(say(store, "មិនទាន់រួច")) == [("tenant.check_not_fixed", "tenant.menu")]
    store.check_answers.append({"result": "NOTHING"})
    assert codes(say(store, "Fixed")) == [("tenant.check_nothing", "tenant.menu")]
    assert store.checks == [(USER, True), (USER, False), (USER, True)]
    # The Done message shows the two buttons and My requests, in the person's language.
    markup = keyboard_markup("tenant.check", "km")
    assert markup is not None
    assert markup["keyboard"] == [
        [{"text": "ជួសជុលរួច"}, {"text": "មិនទាន់រួច"}],
        [{"text": "សំណើរបស់ខ្ញុំ"}],
    ]
    # Someone not linked is asked to link first and nothing is checked.
    stranger = FakeStore()
    stranger.languages[USER] = "en"
    assert codes(say(stranger, "Fixed")) == [("tenant.link_first", "tenant.start")]
    assert stranger.checks == []


def test_my_requests_lists_each_report_with_its_state_and_visit() -> None:
    store = linked_store()
    store.my_reports = {
        "result": "OK",
        "unit_number": "305",
        "reports": [
            {
                "report_number": "UP260009",
                "state": "PLANNED",
                "type_en": "Water",
                "type_kh": "ទឹក",
                "technician": "Sok Khen",
                "visit_on": "06/11/2026",
                "visit_at": "09:00",
            },
            {
                "report_number": "BP260003",
                "state": "JOINED",
                "type_en": "Electricity",
                "type_kh": "អគ្គិសនី",
                "main_number": "BP260001",
            },
            {"report_number": "UP260002", "state": "CLOSED", "type_en": "Door", "type_kh": "ទ្វារ"},
        ],
    }
    answer = say(store, "My requests")
    assert codes(answer) == [("tenant.my_requests", "tenant.menu")]
    details = answer[0]["details"]
    assert details["unit"] == "305"
    assert details["list"] == (
        "UP260009 · Water: Visit planned\n"
        "   Visit: 06/11/2026 at 09:00, Sok Khen\n"
        "BP260003 · Electricity: joined to BP260001\n"
        "UP260002 · Door: Closed"
    )
    text = render("tenant.my_requests", "en", details)
    assert text.startswith("Your requests (Unit 305):\n\nUP260009")
    in_khmer = linked_store("km")
    in_khmer.my_reports = store.my_reports
    khmer = say(in_khmer, "សំណើរបស់ខ្ញុំ")
    assert khmer[0]["details"]["list"].startswith("UP260009 · ទឹក៖ បានរៀបចំការមកពិនិត្យ")
    store.my_reports = {"result": "OK", "unit_number": "305", "reports": []}
    assert codes(say(store, "My requests")) == [("tenant.my_none", "tenant.menu")]


def test_contact_office_takes_one_written_message_for_the_office() -> None:
    store = linked_store()
    assert codes(say(store, "Contact office")) == [("tenant.contact_ask", "tenant.back")]
    # A photo or a voice note is not a message here: the person is asked to write.
    assert codes(say(store, photo=[{"file_id": "x"}])) == [
        ("tenant.contact_text_only", "tenant.back")
    ]
    assert store.contacts == []
    saved = say(store, "  The light in my bathroom is weak. Can someone call me?  ")
    assert codes(saved) == [("tenant.contact_saved", "tenant.menu")]
    assert store.contacts == [
        (
            "TENANT",
            "in-1",
            USER,
            USER,
            "en",
            "Dara Kim",
            "The light in my bathroom is weak. Can someone call me?",
        )
    ]
    # The next text is not another message: the person is back at the menu.
    assert codes(say(store, "hello")) == [("tenant.menu", "tenant.menu")]
    assert len(store.contacts) == 1
    # Back to menu leaves without writing.
    say(store, "Contact office")
    assert codes(say(store, "Back to menu")) == [("tenant.menu", "tenant.menu")]
    assert len(store.contacts) == 1


def test_a_person_who_is_not_linked_can_still_contact_the_office() -> None:
    store = FakeStore()
    store.languages[USER] = "km"
    assert codes(say(store, "ទាក់ទងការិយាល័យ")) == [("tenant.contact_ask", "tenant.back")]
    answer = say(store, "ខ្ញុំមិនអាចភ្ជាប់បានទេ")
    assert codes(answer) == [("tenant.contact_saved", "tenant.start")]
    assert answer[0]["language"] == "km"
    assert store.contacts[0][4:] == ("km", "Dara Kim", "ខ្ញុំមិនអាចភ្ជាប់បានទេ")
    # The FAQ is for linked tenants.
    assert codes(say(store, "សំណួរញឹកញាប់")) == [("tenant.link_first", "tenant.start")]


def test_faq_shows_the_approved_questions_as_buttons_and_answers_the_one_tapped() -> None:
    store = linked_store()
    store.faq = [
        {
            "number": 2,
            "question_en": "What are your office hours?",
            "answer_en": "Monday to Saturday, 07:00 to 17:00.",
            "question_km": "ការិយាល័យបើកម៉ោងប៉ុន្មាន?",
            "answer_km": "ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។",
        },
        {
            "number": 5,
            "question_en": "How can I pay my rent?",
            "answer_en": "In cash at the office, by ABA or by KHQR.",
            "question_km": "តើអាចបង់ថ្លៃជួលតាមរបៀបណាខ្លះ?",
            "answer_km": "ជាសាច់ប្រាក់ ABA ឬ KHQR។",
        },
    ]
    listed = say(store, "FAQ")
    assert codes(listed) == [("tenant.faq_list", "tenant.faq")]
    choices = ["2. What are your office hours?", "5. How can I pay my rent?"]
    assert listed[0]["details"] == {"choices": choices}
    answer = say(store, "5. How can I pay my rent?")
    assert codes(answer) == [("tenant.faq_answer", "tenant.faq")]
    assert answer[0]["details"]["answer"] == "In cash at the office, by ABA or by KHQR."
    # Typing just the number works too; an unknown number shows the list again.
    assert say(store, "2")[0]["details"]["question"] == "What are your office hours?"
    assert codes(say(store, "9. Something else")) == [("tenant.faq_list", "tenant.faq")]
    assert codes(say(store, "Back to menu")) == [("tenant.menu", "tenant.menu")]
    store.languages[USER] = "km"
    khmer = say(store, "សំណួរញឹកញាប់")
    assert khmer[0]["details"]["choices"][0] == "2. ការិយាល័យបើកម៉ោងប៉ុន្មាន?"
    markup = keyboard_markup("tenant.faq", "km", None, khmer[0]["details"])
    assert markup == {
        "keyboard": [
            [{"text": "2. ការិយាល័យបើកម៉ោងប៉ុន្មាន?"}],
            [{"text": "5. តើអាចបង់ថ្លៃជួលតាមរបៀបណាខ្លះ?"}],
            [{"text": "ត្រឡប់ទៅម៉ឺនុយ"}],
        ],
        "resize_keyboard": True,
    }
    with pytest.raises(TextError):
        keyboard_markup("tenant.faq", "en", None, {})
    reply = render("contact.reply", "en", {"text": "We will call you at 10:00."})
    assert reply == "Reply from the office:\n\nWe will call you at 10:00."


def test_each_answer_names_the_message_it_answers_so_the_outbox_keeps_it_once() -> None:
    # DL-202 (B): the database queues the answer to one inbound message once.
    store = FakeStore()
    say(store, "/start")
    store.languages[USER] = "en"
    send_form(
        store,
        {
            "result": "ADDED",
            "report_number": "UP260231",
            "kind": "UNIT",
            "urgent": False,
            "plan_workdays": 1,
        },
    )
    assert store.reply_to == ["in-1", "in-1"]
