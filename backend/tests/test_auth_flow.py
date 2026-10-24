"""Login sub-slice L3a-1 unit tests: the session token digest, the bounded sign-in input and the
methods that stay unavailable until L3c and L3d (DL-081, API-096, DB-AUTH-004)."""

import hashlib
import hmac
from urllib.parse import parse_qs, unquote, urlsplit
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
from property_rental.auth_flow import (
    PostgresAuthenticationFlow,
    provisioning_uri,
    session_token_digest,
    sign_in_source_digest,
    sign_in_username_digest,
)
from property_rental.settings import Settings
from property_rental.totp_security import TotpSecret

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


def test_the_wrong_try_keys_are_sha256_digests_of_the_username_and_the_source() -> None:
    """Login sub-slice L3b: the database count keeps only sha256 digests, with a different
    prefix for a username and a source, so the same text never gives the same key."""
    assert sign_in_username_digest("sokha") == hashlib.sha256(b"username:sokha").digest()
    assert sign_in_source_digest("10.0.0.7") == hashlib.sha256(b"source:10.0.0.7").digest()
    assert sign_in_username_digest("desk") != sign_in_source_digest("desk")
    assert len(sign_in_username_digest("u" * 128)) == 32


def test_the_keyed_wrong_try_digests_are_hmac_sha256_under_the_derived_key() -> None:
    """Login sub-slice L3c-1 (review round 1): with a key the digests are HMAC-SHA256 of the same
    prefixed text, and differ from the plain ones."""
    key = bytes(range(32))
    username = sign_in_username_digest("sokha", key)
    source = sign_in_source_digest("10.0.0.7", key)
    assert username == hmac.new(key, b"username:sokha", hashlib.sha256).digest()
    assert source == hmac.new(key, b"source:10.0.0.7", hashlib.sha256).digest()
    assert username != sign_in_username_digest("sokha")
    assert source != sign_in_source_digest("10.0.0.7")


def test_the_provisioning_link_of_a_new_sign_in_code_is_the_standard_otpauth_link() -> None:
    """Login sub-slice L3c-2b, UI-110: the issuer and the username are the label, both
    percent-encoded (a space or Khmer letters cannot break the link); the Base32 secret, SHA-1,
    6 digits and 30 seconds are the stored parameters."""
    secret = TotpSecret.from_bytes(bytes(range(20)))
    link = urlsplit(provisioning_uri("sokha chan ស", secret))
    assert (link.scheme, link.netloc) == ("otpauth", "totp")
    assert link.path == "/CHETANA%20Residence:sokha%20chan%20%E1%9E%9F"
    assert unquote(link.path) == "/CHETANA Residence:sokha chan ស"
    assert parse_qs(link.query, strict_parsing=True) == {
        "secret": [secret.get_base32_value()],
        "issuer": ["CHETANA Residence"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }
