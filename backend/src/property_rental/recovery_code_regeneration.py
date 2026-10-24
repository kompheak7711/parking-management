"""Atomic recovery-code regeneration persistence orchestration."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from property_rental.recovery_code_issuance import (
    RecoveryCodePresentation,
    RecoveryCodeSetRecord,
    RecoveryCodeVerifierRecord,
)
from property_rental.recovery_code_security import (
    RecoveryCodeGenerator,
    RecoveryCodeVerifierProvider,
    canonical_recovery_code,
)


@dataclass(frozen=True, slots=True)
class RecoveryCodeRegenerationRequest:
    """Non-secret context established by a protected authorized caller."""

    authorized_actor_id: UUID
    target_actor_id: UUID
    prior_set_id: UUID
    correlation_id: str
    provenance: str

    def __post_init__(self) -> None:
        if any(
            not value or value != value.strip() or not value.isprintable()
            for value in (self.correlation_id, self.provenance)
        ):
            raise ValueError("invalid recovery-code regeneration context")


class RecoveryCodeRegenerationAuthorizer(Protocol):
    """Provider-neutral authorization boundary for a protected regeneration caller."""

    def authorize(self, request: RecoveryCodeRegenerationRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryCodeRegenerationAuditEvidence:
    """Immutable secret-free evidence for one regeneration decision."""

    authorized_actor_id: UUID
    target_actor_id: UUID
    occurred_at: datetime
    correlation_id: str
    prior_set_id: UUID
    replacement_set_id: UUID | None
    code_count: int
    outcome: str
    reason: str
    previous_state: str
    resulting_state: str


class RecoveryCodeRegenerationAuditSink(Protocol):
    """Sink for immutable regeneration evidence without recovery-code material."""

    def record(self, evidence: RecoveryCodeRegenerationAuditEvidence) -> None: ...


class RecoveryCodeRegenerationRepository(Protocol):
    """Atomic prior-set invalidation and replacement-set persistence boundary."""

    def replace_atomically(
        self,
        prior_set_id: UUID,
        record: RecoveryCodeSetRecord,
        occurred_at: datetime,
    ) -> None: ...


class RecoveryCodeRegenerationCursor(Protocol):
    """Bounded cursor operations required by the PostgreSQL adapter."""

    rowcount: int

    def __enter__(self) -> "RecoveryCodeRegenerationCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class RecoveryCodeRegenerationConnection(Protocol):
    """Transaction operations required by the PostgreSQL adapter."""

    def cursor(self) -> RecoveryCodeRegenerationCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class PostgresRecoveryCodeRegenerationRepository:
    """Invalidate one exact prior set and insert one replacement atomically."""

    def __init__(self, connection: RecoveryCodeRegenerationConnection) -> None:
        self._connection = connection

    def replace_atomically(
        self,
        prior_set_id: UUID,
        record: RecoveryCodeSetRecord,
        occurred_at: datetime,
    ) -> None:
        """Lock an active prior set before invalidation and complete replacement."""
        invalidation_provenance = json.dumps(
            {
                "correlation_id": record.correlation_id,
                "previous_state": "active",
                "provenance": record.provenance,
                "reason": "set_regenerated",
                "replacement_set_id": str(record.set_id),
                "resulting_state": "invalidated",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        replacement_provenance = json.dumps(
            {
                "correlation_id": record.correlation_id,
                "previous_set_id": str(prior_set_id),
                "provenance": record.provenance,
                "reason": "set_regenerated",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT set_id, invalidated_at
                    FROM app.recovery_code_sets
                    WHERE set_id = %s
                      AND actor_id = %s
                    FOR UPDATE
                    """,
                    (prior_set_id, record.target_actor_id),
                )
                prior = cursor.fetchone()
                if prior is None or prior[1] is not None:
                    raise RuntimeError("active prior recovery-code set not found")
                cursor.execute(
                    """
                    UPDATE app.recovery_code_sets
                    SET invalidated_at = %s,
                        invalidated_by_actor_id = %s,
                        invalidation_provenance = %s
                    WHERE set_id = %s
                      AND actor_id = %s
                      AND invalidated_at IS NULL
                    """,
                    (
                        occurred_at,
                        record.issued_by_actor_id,
                        invalidation_provenance,
                        prior_set_id,
                        record.target_actor_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("recovery-code set invalidation lost race")
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
                        replacement_provenance,
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
                            replacement_provenance,
                        )
                        for code in record.codes
                    ],
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise


class RecoveryCodeRegenerationRejected(RuntimeError):
    """Generic rejection before any replacement code material is generated."""


class RecoveryCodeRegenerationFailed(RuntimeError):
    """Generic fail-closed regeneration failure without secret material."""


