"""The Telegram bots shared base on the real database (migration 20270430_281, bots plan step 1).

Every item pulled from the relay is saved once; each photo once by its fingerprint; every
message waits in the outbox and each try is a row; history is never changed; only the account
the jobs run as (Owner or Manager rights) may call the job functions.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

RECORD = "SELECT app.telegram_record_pulled_item(%s, %s::jsonb, %s)"
QUEUE = "SELECT app.telegram_queue_message(%s, %s::jsonb, %s)"
DUE = "SELECT app.telegram_outbox_due(%s, %s, %s)"
ATTEMPT = "SELECT app.telegram_record_send_attempt(%s, %s, %s, %s, %s, %s)"
HEALTH = "SELECT app.telegram_health(%s, %s)"
SHA = "ab" * 32


@dataclass(frozen=True)
class TelegramDatabase:
    owner_url: str
    runtime_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID


@pytest.fixture(scope="module")
def telegram_database(migrated_database_url: str) -> Iterator[TelegramDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_telegram") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        name = urlsplit(temporary).path.lstrip("/")
        runtime_url = _url_with_database(runtime_database_url(), name)
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            for actor, bundle in ((manager, seeded[1]), (staff, seeded[2])):
                setup.execute(
                    "INSERT INTO app.user_role_assignments (assignment_id, actor_id, "
                    "role_bundle_id, property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
                    (uuid.uuid4(), actor, bundle, property_id),
                )
            setup.commit()
        yield TelegramDatabase(temporary, runtime_url, property_id, owner, manager, staff)


def run(url: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(url: str, state: str, sql: str, *params: Any) -> None:
    with pytest.raises(psycopg.Error) as caught:
        run(url, sql, *params)
    assert caught.value.sqlstate == state, caught.value


def item(relay_id: str, update_id: int | None, **extra: Any) -> str:
    body = {
        "relay_item_id": relay_id,
        "bot": "TENANT",
        "kind": "update",
        "received_at": "2026-11-04T09:00:00+00:00",
        "update_id": update_id,
        "telegram_user_id": 777001,
        "chat_id": 777001,
        "account": {"language": "km", "phone": None},
        "summary": {"kind": "update", "media": 0},
        "payload": {"message": {"text": "hello"}},
        "media": [],
    } | extra
    return json.dumps(body)


def test_rights_owner_and_manager_run_the_jobs_staff_cannot(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    for actor in (db.owner, db.manager):
        assert isinstance(run(db.runtime_url, HEALTH, db.property_id, actor), dict)
    refused(db.runtime_url, "42501", HEALTH, db.property_id, db.staff)
    refused(db.runtime_url, "42501", RECORD, db.property_id, item("item-staff-01", 1), db.staff)
    refused(db.runtime_url, "42501", HEALTH, db.property_id, None)


def test_an_item_is_saved_once_with_its_account_and_photos(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    media = [
        {
            "sha256": SHA,
            "content_type": "image/jpeg",
            "size_bytes": 1234,
            "storage_path": f"ab/{SHA}",
            "width": 1280,
            "height": 960,
            "telegram_file_unique_id": "AQADabc",
        }
    ]
    first = run(
        db.runtime_url,
        RECORD,
        db.property_id,
        item(
            "item-save-0001", 501, media=media, account={"language": "en", "phone": "+85512345678"}
        ),
        db.owner,
    )
    assert first["saved"] is True and len(first["media_ids"]) == 1
    again = run(db.runtime_url, RECORD, db.property_id, item("item-save-0001", 501), db.owner)
    assert again == {"saved": False, "inbound_id": first["inbound_id"]}
    # Telegram sent the same update twice: a second relay item, still saved once.
    twice = run(db.runtime_url, RECORD, db.property_id, item("item-save-0002", 501), db.owner)
    assert twice["saved"] is False
    # The same photo in another message is the same file.
    other = run(
        db.runtime_url,
        RECORD,
        db.property_id,
        item("item-save-0003", 502, media=media, account={}),
        db.owner,
    )
    assert other["media_ids"] == first["media_ids"]
    account = run(
        db.owner_url,
        "SELECT to_jsonb(a) FROM app.telegram_accounts AS a WHERE telegram_user_id = 777001",
    )
    assert account["language"] == "en" and account["phone_e164"] == "+85512345678"
    # A later message without a phone keeps the shared phone.
    run(db.runtime_url, RECORD, db.property_id, item("item-save-0004", 503, account={}), db.owner)
    assert (
        run(
            db.owner_url,
            "SELECT phone_e164 FROM app.telegram_accounts WHERE telegram_user_id = 777001",
        )
        == "+85512345678"
    )
    refused(
        db.runtime_url, "22023", RECORD, db.property_id, json.dumps({"bot": "TENANT"}), db.owner
    )


def test_history_is_never_changed_and_the_runtime_login_cannot_write(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    run(db.runtime_url, RECORD, db.property_id, item("item-hist-0001", 601), db.owner)
    message = run(
        db.runtime_url,
        QUEUE,
        db.property_id,
        json.dumps(
            {
                "bot": "TENANT",
                "chat_id": 777001,
                "text_code": "base.ping_reply",
                "language": "km",
                "details": {"bot": "x"},
            }
        ),
        db.owner,
    )
    for sql in (
        "UPDATE app.telegram_outbox SET chat_id = 1 WHERE id = %s",
        "DELETE FROM app.telegram_outbox WHERE id = %s",
    ):
        refused(db.owner_url, "55000", sql + " RETURNING 1", message)
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.telegram_inbound_events SET kind = 'other' "
        "WHERE relay_item_id = 'item-hist-0001' RETURNING 1",
    )
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.telegram_bots SET name_en = 'x' WHERE code = 'TENANT' RETURNING 1",
    )
    refused(
        db.owner_url,
        "55000",
        "UPDATE app.telegram_accounts SET telegram_user_id = 5 "
        "WHERE telegram_user_id = 777001 RETURNING 1",
    )
    refused(
        db.runtime_url,
        "42501",
        "INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language, "
        "created_by) VALUES (%s, 'TENANT', 1, 'x.y', 'km', %s) RETURNING 1",
        db.property_id,
        db.owner,
    )


def test_outbox_tries_waits_and_finishes_once(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    body = {
        "bot": "STAFF",
        "chat_id": 888002,
        "text_code": "base.ping_reply",
        "language": "en",
        "details": {"bot": "staff"},
    }
    message = str(run(db.runtime_url, QUEUE, db.property_id, json.dumps(body), db.owner))

    def due() -> set[str]:
        found = run(db.runtime_url, DUE, db.property_id, 200, db.owner)
        return {entry["id"] for entry in found}

    with psycopg.connect(db.owner_url) as owner:
        # A first try that failed two minutes ago: the wait is over.
        owner.execute(
            "INSERT INTO app.telegram_outbox_attempts (outbox_id, attempt_number, outcome, "
            "error_code, attempted_at, created_by) VALUES (%s, 1, 'FAILED', 'telegram_http_502', "
            "clock_timestamp() - interval '2 minutes', %s)",
            (message, db.owner),
        )
    assert message in due()
    assert (
        run(
            db.runtime_url,
            ATTEMPT,
            db.property_id,
            message,
            "FAILED",
            "telegram_http_502",
            None,
            db.owner,
        )
        == "FAILED"
    )
    assert message not in due(), "a failed try waits before the next one"
    assert (
        run(db.runtime_url, ATTEMPT, db.property_id, message, "SENT", None, 91, db.owner) == "SENT"
    )
    assert message not in due()
    refused(db.runtime_url, "55000", ATTEMPT, db.property_id, message, "SENT", None, 92, db.owner)

    # A message that kept failing for 7 days is given up.
    with psycopg.connect(db.owner_url) as owner:
        old = owner.execute(
            "INSERT INTO app.telegram_outbox (property_id, bot_code, chat_id, text_code, language, "
            "created_at, created_by) VALUES (%s, 'TENANT', 5, 'base.ping_reply', 'km', "
            "now() - interval '8 days', %s) RETURNING id",
            (db.property_id, db.owner),
        ).fetchone()
    assert old is not None
    assert (
        run(db.runtime_url, ATTEMPT, db.property_id, old[0], "FAILED", None, None, db.owner)
        == "GAVE_UP"
    )
    assert str(old[0]) not in due()
    health = run(db.runtime_url, HEALTH, db.property_id, db.manager)
    assert health["outbox_gave_up_7d"] >= 1


def test_pull_runs_and_health(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    run(
        db.runtime_url,
        "SELECT app.telegram_record_pull_run(%s, %s::jsonb, %s)",
        db.property_id,
        json.dumps(
            {
                "started_at": "2026-11-04T09:00:00+00:00",
                "finished_at": "2026-11-04T09:00:02+00:00",
                "outcome": "OK",
                "items_received": 2,
                "items_saved": 2,
                "relay_waiting": 0,
                "relay_dropped": 1,
            }
        ),
        db.owner,
    )
    health = run(db.runtime_url, HEALTH, db.property_id, db.owner)
    assert health["last_pull_outcome"] == "OK"
    assert health["relay_dropped"] == 1
    assert health["last_ok_pull_at"] is not None


def test_raw_messages_are_removed_after_90_days_and_the_summary_stays(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    old = json.loads(item("item-old-00001", 701))
    old["received_at"] = "2025-01-01T09:00:00+00:00"
    run(db.runtime_url, RECORD, db.property_id, json.dumps(old), db.owner)
    removed = run(
        db.runtime_url, "SELECT app.telegram_remove_old_payloads(%s, %s)", db.property_id, db.owner
    )
    assert removed >= 1
    row = run(
        db.owner_url,
        "SELECT jsonb_build_array(payload, summary, payload_removed_at IS NOT NULL) "
        "FROM app.telegram_inbound_events WHERE relay_item_id = 'item-old-00001'",
    )
    assert row[0] is None and row[1]["kind"] == "update" and row[2] is True
