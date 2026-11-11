"""The Tenant bot conversation: Start, language and linking (step 2a, DL-126), and the Problem
report form (step 2b, DL-127).

Owner rules (2 and 3 Nov 2026, tenant mock-up v15): Start greets the person and asks for Khmer or
English. A person who is not linked sees only "Link my Lease". Linking asks for the person's own
Telegram phone number (Telegram's share button), then the full name, then the Unit; the database
decides the match (migration 20270520_282). A linked tenant sees the menu: Problem report, My
requests, FAQ and Contact office. Problem report opens the Unit Problem or Building problem
form (a Mini App on the relay); the database saves the report (migration 20270521_283) and the
bot answers with its number. Step 2d (DL-129): the tenant hears each step of a report (the
database queues those messages), taps Fixed or Not fixed when the repair is done, and sees My
requests. Step 2d part 2 (DL-170): Contact office takes one written message for the office
(also for a person who is not linked yet); FAQ shows the questions the Owner approved, each as a
button, and answers the one tapped.

Each answer is one database call that saves the person's next step and queues the messages
together, so a reply is never sent for a step that was not saved.

DL-210 (owner 7 Nov 2026, "Bot answers by itself"): while the office app is closed, the relay
answers the chat and says in the item what it did. Such a message is saved the same way (the
language, the Contact office message, the Lease link try, the next step) but not answered again;
only when the database's link answer differs from the relay's does the tenant get the database's.
A Problem report the relay already sent to the caretaker is saved without a second alert.

DL-214 (owner 11 Nov 2026, "Yes, QR for tenants and guests"): staff show a one-time QR at Lease
signing or guest check-in. Scanning it opens this bot with "/start <code>"; the database links
the person at once (a short-stay guest until check-out), with no phone, name or Unit to type.

DL-219 (owner 11 Nov 2026: "all telegram bot has to reply immediately even app open or close"):
the relay answers every message, app open or closed, and the app collects the messages every 150
seconds. The relay also answers FAQ, My requests and Fixed or Not fixed from what the app sends it
(``relay_person``); the database closes or reopens the repair when the app collects the tap, and
the tenant hears the database's answer only when it differs from the relay's.
"""

from __future__ import annotations

import re
from typing import Any, Final

from property_rental.telegram_store import TelegramStore
from property_rental.telegram_texts import TEXTS, button_tapped, render

BOT: Final = "TENANT"
MAX_NAME: Final = 120
MAX_UNIT: Final = 20
# The Start of a QR scan (DL-214): 40 lower-case hex letters made by the database.
START_CODE: Final = re.compile(r"^/start\s+([0-9a-f]{40})$")
LANGUAGE_BUTTONS: Final = {"button.khmer": "km", "button.english": "en"}
# The chat steps this bot saves (telegram_chat_steps.step).
TENANT_STEPS: Final = frozenset(
    {"language", "menu", "link.phone", "link.name", "link.unit", "contact", "faq"}
)
CHECK_BUTTONS: Final = {"button.fixed": True, "button.not_fixed": False}
MY_REQUESTS_SHOWN: Final = 10
MAX_CONTACT: Final = 1000
MAX_SENDER_NAME: Final = 120
# A FAQ button reads "3. Question...": the number before the dot names the question.
FAQ_NUMBER: Final = re.compile(r"^\s*(\d{1,3})(?:[.)]|\s*$)")


def _message(plain: dict[str, Any]) -> dict[str, Any] | None:
    payload = plain.get("payload")
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    # The Tenant bot talks only in private chats with the person.
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    return message


def _own_contact(message: dict[str, Any]) -> bool:
    contact = message.get("contact")
    sender = message.get("from")
    return (
        isinstance(contact, dict)
        and isinstance(sender, dict)
        and contact.get("user_id") == sender.get("id")
    )


def _say(code: str, keyboard: str | None = None, **details: object) -> dict[str, Any]:
    message: dict[str, Any] = {"text_code": code, "details": details}
    if keyboard is not None:
        message["keyboard"] = keyboard
    return message


