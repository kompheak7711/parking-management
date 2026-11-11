"""The Customer bot conversation (bots step 3a, DL-171).

Owner-approved CRM mock-up (customer bot view) and the owner's rules of 28 Oct to 2 Nov 2026:
Start greets the person and asks for Khmer or English, then shows Send an inquiry, FAQ and
Contact office. Send an inquiry asks, one step at a time: how to contact them, their own phone
(Telegram's share button, skipped when they shared it before), the email when they chose Email,
their name, the Unit Type, the visit day (2 to 30 days ahead, Monday to Saturday, or Skip) and
Morning or Afternoon, the move-in month (or Later) and a note they may skip. The bot then shows
the request to check, and "Send an inquiry" saves it as a Visit request (migration
20270525_287); the bot answers with its number. The bot never says which Units are free.

FAQ shows the questions the Owner approved for the Customer bot. Contact office asks for the
phone first, then takes one written message for the office.

Each answer is one database call that saves the person's next step and queues the messages
together, as in the Tenant bot.

DL-213 (owner 11 Nov 2026): while the office app is closed, the relay answers by itself (Start,
language, FAQ, Contact office and every step of Send an inquiry) and says the request was
received. When the office is back it saves what the relay did without answering again; only
the request's number is new, so only that is sent.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Final

from property_rental.telegram_store import TelegramStore
from property_rental.telegram_tenant_bot import (
    LANGUAGE_BUTTONS,
    MAX_CONTACT,
    _faq_answer,
    _message,
    _own_contact,
    _say,
    _sender_name,
)
from property_rental.telegram_texts import button_tapped, render

BOT: Final = "CUSTOMER"
# The chat steps this bot saves (telegram_chat_steps.step).
CUSTOMER_STEPS: Final = frozenset(
    {
        "language",
        "menu",
        "faq",
        "contact.phone",
        "contact",
        "ask.how",
        "ask.phone",
        "ask.email",
        "ask.name",
        "ask.type",
        "ask.day",
        "ask.part",
        "ask.move",
        "ask.note",
        "ask.check",
    }
)
HOW_BUTTONS: Final = {
    "button.by_telegram": "TELEGRAM",
    "button.by_email": "EMAIL",
    "button.by_phone": "PHONE",
    "button.by_whatsapp": "WHATSAPP",
}
HOW_LABELS: Final = {value: code for code, value in HOW_BUTTONS.items()}
PART_BUTTONS: Final = {"button.morning": "MORNING", "button.afternoon": "AFTERNOON"}
PART_LABELS: Final = {value: code for code, value in PART_BUTTONS.items()}
MAX_NAME: Final = 120
MAX_EMAIL: Final = 120
MAX_NOTE: Final = 500
# Visit days: 2 to 30 days from today, Monday to Saturday (the office's working days); the
# keyboard shows the first six.
FIRST_DAY: Final = 2
LAST_DAY: Final = 30
DAYS_SHOWN: Final = 6
# Move-in months: three months from the month two weeks ahead, then Later (as in the mock-up).
MONTHS_SHOWN: Final = 3
MONTH_AHEAD_DAYS: Final = 14
EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TYPED_DAY: Final = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")
WEEKDAYS: Final = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "km": ("ច័ន្ទ", "អង្គារ", "ពុធ", "ព្រហស្បតិ៍", "សុក្រ", "សៅរ៍", "អាទិត្យ"),
}
MONTH_NAMES: Final = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "km": (
        "មករា",
        "កុម្ភៈ",
        "មីនា",
        "មេសា",
        "ឧសភា",
        "មិថុនា",
        "កក្កដា",
        "សីហា",
        "កញ្ញា",
        "តុលា",
        "វិច្ឆិកា",
        "ធ្នូ",
    ),
}
Answer = tuple[str, list[dict[str, Any]], dict[str, Any]]


def handle_customer_update(
    bot: str, plain: dict[str, Any], saved: dict[str, Any], store: TelegramStore
) -> None:
    if bot != BOT:
        return
    message = _message(plain)
    user = plain.get("telegram_user_id")
    chat = plain.get("chat_id")
    if message is None or not isinstance(user, int) or not isinstance(chat, int) or user <= 0:
        return
    text = message.get("text")
    typed = text.strip() if isinstance(text, str) else ""
    if typed.lower() in {"ping", "/ping"}:
        return  # the shared base answers the test message
    relay = plain.get("relay")
    if isinstance(relay, dict) and relay.get("answered") is True:
        _after_relay(relay, user, chat, message, typed, saved, store)
        return
    tapped = button_tapped(typed) if typed else None
    state = store.bot_state(BOT, user)
    language = state.get("language")
    speak = language or "km"

    def reply(
        step: str,
        *messages: dict[str, Any],
        data: dict[str, Any] | None = None,
        chosen: str | None = None,
    ) -> None:
        store.bot_reply(
            BOT,
            user,
            chat,
            step,
            data,
            chosen or speak,
            list(messages),
            reply_to=saved.get("inbound_id"),
        )

    if typed.startswith("/start") or (language is None and tapped not in LANGUAGE_BUTTONS):
        reply("language", _say("customer.welcome", "tenant.language"))
        return
    if tapped in LANGUAGE_BUTTONS:
        chosen = LANGUAGE_BUTTONS[tapped]
        store.choose_language(BOT, user, chosen)
        reply("menu", _say("customer.menu", "customer.menu"), chosen=chosen)
        return
    step = state.get("step") or "menu"
    if tapped == "button.back_menu":
        reply("menu", _say("customer.menu", "customer.menu"))
        return
    if tapped == "button.contact":
        if state.get("has_phone"):
            reply("contact", _say("customer.contact_ask", "tenant.back"))
        else:
            reply("contact.phone", _say("customer.contact_phone", "customer.share_phone"))
        return
    if step == "contact.phone":
        if _own_contact(message):
            reply("contact", _say("customer.contact_ask", "tenant.back"))
        else:
            reply("contact.phone", _say("customer.phone_again", "customer.share_phone"))
        return
    if step == "contact" and tapped is None:
        inbound = saved.get("inbound_id")
        if not typed or not isinstance(inbound, str):
            reply("contact", _say("tenant.contact_text_only", "tenant.back"))
            return
        saved_contact = store.contact_add(
            BOT, inbound, user, chat, speak, _sender_name(message), typed[:MAX_CONTACT]
        )
        if saved_contact.get("result") == "BLOCKED":
            reply("menu", _say("customer.blocked", "customer.menu"))
            return
        reply("menu", _say("customer.contact_saved", "customer.menu"))
        return
    if tapped == "button.faq" or (step == "faq" and tapped is None and typed):
        entries = store.faq_for_bot(BOT)
        answer = _faq_answer(
            entries, speak, typed, tapped, keyboard="customer.faq", home="customer.menu"
        )
        reply("faq" if entries else "menu", answer)
        return
    if tapped == "button.inquiry" and step != "ask.check":
        reply("ask.how", _say("customer.ask_how", "customer.how"), data={})
        return
    if step.startswith("ask."):
        data = state.get("data")
        request = dict(data) if isinstance(data, dict) else {}
        choices = store.customer_choices(user)
        next_step, messages, request = _inquiry(
            step, request, message, typed, tapped, speak, choices, bool(state.get("has_phone"))
        )
        if next_step == "send":
            next_step, messages, request = _send(request, saved, user, chat, speak, store)
        reply(next_step, *messages, data=request)
        return
    reply("menu", _say("customer.menu", "customer.menu"))


def _after_relay(
    relay: dict[str, Any],
    user: int,
    chat: int,
    message: dict[str, Any],
    typed: str,
    saved: dict[str, Any],
    store: TelegramStore,
) -> None:
    """Save what the relay answered while the office was away (DL-213). Only a sent inquiry gets
    an answer, with the request's number."""
    chosen = relay.get("language")
    if chosen in LANGUAGE_BUTTONS.values():
        store.choose_language(BOT, user, str(chosen))
    language = str(chosen or store.bot_state(BOT, user).get("language") or "km")
    inbound = saved.get("inbound_id")
    if relay.get("contact") is True and typed and isinstance(inbound, str):
        store.contact_add(
            BOT, inbound, user, chat, language, _sender_name(message), typed[:MAX_CONTACT]
        )
    inquiry = relay.get("inquiry")
    if isinstance(inquiry, dict) and isinstance(inbound, str):
        after, messages, _ = _send(_relay_request(inquiry), saved, user, chat, language, store)
        store.bot_reply(BOT, user, chat, after, None, language, messages, reply_to=inbound)
        return
    step = relay.get("step")
    request = relay.get("request")
    store.bot_reply(
        BOT,
        user,
        chat,
        step if step in CUSTOMER_STEPS else None,
        _relay_request(request)
        if isinstance(step, str) and step.startswith("ask.") and isinstance(request, dict)
        else None,
        language,
        [],
    )


