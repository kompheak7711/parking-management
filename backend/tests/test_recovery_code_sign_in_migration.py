"""Login sub-slice L3c-2c-2: signing in with a recovery code.

DL-058, API-096, API-098, TEST-129, DB-AUTH-003, DB-AUTH-004 (migration `20270202_190`). One
throwaway database at head; accounts, real Argon2id credentials and active sign-in codes are
written as the table owner, recovery codes come from the real first-codes call, and every sign-in
runs as the runtime role through `PostgresAuthenticationFlow`. Each test uses its own accounts and
request sources, so the order of the tests does not matter. Sign-in codes are made for the time
step of the database clock, never of the test machine.
"""

from __future__ import annotations

import logging
import uuid

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from psycopg import errors
from pydantic import SecretStr

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.recovery_code_security import Argon2idRecoveryCodeVerifierProvider
from property_rental.session_actor import PostgresSessionActorResolver
from property_rental.settings import Settings
from test_recovery_code_flow_migration import signed_in
from test_sign_in_code_enrollment_migration import enrollment_token
from test_sign_in_code_migration import (
    ADD_SESSION,
    CHALLENGES_OF,
    CLEARS_OF,
    KEY,
    ORIGIN,
    PASSWORD,
    SESSIONS_OF,
    TRIES_OF,
    TURN_CODE_OFF,
    Account,
    CodeDatabase,
    add_account,
    add_sign_in_code,
    challenge_token,
    change_for,
    digest,
    fresh_step,
    read,
    request_with,
    username_key,
)
from test_sign_in_code_migration import code_database as code_database
from test_sign_in_code_migration import migrated_database_url as migrated_database_url

REVISION = "20270202_190"
PREVIOUS = "20270201_189"
PROVENANCE = "login-slice-l3c-2c-2-test"
CODE_STATE = (
    "SELECT recovery_code.code_id, recovery_code.consumed_at IS NOT NULL, "
    "recovery_code.consumed_by_actor_id FROM app.recovery_codes AS recovery_code "
    "JOIN app.recovery_code_sets AS recovery_set USING (set_id) "
    "WHERE recovery_set.actor_id = %s ORDER BY recovery_code.code_id"
)
PROOFS_OF = (
    "SELECT proof.method, proof.enrollment_id, proof.recovery_code_id "
    "FROM app.browser_session_mfa_proofs AS proof "
    "JOIN app.browser_sessions AS browser ON browser.session_id = proof.session_id "
    "WHERE browser.actor_id = %s ORDER BY proof.proven_at"
)
REVOCATIONS_OF = (
    "SELECT revocation_reason FROM app.browser_sessions WHERE actor_id = %s ORDER BY created_at"
)
RECOVERY_EVENTS_OF = (
    "SELECT count(*) FROM app.account_recovery_audit_events WHERE target_actor_id = %s"
)


def flow_of(database: CodeDatabase) -> PostgresAuthenticationFlow:
    return PostgresAuthenticationFlow(database.runtime_url, totp_protection_key=KEY)


def with_codes(
    flow: PostgresAuthenticationFlow, database: CodeDatabase, account: Account
) -> tuple[str, tuple[str, ...]]:
    """A session made with the sign-in code and the account's first 10 recovery codes."""
    session = signed_in(flow, database, account)
    return session, flow.issue_recovery_codes(session_token=session, request_id="w").codes


def consumed_codes(database: CodeDatabase, account: Account) -> list[uuid.UUID]:
    return [row[0] for row in read(database, CODE_STATE, account.actor_id) if row[1]]


def code_id_of(database: CodeDatabase, account: Account, code: str) -> uuid.UUID:
    """The id of the stored code that matches `code` (an Argon2id check of each)."""
    verifiers = Argon2idRecoveryCodeVerifierProvider()
    rows = read(
        database,
        "SELECT recovery_code.code_id, recovery_code.verifier_encoding "
        "FROM app.recovery_codes AS recovery_code "
        "JOIN app.recovery_code_sets AS recovery_set USING (set_id) "
        "WHERE recovery_set.actor_id = %s",
        account.actor_id,
    )
    return uuid.UUID(str(next(row[0] for row in rows if verifiers.matches(code, str(row[1])))))


