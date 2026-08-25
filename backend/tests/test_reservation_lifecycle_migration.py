"""Real PostgreSQL coverage for V1-030 Reservation lifecycle services."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import (
    CancellationResponsibility,
    DepositOutcomeState,
    PostgresReservationService,
    ReservationCancelCommand,
    ReservationCreateCommand,
    ReservationExtendCommand,
    ReservationStatus,
)
from test_reservation_migration import (
    create_reservation,
    reservation_business_date,
    setup_reservation_sources,
)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Apply all migrations to the disposable PostgreSQL database."""
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    assert value is not None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    assert value is not None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_actor(
    actor_id: UUID, property_id: UUID, outcome_capability: str
) -> AuthenticatedActor:
    property_scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {
                CapabilityGrant("reservations.cancel", property_scope),
                CapabilityGrant(outcome_capability, property_scope),
            }
        ),
    )


def active_reservation(
    connection: Connection[tuple[object, ...]],
    *,
    expiration_days: int = 10,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
        expiration_days=expiration_days,
    )
    return actor_id, property_id, unit_id, customer_id, identities["reservation_id"]


def expired_reservation(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """Create a complete V1-029 activation bundle whose full expiration day passed."""
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    reservation_id = uuid4()
    deposit_id = uuid4()
    business_date = reservation_business_date(connection, property_id)
    reservation_date = business_date - timedelta(days=4)
    expiration_date = business_date - timedelta(days=1)
    occurred_at = datetime.now(UTC) - timedelta(days=4)
    connection.execute(
        """
        INSERT INTO app.reservations (
            id, unit_id, customer_id, reservation_date,
            agreed_monthly_rent_usd_cents, original_expiration_date,
            effective_expiration_date, status, created_at, created_by,
            updated_at, updated_by
        ) VALUES (%s,%s,%s,%s,50000,%s,%s,'ACTIVE',%s,%s,%s,%s)
        """,
        (
            reservation_id,
            unit_id,
            customer_id,
            reservation_date,
            expiration_date,
            expiration_date,
            occurred_at,
            actor_id,
            occurred_at,
            actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.reservation_deposit_acceptances (
            id, reservation_id, suggested_rate_basis_points,
            suggested_amount_usd_cents, accepted_required_amount_usd_cents,
            acceptance_kind, accepted_at, accepted_by, reason,
            authorization_reference, calculation_trace
        ) VALUES (%s,%s,2000,10000,10000,'NORMAL_SUGGESTION',%s,%s,%s,%s,%s)
        """,
        (
            uuid4(),
            reservation_id,
            occurred_at,
            actor_id,
            "Explicitly accepted initial Security Deposit",
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
        INSERT INTO app.deposits (
            id, deposit_type, customer_id, reservation_id,
            required_usd_cents, required_effective_date, created_by, updated_by
        ) VALUES (%s,'SECURITY',%s,%s,50000,%s,%s,%s)
        """,
        (deposit_id, customer_id, reservation_id, reservation_date, actor_id, actor_id),
    )
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s,%s,%s,10000,%s,%s)
        """,
        (uuid4(), deposit_id, uuid4(), occurred_at, actor_id),
    )
    connection.execute(
        """
        UPDATE app.units
        SET status = 'RESERVED', version = version + 1,
            updated_at = statement_timestamp(), updated_by = %s
        WHERE id = %s
        """,
        (actor_id, unit_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    return actor_id, property_id, unit_id, customer_id, reservation_id, deposit_id


def cancel(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    reservation_id: UUID,
    idempotency_key: UUID,
    event_id: UUID,
    outcome_id: UUID | None = None,
    digest: str = "c" * 64,
    expected_version: int = 1,
    responsibility: str = "CUSTOMER",
    property_could_provide_unit: bool = True,
    coordination_reference: str | None = None,
    refund_number: str | None = None,
) -> tuple[object, ...]:
    outcome_id = outcome_id or uuid4()
    if responsibility == "PROPERTY" and refund_number is None:
        refund_number = f"RF-{outcome_id}"
    row = connection.execute(
        "SELECT * FROM app.cancel_reservation_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            property_id,
            idempotency_key,
            digest,
            event_id,
            outcome_id,
            refund_number,
            reservation_id,
            expected_version,
            "CUSTOMER_WITHDREW"
            if responsibility == "CUSTOMER"
            else "PROPERTY_UNABLE_TO_PROVIDE_UNIT",
            responsibility,
            property_could_provide_unit,
            "Approved cancellation reason",
            coordination_reference,
            "reservations.cancel",
            "reservation_deposits.dispose"
            if responsibility == "CUSTOMER"
            else "reservation_deposits.refund",
            actor_id,
        ),
    ).fetchone()
    assert row is not None
    return row


def test_postgres_service_creates_extends_and_cancels_one_stable_reservation(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(setup)
        business_date = reservation_business_date(setup, property_id)
        setup.commit()
    occurred_at = datetime.now(UTC)
    service = PostgresReservationService(
        runtime_database_url(),
        property_id,
        actor_id,
        financial_database_url=financial_database_url(),
    )
    create_command = ReservationCreateCommand(
        idempotency_key=uuid4(),
        reservation_id=uuid4(),
        unit_id=unit_id,
        customer_id=customer_id,
        reservation_date=business_date,
        agreed_monthly_rent_usd_cents=50_000,
        original_expiration_date=business_date + timedelta(days=10),
        acceptance_id=uuid4(),
        accepted_required_amount_usd_cents=10_000,
        acceptance_kind="NORMAL_SUGGESTION",
        accepted_at=occurred_at,
        acceptance_reason="Explicitly accepted initial Security Deposit",
        authorization_reference="reservations.manage",
        calculation_trace={
            "agreed_monthly_rent_usd_cents": 50_000,
            "suggested_rate_basis_points": 2000,
            "suggested_amount_usd_cents": 10_000,
        },
        deposit_id=uuid4(),
        required_deposit_usd_cents=50_000,
        receipt_id=uuid4(),
        payment_id=uuid4(),
        received_at=occurred_at,
    )

    created = service.create(create_command)
    extended = service.extend(
        ReservationExtendCommand(
            idempotency_key=uuid4(),
            notice_id=uuid4(),
            reservation_id=created.reservation_id,
            expected_version=created.version,
            new_expiration_date=created.effective_expiration_date + timedelta(days=2),
            approved_at=datetime.now(UTC),
            reason_memo="Authorized extension",
            authorization_reference="reservations.extend",
        )
    )
    cancelled = service.cancel(
        ReservationCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            outcome_id=uuid4(),
            reservation_id=created.reservation_id,
            expected_version=extended.version,
            reason_code="CUSTOMER_WITHDREW",
            responsibility=CancellationResponsibility.CUSTOMER,
            property_could_provide_unit=True,
            reason_memo="Customer requested cancellation",
            coordination_reference=None,
            authorization_reference="reservations.cancel",
            outcome_authorization_reference="reservation_deposits.dispose",
            refund_number=None,
        ),
        actor=financial_actor(actor_id, property_id, "reservation_deposits.dispose"),
    )

    assert created.status is ReservationStatus.ACTIVE
    assert created.version == 1
    assert extended.status is ReservationStatus.ACTIVE
    assert extended.version == 2
    assert cancelled.status is ReservationStatus.CANCELLED
    assert cancelled.version == 3
    assert cancelled.deposit_id == created.deposit_id
    assert cancelled.deposit_outcome_state is DepositOutcomeState.NON_REFUNDABLE_DISPOSITION


def test_customer_cancellation_is_atomic_idempotent_and_preserves_deposit(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _, reservation_id = active_reservation(setup)
        deposit_before = setup.execute(
            "SELECT id, required_usd_cents, version FROM app.deposits WHERE reservation_id = %s",
            (reservation_id,),
        ).fetchone()
        receipt_before = setup.execute(
            """
            SELECT receipt.id, receipt.payment_id, receipt.amount_usd_cents
            FROM app.deposit_receipts AS receipt
            JOIN app.deposits AS deposit ON deposit.id = receipt.deposit_id
            WHERE deposit.reservation_id = %s
            """,
            (reservation_id,),
        ).fetchone()
        setup.commit()

    key = uuid4()
    event_id = uuid4()
    with psycopg.connect(financial_database_url()) as runtime:
        first = cancel(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=key,
            event_id=event_id,
        )
        runtime.commit()
    with psycopg.connect(financial_database_url()) as runtime:
        replay = cancel(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=key,
            event_id=event_id,
        )
        runtime.commit()

    assert first == replay
    assert first[2:5] == ("CANCELLED", "CUSTOMER_WITHDREW", "CUSTOMER")
    assert first[7] == "VACANT"
    assert first[11] == "NON_REFUNDABLE_DISPOSITION"
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit_id,)
        ).fetchone() == ("VACANT",)
        assert verify.execute(
            """
            SELECT event_kind, cancellation_responsibility, deposit_outcome_state
            FROM app.reservation_lifecycle_events WHERE id = %s
            """,
            (event_id,),
        ).fetchone() == ("CANCELLATION", "CUSTOMER", "PENDING_V1_031")
        assert (
            verify.execute(
                """
                SELECT id, required_usd_cents, version
                FROM app.deposits WHERE reservation_id = %s
                """,
                (reservation_id,),
            ).fetchone()
            == deposit_before
        )
        assert (
            verify.execute(
                """
            SELECT receipt.id, receipt.payment_id, receipt.amount_usd_cents
            FROM app.deposit_receipts AS receipt
            JOIN app.deposits AS deposit ON deposit.id = receipt.deposit_id
            WHERE deposit.reservation_id = %s
            """,
                (reservation_id,),
            ).fetchone()
            == receipt_before
        )


def test_property_cancellation_requires_coordination_and_creates_refund(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        setup.commit()
    with psycopg.connect(financial_database_url()) as runtime:
        with pytest.raises(Error) as missing_coordination:
            cancel(
                runtime,
                actor_id=actor_id,
                property_id=property_id,
                reservation_id=reservation_id,
                idempotency_key=uuid4(),
                event_id=uuid4(),
                responsibility="PROPERTY",
                property_could_provide_unit=False,
            )
        assert missing_coordination.value.sqlstate == "23514"
        runtime.rollback()
        row = cancel(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            reservation_id=reservation_id,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="CASE-2026-001",
        )
        runtime.commit()
    assert row[4] == "PROPERTY"
    assert row[11] == "REFUND"
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT usd_accounting_value_cents, refund_currency FROM app.refunds WHERE id = %s",
            (row[12],),
        ).fetchone() == (10_000, "USD")


def test_expiration_uses_end_of_date_is_bounded_and_preserves_classification(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _, reservation_id, deposit_id = expired_reservation(setup)
        _, _, _, _, current_id = active_reservation(setup, expiration_days=0)
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        due = runtime.execute(
            "SELECT * FROM app.list_due_reservations(%s, 1)", (property_id,)
        ).fetchall()
        assert due == [(reservation_id, due[0][1], 1)]
        assert all(row[0] != current_id for row in due)
    with psycopg.connect(financial_database_url()) as runtime:
        with pytest.raises(Error) as misclassified:
            runtime.execute(
                "SELECT * FROM app.expire_reservation_v2(%s,%s,%s,%s,%s,%s,1,false,%s,%s,%s)",
                (
                    property_id,
                    uuid4(),
                    "e" * 64,
                    uuid4(),
                    uuid4(),
                    reservation_id,
                    "reservations.cancel",
                    "reservation_deposits.dispose",
                    actor_id,
                ),
            ).fetchone()
        assert misclassified.value.sqlstate == "23514"
        runtime.rollback()
        key = uuid4()
        event_id = uuid4()
        row = runtime.execute(
            "SELECT * FROM app.expire_reservation_v2(%s,%s,%s,%s,%s,%s,1,true,%s,%s,%s)",
            (
                property_id,
                key,
                "f" * 64,
                event_id,
                uuid4(),
                reservation_id,
                "reservations.cancel",
                "reservation_deposits.dispose",
                actor_id,
            ),
        ).fetchone()
        runtime.commit()
    assert row is not None
    assert row[2:5] == ("CANCELLED", "RESERVATION_EXPIRED", "CUSTOMER")
    assert row[7] == "VACANT"
    assert row[9] == deposit_id
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit_id,)
        ).fetchone() == ("VACANT",)
        assert verify.execute(
            "SELECT source, action FROM app.audit_events WHERE id = %s", (event_id,)
        ).fetchone() == ("SCHEDULED", "reservation.expired")


def test_version_checked_extension_replays_then_rejects_stale_new_command(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, _, _, reservation_id = active_reservation(setup)
        old_date_row = setup.execute(
            "SELECT effective_expiration_date FROM app.reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()
        assert old_date_row is not None
        old_date = old_date_row[0]
        setup.commit()
    key = uuid4()
    notice_id = uuid4()
    parameters = (
        property_id,
        key,
        "1" * 64,
        notice_id,
        reservation_id,
        1,
        old_date + timedelta(days=3),
        datetime.now(UTC),
        "Authorized extension",
        "reservations.extend",
        actor_id,
    )
    with psycopg.connect(runtime_database_url()) as runtime:
        first = runtime.execute(
            "SELECT * FROM app.extend_reservation_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            parameters,
        ).fetchone()
        runtime.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        replay = runtime.execute(
            "SELECT * FROM app.extend_reservation_v2(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            parameters,
        ).fetchone()
        runtime.commit()
    assert first == replay
    with psycopg.connect(runtime_database_url()) as runtime:
        with pytest.raises(Error) as stale:
            runtime.execute(
                "SELECT * FROM app.extend_reservation_v2(%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    uuid4(),
                    "2" * 64,
                    uuid4(),
                    reservation_id,
                    old_date + timedelta(days=4),
                    datetime.now(UTC),
                    "Stale extension",
                    "reservations.extend",
                    actor_id,
                ),
            ).fetchone()
        assert stale.value.sqlstate == "40001"


def test_concurrent_extension_and_cancellation_have_one_version_winner(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, _, reservation_id = active_reservation(setup)
        old_date_row = setup.execute(
            "SELECT effective_expiration_date FROM app.reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()
        assert old_date_row is not None
        old_date = old_date_row[0]
        setup.commit()
    barrier = Barrier(2)

    def attempt(action: str) -> str:
        database_url = financial_database_url() if action == "cancel" else runtime_database_url()
        with psycopg.connect(database_url) as runtime:
            barrier.wait()
            try:
                if action == "cancel":
                    cancel(
                        runtime,
                        actor_id=actor_id,
                        property_id=property_id,
                        reservation_id=reservation_id,
                        idempotency_key=uuid4(),
                        event_id=uuid4(),
                    )
                else:
                    runtime.execute(
                        "SELECT * FROM app.extend_reservation_v2(%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s)",
                        (
                            property_id,
                            uuid4(),
                            "9" * 64,
                            uuid4(),
                            reservation_id,
                            old_date + timedelta(days=2),
                            datetime.now(UTC),
                            "Concurrent extension",
                            "reservations.extend",
                            actor_id,
                        ),
                    ).fetchone()
                runtime.commit()
                return "success"
            except Error as error:
                runtime.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(attempt, ("cancel", "extend")))
    assert outcomes == ["40001", "success"]
    with psycopg.connect(migrated_database_url) as verify:
        reservation = verify.execute(
            "SELECT status, version FROM app.reservations WHERE id = %s", (reservation_id,)
        ).fetchone()
        unit_status_row = verify.execute(
            "SELECT status FROM app.units WHERE id = %s", (unit_id,)
        ).fetchone()
        assert unit_status_row is not None
        unit_status = unit_status_row[0]
    assert reservation in {("ACTIVE", 2), ("CANCELLED", 2)}
    assert unit_status == ("RESERVED" if reservation[0] == "ACTIVE" else "VACANT")


def test_database_prevents_summary_drift_illegal_transition_and_history_loss(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, _, unit_id, _, reservation_id = active_reservation(setup)
        setup.commit()
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as summary_drift:
            owner.execute(
                """
                UPDATE app.units SET status = 'VACANT', version = version + 1,
                    updated_at = statement_timestamp(), updated_by = %s WHERE id = %s
                """,
                (actor_id, unit_id),
            )
        assert summary_drift.value.sqlstate == "23514"
        owner.rollback()
        occurred_at = datetime.now(UTC)
        with pytest.raises(Error) as omitted_release:
            owner.execute(
                """
                INSERT INTO app.reservation_lifecycle_events (
                    id, reservation_id, event_kind, cancellation_reason_code,
                    cancellation_responsibility, property_could_provide_unit,
                    authorization_reference, occurred_at, business_date, actor_id,
                    expected_version, resulting_version
                ) VALUES (%s,%s,'CANCELLATION','CUSTOMER_REQUESTED','CUSTOMER',true,
                    'reservations.cancel',%s,%s,%s,1,2)
                """,
                (uuid4(), reservation_id, occurred_at, occurred_at.date(), actor_id),
            )
            owner.execute(
                """
                UPDATE app.reservations
                SET status = 'CANCELLED', cancellation_reason_code = 'CUSTOMER_REQUESTED',
                    cancellation_responsibility = 'CUSTOMER', cancelled_at = %s,
                    version = version + 1, updated_at = %s, updated_by = %s
                WHERE id = %s
                """,
                (occurred_at, occurred_at, actor_id, reservation_id),
            )
            owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert omitted_release.value.sqlstate == "23514"
        owner.rollback()
        with pytest.raises(Error) as move_in_bypass:
            owner.execute(
                """
                UPDATE app.reservations SET status = 'COMPLETED', resulting_lease_id = %s,
                    completed_at = statement_timestamp(), version = version + 1,
                    updated_at = statement_timestamp(), updated_by = %s WHERE id = %s
                """,
                (uuid4(), actor_id, reservation_id),
            )
        assert move_in_bypass.value.sqlstate == "55000"
        owner.rollback()
        with pytest.raises(Error) as history_loss:
            owner.execute("DELETE FROM app.reservations WHERE id = %s", (reservation_id,))
        assert history_loss.value.sqlstate == "55000"
        owner.rollback()
        with pytest.raises(Error) as unsupported_reserved_insert:
            _, new_property_id, _, _ = setup_reservation_sources(owner)
            owner.execute(
                """
                INSERT INTO app.units (
                    id, property_id, unit_number, floor, unit_type, status,
                    created_by, updated_by
                ) VALUES (%s,%s,%s,'1','STUDIO','RESERVED',%s,%s)
                """,
                (uuid4(), new_property_id, f"INVALID-{uuid4()}", actor_id, actor_id),
            )
        assert unsupported_reserved_insert.value.sqlstate == "23514"


def test_runtime_role_has_only_bounded_lifecycle_authority(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(runtime_database_url()) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.reservation_lifecycle_events', 'SELECT'),
                has_table_privilege(current_user, 'app.reservation_lifecycle_events', 'INSERT'),
                has_function_privilege(
                    current_user,
                    'app.extend_reservation(uuid,uuid,text,uuid,uuid,date,timestamptz,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.extend_reservation_v2(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.cancel_reservation_v2(uuid,uuid,text,uuid,uuid,text,uuid,integer,text,text,boolean,text,text,text,text,uuid)',
                    'EXECUTE'
                ),
                has_function_privilege(
                    current_user,
                    'app.expire_reservation_v2(uuid,uuid,text,uuid,uuid,uuid,integer,boolean,text,text,uuid)',
                    'EXECUTE'
                )
            """
        ).fetchone()
        with pytest.raises(Error) as unbounded_due_query:
            runtime.execute(
                "SELECT * FROM app.list_due_reservations(%s, NULL)",
                (uuid4(),),
            ).fetchall()
        assert unbounded_due_query.value.sqlstate == "22023"
        runtime.rollback()
    assert privileges == (True, False, False, True, False, False, False, False)


def test_reservation_lifecycle_migration_is_forward_only() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations/versions/20260825_20_reservation_lifecycle.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "20260825_20"' in source
    assert 'down_revision = "20260825_19"' in source
    assert "Reservation lifecycle migration is forward-only" in source