def _relay_request(request: dict[str, Any]) -> dict[str, Any]:
    """Only the inquiry fields, cut to the bot's own limits."""
    limits = {"name": MAX_NAME, "email": MAX_EMAIL, "note": MAX_NOTE}
    kept: dict[str, Any] = {}
    for field in (
        "contact_by",
        "email",
        "name",
        "unit_type",
        "visit_on",
        "visit_part",
        "move_in",
        "note",
    ):
        value = request.get(field)
        if value is None and field in request:
            kept[field] = None
        elif isinstance(value, str):
            kept[field] = value[: limits.get(field, 40)]
    return kept


def _inquiry(
    step: str,
    request: dict[str, Any],
    message: dict[str, Any],
    typed: str,
    tapped: str | None,
    language: str,
    choices: dict[str, Any],
    has_phone: bool,
) -> Answer:
    """The next step of Send an inquiry: what the person gave, the next question, or the same
    question again when the answer does not fit."""
    today = _today(choices)
    plain = typed if tapped is None else ""
    if step == "ask.how":
        if tapped not in HOW_BUTTONS:
            return step, [_say("customer.ask_how", "customer.how")], request
        request["contact_by"] = HOW_BUTTONS[tapped]
        if not has_phone:
            return "ask.phone", [_say("customer.ask_phone", "customer.share_phone")], request
        return _after_phone(request)
    if step == "ask.phone":
        if not _own_contact(message):
            return step, [_say("customer.phone_again", "customer.share_phone")], request
        return _after_phone(request)
    if step == "ask.email":
        if len(plain) > MAX_EMAIL or not EMAIL.match(plain):
            return step, [_say("customer.email_again", "tenant.back")], request
        request["email"] = plain
        return "ask.name", [_say("customer.ask_name", "tenant.back")], request
    if step == "ask.name":
        if not plain:
            return step, [_say("customer.ask_name", "tenant.back")], request
        request["name"] = plain[:MAX_NAME].strip()
        return "ask.type", [_type_question("customer.ask_type", choices, language)], request
    if step == "ask.type":
        code = _unit_type_code(choices, plain)
        if code is None:
            return step, [_type_question("customer.type_again", choices, language)], request
        request["unit_type"] = code
        return "ask.day", [_day_question("customer.ask_day", today, language)], request
    if step == "ask.day":
        if tapped == "button.skip":
            request["visit_on"] = None
            request["visit_part"] = None
            return "ask.move", [_month_question(today, language)], request
        chosen = _typed_day(plain, today)
        if chosen is None:
            return step, [_day_question("customer.day_again", today, language)], request
        request["visit_on"] = chosen.isoformat()
        return "ask.part", [_say("customer.ask_part", "customer.part")], request
    if step == "ask.part":
        if tapped not in PART_BUTTONS:
            return step, [_say("customer.ask_part", "customer.part")], request
        request["visit_part"] = PART_BUTTONS[tapped]
        return "ask.move", [_month_question(today, language)], request
    if step == "ask.move":
        if tapped == "button.later":
            request["move_in"] = "LATER"
        else:
            month = _typed_month(plain, today)
            if month is None:
                return step, [_month_question(today, language)], request
            request["move_in"] = month
        return "ask.note", [_say("customer.ask_note", "customer.skip")], request
    if step == "ask.note":
        if tapped == "button.skip":
            request["note"] = None
        elif plain:
            request["note"] = plain[:MAX_NOTE].strip()
        else:
            return step, [_say("customer.ask_note", "customer.skip")], request
        return "ask.check", [_summary(request, choices, language)], request
    if step == "ask.check" and tapped == "button.inquiry":
        return "send", [], request
    return "ask.check", [_summary(request, choices, language)], request


