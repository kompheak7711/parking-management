"""Migration 20270327_246 (V1-060 B6, DL-102): Add occupant on a draft or a running Lease.

Before the move-in the person is planned and moves in with the Lease; after it the person gets
their own Occupancy from their own move-in date (BR-OCC-004). Each addition is append-only and
shows in the Lease History, and so does the move-in of a Lease signed with its outcome record.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import month_end
from property_rental.lease import (
    LEASE_DRAFT_CAPABILITY,
    LEASE_SIGN_CAPABILITY,
    LeaseCancelCommand,
    LeaseSignCommand,
)
from property_rental.lease_api import PostgresLeaseResourceFlow
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    AddLeaseOccupantCommand,
    MoveInConflictError,
    MoveInInvalidError,
    MoveInOccupant,
    MoveInVersionConflictError,
    PostgresMoveInService,
    RecordLeaseMoveInCommand,
)
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_lease_signing_reservation_migration import business_date, leases, signed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_reservation_migration import setup_reservation_sources

FUNCTION = "app.add_lease_occupant(uuid,uuid,text,uuid,uuid,integer,uuid,uuid,date,text,text,uuid)"


def _customer(url: str, actor_id: UUID, name: str, *, deactivated: bool = False) -> UUID:
    customer_id = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by,deactivated_at,"
            "deactivation_reason) VALUES (%s,%s,%s,%s,"
            "CASE WHEN %s THEN statement_timestamp() END,CASE WHEN %s THEN 'Left' END)",
            (customer_id, name, actor_id, actor_id, deactivated, deactivated),
        )
    return customer_id


def _walk_in(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    """Return actor, Property, a vacant Unit and its Customer."""
    with psycopg.connect(url) as connection:
        return setup_reservation_sources(connection)


def _add(
    prop: UUID,
    actor_id: UUID,
    lease: UUID,
    version: int,
    customer: UUID,
    day: date | None,
    *,
    key: UUID | None = None,
) -> tuple[AddLeaseOccupantCommand, dict[str, object]]:
    command = AddLeaseOccupantCommand(
        idempotency_key=uuid4() if key is None else key,
        event_id=uuid4(),
        lease_id=lease,
        expected_lease_version=version,
        customer_id=customer,
        occupancy_id=None if day is None else uuid4(),
        move_in_date=day,
        reason="A friend lives here too",
        authorization_reference=MOVE_IN_CAPABILITY,
    )
    service = PostgresMoveInService(runtime_database_url(), prop, actor_id)
    return command, service.add_lease_occupant(
        command, actor=actor(actor_id, prop, MOVE_IN_CAPABILITY)
    )


def _moved_in(url: str) -> tuple[UUID, UUID, UUID, UUID, int, date]:
    """A walk-in Lease signed yesterday's Start Date and moved in today by its tenant alone."""
    actor_id, prop, unit, tenant = _walk_in(url)
    command, result = signed(url, actor_id, prop, unit, tenant, None)
    today = business_date(url, prop)
    moved = PostgresMoveInService(runtime_database_url(), prop, actor_id).record_lease_move_in(
        RecordLeaseMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=command.lease_id,
            expected_lease_version=result.version,
            actual_move_in_date=today,
            occupants=(MoveInOccupant(uuid4(), tenant),),
            reason="Move-in recorded",
            authorization_reference=MOVE_IN_CAPABILITY,
        ),
        actor=actor(actor_id, prop, MOVE_IN_CAPABILITY),
    )
    return actor_id, prop, command.lease_id, tenant, int(str(moved["lease_version"])), today


def test_a_person_added_after_the_move_in_gets_their_own_occupancy_and_history_line(
    migrated_database_url: str,
) -> None:
    """The owner's case: the tenant moved in alone and a friend starts living there later."""
    actor_id, prop, lease, tenant, version, today = _moved_in(migrated_database_url)
    friend = _customer(migrated_database_url, actor_id, "Chan Sopheap")

    command, result = _add(prop, actor_id, lease, version, friend, today)
    replayed = PostgresMoveInService(runtime_database_url(), prop, actor_id).add_lease_occupant(
        command, actor=actor(actor_id, prop, MOVE_IN_CAPABILITY)
    )

    assert replayed == result
    assert result["lease_version"] == version + 1
    assert result["occupancy_id"] == str(command.occupancy_id)
    current = PostgresLeaseResourceFlow(runtime_database_url()).get(lease)
    assert current.version == version + 1
    assert sorted((value.customer_name, value.move_in_date) for value in current.occupancies) == (
        sorted([(current.primary_tenant_name, today), ("Chan Sopheap", today)])
    )
    assert friend not in current.planned_occupant_customer_ids
    kinds = [event.event_kind for event in current.timeline]
    assert kinds.count("lease.move_in") == 1
    assert kinds.count("lease.occupant_added") == 1
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT customer_id,occupancy_id,move_in_date,reason,authorization_reference "
            "FROM app.lease_occupant_additions WHERE id=%s",
            (command.event_id,),
        ).fetchone() == (
            friend,
            command.occupancy_id,
            today,
            "A friend lives here too",
            "reservations.complete",
        )
        # An occupant who did not sign owes nothing (BR-OCC-006): no Signer, no new Invoice.
        assert connection.execute(
            "SELECT count(*) FROM app.lease_signers WHERE lease_id=%s AND customer_id=%s",
            (lease, friend),
        ).fetchone() == (0,)
    assert tenant != friend


