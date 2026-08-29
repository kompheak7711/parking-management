"""Disposable PostgreSQL coverage for the V1-043 Utility API boundary."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.utility_api import (
    PostgresUtilityResourceFlow,
    UtilityResourceIdempotencyConflict,
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


def committed_sources(database_url: str) -> tuple[UUID, UUID, UUID]:
    with psycopg.connect(database_url) as owner:
        actor_id, property_id, unit_id, _, _ = setup_sources(owner)
        owner.commit()
    return actor_id, property_id, unit_id


def install_payload() -> dict[str, object]:
    return {
        "utility_type": "ELECTRICITY",
        "serial_number": "ELEC-API-301",
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


def test_v1_043_is_forward_only_head_and_runtime_has_only_command_execute(
    migrated_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_current_head() == "20260829_34"
    source = (
        Path(__file__).parents[1] / "migrations/versions/20260829_34_v1_043_utility_api.py"
    ).read_text()
    assert 'raise RuntimeError("V1-043 Utility API migration is forward-only")' in source
    with psycopg.connect(migrated_database_url) as owner:
        for table in ("utility_meters", "utility_readings", "utility_api_commands"):
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
    boundary = flow.record_reading(
        meter.id,
        payload={
            "expected_meter_version": 1,
            "reading_date": date(2026, 1, 31),
            "reading_value": "30.000000",
            "source_kind": "MANUAL",
            "source_evidence": "Failure boundary photograph",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="f" * 64,
    )
    replacement = flow.replace_meter(
        meter.id,
        payload={
            "expected_version": 2,
            "failed_boundary_reading_id": boundary.id,
            "failure_date": date(2026, 1, 31),
            "replacement_date": date(2026, 2, 1),
            "reason": "Confirmed mechanical failure",
            "replacement_meter": {
                "serial_number": "ELEC-API-302",
                "description": None,
                "memo": "Replacement work order",
            },
            "replacement_initial_reading": {
                "reading_date": date(2026, 2, 1),
                "reading_value": "0.000000",
                "source_evidence": "Replacement photograph",
            },
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="1" * 64,
    )
    failed = flow.get_meter(meter.id)
    assert failed.deactivated_date == date(2026, 2, 1)
    assert failed.replacement_meter_id == replacement.id
    assert replacement.replaced_meter_id == meter.id
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

    def item(reading_date: date, version: int, digest: str) -> dict[str, object]:
        return {
            "idempotency_key": uuid4(),
            "meter_id": meter.id,
            "request_digest": digest * 64,
            "reading": {
                "expected_meter_version": version,
                "reading_date": reading_date,
                "reading_value": "20.000000",
                "source_kind": "MANUAL",
                "source_evidence": f"Photograph {reading_date.isoformat()}",
            },
        }

    partial = flow.record_batch(
        property_id,
        mode="PARTIAL",
        items=[item(date(2026, 1, 31), 1, "4"), item(date(2026, 2, 28), 1, "5")],
        actor_id=actor_id,
    )
    assert [result.status for result in partial] == ["SUCCEEDED", "FAILED"]
    before_atomic = len(flow.list_readings(meter.id, limit=25, cursor=None).items)
    with pytest.raises(UtilityResourceVersionConflict):
        flow.record_batch(
            property_id,
            mode="ATOMIC_ALL",
            items=[item(date(2026, 2, 28), 2, "6"), item(date(2026, 3, 31), 2, "7")],
            actor_id=actor_id,
        )
    assert len(flow.list_readings(meter.id, limit=25, cursor=None).items) == before_atomic
