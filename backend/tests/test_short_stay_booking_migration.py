"""Daily and weekly rent: price, calendar and new booking (migration 20270601_311, step 2).

The owner's price rules: night = 300% of the monthly rent / 30 and week = 200% / 4.3, each rounded
down to a whole dollar; 2 nights 20% off, 3 to 6 nights 30% off; whole weeks with 2 weeks 10% off
and 3 weeks or more 15% off; extra nights at the 3-to-6-night price; never more than the next whole
week (card answer 04/11/2026 16:21); at most 29 nights. Prices match the owner's table of 04/11.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_default_role_bundles_migration import SEED_QUERY
from test_lease_migration import create_draft, sign_lease
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

REVISION = "20270601_311"
PRICE = "SELECT app.short_stay_price_read(%s, %s, %s, %s, %s)"
BOOK = "SELECT app.make_short_stay_booking(%s, %s::jsonb, %s, NULL)"


@dataclass(frozen=True)
class BookingDatabase:
    owner_url: str
    runtime_url: str
    property_id: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    studio: uuid.UUID
    one_bedroom: uuid.UUID
    two_bedroom: uuid.UUID
    no_rent: uuid.UUID
    leased: uuid.UUID
    guest: uuid.UUID
    today: date


@contextmanager
def short_stay_database(name: str) -> Iterator[BookingDatabase]:
    """A migrated database with the Units, staff, a guest and a Lease the short-stay tests use."""
    with _temporary_migration_database(name) as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        name = urlsplit(temporary).path.lstrip("/")
        runtime_url = _url_with_database(runtime_database_url(), name)
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            for actor, bundle in ((manager, seeded[1]), (staff, seeded[2])):
                setup.execute(
                    "INSERT INTO app.user_role_assignments (assignment_id, actor_id, "
                    "role_bundle_id, property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
                    (uuid.uuid4(), actor, bundle, property_id),
                )
            today = setup.execute(
                "SELECT timezone(timezone_name, statement_timestamp())::date FROM app.properties "
                "WHERE id = %s",
                (property_id,),
            ).fetchone()
            assert today is not None
            units: list[uuid.UUID] = []
            for number, kind, rent in (
                ("U501", "STUDIO", 29900),
                ("U503", "ONE_BEDROOM", 26900),
                ("U505", "TWO_BEDROOM", 49900),
                ("U506", "STUDIO", None),
                ("U507", "STUDIO", 29900),
            ):
                unit = uuid.uuid4()
                setup.execute(
                    "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, "
                    "status, default_monthly_rent_usd_cents, created_by, updated_by) "
                    "VALUES (%s, %s, %s, '5', %s, 'VACANT', %s, %s, %s)",
                    (unit, property_id, number, kind, rent, owner, owner),
                )
                units.append(unit)
            guest = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
                "VALUES (%s, 'Lim Dara', '010 333 444', %s, %s)",
                (guest, owner, owner),
            )
            lease = create_draft(
                setup,
                actor_id=owner,
                unit_id=units[4],
                primary_tenant_id=guest,
                start_date=today[0] + timedelta(days=20),
                end_date=today[0] + timedelta(days=200),
            )
            sign_lease(setup, lease, owner)
            setup.commit()
        yield BookingDatabase(
            temporary,
            runtime_url,
            property_id,
            manager,
            staff,
            units[0],
            units[1],
            units[2],
            units[3],
            units[4],
            guest,
            today[0],
        )


@pytest.fixture(scope="module")
def booking_database(migrated_database_url: str) -> Iterator[BookingDatabase]:
    assert migrated_database_url
    with short_stay_database("prm_short_stay_bookings") as database:
        yield database


def run(url: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(url: str, state: str, sql: str, *params: Any) -> str:
    with pytest.raises(psycopg.Error) as caught:
        run(url, sql, *params)
    assert caught.value.sqlstate == state, caught.value
    return str(caught.value)


def price(db: BookingDatabase, unit: uuid.UUID, nights: int, start: int = 30) -> dict[str, Any]:
    check_in = db.today + timedelta(days=start)
    found = run(
        db.runtime_url,
        PRICE,
        db.property_id,
        unit,
        check_in,
        check_in + timedelta(days=nights),
        db.staff,
    )
    assert isinstance(found, dict)
    return found


def test_migration_311_follows_step_1() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270531_310"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_the_prices_match_the_owner_table(booking_database: BookingDatabase) -> None:
    db = booking_database
    # (unit, night, week, 2 nights, 3 nights, 2 weeks, 3 weeks), in cents.
    for unit, night, week, two, three, two_weeks, three_weeks in (
        (db.studio, 2900, 13900, 4640, 6090, 25000, 35400),
        (db.one_bedroom, 2600, 12500, 4160, 5460, 22500, 31800),
        (db.two_bedroom, 4900, 23200, 7840, 10290, 41700, 59100),
    ):
        one = price(db, unit, 1)
        assert (one["night_usd_cents"], one["week_usd_cents"]) == (night, week)
        assert one["total_usd_cents"] == night
        assert price(db, unit, 2)["total_usd_cents"] == two
        assert price(db, unit, 3)["total_usd_cents"] == three
        assert price(db, unit, 7)["total_usd_cents"] == week
        assert price(db, unit, 14)["total_usd_cents"] == two_weeks
        assert price(db, unit, 21)["total_usd_cents"] == three_weeks


def test_weeks_extra_nights_and_never_more_than_the_next_week(
    booking_database: BookingDatabase,
) -> None:
    db = booking_database
    totals = {nights: price(db, db.one_bedroom, nights) for nights in range(1, 30)}
    assert totals[8]["total_usd_cents"] == 12500 + 1820
    assert totals[8]["lines"] == [
        {
            "position": 1,
            "kind": "WEEKS",
            "quantity": 1,
            "unit_price_usd_cents": 12500,
            "discount_basis_points": 0,
            "amount_usd_cents": 12500,
        },
        {
            "position": 2,
            "kind": "NIGHTS",
            "quantity": 1,
            "unit_price_usd_cents": 2600,
            "discount_basis_points": 3000,
            "amount_usd_cents": 1820,
        },
    ]
    # 13 nights would be $234.20: the guest pays 2 weeks, $225.
    assert totals[13]["total_usd_cents"] == 22500
    assert totals[13]["charged_as_whole_weeks"] is True
    assert totals[12]["total_usd_cents"] == 12500 + 5 * 1820
    # 4 weeks get the 3-week discount; 27 nights would be $427.20 and cost $425.
    assert totals[28]["total_usd_cents"] == 42500
    assert totals[27]["total_usd_cents"] == 42500
    assert totals[29]["total_usd_cents"] == 42500 + 1820
    # A longer stay never costs less than a shorter one.
    values = [totals[nights]["total_usd_cents"] for nights in range(1, 30)]
    assert values == sorted(values)
    # The monthly hint: 27 nights cost more than the 1-month-only rent of $405.
    assert totals[27]["month_only_usd_cents"] == 40500
    assert totals[27]["suggest_month"] is True
    assert totals[20]["suggest_month"] is False
    refused(
        db.runtime_url,
        "22023",
        PRICE,
        db.property_id,
        db.one_bedroom,
        db.today,
        db.today + timedelta(days=30),
        db.staff,
    )
    refused(
        db.runtime_url,
        "55000",
        PRICE,
        db.property_id,
        db.no_rent,
        db.today,
        db.today + timedelta(days=2),
        db.staff,
    )


def booking(db: BookingDatabase, unit: uuid.UUID, start: int, nights: int, **extra: Any) -> str:
    check_in = db.today + timedelta(days=start)
    body = {
        "unit_id": str(unit),
        "customer_id": str(db.guest),
        "guest_count": 2,
        "check_in_on": str(check_in),
        "check_out_on": str(check_in + timedelta(days=nights)),
        "source": "WALK_IN",
    } | extra
    return json.dumps(body)


def test_a_new_booking_keeps_its_price_and_history(booking_database: BookingDatabase) -> None:
    db = booking_database
    made = run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 3, 3), db.staff)
    found = run(
        db.runtime_url,
        "SELECT app.short_stay_booking_read(%s, %s, %s)",
        db.property_id,
        made,
        db.manager,
    )
    assert found["booking_number"].startswith("ST")
    assert found["status"] == "BOOKED" and found["nights"] == 3
    assert found["total_usd_cents"] == 6090 and found["guest_name"] == "Lim Dara"
    assert [line["amount_usd_cents"] for line in found["lines"]] == [6090]
    assert [event["kind"] for event in found["history"]] == ["BOOKED"]
    # The same nights are taken; the check-out day is free.
    message = refused(
        db.runtime_url, "55000", BOOK, db.property_id, booking(db, db.studio, 4, 2), db.staff
    )
    assert "BOOKED" in message
    run(db.runtime_url, BOOK, db.property_id, booking(db, db.studio, 6, 1), db.staff)
    # A Lease night, a past day, a booking site without its name.
    assert "LEASE" in refused(
        db.runtime_url, "55000", BOOK, db.property_id, booking(db, db.leased, 19, 2), db.staff
    )
    assert "PAST" in refused(
        db.runtime_url, "55000", BOOK, db.property_id, booking(db, db.studio, -1, 1), db.staff
    )
    refused(
        db.runtime_url,
        "22023",
        BOOK,
        db.property_id,
        booking(db, db.two_bedroom, 3, 1, source="BOOKING_SITE"),
        db.staff,
    )
    run(
        db.runtime_url,
        BOOK,
        db.property_id,
        booking(
            db,
            db.two_bedroom,
            3,
            1,
            source="BOOKING_SITE",
            site_name="Booking.com",
            site_reference="BK-55821",
        ),
        db.staff,
    )
    calendar = run(
        db.runtime_url,
        "SELECT app.short_stay_calendar(%s, %s, 30, %s)",
        db.property_id,
        db.today,
        db.staff,
    )
    by_number = {unit["unit_number"]: unit for unit in calendar["units"]}
    assert [item["check_in_on"] for item in by_number["U501"]["bookings"]] == [
        str(db.today + timedelta(days=3)),
        str(db.today + timedelta(days=6)),
    ]
    assert by_number["U507"]["leases"][0]["start_date"] == str(db.today + timedelta(days=20))
    listed = run(
        db.runtime_url, "SELECT app.short_stay_bookings_read(%s, %s)", db.property_id, db.staff
    )
    assert len(listed) == 3
    rules = run(
        db.owner_url,
        "SELECT count(*) FROM app.business_rule_names WHERE area = 'SHORT_STAYS' AND used_by_app",
    )
    assert rules >= 12  # step 2 uses 12; later steps use more