def _after_phone(request: dict[str, Any]) -> Answer:
    if request.get("contact_by") == "EMAIL":
        return "ask.email", [_say("customer.ask_email", "tenant.back")], request
    return "ask.name", [_say("customer.ask_name", "tenant.back")], request


def _send(
    request: dict[str, Any],
    saved: dict[str, Any],
    user: int,
    chat: int,
    language: str,
    store: TelegramStore,
) -> Answer:
    """Save the Visit request and answer with its number."""
    needed = ("contact_by", "name", "unit_type", "move_in")
    inbound = saved.get("inbound_id")
    if not isinstance(inbound, str) or any(not request.get(field) for field in needed):
        return "ask.how", [_say("customer.ask_how", "customer.how")], {}
    result = store.visit_request_add(inbound, user, chat, language, request)
    outcome = result.get("result")
    if outcome == "NO_PHONE":
        return "ask.phone", [_say("customer.ask_phone", "customer.share_phone")], request
    if outcome == "BLOCKED":
        return "menu", [_say("customer.blocked", "customer.menu")], {}
    number = str(result.get("number") or "")
    if result.get("main_number"):
        joined = _say(
            "customer.request_joined",
            "customer.menu",
            number=number,
            main=str(result["main_number"]),
        )
        return "menu", [joined], {}
    return "menu", [_say("customer.request_received", "customer.menu", number=number)], {}


