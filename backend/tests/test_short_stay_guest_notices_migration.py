"""Short-stay guest notices on the real database (migration 414, DL-238).

Owner (14 Nov 2026, "Yes, build all four"): the check-out reminder at 18:00 the evening before,
the late check-out notice 30 minutes after the time to leave, the house-rule warnings staff write
(1, then the final 2), and a charge still unpaid on a later day. Each goes to the booking's
Telegram links; a guest with no link is told in person.

The automatic notices are recorded for a chosen moment (``app.short_stay_notices_record``), so the
tests do not depend on the time they run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)
from test_short_stay_check_in_migration import BILL, CHECK_IN, DEPOSIT, TICKS, guest_with_id, pay
from test_short_stay_cleaning_migration import EXTEND, FEE

REVISION = "20270727_414"
READ = "SELECT app.short_stay_booking_read(%s, %s, %s)"
RECORD = "SELECT app.short_stay_notices_record(%s, %s, %s)"
SEND = "SELECT app.short_stay_notice_send(%s, %s)"
RUN = "SELECT app.short_stay_notices_run(%s, %s)"
WARN = "SELECT app.give_short_stay_warning(%s, %s, %s::jsonb, %s, NULL)"
TOLD = "SELECT app.short_stay_notice_told(%s, %s, %s, NULL)"
PAGE = "SELECT app.short_stay_notices_page(%s, %s)"
GUEST_A, GUEST_C = 7_414_001, 7_414_003


@pytest.fixture(scope="module")
def notice_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_guest_notices") as database:
        yield database


def check_in(db: BookingDatabase, unit: uuid.UUID, nights: int, *, late: bool = False) -> str:
    """A paid stay from today, checked in. ``late`` adds late check-out before billing."""
    guest = guest_with_id(db)
    made = str(
        run(
            db.runtime_url,
            BOOK,
            db.property_id,
            booking(db, unit, 0, nights, customer_id=str(guest)),
            db.staff,
        )
    )
    version = run(db.runtime_url, READ, db.property_id, made, db.staff)["version"]
    if late:
        version = run(db.runtime_url, FEE, db.property_id, made, "LATE_CHECK_OUT", version,
                      db.staff)["version"]  # fmt: skip
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, version, db.staff)
    invoice = billed["invoice"]
    pay(db, guest, invoice["invoice_id"], invoice["total_usd_cents"])
    version = run(db.runtime_url, READ, db.property_id, made, db.staff)["version"]
    inside = run(db.runtime_url, CHECK_IN, db.property_id, made, TICKS, version, db.staff)
    assert inside["status"] == "CHECKED_IN"
    return made


def link(db: BookingDatabase, made: str, user: int, language: str = "km") -> None:
    """The guest scanned the check-in QR (DL-214)."""
    with psycopg.connect(db.owner_url) as connection:
        stay = connection.execute(
            "SELECT customer_id, unit_id FROM app.short_stay_bookings WHERE id = %s", (made,)
        ).fetchone()
        assert stay is not None
        connection.execute(
            "INSERT INTO app.tenant_telegram_links (property_id, telegram_user_id, customer_id, "
            "unit_id, booking_id, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (db.property_id, user, stay[0], stay[1], made, db.manager),
        )
        connection.execute(
            "INSERT INTO app.telegram_language_choices (bot_code, telegram_user_id, language, "
            "created_by) VALUES ('TENANT', %s, %s, %s)",
            (user, language, db.manager),
        )


def at(db: BookingDatabase, day: date, clock: str) -> Any:
    """That moment in the Property's time zone."""
    return run(
        db.owner_url,
        "SELECT timezone(property.timezone_name, %s::date + %s::time) "
        "FROM app.properties AS property WHERE property.id = %s",
        day,
        clock,
        db.property_id,
    )


def record(db: BookingDatabase, day: date, clock: str) -> int:
    return int(run(db.owner_url, RECORD, db.property_id, at(db, day, clock), db.manager))


