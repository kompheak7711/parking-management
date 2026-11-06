"""Working the Visit requests (migration 20270526_288, DL-172, bots step 3b).

Owner rules of 28 Oct 2026: oldest first; Take makes a request yours and a Manager gives it to
another person; Late is more than 2 working hours (Monday to Saturday, 07:00 to 17:00) with
nobody taking it; Record a call; Book and move a visit (a Telegram customer gets the bot's
confirmation, and the reminder at 08:00 the day before; others are in "Send by hand today");
Visited or No-show; Close with a reason (Could not reach after no answer on 3 days); Reopen;
a Manager marks Spam.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import TelegramDatabase, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_customer_bot_migration import CHOICES, INQUIRY, PAGE, inbound, request

ACT = "SELECT app.visit_request_act(%s, %s, %s, %s::jsonb, %s)"
DETAIL = "SELECT app.visit_request_detail(%s, %s, %s)"
REMIND = "SELECT app.visit_request_reminders(%s, %s)"


def zone(db: TelegramDatabase) -> ZoneInfo:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT timezone_name FROM app.properties WHERE id = %s", (db.property_id,)
        ).fetchone()
    assert row is not None
    return ZoneInfo(row[0])


def next_weekday(after: date, days: int) -> date:
    day = after + timedelta(days=days)
    return day + timedelta(days=1) if day.isoweekday() == 7 else day


def add_inquiry(db: TelegramDatabase, user: int, relay: str, **changes: Any) -> str:
    message = inbound(db, user, relay, phone=phone_of(user))
    today = date.fromisoformat(
        run(db.runtime_url, CHOICES, db.property_id, user, db.owner)["today"]
    )
    run(
        db.runtime_url, INQUIRY, db.property_id, message, user, user, "en",
        request(today, **changes), db.owner,
    )  # fmt: skip
    return str(card_of(db, user)["id"])


def phone_of(user: int) -> str:
    return f"+855128{user % 1000000:06d}"


def card_of(db: TelegramDatabase, user: int, actor: Any = None) -> dict[str, Any]:
    page = run(db.runtime_url, PAGE, db.property_id, actor or db.owner)
    shown = [row for row in page["requests"] if row["phone"] == phone_of(user)]
    return dict(shown[-1])


def act(db: TelegramDatabase, request_id: str, action: str, actor: Any, **body: Any) -> Any:
    return run(db.runtime_url, ACT, db.property_id, request_id, action, json.dumps(body), actor)


def refuse(
    db: TelegramDatabase, state: str, request_id: str, action: str, actor: Any, **body: Any
) -> None:
    refused(db.runtime_url, state, ACT, db.property_id, request_id, action, json.dumps(body), actor)


def add_event(db: TelegramDatabase, request_id: str, kind: str, **columns: Any) -> None:
    names = ["request_id", "kind", "created_by", *columns]
    values = [request_id, kind, db.owner, *columns.values()]
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            f"INSERT INTO app.visit_request_events ({', '.join(names)}) "
            f"VALUES ({', '.join(['%s'] * len(values))})",
            values,
        )


def test_take_call_book_visit_and_close(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    here = zone(db)
    sokha = 960001
    first = add_inquiry(db, sokha, "item-work-1", contact_by="TELEGRAM")
    card = card_of(db, sokha)
    assert card["status"] == "NEW" and card["staff"] is None and card["late"] is False
    page = run(db.runtime_url, PAGE, db.property_id, db.staff)
    assert page["can_work"] is True and page["can_manage"] is False
    assert page["address"] and page["me"] == str(db.staff)
    assert {worker["id"] for worker in page["workers"]} >= {str(db.staff), str(db.manager)}
    manager_page = run(db.runtime_url, PAGE, db.property_id, db.manager)
    assert manager_page["can_manage"] is True

    # Take first; one person at a time; a Manager gives it to another person.
    refuse(db, "55000", first, "CALL", db.staff, answered=True)
    act(db, first, "TAKE", db.staff)
    refuse(db, "55000", first, "TAKE", db.manager)
    refuse(db, "42501", first, "GIVE", db.staff, staff_id=str(db.manager))
    refuse(db, "22023", first, "GIVE", db.manager)
    act(db, first, "GIVE", db.manager, staff_id=str(db.manager))
    assert card_of(db, sokha)["staff_id"] == str(db.manager)
    act(db, first, "GIVE", db.manager, staff_id=str(db.staff))
    mine = card_of(db, sokha, db.staff)
    assert mine["mine"] is True and mine["staff_id"] == str(db.staff)

    # Calls: no answer keeps it New; an answer makes it Contacted.
    refuse(db, "55000", first, "BOOK", db.staff, visit_at="2030-01-07T10:00")
    refuse(db, "22023", first, "CALL", db.staff)
    act(db, first, "CALL", db.staff, answered=False)
    assert card_of(db, sokha)["status"] == "NEW"
    act(db, first, "CALL", db.staff, answered=True, note="Wants to come on Monday.")
    card = card_of(db, sokha)
    assert card["status"] == "CONTACTED" and card["calls"] == 2

    # A visit: from now, Monday to Saturday, 07:00 to 17:00.
    now = datetime.now(here)
    day = next_weekday(now.date(), 2)
    sunday = now.date() + timedelta(days=(7 - now.date().isoweekday()) or 7)
    for wrong in (
        f"{sunday}T10:00",
        f"{day}T17:30",
        f"{day}T06:30",
        f"{now.date() - timedelta(days=1)}T10:00",
        "tomorrow",
    ):
        refuse(db, "22023", first, "BOOK", db.staff, visit_at=wrong)
    refuse(
        db, "22023", first, "BOOK", db.staff, visit_at=f"{day}T10:00", staff_id=str(uuid.uuid4())
    )
    act(db, first, "BOOK", db.staff, visit_at=f"{day}T10:00")
    card = card_of(db, sokha)
    assert card["status"] == "VISIT_BOOKED" and card["visit_local"] == f"{day}T10:00"
    assert card["to_send"] == []  # The bot sends it.
    refuse(db, "55000", first, "VISITED", db.staff)
    refuse(db, "55000", first, "SPAM", db.manager, note="Not a person")
    act(db, first, "BOOK", db.staff, visit_at=f"{day}T14:30", staff_id=str(db.manager))
    with psycopg.connect(db.owner_url) as connection:
        sent = connection.execute(
            "SELECT text_code, details, keyboard FROM app.telegram_outbox "
            "WHERE chat_id = %s ORDER BY created_at",
            (sokha,),
        ).fetchall()
    assert [(code, keyboard) for code, _, keyboard in sent] == [
        ("customer.visit_booked", "customer.menu"),
        ("customer.visit_moved", "customer.menu"),
    ]
    details = sent[1][1]
    assert details["time"] == "14:30" and details["day"].endswith(f"{day:%d/%m/%Y}")
    assert details["day"].split()[0] == f"{day:%A}" and details["address"]
    assert card_of(db, sokha)["visit_staff"] is not None

    # The visit day comes (a booking for today, as if made earlier).
    today_visit = datetime.now(here).replace(second=0, microsecond=0)
    add_event(db, first, "VISIT_BOOKED", staff_id=db.staff, visit_at=today_visit)
    act(db, first, "VISITED", db.staff)
    assert card_of(db, sokha)["status"] == "VISITED"

    # Close with a reason; Could not reach needs no answer on 3 days.
    refuse(db, "22023", first, "CLOSE", db.staff, reason="BORED")
    refuse(db, "22023", first, "CLOSE", db.staff, reason="OTHER")
    refuse(db, "55000", first, "CLOSE", db.staff, reason="NO_REACH")
    act(db, first, "CLOSE", db.staff, reason="PRICE", note="Too high for now.")
    card = card_of(db, sokha)
    assert card["status"] == "CLOSED" and card["reason"] == "PRICE"
    assert card["close_note"] == "Too high for now."
    refuse(db, "55000", first, "CALL", db.staff, answered=True)

    # A closed request does not take new inquiries: the person starts a new one.
    second = add_inquiry(db, sokha, "item-work-2", contact_by="TELEGRAM")
    assert second != first and card_of(db, sokha)["status"] == "NEW"

    # Reopen with a note, by the person who had it or a Manager.
    refuse(db, "22023", first, "REOPEN", db.staff)
    act(db, first, "REOPEN", db.staff, note="Asked again by phone.")
    detail = run(db.runtime_url, DETAIL, db.property_id, first, db.staff)
    assert detail["status"] == "CONTACTED"
    assert [step["kind"] for step in detail["history"]] == [
        "TAKEN", "GIVEN", "GIVEN", "CALL", "CALL", "VISIT_BOOKED", "VISIT_BOOKED",
        "VISIT_BOOKED", "VISITED", "CLOSED", "REOPENED",
    ]  # fmt: skip
    assert detail["history"][5]["sent_by_bot"] is True

    # Steps are kept as they are.
    refused(db.owner_url, "55000", "UPDATE app.visit_request_events SET note = 'x' RETURNING 1")


def test_send_by_hand_reminders_spam_and_could_not_reach(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    here = zone(db)
    chenda, spam, quiet = 960011, 960012, 960013
    by_email = add_inquiry(db, chenda, "item-work-11")
    act(db, by_email, "TAKE", db.staff)
    act(db, by_email, "CALL", db.staff, answered=True)
    day = next_weekday(datetime.now(here).date(), 3)
    act(db, by_email, "BOOK", db.staff, visit_at=f"{day}T09:00")
    assert card_of(db, chenda)["to_send"] == ["CONFIRMATION"]
    refuse(db, "55000", by_email, "SENT", db.staff, what="LETTER")
    act(db, by_email, "SENT", db.staff, what="CONFIRMATION")
    assert card_of(db, chenda)["to_send"] == []

    # The reminder at 08:00 the day before: Telegram sends it; others are sent by hand.
    tomorrow = datetime.now(here).date() + timedelta(days=1)
    visit = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, tzinfo=here)
    add_event(db, by_email, "VISIT_BOOKED", staff_id=db.staff, visit_at=visit)
    refused(db.runtime_url, "42501", REMIND, db.property_id, db.staff)
    due = run(db.runtime_url, REMIND, db.property_id, db.owner)
    if datetime.now(here).hour >= 8:
        assert due == 1
        assert card_of(db, chenda)["to_send"] == ["CONFIRMATION", "REMINDER"]
        assert run(db.runtime_url, REMIND, db.property_id, db.owner) == 0
        act(db, by_email, "SENT", db.staff, what="REMINDER")
        assert card_of(db, chenda)["to_send"] == ["CONFIRMATION"]
    else:
        assert due == 0
    # The customer cancels.
    act(db, by_email, "CLOSE", db.staff, reason="CANCELLED")
    assert card_of(db, chenda)["reason"] == "CANCELLED"

    # Spam: a Manager, with a note; only a Manager reopens it.
    junk = add_inquiry(db, spam, "item-work-12")
    refuse(db, "42501", junk, "SPAM", db.staff, note="Advert")
    refuse(db, "22023", junk, "SPAM", db.manager)
    act(db, junk, "SPAM", db.manager, note="Advert")
    assert card_of(db, spam)["status"] == "SPAM"
    refuse(db, "42501", junk, "REOPEN", db.staff, note="Real person")
    act(db, junk, "REOPEN", db.manager, note="Real person")
    assert card_of(db, spam)["status"] == "NEW"

    # Could not reach: no answer on 3 different days.
    silent = add_inquiry(db, quiet, "item-work-13")
    act(db, silent, "TAKE", db.staff)
    act(db, silent, "CALL", db.staff, answered=False)
    act(db, silent, "CALL", db.staff, answered=False)
    refuse(db, "55000", silent, "CLOSE", db.staff, reason="NO_REACH")
    for days_ago in (1, 2):
        with psycopg.connect(db.owner_url) as connection:
            connection.execute(
                "INSERT INTO app.visit_request_events (request_id, kind, answered, created_at, "
                "created_by) VALUES (%s, 'CALL', false, clock_timestamp() - %s * interval '1 day', "
                "%s)",
                (silent, days_ago, db.owner),
            )
    assert card_of(db, quiet)["no_answer_days"] == 3
    act(db, silent, "CLOSE", db.staff, reason="NO_REACH")
    assert card_of(db, quiet)["status"] == "CLOSED"


def test_working_minutes_and_late(telegram_database: TelegramDatabase) -> None:
    db = telegram_database
    minutes = (
        "SELECT app.visit_working_minutes(%s::timestamptz, %s::timestamptz, 'Asia/Phnom_Penh')"
    )
    # Saturday 16:00 to Monday 08:00: one hour each side of Sunday.
    assert run(db.owner_url, minutes, "2026-11-07T16:00+07", "2026-11-09T08:00+07") == 120
    assert run(db.owner_url, minutes, "2026-11-09T06:00+07", "2026-11-09T18:00+07") == 600
    assert run(db.owner_url, minutes, "2026-11-09T10:00+07", "2026-11-09T09:00+07") == 0
    # A request waiting more than 2 working hours with nobody taking it is Late.
    late = add_inquiry(db, 960021, "item-work-21")
    with psycopg.connect(db.owner_url) as connection:
        connection.execute("ALTER TABLE app.visit_requests DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.visit_requests SET received_at = received_at - interval '5 days' "
            "WHERE id = %s",
            (late,),
        )
        connection.execute("ALTER TABLE app.visit_requests ENABLE TRIGGER USER")
    card = card_of(db, 960021)
    assert card["late"] is True and card["waiting_minutes"] > 120
    act(db, late, "TAKE", db.staff)
    assert card_of(db, 960021)["late"] is False