def _today(choices: dict[str, Any]) -> date:
    value = choices.get("today")
    return date.fromisoformat(value) if isinstance(value, str) else date.today()


def _unit_types(choices: dict[str, Any]) -> list[dict[str, Any]]:
    types = choices.get("unit_types")
    return [item for item in types if isinstance(item, dict)] if isinstance(types, list) else []


def _unit_type_name(item: dict[str, Any], language: str) -> str:
    name = item.get("name_km") if language == "km" else item.get("name_en")
    return str(name or item.get("name_en") or item.get("code") or "")


def _type_question(code: str, choices: dict[str, Any], language: str) -> dict[str, Any]:
    names = [_unit_type_name(item, language) for item in _unit_types(choices)]
    return _say(code, "customer.types", choices=names)


def _unit_type_code(choices: dict[str, Any], typed: str) -> str | None:
    """The Unit Type whose name (in either language) the person tapped."""
    for item in _unit_types(choices):
        if typed and typed in {_unit_type_name(item, "en"), _unit_type_name(item, "km")}:
            code = item.get("code")
            return str(code) if code else None
    return None


def _day_label(day: date, language: str) -> str:
    return f"{WEEKDAYS['km' if language == 'km' else 'en'][day.weekday()]} {day:%d/%m}"


def _visit_days(today: date) -> list[date]:
    days = [today + timedelta(days=ahead) for ahead in range(FIRST_DAY, LAST_DAY + 1)]
    return [day for day in days if day.isoweekday() != 7]


def _day_question(code: str, today: date, language: str) -> dict[str, Any]:
    labels = [_day_label(day, language) for day in _visit_days(today)[:DAYS_SHOWN]]
    return _say(code, "customer.days", choices=labels)


def _typed_day(typed: str, today: date) -> date | None:
    """The visit day the person tapped or typed as day/month, when it is allowed."""
    found = TYPED_DAY.search(typed)
    if found is None:
        return None
    day, month = int(found.group(1)), int(found.group(2))
    for year in (today.year, today.year + 1):
        try:
            chosen = date(year, month, day)
        except ValueError:
            return None
        if chosen in _visit_days(today):
            return chosen
    return None


def _months(today: date) -> list[date]:
    first = (today + timedelta(days=MONTH_AHEAD_DAYS)).replace(day=1)
    months: list[date] = []
    for _ in range(MONTHS_SHOWN):
        months.append(first)
        first = (first + timedelta(days=32)).replace(day=1)
    return months


def _month_label(month: date, language: str) -> str:
    names = MONTH_NAMES["km" if language == "km" else "en"]
    return f"{names[month.month - 1]} {month.year}"


def _month_question(today: date, language: str) -> dict[str, Any]:
    labels = [_month_label(month, language) for month in _months(today)]
    return _say("customer.ask_move", "customer.months", choices=labels)


def _typed_month(typed: str, today: date) -> str | None:
    for month in _months(today):
        if typed in {_month_label(month, "en"), _month_label(month, "km")}:
            return f"{month:%Y-%m}"
    return None


def _summary(request: dict[str, Any], choices: dict[str, Any], language: str) -> dict[str, Any]:
    """The request to check, in the person's language, with the Send an inquiry button."""
    how = HOW_LABELS.get(str(request.get("contact_by") or ""))
    contact = render(how, language, {}) if how else ""
    if request.get("email"):
        contact = f"{contact} ({request['email']})"
    unit_type = ""
    for item in _unit_types(choices):
        if item.get("code") == request.get("unit_type"):
            unit_type = _unit_type_name(item, language)
    visit = render("customer.no_day", language, {})
    if isinstance(request.get("visit_on"), str):
        part = PART_LABELS.get(str(request.get("visit_part") or ""))
        visit = _day_label(date.fromisoformat(request["visit_on"]), language)
        if part:
            visit = f"{visit}, {render(part, language, {})}"
    move = render("button.later", language, {})
    if isinstance(request.get("move_in"), str) and request["move_in"] != "LATER":
        move = _month_label(date.fromisoformat(request["move_in"] + "-01"), language)
    return _say(
        "customer.check",
        "customer.send",
        name=str(request.get("name") or ""),
        phone=str(choices.get("phone") or ""),
        contact=contact,
        type=unit_type,
        visit=visit,
        move=move,
        note=str(request.get("note") or "-"),
    )
