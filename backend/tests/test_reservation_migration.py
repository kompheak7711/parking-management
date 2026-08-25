"""Real PostgreSQL coverage for V1-029 Reservation persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import Connection, Error
from psycopg.types.json import Jsonb


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Apply all migrations to the disposable PostgreSQL database."""
    database_url = os.environ.get("MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("MIGRATION_DATABASE_URL is required for migration tests")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    """Provide an isolated migration-owner transaction."""
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def setup_reservation_sources(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID, UUID]:
    """Create one actor, Property, vacant Unit, and Customer."""
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s, %s, 'Reservation Tester', 'Reservation Tester',
                  'active', 'optional', 'test')
        """,
        (actor_id, f"reservation-{actor_id}"),
    )
    existing_property = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing_property is None:
        property_id = uuid4()
        connection.execute(
            """
            INSERT INTO app.properties (id, name, created_by, updated_by)
            VALUES (%s, 'Reservation Test Property', %s, %s)
            """,
            (property_id, actor_id, actor_id),
        )
    else:
        property_id = UUID(str(existing_property[0]))
    unit_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.units (
            id, property_id, unit_number, floor, unit_type, status,
            created_by, updated_by
        ) VALUES (%s, %s, %s, '1', 'ONE_BEDROOM', 'VACANT', %s, %s)
        """,
        (unit_id, property_id, f"RES-{unit_id.hex[:12]}", actor_id, actor_id),
    )
    customer_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.customers (
            id, legal_name, created_by, updated_by
        ) VALUES (%s, 'Reservation Customer', %s, %s)
        """,
        (customer_id, actor_id, actor_id),
    )
    return actor_id, property_id, unit_id, customer_id


def reservation_business_date(
    connection: Connection[tuple[object, ...]], property_id: UUID
) -> date:
    """Use the canonical Property timezone for date-sensitive cases."""
    timezone_row = connection.execute(
        "SELECT timezone_name FROM app.properties WHERE id = %s", (property_id,)
    ).fetchone()
    assert timezone_row is not None
    return datetime.now(ZoneInfo(str(timezone_row[0]))).date()


def create_reservation(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    unit_id: UUID,
    customer_id: UUID,
    idempotency_key: UUID | None = None,
    request_digest: str = "a" * 64,
    reservation_id: UUID | None = None,
    accepted_usd_cents: int = 10_000,
    acceptance_kind: str = "NORMAL_SUGGESTION",
    expiration_days: int = 10,
    business_date: date | None = None,
    accepted_at: datetime | None = None,
    received_at: datetime | None = None,
) -> tuple[tuple[object, ...], dict[str, UUID]]:
    """Execute the protected Reservation activation bundle."""
    effective_business_date = business_date or reservation_business_date(connection, property_id)
    database_now_row = connection.execute("SELECT clock_timestamp()").fetchone()
    assert database_now_row is not None
    database_now = database_now_row[0]
    assert isinstance(database_now, datetime)
    effective_accepted_at = accepted_at or database_now
    effective_received_at = received_at or database_now
    identities = {
        "idempotency_key": idempotency_key or uuid4(),
        "reservation_id": reservation_id or uuid4(),
        "acceptance_id": uuid4(),
        "deposit_id": uuid4(),
        "receipt_id": uuid4(),
        "payment_id": uuid4(),
    }
    trace = Jsonb(
        {
            "agreed_monthly_rent_usd_cents": 50_000,
            "suggested_rate_basis_points": 2000,
            "suggested_amount_usd_cents": 10_000,
            "rounding": "HALF_UP_USD_CENTS",
        }
    )
    row = connection.execute(
        """
        SELECT * FROM app.create_reservation(
            %s, %s, %s, %s, %s, %s, %s, 50000, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, 50000, %s, %s, %s, %s
        )
        """,
        (
            property_id,
            identities["idempotency_key"],
            request_digest,
            identities["reservation_id"],
            unit_id,
            customer_id,
            effective_business_date,
            effective_business_date + timedelta(days=expiration_days),
            identities["acceptance_id"],
            accepted_usd_cents,
            acceptance_kind,
            effective_accepted_at,
            "Explicitly accepted Reservation Security Deposit amount",
            "reservations.manage",
            trace,
            identities["deposit_id"],
            identities["receipt_id"],
            identities["payment_id"],
            effective_received_at,
            actor_id,
        ),
    ).fetchone()
    assert row is not None
    return row, identities


