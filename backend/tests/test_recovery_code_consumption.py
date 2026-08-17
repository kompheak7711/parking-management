"""Focused tests for atomic recovery-code consumption orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from property_rental.recovery_code_consumption import (
    PostgresRecoveryCodeConsumptionRepository,
    RecoveryCodeConsumptionAuditEvidence,
    RecoveryCodeConsumptionFailed,
    RecoveryCodeConsumptionRequest,
    RecoveryCodeConsumptionService,
)
from property_rental.recovery_code_lifecycle import (
    RecoveryCodeLifecycleResult,
    RecoveryCodeSetState,
    RecoveryCodeVerifierState,
)


class StubVerifierProvider:
    def __init__(self, matches: set[tuple[str, str]]) -> None:
        self._matches = matches
        self.calls: list[tuple[str, str]] = []

    def matches(self, candidate: str, verifier_reference: str) -> bool:
        self.calls.append((candidate, verifier_reference))
        return (candidate, verifier_reference) in self._matches


class InMemoryAtomicRepository:
    def __init__(self, state: RecoveryCodeSetState) -> None:
        self.state = state
        self.calls = 0

    def consume_atomically(
        self,
        request: RecoveryCodeConsumptionRequest,
        occurred_at: datetime,
        decide: Callable[[RecoveryCodeSetState], RecoveryCodeLifecycleResult],
    ) -> RecoveryCodeLifecycleResult:
        del request, occurred_at
        self.calls += 1
        result = decide(self.state)
        if result.completed:
            self.state = result.state
        return result


class FailingRepository(InMemoryAtomicRepository):
    def consume_atomically(
        self,
        request: RecoveryCodeConsumptionRequest,
        occurred_at: datetime,
        decide: Callable[[RecoveryCodeSetState], RecoveryCodeLifecycleResult],
    ) -> RecoveryCodeLifecycleResult:
        del request, occurred_at, decide
        raise RuntimeError("database failure with internal detail")


class RecordingAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryCodeConsumptionAuditEvidence] = []

    def record(self, evidence: RecoveryCodeConsumptionAuditEvidence) -> None:
        self.evidence.append(evidence)


class FailingAuditSink:
    def record(self, evidence: RecoveryCodeConsumptionAuditEvidence) -> None:
        del evidence
        raise RuntimeError("audit persistence failed with internal detail")


FIXED_TIME = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
REQUEST = RecoveryCodeConsumptionRequest(
    consuming_actor_id=UUID(int=10),
    target_actor_id=UUID(int=11),
    set_id=UUID(int=12),
    candidate="single-use-secret",
    correlation_id="correlation-2n",
    provenance="protected-recovery",
)


def recovery_state(*, lifecycle_state: str = "active") -> RecoveryCodeSetState:
    return RecoveryCodeSetState(
        account_id=str(REQUEST.target_actor_id),
        set_id=str(REQUEST.set_id),
        presentation_state="presented",
        verifiers=(
            RecoveryCodeVerifierState(
                code_id=str(UUID(int=13)),
                verifier_reference="$stub$v=1$opaque-verifier",
                lifecycle_state=lifecycle_state,
            ),
        ),
    )


def test_consumption_composes_lifecycle_verifier_and_atomic_repository_once() -> None:
    verifier = StubVerifierProvider({(REQUEST.candidate, "$stub$v=1$opaque-verifier")})
    repository = InMemoryAtomicRepository(recovery_state())
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeConsumptionService(
        repository=repository,
        verifier_provider=verifier,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
    )

    result = service.consume(REQUEST)

    assert result.completed
    assert result.reason == "code_consumed"
    assert repository.calls == 1
    assert repository.state.verifiers[0].lifecycle_state == "consumed"
    assert verifier.calls == [(REQUEST.candidate, "$stub$v=1$opaque-verifier")]
    assert audit_sink.evidence == [
        RecoveryCodeConsumptionAuditEvidence(
            consuming_actor_id=REQUEST.consuming_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            set_id=REQUEST.set_id,
            code_id=UUID(int=13),
            outcome="completed",
            reason="code_consumed",
            previous_state="active",
            resulting_state="consumed",
        )
    ]
    assert REQUEST.candidate not in repr(result)
    assert REQUEST.candidate not in repr(audit_sink.evidence)


@pytest.mark.parametrize("lifecycle_state", ["consumed", "invalidated"])
def test_non_active_matching_code_has_one_generic_outcome_without_persistence(
    lifecycle_state: str,
) -> None:
    verifier = StubVerifierProvider({(REQUEST.candidate, "$stub$v=1$opaque-verifier")})
    initial = recovery_state(lifecycle_state=lifecycle_state)
    repository = InMemoryAtomicRepository(initial)
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeConsumptionService(
        repository=repository,
        verifier_provider=verifier,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
    )

    result = service.consume(REQUEST)

    assert not result.completed
    assert result.reason == "code_rejected"
    assert repository.state == initial
    assert audit_sink.evidence[0].code_id == UUID(int=13)
    assert audit_sink.evidence[0].outcome == "rejected"
    assert audit_sink.evidence[0].reason in {"code_reused", "code_invalidated"}
    assert audit_sink.evidence[0].previous_state == lifecycle_state
    assert audit_sink.evidence[0].resulting_state == lifecycle_state
    assert REQUEST.candidate not in repr(result)
    assert REQUEST.candidate not in repr(audit_sink.evidence)


def test_persistence_failure_fails_closed_with_secret_free_immutable_evidence() -> None:
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeConsumptionService(
        repository=FailingRepository(recovery_state()),
        verifier_provider=StubVerifierProvider(set()),
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
    )

    with pytest.raises(RecoveryCodeConsumptionFailed) as raised:
        service.consume(REQUEST)

    assert str(raised.value) == "recovery-code consumption failed"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert audit_sink.evidence == [
        RecoveryCodeConsumptionAuditEvidence(
            consuming_actor_id=REQUEST.consuming_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            set_id=REQUEST.set_id,
            code_id=None,
            outcome="failed",
            reason="consumption_failed",
            previous_state="unresolved",
            resulting_state="unchanged",
        )
    ]
    assert REQUEST.candidate not in repr(raised.value)
    assert REQUEST.candidate not in repr(audit_sink.evidence)


class RecordingCursor:
    def __init__(self, rows: list[tuple[object, ...]], *, update_rowcount: int = 1) -> None:
        self.rows = rows
        self.update_rowcount = update_rowcount
        self.rowcount = -1
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))
        if "UPDATE app.recovery_codes" in query:
            self.rowcount = self.update_rowcount

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.cursor_instance = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_postgres_repository_locks_exact_set_and_conditionally_consumes_one_row() -> None:
    code_id = UUID(int=13)
    cursor = RecordingCursor([(code_id, "$stub$v=1$opaque-verifier", None, None, None)])
    connection = RecordingConnection(cursor)
    repository = PostgresRecoveryCodeConsumptionRepository(connection)
    verifier = StubVerifierProvider({(REQUEST.candidate, "$stub$v=1$opaque-verifier")})
    service = RecoveryCodeConsumptionService(
        repository=repository,
        verifier_provider=verifier,
        audit_sink=RecordingAuditSink(),
        clock=lambda: FIXED_TIME,
    )

    result = service.consume(REQUEST)

    assert result.completed
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(cursor.executions) == 2
    select_query, select_parameters = cursor.executions[0]
    assert "FOR UPDATE OF recovery_set, recovery_code" in select_query
    assert select_parameters == (REQUEST.set_id, REQUEST.target_actor_id)
    update_query, update_parameters = cursor.executions[1]
    assert "UPDATE app.recovery_codes" in update_query
    assert "consumed_at IS NULL" in update_query
    assert "invalidated_at IS NULL" in update_query
    assert update_parameters == (
        FIXED_TIME,
        REQUEST.consuming_actor_id,
        '{"correlation_id":"correlation-2n","previous_state":"active","provenance":"protected-recovery","reason":"code_consumed","resulting_state":"consumed"}',
        code_id,
        REQUEST.set_id,
        REQUEST.set_id,
        REQUEST.target_actor_id,
    )


def test_postgres_repository_rolls_back_when_conditional_consumption_loses_race() -> None:
    cursor = RecordingCursor(
        [(UUID(int=13), "$stub$v=1$opaque-verifier", None, None, None)],
        update_rowcount=0,
    )
    connection = RecordingConnection(cursor)
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeConsumptionService(
        repository=PostgresRecoveryCodeConsumptionRepository(connection),
        verifier_provider=StubVerifierProvider({(REQUEST.candidate, "$stub$v=1$opaque-verifier")}),
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
    )

    with pytest.raises(RecoveryCodeConsumptionFailed):
        service.consume(REQUEST)

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert audit_sink.evidence == [
        RecoveryCodeConsumptionAuditEvidence(
            consuming_actor_id=REQUEST.consuming_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            set_id=REQUEST.set_id,
            code_id=None,
            outcome="failed",
            reason="consumption_failed",
            previous_state="unresolved",
            resulting_state="unchanged",
        )
    ]


def test_committed_postgres_evidence_keeps_success_truthful_when_audit_sink_fails() -> None:
    cursor = RecordingCursor([(UUID(int=13), "$stub$v=1$opaque-verifier", None, None, None)])
    connection = RecordingConnection(cursor)
    service = RecoveryCodeConsumptionService(
        repository=PostgresRecoveryCodeConsumptionRepository(connection),
        verifier_provider=StubVerifierProvider({(REQUEST.candidate, "$stub$v=1$opaque-verifier")}),
        audit_sink=FailingAuditSink(),
        clock=lambda: FIXED_TIME,
    )

    result = service.consume(REQUEST)

    assert result.completed
    assert result.reason == "code_consumed"
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(cursor.executions) == 2
