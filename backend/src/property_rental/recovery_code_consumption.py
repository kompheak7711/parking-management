"""Atomic recovery-code consumption persistence orchestration."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from property_rental.recovery_code_lifecycle import (
    RecoveryCodeLifecycleAuditEvidence,
    RecoveryCodeLifecycleAuditSink,
    RecoveryCodeLifecycleResult,
    RecoveryCodeLifecycleService,
    RecoveryCodeSetState,
    RecoveryCodeVerificationProvider,
    RecoveryCodeVerifierState,
)

RecoveryCodeConsumptionReason = Literal["code_consumed", "code_rejected"]


@dataclass(frozen=True, slots=True)
class RecoveryCodeConsumptionRequest:
    """Secret-bearing candidate and bounded non-secret persistence context."""

    consuming_actor_id: UUID
    target_actor_id: UUID
    set_id: UUID
    candidate: str = field(repr=False)
    correlation_id: str
    provenance: str

    def __post_init__(self) -> None:
        if any(
            not value or value != value.strip() or not value.isprintable()
            for value in (self.correlation_id, self.provenance)
        ):
            raise ValueError("invalid recovery-code consumption context")


@dataclass(frozen=True, slots=True)
class RecoveryCodeConsumptionResult:
    """Generic outward result without verifier or lifecycle state."""

    completed: bool
    reason: RecoveryCodeConsumptionReason


@dataclass(frozen=True, slots=True)
class RecoveryCodeConsumptionAuditEvidence:
    """Immutable secret-free evidence for one persisted consumption attempt."""

    consuming_actor_id: UUID
    target_actor_id: UUID
    occurred_at: datetime
    correlation_id: str
    set_id: UUID
    code_id: UUID | None
    outcome: str
    reason: str
    previous_state: str
    resulting_state: str


class RecoveryCodeConsumptionAuditSink(Protocol):
    """Sink for immutable consumption evidence without candidate or verifier material."""

    def record(self, evidence: RecoveryCodeConsumptionAuditEvidence) -> None: ...


class _CollectingLifecycleAuditSink(RecoveryCodeLifecycleAuditSink):
    def __init__(self) -> None:
        self.evidence: list[RecoveryCodeLifecycleAuditEvidence] = []

    def record(self, evidence: RecoveryCodeLifecycleAuditEvidence) -> None:
        self.evidence.append(evidence)


class RecoveryCodeConsumptionRepository(Protocol):
    """Atomic lock/read/consumption and secret-free evidence persistence boundary."""

    def consume_atomically(
        self,
        request: RecoveryCodeConsumptionRequest,
        occurred_at: datetime,
        decide: Callable[[RecoveryCodeSetState], RecoveryCodeLifecycleResult],
    ) -> RecoveryCodeLifecycleResult: ...


class RecoveryCodeConsumptionCursor(Protocol):
    """Bounded cursor operations required by the PostgreSQL adapter."""

    rowcount: int

    def __enter__(self) -> "RecoveryCodeConsumptionCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class RecoveryCodeConsumptionConnection(Protocol):
    """Transaction operations required by the PostgreSQL adapter."""

    def cursor(self) -> RecoveryCodeConsumptionCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgresRecoveryCodeConsumptionRepository:
    """Lock one published verifier set and advance at most one code atomically."""

    def __init__(self, connection: RecoveryCodeConsumptionConnection) -> None:
        self._connection = connection

    def consume_atomically(
        self,
        request: RecoveryCodeConsumptionRequest,
        occurred_at: datetime,
        decide: Callable[[RecoveryCodeSetState], RecoveryCodeLifecycleResult],
    ) -> RecoveryCodeLifecycleResult:
        """Evaluate locked durable state and conditionally persist one consumption."""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT recovery_code.code_id,
                           recovery_code.verifier_encoding,
                           recovery_code.consumed_at,
                           recovery_code.invalidated_at,
                           recovery_set.invalidated_at
                    FROM app.recovery_code_sets AS recovery_set
                    JOIN app.recovery_codes AS recovery_code
                      ON recovery_code.set_id = recovery_set.set_id
                    WHERE recovery_set.set_id = %s
                      AND recovery_set.actor_id = %s
                    ORDER BY recovery_code.code_id
                    FOR UPDATE OF recovery_set, recovery_code
                    """,
                    (request.set_id, request.target_actor_id),
                )
                rows = cursor.fetchall()
                state = self._state_from_rows(request, rows)
                result = decide(state)
                if result.completed:
                    code_id = self._consumed_code_id(state, result.state)
                    consumption_provenance = json.dumps(
                        {
                            "correlation_id": request.correlation_id,
                            "previous_state": "active",
                            "provenance": request.provenance,
                            "reason": "code_consumed",
                            "resulting_state": "consumed",
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    cursor.execute(
                        """
                        UPDATE app.recovery_codes
                        SET consumed_at = %s,
                            consumed_by_actor_id = %s,
                            consumption_provenance = %s
                        WHERE code_id = %s
                          AND set_id = %s
                          AND consumed_at IS NULL
                          AND invalidated_at IS NULL
                          AND EXISTS (
                              SELECT 1
                              FROM app.recovery_code_sets
                              WHERE set_id = %s
                                AND actor_id = %s
                                AND invalidated_at IS NULL
                          )
                        """,
                        (
                            occurred_at,
                            request.consuming_actor_id,
                            consumption_provenance,
                            code_id,
                            request.set_id,
                            request.set_id,
                            request.target_actor_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("recovery-code conditional consumption failed")
            self._connection.commit()
            return result
        except Exception:
            self._connection.rollback()
            raise

    @staticmethod
    def _state_from_rows(
        request: RecoveryCodeConsumptionRequest,
        rows: list[tuple[object, ...]],
    ) -> RecoveryCodeSetState:
        verifiers = []
        for code_id, verifier_encoding, consumed_at, invalidated_at, set_invalidated_at in rows:
            if invalidated_at is not None or set_invalidated_at is not None:
                lifecycle_state = "invalidated"
            elif consumed_at is not None:
                lifecycle_state = "consumed"
            else:
                lifecycle_state = "active"
            verifiers.append(
                RecoveryCodeVerifierState(
                    code_id=str(code_id),
                    verifier_reference=str(verifier_encoding),
                    lifecycle_state=lifecycle_state,
                )
            )
        return RecoveryCodeSetState(
            account_id=str(request.target_actor_id),
            set_id=str(request.set_id),
            presentation_state="presented",
            verifiers=tuple(verifiers),
        )

    @staticmethod
    def _consumed_code_id(
        previous: RecoveryCodeSetState,
        resulting: RecoveryCodeSetState,
    ) -> UUID:
        changed = [
            current.code_id
            for prior, current in zip(previous.verifiers, resulting.verifiers, strict=True)
            if prior.lifecycle_state == "active" and current.lifecycle_state == "consumed"
        ]
        if len(changed) != 1:
            raise RuntimeError("recovery-code lifecycle did not identify one consumption")
        return UUID(changed[0])


class RecoveryCodeConsumptionFailed(RuntimeError):
    """Generic fail-closed persistence orchestration failure."""


class RecoveryCodeConsumptionService:
    """Compose published lifecycle, verifier, and atomic persistence boundaries."""

    def __init__(
        self,
        *,
        repository: RecoveryCodeConsumptionRepository,
        verifier_provider: RecoveryCodeVerificationProvider,
        audit_sink: RecoveryCodeConsumptionAuditSink,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._verifier_provider = verifier_provider
        self._audit_sink = audit_sink
        self._clock = clock

    def consume(self, request: RecoveryCodeConsumptionRequest) -> RecoveryCodeConsumptionResult:
        """Persist one successful use or return one generic closed rejection."""
        occurred_at = self._clock()
        lifecycle_audit = _CollectingLifecycleAuditSink()
        lifecycle = RecoveryCodeLifecycleService(
            clock=lambda: occurred_at,
            verifier_provider=self._verifier_provider,
            audit_sink=lifecycle_audit,
        )

        try:
            lifecycle_result = self._repository.consume_atomically(
                request,
                occurred_at,
                lambda state: lifecycle.consume(
                    actor_id=str(request.consuming_actor_id),
                    state=state,
                    candidate=request.candidate,
                    correlation_id=request.correlation_id,
                ),
            )
        except Exception:
            try:
                self._record(
                    request=request,
                    occurred_at=occurred_at,
                    code_id=None,
                    outcome="failed",
                    reason="consumption_failed",
                    previous_state="unresolved",
                    resulting_state="unchanged",
                )
            except Exception:
                pass
            raise RecoveryCodeConsumptionFailed("recovery-code consumption failed") from None

        completed = lifecycle_result.completed
        evidence = lifecycle_audit.evidence[-1]
        try:
            self._record(
                request=request,
                occurred_at=occurred_at,
                code_id=UUID(evidence.code_id) if evidence.code_id is not None else None,
                outcome="completed" if completed else "rejected",
                reason=evidence.reason,
                previous_state=evidence.previous_state,
                resulting_state=evidence.resulting_state,
            )
        except Exception:
            if not completed:
                raise RecoveryCodeConsumptionFailed("recovery-code consumption failed") from None
        return RecoveryCodeConsumptionResult(
            completed=completed,
            reason="code_consumed" if completed else "code_rejected",
        )

    def _record(
        self,
        *,
        request: RecoveryCodeConsumptionRequest,
        occurred_at: datetime,
        code_id: UUID | None,
        outcome: str,
        reason: str,
        previous_state: str,
        resulting_state: str,
    ) -> None:
        self._audit_sink.record(
            RecoveryCodeConsumptionAuditEvidence(
                consuming_actor_id=request.consuming_actor_id,
                target_actor_id=request.target_actor_id,
                occurred_at=occurred_at,
                correlation_id=request.correlation_id,
                set_id=request.set_id,
                code_id=code_id,
                outcome=outcome,
                reason=reason,
                previous_state=previous_state,
                resulting_state=resulting_state,
            )
        )
