"""Daily and weekly rent: daily cleaning, early and late fees, extend a stay (migration 313).

Daily and weekly guests are cleaned every morning they stay. Early check-in and late check-out
cost $5, free from 7 nights. An extension prices the whole stay again; once the stay is billed, a
fee or an extension is its own Invoice, and the stay is paid only when every Invoice is.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
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
from test_short_stay_check_in_migration import (
    BILL,
    CHECK_IN,
    CHECK_OUT,
    DEPOSIT,
    TICKS,
    guest_with_id,
    pay,
    read,
)

REVISION = "20270603_313"
FEE = "SELECT app.add_short_stay_fee(%s, %s, %s, %s, %s, NULL)"
EXTEND = "SELECT app.extend_short_stay(%s, %s, %s::jsonb, %s, %s, NULL)"
LIST = "SELECT app.short_stay_housekeeping(%s, %s, %s)"
FINISH = "SELECT app.finish_housekeeping_task(%s, %s, %s::jsonb, %s, NULL)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_cleaning") as database:
        yield database


def out_on(db: BookingDatabase, days: int) -> str:
    return json.dumps({"check_out_on": str(db.today + timedelta(days=days))})


def cleans(found: dict[str, Any]) -> list[tuple[str, str]]:
    return [(clean["task_on"], clean["status"]) for clean in found["cleans"]]


def test_migration_313_follows_step_3() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270602_312"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_fees_cleaning_and_extending_a_stay(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest = guest_with_id(db)
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.studio, 0, 3, customer_id=str(guest)),
        db.staff,
    )
    found = read(db, made)
    assert (found["total_usd_cents"], found["fee_usd_cents"]) == (6090, 500)
    assert (found["check_in_time"], found["late_check_out_until"]) == (840, 1080)
    # Before billing, the early check-in is a price line of the one Invoice.
    early = run(db.runtime_url, FEE, db.property_id, made, "EARLY_CHECK_IN", 1, db.staff)
    assert early["total_usd_cents"] == 6590 and early["early_check_in"] is True
    assert [line["kind"] for line in early["lines"]] == ["NIGHTS", "EARLY_CHECK_IN"]
    assert "already" in refused(
        db.runtime_url,
        "55000",
        FEE,
        db.property_id,
        made,
        "EARLY_CHECK_IN",
        early["version"],
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, early["version"], db.staff)
    assert billed["invoice"]["total_usd_cents"] == 6590 and billed["extra_invoices"] == []
    pay(db, guest, billed["invoice"]["invoice_id"], 6590)
    inside = run(
        db.runtime_url, CHECK_IN, db.property_id, made, TICKS, read(db, made)["version"], db.staff
    )
    # A clean each morning the guest stays: the 2 days after check-in.
    day = [str(db.today + timedelta(days=n)) for n in range(9)]
    assert cleans(inside) == [(day[1], "TO_DO"), (day[2], "TO_DO")]
    tomorrow = run(db.runtime_url, LIST, db.property_id, day[1], db.staff)
    task = tomorrow["tasks"][0]
    assert (task["kind"], task["unit_number"], task["guest_name"]) == (
        "DAILY_CLEAN",
        "U501",
        "Meas Rina",
    )
    assert "not due" in refused(
        db.runtime_url, "55000", FINISH, db.property_id, task["task_id"], "{}", db.staff
    )
    # Extend from 3 to 6 nights: priced again with the fee kept; the difference is an Invoice.
    longer = run(
        db.runtime_url, EXTEND, db.property_id, made, out_on(db, 6), inside["version"], db.staff
    )
    assert longer["total_usd_cents"] == 6 * 2030 + 500
    extra = longer["extra_invoices"][0]
    assert (extra["kind"], extra["total_usd_cents"], extra["status"]) == ("EXTEND", 6090, "UNPAID")
    assert longer["payment"] == "UNPAID"
    assert [when for when, _ in cleans(longer)] == day[1:6]
    # 7 nights cost one week: $139.00 + the fee.
    week = run(
        db.runtime_url, EXTEND, db.property_id, made, out_on(db, 7), longer["version"], db.staff
    )
    assert [line["kind"] for line in week["lines"]] == ["WEEKS", "EARLY_CHECK_IN"]
    assert week["total_usd_cents"] == 13900 + 500
    assert week["extra_invoices"][1]["total_usd_cents"] == 1720
    # From 7 nights the late check-out is free: no line and no Invoice.
    late = run(
        db.runtime_url, FEE, db.property_id, made, "LATE_CHECK_OUT", week["version"], db.staff
    )
    assert late["late_check_out"] is True and late["fee_usd_cents"] == 0
    assert late["total_usd_cents"] == week["total_usd_cents"]
    assert len(late["extra_invoices"]) == 2
    # The added nights must be free.
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 7, 1), db.staff)
    assert "BOOKED" in refused(
        db.runtime_url,
        "55000",
        EXTEND,
        db.property_id,
        made,
        out_on(db, 9),
        late["version"],
        db.staff,
    )
    refused(db.runtime_url, "40001", EXTEND, db.property_id, made, out_on(db, 8), 1, db.staff)
    refused(
        db.runtime_url,
        "22023",
        EXTEND,
        db.property_id,
        made,
        out_on(db, 7),
        late["version"],
        db.staff,
    )
    # A clean due today: done, or skipped only with a reason.
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind, "
            "created_by) VALUES (%s, %s, %s, %s, 'DAILY_CLEAN', %s)",
            (db.property_id, db.studio, made, db.today, db.staff),
        )
    today = run(db.runtime_url, LIST, db.property_id, day[0], db.staff)
    due = today["tasks"][0]["task_id"]
    refused(db.runtime_url, "22023", FINISH, db.property_id, due, '{"skip": true}', db.staff)
    done = run(
        db.runtime_url,
        FINISH,
        db.property_id,
        due,
        json.dumps({"skip": True, "note": "Do not disturb"}),
        db.staff,
    )
    assert (done["tasks"][0]["status"], done["tasks"][0]["note"]) == ("SKIPPED", "Do not disturb")
    # An early check-out leaves the later cleans skipped.
    left = run(db.runtime_url, CHECK_OUT, db.property_id, made, late["version"], db.staff)
    assert {status for _, status in cleans(left)} == {"SKIPPED"}
    assert left["cleans"][-1]["note"] == "The guest checked out"
    room = run(db.runtime_url, LIST, db.property_id, day[0], db.staff)["tasks"][0]
    assert room["kind"] == "ROOM_CHECK"
    assert "booking page" in refused(
        db.runtime_url, "55000", FINISH, db.property_id, room["task_id"], "{}", db.staff
    )
    refused(
        db.runtime_url,
        "55000",
        EXTEND,
        db.property_id,
        made,
        out_on(db, 8),
        left["version"],
        db.staff,
    )
    assert [event["kind"] for event in left["history"]] == [
        "BOOKED",
        "EARLY_CHECK_IN",
        "DEPOSIT_TAKEN",
        "BILLED",
        "CHECKED_IN",
        "EXTENDED",
        "EXTENDED",
        "LATE_CHECK_OUT",
        "CHECKED_OUT",
    ]


def test_a_booked_stay_extends_without_an_invoice(stay_database: BookingDatabase) -> None:
    db = stay_database
    made = run(db.runtime_url, BOOK, db.property_id, booking(db, db.one_bedroom, 10, 2), db.staff)
    first = read(db, made)
    longer = run(
        db.runtime_url, EXTEND, db.property_id, made, out_on(db, 13), first["version"], db.staff
    )
    assert (longer["nights"], longer["extra_invoices"], longer["cleans"]) == (3, [], [])
    assert longer["total_usd_cents"] > first["total_usd_cents"]
    # An early check-in is only before the guest is in, and a fee kind must be known.
    refused(
        db.runtime_url, "22023", FEE, db.property_id, made, "PARKING", longer["version"], db.staff
    )
    the_unit = uuid.UUID(longer["unit_id"])
    assert the_unit == db.one_bedroom