def test_a_recovery_code_completes_the_challenge_once_and_ends_the_other_sessions(
    code_database: CodeDatabase,
) -> None:
    """TEST-129, DL-058: after one wrong recovery code, a right one (with spaces around it, as
    when it is pasted) completes the sign-in code challenge: a session with `mfa_assurance`
    `recovery_code` and a proof naming the consumed code, which the session read and the actor
    resolver accept; the code is consumed by the account itself through the audited account
    recovery, which revokes the account's other sessions (`mfa_recovery`) and clears the
    wrong-try count. The same code is refused at a later challenge (and counted); another code
    of the set works."""
    flow = flow_of(code_database)
    resolver = PostgresSessionActorResolver(code_database.runtime_url)
    account = add_account(code_database, "l3c-2c-2.manager")
    first_session, codes = with_codes(flow, code_database, account)
    events_before = read(code_database, RECOVERY_EVENTS_OF, account.actor_id)[0][0]
    preauth = challenge_token(flow, account, "l3c-2c-2-desk")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code="not-a-code", request_id="r"
        )
    done = flow.complete_mfa(
        preauth_token=preauth, method="recovery_code", code=f"  {codes[3]} ", request_id="r"
    )
    assert done.phase is AuthenticationPhase.AUTHENTICATED
    assert done.session is not None and done.session_token is not None
    assert (done.session.actor_id, done.session.mfa_assurance) == (
        str(account.actor_id),
        "recovery_code",
    )
    used = code_id_of(code_database, account, codes[3])
    assert consumed_codes(code_database, account) == [used]
    assert [
        row[2] for row in read(code_database, CODE_STATE, account.actor_id) if row[0] == used
    ] == [account.actor_id]
    assert read(code_database, PROOFS_OF, account.actor_id)[-1] == ("recovery_code", None, used)
    assert read(code_database, RECOVERY_EVENTS_OF, account.actor_id)[0][0] == events_before + 1
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(1,)]
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=first_session, request_id="r")
    assert read(code_database, REVOCATIONS_OF, account.actor_id) == [("mfa_recovery",), (None,)]
    assert (
        flow.inspect_session(session_token=done.session_token, request_id="r").mfa_assurance
        == "recovery_code"
    )
    actor = resolver(request_with(f"__Host-prm_session={done.session_token}"))
    assert actor is not None and actor.actor_id == str(account.actor_id)

    again = challenge_token(flow, account, "l3c-2c-2-desk")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=again, method="recovery_code", code=codes[3], request_id="r"
        )
    assert read(code_database, TRIES_OF, username_key(account.username))[-1] == ("recovery_code",)
    other = flow.complete_mfa(
        preauth_token=again, method="recovery_code", code=codes[4], request_id="r"
    )
    assert other.session is not None and other.session.mfa_assurance == "recovery_code"
    assert len(consumed_codes(code_database, account)) == 2


