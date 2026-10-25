"""V1-057 step 4: the audit search record and the export files (DL-072 answers 4, 12, 14).

A new audit search writes one `audit.searched` event and its next pages write none; a report
or audit export writes its own event with the file's SHA-256 fingerprint; an export job's file
is kept for its maker only, for 24 hours, and the runtime role reaches it only through the
definer functions. The shared test database holds other tests' rows, so each check keeps this
test's own events and files.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.audit_api import (
    AuditPageRequest,
    PostgresAuditEventQueryFlow,
    PropertyAuditQuery,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.report_exports import (
    AuditExportRequest,
    ExportRequest,
    ExportService,
    PostgresExportStore,
)
from property_rental.reports import (
    PostgresReportStore,
    ReportActor,
    ReportForbiddenError,
    ReportService,
)
from test_invoice_migration import runtime_database_url, setup_signed_lease
from test_reservation_migration import migrated_database_url  # noqa: F401

REVISION = "20270305_224"
RECORD = "SELECT app.record_report_activity(%s,%s,%s::uuid[],%s,%s,%s::jsonb,%s)"
STORE = "SELECT app.store_report_export(%s,%s,%s::uuid[],%s,%s,%s,%s,%s,%s,%s,%s)"
TAKE = "SELECT * FROM app.take_report_export(%s,%s,%s::uuid[],%s)"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def person(actor_id: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(actor_id),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)})) for capability in capabilities
        ),
    )


def events(url: str, actor: UUID, action: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT entity_type,entity_id,authorization_reference,resulting_state,reason "
            "FROM app.audit_events WHERE actor_id=%s AND action=%s ORDER BY occurred_at",
            (actor, action),
        ).fetchall()


def runtime(query: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(runtime_database_url()) as connection:
        return connection.execute(query, parameters).fetchall()


def test_a_new_audit_search_writes_one_event_and_its_next_pages_none(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    for _ in range(2):
        details = json.dumps({"export_id": str(uuid4()), "row_count": 1})
        runtime(RECORD, human, prop, [prop], "report_export", "data.export", details, uuid4())
    flow = PostgresAuditEventQueryFlow(runtime_database_url())
    viewer = person(human, prop, "audit.view")
    first = flow.search_property(
        viewer,
        PropertyAuditQuery(
            property_id=prop, page=AuditPageRequest(limit=1), from_date=date(2020, 1, 1)
        ),
    )
    assert first.next_cursor is not None
    flow.search_property(
        viewer,
        PropertyAuditQuery(
            property_id=prop,
            page=AuditPageRequest(limit=1, cursor=first.next_cursor),
            from_date=date(2020, 1, 1),
        ),
    )
    [(entity, _, capability, state, reason)] = events(
        migrated_database_url, human, "audit.searched"
    )
    assert (entity, capability) == ("audit_search", "audit.view")
    assert state == {"filters": {"from_date": "2020-01-01"}, "first_page_count": 1}
    assert reason == "Audit search (DL-072 answer 14)"


def test_report_activity_checks_its_kind_its_right_and_the_audit_fingerprint(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    export_id = uuid4()
    details = {"export_id": str(export_id), "file_sha256": "a" * 64, "row_count": 3}
    runtime(
        RECORD, human, prop, [prop], "report_export", "data.export", json.dumps(details), uuid4()
    )
    [(entity, entity_id, capability, state, _)] = events(
        migrated_database_url, human, "report.exported"
    )
    assert (entity, entity_id, capability, state) == (
        "report_export",
        export_id,
        "data.export",
        details,
    )
    for kind, capability, body in (
        ("report_export", "audit.export", details),
        ("audit_export", "audit.export", {"row_count": 1}),
        ("audit_export", "audit.export", {"file_sha256": "XYZ"}),
        ("customer_export", "data.export", details),
    ):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            runtime(RECORD, human, prop, [prop], kind, capability, json.dumps(body), uuid4())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime(RECORD, uuid4(), prop, [prop], "report_export", "data.export", "{}", uuid4())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime(RECORD, human, prop, [], "report_export", "data.export", "{}", uuid4())


def test_an_export_file_is_kept_for_its_maker_for_24_hours(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
        other, _, _, _ = setup_signed_lease(connection)
    content = b"PK\x03\x04 report"
    digest = hashlib.sha256(content).hexdigest()
    export_id = uuid4()
    store = (human, prop, [prop], export_id, "payments", "xlsx", "payments.xlsx", XLSX)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        runtime(STORE, *store, content, "0" * 64, 1)
    [(expires_at,)] = runtime(STORE, *store, content, digest, 1)
    [kept] = runtime(TAKE, human, prop, [prop], export_id)
    assert kept[:4] == ("payments", "xlsx", "payments.xlsx", XLSX)
    assert bytes(kept[4]) == content and kept[5] == digest and kept[7] == expires_at
    assert runtime(TAKE, other, prop, [prop], export_id) == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime("SELECT count(*) FROM app.report_export_files")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.report_export_files SET created_at=created_at-interval '25 hours',"
            "expires_at=expires_at-interval '25 hours' WHERE id=%s",
            (export_id,),
        )
    assert runtime(TAKE, human, prop, [prop], export_id) == []
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.report_export_files WHERE id=%s", (export_id,)
        ).fetchone() == (0,)


def test_an_export_through_the_service_writes_its_event_with_the_file_fingerprint(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    exports = ExportService(
        ReportService(PostgresReportStore(runtime_database_url())),
        PostgresExportStore(runtime_database_url()),
    )
    manager = person(human, prop, "reports.read", "data.export")
    result = exports.export(manager, prop, ExportRequest("invoice_register", "xlsx"))
    assert result.file.content.startswith(b"PK")
    [(_, entity_id, _, state, _)] = events(migrated_database_url, human, "report.exported")
    assert entity_id == result.export_id
    assert state["file_sha256"] == hashlib.sha256(result.file.content).hexdigest()
    assert state["report_kind"] == "invoice_register" and state["file_type"] == "xlsx"
    # The History page reads the export's event with its fingerprint.
    page = PostgresAuditEventQueryFlow(runtime_database_url()).search_property(
        person(human, prop, "audit.view"),
        PropertyAuditQuery(property_id=prop, page=AuditPageRequest(limit=5), actor_id=human),
    )
    shown = [event for event in page.events if event.action == "report.exported"]
    assert len(shown) == 1


def test_an_odd_search_filter_is_left_out_so_history_still_reads_the_search(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Review round 1: a search for free text must not leave an event History cannot read."""
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    flow = PostgresAuditEventQueryFlow(runtime_database_url())
    viewer = person(human, prop, "audit.view")
    odd = PropertyAuditQuery(property_id=prop, page=AuditPageRequest(limit=5), action="foo bar")
    assert flow.search_property(viewer, odd).events == ()
    [(_, _, _, state, _)] = events(migrated_database_url, human, "audit.searched")
    assert state == {"filters": {"filters_not_recorded_count": 1}, "first_page_count": 0}
    page = flow.search_property(
        viewer,
        PropertyAuditQuery(property_id=prop, page=AuditPageRequest(limit=5), actor_id=human),
    )
    assert [event.action for event in page.events] == ["audit.searched"]


