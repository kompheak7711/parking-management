"""Bounded recovery-code set issuance and one-time presentation orchestration."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from property_rental.recovery_code_security import (
    RecoveryCodeGenerator,
    RecoveryCodeVerifierProvider,
    canonical_recovery_code,
)


@dataclass(frozen=True, slots=True)
class RecoveryCodeIssuanceRequest:
    """Non-secret context established by a protected authorized caller."""

    authorized_actor_id: UUID
    target_actor_id: UUID
    correlation_id: str
    provenance: str

    def __post_init__(self) -> None:
        if any(
            not value or value != value.strip() or not value.isprintable()
            for value in (self.correlation_id, self.provenance)
        ):
            raise ValueError("invalid recovery-code issuance context")


class RecoveryCodeIssuanceAuthorizer(Protocol):
    """Provider-neutral authorization boundary for a protected issuance caller."""

    def authorize(self, request: RecoveryCodeIssuanceRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryCodeIssuanceAuditEvidence:
    """Immutable secret-free evidence for one issuance decision."""

    authorized_actor_id: UUID
    target_actor_id: UUID
    occurred_at: datetime
    correlation_id: str
    set_id: UUID | None
    code_count: int
    outcome: str
    reason: str


class RecoveryCodeIssuanceAuditSink(Protocol):
    """Sink for immutable issuance evidence without recovery-code material."""

    def record(self, evidence: RecoveryCodeIssuanceAuditEvidence) -> None: ...


class _NullRecoveryCodeIssuanceAuditSink:
    def record(self, evidence: RecoveryCodeIssuanceAuditEvidence) -> None:
        del evidence


@dataclass(frozen=True, slots=True)
class RecoveryCodeVerifierRecord:
    """One independently identified opaque verifier prepared for persistence."""

    code_id: UUID
    verifier_encoding: str = field(repr=False)
    algorithm: str
    work_factor_metadata: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RecoveryCodeSetRecord:
    """Atomic non-plaintext recovery-code set persistence input."""

    set_id: UUID
    target_actor_id: UUID
    issued_by_actor_id: UUID
    correlation_id: str
    provenance: str
    codes: tuple[RecoveryCodeVerifierRecord, ...]


class RecoveryCodeIssuanceRepository(Protocol):
    """Atomic persistence boundary for one complete verifier set."""

    def persist(self, record: RecoveryCodeSetRecord) -> None: ...


class RecoveryCodeIssuanceCursor(Protocol):
    """Bounded cursor operations required for atomic set insertion."""

    def __enter__(self) -> "RecoveryCodeIssuanceCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None: ...


class RecoveryCodeIssuanceConnection(Protocol):
    """Transaction operations used by the PostgreSQL persistence adapter."""

    def cursor(self) -> RecoveryCodeIssuanceCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgresRecoveryCodeIssuanceRepository:
    """Persist one complete verifier set through the published DB-AUTH-003 tables."""

    def __init__(self, connection: RecoveryCodeIssuanceConnection) -> None:
        self._connection = connection

    def persist(self, record: RecoveryCodeSetRecord) -> None:
        """Insert the set and every verifier before committing the transaction."""
        provenance = json.dumps(
            {"correlation_id": record.correlation_id, "provenance": record.provenance},
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.recovery_code_sets (
                        set_id, actor_id, created_by_actor_id, provenance
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        record.set_id,
                        record.target_actor_id,
                        record.issued_by_actor_id,
                        provenance,
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO app.recovery_codes (
                        code_id, set_id, verifier_encoding, algorithm,
                        work_factor_metadata, provenance
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    [
                        (
                            code.code_id,
                            record.set_id,
                            code.verifier_encoding,
                            code.algorithm,
                            json.dumps(
                                dict(code.work_factor_metadata),
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                            provenance,
                        )
                        for code in record.codes
                    ],
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise


@dataclass(slots=True)
class RecoveryCodePresentation:
    """Caller-owned one-time issuance response with redacted representation."""

    set_id: UUID
    _plaintext_codes: tuple[str, ...] | None = field(repr=False)

    def take_plaintext_codes(self) -> tuple[str, ...]:
        """Release and remove plaintext through the successful issuance response once."""
        plaintext_codes = self._plaintext_codes
        if plaintext_codes is None:
            raise RuntimeError("recovery codes were already presented")
        self._plaintext_codes = None
        return plaintext_codes


class RecoveryCodeIssuanceRejected(RuntimeError):
    """Generic rejection before any recovery-code material is generated."""


class RecoveryCodeIssuanceFailed(RuntimeError):
    """Generic closed failure that never includes recovery-code material."""


class RecoveryCodeIssuanceService:
    """Compose authorized generation, irreversible encoding, and atomic persistence."""

    def __init__(
        self,
        *,
        authorizer: RecoveryCodeIssuanceAuthorizer,
        generator: RecoveryCodeGenerator,
        verifier_provider: RecoveryCodeVerifierProvider,
        repository: RecoveryCodeIssuanceRepository,
        code_count: int,
        identifier_factory: Callable[[], UUID] = uuid4,
        audit_sink: RecoveryCodeIssuanceAuditSink | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if code_count <= 0:
            raise ValueError("recovery-code count must be positive")
        self._authorizer = authorizer
        self._generator = generator
        self._verifier_provider = verifier_provider
        self._repository = repository
        self._audit_sink = audit_sink or _NullRecoveryCodeIssuanceAuditSink()
        self._clock = clock
        self._code_count = code_count
        self._identifier_factory = identifier_factory

    def issue(self, request: RecoveryCodeIssuanceRequest) -> RecoveryCodePresentation:
        """Persist opaque verifiers atomically before returning plaintext exactly once."""
        try:
            authorized = self._authorizer.authorize(request)
        except Exception:
            self._record(request, None, 0, "rejected", "authorization_unavailable")
            raise RecoveryCodeIssuanceRejected("recovery-code issuance rejected") from None
        if not authorized:
            self._record(request, None, 0, "rejected", "authorization_denied")
            raise RecoveryCodeIssuanceRejected("recovery-code issuance rejected")

        try:
            set_id = self._identifier_factory()
            plaintext_codes: list[str] = []
            verifier_records: list[RecoveryCodeVerifierRecord] = []
            for _ in range(self._code_count):
                plaintext = self._generator.generate().get_secret_value()
                if canonical_recovery_code(plaintext) in map(
                    canonical_recovery_code, plaintext_codes
                ):
                    raise RuntimeError("recovery-code generator returned duplicate material")
                verifier = self._verifier_provider.encode(plaintext)
                plaintext_codes.append(plaintext)
                verifier_records.append(
                    RecoveryCodeVerifierRecord(
                        code_id=self._identifier_factory(),
                        verifier_encoding=verifier.verifier_encoding,
                        algorithm=verifier.algorithm,
                        work_factor_metadata=verifier.work_factor_metadata,
                    )
                )

            self._repository.persist(
                RecoveryCodeSetRecord(
                    set_id=set_id,
                    target_actor_id=request.target_actor_id,
                    issued_by_actor_id=request.authorized_actor_id,
                    correlation_id=request.correlation_id,
                    provenance=request.provenance,
                    codes=tuple(verifier_records),
                )
            )
        except Exception:
            self._record(request, locals().get("set_id"), 0, "failed", "issuance_failed")
            raise RecoveryCodeIssuanceFailed("recovery-code issuance failed") from None
        self._record(
            request,
            set_id,
            len(plaintext_codes),
            "completed",
            "one_time_presentation_completed",
        )
        return RecoveryCodePresentation(set_id=set_id, _plaintext_codes=tuple(plaintext_codes))

    def _record(
        self,
        request: RecoveryCodeIssuanceRequest,
        set_id: UUID | None,
        code_count: int,
        outcome: str,
        reason: str,
    ) -> None:
        self._audit_sink.record(
            RecoveryCodeIssuanceAuditEvidence(
                authorized_actor_id=request.authorized_actor_id,
                target_actor_id=request.target_actor_id,
                occurred_at=self._clock(),
                correlation_id=request.correlation_id,
                set_id=set_id,
                code_count=code_count,
                outcome=outcome,
                reason=reason,
            )
        )