def test_activation_persists_one_reservation_and_continuing_security_deposit(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    row, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )

    assert row == (
        identities["reservation_id"],
        unit_id,
        customer_id,
        "ACTIVE",
        reservation_business_date(connection, property_id) + timedelta(days=10),
        identities["deposit_id"],
        10_000,
        1,
    )
    assert connection.execute(
        "SELECT status, version FROM app.units WHERE id = %s", (unit_id,)
    ).fetchone() == ("RESERVED", 2)
    assert connection.execute(
        """
        SELECT acceptance.suggested_amount_usd_cents,
               acceptance.accepted_required_amount_usd_cents,
               deposit.required_usd_cents,
               receipt.payment_id,
               receipt.amount_usd_cents
        FROM app.reservation_deposit_acceptances AS acceptance
        JOIN app.deposits AS deposit
          ON deposit.reservation_id = acceptance.reservation_id
        JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
        WHERE acceptance.reservation_id = %s
        """,
        (identities["reservation_id"],),
    ).fetchone() == (10_000, 10_000, 50_000, identities["payment_id"], 10_000)
    assert connection.execute(
        """
        SELECT count(*) FROM app.audit_events
        WHERE correlation_id = %s
          AND action IN (
              'reservation.activated',
              'reservation.deposit_acceptance.recorded',
              'reservation.security_deposit.created',
              'reservation.security_deposit.received'
          )
        """,
        (identities["idempotency_key"],),
    ).fetchone() == (4,)
    assert connection.execute(
        """
        SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'app' AND table_name = 'reservation_deposits'
        """
    ).fetchone() == (0,)


