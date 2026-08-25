"""Real PostgreSQL coverage for V1-027 configuration persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import UUID, uuid4

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


def actor_and_property(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID]:
    """Create an actor and reuse or create the single Property."""
    actor_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.user_accounts (
            actor_id, normalized_username, display_name, audit_name,
            lifecycle_state, mfa_policy_class, provenance
        ) VALUES (%s, %s, 'Configuration Tester', 'Configuration Tester',
                  'active', 'optional', 'test')
        """,
        (actor_id, f"configuration-{actor_id}"),
    )
    existing = connection.execute("SELECT id FROM app.properties").fetchone()
    if existing is not None:
        return actor_id, UUID(str(existing[0]))
    property_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.properties (id, name, created_by, updated_by)
        VALUES (%s, 'Configuration Test Property', %s, %s)
        """,
        (property_id, actor_id, actor_id),
    )
    return actor_id, property_id


def insert_service(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    code: str = "TRASH_COLLECTION",
) -> UUID:
    """Insert one configured Service identity."""
    service_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.property_services (
            id, property_id, service_code, display_name,
            configured_by, created_by, updated_by
        ) VALUES (%s, %s, %s, 'Trash Collection', %s, %s, %s)
        """,
        (service_id, property_id, code, actor_id, actor_id, actor_id),
    )
    return service_id


