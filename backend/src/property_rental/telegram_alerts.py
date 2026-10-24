"""Telegram alert messages to the Owner and the Manager (V1-059, DL-071 answer 8; DEPLOY-051).

The bot token and the two chat ids are secrets in protected files (`/run/secrets/`); this
module reads them, never writes them, and never puts them in a log, a status file or an error
message (an error from the network library may contain the request address, which holds the
token, so only fixed failure codes leave this module). A message carries only the fixed text of
a warning code, never Customer data. Telegram is optional (SEC-059): when the files hold only a
placeholder, or a message cannot be sent, the caller keeps working and the health page shows
the warning.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from property_rental.operations_config import TelegramConfig

TELEGRAM_TOKEN_PATTERN: Final = re.compile(r"^[0-9]{5,16}:[A-Za-z0-9_-]{30,64}$")
CHAT_ID_PATTERN: Final = re.compile(r"^-?[0-9]{1,20}$")
SEND_TIMEOUT_SECONDS: Final = 10
MAX_MESSAGE_CHARACTERS: Final = 3500

DeliveryOutcome = Literal["sent", "failed", "not_configured"]
# A sender posts one form to one address and returns the HTTP status; it is replaced in tests.
PostForm = Callable[[str, dict[str, str]], int]


@dataclass(frozen=True, slots=True)
class TelegramTarget:
    """A resolved token and the chat ids, kept in memory only."""

    token: str
    chat_ids: tuple[str, ...]

    def __repr__(self) -> str:
        return f"TelegramTarget(chats={len(self.chat_ids)})"


def load_telegram_target(config: TelegramConfig) -> TelegramTarget | None:
    """The token and chat ids, or None while either file is missing or a placeholder."""
    try:
        token = config.bot_token_file.read_text(encoding="utf-8").strip()
        chats_document = json.loads(config.chat_ids_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not TELEGRAM_TOKEN_PATTERN.fullmatch(token):
        return None
    if not isinstance(chats_document, dict):
        return None
    chat_ids: list[str] = []
    for recipient in config.recipients:
        chat_id = chats_document.get(recipient)
        if not isinstance(chat_id, str | int) or isinstance(chat_id, bool):
            return None
        text = str(chat_id)
        if not CHAT_ID_PATTERN.fullmatch(text):
            return None
        chat_ids.append(text)
    return TelegramTarget(token=token, chat_ids=tuple(chat_ids))


def _post_form(address: str, form: dict[str, str]) -> int:
    request = urllib.request.Request(
        address,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS, context=context) as answer:
        return int(answer.status)


def send_alert(
    config: TelegramConfig,
    lines: Sequence[str],
    *,
    post_form: PostForm = _post_form,
    target: TelegramTarget | None = None,
) -> DeliveryOutcome:
    """Send one message to every recipient; `sent` only when all of them got it."""
    resolved = target if target is not None else load_telegram_target(config)
    if resolved is None:
        return "not_configured"
    text = "\n".join(lines)[:MAX_MESSAGE_CHARACTERS]
    address = f"https://{config.api_host}/bot{resolved.token}/sendMessage"
    delivered = True
    for chat_id in resolved.chat_ids:
        try:
            status = post_form(address, {"chat_id": chat_id, "text": text})
        except Exception:
            delivered = False
            continue
        if status != 200:
            delivered = False
    return "sent" if delivered else "failed"
