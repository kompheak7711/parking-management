"""PostgreSQL account and role bundle administration flow (login slice sub-slice L2b-2).

API-079, API-080, DL-081, SEC-014, SEC-021, SEC-075, DB-AUTH-010: the flow changes accounts,
bundles, assignments and Settings access only through the audited `app.admin_*` functions, as the
runtime role, and answers every refusal with a stable code. Every test uses one throwaway database
at head (so an Owner may be committed there), shared by this module.
"""

from __future__ import annotations

import secrets
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
    REAUTHENTICATION_REQUIRED_MESSAGE,
    RECENT_REAUTHENTICATION,
    SIGN_IN_CODE_MESSAGE,
    PostgresAccessAdministrationFlow,
    PostgresAccessAdministrationScopeReader,
    correlation_id,
    with_administration_scopes,
)
from property_rental.access_control import BUNDLE_CAPABILITIES
from property_rental.app import create_app
from property_rental.auth_api import REAUTHENTICATION_COOKIE_NAME, SESSION_COOKIE_NAME
from property_rental.auth_flow import session_token_digest
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
        allow_admin_actions(temporary, owner, manager)
        yield AdminDatabase(temporary, runtime_url, str(property_id), owner, manager)


# Login sub-slice L3d-2: the actions that change who may do what need a recent reauthentication
# of the request's own session with the sign-in code. A module fixture names the actors of its
# database with `allow_admin_actions`; `context` then gives such an actor a fresh live session
# and a reauthentication of it on every call. The refusal without one has its own tests.
ADMIN_ACTION_DATABASES: dict[str, str] = {}
TEST_PROVENANCE = "login-slice-l3d-2-test"
ACTIVE_SIGN_IN_CODE = (
    "SELECT enrollment_id FROM app.totp_mfa_enrollments "
    "WHERE actor_id = %s AND enrollment_state = 'active'"
)
ADD_SIGN_IN_CODE = (
    "INSERT INTO app.totp_mfa_enrollments(enrollment_id,actor_id,secret_ciphertext,"
    "secret_nonce,key_identifier,protection_algorithm,totp_algorithm,created_by_actor_id,"
    "provenance) VALUES (%s,%s,%s,%s,%s,'aes-256-gcm','sha1',%s,%s)"
)
TURN_SIGN_IN_CODE_ON = (
    "UPDATE app.totp_mfa_enrollments SET enrollment_state='active',activated_by_actor_id=%s,"
    "activation_provenance=%s WHERE enrollment_id=%s"
)
NEXT_STEP = (
    "SELECT COALESCE(max(time_step), 0) + 1 FROM app.totp_used_steps WHERE enrollment_id = %s"
)
USE_STEP = "INSERT INTO app.totp_used_steps (enrollment_id, time_step) VALUES (%s, %s)"
ADD_SESSION = (
    "INSERT INTO app.browser_sessions (session_id, actor_id, token_verifier, "
    "verifier_algorithm, creation_provenance) VALUES (%s, %s, %s, 'sha256', %s)"
)
ADD_REAUTHENTICATION = (
    "INSERT INTO app.browser_session_reauthentications (reauthentication_id, session_id, "
    "actor_id, method, enrollment_id, time_step, token_verifier) "
    "VALUES (%s, %s, %s, 'totp', %s, %s, %s)"
)
ADD_OLD_REAUTHENTICATION = (
    "INSERT INTO app.browser_session_reauthentications (reauthentication_id, session_id, "
    "actor_id, method, enrollment_id, time_step, token_verifier, reauthenticated_at) "
    "VALUES (%s, %s, %s, 'totp', %s, %s, %s, statement_timestamp() - make_interval(mins => %s))"
)


def allow_admin_actions(owner_url: str, *actors: uuid.UUID) -> None:
    for actor in actors:
        ADMIN_ACTION_DATABASES[str(actor)] = owner_url


