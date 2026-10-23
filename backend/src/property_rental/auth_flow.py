"""Password sign-in, the session read and sign-out on PostgreSQL (login sub-slice L3a-1, DL-081).

`PostgresAuthenticationFlow` implements the sign-in part of `AuthenticationFlow`. The password
check is the existing `LocalAuthenticationService` (Argon2id, a dummy verifier for unknown names,
one generic rejection). A session is a row of `app.browser_sessions` that keeps only the sha256
digest of a random token; the token itself goes only into the `__Host-prm_session` cookie. Every
time is the database clock. An account that needs MFA (its MFA policy is `required`, or it has an
active sign-in code) gets no session before the MFA challenge: its sign-in stores a challenge row
with only the digest of the pre-authentication token, and the right sign-in code makes a session
with an MFA proof (login sub-slice L3c-2a); an account without a sign-in code sets one up at
sign-in and its first right code makes the session (login sub-slice L3c-2b). Wrong tries are
counted in the database (login sub-slice L3b): a try during a wait is refused before the
password check, and a sign-in that makes a session clears the count.
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Final, Literal, NoReturn, cast
from urllib.parse import quote, urlencode
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
from property_rental.runtime_secrets import derive_totp_key_identifier
from property_rental.totp_security import (
    TOTP_DEFAULT_DIGITS,
    TOTP_DEFAULT_PERIOD_SECONDS,
    Aes256GcmTotpSecretProtector,
    ProtectedTotpSecret,
    TotpSecret,
    TotpSecretGenerator,
    TotpSecretProtectionError,
    TotpService,
)

# A session cookie made by this flow is 43 characters (`secrets.token_urlsafe(32)`); a longer
# value is refused before it is hashed.
MAX_SESSION_TOKEN_LENGTH: Final = 128
SESSION_TOKEN_BYTES: Final = 32
LOGIN_PROVENANCE: Final = "auth-login"
MFA_CHALLENGE_PROVENANCE: Final = "auth-mfa-challenge"
MFA_ENROLLMENT_PROVENANCE: Final = "auth-mfa-enrollment"
MFA_ENROLLMENT_REPLACED_PROVENANCE: Final = "auth-mfa-enrollment-replaced"
# The name an authenticator app shows for the sign-in code (decided under the owner's
# 2026-10-22 rule, login sub-slice L3c-2b).
TOTP_ISSUER: Final = "Property Rental"
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

# An account needs MFA when its MFA policy is `required` or it has an active sign-in code (the
# L3a-1 binding: Staff with a sign-in code must give it); a session of such an account is usable
# only with an MFA proof (login sub-slice L3c-2a), and a `totp` proof only while its sign-in code
# is active (review round 2), so a sign-in code turned off ends the session even without a
# revocation. The fragment uses the aliases `browser` and `account`.
SESSION_MFA_SATISFIED: Final = """
    (
        EXISTS (
            SELECT 1
            FROM app.browser_session_mfa_proofs AS proof
            WHERE proof.session_id = browser.session_id
              AND (
                  proof.method <> 'totp'
                  OR EXISTS (
                      SELECT 1
                      FROM app.totp_mfa_enrollments AS proven
                      WHERE proven.enrollment_id = proof.enrollment_id
                        AND proven.enrollment_state = 'active'
                  )
              )
        )
        OR (
            account.mfa_policy_class = 'optional'
            AND NOT EXISTS (
                SELECT 1
                FROM app.totp_mfa_enrollments AS enrollment
                WHERE enrollment.actor_id = account.actor_id
                  AND enrollment.enrollment_state = 'active'
            )
        )
    )
