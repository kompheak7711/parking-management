"""Database review fixes of 7 Nov 2026 (DL-202 (D), migration 20270707_372): after an early
check-out the weekly report counts the Unit's nights only up to the day the guest left (owner
7 Nov 2026 20:58), while the money stays as DL-200 says.
"""

from __future__ import annotations

import json
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
    run,
    short_stay_database,
)
from test_short_stay_check_in_migration import (
    BILL,
    CHECK_IN,
    DEPOSIT,
    TICKS,
    guest_with_id,
    pay,
    read,
)
from test_short_stay_week_report_migration import REPORT, row

REVISION = "20270707_372"
LEAVE = (
    "UPDATE app.short_stay_bookings SET status = 'CHECKED_OUT', checked_out_by = %s, "
    "version = version + 1, checked_out_at = (%s::date + time '10:00') AT TIME ZONE "
    "(SELECT timezone_name FROM app.properties WHERE id = %s) WHERE id = %s"
)


@pytest.fixture(scope="module")
def early_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_v12_early_check_out") as database:
        yield database


def paid_booking(db: BookingDatabase, guest: Any, start: int, nights: int) -> str:
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.studio, start, nights, customer_id=str(guest)),
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, read(db, made)["version"], db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], billed["invoice"]["due_usd_cents"])
    return str(made)


def test_migration_372_follows_371_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270706_371"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_an_early_check_out_frees_the_nights_but_keeps_the_money(
    early_database: BookingDatabase,
) -> None:
    db = early_database
    guest = guest_with_id(db)
    # Three paid nights from today; the guest checks in today.
    made = paid_booking(db, guest, 0, 3)
    run(db.runtime_url, CHECK_IN, db.property_id, made, TICKS, read(db, made)["version"], db.staff)
    total = read(db, made)["total_usd_cents"]
    # The guest leaves tomorrow morning, two nights early. (The desk's check-out stamps the real
    # time; the test writes that stamp itself because it cannot wait a day.)
    with psycopg.connect(db.owner_url) as owner:
        owner.execute(LEAVE, (db.staff, db.today + timedelta(days=1), db.property_id, made))
        owner.commit()
    assert read(db, made)["status"] == "CHECKED_OUT"

    report = run(db.runtime_url, REPORT, db.property_id, db.today, db.manager)
    studio = row(report, "U501")
    assert studio["nights"] == 1, "only the night slept counts"
    assert studio["income_usd_cents"] == total, "the money for the unused nights stays (DL-200)"

    # The two freed nights are sold again to another guest, who pays: the Unit shows three
    # nights in the week, not five.
    paid_booking(db, db.guest, 1, 2)
    report = run(db.runtime_url, REPORT, db.property_id, db.today, db.manager)
    studio = row(report, "U501")
    assert studio["nights"] == 3
    assert report["totals"]["nights"] == 3
    assert report["totals"]["occupancy_points"] == 3 * 10000 // (report["totals"]["units"] * 7)
