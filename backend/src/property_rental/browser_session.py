"""Provider-neutral browser-session lifetime and revocation boundary."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final, Literal, Protocol

INACTIVITY_TIMEOUT: Final = timedelta(minutes=30)
ABSOLUTE_LIFETIME: Final = timedelta(hours=24)

BrowserSessionReason = Literal[
    "active",
    "inactive_expired",
    "absolute_expired",
    "revoked",
    "invalid_timestamps",
]
BrowserSessionOperation = Literal["evaluate", "activity", "revoke"]
BrowserSessionAuditOutcome = Literal["allowed", "denied", "recorded"]


@dataclass(frozen=True, slots=True)
class BrowserSessionState:
    """Provider-neutral timestamps required to enforce one browser-session lifetime."""

    authenticated_at: datetime
    last_activity_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BrowserSessionDecision:
    """Bounded access decision for one browser-session state."""

    active: bool
    reason: BrowserSessionReason


@dataclass(frozen=True, slots=True)
class BrowserSessionAuditEvidence:
    """Bounded secret-free evidence of one lifetime operation."""

    operation: BrowserSessionOperation
    outcome: BrowserSessionAuditOutcome
    reason: BrowserSessionReason


class BrowserSessionAuditSink(Protocol):
    """Sink for secret-free browser-session lifetime evidence."""

    def record(self, evidence: BrowserSessionAuditEvidence) -> None: ...


class BrowserSessionLifetimeService:
    """Apply the fixed inactivity, absolute-lifetime, and revocation policy."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        audit_sink: BrowserSessionAuditSink,
    ) -> None:
        self._clock = clock
        self._audit_sink = audit_sink

    def evaluate(self, session: BrowserSessionState) -> BrowserSessionDecision:
        """Allow only a valid, unexpired, and unrevoked session."""
        decision = self._decision(session, self._clock())
        self._audit_sink.record(
            BrowserSessionAuditEvidence(
                operation="evaluate",
                outcome="allowed" if decision.active else "denied",
                reason=decision.reason,
            )
        )
        return decision

    def record_activity(self, session: BrowserSessionState) -> BrowserSessionState | None:
        """Advance inactivity state only while absolute lifetime still permits access."""
        now = self._clock()
        decision = self._decision(session, now)
        if decision.active:
            updated_session = replace(session, last_activity_at=now)
            outcome: BrowserSessionAuditOutcome = "recorded"
        else:
            updated_session = None
            outcome = "denied"
        self._audit_sink.record(
            BrowserSessionAuditEvidence(
                operation="activity",
                outcome=outcome,
                reason=decision.reason,
            )
        )
        return updated_session

    def revoke(self, session: BrowserSessionState) -> BrowserSessionState:
        """Record explicit revocation so all subsequent access fails closed."""
        revoked_session = replace(session, revoked_at=self._clock())
        self._audit_sink.record(
            BrowserSessionAuditEvidence(
                operation="revoke",
                outcome="recorded",
                reason="revoked",
            )
        )
        return revoked_session

    @staticmethod
    def _decision(session: BrowserSessionState, now: datetime) -> BrowserSessionDecision:
        if session.revoked_at is not None:
            return BrowserSessionDecision(active=False, reason="revoked")
        if not BrowserSessionLifetimeService._timestamps_are_valid(session, now):
            return BrowserSessionDecision(active=False, reason="invalid_timestamps")
        if now - session.authenticated_at >= ABSOLUTE_LIFETIME:
            return BrowserSessionDecision(active=False, reason="absolute_expired")
        if now - session.last_activity_at >= INACTIVITY_TIMEOUT:
            return BrowserSessionDecision(active=False, reason="inactive_expired")
        return BrowserSessionDecision(active=True, reason="active")

    @staticmethod
    def _timestamps_are_valid(session: BrowserSessionState, now: datetime) -> bool:
        timestamps = (session.authenticated_at, session.last_activity_at, now)
        if any(timestamp.utcoffset() is None for timestamp in timestamps):
            return False
        return session.authenticated_at <= session.last_activity_at <= now