"""
# The live session of a token digest: not revoked, before both expiries by the database clock,
# of an active, classified account, and with an MFA proof when the account needs MFA. The
# `mfa_assurance` is the proof's method while it counts, else `none` (login sub-slice L3c-2b).
LIVE_SESSION: Final = f"""
    SELECT browser.session_id, browser.actor_id::text, account.display_name, browser.created_at,
           browser.last_activity_at, browser.idle_expires_at, browser.absolute_expires_at,
           COALESCE(
               (SELECT proof.method
                FROM app.browser_session_mfa_proofs AS proof
                WHERE proof.session_id = browser.session_id
                  AND (
                      proof.method <> 'totp'
                      OR EXISTS (
                          SELECT 1
                          FROM app.totp_mfa_enrollments AS proven
                          WHERE proven.enrollment_id = proof.enrollment_id
                            AND proven.enrollment_state = 'active'
                      )
                  )),
               'none'
           )
    FROM app.browser_sessions AS browser
    JOIN app.user_accounts AS account ON account.actor_id = browser.actor_id
    JOIN app.user_account_classes AS classification ON classification.actor_id = browser.actor_id
    WHERE browser.token_verifier = %s
      AND browser.verifier_algorithm = 'sha256'
      AND browser.revoked_at IS NULL
      AND statement_timestamp() < browser.idle_expires_at
      AND statement_timestamp() < browser.absolute_expires_at
      AND account.lifecycle_state = 'active'
      AND {SESSION_MFA_SATISFIED}
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
RECORD_WRONG_SIGN_IN_CODE: Final = "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')"
CLEAR_WRONG_SIGN_INS: Final = "SELECT app.clear_sign_in_wrong_tries(%s, %s, %s)"
# Whether an account has an active sign-in code (login sub-slice L3c-2a).
ACTIVE_SIGN_IN_CODE: Final = """
    SELECT EXISTS (
        SELECT 1
        FROM app.totp_mfa_enrollments AS enrollment
        WHERE enrollment.actor_id = %s
          AND enrollment.enrollment_state = 'active'
    )
"""
# The active sign-in code of an account, which a `challenge` is made for (review round 1).
ACTIVE_ENROLLMENT_OF: Final = """
    SELECT enrollment.enrollment_id
    FROM app.totp_mfa_enrollments AS enrollment
    WHERE enrollment.actor_id = %s
      AND enrollment.enrollment_state = 'active'
"""
# The id an unknown username is looked up with, so both cases run the same query.
NO_ACCOUNT: Final = UUID(int=0)
INSERT_CHALLENGE: Final = """
    INSERT INTO app.sign_in_mfa_challenges (
        challenge_id, actor_id, token_verifier, purpose, enrollment_id,
        password_verifier_digest, username_digest, source_digest
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""
# An open `challenge` of an active, classified account, with the sign-in code it was made for
# while that code is still active (a reset in between refuses), the last
# used time step of that code and the current time step of the database clock.
OPEN_CHALLENGE: Final = f"""
    SELECT challenge.challenge_id, challenge.actor_id, challenge.password_verifier_digest,
           challenge.username_digest, challenge.source_digest, enrollment.enrollment_id,
           enrollment.secret_ciphertext, enrollment.secret_nonce, enrollment.key_identifier,
           enrollment.protection_algorithm,
           COALESCE(
               (SELECT max(used.time_step)
                FROM app.totp_used_steps AS used
                WHERE used.enrollment_id = enrollment.enrollment_id),
               0
           ),
           floor(extract(epoch FROM statement_timestamp()) / {TOTP_DEFAULT_PERIOD_SECONDS})::bigint
    FROM app.sign_in_mfa_challenges AS challenge
    JOIN app.user_accounts AS account ON account.actor_id = challenge.actor_id
    JOIN app.user_account_classes AS classification ON classification.actor_id = challenge.actor_id
    JOIN app.totp_mfa_enrollments AS enrollment
      ON enrollment.enrollment_id = challenge.enrollment_id
     AND enrollment.actor_id = challenge.actor_id
    WHERE challenge.token_verifier = %s
      AND challenge.purpose = 'challenge'
      AND challenge.completed_at IS NULL
      AND statement_timestamp() < challenge.expires_at
      AND account.lifecycle_state = 'active'
      AND enrollment.enrollment_state = 'active'
"""
# An open `enrollment` challenge not yet started, of an active, classified account that still
# needs a sign-in code (the L3c-2a binding; login sub-slice L3c-2b).
OPEN_ENROLLMENT_CHALLENGE: Final = """
    SELECT challenge.challenge_id, challenge.actor_id, challenge.username_digest,
           challenge.source_digest, account.normalized_username,
           challenge.password_verifier_digest
    FROM app.sign_in_mfa_challenges AS challenge
    JOIN app.user_accounts AS account ON account.actor_id = challenge.actor_id
    JOIN app.user_account_classes AS classification ON classification.actor_id = challenge.actor_id
    WHERE challenge.token_verifier = %s
      AND challenge.purpose = 'enrollment'
      AND challenge.completed_at IS NULL
      AND statement_timestamp() < challenge.expires_at
      AND account.lifecycle_state = 'active'
      AND account.mfa_policy_class = 'required'
      AND NOT EXISTS (
          SELECT 1
          FROM app.sign_in_code_enrollment_starts AS start
          WHERE start.challenge_id = challenge.challenge_id
      )
      AND NOT EXISTS (
          SELECT 1
          FROM app.totp_mfa_enrollments AS enrollment
          WHERE enrollment.actor_id = challenge.actor_id
            AND enrollment.enrollment_state = 'active'
      )
