"""Migration 20270404_254 (V1-061, DL-114): Meter changes show in History.

Owner bug list of 2026-10-29: "Meter changes must show in History." A new Meter, a replaced
Meter and a Meter reported broken each write one audit event, with the Unit, in the same
transaction; a replay writes none.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_report_broken_meter_migration import _meter_with_reading, _report
from test_utility_api_migration import migrated_database_url as migrated_database_url
from test_utility_api_migration import replacement_payload


def history(url: str, unit_id: UUID) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT event.action, event.entity_id, event.reason, event.actor_id, "
            "event.previous_state ->> 'serial_number', event.resulting_state ->> 'serial_number' "
            "FROM app.audit_events AS event WHERE event.unit_id=%s "
            "AND event.entity_type='utility_meter' ORDER BY event.occurred_at, event.action",
            (unit_id,),
        ).fetchall()


def test_adding_reporting_and_replacing_a_meter_each_show_once_in_history(
    migrated_database_url: str,
) -> None:
    flow, actor_id, meter, boundary = _meter_with_reading(migrated_database_url)
    unit_id = meter.unit_id
    assert history(migrated_database_url, unit_id) == [
        ("utility.meter.installed", meter.id, "Meter added", actor_id, None, meter.serial_number)
    ]
    key, digest = uuid4(), "7" * 64
    _report(
        flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 10), key=key, digest=digest
    )
    # The same press again writes nothing more.
    _report(
        flow, meter.id, actor_id, version=2, failure_date=date(2026, 2, 10), key=key, digest=digest
    )
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
    assert history(migrated_database_url, unit_id) == [
        ("utility.meter.installed", meter.id, "Meter added", actor_id, None, meter.serial_number),
        (
            "utility.meter.failure_reported",
            meter.id,
            "The display is blank",
            actor_id,
            None,
            meter.serial_number,
        ),
        (
            "utility.meter.replaced",
            replacement.id,
            "Confirmed mechanical failure",
            actor_id,
            meter.serial_number,
            replacement.serial_number,
        ),
    ]
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT bool_and(event.property_id = unit.property_id), "
            "bool_and(event.authorization_reference = 'utility_meters.manage') "
            "FROM app.audit_events AS event JOIN app.units AS unit ON unit.id = event.unit_id "
            "WHERE event.unit_id=%s AND event.entity_type='utility_meter'",
            (unit_id,),
        ).fetchone()
    assert row == (True, True)


def test_the_meter_history_migration_is_the_head_and_is_forward_only() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = script.get_revision("20270404_254")
    assert revision is not None
    assert revision.down_revision == "20270403_253"
    assert script.get_current_head() == "20270404_254"