def test_wrong_recovery_codes_count_and_a_right_one_during_a_wait_is_refused(
    code_database: CodeDatabase,
) -> None:
    """Q-2026-10-21-154 (a): a wrong recovery code is a wrong try of kind `recovery_code`; the
    3rd starts the 5-minute wait (429) and a right code during the wait is refused with 429; no
    code is consumed and no session is made."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.wrong")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, "l3c-2c-2-wrong")
    sessions_before = read(code_database, SESSIONS_OF, account.actor_id)
    for _ in range(2):
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(
                preauth_token=preauth, method="recovery_code", code="wrong-code", request_id="w"
            )
    with pytest.raises(AuthenticationRateLimited) as started:
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code="wrong-code", request_id="w"
        )
    assert started.value.retry_after_seconds == 300
    with pytest.raises(AuthenticationRateLimited):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=codes[0], request_id="w"
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("recovery_code",)] * 3
    assert consumed_codes(code_database, account) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == sessions_before


def test_a_code_of_a_replaced_set_is_a_wrong_code(code_database: CodeDatabase) -> None:
    """The codes of a set that a regeneration replaced are refused at the challenge (counted as a
    wrong try, nothing consumed); a code of the new set works."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.replaced")
    session = signed_in(flow, code_database, account)
    first = flow.issue_recovery_codes(session_token=session, request_id="p")
    second = flow.regenerate_recovery_codes(
        session_token=session, prior_set_id=first.set_id, request_id="p"
    )
    preauth = challenge_token(flow, account, "l3c-2c-2-replaced")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=first.codes[0], request_id="p"
        )
    assert consumed_codes(code_database, account) == []
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("recovery_code",)]
    done = flow.complete_mfa(
        preauth_token=preauth, method="recovery_code", code=second.codes[0], request_id="p"
    )
    assert done.session is not None


def test_a_recovery_code_does_not_complete_a_set_up_and_a_parallel_try_waits_for_nothing(
    code_database: CodeDatabase,
) -> None:
    """A recovery code does not complete an `enrollment` challenge (an account whose sign-in code
    is off still has its codes; nothing is consumed); a try while another try of the account
    holds its lock is refused at once, without hashing or counting."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.no-set-up", account_class="staff")
    _, codes = with_codes(flow, code_database, account)
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        connection.execute(
            "UPDATE app.user_accounts SET mfa_policy_class = 'required' WHERE actor_id = %s",
            (account.actor_id,),
        )
        connection.commit()
    token = enrollment_token(flow, account, "l3c-2c-2-no-set-up")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=token, method="recovery_code", code=codes[0], request_id="e"
        )
    assert consumed_codes(code_database, account) == []

    locked = add_account(code_database, "l3c-2c-2.parallel")
    _, locked_codes = with_codes(flow, code_database, locked)
    preauth = challenge_token(flow, locked, "l3c-2c-2-parallel")
    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('recovery-codes:' || %s::text, 0))",
            (locked.actor_id,),
        )
        with pytest.raises(AuthenticationRejected):
            flow.complete_mfa(
                preauth_token=preauth,
                method="recovery_code",
                code=locked_codes[0],
                request_id="e",
            )
        holder.commit()
    assert read(code_database, TRIES_OF, username_key(locked.username)) == []
    assert consumed_codes(code_database, locked) == []
    # Review round 1: the refused try completed nothing, so the same step and code then work.
    done = flow.complete_mfa(
        preauth_token=preauth, method="recovery_code", code=locked_codes[0], request_id="e"
    )
    assert done.session is not None and len(consumed_codes(code_database, locked)) == 1


def test_a_recovery_code_session_ends_when_the_sign_in_code_is_turned_off(
    code_database: CodeDatabase,
) -> None:
    """The L3c-2a binding: a `recovery_code` proof counts only while the sign-in code its
    challenge was made for is active, so a sign-in code turned off (even without a revocation)
    ends the session of a Manager."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.code-off")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, "l3c-2c-2-off")
    done = flow.complete_mfa(
        preauth_token=preauth, method="recovery_code", code=codes[0], request_id="o"
    )
    assert done.session_token is not None
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        connection.commit()
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=done.session_token, request_id="o")


