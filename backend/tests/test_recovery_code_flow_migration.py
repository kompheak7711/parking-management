"""Login sub-slice L3c-2c-1: the first recovery codes and their regeneration.

DL-058, API-098, TEST-129, DB-AUTH-003 (migration `20270201_189`). One throwaway database at head;
accounts, real Argon2id credentials and active sign-in codes are written as the table owner, and
every sign-in and recovery-code call runs as the runtime role through `PostgresAuthenticationFlow`.
Each test uses its own accounts, so the order of the tests does not matter. Sign-in codes are made
for the time step of the database clock, never of the test machine.
"""

from __future__ import annotations

import json
import logging
import threading
import time
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
    AuthenticationRejected,
    RecoveryCodeSetData,
    RecoveryCodeSetResult,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.recovery_code_security import Argon2idRecoveryCodeVerifierProvider
from property_rental.settings import Settings
from test_sign_in_code_enrollment_migration import begin, code_of, enrollment_token, new_account
from test_sign_in_code_migration import (
    ADD_SESSION,
    KEY,
    ORIGIN,
    PASSWORD,
    TURN_CODE_OFF,
    Account,
    CodeDatabase,
    add_account,
    challenge_token,
    code_for,
    digest,
    fresh_step,
    lock_waits,
    read,
)
from test_sign_in_code_migration import code_database as code_database
from test_sign_in_code_migration import migrated_database_url as migrated_database_url

REVISION = "20270201_189"
PREVIOUS = "20270131_188"
PROVENANCE = "login-slice-l3c-2c-1-test"
SETS_OF = (
    "SELECT set_id, created_by_actor_id, provenance, invalidated_at IS NOT NULL, "
    "invalidated_by_actor_id, invalidation_provenance FROM app.recovery_code_sets "
    "WHERE actor_id = %s ORDER BY created_at"
)
CODES_OF_SET = (
    "SELECT verifier_encoding, algorithm, provenance, consumed_at, invalidated_at "
    "FROM app.recovery_codes WHERE set_id = %s ORDER BY code_id"
)
ADD_SET = (
    "INSERT INTO app.recovery_code_sets (set_id, actor_id, created_by_actor_id, provenance) "
    f"VALUES (%s, %s, %s, '{PROVENANCE}')"
)


# Login sub-slice L3d-2b: new recovery codes need the reauthentication cookie a sign-in with the
# sign-in code answers, so the sessions of these tests keep theirs here.
REAUTHENTICATION_COOKIES: dict[str, str] = {}


def cookie_of(session: str) -> str | None:
    """The reauthentication cookie of a session these tests made, if it has one."""
    return REAUTHENTICATION_COOKIES.get(session)


def signed_in(
    flow: PostgresAuthenticationFlow,
    database: CodeDatabase,
    account: Account,
    step: int | None = None,
) -> str:
    """A session made with the account's sign-in code (of `step`, else of the current step);
    its reauthentication cookie is kept for `cookie_of` (login sub-slice L3d-2b)."""
    token = challenge_token(flow, account, f"{account.username}-desk")
    done = flow.complete_mfa(
        preauth_token=token,
        method="totp",
        code=code_for(account, fresh_step(database) if step is None else step),
        request_id="l3c-2c-1",
    )
    assert done.session_token is not None and done.session is not None
    assert done.session.mfa_assurance == "totp"
    assert done.reauthentication_token is not None
    REAUTHENTICATION_COOKIES[done.session_token] = done.reauthentication_token
    return done.session_token


def count_hashing(flow: PostgresAuthenticationFlow) -> list[int]:
    """Count the flow's slow hashing steps (review round 2); the list holds one counter."""
    real = flow._new_recovery_codes
    counted = [0]
    guard = threading.Lock()

    def counting() -> tuple[tuple[str, ...], list[tuple[uuid.UUID, str, str, str]]]:
        with guard:
            counted[0] += 1
        return real()

    flow._new_recovery_codes = counting  # type: ignore[method-assign]
    return counted


def assert_codes_stored_only_as_verifiers(
    database: CodeDatabase, result: RecoveryCodeSetResult, provenance: str
) -> None:
    """10 different codes, each stored only as its own Argon2id verifier."""
    assert len(result.codes) == 10 and len(set(result.codes)) == 10
    stored = read(database, CODES_OF_SET, result.set_id)
    assert [(row[1], row[2], row[3], row[4]) for row in stored] == [
        ("argon2id", provenance, None, None)
    ] * 10
    verifiers = Argon2idRecoveryCodeVerifierProvider()
    encodings = [str(row[0]) for row in stored]
    for code in result.codes:
        assert all(code not in encoding for encoding in encodings)
        assert sum(verifiers.matches(code, encoding) for encoding in encodings) == 1


