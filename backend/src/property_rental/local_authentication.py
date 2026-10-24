"""Private local username/password authentication foundation."""

import hashlib
import secrets
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, Protocol

from property_rental.password_security import PasswordHashService
from property_rental.visible_text import tidy_spaces, without_zero_width_spaces


class CursorBoundary(Protocol):
    """Bounded cursor operations required by local-account lookup."""

    def __enter__(self) -> "CursorBoundary": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[str, ...]) -> None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


class ConnectionBoundary(Protocol):
    """Existing runtime persistence connection used for account lookup."""

    def cursor(self) -> CursorBoundary: ...


class LocalAccountRepository(Protocol):
    """Persistence boundary required by local authentication."""

    def find_by_username(self, username: str) -> "LocalAccountCredential | None": ...


class AuthenticationAttemptLimiter(Protocol):
    """Account-and-source request admission boundary."""

    def allow(self, account_key: str, source_key: str) -> bool: ...


class SignInWaitBoundary(Protocol):
    """The database count of wrong sign-in tries and the waits it starts (login sub-slice L3b).

    Each method returns the seconds left of an active wait for the username or the source, or
    None. The keys are the normalized username and the request source; an implementation stores
    only digests of them.
    """

    def wait_seconds(self, account_key: str, source_key: str) -> int | None: ...

    def record_wrong_try(self, account_key: str, source_key: str) -> int | None: ...


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
    # The pending one-time password of the Owner's reset, and whether its 24 hours have passed
    # on the database clock (login sub-slice L4, Q-2026-10-24-185).
    one_time_password_id: str | None = None
    one_time_password_expired: bool = False


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """Generic private authentication result with no failure disclosure."""

    is_authenticated: bool
    actor_id: str | None = None
    mfa_policy_class: str | None = None
    # The seconds left of the wait a rejected try met or started (login sub-slice L3b).
    wait_seconds: int | None = None
    # The sha256 digest of the stored verifier the password was checked against, so a later
    # transaction can see that the stored password has not changed without a second Argon2id
    # check (owner answer (a) to Q-2026-10-23-177).
    verifier_digest: bytes | None = field(default=None, repr=False)
    # Set when the password was a one-time password that must be changed first (login
    # sub-slice L4).
    one_time_password_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationAuditEvidence:
    """Secret-free evidence that an authentication decision occurred."""

    outcome: Literal["authenticated", "rejected"]
    reason: Literal["credentials_verified", "credentials_rejected", "rate_limited", "sign_in_wait"]
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


def verifier_digest(verifier_encoding: str) -> bytes:
    """The sha256 digest of a stored password verifier; any password change, also to the same
    password, stores a new verifier with a new salt and so a new digest."""
    return hashlib.sha256(verifier_encoding.encode("utf-8")).digest()


def normalize_local_username(username: str) -> str:
    """Apply the lower-and-space-trim normalization enforced by DB-AUTH-001, after removing
    U+200B, making the username NFC (Q-2026-10-22-169 (a)) and tidying its spaces
    (Q-2026-10-22-170 (a)), as account creation does."""
    nfc = unicodedata.normalize("NFC", without_zero_width_spaces(username))
    return tidy_spaces(nfc).lower()


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
                       account.mfa_policy_class, credential.verifier_encoding,
                       credential.one_time_password_id::text,
                       COALESCE(issued.expires_at <= statement_timestamp(), false)
                FROM app.user_accounts AS account
                JOIN app.password_credentials AS credential USING (actor_id)
                JOIN app.user_account_classes AS classification USING (actor_id)
                LEFT JOIN app.one_time_passwords AS issued
                  ON issued.one_time_password_id = credential.one_time_password_id
                WHERE account.normalized_username = %s
                """,
                (normalized_username,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return LocalAccountCredential(
            actor_id=str(row[0]),
            lifecycle_state=str(row[1]),
            mfa_policy_class=str(row[2]),
            verifier_encoding=str(row[3]),
            one_time_password_id=None if row[4] is None else str(row[4]),
            one_time_password_expired=row[5] is True,
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
        sign_in_waits: SignInWaitBoundary | None = None,
    ) -> None:
        self._repository = repository
        self._password_service = password_service
        self._attempt_limiter = attempt_limiter
        self._audit_sink = audit_sink
        self._sign_in_waits = sign_in_waits
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
        if self._sign_in_waits is not None:
            # A try during a wait is refused before the lookup and the password check, and
            # adds nothing to the count (owner's rule, DL-081).
            waiting = self._sign_in_waits.wait_seconds(account_key, request_source)
            if waiting is not None:
                return self._reject("sign_in_wait", wait_seconds=waiting)

        account = self._repository.find_by_username(username)
        verification = self._password_service.verify_password(
            password,
            account.verifier_encoding if account is not None else self._dummy_verifier_encoding,
        )
        if (
            account is None
            or account.lifecycle_state != "active"
            or not verification.is_valid
            # A one-time password after its 24 hours gets the same answer as a wrong password
            # (owner answer (a) to Q-2026-10-21-153; login sub-slice L4).
            or account.one_time_password_expired
        ):
            # Every refused password check counts as one wrong try, whether or not the account
            # exists, so the answers stay the same for every username.
            started = (
                self._sign_in_waits.record_wrong_try(account_key, request_source)
                if self._sign_in_waits is not None
                else None
            )
            return self._reject("credentials_rejected", wait_seconds=started)

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
            verifier_digest=verifier_digest(account.verifier_encoding),
            one_time_password_id=account.one_time_password_id,
        )

    def _reject(
        self,
        reason: Literal["credentials_rejected", "rate_limited", "sign_in_wait"],
        *,
        wait_seconds: int | None = None,
    ) -> AuthenticationResult:
        self._audit_sink.record(AuthenticationAuditEvidence(outcome="rejected", reason=reason))
        return AuthenticationResult(is_authenticated=False, wait_seconds=wait_seconds)
