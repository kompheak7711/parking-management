"""Focused tests for atomic recovery-code regeneration orchestration."""

import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from property_rental.recovery_code_issuance import (
    RecoveryCodeSetRecord,
    RecoveryCodeVerifierRecord,
)
from property_rental.recovery_code_regeneration import (
    PostgresRecoveryCodeRegenerationRepository,
    RecoveryCodeRegenerationAuditEvidence,
    RecoveryCodeRegenerationFailed,
    RecoveryCodeRegenerationRejected,
    RecoveryCodeRegenerationRequest,
    RecoveryCodeRegenerationService,
)
from property_rental.recovery_code_security import (
    Argon2idRecoveryCodeVerifierProvider,
    RecoveryCodeMaterial,
    RecoveryCodeVerifierMaterial,
    SecureRecoveryCodeGenerator,
)


class StubAuthorizer:
    def __init__(self, authorized: bool = True) -> None:
        self.authorized = authorized
        self.requests: list[RecoveryCodeRegenerationRequest] = []

    def authorize(self, request: RecoveryCodeRegenerationRequest) -> bool:
        self.requests.append(request)
        return self.authorized


class FailingAuthorizer(StubAuthorizer):
    def authorize(self, request: RecoveryCodeRegenerationRequest) -> bool:
        del request
        raise RuntimeError("authorization provider failed with internal detail")


class StubGenerator:
    def __init__(self, values: list[str]) -> None:
        self._values: Iterator[str] = iter(values)
        self.calls = 0

    def generate(self) -> RecoveryCodeMaterial:
        self.calls += 1
        return RecoveryCodeMaterial(next(self._values))


class StubVerifierProvider:
    def __init__(self) -> None:
        self.encoded: list[str] = []

    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial:
        self.encoded.append(recovery_code)
        return RecoveryCodeVerifierMaterial(
            verifier_encoding=f"$stub$v=1${recovery_code}-verifier",
            algorithm="stub",
            work_factor_metadata={"cost": 1},
        )

    def matches(self, candidate: str, verifier_encoding: str) -> bool:
        raise AssertionError("regeneration must not consume recovery codes")


class FailingVerifierProvider(StubVerifierProvider):
    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial:
        raise RuntimeError(f"verifier failed for {recovery_code}")


class SequenceEntropySource:
    def __init__(self) -> None:
        self.next_byte = 0

    def __call__(self, size: int) -> bytes:
        start = self.next_byte
        self.next_byte += size
        return bytes(range(start, start + size))


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, RecoveryCodeSetRecord, datetime]] = []

    def replace_atomically(
        self,
        prior_set_id: UUID,
        record: RecoveryCodeSetRecord,
        occurred_at: datetime,
    ) -> None:
        self.calls.append((prior_set_id, record, occurred_at))


class FailingRepository(RecordingRepository):
    def replace_atomically(
        self,
        prior_set_id: UUID,
        record: RecoveryCodeSetRecord,
        occurred_at: datetime,
    ) -> None:
        del prior_set_id, record, occurred_at
        raise RuntimeError("database failure with internal detail")


class RecordingAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryCodeRegenerationAuditEvidence] = []

    def record(self, evidence: RecoveryCodeRegenerationAuditEvidence) -> None:
        self.evidence.append(evidence)


class ExceptionObservingAuditSink(RecordingAuditSink):
    def __init__(self) -> None:
        super().__init__()
        self.active_exceptions: list[BaseException | None] = []

    def record(self, evidence: RecoveryCodeRegenerationAuditEvidence) -> None:
        self.active_exceptions.append(sys.exception())
        super().record(evidence)


class FailingAuditSink:
    def record(self, evidence: RecoveryCodeRegenerationAuditEvidence) -> None:
        del evidence
        raise RuntimeError("secondary audit sink failed with internal detail")


