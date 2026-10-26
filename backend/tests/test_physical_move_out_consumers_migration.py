"""Preserve later Unit decisions and retrieve complete physical-departure audits."""

from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from payment_test_support import seed_deposit_payment
from property_rental.audit_api import (
    AUDIT_VIEW_CAPABILITY,
    AuditPageRequest,
    PostgresAuditEventQueryFlow,
    PropertyAuditQuery,
    ResourceAuditQuery,
    _event_view,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    CompleteMoveInCommand,
    MoveInOccupant,
    PostgresMoveInService,
)
from property_rental.physical_move_out import (
    EndedOccupancy,
    PhysicalMoveOutConflictError,
    RecordPhysicalMoveOut,
    physical_move_out_digest,
)
from property_rental.unit import UnitStatus
from property_rental.unit_api import PostgresUnitResourceFlow, UnitDetails
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_invoice_migration import runtime_database_url
from test_lease_migration import create_draft, sign_lease
from test_move_in_migration import setup_historical_move_in
from test_physical_move_out_migration import (
    NEW_TABLES,
    raw_record,
    record,
    snapshot,
    source,
    successor,
)
from test_reservation_migration import create_reservation, reservation_business_date
from test_termination_deposit_migration import terminate


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


def source_ended_yesterday(url: str) -> tuple[UUID, UUID, UUID, RecordPhysicalMoveOut]:
    move_flow, staff, move = setup_historical_move_in(
        url, signed_day_offset=-1, receipt_day_offset=-1
    )
    human, prop, lease = move_flow.actor_id, move_flow.property_id, move.lease_id
    result = move_flow.complete(move, actor=staff)
    actual_date = move.actual_move_in_date + timedelta(days=1)
    termination = terminate(url, human, prop, lease, actual_date)
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT l.version,u.version FROM app.leases l JOIN app.units u "
            "ON u.id=l.unit_id WHERE l.id=%s",
            (lease,),
        ).fetchone()
        assert row is not None
    return (
        human,
        prop,
        lease,
        RecordPhysicalMoveOut(
            uuid4(),
            uuid4(),
            termination,
            int(row[0]),
            int(row[1]),
            actual_date,
            "CLEANING",
            tuple(EndedOccupancy(identity, 1) for identity in result.occupancy_ids),
            "Observed departure confirmed",
            "Authorized move-out",
            "Synthetic departure evidence",
        ),
    )


