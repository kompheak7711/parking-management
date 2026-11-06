"""Daily and weekly rent: payment, deposit, check-in, check-out, damage (migration 20270602_312).

Full payment before check-in: the booking's Invoice is paid on the usual Receive payment
command, or a booking-site booking is paid on the site. Every guest leaves a $50 cash deposit or
card hold (never a card number). Check-in needs the ID number, the copy and the house rules; the
room check after check-out can report damage, which the Manager approves: it is taken from the
deposit first and the rest is an Invoice.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import database_instant, seed_method
from property_rental.payment_confirmation import ConfirmUsdPaymentCommand
from property_rental.receive_payment import (
    PaysTarget,
    ReceivePaymentCommand,
    ReceivePaymentService,
)
from test_credit_migration import actor
from test_invoice_migration import financial_database_url
from test_khr_payment_confirmation import provider
from test_migrations import _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)

REVISION = "20270602_312"
READ = "SELECT app.short_stay_booking_read(%s, %s, %s)"
BILL = "SELECT app.bill_short_stay(%s, %s, %s, %s, NULL)"
ON_SITE = "SELECT app.mark_short_stay_paid_on_site(%s, %s, %s, %s, NULL)"
DEPOSIT = "SELECT app.take_short_stay_deposit(%s, %s, %s::jsonb, %s, NULL)"
CHECK_IN = "SELECT app.check_in_short_stay(%s, %s, %s::jsonb, %s, %s, NULL)"
CHECK_OUT = "SELECT app.check_out_short_stay(%s, %s, %s, %s, NULL)"
ROOM = "SELECT app.check_short_stay_room(%s, %s, %s::jsonb, %s, NULL)"
DECIDE = "SELECT app.decide_short_stay_damage(%s, %s, %s::jsonb, %s, NULL)"
END_DEPOSIT = "SELECT app.end_short_stay_deposit(%s, %s, %s, NULL)"
TICKS = json.dumps({"id_copy_made": True, "house_rules_signed": True})


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_check_in") as database:
        yield database


def read(db: BookingDatabase, made: Any) -> dict[str, Any]:
    found = run(db.runtime_url, READ, db.property_id, made, db.staff)
    assert isinstance(found, dict)
    return found


def unit_status(db: BookingDatabase, unit: uuid.UUID) -> str:
    return str(run(db.owner_url, "SELECT status FROM app.units WHERE id = %s", unit))


def guest_with_id(db: BookingDatabase) -> uuid.UUID:
    guest = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.customers (id, legal_name, phone_number, id_document_number, "
            "created_by, updated_by) VALUES (%s, 'Meas Rina', '012 555 666', %s, %s, %s)",
            (guest, f"N{guest.hex[:8]}", db.manager, db.manager),
        )
    return guest


def pay(db: BookingDatabase, customer: uuid.UUID, invoice: str, amount: int) -> None:
    name = urlsplit(db.owner_url).path.lstrip("/")
    with psycopg.connect(db.owner_url) as connection:
        method = seed_method(connection, db.manager)
        at = database_instant(connection)
    command = ReceivePaymentCommand(
        ConfirmUsdPaymentCommand(uuid.uuid4(), customer, method, amount, at, "Front desk cash"),
        "NAMED",
        (PaysTarget("INVOICE", uuid.UUID(invoice), amount),),
    )
    service = ReceivePaymentService(
        _url_with_database(financial_database_url(), name), provider(at)
    )
    service.receive(
        db.property_id,
        command,
        actor=actor(db.staff, db.property_id, "payments.record", "payments.allocate"),
    )


def test_migration_312_follows_step_2() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270601_311"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_full_stay_from_payment_to_the_deposit(stay_database: BookingDatabase) -> None:
    db = stay_database
    guest = guest_with_id(db)
    made = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, db.studio, 0, 2, customer_id=str(guest)),
        db.staff,
    )
    found = read(db, made)
    assert (found["payment"], found["deposit"], found["invoice"]) == ("NOT_BILLED", None, None)
    # Nothing is ready: the message names every missing step.
    message = refused(
        db.runtime_url, "55000", CHECK_IN, db.property_id, made, "{}", found["version"], db.staff
    )
    assert "PAYMENT, DEPOSIT, ID_COPY, HOUSE_RULES" in message
    # A card number is never saved; the hold reference and the last 4 digits are.
    refused(
        db.runtime_url,
        "22023",
        DEPOSIT,
        db.property_id,
        made,
        json.dumps({"kind": "CARD_HOLD", "hold_reference": "4111 1111 1111 1111"}),
        db.staff,
    )
    held = run(
        db.runtime_url,
        DEPOSIT,
        db.property_id,
        made,
        json.dumps({"kind": "CARD_HOLD", "hold_reference": "HOLD-7781", "card_last4": "1234"}),
        db.staff,
    )
    assert held["deposit"]["amount_usd_cents"] == 5000
    assert held["deposit"]["status"] == "HELD"
    refused(
        db.runtime_url,
        "55000",
        DEPOSIT,
        db.property_id,
        made,
        json.dumps({"kind": "CASH"}),
        db.staff,
    )
    # Bill: one issued Invoice with one item per price line, for the booking's total.
    billed = run(db.runtime_url, BILL, db.property_id, made, found["version"], db.staff)
    assert billed["payment"] == "UNPAID"
    assert billed["invoice"]["total_usd_cents"] == billed["total_usd_cents"] == 4640
    items = run(
        db.owner_url,
        "SELECT count(*) FROM app.invoice_lines WHERE invoice_id = %s",
        billed["invoice"]["invoice_id"],
    )
    assert items == len(billed["lines"])
    refused(db.runtime_url, "55000", BILL, db.property_id, made, billed["version"], db.staff)
    # A stale screen is refused.
    refused(db.runtime_url, "40001", CHECK_IN, db.property_id, made, TICKS, 1, db.staff)
    pay(db, guest, billed["invoice"]["invoice_id"], 4640)
    paid = read(db, made)
    assert paid["payment"] == "PAID"
    calendar = run(
        db.runtime_url,
        "SELECT app.short_stay_calendar(%s, %s, 3, %s)",
        db.property_id,
        db.today,
        db.staff,
    )
    rows = {unit["unit_number"]: unit for unit in calendar["units"]}
    assert rows["U501"]["bookings"][0]["paid"] is True
    # Check-in: the Unit becomes Short stay.
    inside = run(db.runtime_url, CHECK_IN, db.property_id, made, TICKS, paid["version"], db.staff)
    assert inside["status"] == "CHECKED_IN"
    assert unit_status(db, db.studio) == "SHORT_STAY"
    refused(db.runtime_url, "55000", ROOM, db.property_id, made, "{}", db.staff)
    refused(db.runtime_url, "55000", END_DEPOSIT, db.property_id, made, db.staff)
    # Check-out: Cleaning and a room check today.
    left = run(db.runtime_url, CHECK_OUT, db.property_id, made, inside["version"], db.staff)
    assert left["status"] == "CHECKED_OUT" and left["room_check"]["status"] == "TO_DO"
    assert unit_status(db, db.studio) == "CLEANING"
    # The room check finds damage; the Unit is ready again.
    checked = run(
        db.runtime_url,
        ROOM,
        db.property_id,
        made,
        json.dumps({"damage": "Broken lamp", "damage_usd_cents": 8000}),
        db.staff,
    )
    assert checked["room_check"]["status"] == "DONE"
    assert unit_status(db, db.studio) == "VACANT"
    damage = checked["damages"][0]
    assert (damage["status"], damage["amount_usd_cents"]) == ("WAITING", 8000)
    assert "Damage waits" in refused(
        db.runtime_url, "55000", END_DEPOSIT, db.property_id, made, db.staff
    )
    # Only the approve right decides; a refusal says why.
    decision = json.dumps({"approve": True, "note": "Photo on file"})
    refused(
        db.runtime_url, "42501", DECIDE, db.property_id, damage["damage_id"], decision, db.staff
    )
    refused(
        db.runtime_url,
        "22023",
        DECIDE,
        db.property_id,
        damage["damage_id"],
        json.dumps({"approve": False}),
        db.manager,
    )
    approved = run(
        db.runtime_url, DECIDE, db.property_id, damage["damage_id"], decision, db.manager
    )
    charge = approved["damages"][0]
    assert charge["status"] == "APPROVED" and charge["from_deposit_usd_cents"] == 5000
    rest = run(
        db.owner_url,
        "SELECT original_total_usd_cents FROM app.invoices WHERE id = %s",
        charge["invoice_id"],
    )
    assert rest == 3000
    ended = run(db.runtime_url, END_DEPOSIT, db.property_id, made, db.staff)
    assert (ended["deposit"]["status"], ended["deposit"]["kept_usd_cents"]) == ("KEPT", 5000)
    assert [event["kind"] for event in ended["history"]] == [
        "BOOKED",
        "DEPOSIT_TAKEN",
        "BILLED",
        "CHECKED_IN",
        "CHECKED_OUT",
        "ROOM_CHECKED",
        "DAMAGE_APPROVED",
        "DEPOSIT_KEPT",
    ]


def test_paid_on_the_site_and_the_guest_without_an_id(stay_database: BookingDatabase) -> None:
    db = stay_database
    walk_in = run(db.runtime_url, BOOK, db.property_id, booking(db, db.one_bedroom, 0, 1), db.staff)
    found = read(db, walk_in)
    refused(db.runtime_url, "55000", ON_SITE, db.property_id, walk_in, found["version"], db.staff)
    # Lim Dara has no ID or passport number on the Customer yet.
    message = refused(
        db.runtime_url,
        "55000",
        CHECK_IN,
        db.property_id,
        walk_in,
        TICKS,
        found["version"],
        db.staff,
    )
    assert "ID_NUMBER" in message
    site = run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(
            db,
            db.two_bedroom,
            5,
            2,
            source="BOOKING_SITE",
            site_name="Agoda",
            site_reference="AG-1201",
        ),
        db.staff,
    )
    marked = run(db.runtime_url, ON_SITE, db.property_id, site, 1, db.staff)
    assert marked["payment"] == "PAID_ON_SITE" and marked["invoice"] is None
    refused(db.runtime_url, "55000", BILL, db.property_id, site, marked["version"], db.staff)
    # Payment and check-in only move forward.
    with psycopg.connect(db.owner_url) as connection, pytest.raises(psycopg.Error) as caught:
        connection.execute(
            "UPDATE app.short_stay_bookings SET paid_on_site = false, version = version + 1 "
            "WHERE id = %s",
            (site,),
        )
    assert caught.value.sqlstate == "55000"
    # A guest checks in only from the check-in day.
    assert "check-in day" in refused(
        db.runtime_url, "55000", CHECK_IN, db.property_id, site, TICKS, marked["version"], db.staff
    )
    later = db.today + timedelta(days=5)
    assert marked["check_in_on"] == str(later)
