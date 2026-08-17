"""Focused deterministic tests for recovery-code lifecycle decisions."""

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from property_rental.recovery_code_lifecycle import (
    RecoveryCodeLifecycleAuditEvidence,
    RecoveryCodeLifecycleService,
    RecoveryCodeSetState,
    RecoveryCodeVerificationProvider,
    RecoveryCodeVerifierState,
)


class CollectingRecoveryCodeAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryCodeLifecycleAuditEvidence] = []

    def record(self, evidence: RecoveryCodeLifecycleAuditEvidence) -> None:
        self.evidence.append(evidence)


class StubRecoveryCodeVerificationProvider(RecoveryCodeVerificationProvider):
    def __init__(self, matches: set[tuple[str, str]] | None = None) -> None:
        self._matches = matches or set()
        self.calls: list[tuple[str, str]] = []

    def matches(self, candidate: str, verifier_reference: str) -> bool:
        self.calls.append((candidate, verifier_reference))
        return (candidate, verifier_reference) in self._matches


class FailingRecoveryCodeVerificationProvider(RecoveryCodeVerificationProvider):
    def matches(self, candidate: str, verifier_reference: str) -> bool:
        del candidate, verifier_reference
        raise RuntimeError("provider failure containing no recoverable decision")


OCCURRED_AT = datetime(2026, 8, 18, 2, 30, tzinfo=UTC)


def recovery_code_set(*, presentation_state: str = "pending") -> RecoveryCodeSetState:
    return RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state=presentation_state,
        verifiers=(
            RecoveryCodeVerifierState(
                code_id="code-1",
                verifier_reference="verifier-1",
                lifecycle_state="active",
            ),
        ),
    )


def test_protected_presentation_is_recorded_only_once_without_returning_code_material() -> None:
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=StubRecoveryCodeVerificationProvider(),
        audit_sink=audit_sink,
    )
    initial = recovery_code_set()

    presented = service.record_presentation(
        actor_id="actor-2j",
        state=initial,
        protected_flow=True,
        correlation_id="correlation-2j",
    )
    repeated = service.record_presentation(
        actor_id="actor-2j",
        state=presented.state,
        protected_flow=True,
        correlation_id="correlation-2j-repeat",
    )

    assert presented.completed
    assert presented.reason == "presentation_recorded"
    assert presented.state.presentation_state == "presented"
    assert not repeated.completed
    assert repeated.reason == "already_presented"
    assert repeated.state == presented.state
    assert audit_sink.evidence == [
        RecoveryCodeLifecycleAuditEvidence(
            actor_id="actor-2j",
            target_id="account-2j",
            occurred_at=OCCURRED_AT,
            correlation_id="correlation-2j",
            set_id="set-2j",
            code_id=None,
            operation="presentation",
            outcome="completed",
            reason="presentation_recorded",
            previous_state="pending",
            resulting_state="presented",
        ),
        RecoveryCodeLifecycleAuditEvidence(
            actor_id="actor-2j",
            target_id="account-2j",
            occurred_at=OCCURRED_AT,
            correlation_id="correlation-2j-repeat",
            set_id="set-2j",
            code_id=None,
            operation="presentation",
            outcome="rejected",
            reason="already_presented",
            previous_state="presented",
            resulting_state="presented",
        ),
    ]
    assert "recovery-code-material" not in repr(presented)


def test_unprotected_presentation_fails_closed_without_changing_state() -> None:
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=StubRecoveryCodeVerificationProvider(),
        audit_sink=audit_sink,
    )
    initial = recovery_code_set()

    result = service.record_presentation(
        actor_id="actor-2j",
        state=initial,
        protected_flow=False,
        correlation_id="correlation-unprotected",
    )

    assert not result.completed
    assert result.reason == "presentation_not_protected"
    assert result.state == initial
    assert audit_sink.evidence[0].previous_state == "pending"
    assert audit_sink.evidence[0].resulting_state == "pending"


def test_successful_use_consumes_only_the_matching_code() -> None:
    secret = "candidate-code-secret"
    verifier_provider = StubRecoveryCodeVerificationProvider({(secret, "verifier-1")})
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )
    initial = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state="presented",
        verifiers=(
            RecoveryCodeVerifierState("code-1", "verifier-1", "active"),
            RecoveryCodeVerifierState("code-2", "verifier-2", "active"),
        ),
    )

    result = service.consume(
        actor_id="actor-2j",
        state=initial,
        candidate=secret,
        correlation_id="correlation-consume",
    )

    assert result.completed
    assert result.reason == "code_consumed"
    assert tuple(verifier.lifecycle_state for verifier in result.state.verifiers) == (
        "consumed",
        "active",
    )
    assert verifier_provider.calls == [(secret, "verifier-1"), (secret, "verifier-2")]
    assert audit_sink.evidence == [
        RecoveryCodeLifecycleAuditEvidence(
            actor_id="actor-2j",
            target_id="account-2j",
            occurred_at=OCCURRED_AT,
            correlation_id="correlation-consume",
            set_id="set-2j",
            code_id="code-1",
            operation="consumption",
            outcome="completed",
            reason="code_consumed",
            previous_state="active",
            resulting_state="consumed",
        )
    ]
    assert secret not in repr(result)
    assert secret not in repr(audit_sink.evidence)


