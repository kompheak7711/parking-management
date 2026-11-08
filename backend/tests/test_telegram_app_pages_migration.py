"""The Telegram app pages on the real database (migration 20270522_284, DL-128, bots step 2c).

Linked tenants: the links in force, the wrong link tries with tries left, the ended links, and
Remove link with a reason. Telegram health: the bots, the messages not sent with their last error,
Retry once for a message the app gave up on, and the last relay pulls. Owner and Manager only.
"""

from __future__ import annotations

import json
import uuid

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import ATTEMPT, DUE, RECORD, TelegramDatabase, item, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_tenant_link_migration import LINK, add_lease, share_phone

LINKS = "SELECT app.telegram_links_page(%s, %s)"
HEALTH = "SELECT app.telegram_health_page(%s, %s)"
RETRY = "SELECT app.telegram_outbox_retry(%s, %s, %s)"
REMOVE = "SELECT app.telegram_tenant_link_remove(%s, %s, %s, %s)::text"


def test_linked_tenants_shows_links_wrong_tries_and_ended_links(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    add_lease(db, name="Sao Rina", phone="+85512300400", unit_number="601")
    linked_user, trying_user = 920001, 920002
    share_phone(db, linked_user, "+85512300400", "item-page-link-01")
    link = run(db.runtime_url, LINK, db.property_id, linked_user, "Rina Sao", "601", db.owner)
    share_phone(db, trying_user, "+85599000111", "item-page-try-01")
    for _ in range(2):
        run(db.runtime_url, LINK, db.property_id, trying_user, "Somebody", "601", db.owner)
    page = run(db.runtime_url, LINKS, db.property_id, db.manager)
    mine = [row for row in page["linked"] if row["id"] == link["link_id"]]
    assert mine and mine[0]["name"] == "Sao Rina" and mine[0]["unit_number"] == "601"
    assert mine[0]["phone"] == "+85512300400" and mine[0]["telegram_user_id"] == linked_user
    tries = [row for row in page["tries"] if row["telegram_user_id"] == trying_user]
    assert tries == [
        {
            "telegram_user_id": trying_user,
            "phone": "+85599000111",
            "typed_name": "Somebody",
            "typed_unit": "601",
            "tries": 2,
            "tries_left": 3,
            "blocked_until": None,
            "last_at": tries[0]["last_at"],
        }
    ]
    assert page["rules"] == {"tries": 5, "block_hours": 24, "keep_days": 90}
    run(db.runtime_url, REMOVE, db.property_id, link["link_id"], "Lost phone", db.manager)
    page = run(db.runtime_url, LINKS, db.property_id, db.owner)
    assert link["link_id"] not in [row["id"] for row in page["linked"]]
    ended = [row for row in page["ended"] if row["id"] == link["link_id"]]
    assert ended and ended[0]["reason"] == "REMOVED" and ended[0]["note"] == "Lost phone"
    refused(db.runtime_url, "42501", LINKS, db.property_id, db.staff)


def test_telegram_health_lists_messages_not_sent_and_retries_a_given_up_one_once(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    waiting = run(
        db.runtime_url,
        "SELECT app.telegram_queue_message(%s, %s::jsonb, %s)",
        db.property_id,
        json.dumps(
            {
                "bot": "TENANT",
                "chat_id": 920003,
                "text_code": "tenant.menu",
                "language": "en",
                "details": {},
            }
        ),
        db.owner,
    )
    run(
        db.runtime_url,
        ATTEMPT,
        db.property_id,
        waiting,
        "FAILED",
        "telegram_too_many",
        None,
        db.owner,
    )
    old = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.telegram_outbox (id, property_id, bot_code, chat_id, text_code, "
            "language, details, keyboard, created_at, created_by) VALUES (%s, %s, 'TENANT', "
            "920004, 'tenant.menu', 'km', '{}', 'tenant.menu', "
            "clock_timestamp() - interval '8 days', %s)",
            (old, db.property_id, db.owner),
        )
    gave_up = run(
        db.runtime_url,
        ATTEMPT,
        db.property_id,
        old,
        "FAILED",
        "telegram_blocked_by_person",
        None,
        db.owner,
    )
    assert gave_up == "GAVE_UP"
    page = run(db.runtime_url, HEALTH, db.property_id, db.manager)
    assert [bot["code"] for bot in page["bots"]] == ["CUSTOMER", "TENANT", "STAFF"]
    assert "outbox_waiting" in page and isinstance(page["pulls"], list)
    rows = {row["id"]: row for row in page["outbox"]}
    assert rows[str(waiting)]["status"] == "WAITING"
    assert rows[str(waiting)]["last_error"] == "telegram_too_many"
    assert rows[str(old)]["status"] == "GAVE_UP" and rows[str(old)]["retried"] is False
    assert rows[str(old)]["tries"] == 1
    refused(db.runtime_url, "55000", RETRY, db.property_id, waiting, db.owner)
    again = run(db.runtime_url, RETRY, db.property_id, old, db.manager)
    # Telegram said the person blocked the bot, so the copy waits until the person writes
    # again (DL-202 (C)); then it goes out with the same keyboard.
    due = run(db.runtime_url, DUE, db.property_id, 200, db.owner)
    assert str(again) not in {row["id"] for row in due}
    run(
        db.runtime_url,
        RECORD,
        db.property_id,
        item("item-page-unblock-01", 920004, telegram_user_id=920004, chat_id=920004),
        db.owner,
    )
    due = run(db.runtime_url, DUE, db.property_id, 200, db.owner)
    copy = [row for row in due if row["id"] == str(again)]
    assert copy and copy[0]["chat_id"] == 920004 and copy[0]["keyboard"] == "tenant.menu"
    refused(db.runtime_url, "55000", RETRY, db.property_id, old, db.manager)
    page = run(db.runtime_url, HEALTH, db.property_id, db.owner)
    assert {row["id"]: row for row in page["outbox"]}[str(old)]["retried"] is True
    refused(db.runtime_url, "42501", HEALTH, db.property_id, db.staff)
    refused(db.runtime_url, "42501", RETRY, db.property_id, old, db.staff)
    refused(db.runtime_url, "42501", "SELECT count(*) FROM app.telegram_outbox_retries")
