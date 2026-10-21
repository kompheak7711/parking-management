"""Per-user Settings access (login slice sub-slice L1d).

DL-074 answer 2, DL-075, DL-081 (owner answer (a) to Q-2026-10-21-151), SEC-014, SEC-021,
SEC-075, DB-AUTH-008: only the Owner account class gives or removes `settings.manage`, only to an
active Manager or Staff account; the Owner always has it; each grant and removal is an
append-only record; the grant reader gives it at the next read and takes it away at the next read
after its removal. Rows written here are rolled back, except the committed Manager and Staff
accounts, the Staff grant of the race and runtime-role tests and the runtime-role test's
Staff sign-in code (sub-slice L1e); no Owner is ever committed.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import GrantConnection, PostgresCapabilityGrantReader
from property_rental.identity import CapabilityGrant
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, grants, refused, the_property

REVISION = "20270121_178"
PREVIOUS = "20270120_177"
GIVE = "SELECT app.give_settings_access(%s,%s,%s)"
REMOVE = "SELECT app.remove_settings_access(%s,%s,%s)"
INSERT_GRANT = (
    "INSERT INTO app.user_capability_grants(grant_id,actor_id,capability_id,grant_path,"
    "given_by_actor_id,reason,provenance) VALUES (%s,%s,%s,%s,%s,%s,'login-slice-l1d-test')"
)
INSERT_REMOVAL = (
    "INSERT INTO app.user_capability_grant_removals(grant_id,removed_by_actor_id,reason,"
    "provenance) VALUES (%s,%s,%s,'login-slice-l1d-test')"
)
TABLES = ("app.user_capability_grants", "app.user_capability_grant_removals")
READER = "app.actor_capability_grants(uuid)"
NOT_DEFINERS = {
    "app.reject_settings_access_history_change()",
    "app.require_single_active_capability_grant()",
    "app.assert_settings_access_owner(uuid)",
}
DEFINERS = {
    "app.give_settings_access(uuid,uuid,text)",
    "app.remove_settings_access(uuid,uuid,text)",
}
ONLY_OWNER = "only the Owner gives or removes Settings access"
ONLY_MANAGER_OR_STAFF = "Settings access is given only to a Manager or Staff account"
ALREADY = "this account already has Settings access"
NONE_GIVEN = "this account has no Settings access"
APPEND_ONLY = "settings access history is append-only"
NO_SIGN_IN_CODE = "a Staff account gets Settings access only after it has set up its sign-in code"


def every_property(connection: psycopg.Connection[Any]) -> set[uuid.UUID]:
    return {row[0] for row in connection.execute("SELECT id FROM app.properties").fetchall()}


def settings_rows(connection: psycopg.Connection[Any]) -> set[tuple[str, uuid.UUID]]:
    return {("settings.manage", found) for found in every_property(connection)}


def one(connection: psycopg.Connection[Any], query: str, parameters: tuple[Any, ...]) -> Any:
    row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row[0]


def add_sign_in_code(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> uuid.UUID:
    """The account requires MFA and has an active sign-in code enrollment (owner rule of
    2026-10-21, sub-slice L1e), written as the table owner: the sign-in flow that sets one up
    comes with sub-slice L3c."""
    connection.execute(
        "UPDATE app.user_accounts SET mfa_policy_class='required' WHERE actor_id=%s", (actor_id,)
    )
    enrollment_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO app.totp_mfa_enrollments(enrollment_id,actor_id,secret_ciphertext,"
        "secret_nonce,key_identifier,protection_algorithm,totp_algorithm,created_by_actor_id,"
        "provenance) VALUES (%s,%s,%s,%s,'login-slice-l1e-test','aes-256-gcm','sha1',%s,"
        "'login-slice-l1e-test')",
        (enrollment_id, actor_id, b"c" * 36, uuid.uuid4().bytes[:12], actor_id),
    )
    connection.execute(
        "UPDATE app.totp_mfa_enrollments SET enrollment_state='active',"
        "activated_by_actor_id=%s,activation_provenance='login-slice-l1e-test' "
        "WHERE enrollment_id=%s",
        (actor_id, enrollment_id),
    )
    return enrollment_id


def test_the_owner_gives_and_removes_settings_access(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        manager = add_account(connection, "manager")
        staff = add_account(connection, "staff")
        given = one(connection, GIVE, (owner, manager, "Changes the Water Rate"))
        assert grants(connection, manager) == settings_rows(connection)
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            GIVE,
            (owner, manager, "Given twice"),
            ALREADY,
        )
        # Owner rule of 2026-10-21 (sub-slice L1e): a Staff account without a sign-in code
        # cannot be given Settings access, so this one sets up its code first.
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            GIVE,
            (owner, staff, "Covers the Manager"),
            NO_SIGN_IN_CODE,
        )
        add_sign_in_code(connection, staff)
        one(connection, GIVE, (owner, staff, "Covers the Manager"))
        assert grants(connection, staff) == settings_rows(connection)
        assert one(connection, REMOVE, (owner, manager, "Back to daily work")) == given
        # The removal takes effect at the next read and touches nothing else.
        assert grants(connection, manager) == set()
        assert grants(connection, staff) == settings_rows(connection)
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            REMOVE,
            (owner, manager, "Removed twice"),
            NONE_GIVEN,
        )
        again = one(connection, GIVE, (owner, manager, "Needed again"))
        assert again != given
        assert grants(connection, manager) == settings_rows(connection)
        # Review round 1: the Owner can also remove the Settings access of a disabled account,
        # so it does not come back when the account is enabled again.
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (staff,)
        )
        one(connection, REMOVE, (owner, staff, "Account disabled"))
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='active' WHERE actor_id=%s", (staff,)
        )
        assert grants(connection, staff) == set()
        assert connection.execute(
            "SELECT given.grant_id,given.given_by_actor_id,given.reason,given.provenance,"
            "removal.removed_by_actor_id,removal.reason,removal.provenance "
            "FROM app.user_capability_grants AS given LEFT JOIN "
            "app.user_capability_grant_removals AS removal USING (grant_id) "
            "WHERE given.actor_id=%s ORDER BY given.given_at,removal.reason NULLS LAST",
            (manager,),
        ).fetchall() == [
            (
                given,
                owner,
                "Changes the Water Rate",
                "owner-settings-access",
                owner,
                "Back to daily work",
                "owner-settings-access",
            ),
            (again, owner, "Needed again", "owner-settings-access", None, None, None),
        ]
        connection.rollback()


def test_only_the_owner_gives_settings_access_and_only_to_a_manager_or_staff_account(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        manager = add_account(connection, "manager")
        staff = add_account(connection, "staff")
        # A disabled Owner gives nothing (rolled back first: at most one Owner exists).
        with connection.transaction(force_rollback=True):
            disabled_owner = add_account(connection, "owner", "disabled")
            refused(
                connection,
                psycopg.errors.InsufficientPrivilege,
                GIVE,
                (disabled_owner, staff, "Disabled Owner"),
                ONLY_OWNER,
            )
        owner = add_account(connection, "owner")
        one(connection, GIVE, (owner, manager, "Changes the Water Rate"))
        for acting in (manager, staff, add_account(connection, None), uuid.uuid4()):
            for query in (GIVE, REMOVE):
                refused(
                    connection,
                    psycopg.errors.InsufficientPrivilege,
                    query,
                    (acting, staff, "Not the Owner"),
                    ONLY_OWNER,
                )
        refused(
            connection,
            psycopg.errors.InsufficientPrivilege,
            REMOVE,
            (staff, manager, "Not the Owner"),
            ONLY_OWNER,
        )
        for target in (
            owner,
            add_account(connection, None),
            add_account(connection, "staff", "disabled"),
            add_account(connection, "manager", "disabled"),
            uuid.uuid4(),
        ):
            refused(
                connection,
                psycopg.errors.InvalidParameterValue,
                GIVE,
                (owner, target, "Not a Manager or Staff account"),
                ONLY_MANAGER_OR_STAFF,
            )
            # Review round 1: a removal checks only the Owner; none of these has a grant.
            refused(
                connection,
                psycopg.errors.ObjectNotInPrerequisiteState,
                REMOVE,
                (owner, target, "Nothing to remove"),
                NONE_GIVEN,
            )
        connection.rollback()


def test_only_settings_access_is_stored_and_its_history_is_append_only(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        giver = add_account(connection, "manager")
        holder = add_account(connection, "staff")
        for capability, grant_path in (
            ("leases.read", "per_user"),
            ("settings.manage", "bundle"),
            ("identity.manage_access", "owner_class"),
        ):
            refused(
                connection,
                psycopg.errors.CheckViolation,
                INSERT_GRANT,
                (uuid.uuid4(), holder, capability, grant_path, giver, "Wrong capability"),
            )
        for reason in ("", "  ", "r" * 501):
            refused(
                connection,
                psycopg.errors.CheckViolation,
                INSERT_GRANT,
                (uuid.uuid4(), holder, "settings.manage", "per_user", giver, reason),
            )
        refused(
            connection,
            psycopg.errors.NotNullViolation,
            INSERT_GRANT,
            (uuid.uuid4(), holder, "settings.manage", "per_user", None, "No giver"),
        )
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            INSERT_GRANT,
            (uuid.uuid4(), holder, "settings.manage", "per_user", uuid.uuid4(), "Unknown giver"),
        )
        grant_id = uuid.uuid4()
        connection.execute(
            INSERT_GRANT, (grant_id, holder, "settings.manage", "per_user", giver, "Given")
        )
        refused(
            connection,
            psycopg.errors.ForeignKeyViolation,
            INSERT_REMOVAL,
            (grant_id, uuid.uuid4(), "Unknown remover"),
        )
        connection.execute(INSERT_REMOVAL, (grant_id, giver, "Removed"))
        refused(
            connection,
            psycopg.errors.UniqueViolation,
            INSERT_REMOVAL,
            (grant_id, giver, "Removed twice"),
        )
        for query in (
            "UPDATE app.user_capability_grants SET reason='changed' WHERE grant_id=%s",
            "DELETE FROM app.user_capability_grants WHERE grant_id=%s",
            "UPDATE app.user_capability_grant_removals SET reason='changed' WHERE grant_id=%s",
            "DELETE FROM app.user_capability_grant_removals WHERE grant_id=%s",
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                (grant_id,),
                APPEND_ONLY,
            )
        for query in (
            "TRUNCATE app.user_capability_grants CASCADE",
            "TRUNCATE app.user_capability_grant_removals",
        ):
            refused(connection, psycopg.errors.IntegrityConstraintViolation, query, (), APPEND_ONLY)
        connection.rollback()


def test_two_grants_of_settings_access_at_the_same_time_wait_and_one_is_refused(
    migrated_database_url: str,
) -> None:
    """Both at READ COMMITTED: the second waits on the advisory lock while the first is
    uncommitted and is refused once the first commits; any other isolation level is refused,
    for a grant and for a removal (fail closed). The Manager and Staff accounts and the first
    grant are committed (written as the table owner, so no Owner is committed)."""
    with psycopg.connect(migrated_database_url) as setup:
        the_property(setup)
        giver = add_account(setup, "manager")
        holder = add_account(setup, "staff")
        setup.commit()
    for isolation in (
        psycopg.IsolationLevel.REPEATABLE_READ,
        psycopg.IsolationLevel.SERIALIZABLE,
    ):
        with psycopg.connect(migrated_database_url) as other:
            other.isolation_level = isolation
            refused(
                other,
                psycopg.errors.ObjectNotInPrerequisiteState,
                INSERT_GRANT,
                (uuid.uuid4(), holder, "settings.manage", "per_user", giver, "Snapshot"),
                "Settings access is given only at READ COMMITTED",
            )
            with other.transaction(force_rollback=True):
                owner = add_account(other, "owner")
                refused(
                    other,
                    psycopg.errors.ObjectNotInPrerequisiteState,
                    REMOVE,
                    (owner, holder, "Snapshot"),
                    "Settings access is removed only at READ COMMITTED",
                )
            other.rollback()
    with (
        psycopg.connect(migrated_database_url) as first,
        # A lock timeout, so a wait that never ends fails instead of hanging.
        psycopg.connect(migrated_database_url, options="-c lock_timeout=15s") as second,
    ):
        first.execute(
            INSERT_GRANT, (uuid.uuid4(), holder, "settings.manage", "per_user", giver, "First")
        )
        errors: list[BaseException] = []

        def second_grant() -> None:
            try:
                second.execute(
                    INSERT_GRANT,
                    (uuid.uuid4(), holder, "settings.manage", "per_user", giver, "Second"),
                )
            except psycopg.Error as error:
                errors.append(error)

        waiter = threading.Thread(target=second_grant)
        waiter.start()
        try:
            with psycopg.connect(migrated_database_url, autocommit=True) as watcher:
                deadline = time.monotonic() + 5
                while watcher.execute(
                    "SELECT wait_event_type,wait_event FROM pg_catalog.pg_stat_activity "
                    "WHERE pid=%s",
                    (second.info.backend_pid,),
                ).fetchone() != ("Lock", "advisory"):
                    assert time.monotonic() < deadline, "the second grant never waited"
                    time.sleep(0.05)
            first.commit()
        finally:
            # Release the first's lock before waiting for the thread, so a failed wait check
            # ends the test instead of hanging it.
            first.rollback()
            waiter.join(timeout=20)
        assert not waiter.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], psycopg.errors.UniqueViolation)
        assert ALREADY in str(errors[0])
        second.rollback()
    # Review round 1: a removal takes the same lock. While an uncommitted removal of the
    # committed grant holds it, a new grant waits; when the removal is rolled back (no Owner is
    # committed), the grant is still active and the new grant is refused.
    with (
        psycopg.connect(migrated_database_url) as first,
        psycopg.connect(migrated_database_url, options="-c lock_timeout=15s") as second,
    ):
        owner = add_account(first, "owner")
        one(first, REMOVE, (owner, holder, "Uncommitted removal"))
        errors.clear()
        waiter = threading.Thread(target=second_grant)
        waiter.start()
        try:
            with psycopg.connect(migrated_database_url, autocommit=True) as watcher:
                deadline = time.monotonic() + 5
                while watcher.execute(
                    "SELECT wait_event_type,wait_event FROM pg_catalog.pg_stat_activity "
                    "WHERE pid=%s",
                    (second.info.backend_pid,),
                ).fetchone() != ("Lock", "advisory"):
                    assert time.monotonic() < deadline, "the grant never waited for the removal"
                    time.sleep(0.05)
        finally:
            first.rollback()
            waiter.join(timeout=20)
        assert not waiter.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], psycopg.errors.UniqueViolation)
        assert ALREADY in str(errors[0])
        second.rollback()


def test_the_reader_gives_settings_access_to_the_owner_and_to_given_accounts_only(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        manager = add_account(connection, "manager")
        staff = add_account(connection, "staff")
        properties = every_property(connection)
        assert grants(connection, owner) == {
            (capability, found)
            for capability in ("identity.manage_access", "settings.manage")
            for found in properties
        }
        assert grants(connection, manager) == set()
        # Review round 1: a grant written by hand for an unclassified account gives nothing.
        unclassified = add_account(connection, None)
        connection.execute(
            INSERT_GRANT,
            (uuid.uuid4(), unclassified, "settings.manage", "per_user", manager, "By hand"),
        )
        assert grants(connection, unclassified) == set()
        one(connection, GIVE, (owner, manager, "Changes the Water Rate"))
        # Owner rule of 2026-10-21 (sub-slice L1e): a Staff account without a sign-in code
        # cannot be given Settings access, so this one sets up its code first.
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            GIVE,
            (owner, staff, "Covers the Manager"),
            NO_SIGN_IN_CODE,
        )
        add_sign_in_code(connection, staff)
        one(connection, GIVE, (owner, staff, "Covers the Manager"))
        reader = PostgresCapabilityGrantReader(cast(GrantConnection, connection))
        assert reader.grants_for(manager) == frozenset(
            {CapabilityGrant("settings.manage", frozenset(str(found) for found in properties))}
        )
        # A disabled holder gets nothing; the grant itself is kept.
        connection.execute(
            "UPDATE app.user_accounts SET lifecycle_state='disabled' WHERE actor_id=%s", (staff,)
        )
        assert grants(connection, staff) == set()
        one(connection, REMOVE, (owner, manager, "Back to daily work"))
        assert grants(connection, manager) == set()
        assert grants(connection, owner) == {
            (capability, found)
            for capability in ("identity.manage_access", "settings.manage")
            for found in properties
        }
        connection.rollback()


def test_the_runtime_role_reaches_settings_access_only_through_its_functions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        the_property(setup)
        manager = add_account(setup, "manager")
        staff = add_account(setup, "staff")
        # Sub-slice L1e: a Staff holder's Settings access works only with its sign-in code.
        add_sign_in_code(setup, staff)
        setup.execute(
            INSERT_GRANT,
            (uuid.uuid4(), staff, "settings.manage", "per_user", manager, "Runtime test"),
        )
        properties = every_property(setup)
        setup.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        assert grants(runtime, staff) == {("settings.manage", found) for found in properties}
        # The runtime role may call the functions, which still refuse a non-Owner.
        for query in (GIVE, REMOVE):
            refused(
                runtime,
                psycopg.errors.InsufficientPrivilege,
                query,
                (manager, staff, "Not the Owner"),
                ONLY_OWNER,
            )
        for table in TABLES:
            refused(
                runtime,
                psycopg.errors.InsufficientPrivilege,
                f"SELECT 1 FROM {table}",
                (),
                "permission denied",
            )
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            INSERT_GRANT,
            (uuid.uuid4(), manager, "settings.manage", "per_user", manager, "Direct"),
            "permission denied",
        )
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            "SELECT app.assert_settings_access_owner(%s)",
            (manager,),
            "permission denied",
        )
        runtime.rollback()


def test_the_settings_access_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Two relations (with their keys and one index), three functions that are not definers,
    two definer functions, five triggers and the replaced reader (same signature, still a
    STABLE definer with `search_path=pg_catalog`, PUBLIC revoked) are added; nothing else
    changes; the runtime role may only execute the two definer functions and the reader;
    forward-only."""
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
    functions = sorted({*NOT_DEFINERS, *DEFINERS, READER})

    def catalog(database: str) -> dict[str, set[str]]:
        with psycopg.connect(database) as connection:

            def rows(query: str) -> set[str]:
                return {
                    ":".join(str(item) for item in found)
                    for found in connection.execute(query).fetchall()
                }

            present = connection.execute(
                "SELECT to_regclass('app.user_capability_grants')"
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
                        "SELECT role,table_name,"
                        "has_table_privilege(role,table_name,'SELECT'),"
                        "has_table_privilege(role,table_name,"
                        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
                        f"FROM unnest(ARRAY{list(roles)}) role, "
                        f"unnest(ARRAY{list(TABLES)}) table_name"
                    )
                    | rows(
                        "SELECT role,function_name,"
                        "has_function_privilege(role,function_name,'EXECUTE') "
                        f"FROM unnest(ARRAY{list(roles)}) role, "
                        f"unnest(ARRAY{functions}) function_name"
                    )
                    if present != (None,)
                    else set()
                ),
            }

    with _temporary_migration_database("prm_settings_access") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    def without_reader(items: set[str]) -> set[str]:
        return {item for item in items if not item.startswith(READER + ":")}

    assert without_reader(before["functions"]) <= after["functions"]
    for key in ("triggers", "relations", "constraints", "columns"):
        assert before[key] <= after[key]
    added = {item.split(":")[0]: item for item in after["functions"] - before["functions"]}
    assert set(added) == {*NOT_DEFINERS, *DEFINERS, READER}
    for function, item in added.items():
        stable = (READER, "app.assert_settings_access_owner(uuid)")
        volatility = "s" if function in stable else "v"
        definer = "True" if function in (*DEFINERS, READER) else "False"
        assert item.endswith(f":{volatility}:{definer}:{{search_path=pg_catalog}}"), function
    (old_reader,) = (item for item in before["functions"] if item.startswith(READER + ":"))
    # The reader keeps its owner and privileges; only its body gains the Settings access rows.
    assert old_reader.split(":")[-5:] == added[READER].split(":")[-5:]
    assert "settings.manage" in added[READER] and "settings.manage" not in old_reader
    assert {item.split(":")[1] for item in after["triggers"] - before["triggers"]} == {
        "user_capability_grants_are_append_only",
        "user_capability_grants_reject_truncate",
        "user_capability_grants_single_active",
        "user_capability_grant_removals_are_append_only",
        "user_capability_grant_removals_reject_truncate",
    }
    assert {item.split(":")[0] for item in after["relations"] - before["relations"]} == {
        *TABLES,
        "app.user_capability_grants_pkey",
        "app.user_capability_grants_actor_idx",
        "app.user_capability_grant_removals_pkey",
    }
    for key in ("constraints", "columns"):
        assert {item.split(":")[0] for item in after[key] - before[key]} == set(TABLES)
    expected: set[str] = set()
    for role in roles:
        # The backup role reads every table through pg_read_all_data (scripts/postgres-init.sh).
        expected |= {f"{role}:{table}:{role == 'prm_backup'}:False" for table in TABLES}
        expected |= {f"{role}:{function}:False" for function in NOT_DEFINERS}
        expected |= {
            f"{role}:{function}:{role == 'prm_runtime'}" for function in (*DEFINERS, READER)
        }
    assert after["privileges"] == expected
