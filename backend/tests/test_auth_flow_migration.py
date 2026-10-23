"""Login sub-slice L3a-1: password sign-in, the session read and sign-out on PostgreSQL.

DL-055, DL-056, DL-057, API-096, API-097, SEC-010, SEC-011, SEC-015, SEC-016, DB-AUTH-004. One
throwaway database at head; accounts and real Argon2id credentials are written as the table
owner, and every sign-in runs as the runtime role through `PostgresAuthenticationFlow`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
)
from property_rental.auth_flow import PostgresAuthenticationFlow
from property_rental.password_security import PasswordHashService
from property_rental.settings import Settings
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

PASSWORD = "correct horse battery staple"
ORIGIN = "https://property.test"
PROVENANCE = "login-slice-l3a-1-test"
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    f"lifecycle_state,mfa_policy_class,provenance) VALUES (%s,%s,%s,%s,%s,%s,'{PROVENANCE}')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    f"VALUES (%s,%s,'{PROVENANCE}')"
)
ADD_CREDENTIAL = (
    "INSERT INTO app.password_credentials(actor_id,verifier_encoding,algorithm,"
    "work_factor_metadata,provenance) VALUES (%s,%s,%s,%s::jsonb,'initial-credential')"
)
# A session row written as the table owner, its times taken back from the database clock.
ADD_OLD_SESSION = """
    INSERT INTO app.browser_sessions (
        session_id, actor_id, token_verifier, verifier_algorithm, created_at, last_activity_at,
        idle_expires_at, absolute_expires_at, creation_provenance
    )
    SELECT %s, %s, %s, 'sha256', moment.created, moment.active,
           LEAST(moment.active + interval '30 minutes', moment.created + interval '24 hours'),
           moment.created + interval '24 hours', 'login-slice-l3a-1-test'
    FROM (
        SELECT statement_timestamp() - %s::interval AS created,
               statement_timestamp() - %s::interval AS active
    ) AS moment
