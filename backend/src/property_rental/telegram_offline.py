"""What the relay needs to answer the bots (DL-210; DL-219: every message, app open or closed).

Owner (7 Nov 2026, card "Bot answers by itself"): the relay links a new tenant at night with the
scrambled check list, opens the Problem report form, answers a sent report at once and sends an
urgent one to the caretaker on shift; the app collects everything when it opens.

After each pull the job sends the relay, when anything changed:

* the bot's texts and keyboards in both languages, rendered here from ``telegram_texts`` so the
  relay says exactly what the office says;
* the scrambled check list: for each person a Lease link may name, a keyed hash (HMAC-SHA256 with
  the link check key, kept in the office and as the relay's ``LINK_CHECK_KEY`` secret) of the
  phone, the Unit key and one form of the name. No name or phone number leaves the office;
* each Unit's number and places (what the form shows), the problem types and shared places, and
  who gets an urgent alert (Telegram account numbers and shift times).

The relay compares the same hash of what the tenant shares and types (relay/src/offline.ts uses
the same phone, name and Unit rules as ``app.telegram_tenant_link``).

DL-213 (owner 11 Nov 2026): the Customer bot and the Staff bot answer by themselves too. The
Customer bot's body has its texts, the Unit Types, the FAQ the Owner approved for it and the
Property's distance from UTC (for the visit days); the Staff bot's body has its texts, the problem
types and shared places, and who gets an urgent alert. Neither holds a name or a phone number.

DL-219 (owner 11 Nov 2026: "all telegram bot has to reply immediately even app open or close"):
the relay answers every message, so the Tenant bot's body also has the FAQ the Owner approved,
and the access list (telegram_pull_job.push_form_data) has each linked person's My requests and
the repair waiting for Fixed or Not fixed. The job sends these every 10 seconds when they changed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from property_rental.telegram_customer_bot import (
    DAYS_SHOWN,
    FIRST_DAY,
    LAST_DAY,
    MAX_EMAIL,
    MAX_NAME,
    MAX_NOTE,
    MONTH_AHEAD_DAYS,
    MONTH_NAMES,
    MONTHS_SHOWN,
    WEEKDAYS,
)
from property_rental.telegram_relay_client import RelayClient, RelayError
from property_rental.telegram_store import TelegramStore
from property_rental.telegram_texts import (
    CHOICE_KEYBOARDS,
    MAX_CHOICE_CHARACTERS,
    MAX_CHOICES,
    TEXTS,
    keyboard_markup,
    text_fields,
)

CODE_CHARS: Final = 32
FINGERPRINT_FILE: Final = "telegram-offline.sha256"
FINGERPRINT_FILES: Final = {
    "TENANT": FINGERPRINT_FILE,
    "CUSTOMER": "telegram-offline-customer.sha256",
    "STAFF": "telegram-offline-staff.sha256",
}
# The relay's message names, each with the office's text and keyboard (telegram_tenant_bot).
MESSAGES: Final[dict[str, tuple[str, str | None]]] = {
    "welcome": ("tenant.welcome", "tenant.language"),
    "hello": ("tenant.hello", "tenant.start"),
    "menu": ("tenant.menu", "tenant.menu"),
    "ask_phone": ("tenant.ask_phone", "tenant.share_phone"),
    "ask_phone_again": ("tenant.ask_phone_again", "tenant.share_phone"),
    "ask_name": ("tenant.ask_name", "remove"),
    "ask_unit": ("tenant.ask_unit", None),
    "linked": ("tenant.linked_offline", "tenant.menu"),
    "no_match": ("tenant.no_match", "tenant.reject"),
    "blocked": ("tenant.blocked", "tenant.reject"),
    "code_bad": ("tenant.code_bad", "tenant.reject"),
    "link_first": ("tenant.link_first", "tenant.start"),
    "contact_ask": ("tenant.contact_ask", "tenant.back"),
    "contact_text_only": ("tenant.contact_text_only", "tenant.back"),
    "contact_saved": ("tenant.contact_saved", "tenant.start"),
    "contact_saved_linked": ("tenant.contact_saved", "tenant.menu"),
    "report_kind": ("tenant.report_kind", "tenant.report_kind"),
    # DL-219: FAQ, Fixed or Not fixed and My requests, answered by the relay too.
    "faq_none": ("tenant.faq_none", "tenant.menu"),
    "faq_list": ("tenant.faq_list", "tenant.faq"),
    "faq_answer": ("tenant.faq_answer", "tenant.faq"),
    "check_fixed": ("tenant.check_fixed", "tenant.menu"),
    "check_not_fixed": ("tenant.check_not_fixed", "tenant.menu"),
    "check_nothing": ("tenant.check_nothing", "tenant.menu"),
    "my_requests": ("tenant.my_requests", "tenant.menu"),
    "my_none": ("tenant.my_none", "tenant.menu"),
    "report_sent": ("tenant.report_sent_offline", None),
    "report_sent_urgent": ("tenant.report_sent_offline_urgent", None),
}
# The fields the relay fills in itself.
RELAY_FIELDS: Final = frozenset({"unit", "tries_left", "question", "answer", "number", "list"})
# The Customer bot's messages the relay answers with (DL-213), as telegram_customer_bot says
# them. A message whose keyboard starts with choices (FAQ questions, Unit Types, days, months)
# carries "choices": true; the relay puts those buttons above the fixed rows.
CUSTOMER_MESSAGES: Final[dict[str, tuple[str, str | None]]] = {
    "welcome": ("customer.welcome", "tenant.language"),
    "menu": ("customer.menu", "customer.menu"),
    "contact_phone": ("customer.contact_phone", "customer.share_phone"),
    "contact_ask": ("customer.contact_ask", "tenant.back"),
    "contact_text_only": ("tenant.contact_text_only", "tenant.back"),
    "contact_saved": ("customer.contact_saved", "customer.menu"),
    "faq_none": ("tenant.faq_none", "customer.menu"),
    "faq_list": ("tenant.faq_list", "customer.faq"),
    "faq_answer": ("tenant.faq_answer", "customer.faq"),
    "ask_how": ("customer.ask_how", "customer.how"),
    "ask_phone": ("customer.ask_phone", "customer.share_phone"),
    "phone_again": ("customer.phone_again", "customer.share_phone"),
    "ask_email": ("customer.ask_email", "tenant.back"),
    "email_again": ("customer.email_again", "tenant.back"),
    "ask_name": ("customer.ask_name", "tenant.back"),
    "ask_type": ("customer.ask_type", "customer.types"),
    "type_again": ("customer.type_again", "customer.types"),
    "ask_day": ("customer.ask_day", "customer.days"),
    "day_again": ("customer.day_again", "customer.days"),
    "ask_part": ("customer.ask_part", "customer.part"),
    "ask_move": ("customer.ask_move", "customer.months"),
    "ask_note": ("customer.ask_note", "customer.skip"),
    "check": ("customer.check", "customer.send"),
    "received": ("customer.inquiry_offline", "customer.menu"),
}
CUSTOMER_FIELDS: Final = frozenset(
    {"question", "answer", "name", "phone", "contact", "type", "visit", "move", "note"}
)
CUSTOMER_BUTTONS: Final = (
    "button.khmer",
    "button.english",
    "button.back_menu",
    "button.contact",
    "button.faq",
    "button.inquiry",
    "button.share_phone",
    "button.by_telegram",
    "button.by_email",
    "button.by_phone",
    "button.by_whatsapp",
    "button.morning",
    "button.afternoon",
    "button.skip",
    "button.later",
)
# Words the relay puts in the request to check, in each language.
CUSTOMER_WORDS: Final = (
    "button.by_telegram",
    "button.by_email",
    "button.by_phone",
    "button.by_whatsapp",
    "button.morning",
    "button.afternoon",
    "button.later",
    "customer.no_day",
)
# The Staff bot's messages the relay answers with (DL-213; staff read Khmer only).
STAFF_MESSAGES: Final[dict[str, tuple[str, str | None]]] = {
    "hello": ("staff.hello", "staff.open"),
    "ask_phone": ("staff.ask_phone", "staff.share_phone"),
    "waiting": ("staff.waiting", "remove"),
    "check": ("staff.check_offline", None),
    "form": ("staff.form_offline", None),
    "urgent": ("staff.report_offline_urgent", None),
}
STAFF_FIELDS: Final = frozenset({"name"})
BUTTONS: Final = (
    "button.khmer",
    "button.english",
    "button.link",
    "button.share_phone",
    "button.problem",
    "button.my_requests",
    "button.faq",
    "button.contact",
    "button.back_menu",
    "button.fixed",
    "button.not_fixed",
)
STAFF_ALERT: Final = "staff.urgent_offline"
LANGUAGES: Final = ("km", "en")


class LinkKeyError(ValueError):
    """The link check key file is missing or not 64 hex characters."""


def read_link_key(path: Path) -> str:
    try:
        key = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise LinkKeyError("link_key_unreadable") from error
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise LinkKeyError("link_key_not_set")
    return key


def link_code(key: str, phone: str, unit_key: str, name_form: str) -> str:
    """The relay's linkCode: HMAC-SHA256 of phone, Unit key and name form, first 32 hex."""
    message = f"{phone}\n{unit_key}\n{name_form}".encode()
    return hmac.new(bytes.fromhex(key), message, hashlib.sha256).hexdigest()[:CODE_CHARS]


