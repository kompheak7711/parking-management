"""Real PostgreSQL coverage for V1-041 Utility persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from time import monotonic, sleep
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import Connection, Error
from psycopg.conninfo import make_conninfo

from test_lease_migration import setup_sources


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


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def financial_database_url() -> str:
    value = os.environ.get("FINANCIAL_DATABASE_URL")
    if value is None:
        pytest.skip("FINANCIAL_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def admin_database_url() -> str:
    value = os.environ.get("TEST_ADMIN_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_ADMIN_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def assert_sessions_wait_for_lock(*application_names: str) -> None:
    deadline = monotonic() + 5
    with psycopg.connect(admin_database_url(), autocommit=True) as observer:
        while monotonic() < deadline:
            waiting = observer.execute(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE application_name=ANY(%s::text[]) AND state='active' "
                "AND wait_event_type='Lock'",
                (list(application_names),),
            ).fetchone()
            if waiting == (len(application_names),):
                return
            sleep(0.02)
    pytest.fail(f"Sessions did not reach the expected lock wait: {application_names}")


def utility_source(
    connection: Connection[tuple[object, ...]],
) -> tuple[UUID, UUID, UUID]:
    actor_id, property_id, unit_id, _, _ = setup_sources(connection)
    return actor_id, property_id, unit_id


def add_meter(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    unit_id: UUID,
    utility_type: str = "ELECTRICITY",
    measurement_unit_code: str = "KWH",
    installed_date: date = date(2026, 1, 1),
    meter_id: UUID | None = None,
    serial_number: str | None = None,
) -> UUID:
    stored_id = uuid4() if meter_id is None else meter_id
    connection.execute(
        """
        INSERT INTO app.utility_meters(
            id,unit_id,serial_number,utility_type,measurement_unit_code,
            installed_date,created_by,updated_by
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            stored_id,
            unit_id,
            serial_number or f"SERIAL-{stored_id}",
            utility_type,
            measurement_unit_code,
            installed_date,
            actor_id,
            actor_id,
        ),
    )
    return stored_id


def add_reading(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    meter_id: UUID,
    reading_date: date,
    reading_value: str,
    validated: bool = True,
    reading_id: UUID | None = None,
) -> UUID:
    stored_id = uuid4() if reading_id is None else reading_id
    connection.execute(
        """
        INSERT INTO app.utility_readings(
            id,meter_id,reading_date,reading_value,validated_at,validated_by,
            created_by,updated_by
        ) VALUES (
            %s,%s,%s,%s,
            CASE WHEN %s THEN statement_timestamp() END,
            CASE WHEN %s THEN %s END,%s,%s
        )
        """,
        (
            stored_id,
            meter_id,
            reading_date,
            reading_value,
            validated,
            validated,
            actor_id,
            actor_id,
            actor_id,
        ),
    )
    return stored_id


def add_rate(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: UUID,
    property_id: UUID,
    utility_type: str,
    measurement_unit_code: str,
    effective_date: date = date(2026, 2, 1),
    rate_id: UUID | None = None,
) -> UUID:
    stored_id = uuid4() if rate_id is None else rate_id
    connection.execute(
        """
        INSERT INTO app.utility_rates(
            id,property_id,utility_type,measurement_unit_code,rate_usd_per_unit,
            effective_date,notice_at,notice_evidence,actor_id
        ) VALUES (%s,%s,%s,%s,0.25,%s,
                  TIMESTAMPTZ '2026-01-01 00:00:00+07','OWNER-NOTICE',%s)
        """,
        (stored_id, property_id, utility_type, measurement_unit_code, effective_date, actor_id),
    )
    return stored_id


def test_v1_041_remains_forward_only_after_successor() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == "20270407_257"
    source = (
        Path(__file__).parents[1] / "migrations/versions/20260828_31_utility_meter_persistence.py"
    ).read_text()
    assert 'raise RuntimeError("V1-041 Utility persistence is forward-only")' in source