def notices(db: BookingDatabase, made: str) -> list[tuple[str, str, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT kind, text_code, details FROM app.short_stay_guest_notices "
            "WHERE booking_id = %s ORDER BY created_at, id",
            (made,),
        ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def notice_id(db: BookingDatabase, made: str, kind: str) -> str:
    return str(
        run(
            db.owner_url,
            "SELECT id FROM app.short_stay_guest_notices WHERE booking_id = %s AND kind = %s "
            "ORDER BY created_at DESC LIMIT 1",
            made,
            kind,
        )
    )


def outbox(db: BookingDatabase, user: int) -> list[tuple[str, str, dict[str, Any]]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT text_code, language, details FROM app.telegram_outbox "
            "WHERE bot_code = 'TENANT' AND chat_id = %s ORDER BY created_at, id",
            (user,),
        ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


@pytest.fixture(scope="module")
def stays(notice_database: BookingDatabase) -> dict[str, str]:
    db = notice_database
    found = {
        # Two nights, linked in English; eight nights (late check-out free), not linked; three
        # nights with late check-out added, linked in Khmer.
        "a": check_in(db, db.studio, 2),
        "b": check_in(db, db.one_bedroom, 8),
        "c": check_in(db, db.two_bedroom, 3, late=True),
    }
    link(db, found["a"], GUEST_A, "en")
    link(db, found["c"], GUEST_C)
    return found


def test_migration_414_follows_the_ui_v81_join_403() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270728_405"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_check_out_reminder_goes_at_18_00_the_evening_before(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    eve_a = db.today + timedelta(days=1)
    assert record(db, eve_a, "17:59") == 0
    assert record(db, eve_a, "18:05") == 1
    assert record(db, eve_a, "18:40") == 0  # once a day
    [(kind, code, details)] = notices(db, stays["a"])
    assert (kind, code) == ("CHECK_OUT_REMINDER", "tenant.ss_check_out")
    assert details == {
        "unit": "U501",
        "date": (db.today + timedelta(days=2)).strftime("%d/%m/%Y"),
        "time": "12:00",
        "until": "18:00",
        "fee": "$5.00",
    }
    assert run(db.owner_url, SEND, notice_id(db, stays["a"], "CHECK_OUT_REMINDER"), db.manager) == 1
    assert run(db.owner_url, SEND, notice_id(db, stays["a"], "CHECK_OUT_REMINDER"), db.manager) == 0
    assert outbox(db, GUEST_A) == [("tenant.ss_check_out", "en", details)]
    # From 7 nights late check-out is free; with late check-out added it names the later time.
    assert record(db, db.today + timedelta(days=7), "18:05") == 1
    assert notices(db, stays["b"])[0][1] == "tenant.ss_check_out_free"


def test_the_late_check_out_notice_comes_30_minutes_after_the_time_to_leave(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    out_a, out_c = db.today + timedelta(days=2), db.today + timedelta(days=3)
    assert record(db, out_a, "12:29") == 0
    assert record(db, out_a, "12:31") == 1
    late = notices(db, stays["a"])[-1]
    assert late == ("LATE_CHECK_OUT", "tenant.ss_late", {"unit": "U501", "time": "12:00"})
    # The same evening C, with late check-out added, gets its reminder with the later time.
    assert record(db, out_a, "18:05") == 1
    assert notices(db, stays["c"])[0][1] == "tenant.ss_check_out_late"
    # Never at night: a run after 22:00 records nothing.
    assert record(db, out_a, "22:00") == 0
    # Late check-out added: the time to leave is 18:00.
    assert record(db, out_c, "12:31") == 0
    assert record(db, out_c, "18:31") == 1
    assert notices(db, stays["c"])[-1][2] == {"unit": "U505", "time": "18:00"}
    # No money is added: the stays keep their price.
    found = run(db.runtime_url, READ, db.property_id, stays["a"], db.staff)
    assert found["total_usd_cents"] == found["invoice"]["total_usd_cents"]
    assert found["extra_invoices"] == []


def test_staff_give_warning_1_then_the_final_warning_2(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    body = json.dumps({"reason": "Loud music after 22:00."})
    first = run(db.runtime_url, WARN, db.property_id, stays["a"], body, db.staff)
    assert (first["warning_number"], first["telegram_messages"]) == (1, 1)
    final = run(db.runtime_url, WARN, db.property_id, stays["a"],
                json.dumps({"reason": "  Smoking in the room.  "}), db.staff)  # fmt: skip
    assert final["warning_number"] == 2
    sent = [(code, fields["text"]) for code, _, fields in outbox(db, GUEST_A)[-2:]]
    assert sent == [
        ("tenant.ss_warning_1", "Loud music after 22:00."),
        ("tenant.ss_warning_2", "Smoking in the room."),
    ]
    assert "final warning" in refused(
        db.runtime_url, "55000", WARN, db.property_id, stays["a"], body, db.staff
    )
    for wrong in ('{"reason": "   "}', '{"reason": 3}', '{"reason": "x", "more": 1}'):
        refused(db.runtime_url, "22023", WARN, db.property_id, stays["b"], wrong, db.staff)
    history = run(db.runtime_url, READ, db.property_id, stays["a"], db.staff)["history"]
    assert [event["note"] for event in history if event["kind"] == "HOUSE_RULE_WARNING"] == [
        "Loud music after 22:00.",
        "Smoking in the room.",
    ]
    # Only a guest who is checked in.
    booked = run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 20, 2), db.staff)
    assert "checked in" in refused(
        db.runtime_url, "55000", WARN, db.property_id, booked, body, db.staff
    )


def test_a_charge_still_unpaid_on_a_later_day(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    version = run(db.runtime_url, READ, db.property_id, stays["b"], db.staff)["version"]
    out = json.dumps({"check_out_on": str(db.today + timedelta(days=9))})
    longer = run(db.runtime_url, EXTEND, db.property_id, stays["b"], out, version, db.staff)
    extra = longer["extra_invoices"][0]
    assert extra["status"] == "UNPAID"
    # Not on the day it was added; from 09:00 the day after; once.
    assert record(db, db.today, "20:00") == 0
    tomorrow = db.today + timedelta(days=1)
    assert record(db, tomorrow, "08:59") == 0
    assert record(db, tomorrow, "09:05") == 1
    assert record(db, tomorrow, "10:00") == 0
    [(code, details)] = [(c, d) for k, c, d in notices(db, stays["b"]) if k == "UNPAID_CHARGE"]
    assert code == "tenant.ss_unpaid"
    assert details["invoice"] == extra["invoice_number"]
    assert details["amount"] == f"${extra['total_usd_cents'] / 100:,.2f}"


def test_the_notices_page_and_a_guest_told_in_person(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    page = run(db.runtime_url, PAGE, db.property_id, db.staff)
    rows = {(row["booking_id"], row["kind"]): row for row in page["notices"]}
    reminder_b = rows[(stays["b"], "CHECK_OUT_REMINDER")]
    # B has no Telegram: the desk tells the guest in person.
    assert reminder_b["telegram"] == "NO_TELEGRAM" and reminder_b["told_at"] is None
    assert reminder_b["automatic"] is True and reminder_b["given_by_name"] is None
    assert rows[(stays["a"], "CHECK_OUT_REMINDER")]["telegram"] == "WAITING"
    warning = next(row for row in page["notices"] if row["warning_number"] == 2)
    assert warning["reason"] == "Smoking in the room." and warning["automatic"] is False
    assert warning["given_by_name"]
    assert {stay["booking_id"]: stay["warnings"] for stay in page["stays"]} == {
        stays["a"]: 2,
        stays["b"]: 0,
        stays["c"]: 0,
    }
    assert {stay["booking_id"]: stay["telegram"] for stay in page["stays"]}[stays["b"]] is False
    assert page["rules"] == {
        "days": 90,
        "reminder_at": "18:00",
        "late_after_minutes": 30,
        "unpaid_at": "09:00",
    }
    told = run(db.runtime_url, TOLD, db.property_id, reminder_b["notice_id"], db.staff)
    again = next(row for row in told["notices"] if row["notice_id"] == reminder_b["notice_id"])
    assert again["told_at"] is not None and again["told_by_name"]
    assert "already" in refused(
        db.runtime_url, "55000", TOLD, db.property_id, reminder_b["notice_id"], db.staff
    )
    refused(db.runtime_url, "22023", TOLD, db.property_id, str(uuid.uuid4()), db.staff)


def test_the_pull_job_runs_the_notices_with_the_telegram_right(
    notice_database: BookingDatabase, stays: dict[str, str]
) -> None:
    db = notice_database
    # The pull job's account (telegram.operate) runs it; it records what is due now (which
    # depends on the time the test runs) and sends what was not sent yet.
    before = len(outbox(db, GUEST_C))
    assert run(db.runtime_url, RUN, db.property_id, db.manager) >= 2
    assert len(outbox(db, GUEST_C)) >= before + 2
    refused(db.runtime_url, "42501", RUN, db.property_id, db.staff)
    # The tables are never changed.
    with psycopg.connect(db.owner_url) as connection, pytest.raises(psycopg.Error):
        connection.execute("DELETE FROM app.short_stay_guest_notices")