def test_the_first_recovery_codes_are_shown_once_after_the_sign_in_code(
    code_database: CodeDatabase,
) -> None:
    """TEST-129, DL-058: a session made with the sign-in code (a challenge, and a first set-up)
    gets 10 recovery codes once; they are stored only as Argon2id verifiers in one live set made
    by the account itself; asking again is refused and changes nothing."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.manager")
    session = signed_in(flow, code_database, account)
    result = flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="i"
    )
    assert_codes_stored_only_as_verifiers(code_database, result, "auth-recovery-codes")
    assert read(code_database, SETS_OF, account.actor_id) == [
        (result.set_id, account.actor_id, "auth-recovery-codes", False, None, None)
    ]
    with pytest.raises(AuthenticationRejected):
        flow.issue_recovery_codes(
            session_token=session, reauthentication_token=cookie_of(session), request_id="i"
        )
    assert len(read(code_database, SETS_OF, account.actor_id)) == 1

    enrolled = new_account(code_database, "l3c-2c-1.new-staff", account_class="staff")
    preauth = enrollment_token(flow, enrolled, "l3c-2c-1-new")
    secret = begin(flow, preauth)
    done = flow.confirm_mfa_enrollment(
        preauth_token=preauth, code=code_of(secret, fresh_step(code_database)), request_id="i"
    )
    assert done.session_token is not None
    first = flow.issue_recovery_codes(
        session_token=done.session_token,
        reauthentication_token=done.reauthentication_token,
        request_id="i",
    )
    assert_codes_stored_only_as_verifiers(code_database, first, "auth-recovery-codes")


@pytest.mark.parametrize(
    "case", ["no_code", "unknown", "signed_out", "live_set", "code_off", "recovery_code"]
)
def test_recovery_codes_need_a_session_proven_with_a_sign_in_code_and_no_live_set(
    code_database: CodeDatabase,
    case: str,
) -> None:
    """The first codes and a regeneration are refused with the generic rejection and nothing
    is written for a session of an account without a sign-in code (Staff with MFA
    `optional`), an unknown cookie, a signed-out session, a session whose sign-in code was
    turned off and a session proven with a recovery code (review round 1); the first codes also
    for an account that already has a live set (as the Owner has after the bootstrap)."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    if case == "no_code":
        account = add_account(
            code_database,
            "l3c-2c-1.optional",
            account_class="staff",
            mfa="optional",
            sign_in_code=False,
        )
        result = flow.login(
            username=account.username,
            password=PASSWORD,
            request_source="l3c-2c-1",
            request_id="n",
        )
        assert result.session is not None and result.session.mfa_assurance == "none"
        assert result.session_token is not None
        session = result.session_token
    else:
        account = add_account(code_database, f"l3c-2c-1.refused-{case}")
        # L3d-2b review: the recovery-code case signs in with the previous step, so that its
        # later reauthentication can use the current one.
        earlier = fresh_step(code_database) - 1 if case == "recovery_code" else None
        session = signed_in(flow, code_database, account, earlier)
        if case == "unknown":
            session = "u" * 43
        elif case == "signed_out":
            flow.logout(session_token=session, request_id="n")
        elif case == "live_set":
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(ADD_SET, (uuid.uuid4(), account.actor_id, account.actor_id))
                connection.commit()
        elif case == "code_off":
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(TURN_CODE_OFF, (account.actor_id, account.enrollment_id))
                connection.commit()
        elif case == "recovery_code":
            # Login sub-slice L3c-2c-2: a recovery-code session needs its code's set to be live
            # (review round 2), so this account has a live set; the regeneration below names
            # it, so there only the session can refuse.
            session = recovery_code_session(flow, code_database, account, session)
            assert flow.inspect_session(session_token=session, request_id="n").mfa_assurance == (
                "recovery_code"
            )
            # Login sub-slice L3d-2b review: a recent reauthentication with the sign-in code and
            # its cookie, so only the session's recovery-code proof can refuse.
            REAUTHENTICATION_COOKIES[session] = totp_reauthentication(
                code_database, account, session
            )
    before = read(code_database, SETS_OF, account.actor_id)
    with pytest.raises(AuthenticationRejected):
        flow.issue_recovery_codes(
            session_token=session, reauthentication_token=cookie_of(session), request_id="n"
        )
    if case != "live_set":
        # Review round 2: a real live set, so only the session can refuse the regeneration
        # (the recovery-code case names the set its code came from).
        live = [row[0] for row in before if not row[3]]
        prior = live[0] if live else uuid.uuid4()
        if not live:
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(ADD_SET, (prior, account.actor_id, account.actor_id))
                connection.commit()
        before = read(code_database, SETS_OF, account.actor_id)
        with pytest.raises(AuthenticationRejected):
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=prior,
                request_id="n",
            )
    assert read(code_database, SETS_OF, account.actor_id) == before