def test_add_occupant_after_the_move_in_keeps_the_dates_and_people_rules(
    migrated_database_url: str,
) -> None:
    actor_id, prop, lease, tenant, version, today = _moved_in(migrated_database_url)
    friend = _customer(migrated_database_url, actor_id, "Keo Malis")
    gone = _customer(migrated_database_url, actor_id, "Former Customer", deactivated=True)

    refused: list[tuple[UUID, date | None]] = [
        (friend, today - timedelta(days=1)),  # before the Lease's move-in
        (friend, today + timedelta(days=1)),  # after today
        (friend, None),  # planned after the move-in: they need their own date
        (tenant, today),  # the Primary Tenant already lives there
        (gone, today),  # a deactivated Customer
    ]
    for customer, day in refused:
        with pytest.raises(MoveInInvalidError):
            _add(prop, actor_id, lease, version, customer, day)
    with pytest.raises(MoveInVersionConflictError):
        _add(prop, actor_id, lease, version - 1, friend, today)

    key = uuid4()
    _add(prop, actor_id, lease, version, friend, today, key=key)
    with pytest.raises(MoveInConflictError):
        # The same key with other values is refused, not replayed.
        _add(prop, actor_id, lease, version, tenant, today, key=key)
    with pytest.raises(MoveInInvalidError):
        # Someone already living there is not added twice.
        _add(prop, actor_id, lease, version + 1, friend, today)
    with pytest.raises(ValueError, match="come together"):
        AddLeaseOccupantCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease,
            expected_lease_version=version,
            customer_id=friend,
            occupancy_id=uuid4(),
            move_in_date=None,
            reason="No date",
            authorization_reference=MOVE_IN_CAPABILITY,
        )


def test_a_person_added_before_the_move_in_is_planned_and_moves_in_with_the_lease(
    migrated_database_url: str,
) -> None:
    actor_id, prop, unit, tenant = _walk_in(migrated_database_url)
    friend = _customer(migrated_database_url, actor_id, "Sok Lina")
    later = _customer(migrated_database_url, actor_id, "Ly Dara")
    service, who = leases(actor_id, prop)
    today = business_date(migrated_database_url, prop)
    draft = replace(
        draft_command(
            unit,
            tenant,
            start_date=today - timedelta(days=1),
            end_date=month_end(today + timedelta(days=365)),
        ),
        planned_occupant_customer_ids=(tenant,),
    )
    service.draft_with_terms(draft, actor=who)
    lease = draft.lease_id
    flow = PostgresLeaseResourceFlow(runtime_database_url())

    # On the draft.
    _add(prop, actor_id, lease, 1, friend, None)
    on_draft = flow.get(lease)
    assert on_draft.planned_occupant_customer_ids == (tenant, friend)
    assert [value.customer_name for value in on_draft.planned_occupants][1] == "Sok Lina"
    for customer in (friend, tenant):
        with pytest.raises(MoveInInvalidError):
            _add(prop, actor_id, lease, on_draft.version, customer, None)
    with pytest.raises(MoveInInvalidError):
        # Nobody has moved in yet, so nobody gets a date of their own.
        _add(prop, actor_id, lease, on_draft.version, later, today)

    # On the signed Lease before its move-in.
    service.record_signature(
        signature_command(lease, draft.primary_signer_id, on_draft.version), actor=who
    )
    signing = service.sign(
        LeaseSignCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease,
            expected_version=on_draft.version + 1,
            signed_at=database_now(),
            reason="Lease signed",
            authorization_reference=LEASE_SIGN_CAPABILITY,
            reservation_id=None,
        ),
        actor=actor(actor_id, prop, LEASE_SIGN_CAPABILITY),
    )
    _add(prop, actor_id, lease, signing.version, later, None)
    planned = flow.get(lease)
    assert planned.planned_occupant_customer_ids == (tenant, friend, later)
    assert planned.occupancies == ()
    assert [event.event_kind for event in planned.timeline].count("lease.occupant_added") == 2

    # Record move-in takes the planned people with the Lease's move-in date.
    PostgresMoveInService(runtime_database_url(), prop, actor_id).record_lease_move_in(
        RecordLeaseMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=lease,
            expected_lease_version=planned.version,
            actual_move_in_date=today,
            occupants=tuple(
                MoveInOccupant(uuid4(), value) for value in planned.planned_occupant_customer_ids
            ),
            reason="Move-in recorded",
            authorization_reference=MOVE_IN_CAPABILITY,
        ),
        actor=actor(actor_id, prop, MOVE_IN_CAPABILITY),
    )
    moved = flow.get(lease)
    assert sorted(value.customer_name for value in moved.occupancies) == sorted(
        [moved.primary_tenant_name, "Sok Lina", "Ly Dara"]
    )
    assert {value.move_in_date for value in moved.occupancies} == {today}


