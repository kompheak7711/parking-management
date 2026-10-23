"""Login sub-slice L3c-2a: the stored sign-in code challenge and the session's MFA proof.

DL-056, SEC-013, API-096, TEST-128, DB-AUTH-003, DB-AUTH-004 (migration `20270130_187`). One
throwaway database at head; accounts, real Argon2id credentials and active sign-in codes (TOTP
enrollments protected with a test key) are written as the table owner, and every sign-in runs as
the runtime role through `PostgresAuthenticationFlow`. Each test uses its own accounts and
request sources, so the order of the tests does not matter. Sign-in codes are made for the time
step of the database clock, never of the test machine.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from psycopg import errors
from pydantic import SecretStr
from starlette.requests import Request

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
)
from property_rental.auth_flow import (
    PostgresAuthenticationFlow,
    sign_in_source_digest,
    sign_in_username_digest,
)
from property_rental.local_authentication import normalize_local_username, verifier_digest
from property_rental.password_security import PasswordHashService
from property_rental.session_actor import PostgresSessionActorResolver
from property_rental.settings import Settings
from property_rental.totp_security import (
    Aes256GcmTotpSecretProtector,
    TotpSecret,
    TotpSecretGenerator,
    TotpService,
)
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

REVISION = "20270130_187"
PREVIOUS = "20270129_186"
PASSWORD = "correct horse battery staple"
WRONG = "wrong horse battery staple"
ORIGIN = "https://property.test"
PROVENANCE = "login-slice-l3c-2a-test"
KEY = bytes(range(32))
KEY_IDENTIFIER = "l3c-2a-test-key"
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    f"lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,%s,%s,'active',%s,'{PROVENANCE}')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    f"VALUES (%s,%s,'{PROVENANCE}')"
)
ADD_CREDENTIAL = (
    "INSERT INTO app.password_credentials(actor_id,verifier_encoding,algorithm,"
    "work_factor_metadata,provenance) VALUES (%s,%s,%s,%s::jsonb,'initial-credential')"
)
ADD_ENROLLMENT = (
    "INSERT INTO app.totp_mfa_enrollments(enrollment_id,actor_id,secret_ciphertext,secret_nonce,"
    "key_identifier,protection_algorithm,totp_algorithm,created_by_actor_id,provenance) "
    f"VALUES (%s,%s,%s,%s,%s,%s,'sha1',%s,'{PROVENANCE}')"
)
ACTIVATE_ENROLLMENT = (
    "UPDATE app.totp_mfa_enrollments SET enrollment_state='active',activated_by_actor_id=%s,"
    f"activation_provenance='{PROVENANCE}' WHERE enrollment_id=%s"
)
CHALLENGES_OF = (
    "SELECT token_verifier, purpose, completed_at IS NOT NULL, password_verifier_digest, "
    "username_digest, source_digest FROM app.sign_in_mfa_challenges WHERE actor_id = %s "
    "ORDER BY created_at"
)
SESSIONS_OF = (
    "SELECT session_id, token_verifier, creation_provenance FROM app.browser_sessions "
    "WHERE actor_id = %s ORDER BY created_at"
)
PROOFS_OF = (
    "SELECT proof.method, proof.enrollment_id FROM app.browser_session_mfa_proofs AS proof "
    "JOIN app.browser_sessions AS browser ON browser.session_id = proof.session_id "
    "WHERE browser.actor_id = %s"
)
TRIES_OF = "SELECT try_kind FROM app.sign_in_wrong_tries WHERE username_digest = %s ORDER BY try_no"
CLEARS_OF = "SELECT count(*) FROM app.sign_in_try_clears WHERE username_digest = %s"
USED_STEPS_OF = (
    "SELECT time_step FROM app.totp_used_steps WHERE enrollment_id = %s ORDER BY time_step"
)
CREDENTIAL_OF = "SELECT verifier_encoding FROM app.password_credentials WHERE actor_id = %s"
# Connections of the test database that wait for a lock; `pg_locks` shows every role's locks
# (review round 2: `pg_stat_activity` may hide another role's wait). A row lock wait is a wait for
# the holder's transaction id, which has no database, so the waiting connections are counted and
# kept to the test database by their `pg_stat_activity` row (review round 3, login sub-slice
# L3c-2b).
LOCK_WAITS = (
    "SELECT count(DISTINCT lock.pid) FROM pg_catalog.pg_locks AS lock "
    "JOIN pg_catalog.pg_stat_activity AS activity ON activity.pid = lock.pid "
    "WHERE NOT lock.granted AND activity.datname = current_database()"
)
ADD_CHALLENGE = (
    "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, purpose, "
    "enrollment_id, password_verifier_digest, username_digest, source_digest) "
    "VALUES (%s, %s, %s, 'challenge', %s, %s, %s, %s)"
)
ADD_SESSION = (
    "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
    "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)"
)
ADD_PROOF = (
    "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
    "enrollment_id) VALUES (%s, %s, 'totp', %s)"
)
CHALLENGE_ID_OF = "SELECT challenge_id FROM app.sign_in_mfa_challenges WHERE token_verifier = %s"
TURN_CODE_OFF = (
    "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
    "disabled_by_actor_id = %s, disablement_provenance = 'l3c-2a-test' WHERE enrollment_id = %s"
)
DATABASE_STEP = (
    "SELECT floor(extract(epoch FROM statement_timestamp()) / 30)::bigint, "
    "30 - mod(extract(epoch FROM statement_timestamp())::numeric, 30)"
)


@dataclass(frozen=True)
class CodeDatabase:
    owner_url: str
    runtime_url: str


@dataclass(frozen=True)
class Account:
    actor_id: uuid.UUID
    username: str
    secret: TotpSecret | None
    enrollment_id: uuid.UUID | None


@pytest.fixture(scope="module")
def code_database(migrated_database_url: str) -> Iterator[CodeDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_sign_in_code") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        yield CodeDatabase(temporary, runtime_url)


def add_account(
    database: CodeDatabase,
    username: str,
    *,
    account_class: str = "manager",
    mfa: str = "required",
    sign_in_code: bool = True,
) -> Account:
    """An account with the test password and, if asked, an active sign-in code."""
    credential = PasswordHashService().hash_password(PASSWORD)
    actor_id = uuid.uuid4()
    secret = None
    enrollment_id = None
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(ADD_ACCOUNT, (actor_id, username, username, username, mfa))
        connection.execute(ADD_CLASS, (actor_id, account_class))
        connection.execute(
            ADD_CREDENTIAL,
            (
                actor_id,
                credential.verifier_encoding,
                credential.algorithm,
                json.dumps(dict(credential.work_factor_metadata)),
            ),
        )
        if sign_in_code:
            secret, enrollment_id = add_sign_in_code(connection, actor_id)
        connection.commit()
    return Account(actor_id, username, secret, enrollment_id)


def add_sign_in_code(
    connection: psycopg.Connection[tuple[Any, ...]], actor_id: uuid.UUID
) -> tuple[TotpSecret, uuid.UUID]:
    """An active sign-in code for the account, protected with the test key (not committed)."""
    secret = TotpSecretGenerator().generate()
    enrollment_id = uuid.uuid4()
    protected = Aes256GcmTotpSecretProtector(key=KEY, key_identifier=KEY_IDENTIFIER).protect(
        secret, actor_id=actor_id, enrollment_id=enrollment_id
    )
    connection.execute(
        ADD_ENROLLMENT,
        (
            enrollment_id,
            actor_id,
            protected.ciphertext,
            protected.nonce,
            protected.key_identifier,
            protected.encryption_algorithm,
            actor_id,
        ),
    )
    connection.execute(ACTIVATE_ENROLLMENT, (actor_id, enrollment_id))
    return secret, enrollment_id


def fresh_step(database: CodeDatabase) -> int:
    """The time step of the database clock, with at least 5 seconds of it left."""
    while True:
        with psycopg.connect(database.owner_url) as connection:
            row = connection.execute(DATABASE_STEP).fetchone()
        assert row is not None
        if float(str(row[1])) >= 5:
            return int(str(row[0]))
        time.sleep(float(str(row[1])) + 0.5)


def code_for(account: Account, step: int) -> str:
    assert account.secret is not None
    return TotpService().generate_code(account.secret, at_time=step * 30)


def wrong_code(account: Account, step: int) -> str:
    right = {code_for(account, step), code_for(account, step - 1)}
    return next(code for code in ("000000", "111111", "222222") if code not in right)


def read(database: CodeDatabase, query: str, key: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(database.owner_url) as connection:
        return connection.execute(query, (key,)).fetchall()


def lock_waits(database: CodeDatabase) -> int:
    """The number of connections of the test database that wait for a lock."""
    with psycopg.connect(database.owner_url) as connection:
        row = connection.execute(LOCK_WAITS).fetchone()
    assert row is not None
    return int(str(row[0]))


def username_key(username: str) -> bytes:
    return sign_in_username_digest(normalize_local_username(username))


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def challenge_token(flow: PostgresAuthenticationFlow, account: Account, source: str) -> str:
    result = flow.login(
        username=account.username, password=PASSWORD, request_source=source, request_id="l3c-2a"
    )
    assert result.phase is AuthenticationPhase.MFA_REQUIRED
    assert result.session is None and result.session_token is None
    assert result.preauth_token is not None
    return result.preauth_token


def request_with(cookie: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", cookie.encode("latin-1"))],
        }
    )


def test_an_account_with_a_sign_in_code_gets_a_session_only_after_the_right_code(
    code_database: CodeDatabase,
) -> None:
    """TEST-128, DL-056: the Owner, a Manager and a Staff account with MFA `optional` and an
    active sign-in code get `mfa_required` and no session after the right password; the
    challenge row keeps only the sha256 digest of the pre-authentication token. The right code
    gives a session with `mfa_assurance` `totp` and one proof, which the session read and the
    actor resolver accept."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    for username, account_class, mfa in (
        ("l3c.owner", "owner", "required"),
        ("l3c.manager", "manager", "required"),
        ("l3c.staff-code", "staff", "optional"),
    ):
        account = add_account(code_database, username, account_class=account_class, mfa=mfa)
        preauth = challenge_token(flow, account, f"{username}-desk")
        assert read(code_database, SESSIONS_OF, account.actor_id) == []
        challenges = read(code_database, CHALLENGES_OF, account.actor_id)
        assert [(bytes(row[0]), row[1], row[2]) for row in challenges] == [
            (digest(preauth), "challenge", False)
        ]
        assert all(
            preauth.encode() not in value for value in challenges[0] if isinstance(value, bytes)
        )
        done = flow.complete_mfa(
            preauth_token=preauth,
            method="totp",
            code=code_for(account, fresh_step(code_database)),
            request_id="l3c-2a",
        )
        assert done.phase is AuthenticationPhase.AUTHENTICATED
        assert done.session is not None and done.session_token is not None
        assert done.csrf_token and done.csrf_token != done.session_token
        assert (done.session.actor_id, done.session.mfa_assurance) == (
            str(account.actor_id),
            "totp",
        )
        sessions = read(code_database, SESSIONS_OF, account.actor_id)
        assert [(bytes(row[1]), row[2]) for row in sessions] == [
            (digest(done.session_token), "auth-mfa-challenge")
        ]
        assert read(code_database, PROOFS_OF, account.actor_id) == [("totp", account.enrollment_id)]
        assert [row[2] for row in read(code_database, CHALLENGES_OF, account.actor_id)] == [True]
        read_back = flow.inspect_session(session_token=done.session_token, request_id="l3c-2a")
        assert read_back.mfa_assurance == "totp"
        actor = resolver(request_with(f"__Host-prm_session={done.session_token}"))
        assert actor is not None and actor.actor_id == str(account.actor_id)


