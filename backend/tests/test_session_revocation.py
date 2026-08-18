"""Focused deterministic tests for authentication session-revocation orchestration."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

import property_rental.session_revocation as session_revocation_module
from property_rental.browser_session import BrowserSessionState
from property_rental.session_revocation import (
    SessionRevocationAuditEvidence,
    SessionRevocationFailed,
    SessionRevocationRequest,
    SessionRevocationService,
    SessionRevocationTrigger,
)


class CollectingSessionRevocationAuditSink:
    def __init__(self) -> None:
        self.evidence: list[SessionRevocationAuditEvidence] = []

    def record(self, evidence: SessionRevocationAuditEvidence) -> None:
        self.evidence.append(evidence)


class FailingSessionRevocationAuditSink:
    def record(self, evidence: SessionRevocationAuditEvidence) -> None:
        del evidence
        raise RuntimeError("audit backend failed with internal detail")


AUTHENTICATED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
REVOKED_AT = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
TARGET_ACTOR_ID = UUID(int=21)
PASSWORD_CORRELATION_ID = UUID(int=31)
INVALID_TRIGGER_CORRELATION_ID = UUID(int=32)
AUDIT_FAILURE_CORRELATION_ID = UUID(int=33)
CLOCK_FAILURE_CORRELATION_ID = UUID(int=34)
BROWSER_FAILURE_CORRELATION_ID = UUID(int=35)
TRIGGER_CORRELATION_ID = UUID(int=36)
BOUNDED_EVIDENCE_CORRELATION_ID = UUID(int=37)


def active_session(minutes_since_activity: int) -> BrowserSessionState:
    return BrowserSessionState(
        authenticated_at=AUTHENTICATED_AT,
        last_activity_at=REVOKED_AT - timedelta(minutes=minutes_since_activity),
    )


def test_password_reset_revokes_every_applicable_session_through_browser_boundary() -> None:
    audit_sink = CollectingSessionRevocationAuditSink()
    service = SessionRevocationService(clock=lambda: REVOKED_AT, audit_sink=audit_sink)
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger="password_reset",
        correlation_id=PASSWORD_CORRELATION_ID,
    )
    sessions = (active_session(1), active_session(2))

    result = service.revoke_applicable(request, sessions)

    assert result.revoked_sessions == (
        BrowserSessionState(
            authenticated_at=sessions[0].authenticated_at,
            last_activity_at=sessions[0].last_activity_at,
            revoked_at=REVOKED_AT,
        ),
        BrowserSessionState(
            authenticated_at=sessions[1].authenticated_at,
            last_activity_at=sessions[1].last_activity_at,
            revoked_at=REVOKED_AT,
        ),
    )
    assert result.revoked_count == 2
    assert audit_sink.evidence == [
        SessionRevocationAuditEvidence(
            target_actor_id=TARGET_ACTOR_ID,
            occurred_at=REVOKED_AT,
            correlation_id=PASSWORD_CORRELATION_ID,
            trigger="password_reset",
            outcome="completed",
            reason="applicable_sessions_revoked",
            applicable_session_count=2,
            revoked_session_count=2,
        )
    ]


@pytest.mark.parametrize(
    "correlation_id",
    [
        "",
        " padded",
        "line\nbreak",
        "x" * 129,
        "password=must-not-enter-audit",
        "sk_live_abcdefghijklmnopqrstuvwxyz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
    ],
)
def test_revocation_request_rejects_invalid_nonsecret_context(correlation_id: str) -> None:
    with pytest.raises(ValueError, match=r"^invalid session-revocation context$"):
        SessionRevocationRequest(
            target_actor_id=TARGET_ACTOR_ID,
            trigger="account_disabled",
            correlation_id=cast(UUID, correlation_id),
        )
    with pytest.raises(ValueError, match=r"^invalid session-revocation context$"):
        SessionRevocationRequest(
            target_actor_id=cast(UUID, "sk_live_must-not-enter-audit"),
            trigger="account_disabled",
            correlation_id=BOUNDED_EVIDENCE_CORRELATION_ID,
        )


def test_revocation_request_rejects_unapproved_trigger() -> None:
    with pytest.raises(ValueError, match=r"^unsupported session-revocation trigger$"):
        SessionRevocationRequest(
            target_actor_id=TARGET_ACTOR_ID,
            trigger=cast(SessionRevocationTrigger, "credential_changed"),
            correlation_id=INVALID_TRIGGER_CORRELATION_ID,
        )


def test_audit_failure_fails_closed_without_exposing_internal_exception() -> None:
    service = SessionRevocationService(
        clock=lambda: REVOKED_AT,
        audit_sink=FailingSessionRevocationAuditSink(),
    )
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger="material_privilege_reduction",
        correlation_id=AUDIT_FAILURE_CORRELATION_ID,
    )
    sessions = (active_session(1),)

    with pytest.raises(
        SessionRevocationFailed,
        match=r"^session revocation failed$",
    ) as captured:
        service.revoke_applicable(request, sessions)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert sessions[0].revoked_at is None


def test_clock_failure_fails_closed_without_exposing_provider_detail() -> None:
    def failing_clock() -> datetime:
        raise RuntimeError("clock provider failed with internal detail")

    audit_sink = CollectingSessionRevocationAuditSink()
    service = SessionRevocationService(clock=failing_clock, audit_sink=audit_sink)
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger="account_disabled",
        correlation_id=CLOCK_FAILURE_CORRELATION_ID,
    )

    with pytest.raises(
        SessionRevocationFailed,
        match=r"^session revocation failed$",
    ) as captured:
        service.revoke_applicable(request, (active_session(1),))

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert audit_sink.evidence == []


def test_browser_boundary_failure_is_generic_and_has_no_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingBrowserSessionBoundary:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            self.calls = 0

        def revoke(self, session: BrowserSessionState) -> BrowserSessionState:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("browser provider failed with internal detail")
            return BrowserSessionState(
                authenticated_at=session.authenticated_at,
                last_activity_at=session.last_activity_at,
                revoked_at=REVOKED_AT,
            )

    monkeypatch.setattr(
        session_revocation_module,
        "BrowserSessionLifetimeService",
        FailingBrowserSessionBoundary,
    )
    audit_sink = CollectingSessionRevocationAuditSink()
    service = SessionRevocationService(clock=lambda: REVOKED_AT, audit_sink=audit_sink)
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger="password_reset",
        correlation_id=BROWSER_FAILURE_CORRELATION_ID,
    )
    sessions = (active_session(1), active_session(2))

    with pytest.raises(
        SessionRevocationFailed,
        match=r"^session revocation failed$",
    ) as captured:
        service.revoke_applicable(request, sessions)

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert all(session.revoked_at is None for session in sessions)
    assert audit_sink.evidence == [
        SessionRevocationAuditEvidence(
            target_actor_id=TARGET_ACTOR_ID,
            occurred_at=REVOKED_AT,
            correlation_id=BROWSER_FAILURE_CORRELATION_ID,
            trigger="password_reset",
            outcome="failed",
            reason="revocation_failed",
            applicable_session_count=2,
            revoked_session_count=0,
        )
    ]


@pytest.mark.parametrize(
    "trigger",
    ["password_reset", "account_disabled", "material_privilege_reduction"],
)
def test_each_approved_trigger_records_the_exact_revocation_reason(
    trigger: SessionRevocationTrigger,
) -> None:
    audit_sink = CollectingSessionRevocationAuditSink()
    service = SessionRevocationService(clock=lambda: REVOKED_AT, audit_sink=audit_sink)
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger=trigger,
        correlation_id=TRIGGER_CORRELATION_ID,
    )

    result = service.revoke_applicable(request, (active_session(1),))

    assert result.revoked_count == 1
    assert audit_sink.evidence[0].trigger == trigger
    assert audit_sink.evidence[0].reason == "applicable_sessions_revoked"


def test_revocation_audit_evidence_is_fixed_bounded_and_secret_free() -> None:
    audit_sink = CollectingSessionRevocationAuditSink()
    service = SessionRevocationService(clock=lambda: REVOKED_AT, audit_sink=audit_sink)
    request = SessionRevocationRequest(
        target_actor_id=TARGET_ACTOR_ID,
        trigger="account_disabled",
        correlation_id=BOUNDED_EVIDENCE_CORRELATION_ID,
    )

    service.revoke_applicable(request, ())

    assert {field.name for field in fields(audit_sink.evidence[0])} == {
        "target_actor_id",
        "occurred_at",
        "correlation_id",
        "trigger",
        "outcome",
        "reason",
        "applicable_session_count",
        "revoked_session_count",
    }
    assert audit_sink.evidence[0].applicable_session_count == 0
    assert audit_sink.evidence[0].revoked_session_count == 0
