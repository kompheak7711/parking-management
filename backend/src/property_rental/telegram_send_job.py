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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from property_rental.operations_config import OperationsConfigError, load_operations_config
from property_rental.operations_status import format_time, utc_now, write_status
from property_rental.telegram_alerts import TELEGRAM_TOKEN_PATTERN
from property_rental.telegram_store import PostgresTelegramStore, TelegramStore
from property_rental.telegram_texts import TextError, keyboard_markup, render

SEND_TIMEOUT_SECONDS: Final = 10
# A sender posts JSON to an address and returns (HTTP status, answer). Tests replace it.
PostJson = Callable[[str, dict[str, Any]], tuple[int, bytes]]


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
        address = f"https://{api_host}/bot{token}/sendMessage"
        try:
            status, answer = post_json(address, body)
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
    result = run_send(
        store=store,
        api_host=bots.api_host,
        tokens=tokens,
        app_host=bots.relay_host,
    )
    print(
        f"telegram_send:sent={result.sent},failed={result.failed},gave_up={result.gave_up},"
        f"skipped={result.skipped}",
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