def test_consumed_code_reuse_is_rejected_without_state_change() -> None:
    secret = "previously-consumed-secret"
    verifier_provider = StubRecoveryCodeVerificationProvider({(secret, "verifier-1")})
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )
    initial = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state="presented",
        verifiers=(RecoveryCodeVerifierState("code-1", "verifier-1", "consumed"),),
    )

    result = service.consume(
        actor_id="actor-2j",
        state=initial,
        candidate=secret,
        correlation_id="correlation-reuse",
    )

    assert not result.completed
    assert result.reason == "code_rejected"
    assert result.state == initial
    assert audit_sink.evidence[0].code_id == "code-1"
    assert audit_sink.evidence[0].outcome == "rejected"
    assert audit_sink.evidence[0].reason == "code_reused"
    assert audit_sink.evidence[0].previous_state == "consumed"
    assert audit_sink.evidence[0].resulting_state == "consumed"
    assert secret not in repr(audit_sink.evidence)


def test_regeneration_invalidates_every_old_verifier_and_rejects_old_code() -> None:
    secret = "old-set-secret"
    verifier_provider = StubRecoveryCodeVerificationProvider({(secret, "verifier-2")})
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )
    initial = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="old-set-2j",
        presentation_state="presented",
        verifiers=(
            RecoveryCodeVerifierState("code-1", "verifier-1", "consumed"),
            RecoveryCodeVerifierState("code-2", "verifier-2", "active"),
        ),
    )

    invalidated = service.invalidate_for_regeneration(
        actor_id="actor-2j",
        state=initial,
        protected_flow=True,
        correlation_id="correlation-regenerate",
    )
    rejected = service.consume(
        actor_id="actor-2j",
        state=invalidated.state,
        candidate=secret,
        correlation_id="correlation-old-code",
    )

    assert invalidated.completed
    assert invalidated.reason == "set_invalidated"
    assert all(
        verifier.lifecycle_state == "invalidated" for verifier in invalidated.state.verifiers
    )
    assert not rejected.completed
    assert rejected.reason == "code_rejected"
    assert rejected.state == invalidated.state
    assert [evidence.operation for evidence in audit_sink.evidence] == [
        "regeneration",
        "regeneration",
        "consumption",
    ]
    assert [evidence.code_id for evidence in audit_sink.evidence] == [
        "code-1",
        "code-2",
        "code-2",
    ]
    assert [evidence.previous_state for evidence in audit_sink.evidence[:2]] == [
        "consumed",
        "active",
    ]
    assert all(evidence.resulting_state == "invalidated" for evidence in audit_sink.evidence[:2])
    assert audit_sink.evidence[2].reason == "code_invalidated"
    assert secret not in repr(audit_sink.evidence)


def test_unprotected_regeneration_is_rejected_without_invalidating_codes() -> None:
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=StubRecoveryCodeVerificationProvider(),
        audit_sink=audit_sink,
    )
    initial = recovery_code_set(presentation_state="presented")

    result = service.invalidate_for_regeneration(
        actor_id="actor-2j",
        state=initial,
        protected_flow=False,
        correlation_id="correlation-unprotected-regeneration",
    )

    assert not result.completed
    assert result.reason == "regeneration_not_protected"
    assert result.state == initial
    assert audit_sink.evidence[0].operation == "regeneration"
    assert audit_sink.evidence[0].outcome == "rejected"
    assert audit_sink.evidence[0].previous_state == "unchanged"
    assert audit_sink.evidence[0].resulting_state == "unchanged"


@pytest.mark.parametrize(
    "invalid_state",
    [
        RecoveryCodeSetState("account", "set", "unknown", ()),
        RecoveryCodeSetState("account", "set", "presented", ()),
        RecoveryCodeSetState(
            "account",
            "set",
            "presented",
            (RecoveryCodeVerifierState("code", "verifier", "unknown"),),
        ),
        RecoveryCodeSetState(
            "account",
            "set",
            "presented",
            (
                RecoveryCodeVerifierState("duplicate", "verifier-1", "active"),
                RecoveryCodeVerifierState("duplicate", "verifier-2", "active"),
            ),
        ),
        RecoveryCodeSetState(
            "account",
            "set",
            "presented",
            (
                RecoveryCodeVerifierState("code-1", "duplicate", "active"),
                RecoveryCodeVerifierState("code-2", "duplicate", "active"),
            ),
        ),
    ],
)
def test_invalid_lifecycle_state_fails_closed_before_verification(
    invalid_state: RecoveryCodeSetState,
) -> None:
    verifier_provider = StubRecoveryCodeVerificationProvider()
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )

    result = service.consume(
        actor_id="actor-2j",
        state=invalid_state,
        candidate="candidate-secret",
        correlation_id="correlation-invalid",
    )

    assert not result.completed
    assert result.reason == "invalid_lifecycle_state"
    assert result.state == invalid_state
    assert verifier_provider.calls == []
    assert audit_sink.evidence[0].previous_state == "invalid"
    assert audit_sink.evidence[0].resulting_state == "invalid"