def sign_in_code_of(connection: psycopg.Connection[Any], actor: uuid.UUID | str) -> uuid.UUID:
    """The actor's active sign-in code; an actor without one gets one (its MFA policy is left as
    it is). Written as the table owner, not committed."""
    active = connection.execute(ACTIVE_SIGN_IN_CODE, (actor,)).fetchone()
    if active is not None:
        return uuid.UUID(str(active[0]))
    enrollment_id = uuid.uuid4()
    connection.execute(
        ADD_SIGN_IN_CODE,
        (
            enrollment_id,
            actor,
            b"c" * 36,
            uuid.uuid4().bytes[:12],
            TEST_PROVENANCE,
            actor,
            TEST_PROVENANCE,
        ),
    )
    connection.execute(TURN_SIGN_IN_CODE_ON, (actor, TEST_PROVENANCE, enrollment_id))
    return enrollment_id


def live_session(owner_url: str, actor: uuid.UUID | str) -> tuple[uuid.UUID, str]:
    """A new live session of the actor and its session cookie value."""
    session_id = uuid.uuid4()
    session_token = secrets.token_urlsafe(32)
    with psycopg.connect(owner_url) as connection:
        connection.execute(
            ADD_SESSION,
            (session_id, actor, session_token_digest(session_token), TEST_PROVENANCE),
        )
        connection.commit()
    return session_id, session_token


def reauthentication_of(
    owner_url: str,
    actor: uuid.UUID | str,
    session_id: uuid.UUID,
    *,
    minutes_ago: int = 0,
) -> str:
    """A reauthentication of the session with the actor's sign-in code (a new step) and its
    reauthentication cookie value, written as the table owner (the flow's own reauthentication
    needs a real password and code). `minutes_ago` backdates the row, with the table's triggers
    off for that one insert."""
    reauthentication_token = secrets.token_urlsafe(32)
    with psycopg.connect(owner_url) as connection:
        enrollment_id = sign_in_code_of(connection, actor)
        step = connection.execute(NEXT_STEP, (enrollment_id,)).fetchone()
        assert step is not None
        connection.execute(USE_STEP, (enrollment_id, step[0]))
        row = (
            uuid.uuid4(),
            session_id,
            actor,
            enrollment_id,
            step[0],
            session_token_digest(reauthentication_token),
        )
        if minutes_ago:
            connection.execute(
                "ALTER TABLE app.browser_session_reauthentications DISABLE TRIGGER USER"
            )
            connection.execute(ADD_OLD_REAUTHENTICATION, (*row, minutes_ago))
            connection.execute(
                "ALTER TABLE app.browser_session_reauthentications ENABLE TRIGGER USER"
            )
        else:
            connection.execute(ADD_REAUTHENTICATION, row)
        connection.commit()
    return reauthentication_token


def reauthenticated(owner_url: str, actor: uuid.UUID | str) -> tuple[uuid.UUID, str, str]:
    """A new live session of the actor, reauthenticated with the sign-in code just now."""
    session_id, session_token = live_session(owner_url, actor)
    return session_id, session_token, reauthentication_of(owner_url, actor, session_id)


def cookie_context(
    actor: uuid.UUID | str,
    session_token: str | None,
    reauthentication_token: str | None,
    request_id: str | None = None,
) -> AdministrationAuditContext:
    return AdministrationAuditContext(
        actor_id=str(actor),
        request_id=request_id or str(uuid.uuid4()),
        session_token=session_token,
        reauthentication_token=reauthentication_token,
    )


def context(actor: uuid.UUID | str, request_id: str | None = None) -> AdministrationAuditContext:
    owner_url = ADMIN_ACTION_DATABASES.get(str(actor))
    if owner_url is None:
        return cookie_context(actor, None, None, request_id)
    _, session_token, reauthentication_token = reauthenticated(owner_url, actor)
    return cookie_context(actor, session_token, reauthentication_token, request_id)


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
    # Login sub-slice L4: the first one-time password is given in the same step (same time).
    assert sorted(audit_actions(database, "create-dara")) == [
        "identity.account.created",
        "identity.account.one_time_password_given",
    ]
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


