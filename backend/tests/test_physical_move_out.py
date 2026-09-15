"""Explicit ended members, source-bound recovery and scoped physical commands."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.physical_move_out import (
    MOVE_OUT_READ,
    MOVE_OUT_RECORD,
    EndedOccupancy,
    PhysicalMoveOutAuthorizationError,
    PhysicalMoveOutConflictError,
    PhysicalMoveOutInvalidError,
    PhysicalMoveOutNotFoundError,
    PhysicalMoveOutUnavailableError,
    PostgresPhysicalMoveOutService,
    RecordPhysicalMoveOut,
    physical_move_out_digest,
)


def departure() -> RecordPhysicalMoveOut:
    return RecordPhysicalMoveOut(
        uuid4(),
        uuid4(),
        uuid4(),
        4,
        3,
        date(2026, 9, 14),
        "CLEANING",
        (EndedOccupancy(uuid4(), 1),),
        "Recorded physical departure",
        "Authorized move-out",
        "Observed departure evidence",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("idempotency_key", UUID(int=0)),
        ("event_id", "invalid"),
        ("termination_event_id", UUID(int=0)),
        ("expected_lease_version", True),
        ("expected_lease_version", 0),
        ("expected_unit_version", 1.0),
        ("expected_unit_version", 2147483648),
        ("actual_move_out_date", "2026-09-14"),
        ("actual_move_out_date", datetime(2026, 9, 14)),
        ("unit_condition", "VACANT"),
        ("unit_condition", "OCCUPIED"),
        ("unit_condition", None),
        ("occupancies", ()),
        ("occupancies", []),
        ("occupancies", ({},)),
        ("reason", ""),
        ("reason", "x\x00y"),
        ("reason", "x" * 501),
        ("evidence_reference", " x"),
        ("authorization_reference", None),
        ("supersedes_event_id", UUID(int=0)),
    ],
)
def test_physical_departure_rejects_invalid_or_mutable_intent(field: str, value: object) -> None:
    with pytest.raises(PhysicalMoveOutInvalidError):
        replace(departure(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "identity,version",
    [(UUID(int=0), 1), (uuid4(), True), (uuid4(), 0), (uuid4(), 2147483648)],
)
def test_ended_occupancy_requires_real_identity_and_exact_version(
    identity: UUID, version: int
) -> None:
    with pytest.raises(PhysicalMoveOutInvalidError):
        EndedOccupancy(identity, version)


def test_physical_member_bounds_order_and_complete_correction_intent() -> None:
    request = departure()
    members = tuple(EndedOccupancy(uuid4(), 1) for _ in range(20))
    largest = replace(request, occupancies=members)
    assert largest.intent() == replace(largest, occupancies=tuple(reversed(members))).intent()
    for bad in ((members[0], members[0]), (*members, EndedOccupancy(uuid4(), 1))):
        with pytest.raises(PhysicalMoveOutInvalidError):
            replace(request, occupancies=bad)
    with pytest.raises(PhysicalMoveOutInvalidError):
        replace(request, supersedes_event_id=request.event_id)
    prop, lease = uuid4(), uuid4()
    intent = largest.intent()
    digest = physical_move_out_digest(prop, lease, intent)
    assert digest == physical_move_out_digest(prop, lease, dict(reversed(list(intent.items()))))
    assert digest != physical_move_out_digest(uuid4(), lease, intent)
    assert digest != physical_move_out_digest(prop, uuid4(), intent)
    for field in intent:
        assert digest != physical_move_out_digest(prop, lease, intent | {field: "changed"})
    assert replace(largest, idempotency_key=uuid4()).intent() == intent


@pytest.mark.parametrize("capability", [MOVE_OUT_READ, "leases.terminate", "leases.inspect"])
def test_physical_record_requires_exact_capability_before_connection(
    capability: str,
) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(capability, frozenset({str(prop)}))})
    )
    with pytest.raises(PhysicalMoveOutAuthorizationError):
        PostgresPhysicalMoveOutService("unused", "unused").record(
            prop, uuid4(), departure(), actor=actor, request_id="test"
        )


def test_physical_property_read_scope_and_missing_writer_are_fail_closed() -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()),
        frozenset({CapabilityGrant(MOVE_OUT_RECORD, frozenset({str(prop)}))}),
    )
    flow = PostgresPhysicalMoveOutService("unused")
    with pytest.raises(PhysicalMoveOutNotFoundError):
        flow.read(prop, uuid4(), actor=actor)
    with pytest.raises(PhysicalMoveOutAuthorizationError):
        flow.record(uuid4(), uuid4(), departure(), actor=actor, request_id="test")
    with pytest.raises(PhysicalMoveOutUnavailableError):
        flow.record(prop, uuid4(), departure(), actor=actor, request_id="test")


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (21, 0), (True, 0), (1, -1), (1, 1000001), (1, True)]
)
def test_physical_reads_enforce_bounded_pages(limit: int, offset: int) -> None:
    with pytest.raises(PhysicalMoveOutInvalidError):
        PostgresPhysicalMoveOutService("unused").read(
            uuid4(),
            uuid4(),
            actor=AuthenticatedActor(str(uuid4())),
            limit=limit,
            offset=offset,
        )


@pytest.mark.parametrize("request_id", ["", "x" * 129, " x", "x\ny", "x/y"])
def test_physical_request_identity_is_bounded(request_id: str) -> None:
    with pytest.raises(PhysicalMoveOutInvalidError):
        PostgresPhysicalMoveOutService("unused").record(
            uuid4(),
            uuid4(),
            departure(),
            actor=AuthenticatedActor(str(uuid4())),
            request_id=request_id,
        )


@pytest.mark.parametrize("state", ["23505", "23514", "57014", "08006"])
def test_uncertain_physical_outcomes_require_original_command_recovery(
    state: str,
) -> None:
    assert isinstance(
        PostgresPhysicalMoveOutService._error(psycopg.errors.lookup(state)("Synthetic failure")),
        PhysicalMoveOutUnavailableError,
    )


@pytest.mark.parametrize("state", ["40001", "40P01", "55P03"])
def test_physical_source_contention_is_explicit_without_automatic_retry(
    state: str,
) -> None:
    assert isinstance(
        PostgresPhysicalMoveOutService._error(psycopg.errors.lookup(state)("Synthetic contention")),
        PhysicalMoveOutConflictError,
    )
