"""Login sub-slice L3d-1: high-risk reauthentication of a signed-in session.

SEC-018, API-097, UI-111, TEST-132, DB-AUTH-004, owner answer (a) to Q-2026-10-21-157 (migration
`20270203_191`). One throwaway database at head; accounts, real Argon2id credentials and active
sign-in codes are written as the table owner, and every sign-in and reauthentication runs as the
runtime role through `PostgresAuthenticationFlow`. Each test uses its own accounts, so the order
of the tests does not matter. Sign-in codes are made for the time step of the database clock,
never of the test machine.
"""

from __future__ import annotations

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
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
)
from property_rental.auth_flow import PostgresAuthenticationFlow, sign_in_username_digest
from property_rental.password_security import PasswordVerification
from property_rental.settings import Settings
from test_recovery_code_flow_migration import signed_in
from test_sign_in_code_migration import (
    ADD_SESSION,
    CLEARS_OF,
    KEY,
    ORIGIN,
    PASSWORD,
    USED_STEPS_OF,
    WRONG,
    Account,
    CodeDatabase,
    add_account,
    change_for,
    code_for,
    digest,
    fresh_step,
    read,
    wrong_code,
)
from test_sign_in_code_migration import code_database as code_database
from test_sign_in_code_migration import migrated_database_url as migrated_database_url

REVISION = "20270203_191"
PREVIOUS = "20270202_190"
PROVENANCE = "login-slice-l3d-1-test"
REAUTHENTICATIONS_OF = (
    "SELECT method, enrollment_id, time_step FROM app.browser_session_reauthentications "
    "WHERE actor_id = %s ORDER BY reauthenticated_at"
)
TRIES_OF = "SELECT try_kind FROM app.sign_in_wrong_tries WHERE username_digest = %s ORDER BY try_no"


def flow_of(database: CodeDatabase) -> PostgresAuthenticationFlow:
    return PostgresAuthenticationFlow(database.runtime_url, totp_protection_key=KEY)


def username_key(account: Account) -> bytes:
    return sign_in_username_digest(account.username)


def reauthenticate(
    flow: PostgresAuthenticationFlow,
    session: str,
    *,
    password: str = PASSWORD,
    method: str | None = "totp",
    code: str | None = None,
) -> None:
    flow.reauthenticate(
        session_token=session,
        password=password,
        second_factor_method=method,
        second_factor_code=code,
        request_id="l3d-1",
    )