def test_an_account_without_a_sign_in_code_must_enroll_and_cannot_complete_a_challenge(
    code_database: CodeDatabase,
) -> None:
    """DL-056, UI-110: a Manager and a Staff account with MFA `required` and no sign-in code get
    `mfa_enrollment_required` and a stored `enrollment` challenge; its token cannot complete a
    sign-in code challenge, and no session is made."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    for username, account_class in (("l3c.new-manager", "manager"), ("l3c.new-staff", "staff")):
        account = add_account(
            code_database, username, account_class=account_class, sign_in_code=False
        )
        result = flow.login(
            username=username, password=PASSWORD, request_source="l3c-new", request_id="l3c-2a"
        )
        assert result.phase is AuthenticationPhase.MFA_ENROLLMENT_REQUIRED
        assert result.preauth_token is not None and result.session is None
        challenges = read(code_database, CHALLENGES_OF, account.actor_id)
        assert [(bytes(row[0]), row[1]) for row in challenges] == [
            (digest(result.preauth_token), "enrollment")
        ]
        # Review round 1: a sign-in code set up while the `enrollment` challenge is open still
        # does not complete it.
        with psycopg.connect(code_database.owner_url) as connection:
            secret, enrollment_id = add_sign_in_code(connection, account.actor_id)
            connection.commit()
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(
                preauth_token=result.preauth_token,
                method="totp",
                code=TotpService().generate_code(secret, at_time=fresh_step(code_database) * 30),
                request_id="l3c-2a",
            )
        assert read(code_database, SESSIONS_OF, account.actor_id) == []
        assert read(code_database, USED_STEPS_OF, enrollment_id) == []


def test_wrong_sign_in_codes_count_as_wrong_tries_and_a_right_code_during_a_wait_is_refused(
    code_database: CodeDatabase,
) -> None:
    """Q-2026-10-21-154 (a) with the owner's amended rule: each wrong sign-in code is a wrong try
    of kind `sign_in_code` for the account; the 3rd in a row starts the 5-minute wait, and the
    right code during it gets the same wait answer and no session."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.wrong-codes")
    preauth = challenge_token(flow, account, "l3c-wrong")
    step = fresh_step(code_database)
    for _ in range(2):
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(
                preauth_token=preauth,
                method="totp",
                code=wrong_code(account, step),
                request_id="l3c-2a",
            )
    with pytest.raises(AuthenticationRateLimited) as waiting:
        flow.complete_mfa(
            preauth_token=preauth, method="totp", code=wrong_code(account, step), request_id="w"
        )
    assert waiting.value.retry_after_seconds == 300
    with pytest.raises(AuthenticationRateLimited):
        flow.complete_mfa(
            preauth_token=preauth,
            method="totp",
            code=code_for(account, fresh_step(code_database)),
            request_id="l3c-2a",
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == [
        ("sign_in_code",),
        ("sign_in_code",),
        ("sign_in_code",),
    ]
    assert read(code_database, SESSIONS_OF, account.actor_id) == []


def test_the_right_sign_in_code_clears_the_count_of_wrong_tries(
    code_database: CodeDatabase,
) -> None:
    """DL-081: a wrong password and a wrong sign-in code are 2 wrong tries in a row; the right
    code clears them, so the next wrong password is the 1st again and gets the plain
    rejection."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.clears")
    with pytest.raises(AuthenticationRejected):
        flow.login(
            username=account.username, password=WRONG, request_source="l3c-clr", request_id="c"
        )
    preauth = challenge_token(flow, account, "l3c-clr")
    step = fresh_step(code_database)
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="totp", code=wrong_code(account, step), request_id="c"
        )
    done = flow.complete_mfa(
        preauth_token=preauth, method="totp", code=code_for(account, step), request_id="c"
    )
    assert done.phase is AuthenticationPhase.AUTHENTICATED
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(1,)]
    for _ in range(2):
        with pytest.raises(AuthenticationRejected):
            flow.login(
                username=account.username, password=WRONG, request_source="l3c-clr", request_id="c"
            )


def test_a_sign_in_code_is_used_once_and_only_the_previous_step_is_accepted(
    code_database: CodeDatabase,
) -> None:
    """TEST-128: the same code in a second sign-in of the same step is refused and counted; on an
    enrollment with no used step, codes of two steps ago and of the next step are refused and
    counted; a code of the previous step (one step of clock drift) is accepted once, after which
    the current step still works."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.once")
    first = challenge_token(flow, account, "l3c-once")
    step = fresh_step(code_database)
    assert (
        flow.complete_mfa(
            preauth_token=first, method="totp", code=code_for(account, step), request_id="o"
        ).phase
        is AuthenticationPhase.AUTHENTICATED
    )
    second = challenge_token(flow, account, "l3c-once")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=second, method="totp", code=code_for(account, step), request_id="o"
        )
    assert len(read(code_database, SESSIONS_OF, account.actor_id)) == 1
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("sign_in_code",)]

    # Review round 1: the window itself, on an enrollment that has used no step.
    window = add_account(code_database, "l3c.window")
    token = challenge_token(flow, window, "l3c-window")
    step = fresh_step(code_database)
    for refused in (code_for(window, step - 2), code_for(window, step + 1)):
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(preauth_token=token, method="totp", code=refused, request_id="w")
    assert read(code_database, USED_STEPS_OF, window.enrollment_id) == []
    assert read(code_database, TRIES_OF, username_key(window.username)) == [
        ("sign_in_code",),
        ("sign_in_code",),
    ]

    drift = add_account(code_database, "l3c.drift")
    earlier = challenge_token(flow, drift, "l3c-drift")
    later = challenge_token(flow, drift, "l3c-drift")
    step = fresh_step(code_database)
    flow.complete_mfa(
        preauth_token=earlier, method="totp", code=code_for(drift, step - 1), request_id="d"
    )
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=later, method="totp", code=code_for(drift, step - 1), request_id="d"
        )
    flow.complete_mfa(
        preauth_token=later, method="totp", code=code_for(drift, step), request_id="d"
    )
    assert len(read(code_database, SESSIONS_OF, drift.actor_id)) == 2
    assert read(code_database, USED_STEPS_OF, drift.enrollment_id) == [(step - 1,), (step,)]