def later_unit_activity(url: str, human: UUID, prop: UUID, lease: UUID, activity: str) -> UUID:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
        unit_id = cast(UUID, row[0])
    units = PostgresUnitResourceFlow(runtime_database_url())
    unit = units.get(unit_id)
    units.patch(
        unit_id,
        floor_item_id=unit.floor_item_id,
        unit_type=unit.unit_type,
        unit_status=UnitStatus(
            activity if activity in {"UNDER_MAINTENANCE", "OUT_OF_SERVICE"} else "VACANT"
        ),
        details=UnitDetails.of(unit),
        expected_version=unit.version,
        actor_id=str(human),
    )
    if activity in {"VACANT", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"}:
        return unit_id
    with psycopg.connect(url) as connection:
        customer = uuid4()
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Later synthetic Customer',%s,%s)",
            (customer, human, human),
        )
        today = reservation_business_date(connection, prop)
        _, ids = create_reservation(
            connection,
            actor_id=human,
            property_id=prop,
            unit_id=unit_id,
            customer_id=customer,
        )
        connection.commit()
        if activity == "RESERVED":
            return unit_id
        later_lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit_id,
            primary_tenant_id=customer,
            start_date=today,
            end_date=today + timedelta(days=365),
        )
        sign_lease(connection, later_lease, human)
        if activity == "SIGNED":
            return unit_id
        payment = seed_deposit_payment(
            connection, deposit_id=ids["deposit_id"], actor_id=human, amount=40_000
        )
        connection.execute(
            "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,am"
            "ount_usd_cents,occurred_at,actor_id) "
            "VALUES (%s,%s,%s,40000,clock_timestamp(),%s)",
            (uuid4(), ids["deposit_id"], payment, human),
        )
        row = connection.execute("SELECT version FROM app.units WHERE id=%s", (unit_id,)).fetchone()
        assert row is not None
        command = CompleteMoveInCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=ids["reservation_id"],
            lease_id=later_lease,
            expected_reservation_version=1,
            expected_lease_version=2,
            expected_unit_version=int(row[0]),
            actual_move_in_date=today,
            occupants=(MoveInOccupant(uuid4(), customer),),
            reason="Confirmed later move-in",
            authorization_reference=MOVE_IN_CAPABILITY,
        )
    staff = AuthenticatedActor(
        str(human),
        frozenset({CapabilityGrant(MOVE_IN_CAPABILITY, frozenset({str(prop)}))}),
    )
    PostgresMoveInService(runtime_database_url(), prop, human).complete(command, actor=staff)
    return unit_id


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
@pytest.mark.parametrize(
    "activity",
    ["VACANT", "RESERVED", "SIGNED", "OCCUPIED", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"],
)
def test_physical_evidence_successor_preserves_later_unit_reservation_and_lease(
    migrated_database_url: str, mode: str, activity: str
) -> None:
    make_source = source_ended_yesterday if activity in {"SIGNED", "OCCUPIED"} else source
    human, prop, lease, request = make_source(migrated_database_url)
    original = record(prop, lease, human, request)
    stale = successor(migrated_database_url, lease, request)
    unit_id = later_unit_activity(migrated_database_url, human, prop, lease, activity)
    before = snapshot(migrated_database_url)
    with pytest.raises(PhysicalMoveOutConflictError):
        record(prop, lease, human, stale)
    assert snapshot(migrated_database_url) == before
    correction = successor(migrated_database_url, lease, request)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        response = raw_record(connection, prop, lease, human, correction)
        assert raw_record(connection, prop, lease, human, correction) == response
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    after = snapshot(migrated_database_url)
    assert all(
        after[table] == rows
        for table, rows in before.items()
        if table not in NEW_TABLES | {"audit_events"}
    )
    for table in NEW_TABLES | {"audit_events"}:
        assert all(row in after[table] for row in before[table])
    body = cast(dict[str, object], response["body"])
    data = cast(dict[str, object], body["data"])
    expected_status = "RESERVED" if activity == "SIGNED" else activity
    assert data["previous_unit_status"] == data["resulting_unit_status"] == expected_status
    assert (
        data["expected_unit_version"]
        == data["resulting_unit_version"]
        == correction.expected_unit_version
    )
    assert (
        PostgresUnitResourceFlow(runtime_database_url()).get(unit_id).version
        == correction.expected_unit_version
    )
    before_replay = snapshot(migrated_database_url)
    assert record(prop, lease, human, request) == original
    assert snapshot(migrated_database_url) == before_replay


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
@pytest.mark.parametrize("change", ["date", "condition"])
def test_physical_substantive_correction_retains_existing_transition_rules(
    migrated_database_url: str, mode: str, change: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    original = record(prop, lease, human, request)
    later_unit_activity(migrated_database_url, human, prop, lease, "VACANT")
    correction = successor(migrated_database_url, lease, request, date_change=change == "date")
    if change == "condition":
        correction = replace(correction, unit_condition="UNDER_MAINTENANCE")
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        response = raw_record(connection, prop, lease, human, correction)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    body = cast(dict[str, object], response["body"])
    data = cast(dict[str, object], body["data"])
    assert data["previous_unit_status"] == "VACANT"
    assert data["resulting_unit_status"] == correction.unit_condition
    assert data["resulting_unit_version"] == correction.expected_unit_version + 1
    members = cast(list[dict[str, object]], data["occupancies"])
    assert members[0]["resulting_version"] == cast(int, members[0]["previous_version"]) + int(
        change == "date"
    )
    before_replay = snapshot(migrated_database_url)
    assert record(prop, lease, human, request) == original
    assert snapshot(migrated_database_url) == before_replay


def test_physical_original_and_corrected_audits_reach_unit_readers(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    original = record(prop, lease, human, request)
    unit_id = later_unit_activity(migrated_database_url, human, prop, lease, "VACANT")
    correction = successor(migrated_database_url, lease, request)
    record(prop, lease, human, correction)
    before = snapshot(migrated_database_url)
    reader = AuthenticatedActor(
        str(human),
        frozenset({CapabilityGrant(AUDIT_VIEW_CAPABILITY, frozenset({str(prop)}))}),
    )
    query = PostgresAuditEventQueryFlow(runtime_database_url())
    pages = [
        query.search_property(
            reader,
            PropertyAuditQuery(
                prop,
                AuditPageRequest(limit=100),
                action="lease.move_out.record",
                unit_id=unit_id,
            ),
        ),
        query.resource_timeline(
            reader, ResourceAuditQuery("units", unit_id, AuditPageRequest(limit=100))
        ),
    ]
    for page in pages:
        events = [event for event in page.events if event.action == "lease.move_out.record"]
        views = [_event_view(event) for event in events]
        assert [value.resource_id for value in views] == [
            correction.event_id,
            request.event_id,
        ]
        for value in views:
            previous = cast(dict[str, object], value.previous_state)
            resulting = cast(dict[str, object], value.resulting_state)
            assert previous["unit_id"] == resulting["unit_id"] == str(unit_id)
            assert resulting["financial_completion_assessed"] is False
            assert "evidence_reference" not in resulting and "reason" not in resulting
        assert cast(dict[str, object], views[0].previous_state)["unit_status"] == "VACANT"
        assert cast(dict[str, object], views[0].resulting_state)["unit_status"] == "VACANT"
        assert cast(dict[str, object], views[1].resulting_state)["unit_status"] == "CLEANING"
    assert record(prop, lease, human, request) == original
    assert without_searches(snapshot(migrated_database_url)) == without_searches(before)


@pytest.mark.parametrize(
    "mismatch",
    [
        None,
        "missing_unit",
        "wrong_unit",
        "changed_evidence_status",
        "initial_availability",
        "substantive_availability",
    ],
)
def test_physical_completion_requires_unit_relation_and_preserved_evidence_state(
    migrated_database_url: str, mismatch: str | None
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    record(prop, lease, human, request)
    correction = successor(migrated_database_url, lease, request)
    if mismatch == "initial_availability":
        correction = replace(request, idempotency_key=uuid4(), event_id=uuid4())
    elif mismatch == "substantive_availability":
        correction = replace(correction, unit_condition="UNDER_MAINTENANCE")
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
        unit_id = cast(UUID, row[0])
        wrong_unit = uuid4()
        if mismatch == "wrong_unit":
            connection.execute(
                "INSERT INTO app.units(id,property_id,unit_number,floor,unit_"
                "type,status,created_by,updated_by) "
                "VALUES (%s,%s,%s,'1','ONE_BEDROOM','VACANT',%s,%s)",
                (wrong_unit, prop, "PD-" + wrong_unit.hex[:12], human, human),
            )
        previous = "OCCUPIED" if mismatch == "initial_availability" else "CLEANING"
        resulting = (
            "VACANT"
            if mismatch in {"initial_availability", "substantive_availability"}
            else "UNDER_MAINTENANCE"
            if mismatch == "changed_evidence_status"
            else "CLEANING"
        )
        changes = {
            "id": str(correction.event_id),
            "expected_lease_version": correction.expected_lease_version,
            "expected_unit_version": correction.expected_unit_version,
            "previous_unit_status": previous,
            "resulting_unit_status": resulting,
            "resulting_unit_version": correction.expected_unit_version + int(previous != resulting),
            "unit_condition": correction.unit_condition,
            "evidence_reference": correction.evidence_reference,
            "supersedes_event_id": str(correction.supersedes_event_id)
            if correction.supersedes_event_id
            else None,
        }
        connection.execute(
            "INSERT INTO app.physical_move_out_events SELECT (jsonb_popul"
            "ate_record(NULL::app.physical_move_out_events,to_jsonb(e)||%"
            "s)).* "
            "FROM app.physical_move_out_events e WHERE id=%s",
            (Jsonb(changes), request.event_id),
        )
        connection.execute(
            "INSERT INTO app.physical_move_out_occupancies SELECT %s,occu"
            "pancy_id,%s,resulting_version "
            "FROM app.physical_move_out_occupancies WHERE event_id=%s",
            (
                correction.event_id,
                correction.occupancies[0].expected_version,
                request.event_id,
            ),
        )
        audit_id = uuid4()
        audit_unit = (
            None
            if mismatch == "missing_unit"
            else wrong_unit
            if mismatch == "wrong_unit"
            else unit_id
        )
        connection.execute(
            "INSERT INTO app.audit_events(id,occurred_at,business_date,ac"
            "tor_id,action,entity_type,entity_id,reason,authorization_ref"
            "erence,property_id,previous_state,resulting_state,correlatio"
            "n_id,source,outcome,authorization_evidence,linked_source_eve"
            "nt_id,customer_id,lease_id,unit_id) "
            "SELECT %s,a.occurred_at,a.business_date,a.actor_id,a.action,"
            "a.entity_type,%s,a.reason,a.authorization_reference,a.proper"
            "ty_id,"
            "app.physical_move_out_audit_snapshot(%s,true),app.physical_m"
            "ove_out_audit_snapshot(%s,false),%s,a.source,a.outcome,%s,%s"
            ",a.customer_id,a.lease_id,%s "
            "FROM app.audit_events a JOIN app.physical_move_out_commands "
            "c ON c.audit_event_id=a.id WHERE c.event_id=%s",
            (
                audit_id,
                correction.event_id,
                correction.event_id,
                correction.event_id,
                correction.idempotency_key,
                Jsonb(
                    {
                        "capability": "leases.move_out",
                        "move_out_event_id": str(correction.event_id),
                    }
                ),
                correction.event_id,
                audit_unit,
                request.event_id,
            ),
        )
        connection.execute(
            "INSERT INTO app.physical_move_out_commands SELECT property_i"
            "d,actor_id,%s,lease_id,%s,%s,%s,%s,"
            "jsonb_set(response_body,'{data}',app.physical_move_out_snaps"
            "hot(%s)),occurred_at FROM app.physical_move_out_commands WHE"
            "RE event_id=%s",
            (
                correction.idempotency_key,
                correction.event_id,
                audit_id,
                physical_move_out_digest(prop, lease, correction.intent()),
                Jsonb(correction.intent()),
                correction.event_id,
                request.event_id,
            ),
        )
        if mismatch is None:
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            connection.rollback()
        else:
            message = (
                "audit evidence disagrees"
                if mismatch in {"missing_unit", "wrong_unit"}
                else "Unit transition disagrees"
            )
            with pytest.raises(psycopg.errors.CheckViolation, match=message):
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(migrated_database_url) == before
