"Real physical departures, original recovery, connected guards and additive storage."

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo
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
from property_rental.move_in import MoveInOccupant
from property_rental.physical_move_out import (
    MOVE_OUT_READ,
    MOVE_OUT_RECORD,
    EndedOccupancy,
    PhysicalMoveOutAuthorizationError,
    PhysicalMoveOutConflictError,
    PhysicalMoveOutKeyReused,
    PhysicalMoveOutNotFoundError,
    PhysicalMoveOutUtilityConflictError,
    PostgresPhysicalMoveOutService,
    RecordPhysicalMoveOut,
    physical_move_out_digest,
)
from property_rental.utility import UTILITY_CALCULATE_CAPABILITY
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import setup_historical_move_in
from test_termination_deposit_migration import history, terminate
from test_utility_consumption_migration import (
    authorized_actor,
    finalize_actual,
    service,
)
from test_utility_meter_migration import add_meter, add_reading

NEW_TABLES = {
    "physical_move_out_events",
    "physical_move_out_occupancies",
    "physical_move_out_commands",
}
MUTATED_TABLES = NEW_TABLES | {
    "occupancies",
    "occupancy_revisions",
    "units",
    "audit_events",
    "invoice_serialization_guards",
}


def flow() -> PostgresPhysicalMoveOutService:
    return PostgresPhysicalMoveOutService(runtime_database_url(), financial_database_url())


def actor(human: UUID, prop: UUID) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in (MOVE_OUT_READ, MOVE_OUT_RECORD)
        ),
    )


def source(
    url: str, *, count: int = 1, signer: bool = False
) -> tuple[UUID, UUID, UUID, RecordPhysicalMoveOut]:
    move_flow, staff, move = setup_historical_move_in(
        url, signed_day_offset=-1, receipt_day_offset=-1
    )
    human, prop, lease = move_flow.actor_id, move_flow.property_id, move.lease_id
    members = list(move.occupants)
    with psycopg.connect(url) as connection:
        if signer:
            row = connection.execute(
                "SELECT primary_tenant_id FROM app.leases WHERE id=%s", (lease,)
            ).fetchone()
            assert row is not None
            members = [MoveInOccupant(uuid4(), cast(UUID, row[0]))]
        for _ in range(count - 1):
            customer = uuid4()
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,'Additional synthetic occupant',%s,%s)",
                (customer, human, human),
            )
            members.append(MoveInOccupant(uuid4(), customer))
    move = replace(move, occupants=tuple(members))
    result = move_flow.complete(move, actor=staff)
    termination = terminate(url, human, prop, lease, move.actual_move_in_date + timedelta(days=2))
    with psycopg.connect(url) as connection:
        row = connection.execute(
            (
                "SELECT l.version,u.version FROM app.leases l JOIN app.units u ON u.i"
                "d=l.unit_id WHERE l.id=%s"
            ),
            (lease,),
        ).fetchone()
        assert row is not None
        request = RecordPhysicalMoveOut(
            uuid4(),
            uuid4(),
            termination,
            int(row[0]),
            int(row[1]),
            move.actual_move_in_date + timedelta(days=1),
            "CLEANING",
            tuple(EndedOccupancy(identity, 1) for identity in result.occupancy_ids),
            "Observed departure confirmed",
            "Authorized move-out",
            "Synthetic departure evidence",
        )
    return human, prop, lease, request


def snapshot(url: str) -> dict[str, list[tuple[object, ...]]]:
    with psycopg.connect(url) as connection:
        return history(connection)


def record(
    prop: UUID, lease: UUID, human: UUID, request: RecordPhysicalMoveOut
) -> dict[str, object]:
    return (
        flow()
        .record(prop, lease, request, actor=actor(human, prop), request_id="physical-test")
        .body
    )


def raw_record(
    connection: psycopg.Connection[tuple[object, ...]],
    prop: UUID,
    lease: UUID,
    human: UUID,
    request: RecordPhysicalMoveOut,
    *,
    intent: dict[str, object] | None = None,
) -> dict[str, object]:
    value = request.intent() if intent is None else intent
    row = connection.execute(
        "SELECT app.physical_move_out_record(%s,%s,%s,%s,%s,%s,%s)",
        (
            prop,
            lease,
            human,
            request.idempotency_key,
            physical_move_out_digest(prop, lease, value),
            Jsonb(value),
            "direct",
        ),
    ).fetchone()
    assert row is not None and isinstance(row[0], dict)
    return cast(dict[str, object], row[0])