def test_a_challenge_is_completed_once_and_not_after_5_minutes(
    code_database: CodeDatabase,
) -> None:
    """A completed challenge's token is refused even with a code of a later, unused step; a
    challenge made 6 minutes ago by the database clock, with the real digests of the account, is
    refused by the flow, and the database refuses to complete it."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.expiry")
    preauth = challenge_token(flow, account, "l3c-exp")
    step = fresh_step(code_database)
    flow.complete_mfa(
        preauth_token=preauth, method="totp", code=code_for(account, step - 1), request_id="e"
    )
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="totp", code=code_for(account, step), request_id="e"
        )
    assert len(read(code_database, SESSIONS_OF, account.actor_id)) == 1
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == [(step - 1,)]
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(preauth_token="t" * 129, method="totp", code="123456", request_id="e")

    old = add_account(code_database, "l3c.old-challenge")
    old_token = "o" * 43
    challenge_id = uuid.uuid4()
    verifier = read(code_database, CREDENTIAL_OF, old.actor_id)[0][0]
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
            "purpose, enrollment_id, password_verifier_digest, username_digest, source_digest, "
            "created_at, expires_at) SELECT %s, %s, %s, 'challenge', %s, %s, %s, %s, moment.at, "
            "moment.at + interval '5 minutes' "
            "FROM (SELECT statement_timestamp() - interval '6 minutes' AS at) AS moment",
            (
                challenge_id,
                old.actor_id,
                digest(old_token),
                old.enrollment_id,
                verifier_digest(str(verifier)),
                username_key(old.username),
                sign_in_source_digest("l3c-old"),
            ),
        )
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=old_token,
            method="totp",
            code=code_for(old, fresh_step(code_database)),
            request_id="e",
        )
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="expired"):
            connection.execute(
                "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
                "WHERE challenge_id = %s",
                (challenge_id,),
            )
    assert read(code_database, SESSIONS_OF, old.actor_id) == []
    assert read(code_database, USED_STEPS_OF, old.enrollment_id) == []


def change_for(case: str, account: Account) -> tuple[str, tuple[object, ...]]:
    """One change between the password check and the sign-in code, written as the table
    owner."""
    replacement = PasswordHashService().hash_password("an entirely different passphrase")
    if case == "password":
        return (
            "UPDATE app.password_credentials SET verifier_encoding = %s, "
            "changed_by_actor_id = %s, provenance = 'l3c-2a-reset-test' WHERE actor_id = %s",
            (replacement.verifier_encoding, account.actor_id, account.actor_id),
        )
    if case == "sign_in_code":
        return (
            "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
            "disabled_by_actor_id = %s, disablement_provenance = 'l3c-2a-reset-test' "
            "WHERE actor_id = %s",
            (account.actor_id, account.actor_id),
        )
    return (
        "UPDATE app.user_accounts SET lifecycle_state = 'disabled' WHERE actor_id = %s",
        (account.actor_id,),
    )


def assert_nothing_written(database: CodeDatabase, account: Account) -> None:
    assert read(database, SESSIONS_OF, account.actor_id) == []
    assert read(database, PROOFS_OF, account.actor_id) == []
    assert read(database, USED_STEPS_OF, account.enrollment_id) == []
    assert [row[2] for row in read(database, CHALLENGES_OF, account.actor_id)] == [False]
    assert read(database, CLEARS_OF, username_key(account.username)) == [(0,)]


def test_a_password_reset_a_sign_in_code_reset_or_a_disabled_account_refuses_the_code(
    code_database: CodeDatabase,
) -> None:
    """A change between the password check and the sign-in code refuses the right code with the
    generic rejection and writes nothing (no session, proof or used step, the challenge open, the
    count not cleared): a new password (the L3a-1 guard), the sign-in code turned off, and the
    account disabled."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    for case in ("password", "sign_in_code", "account"):
        account = add_account(code_database, f"l3c.reset-{case}")
        preauth = challenge_token(flow, account, f"l3c-reset-{case}")
        statement, parameters = change_for(case, account)
        with psycopg.connect(code_database.owner_url) as connection:
            connection.execute(statement, parameters)
            connection.commit()
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(
                preauth_token=preauth,
                method="totp",
                code=code_for(account, fresh_step(code_database)),
                request_id="r",
            )
        assert_nothing_written(code_database, account)


