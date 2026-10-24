"""API-096/097 authentication transport tests."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from property_rental.app import NEW_PASSWORD_RULE_MESSAGE, create_app
from property_rental.auth_api import (
    AuthenticationFlow,
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
from property_rental.identity import AuthenticatedActor
from property_rental.settings import Settings
from property_rental.totp_qr import provisioning_qr_svg


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

    def change_password(
        self,
        *,
        preauth_token: str,
        new_password: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise NotImplementedError

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise NotImplementedError

    def inspect_session(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> SessionView:
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
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        raise NotImplementedError

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        raise NotImplementedError

    def live_recovery_code_set(
        self, *, session_token: str, request_id: str
    ) -> RecoveryCodeSetSummary | None:
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


def reauthentication_cookies(response: httpx.Response) -> list[str]:
    """The reauthentication cookies a response sets (login sub-slices L3d-1 and L3d-2)."""
    return [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith("__Host-prm_reauth=")
    ]


def assert_sign_in_reauthentication_cookie(response: httpx.Response) -> None:
    """Login sub-slice L3d-2 (Q-2026-10-24-184): a sign-in with the sign-in code also sets the
    reauthentication cookie: HttpOnly, Secure, SameSite=Strict, the whole site, 15 minutes;
    never in the body."""
    cookies = reauthentication_cookies(response)
    assert len(cookies) == 1
    assert cookies[0].startswith("__Host-prm_reauth=sign-in-reauthentication-secret;")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=900"):
        assert attribute in cookies[0]
    assert "sign-in-reauthentication-secret" not in response.text


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
                # Login sub-slice L3a-1 (approved plan): the session shows the display name.
                "display_name": None,
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
            return replace(
                authenticated_result(),
                reauthentication_token="sign-in-reauthentication-secret",
            )

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
    assert_sign_in_reauthentication_cookie(response)


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
    # A recovery code sign-in is not a reauthentication (login sub-slice L3d-2): it only clears
    # a reauthentication cookie an earlier session left (review round 1).
    cleared = reauthentication_cookies(response)
    assert len(cleared) == 1 and cleared[0].startswith('__Host-prm_reauth="";')
    assert "Max-Age=0" in cleared[0]


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
        "qr_code_svg": provisioning_qr_svg("otpauth://totp/Property:operator?secret=ONETIMESECRET"),
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
            return replace(
                authenticated_result(),
                reauthentication_token="sign-in-reauthentication-secret",
            )

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
    assert_sign_in_reauthentication_cookie(response)


def test_authenticated_session_inspection_returns_only_bounded_non_secret_state() -> None:
    class InspectionFlow(StubAuthenticationFlow):
        def inspect_session(
            self,
            *,
            session_token: str,
            request_id: str,
            reauthentication_token: str | None = None,
        ) -> SessionView:
            assert session_token == "session-token-secret"
            assert request_id == "session-inspect"
            # The reauthentication cookie is passed on (login sub-slice L3d-1, review round 2).
            assert reauthentication_token == "reauthentication-token-secret"
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
            "Cookie": (
                "__Host-prm_session=session-token-secret; "
                "__Host-prm_reauth=reauthentication-token-secret"
            ),
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
        "display_name",
    }
    assert "session-token-secret" not in response.text
    assert "reauthentication-token-secret" not in response.text


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
    assert any('__Host-prm_reauth=""' in value and "Max-Age=0" in value for value in cookies)


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
                reauthentication_token="reauthentication-token-secret",
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
    # The separate reauthentication cookie (login sub-slice L3d-1, review round 2): HttpOnly,
    # Secure, SameSite=Strict, the whole site, 15 minutes; never in the body.
    reauthentication_cookie = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith("__Host-prm_reauth=")
    ]
    assert len(reauthentication_cookie) == 1
    assert reauthentication_cookie[0].startswith("__Host-prm_reauth=reauthentication-token-secret;")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=900"):
        assert attribute in reauthentication_cookie[0]
    assert "reauthentication-token-secret" not in response.text

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
            reauthentication_token: str | None = None,
        ) -> RecoveryCodeSetResult:
            assert session_token == "session-token-secret"
            assert request_id == "issue-recovery-codes"
            # Login sub-slice L3d-2b: the reauthentication cookie is passed on.
            assert reauthentication_token == "reauthentication-token-secret"
            return RecoveryCodeSetResult(set_id=prior_set_id, codes=("one-time-1", "one-time-2"))

        def regenerate_recovery_codes(
            self,
            *,
            session_token: str,
            prior_set_id: UUID,
            request_id: str,
            reauthentication_token: str | None = None,
        ) -> RecoveryCodeSetResult:
            assert session_token == "session-token-secret"
            assert reauthentication_token == "reauthentication-token-secret"
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
        "Cookie": (
            "__Host-prm_session=session-token-secret; __Host-prm_csrf=csrf-token-secret; "
            "__Host-prm_reauth=reauthentication-token-secret"
        ),
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


def test_the_live_recovery_code_set_is_read_without_codes_with_no_store() -> None:
    """Login sub-slice L6 (API-098): `GET /auth/recovery-codes` answers the live set's id,
    time, origin and usable count, or null; no session cookie or a refused session is 401."""
    made = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
    summaries: list[RecoveryCodeSetSummary | None] = [
        RecoveryCodeSetSummary(
            set_id=UUID("33333333-3333-4333-8333-333333333333"),
            created_at=made,
            made_by="other",
            usable_count=7,
        ),
        None,
    ]

    class LiveSetFlow(StubAuthenticationFlow):
        def live_recovery_code_set(
            self, *, session_token: str, request_id: str
        ) -> RecoveryCodeSetSummary | None:
            if session_token != "session-token-secret":
                raise AuthenticationRejected
            assert request_id == "live-set"
            return summaries.pop(0)

    app = create_app(
        Settings(allowed_browser_origin="https://property.test"),
        authentication_flow=LiveSetFlow(authenticated_result()),
    )
    headers = {"Cookie": "__Host-prm_session=session-token-secret", "X-Request-ID": "live-set"}

    live = request(app, "GET", "/api/v1/auth/recovery-codes", headers=headers)
    none = request(app, "GET", "/api/v1/auth/recovery-codes", headers=headers)
    unknown = request(
        app,
        "GET",
        "/api/v1/auth/recovery-codes",
        headers={"Cookie": "__Host-prm_session=other", "X-Request-ID": "live-set"},
    )
    missing = request(app, "GET", "/api/v1/auth/recovery-codes")

    assert live.status_code == 200
    assert live.headers["Cache-Control"] == "no-store"
    assert live.json()["data"] == {
        "set_id": "33333333-3333-4333-8333-333333333333",
        "created_at": "2026-10-24T09:00:00Z",
        "made_by": "other",
        "usable_count": 7,
    }
    assert none.status_code == 200 and none.json()["data"] is None
    assert (unknown.status_code, missing.status_code) == (401, 401)


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


class WaitingAuthenticationFlow(StubAuthenticationFlow):
    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        raise AuthenticationRateLimited(300)


def test_a_sign_in_wait_answers_429_with_retry_after_and_no_store() -> None:
    """Login sub-slice L3b: the wait answer is the generic 429 body with the seconds left in
    `Retry-After`, `no-store`, and nothing about the account."""
    response = request(
        create_app(
            Settings(allowed_browser_origin="https://property.test"),
            authentication_flow=WaitingAuthenticationFlow(authenticated_result()),
        ),
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "not-used"},
        headers={"Origin": "https://property.test", "X-Request-ID": "auth-wait"},
    )

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "RATE_LIMITED",
        "message": "Too many requests.",
        "fields": [],
        "rule_ids": [],
        "current_version": None,
    }
    assert response.headers["Retry-After"] == "300"
    assert response.headers["Cache-Control"] == "no-store"
    assert "operator" not in response.text and "set-cookie" not in response.headers


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


CHANGE_HEADERS = {
    "Cookie": "__Host-prm_preauth=preauth-token-secret; __Host-prm_csrf=csrf-token-secret",
    "Origin": "https://property.test",
    "X-CSRF-Token": "csrf-token-secret",
    "X-Request-ID": "password-change",
}
NEW_PASSWORD = "a new long password of mine"


def password_change_result() -> AuthenticationResult:
    return AuthenticationResult(
        phase=AuthenticationPhase.PASSWORD_CHANGE_REQUIRED,
        preauth_token="preauth-token-secret",
        csrf_token="csrf-token-secret",
    )


class PasswordChangeFlow(StubAuthenticationFlow):
    """Answers the password change with `change_result`, or raises it; records the calls."""

    def __init__(self, change_result: AuthenticationResult | Exception) -> None:
        super().__init__(password_change_result())
        self.change_result = change_result
        self.changes: list[tuple[str, str, str]] = []

    def change_password(
        self,
        *,
        preauth_token: str,
        new_password: str,
        request_id: str,
    ) -> AuthenticationResult:
        self.changes.append((preauth_token, new_password, request_id))
        if isinstance(self.change_result, Exception):
            raise self.change_result
        return self.change_result


def change_app(flow: AuthenticationFlow) -> FastAPI:
    return create_app(
        Settings(allowed_browser_origin="https://property.test"), authentication_flow=flow
    )


def test_a_one_time_password_sign_in_asks_for_a_new_password_for_10_minutes() -> None:
    """Login sub-slice L4 (owner answer (a) to Q-2026-10-21-153, Q-2026-10-24-185): the right
    one-time password gives no session, only the pre-authentication cookie of the password
    change, for 10 minutes, and any session cookie is cleared."""
    response = request(
        change_app(StubAuthenticationFlow(password_change_result())),
        "POST",
        "/api/v1/auth/login",
        json={"username": "operator", "password": "correct horse battery staple"},
        headers={"Origin": "https://property.test", "X-Request-ID": "login-success"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {"phase": "password_change_required", "session": None}
    cookies = response.headers.get_list("set-cookie")
    preauth_cookie = next(value for value in cookies if "__Host-prm_preauth=" in value)
    for attribute in ("preauth-token-secret", "Max-Age=600", "HttpOnly", "SameSite=strict"):
        assert attribute in preauth_cookie
    assert any('__Host-prm_session=""' in value for value in cookies)
    assert "preauth-token-secret" not in response.text


@pytest.mark.parametrize(
    ("next_step", "cookie", "max_age"),
    [
        (authenticated_result(), "__Host-prm_session=session-token-secret", None),
        (mfa_required_result(), "__Host-prm_preauth=preauth-token-secret", "Max-Age=300"),
    ],
)
def test_the_password_change_continues_the_sign_in_with_the_next_step(
    next_step: AuthenticationResult, cookie: str, max_age: str | None
) -> None:
    """Login sub-slice L4: the new password goes to the flow exactly, with the
    pre-authentication cookie; the answer is the session, or the next step (the sign-in code or
    its set-up) with a 5-minute cookie, never cached and never showing the password."""
    flow = PasswordChangeFlow(next_step)
    response = request(
        change_app(flow),
        "POST",
        "/api/v1/auth/password-change",
        json={"new_password": NEW_PASSWORD},
        headers=CHANGE_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"]["phase"] == next_step.phase.value
    assert flow.changes == [("preauth-token-secret", NEW_PASSWORD, "password-change")]
    set_cookie = next(value for value in response.headers.get_list("set-cookie") if cookie in value)
    assert max_age is None or max_age in set_cookie
    assert NEW_PASSWORD not in response.text


def test_a_refused_new_password_names_the_rule_and_other_refusals_stay_generic() -> None:
    """Login sub-slice L4: a new password against the rule (length, blocklist, the account's
    names, the one-time password itself) answers 422 `PASSWORD_RULE` naming only the field;
    a wrong or old step answers a generic 401; a flow that answers the change step again fails
    closed (503); none of them shows the password."""
    refused = request(
        change_app(PasswordChangeFlow(NewPasswordRejected())),
        "POST",
        "/api/v1/auth/password-change",
        json={"new_password": NEW_PASSWORD},
        headers=CHANGE_HEADERS,
    )
    assert refused.status_code == 422
    assert refused.headers["Cache-Control"] == "no-store"
    assert refused.json()["error"]["code"] == "PASSWORD_RULE"
    assert refused.json()["error"]["fields"] == ["new_password"]
    # Review rounds 2 and 3: the one message the screen also shows, word for word
    # (`PASSWORD_RULE_MESSAGE` in authClient.ts).
    assert (
        refused.json()["error"]["message"]
        == NEW_PASSWORD_RULE_MESSAGE
        == (
            "Choose a password of 15 to 128 characters that is not a common password, not your "
            "name and not the one-time password."
        )
    )
    assert NEW_PASSWORD not in refused.text

    for result, status_code in (
        (AuthenticationRejected(), 401),
        (password_change_result(), 503),
    ):
        response = request(
            change_app(PasswordChangeFlow(result)),
            "POST",
            "/api/v1/auth/password-change",
            json={"new_password": NEW_PASSWORD},
            headers=CHANGE_HEADERS,
        )
        assert response.status_code == status_code
        assert NEW_PASSWORD not in response.text
        assert all(
            "session-token-secret" not in value for value in response.headers.get_list("set-cookie")
        )


def test_the_password_change_needs_origin_csrf_and_its_step_before_the_flow() -> None:
    """Login sub-slice L4: without the browser origin, the CSRF pair or the
    pre-authentication cookie, or with an old request shape, nothing reaches the flow."""
    flow = PasswordChangeFlow(authenticated_result())
    app = change_app(flow)
    cases: tuple[tuple[dict[str, str], dict[str, object], int], ...] = (
        ({**CHANGE_HEADERS, "Origin": "https://other.test"}, {"new_password": NEW_PASSWORD}, 403),
        ({**CHANGE_HEADERS, "X-CSRF-Token": "other"}, {"new_password": NEW_PASSWORD}, 403),
        (
            {**CHANGE_HEADERS, "Cookie": "__Host-prm_csrf=csrf-token-secret"},
            {"new_password": NEW_PASSWORD},
            401,
        ),
        (CHANGE_HEADERS, {"new_password": ""}, 422),
        (CHANGE_HEADERS, {"new_password": "x" * 1025}, 422),
        (CHANGE_HEADERS, {"new_password": NEW_PASSWORD, "password": NEW_PASSWORD}, 422),
    )
    for headers, payload, status_code in cases:
        response = request(
            app, "POST", "/api/v1/auth/password-change", json=payload, headers=headers
        )
        assert response.status_code == status_code, (headers, payload)
        assert NEW_PASSWORD not in response.text
    assert flow.changes == []


def test_the_password_change_answers_a_wait_with_429_and_an_outage_with_503() -> None:
    """Login sub-slice L4 review round 1: a sign-in wait during the change answers 429 with
    Retry-After and no-store, and an unavailable database 503, both without the
    password."""
    for failure, status_code in (
        (AuthenticationRateLimited(300), 429),
        (AuthenticationUnavailable(), 503),
    ):
        response = request(
            change_app(PasswordChangeFlow(failure)),
            "POST",
            "/api/v1/auth/password-change",
            json={"new_password": NEW_PASSWORD},
            headers=CHANGE_HEADERS,
        )
        assert response.status_code == status_code
        assert NEW_PASSWORD not in response.text
        if status_code == 429:
            assert response.headers["Retry-After"] == "300"
            assert response.headers["Cache-Control"] == "no-store"