def totp_reauthentication(database: CodeDatabase, account: Account, session: str) -> str:
    """A reauthentication of the session with the account's sign-in code just now (a new used
    step), written as the table owner through the table's guard; its cookie value."""
    cookie = f"cookie-{uuid.uuid4().hex}"
    with psycopg.connect(database.owner_url) as connection:
        step = connection.execute(
            "SELECT max(time_step) + 1 FROM app.totp_used_steps WHERE enrollment_id = %s",
            (account.enrollment_id,),
        ).fetchone()
        assert step is not None
        connection.execute(
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (account.enrollment_id, step[0]),
        )
        connection.execute(
            "INSERT INTO app.browser_session_reauthentications (reauthentication_id, "
            "session_id, actor_id, method, enrollment_id, time_step, token_verifier) "
            "SELECT %s, session_id, actor_id, 'totp', %s, %s, %s FROM app.browser_sessions "
            "WHERE token_verifier = %s",
            (uuid.uuid4(), account.enrollment_id, step[0], digest(cookie), digest(session)),
        )
        connection.commit()
    return cookie


def recovery_code_session(
    flow: PostgresAuthenticationFlow, database: CodeDatabase, account: Account, session: str
) -> str:
    """A live session of the account proven with one of its recovery codes. Login sub-slice
    L3c-2c-2: a `recovery_code` proof must name a consumed code, so the hand-written proof of
    L3c-2c-1 is refused now; the session comes from the real path (the first codes from the
    session made with the sign-in code, then a sign-in with one of them)."""
    codes = flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="n"
    ).codes
    token = challenge_token(flow, account, f"{account.username}-recovery")
    done = flow.complete_mfa(
        preauth_token=token, method="recovery_code", code=codes[0], request_id="n"
    )
    assert done.session_token is not None
    return done.session_token