class RecordingCursor:
    def __init__(self, prior_row: tuple[object, ...] | None = (UUID(int=12), None)) -> None:
        self.prior_row = prior_row
        self.rowcount = -1
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.batch_executions: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))
        if "UPDATE app.recovery_code_sets" in query:
            self.rowcount = 1

    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None:
        self.batch_executions.append((query, parameters))

    def fetchone(self) -> tuple[object, ...] | None:
        return self.prior_row


class FailingBatchCursor(RecordingCursor):
    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None:
        del query, parameters
        raise RuntimeError("replacement verifier insert failed")


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


FIXED_TIME = datetime(2026, 8, 18, 3, 30, tzinfo=UTC)
REQUEST = RecoveryCodeRegenerationRequest(
    authorized_actor_id=UUID(int=10),
    target_actor_id=UUID(int=11),
    prior_set_id=UUID(int=12),
    correlation_id="correlation-2o",
    provenance="protected-regeneration",
)


def identifier_sequence() -> Iterator[UUID]:
    for value in range(20, 23):
        yield UUID(int=value)


def test_authorized_regeneration_atomically_replaces_prior_set_before_one_time_return() -> None:
    authorizer = StubAuthorizer()
    generator = StubGenerator(["first-replacement-secret", "second-replacement-secret"])
    verifier_provider = StubVerifierProvider()
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    identifiers = identifier_sequence()
    service = RecoveryCodeRegenerationService(
        authorizer=authorizer,
        generator=generator,
        verifier_provider=verifier_provider,
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=2,
        identifier_factory=lambda: next(identifiers),
    )

    presentation = service.regenerate(REQUEST)

    assert authorizer.requests == [REQUEST]
    assert generator.calls == 2
    assert verifier_provider.encoded == [
        "first-replacement-secret",
        "second-replacement-secret",
    ]
    assert presentation.set_id == UUID(int=20)
    assert presentation.take_plaintext_codes() == (
        "first-replacement-secret",
        "second-replacement-secret",
    )
    with pytest.raises(RuntimeError, match=r"^recovery codes were already presented$"):
        presentation.take_plaintext_codes()
    assert len(repository.calls) == 1
    prior_set_id, replacement, occurred_at = repository.calls[0]
    assert prior_set_id == REQUEST.prior_set_id
    assert occurred_at == FIXED_TIME
    assert replacement.set_id == UUID(int=20)
    assert replacement.target_actor_id == REQUEST.target_actor_id
    assert replacement.issued_by_actor_id == REQUEST.authorized_actor_id
    assert [code.code_id for code in replacement.codes] == [UUID(int=21), UUID(int=22)]
    assert audit_sink.evidence == [
        RecoveryCodeRegenerationAuditEvidence(
            authorized_actor_id=REQUEST.authorized_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            prior_set_id=REQUEST.prior_set_id,
            replacement_set_id=UUID(int=20),
            code_count=2,
            outcome="completed",
            reason="set_regenerated",
            previous_state="active",
            resulting_state="invalidated_and_replaced",
        )
    ]


def test_unauthorized_regeneration_is_rejected_before_secret_generation() -> None:
    generator = StubGenerator(["must-not-be-generated"])
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(authorized=False),
        generator=generator,
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
    )

    with pytest.raises(
        RecoveryCodeRegenerationRejected,
        match=r"^recovery-code regeneration rejected$",
    ):
        service.regenerate(REQUEST)

    assert generator.calls == 0
    assert repository.calls == []
    assert audit_sink.evidence == [
        RecoveryCodeRegenerationAuditEvidence(
            authorized_actor_id=REQUEST.authorized_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            prior_set_id=REQUEST.prior_set_id,
            replacement_set_id=None,
            code_count=0,
            outcome="rejected",
            reason="authorization_denied",
            previous_state="unresolved",
            resulting_state="unchanged",
        )
    ]