@pytest.mark.parametrize(
    "matching_references",
    [set(), {"verifier-1", "verifier-2"}],
)
def test_unmatched_or_ambiguous_verification_is_generically_rejected(
    matching_references: set[str],
) -> None:
    secret = "candidate-secret"
    verifier_provider = StubRecoveryCodeVerificationProvider(
        {(secret, reference) for reference in matching_references}
    )
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )
    initial = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state="presented",
        verifiers=(
            RecoveryCodeVerifierState("code-1", "verifier-1", "active"),
            RecoveryCodeVerifierState("code-2", "verifier-2", "active"),
        ),
    )

    result = service.consume(
        actor_id="actor-2j",
        state=initial,
        candidate=secret,
        correlation_id="correlation-rejected",
    )

    assert not result.completed
    assert result.reason == "code_rejected"
    assert result.state == initial
    assert verifier_provider.calls == [(secret, "verifier-1"), (secret, "verifier-2")]
    assert audit_sink.evidence[0].code_id is None
    assert audit_sink.evidence[0].previous_state == "unresolved"
    assert audit_sink.evidence[0].resulting_state == "unchanged"
    assert secret not in repr(audit_sink.evidence)


def test_code_cannot_be_consumed_before_protected_presentation_is_recorded() -> None:
    verifier_provider = StubRecoveryCodeVerificationProvider({("candidate-secret", "verifier-1")})
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=verifier_provider,
        audit_sink=audit_sink,
    )
    initial = recovery_code_set(presentation_state="pending")

    result = service.consume(
        actor_id="actor-2j",
        state=initial,
        candidate="candidate-secret",
        correlation_id="correlation-before-presentation",
    )

    assert not result.completed
    assert result.reason == "presentation_required"
    assert result.state == initial
    assert verifier_provider.calls == []
    assert audit_sink.evidence[0].previous_state == "pending"
    assert audit_sink.evidence[0].resulting_state == "pending"


def test_presentation_and_regeneration_fail_closed_on_invalid_state() -> None:
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=StubRecoveryCodeVerificationProvider(),
        audit_sink=audit_sink,
    )
    invalid = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state="pending",
        verifiers=(RecoveryCodeVerifierState("code-1", "verifier-1", "unknown"),),
    )

    presentation = service.record_presentation(
        actor_id="actor-2j",
        state=invalid,
        protected_flow=True,
        correlation_id="correlation-invalid-presentation",
    )
    regeneration = service.invalidate_for_regeneration(
        actor_id="actor-2j",
        state=invalid,
        protected_flow=True,
        correlation_id="correlation-invalid-regeneration",
    )

    assert not presentation.completed
    assert presentation.reason == "invalid_lifecycle_state"
    assert presentation.state == invalid
    assert not regeneration.completed
    assert regeneration.reason == "invalid_lifecycle_state"
    assert regeneration.state == invalid
    assert [evidence.operation for evidence in audit_sink.evidence] == [
        "presentation",
        "regeneration",
    ]
    assert all(evidence.outcome == "rejected" for evidence in audit_sink.evidence)


def test_verification_provider_failure_is_a_secret_free_closed_rejection() -> None:
    secret = "provider-failure-secret"
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=FailingRecoveryCodeVerificationProvider(),
        audit_sink=audit_sink,
    )
    initial = recovery_code_set(presentation_state="presented")

    result = service.consume(
        actor_id="actor-2j",
        state=initial,
        candidate=secret,
        correlation_id="correlation-provider-failure",
    )

    assert not result.completed
    assert result.reason == "code_rejected"
    assert result.state == initial
    assert audit_sink.evidence[0].code_id is None
    assert secret not in repr(result)
    assert secret not in repr(audit_sink.evidence)


def test_lifecycle_audit_evidence_is_fixed_bounded_and_excludes_secret_material() -> None:
    candidate = "candidate-sensitive-sentinel"
    verifier_reference = "verifier-sensitive-sentinel"
    audit_sink = CollectingRecoveryCodeAuditSink()
    service = RecoveryCodeLifecycleService(
        clock=lambda: OCCURRED_AT,
        verifier_provider=StubRecoveryCodeVerificationProvider({(candidate, verifier_reference)}),
        audit_sink=audit_sink,
    )
    state = RecoveryCodeSetState(
        account_id="account-2j",
        set_id="set-2j",
        presentation_state="presented",
        verifiers=(RecoveryCodeVerifierState("code-1", verifier_reference, "active"),),
    )

    service.consume(
        actor_id="actor-2j",
        state=state,
        candidate=candidate,
        correlation_id="correlation-audit",
    )

    evidence = audit_sink.evidence[0]
    assert {field.name for field in fields(evidence)} == {
        "actor_id",
        "target_id",
        "occurred_at",
        "correlation_id",
        "set_id",
        "code_id",
        "operation",
        "outcome",
        "reason",
        "previous_state",
        "resulting_state",
    }
    assert candidate not in repr(evidence)
    assert verifier_reference not in repr(evidence)
