"""The Customer bot conversation (DL-171, bots step 3a): Start, language, Send an inquiry, FAQ
and Contact office."""

from __future__ import annotations

from typing import Any

from property_rental.telegram_customer_bot import CUSTOMER_STEPS, handle_customer_update
from property_rental.telegram_texts import keyboard_markup, render
from test_telegram_jobs import FakeStore

USER = 880
OWN_PHONE = {"user_id": USER, "phone_number": "85512800200"}
TYPES = [
    {"code": "STUDIO", "name_en": "Studio", "name_km": "ស្ទូឌីយោ"},
    {"code": "TWO_BEDROOM", "name_en": "2 bedrooms", "name_km": "បន្ទប់គេង ២"},
]


def say(store: FakeStore, text: str | None = None, **message: Any) -> list[dict[str, Any]]:
    before = len(store.replies)
    body: dict[str, Any] = {
        "from": {"id": USER, "first_name": "Sokha", "last_name": "Chan"},
        "chat": {"id": USER, "type": "private"},
        **message,
    }
    if text is not None:
        body["text"] = text
    plain = {"telegram_user_id": USER, "chat_id": USER, "payload": {"message": body}}
    handle_customer_update("CUSTOMER", plain, {"saved": True, "inbound_id": "in-9"}, store)
    return store.replies[before:]


def codes(replies: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(reply["text_code"], reply.get("keyboard")) for reply in replies]


def english_store() -> FakeStore:
    store = FakeStore()
    store.languages[USER] = "en"
    store.choices = {"today": "2026-11-05", "unit_types": TYPES, "phone": "+85512800200"}
    return store


def test_start_asks_for_the_language_then_shows_the_three_choices() -> None:
    store = FakeStore()
    assert codes(say(store, "/start")) == [("customer.welcome", "tenant.language")]
    assert codes(say(store, "hello")) == [("customer.welcome", "tenant.language")]
    answer = say(store, "ភាសាខ្មែរ")
    assert codes(answer) == [("customer.menu", "customer.menu")]
    assert answer[0]["language"] == "km" and answer[0]["bot"] == "CUSTOMER"
    menu = keyboard_markup("customer.menu", "km")
    assert menu is not None
    assert menu["keyboard"] == [
        [{"text": "ផ្ញើការសាកសួរ"}],
        [{"text": "សំណួរញឹកញាប់"}, {"text": "ទាក់ទងការិយាល័យ"}],
    ]
    # The Tenant bot's updates are not this bot's.
    plain = {"telegram_user_id": USER, "chat_id": USER, "payload": {"message": {}}}
    handle_customer_update("TENANT", plain, {"saved": True}, store)
    assert store.steps[USER][0] in CUSTOMER_STEPS


