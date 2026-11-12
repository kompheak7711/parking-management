"""DL-225 (12 Nov 2026, migration 20270721_376): Reserve Unit stops on a Unit that a short-stay
guest has booked. The owner's rule for a Lease (the booking wins, DL-223) also holds here.

A Reservation holds the Unit from today for the Lease that follows. Before this migration it
was saved on a Unit with a booked guest, because only the Unit status (VACANT) was checked. The
guest could then not check in (the Unit was RESERVED), and the Lease draft that followed stopped
only later (DL-223). Now the Reservation stops at once, keeps no money, and the screen gets the
reason: reserve another Unit, or move the guest first with Change Unit (DL-224).
"""

from __future__ import annotations

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

from property_rental.api_refusals import RESERVATION_UNIT_BOOKED, RefusedRequest
from property_rental.reservation import (
    UNIT_BOOKED_BY_SHORT_STAY_GUEST,
    PostgresReservationService,
    ReservationCommandConflictError,
    ReservationCreateCommand,
    ReservationUnitBookedError,
    _raise_command_error,
)
from property_rental.reservation_api import _translate
from test_invoice_migration import financial_database_url
from test_migrations import _url_with_database
from test_money_one_step_migration import money, payments
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import create_reservation
from test_short_stay_booking_migration import BookingDatabase, run, short_stay_database
from test_short_stay_cancel_migration import CANCEL, WHY
from test_short_stay_check_in_migration import guest_with_id, read, unit_status
from test_v12_short_stay_change_unit_migration import book, move

REVISION = "20270721_376"


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_v12_reserve_booked") as database:
        yield database


def spare_unit(db: BookingDatabase, number: str) -> uuid.UUID:
    """One more vacant studio, so each test has Units of its own."""
    unit = uuid.uuid4()
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, status, "
            "default_monthly_rent_usd_cents, created_by, updated_by) "
            "VALUES (%s, %s, %s, '6', 'STUDIO', 'VACANT', 29900, %s, %s)",
            (unit, db.property_id, number, db.manager, db.manager),
        )
    return unit


def service(db: BookingDatabase) -> PostgresReservationService:
    name = urlsplit(db.owner_url).path.lstrip("/")
    return PostgresReservationService(
        db.runtime_url,
        db.property_id,
        db.manager,
        _url_with_database(financial_database_url(), name),
    )


def command(db: BookingDatabase, unit: uuid.UUID, customer: uuid.UUID) -> ReservationCreateCommand:
    return ReservationCreateCommand(
        idempotency_key=uuid.uuid4(),
        reservation_id=uuid.uuid4(),
        unit_id=unit,
        customer_id=customer,
        reservation_date=db.today,
        agreed_monthly_rent_usd_cents=50_000,
        original_expiration_date=db.today + timedelta(days=10),
        acceptance_id=uuid.uuid4(),
        accepted_required_amount_usd_cents=10_000,
        acceptance_kind="NORMAL_SUGGESTION",
        accepted_at=None,
        acceptance_reason="Suggested 20% of the agreed Rent",
        authorization_reference="reservations.create",
        calculation_trace={
            "agreed_monthly_rent_usd_cents": 50_000,
            "suggested_rate_basis_points": 2000,
            "suggested_amount_usd_cents": 10_000,
        },
        deposit_id=uuid.uuid4(),
        required_deposit_usd_cents=50_000,
        receipt_id=uuid.uuid4(),
        # A placeholder: the Payment confirmed in the same transaction replaces it.
        payment_id=uuid.uuid4(),
        received_at=None,
    )


def reserve(db: BookingDatabase, unit: uuid.UUID, customer: uuid.UUID) -> Any:
    """Make Reservation as the screen does: the money and the Reservation in one step."""
    made, _ = service(db).create_with_payment(
        command(db, unit, customer), money(db.owner_url, db.manager, customer, 10_000)
    )
    return made


def reservations(db: BookingDatabase, unit: uuid.UUID) -> int:
    return int(run(db.owner_url, "SELECT count(*) FROM app.reservations WHERE unit_id = %s", unit))


