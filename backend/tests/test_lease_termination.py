"""Compatibility evidence for the existing termination command digest."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from property_rental.lease import LeaseTerminateCommand, lease_request_digest
from property_rental.lease_termination import TerminationBasis, TerminationContext


def legacy_termination_command() -> LeaseTerminateCommand:
    return LeaseTerminateCommand(
        idempotency_key=UUID(int=1),
        event_id=UUID(int=2),
        lease_id=UUID(int=3),
        expected_version=2,
        actual_termination_date=date(2026, 7, 10),
        occurred_at=datetime(2026, 7, 10, 10, tzinfo=UTC),
        governing_event_reference="BR-LEASE-021",
        reason="Approved voluntary departure",
        authorization_reference="leases.terminate",
    )


def test_legacy_termination_digest_preserves_accepted_request_identity() -> None:
    # Captured from accepted1f52fd1 before adding any optional context field.
    assert lease_request_digest("lease.terminate", legacy_termination_command()) == (
        "137a865f04a33726d418e0aec84eeee2a322bd2104fbdc94dabd01961a76b790"
    )


def context_without_notice(**changes: object) -> TerminationContext:
    values: dict[str, object] = {
        "basis": TerminationBasis.VOLUNTARY_EARLY,
        "signed_lease_provision": "Signed Lease section 18",
        "approved_grounds": "Approved voluntary departure",
        "management_authorization_reference": "Approved decision TERM-001",
        "evidence_reference": "Signed termination source TERM-001",
        "notice_required": False,
        "notice_exception_reason": "Signed terms permit this documented approved surrender",
    }
    values.update(changes)
    return TerminationContext(**values)  # type: ignore[arg-type]


def test_absent_context_preserves_old_digest_and_supplied_context_binds_every_field() -> None:
    original = legacy_termination_command()
    assert lease_request_digest("lease.terminate", replace(original, context=None)) == (
        "137a865f04a33726d418e0aec84eeee2a322bd2104fbdc94dabd01961a76b790"
    )
    context = context_without_notice()
    current = replace(original, context=context)
    digest = lease_request_digest("lease.terminate", current)
    assert digest != lease_request_digest("lease.terminate", original)
    for changed_context in (
        replace(context, signed_lease_provision="Different approved source"),
        replace(context, approved_grounds="Different approved source"),
        replace(context, management_authorization_reference="Different approved source"),
        replace(context, evidence_reference="Different approved source"),
        replace(context, notice_exception_reason="Different approved source"),
    ):
        changed = replace(current, context=changed_context)
        assert lease_request_digest("lease.terminate", changed) != digest
    applicable = replace(
        context,
        notice_required=True,
        notice_id=UUID(int=4),
        notice_period_ends_on=date(2026, 7, 9),
        notice_exception_reason=None,
    )
    assert lease_request_digest("lease.terminate", replace(current, context=applicable)) != digest
    intent = applicable.intent()
    assert intent["notice_id"] == str(UUID(int=4))
    assert intent["notice_period_ends_on"] == "2026-07-09"
    assert intent["warning_ids"] == []


@pytest.mark.parametrize(
    "changes",
    (
        {"basis": "VOLUNTARY_EARLY"},
        {"basis": None},
        {"signed_lease_provision": " "},
        {"approved_grounds": "\u2003"},
        {"management_authorization_reference": " copied "},
        {"evidence_reference": "bad\x00source"},
        {"evidence_reference": "x" * 501},
        {"notice_required": 1},
        {"notice_exception_reason": None},
        {"notice_exception_reason": "\n"},
        {"notice_id": UUID(int=4)},
        {"notice_period_ends_on": date(2026, 7, 1)},
        {"warning_ids": [UUID(int=4)]},
        {"warning_ids": (UUID(int=0),)},
        {"warning_ids": (UUID(int=4), UUID(int=4))},
        {"warning_ids": (UUID(int=4),)},
        {"basis": TerminationBasis.CUSTOMER_VIOLATION},
        {"basis": TerminationBasis.CUSTOMER_VIOLATION, "warning_ids": (UUID(int=4), UUID(int=5))},
        {
            "basis": TerminationBasis.CUSTOMER_VIOLATION,
            "warning_ids": tuple(UUID(int=i) for i in range(1, 102)),
        },
        {"notice_required": True, "notice_exception_reason": None},
        {
            "notice_required": True,
            "notice_id": UUID(int=4),
            "notice_period_ends_on": datetime(2026, 7, 1, tzinfo=UTC),
            "notice_exception_reason": None,
        },
    ),
)
def test_termination_context_rejects_missing_or_ambiguous_authority(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        context_without_notice(**changes)


def test_notice_dates_and_governing_basis_match_the_actual_command() -> None:
    original = legacy_termination_command()
    with pytest.raises(ValueError, match="basis"):
        replace(original, context=context_without_notice(basis=TerminationBasis.SIGNED_LEASE_OTHER))
    with pytest.raises(ValueError, match="basis"):
        replace(original, context=context_without_notice(), governing_event_reference="OTHER")
    with pytest.raises(ValueError, match="notice period"):
        replace(
            original,
            context=context_without_notice(
                notice_required=True,
                notice_id=UUID(int=4),
                notice_period_ends_on=date(2026, 7, 11),
                notice_exception_reason=None,
            ),
        )
    with pytest.raises(ValueError):
        replace(original, context={})  # type: ignore[arg-type]  # Runtime-invalid input.
    with pytest.raises(ValueError):
        replace(original, context=context_without_notice(), expected_version=True)


def test_three_distinct_general_warning_ids_remain_exact_intent() -> None:
    warnings = tuple(UUID(int=i) for i in (4, 5, 6))
    context = context_without_notice(
        basis=TerminationBasis.CUSTOMER_VIOLATION, warning_ids=warnings
    )
    assert context.intent()["warning_ids"] == [str(value) for value in warnings]
    original = replace(
        legacy_termination_command(), context=context, governing_event_reference="BR-LEASE-025"
    )
    reordered = replace(original, context=replace(context, warning_ids=tuple(reversed(warnings))))
    assert lease_request_digest("lease.terminate", original) != lease_request_digest(
        "lease.terminate", reordered
    )
