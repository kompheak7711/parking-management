"""Local authentication HTTP surface and secure browser transport."""

import hmac
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.api import ResponseMeta
from property_rental.settings import Settings

SESSION_COOKIE_NAME = "__Host-prm_session"
PREAUTH_COOKIE_NAME = "__Host-prm_preauth"
CSRF_COOKIE_NAME = "__Host-prm_csrf"
# Set only by a successful reauthentication (login sub-slice L3d-1, review round 2, owner answer
# of 2026-10-24 to Q-2026-10-24-183); the server keeps only its sha256 digest. It lives as long
# as the reauthentication window of Q-2026-10-21-157 (a), which L3d-2 checks on the database clock.
REAUTHENTICATION_COOKIE_NAME = "__Host-prm_reauth"
REAUTHENTICATION_COOKIE_MAX_AGE_SECONDS = 15 * 60


class AuthenticationPhase(StrEnum):
    """Externally safe next phase after valid local credentials."""

    AUTHENTICATED = "authenticated"
    MFA_REQUIRED = "mfa_required"
    MFA_ENROLLMENT_REQUIRED = "mfa_enrollment_required"
    # A one-time password of the Owner's reset is changed first (login sub-slice L4).
    PASSWORD_CHANGE_REQUIRED = "password_change_required"


@dataclass(frozen=True, slots=True)
class SessionView:
    """Bounded non-secret browser-session inspection state."""

    actor_id: str
    authenticated_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    mfa_assurance: Literal["none", "totp", "recovery_code"]
    reauthenticated_at: datetime | None
    # The signed-in person's display name, for the shell (login sub-slice L3a-1).
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """Secret-bearing service result consumed only by browser transport."""

    phase: AuthenticationPhase
    session_token: str | None = field(default=None, repr=False)
    preauth_token: str | None = field(default=None, repr=False)
    csrf_token: str = field(default="", repr=False)
    session: SessionView | None = None
    # A sign-in with the sign-in code also counts as a reauthentication (login sub-slice L3d-2).
    reauthentication_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class MfaEnrollmentResult:
    """One-time TOTP provisioning material returned by the application service."""

    provisioning_uri: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.provisioning_uri.startswith("otpauth://totp/"):
            raise ValueError("invalid TOTP provisioning material")


@dataclass(frozen=True, slots=True)
class ReauthenticationResult:
    """Recent-authentication evidence and rotated browser CSRF material."""

    session: SessionView
    csrf_token: str = field(repr=False)
    reauthentication_token: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class RecoveryCodeSetResult:
    """One-time recovery-code material returned by a protected service boundary."""

    set_id: UUID
    codes: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.codes or len(self.codes) > 20 or len(set(self.codes)) != len(self.codes):
            raise ValueError("invalid recovery-code presentation")
        if any(not code or len(code) > 256 or not code.isprintable() for code in self.codes):
            raise ValueError("invalid recovery-code presentation")


