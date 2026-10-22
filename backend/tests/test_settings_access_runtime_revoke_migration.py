"""Only the audited Settings access functions for the runtime role (login sub-slice L2b-1).

DL-081 (Q-2026-10-21-167 (a), owner, 2026-10-22), SEC-014, SEC-075, DB-AUTH-008: the runtime
role can no longer execute the unaudited `app.give_settings_access` and
`app.remove_settings_access`; it gives and removes Settings access only through the audited L2a
functions. Both tests use throwaway databases, so an Owner may be committed there.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_access_administration_migration import GIVE_SETTINGS, REMOVE_SETTINGS, audit_event
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, grants, refused, the_property
from test_settings_access_migration import GIVE, REMOVE, add_sign_in_code, one

REVISION = "20270125_182"
PREVIOUS = "20270124_181"
UNAUDITED = (
    "app.give_settings_access(uuid,uuid,text)",
    "app.remove_settings_access(uuid,uuid,text)",
)
AUDITED = (
    "app.admin_give_settings_access(uuid,uuid,text,uuid)",
    "app.admin_remove_settings_access(uuid,uuid,text,uuid)",
)
ROLES = (
    "prm_runtime",
    "prm_financial",
    "prm_bootstrap",
    "prm_backup",
    "prm_restore",
    "prm_human_admin",
)


def test_the_runtime_role_changes_settings_access_only_through_the_audited_functions(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with _temporary_migration_database("prm_settings_access_revoke") as temporary:
        assert _run_alembic("upgrade", REVISION).returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            the_property(setup)
            owner = add_account(setup, "owner")
            staff = add_account(setup, "staff")
            add_sign_in_code(setup, staff)
            setup.commit()
        with psycopg.connect(runtime_url) as runtime:
            for query in (GIVE, REMOVE):
                refused(
                    runtime,
                    psycopg.errors.InsufficientPrivilege,
                    query,
                    (owner, staff, "Keeps the riel rate"),
                    "permission denied",
                )
            correlation = uuid.uuid4()
            given = one(runtime, GIVE_SETTINGS, (owner, staff, "Keeps the riel rate", correlation))
            assert audit_event(runtime, correlation)["action"] == "identity.settings_access.given"
            assert {capability for capability, _ in grants(runtime, staff)} == {"settings.manage"}
            correlation = uuid.uuid4()
            removal = (owner, staff, "Back to daily work", correlation)
            assert one(runtime, REMOVE_SETTINGS, removal) == given
            assert audit_event(runtime, correlation)["action"] == (
                "identity.settings_access.removed"
            )
            assert grants(runtime, staff) == set()
            runtime.rollback()


def test_the_settings_access_runtime_revoke_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the runtime role's EXECUTE on the two unaudited functions goes away; no function
    body, relation, trigger, constraint or column changes; forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> dict[str, set[str]]:
        with psycopg.connect(database) as connection:

            def rows(query: str) -> set[str]:
                return {
                    ":".join(str(item) for item in found)
                    for found in connection.execute(query).fetchall()
                }

            return {
                "functions": rows(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proowner,p.provolatile,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ),
                "acls": rows(
                    "SELECT p.oid::regprocedure::text,p.proacl::text "
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
                    f"FROM unnest(ARRAY{list(ROLES)}) role, "
                    f"unnest(ARRAY{list(UNAUDITED + AUDITED)}) function_name"
                ),
            }

    with _temporary_migration_database("prm_settings_access_revoke_catalog") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("functions", "triggers", "relations", "constraints", "columns"):
        assert before[key] == after[key], key

    def by_name(items: set[str]) -> dict[str, str]:
        return {item.split(":")[0]: item for item in items}

    old, new = by_name(before["acls"]), by_name(after["acls"])
    assert set(old) == set(new)
    assert {name for name in old if old[name] != new[name]} == set(UNAUDITED)
    for function in UNAUDITED:
        assert "prm_runtime=X/" in old[function]
        assert "prm_runtime" not in new[function]
    assert before["privileges"] - after["privileges"] == {
        f"prm_runtime:{function}:True" for function in UNAUDITED
    }
    assert {item for item in after["privileges"] if item.endswith(":True")} == {
        f"prm_runtime:{function}:True" for function in AUDITED
    }
