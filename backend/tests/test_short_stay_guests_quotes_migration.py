"""Daily and weekly rent: quotes, guest history, the thank-you and extra discounts (migration 317).

A returning direct guest gets $3 off; the Manager may give an extra discount with a reason before
the Invoice; either comes off the Invoice as a credit. A quote gives today's price, and the
guest's history keeps every stay, the notes and the review request.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

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

REVISION = "20270607_317"
DISCOUNT = "SELECT app.give_short_stay_discount(%s, %s, %s::jsonb, %s, %s, NULL)"
GUEST = "SELECT app.short_stay_guest(%s, %s, %s)"
NOTE = "SELECT app.add_guest_note(%s, %s, %s::jsonb, %s, NULL)"
REVIEW = "SELECT app.ask_short_stay_review(%s, %s, %s, NULL)"
QUOTE = "SELECT app.make_short_stay_quote(%s, %s::jsonb, %s, NULL)"
QUOTES = "SELECT app.short_stay_quotes_read(%s, %s)"
PRICE = "SELECT app.short_stay_price_read(%s, %s, %s, %s, %s)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_guests_quotes") as database:
        yield database


def stayed(db: BookingDatabase, unit: uuid.UUID) -> tuple[uuid.UUID, Any]:
    """A new guest who stayed two nights from today and checked out."""
    guest = guest_with_id(db)
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, 0, 2, customer_id=str(guest)),
        db.staff,
    )
    run(db.runtime_url, DEPOSIT, db.property_id, made, json.dumps({"kind": "CASH"}), db.staff)
    billed = run(db.runtime_url, BILL, db.property_id, made, read(db, made)["version"], db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], billed["invoice"]["due_usd_cents"])
    inside = run(
        db.runtime_url, CHECK_IN, db.property_id, made, TICKS, read(db, made)["version"], db.staff
    )
    left = run(db.runtime_url, CHECK_OUT, db.property_id, made, inside["version"], db.staff)
    assert left["status"] == "CHECKED_OUT"
    return guest, made


def kinds(found: dict[str, Any]) -> list[str]:
    return [line["kind"] for line in found["lines"]]


def test_migration_317_follows_step_5a() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270606_316"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_returning_direct_guest_gets_the_thank_you(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest, _ = stayed(db, db.studio)
    # A booking-site guest pays the site's price: no thank-you.
    site = read(
        db,
        run(
            db.runtime_url,
            BOOK,
            db.property_id,
            booking(
                db,
                db.one_bedroom,
                20,
                2,
                customer_id=str(guest),
                source="BOOKING_SITE",
                site_name="Agoda",
                site_reference="AG-1",
            ),
            db.staff,
        ),
    )
    assert "RETURNING_GUEST" not in kinds(site) and site["returning_guest"] is True
    # A direct booking: $3 off as its own line.
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.one_bedroom, 10, 3, customer_id=str(guest), source="TELEGRAM"),
        db.staff,
    )
    found = read(db, made)
    thank = found["lines"][-1]
    assert (thank["kind"], thank["amount_usd_cents"]) == ("RETURNING_GUEST", -300)
    before = sum(
        line["amount_usd_cents"] for line in found["lines"] if line["amount_usd_cents"] > 0
    )
    assert found["total_usd_cents"] == before - 300
    # A first-time guest has none.
    first = read(
        db, run(db.runtime_url, BOOK, db.property_id, booking(db, db.one_bedroom, 30, 2), db.staff)
    )
    assert "RETURNING_GUEST" not in kinds(first) and first["returning_guest"] is False
    # The Invoice keeps the stay's lines; the $3 is a credit, so the guest owes the total.
    billed = run(db.runtime_url, BILL, db.property_id, made, found["version"], db.staff)
    invoice = billed["invoice"]
    assert (invoice["total_usd_cents"], invoice["due_usd_cents"]) == (before, before - 300)
    credit = run(
        db.owner_url,
        "SELECT jsonb_agg(jsonb_build_array(adjustment_type, amount_usd_cents)) "
        "FROM app.invoice_adjustments WHERE invoice_id = %s",
        invoice["invoice_id"],
    )
    assert credit == [["CREDIT", 300]]
    pay(db, guest, invoice["invoice_id"], before - 300)
    assert read(db, made)["payment"] == "PAID"


def test_an_extra_discount_needs_the_manager_and_a_reason(stay_database: BookingDatabase) -> None:
    db = stay_database
    made = run(db.runtime_url, BOOK, db.property_id, booking(db, db.two_bedroom, 40, 3), db.staff)
    found = read(db, made)
    total, version = found["total_usd_cents"], found["version"]
    ask = json.dumps({"amount_usd_cents": 1000, "reason": "Stayed with us last year"})
    refused(db.runtime_url, "42501", DISCOUNT, db.property_id, made, ask, version, db.staff)
    refused(
        db.runtime_url,
        "22023",
        DISCOUNT,
        db.property_id,
        made,
        json.dumps({"amount_usd_cents": 1000, "reason": " "}),
        version,
        db.manager,
    )
    refused(
        db.runtime_url,
        "55000",
        DISCOUNT,
        db.property_id,
        made,
        json.dumps({"amount_usd_cents": total, "reason": "Free"}),
        version,
        db.manager,
    )
    refused(db.runtime_url, "40001", DISCOUNT, db.property_id, made, ask, version - 1, db.manager)
    given = run(db.runtime_url, DISCOUNT, db.property_id, made, ask, version, db.manager)
    assert given["total_usd_cents"] == total - 1000
    line = given["lines"][-1]
    assert (line["kind"], line["amount_usd_cents"]) == ("EXTRA_DISCOUNT", -1000)
    assert given["history"][-1]["kind"] == "DISCOUNT"
    refused(
        db.runtime_url, "55000", DISCOUNT, db.property_id, made, ask, given["version"], db.manager
    )
    billed = run(db.runtime_url, BILL, db.property_id, made, given["version"], db.staff)
    assert billed["invoice"]["due_usd_cents"] == total - 1000
    assert "before the Invoice" in refused(
        db.runtime_url, "55000", DISCOUNT, db.property_id, made, ask, billed["version"], db.manager
    )


def test_guest_history_notes_and_the_review(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest, made = stayed(db, db.two_bedroom)
    history = run(db.runtime_url, GUEST, db.property_id, guest, db.staff)
    assert (history["stays_done"], history["nights_done"], history["returning"]) == (1, 2, True)
    assert history["spent_usd_cents"] == read(db, made)["total_usd_cents"]
    assert history["problem_guest"] is False and history["notes"] == []
    assert history["thank_you_usd_cents"] == 300
    refused(db.runtime_url, "22023", GUEST, db.property_id, uuid.uuid4(), db.staff)
    # The desk writes a note; a problem guest shows on every booking.
    refused(
        db.runtime_url, "22023", NOTE, db.property_id, guest, json.dumps({"note": ""}), db.staff
    )
    noted = run(
        db.runtime_url,
        NOTE,
        db.property_id,
        guest,
        json.dumps({"note": "Loud music at night", "problem_guest": True, "booking_id": str(made)}),
        db.staff,
    )
    assert noted["problem_guest"] is True
    assert noted["notes"][0]["booking_number"] == read(db, made)["booking_number"]
    assert read(db, made)["problem_guest"] is True
    # A review is asked for after the check-out, once.
    waiting = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.two_bedroom, 50, 2, customer_id=str(guest)),
        db.staff,
    )
    refused(db.runtime_url, "55000", REVIEW, db.property_id, waiting, db.staff)
    asked = run(db.runtime_url, REVIEW, db.property_id, made, db.staff)
    assert asked["review_asked_at"] is not None
    assert asked["history"][-1]["kind"] == "REVIEW_ASKED"
    assert "already" in refused(db.runtime_url, "55000", REVIEW, db.property_id, made, db.staff)


def test_a_quote_gives_todays_price(stay_database: BookingDatabase) -> None:
    db = stay_database
    check_in = db.today + timedelta(days=60)
    body = {
        "unit_id": str(db.studio),
        "guest_name": "Sok Chenda",
        "guest_contact": "@chenda",
        "guest_count": 2,
        "check_in_on": str(check_in),
        "check_out_on": str(check_in + timedelta(days=3)),
    }
    quote = run(db.runtime_url, QUOTE, db.property_id, json.dumps(body), db.staff)
    priced = run(
        db.runtime_url,
        PRICE,
        db.property_id,
        db.studio,
        check_in,
        check_in + timedelta(days=3),
        db.staff,
    )
    assert quote["quote_number"].startswith("SQ")
    assert (quote["total_usd_cents"], quote["nights"]) == (priced["total_usd_cents"], 3)
    assert quote["deposit_usd_cents"] == 5000 and quote["guest_name"] == "Sok Chenda"
    # A quote names its guest; a Unit that is let for those nights is refused.
    nameless = {key: value for key, value in body.items() if key != "guest_name"}
    refused(db.runtime_url, "22023", QUOTE, db.property_id, json.dumps(nameless), db.staff)
    leased = body | {"unit_id": str(db.leased)}
    refused(db.runtime_url, "55000", QUOTE, db.property_id, json.dumps(leased), db.staff)
    # A returning guest is quoted with the thank-you.
    guest, _ = stayed(db, db.one_bedroom)
    again = run(
        db.runtime_url,
        QUOTE,
        db.property_id,
        json.dumps(nameless | {"customer_id": str(guest)}),
        db.staff,
    )
    assert again["total_usd_cents"] == quote["total_usd_cents"] - 300
    assert again["lines"][-1]["kind"] == "RETURNING_GUEST"
    listed = run(db.runtime_url, QUOTES, db.property_id, db.staff)
    assert [found["quote_id"] for found in listed[:2]] == [again["quote_id"], quote["quote_id"]]