"""
# The same challenge locked for its start; a parallel start of it is then seen by a new
# statement (review round 1: the re-check of a locked row does not see a start committed
# meanwhile).
LOCK_ENROLLMENT_CHALLENGE: Final = f"""{OPEN_ENROLLMENT_CHALLENGE}    FOR UPDATE OF challenge
"""
# The unique constraints a parallel start or first code meets (review round 2).
STARTED_ELSEWHERE: Final = frozenset(
    {"totp_mfa_enrollments_one_live_per_actor", "sign_in_code_enrollment_starts_pkey"}
)
CHALLENGE_STARTED: Final = """
    SELECT EXISTS (
        SELECT 1
        FROM app.sign_in_code_enrollment_starts AS start
        WHERE start.challenge_id = %s
    )
"""
# A sign-in code started at an earlier sign-in and never confirmed is replaced.
REPLACE_PENDING_CODE: Final = """
    UPDATE app.totp_mfa_enrollments AS enrollment
    SET enrollment_state = 'disabled',
        disabled_by_actor_id = enrollment.actor_id,
        disablement_provenance = %s
    WHERE enrollment.actor_id = %s
      AND enrollment.enrollment_state = 'pending'
"""
INSERT_PENDING_CODE: Final = """
    INSERT INTO app.totp_mfa_enrollments (
        enrollment_id, actor_id, secret_ciphertext, secret_nonce, key_identifier,
        protection_algorithm, totp_algorithm, created_by_actor_id, provenance
    ) VALUES (%s, %s, %s, %s, %s, %s, 'sha1', %s, %s)
"""
INSERT_ENROLLMENT_START: Final = """
    INSERT INTO app.sign_in_code_enrollment_starts (challenge_id, actor_id, enrollment_id)
    VALUES (%s, %s, %s)
"""
# An open, started `enrollment` challenge of an active, classified account that still has MFA
# `required` (review round 1: MFA turned off while a start commits can leave the started code
# pending, and it must not be activated), with its pending
# sign-in code, the last used time step of that code and the current time step of the database
# clock: the same columns as `OPEN_CHALLENGE`.
OPEN_ENROLLMENT_START: Final = f"""
    SELECT challenge.challenge_id, challenge.actor_id, challenge.password_verifier_digest,
           challenge.username_digest, challenge.source_digest, enrollment.enrollment_id,
           enrollment.secret_ciphertext, enrollment.secret_nonce, enrollment.key_identifier,
           enrollment.protection_algorithm,
           COALESCE(
               (SELECT max(used.time_step)
                FROM app.totp_used_steps AS used
                WHERE used.enrollment_id = enrollment.enrollment_id),
               0
           ),
           floor(extract(epoch FROM statement_timestamp()) / {TOTP_DEFAULT_PERIOD_SECONDS})::bigint
    FROM app.sign_in_mfa_challenges AS challenge
    JOIN app.user_accounts AS account ON account.actor_id = challenge.actor_id
    JOIN app.user_account_classes AS classification ON classification.actor_id = challenge.actor_id
    JOIN app.sign_in_code_enrollment_starts AS start
      ON start.challenge_id = challenge.challenge_id
     AND start.actor_id = challenge.actor_id
    JOIN app.totp_mfa_enrollments AS enrollment
      ON enrollment.enrollment_id = start.enrollment_id
     AND enrollment.actor_id = challenge.actor_id
    WHERE challenge.token_verifier = %s
      AND challenge.purpose = 'enrollment'
      AND challenge.completed_at IS NULL
      AND statement_timestamp() < challenge.expires_at
      AND account.lifecycle_state = 'active'
      AND account.mfa_policy_class = 'required'
      AND enrollment.enrollment_state = 'pending'