@pytest.mark.parametrize("case", ["wait", "password", "sign_in_code", "account"])
def test_a_change_after_the_code_check_refuses_and_rolls_the_session_back(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Review round 1 (reviewers' set-up): a change committed after the challenge was read and its
    wait checked, before the session transaction, is met inside that transaction: a wait that 3
    parallel wrong codes started (the clear answers it, 429), the sign-in code turned off (the
    enrollment lock), a new password (the verifier comparison) and the account disabled (the live
    session read back); nothing is written and the count is not cleared."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, f"l3c.window-{case}")
    preauth = challenge_token(flow, account, f"l3c-window-{case}")
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[0]
    checked = flow._sign_in_waits.challenge_wait_seconds

    def checked_then_changed(username_digest: bytes, source_digest: bytes) -> int | None:
        waiting = checked(username_digest, source_digest)
        if case == "wait":
            with psycopg.connect(code_database.runtime_url) as connection:
                for _ in range(3):
                    connection.execute(
                        "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')",
                        (bytes(stored[4]), bytes(stored[5])),
                    )
                    connection.commit()
        else:
            statement, parameters = change_for(case, account)
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(statement, parameters)
                connection.commit()
        return waiting

    monkeypatch.setattr(flow._sign_in_waits, "challenge_wait_seconds", checked_then_changed)
    refusal: type[Exception] = (
        AuthenticationRateLimited if case == "wait" else AuthenticationRejected
    )
    with pytest.raises(refusal):
        flow.complete_mfa(
            preauth_token=preauth,
            method="totp",
            code=code_for(account, fresh_step(code_database)),
            request_id="x",
        )
    assert_nothing_written(code_database, account)


def test_two_parallel_uses_of_one_code_make_one_session(code_database: CodeDatabase) -> None:
    """Review round 1 (reviewers' set-up): two challenges of one account given the same right
    code at the same moment, while the table owner holds the enrollment row, wait for each other
    (the wrong-try clear's username lock queues the second behind the first, which waits for the
    enrollment row); exactly one makes a session and one used step, the other is refused."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.parallel")
    tokens = [challenge_token(flow, account, "l3c-parallel") for _ in range(2)]
    step = fresh_step(code_database)
    outcomes: list[str] = []

    def complete(token: str) -> None:
        try:
            flow.complete_mfa(
                preauth_token=token, method="totp", code=code_for(account, step), request_id="p"
            )
            outcomes.append("authenticated")
        except AuthenticationRejected:
            outcomes.append("rejected")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.totp_mfa_enrollments WHERE enrollment_id = %s FOR UPDATE",
            (account.enrollment_id,),
        )
        threads = [threading.Thread(target=complete, args=(token,)) for token in tokens]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 2:
            time.sleep(0.05)
        waited = lock_waits(code_database)
        holder.commit()
    assert waited >= 2
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(outcomes) == ["authenticated", "rejected"]
    assert len(read(code_database, SESSIONS_OF, account.actor_id)) == 1
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == [(step,)]


def test_a_used_step_waits_for_a_parallel_step_and_is_never_in_the_future(
    code_database: CodeDatabase,
) -> None:
    """Review round 1: the step guard locks the enrollment, so a step written while a later one
    is not yet committed waits and is then refused; a step after the current step of the
    database clock is refused."""
    account = add_account(code_database, "l3c.step-lock")
    step = fresh_step(code_database)
    errors_seen: list[str] = []

    def earlier_step() -> None:
        with psycopg.connect(code_database.owner_url) as connection:
            try:
                connection.execute(
                    "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
                    (account.enrollment_id, step - 1),
                )
            except errors.IntegrityConstraintViolation as error:
                errors_seen.append(str(error))

    with psycopg.connect(code_database.owner_url) as first:
        first.execute(
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (account.enrollment_id, step),
        )
        waiting = threading.Thread(target=earlier_step)
        waiting.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and lock_waits(code_database) < 1:
            time.sleep(0.05)
        assert lock_waits(code_database) >= 1 and waiting.is_alive()
        first.commit()
    waiting.join(timeout=15)
    assert len(errors_seen) == 1 and "after the last used step" in errors_seen[0]
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="never after the current"):
            connection.execute(
                "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
                (account.enrollment_id, step + 5),
            )
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == [(step,)]


def test_a_challenge_completes_only_with_the_sign_in_code_it_was_made_for(
    code_database: CodeDatabase,
) -> None:
    """Review round 2: a challenge keeps the sign-in code it was made for; after that code is
    turned off and a new one set up, the new code's right code does not complete it, and
    nothing is written."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.new-code")
    preauth = challenge_token(flow, account, "l3c-new-code")
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        new_secret, new_enrollment = add_sign_in_code(connection, account.actor_id)
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth,
            method="totp",
            code=TotpService().generate_code(new_secret, at_time=fresh_step(code_database) * 30),
            request_id="n",
        )
    assert_nothing_written(code_database, account)
    assert read(code_database, USED_STEPS_OF, new_enrollment) == []
    assert read(
        code_database,
        "SELECT enrollment_id FROM app.sign_in_mfa_challenges WHERE token_verifier = %s",
        digest(preauth),
    ) == [(account.enrollment_id,)]


