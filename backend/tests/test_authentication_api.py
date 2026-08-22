"""API-096/097 authentication transport tests."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from property_rental.app import create_app
from property_rental.auth_api import (
    AuthenticationFlow,
    AuthenticationPhase,
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationResult,
    MfaEnrollmentResult,
    ReauthenticationResult,
    RecoveryCodeSetResult,
    SessionView,
)
from property_rental.identity import AuthenticatedActor
from property_rental.settings import Settings


@dataclass
class StubAuthenticationFlow(AuthenticationFlow):
    """Deterministic API test boundary with no credential or token persistence."""

    login_result: AuthenticationResult

    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        assert username == "operator"
        assert password == "correct horse battery staple"
        assert request_source == "127.0.0.1"
        assert request_id == "login-success"
        return self.login_result

    def complete_mfa(
        self,
        *,
        preauth_token: str,
        method: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise NotImplementedError

    def begin_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        request_id: str,
    ) -> MfaEnrollmentResult:
        raise NotImplementedError

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise NotImplementedError

    def inspect_session(self, *, session_token: str, request_id: str) -> SessionView:
        raise NotImplementedError

    def logout(self, *, session_token: str, request_id: str) -> None:
        raise NotImplementedError

    def reauthenticate(
        self,
        *,
        session_token: str,
        password: str,
        second_factor_method: str | None,
        second_factor_code: str | None,
        request_id: str,
    ) -> ReauthenticationResult:
        raise NotImplementedError

    def issue_recovery_codes(
        self,
        *,
        session_token: str,
        request_id: str,
    ) -> RecoveryCodeSetResult:
        raise NotImplementedError

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
    ) -> RecoveryCodeSetResult:
        raise NotImplementedError


class RejectingAuthenticationFlow(StubAuthenticationFlow):
    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise AuthenticationRejected


class RateLimitedAuthenticationFlow(StubAuthenticationFlow):
    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise AuthenticationRateLimited


def authenticated_result() -> AuthenticationResult:
    authenticated_at = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
    return AuthenticationResult(
        phase=AuthenticationPhase.AUTHENTICATED,
        session_token="session-token-secret",
        csrf_token="csrf-token-secret",
        session=SessionView(
            actor_id="opaque-actor",
            authenticated_at=authenticated_at,
            last_activity_at=authenticated_at,
            idle_expires_at=authenticated_at + timedelta(minutes=30),
            absolute_expires_at=authenticated_at + timedelta(hours=24),
            mfa_assurance="totp",
            reauthenticated_at=None,
        ),
    )


def mfa_required_result() -> AuthenticationResult:
    return AuthenticationResult(
        phase=AuthenticationPhase.MFA_REQUIRED,
        preauth_token="preauth-token-secret",
        csrf_token="csrf-token-secret",
    )


def request(
    app: FastAPI,
    method: Literal["GET", "POST"],
    path: str,
    *,
    json: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41000))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://property.test",
        ) as client:
            return await client.request(method, path, json=json, headers=headers)

    return asyncio.run(send())


def test_successful_local_login_sets_protected_session_and_csrf_cookies() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={"Origin": "https://property.test", "X-Request-ID": "login-success"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "data": {
            "phase": "authenticated",
            "session": {
                "actor_id": "opaque-actor",
                "authenticated_at": "2026-08-19T09:00:00Z",
                "last_activity_at": "2026-08-19T09:00:00Z",
                "idle_expires_at": "2026-08-19T09:30:00Z",
                "absolute_expires_at": "2026-08-20T09:00:00Z",
                "mfa_assurance": "totp",
                "reauthenticated_at": None,
            },
        },
        "meta": {"request_id": "login-success"},
    }
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if "__Host-prm_session=" in value)
    csrf_cookie = next(value for value in cookies if "__Host-prm_csrf=" in value)
    assert "session-token-secret" in session_cookie
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie
    assert "Domain=" not in session_cookie
    assert "csrf-token-secret" in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=strict" in csrf_cookie
    assert "session-token-secret" not in response.text
    assert "csrf-token-secret" not in response.text


def test_valid_password_requiring_mfa_sets_only_short_lived_preauthentication_cookie() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(mfa_required_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={"Origin": "https://property.test", "X-Request-ID": "login-success"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"phase": "mfa_required", "session": None}
    cookies = response.headers.get_list("set-cookie")
    preauth_cookie = next(value for value in cookies if "__Host-prm_preauth=" in value)
    assert "preauth-token-secret" in preauth_cookie
    assert "Max-Age=300" in preauth_cookie
    assert "Secure" in preauth_cookie
    assert "HttpOnly" in preauth_cookie
    assert "SameSite=strict" in preauth_cookie
    assert all("__Host-prm_session=" not in value or 'session=""' in value for value in cookies)


def test_mfa_required_login_expires_any_existing_authenticated_session() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(mfa_required_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={
            "Cookie": "__Host-prm_session=stale-session",
            "Origin": "https://property.test",
            "X-Request-ID": "login-success",
        },
    )

    assert any(
        '__Host-prm_session=""' in value and "Max-Age=0" in value
        for value in response.headers.get_list("set-cookie")
    )


def test_authenticated_login_expires_any_stale_preauthentication_capability() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={
            "Cookie": "__Host-prm_preauth=stale-preauth",
            "Origin": "https://property.test",
            "X-Request-ID": "login-success",
        },
    )

    assert any(
        '__Host-prm_preauth=""' in value and "Max-Age=0" in value
        for value in response.headers.get_list("set-cookie")
    )


def test_login_rejection_is_generic_and_sets_no_authentication_cookie() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=RejectingAuthenticationFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "unknown", "password": "wrong"},
        headers={"Origin": "https://property.test", "X-Request-ID": "login-rejected"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert "unknown" not in response.text
    assert "wrong" not in response.text
    assert response.headers.get_list("set-cookie") == []


def test_totp_challenge_requires_preauthentication_and_csrf_then_establishes_session() -> None:
    class MfaFlow(StubAuthenticationFlow):
        def complete_mfa(
            self,
            *,
            preauth_token: str,
            method: str,
            code: str,
            request_id: str,
        ) -> AuthenticationResult:
            assert preauth_token == "preauth-token-secret"
            assert method == "totp"
            assert code == "123456"
            assert request_id == "mfa-success"
            return authenticated_result()

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=MfaFlow(mfa_required_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/mfa/challenge",
        json={"method": "totp", "code": "123456"},
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "mfa-success",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["phase"] == "authenticated"
    cookies = response.headers.get_list("set-cookie")
    assert any("__Host-prm_session=session-token-secret" in value for value in cookies)
    assert any('__Host-prm_preauth=""' in value and "Max-Age=0" in value for value in cookies)


def test_recovery_code_challenge_is_transported_exactly_and_establishes_session() -> None:
    class RecoveryCodeFlow(StubAuthenticationFlow):
        def complete_mfa(
            self,
            *,
            preauth_token: str,
            method: str,
            code: str,
            request_id: str,
        ) -> AuthenticationResult:
            assert preauth_token == "preauth-token-secret"
            assert method == "recovery_code"
            assert code == "single-use-recovery-code"
            assert request_id == "recovery-success"
            return authenticated_result()

    response = request(
        create_app(
            Settings(allowed_browser_origin="https://property.test"),
            authentication_flow=RecoveryCodeFlow(mfa_required_result()),
        ),
        "POST",
        "/api/v1/auth/mfa/challenge",
        json={"method": "recovery_code", "code": "single-use-recovery-code"},
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "recovery-success",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["phase"] == "authenticated"


@pytest.mark.parametrize("method", ["totp", "recovery_code"])
def test_rejected_mfa_challenge_returns_generic_unauthorized(method: str) -> None:
    class RejectingMfaFlow(StubAuthenticationFlow):
        def complete_mfa(
            self,
            *,
            preauth_token: str,
            method: str,
            code: str,
            request_id: str,
        ) -> AuthenticationResult:
            raise AuthenticationRejected

    response = request(
        create_app(
            Settings(allowed_browser_origin="https://property.test"),
            authentication_flow=RejectingMfaFlow(mfa_required_result()),
        ),
        "POST",
        "/api/v1/auth/mfa/challenge",
        json={"method": method, "code": "incorrect-secret"},
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "mfa-rejected",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert "incorrect-secret" not in response.text
    assert response.headers.get_list("set-cookie") == []


def test_required_mfa_enrollment_returns_one_time_totp_provisioning_material() -> None:
    class EnrollmentFlow(StubAuthenticationFlow):
        def begin_mfa_enrollment(
            self,
            *,
            preauth_token: str,
            request_id: str,
        ) -> MfaEnrollmentResult:
            assert preauth_token == "preauth-token-secret"
            assert request_id == "enrollment-start"
            return MfaEnrollmentResult(
                provisioning_uri="otpauth://totp/Property:operator?secret=ONETIMESECRET"
            )

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=EnrollmentFlow(mfa_required_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/mfa/enrollment",
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "enrollment-start",
        },
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {
        "method": "totp",
        "provisioning_uri": "otpauth://totp/Property:operator?secret=ONETIMESECRET",
    }


def test_confirmed_mfa_enrollment_activates_totp_and_establishes_session() -> None:
    class EnrollmentConfirmationFlow(StubAuthenticationFlow):
        def confirm_mfa_enrollment(
            self,
            *,
            preauth_token: str,
            code: str,
            request_id: str,
        ) -> AuthenticationResult:
            assert preauth_token == "preauth-token-secret"
            assert code == "654321"
            assert request_id == "enrollment-confirm"
            return authenticated_result()

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=EnrollmentConfirmationFlow(mfa_required_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/mfa/enrollment/confirm",
        json={"code": "654321"},
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "enrollment-confirm",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["phase"] == "authenticated"
    assert any(
        "__Host-prm_session=session-token-secret" in value
        for value in response.headers.get_list("set-cookie")
    )


def test_authenticated_session_inspection_returns_only_bounded_non_secret_state() -> None:
    class InspectionFlow(StubAuthenticationFlow):
        def inspect_session(self, *, session_token: str, request_id: str) -> SessionView:
            assert session_token == "session-token-secret"
            assert request_id == "session-inspect"
            session = authenticated_result().session
            assert session is not None
            return session

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=InspectionFlow(authenticated_result()),
    )

    response = request(
        app,
        "GET",
        "/api/v1/auth/session",
        headers={
            "Cookie": "__Host-prm_session=session-token-secret",
            "X-Request-ID": "session-inspect",
        },
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"]["actor_id"] == "opaque-actor"
    assert set(response.json()["data"]) == {
        "actor_id",
        "authenticated_at",
        "last_activity_at",
        "idle_expires_at",
        "absolute_expires_at",
        "mfa_assurance",
        "reauthenticated_at",
    }
    assert "session-token-secret" not in response.text


def test_logout_requires_csrf_revokes_current_session_and_clears_browser_material() -> None:
    class LogoutFlow(StubAuthenticationFlow):
        def logout(self, *, session_token: str, request_id: str) -> None:
            assert session_token == "session-token-secret"
            assert request_id == "logout-success"

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=LogoutFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/logout",
        headers={
            "Cookie": (
                "__Host-prm_session=session-token-secret; "
                "__Host-prm_preauth=stale-preauth; "
                "__Host-prm_csrf=csrf-token-secret"
            ),
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "logout-success",
        },
    )

    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    assert any('__Host-prm_session=""' in value and "Max-Age=0" in value for value in cookies)
    assert any('__Host-prm_preauth=""' in value and "Max-Age=0" in value for value in cookies)
    assert any('__Host-prm_csrf=""' in value and "Max-Age=0" in value for value in cookies)


def test_reauthentication_records_additional_evidence_without_granting_authority() -> None:
    class ReauthenticationFlow(StubAuthenticationFlow):
        def reauthenticate(
            self,
            *,
            session_token: str,
            password: str,
            second_factor_method: str | None,
            second_factor_code: str | None,
            request_id: str,
        ) -> ReauthenticationResult:
            assert session_token == "session-token-secret"
            assert password == "correct horse battery staple"
            assert second_factor_method == "totp"
            assert second_factor_code == "123456"
            assert request_id == "reauth-success"
            session = authenticated_result().session
            assert session is not None
            return ReauthenticationResult(
                session=SessionView(
                    actor_id=session.actor_id,
                    authenticated_at=session.authenticated_at,
                    last_activity_at=session.last_activity_at,
                    idle_expires_at=session.idle_expires_at,
                    absolute_expires_at=session.absolute_expires_at,
                    mfa_assurance=session.mfa_assurance,
                    reauthenticated_at=datetime(2026, 8, 19, 9, 10, tzinfo=UTC),
                ),
                csrf_token="rotated-csrf-secret",
            )

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        actor_resolver=lambda _: AuthenticatedActor(actor_id="actor-1"),
        authentication_flow=ReauthenticationFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/reauthenticate",
        json={
            "password": "correct horse battery staple",
            "second_factor": {"method": "totp", "code": "123456"},
        },
        headers={
            "Cookie": "__Host-prm_session=session-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "reauth-success",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["reauthenticated_at"] == "2026-08-19T09:10:00Z"
    assert "capabilities" not in response.text
    assert "roles" not in response.text
    assert any(
        "__Host-prm_csrf=rotated-csrf-secret" in value
        for value in response.headers.get_list("set-cookie")
    )

    forbidden_administration = request(
        app,
        "GET",
        "/api/v1/properties/property-main/users",
        headers={"X-Request-ID": "reauth-still-requires-capability"},
    )
    assert forbidden_administration.status_code == 403
    assert forbidden_administration.json()["error"]["code"] == "FORBIDDEN"


def test_recovery_code_sets_are_returned_once_only_through_protected_session_routes() -> None:
    prior_set_id = UUID("11111111-1111-4111-8111-111111111111")
    replacement_set_id = UUID("22222222-2222-4222-8222-222222222222")

    class RecoveryCodesFlow(StubAuthenticationFlow):
        def issue_recovery_codes(
            self,
            *,
            session_token: str,
            request_id: str,
        ) -> RecoveryCodeSetResult:
            assert session_token == "session-token-secret"
            assert request_id == "issue-recovery-codes"
            return RecoveryCodeSetResult(set_id=prior_set_id, codes=("one-time-1", "one-time-2"))

        def regenerate_recovery_codes(
            self,
            *,
            session_token: str,
            prior_set_id: UUID,
            request_id: str,
        ) -> RecoveryCodeSetResult:
            assert session_token == "session-token-secret"
            assert prior_set_id == UUID("11111111-1111-4111-8111-111111111111")
            assert request_id == "replace-recovery-codes"
            return RecoveryCodeSetResult(
                set_id=replacement_set_id,
                codes=("replacement-1", "replacement-2"),
            )

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=RecoveryCodesFlow(authenticated_result()),
    )
    protected_headers = {
        "Cookie": ("__Host-prm_session=session-token-secret; __Host-prm_csrf=csrf-token-secret"),
        "Origin": "https://property.test",
        "X-CSRF-Token": "csrf-token-secret",
    }
    issued = request(
        app,
        "POST",
        "/api/v1/auth/recovery-codes",
        headers={**protected_headers, "X-Request-ID": "issue-recovery-codes"},
    )
    replaced = request(
        app,
        "POST",
        "/api/v1/auth/recovery-codes/regenerate",
        json={"prior_set_id": str(prior_set_id)},
        headers={**protected_headers, "X-Request-ID": "replace-recovery-codes"},
    )

    assert issued.status_code == 200
    assert issued.headers["Cache-Control"] == "no-store"
    assert issued.json()["data"] == {
        "set_id": str(prior_set_id),
        "codes": ["one-time-1", "one-time-2"],
    }
    assert replaced.status_code == 200
    assert replaced.headers["Cache-Control"] == "no-store"
    assert replaced.json()["data"] == {
        "set_id": str(replacement_set_id),
        "codes": ["replacement-1", "replacement-2"],
    }


def test_recovery_code_routes_reject_missing_browser_protection_before_flow() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    response = request(app, "POST", "/api/v1/auth/recovery-codes")

    assert response.status_code == 403


def test_authentication_routes_fail_closed_when_no_runtime_flow_is_configured() -> None:
    response = request(
        create_app(Settings(allowed_browser_origin="https://property.test")),
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "not-used"},
        headers={"Origin": "https://property.test", "X-Request-ID": "auth-unavailable"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["meta"] == {"request_id": "auth-unavailable"}


def test_rate_limited_login_returns_generic_429_without_account_disclosure() -> None:
    response = request(
        create_app(
            Settings(allowed_browser_origin="https://property.test"),
            authentication_flow=RateLimitedAuthenticationFlow(authenticated_result()),
        ),
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "not-used"},
        headers={"Origin": "https://property.test", "X-Request-ID": "auth-rate-limit"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert "operator" not in response.text


def test_authentication_mutations_reject_missing_origin_and_csrf_evidence() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    login = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={"X-Request-ID": "origin-missing"},
    )
    logout = request(
        app,
        "POST",
        "/api/v1/auth/logout",
        headers={
            "Cookie": "__Host-prm_session=session-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-Request-ID": "csrf-missing",
        },
    )

    assert login.status_code == 403
    assert logout.status_code == 403


def test_authentication_mutations_reject_wrong_origin_and_mismatched_csrf_evidence() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    wrong_origin = request(
        app,
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={"Origin": "https://attacker.test", "X-Request-ID": "origin-wrong"},
    )
    mismatched_csrf = request(
        app,
        "POST",
        "/api/v1/auth/logout",
        headers={
            "Cookie": "__Host-prm_session=session-token-secret; __Host-prm_csrf=cookie-token",
            "Origin": "https://property.test",
            "X-CSRF-Token": "different-header-token",
            "X-Request-ID": "csrf-mismatch",
        },
    )

    assert wrong_origin.status_code == 403
    assert mismatched_csrf.status_code == 403


def test_sms_mfa_is_not_an_accepted_authentication_method() -> None:
    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=StubAuthenticationFlow(authenticated_result()),
    )

    response = request(
        app,
        "POST",
        "/api/v1/auth/mfa/challenge",
        json={"method": "sms", "code": "123456"},
        headers={
            "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
            "Origin": "https://property.test",
            "X-CSRF-Token": "csrf-token-secret",
            "X-Request-ID": "unsupported-factor",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "sms" not in response.text