def test_authorization_failure_is_a_generic_pre_generation_rejection() -> None:
    generator = StubGenerator(["must-not-be-generated"])
    audit_sink = ExceptionObservingAuditSink()
    service = RecoveryCodeRegenerationService(
        authorizer=FailingAuthorizer(),
        generator=generator,
        verifier_provider=StubVerifierProvider(),
        repository=RecordingRepository(),
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
    )

    with pytest.raises(RecoveryCodeRegenerationRejected) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration rejected"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is True
    assert audit_sink.active_exceptions == [None]
    assert generator.calls == 0
    assert audit_sink.evidence[0].reason == "authorization_unavailable"
    assert audit_sink.evidence[0].outcome == "rejected"


def test_rejection_audit_failure_remains_generic_and_pre_generation() -> None:
    generator = StubGenerator(["must-not-be-generated"])
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(authorized=False),
        generator=generator,
        verifier_provider=StubVerifierProvider(),
        repository=RecordingRepository(),
        audit_sink=FailingAuditSink(),
        code_count=1,
    )

    with pytest.raises(RecoveryCodeRegenerationRejected) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration rejected"
    assert raised.value.__cause__ is None
    assert generator.calls == 0


def test_replacement_persistence_failure_is_generic_and_preserves_prior_set() -> None:
    secret = "replacement-persistence-secret"
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=StubVerifierProvider(),
        repository=FailingRepository(),
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
        identifier_factory=lambda: UUID(int=20),
    )

    with pytest.raises(RecoveryCodeRegenerationFailed) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert raised.value.__suppress_context__ is True
    assert secret not in repr(raised.value)
    assert audit_sink.evidence == [
        RecoveryCodeRegenerationAuditEvidence(
            authorized_actor_id=REQUEST.authorized_actor_id,
            target_actor_id=REQUEST.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=REQUEST.correlation_id,
            prior_set_id=REQUEST.prior_set_id,
            replacement_set_id=UUID(int=20),
            code_count=0,
            outcome="failed",
            reason="regeneration_failed",
            previous_state="unresolved",
            resulting_state="unchanged",
        )
    ]
    assert secret not in repr(audit_sink.evidence)


def test_failure_audit_unavailability_preserves_one_generic_closed_failure() -> None:
    secret = "audit-unavailable-secret"
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=StubVerifierProvider(),
        repository=FailingRepository(),
        audit_sink=FailingAuditSink(),
        code_count=1,
        identifier_factory=lambda: UUID(int=20),
    )

    with pytest.raises(RecoveryCodeRegenerationFailed) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert secret not in repr(raised.value)


def test_verifier_failure_does_not_chain_generated_plaintext() -> None:
    secret = "verifier-provider-secret"
    audit_sink = ExceptionObservingAuditSink()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=FailingVerifierProvider(),
        repository=RecordingRepository(),
        audit_sink=audit_sink,
        code_count=1,
    )

    with pytest.raises(RecoveryCodeRegenerationFailed) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert secret not in repr(raised.value)
    assert audit_sink.active_exceptions == [None]
    traceback = raised.value.__traceback__
    while traceback is not None:
        if (
            traceback.tb_frame.f_globals.get("__name__")
            == "property_rental.recovery_code_regeneration"
        ):
            assert secret not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next


def test_identifier_failure_is_generic_and_audited_without_active_exception() -> None:
    audit_sink = ExceptionObservingAuditSink()

    def fail_identifier() -> UUID:
        raise RuntimeError("identifier provider failed with internal detail")

    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["must-not-be-generated"]),
        verifier_provider=StubVerifierProvider(),
        repository=RecordingRepository(),
        audit_sink=audit_sink,
        identifier_factory=fail_identifier,
        code_count=1,
    )

    with pytest.raises(RecoveryCodeRegenerationFailed) as raised:
        service.regenerate(REQUEST)

    assert str(raised.value) == "recovery-code regeneration failed"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert audit_sink.active_exceptions == [None]
    assert audit_sink.evidence[0].reason == "regeneration_failed"
    assert audit_sink.evidence[0].replacement_set_id is None


