"""Provider-neutral authentication session-revocation orchestration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from property_rental.browser_session import (
    BrowserSessionAuditEvidence,
    BrowserSessionLifetimeService,
    BrowserSessionState,
)

SessionRevocationTrigger = Literal[
    "password_reset",
    "account_disabled",
    "material_privilege_reduction",
]
SessionRevocationOutcome = Literal["completed", "failed"]
SessionRevocationReason = Literal["applicable_sessions_revoked", "revocation_failed"]
APPROVED_REVOCATION_TRIGGERS: Final = {
    "password_reset",
    "account_disabled",
    "material_privilege_reduction",
}


@dataclass(frozen=True, slots=True)
class SessionRevocationRequest:
    """Bounded non-secret context for one approved account-level trigger."""

    target_actor_id: UUID
    trigger: SessionRevocationTrigger
    correlation_id: UUID

    def __post_init__(self) -> None:
        if self.trigger not in APPROVED_REVOCATION_TRIGGERS:
            raise ValueError("unsupported session-revocation trigger")
        if not isinstance(self.target_actor_id, UUID) or not isinstance(self.correlation_id, UUID):
            raise ValueError("invalid session-revocation context")


@dataclass(frozen=True, slots=True)
class SessionRevocationResult:
    """Revoked immutable session states for caller-controlled persistence."""

    revoked_sessions: tuple[BrowserSessionState, ...]
    revoked_count: int


@dataclass(frozen=True, slots=True)
class SessionRevocationAuditEvidence:
    """Immutable secret-free evidence for one account-level revocation."""

    target_actor_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    trigger: SessionRevocationTrigger
    outcome: SessionRevocationOutcome
    reason: SessionRevocationReason
    applicable_session_count: int
    revoked_session_count: int


class SessionRevocationAuditSink(Protocol):
    """Sink for immutable account-level revocation evidence."""

    def record(self, evidence: SessionRevocationAuditEvidence) -> None: ...


class _CollectingBrowserSessionAuditSink:
    def __init__(self) -> None:
        self.evidence: list[BrowserSessionAuditEvidence] = []

    def record(self, evidence: BrowserSessionAuditEvidence) -> None:
        self.evidence.append(evidence)


class SessionRevocationFailed(RuntimeError):
    """Generic fail-closed orchestration failure without provider detail."""


class SessionRevocationService:
    """Compose approved account triggers with the browser-session revoke boundary."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        audit_sink: SessionRevocationAuditSink,
    ) -> None:
        self._clock = clock
        self._audit_sink = audit_sink

    def revoke_applicable(
        self,
        request: SessionRevocationRequest,
        sessions: tuple[BrowserSessionState, ...],
    ) -> SessionRevocationResult:
        """Revoke every caller-selected applicable session at one instant."""
        occurred_at: datetime | None = None
        try:
            candidate_time = self._clock()
            if candidate_time.utcoffset() is not None:
                occurred_at = candidate_time
        except Exception:
            pass
        if occurred_at is None:
            raise SessionRevocationFailed("session revocation failed") from None
        revoked_sessions: tuple[BrowserSessionState, ...] | None = None
        try:
            browser_audit = _CollectingBrowserSessionAuditSink()
            browser_sessions = BrowserSessionLifetimeService(
                clock=lambda: occurred_at,
                audit_sink=browser_audit,
            )
            revoked_sessions = tuple(browser_sessions.revoke(session) for session in sessions)
        except Exception:
            pass
        if revoked_sessions is None:
            try:
                self._audit_sink.record(
                    SessionRevocationAuditEvidence(
                        target_actor_id=request.target_actor_id,
                        occurred_at=occurred_at,
                        correlation_id=request.correlation_id,
                        trigger=request.trigger,
                        outcome="failed",
                        reason="revocation_failed",
                        applicable_session_count=len(sessions),
                        revoked_session_count=0,
                    )
                )
            except Exception:
                pass
            raise SessionRevocationFailed("session revocation failed") from None
        audit_failed = False
        try:
            self._audit_sink.record(
                SessionRevocationAuditEvidence(
                    target_actor_id=request.target_actor_id,
                    occurred_at=occurred_at,
                    correlation_id=request.correlation_id,
                    trigger=request.trigger,
                    outcome="completed",
                    reason="applicable_sessions_revoked",
                    applicable_session_count=len(sessions),
                    revoked_session_count=len(revoked_sessions),
                )
            )
        except Exception:
            audit_failed = True
        if audit_failed:
            raise SessionRevocationFailed("session revocation failed") from None
        return SessionRevocationResult(
            revoked_sessions=revoked_sessions,
            revoked_count=len(revoked_sessions),
        )
