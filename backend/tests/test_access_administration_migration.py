"""Account and role bundle administration in the database (login slice sub-slice L2a).

API-079, API-080, DL-057, DL-074 answers 1 and 2, DL-081 (Q-2026-10-21-152 (a), Q-156 (a),
Q-165 (a)), SEC-014, SEC-017, SEC-021, SEC-075, DB-AUTH-010: only the active Owner account class
administers accounts, role bundles, assignments and Settings access, at READ COMMITTED, with one
immutable audit event per action; disabling, a bundle that loses a capability, a removed
assignment and a Staff account whose MFA policy is raised revoke the applicable sessions; a Staff
account whose MFA is turned off loses its sign-in code, its sessions and its Settings access in
the same step. Rows written to the shared database are rolled back, except the committed Manager
and Staff accounts of the runtime-role test; no Owner is ever committed there (the race tests
and the "no default bundles" test use throwaway databases).
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import BUNDLE_CAPABILITIES, STAFF_DEFAULT_BUNDLE_CAPABILITIES
from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, grants, refused, the_property
from test_settings_access_migration import NO_SIGN_IN_CODE, add_sign_in_code, one, settings_rows

REVISION = "20270124_181"
PREVIOUS = "20270123_180"
CREATE_ACCOUNT = "SELECT app.admin_create_account(%s,%s,%s,%s,%s,%s)"
UPDATE_ACCOUNT = "SELECT app.admin_update_account(%s,%s,%s,%s,%s,%s,%s,%s)"
REVOKE_SESSIONS = "SELECT app.admin_revoke_account_sessions(%s,%s,%s)"
CREATE_BUNDLE = "SELECT app.admin_create_role_bundle(%s,%s,%s,%s,%s)"
UPDATE_BUNDLE = "SELECT app.admin_update_role_bundle(%s,%s,%s,%s,%s,%s)"
ASSIGN = "SELECT app.admin_assign_role_bundle(%s,%s,%s,%s)"
REMOVE_ASSIGNMENT = "SELECT app.admin_remove_role_assignment(%s,%s,%s,%s,%s)"
GIVE_SETTINGS = "SELECT app.admin_give_settings_access(%s,%s,%s,%s)"
REMOVE_SETTINGS = "SELECT app.admin_remove_settings_access(%s,%s,%s,%s)"
ACCOUNTS = (
    "SELECT actor_id,username,display_name,audit_name,lifecycle_state,mfa_policy_class,"
    "account_class,settings_access,version FROM app.admin_accounts(%s)"
)
BUNDLES = (
    "SELECT role_bundle_id,property_id,name,version,capability_ids FROM app.admin_role_bundles(%s)"
)
DEFINERS = (
    "app.admin_create_account(uuid,text,text,text,text,uuid)",
    "app.admin_update_account(uuid,uuid,integer,text,text,boolean,text,uuid)",
    "app.admin_revoke_account_sessions(uuid,uuid,uuid)",
    "app.admin_create_role_bundle(uuid,uuid,text,text[],uuid)",
    "app.admin_update_role_bundle(uuid,uuid,integer,text,text[],uuid)",
    "app.admin_assign_role_bundle(uuid,uuid,uuid,uuid)",
    "app.admin_remove_role_assignment(uuid,uuid,uuid,text,uuid)",
    "app.admin_give_settings_access(uuid,uuid,text,uuid)",
    "app.admin_remove_settings_access(uuid,uuid,text,uuid)",
    "app.admin_accounts(uuid)",
    "app.admin_role_bundles(uuid)",
)
INTERNAL = (
    "app.reject_account_change_history_change()",
    "app.assert_access_administrator(uuid)",
    "app.administered_property()",
    "app.user_account_version(uuid)",
    "app.revoke_live_sessions(uuid,uuid,text,text)",
    "app.bundle_capability_set(text[])",
    "app.assert_account_names(text[])",
    "app.record_access_administration(uuid,text,text,uuid,text,jsonb,jsonb,uuid)",
)
ONLY_OWNER = "only the Owner administers accounts and role bundles"
READ_COMMITTED = "account administration runs only at READ COMMITTED"
APPEND_ONLY = "account change history is append-only"
ONLY_BUNDLE = "only bundle capabilities can be in a role bundle"
BAD_NAME = "an account name is 1 to 128 visible characters with no space at either end"
ADD_SESSION = (
    "INSERT INTO app.browser_sessions(session_id,actor_id,token_verifier,verifier_algorithm,"
    "creation_provenance) VALUES (%s,%s,%s,'sha256','login-slice-l2a-test')"
)
ADD_EXPIRED_SESSION = (
    "INSERT INTO app.browser_sessions(session_id,actor_id,token_verifier,verifier_algorithm,"
    "created_at,last_activity_at,idle_expires_at,absolute_expires_at,creation_provenance) "
    "VALUES (%s,%s,%s,'sha256',%s,%s,%s,%s,'login-slice-l2a-test')"
)
NOT_REVOKED = (False, None, None, None)


def add_session(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> uuid.UUID:
    session_id = uuid.uuid4()
    connection.execute(ADD_SESSION, (session_id, actor_id, uuid.uuid4().bytes * 2))
    return session_id


def add_expired_session(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> uuid.UUID:
    """A session that reached its 24-hour limit a day ago (the database clock)."""
    session_id = uuid.uuid4()
    now = one(connection, "SELECT statement_timestamp()", ())
    created = now - timedelta(hours=48)
    connection.execute(
        ADD_EXPIRED_SESSION,
        (
            session_id,
            actor_id,
            uuid.uuid4().bytes * 2,
            created,
            created,
            created + timedelta(minutes=30),
            created + timedelta(hours=24),
        ),
    )
    return session_id


def session_states(
    connection: psycopg.Connection[Any], actor_id: uuid.UUID
) -> dict[uuid.UUID, tuple[Any, ...]]:
    return {
        row[0]: tuple(row[1:])
        for row in connection.execute(
            "SELECT session_id,revoked_at IS NOT NULL,revoked_by_actor_id,revocation_reason,"
            "revocation_provenance FROM app.browser_sessions WHERE actor_id=%s",
            (actor_id,),
        ).fetchall()
    }


def audit_count(connection: psycopg.Connection[Any]) -> int:
    return int(one(connection, "SELECT count(*) FROM app.audit_events", ()))


def audit_event(connection: psycopg.Connection[Any], correlation_id: uuid.UUID) -> dict[str, Any]:
    """The one audit event an administration call wrote."""
    rows = connection.execute(
        "SELECT actor_id,action,entity_type,entity_id,reason,authorization_reference,"
        "property_id,previous_state,resulting_state,source,outcome "
        "FROM app.audit_events WHERE correlation_id=%s",
        (correlation_id,),
    ).fetchall()
    assert len(rows) == 1
    keys = (
        "actor_id",
        "action",
        "entity_type",
        "entity_id",
        "reason",
        "authorization_reference",
        "property_id",
        "previous_state",
        "resulting_state",
        "source",
        "outcome",
    )
    event = dict(zip(keys, rows[0], strict=True))
    assert event["authorization_reference"] == "identity.manage_access"
    assert (event["source"], event["outcome"]) == ("API", "SUCCEEDED")
    text = f"{event['previous_state']} {event['resulting_state']}".lower()
    for word in ("password", "verifier", "secret", "token", "code"):
        assert word not in text
    return event


def seeded(
    connection: psycopg.Connection[Any], property_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    row = connection.execute(SEED_QUERY, (property_id,)).fetchone()
    assert row is not None
    return row[0], row[1], row[2]


def account_row(connection: psycopg.Connection[Any], owner: uuid.UUID, actor: uuid.UUID) -> Any:
    for row in connection.execute(ACCOUNTS, (owner,)).fetchall():
        if row[0] == actor:
            return row
    raise AssertionError(actor)


def enrollment_states(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT enrollment_state FROM app.totp_mfa_enrollments WHERE actor_id=%s "
            "ORDER BY created_at",
            (actor_id,),
        ).fetchall()
    ]


def bundle_set(connection: psycopg.Connection[Any], bundle_id: uuid.UUID, version: int) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT capability_id FROM app.role_bundle_capabilities "
            "WHERE role_bundle_id=%s AND version=%s",
            (bundle_id, version),
        ).fetchall()
    }


def test_only_the_active_owner_administers_at_read_committed(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        connection.rollback()

        def calls(target: uuid.UUID, bundle: uuid.UUID) -> tuple[tuple[str, tuple[Any, ...]], ...]:
            return (
                (CREATE_ACCOUNT, ("night-desk", "Night Desk", "night-desk", "staff", uuid.uuid4())),
                (UPDATE_ACCOUNT, (target, 1, "Night Desk", None, None, None, uuid.uuid4())),
                (REVOKE_SESSIONS, (target, uuid.uuid4())),
                (CREATE_BUNDLE, (property_id, "Late desk", ["units.read"], uuid.uuid4())),
                (UPDATE_BUNDLE, (bundle, 1, "Night shift", None, uuid.uuid4())),
                (ASSIGN, (target, bundle, uuid.uuid4())),
                (REMOVE_ASSIGNMENT, (target, bundle, "Moved to day shift", uuid.uuid4())),
                (GIVE_SETTINGS, (target, "Keeps the riel rate", uuid.uuid4())),
                (REMOVE_SETTINGS, (target, "Back to daily work", uuid.uuid4())),
                (ACCOUNTS, ()),
                (BUNDLES, ()),
            )

        owner = add_account(connection, "owner")
        target = add_account(connection, "staff")
        bundle = one(
            connection,
            CREATE_BUNDLE,
            (owner, property_id, "Night desk", ["units.read"], uuid.uuid4()),
        )
        acting = (
            add_account(connection, "manager"),
            add_account(connection, "staff"),
            add_account(connection, "manager", "disabled"),
            add_account(connection, None),
            uuid.uuid4(),
        )
        for actor in acting:
            for query, parameters in calls(target, bundle):
                refused(
                    connection,
                    psycopg.errors.InsufficientPrivilege,
                    query,
                    (actor, *parameters),
                    ONLY_OWNER,
                )
        # A disabled Owner administers nothing either (in a savepoint: one Owner at most).
        with connection.transaction(force_rollback=True):
            connection.execute(
                "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s",
                (owner,),
            )
            for query, parameters in calls(target, bundle):
                refused(
                    connection,
                    psycopg.errors.InsufficientPrivilege,
                    query,
                    (owner, *parameters),
                    ONLY_OWNER,
                )
        # A write without a correlation id writes nothing (its audit event needs one).
        before = audit_count(connection)
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            REVOKE_SESSIONS,
            (owner, target, None),
            "an administration action needs a correlation id",
        )
        assert audit_count(connection) == before
        connection.rollback()
        # As in sub-slices L1a to L1d: an older snapshot could miss a committed change.
        for level in ("repeatable read", "serializable"):
            with connection.transaction():
                connection.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
                owner = add_account(connection, "owner")
                target = add_account(connection, "staff")
                for query, parameters in calls(target, uuid.uuid4()):
                    refused(
                        connection,
                        psycopg.errors.ObjectNotInPrerequisiteState,
                        query,
                        (owner, *parameters),
                        READ_COMMITTED,
                    )
                raise psycopg.Rollback


def test_the_owner_creates_manager_and_staff_accounts(migrated_database_url: str) -> None:
    """Q-2026-10-21-152 (a): the class sets the MFA policy and the default bundle; no second
    Owner; the account has no password until sub-slice L4."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        _, manager_bundle, staff_bundle = seeded(connection, property_id)
        made: dict[str, uuid.UUID] = {}
        for account_class, username, bundle in (
            ("manager", "  Dara.Manager ", manager_bundle),
            ("staff", "Sokha", staff_bundle),
        ):
            correlation = uuid.uuid4()
            before = audit_count(connection)
            actor = one(
                connection,
                CREATE_ACCOUNT,
                (owner, username, f"{username.strip()} Name", "audit", account_class, correlation),
            )
            assert audit_count(connection) == before + 1
            made[account_class] = actor
            mfa = "required" if account_class == "manager" else "optional"
            assert account_row(connection, owner, actor)[1:] == (
                username.strip().lower(),
                f"{username.strip()} Name",
                "audit",
                "active",
                mfa,
                account_class,
                False,
                1,
            )
            assert connection.execute(
                "SELECT role_bundle_id,property_id,assigned_by_actor_id,provenance "
                "FROM app.user_role_assignments WHERE actor_id=%s",
                (actor,),
            ).fetchall() == [(bundle, property_id, owner, "owner-account-create")]
            assert (
                one(
                    connection,
                    "SELECT identity_kind FROM app.actor_identities WHERE actor_id=%s",
                    (actor,),
                )
                == "HUMAN"
            )
            assert (
                one(
                    connection,
                    "SELECT count(*) FROM app.password_credentials WHERE actor_id=%s",
                    (actor,),
                )
                == 0
            )
            event = audit_event(connection, correlation)
            assert (event["actor_id"], event["action"], event["entity_type"]) == (
                owner,
                "identity.account.created",
                "user_account",
            )
            assert (event["entity_id"], event["property_id"]) == (actor, property_id)
            assert event["previous_state"] is None
            assert event["resulting_state"]["account_class"] == account_class
            assert event["resulting_state"]["default_role_bundle_id"] == str(bundle)
        assert {capability for capability, _ in grants(connection, made["staff"])} == set(
            STAFF_DEFAULT_BUNDLE_CAPABILITIES
        )
        assert {capability for capability, _ in grants(connection, made["manager"])} == set(
            BUNDLE_CAPABILITIES
        )
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            CREATE_ACCOUNT,
            (owner, "second-owner", "Second", "second", "owner", uuid.uuid4()),
            "the Owner creates Manager or Staff accounts only",
        )
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            CREATE_ACCOUNT,
            (owner, "SOKHA", "Sokha Again", "sokha", "staff", uuid.uuid4()),
        )
        connection.rollback()


