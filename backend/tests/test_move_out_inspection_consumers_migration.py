"""Inspection audit consumers and atomic completion under caller constraint modes."""

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.audit_api import (
    AUDIT_VIEW_CAPABILITY,
    AuditPageRequest,
    PostgresAuditEventQueryFlow,
    PropertyAuditQuery,
    ResourceAuditQuery,
    _event_view,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_inspection import InspectionFinding, inspection_request_digest
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import NEW_TABLES, actor, flow, raw_record, snapshot, source


@pytest.mark.parametrize("finding_count", [0, 2, 50])
def test_inspection_audit_property_lease_customer_consumers_preserve_full_source(
    migrated_database_url: str, finding_count: int
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    request = replace(
        request,
        result_text=("Inspection condition " * 250)[:5000],
        reason=("Approved observation " * 25)[:500],
        authorization_reference=("Approval reference " * 30)[:500],
        evidence_reference=("Evidence reference " * 30)[:500],
        findings=tuple(
            InspectionFinding(uuid4(), ("Observed condition " * 60)[:1000], bool(index % 2))
            for index in range(finding_count)
        ),
    )
    before = snapshot(migrated_database_url)
    original = flow().record(prop, lease, request, actor=actor(human, prop), request_id="first")
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert row is not None
        customer = cast(UUID, row[0])
    reader = AuthenticatedActor(
        str(human),
        frozenset({CapabilityGrant(AUDIT_VIEW_CAPABILITY, frozenset({str(prop)}))}),
    )
    queries = PostgresAuditEventQueryFlow(runtime_database_url())
    prior_state: object = None
    correction = replace(
        request,
        idempotency_key=uuid4(),
        inspection_id=uuid4(),
        supersedes_inspection_id=request.inspection_id,
        result_text="Corrected inspection evidence",
        findings=(),
    )
    for count, chosen in ((1, request), (2, correction)):
        if count == 2:
            flow().record(prop, lease, chosen, actor=actor(human, prop), request_id="correct")
        pages = [
            queries.search_property(
                reader,
                PropertyAuditQuery(
                    prop, AuditPageRequest(limit=count), action="lease.inspection.record"
                ),
            ),
            *(
                queries.resource_timeline(
                    reader, ResourceAuditQuery(kind, identity, AuditPageRequest(limit=count))
                )
                for kind, identity in (("leases", lease), ("customers", customer))
            ),
        ]
        for page in pages:
            assert len(page.events) == count
            views = [_event_view(event) for event in page.events]
            current = views[0]
            assert current.resource_id == chosen.inspection_id
            assert current.linked_source_event_id == chosen.inspection_id
            assert current.previous_state == prior_state
            state = cast(dict[str, object], current.resulting_state)
            assert state["inspection_id"] == str(chosen.inspection_id)
            assert state["actor_id"] == str(human)
            assert state["findings_count"] == len(chosen.findings)
            assert state["inspection_status"] == "INSPECTION_ONLY"
            assert state["supersedes_inspection_id"] == (
                str(request.inspection_id) if count == 2 else None
            )
            assert "result_text" not in state and "evidence_reference" not in state
            findings = cast(list[dict[str, object]], state["findings"])
            assert [item["finding_id"] for item in findings] == [
                str(finding.finding_id) for finding in chosen.findings
            ]
            assert [item["sequence"] for item in findings] == list(range(1, len(findings) + 1))
            if count == 2:
                assert views[1].resulting_state == prior_state
        if count == 1:
            prior_state = _event_view(pages[0].events[0]).resulting_state
    assert (
        flow().record(prop, lease, request, actor=actor(human, prop), request_id="retry")
        == original
    )
    data = cast(dict[str, object], original.body["data"])
    read = flow().read(prop, lease, actor=actor(human, prop))
    old = cast(list[dict[str, object]], read["items"])[0]
    for field in (
        "result_text",
        "reason",
        "authorization_reference",
        "evidence_reference",
        "findings",
    ):
        assert old[field] == data[field]
    assert data["result_text"] == request.result_text
    assert [
        finding["description"] for finding in cast(list[dict[str, object]], data["findings"])
    ] == [finding.description for finding in request.findings]
    after = without_searches(snapshot(migrated_database_url))
    assert all(
        after[table] == rows
        for table, rows in before.items()
        if table not in NEW_TABLES | {"audit_events"}
    )
    assert len(after["audit_events"]) == len(without_searches(before)["audit_events"]) + 2


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
@pytest.mark.parametrize("same_transaction", [True, False])
@pytest.mark.parametrize("finding_count", [0, 2])
def test_inspection_complete_commands_and_replay_in_both_constraint_modes(
    migrated_database_url: str, mode: str, same_transaction: bool, finding_count: int
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    request = replace(request, findings=request.findings[:finding_count])
    correction = replace(
        request,
        inspection_id=uuid4(),
        idempotency_key=uuid4(),
        supersedes_inspection_id=request.inspection_id,
        findings=(),
    )
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        original = raw_record(connection, prop, lease, human, request)
        if not same_transaction:
            connection.commit()
            connection.execute("SET CONSTRAINTS ALL " + mode)
        corrected = raw_record(connection, prop, lease, human, correction)
        assert raw_record(connection, prop, lease, human, request) == original
        assert raw_record(connection, prop, lease, human, correction) == corrected
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    before_replay = snapshot(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        assert raw_record(connection, prop, lease, human, request) == original
        assert raw_record(connection, prop, lease, human, correction) == corrected
    assert snapshot(migrated_database_url) == before_replay


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
@pytest.mark.parametrize("incomplete", [True, False])
def test_inspection_incomplete_or_late_finding_evidence_rejected_in_both_modes(
    migrated_database_url: str, mode: str, incomplete: bool
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    flow().record(prop, lease, request, actor=actor(human, prop), request_id="original")
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        with pytest.raises(psycopg.errors.CheckViolation):
            if incomplete:
                connection.execute(
                    "INSERT INTO app.move_out_inspections SELECT %s,property_id,lease_i"
                    "d,"
                    "expected_lease_version,inspection_date,result_text,completed_at,co"
                    "mpleted_by,"
                    "authorization_reference,evidence_reference,reason,NULL "
                    "FROM app.move_out_inspections WHERE id=%s",
                    (uuid4(), request.inspection_id),
                )
            else:
                connection.execute(
                    "INSERT INTO app.inspection_damage_findings SELECT %s,id,3,%s,false"
                    ","
                    "completed_at,completed_by FROM app.move_out_inspections WHERE id=%"
                    "s",
                    (uuid4(), "Later unrecorded finding", request.inspection_id),
                )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize(
    "mismatch", [None, "resulting_state", "previous_state", "authorization_evidence"]
)
def test_inspection_completion_binds_typed_audit_projection(
    migrated_database_url: str, mismatch: str | None
) -> None:
    human, prop, lease, original = source(migrated_database_url)
    original = replace(original, findings=())
    flow().record(prop, lease, original, actor=actor(human, prop), request_id="original")
    before = snapshot(migrated_database_url)
    copied = replace(original, idempotency_key=uuid4(), inspection_id=uuid4())
    event_id = uuid4()
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "INSERT INTO app.move_out_inspections SELECT %s,property_id,lease_id,"
            "expected_lease_version,inspection_date,result_text,completed_at,completed_"
            "by,"
            "authorization_reference,evidence_reference,reason,NULL "
            "FROM app.move_out_inspections WHERE id=%s",
            (copied.inspection_id, original.inspection_id),
        )
        row = connection.execute(
            "SELECT app.move_out_inspection_audit_snapshot(app.move_out_inspection_snapshot(%s))",
            (copied.inspection_id,),
        ).fetchone()
        assert row is not None
        resulting = cast(dict[str, object], row[0])
        previous: dict[str, object] | None = None
        authorization = {"capability": "leases.inspect", "inspection_id": str(copied.inspection_id)}
        if mismatch == "resulting_state":
            resulting = resulting | {"findings_count": 1}
        elif mismatch == "previous_state":
            previous = resulting
        elif mismatch == "authorization_evidence":
            authorization["inspection_id"] = str(uuid4())
        connection.execute(
            "INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,"
            "entity_type,"
            "entity_id,reason,authorization_reference,property_id,previous_state,result"
            "ing_state,"
            "correlation_id,source,outcome,authorization_evidence,linked_source_event_i"
            "d,customer_id,lease_id) "
            "SELECT %s,a.occurred_at,a.business_date,a.actor_id,a.action,a.entity_type,"
            "%s,a.reason,"
            "a.authorization_reference,a.property_id,%s,%s,%s,a.source,a.outcome,%s,%s,"
            "a.customer_id,a.lease_id "
            "FROM app.audit_events a JOIN app.move_out_inspection_commands c ON c.audit"
            "_event_id=a.id "
            "WHERE c.inspection_id=%s",
            (
                event_id,
                copied.inspection_id,
                None if previous is None else Jsonb(previous),
                Jsonb(resulting),
                copied.idempotency_key,
                Jsonb(authorization),
                copied.inspection_id,
                original.inspection_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.move_out_inspection_commands SELECT property_id,actor_id,%"
            "s,lease_id,"
            "%s,%s,%s,%s,jsonb_set(response_body,'{data}',app.move_out_inspection_snaps"
            "hot(%s)),completed_at "
            "FROM app.move_out_inspection_commands WHERE inspection_id=%s",
            (
                copied.idempotency_key,
                copied.inspection_id,
                event_id,
                inspection_request_digest(prop, lease, copied.intent()),
                Jsonb(copied.intent()),
                copied.inspection_id,
                original.inspection_id,
            ),
        )
        if mismatch is None:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            connection.rollback()
        else:
            with pytest.raises(
                psycopg.errors.CheckViolation, match="source, command and audit evidence must agree"
            ):
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(migrated_database_url) == before


def without_searches(
    tables: dict[str, list[tuple[object, ...]]],
) -> dict[str, list[tuple[object, ...]]]:
    """The tables without the `audit.searched` events a History search now writes (V1-057)."""
    events = [
        row
        for row in tables["audit_events"]
        if not (isinstance(row[0], dict) and row[0].get("action") == "audit.searched")
    ]
    return {**tables, "audit_events": events}


def test_inspection_audit_projection_remains_internal(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,'app.move_out_inspection_audit_snapsh"
                "ot(jsonb)','EXECUTE')",
                (role,),
            ).fetchone() == (False,)
