"""API-079/080 account and configurable capability administration surface."""

import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Final, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from property_rental.api import ResponseMeta
from property_rental.auth_api import (
    CSRF_COOKIE_NAME,
    REAUTHENTICATION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    ObjectScope,
    is_authorized,
)
from property_rental.settings import Settings
from property_rental.visible_text import (
    HIDDEN_REASON_CHARACTERS,
    tidy_spaces,
    without_zero_width_spaces,
)

ACCESS_ADMIN_CAPABILITY: Final = "identity.manage_access"
USER_ACCOUNT_OBJECT_TYPE: Final = "user_account"
ROLE_BUNDLE_OBJECT_TYPE: Final = "role_bundle"


def _without_zero_width_spaces(value: object) -> object:
    # Q-2026-10-22-169 (a): U+200B is removed before the trim and the length rule, so the
    # length counts the characters that are saved.
    return without_zero_width_spaces(value) if isinstance(value, str) else value


def _tidied_name(value: object) -> object:
    # Q-2026-10-22-170 (a): a name typed with odd or double spaces is tidied, not refused; U+200B
    # is removed and the spaces tidied before the trim and the length rule, so the length counts
    # the characters that are saved.
    return tidy_spaces(without_zero_width_spaces(value)) if isinstance(value, str) else value


BoundedName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    BeforeValidator(_tidied_name),
]
# A reason is free text (DL-074 answer 10) kept in the audit history: no control character, line
# or paragraph separator, direction mark or other hidden character that could hide or reorder
# what the history shows (Q-2026-10-22-169 (a)). U+200B is removed; U+200C and U+200D, which
# Khmer text uses, and the emoji variation selector U+FE0F stay allowed, but none of them counts
# as a visible character (review round 2 of sub-slice L2c).
INVISIBLE_KEPT_IN_REASONS: Final = dict.fromkeys((0x200C, 0x200D, 0xFE0F))


def _visible_reason(value: str) -> str:
    if HIDDEN_REASON_CHARACTERS.search(value):
        raise ValueError("a reason has no control, line-break, direction or hidden characters")
    if not value.translate(INVISIBLE_KEPT_IN_REASONS).strip():
        raise ValueError("a reason needs at least one visible character")
    return value


BoundedReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    BeforeValidator(_without_zero_width_spaces),
    AfterValidator(_visible_reason),
]
AccountClass = Literal["owner", "manager", "staff"]
CreatableAccountClass = Literal["manager", "staff"]
CapabilityIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$"),
]
PropertyIdentifier = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"),
]


@dataclass(frozen=True, slots=True)
class OneTimePasswordView:
    """A one-time password the app made (login sub-slice L4, owner answer (a) to
    Q-2026-10-21-153): answered once to the Owner, never stored or printed."""

    value: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UserAccountView:
    """Safe administrative account state without credentials or session material."""

    user_id: UUID
    property_id: str
    username: str
    display_name: str
    audit_name: str
    lifecycle_state: Literal["active", "disabled"]
    mfa_policy_class: Literal["required", "optional"]
    version: int
    account_class: AccountClass | None
    settings_access: bool
    # Only in the answer of a create, or of a Staff account's MFA turned off (login sub-slice
    # L4): the one-time password given in the same step.
    one_time_password: OneTimePasswordView | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class CapabilityView:
    """One configured capability-catalog entry."""

    capability_id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class RoleBundleView:
    """A configurable name mapped to capability identifiers."""

    role_bundle_id: UUID
    property_id: str
    name: str
    capability_ids: tuple[str, ...]
    version: int


@dataclass(frozen=True, slots=True)
class RoleAssignmentView:
    """Committed assignment of a configured bundle to an account."""

    user_id: UUID
    role_bundle_id: UUID
    property_id: str


@dataclass(frozen=True, slots=True)
class AuthorizationHistoryView:
    """Bounded secret-free authorization event exposed to an authorized administrator."""

    event_id: UUID
    property_id: str
    occurred_at: datetime
    action: str
    actor_id: str
    target_id: str
    outcome: Literal["completed", "rejected"]