def test_meter_identity_active_uniqueness_and_rate_unit_consistency(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, property_id, unit_id = utility_source(connection)
    add_rate(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        utility_type="ELECTRICITY",
        measurement_unit_code="KWH",
    )
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        utility_type="WATER",
        measurement_unit_code="M3",
    )

    with pytest.raises(Error) as duplicate_active:
        add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    assert duplicate_active.value.sqlstate == "23505"
    connection.rollback()

    actor_id, property_id, unit_id = utility_source(connection)
    add_rate(
        connection,
        actor_id=actor_id,
        property_id=property_id,
        utility_type="ELECTRICITY",
        measurement_unit_code="KWH",
    )
    with pytest.raises(Error) as mismatched_meter:
        add_meter(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            measurement_unit_code="MWH",
        )
    assert mismatched_meter.value.sqlstate == "23514"
    connection.rollback()

    actor_id, property_id, unit_id = utility_source(connection)
    add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    with pytest.raises(Error) as mismatched_rate:
        add_rate(
            connection,
            actor_id=actor_id,
            property_id=property_id,
            utility_type="ELECTRICITY",
            measurement_unit_code="MWH",
        )
    assert mismatched_rate.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _, unit_id = utility_source(connection)
    with pytest.raises(Error) as unsupported_type:
        add_meter(
            connection,
            actor_id=actor_id,
            unit_id=unit_id,
            utility_type="GAS",
        )
    assert unsupported_type.value.sqlstate == "23514"

    connection.rollback()
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 2),
        reading_value="1",
    )
    with pytest.raises(Error) as changed_unit:
        connection.execute(
            "UPDATE app.utility_meters SET measurement_unit_code='MWH',version=version+1,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (actor_id, meter_id),
        )
    assert changed_unit.value.sqlstate == "55000"


def test_replacement_preserves_meter_and_reading_boundaries(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    old_reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=failed_id,
        reading_date=date(2026, 1, 31),
        reading_value="125",
    )
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-02-01',"
        "deactivated_date=DATE '2026-02-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, failed_id),
    )
    replacement_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        installed_date=date(2026, 2, 1),
    )
    event_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_meter_replacements("
        "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
        "VALUES (%s,%s,%s,DATE '2026-02-01','Confirmed broken Meter',%s)",
        (event_id, failed_id, replacement_id, actor_id),
    )
    new_reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=replacement_id,
        reading_date=date(2026, 2, 1),
        reading_value="3",
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    stored = connection.execute(
        "SELECT failed_meter_id,replacement_meter_id FROM app.utility_meter_replacements "
        "WHERE id=%s",
        (event_id,),
    ).fetchone()
    assert stored == (failed_id, replacement_id)
    assert connection.execute(
        "SELECT meter_id FROM app.utility_readings WHERE id=%s", (old_reading_id,)
    ).fetchone() == (failed_id,)
    assert connection.execute(
        "SELECT meter_id FROM app.utility_readings WHERE id=%s", (new_reading_id,)
    ).fetchone() == (replacement_id,)

    with pytest.raises(Error) as late_old_reading:
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=failed_id,
            reading_date=date(2026, 2, 2),
            reading_value="130",
        )
    assert late_old_reading.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-02-01',"
        "deactivated_date=DATE '2026-02-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, failed_id),
    )
    with pytest.raises(Error) as missing_event:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert missing_event.value.sqlstate == "23514"

    connection.rollback()
    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    add_reading(
        connection,
        actor_id=actor_id,
        meter_id=failed_id,
        reading_date=date(2026, 1, 20),
        reading_value="125",
    )
    with pytest.raises(Error, match="failure date conflicts") as backdated_failure:
        connection.execute(
            "UPDATE app.utility_meters SET failure_date=DATE '2026-01-10',"
            "deactivated_date=DATE '2026-02-01',version=version+1,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (actor_id, failed_id),
        )
    assert backdated_failure.value.sqlstate == "23514"

    connection.rollback()
    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-01-10',"
        "deactivated_date=DATE '2026-02-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, failed_id),
    )
    replacement_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        installed_date=date(2026, 2, 1),
    )
    connection.execute(
        "INSERT INTO app.utility_meter_replacements("
        "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
        "VALUES (%s,%s,%s,DATE '2026-02-01','Replacement after failure gap',%s)",
        (uuid4(), failed_id, replacement_id, actor_id),
    )
    connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    add_reading(
        connection,
        actor_id=actor_id,
        meter_id=failed_id,
        reading_date=date(2026, 1, 10),
        reading_value="125",
    )
    with pytest.raises(Error) as after_failure:
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=failed_id,
            reading_date=date(2026, 1, 11),
            reading_value="126",
        )
    assert after_failure.value.sqlstate == "23514"