def test_a_non_owner_or_unknown_actor_is_refused_including_the_owners_reset(
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
        # Login sub-slice L3d-2: the reauthentication check comes first, so an unknown actor with
        # no session is refused by it; the reauthenticated Manager by the capability, and an
        # actor id that is not a UUID before any database work.
        refused(
            "REAUTHENTICATION_REQUIRED"
            if isinstance(actor, uuid.UUID) and actor != database.manager
            else "FORBIDDEN",
            403,
            flow.create_user,
            property_id=database.property_id,
            username=f"denied-{uuid.uuid4().hex[:8]}",
            display_name="Denied",
            audit_name="Denied",
            account_class="staff",
            audit_context=context(actor),
        )
        # Login sub-slice L4: the Owner's reset works now, and only for the Owner, with the same
        # order of checks.
        refused(
            "REAUTHENTICATION_REQUIRED"
            if isinstance(actor, uuid.UUID) and actor != database.manager
            else "FORBIDDEN",
            403,
            flow.administratively_recover_user,
            user_id=database.manager,
            property_id=database.property_id,
            reset_mfa=False,
            reason="Not allowed",
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


ADD_PASSWORD_REAUTHENTICATION = (
    "INSERT INTO app.browser_session_reauthentications (reauthentication_id, session_id, "
    "actor_id, method, token_verifier) VALUES (%s, %s, %s, 'password', %s)"
)
SIGN_OUT = (
    "UPDATE app.browser_sessions SET revoked_by_actor_id = %s, revocation_reason = 'logout', "
    "revocation_provenance = %s WHERE session_id = %s"
)
TURN_SIGN_IN_CODE_OFF = (
    "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'disabled', "
    "disabled_by_actor_id = %s, disablement_provenance = %s "
    "WHERE actor_id = %s AND enrollment_state = 'active'"
)


def test_each_change_of_who_may_do_what_needs_a_recent_reauthentication(
    admin_database: AdminDatabase,
) -> None:
    """TEST-132, SEC-018, owner answer (a) to Q-2026-10-21-157, login sub-slice L3d-2: creating
    an account, disabling it or turning its MFA on or off, creating or changing a role bundle,
    giving or removing one, and giving or removing Settings access each need a reauthentication
    with the sign-in code of the request's own session in the last 15 minutes. Without the
    reauthentication cookie, or with a copied session cookie alone, each answers 403
    `REAUTHENTICATION_REQUIRED` and writes nothing, no audit event included. A change of the
    names alone and a sign-out of an account's sessions do not need one."""
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    staff = new_staff(database, flow, "Sophea")
    bundle = flow.create_role_bundle(
        property_id=database.property_id,
        name=f"Front desk {uuid.uuid4().hex[:6]}",
        capability_ids=("payments.read",),
        audit_context=context(database.owner),
    )
    flow.assign_role_bundle(
        user_id=staff.user_id,
        role_bundle_id=bundle.role_bundle_id,
        property_id=database.property_id,
        audit_context=context(database.owner),
    )
    _, copied_session = live_session(database.owner_url, database.owner)
    of_staff = {"user_id": staff.user_id, "property_id": database.property_id}
    account_change = {
        **of_staff,
        "expected_version": staff.version,
        "display_name": None,
        "audit_name": None,
        "revoke_applicable_sessions_if_disabled": True,
    }
    late_username = f"late-{uuid.uuid4().hex[:8]}"
    calls: list[tuple[Any, dict[str, Any]]] = [
        (
            flow.create_user,
            {
                "property_id": database.property_id,
                "username": late_username,
                "display_name": "Late",
                "audit_name": "Late",
                "account_class": "staff",
            },
        ),
        (
            flow.update_user,
            {**account_change, "lifecycle_state": "disabled", "mfa_policy_class": None},
        ),
        (
            flow.update_user,
            {**account_change, "lifecycle_state": None, "mfa_policy_class": "required"},
        ),
        (
            flow.create_role_bundle,
            {
                "property_id": database.property_id,
                "name": f"Late desk {uuid.uuid4().hex[:6]}",
                "capability_ids": ("payments.read",),
            },
        ),
        (
            flow.update_role_bundle,
            {
                "role_bundle_id": bundle.role_bundle_id,
                "property_id": database.property_id,
                "expected_version": bundle.version,
                "name": f"Renamed desk {uuid.uuid4().hex[:6]}",
                "capability_ids": None,
                "revoke_affected_sessions_on_capability_reduction": True,
            },
        ),
        (
            flow.assign_role_bundle,
            {"role_bundle_id": bundle.role_bundle_id, **of_staff},
        ),
        (
            flow.remove_role_assignment,
            {"role_bundle_id": bundle.role_bundle_id, **of_staff, "reason": "Moved"},
        ),
        (flow.give_settings_access, {**of_staff, "reason": "Keeps the riel rate"}),
        (flow.remove_settings_access, {**of_staff, "reason": "Back to daily work"}),
    ]
    request_id = str(uuid.uuid4())
    for call, arguments in calls:
        for session_token in (None, copied_session):
            with pytest.raises(AccessAdministrationRejected) as caught:
                call(
                    **arguments,
                    audit_context=cookie_context(database.owner, session_token, None, request_id),
                )
            assert (caught.value.status_code, caught.value.code, caught.value.message) == (
                403,
                "REAUTHENTICATION_REQUIRED",
                REAUTHENTICATION_REQUIRED_MESSAGE,
            )
    assert audit_actions(database, request_id) == []
    with psycopg.connect(database.owner_url) as connection:
        assert connection.execute(
            "SELECT lifecycle_state, mfa_policy_class, settings_access, version "
            "FROM app.admin_accounts(%s) WHERE actor_id = %s",
            (database.owner, staff.user_id),
        ).fetchone() == ("active", staff.mfa_policy_class, False, staff.version)
        assert connection.execute(
            "SELECT max(version) FROM app.role_bundles WHERE role_bundle_id = %s",
            (bundle.role_bundle_id,),
        ).fetchone() == (bundle.version,)
        assert connection.execute(
            "SELECT count(*) FROM app.admin_accounts(%s) WHERE username = %s",
            (database.owner, late_username),
        ).fetchone() == (0,)
    # Not on the list: the names alone, and signing an account out everywhere.
    renamed = flow.update_user(
        **{**account_change, "display_name": "Sophea Chan"},
        lifecycle_state=None,
        mfa_policy_class=None,
        audit_context=cookie_context(database.owner, None, None),
    )
    assert renamed.display_name == "Sophea Chan"
    flow.revoke_user_sessions(
        user_id=staff.user_id, audit_context=cookie_context(database.owner, None, None)
    )
    # With a recent reauthentication of the request's own session the same change goes through.
    disabled = flow.update_user(
        **{**account_change, "expected_version": renamed.version},
        lifecycle_state="disabled",
        mfa_policy_class=None,
        audit_context=context(database.owner),
    )
    assert disabled.lifecycle_state == "disabled"


def test_only_a_recent_sign_in_code_reauthentication_of_the_same_session_counts(
    admin_database: AdminDatabase,
) -> None:
    """TEST-132, login sub-slice L3d-2 (bindings of L3d-1 review rounds 1 to 3): only the latest
    `totp` reauthentication of the request's own live session counts, found through its
    reauthentication cookie, made in the last 15 minutes on the database clock, while its
    sign-in code is still the account's active one. Refused: the cookie of another session of
    the same Owner, a Manager's cookies sent for the Owner, an older cookie of the session after
    a newer reauthentication, a row 16 minutes old, a signed-out session, a sign-in code turned
    off since, cookies of no or too long a value, and a password-only reauthentication (it never
    counts, even for an account whose MFA is `optional`). The capability is still checked."""
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)

    def create(audit_context: AdministrationAuditContext) -> Any:
        return flow.create_user(
            property_id=database.property_id,
            username=f"check-{uuid.uuid4().hex[:8]}",
            display_name="Check",
            audit_name="Check",
            account_class="staff",
            audit_context=audit_context,
        )

    def refused_create(
        audit_context: AdministrationAuditContext, code: str = "REAUTHENTICATION_REQUIRED"
    ) -> None:
        refused(code, 403, create, audit_context)

    owner = database.owner
    first_id, first_session = live_session(database.owner_url, owner)
    second_id, second_session = live_session(database.owner_url, owner)
    first_cookie = reauthentication_of(database.owner_url, owner, first_id)
    second_cookie = reauthentication_of(database.owner_url, owner, second_id)
    refused_create(cookie_context(owner, first_session, second_cookie))
    refused_create(cookie_context(owner, second_session, first_cookie))
    for session_token, cookie in (
        ("", first_cookie),
        (first_session, ""),
        ("x" * 129, first_cookie),
        (first_session, "x" * 129),
    ):
        refused_create(cookie_context(owner, session_token, cookie))
    manager_id, manager_session = live_session(database.owner_url, database.manager)
    manager_cookie = reauthentication_of(database.owner_url, database.manager, manager_id)
    refused_create(cookie_context(owner, manager_session, manager_cookie))
    refused_create(cookie_context(database.manager, manager_session, manager_cookie), "FORBIDDEN")
    assert create(cookie_context(owner, first_session, first_cookie)).account_class == "staff"
    # A newer reauthentication of the session replaces the older cookie.
    newer_cookie = reauthentication_of(database.owner_url, owner, first_id)
    refused_create(cookie_context(owner, first_session, first_cookie))
    assert create(cookie_context(owner, first_session, newer_cookie)).account_class == "staff"
    # 15 minutes on the database clock.
    stale_id, stale_session = live_session(database.owner_url, owner)
    stale_cookie = reauthentication_of(database.owner_url, owner, stale_id, minutes_ago=16)
    refused_create(cookie_context(owner, stale_session, stale_cookie))
    recent_id, recent_session = live_session(database.owner_url, owner)
    recent_cookie = reauthentication_of(database.owner_url, owner, recent_id, minutes_ago=14)
    assert create(cookie_context(owner, recent_session, recent_cookie)).account_class == "staff"
    # A signed-out session, then a sign-in code turned off since the reauthentication.
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(SIGN_OUT, (owner, TEST_PROVENANCE, first_id))
        connection.commit()
    refused_create(cookie_context(owner, first_session, newer_cookie))
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(TURN_SIGN_IN_CODE_OFF, (owner, TEST_PROVENANCE, owner))
        connection.commit()
    refused_create(cookie_context(owner, second_session, second_cookie))
    refused_create(cookie_context(owner, recent_session, recent_cookie))
    # A password-only reauthentication of a Staff account with MFA `optional` and no sign-in
    # code never counts: the check refuses before the capability does.
    with psycopg.connect(database.owner_url) as setup:
        staff = add_account(setup, "staff")
        setup.commit()
    staff_id, staff_session = live_session(database.owner_url, staff)
    staff_cookie = secrets.token_urlsafe(32)
    with psycopg.connect(database.owner_url) as connection:
        connection.execute(
            ADD_PASSWORD_REAUTHENTICATION,
            (uuid.uuid4(), staff_id, staff, session_token_digest(staff_cookie)),
        )
        connection.commit()
    refused_create(cookie_context(staff, staff_session, staff_cookie))


ADD_AGED_SESSION = """
    INSERT INTO app.browser_sessions (
        session_id, actor_id, token_verifier, verifier_algorithm, created_at, last_activity_at,
        idle_expires_at, absolute_expires_at, creation_provenance
    )
    SELECT %s, %s, %s, 'sha256', moment.created, moment.active,
           LEAST(moment.active + interval '30 minutes', moment.created + interval '24 hours'),
           moment.created + interval '24 hours', %s
    FROM (
        SELECT statement_timestamp() - %s::interval AS created,
               statement_timestamp() - %s::interval AS active
    ) AS moment
"""


def test_the_check_holds_the_session_and_comes_before_the_other_refusals(
    admin_database: AdminDatabase,
) -> None:
    """Login sub-slice L3d-2 review round 1: a session past its 30 idle minutes or its 24 hours
    is refused like a signed-out one (a table check makes the idle expiry never later than the
    absolute one, so the second case is past both); the check holds the session `FOR SHARE`,
    so a sign-out from another connection waits until the action ends, while the action's own
    transaction may still end that session; and a stale reauthentication is refused before a
    stale version."""
    database = admin_database
    flow = PostgresAccessAdministrationFlow(database.runtime_url)
    owner = database.owner

    def create(audit_context: AdministrationAuditContext) -> Any:
        return flow.create_user(
            property_id=database.property_id,
            username=f"held-{uuid.uuid4().hex[:8]}",
            display_name="Held",
            audit_name="Held",
            account_class="staff",
            audit_context=audit_context,
        )

    for created_ago, active_ago in (
        ("40 minutes", "31 minutes"),
        ("24 hours 2 minutes", "3 minutes"),
    ):
        session_id = uuid.uuid4()
        session_token = secrets.token_urlsafe(32)
        with psycopg.connect(database.owner_url) as connection:
            connection.execute(
                ADD_AGED_SESSION,
                (
                    session_id,
                    owner,
                    session_token_digest(session_token),
                    TEST_PROVENANCE,
                    created_ago,
                    active_ago,
                ),
            )
            connection.commit()
        cookie = reauthentication_of(database.owner_url, owner, session_id, minutes_ago=1)
        refused(
            "REAUTHENTICATION_REQUIRED", 403, create, cookie_context(owner, session_token, cookie)
        )
    # FOR SHARE: a sign-out from another connection waits for the check's transaction.
    session_id, session_token, cookie = reauthenticated(database.owner_url, owner)
    check = (session_token_digest(session_token), owner, session_token_digest(cookie))
    with psycopg.connect(database.runtime_url) as holding:
        assert holding.execute(RECENT_REAUTHENTICATION, check).fetchone() == (1,)
        with psycopg.connect(database.owner_url) as other:
            other.execute("SET lock_timeout = '300ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                other.execute(SIGN_OUT, (owner, TEST_PROVENANCE, session_id))
        holding.commit()
    # In one transaction the held session may still be ended (the Owner's own session).
    with psycopg.connect(database.owner_url) as connection:
        assert connection.execute(RECENT_REAUTHENTICATION, check).fetchone() == (1,)
        connection.execute(SIGN_OUT, (owner, TEST_PROVENANCE, session_id))
        connection.commit()
    refused("REAUTHENTICATION_REQUIRED", 403, create, cookie_context(owner, session_token, cookie))
    # A stale reauthentication is refused before a stale version.
    bundle = flow.create_role_bundle(
        property_id=database.property_id,
        name=f"Order desk {uuid.uuid4().hex[:6]}",
        capability_ids=("payments.read",),
        audit_context=context(owner),
    )
    stale_id, stale_session = live_session(database.owner_url, owner)
    stale_cookie = reauthentication_of(database.owner_url, owner, stale_id, minutes_ago=16)
    change = {
        "role_bundle_id": bundle.role_bundle_id,
        "property_id": database.property_id,
        "expected_version": bundle.version + 5,
        "name": None,
        "capability_ids": ("payments.read", "payments.record"),
        "revoke_affected_sessions_on_capability_reduction": True,
    }
    refused(
        "REAUTHENTICATION_REQUIRED",
        403,
        flow.update_role_bundle,
        **change,
        audit_context=cookie_context(owner, stale_session, stale_cookie),
    )
    refused("STALE_VERSION", 412, flow.update_role_bundle, **change, audit_context=context(owner))


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
    payload = {
        "username": f"http-{uuid.uuid4().hex[:8]}",
        "display_name": "Http Staff",
        "audit_name": "Http Staff",
        "account_class": "staff",
    }
    # Login sub-slice L3d-2: the route reads both browser cookies; the session cookie alone (a
    # copied cookie in a second client) is refused with the stable code and message.
    _, session_token, reauthentication_token = reauthenticated(database.owner_url, database.owner)
    users_path = f"/api/v1/properties/{database.property_id}/users"
    copied = request(
        app, "POST", users_path, payload=payload, cookies={SESSION_COOKIE_NAME: session_token}
    )
    assert copied.status_code == 403
    assert copied.json()["error"] == {
        "code": "REAUTHENTICATION_REQUIRED",
        "message": REAUTHENTICATION_REQUIRED_MESSAGE,
        "fields": [],
        "rule_ids": [],
        "current_version": None,
    }
    cookies = {
        SESSION_COOKIE_NAME: session_token,
        REAUTHENTICATION_COOKIE_NAME: reauthentication_token,
    }
    created = request(app, "POST", users_path, payload=payload, cookies=cookies)
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
        cookies=cookies,
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