"""
ACTIVATE_PENDING_CODE: Final = """
    UPDATE app.totp_mfa_enrollments AS enrollment
    SET enrollment_state = 'active',
        activated_by_actor_id = enrollment.actor_id,
        activation_provenance = %s
    WHERE enrollment.enrollment_id = %s
      AND enrollment.enrollment_state = 'pending'
    RETURNING enrollment.enrollment_id
"""
LOCK_PENDING_ENROLLMENT: Final = """
    SELECT enrollment.enrollment_id
    FROM app.totp_mfa_enrollments AS enrollment
    WHERE enrollment.enrollment_id = %s
      AND enrollment.enrollment_state = 'pending'
    FOR UPDATE
"""
LOCK_ACTIVE_ENROLLMENT: Final = """
    SELECT enrollment.enrollment_id
    FROM app.totp_mfa_enrollments AS enrollment
    WHERE enrollment.enrollment_id = %s
      AND enrollment.enrollment_state = 'active'
    FOR UPDATE
"""
LAST_USED_STEP: Final = """
    SELECT COALESCE(max(used.time_step), 0)
    FROM app.totp_used_steps AS used
    WHERE used.enrollment_id = %s
"""
RECORD_USED_STEP: Final = (
    "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)"
)
COMPLETE_CHALLENGE: Final = """
    UPDATE app.sign_in_mfa_challenges AS challenge
    SET completed_at = statement_timestamp()
    WHERE challenge.challenge_id = %s
      AND challenge.completed_at IS NULL
      AND statement_timestamp() < challenge.expires_at
    RETURNING challenge.challenge_id
"""
INSERT_MFA_PROOF: Final = """
    INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, enrollment_id)
    VALUES (%s, %s, %s, %s)
"""
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

MFA_ASSURANCES: Final[dict[str, Literal["totp", "recovery_code"]]] = {
    "totp": "totp",
    "recovery_code": "recovery_code",
}

logger = logging.getLogger(__name__)


def session_token_digest(session_token: str) -> bytes:
    """The sha256 digest stored for a session token; a token that is too long is refused."""
    if not session_token or len(session_token) > MAX_SESSION_TOKEN_LENGTH:
        raise AuthenticationRejected
    return hashlib.sha256(session_token.encode("utf-8")).digest()


def provisioning_uri(username: str, secret: TotpSecret) -> str:
    """The standard `otpauth://totp/` link of a new sign-in code (the authenticator app's key URI
    format): the issuer and the username as the label, the secret in Base32 and the 6 digits,
    30 seconds and SHA-1 the database stores."""
    label = f"{quote(TOTP_ISSUER, safe='')}:{quote(username, safe='')}"
    query = urlencode(
        {
            "secret": secret.get_base32_value(),
            "issuer": TOTP_ISSUER,
            "algorithm": "SHA1",
            "digits": TOTP_DEFAULT_DIGITS,
            "period": TOTP_DEFAULT_PERIOD_SECONDS,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{query}"


def _try_digest(text: str, key: bytes | None) -> bytes:
    if key is None:
        return hashlib.sha256(text.encode()).digest()
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def sign_in_username_digest(account_key: str, key: bytes | None = None) -> bytes:
    """The key of a normalized username in the wrong-try count. The typed text, which may be a
    password typed into the wrong box, is never stored as text. With the key derived from the
    protected key file it is HMAC-SHA256 (owner answer (a) to Q-2026-10-23-175, login sub-slice
    L3c-1); without one (development and tests only) a plain, pseudonymous sha256."""
    return _try_digest(f"username:{account_key}", key)


def sign_in_source_digest(source_key: str, key: bytes | None = None) -> bytes:
    """The key of a request source in the wrong-try count, keyed as the username's."""
    return _try_digest(f"source:{source_key}", key)