def test_the_proof_guard_needs_a_live_later_session_and_a_step_used_since_the_challenge(
    code_database: CodeDatabase,
) -> None:
    """Review round 2 (reviewer's set-up), as the table owner, each condition alone: a proof of a
    completed challenge is refused for a session made before the challenge, for a later session
    while no step of the code was used since the challenge, and for a revoked session; a live
    session made after the challenge, with a step used since, gets the proof and is read with
    `mfa_assurance` `totp`."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.proof-guard")
    first = challenge_token(flow, account, "l3c-proof")
    step = fresh_step(code_database)
    done = flow.complete_mfa(
        preauth_token=first, method="totp", code=code_for(account, step - 1), request_id="p"
    )
    assert done.session_token is not None
    second = challenge_token(flow, account, "l3c-proof")
    challenge_id = read(code_database, CHALLENGE_ID_OF, digest(second))[0][0]
    earlier_session = read(
        code_database,
        "SELECT session_id FROM app.browser_sessions WHERE token_verifier = %s",
        digest(done.session_token),
    )[0][0]
    later_session, live_session = uuid.uuid4(), uuid.uuid4()
    live_token = "l" * 43

    def refused(session_id: uuid.UUID, message: str) -> None:
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match=message):
                connection.execute(ADD_PROOF, (session_id, challenge_id, account.enrollment_id))

    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
            "WHERE challenge_id = %s",
            (challenge_id,),
        )
        connection.commit()
    refused(earlier_session, "completed challenge of the session account")
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            ADD_SESSION, (later_session, account.actor_id, digest("m" * 43), PROVENANCE)
        )
        connection.commit()
    refused(later_session, "names the challenge sign-in code")
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (account.enrollment_id, step),
        )
        connection.execute(
            "UPDATE app.browser_sessions SET revoked_by_actor_id = %s, "
            "revocation_reason = 'logout', revocation_provenance = 'l3c-2a-test' "
            "WHERE session_id = %s",
            (account.actor_id, later_session),
        )
        connection.commit()
    refused(later_session, "completed challenge of the session account")
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            ADD_SESSION, (live_session, account.actor_id, digest(live_token), PROVENANCE)
        )
        connection.execute(ADD_PROOF, (live_session, challenge_id, account.enrollment_id))
        connection.commit()
    assert flow.inspect_session(session_token=live_token, request_id="p").mfa_assurance == "totp"


def test_a_session_ends_when_its_sign_in_code_is_turned_off(code_database: CodeDatabase) -> None:
    """Review round 2 (defence in depth): a `totp` proof counts only while its sign-in code is
    active, so a session made with the code is no longer read and gives no actor once the code
    is turned off, even when nothing revoked the session."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    account = add_account(code_database, "l3c.code-off")
    preauth = challenge_token(flow, account, "l3c-code-off")
    done = flow.complete_mfa(
        preauth_token=preauth,
        method="totp",
        code=code_for(account, fresh_step(code_database)),
        request_id="o",
    )
    assert done.session_token is not None
    cookie = f"__Host-prm_session={done.session_token}"
    assert resolver(request_with(cookie)) is not None
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=done.session_token, request_id="o")
    assert resolver(request_with(cookie)) is None
    assert read(
        code_database,
        "SELECT revoked_at FROM app.browser_sessions WHERE actor_id = %s",
        account.actor_id,
    ) == [(None,)]


