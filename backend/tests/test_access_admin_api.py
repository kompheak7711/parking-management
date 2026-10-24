"""API-079/080 account and configurable capability administration tests."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from fastapi import FastAPI

from property_rental.access_admin_api import (
    ACCESS_ADMIN_CAPABILITY,
    ROLE_BUNDLE_OBJECT_TYPE,
    USER_ACCOUNT_OBJECT_TYPE,
    AccessAdministrationConflict,
    AccessAdministrationFlow,
    AdministrationAuditContext,
    AdministrativeRecoveryRequest,
    AdministrativeRecoveryView,
    AuthorizationHistoryView,
    CapabilityView,
    OneTimePasswordView,
    RoleAssignmentView,
    RoleBundleView,
    UserAccountView,
)
from property_rental.app import create_app
from property_rental.auth_api import CSRF_COOKIE_NAME
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.settings import Settings
from property_rental.visible_text import HIDDEN_NAME_CHARACTERS, HIDDEN_REASON_CHARACTERS

PROPERTY_ID = "property-main"
OTHER_PROPERTY_ID = "property-other"
ACTOR_ID = "access-administrator"
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
ONE_TIME_PASSWORD = OneTimePasswordView(
    value="k7m2-x9qp-4hrt-w3nd", expires_at=datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
)
ROLE_BUNDLE_ID = UUID("33333333-3333-4333-8333-333333333333")
OTHER_ROLE_BUNDLE_ID = UUID("44444444-4444-4444-8444-444444444444")
VERSION = 4
CSRF_TOKEN = "access-administration-csrf-token"


@dataclass
class RecordingAccessAdministrationFlow(AccessAdministrationFlow):
    """Deterministic audited application boundary for HTTP contract tests."""

    calls: list[tuple[str, object]] = field(default_factory=list)
    user_property: str | None = PROPERTY_ID
    role_bundle_property: str | None = PROPERTY_ID
    assignment_user_id: UUID = USER_ID
    assignment_role_bundle_id: UUID = ROLE_BUNDLE_ID
    created_account: UserAccountView | None = None
    assignment_property_id: str | None = None
    settings_access_result: bool | None = None
    update_one_time_password: OneTimePasswordView | None = None
    account: UserAccountView = field(
        default_factory=lambda: UserAccountView(
            user_id=USER_ID,
            property_id=PROPERTY_ID,
            username="operator",
            display_name="Operator",
            audit_name="operator-audit",
            lifecycle_state="active",
            mfa_policy_class="required",
            version=VERSION,
            account_class="manager",
            settings_access=False,
        )
    )
    bundle: RoleBundleView = field(
        default_factory=lambda: RoleBundleView(
            role_bundle_id=ROLE_BUNDLE_ID,
            property_id=PROPERTY_ID,
            name="Lease operations",
            capability_ids=("leases.inspect", "leases.sign"),
            version=VERSION,
        )
    )

    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        self.calls.append(("list_users", (property_id, cursor, limit, actor_id, request_id)))
        return (self.account,), "next-users"

    def create_user(
        self,
        *,
        property_id: str,
        username: str,
        display_name: str,
        audit_name: str,
        account_class: Literal["manager", "staff"],
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self.calls.append(
            (
                "create_user",
                (
                    property_id,
                    username,
                    display_name,
                    audit_name,
                    account_class,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        if self.created_account is not None:
            return self.created_account
        return UserAccountView(
            user_id=CREATED_USER_ID,
            property_id=property_id,
            username=username,
            display_name=display_name,
            audit_name=audit_name,
            lifecycle_state="active",
            mfa_policy_class="required" if account_class == "manager" else "optional",
            version=1,
            account_class=account_class,
            settings_access=False,
            one_time_password=ONE_TIME_PASSWORD,
        )

    def user_property_id(self, *, user_id: UUID) -> str | None:
        self.calls.append(("user_property_id", user_id))
        return self.user_property

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
        if expected_version != self.account.version:
            raise AccessAdministrationConflict
        self.calls.append(
            (
                "update_user",
                (
                    user_id,
                    property_id,
                    expected_version,
                    display_name,
                    audit_name,
                    lifecycle_state,
                    mfa_policy_class,
                    revoke_applicable_sessions_if_disabled,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return replace(
            self.account,
            display_name=display_name or self.account.display_name,
            audit_name=audit_name or self.account.audit_name,
            lifecycle_state=lifecycle_state or self.account.lifecycle_state,
            mfa_policy_class=mfa_policy_class or self.account.mfa_policy_class,
            version=expected_version + 1,
            one_time_password=self.update_one_time_password,
        )

    def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        audit_context: AdministrationAuditContext,
    ) -> int:
        self.calls.append(
            (
                "revoke_user_sessions",
                (user_id, audit_context.actor_id, audit_context.request_id),
            )
        )
        return 3

    def list_capabilities(
        self,
        *,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[CapabilityView, ...], str | None]:
        self.calls.append(("list_capabilities", (cursor, limit, actor_id, request_id)))
        return (
            (
                CapabilityView(
                    capability_id="leases.sign",
                    name="Sign leases",
                    description="Sign an approved lease",
                ),
            ),
            None,
        )

    def list_role_bundles(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[RoleBundleView, ...], str | None]:
        self.calls.append(("list_role_bundles", (property_id, cursor, limit, actor_id, request_id)))
        return (self.bundle,), "next-bundles"

    def create_role_bundle(
        self,
        *,
        property_id: str,
        name: str,
        capability_ids: tuple[str, ...],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        self.calls.append(
            (
                "create_role_bundle",
                (
                    property_id,
                    name,
                    capability_ids,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return RoleBundleView(
            role_bundle_id=ROLE_BUNDLE_ID,
            property_id=property_id,
            name=name,
            capability_ids=capability_ids,
            version=1,
        )

    def role_bundle_property_id(self, *, role_bundle_id: UUID) -> str | None:
        self.calls.append(("role_bundle_property_id", role_bundle_id))
        return self.role_bundle_property

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
        if expected_version != self.bundle.version:
            raise AccessAdministrationConflict
        self.calls.append(
            (
                "update_role_bundle",
                (
                    role_bundle_id,
                    property_id,
                    expected_version,
                    name,
                    capability_ids,
                    revoke_affected_sessions_on_capability_reduction,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return replace(
            self.bundle,
            name=name or self.bundle.name,
            capability_ids=(
                capability_ids if capability_ids is not None else self.bundle.capability_ids
            ),
            version=expected_version + 1,
        )

    def assign_role_bundle(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        self.calls.append(
            (
                "assign_role_bundle",
                (
                    user_id,
                    role_bundle_id,
                    property_id,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return RoleAssignmentView(
            user_id=self.assignment_user_id,
            role_bundle_id=self.assignment_role_bundle_id,
            property_id=property_id,
        )

    def remove_role_assignment(
        self,
        *,
        user_id: UUID,
        role_bundle_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> RoleAssignmentView:
        self.calls.append(
            (
                "remove_role_assignment",
                (
                    user_id,
                    role_bundle_id,
                    property_id,
                    reason,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return RoleAssignmentView(
            user_id=self.assignment_user_id,
            role_bundle_id=self.assignment_role_bundle_id,
            property_id=self.assignment_property_id or property_id,
        )

    def give_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self.calls.append(
            (
                "give_settings_access",
                (user_id, property_id, reason, audit_context.actor_id, audit_context.request_id),
            )
        )
        result = self.settings_access_result
        return replace(self.account, settings_access=True if result is None else result)

    def remove_settings_access(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> UserAccountView:
        self.calls.append(
            (
                "remove_settings_access",
                (user_id, property_id, reason, audit_context.actor_id, audit_context.request_id),
            )
        )
        result = self.settings_access_result
        return replace(self.account, settings_access=False if result is None else result)

    def list_authorization_history(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[AuthorizationHistoryView, ...], str | None]:
        self.calls.append(
            (
                "list_authorization_history",
                (property_id, cursor, limit, actor_id, request_id),
            )
        )
        return (
            (
                AuthorizationHistoryView(
                    event_id=UUID("55555555-5555-4555-8555-555555555555"),
                    property_id=property_id,
                    occurred_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
                    action="role_bundle_assigned",
                    actor_id=actor_id,
                    target_id=str(USER_ID),
                    outcome="completed",
                ),
            ),
            None,
        )

    def administratively_recover_user(
        self,
        *,
        user_id: UUID,
        property_id: str,
        reset_mfa: bool,
        reason: str,
        audit_context: AdministrationAuditContext,
    ) -> AdministrativeRecoveryView:
        self.calls.append(
            (
                "administratively_recover_user",
                (
                    user_id,
                    property_id,
                    reset_mfa,
                    reason,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return AdministrativeRecoveryView(
            user_id=user_id,
            password_changed=True,
            mfa_reset=reset_mfa,
            sessions_revoked=3,
            one_time_password=ONE_TIME_PASSWORD,
        )


class ConflictingAccessAdministrationFlow(RecordingAccessAdministrationFlow):
    def create_role_bundle(
        self,
        *,
        property_id: str,
        name: str,
        capability_ids: tuple[str, ...],
        audit_context: AdministrationAuditContext,
    ) -> RoleBundleView:
        del property_id, name, capability_ids, audit_context
        raise AccessAdministrationConflict


class UnorderedAccessAdministrationFlow(RecordingAccessAdministrationFlow):
    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        del property_id, cursor, limit, actor_id, request_id
        return (replace(self.account, user_id=CREATED_USER_ID), self.account), None


class DuplicateAccessAdministrationFlow(RecordingAccessAdministrationFlow):
    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        del property_id, cursor, limit, actor_id, request_id
        return (self.account, self.account), None


class CursorAwareAccessAdministrationFlow(RecordingAccessAdministrationFlow):
    def list_users(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[UserAccountView, ...], str | None]:
        self.calls.append(("list_users", (property_id, cursor, limit, actor_id, request_id)))
        if cursor is None:
            return (self.account,), "users-page-2"
        if cursor == "users-page-2":
            return (replace(self.account, user_id=CREATED_USER_ID),), None
        raise AssertionError("unexpected user cursor")

    def list_capabilities(
        self,
        *,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[CapabilityView, ...], str | None]:
        self.calls.append(("list_capabilities", (cursor, limit, actor_id, request_id)))
        if cursor is None:
            return (
                (
                    CapabilityView(
                        capability_id="leases.inspect",
                        name="Inspect leases",
                        description="Inspect an authorized lease",
                    ),
                ),
                "capabilities-page-2",
            )
        if cursor == "capabilities-page-2":
            return (
                (
                    CapabilityView(
                        capability_id="leases.sign",
                        name="Sign leases",
                        description="Sign an approved lease",
                    ),
                ),
                None,
            )
        raise AssertionError("unexpected capability cursor")

    def list_role_bundles(
        self,
        *,
        property_id: str,
        cursor: str | None,
        limit: int,
        actor_id: str,
        request_id: str,
    ) -> tuple[tuple[RoleBundleView, ...], str | None]:
        self.calls.append(("list_role_bundles", (property_id, cursor, limit, actor_id, request_id)))
        if cursor is None:
            return (self.bundle,), "bundles-page-2"
        if cursor == "bundles-page-2":
            return (replace(self.bundle, role_bundle_id=OTHER_ROLE_BUNDLE_ID),), None
        raise AssertionError("unexpected role-bundle cursor")


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    payload: Mapping[str, object] | None = None,
    request_id: str = "access-admin-test",
    headers: dict[str, str] | None = None,
    browser_protection: bool = True,
    include_if_match: bool = True,
    cookies: Mapping[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        client_cookies = {
            **({CSRF_COOKIE_NAME: CSRF_TOKEN} if browser_protection else {}),
            **(cookies or {}),
        }
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies=client_cookies or None,
        ) as client:
            mutation_headers: dict[str, str] = (
                {
                    "Origin": Settings().allowed_browser_origin,
                    "X-CSRF-Token": CSRF_TOKEN,
                }
                if browser_protection and method in {"POST", "PATCH"}
                else {}
            )
            if method == "PATCH" and include_if_match:
                mutation_headers["If-Match"] = f'"{VERSION}"'
            merged_headers = {
                "X-Request-ID": request_id,
                **mutation_headers,
                **(headers or {}),
            }
            return await client.request(method, path, json=payload, headers=merged_headers)

    return asyncio.run(send())


def authorized_actor(
    *property_ids: str,
    object_scopes: tuple[ObjectScope, ...] | None = None,
) -> AuthenticatedActor:
    if object_scopes is None:
        object_scopes = (
            ObjectScope(object_type=USER_ACCOUNT_OBJECT_TYPE, object_id=str(USER_ID)),
            ObjectScope(
                object_type=ROLE_BUNDLE_OBJECT_TYPE,
                object_id=str(ROLE_BUNDLE_ID),
            ),
        )
    return AuthenticatedActor(
        actor_id=ACTOR_ID,
        capability_grants=frozenset(
            {
                CapabilityGrant(
                    capability=ACCESS_ADMIN_CAPABILITY,
                    property_ids=frozenset(property_ids),
                    object_scopes=frozenset(object_scopes),
                )
            }
        ),
    )


def authorized_app(
    flow: AccessAdministrationFlow | None = None,
    *,
    property_ids: tuple[str, ...] = (PROPERTY_ID,),
    object_scopes: tuple[ObjectScope, ...] | None = None,
) -> FastAPI:
    return create_app(
        Settings(),
        actor_resolver=lambda _: authorized_actor(
            *property_ids,
            object_scopes=object_scopes,
        ),
        access_administration_flow=flow,
    )


def test_administration_openapi_exposes_only_api_079_080_operations_and_safe_fields() -> None:
    schema = create_app(Settings()).openapi()
    expected_operations = {
        ("/api/v1/properties/{property_id}/users", "get"),
        ("/api/v1/properties/{property_id}/users", "post"),
        ("/api/v1/users/{user_id}", "patch"),
        ("/api/v1/users/{user_id}/revoke-sessions", "post"),
        ("/api/v1/capabilities", "get"),
        ("/api/v1/properties/{property_id}/role-bundles", "get"),
        ("/api/v1/properties/{property_id}/role-bundles", "post"),
        ("/api/v1/role-bundles/{role_bundle_id}", "patch"),
        ("/api/v1/users/{user_id}/role-assignments", "post"),
        ("/api/v1/users/{user_id}/role-assignments/remove", "post"),
        ("/api/v1/users/{user_id}/settings-access", "post"),
        ("/api/v1/users/{user_id}/settings-access/remove", "post"),
        ("/api/v1/properties/{property_id}/authorization-history", "get"),
        ("/api/v1/users/{user_id}/administrative-recovery", "post"),
    }
    actual_operations = {
        (path, method)
        for path, operations in schema["paths"].items()
        for method in operations
        if path in {item[0] for item in expected_operations}
    }

    assert actual_operations == expected_operations
    schemas = schema["components"]["schemas"]
    administration_schemas = {
        name: schemas[name]
        for name in (
            "UserCreateRequest",
            "UserUpdateRequest",
            "UserAccountData",
            "RoleBundleCreateRequest",
            "RoleBundleUpdateRequest",
            "RoleAssignmentRequest",
            "RoleAssignmentRemovalRequest",
            "SettingsAccessRequest",
        )
    }

    def property_names(value: object) -> set[str]:
        if isinstance(value, dict):
            names = {
                str(name).lower() for name in value.get("properties", {}) if isinstance(name, str)
            }
            return names | set().union(*(property_names(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(property_names(item) for item in value))
        return set()

    exposed_fields = property_names(administration_schemas)
    assert not any(
        forbidden in field
        for forbidden in ("password", "credential", "secret")
        for field in exposed_fields
    )
    assert set(schemas["UserCreateRequest"]["properties"]) == {
        "username",
        "display_name",
        "audit_name",
        "account_class",
    }


def test_every_administration_operation_denies_without_an_authenticated_actor() -> None:
    app = create_app(Settings())
    operations = (
        ("GET", f"/api/v1/properties/{PROPERTY_ID}/users", None),
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/users",
            {
                "username": "operator",
                "display_name": "Operator",
                "audit_name": "operator-audit",
                "account_class": "manager",
            },
        ),
        ("PATCH", f"/api/v1/users/{USER_ID}", {"lifecycle_state": "disabled"}),
        ("POST", f"/api/v1/users/{USER_ID}/revoke-sessions", None),
        ("GET", "/api/v1/capabilities", None),
        ("GET", f"/api/v1/properties/{PROPERTY_ID}/role-bundles", None),
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
            {"name": "Configured bundle", "capability_ids": ["leases.inspect"]},
        ),
        ("PATCH", f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}", {"name": "Renamed"}),
        (
            "POST",
            f"/api/v1/users/{USER_ID}/role-assignments",
            {"role_bundle_id": str(ROLE_BUNDLE_ID)},
        ),
    )

    for method, path, payload in operations:
        response = request(app, method, path, payload=payload)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_property_scoped_routes_reject_an_access_grant_for_another_property() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow, property_ids=(OTHER_PROPERTY_ID,))

    response = request(app, "GET", f"/api/v1/properties/{PROPERTY_ID}/users")

    assert response.status_code == 403
    assert flow.calls == []


def test_missing_capability_and_inactive_sessions_fail_closed() -> None:
    flow = RecordingAccessAdministrationFlow()
    missing_capability = create_app(
        Settings(),
        actor_resolver=lambda _: AuthenticatedActor(actor_id=ACTOR_ID),
        access_administration_flow=flow,
    )
    forbidden = request(
        missing_capability,
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
    )
    assert forbidden.status_code == 403
    assert flow.calls == []

    for session_state in ("disabled", "stale", "revoked"):
        app = create_app(
            Settings(),
            actor_resolver=lambda request: (
                None
                if request.headers.get("X-Test-Session-State") in {"disabled", "stale", "revoked"}
                else authorized_actor(PROPERTY_ID)
            ),
            access_administration_flow=flow,
        )
        rejected = request(
            app,
            "GET",
            f"/api/v1/properties/{PROPERTY_ID}/users",
            headers={"X-Test-Session-State": session_state},
        )
        assert rejected.status_code == 401
    assert flow.calls == []


def test_every_browser_mutation_requires_exact_origin_and_csrf_proof() -> None:
    operations = (
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/users",
            {
                "username": "operator",
                "display_name": "Operator",
                "audit_name": "operator-audit",
                "account_class": "staff",
            },
        ),
        ("PATCH", f"/api/v1/users/{USER_ID}", {"display_name": "Changed"}),
        ("POST", f"/api/v1/users/{USER_ID}/revoke-sessions", None),
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
            {"name": "Configured", "capability_ids": []},
        ),
        ("PATCH", f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}", {"name": "Changed"}),
        (
            "POST",
            f"/api/v1/users/{USER_ID}/role-assignments",
            {"role_bundle_id": str(ROLE_BUNDLE_ID)},
        ),
    )
    for method, path, payload in operations:
        flow = RecordingAccessAdministrationFlow()
        rejected = request(
            authorized_app(flow),
            method,
            path,
            payload=payload,
            browser_protection=False,
        )
        assert rejected.status_code == 403, (method, path, rejected.text)
        assert flow.calls == []

    origin_flow = RecordingAccessAdministrationFlow()
    wrong_origin = request(
        authorized_app(origin_flow),
        "POST",
        f"/api/v1/users/{USER_ID}/revoke-sessions",
        headers={"Origin": "https://attacker.invalid"},
    )
    assert wrong_origin.status_code == 403
    assert origin_flow.calls == []


def test_identifier_mutations_require_exact_object_grants() -> None:
    user_flow = RecordingAccessAdministrationFlow()
    denied_user = request(
        authorized_app(user_flow, object_scopes=()),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"display_name": "Denied"},
    )
    assert denied_user.status_code == 403
    assert user_flow.calls == []

    bundle_flow = RecordingAccessAdministrationFlow()
    denied_bundle = request(
        authorized_app(
            bundle_flow,
            object_scopes=(
                ObjectScope(
                    object_type=USER_ACCOUNT_OBJECT_TYPE,
                    object_id=str(USER_ID),
                ),
            ),
        ),
        "PATCH",
        f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}",
        payload={"name": "Denied"},
    )
    assert denied_bundle.status_code == 403
    assert bundle_flow.calls == []


def test_account_list_and_creation_are_scoped_audited_and_never_return_credentials() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    listed = request(
        app,
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        request_id="accounts-list",
    )
    created = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload={
            "username": "new.operator",
            "display_name": "New Operator",
            "audit_name": "new-operator-audit",
            "account_class": "staff",
        },
        request_id="account-create",
    )

    assert listed.status_code == 200
    assert listed.json()["data"] == [
        {
            "user_id": str(USER_ID),
            "property_id": PROPERTY_ID,
            "username": "operator",
            "display_name": "Operator",
            "audit_name": "operator-audit",
            "lifecycle_state": "active",
            "mfa_policy_class": "required",
            "version": VERSION,
            "account_class": "manager",
            "settings_access": False,
        }
    ]
    assert listed.json()["page"] == {"next_cursor": "next-users", "limit": 50}
    assert created.status_code == 201
    assert created.headers["Location"] == f"/api/v1/users/{CREATED_USER_ID}"
    assert created.json()["data"]["user_id"] == str(CREATED_USER_ID)
    assert created.json()["data"]["lifecycle_state"] == "active"
    assert created.json()["data"]["version"] == 1
    # Login sub-slice L4: the new account's first one-time password is answered once, beside the
    # account and never cached; no stored credential is ever answered.
    assert created.json()["one_time_password"] == {
        "value": ONE_TIME_PASSWORD.value,
        "expires_at": "2026-10-25T03:00:00Z",
    }
    assert created.headers["cache-control"] == "no-store"
    assert "password" not in json.dumps(created.json()["data"]).lower()
    assert "password" not in listed.text.lower()
    assert "credential" not in created.text.lower()
    assert "argon" not in created.text.lower()
    assert flow.calls == [
        ("list_users", (PROPERTY_ID, None, 50, ACTOR_ID, "accounts-list")),
        (
            "create_user",
            (
                PROPERTY_ID,
                "new.operator",
                "New Operator",
                "new-operator-audit",
                "staff",
                ACTOR_ID,
                "account-create",
            ),
        ),
    ]


def test_account_disable_and_explicit_session_revocation_use_authoritative_resource_scope() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    updated = request(
        app,
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"lifecycle_state": "disabled"},
        request_id="account-disable",
    )
    revoked = request(
        app,
        "POST",
        f"/api/v1/users/{USER_ID}/revoke-sessions",
        request_id="account-revoke",
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["lifecycle_state"] == "disabled"
    assert revoked.status_code == 200
    assert revoked.json()["data"] == {"user_id": str(USER_ID), "sessions_revoked": 3}
    assert flow.calls == [
        ("user_property_id", USER_ID),
        (
            "update_user",
            (
                USER_ID,
                PROPERTY_ID,
                VERSION,
                None,
                None,
                "disabled",
                None,
                True,
                ACTOR_ID,
                "account-disable",
            ),
        ),
        ("user_property_id", USER_ID),
        ("revoke_user_sessions", (USER_ID, ACTOR_ID, "account-revoke")),
    ]


def test_mutable_resources_expose_versions_and_reject_missing_invalid_or_stale_preconditions() -> (
    None
):
    for path, payload in (
        (f"/api/v1/users/{USER_ID}", {"display_name": "Changed"}),
        (f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}", {"name": "Changed"}),
    ):
        missing = request(
            authorized_app(RecordingAccessAdministrationFlow()),
            "PATCH",
            path,
            payload=payload,
            include_if_match=False,
        )
        malformed = request(
            authorized_app(RecordingAccessAdministrationFlow()),
            "PATCH",
            path,
            payload=payload,
            headers={"If-Match": "not-a-version"},
        )
        stale = request(
            authorized_app(RecordingAccessAdministrationFlow()),
            "PATCH",
            path,
            payload=payload,
            headers={"If-Match": '"3"'},
        )
        assert missing.status_code == 412
        assert missing.json()["error"]["code"] == "PRECONDITION_FAILED"
        assert malformed.status_code == 400
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "CONFLICT"

    updated_user = request(
        authorized_app(RecordingAccessAdministrationFlow()),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"display_name": "Changed"},
    )
    updated_bundle = request(
        authorized_app(RecordingAccessAdministrationFlow()),
        "PATCH",
        f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}",
        payload={"name": "Changed"},
    )
    assert updated_user.json()["data"]["version"] == VERSION + 1
    assert updated_bundle.json()["data"]["version"] == VERSION + 1


def test_disable_and_privilege_reduction_bind_audit_and_session_revocation_atomically() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    disabled = request(
        app,
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"lifecycle_state": "disabled"},
        request_id="atomic-disable",
    )
    reduced = request(
        app,
        "PATCH",
        f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}",
        payload={"capability_ids": ["leases.inspect"]},
        request_id="atomic-privilege-reduction",
    )

    assert disabled.status_code == 200
    assert reduced.status_code == 200
    assert (
        "update_user",
        (
            USER_ID,
            PROPERTY_ID,
            VERSION,
            None,
            None,
            "disabled",
            None,
            True,
            ACTOR_ID,
            "atomic-disable",
        ),
    ) in flow.calls
    assert (
        "update_role_bundle",
        (
            ROLE_BUNDLE_ID,
            PROPERTY_ID,
            VERSION,
            None,
            ("leases.inspect",),
            True,
            ACTOR_ID,
            "atomic-privilege-reduction",
        ),
    ) in flow.calls


def test_capabilities_and_role_bundles_are_data_not_role_title_authority() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    capabilities = request(app, "GET", "/api/v1/capabilities", request_id="capabilities")
    bundles = request(
        app,
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
        request_id="bundles",
    )
    created = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
        payload={
            "name": "Any deployment-defined name",
            "capability_ids": ["leases.inspect", "leases.sign"],
        },
        request_id="bundle-create",
    )
    updated = request(
        app,
        "PATCH",
        f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}",
        payload={"name": "Renamed by configuration", "capability_ids": ["leases.inspect"]},
        request_id="bundle-update",
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["data"][0]["capability_id"] == "leases.sign"
    assert capabilities.json()["page"] == {"next_cursor": None, "limit": 50}
    assert bundles.status_code == 200
    assert bundles.json()["data"][0]["name"] == "Lease operations"
    assert bundles.json()["page"] == {"next_cursor": "next-bundles", "limit": 50}
    assert created.status_code == 201
    assert created.headers["Location"] == f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}"
    assert created.json()["data"]["name"] == "Any deployment-defined name"
    assert created.json()["data"]["capability_ids"] == ["leases.inspect", "leases.sign"]
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Renamed by configuration"
    assert updated.json()["data"]["capability_ids"] == ["leases.inspect"]
    assert ("list_capabilities", (None, 50, ACTOR_ID, "capabilities")) in flow.calls
    assert (
        "create_role_bundle",
        (
            PROPERTY_ID,
            "Any deployment-defined name",
            ("leases.inspect", "leases.sign"),
            ACTOR_ID,
            "bundle-create",
        ),
    ) in flow.calls


def test_collection_pagination_is_bounded_and_forwarded_to_the_flow() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    users = request(
        app,
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users?cursor=user-cursor&limit=7",
        request_id="paged-users",
    )
    bundles = request(
        app,
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/role-bundles?cursor=bundle-cursor&limit=8",
        request_id="paged-bundles",
    )
    invalid = request(app, "GET", "/api/v1/capabilities?limit=101")

    assert users.status_code == 200
    assert users.json()["page"] == {"next_cursor": "next-users", "limit": 7}
    assert bundles.status_code == 200
    assert bundles.json()["page"] == {"next_cursor": "next-bundles", "limit": 8}
    assert invalid.status_code == 422
    assert (
        "list_users",
        (PROPERTY_ID, "user-cursor", 7, ACTOR_ID, "paged-users"),
    ) in flow.calls
    assert (
        "list_role_bundles",
        (PROPERTY_ID, "bundle-cursor", 8, ACTOR_ID, "paged-bundles"),
    ) in flow.calls

    unordered = request(
        authorized_app(UnorderedAccessAdministrationFlow()),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
    )
    duplicate = request(
        authorized_app(DuplicateAccessAdministrationFlow()),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
    )
    assert unordered.status_code == 503
    assert duplicate.status_code == 503


def test_collection_cursors_traverse_stable_pages_without_duplicates_or_skips() -> None:
    flow = CursorAwareAccessAdministrationFlow()
    app = authorized_app(flow)
    collections = (
        (
            f"/api/v1/properties/{PROPERTY_ID}/users",
            "user_id",
            [str(USER_ID), str(CREATED_USER_ID)],
        ),
        (
            "/api/v1/capabilities",
            "capability_id",
            ["leases.inspect", "leases.sign"],
        ),
        (
            f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
            "role_bundle_id",
            [str(ROLE_BUNDLE_ID), str(OTHER_ROLE_BUNDLE_ID)],
        ),
    )

    for path, identifier_field, expected_identifiers in collections:
        first = request(app, "GET", f"{path}?limit=1")
        assert first.status_code == 200
        next_cursor = first.json()["page"]["next_cursor"]
        assert isinstance(next_cursor, str) and next_cursor

        second = request(app, "GET", f"{path}?limit=1&cursor={next_cursor}")
        assert second.status_code == 200
        assert second.json()["page"]["next_cursor"] is None

        identifiers = [
            first.json()["data"][0][identifier_field],
            second.json()["data"][0][identifier_field],
        ]
        assert identifiers == expected_identifiers == sorted(identifiers)
        assert len(identifiers) == len(set(identifiers)) == 2


def test_role_assignment_validates_both_resource_properties_before_mutation() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    assigned = request(
        app,
        "POST",
        f"/api/v1/users/{USER_ID}/role-assignments",
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID)},
        request_id="role-assign",
    )

    assert assigned.status_code == 200
    assert assigned.json()["data"] == {
        "user_id": str(USER_ID),
        "role_bundle_id": str(ROLE_BUNDLE_ID),
        "property_id": PROPERTY_ID,
    }
    assert flow.calls == [
        ("user_property_id", USER_ID),
        ("role_bundle_property_id", ROLE_BUNDLE_ID),
        (
            "assign_role_bundle",
            (USER_ID, ROLE_BUNDLE_ID, PROPERTY_ID, ACTOR_ID, "role-assign"),
        ),
    ]

    cross_property_flow = RecordingAccessAdministrationFlow(role_bundle_property=OTHER_PROPERTY_ID)
    rejected = request(
        authorized_app(cross_property_flow),
        "POST",
        f"/api/v1/users/{USER_ID}/role-assignments",
        payload={"role_bundle_id": str(OTHER_ROLE_BUNDLE_ID)},
        request_id="cross-property-role-assign",
    )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "FORBIDDEN"
    assert cross_property_flow.calls == []

    relationship_flow = RecordingAccessAdministrationFlow(role_bundle_property=OTHER_PROPERTY_ID)
    relationship_conflict = request(
        authorized_app(
            relationship_flow,
            property_ids=(PROPERTY_ID, OTHER_PROPERTY_ID),
            object_scopes=(
                ObjectScope(
                    object_type=USER_ACCOUNT_OBJECT_TYPE,
                    object_id=str(USER_ID),
                ),
                ObjectScope(
                    object_type=ROLE_BUNDLE_OBJECT_TYPE,
                    object_id=str(OTHER_ROLE_BUNDLE_ID),
                ),
            ),
        ),
        "POST",
        f"/api/v1/users/{USER_ID}/role-assignments",
        payload={"role_bundle_id": str(OTHER_ROLE_BUNDLE_ID)},
    )
    assert relationship_conflict.status_code == 409


def test_mutation_results_must_match_every_requested_identifier() -> None:
    wrong_user = replace(
        RecordingAccessAdministrationFlow().account,
        user_id=CREATED_USER_ID,
    )
    user_response = request(
        authorized_app(RecordingAccessAdministrationFlow(account=wrong_user)),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"display_name": "Changed"},
    )

    wrong_bundle = replace(
        RecordingAccessAdministrationFlow().bundle,
        role_bundle_id=OTHER_ROLE_BUNDLE_ID,
    )
    bundle_response = request(
        authorized_app(RecordingAccessAdministrationFlow(bundle=wrong_bundle)),
        "PATCH",
        f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}",
        payload={"name": "Changed"},
    )

    assignment_response = request(
        authorized_app(RecordingAccessAdministrationFlow(assignment_user_id=CREATED_USER_ID)),
        "POST",
        f"/api/v1/users/{USER_ID}/role-assignments",
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID)},
    )

    assert user_response.status_code == 503
    assert bundle_response.status_code == 503
    assert assignment_response.status_code == 503


def test_resource_routes_deny_wrong_scope_before_any_mutation() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow, property_ids=(OTHER_PROPERTY_ID,))

    response = request(
        app,
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"display_name": "Not authorized"},
    )

    assert response.status_code == 403
    assert flow.calls == [("user_property_id", USER_ID)]


def test_request_validation_rejects_unknown_fields_blank_updates_and_invalid_capabilities() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    invalid_requests: tuple[tuple[str, str, dict[str, object]], ...] = (
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/users",
            {
                "username": "operator",
                "display_name": "Operator",
                "audit_name": "operator-audit",
                "account_class": "staff",
                "role": "Owner",
            },
        ),
        ("PATCH", f"/api/v1/users/{USER_ID}", {}),
        ("PATCH", f"/api/v1/users/{USER_ID}", {"lifecycle_state": "active"}),
        (
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
            {"name": "Invalid capability", "capability_ids": ["Owner authority"]},
        ),
        ("PATCH", f"/api/v1/role-bundles/{ROLE_BUNDLE_ID}", {}),
    )

    for method, path, payload in invalid_requests:
        response = request(app, method, path, payload=payload)
        assert response.status_code == 422, (path, response.text)
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    assert flow.calls == []


def test_missing_and_unavailable_administration_resources_fail_closed() -> None:
    missing_flow = RecordingAccessAdministrationFlow(user_property=None)
    missing = request(
        authorized_app(missing_flow),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"lifecycle_state": "disabled"},
        request_id="missing-user",
    )
    unavailable = request(
        authorized_app(),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        request_id="administration-unavailable",
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "runtime adapter" not in unavailable.text.lower()


def test_conflicts_use_canonical_secret_free_error_envelope() -> None:
    response = request(
        authorized_app(ConflictingAccessAdministrationFlow()),
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/role-bundles",
        payload={"name": "Duplicate", "capability_ids": []},
        request_id="bundle-conflict",
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "CONFLICT",
            "message": "The request conflicts with the current resource state.",
            "fields": [],
            "rule_ids": [],
            "current_version": None,
        },
        "meta": {"request_id": "bundle-conflict"},
    }


def test_client_role_capability_and_property_headers_never_create_authority() -> None:
    flow = RecordingAccessAdministrationFlow()
    response = request(
        create_app(Settings(), access_administration_flow=flow),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        headers={
            "X-Role": "Owner",
            "X-Capabilities": ACCESS_ADMIN_CAPABILITY,
            "X-Property-Scope": PROPERTY_ID,
            "X-Actor-ID": ACTOR_ID,
        },
    )

    assert response.status_code == 401
    assert flow.calls == []
    assert ACTOR_ID not in response.text


def test_authorized_administrator_can_inspect_secret_free_authorization_history() -> None:
    flow = RecordingAccessAdministrationFlow()

    response = request(
        authorized_app(flow),
        "GET",
        f"/api/v1/properties/{PROPERTY_ID}/authorization-history?limit=50",
        request_id="authorization-history",
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "event_id": "55555555-5555-4555-8555-555555555555",
            "property_id": PROPERTY_ID,
            "occurred_at": "2026-08-22T10:00:00Z",
            "action": "role_bundle_assigned",
            "actor_id": ACTOR_ID,
            "target_id": str(USER_ID),
            "outcome": "completed",
        }
    ]
    assert "password" not in response.text.lower()
    assert (
        "list_authorization_history",
        (PROPERTY_ID, None, 50, ACTOR_ID, "authorization-history"),
    ) in flow.calls


def test_administrative_recovery_requires_scope_csrf_and_explicit_audit_reason() -> None:
    flow = RecordingAccessAdministrationFlow()
    payload = {"reset_mfa": True, "reason": "approved account recovery"}

    response = request(
        authorized_app(flow),
        "POST",
        f"/api/v1/users/{USER_ID}/administrative-recovery",
        payload=payload,
        request_id="administrative-recovery",
    )
    denied = request(
        authorized_app(flow, object_scopes=()),
        "POST",
        f"/api/v1/users/{USER_ID}/administrative-recovery",
        payload=payload,
        request_id="administrative-recovery-denied",
    )

    # Login sub-slice L4: the app makes the one-time password and answers it once, never cached;
    # the Owner no longer types a password, so the old request shape is refused.
    old_shape = request(
        authorized_app(flow),
        "POST",
        f"/api/v1/users/{USER_ID}/administrative-recovery",
        payload={**payload, "new_password": "a sufficiently long replacement password"},
        request_id="administrative-recovery-old-shape",
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "user_id": str(USER_ID),
        "password_changed": True,
        "mfa_reset": True,
        "sessions_revoked": 3,
        "one_time_password": {
            "value": ONE_TIME_PASSWORD.value,
            "expires_at": "2026-10-25T03:00:00Z",
        },
    }
    assert response.headers["cache-control"] == "no-store"
    assert denied.status_code == 403
    assert old_shape.status_code == 422
    assert ONE_TIME_PASSWORD.value not in repr(flow.calls)
    assert (
        "administratively_recover_user",
        (
            USER_ID,
            PROPERTY_ID,
            True,
            "approved account recovery",
            ACTOR_ID,
            "administrative-recovery",
        ),
    ) in flow.calls


SETTINGS_ACCESS_PATH = f"/api/v1/users/{USER_ID}/settings-access"
SETTINGS_ACCESS_REMOVE_PATH = f"/api/v1/users/{USER_ID}/settings-access/remove"
ASSIGNMENT_REMOVE_PATH = f"/api/v1/users/{USER_ID}/role-assignments/remove"
OWNER_ONLY_ROUTES: tuple[tuple[str, dict[str, object]], ...] = (
    (SETTINGS_ACCESS_PATH, {"reason": "Keeps the riel rate"}),
    (SETTINGS_ACCESS_REMOVE_PATH, {"reason": "Back to daily work"}),
    (
        ASSIGNMENT_REMOVE_PATH,
        {"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "Cover week ended"},
    ),
)


def test_settings_access_and_assignment_removal_need_actor_capability_scope_and_browser_proof() -> (
    None
):
    """Login sub-slice L2b-1 (DL-081; Q-2026-10-21-158 (a), Q-166 (a))."""
    for path, payload in OWNER_ONLY_ROUTES:
        flow = RecordingAccessAdministrationFlow()
        unauthenticated = request(
            create_app(Settings(), access_administration_flow=flow),
            "POST",
            path,
            payload=payload,
        )
        assert unauthenticated.status_code == 401, path
        assert unauthenticated.json()["error"]["code"] == "UNAUTHORIZED"
        no_capability = request(
            create_app(
                Settings(),
                actor_resolver=lambda _: AuthenticatedActor(actor_id=ACTOR_ID),
                access_administration_flow=flow,
            ),
            "POST",
            path,
            payload=payload,
        )
        assert no_capability.status_code == 403, path
        no_scope = request(authorized_app(flow, object_scopes=()), "POST", path, payload=payload)
        assert no_scope.status_code == 403, path
        no_browser_proof = request(
            authorized_app(flow), "POST", path, payload=payload, browser_protection=False
        )
        assert no_browser_proof.status_code == 403, path
        wrong_origin = request(
            authorized_app(flow),
            "POST",
            path,
            payload=payload,
            headers={"Origin": "https://attacker.invalid"},
        )
        assert wrong_origin.status_code == 403, path
        assert flow.calls == [], path
        other_property = request(
            authorized_app(flow, property_ids=(OTHER_PROPERTY_ID,)), "POST", path, payload=payload
        )
        assert other_property.status_code == 403, path
        assert flow.calls == [("user_property_id", USER_ID)], path

    bundle_flow = RecordingAccessAdministrationFlow()
    no_bundle_scope = request(
        authorized_app(
            bundle_flow,
            object_scopes=(
                ObjectScope(object_type=USER_ACCOUNT_OBJECT_TYPE, object_id=str(USER_ID)),
            ),
        ),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "Cover week ended"},
    )
    assert no_bundle_scope.status_code == 403
    assert bundle_flow.calls == []


def test_settings_access_is_given_and_removed_by_the_session_actor_with_a_reason() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)

    given = request(
        app,
        "POST",
        SETTINGS_ACCESS_PATH,
        payload={"reason": "  Keeps the riel rate  "},
        request_id="settings-access-give",
    )
    removed = request(
        app,
        "POST",
        SETTINGS_ACCESS_REMOVE_PATH,
        payload={"reason": "Back to daily work"},
        request_id="settings-access-remove",
    )

    assert given.status_code == 200
    assert given.json()["data"]["user_id"] == str(USER_ID)
    assert given.json()["data"]["settings_access"] is True
    assert removed.status_code == 200
    assert removed.json()["data"]["settings_access"] is False
    assert flow.calls == [
        ("user_property_id", USER_ID),
        (
            "give_settings_access",
            (USER_ID, PROPERTY_ID, "Keeps the riel rate", ACTOR_ID, "settings-access-give"),
        ),
        ("user_property_id", USER_ID),
        (
            "remove_settings_access",
            (USER_ID, PROPERTY_ID, "Back to daily work", ACTOR_ID, "settings-access-remove"),
        ),
    ]

    wrong_user = replace(flow.account, user_id=CREATED_USER_ID)
    mismatched = request(
        authorized_app(RecordingAccessAdministrationFlow(account=wrong_user)),
        "POST",
        SETTINGS_ACCESS_PATH,
        payload={"reason": "Keeps the riel rate"},
    )
    assert mismatched.status_code == 503


def test_a_role_bundle_is_removed_from_an_account_of_the_same_property_with_a_reason() -> None:
    flow = RecordingAccessAdministrationFlow()

    removed = request(
        authorized_app(flow),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": " Cover week ended "},
        request_id="assignment-remove",
    )

    assert removed.status_code == 200
    assert removed.json()["data"] == {
        "user_id": str(USER_ID),
        "role_bundle_id": str(ROLE_BUNDLE_ID),
        "property_id": PROPERTY_ID,
    }
    assert flow.calls == [
        ("user_property_id", USER_ID),
        ("role_bundle_property_id", ROLE_BUNDLE_ID),
        (
            "remove_role_assignment",
            (
                USER_ID,
                ROLE_BUNDLE_ID,
                PROPERTY_ID,
                "Cover week ended",
                ACTOR_ID,
                "assignment-remove",
            ),
        ),
    ]

    other_property_flow = RecordingAccessAdministrationFlow(role_bundle_property=OTHER_PROPERTY_ID)
    other_property = request(
        authorized_app(other_property_flow, property_ids=(PROPERTY_ID, OTHER_PROPERTY_ID)),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "Cover week ended"},
    )
    assert other_property.status_code == 409
    assert [call[0] for call in other_property_flow.calls] == [
        "user_property_id",
        "role_bundle_property_id",
    ]

    mismatched = request(
        authorized_app(RecordingAccessAdministrationFlow(assignment_user_id=CREATED_USER_ID)),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload={"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "Cover week ended"},
    )
    assert mismatched.status_code == 503


def test_settings_access_and_assignment_removal_need_a_valid_reason_and_known_fields() -> None:
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)
    invalid_requests: tuple[tuple[str, dict[str, object]], ...] = (
        (SETTINGS_ACCESS_PATH, {}),
        (SETTINGS_ACCESS_PATH, {"reason": "   "}),
        (SETTINGS_ACCESS_PATH, {"reason": "x" * 501}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps the riel rate", "capability": "settings.manage"}),
        (SETTINGS_ACCESS_REMOVE_PATH, {"reason": ""}),
        # Review round 1 (security): no control, line-break or direction characters.
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\x00the riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\nthe riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\u2028the riel rate"}),
        # Review round 2: one example of each other refused kind, and a reason with nothing
        # visible in it.
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\x7fthe riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\x85the riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\u2029the riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\u061cthe riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "Keeps\u200ethe riel rate"}),
        (SETTINGS_ACCESS_PATH, {"reason": "\u200b"}),
        (SETTINGS_ACCESS_REMOVE_PATH, {"reason": "\u200b \u200c\u200d"}),
        (SETTINGS_ACCESS_REMOVE_PATH, {"reason": "Back to \u202edaily work"}),
        (ASSIGNMENT_REMOVE_PATH, {"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "End\u2066ed"}),
        (ASSIGNMENT_REMOVE_PATH, {"reason": "Cover week ended"}),
        (ASSIGNMENT_REMOVE_PATH, {"role_bundle_id": str(ROLE_BUNDLE_ID)}),
        (ASSIGNMENT_REMOVE_PATH, {"role_bundle_id": "Manager", "reason": "Cover week ended"}),
        # Q-2026-10-21-152 (a): the Owner creates Manager or Staff accounts only, and the class
        # sets the MFA policy, so the request names no Owner class and no MFA policy.
        (
            f"/api/v1/properties/{PROPERTY_ID}/users",
            {
                "username": "second.owner",
                "display_name": "Second Owner",
                "audit_name": "second-owner",
                "account_class": "owner",
            },
        ),
        (
            f"/api/v1/properties/{PROPERTY_ID}/users",
            {
                "username": "operator",
                "display_name": "Operator",
                "audit_name": "operator-audit",
                "account_class": "staff",
                "mfa_policy_class": "required",
            },
        ),
    )

    for path, payload in invalid_requests:
        response = request(app, "POST", path, payload=payload)
        assert response.status_code == 422, (path, payload, response.text)
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    accepted = request(app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": "x" * 500})
    assert accepted.status_code == 200
    # Q-2026-10-22-169 (a): a Khmer reason is passed on without its zero-width space (U+200B).
    khmer = "\u1790\u17c2\u179a\u1780\u17d2\u179f\u17b6\u200b\u17a2\u178f\u17d2\u179a\u17b6"
    accepted_khmer = request(app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": khmer})
    assert accepted_khmer.status_code == 200
    assert [call[0] for call in flow.calls] == [
        "user_property_id",
        "give_settings_access",
        "user_property_id",
        "give_settings_access",
    ]
    saved = khmer.replace("\u200b", "")
    assert flow.calls[-1][1] == (USER_ID, PROPERTY_ID, saved, ACTOR_ID, "access-admin-test")


def test_administration_results_must_match_the_change_that_was_asked() -> None:
    """Review round 1 (independent and security): a result that does not show the change asked
    for, or that names another account, bundle or Property, fails closed (503)."""
    account = replace(
        RecordingAccessAdministrationFlow().account, one_time_password=ONE_TIME_PASSWORD
    )
    staff_payload = {
        "username": "new.operator",
        "display_name": "New Operator",
        "audit_name": "new-operator-audit",
        "account_class": "staff",
    }
    wrong_results = (
        replace(account, account_class="manager", mfa_policy_class="optional"),
        replace(account, account_class="staff", mfa_policy_class="required"),
        replace(account, account_class="owner", mfa_policy_class="required"),
        replace(account, account_class=None, mfa_policy_class="optional"),
    )
    for wrong in wrong_results:
        created = request(
            authorized_app(RecordingAccessAdministrationFlow(created_account=wrong)),
            "POST",
            f"/api/v1/properties/{PROPERTY_ID}/users",
            payload=staff_payload,
        )
        assert created.status_code == 503, wrong
    right = replace(account, account_class="staff", mfa_policy_class="optional")
    created = request(
        authorized_app(RecordingAccessAdministrationFlow(created_account=right)),
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload=staff_payload,
    )
    assert created.status_code == 201
    # Login sub-slice L4: a new account without its first one-time password fails closed too.
    created = request(
        authorized_app(
            RecordingAccessAdministrationFlow(
                created_account=replace(right, one_time_password=None)
            )
        ),
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload=staff_payload,
    )
    assert created.status_code == 503

    for path, stale in ((SETTINGS_ACCESS_PATH, False), (SETTINGS_ACCESS_REMOVE_PATH, True)):
        response = request(
            authorized_app(RecordingAccessAdministrationFlow(settings_access_result=stale)),
            "POST",
            path,
            payload={"reason": "Keeps the riel rate"},
        )
        assert response.status_code == 503, path
        other_property = request(
            authorized_app(
                RecordingAccessAdministrationFlow(
                    account=replace(account, property_id=OTHER_PROPERTY_ID)
                )
            ),
            "POST",
            path,
            payload={"reason": "Keeps the riel rate"},
        )
        assert other_property.status_code == 503, path
        other_account = request(
            authorized_app(
                RecordingAccessAdministrationFlow(account=replace(account, user_id=CREATED_USER_ID))
            ),
            "POST",
            path,
            payload={"reason": "Keeps the riel rate"},
        )
        assert other_account.status_code == 503, path

    removal = {"role_bundle_id": str(ROLE_BUNDLE_ID), "reason": "Cover week ended"}
    other_bundle = request(
        authorized_app(
            RecordingAccessAdministrationFlow(assignment_role_bundle_id=OTHER_ROLE_BUNDLE_ID)
        ),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload=removal,
    )
    assert other_bundle.status_code == 503
    other_property_assignment = request(
        authorized_app(RecordingAccessAdministrationFlow(assignment_property_id=OTHER_PROPERTY_ID)),
        "POST",
        ASSIGNMENT_REMOVE_PATH,
        payload=removal,
    )
    assert other_property_assignment.status_code == 503

    for path, payload in OWNER_ONLY_ROUTES:
        flow = RecordingAccessAdministrationFlow(user_property=None)
        missing = request(authorized_app(flow), "POST", path, payload=payload)
        assert missing.status_code == 404, path
        assert flow.calls == [("user_property_id", USER_ID)], path
    bundle_flow = RecordingAccessAdministrationFlow(role_bundle_property=None)
    missing_bundle = request(
        authorized_app(bundle_flow), "POST", ASSIGNMENT_REMOVE_PATH, payload=removal
    )
    assert missing_bundle.status_code == 404
    assert [call[0] for call in bundle_flow.calls] == [
        "user_property_id",
        "role_bundle_property_id",
    ]


def test_names_and_reasons_lose_the_zero_width_space_and_refuse_other_hidden_characters() -> None:
    """DL-081, Q-2026-10-22-169 (a) (sub-slice L2c): the API removes U+200B from a name and a
    reason before the length rule and passes them on without it; a reason refuses the other
    hidden characters and keeps U+200C and U+200D, which Khmer text uses."""
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)
    sokha, chan = "\u179f\u17bb\u1781\u17b6", "\u1785\u17b6\u1793\u17cb"
    created = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload={
            "username": "\u200bsokha.chan",
            "display_name": f"{sokha}\u200b {chan}",
            "audit_name": "\u200b" + "x" * 128,
            "account_class": "staff",
        },
    )
    assert created.status_code == 201, created.text
    created_call = (
        PROPERTY_ID,
        "sokha.chan",
        f"{sokha} {chan}",
        "x" * 128,
        "staff",
        ACTOR_ID,
        "access-admin-test",
    )
    assert flow.calls[-1:] == [("create_user", created_call)]

    for character in (
        "\u00ad",
        "\u034f",
        "\u115f",
        "\u1160",
        "\u17b4",
        "\u17b5",
        "\u180e",
        "\u2060",
        "\u2064",
        "\u3164",
        "\ufeff",
        "\uffa0",
        "\ufff9",
        "\ufffb",
        "\U000e0001",
        "\U000e007f",
        # Review rounds 1 and 2: the other invisible characters.
        "\u180b",
        "\u2800",
        "\ufe00",
        "\ufe0e",
        "\ufff0",
        "\U0001bca0",
        "\U0001d173",
        "\U000e0100",
    ):
        refused = request(
            app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": f"Keeps{character}the rate"}
        )
        assert refused.status_code == 422, (hex(ord(character)), refused.text)
        assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
    assert flow.calls[-1:] == [("create_user", created_call)]

    # Review round 2: U+FE0F (the emoji keyboard's variation selector) is kept but is not a
    # visible character on its own.
    for invisible in ("\ufe0f", "\ufe0f\u200d", "\u200b\u200c"):
        refused = request(app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": invisible})
        assert refused.status_code == 422, (invisible.encode("unicode_escape"), refused.text)
        assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
    assert flow.calls[-1:] == [("create_user", created_call)]
    thanks = "Thanks \u2764\ufe0f"
    thanked = request(app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": thanks})
    assert thanked.status_code == 200, thanked.text
    assert flow.calls[-1:] == [
        ("give_settings_access", (USER_ID, PROPERTY_ID, thanks, ACTOR_ID, "access-admin-test"))
    ]

    joined = f"{sokha}\u200c{chan}\u200d"
    accepted = request(
        app, "POST", SETTINGS_ACCESS_PATH, payload={"reason": f"\u200b{joined}\u200b"}
    )
    assert accepted.status_code == 200, accepted.text
    assert flow.calls[-1:] == [
        ("give_settings_access", (USER_ID, PROPERTY_ID, joined, ACTOR_ID, "access-admin-test"))
    ]


def test_the_reason_list_differs_from_the_name_list_only_by_kept_invisible_characters() -> None:
    """Review round 2 of sub-slice L2c: the reason rule has no database twin, so this checks the
    whole list. Over every code point but the surrogates, a reason refuses a subset of what a
    name refuses, and the difference is exactly U+200C, U+200D (Khmer text) and U+FE0F (the
    emoji keyboard)."""
    points = [point for point in range(0x110000) if not 0xD800 <= point <= 0xDFFF]
    names = {point for point in points if HIDDEN_NAME_CHARACTERS.fullmatch(chr(point))}
    reasons = {point for point in points if HIDDEN_REASON_CHARACTERS.fullmatch(chr(point))}
    assert reasons <= names
    assert names - reasons == {0x200C, 0x200D, 0xFE0F}


def test_names_with_odd_or_double_spaces_reach_the_flow_tidied() -> None:
    """DL-081, Q-2026-10-22-170 (a) (login sub-slice L2d): the screen refuses no space; the API
    tidies a username, display name and audit name before the length rule (every space
    separator becomes U+0020, a run of them one, none at either end), so "Sokha  Chan" typed
    with two spaces on an iPad reaches the flow as "Sokha Chan" and the 128 limit counts the
    tidied name."""
    flow = RecordingAccessAdministrationFlow()
    app = authorized_app(flow)
    created = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload={
            "username": " Sokha\u00a0 Chan ",
            "display_name": "Sokha  Chan",
            "audit_name": "x" * 64 + "\u3000\u2009  " + "y" * 63,
            "account_class": "staff",
        },
    )
    assert created.status_code == 201, created.text
    assert flow.calls[-1:] == [
        (
            "create_user",
            (
                PROPERTY_ID,
                "Sokha Chan",
                "Sokha Chan",
                "x" * 64 + " " + "y" * 63,
                "staff",
                ACTOR_ID,
                "access-admin-test",
            ),
        )
    ]

    calls = len(flow.calls)
    too_long = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload={
            "username": "sokha.chan",
            "display_name": "x" * 64 + "  " + "y" * 64,
            "audit_name": "Sokha Chan",
            "account_class": "staff",
        },
    )
    assert too_long.status_code == 422
    assert len(flow.calls) == calls
    # Review round 1: a name made only of odd spaces is empty after tidying and refused.
    only_spaces = request(
        app,
        "POST",
        f"/api/v1/properties/{PROPERTY_ID}/users",
        payload={
            "username": "\u00a0\u3000 ",
            "display_name": "Sokha Chan",
            "audit_name": "Sokha Chan",
            "account_class": "staff",
        },
    )
    assert only_spaces.status_code == 422
    assert len(flow.calls) == calls
    # Review round 1: the Owner's reset reason is free text, not a name; since L4 it follows the
    # reason rule, so its spaces stay as typed and only U+200B is removed.
    recovery = AdministrativeRecoveryRequest(reason="forgot  password\u200b again")
    assert recovery.reason == "forgot  password again"


def test_the_routes_pass_both_browser_cookies_to_the_flow_and_never_show_them() -> None:
    """Login sub-slice L3d-2: the route hands the flow the session and reauthentication cookies
    for the recent-reauthentication check, kept out of the context's repr; without them the
    context carries none."""
    seen: list[AdministrationAuditContext] = []

    class SeeingFlow(RecordingAccessAdministrationFlow):
        def create_user(
            self,
            *,
            property_id: str,
            username: str,
            display_name: str,
            audit_name: str,
            account_class: Literal["manager", "staff"],
            audit_context: AdministrationAuditContext,
        ) -> UserAccountView:
            seen.append(audit_context)
            return super().create_user(
                property_id=property_id,
                username=username,
                display_name=display_name,
                audit_name=audit_name,
                account_class=account_class,
                audit_context=audit_context,
            )

    app = authorized_app(SeeingFlow())
    payload = {
        "username": "dara.staff",
        "display_name": "Dara",
        "audit_name": "Dara",
        "account_class": "staff",
    }
    path = f"/api/v1/properties/{PROPERTY_ID}/users"
    with_cookies = request(
        app,
        "POST",
        path,
        payload=payload,
        cookies={
            "__Host-prm_session": "session-cookie-secret",
            "__Host-prm_reauth": "reauthentication-cookie-secret",
        },
    )
    assert with_cookies.status_code == 201, with_cookies.text
    without = request(app, "POST", path, payload=payload)
    assert without.status_code == 201, without.text
    assert [(item.session_token, item.reauthentication_token) for item in seen] == [
        ("session-cookie-secret", "reauthentication-cookie-secret"),
        (None, None),
    ]
    assert "cookie-secret" not in repr(seen[0])


def test_turning_a_staff_accounts_mfa_off_answers_its_one_time_password_once() -> None:
    """Login sub-slice L4 (Q-2026-10-23-180 (a)): turning off the MFA of an account whose MFA was
    required gives it a one-time password, answered once and never cached; a one-time password
    with any other change fails closed (503), and other changes are answered without one."""
    flow = RecordingAccessAdministrationFlow(update_one_time_password=ONE_TIME_PASSWORD)
    turned_off = request(
        authorized_app(flow),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"mfa_policy_class": "optional"},
        request_id="mfa-off",
    )
    assert turned_off.status_code == 200
    assert turned_off.headers["cache-control"] == "no-store"
    assert turned_off.json()["data"]["mfa_policy_class"] == "optional"
    assert turned_off.json()["one_time_password"] == {
        "value": ONE_TIME_PASSWORD.value,
        "expires_at": "2026-10-25T03:00:00Z",
    }

    for payload in ({"display_name": "Renamed"}, {"mfa_policy_class": "required"}):
        unexpected = request(
            authorized_app(
                RecordingAccessAdministrationFlow(update_one_time_password=ONE_TIME_PASSWORD)
            ),
            "PATCH",
            f"/api/v1/users/{USER_ID}",
            payload=payload,
        )
        assert unexpected.status_code == 503, payload
        assert ONE_TIME_PASSWORD.value not in unexpected.text
    renamed = request(
        authorized_app(RecordingAccessAdministrationFlow()),
        "PATCH",
        f"/api/v1/users/{USER_ID}",
        payload={"display_name": "Renamed"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["one_time_password"] is None