def session_view(row: tuple[object, ...]) -> SessionView:
    """A `SessionView` from a `LIVE_SESSION` row."""
    _, actor_id, display_name, created_at, last_activity_at, idle_expires_at, absolute, mfa = row
    return SessionView(
        actor_id=str(actor_id),
        authenticated_at=cast(datetime, created_at),
        last_activity_at=cast(datetime, last_activity_at),
        idle_expires_at=cast(datetime, idle_expires_at),
        absolute_expires_at=cast(datetime, absolute),
        mfa_assurance=MFA_ASSURANCES.get(str(mfa), "none"),
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
    connection. An account with an active sign-in code is reported with the MFA policy
    `required`, because it needs MFA whatever its policy (login sub-slice L3c-2a)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def find_by_username(self, username: str) -> LocalAccountCredential | None:
        with psycopg.connect(
            self._database_url,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            options=STATEMENT_TIMEOUT_OPTION,
        ) as connection:
            repository = PostgresLocalAccountRepository(cast(ConnectionBoundary, connection))
            credential = repository.find_by_username(username)
            # The same query for an unknown username, so both cases do the same work.
            actor_id = UUID(credential.actor_id) if credential is not None else NO_ACCOUNT
            row = connection.execute(ACTIVE_SIGN_IN_CODE, (actor_id,)).fetchone()
        if credential is not None and row is not None and row[0] is True:
            return replace(credential, mfa_policy_class="required")
        return credential


class _PostgresSignInWaits:
    """The database count of wrong sign-in tries, each call in its own short READ COMMITTED
    connection."""

    def __init__(self, database_url: str, key: bytes | None) -> None:
        self._database_url = database_url
        self._key = key

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
            (
                sign_in_username_digest(account_key, self._key),
                sign_in_source_digest(source_key, self._key),
            ),
        )

    def record_wrong_try(self, account_key: str, source_key: str) -> int | None:
        return self._seconds(
            RECORD_WRONG_SIGN_IN,
            (
                sign_in_username_digest(account_key, self._key),
                sign_in_source_digest(source_key, self._key),
            ),
        )

    def challenge_wait_seconds(self, username_digest: bytes, source_digest: bytes) -> int | None:
        """The wait of the digests a sign-in code challenge stored (login sub-slice L3c-2a)."""
        return self._seconds(SIGN_IN_WAIT_SECONDS, (username_digest, source_digest))

    def record_wrong_code(self, username_digest: bytes, source_digest: bytes) -> int | None:
        """A wrong sign-in code is a wrong try of the account (Q-2026-10-21-154 (a))."""
        return self._seconds(RECORD_WRONG_SIGN_IN_CODE, (username_digest, source_digest))