@pytest.mark.parametrize("case", ["wait", "password", "sign_in_code", "account"])
def test_a_change_before_the_recovery_code_refuses_and_consumes_nothing(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """A change committed after the challenge was read and its wait checked, before the recovery
    code's transaction: a wait that 3 parallel wrong codes started (429), a new password (the
    verifier comparison), the sign-in code turned off (the session read back) and the account
    disabled (the account recovery refuses); the code is not consumed, no session is revoked
    or made, no audit event is left and the count is not cleared."""
    flow = flow_of(code_database)
    account = add_account(code_database, f"l3c-2c-2.window-{case}")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, f"l3c-2c-2-window-{case}")
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[-1]
    sessions_before = read(code_database, SESSIONS_OF, account.actor_id)
    events_before = read(code_database, RECOVERY_EVENTS_OF, account.actor_id)
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
            preauth_token=preauth, method="recovery_code", code=codes[0], request_id="x"
        )
    assert consumed_codes(code_database, account) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == sessions_before
    # Review round 1: the account recovery's audit event is rolled back too.
    assert read(code_database, RECOVERY_EVENTS_OF, account.actor_id) == events_before
    assert read(
        code_database,
        "SELECT revoked_at IS NULL FROM app.browser_sessions WHERE actor_id = %s",
        account.actor_id,
    ) == [(True,)]
    assert [row[2] for row in read(code_database, CHALLENGES_OF, account.actor_id)][-1] is False
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(0,)]