def test_regeneration_invalidates_the_prior_set_and_shows_10_new_codes_once(
    code_database: CodeDatabase,
) -> None:
    """TEST-129: regeneration names the live set; the prior set is invalidated by the account
    itself and a new live set of 10 codes is shown once; the invalidated set, a set of another
    account and an unknown set id are refused and change nothing."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.regenerate")
    other = add_account(code_database, "l3c-2c-1.regenerate-other")
    session = signed_in(flow, code_database, account)
    first = flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="r"
    )
    other_session = signed_in(flow, code_database, other)
    other_set = flow.issue_recovery_codes(
        session_token=other_session,
        reauthentication_token=cookie_of(other_session),
        request_id="r",
    )
    second = flow.regenerate_recovery_codes(
        session_token=session,
        reauthentication_token=cookie_of(session),
        prior_set_id=first.set_id,
        request_id="r",
    )
    assert second.set_id != first.set_id and not set(second.codes) & set(first.codes)
    assert_codes_stored_only_as_verifiers(code_database, second, "auth-recovery-codes-regenerated")
    assert read(code_database, SETS_OF, account.actor_id) == [
        (
            first.set_id,
            account.actor_id,
            "auth-recovery-codes",
            True,
            account.actor_id,
            json.dumps(
                {
                    "reason": "auth-recovery-codes-regenerated",
                    "replacement_set_id": str(second.set_id),
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        ),
        (second.set_id, account.actor_id, "auth-recovery-codes-regenerated", False, None, None),
    ]
    for prior in (first.set_id, other_set.set_id, uuid.uuid4()):
        with pytest.raises(AuthenticationRejected):
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=prior,
                request_id="r",
            )
    assert len(read(code_database, SETS_OF, account.actor_id)) == 2
    assert [row[3] for row in read(code_database, SETS_OF, other.actor_id)] == [False]


def proven_session(database: CodeDatabase, account: Account, proof_age: str) -> str:
    """A session of the account with a `totp` proof made `proof_age` ago, written as the table
    owner: a completed challenge and a used step of now (the proof guard's conditions), and
    only the proof's time in the past (so the proof is older than its challenge's completion,
    which the proof guard does not read; review round 1). Login sub-slice L3d-2b: the window is
    now the session's reauthentication, so the sign-in's reauthentication row is written with
    the same age (the table's triggers off for that one insert) and its cookie kept."""
    token = f"proven-{uuid.uuid4().hex}"[:43]
    challenge_id = uuid.uuid4()
    session_id = uuid.uuid4()
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(
            "INSERT INTO app.sign_in_mfa_challenges (challenge_id, actor_id, token_verifier, "
            "purpose, enrollment_id, password_verifier_digest, username_digest, source_digest, "
            "completed_at) VALUES (%s, %s, %s, 'challenge', %s, %s, %s, %s, "
            "statement_timestamp())",
            (
                challenge_id,
                account.actor_id,
                digest(f"challenge-{token}"),
                account.enrollment_id,
                bytes(32),
                bytes(32),
                bytes(32),
            ),
        )
        connection.execute(
            "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
            (account.enrollment_id, fresh_step(database)),
        )
        connection.execute(ADD_SESSION, (session_id, account.actor_id, digest(token), PROVENANCE))
        connection.execute(
            "INSERT INTO app.browser_session_mfa_proofs (session_id, challenge_id, method, "
            "enrollment_id, proven_at) VALUES (%s, %s, 'totp', %s, "
            "statement_timestamp() - %s::interval)",
            (session_id, challenge_id, account.enrollment_id, proof_age),
        )
        cookie = f"cookie-{uuid.uuid4().hex}"
        connection.execute("ALTER TABLE app.browser_session_reauthentications DISABLE TRIGGER USER")
        connection.execute(
            "INSERT INTO app.browser_session_reauthentications (reauthentication_id, "
            "session_id, actor_id, method, enrollment_id, time_step, token_verifier, "
            "reauthenticated_at) SELECT %s, %s, %s, 'totp', %s, max(time_step), %s, "
            "statement_timestamp() - %s::interval FROM app.totp_used_steps "
            "WHERE enrollment_id = %s",
            (
                uuid.uuid4(),
                session_id,
                account.actor_id,
                account.enrollment_id,
                digest(cookie),
                proof_age,
                account.enrollment_id,
            ),
        )
        connection.execute("ALTER TABLE app.browser_session_reauthentications ENABLE TRIGGER USER")
        connection.commit()
    REAUTHENTICATION_COOKIES[token] = cookie
    return token


def test_new_codes_need_a_sign_in_code_given_within_15_minutes(
    code_database: CodeDatabase,
) -> None:
    """Decided under the owner's 2026-10-22 rule, for the first codes too (review round 1,
    security): a live session whose sign-in code was given 16 minutes ago by the database clock
    gets no first codes and cannot regenerate, and changes nothing; with the code given 14
    minutes ago both work. Login sub-slice L3d-2b: the time is now that of the session's
    reauthentication (a sign-in with the code writes one), set up with the same age."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    for age, allowed in (("16 minutes", False), ("14 minutes", True)):
        first = add_account(code_database, f"l3c-2c-1.first-window-{age[:2]}")
        session = proven_session(code_database, first, age)
        if allowed:
            flow.issue_recovery_codes(
                session_token=session, reauthentication_token=cookie_of(session), request_id="w"
            )
        else:
            with pytest.raises(AuthenticationRejected):
                flow.issue_recovery_codes(
                    session_token=session, reauthentication_token=cookie_of(session), request_id="w"
                )
        assert len(read(code_database, SETS_OF, first.actor_id)) == (1 if allowed else 0)
        account = add_account(code_database, f"l3c-2c-1.window-{age[:2]}")
        prior = uuid.uuid4()
        with psycopg.connect(code_database.owner_url) as connection:
            connection.execute(ADD_SET, (prior, account.actor_id, account.actor_id))
            connection.commit()
        session = proven_session(code_database, account, age)
        assert flow.inspect_session(session_token=session, request_id="w").mfa_assurance == "totp"
        if allowed:
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=prior,
                request_id="w",
            )
            assert [row[3] for row in read(code_database, SETS_OF, account.actor_id)] == [
                True,
                False,
            ]
        else:
            with pytest.raises(AuthenticationRejected):
                flow.regenerate_recovery_codes(
                    session_token=session,
                    reauthentication_token=cookie_of(session),
                    prior_set_id=prior,
                    request_id="w",
                )
            assert [row[3] for row in read(code_database, SETS_OF, account.actor_id)] == [False]


def test_two_parallel_first_sets_leave_one_live_set(code_database: CodeDatabase) -> None:
    """Two first-set requests of one account at the same moment, while the table owner holds the
    account row: one takes the account's generation lock, hashes and waits at the new set's
    account key; the other is refused at once with the generic rejection, without hashing
    (review round 1, security); one live set of 10 codes."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.parallel")
    # Each step is used once, so the first session uses the previous step and the second the
    # current one.
    step = fresh_step(code_database)
    sessions = [signed_in(flow, code_database, account, used) for used in (step - 1, step)]
    outcomes: list[str] = []
    hashed = count_hashing(flow)

    def issue(session: str) -> None:
        try:
            flow.issue_recovery_codes(
                session_token=session, reauthentication_token=cookie_of(session), request_id="p"
            )
            outcomes.append("issued")
        except AuthenticationRejected:
            outcomes.append("rejected")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.user_accounts WHERE actor_id = %s FOR UPDATE", (account.actor_id,)
        )
        threads = [threading.Thread(target=issue, args=(session,)) for session in sessions]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and (
            lock_waits(code_database) < 1 or outcomes != ["rejected"]
        ):
            time.sleep(0.05)
        waited = lock_waits(code_database)
        refused_first = list(outcomes)
        holder.commit()
    assert waited >= 1 and refused_first == ["rejected"] and hashed == [1]
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["issued", "rejected"] and hashed == [1]
    sets = read(code_database, SETS_OF, account.actor_id)
    assert [row[3] for row in sets] == [False]
    assert len(read(code_database, CODES_OF_SET, sets[0][0])) == 10


