"""Focused tests for provider-neutral MFA policy enforcement."""

from collections.abc import Iterable
from dataclasses import FrozenInstanceError, fields
from typing import cast

import pytest

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    CapabilityGrant,
    ObjectScope,
    is_authorized,
)
from property_rental.mfa_policy import (
    MfaActorEstablishmentService,
    MfaAuthenticationState,
    MfaPolicyAuditEvidence,
    MfaPolicyReason,
)


class CollectingMfaPolicyAuditSink:
    def __init__(self) -> None:
        self.evidence: list[MfaPolicyAuditEvidence] = []

    def record(self, evidence: MfaPolicyAuditEvidence) -> None:
        self.evidence.append(evidence)


def establish_actor(
    *,
    mfa_policy_class: str,
    enrollment_state: str,
    challenge_state: str,
    capability_grants: Iterable[CapabilityGrant] = (),
) -> tuple[AuthenticatedActor | None, list[MfaPolicyAuditEvidence]]:
    audit_sink = CollectingMfaPolicyAuditSink()
    actor = MfaActorEstablishmentService(audit_sink=audit_sink).establish_actor(
        actor_id="actor-2g",
        mfa_policy_class=mfa_policy_class,
        authentication_state=MfaAuthenticationState(
            enrollment_state=enrollment_state,
            challenge_state=challenge_state,
        ),
        capability_grants=frozenset(capability_grants),
    )
    return actor, audit_sink.evidence


@pytest.mark.parametrize(
    ("mfa_policy_class", "enrollment_state", "challenge_state", "is_established", "reason"),
    [
        ("required", "not_enrolled", "not_applicable", False, "enrollment_required"),
        ("required", "enrolled", "pending", False, "challenge_required"),
        ("required", "enrolled", "completed", True, "policy_satisfied"),
        ("optional", "not_enrolled", "not_applicable", True, "optional_not_enrolled"),
        ("optional", "enrolled", "pending", False, "challenge_required"),
        ("optional", "enrolled", "completed", True, "policy_satisfied"),
    ],
)
def test_mfa_policy_matrix_controls_normal_actor_establishment(
    mfa_policy_class: str,
    enrollment_state: str,
    challenge_state: str,
    is_established: bool,
    reason: str,
) -> None:
    actor, evidence = establish_actor(
        mfa_policy_class=mfa_policy_class,
        enrollment_state=enrollment_state,
        challenge_state=challenge_state,
    )

    assert (actor is not None) is is_established
    assert evidence == [
        MfaPolicyAuditEvidence(
            actor_id="actor-2g",
            outcome="established" if is_established else "rejected",
            reason=cast(MfaPolicyReason, reason),
            mfa_policy_class=mfa_policy_class,
            enrollment_state=enrollment_state,
            challenge_state=challenge_state,
        )
    ]


def test_optional_unenrolled_actor_keeps_only_separately_granted_capabilities() -> None:
    granted_scope = ObjectScope(object_type="actor", object_id="actor-2g")
    actor, _ = establish_actor(
        mfa_policy_class="optional",
        enrollment_state="not_enrolled",
        challenge_state="not_applicable",
        capability_grants=[
            CapabilityGrant(
                capability="identity.read_self",
                object_scopes=frozenset({granted_scope}),
            )
        ],
    )

    assert actor is not None
    assert is_authorized(
        actor,
        AuthorizationRequirement(
            capability="identity.read_self",
            object_scope=granted_scope,
        ),
    )
    assert not is_authorized(actor, AuthorizationRequirement(capability="leases.write"))


def test_mfa_policy_audit_evidence_is_immutable() -> None:
    _, evidence = establish_actor(
        mfa_policy_class="required",
        enrollment_state="enrolled",
        challenge_state="pending",
    )

    with pytest.raises(FrozenInstanceError):
        evidence[0].outcome = "established"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mfa_policy_class", "enrollment_state", "challenge_state"),
    [
        ("unexpected", "enrolled", "completed"),
        ("optional", "unexpected", "completed"),
        ("optional", "enrolled", "unexpected"),
        ("optional", "not_enrolled", "completed"),
    ],
)
def test_invalid_mfa_policy_evidence_fails_closed_without_actor_establishment(
    mfa_policy_class: str,
    enrollment_state: str,
    challenge_state: str,
) -> None:
    actor, evidence = establish_actor(
        mfa_policy_class=mfa_policy_class,
        enrollment_state=enrollment_state,
        challenge_state=challenge_state,
    )

    assert actor is None
    assert evidence[0].outcome == "rejected"
    assert evidence[0].reason == "invalid_evidence"
    assert {field.name for field in fields(evidence[0])} == {
        "actor_id",
        "outcome",
        "reason",
        "mfa_policy_class",
        "enrollment_state",
        "challenge_state",
    }


def test_invalid_mfa_policy_values_are_sanitized_before_audit_recording() -> None:
    sentinel = "credential-like-sensitive-sentinel"

    actor, evidence = establish_actor(
        mfa_policy_class=sentinel,
        enrollment_state=sentinel,
        challenge_state=sentinel,
    )

    assert actor is None
    assert evidence == [
        MfaPolicyAuditEvidence(
            actor_id="actor-2g",
            outcome="rejected",
            reason="invalid_evidence",
            mfa_policy_class="invalid",
            enrollment_state="invalid",
            challenge_state="invalid",
        )
    ]
    assert sentinel not in repr(evidence)
