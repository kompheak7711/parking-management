"""Database review fixes of 7 Nov 2026 (DL-202 (B) and (C), migrations 20270705_370 and
20270706_371): a message with a dedupe key waits in the outbox once, and a chat whose person
blocked the bot gets nothing until the person writes again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import (
    ATTEMPT,
    DUE,
    HEALTH,
    QUEUE,
    RECORD,
    TelegramDatabase,
    item,
    refused,
    run,
)
from test_telegram_base_migration import telegram_database as telegram_database

REPLY = "SELECT app.telegram_bot_reply(%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)"
RETRY = "SELECT app.telegram_outbox_retry(%s, %s, %s)"
ROWS = "SELECT count(*) FROM app.telegram_outbox WHERE bot_code = %s AND chat_id = %s"
KEY = "SELECT dedupe_key FROM app.telegram_outbox WHERE id = %s"
BLOCKS = (
    "SELECT kind FROM app.telegram_bot_blocks WHERE bot_code = %s AND chat_id = %s "
    "ORDER BY noted_at, kind"
)
BLOCKED = "telegram_blocked_by_person"


def message(chat: int, **extra: Any) -> str:
    body = {
        "bot": "TENANT",
        "chat_id": chat,
        "text_code": "base.ping_reply",
        "language": "en",
        "details": {"bot": "test"},
    }
    return json.dumps(body | extra)


def queue(db: TelegramDatabase, chat: int, **extra: Any) -> str:
    return str(run(db.runtime_url, QUEUE, db.property_id, message(chat, **extra), db.owner))


def due(db: TelegramDatabase) -> set[str]:
    found = run(db.runtime_url, DUE, db.property_id, 200, db.owner)
    return {entry["id"] for entry in found}


def blocks(db: TelegramDatabase, chat: int) -> list[str]:
    with psycopg.connect(db.owner_url) as owner:
        return [kind for (kind,) in owner.execute(BLOCKS, ("TENANT", chat)).fetchall()]


@pytest.mark.parametrize(
    ("revision", "parent"),
    [("20270705_370", "20270612_321"), ("20270706_371", "20270705_370")],
)
def test_migrations_370_and_371_follow_in_order_and_are_forward_only(
    revision: str, parent: str
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config).get_revision(revision)
    assert script is not None and script.down_revision == parent
    with pytest.raises(RuntimeError, match="forward-only"):
        script.module.downgrade()


def test_a_message_with_a_dedupe_key_waits_once(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    chat = 7770501
    first = queue(db, chat, dedupe_key="ping:item-1")
    assert queue(db, chat, dedupe_key="ping:item-1") == first, "the same message is queued once"
    assert run(db.owner_url, ROWS, "TENANT", chat) == 1
    assert run(db.owner_url, KEY, first) == "ping:item-1"
    # The same key for another chat, or a message without a key, is another message.
    assert queue(db, chat + 1, dedupe_key="ping:item-1") != first
    queue(db, chat)
    queue(db, chat)
    assert run(db.owner_url, ROWS, "TENANT", chat) == 3
    # A key is a short word, never blank.
    for bad in (" ", "k" * 121):
        refused(
            db.runtime_url, "22023", QUEUE, db.property_id, message(chat, dedupe_key=bad), db.owner
        )


def test_a_given_up_message_with_a_key_can_still_be_sent_again(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    chat = 7770503
    with psycopg.connect(db.owner_url) as owner:
        old = owner.execute(
            "INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language, "
            "dedupe_key, created_at, created_by) VALUES (%s, 'TENANT', %s, 'base.ping_reply', "
            "'km', 'summary:2026-10-01', now() - interval '8 days', %s) RETURNING id",
            (db.property_id, chat, db.owner),
        ).fetchone()
    assert old is not None
    failed = (db.property_id, old[0], "FAILED", "telegram_http_502", None, db.owner)
    assert run(db.runtime_url, ATTEMPT, *failed) == "GAVE_UP"
    again = run(db.runtime_url, RETRY, db.property_id, old[0], db.owner)
    assert again != old[0] and str(again) in due(db)
    # The copy carries no key, so the key still names the first message only.
    assert run(db.owner_url, KEY, again) is None


def test_bot_replies_to_one_inbound_item_wait_once(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    user = 7770505
    messages = json.dumps(
        [
            {"text_code": "tenant.welcome", "keyboard": "tenant.language"},
            {"text_code": "base.ping_reply", "details": {"bot": "x"}},
        ]
    )
    args = (db.property_id, "TENANT", user, user, "language", None, "km", messages, db.owner)
    assert run(db.runtime_url, REPLY, *args, "in-501") == 2
    assert run(db.runtime_url, REPLY, *args, "in-501") == 0, "the same answer is queued once"
    assert run(db.owner_url, ROWS, "TENANT", user) == 2
    # An answer to another item, or one that names no item, is new.
    assert run(db.runtime_url, REPLY, *args, "in-502") == 2
    assert run(db.runtime_url, REPLY, *args, None) == 2
    assert run(db.owner_url, ROWS, "TENANT", user) == 6


def test_a_chat_that_blocked_the_bot_waits_until_the_person_writes_again(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    chat = 7770507
    first = queue(db, chat)
    second = queue(db, chat)
    elsewhere = queue(db, chat + 1)
    assert {first, second, elsewhere} <= due(db)

    # Telegram answers 403: the person blocked the bot. The chat is noted and nothing more is
    # sent to it; other chats are not touched.
    assert (
        run(db.runtime_url, ATTEMPT, db.property_id, first, "FAILED", BLOCKED, None, db.owner)
        == "FAILED"
    )
    assert blocks(db, chat) == ["BLOCKED"]
    waiting = due(db)
    assert first not in waiting and second not in waiting and elsewhere in waiting
    assert run(db.runtime_url, HEALTH, db.property_id, db.manager)["chats_blocked"] == 1
    # A second refusal while blocked adds nothing.
    with psycopg.connect(db.owner_url) as owner:
        owner.execute(
            "INSERT INTO app.telegram_outbox_attempts (outbox_id, attempt_number, outcome, "
            "error_code, attempted_at, created_by) VALUES (%s, 2, 'FAILED', %s, "
            "clock_timestamp() - interval '2 minutes', %s)",
            (first, BLOCKED, db.owner),
        )
    assert blocks(db, chat) == ["BLOCKED"]

    # The person writes again (the pull job saves the item): the block is over and the waiting
    # messages go out again.
    run(
        db.runtime_url,
        RECORD,
        db.property_id,
        item("item-block-1", 9101, telegram_user_id=chat, chat_id=chat),
        db.owner,
    )
    assert blocks(db, chat) == ["BLOCKED", "CLEARED"]
    assert run(db.owner_url, "SELECT app.telegram_chat_blocked('TENANT', %s)", chat) is False
    # The never-tried message goes out at once; the refused one waits out its normal pause
    # after two tries (two minutes) and then goes out too.
    assert {second, elsewhere} <= due(db)
    assert run(db.runtime_url, HEALTH, db.property_id, db.manager)["chats_blocked"] == 0

    # Nobody writes or edits the record by hand.
    refused(
        db.runtime_url,
        "42501",
        "INSERT INTO app.telegram_bot_blocks (property_id, bot_code, chat_id, kind, outbox_id, "
        "created_by) VALUES (%s, 'TENANT', %s, 'BLOCKED', %s, %s)",
        db.property_id,
        chat,
        first,
        db.owner,
    )
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.telegram_bot_blocks SET kind = 'CLEARED' WHERE chat_id = %s RETURNING id",
        chat,
    )
