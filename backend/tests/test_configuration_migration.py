"""Real PostgreSQL coverage for V1-027 configuration persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
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

from property_rental.configuration_api import (
    ConfigurationNotFound,
    ExchangeRateRecord,
    PostgresConfigurationFlow,
)


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


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    assert value is not None
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def test_runtime_configuration_commands_are_idempotent_and_audited(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        service_id = insert_service(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            code=f"API_TRASH_{uuid4().hex}",
        )
        setup.commit()
    key = uuid4()
    parameters = (
        property_id,
        key,
        "a" * 64,
        uuid4(),
        service_id,
        1_250,
        "2026-10-01",
        "Approved through administration API",
        actor_id,
    )
    statement = "SELECT * FROM app.execute_service_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    with psycopg.connect(runtime_database_url()) as runtime:
        first = runtime.execute(statement, parameters).fetchone()
        assert first is not None
        replay = runtime.execute(statement, (*parameters[:3], uuid4(), *parameters[4:])).fetchone()
        assert replay == first
        assert runtime.execute(
            "SELECT count(*) FROM app.service_rates WHERE property_service_id = %s",
            (service_id,),
        ).fetchone() == (1,)
        assert runtime.execute(
            "SELECT action, authorization_reference FROM app.audit_events WHERE id = %s",
            (first[0],),
        ).fetchone() == ("service_rate.created", "service_rates.manage")
        with pytest.raises(Error) as changed:
            runtime.execute(
                statement,
                (
                    property_id,
                    key,
                    "b" * 64,
                    uuid4(),
                    service_id,
                    1_300,
                    "2026-11-01",
                    "Changed",
                    actor_id,
                ),
            )
        assert changed.value.sqlstate == "P0001"


def test_runtime_utility_and_exchange_commands_preserve_effective_evidence(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        utility = runtime.execute(
            "SELECT * FROM app.execute_utility_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                uuid4(),
                "c" * 64,
                uuid4(),
                "ELECTRICITY",
                "KWH",
                Decimal("0.25000000"),
                # This rate is committed to the shared test database; a far-future date keeps
                # it from becoming the current ELECTRICITY rate for later tests.
                "2099-10-01",
                "2099-09-01T09:00:00+07:00",
                "Notice ELEC-2026-09",
                "Approved rate",
                actor_id,
            ),
        ).fetchone()
        assert utility is not None
        assert utility[2:6] == (
            "ELECTRICITY",
            "KWH",
            Decimal("0.25000000"),
            datetime(2099, 10, 1).date(),
        )
        trace = {
            "usd_amount_cents": 10001,
            "unrounded_payable_khr": "408340.83",
            "payable_khr": 408341,
            "markup_basis_points": 50,
            "rounding": "CEILING_WHOLE_KHR",
        }
        exchange = runtime.execute(
            "SELECT * FROM app.execute_exchange_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                uuid4(),
                "d" * 64,
                uuid4(),
                Decimal("4062.500000"),
                4083,
                "ABA_EQUIVALENT_MANUAL",
                "ABA fallback evidence",
                "2026-08-25T10:00:00+07:00",
                actor_id,
                Jsonb(trace),
            ),
        ).fetchone()
        assert exchange is not None
        assert exchange[1:5] == (
            Decimal("4062.500000"),
            4083,
            "ABA_EQUIVALENT_MANUAL",
            "ABA fallback evidence",
        )


def test_concurrent_configuration_replay_creates_one_rate(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        service_id = insert_service(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            code=f"API_CONCURRENT_{uuid4().hex}",
        )
        setup.commit()
    key = uuid4()

    def execute(_: int) -> UUID:
        with psycopg.connect(runtime_database_url()) as runtime:
            row = runtime.execute(
                "SELECT * FROM app.execute_service_rate(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    property_id,
                    key,
                    "e" * 64,
                    uuid4(),
                    service_id,
                    1_500,
                    "2026-12-01",
                    "Concurrent replay",
                    actor_id,
                ),
            ).fetchone()
            assert row is not None
            return UUID(str(row[0]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_ids = list(executor.map(execute, range(2)))
    assert result_ids[0] == result_ids[1]
    with psycopg.connect(migrated_database_url) as verify:
        assert verify.execute(
            "SELECT count(*) FROM app.service_rates WHERE property_service_id = %s",
            (service_id,),
        ).fetchone() == (1,)


def test_runtime_flow_maps_missing_configuration_to_not_found(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        setup.commit()
    flow = PostgresConfigurationFlow(runtime_database_url())
    with pytest.raises(ConfigurationNotFound):
        flow.create_service_rate(
            property_id,
            rate_id=uuid4(),
            property_service_id=uuid4(),
            monthly_rate_usd_cents=1_250,
            effective_date=datetime(2026, 10, 1).date(),
            source_memo=None,
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="f" * 64,
        )
    with pytest.raises(ConfigurationNotFound):
        flow.create_utility_rate(
            uuid4(),
            rate_id=uuid4(),
            utility_type="WATER",
            measurement_unit_code="M3",
            rate_usd_per_unit=Decimal("0.5"),
            effective_date=datetime(2026, 10, 1).date(),
            notice_at=datetime.fromisoformat("2026-09-01T09:00:00+07:00"),
            notice_evidence="Notice",
            source_memo=None,
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="0" * 64,
        )


def test_runtime_flow_discovers_only_configured_services(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id = actor_and_property(setup)
        service_id = insert_service(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            code=f"DISCOVER_{uuid4().hex}",
        )
        second_service_id = insert_service(
            setup,
            actor_id=actor_id,
            property_id=property_id,
            code=f"DISCOVER_{uuid4().hex}",
        )
        setup.commit()
    flow = PostgresConfigurationFlow(runtime_database_url())
    first = flow.list_configured_services(property_id, limit=1, cursor=None)
    assert first.next_cursor is not None
    second = flow.list_configured_services(property_id, limit=100, cursor=first.next_cursor)
    discovered = {record.id for record in (*first.items, *second.items)}
    assert {service_id, second_service_id}.issubset(discovered)
    assert len(first.items) == 1
    assert len(second.items) <= 100


def test_runtime_exchange_history_is_scoped_to_the_exact_property(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, first_property_id = actor_and_property(setup)
        setup.commit()
    flow = PostgresConfigurationFlow(runtime_database_url())

    def persist(property_id: UUID, amount: int) -> ExchangeRateRecord:
        unrounded = Decimal(amount) * Decimal(4083) / Decimal(100)
        record = ExchangeRateRecord(
            id=uuid4(),
            reference_rate_khr_per_usd=Decimal("4062.500000"),
            system_rate_khr_per_usd=4083,
            rate_source="ABA_AUTOMATIC",
            source_reference=f"automatic-{property_id}",
            applicable_at=datetime.fromisoformat("2026-08-25T10:00:00+07:00"),
            usd_amount_cents=amount,
            unrounded_payable_khr=unrounded,
            payable_khr=int(unrounded.to_integral_value(rounding=ROUND_CEILING)),
        )
        idempotency_key = uuid4()
        request_digest = uuid4().hex * 2
        persisted = flow.confirm_exchange_rate(
            property_id,
            record=record,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        replay = flow.get_exchange_rate_replay(
            property_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        assert replay == persisted
        return persisted

    first = persist(first_property_id, 100)
    first_ids = {
        record.id
        for record in flow.list_exchange_rates(first_property_id, limit=100, cursor=None).items
    }
    assert first.id in first_ids
    with pytest.raises(ConfigurationNotFound):
        flow.list_exchange_rates(uuid4(), limit=100, cursor=None)