def test_the_password_and_a_new_sign_in_code_reauthenticate_a_session(
    code_database: CodeDatabase,
) -> None:
    """TEST-132, owner answer (a) to Q-2026-10-21-157: a Manager's session given the password
    and a sign-in code of a time step not used yet gets a reauthentication: the session shows
    `reauthenticated_at`, a new CSRF token is answered, the step is used once and one row names
    the sign-in code and the step."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3d-1.manager")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    assert flow.inspect_session(session_token=session, request_id="r").reauthenticated_at is None
    result = flow.reauthenticate(
        session_token=session,
        password=PASSWORD,
        second_factor_method="totp",
        second_factor_code=code_for(account, step),
        request_id="r",
    )
    assert result.csrf_token and result.session.reauthenticated_at is not None
    assert result.reauthentication_token and result.reauthentication_token != result.csrf_token
    assert result.session.actor_id == str(account.actor_id)
    assert (
        flow.inspect_session(
            session_token=session,
            request_id="r",
            reauthentication_token=result.reauthentication_token,
        ).reauthenticated_at
        == result.session.reauthenticated_at
    )
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == [
        ("totp", account.enrollment_id, step)
    ]
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == [(step - 1,), (step,)]


def test_a_reauthentication_shows_only_with_its_own_reauthentication_cookie(
    code_database: CodeDatabase,
) -> None:
    """Review round 2 (security S-1), owner answer of 2026-10-24 to Q-2026-10-24-183: each
    reauthentication answers a new reauthentication cookie; only its sha256 digest is kept on
    the row, never the cookie itself. The session shows `reauthenticated_at` only with the
    cookie made for it: a copied session cookie alone shows none, nor does a reauthentication
    cookie of another session, a made-up, empty or too long one (which never refuses the live
    session either). A later reauthentication answers a new cookie; each cookie shows its own
    row."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3d-1.cookie")
    other = add_account(code_database, "l3d-1.cookie-other")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    other_session = signed_in(flow, code_database, other, step - 1)
    first = flow.reauthenticate(
        session_token=session,
        password=PASSWORD,
        second_factor_method="totp",
        second_factor_code=code_for(account, step),
        request_id="c",
    )
    other_result = flow.reauthenticate(
        session_token=other_session,
        password=PASSWORD,
        second_factor_method="totp",
        second_factor_code=code_for(other, step),
        request_id="c",
    )
    kept = read(
        code_database,
        "SELECT token_verifier FROM app.browser_session_reauthentications WHERE actor_id = %s",
        account.actor_id,
    )
    assert kept == [(digest(first.reauthentication_token),)]

    def shown(token: str | None) -> object:
        return flow.inspect_session(
            session_token=session, request_id="c", reauthentication_token=token
        ).reauthenticated_at

    assert shown(first.reauthentication_token) == first.session.reauthenticated_at
    assert shown(None) is None
    assert shown(other_result.reauthentication_token) is None
    assert shown("made-up-" + first.reauthentication_token) is None
    # A missing or malformed cookie shows none and never refuses the live session.
    assert shown("") is None
    assert shown("x" * 129) is None
    # Each reauthentication answers its own cookie (review round 2): at the next time step a
    # second one is not limited (only password-only ones are), and each cookie shows its own row.
    while fresh_step(code_database) <= step:
        time.sleep(1)
    later = flow.reauthenticate(
        session_token=session,
        password=PASSWORD,
        second_factor_method="totp",
        second_factor_code=code_for(account, step + 1),
        request_id="c",
    )
    assert later.reauthentication_token != first.reauthentication_token
    assert later.session.reauthenticated_at is not None
    assert first.session.reauthenticated_at is not None
    assert later.session.reauthenticated_at > first.session.reauthenticated_at
    assert shown(later.reauthentication_token) == later.session.reauthenticated_at
    assert shown(first.reauthentication_token) == first.session.reauthenticated_at
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == [
        ("totp", account.enrollment_id, step),
        ("totp", account.enrollment_id, step + 1),
    ]


