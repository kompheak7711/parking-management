"""The append-only capability catalog (login slice sub-slice L1b-1).

SEC-001 to SEC-003, SEC-021, API-080, DB-AUTH-006, DL-074, DL-081 (owner answers (a) to
Q-2026-10-21-151, Q-2026-10-21-158, Q-2026-10-21-160 and Q-2026-10-21-161, (b) to
Q-2026-10-21-162): `app.capabilities` holds exactly the catalog of `property_rental.access_control`
with each capability's grant path (`settings.manage` per user, `identity.manage_access` Owner
class only, `rent_nonpayment.evaluate` a service principal's, every other one a bundle
capability); the catalog is never updated, deleted or truncated. Every write here is rolled back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import CAPABILITY_CATALOG, capability_grant_path
from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

REVISION = "20270119_176"
PREVIOUS = "20270118_175"
GUARD = "app.reject_capability_catalog_change()"
ADD = (
    "INSERT INTO app.capabilities(capability_id,family,description,grant_path,"
    "provenance) VALUES (%s,%s,'A test capability',%s,'login-slice-l1b-test')"
)


def refused(
    connection: psycopg.Connection[Any],
    error: type[Exception],
    query: str,
    parameters: tuple[Any, ...] = (),
    match: str | None = None,
) -> None:
    with pytest.raises(error, match=match):
        with connection.transaction():
            connection.execute(query, parameters)


def test_the_catalog_table_holds_exactly_the_application_catalog(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(runtime_database_url()) as runtime:
        rows = runtime.execute(
            "SELECT capability_id,family,description,grant_path,provenance,isfinite(added_at) "
            "FROM app.capabilities ORDER BY capability_id"
        ).fetchall()
    # Sorted in Python: the database collation orders `lease_signers` before `leases`.
    assert sorted(row[0] for row in rows) == sorted(CAPABILITY_CATALOG)
    for capability, family, description, grant_path, provenance, finite in rows:
        assert family == capability.split(".", 1)[0]
        assert description == CAPABILITY_CATALOG[capability]
        assert grant_path == capability_grant_path(capability)
        # The V1-057 report and export rights came with migration `20270301_220`, and the
        # V1-061 lower-Rent right with migration `20270401_251`.
        expected = (
            "v1-057-reports"
            if capability in {"audit.export", "data.export", "reports.read"}
            else "v1-061-unit-rent"
            if capability == "rent.below_default"
            else "login-slice-capability-catalog"
        )
        assert provenance == expected and finite is True
    assert {(row[0], row[3]) for row in rows if row[3] != "bundle"} == {
        ("settings.manage", "per_user"),
        ("identity.manage_access", "owner_class"),
        ("rent_nonpayment.evaluate", "service_principal"),
    }
    assert ("billing.generate", "bundle") in {(row[0], row[3]) for row in rows}


def test_a_catalog_row_needs_a_dotted_name_its_family_a_description_and_a_grant_path(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for capability, family, grant_path in (
            ("Leases.read", "Leases", "bundle"),
            ("leases", "leases", "bundle"),
            ("leases.read.", "leases", "bundle"),
            ("leases read", "leases read", "bundle"),
            ("tests.login_new", "leases", "bundle"),
            ("tests." + "a" * 123, "tests", "bundle"),
            ("tests.login_new", "tests", "admin"),
            ("tests.login_new", "tests", "Bundle"),
        ):
            refused(
                connection, psycopg.errors.CheckViolation, ADD, (capability, family, grant_path)
            )
        insert = (
            "INSERT INTO app.capabilities(capability_id,family,description,grant_path,"
            "provenance,added_at) VALUES ('tests.login_wrong','tests',%s,'bundle',"
            "'login-slice-l1b-test',%s)"
        )
        for description, added_at in (("  ", "now"), ("A test capability", "infinity")):
            refused(connection, psycopg.errors.CheckViolation, insert, (description, added_at))
        refused(
            connection, psycopg.errors.UniqueViolation, ADD, ("leases.read", "leases", "per_user")
        )
        connection.execute(ADD, ("tests." + "a" * 122, "tests", "per_user"))
        connection.execute(ADD, ("tests.login_new", "tests", "bundle"))
        assert connection.execute(
            "SELECT pg_catalog.pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
            "WHERE conname='capabilities_capability_grant_path_key'"
        ).fetchone() == ("UNIQUE (capability_id, grant_path)",)
        connection.rollback()


def test_the_capability_catalog_is_append_only(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        for query in (
            "UPDATE app.capabilities SET description='changed' WHERE capability_id='leases.read'",
            "UPDATE app.capabilities SET grant_path='bundle' WHERE capability_id='settings.manage'",
            "UPDATE app.capabilities SET grant_path='bundle' "
            "WHERE capability_id='identity.manage_access'",
            "DELETE FROM app.capabilities WHERE capability_id='leases.read'",
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                match="capability catalog is append-only",
            )
        # Since sub-slice L1b-2 `app.role_bundle_capabilities` refers to the catalog, so a TRUNCATE
        # of the catalog alone is refused by that foreign key before the trigger runs; the
        # trigger's refusal is checked with both tables in test_role_bundle_migration.py.
        refused(
            connection,
            psycopg.errors.FeatureNotSupported,
            "TRUNCATE app.capabilities",
            match="cannot truncate a table referenced in a foreign key constraint",
        )
        connection.rollback()
    with psycopg.connect(runtime_database_url()) as runtime:
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            ADD,
            ("tests.login_runtime", "tests", "bundle"),
        )
        runtime.rollback()


def test_the_capability_catalog_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """One relation (with its key index and its capability and grant path index), one trigger
    function (not a definer, no EXECUTE for the application roles) and two triggers are added; no
    existing function, trigger, relation, constraint or column changes; the runtime role may only
    read the catalog; forward-only."""
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
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
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
                    "SELECT role,has_table_privilege(role,'app.capabilities','SELECT'),"
                    "has_table_privilege(role,'app.capabilities',"
                    "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                    f"has_function_privilege(role,'{GUARD}','EXECUTE') "
                    "FROM unnest(ARRAY['prm_runtime','prm_financial','prm_bootstrap',"
                    "'prm_backup','prm_restore','prm_human_admin']) role"
                )
                if connection.execute("SELECT to_regclass('app.capabilities')").fetchone()
                != (None,)
                else set(),
            }

    with _temporary_migration_database("prm_capability_catalog") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)

    for key in ("functions", "triggers", "relations", "constraints", "columns"):
        assert before[key] <= after[key]
    added_functions = after["functions"] - before["functions"]
    assert [item.split(":")[0] for item in added_functions] == [GUARD]
    (guard,) = added_functions
    assert guard.endswith(":False:{search_path=pg_catalog}")
    assert {item.split(":")[1] for item in after["triggers"] - before["triggers"]} == {
        "capabilities_are_append_only",
        "capabilities_reject_truncate",
    }
    assert {item.split(":")[0] for item in after["relations"] - before["relations"]} == {
        "app.capabilities",
        "app.capabilities_pkey",
        "app.capabilities_capability_grant_path_key",
    }
    for key in ("constraints", "columns"):
        assert {item.split(":")[0] for item in after[key] - before[key]} == {"app.capabilities"}
    assert after["privileges"] == {
        "prm_runtime:True:False:False",
        "prm_financial:False:False:False",
        "prm_bootstrap:False:False:False",
        # Review round 2: the other application roles get nothing either; the backup role reads
        # every table through pg_read_all_data (scripts/postgres-init.sh), as for every relation.
        "prm_backup:True:False:False",
        "prm_restore:False:False:False",
        "prm_human_admin:False:False:False",
    }
