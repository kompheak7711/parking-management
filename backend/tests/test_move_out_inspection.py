"""Strict operational evidence, source-bound intent and conservative recovery."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_out_inspection import (
    INSPECTION_READ,
    INSPECTION_RECORD,
    InspectionFinding,
    MoveOutInspectionAuthorizationError,
    MoveOutInspectionConflictError,
    MoveOutInspectionInvalidError,
    MoveOutInspectionNotFoundError,
    MoveOutInspectionUnavailableError,
    PostgresMoveOutInspectionService,
    RecordMoveOutInspection,
    inspection_request_digest,
)


def inspection() -> RecordMoveOutInspection:
    return RecordMoveOutInspection(
        uuid4(),
        uuid4(),
        2,
        date(2026, 9, 15),
        "Recorded condition",
        "Management approval",
        "Inspection evidence",
        "Record findings",
        (InspectionFinding(uuid4(), "Observed door condition", False),),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("idempotency_key", UUID(int=0)),
        ("inspection_id", "invalid"),
        ("expected_lease_version", True),
        ("expected_lease_version", 1.0),
        ("expected_lease_version", 0),
        ("expected_lease_version", 2147483648),
        ("inspection_date", datetime(2026, 9, 15)),
        ("inspection_date", "2026-09-15"),
        ("result_text", ""),
        ("result_text", "x" * 5001),
        ("result_text", "\u2003x"),
        ("reason", "x\x00y"),
        ("evidence_reference", "x "),
        ("authorization_reference", None),
        ("authorization_reference", "x" * 501),
        ("supersedes_inspection_id", UUID(int=0)),
        ("findings", []),
        ("findings", ({},)),
    ],
)
def test_inspection_rejects_invalid_or_mutable_command_fields(field: str, value: object) -> None:
    with pytest.raises(MoveOutInspectionInvalidError):
        replace(inspection(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("finding_id", UUID(int=0)),
        ("description", " "),
        ("description", "x" * 1001),
        ("description", "x\x00y"),
        ("pet_related", 1),
        ("pet_related", "false"),
        ("pet_related", None),
    ],
)
def test_findings_require_typed_identity_text_and_boolean(field: str, value: object) -> None:
    with pytest.raises(MoveOutInspectionInvalidError):
        replace(inspection().findings[0], **{field: value})  # type: ignore[arg-type]


def test_inspection_preserves_empty_findings_order_and_full_correction_intent() -> None:
    request = inspection()
    assert replace(request, findings=()).intent()["findings"] == []
    findings = tuple(InspectionFinding(uuid4(), f"Condition {i}", bool(i % 2)) for i in range(50))
    assert len(replace(request, findings=findings).intent()["findings"]) == 50  # type: ignore[arg-type]
    with pytest.raises(MoveOutInspectionInvalidError):
        replace(
            request, findings=(*findings, InspectionFinding(uuid4(), "Another condition", False))
        )
    with pytest.raises(MoveOutInspectionInvalidError):
        replace(request, findings=(findings[0], findings[0]))
    with pytest.raises(MoveOutInspectionInvalidError):
        replace(request, supersedes_inspection_id=request.inspection_id)
    prop, lease = uuid4(), uuid4()
    intent = request.intent()
    digest = inspection_request_digest(prop, lease, intent)
    assert digest == inspection_request_digest(prop, lease, dict(reversed(list(intent.items()))))
    assert digest != inspection_request_digest(uuid4(), lease, intent)
    assert digest != inspection_request_digest(prop, uuid4(), intent)
    for field in intent:
        assert digest != inspection_request_digest(prop, lease, intent | {field: "changed"})
    assert replace(request, idempotency_key=uuid4()).intent() == intent
    assert "amount" not in intent and "move_out_date" not in intent


@pytest.mark.parametrize("capability", [INSPECTION_READ, "leases.terminate", "leases.warn"])
def test_record_requires_exact_inspection_capability_before_connecting(capability: str) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(capability, frozenset({str(prop)}))})
    )
    with pytest.raises(MoveOutInspectionAuthorizationError):
        PostgresMoveOutInspectionService("unused", "unused").record(
            prop, uuid4(), inspection(), actor=actor, request_id="test"
        )


def test_inspection_scope_and_missing_write_database_fail_before_connection() -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(INSPECTION_RECORD, frozenset({str(prop)}))})
    )
    flow = PostgresMoveOutInspectionService("unused")
    with pytest.raises(MoveOutInspectionNotFoundError):
        flow.read(prop, uuid4(), actor=actor)
    with pytest.raises(MoveOutInspectionAuthorizationError):
        flow.record(uuid4(), uuid4(), inspection(), actor=actor, request_id="test")
    with pytest.raises(MoveOutInspectionUnavailableError):
        flow.record(prop, uuid4(), inspection(), actor=actor, request_id="test")


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (21, 0), (True, 0), (1, -1), (1, 1000001), (1, True)]
)
def test_inspection_read_pages_are_bounded(limit: int, offset: int) -> None:
    with pytest.raises(MoveOutInspectionInvalidError):
        PostgresMoveOutInspectionService("unused").read(
            uuid4(), uuid4(), actor=AuthenticatedActor(str(uuid4())), limit=limit, offset=offset
        )


@pytest.mark.parametrize("state", ["23505", "23514", "40001", "40P01", "55P03", "57014", "08006"])
def test_inspection_unknown_database_outcomes_keep_exact_recovery_required(state: str) -> None:
    assert isinstance(
        PostgresMoveOutInspectionService._error(psycopg.errors.lookup(state)("Synthetic failure")),
        MoveOutInspectionUnavailableError,
    )


def test_a_supersede_refused_after_final_settlement_closure_is_a_conflict() -> None:
    """V1-056 sub-slice 10c-2a-4: the database refuses a supersede on a Lease whose Final
    Settlement is closed (P5S01); the service reports a conflict, not an unknown outcome."""

    class Failure(psycopg.Error):
        pass

    failure = Failure(
        "A move-out inspection of a Lease with a closed Final Settlement cannot be superseded"
    )
    failure.sqlstate = "P5S01"
    error = PostgresMoveOutInspectionService._error(failure)
    assert type(error) is MoveOutInspectionConflictError
    assert str(error) == "The Final Settlement is closed; record later damage as a new inspection"
