"""Real PostgreSQL coverage for V1-042 Utility calculation services."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection, Error
from psycopg.conninfo import make_conninfo

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.utility import (
    UTILITY_CALCULATE_CAPABILITY,
    UTILITY_ESTIMATE_CAPABILITY,
    FinalizeActualConsumptionCommand,
    FinalizeBrokenMeterEstimateCommand,
    OpenBrokenMeterCaseCommand,
    PostgresUtilityService,
    UtilityAuthorizationError,
    UtilityBasisKind,
    UtilityCalculationKind,
    UtilityCalculationStatus,
    UtilityConflictError,
    UtilityIdempotencyKeyReused,
    UtilityInvalidError,
    UtilityPreviewSourceKind,
)
from test_lease_migration import create_draft, sign_lease
from test_utility_meter_migration import (
    add_meter,
    add_rate,
    add_reading,
    assert_sessions_wait_for_lock,
    utility_source,
)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_database_url) as database_connection:
        yield database_connection
        database_connection.rollback()


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def authorized_actor(
    actor_id: UUID,
    property_id: UUID,
    *capabilities: str,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            CapabilityGrant(capability, frozenset({str(property_id)}))
            for capability in capabilities
        ),
    )


def committed_source(
    migrated_database_url: str,
    reading_points: tuple[tuple[date, str], ...],
) -> tuple[UUID, UUID, UUID, UUID, tuple[UUID, ...]]:
    with psycopg.connect(migrated_database_url) as owner:
        actor_id, property_id, unit_id = utility_source(owner)
        meter_id = add_meter(owner, actor_id=actor_id, unit_id=unit_id)
        reading_ids = tuple(
            add_reading(
                owner,
                actor_id=actor_id,
                meter_id=meter_id,
                reading_date=reading_date,
                reading_value=value,
            )
            for reading_date, value in reading_points
        )
        owner.commit()
    return actor_id, property_id, unit_id, meter_id, reading_ids


def committed_isolated_source(
    migrated_database_url: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    with psycopg.connect(migrated_database_url) as owner:
        actor_id = uuid4()
        unit_id = uuid4()
        owner.execute(
            "INSERT INTO app.user_accounts("
            "actor_id,normalized_username,display_name,audit_name,lifecycle_state,"
            "mfa_policy_class,provenance) "
            "VALUES (%s,%s,'Utility Isolation Tester','Utility Isolation Tester',"
            "'active','optional','test')",
            (actor_id, f"utility-isolation-{actor_id}"),
        )
        property_row = owner.execute("SELECT id FROM app.properties").fetchone()
        assert property_row is not None
        property_id = UUID(str(property_row[0]))
        owner.execute(
            "INSERT INTO app.units("
            "id,property_id,unit_number,floor,unit_type,status,created_by,updated_by) "
            "VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
            (unit_id, property_id, f"UTILITY-{unit_id.hex[:12]}", actor_id, actor_id),
        )
        meter_id = add_meter(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            utility_type="WATER",
            measurement_unit_code="M3",
        )
        owner.commit()
    return actor_id, property_id, unit_id, meter_id


def service(property_id: UUID, actor_id: UUID) -> PostgresUtilityService:
    return PostgresUtilityService(financial_database_url(), property_id, actor_id)


def primary_tenant_id(connection: Connection[tuple[object, ...]], actor_id: UUID) -> UUID:
    row = connection.execute(
        "SELECT id FROM app.customers WHERE created_by=%s AND legal_name='Primary Lease Customer'",
        (actor_id,),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def database_now() -> datetime:
    with psycopg.connect(financial_database_url()) as connection:
        row = connection.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    assert isinstance(row[0], datetime)
    return row[0]


def finalize_actual(
    utility_service: PostgresUtilityService,
    actor: AuthenticatedActor,
    unit_id: UUID,
    start_reading_id: UUID,
    end_reading_id: UUID,
    *,
    period_id: UUID | None = None,
    idempotency_key: UUID | None = None,
) -> tuple[UUID, FinalizeActualConsumptionCommand]:
    stored_period_id = period_id or uuid4()
    command_value = FinalizeActualConsumptionCommand(
        idempotency_key=idempotency_key or uuid4(),
        consumption_period_id=stored_period_id,
        unit_id=unit_id,
        utility_type="ELECTRICITY",
        start_reading_id=start_reading_id,
        end_reading_id=end_reading_id,
        finalized_at=database_now(),
    )
    utility_service.finalize_actual(command_value, actor=actor)
    return stored_period_id, command_value


def replace_failed_meter(
    migrated_database_url: str,
    *,
    actor_id: UUID,
    unit_id: UUID,
    failed_meter_id: UUID,
    failure_date: date,
    replacement_date: date,
    first_valid_reading_date: date | None = None,
    first_valid_reading_value: str = "0",
    utility_type: str = "ELECTRICITY",
    measurement_unit_code: str = "KWH",
) -> tuple[UUID, UUID]:
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "UPDATE app.utility_meters SET failure_date=%s,deactivated_date=%s,"
            "version=version+1,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (failure_date, replacement_date, actor_id, failed_meter_id),
        )
        replacement_id = add_meter(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            installed_date=replacement_date,
            utility_type=utility_type,
            measurement_unit_code=measurement_unit_code,
        )
        replacement_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=first_valid_reading_date or replacement_date,
            reading_value=first_valid_reading_value,
        )
        owner.execute(
            "INSERT INTO app.utility_meter_replacements("
            "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
            "VALUES (%s,%s,%s,%s,'Confirmed broken Meter',%s)",
            (uuid4(), failed_meter_id, replacement_id, replacement_date, actor_id),
        )
        owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        owner.commit()
    return replacement_id, replacement_reading_id


def replace_failed_meter_in_transaction(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    unit_id: UUID,
    failed_meter_id: UUID,
    failure_date: date,
    replacement_date: date,
    measurement_unit_code: str,
) -> tuple[UUID, UUID]:
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=%s,deactivated_date=%s,"
        "version=version+1,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (failure_date, replacement_date, actor_id, failed_meter_id),
    )
    replacement_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        installed_date=replacement_date,
        measurement_unit_code=measurement_unit_code,
    )
    replacement_reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=replacement_id,
        reading_date=replacement_date,
        reading_value="0",
    )
    connection.execute(
        "INSERT INTO app.utility_meter_replacements("
        "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
        "VALUES (%s,%s,%s,%s,'Confirmed broken Meter',%s)",
        (uuid4(), failed_meter_id, replacement_id, replacement_date, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.execute("SET CONSTRAINTS ALL DEFERRED")
    return replacement_id, replacement_reading_id


def hide_utility_rates_for_transaction(
    connection: Connection[tuple[object, ...]],
) -> None:
    connection.execute(
        "ALTER TABLE app.utility_rates DISABLE TRIGGER utility_rates_reject_update_or_delete"
    )
    connection.execute("DELETE FROM app.utility_rates")
    connection.execute(
        "ALTER TABLE app.utility_rates ENABLE TRIGGER utility_rates_reject_update_or_delete"
    )


def direct_finalize_actual(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    unit_id: UUID,
    start_reading_id: UUID,
    end_reading_id: UUID,
) -> UUID:
    period_id = uuid4()
    connection.execute(
        "SELECT app.finalize_actual_utility_consumption("
        "%s,%s,%s,%s,%s,'ELECTRICITY',%s,%s,clock_timestamp(),%s)",
        (
            property_id,
            uuid4(),
            "a" * 64,
            period_id,
            unit_id,
            start_reading_id,
            end_reading_id,
            actor_id,
        ),
    )
    return period_id


def direct_open_case(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    failed_meter_id: UUID,
    replacement_meter_id: UUID,
) -> UUID:
    case_id = uuid4()
    connection.execute(
        "SELECT app.open_broken_meter_estimation_case("
        "%s,%s,%s,%s,%s,%s,NULL,NULL,%s,clock_timestamp(),%s,'utility.estimate')",
        (
            property_id,
            uuid4(),
            "b" * 64,
            case_id,
            failed_meter_id,
            replacement_meter_id,
            "Confirmed physical Meter failure",
            actor_id,
        ),
    )
    return case_id


def direct_finalize_estimate(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    case_id: UUID,
) -> tuple[UUID, UUID]:
    estimate_id = uuid4()
    consumption_period_id = uuid4()
    connection.execute(
        "SELECT app.finalize_broken_meter_estimate("
        "%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),%s,'utility.estimate')",
        (
            property_id,
            uuid4(),
            "c" * 64,
            case_id,
            estimate_id,
            consumption_period_id,
            "Approved confirmed broken-Meter estimate",
            actor_id,
        ),
    )
    return estimate_id, consumption_period_id


def open_case(
    utility_service: PostgresUtilityService,
    actor: AuthenticatedActor,
    failed_meter_id: UUID,
    replacement_meter_id: UUID,
    *,
    unmeasured_start_date: date | None = None,
    unmeasured_end_date: date | None = None,
) -> tuple[UUID, OpenBrokenMeterCaseCommand]:
    case_id = uuid4()
    command_value = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        failed_meter_id=failed_meter_id,
        replacement_meter_id=replacement_meter_id,
        unmeasured_start_date=unmeasured_start_date,
        unmeasured_end_date=unmeasured_end_date,
        opened_reason="Confirmed physical Meter failure",
        opened_at=database_now(),
    )
    utility_service.open_broken_meter_case(command_value, actor=actor)
    return case_id, command_value


def finalize_estimate(
    utility_service: PostgresUtilityService,
    actor: AuthenticatedActor,
    case_id: UUID,
    *,
    idempotency_key: UUID | None = None,
) -> tuple[UUID, FinalizeBrokenMeterEstimateCommand]:
    period_id = uuid4()
    command_value = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=idempotency_key or uuid4(),
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=period_id,
        authorization_reason="Approved confirmed broken-Meter estimate",
        authorized_at=database_now(),
    )
    utility_service.finalize_broken_meter_estimate(command_value, actor=actor)
    return period_id, command_value


def test_v1_042_is_forward_only_head_with_least_privilege(
    connection: Connection[tuple[object, ...]],
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == "20270204_192"
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "20270204_192",
    )
    source = (
        Path(__file__).parents[1] / "migrations/versions/20260829_33_v1_042_utility_corrections.py"
    ).read_text()
    assert 'raise RuntimeError("V1-042 Utility corrections are forward-only")' in source
    expected_tables = {
        "utility_consumption_periods",
        "broken_meter_estimation_cases",
        "broken_meter_estimates",
        "broken_meter_estimate_basis_periods",
        "utility_reading_correction_impacts",
        "utility_service_commands",
    }
    assert expected_tables <= {
        str(row[0])
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='app'"
        ).fetchall()
    }
    for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
        for table in expected_tables:
            assert connection.execute(
                "SELECT has_table_privilege(%s,%s,'INSERT')",
                (role, f"app.{table}"),
            ).fetchone() == (False,)
    assert connection.execute(
        "SELECT has_function_privilege('prm_financial',"
        "'app.finalize_actual_utility_consumption(uuid,uuid,text,uuid,uuid,text,uuid,uuid,"
        "timestamp with time zone,uuid)','EXECUTE'),"
        "has_function_privilege('prm_runtime',"
        "'app.preview_utility_calculation(uuid,text,uuid,timestamp with time zone,uuid)',"
        "'EXECUTE')"
    ).fetchone() == (True, True)
    with psycopg.connect(runtime_database_url()) as restricted:
        with pytest.raises(Error) as direct_write:
            restricted.execute(
                "INSERT INTO app.utility_consumption_periods("
                "id,unit_id,utility_type,start_date,end_date,calculation_kind,"
                "consumption_quantity,calculation_trace,finalized_at,finalized_by) "
                "VALUES (%s,%s,'ELECTRICITY',current_date,current_date,"
                "'BROKEN_METER_ESTIMATE',0,'{}',statement_timestamp(),%s)",
                (uuid4(), uuid4(), uuid4()),
            )
        assert direct_write.value.sqlstate == "42501"


def test_postgresql_rejects_nonfinite_utility_inputs(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 1),
        reading_value="10",
    )

    assert connection.execute(
        "SELECT 'NaN'::numeric>=0,'NaN'::numeric<'Infinity'::numeric"
    ).fetchone() == (True, False)

    with pytest.raises(Error) as nonfinite_reading:
        with connection.transaction():
            add_reading(
                connection,
                actor_id=actor_id,
                meter_id=meter_id,
                reading_date=date(2026, 1, 2),
                reading_value="NaN",
            )
    assert nonfinite_reading.value.sqlstate == "23514"

    with pytest.raises(Error) as nonfinite_correction:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.utility_reading_corrections("
                "id,reading_id,previous_value,corrected_value,reason,actor_id,"
                "authorization_reference) VALUES (%s,%s,10,'NaN',"
                "'Reject non-finite correction',%s,'utility.reading.correct')",
                (uuid4(), reading_id, actor_id),
            )
    assert nonfinite_correction.value.sqlstate == "23514"

    with pytest.raises(Error) as nonfinite_rate:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.utility_rates("
                "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
                "effective_date,notice_at,notice_evidence,actor_id) VALUES "
                "(%s,%s,'ELECTRICITY','KWH','NaN',DATE '2027-01-01',"
                "TIMESTAMPTZ '2026-12-01 00:00:00+07','NONFINITE-REJECTION',%s)",
                (uuid4(), property_id, actor_id),
            )
    assert nonfinite_rate.value.sqlstate == "23514"


def test_broken_meter_case_rejects_mixed_failed_and_replacement_units(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, property_id, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
        measurement_unit_code="MWH",
    )
    with pytest.raises(Error) as mismatched_pair:
        with connection.transaction():
            direct_open_case(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                failed_meter_id=failed_id,
                replacement_meter_id=replacement_id,
            )
    assert mismatched_pair.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.broken_meter_estimation_cases "
        "WHERE failed_meter_id=%s AND replacement_meter_id=%s",
        (failed_id, replacement_id),
    ).fetchone() == (0,)


def test_broken_meter_case_deferred_assertion_rejects_fabricated_or_misderived_rows(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
        measurement_unit_code="KWH",
    )
    other_actor_id, _, other_unit_id = utility_source(connection)
    other_failed_id = add_meter(
        connection,
        actor_id=other_actor_id,
        unit_id=other_unit_id,
    )
    other_replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=other_actor_id,
        unit_id=other_unit_id,
        failed_meter_id=other_failed_id,
        failure_date=date(2026, 3, 1),
        replacement_date=date(2026, 3, 11),
        measurement_unit_code="KWH",
    )

    with pytest.raises(Error) as fabricated_pair:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.broken_meter_estimation_cases("
                "id,failed_meter_id,replacement_meter_id,unit_id,utility_type,"
                "unmeasured_start_date,unmeasured_end_date,"
                "historical_actual_period_count_at_open,opened_reason,opened_at,"
                "opened_by,authorization_reference) VALUES "
                "(%s,%s,%s,%s,'ELECTRICITY','2026-02-01','2026-02-10',0,"
                "'Fabricated direct pair',clock_timestamp(),%s,'utility.estimate')",
                (uuid4(), failed_id, other_replacement_id, unit_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert fabricated_pair.value.sqlstate == "23514"

    with pytest.raises(Error) as misderived_evidence:
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.broken_meter_estimation_cases("
                "id,failed_meter_id,replacement_meter_id,unit_id,utility_type,"
                "unmeasured_start_date,unmeasured_end_date,"
                "historical_actual_period_count_at_open,opened_reason,opened_at,"
                "opened_by,authorization_reference) VALUES "
                "(%s,%s,%s,%s,'ELECTRICITY','2026-02-02','2026-02-10',1,"
                "'Misderived direct evidence',clock_timestamp(),%s,'utility.estimate')",
                (uuid4(), failed_id, replacement_id, unit_id, actor_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert misderived_evidence.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.broken_meter_estimation_cases "
        "WHERE failed_meter_id=%s OR replacement_meter_id=%s",
        (failed_id, other_replacement_id),
    ).fetchone() == (0,)


def test_broken_meter_case_rejects_mixed_historical_basis_units(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, property_id, unit_id = utility_source(connection)
    historical_meter_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        measurement_unit_code="MWH",
    )
    historical_readings = (
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=historical_meter_id,
            reading_date=date(2026, 1, 1),
            reading_value="0",
        ),
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=historical_meter_id,
            reading_date=date(2026, 1, 11),
            reading_value="1",
        ),
    )
    direct_finalize_actual(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        start_reading_id=historical_readings[0],
        end_reading_id=historical_readings[1],
    )
    current_meter_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=historical_meter_id,
        failure_date=date(2026, 1, 20),
        replacement_date=date(2026, 2, 1),
        measurement_unit_code="KWH",
    )
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=current_meter_id,
        failure_date=date(2026, 2, 10),
        replacement_date=date(2026, 2, 20),
        measurement_unit_code="KWH",
    )
    with pytest.raises(Error) as mismatched_history:
        with connection.transaction():
            direct_open_case(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                failed_meter_id=current_meter_id,
                replacement_meter_id=replacement_id,
            )
    assert mismatched_history.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.broken_meter_estimation_cases "
        "WHERE failed_meter_id=%s AND replacement_meter_id=%s",
        (current_meter_id, replacement_id),
    ).fetchone() == (0,)


def test_broken_meter_case_ignores_an_unselected_legacy_unit_period(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, property_id, unit_id = utility_source(connection)
    legacy_meter_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        measurement_unit_code="MWH",
    )
    legacy_start_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=legacy_meter_id,
        reading_date=date(2026, 1, 1),
        reading_value="0",
    )
    legacy_end_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=legacy_meter_id,
        reading_date=date(2026, 1, 11),
        reading_value="1",
    )
    direct_finalize_actual(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unit_id,
        start_reading_id=legacy_start_id,
        end_reading_id=legacy_end_id,
    )
    current_meter_id, first_current_reading_id = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=legacy_meter_id,
        failure_date=date(2026, 1, 11),
        replacement_date=date(2026, 1, 12),
        measurement_unit_code="KWH",
    )
    current_reading_ids = [first_current_reading_id]
    for reading_date, reading_value in (
        (date(2026, 1, 22), "10"),
        (date(2026, 2, 1), "20"),
        (date(2026, 2, 11), "30"),
    ):
        current_reading_ids.append(
            add_reading(
                connection,
                actor_id=actor_id,
                meter_id=current_meter_id,
                reading_date=reading_date,
                reading_value=reading_value,
            )
        )
    selected_period_ids = tuple(
        direct_finalize_actual(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            unit_id=unit_id,
            start_reading_id=start_reading_id,
            end_reading_id=end_reading_id,
        )
        for start_reading_id, end_reading_id in pairwise(current_reading_ids)
    )
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=current_meter_id,
        failure_date=date(2026, 2, 11),
        replacement_date=date(2026, 2, 20),
        measurement_unit_code="KWH",
    )
    case_id = direct_open_case(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        failed_meter_id=current_meter_id,
        replacement_meter_id=replacement_id,
    )
    preview_row = connection.execute(
        "SELECT app.utility_case_preview_snapshot(%s)", (case_id,)
    ).fetchone()
    assert preview_row is not None
    assert isinstance(preview_row[0], dict)
    assert preview_row[0]["basis_period_ids"] == [
        str(period_id) for period_id in reversed(selected_period_ids)
    ]


def test_broken_meter_rejects_mixed_first_future_basis_before_period_persistence(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, property_id, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
        measurement_unit_code="KWH",
    )
    case_id = direct_open_case(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
    )
    future_meter_id, future_start_reading_id = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=replacement_id,
        failure_date=date(2026, 3, 10),
        replacement_date=date(2026, 3, 11),
        measurement_unit_code="MWH",
    )
    future_end_reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=future_meter_id,
        reading_date=date(2026, 3, 21),
        reading_value="1",
    )
    with pytest.raises(Error) as mismatched_future:
        with connection.transaction():
            direct_finalize_actual(
                connection,
                actor_id=actor_id,
                property_id=property_id,
                unit_id=unit_id,
                start_reading_id=future_start_reading_id,
                end_reading_id=future_end_reading_id,
            )
    assert mismatched_future.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.broken_meter_estimates WHERE estimation_case_id=%s",
        (case_id,),
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT count(*) FROM app.utility_consumption_periods "
        "WHERE start_reading_id=%s AND end_reading_id=%s",
        (future_start_reading_id, future_end_reading_id),
    ).fetchone() == (0,)


def test_deferred_zero_history_basis_requires_an_exact_future_period(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
        measurement_unit_code="KWH",
    )
    case_id = direct_open_case(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
    )

    unrelated_unit_id = uuid4()
    connection.execute(
        "INSERT INTO app.units("
        "id,property_id,unit_number,floor,unit_type,status,created_by,updated_by) "
        "VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
        (
            unrelated_unit_id,
            property_id,
            f"UNRELATED-BASIS-{unrelated_unit_id.hex[:12]}",
            actor_id,
            actor_id,
        ),
    )
    unrelated_meter_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unrelated_unit_id,
        installed_date=date(2026, 4, 1),
    )
    unrelated_start_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=unrelated_meter_id,
        reading_date=date(2026, 4, 1),
        reading_value="0",
    )
    unrelated_end_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=unrelated_meter_id,
        reading_date=date(2026, 4, 11),
        reading_value="10",
    )
    unrelated_period_id = direct_finalize_actual(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        unit_id=unrelated_unit_id,
        start_reading_id=unrelated_start_id,
        end_reading_id=unrelated_end_id,
    )
    case_row = connection.execute(
        "SELECT unmeasured_start_date,unmeasured_end_date FROM "
        "app.broken_meter_estimation_cases WHERE id=%s",
        (case_id,),
    ).fetchone()
    basis_row = connection.execute(
        "SELECT consumption_quantity,end_date-start_date+1 "
        "FROM app.utility_consumption_periods WHERE id=%s",
        (unrelated_period_id,),
    ).fetchone()
    assert case_row is not None and basis_row is not None
    case_start, case_end = case_row
    basis_quantity, basis_days = basis_row
    assert isinstance(case_start, date) and isinstance(case_end, date)
    assert isinstance(basis_quantity, Decimal) and isinstance(basis_days, int)
    unmeasured_days = (case_end - case_start).days + 1
    weighted_average = (basis_quantity / basis_days).quantize(Decimal("0.0000000001"))
    estimated_quantity = (basis_quantity * unmeasured_days / basis_days).quantize(
        Decimal("0.000001")
    )
    estimate_period_id = uuid4()
    estimate_id = uuid4()
    authorized_at = database_now()

    with pytest.raises(Error) as missing_expected_basis:
        with connection.transaction():
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "INSERT INTO app.utility_consumption_periods("
                "id,unit_id,utility_type,start_date,end_date,calculation_kind,"
                "consumption_quantity,calculation_trace,finalized_at,finalized_by) "
                "VALUES (%s,%s,'ELECTRICITY',%s,%s,'BROKEN_METER_ESTIMATE',"
                "%s,'{}'::jsonb,%s,%s)",
                (
                    estimate_period_id,
                    unit_id,
                    case_start,
                    case_end,
                    estimated_quantity,
                    authorized_at,
                    actor_id,
                ),
            )
            connection.execute(
                "INSERT INTO app.broken_meter_estimates("
                "id,estimation_case_id,consumption_period_id,basis_kind,"
                "historical_actual_period_count_at_selection,total_basis_consumption,"
                "total_basis_days,weighted_daily_average,estimated_consumption,"
                "authorization_reason,authorized_at,authorized_by,calculation_trace) "
                "VALUES (%s,%s,%s,'FIRST_COMPLETE_FUTURE_ZERO_HISTORY',0,%s,%s,%s,%s,"
                "'Attempted unrelated basis repair',%s,%s,'{}'::jsonb)",
                (
                    estimate_id,
                    case_id,
                    estimate_period_id,
                    basis_quantity,
                    basis_days,
                    weighted_average,
                    estimated_quantity,
                    authorized_at,
                    actor_id,
                ),
            )
            connection.execute(
                "INSERT INTO app.broken_meter_estimate_basis_periods("
                "broken_meter_estimate_id,basis_consumption_period_id,basis_order) "
                "VALUES (%s,%s,1)",
                (estimate_id, unrelated_period_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert missing_expected_basis.value.sqlstate == "23514"
    assert connection.execute(
        "SELECT count(*) FROM app.broken_meter_estimates WHERE id=%s",
        (estimate_id,),
    ).fetchone() == (0,)


def test_open_case_freezes_failed_and_replacement_meter_units(
    connection: Connection[tuple[object, ...]],
) -> None:
    hide_utility_rates_for_transaction(connection)
    actor_id, property_id, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    replacement_id, _ = replace_failed_meter_in_transaction(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
        measurement_unit_code="KWH",
    )
    case_id = direct_open_case(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
    )
    for meter_id in (failed_id, replacement_id):
        with pytest.raises(Error) as changed_unit:
            with connection.transaction():
                connection.execute(
                    "UPDATE app.utility_meters SET measurement_unit_code='MWH',"
                    "version=version+1,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, meter_id),
                )
        assert changed_unit.value.sqlstate == "55000"
    assert connection.execute(
        "SELECT failed.measurement_unit_code,replacement.measurement_unit_code "
        "FROM app.broken_meter_estimation_cases AS case_record "
        "JOIN app.utility_meters AS failed ON failed.id=case_record.failed_meter_id "
        "JOIN app.utility_meters AS replacement ON replacement.id=case_record.replacement_meter_id "
        "WHERE case_record.id=%s",
        (case_id,),
    ).fetchone() == ("KWH", "KWH")


def test_case_opening_and_meter_unit_change_serialize_without_mixed_evidence(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id = committed_isolated_source(migrated_database_url)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
        utility_type="WATER",
        measurement_unit_code="M3",
    )
    application_names = (
        f"v1042-case-unit-race-{uuid4().hex}",
        f"v1042-meter-unit-race-{uuid4().hex}",
    )

    def open_case_write() -> str:
        try:
            with psycopg.connect(
                make_conninfo(
                    financial_database_url(),
                    application_name=application_names[0],
                )
            ) as concurrent:
                direct_open_case(
                    concurrent,
                    actor_id=actor_id,
                    property_id=property_id,
                    failed_meter_id=failed_id,
                    replacement_meter_id=replacement_id,
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    def change_meter_unit() -> str:
        try:
            with psycopg.connect(
                make_conninfo(
                    migrated_database_url,
                    application_name=application_names[1],
                )
            ) as concurrent:
                concurrent.execute(
                    "UPDATE app.utility_meters SET measurement_unit_code='LITRE',"
                    "version=version+1,updated_at=statement_timestamp(),updated_by=%s "
                    "WHERE id=%s",
                    (actor_id, failed_id),
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute(
            "SELECT app.lock_utility_property_type(%s,'WATER')",
            (property_id,),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(open_case_write),
                executor.submit(change_meter_unit),
            )
            assert_sessions_wait_for_lock(*application_names)
            blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    assert outcomes.count("success") == 1
    assert {"23514", "55000"} & set(outcomes)
    with psycopg.connect(migrated_database_url) as owner:
        persisted = owner.execute(
            "SELECT (SELECT count(*) FROM app.broken_meter_estimation_cases "
            "WHERE failed_meter_id=%s AND replacement_meter_id=%s),"
            "(SELECT measurement_unit_code FROM app.utility_meters WHERE id=%s),"
            "(SELECT measurement_unit_code FROM app.utility_meters WHERE id=%s)",
            (failed_id, replacement_id, failed_id, replacement_id),
        ).fetchone()
    assert persisted in {(1, "M3", "M3"), (0, "LITRE", "M3")}


def test_actual_service_is_exact_idempotent_and_append_preserved(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "10.125000"), (date(2026, 1, 11), "21.500000")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, actual_command = finalize_actual(
        utility_service, actor, unit_id, readings[0], readings[1]
    )
    snapshot = utility_service.finalize_actual(actual_command, actor=actor)
    assert snapshot.status is UtilityCalculationStatus.READY
    assert snapshot.calculation_kind is UtilityCalculationKind.ACTUAL
    assert snapshot.period_start == date(2026, 1, 2)
    assert snapshot.period_end == date(2026, 1, 11)
    assert snapshot.represented_days == 10
    assert snapshot.consumption_quantity == Decimal("11.375000")
    assert snapshot.meter_id is not None
    assert snapshot.start_reading_id == readings[0]
    assert snapshot.end_reading_id == readings[1]
    assert snapshot.total_basis_consumption is None
    assert snapshot.total_basis_days is None
    assert snapshot.weighted_daily_average is None
    conflicting_command = FinalizeActualConsumptionCommand(
        idempotency_key=actual_command.idempotency_key,
        consumption_period_id=uuid4(),
        unit_id=unit_id,
        utility_type="ELECTRICITY",
        start_reading_id=readings[0],
        end_reading_id=readings[1],
        finalized_at=actual_command.finalized_at,
    )
    with pytest.raises(UtilityIdempotencyKeyReused):
        utility_service.finalize_actual(conflicting_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*),count(DISTINCT result_snapshot) FROM app.utility_service_commands "
            "WHERE idempotency_key=%s",
            (actual_command.idempotency_key,),
        ).fetchone() == (1, 1)
        for statement in (
            "UPDATE app.utility_consumption_periods SET consumption_quantity=99 WHERE id=%s",
            "DELETE FROM app.utility_consumption_periods WHERE id=%s",
        ):
            with pytest.raises(Error) as mutation:
                with owner.transaction():
                    owner.execute(statement, (period_id,))
            assert mutation.value.sqlstate == "55000"


def test_json_snapshots_preserve_maximum_consumption_and_rate_precision(
    migrated_database_url: str,
) -> None:
    maximum_quantity = Decimal("99999999999999.999999")
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), str(maximum_quantity))),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, command_value = finalize_actual(
        utility_service, actor, unit_id, readings[0], readings[1]
    )
    replay = utility_service.finalize_actual(command_value, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        rate_id = uuid4()
        owner.execute(
            "INSERT INTO app.utility_rates("
            "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
            "effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',900.00000001,DATE '2025-01-01',"
            "TIMESTAMPTZ '2024-12-31 00:00:00+07','PRECISION',%s)",
            (rate_id, property_id, actor_id),
        )
        owner.commit()
    preview = utility_service.preview(
        period_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    assert replay.consumption_quantity == maximum_quantity
    assert preview.consumption_quantity == maximum_quantity
    assert preview.rate_usd_per_unit == Decimal("900.00000001")
    assert preview.amount_usd_cents == 9_000_000_000_100_000_000
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_rates("
            "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
            "effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',1000.00000001,DATE '2026-08-01',"
            "TIMESTAMPTZ '2026-07-31 00:00:00+07','OVERFLOW BOUNDARY',%s)",
            (uuid4(), property_id, actor_id),
        )
        owner.commit()
    with pytest.raises(UtilityInvalidError):
        utility_service.preview(
            period_id,
            database_now(),
            source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
            actor=actor,
        )


def test_broken_meter_rejects_derived_values_beyond_canonical_precision(
    migrated_database_url: str,
) -> None:
    maximum_quantity = Decimal("99999999999999.999999")
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), str(maximum_quantity))),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    first_basis_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, readings[0], readings[1]
    )
    second_meter_id, second_start_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 1, 11),
        replacement_date=date(2026, 1, 12),
    )
    with psycopg.connect(migrated_database_url) as owner:
        second_end_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=second_meter_id,
            reading_date=date(2026, 1, 22),
            reading_value=str(maximum_quantity),
        )
        owner.commit()
    second_basis_period_id, _ = finalize_actual(
        utility_service,
        actor,
        unit_id,
        second_start_reading_id,
        second_end_reading_id,
    )
    third_meter_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=second_meter_id,
        failure_date=date(2026, 1, 22),
        replacement_date=date(2026, 2, 12),
    )
    case_id, _ = open_case(utility_service, actor, second_meter_id, third_meter_id)
    estimate_command = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=uuid4(),
        authorization_reason="Approved precision-boundary estimate",
        authorized_at=database_now(),
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimates WHERE id=%s",
            (estimate_command.estimate_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (estimate_command.consumption_period_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (estimate_command.idempotency_key,),
        ).fetchone() == (0,)
        assert {
            row[0]
            for row in owner.execute(
                "SELECT id FROM app.utility_consumption_periods WHERE id IN (%s,%s)",
                (first_basis_period_id, second_basis_period_id),
            ).fetchall()
        } == {first_basis_period_id, second_basis_period_id}


def test_idempotency_key_scope_includes_utility_action(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    shared_key = uuid4()
    finalize_actual(
        utility_service,
        actor,
        unit_id,
        readings[0],
        readings[1],
        idempotency_key=shared_key,
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_command = OpenBrokenMeterCaseCommand(
        idempotency_key=shared_key,
        estimation_case_id=uuid4(),
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Same idempotency value in a distinct action scope",
        opened_at=database_now(),
    )
    utility_service.open_broken_meter_case(case_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT array_agg(action ORDER BY action) FROM app.utility_service_commands "
            "WHERE property_id=%s AND actor_id=%s AND idempotency_key=%s",
            (property_id, actor_id, shared_key),
        ).fetchone() == (["FINALIZE_ACTUAL", "OPEN_BROKEN_METER_CASE"],)


def test_replay_rechecks_current_actor_lifecycle_for_every_utility_command(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    _, actual_command = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, case_command = open_case(utility_service, actor, failed_id, replacement_id)
    _, estimate_command = finalize_estimate(utility_service, actor, case_id)
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (actor_id,),
        )
        owner.commit()
    with pytest.raises(UtilityAuthorizationError, match="no longer active"):
        utility_service.finalize_actual(actual_command, actor=actor)
    with pytest.raises(UtilityAuthorizationError, match="no longer active"):
        utility_service.open_broken_meter_case(case_command, actor=actor)
    with pytest.raises(UtilityAuthorizationError, match="no longer active"):
        utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE actor_id=%s",
            (actor_id,),
        ).fetchone() == (3,)


def test_concurrent_actual_commands_preserve_unit_exclusivity(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 2, 1), "100"), (date(2026, 2, 11), "125")),
    )
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)

    def attempt(_: int) -> str:
        try:
            finalize_actual(
                service(property_id, actor_id), actor, unit_id, readings[0], readings[1]
            )
        except Exception as exc:  # the public service maps the database conflict
            return type(exc).__name__
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(attempt, (1, 2)))
    assert outcomes == ["UtilityConflictError", "success"]
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods "
            "WHERE unit_id=%s AND start_date=DATE '2026-02-02'",
            (unit_id,),
        ).fetchone() == (1,)


def test_actual_period_rejects_customer_responsibility_boundary_in_both_directions(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    with psycopg.connect(migrated_database_url) as owner:
        lease_id = create_draft(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=primary_tenant_id(owner, actor_id),
            start_date=date(2026, 1, 6),
            end_date=date(2026, 12, 31),
        )
        sign_lease(owner, lease_id, actor_id)
        owner.commit()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    rejected_period_id = uuid4()
    rejected_command = FinalizeActualConsumptionCommand(
        idempotency_key=uuid4(),
        consumption_period_id=rejected_period_id,
        unit_id=unit_id,
        utility_type="ELECTRICITY",
        start_reading_id=readings[0],
        end_reading_id=readings[1],
        finalized_at=database_now(),
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.finalize_actual(rejected_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (rejected_period_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (rejected_command.idempotency_key,),
        ).fetchone() == (0,)

    later_actor_id, later_property_id, later_unit_id, _, later_readings = committed_source(
        migrated_database_url,
        ((date(2026, 3, 1), "0"), (date(2026, 3, 11), "10")),
    )
    later_service = service(later_property_id, later_actor_id)
    later_actor = authorized_actor(later_actor_id, later_property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, _ = finalize_actual(
        later_service,
        later_actor,
        later_unit_id,
        later_readings[0],
        later_readings[1],
    )
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as late_responsibility:
            with owner.transaction():
                lease_id = create_draft(
                    owner,
                    actor_id=later_actor_id,
                    unit_id=later_unit_id,
                    primary_tenant_id=primary_tenant_id(owner, later_actor_id),
                    start_date=date(2026, 3, 6),
                    end_date=date(2026, 12, 31),
                )
                sign_lease(owner, lease_id, later_actor_id)
        assert late_responsibility.value.sqlstate == "23514"
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (period_id,),
        ).fetchone() == (1,)


def test_non_signer_occupants_do_not_create_utility_responsibility_boundaries(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    with psycopg.connect(migrated_database_url) as owner:
        lease_id = create_draft(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=primary_tenant_id(owner, actor_id),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        sign_lease(owner, lease_id, actor_id)
        first_occupant_id = uuid4()
        owner.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Non-signing Utility Occupant One',%s,%s)",
            (first_occupant_id, actor_id, actor_id),
        )
        owner.execute(
            "INSERT INTO app.occupancies("
            "id,lease_id,customer_id,move_in_date,move_out_date,created_by,updated_by) "
            "VALUES (%s,%s,%s,DATE '2026-01-05',DATE '2026-01-08',%s,%s)",
            (uuid4(), lease_id, first_occupant_id, actor_id, actor_id),
        )
        owner.commit()

    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])

    with psycopg.connect(migrated_database_url) as owner:
        second_occupant_id = uuid4()
        owner.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Non-signing Utility Occupant Two',%s,%s)",
            (second_occupant_id, actor_id, actor_id),
        )
        owner.execute(
            "INSERT INTO app.occupancies("
            "id,lease_id,customer_id,move_in_date,created_by,updated_by) "
            "VALUES (%s,%s,%s,DATE '2026-01-06',%s,%s)",
            (uuid4(), lease_id, second_occupant_id, actor_id, actor_id),
        )
        owner.commit()
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (period_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.occupancies WHERE lease_id=%s",
            (lease_id,),
        ).fetchone() == (2,)


def test_concurrent_actual_period_and_responsibility_change_serialize(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 4, 1), "0"), (date(2026, 4, 11), "10")),
    )
    with psycopg.connect(migrated_database_url) as owner:
        lease_id = create_draft(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=primary_tenant_id(owner, actor_id),
            start_date=date(2026, 4, 6),
            end_date=date(2026, 12, 31),
        )
        owner.commit()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    start_together = Barrier(2)

    def finalize_crossing_period() -> str:
        start_together.wait(timeout=10)
        try:
            finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
        except UtilityInvalidError:
            return "period_rejected"
        return "period_committed"

    def sign_crossing_lease() -> str:
        start_together.wait(timeout=10)
        try:
            with psycopg.connect(migrated_database_url) as writer:
                sign_lease(writer, lease_id, actor_id)
        except Error as error:
            assert error.sqlstate == "23514"
            return "lease_rejected"
        return "lease_committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        period_future = executor.submit(finalize_crossing_period)
        lease_future = executor.submit(sign_crossing_lease)
        results = {period_future.result(timeout=20), lease_future.result(timeout=20)}
    assert results in (
        {"period_committed", "lease_rejected"},
        {"period_rejected", "lease_committed"},
    )


@pytest.mark.parametrize("history_count", [1, 2])
def test_broken_meter_uses_all_one_or_two_historical_periods(
    migrated_database_url: str,
    history_count: int,
) -> None:
    points = (
        (date(2026, 1, 1), "0"),
        (date(2026, 1, 11), "10"),
        (date(2026, 1, 21), "30"),
    )[: history_count + 1]
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url, points
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    expected_basis = []
    for index in range(history_count):
        period_id, _ = finalize_actual(
            utility_service, actor, unit_id, readings[index], readings[index + 1]
        )
        expected_basis.append(period_id)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    _, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.status is UtilityCalculationStatus.READY
    assert snapshot.basis_kind is UtilityBasisKind.ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO
    assert snapshot.basis_period_ids == tuple(reversed(expected_basis))
    expected_quantity = Decimal("10.000000") if history_count == 1 else Decimal("15.000000")
    assert snapshot.consumption_quantity == expected_quantity


def test_broken_meter_case_splits_at_move_in_responsibility_boundary(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    with psycopg.connect(migrated_database_url) as owner:
        tenant_id = primary_tenant_id(owner, actor_id)
        lease_id = create_draft(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        sign_lease(owner, lease_id, actor_id)
        owner.execute(
            "INSERT INTO app.occupancies("
            "id,lease_id,customer_id,move_in_date,created_by,updated_by) "
            "VALUES (%s,%s,%s,DATE '2026-02-05',%s,%s)",
            (uuid4(), lease_id, tenant_id, actor_id, actor_id),
        )
        owner.commit()
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    first_case_id, first_command = open_case(
        utility_service,
        actor,
        failed_id,
        replacement_id,
        unmeasured_start_date=date(2026, 2, 1),
        unmeasured_end_date=date(2026, 2, 4),
    )
    second_case_id, second_command = open_case(
        utility_service,
        actor,
        failed_id,
        replacement_id,
        unmeasured_start_date=date(2026, 2, 5),
        unmeasured_end_date=date(2026, 2, 10),
    )
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT id,unmeasured_start_date,unmeasured_end_date "
            "FROM app.broken_meter_estimation_cases WHERE id IN (%s,%s) "
            "ORDER BY unmeasured_start_date",
            (first_case_id, second_case_id),
        ).fetchall() == [
            (first_case_id, date(2026, 2, 1), date(2026, 2, 4)),
            (second_case_id, date(2026, 2, 5), date(2026, 2, 10)),
        ]
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key IN (%s,%s)",
            (first_command.idempotency_key, second_command.idempotency_key),
        ).fetchone() == (2,)

    invalid_command = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=uuid4(),
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        unmeasured_start_date=date(2026, 2, 2),
        unmeasured_end_date=date(2026, 2, 4),
        opened_reason="Unapproved partial Customer period",
        opened_at=database_now(),
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(invalid_command, actor=actor)


def test_broken_meter_case_ignores_non_signer_occupancy_boundaries(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    with psycopg.connect(migrated_database_url) as owner:
        tenant_id = primary_tenant_id(owner, actor_id)
        lease_id = create_draft(
            owner,
            actor_id=actor_id,
            unit_id=unit_id,
            primary_tenant_id=tenant_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        sign_lease(owner, lease_id, actor_id)
        occupant_id = uuid4()
        owner.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Non-signing Broken Meter Occupant',%s,%s)",
            (occupant_id, actor_id, actor_id),
        )
        owner.execute(
            "INSERT INTO app.occupancies("
            "id,lease_id,customer_id,move_in_date,created_by,updated_by) "
            "VALUES (%s,%s,%s,DATE '2026-02-05',%s,%s)",
            (uuid4(), lease_id, occupant_id, actor_id, actor_id),
        )
        owner.commit()
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    snapshot = utility_service.preview(
        case_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.ESTIMATION_CASE,
        actor=actor,
    )
    assert snapshot.status is UtilityCalculationStatus.PENDING_FUTURE_ACTUAL_BASIS


def test_estimate_basis_is_atomically_audited_and_replayed_once(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    basis_period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    replay = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert replay.consumption_period_id == period_id
    with psycopg.connect(migrated_database_url) as owner:
        audit = owner.execute(
            "SELECT action,entity_type,entity_id,reason,authorization_reference,"
            "property_id,correlation_id,source,outcome,unit_id,"
            "authorization_evidence->>'basis_kind',"
            "authorization_evidence->'basis_period_ids',"
            "previous_state->>'status',resulting_state->>'consumption_period_id' "
            "FROM app.audit_events WHERE id=%s",
            (estimate_command.estimate_id,),
        ).fetchone()
        assert audit == (
            "utility.estimate.finalized",
            "broken_meter_estimate",
            estimate_command.estimate_id,
            estimate_command.authorization_reason,
            "utility.estimate",
            property_id,
            estimate_command.idempotency_key,
            "API",
            "SUCCEEDED",
            unit_id,
            "ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO",
            [str(basis_period_id)],
            "READY",
            str(period_id),
        )
        assert owner.execute(
            "SELECT count(*) FROM app.audit_events WHERE id=%s",
            (estimate_command.estimate_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands "
            "WHERE action='FINALIZE_BROKEN_METER_ESTIMATE' AND idempotency_key=%s",
            (estimate_command.idempotency_key,),
        ).fetchone() == (1,)


def test_distinct_key_duplicate_estimate_finalization_is_a_state_conflict(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    _, first_command = finalize_estimate(utility_service, actor, case_id)
    competing_command = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=uuid4(),
        authorization_reason="Competing finalization for the same preserved case",
        authorized_at=database_now(),
    )
    with pytest.raises(UtilityConflictError):
        utility_service.finalize_broken_meter_estimate(competing_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimates WHERE estimation_case_id=%s",
            (case_id,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands "
            "WHERE action='FINALIZE_BROKEN_METER_ESTIMATE' "
            "AND idempotency_key IN (%s,%s)",
            (first_command.idempotency_key, competing_command.idempotency_key),
        ).fetchone() == (1,)


def test_latest_three_weighted_basis_and_generation_date_rate(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        (
            (date(2026, 1, 1), "0"),
            (date(2026, 1, 11), "10"),
            (date(2026, 1, 21), "30"),
            (date(2026, 1, 31), "60"),
            (date(2026, 4, 30), "100"),
        ),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    periods = [
        finalize_actual(utility_service, actor, unit_id, readings[index], readings[index + 1])[0]
        for index in range(4)
    ]
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 5, 1),
        replacement_date=date(2026, 5, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT (snapshot->>'total_basis_consumption')::numeric,"
            "(snapshot->>'total_basis_days')::integer,"
            "(snapshot->>'weighted_daily_average')::numeric "
            "FROM (SELECT app.utility_case_preview_snapshot(%s) AS snapshot) AS preview",
            (case_id,),
        ).fetchone() == (Decimal("90.000000"), 109, Decimal("0.8256880734"))
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.basis_kind is UtilityBasisKind.LATEST_THREE_HISTORICAL
    assert snapshot.basis_period_ids == tuple(reversed(periods[1:]))
    assert snapshot.failed_meter_id == failed_id
    assert snapshot.replacement_meter_id == replacement_id
    assert tuple(source.consumption_period_id for source in snapshot.basis_sources) == tuple(
        reversed(periods[1:])
    )
    assert all(source.meter_id == failed_id for source in snapshot.basis_sources)
    assert snapshot.total_basis_consumption == Decimal("90.000000")
    assert snapshot.total_basis_days == 109
    assert snapshot.weighted_daily_average == Decimal("0.8256880734")
    assert snapshot.consumption_quantity == Decimal("8.256881")
    with psycopg.connect(migrated_database_url) as owner:
        first_rate_id = uuid4()
        second_rate_id = uuid4()
        owner.execute(
            "INSERT INTO app.utility_rates("
            "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
            "effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',0.25,DATE '2026-01-01',"
            "TIMESTAMPTZ '2025-12-31 00:00:00+07','FIRST',%s),"
            "(%s,%s,'ELECTRICITY','KWH',0.30,DATE '2026-05-05',"
            "TIMESTAMPTZ '2026-05-04 00:00:00+07','SECOND',%s)",
            (first_rate_id, property_id, actor_id, second_rate_id, property_id, actor_id),
        )
        owner.commit()
    before_rate = utility_service.preview(
        estimate_period_id,
        datetime(2026, 5, 4, 16, 59, tzinfo=UTC),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    after_rate = utility_service.preview(
        estimate_period_id,
        datetime(2026, 5, 4, 17, 0, tzinfo=UTC),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    assert (before_rate.rate_id, before_rate.amount_usd_cents) == (first_rate_id, 206)
    assert (after_rate.rate_id, after_rate.amount_usd_cents) == (second_rate_id, 248)
    assert (
        before_rate.total_basis_consumption,
        before_rate.total_basis_days,
        before_rate.weighted_daily_average,
    ) == (Decimal("90.000000"), 109, Decimal("0.8256880734"))
    assert (
        after_rate.total_basis_consumption,
        after_rate.total_basis_days,
        after_rate.weighted_daily_average,
    ) == (Decimal("90.000000"), 109, Decimal("0.8256880734"))


def test_zero_history_stays_pending_until_first_complete_future_actual(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, replacement_start_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
        first_valid_reading_value="5",
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    pending = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=uuid4(),
        authorization_reason="Await exact future basis",
        authorized_at=database_now(),
    )
    pending_preview = utility_service.preview(
        case_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.ESTIMATION_CASE,
        actor=actor,
    )
    assert pending_preview.status is UtilityCalculationStatus.PENDING_FUTURE_ACTUAL_BASIS
    assert pending_preview.consumption_period_id is None
    assert pending_preview.failed_meter_id == failed_id
    assert pending_preview.replacement_meter_id == replacement_id
    assert pending_preview.total_basis_consumption is None
    assert pending_preview.total_basis_days is None
    assert pending_preview.weighted_daily_average is None
    pending_snapshot = utility_service.finalize_broken_meter_estimate(pending, actor=actor)
    assert pending_snapshot.status is UtilityCalculationStatus.PENDING_FUTURE_ACTUAL_BASIS
    changed_pending = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=pending.idempotency_key,
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=uuid4(),
        authorization_reason="Changed request under the preserved pending key",
        authorized_at=pending.authorized_at,
    )
    with pytest.raises(UtilityIdempotencyKeyReused):
        utility_service.finalize_broken_meter_estimate(changed_pending, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        future_readings = (
            replacement_start_reading_id,
            add_reading(
                owner,
                actor_id=actor_id,
                meter_id=replacement_id,
                reading_date=date(2026, 3, 11),
                reading_value="25",
            ),
        )
        owner.commit()
    future_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, future_readings[0], future_readings[1]
    )
    pending_replay = utility_service.finalize_broken_meter_estimate(pending, actor=actor)
    assert pending_replay == pending_snapshot
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.basis_kind is UtilityBasisKind.FIRST_COMPLETE_FUTURE_ZERO_HISTORY
    assert snapshot.basis_period_ids == (future_period_id,)
    assert snapshot.consumption_period_id == estimate_period_id
    assert snapshot.consumption_quantity == Decimal("56.000000")
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (pending.idempotency_key,),
        ).fetchone() == (1,)
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimates WHERE id=%s",
            (pending.estimate_id,),
        ).fetchone() == (0,)


def test_zero_history_case_opens_ready_when_future_basis_already_exists(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, replacement_start_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
    )
    with psycopg.connect(migrated_database_url) as owner:
        replacement_end_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 3, 11),
            reading_value="20",
        )
        owner.commit()
    future_period_id, _ = finalize_actual(
        utility_service,
        actor,
        unit_id,
        replacement_start_reading_id,
        replacement_end_reading_id,
    )
    stale_case_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        stale_opened_at_row = owner.execute(
            "SELECT finalized_at-INTERVAL '1 microsecond' "
            "FROM app.utility_consumption_periods WHERE id=%s",
            (future_period_id,),
        ).fetchone()
    assert stale_opened_at_row is not None
    assert isinstance(stale_opened_at_row[0], datetime)
    stale_command = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=stale_case_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Opening timestamp predates the existing future basis",
        opened_at=stale_opened_at_row[0],
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(stale_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimation_cases WHERE id=%s",
            (stale_case_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (stale_command.idempotency_key,),
        ).fetchone() == (0,)
    case_id = uuid4()
    command_value = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Confirmed after the future basis was finalized",
        opened_at=database_now(),
    )
    snapshot = utility_service.open_broken_meter_case(command_value, actor=actor)
    replay = utility_service.open_broken_meter_case(command_value, actor=actor)
    assert snapshot.status is UtilityCalculationStatus.READY
    assert replay.status is UtilityCalculationStatus.READY
    with psycopg.connect(migrated_database_url) as owner:
        if (
            owner.execute(
                "SELECT 1 FROM app.utility_rates "
                "WHERE property_id=%s AND utility_type='ELECTRICITY' "
                "AND effective_date<=DATE '2026-08-28' LIMIT 1",
                (property_id,),
            ).fetchone()
            is None
        ):
            add_rate(
                owner,
                actor_id=actor_id,
                property_id=property_id,
                utility_type="ELECTRICITY",
                measurement_unit_code="KWH",
            )
        owner.commit()
    preview = utility_service.preview(
        case_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.ESTIMATION_CASE,
        actor=actor,
    )
    assert preview.basis_period_ids == (future_period_id,)


def test_zero_history_case_rejects_a_later_future_period_when_the_first_is_unfinalized(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, first_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
    )
    with psycopg.connect(migrated_database_url) as owner:
        middle_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 3, 11),
            reading_value="20",
        )
        last_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 3, 21),
            reading_value="30",
        )
        owner.commit()
    later_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, middle_reading_id, last_reading_id
    )
    blocked_case_id = uuid4()
    blocked_command = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=blocked_case_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="The first future period remains unfinalized",
        opened_at=database_now(),
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(blocked_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimation_cases WHERE id=%s",
            (blocked_case_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (blocked_command.idempotency_key,),
        ).fetchone() == (0,)

    first_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, first_reading_id, middle_reading_id
    )
    accepted_command = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=uuid4(),
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="The first future period is now finalized",
        opened_at=database_now(),
    )
    snapshot = utility_service.open_broken_meter_case(accepted_command, actor=actor)
    assert snapshot.status is UtilityCalculationStatus.READY
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT app.utility_case_preview_snapshot(%s)->>'status',"
            "app.utility_case_preview_snapshot(%s)->'basis_period_ids'="
            "jsonb_build_array(%s::uuid)",
            (
                accepted_command.estimation_case_id,
                accepted_command.estimation_case_id,
                first_period_id,
            ),
        ).fetchone() == ("READY", True)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (later_period_id,),
        ).fetchone() == (1,)


def test_preview_source_kind_disambiguates_equal_period_and_case_ids(
    migrated_database_url: str,
) -> None:
    shared_source_id = uuid4()
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    finalize_actual(
        utility_service,
        actor,
        unit_id,
        readings[0],
        readings[1],
        period_id=shared_source_id,
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_command = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=shared_source_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Explicitly typed colliding preview identity",
        opened_at=database_now(),
    )
    utility_service.open_broken_meter_case(case_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_rates("
            "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
            "effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',0.25,DATE '2026-06-01',"
            "TIMESTAMPTZ '2026-05-31 00:00:00+07','TYPED-PREVIEW',%s)",
            (uuid4(), property_id, actor_id),
        )
        owner.commit()
    period_preview = utility_service.preview(
        shared_source_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    case_preview = utility_service.preview(
        shared_source_id,
        database_now(),
        source_kind=UtilityPreviewSourceKind.ESTIMATION_CASE,
        actor=actor,
    )
    assert period_preview.calculation_kind is UtilityCalculationKind.ACTUAL
    assert period_preview.consumption_period_id == shared_source_id
    assert case_preview.calculation_kind is UtilityCalculationKind.BROKEN_METER_ESTIMATE
    assert case_preview.consumption_period_id is None


def test_reading_correction_preserves_original_and_records_exact_impact(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 6, 1), "100"), (date(2026, 6, 11), "120")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,120,125,'Validated correction',%s,%s)",
            (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
        )
        owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert owner.execute(
            "SELECT period.consumption_quantity,"
            "app.utility_consumption_effective_quantity(period.id),"
            "impact.previous_consumption_quantity,impact.corrected_consumption_quantity,"
            "impact.billing_effect_kind FROM app.utility_consumption_periods AS period "
            "JOIN app.utility_reading_correction_impacts AS impact "
            "ON impact.consumption_period_id=period.id WHERE period.id=%s",
            (period_id,),
        ).fetchone() == (
            Decimal("20.000000"),
            Decimal("25.000000"),
            Decimal("20.000000"),
            Decimal("25.000000"),
            "PRE_ISSUANCE_INPUT",
        )


def test_case_boundary_uses_first_valid_replacement_reading(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    replacement_id, replacement_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
        first_valid_reading_date=date(2026, 3, 5),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT unmeasured_start_date,unmeasured_end_date FROM "
            "app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (date(2026, 2, 1), date(2026, 3, 4))
        assert owner.execute(
            "SELECT id FROM app.utility_readings WHERE meter_id=%s "
            "ORDER BY reading_date,id LIMIT 1",
            (replacement_id,),
        ).fetchone() == (replacement_reading_id,)


def test_same_day_failure_and_replacement_preserves_later_unmeasured_interval(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 1),
        first_valid_reading_date=date(2026, 2, 5),
    )

    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)

    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT unmeasured_start_date,unmeasured_end_date FROM "
            "app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (date(2026, 2, 1), date(2026, 2, 4))


def test_failure_date_reading_is_historical_and_estimation_starts_next_day(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 2, 1), "31")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    basis_period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.status is UtilityCalculationStatus.READY
    assert snapshot.basis_period_ids == (basis_period_id,)
    assert snapshot.period_start == date(2026, 2, 2)
    assert snapshot.period_end == date(2026, 2, 10)
    assert snapshot.consumption_quantity == Decimal("9.000000")
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT unmeasured_start_date,unmeasured_end_date,"
            "historical_actual_period_count_at_open FROM "
            "app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (date(2026, 2, 2), date(2026, 2, 10), 1)
        assert owner.execute(
            "SELECT start_date,end_date FROM app.utility_consumption_periods WHERE id=%s",
            (estimate_period_id,),
        ).fetchone() == (date(2026, 2, 2), date(2026, 2, 10))


def test_case_opening_requires_finalized_eligible_history(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    blocked_case_id = uuid4()
    blocked_key = uuid4()
    blocked_command = OpenBrokenMeterCaseCommand(
        idempotency_key=blocked_key,
        estimation_case_id=blocked_case_id,
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Confirmed physical Meter failure",
        opened_at=database_now(),
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(blocked_command, actor=actor)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.broken_meter_estimation_cases WHERE id=%s",
            (blocked_case_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_service_commands WHERE idempotency_key=%s",
            (blocked_key,),
        ).fetchone() == (0,)
    historical_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, readings[0], readings[1]
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.basis_kind is UtilityBasisKind.ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO
    assert snapshot.basis_period_ids == (historical_period_id,)
    assert snapshot.consumption_period_id == estimate_period_id
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT historical_actual_period_count_at_open FROM "
            "app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (1,)


def test_basis_reading_correction_propagates_to_dependent_estimate(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    basis_period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    initial = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert initial.consumption_quantity == Decimal("10.000000")
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,10,20,'Validated basis correction',%s,%s)",
            (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
        )
        owner.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert owner.execute(
            "SELECT consumption_period_id,previous_consumption_quantity,"
            "corrected_consumption_quantity FROM app.utility_reading_correction_impacts "
            "WHERE reading_correction_id=%s ORDER BY consumption_period_id",
            (correction_id,),
        ).fetchall() == sorted(
            [
                (basis_period_id, Decimal("10.000000"), Decimal("20.000000")),
                (estimate_period_id, Decimal("10.000000"), Decimal("20.000000")),
            ]
        )
        rate_id = uuid4()
        owner.execute(
            "INSERT INTO app.utility_rates("
            "id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,"
            "effective_date,notice_at,notice_evidence,actor_id) VALUES "
            "(%s,%s,'ELECTRICITY','KWH',0.25,DATE '2026-02-01',"
            "TIMESTAMPTZ '2026-01-31 00:00:00+07','CORRECTION-RATE',%s)",
            (rate_id, property_id, actor_id),
        )
        owner.commit()
    corrected = utility_service.preview(
        estimate_period_id,
        datetime(2026, 2, 12, tzinfo=UTC),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    assert corrected.consumption_quantity == Decimal("20.000000")
    assert corrected.amount_usd_cents == 500
    assert corrected.total_basis_consumption == Decimal("20.000000")
    assert corrected.total_basis_days == 10
    assert corrected.weighted_daily_average == Decimal("2.0000000000")
    assert corrected.basis_sources[0].consumption_period_id == basis_period_id


def test_basis_reading_correction_rejects_unrepresentable_dependent_estimate(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    basis_period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    estimate_period_id, estimate_command = finalize_estimate(utility_service, actor, case_id)
    initial = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert initial.weighted_daily_average == Decimal("1.0000000000")

    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(psycopg.errors.NumericValueOutOfRange):
            owner.execute(
                "INSERT INTO app.utility_reading_corrections("
                "id,reading_id,previous_value,corrected_value,reason,actor_id,"
                "authorization_reference) VALUES "
                "(%s,%s,10,99999999999999.999999,"
                "'Rejected precision-boundary correction',%s,%s)",
                (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
            )
        owner.rollback()
        assert owner.execute(
            "SELECT count(*) FROM app.utility_reading_corrections WHERE id=%s",
            (correction_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_reading_correction_impacts "
            "WHERE reading_correction_id=%s",
            (correction_id,),
        ).fetchone() == (0,)
        assert owner.execute(
            "SELECT app.utility_consumption_effective_quantity(%s),"
            "basis.total_basis_consumption,basis.weighted_daily_average "
            "FROM app.utility_estimate_effective_basis(%s) AS basis",
            (basis_period_id, estimate_command.estimate_id),
        ).fetchone() == (
            Decimal("10.000000"),
            Decimal("10.000000"),
            Decimal("1.0000000000"),
        )
    preserved = utility_service.preview(
        estimate_period_id,
        datetime(2026, 2, 12, tzinfo=UTC),
        source_kind=UtilityPreviewSourceKind.CONSUMPTION_PERIOD,
        actor=actor,
    )
    assert preserved.consumption_quantity == Decimal("10.000000")
    assert preserved.weighted_daily_average == Decimal("1.0000000000")


def test_period_wide_correction_chronology_rejects_backdated_boundary_effect(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    later_correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,10,20,'Later boundary correction',%s,%s)",
            (
                later_correction_id,
                readings[1],
                actor_id,
                f"AUTH-{later_correction_id}",
            ),
        )
        owner.commit()
    backdated_correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as backdated:
            owner.execute(
                "INSERT INTO app.utility_reading_corrections("
                "id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,"
                "authorization_reference) SELECT %s,%s,0,1,'Backdated boundary correction',"
                "reading.validated_at+(prior.occurred_at-reading.validated_at)/2,%s,%s "
                "FROM app.utility_readings AS reading "
                "JOIN app.utility_reading_corrections AS prior ON prior.id=%s "
                "WHERE reading.id=%s",
                (
                    backdated_correction_id,
                    readings[0],
                    actor_id,
                    f"AUTH-{backdated_correction_id}",
                    later_correction_id,
                    readings[0],
                ),
            )
        assert backdated.value.sqlstate == "23514"
        owner.rollback()
        assert owner.execute(
            "SELECT app.utility_consumption_effective_quantity(%s),count(*) "
            "FROM app.utility_reading_correction_impacts WHERE consumption_period_id=%s",
            (period_id, period_id),
        ).fetchone() == (Decimal("20.000000"), 1)


def test_correction_cannot_claim_to_predate_affected_actual_finalization(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    stale_occurred_at = database_now()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as stale_correction:
            owner.execute(
                "INSERT INTO app.utility_reading_corrections("
                "id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES "
                "(%s,%s,10,20,'Correction predating actual finalization',%s,%s,%s)",
                (
                    correction_id,
                    readings[1],
                    stale_occurred_at,
                    actor_id,
                    f"AUTH-{correction_id}",
                ),
            )
        assert stale_correction.value.sqlstate == "23514"
        owner.rollback()
        assert owner.execute(
            "SELECT app.utility_consumption_effective_quantity(%s),"
            "count(*) FROM app.utility_reading_correction_impacts "
            "WHERE consumption_period_id=%s",
            (period_id, period_id),
        ).fetchone() == (Decimal("10.000000"), 0)


def test_correction_cannot_claim_to_predate_dependent_estimate_authorization(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    basis_period_id, _ = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    stale_occurred_at = database_now()
    estimate_period_id, _ = finalize_estimate(utility_service, actor, case_id)
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as stale_correction:
            owner.execute(
                "INSERT INTO app.utility_reading_corrections("
                "id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,"
                "authorization_reference) VALUES "
                "(%s,%s,10,20,'Correction predating estimate authorization',%s,%s,%s)",
                (
                    correction_id,
                    readings[1],
                    stale_occurred_at,
                    actor_id,
                    f"AUTH-{correction_id}",
                ),
            )
        assert stale_correction.value.sqlstate == "23514"
        owner.rollback()
        assert owner.execute(
            "SELECT app.utility_consumption_effective_quantity(%s),"
            "app.utility_consumption_effective_quantity(%s),count(*) "
            "FROM app.utility_reading_correction_impacts "
            "WHERE consumption_period_id IN (%s,%s)",
            (
                basis_period_id,
                estimate_period_id,
                basis_period_id,
                estimate_period_id,
            ),
        ).fetchone() == (Decimal("10.000000"), Decimal("10.000000"), 0)


@pytest.mark.parametrize("pending_before_case", [True, False])
def test_case_freezes_late_failure_date_reading_validation(
    migrated_database_url: str,
    pending_before_case: bool,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    failure_reading_id = uuid4()
    if pending_before_case:
        with psycopg.connect(migrated_database_url) as owner:
            add_reading(
                owner,
                actor_id=actor_id,
                meter_id=failed_id,
                reading_date=date(2026, 2, 1),
                reading_value="31",
                validated=False,
                reading_id=failure_reading_id,
            )
            owner.commit()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    open_case(utility_service, actor, failed_id, replacement_id)
    with psycopg.connect(migrated_database_url) as owner:
        with pytest.raises(Error) as late_reading:
            if pending_before_case:
                owner.execute(
                    "UPDATE app.utility_readings SET validated_at=statement_timestamp(),"
                    "validated_by=%s,version=version+1,updated_at=statement_timestamp(),"
                    "updated_by=%s WHERE id=%s",
                    (actor_id, actor_id, failure_reading_id),
                )
            else:
                add_reading(
                    owner,
                    actor_id=actor_id,
                    meter_id=failed_id,
                    reading_date=date(2026, 2, 1),
                    reading_value="31",
                    reading_id=failure_reading_id,
                )
        assert late_reading.value.sqlstate == "55000"
        owner.rollback()
        assert owner.execute(
            "SELECT count(*) FROM app.utility_readings WHERE id=%s AND validated_at IS NOT NULL",
            (failure_reading_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("pending_before_case", [True, False])
def test_case_freezes_all_late_prefailure_reading_candidates(
    migrated_database_url: str,
    pending_before_case: bool,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"),),
    )
    late_reading_id = uuid4()
    if pending_before_case:
        with psycopg.connect(migrated_database_url) as owner:
            add_reading(
                owner,
                actor_id=actor_id,
                meter_id=failed_id,
                reading_date=date(2026, 1, 11),
                reading_value="10",
                validated=False,
                reading_id=late_reading_id,
            )
            owner.commit()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT historical_actual_period_count_at_open "
            "FROM app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (0,)
        with pytest.raises(Error) as late_reading:
            if pending_before_case:
                owner.execute(
                    "UPDATE app.utility_readings SET validated_at=statement_timestamp(),"
                    "validated_by=%s,version=version+1,updated_at=statement_timestamp(),"
                    "updated_by=%s WHERE id=%s",
                    (actor_id, actor_id, late_reading_id),
                )
            else:
                add_reading(
                    owner,
                    actor_id=actor_id,
                    meter_id=failed_id,
                    reading_date=date(2026, 1, 11),
                    reading_value="10",
                    reading_id=late_reading_id,
                )
        assert late_reading.value.sqlstate == "55000"
        owner.rollback()
        assert owner.execute(
            "SELECT count(*) FROM app.utility_readings WHERE id=%s AND validated_at IS NOT NULL",
            (late_reading_id,),
        ).fetchone() == (0,)


def test_case_freezes_late_history_from_an_older_same_utility_meter(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, oldest_meter_id, _ = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"),),
    )
    current_failed_meter_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=oldest_meter_id,
        failure_date=date(2026, 1, 15),
        replacement_date=date(2026, 1, 16),
    )
    replacement_meter_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=current_failed_meter_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    case_id, _ = open_case(
        utility_service,
        actor,
        current_failed_meter_id,
        replacement_meter_id,
    )
    late_reading_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT historical_actual_period_count_at_open "
            "FROM app.broken_meter_estimation_cases WHERE id=%s",
            (case_id,),
        ).fetchone() == (0,)
        with pytest.raises(Error) as late_reading:
            add_reading(
                owner,
                actor_id=actor_id,
                meter_id=oldest_meter_id,
                reading_date=date(2026, 1, 10),
                reading_value="10",
                reading_id=late_reading_id,
            )
        assert late_reading.value.sqlstate == "55000"
        owner.rollback()
        assert owner.execute(
            "SELECT count(*) FROM app.utility_readings WHERE id=%s",
            (late_reading_id,),
        ).fetchone() == (0,)


def test_case_opening_must_follow_failure_date_reading_validation(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_ESTIMATE_CAPABILITY)
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    stale_opened_at = database_now()
    with psycopg.connect(migrated_database_url) as owner:
        add_reading(
            owner,
            actor_id=actor_id,
            meter_id=failed_id,
            reading_date=date(2026, 2, 1),
            reading_value="31",
        )
        owner.commit()
    command_value = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=uuid4(),
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Opening timestamp predates the failure-date Reading",
        opened_at=stale_opened_at,
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(command_value, actor=actor)


def test_case_opening_must_follow_historical_period_finalization(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    stale_opened_at = database_now()
    finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    command_value = OpenBrokenMeterCaseCommand(
        idempotency_key=uuid4(),
        estimation_case_id=uuid4(),
        failed_meter_id=failed_id,
        replacement_meter_id=replacement_id,
        opened_reason="Opening timestamp predates historical period finalization",
        opened_at=stale_opened_at,
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.open_broken_meter_case(command_value, actor=actor)


def test_zero_history_requires_earliest_eligible_future_period_first(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, _ = committed_source(migrated_database_url, ())
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    replacement_id, first_reading_id = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 3, 1),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    with psycopg.connect(migrated_database_url) as owner:
        middle_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 3, 11),
            reading_value="20",
        )
        last_reading_id = add_reading(
            owner,
            actor_id=actor_id,
            meter_id=replacement_id,
            reading_date=date(2026, 3, 21),
            reading_value="30",
        )
        owner.commit()
    with pytest.raises(UtilityInvalidError):
        finalize_actual(utility_service, actor, unit_id, middle_reading_id, last_reading_id)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods "
            "WHERE unit_id=%s AND calculation_kind='ACTUAL'",
            (unit_id,),
        ).fetchone() == (0,)
    selected_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, first_reading_id, middle_reading_id
    )
    later_period_id, _ = finalize_actual(
        utility_service, actor, unit_id, middle_reading_id, last_reading_id
    )
    _, estimate_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(estimate_command, actor=actor)
    assert snapshot.basis_period_ids == (selected_period_id,)
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT count(*),count(*) FILTER (WHERE id=%s) "
            "FROM app.utility_consumption_periods "
            "WHERE unit_id=%s AND calculation_kind='ACTUAL'",
            (selected_period_id, unit_id),
        ).fetchone() == (2, 1)
        assert owner.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (later_period_id,),
        ).fetchone() == (1,)


def test_actual_finalization_must_follow_reading_corrections(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, _, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    source_cutoff = database_now()
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,10,12,'Source correction',%s,%s)",
            (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
        )
        owner.commit()
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(actor_id, property_id, UTILITY_CALCULATE_CAPABILITY)
    stale_command = FinalizeActualConsumptionCommand(
        idempotency_key=uuid4(),
        consumption_period_id=uuid4(),
        unit_id=unit_id,
        utility_type="ELECTRICITY",
        start_reading_id=readings[0],
        end_reading_id=readings[1],
        finalized_at=source_cutoff,
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.finalize_actual(stale_command, actor=actor)
    _, fresh_command = finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    fresh_snapshot = utility_service.finalize_actual(fresh_command, actor=actor)
    assert fresh_snapshot.consumption_quantity == Decimal("12.000000")


def test_estimate_authorization_must_follow_basis_corrections(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id, failed_id, readings = committed_source(
        migrated_database_url,
        ((date(2026, 1, 1), "0"), (date(2026, 1, 11), "10")),
    )
    utility_service = service(property_id, actor_id)
    actor = authorized_actor(
        actor_id, property_id, UTILITY_CALCULATE_CAPABILITY, UTILITY_ESTIMATE_CAPABILITY
    )
    finalize_actual(utility_service, actor, unit_id, readings[0], readings[1])
    replacement_id, _ = replace_failed_meter(
        migrated_database_url,
        actor_id=actor_id,
        unit_id=unit_id,
        failed_meter_id=failed_id,
        failure_date=date(2026, 2, 1),
        replacement_date=date(2026, 2, 11),
    )
    case_id, _ = open_case(utility_service, actor, failed_id, replacement_id)
    source_cutoff = database_now()
    correction_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,10,20,'Basis correction',%s,%s)",
            (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
        )
        owner.commit()
    stale_command = FinalizeBrokenMeterEstimateCommand(
        idempotency_key=uuid4(),
        estimation_case_id=case_id,
        estimate_id=uuid4(),
        consumption_period_id=uuid4(),
        authorization_reason="Authorization predating corrected basis",
        authorized_at=source_cutoff,
    )
    with pytest.raises(UtilityInvalidError):
        utility_service.finalize_broken_meter_estimate(stale_command, actor=actor)
    _, fresh_command = finalize_estimate(utility_service, actor, case_id)
    snapshot = utility_service.finalize_broken_meter_estimate(fresh_command, actor=actor)
    assert snapshot.consumption_quantity == Decimal("20.000000")
