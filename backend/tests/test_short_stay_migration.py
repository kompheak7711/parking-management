"""Daily and weekly rent on the real database (migration 20270531_310, phase 6 step 1).

One Unit never has two bookings, or a booking and a signed Lease, on the same night; the booking
wins over a new Lease. The total of a booking is the sum of its price lines. Quotes, price lines,
history and guest notes never change; deposits, housekeeping tasks and damage charges move
forward once. A card number is never saved. Only a check-in makes a Unit Short stay.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
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

REVISION = "20270531_310"
GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"
RIGHTS = {
    "short_stays.read",
    "short_stays.desk",
    "short_stays.housekeeping",
    "short_stays.approve",
    "short_stays.credit",
}
OWNER_RULES = {
    "SS_NIGHT_PERCENT": 30000,
    "SS_NIGHT_DAYS": 30,
    "SS_WEEK_PERCENT": 20000,
    "SS_WEEKS_IN_MONTH_TENTHS": 43,
    "SS_TWO_NIGHTS_OFF": 2000,
    "SS_THREE_NIGHTS_OFF": 3000,
    "SS_TWO_WEEKS_OFF": 1000,
    "SS_THREE_WEEKS_OFF": 1500,
    "SS_MAX_NIGHTS": 29,
    "SS_MONTH_ONLY_STUDIO": 44900,
    "SS_MONTH_ONLY_ONE_BEDROOM": 40500,
    "SS_MONTH_ONLY_TWO_BEDROOM": 74900,
    "SS_CASH_DEPOSIT": 5000,
    "SS_CARD_HOLD": 5000,
    "SS_FREE_CANCEL_DAYS": 2,
    "SS_CREDIT_MONTHS": 12,
    "SS_CHECK_IN_TIME": 840,
    "SS_CHECK_OUT_TIME": 720,
    "SS_LATE_CHECK_OUT_UNTIL": 1080,
    "SS_EARLY_LATE_FEE": 500,
    "SS_EARLY_LATE_FREE_NIGHTS": 7,
    "SS_LEASE_FIRST_MONTH_OFF": 5000,
    "SS_RETURNING_GUEST_OFF": 300,
    "SS_CHANGE_OVER_COST": 500,
    "SS_LINEN_COST": 200,
    "SS_CALENDAR_SYNC_MINUTES": 15,
    # Step 5c (318): report only; site fees start at 0% until the owner sets them.
    "SS_SITE_FEE_BOOKING_COM": 0,
    "SS_SITE_FEE_AGODA": 0,
    "SS_SITE_FEE_AIRBNB": 0,
    "SS_BASE_OCCUPANCY": 4000,
}


@dataclass(frozen=True)
class StayDatabase:
    owner_url: str
    runtime_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    units: tuple[uuid.UUID, ...]
    guest: uuid.UUID
    today: date


@pytest.fixture(scope="module")
def stay_database(migrated_database_url: str) -> Iterator[StayDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_short_stays") as temporary:
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
            units = []
            for number in ("S201", "S202", "S203", "S204", "S205", "S206"):
                unit = uuid.uuid4()
                setup.execute(
                    "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, "
                    "status, created_by, updated_by) "
                    "VALUES (%s, %s, %s, '2', 'STUDIO', 'VACANT', %s, %s)",
                    (unit, property_id, number, owner, owner),
                )
                units.append(unit)
            guest = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
                "VALUES (%s, 'Chea Sophy', '017 222 333', %s, %s)",
                (guest, owner, owner),
            )
            setup.commit()
        yield StayDatabase(
            temporary,
            runtime_url,
            property_id,
            owner,
            manager,
            staff,
            tuple(units),
            guest,
            today[0],
        )


def refused(url: str, state: str, *statements: tuple[str, tuple[Any, ...]]) -> None:
    """Run the statements in one transaction and expect the error at once or at commit."""
    with pytest.raises(psycopg.Error) as caught:
        with psycopg.connect(url) as connection:
            for sql, params in statements:
                connection.execute(sql, params)
    assert caught.value.sqlstate == state, caught.value


BOOK = (
    "INSERT INTO app.short_stay_bookings (id, property_id, unit_id, booking_number, customer_id, "
    "guest_count, check_in_on, check_out_on, source, site_name, total_usd_cents, created_by) "
    "VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s)"
)
LINE = (
    "INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, kind, "
    "quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents) "
    "VALUES (%s, 1, 1, 'NIGHTS', %s, 2900, 0, %s)"
)


def booking_statements(
    db: StayDatabase,
    unit: uuid.UUID,
    start: date,
    nights: int,
    total: int | None = None,
    site: str | None = None,
) -> tuple[uuid.UUID, list[tuple[str, tuple[Any, ...]]]]:
    booking = uuid.uuid4()
    amount = 2900 * nights
    number = "ST" + str(uuid.uuid4().int)[:8]
    return booking, [
        (
            BOOK,
            (
                booking,
                db.property_id,
                unit,
                number,
                db.guest,
                start,
                start + timedelta(days=nights),
                "WALK_IN" if site is None else "BOOKING_SITE",
                site,
                amount if total is None else total,
                db.staff,
            ),
        ),
        (LINE, (booking, nights, amount)),
    ]


def book(
    db: StayDatabase, unit: uuid.UUID, start: date, nights: int, site: str | None = None
) -> uuid.UUID:
    booking, statements = booking_statements(db, unit, start, nights, site=site)
    with psycopg.connect(db.owner_url) as connection:
        for sql, params in statements:
            connection.execute(sql, params)
    return booking


def test_migration_310_follows_the_ledger_method_fix() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270609_320"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()


def test_rights_rules_and_numbers_are_seeded(stay_database: StayDatabase) -> None:
    db = stay_database
    with psycopg.connect(db.owner_url) as connection:
        held = {
            actor: {row[0] for row in connection.execute(GRANTS, (actor,))}
            for actor in (db.owner, db.manager, db.staff)
        }
        assert RIGHTS <= held[db.owner] and RIGHTS <= held[db.manager]
        assert held[db.staff] & RIGHTS == {
            "short_stays.read",
            "short_stays.desk",
            "short_stays.housekeeping",
        }
        groups = connection.execute(
            "SELECT permission.group_code, count(*) FROM app.permissions AS permission "
            "WHERE permission.permission_code LIKE 'SHORT_STAYS_%' GROUP BY 1"
        ).fetchall()
        assert groups == [("SHORT_STAYS", 5)]
        rules: dict[Any, Any] = dict(
            connection.execute(
                "SELECT name.code, rule.value FROM app.business_rule_names AS name "
                "JOIN app.business_rules AS rule ON rule.rule_name_id = name.id "
                "WHERE name.area = 'SHORT_STAYS'"
            ).fetchall()
        )
        assert rules == OWNER_RULES
        formats: dict[Any, Any] = dict(
            connection.execute(
                "SELECT document_type, format FROM app.number_rules "
                "WHERE document_type IN ('SHORT_STAY', 'SHORT_STAY_QUOTE')"
            ).fetchall()
        )
        assert formats == {"SHORT_STAY": "STyy000n", "SHORT_STAY_QUOTE": "SQyy000n"}
        # A rule the program reads keeps a safe range.
        with pytest.raises(psycopg.Error) as caught, connection.transaction():
            connection.execute(
                "INSERT INTO app.business_rules (rule_name_id, value, effective_from, reason, "
                "created_by) SELECT id, 0, DATE '2026-12-01', 'test', %s "
                "FROM app.business_rule_names WHERE code = 'SS_MAX_NIGHTS'",
                (db.owner,),
            )
        assert caught.value.sqlstate == "22023"


def test_one_unit_never_has_two_bookings_on_the_same_night(stay_database: StayDatabase) -> None:
    db = stay_database
    unit = db.units[0]
    start = db.today + timedelta(days=10)
    first = book(db, unit, start, 3)
    _, overlapping = booking_statements(db, unit, start + timedelta(days=2), 2)
    refused(db.owner_url, "23P01", *overlapping)
    # The check-out day is free for the next guest; another Unit is free on the same nights.
    book(db, unit, start + timedelta(days=3), 1)
    book(db, db.units[1], start, 3)
    # A cancelled booking frees its nights.
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "UPDATE app.short_stay_bookings SET status = 'CANCELLED', cancelled_at = now(), "
            "cancelled_by = %s, cancel_reason = 'Guest cancelled', version = version + 1 "
            "WHERE id = %s",
            (db.staff, first),
        )
    book(db, unit, start, 2)


def test_a_booking_and_a_lease_never_share_a_night(stay_database: StayDatabase) -> None:
    db = stay_database
    unit = db.units[2]
    lease_start = db.today + timedelta(days=40)
    with psycopg.connect(db.owner_url) as connection:
        lease = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=unit,
            primary_tenant_id=db.guest,
            start_date=lease_start,
            end_date=lease_start + timedelta(days=180),
        )
        sign_lease(connection, lease, db.owner)
    # A stay that checks out on the Lease's Start Date is fine; one more night is not.
    book(db, unit, lease_start - timedelta(days=3), 3)
    _, into_lease = booking_statements(db, unit, lease_start - timedelta(days=1), 2)
    refused(db.owner_url, "23P01", *into_lease)
    # The booking wins: a new Lease over a booked night is refused.
    other = db.units[3]
    book(db, other, db.today + timedelta(days=5), 2)
    with psycopg.connect(db.owner_url) as connection:
        draft = create_draft(
            connection,
            actor_id=db.owner,
            unit_id=other,
            primary_tenant_id=db.guest,
            start_date=db.today + timedelta(days=6),
            end_date=db.today + timedelta(days=190),
        )
    with pytest.raises(psycopg.Error) as caught:
        with psycopg.connect(db.owner_url) as connection:
            sign_lease(connection, draft, db.owner)
    assert caught.value.sqlstate == "23P01"
    assert "another Unit" in str(caught.value)


def test_the_total_is_the_sum_of_the_price_lines(stay_database: StayDatabase) -> None:
    db = stay_database
    _, wrong = booking_statements(db, db.units[4], db.today + timedelta(days=60), 2, total=9999)
    refused(db.owner_url, "23514", *wrong)
    booking, no_lines = booking_statements(db, db.units[4], db.today + timedelta(days=60), 2)
    refused(db.owner_url, "23514", no_lines[0])
    # An extension prices the whole stay again, with a new price version.
    booking = book(db, db.units[4], db.today + timedelta(days=60), 2)
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.short_stay_price_lines (booking_id, price_version, line_position, "
            "kind, quantity, unit_price_usd_cents, discount_basis_points, amount_usd_cents) "
            "VALUES (%s, 2, 1, 'NIGHTS', 3, 2900, 3000, 6090)",
            (booking,),
        )
        connection.execute(
            "UPDATE app.short_stay_bookings SET check_out_on = check_out_on + 1, "
            "price_version = 2, total_usd_cents = 6090, version = version + 1 WHERE id = %s",
            (booking,),
        )
    # The same price version cannot carry new dates.
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.short_stay_bookings SET check_out_on = check_out_on + 1, "
            "version = version + 1 WHERE id = %s",
            (booking,),
        ),
    )
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.short_stay_price_lines SET amount_usd_cents = 1 WHERE booking_id = %s",
            (booking,),
        ),
    )
    refused(
        db.owner_url,
        "55000",
        ("DELETE FROM app.short_stay_bookings WHERE id = %s", (booking,)),
    )


def test_a_booking_only_moves_forward_and_the_unit_status_follows_the_guest(
    stay_database: StayDatabase,
) -> None:
    db = stay_database
    unit = db.units[5]
    # Paid on the booking site, so the check-in needs (step 3, migration 312) are met.
    booking = book(db, unit, db.today, 2, site="Agoda")
    # Only a check-in makes the Unit Short stay.
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.units SET status = 'SHORT_STAY', version = version + 1, "
            "updated_at = now() WHERE id = %s",
            (unit,),
        ),
    )
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "UPDATE app.short_stay_bookings SET status = 'CHECKED_IN', checked_in_at = now(), "
            "checked_in_by = %s, paid_on_site = true, id_copy_made = true, "
            "house_rules_signed = true, version = version + 1 WHERE id = %s",
            (db.staff, booking),
        )
        connection.execute(
            "UPDATE app.units SET status = 'SHORT_STAY', version = version + 1, "
            "updated_at = now() WHERE id = %s",
            (unit,),
        )
    # The guest is in: the Unit stays Short stay until the check-out.
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.units SET status = 'VACANT', version = version + 1, "
            "updated_at = now() WHERE id = %s",
            (unit,),
        ),
    )
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.short_stay_bookings SET status = 'BOOKED', checked_in_at = NULL, "
            "checked_in_by = NULL, version = version + 1 WHERE id = %s",
            (booking,),
        ),
    )
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "UPDATE app.short_stay_bookings SET status = 'CHECKED_OUT', checked_out_at = now(), "
            "checked_out_by = %s, version = version + 1 WHERE id = %s",
            (db.staff, booking),
        )
        connection.execute(
            "UPDATE app.units SET status = 'CLEANING', version = version + 1, "
            "updated_at = now() WHERE id = %s",
            (unit,),
        )
        status = connection.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit,)
        ).fetchone()
    assert status == ("CLEANING",)
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.short_stay_bookings SET note = 'Late', version = version + 1 WHERE id = %s",
            (booking,),
        ),
    )


def test_a_card_number_is_never_saved_and_steps_move_forward_once(
    stay_database: StayDatabase,
) -> None:
    db = stay_database
    booking = book(db, db.units[1], db.today + timedelta(days=80), 1)
    deposit = (
        "INSERT INTO app.short_stay_deposits (booking_id, kind, amount_usd_cents, "
        "hold_reference, card_last4, taken_by) VALUES (%s, %s, 5000, %s, %s, %s)"
    )
    refused(
        db.owner_url,
        "23514",
        (deposit, (booking, "CARD_HOLD", "4111 1111 1111 1111", None, db.staff)),
    )
    refused(db.owner_url, "23514", (deposit, (booking, "CARD_HOLD", None, None, db.staff)))
    refused(db.owner_url, "23514", (deposit, (booking, "CASH", None, "1111", db.staff)))
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(deposit, (booking, "CARD_HOLD", "AUTH 829301", "4242", db.staff))
        connection.execute(
            "INSERT INTO app.housekeeping_tasks (property_id, unit_id, booking_id, task_on, kind, "
            "created_by) VALUES (%s, %s, %s, %s, 'DAILY_CLEAN', %s)",
            (db.property_id, db.units[1], booking, db.today + timedelta(days=80), db.staff),
        )
        connection.execute(
            "UPDATE app.housekeeping_tasks SET status = 'DONE', done_at = now(), done_by = %s, "
            "version = version + 1 WHERE booking_id = %s",
            (db.staff, booking),
        )
        connection.execute(
            "INSERT INTO app.short_stay_damages (booking_id, description, amount_usd_cents, "
            "asked_by) VALUES (%s, 'Broken glass', 300, %s)",
            (booking, db.staff),
        )
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.housekeeping_tasks SET status = 'SKIPPED', note = 'x', "
            "version = version + 1 WHERE booking_id = %s",
            (booking,),
        ),
    )
    # Keeping a deposit says why; the amount kept is not more than the deposit.
    refused(
        db.owner_url,
        "23514",
        (
            "UPDATE app.short_stay_deposits SET status = 'KEPT', kept_usd_cents = 300, "
            "ended_at = now(), ended_by = %s, version = version + 1 WHERE booking_id = %s",
            (db.manager, booking),
        ),
    )
    with psycopg.connect(db.owner_url) as connection:
        connection.execute(
            "UPDATE app.short_stay_damages SET status = 'APPROVED', decided_at = now(), "
            "decided_by = %s, from_deposit_usd_cents = 300, version = version + 1 "
            "WHERE booking_id = %s",
            (db.manager, booking),
        )
        connection.execute(
            "UPDATE app.short_stay_deposits SET status = 'KEPT', kept_usd_cents = 300, "
            "end_note = 'Broken glass', ended_at = now(), ended_by = %s, "
            "version = version + 1 WHERE booking_id = %s",
            (db.manager, booking),
        )
    refused(
        db.owner_url,
        "55000",
        (
            "UPDATE app.short_stay_deposits SET status = 'RETURNED', kept_usd_cents = 0, "
            "version = version + 1 WHERE booking_id = %s",
            (booking,),
        ),
    )


def test_the_app_reads_but_never_writes_the_tables(stay_database: StayDatabase) -> None:
    db = stay_database
    with psycopg.connect(db.runtime_url) as runtime:
        for table in (
            "short_stay_quotes",
            "short_stay_bookings",
            "short_stay_price_lines",
            "short_stay_booking_events",
            "short_stay_deposits",
            "housekeeping_tasks",
            "short_stay_damages",
            "booking_site_calendars",
            "guest_notes",
        ):
            runtime.execute(f"SELECT count(*) FROM app.{table}")
    _, statements = booking_statements(db, db.units[0], db.today + timedelta(days=300), 1)
    refused(db.runtime_url, "42501", *statements)
    refused(
        db.owner_url,
        "55000",
        ("TRUNCATE app.guest_notes", ()),
    )