def test_duplicate_replacement_material_fails_before_prior_set_invalidation() -> None:
    repository = RecordingRepository()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["duplicate-secret", "duplicate-secret"]),
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=RecordingAuditSink(),
        code_count=2,
    )

    with pytest.raises(
        RecoveryCodeRegenerationFailed,
        match=r"^recovery-code regeneration failed$",
    ):
        service.regenerate(REQUEST)

    assert repository.calls == []


def test_two_spellings_of_one_code_fail_before_prior_set_invalidation() -> None:
    """Login sub-slice L7a review round 3: the duplicate check compares canonical forms, so two
    spellings of one code (whose verifiers would both match it) are refused."""
    repository = RecordingRepository()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["7KQ4-M2XD-9PRT", "7kq4m2xd9prt"]),
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=RecordingAuditSink(),
        code_count=2,
    )

    with pytest.raises(
        RecoveryCodeRegenerationFailed,
        match=r"^recovery-code regeneration failed$",
    ):
        service.regenerate(REQUEST)

    assert repository.calls == []


def test_published_providers_create_independently_salted_replacement_verifiers() -> None:
    verifier_provider = Argon2idRecoveryCodeVerifierProvider()
    repository = RecordingRepository()
    identifiers = identifier_sequence()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=SecureRecoveryCodeGenerator(entropy_source=SequenceEntropySource()),
        verifier_provider=verifier_provider,
        repository=repository,
        audit_sink=RecordingAuditSink(),
        code_count=2,
        identifier_factory=lambda: next(identifiers),
    )

    plaintext_codes = service.regenerate(REQUEST).take_plaintext_codes()
    replacement = repository.calls[0][1]

    assert plaintext_codes[0] != plaintext_codes[1]
    assert replacement.codes[0].verifier_encoding != replacement.codes[1].verifier_encoding
    assert all(
        verifier_provider.matches(plaintext, verifier.verifier_encoding)
        for plaintext, verifier in zip(plaintext_codes, replacement.codes, strict=True)
    )


@pytest.mark.parametrize(
    ("correlation_id", "provenance"),
    [("", "protected-regeneration"), ("correlation", "   "), ("bad\nvalue", "valid")],
)
def test_regeneration_request_rejects_invalid_nonsecret_context(
    correlation_id: str,
    provenance: str,
) -> None:
    with pytest.raises(ValueError, match="invalid recovery-code regeneration context"):
        RecoveryCodeRegenerationRequest(
            authorized_actor_id=UUID(int=10),
            target_actor_id=UUID(int=11),
            prior_set_id=UUID(int=12),
            correlation_id=correlation_id,
            provenance=provenance,
        )


def test_persisted_regeneration_remains_truthful_when_secondary_audit_sink_fails() -> None:
    repository = RecordingRepository()
    service = RecoveryCodeRegenerationService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["sink-failure-secret"]),
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=FailingAuditSink(),
        clock=lambda: FIXED_TIME,
        code_count=1,
        identifier_factory=lambda: UUID(int=20),
    )

    presentation = service.regenerate(REQUEST)

    assert len(repository.calls) == 1
    assert presentation.set_id == UUID(int=20)
    assert presentation.take_plaintext_codes() == ("sink-failure-secret",)