"""
SESSIONS_OF = (
    "SELECT token_verifier, revoked_at IS NOT NULL, revoked_by_actor_id, revocation_reason, "
    "creation_provenance FROM app.browser_sessions WHERE actor_id = %s ORDER BY created_at"
)


@dataclass(frozen=True)
class SignInDatabase:
    owner_url: str
    runtime_url: str
    accounts: dict[str, uuid.UUID]


@pytest.fixture(scope="module")
def sign_in_database(migrated_database_url: str) -> Iterator[SignInDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_auth_flow") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        credential = PasswordHashService().hash_password(PASSWORD)
        accounts: dict[str, uuid.UUID] = {}
        with psycopg.connect(temporary) as setup:
            for username, display_name, account_class, lifecycle, mfa in (
                ("sokha.chan", "Sokha Chan", "staff", "active", "optional"),
                ("dara.sok", "Dara Sok", "staff", "disabled", "optional"),
                ("vanna.lim", "Vanna Lim", None, "active", "optional"),
                ("owner.one", "Owner One", "owner", "active", "required"),
                ("manager.one", "Manager One", "manager", "active", "required"),
            ):
                actor_id = uuid.uuid4()
                setup.execute(
                    ADD_ACCOUNT,
                    (actor_id, username, display_name, display_name, lifecycle, mfa),
                )
                if account_class is not None:
                    setup.execute(ADD_CLASS, (actor_id, account_class))
                setup.execute(
                    ADD_CREDENTIAL,
                    (
                        actor_id,
                        credential.verifier_encoding,
                        credential.algorithm,
                        json.dumps(dict(credential.work_factor_metadata)),
                    ),
                )
                accounts[username] = actor_id
            setup.commit()
        yield SignInDatabase(temporary, runtime_url, accounts)


def sessions_of(database: SignInDatabase, actor_id: uuid.UUID) -> list[tuple[Any, ...]]:
    with psycopg.connect(database.owner_url) as connection:
        return connection.execute(SESSIONS_OF, (actor_id,)).fetchall()


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def test_a_staff_account_signs_in_reads_its_session_and_signs_out(
    sign_in_database: SignInDatabase,
) -> None:
    """A Staff account with MFA policy `optional` gets a session whose row keeps only the sha256
    digest of the cookie token, with its display name in the view and a new CSRF token; it reads
    the session and signs out (revoked by itself, reason `logout`); reading the session or
    signing out again gives the generic rejection."""
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    staff = sign_in_database.accounts["sokha.chan"]
    before = len(sessions_of(sign_in_database, staff))
    result = flow.login(
        username=" Sokha.Chan ", password=PASSWORD, request_source="desk", request_id="l3a-1"
    )
    assert result.phase is AuthenticationPhase.AUTHENTICATED
    assert result.session_token is not None and result.preauth_token is None
    assert len(result.csrf_token) >= 43 and result.csrf_token != result.session_token
    assert result.session is not None
    assert (result.session.actor_id, result.session.display_name) == (str(staff), "Sokha Chan")
    assert result.session.mfa_assurance == "none" and result.session.reauthenticated_at is None
    assert (
        result.session.absolute_expires_at - result.session.authenticated_at
        == (result.session.idle_expires_at - result.session.last_activity_at) * 48
    )
    # Review round 1: only the rows this test writes are compared, so the order of the tests in
    # the module does not matter.
    rows = sessions_of(sign_in_database, staff)[before:]
    assert [(bytes(row[0]), row[1], row[4]) for row in rows] == [
        (digest(result.session_token), False, "auth-login")
    ]
    assert result.session_token.encode("utf-8") not in bytes(rows[0][0])

    read = flow.inspect_session(session_token=result.session_token, request_id="l3a-1-read")
    assert read.actor_id == str(staff) and read.display_name == "Sokha Chan"
    assert read.last_activity_at == result.session.last_activity_at

    flow.logout(session_token=result.session_token, request_id="l3a-1-logout")
    rows = sessions_of(sign_in_database, staff)[before:]
    assert [(row[1], row[2], row[3]) for row in rows] == [(True, staff, "logout")]
    with pytest.raises(AuthenticationRejected):
        flow.inspect_session(session_token=result.session_token, request_id="l3a-1-again")
    with pytest.raises(AuthenticationRejected):
        flow.logout(session_token=result.session_token, request_id="l3a-1-again")
    for unknown in (secrets.token_urlsafe(32), "x" * 129, ""):
        with pytest.raises(AuthenticationRejected):
            flow.inspect_session(session_token=unknown, request_id="l3a-1-unknown")


def test_every_failed_sign_in_gives_the_same_rejection_and_writes_no_session(
    sign_in_database: SignInDatabase,
) -> None:
    """A wrong password, an unknown username, a disabled account and an account without a class
    are all refused with the one generic rejection, and no session is written."""
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    before = {
        name: len(sessions_of(sign_in_database, actor))
        for name, actor in sign_in_database.accounts.items()
    }
    for username, password in (
        ("sokha.chan", "wrong horse battery staple"),
        ("nobody.here", PASSWORD),
        ("dara.sok", PASSWORD),
        ("vanna.lim", PASSWORD),
    ):
        with pytest.raises(AuthenticationRejected) as caught:
            flow.login(
                username=username, password=password, request_source="desk", request_id="l3a-1"
            )
        assert str(caught.value) == ""
    after = {
        name: len(sessions_of(sign_in_database, actor))
        for name, actor in sign_in_database.accounts.items()
    }
    assert after == before


def test_an_account_that_needs_mfa_gets_no_session_before_the_challenge(
    sign_in_database: SignInDatabase,
) -> None:
    """DL-056: the Owner and a Manager (MFA policy `required`) get the phase `mfa_required` with a
    pre-authentication token and no session, no session row and no actor; the challenge answers
    unavailable until login sub-slice L3c."""
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    for username in ("owner.one", "manager.one"):
        result = flow.login(
            username=username, password=PASSWORD, request_source="desk", request_id="l3a-1"
        )
        assert result.phase is AuthenticationPhase.MFA_REQUIRED
        assert result.session is None and result.session_token is None
        assert result.preauth_token is not None and result.csrf_token
        assert sessions_of(sign_in_database, sign_in_database.accounts[username]) == []
        with pytest.raises(AuthenticationUnavailable):
            flow.complete_mfa(
                preauth_token=result.preauth_token,
                method="totp",
                code="123456",
                request_id="l3a-1",
            )


def test_a_session_ends_after_30_idle_minutes_and_after_24_hours(
    sign_in_database: SignInDatabase,
) -> None:
    """DL-057 by the database clock: a session last active 29 minutes ago is read; one last
    active 31 minutes ago is refused; one created 24 hours ago and last active 10 minutes ago is
    refused; neither refused session can be signed out, and the fresh one is."""
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    staff = sign_in_database.accounts["sokha.chan"]
    tokens = {}
    with psycopg.connect(sign_in_database.owner_url) as connection:
        for name, created, active in (
            ("fresh", "29 minutes", "29 minutes"),
            ("idle", "31 minutes", "31 minutes"),
            ("old", "24 hours", "10 minutes"),
        ):
            tokens[name] = secrets.token_urlsafe(32)
            connection.execute(
                ADD_OLD_SESSION, (uuid.uuid4(), staff, digest(tokens[name]), created, active)
            )
        connection.commit()
    read = flow.inspect_session(session_token=tokens["fresh"], request_id="l3a-1")
    assert read.actor_id == str(staff)
    for name in ("idle", "old"):
        with pytest.raises(AuthenticationRejected):
            flow.inspect_session(session_token=tokens[name], request_id="l3a-1")
        with pytest.raises(AuthenticationRejected):
            flow.logout(session_token=tokens[name], request_id="l3a-1")
    flow.logout(session_token=tokens["fresh"], request_id="l3a-1")


def test_the_sign_in_routes_use_secure_cookies_and_keep_secrets_out_of_answers_and_logs(
    sign_in_database: SignInDatabase,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Through `create_app` with the real flow: the session cookie is `__Host-`, `Secure`,
    `HttpOnly`, `SameSite=Lax`, path `/` and has no `Domain`; the token is never in a body; the
    answer is `no-store`; every rejection has the same 401 body; no token, password or username
    reaches the log; signing out clears the cookies."""
    caplog.set_level(logging.DEBUG)
    app = create_app(
        Settings(
            database_url=SecretStr(sign_in_database.runtime_url),
            allowed_browser_origin=ORIGIN,
        )
    )
    with TestClient(app, base_url="https://testserver") as client:
        rejected = []
        for username, password in (
            ("sokha.chan", "wrong horse battery staple"),
            ("nobody.here", PASSWORD),
            ("dara.sok", PASSWORD),
        ):
            answer = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
                headers={"Origin": ORIGIN, "X-Request-ID": "l3a-1-rejected"},
            )
            assert answer.status_code == 401
            rejected.append(answer.json())
        assert rejected[0] == rejected[1] == rejected[2]

        signed_in = client.post(
            "/api/v1/auth/login",
            json={"username": "sokha.chan", "password": PASSWORD},
            headers={"Origin": ORIGIN, "X-Request-ID": "l3a-1-login"},
        )
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.headers["Cache-Control"] == "no-store"
        assert signed_in.json()["data"]["session"]["display_name"] == "Sokha Chan"
        cookies = signed_in.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if value.startswith("__Host-prm_session="))
        token = session_cookie.split(";", 1)[0].split("=", 1)[1]
        attributes = {part.strip().lower() for part in session_cookie.split(";")[1:]}
        assert {"secure", "httponly", "samesite=lax", "path=/"} <= attributes
        assert not any(part.startswith("domain") for part in attributes)
        assert token not in signed_in.text
        csrf_cookie = next(value for value in cookies if value.startswith("__Host-prm_csrf="))
        csrf = csrf_cookie.split(";", 1)[0].split("=", 1)[1]

        assert client.cookies.get("__Host-prm_session") == token
        session = client.get("/api/v1/auth/session", headers={"X-Request-ID": "l3a-1-session"})
        assert session.status_code == 200
        assert session.headers["Cache-Control"] == "no-store"
        assert token not in session.text

        signed_out = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "X-Request-ID": "l3a-1-logout"},
        )
        assert signed_out.status_code == 204
        cleared = signed_out.headers.get_list("set-cookie")
        for name in ("__Host-prm_session=", "__Host-prm_preauth=", "__Host-prm_csrf="):
            assert any(value.startswith(name) and "max-age=0" in value.lower() for value in cleared)
        # The revoked token itself, sent again, is refused.
        client.cookies.clear()
        after = client.get(
            "/api/v1/auth/session",
            headers={"Cookie": f"__Host-prm_session={token}", "X-Request-ID": "l3a-1-after"},
        )
        assert after.status_code == 401
    for secret in (token, csrf, PASSWORD, "wrong horse battery staple", "sokha.chan"):
        assert secret not in caplog.text


