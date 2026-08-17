"""Provider-neutral recovery-code lifecycle decisions."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Protocol

RecoveryCodeLifecycleReason = Literal[
    "presentation_recorded",
    "presentation_not_protected",
    "already_presented",
    "code_consumed",
    "code_reused",
    "code_invalidated",
    "set_invalidated",
    "regeneration_not_protected",
    "invalid_lifecycle_state",
    "code_rejected",
    "presentation_required",
]
RecoveryCodeLifecycleOperation = Literal["presentation", "consumption", "regeneration"]
RecoveryCodeLifecycleOutcome = Literal["completed", "rejected"]


@dataclass(frozen=True, slots=True)
class RecoveryCodeVerifierState:
    """Opaque verifier reference and its provider-neutral lifecycle state."""

    code_id: str
    verifier_reference: str
    lifecycle_state: str


@dataclass(frozen=True, slots=True)
class RecoveryCodeSetState:
    """Non-persistent lifecycle snapshot for one recovery-code set."""

    account_id: str
    set_id: str
    presentation_state: str
    verifiers: tuple[RecoveryCodeVerifierState, ...]


@dataclass(frozen=True, slots=True)
class RecoveryCodeLifecycleResult:
    """Lifecycle decision and resulting non-secret state."""

    completed: bool
    reason: RecoveryCodeLifecycleReason
    state: RecoveryCodeSetState


@dataclass(frozen=True, slots=True)
class RecoveryCodeLifecycleAuditEvidence:
    """Bounded secret-free evidence of one lifecycle decision."""

    actor_id: str
    target_id: str
    occurred_at: datetime
    correlation_id: str
    set_id: str
    code_id: str | None
    operation: RecoveryCodeLifecycleOperation
    outcome: RecoveryCodeLifecycleOutcome
    reason: RecoveryCodeLifecycleReason
    previous_state: str
    resulting_state: str


class RecoveryCodeLifecycleAuditSink(Protocol):
    """Sink for immutable recovery-code lifecycle evidence."""

    def record(self, evidence: RecoveryCodeLifecycleAuditEvidence) -> None: ...


class RecoveryCodeVerificationProvider(Protocol):
    """Provider-selected verification behind an opaque verifier reference."""

    def matches(self, candidate: str, verifier_reference: str, /) -> bool: ...


class RecoveryCodeLifecycleService:
    """Apply provider-neutral one-time recovery-code lifecycle transitions."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        verifier_provider: RecoveryCodeVerificationProvider,
        audit_sink: RecoveryCodeLifecycleAuditSink,
    ) -> None:
        self._clock = clock
        self._verifier_provider = verifier_provider
        self._audit_sink = audit_sink

    def record_presentation(
        self,
        *,
        actor_id: str,
        state: RecoveryCodeSetState,
        protected_flow: bool,
        correlation_id: str,
    ) -> RecoveryCodeLifecycleResult:
        """Record the one allowed presentation transition without handling code material."""
        if not self._is_valid_state(state):
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="invalid_lifecycle_state",
                operation="presentation",
                code_id=None,
                previous_state="invalid",
                resulting_state="invalid",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="invalid_lifecycle_state",
                state=state,
            )
        completed = protected_flow and state.presentation_state == "pending"
        if not protected_flow:
            reason: RecoveryCodeLifecycleReason = "presentation_not_protected"
        elif completed:
            reason = "presentation_recorded"
        else:
            reason = "already_presented"
        resulting_state = replace(state, presentation_state="presented") if completed else state
        self._record(
            actor_id=actor_id,
            state=state,
            correlation_id=correlation_id,
            outcome="completed" if completed else "rejected",
            reason=reason,
            operation="presentation",
            code_id=None,
            previous_state=state.presentation_state,
            resulting_state=resulting_state.presentation_state,
        )
        return RecoveryCodeLifecycleResult(
            completed=completed,
            reason=reason,
            state=resulting_state,
        )

    def consume(
        self,
        *,
        actor_id: str,
        state: RecoveryCodeSetState,
        candidate: str,
        correlation_id: str,
    ) -> RecoveryCodeLifecycleResult:
        """Consume exactly one independently matching active verifier."""
        if not self._is_valid_state(state):
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="invalid_lifecycle_state",
                operation="consumption",
                code_id=None,
                previous_state="invalid",
                resulting_state="invalid",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="invalid_lifecycle_state",
                state=state,
            )
        if state.presentation_state != "presented":
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="presentation_required",
                operation="consumption",
                code_id=None,
                previous_state=state.presentation_state,
                resulting_state=state.presentation_state,
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="presentation_required",
                state=state,
            )
        try:
            matched_indexes = [
                index
                for index, verifier in enumerate(state.verifiers)
                if self._verifier_provider.matches(candidate, verifier.verifier_reference) is True
            ]
        except Exception:
            matched_indexes = []
        if len(matched_indexes) != 1:
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="code_rejected",
                operation="consumption",
                code_id=None,
                previous_state="unresolved",
                resulting_state="unchanged",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="code_rejected",
                state=state,
            )
        matched_index = matched_indexes[0]
        matched = state.verifiers[matched_index]
        if matched.lifecycle_state == "consumed":
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="code_reused",
                operation="consumption",
                code_id=matched.code_id,
                previous_state="consumed",
                resulting_state="consumed",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="code_rejected",
                state=state,
            )
        if matched.lifecycle_state == "invalidated":
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="code_invalidated",
                operation="consumption",
                code_id=matched.code_id,
                previous_state="invalidated",
                resulting_state="invalidated",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="code_rejected",
                state=state,
            )
        updated_verifiers = list(state.verifiers)
        updated_verifiers[matched_index] = replace(matched, lifecycle_state="consumed")
        resulting_state = replace(state, verifiers=tuple(updated_verifiers))
        self._record(
            actor_id=actor_id,
            state=state,
            correlation_id=correlation_id,
            outcome="completed",
            reason="code_consumed",
            operation="consumption",
            code_id=matched.code_id,
            previous_state=matched.lifecycle_state,
            resulting_state="consumed",
        )
        return RecoveryCodeLifecycleResult(
            completed=True,
            reason="code_consumed",
            state=resulting_state,
        )

    def invalidate_for_regeneration(
        self,
        *,
        actor_id: str,
        state: RecoveryCodeSetState,
        protected_flow: bool,
        correlation_id: str,
    ) -> RecoveryCodeLifecycleResult:
        """Invalidate every verifier in the old set before external regeneration."""
        if not self._is_valid_state(state):
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="invalid_lifecycle_state",
                operation="regeneration",
                code_id=None,
                previous_state="invalid",
                resulting_state="invalid",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="invalid_lifecycle_state",
                state=state,
            )
        if not protected_flow:
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="rejected",
                reason="regeneration_not_protected",
                operation="regeneration",
                code_id=None,
                previous_state="unchanged",
                resulting_state="unchanged",
            )
            return RecoveryCodeLifecycleResult(
                completed=False,
                reason="regeneration_not_protected",
                state=state,
            )
        resulting_state = replace(
            state,
            verifiers=tuple(
                replace(verifier, lifecycle_state="invalidated") for verifier in state.verifiers
            ),
        )
        for verifier in state.verifiers:
            self._record(
                actor_id=actor_id,
                state=state,
                correlation_id=correlation_id,
                outcome="completed",
                reason="set_invalidated",
                operation="regeneration",
                code_id=verifier.code_id,
                previous_state=verifier.lifecycle_state,
                resulting_state="invalidated",
            )
        return RecoveryCodeLifecycleResult(
            completed=True,
            reason="set_invalidated",
            state=resulting_state,
        )

    @staticmethod
    def _is_valid_state(state: RecoveryCodeSetState) -> bool:
        if (
            not state.account_id
            or not state.set_id
            or state.presentation_state not in {"pending", "presented"}
            or not state.verifiers
        ):
            return False
        code_ids = [verifier.code_id for verifier in state.verifiers]
        verifier_references = [verifier.verifier_reference for verifier in state.verifiers]
        return (
            all(code_ids)
            and all(verifier_references)
            and len(set(code_ids)) == len(code_ids)
            and len(set(verifier_references)) == len(verifier_references)
            and all(
                verifier.lifecycle_state in {"active", "consumed", "invalidated"}
                for verifier in state.verifiers
            )
        )

    def _record(
        self,
        *,
        actor_id: str,
        state: RecoveryCodeSetState,
        correlation_id: str,
        outcome: RecoveryCodeLifecycleOutcome,
        reason: RecoveryCodeLifecycleReason,
        operation: RecoveryCodeLifecycleOperation,
        code_id: str | None,
        previous_state: str,
        resulting_state: str,
    ) -> None:
        self._audit_sink.record(
            RecoveryCodeLifecycleAuditEvidence(
                actor_id=actor_id,
                target_id=state.account_id,
                occurred_at=self._clock(),
                correlation_id=correlation_id,
                set_id=state.set_id,
                code_id=code_id,
                operation=operation,
                outcome=outcome,
                reason=reason,
                previous_state=previous_state,
                resulting_state=resulting_state,
            )
        )