def test_a_session_of_an_account_with_a_sign_in_code_is_live_only_with_its_proof(
    code_database: CodeDatabase,
) -> None:
    """The L3a-1 binding: a session row of a Staff account with MFA `optional` and an active
    sign-in code, written without an MFA proof, is not read and gives no actor and no
    activity; the same row of a Staff account without a sign-in code is live."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    for username, sign_in_code in (("l3c.unproven", True), ("l3c.no-code", False)):
        account = add_account(
            code_database,
            username,
            account_class="staff",
            mfa="optional",
            sign_in_code=sign_in_code,
        )
        token = f"{username:x<43}"[:43]
        with psycopg.connect(code_database.owner_url) as connection:
            connection.execute(
                "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
                "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)",
                (uuid.uuid4(), account.actor_id, digest(token), PROVENANCE),
            )
            connection.commit()
        before = read(
            code_database,
            "SELECT last_activity_at FROM app.browser_sessions WHERE actor_id = %s",
            account.actor_id,
        )
        actor = resolver(request_with(f"__Host-prm_session={token}"))
        after = read(
            code_database,
            "SELECT last_activity_at FROM app.browser_sessions WHERE actor_id = %s",
            account.actor_id,
        )
        if sign_in_code:
            assert actor is None and before == after
            with pytest.raises(AuthenticationRejected):
                flow.inspect_session(session_token=token, request_id="u")
        else:
            assert actor is not None and before != after
            assert flow.inspect_session(session_token=token, request_id="u").mfa_assurance == (
                "none"
            )


def test_a_sign_in_code_needs_the_protection_key_that_protected_it(
    code_database: CodeDatabase,
) -> None:
    """Without the protection key, or for a recovery code (login sub-slice L3c-2c), the challenge
    answers unavailable; with another key the code cannot be opened and the challenge answers
    unavailable without detail; no wrong try is counted and no session is made."""
    account = add_account(code_database, "l3c.other-key")
    preauth = challenge_token(
        PostgresAuthenticationFlow(code_database.runtime_url), account, "l3c-key"
    )
    code = code_for(account, fresh_step(code_database))
    for flow, method in (
        (PostgresAuthenticationFlow(code_database.runtime_url), "totp"),
        (
            PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY),
            "recovery_code",
        ),
        (
            PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=bytes(32)),
            "totp",
        ),
    ):
        with pytest.raises(AuthenticationUnavailable):
            flow.complete_mfa(preauth_token=preauth, method=method, code=code, request_id="k")
    assert read(code_database, TRIES_OF, username_key(account.username)) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == []


def test_the_sign_in_code_routes_answer_401_and_429_and_set_the_session_cookie(
    code_database: CodeDatabase,
) -> None:
    """API-096 over HTTP: the password sets the pre-authentication cookie; a wrong code answers
    401, the 3rd wrong try 429 with `Retry-After`; another account's right code sets the
    session cookie and removes the pre-authentication cookie."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    app = create_app(
        Settings(database_url=SecretStr(code_database.runtime_url), allowed_browser_origin=ORIGIN),
        authentication_flow=flow,
    )
    for username, codes in (("l3c.http-wrong", 3), ("l3c.http-right", 0)):
        account = add_account(code_database, username)
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": PASSWORD},
                headers={"Origin": ORIGIN, "X-Request-ID": "l3c-2a-http"},
            )
            assert login.status_code == 200
            assert login.json()["data"] == {"phase": "mfa_required", "session": None}
            headers = {
                "Origin": ORIGIN,
                "X-CSRF-Token": client.cookies["__Host-prm_csrf"],
                "X-Request-ID": "l3c-2a-http",
            }
            step = fresh_step(code_database)
            answers = [
                client.post(
                    "/api/v1/auth/mfa/challenge",
                    json={"method": "totp", "code": wrong_code(account, step)},
                    headers=headers,
                )
                for _ in range(codes)
            ]
            expected = [(401, None), (401, None), (429, "300")] if codes else []
            assert [
                (answer.status_code, answer.headers.get("Retry-After")) for answer in answers
            ] == expected
            if not codes:
                done = client.post(
                    "/api/v1/auth/mfa/challenge",
                    json={"method": "totp", "code": code_for(account, step)},
                    headers=headers,
                )
                assert done.status_code == 200
                assert done.json()["data"]["session"]["mfa_assurance"] == "totp"
                assert done.headers["Cache-Control"] == "no-store"
                assert "__Host-prm_session" in client.cookies
                assert "__Host-prm_preauth" not in client.cookies


