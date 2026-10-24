"""Real PostgreSQL coverage for Meter serial numbers unique across the Property.

DL-071 answer 12, DB-UTIL-001, TCD-DB-004 (V1-059 part B, migration `20270205_193`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, Error

from test_utility_meter_migration import (
    add_meter,
    assert_sessions_wait_for_lock,
    connection,
    migrated_database_url,
    utility_source,
)

__all__ = ["connection", "migrated_database_url"]


def test_a_serial_is_unique_across_utility_types_and_ignores_case_spaces_and_dashes(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    add_meter(connection, actor_id=actor_id, unit_id=unit_id, serial_number="EL-U101")
    for same in ("el-u101", "EL U101", "ELU101"):
        with pytest.raises(Error) as refused:
            with connection.transaction():
                add_meter(
                    connection,
                    actor_id=actor_id,
                    unit_id=unit_id,
                    utility_type="WATER",
                    measurement_unit_code="M3",
                    serial_number=same,
                )
        assert refused.value.sqlstate == "23505"
        assert "Meter serial number is already used" in str(refused.value)
    add_meter(
        connection,
        actor_id=actor_id,
        unit_id=unit_id,
        utility_type="WATER",
        measurement_unit_code="M3",
        serial_number="WA-U101",
    )


def test_a_replaced_meter_keeps_its_serial_and_another_unit_cannot_use_it(
    connection: Connection[tuple[object, ...]],
) -> None:
    actor_id, _, unit_id = utility_source(connection)
    old_id = add_meter(connection, actor_id=actor_id, unit_id=unit_id, serial_number="SN-7788")
    connection.execute(
        "UPDATE app.utility_meters SET failure_date=DATE '2026-02-01',"
        "deactivated_date=DATE '2026-02-01',version=version+1,"
        "updated_at=statement_timestamp(),updated_by=%s WHERE id=%s",
        (actor_id, old_id),
    )
    with pytest.raises(Error) as refused:
        with connection.transaction():
            add_meter(
                connection,
                actor_id=actor_id,
                unit_id=unit_id,
                installed_date=date(2026, 2, 1),
                serial_number="SN-7788",
            )
    assert refused.value.sqlstate == "23505"

    other_actor_id, _, other_unit_id = utility_source(connection)
    with pytest.raises(Error) as other_unit:
        with connection.transaction():
            add_meter(
                connection,
                actor_id=other_actor_id,
                unit_id=other_unit_id,
                serial_number="SN-7788",
            )
    assert other_unit.value.sqlstate == "23505"


def test_two_meters_with_one_serial_saved_at_once_cannot_both_commit(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        actor_id, property_id, unit_id = utility_source(setup)
        setup.commit()
    serial = f"RACE-{uuid4().hex[:8]}"
    names = (f"serial-race-a-{uuid4().hex[:8]}", f"serial-race-b-{uuid4().hex[:8]}")

    def save(name: str, utility_type: str, code: str) -> str:
        try:
            with psycopg.connect(migrated_database_url, application_name=name) as session:
                add_meter(
                    session,
                    actor_id=actor_id,
                    unit_id=unit_id,
                    utility_type=utility_type,
                    measurement_unit_code=code,
                    serial_number=serial,
                )
            return "saved"
        except Error as error:
            return str(error.sqlstate)

    with psycopg.connect(migrated_database_url) as blocker:
        blocker.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(%s,0))",
            (f"utility-meter-serial:{property_id}",),
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save, names[0], "ELECTRICITY", "KWH")
            second = pool.submit(save, names[1], "WATER", "M3")
            assert_sessions_wait_for_lock(*names)
            blocker.rollback()
            outcomes = sorted((first.result(), second.result()))
    assert outcomes == ["23505", "saved"]