def test_account_names_have_only_visible_characters(migrated_database_url: str) -> None:
    """Review round 1: the bundle name rule of sub-slice L1b-2 for the username, the display
    name and the audit name, so no two accounts or audit names look alike."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        seeded(connection, property_id)
        staff = add_account(connection, "staff")
        for username, display, audit in (
            ("dara\u200b", "Dara", "dara"),
            ("", "Dara", "dara"),
            ("dara", "Dara\u202e", "dara"),
            ("dara", " Dara", "dara"),
            ("dara", "Dara", "d" * 129),
            ("dara", "Dara", "dara\u0085"),
        ):
            refused(
                connection,
                psycopg.errors.InvalidParameterValue,
                CREATE_ACCOUNT,
                (owner, username, display, audit, "staff", uuid.uuid4()),
                BAD_NAME,
            )
            if (display, audit) != ("Dara", "dara"):
                refused(
                    connection,
                    psycopg.errors.InvalidParameterValue,
                    UPDATE_ACCOUNT,
                    (owner, staff, 1, display, audit, None, None, uuid.uuid4()),
                    BAD_NAME,
                )
        # Khmer and English names are kept as typed.
        one(
            connection,
            CREATE_ACCOUNT,
            (owner, "sokha.k", "សុខា Sokha", "សុខា", "staff", uuid.uuid4()),
        )
        connection.rollback()


def test_the_owner_needs_the_default_bundles_to_create_an_account(
    migrated_database_url: str,
) -> None:
    """A throwaway database: its Property has no default bundles (the migration seeds only a
    Property that existed before it)."""
    assert migrated_database_url
    with _temporary_migration_database("prm_access_admin_defaults") as temporary:
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(temporary) as connection:
            the_property(connection)
            owner = add_account(connection, "owner")
            refused(
                connection,
                psycopg.errors.ObjectNotInPrerequisiteState,
                CREATE_ACCOUNT,
                (owner, "dara", "Dara", "dara", "manager", uuid.uuid4()),
                "the Property has no default role bundles",
            )
            connection.rollback()


def test_an_account_change_needs_its_version_and_keeps_its_history(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        correlation = uuid.uuid4()
        update = (owner, staff, 1, "Vanna", None, None, None, correlation)
        assert one(connection, UPDATE_ACCOUNT, update) == 2
        event = audit_event(connection, correlation)
        assert event["action"] == "identity.account.updated"
        assert event["previous_state"]["version"] == 1
        assert event["resulting_state"]["display_name"] == "Vanna"
        assert event["resulting_state"]["version"] == 2
        refused(
            connection,
            psycopg.errors.SerializationFailure,
            UPDATE_ACCOUNT,
            (owner, staff, 1, None, "vanna", None, None, uuid.uuid4()),
            "the account changed since it was read",
        )
        one(connection, UPDATE_ACCOUNT, (owner, staff, 2, None, "vanna", None, None, uuid.uuid4()))
        changed = account_row(connection, owner, staff)
        assert (changed[2], changed[3], changed[8]) == ("Vanna", "vanna", 3)
        assert connection.execute(
            "SELECT version,changed_by_actor_id,provenance FROM app.user_account_changes "
            "WHERE actor_id=%s ORDER BY version",
            (staff,),
        ).fetchall() == [(2, owner, "owner-account-update"), (3, owner, "owner-account-update")]
        for query in (
            "UPDATE app.user_account_changes SET provenance='changed' WHERE actor_id=%s",
            "DELETE FROM app.user_account_changes WHERE actor_id=%s",
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                (staff,),
                APPEND_ONLY,
            )
        refused(
            connection,
            psycopg.errors.IntegrityConstraintViolation,
            "TRUNCATE app.user_account_changes",
            (),
            APPEND_ONLY,
        )
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            UPDATE_ACCOUNT,
            (owner, staff, 3, None, None, None, None, uuid.uuid4()),
            "at least one account change is required",
        )
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            UPDATE_ACCOUNT,
            (owner, staff, 3, None, None, None, "sometimes", uuid.uuid4()),
            "an MFA policy is required or optional",
        )
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            UPDATE_ACCOUNT,
            (owner, owner, 1, "Proprietor", None, None, None, uuid.uuid4()),
            "the Owner account is not changed by account administration",
        )
        refused(
            connection,
            psycopg.errors.NoDataFound,
            UPDATE_ACCOUNT,
            (owner, uuid.uuid4(), 1, "Nobody", None, None, None, uuid.uuid4()),
            "the account does not exist",
        )
        # Q-2026-10-21-152 (a): an old account without a class is only disabled.
        old = add_account(connection, None)
        assert account_row(connection, owner, old)[6:8] == (None, False)
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            UPDATE_ACCOUNT,
            (owner, old, 1, "Old", None, True, None, uuid.uuid4()),
            "an account without a class can only be disabled",
        )
        one(connection, UPDATE_ACCOUNT, (owner, old, 1, None, None, True, None, uuid.uuid4()))
        assert account_row(connection, owner, old)[4:7] == ("disabled", "optional", None)
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            UPDATE_ACCOUNT,
            (owner, old, 2, None, None, True, None, uuid.uuid4()),
            "a disabled account is not changed",
        )
        connection.rollback()


def test_disabling_an_account_revokes_its_sessions_and_keeps_its_history(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        _, _, staff_bundle = seeded(connection, property_id)
        staff = one(
            connection,
            CREATE_ACCOUNT,
            (owner, "sophea", "Sophea", "sophea", "staff", uuid.uuid4()),
        )
        add_sign_in_code(connection, staff)
        one(connection, GIVE_SETTINGS, (owner, staff, "Keeps the riel rate", uuid.uuid4()))
        live = {add_session(connection, staff), add_session(connection, staff)}
        expired = add_expired_session(connection, staff)
        other = add_account(connection, "staff")
        untouched = add_session(connection, other)
        version = account_row(connection, owner, staff)[8]
        correlation = uuid.uuid4()
        one(
            connection, UPDATE_ACCOUNT, (owner, staff, version, None, None, True, None, correlation)
        )
        states = session_states(connection, staff)
        for session in live:
            assert states[session] == (
                True,
                owner,
                "account_disabled",
                "access-admin-account-disabled",
            )
        assert states[expired] == NOT_REVOKED
        assert session_states(connection, other)[untouched] == NOT_REVOKED
        event = audit_event(connection, correlation)
        assert event["action"] == "identity.account.disabled"
        assert event["resulting_state"]["sessions_revoked"] == 2
        # The assignment and the Settings access stay as history; the reader gives nothing.
        assert (
            one(
                connection,
                "SELECT count(*) FROM app.user_role_assignments WHERE actor_id=%s "
                "AND role_bundle_id=%s",
                (staff, staff_bundle),
            )
            == 1
        )
        assert account_row(connection, owner, staff)[4] == "disabled"
        assert account_row(connection, owner, staff)[7] is True
        assert grants(connection, staff) == set()
        connection.rollback()


def test_staff_mfa_raised_revokes_sessions_and_mfa_off_resets_the_sign_in_code(
    migrated_database_url: str,
) -> None:
    """Sub-slice L1e (sessions end when MFA becomes required), Q-2026-10-21-156 (a) (MFA off is a
    reset of the sign-in code) and Q-165 (a) (MFA off removes Settings access in the same step,
    as a recorded removal; the Owner gives it again only after a new code)."""
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        session = add_session(connection, staff)
        raise_mfa = (owner, staff, 1, None, None, None, "required", uuid.uuid4())
        one(connection, UPDATE_ACCOUNT, raise_mfa)
        assert session_states(connection, staff)[session] == (
            True,
            owner,
            "material_privilege_reduction",
            "access-admin-mfa-required",
        )
        add_sign_in_code(connection, staff)
        given = one(connection, GIVE_SETTINGS, (owner, staff, "Keeps the riel rate", uuid.uuid4()))
        assert grants(connection, staff) == settings_rows(connection)
        later = add_session(connection, staff)
        correlation = uuid.uuid4()
        one(
            connection, UPDATE_ACCOUNT, (owner, staff, 2, None, None, None, "optional", correlation)
        )
        assert connection.execute(
            "SELECT removed_by_actor_id,reason FROM app.user_capability_grant_removals "
            "WHERE grant_id=%s",
            (given,),
        ).fetchall() == [(owner, "sign-in code turned off")]
        assert enrollment_states(connection, staff) == ["disabled"]
        assert account_row(connection, owner, staff)[5:8] == ("optional", "staff", False)
        assert session_states(connection, staff)[later] == (
            True,
            owner,
            "mfa_reset",
            "access-admin-mfa-off",
        )
        resulting = audit_event(connection, correlation)["resulting_state"]
        assert resulting["mfa_disabled"] is True
        assert resulting["settings_access_removed"] is True
        assert resulting["settings_access_removed_grant_id"] == str(given)
        assert resulting["sessions_revoked"] == 1
        connection.rollback()

    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        add_sign_in_code(connection, staff)
        one(
            connection,
            UPDATE_ACCOUNT,
            (owner, staff, 1, None, None, None, "optional", uuid.uuid4()),
        )
        one(
            connection,
            UPDATE_ACCOUNT,
            (owner, staff, 2, None, None, None, "required", uuid.uuid4()),
        )
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            GIVE_SETTINGS,
            (owner, staff, "Keeps the riel rate", uuid.uuid4()),
            NO_SIGN_IN_CODE,
        )
        add_sign_in_code(connection, staff)
        assert enrollment_states(connection, staff) == ["disabled", "active"]
        one(connection, GIVE_SETTINGS, (owner, staff, "New phone", uuid.uuid4()))
        # Required again, the old sign-in code did not count; MFA off removes the new grant.
        correlation = uuid.uuid4()
        one(
            connection, UPDATE_ACCOUNT, (owner, staff, 3, None, None, None, "optional", correlation)
        )
        resulting = audit_event(connection, correlation)["resulting_state"]
        assert (resulting["mfa_disabled"], resulting["settings_access_removed"]) == (True, True)
        plain = add_account(connection, "staff")
        add_sign_in_code(connection, plain)
        correlation = uuid.uuid4()
        one(
            connection, UPDATE_ACCOUNT, (owner, plain, 1, None, None, None, "optional", correlation)
        )
        resulting = audit_event(connection, correlation)["resulting_state"]
        assert (resulting["mfa_disabled"], resulting["settings_access_removed"]) == (True, False)
        assert resulting["settings_access_removed_grant_id"] is None
        assert (
            one(
                connection,
                "SELECT count(*) FROM app.user_capability_grants WHERE actor_id=%s",
                (plain,),
            )
            == 0
        )
        # A Manager's MFA cannot be lowered (sub-slice L1a).
        manager = add_account(connection, "manager")
        refused(
            connection,
            psycopg.errors.CheckViolation,
            UPDATE_ACCOUNT,
            (owner, manager, 1, None, None, None, "optional", uuid.uuid4()),
            "an Owner or Manager account requires MFA",
        )
        connection.rollback()


def test_disabling_with_mfa_off_does_both_in_one_change(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        add_sign_in_code(connection, staff)
        given = one(connection, GIVE_SETTINGS, (owner, staff, "Keeps the riel rate", uuid.uuid4()))
        session = add_session(connection, staff)
        before = audit_count(connection)
        correlation = uuid.uuid4()
        one(
            connection, UPDATE_ACCOUNT, (owner, staff, 1, None, None, True, "optional", correlation)
        )
        assert audit_count(connection) == before + 1
        assert session_states(connection, staff)[session][2] == "account_disabled"
        assert enrollment_states(connection, staff) == ["disabled"]
        event = audit_event(connection, correlation)
        assert event["action"] == "identity.account.disabled"
        assert event["resulting_state"]["settings_access_removed_grant_id"] == str(given)
        assert event["resulting_state"]["sessions_revoked"] == 1
        assert (
            one(
                connection,
                "SELECT count(*) FROM app.user_account_changes WHERE actor_id=%s",
                (staff,),
            )
            == 1
        )
        connection.rollback()


def test_role_bundles_are_created_and_changed_with_kept_versions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        holder = add_account(connection, "staff")
        correlation = uuid.uuid4()
        given = ["units.read", "leases.read", "units.read"]
        bundle = one(
            connection, CREATE_BUNDLE, (owner, property_id, "Front desk", given, correlation)
        )
        assert bundle_set(connection, bundle, 1) == {"units.read", "leases.read"}
        event = audit_event(connection, correlation)
        assert (event["action"], event["entity_id"]) == ("identity.role_bundle.created", bundle)
        assert event["resulting_state"]["capability_ids"] == ["leases.read", "units.read"]
        for capabilities in (
            ["settings.manage"],
            ["identity.manage_access"],
            ["rent_nonpayment.evaluate"],
            ["reports.export"],
            ["units.read", None],
        ):
            refused(
                connection,
                psycopg.errors.InvalidParameterValue,
                CREATE_BUNDLE,
                (owner, property_id, "Refused desk", capabilities, uuid.uuid4()),
                ONLY_BUNDLE,
            )
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            CREATE_BUNDLE,
            (owner, property_id, "FRONT DESK", ["units.read"], uuid.uuid4()),
        )
        refused(
            connection,
            psycopg.errors.NoDataFound,
            CREATE_BUNDLE,
            (owner, uuid.uuid4(), "Elsewhere", ["units.read"], uuid.uuid4()),
            "the Property does not exist",
        )
        one(connection, ASSIGN, (owner, holder, bundle, uuid.uuid4()))
        session = add_session(connection, holder)
        # A rename alone, or more capabilities, revokes nothing.
        assert one(connection, UPDATE_BUNDLE, (owner, bundle, 1, "Desk", None, uuid.uuid4())) == 2
        assert bundle_set(connection, bundle, 2) == {"units.read", "leases.read"}
        grown = ["units.read", "leases.read", "invoices.read"]
        assert one(connection, UPDATE_BUNDLE, (owner, bundle, 2, None, grown, uuid.uuid4())) == 3
        assert session_states(connection, holder)[session] == NOT_REVOKED
        # A capability taken away revokes the holders' sessions (DL-057, SEC-017).
        correlation = uuid.uuid4()
        smaller = (owner, bundle, 3, None, ["units.read"], correlation)
        assert one(connection, UPDATE_BUNDLE, smaller) == 4
        assert session_states(connection, holder)[session] == (
            True,
            owner,
            "material_privilege_reduction",
            "access-admin-role-bundle-reduced",
        )
        event = audit_event(connection, correlation)
        assert event["previous_state"]["capability_ids"] == [
            "invoices.read",
            "leases.read",
            "units.read",
        ]
        resulting = event["resulting_state"]
        assert (resulting["capability_ids"], resulting["sessions_revoked"]) == (["units.read"], 1)
        assert {capability for capability, _ in grants(connection, holder)} == {"units.read"}
        assert bundle_set(connection, bundle, 3) == set(grown)
        assert connection.execute(
            "SELECT version,name FROM app.role_bundle_versions WHERE role_bundle_id=%s "
            "ORDER BY version",
            (bundle,),
        ).fetchall() == [(1, "Front desk"), (2, "Desk"), (3, "Desk"), (4, "Desk")]
        listed = [row[2:] for row in connection.execute(BUNDLES, (owner,)).fetchall()]
        assert ("Desk", 4, ["units.read"]) in listed
        refused(
            connection,
            psycopg.errors.SerializationFailure,
            UPDATE_BUNDLE,
            (owner, bundle, 3, "Old desk", None, uuid.uuid4()),
            "the role bundle changed since it was read",
        )
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            UPDATE_BUNDLE,
            (owner, bundle, 4, None, None, uuid.uuid4()),
            "at least one role bundle change is required",
        )
        refused(
            connection,
            psycopg.errors.NoDataFound,
            UPDATE_BUNDLE,
            (owner, uuid.uuid4(), 1, "Nothing", None, uuid.uuid4()),
            "the role bundle does not exist",
        )
        connection.rollback()


def test_a_smaller_bundle_revokes_only_its_active_holders_sessions(
    migrated_database_url: str,
) -> None:
    """Review round 1: the Owner holding the bundle is revoked too; a removed holder, another
    bundle's holder and an expired session are not touched."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        reduced = one(
            connection,
            CREATE_BUNDLE,
            (owner, property_id, "Reduced", ["units.read", "leases.read"], uuid.uuid4()),
        )
        other_bundle = one(
            connection,
            CREATE_BUNDLE,
            (owner, property_id, "Other", ["units.read", "leases.read"], uuid.uuid4()),
        )
        holder, removed, other = (add_account(connection, "staff") for _ in range(3))
        for actor, bundle in (
            (holder, reduced),
            (removed, reduced),
            (other, other_bundle),
            (owner, reduced),
        ):
            one(connection, ASSIGN, (owner, actor, bundle, uuid.uuid4()))
        one(connection, REMOVE_ASSIGNMENT, (owner, removed, reduced, "Left", uuid.uuid4()))
        live = {actor: add_session(connection, actor) for actor in (holder, removed, other, owner)}
        expired = add_expired_session(connection, holder)
        correlation = uuid.uuid4()
        one(connection, UPDATE_BUNDLE, (owner, reduced, 1, None, ["units.read"], correlation))
        assert audit_event(connection, correlation)["resulting_state"]["sessions_revoked"] == 2
        for actor in (holder, owner):
            assert session_states(connection, actor)[live[actor]][0] is True
        for actor in (removed, other):
            assert session_states(connection, actor)[live[actor]] == NOT_REVOKED
        assert session_states(connection, holder)[expired] == NOT_REVOKED
        connection.rollback()


