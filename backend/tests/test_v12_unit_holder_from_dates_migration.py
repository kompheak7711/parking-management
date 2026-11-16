"""C2 (DL-241): who holds a Unit is worked out from the dates of its records.

Owner (12 Nov 2026, DL-226, C2): Reserved, Occupied and Short stay come from the Reservations,
Leases and short stays on the day asked; only the condition (Vacant, Cleaning, Under
maintenance, Out of service) is stored and set by staff.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import month_end
from property_rental.lease import (
    LEASE_SIGN_CAPABILITY,
    LeaseCommandInvalidError,
    LeaseSignCommand,
)
from test_lease_lifecycle_migration import database_now, draft_command, signature_command
from test_lease_signing_reservation_migration import business_date, leases, reserved_unit
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_reservation_migration import create_reservation, setup_reservation_sources

REVISION = "20270803_421"
FUNCTIONS = (
    "app.unit_today(uuid)",
    "app.unit_lease_held(uuid,uuid)",
    "app.unit_held_by(uuid,date)",
    "app.unit_status_on(uuid,date)",
    "app.unit_lease_from(uuid,date)",
)


def _sign(
    actor: UUID,
    prop: UUID,
    unit: UUID,
    customer: UUID,
    starts: date,
    ends: date | None = None,
    *,
    refused: bool = False,
) -> UUID:
    service, who = leases(actor, prop)
    draft = draft_command(
        unit,
        customer,
        start_date=starts,
        end_date=ends or month_end(starts + timedelta(days=365)),
    )
    service.draft(draft, actor=who)
    service.record_signature(
        signature_command(draft.lease_id, draft.primary_signer_id, 1), actor=who
    )
    command = LeaseSignCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=draft.lease_id,
        expected_version=2,
        signed_at=database_now(),
        reason="Lease signed",
        authorization_reference=LEASE_SIGN_CAPABILITY,
        reservation_id=None,
    )
    if refused:
        # Only the signing is refused; the draft and its signature were saved.
        with pytest.raises(LeaseCommandInvalidError):
            service.sign(command, actor=who)
    else:
        service.sign(command, actor=who)
    return draft.lease_id


def _unit(url: str, unit: UUID, day: date) -> tuple[object, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT app.unit_status_on(id, %s), status, app.unit_lease_from(id, %s) "
            "FROM app.units WHERE id = %s",
            (day, day, unit),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _condition(url: str, unit: UUID, condition: str) -> None:
    with psycopg.connect(url) as connection:
        connection.execute(
            "UPDATE app.units SET status = %s, version = version + 1, "
            "updated_at = statement_timestamp() WHERE id = %s",
            (condition, unit),
        )


def test_a_lease_that_starts_later_leaves_the_unit_vacant_until_its_start(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        actor, prop, unit, customer = setup_reservation_sources(connection)
    today = business_date(url, prop)
    first_end = month_end(today)
    starts = first_end + timedelta(days=40)
    _sign(actor, prop, unit, customer, starts)
    # Signed today, starting next month or later: Vacant until then, with the start date shown.
    assert _unit(url, unit, today) == ("VACANT", "VACANT", starts)
    assert _unit(url, unit, starts - timedelta(days=1)) == ("VACANT", "VACANT", starts)
    assert _unit(url, unit, starts) == ("OCCUPIED", "VACANT", None)
    # The Lease still holds the Unit: no Reservation and no other new Lease (as before).
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error):
        create_reservation(
            connection, actor_id=actor, property_id=prop, unit_id=unit, customer_id=customer
        )
    # A Lease for the free days before it (not a renewal) is refused, as before.
    _sign(actor, prop, unit, customer, today, first_end, refused=True)


def test_a_reservation_holds_the_unit_and_staff_keep_its_condition(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    actor, prop, unit, customer, _, _ = reserved_unit(url)
    today = business_date(url, prop)
    assert _unit(url, unit, today) == ("RESERVED", "VACANT", None)
    _condition(url, unit, "CLEANING")
    assert _unit(url, unit, today) == ("RESERVED", "CLEANING", None)
    with psycopg.connect(url) as connection:
        for held in ("RESERVED", "OCCUPIED", "SHORT_STAY"):
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE app.units SET status = %s, version = version + 1 WHERE id = %s",
                    (held, unit),
                )
            connection.rollback()
        with pytest.raises(psycopg.Error):
            create_reservation(
                connection, actor_id=actor, property_id=prop, unit_id=unit, customer_id=customer
            )


def test_maintenance_on_an_occupied_unit_shows_occupied_and_keeps_the_condition(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        actor, prop, unit, customer = setup_reservation_sources(connection)
    today = business_date(url, prop)
    _sign(actor, prop, unit, customer, today - timedelta(days=1))
    _condition(url, unit, "UNDER_MAINTENANCE")
    assert _unit(url, unit, today) == ("OCCUPIED", "UNDER_MAINTENANCE", None)
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT app.unit_held_by(%s, %s), app.unit_lease_held(%s, NULL)",
            (unit, today, unit),
        ).fetchone() == ("OCCUPIED", True)


def test_the_migration_is_forward_only_and_its_functions_are_for_the_app_roles(
    migrated_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270802_399"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with psycopg.connect(migrated_database_url) as connection:
        for function in FUNCTIONS:
            grants = connection.execute(
                "SELECT role, has_function_privilege(role, %s, 'EXECUTE') "
                "FROM unnest(ARRAY['prm_bootstrap','prm_financial','prm_runtime']) role "
                "ORDER BY role",
                (function,),
            ).fetchall()
            assert grants == [
                ("prm_bootstrap", False),
                ("prm_financial", True),
                ("prm_runtime", True),
            ], function
        triggers = connection.execute(
            "SELECT tgname FROM pg_trigger WHERE tgname IN ('units_validate_reservation_summary',"
            "'reservations_validate_unit_summary','units_short_stay_status')"
        ).fetchall()
    assert triggers == []