class AuthenticationFlow(Protocol):
    """Application boundary that atomically performs authentication commands."""

    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult: ...

    def complete_mfa(
        self,
        *,
        preauth_token: str,
        method: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult: ...

    def begin_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        request_id: str,
    ) -> MfaEnrollmentResult: ...

    def change_password(
        self,
        *,
        preauth_token: str,
        new_password: str,
        request_id: str,
    ) -> AuthenticationResult: ...

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult: ...

    def inspect_session(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> SessionView: ...

    def logout(self, *, session_token: str, request_id: str) -> None: ...

    def reauthenticate(
        self,
        *,
        session_token: str,
        password: str,
        second_factor_method: str | None,
        second_factor_code: str | None,
        request_id: str,
    ) -> ReauthenticationResult: ...

    def issue_recovery_codes(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult: ...

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult: ...


class AuthenticationRejected(RuntimeError):
    """Generic credential or MFA rejection without account details."""


class AuthenticationRateLimited(RuntimeError):
    """Generic account-and-source authentication rate-limit signal.

    `retry_after_seconds` is the seconds left of a sign-in wait (login sub-slice L3b), the same
    for a known and an unknown username.
    """

    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__("authentication rate limited")
        self.retry_after_seconds = retry_after_seconds


class AuthenticationUnavailable(RuntimeError):
    """Fail-closed signal when atomic authentication persistence is unavailable."""


class NewPasswordRejected(RuntimeError):
    """The new password does not meet the shared rule or is the one-time password itself
    (login sub-slice L4); the answer names the rule, never the reason."""


class UnavailableAuthenticationFlow:
    """Expose the stable API while refusing authentication without a runtime adapter."""

    @staticmethod
    def _unavailable() -> None:
        raise AuthenticationUnavailable

    def login(
        self,
        *,
        username: str,
        password: str,
        request_source: str,
        request_id: str,
    ) -> AuthenticationResult:
        self._unavailable()
        raise AssertionError

    def complete_mfa(
        self,
        *,
        preauth_token: str,
        method: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        self._unavailable()
        raise AssertionError

    def begin_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        request_id: str,
    ) -> MfaEnrollmentResult:
        self._unavailable()
        raise AssertionError

    def change_password(
        self,
        *,
        preauth_token: str,
        new_password: str,
        request_id: str,
    ) -> AuthenticationResult:
        self._unavailable()
        raise AssertionError

    def confirm_mfa_enrollment(
        self,
        *,
        preauth_token: str,
        code: str,
        request_id: str,
    ) -> AuthenticationResult:
        self._unavailable()
        raise AssertionError

    def inspect_session(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> SessionView:
        self._unavailable()
        raise AssertionError

    def logout(self, *, session_token: str, request_id: str) -> None:
        self._unavailable()

    def reauthenticate(
        self,
        *,
        session_token: str,
        password: str,
        second_factor_method: str | None,
        second_factor_code: str | None,
        request_id: str,
    ) -> ReauthenticationResult:
        self._unavailable()
        raise AssertionError

    def issue_recovery_codes(
        self,
        *,
        session_token: str,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        self._unavailable()
        raise AssertionError

    def regenerate_recovery_codes(
        self,
        *,
        session_token: str,
        prior_set_id: UUID,
        request_id: str,
        reauthentication_token: str | None = None,
    ) -> RecoveryCodeSetResult:
        self._unavailable()
        raise AssertionError


class LoginRequest(BaseModel):
    """Bounded local credential input."""

    model_config = ConfigDict(extra="forbid")

    # At most 128 characters, the longest saved username (login sub-slice L3a-1; L2c note), so
    # the NFC step of the sign-in lookup never runs on a long input.
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChangeRequest(BaseModel):
    """The new password that replaces a one-time password (login sub-slice L4); the rule is
    checked by the flow, so a refusal names the rule."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=1024, repr=False)


class MfaChallengeRequest(BaseModel):
    """Bounded standards-based or one-time recovery challenge input."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["totp", "recovery_code"]
    code: str = Field(min_length=1, max_length=256)


class MfaEnrollmentConfirmationRequest(BaseModel):
    """Exact TOTP proof used to activate a pending enrollment."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=8, pattern=r"^[0-9]+$")


class ReauthenticationFactor(BaseModel):
    """Optional additional factor for a high-risk reauthentication policy."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["totp", "recovery_code"]
    code: str = Field(min_length=1, max_length=256)


class ReauthenticationRequest(BaseModel):
    """Current-session password proof plus optional additional factor."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)
    second_factor: ReauthenticationFactor | None = None


class RecoveryCodeRegenerationRequest(BaseModel):
    """Identify the exact active set replaced by a protected regeneration."""

    model_config = ConfigDict(extra="forbid")

    prior_set_id: UUID


class SessionData(BaseModel):
    """Canonical non-secret session representation."""

    model_config = ConfigDict(frozen=True)

    actor_id: str
    authenticated_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    mfa_assurance: Literal["none", "totp", "recovery_code"]
    reauthenticated_at: datetime | None
    display_name: str | None = None


class AuthenticationData(BaseModel):
    """Safe authentication phase and optional established session."""

    model_config = ConfigDict(frozen=True)

    phase: AuthenticationPhase
    session: SessionData | None = None


class AuthenticationResponse(BaseModel):
    """Canonical authentication resource envelope."""

    model_config = ConfigDict(frozen=True)

    data: AuthenticationData
    meta: ResponseMeta


class SessionResponse(BaseModel):
    """Canonical established browser-session envelope."""

    model_config = ConfigDict(frozen=True)

    data: SessionData
    meta: ResponseMeta


class MfaEnrollmentData(BaseModel):
    """One-time standards-based provisioning response."""

    model_config = ConfigDict(frozen=True)

    method: Literal["totp"] = "totp"
    provisioning_uri: str


class MfaEnrollmentResponse(BaseModel):
    """Canonical one-time enrollment envelope."""

    model_config = ConfigDict(frozen=True)

    data: MfaEnrollmentData
    meta: ResponseMeta


class RecoveryCodeSetData(BaseModel):
    """Secret-bearing one-time recovery-code response; never persisted by the UI."""

    model_config = ConfigDict(frozen=True)

    set_id: UUID
    # Review round 1 (security): the codes never appear in a printed model.
    codes: tuple[str, ...] = Field(min_length=1, max_length=20, repr=False)


class RecoveryCodeSetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: RecoveryCodeSetData
    meta: ResponseMeta


def _require_browser_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.allowed_browser_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _request_source(request: Request) -> str:
    return request.client.host if request.client is not None else "unavailable"


def _require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        cookie_token is None
        or header_token is None
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _set_secret_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    httponly: bool,
    samesite: Literal["lax", "strict"],
    max_age: int | None = None,
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        secure=True,
        httponly=httponly,
        samesite=samesite,
        path="/",
        max_age=max_age,
    )


def _set_reauthentication_cookie(response: Response, token: str | None) -> None:
    """The reauthentication cookie of a sign-in with the sign-in code (login sub-slice L3d-2);
    a sign-in code challenge or set-up without one (a recovery code) clears any cookie an earlier
    session left (review round 1); the cookie is bound to its session anyway."""
    if token:
        _set_secret_cookie(
            response,
            name=REAUTHENTICATION_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="strict",
            max_age=REAUTHENTICATION_COOKIE_MAX_AGE_SECONDS,
        )
    else:
        response.delete_cookie(REAUTHENTICATION_COOKIE_NAME, path="/", secure=True, httponly=True)


def _signed_in_or_next_step(
    result: AuthenticationResult, request: Request, response: Response
) -> AuthenticationResponse:
    """The answer of a checked password (a sign-in, or the change of a one-time password): the
    session cookie, or the pre-authentication cookie of the next step (the password change, the
    sign-in code or its set-up), and a new CSRF cookie."""
    if not result.csrf_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    response.headers["Cache-Control"] = "no-store"
    if result.phase is AuthenticationPhase.AUTHENTICATED:
        if result.session_token is None or result.session is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=True, httponly=True)
        _set_secret_cookie(
            response,
            name=SESSION_COOKIE_NAME,
            value=result.session_token,
            httponly=True,
            samesite="lax",
        )
    else:
        if result.preauth_token is None or result.session is not None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, httponly=True)
        _set_secret_cookie(
            response,
            name=PREAUTH_COOKIE_NAME,
            value=result.preauth_token,
            httponly=True,
            samesite="strict",
            # The password change step lasts 10 minutes (login sub-slice L4).
            max_age=600 if result.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED else 300,
        )
    _set_secret_cookie(
        response,
        name=CSRF_COOKIE_NAME,
        value=result.csrf_token,
        httponly=False,
        samesite="strict",
    )
    return AuthenticationResponse(
        data=AuthenticationData(
            phase=result.phase,
            session=(
                SessionData.model_validate(result.session, from_attributes=True)
                if result.session is not None
                else None
            ),
        ),
        meta=ResponseMeta(request_id=request.state.request_id),
    )


def create_auth_router(settings: Settings, flow: AuthenticationFlow) -> APIRouter:
    """Create local authentication routes around an atomic application boundary."""
    router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

    @router.post(
        "/login",
        response_model=AuthenticationResponse,
        summary="Authenticate a local human account",
    )
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> AuthenticationResponse:
        _require_browser_origin(request, settings)
        try:
            result = flow.login(
                username=payload.username,
                password=payload.password,
                request_source=_request_source(request),
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        return _signed_in_or_next_step(result, request, response)

    @router.post(
        "/password-change",
        response_model=AuthenticationResponse,
        summary="Replace a one-time password before the sign-in continues",
    )
    def change_password(
        payload: PasswordChangeRequest,
        request: Request,
        response: Response,
    ) -> AuthenticationResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        preauth_token = request.cookies.get(PREAUTH_COOKIE_NAME)
        if preauth_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.change_password(
                preauth_token=preauth_token,
                new_password=payload.new_password,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        if result.phase is AuthenticationPhase.PASSWORD_CHANGE_REQUIRED:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return _signed_in_or_next_step(result, request, response)

    @router.post(
        "/mfa/challenge",
        response_model=AuthenticationResponse,
        summary="Complete a password-verified MFA challenge",
    )
    def complete_mfa(
        payload: MfaChallengeRequest,
        request: Request,
        response: Response,
    ) -> AuthenticationResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        preauth_token = request.cookies.get(PREAUTH_COOKIE_NAME)
        if preauth_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.complete_mfa(
                preauth_token=preauth_token,
                method=payload.method,
                code=payload.code,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        if (
            result.phase is not AuthenticationPhase.AUTHENTICATED
            or result.session_token is None
            or result.session is None
            or not result.csrf_token
        ):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response.headers["Cache-Control"] = "no-store"
        _set_secret_cookie(
            response,
            name=SESSION_COOKIE_NAME,
            value=result.session_token,
            httponly=True,
            samesite="lax",
        )
        _set_secret_cookie(
            response,
            name=CSRF_COOKIE_NAME,
            value=result.csrf_token,
            httponly=False,
            samesite="strict",
        )
        response.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=True, httponly=True)
        _set_reauthentication_cookie(response, result.reauthentication_token)
        return AuthenticationResponse(
            data=AuthenticationData(
                phase=result.phase,
                session=SessionData.model_validate(result.session, from_attributes=True),
            ),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/mfa/enrollment",
        response_model=MfaEnrollmentResponse,
        summary="Begin required TOTP enrollment",
    )
    def begin_mfa_enrollment(
        request: Request,
        response: Response,
    ) -> MfaEnrollmentResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        preauth_token = request.cookies.get(PREAUTH_COOKIE_NAME)
        if preauth_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.begin_mfa_enrollment(
                preauth_token=preauth_token,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        response.headers["Cache-Control"] = "no-store"
        return MfaEnrollmentResponse(
            data=MfaEnrollmentData(provisioning_uri=result.provisioning_uri),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/mfa/enrollment/confirm",
        response_model=AuthenticationResponse,
        summary="Confirm and activate pending TOTP enrollment",
    )
    def confirm_mfa_enrollment(
        payload: MfaEnrollmentConfirmationRequest,
        request: Request,
        response: Response,
    ) -> AuthenticationResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        preauth_token = request.cookies.get(PREAUTH_COOKIE_NAME)
        if preauth_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.confirm_mfa_enrollment(
                preauth_token=preauth_token,
                code=payload.code,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        if (
            result.phase is not AuthenticationPhase.AUTHENTICATED
            or result.session_token is None
            or result.session is None
            or not result.csrf_token
        ):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response.headers["Cache-Control"] = "no-store"
        _set_secret_cookie(
            response,
            name=SESSION_COOKIE_NAME,
            value=result.session_token,
            httponly=True,
            samesite="lax",
        )
        _set_secret_cookie(
            response,
            name=CSRF_COOKIE_NAME,
            value=result.csrf_token,
            httponly=False,
            samesite="strict",
        )
        response.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=True, httponly=True)
        _set_reauthentication_cookie(response, result.reauthentication_token)
        return AuthenticationResponse(
            data=AuthenticationData(
                phase=result.phase,
                session=SessionData.model_validate(result.session, from_attributes=True),
            ),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.get(
        "/session",
        response_model=SessionResponse,
        summary="Inspect the current authenticated browser session",
    )
    def inspect_session(request: Request, response: Response) -> SessionResponse:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            session = flow.inspect_session(
                session_token=session_token,
                request_id=request.state.request_id,
                reauthentication_token=request.cookies.get(REAUTHENTICATION_COOKIE_NAME),
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        response.headers["Cache-Control"] = "no-store"
        return SessionResponse(
            data=SessionData.model_validate(session, from_attributes=True),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        response_model=None,
        summary="Revoke the current browser session",
    )
    def logout(request: Request, response: Response) -> Response:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            flow.logout(
                session_token=session_token,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        response.headers["Cache-Control"] = "no-store"
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, httponly=True)
        response.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=True, httponly=True)
        response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=True)
        response.delete_cookie(REAUTHENTICATION_COOKIE_NAME, path="/", secure=True, httponly=True)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @router.post(
        "/reauthenticate",
        response_model=SessionResponse,
        summary="Record recent authentication for high-risk administration",
    )
    def reauthenticate(
        payload: ReauthenticationRequest,
        request: Request,
        response: Response,
    ) -> SessionResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        factor = payload.second_factor
        try:
            result = flow.reauthenticate(
                session_token=session_token,
                password=payload.password,
                second_factor_method=factor.method if factor is not None else None,
                second_factor_code=factor.code if factor is not None else None,
                request_id=request.state.request_id,
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        if not result.csrf_token or not result.reauthentication_token:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response.headers["Cache-Control"] = "no-store"
        _set_secret_cookie(
            response,
            name=CSRF_COOKIE_NAME,
            value=result.csrf_token,
            httponly=False,
            samesite="strict",
        )
        _set_reauthentication_cookie(response, result.reauthentication_token)
        return SessionResponse(
            data=SessionData.model_validate(result.session, from_attributes=True),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/recovery-codes",
        response_model=RecoveryCodeSetResponse,
        summary="Issue recovery codes through a protected authenticated flow",
    )
    def issue_recovery_codes(
        request: Request,
        response: Response,
    ) -> RecoveryCodeSetResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.issue_recovery_codes(
                session_token=session_token,
                request_id=request.state.request_id,
                reauthentication_token=request.cookies.get(REAUTHENTICATION_COOKIE_NAME),
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        response.headers["Cache-Control"] = "no-store"
        return RecoveryCodeSetResponse(
            data=RecoveryCodeSetData(set_id=result.set_id, codes=result.codes),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/recovery-codes/regenerate",
        response_model=RecoveryCodeSetResponse,
        summary="Atomically replace an active recovery-code set",
    )
    def regenerate_recovery_codes(
        payload: RecoveryCodeRegenerationRequest,
        request: Request,
        response: Response,
    ) -> RecoveryCodeSetResponse:
        _require_browser_origin(request, settings)
        _require_csrf(request)
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        try:
            result = flow.regenerate_recovery_codes(
                session_token=session_token,
                prior_set_id=payload.prior_set_id,
                request_id=request.state.request_id,
                reauthentication_token=request.cookies.get(REAUTHENTICATION_COOKIE_NAME),
            )
        except AuthenticationRejected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from None
        response.headers["Cache-Control"] = "no-store"
        return RecoveryCodeSetResponse(
            data=RecoveryCodeSetData(set_id=result.set_id, codes=result.codes),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    return router