def test_a_request_refused_by_its_set_costs_no_hashing(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (both reviewers; reviewer's set-up): a regeneration naming a set that is
    not the account's live set, and a first-codes request of an account with a live set, are
    refused before the slow hashing starts."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.no-hashing")
    session = signed_in(flow, code_database, account)
    flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="h"
    )

    def no_hashing() -> None:
        raise AssertionError("recovery codes were hashed for a refused request")

    monkeypatch.setattr(flow, "_new_recovery_codes", no_hashing)
    with pytest.raises(AuthenticationRejected):
        flow.regenerate_recovery_codes(
            session_token=session,
            reauthentication_token=cookie_of(session),
            prior_set_id=uuid.uuid4(),
            request_id="h",
        )
    with pytest.raises(AuthenticationRejected):
        flow.issue_recovery_codes(
            session_token=session, reauthentication_token=cookie_of(session), request_id="h"
        )


@pytest.mark.parametrize("call", ["issue", "regenerate"])
def test_a_sign_out_while_the_codes_are_made_writes_nothing(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    call: str,
) -> None:
    """Review round 1 (both reviewers): the person signs out while the codes are being hashed,
    after every check; the session read after the writes refuses, so no new set is written and
    a prior set stays live. (Holding the account row cannot place the sign-out there, because
    the sign-out's own revocation also waits for that row.)"""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, f"l3c-2c-1.sign-out-{call}")
    session = signed_in(flow, code_database, account)
    prior = None
    if call == "regenerate":
        prior = flow.issue_recovery_codes(
            session_token=session, reauthentication_token=cookie_of(session), request_id="s"
        ).set_id
    real = flow._new_recovery_codes

    def hashed_then_signed_out() -> tuple[tuple[str, ...], list[tuple[uuid.UUID, str, str, str]]]:
        made = real()
        flow.logout(session_token=session, request_id="s")
        return made

    monkeypatch.setattr(flow, "_new_recovery_codes", hashed_then_signed_out)
    before = read(code_database, SETS_OF, account.actor_id)
    with pytest.raises(AuthenticationRejected):
        if prior is None:
            flow.issue_recovery_codes(
                session_token=session, reauthentication_token=cookie_of(session), request_id="s"
            )
        else:
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=prior,
                request_id="s",
            )
    assert read(code_database, SETS_OF, account.actor_id) == before


def test_two_parallel_regenerations_of_one_set_make_one_new_set(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (reviewer's set-up): two regenerations of one set at the same moment,
    while the table owner holds the account row: the first takes the account's generation lock,
    locks the set, hashes and waits at the invalidation's account key; the second is refused at
    once by the generation lock, without hashing (review round 2); one new live set of 10
    codes."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.parallel-regenerate")
    step = fresh_step(code_database)
    sessions = [signed_in(flow, code_database, account, used) for used in (step - 1, step)]
    first = flow.issue_recovery_codes(
        session_token=sessions[0], reauthentication_token=cookie_of(sessions[0]), request_id="g"
    )
    outcomes: list[str] = []
    hashed = count_hashing(flow)

    def regenerate(session: str) -> None:
        try:
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=first.set_id,
                request_id="g",
            )
            outcomes.append("regenerated")
        except AuthenticationRejected:
            outcomes.append("rejected")

    with psycopg.connect(code_database.owner_url) as holder:
        holder.execute(
            "SELECT 1 FROM app.user_accounts WHERE actor_id = %s FOR UPDATE", (account.actor_id,)
        )
        threads = [threading.Thread(target=regenerate, args=(session,)) for session in sessions]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and (
            lock_waits(code_database) < 1 or outcomes != ["rejected"]
        ):
            time.sleep(0.05)
        waited = lock_waits(code_database)
        refused_first = list(outcomes)
        holder.commit()
    assert waited >= 1 and refused_first == ["rejected"] and hashed == [1]
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["regenerated", "rejected"] and hashed == [1]
    sets = read(code_database, SETS_OF, account.actor_id)
    assert [row[3] for row in sets] == [True, False]
    assert len(read(code_database, CODES_OF_SET, sets[1][0])) == 10