def test_an_inquiry_asks_each_question_then_saves_the_request() -> None:
    store = english_store()
    assert codes(say(store, "Send an inquiry")) == [("customer.ask_how", "customer.how")]
    assert codes(say(store, "Hello")) == [("customer.ask_how", "customer.how")]
    assert codes(say(store, "Email")) == [("customer.ask_phone", "customer.share_phone")]
    # Only the person's own number counts.
    other = {"user_id": 1, "phone_number": "85512000000"}
    assert codes(say(store, contact=other)) == [("customer.phone_again", "customer.share_phone")]
    assert codes(say(store, contact=OWN_PHONE)) == [("customer.ask_email", "tenant.back")]
    assert codes(say(store, "not an email")) == [("customer.email_again", "tenant.back")]
    assert codes(say(store, "sokha@example.com")) == [("customer.ask_name", "tenant.back")]
    types = say(store, "Sokha Chan")
    assert codes(types) == [("customer.ask_type", "customer.types")]
    assert types[0]["details"]["choices"] == ["Studio", "2 bedrooms"]
    assert codes(say(store, "Penthouse")) == [("customer.type_again", "customer.types")]
    days = say(store, "2 bedrooms")
    assert codes(days) == [("customer.ask_day", "customer.days")]
    # Thursday 5 Nov: from Saturday, two days ahead, with no Sunday.
    assert days[0]["details"]["choices"] == [
        "Sat 07/11",
        "Mon 09/11",
        "Tue 10/11",
        "Wed 11/11",
        "Thu 12/11",
        "Fri 13/11",
    ]
    # Tomorrow, a Sunday or more than 30 days ahead are refused.
    for wrong in ("06/11", "08/11", "06/12", "31/02"):
        assert codes(say(store, wrong)) == [("customer.day_again", "customer.days")]
    assert codes(say(store, "Mon 09/11")) == [("customer.ask_part", "customer.part")]
    months = say(store, "Afternoon")
    assert codes(months) == [("customer.ask_move", "customer.months")]
    assert months[0]["details"]["choices"] == ["November 2026", "December 2026", "January 2027"]
    assert codes(say(store, "December 2026")) == [("customer.ask_note", "customer.skip")]
    summary = say(store, "  I would like a high floor.  ")
    assert codes(summary) == [("customer.check", "customer.send")]
    assert summary[0]["details"] == {
        "name": "Sokha Chan",
        "phone": "+85512800200",
        "contact": "Email (sokha@example.com)",
        "type": "2 bedrooms",
        "visit": "Mon 09/11, Afternoon",
        "move": "December 2026",
        "note": "I would like a high floor.",
    }
    text = render("customer.check", "en", summary[0]["details"])
    assert "Viewing: Mon 09/11, Afternoon" in text and "Move-in: December 2026" in text
    # Anything but the button shows the request again.
    assert codes(say(store, "ok")) == [("customer.check", "customer.send")]

    store.inquiry_answers.append({"result": "ADDED", "number": "VR260001", "main_number": None})
    sent = say(store, "Send an inquiry")
    assert codes(sent) == [("customer.request_received", "customer.menu")]
    assert sent[0]["details"] == {"number": "VR260001"}
    assert store.inquiries == [
        (
            "in-9",
            USER,
            USER,
            "en",
            {
                "contact_by": "EMAIL",
                "email": "sokha@example.com",
                "name": "Sokha Chan",
                "unit_type": "TWO_BEDROOM",
                "visit_on": "2026-11-09",
                "visit_part": "AFTERNOON",
                "move_in": "2026-12",
                "note": "I would like a high floor.",
            },
        )
    ]
    assert store.steps[USER] == ("menu", {})


def test_a_known_phone_is_not_asked_again_and_skips_are_allowed() -> None:
    store = english_store()
    store.languages[USER] = "km"
    store.phones.add(USER)
    say(store, "ផ្ញើការសាកសួរ")
    assert codes(say(store, "WhatsApp")) == [("customer.ask_name", "tenant.back")]
    say(store, "សុខា")
    say(store, "ស្ទូឌីយោ")
    assert codes(say(store, "រំលង")) == [("customer.ask_move", "customer.months")]
    assert codes(say(store, "ក្រោយ")) == [("customer.ask_note", "customer.skip")]
    summary = say(store, "រំលង")
    assert summary[0]["details"]["visit"] == "មិនទាន់កំណត់"
    assert summary[0]["details"]["move"] == "ក្រោយ"
    assert summary[0]["details"]["note"] == "-"
    store.inquiry_answers.append(
        {"result": "JOINED", "number": "VR260002", "main_number": "VR260001"}
    )
    joined = say(store, "ផ្ញើការសាកសួរ")
    assert codes(joined) == [("customer.request_joined", "customer.menu")]
    assert joined[0]["details"] == {"number": "VR260002", "main": "VR260001"}
    request = store.inquiries[0][4]
    assert request["contact_by"] == "WHATSAPP" and request["move_in"] == "LATER"
    assert request["visit_on"] is None and request["note"] is None


def test_back_to_menu_leaves_the_inquiry_and_a_lost_phone_asks_again() -> None:
    store = english_store()
    store.phones.add(USER)
    say(store, "Send an inquiry")
    assert codes(say(store, "Back to menu")) == [("customer.menu", "customer.menu")]
    say(store, "Send an inquiry")
    say(store, "Telegram")
    say(store, "Sokha")
    say(store, "Studio")
    say(store, "Skip")
    say(store, "Later")
    say(store, "Skip")
    store.inquiry_answers.append({"result": "NO_PHONE"})
    assert codes(say(store, "Send an inquiry")) == [("customer.ask_phone", "customer.share_phone")]


