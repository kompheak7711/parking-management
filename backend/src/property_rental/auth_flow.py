"""Password sign-in, the session read and sign-out on PostgreSQL (login sub-slice L3a-1, DL-081).

`PostgresAuthenticationFlow` implements the sign-in part of `AuthenticationFlow`. The password
check is the existing `LocalAuthenticationService` (Argon2id, a dummy verifier for unknown names,
one generic rejection). A session is a row of `app.browser_sessions` that keeps only the sha256
digest of a random token; the token itself goes only into the `__Host-prm_session` cookie. Every
time is the database clock. An account whose MFA policy is `required` gets no session before the
MFA challenge, which login sub-slice L3c builds; until then that challenge answers unavailable.
Wrong tries are counted in the database (login sub-slice L3b): a try during a wait is refused
before the password check, and a sign-in that makes a session clears the count.
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Final, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import IsolationLevel

from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationResult,
    AuthenticationUnavailable,
    MfaEnrollmentResult,
    ReauthenticationResult,
    RecoveryCodeSetResult,
    SessionView,
)
from property_rental.local_authentication import (
    AuthenticationAuditEvidence,
    BoundedAuthenticationAttemptLimiter,
    ConnectionBoundary,
    LocalAccountCredential,
    LocalAuthenticationService,
    PostgresLocalAccountRepository,
    normalize_local_username,
    verifier_digest,
)
from property_rental.password_security import PasswordHashService

# A session cookie made by this flow is 43 characters (`secrets.token_urlsafe(32)`); a longer
# value is refused before it is hashed.
MAX_SESSION_TOKEN_LENGTH: Final = 128
SESSION_TOKEN_BYTES: Final = 32
LOGIN_PROVENANCE: Final = "auth-login"
LOGOUT_PROVENANCE: Final = "auth-logout"
# A database that does not answer must not hold a request thread for long (review round 1).
CONNECT_TIMEOUT_SECONDS: Final = 5
# No statement of the sign-in or the session check may run longer than 5 seconds (login
# sub-slice L3a-2).
STATEMENT_TIMEOUT_OPTION: Final = "-c statement_timeout=5000"
# A coarse per-process flood guard (decided under the owner's 2026-10-22 rule), in front of the
# database count of wrong tries of login sub-slice L3b.
FLOOD_GUARD_TRIES_PER_USERNAME: Final = 20
FLOOD_GUARD_TRIES_PER_SOURCE: Final = 100
FLOOD_GUARD_WINDOW_SECONDS: Final = 15 * 60

# The live session of a token digest: not revoked, before both expiries by the database clock,
# and of an active, classified account with MFA policy `optional` (until login sub-slice L3c
# records the MFA proof of a session, an account that needs MFA has no usable session).
LIVE_SESSION: Final = """
    SELECT browser.session_id, browser.actor_id::text, account.display_name, browser.created_at,
           browser.last_activity_at, browser.idle_expires_at, browser.absolute_expires_at
    FROM app.browser_sessions AS browser
    JOIN app.user_accounts AS account ON account.actor_id = browser.actor_id
    JOIN app.user_account_classes AS classification ON classification.actor_id = browser.actor_id
    WHERE browser.token_verifier = %s
      AND browser.verifier_algorithm = 'sha256'
      AND browser.revoked_at IS NULL
      AND statement_timestamp() < browser.idle_expires_at
      AND statement_timestamp() < browser.absolute_expires_at
      AND account.lifecycle_state = 'active'
      AND account.mfa_policy_class = 'optional'
"""
INSERT_SESSION: Final = """
    INSERT INTO app.browser_sessions (
        session_id, actor_id, token_verifier, verifier_algorithm, creation_provenance
    ) VALUES (%s, %s, %s, 'sha256', %s)
"""
# The account's current password verifier, read again in the transaction that writes the
# session (review round 1, security).
CURRENT_VERIFIER: Final = """
    SELECT credential.verifier_encoding
    FROM app.password_credentials AS credential
    WHERE credential.actor_id = %s
"""
# The database count of wrong tries (login sub-slice L3b, migration 20270128_185); each answers
# the seconds left of an active wait, or NULL.
SIGN_IN_WAIT_SECONDS: Final = "SELECT app.sign_in_wait_seconds(%s, %s)"
RECORD_WRONG_SIGN_IN: Final = "SELECT app.record_sign_in_wrong_try(%s, %s, 'password')"
CLEAR_WRONG_SIGN_INS: Final = "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)"
REVOKE_LIVE_SESSION: Final = """
    UPDATE app.browser_sessions AS browser
    SET revoked_by_actor_id = browser.actor_id,
        revocation_reason = 'logout',
        revocation_provenance = %s
    WHERE browser.token_verifier = %s
      AND browser.revoked_at IS NULL
      AND statement_timestamp() < browser.idle_expires_at
      AND statement_timestamp() < browser.absolute_expires_at
    RETURNING browser.session_id
