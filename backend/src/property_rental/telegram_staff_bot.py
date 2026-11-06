"""The Staff bot (step 4a, DL-174): staff join, check in and out, and the caretaker's card scan.

Owner rules: staff see Khmer only. A new person taps Start and shares their own Telegram phone;
the Owner or a Manager approves them in HR > Staff requests and gives the report roles (24 Oct
2026), and the person hears the answer from this bot (migration 20270620_331). A linked person
gets the Reports button, which opens the Staff forms (a Mini App on the relay, /app/staff).

Check in and Check out (3 Nov 2026, HR plan PR-HR-060 to 068): the form asks for the phone's
Location first, then scans the place QR; the HR rules decide (too early, late, needs check), and
this bot answers with the time. A caretaker scans the card of a person with no phone, with a
reason and a half-body photo; the photo is kept in the HR files folder, not with the Telegram
photos, so the HR rule "card photos kept 90 days" can remove it.

Report a problem and Close job (step 4b, DL-175; Problem report Part B, 3 Nov 2026): every
linked person reports what is wrong on the walk-round (a photo and a text or voice note), and the
Technician closes a planned repair with the after photo and the cost. The database saves them in
the one Problem reports list; an urgent report reaches the caretaker on shift and the Authorizers
from the database itself.

Utility reading and Meter check request (step 4c, DL-176; owner rule 22 Oct 2026): the meter
reader types each Unit's Electricity and Water reading with no photo; the readings wait until a
Manager confirms them in Utilities (asking to read again reaches the reader in this bot). The
flag beside a Unit asks the Technical team to check that meter (a Unit Problem).

Daily checklists (step 4d, DL-177; staff checklists 24-25 Oct 2026): the Cleaning, Caretaker
shift and Technical checks, and each patrol round of a caretaker's shift. The 18:00 summary for
the Authorizers comes from the database (the pull job asks for it every run).

Unit Check and Maintenance check (step 4e, DL-178; staff forms mock-up v14): the Technician
marks each area of a Unit Good, Broken or Missing (each finding becomes a Unit Problem with its
photos), and checks a planned visit (how staff entered, the cause, fixed at once when urgent),
which moves the report to Checked. Who pays is decided by the Manager in the app.

The forms reach the office through the relay and the pull job, so the answer comes in the chat
within about a minute.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Final

from property_rental.telegram_phone import normalize_phone
from property_rental.telegram_store import StaffBotUnavailable, TelegramStore
from property_rental.telegram_texts import TEXTS

BOT: Final = "STAFF"
LANGUAGE: Final = "km"
MAX_NAME: Final = 120
MAX_REASON_TEXT: Final = 300
MAX_QR: Final = 200
CARD_REASONS: Final = frozenset({"NO_PHONE", "PHONE_BROKEN", "PHONE_LOST", "PHONE_STOLEN", "OTHER"})
LOCATION_STATES: Final = frozenset({"OK", "NOT_FOUND", "OFF"})
PHOTO_TYPES: Final = {"image/jpeg": "jpg", "image/png": "png"}
CARD_PHOTOS: Final = "card-photos"
REFUSED_PREFIX: Final = "check_refused_"
SAVED_FORMS: Final = frozenset(
    {
        "REPORT",
        "CLOSE",
        "METER",
        "METER_CHECK",
        "CHECKLIST",
        "PATROL",
        "UNIT_CHECK",
        "MAINT_CHECK",
    }
)
FORM_TYPES: Final = SAVED_FORMS | {"CHECK", "CARD"}


def _message(plain: dict[str, Any]) -> dict[str, Any] | None:
    payload = plain.get("payload")
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    return message


def _say(code: str, keyboard: str | None = None, **details: object) -> dict[str, Any]:
    message: dict[str, Any] = {"text_code": code, "details": details}
    if keyboard is not None:
        message["keyboard"] = keyboard
    return message


def _sender_name(message: dict[str, Any]) -> str:
    sender = message.get("from")
    parts = [sender.get("first_name"), sender.get("last_name")] if isinstance(sender, dict) else []
    name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    return name[:MAX_NAME]


def _own_phone(message: dict[str, Any]) -> str | None:
    contact = message.get("contact")
    sender = message.get("from")
    if not isinstance(contact, dict) or not isinstance(sender, dict):
        return None
    if contact.get("user_id") != sender.get("id"):
        return None
    number = contact.get("phone_number")
    return normalize_phone(number) if isinstance(number, str) else None


def handle_staff_update(
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
    if isinstance(text, str) and text.strip().lower() in {"ping", "/ping"}:
        return  # the shared base answers the test message

    def reply(*messages: dict[str, Any]) -> None:
        store.bot_reply(BOT, user, chat, "menu", None, LANGUAGE, list(messages))

    try:
        who = store.staff_who(user)
        if who.get("linked") is True:
            reply(_say("staff.hello", "staff.open", name=_name(who)))
            return
        phone = _own_phone(message)
        if phone is not None:
            asked = store.staff_join(user, _sender_name(message) or str(user), phone)
            if asked.get("state") == "LINKED":
                reply(_say("staff.hello", "staff.open", name=_name(store.staff_who(user))))
            else:
                reply(_say("staff.waiting", "remove"))
            return
    except StaffBotUnavailable:
        reply(_say("staff.not_ready", "remove"))
        return
    if who.get("waiting") is True:
        reply(_say("staff.waiting", "remove"))
        return
    reply(_say("staff.ask_phone", "staff.share_phone"))


def _name(who: dict[str, Any]) -> str:
    for key in ("name_km", "name_en"):
        value = who.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _scan_from(form: dict[str, Any]) -> dict[str, Any]:
    """Only the fields the HR rules read, each checked for its kind."""
    mode = form.get("mode")
    qr = form.get("qr")
    location = form.get("location")
    status = location.get("status") if isinstance(location, dict) else None
    place: dict[str, Any] = {"status": status if status in LOCATION_STATES else "NOT_FOUND"}
    if place["status"] == "OK" and isinstance(location, dict):
        for key in ("latitude", "longitude"):
            value = location.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                place[key] = float(value)
    scan: dict[str, Any] = {
        "mode": mode if mode in {"IN", "OUT"} else "",
        "qr": qr[:MAX_QR] if isinstance(qr, str) else "",
        "location": place,
    }
    phone_time = form.get("phone_time")
    if isinstance(phone_time, str) and len(phone_time) <= 40:
        scan["phone_time"] = phone_time
    return scan


def _answer(result: dict[str, Any], *, card: bool) -> dict[str, Any]:
    if result.get("ok") is True:
        time = str(result.get("time") or "")
        if card:
            code = "staff.card_out_ok" if result.get("direction") == "OUT" else "staff.card_in_ok"
            return _say(code, name=_name(result), time=time)
        key = f"staff.{result.get('reply_key')}"
        details: dict[str, object] = {"time": time}
        if key == "staff.check_in_ok":
            details["place"] = str(result.get("place_km") or result.get("place_en") or "")
        if key == "staff.check_in_late":
            details["minutes"] = int(result.get("late_minutes") or 0)
        return {"text_code": key if key in TEXTS else "staff.check_out_ok", "details": details}
    reply_key = str(result.get("reply_key") or "")
    key = f"staff.{reply_key}"
    if key == "staff.check_refused_too_early":
        return _say(key, starts=str(result.get("starts") or ""))
    known = key in TEXTS and reply_key.startswith(REFUSED_PREFIX)
    return _say(key if known else "staff.refused_other")


def handle_staff_form(
    bot: str, plain: dict[str, Any], saved: dict[str, Any], store: TelegramStore
) -> None:
    """A Staff form (check in or out, card scan, Report a problem, Close job): save, answer."""
    if bot != BOT:
        return
    user = plain.get("telegram_user_id")
    chat = plain.get("chat_id")
    payload = plain.get("payload")
    office = plain.get("office")
    if not isinstance(user, int) or not isinstance(chat, int) or user <= 0:
        return
    if not isinstance(payload, dict) or not isinstance(office, dict):
        return
    form = payload.get("form")
    if not isinstance(form, dict) or form.get("type") not in FORM_TYPES:
        return
    at = str(office.get("received_at") or "")

    def reply(message: dict[str, Any]) -> None:
        store.bot_reply(BOT, user, chat, None, None, LANGUAGE, [message])

    if form["type"] in SAVED_FORMS:
        inbound = saved.get("inbound_id")
        media = saved.get("media_ids")
        if not isinstance(inbound, str):
            return
        files = [str(media_id) for media_id in media] if isinstance(media, list) else []
        if form["type"] == "REPORT":
            result = store.staff_problem_report(inbound, form, files)
            message = _report_answer(result)
        elif form["type"] == "CLOSE":
            result = store.staff_close_job(inbound, form, files)
            message = _close_answer(result)
        elif form["type"] == "METER":
            result = store.staff_meter_readings(inbound, form, files)
            message = _meter_answer(result)
        elif form["type"] == "CHECKLIST":
            result = store.staff_checklist(inbound, form, files)
            message = _checklist_answer(result)
        elif form["type"] == "PATROL":
            result = store.staff_patrol(inbound, form, files)
            message = _patrol_answer(result)
        elif form["type"] == "UNIT_CHECK":
            result = store.staff_unit_check(inbound, form, files)
            message = _unit_check_answer(result)
        elif form["type"] == "MAINT_CHECK":
            result = store.staff_maintenance_check(inbound, form, files)
            message = _maintenance_answer(result)
        else:
            result = store.staff_meter_check(inbound, form, files)
            message = _meter_check_answer(result)
        if result.get("repeated") is not True:
            reply(message)
        return
    try:
        if form["type"] == "CHECK":
            reply(_answer(store.staff_check(user, _scan_from(form), at), card=False))
            return
        reply(_card(user, form, at, office, store))
    except StaffBotUnavailable:
        reply(_say("staff.not_ready"))


def _report_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Report a problem: the new number, urgent or joined to the open report."""
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome != "ADDED":
        return _say("staff.report_invalid")
    number = str(result.get("report_number") or "")
    if result.get("joined_to"):
        return _say("staff.report_joined", number=number, main=str(result["joined_to"]))
    if result.get("urgent") is True:
        return _say("staff.report_urgent", number=number)
    return _say("staff.report_saved", number=number)