def test_another_accounts_code_is_a_wrong_code(code_database: CodeDatabase) -> None:
    """Review round 1: a valid recovery code of another account is a wrong code here (counted,
    nothing consumed), and still works for its own account."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.cross")
    other = add_account(code_database, "l3c-2c-2.cross-other")
    with_codes(flow, code_database, account)
    _, other_codes = with_codes(flow, code_database, other)
    preauth = challenge_token(flow, account, "l3c-2c-2-cross")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=other_codes[0], request_id="c"
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("recovery_code",)]
    assert consumed_codes(code_database, other) == []
    recover(flow, other, other_codes[0], "l3c-2c-2-cross")


def test_a_wait_that_starts_before_the_try_lock_is_met_under_it(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (security; reviewer's set-up): a wait that the first check did not see
    (3 wrong tries recorded, the first check made to see none) is met under the try lock:
    429, and no recovery code is hashed."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.wait-under-lock")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, "l3c-2c-2-wait-lock")
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[-1]
    with psycopg.connect(code_database.runtime_url) as connection:
        for _ in range(3):
            connection.execute(
                "SELECT app.record_sign_in_wrong_try(%s, %s, 'sign_in_code')",
                (bytes(stored[4]), bytes(stored[5])),
            )
            connection.commit()
    checks: list[int] = []
    real = Argon2idRecoveryCodeVerifierProvider.matches

    def counted(self: Argon2idRecoveryCodeVerifierProvider, candidate: str, encoding: str) -> bool:
        checks.append(1)
        return real(self, candidate, encoding)

    monkeypatch.setattr(flow._sign_in_waits, "challenge_wait_seconds", lambda *_: None)
    monkeypatch.setattr(Argon2idRecoveryCodeVerifierProvider, "matches", counted)
    with pytest.raises(AuthenticationRateLimited):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=codes[0], request_id="l"
        )
    assert checks == []
    assert consumed_codes(code_database, account) == []


def test_a_regeneration_during_the_check_refuses_the_replaced_code(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (security; reviewer's set-up): the set is invalidated and committed while
    the typed code is being checked; the account recovery then refuses the replaced code (401,
    uncounted): nothing is consumed, revoked or written, the challenge stays open, and the clear
    and the audit event are rolled back too (review round 2: one wrong try first)."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.regenerated-meanwhile")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, "l3c-2c-2-meanwhile")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code="not-a-code", request_id="m"
        )
    sessions_before = read(code_database, SESSIONS_OF, account.actor_id)
    events_before = read(code_database, RECOVERY_EVENTS_OF, account.actor_id)
    real = Argon2idRecoveryCodeVerifierProvider.matches
    invalidated: list[bool] = []

    def invalidating(
        self: Argon2idRecoveryCodeVerifierProvider, candidate: str, encoding: str
    ) -> bool:
        if not invalidated:
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(
                    "UPDATE app.recovery_code_sets SET invalidated_at = statement_timestamp(), "
                    "invalidated_by_actor_id = actor_id, invalidation_provenance = 'l3c-2c-2' "
                    "WHERE actor_id = %s AND invalidated_at IS NULL",
                    (account.actor_id,),
                )
                connection.commit()
            invalidated.append(True)
        return real(self, candidate, encoding)

    monkeypatch.setattr(Argon2idRecoveryCodeVerifierProvider, "matches", invalidating)
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=codes[0], request_id="m"
        )
    assert consumed_codes(code_database, account) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == sessions_before
    assert [row[2] for row in read(code_database, CHALLENGES_OF, account.actor_id)][-1] is False
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("recovery_code",)]
    assert read(code_database, CLEARS_OF, username_key(account.username)) == [(0,)]
    assert read(code_database, RECOVERY_EVENTS_OF, account.actor_id) == events_before


def test_the_sign_in_wait_locks_are_free_during_the_hashing(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2 (both reviewers; reviewer's set-up): while a recovery code is being
    checked, the sign-in wait check of another account from the same source does not wait (a
    1-second lock timeout), and the try still makes its session."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.free-locks")
    neighbour = add_account(code_database, "l3c-2c-2.free-locks-other")
    _, codes = with_codes(flow, code_database, account)
    preauth = challenge_token(flow, account, "l3c-2c-2-shared-source")
    stored = read(code_database, CHALLENGES_OF, account.actor_id)[-1]
    real = Argon2idRecoveryCodeVerifierProvider.matches
    probes: list[object] = []

    def probing(self: Argon2idRecoveryCodeVerifierProvider, candidate: str, encoding: str) -> bool:
        if not probes:
            with psycopg.connect(code_database.runtime_url) as connection:
                connection.execute("SET lock_timeout = '1s'")
                for username_digest in (username_key(neighbour.username), bytes(stored[4])):
                    probes.append(
                        connection.execute(
                            "SELECT app.sign_in_wait_seconds(%s, %s)",
                            (username_digest, bytes(stored[5])),
                        ).fetchone()
                    )
        return real(self, candidate, encoding)

    monkeypatch.setattr(Argon2idRecoveryCodeVerifierProvider, "matches", probing)
    done = flow.complete_mfa(
        preauth_token=preauth, method="recovery_code", code=codes[0], request_id="f"
    )
    assert done.session is not None
    assert probes == [(None,), (None,)]


def test_codes_from_before_a_sign_in_code_reset_do_not_come_back(
    code_database: CodeDatabase,
) -> None:
    """Review round 2 (security): after the sign-in code is turned off and a new one is set up,
    the codes made before stay live until L4 invalidates them at a reset, but they are older
    than the sign-in code the challenge is made for, so they are wrong codes (counted, nothing
    consumed, no session)."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.reset")
    _, codes = with_codes(flow, code_database, account)
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
        add_sign_in_code(connection, account.actor_id)
        connection.commit()
    sessions_before = read(code_database, SESSIONS_OF, account.actor_id)
    preauth = challenge_token(flow, account, "l3c-2c-2-reset")
    with pytest.raises(AuthenticationRejected):
        flow.complete_mfa(
            preauth_token=preauth, method="recovery_code", code=codes[0], request_id="t"
        )
    assert read(code_database, TRIES_OF, username_key(account.username)) == [("recovery_code",)]
    assert consumed_codes(code_database, account) == []
    assert read(code_database, SESSIONS_OF, account.actor_id) == sessions_before


