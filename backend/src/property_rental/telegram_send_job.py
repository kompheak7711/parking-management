"""The send job (bots plan, "The office app side"): every 10 seconds, send each message waiting in
the outbox to Telegram and record the try. A failed try is tried again after a growing wait
(the database decides when); after 7 days of failures the message is given up. Messages failing
for 12 hours show on the health page.

Each bot's key is a secret file under /run/secrets. A key, like the alert bot's, never goes
into a log or an error: only fixed codes leave this module.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from property_rental import aba_qr, payway
from property_rental.invoice_pdf import InvoicePdfError
from property_rental.operations_config import OperationsConfigError, load_operations_config
from property_rental.operations_status import format_time, utc_now, write_status
from property_rental.telegram_alerts import TELEGRAM_TOKEN_PATTERN
from property_rental.telegram_store import PostgresTelegramStore, TelegramStore
from property_rental.telegram_texts import TextError, keyboard_markup, render

SEND_TIMEOUT_SECONDS: Final = 10
# A sender posts JSON to an address and returns (HTTP status, answer). Tests replace it.
PostJson = Callable[[str, dict[str, Any]], tuple[int, bytes]]
# A document sender posts form fields and one file (name, bytes) and returns the same.
PostDocument = Callable[[str, dict[str, str], tuple[str, bytes]], tuple[int, bytes]]
# The Invoice PDF for an outbox message (DL-180), or None for a message without one.
InvoiceDocuments = Callable[[str], "aba_qr.InvoiceDocument | None"]
CAPTION_LIMIT: Final = 1024  # Telegram's longest caption


def _post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
    request = urllib.request.Request(
        address,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
            request, timeout=SEND_TIMEOUT_SECONDS, context=context
        ) as answer:
            return int(answer.status), answer.read(65536)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def _post_document(
    address: str, fields: dict[str, str], document: tuple[str, bytes]
) -> tuple[int, bytes]:
    """multipart/form-data with the fields and the PDF, as Telegram's sendDocument takes it."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode("utf-8")
            + b"\r\n"
        )
    file_name, data = document
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
        f'filename="{file_name}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        address,
        data=b"".join(parts),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
            request, timeout=SEND_TIMEOUT_SECONDS * 3, context=context
        ) as answer:
            return int(answer.status), answer.read(65536)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def caption_of(text: str) -> str:
    """The message as the PDF's caption; a very long one is cut (the PDF has every line)."""
    return text if len(text) <= CAPTION_LIMIT else text[: CAPTION_LIMIT - 1].rstrip() + "…"


def load_bot_tokens(files: dict[str, Path]) -> dict[str, str]:
    """The keys of the bots that are set up; a missing or placeholder file is left out."""
    tokens: dict[str, str] = {}
    for code, path in files.items():
        try:
            token = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if TELEGRAM_TOKEN_PATTERN.fullmatch(token):
            tokens[code] = token
    return tokens


def _error_code(status: int) -> str:
    return {
        400: "telegram_bad_request",
        401: "telegram_key_refused",
        403: "telegram_blocked_by_person",
        429: "telegram_too_many",
    }.get(status, f"telegram_http_{status}" if 100 <= status <= 599 else "telegram_failed")


@dataclass
class SendResult:
    sent: int = 0
    failed: int = 0
    gave_up: int = 0
    skipped: int = 0


