"""What the relay needs to answer the Tenant bot while the office app is closed (DL-210).

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
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from property_rental.telegram_relay_client import RelayClient, RelayError
from property_rental.telegram_store import TelegramStore
from property_rental.telegram_texts import TEXTS, keyboard_markup, text_fields

CODE_CHARS: Final = 32
FINGERPRINT_FILE: Final = "telegram-offline.sha256"
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
    "link_first": ("tenant.link_first", "tenant.start"),
    "contact_ask": ("tenant.contact_ask", "tenant.back"),
    "contact_text_only": ("tenant.contact_text_only", "tenant.back"),
    "contact_saved": ("tenant.contact_saved", "tenant.start"),
    "contact_saved_linked": ("tenant.contact_saved", "tenant.menu"),
    "report_kind": ("tenant.report_kind", "tenant.report_kind"),
    "office_away": ("tenant.office_away", "tenant.menu"),
    "report_sent": ("tenant.report_sent_offline", None),
    "report_sent_urgent": ("tenant.report_sent_offline_urgent", None),
}
# The fields the relay fills in itself.
RELAY_FIELDS: Final = frozenset({"unit", "tries_left"})
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


def offline_texts(data: dict[str, Any], relay_host: str) -> dict[str, Any]:
    """The texts, buttons, types, places and alert list the relay answers with."""
    messages: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (code, keyboard) in MESSAGES.items():
        extra = text_fields(code) - RELAY_FIELDS
        if extra:
            raise KeyError(f"{code} needs {sorted(extra)}")
        messages[name] = {}
        for language in LANGUAGES:
            said: dict[str, Any] = {"text": TEXTS[code][language]}
            markup = keyboard_markup(keyboard, language, relay_host)
            if markup is not None:
                said["markup"] = markup
            messages[name][language] = said
    alert = data.get("alert") or {}
    return {
        "messages": messages,
        "buttons": {code: sorted(set(TEXTS[code].values())) for code in BUTTONS},
        "types": data.get("types") or {},
        "places": data.get("places") or {},
        "alert": {"always": alert.get("always") or [], "shifts": alert.get("shifts") or []},
        "staff_urgent": TEXTS[STAFF_ALERT]["km"],
    }


def offline_links(data: dict[str, Any], key: str) -> dict[str, Any]:
    """The scrambled check list: hash -> Unit, and each Unit's number and places."""
    units: list[dict[str, Any]] = []
    where: dict[str, int] = {}
    codes: dict[str, int] = {}
    known = data.get("units") or {}
    for person in data.get("people") or []:
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
                    codes[link_code(key, phone, str(unit["unit_key"]), name_form)] = where[unit_id]
    return {"units": units, "codes": codes}


def push_offline(
    *,
    client: RelayClient,
    store: TelegramStore,
    relay_host: str,
    link_key_file: Path | None,
    status_directory: Path,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> bool:
    """Send the relay the Tenant bot's offline body when it changed; True when sent. Without a
    link check key the relay still answers, but links nobody on its own."""
    key: str | None = None
    if link_key_file is not None:
        try:
            key = read_link_key(link_key_file)
        except LinkKeyError as error:
            log(f"telegram_pull:offline_{error}")
    data = store.tenant_offline_data()
    texts = offline_texts(data, relay_host)
    links = offline_links(data, key) if key else {"units": [], "codes": {}}
    fingerprint = hashlib.sha256(
        json.dumps([texts, links], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    marker = status_directory / FINGERPRINT_FILE
    try:
        if marker.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        client.set_offline("TENANT", texts, links)
    except RelayError as error:
        log(f"telegram_pull:offline_not_sent:{error.code}")
        return False
    status_directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(fingerprint + "\n", encoding="utf-8")
    return True