def test_role_bundles_are_assigned_and_removed(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        bundle = one(
            connection,
            CREATE_BUNDLE,
            (owner, property_id, "Readers", ["units.read"], uuid.uuid4()),
        )
        correlation = uuid.uuid4()
        assignment = one(connection, ASSIGN, (owner, staff, bundle, correlation))
        event = audit_event(connection, correlation)
        assert (event["action"], event["entity_id"]) == ("identity.role_assignment.created", staff)
        assert event["resulting_state"] == {
            "assignment_id": str(assignment),
            "role_bundle_id": str(bundle),
        }
        assert {capability for capability, _ in grants(connection, staff)} == {"units.read"}
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            ASSIGN,
            (owner, staff, bundle, uuid.uuid4()),
            "a role bundle is already assigned to this account",
        )
        for target in (add_account(connection, None), add_account(connection, "staff", "disabled")):
            refused(
                connection,
                psycopg.errors.InvalidParameterValue,
                ASSIGN,
                (owner, target, bundle, uuid.uuid4()),
                "a role bundle is assigned only to an active account with a class",
            )
        refused(
            connection,
            psycopg.errors.NoDataFound,
            ASSIGN,
            (owner, staff, uuid.uuid4(), uuid.uuid4()),
            "the role bundle does not exist",
        )
        # Sub-slice L1c note 2: the Owner may assign a bundle to itself.
        one(connection, ASSIGN, (owner, owner, bundle, uuid.uuid4()))
        session = add_session(connection, staff)
        correlation = uuid.uuid4()
        removal = (owner, staff, bundle, "Moved to day shift", correlation)
        assert one(connection, REMOVE_ASSIGNMENT, removal) == assignment
        assert connection.execute(
            "SELECT removed_by_actor_id,reason FROM app.user_role_assignment_removals "
            "WHERE assignment_id=%s",
            (assignment,),
        ).fetchall() == [(owner, "Moved to day shift")]
        assert session_states(connection, staff)[session][2:] == (
            "material_privilege_reduction",
            "access-admin-role-assignment-removed",
        )
        event = audit_event(connection, correlation)
        assert (event["action"], event["reason"]) == (
            "identity.role_assignment.removed",
            "Moved to day shift",
        )
        assert grants(connection, staff) == set()
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            REMOVE_ASSIGNMENT,
            (owner, staff, bundle, "Removed twice", uuid.uuid4()),
            "this account does not have that role bundle",
        )
        assert one(connection, ASSIGN, (owner, staff, bundle, uuid.uuid4())) != assignment
        connection.rollback()