def test_contact_office_asks_for_the_phone_first_then_takes_one_message() -> None:
    store = english_store()
    assert codes(say(store, "Contact office")) == [
        ("customer.contact_phone", "customer.share_phone")
    ]
    assert codes(say(store, "0128002000")) == [("customer.phone_again", "customer.share_phone")]
    assert codes(say(store, contact=OWN_PHONE)) == [("customer.contact_ask", "tenant.back")]
    assert codes(say(store, photo=[{"file_id": "x"}])) == [
        ("tenant.contact_text_only", "tenant.back")
    ]
    assert codes(say(store, "Does the Studio have a washing machine?")) == [
        ("customer.contact_saved", "customer.menu")
    ]
    assert store.contacts == [
        (
            "CUSTOMER",
            "in-9",
            USER,
            USER,
            "en",
            "Sokha Chan",
            "Does the Studio have a washing machine?",
        )
    ]
    # With the phone known, Contact office asks for the message at once.
    store.phones.add(USER)
    assert codes(say(store, "Contact office")) == [("customer.contact_ask", "tenant.back")]


def test_the_faq_shows_the_customer_questions() -> None:
    store = english_store()
    assert codes(say(store, "FAQ")) == [("tenant.faq_none", "customer.menu")]
    store.faq = [
        {
            "number": 1,
            "question_en": "Where is CHETANA Residence?",
            "answer_en": "Near Camko Roundabout.",
            "question_km": "នៅទីណា?",
            "answer_km": "ក្បែររង្វង់មូលកាំកូ។",
        }
    ]
    listed = say(store, "FAQ")
    assert codes(listed) == [("tenant.faq_list", "customer.faq")]
    assert listed[0]["details"]["choices"] == ["1. Where is CHETANA Residence?"]
    answered = say(store, "1. Where is CHETANA Residence?")
    assert codes(answered) == [("tenant.faq_answer", "customer.faq")]
    assert answered[0]["details"]["answer"] == "Near Camko Roundabout."
    markup = keyboard_markup("customer.days", "en", details={"choices": ["Sat 07/11"]})
    assert markup is not None
    assert markup["keyboard"] == [
        [{"text": "Sat 07/11"}],
        [{"text": "Skip"}],
        [{"text": "Back to menu"}],
    ]


def test_the_visit_messages_from_the_app_have_their_words() -> None:
    details = {
        "day": "Saturday 07/11/2026",
        "time": "09:00",
        "staff": "Dara",
        "address": "Near Camko Roundabout",
    }
    booked = render("customer.visit_booked", "en", details)
    assert "Date: Saturday 07/11/2026 at 09:00" in booked and "Staff: Dara" in booked
    assert "Address: Near Camko Roundabout" in render("customer.visit_moved", "en", details)
    reminder = render(
        "customer.visit_reminder", "km", {"day": "ថ្ងៃសៅរ៍ 07/11/2026", "time": "09:00"}
    )
    assert reminder.startswith("រំលឹក៖") and "09:00" in reminder


def test_a_blocked_account_is_told_to_visit_or_call_the_office() -> None:
    store = english_store()
    store.phones.add(USER)
    store.blocked = True
    say(store, "Contact office")
    assert codes(say(store, "Hello")) == [("customer.blocked", "customer.menu")]
    say(store, "Send an inquiry")
    say(store, "Telegram")
    say(store, "Sokha")
    say(store, "Studio")
    say(store, "Skip")
    say(store, "Later")
    say(store, "Skip")
    store.inquiry_answers.append({"result": "BLOCKED"})
    assert codes(say(store, "Send an inquiry")) == [("customer.blocked", "customer.menu")]
    assert store.steps[USER] == ("menu", {})


def test_each_answer_names_the_message_it_answers_so_the_outbox_keeps_it_once() -> None:
    # DL-202 (B): the database queues the answer to one inbound message once.
    store = FakeStore()
    say(store, "/start")
    assert store.reply_to == ["in-9"]
