"""Command validation, exact permissions, and uncertain-outcome recovery."""

from dataclasses import replace
from datetime import date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_enforcement import (
    NONPAYMENT_EVENT,
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    WARNING_CREATE,
    WARNING_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementInvalidError,
    LeaseEnforcementNotFoundError,
    LeaseEnforcementUnavailableError,
    NonpaymentEventKind,
    OpenRentNonpaymentCase,
    PostgresLeaseEnforcementService,
    RecordLeaseWarning,
    RecordRentNonpaymentEvent,
    enforcement_request_digest,
)


def warning() -> RecordLeaseWarning:
    return RecordLeaseWarning(
        uuid4(),
        1,
        date(2026, 5, 1),
        date(2026, 5, 2),
        "Documented violation",
        "Signed Lease provision",
        "Letter delivered",
        "Record notice",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("warning_sequence", True),
        ("warning_sequence", 0),
        ("warning_sequence", 32768),
        ("warning_sequence", 1.0),
        ("violation_date", datetime(2026, 5, 1)),
        ("warning_date", "2026-05-01"),
        ("idempotency_key", UUID(int=0)),
        ("violation_description", " "),
        ("lease_provision", "x\x00y"),
        ("communication_record", "x" * 2001),
        ("reason", "x" * 501),
    ],
)
def test_warning_rejects_malformed_or_unbounded_source(field: str, value: object) -> None:
    with pytest.raises(LeaseEnforcementInvalidError):
        replace(warning(), **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kind", [NonpaymentEventKind.TWENTY_DAY_WARNING, NonpaymentEventKind.AUTHORIZED_FOLLOW_UP]
)
def test_notice_and_follow_up_require_distinct_permanent_evidence(
    kind: NonpaymentEventKind,
) -> None:
    with pytest.raises(LeaseEnforcementInvalidError):
        RecordRentNonpaymentEvent(uuid4(), kind, "Record authorized action")


@pytest.mark.parametrize("value", ["TERMINATED", "THIRTY_DAY_SERIOUS_DEFAULT", None])
def test_event_requires_typed_canonical_kind(value: object) -> None:
    with pytest.raises(LeaseEnforcementInvalidError):
        RecordRentNonpaymentEvent(uuid4(), value, "Reason")  # type: ignore[arg-type]


def test_digest_excludes_generated_evidence_and_binds_every_resource_and_intent() -> None:
    prop, lease, case = uuid4(), uuid4(), uuid4()
    payload: dict[str, object] = {"reason": "Reason", "event_kind": "CURE"}
    digest = enforcement_request_digest("EVENT", prop, lease, case, payload)
    assert digest == enforcement_request_digest(
        "EVENT", prop, lease, case, dict(reversed(list(payload.items())))
    )
    alternatives = [
        enforcement_request_digest("WARNING", prop, lease, case, payload),
        enforcement_request_digest("EVENT", uuid4(), lease, case, payload),
        enforcement_request_digest("EVENT", prop, uuid4(), case, payload),
        enforcement_request_digest("EVENT", prop, lease, uuid4(), payload),
        enforcement_request_digest("EVENT", prop, lease, case, payload | {"reason": "Different"}),
    ]
    assert digest not in alternatives and len(set(alternatives)) == len(alternatives)


@pytest.mark.parametrize(
    "granted", [WARNING_CREATE, WARNING_READ, NONPAYMENT_OPEN, NONPAYMENT_READ]
)
def test_generic_warning_case_and_view_grants_never_authorize_nonpayment_events(
    granted: str,
) -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(granted, frozenset({str(prop)}))})
    )
    with pytest.raises(LeaseEnforcementAuthorizationError):
        PostgresLeaseEnforcementService("unused", "unused").record_event(
            prop,
            uuid4(),
            uuid4(),
            RecordRentNonpaymentEvent(uuid4(), NonpaymentEventKind.CURE, "Cure"),
            actor=actor,
            request_id="test",
        )


def test_wrong_property_and_mutation_only_grants_hide_reads_before_connecting() -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(NONPAYMENT_EVENT, frozenset({str(prop)}))})
    )
    with pytest.raises(LeaseEnforcementNotFoundError):
        PostgresLeaseEnforcementService("unused").read(prop, uuid4(), "CASES", actor=actor)
    viewer = AuthenticatedActor(
        actor.actor_id, frozenset({CapabilityGrant(NONPAYMENT_READ, frozenset({str(uuid4())}))})
    )
    with pytest.raises(LeaseEnforcementNotFoundError):
        PostgresLeaseEnforcementService("unused").read(prop, uuid4(), "CASES", actor=viewer)


@pytest.mark.parametrize("state", ["23505", "23514", "40001", "40P01", "55P03", "57014", "08006"])
def test_generic_database_errors_preserve_unknown_outcome_instead_of_discarding_replay(
    state: str,
) -> None:
    error = psycopg.errors.lookup(state)("Synthetic failure")
    assert isinstance(
        PostgresLeaseEnforcementService._error(error), LeaseEnforcementUnavailableError
    )


def test_missing_command_database_never_falls_back_to_runtime_writer() -> None:
    prop = uuid4()
    actor = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant(NONPAYMENT_OPEN, frozenset({str(prop)}))})
    )
    with pytest.raises(LeaseEnforcementUnavailableError):
        PostgresLeaseEnforcementService("unused").open_case(
            prop,
            uuid4(),
            OpenRentNonpaymentCase(uuid4(), uuid4(), "Reason"),
            actor=actor,
            request_id="test",
        )
