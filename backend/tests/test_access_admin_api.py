"""API-079/080 account and configurable capability administration tests."""

import asyncio
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
    AdministrativeRecoveryView,
    AuthorizationHistoryView,
    CapabilityView,
    RoleAssignmentView,
    RoleBundleView,
    UserAccountView,
)
from property_rental.app import create_app
from property_rental.auth_api import CSRF_COOKIE_NAME
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.settings import Settings

PROPERTY_ID = "property-main"
OTHER_PROPERTY_ID = "property-other"
ACTOR_ID = "access-administrator"
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
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
        mfa_policy_class: Literal["required", "optional"],
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
                    mfa_policy_class,
                    audit_context.actor_id,
                    audit_context.request_id,
                ),
            )
        )
        return UserAccountView(
            user_id=CREATED_USER_ID,
            property_id=property_id,
            username=username,
            display_name=display_name,
            audit_name=audit_name,
            lifecycle_state="active",
            mfa_policy_class=mfa_policy_class,
            version=1,
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
        new_password: str,
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
                    new_password,
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
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        cookies = {CSRF_COOKIE_NAME: CSRF_TOKEN} if browser_protection else None
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies=cookies,
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
        "mfa_policy_class",
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
                "mfa_policy_class": "required",
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
                "mfa_policy_class": "optional",
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
            "mfa_policy_class": "optional",
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
        }
    ]
    assert listed.json()["page"] == {"next_cursor": "next-users", "limit": 50}
    assert created.status_code == 201
    assert created.headers["Location"] == f"/api/v1/users/{CREATED_USER_ID}"
    assert created.json()["data"]["user_id"] == str(CREATED_USER_ID)
    assert created.json()["data"]["lifecycle_state"] == "active"
    assert created.json()["data"]["version"] == 1
    assert "password" not in created.text.lower()
    assert "credential" not in created.text.lower()
    assert flow.calls == [
        ("list_users", (PROPERTY_ID, None, 50, ACTOR_ID, "accounts-list")),
        (
            "create_user",
            (
                PROPERTY_ID,
                "new.operator",
                "New Operator",
                "new-operator-audit",
                "optional",
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
                "mfa_policy_class": "optional",
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
    payload = {
        "new_password": "a sufficiently long replacement password",
        "reset_mfa": True,
        "reason": "approved account recovery",
    }

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

    assert response.status_code == 200
    assert response.json()["data"] == {
        "user_id": str(USER_ID),
        "password_changed": True,
        "mfa_reset": True,
        "sessions_revoked": 3,
    }
    assert denied.status_code == 403
    assert (
        "administratively_recover_user",
        (
            USER_ID,
            PROPERTY_ID,
            "a sufficiently long replacement password",
            True,
            "approved account recovery",
            ACTOR_ID,
            "administrative-recovery",
        ),
    ) in flow.calls