def test_validated_readings_are_chronological_nonnegative_and_immutable(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    first_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 10),
        reading_value="10.125000",
    )
    pending_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 2, 10),
        reading_value="20.250000",
        validated=False,
    )
    connection.execute(
        "UPDATE app.utility_readings SET validated_at=statement_timestamp(),validated_by=%s,"
        "version=version+1,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, actor_id, pending_id),
    )
    assert connection.execute(
        "SELECT validated_by,version FROM app.utility_readings WHERE id=%s", (pending_id,)
    ).fetchone() == (actor_id, 2)

    with pytest.raises(Error) as decreasing:
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 3, 10),
            reading_value="19",
        )
    assert decreasing.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    first_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 10),
        reading_value="10",
    )
    with pytest.raises(Error) as duplicate_date:
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 1, 10),
            reading_value="11",
        )
    assert duplicate_date.value.sqlstate == "23514"
    connection.rollback()

    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    first_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 10),
        reading_value="10",
    )
    with pytest.raises(Error) as changed_identity:
        connection.execute(
            "UPDATE app.utility_readings SET reading_value=11,version=version+1,"
            "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
            (actor_id, first_id),
        )
    assert changed_identity.value.sqlstate == "55000"


def test_replacement_history_rejects_a_reciprocal_cycle(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    first_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-01-01',"
        "deactivated_date=DATE '2026-01-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, first_id),
    )
    second_id = add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        installed_date=date(2026, 1, 1),
    )
    connection.execute(
        "INSERT INTO app.utility_meter_replacements("
        "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
        "VALUES (%s,%s,%s,DATE '2026-01-01','First link',%s)",
        (uuid4(), first_id, second_id, actor_id),
    )
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-01-01',"
        "deactivated_date=DATE '2026-01-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, second_id),
    )
    connection.execute(
        "INSERT INTO app.utility_meter_replacements("
        "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
        "VALUES (%s,%s,%s,DATE '2026-01-01','Reciprocal link',%s)",
        (uuid4(), second_id, first_id, actor_id),
    )
    with pytest.raises(Error, match="acyclic") as cycle:
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert cycle.value.sqlstate == "23514"


def test_corrections_preserve_source_chain_and_adjacent_sequence(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    readings = [
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=reading_date,
            reading_value=value,
        )
        for reading_date, value in (
            (date(2026, 1, 1), "10"),
            (date(2026, 2, 1), "20"),
            (date(2026, 3, 1), "30"),
        )
    ]
    correction_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_reading_corrections("
        "id,reading_id,previous_value,corrected_value,reason,actor_id,"
        "authorization_reference) VALUES (%s,%s,20,25,'Correct transcription',%s,%s)",
        (correction_id, readings[1], actor_id, f"AUTH-{correction_id}"),
    )
    assert connection.execute(
        "SELECT reading_value FROM app.utility_readings WHERE id=%s", (readings[1],)
    ).fetchone() == (20,)
    assert connection.execute(
        "SELECT app.utility_reading_effective_value(%s)", (readings[1],)
    ).fetchone() == (25,)

    with pytest.raises(Error) as stale:
        connection.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,20,26,'Stale retry',%s,%s)",
            (uuid4(), readings[1], actor_id, f"AUTH-{uuid4()}"),
        )
    assert stale.value.sqlstate == "40001"
    connection.rollback()

    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    readings = [
        add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=reading_date,
            reading_value=value,
        )
        for reading_date, value in (
            (date(2026, 1, 1), "10"),
            (date(2026, 2, 1), "20"),
            (date(2026, 3, 1), "30"),
        )
    ]
    with pytest.raises(Error) as crosses_next:
        connection.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,20,31,'Invalid correction',%s,%s)",
            (uuid4(), readings[1], actor_id, f"AUTH-{uuid4()}"),
        )
    assert crosses_next.value.sqlstate == "23514"


