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
import json
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
    NewPasswordRejected,
    ReauthenticationResult,
    RecoveryCodeSetResult,
    RecoveryCodeSetSummary,
    SessionView,
)
from property_rental.initial_owner_bootstrap import RECOVERY_CODE_COUNT
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
from property_rental.password_security import (
    PasswordHashService,
    one_time_password_forms,
    validate_new_password,
)
from property_rental.recovery_code_security import (
    Argon2idRecoveryCodeVerifierProvider,
    SecureRecoveryCodeGenerator,
    canonical_recovery_code,
)
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

# A reauthentication password is at most as long as the API accepts (`ReauthenticationRequest`).
MAX_REAUTHENTICATION_PASSWORD_LENGTH: Final = 1024
# A session cookie made by this flow is 43 characters (`secrets.token_urlsafe(32)`); a longer
# value is refused before it is hashed.
MAX_SESSION_TOKEN_LENGTH: Final = 128
SESSION_TOKEN_BYTES: Final = 32
LOGIN_PROVENANCE: Final = "auth-login"
MFA_CHALLENGE_PROVENANCE: Final = "auth-mfa-challenge"
MFA_RECOVERY_CODE_PROVENANCE: Final = "auth-mfa-recovery-code"
MFA_ENROLLMENT_PROVENANCE: Final = "auth-mfa-enrollment"
MFA_ENROLLMENT_REPLACED_PROVENANCE: Final = "auth-mfa-enrollment-replaced"
RECOVERY_CODES_PROVENANCE: Final = "auth-recovery-codes"
RECOVERY_CODES_REGENERATED_PROVENANCE: Final = "auth-recovery-codes-regenerated"
# Recovery codes are replaced only within 15 minutes of the sign-in code that proved the session
# (decided under the owner's 2026-10-22 rule, login sub-slice L3c-2c-1; the time of the owner's
# answer to Q-2026-10-21-157).
RECOVERY_CODE_REGENERATION_WINDOW: Final = "15 minutes"
# The name an authenticator app shows for the sign-in code (decided under the owner's
# 2026-10-22 rule, login sub-slice L3c-2b); the Property's name since L6, so the app shows the
# code "for CHETANA" as the sign-in screen says (Q-2026-10-24-187).
TOTP_ISSUER: Final = "CHETANA Residence"
LOGOUT_PROVENANCE: Final = "auth-logout"
# How a live recovery-code set was made, as the sign-in screens show it (login sub-slice L6);
# any other provenance (the first Owner's bootstrap, the older services) reads "other".
RECOVERY_SET_ORIGINS: Final[dict[str, Literal["issued", "regenerated"]]] = {
    RECOVERY_CODES_PROVENANCE: "issued",
    RECOVERY_CODES_REGENERATED_PROVENANCE: "regenerated",
}
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
# A proof counts while the sign-in code it stands for is active: for `totp` the code it used, for
# `recovery_code` the code its challenge was made for (login sub-slice L3c-2c-2; the L3c-2a
# binding: a sign-in code reset also ends recovery-code sessions) while the recovery code's set
# is live (review round 2: replacing the codes also ends a session made with one of them). The
# alias is `proof`.
PROOF_COUNTS: Final = """
    (
        (proof.method = 'totp' AND EXISTS (
            SELECT 1
            FROM app.totp_mfa_enrollments AS proven
            WHERE proven.enrollment_id = proof.enrollment_id
              AND proven.enrollment_state = 'active'
        ))
        OR (proof.method = 'recovery_code' AND EXISTS (
            SELECT 1
            FROM app.sign_in_mfa_challenges AS proven_challenge
            JOIN app.totp_mfa_enrollments AS proven
              ON proven.enrollment_id = proven_challenge.enrollment_id
            JOIN app.recovery_codes AS proven_code ON proven_code.code_id = proof.recovery_code_id
            JOIN app.recovery_code_sets AS proven_set ON proven_set.set_id = proven_code.set_id
            WHERE proven_challenge.challenge_id = proof.challenge_id
              AND proven.enrollment_state = 'active'
              AND proven_set.invalidated_at IS NULL
        ))
    )
"""
SESSION_MFA_SATISFIED: Final = f"""
    (
        EXISTS (
            SELECT 1
            FROM app.browser_session_mfa_proofs AS proof
            WHERE proof.session_id = browser.session_id
              AND {PROOF_COUNTS}
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
# The last column is always NULL here: a session's reauthentication time is read only with its
# reauthentication cookie (`REAUTHENTICATION_OF_COOKIE`, L3d-1 review round 2), so a copied
# session cookie alone never shows or carries one.
LIVE_SESSION: Final = f"""
    SELECT browser.session_id, browser.actor_id::text, account.display_name, browser.created_at,
           browser.last_activity_at, browser.idle_expires_at, browser.absolute_expires_at,
           COALESCE(
               (SELECT proof.method
                FROM app.browser_session_mfa_proofs AS proof
                WHERE proof.session_id = browser.session_id
                  AND {PROOF_COUNTS}),
               'none'
           ),
           NULL::timestamptz
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
# Login sub-slice L4 (Q-2026-10-24-185 point 5): every session write takes the account's password
# lock shared as its first statement; every replacement of the password or the sign-in code takes
# it exclusive first (migration 20270204_192).
SHARE_PASSWORD_LOCK: Final = (
    "SELECT pg_advisory_xact_lock_shared(hashtextextended('password-credential:' || %s::text, 0))"
)
# The pre-authentication state of a sign-in with a one-time password (login sub-slice L4); the
# database sets its 10 minutes.
INSERT_PASSWORD_CHANGE_CHALLENGE: Final = """
    INSERT INTO app.password_change_challenges (
        challenge_id, actor_id, one_time_password_id, token_verifier, checked_verifier_digest,
        username_digest, source_digest
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""
# The open change step of a pre-authentication token: its account, stored digests, the one-time
# password's verifier, the account's names (the password must not be one of them) and whether a
# sign-in code follows (the MFA policy, or an active sign-in code).
OPEN_PASSWORD_CHANGE: Final = """
    SELECT challenge.actor_id, challenge.username_digest, challenge.source_digest,
           credential.verifier_encoding, account.normalized_username, account.display_name,
           account.audit_name,
           account.mfa_policy_class <> 'optional' OR EXISTS (
               SELECT 1
               FROM app.totp_mfa_enrollments AS enrollment
               WHERE enrollment.actor_id = account.actor_id
                 AND enrollment.enrollment_state = 'active'
           )
    FROM app.password_change_challenges AS challenge
    JOIN app.user_accounts AS account ON account.actor_id = challenge.actor_id
    JOIN app.password_credentials AS credential ON credential.actor_id = challenge.actor_id
    WHERE challenge.token_verifier = %s
      AND challenge.completed_at IS NULL
      AND statement_timestamp() < challenge.expires_at
      AND account.lifecycle_state = 'active'
      AND credential.one_time_password_id = challenge.one_time_password_id