def test_authorized_variance_is_preserved_and_replay_is_idempotent(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    row, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
        accepted_usd_cents=7_500,
        acceptance_kind="AUTHORIZED_VARIANCE",
    )
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s, %s, %s, 1000, clock_timestamp(), %s)
        """,
        (uuid4(), identities["deposit_id"], uuid4(), actor_id),
    )
    replay = connection.execute(
        """
        SELECT * FROM app.create_reservation(
            %s, %s, %s, %s, %s, %s, %s, 50000, %s,
            %s, 7500, 'AUTHORIZED_VARIANCE', %s, %s, %s, %s,
            %s, 50000, %s, %s, %s, %s
        )
        """,
        (
            property_id,
            identities["idempotency_key"],
            "a" * 64,
            identities["reservation_id"],
            unit_id,
            customer_id,
            reservation_business_date(connection, property_id),
            reservation_business_date(connection, property_id) + timedelta(days=10),
            identities["acceptance_id"],
            datetime.now(UTC),
            "Explicitly accepted Reservation Security Deposit amount",
            "reservations.manage",
            Jsonb(
                {
                    "agreed_monthly_rent_usd_cents": 50_000,
                    "suggested_rate_basis_points": 2000,
                    "suggested_amount_usd_cents": 10_000,
                }
            ),
            identities["deposit_id"],
            identities["receipt_id"],
            identities["payment_id"],
            datetime.now(UTC),
            actor_id,
        ),
    ).fetchone()
    assert replay == row
    assert connection.execute(
        "SELECT count(*) FROM app.reservations WHERE id = %s",
        (identities["reservation_id"],),
    ).fetchone() == (1,)

    with pytest.raises(Error) as reused:
        connection.execute(
            """
            SELECT * FROM app.create_reservation(
                %s, %s, %s, %s, %s, %s, %s, 50000, %s,
                %s, 7500, 'AUTHORIZED_VARIANCE', %s, %s, %s, %s,
                %s, 50000, %s, %s, %s, %s
            )
            """,
            (
                property_id,
                identities["idempotency_key"],
                "b" * 64,
                identities["reservation_id"],
                unit_id,
                customer_id,
                reservation_business_date(connection, property_id),
                reservation_business_date(connection, property_id) + timedelta(days=10),
                identities["acceptance_id"],
                datetime.now(UTC),
                "Accepted amount",
                "reservations.manage",
                Jsonb({"replay": False}),
                identities["deposit_id"],
                identities["receipt_id"],
                identities["payment_id"],
                datetime.now(UTC) - timedelta(seconds=1),
                actor_id,
            ),
        )
    assert reused.value.sqlstate == "P0001"


def test_extension_is_single_bounded_and_preserves_original_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    connection.commit()
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s, %s, %s, 1000, clock_timestamp(), %s)
        """,
        (uuid4(), identities["deposit_id"], uuid4(), actor_id),
    )
    connection.commit()
    notice_id = uuid4()
    idempotency_key = uuid4()
    previous = reservation_business_date(connection, property_id) + timedelta(days=10)
    new_expiration = previous + timedelta(days=14)
    row = connection.execute(
        """
        SELECT * FROM app.extend_reservation(
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            property_id,
            idempotency_key,
            "c" * 64,
            notice_id,
            identities["reservation_id"],
            new_expiration,
            datetime.now(UTC),
            "Move-in coordination needs one extension",
            "reservations.extend",
            actor_id,
        ),
    ).fetchone()
    assert row == (
        identities["reservation_id"],
        previous,
        previous,
        new_expiration,
        "ACTIVE",
        2,
    )
    connection.commit()
    replay = connection.execute(
        "SELECT * FROM app.extend_reservation(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            property_id,
            idempotency_key,
            "c" * 64,
            notice_id,
            identities["reservation_id"],
            new_expiration,
            datetime.now(UTC),
            "ignored on replay",
            "reservations.extend",
            actor_id,
        ),
    ).fetchone()
    assert replay == row

    with pytest.raises(Error) as second_extension:
        connection.execute(
            "SELECT * FROM app.extend_reservation(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                uuid4(),
                "d" * 64,
                uuid4(),
                identities["reservation_id"],
                new_expiration + timedelta(days=1),
                datetime.now(UTC),
                "Second extension is prohibited",
                "reservations.extend",
                actor_id,
            ),
        )
    assert second_extension.value.sqlstate in {"23505", "23514"}


def test_expired_reservation_cannot_be_retroactively_extended(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    business_date = reservation_business_date(connection, property_id)
    created_at = datetime.now(UTC) - timedelta(days=3)
    reservation_id = uuid4()
    acceptance_id = uuid4()
    deposit_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.reservations (
            id, unit_id, customer_id, reservation_date,
            agreed_monthly_rent_usd_cents, original_expiration_date,
            effective_expiration_date, status, created_at, created_by,
            updated_at, updated_by
        ) VALUES (%s, %s, %s, %s, 50000, %s, %s, 'ACTIVE', %s, %s, %s, %s)
        """,
        (
            reservation_id,
            unit_id,
            customer_id,
            business_date - timedelta(days=3),
            business_date - timedelta(days=1),
            business_date - timedelta(days=1),
            created_at,
            actor_id,
            created_at,
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
        ) VALUES (%s, %s, 2000, 10000, 10000, 'NORMAL_SUGGESTION',
                  %s, %s, 'Accepted before expiration', 'reservations.manage', %s)
        """,
        (
            acceptance_id,
            reservation_id,
            created_at,
            actor_id,
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
        ) VALUES (%s, 'SECURITY', %s, %s, 50000, %s, %s, %s)
        """,
        (
            deposit_id,
            customer_id,
            reservation_id,
            business_date - timedelta(days=3),
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s, %s, %s, 10000, %s, %s)
        """,
        (uuid4(), deposit_id, uuid4(), created_at, actor_id),
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

    with pytest.raises(Error) as retroactive_extension:
        connection.execute(
            "SELECT * FROM app.extend_reservation(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                uuid4(),
                "e" * 64,
                uuid4(),
                reservation_id,
                business_date + timedelta(days=1),
                created_at + timedelta(days=1),
                "Retroactive extension is prohibited",
                "reservations.extend",
                actor_id,
            ),
        )
    assert retroactive_extension.value.sqlstate == "23514"


def test_extension_notice_requires_atomic_reservation_update(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    previous = reservation_business_date(connection, property_id) + timedelta(days=10)
    connection.execute(
        """
        INSERT INTO app.reservation_extension_notices (
            id, reservation_id, original_expiration_date,
            previous_expiration_date, new_expiration_date,
            approved_at, approved_by, reason_memo, authorization_reference
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            identities["reservation_id"],
            previous,
            previous,
            previous + timedelta(days=1),
            datetime.now(UTC),
            actor_id,
            "Direct notice must not consume the extension slot",
            "reservations.extend",
        ),
    )
    with pytest.raises(Error) as unapplied_notice:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert unapplied_notice.value.sqlstate == "23514"