def test_correction_order_is_total_when_database_timestamps_are_equal(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 1),
        reading_value="10",
    )
    validation = connection.execute(
        "SELECT validated_at FROM app.utility_readings WHERE id=%s", (reading_id,)
    ).fetchone()
    assert validation is not None
    occurred_at = validation[0]
    first_id = UUID("00000000-0000-0000-0000-000000000002")
    next_id = UUID("00000000-0000-0000-0000-000000000003")
    stale_order_id = UUID("00000000-0000-0000-0000-000000000001")
    for correction_id, previous_value, corrected_value in (
        (first_id, 10, 11),
        (next_id, 11, 12),
    ):
        connection.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,%s,%s,'Ordered correction',%s,%s,%s)",
            (
                correction_id,
                reading_id,
                previous_value,
                corrected_value,
                occurred_at,
                actor_id,
                f"AUTH-{correction_id}",
            ),
        )
    assert connection.execute(
        "SELECT app.utility_reading_effective_value(%s)", (reading_id,)
    ).fetchone() == (12,)

    connection.execute("SAVEPOINT before_stale_order")
    with pytest.raises(Error) as stale_order:
        connection.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,12,13,'Stale ordering key',%s,%s,%s)",
            (
                stale_order_id,
                reading_id,
                occurred_at,
                actor_id,
                f"AUTH-{stale_order_id}",
            ),
        )
    assert stale_order.value.sqlstate == "23514"
    connection.execute("ROLLBACK TO SAVEPOINT before_stale_order")
    assert connection.execute(
        "SELECT count(*),app.utility_reading_effective_value(%s) "
        "FROM app.utility_reading_corrections WHERE reading_id=%s",
        (reading_id, reading_id),
    ).fetchone() == (2, 12)


def test_utility_history_rejects_update_delete_and_truncate(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 1),
        reading_value="10",
    )
    correction_id = uuid4()
    connection.execute(
        "INSERT INTO app.utility_reading_corrections("
        "id,reading_id,previous_value,corrected_value,reason,actor_id,"
        "authorization_reference) VALUES (%s,%s,10,11,'Correction',%s,%s)",
        (correction_id, reading_id, actor_id, f"AUTH-{correction_id}"),
    )
    for operation in (
        "meter delete",
        "reading delete",
        "correction update",
        "reading truncate",
    ):
        parameters: tuple[object, ...]
        if operation == "meter delete":
            statement, parameters = (
                "DELETE FROM app.utility_meters WHERE id=%s",
                (meter_id,),
            )
        elif operation == "reading delete":
            statement, parameters = (
                "DELETE FROM app.utility_readings WHERE id=%s",
                (reading_id,),
            )
        elif operation == "correction update":
            statement, parameters = (
                "UPDATE app.utility_reading_corrections SET corrected_value=12 WHERE id=%s",
                (correction_id,),
            )
        else:
            statement, parameters = (
                "TRUNCATE app.utility_reading_corrections,app.utility_readings",
                (),
            )
        try:
            connection.execute(statement, parameters)
        except Error as rejected:
            expected_state = "0A000" if operation == "reading truncate" else "55000"
            assert rejected.sqlstate == expected_state, operation
            if expected_state == "55000":
                assert "append-preserved" in str(rejected), operation
        else:
            pytest.fail(f"Utility history mutation unexpectedly succeeded: {operation}")
        connection.rollback()
        actor_id, _, unit_id = utility_source(connection)
        meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
        reading_id = add_reading(
            connection,
            actor_id=actor_id,
            meter_id=meter_id,
            reading_date=date(2026, 1, 1),
            reading_value="10",
        )
        correction_id = uuid4()
        connection.execute(
            "INSERT INTO app.utility_reading_corrections("
            "id,reading_id,previous_value,corrected_value,reason,actor_id,"
            "authorization_reference) VALUES (%s,%s,10,11,'Correction',%s,%s)",
            (correction_id, reading_id, actor_id, f"AUTH-{correction_id}"),
        )