def test_replacing_the_codes_ends_a_session_made_with_one_of_them(
    code_database: CodeDatabase,
) -> None:
    """Review round 2 (security; reviewer's set-up): a session made with a recovery code ends
    when the person, signed in with the sign-in code, replaces the codes; the sign-in code's
    session stays live."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.replace-ends")
    # Each step is used once: the previous step for the first session, the current for the
    # second.
    step = fresh_step(code_database)
    first = signed_in(flow, code_database, account, step - 1)
    codes = flow.issue_recovery_codes(session_token=first, request_id="r").codes
    recovered = flow.complete_mfa(
        preauth_token=challenge_token(flow, account, "l3c-2c-2-replace"),
        method="recovery_code",
        code=codes[0],
        request_id="r",
    )
    assert recovered.session_token is not None
    set_id = read(
        code_database,
        "SELECT set_id FROM app.recovery_code_sets WHERE actor_id = %s AND invalidated_at IS NULL",
        account.actor_id,
    )[0][0]
    signed = signed_in(flow, code_database, account, step)
    flow.regenerate_recovery_codes(session_token=signed, prior_set_id=set_id, request_id="r")
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=recovered.session_token, request_id="r")
    assert flow.inspect_session(session_token=signed, request_id="r").mfa_assurance == "totp"


def test_the_challenge_route_takes_a_recovery_code_and_logs_no_code(
    code_database: CodeDatabase,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API-096 over HTTP: `POST /auth/mfa/challenge` with `recovery_code` sets the session
    cookie, removes the pre-authentication cookie and answers no-store with `mfa_assurance`
    `recovery_code`; no recovery code reaches the log."""
    flow = flow_of(code_database)
    app = create_app(
        Settings(database_url=SecretStr(code_database.runtime_url), allowed_browser_origin=ORIGIN),
        authentication_flow=flow,
    )
    account = add_account(code_database, "l3c-2c-2.http")
    _, codes = with_codes(flow, code_database, account)
    monkeypatch.setattr(logging.getLogger("property_rental.auth_flow"), "disabled", False)
    with caplog.at_level(logging.DEBUG), TestClient(app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": account.username, "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": "l3c-2c-2-http"},
        )
        assert login.json()["data"]["phase"] == "mfa_required"
        done = client.post(
            "/api/v1/auth/mfa/challenge",
            json={"method": "recovery_code", "code": codes[0]},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": client.cookies["__Host-prm_csrf"],
                "X-Request-ID": "l3c-2c-2-http",
            },
        )
        assert done.status_code == 200
        assert done.json()["data"]["session"]["mfa_assurance"] == "recovery_code"
        assert done.headers["Cache-Control"] == "no-store"
        assert "__Host-prm_session" in client.cookies
        assert "__Host-prm_preauth" not in client.cookies
    logged = " ".join(
        f"{record.getMessage()} {record.__dict__} {record.exc_text or ''}"
        for record in caplog.records
    )
    assert "recovery code sign-in decision" in logged
    assert all(code not in logged for code in codes)
    # Review round 2: the audit event's correlation id is in the decision log.
    correlation = read(
        code_database,
        "SELECT correlation_id FROM app.account_recovery_audit_events "
        "WHERE target_actor_id = %s ORDER BY event_id DESC LIMIT 1",
        account.actor_id,
    )[0][0]
    assert str(correlation) in logged


def recover(flow: PostgresAuthenticationFlow, account: Account, code: str, source: str) -> None:
    """A sign-in with a recovery code (the flow is the positive control of the proof guard)."""
    done = flow.complete_mfa(
        preauth_token=challenge_token(flow, account, source),
        method="recovery_code",
        code=code,
        request_id="g",
    )
    assert done.session is not None and done.session.mfa_assurance == "recovery_code"


