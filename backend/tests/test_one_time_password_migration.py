"""Login sub-slice L4a: the Owner's reset with a one-time password and the forced change.

DL-058, DL-080 item 10, DL-081, API-099, SEC-011, SEC-014, SEC-075, DB-AUTH-002, DB-AUTH-005,
TEST-130, TEST-131 (migration `20270204_192`; owner answers (a) to Q-2026-10-21-153,
Q-2026-10-21-165 and Q-2026-10-23-180; technical points Q-2026-10-24-185). One throwaway
database at head with the Property and the Owner, shared by this module; each test uses its own
accounts. The functions run as the runtime role; set-up rows are written as the table owner.
"""

from __future__ import annotations

import hashlib
import json
import secrets
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
from psycopg import errors

from property_rental.password_security import PasswordCredentialMaterial, PasswordHashService
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property
from test_settings_access_migration import add_sign_in_code

REVISION = "20270204_192"
PREVIOUS = "20270203_191"
PROVENANCE = "login-slice-l4a-test"
HASHER = PasswordHashService()
ISSUE = "SELECT * FROM app.issue_one_time_password(%s, %s, %s, %s, %s, %s, %s::jsonb, %s)"
CHANGE = "SELECT * FROM app.change_one_time_password(%s, %s, %s, %s::jsonb, %s)"
RECOVER = (
    "SELECT * FROM app.perform_account_recovery("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NULL)"
)
ADD_CREDENTIAL = (
    "INSERT INTO app.password_credentials(actor_id,verifier_encoding,algorithm,"
    "work_factor_metadata,provenance) VALUES (%s,%s,%s,%s::jsonb,'initial-credential')"
)
ADD_SESSION = (
    "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
    "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)"
)
ADD_RECOVERY_SET = (
    "INSERT INTO app.recovery_code_sets (set_id, actor_id, created_by_actor_id, provenance) "
    "VALUES (%s, %s, %s, %s)"
)
ADD_CHALLENGE = (
    "INSERT INTO app.password_change_challenges (challenge_id, actor_id, one_time_password_id, "
    "token_verifier, checked_verifier_digest, username_digest, source_digest) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)
CREDENTIAL_OF = (
    "SELECT verifier_encoding, one_time_password_id FROM app.password_credentials "
    "WHERE actor_id = %s"
)
LOCK_WAITS = (
    "SELECT count(DISTINCT lock.pid) FROM pg_catalog.pg_locks AS lock "
    "JOIN pg_catalog.pg_stat_activity AS activity ON activity.pid = lock.pid "
    "WHERE NOT lock.granted AND activity.datname = current_database()"
)


@dataclass(frozen=True)
class OneTimeDatabase:
    owner_url: str
    runtime_url: str
    owner: uuid.UUID


@pytest.fixture(scope="module")
def one_time_database(migrated_database_url: str) -> Iterator[OneTimeDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_one_time_password") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            the_property(setup)
            owner = add_account(setup, "owner")
            setup.commit()
        yield OneTimeDatabase(temporary, runtime_url, owner)


def material(password: str) -> tuple[PasswordCredentialMaterial, str]:
    credential = HASHER.hash_password(password)
    return credential, json.dumps(dict(credential.work_factor_metadata))


def digest_of(verifier_encoding: str) -> bytes:
    return hashlib.sha256(verifier_encoding.encode("utf-8")).digest()


@dataclass(frozen=True)
class Target:
    actor_id: uuid.UUID
    session_id: uuid.UUID
    set_id: uuid.UUID


def add_target(
    database: OneTimeDatabase,
    account_class: str = "manager",
    *,
    settings_access: bool = False,
) -> Target:
    """An account with a password, an active sign-in code, a live session, a live recovery-code
    set and, if asked, Settings access."""
    credential, metadata = material("an old password of the target")
    session_id = uuid.uuid4()
    set_id = uuid.uuid4()
    with psycopg.connect(database.owner_url) as connection:
        actor_id = add_account(connection, account_class)
        connection.execute(
            ADD_CREDENTIAL,
            (actor_id, credential.verifier_encoding, credential.algorithm, metadata),
        )
        add_sign_in_code(connection, actor_id)
        connection.execute(ADD_SESSION, (session_id, actor_id, secrets.token_bytes(32), PROVENANCE))
        connection.execute(ADD_RECOVERY_SET, (set_id, actor_id, actor_id, PROVENANCE))
        connection.commit()
        if settings_access:
            connection.execute(
                "SELECT app.give_settings_access(%s, %s, 'test grant')", (database.owner, actor_id)
            )
            connection.commit()
    return Target(actor_id, session_id, set_id)


def issue(
    database: OneTimeDatabase,
    actor_id: uuid.UUID,
    *,
    owner: uuid.UUID | None = None,
    reason: str | None = "Forgot the password",
    reset_mfa: bool = False,
    password: str = "one-time-password-0001",
    correlation: uuid.UUID | None = None,
) -> tuple[Any, ...]:
    credential, metadata = material(password)
    with psycopg.connect(database.runtime_url) as connection:
        row = connection.execute(
            ISSUE,
            (
                owner or database.owner,
                actor_id,
                correlation or uuid.uuid4(),
                reason,
                credential.verifier_encoding,
                credential.algorithm,
                metadata,
                reset_mfa,
            ),
        ).fetchone()
        connection.commit()
    assert row is not None
    return tuple(row)


def read(database: OneTimeDatabase, query: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(database.owner_url) as connection:
        return [tuple(row) for row in connection.execute(query, parameters).fetchall()]


def refused_with(state: type[Exception], call: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(state):
        call(*args, **kwargs)


def add_challenge(
    database: OneTimeDatabase, actor_id: uuid.UUID, *, checked: bytes | None = None
) -> bytes:
    """The pre-authentication state a sign-in with the one-time password writes (as the runtime
    role); answers the token digest."""
    verifier, one_time_id = read(database, CREDENTIAL_OF, actor_id)[0]
    token = secrets.token_bytes(32)
    with psycopg.connect(database.runtime_url) as connection:
        connection.execute(
            ADD_CHALLENGE,
            (
                uuid.uuid4(),
                actor_id,
                one_time_id,
                token,
                checked or digest_of(str(verifier)),
                secrets.token_bytes(32),
                secrets.token_bytes(32),
            ),
        )
        connection.commit()
    return token


def change(database: OneTimeDatabase, token: bytes, password: str) -> tuple[Any, ...]:
    credential, metadata = material(password)
    with psycopg.connect(database.runtime_url) as connection:
        row = connection.execute(
            CHANGE,
            (token, credential.verifier_encoding, credential.algorithm, metadata, uuid.uuid4()),
        ).fetchone()
        connection.commit()
    assert row is not None
    return tuple(row)


def age_one_time_password(database: OneTimeDatabase, actor_id: uuid.UUID, by: str) -> None:
    """Moves the account's one-time password back by `by`, triggers off for that update."""
    with psycopg.connect(database.owner_url) as connection:
        connection.execute("ALTER TABLE app.one_time_passwords DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.one_time_passwords SET issued_at = issued_at - %s::interval, "
            "expires_at = expires_at - %s::interval WHERE actor_id = %s",
            (by, by, actor_id),
        )
        connection.execute("ALTER TABLE app.one_time_passwords ENABLE TRIGGER USER")
        connection.commit()


def test_the_migration_follows_l3d_1_is_forward_only_and_opens_only_the_functions(
    one_time_database: OneTimeDatabase,
) -> None:
    """The chain and the runtime role's privileges: SELECT on the one-time passwords, SELECT and
    INSERT on the change challenges, nothing on the changes, EXECUTE on the two functions and
    SELECT on the credential's new column (L4b run 1); no UPDATE or DELETE anywhere."""
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    privileges = read(
        one_time_database,
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = 'prm_runtime' AND table_schema = 'app' AND table_name IN "
        "('one_time_passwords', 'password_change_challenges', 'password_changes') "
        "ORDER BY 1, 2",
    )
    assert privileges == [
        ("one_time_passwords", "SELECT"),
        ("password_change_challenges", "INSERT"),
        ("password_change_challenges", "SELECT"),
    ]
    for function in (
        "app.issue_one_time_password(uuid,uuid,uuid,text,text,text,jsonb,boolean)",
        "app.change_one_time_password(bytea,text,text,jsonb,uuid)",
    ):
        assert read(
            one_time_database,
            "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('public', %s, 'EXECUTE'), prosecdef "
            "FROM pg_proc WHERE oid = %s::regprocedure",
            function,
            function,
            function,
        ) == [(True, False, True)]
    # The sign-in reads the new column of the credential, and only reads it.
    assert read(
        one_time_database,
        "SELECT privilege_type FROM information_schema.column_privileges "
        "WHERE grantee = 'prm_runtime' AND table_schema = 'app' "
        "AND table_name = 'password_credentials' AND column_name = 'one_time_password_id'",
    ) == [("SELECT",)]


def test_the_owner_resets_a_manager_with_mfa_and_everything_ends_in_one_step(
    one_time_database: OneTimeDatabase,
) -> None:
    """TEST-130, TEST-131, owner answers (a) to Q-2026-10-21-153, Q-2026-10-21-165 and
    Q-2026-10-23-180: the reset with "also reset MFA" replaces the password with the one-time
    password's verifier and marks it as one to change, ends the sign-in code, the live recovery
    codes, the Settings access (one recorded removal, reason "sign-in code reset") and every live
    session (reason `password_reset`); the one-time password ends 24 hours after its issue on the
    database clock; the recovery audit and the administration history each get one row."""
    target = add_target(one_time_database, settings_access=True)
    correlation = uuid.uuid4()
    one_time_id, expires_at, code_reset, codes_ended, settings_ended, sessions = issue(
        one_time_database, target.actor_id, reset_mfa=True, correlation=correlation
    )
    assert (code_reset, codes_ended, settings_ended, sessions) == (True, True, True, 1)
    verifier, pending = read(one_time_database, CREDENTIAL_OF, target.actor_id)[0]
    assert pending == one_time_id
    assert HASHER.verify_password("one-time-password-0001", str(verifier)).is_valid
    assert read(
        one_time_database,
        "SELECT issued_by_actor_id, expires_at - issued_at, expires_at, reason, correlation_id "
        "FROM app.one_time_passwords WHERE one_time_password_id = %s",
        one_time_id,
    ) == [
        (
            one_time_database.owner,
            read(one_time_database, "SELECT interval '24 hours'")[0][0],
            expires_at,
            "Forgot the password",
            correlation,
        )
    ]
    assert read(
        one_time_database,
        "SELECT enrollment_state FROM app.totp_mfa_enrollments WHERE actor_id = %s",
        target.actor_id,
    ) == [("disabled",)]
    assert read(
        one_time_database,
        "SELECT invalidated_at IS NOT NULL FROM app.recovery_code_sets WHERE set_id = %s",
        target.set_id,
    ) == [(True,)]
    assert read(
        one_time_database,
        "SELECT removal.reason FROM app.user_capability_grant_removals AS removal "
        "JOIN app.user_capability_grants AS given USING (grant_id) WHERE given.actor_id = %s",
        target.actor_id,
    ) == [("sign-in code reset",)]
    assert read(
        one_time_database,
        "SELECT revocation_reason FROM app.browser_sessions WHERE session_id = %s",
        target.session_id,
    ) == [("password_reset",)]
    assert read(
        one_time_database,
        "SELECT actor_id, recovery_mode, outcome, password_changed, mfa_disabled, "
        "sessions_revoked FROM app.account_recovery_audit_events WHERE correlation_id = %s",
        correlation,
    ) == [(one_time_database.owner, "administrative", "completed", True, True, 1)]
    history = read(
        one_time_database,
        "SELECT action, reason, resulting_state FROM app.audit_events WHERE correlation_id = %s",
        correlation,
    )
    assert [(row[0], row[1]) for row in history] == [
        ("identity.account.one_time_password_given", "Forgot the password")
    ]
    # The administration history never holds the password or its verifier.
    assert "verifier" not in json.dumps(history[0][2])


def test_a_reset_without_mfa_keeps_the_code_the_codes_and_settings_access(
    one_time_database: OneTimeDatabase,
) -> None:
    """Without "also reset MFA" only the password and the sessions change (Q-2026-10-21-165:
    the Settings access is kept); a Staff account is reset the same way."""
    target = add_target(one_time_database, "staff", settings_access=True)
    _, _, code_reset, codes_ended, settings_ended, sessions = issue(
        one_time_database, target.actor_id
    )
    assert (code_reset, codes_ended, settings_ended, sessions) == (False, False, False, 1)
    assert read(
        one_time_database,
        "SELECT enrollment_state FROM app.totp_mfa_enrollments WHERE actor_id = %s",
        target.actor_id,
    ) == [("active",)]
    assert read(
        one_time_database,
        "SELECT invalidated_at IS NULL FROM app.recovery_code_sets WHERE set_id = %s",
        target.set_id,
    ) == [(True,)]
    assert read(
        one_time_database,
        "SELECT count(*) FROM app.user_capability_grant_removals AS removal "
        "JOIN app.user_capability_grants AS given USING (grant_id) WHERE given.actor_id = %s",
        target.actor_id,
    ) == [(0,)]


def test_a_new_account_gets_its_first_password_as_a_one_time_password(
    one_time_database: OneTimeDatabase,
) -> None:
    """Q-2026-10-21-153 (a): an account without a password gets its first one the same way."""
    with psycopg.connect(one_time_database.owner_url) as connection:
        actor_id = add_account(connection, "staff")
        connection.commit()
    one_time_id = issue(one_time_database, actor_id)[0]
    assert read(one_time_database, CREDENTIAL_OF, actor_id)[0][1] == one_time_id


def test_only_the_owner_resets_and_only_an_active_manager_or_staff_account(
    one_time_database: OneTimeDatabase,
) -> None:
    """SEC-075: a Manager cannot reset anyone; the Owner cannot reset itself or another Owner
    account; a disabled or unknown account, a missing or untidy reason, a missing
    verifier and an isolation level above READ COMMITTED are refused; nothing is written."""
    target = add_target(one_time_database)
    manager = add_target(one_time_database)
    with psycopg.connect(one_time_database.owner_url) as connection:
        disabled = add_account(connection, "staff", lifecycle="disabled")
        connection.commit()
    refused_with(
        errors.InsufficientPrivilege,
        issue,
        one_time_database,
        target.actor_id,
        owner=manager.actor_id,
    )
    refused_with(errors.InvalidParameterValue, issue, one_time_database, one_time_database.owner)
    refused_with(errors.ObjectNotInPrerequisiteState, issue, one_time_database, disabled)
    refused_with(errors.NoDataFound, issue, one_time_database, uuid.uuid4())
    for reason in (None, "", " padded ", "x" * 501):
        refused_with(
            errors.InvalidParameterValue, issue, one_time_database, target.actor_id, reason=reason
        )
    credential, metadata = material("one-time-password-0002")
    with psycopg.connect(one_time_database.runtime_url) as connection:
        with pytest.raises(errors.InvalidParameterValue):
            connection.execute(
                ISSUE,
                (
                    one_time_database.owner,
                    target.actor_id,
                    uuid.uuid4(),
                    "reason",
                    None,
                    credential.algorithm,
                    metadata,
                    False,
                ),
            )
    with psycopg.connect(one_time_database.runtime_url) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(errors.ObjectNotInPrerequisiteState):
            connection.execute(
                ISSUE,
                (
                    one_time_database.owner,
                    target.actor_id,
                    uuid.uuid4(),
                    "reason",
                    credential.verifier_encoding,
                    credential.algorithm,
                    metadata,
                    False,
                ),
            )
    assert read(
        one_time_database,
        "SELECT count(*) FROM app.one_time_passwords WHERE actor_id IN (%s, %s, %s)",
        target.actor_id,
        one_time_database.owner,
        disabled,
    ) == [(0,)]
    assert read(one_time_database, CREDENTIAL_OF, target.actor_id)[0][1] is None


def test_the_old_recovery_function_no_longer_resets_without_a_one_time_password(
    one_time_database: OneTimeDatabase,
) -> None:
    """The administrative mode of `app.perform_account_recovery` is refused (the Owner's reset is
    the new function); the emergency mode resets a sign-in code only with a new password
    (Q-2026-10-23-180), and then also ends the live recovery codes and clears a pending
    one-time password."""
    target = add_target(one_time_database)
    credential, metadata = material("a replacement password")

    def recover(mode: str, actor: uuid.UUID | None, reason: str, **values: Any) -> Any:
        with psycopg.connect(one_time_database.runtime_url) as connection:
            row = connection.execute(
                RECOVER,
                (
                    actor,
                    target.actor_id,
                    uuid.uuid4(),
                    mode,
                    values.get("procedure"),
                    reason,
                    values.get("verifier"),
                    values.get("algorithm"),
                    values.get("metadata"),
                    values.get("reset_mfa", False),
                ),
            ).fetchone()
            connection.commit()
        return row

    full = {
        "verifier": credential.verifier_encoding,
        "algorithm": credential.algorithm,
        "metadata": metadata,
    }
    refused_with(
        errors.RaiseException,
        recover,
        "administrative",
        one_time_database.owner,
        "authorized_account_recovery",
        **full,
    )
    refused_with(
        errors.RaiseException,
        recover,
        "emergency",
        None,
        "documented_emergency_recovery",
        procedure="server-console",
        reset_mfa=True,
    )
    issue(one_time_database, target.actor_id)
    assert recover(
        "emergency",
        None,
        "documented_emergency_recovery",
        procedure="server-console",
        reset_mfa=True,
        **full,
    )[:2] == (True, True)
    assert read(one_time_database, CREDENTIAL_OF, target.actor_id)[0] == (
        credential.verifier_encoding,
        None,
    )
    assert read(
        one_time_database,
        "SELECT invalidated_at IS NOT NULL FROM app.recovery_code_sets WHERE set_id = %s",
        target.set_id,
    ) == [(True,)]


def test_the_forced_change_replaces_the_one_time_password_once(
    one_time_database: OneTimeDatabase,
) -> None:
    """The change takes a challenge the sign-in wrote, replaces the one-time password, clears
    the mark, completes the challenge, records the change and ends every live session (the L3d-1
    binding); the challenge works once, and the database clock sets its 10 minutes whatever the
    insert sent."""
    target = add_target(one_time_database)
    one_time_id = issue(one_time_database, target.actor_id)[0]
    token = add_challenge(one_time_database, target.actor_id)
    assert read(
        one_time_database,
        "SELECT expires_at - created_at, completed_at FROM app.password_change_challenges "
        "WHERE token_verifier = %s",
        token,
    ) == [(read(one_time_database, "SELECT interval '10 minutes'")[0][0], None)]
    with psycopg.connect(one_time_database.owner_url) as connection:
        connection.execute(ADD_SESSION, (uuid.uuid4(), target.actor_id, b"s" * 32, PROVENANCE))
        connection.commit()
    assert change(one_time_database, token, "my own new password 2026") == (target.actor_id, 1)
    verifier, pending = read(one_time_database, CREDENTIAL_OF, target.actor_id)[0]
    assert pending is None
    assert HASHER.verify_password("my own new password 2026", str(verifier)).is_valid
    assert read(
        one_time_database,
        "SELECT one_time_password_id, sessions_revoked FROM app.password_changes "
        "WHERE actor_id = %s",
        target.actor_id,
    ) == [(one_time_id, 1)]
    refused_with(errors.RaiseException, change, one_time_database, token, "another new password")
    refused_with(
        errors.RaiseException, change, one_time_database, secrets.token_bytes(32), "x" * 20
    )


def test_the_change_is_refused_after_24_hours_or_a_newer_password(
    one_time_database: OneTimeDatabase,
) -> None:
    """The 24 hours on the database clock (just before: changed; just after: refused), a
    challenge older than 10 minutes, and a challenge made for a password that a newer reset
    replaced are refused; nothing changes."""
    just_before = add_target(one_time_database)
    issue(one_time_database, just_before.actor_id)
    token = add_challenge(one_time_database, just_before.actor_id)
    age_one_time_password(one_time_database, just_before.actor_id, "23 hours 59 minutes")
    assert change(one_time_database, token, "changed just in time")[0] == just_before.actor_id

    late = add_target(one_time_database)
    issue(one_time_database, late.actor_id)
    token = add_challenge(one_time_database, late.actor_id)
    age_one_time_password(one_time_database, late.actor_id, "24 hours 1 second")
    refused_with(errors.RaiseException, change, one_time_database, token, "changed too late")

    stale = add_target(one_time_database)
    issue(one_time_database, stale.actor_id)
    token = add_challenge(one_time_database, stale.actor_id)
    with psycopg.connect(one_time_database.owner_url) as connection:
        connection.execute("ALTER TABLE app.password_change_challenges DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.password_change_challenges SET created_at = created_at - "
            "interval '11 minutes', expires_at = expires_at - interval '11 minutes' "
            "WHERE token_verifier = %s",
            (token,),
        )
        connection.execute("ALTER TABLE app.password_change_challenges ENABLE TRIGGER USER")
        connection.commit()
    refused_with(errors.RaiseException, change, one_time_database, token, "a slow new password")

    replaced = add_target(one_time_database)
    issue(one_time_database, replaced.actor_id)
    token = add_challenge(one_time_database, replaced.actor_id)
    issue(one_time_database, replaced.actor_id, password="one-time-password-0003")
    refused_with(errors.RaiseException, change, one_time_database, token, "a stale new password")
    assert read(
        one_time_database,
        "SELECT count(*) FROM app.password_changes WHERE actor_id IN (%s, %s, %s)",
        late.actor_id,
        stale.actor_id,
        replaced.actor_id,
    ) == [(0,)]


def test_the_records_are_append_only(one_time_database: OneTimeDatabase) -> None:
    """The one-time passwords and the changes never change; a challenge is only completed once
    (by the change function); none is deleted or truncated."""
    target = add_target(one_time_database)
    issue(one_time_database, target.actor_id)
    token = add_challenge(one_time_database, target.actor_id)
    change(one_time_database, token, "an append only check")
    for statement in (
        "UPDATE app.one_time_passwords SET reason = 'changed' WHERE actor_id = %s",
        "DELETE FROM app.one_time_passwords WHERE actor_id = %s",
        "UPDATE app.password_changes SET sessions_revoked = 9 WHERE actor_id = %s",
        "DELETE FROM app.password_changes WHERE actor_id = %s",
        "UPDATE app.password_change_challenges SET completed_at = statement_timestamp() "
        "WHERE actor_id = %s",
        "UPDATE app.password_change_challenges SET source_digest = token_verifier "
        "WHERE actor_id = %s",
        "DELETE FROM app.password_change_challenges WHERE actor_id = %s",
    ):
        with psycopg.connect(one_time_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation):
                connection.execute(statement, (target.actor_id,))
    for table in ("one_time_passwords", "password_change_challenges", "password_changes"):
        with psycopg.connect(one_time_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation):
                connection.execute(f"TRUNCATE app.{table} CASCADE")


def test_a_reset_waits_for_a_session_write_that_holds_the_password_lock(
    one_time_database: OneTimeDatabase,
) -> None:
    """Q-2026-10-24-185 (the L3a-1 and L3d-1 bindings): a session write takes the account's
    `password-credential:` lock shared as its first statement; the reset takes it exclusive, so
    it waits until the session write commits and then ends that session too (review round 2:
    the session is written inside the transaction that holds the lock)."""
    target = add_target(one_time_database)
    new_session = uuid.uuid4()
    holder = psycopg.connect(one_time_database.owner_url)
    try:
        holder.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended("
            "'password-credential:' || %s::text, 0))",
            (target.actor_id,),
        )
        results: list[tuple[Any, ...]] = []
        worker = threading.Thread(
            target=lambda: results.append(issue(one_time_database, target.actor_id))
        )
        worker.start()
        deadline = time.monotonic() + 10
        while read(one_time_database, LOCK_WAITS)[0][0] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert not results
        holder.execute(ADD_SESSION, (new_session, target.actor_id, b"n" * 32, PROVENANCE))
        holder.commit()
        worker.join(10)
        assert results and results[0][5] == 2
    finally:
        holder.close()
    assert read(
        one_time_database,
        "SELECT revocation_reason FROM app.browser_sessions WHERE session_id = %s",
        new_session,
    ) == [("password_reset",)]
