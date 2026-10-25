"""The default Owner, Manager and Staff role bundles (login slice sub-slice L1c).

DL-074 answer 1, DL-080 item 2, DL-081 (owner answers (a) to Q-2026-10-21-150 and
Q-2026-10-21-164, G7, (a) to Q-2026-10-21-161 and (b) to Q-2026-10-21-162), SEC-021, SEC-022,
API-080, DB-AUTH-009: a Property gets its three default bundles once; the Owner and Manager
bundles hold every bundle capability of the catalog, the Staff bundle the approved daily work
only; the Owner-class account gets the Owner bundle; seeding again changes nothing; the bundles
stay editable data. Rows written on the shared test database are rolled back; the migration,
Property setup and race tests use throwaway databases.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.access_control import (
    BUNDLE_CAPABILITIES,
    STAFF_DEFAULT_BUNDLE_CAPABILITIES,
    STAFF_L1C_BUNDLE_CAPABILITIES,
    GrantConnection,
    PostgresCapabilityGrantReader,
)
from property_rental.property import (
    PostgresPropertyConfigurationRepository,
    PropertyAlreadyConfiguredError,
    PropertyConfiguration,
    configure_postgres_property,
)
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import (
    add_account,
    assign,
    grants,
    next_version,
    refused,
    the_property,
)

REVISION = "20270122_179"
PREVIOUS = "20270121_178"
SEED = "app.seed_default_role_bundles(uuid)"
SEED_QUERY = (
    "SELECT owner_bundle_id,manager_bundle_id,staff_bundle_id "
    "FROM app.seed_default_role_bundles(%s)"
)
TABLE = "app.default_role_bundles"
PROVENANCE = "login-slice-default-bundles"
APPEND_ONLY = "role bundle history is append-only"
ONLY_READ_COMMITTED = "default role bundles are seeded only at READ COMMITTED"


def seed(connection: psycopg.Connection[Any], property_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
    row = connection.execute(SEED_QUERY, (property_id,)).fetchone()
    assert row is not None
    return cast(tuple[uuid.UUID, ...], tuple(row))


def bundle_capabilities(connection: psycopg.Connection[Any], bundle_id: uuid.UUID) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT capability.capability_id FROM app.role_bundles AS bundle "
            "JOIN app.role_bundle_capabilities AS capability "
            "ON capability.role_bundle_id=bundle.role_bundle_id "
            "AND capability.version=bundle.version WHERE bundle.role_bundle_id=%s",
            (bundle_id,),
        ).fetchall()
    }


def catalog_bundle_capabilities(connection: psycopg.Connection[Any]) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT capability_id FROM app.capabilities WHERE grant_path='bundle'"
        ).fetchall()
    }


def assignments(connection: psycopg.Connection[Any], actor_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return connection.execute(
        "SELECT role_bundle_id,assigned_by_actor_id,provenance FROM app.user_role_assignments "
        "WHERE actor_id=%s",
        (actor_id,),
    ).fetchall()


def add_owner_and_property(connection: psycopg.Connection[Any]) -> tuple[uuid.UUID, uuid.UUID]:
    """An Owner-class account and the Property it set up, as on a new deployment (throwaway
    databases only: at most one Owner exists)."""
    owner = add_account(connection, "owner")
    property_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO app.properties (id, name, created_by, updated_by) "
        "VALUES (%s, 'Default Bundles Property', %s, %s)",
        (property_id, owner, owner),
    )
    return owner, property_id


def test_the_default_bundles_hold_the_approved_capabilities(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        # Review round 1 note: the shared test database holds no defaults (this module runs
        # last and rolls back what it seeds), so a stale database fails here, not later.
        assert connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)
        owner = add_account(connection, "owner")
        manager = add_account(connection, "manager")
        staff = add_account(connection, "staff")
        owner_bundle, manager_bundle, staff_bundle = seed(connection, property_id)
        assert connection.execute(
            "SELECT name,version,provenance FROM app.role_bundles WHERE role_bundle_id=%s",
            (owner_bundle,),
        ).fetchone() == ("Owner", 1, PROVENANCE)
        assert connection.execute(
            "SELECT name,version,provenance FROM app.role_bundles WHERE role_bundle_id=%s",
            (manager_bundle,),
        ).fetchone() == ("Manager", 1, PROVENANCE)
        assert connection.execute(
            "SELECT name,version,provenance FROM app.role_bundles WHERE role_bundle_id=%s",
            (staff_bundle,),
        ).fetchone() == ("Staff", 1, PROVENANCE)
        assert connection.execute(
            f"SELECT owner_bundle_id,manager_bundle_id,staff_bundle_id,provenance FROM {TABLE} "
            "WHERE property_id=%s",
            (property_id,),
        ).fetchone() == (owner_bundle, manager_bundle, staff_bundle, PROVENANCE)
        every_bundle_capability = catalog_bundle_capabilities(connection)
        assert every_bundle_capability == set(BUNDLE_CAPABILITIES)
        # The Owner and Manager bundles are the same (Q-162 (b)); the Owner's extra rights come
        # from the account class. Staff hold exactly the approved list (Q-150 (a), Q-164 (a)).
        assert bundle_capabilities(connection, owner_bundle) == every_bundle_capability
        assert bundle_capabilities(connection, manager_bundle) == every_bundle_capability
        assert bundle_capabilities(connection, staff_bundle) == set(
            STAFF_DEFAULT_BUNDLE_CAPABILITIES
        )
        for manager_only in ("leases.sign", "reservations.extend", "leases.terminate"):
            assert manager_only in every_bundle_capability
            assert manager_only not in STAFF_DEFAULT_BUNDLE_CAPABILITIES
        # The bootstrapped Owner gets the Owner bundle; Manager and Staff accounts get theirs
        # when they are created (sub-slice L2).
        assert assignments(connection, owner) == [(owner_bundle, None, PROVENANCE)]
        assert assignments(connection, manager) == []
        assert assignments(connection, staff) == []
        assign(connection, manager, manager_bundle, property_id)
        assign(connection, staff, staff_bundle, property_id)
        every_property = {
            row[0] for row in connection.execute("SELECT id FROM app.properties").fetchall()
        }
        assert grants(connection, owner) == {
            (capability, property_id) for capability in every_bundle_capability
        } | {
            (capability, found)
            for capability in ("identity.manage_access", "settings.manage")
            for found in every_property
        }
        assert grants(connection, manager) == {
            (capability, property_id) for capability in every_bundle_capability
        }
        assert grants(connection, staff) == {
            (capability, property_id) for capability in STAFF_DEFAULT_BUNDLE_CAPABILITIES
        }
        reader = PostgresCapabilityGrantReader(cast(GrantConnection, connection))
        assert {grant.capability for grant in reader.grants_for(staff)} == set(
            STAFF_DEFAULT_BUNDLE_CAPABILITIES
        )
        connection.rollback()


def test_seeding_again_changes_nothing_and_the_bundles_stay_editable(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        property_id = the_property(connection)
        # Review round 1 note: the shared test database holds no defaults (this module runs
        # last and rolls back what it seeds), so a stale database fails here, not later.
        assert connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)
        owner = add_account(connection, "owner")
        staff = add_account(connection, "staff")
        seeded = seed(connection, property_id)
        before = {bundle: bundle_capabilities(connection, bundle) for bundle in seeded}
        # A later catalog row is not added to an existing bundle by itself (the Owner adds it).
        connection.execute(
            "INSERT INTO app.capabilities (capability_id,family,description,grant_path,"
            "provenance) VALUES ('loginslice.later','loginslice','A later capability',"
            "'bundle','login-slice-l1c-test')"
        )
        assert seed(connection, property_id) == seeded
        assert {bundle: bundle_capabilities(connection, bundle) for bundle in seeded} == before
        assert connection.execute(
            "SELECT count(*) FROM app.role_bundles WHERE property_id=%s AND provenance=%s",
            (property_id, PROVENANCE),
        ).fetchone() == (3,)
        assert assignments(connection, owner) == [(seeded[0], None, PROVENANCE)]
        # The defaults stay configurable data (SEC-021): a new version of the Staff bundle
        # changes what Staff get at the next read, and the default record keeps the bundle.
        staff_bundle = seeded[2]
        assign(connection, staff, staff_bundle, property_id)
        fewer = tuple(sorted(STAFF_DEFAULT_BUNDLE_CAPABILITIES - {"receipts.reprint"}))
        assert next_version(connection, staff_bundle, fewer, "Desk staff") == 2
        assert {capability for capability, _ in grants(connection, staff)} == set(fewer)
        assert connection.execute(
            f"SELECT staff_bundle_id FROM {TABLE} WHERE property_id=%s", (property_id,)
        ).fetchone() == (staff_bundle,)
        # Review round 1 (security): after the Owner removed its own Owner bundle assignment
        # and renamed the bundle, seeding again still changes nothing: no new bundle, no new
        # assignment, and the Owner keeps only what its account class gives.
        connection.execute(
            "INSERT INTO app.user_role_assignment_removals(assignment_id,reason,provenance) "
            "SELECT assignment_id,'Removed by the Owner','login-slice-l1c-test' "
            "FROM app.user_role_assignments WHERE actor_id=%s",
            (owner,),
        )
        owner_capabilities = tuple(sorted(before[seeded[0]]))
        assert next_version(connection, seeded[0], owner_capabilities, "Proprietor") == 2
        assert seed(connection, property_id) == seeded
        assert connection.execute(
            "SELECT count(*) FROM app.role_bundles WHERE property_id=%s AND provenance=%s",
            (property_id, PROVENANCE),
        ).fetchone() == (3,)
        assert assignments(connection, owner) == [(seeded[0], None, PROVENANCE)]
        assert {capability for capability, _ in grants(connection, owner)} == {
            "identity.manage_access",
            "settings.manage",
        }
        connection.rollback()


def test_seeding_is_refused_outside_read_committed_or_for_an_unknown_property(
    migrated_database_url: str,
) -> None:
    for isolation in (
        psycopg.IsolationLevel.REPEATABLE_READ,
        psycopg.IsolationLevel.SERIALIZABLE,
    ):
        with psycopg.connect(migrated_database_url) as other:
            other.isolation_level = isolation
            refused(
                other,
                psycopg.errors.ObjectNotInPrerequisiteState,
                SEED_QUERY,
                (the_property(other),),
                ONLY_READ_COMMITTED,
            )
            other.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        refused(
            connection,
            psycopg.errors.InvalidParameterValue,
            SEED_QUERY,
            (uuid.uuid4(),),
            "the Property does not exist",
        )
        property_id = the_property(connection)
        seed(connection, property_id)
        for statement in (
            f"UPDATE {TABLE} SET provenance='changed'",
            f"DELETE FROM {TABLE}",
            f"TRUNCATE {TABLE}",
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                statement,
                (),
                APPEND_ONLY,
            )
        connection.rollback()


def test_the_runtime_role_seeds_only_through_the_function(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as setup:
        property_id = the_property(setup)
    with psycopg.connect(runtime_database_url()) as runtime:
        assert len(set(seed(runtime, property_id))) == 3
        refused(
            runtime,
            psycopg.errors.InsufficientPrivilege,
            f"SELECT 1 FROM {TABLE}",
            (),
            "permission denied",
        )
        runtime.rollback()


def test_the_property_setup_seeds_the_default_bundles_in_its_transaction() -> None:
    """The Property setup command's path (`configure_postgres_property`, as the runtime
    identity) makes the Property and its default bundles in one transaction (a failed seed
    leaves no Property behind), and gives the bootstrapped Owner the Owner bundle; a second
    Property is refused and changes nothing."""
    with _temporary_migration_database("prm_default_bundles_setup") as temporary:
        assert _run_alembic("upgrade", REVISION).returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            owner = add_account(setup, "owner")
            setup.commit()
        # Review round 1: a seed that fails (here refused because the session runs at
        # SERIALIZABLE) rolls back the new Property too.
        parts = urlsplit(runtime_url)
        serializable = "options=-c%20default_transaction_isolation%3Dserializable"
        failing_url = urlunsplit(
            parts._replace(query=f"{parts.query}&{serializable}" if parts.query else serializable)
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match=ONLY_READ_COMMITTED):
            configure_postgres_property(failing_url, uuid.uuid4(), name="Failed", actor_id=owner)
        with psycopg.connect(temporary) as check:
            for table in (
                "app.properties",
                "app.role_bundles",
                TABLE,
                "app.user_role_assignments",
            ):
                assert check.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table
        property_id = uuid.uuid4()
        configure_postgres_property(runtime_url, property_id, name="Riverside", actor_id=owner)
        # Straight to the repository (the service refuses a second Property before it), so the
        # database refusal and its mapping are exercised.
        with pytest.raises(PropertyAlreadyConfiguredError):
            PostgresPropertyConfigurationRepository(runtime_url, owner).add(
                PropertyConfiguration(uuid.uuid4(), name="Second Property")
            )
        with psycopg.connect(temporary) as check:
            (seeded,) = check.execute(
                f"SELECT owner_bundle_id,manager_bundle_id,staff_bundle_id FROM {TABLE} "
                "WHERE property_id=%s",
                (property_id,),
            ).fetchall()
            assert check.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (1,)
            assert check.execute("SELECT name FROM app.role_bundles ORDER BY name").fetchall() == [
                ("Manager",),
                ("Owner",),
                ("Staff",),
            ]
            assert bundle_capabilities(check, seeded[2]) == set(STAFF_L1C_BUNDLE_CAPABILITIES)
            assert assignments(check, owner) == [(seeded[0], None, PROVENANCE)]


def test_two_seeds_of_one_property_at_the_same_time_make_the_bundles_once() -> None:
    """Both at READ COMMITTED: the second waits for the first's lock and only then checks, so
    it returns the first's committed bundles (a check before the lock would make the second
    fail on the bundle names instead)."""
    with _temporary_migration_database("prm_default_bundles_race") as temporary:
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(temporary) as setup:
            _, property_id = add_owner_and_property(setup)
            setup.commit()
        with (
            psycopg.connect(temporary) as first,
            psycopg.connect(temporary, options="-c lock_timeout=15s") as second,
        ):
            first_bundles = seed(first, property_id)
            results: list[tuple[uuid.UUID, ...]] = []
            errors: list[BaseException] = []

            def second_seed() -> None:
                try:
                    results.append(seed(second, property_id))
                except psycopg.Error as error:
                    errors.append(error)

            waiter = threading.Thread(target=second_seed)
            waiter.start()
            try:
                with psycopg.connect(temporary, autocommit=True) as watcher:
                    deadline = time.monotonic() + 5
                    while watcher.execute(
                        "SELECT wait_event_type,wait_event FROM pg_catalog.pg_stat_activity "
                        "WHERE pid=%s",
                        (second.info.backend_pid,),
                    ).fetchone() != ("Lock", "advisory"):
                        assert time.monotonic() < deadline, "the second seed never waited"
                        time.sleep(0.05)
                first.commit()
            finally:
                # Release the first's lock before waiting for the thread, so a failed wait
                # check ends the test instead of hanging it.
                first.rollback()
                waiter.join(timeout=20)
            assert not waiter.is_alive()
            assert errors == []
            assert results == [first_bundles]
            second.commit()
        with psycopg.connect(temporary) as check:
            assert check.execute("SELECT count(*) FROM app.role_bundles").fetchone() == (3,)
            assert check.execute("SELECT count(*) FROM app.user_role_assignments").fetchone() == (
                1,
            )


def test_the_default_bundles_migration_seeds_an_existing_property_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration seeds the Property that already exists and gives the Owner the Owner
    bundle. One relation (with its key), one definer function and two triggers are added;
    nothing else changes; the runtime role may only execute the seed function; forward-only."""
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

            present = connection.execute(f"SELECT to_regclass('{TABLE}')").fetchone()
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
                        "SELECT role,"
                        f"has_table_privilege(role,'{TABLE}','SELECT'),"
                        f"has_table_privilege(role,'{TABLE}',"
                        "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                        f"has_function_privilege(role,'{SEED}','EXECUTE') "
                        f"FROM unnest(ARRAY{list(roles)}) role"
                    )
                    if present != (None,)
                    else set()
                ),
            }

    with _temporary_migration_database("prm_default_bundles") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        with psycopg.connect(temporary) as setup:
            owner, property_id = add_owner_and_property(setup)
            manager = add_account(setup, "manager")
            setup.commit()
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)
        with psycopg.connect(temporary) as check:
            (seeded,) = check.execute(
                f"SELECT owner_bundle_id,manager_bundle_id,staff_bundle_id,provenance FROM {TABLE}"
            ).fetchall()
            every_bundle_capability = catalog_bundle_capabilities(check)
            assert seeded[3] == PROVENANCE
            assert bundle_capabilities(check, seeded[0]) == every_bundle_capability
            assert bundle_capabilities(check, seeded[1]) == every_bundle_capability
            assert bundle_capabilities(check, seeded[2]) == set(STAFF_L1C_BUNDLE_CAPABILITIES)
            assert assignments(check, owner) == [(seeded[0], None, PROVENANCE)]
            assert assignments(check, manager) == []
            assert {capability for capability, _ in grants(check, owner)} == (
                every_bundle_capability | {"identity.manage_access", "settings.manage"}
            )
            assert grants(check, manager) == set()
            assert {row[0] for row in check.execute("SELECT id FROM app.properties")} == {
                property_id
            }

    for key in ("functions", "triggers", "relations", "constraints", "columns"):
        assert before[key] <= after[key]
    added = {item.split(":")[0]: item for item in after["functions"] - before["functions"]}
    assert set(added) == {SEED}
    assert added[SEED].endswith(":v:True:{search_path=pg_catalog}")
    assert {item.split(":")[1] for item in after["triggers"] - before["triggers"]} == {
        "default_role_bundles_are_append_only",
        "default_role_bundles_reject_truncate",
    }
    assert {item.split(":")[0] for item in after["relations"] - before["relations"]} == {
        TABLE,
        "app.default_role_bundles_pkey",
    }
    for key in ("constraints", "columns"):
        assert {item.split(":")[0] for item in after[key] - before[key]} == {TABLE}
    # The backup role reads every table through pg_read_all_data (scripts/postgres-init.sh).
    assert after["privileges"] == {
        f"{role}:{role == 'prm_backup'}:False:{role == 'prm_runtime'}" for role in roles
    }