class RecoveryCodeRegenerationService:
    """Compose protected regeneration with atomic replacement persistence."""

    def __init__(
        self,
        *,
        authorizer: RecoveryCodeRegenerationAuthorizer,
        generator: RecoveryCodeGenerator,
        verifier_provider: RecoveryCodeVerifierProvider,
        repository: RecoveryCodeRegenerationRepository,
        audit_sink: RecoveryCodeRegenerationAuditSink,
        code_count: int,
        identifier_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if code_count <= 0:
            raise ValueError("recovery-code count must be positive")
        self._authorizer = authorizer
        self._generator = generator
        self._verifier_provider = verifier_provider
        self._repository = repository
        self._audit_sink = audit_sink
        self._code_count = code_count
        self._identifier_factory = identifier_factory
        self._clock = clock

    def regenerate(self, request: RecoveryCodeRegenerationRequest) -> RecoveryCodePresentation:
        """Invalidate one prior set and persist its replacement before one-time return."""
        occurred_at = self._clock()
        authorized: bool | None = None
        try:
            authorized = self._authorizer.authorize(request)
        except Exception:
            pass

        if authorized is None:
            try:
                self._record(
                    request=request,
                    occurred_at=occurred_at,
                    replacement_set_id=None,
                    code_count=0,
                    outcome="rejected",
                    reason="authorization_unavailable",
                    previous_state="unresolved",
                    resulting_state="unchanged",
                )
            except Exception:
                pass
            raise RecoveryCodeRegenerationRejected("recovery-code regeneration rejected") from None

        if authorized:
            return self._regenerate_authorized(request, occurred_at)
        try:
            self._record(
                request=request,
                occurred_at=occurred_at,
                replacement_set_id=None,
                code_count=0,
                outcome="rejected",
                reason="authorization_denied",
                previous_state="unresolved",
                resulting_state="unchanged",
            )
        except Exception:
            pass
        raise RecoveryCodeRegenerationRejected("recovery-code regeneration rejected") from None

    def _regenerate_authorized(
        self,
        request: RecoveryCodeRegenerationRequest,
        occurred_at: datetime,
    ) -> RecoveryCodePresentation:
        set_id: UUID | None = None
        plaintext_codes: tuple[str, ...] | None = None
        try:
            set_id = self._identifier_factory()
            plaintext_codes = self._replace_atomically(request, occurred_at, set_id)
        except Exception:
            pass

        if set_id is None or plaintext_codes is None:
            try:
                self._record(
                    request=request,
                    occurred_at=occurred_at,
                    replacement_set_id=set_id,
                    code_count=0,
                    outcome="failed",
                    reason="regeneration_failed",
                    previous_state="unresolved",
                    resulting_state="unchanged",
                )
            except Exception:
                pass
            raise RecoveryCodeRegenerationFailed("recovery-code regeneration failed") from None

        try:
            self._record(
                request=request,
                occurred_at=occurred_at,
                replacement_set_id=set_id,
                code_count=len(plaintext_codes),
                outcome="completed",
                reason="set_regenerated",
                previous_state="active",
                resulting_state="invalidated_and_replaced",
            )
        except Exception:
            pass
        return RecoveryCodePresentation(
            set_id=set_id,
            _plaintext_codes=plaintext_codes,
        )

    def _replace_atomically(
        self,
        request: RecoveryCodeRegenerationRequest,
        occurred_at: datetime,
        set_id: UUID,
    ) -> tuple[str, ...]:
        plaintext_codes: list[str] = []
        verifier_records: list[RecoveryCodeVerifierRecord] = []
        for _ in range(self._code_count):
            plaintext = self._generator.generate().get_secret_value()
            if canonical_recovery_code(plaintext) in map(canonical_recovery_code, plaintext_codes):
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
        replacement = RecoveryCodeSetRecord(
            set_id=set_id,
            target_actor_id=request.target_actor_id,
            issued_by_actor_id=request.authorized_actor_id,
            correlation_id=request.correlation_id,
            provenance=request.provenance,
            codes=tuple(verifier_records),
        )
        self._repository.replace_atomically(request.prior_set_id, replacement, occurred_at)
        return tuple(plaintext_codes)

    def _record(
        self,
        *,
        request: RecoveryCodeRegenerationRequest,
        occurred_at: datetime,
        replacement_set_id: UUID | None,
        code_count: int,
        outcome: str,
        reason: str,
        previous_state: str,
        resulting_state: str,
    ) -> None:
        self._audit_sink.record(
            RecoveryCodeRegenerationAuditEvidence(
                authorized_actor_id=request.authorized_actor_id,
                target_actor_id=request.target_actor_id,
                occurred_at=occurred_at,
                correlation_id=request.correlation_id,
                prior_set_id=request.prior_set_id,
                replacement_set_id=replacement_set_id,
                code_count=code_count,
                outcome=outcome,
                reason=reason,
                previous_state=previous_state,
                resulting_state=resulting_state,
            )
        )