def test_configuration_tables_are_history_safe_and_runtime_read_only(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id = actor_and_property(connection)
    service_id = insert_service(connection, actor_id=actor_id, property_id=property_id)

    connection.execute(
        """
        INSERT INTO app.service_rates (
            id, property_service_id, monthly_rate_usd_cents,
            effective_date, source_memo, actor_id
        ) VALUES (%s, %s, 1250, DATE '2026-01-01', 'Owner-approved rate', %s)
        """,
        (uuid4(), service_id, actor_id),
    )
    connection.execute(
        """
        INSERT INTO app.property_service_approval_periods (
            id, property_service_id, effective_from, approval_reference,
            approved_at, approved_by, reason
        ) VALUES (%s, %s, DATE '2026-01-01', 'OWNER-TRASH-2026',
                  TIMESTAMPTZ '2025-12-01 00:00:00+07', %s,
                  'Approved recurring Trash Collection')
        """,
        (uuid4(), service_id, actor_id),
    )

    with pytest.raises(Error) as updated:
        connection.execute("UPDATE app.service_rates SET monthly_rate_usd_cents = 1300")
    assert updated.value.sqlstate == "55000"
    connection.rollback()

    actor_id, property_id = actor_and_property(connection)
    service_id = insert_service(
        connection, actor_id=actor_id, property_id=property_id, code="TRASH_RUNTIME"
    )
    runtime_url = os.environ.get("APP_DATABASE_URL")
    assert runtime_url is not None
    runtime_url = runtime_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(runtime_url) as runtime:
        privileges = runtime.execute(
            """
            SELECT
                has_table_privilege(current_user, 'app.property_services', 'SELECT'),
                has_table_privilege(current_user, 'app.property_services', 'INSERT'),
                has_table_privilege(current_user, 'app.service_rates', 'UPDATE'),
                has_table_privilege(current_user, 'app.utility_rates', 'DELETE'),
                has_table_privilege(current_user, 'app.exchange_rate_records', 'TRUNCATE')
            """
        ).fetchone()
        assert privileges == (True, False, False, False, False)
        assert (
            runtime.execute(
                "SELECT service_code FROM app.property_services WHERE id = %s",
                (service_id,),
            ).fetchone()
            is None
        )


def test_service_rates_and_approval_periods_preserve_effective_history(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id = actor_and_property(connection)
    service_id = insert_service(connection, actor_id=actor_id, property_id=property_id)
    first_rate_id = uuid4()
    second_rate_id = uuid4()
    statement = """
    INSERT INTO app.service_rates (
        id, property_service_id, monthly_rate_usd_cents,
        effective_date, source_memo, actor_id
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    for parameters in (
        (
            first_rate_id,
            service_id,
            1_000,
            "2026-01-01",
            "Initial approved rate",
            actor_id,
        ),
        (
            second_rate_id,
            service_id,
            1_250,
            "2026-04-01",
            "Future approved rate",
            actor_id,
        ),
    ):
        connection.execute(statement, parameters)
    selected = connection.execute(
        """
        SELECT id, monthly_rate_usd_cents
        FROM app.service_rates
        WHERE property_service_id = %s AND effective_date <= %s
        ORDER BY effective_date DESC
        LIMIT 1
        """,
        (service_id, "2026-03-01"),
    ).fetchone()
    assert selected == (first_rate_id, 1_000)

    period_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.property_service_approval_periods (
            id, property_service_id, effective_from, approval_reference,
            approved_at, approved_by, reason
        ) VALUES (%s, %s, DATE '2026-01-01', 'OWNER-TRASH-2026',
                  TIMESTAMPTZ '2025-12-01 00:00:00+07', %s,
                  'Approved recurring Trash Collection')
        """,
        (period_id, service_id, actor_id),
    )
    connection.execute(
        """
        UPDATE app.property_service_approval_periods
        SET effective_through = DATE '2026-06-30'
        WHERE id = %s
        """,
        (period_id,),
    )
    assert connection.execute(
        "SELECT effective_through FROM app.property_service_approval_periods WHERE id = %s",
        (period_id,),
    ).fetchone() == (datetime(2026, 6, 30).date(),)
    with pytest.raises(Error) as second_closure:
        connection.execute(
            """
            UPDATE app.property_service_approval_periods
            SET effective_through = DATE '2026-07-31'
            WHERE id = %s
            """,
            (period_id,),
        )
    assert second_closure.value.sqlstate == "55000"


def test_service_approval_periods_reject_overlap(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id = actor_and_property(connection)
    service_id = insert_service(connection, actor_id=actor_id, property_id=property_id)
    connection.execute(
        """
        INSERT INTO app.property_service_approval_periods (
            id, property_service_id, effective_from, effective_through,
            approval_reference, approved_at, approved_by, reason
        ) VALUES (%s, %s, DATE '2026-01-01', DATE '2026-06-30',
                  'OWNER-FIRST', statement_timestamp(), %s, 'First approval')
        """,
        (uuid4(), service_id, actor_id),
    )
    with pytest.raises(Error) as overlap:
        connection.execute(
            """
            INSERT INTO app.property_service_approval_periods (
                id, property_service_id, effective_from, effective_through,
                approval_reference, approved_at, approved_by, reason
            ) VALUES (%s, %s, DATE '2026-06-30', DATE '2026-12-31',
                      'OWNER-OVERLAP', statement_timestamp(), %s, 'Overlapping approval')
            """,
            (uuid4(), service_id, actor_id),
        )
    assert overlap.value.sqlstate == "23P01"


def test_utility_rates_are_independent_effective_and_append_only(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id = actor_and_property(connection)
    electricity_id = uuid4()
    water_id = uuid4()
    statement = """
    INSERT INTO app.utility_rates (
        id, property_id, utility_type, measurement_unit_code,
        rate_usd_per_unit, effective_date, notice_at,
        notice_evidence, source_memo, actor_id
    ) VALUES (%s, %s, %s, %s, %s, DATE '2026-02-01',
              TIMESTAMPTZ '2026-01-01 10:00:00+07', %s, %s, %s)
    """
    for parameters in (
        (
            electricity_id,
            property_id,
            "ELECTRICITY",
            "KWH",
            Decimal("0.25000000"),
            "Notice ELEC-2026-01",
            "Approved electricity rate",
            actor_id,
        ),
        (
            water_id,
            property_id,
            "WATER",
            "M3",
            Decimal("0.50000000"),
            "Notice WATER-2026-01",
            "Approved water rate",
            actor_id,
        ),
    ):
        connection.execute(statement, parameters)
    stored = connection.execute(
        """
        SELECT utility_type, measurement_unit_code, rate_usd_per_unit
        FROM app.utility_rates
        WHERE property_id = %s
        ORDER BY utility_type
        """,
        (property_id,),
    ).fetchall()
    assert stored == [
        ("ELECTRICITY", "KWH", Decimal("0.25000000")),
        ("WATER", "M3", Decimal("0.50000000")),
    ]
    with pytest.raises(Error) as late_notice:
        connection.execute(
            """
            INSERT INTO app.utility_rates (
                id, property_id, utility_type, measurement_unit_code,
                rate_usd_per_unit, effective_date, notice_at,
                notice_evidence, actor_id
            ) VALUES (%s, %s, 'WATER', 'M3', 0.75, DATE '2026-03-01',
                      TIMESTAMPTZ '2026-03-01 00:00:00+07', 'Late notice', %s)
            """,
            (uuid4(), property_id, actor_id),
        )
    assert late_notice.value.sqlstate == "23514"
    connection.rollback()

    actor_id, property_id = actor_and_property(connection)
    connection.execute(
        """
        INSERT INTO app.utility_rates (
            id, property_id, utility_type, measurement_unit_code,
            rate_usd_per_unit, effective_date, notice_at,
            notice_evidence, actor_id
        ) VALUES (%s, %s, 'ELECTRICITY', 'KWH', 0.25, DATE '2026-02-01',
                  TIMESTAMPTZ '2026-01-01 00:00:00+07', 'Approved notice', %s)
        """,
        (uuid4(), property_id, actor_id),
    )
    with pytest.raises(Error) as mutation:
        connection.execute("UPDATE app.utility_rates SET rate_usd_per_unit = 0.30")
    assert mutation.value.sqlstate == "55000"


def test_exchange_rate_formula_manual_source_and_channel_evidence(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    rate_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.exchange_rate_records (
            id, reference_rate_khr_per_usd, markup_basis_points,
            system_rate_khr_per_usd, rate_source, source_reference,
            applicable_at, entered_by, channel_actual_currency,
            channel_actual_amount_minor, channel_transaction_reference,
            channel_confirmed_at, calculation_trace
        ) VALUES (%s, 4062.500000, 50, 4083, 'ABA_EQUIVALENT_MANUAL',
                  'Owner-entered ABA sell reference', statement_timestamp(), %s,
                  'KHR', 408300, 'CHANNEL-TX-1', statement_timestamp(), %s)
        """,
        (
            rate_id,
            actor_id,
            Jsonb(
                {
                    "reference_rate_khr_per_usd": "4062.500000",
                    "markup_basis_points": 50,
                    "rounding": "CEILING_WHOLE_KHR",
                    "system_rate_khr_per_usd": 4083,
                }
            ),
        ),
    )
    assert connection.execute(
        """
        SELECT reference_rate_khr_per_usd, system_rate_khr_per_usd,
               rate_source, channel_actual_amount_minor
        FROM app.exchange_rate_records WHERE id = %s
        """,
        (rate_id,),
    ).fetchone() == (
        Decimal("4062.500000"),
        4083,
        "ABA_EQUIVALENT_MANUAL",
        408300,
    )
    with pytest.raises(Error) as wrong_formula:
        connection.execute(
            """
            INSERT INTO app.exchange_rate_records (
                id, reference_rate_khr_per_usd, markup_basis_points,
                system_rate_khr_per_usd, rate_source, applicable_at,
                calculation_trace
            ) VALUES (%s, 4062.5, 50, 4082, 'ABA_AUTOMATIC',
                      statement_timestamp(), '{"calculation":"wrong"}'::jsonb)
            """,
            (uuid4(),),
        )
    assert wrong_formula.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _ = actor_and_property(connection)
    with pytest.raises(Error) as missing_actor:
        connection.execute(
            """
            INSERT INTO app.exchange_rate_records (
                id, reference_rate_khr_per_usd, markup_basis_points,
                system_rate_khr_per_usd, rate_source, applicable_at,
                calculation_trace
            ) VALUES (%s, 4062.5, 50, 4083, 'ABA_EQUIVALENT_MANUAL',
                      statement_timestamp(), '{"calculation":"manual"}'::jsonb)
            """,
            (uuid4(),),
        )
    assert missing_actor.value.sqlstate == "23514"
    del actor_id


def test_payment_method_retirement_preserves_identity(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _ = actor_and_property(connection)
    method_id = uuid4()
    connection.execute(
        """
        INSERT INTO app.payment_methods (
            id, code, display_name, accepted, created_by, updated_by
        ) VALUES (%s, 'BANK_TRANSFER', 'Bank transfer', true, %s, %s)
        """,
        (method_id, actor_id, actor_id),
    )
    connection.execute(
        """
        UPDATE app.payment_methods
        SET accepted = false,
            display_name = 'Bank transfer (retired)',
            updated_at = statement_timestamp(),
            updated_by = %s
        WHERE id = %s
        """,
        (actor_id, method_id),
    )
    assert connection.execute(
        "SELECT id, code, display_name, accepted FROM app.payment_methods WHERE id = %s",
        (method_id,),
    ).fetchone() == (
        method_id,
        "BANK_TRANSFER",
        "Bank transfer (retired)",
        False,
    )
    with pytest.raises(Error) as deleted:
        connection.execute("DELETE FROM app.payment_methods WHERE id = %s", (method_id,))
    assert deleted.value.sqlstate == "55000"


def test_concurrent_overlapping_service_approvals_commit_only_one(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        service_id = insert_service(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            code=f"CONCURRENT_{uuid4().hex}",
        )
        setup.commit()

    first_inserted = Event()
    second_backend_pid: Queue[int] = Queue(maxsize=1)
    with psycopg.connect(migrated_database_url) as first:
        first.execute(
            """
            INSERT INTO app.property_service_approval_periods (
                id, property_service_id, effective_from, effective_through,
                approval_reference, approved_at, approved_by, reason
            ) VALUES (%s, %s, DATE '2026-01-01', DATE '2026-06-30',
                      'OWNER-CONCURRENT-FIRST', statement_timestamp(), %s,
                      'First concurrent approval')
            """,
            (uuid4(), service_id, actor_id),
        )
        first_inserted.set()

        def insert_overlap() -> str | None:
            first_inserted.wait(timeout=2)
            with psycopg.connect(migrated_database_url) as second:
                second.execute("SET LOCAL lock_timeout = '5s'")
                pid_row = second.execute("SELECT pg_backend_pid()").fetchone()
                assert pid_row is not None
                second_backend_pid.put(int(pid_row[0]))
                try:
                    second.execute(
                        """
                        INSERT INTO app.property_service_approval_periods (
                            id, property_service_id, effective_from, effective_through,
                            approval_reference, approved_at, approved_by, reason
                        ) VALUES (%s, %s, DATE '2026-04-01', DATE '2026-12-31',
                                  'OWNER-CONCURRENT-SECOND', statement_timestamp(), %s,
                                  'Second concurrent approval')
                        """,
                        (uuid4(), service_id, actor_id),
                    )
                    second.commit()
                    return None
                except Error as error:
                    second.rollback()
                    return error.sqlstate

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(insert_overlap)
            competing_pid = second_backend_pid.get(timeout=2)
            deadline = monotonic() + 3
            lock_wait_observed = False
            with psycopg.connect(migrated_database_url) as monitor:
                while monotonic() < deadline:
                    wait = monitor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                        (competing_pid,),
                    ).fetchone()
                    if wait == ("Lock",):
                        lock_wait_observed = True
                        break
                    sleep(0.01)
            assert lock_wait_observed is True
            first.commit()
            second_state = future.result(timeout=10)

    assert second_state == "23P01"
    with psycopg.connect(migrated_database_url) as verification:
        assert verification.execute(
            """
            SELECT count(*)
            FROM app.property_service_approval_periods
            WHERE property_service_id = %s
            """,
            (service_id,),
        ).fetchone() == (1,)


def test_configuration_tables_reject_destructive_truncation(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id = actor_and_property(connection)
    insert_service(connection, actor_id=actor_id, property_id=property_id)
    with pytest.raises(Error) as truncated:
        connection.execute("TRUNCATE app.property_services CASCADE")
    assert truncated.value.sqlstate == "55000"