def test_wrong_passwords_and_codes_count_and_a_wait_refuses_before_any_check(
    code_database: CodeDatabase,
) -> None:
    """A wrong password is a wrong try of kind `password`, a wrong sign-in code one of kind
    `sign_in_code`, counted for the username (the session is the source); the 3rd starts the
    5-minute wait (429); during the wait a wrong password is refused with 429 before any check
    (not counted, review round 1) and so is the right answer; nothing is written."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3d-1.wrong")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    with pytest.raises(AuthenticationRejected):
        reauthenticate(flow, session, password=WRONG, code=code_for(account, step))
    with pytest.raises(AuthenticationRejected):
        reauthenticate(flow, session, code=wrong_code(account, step))
    with pytest.raises(AuthenticationRateLimited) as started:
        reauthenticate(flow, session, password=WRONG, code=code_for(account, step))
    assert started.value.retry_after_seconds == 300
    with pytest.raises(AuthenticationRateLimited):
        reauthenticate(flow, session, password=WRONG, code=code_for(account, step))
    with pytest.raises(AuthenticationRateLimited):
        reauthenticate(flow, session, code=code_for(account, step))
    assert read(code_database, TRIES_OF, username_key(account)) == [
        ("password",),
        ("sign_in_code",),
        ("password",),
    ]
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == []
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == [(step - 1,)]


@pytest.mark.parametrize(
    "case", ["no_factor", "recovery_code", "used_step", "signed_out", "unknown", "no_key"]
)
def test_a_reauthentication_without_the_right_factor_or_session_is_refused(
    code_database: CodeDatabase,
    case: str,
) -> None:
    """Refused and nothing written: an MFA account without a second factor or with a recovery
    code (the owner's answer names the sign-in code), a sign-in code of the step already used at
    sign-in (counted as a wrong code), a signed-out session, an unknown cookie, and the sign-in
    code without the protection key (unavailable)."""
    flow = flow_of(code_database)
    account = add_account(code_database, f"l3d-1.refused-{case}")
    step = fresh_step(code_database)
    # Review round 1: signed in with the previous step, so only `used_step` offers a used one.
    session = signed_in(flow, code_database, account, step - 1)
    refusal: type[Exception] = AuthenticationRejected
    method: str | None = "totp"
    code: str | None = code_for(account, step)
    if case == "no_factor":
        method, code = None, None
    elif case == "recovery_code":
        method, code = "recovery_code", "x" * 43
    elif case == "used_step":
        code = code_for(account, step - 1)
    elif case == "signed_out":
        flow.logout(session_token=session, request_id="n")
    elif case == "unknown":
        session = "u" * 43
    elif case == "no_key":
        flow = PostgresAuthenticationFlow(code_database.runtime_url)
        refusal = AuthenticationUnavailable
    with pytest.raises(refusal):
        reauthenticate(flow, session, method=method, code=code)
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == []
    expected_tries = [("sign_in_code",)] if case == "used_step" else []
    assert read(code_database, TRIES_OF, username_key(account)) == expected_tries


def test_an_account_without_mfa_reauthenticates_with_its_password_only(
    code_database: CodeDatabase,
) -> None:
    """A Staff account with MFA `optional` and no sign-in code reauthenticates with the password
    alone (method `password`); a second factor given anyway is refused; a wrong password is
    counted (review round 1); a second one within a minute answers 429, for that account only
    (review round 2)."""
    flow = flow_of(code_database)
    account = add_account(
        code_database, "l3d-1.staff", account_class="staff", mfa="optional", sign_in_code=False
    )
    result = flow.login(
        username=account.username, password=PASSWORD, request_source="l3d-1", request_id="p"
    )
    assert result.session_token is not None
    with pytest.raises(AuthenticationRejected):
        reauthenticate(flow, result.session_token, method="totp", code="123456")
    with pytest.raises(AuthenticationRejected):
        reauthenticate(flow, result.session_token, password=WRONG, method=None)
    assert read(code_database, TRIES_OF, username_key(account)) == [("password",)]
    first = flow.reauthenticate(
        session_token=result.session_token,
        password=PASSWORD,
        second_factor_method=None,
        second_factor_code=None,
        request_id="p",
    )
    assert first.session.reauthenticated_at is not None
    # Review round 2 (security S-3): a second password-only reauthentication of the account
    # within a minute answers 429 before any password check, a wrong password included, and
    # writes and counts nothing.
    for password in (PASSWORD, WRONG):
        with pytest.raises(AuthenticationRateLimited) as limited:
            reauthenticate(flow, result.session_token, password=password, method=None)
        assert limited.value.retry_after_seconds is not None
        assert 1 <= limited.value.retry_after_seconds <= 60
    assert read(code_database, TRIES_OF, username_key(account)) == [("password",)]
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == [("password", None, None)]
    # The minute is per account: another password-only account is not limited.
    neighbour = add_account(
        code_database,
        "l3d-1.staff-neighbour",
        account_class="staff",
        mfa="optional",
        sign_in_code=False,
    )
    other = flow.login(
        username=neighbour.username, password=PASSWORD, request_source="l3d-1", request_id="p"
    )
    assert other.session_token is not None
    reauthenticate(flow, other.session_token, method=None)
    assert read(code_database, REAUTHENTICATIONS_OF, neighbour.actor_id) == [
        ("password", None, None)
    ]


@pytest.mark.parametrize(
    "case", ["wait", "password", "sign_in_code", "account", "step_used", "staff_code_off"]
)
def test_a_change_before_the_reauthentication_refuses_and_writes_nothing(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """A change committed after the wait check, before the reauthentication's transaction: a
    wait that 3 parallel wrong tries started (429), a new password (the verifier comparison),
    the sign-in code turned off (its lock; for a Manager and, review round 1, for a Staff account
    with MFA `optional` whose session stays live), the account disabled (the guard) and the
    step used meanwhile (the used-step re-check, review round 1); no reauthentication or new
    step is written and the count is not cleared."""
    flow = flow_of(code_database)
    if case == "staff_code_off":
        account = add_account(
            code_database, "l3d-1.window-staff", account_class="staff", mfa="optional"
        )
    else:
        account = add_account(code_database, f"l3d-1.window-{case}")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    checked = flow._sign_in_waits.challenge_wait_seconds

    def checked_then_changed(username_digest: bytes, source_digest: bytes) -> int | None:
        waiting = checked(username_digest, source_digest)
        if case == "wait":
            with psycopg.connect(code_database.runtime_url) as connection:
                for _ in range(3):
                    connection.execute(
                        "SELECT app.record_sign_in_wrong_try(%s, %s, 'password')",
                        (username_digest, source_digest),
                    )
                    connection.commit()
        elif case == "step_used":
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(
                    "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)",
                    (account.enrollment_id, step),
                )
                connection.commit()
        else:
            statement, parameters = change_for(
                "sign_in_code" if case == "staff_code_off" else case, account
            )
            with psycopg.connect(code_database.owner_url) as connection:
                connection.execute(statement, parameters)
                connection.commit()
        return waiting

    monkeypatch.setattr(flow._sign_in_waits, "challenge_wait_seconds", checked_then_changed)
    refusal: type[Exception] = (
        AuthenticationRateLimited if case == "wait" else AuthenticationRejected
    )
    with pytest.raises(refusal):
        reauthenticate(flow, session, code=code_for(account, step))
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == []
    expected_steps = [(step - 1,), (step,)] if case == "step_used" else [(step - 1,)]
    assert read(code_database, USED_STEPS_OF, account.enrollment_id) == expected_steps
    assert read(code_database, CLEARS_OF, username_key(account)) == [(0,)]


def test_one_reauthentication_of_an_account_at_a_time(
    code_database: CodeDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (both reviewers): while one reauthentication of the account is checking
    its password, a second one is refused at once, without a password check and uncounted;
    the first is counted once."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3d-1.parallel")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    real = flow._password_service.verify_password
    calls: list[int] = []
    second: list[str] = []

    def checking(password: str, verifier: str) -> PasswordVerification:
        calls.append(1)
        if len(calls) == 1:
            try:
                reauthenticate(flow, session, password=WRONG, code=code_for(account, step))
            except AuthenticationRejected:
                second.append("rejected")
        return real(password, verifier)

    monkeypatch.setattr(flow._password_service, "verify_password", checking)
    with pytest.raises(AuthenticationRejected):
        reauthenticate(flow, session, password=WRONG, code=code_for(account, step))
    assert calls == [1] and second == ["rejected"]
    assert read(code_database, TRIES_OF, username_key(account)) == [("password",)]


def test_the_reauthentication_route_answers_the_session_and_a_new_csrf_cookie(
    code_database: CodeDatabase,
) -> None:
    """API-097 over HTTP: `POST /auth/reauthenticate` with the password and the sign-in code
    answers the session with `reauthenticated_at`, `Cache-Control: no-store`, a new CSRF cookie
    and the reauthentication cookie (review round 2); `GET /auth/session` shows the
    reauthentication only with that cookie; a wrong password answers 401."""
    flow = flow_of(code_database)
    app = create_app(
        Settings(database_url=SecretStr(code_database.runtime_url), allowed_browser_origin=ORIGIN),
        authentication_flow=flow,
    )
    account = add_account(code_database, "l3d-1.http")
    step = fresh_step(code_database)
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": account.username, "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": "l3d-1-http"},
        )
        assert login.status_code == 200
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies["__Host-prm_csrf"],
            "X-Request-ID": "l3d-1-http",
        }
        done = client.post(
            "/api/v1/auth/mfa/challenge",
            json={"method": "totp", "code": code_for(account, step - 1)},
            headers=headers,
        )
        assert done.status_code == 200
        headers["X-CSRF-Token"] = client.cookies["__Host-prm_csrf"]
        wrong = client.post(
            "/api/v1/auth/reauthenticate",
            json={"password": WRONG, "second_factor": {"method": "totp", "code": "000000"}},
            headers=headers,
        )
        assert wrong.status_code == 401
        before = client.cookies["__Host-prm_csrf"]
        answer = client.post(
            "/api/v1/auth/reauthenticate",
            json={
                "password": PASSWORD,
                "second_factor": {"method": "totp", "code": code_for(account, step)},
            },
            headers=headers,
        )
        assert answer.status_code == 200
        assert answer.json()["data"]["reauthenticated_at"] is not None
        assert answer.headers["Cache-Control"] == "no-store"
        assert client.cookies["__Host-prm_csrf"] != before
        # Review round 2 (security S-1): the separate reauthentication cookie. This browser's
        # session shows the reauthentication; a second browser with a copy of the session
        # cookie alone shows none.
        reauthentication_cookie = client.cookies["__Host-prm_reauth"]
        assert reauthentication_cookie not in answer.text
        session_cookie = client.cookies["__Host-prm_session"]
        mine = client.get("/api/v1/auth/session", headers={"X-Request-ID": "l3d-1-http"})
        assert mine.status_code == 200
        assert (
            mine.json()["data"]["reauthenticated_at"] == answer.json()["data"]["reauthenticated_at"]
        )
    with TestClient(app, base_url="https://testserver") as copied:
        copied.cookies.set("__Host-prm_session", session_cookie)
        theirs = copied.get("/api/v1/auth/session", headers={"X-Request-ID": "l3d-1-http"})
        assert theirs.status_code == 200
        assert theirs.json()["data"]["reauthenticated_at"] is None
        # A malformed reauthentication cookie never turns the live session away (round 2).
        copied.cookies.clear()
        for bad in ("", "x" * 129):
            answered = copied.get(
                "/api/v1/auth/session",
                headers={
                    "X-Request-ID": "l3d-1-http",
                    "Cookie": f"__Host-prm_session={session_cookie}; __Host-prm_reauth={bad}",
                },
            )
            assert answered.status_code == 200
            assert answered.json()["data"]["reauthenticated_at"] is None


def test_a_reauthentication_is_guarded_in_the_database(code_database: CodeDatabase) -> None:
    """DB-AUTH-004 (migration `20270203_191`): a row needs a live session of its own account; a
    `totp` row needs the account's active sign-in code with a step used since its transaction
    began (another account's code, a code turned off and a step used earlier are each refused
    alone, review round 1), one row per step; a `password` row is refused for an account that
    needs MFA (MFA `required`, or `optional` with an active code); rows never change and cannot
    be deleted or truncated; the runtime role writes only the listed columns on insert. The
    flow and a raw row are the positive controls."""
    flow = flow_of(code_database)
    account = add_account(code_database, "l3d-1.guard")
    other = add_account(code_database, "l3d-1.guard-other")
    step = fresh_step(code_database)
    session = signed_in(flow, code_database, account, step - 1)
    reauthenticate(flow, session, code=code_for(account, step))
    session_id = read(
        code_database,
        "SELECT session_id FROM app.browser_sessions WHERE token_verifier = %s",
        digest(session),
    )[0][0]
    revoked_id = uuid.uuid4()
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(
            ADD_SESSION, (revoked_id, account.actor_id, digest(f"r-{revoked_id}"), PROVENANCE)
        )
        connection.execute(
            "UPDATE app.browser_sessions SET revoked_by_actor_id = actor_id, "
            "revocation_reason = 'logout', revocation_provenance = 'l3d-1-test' "
            "WHERE session_id = %s",
            (revoked_id,),
        )
        connection.commit()
    add_row = (
        "INSERT INTO app.browser_session_reauthentications (reauthentication_id, session_id, "
        "actor_id, method, enrollment_id, time_step, token_verifier) "
        "VALUES (%s, %s, %s, %s, %s, %s, sha256(gen_random_uuid()::text::bytea))"
    )
    cases = (
        ((session_id, other.actor_id, "password", None, None), "live session of its account"),
        ((revoked_id, account.actor_id, "password", None, None), "live session of its account"),
        ((session_id, account.actor_id, "totp", account.enrollment_id, step), "step of its"),
        ((session_id, account.actor_id, "totp", other.enrollment_id, step), "step of its"),
        ((session_id, account.actor_id, "password", None, None), "needs MFA"),
    )
    for (target, actor_id, method, enrollment_id, time_step), message in cases:
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match=message):
                connection.execute(
                    add_row, (uuid.uuid4(), target, actor_id, method, enrollment_id, time_step)
                )
    for statement in (
        "UPDATE app.browser_session_reauthentications SET method = method WHERE actor_id = %s",
        "DELETE FROM app.browser_session_reauthentications WHERE actor_id = %s",
    ):
        with psycopg.connect(code_database.owner_url) as connection:
            with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
                connection.execute(statement, (account.actor_id,))
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="append-only"):
            connection.execute("TRUNCATE app.browser_session_reauthentications")
    with psycopg.connect(code_database.owner_url) as connection:
        privileges = connection.execute(
            "SELECT has_column_privilege('prm_runtime', "
            "'app.browser_session_reauthentications', 'time_step', 'INSERT'), "
            "has_column_privilege('prm_runtime', 'app.browser_session_reauthentications', "
            "'reauthenticated_at', 'INSERT'), has_column_privilege('prm_runtime', "
            "'app.browser_session_reauthentications', 'method', 'UPDATE'), "
            "has_table_privilege('prm_runtime', 'app.browser_session_reauthentications', "
            "'DELETE'), has_column_privilege('prm_runtime', "
            "'app.browser_session_reauthentications', 'token_verifier', 'INSERT'), "
            "has_column_privilege('prm_runtime', 'app.browser_session_reauthentications', "
            "'token_verifier', 'SELECT'), has_column_privilege('prm_runtime', "
            "'app.browser_session_reauthentications', 'token_verifier', 'UPDATE')"
        ).fetchone()
    assert privileges == (True, False, False, False, True, True, False)
    assert read(code_database, REAUTHENTICATIONS_OF, account.actor_id) == [
        ("totp", account.enrollment_id, step)
    ]
    # Review round 1: each `totp` condition alone, with a raw positive control, written as the
    # table owner in one transaction each (the step is used in the same transaction).
    other_step = fresh_step(code_database)
    other_session = signed_in(flow, code_database, other, other_step - 1)
    other_session_id = read(
        code_database,
        "SELECT session_id FROM app.browser_sessions WHERE token_verifier = %s",
        digest(other_session),
    )[0][0]
    use_step = "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)"
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        with pytest.raises(errors.IntegrityConstraintViolation, match="step of its"):
            connection.execute(
                add_row,
                (
                    uuid.uuid4(),
                    session_id,
                    account.actor_id,
                    "totp",
                    other.enrollment_id,
                    other_step,
                ),
            )
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        connection.execute(
            "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
            "disabled_by_actor_id = actor_id, disablement_provenance = 'l3d-1-test' "
            "WHERE enrollment_id = %s",
            (other.enrollment_id,),
        )
        with pytest.raises(errors.IntegrityConstraintViolation, match="step of its"):
            connection.execute(
                add_row,
                (
                    uuid.uuid4(),
                    other_session_id,
                    other.actor_id,
                    "totp",
                    other.enrollment_id,
                    other_step,
                ),
            )
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        row = (other_session_id, other.actor_id, "totp", other.enrollment_id, other_step)
        connection.execute(add_row, (uuid.uuid4(), *row))
        with pytest.raises(errors.UniqueViolation, match="one_per_step"):
            connection.execute(add_row, (uuid.uuid4(), *row))
    # Review round 2: one row per reauthentication cookie, and a digest of 32 bytes, each on a
    # raw row that passes the guard.
    add_row_with = (
        "INSERT INTO app.browser_session_reauthentications (reauthentication_id, session_id, "
        "actor_id, method, enrollment_id, time_step, token_verifier) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    taken = read(
        code_database,
        "SELECT token_verifier FROM app.browser_session_reauthentications WHERE actor_id = %s",
        account.actor_id,
    )[0][0]
    row = (other_session_id, other.actor_id, "totp", other.enrollment_id, other_step)
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        with pytest.raises(errors.UniqueViolation, match="one_per_cookie"):
            connection.execute(add_row_with, (uuid.uuid4(), *row, taken))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        with pytest.raises(errors.CheckViolation, match="token_verifier"):
            connection.execute(add_row_with, (uuid.uuid4(), *row, bytes(1)))
    with psycopg.connect(code_database.owner_url) as connection:
        connection.execute(use_step, (other.enrollment_id, other_step))
        connection.execute(
            add_row,
            (
                uuid.uuid4(),
                other_session_id,
                other.actor_id,
                "totp",
                other.enrollment_id,
                other_step,
            ),
        )
        connection.commit()
    assert read(code_database, REAUTHENTICATIONS_OF, other.actor_id) == [
        ("totp", other.enrollment_id, other_step)
    ]
    # The `password` refusal for an account with MFA `optional` and an active sign-in code.
    optional = add_account(
        code_database, "l3d-1.guard-optional", account_class="staff", mfa="optional"
    )
    optional_session = signed_in(flow, code_database, optional)
    optional_session_id = read(
        code_database,
        "SELECT session_id FROM app.browser_sessions WHERE token_verifier = %s",
        digest(optional_session),
    )[0][0]
    with psycopg.connect(code_database.owner_url) as connection:
        with pytest.raises(errors.IntegrityConstraintViolation, match="needs MFA"):
            connection.execute(
                add_row,
                (uuid.uuid4(), optional_session_id, optional.actor_id, "password", None, None),
            )


def test_the_session_reauthentication_migration_follows_l3c_2c_2_and_is_forward_only() -> None:
    """The migration chain: `20270203_191` follows `20270202_190` and has no downgrade."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