@dataclass(frozen=True, slots=True)
class AdministrativeRecoveryView:
    """Non-secret result of an audited Owner-authorized account recovery."""

    user_id: UUID
    password_changed: bool
    mfa_reset: bool
    sessions_revoked: int
    one_time_password: OneTimePasswordView = field(repr=False)


@dataclass(frozen=True, slots=True)
class AdministrationAuditContext:
    """Evidence that every mutation must persist as an immutable atomic audit event.

    The browser's session and reauthentication cookies travel with it, never shown, so the
    flow can check a recent reauthentication in the action's own transaction (login sub-slice
    L3d-2, owner answer (a) to Q-2026-10-21-157).
    """

    actor_id: str
    request_id: str
    session_token: str | None = field(default=None, repr=False)
    reauthentication_token: str | None = field(default=None, repr=False)


class AccessAdministrationFlow(Protocol):
    """Atomic administration boundary with mandatory immutable mutation auditing.

    Implementations must commit each mutation and its ``audit_context`` event in one
    transaction. Account disablement and role-bundle capability reduction must also
    revoke every applicable session in that same transaction.
    """

    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]: ...

    def create_user(
        self,
        *,
        property_id: str,
        username: str,
        display_name: str,
        audit_name: str,
        account_class: CreatableAccountClass,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView: ...

    def user_property_id(self, *, user_id: UUID) -> str | None: ...

    def update_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        expected_version: int,
        display_name: str | None,
        audit_name: str | None,
        lifecycle_state: Literal["disabled"] | None,
        mfa_policy_class: Literal["required", "optional"] | None,
        revoke_applicable_sessions_if_disabled: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView: ...

    def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        audit_context: AdministrationAuditContext,
    ) -> int: ...

    def list_capabilities(
        self,
        *,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[CapabilityView, ...], str | None]: ...

    def list_role_bundles(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[RoleBundleView, ...], str | None]: ...

    def create_role_bundle(
        self,
        *,
        property_id: str,
        name: str,
        capability_ids: tuple[str, ...],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView: ...

    def role_bundle_property_id(self, *, role_bundle_id: UUID) -> str | None: ...

    def update_role_bundle(
        self,
        *,
        role_bundle_id: UUID,
        property_id: str,
        expected_version: int,
        name: str | None,
        capability_ids: tuple[str, ...] | None,
        revoke_affected_sessions_on_capability_reduction: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView: ...

    def assign_role_bundle(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView: ...

    def remove_role_assignment(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView: ...

    def give_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView: ...

    def remove_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView: ...

    def list_authorization_history(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[AuthorizationHistoryView, ...], str | None]: ...

    def administratively_recover_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reset_mfa: bool,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> AdministrativeRecoveryView: ...


class AccessAdministrationUnavailable(RuntimeError):
    """Fail-closed signal when audited administration persistence is unavailable."""


class AccessAdministrationNotFound(RuntimeError):
    """Requested account or role bundle does not exist."""


class AccessAdministrationConflict(RuntimeError):
    """Requested administration mutation conflicts with current state."""


class AccessAdministrationRejected(RuntimeError):
    """A refused administration request with a stable code and a fixed plain message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message


class UnavailableAccessAdministrationFlow:
    """Expose the stable contract while refusing work without a runtime adapter."""

    @staticmethod
    def _unavailable() -> None:
        raise AccessAdministrationUnavailable

    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        self._unavailable()
        raise AssertionError

    def create_user(
        self,
        *,
        property_id: str,
        username: str,
        display_name: str,
        audit_name: str,
        account_class: CreatableAccountClass,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self._unavailable()
        raise AssertionError

    def user_property_id(self, *, user_id: UUID) -> str | None:
        self._unavailable()
        raise AssertionError

    def update_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        expected_version: int,
        display_name: str | None,
        audit_name: str | None,
        lifecycle_state: Literal["disabled"] | None,
        mfa_policy_class: Literal["required", "optional"] | None,
        revoke_applicable_sessions_if_disabled: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self._unavailable()
        raise AssertionError

    def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        audit_context: AdministrationAuditContext,
    ) -> int:
        self._unavailable()
        raise AssertionError

    def list_capabilities(
        self,
        *,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[CapabilityView, ...], str | None]:
        self._unavailable()
        raise AssertionError

    def list_role_bundles(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[RoleBundleView, ...], str | None]:
        self._unavailable()
        raise AssertionError

    def create_role_bundle(
        self,
        *,
        property_id: str,
        name: str,
        capability_ids: tuple[str, ...],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        self._unavailable()
        raise AssertionError

    def role_bundle_property_id(self, *, role_bundle_id: UUID) -> str | None:
        self._unavailable()
        raise AssertionError

    def update_role_bundle(
        self,
        *,
        role_bundle_id: UUID,
        property_id: str,
        expected_version: int,
        name: str | None,
        capability_ids: tuple[str, ...] | None,
        revoke_affected_sessions_on_capability_reduction: Literal[True],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        self._unavailable()
        raise AssertionError

    def assign_role_bundle(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        self._unavailable()
        raise AssertionError

    def remove_role_assignment(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        self._unavailable()
        raise AssertionError

    def give_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self._unavailable()
        raise AssertionError

    def remove_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self._unavailable()
        raise AssertionError

    def list_authorization_history(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[AuthorizationHistoryView, ...], str | None]:
        self._unavailable()
        raise AssertionError

    def administratively_recover_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reset_mfa: bool,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> AdministrativeRecoveryView:
        self._unavailable()
        raise AssertionError


class UserCreateRequest(BaseModel):
    """Bounded profile and account class for a new account; credentials are separate.

    The class (Manager or Staff, never Owner) sets the MFA policy and the default role bundle
    (DL-081, Q-2026-10-21-152 (a)).
    """

    model_config = ConfigDict(extra="forbid")

    username: BoundedName
    display_name: BoundedName
    audit_name: BoundedName
    account_class: CreatableAccountClass


class UserUpdateRequest(BaseModel):
    """Only approved profile and lifecycle fields are mutable."""

    model_config = ConfigDict(extra="forbid")

    display_name: BoundedName | None = None
    audit_name: BoundedName | None = None
    lifecycle_state: Literal["disabled"] | None = None
    mfa_policy_class: Literal["required", "optional"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UserUpdateRequest":
        if all(
            value is None
            for value in (
                self.display_name,
                self.audit_name,
                self.lifecycle_state,
                self.mfa_policy_class,
            )
        ):
            raise ValueError("at least one account change is required")
        return self


class RoleBundleCreateRequest(BaseModel):
    """Configurable bundle name and explicit capability mapping."""

    model_config = ConfigDict(extra="forbid")

    name: BoundedName
    capability_ids: tuple[CapabilityIdentifier, ...] = Field(max_length=256)


class RoleBundleUpdateRequest(BaseModel):
    """Explicit replacement fields for a configured role bundle."""

    model_config = ConfigDict(extra="forbid")

    name: BoundedName | None = None
    capability_ids: tuple[CapabilityIdentifier, ...] | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def require_change(self) -> "RoleBundleUpdateRequest":
        if self.name is None and self.capability_ids is None:
            raise ValueError("at least one role bundle change is required")
        return self


class RoleAssignmentRequest(BaseModel):
    """Assign one configured bundle without accepting role-title authority."""

    model_config = ConfigDict(extra="forbid")

    role_bundle_id: UUID


class RoleAssignmentRemovalRequest(BaseModel):
    """Remove one assigned bundle from an account, with a reason (Q-2026-10-21-166 (a))."""

    model_config = ConfigDict(extra="forbid")

    role_bundle_id: UUID
    reason: BoundedReason


class SettingsAccessRequest(BaseModel):
    """Give or remove per-user Settings access, with a reason (DL-081, Q-151 (a))."""

    model_config = ConfigDict(extra="forbid")

    reason: BoundedReason


class AdministrativeRecoveryRequest(BaseModel):
    """The Owner's reset with an audit reason; the app makes the one-time password (login
    sub-slice L4, owner answer (a) to Q-2026-10-21-153), and the reason follows the reason rule
    (Q-2026-10-22-169 (a); the L2c note)."""

    model_config = ConfigDict(extra="forbid")

    reset_mfa: bool = False
    reason: BoundedReason


class UserAccountData(BaseModel):
    """Safe account representation."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    property_id: str
    username: str
    display_name: str
    audit_name: str
    lifecycle_state: Literal["active", "disabled"]
    mfa_policy_class: Literal["required", "optional"]
    version: int = Field(ge=1)
    account_class: AccountClass | None
    settings_access: bool


class CapabilityData(BaseModel):
    """Capability catalog representation."""

    model_config = ConfigDict(frozen=True)

    capability_id: str
    name: str
    description: str


class RoleBundleData(BaseModel):
    """Configured role bundle representation."""

    model_config = ConfigDict(frozen=True)

    role_bundle_id: UUID
    property_id: str
    name: str
    capability_ids: tuple[str, ...]
    version: int = Field(ge=1)


class RoleAssignmentData(BaseModel):
    """Configured account-to-bundle assignment representation."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    role_bundle_id: UUID
    property_id: str


class SessionRevocationData(BaseModel):
    """Non-secret count of sessions revoked by an explicit operation."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    sessions_revoked: int = Field(ge=0)


class AuthorizationHistoryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    property_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    action: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=256)
    target_id: str = Field(min_length=1, max_length=256)
    outcome: Literal["completed", "rejected"]


class OneTimePasswordData(BaseModel):
    """The one-time password, shown once to the Owner (login sub-slice L4); the answer carrying
    it is never cached."""

    model_config = ConfigDict(frozen=True)

    value: str = Field(repr=False)
    expires_at: datetime


class AdministrativeRecoveryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    password_changed: bool
    mfa_reset: bool
    sessions_revoked: int = Field(ge=0)
    one_time_password: OneTimePasswordData


class UserAccountResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: UserAccountData
    # A create, or a Staff account's MFA turned off, gives a one-time password (login sub-slice
    # L4); every other account answer has none.
    one_time_password: OneTimePasswordData | None = None
    meta: ResponseMeta


class UserAccountListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: tuple[UserAccountData, ...]
    page: "PageMeta"
    meta: ResponseMeta


class CapabilityListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: tuple[CapabilityData, ...]
    page: "PageMeta"
    meta: ResponseMeta


class RoleBundleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: RoleBundleData
    meta: ResponseMeta


class RoleBundleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: tuple[RoleBundleData, ...]
    page: "PageMeta"
    meta: ResponseMeta


class RoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: RoleAssignmentData
    meta: ResponseMeta


class SessionRevocationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: SessionRevocationData
    meta: ResponseMeta


class AuthorizationHistoryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: tuple[AuthorizationHistoryData, ...]
    page: "PageMeta"
    meta: ResponseMeta


class AdministrativeRecoveryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: AdministrativeRecoveryData
    meta: ResponseMeta


class PageMeta(BaseModel):
    """Canonical bounded collection metadata."""

    model_config = ConfigDict(frozen=True)

    next_cursor: str | None
    limit: int = Field(ge=1, le=100)


def _require_access_actor(
    request: Request,
    actor_resolver: ActorResolver,
    *,
    property_id: str | None = None,
) -> AuthenticatedActor:
    actor = actor_resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ACCESS_ADMIN_CAPABILITY,
            property_id=property_id,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return actor


def _resource_property_id(property_id: str | None) -> str:
    if property_id is None:
        raise AccessAdministrationNotFound
    return property_id


def _require_property_access(
    actor: AuthenticatedActor,
    property_id: str,
    *,
    object_scope: ObjectScope | None = None,
) -> None:
    if not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ACCESS_ADMIN_CAPABILITY,
            property_id=property_id,
            object_scope=object_scope,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _require_object_access(actor: AuthenticatedActor, object_scope: ObjectScope) -> None:
    if not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=ACCESS_ADMIN_CAPABILITY,
            object_scope=object_scope,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _require_matching_property(actual_property_id: str, required_property_id: str) -> None:
    if actual_property_id != required_property_id:
        raise AccessAdministrationUnavailable


def _require_matching_identifier(actual: UUID, required: UUID) -> None:
    if actual != required:
        raise AccessAdministrationUnavailable


def _require_browser_mutation(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.allowed_browser_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        cookie_token is None
        or header_token is None
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _expected_version(request: Request) -> int:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    normalized = raw.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    if not normalized.isascii() or not normalized.isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    version = int(normalized)
    if version < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return version


def _page(
    items: tuple[object, ...],
    cursor: str | None,
    next_cursor: str | None,
    limit: int,
) -> PageMeta:
    if len(items) > limit:
        raise AccessAdministrationUnavailable
    if next_cursor == "" or (next_cursor is not None and next_cursor == cursor):
        raise AccessAdministrationUnavailable
    return PageMeta(next_cursor=next_cursor, limit=limit)


def _require_deterministic_order(keys: tuple[str, ...]) -> None:
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise AccessAdministrationUnavailable


def _user_data(view: UserAccountView) -> UserAccountData:
    return UserAccountData.model_validate(view, from_attributes=True)


def _capability_data(view: CapabilityView) -> CapabilityData:
    return CapabilityData.model_validate(view, from_attributes=True)


def _role_bundle_data(view: RoleBundleView) -> RoleBundleData:
    return RoleBundleData.model_validate(view, from_attributes=True)


def _audit_context(actor_id: str, request: Request) -> AdministrationAuditContext:
    """The audit evidence of a mutation, with the browser's session and reauthentication
    cookies for the recent-reauthentication check (login sub-slice L3d-2)."""
    return AdministrationAuditContext(
        actor_id=actor_id,
        request_id=request.state.request_id,
        session_token=request.cookies.get(SESSION_COOKIE_NAME),
        reauthentication_token=request.cookies.get(REAUTHENTICATION_COOKIE_NAME),
    )


def _one_time_password_data(view: OneTimePasswordView) -> OneTimePasswordData:
    return OneTimePasswordData(value=view.value, expires_at=view.expires_at)


def create_access_admin_router(
    actor_resolver: ActorResolver,
    flow: AccessAdministrationFlow,
    settings: Settings,
) -> APIRouter:
    """Create property-scoped, capability-authorized administration routes."""
    router = APIRouter(prefix="/api/v1", tags=["access administration"])

    @router.get("/properties/{property_id}/users", response_model=UserAccountListResponse)
    def list_users(
        property_id: PropertyIdentifier,
        request: Request,
        cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> UserAccountListResponse:
        actor = _require_access_actor(request, actor_resolver, property_id=property_id)
        users, next_cursor = flow.list_users(
            property_id=property_id,
            cursor=cursor,
            limit=limit,
            actor_id=actor.actor_id,
            request_id=request.state.request_id,
        )
        for user in users:
            _require_matching_property(user.property_id, property_id)
        _require_deterministic_order(tuple(str(user.user_id) for user in users))
        return UserAccountListResponse(
            data=tuple(_user_data(user) for user in users),
            page=_page(users, cursor, next_cursor, limit),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/properties/{property_id}/users",
        response_model=UserAccountResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_user(
        property_id: PropertyIdentifier,
        payload: UserCreateRequest,
        request: Request,
        response: Response,
    ) -> UserAccountResponse:
        actor = _require_access_actor(request, actor_resolver, property_id=property_id)
        _require_browser_mutation(request, settings)
        user = flow.create_user(
            property_id=property_id,
            username=payload.username,
            display_name=payload.display_name,
            audit_name=payload.audit_name,
            account_class=payload.account_class,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(user.property_id, property_id)
        # Q-2026-10-21-152 (a): the class asked for, with the MFA policy it sets (fail closed).
        if user.account_class != payload.account_class or user.mfa_policy_class != (
            "required" if payload.account_class == "manager" else "optional"
        ):
            raise AccessAdministrationUnavailable
        # Q-2026-10-21-153 (a): a new account's first password, shown once (fail closed).
        if user.one_time_password is None:
            raise AccessAdministrationUnavailable
        response.headers["Location"] = f"/api/v1/users/{user.user_id}"
        response.headers["Cache-Control"] = "no-store"
        return UserAccountResponse(
            data=_user_data(user),
            one_time_password=_one_time_password_data(user.one_time_password),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.patch("/users/{user_id}", response_model=UserAccountResponse)
    def update_user(
        user_id: UUID,
        payload: UserUpdateRequest,
        request: Request,
        response: Response,
    ) -> UserAccountResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(
            object_type=USER_ACCOUNT_OBJECT_TYPE,
            object_id=str(user_id),
        )
        _require_object_access(actor, user_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(
            actor,
            property_id,
            object_scope=user_scope,
        )
        user = flow.update_user(
            user_id=user_id,
            property_id=property_id,
            expected_version=_expected_version(request),
            display_name=payload.display_name,
            audit_name=payload.audit_name,
            lifecycle_state=payload.lifecycle_state,
            mfa_policy_class=payload.mfa_policy_class,
            revoke_applicable_sessions_if_disabled=True,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(user.property_id, property_id)
        _require_matching_identifier(user.user_id, user_id)
        if user.one_time_password is not None:
            # A Staff account's MFA turned off (Q-2026-10-23-180 (a)): shown once.
            if payload.mfa_policy_class != "optional":
                raise AccessAdministrationUnavailable
            response.headers["Cache-Control"] = "no-store"
        return UserAccountResponse(
            data=_user_data(user),
            one_time_password=(
                _one_time_password_data(user.one_time_password)
                if user.one_time_password is not None
                else None
            ),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/users/{user_id}/revoke-sessions",
        response_model=SessionRevocationResponse,
    )
    def revoke_user_sessions(user_id: UUID, request: Request) -> SessionRevocationResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(
            object_type=USER_ACCOUNT_OBJECT_TYPE,
            object_id=str(user_id),
        )
        _require_object_access(actor, user_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(
            actor,
            property_id,
            object_scope=user_scope,
        )
        revoked = flow.revoke_user_sessions(
            user_id=user_id,
            audit_context=_audit_context(actor.actor_id, request),
        )
        return SessionRevocationResponse(
            data=SessionRevocationData(user_id=user_id, sessions_revoked=revoked),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.get("/capabilities", response_model=CapabilityListResponse)
    def list_capabilities(
        request: Request,
        cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> CapabilityListResponse:
        actor = _require_access_actor(request, actor_resolver)
        capabilities, next_cursor = flow.list_capabilities(
            cursor=cursor,
            limit=limit,
            actor_id=actor.actor_id,
            request_id=request.state.request_id,
        )
        _require_deterministic_order(tuple(capability.capability_id for capability in capabilities))
        return CapabilityListResponse(
            data=tuple(_capability_data(capability) for capability in capabilities),
            page=_page(capabilities, cursor, next_cursor, limit),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.get(
        "/properties/{property_id}/role-bundles",
        response_model=RoleBundleListResponse,
    )
    def list_role_bundles(
        property_id: PropertyIdentifier,
        request: Request,
        cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> RoleBundleListResponse:
        actor = _require_access_actor(request, actor_resolver, property_id=property_id)
        bundles, next_cursor = flow.list_role_bundles(
            property_id=property_id,
            cursor=cursor,
            limit=limit,
            actor_id=actor.actor_id,
            request_id=request.state.request_id,
        )
        for bundle in bundles:
            _require_matching_property(bundle.property_id, property_id)
        _require_deterministic_order(tuple(str(bundle.role_bundle_id) for bundle in bundles))
        return RoleBundleListResponse(
            data=tuple(_role_bundle_data(bundle) for bundle in bundles),
            page=_page(bundles, cursor, next_cursor, limit),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/properties/{property_id}/role-bundles",
        response_model=RoleBundleResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_role_bundle(
        property_id: PropertyIdentifier,
        payload: RoleBundleCreateRequest,
        request: Request,
        response: Response,
    ) -> RoleBundleResponse:
        actor = _require_access_actor(request, actor_resolver, property_id=property_id)
        _require_browser_mutation(request, settings)
        bundle = flow.create_role_bundle(
            property_id=property_id,
            name=payload.name,
            capability_ids=payload.capability_ids,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(bundle.property_id, property_id)
        response.headers["Location"] = f"/api/v1/role-bundles/{bundle.role_bundle_id}"
        return RoleBundleResponse(
            data=_role_bundle_data(bundle),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.patch("/role-bundles/{role_bundle_id}", response_model=RoleBundleResponse)
    def update_role_bundle(
        role_bundle_id: UUID,
        payload: RoleBundleUpdateRequest,
        request: Request,
    ) -> RoleBundleResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        bundle_scope = ObjectScope(
            object_type=ROLE_BUNDLE_OBJECT_TYPE,
            object_id=str(role_bundle_id),
        )
        _require_object_access(actor, bundle_scope)
        property_id = _resource_property_id(
            flow.role_bundle_property_id(role_bundle_id=role_bundle_id)
        )
        _require_property_access(
            actor,
            property_id,
            object_scope=bundle_scope,
        )
        bundle = flow.update_role_bundle(
            role_bundle_id=role_bundle_id,
            property_id=property_id,
            expected_version=_expected_version(request),
            name=payload.name,
            capability_ids=payload.capability_ids,
            revoke_affected_sessions_on_capability_reduction=True,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(bundle.property_id, property_id)
        _require_matching_identifier(bundle.role_bundle_id, role_bundle_id)
        return RoleBundleResponse(
            data=_role_bundle_data(bundle),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post("/users/{user_id}/role-assignments", response_model=RoleAssignmentResponse)
    def assign_role_bundle(
        user_id: UUID,
        payload: RoleAssignmentRequest,
        request: Request,
    ) -> RoleAssignmentResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(
            object_type=USER_ACCOUNT_OBJECT_TYPE,
            object_id=str(user_id),
        )
        bundle_scope = ObjectScope(
            object_type=ROLE_BUNDLE_OBJECT_TYPE,
            object_id=str(payload.role_bundle_id),
        )
        _require_object_access(actor, user_scope)
        _require_object_access(actor, bundle_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(
            actor,
            property_id,
            object_scope=user_scope,
        )
        role_bundle_property_id = _resource_property_id(
            flow.role_bundle_property_id(role_bundle_id=payload.role_bundle_id)
        )
        _require_property_access(
            actor,
            role_bundle_property_id,
            object_scope=bundle_scope,
        )
        if role_bundle_property_id != property_id:
            raise AccessAdministrationConflict
        assignment = flow.assign_role_bundle(
            user_id=user_id,
            role_bundle_id=payload.role_bundle_id,
            property_id=property_id,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(assignment.property_id, property_id)
        _require_matching_identifier(assignment.user_id, user_id)
        _require_matching_identifier(assignment.role_bundle_id, payload.role_bundle_id)
        return RoleAssignmentResponse(
            data=RoleAssignmentData.model_validate(assignment, from_attributes=True),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/users/{user_id}/role-assignments/remove",
        response_model=RoleAssignmentResponse,
    )
    def remove_role_assignment(
        user_id: UUID,
        payload: RoleAssignmentRemovalRequest,
        request: Request,
    ) -> RoleAssignmentResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(object_type=USER_ACCOUNT_OBJECT_TYPE, object_id=str(user_id))
        bundle_scope = ObjectScope(
            object_type=ROLE_BUNDLE_OBJECT_TYPE,
            object_id=str(payload.role_bundle_id),
        )
        _require_object_access(actor, user_scope)
        _require_object_access(actor, bundle_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(actor, property_id, object_scope=user_scope)
        role_bundle_property_id = _resource_property_id(
            flow.role_bundle_property_id(role_bundle_id=payload.role_bundle_id)
        )
        _require_property_access(actor, role_bundle_property_id, object_scope=bundle_scope)
        if role_bundle_property_id != property_id:
            raise AccessAdministrationConflict
        assignment = flow.remove_role_assignment(
            user_id=user_id,
            role_bundle_id=payload.role_bundle_id,
            property_id=property_id,
            reason=payload.reason,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(assignment.property_id, property_id)
        _require_matching_identifier(assignment.user_id, user_id)
        _require_matching_identifier(assignment.role_bundle_id, payload.role_bundle_id)
        return RoleAssignmentResponse(
            data=RoleAssignmentData.model_validate(assignment, from_attributes=True),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    def change_settings_access(
        user_id: UUID,
        payload: SettingsAccessRequest,
        request: Request,
        *,
        give: bool,
    ) -> UserAccountResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(object_type=USER_ACCOUNT_OBJECT_TYPE, object_id=str(user_id))
        _require_object_access(actor, user_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(actor, property_id, object_scope=user_scope)
        change = flow.give_settings_access if give else flow.remove_settings_access
        user = change(
            user_id=user_id,
            property_id=property_id,
            reason=payload.reason,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_property(user.property_id, property_id)
        _require_matching_identifier(user.user_id, user_id)
        if user.settings_access is not give:
            raise AccessAdministrationUnavailable
        return UserAccountResponse(
            data=_user_data(user),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post("/users/{user_id}/settings-access", response_model=UserAccountResponse)
    def give_settings_access(
        user_id: UUID,
        payload: SettingsAccessRequest,
        request: Request,
    ) -> UserAccountResponse:
        return change_settings_access(user_id, payload, request, give=True)

    @router.post("/users/{user_id}/settings-access/remove", response_model=UserAccountResponse)
    def remove_settings_access(
        user_id: UUID,
        payload: SettingsAccessRequest,
        request: Request,
    ) -> UserAccountResponse:
        return change_settings_access(user_id, payload, request, give=False)

    @router.get(
        "/properties/{property_id}/authorization-history",
        response_model=AuthorizationHistoryListResponse,
    )
    def list_authorization_history(
        property_id: PropertyIdentifier,
        request: Request,
        cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> AuthorizationHistoryListResponse:
        actor = _require_access_actor(request, actor_resolver, property_id=property_id)
        events, next_cursor = flow.list_authorization_history(
            property_id=property_id,
            cursor=cursor,
            limit=limit,
            actor_id=actor.actor_id,
            request_id=request.state.request_id,
        )
        for event in events:
            _require_matching_property(event.property_id, property_id)
        if len({event.event_id for event in events}) != len(events):
            raise AccessAdministrationUnavailable
        return AuthorizationHistoryListResponse(
            data=tuple(
                AuthorizationHistoryData.model_validate(event, from_attributes=True)
                for event in events
            ),
            page=_page(events, cursor, next_cursor, limit),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    @router.post(
        "/users/{user_id}/administrative-recovery",
        response_model=AdministrativeRecoveryResponse,
    )
    def administratively_recover_user(
        user_id: UUID,
        payload: AdministrativeRecoveryRequest,
        request: Request,
        response: Response,
    ) -> AdministrativeRecoveryResponse:
        actor = _require_access_actor(request, actor_resolver)
        _require_browser_mutation(request, settings)
        user_scope = ObjectScope(object_type=USER_ACCOUNT_OBJECT_TYPE, object_id=str(user_id))
        _require_object_access(actor, user_scope)
        property_id = _resource_property_id(flow.user_property_id(user_id=user_id))
        _require_property_access(actor, property_id, object_scope=user_scope)
        result = flow.administratively_recover_user(
            user_id=user_id,
            property_id=property_id,
            reset_mfa=payload.reset_mfa,
            reason=payload.reason,
            audit_context=_audit_context(actor.actor_id, request),
        )
        _require_matching_identifier(result.user_id, user_id)
        response.headers["Cache-Control"] = "no-store"
        return AdministrativeRecoveryResponse(
            data=AdministrativeRecoveryData(
                user_id=result.user_id,
                password_changed=result.password_changed,
                mfa_reset=result.mfa_reset,
                sessions_revoked=result.sessions_revoked,
                one_time_password=_one_time_password_data(result.one_time_password),
            ),
            meta=ResponseMeta(request_id=request.state.request_id),
        )

    return router