def successor(
    url: str, lease: UUID, prior: RecordPhysicalMoveOut, *, date_change: bool = False
) -> RecordPhysicalMoveOut:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            (
                "SELECT l.version,u.version FROM app.leases l JOIN app.units u ON u.i"
                "d=l.unit_id WHERE l.id=%s"
            ),
            (lease,),
        ).fetchone()
        assert row is not None
        versions: dict[UUID, int] = dict(
            connection.execute("SELECT id,version FROM app.occupancies WHERE lease_id=%s", (lease,))
        )
    return replace(
        prior,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        supersedes_event_id=prior.event_id,
        expected_lease_version=int(row[0]),
        expected_unit_version=int(row[1]),
        occupancies=tuple(
            EndedOccupancy(item.occupancy_id, int(versions[item.occupancy_id]))
            for item in prior.occupancies
        ),
        actual_move_out_date=prior.actual_move_out_date + timedelta(days=int(date_change)),
        evidence_reference="Additional confirmed departure evidence",
    )


def test_physical_departure_changes_only_explicit_occupancies_and_condition(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url, count=2)
    before = snapshot(migrated_database_url)
    partial = replace(request, occupancies=request.occupancies[:1])
    original = record(prop, lease, human, partial)
    data = cast(dict[str, object], original["data"])
    assert data["resulting_unit_status"] == "OCCUPIED"
    assert data["resulting_unit_version"] == partial.expected_unit_version
    current = flow().read(prop, lease, actor=actor(human, prop))
    assert current["open_occupancy_count"] == 1
    assert current["financial_completion_assessed"] is False
    assert current["utility_completion_assessed"] is False
    assert current["final_inputs_status"] == "PENDING_RECONCILIATION"
    remaining = replace(
        request,
        idempotency_key=uuid4(),
        event_id=uuid4(),
        occupancies=request.occupancies[1:],
    )
    final = record(prop, lease, human, remaining)
    assert cast(dict[str, object], final["data"])["resulting_unit_status"] == "CLEANING"
    assert record(prop, lease, human, partial) == original
    after = snapshot(migrated_database_url)
    assert all(after[name] == rows for name, rows in before.items() if name not in MUTATED_TABLES)
    with psycopg.connect(migrated_database_url) as connection:
        assert (
            connection.execute(
                ("SELECT move_out_date,version FROM app.occupancies WHERE lease_id=%s ORDER BY id"),
                (lease,),
            ).fetchall()
            == [(request.actual_move_out_date, 2)] * 2
        )
        assert connection.execute(
            "SELECT count(*) FROM app.physical_move_out_events WHERE lease_id=%s",
            (lease,),
        ).fetchone() == (2,)
    before_read = snapshot(migrated_database_url)
    assert flow().read(prop, lease, actor=actor(human, prop), limit=1, offset=2)["items"] == []
    assert snapshot(migrated_database_url) == before_read