def test_database_rejects_invalid_dates_statuses_and_history_rewrite(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    with pytest.raises(Error) as rewritten_expiration:
        connection.execute(
            """
            UPDATE app.reservations
            SET effective_expiration_date = effective_expiration_date + 1,
                version = version + 1,
                updated_at = statement_timestamp(), updated_by = %s
            WHERE id = %s
            """,
            (actor_id, identities["reservation_id"]),
        )
    assert rewritten_expiration.value.sqlstate == "55000"
    connection.rollback()

    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    connection.execute(
        """
        UPDATE app.reservations
        SET status = 'CANCELLED', cancellation_reason_code = 'CUSTOMER_CANCELLED',
            cancellation_responsibility = 'CUSTOMER',
            cancelled_at = statement_timestamp(), version = version + 1,
            updated_at = statement_timestamp(), updated_by = %s
        WHERE id = %s
        """,
        (actor_id, identities["reservation_id"]),
    )
    with pytest.raises(Error) as uncoordinated_cancellation:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert uncoordinated_cancellation.value.sqlstate == "23514"
    connection.rollback()

    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    with pytest.raises(Error) as invented_status:
        connection.execute(
            "UPDATE app.reservations SET status = 'EXPIRED' WHERE id = %s",
            (identities["reservation_id"],),
        )
    assert invented_status.value.sqlstate == "55000"
    connection.rollback()

    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    with pytest.raises(Error) as deleted:
        connection.execute(
            "DELETE FROM app.deposit_receipts WHERE deposit_id = %s",
            (identities["deposit_id"],),
        )
    assert deleted.value.sqlstate == "55000"

    connection.rollback()
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    with pytest.raises(Error) as future_business_date:
        create_reservation(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
            business_date=reservation_business_date(connection, property_id) + timedelta(days=1),
        )
    assert future_business_date.value.sqlstate == "23514"

    connection.rollback()
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    future_accepted_at = datetime.now(UTC) + timedelta(minutes=1)
    with pytest.raises(Error) as future_acceptance:
        create_reservation(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
            accepted_at=future_accepted_at,
            received_at=future_accepted_at + timedelta(seconds=1),
        )
    assert future_acceptance.value.sqlstate == "23514"

    connection.rollback()
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    accepted_at = datetime.now(UTC)
    with pytest.raises(Error) as receipt_before_acceptance:
        create_reservation(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
            accepted_at=accepted_at,
            received_at=accepted_at - timedelta(seconds=1),
        )
    assert receipt_before_acceptance.value.sqlstate == "23514"


def test_activation_bundle_requires_exact_accepted_receipt(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s, %s, %s, 1, clock_timestamp(), %s)
        """,
        (uuid4(), identities["deposit_id"], uuid4(), actor_id),
    )
    with pytest.raises(Error) as overpaid_activation:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert overpaid_activation.value.sqlstate == "23514"


def test_received_deposit_cannot_exceed_required_liability(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id, customer_id = setup_reservation_sources(connection)
    _, identities = create_reservation(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        customer_id=customer_id,
    )
    connection.execute(
        """
        INSERT INTO app.deposit_receipts (
            id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
        ) VALUES (%s, %s, %s, 40000, clock_timestamp(), %s)
        """,
        (uuid4(), identities["deposit_id"], uuid4(), actor_id),
    )
    with pytest.raises(Error) as excess:
        connection.execute(
            """
            INSERT INTO app.deposit_receipts (
                id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
            ) VALUES (%s, %s, %s, 1, clock_timestamp(), %s)
            """,
            (uuid4(), identities["deposit_id"], uuid4(), actor_id),
        )
    assert excess.value.sqlstate == "23514"


def test_concurrent_attempts_hold_one_unit_exactly_once(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(setup)
        setup.commit()
    barrier = Barrier(2)

    def attempt(digest_character: str) -> str:
        with psycopg.connect(migrated_database_url) as competing:
            barrier.wait(timeout=5)
            try:
                create_reservation(
                    competing,
                    actor_id=actor_id,
                    property_id=property_id,
                    unit_id=unit_id,
                    customer_id=customer_id,
                    request_digest=digest_character * 64,
                )
                competing.commit()
                return "success"
            except Error as error:
                competing.rollback()
                return str(error.sqlstate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(attempt, ("e", "f")))
    assert outcomes == ["P0001", "success"]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.reservations WHERE unit_id = %s AND status = 'ACTIVE'",
            (unit_id,),
        ).fetchone() == (1,)


def test_runtime_is_read_only_except_for_bounded_commands(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id, customer_id = setup_reservation_sources(setup)
        setup.commit()
    runtime_url = os.environ.get("APP_DATABASE_URL")
    assert runtime_url is not None
    runtime_url = runtime_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(runtime_url) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.reservations', 'SELECT'),
                has_table_privilege(current_user, 'app.reservations', 'INSERT'),
                has_table_privilege(current_user, 'app.deposit_receipts', 'UPDATE'),
                has_table_privilege(current_user, 'app.reservation_commands', 'SELECT'),
                has_function_privilege(
                    current_user,
                    'app.create_reservation(uuid,uuid,text,uuid,uuid,uuid,date,bigint,date,uuid,bigint,text,timestamptz,text,text,jsonb,uuid,bigint,uuid,uuid,timestamptz,uuid)',
                    'EXECUTE'
                )
            """
        ).fetchone()
        assert privileges == (True, False, False, False, True)
        row, _ = create_reservation(
            runtime,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            customer_id=customer_id,
        )
        assert row[3] == "ACTIVE"
        runtime.commit()


def test_reservation_migration_is_forward_only() -> None:
    """Keep durable Reservation and Deposit history across later corrections."""
    migration = (
        Path(__file__).parents[1] / "migrations/versions/20260825_19_reservation_persistence.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "20260825_19"' in source
    assert 'down_revision = "20260825_18"' in source
    assert "Reservation and reservation-deposit migration is forward-only" in source
