"""Notice validation, permissions, stable intent and conservative recovery."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_notices import (
    NOTICE_READ,
    NOTICE_RECORD,
    LeaseNoticeAuthorizationError,
    LeaseNoticeInvalidError,
    LeaseNoticeNotFoundError,
    LeaseNoticeUnavailableError,
    PostgresLeaseNoticeService,
    RecordLeaseNotice,
    notice_request_digest,
)


def notice() -> RecordLeaseNotice:
    return RecordLeaseNotice(
        uuid4(),
        uuid4(),
        2,
        date(2026, 9, 11),
        date(2026, 10, 11),
        "Notice under signed Lease",
        "Signed Lease clause 8",
        "Approved documented grounds",
        "Notice period exactly as signed clause 8",
        "Document-001",
        "Delivered with evidence",
        "Management approval-001",
        "Record approved notice",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("idempotency_key", UUID(int=0)),
        ("notice_id", UUID(int=0)),
        ("expected_lease_version", True),
        ("expected_lease_version", 0),
        ("expected_lease_version", 1.0),
        ("expected_lease_version", 2_147_483_648),
        ("notice_date", datetime(2026, 9, 11)),
        ("notice_date", "2026-09-11"),
        ("intended_termination_date", date(2026, 9, 10)),
        ("intended_termination_date", datetime(2026, 10, 11)),
        ("notice_text", " "),
        ("notice_text", "x" * 5001),
        ("approved_grounds", "x\x00y"),
        ("notice_period_terms", ""),
        ("notice_period_terms", "x" * 2001),
        ("governing_lease_provision", " x"),
        ("communication_record", "x\n"),
        ("evidence_reference", "x" * 501),
        ("authorization_reference", None),
        ("reason", "x" * 501),
        ("supersedes_notice_id", UUID(int=0)),
    ],
)
def test_notice_rejects_missing_invalid_or_unbounded_evidence(field: str, value: object) -> None:
    with pytest.raises(LeaseNoticeInvalidError):
        replace(notice(), **{field: value})  # type: ignore[arg-type]


def test_optional_intended_date_does_not_invent_a_required_notice_period() -> None:
    request = replace(notice(), intended_termination_date=None)
    assert request.intent()["intended_termination_date"] is None
    with pytest.raises(LeaseNoticeInvalidError):
        replace(request, supersedes_notice_id=request.notice_id)


def test_exact_digest_covers_resource_and_correction_evidence() -> None:
    prop, lease = uuid4(), uuid4()
    request = notice()
    intent = request.intent()
    expected = notice_request_digest(prop, lease, intent)
    assert expected == notice_request_digest(prop, lease, dict(reversed(list(intent.items()))))
    assert expected != notice_request_digest(uuid4(), lease, intent)
    assert expected != notice_request_digest(prop, uuid4(), intent)
    for field in intent:
        assert expected != notice_request_digest(prop, lease, intent | {field: "changed"})
    assert replace(request, idempotency_key=uuid4()).intent() == intent


@pytest.mark.parametrize("capability", [NOTICE_READ, "leases.warn", "rent_nonpayment.event_post"])
def test_notice_requires_exact_termination_capability(capability: str) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(capability, frozenset({str(prop)}))})
    )
    with pytest.raises(LeaseNoticeAuthorizationError):
        PostgresLeaseNoticeService("unused", "unused").record(
            prop, uuid4(), notice(), actor=actor, request_id="test"
        )


def test_read_scope_and_mutation_database_fail_closed_before_connection() -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(NOTICE_RECORD, frozenset({str(prop)}))})
    )
    service = PostgresLeaseNoticeService("unused")
    with pytest.raises(LeaseNoticeNotFoundError):
        service.read(prop, uuid4(), actor=actor)
    with pytest.raises(LeaseNoticeAuthorizationError):
        service.record(uuid4(), uuid4(), notice(), actor=actor, request_id="test")
    with pytest.raises(LeaseNoticeUnavailableError):
        service.record(prop, uuid4(), notice(), actor=actor, request_id="test")


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (101, 0), (True, 0), (1, -1), (1, 1_000_001), (1, True)]
)
def test_read_pages_are_bounded(limit: int, offset: int) -> None:
    with pytest.raises(LeaseNoticeInvalidError):
        PostgresLeaseNoticeService("unused").read(
            uuid4(),
            uuid4(),
            actor=AuthenticatedActor(str(uuid4()), frozenset()),
            limit=limit,
            offset=offset,
        )


@pytest.mark.parametrize("state", ["23505", "23514", "40001", "40P01", "55P03", "57014", "08006"])
def test_unknown_database_outcome_retains_exact_recovery_intent(state: str) -> None:
    assert isinstance(
        PostgresLeaseNoticeService._error(psycopg.errors.lookup(state)("Synthetic failure")),
        LeaseNoticeUnavailableError,
    )