class PostgresAuthenticationFlow:
    """`AuthenticationFlow` sign-in, session read and sign-out on PostgreSQL."""

    def __init__(
        self,
        database_url: str,
        *,
        sign_in_try_key: bytes | None = None,
        totp_protection_key: bytes | None = None,
    ) -> None:
        self._database_url = database_url
        self._sign_in_try_key = sign_in_try_key
        # The TOTP protection key read from the protected key file (login sub-slice L3c-2a);
        # without it no sign-in code can be checked.
        self._totp_protection_key = totp_protection_key
        # The name stored with a sign-in code set up at sign-in (login sub-slice L3c-2b).
        self._totp_key_identifier = (
            derive_totp_key_identifier(totp_protection_key)
            if totp_protection_key is not None
            else None
        )
        self._totp = TotpService()
        self._password_service = PasswordHashService()
        self._sign_in_waits = _PostgresSignInWaits(database_url, sign_in_try_key)
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
            # No session and no actor before MFA (DL-056): a stored challenge row keeps only the
            # digest of the pre-authentication token (login sub-slice L3c-2a). The wrong-try
            # count is neither added to nor cleared here: it is cleared only when the challenge
            # completes, so a known password cannot clear a count of wrong sign-in codes.
            if result.verifier_digest is None:
                raise AuthenticationRejected
            preauth_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            with self._transaction() as connection:
                enrolled = connection.execute(ACTIVE_ENROLLMENT_OF, (result.actor_id,)).fetchone()
                enrollment_id = enrolled[0] if enrolled is not None else None
                purpose = "challenge" if enrollment_id is not None else "enrollment"
                connection.execute(
                    INSERT_CHALLENGE,
                    (
                        uuid4(),
                        result.actor_id,
                        session_token_digest(preauth_token),
                        purpose,
                        enrollment_id,
                        result.verifier_digest,
                        sign_in_username_digest(account_key, self._sign_in_try_key),
                        sign_in_source_digest(request_source, self._sign_in_try_key),
                    ),
                )
            return AuthenticationResult(
                phase=(
                    AuthenticationPhase.MFA_REQUIRED
                    if purpose == "challenge"
                    else AuthenticationPhase.MFA_ENROLLMENT_REQUIRED
                ),
                preauth_token=preauth_token,
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
                    sign_in_username_digest(account_key, self._sign_in_try_key),
                    sign_in_source_digest(request_source, self._sign_in_try_key),
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
        # The recovery codes come with login sub-slice L3c-2c and reauthentication with L3d.
        return AuthenticationUnavailable()

    def _refuse_during_wait(self, username_digest: bytes, source_digest: bytes) -> None:
        """A wait of the stored username or source answers 429 before any code is used."""
        try:
            waiting = self._sign_in_waits.challenge_wait_seconds(username_digest, source_digest)
        except psycopg.Error as exc:
            raise AuthenticationUnavailable from exc
        if waiting is not None:
            raise AuthenticationRateLimited(waiting)

    def _open_sign_in_code(self, challenge: tuple[object, ...], *, request_id: str) -> TotpSecret:
        """The secret of the challenge row's sign-in code, opened with the protection key."""
        if self._totp_protection_key is None:
            raise self._unavailable()
        actor_id, enrollment_id = challenge[1], challenge[5]
        ciphertext, nonce, key_identifier, protection_algorithm = challenge[6:10]
        try:
            return Aes256GcmTotpSecretProtector(
                key=self._totp_protection_key, key_identifier=str(key_identifier)
            ).unprotect(
                ProtectedTotpSecret(
                    ciphertext=bytes(cast(bytes, ciphertext)),
                    nonce=bytes(cast(bytes, nonce)),
                    key_identifier=str(key_identifier),
                    encryption_algorithm=str(protection_algorithm),
                ),
                actor_id=cast(UUID, actor_id),
                enrollment_id=cast(UUID, enrollment_id),
            )
        except (TotpSecretProtectionError, ValueError) as exc:
            # The key file does not open this sign-in code; no detail is given.
            logger.warning(
                "sign-in code cannot be opened",
                extra={"outcome": "unavailable", "request_id": request_id},
            )
            raise AuthenticationUnavailable from exc

    def _matching_step(
        self, code: str, secret: TotpSecret, *, current_step: object, last_used_step: object
    ) -> int | None:
        """The current or the previous 30-second step of the database clock (one step of drift)
        that the code is right for, each used once and only after the last used step."""
        return next(
            (
                candidate
                for candidate in (int(str(current_step)), int(str(current_step)) - 1)
                if candidate > int(str(last_used_step))
                and self._totp.verify_code(
                    code, secret, at_time=candidate * TOTP_DEFAULT_PERIOD_SECONDS
                )
            ),
            None,
        )

    def _refuse_wrong_code(
        self, username_digest: bytes, source_digest: bytes, *, decision: str, request_id: str
    ) -> NoReturn:
        """A wrong sign-in code is a wrong try of the account (Q-2026-10-21-154 (a)): 429 when
        it starts a wait, otherwise 401."""
        try:
            waiting = self._sign_in_waits.record_wrong_code(username_digest, source_digest)
        except psycopg.Error as exc:
            raise AuthenticationUnavailable from exc
        logger.info(decision, extra={"outcome": "rejected", "request_id": request_id})
        if waiting is not None:
            raise AuthenticationRateLimited(waiting)
        raise AuthenticationRejected

    @staticmethod
    def _clear_wrong_tries(
        connection: psycopg.Connection[tuple[object, ...]],
        username_digest: bytes,
        source_digest: bytes,
        actor_id: object,
    ) -> None:
        """The clear first, as at a password sign-in: a wait that a parallel wrong try started
        refuses and rolls everything back."""
        cleared = connection.execute(
            CLEAR_WRONG_SIGN_INS, (username_digest, source_digest, actor_id)
        ).fetchone()
        if cleared is not None and cleared[0] is not None:
            raise AuthenticationRateLimited(int(str(cleared[0])))

    @staticmethod
    def _write_proven_session(
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        challenge_id: object,
        actor_id: object,
        checked_verifier: object,
        enrollment_id: object,
        session_digest: bytes,
        provenance: str,
    ) -> tuple[object, ...]:
        """After the used step: the challenge completed, the password verifier compared, the
        session and its `totp` proof written and the live session read back."""
        if connection.execute(COMPLETE_CHALLENGE, (challenge_id,)).fetchone() is None:
            raise AuthenticationRejected
        # A password reset after the password check refuses the session (the L3a-1 guard).
        current = connection.execute(CURRENT_VERIFIER, (actor_id,)).fetchone()
        if current is None or not hmac.compare_digest(
            verifier_digest(str(current[0])), bytes(cast(bytes, checked_verifier))
        ):
            raise AuthenticationRejected
        session_id = uuid4()
        connection.execute(INSERT_SESSION, (session_id, actor_id, session_digest, provenance))
        connection.execute(INSERT_MFA_PROOF, (session_id, challenge_id, "totp", enrollment_id))
        row = connection.execute(LIVE_SESSION, (session_digest,)).fetchone()
        if row is None:
            # The account changed between the challenge read and the session write.
            raise AuthenticationRejected
        return row

    def complete_mfa(
        self,
        *,
        preauth_token: str,
        method: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        """The sign-in code challenge (login sub-slice L3c-2a, DL-056, SEC-013)."""
        if method != "totp" or self._totp_protection_key is None:
            # A recovery code comes with L3c-2c; without the protection key no sign-in code
            # can be checked (development and tests without a key file).
            raise self._unavailable()
        digest = session_token_digest(preauth_token)
        with self._transaction() as connection:
            challenge = connection.execute(OPEN_CHALLENGE, (digest,)).fetchone()
        if challenge is None:
            raise AuthenticationRejected
        challenge_id, actor_id, checked_verifier, username_digest, source_digest = challenge[:5]
        enrollment_id, last_used_step, current_step = challenge[5], challenge[10], challenge[11]
        username_key = bytes(cast(bytes, username_digest))
        source_key = bytes(cast(bytes, source_digest))
        self._refuse_during_wait(username_key, source_key)
        secret = self._open_sign_in_code(challenge, request_id=request_id)
        step = self._matching_step(
            code, secret, current_step=current_step, last_used_step=last_used_step
        )
        if step is None:
            self._refuse_wrong_code(
                username_key, source_key, decision="sign-in code decision", request_id=request_id
            )
        session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        with self._transaction() as connection:
            self._clear_wrong_tries(connection, username_key, source_key, actor_id)
            # The enrollment lock makes two uses of one step, or of one challenge, wait for each
            # other; the second then finds the step or the challenge used.
            locked = connection.execute(LOCK_ACTIVE_ENROLLMENT, (enrollment_id,)).fetchone()
            last = connection.execute(LAST_USED_STEP, (enrollment_id,)).fetchone()
            if locked is None or last is None or step <= int(str(last[0])):
                raise AuthenticationRejected
            connection.execute(RECORD_USED_STEP, (enrollment_id, step))
            row = self._write_proven_session(
                connection,
                challenge_id=challenge_id,
                actor_id=actor_id,
                checked_verifier=checked_verifier,
                enrollment_id=enrollment_id,
                session_digest=session_token_digest(session_token),
                provenance=MFA_CHALLENGE_PROVENANCE,
            )
        logger.info(
            "sign-in code decision", extra={"outcome": "authenticated", "request_id": request_id}
        )
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            session=session_view(row),
        )

    def begin_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        request_id: str,
    ) -> MfaEnrollmentResult:
        """Set up a sign-in code at sign-in (login sub-slice L3c-2b, DL-056, UI-110): an open
        `enrollment` challenge of an account that still needs a sign-in code writes a new
        `pending` sign-in code, protected with the protection key, and starts it once; the
        secret is answered once, as the standard provisioning link, and never stored in the
        clear."""
        if self._totp_protection_key is None or self._totp_key_identifier is None:
            raise self._unavailable()
        digest = session_token_digest(preauth_token)
        with self._transaction() as connection:
            challenge = connection.execute(OPEN_ENROLLMENT_CHALLENGE, (digest,)).fetchone()
        if challenge is None:
            raise AuthenticationRejected
        # The wait first, outside the transaction that locks the challenge (review round 1).
        self._refuse_during_wait(bytes(cast(bytes, challenge[2])), bytes(cast(bytes, challenge[3])))
        secret = TotpSecretGenerator().generate()
        enrollment_id = uuid4()
        with self._transaction() as connection:
            locked = connection.execute(LOCK_ENROLLMENT_CHALLENGE, (digest,)).fetchone()
            if locked is None:
                raise AuthenticationRejected
            challenge_id, actor_id, _, _, username, checked_verifier = locked
            started = connection.execute(CHALLENGE_STARTED, (challenge_id,)).fetchone()
            if started is None or started[0] is not False:
                raise AuthenticationRejected
            # Review round 1 (security): a sign-in from before a password reset starts nothing,
            # so it cannot turn off the code another sign-in started with the new password.
            current = connection.execute(CURRENT_VERIFIER, (actor_id,)).fetchone()
            if current is None or not hmac.compare_digest(
                verifier_digest(str(current[0])), bytes(cast(bytes, checked_verifier))
            ):
                raise AuthenticationRejected
            protected = Aes256GcmTotpSecretProtector(
                key=self._totp_protection_key, key_identifier=self._totp_key_identifier
            ).protect(secret, actor_id=cast(UUID, actor_id), enrollment_id=enrollment_id)
            try:
                connection.execute(
                    REPLACE_PENDING_CODE, (MFA_ENROLLMENT_REPLACED_PROVENANCE, actor_id)
                )
                connection.execute(
                    INSERT_PENDING_CODE,
                    (
                        enrollment_id,
                        actor_id,
                        protected.ciphertext,
                        protected.nonce,
                        protected.key_identifier,
                        protected.encryption_algorithm,
                        actor_id,
                        MFA_ENROLLMENT_PROVENANCE,
                    ),
                )
                connection.execute(INSERT_ENROLLMENT_START, (challenge_id, actor_id, enrollment_id))
            except psycopg.errors.UniqueViolation as exc:
                # A parallel start of another challenge of the account, or a parallel first code
                # of an earlier start, came first (review round 1); everything rolls back. Any
                # other violation stays unavailable (review round 2).
                if exc.diag.constraint_name not in STARTED_ELSEWHERE:
                    raise
                raise AuthenticationRejected from None
        logger.info(
            "sign-in code enrollment decision",
            extra={"outcome": "started", "request_id": request_id},
        )
        return MfaEnrollmentResult(provisioning_uri=provisioning_uri(str(username), secret))

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        """The first right code of a started sign-in code activates it and makes the session
        with a `totp` proof (login sub-slice L3c-2b); a wrong code is a wrong try, as at the
        challenge."""
        if self._totp_protection_key is None:
            raise self._unavailable()
        digest = session_token_digest(preauth_token)
        with self._transaction() as connection:
            challenge = connection.execute(OPEN_ENROLLMENT_START, (digest,)).fetchone()
        if challenge is None:
            raise AuthenticationRejected
        challenge_id, actor_id, checked_verifier, username_digest, source_digest = challenge[:5]
        enrollment_id, last_used_step, current_step = challenge[5], challenge[10], challenge[11]
        username_key = bytes(cast(bytes, username_digest))
        source_key = bytes(cast(bytes, source_digest))
        self._refuse_during_wait(username_key, source_key)
        secret = self._open_sign_in_code(challenge, request_id=request_id)
        step = self._matching_step(
            code, secret, current_step=current_step, last_used_step=last_used_step
        )
        if step is None:
            self._refuse_wrong_code(
                username_key,
                source_key,
                decision="sign-in code enrollment decision",
                request_id=request_id,
            )
        session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        with self._transaction() as connection:
            self._clear_wrong_tries(connection, username_key, source_key, actor_id)
            # The lock makes a parallel confirmation, a replacement by a later sign-in or a
            # sign-in code reset wait; the sign-in code must still be pending.
            locked = connection.execute(LOCK_PENDING_ENROLLMENT, (enrollment_id,)).fetchone()
            if locked is None:
                raise AuthenticationRejected
            if (
                connection.execute(
                    ACTIVATE_PENDING_CODE, (MFA_ENROLLMENT_PROVENANCE, enrollment_id)
                ).fetchone()
                is None
            ):
                raise AuthenticationRejected
            last = connection.execute(LAST_USED_STEP, (enrollment_id,)).fetchone()
            if last is None or step <= int(str(last[0])):
                raise AuthenticationRejected
            connection.execute(RECORD_USED_STEP, (enrollment_id, step))
            row = self._write_proven_session(
                connection,
                challenge_id=challenge_id,
                actor_id=actor_id,
                checked_verifier=checked_verifier,
                enrollment_id=enrollment_id,
                session_digest=session_token_digest(session_token),
                provenance=MFA_ENROLLMENT_PROVENANCE,
            )
        logger.info(
            "sign-in code enrollment decision",
            extra={"outcome": "authenticated", "request_id": request_id},
        )
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            session=session_view(row),
        )

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
