"""The account class of a local human account (login slice sub-slice L1a).

DL-056, DL-058, DL-059, DL-074 answer 2, DL-081 (owner answer (a) to Q-2026-10-21-152): an
account has one class, `owner`, `manager` or `staff`, kept in the separate append-only relation
`app.user_account_classes`; exactly one Owner account (the bootstrapped one); an Owner or Manager
account requires MFA; a class, once given, never changes or goes away. An account without a class
is never found for sign-in or recovery (fail closed). Rows written on the shared test database are
rolled back, except the committed Manager, Staff, disabled and unclassified accounts of the
resolver and sign-in tests (no Owner is ever committed there).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.account_recovery import (
    AccountRecoveryConnection,
    PostgresRecoveryAccountResolver,
)
from property_rental.administrative_recovery import RecoveryAccount
from property_rental.local_authentication import (
    ConnectionBoundary,
    PostgresLocalAccountRepository,
)
from test_migrations import (
    BOOTSTRAP_URL_ENV,
    RUNTIME_URL_ENV,
    _execute_atomic_owner_bootstrap,
    _required_url,
    _run_alembic,
    _temporary_migration_database,
    _url_with_database,
)
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

REVISION = "20270118_175"
PREVIOUS = "20270117_174"
BOOTSTRAP = (
    "app.establish_initial_owner_bootstrap(uuid,uuid,uuid,uuid,text,text,text,text,text,jsonb,"
    "bytea,bytea,text,uuid[],text[],text,jsonb)"
)
NEW_FUNCTIONS = {
    "app.reject_user_account_class_change()",
    "app.require_user_account_class_mfa()",
    "app.reject_privileged_account_optional_mfa()",
}
NEW_RELATIONS = {
    "app.user_account_classes",
    "app.user_account_classes_pkey",
    "app.user_account_classes_single_owner",
}
ROLES = ("prm_runtime", "prm_financial", "prm_bootstrap")
ADD_ACCOUNT = (
    "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,audit_name,"
    "lifecycle_state,mfa_policy_class,provenance) "
    "VALUES (%s,%s,'Class Test','class-test',%s,%s,'login-slice-l1a-test')"
)
ADD_CLASS = (
    "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
    "VALUES (%s,%s,'login-slice-l1a-test')"
)
ADD_CREDENTIAL = (
    "INSERT INTO app.password_credentials(actor_id,verifier_encoding,algorithm,"
    "work_factor_metadata,provenance) VALUES (%s,'$adaptive$params$saltandhash','adaptive',"
    "'{\"cost\": 1}'::jsonb,'authorized-credential-change')"
)
CLASS_OF = "SELECT account_class FROM app.user_account_classes WHERE actor_id=%s"
SET_MFA = "UPDATE app.user_accounts SET mfa_policy_class=%s WHERE actor_id=%s"
REQUIRES_MFA = "an Owner or Manager account requires MFA"
IMMUTABLE = "user account class is immutable"


def add_account(
    connection: psycopg.Connection[Any],
    mfa: str,
    account_class: str | None = None,
    lifecycle: str = "active",
) -> uuid.UUID:
    actor_id = uuid.uuid4()
    connection.execute(ADD_ACCOUNT, (actor_id, username(actor_id), lifecycle, mfa))
    if account_class is not None:
        connection.execute(ADD_CLASS, (actor_id, account_class))
    return actor_id


def username(actor_id: uuid.UUID) -> str:
    return f"class-{actor_id.hex}"


def resolver_for(connection: psycopg.Connection[Any]) -> PostgresRecoveryAccountResolver:
    return PostgresRecoveryAccountResolver(cast(AccountRecoveryConnection, connection))


def repository_for(connection: psycopg.Connection[Any]) -> PostgresLocalAccountRepository:
    return PostgresLocalAccountRepository(cast(ConnectionBoundary, connection))


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


def test_an_account_class_is_owner_manager_staff_or_not_given(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
            "WHERE table_schema='app' AND table_name='user_account_classes' "
            "ORDER BY ordinal_position"
        ).fetchall() == [
            ("actor_id", "uuid", "NO"),
            ("account_class", "text", "NO"),
            ("classified_at", "timestamp with time zone", "NO"),
            ("provenance", "text", "NO"),
        ]
        for account_class in ("staff", "manager"):
            actor_id = add_account(connection, "required", account_class)
            assert connection.execute(CLASS_OF, (actor_id,)).fetchone() == (account_class,)
            refused(connection, psycopg.errors.UniqueViolation, ADD_CLASS, (actor_id, "staff"))
        unclassified = add_account(connection, "required")
        assert connection.execute(CLASS_OF, (unclassified,)).fetchone() is None
        for wrong in ("admin", "Owner", ""):
            refused(connection, psycopg.errors.CheckViolation, ADD_CLASS, (unclassified, wrong))
        refused(
            connection,
            psycopg.errors.CheckViolation,
            "INSERT INTO app.user_account_classes(actor_id,account_class,provenance) "
            "VALUES (%s,'staff','  ')",
            (unclassified,),
        )
        refused(connection, psycopg.errors.ForeignKeyViolation, ADD_CLASS, (uuid.uuid4(), "staff"))
        connection.rollback()


def test_owner_and_manager_accounts_require_mfa(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        optional = add_account(connection, "optional")
        for account_class in ("owner", "manager"):
            refused(
                connection,
                psycopg.errors.CheckViolation,
                ADD_CLASS,
                (optional, account_class),
                match=REQUIRES_MFA,
            )
        for account_class in ("owner", "manager"):
            privileged = add_account(connection, "required", account_class)
            refused(
                connection,
                psycopg.errors.CheckViolation,
                SET_MFA,
                ("optional", privileged),
                match=REQUIRES_MFA,
            )
            connection.execute(
                "UPDATE app.user_accounts SET display_name='Renamed Account' WHERE actor_id=%s",
                (privileged,),
            )
            connection.execute(SET_MFA, ("required", privileged))
        staff = add_account(connection, "optional", "staff")
        for actor_id in (staff, optional):
            for mfa in ("required", "optional"):
                connection.execute(SET_MFA, (mfa, actor_id))
        connection.rollback()


def test_a_class_and_an_mfa_change_at_the_same_time_wait_for_each_other(
    migrated_database_url: str,
) -> None:
    """Review round 1: at READ COMMITTED a class insert waits for an uncommitted MFA change of
    the same account and then sees it, and an MFA change waits for an uncommitted Manager class
    and then sees it; both orders end in the MFA refusal. Commits one Manager on the shared
    database (no Owner)."""
    with psycopg.connect(migrated_database_url, autocommit=True) as setup:
        first = add_account(setup, "required")
        second = add_account(setup, "required")
    with (
        psycopg.connect(migrated_database_url) as changer,
        psycopg.connect(migrated_database_url) as classer,
    ):
        changer.execute(SET_MFA, ("optional", first))
        classer.execute("SET lock_timeout='200ms'")
        refused(classer, psycopg.errors.LockNotAvailable, ADD_CLASS, (first, "manager"))
        changer.commit()
        refused(classer, psycopg.errors.CheckViolation, ADD_CLASS, (first, "manager"), REQUIRES_MFA)
        classer.rollback()

        classer.execute(ADD_CLASS, (second, "manager"))
        changer.execute("SET lock_timeout='200ms'")
        refused(changer, psycopg.errors.LockNotAvailable, SET_MFA, ("optional", second))
        classer.commit()
        refused(changer, psycopg.errors.CheckViolation, SET_MFA, ("optional", second), REQUIRES_MFA)
        changer.rollback()
        assert classer.execute(CLASS_OF, (first,)).fetchone() is None
        assert classer.execute(CLASS_OF, (second,)).fetchone() == ("manager",)
        classer.rollback()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_an_mfa_policy_is_lowered_only_at_read_committed(
    migrated_database_url: str, isolation: str
) -> None:
    """Security review round 1: a transaction whose snapshot is older than a Manager class given
    meanwhile cannot set that account's MFA to optional; no MFA policy is lowered outside READ
    COMMITTED, while raising one still works there. Commits one Manager on the shared database
    (no Owner)."""
    with psycopg.connect(migrated_database_url, autocommit=True) as setup:
        manager = add_account(setup, "required")
        staff = add_account(setup, "optional", "staff")
        unclassified = add_account(setup, "required")
    with (
        psycopg.connect(migrated_database_url) as older,
        psycopg.connect(migrated_database_url, autocommit=True) as classer,
    ):
        older.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        assert older.execute(CLASS_OF, (manager,)).fetchone() is None
        classer.execute(ADD_CLASS, (manager, "manager"))
        for actor_id in (manager, unclassified):
            refused(
                older,
                psycopg.errors.ObjectNotInPrerequisiteState,
                SET_MFA,
                ("optional", actor_id),
                "an MFA policy can be lowered only at READ COMMITTED",
            )
        older.execute(SET_MFA, ("required", staff))
        older.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(CLASS_OF, (manager,)).fetchone() == ("manager",)
        refused(
            connection, psycopg.errors.CheckViolation, SET_MFA, ("optional", manager), REQUIRES_MFA
        )
        connection.execute(SET_MFA, ("optional", unclassified))
        connection.rollback()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_a_class_given_from_a_snapshot_older_than_an_mfa_change_fails(
    migrated_database_url: str, isolation: str
) -> None:
    """Review round 2 note: a Manager class given from a snapshot taken before the account's MFA
    was lowered fails with a serialization failure, so it never sees the old `required`."""
    with psycopg.connect(migrated_database_url, autocommit=True) as setup:
        account = add_account(setup, "required")
    with (
        psycopg.connect(migrated_database_url) as classer,
        psycopg.connect(migrated_database_url, autocommit=True) as changer,
    ):
        classer.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        assert classer.execute(CLASS_OF, (account,)).fetchone() is None
        changer.execute(SET_MFA, ("optional", account))
        refused(classer, psycopg.errors.SerializationFailure, ADD_CLASS, (account, "manager"))
        classer.rollback()
        assert classer.execute(CLASS_OF, (account,)).fetchone() is None
        classer.rollback()


def test_at_most_one_owner_account_exists(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        add_account(connection, "required", "owner")
        second = add_account(connection, "required")
        refused(connection, psycopg.errors.UniqueViolation, ADD_CLASS, (second, "owner"))
        add_account(connection, "required", "manager")
        add_account(connection, "required", "manager")
        connection.rollback()


def test_a_class_once_given_never_changes_or_goes_away(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        staff = add_account(connection, "required", "staff")
        manager = add_account(connection, "required", "manager")
        change = "UPDATE app.user_account_classes SET {} WHERE actor_id=%s"
        for query, parameters in (
            (change.format("account_class='manager'"), (staff,)),
            (change.format("account_class='owner'"), (manager,)),
            (change.format("provenance='changed'"), (staff,)),
            ("DELETE FROM app.user_account_classes WHERE actor_id=%s", (manager,)),
            ("TRUNCATE app.user_account_classes", ()),
        ):
            refused(
                connection,
                psycopg.errors.IntegrityConstraintViolation,
                query,
                parameters,
                match=IMMUTABLE,
            )
        connection.execute(
            "UPDATE app.user_accounts SET display_name='Renamed Staff',lifecycle_state='disabled' "
            "WHERE actor_id=%s",
            (staff,),
        )
        assert connection.execute(CLASS_OF, (staff,)).fetchone() == ("staff",)
        connection.rollback()


def test_the_bootstrapped_owner_has_class_owner_and_no_second_owner_can_be_added() -> None:
    with _temporary_migration_database("prm_account_class_bootstrap") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            owner = _execute_atomic_owner_bootstrap(bootstrap_connection)
            bootstrap_connection.commit()
        with psycopg.connect(migration_url) as connection:
            assert connection.execute(
                "SELECT classification.account_class,classification.provenance,"
                "account.mfa_policy_class,account.lifecycle_state "
                "FROM app.user_accounts account "
                "JOIN app.user_account_classes classification USING (actor_id)"
            ).fetchall() == [
                ("owner", "protected-initial-owner-bootstrap", "required", "active"),
            ]
            second = add_account(connection, "required")
            refused(connection, psycopg.errors.UniqueViolation, ADD_CLASS, (second, "owner"))
            add_account(connection, "required", "manager")
            connection.rollback()
        runtime_url = _url_with_database(_required_url(RUNTIME_URL_ENV), database)
        with psycopg.connect(runtime_url) as runtime:
            assert resolver_for(runtime).resolve(owner) == RecoveryAccount(
                account_id=str(owner), account_class="owner"
            )
            found = repository_for(runtime).find_by_username("initial-owner")
            assert found is not None and found.actor_id == str(owner)


def test_the_migration_classes_only_the_bootstrapped_owner() -> None:
    with _temporary_migration_database("prm_account_class_backfill") as migration_url:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            owner = _execute_atomic_owner_bootstrap(bootstrap_connection)
            bootstrap_connection.commit()
        older = uuid.uuid4()
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                "INSERT INTO app.user_accounts(actor_id,normalized_username,display_name,"
                "audit_name,lifecycle_state,mfa_policy_class,provenance) VALUES "
                "(%s,'older-staff','Older Staff','older-staff','active','optional',"
                "'authorized-account-creation')",
                (older,),
            )
            connection.commit()
            accounts_before = connection.execute(
                "SELECT * FROM app.user_accounts ORDER BY actor_id"
            ).fetchall()
        assert _run_alembic("upgrade", REVISION).returncode == 0
        with psycopg.connect(migration_url) as connection:
            assert (
                connection.execute("SELECT * FROM app.user_accounts ORDER BY actor_id").fetchall()
                == accounts_before
            )
            assert connection.execute(
                "SELECT actor_id,account_class,provenance FROM app.user_account_classes"
            ).fetchall() == [(owner, "owner", "login-slice-account-class-backfill")]
            # A bootstrap closed before the upgrade stays closed (review round 1, SEC-074).
            assert connection.execute(
                "SELECT has_function_privilege('prm_bootstrap',%s,'EXECUTE')", (BOOTSTRAP,)
            ).fetchone() == (False,)
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            assert bootstrap_connection.execute(
                "SELECT app.begin_initial_owner_bootstrap_attempt(%s,%s)",
                (uuid.uuid4(), uuid.uuid4()),
            ).fetchone() == (False,)
            bootstrap_connection.commit()
        runtime_url = _url_with_database(_required_url(RUNTIME_URL_ENV), database)
        with psycopg.connect(runtime_url) as runtime:
            assert resolver_for(runtime).resolve(owner) == RecoveryAccount(str(owner), "owner")
            assert resolver_for(runtime).resolve(older) is None


def test_the_recovery_resolver_reads_only_the_stored_class_of_an_active_account(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        manager = add_account(connection, "required", "manager")
        staff = add_account(connection, "optional", "staff")
        disabled = add_account(connection, "optional", "staff", lifecycle="disabled")
        unclassified = add_account(connection, "required")
        connection.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        resolver = resolver_for(runtime)
        assert resolver.resolve(manager) == RecoveryAccount(str(manager), "manager")
        assert resolver.resolve(staff) == RecoveryAccount(str(staff), "staff")
        for missing in (disabled, unclassified, uuid.uuid4()):
            assert resolver.resolve(missing) is None


def test_an_account_without_a_class_cannot_be_found_for_sign_in(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        staff = add_account(connection, "optional", "staff")
        unclassified = add_account(connection, "optional")
        for actor_id in (staff, unclassified):
            connection.execute(ADD_CREDENTIAL, (actor_id,))
        connection.commit()
    with psycopg.connect(runtime_database_url()) as runtime:
        repository = repository_for(runtime)
        found = repository.find_by_username(username(staff))
        assert found is not None and found.actor_id == str(staff)
        assert repository.find_by_username(username(unclassified)) is None


def test_the_account_class_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the bootstrap function body changes, by the one class insert; three trigger
    functions (no EXECUTE for the application roles) and four triggers are added; the new
    relation, its two indexes, constraints and columns are the only other structure changes; the
    runtime role gets SELECT on the new relation only; no existing privilege changes;
    forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> dict[str, Any]:
        with psycopg.connect(database) as connection:

            def rows(query: str) -> set[str]:
                return {
                    ":".join(str(item) for item in found)
                    for found in connection.execute(query).fetchall()
                }

            return {
                "functions": {
                    str(found[0]): tuple(found[1:])
                    for found in connection.execute(
                        "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                        "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                        "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                    ).fetchall()
                },
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
                "indexes": rows(
                    "SELECT indexrelid::regclass::text,pg_catalog.pg_get_indexdef(indexrelid) "
                    "FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app'"
                ),
            }

    def privileges(database: str) -> list[tuple[Any, ...]]:
        with psycopg.connect(database) as connection:
            return connection.execute(
                "SELECT role,has_table_privilege(role,'app.user_account_classes','SELECT'),"
                "has_table_privilege(role,'app.user_account_classes',"
                "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                "bool_or(has_function_privilege(role,function,'EXECUTE')) "
                "FROM unnest(%s::text[]) role, unnest(%s::text[]) function "
                "GROUP BY role ORDER BY role",
                (list(ROLES), sorted(NEW_FUNCTIONS)),
            ).fetchall()

    with _temporary_migration_database("prm_account_class_catalog") as temporary:
        assert _run_alembic("upgrade", PREVIOUS).returncode == 0
        before = catalog(temporary)
        assert _run_alembic("upgrade", REVISION).returncode == 0
        after = catalog(temporary)
        granted = privileges(temporary)

    assert set(after["functions"]) == set(before["functions"]) | NEW_FUNCTIONS
    assert {
        name
        for name in before["functions"]
        if after["functions"][name] != before["functions"][name]
    } == {BOOTSTRAP}
    assert after["functions"][BOOTSTRAP][1:] == before["functions"][BOOTSTRAP][1:]
    class_insert = (
        "            INSERT INTO app.user_account_classes (\n"
        "                actor_id, account_class, provenance\n"
        "            ) VALUES (\n"
        "                p_actor_id, 'owner', 'protected-initial-owner-bootstrap'\n"
        "            );\n"
    )
    bootstrap_after = str(after["functions"][BOOTSTRAP][0])
    assert bootstrap_after.count(class_insert) == 1
    assert bootstrap_after.replace(class_insert, "") == str(before["functions"][BOOTSTRAP][0])
    for name in NEW_FUNCTIONS:
        definition, _acl, _owner, definer, settings = after["functions"][name]
        assert definer is False and settings == "{search_path=pg_catalog}"
        assert "SECURITY DEFINER" not in str(definition)
    assert granted == [
        ("prm_bootstrap", False, False, False),
        ("prm_financial", False, False, False),
        ("prm_runtime", True, False, False),
    ]
    assert before["triggers"] <= after["triggers"]
    assert {item.split(":")[1] for item in after["triggers"] - before["triggers"]} == {
        "user_account_classes_are_immutable",
        "user_account_classes_reject_truncate",
        "user_account_classes_require_mfa",
        "user_accounts_privileged_class_requires_mfa",
    }
    (mfa_trigger,) = {
        item
        for item in after["triggers"]
        if item.startswith("app.user_accounts:user_accounts_privileged_class_requires_mfa:")
    }
    assert "AFTER UPDATE ON app.user_accounts FOR EACH ROW" in mfa_trigger
    assert "WHEN ((new.mfa_policy_class IS DISTINCT FROM 'required'::text))" in mfa_trigger
    assert mfa_trigger.endswith("EXECUTE FUNCTION app.reject_privileged_account_optional_mfa()")
    for key in ("relations", "constraints", "columns", "indexes"):
        assert before[key] <= after[key]
        assert {item.split(":")[0] for item in after[key] - before[key]} <= NEW_RELATIONS
    assert {item.split(":")[0] for item in after["relations"] - before["relations"]} == (
        NEW_RELATIONS
    )
    assert {item.split(":")[1] for item in after["columns"] - before["columns"]} == {
        "actor_id",
        "account_class",
        "classified_at",
        "provenance",
    }
    assert (
        "app.user_account_classes_single_owner:CREATE UNIQUE INDEX "
        "user_account_classes_single_owner ON app.user_account_classes USING btree "
        "(account_class) WHERE (account_class = 'owner'::text)"
    ) in after["indexes"]
