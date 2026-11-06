"""Make Reservation, Block, the 12-month removal and the month (migration 20270527_289, DL-173).

Owner rules of 28 Oct 2026 and the CRM mock-up: a request becomes a Reservation and closes; a
Manager blocks a Telegram account; name, phone, email, note and account go after 12 months with
no activity; this month, the reasons and the sources are for Managers and the Owner.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import create_reservation, setup_reservation_sources
from test_telegram_base_migration import TelegramDatabase, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_contact_faq_migration import ADD as CONTACT_ADD
from test_telegram_customer_bot_migration import CHOICES, INQUIRY, PAGE, inbound, request
from test_telegram_visit_request_work_migration import (
    DETAIL,
    act,
    add_inquiry,
    card_of,
    phone_of,
    refuse,
)

REMOVE = "SELECT app.visit_requests_remove_old(%s, %s)"


def reservation(db: TelegramDatabase) -> str:
    with psycopg.connect(db.owner_url) as connection:
        actor, property_id, unit, customer = setup_reservation_sources(connection)
        assert property_id == db.property_id
        _, made = create_reservation(
            connection, actor_id=actor, property_id=property_id, unit_id=unit,
            customer_id=customer,
        )  # fmt: skip
    return str(made["reservation_id"])


def ask_again(db: TelegramDatabase, user: int, relay: str) -> Any:
    from datetime import date

    message = inbound(db, user, relay, phone=phone_of(user))
    today = date.fromisoformat(
        run(db.runtime_url, CHOICES, db.property_id, user, db.owner)["today"]
    )
    return run(
        db.runtime_url, INQUIRY, db.property_id, message, user, user, "en",
        request(today, contact_by="TELEGRAM"), db.owner,
    )  # fmt: skip


def without_triggers(db: TelegramDatabase, *statements: tuple[str, tuple[Any, ...]]) -> None:
    with psycopg.connect(db.owner_url) as connection:
        for table in ("visit_requests", "visit_request_events"):
            connection.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER USER")
        for sql, values in statements:
            connection.execute(sql, values)
        for table in ("visit_requests", "visit_request_events"):
            connection.execute(f"ALTER TABLE app.{table} ENABLE TRIGGER USER")


def test_make_reservation_block_and_the_month(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    sokha, other = 970001, 970002
    first = add_inquiry(db, sokha, "item-close-1", contact_by="TELEGRAM")
    act(db, first, "TAKE", db.staff)
    held = reservation(db)
    refuse(db, "55000", first, "RESERVE", db.staff, reservation_id=held)
    act(db, first, "CALL", db.staff, answered=True)
    refuse(db, "22023", first, "RESERVE", db.staff, reservation_id=str(uuid.uuid4()))
    refuse(db, "22023", first, "RESERVE", db.staff, reservation_id="not a number")
    act(db, first, "RESERVE", db.staff, reservation_id=held)
    card = card_of(db, sokha)
    assert card["status"] == "RESERVED" and card["reservation_id"] == held
    refuse(db, "55000", first, "CALL", db.staff, answered=True)
    refuse(db, "55000", first, "REOPEN", db.manager, note="Again")
    # One request per Reservation.
    second = add_inquiry(db, other, "item-close-2", contact_by="TELEGRAM")
    act(db, second, "TAKE", db.staff)
    act(db, second, "CALL", db.staff, answered=True)
    refuse(db, "55000", second, "RESERVE", db.staff, reservation_id=held)
    # A Reservation request does not take new inquiries: the person starts a new one.
    assert ask_again(db, sokha, "item-close-3")["result"] == "ADDED"

    # Block: a Manager, with why. A blocked account sends no inquiry and no Contact office message.
    refuse(db, "42501", second, "BLOCK", db.staff, note="Adverts")
    refuse(db, "22023", second, "BLOCK", db.manager)
    act(db, second, "BLOCK", db.manager, note="Adverts")
    assert card_of(db, other)["blocked"] is True
    refuse(db, "55000", second, "BLOCK", db.manager, note="Adverts")
    assert ask_again(db, other, "item-close-4") == {"result": "BLOCKED"}
    message = inbound(db, other, "item-close-5", phone=phone_of(other))
    blocked = run(
        db.runtime_url, CONTACT_ADD, db.property_id, message, "CUSTOMER", other, other, "en",
        "Spammer", "Buy now", db.owner,
    )  # fmt: skip
    assert blocked == {"result": "BLOCKED"}
    act(db, second, "UNBLOCK", db.manager)
    assert card_of(db, other)["blocked"] is False
    assert ask_again(db, other, "item-close-6")["result"] == "JOINED"
    refused(db.owner_url, "55000", "DELETE FROM app.telegram_account_blocks RETURNING 1")

    # This month: for Managers and the Owner only.
    assert run(db.runtime_url, PAGE, db.property_id, db.staff)["month"] is None
    month = run(db.runtime_url, PAGE, db.property_id, db.manager)["month"]
    assert month["new"] >= 3 and month["joined"] >= 1
    assert month["steps"]["RESERVED"] == 1 and month["steps"]["VISIT_BOOKED"] == 0
    assert month["sources"] == [{"source": "TELEGRAM", "count": month["new"]}]


def test_name_phone_and_account_go_after_12_months(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    old, fresh = 970011, 970012
    stale = add_inquiry(db, old, "item-close-11", contact_by="EMAIL")
    act(db, stale, "TAKE", db.staff)
    act(db, stale, "CALL", db.staff, answered=True, note="Will call back")
    ask_again(db, old, "item-close-12")  # joins the first
    add_inquiry(db, fresh, "item-close-13")
    year_ago = "clock_timestamp() - interval '13 months'"
    without_triggers(
        db,
        (
            f"UPDATE app.visit_requests SET received_at = {year_ago} "
            "WHERE id = %s OR joined_to = %s",
            (stale, stale),
        ),
        (
            f"UPDATE app.visit_request_events SET created_at = {year_ago} WHERE request_id = %s",
            (stale,),
        ),
    )
    with psycopg.connect(db.owner_url) as connection:
        connection.execute("ALTER TABLE app.telegram_accounts DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.telegram_accounts SET first_seen_at = clock_timestamp() - interval "
            "'14 months', last_seen_at = clock_timestamp() - interval '13 months' "
            "WHERE telegram_user_id = %s",
            (old,),
        )
        connection.execute("ALTER TABLE app.telegram_accounts ENABLE TRIGGER USER")
    refused(db.runtime_url, "42501", REMOVE, db.property_id, db.staff)
    assert run(db.runtime_url, REMOVE, db.property_id, db.owner) == 1
    assert run(db.runtime_url, REMOVE, db.property_id, db.owner) == 0
    page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    gone = next(row for row in page["requests"] if row["id"] == stale)
    assert gone["removed"] is True and gone["name"] == "" and gone["phone"] == ""
    assert gone["email"] is None and gone["note"] is None
    assert gone["joined"][0]["name"] == "" and gone["calls"] == 1
    assert run(db.runtime_url, DETAIL, db.property_id, stale, db.staff)["history"]
    assert card_of(db, fresh)["removed"] is False
    with psycopg.connect(db.owner_url) as connection:
        phone = connection.execute(
            "SELECT phone_e164 FROM app.telegram_accounts WHERE telegram_user_id = %s", (old,)
        ).fetchone()
    assert phone == (None,)
    # Nothing else can change on a request, removed or not.
    refused(
        db.owner_url, "55000", "UPDATE app.visit_requests SET unit_type = 'STUDIO' WHERE id = %s "
        "RETURNING 1", stale,
    )  # fmt: skip
    refused(
        db.owner_url, "55000", "DELETE FROM app.visit_requests WHERE id = %s RETURNING 1", stale
    )
    assert json.dumps(gone)  # the row stays readable