def test_a_code_of_a_replaced_set_does_not_recover_the_account(
    code_database: CodeDatabase,
) -> None:
    """Review round 1 (security): the existing recovery with a recovery code
    (`app.perform_account_recovery`, migration 20260819_08) refuses a code of the set that a
    regeneration replaced, consumes nothing and revokes no session; a code of the new set
    works."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.replaced")
    session = signed_in(flow, code_database, account)
    first = flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="c"
    )
    second = flow.regenerate_recovery_codes(
        session_token=session,
        reauthentication_token=cookie_of(session),
        prior_set_id=first.set_id,
        request_id="c",
    )
    recover = (
        "SELECT * FROM app.perform_account_recovery(%s, %s, %s, 'recovery_code', NULL, "
        "'mfa_recovery', NULL, NULL, NULL, false, %s)"
    )
    old_code = read(
        code_database, "SELECT code_id FROM app.recovery_codes WHERE set_id = %s", first.set_id
    )[0][0]
    new_code = read(
        code_database, "SELECT code_id FROM app.recovery_codes WHERE set_id = %s", second.set_id
    )[0][0]
    with psycopg.connect(code_database.runtime_url) as connection:
        with pytest.raises(errors.RaiseException, match="account recovery rejected"):
            connection.execute(
                recover, (account.actor_id, account.actor_id, uuid.uuid4(), old_code)
            )
    assert read(
        code_database,
        "SELECT count(*) FROM app.recovery_codes WHERE set_id = %s AND consumed_at IS NOT NULL",
        first.set_id,
    ) == [(0,)]
    assert flow.inspect_session(session_token=session, request_id="c").mfa_assurance == "totp"
    with psycopg.connect(code_database.runtime_url) as connection:
        row = connection.execute(
            recover, (account.actor_id, account.actor_id, uuid.uuid4(), new_code)
        ).fetchone()
        connection.commit()
    assert row is not None and row[2] is True
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=session, request_id="c")


def test_the_codes_never_reach_the_log(
    code_database: CodeDatabase,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (security): no recovery code appears in any log record of the first codes
    or of a regeneration, at every level."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3c-2c-1.log")
    session = signed_in(flow, code_database, account)
    # Alembic's `fileConfig` in an in-process migration of the same test run turns existing
    # loggers off; the flow's own logger is turned on again for this test.
    monkeypatch.setattr(logging.getLogger("property_rental.auth_flow"), "disabled", False)
    with caplog.at_level(logging.DEBUG):
        first = flow.issue_recovery_codes(
            session_token=session, reauthentication_token=cookie_of(session), request_id="l"
        )
        second = flow.regenerate_recovery_codes(
            session_token=session,
            reauthentication_token=cookie_of(session),
            prior_set_id=first.set_id,
            request_id="l",
        )
    logged = " ".join(
        f"{record.getMessage()} {record.__dict__} {record.exc_text or ''}"
        for record in caplog.records
    )
    assert "recovery code decision" in logged
    assert all(code not in logged for code in first.codes + second.codes)
    assert all(code not in repr(first) for code in first.codes)
    # Review round 2: the response model does not print the codes either.
    data = RecoveryCodeSetData(set_id=first.set_id, codes=first.codes)
    assert all(code not in repr(data) and code not in str(data) for code in first.codes)


def test_at_most_5_sets_of_one_account_in_15_minutes(code_database: CodeDatabase) -> None:
    """Review round 2 (security; decided under the owner's 2026-10-22 rule): an account that
    made 5 sets in the last 15 minutes by the database clock is refused a regeneration before
    any hashing; with the same 5 sets made 16 minutes ago it regenerates. (The sets are
    written as the table owner: 4 invalidated and 1 live.)"""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    for age, allowed in (("0 minutes", False), ("16 minutes", True)):
        account = add_account(code_database, f"l3c-2c-1.limit-{age[:2].strip()}")
        live = uuid.uuid4()
        with psycopg.connect(code_database.owner_url) as connection:
            for number in range(5):
                connection.execute(
                    "INSERT INTO app.recovery_code_sets (set_id, actor_id, created_by_actor_id, "
                    "provenance, created_at, invalidated_at, invalidated_by_actor_id, "
                    "invalidation_provenance) SELECT %s, %s, %s, %s, moment.at, "
                    "CASE WHEN %s THEN moment.at END, CASE WHEN %s THEN %s::uuid END, "
                    "CASE WHEN %s THEN 'l3c-2c-1-test' END "
                    "FROM (SELECT statement_timestamp() - %s::interval AS at) AS moment",
                    (
                        live if number == 4 else uuid.uuid4(),
                        account.actor_id,
                        account.actor_id,
                        PROVENANCE,
                        number < 4,
                        number < 4,
                        account.actor_id,
                        number < 4,
                        age,
                    ),
                )
            connection.commit()
        session = signed_in(flow, code_database, account)
        hashed = count_hashing(flow)
        if allowed:
            flow.regenerate_recovery_codes(
                session_token=session,
                reauthentication_token=cookie_of(session),
                prior_set_id=live,
                request_id="m",
            )
            assert hashed == [1]
        else:
            with pytest.raises(AuthenticationRejected):
                flow.regenerate_recovery_codes(
                    session_token=session,
                    reauthentication_token=cookie_of(session),
                    prior_set_id=live,
                    request_id="m",
                )
            assert hashed == [0]
            assert [row[3] for row in read(code_database, SETS_OF, account.actor_id)] == [
                True,
                True,
                True,
                True,
                False,
            ]


def test_new_codes_need_the_reauthentication_cookie_of_the_session(
    code_database: CodeDatabase,
) -> None:
    """Login sub-slice L3d-2b (Q-2026-10-24-184 point 8): right after a sign-in with the sign-in
    code, the session cookie alone (copied into another client) gets no first codes and cannot
    regenerate, and neither does the cookie of another session of the account; with its own
    cookie the session gets them. A later reauthentication with the password and the code of a
    session opens the window again with its new cookie."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l3d-2b.manager")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    other = signed_in(flow, code_database, account, step)
    for cookie in (None, "", cookie_of(other), "x" * 129):
        with pytest.raises(AuthenticationRejected):
            flow.issue_recovery_codes(
                session_token=session, reauthentication_token=cookie, request_id="b"
            )
    assert read(code_database, SETS_OF, account.actor_id) == []
    first = flow.issue_recovery_codes(
        session_token=session, reauthentication_token=cookie_of(session), request_id="b"
    )
    with pytest.raises(AuthenticationRejected):
        flow.regenerate_recovery_codes(
            session_token=session, prior_set_id=first.set_id, request_id="b"
        )
    while fresh_step(code_database) <= step:
        time.sleep(1)
    again = flow.reauthenticate(
        session_token=session,
        password=PASSWORD,
        second_factor_method="totp",
        second_factor_code=code_for(account, step + 1),
        request_id="b",
    )
    with pytest.raises(AuthenticationRejected):
        flow.regenerate_recovery_codes(
            session_token=session,
            reauthentication_token=cookie_of(session),
            prior_set_id=first.set_id,
            request_id="b",
        )
    second = flow.regenerate_recovery_codes(
        session_token=session,
        reauthentication_token=again.reauthentication_token,
        prior_set_id=first.set_id,
        request_id="b",
    )
    assert [row[0] for row in read(code_database, SETS_OF, account.actor_id)] == [
        first.set_id,
        second.set_id,
    ]