def test_migration_376_follows_change_unit_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270720_375"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_make_reservation_stops_on_a_unit_with_a_booked_guest_and_keeps_no_money(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    booked, free = spare_unit(db, "U601"), spare_unit(db, "U602")
    made = book(db, booked, 3)
    customer = guest_with_id(db)

    with pytest.raises(ReservationUnitBookedError) as stopped:
        reserve(db, booked, customer)
    # Nothing was saved: no money, no Reservation, and the guest keeps the Unit.
    assert payments(db.owner_url, customer) == 0
    assert reservations(db, booked) == 0
    assert unit_status(db, booked) == "VACANT"
    assert read(db, made)["status"] == "BOOKED"
    # The screen gets the reason with a code, not "try again later".
    assert isinstance(stopped.value, ReservationCommandConflictError)
    answer = _translate(stopped.value)
    assert isinstance(answer, RefusedRequest)
    assert answer.refusal is RESERVATION_UNIT_BOOKED
    assert (answer.refusal.status_code, answer.refusal.code) == (409, "RESERVATION_UNIT_BOOKED")
    assert "Change Unit" in answer.refusal.message

    # The database itself refuses, whichever command saves the Reservation.
    with psycopg.connect(db.owner_url) as connection, pytest.raises(psycopg.Error) as raised:
        create_reservation(
            connection,
            actor_id=db.manager,
            property_id=db.property_id,
            unit_id=booked,
            customer_id=customer,
        )
    assert raised.value.sqlstate == "23P01"
    assert raised.value.diag.message_primary == UNIT_BOOKED_BY_SHORT_STAY_GUEST
    with pytest.raises(ReservationUnitBookedError):
        _raise_command_error(raised.value)
    assert reservations(db, booked) == 0

    # A Unit with no booked guest is reserved as before.
    held = reserve(db, free, customer)
    assert held.status == "ACTIVE"
    assert unit_status(db, free) == "RESERVED"
    assert payments(db.owner_url, customer) == 1


def test_the_unit_is_reserved_after_the_guest_moves_to_another_unit(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    wanted, other = spare_unit(db, "U603"), spare_unit(db, "U604")
    made = book(db, wanted, 10)
    customer = guest_with_id(db)
    with pytest.raises(ReservationUnitBookedError):
        reserve(db, wanted, customer)

    # Change Unit (DL-224) moves the guest; the Unit is then free to reserve.
    assert move(db, made, other)["unit_id"] == str(other)
    assert reserve(db, wanted, customer).status == "ACTIVE"
    assert unit_status(db, wanted) == "RESERVED"
    # The Unit the guest moved to is now the one that cannot be reserved.
    with pytest.raises(ReservationUnitBookedError):
        reserve(db, other, guest_with_id(db))


def test_the_unit_is_reserved_after_the_booking_is_cancelled(
    stay_database: BookingDatabase,
) -> None:
    db = stay_database
    unit = spare_unit(db, "U605")
    made = book(db, unit, 20)
    customer = guest_with_id(db)
    with pytest.raises(ReservationUnitBookedError):
        reserve(db, unit, customer)

    cancelled = run(
        db.runtime_url, CANCEL, db.property_id, made, WHY, read(db, made)["version"], db.staff
    )
    assert cancelled["status"] == "CANCELLED"
    assert reserve(db, unit, customer).status == "ACTIVE"


def test_a_stay_that_is_over_does_not_stop_a_reservation(stay_database: BookingDatabase) -> None:
    db = stay_database
    unit = spare_unit(db, "U606")
    # The guest's last night is tonight: the Unit cannot be reserved today.
    made = book(db, unit, 0, 1)
    customer = guest_with_id(db)
    with pytest.raises(ReservationUnitBookedError):
        reserve(db, unit, customer)

    # A day passes (the test moves the booking one day back, which no command may do): the
    # check-out day is today and the guest never came. A booking holds the nights up to, not
    # including, its check-out day (as for a Lease), so the Unit is free to reserve.
    with psycopg.connect(db.owner_url) as connection:
        connection.execute("ALTER TABLE app.short_stay_bookings DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.short_stay_bookings SET check_in_on = check_in_on - 1, "
            "check_out_on = check_out_on - 1 WHERE id = %s",
            (made,),
        )
        connection.execute("ALTER TABLE app.short_stay_bookings ENABLE TRIGGER USER")
    assert read(db, made)["status"] == "BOOKED"
    assert reserve(db, unit, customer).status == "ACTIVE"
