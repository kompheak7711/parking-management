"""Private local username/password authentication foundation."""

import secrets
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Literal, Protocol

from property_rental.password_security import PasswordHashService
from property_rental.visible_text import without_zero_width_spaces


class CursorBoundary(Protocol):
    """Bounded cursor operations required by local-account lookup."""

    def __enter__(self) -> "CursorBoundary": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[str, ...]) -> None: ...

    def fetchone(self) -> tuple[str, str, str, str] | None: ...


class ConnectionBoundary(Protocol):
    """Existing runtime persistence connection used for account lookup."""

    def cursor(self) -> CursorBoundary: ...


class LocalAccountRepository(Protocol):
    """Persistence boundary required by local authentication."""

    def find_by_username(self, username: str) -> "LocalAccountCredential | None": ...


class AuthenticationAttemptLimiter(Protocol):
    """Account-and-source request admission boundary."""

    def allow(self, account_key: str, source_key: str) -> bool: ...


class AuthenticationAuditSink(Protocol):
    """Sink for secret-free authentication decision evidence."""

    def record(self, evidence: "AuthenticationAuditEvidence") -> None: ...


@dataclass(frozen=True, slots=True)
class LocalAccountCredential:
    """Bounded account and password-verifier values needed for authentication."""

    actor_id: str
    lifecycle_state: str
    mfa_policy_class: str
    verifier_encoding: str


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """Generic private authentication result with no failure disclosure."""

    is_authenticated: bool
    actor_id: str | None = None
    mfa_policy_class: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationAuditEvidence:
    """Secret-free evidence that an authentication decision occurred."""

    outcome: Literal["authenticated", "rejected"]
    reason: Literal["credentials_verified", "credentials_rejected", "rate_limited"]
    actor_id: str | None = None


class BoundedAuthenticationAttemptLimiter:
    """Thread-safe rolling-window request bounds for account and source keys."""

    def __init__(
        self,
        *,
        max_attempts_per_account: int,
        max_attempts_per_source: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts_per_account <= 0 or max_attempts_per_source <= 0:
            raise ValueError("authentication attempt limits must be positive")
        if window_seconds <= 0:
            raise ValueError("authentication attempt window must be positive")
        self._max_attempts_per_account = max_attempts_per_account
        self._max_attempts_per_source = max_attempts_per_source
        self._window_seconds = window_seconds
        self._clock = clock
        self._account_attempts: dict[str, deque[float]] = {}
        self._source_attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, account_key: str, source_key: str) -> bool:
        """Consume one attempt only when both configured bounds allow it."""
        with self._lock:
            now = self._clock()
            account_attempts = self._active_attempts(self._account_attempts, account_key, now)
            source_attempts = self._active_attempts(self._source_attempts, source_key, now)
            if (
                len(account_attempts) >= self._max_attempts_per_account
                or len(source_attempts) >= self._max_attempts_per_source
            ):
                return False
            self._account_attempts[account_key] = account_attempts
            self._source_attempts[source_key] = source_attempts
            account_attempts.append(now)
            source_attempts.append(now)
            return True

    def _active_attempts(
        self,
        attempts_by_key: dict[str, deque[float]],
        key: str,
        now: float,
    ) -> deque[float]:
        attempts = attempts_by_key.get(key)
        if attempts is None:
            return deque()
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            del attempts_by_key[key]
        return attempts


def normalize_local_username(username: str) -> str:
    """Apply the lower-and-space-trim normalization enforced by DB-AUTH-001, after removing
    U+200B and making the username NFC, as account creation does (Q-2026-10-22-169 (a))."""
    return unicodedata.normalize("NFC", without_zero_width_spaces(username)).strip(" ").lower()


class PostgresLocalAccountRepository:
    """Read local account and credential state through the existing runtime boundary."""

    def __init__(self, connection: ConnectionBoundary) -> None:
        self._connection = connection

    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        """Look up one credential by the transactionally unique normalized username.

        An account without an account class is never found, so it cannot sign in (fail closed).
        """
        normalized_username = normalize_local_username(username)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT account.actor_id::text, account.lifecycle_state,
                       account.mfa_policy_class, credential.verifier_encoding
                FROM app.user_accounts AS account
                JOIN app.password_credentials AS credential USING (actor_id)
                JOIN app.user_account_classes AS classification USING (actor_id)
                WHERE account.normalized_username = %s
                """,
                (normalized_username,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return LocalAccountCredential(
            actor_id=row[0],
            lifecycle_state=row[1],
            mfa_policy_class=row[2],
            verifier_encoding=row[3],
        )


class LocalAuthenticationService:
    """Verify local credentials without exposing account or rejection state."""

    def __init__(
        self,
        *,
        repository: LocalAccountRepository,
        password_service: PasswordHashService,
        attempt_limiter: AuthenticationAttemptLimiter,
        audit_sink: AuthenticationAuditSink,
    ) -> None:
        self._repository = repository
        self._password_service = password_service
        self._attempt_limiter = attempt_limiter
        self._audit_sink = audit_sink
        self._dummy_verifier_encoding = password_service.hash_password(
            secrets.token_urlsafe(32)
        ).verifier_encoding

    def authenticate(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
    ) -> AuthenticationResult:
        """Return only an authenticated actor or a generic rejection."""
        account_key = normalize_local_username(username)
        if not self._attempt_limiter.allow(account_key, request_source):
            return self._reject("rate_limited")

        account = self._repository.find_by_username(username)
        verification = self._password_service.verify_password(
            password,
            account.verifier_encoding if account is not None else self._dummy_verifier_encoding,
        )
        if account is None or account.lifecycle_state != "active" or not verification.is_valid:
            return self._reject("credentials_rejected")

        evidence = AuthenticationAuditEvidence(
            outcome="authenticated",
            reason="credentials_verified",
            actor_id=account.actor_id,
        )
        self._audit_sink.record(evidence)
        return AuthenticationResult(
            is_authenticated=True,
            actor_id=account.actor_id,
            mfa_policy_class=account.mfa_policy_class,
        )

    def _reject(
        self,
        reason: Literal["credentials_rejected", "rate_limited"],
    ) -> AuthenticationResult:
        self._audit_sink.record(AuthenticationAuditEvidence(outcome="rejected", reason=reason))
        return AuthenticationResult(is_authenticated=False)