def test_runtime_and_financial_roles_are_read_only(
    connection: Connection[tuple[object, ...]], migrated_database_url: str
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    connection.commit()
    for database_url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(database_url) as scoped:
            privileges = scoped.execute(
                """
                SELECT
                    has_table_privilege(current_user,'app.utility_meters','SELECT'),
                    has_table_privilege(current_user,'app.utility_meters','INSERT'),
                    has_table_privilege(current_user,'app.utility_readings','UPDATE'),
                    has_table_privilege(current_user,'app.utility_reading_corrections','DELETE')
                """
            ).fetchone()
            assert privileges == (True, False, False, False)
            assert scoped.execute(
                "SELECT id FROM app.utility_meters WHERE id=%s", (meter_id,)
            ).fetchone() == (meter_id,)
    del migrated_database_url


def test_concurrent_active_meter_creation_allows_exactly_one(
    connection: Connection[tuple[object, ...]], migrated_database_url: str
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    connection.commit()
    application_names = (
        f"v1041-meter-a-{uuid4().hex}",
        f"v1041-meter-b-{uuid4().hex}",
    )

    def create(serial: str, application_name: str) -> str:
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_name)
            ) as concurrent:
                add_meter(
                    concurrent,
                    actor_id=actor_id,
                    unit_id=unit_id,
                    serial_number=serial,
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute("SELECT app.lock_utility_unit_type(%s,'ELECTRICITY')", (unit_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(create, "CONCURRENT-A", application_names[0]),
                pool.submit(create, "CONCURRENT-B", application_names[1]),
            )
            assert_sessions_wait_for_lock(*application_names)
            blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["23505", "success"]
    assert connection.execute(
        "SELECT count(*) FROM app.utility_meters "
        "WHERE unit_id=%s AND utility_type='ELECTRICITY' AND deactivated_date IS NULL",
        (unit_id,),
    ).fetchone() == (1,)


def test_concurrent_corrections_use_exact_current_evidence(
    connection: Connection[tuple[object, ...]], migrated_database_url: str
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    meter_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    reading_id = add_reading(
        connection,
        actor_id=actor_id,
        meter_id=meter_id,
        reading_date=date(2026, 1, 1),
        reading_value="20",
    )
    connection.commit()
    application_names = (
        f"v1041-correction-a-{uuid4().hex}",
        f"v1041-correction-b-{uuid4().hex}",
    )

    def correct(value: int, application_name: str) -> str:
        correction_id = uuid4()
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_name)
            ) as concurrent:
                concurrent.execute(
                    "INSERT INTO app.utility_reading_corrections("
                    "id,reading_id,previous_value,corrected_value,reason,actor_id,"
                    "authorization_reference) VALUES (%s,%s,20,%s,%s,%s,%s)",
                    (
                        correction_id,
                        reading_id,
                        value,
                        f"Concurrent {value}",
                        actor_id,
                        f"AUTH-{correction_id}",
                    ),
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute("SELECT app.lock_utility_meter_sequence(%s)", (meter_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(correct, 21, application_names[0]),
                pool.submit(correct, 22, application_names[1]),
            )
            assert_sessions_wait_for_lock(*application_names)
            blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["40001", "success"]
    assert connection.execute(
        "SELECT count(*) FROM app.utility_reading_corrections WHERE reading_id=%s",
        (reading_id,),
    ).fetchone() == (1,)


def test_meter_and_rate_unit_writes_serialize_at_the_property_boundary(
    connection: Connection[tuple[object, ...]], migrated_database_url: str
) -> None:
    actor_id, property_id, unit_id = utility_source(connection)
    connection.commit()
    application_names = (
        f"v1041-meter-source-{uuid4().hex}",
        f"v1041-rate-source-{uuid4().hex}",
    )
    meter_id = uuid4()
    rate_id = uuid4()

    def create_meter() -> str:
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_names[0])
            ) as concurrent:
                add_meter(
                    concurrent,
                    actor_id=actor_id,
                    unit_id=unit_id,
                    meter_id=meter_id,
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    def create_rate() -> str:
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_names[1])
            ) as concurrent:
                add_rate(
                    concurrent,
                    actor_id=actor_id,
                    property_id=property_id,
                    utility_type="ELECTRICITY",
                    measurement_unit_code="MWH",
                    rate_id=rate_id,
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute("SELECT app.lock_utility_property_type(%s,'ELECTRICITY')", (property_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(create_meter), pool.submit(create_rate))
            assert_sessions_wait_for_lock(*application_names)
            blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["23514", "success"]
    stored = connection.execute(
        "SELECT (SELECT count(*) FROM app.utility_meters WHERE id=%s),"
        "(SELECT count(*) FROM app.utility_rates WHERE id=%s)",
        (meter_id, rate_id),
    ).fetchone()
    assert stored in {(0, 1), (1, 0)}


def test_reading_and_replacement_race_cannot_cross_the_failure_boundary(
    connection: Connection[tuple[object, ...]], migrated_database_url: str
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    failed_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id)
    connection.commit()
    application_names = (
        f"v1041-reading-race-{uuid4().hex}",
        f"v1041-replacement-race-{uuid4().hex}",
    )

    def record_late_reading() -> str:
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_names[0])
            ) as concurrent:
                add_reading(
                    concurrent,
                    actor_id=actor_id,
                    meter_id=failed_id,
                    reading_date=date(2026, 1, 20),
                    reading_value="10",
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    def replace_meter() -> str:
        try:
            with psycopg.connect(
                make_conninfo(migrated_database_url, application_name=application_names[1])
            ) as concurrent:
                concurrent.execute(
                    "UPDATE app.utility_meters SET failure_date=DATE '2026-01-10',"
                    "deactivated_date=DATE '2026-02-01',version=version+1,"
                    "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
                    (actor_id, failed_id),
                )
                replacement_id = add_meter(
                    concurrent,
                    actor_id=actor_id,
                    unit_id=unit_id,
                    installed_date=date(2026, 2, 1),
                )
                concurrent.execute(
                    "INSERT INTO app.utility_meter_replacements("
                    "id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id) "
                    "VALUES (%s,%s,%s,DATE '2026-02-01','Concurrent replacement',%s)",
                    (uuid4(), failed_id, replacement_id, actor_id),
                )
            return "success"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute("SELECT app.lock_utility_meter_sequence(%s)", (failed_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(record_late_reading), pool.submit(replace_meter))
            assert_sessions_wait_for_lock(*application_names)
            blocker.commit()
            outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["23514", "success"]
    stored = connection.execute(
        "SELECT (SELECT count(*) FROM app.utility_readings "
        "WHERE meter_id=%s AND reading_date=DATE '2026-01-20'),"
        "(SELECT count(*) FROM app.utility_meter_replacements WHERE failed_meter_id=%s)",
        (failed_id, failed_id),
    ).fetchone()
    assert stored in {(0, 1), (1, 0)}