def test_a_recovery_code_proof_is_guarded_in_the_database(code_database: CodeDatabase) -> None:
    """DB-AUTH-004 (migration `20270202_190`): a `recovery_code` proof must name a recovery code
    of the challenge's account consumed by that account since the challenge was made, for a
    `challenge` (not an `enrollment`): refused without a code, for an unused code, another
    account's consumed code, a code consumed before the challenge and an `enrollment`
    challenge; one code proves one session (a code that already proves a session meets the
    unique column); a code of an invalidated set and a code of a set made before the
    challenge's sign-in code (review round 3) are refused; the method and the code go
    together (check constraint, with a `totp` proof the guard accepts); the runtime role may
    write the new column only on insert and read it (the session read, review round 2). The
    real sign-ins are the positive controls. The first case (no code) is also the refusal of
    the proof that L3c-2c-1's test set-up wrote by hand."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3c-2c-2.guard")
    other = add_account(code_database, "l3c-2c-2.guard-other")
    _, codes = with_codes(flow, code_database, account)
    _, other_codes = with_codes(flow, code_database, other)
    recover(flow, account, codes[0], "l3c-2c-2-guard")
    recover(flow, other, other_codes[0], "l3c-2c-2-guard")
    open_challenge = challenge_token(flow, account, "l3c-2c-2-guard")
    set_up_token = f"set-up-{uuid.uuid4().hex}"[:43]
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
            "purpose, password_verifier_digest, username_digest, source_digest, completed_at) "
            "VALUES (%s, %s, %s, 'enrollment', %s, %s, %s, statement_timestamp())",
            (uuid.uuid4(), account.actor_id, digest(set_up_token), bytes(32), bytes(32), bytes(32)),
        )
        connection.commit()
    recover(flow, account, codes[1], "l3c-2c-2-guard")
    recover(flow, account, codes[2], "l3c-2c-2-guard")
    session_id = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
            "WHERE token_verifier = %s",
            (digest(open_challenge),),
        )
        connection.execute(
            ADD_SESSION, (session_id, account.actor_id, digest(f"guard-{session_id}"), PROVENANCE)
        )
        connection.commit()
    add_proof = (
        "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
        "recovery_code_id) SELECT %s, challenge_id, 'recovery_code', %s "
        "FROM app.sign_in_mfa_challenges WHERE token_verifier = %s"
    )
    code_ids = {code: code_id_of(code_database, account, code) for code in codes[:6]}
    cases = (
        ((None, digest(open_challenge)), errors.IntegrityConstraintViolation, "used since"),
        (
            (code_ids[codes[5]], digest(open_challenge)),
            errors.IntegrityConstraintViolation,
            "used since",
        ),
        (
            (code_id_of(code_database, other, other_codes[0]), digest(open_challenge)),
            errors.IntegrityConstraintViolation,
            "used since",
        ),
        (
            (code_ids[codes[0]], digest(open_challenge)),
            errors.IntegrityConstraintViolation,
            "used since",
        ),
        (
            (code_ids[codes[2]], digest(set_up_token)),
            errors.IntegrityConstraintViolation,
            "used since",
        ),
        ((code_ids[codes[1]], digest(open_challenge)), errors.UniqueViolation, "recovery_code_id"),
    )
    for (code_id, token_verifier), error, message in cases:
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(error, match=message):
                connection.execute(add_proof, (session_id, code_id, token_verifier))
    # Review round 1: a code consumed since the challenge but of an invalidated set is refused
    # (the set-live condition alone; written as the table owner).
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.recovery_codes SET consumed_at = statement_timestamp(), "
            "consumed_by_actor_id = %s, consumption_provenance = 'l3c-2c-2-test' "
            "WHERE code_id = %s",
            (account.actor_id, code_ids[codes[4]]),
        )
        connection.execute(
            "UPDATE app.recovery_code_sets SET invalidated_at = statement_timestamp(), "
            "invalidated_by_actor_id = actor_id, invalidation_provenance = 'l3c-2c-2-test' "
            "WHERE actor_id = %s AND invalidated_at IS NULL",
            (account.actor_id,),
        )
        with pytest.raises(errors.IntegrityConstraintViolation, match="used since"):
            connection.execute(add_proof, (session_id, code_ids[codes[4]], digest(open_challenge)))
    # Review round 1: the check constraint itself, with a `totp` proof the guard accepts (a
    # fresh account's completed challenge and a used step of its sign-in code) that also names
    # a recovery code.
    third = add_account(code_database, "l3c-2c-2.guard-check")
    third_session = uuid.uuid4()
    third_token = f"check-{uuid.uuid4().hex}"[:43]
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
            "purpose, enrollment_id, password_verifier_digest, username_digest, source_digest, "
            "completed_at) VALUES (%s, %s, %s, 'challenge', %s, %s, %s, %s, "
            "statement_timestamp())",
            (
                uuid.uuid4(),
                third.actor_id,
                digest(third_token),
                third.enrollment_id,
                bytes(32),
                bytes(32),
                bytes(32),
            ),
        )
        connection.execute(
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (third.enrollment_id, fresh_step(code_database)),
        )
        connection.execute(
            ADD_SESSION, (third_session, third.actor_id, digest(f"s-{third_token}"), PROVENANCE)
        )
        with pytest.raises(errors.CheckViolation, match="recovery_code_of_method"):
            connection.execute(
                "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
                "enrollment_id, recovery_code_id) SELECT %s, challenge_id, 'totp', %s, %s "
                "FROM app.sign_in_mfa_challenges WHERE token_verifier = %s",
                (third_session, third.enrollment_id, code_ids[codes[0]], digest(third_token)),
            )
    # Review round 3 (reviewer's set-up): a code of a live set made before the sign-in code the
    # challenge was made for (the sign-in code turned off and a new one set up), consumed by the
    # account since the challenge, is refused (the made-no-earlier condition alone).
    fourth = add_account(code_database, "l3c-2c-2.guard-older-set")
    _, fourth_codes = with_codes(flow, code_database, fourth)
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(TURN_CODE_OFF, (fourth.actor_id, fourth.enrollment_id))
        add_sign_in_code(connection, fourth.actor_id)
        connection.commit()
    newer_challenge = challenge_token(flow, fourth, "l3c-2c-2-guard-older")
    older_code = code_id_of(code_database, fourth, fourth_codes[0])
    fourth_session = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.recovery_codes SET consumed_at = statement_timestamp(), "
            "consumed_by_actor_id = %s, consumption_provenance = 'l3c-2c-2-test' "
            "WHERE code_id = %s",
            (fourth.actor_id, older_code),
        )
        connection.execute(
            "UPDATE app.sign_in_mfa_challenges SET completed_at = statement_timestamp() "
            "WHERE token_verifier = %s",
            (digest(newer_challenge),),
        )
        connection.execute(
            ADD_SESSION,
            (fourth_session, fourth.actor_id, digest(f"older-{fourth_session}"), PROVENANCE),
        )
        with pytest.raises(errors.IntegrityConstraintViolation, match="used since"):
            connection.execute(add_proof, (fourth_session, older_code, digest(newer_challenge)))
    with psycopg.connect(code_database.owner_url) as connection:
        definition = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'browser_session_mfa_proofs_recovery_code_of_method'"
        ).fetchone()
        privileges = connection.execute(
            "SELECT has_column_privilege('prm_runtime', 'app.browser_session_mfa_proofs', "
            "'recovery_code_id', 'INSERT'), has_column_privilege('prm_runtime', "
            "'app.browser_session_mfa_proofs', 'recovery_code_id', 'UPDATE'), "
            "has_column_privilege('prm_runtime', 'app.browser_session_mfa_proofs', "
            "'recovery_code_id', 'SELECT')"
        ).fetchone()
    assert definition is not None
    assert "method = 'recovery_code'" in str(definition[0])
    assert "recovery_code_id IS NOT NULL" in str(definition[0])
    assert privileges == (True, False, True)


def test_the_recovery_code_sign_in_migration_follows_l3c_2c_1_and_is_forward_only() -> None:
    """The migration chain: `20270202_190` follows `20270201_189` and has no downgrade."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
