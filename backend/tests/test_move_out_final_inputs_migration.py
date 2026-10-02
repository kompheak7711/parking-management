"""Final Utility inputs reference existing Readings without creating readings or charges."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_final_inputs import (
    FINAL_INPUTS_READ,
    FINAL_INPUTS_RECORD,
    FinalInputItem,
    MoveOutFinalInputsAuthorizationError,
    MoveOutFinalInputsConflictError,
    MoveOutFinalInputsInvalidError,
    MoveOutFinalInputsKeyReused,
    MoveOutFinalInputsNotFoundError,
    PostgresMoveOutFinalInputsService,
    RecordMoveOutFinalInputs,
)
from property_rental.physical_move_out import RecordPhysicalMoveOut
from test_invoice import mutation_headers
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_payment_api_migration import api
from test_physical_move_out_migration import record as record_departure
from test_physical_move_out_migration import snapshot
from test_physical_move_out_migration import source as departure_source
from test_physical_move_out_migration import successor as departure_successor
from test_utility_meter_migration import add_meter, add_reading

NEW_TABLES = {
    "move_out_final_input_events",
    "move_out_final_input_items",
    "move_out_final_input_commands",
}
EXPECTED_CHANGES = NEW_TABLES | {"audit_events"}


@dataclass(frozen=True)
class Departure:
    human: UUID
    prop: UUID
    lease: UUID
    unit: UUID
    physical_event: UUID
    move_out_date: date
    electricity: UUID
    water: UUID
    request: RecordPhysicalMoveOut


def flow() -> PostgresMoveOutFinalInputsService:
    return PostgresMoveOutFinalInputsService(runtime_database_url(), financial_database_url())


def actor(human: UUID, prop: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(human),
        frozenset(
            CapabilityGrant(capability, frozenset({str(prop)}))
            for capability in (capabilities or (FINAL_INPUTS_READ, FINAL_INPUTS_RECORD))
        ),
    )


def departure(url: str) -> Departure:
    human, prop, lease, request = departure_source(url)
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT unit_id FROM app.leases WHERE id=%s", (lease,)).fetchone()
        assert row is not None
        unit = cast(UUID, row[0])
        installed = request.actual_move_out_date - timedelta(days=1)
        electricity = add_meter(connection, actor_id=human, unit_id=unit, installed_date=installed)
        water = add_meter(
            connection,
            actor_id=human,
            unit_id=unit,
            utility_type="WATER",
            measurement_unit_code="M3",
            installed_date=installed,
        )
    record_departure(prop, lease, human, request)
    return Departure(
        human,
        prop,
        lease,
        unit,
        request.event_id,
        request.actual_move_out_date,
        electricity,
        water,
        request,
    )


def reading(
    url: str, source: Departure, meter: UUID, *, day: date | None = None, validated: bool = True
) -> UUID:
    with psycopg.connect(url) as connection:
        return add_reading(
            connection,
            actor_id=source.human,
            meter_id=meter,
            reading_date=day or source.move_out_date,
            reading_value="100",
            validated=validated,
        )


def missing(meter: UUID) -> FinalInputItem:
    return FinalInputItem(meter, "UNRESOLVED", unresolved_reason="MISSING_READING")


def used(meter: UUID, reading_id: UUID) -> FinalInputItem:
    return FinalInputItem(meter, "READING", reading_id=reading_id)


def command(
    source: Departure,
    items: tuple[FinalInputItem, ...],
    *,
    supersedes: UUID | None = None,
    physical_event: UUID | None = None,
    key: UUID | None = None,
    event: UUID | None = None,
) -> RecordMoveOutFinalInputs:
    return RecordMoveOutFinalInputs(
        key or uuid4(),
        event or uuid4(),
        physical_event or source.physical_event,
        items,
        "Final Utility inputs reviewed",
        "Authorized move-out",
        "Synthetic final input evidence",
        supersedes,
    )


def record(source: Departure, value: RecordMoveOutFinalInputs) -> dict[str, object]:
    return (
        flow()
        .record(
            source.prop,
            source.lease,
            value,
            actor=actor(source.human, source.prop),
            request_id="final-inputs-test",
        )
        .body
    )


def changed(
    before: dict[str, list[tuple[object, ...]]], after: dict[str, list[tuple[object, ...]]]
) -> set[str]:
    return {table for table in before if before[table] != after[table]}


def data_of(body: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], body["data"])


def test_final_reading_is_referenced_and_missing_reading_stays_explicit(
    migrated_database_url: str,
) -> None:
    source = departure(migrated_database_url)
    reading_id = reading(migrated_database_url, source, source.electricity)
    before = snapshot(migrated_database_url)
    body = record(
        source,
        command(source, (used(source.electricity, reading_id), missing(source.water))),
    )
    data = data_of(body)
    assert data["final_inputs_status"] == "PENDING_RECONCILIATION"
    assert data["unresolved_item_count"] == 1
    assert data["creates_reading"] is False and data["creates_charge"] is False
    assert data["utility_completion_assessed"] is False
    assert data["financial_completion_assessed"] is False
    items = cast(list[dict[str, object]], data["items"])
    by_meter = {item["meter_id"]: item for item in items}
    electricity = by_meter[str(source.electricity)]
    assert electricity["resolution"] == "READING"
    assert cast(dict[str, object], electricity["reading"])["reading_value"] == "100.000000"
    assert by_meter[str(source.water)]["unresolved_reason"] == "MISSING_READING"
    after = snapshot(migrated_database_url)
    assert changed(before, after) == EXPECTED_CHANGES
    page = flow().read(source.prop, source.lease, actor=actor(source.human, source.prop))
    assert page["total"] == 1 and page["creates_charge"] is False
    listed = cast(list[dict[str, object]], page["items"])[0]
    assert listed["event_status"] == "CURRENT" and listed["physical_event_status"] == "CURRENT"
    assert listed["changed_reading_meter_ids"] == []


def test_successor_completes_inputs_and_preserves_the_original_evidence(
    migrated_database_url: str,
) -> None:
    source = departure(migrated_database_url)
    reading_id = reading(migrated_database_url, source, source.electricity)
    first = command(source, (used(source.electricity, reading_id), missing(source.water)))
    record(source, first)
    water_reading = reading(migrated_database_url, source, source.water)
    second = command(
        source,
        (used(source.electricity, reading_id), used(source.water, water_reading)),
        supersedes=first.event_id,
    )
    data = data_of(record(source, second))
    assert data["final_inputs_status"] == "INPUTS_RECORDED"
    assert data["unresolved_item_count"] == 0
    assert data["supersedes_event_id"] == str(first.event_id)
    page = flow().read(source.prop, source.lease, actor=actor(source.human, source.prop))
    statuses = {
        cast(str, item["event_id"]): item["event_status"]
        for item in cast(list[dict[str, object]], page["items"])
    }
    assert statuses == {str(first.event_id): "SUPERSEDED", str(second.event_id): "CURRENT"}
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.move_out_final_input_events WHERE lease_id=%s",
            (source.lease,),
        ).fetchone() == (2,)
    with pytest.raises(MoveOutFinalInputsConflictError):
        record(
            source,
            command(
                source,
                (used(source.electricity, reading_id), used(source.water, water_reading)),
                supersedes=first.event_id,
            ),
        )
    with pytest.raises(MoveOutFinalInputsConflictError):
        record(
            source,
            command(
                source,
                (used(source.electricity, reading_id), missing(source.water)),
            ),
        )


def test_replay_returns_the_saved_response_and_key_reuse_is_rejected(
    migrated_database_url: str,
) -> None:
    source = departure(migrated_database_url)
    items = (missing(source.electricity), missing(source.water))
    value = command(source, items)
    first = record(source, value)
    before = snapshot(migrated_database_url)
    assert record(source, value) == first
    assert snapshot(migrated_database_url) == before
    reused = replace(value, evidence_reference="Different evidence")
    with pytest.raises(MoveOutFinalInputsKeyReused):
        record(source, reused)
    assert snapshot(migrated_database_url) == before


@pytest.mark.parametrize(
    "case,error",
    [
        ("unvalidated_reading", MoveOutFinalInputsInvalidError),
        ("reading_on_another_date", MoveOutFinalInputsInvalidError),
        ("reading_of_another_meter", MoveOutFinalInputsNotFoundError),
        ("missing_meter_coverage", MoveOutFinalInputsInvalidError),
        ("missing_reason_contradicted", MoveOutFinalInputsInvalidError),
        ("missing_reason_with_validated_reading", MoveOutFinalInputsInvalidError),
        ("not_validated_reason_contradicted", MoveOutFinalInputsInvalidError),
        ("pending_estimate_for_working_meter", MoveOutFinalInputsInvalidError),
        ("unknown_estimate", MoveOutFinalInputsNotFoundError),
        ("unknown_physical_departure", MoveOutFinalInputsNotFoundError),
        ("unknown_correction_source", MoveOutFinalInputsNotFoundError),
    ],
)
def test_unsupported_final_inputs_are_rejected_without_partial_writes(
    migrated_database_url: str, case: str, error: type[Exception]
) -> None:
    source = departure(migrated_database_url)
    other = missing(source.water)
    items: tuple[FinalInputItem, ...]
    physical: UUID | None = None
    supersedes: UUID | None = None
    if case == "unvalidated_reading":
        item = used(
            source.electricity,
            reading(migrated_database_url, source, source.electricity, validated=False),
        )
        items = (item, other)
    elif case == "reading_on_another_date":
        early = reading(
            migrated_database_url,
            source,
            source.electricity,
            day=source.move_out_date - timedelta(days=1),
        )
        items = (used(source.electricity, early), other)
    elif case == "reading_of_another_meter":
        water_reading = reading(migrated_database_url, source, source.water)
        items = (used(source.electricity, water_reading), used(source.water, water_reading))
    elif case == "missing_meter_coverage":
        items = (missing(source.electricity),)
    elif case == "missing_reason_contradicted":
        reading(migrated_database_url, source, source.electricity)
        items = (missing(source.electricity), other)
    elif case == "missing_reason_with_validated_reading":
        reading(migrated_database_url, source, source.electricity)
        water_reading = reading(migrated_database_url, source, source.water)
        items = (missing(source.electricity), used(source.water, water_reading))
    elif case == "not_validated_reason_contradicted":
        items = (
            FinalInputItem(
                source.electricity, "UNRESOLVED", unresolved_reason="READING_NOT_VALIDATED"
            ),
            other,
        )
    elif case == "pending_estimate_for_working_meter":
        items = (
            FinalInputItem(
                source.electricity,
                "UNRESOLVED",
                unresolved_reason="BROKEN_METER_ESTIMATE_PENDING",
            ),
            other,
        )
    elif case == "unknown_estimate":
        items = (FinalInputItem(source.electricity, "ESTIMATE", estimate_id=uuid4()), other)
    else:
        items = (missing(source.electricity), other)
        if case == "unknown_physical_departure":
            physical = uuid4()
        else:
            supersedes = uuid4()
    before = snapshot(migrated_database_url)
    with pytest.raises(error) as rejected:
        record(source, command(source, items, physical_event=physical, supersedes=supersedes))
    if case == "missing_reason_with_validated_reading":
        assert "Unresolved reason is not supported by current Utility evidence" in str(
            rejected.value.__cause__
        )
    assert snapshot(migrated_database_url) == before


def test_recording_requires_the_current_physical_departure(
    migrated_database_url: str,
) -> None:
    source = departure(migrated_database_url)
    correction = departure_successor(migrated_database_url, source.lease, source.request)
    record_departure(source.prop, source.lease, source.human, correction)
    items = (missing(source.electricity), missing(source.water))
    before = snapshot(migrated_database_url)
    with pytest.raises(MoveOutFinalInputsConflictError):
        record(source, command(source, items))
    assert snapshot(migrated_database_url) == before
    current = record(source, command(source, items, physical_event=correction.event_id))
    assert data_of(current)["move_out_event_id"] == str(correction.event_id)
    page = flow().read(source.prop, source.lease, actor=actor(source.human, source.prop))
    listed = cast(list[dict[str, object]], page["items"])[0]
    assert listed["physical_event_status"] == "CURRENT"


def test_capabilities_and_property_scope_are_required(migrated_database_url: str) -> None:
    source = departure(migrated_database_url)
    items = (missing(source.electricity), missing(source.water))
    before = snapshot(migrated_database_url)
    with pytest.raises(MoveOutFinalInputsAuthorizationError):
        flow().record(
            source.prop,
            source.lease,
            command(source, items),
            actor=actor(source.human, source.prop, FINAL_INPUTS_READ),
            request_id="final-inputs-test",
        )
    with pytest.raises(MoveOutFinalInputsNotFoundError):
        flow().read(
            source.prop,
            source.lease,
            actor=AuthenticatedActor(str(source.human), frozenset()),
        )
    with pytest.raises(MoveOutFinalInputsNotFoundError):
        flow().read(
            source.prop,
            source.lease,
            actor=actor(source.human, uuid4()),
        )
    with pytest.raises(MoveOutFinalInputsNotFoundError):
        flow().read(
            uuid4(),
            source.lease,
            actor=actor(source.human, source.prop),
        )
    assert snapshot(migrated_database_url) == before


def test_final_input_storage_is_append_only_and_role_bounded(migrated_database_url: str) -> None:
    source = departure(migrated_database_url)
    record(source, command(source, (missing(source.electricity), missing(source.water))))
    columns = {
        "move_out_final_input_events": "property_id",
        "move_out_final_input_items": "event_id",
        "move_out_final_input_commands": "property_id",
    }
    for table, column in columns.items():
        name = sql.Identifier(table)
        for statement in (
            sql.SQL("UPDATE app.{} SET {}={}").format(
                name, sql.Identifier(column), sql.Identifier(column)
            ),
            sql.SQL("DELETE FROM app.{}").format(name),
            sql.SQL("TRUNCATE app.{}").format(name),
        ):
            with psycopg.connect(migrated_database_url) as connection:
                with pytest.raises(psycopg.Error):
                    connection.execute(statement)
    for url in (runtime_database_url(), financial_database_url()):
        for table in NEW_TABLES:
            with psycopg.connect(url) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        sql.SQL("SELECT count(*) FROM app.{}").format(sql.Identifier(table))
                    )
    with psycopg.connect(runtime_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.move_out_final_inputs_record(%s,%s,%s,%s,%s,%s,%s)",
                (uuid4(), uuid4(), uuid4(), uuid4(), "0" * 64, "{}", "direct"),
            )
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT app.move_out_final_inputs_read(%s,%s,%s,%s,%s)",
                (uuid4(), uuid4(), uuid4(), 1, 0),
            )


def test_concurrent_first_records_allow_exactly_one(migrated_database_url: str) -> None:
    source = departure(migrated_database_url)
    items = (missing(source.electricity), missing(source.water))
    barrier = Barrier(2)

    def attempt() -> object:
        value = command(source, items)
        barrier.wait(timeout=10)
        try:
            return record(source, value)
        except MoveOutFinalInputsConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(attempt) for _ in range(2)]]
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, MoveOutFinalInputsConflictError) for result in results) == 1
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.move_out_final_input_events WHERE lease_id=%s",
            (source.lease,),
        ).fetchone() == (1,)


def test_final_input_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20260917_63")
    assert revision is not None and revision.down_revision == "20260915_61"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


def test_final_input_routes_record_replay_read_and_need_the_move_out_capability(
    migrated_database_url: str,
) -> None:
    source = departure(migrated_database_url)
    reading_id = reading(migrated_database_url, source, source.electricity)
    path = f"/api/v1/properties/{source.prop}/leases/{source.lease}/move-out-final-utility-inputs"
    body = {
        "event_id": str(uuid4()),
        "move_out_event_id": str(source.physical_event),
        "reason": "Final Utility inputs reviewed",
        "authorization_reference": "Authorized move-out",
        "evidence_reference": "Synthetic final input evidence",
        "items": [
            {
                "meter_id": str(source.electricity),
                "resolution": "READING",
                "reading_id": str(reading_id),
            },
            {
                "meter_id": str(source.water),
                "resolution": "UNRESOLVED",
                "unresolved_reason": "MISSING_READING",
            },
        ],
    }
    key = uuid4()
    client = api(actor(source.human, source.prop))
    reply = client.post(path, json=body, headers=mutation_headers(key=key))
    assert reply.status_code == 201, reply.text
    assert reply.headers["cache-control"] == "private, no-store"
    data = reply.json()["data"]
    assert data["final_inputs_status"] == "PENDING_RECONCILIATION"
    assert data["creates_reading"] is False and data["creates_charge"] is False
    replay = client.post(path, json=body, headers=mutation_headers(key=key))
    assert replay.status_code == 201 and replay.json() == reply.json()
    reused = client.post(
        path, json={**body, "reason": "Another reason"}, headers=mutation_headers(key=key)
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    listed = client.get(path)
    assert listed.status_code == 200 and body["event_id"] in listed.text
    reader = api(actor(source.human, source.prop, FINAL_INPUTS_READ))
    assert reader.post(path, json=body, headers=mutation_headers()).status_code == 403
    assert api(actor(source.human, source.prop, "invoices.read")).get(path).status_code == 404
    invalid = {
        **body,
        "event_id": str(uuid4()),
        "items": [
            {"meter_id": str(source.water), "resolution": "READING", "unresolved_reason": "X"}
        ],
    }
    assert client.post(path, json=invalid, headers=mutation_headers()).status_code == 422