def add_staff(database: SignInDatabase, username: str) -> uuid.UUID:
    """A fresh Staff account with MFA policy `optional` and the test password."""
    credential = PasswordHashService().hash_password(PASSWORD)
    actor_id = uuid.uuid4()
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(
            ADD_ACCOUNT, (actor_id, username, username, username, "active", "optional")
        )
        connection.execute(ADD_CLASS, (actor_id, "staff"))
        connection.execute(
            ADD_CREDENTIAL,
            (
                actor_id,
                credential.verifier_encoding,
                credential.algorithm,
                json.dumps(dict(credential.work_factor_metadata)),
            ),
        )
        connection.commit()
    return actor_id


def test_a_live_session_ends_when_its_account_is_disabled_or_needs_mfa(
    sign_in_database: SignInDatabase,
) -> None:
    """Review round 1: the session read checks the account on every read, so a session made
    before its account was disabled, or before its MFA policy was raised to `required`, is
    refused at the next read, even if no revocation reached it."""
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    disabled = add_staff(sign_in_database, "l3a-1.disabled")
    raised = add_staff(sign_in_database, "l3a-1.mfa")
    tokens = []
    for username in ("l3a-1.disabled", "l3a-1.mfa"):
        result = flow.login(
            username=username, password=PASSWORD, request_source="desk", request_id="l3a-1"
        )
        assert result.session_token is not None
        assert flow.inspect_session(session_token=result.session_token, request_id="l3a-1")
        tokens.append(result.session_token)
    with psycopg.connect(sign_in_database.owner_url) as connection:
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state = 'disabled' WHERE actor_id = %s",
            (disabled,),
        )
        connection.execute(
            "UPDATE app.user_accounts SET mfa_policy_class = 'required' WHERE actor_id = %s",
            (raised,),
        )
        connection.commit()
    for token in tokens:
        with pytest.raises(AuthenticationRejected):
            flow.inspect_session(session_token=token, request_id="l3a-1")