def test_settings_access_is_given_and_removed_with_an_audit_event(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            GIVE_SETTINGS,
            (owner, staff, "Keeps the riel rate", uuid.uuid4()),
            NO_SIGN_IN_CODE,
        )
        add_sign_in_code(connection, staff)
        correlation = uuid.uuid4()
        given = one(connection, GIVE_SETTINGS, (owner, staff, "Keeps the riel rate", correlation))
        event = audit_event(connection, correlation)
        assert (event["action"], event["entity_id"], event["reason"]) == (
            "identity.settings_access.given",
            staff,
            "Keeps the riel rate",
        )
        assert event["resulting_state"] == {"grant_id": str(given)}
        assert account_row(connection, owner, staff)[7] is True
        correlation = uuid.uuid4()
        removal = (owner, staff, "Back to daily work", correlation)
        assert one(connection, REMOVE_SETTINGS, removal) == given
        event = audit_event(connection, correlation)
        assert (event["action"], event["previous_state"]) == (
            "identity.settings_access.removed",
            {"grant_id": str(given)},
        )
        assert account_row(connection, owner, staff)[7] is False
        assert grants(connection, staff) == set()
        # The Owner always has Settings access, shown as such in the list.
        assert account_row(connection, owner, owner)[6:8] == ("owner", True)
        connection.rollback()


