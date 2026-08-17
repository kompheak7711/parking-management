"""Provider-neutral administrative recovery authorization boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

RecoveryAuthorizationOutcome = Literal["allowed", "denied"]
RecoveryAuthorizationReason = Literal[
    "owner_to_manager",
    "owner_to_staff",
    "recovery_not_granted",
    "self_recovery_not_granted",
    "invalid_account_class",
]

_VALID_ACCOUNT_CLASSES = frozenset({"owner", "manager", "staff"})
_INVALID_AUDIT_VALUE = "invalid"


@dataclass(frozen=True, slots=True)
class RecoveryAccount:
    """Opaque account identity and provider-established recovery policy class."""

    account_id: str
    account_class: str


@dataclass(frozen=True, slots=True)
class RecoveryAuthorizationDecision:
    """Bounded administrative recovery authorization decision."""

    allowed: bool
    reason: RecoveryAuthorizationReason


@dataclass(frozen=True, slots=True)
class RecoveryAuthorizationAuditEvidence:
    """Secret-free evidence of one administrative recovery authorization decision."""

    actor_id: str
    target_id: str
    occurred_at: datetime
    correlation_id: str
    actor_class: str
    target_class: str
    outcome: RecoveryAuthorizationOutcome
    reason: RecoveryAuthorizationReason


class RecoveryAuthorizationAuditSink(Protocol):
    """Sink for secret-free administrative recovery authorization evidence."""

    def record(self, evidence: RecoveryAuthorizationAuditEvidence) -> None: ...


class AdministrativeRecoveryAuthorizationService:
    """Grant only the approved Owner-to-Manager or Owner-to-Staff recovery paths."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        audit_sink: RecoveryAuthorizationAuditSink,
    ) -> None:
        self._clock = clock
        self._audit_sink = audit_sink

    def authorize(
        self,
        *,
        actor: RecoveryAccount,
        target: RecoveryAccount,
        correlation_id: str,
    ) -> RecoveryAuthorizationDecision:
        """Decide one administrative recovery request and record bounded evidence."""
        reason = self._decision_reason(actor, target)
        allowed = reason in {"owner_to_manager", "owner_to_staff"}
        outcome: RecoveryAuthorizationOutcome = "allowed" if allowed else "denied"
        self._audit_sink.record(
            RecoveryAuthorizationAuditEvidence(
                actor_id=actor.account_id,
                target_id=target.account_id,
                occurred_at=self._clock(),
                correlation_id=correlation_id,
                actor_class=self._safe_account_class(actor.account_class),
                target_class=self._safe_account_class(target.account_class),
                outcome=outcome,
                reason=reason,
            )
        )
        return RecoveryAuthorizationDecision(allowed=allowed, reason=reason)

    @staticmethod
    def _safe_account_class(account_class: str) -> str:
        """Prevent arbitrary class values from entering audit evidence."""
        return account_class if account_class in _VALID_ACCOUNT_CLASSES else _INVALID_AUDIT_VALUE

    @staticmethod
    def _decision_reason(
        actor: RecoveryAccount,
        target: RecoveryAccount,
    ) -> RecoveryAuthorizationReason:
        if (
            actor.account_class not in _VALID_ACCOUNT_CLASSES
            or target.account_class not in _VALID_ACCOUNT_CLASSES
        ):
            return "invalid_account_class"
        if actor.account_id == target.account_id:
            return "self_recovery_not_granted"
        if actor.account_class == "owner" and target.account_class == "manager":
            return "owner_to_manager"
        if actor.account_class == "owner" and target.account_class == "staff":
            return "owner_to_staff"
        return "recovery_not_granted"