def test_a_password_reset_during_sign_in_leaves_no_session_made_with_the_old_password(
    sign_in_database: SignInDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1 (security): the password is checked, then the account's password is
    replaced before the session is written; the sign-in is refused and no session is written,
    because the session transaction checks that the current verifier is the one the password was
    checked against (a comparison since login sub-slice L3b, Q-2026-10-23-177 (a))."""
    actor_id = add_staff(sign_in_database, "l3a-1.reset")
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    replacement = PasswordHashService().hash_password("an entirely different passphrase")
    checked = flow._authentication.authenticate

    def check_then_reset(**kwargs: Any) -> Any:
        result = checked(**kwargs)
        with psycopg.connect(sign_in_database.owner_url) as connection:
            connection.execute(
                "UPDATE app.password_credentials SET verifier_encoding = %s, "
                "changed_by_actor_id = %s, provenance = 'l3a-1-reset-test' WHERE actor_id = %s",
                (replacement.verifier_encoding, actor_id, actor_id),
            )
            connection.commit()
        return result

    monkeypatch.setattr(flow._authentication, "authenticate", check_then_reset)
    with pytest.raises(AuthenticationRejected):
        flow.login(
            username="l3a-1.reset", password=PASSWORD, request_source="desk", request_id="l3a-1"
        )
    assert sessions_of(sign_in_database, actor_id) == []


def test_the_flood_guard_refuses_a_username_after_20_tries_and_a_source_after_100(
    sign_in_database: SignInDatabase,
) -> None:
    """Review round 1: the coarse per-process flood guard of this sub-slice refuses a username
    after 20 tries in 15 minutes, even with the right password, and a source after 100 tries,
    with the same rejection as a wrong password and no session.

    Login sub-slice L3b (the owner's wait rule, DL-081): the database count now answers first:
    the 3rd wrong try for the username starts a 5-minute wait and the 20th wrong try from one
    source a 15-minute wait, so the tries after them get the wait answer; the flood guard still
    refuses the 21st and the 101st try before the database is asked. The wait is kept in the
    database, so a new flow object still refuses the waiting username."""
    actor_id = add_staff(sign_in_database, "l3a-1.flood")
    flow = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    for attempt in range(20):
        # L3b: the 3rd wrong try starts the 5-minute wait of the owner's rule.
        refusal = AuthenticationRejected if attempt < 2 else AuthenticationRateLimited
        with pytest.raises(refusal):
            flow.login(
                username="l3a-1.flood",
                password="wrong horse battery staple",
                request_source=f"desk-{attempt}",
                request_id="l3a-1",
            )
    with pytest.raises(AuthenticationRejected):
        flow.login(
            username="l3a-1.flood", password=PASSWORD, request_source="desk", request_id="l3a-1"
        )
    assert sessions_of(sign_in_database, actor_id) == []

    other = PostgresAuthenticationFlow(sign_in_database.runtime_url)
    for attempt in range(100):
        # L3b: the 20th wrong try from one source starts its 15-minute wait.
        refusal = AuthenticationRejected if attempt < 19 else AuthenticationRateLimited
        with pytest.raises(refusal):
            other.login(
                username=f"nobody-{attempt}",
                password=PASSWORD,
                request_source="shared-source",
                request_id="l3a-1",
            )
    with pytest.raises(AuthenticationRejected):
        other.login(
            username="l3a-1.flood",
            password=PASSWORD,
            request_source="shared-source",
            request_id="l3a-1",
        )
    assert sessions_of(sign_in_database, actor_id) == []
    # L3b: the username's wait is in the database, so the new flow object still refuses it.
    with pytest.raises(AuthenticationRateLimited):
        other.login(
            username="l3a-1.flood", password=PASSWORD, request_source="desk", request_id="l3a-1"
        )
    assert sessions_of(sign_in_database, actor_id) == []
    # Another account still signs in from another source through the same flow object.
    add_staff(sign_in_database, "l3a-1.flood-other")
    signed_in = other.login(
        username="l3a-1.flood-other", password=PASSWORD, request_source="desk", request_id="l3a-1"
    )
    assert signed_in.session_token is not None
