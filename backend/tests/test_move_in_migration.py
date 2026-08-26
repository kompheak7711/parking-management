"""Real PostgreSQL coverage for V1-035 move-in orchestration."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    CompleteMoveInCommand,
    MoveInConflictError,
    MoveInInvalidError,
    MoveInOccupant,
    MoveInVersionConflictError,
    PostgresMoveInService,
)
from test_lease_migration import create_draft, sign_lease
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    alembic_command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required for runtime-role migration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def actor(actor_id: UUID, property_id: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(MOVE_IN_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )


def setup_move_in(
    database_url: str, *, fully_paid: bool = True
) -> tuple[PostgresMoveInService, AuthenticatedActor, CompleteMoveInCommand, UUID]:
    with psycopg.connect(database_url) as connection:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
        business_date = reservation_business_date(connection, property_id)
        _, reservation_ids = create_reservation(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
            expiration_days=10,
        )
        connection.commit()
        if fully_paid:
            connection.execute(
                """
                INSERT INTO app.deposit_receipts(
                    id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id
                ) VALUES (%s,%s,%s,40000,clock_timestamp(),%s)
                """,
                (uuid4(), reservation_ids["deposit_id"], uuid4(), actor_id),
            )
        lease_id = create_draft(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=customer_id,
            start_date=business_date - timedelta(days=1),
            end_date=business_date + timedelta(days=365),
        )
        sign_lease(connection, lease_id, actor_id)
        occupant_id = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES (%s,%s,%s,%s)",
            (occupant_id, "Recorded Non-signer Occupant", actor_id, actor_id),
        )
        unit_version_row = connection.execute(
            "SELECT version FROM app.units WHERE id=%s", (unit_id,)
        ).fetchone()
        assert unit_version_row is not None
        value = CompleteMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=reservation_ids["reservation_id"],
            lease_id=lease_id,
            expected_reservation_version=1,
            expected_lease_version=2,
            expected_unit_version=int(unit_version_row[0]),
            actual_move_in_date=business_date,
            occupants=(MoveInOccupant(uuid4(), occupant_id),),
            reason="All move-in prerequisites verified",
            authorization_reference=MOVE_IN_CAPABILITY,
        )
        connection.commit()
    return (
        PostgresMoveInService(runtime_database_url(), property_id, actor_id),
        actor(actor_id, property_id),
        value,
        reservation_ids["deposit_id"],
    )


def setup_historical_move_in(
    database_url: str, *, signed_day_offset: int, receipt_day_offset: int
) -> tuple[PostgresMoveInService, AuthenticatedActor, CompleteMoveInCommand]:
    with psycopg.connect(database_url) as connection:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
        business_date = reservation_business_date(connection, property_id)
        actual_date = business_date - timedelta(days=2)
        reservation_date = actual_date - timedelta(days=3)
        accepted_at = datetime.combine(reservation_date, time(hour=9), tzinfo=UTC)
        signed_at = datetime.combine(
            actual_date + timedelta(days=signed_day_offset), time(hour=9), tzinfo=UTC
        )
        receipt_at = datetime.combine(
            actual_date + timedelta(days=receipt_day_offset), time(hour=9), tzinfo=UTC
        )
        reservation_id = uuid4()
        acceptance_id = uuid4()
        deposit_id = uuid4()
        connection.execute(
            """
            INSERT INTO app.reservations(
                id,unit_id,customer_id,reservation_date,agreed_monthly_rent_usd_cents,
                original_expiration_date,effective_expiration_date,status,created_by,updated_by
            ) VALUES (%s,%s,%s,%s,50000,%s,%s,'ACTIVE',%s,%s)
            """,
            (
                reservation_id,
                unit_id,
                customer_id,
                reservation_date,
                business_date + timedelta(days=5),
                business_date + timedelta(days=5),
                actor_id,
                actor_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO app.reservation_deposit_acceptances(
                id,reservation_id,suggested_rate_basis_points,suggested_amount_usd_cents,
                accepted_required_amount_usd_cents,acceptance_kind,accepted_at,accepted_by,
                reason,authorization_reference,calculation_trace
            ) VALUES (%s,%s,2000,10000,50000,'AUTHORIZED_VARIANCE',%s,%s,%s,%s,%s)
            """,
            (
                acceptance_id,
                reservation_id,
                accepted_at,
                actor_id,
                "Authorized full Security Deposit requirement",
                "reservations.manage",
                Jsonb(
                    {
                        "agreed_monthly_rent_usd_cents": 50_000,
                        "suggested_rate_basis_points": 2000,
                        "suggested_amount_usd_cents": 10_000,
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO app.deposits(
                id,deposit_type,customer_id,reservation_id,required_usd_cents,
                required_effective_date,created_by,updated_by
            ) VALUES (%s,'SECURITY',%s,%s,50000,%s,%s,%s)
            """,
            (deposit_id, customer_id, reservation_id, reservation_date, actor_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO app.deposit_receipts(
                id,deposit_id,payment_id,amount_usd_cents,occurred_at,actor_id
            ) VALUES (%s,%s,%s,50000,%s,%s)
            """,
            (uuid4(), deposit_id, uuid4(), receipt_at, actor_id),
        )
        connection.execute(
            "UPDATE app.units SET status='RESERVED',version=version+1,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (actor_id, unit_id),
        )
        lease_id = uuid4()
        connection.execute(
            """
            INSERT INTO app.leases(
                id,unit_id,primary_tenant_id,start_date,end_date,monthly_rent_usd_cents,
                created_at,created_by,updated_at,updated_by
            ) VALUES (%s,%s,%s,%s,%s,80000,%s,%s,%s,%s)
            """,
            (
                lease_id,
                unit_id,
                customer_id,
                actual_date - timedelta(days=1),
                business_date + timedelta(days=365),
                accepted_at,
                actor_id,
                accepted_at,
                actor_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO app.lease_signers(
                id,lease_id,customer_id,signed_at,added_at,added_by
            ) VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (uuid4(), lease_id, customer_id, signed_at, accepted_at, actor_id),
        )
        connection.execute(
            """
            UPDATE app.leases SET status='SIGNED',signed_at=%s,version=2,
                updated_at=statement_timestamp(),updated_by=%s WHERE id=%s
            """,
            (signed_at, actor_id, lease_id),
        )
        occupant_id = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) VALUES (%s,%s,%s,%s)",
            (occupant_id, "Historical Move-in Occupant", actor_id, actor_id),
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.commit()
    value = CompleteMoveInCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        reservation_id=reservation_id,
        lease_id=lease_id,
        expected_reservation_version=1,
        expected_lease_version=2,
        expected_unit_version=2,
        actual_move_in_date=actual_date,
        occupants=(MoveInOccupant(uuid4(), occupant_id),),
        reason="Historical move-in chronology verification",
        authorization_reference=MOVE_IN_CAPABILITY,
    )
    return (
        PostgresMoveInService(runtime_database_url(), property_id, actor_id),
        actor(actor_id, property_id),
        value,
    )


def test_complete_move_in_is_atomic_replay_safe_and_preserves_source_history(
    migrated_database_url: str,
) -> None:
    service, authenticated, value, deposit_id = setup_move_in(migrated_database_url)
    result = service.complete(value, actor=authenticated)
    assert service.complete(value, actor=authenticated) == result
    assert result.occupancy_ids == (value.occupants[0].occupancy_id,)

    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status,resulting_lease_id,version FROM app.reservations WHERE id=%s",
            (value.reservation_id,),
        ).fetchone() == ("COMPLETED", value.lease_id, 2)
        assert verify.execute(
            "SELECT status FROM app.units WHERE id=%s", (result.unit_id,)
        ).fetchone() == ("OCCUPIED",)
        assert verify.execute(
            "SELECT reservation_id,lease_id,version FROM app.deposits WHERE id=%s",
            (deposit_id,),
        ).fetchone() == (value.reservation_id, value.lease_id, 2)
        assert verify.execute(
            "SELECT customer_id,move_in_date,move_out_date FROM app.occupancies WHERE id=%s",
            (value.occupants[0].occupancy_id,),
        ).fetchone() == (
            value.occupants[0].customer_id,
            value.actual_move_in_date,
            None,
        )
        assert verify.execute(
            "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (1,)
        assert verify.execute(
            "SELECT status FROM app.lease_revisions WHERE lease_id=%s ORDER BY version",
            (value.lease_id,),
        ).fetchall() == [("DRAFTED",), ("SIGNED",), ("SIGNED",)]

    with pytest.raises(MoveInConflictError):
        service.complete(
            replace(value, reason="Different payload with the same replay key"),
            actor=authenticated,
        )


def test_unpaid_deposit_rolls_back_every_move_in_effect(migrated_database_url: str) -> None:
    service, authenticated, value, deposit_id = setup_move_in(
        migrated_database_url, fully_paid=False
    )
    with pytest.raises(MoveInInvalidError):
        service.complete(value, actor=authenticated)
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status,resulting_lease_id FROM app.reservations WHERE id=%s",
            (value.reservation_id,),
        ).fetchone() == ("ACTIVE", None)
        assert verify.execute(
            "SELECT status,version FROM app.units "
            "WHERE id=(SELECT unit_id FROM app.reservations WHERE id=%s)",
            (value.reservation_id,),
        ).fetchone() == ("RESERVED", 2)
        assert verify.execute(
            "SELECT status,version FROM app.leases WHERE id=%s", (value.lease_id,)
        ).fetchone() == ("SIGNED", 2)
        assert verify.execute(
            "SELECT lease_id,version FROM app.deposits WHERE id=%s", (deposit_id,)
        ).fetchone() == (None, 1)
        assert verify.execute(
            "SELECT count(*) FROM app.occupancies WHERE lease_id=%s", (value.lease_id,)
        ).fetchone() == (0,)
        assert verify.execute(
            "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (0,)


def test_required_pet_deposit_prerequisite_fails_closed(migrated_database_url: str) -> None:
    service, authenticated, value, _ = setup_move_in(migrated_database_url)
    with psycopg.connect(migrated_database_url) as setup:
        setup.execute(
            """
            INSERT INTO app.lease_pet_approvals(
                id,lease_id,approved_date,deposit_required_by_signed_terms,
                pet_description,approved_at,approved_by
            ) VALUES (%s,%s,%s,true,'Approved move-in pet',clock_timestamp(),%s)
            """,
            (uuid4(), value.lease_id, value.actual_move_in_date, service.actor_id),
        )
        setup.commit()
    with pytest.raises(MoveInInvalidError):
        service.complete(value, actor=authenticated)
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status,version FROM app.reservations WHERE id=%s", (value.reservation_id,)
        ).fetchone() == ("ACTIVE", 1)
        assert verify.execute(
            "SELECT status,version FROM app.units "
            "WHERE id=(SELECT unit_id FROM app.reservations WHERE id=%s)",
            (value.reservation_id,),
        ).fetchone() == ("RESERVED", 2)
        assert verify.execute(
            "SELECT status,version FROM app.leases WHERE id=%s", (value.lease_id,)
        ).fetchone() == ("SIGNED", 2)
        assert verify.execute(
            "SELECT lease_id,version FROM app.deposits WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (None, 1)
        assert verify.execute(
            "SELECT count(*) FROM app.occupancies WHERE lease_id=%s", (value.lease_id,)
        ).fetchone() == (0,)
        assert verify.execute(
            "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("signed_day_offset", "receipt_day_offset"),
    ((1, -1), (-1, 1)),
)
def test_backdated_move_in_requires_signing_and_full_payment_by_actual_date(
    migrated_database_url: str,
    signed_day_offset: int,
    receipt_day_offset: int,
) -> None:
    service, authenticated, value = setup_historical_move_in(
        migrated_database_url,
        signed_day_offset=signed_day_offset,
        receipt_day_offset=receipt_day_offset,
    )
    with pytest.raises(MoveInInvalidError):
        service.complete(value, actor=authenticated)
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status,version FROM app.reservations WHERE id=%s", (value.reservation_id,)
        ).fetchone() == ("ACTIVE", 1)
        assert verify.execute(
            "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (0,)


def test_concurrent_completion_has_one_winner_and_one_permanent_event(
    migrated_database_url: str,
) -> None:
    service, authenticated, value, _ = setup_move_in(migrated_database_url)
    barrier = Barrier(2)

    def complete(candidate: CompleteMoveInCommand) -> object:
        barrier.wait()
        try:
            return service.complete(candidate, actor=authenticated)
        except Exception as exc:  # exact class is asserted below
            return exc

    competing = replace(
        value,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        occupants=(MoveInOccupant(uuid4(), value.occupants[0].customer_id),),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(complete, (value, competing)))
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, MoveInVersionConflictError) for item in results) == 1
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.move_in_events WHERE reservation_id=%s",
            (value.reservation_id,),
        ).fetchone() == (1,)


def test_history_runtime_role_and_forward_only_boundary(migrated_database_url: str) -> None:
    service, authenticated, value, _ = setup_move_in(migrated_database_url)
    service.complete(value, actor=authenticated)
    with psycopg.connect(runtime_database_url()) as runtime:
        privileges = runtime.execute(
            """
            SELECT has_table_privilege(current_user,'app.move_in_events','SELECT'),
                   has_table_privilege(current_user,'app.move_in_events','UPDATE'),
                   has_function_privilege(
                     current_user,
                     'app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,integer,date,jsonb,text,text,uuid)',
                     'EXECUTE'
                   )
            """
        ).fetchone()
        assert privileges == (True, False, True)
        with pytest.raises(psycopg.Error) as mutation:
            runtime.execute("DELETE FROM app.move_in_events WHERE id=%s", (value.event_id,))
        assert mutation.value.sqlstate == "42501"
    source = (
        Path(__file__).parents[1] / "migrations/versions/20260826_25_move_in_orchestration.py"
    ).read_text()
    assert "Move-in orchestration migration is forward-only" in source