def test_the_database_checks_the_property_against_the_persons_grants(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, _ = setup_signed_lease(connection)
    store = PostgresReportStore(runtime_database_url())
    assert store.rows("report_lease_dates", ReportActor(human, (prop,)), prop) != []
    with pytest.raises(ReportForbiddenError):
        store.rows("report_lease_dates", ReportActor(human, (uuid4(),)), prop)


def test_an_audit_file_for_a_unit_holds_the_events_about_the_unit_itself(
    migrated_database_url: str,  # noqa: F811
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, lease = setup_signed_lease(connection)
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
        unit = row[0]
        connection.execute(
            "INSERT INTO app.audit_events (id,occurred_at,business_date,actor_id,action,"
            "entity_type,entity_id,reason,property_id,resulting_state,correlation_id,source,"
            "outcome) VALUES (%s,now(),current_date,%s,'unit.status_changed','unit',%s,"
            "'Unit check',%s,'{\"status\":\"VACANT\"}'::jsonb,%s,'API','SUCCEEDED')",
            (uuid4(), human, unit, prop, uuid4()),
        )
    rows = PostgresExportStore(runtime_database_url()).audit_rows(
        prop, AuditExportRequest("xlsx", unit_id=unit)
    )
    unit_events = [item for item in rows if item["action"] == "unit.status_changed"]
    assert len(unit_events) == 1 and unit_events[0]["unit_number"] is not None


def test_the_report_exports_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270304_223"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