"""

logger = logging.getLogger(__name__)


def session_token_digest(session_token: str) -> bytes:
    """The sha256 digest stored for a session token; a token that is too long is refused."""
    if not session_token or len(session_token) > MAX_SESSION_TOKEN_LENGTH:
        raise AuthenticationRejected
    return hashlib.sha256(session_token.encode("utf-8")).digest()


def sign_in_username_digest(account_key: str) -> bytes:
    """The sha256 key of a normalized username in the wrong-try count. The typed text, which may
    be a password typed into the wrong box, is never stored as text; the digest has no key, so it
    is pseudonymous only (Q-2026-10-23-175)."""
    return hashlib.sha256(f"username:{account_key}".encode()).digest()


def sign_in_source_digest(source_key: str) -> bytes:
    """The sha256 key of a request source in the wrong-try count."""
    return hashlib.sha256(f"source:{source_key}".encode()).digest()


def session_view(row: tuple[object, ...]) -> SessionView:
    """A `SessionView` from a `LIVE_SESSION` row."""
    _, actor_id, display_name, created_at, last_activity_at, idle_expires_at, absolute = row
    return SessionView(
        actor_id=str(actor_id),
        authenticated_at=cast(datetime, created_at),
        last_activity_at=cast(datetime, last_activity_at),
        idle_expires_at=cast(datetime, idle_expires_at),
        absolute_expires_at=cast(datetime, absolute),
        mfa_assurance="none",
        reauthenticated_at=None,
        display_name=str(display_name),
    )


class _LoggingAuthenticationAuditSink:
    """Secret-free sign-in decisions in the application log (no username, password or token)."""

    def record(self, evidence: AuthenticationAuditEvidence) -> None:
        logger.info(
            "authentication decision",
            extra={"outcome": evidence.outcome, "reason": evidence.reason},
        )


class _PostgresAccountLookup:
    """Look one account up in its own short connection, so parallel sign-ins share no
    connection."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        with psycopg.connect(
            self._database_url,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            options=STATEMENT_TIMEOUT_OPTION,
        ) as connection:
            repository = PostgresLocalAccountRepository(cast(ConnectionBoundary, connection))
            return repository.find_by_username(username)