def test_explicit_session_revocation_is_for_manager_and_staff_accounts(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        manager = add_account(connection, "manager")
        sessions = {add_session(connection, manager), add_session(connection, manager)}
        correlation = uuid.uuid4()
        assert one(connection, REVOKE_SESSIONS, (owner, manager, correlation)) == 2
        for session in sessions:
            assert session_states(connection, manager)[session][2:] == (
                "material_privilege_reduction",
                "access-admin-revoke-sessions",
            )
        assert audit_event(connection, correlation)["resulting_state"] == {"sessions_revoked": 2}
        assert one(connection, REVOKE_SESSIONS, (owner, manager, uuid.uuid4())) == 0
        for target in (owner, add_account(connection, None)):
            refused(
                connection,
                psycopg.errors.InvalidParameterValue,
                REVOKE_SESSIONS,
                (owner, target, uuid.uuid4()),
                "sessions are revoked here only for a Manager or Staff account",
            )
        connection.rollback()


def race(
    database_url: str,
    first: tuple[str, tuple[Any, ...]],
    second: tuple[str, tuple[Any, ...]],
) -> dict[str, Any]:
    """Run `first` uncommitted, start `second` in a thread, see it wait on a lock, commit
    `first`; return the second call's result or error. The first connection is rolled back
    before the thread is joined, so a failed wait check fails instead of hanging."""
    outcome: dict[str, Any] = {}
    with (
        psycopg.connect(database_url) as first_connection,
        psycopg.connect(database_url, options="-c lock_timeout=15s") as second_connection,
    ):
        first_connection.execute(*first)
        pid = second_connection.info.backend_pid

        def run_second() -> None:
            try:
                outcome["result"] = second_connection.execute(*second).fetchone()
                second_connection.commit()
            except psycopg.Error as error:
                outcome["error"] = error
                second_connection.rollback()

        waiter = threading.Thread(target=run_second, daemon=True)
        waiter.start()
        try:
            deadline = time.monotonic() + 5
            with psycopg.connect(database_url, autocommit=True) as watcher:
                while True:
                    row = watcher.execute(
                        "SELECT wait_event_type FROM pg_catalog.pg_stat_activity WHERE pid=%s",
                        (pid,),
                    ).fetchone()
                    if row is not None and row[0] == "Lock":
                        break
                    assert time.monotonic() < deadline, "the second call never waited"
                    time.sleep(0.05)
            first_connection.commit()
        finally:
            first_connection.rollback()
            waiter.join(20)
    assert not waiter.is_alive()
    return outcome


def test_concurrent_administration_waits_and_sees_the_committed_change(
    migrated_database_url: str,
) -> None:
    """Review round 1 (throwaway database, so an Owner may be committed): disable and give in both
    orders, a give against MFA off, and two changes of one account with the same version."""
    assert migrated_database_url
    with _temporary_migration_database("prm_access_admin_races") as temporary:
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(temporary) as setup:
            the_property(setup)
            owner = add_account(setup, "owner")
            staff = [add_account(setup, "staff") for _ in range(5)]
            for actor in (*staff[:3], staff[4]):
                add_sign_in_code(setup, actor)
            setup.commit()

        def give(actor: uuid.UUID) -> tuple[str, tuple[Any, ...]]:
            return (GIVE_SETTINGS, (owner, actor, "Keeps the riel rate", uuid.uuid4()))

        def update(actor: uuid.UUID, disable: Any, mfa: Any, name: Any = None) -> Any:
            return (UPDATE_ACCOUNT, (owner, actor, 1, name, None, disable, mfa, uuid.uuid4()))

        # A disable first: the give waits, then sees a disabled account.
        outcome = race(temporary, update(staff[0], True, None), give(staff[0]))
        assert isinstance(outcome["error"], psycopg.errors.InvalidParameterValue)
        assert "given only to a Manager or Staff account" in str(outcome["error"])
        # A give first: the disable waits, then succeeds; the grant stays as history.
        outcome = race(temporary, give(staff[1]), update(staff[1], True, None))
        assert outcome["result"] == (2,)
        # A give first: MFA off waits, then removes it (Q-2026-10-21-165 (a)).
        outcome = race(temporary, give(staff[2]), update(staff[2], None, "optional"))
        assert outcome["result"] == (2,)
        # Two changes from the same version: the second is refused after the wait.
        outcome = race(
            temporary,
            update(staff[3], None, None, "First"),
            update(staff[3], None, None, "Second"),
        )
        assert isinstance(outcome["error"], psycopg.errors.SerializationFailure)
        # Review round 2: MFA off first, so the waiting give sees no sign-in code.
        outcome = race(temporary, update(staff[4], None, "optional"), give(staff[4]))
        assert isinstance(outcome["error"], psycopg.errors.ObjectNotInPrerequisiteState)
        assert NO_SIGN_IN_CODE in str(outcome["error"])
        with psycopg.connect(temporary) as check:
            assert (
                one(
                    check,
                    "SELECT count(*) FROM app.user_capability_grants WHERE actor_id=%s",
                    (staff[0],),
                )
                == 0
            )
            assert grants(check, staff[1]) == set()
            assert account_row(check, owner, staff[1])[4:8] == (
                "disabled",
                "required",
                "staff",
                True,
            )
            assert check.execute(
                "SELECT removal.reason FROM app.user_capability_grants AS given "
                "JOIN app.user_capability_grant_removals AS removal USING (grant_id) "
                "WHERE given.actor_id=%s",
                (staff[2],),
            ).fetchall() == [("sign-in code turned off",)]
            assert account_row(check, owner, staff[3])[2] == "First"
            assert (
                one(
                    check,
                    "SELECT count(*) FROM app.user_capability_grants WHERE actor_id=%s",
                    (staff[4],),
                )
                == 0
            )


def test_the_runtime_role_administers_only_through_the_functions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        the_property(setup)
        manager = add_account(setup, "manager")
        staff = add_account(setup, "staff")
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        # The runtime role may call every definer function, which still refuses a non-Owner.
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            REVOKE_SESSIONS,
            (manager, staff, uuid.uuid4()),
            ONLY_OWNER,
        )
        refused(runtime, psycopg.errors.InsufficientPrivilege, ACCOUNTS, (manager,), ONLY_OWNER)
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            "SELECT 1 FROM app.user_account_changes",
            (),
            "permission denied",
        )
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            "SELECT app.user_account_version(%s)",
            (staff,),
            "permission denied",
        )
        runtime.rollback()