def test_the_challenge_steps_and_proofs_are_guarded_in_the_database(
    code_database: CodeDatabase,
) -> None:
    """DB-AUTH-003, DB-AUTH-004: a challenge changes only by one completion; a used step and a
    proof never change; a step not after the last used one and a step of a disabled sign-in code
    are refused; a proof with another account's completed challenge, with the account's own open
    challenge, or naming another account's sign-in code is refused; a challenge naming another
    account's sign-in code or its own code once turned off is refused; the runtime role has only
    the column privileges it needs and cannot delete or truncate."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c.guards")
    other = add_account(code_database, "l3c.guards-other")
    preauth = challenge_token(flow, account, "l3c-guards")
    step = fresh_step(code_database)
    done = flow.complete_mfa(
        preauth_token=preauth, method="totp", code=code_for(account, step), request_id="g"
    )
    assert done.session_token is not None
    other_first = challenge_token(flow, other, "l3c-guards")
    flow.complete_mfa(
        preauth_token=other_first, method="totp", code=code_for(other, step), request_id="g"
    )
    own_open = challenge_token(flow, account, "l3c-guards")
    add_proof = (
        "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
        "enrollment_id) SELECT browser.session_id, challenge.challenge_id, 'totp', %s "
        "FROM app.browser_sessions AS browser, app.sign_in_mfa_challenges AS challenge "
        "WHERE browser.token_verifier = %s AND challenge.token_verifier = %s"
    )
    statements = (
        (
            "UPDATE app.sign_in_mfa_challenges SET purpose = 'enrollment' WHERE actor_id = %s",
            (account.actor_id,),
            "immutable",
        ),
        (
            "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
            "WHERE token_verifier = %s",
            (digest(preauth),),
            "completed once",
        ),
        (
            "UPDATE app.sign_in_mfa_challenges SET completed_at = NULL WHERE token_verifier = %s",
            (digest(own_open),),
            "only by its completion",
        ),
        (
            "DELETE FROM app.sign_in_mfa_challenges WHERE actor_id = %s",
            (account.actor_id,),
            "append-only",
        ),
        (
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (account.enrollment_id, step),
            "after the last used step",
        ),
        (
            "UPDATE app.totp_used_steps SET time_step = time_step + 1 WHERE enrollment_id = %s",
            (account.enrollment_id,),
            "append-only",
        ),
        (
            "DELETE FROM app.totp_used_steps WHERE enrollment_id = %s",
            (account.enrollment_id,),
            "append-only",
        ),
        (
            "UPDATE app.browser_session_mfa_proofs SET method = 'recovery_code' "
            "WHERE enrollment_id = %s",
            (account.enrollment_id,),
            "append-only",
        ),
        (
            "DELETE FROM app.browser_session_mfa_proofs WHERE enrollment_id = %s",
            (account.enrollment_id,),
            "append-only",
        ),
        (
            add_proof,
            (other.enrollment_id, digest(done.session_token), digest(other_first)),
            "completed challenge of the session account",
        ),
        (
            add_proof,
            (account.enrollment_id, digest(done.session_token), digest(own_open)),
            "completed challenge of the session account",
        ),
        (
            add_proof,
            (other.enrollment_id, digest(done.session_token), digest(preauth)),
            "names the challenge sign-in code",
        ),
    )
    for statement, parameters, message in statements:
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match=message):
                connection.execute(statement, parameters)
    for table in ("sign_in_mfa_challenges", "totp_used_steps", "browser_session_mfa_proofs"):
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
                connection.execute(f"TRUNCATE app.{table} CASCADE")
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
            "disabled_by_actor_id = %s, disablement_provenance = 'l3c-2a-guard-test' "
            "WHERE enrollment_id = %s",
            (other.actor_id, other.enrollment_id),
        )
        connection.commit()
        with pytest.raises(errors.IntegrityConstraintViolation, match="active enrollment"):
            connection.execute(
                "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
                (other.enrollment_id, step + 10),
            )
    # Review round 2: a challenge names an active sign-in code of its own account, not another
    # account's active code and not its own code once turned off.
    third = add_account(code_database, "l3c.guards-third")
    for actor_id, enrollment_id in (
        (account.actor_id, third.enrollment_id),
        (other.actor_id, other.enrollment_id),
    ):
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match="active sign-in code"):
                connection.execute(
                    ADD_CHALLENGE,
                    (
                        uuid.uuid4(),
                        actor_id,
                        digest(f"guard-{enrollment_id}"),
                        enrollment_id,
                        bytes(32),
                        bytes(32),
                        bytes(32),
                    ),
                )
    with psycopg.connect(code_database.owner_url) as connection:
        privileges = connection.execute(
            "SELECT has_column_privilege('prm_runtime', 'app.sign_in_mfa_challenges', "
            "'completed_at', 'UPDATE'), has_column_privilege('prm_runtime', "
            "'app.sign_in_mfa_challenges', 'purpose', 'UPDATE'), has_column_privilege("
            "'prm_runtime', 'app.sign_in_mfa_challenges', 'created_at', 'INSERT'), "
            "has_table_privilege('prm_runtime', 'app.sign_in_mfa_challenges', 'DELETE'), "
            "has_column_privilege('prm_runtime', 'app.totp_used_steps', 'time_step', 'UPDATE'), "
            "has_table_privilege('prm_runtime', 'app.totp_used_steps', 'TRUNCATE'), "
            "has_column_privilege('prm_runtime', 'app.browser_session_mfa_proofs', 'method', "
            "'UPDATE'), has_table_privilege('prm_runtime', 'app.browser_session_mfa_proofs', "
            "'DELETE'), has_column_privilege('prm_runtime', 'app.sign_in_mfa_challenges', "
            "'completed_at', 'INSERT'), has_column_privilege('prm_runtime', "
            "'app.sign_in_mfa_challenges', 'expires_at', 'INSERT'), has_column_privilege("
            "'prm_runtime', 'app.totp_used_steps', 'used_at', 'INSERT'), has_column_privilege("
            "'prm_runtime', 'app.browser_session_mfa_proofs', 'proven_at', 'INSERT'), "
            "has_column_privilege('prm_runtime', 'app.sign_in_mfa_challenges', "
            "'enrollment_id', 'INSERT')"
        ).fetchone()
    assert privileges == (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    )


def test_the_sign_in_code_migration_follows_l3c_1_and_is_forward_only() -> None:
    """The migration chain: `20270130_187` follows `20270129_186` and has no downgrade."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
