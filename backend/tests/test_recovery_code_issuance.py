"""Focused tests for bounded recovery-code set issuance and one-time presentation."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from property_rental.recovery_code_issuance import (
    PostgresRecoveryCodeIssuanceRepository,
    RecoveryCodeIssuanceAuditEvidence,
    RecoveryCodeIssuanceFailed,
    RecoveryCodeIssuanceRejected,
    RecoveryCodeIssuanceRequest,
    RecoveryCodeIssuanceService,
    RecoveryCodeSetRecord,
    RecoveryCodeVerifierRecord,
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
        self.requests: list[RecoveryCodeIssuanceRequest] = []

    def authorize(self, request: RecoveryCodeIssuanceRequest) -> bool:
        self.requests.append(request)
        return self.authorized


class FailingAuthorizer(StubAuthorizer):
    def authorize(self, request: RecoveryCodeIssuanceRequest) -> bool:
        raise RuntimeError("authorization provider failed with sensitive detail")


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
        raise AssertionError("issuance must not consume recovery codes")


class FailingVerifierProvider(StubVerifierProvider):
    def encode(self, recovery_code: str) -> RecoveryCodeVerifierMaterial:
        raise RuntimeError(f"provider exposed {recovery_code}")


class RecordingRepository:
    def __init__(self) -> None:
        self.records: list[RecoveryCodeSetRecord] = []

    def persist(self, record: RecoveryCodeSetRecord) -> None:
        self.records.append(record)


class FailingRepository(RecordingRepository):
    def persist(self, record: RecoveryCodeSetRecord) -> None:
        del record
        raise RuntimeError("persistence failed with internal detail")


class RecordingAuditSink:
    def __init__(self) -> None:
        self.evidence: list[RecoveryCodeIssuanceAuditEvidence] = []

    def record(self, evidence: RecoveryCodeIssuanceAuditEvidence) -> None:
        self.evidence.append(evidence)


FIXED_TIME = datetime(2026, 8, 17, 21, 20, tzinfo=UTC)


class RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.batch_executions: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))

    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None:
        self.batch_executions.append((query, parameters))


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FailingBatchCursor(RecordingCursor):
    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None:
        raise RuntimeError("database rejected verifier batch")


class FailingBatchConnection(RecordingConnection):
    def __init__(self) -> None:
        super().__init__()
        self.cursor_instance = FailingBatchCursor()


class SequenceEntropySource:
    def __init__(self) -> None:
        self.next_byte = 0

    def __call__(self, size: int) -> bytes:
        start = self.next_byte
        self.next_byte += size
        return bytes(range(start, start + size))


def identifier_sequence() -> Iterator[UUID]:
    for value in range(1, 5):
        yield UUID(int=value)


def test_authorized_issuance_persists_independent_verifiers_before_one_time_return() -> None:
    authorizer = StubAuthorizer()
    generator = StubGenerator(["first-secret", "second-secret", "third-secret"])
    verifier_provider = StubVerifierProvider()
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    identifiers = identifier_sequence()
    service = RecoveryCodeIssuanceService(
        authorizer=authorizer,
        generator=generator,
        verifier_provider=verifier_provider,
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=3,
        identifier_factory=lambda: next(identifiers),
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="correlation-2m",
        provenance="protected-enrollment",
    )

    presentation = service.issue(request)

    assert authorizer.requests == [request]
    assert generator.calls == 3
    assert verifier_provider.encoded == ["first-secret", "second-secret", "third-secret"]
    assert presentation.set_id == UUID(int=1)
    assert presentation.take_plaintext_codes() == (
        "first-secret",
        "second-secret",
        "third-secret",
    )
    assert audit_sink.evidence == [
        RecoveryCodeIssuanceAuditEvidence(
            authorized_actor_id=request.authorized_actor_id,
            target_actor_id=request.target_actor_id,
            occurred_at=FIXED_TIME,
            correlation_id=request.correlation_id,
            set_id=UUID(int=1),
            code_count=3,
            outcome="completed",
            reason="one_time_presentation_completed",
        )
    ]
    assert len(repository.records) == 1
    persisted = repository.records[0]
    assert persisted.set_id == presentation.set_id
    assert persisted.target_actor_id == request.target_actor_id
    assert persisted.issued_by_actor_id == request.authorized_actor_id
    assert persisted.correlation_id == request.correlation_id
    assert persisted.provenance == request.provenance
    assert [code.code_id for code in persisted.codes] == [UUID(int=2), UUID(int=3), UUID(int=4)]
    assert [code.verifier_encoding for code in persisted.codes] == [
        "$stub$v=1$first-secret-verifier",
        "$stub$v=1$second-secret-verifier",
        "$stub$v=1$third-secret-verifier",
    ]
    assert all(not hasattr(code, "plaintext") for code in persisted.codes)


def test_unauthorized_caller_is_rejected_before_secret_generation_or_persistence() -> None:
    authorizer = StubAuthorizer(authorized=False)
    generator = StubGenerator(["must-not-be-generated"])
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeIssuanceService(
        authorizer=authorizer,
        generator=generator,
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="denied-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceRejected, match=r"^recovery-code issuance rejected$"):
        service.issue(request)

    assert authorizer.requests == [request]
    assert generator.calls == 0
    assert repository.records == []
    assert audit_sink.evidence[0].outcome == "rejected"
    assert audit_sink.evidence[0].reason == "authorization_denied"
    assert audit_sink.evidence[0].set_id is None
    assert audit_sink.evidence[0].code_count == 0


def test_authorization_provider_failure_is_a_generic_pre_generation_rejection() -> None:
    generator = StubGenerator(["must-not-be-generated"])
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeIssuanceService(
        authorizer=FailingAuthorizer(),
        generator=generator,
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="authorization-failure-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceRejected) as raised:
        service.issue(request)

    assert str(raised.value) == "recovery-code issuance rejected"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert generator.calls == 0
    assert repository.records == []
    assert audit_sink.evidence[0].reason == "authorization_unavailable"


def test_provider_failure_is_generic_and_never_persists_partial_set() -> None:
    secret = "provider-failure-secret"
    repository = RecordingRepository()
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=FailingVerifierProvider(),
        repository=repository,
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="failure-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceFailed) as raised:
        service.issue(request)

    assert str(raised.value) == "recovery-code issuance failed"
    assert secret not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert repository.records == []
    assert audit_sink.evidence[0].outcome == "failed"
    assert audit_sink.evidence[0].reason == "issuance_failed"
    assert audit_sink.evidence[0].code_count == 0


def test_persistence_failure_records_secret_free_generic_failure_evidence() -> None:
    secret = "persistence-failure-secret"
    audit_sink = RecordingAuditSink()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=StubVerifierProvider(),
        repository=FailingRepository(),
        audit_sink=audit_sink,
        clock=lambda: FIXED_TIME,
        code_count=1,
        identifier_factory=lambda: UUID(int=1),
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="persistence-failure-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceFailed) as raised:
        service.issue(request)

    assert secret not in repr(raised.value)
    assert audit_sink.evidence[0].outcome == "failed"
    assert audit_sink.evidence[0].reason == "issuance_failed"
    assert audit_sink.evidence[0].set_id == UUID(int=1)
    assert secret not in repr(audit_sink.evidence[0])


def test_duplicate_generated_material_fails_before_persisting_a_non_independent_set() -> None:
    repository = RecordingRepository()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["duplicate-secret", "duplicate-secret"]),
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        code_count=2,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="duplicate-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceFailed, match=r"^recovery-code issuance failed$"):
        service.issue(request)

    assert repository.records == []


def test_two_spellings_of_one_code_fail_as_duplicate_material_before_persisting() -> None:
    """Login sub-slice L7a review round 3: the duplicate check compares canonical forms, so two
    spellings of one code (whose verifiers would both match it) are refused."""
    repository = RecordingRepository()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["7KQ4-M2XD-9PRT", "7kq4m2xd9prt"]),
        verifier_provider=StubVerifierProvider(),
        repository=repository,
        code_count=2,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="canonical-duplicate-correlation",
        provenance="protected-enrollment",
    )

    with pytest.raises(RecoveryCodeIssuanceFailed, match=r"^recovery-code issuance failed$"):
        service.issue(request)

    assert repository.records == []


def test_issuance_contract_rejects_empty_set_configuration() -> None:
    with pytest.raises(ValueError, match=r"^recovery-code count must be positive$"):
        RecoveryCodeIssuanceService(
            authorizer=StubAuthorizer(),
            generator=StubGenerator([]),
            verifier_provider=StubVerifierProvider(),
            repository=RecordingRepository(),
            code_count=0,
        )


@pytest.mark.parametrize(
    ("correlation_id", "provenance"),
    [("", "protected-enrollment"), ("valid-correlation", "   "), ("bad\nvalue", "valid")],
)
def test_issuance_request_rejects_invalid_nonsecret_context(
    correlation_id: str,
    provenance: str,
) -> None:
    with pytest.raises(ValueError, match="invalid recovery-code issuance context"):
        RecoveryCodeIssuanceRequest(
            authorized_actor_id=UUID(int=10),
            target_actor_id=UUID(int=11),
            correlation_id=correlation_id,
            provenance=provenance,
        )


def test_postgres_repository_commits_complete_set_and_verifiers_as_one_transaction() -> None:
    connection = RecordingConnection()
    repository = PostgresRecoveryCodeIssuanceRepository(connection)
    record = RecoveryCodeSetRecord(
        set_id=UUID(int=1),
        target_actor_id=UUID(int=10),
        issued_by_actor_id=UUID(int=11),
        correlation_id="transaction-correlation",
        provenance="protected-enrollment",
        codes=(
            RecoveryCodeVerifierRecord(
                code_id=UUID(int=2),
                verifier_encoding="$stub$v=1$first-verifier",
                algorithm="stub",
                work_factor_metadata={"cost": 1},
            ),
            RecoveryCodeVerifierRecord(
                code_id=UUID(int=3),
                verifier_encoding="$stub$v=1$second-verifier",
                algorithm="stub",
                work_factor_metadata={"cost": 2},
            ),
        ),
    )

    repository.persist(record)

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(connection.cursor_instance.executions) == 1
    set_query, set_parameters = connection.cursor_instance.executions[0]
    assert "INSERT INTO app.recovery_code_sets" in set_query
    assert set_parameters == (
        UUID(int=1),
        UUID(int=10),
        UUID(int=11),
        '{"correlation_id":"transaction-correlation","provenance":"protected-enrollment"}',
    )
    assert len(connection.cursor_instance.batch_executions) == 1
    code_query, code_parameters = connection.cursor_instance.batch_executions[0]
    assert "INSERT INTO app.recovery_codes" in code_query
    assert code_parameters == [
        (
            UUID(int=2),
            UUID(int=1),
            "$stub$v=1$first-verifier",
            "stub",
            '{"cost":1}',
            '{"correlation_id":"transaction-correlation","provenance":"protected-enrollment"}',
        ),
        (
            UUID(int=3),
            UUID(int=1),
            "$stub$v=1$second-verifier",
            "stub",
            '{"cost":2}',
            '{"correlation_id":"transaction-correlation","provenance":"protected-enrollment"}',
        ),
    ]


def test_postgres_repository_rolls_back_deterministically_on_partial_insert_failure() -> None:
    connection = FailingBatchConnection()
    repository = PostgresRecoveryCodeIssuanceRepository(connection)
    record = RecoveryCodeSetRecord(
        set_id=UUID(int=1),
        target_actor_id=UUID(int=10),
        issued_by_actor_id=UUID(int=11),
        correlation_id="rollback-correlation",
        provenance="protected-enrollment",
        codes=(
            RecoveryCodeVerifierRecord(
                code_id=UUID(int=2),
                verifier_encoding="$stub$v=1$verifier",
                algorithm="stub",
                work_factor_metadata={"cost": 1},
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="database rejected verifier batch"):
        repository.persist(record)

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_issuance_does_not_represent_log_or_retain_plaintext_in_service_state(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "one-time-presentation-secret"

    repository = RecordingRepository()
    provider = StubVerifierProvider()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator([secret]),
        verifier_provider=provider,
        repository=repository,
        code_count=1,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="nonrepresentation-correlation",
        provenance="protected-enrollment",
    )

    with caplog.at_level(logging.DEBUG):
        presentation = service.issue(request)

    captured = capsys.readouterr()
    verifier = repository.records[0].codes[0].verifier_encoding
    assert secret not in repr(presentation)
    assert presentation.take_plaintext_codes() == (secret,)
    assert secret not in repr(repository.records[0])
    assert verifier not in repr(repository.records[0])
    assert not hasattr(service, "_plaintext_codes")
    assert secret not in repr(vars(service))
    assert secret not in captured.out
    assert secret not in captured.err
    assert secret not in caplog.text


def test_caller_owned_presentation_releases_plaintext_only_once() -> None:
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=StubGenerator(["single-presentation-secret"]),
        verifier_provider=StubVerifierProvider(),
        repository=RecordingRepository(),
        code_count=1,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="one-time-correlation",
        provenance="protected-enrollment",
    )

    presentation = service.issue(request)

    assert presentation.take_plaintext_codes() == ("single-presentation-secret",)
    with pytest.raises(RuntimeError, match=r"^recovery codes were already presented$"):
        presentation.take_plaintext_codes()


def test_published_generator_and_verifier_satisfy_issuance_provider_contracts() -> None:
    verifier_provider = Argon2idRecoveryCodeVerifierProvider()
    repository = RecordingRepository()
    service = RecoveryCodeIssuanceService(
        authorizer=StubAuthorizer(),
        generator=SecureRecoveryCodeGenerator(entropy_source=SequenceEntropySource()),
        verifier_provider=verifier_provider,
        repository=repository,
        code_count=2,
    )
    request = RecoveryCodeIssuanceRequest(
        authorized_actor_id=UUID(int=10),
        target_actor_id=UUID(int=11),
        correlation_id="provider-contract-correlation",
        provenance="protected-enrollment",
    )

    presentation = service.issue(request)
    plaintext_codes = presentation.take_plaintext_codes()

    assert len(plaintext_codes) == 2
    assert plaintext_codes[0] != plaintext_codes[1]
    assert len(repository.records[0].codes) == 2
    assert all(
        verifier_provider.matches(plaintext, verifier.verifier_encoding)
        for plaintext, verifier in zip(plaintext_codes, repository.records[0].codes, strict=True)
    )