@pytest.mark.parametrize("condition", ["CLEANING", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"])
def test_physical_departure_uses_confirmed_nonavailable_condition(
    migrated_database_url: str, condition: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    result = record(prop, lease, human, replace(request, unit_condition=condition))
    assert cast(dict[str, object], result["data"])["resulting_unit_status"] == condition


@pytest.mark.parametrize("protected", ["UNDER_MAINTENANCE", "OUT_OF_SERVICE"])
def test_physical_departure_preserves_blocking_unit_condition(
    migrated_database_url: str, protected: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            (
                "UPDATE app.units SET status=%s,version=version+1,updated_at=clock_ti"
                "mestamp(),updated_by=%s WHERE id=(SELECT unit_id FROM app.leases WHE"
                "RE id=%s)"
            ),
            (protected, human, lease),
        )
    request = replace(request, expected_unit_version=request.expected_unit_version + 1)
    result = cast(dict[str, object], record(prop, lease, human, request)["data"])
    assert result["resulting_unit_status"] == protected
    assert result["resulting_unit_version"] == request.expected_unit_version


def test_physical_date_and_evidence_corrections_preserve_original_commands_and_revisions(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    original = record(prop, lease, human, request)
    corrected = successor(migrated_database_url, lease, request, date_change=True)
    corrected_result = record(prop, lease, human, corrected)
    evidence = successor(migrated_database_url, lease, corrected)
    before_evidence = snapshot(migrated_database_url)
    evidence_result = record(prop, lease, human, evidence)
    after_evidence = snapshot(migrated_database_url)
    for table in (
        "occupancies",
        "occupancy_revisions",
        "units",
        "invoice_serialization_guards",
    ):
        assert after_evidence[table] == before_evidence[table]
    before_replays = snapshot(migrated_database_url)
    for command, expected in (
        (request, original),
        (corrected, corrected_result),
        (evidence, evidence_result),
    ):
        assert record(prop, lease, human, command) == expected
    assert snapshot(migrated_database_url) == before_replays
    with pytest.raises(PhysicalMoveOutConflictError):
        record(prop, lease, human, successor(migrated_database_url, lease, request))
    page = flow().read(prop, lease, actor=actor(human, prop))
    items = cast(list[dict[str, object]], page["items"])
    assert [item["event_status"] for item in items] == [
        "CURRENT",
        "SUPERSEDED",
        "SUPERSEDED",
    ]
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            (
                "SELECT move_out_date,version FROM app.occupancy_revisions WHERE occu"
                "pancy_id=%s ORDER BY version"
            ),
            (request.occupancies[0].occupancy_id,),
        ).fetchall() == [
            (None, 1),
            (request.actual_move_out_date, 2),
            (corrected.actual_move_out_date, 3),
        ]


def test_physical_fresh_identity_scope_versions_and_termination_evidence(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    invalid = [
        replace(request, termination_event_id=uuid4()),
        replace(request, expected_lease_version=request.expected_lease_version + 1),
        replace(request, expected_unit_version=request.expected_unit_version + 1),
        replace(request, occupancies=(replace(request.occupancies[0], expected_version=2),)),
        replace(
            request,
            actual_move_out_date=request.actual_move_out_date + timedelta(days=2),
        ),
        replace(
            request,
            actual_move_out_date=request.actual_move_out_date - timedelta(days=2),
        ),
    ]
    for value in invalid:
        with pytest.raises(PhysicalMoveOutConflictError):
            record(prop, lease, human, value)
    wrong = uuid4()
    with pytest.raises(PhysicalMoveOutNotFoundError):
        record(wrong, lease, human, request)
    with pytest.raises(PhysicalMoveOutNotFoundError):
        record(
            prop,
            lease,
            human,
            replace(request, occupancies=(EndedOccupancy(uuid4(), 1),)),
        )
    assert snapshot(migrated_database_url) == before
    record(prop, lease, human, request)
    with pytest.raises(PhysicalMoveOutKeyReused):
        record(prop, lease, human, replace(request, reason="Changed original command"))
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
            (human,),
        )
    disabled = snapshot(migrated_database_url)
    with pytest.raises(PhysicalMoveOutAuthorizationError):
        record(prop, lease, human, request)
    with pytest.raises(PhysicalMoveOutAuthorizationError):
        flow().read(prop, lease, actor=actor(human, prop))
    assert snapshot(migrated_database_url) == disabled


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_unit_version": True},
        {"expected_lease_version": 2147483648},
        {"actual_move_out_date": "2026-02-30"},
        {"termination_event_id": "invalid"},
        {"reason": None},
        {"reason": 123},
        {"evidence_reference": " x"},
        {"unexpected": True},
        {"unit_condition": "VACANT"},
        {"occupancies": []},
        {"occupancies": [{"occupancy_id": str(uuid4()), "expected_version": True}]},
    ],
)
def test_physical_direct_intent_validation_rolls_back_every_effect(
    migrated_database_url: str, patch: dict[str, object]
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as error:
            raw_record(connection, prop, lease, human, request, intent=request.intent() | patch)
        assert error.value.sqlstate == "P5N02"
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
def test_physical_complete_commands_and_exact_replays_work_in_both_constraint_modes(
    migrated_database_url: str, mode: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        original = raw_record(connection, prop, lease, human, request)
        correction = replace(
            request,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            supersedes_event_id=request.event_id,
            expected_unit_version=request.expected_unit_version + 1,
            occupancies=tuple(replace(item, expected_version=2) for item in request.occupancies),
            evidence_reference="Additional evidence in same transaction",
        )
        corrected = raw_record(connection, prop, lease, human, correction)
        assert raw_record(connection, prop, lease, human, request) == original
        assert raw_record(connection, prop, lease, human, correction) == corrected
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    before = snapshot(migrated_database_url)
    with psycopg.connect(financial_database_url()) as connection:
        connection.execute("SET CONSTRAINTS ALL " + mode)
        assert raw_record(connection, prop, lease, human, request) == original
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("lock", ["lease", "unit", "occupancy", "invoice", "utility"])
def test_physical_conflicts_with_held_legacy_source_locks_without_partial_writes(
    migrated_database_url: str, lock: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as held:
        if lock == "lease":
            held.execute("SELECT id FROM app.leases WHERE id=%s FOR UPDATE", (lease,))
        elif lock == "unit":
            held.execute(
                (
                    "SELECT id FROM app.units WHERE id=(SELECT unit_id FROM app.leases WH"
                    "ERE id=%s) FOR UPDATE"
                ),
                (lease,),
            )
        elif lock == "occupancy":
            held.execute(
                "SELECT id FROM app.occupancies WHERE id=%s FOR UPDATE",
                (request.occupancies[0].occupancy_id,),
            )
        else:
            key = (
                f"invoice-lease:{lease}"
                if lock == "invoice"
                else f"utility-property-type:{prop}:ELECTRICITY"
            )
            held.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        with pytest.raises(PhysicalMoveOutConflictError):
            record(prop, lease, human, request)
    assert snapshot(migrated_database_url) == before
    assert cast(dict[str, object], record(prop, lease, human, request)["data"])["event_id"] == str(
        request.event_id
    )


@pytest.mark.parametrize("same_key", [True, False])
def test_competing_physical_commands_commit_one_event_and_preserve_exact_recovery(
    migrated_database_url: str, same_key: bool
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    alternative = (
        request if same_key else replace(request, idempotency_key=uuid4(), event_id=uuid4())
    )
    barrier = Barrier(2)

    def submit(value: RecordPhysicalMoveOut) -> dict[str, object] | None:
        barrier.wait(timeout=10)
        try:
            return record(prop, lease, human, value)
        except PhysicalMoveOutConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, value) for value in (request, alternative)]
        results = [future.result(timeout=15) for future in futures]
    successful = [value for value in results if value is not None]
    assert len(successful) >= 1
    if same_key:
        assert all(value == successful[0] for value in successful)
        assert record(prop, lease, human, request) == successful[0]
    else:
        assert len(successful) == 1
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.physical_move_out_events WHERE lease_id=%s",
            (lease,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT version FROM app.occupancies WHERE lease_id=%s", (lease,)
        ).fetchone() == (2,)


def test_signer_departure_rolls_back_when_existing_actual_utility_period_crosses_boundary(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url, signer=True)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
        unit = cast(UUID, row[0])
        meter = add_meter(
            connection,
            actor_id=human,
            unit_id=unit,
            installed_date=request.actual_move_out_date - timedelta(days=1),
        )
        readings = tuple(
            add_reading(
                connection,
                actor_id=human,
                meter_id=meter,
                reading_date=request.actual_move_out_date + timedelta(days=offset),
                reading_value=str(value),
            )
            for offset, value in ((-1, 0), (1, 10))
        )
    period, _ = finalize_actual(
        service(prop, human),
        authorized_actor(human, prop, UTILITY_CALCULATE_CAPABILITY),
        unit,
        readings[0],
        readings[1],
    )
    before = snapshot(migrated_database_url)
    with pytest.raises(PhysicalMoveOutUtilityConflictError):
        record(prop, lease, human, request)
    assert snapshot(migrated_database_url) == before
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.utility_consumption_periods WHERE id=%s",
            (period,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT move_out_date,version FROM app.occupancies WHERE lease_id=%s",
            (lease,),
        ).fetchone() == (None, 1)


def test_physical_audit_round_trips_through_property_lease_and_customer_consumers(
    migrated_database_url: str,
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    record(prop, lease, human, request)
    correction = successor(migrated_database_url, lease, request, date_change=True)
    record(prop, lease, human, correction)
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
    query = PostgresAuditEventQueryFlow(runtime_database_url())
    pages = [
        query.search_property(
            reader,
            PropertyAuditQuery(prop, AuditPageRequest(limit=2), action="lease.move_out.record"),
        ),
        *(
            query.resource_timeline(
                reader, ResourceAuditQuery(kind, identity, AuditPageRequest(limit=2))
            )
            for kind, identity in (("leases", lease), ("customers", customer))
        ),
    ]
    for page in pages:
        assert len(page.events) == 2
        values = [_event_view(event) for event in page.events]
        assert [item.resource_id for item in values] == [
            correction.event_id,
            request.event_id,
        ]
        for item in values:
            assert item.previous_state is not None and item.resulting_state is not None
            state = cast(dict[str, object], item.resulting_state)
            assert state["financial_completion_assessed"] is False
            assert state["move_out_event_id"] == str(item.resource_id)


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_physical_event_history_and_runtime_permissions_are_append_preserved(
    migrated_database_url: str, table: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    record(prop, lease, human, request)
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        for statement in (f"DELETE FROM app.{table}", f"TRUNCATE app.{table} CASCADE"):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(statement)
    for url in (runtime_database_url(), financial_database_url()):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM app.{table}")
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize("mode", ["IMMEDIATE", "DEFERRED"])
def test_physical_incomplete_event_rejected_without_changing_completed_evidence(
    migrated_database_url: str, mode: str
) -> None:
    human, prop, lease, request = source(migrated_database_url)
    record(prop, lease, human, request)
    before = snapshot(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("SET CONSTRAINTS ALL " + mode)
            connection.execute(
                (
                    "INSERT INTO app.physical_move_out_events SELECT %s,property_id,lease"
                    "_id,unit_id,termination_event_id,expected_lease_version,expected_uni"
                    "t_version,actual_move_out_date,unit_condition,previous_unit_status,r"
                    "esulting_unit_status,resulting_unit_version,reason,authorization_ref"
                    "erence,evidence_reference,NULL,occurred_at,actor_id FROM app.physica"
                    "l_move_out_events WHERE id=%s"
                ),
                (uuid4(), request.event_id),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert snapshot(migrated_database_url) == before


def test_forward61_preserves_all60_rows_functions_constraints_and_permissions(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert migrated_database_url
    queries = [
        (
            "SELECT p.oid,pg_get_functiondef(p.oid),p.proacl::text,p.proowner FRO"
            "M pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspn"
            "ame='app' AND p.prokind='f' ORDER BY p.oid"
        ),
        (
            "SELECT c.oid,c.relacl::text,c.relowner FROM pg_class c JOIN pg_names"
            "pace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind='"
            "r' ORDER BY c.oid"
        ),
        (
            "SELECT con.oid,pg_get_constraintdef(con.oid) FROM pg_constraint con "
            "JOIN pg_namespace n ON n.oid=con.connamespace WHERE n.nspname='app' "
            "ORDER BY con.oid"
        ),
    ]
    with (
        _temporary_migration_database("physical_departure") as temporary,
        monkeypatch.context() as environment,
    ):
        name = conninfo_to_dict(temporary)["dbname"]
        environment.setenv("APP_DATABASE_URL", make_conninfo(runtime_database_url(), dbname=name))
        environment.setenv(
            "FINANCIAL_DATABASE_URL",
            make_conninfo(financial_database_url(), dbname=name),
        )
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        alembic_command.upgrade(config, "20260915_60")
        human, prop, lease, request = source(temporary)
        with psycopg.connect(temporary) as connection:
            before = history(connection)
            catalogs = [{row[0]: row[1:] for row in connection.execute(query)} for query in queries]
        alembic_command.upgrade(config, "20260915_61")
        with psycopg.connect(temporary) as connection:
            after = history(connection)
            assert all(after[table] == rows for table, rows in before.items())
            assert set(after) - set(before) == NEW_TABLES
            for query, catalog in zip(queries, catalogs, strict=True):
                current = {row[0]: row[1:] for row in connection.execute(query)}
                assert all(current[key] == value for key, value in catalog.items())
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260915_61",
            )
        assert cast(dict[str, object], record(prop, lease, human, request)["data"])[
            "event_id"
        ] == str(request.event_id)
