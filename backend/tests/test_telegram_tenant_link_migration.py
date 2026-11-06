"""The Tenant bot link on the real database (migration 20270520_282, DL-126, bots plan step 2).

Owner rules: the shared phone, the typed name and the typed Unit must all match one person on an
active Lease; capitals, spaces and word order do not matter; 5 wrong tries in 24 hours block
linking for 24 hours; a link ends when its Lease ends or staff remove it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import psycopg
import pytest

from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, TelegramDatabase, item, refused, run
from test_telegram_base_migration import telegram_database as telegram_database

STATE = "SELECT app.telegram_bot_state(%s, %s, %s, %s)"
LINK = "SELECT app.telegram_tenant_link(%s, %s, %s, %s, %s)"
REPLY = "SELECT app.telegram_bot_reply(%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)"


def today(db: TelegramDatabase) -> date:
    day = run(db.owner_url, "SELECT app.gl_today(%s)", db.property_id)
    assert isinstance(day, date)
    return day


def add_lease(
    db: TelegramDatabase,
    *,
    name: str,
    phone: str | None,
    unit_number: str,
    ends_in_days: int = 300,
) -> tuple[uuid.UUID, uuid.UUID]:
    day = today(db)
    with psycopg.connect(db.owner_url) as connection:
        unit_id, customer_id = uuid.uuid4(), uuid.uuid4()
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "created_by, updated_by) VALUES (%s, %s, %s, '3', 'ONE_BEDROOM', 'VACANT', %s, %s)",
            (unit_id, db.property_id, unit_number, db.owner, db.owner),
        )
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            (customer_id, name, phone, db.owner, db.owner),
        )
        lease_id = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=day - timedelta(days=400),
            end_date=day + timedelta(days=ends_in_days),
        )
        sign_lease(connection, lease_id, db.owner)
    return lease_id, customer_id


def share_phone(db: TelegramDatabase, user: int, phone: str | None, relay_id: str) -> None:
    body = json.loads(item(relay_id, None))
    body.update(telegram_user_id=user, chat_id=user, account={"language": "km", "phone": phone})
    run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.owner)


@pytest.fixture(scope="module")
def tenant(telegram_database: TelegramDatabase) -> Iterator[dict[str, Any]]:
    lease_id, customer_id = add_lease(
        telegram_database, name="Dara Kim", phone="012 345 678 / 017 000 111", unit_number="305"
    )
    yield {"lease": lease_id, "customer": customer_id}


def test_a_tenant_links_with_phone_name_and_unit_in_any_order(
    telegram_database: TelegramDatabase, tenant: dict[str, Any]
) -> None:
    db = telegram_database
    user = 900001
    assert run(db.runtime_url, LINK, db.property_id, user, "Dara Kim", "305", db.owner) == {
        "result": "NO_PHONE"
    }
    share_phone(db, user, "+85512345678", "item-link-0001")
    linked = run(db.runtime_url, LINK, db.property_id, user, "  kim DARA ", "Unit 305", db.owner)
    assert linked["result"] == "LINKED"
    assert linked["name"] == "Dara Kim" and linked["unit_number"] == "305"
    state = run(db.runtime_url, STATE, db.property_id, "TENANT", user, db.owner)
    assert state["link"]["customer_id"] == str(tenant["customer"])
    assert state["link"]["lease_id"] == str(tenant["lease"])
    # Linking again to the same person keeps the one link.
    again = run(db.runtime_url, LINK, db.property_id, user, "DaraKim", "305", db.owner)
    assert again["link_id"] == linked["link_id"]
    access = run(
        db.runtime_url, "SELECT app.telegram_tenant_access_list(%s, %s)", db.property_id, db.owner
    )
    assert {"id": user, "role": "TENANT"} in access
    links = run(
        db.runtime_url, "SELECT app.telegram_tenant_links_read(%s, %s)", db.property_id, db.manager
    )
    assert [row["id"] for row in links].count(linked["link_id"]) == 1
    refused(
        db.runtime_url,
        "42501",
        "SELECT app.telegram_tenant_links_read(%s, %s)",
        db.property_id,
        db.staff,
    )


def test_a_wrong_part_is_refused_and_five_wrong_tries_block_for_a_day(
    telegram_database: TelegramDatabase, tenant: dict[str, Any]
) -> None:
    db = telegram_database
    user = 900002
    # Someone else's phone with the right name and Unit is not a match.
    share_phone(db, user, "+85599888777", "item-link-0002")
    tries = [
        run(db.runtime_url, LINK, db.property_id, user, "Dara Kim", "305", db.owner)
        for _ in range(5)
    ]
    assert [answer["tries_left"] for answer in tries] == [4, 3, 2, 1, 0]
    assert all(answer["result"] == "NO_MATCH" for answer in tries)
    assert tries[-1]["blocked_until"] is not None
    blocked = run(db.runtime_url, LINK, db.property_id, user, "Dara Kim", "305", db.owner)
    assert blocked["result"] == "BLOCKED"
    state = run(db.runtime_url, STATE, db.property_id, "TENANT", user, db.owner)
    assert state["blocked_until"] is not None and state["link"] is None
    # The right phone with a wrong name or a wrong Unit is refused too.
    other = 900003
    share_phone(db, other, "+85517000111", "item-link-0003")
    for name, unit in (("Dara Sok", "305"), ("Dara Kim", "306")):
        answer = run(db.runtime_url, LINK, db.property_id, other, name, unit, db.owner)
        assert answer["result"] == "NO_MATCH"
    assert (
        run(db.runtime_url, LINK, db.property_id, other, "Kim Dara", "305", db.owner)["result"]
        == "LINKED"
    )


def test_links_end_with_the_lease_or_when_staff_remove_them(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    # A Lease that ended yesterday: a link to it no longer counts, and the job records the end.
    lease_id, customer_id = add_lease(
        db, name="Sok Chan", phone="+855 15 222 333", unit_number="410", ends_in_days=-1
    )
    user = 900004
    share_phone(db, user, "+85515222333", "item-link-0004")
    assert (
        run(db.runtime_url, LINK, db.property_id, user, "Sok Chan", "410", db.owner)["result"]
        == "NO_MATCH"
    )
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.tenant_telegram_links (property_id, telegram_user_id, customer_id, "
            "lease_id, unit_id, created_by) SELECT %s, %s, %s, lease.id, lease.unit_id, %s "
            "FROM app.leases AS lease WHERE lease.id = %s",
            (db.property_id, user, customer_id, db.owner, lease_id),
        )
    state = run(db.runtime_url, STATE, db.property_id, "TENANT", user, db.owner)
    assert state["link"] is None
    ended = run(
        db.runtime_url,
        "SELECT app.telegram_tenant_end_finished_links(%s, %s)",
        db.property_id,
        db.owner,
    )
    assert ended >= 1
    # Staff remove a link with a reason; a removed link cannot be removed twice.
    add_lease(db, name="Neary Lim", phone="+855 16 444 555", unit_number="411")
    person = 900005
    share_phone(db, person, "+85516444555", "item-link-0005")
    link = run(db.runtime_url, LINK, db.property_id, person, "Lim Neary", "411", db.owner)
    remove = "SELECT app.telegram_tenant_link_remove(%s, %s, %s, %s)"
    refused(db.runtime_url, "22023", remove, db.property_id, link["link_id"], " ", db.manager)
    run(
        db.runtime_url,
        remove + " IS NULL",
        db.property_id,
        link["link_id"],
        "Lost phone",
        db.manager,
    )
    refused(db.runtime_url, "55000", remove, db.property_id, link["link_id"], "again", db.manager)
    assert run(db.runtime_url, STATE, db.property_id, "TENANT", person, db.owner)["link"] is None
    refused(db.runtime_url, "42501", remove, db.property_id, link["link_id"], "x", db.staff)


def test_the_bot_answer_saves_the_step_and_queues_the_messages(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 900006
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'en', %s) IS NULL",
        db.property_id,
        user,
        db.owner,
    )
    messages = [{"text_code": "tenant.ask_name", "details": {}, "keyboard": "remove"}]
    assert (
        run(
            db.runtime_url,
            REPLY,
            db.property_id,
            "TENANT",
            user,
            user,
            "link.name",
            json.dumps({"tries": 1}),
            "en",
            json.dumps(messages),
            db.owner,
        )
        == 1
    )
    state = run(db.runtime_url, STATE, db.property_id, "TENANT", user, db.owner)
    assert state["language"] == "en" and state["step"] == "link.name"
    assert state["data"] == {"tries": 1}
    due = run(
        db.runtime_url, "SELECT app.telegram_outbox_due(%s, 200, %s)", db.property_id, db.owner
    )
    mine = [message for message in due if message["chat_id"] == user]
    assert mine[0]["text_code"] == "tenant.ask_name" and mine[0]["keyboard"] == "remove"
    refused(
        db.runtime_url,
        "22023",
        REPLY,
        db.property_id,
        "TENANT",
        user,
        user,
        None,
        None,
        "fr",
        "[]",
        db.owner,
    )
    refused(
        db.runtime_url,
        "42501",
        REPLY,
        db.property_id,
        "TENANT",
        user,
        user,
        None,
        None,
        "en",
        "[]",
        db.staff,
    )


def test_typed_names_and_phones_stay_behind_the_functions(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    for table in ("tenant_link_attempts", "tenant_telegram_links", "telegram_chat_steps"):
        refused(db.runtime_url, "42501", f"SELECT count(*) FROM app.{table}")
    refused(
        db.owner_url, "55000", "UPDATE app.tenant_link_attempts SET typed_name = 'x' RETURNING 1"
    )
    refused(db.owner_url, "55000", "DELETE FROM app.tenant_link_attempts RETURNING 1")
    assert (
        run(
            db.runtime_url,
            "SELECT app.telegram_remove_old_link_attempts(%s, %s)",
            db.property_id,
            db.owner,
        )
        == 0
    )
