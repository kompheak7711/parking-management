"""Authorized account-recovery orchestration over an atomic persistence boundary."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from property_rental.administrative_recovery import (
    AdministrativeRecoveryAuthorizationService,
    RecoveryAccount,
)
from property_rental.password_security import PasswordCredentialMaterial

RecoveryMode = Literal["recovery_code", "administrative", "emergency"]
RecoveryAuditOutcome = Literal["rejected"]
RecoveryAuditReason = Literal[
    "authorization_denied",
    "authorization_unavailable",
    "invalid_recovery_path",
    "rate_limited",
]
_RECOVERY_REASONS: dict[RecoveryMode, frozenset[str]] = {
    "recovery_code": frozenset({"mfa_recovery"}),
    "administrative": frozenset({"authorized_account_recovery"}),
    "emergency": frozenset({"documented_emergency_recovery"}),
}
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class AccountRecoveryRequest:
    """Trusted non-secret context for one bounded recovery attempt."""

    mode: RecoveryMode
    actor_id: UUID | None
    target_actor_id: UUID
    actor_class: str | None
    target_class: str
    request_source: str
    correlation_id: UUID
    reason: str
    procedure_identity: str | None = None
    authorization_proof_identity: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"recovery_code", "administrative", "emergency"}:
            raise ValueError("invalid account recovery context")
        if not isinstance(self.target_actor_id, UUID) or not isinstance(self.correlation_id, UUID):
            raise ValueError("invalid account recovery context")
        if (
            not self.request_source
            or self.request_source != self.request_source.strip()
            or not self.request_source.isprintable()
            or self.reason not in _RECOVERY_REASONS[self.mode]
        ):
            raise ValueError("invalid account recovery context")
        if self.procedure_identity is not None and not _SAFE_IDENTIFIER.fullmatch(
            self.procedure_identity
        ):
            raise ValueError("invalid account recovery context")
        if self.mode == "emergency" and self.authorization_proof_identity is not None:
            raise ValueError("invalid account recovery context")
        if self.authorization_proof_identity is not None and (
            not self.authorization_proof_identity
            or self.authorization_proof_identity != self.authorization_proof_identity.strip()
            or not self.authorization_proof_identity.isprintable()
        ):
            raise ValueError("invalid account recovery context")


@dataclass(frozen=True, slots=True)
class AccountRecoveryMutation:
    """Explicit credential and MFA changes; verifier material is never represented."""

    password_credential: PasswordCredentialMaterial | None = field(default=None, repr=False)
    reset_mfa: bool = False

    @property
    def requested(self) -> bool:
        return self.password_credential is not None or self.reset_mfa


@dataclass(frozen=True, slots=True)
class AccountRecoveryResult:
    """Bounded non-secret result of one committed recovery transaction."""

    completed: bool
    password_changed: bool
    mfa_disabled: bool
    recovery_code_consumed: bool
    sessions_revoked: int


@dataclass(frozen=True, slots=True)
class AccountRecoveryAuditEvidence:
    """Secret-free evidence for a rejected recovery attempt."""

    actor_id: UUID | None
    target_actor_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    mode: RecoveryMode
    procedure_identity: str | None
    reason: RecoveryAuditReason
    outcome: RecoveryAuditOutcome
    previous_state: str
    resulting_state: str

    @classmethod
    def rejected(
        cls,
        *,
        request: AccountRecoveryRequest,
        occurred_at: datetime,
        reason: RecoveryAuditReason,
    ) -> "AccountRecoveryAuditEvidence":
        return cls(
            actor_id=request.actor_id,
            target_actor_id=request.target_actor_id,
            occurred_at=occurred_at,
            correlation_id=request.correlation_id,
            mode=request.mode,
            procedure_identity=request.procedure_identity,
            reason=reason,
            outcome="rejected",
            previous_state="unresolved",
            resulting_state="unchanged",
        )


class AccountRecoveryAttemptLimiter(Protocol):
    """Account-and-source admission boundary applied before proof or mutation work."""

    def allow(self, account_key: str, source_key: str) -> bool: ...


class AccountRecoveryAuthorizer(Protocol):
    """Trusted proof/authority boundary for the selected recovery mode."""

    def authorize(self, request: AccountRecoveryRequest) -> bool: ...


class RecoveryAccountResolver(Protocol):
    """Resolve the current provider-established recovery class for an actor."""

    def resolve(self, actor_id: UUID) -> RecoveryAccount | None: ...


class PasswordPreauthorizationVerifier(Protocol):
    """Verify an opaque, short-lived password-preauthorization identity."""

    def verify(self, actor_id: UUID, proof_identity: str, correlation_id: UUID) -> bool: ...


class EmergencyProcedureVerifier(Protocol):
    """Verify a registered controlled emergency procedure invocation."""

    def verify(
        self,
        procedure_identity: str,
        target_actor_id: UUID,
        correlation_id: UUID,
    ) -> bool: ...


class TrustedAccountRecoveryAuthorizer:
    """Resolve current classes and verify trusted proof before recovery.

    Request class labels are never authority. The current schema has no durable account-class
    relation, so provider authorization and the later database mutation cannot yet share one
    PostgreSQL transaction. The mutation function revalidates every durable lifecycle predicate
    that the existing schema can express.
    """

    def __init__(
        self,
        *,
        account_resolver: RecoveryAccountResolver,
        password_preauthorization_verifier: PasswordPreauthorizationVerifier,
        emergency_procedure_verifier: EmergencyProcedureVerifier,
        administrative_authorization: AdministrativeRecoveryAuthorizationService,
    ) -> None:
        self._account_resolver = account_resolver
        self._password_preauthorization_verifier = password_preauthorization_verifier
        self._emergency_procedure_verifier = emergency_procedure_verifier
        self._administrative_authorization = administrative_authorization

    def authorize(self, request: AccountRecoveryRequest) -> bool:
        target = self._account_resolver.resolve(request.target_actor_id)
        if target is None or target.account_id != str(request.target_actor_id):
            return False
        if request.mode == "emergency":
            return bool(
                target.account_class == "owner"
                and request.procedure_identity is not None
                and self._emergency_procedure_verifier.verify(
                    request.procedure_identity,
                    request.target_actor_id,
                    request.correlation_id,
                )
            )
        if request.actor_id is None:
            return False
        actor = self._account_resolver.resolve(request.actor_id)
        if actor is None or actor.account_id != str(request.actor_id):
            return False
        proof_identity = request.authorization_proof_identity
        if proof_identity is None:
            return False
        if not self._password_preauthorization_verifier.verify(
            request.actor_id,
            proof_identity,
            request.correlation_id,
        ):
            return False
        if request.mode == "recovery_code":
            return actor.account_id == target.account_id and target.account_class == "owner"
        return self._administrative_authorization.authorize(
            actor=actor,
            target=target,
            correlation_id=str(request.correlation_id),
        ).allowed


class AccountRecoveryRepository(Protocol):
    """Atomic mutation, recovery-code consumption, revocation, and audit boundary."""

    def recover_atomically(
        self,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> AccountRecoveryResult: ...

    def record_rejection(self, evidence: AccountRecoveryAuditEvidence) -> None: ...


class AccountRecoveryCursor(Protocol):
    """Bounded cursor operations used by atomic recovery persistence."""

    rowcount: int

    def __enter__(self) -> "AccountRecoveryCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class AccountRecoveryConnection(Protocol):
    """Transaction operations required by the PostgreSQL adapter."""

    def cursor(self) -> AccountRecoveryCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class RecoveryCodeVerifier(Protocol):
    """Opaque recovery-code verifier used while durable rows are locked."""

    def matches(self, candidate: str, verifier_encoding: str) -> bool: ...


class AccountRecoveryRejected(RuntimeError):
    """Generic rejection without account, authority, or proof disclosure."""


class AccountRecoveryRateLimited(RuntimeError):
    """Generic recovery-specific rate-limit signal."""


class AccountRecoveryFailed(RuntimeError):
    """Generic fail-closed atomic recovery failure."""


class PostgresAccountRecoveryRepository:
    """Commit recovery mutation, code use, session revocation, and audit together."""

    def __init__(
        self,
        *,
        connection: AccountRecoveryConnection,
        recovery_code_verifier: RecoveryCodeVerifier,
    ) -> None:
        self._connection = connection
        self._recovery_code_verifier = recovery_code_verifier

    def recover_atomically(
        self,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> AccountRecoveryResult:
        try:
            with self._connection.cursor() as cursor:
                recovery_code_id = self._resolve_recovery_code(
                    cursor,
                    request,
                    recovery_code,
                )
                result = self._perform_recovery(cursor, request, mutation, recovery_code_id)
            self._connection.commit()
        except AccountRecoveryRejected:
            try:
                self._connection.rollback()
            except Exception:
                pass
            raise
        except Exception as error:
            try:
                self._connection.rollback()
            except Exception:
                pass
            if getattr(error, "sqlstate", None) == "P0001":
                raise AccountRecoveryRejected("account recovery rejected") from None
            raise AccountRecoveryFailed("account recovery failed") from None
        return result

    def record_rejection(self, evidence: AccountRecoveryAuditEvidence) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT app.record_account_recovery_rejection(
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        evidence.actor_id,
                        evidence.target_actor_id,
                        evidence.occurred_at,
                        evidence.correlation_id,
                        evidence.mode,
                        evidence.procedure_identity,
                        evidence.reason,
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise AccountRecoveryFailed("account recovery failed") from None

    def _resolve_recovery_code(
        self,
        cursor: AccountRecoveryCursor,
        request: AccountRecoveryRequest,
        recovery_code: str | None,
    ) -> UUID | None:
        if request.mode != "recovery_code":
            return None
        if recovery_code is None:
            raise AccountRecoveryRejected("account recovery rejected")
        cursor.execute(
            """
            SELECT recovery_code.code_id, recovery_code.verifier_encoding,
                   recovery_code.consumed_at, recovery_code.invalidated_at,
                   recovery_set.invalidated_at
            FROM app.recovery_code_sets AS recovery_set
            JOIN app.recovery_codes AS recovery_code USING (set_id)
            WHERE recovery_set.actor_id = %s
            ORDER BY recovery_code.code_id
            """,
            (request.target_actor_id,),
        )
        rows = cursor.fetchall()
        matches = [
            code_id
            for code_id, verifier, consumed_at, invalidated_at, set_invalidated_at in rows
            if consumed_at is None
            and invalidated_at is None
            and set_invalidated_at is None
            and self._recovery_code_verifier.matches(recovery_code, str(verifier))
        ]
        if len(matches) != 1:
            raise AccountRecoveryRejected("account recovery rejected")
        return UUID(str(matches[0]))

    @staticmethod
    def _perform_recovery(
        cursor: AccountRecoveryCursor,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code_id: UUID | None,
    ) -> AccountRecoveryResult:
        credential = mutation.password_credential
        cursor.execute(
            """
            SELECT password_changed, mfa_disabled, recovery_code_consumed, sessions_revoked
            FROM app.perform_account_recovery(
                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
            )
            """,
            (
                request.actor_id,
                request.target_actor_id,
                request.correlation_id,
                request.mode,
                request.procedure_identity,
                request.reason,
                credential.verifier_encoding if credential is not None else None,
                credential.algorithm if credential is not None else None,
                json.dumps(dict(credential.work_factor_metadata))
                if credential is not None
                else None,
                mutation.reset_mfa,
                recovery_code_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("account recovery function returned no result")
        password_changed, mfa_disabled, recovery_code_consumed, sessions_revoked = row
        if request.mode == "recovery_code":
            if not recovery_code_consumed:
                raise AccountRecoveryRejected("account recovery rejected")
        elif not (password_changed or mfa_disabled):
            raise RuntimeError("recovery request did not mutate credential or MFA state")
        return AccountRecoveryResult(
            completed=True,
            password_changed=bool(password_changed),
            mfa_disabled=bool(mfa_disabled),
            recovery_code_consumed=bool(recovery_code_consumed),
            sessions_revoked=int(str(sessions_revoked)),
        )


class AccountRecoveryService:
    """Enforce fixed recovery modes before delegating one atomic transaction."""

    def __init__(
        self,
        *,
        attempt_limiter: AccountRecoveryAttemptLimiter,
        authorizer: AccountRecoveryAuthorizer,
        repository: AccountRecoveryRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._attempt_limiter = attempt_limiter
        self._authorizer = authorizer
        self._repository = repository
        self._clock = clock

    def recover(
        self,
        *,
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None = None,
    ) -> AccountRecoveryResult:
        """Apply rate limit and authorization before one atomic recovery operation."""
        occurred_at = self._occurred_at()
        if not self._attempt_limiter.allow(
            str(request.target_actor_id),
            request.request_source,
        ):
            self._reject(request, occurred_at, "rate_limited")
            raise AccountRecoveryRateLimited("account recovery rate limited") from None

        if not self._valid_path(request, mutation, recovery_code):
            self._reject(request, occurred_at, "authorization_denied")
            raise AccountRecoveryRejected("account recovery rejected") from None

        try:
            authorized = self._authorizer.authorize(request)
        except Exception:
            self._reject(request, occurred_at, "authorization_unavailable")
            raise AccountRecoveryRejected("account recovery rejected") from None
        if not authorized:
            self._reject(request, occurred_at, "authorization_denied")
            raise AccountRecoveryRejected("account recovery rejected") from None

        try:
            result = self._repository.recover_atomically(request, mutation, recovery_code)
        except AccountRecoveryRejected:
            self._reject(request, occurred_at, "authorization_denied")
            raise AccountRecoveryRejected("account recovery rejected") from None
        except Exception:
            raise AccountRecoveryFailed("account recovery failed") from None
        if not result.completed:
            raise AccountRecoveryFailed("account recovery failed") from None
        return result

    def _occurred_at(self) -> datetime:
        try:
            occurred_at = self._clock()
        except Exception:
            raise AccountRecoveryFailed("account recovery failed") from None
        if occurred_at.utcoffset() is None:
            raise AccountRecoveryFailed("account recovery failed") from None
        return occurred_at

    @staticmethod
    def _valid_path(
        request: AccountRecoveryRequest,
        mutation: AccountRecoveryMutation,
        recovery_code: str | None,
    ) -> bool:
        if request.mode == "administrative":
            return (
                request.actor_id is not None
                and request.actor_id != request.target_actor_id
                and request.procedure_identity is None
                and mutation.requested
                and recovery_code is None
            )
        if request.mode == "recovery_code":
            return (
                request.actor_id == request.target_actor_id
                and request.procedure_identity is None
                and not mutation.requested
                and recovery_code is not None
                and bool(recovery_code)
            )
        return (
            request.actor_id is None
            and request.procedure_identity is not None
            and mutation.requested
            and recovery_code is None
        )

    def _reject(
        self,
        request: AccountRecoveryRequest,
        occurred_at: datetime,
        reason: RecoveryAuditReason,
    ) -> None:
        evidence = AccountRecoveryAuditEvidence.rejected(
            request=request,
            occurred_at=occurred_at,
            reason=reason,
        )
        failed = False
        try:
            self._repository.record_rejection(evidence)
        except Exception:
            failed = True
        if failed:
            raise AccountRecoveryFailed("account recovery failed") from None
