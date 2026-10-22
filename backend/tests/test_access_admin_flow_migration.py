"""PostgreSQL account and role bundle administration flow (login slice sub-slice L2b-2).

API-079, API-080, DL-081, SEC-014, SEC-021, SEC-075, DB-AUTH-010: the flow changes accounts,
bundles, assignments and Settings access only through the audited `app.admin_*` functions, as the
runtime role, and answers every refusal with a stable code. Every test uses one throwaway database
at head (so an Owner may be committed there), shared by this module.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from property_rental.access_admin_api import (
    ACCESS_ADMIN_CAPABILITY,
    ROLE_BUNDLE_OBJECT_TYPE,
    USER_ACCOUNT_OBJECT_TYPE,
    AccessAdministrationNotFound,
    AccessAdministrationRejected,
    AccessAdministrationUnavailable,
    AdministrationAuditContext,
)
from property_rental.access_admin_flow import (
    SIGN_IN_CODE_MESSAGE,
    PostgresAccessAdministrationFlow,
    PostgresAccessAdministrationScopeReader,
    correlation_id,
    with_administration_scopes,
)
from property_rental.access_control import BUNDLE_CAPABILITIES
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant, ObjectScope
from property_rental.settings import Settings
from test_access_admin_api import request
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property
from test_settings_access_migration import add_sign_in_code


@dataclass(frozen=True)
class AdminDatabase:
    owner_url: str
    runtime_url: str
    property_id: str
    owner: uuid.UUID
    manager: uuid.UUID


@pytest.fixture(scope="module")
def admin_database(migrated_database_url: str) -> Iterator[AdminDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_access_admin_flow") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            setup.execute(SEED_QUERY, (property_id,))
            setup.commit()
        yield AdminDatabase(temporary, runtime_url, str(property_id), owner, manager)


def context(actor: uuid.UUID | str, request_id: str | None = None) -> AdministrationAuditContext:
    return AdministrationAuditContext(
        actor_id=str(actor), request_id=request_id or str(uuid.uuid4())
    )


def refused(code: str, status: int, call: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(AccessAdministrationRejected) as caught:
        call(*args, **kwargs)
    assert (caught.value.status_code, caught.value.code) == (status, code)


def audit_actions(database: AdminDatabase, request_id: str) -> list[str]:
    with psycopg.connect(database.owner_url) as connection:
        rows = connection.execute(
            "SELECT action FROM app.audit_events WHERE correlation_id = %s ORDER BY occurred_at",
            (correlation_id(request_id),),
        ).fetchall()
    return [str(row[0]) for row in rows]


def new_staff(database: AdminDatabase, flow: PostgresAccessAdministrationFlow, name: str) -> Any:
    return flow.create_user(
        property_id=database.property_id,
        username=f"{name}-{uuid.uuid4().hex[:8]}",
        display_name=name,
        audit_name=name,
        account_class="staff",
        audit_context=context(database.owner),
    )


def test_the_flow_creates_lists_and_changes_accounts_through_the_audited_functions(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    suffix = uuid.uuid4().hex[:8]
    created = flow.create_user(
        property_id=database.property_id,
        username=f" Dara.Manager-{suffix}",
        display_name="Dara   Sok",
        audit_name="Dara Sok",
        account_class="manager",
        audit_context=context(database.owner, "create-dara"),
    )
    assert (created.username, created.display_name) == (f"dara.manager-{suffix}", "Dara Sok")
    assert (created.account_class, created.mfa_policy_class, created.version) == (
        "manager",
        "required",
        1,
    )
    assert (created.lifecycle_state, created.settings_access) == ("active", False)
    assert created.property_id == database.property_id
    # A request id that is not a UUID becomes a stable UUID5 correlation id.
    assert audit_actions(database, "create-dara") == ["identity.account.created"]
    staff = new_staff(database, flow, "Sokha")
    assert (staff.account_class, staff.mfa_policy_class) == ("staff", "optional")

    seen: list[str] = []
    cursor = None
    while True:
        page, cursor = flow.list_users(
            property_id=database.property_id,
            cursor=cursor,
            limit=2,
            actor_id=str(database.owner),
            request_id="list",
        )
        assert len(page) <= 2
        seen.extend(str(account.user_id) for account in page)
        if cursor is None:
            break
    assert seen == sorted(seen) and len(seen) == len(set(seen))
    assert {str(database.owner), str(created.user_id), str(staff.user_id)} <= set(seen)

    updated = flow.update_user(
        user_id=staff.user_id,
        property_id=database.property_id,
        expected_version=1,
        display_name="Sokha  Chan",
        audit_name=None,
        lifecycle_state=None,
        mfa_policy_class=None,
        revoke_applicable_sessions_if_disabled=True,
        audit_context=context(database.owner),
    )
    assert (updated.display_name, updated.version) == ("Sokha Chan", 2)
    change: dict[str, Any] = {
        "user_id": staff.user_id,
        "property_id": database.property_id,
        "display_name": "Again",
        "audit_name": None,
        "lifecycle_state": None,
        "mfa_policy_class": None,
        "revoke_applicable_sessions_if_disabled": True,
    }
    refused(
        "STALE_VERSION",
        412,
        flow.update_user,
        expected_version=1,
        audit_context=context(database.owner),
        **change,
    )
    manager_change = {**change, "user_id": created.user_id, "display_name": None}
    manager_change["mfa_policy_class"] = "optional"
    refused(
        "MANAGER_MFA_REQUIRED",
        422,
        flow.update_user,
        expected_version=1,
        audit_context=context(database.owner),
        **manager_change,
    )
    refused(
        "OWNER_ACCOUNT_NOT_CHANGED",
        422,
        flow.update_user,
        expected_version=1,
        audit_context=context(database.owner),
        **{**change, "user_id": database.owner},
    )
    disabled = flow.update_user(
        expected_version=2,
        audit_context=context(database.owner),
        **{**change, "display_name": None, "lifecycle_state": "disabled"},
    )
    assert (disabled.lifecycle_state, disabled.version) == ("disabled", 3)
    refused(
        "ACCOUNT_DISABLED",
        409,
        flow.update_user,
        expected_version=3,
        audit_context=context(database.owner),
        **change,
    )
    refused(
        "USERNAME_TAKEN",
        409,
        flow.create_user,
        property_id=database.property_id,
        username=f"DARA.MANAGER-{suffix}",
        display_name="Other Dara",
        audit_name="Other Dara",
        account_class="staff",
        audit_context=context(database.owner),
    )
    for display_name, code in (
        # Q-2026-10-22-169 (a): U+200B is now removed before saving (sub-slice L2c), so the
        # refused hidden character here is the direction mark U+200E (the L2a character list).
        ("Dara\u200eSok", "INVALID_NAME"),
        ("Dara\x00Sok", "VALIDATION_ERROR"),
    ):
        refused(
            code,
            422,
            flow.create_user,
            property_id=database.property_id,
            username=f"hidden-{uuid.uuid4().hex[:8]}",
            display_name=display_name,
            audit_name="Hidden",
            account_class="staff",
            audit_context=context(database.owner),
        )
    assert flow.user_property_id(user_id=staff.user_id) == database.property_id
    assert flow.user_property_id(user_id=uuid.uuid4()) is None
    assert (
        flow.revoke_user_sessions(user_id=created.user_id, audit_context=context(database.owner))
        == 0
    )


def test_the_flow_administers_role_bundles_and_assignments(admin_database: AdminDatabase) -> None:
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    listed: list[str] = []
    cursor = None
    while True:
        page, cursor = flow.list_capabilities(
            cursor=cursor, limit=50, actor_id=str(database.owner), request_id="capabilities"
        )
        listed.extend(capability.capability_id for capability in page)
        if cursor is None:
            break
    assert listed == sorted(BUNDLE_CAPABILITIES)

    name = f"Night desk {uuid.uuid4().hex[:6]}"
    bundle = flow.create_role_bundle(
        property_id=database.property_id,
        name=f"{name}  ",
        capability_ids=("payments.read", "payments.record", "payments.read"),
        audit_context=context(database.owner),
    )
    assert (bundle.name, bundle.version) == (name, 1)
    assert set(bundle.capability_ids) == {"payments.read", "payments.record"}
    refused(
        "CAPABILITY_NOT_ASSIGNABLE",
        422,
        flow.create_role_bundle,
        property_id=database.property_id,
        name=f"Settings {uuid.uuid4().hex[:6]}",
        capability_ids=("settings.manage",),
        audit_context=context(database.owner),
    )
    refused(
        "ROLE_BUNDLE_NAME_TAKEN",
        409,
        flow.create_role_bundle,
        property_id=database.property_id,
        name=name.upper(),
        capability_ids=(),
        audit_context=context(database.owner),
    )
    refused(
        "INVALID_NAME",
        422,
        flow.create_role_bundle,
        property_id=database.property_id,
        # Q-2026-10-22-169 (a): U+200B is now removed before saving (sub-slice L2c); the direction
        # mark U+200E stays refused by the L1b-2 check `role_bundles_name_check`.
        name="Night\u200edesk",
        capability_ids=(),
        audit_context=context(database.owner),
    )
    renamed = flow.update_role_bundle(
        role_bundle_id=bundle.role_bundle_id,
        property_id=database.property_id,
        expected_version=1,
        name=f"{name} late",
        capability_ids=None,
        revoke_affected_sessions_on_capability_reduction=True,
        audit_context=context(database.owner),
    )
    assert (renamed.name, renamed.version, renamed.capability_ids) == (
        f"{name} late",
        2,
        bundle.capability_ids,
    )
    refused(
        "STALE_VERSION",
        412,
        flow.update_role_bundle,
        role_bundle_id=bundle.role_bundle_id,
        property_id=database.property_id,
        expected_version=1,
        name="Stale",
        capability_ids=None,
        revoke_affected_sessions_on_capability_reduction=True,
        audit_context=context(database.owner),
    )
    bundles, _ = flow.list_role_bundles(
        property_id=database.property_id,
        cursor=None,
        limit=100,
        actor_id=str(database.owner),
        request_id="bundles",
    )
    assert {"Owner", "Manager", "Staff", f"{name} late"} <= {item.name for item in bundles}
    assert (
        flow.role_bundle_property_id(role_bundle_id=bundle.role_bundle_id) == database.property_id
    )

    staff = new_staff(database, flow, "Vanna")
    assignment = {
        "user_id": staff.user_id,
        "role_bundle_id": bundle.role_bundle_id,
        "property_id": database.property_id,
    }
    assigned = flow.assign_role_bundle(**assignment, audit_context=context(database.owner))
    assert (assigned.user_id, assigned.role_bundle_id) == (staff.user_id, bundle.role_bundle_id)
    refused(
        "ROLE_BUNDLE_ALREADY_ASSIGNED",
        409,
        flow.assign_role_bundle,
        **assignment,
        audit_context=context(database.owner),
    )
    removal_id = str(uuid.uuid4())
    flow.remove_role_assignment(
        **assignment, reason="Cover week ended", audit_context=context(database.owner, removal_id)
    )
    assert audit_actions(database, removal_id) == ["identity.role_assignment.removed"]
    refused(
        "ROLE_BUNDLE_NOT_ASSIGNED",
        409,
        flow.remove_role_assignment,
        **assignment,
        reason="Again",
        audit_context=context(database.owner),
    )
    with pytest.raises(AccessAdministrationNotFound):
        flow.assign_role_bundle(
            **{**assignment, "role_bundle_id": uuid.uuid4()}, audit_context=context(database.owner)
        )


def test_the_flow_gives_and_removes_settings_access_with_the_sign_in_code_rule(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    staff = new_staff(database, flow, "Dara")
    access = {"user_id": staff.user_id, "property_id": database.property_id}
    with pytest.raises(AccessAdministrationRejected) as caught:
        flow.give_settings_access(
            **access, reason="Keeps the riel rate", audit_context=context(database.owner)
        )
    assert (caught.value.status_code, caught.value.code, caught.value.message) == (
        409,
        "SIGN_IN_CODE_REQUIRED",
        SIGN_IN_CODE_MESSAGE,
    )
    with psycopg.connect(database.owner_url) as setup:
        add_sign_in_code(setup, staff.user_id)
        setup.commit()
    give_id = str(uuid.uuid4())
    given = flow.give_settings_access(
        **access, reason="Keeps the riel rate", audit_context=context(database.owner, give_id)
    )
    assert given.settings_access is True
    assert audit_actions(database, give_id) == ["identity.settings_access.given"]
    refused(
        "SETTINGS_ACCESS_ALREADY_GIVEN",
        409,
        flow.give_settings_access,
        **access,
        reason="Again",
        audit_context=context(database.owner),
    )
    removed = flow.remove_settings_access(
        **access, reason="Back to daily work", audit_context=context(database.owner)
    )
    assert removed.settings_access is False
    refused(
        "NO_SETTINGS_ACCESS",
        409,
        flow.remove_settings_access,
        **access,
        reason="Again",
        audit_context=context(database.owner),
    )
    refused(
        "NOT_MANAGER_OR_STAFF",
        422,
        flow.give_settings_access,
        user_id=database.owner,
        property_id=database.property_id,
        reason="The Owner",
        audit_context=context(database.owner),
    )


def test_a_non_owner_or_unknown_actor_is_refused_and_recovery_stays_unavailable(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    for actor in (database.manager, "not-a-uuid", uuid.uuid4()):
        refused(
            "FORBIDDEN",
            403,
            flow.list_users,
            property_id=database.property_id,
            cursor=None,
            limit=10,
            actor_id=str(actor),
            request_id="denied",
        )
        refused(
            "FORBIDDEN",
            403,
            flow.create_user,
            property_id=database.property_id,
            username=f"denied-{uuid.uuid4().hex[:8]}",
            display_name="Denied",
            audit_name="Denied",
            account_class="staff",
            audit_context=context(actor),
        )
        # Review round 1 (security): the reads the runtime role could do alone are checked too.
        refused(
            "FORBIDDEN",
            403,
            flow.list_authorization_history,
            property_id=database.property_id,
            cursor=None,
            limit=10,
            actor_id=str(actor),
            request_id="denied",
        )
        refused(
            "FORBIDDEN",
            403,
            flow.list_capabilities,
            cursor=None,
            limit=10,
            actor_id=str(actor),
            request_id="denied",
        )
    with pytest.raises(AccessAdministrationNotFound):
        flow.revoke_user_sessions(user_id=uuid.uuid4(), audit_context=context(database.owner))
    refused(
        "VALIDATION_ERROR",
        422,
        flow.list_users,
        property_id=database.property_id,
        cursor="Owner",
        limit=10,
        actor_id=str(database.owner),
        request_id="cursor",
    )
    with pytest.raises(AccessAdministrationUnavailable):
        flow.administratively_recover_user(
            user_id=database.manager,
            property_id=database.property_id,
            new_password="",
            reset_mfa=False,
            reason="Not before L4",
            audit_context=context(database.owner),
        )


def test_the_authorization_history_lists_administration_events_oldest_first_in_pages(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    first = new_staff(database, flow, "History one")
    second = new_staff(database, flow, "History two")
    events: list[Any] = []
    cursor = None
    while True:
        page, cursor = flow.list_authorization_history(
            property_id=database.property_id,
            cursor=cursor,
            limit=2,
            actor_id=str(database.owner),
            request_id="history",
        )
        assert len(page) <= 2
        events.extend(page)
        if cursor is None:
            break
    assert [event.occurred_at for event in events] == sorted(event.occurred_at for event in events)
    assert len({event.event_id for event in events}) == len(events)
    created = [event.target_id for event in events if event.action == "identity.account.created"]
    assert created.index(str(first.user_id)) < created.index(str(second.user_id))
    assert {event.outcome for event in events} == {"completed"}
    assert all(event.actor_id == str(database.owner) for event in events)


def test_the_owner_gets_object_scopes_for_every_account_and_bundle(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    reader = PostgresAccessAdministrationScopeReader(database.runtime_url)
    scopes = reader.object_scopes(database.owner)
    with psycopg.connect(database.owner_url) as check:
        accounts = {str(row[0]) for row in check.execute("SELECT actor_id FROM app.user_accounts")}
        bundles = {
            str(row[0]) for row in check.execute("SELECT role_bundle_id FROM app.role_bundles")
        }
    assert scopes == {ObjectScope(USER_ACCOUNT_OBJECT_TYPE, item) for item in accounts} | {
        ObjectScope(ROLE_BUNDLE_OBJECT_TYPE, item) for item in bundles
    }
    assert reader.object_scopes(database.manager) == frozenset()
    # Review round 2: an error other than the Owner refusal is unavailable, never no scope.
    missing = _url_with_database(database.runtime_url, f"prm_missing_{uuid.uuid4().hex}")
    with pytest.raises(AccessAdministrationUnavailable):
        PostgresAccessAdministrationScopeReader(missing).object_scopes(database.owner)
    grants = frozenset(
        {
            CapabilityGrant(ACCESS_ADMIN_CAPABILITY, frozenset({database.property_id})),
            CapabilityGrant("payments.read", frozenset({database.property_id})),
        }
    )
    scoped = {grant.capability: grant for grant in with_administration_scopes(grants, scopes)}
    assert scoped[ACCESS_ADMIN_CAPABILITY].object_scopes == scopes
    assert scoped[ACCESS_ADMIN_CAPABILITY].property_ids == frozenset({database.property_id})
    assert scoped["payments.read"].object_scopes == frozenset()


def test_create_app_administers_through_postgresql_when_a_database_is_configured(
    admin_database: AdminDatabase,
) -> None:
    database = admin_database
    actor = AuthenticatedActor(
        actor_id=str(database.owner),
        capability_grants=with_administration_scopes(
            frozenset(
                {CapabilityGrant(ACCESS_ADMIN_CAPABILITY, frozenset({database.property_id}))}
            ),
            PostgresAccessAdministrationScopeReader(database.runtime_url).object_scopes(
                database.owner
            ),
        ),
    )
    app = create_app(
        Settings(APP_DATABASE_URL=database.runtime_url),
        readiness_check=lambda _: None,
        actor_resolver=lambda _: actor,
    )
    created = request(
        app,
        "POST",
        f"/api/v1/properties/{database.property_id}/users",
        payload={
            "username": f"http-{uuid.uuid4().hex[:8]}",
            "display_name": "Http Staff",
            "audit_name": "Http Staff",
            "account_class": "staff",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["account_class"] == "staff"
    # The new account is not yet in this request's object scopes; it is from the next one.
    staff_id = created.json()["data"]["user_id"]
    scoped_actor = AuthenticatedActor(
        actor_id=actor.actor_id,
        capability_grants=with_administration_scopes(
            actor.capability_grants,
            frozenset({ObjectScope(USER_ACCOUNT_OBJECT_TYPE, staff_id)}),
        ),
    )
    scoped_app = create_app(
        Settings(APP_DATABASE_URL=database.runtime_url),
        readiness_check=lambda _: None,
        actor_resolver=lambda _: scoped_actor,
    )
    refusal = request(
        scoped_app,
        "POST",
        f"/api/v1/users/{staff_id}/settings-access",
        payload={"reason": "Keeps the riel rate"},
    )
    assert refusal.status_code == 409
    assert refusal.json()["error"] == {
        "code": "SIGN_IN_CODE_REQUIRED",
        "message": SIGN_IN_CODE_MESSAGE,
        "fields": [],
        "rule_ids": [],
        "current_version": None,
    }
    assert "app." not in refusal.text and "ERROR" not in refusal.text


class MismatchedResultFlow(PostgresAccessAdministrationFlow):
    """A flow whose read-back shows another version than the change made."""

    def _account(self, connection: Any, owner: uuid.UUID, user_id: uuid.UUID) -> Any:
        return replace(super()._account(connection, owner, user_id), version=99)


def test_the_flow_refuses_each_reachable_case_and_rolls_back_a_mismatched_result(
    admin_database: AdminDatabase,
) -> None:
    """Review round 1: the codes the API can reach that the other tests do not show, and a
    result check that fails before the commit leaves no change and no audit event."""
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    with psycopg.connect(database.owner_url) as setup:
        unclassified = add_account(setup, None)
        setup.commit()
    change: dict[str, Any] = {
        "property_id": database.property_id,
        "expected_version": 1,
        "display_name": "Renamed",
        "audit_name": None,
        "lifecycle_state": None,
        "mfa_policy_class": None,
        "revoke_applicable_sessions_if_disabled": True,
    }
    refused(
        "ACCOUNT_WITHOUT_CLASS",
        422,
        flow.update_user,
        user_id=unclassified,
        audit_context=context(database.owner),
        **change,
    )
    with pytest.raises(AccessAdministrationNotFound):
        flow.update_user(user_id=uuid.uuid4(), audit_context=context(database.owner), **change)
    refused(
        "NOT_MANAGER_OR_STAFF",
        422,
        flow.revoke_user_sessions,
        user_id=database.owner,
        audit_context=context(database.owner),
    )
    refused(
        "INVALID_NAME",
        422,
        flow.update_user,
        user_id=database.manager,
        audit_context=context(database.owner),
        **{**change, "display_name": "Dara\nSok"},
    )
    refused(
        "INVALID_NAME",
        422,
        flow.create_user,
        property_id=database.property_id,
        # Q-2026-10-22-170 (a) (sub-slice L2d): a no-break space is now tidied into an ordinary
        # space (test_name_hidden_characters_migration.py); a tab is still refused.
        username="ann\tlee",
        display_name="Ann Lee",
        audit_name="Ann Lee",
        account_class="staff",
        audit_context=context(database.owner),
    )
    with pytest.raises(AccessAdministrationNotFound):
        flow.list_role_bundles(
            property_id=str(uuid.uuid4()),
            cursor=None,
            limit=10,
            actor_id=str(database.owner),
            request_id="other-property",
        )
    with pytest.raises(AccessAdministrationNotFound):
        flow.list_authorization_history(
            property_id=str(uuid.uuid4()),
            cursor=None,
            limit=10,
            actor_id=str(database.owner),
            request_id="other-property",
        )

    request_id = str(uuid.uuid4())
    username = f"rolled-back-{uuid.uuid4().hex[:8]}"
    with pytest.raises(AccessAdministrationUnavailable):
        MismatchedResultFlow(database.runtime_url).create_user(
            property_id=database.property_id,
            username=username,
            display_name="Rolled Back",
            audit_name="Rolled Back",
            account_class="staff",
            audit_context=context(database.owner, request_id),
        )
    assert audit_actions(database, request_id) == []
    with psycopg.connect(database.owner_url) as check:
        assert check.execute(
            "SELECT count(*) FROM app.user_accounts WHERE normalized_username = %s",
            (username,),
        ).fetchone() == (0,)