class _PostgresSignInWaits:
    """The database count of wrong sign-in tries, each call in its own short READ COMMITTED
    connection."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _seconds(self, query: str, parameters: tuple[object, ...]) -> int | None:
        with psycopg.connect(
            self._database_url,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            options=STATEMENT_TIMEOUT_OPTION,
        ) as connection:
            connection.isolation_level = IsolationLevel.READ_COMMITTED
            row = connection.execute(query, parameters).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def wait_seconds(self, account_key: str, source_key: str) -> int | None:
        return self._seconds(
            SIGN_IN_WAIT_SECONDS,
            (sign_in_username_digest(account_key), sign_in_source_digest(source_key)),
        )

    def record_wrong_try(self, account_key: str, source_key: str) -> int | None:
        return self._seconds(
            RECORD_WRONG_SIGN_IN,
            (sign_in_username_digest(account_key), sign_in_source_digest(source_key)),
        )


class PostgresAuthenticationFlow:
    """`AuthenticationFlow` sign-in, session read and sign-out on PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._password_service = PasswordHashService()
        self._sign_in_waits = _PostgresSignInWaits(database_url)
        self._authentication = LocalAuthenticationService(
            repository=_PostgresAccountLookup(database_url),
            password_service=self._password_service,
            attempt_limiter=BoundedAuthenticationAttemptLimiter(
                max_attempts_per_account=FLOOD_GUARD_TRIES_PER_USERNAME,
                max_attempts_per_source=FLOOD_GUARD_TRIES_PER_SOURCE,
                window_seconds=FLOOD_GUARD_WINDOW_SECONDS,
            ),
            audit_sink=_LoggingAuthenticationAuditSink(),
            sign_in_waits=self._sign_in_waits,
        )

    @contextmanager
    def _transaction(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        try:
            with psycopg.connect(
                self._database_url,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                options=STATEMENT_TIMEOUT_OPTION,
            ) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                yield connection
        except psycopg.Error as exc:
            raise AuthenticationUnavailable from exc

    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        try:
            result = self._authentication.authenticate(
                username=username, password=password, request_source=request_source
            )
        except psycopg.Error as exc:
            raise AuthenticationUnavailable from exc
        if result.wait_seconds is not None:
            # The same answer for every username, known or not (owner's rule, DL-081).
            raise AuthenticationRateLimited(result.wait_seconds)
        if not result.is_authenticated or result.actor_id is None:
            raise AuthenticationRejected
        csrf_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        account_key = normalize_local_username(username)
        if result.mfa_policy_class != "optional":
            # Review round 1 (security): a wait that a parallel wrong try started after the
            # first check refuses the MFA step too; the check takes the same locks as the count.
            try:
                waiting = self._sign_in_waits.wait_seconds(account_key, request_source)
            except psycopg.Error as exc:
                raise AuthenticationUnavailable from exc
            if waiting is not None:
                raise AuthenticationRateLimited(waiting)
            # No session and no actor before MFA (DL-056); the pre-authentication token is not
            # stored yet, so the challenge stays unavailable until login sub-slice L3c. The
            # wrong-try count is neither added to nor cleared here: it is cleared only when the
            # challenge completes (L3c), so a known password cannot clear a count of wrong
            # sign-in codes.
            return AuthenticationResult(
                phase=AuthenticationPhase.MFA_REQUIRED,
                preauth_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
                csrf_token=csrf_token,
            )
        session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        digest = session_token_digest(session_token)
        with self._transaction() as connection:
            # A correct sign-in clears the wrong-try count, unless a parallel wrong try started
            # a wait after this sign-in was checked (fail closed, login sub-slice L3b). It is the
            # first statement, so a correct password that meets a wait answers after the same
            # work as a wrong one (owner answer (a) to Q-2026-10-23-177; review round 4); a
            # refusal below rolls the clear back.
            cleared = connection.execute(
                CLEAR_WRONG_SIGN_INS,
                (
                    sign_in_username_digest(account_key),
                    sign_in_source_digest(request_source),
                    result.actor_id,
                ),
            ).fetchone()
            if cleared is not None and cleared[0] is not None:
                raise AuthenticationRateLimited(int(str(cleared[0])))
            # Review round 1 (security): a password reset that committed after the password
            # check must not leave a session made with the old password, so the verifier this
            # transaction reads must be the one the password was checked against. A reset that
            # commits after this read and before the commit is closed by login sub-slice L4
            # (binding). Login sub-slice L3b (Q-2026-10-23-177 (a)): a comparison of digests,
            # not a second Argon2id check; a reset to the same password stores a new verifier and
            # is refused too.
            current = connection.execute(CURRENT_VERIFIER, (result.actor_id,)).fetchone()
            if (
                current is None
                or result.verifier_digest is None
                or not hmac.compare_digest(verifier_digest(str(current[0])), result.verifier_digest)
            ):
                raise AuthenticationRejected
            connection.execute(INSERT_SESSION, (uuid4(), result.actor_id, digest, LOGIN_PROVENANCE))
            row = connection.execute(LIVE_SESSION, (digest,)).fetchone()
            if row is None:
                # The account changed between the password check and the session write.
                raise AuthenticationRejected
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=csrf_token,
            session=session_view(row),
        )

    def inspect_session(self, *, session_token: str, request_id: str) -> SessionView:
        digest = session_token_digest(session_token)
        with self._transaction() as connection:
            row = connection.execute(LIVE_SESSION, (digest,)).fetchone()
        if row is None:
            raise AuthenticationRejected
        return session_view(row)

    def logout(self, *, session_token: str, request_id: str) -> None:
        digest = session_token_digest(session_token)
        with self._transaction() as connection:
            # A parallel activity committed after this statement started is fine: the trigger
            # records the later of the two times (migration 20270127_184).
            row = connection.execute(REVOKE_LIVE_SESSION, (LOGOUT_PROVENANCE, digest)).fetchone()
        if row is None:
            raise AuthenticationRejected

    @staticmethod
    def _unavailable() -> AuthenticationUnavailable:
        # The MFA challenge and enrollment come with login sub-slice L3c, reauthentication with
        # L3d, and the recovery codes with L3c.
        return AuthenticationUnavailable()

    def complete_mfa(
        self,
        *,
        preauth_token: str,
        method: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise self._unavailable()

    def begin_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        request_id: str,
    ) -> MfaEnrollmentResult:
        raise self._unavailable()

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise self._unavailable()

    def reauthenticate(
        self,
        *,
        session_token: str,
        password: str,
        second_factor_method: str | None,
        second_factor_code: str | None,
        request_id: str,
    ) -> ReauthenticationResult:
        raise self._unavailable()

    def issue_recovery_codes(
        self,
        *,
        session_token: str,
        request_id: str,
    ) -> RecoveryCodeSetResult:
        raise self._unavailable()

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
    ) -> RecoveryCodeSetResult:
        raise self._unavailable()
