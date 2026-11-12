"""Owner's rules of 12 Nov 2026 (DL-224, migration 20270720_375): Change Unit for a short-stay
booking before check-in.

Staff may move a booked guest to another Unit while the guest has not checked in: a Unit of the
same type first, another type when none is free. The guest keeps the agreed price: the price
lines, the bill and the money paid stay as they are. An Owner or Manager may then give a special
discount with a reason; when the stay is already paid, the amount becomes the guest's Credit.
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

from property_rental.products_api import ProductConflict, ProductForbidden, ProductStale
from property_rental.short_stays_api import PostgresShortStayFlow
from test_lease_api_migration import headers
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_short_stay_booking_migration import (
    BOOK,
    BookingDatabase,
    booking,
    refused,
    run,
    short_stay_database,
)
from test_short_stay_cancel_migration import CANCEL, WHY, credit_of, paid_stay
from test_short_stay_check_in_migration import (
    BILL,
    CHECK_IN,
    ON_SITE,
    TICKS,
    guest_with_id,
    read,
)
from test_short_stay_cleaning_migration import EXTEND
from test_short_stay_guests_quotes_migration import DISCOUNT
from test_v12_lease_draft_short_stay_migration import client as lease_client
from test_v12_lease_draft_short_stay_migration import new_lease

REVISION = "20270720_375"
UNITS = "SELECT app.short_stay_move_units(%s, %s, %s)"
CHANGE = "SELECT app.change_short_stay_unit(%s, %s, %s::jsonb, %s, %s, NULL)"
MOVE_DISCOUNT = "SELECT app.give_short_stay_move_discount(%s, %s, %s::jsonb, %s, %s, NULL)"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_v12_change_unit") as database:
        yield database


def book(db: BookingDatabase, unit: uuid.UUID, start: int, nights: int = 2, **extra: Any) -> Any:
    """A guest with an ID books the Unit: check-in ``start`` days from today."""
    guest = extra.pop("customer_id", None) or str(guest_with_id(db))
    return run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(db, unit, start, nights, customer_id=guest, **extra),
        db.staff,
    )


def to(unit: uuid.UUID, reason: str = "A Lease takes the Unit the guest booked") -> str:
    return json.dumps({"unit_id": str(unit), "reason": reason})


def move(db: BookingDatabase, made: Any, unit: uuid.UUID) -> dict[str, Any]:
    moved = run(
        db.runtime_url, CHANGE, db.property_id, made, to(unit), read(db, made)["version"], db.staff
    )
    assert isinstance(moved, dict)
    return moved


def offered(db: BookingDatabase, made: Any) -> list[str]:
    found = run(db.runtime_url, UNITS, db.property_id, made, db.staff)
    return [unit["unit_number"] for unit in found["units"]]


def amount(cents: int, reason: str = "A smaller Unit than the guest booked") -> str:
    return json.dumps({"amount_usd_cents": cents, "reason": reason})


def test_migration_375_follows_the_lease_draft_fix_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270719_374"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_a_booked_stay_moves_to_another_unit_and_keeps_its_price(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    made = book(db, db.studio, 3)
    before = read(db, made)
    # The Units free on every night of the stay: the same type first, then the other types.
    found = run(db.runtime_url, UNITS, db.property_id, made, db.staff)
    assert [(unit["unit_number"], unit["same_type"]) for unit in found["units"]] == [
        ("U506", True),
        ("U507", True),
        ("U503", False),
        ("U505", False),
    ]
    assert found["units"][3]["unit_type"] == "TWO_BEDROOM"
    assert found["units"][3]["monthly_rent_usd_cents"] == 49900
    version = before["version"]

    # A move says why, goes to another Unit of this Property, and uses the version it read.
    for body in (
        json.dumps({"unit_id": str(db.two_bedroom), "reason": " "}),
        json.dumps({"unit_id": str(db.studio), "reason": "Same Unit"}),
        json.dumps({"unit_id": str(uuid.uuid4()), "reason": "Unknown Unit"}),
        json.dumps({"unit_id": "not a Unit", "reason": "Not an id"}),
    ):
        refused(db.runtime_url, "22023", CHANGE, db.property_id, made, body, version, db.staff)
    refused(
        db.runtime_url,
        "40001",
        CHANGE,
        db.property_id,
        made,
        to(db.two_bedroom),
        version - 1,
        db.staff,
    )
    refused(
        db.runtime_url,
        "42501",
        CHANGE,
        db.property_id,
        made,
        to(db.two_bedroom),
        version,
        uuid.uuid4(),
    )

    moved = run(db.runtime_url, CHANGE, db.property_id, made, to(db.two_bedroom), version, db.staff)
    assert (moved["unit_id"], moved["unit_number"], moved["unit_type"]) == (
        str(db.two_bedroom),
        "U505",
        "TWO_BEDROOM",
    )
    # The guest keeps the agreed price: a bigger Unit is a free upgrade.
    assert moved["total_usd_cents"] == before["total_usd_cents"]
    assert [
        (line["kind"], line["quantity"], line["unit_price_usd_cents"], line["amount_usd_cents"])
        for line in moved["lines"]
    ] == [
        (line["kind"], line["quantity"], line["unit_price_usd_cents"], line["amount_usd_cents"])
        for line in before["lines"]
    ]
    assert (moved["status"], moved["version"]) == ("BOOKED", version + 1)
    assert (moved["check_in_on"], moved["check_out_on"]) == (
        before["check_in_on"],
        before["check_out_on"],
    )
    event = moved["history"][-1]
    assert (event["kind"], event["note"]) == (
        "UNIT_CHANGED",
        "A Lease takes the Unit the guest booked",
    )
    assert event["actor_id"] == str(db.staff)
    assert event["details"] == {
        "from_unit_id": str(db.studio),
        "from_unit_number": "U501",
        "from_unit_type": "STUDIO",
        "to_unit_id": str(db.two_bedroom),
        "to_unit_number": "U505",
        "to_unit_type": "TWO_BEDROOM",
    }
    with psycopg.connect(db.owner_url) as connection:
        audit = connection.execute(
            "SELECT reason, authorization_reference, resulting_state ->> 'unit_number' "
            "FROM app.audit_events WHERE entity_id = %s AND action = 'short_stay.unit_changed'",
            (made,),
        ).fetchall()
    assert audit == [("A Lease takes the Unit the guest booked", "short_stays.desk", "U505")]

    # The old Unit is free again on those nights; the new Unit is taken.
    book(db, db.studio, 3)
    assert "BOOKED" in refused(
        db.runtime_url, "55000", BOOK, db.property_id, booking(db, db.two_bedroom, 3, 2), db.staff
    )


def test_a_stay_moves_only_to_a_free_unit_and_only_before_check_in(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    first = book(db, db.studio, 8)
    book(db, db.one_bedroom, 9)
    # Another guest has the one-bedroom on one of the nights.
    assert "U503" not in offered(db, first)
    assert "BOOKED" in refused(
        db.runtime_url,
        "55000",
        CHANGE,
        db.property_id,
        first,
        to(db.one_bedroom),
        read(db, first)["version"],
        db.staff,
    )
    # U507 has a signed Lease from day 20: a stay that ends on day 22 does not move there.
    late = book(db, db.two_bedroom, 19, 3)
    assert "U507" not in offered(db, late)
    assert "LEASE" in refused(
        db.runtime_url,
        "55000",
        CHANGE,
        db.property_id,
        late,
        to(db.leased),
        read(db, late)["version"],
        db.staff,
    )
    assert read(db, first)["unit_number"] == "U501" and read(db, late)["unit_number"] == "U505"

    # After check-in the guest stays in the Unit; a cancelled booking does not move either.
    guest, staying = paid_stay(db, db.studio, 0)
    version = read(db, staying)["version"]
    checked_in = run(db.runtime_url, CHECK_IN, db.property_id, staying, TICKS, version, db.staff)
    assert checked_in["status"] == "CHECKED_IN"
    assert offered(db, staying) == []
    assert "not checked in yet" in refused(
        db.runtime_url,
        "55000",
        CHANGE,
        db.property_id,
        staying,
        to(db.one_bedroom),
        checked_in["version"],
        db.staff,
    )
    cancelled = run(
        db.runtime_url, CANCEL, db.property_id, first, WHY, read(db, first)["version"], db.staff
    )
    refused(
        db.runtime_url,
        "55000",
        CHANGE,
        db.property_id,
        first,
        to(db.two_bedroom),
        cancelled["version"],
        db.staff,
    )
    assert guest


def test_a_paid_stay_moves_with_its_bill_and_money_as_they_are(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    guest, made = paid_stay(db, db.studio, 12)
    before = read(db, made)
    assert before["payment"] == "PAID"
    moved = move(db, made, db.one_bedroom)
    assert moved["unit_number"] == "U503"
    for key in ("payment", "paid_usd_cents", "total_usd_cents", "invoice", "deposit"):
        assert moved[key] == before[key], key
    assert credit_of(db, guest) == 0


def test_a_special_discount_after_a_move_makes_credit_when_the_stay_is_paid(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    guest, made = paid_stay(db, db.two_bedroom, 14)
    before = read(db, made)
    total, paid = before["total_usd_cents"], before["paid_usd_cents"]
    assert paid == total
    # The special discount is for a stay that was moved.
    assert "moved" in refused(
        db.runtime_url,
        "55000",
        MOVE_DISCOUNT,
        db.property_id,
        made,
        amount(1000),
        before["version"],
        db.manager,
    )
    moved = move(db, made, db.studio)
    version = moved["version"]
    # Only an Owner or Manager gives it, with a reason, and it is less than the stay.
    refused(
        db.runtime_url,
        "42501",
        MOVE_DISCOUNT,
        db.property_id,
        made,
        amount(1000),
        version,
        db.staff,
    )
    for body in (amount(1000, " "), amount(0), json.dumps({"reason": "No amount"})):
        refused(
            db.runtime_url, "22023", MOVE_DISCOUNT, db.property_id, made, body, version, db.manager
        )
    refused(
        db.runtime_url,
        "55000",
        MOVE_DISCOUNT,
        db.property_id,
        made,
        amount(total),
        version,
        db.manager,
    )
    refused(
        db.runtime_url,
        "40001",
        MOVE_DISCOUNT,
        db.property_id,
        made,
        amount(1000),
        version - 1,
        db.manager,
    )

    given = run(
        db.runtime_url, MOVE_DISCOUNT, db.property_id, made, amount(1000), version, db.manager
    )
    assert given["total_usd_cents"] == total - 1000
    line = given["lines"][-1]
    assert (line["kind"], line["amount_usd_cents"], line["reason"]) == (
        "EXTRA_DISCOUNT",
        -1000,
        "A smaller Unit than the guest booked",
    )
    # The stay was paid: the amount is now the guest's Credit and the stay is still paid.
    assert credit_of(db, guest) == 1000
    assert (given["payment"], given["paid_usd_cents"]) == ("PAID", total - 1000)
    assert given["invoice"]["invoice_id"] == before["invoice"]["invoice_id"]
    event = given["history"][-1]
    assert (event["kind"], event["note"]) == (
        "MOVE_DISCOUNT",
        "A smaller Unit than the guest booked",
    )
    assert event["details"] == {"amount_usd_cents": 1000, "credit_usd_cents": 1000}
    assert event["actor_id"] == str(db.manager)
    # The booking shows that Credit with the Refund button a free cancel already has.
    assert moved.get("refund") is None
    assert given["refund"]["left_usd_cents"] == 1000
    assert len(given["refund"]["credits"]) == 1
    # One special discount for one move.
    assert "already" in refused(
        db.runtime_url,
        "55000",
        MOVE_DISCOUNT,
        db.property_id,
        made,
        amount(500),
        given["version"],
        db.manager,
    )
    assert credit_of(db, guest) == 1000


def test_a_special_discount_lowers_a_bill_that_is_not_paid_yet(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    # Not billed yet: the discount is a price line, and the Invoice is made for the lower total.
    guest = guest_with_id(db)
    open_stay = book(db, db.studio, 26, customer_id=str(guest))
    total = read(db, open_stay)["total_usd_cents"]
    moved = move(db, open_stay, db.one_bedroom)
    given = run(
        db.runtime_url,
        MOVE_DISCOUNT,
        db.property_id,
        open_stay,
        amount(500),
        moved["version"],
        db.manager,
    )
    assert (given["payment"], given["total_usd_cents"]) == ("NOT_BILLED", total - 500)
    assert given["history"][-1]["details"] == {"amount_usd_cents": 500, "credit_usd_cents": 0}
    billed = run(db.runtime_url, BILL, db.property_id, open_stay, given["version"], db.staff)
    assert billed["invoice"]["due_usd_cents"] == total - 500
    # The Manager's extra discount before the Invoice is still one for a stay.
    refused(
        db.runtime_url,
        "55000",
        DISCOUNT,
        db.property_id,
        open_stay,
        amount(100),
        billed["version"],
        db.manager,
    )

    # Billed, not paid: the Invoice asks for less, and no Credit is made.
    owing = book(db, db.studio, 30, customer_id=str(guest))
    billed = run(db.runtime_url, BILL, db.property_id, owing, read(db, owing)["version"], db.staff)
    due = billed["invoice"]["due_usd_cents"]
    moved = move(db, owing, db.one_bedroom)
    given = run(
        db.runtime_url,
        MOVE_DISCOUNT,
        db.property_id,
        owing,
        amount(700),
        moved["version"],
        db.manager,
    )
    assert given["invoice"]["due_usd_cents"] == due - 700
    assert (given["total_usd_cents"], given["paid_usd_cents"]) == (due - 700, 0)
    assert given["history"][-1]["details"] == {"amount_usd_cents": 700, "credit_usd_cents": 0}
    assert credit_of(db, guest) == 0

    # Paid on the booking site: there is no Invoice here to take the discount off.
    site = book(
        db,
        db.two_bedroom,
        34,
        source="BOOKING_SITE",
        site_name="Booking.com",
        site_reference="BK-375",
    )
    on_site = run(
        db.runtime_url, ON_SITE, db.property_id, site, read(db, site)["version"], db.staff
    )
    assert on_site["payment"] == "PAID_ON_SITE"
    moved = move(db, site, db.studio)
    assert "booking site" in refused(
        db.runtime_url,
        "55000",
        MOVE_DISCOUNT,
        db.property_id,
        site,
        amount(300),
        moved["version"],
        db.manager,
    )


def test_a_moved_stay_is_not_extended_it_gets_a_new_booking(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    made = book(db, db.studio, 40)
    stay = read(db, made)
    longer = json.dumps({"check_out_on": str(db.today + timedelta(days=44))})
    moved = move(db, made, db.one_bedroom)
    # Extend would price every night again from the new Unit's Rent; the agreed price stays.
    assert "moved to another Unit" in refused(
        db.runtime_url, "55000", EXTEND, db.property_id, made, longer, moved["version"], db.staff
    )
    after = read(db, made)
    assert (after["check_out_on"], after["total_usd_cents"]) == (
        stay["check_out_on"],
        stay["total_usd_cents"],
    )
    # The extra nights are a new booking in the Unit the guest is in, from the check-out day.
    extra = book(db, db.one_bedroom, 42, customer_id=stay["customer_id"])
    assert read(db, extra)["unit_number"] == "U503"
    # A stay that was not moved is extended as before.
    plain = book(db, db.studio, 40)
    extended = run(
        db.runtime_url,
        EXTEND,
        db.property_id,
        plain,
        longer,
        read(db, plain)["version"],
        db.staff,
    )
    assert extended["check_out_on"] == str(db.today + timedelta(days=44))


def test_the_api_runs_the_three_steps_on_the_database(stay_database: BookingDatabase) -> None:
    """The API's own SQL for Change Unit: the Units, the move and the special discount."""
    db = stay_database
    flow = PostgresShortStayFlow(db.runtime_url)
    made = uuid.UUID(str(book(db, db.studio, 50)))
    book(db, db.one_bedroom, 50)
    staff, manager = str(db.staff), str(db.manager)

    found = flow.act(db.property_id, "move_units", made, {}, actor_id=staff)
    # U505 is free; U503 has another guest on those nights. The same answer as the database's.
    assert found == run(db.runtime_url, UNITS, db.property_id, made, db.staff)
    numbers = offered(db, made)
    assert "U505" in numbers and "U503" not in numbers
    version = read(db, made)["version"]
    before = read(db, made)["total_usd_cents"]
    why = "The guest asked for more room"

    def change(unit: uuid.UUID, read_version: int) -> dict[str, object]:
        body = {"version": read_version, "unit_id": str(unit), "reason": why}
        return flow.act(db.property_id, "change_unit", made, body, actor_id=staff)

    with pytest.raises(ProductStale):
        change(db.two_bedroom, version - 1)
    with pytest.raises(ProductConflict, match="The Unit cannot take this stay: BOOKED"):
        change(db.one_bedroom, version)
    moved = change(db.two_bedroom, version)
    assert (moved["unit_number"], moved["version"]) == ("U505", version + 1)

    lower = {"version": moved["version"], "amount_usd_cents": 400, "reason": "Asked to move"}
    with pytest.raises(ProductForbidden):
        flow.act(db.property_id, "move_discount", made, dict(lower), actor_id=staff)
    given = flow.act(db.property_id, "move_discount", made, dict(lower), actor_id=manager)
    after = read(db, made)
    assert given["total_usd_cents"] == after["total_usd_cents"] == before - 400
    assert after["history"][-1]["kind"] == "MOVE_DISCOUNT"


def test_the_owners_case_the_guest_moves_and_the_lease_draft_is_then_saved(
    stay_database: BookingDatabase,
) -> None:
    """Owner 12 Nov 2026: a paid guest has the Unit a Lease wants; the guest moves first."""
    db = stay_database
    _, made = paid_stay(db, db.two_bedroom, 62)
    url = f"/api/v1/properties/{db.property_id}/leases"
    api = lease_client(db)
    draft = new_lease(db, db.two_bedroom, db.today + timedelta(days=60))

    stopped = api.post(url, json=draft, headers=headers())
    assert stopped.status_code == 409, stopped.text
    error = stopped.json()["error"]
    assert error["code"] == "LEASE_UNIT_BOOKED"
    assert "move the guest to another Unit first" in error["message"]

    moved = move(db, made, db.studio)
    assert (moved["unit_number"], moved["payment"]) == ("U501", "PAID")
    saved = api.post(url, json=draft, headers=headers())
    assert saved.status_code == 201, saved.text
    # The guest's nights are safe in the new Unit: a Lease there is stopped the same way.
    again = api.post(
        url, json=new_lease(db, db.studio, db.today + timedelta(days=60)), headers=headers()
    )
    assert again.status_code == 409, again.text