def test_the_access_administration_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """One relation (with its key) and two triggers are added, with eleven definer functions
    for the runtime role and eight internal functions (not definers, no EXECUTE for any
    application role); no existing function, trigger, relation, constraint or column changes;
    no application role may use the new relation (the backup role reads every table); forward-
    only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    roles = (
        "prm_runtime",
        "prm_financial",
        "prm_bootstrap",
        "prm_backup",
        "prm_restore",
        "prm_human_admin",
    )

    def catalog(database: str) -> dict[str, set[str]]:
        with psycopg.connect(database) as connection:

            def rows(query: str) -> set[str]:
                return {
                    ":".join(str(item) for item in found)
                    for found in connection.execute(query).fetchall()
                }

            present = connection.execute(
                "SELECT to_regclass('app.user_account_changes')"
            ).fetchone()
            return {
                "functions": rows(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.provolatile,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ),
                "triggers": rows(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text,"
                    "pg_catalog.pg_get_triggerdef(t.oid) FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ),
                "relations": rows(
                    "SELECT c.oid::regclass::text,c.relkind,c.relacl::text "
                    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='app'"
                ),
                "constraints": rows(
                    "SELECT con.conrelid::regclass::text,con.conname,"
                    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace "
                    "WHERE n.nspname='app'"
                ),
                "columns": rows(
                    "SELECT a.attrelid::regclass::text,a.attname,"
                    "pg_catalog.format_type(a.atttypid,a.atttypmod),a.attacl::text "
                    "FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c "
                    "ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind='r' "
                    "AND a.attnum>0 AND NOT a.attisdropped"
                ),
                "privileges": (
                    rows(
                        "SELECT role,'app.user_account_changes',"
                        "has_table_privilege(role,'app.user_account_changes','SELECT'),"
                        "has_table_privilege(role,'app.user_account_changes',"
                        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                        "has_any_column_privilege(role,'app.user_account_changes','SELECT'),"
                        "has_any_column_privilege(role,'app.user_account_changes',"
                        "'INSERT,UPDATE,REFERENCES') "
                        f"FROM unnest(ARRAY{list(roles)}) role"
                    )
                    | rows(
                        "SELECT role,function_name,"
                        "has_function_privilege(role,function_name,'EXECUTE') "
                        f"FROM unnest(ARRAY{list(roles)}) role, "
                        f"unnest(ARRAY{list(DEFINERS + INTERNAL)}) function_name"
                    )
                    if present != (None,)
                    else set()
                ),
            }

    with _temporary_migration_database("prm_access_administration") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("functions", "triggers", "relations", "constraints", "columns"):
        assert before[key] <= after[key], key

    def names(items: set[str]) -> set[str]:
        return {item.split(":")[0] for item in items}

    assert names(after["functions"] - before["functions"]) == set(DEFINERS + INTERNAL)
    added_functions = {
        item.split(":")[0]: item for item in after["functions"] - before["functions"]
    }
    for function, item in added_functions.items():
        definer = function in DEFINERS
        assert item.endswith(f":{definer}:{{search_path=pg_catalog}}"), function
    assert names(after["triggers"] - before["triggers"]) == {"app.user_account_changes"}
    assert names(after["relations"] - before["relations"]) == {
        "app.user_account_changes",
        "app.user_account_changes_pkey",
    }
    assert names(after["columns"] - before["columns"]) == {"app.user_account_changes"}
    assert names(after["constraints"] - before["constraints"]) == {"app.user_account_changes"}
    expected: set[str] = set()
    for role in roles:
        # The backup role reads every table through pg_read_all_data (scripts/postgres-init.sh).
        backup = role == "prm_backup"
        expected.add(f"{role}:app.user_account_changes:{backup}:False:{backup}:False")
        expected |= {f"{role}:{function}:False" for function in INTERNAL}
        expected |= {f"{role}:{function}:{role == 'prm_runtime'}" for function in DEFINERS}
    assert after["privileges"] == expected