def run_send(
    *,
    store: TelegramStore,
    api_host: str,
    tokens: dict[str, str],
    post_json: PostJson = _post_json,
    app_host: str | None = None,
    invoice_documents: InvoiceDocuments | None = None,
    post_document: PostDocument = _post_document,
    limit: int = 50,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> SendResult:
    result = SendResult()
    for message in store.outbox_due(limit):
        token = tokens.get(message["bot"])
        if token is None:
            # The bot is not set up yet: the message waits, and the health page shows it.
            result.skipped += 1
            continue
        try:
            details = message.get("details") or {}
            text = render(message["text_code"], message["language"], details)
            markup = keyboard_markup(
                message.get("keyboard"), message["language"], app_host, details
            )
        except TextError:
            outcome = store.record_attempt(message["id"], "FAILED", "text_unknown", None)
            result.gave_up += outcome == "GAVE_UP"
            result.failed += outcome == "FAILED"
            log("telegram_send:text_unknown")
            continue
        body: dict[str, Any] = {"chat_id": message["chat_id"], "text": text}
        if message.get("buttons"):
            body["reply_markup"] = {"inline_keyboard": message["buttons"]}
        elif markup is not None:
            body["reply_markup"] = markup
        # An Invoice to pay goes as the PDF with its ABA QR (DL-180). Without PayWay set up it
        # goes as text, as before; a PayWay problem waits and is tried again.
        invoice_file: aba_qr.InvoiceDocument | None = None
        if invoice_documents is not None and message.get("text_code") in aba_qr.INVOICE_MESSAGES:
            try:
                invoice_file = invoice_documents(str(message["id"]))
            except payway.PayWayError as error:
                outcome = store.record_attempt(message["id"], "FAILED", error.code, None)
                result.gave_up += outcome == "GAVE_UP"
                result.failed += outcome == "FAILED"
                log(f"telegram_send:failed:{error.code}")
                continue
            except InvoicePdfError as error:
                log(f"telegram_send:invoice_pdf:{error}")
            except Exception as error:
                # The QR or the PDF could not be made (database, fonts): tried again later. The
                # log names the kind of error only (never its text, which may hold data).
                outcome = store.record_attempt(message["id"], "FAILED", "invoice_pdf_failed", None)
                result.gave_up += outcome == "GAVE_UP"
                result.failed += outcome == "FAILED"
                log(f"telegram_send:failed:invoice_pdf_failed:{type(error).__name__}")
                continue
        try:
            if invoice_file is not None:
                fields = {"chat_id": str(message["chat_id"]), "caption": caption_of(text)}
                if "reply_markup" in body:
                    fields["reply_markup"] = json.dumps(body["reply_markup"])
                status, answer = post_document(
                    f"https://{api_host}/bot{token}/sendDocument",
                    fields,
                    (invoice_file.file_name, invoice_file.pdf),
                )
            else:
                status, answer = post_json(f"https://{api_host}/bot{token}/sendMessage", body)
        except Exception:
            status, answer = 0, b""
        message_id: int | None = None
        if status == 200:
            try:
                document = json.loads(answer)
                candidate = document["result"]["message_id"] if document.get("ok") else None
                if isinstance(candidate, int) and candidate > 0:
                    message_id = candidate
            except (ValueError, KeyError, TypeError):
                message_id = None
        if message_id is not None:
            store.record_attempt(message["id"], "SENT", None, message_id)
            result.sent += 1
            continue
        code = "telegram_unreachable" if status == 0 else _error_code(status)
        if status == 200:
            code = "telegram_bad_answer"
        outcome = store.record_attempt(message["id"], "FAILED", code, None)
        if outcome == "GAVE_UP":
            result.gave_up += 1
        else:
            result.failed += 1
        log(f"telegram_send:failed:{code}")
    return result


BOT_NAMES_FILE: Final = "telegram-bot-names.day"


def learn_bot_names(
    *,
    store: TelegramStore,
    api_host: str,
    tokens: dict[str, str],
    status_directory: Path,
    today: str,
    post_json: PostJson = _post_json,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> int:
    """Once a day, ask Telegram each bot's user name (getMe) and save it, so the app can make the
    t.me link of a QR (DL-214). Returns how many names changed."""
    marker = status_directory / BOT_NAMES_FILE
    try:
        if marker.read_text(encoding="utf-8").strip() == today:
            return 0
    except OSError:
        pass
    changed = 0
    learned = True
    for bot, token in sorted(tokens.items()):
        try:
            status, answer = post_json(f"https://{api_host}/bot{token}/getMe", {})
            document = json.loads(answer) if status == 200 else {}
            username = document["result"]["username"] if document.get("ok") else None
        except Exception:
            username = None
        if not isinstance(username, str) or not username:
            learned = False
            log(f"telegram_send:bot_name_unknown:{bot}")
            continue
        try:
            changed += store.bot_name_set(bot, username)
        except Exception:
            learned = False
            log(f"telegram_send:bot_name_not_saved:{bot}")
    if learned and tokens:
        try:
            marker.write_text(today + "\n", encoding="utf-8")
        except OSError:
            log("telegram_send:bot_names_marker_not_written")
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send the Telegram messages waiting in the outbox")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--property-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    args = parser.parse_args(argv)
    database_url = os.environ.get("APP_DATABASE_URL")
    if not database_url:
        parser.error("APP_DATABASE_URL is required")
    try:
        config = load_operations_config(args.config)
    except OperationsConfigError as error:
        print(f"telegram_send:config:{error}", file=sys.stderr, flush=True)
        return 2
    bots = config.telegram_bots
    if bots is None or not bots.enabled:
        print("telegram_send:not_enabled", flush=True)
        return 0
    store = PostgresTelegramStore(
        database_url, property_id=args.property_id, actor_id=args.actor_id
    )
    tokens = load_bot_tokens(bots.bot_token_files)
    learn_bot_names(
        store=store,
        api_host=bots.api_host,
        tokens=tokens,
        status_directory=config.status_directory,
        today=format_time(utc_now())[:10],
    )
    # ABA PayWay (DL-180): the Invoice PDF with its QR, and every 10 minutes a check of the
    # open QRs (a payment ABA tells the relay about is checked by the pull job at once).
    aba: aba_qr.AbaJob | None = None
    try:
        aba = aba_qr.load_job(
            config,
            database_url=database_url,
            financial_database_url=os.environ.get("APP_FINANCIAL_DATABASE_URL"),
            property_id=args.property_id,
            actor_id=args.actor_id,
        )
    except payway.PayWayError as error:
        print(f"telegram_send:payway:{error.code}", flush=True)
        aba_broken = True
    except Exception as error:
        print(f"telegram_send:payway:{type(error).__name__}", flush=True)
        aba_broken = True
    else:
        aba_broken = False
    documents: InvoiceDocuments | None = None
    if aba_broken:
        # PayWay is on but not ready: Invoice messages wait for their QR (owner: every Invoice
        # comes with its QR); the other messages go.
        def documents(outbox_id: str) -> aba_qr.InvoiceDocument | None:
            raise payway.PayWayError("payway_not_ready")

    elif aba is not None:
        job = aba

        def documents(outbox_id: str) -> aba_qr.InvoiceDocument | None:
            return aba_qr.invoice_document(outbox_id, store=job.store, config=job.config)

    result = run_send(
        store=store,
        api_host=bots.api_host,
        tokens=tokens,
        app_host=bots.relay_host,
        invoice_documents=documents,
    )
    print(
        f"telegram_send:sent={result.sent},failed={result.failed},gave_up={result.gave_up},"
        f"skipped={result.skipped}",
        flush=True,
    )
    if aba is not None:
        marker = config.status_directory / "aba-payway-check.time"
        if aba_qr.check_due(marker, utc_now()):
            try:
                checked = aba_qr.check_payments(
                    store=aba.store, config=aba.config, record_payment=aba.record_payment
                )
            except Exception as error:  # tried again at the next run
                print(f"aba_check:failed:{type(error).__name__}", flush=True)
            else:
                aba_qr.mark_checked(marker, utc_now())
                print(
                    f"aba_check:checked={checked.checked},recorded={checked.recorded},"
                    f"needs_check={checked.needs_check},failed={checked.failed}",
                    flush=True,
                )
    health = store.health()
    write_status(
        config.status_directory,
        "telegram-send",
        {
            "last_run_at": format_time(utc_now()),
            "outbox_waiting": health.get("outbox_waiting", 0),
            "outbox_failing_12h": health.get("outbox_failing_12h", 0),
            "outbox_gave_up_7d": health.get("outbox_gave_up_7d", 0),
        },
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
