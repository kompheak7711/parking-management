"""Migration 20270329_248 (V1-060 B6, DL-104): Report broken on a Utility Meter.

The owner asked on 2026-10-28 how staff report a broken meter or change its status. The approved
DESIGN.md "Report broken" keeps the date found broken and a reason; the meter then shows "Broken
since" and its Readings are no longer accepted until it is replaced (BR-UTIL-006, DB-UTIL-001).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.utility_api import (
    MeterRecord,
    PostgresUtilityResourceFlow,
    UtilityResourceConflict,
    UtilityResourceIdempotencyConflict,
    UtilityResourceInvalid,
    UtilityResourceNotFound,
    UtilityResourceVersionConflict,
)
from test_utility_api_migration import (
    committed_sources,
    install_payload,
    replacement_payload,
    runtime_database_url,
)
from test_utility_api_migration import migrated_database_url as migrated_database_url

REPORT = "app.report_utility_meter_failure_api(uuid,uuid,integer,date,text,uuid,uuid,text)"
TABLE = "app.utility_meter_failure_reports"


def _reading(
    flow: PostgresUtilityResourceFlow,
    meter_id: UUID,
    actor_id: UUID,
    *,
    version: int,
    reading_date: date,
    value: str,
) -> UUID:
    return flow.record_reading(
        meter_id,
        payload={
            "expected_meter_version": version,
            "reading_date": reading_date,
            "reading_value": value,
            "source_kind": "MANUAL",
            "source_evidence": f"Monthly photograph {reading_date.isoformat()}",
        },
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest=uuid4().hex * 2,
    ).id


def _meter_with_reading(url: str) -> tuple[PostgresUtilityResourceFlow, UUID, MeterRecord, UUID]:
    """A Meter put in on 1/1/2026 with a Reading on 31/1/2026, so at version 2."""
    actor_id, _, unit_id = committed_sources(url)
    flow = PostgresUtilityResourceFlow(runtime_database_url())
    meter = flow.install_meter(
        unit_id,
        payload=install_payload(),
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest=uuid4().hex * 2,
    )
    boundary = _reading(
        flow, meter.id, actor_id, version=1, reading_date=date(2026, 1, 31), value="20.000000"
    )
    return flow, actor_id, flow.get_meter(meter.id), boundary


def _report(
    flow: PostgresUtilityResourceFlow,
    meter_id: UUID,
    actor_id: UUID,
    *,
    version: int,
    failure_date: date,
    reason: str = "The display is blank",
    key: UUID | None = None,
    digest: str | None = None,
) -> MeterRecord:
    return flow.report_failure(
        meter_id,
        payload={"expected_version": version, "failure_date": failure_date, "reason": reason},
        actor_id=actor_id,
        idempotency_key=key or uuid4(),
        request_digest=digest or uuid4().hex * 2,
    )


def _today(url: str) -> date:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT timezone('Asia/Phnom_Penh',clock_timestamp())::date"
        ).fetchone()
    assert row is not None
    return cast(date, row[0])


def test_a_broken_meter_refuses_later_readings_and_replace_keeps_the_date(
    migrated_database_url: str,
) -> None:
    flow, actor_id, meter, boundary = _meter_with_reading(migrated_database_url)
    assert (meter.version, meter.failure_date, meter.failure_report) == (2, None, None)
    key, digest = uuid4(), "7" * 64
    broken = _report(
        flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 10), key=key, digest=digest
    )
    assert (broken.failure_date, broken.deactivated_date, broken.version) == (
        date(2026, 2, 10),
        None,
        3,
    )
    report = broken.failure_report
    assert report is not None
    assert (report.failure_date, report.reason, report.actor_id) == (
        date(2026, 2, 10),
        "The display is blank",
        actor_id,
    )
    # The same key and request give the same answer and keep one report.
    replay = _report(
        flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 10), key=key, digest=digest
    )
    assert (replay.failure_report, replay.version) == (report, 3)
    with pytest.raises(UtilityResourceIdempotencyConflict):
        _report(
            flow,
            meter.id,
            actor_id,
            version=2,
            failure_date=date(2026, 2, 11),
            key=key,
            digest="8" * 64,
        )
    # A Meter is reported broken once; then it must be replaced.
    with pytest.raises(UtilityResourceConflict) as again:
        _report(flow, meter.id, actor_id, version=3, failure_date=date(2026, 2, 10))
    assert type(again.value) is UtilityResourceConflict
    with pytest.raises(UtilityResourceInvalid):
        _reading(
            flow, meter.id, actor_id, version=3, reading_date=date(2026, 2, 11), value="25.000000"
        )
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            f"SELECT count(*),min(expected_meter_version),min(request_digest) FROM {TABLE} "
            "WHERE meter_id=%s",
            (meter.id,),
        ).fetchone() == (1, 2, digest)
        assert owner.execute(
            "SELECT action,resource_id FROM app.utility_api_commands "
            "WHERE actor_id=%s AND idempotency_key=%s",
            (actor_id, key),
        ).fetchone() == ("REPORT_METER_FAILURE", meter.id)

    # Replace meter keeps the reported date: another date is refused.
    with pytest.raises(UtilityResourceConflict) as moved:
        flow.replace_meter(
            meter.id,
            payload=replacement_payload(
                boundary,
                expected_version=3,
                failure_date=date(2026, 2, 11),
                replacement_date=date(2026, 2, 12),
            ),
            actor_id=actor_id,
            idempotency_key=uuid4(),
            request_digest="9" * 64,
        )
    assert type(moved.value) is UtilityResourceConflict
    replacement = flow.replace_meter(
        meter.id,
        payload=replacement_payload(
            boundary,
            expected_version=3,
            failure_date=date(2026, 2, 10),
            replacement_date=date(2026, 2, 12),
        ),
        actor_id=actor_id,
        idempotency_key=uuid4(),
        request_digest="a" * 64,
    )
    failed = flow.get_meter(meter.id)
    assert (failed.failure_date, failed.deactivated_date) == (date(2026, 2, 10), date(2026, 2, 12))
    assert failed.replacement_meter_id == replacement.id
    assert failed.failure_report == report
    assert replacement.failure_report is None


def test_report_broken_checks_the_version_the_dates_and_the_inputs(
    migrated_database_url: str,
) -> None:
    flow, actor_id, meter, _ = _meter_with_reading(migrated_database_url)
    with pytest.raises(UtilityResourceVersionConflict) as stale:
        _report(flow, meter.id, actor_id, version=1, failure_date=date(2026, 2, 1))
    assert stale.value.current_version == 2
    # Not before the Meter was put in, not before its latest Reading, not after today.
    later = _today(migrated_database_url) + timedelta(days=2)
    for failure_date in (date(2025, 12, 31), date(2026, 1, 30), later):
        with pytest.raises(UtilityResourceInvalid):
            _report(flow, meter.id, actor_id, version=2, failure_date=failure_date)
    for reason in (" The display is blank", "", "x" * 501):
        with pytest.raises(UtilityResourceInvalid):
            _report(
                flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 1), reason=reason
            )
    with pytest.raises(UtilityResourceInvalid):
        _report(flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 1), digest="A" * 64)
    with pytest.raises(UtilityResourceNotFound):
        _report(flow, uuid4(), actor_id, version=2, failure_date=date(2026, 2, 1))
    assert flow.get_meter(meter.id).failure_date is None
    # The day of the latest Reading is allowed: that Reading is the last good one.
    broken = _report(flow, meter.id, actor_id, version=2, failure_date=date(2026, 1, 31))
    assert broken.failure_date == date(2026, 1, 31)


def test_report_broken_is_least_privilege_and_its_reports_are_append_only(
    migrated_database_url: str,
) -> None:
    flow, actor_id, meter, _ = _meter_with_reading(migrated_database_url)
    today = _today(migrated_database_url)
    report = _report(flow, meter.id, actor_id, version=2, failure_date=today).failure_report
    assert report is not None and report.failure_date == today
    with psycopg.connect(migrated_database_url) as owner:
        assert owner.execute(
            "SELECT routine.prosecdef,routine.proconfig @> ARRAY['search_path=pg_catalog'] "
            "FROM pg_catalog.pg_proc AS routine WHERE routine.oid=%s::regprocedure",
            (REPORT,),
        ).fetchone() == (True, True)
        for role in ("public", "prm_runtime", "prm_financial", "prm_bootstrap"):
            assert owner.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, REPORT)
            ).fetchone() == (role == "prm_runtime",), role
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert owner.execute(
                    "SELECT has_table_privilege(%s,%s,%s)", (role, TABLE, privilege)
                ).fetchone() == (
                    privilege == "SELECT" and role in {"prm_runtime", "prm_financial"},
                ), (role, privilege)
        for statement in (
            f"UPDATE {TABLE} SET reason='Changed' WHERE id=%s",
            f"DELETE FROM {TABLE} WHERE id=%s",
        ):
            with pytest.raises(psycopg.Error) as kept:
                with owner.transaction():
                    owner.execute(statement, (report.id,))
            assert kept.value.sqlstate == "55000"
        with pytest.raises(psycopg.Error) as truncated:
            with owner.transaction():
                owner.execute(f"TRUNCATE {TABLE}")
        assert truncated.value.sqlstate == "55000"


def test_report_broken_migration_is_the_head_and_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20270329_248")
    assert revision is not None and revision.down_revision == "20270328_247"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