def _close_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Close job: done with or without a cost, or why it was not closed."""
    outcome = result.get("result")
    number = str(result.get("report_number") or "")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_TECHNICIAN":
        return _say("staff.close_not_technician")
    if outcome == "NOT_OPEN":
        return _say("staff.close_not_open", number=number)
    if outcome == "COST_CHECKED":
        return _say("staff.close_cost_checked", number=number)
    if outcome != "DONE":
        return _say("staff.close_invalid")
    cents = result.get("total_usd_cents")
    if result.get("cost") == "PAID" and isinstance(cents, int) and cents > 0:
        return _say(
            "staff.close_done_cost", number=number, amount=f"{cents // 100}.{cents % 100:02d}"
        )
    return _say("staff.close_done", number=number)


def _meter_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Utility reading: how many readings wait for the Manager, and how many to look at."""
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_METER_READER":
        return _say("staff.meter_not_reader")
    count = result.get("count")
    if outcome != "SENT" or not isinstance(count, int):
        return _say("staff.meter_invalid")
    flagged = result.get("flagged")
    if isinstance(flagged, int) and flagged > 0:
        return _say("staff.meter_sent_flagged", count=str(count), flagged=str(flagged))
    return _say("staff.meter_sent", count=str(count))


def _meter_check_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Meter check request: the Unit Problem number for the Technical team."""
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome != "ADDED":
        return _say("staff.meter_check_invalid")
    return _say("staff.meter_check_saved", number=str(result.get("report_number") or ""))


def _not_role(result: dict[str, Any]) -> dict[str, Any]:
    kind = result.get("kind")
    if kind == "CLEANING":
        return _say("staff.checklist_not_cleaner")
    if kind == "CARETAKER":
        return _say("staff.checklist_not_caretaker")
    return _say("staff.checklist_not_technician")


def _checklist_answer(result: dict[str, Any]) -> dict[str, Any]:
    """A daily checklist: how many tasks were done, and how many were not."""
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_ROLE":
        return _not_role(result)
    if outcome == "NO_SHIFT":
        return _say("staff.checklist_no_shift")
    if outcome == "NOTHING_DUE":
        return _say("staff.checklist_nothing_due")
    done, problems = result.get("done"), result.get("problems")
    if outcome != "SENT" or not isinstance(done, int) or not isinstance(problems, int):
        return _say("staff.checklist_invalid")
    total = str(done + problems)
    if problems > 0:
        return _say(
            "staff.checklist_sent_problems", done=str(done), total=total, problems=str(problems)
        )
    return _say("staff.checklist_sent", done=str(done), total=total)


def _patrol_answer(result: dict[str, Any]) -> dict[str, Any]:
    """A patrol round: saved with the real time, or why not."""
    outcome = result.get("result")
    round_time = str(result.get("round") or "")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_ROLE":
        return _say("staff.checklist_not_caretaker")
    if outcome == "NO_SHIFT":
        return _say("staff.checklist_no_shift")
    if outcome == "TOO_EARLY":
        return _say("staff.patrol_too_early", round=round_time)
    if outcome == "ROUND_DONE":
        return _say("staff.patrol_done_before", round=round_time, at=str(result.get("at") or ""))
    if outcome != "SENT":
        return _say("staff.patrol_invalid")
    return _say("staff.patrol_sent", round=round_time, at=str(result.get("at") or ""))


def _unit_check_answer(result: dict[str, Any]) -> dict[str, Any]:
    """A Unit Check: all good, or the Unit Problem numbers of what was found."""
    outcome = result.get("result")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_ROLE":
        return _say("staff.tech_only")
    numbers = result.get("numbers")
    if outcome != "SENT" or not isinstance(numbers, list):
        return _say("staff.unit_check_invalid")
    if not numbers:
        return _say("staff.unit_check_good")
    return _say(
        "staff.unit_check_findings",
        count=str(len(numbers)),
        numbers=", ".join(str(number) for number in numbers),
    )


def _maintenance_answer(result: dict[str, Any]) -> dict[str, Any]:
    """A Maintenance check: the visit is checked (and fixed), or why not."""
    outcome = result.get("result")
    number = str(result.get("report_number") or "")
    if outcome == "NOT_LINKED":
        return _say("staff.check_refused_not_linked")
    if outcome == "NOT_ROLE":
        return _say("staff.tech_only")
    if outcome == "NOT_PLANNED":
        return _say("staff.maint_not_planned", number=number)
    if outcome != "CHECKED":
        return _say("staff.maint_invalid")
    if result.get("fixed") is True:
        return _say("staff.maint_fixed", number=number)
    return _say("staff.maint_checked", number=number)


def _card(
    user: int, form: dict[str, Any], at: str, office: dict[str, Any], store: TelegramStore
) -> dict[str, Any]:
    folder = office.get("hr_files")
    held = office.get("held_media")
    photo = held[0] if isinstance(held, list) and held and isinstance(held[0], dict) else None
    if not isinstance(folder, str) or not folder:
        return _say("staff.card_not_ready")
    mode = form.get("mode")
    card = form.get("card")
    reason = form.get("reason")
    reason_text = form.get("reason_text")
    scan: dict[str, Any] = {
        "mode": mode if mode in {"IN", "OUT"} else "",
        "card": card[:MAX_QR] if isinstance(card, str) else "",
        "reason": reason if reason in CARD_REASONS else "",
        "reason_text": reason_text[:MAX_REASON_TEXT] if isinstance(reason_text, str) else "",
    }
    made: Path | None = None
    if photo is not None and isinstance(photo.get("data"), bytes):
        data: bytes = photo["data"]
        content_type = str(photo.get("content_type"))
        if content_type in PHOTO_TYPES:
            sha256 = hashlib.sha256(data).hexdigest()
            key = f"{CARD_PHOTOS}/{sha256}.{PHOTO_TYPES[content_type]}"
            made = _keep(Path(folder), key, data)
            scan["photo"] = {
                "sha256": sha256,
                "byte_size": len(data),
                "media_type": content_type,
                "storage_key": key,
            }
    result = store.staff_card(user, scan, at)
    if result.get("ok") is not True and made is not None:
        # A refused scan keeps no photo row (HR contract), so the file goes too.
        made.unlink(missing_ok=True)
    return _answer(result, card=True)


def _keep(root: Path, key: str, data: bytes) -> Path | None:
    """Write the photo; the path when this call made the file, None when it was already there."""
    target = (root / key).resolve()
    if root.resolve() not in target.parents:
        raise ValueError("the photo key leaves the HR files folder")
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    partial = target.parent / f".{target.name}.partial"
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def remove_old_card_photos(store: TelegramStore, folder: Path | None) -> int:
    """The HR rule's old card photos: delete each file, then record it (PR-HR-067)."""
    if folder is None:
        return 0
    removed = 0
    root = folder.resolve()
    for due in store.staff_photos_due():
        key, file_id = due.get("storage_key"), due.get("file_id")
        if not isinstance(key, str) or not isinstance(file_id, str):
            continue
        target = (root / key).resolve()
        if root not in target.parents:
            continue
        target.unlink(missing_ok=True)
        store.staff_photo_removed(file_id)
        removed += 1
    return removed