def handle_tenant_update(
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

    def reply(
        step: str | None,
        *messages: dict[str, Any],
        data: dict[str, Any] | None = None,
        speak: str | None = None,
    ) -> None:
        store.bot_reply(
            BOT,
            user,
            chat,
            step,
            data,
            speak or language or "km",
            list(messages),
            reply_to=saved.get("inbound_id"),
        )

    started = START_CODE.match(typed)
    if started is not None:
        answer = _code_answer(store.tenant_link_code(user, started.group(1)))
        if language is None:
            reply("language", answer, _say("tenant.welcome", "tenant.language"))
        else:
            reply("menu", answer)
        return
    if typed.startswith("/start") or (language is None and tapped not in LANGUAGE_BUTTONS):
        reply("language", _say("tenant.welcome", "tenant.language"))
        return
    if tapped in LANGUAGE_BUTTONS:
        chosen = LANGUAGE_BUTTONS[tapped]
        store.choose_language(BOT, user, chosen)
        reply("menu", _hello(state), speak=chosen)
        return
    link = state.get("link")
    step = state.get("step") or "menu"
    if tapped == "button.link":
        if state.get("blocked_until"):
            reply("menu", _say("tenant.blocked", "tenant.reject"))
        else:
            reply("link.phone", _say("tenant.ask_phone", "tenant.share_phone"))
        return
    if step == "link.phone":
        if _own_contact(message) and state.get("has_phone"):
            reply("link.name", _say("tenant.ask_name", "remove"))
        else:
            reply("link.phone", _say("tenant.ask_phone_again", "tenant.share_phone"))
        return
    if step == "link.name" and typed and tapped is None:
        reply("link.unit", _say("tenant.ask_unit"), data={"name": typed[:MAX_NAME]})
        return
    if step == "link.unit" and typed and tapped is None:
        name = str((state.get("data") or {}).get("name") or "")
        if not name:
            reply("link.name", _say("tenant.ask_name", "remove"))
            return
        reply("menu", *_link_answer(store.tenant_link(user, name, typed[:MAX_UNIT])))
        return
    home = "tenant.menu" if link is not None else "tenant.start"
    if tapped == "button.contact":
        reply("contact", _say("tenant.contact_ask", "tenant.back"))
        return
    if step == "contact" and tapped is None:
        inbound = saved.get("inbound_id")
        if not typed or not isinstance(inbound, str):
            reply("contact", _say("tenant.contact_text_only", "tenant.back"))
            return
        store.contact_add(
            BOT, inbound, user, chat, language or "km", _sender_name(message), typed[:MAX_CONTACT]
        )
        reply("menu", _say("tenant.contact_saved", home))
        return
    if link is None:
        reply("menu", _say("tenant.link_first", "tenant.start"))
        return
    if tapped == "button.back_menu":
        reply("menu", _say("tenant.menu", "tenant.menu"))
        return
    if tapped == "button.faq" or (step == "faq" and tapped is None and typed):
        entries = store.faq_for_bot(BOT)
        reply("faq" if entries else "menu", _faq_answer(entries, language or "km", typed, tapped))
        return
    if tapped == "button.problem":
        reply("menu", _say("tenant.report_kind", "tenant.report_kind"))
        return
    if tapped in CHECK_BUTTONS:
        reply("menu", _check_answer(store.tenant_report_check(user, CHECK_BUTTONS[tapped])))
        return
    if tapped == "button.my_requests":
        reply("menu", _my_requests(store.tenant_my_reports(user), language or "km"))
        return
    reply("menu", _say("tenant.menu", "tenant.menu"))


def _after_relay(
    relay: dict[str, Any],
    user: int,
    chat: int,
    message: dict[str, Any],
    typed: str,
    saved: dict[str, Any],
    store: TelegramStore,
) -> None:
    """Save what the relay answered (DL-210; DL-219: every message), without answering again."""
    chosen = relay.get("language")
    if chosen in LANGUAGE_BUTTONS.values():
        store.choose_language(BOT, user, str(chosen))
    language = str(chosen or store.bot_state(BOT, user).get("language") or "km")
    code = relay.get("code")
    started = START_CODE.match(typed)
    if isinstance(code, dict) and started is not None:
        result = store.tenant_link_code(user, started.group(1))
        linked = result.get("result") == "LINKED"
        answer = [] if linked == (code.get("outcome") == "LINKED") else [_code_answer(result)]
        step = relay.get("step")
        store.bot_reply(
            BOT, user, chat, step if step in TENANT_STEPS else "menu", None, language, answer
        )
        return
    link = relay.get("link")
    if isinstance(link, dict):
        name = str(link.get("name") or "").strip()[:MAX_NAME]
        unit = str(link.get("unit") or "").strip()[:MAX_UNIT]
        if name and unit:
            result = store.tenant_link(user, name, unit)
            linked = result.get("result") == "LINKED"
            if linked == (link.get("outcome") == "LINKED"):
                store.bot_reply(BOT, user, chat, "menu", None, language, [])
            else:
                store.bot_reply(BOT, user, chat, "menu", None, language, _link_answer(result))
            return
    check = relay.get("check")
    if isinstance(check, dict) and isinstance(check.get("fixed"), bool):
        # DL-219: the relay answered Fixed or Not fixed from what the office last sent. The
        # database decides now; only a different answer is sent.
        result = store.tenant_report_check(user, bool(check["fixed"]))
        told = check.get("number")
        number = str(result.get("report_number") or "")
        same = (
            result.get("result") in {"CLOSED", "REOPENED"} and told == number
            if told
            else result.get("result") == "NOTHING"
        )
        store.bot_reply(
            BOT, user, chat, "menu", None, language, [] if same else [_check_answer(result)]
        )
        return
    if relay.get("contact") is True:
        inbound = saved.get("inbound_id")
        if typed and isinstance(inbound, str):
            store.contact_add(
                BOT, inbound, user, chat, language, _sender_name(message), typed[:MAX_CONTACT]
            )
    step = relay.get("step")
    name = str(relay.get("name") or "")[:MAX_NAME]
    store.bot_reply(
        BOT,
        user,
        chat,
        step if step in TENANT_STEPS else None,
        {"name": name} if step == "link.unit" and name else None,
        language,
        [],
    )


def _sender_name(message: dict[str, Any]) -> str | None:
    """The person's Telegram name, for the office to see who wrote."""
    sender = message.get("from")
    if not isinstance(sender, dict):
        return None
    parts = [sender.get("first_name"), sender.get("last_name")]
    name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    return name[:MAX_SENDER_NAME] or None


def _faq_answer(
    entries: list[dict[str, Any]],
    language: str,
    typed: str,
    tapped: str | None,
    *,
    keyboard: str = "tenant.faq",
    home: str = "tenant.menu",
) -> dict[str, Any]:
    """The list of questions as buttons, or the answer to the one the person tapped (both bots:
    the Customer bot passes its own keyboards)."""
    if not entries:
        return _say("tenant.faq_none", home)
    suffix = "km" if language == "km" else "en"
    choices = [
        f"{entry.get('number')}. {entry.get('question_' + suffix) or ''}" for entry in entries
    ]
    found = FAQ_NUMBER.match(typed) if tapped is None else None
    if found is not None:
        number = int(found.group(1))
        for entry in entries:
            if entry.get("number") == number:
                return _say(
                    "tenant.faq_answer",
                    keyboard,
                    question=str(entry.get("question_" + suffix) or ""),
                    answer=str(entry.get("answer_" + suffix) or ""),
                    choices=choices,
                )
    return _say("tenant.faq_list", keyboard, choices=choices)


def _hello(state: dict[str, Any]) -> dict[str, Any]:
    link = state.get("link")
    if isinstance(link, dict):
        return _say(
            "tenant.hello_linked", "tenant.menu", name=link["name"], unit=link["unit_number"]
        )
    return _say("tenant.hello", "tenant.start")


def _code_answer(result: dict[str, Any]) -> dict[str, Any]:
    """The answer to a QR scan (DL-214): linked, the stay is over, or the code does not work."""
    outcome = result.get("result")
    if outcome == "LINKED":
        return _say(
            "tenant.linked_code", "tenant.menu", name=result["name"], unit=result["unit_number"]
        )
    if outcome == "ENDED":
        return _say("tenant.code_ended", "tenant.reject")
    return _say("tenant.code_bad", "tenant.reject")


def _link_answer(result: dict[str, Any]) -> list[dict[str, Any]]:
    outcome = result.get("result")
    if outcome == "LINKED":
        return [
            _say("tenant.linked", "tenant.menu", name=result["name"], unit=result["unit_number"])
        ]
    if outcome == "NO_PHONE":
        return [_say("tenant.ask_phone", "tenant.share_phone")]
    tries_left = int(result.get("tries_left") or 0)
    if outcome == "BLOCKED" or tries_left == 0:
        return [_say("tenant.blocked", "tenant.reject")]
    return [_say("tenant.no_match", "tenant.reject", tries_left=tries_left)]


def handle_tenant_form(
    bot: str, plain: dict[str, Any], saved: dict[str, Any], store: TelegramStore
) -> None:
    """A Problem report form sent from the Mini App: save it, then answer with its number."""
    if bot != BOT:
        return
    user = plain.get("telegram_user_id")
    chat = plain.get("chat_id")
    inbound = saved.get("inbound_id")
    payload = plain.get("payload")
    if not isinstance(user, int) or not isinstance(chat, int) or user <= 0:
        return
    if not isinstance(inbound, str) or not isinstance(payload, dict):
        return
    form = payload.get("form")
    media = saved.get("media_ids")
    relay = plain.get("relay")
    result = store.tenant_problem_report(
        inbound,
        form if isinstance(form, dict) else {},
        [str(media_id) for media_id in media] if isinstance(media, list) else [],
        relay_alerted=isinstance(relay, dict) and relay.get("alerted") is True,
    )
    if result.get("repeated") is True:
        return
    language = store.bot_state(BOT, user).get("language") or "km"
    store.bot_reply(
        BOT, user, chat, "menu", None, language, [_report_answer(result)], reply_to=inbound
    )


def _report_answer(result: dict[str, Any]) -> dict[str, Any]:
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("tenant.report_not_linked", "tenant.start")
    if outcome != "ADDED":
        return _say("tenant.report_invalid", "tenant.menu")
    number = str(result.get("report_number") or "")
    if result.get("joined_to"):
        return _say("tenant.report_joined", "tenant.menu", number=number, main=result["joined_to"])
    urgent = result.get("urgent") is True
    if result.get("kind") == "BUILDING":
        code = "tenant.report_building_urgent" if urgent else "tenant.report_building"
        return _say(code, "tenant.menu", number=number)
    if urgent:
        hours = int(result.get("urgent_hours") or 1)
        code = "tenant.report_urgent" if hours == 1 else "tenant.report_urgent_hours"
        return _say(code, "tenant.menu", number=number, hours=hours)
    days = int(result.get("plan_workdays") or 1)
    code = "tenant.report_received" if days == 1 else "tenant.report_received_days"
    return _say(code, "tenant.menu", number=number, days=days)


def _check_answer(result: dict[str, Any]) -> dict[str, Any]:
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("tenant.link_first", "tenant.start")
    number = str(result.get("report_number") or "")
    if outcome == "CLOSED":
        return _say("tenant.check_fixed", "tenant.menu", number=number)
    if outcome == "REOPENED":
        return _say("tenant.check_not_fixed", "tenant.menu", number=number)
    return _say("tenant.check_nothing", "tenant.menu")


def _my_requests(result: dict[str, Any], language: str) -> dict[str, Any]:
    """My requests as one message: a fixed line for each report, in the person's language."""
    if result.get("result") != "OK":
        return _say("tenant.link_first", "tenant.start")
    lines = _request_lines(result, language)
    if not lines:
        return _say("tenant.my_none", "tenant.menu")
    return _say(
        "tenant.my_requests",
        "tenant.menu",
        unit=str(result.get("unit_number") or ""),
        list=lines,
    )


def _request_lines(result: dict[str, Any], language: str) -> str:
    """The lines of My requests (empty when there is none)."""
    reports = result.get("reports")
    if not isinstance(reports, list):
        return ""
    lines: list[str] = []
    for report in reports[:MY_REQUESTS_SHOWN]:
        if not isinstance(report, dict):
            continue
        number = str(report.get("report_number") or "")
        name = report.get("type_kh") if language == "km" else report.get("type_en")
        kind = str(name or report.get("type_en") or "")
        state = str(report.get("state") or "")
        if state == "JOINED" and report.get("main_number"):
            lines.append(
                render(
                    "tenant.my_joined",
                    language,
                    {"number": number, "type": kind, "main": report["main_number"]},
                )
            )
            continue
        status = render(f"status.{state}", language, {}) if f"status.{state}" in TEXTS else state
        lines.append(
            render("tenant.my_line", language, {"number": number, "type": kind, "status": status})
        )
        if report.get("visit_on") and report.get("visit_at"):
            lines.append(
                render(
                    "tenant.my_visit",
                    language,
                    {
                        "day": report["visit_on"],
                        "time": report["visit_at"],
                        "technician": report.get("technician") or "",
                    },
                )
            )
    return "\n".join(lines)


def relay_person(result: dict[str, Any]) -> dict[str, Any]:
    """DL-219: what the relay needs to answer one linked person at once, from their My requests:
    the lines in both languages, and the newest Unit repair marked done (the one Fixed or Not
    fixed answers; the database decides again when the app collects the tap)."""
    if result.get("result") != "OK":
        return {}
    reports = result.get("reports")
    done = next(
        (
            str(report["report_number"])
            for report in (reports if isinstance(reports, list) else [])
            if isinstance(report, dict)
            and report.get("kind") == "UNIT"
            and report.get("state") == "DONE"
            and report.get("report_number")
        ),
        None,
    )
    return {
        "requests": {language: _request_lines(result, language) for language in ("km", "en")},
        "check": done,
    }
