"""The pull job (bots plan, "The office app side"): every minute, ask the relay for what waits,
open each item with the office key, save it once, then confirm so the relay deletes it.

Photos and voice notes come with their item: each is fetched, opened, checked against the
fingerprint the relay took before sealing, and kept once on the office disk by that
fingerprint (inside the encrypted backups). An item that cannot be opened or saved is not
confirmed: it stays in the relay, the run counts it as refused, and after 7 days the relay
removes it and the health page shows a warning.

After an item is saved, the handler for its bot and kind runs: "ping" to any bot answers that the
connection works (the owner's setup test); the Tenant bot answers chat messages and saves Problem
report forms (steps 2a and 2b). After each pull the job sends the relay the Tenant bot access list
and form choices when they changed. The Staff bot (step 4a) joins staff and records check-in and
card scans with the HR service actor; a card scan's photo goes to the HR files folder, not with
the Telegram photos, so the HR rule can remove it after 90 days.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from property_rental.operations_config import (
    BOT_CODES,
    OperationsConfigError,
    load_operations_config,
)
from property_rental.operations_status import format_time, utc_now, write_status
from property_rental.telegram_customer_bot import handle_customer_update
from property_rental.telegram_phone import normalize_phone
from property_rental.telegram_relay_client import RelayClient, RelayError, RelayItem, read_pull_key
from property_rental.telegram_seal import SealError, load_office_private_key, open_sealed
from property_rental.telegram_staff_bot import (
    handle_staff_form,
    handle_staff_update,
    remove_old_card_photos,
)
from property_rental.telegram_store import PostgresTelegramStore, TelegramStore
from property_rental.telegram_tenant_bot import handle_tenant_form, handle_tenant_update

MEDIA_TYPES: Final = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp4",
        "audio/webm",
    }
)
FORM_DATA_FILES: Final = {
    "TENANT": "telegram-form-data.sha256",
    "STAFF": "telegram-staff-form-data.sha256",
}
MAX_MEDIA_BYTES: Final = 20 * 1024 * 1024
BOT_NAMES: Final = {
    "CUSTOMER": "CHETANA Residence",
    "TENANT": "CHETANA Residence support",
    "STAFF": "CHETANA staff",
}


class ItemRefused(ValueError):
    """The item cannot be saved; `code` is a fixed word."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


Handler = Callable[[str, dict[str, Any], dict[str, Any], TelegramStore], None]


def _ping(bot: str, plain: dict[str, Any], saved: dict[str, Any], store: TelegramStore) -> None:
    message = plain.get("payload", {}).get("message")
    if not isinstance(message, dict):
        return
    text = message.get("text")
    chat = plain.get("chat_id")
    if (
        isinstance(text, str)
        and text.strip().lower() in {"ping", "/ping"}
        and isinstance(chat, int)
    ):
        answer: dict[str, Any] = {
            "bot": bot,
            "chat_id": chat,
            "text_code": "base.ping_reply",
            "language": "km" if plain.get("language_code") == "km" else "en",
            "details": {"bot": BOT_NAMES[bot]},
        }
        inbound = saved.get("inbound_id")
        if isinstance(inbound, str) and inbound:
            # One answer per saved message, kept by the outbox itself (DL-202 (B)).
            answer["dedupe_key"] = f"ping:{inbound}"
        store.queue(answer)


HANDLERS: Final[dict[str, list[Handler]]] = {
    "update": [_ping, handle_tenant_update, handle_customer_update, handle_staff_update],
    "form": [handle_tenant_form, handle_staff_form],
}