def test_the_recovery_code_routes_answer_the_codes_once_with_no_store(
    code_database: CodeDatabase,
) -> None:
    """API-098 over HTTP: after the sign-in code, `POST /auth/recovery-codes` answers 10 codes
    with `Cache-Control: no-store` and 401 the second time; regeneration with the set id answers
    10 new codes with no-store."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    app = create_app(
        Settings(database_url=SecretStr(code_database.runtime_url), allowed_browser_origin=ORIGIN),
        authentication_flow=flow,
    )
    account = add_account(code_database, "l3c-2c-1.http")
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": account.username, "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": "l3c-2c-1-http"},
        )
        assert login.status_code == 200
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies["__Host-prm_csrf"],
            "X-Request-ID": "l3c-2c-1-http",
        }
        done = client.post(
            "/api/v1/auth/mfa/challenge",
            json={"method": "totp", "code": code_for(account, fresh_step(code_database))},
            headers=headers,
        )
        assert done.status_code == 200
        headers["X-CSRF-Token"] = client.cookies["__Host-prm_csrf"]
        issued = client.post("/api/v1/auth/recovery-codes", headers=headers)
        assert issued.status_code == 200
        assert issued.headers["Cache-Control"] == "no-store"
        assert len(issued.json()["data"]["codes"]) == 10
        assert client.post("/api/v1/auth/recovery-codes", headers=headers).status_code == 401
        regenerated = client.post(
            "/api/v1/auth/recovery-codes/regenerate",
            json={"prior_set_id": issued.json()["data"]["set_id"]},
            headers=headers,
        )
        assert regenerated.status_code == 200
        assert regenerated.headers["Cache-Control"] == "no-store"
        assert len(regenerated.json()["data"]["codes"]) == 10
        # Login sub-slice L6: the read shows the new set without its codes, with no-store.
        live = client.get("/api/v1/auth/recovery-codes")
        assert live.status_code == 200
        assert live.headers["Cache-Control"] == "no-store"
        assert live.json()["data"]["set_id"] == regenerated.json()["data"]["set_id"]
        assert (live.json()["data"]["made_by"], live.json()["data"]["usable_count"]) == (
            "regenerated",
            10,
        )
        assert "codes" not in live.json()["data"]


def test_the_live_set_read_shows_its_id_time_origin_and_usable_codes(
    code_database: CodeDatabase,
) -> None:
    """Login sub-slice L6 (API-098; plan bindings of L3c-2c-1 rounds 1 and 2): any live session
    of the account reads its live set without the codes: the id a regeneration names, when it
    was made, how (`issued`, `regenerated`, else `other`, as for the bootstrap's set) and how
    many of its codes still work; none before the first codes; another account's set is never
    shown; a signed-out session is refused."""
    flow = PostgresAuthenticationFlow(code_database.runtime_url, totp_protection_key=KEY)
    account = add_account(code_database, "l6.live-set")
    other = add_account(code_database, "l6.live-set-other")
    session = signed_in(flow, code_database, account, fresh_step(code_database) - 1)
    assert flow.live_recovery_code_set(session_token=session, request_id="l6") is None
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(ADD_SET, (uuid.uuid4(), other.actor_id, other.actor_id))
        connection.commit()
    assert flow.live_recovery_code_set(session_token=session, request_id="l6") is None

    recovery_session = recovery_code_session(flow, code_database, account, session)
    first = read(code_database, SETS_OF, account.actor_id)[0][0]
    summary = flow.live_recovery_code_set(session_token=recovery_session, request_id="l6")
    assert summary is not None
    assert (summary.set_id, summary.made_by, summary.usable_count) == (first, "issued", 9)
    created = read(
        code_database, "SELECT created_at FROM app.recovery_code_sets WHERE set_id = %s", first
    )
    assert summary.created_at == created[0][0]

    session = signed_in(flow, code_database, account)
    second = flow.regenerate_recovery_codes(
        session_token=session,
        reauthentication_token=cookie_of(session),
        prior_set_id=first,
        request_id="l6",
    )
    summary = flow.live_recovery_code_set(session_token=session, request_id="l6")
    assert summary is not None
    assert (summary.set_id, summary.made_by, summary.usable_count) == (
        second.set_id,
        "regenerated",
        10,
    )

    other_session = signed_in(flow, code_database, other)
    summary = flow.live_recovery_code_set(session_token=other_session, request_id="l6")
    assert summary is not None and (summary.made_by, summary.usable_count) == ("other", 0)

    flow.logout(session_token=session, request_id="l6")
    with pytest.raises(AuthenticationRejected):
        flow.live_recovery_code_set(session_token=session, request_id="l6")


def test_an_account_has_at_most_one_live_recovery_code_set(code_database: CodeDatabase) -> None:
    """Migration `20270201_189`: a second set of an account that is not invalidated is refused,
    also for the table owner; after the first is invalidated a new one is allowed."""
    account = add_account(code_database, "l3c-2c-1.index", sign_in_code=False)
    first = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(ADD_SET, (first, account.actor_id, account.actor_id))
        connection.commit()
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.UniqueViolation, match="recovery_code_sets_one_live_per_actor"):
            connection.execute(ADD_SET, (uuid.uuid4(), account.actor_id, account.actor_id))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.recovery_code_sets SET invalidated_at = statement_timestamp(), "
            "invalidated_by_actor_id = %s, invalidation_provenance = 'l3c-2c-1-test' "
            "WHERE set_id = %s",
            (account.actor_id, first),
        )
        connection.execute(ADD_SET, (uuid.uuid4(), account.actor_id, account.actor_id))
        connection.commit()
    assert [row[3] for row in read(code_database, SETS_OF, account.actor_id)] == [True, False]


def test_the_one_live_recovery_code_set_migration_follows_l3c_2b_and_is_forward_only() -> None:
    """The migration chain: `20270201_189` follows `20270131_188` and has no downgrade."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