"""
CHANGE_ONE_TIME_PASSWORD: Final = (
    "SELECT changed_actor_id, sessions_ended "
    "FROM app.change_one_time_password(%s, %s, %s, %s::jsonb, %s)"
)
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
    INSERT INTO app.browser_session_mfa_proofs (
        session_id, challenge_id, method, enrollment_id, recovery_code_id
    ) VALUES (%s, %s, %s, %s, %s)
"""
# The usable recovery codes of an account: of its live set, neither consumed nor invalidated
# (login sub-slice L3c-2c-2; the codes of an invalidated set keep their own `invalidated_at`
# empty, so the set's invalidation is checked too), and made no earlier than the sign-in code
# the challenge was made for (review round 2: codes from before a sign-in code reset never come
# back with the new code; the bootstrap writes the Owner's code and codes at one time).
USABLE_RECOVERY_CODES: Final = f"""
    SELECT recovery_code.code_id, recovery_code.verifier_encoding
    FROM app.recovery_codes AS recovery_code
    JOIN app.recovery_code_sets AS recovery_set ON recovery_set.set_id = recovery_code.set_id
    JOIN app.totp_mfa_enrollments AS enrollment ON enrollment.enrollment_id = %s
    WHERE recovery_set.actor_id = %s
      AND recovery_set.invalidated_at IS NULL
      AND recovery_set.created_at >= enrollment.created_at
      AND recovery_code.consumed_at IS NULL
      AND recovery_code.invalidated_at IS NULL
    ORDER BY recovery_code.code_id
    LIMIT {RECOVERY_CODE_COUNT}
"""
# One recovery-code try of an account at a time, and none while its codes are made (the key of
# `GENERATION_LOCK`), so parallel tries cannot multiply the slow Argon2id work; a lock of the
# connection, held through the separate transactions of the try and ended when the connection
# closes (review round 2: the sign-in wait locks are not held during the hashing).
RECOVERY_TRY_LOCK: Final = (
    "SELECT pg_try_advisory_lock(hashtextextended('recovery-codes:' || %s::text, 0))"
)
RECORD_WRONG_RECOVERY_CODE: Final = "SELECT app.record_sign_in_wrong_try(%s, %s, 'recovery_code')"
# The recovery code is consumed through the audited account recovery of migration 20260819_08,
# which also revokes every live session of the account.
CONSUME_RECOVERY_CODE: Final = """
    SELECT recovery.recovery_code_consumed
    FROM app.perform_account_recovery(
        %s, %s, %s, 'recovery_code', NULL, 'mfa_recovery', NULL, NULL, NULL, false, %s
    ) AS recovery
"""
# What a reauthentication checks of the session's account (login sub-slice L3d-1): the username
# (the key of the wrong-try count), the current password verifier, and the active sign-in code
# with its last used time step and the current time step of the database clock, when it has one.
REAUTHENTICATION_ACCOUNT: Final = f"""
    SELECT account.normalized_username,
           credential.verifier_encoding,
           account.mfa_policy_class <> 'optional',
           enrollment.enrollment_id,
           enrollment.secret_ciphertext,
           enrollment.secret_nonce,
           enrollment.key_identifier,
           enrollment.protection_algorithm,
           COALESCE(
               (SELECT max(used.time_step)
                FROM app.totp_used_steps AS used
                WHERE used.enrollment_id = enrollment.enrollment_id),
               0
           ),
           floor(extract(epoch FROM statement_timestamp()) / {TOTP_DEFAULT_PERIOD_SECONDS})::bigint
    FROM app.user_accounts AS account
    JOIN app.password_credentials AS credential ON credential.actor_id = account.actor_id
    LEFT JOIN app.totp_mfa_enrollments AS enrollment
      ON enrollment.actor_id = account.actor_id
     AND enrollment.enrollment_state = 'active'
    WHERE account.actor_id = %s
"""
INSERT_REAUTHENTICATION: Final = """
    INSERT INTO app.browser_session_reauthentications (
        reauthentication_id, session_id, actor_id, method, enrollment_id, time_step, token_verifier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING reauthenticated_at
"""
# The reauthentication of a session made with this reauthentication cookie (its sha256 digest;
# L3d-1 review round 2, owner answer of 2026-10-24 to Q-2026-10-24-183).
REAUTHENTICATION_OF_COOKIE: Final = """
    SELECT reauthentication.reauthenticated_at
    FROM app.browser_session_reauthentications AS reauthentication
    WHERE reauthentication.session_id = %s
      AND reauthentication.token_verifier = %s
"""
# A password-only reauthentication of the account within the last minute: the seconds left
# (L3d-1 review round 2, security S-3: each one costs an Argon2id check and a kept row).
PASSWORD_REAUTHENTICATION_INTERVAL_SECONDS: Final = 60
RECENT_PASSWORD_REAUTHENTICATION: Final = f"""
    SELECT ceil(extract(epoch FROM (
               max(reauthentication.reauthenticated_at)
               + interval '{PASSWORD_REAUTHENTICATION_INTERVAL_SECONDS} seconds'
               - statement_timestamp()
           )))::integer
    FROM app.browser_session_reauthentications AS reauthentication
    WHERE reauthentication.actor_id = %s
      AND reauthentication.method = 'password'
    HAVING max(reauthentication.reauthenticated_at)
           > statement_timestamp() - interval '{PASSWORD_REAUTHENTICATION_INTERVAL_SECONDS} seconds'
"""
# One reauthentication of an account at a time (review round 1), a lock of the connection ended
# when it closes.
REAUTHENTICATION_TRY_LOCK: Final = (
    "SELECT pg_try_advisory_lock(hashtextextended('reauthentication:' || %s::text, 0))"
)
# Login sub-slice L3d-2 (owner answer (a) to Q-2026-10-21-157, Q-2026-10-24-184): a recent
# reauthentication of a live session with the password and the sign-in code, found through the
# request's reauthentication cookie (L3d-1 review rounds 2 and 3): the session's latest `totp`
# row, made in the last 15 minutes on the database clock, while its sign-in code is still the
# account's active one. A sign-in with the sign-in code writes such a row too. Parameters: the
# session cookie's digest, the account, the reauthentication cookie's digest. Used for the
# high-risk administration actions (`access_admin_flow.py`, with the session held) and, from
# L3d-2b, for new recovery codes.
REAUTHENTICATION_WINDOW: Final = "15 minutes"
RECENT_SESSION_REAUTHENTICATION: Final = f"""
    SELECT 1
    FROM app.browser_sessions AS browser
    JOIN app.browser_session_reauthentications AS reauthentication
      ON reauthentication.session_id = browser.session_id
     AND reauthentication.actor_id = browser.actor_id
    JOIN app.totp_mfa_enrollments AS enrollment
      ON enrollment.enrollment_id = reauthentication.enrollment_id
     AND enrollment.actor_id = browser.actor_id
     AND enrollment.enrollment_state = 'active'
    WHERE browser.token_verifier = %s
      AND browser.verifier_algorithm = 'sha256'
      AND browser.actor_id = %s
      AND browser.revoked_at IS NULL
      AND statement_timestamp() < browser.idle_expires_at
      AND statement_timestamp() < browser.absolute_expires_at
      AND reauthentication.token_verifier = %s
      AND reauthentication.method = 'totp'
      AND reauthentication.reauthenticated_at
          > statement_timestamp() - interval '{REAUTHENTICATION_WINDOW}'
      AND NOT EXISTS (
          SELECT 1
          FROM app.browser_session_reauthentications AS newer
          WHERE newer.session_id = browser.session_id
            AND newer.method = 'totp'
            AND newer.reauthenticated_at > reauthentication.reauthenticated_at
      )
"""
# The account's recovery-code set that is not invalidated (at most one, migration 20270201_189).
LIVE_RECOVERY_SET: Final = """
    SELECT recovery_set.set_id
    FROM app.recovery_code_sets AS recovery_set
    WHERE recovery_set.actor_id = %s
      AND recovery_set.invalidated_at IS NULL
"""
# The live set without its codes for the sign-in screens (login sub-slice L6): when and how it
# was made, and its codes neither used nor invalidated.
LIVE_RECOVERY_SET_SUMMARY: Final = """
    SELECT recovery_set.set_id, recovery_set.created_at, recovery_set.provenance,
           (SELECT count(*)
            FROM app.recovery_codes AS recovery_code
            WHERE recovery_code.set_id = recovery_set.set_id
              AND recovery_code.consumed_at IS NULL
              AND recovery_code.invalidated_at IS NULL)
    FROM app.recovery_code_sets AS recovery_set
    WHERE recovery_set.actor_id = %s::uuid
      AND recovery_set.invalidated_at IS NULL
"""
# One generation of recovery codes per account at a time (review round 1, security); the lock
# ends with the transaction.
GENERATION_LOCK: Final = (
    "SELECT pg_try_advisory_xact_lock(hashtextextended('recovery-codes:' || %s::text, 0))"
)
# At most 5 recovery-code sets of one account in 15 minutes (review round 2, security; decided
# under the owner's 2026-10-22 rule), so no account can keep the server hashing.
RECOVERY_SETS_PER_WINDOW: Final = 5
RECENT_RECOVERY_SETS: Final = f"""
    SELECT count(*)
    FROM app.recovery_code_sets AS recovery_set
    WHERE recovery_set.actor_id = %s
      AND recovery_set.created_at
          > statement_timestamp() - interval '{RECOVERY_CODE_REGENERATION_WINDOW}'
"""
# The live session read before the codes are committed, held until the commit, so a sign-out
# waits for it (review round 2, security).
LOCK_LIVE_SESSION: Final = f"""{LIVE_SESSION}    FOR SHARE OF browser
"""
LOCK_PRIOR_RECOVERY_SET: Final = """
    SELECT recovery_set.set_id
    FROM app.recovery_code_sets AS recovery_set
    WHERE recovery_set.set_id = %s
      AND recovery_set.actor_id = %s
      AND recovery_set.invalidated_at IS NULL
    FOR UPDATE
"""
INVALIDATE_RECOVERY_SET: Final = """
    UPDATE app.recovery_code_sets AS recovery_set
    SET invalidated_at = statement_timestamp(),
        invalidated_by_actor_id = %s,
        invalidation_provenance = %s
    WHERE recovery_set.set_id = %s
      AND recovery_set.invalidated_at IS NULL
    RETURNING recovery_set.set_id
"""
INSERT_RECOVERY_SET: Final = """
    INSERT INTO app.recovery_code_sets (set_id, actor_id, created_by_actor_id, provenance)
    VALUES (%s, %s, %s, %s)
"""
INSERT_RECOVERY_CODE: Final = """
    INSERT INTO app.recovery_codes (
        code_id, set_id, verifier_encoding, algorithm, work_factor_metadata, provenance
    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
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
    _, actor_id, display_name, created_at, last_activity_at, idle_expires_at, absolute, mfa = row[
        :8
    ]
    reauthenticated_at = row[8]
    return SessionView(
        actor_id=str(actor_id),
        authenticated_at=cast(datetime, created_at),
        last_activity_at=cast(datetime, last_activity_at),
        idle_expires_at=cast(datetime, idle_expires_at),
        absolute_expires_at=cast(datetime, absolute),
        mfa_assurance=MFA_ASSURANCES.get(str(mfa), "none"),
        reauthenticated_at=cast(datetime | None, reauthenticated_at),
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
        password_blocklist: frozenset[str] = frozenset(),
    ) -> None:
        self._database_url = database_url
        # The local password blocklist of every new password, in comparison form (login
        # sub-slice L4); read at start-up.
        self._password_blocklist = password_blocklist
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
        username_key = sign_in_username_digest(account_key, self._sign_in_try_key)
        source_key = sign_in_source_digest(request_source, self._sign_in_try_key)
        if result.verifier_digest is None:
            raise AuthenticationRejected
        if result.one_time_password_id is not None:
            # Login sub-slice L4 (owner answer (a) to Q-2026-10-21-153, Q-2026-10-24-185): a
            # one-time password is changed first, before the sign-in code and before any session
            # or actor; as for MFA, only the digest of the pre-authentication token is stored.
            self._refuse_during_wait(username_key, source_key)
            preauth_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            with self._transaction() as connection:
                connection.execute(
                    INSERT_PASSWORD_CHANGE_CHALLENGE,
                    (
                        uuid4(),
                        result.actor_id,
                        result.one_time_password_id,
                        session_token_digest(preauth_token),
                        result.verifier_digest,
                        username_key,
                        source_key,
                    ),
                )
            return AuthenticationResult(
                phase=AuthenticationPhase.PASSWORD_CHANGE_REQUIRED,
                preauth_token=preauth_token,
                csrf_token=csrf_token,
            )
        return self._after_password(
            actor_id=result.actor_id,
            mfa_required=result.mfa_policy_class != "optional",
            checked_verifier=result.verifier_digest,
            username_key=username_key,
            source_key=source_key,
            csrf_token=csrf_token,
        )

    def _after_password(
        self,
        *,
        actor_id: object,
        mfa_required: bool,
        checked_verifier: bytes,
        username_key: bytes,
        source_key: bytes,
        csrf_token: str,
    ) -> AuthenticationResult:
        """After a checked password (a sign-in, or the forced change of a one-time password):
        the sign-in code challenge or its set-up where MFA is needed, otherwise the session."""
        if mfa_required:
            # Review round 1 (security): a wait that a parallel wrong try started after the
            # first check refuses the MFA step too; the check takes the same locks as the count.
            self._refuse_during_wait(username_key, source_key)
            # No session and no actor before MFA (DL-056): a stored challenge row keeps only the
            # digest of the pre-authentication token (login sub-slice L3c-2a). The wrong-try
            # count is neither added to nor cleared here: it is cleared only when the challenge
            # completes, so a known password cannot clear a count of wrong sign-in codes.
            preauth_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            with self._transaction() as connection:
                enrolled = connection.execute(ACTIVE_ENROLLMENT_OF, (actor_id,)).fetchone()
                enrollment_id = enrolled[0] if enrolled is not None else None
                purpose = "challenge" if enrollment_id is not None else "enrollment"
                connection.execute(
                    INSERT_CHALLENGE,
                    (
                        uuid4(),
                        actor_id,
                        session_token_digest(preauth_token),
                        purpose,
                        enrollment_id,
                        checked_verifier,
                        username_key,
                        source_key,
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
            # Login sub-slice L4 (Q-2026-10-24-185): the password lock first, so a reset either
            # committed before (the comparison below refuses) or waits and ends this session.
            self._hold_password(connection, actor_id)
            # A correct sign-in clears the wrong-try count, unless a parallel wrong try started
            # a wait after this sign-in was checked (fail closed, login sub-slice L3b). It comes
            # before the password work, so a correct password that meets a wait answers after
            # the same work as a wrong one (owner answer (a) to Q-2026-10-23-177; review round
            # 4); a refusal below rolls the clear back.
            cleared = connection.execute(
                CLEAR_WRONG_SIGN_INS, (username_key, source_key, actor_id)
            ).fetchone()
            if cleared is not None and cleared[0] is not None:
                raise AuthenticationRateLimited(int(str(cleared[0])))
            # Review round 1 (security): a password reset that committed after the password
            # check must not leave a session made with the old password, so the verifier this
            # transaction reads must be the one the password was checked against; a reset that
            # has not committed yet waits for the lock above (login sub-slice L4). Login
            # sub-slice L3b (Q-2026-10-23-177 (a)): a comparison of digests, not a second
            # Argon2id check; a reset to the same password stores a new verifier and is refused
            # too.
            current = connection.execute(CURRENT_VERIFIER, (actor_id,)).fetchone()
            if current is None or not hmac.compare_digest(
                verifier_digest(str(current[0])), checked_verifier
            ):
                raise AuthenticationRejected
            connection.execute(INSERT_SESSION, (uuid4(), actor_id, digest, LOGIN_PROVENANCE))
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

    @staticmethod
    def _hold_password(
        connection: psycopg.Connection[tuple[object, ...]], actor_id: object
    ) -> None:
        """The account's `password-credential:` lock, shared, as the first statement of every
        session write (login sub-slice L4, Q-2026-10-24-185 point 5): a replacement of the
        password or the sign-in code takes it exclusive before any other work (a reset takes
        only the `recovery-codes:` lock before it), so the two never both commit with the old
        one (the L3a-1 and L3d-1 bindings)."""
        connection.execute(SHARE_PASSWORD_LOCK, (actor_id,))

    def change_password(
        self,
        *,
        preauth_token: str,
        new_password: str,
        request_id: str,
    ) -> AuthenticationResult:
        """The forced change of a one-time password (login sub-slice L4, owner answer (a) to
        Q-2026-10-21-153, Q-2026-10-24-185 points 3 and 4): the open change step of the
        pre-authentication token, the wait of its stored username and source, the shared rule
        (15 to 128 code points before and after NFC, the blocklist, not one of the account's
        names) and a password other than the one-time password; then, in one transaction of
        `app.change_one_time_password`, the password replaced, the step completed and every
        session ended; then the sign-in code where MFA is needed, otherwise the session."""
        if not preauth_token or len(preauth_token) > MAX_SESSION_TOKEN_LENGTH:
            raise AuthenticationRejected
        digest = session_token_digest(preauth_token)
        with self._transaction() as connection:
            opened = connection.execute(OPEN_PASSWORD_CHANGE, (digest,)).fetchone()
        if opened is None:
            raise AuthenticationRejected
        actor_id, username_digest, source_digest, one_time_verifier = opened[:4]
        names = tuple(str(name) for name in opened[4:7])
        mfa_required = opened[7] is True
        username_key = bytes(cast(bytes, username_digest))
        source_key = bytes(cast(bytes, source_digest))
        self._refuse_during_wait(username_key, source_key)
        try:
            accepted = validate_new_password(
                new_password, blocked=self._password_blocklist, context=names
            )
        except ValueError:
            raise NewPasswordRejected from None
        # The one-time password in another case or spacing is refused too (review round 1).
        if any(
            self._password_service.verify_password(form, str(one_time_verifier)).is_valid
            for form in one_time_password_forms(accepted)
        ):
            raise NewPasswordRejected
        credential = self._password_service.hash_password(accepted)
        correlation = uuid4()
        with self._transaction() as connection:
            try:
                changed = connection.execute(
                    CHANGE_ONE_TIME_PASSWORD,
                    (
                        digest,
                        credential.verifier_encoding,
                        credential.algorithm,
                        json.dumps(dict(credential.work_factor_metadata)),
                        correlation,
                    ),
                ).fetchone()
            except psycopg.errors.RaiseException:
                # The step was used, ended, or the password changed meanwhile.
                raise AuthenticationRejected from None
        if changed is None or str(changed[0]) != str(actor_id):
            raise AuthenticationRejected
        logger.info(
            "password change decision",
            extra={
                "outcome": "changed",
                "request_id": request_id,
                "correlation_id": str(correlation),
            },
        )
        return self._after_password(
            actor_id=actor_id,
            mfa_required=mfa_required,
            checked_verifier=verifier_digest(credential.verifier_encoding),
            username_key=username_key,
            source_key=source_key,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
        )

    def inspect_session(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> SessionView:
        """The live session; `reauthenticated_at` only with the reauthentication cookie made for
        this session (L3d-1 review round 2). It is the time of that cookie's row, whatever its
        method or age: for display only; L3d-2 checks its own window in the action's
        transaction."""
        digest = session_token_digest(session_token)
        with self._transaction() as connection:
            row = connection.execute(LIVE_SESSION, (digest,)).fetchone()
            if row is None:
                raise AuthenticationRejected
            view = session_view(row)
            # A missing or malformed reauthentication cookie only means no reauthentication; it
            # never turns a live session away (review round 2).
            if not reauthentication_token or len(reauthentication_token) > MAX_SESSION_TOKEN_LENGTH:
                return view
            reauthentication = connection.execute(
                REAUTHENTICATION_OF_COOKIE,
                (row[0], session_token_digest(reauthentication_token)),
            ).fetchone()
        if reauthentication is None:
            return view
        return replace(view, reauthenticated_at=cast(datetime, reauthentication[0]))

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
        return self._open_secret(challenge[1], challenge[5], challenge[6:10], request_id=request_id)

    def _open_secret(
        self,
        actor_id: object,
        enrollment_id: object,
        protected: tuple[object, ...],
        *,
        request_id: str,
    ) -> TotpSecret:
        """A sign-in code's secret (ciphertext, nonce, key identifier and algorithm), opened with
        the protection key."""
        if self._totp_protection_key is None:
            raise self._unavailable()
        ciphertext, nonce, key_identifier, protection_algorithm = protected
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
                actor_id=UUID(str(actor_id)),
                enrollment_id=UUID(str(enrollment_id)),
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
    def _write_sign_in_reauthentication(
        connection: psycopg.Connection[tuple[object, ...]],
        row: tuple[object, ...],
        *,
        actor_id: object,
        enrollment_id: object,
        step: int,
    ) -> tuple[str, datetime]:
        """A sign-in with the sign-in code also counts as a reauthentication of its new session
        (login sub-slice L3d-2, decided by Claude under the owner's 2026-10-23 22:30 rule): the
        same `totp` row as `reauthenticate` writes, for the step just used, in the same
        transaction, with a new reauthentication cookie of which only the digest is kept. So
        the 15 minutes of Q-2026-10-21-157 (a) start at the sign-in, and only in the browser
        that signed in (L3d-1 review round 2)."""
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        try:
            written = connection.execute(
                INSERT_REAUTHENTICATION,
                (
                    uuid4(),
                    row[0],
                    actor_id,
                    "totp",
                    enrollment_id,
                    step,
                    session_token_digest(token),
                ),
            ).fetchone()
        except psycopg.errors.IntegrityConstraintViolation as exc:
            # The guard refused (for example the account was disabled meanwhile): a refused
            # sign-in, as in `reauthenticate` (review round 1, security note).
            raise AuthenticationRejected from exc
        if written is None:
            raise AuthenticationRejected
        return token, cast(datetime, written[0])

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
        recovery_code_id: object = None,
    ) -> tuple[object, ...]:
        """After the used step or the consumed recovery code: the challenge completed, the
        password verifier compared, the session and its proof (`totp`, or `recovery_code` with
        the consumed code) written and the live session read back."""
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
        method = "totp" if recovery_code_id is None else "recovery_code"
        connection.execute(
            INSERT_MFA_PROOF,
            (
                session_id,
                challenge_id,
                method,
                enrollment_id if recovery_code_id is None else None,
                recovery_code_id,
            ),
        )
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
        """The sign-in code challenge (login sub-slice L3c-2a, DL-056, SEC-013), with the sign-in
        code or with a recovery code (login sub-slice L3c-2c-2, DL-058, API-098)."""
        if method not in ("totp", "recovery_code") or (
            method == "totp" and self._totp_protection_key is None
        ):
            # Without the protection key no sign-in code can be checked (development and tests
            # without a key file); a recovery code needs no key.
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
        if method == "recovery_code":
            return self._complete_with_recovery_code(
                challenge, code, username_key, source_key, request_id=request_id
            )
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
            # The password lock first (login sub-slice L4, Q-2026-10-24-185).
            self._hold_password(connection, actor_id)
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
            reauthentication_token, reauthenticated_at = self._write_sign_in_reauthentication(
                connection, row, actor_id=actor_id, enrollment_id=enrollment_id, step=step
            )
        logger.info(
            "sign-in code decision", extra={"outcome": "authenticated", "request_id": request_id}
        )
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            session=replace(session_view(row), reauthenticated_at=reauthenticated_at),
            reauthentication_token=reauthentication_token,
        )

    def _complete_with_recovery_code(
        self,
        challenge: tuple[object, ...],
        code: str,
        username_key: bytes,
        source_key: bytes,
        *,
        request_id: str,
    ) -> AuthenticationResult:
        """A recovery code instead of the sign-in code (login sub-slice L3c-2c-2), on one
        connection that holds the account's try lock (review round 2): the try lock (refused at
        once when held), the wait checked again under it (its own short transaction, so the
        sign-in wait locks are not held during the hashing), the usable codes read, the typed
        code compared with every one of them outside any transaction (at most 10 Argon2id
        checks, so a match and a miss do the same work); a wrong code is counted as a wrong try
        of kind `recovery_code` before the lock ends; the right code, in one transaction: the
        clear first, the code consumed through the audited account recovery (every other
        session of the account revoked), the challenge completed, the password verifier
        compared, the session and its `recovery_code` proof written and the live session read
        back."""
        challenge_id, actor_id, checked_verifier = challenge[:3]
        enrollment_id = challenge[5]
        candidate = code.strip()
        verifiers = Argon2idRecoveryCodeVerifierProvider()
        session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        # The audit event's correlation id, also written to the decision log (review round 1).
        correlation = uuid4()
        with self._transaction() as connection:
            held = connection.execute(RECOVERY_TRY_LOCK, (actor_id,)).fetchone()
            connection.commit()
            if held is None or held[0] is not True:
                self._log_recovery_decision("rejected", request_id)
                raise AuthenticationRejected
            waiting = connection.execute(
                SIGN_IN_WAIT_SECONDS, (username_key, source_key)
            ).fetchone()
            connection.commit()
            if waiting is not None and waiting[0] is not None:
                raise AuthenticationRateLimited(int(str(waiting[0])))
            usable = connection.execute(USABLE_RECOVERY_CODES, (enrollment_id, actor_id)).fetchall()
            connection.commit()
            matched = [
                code_id
                for code_id, encoding in usable
                if verifiers.matches(candidate, str(encoding))
            ]
            if not matched:
                # The wrong try is counted before the try lock ends, so the next try of the
                # account sees it (review round 1).
                counted = connection.execute(
                    RECORD_WRONG_RECOVERY_CODE, (username_key, source_key)
                ).fetchone()
                connection.commit()
                self._log_recovery_decision("rejected", request_id)
                if counted is not None and counted[0] is not None:
                    raise AuthenticationRateLimited(int(str(counted[0])))
                raise AuthenticationRejected
            # The password lock first (login sub-slice L4, Q-2026-10-24-185).
            self._hold_password(connection, actor_id)
            self._clear_wrong_tries(connection, username_key, source_key, actor_id)
            try:
                consumed = connection.execute(
                    CONSUME_RECOVERY_CODE, (actor_id, actor_id, correlation, matched[0])
                ).fetchone()
            except psycopg.errors.RaiseException:
                # The account recovery refuses (the account or the code changed meanwhile).
                self._log_recovery_decision("rejected", request_id)
                raise AuthenticationRejected from None
            if consumed is None or consumed[0] is not True:
                raise AuthenticationRejected
            row = self._write_proven_session(
                connection,
                challenge_id=challenge_id,
                actor_id=actor_id,
                checked_verifier=checked_verifier,
                enrollment_id=None,
                session_digest=session_token_digest(session_token),
                provenance=MFA_RECOVERY_CODE_PROVENANCE,
                recovery_code_id=matched[0],
            )
        logger.info(
            "recovery code sign-in decision",
            extra={
                "outcome": "authenticated",
                "request_id": request_id,
                "correlation_id": str(correlation),
            },
        )
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            session=session_view(row),
        )

    @staticmethod
    def _log_recovery_decision(outcome: str, request_id: str) -> None:
        logger.info(
            "recovery code sign-in decision", extra={"outcome": outcome, "request_id": request_id}
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
            # The password lock first (L4 review round 2), as every other write of a sign-in.
            self._hold_password(connection, actor_id)
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
            # The password lock first (login sub-slice L4, Q-2026-10-24-185).
            self._hold_password(connection, actor_id)
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
            reauthentication_token, reauthenticated_at = self._write_sign_in_reauthentication(
                connection, row, actor_id=actor_id, enrollment_id=enrollment_id, step=step
            )
        logger.info(
            "sign-in code enrollment decision",
            extra={"outcome": "authenticated", "request_id": request_id},
        )
        return AuthenticationResult(
            phase=AuthenticationPhase.AUTHENTICATED,
            session_token=session_token,
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            session=replace(session_view(row), reauthenticated_at=reauthenticated_at),
            reauthentication_token=reauthentication_token,
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
        """High-risk reauthentication (login sub-slice L3d-1, SEC-018, API-097, owner answer (a)
        to Q-2026-10-21-157): a live session gives the password again and, when its account
        needs MFA, a sign-in code (`totp`; a recovery code is not accepted here, as the owner's
        answer names the sign-in code). One reauthentication of an account at a time, on one
        connection holding the account's try lock (review round 1: parallel guesses would each
        pass the wait check and do the Argon2id work); wrong tries are counted for the username,
        with the session as the source (the API passes no source here), before the lock ends; a
        wait answers 429 before any check. The right answer, in one transaction: the clear
        first, the sign-in code's step recorded, the password verifier compared with the one
        checked, the reauthentication written and the session locked and read last (review
        round 1: the account and the sign-in code before the session, the order of the Owner's
        functions); a new CSRF token and a new reauthentication cookie are answered, and only
        the cookie's sha256 digest is kept on the row (review round 2, owner answer of
        2026-10-24 to Q-2026-10-24-183). A password-only reauthentication of the account within
        the last minute answers 429 under the lock, before any password check (review round 2,
        security S-3)."""
        digest = session_token_digest(session_token)
        if not password or len(password) > MAX_REAUTHENTICATION_PASSWORD_LENGTH:
            raise AuthenticationRejected
        with self._transaction() as connection:
            session = connection.execute(LIVE_SESSION, (digest,)).fetchone()
            if session is None:
                raise AuthenticationRejected
            session_id, actor_id = session[0], session[1]
            account = connection.execute(REAUTHENTICATION_ACCOUNT, (actor_id,)).fetchone()
            connection.commit()
            if account is None:
                raise AuthenticationRejected
            username, verifier, policy_requires_mfa, enrollment_id = account[:4]
            last_used_step, current_step = account[8], account[9]
            needs_mfa = bool(policy_requires_mfa) or enrollment_id is not None
            if needs_mfa and (
                second_factor_method != "totp"
                or second_factor_code is None
                or enrollment_id is None
            ):
                raise AuthenticationRejected
            if not needs_mfa and second_factor_method is not None:
                raise AuthenticationRejected
            if needs_mfa and self._totp_protection_key is None:
                # Without the protection key no sign-in code can be checked.
                raise self._unavailable()
            held = connection.execute(REAUTHENTICATION_TRY_LOCK, (actor_id,)).fetchone()
            connection.commit()
            if held is None or held[0] is not True:
                logger.info(
                    "reauthentication decision",
                    extra={"outcome": "rejected", "request_id": request_id},
                )
                raise AuthenticationRejected
            if not needs_mfa:
                recent = connection.execute(
                    RECENT_PASSWORD_REAUTHENTICATION, (actor_id,)
                ).fetchone()
                connection.commit()
                if recent is not None:
                    logger.info(
                        "reauthentication decision",
                        extra={"outcome": "rate_limited", "request_id": request_id},
                    )
                    raise AuthenticationRateLimited(max(1, int(str(recent[0]))))
            username_key = sign_in_username_digest(str(username), self._sign_in_try_key)
            source_key = sign_in_source_digest(f"session:{session_id}", self._sign_in_try_key)
            self._refuse_during_wait(username_key, source_key)
            if not self._password_service.verify_password(password, str(verifier)).is_valid:
                self._refuse_wrong_try(
                    RECORD_WRONG_SIGN_IN, username_key, source_key, request_id=request_id
                )
            step: int | None = None
            if needs_mfa:
                secret = self._open_secret(
                    actor_id, enrollment_id, account[4:8], request_id=request_id
                )
                step = self._matching_step(
                    str(second_factor_code),
                    secret,
                    current_step=current_step,
                    last_used_step=last_used_step,
                )
                if step is None:
                    self._refuse_wrong_try(
                        RECORD_WRONG_SIGN_IN_CODE, username_key, source_key, request_id=request_id
                    )
            # The password lock first (login sub-slice L4, Q-2026-10-24-185).
            self._hold_password(connection, actor_id)
            self._clear_wrong_tries(connection, username_key, source_key, actor_id)
            if step is not None:
                locked = connection.execute(LOCK_ACTIVE_ENROLLMENT, (enrollment_id,)).fetchone()
                last = connection.execute(LAST_USED_STEP, (enrollment_id,)).fetchone()
                if locked is None or last is None or step <= int(str(last[0])):
                    raise AuthenticationRejected
                connection.execute(RECORD_USED_STEP, (enrollment_id, step))
            # A password change after the check refuses (the L3a-1 guard).
            current = connection.execute(CURRENT_VERIFIER, (actor_id,)).fetchone()
            if current is None or not hmac.compare_digest(
                verifier_digest(str(current[0])), verifier_digest(str(verifier))
            ):
                raise AuthenticationRejected
            reauthentication_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            try:
                written = connection.execute(
                    INSERT_REAUTHENTICATION,
                    (
                        uuid4(),
                        session_id,
                        actor_id,
                        "password" if step is None else "totp",
                        enrollment_id if step is not None else None,
                        step,
                        session_token_digest(reauthentication_token),
                    ),
                ).fetchone()
            except psycopg.errors.IntegrityConstraintViolation:
                # The guard refuses a change committed meanwhile (the account disabled, its MFA
                # policy raised): the generic rejection (review round 1).
                raise AuthenticationRejected from None
            row = connection.execute(LOCK_LIVE_SESSION, (digest,)).fetchone()
            if row is None or row[0] != session_id or written is None:
                raise AuthenticationRejected
        logger.info(
            "reauthentication decision",
            extra={"outcome": "authenticated", "request_id": request_id},
        )
        return ReauthenticationResult(
            session=replace(session_view(row), reauthenticated_at=cast(datetime, written[0])),
            csrf_token=secrets.token_urlsafe(SESSION_TOKEN_BYTES),
            reauthentication_token=reauthentication_token,
        )

    def _refuse_wrong_try(
        self, record: str, username_key: bytes, source_key: bytes, *, request_id: str
    ) -> NoReturn:
        """A wrong password or sign-in code at a reauthentication is a wrong try (429 when it
        starts a wait, otherwise 401)."""
        with self._transaction() as connection:
            counted = connection.execute(record, (username_key, source_key)).fetchone()
        logger.info(
            "reauthentication decision", extra={"outcome": "rejected", "request_id": request_id}
        )
        if counted is not None and counted[0] is not None:
            raise AuthenticationRateLimited(int(str(counted[0])))
        raise AuthenticationRejected

    @staticmethod
    def _recently_signed_in_with_code(
        connection: psycopg.Connection[tuple[object, ...]],
        digest: bytes,
        reauthentication_token: str | None,
    ) -> object:
        """The account of a live session proven with its sign-in code, which is still active,
        reauthenticated with the password and the sign-in code (a sign-in with the code counts)
        within the last 15 minutes, shown by the request's reauthentication cookie (login
        sub-slice L3d-2b, Q-2026-10-24-184 point 8; before it the session's sign-in proof
        alone, so a copied session cookie could take new codes). For the first codes too, so a
        session left open cannot take them later (L3c-2c-1 review round 1)."""
        row = connection.execute(LIVE_SESSION, (digest,)).fetchone()
        if row is None or row[7] != "totp":
            raise AuthenticationRejected
        if not reauthentication_token or len(reauthentication_token) > MAX_SESSION_TOKEN_LENGTH:
            raise AuthenticationRejected
        recent = connection.execute(
            RECENT_SESSION_REAUTHENTICATION,
            (digest, row[1], session_token_digest(reauthentication_token)),
        ).fetchone()
        if recent is None:
            raise AuthenticationRejected
        return row[1]

    @staticmethod
    def _one_generation_at_a_time(
        connection: psycopg.Connection[tuple[object, ...]], actor_id: object
    ) -> None:
        """Review round 1 (security): the slow Argon2id work of one account runs once at a time;
        a parallel request of the account is refused instead of hashing too."""
        held = connection.execute(GENERATION_LOCK, (actor_id,)).fetchone()
        if held is None or held[0] is not True:
            raise AuthenticationRejected

    @staticmethod
    def _within_the_set_limit(
        connection: psycopg.Connection[tuple[object, ...]], actor_id: object
    ) -> None:
        """At most 5 sets of the account in 15 minutes, checked before the slow hashing."""
        made = connection.execute(RECENT_RECOVERY_SETS, (actor_id,)).fetchone()
        if made is None or int(str(made[0])) >= RECOVERY_SETS_PER_WINDOW:
            raise AuthenticationRejected

    @staticmethod
    def _still_signed_in_with_code(
        connection: psycopg.Connection[tuple[object, ...]], digest: bytes
    ) -> None:
        """The session is still live and proven with an active sign-in code when the codes are
        written; the row stays locked until the commit."""
        row = connection.execute(LOCK_LIVE_SESSION, (digest,)).fetchone()
        if row is None or row[7] != "totp":
            raise AuthenticationRejected

    @staticmethod
    def _new_recovery_codes() -> tuple[tuple[str, ...], list[tuple[UUID, str, str, str]]]:
        """10 new recovery codes and their Argon2id verifiers (the existing services of
        `recovery_code_security.py`); only the verifiers are stored."""
        generator = SecureRecoveryCodeGenerator()
        verifiers = Argon2idRecoveryCodeVerifierProvider()
        codes: list[str] = []
        rows: list[tuple[UUID, str, str, str]] = []
        while len(codes) < RECOVERY_CODE_COUNT:
            code = generator.generate().get_secret_value()
            if canonical_recovery_code(code) in map(canonical_recovery_code, codes):
                # 60 random bits do not repeat in 10 codes; a repeat means a broken entropy source.
                raise RuntimeError("duplicate recovery-code material")
            verifier = verifiers.encode(code)
            codes.append(code)
            rows.append(
                (
                    uuid4(),
                    verifier.verifier_encoding,
                    verifier.algorithm,
                    json.dumps(
                        dict(verifier.work_factor_metadata), separators=(",", ":"), sort_keys=True
                    ),
                )
            )
        return tuple(codes), rows

    @staticmethod
    def _write_recovery_set(
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        set_id: UUID,
        actor_id: object,
        rows: list[tuple[UUID, str, str, str]],
        provenance: str,
    ) -> None:
        """The set and its codes; a parallel set of the account answers the generic rejection."""
        try:
            connection.execute(INSERT_RECOVERY_SET, (set_id, actor_id, actor_id, provenance))
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name != "recovery_code_sets_one_live_per_actor":
                raise
            raise AuthenticationRejected from None
        with connection.cursor() as cursor:
            cursor.executemany(
                INSERT_RECOVERY_CODE,
                [
                    (code_id, set_id, encoding, algorithm, work_factors, provenance)
                    for code_id, encoding, algorithm, work_factors in rows
                ],
            )

    def live_recovery_code_set(
        self, *, session_token: str, request_id: str
    ) -> RecoveryCodeSetSummary | None:
        """The account's live recovery-code set without its codes, or None (login sub-slice L6,
        API-098): any live session of the account may read it, so a person can replace the
        bootstrap's set and see a set whose codes they never received."""
        digest = session_token_digest(session_token)
        with self._transaction() as connection:
            session = connection.execute(LIVE_SESSION, (digest,)).fetchone()
            if session is None:
                raise AuthenticationRejected
            row = connection.execute(LIVE_RECOVERY_SET_SUMMARY, (session[1],)).fetchone()
        if row is None:
            return None
        set_id, created_at, provenance, usable = row
        return RecoveryCodeSetSummary(
            set_id=cast(UUID, set_id),
            created_at=cast(datetime, created_at),
            made_by=RECOVERY_SET_ORIGINS.get(str(provenance), "other"),
            usable_count=cast(int, usable),
        )

    def issue_recovery_codes(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        """The first 10 recovery codes of an account (login sub-slice L3c-2c-1, DL-058, API-098):
        a live session proven with the account's sign-in code and reauthenticated with it within
        the last 15 minutes (L3d-2b: its reauthentication cookie), while
        the account has no recovery-code set that is not invalidated; shown once and stored
        only as Argon2id verifiers. Later sets come only by regeneration. One READ COMMITTED
        transaction: every check before the slow hashing, then the set, then the session read
        back."""
        digest = session_token_digest(session_token)
        set_id = uuid4()
        with self._transaction() as connection:
            actor_id = self._recently_signed_in_with_code(
                connection, digest, reauthentication_token
            )
            # The account's lock first (review round 2): every later check then sees what a
            # parallel request of the account committed.
            self._one_generation_at_a_time(connection, actor_id)
            if connection.execute(LIVE_RECOVERY_SET, (actor_id,)).fetchone() is not None:
                raise AuthenticationRejected
            self._within_the_set_limit(connection, actor_id)
            codes, rows = self._new_recovery_codes()
            self._write_recovery_set(
                connection,
                set_id=set_id,
                actor_id=actor_id,
                rows=rows,
                provenance=RECOVERY_CODES_PROVENANCE,
            )
            self._still_signed_in_with_code(connection, digest)
        logger.info("recovery code decision", extra={"outcome": "issued", "request_id": request_id})
        return RecoveryCodeSetResult(set_id=set_id, codes=codes)

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        """Replace the account's live recovery-code set (login sub-slice L3c-2c-1, API-098,
        TEST-129): a live session proven with the account's sign-in code and reauthenticated
        with it within the last 15 minutes (L3d-2b: its reauthentication cookie) names the set it
        replaces; in one READ COMMITTED transaction the prior set is
        locked before the slow hashing (review round 1), then invalidated, so none of its codes
        works again, and 10 new codes are written and shown once."""
        digest = session_token_digest(session_token)
        set_id = uuid4()
        with self._transaction() as connection:
            actor_id = self._recently_signed_in_with_code(
                connection, digest, reauthentication_token
            )
            self._one_generation_at_a_time(connection, actor_id)
            if (
                connection.execute(LOCK_PRIOR_RECOVERY_SET, (prior_set_id, actor_id)).fetchone()
                is None
            ):
                raise AuthenticationRejected
            self._within_the_set_limit(connection, actor_id)
            codes, rows = self._new_recovery_codes()
            # Review round 2: the invalidation names the set that replaces it.
            invalidation = json.dumps(
                {
                    "reason": RECOVERY_CODES_REGENERATED_PROVENANCE,
                    "replacement_set_id": str(set_id),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            if (
                connection.execute(
                    INVALIDATE_RECOVERY_SET, (actor_id, invalidation, prior_set_id)
                ).fetchone()
                is None
            ):
                raise AuthenticationRejected
            self._write_recovery_set(
                connection,
                set_id=set_id,
                actor_id=actor_id,
                rows=rows,
                provenance=RECOVERY_CODES_REGENERATED_PROVENANCE,
            )
            self._still_signed_in_with_code(connection, digest)
        logger.info(
            "recovery code decision", extra={"outcome": "regenerated", "request_id": request_id}
        )
        return RecoveryCodeSetResult(set_id=set_id, codes=codes)