def test_add_occupant_is_refused_on_a_renewal_without_its_own_move_in_or_a_cancelled_lease(
    migrated_database_url: str,
) -> None:
    actor_id, prop, lease, tenant, version, today = _moved_in(migrated_database_url)
    friend = _customer(migrated_database_url, actor_id, "Heng Sreypov")
    service, who = leases(actor_id, prop)
    current = PostgresLeaseResourceFlow(runtime_database_url()).get(lease)
    assert current.end_date is not None and current.unit_id is not None
    renewal = replace(
        draft_command(
            current.unit_id,
            tenant,
            start_date=current.end_date + timedelta(days=1),
            end_date=month_end(current.end_date + timedelta(days=365)),
        ),
        predecessor_lease_id=lease,
    )
    service.draft(renewal, actor=who)
    with pytest.raises(MoveInInvalidError):
        _add(prop, actor_id, renewal.lease_id, 1, friend, None)

    _, _, unit, other_tenant = _walk_in(migrated_database_url)
    cancelled = draft_command(unit, other_tenant)
    service.draft(cancelled, actor=who)
    ended = service.cancel(
        LeaseCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            lease_id=cancelled.lease_id,
            expected_version=1,
            reason="Customer chose another Unit",
            authorization_reference=LEASE_DRAFT_CAPABILITY,
        ),
        actor=who,
    )
    with pytest.raises(MoveInInvalidError):
        _add(prop, actor_id, cancelled.lease_id, ended.version, friend, None)
    assert version > 1 and today is not None


def test_the_addition_store_is_append_only_and_written_only_by_the_definer_function(
    migrated_database_url: str,
) -> None:
    actor_id, prop, lease, _, version, today = _moved_in(migrated_database_url)
    friend = _customer(migrated_database_url, actor_id, "Pich Sothea")
    command, _ = _add(prop, actor_id, lease, version, friend, today)
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT routine.prosecdef, routine.proconfig @> ARRAY['search_path=pg_catalog'],"
            "has_function_privilege('public',%s,'EXECUTE'),"
            "has_function_privilege('prm_runtime',%s,'EXECUTE'),"
            "has_function_privilege('prm_financial',%s,'EXECUTE'),"
            "has_table_privilege('prm_runtime','app.lease_occupant_additions','SELECT'),"
            "has_table_privilege('prm_runtime','app.lease_occupant_additions','INSERT'),"
            "has_table_privilege('prm_runtime','app.lease_occupant_additions','UPDATE') "
            "FROM pg_catalog.pg_proc AS routine WHERE routine.oid=%s::regprocedure",
            (FUNCTION, FUNCTION, FUNCTION, FUNCTION),
        ).fetchone() == (True, True, False, True, False, True, False, False)
        for statement in (
            "UPDATE app.lease_occupant_additions SET reason='Changed' WHERE id=%s",
            "DELETE FROM app.lease_occupant_additions WHERE id=%s",
        ):
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute(statement, (command.event_id,))
        with pytest.raises(psycopg.Error):
            with connection.transaction():
                connection.execute("TRUNCATE app.lease_occupant_additions")


def test_add_occupant_migration_follows_the_deposit_migration_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "20270327_246"
    revision = scripts.get_revision("20270327_246")
    assert revision is not None and revision.down_revision == "20270326_245"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
