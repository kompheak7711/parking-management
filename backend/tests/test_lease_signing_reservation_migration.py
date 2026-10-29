"""Lease signing completes the Reservation and occupies the Unit; move-in starts Occupancy."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import month_end
from property_rental.identity import AuthenticatedActor
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseCommandInvalidError,
    LeaseSignCommand,
    LeaseSnapshot,
    PostgresLeaseService,
)
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    MoveInInvalidError,
    MoveInOccupant,
    PostgresMoveInService,
    RecordLeaseMoveInCommand,
)
from test_invoice_migration import create_recurring_rent_invoice
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_lease_migration import create_draft
from test_lease_migration import sign_lease as legacy_sign
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)

SNAPSHOT_TABLES = ("leases", "reservations", "deposits", "invoices", "units")
# V1-058 migration 227 adds the Unit setup columns: NULL, or the Floor item linked from the
# Floor text; V1-061 migration 251 adds the default Rent (NULL). Every other value must
# stay as it was.
UNIT_SETUP_COLUMNS = (
    "ARRAY['floor_item_id','size_square_metres','bedrooms','bathrooms',"
    "'view_item_id','kitchen_item_id','notes',"
    "'default_monthly_rent_usd_cents']"
)


def reserved_unit(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """Return actor, Property, Unit, Customer, Reservation and holding deposit."""
    with psycopg.connect(url) as connection:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
        _, ids = create_reservation(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
            expiration_days=10,
        )
    return actor_id, property_id, unit_id, customer_id, ids["reservation_id"], ids["deposit_id"]


def leases(actor_id: UUID, property_id: UUID) -> tuple[PostgresLeaseService, AuthenticatedActor]:
    return (
        PostgresLeaseService(runtime_database_url(), property_id, actor_id),
        actor(actor_id, property_id, LEASE_DRAFT_CAPABILITY, LEASE_SIGN_CAPABILITY),
    )


def business_date(url: str, property_id: UUID) -> date:
    with psycopg.connect(url) as connection:
        return reservation_business_date(connection, property_id)


def signed(
    url: str,
    actor_id: UUID,
    property_id: UUID,
    unit_id: UUID,
    customer_id: UUID,
    reservation_id: UUID | None,
) -> tuple[LeaseSignCommand, LeaseSnapshot]:
    service, who = leases(actor_id, property_id)
    today = business_date(url, property_id)
    draft = draft_command(
        unit_id,
        customer_id,
        start_date=today - timedelta(days=1),
        end_date=month_end(today + timedelta(days=365)),
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
        reservation_id=reservation_id,
    )
    return command, service.sign(command, actor=who)


def state(url: str, query: str, *parameters: object) -> Any:
    with psycopg.connect(url) as connection:
        return connection.execute(query, parameters).fetchone()


def test_signing_with_reservation_completes_it_links_the_holding_deposit_and_occupies_the_unit(
    migrated_database_url: str,
) -> None:
    actor_id, prop, unit, customer, reservation, deposit = reserved_unit(migrated_database_url)
    command, result = signed(migrated_database_url, actor_id, prop, unit, customer, reservation)
    service, who = leases(actor_id, prop)
    assert service.sign(command, actor=who) == result
    assert state(
        migrated_database_url,
        "SELECT status,resulting_lease_id FROM app.reservations WHERE id=%s",
        reservation,
    ) == ("COMPLETED", command.lease_id)
    assert state(
        migrated_database_url, "SELECT lease_id FROM app.deposits WHERE id=%s", deposit
    ) == (command.lease_id,)
    assert state(migrated_database_url, "SELECT status FROM app.units WHERE id=%s", unit) == (
        "OCCUPIED",
    )
    assert state(
        migrated_database_url,
        "SELECT reservation_id,deposit_id,previous_unit_status,count(*) OVER () "
        "FROM app.lease_signing_outcomes WHERE lease_id=%s",
        command.lease_id,
    ) == (reservation, deposit, "RESERVED", 1)
    assert state(
        migrated_database_url,
        "SELECT count(*) FROM app.audit_events WHERE action='lease.signing_outcome.recorded' "
        "AND entity_id=%s",
        command.lease_id,
    ) == (1,)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.reservations SET status='CANCELLED',version=version+1 WHERE id=%s",
                (reservation,),
            )


def test_walk_in_signing_occupies_a_vacant_unit_without_a_reservation(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id, prop, unit, customer = setup_reservation_sources(connection)
    command, _ = signed(migrated_database_url, actor_id, prop, unit, customer, None)
    assert state(migrated_database_url, "SELECT status FROM app.units WHERE id=%s", unit) == (
        "OCCUPIED",
    )
    assert state(
        migrated_database_url,
        "SELECT reservation_id,deposit_id,previous_unit_status FROM app.lease_signing_outcomes "
        "WHERE lease_id=%s",
        command.lease_id,
    ) == (None, None, "VACANT")


def test_reserved_unit_cannot_be_signed_without_its_own_reservation(
    migrated_database_url: str,
) -> None:
    actor_id, prop, unit, customer, reservation, _ = reserved_unit(migrated_database_url)
    _, _, other_unit, _, other_reservation, _ = reserved_unit(migrated_database_url)
    for reservation_id in (None, other_reservation):
        with pytest.raises(LeaseCommandInvalidError):
            signed(migrated_database_url, actor_id, prop, unit, customer, reservation_id)
    assert state(
        migrated_database_url, "SELECT status FROM app.reservations WHERE id=%s", reservation
    ) == ("ACTIVE",)
    assert state(migrated_database_url, "SELECT status FROM app.units WHERE id=%s", unit) == (
        "RESERVED",
    )
    assert other_unit != unit


def move_in_command(
    lease_id: UUID, customer: UUID, day: date, version: int
) -> RecordLeaseMoveInCommand:
    return RecordLeaseMoveInCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=lease_id,
        expected_lease_version=version,
        actual_move_in_date=day,
        occupants=(MoveInOccupant(uuid4(), customer),),
        reason="Customer physically moved in",
        authorization_reference=MOVE_IN_CAPABILITY,
    )


def test_move_in_after_signing_starts_occupancy_without_a_payment_gate(
    migrated_database_url: str,
) -> None:
    actor_id, prop, unit, customer, reservation, _ = reserved_unit(migrated_database_url)
    command, result = signed(migrated_database_url, actor_id, prop, unit, customer, reservation)
    today = business_date(migrated_database_url, prop)
    flow = PostgresMoveInService(runtime_database_url(), prop, actor_id)
    who = actor(actor_id, prop, MOVE_IN_CAPABILITY)
    value = move_in_command(command.lease_id, customer, today, result.version)
    first = flow.record_lease_move_in(value, actor=who)
    assert flow.record_lease_move_in(value, actor=who) == first
    assert state(
        migrated_database_url,
        "SELECT count(*) FROM app.occupancies WHERE lease_id=%s AND move_out_date IS NULL",
        command.lease_id,
    ) == (1,)
    with pytest.raises(MoveInInvalidError):
        flow.record_lease_move_in(
            move_in_command(command.lease_id, customer, today, int(str(first["lease_version"]))),
            actor=who,
        )
    assert state(migrated_database_url, "SELECT status FROM app.units WHERE id=%s", unit) == (
        "OCCUPIED",
    )


def test_lease_signed_before_the_new_path_keeps_the_reservation_move_in(
    migrated_database_url: str,
) -> None:
    actor_id, prop, unit, customer, reservation, _ = reserved_unit(migrated_database_url)
    today = business_date(migrated_database_url, prop)
    with psycopg.connect(migrated_database_url) as connection:
        lease = create_draft(
            connection,
            actor_id=actor_id,
            unit_id=unit,
            primary_tenant_id=customer,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=365),
        )
        legacy_sign(connection, lease, actor_id)
    flow = PostgresMoveInService(runtime_database_url(), prop, actor_id)
    with pytest.raises(MoveInInvalidError):
        flow.record_lease_move_in(
            move_in_command(lease, customer, today, 2),
            actor=actor(actor_id, prop, MOVE_IN_CAPABILITY),
        )
    assert state(
        migrated_database_url, "SELECT status FROM app.reservations WHERE id=%s", reservation
    ) == ("ACTIVE",)


def snapshot(url: str) -> dict[str, Any]:
    with psycopg.connect(url) as connection:
        return {
            table: connection.execute(
                # V1-059 part B adds invoices.draft_reference and customers.id_document_number
                # (NULL on earlier rows); every other value must stay as it was.
                "SELECT COALESCE(jsonb_agg(to_jsonb(t)-'draft_reference'-'id_document_number'"
                f"{'-' + UNIT_SETUP_COLUMNS if table == 'units' else ''} "
                "ORDER BY t.id),'[]'::jsonb) "
                f"FROM app.{table} t"
            ).fetchone()
            for table in SNAPSHOT_TABLES
        }


def test_forward_upgrade_keeps_earlier_leases_reservations_deposits_and_invoices(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("lease_signing_reservation") as temporary:
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20261004_68")
        actor_id, prop, unit, customer, _, _ = reserved_unit(temporary)
        today = business_date(temporary, prop)
        with psycopg.connect(temporary) as connection:
            lease = create_draft(
                connection,
                actor_id=actor_id,
                unit_id=unit,
                primary_tenant_id=customer,
                start_date=today.replace(day=1) - timedelta(days=31),
                end_date=today + timedelta(days=365),
            )
            legacy_sign(connection, lease, actor_id)
            create_recurring_rent_invoice(
                connection,
                actor_id=actor_id,
                customer_id=customer,
                lease_id=lease,
                period_start=today.replace(day=1),
            )
        before = snapshot(temporary)
        alembic_command.upgrade(config, "head")
        assert snapshot(temporary) == before


def test_lease_signing_reservation_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261005_69")
    assert revision is not None and revision.down_revision == "20261004_68"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