def push_form_data(
    *,
    client: RelayClient,
    store: TelegramStore,
    status_directory: Path,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> bool:
    """Send the relay who may open the Tenant and Staff bot forms and what the forms show. Only
    a change is sent (the relay's free plan counts writes); a failed send is tried again next
    minute. True when anything was sent."""
    sent = False
    for bot, read in (("TENANT", store.tenant_form_data), ("STAFF", store.staff_form_data)):
        data = read()
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        marker = status_directory / FORM_DATA_FILES[bot]
        try:
            if marker.read_text(encoding="utf-8").strip() == fingerprint:
                continue
        except OSError:
            pass
        users = data.get("users")
        choices = data.get("choices")
        if not isinstance(users, list) or not isinstance(choices, dict):
            log(f"telegram_pull:form_data_invalid:{bot}")
            continue
        try:
            client.set_access(bot, users)
            client.set_choices(bot, choices)
        except RelayError as error:
            log(f"telegram_pull:form_data_not_sent:{bot}:{error.code}")
            continue
        status_directory.mkdir(parents=True, exist_ok=True)
        marker.write_text(fingerprint + "\n", encoding="utf-8")
        sent = True
    return sent


def store_media(directory: Path, sha256: str, data: bytes) -> str:
    """Keep one file by its fingerprint; a file already there is the same file."""
    relative = f"{sha256[:2]}/{sha256}"
    target = directory / relative
    if target.exists():
        return relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    partial = target.parent / f".{sha256}.partial"
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
    return relative


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _phone_from(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    contact = message.get("contact")
    sender = message.get("from")
    if not isinstance(contact, dict) or not isinstance(sender, dict):
        return None
    # Only the person's own number counts (Telegram's "share my phone"), never a forwarded one.
    if contact.get("user_id") != sender.get("id"):
        return None
    number = contact.get("phone_number")
    return normalize_phone(number) if isinstance(number, str) else None


@dataclass
class PullResult:
    received: int = 0
    saved: int = 0
    repeated: int = 0
    refused: int = 0
    confirmed: int = 0
    refused_codes: list[str] = field(default_factory=list)


def save_item(
    item: RelayItem,
    *,
    client: RelayClient,
    key: Any,
    store: TelegramStore,
    media_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if item.bot not in BOT_CODES:
        raise ItemRefused("unknown_bot")
    try:
        plain = json.loads(open_sealed(key, item.sealed, item.item_id))
    except SealError as error:
        raise ItemRefused("cannot_open") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ItemRefused("not_json") from error
    if not isinstance(plain, dict) or plain.get("v") != 1:
        raise ItemRefused("unknown_format")
    payload = plain.get("payload")
    if not isinstance(payload, dict):
        raise ItemRefused("no_payload")
    described = plain.get("media", [])
    if not isinstance(described, list) or [
        m.get("id") for m in described if isinstance(m, dict)
    ] != list(item.media_ids):
        raise ItemRefused("media_list_differs")
    media: list[dict[str, Any]] = []
    # A caretaker's card scan photo is held for the HR files folder (90-day rule), not kept
    # with the Telegram photos.
    form = payload.get("form")
    hold = item.bot == "STAFF" and isinstance(form, dict) and form.get("type") == "CARD"
    held: list[dict[str, Any]] = []
    for entry in described:
        content_type, sha256, size = (
            entry.get("content_type"),
            entry.get("sha256"),
            entry.get("size"),
        )
        if content_type not in MEDIA_TYPES or not isinstance(sha256, str) or _int(size) is None:
            raise ItemRefused("media_not_allowed")
        if not 0 < size <= MAX_MEDIA_BYTES:
            raise ItemRefused("media_too_big")
        try:
            data = open_sealed(key, client.media(entry["id"]), entry["id"])
        except SealError as error:
            raise ItemRefused("media_cannot_open") from error
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
            raise ItemRefused("media_fingerprint_differs")
        if hold:
            held.append({"content_type": content_type, "sha256": sha256, "data": data})
            continue
        media.append(
            {
                "sha256": sha256,
                "content_type": content_type,
                "size_bytes": size,
                "storage_path": store_media(media_directory, sha256, data),
                "width": _int(entry.get("width")),
                "height": _int(entry.get("height")),
                "duration_seconds": _int(entry.get("duration")),
                "telegram_file_unique_id": entry.get("file_unique_id"),
            }
        )
    language = plain.get("language_code")
    record = {
        "relay_item_id": item.item_id,
        "bot": item.bot,
        "kind": item.kind,
        "received_at": item.received_at,
        "update_id": _int(plain.get("update_id")),
        "telegram_user_id": _int(plain.get("telegram_user_id")),
        "chat_id": _int(plain.get("chat_id")),
        "account": {
            "language": language if language in {"km", "en"} else None,
            "phone": _phone_from(payload),
        },
        "summary": {"kind": item.kind, "media": len(media), "held_media": len(held)},
        "payload": _without_codes(payload) if item.bot == "STAFF" else payload,
        "media": media,
    }
    # What the office adds for the handlers; never saved.
    plain["office"] = {"received_at": item.received_at, "held_media": held}
    return plain, store.record_item(record)


def _without_codes(payload: dict[str, Any]) -> dict[str, Any]:
    """A Staff form as kept: the scanned QR and card texts stay out (HR keeps only their hash)."""
    form = payload.get("form")
    if not isinstance(form, dict):
        return payload
    kept = {key: value for key, value in form.items() if key not in {"qr", "card"}}
    return payload | {"form": kept}


def run_pull(
    *,
    client: RelayClient,
    key: Any,
    store: TelegramStore,
    media_directory: Path,
    hr_files_directory: Path | None = None,
    limit: int = 50,
    now: Callable[[], datetime] = utc_now,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> PullResult:
    started = now()
    result = PullResult()
    try:
        batch = client.pull(limit)
    except RelayError as error:
        store.record_run(
            {
                "started_at": format_time(started),
                "finished_at": format_time(now()),
                "outcome": "FAILED",
                "error_code": error.code,
            }
        )
        raise
    result.received = len(batch.items)
    done: list[str] = []
    for item in batch.items:
        try:
            plain, saved = save_item(
                item, client=client, key=key, store=store, media_directory=media_directory
            )
        except ItemRefused as refused:
            result.refused += 1
            result.refused_codes.append(refused.code)
            log(f"telegram_pull:refused:{refused.code}")
            continue
        except RelayError as error:
            result.refused += 1
            result.refused_codes.append(error.code)
            log(f"telegram_pull:refused:{error.code}")
            continue
        done.append(item.item_id)
        if saved.get("saved") is True:
            result.saved += 1
            plain["office"]["hr_files"] = str(hr_files_directory) if hr_files_directory else ""
            for handler in HANDLERS.get(item.kind, []):
                handler(item.bot, plain, saved, store)
        else:
            result.repeated += 1
    error_code: str | None = None
    try:
        result.confirmed = client.confirm(done)
    except RelayError as error:
        # The items are saved; the next pull gets them again and saves each once.
        error_code = error.code
    store.record_run(
        {
            "started_at": format_time(started),
            "finished_at": format_time(now()),
            "outcome": "FAILED" if error_code else "OK",
            "error_code": error_code,
            "items_received": result.received,
            "items_saved": result.saved,
            "items_repeated": result.repeated,
            "items_refused": result.refused,
            "relay_waiting": batch.waiting,
            "relay_oldest_at": batch.oldest_at,
            "relay_dropped": batch.dropped,
        }
    )
    if error_code:
        raise RelayError(error_code)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull what waits in the Telegram relay")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    # The HR service actor the Staff bot calls the HR functions with; empty while not set up.
    parser.add_argument("--service-actor-id", default="", type=str)
    args = parser.parse_args(argv)
    try:
        service_actor = UUID(args.service_actor_id) if args.service_actor_id else None
    except ValueError:
        parser.error("--service-actor-id is not a UUID")
    hr_folder = os.environ.get("APP_HR_FILES_DIRECTORY")
    hr_files = Path(hr_folder) if hr_folder else None
    database_url = os.environ.get("APP_DATABASE_URL")
    if not database_url:
        parser.error("APP_DATABASE_URL is required")
    try:
        config = load_operations_config(args.config)
    except OperationsConfigError as error:
        print(f"telegram_pull:config:{error}", file=sys.stderr, flush=True)
        return 2
    bots = config.telegram_bots
    if bots is None or not bots.enabled:
        print("telegram_pull:not_enabled", flush=True)
        return 0
    store = PostgresTelegramStore(
        database_url,
        property_id=args.property_id,
        actor_id=args.actor_id,
        service_actor_id=service_actor,
    )
    started = utc_now()
    status: dict[str, object] = {"last_run_at": format_time(started)}
    try:
        client = RelayClient(bots.relay_host, read_pull_key(bots.relay_pull_key_file))
        key = load_office_private_key(bots.office_private_key_file)
        result = run_pull(
            client=client,
            key=key,
            store=store,
            media_directory=bots.media_directory,
            hr_files_directory=hr_files,
        )
        store.remove_old_payloads()
        store.tenant_end_finished_links()
        store.remove_old_link_attempts()
        store.visit_reminders()
        store.visit_requests_remove_old()
        # The 18:00 summary of the staff checklists for the Authorizers, once a day.
        store.staff_daily_summary()
        if service_actor is not None:
            remove_old_card_photos(store, hr_files)
        push_form_data(client=client, store=store, status_directory=config.status_directory)
    except (RelayError, SealError) as error:
        code = error.code if isinstance(error, RelayError) else "office_key_unreadable"
        print(f"telegram_pull:failed:{code}", file=sys.stderr, flush=True)
        status.update({"last_outcome": "failed", "last_error": code})
        _write(config.status_directory, status, store)
        return 1
    print(
        f"telegram_pull:received={result.received},saved={result.saved},"
        f"repeated={result.repeated},refused={result.refused}",
        flush=True,
    )
    status.update({"last_outcome": "ok", "last_success_at": format_time(utc_now())})
    _write(config.status_directory, status, store)
    return 0


def _write(directory: Path, status: dict[str, object], store: TelegramStore) -> None:
    try:
        health = store.health()
    except Exception:
        health = {}
    status["relay_dropped"] = health.get("relay_dropped", 0)
    write_status(directory, "telegram-pull", status)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
