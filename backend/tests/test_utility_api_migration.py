"""Disposable PostgreSQL coverage for the V1-043 Utility API boundary."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal, getcontext, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.utility_api import (
    PostgresUtilityResourceFlow,
    ReadingRecord,
    UtilityResourceIdempotencyConflict,
    UtilityResourceInvalid,
    UtilityResourceVersionConflict,
)
from test_lease_migration import setup_sources


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    value = os.environ.get("MIGRATION_DATABASE_URL")
    if value is None:
        pytest.skip("MIGRATION_DATABASE_URL is required")
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url() -> str:
    value = os.environ.get("APP_DATABASE_URL")
    if value is None:
        pytest.skip("APP_DATABASE_URL is required")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


class _ConnectionProbe:
    def __init__(self) -> None:
        self.parameters: list[tuple[object, ...]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> _ConnectionProbe:
        del query
        self.parameters.append(parameters)
        return self

    def fetchone(self) -> tuple[UUID]:
        return (uuid4(),)


def _direct_reading_payload(reading_value: object) -> dict[str, object]:
    return {
        "expected_meter_version": 1,
        "reading_date": date(2026, 1, 31),
        "reading_value": reading_value,
        "source_kind": "MANUAL",
        "source_evidence": "Boundary photograph",
    }


def test_postgres_reading_boundary_canonicalizes_decimal_and_numeric_string() -> None:
    connection = _ConnectionProbe()
    with localcontext() as ambient_context:
        ambient_context.prec = 19
        original_context = repr(ambient_context)
        for value in (
            Decimal("20"),
            "20.000000",
            Decimal("99999999999999.999999"),
            "99999999999999.999999",
        ):
            PostgresUtilityResourceFlow._record_on_connection(
                cast(psycopg.Connection[object], connection),
                uuid4(),
                _direct_reading_payload(value),
                uuid4(),
                uuid4(),
                "a" * 64,
            )
        assert repr(getcontext()) == original_context

    assert [parameters[4] for parameters in connection.parameters] == [
        "20.000000",
        "20.000000",
        "99999999999999.999999",
        "99999999999999.999999",
    ]


@pytest.mark.parametrize(
    "reading_value",
    [
        True,
        20,
        "not-a-number",
        Decimal("NaN"),
        "Infinity",
        "-0.000001",
        "123456789012345.123456",
        "100000000000000.000000",
        "1.0000001",
        "2E+1",
    ],
)
def test_postgres_reading_boundary_rejects_invalid_values_before_execute(
    reading_value: object,
) -> None:
    connection = _ConnectionProbe()
    with pytest.raises(UtilityResourceInvalid, match="Utility reading value is invalid"):
        PostgresUtilityResourceFlow._record_on_connection(
            cast(psycopg.Connection[object], connection),
            uuid4(),
            _direct_reading_payload(reading_value),
            uuid4(),
            uuid4(),
            "a" * 64,
        )
    assert connection.parameters == []


def committed_sources(database_url: str) -> tuple[UUID, UUID, UUID]:
    with psycopg.connect(database_url) as owner:
        actor_id, property_id, unit_id, _, _ = setup_sources(owner)
        owner.commit()
    return actor_id, property_id, unit_id


def install_payload() -> dict[str, object]:
    return {
        "utility_type": "ELECTRICITY",
        "serial_number": f"ELEC-API-{uuid4().hex[:12]}",
        "measurement_unit_code": "KWH",
        "description": "Main Electricity Meter",
        "installed_date": date(2026, 1, 1),
        "memo": "Owner installation record",
        "initial_reading": {
            "reading_date": date(2026, 1, 1),
            "reading_value": "10.000000",
            "source_evidence": "Installation photograph 1",
        },
    }


def replacement_payload(
    boundary_reading_id: UUID,
    *,
    expected_version: int,
    failure_date: date = date(2026, 1, 31),
    replacement_date: date = date(2026, 2, 1),
) -> dict[str, object]:
    return {
        "expected_version": expected_version,
        "failed_boundary_reading_id": boundary_reading_id,
        "failure_date": failure_date,
        "replacement_date": replacement_date,
        "reason": "Confirmed mechanical failure",
        "replacement_meter": {
            "serial_number": f"ELEC-API-{uuid4().hex[:12]}",
            "description": None,
            "memo": "Replacement work order",
        },
        "replacement_initial_reading": {
            "reading_date": replacement_date,
            "reading_value": "0.000000",
            "source_evidence": "Replacement photograph",
        },
    }


def test_v1_043_is_forward_only_head_and_runtime_has_only_command_execute(
    migrated_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == "20270403_253"
    source = (
        Path(__file__).parents[1] / "migrations/versions/20260829_34_v1_043_utility_api.py"
    ).read_text()
    assert 'raise RuntimeError("V1-043 Utility API migration is forward-only")' in source
    with pytest.raises(RuntimeError, match="forward-only"):
        command.downgrade(config, "20260829_33")
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "20270403_253",
        )
        for table in (
            "utility_meters",
            "utility_readings",
            "utility_api_commands",
            "utility_api_batch_items",
        ):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert owner.execute(
                    "SELECT has_table_privilege('prm_runtime',%s,%s)",
                    (f"app.{table}", privilege),
                ).fetchone() == (False,)
        assert owner.execute(
            "SELECT has_function_privilege('prm_runtime',"
            "'app.record_utility_reading_api(uuid,uuid,integer,date,numeric,text,text,uuid,uuid,text)',"
            "'EXECUTE')"
        ).fetchone() == (True,)
        assert owner.execute(
            "SELECT has_function_privilege('prm_runtime',"
            "'app.record_utility_reading_batch_api(uuid,uuid,jsonb,uuid,uuid,text)',"
            "'EXECUTE')"
        ).fetchone() == (True,)


def test_runtime_install_reading_replay_and_version_conflict(
    migrated_database_url: str,
) -> None:
    actor_id, _, unit_id = committed_sources(migrated_database_url)
    flow = PostgresUtilityResourceFlow(runtime_database_url())
    key = uuid4()
    meter = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=key,
        request_digest="a" * 64,
    )
    replay = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=key,
        request_digest="a" * 64,
    )
    assert replay.id == meter.id
    assert len(flow.list_readings(meter.id, limit=25, cursor=None).items) == 1
    with pytest.raises(UtilityResourceIdempotencyConflict):
        flow.install_meter(
            unit_id,
            payload={**install_payload(), "serial_number": "DIFFERENT"},
            actor_id=actor_id,
            idempotency_key=key,
            request_digest="b" * 64,
        )
    with pytest.raises(UtilityResourceVersionConflict) as stale:
        flow.record_reading(
            meter.id,
            payload={
                "expected_meter_version": 2,
                "reading_date": date(2026, 1, 31),
                "reading_value": "20.000000",
                "source_kind": "MANUAL",
                "source_evidence": "Monthly photograph",
            },
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="c" * 64,
        )
    assert stale.value.current_version == 1
    reading = flow.record_reading(
        meter.id,
        payload={
            "expected_meter_version": 1,
            "reading_date": date(2026, 1, 31),
            "reading_value": "20.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Monthly photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="d" * 64,
    )
    assert reading.effective_value == 20
    assert flow.get_meter(meter.id).version == 2
    pending_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            """INSERT INTO app.utility_readings(
                id,meter_id,reading_date,reading_value,validated_at,validated_by,
                created_by,updated_by,source_kind,source_evidence
            ) VALUES(%s,%s,%s,%s,NULL,NULL,%s,%s,'MIGRATED',%s)""",
            (
                pending_id,
                meter.id,
                date(2026, 2, 28),
                "25.000000",
                actor_id,
                actor_id,
                "Published historical Utility Reading",
            ),
        )
    readings = flow.list_readings(meter.id, limit=25, cursor=None).items
    pending = next(reading for reading in readings if reading.id == pending_id)
    validated = next(item for item in readings if item.id == reading.id)
    assert isinstance(pending, ReadingRecord)
    assert isinstance(validated, ReadingRecord)
    assert pending.validated_at is None
    assert pending.validated_by is None
    assert validated.validated_at is not None
    assert validated.validated_by == actor_id


def test_runtime_replacement_and_correction_preserve_original_history(
    migrated_database_url: str,
) -> None:
    actor_id, _, unit_id = committed_sources(migrated_database_url)
    flow = PostgresUtilityResourceFlow(runtime_database_url())
    meter = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="e" * 64,
    )
    stale_boundary = flow.record_reading(
        meter.id,
        payload={
            "expected_meter_version": 1,
            "reading_date": date(2026, 1, 15),
            "reading_value": "20.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Earlier monthly photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="f" * 64,
    )
    boundary = flow.record_reading(
        meter.id,
        payload={
            "expected_meter_version": 2,
            "reading_date": date(2026, 1, 31),
            "reading_value": "30.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Failure boundary photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="0" * 64,
    )
    replacement_key = uuid4()
    replacement_digest = "1" * 64
    payload = replacement_payload(boundary.id, expected_version=3)
    replacement = flow.replace_meter(
        meter.id,
        payload=payload,
        actor_id=actor_id,
        idempotency_key=replacement_key,
        request_digest=replacement_digest,
    )
    failed = flow.get_meter(meter.id)
    assert failed.deactivated_date == date(2026, 2, 1)
    assert failed.replacement_meter_id == replacement.id
    assert replacement.replaced_meter_id == meter.id
    assert failed.replacement_events == replacement.replacement_events
    assert len(failed.replacement_events) == 1
    event = failed.replacement_events[0]
    assert event.failed_boundary_reading_id == boundary.id
    assert event.failed_boundary_reading_id != stale_boundary.id
    assert (
        event.replacement_initial_reading_id
        == flow.list_readings(replacement.id, limit=1, cursor=None).items[0].id
    )
    assert event.failure_date == date(2026, 1, 31)
    assert event.replacement_date == date(2026, 2, 1)
    assert event.expected_failed_meter_version == 3
    assert event.reason == "Confirmed mechanical failure"
    assert event.actor_id == actor_id
    assert event.idempotency_key == replacement_key
    assert event.request_digest == replacement_digest
    assert event.request_evidence is not None
    assert event.request_evidence["failed_boundary_reading_id"] == str(boundary.id)
    assert event.request_evidence["reason"] == "Confirmed mechanical failure"
    initial_evidence = event.request_evidence["replacement_initial_reading"]
    assert isinstance(initial_evidence, dict)
    assert initial_evidence["source_evidence"] == "Replacement photograph"
    replay = flow.replace_meter(
        meter.id,
        payload=payload,
        actor_id=actor_id,
        idempotency_key=replacement_key,
        request_digest=replacement_digest,
    )
    assert replay.id == replacement.id
    assert replay.replacement_events == (event,)
    with psycopg.connect(migrated_database_url) as owner:
        stored = owner.execute(
            """SELECT failed_boundary_reading_id,replacement_initial_reading_id,
               failure_date,expected_failed_meter_version,request_idempotency_key,
               request_digest,request_evidence
               FROM app.utility_meter_replacements WHERE id=%s""",
            (event.id,),
        ).fetchone()
        assert stored is not None
        assert stored[:6] == (
            boundary.id,
            event.replacement_initial_reading_id,
            date(2026, 1, 31),
            3,
            replacement_key,
            replacement_digest,
        )
        assert stored[6] == event.request_evidence
        with pytest.raises(psycopg.Error) as immutable:
            owner.execute(
                """UPDATE app.utility_meter_replacements
                SET request_evidence=request_evidence WHERE id=%s""",
                (event.id,),
            )
        assert immutable.value.sqlstate == "55000"
        owner.rollback()
    correction = flow.correct_reading(
        boundary.id,
        payload={
            "expected_version": 1,
            "corrected_value": "31.000000",
            "reason": "Reviewed source photograph",
            "authorization_reference": "utility-correction-approval-1",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="2" * 64,
    )
    assert correction.reading.original_value == 30
    assert correction.reading.effective_value == 31
    assert correction.reading.version == 2
    assert correction.correction.previous_value == 30
    _assert_runtime_replacement_rejects_non_authoritative_boundaries(migrated_database_url)


def _assert_runtime_replacement_rejects_non_authoritative_boundaries(
    migrated_database_url: str,
) -> None:
    flow = PostgresUtilityResourceFlow(runtime_database_url())

    actor_id, _, unit_id = committed_sources(migrated_database_url)
    stale_meter = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="3" * 64,
    )
    stale = flow.record_reading(
        stale_meter.id,
        payload={
            "expected_meter_version": 1,
            "reading_date": date(2026, 1, 15),
            "reading_value": "20.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Earlier boundary photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="4" * 64,
    )
    flow.record_reading(
        stale_meter.id,
        payload={
            "expected_meter_version": 2,
            "reading_date": date(2026, 1, 31),
            "reading_value": "30.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Latest boundary photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="5" * 64,
    )
    with pytest.raises(UtilityResourceInvalid):
        flow.replace_meter(
            stale_meter.id,
            payload=replacement_payload(stale.id, expected_version=3),
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="6" * 64,
        )

    wrong_actor_id, _, wrong_unit_id = committed_sources(migrated_database_url)
    wrong_meter = flow.install_meter(
        wrong_unit_id,
        payload=install_payload(),
        actor_id=wrong_actor_id,
        idempotency_key=uuid4(),
        request_digest="7" * 64,
    )
    wrong_boundary = flow.list_readings(wrong_meter.id, limit=1, cursor=None).items[0]
    with pytest.raises(UtilityResourceInvalid):
        flow.replace_meter(
            stale_meter.id,
            payload=replacement_payload(wrong_boundary.id, expected_version=3),
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="8" * 64,
        )

    pending_actor_id, _, pending_unit_id = committed_sources(migrated_database_url)
    pending_meter = flow.install_meter(
        pending_unit_id,
        payload=install_payload(),
        actor_id=pending_actor_id,
        idempotency_key=uuid4(),
        request_digest="9" * 64,
    )
    pending_boundary_id = uuid4()
    with psycopg.connect(migrated_database_url) as owner:
        owner.execute(
            """INSERT INTO app.utility_readings(
                id,meter_id,reading_date,reading_value,validated_at,validated_by,
                created_by,updated_by,source_kind,source_evidence
            ) VALUES(%s,%s,DATE '2026-01-31',20,NULL,NULL,%s,%s,'MIGRATED',%s)""",
            (
                pending_boundary_id,
                pending_meter.id,
                pending_actor_id,
                pending_actor_id,
                "Unvalidated boundary source",
            ),
        )
    with pytest.raises(UtilityResourceInvalid):
        flow.replace_meter(
            pending_meter.id,
            payload=replacement_payload(pending_boundary_id, expected_version=1),
            actor_id=pending_actor_id,
            idempotency_key=uuid4(),
            request_digest="a" * 64,
        )

    future_actor_id, _, future_unit_id = committed_sources(migrated_database_url)
    future_meter = flow.install_meter(
        future_unit_id,
        payload=install_payload(),
        actor_id=future_actor_id,
        idempotency_key=uuid4(),
        request_digest="b" * 64,
    )
    future_boundary = flow.record_reading(
        future_meter.id,
        payload={
            "expected_meter_version": 1,
            "reading_date": date(2026, 2, 1),
            "reading_value": "20.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Future boundary photograph",
        },
        actor_id=future_actor_id,
        idempotency_key=uuid4(),
        request_digest="c" * 64,
    )
    with pytest.raises(UtilityResourceInvalid):
        flow.replace_meter(
            future_meter.id,
            payload=replacement_payload(future_boundary.id, expected_version=2),
            actor_id=future_actor_id,
            idempotency_key=uuid4(),
            request_digest="d" * 64,
        )

    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            """SELECT count(*) FROM app.utility_meter_replacements
            WHERE failed_meter_id=ANY(%s)""",
            ([stale_meter.id, pending_meter.id, future_meter.id],),
        ).fetchone() == (0,)


def test_runtime_batch_partial_and_atomic_all_transactions(
    migrated_database_url: str,
) -> None:
    actor_id, property_id, unit_id = committed_sources(migrated_database_url)
    flow = PostgresUtilityResourceFlow(runtime_database_url())
    meter = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="3" * 64,
    )

    def item(
        reading_date: date, version: int, digest: str, reading_value: object = "20.000000"
    ) -> dict[str, object]:
        return {
            "idempotency_key": uuid4(),
            "meter_id": meter.id,
            "request_digest": digest * 64,
            "reading": {
                "expected_meter_version": version,
                "reading_date": reading_date,
                "reading_value": reading_value,
                "source_kind": "MANUAL",
                "source_evidence": f"Photograph {reading_date.isoformat()}",
            },
        }

    partial = flow.record_batch(
        property_id,
        mode="PARTIAL",
        items=[
            item(date(2026, 1, 31), 1, "4", Decimal("20")),
            item(date(2026, 2, 28), 1, "5"),
        ],
        actor_id=actor_id,
        idempotency_key=None,
        request_digest=None,
    )
    assert [result.status for result in partial] == ["SUCCEEDED", "FAILED"]
    assert [result.error_code for result in partial] == [None, "CONFLICT"]

    success_key = uuid4()
    success_digest = "6" * 64
    success_items = [
        item(date(2026, 2, 28), 2, "6"),
        item(date(2026, 3, 31), 3, "7", Decimal("20")),
    ]
    success = flow.record_batch(
        property_id,
        mode="ATOMIC_ALL",
        items=success_items,
        actor_id=actor_id,
        idempotency_key=success_key,
        request_digest=success_digest,
    )
    assert [result.status for result in success] == ["SUCCEEDED", "SUCCEEDED"]
    assert [result.index for result in success] == [0, 1]
    assert [result.idempotency_key for result in success] == [
        item["idempotency_key"] for item in success_items
    ]
    success_reading_ids = [result.reading.id for result in success if result.reading]
    assert len(success_reading_ids) == 2
    after_success = len(flow.list_readings(meter.id, limit=25, cursor=None).items)
    replay = flow.record_batch(
        property_id,
        mode="ATOMIC_ALL",
        items=success_items,
        actor_id=actor_id,
        idempotency_key=success_key,
        request_digest=success_digest,
    )
    assert [result.reading.id for result in replay if result.reading] == success_reading_ids
    assert len(flow.list_readings(meter.id, limit=25, cursor=None).items) == after_success
    with pytest.raises(UtilityResourceIdempotencyConflict):
        flow.record_batch(
            property_id,
            mode="ATOMIC_ALL",
            items=success_items,
            actor_id=actor_id,
            idempotency_key=success_key,
            request_digest="8" * 64,
        )

    failure_key = uuid4()
    failure_items = [item(date(2026, 4, 30), 4, "a"), item(date(2026, 5, 31), 4, "b")]
    before_failure = len(flow.list_readings(meter.id, limit=25, cursor=None).items)
    failure = flow.record_batch(
        property_id,
        mode="ATOMIC_ALL",
        items=failure_items,
        actor_id=actor_id,
        idempotency_key=failure_key,
        request_digest="c" * 64,
    )
    assert [result.status for result in failure] == ["FAILED", "FAILED"]
    assert [result.index for result in failure] == [0, 1]
    assert [result.idempotency_key for result in failure] == [
        item["idempotency_key"] for item in failure_items
    ]
    assert [result.error_code for result in failure] == ["ATOMIC_ROLLBACK", "CONFLICT"]
    assert all(result.reading is None for result in failure)
    assert len(flow.list_readings(meter.id, limit=25, cursor=None).items) == before_failure
    failure_replay = flow.record_batch(
        property_id,
        mode="ATOMIC_ALL",
        items=failure_items,
        actor_id=actor_id,
        idempotency_key=failure_key,
        request_digest="c" * 64,
    )
    assert failure_replay == failure

    with psycopg.connect(migrated_database_url) as owner:
        commands = owner.execute(
            """SELECT idempotency_key,action,request_digest
            FROM app.utility_api_commands
            WHERE actor_id=%s AND idempotency_key IN (%s,%s)
            ORDER BY idempotency_key""",
            (actor_id, success_key, failure_key),
        ).fetchall()
        assert len(commands) == 2
        assert {row[1] for row in commands} == {"RECORD_READING_BATCH"}
        assert {row[2] for row in commands} == {success_digest, "c" * 64}
        assert owner.execute(
            """SELECT count(*) FROM app.utility_api_commands
            WHERE actor_id=%s AND idempotency_key=ANY(%s)""",
            (actor_id, [entry["idempotency_key"] for entry in success_items + failure_items]),
        ).fetchone() == (0,)
        assert owner.execute(
            """SELECT count(*) FROM app.utility_api_batch_items
            WHERE actor_id=%s AND batch_idempotency_key IN (%s,%s)""",
            (actor_id, success_key, failure_key),
        ).fetchone() == (4,)
