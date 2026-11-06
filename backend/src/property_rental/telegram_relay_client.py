"""The office side of the relay calls (bots plan, "The relay", job 4, and "Safety rules").

Every call the office makes to the relay is signed with the pull key, a secret file under
/run/secrets that the relay also holds:

    X-Office-Time:      the time in whole seconds (the relay refuses more than 5 minutes off)
    X-Office-Signature: hex HMAC-SHA256(pull key,
                        time LF METHOD LF path LF hex SHA-256(body))

The relay answers only signed calls, so nobody else can read or delete what waits there. The
pull key, like the bot keys, never goes into a log or an error message: only fixed codes leave
this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

TIMEOUT_SECONDS: Final = 20
MAX_MEDIA_BYTES: Final = 30 * 1024 * 1024
HOST_PATTERN: Final = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9-]{1,63})+$")
ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class RelayError(RuntimeError):
    """A relay call failed; `code` is a fixed word safe for logs and status files."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# A transport takes (method, url, headers, body) and returns (status, body). Tests replace it.
Transport = Callable[[str, str, dict[str, str], bytes], tuple[int, bytes]]


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes
) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body if method != "GET" else None, method=method, headers=headers
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=context) as answer:
            return int(answer.status), answer.read(MAX_MEDIA_BYTES + 1)
    except urllib.error.HTTPError as error:
        return int(error.code), b""


def read_pull_key(path: Path) -> bytes:
    try:
        key = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise RelayError("pull_key_unreadable") from error
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise RelayError("pull_key_not_set")
    return bytes.fromhex(key)


def signature(key: bytes, moment: int, method: str, path: str, body: bytes) -> str:
    message = f"{moment}\n{method}\n{path}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class RelayItem:
    item_id: str
    bot: str
    kind: str
    received_at: str
    sealed: bytes
    media_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelayBatch:
    items: tuple[RelayItem, ...]
    waiting: int
    oldest_at: str | None
    dropped: int


class RelayClient:
    def __init__(
        self,
        host: str,
        pull_key: bytes,
        *,
        transport: Transport = _urllib_transport,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not HOST_PATTERN.fullmatch(host):
            raise RelayError("relay_host_invalid")
        self._host = host
        self._key = pull_key
        self._transport = transport
        self._clock = clock

    def __repr__(self) -> str:
        return f"RelayClient(host={self._host!r})"

    def _call(self, method: str, path: str, payload: object | None = None) -> bytes:
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        moment = int(self._clock())
        headers = {
            "X-Office-Time": str(moment),
            "X-Office-Signature": signature(self._key, moment, method, path, body),
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            status, answer = self._transport(method, f"https://{self._host}{path}", headers, body)
        except Exception as error:
            raise RelayError("relay_unreachable") from error
        if status == 401:
            raise RelayError("relay_refused_signature")
        if status != 200:
            raise RelayError(f"relay_http_{status}" if 100 <= status <= 599 else "relay_failed")
        return answer

    def _json(self, method: str, path: str, payload: object | None = None) -> dict[str, object]:
        try:
            document = json.loads(self._call(method, path, payload))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RelayError("relay_bad_answer") from error
        if not isinstance(document, dict):
            raise RelayError("relay_bad_answer")
        return document

    def pull(self, limit: int = 50) -> RelayBatch:
        import base64

        document = self._json("GET", f"/office/items?limit={max(1, min(limit, 100))}")
        raw_items = document.get("items")
        if not isinstance(raw_items, list):
            raise RelayError("relay_bad_answer")
        items: list[RelayItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise RelayError("relay_bad_answer")
            item_id, bot, kind = raw.get("id"), raw.get("bot"), raw.get("kind")
            received, sealed, media = raw.get("received_at"), raw.get("sealed"), raw.get("media")
            if not (
                isinstance(item_id, str)
                and ID_PATTERN.fullmatch(item_id)
                and isinstance(bot, str)
                and isinstance(kind, str)
                and isinstance(received, str)
                and isinstance(sealed, str)
                and isinstance(media, list)
                and all(isinstance(m, str) and ID_PATTERN.fullmatch(m) for m in media)
            ):
                raise RelayError("relay_bad_answer")
            try:
                sealed_bytes = base64.b64decode(sealed, validate=True)
            except ValueError as error:
                raise RelayError("relay_bad_answer") from error
            items.append(RelayItem(item_id, bot, kind, received, sealed_bytes, tuple(media)))
        waiting, oldest, dropped = (
            document.get("waiting"),
            document.get("oldest_at"),
            document.get("dropped"),
        )
        return RelayBatch(
            items=tuple(items),
            waiting=waiting if isinstance(waiting, int) and waiting >= 0 else 0,
            oldest_at=oldest if isinstance(oldest, str) else None,
            dropped=dropped if isinstance(dropped, int) and dropped >= 0 else 0,
        )

    def media(self, media_id: str) -> bytes:
        if not ID_PATTERN.fullmatch(media_id):
            raise RelayError("relay_bad_answer")
        answer = self._call("GET", f"/office/media/{media_id}")
        if len(answer) > MAX_MEDIA_BYTES:
            raise RelayError("relay_media_too_big")
        return answer

    def confirm(self, item_ids: list[str]) -> int:
        if not item_ids:
            return 0
        document = self._json("POST", "/office/confirm", {"ids": item_ids})
        deleted = document.get("deleted")
        return deleted if isinstance(deleted, int) else 0

    def set_access(self, bot: str, users: list[dict[str, object]]) -> None:
        self._json("PUT", f"/office/access/{bot.lower()}", {"users": users})

    def set_choices(self, bot: str, choices: dict[str, object]) -> None:
        self._json("PUT", f"/office/choices/{bot.lower()}", {"choices": choices})
