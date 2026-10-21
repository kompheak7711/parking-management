"""Settings access needs the sign-in code (login slice sub-slice L1e).

DL-081 (owner rule of 2026-10-21, amending DL-074 answer 2), SEC-013, SEC-021, DB-AUTH-008: the
Owner gives Settings access to a Staff account only after it has set up its sign-in code (MFA
policy `required` and an `active` enrollment), and the grant reader gives a Staff account's
Settings access only while that holds. Rows written here are rolled back.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import (
    STAFF_DEFAULT_BUNDLE_CAPABILITIES,
    GrantConnection,
    PostgresCapabilityGrantReader,
)
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_role_bundle_migration import add_account, assign, grants, refused, the_property
from test_settings_access_migration import (
    GIVE,
    INSERT_GRANT,
    NO_SIGN_IN_CODE,
    add_sign_in_code,
    one,
    settings_rows,
)

REVISION = "20270123_180"
PREVIOUS = "20270122_179"
GIVE_FUNCTION = "app.give_settings_access(uuid,uuid,text)"
READER = "app.actor_capability_grants(uuid)"
HELPER = "app.staff_sign_in_code_is_set_up(uuid)"
SET_POLICY = "UPDATE app.user_accounts SET mfa_policy_class=%s WHERE actor_id=%s"


def pending_sign_in_code(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> uuid.UUID:
    """A sign-in code enrollment that was started but never confirmed."""
    enrollment_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO app.totp_mfa_enrollments(enrollment_id,actor_id,secret_ciphertext,"
        "secret_nonce,key_identifier,protection_algorithm,totp_algorithm,created_by_actor_id,"
        "provenance) VALUES (%s,%s,%s,%s,'login-slice-l1e-test','aes-256-gcm','sha1',%s,"
        "'login-slice-l1e-test')",
        (enrollment_id, actor_id, b"c" * 36, uuid.uuid4().bytes[:12], actor_id),
    )
    return enrollment_id


def disable_sign_in_code(
    connection: psycopg.Connection[Any], enrollment_id: uuid.UUID, by: uuid.UUID
) -> None:
    """As an MFA reset does (`app.perform_account_recovery`, migration `20260819_08`)."""
    connection.execute(
        "UPDATE app.totp_mfa_enrollments SET enrollment_state='disabled',"
        "disabled_by_actor_id=%s,disablement_provenance='login-slice-l1e-test' "
        "WHERE enrollment_id=%s",
        (by, enrollment_id),
    )


def test_a_staff_account_gets_settings_access_only_after_setting_up_its_sign_in_code(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")

        def give_refused(reason: str) -> None:
            refused(
                connection,
                psycopg.errors.ObjectNotInPrerequisiteState,
                GIVE,
                (owner, staff, reason),
                NO_SIGN_IN_CODE,
            )

        give_refused("Optional MFA and no sign-in code")
        connection.execute(SET_POLICY, ("required", staff))
        give_refused("MFA required but no sign-in code")
        enrollment = pending_sign_in_code(connection, staff)
        give_refused("Sign-in code started but not confirmed")
        connection.execute(
            "UPDATE app.totp_mfa_enrollments SET enrollment_state='active',"
            "activated_by_actor_id=%s,activation_provenance='login-slice-l1e-test' "
            "WHERE enrollment_id=%s",
            (staff, enrollment),
        )
        connection.execute(SET_POLICY, ("optional", staff))
        give_refused("Sign-in code set up but not asked at every sign-in")
        assert grants(connection, staff) == set()
        connection.execute(SET_POLICY, ("required", staff))
        one(connection, GIVE, (owner, staff, "Keeps the riel rate up to date"))
        assert grants(connection, staff) == settings_rows(connection)
        # A Manager always needs the sign-in code at sign-in by its class (sub-slice L1a), so
        # the give does not wait for its enrollment.
        manager = add_account(connection, "manager")
        one(connection, GIVE, (owner, manager, "Changes the Water Rate"))
        assert grants(connection, manager) == settings_rows(connection)
        connection.rollback()


def test_a_staff_holder_has_settings_access_only_while_its_sign_in_code_is_set_up(
    migrated_database_url: str,
) -> None:
    """Whatever path changes the sign-in code or the MFA policy, a Staff account's Settings
    access stops working at the next read; the grant itself stays recorded."""
    with psycopg.connect(migrated_database_url) as connection:
        the_property(connection)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        first_code = add_sign_in_code(connection, staff)
        grant_id = one(connection, GIVE, (owner, staff, "Keeps the riel rate up to date"))
        assert grants(connection, staff) == settings_rows(connection)
        # Dara's phone is lost and the sign-in code is reset.
        disable_sign_in_code(connection, first_code, owner)
        assert grants(connection, staff) == set()
        assert connection.execute(
            "SELECT count(*) FROM app.user_capability_grants AS given "
            "WHERE given.grant_id=%s AND NOT EXISTS (SELECT 1 FROM "
            "app.user_capability_grant_removals AS removal WHERE removal.grant_id=given.grant_id)",
            (grant_id,),
        ).fetchone() == (1,)
        add_sign_in_code(connection, staff)
        assert grants(connection, staff) == settings_rows(connection)
        connection.execute(SET_POLICY, ("optional", staff))
        assert grants(connection, staff) == set()
        connection.execute(SET_POLICY, ("required", staff))
        assert grants(connection, staff) == settings_rows(connection)
        # A grant written by hand for a Staff account without a sign-in code gives nothing,
        # also through the application reader.
        other = add_account(connection, "staff")
        manager = add_account(connection, "manager")
        connection.execute(
            INSERT_GRANT,
            (uuid.uuid4(), other, "settings.manage", "per_user", manager, "By hand"),
        )
        assert grants(connection, other) == set()
        reader = PostgresCapabilityGrantReader(cast(GrantConnection, connection))
        assert reader.grants_for(other) == frozenset()
        connection.rollback()


def test_a_staff_account_without_a_sign_in_code_keeps_its_bundle_capabilities(
    migrated_database_url: str,
) -> None:
    """Review round 1: the sign-in code rule touches only Settings access; a Staff account
    without a code still gets its default bundle's capabilities, and a hand-written grant adds
    no Settings access."""
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        staff = add_account(connection, "staff")
        manager = add_account(connection, "manager")
        row = connection.execute(
            "SELECT staff_bundle_id FROM app.seed_default_role_bundles(%s)", (property_id,)
        ).fetchone()
        assert row is not None
        assign(connection, staff, row[0], property_id)
        connection.execute(
            INSERT_GRANT,
            (uuid.uuid4(), staff, "settings.manage", "per_user", manager, "By hand"),
        )
        assert grants(connection, staff) == {
            (capability, property_id) for capability in STAFF_DEFAULT_BUNDLE_CAPABILITIES
        }
        connection.rollback()


def test_the_settings_access_sign_in_code_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the give function and the reader bodies change (same signature, owner,
    privileges, volatility, definer flag and settings) and one internal function is added
    (STABLE, not a definer, `search_path=pg_catalog`, no EXECUTE for any application role);
    no relation, trigger, constraint or column changes; forward-only."""
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

            present = connection.execute(f"SELECT to_regprocedure('{HELPER}')").fetchone()
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
                "privileges": rows(
                    "SELECT role,function_name,"
                    "has_function_privilege(role,function_name,'EXECUTE') "
                    f"FROM unnest(ARRAY{list(roles)}) role, "
                    "unnest(ARRAY["
                    + ",".join(
                        f"'{function}'"
                        for function in (
                            (GIVE_FUNCTION, READER, HELPER)
                            if present != (None,)
                            else (GIVE_FUNCTION, READER)
                        )
                    )
                    + "]) function_name"
                ),
            }

    with _temporary_migration_database("prm_settings_access_sign_in_code") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("triggers", "relations", "constraints", "columns"):
        assert before[key] == after[key], key

    def by_name(items: set[str]) -> dict[str, str]:
        return {item.split(":")[0]: item for item in items}

    old, new = by_name(before["functions"]), by_name(after["functions"])
    assert set(new) == set(old) | {HELPER}
    assert {name for name in old if old[name] != new[name]} == {GIVE_FUNCTION, READER}
    for function in (GIVE_FUNCTION, READER):
        # Same owner, privileges, volatility, definer flag and settings; only the body changes.
        assert old[function].split(":")[-5:] == new[function].split(":")[-5:]
        assert "staff_sign_in_code_is_set_up" in new[function]
    assert new[HELPER].endswith(":s:False:{search_path=pg_catalog}")
    assert before["privileges"] <= after["privileges"]
    added_privileges = after["privileges"] - before["privileges"]
    assert added_privileges == {f"{role}:{HELPER}:False" for role in roles}
    assert {item for item in after["privileges"] if item.endswith(":True")} == {
        f"prm_runtime:{function}:True" for function in (GIVE_FUNCTION, READER)
    }
