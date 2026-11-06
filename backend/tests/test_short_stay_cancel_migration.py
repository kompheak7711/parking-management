"""Daily and weekly rent: cancel, no-show and late-cancel credit (migration 20270604_314).

Free until 23:59 two days before check-in: the money paid becomes Customer Credit, which the desk
pays back on the usual Refund of Credit. Later, or a no-show: no refund, and what was not paid is
no longer owed. The Owner, the Manager or the credit right may then turn some or all of the kept
money into credit for 12 months, once. The deposit always comes back.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

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
from test_short_stay_check_in_migration import BILL, DEPOSIT, ON_SITE, guest_with_id, pay, read

REVISION = "20270604_314"
CANCEL = "SELECT app.cancel_short_stay(%s, %s, %s::jsonb, %s, %s, NULL)"
CREDIT = "SELECT app.give_short_stay_credit(%s, %s, %s::jsonb, %s, NULL)"
WHY = json.dumps({"reason": "Flight changed"})


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_cancel") as database:
        yield database


def credit_of(db: BookingDatabase, customer: uuid.UUID) -> int:
    return int(
        run(
            db.owner_url,
            "SELECT COALESCE(sum(recognized_usd_cents), 0) FROM app.customer_credits "
            "WHERE customer_id = %s",
            customer,
        )
    )


def paid_stay(db: BookingDatabase, unit: uuid.UUID, start: int) -> tuple[uuid.UUID, str]:
    guest = guest_with_id(db)
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, start, 2, customer_id=str(guest)),
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, read(db, made)["version"], db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], billed["total_usd_cents"])
    return guest, made


def test_migration_314_follows_step_4a() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270603_313"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_free_cancel_gives_the_money_back_as_credit(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest, made = paid_stay(db, db.studio, 10)
    found = read(db, made)
    assert found["paid_usd_cents"] == 4640
    # Free until 23:59 two days before the check-in day (day 10).
    assert date.fromisoformat(found["free_cancel_until"]) == db.today + timedelta(days=8)
    refused(db.runtime_url, "22023", CANCEL, db.property_id, made, "{}", found["version"], db.staff)
    # A no-show is only from the check-in day.
    refused(
        db.runtime_url,
        "55000",
        CANCEL,
        db.property_id,
        made,
        json.dumps({"reason": "Did not come", "no_show": True}),
        found["version"],
        db.staff,
    )
    cancelled = run(db.runtime_url, CANCEL, db.property_id, made, WHY, found["version"], db.staff)
    assert cancelled["status"] == "CANCELLED" and cancelled["cancel_reason"] == "Flight changed"
    cancel = cancelled["cancellation"]
    assert (cancel["free"], cancel["back_usd_cents"], cancel["kept_usd_cents"]) == (True, 4640, 0)
    assert cancelled["deposit"]["status"] == "RETURNED"
    assert credit_of(db, guest) == 4640
    # Owner test 06/11/2026: the booking shows what the Refund button gives back.
    assert cancelled["refund"]["left_usd_cents"] == 4640
    assert cancelled["refund"]["waiting_usd_cents"] == 0
    assert cancelled["refund"]["refunded_usd_cents"] == 0
    [source] = cancelled["refund"]["credits"]
    assert source["left_usd_cents"] == 4640
    with psycopg.connect(db.owner_url) as connection:
        method = connection.execute(
            "SELECT id FROM app.refund_methods WHERE active ORDER BY code LIMIT 1"
        ).fetchone()
        assert method is not None
        connection.execute(
            "SELECT app.record_refund_draft(%s,%s,%s,'USD','CREDIT',%s,NULL,%s,%s,%s,%s,%s)",
            (
                db.property_id,
                db.manager,
                uuid.uuid4(),
                source["credit_id"],
                4640,
                "Free cancel",
                method[0],
                "Cash at the desk",
                "refunds.create",
            ),
        )
    waiting = read(db, made)["refund"]
    assert (waiting["left_usd_cents"], waiting["waiting_usd_cents"]) == (4640, 4640)
    # Free cancel gives no extra credit; the nights are free again.
    refused(
        db.runtime_url,
        "55000",
        CREDIT,
        db.property_id,
        made,
        json.dumps({"amount_usd_cents": 100, "note": "x"}),
        db.manager,
    )
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 10, 2), db.staff)
    refused(
        db.runtime_url,
        "55000",
        CANCEL,
        db.property_id,
        made,
        WHY,
        cancelled["version"],
        db.staff,
    )


def test_a_late_cancel_keeps_the_money_and_may_give_credit(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    guest, made = paid_stay(db, db.one_bedroom, 1)
    found = read(db, made)
    late = run(db.runtime_url, CANCEL, db.property_id, made, WHY, found["version"], db.staff)
    kept = late["cancellation"]
    assert (kept["free"], kept["back_usd_cents"], kept["kept_usd_cents"]) == (False, 0, 4160)
    assert credit_of(db, guest) == 0
    # Only the credit right gives credit, at most what was kept, with a reason.
    give = json.dumps({"amount_usd_cents": 2000, "note": "Sick child"})
    refused(db.runtime_url, "42501", CREDIT, db.property_id, made, give, db.staff)
    for wrong in (
        {"amount_usd_cents": 4161, "note": "Too much"},
        {"amount_usd_cents": 2000},
    ):
        refused(
            db.runtime_url, "22023", CREDIT, db.property_id, made, json.dumps(wrong), db.manager
        )
    given = run(db.runtime_url, CREDIT, db.property_id, made, give, db.manager)
    assert given["credit"]["amount_usd_cents"] == 2000
    use_by = date.fromisoformat(given["credit"]["use_by"])
    assert (use_by.year * 12 + use_by.month) - (db.today.year * 12 + db.today.month) == 12
    assert credit_of(db, guest) == 2000
    refused(db.runtime_url, "55000", CREDIT, db.property_id, made, give, db.manager)
    assert [event["kind"] for event in given["history"]][-2:] == ["CANCELLED", "CREDIT_GIVEN"]


def test_a_no_show_owes_nothing_unpaid_and_a_site_booking_moves_no_money(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    made = run(db.runtime_url, BOOK, db.property_id, booking(db, db.two_bedroom, 0, 1), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, 1, db.staff)
    gone = run(
        db.runtime_url,
        CANCEL,
        db.property_id,
        made,
        json.dumps({"reason": "Did not come", "no_show": True}),
        billed["version"],
        db.staff,
    )
    assert gone["status"] == "NO_SHOW" and gone["invoice"]["status"] == "VOID"
    assert (gone["cancellation"]["paid_usd_cents"], gone["paid_usd_cents"]) == (0, 0)
    site = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.two_bedroom, 20, 2, source="BOOKING_SITE", site_name="Agoda"),
        db.staff,
    )
    marked = run(db.runtime_url, ON_SITE, db.property_id, site, 1, db.staff)
    off = run(db.runtime_url, CANCEL, db.property_id, site, WHY, marked["version"], db.staff)
    assert off["cancellation"]["free"] is True and off["cancellation"]["paid_usd_cents"] == 0