def test_postgres_repository_locks_invalidates_and_inserts_replacement_in_one_transaction() -> None:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    repository = PostgresRecoveryCodeRegenerationRepository(connection)
    replacement = RecoveryCodeSetRecord(
        set_id=UUID(int=20),
        target_actor_id=REQUEST.target_actor_id,
        issued_by_actor_id=REQUEST.authorized_actor_id,
        correlation_id=REQUEST.correlation_id,
        provenance=REQUEST.provenance,
        codes=(
            RecoveryCodeVerifierRecord(
                code_id=UUID(int=21),
                verifier_encoding="$stub$v=1$replacement-verifier",
                algorithm="stub",
                work_factor_metadata={"cost": 1},
            ),
        ),
    )

    repository.replace_atomically(REQUEST.prior_set_id, replacement, FIXED_TIME)

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(cursor.executions) == 3
    lock_query, lock_parameters = cursor.executions[0]
    assert "FROM app.recovery_code_sets" in lock_query
    assert "FOR UPDATE" in lock_query
    assert lock_parameters == (REQUEST.prior_set_id, REQUEST.target_actor_id)
    invalidation_query, invalidation_parameters = cursor.executions[1]
    assert "UPDATE app.recovery_code_sets" in invalidation_query
    assert "invalidated_at IS NULL" in invalidation_query
    assert invalidation_parameters == (
        FIXED_TIME,
        REQUEST.authorized_actor_id,
        '{"correlation_id":"correlation-2o","previous_state":"active","provenance":"protected-regeneration","reason":"set_regenerated","replacement_set_id":"00000000-0000-0000-0000-000000000014","resulting_state":"invalidated"}',
        REQUEST.prior_set_id,
        REQUEST.target_actor_id,
    )
    insert_query, insert_parameters = cursor.executions[2]
    assert "INSERT INTO app.recovery_code_sets" in insert_query
    assert insert_parameters == (
        replacement.set_id,
        replacement.target_actor_id,
        replacement.issued_by_actor_id,
        '{"correlation_id":"correlation-2o","previous_set_id":"00000000-0000-0000-0000-00000000000c","provenance":"protected-regeneration","reason":"set_regenerated"}',
    )
    assert len(cursor.batch_executions) == 1
    code_query, code_parameters = cursor.batch_executions[0]
    assert "INSERT INTO app.recovery_codes" in code_query
    assert code_parameters[0][:5] == (
        UUID(int=21),
        UUID(int=20),
        "$stub$v=1$replacement-verifier",
        "stub",
        '{"cost":1}',
    )


def test_postgres_repository_rolls_back_when_replacement_insert_fails() -> None:
    connection = RecordingConnection(FailingBatchCursor())
    repository = PostgresRecoveryCodeRegenerationRepository(connection)
    replacement = RecoveryCodeSetRecord(
        set_id=UUID(int=20),
        target_actor_id=REQUEST.target_actor_id,
        issued_by_actor_id=REQUEST.authorized_actor_id,
        correlation_id=REQUEST.correlation_id,
        provenance=REQUEST.provenance,
        codes=(
            RecoveryCodeVerifierRecord(
                code_id=UUID(int=21),
                verifier_encoding="$stub$v=1$replacement-verifier",
                algorithm="stub",
                work_factor_metadata={"cost": 1},
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="replacement verifier insert failed"):
        repository.replace_atomically(REQUEST.prior_set_id, replacement, FIXED_TIME)

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_postgres_repository_rejects_missing_or_invalidated_prior_set_without_replacement() -> None:
    for prior_row in (None, (REQUEST.prior_set_id, FIXED_TIME)):
        cursor = RecordingCursor(prior_row)
        connection = RecordingConnection(cursor)
        repository = PostgresRecoveryCodeRegenerationRepository(connection)
        replacement = RecoveryCodeSetRecord(
            set_id=UUID(int=20),
            target_actor_id=REQUEST.target_actor_id,
            issued_by_actor_id=REQUEST.authorized_actor_id,
            correlation_id=REQUEST.correlation_id,
            provenance=REQUEST.provenance,
            codes=(),
        )

        with pytest.raises(RuntimeError, match="active prior recovery-code set not found"):
            repository.replace_atomically(REQUEST.prior_set_id, replacement, FIXED_TIME)

        assert connection.commits == 0
        assert connection.rollbacks == 1
        assert len(cursor.executions) == 1