def _messages(
    table: dict[str, tuple[str, str | None]], fields: frozenset[str], relay_host: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """Each message's text and keyboard in both languages, as the office would send them."""
    messages: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (code, keyboard) in table.items():
        extra = text_fields(code) - fields
        if extra:
            raise KeyError(f"{code} needs {sorted(extra)}")
        messages[name] = {}
        for language in LANGUAGES:
            said: dict[str, Any] = {"text": TEXTS[code][language]}
            choices = keyboard in CHOICE_KEYBOARDS
            markup = keyboard_markup(
                keyboard, language, relay_host, {"choices": []} if choices else None
            )
            if markup is not None:
                said["markup"] = markup
            if choices:
                said["choices"] = True
            messages[name][language] = said
    return messages


def _alert(data: dict[str, Any]) -> dict[str, Any]:
    alert = data.get("alert") or {}
    return {"always": alert.get("always") or [], "shifts": alert.get("shifts") or []}


def offline_texts(
    data: dict[str, Any], relay_host: str, faq: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The texts, buttons, types, places, alert list and FAQ (DL-219) the relay answers with."""
    return {
        "messages": _messages(MESSAGES, RELAY_FIELDS, relay_host),
        "buttons": {code: sorted(set(TEXTS[code].values())) for code in BUTTONS},
        "types": data.get("types") or {},
        "places": data.get("places") or {},
        "alert": _alert(data),
        "staff_urgent": TEXTS[STAFF_ALERT]["km"],
        "faq": _faq(faq or []),
    }


def _faq(faq: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The FAQ the Owner approved for a bot, as the relay shows it (both languages)."""
    return [
        {
            "number": entry.get("number"),
            **{
                f"{part}_{lang}": str(entry.get(f"{part}_{lang}") or "")
                for part in ("question", "answer")
                for lang in LANGUAGES
            },
        }
        for entry in faq
        if isinstance(entry, dict) and isinstance(entry.get("number"), int)
    ]


def customer_offline_texts(
    unit_types: list[dict[str, Any]],
    faq: list[dict[str, Any]],
    clock: dict[str, Any],
    relay_host: str,
) -> dict[str, Any]:
    """The Customer bot's body (DL-213): texts, buttons, words, Unit Types, FAQ and the clock."""
    offset = clock.get("utc_offset_minutes")
    return {
        "messages": _messages(CUSTOMER_MESSAGES, CUSTOMER_FIELDS, relay_host),
        "buttons": {code: sorted(set(TEXTS[code].values())) for code in CUSTOMER_BUTTONS},
        "words": {code: {lang: TEXTS[code][lang] for lang in LANGUAGES} for code in CUSTOMER_WORDS},
        "unit_types": [
            {
                "code": str(item.get("code") or ""),
                "name_en": str(item.get("name_en") or item.get("code") or ""),
                "name_km": str(item.get("name_km") or item.get("name_en") or ""),
            }
            for item in unit_types
            if isinstance(item, dict) and item.get("code")
        ],
        "faq": _faq(faq),
        "weekdays": {lang: list(WEEKDAYS[lang]) for lang in LANGUAGES},
        "months": {lang: list(MONTH_NAMES[lang]) for lang in LANGUAGES},
        "utc_offset_minutes": offset if isinstance(offset, int) else 0,
        "rules": {
            "first_day": FIRST_DAY,
            "last_day": LAST_DAY,
            "days_shown": DAYS_SHOWN,
            "months_shown": MONTHS_SHOWN,
            "month_ahead_days": MONTH_AHEAD_DAYS,
            "max_name": MAX_NAME,
            "max_email": MAX_EMAIL,
            "max_note": MAX_NOTE,
            "max_choices": MAX_CHOICES,
            "max_choice_chars": MAX_CHOICE_CHARACTERS,
        },
    }


def staff_offline_texts(data: dict[str, Any], relay_host: str) -> dict[str, Any]:
    """The Staff bot's body (DL-213): texts, the problem types and places, the alert list."""
    return {
        "messages": _messages(STAFF_MESSAGES, STAFF_FIELDS, relay_host),
        "buttons": {"button.share_phone": sorted(set(TEXTS["button.share_phone"].values()))},
        "types": data.get("types") or {},
        "places": data.get("places") or {},
        "alert": _alert(data),
        "staff_urgent": TEXTS[STAFF_ALERT]["km"],
    }


def offline_links(
    data: dict[str, Any], key: str | None, start_codes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The scrambled check list: hash -> Unit, and each Unit's number and places. With the QR
    codes (DL-214): the SHA-256 of each unused code -> [Unit, the second it stops working]."""
    units: list[dict[str, Any]] = []
    where: dict[str, int] = {}
    codes: dict[str, int] = {}
    starts: dict[str, list[int]] = {}
    for code in start_codes or []:
        unit_id = str(code.get("unit_id"))
        code_hash = code.get("code_hash")
        expires = code.get("expires_at")
        if not isinstance(code_hash, str) or not isinstance(expires, int):
            continue
        if unit_id not in where:
            where[unit_id] = len(units)
            units.append({"unit": code.get("unit"), "places": code.get("places") or []})
        starts[code_hash] = [where[unit_id], expires]
    known = data.get("units") or {}
    # Without the link check key the relay links nobody by name, only by a QR code.
    people = (data.get("people") or []) if key else []
    for person in people:
        unit_id = str(person.get("unit_id"))
        unit = known.get(unit_id)
        if not isinstance(unit, dict) or not unit.get("unit_key"):
            continue
        if unit_id not in where:
            where[unit_id] = len(units)
            units.append({"unit": unit.get("unit"), "places": unit.get("places") or []})
        for phone in person.get("phones") or []:
            for name_form in person.get("names") or []:
                if isinstance(phone, str) and isinstance(name_form, str) and len(name_form) > 2:
                    hashed = link_code(str(key), phone, str(unit["unit_key"]), name_form)
                    codes[hashed] = where[unit_id]
    linked: dict[str, Any] = {"units": units, "codes": codes}
    if starts:
        linked["start_codes"] = starts
    return linked


def _send_when_changed(
    client: RelayClient,
    bot: str,
    texts: dict[str, Any],
    links: dict[str, Any],
    status_directory: Path,
    log: Callable[[str], None],
) -> bool:
    fingerprint = hashlib.sha256(
        json.dumps([texts, links], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    marker = status_directory / FINGERPRINT_FILES[bot]
    try:
        if marker.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        client.set_offline(bot, texts, links)
    except RelayError as error:
        log(f"telegram_pull:offline_not_sent:{bot.lower()}:{error.code}")
        return False
    status_directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(fingerprint + "\n", encoding="utf-8")
    return True


def push_offline(
    *,
    client: RelayClient,
    store: TelegramStore,
    relay_host: str,
    link_key_file: Path | None,
    status_directory: Path,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> bool:
    """Send the relay each bot's offline body when it changed; True when any was sent. Without a
    link check key the relay still answers, but links nobody on its own."""
    key: str | None = None
    if link_key_file is not None:
        try:
            key = read_link_key(link_key_file)
        except LinkKeyError as error:
            log(f"telegram_pull:offline_{error}")
    data = store.tenant_offline_data()
    links = offline_links(data, key, store.link_codes_offline())
    texts = offline_texts(data, relay_host, store.faq_for_bot("TENANT"))
    sent = _send_when_changed(client, "TENANT", texts, links, status_directory, log)
    customer = customer_offline_texts(
        store.customer_choices(0).get("unit_types") or [],
        store.faq_for_bot("CUSTOMER"),
        store.offline_clock(),
        relay_host,
    )
    sent = _send_when_changed(client, "CUSTOMER", customer, {}, status_directory, log) or sent
    staff = staff_offline_texts(data, relay_host)
    return _send_when_changed(client, "STAFF", staff, {}, status_directory, log) or sent
