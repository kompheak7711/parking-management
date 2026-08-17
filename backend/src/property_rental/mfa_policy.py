"""Provider-neutral MFA policy gate for normal actor establishment."""

from dataclasses import dataclass
from typing import Literal, Protocol

from property_rental.identity import AuthenticatedActor, CapabilityGrant

MfaPolicyClass = Literal["required", "optional"]
MfaEnrollmentState = Literal["not_enrolled", "enrolled"]
MfaChallengeState = Literal["not_applicable", "pending", "completed"]
MfaPolicyOutcome = Literal["established", "rejected"]
MfaPolicyReason = Literal[
    "policy_satisfied",
    "optional_not_enrolled",
    "enrollment_required",
    "challenge_required",
    "invalid_evidence",
]

_VALID_POLICY_CLASSES = frozenset({"required", "optional"})
_VALID_ENROLLMENT_STATES = frozenset({"not_enrolled", "enrolled"})
_VALID_CHALLENGE_STATES = frozenset({"not_applicable", "pending", "completed"})
_INVALID_AUDIT_VALUE = "invalid"


@dataclass(frozen=True, slots=True)
class MfaAuthenticationState:
    """Provider-neutral enrollment and challenge assertions for one login."""

    enrollment_state: str
    challenge_state: str


@dataclass(frozen=True, slots=True)
class MfaPolicyAuditEvidence:
    """Secret-free evidence of one MFA policy enforcement decision."""

    actor_id: str
    outcome: MfaPolicyOutcome
    reason: MfaPolicyReason
    mfa_policy_class: str
    enrollment_state: str
    challenge_state: str


class MfaPolicyAuditSink(Protocol):
    """Sink for secret-free MFA policy decision evidence."""

    def record(self, evidence: MfaPolicyAuditEvidence) -> None: ...


class MfaActorEstablishmentService:
    """Establish an actor only after its existing MFA policy is satisfied."""

    def __init__(self, *, audit_sink: MfaPolicyAuditSink) -> None:
        self._audit_sink = audit_sink

    def establish_actor(
        self,
        *,
        actor_id: str,
        mfa_policy_class: str,
        authentication_state: MfaAuthenticationState,
        capability_grants: frozenset[CapabilityGrant] = frozenset(),
    ) -> AuthenticatedActor | None:
        """Apply the required/optional matrix without inferring any capability."""
        reason = self._decision_reason(mfa_policy_class, authentication_state)
        if reason in {"policy_satisfied", "optional_not_enrolled"}:
            outcome: MfaPolicyOutcome = "established"
            actor = AuthenticatedActor(
                actor_id=actor_id,
                capability_grants=capability_grants,
            )
        else:
            outcome = "rejected"
            actor = None

        self._audit_sink.record(
            MfaPolicyAuditEvidence(
                actor_id=actor_id,
                outcome=outcome,
                reason=reason,
                mfa_policy_class=self._safe_audit_value(mfa_policy_class, _VALID_POLICY_CLASSES),
                enrollment_state=self._safe_audit_value(
                    authentication_state.enrollment_state, _VALID_ENROLLMENT_STATES
                ),
                challenge_state=self._safe_audit_value(
                    authentication_state.challenge_state, _VALID_CHALLENGE_STATES
                ),
            )
        )
        return actor

    @staticmethod
    def _safe_audit_value(value: str, allowed_values: frozenset[str]) -> str:
        """Keep bounded policy labels while preventing arbitrary input in audit evidence."""
        return value if value in allowed_values else _INVALID_AUDIT_VALUE

    @staticmethod
    def _decision_reason(
        mfa_policy_class: str,
        authentication_state: MfaAuthenticationState,
    ) -> MfaPolicyReason:
        enrollment_state = authentication_state.enrollment_state
        challenge_state = authentication_state.challenge_state
        if (
            mfa_policy_class not in _VALID_POLICY_CLASSES
            or enrollment_state not in _VALID_ENROLLMENT_STATES
            or challenge_state not in _VALID_CHALLENGE_STATES
            or (enrollment_state == "not_enrolled" and challenge_state != "not_applicable")
            or (enrollment_state == "enrolled" and challenge_state == "not_applicable")
        ):
            return "invalid_evidence"
        if enrollment_state == "not_enrolled":
            if mfa_policy_class == "required":
                return "enrollment_required"
            return "optional_not_enrolled"
        if challenge_state != "completed":
            return "challenge_required"
        return "policy_satisfied"
