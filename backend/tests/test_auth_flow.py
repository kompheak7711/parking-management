"""Login sub-slice L3a-1 unit tests: the session token digest, the bounded sign-in input and the
methods that stay unavailable until L3c and L3d (DL-081, API-096, DB-AUTH-004)."""

import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationRejected,
    AuthenticationUnavailable,
    LoginRequest,
)
from property_rental.auth_flow import PostgresAuthenticationFlow, session_token_digest
from property_rental.settings import Settings

ORIGIN = "https://property.test"


def test_the_session_token_digest_is_sha256_and_a_long_or_empty_token_is_refused() -> None:
    token = "t" * 43
    assert session_token_digest(token) == hashlib.sha256(token.encode("utf-8")).digest()
    assert len(session_token_digest("x" * 128)) == 32
    for refused in ("", "x" * 129):
        with pytest.raises(AuthenticationRejected):
            session_token_digest(refused)


def test_the_sign_in_username_is_at_most_128_characters() -> None:
    """The longest saved username is 128 characters (L2c note), so the NFC step of the sign-in
    lookup never runs on a long input."""
    assert LoginRequest(username="u" * 128, password="p").username == "u" * 128
    with pytest.raises(ValidationError):
        LoginRequest(username="u" * 129, password="p")


def test_the_mfa_reauthentication_and_recovery_code_methods_stay_unavailable() -> None:
    """Until login sub-slices L3c and L3d, these methods answer unavailable (review round 1: the
    test does not claim that no connection is opened)."""
    flow = PostgresAuthenticationFlow("postgresql://unused.invalid/unused")
    calls = (
        lambda: flow.complete_mfa(preauth_token="p", method="totp", code="1", request_id="r"),
        lambda: flow.begin_mfa_enrollment(preauth_token="p", request_id="r"),
        lambda: flow.confirm_mfa_enrollment(preauth_token="p", code="123456", request_id="r"),
        lambda: flow.reauthenticate(
            session_token="s",
            password="p",
            second_factor_method=None,
            second_factor_code=None,
            request_id="r",
        ),
        lambda: flow.issue_recovery_codes(session_token="s", request_id="r"),
        lambda: flow.regenerate_recovery_codes(
            session_token="s", prior_set_id=uuid4(), request_id="r"
        ),
    )
    for call in calls:
        with pytest.raises(AuthenticationUnavailable):
            call()


def test_a_database_that_cannot_be_reached_answers_unavailable() -> None:
    """Review round 1: sign-in, the session read and sign-out fail closed with 503 when the
    database cannot be reached; no answer says whether the account exists."""
    unreachable = "postgresql://prm@127.0.0.1:1/unused"
    flow = PostgresAuthenticationFlow(unreachable)
    with pytest.raises(AuthenticationUnavailable):
        flow.login(username="sokha.chan", password="p", request_source="desk", request_id="r")
    with pytest.raises(AuthenticationUnavailable):
        flow.inspect_session(session_token="t" * 43, request_id="r")
    with pytest.raises(AuthenticationUnavailable):
        flow.logout(session_token="t" * 43, request_id="r")

    app = create_app(Settings(database_url=SecretStr(unreachable), allowed_browser_origin=ORIGIN))
    with TestClient(app, base_url="https://testserver") as client:
        answer = client.post(
            "/api/v1/auth/login",
            json={"username": "sokha.chan", "password": "p"},
            headers={"Origin": ORIGIN},
        )
        assert answer.status_code == 503
        session = client.get(
            "/api/v1/auth/session", headers={"Cookie": "__Host-prm_session=" + "t" * 43}
        )
        assert session.status_code == 503
