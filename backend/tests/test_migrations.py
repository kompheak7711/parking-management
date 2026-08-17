"""Real PostgreSQL migration tests for the bounded Phase 1C baseline."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql

from property_rental.app import create_app
from property_rental.settings import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_URL_ENV = "MIGRATION_DATABASE_URL"
RUNTIME_URL_ENV = "APP_DATABASE_URL"
ADMIN_URL_ENV = "TEST_ADMIN_DATABASE_URL"
BACKUP_URL_ENV = "BACKUP_DATABASE_URL"
RESTORE_URL_ENV = "RESTORE_DATABASE_URL"
HUMAN_ADMIN_URL_ENV = "HUMAN_ADMIN_DATABASE_URL"
REQUIRE_DATABASE_TESTS_ENV = "REQUIRE_DATABASE_TESTS"
LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        if os.environ.get(REQUIRE_DATABASE_TESTS_ENV) == "1":
            pytest.fail(f"{name} is required for the dedicated real PostgreSQL test gate")
        pytest.skip(f"{name} is required for real PostgreSQL migration tests")
    return value


def _run_alembic(*arguments: str, cwd: Path = BACKEND_ROOT) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment[MIGRATION_URL_ENV] = _required_url(MIGRATION_URL_ENV)
    return subprocess.run(
        ["alembic", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _url_with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _validate_local_test_urls(admin_url: str, migration_url: str, runtime_url: str) -> None:
    """Refuse non-local, misidentified, or credential-reused database test targets."""
    expected_users = {
        ADMIN_URL_ENV: "prm_admin",
        MIGRATION_URL_ENV: "prm_migrator",
        RUNTIME_URL_ENV: "prm_runtime",
        BACKUP_URL_ENV: "prm_backup",
        RESTORE_URL_ENV: "prm_restore",
        HUMAN_ADMIN_URL_ENV: "prm_human_admin",
    }
    parsed_urls = {
        ADMIN_URL_ENV: urlsplit(admin_url),
        MIGRATION_URL_ENV: urlsplit(migration_url),
        RUNTIME_URL_ENV: urlsplit(runtime_url),
        BACKUP_URL_ENV: urlsplit(_required_url(BACKUP_URL_ENV)),
        RESTORE_URL_ENV: urlsplit(_required_url(RESTORE_URL_ENV)),
        HUMAN_ADMIN_URL_ENV: urlsplit(_required_url(HUMAN_ADMIN_URL_ENV)),
    }
    for name, parsed in parsed_urls.items():
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
            pytest.fail(f"{name} must use PostgreSQL")
        if parsed.hostname not in LOCAL_DATABASE_HOSTS:
            pytest.fail(f"{name} must target a loopback PostgreSQL host")
        if parsed.username != expected_users[name]:
            pytest.fail(f"{name} must use the expected isolated development identity")
        if parsed.path != "/prm":
            pytest.fail(f"{name} must target the isolated development bootstrap database")
        if parsed.password is None:
            pytest.fail(f"{name} must include a protected test password")

    passwords = {parsed.password for parsed in parsed_urls.values()}
    if len(passwords) != len(parsed_urls):
        pytest.fail("PostgreSQL test identity passwords must be distinct")


@pytest.fixture(scope="session", autouse=True)
def empty_application_database() -> Iterator[None]:
    database = f"prm_test_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    original_runtime_url = _required_url(RUNTIME_URL_ENV)
    original_backup_url = _required_url(BACKUP_URL_ENV)
    original_restore_url = _required_url(RESTORE_URL_ENV)
    original_human_admin_url = _required_url(HUMAN_ADMIN_URL_ENV)
    _validate_local_test_urls(admin_url, original_migration_url, original_runtime_url)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )
    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    os.environ[RUNTIME_URL_ENV] = _url_with_database(original_runtime_url, database)
    os.environ[BACKUP_URL_ENV] = _url_with_database(original_backup_url, database)
    os.environ[RESTORE_URL_ENV] = _url_with_database(original_restore_url, database)
    os.environ[HUMAN_ADMIN_URL_ENV] = _url_with_database(original_human_admin_url, database)
    yield
    os.environ[MIGRATION_URL_ENV] = original_migration_url
    os.environ[RUNTIME_URL_ENV] = original_runtime_url
    os.environ[BACKUP_URL_ENV] = original_backup_url
    os.environ[RESTORE_URL_ENV] = original_restore_url
    os.environ[HUMAN_ADMIN_URL_ENV] = original_human_admin_url


def test_upgrade_from_empty_database_reaches_reviewed_head() -> None:
    result = _run_alembic("upgrade", "head")

    assert result.returncode == 0, result.stderr
    config = Config(BACKEND_ROOT / "alembic.ini")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (expected_head,)
            cursor.execute("SELECT baseline_key FROM app.schema_baseline")
            assert cursor.fetchone() == ("phase-1c",)


def test_user_accounts_storage_has_bounded_identity_and_policy_columns() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'user_accounts'
                ORDER BY ordinal_position
                """
            )

            assert cursor.fetchall() == [
                ("actor_id", "uuid", "NO"),
                ("normalized_username", "text", "NO"),
                ("display_name", "text", "NO"),
                ("audit_name", "text", "NO"),
                ("lifecycle_state", "text", "NO"),
                ("mfa_policy_class", "text", "NO"),
                ("created_at", "timestamp with time zone", "NO"),
                ("updated_at", "timestamp with time zone", "NO"),
                ("created_by_actor_id", "uuid", "YES"),
                ("provenance", "text", "NO"),
            ]


def test_user_accounts_reject_duplicate_normalized_username_transactionally() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    first_actor_id = uuid.uuid4()
    second_actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, 'operator', 'Operator One', 'operator-one',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (first_actor_id,),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, 'operator', 'Operator Two', 'operator-two',
                              'active', 'optional', 'authorized-account-creation')
                    """,
                    (second_actor_id,),
                )


def test_user_accounts_reject_username_that_is_not_normalized() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, ' Operator ', 'Operator', 'operator',
                              'active', 'optional', 'authorized-account-creation')
                    """,
                    (uuid.uuid4(),),
                )


def test_user_accounts_reject_actor_identity_changes() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, 'immutable-actor', 'Immutable Actor', 'immutable-actor',
                          'active', 'required', 'authorized-account-creation')
                """,
                (actor_id,),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.user_accounts SET actor_id = %s WHERE actor_id = %s",
                    (uuid.uuid4(), actor_id),
                )


def test_user_accounts_reject_unknown_lifecycle_state() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, 'unknown-lifecycle', 'Unknown Lifecycle',
                              'unknown-lifecycle', 'deleted', 'optional',
                              'authorized-account-creation')
                    """,
                    (uuid.uuid4(),),
                )


def test_user_accounts_reject_unknown_mfa_policy_class() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, 'unknown-mfa-policy', 'Unknown MFA Policy',
                              'unknown-mfa-policy', 'active', 'owner',
                              'authorized-account-creation')
                    """,
                    (uuid.uuid4(),),
                )


@pytest.mark.parametrize("blank_column", ["display_name", "audit_name", "provenance"])
def test_user_accounts_reject_blank_identity_or_provenance(blank_column: str) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    values = {
        "display_name": "Display Name",
        "audit_name": "audit-name",
        "provenance": "authorized-account-creation",
    }
    values[blank_column] = "   "
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, %s, %s, 'active', 'optional', %s)
                    """,
                    (
                        uuid.uuid4(),
                        f"blank-{blank_column.replace('_', '-')}",
                        values["display_name"],
                        values["audit_name"],
                        values["provenance"],
                    ),
                )


def test_runtime_identity_is_distinct_and_cannot_change_schema() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT baseline_key FROM app.schema_baseline")
            assert cursor.fetchone() == ("phase-1c",)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE app.forbidden_runtime_ddl (id integer)")


def test_operational_database_identities_have_separate_least_privilege() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication
                FROM pg_roles
                WHERE rolname IN (
                    'prm_runtime', 'prm_migrator', 'prm_backup',
                    'prm_restore', 'prm_human_admin'
                )
                ORDER BY rolname
                """
            )
            rows = cursor.fetchall()
            assert [row[0] for row in rows] == [
                "prm_backup",
                "prm_human_admin",
                "prm_migrator",
                "prm_restore",
                "prm_runtime",
            ]
            assert all(row[1:] == (False, False, False, False) for row in rows)
            cursor.execute(
                """
                SELECT
                    pg_has_role('prm_backup', 'pg_read_all_data', 'member'),
                    pg_has_role('prm_human_admin', 'pg_monitor', 'member'),
                    pg_has_role('prm_restore', 'pg_read_all_data', 'member'),
                    pg_has_role('prm_human_admin', 'pg_write_all_data', 'member')
                """
            )
            assert cursor.fetchone() == (True, True, False, False)

    with psycopg.connect(_required_url(BACKUP_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT baseline_key FROM app.schema_baseline")
            assert cursor.fetchone() == ("phase-1c",)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("INSERT INTO app.schema_baseline VALUES ('forbidden-backup-write')")

    for url_environment in (RESTORE_URL_ENV, HUMAN_ADMIN_URL_ENV):
        with psycopg.connect(_required_url(url_environment)) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT actor_id FROM app.user_accounts")


def test_runtime_has_only_bounded_user_account_data_privileges() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT actor_id FROM app.user_accounts")
            assert all(isinstance(row[0], uuid.UUID) for row in cursor.fetchall())

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, 'runtime-operator', 'Runtime Operator',
                              'runtime-operator', 'active', 'optional',
                              'authorized-account-creation')
                    """,
                    (uuid.uuid4(),),
                )

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    has_table_privilege('prm_runtime', 'app.user_accounts', 'SELECT'),
                    has_table_privilege('prm_runtime', 'app.user_accounts', 'INSERT'),
                    has_table_privilege('prm_runtime', 'app.user_accounts', 'UPDATE'),
                    has_table_privilege('prm_runtime', 'app.user_accounts', 'DELETE'),
                    has_table_privilege('prm_runtime', 'app.user_accounts', 'TRUNCATE'),
                    bool_or(has_column_privilege(
                        'prm_runtime', 'app.user_accounts', column_name, 'INSERT'
                    )),
                    bool_or(has_column_privilege(
                        'prm_runtime', 'app.user_accounts', column_name, 'UPDATE'
                    ))
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'user_accounts'
                """
            )
            assert cursor.fetchone() == (True, False, False, False, False, False, False)


def test_user_account_updates_advance_the_managed_timestamp() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, 'timestamped-actor', 'Timestamped Actor',
                          'timestamped-actor', 'active', 'optional',
                          'authorized-account-creation')
                RETURNING created_at, updated_at
                """,
                (actor_id,),
            )
            inserted_timestamps = cursor.fetchone()
            assert inserted_timestamps is not None
            created_at, initial_updated_at = inserted_timestamps
            cursor.execute("SELECT pg_sleep(0.01)")
            cursor.execute(
                """
                UPDATE app.user_accounts
                SET display_name = 'Updated Timestamped Actor'
                WHERE actor_id = %s
                RETURNING updated_at
                """,
                (actor_id,),
            )
            updated_timestamp = cursor.fetchone()
            assert updated_timestamp is not None
            updated_at = updated_timestamp[0]

    assert initial_updated_at == created_at
    assert updated_at > initial_updated_at


def test_password_credentials_store_only_bounded_verifier_material() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'password_credentials'
                ORDER BY ordinal_position
                """
            )

            assert cursor.fetchall() == [
                ("actor_id", "uuid", "NO"),
                ("verifier_encoding", "text", "NO"),
                ("algorithm", "text", "NO"),
                ("work_factor_metadata", "jsonb", "NO"),
                ("created_at", "timestamp with time zone", "NO"),
                ("changed_at", "timestamp with time zone", "NO"),
                ("changed_by_actor_id", "uuid", "YES"),
                ("provenance", "text", "NO"),
            ]


@pytest.mark.parametrize(
    ("verifier_encoding", "algorithm", "work_factor_metadata", "provenance"),
    [
        ("plaintext-password", "adaptive", '{"cost": 1}', "credential-change-1"),
        ("$adaptive$params$saltandhash", "   ", '{"cost": 1}', "credential-change-1"),
        ("$different$params$saltandhash", "adaptive", '{"cost": 1}', "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", "{}", "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", "[]", "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", '{"cost": 0}', "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", '{"cost": 1.5}', "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", '{"note": null}', "credential-change-1"),
        ("$adaptive$params$saltandhash", "adaptive", '{"cost": 1}', "   "),
    ],
)
def test_password_credentials_reject_incomplete_verifier_records(
    verifier_encoding: str,
    algorithm: str,
    work_factor_metadata: str,
    provenance: str,
) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Credential Constraint', 'credential-constraint',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"credential-{uuid.uuid4().hex}"),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.password_credentials (
                        actor_id, verifier_encoding, algorithm,
                        work_factor_metadata, provenance
                    ) VALUES (%s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        actor_id,
                        verifier_encoding,
                        algorithm,
                        work_factor_metadata,
                        provenance,
                    ),
                )


def test_password_credentials_require_an_existing_account() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.password_credentials (
                        actor_id, verifier_encoding, algorithm,
                        work_factor_metadata, provenance
                    ) VALUES (%s, '$adaptive$params$saltandhash', 'adaptive',
                              '{"cost": 1}'::jsonb,
                              'authorized-credential-change')
                    """,
                    (uuid.uuid4(),),
                )


def test_runtime_has_only_bounded_password_credential_privileges() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT actor_id, verifier_encoding, algorithm, work_factor_metadata
                FROM app.password_credentials
                """
            )
            assert cursor.fetchall() == []

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute("SELECT provenance FROM app.password_credentials")

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE app.password_credentials
                    SET verifier_encoding = '$adaptive$params$forbiddenchange'
                    """
                )

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'SELECT'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'INSERT'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'UPDATE'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'DELETE'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'TRUNCATE'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'REFERENCES'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.password_credentials', 'TRIGGER'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'verifier_encoding', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'actor_id', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'algorithm', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'work_factor_metadata', 'SELECT'
                    ),
                    bool_or(has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        column_name, 'INSERT'
                    )),
                    bool_or(has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        column_name, 'UPDATE'
                    )),
                    bool_or(has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        column_name, 'SELECT'
                    )) FILTER (WHERE column_name IN (
                        'created_at', 'changed_at', 'changed_by_actor_id', 'provenance'
                    )),
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'provenance', 'SELECT'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.valid_password_work_factor_metadata(jsonb)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.protect_password_credential_lifecycle()',
                        'EXECUTE'
                    )
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'password_credentials'
                """
            )
            assert cursor.fetchone() == (
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
                True,
                True,
                True,
                False,
                False,
                False,
                False,
                False,
                False,
            )


def test_password_credential_change_advances_timestamp_with_new_provenance() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Credential Lifecycle', 'credential-lifecycle',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"credential-lifecycle-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.password_credentials (
                    actor_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, '$adaptive$params$oldsaltandhash', 'adaptive',
                          '{"cost": 1}'::jsonb, 'credential-change-1')
                RETURNING created_at, changed_at
                """,
                (actor_id,),
            )
            inserted = cursor.fetchone()
            assert inserted is not None
            created_at, initial_changed_at = inserted
            cursor.execute("SELECT pg_sleep(0.01)")
            cursor.execute(
                """
                UPDATE app.password_credentials
                SET verifier_encoding = '$adaptive$params$newsaltandhash',
                    changed_by_actor_id = %s,
                    provenance = 'credential-change-2'
                WHERE actor_id = %s
                RETURNING created_at, changed_at, changed_by_actor_id, provenance
                """,
                (actor_id, actor_id),
            )
            changed = cursor.fetchone()

    assert initial_changed_at == created_at
    assert changed is not None
    unchanged_created_at, changed_at, changed_by_actor_id, provenance = changed
    assert unchanged_created_at == created_at
    assert changed_at > initial_changed_at
    assert changed_by_actor_id == actor_id
    assert provenance == "credential-change-2"


@pytest.mark.parametrize(
    "mutation_case",
    [
        "missing-actor",
        "stale-provenance",
        "audit-only",
    ],
)
def test_password_credential_changes_require_material_actor_and_new_provenance(
    mutation_case: str,
) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Credential Audit', 'credential-audit',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"credential-audit-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.password_credentials (
                    actor_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, '$adaptive$params$oldsaltandhash', 'adaptive',
                          '{"cost": 1}'::jsonb, 'credential-change-1')
                """,
                (actor_id,),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                if mutation_case == "missing-actor":
                    cursor.execute(
                        """
                        UPDATE app.password_credentials
                        SET verifier_encoding = '$adaptive$params$newsaltandhash'
                        WHERE actor_id = %s
                        """,
                        (actor_id,),
                    )
                elif mutation_case == "stale-provenance":
                    cursor.execute(
                        """
                        UPDATE app.password_credentials
                        SET verifier_encoding = '$adaptive$params$newsaltandhash',
                            changed_by_actor_id = %s
                        WHERE actor_id = %s
                        """,
                        (actor_id, actor_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE app.password_credentials
                        SET changed_by_actor_id = %s,
                            provenance = 'credential-change-2'
                        WHERE actor_id = %s
                        """,
                        (actor_id, actor_id),
                    )


def test_readiness_succeeds_with_managed_runtime_database() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/health/ready")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_failed_forward_migration_preserves_baseline_and_history(tmp_path: Path) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    shutil.copy(BACKEND_ROOT / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(BACKEND_ROOT / "migrations", tmp_path / "migrations")
    config = Config(tmp_path / "alembic.ini")
    baseline_head = ScriptDirectory.from_config(config).get_current_head()
    assert baseline_head is not None
    failure_revision = tmp_path / "migrations" / "versions" / "ffff_test_failure.py"
    failure_revision.write_text(
        dedent(
            f'''\
            """Test-only failing forward migration."""
            from alembic import op
            revision = "ffff_test_failure"
            down_revision = "{baseline_head}"
            branch_labels = None
            depends_on = None
            def upgrade():
                op.execute("CREATE TABLE app.must_rollback (id integer)")
                op.execute("SELECT 1 / 0")
            def downgrade():
                raise RuntimeError("forward-only test migration")
            '''
        ),
        encoding="utf-8",
    )

    result = _run_alembic("-c", str(tmp_path / "alembic.ini"), "upgrade", "head", cwd=tmp_path)

    assert result.returncode != 0
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (baseline_head,)
            cursor.execute("SELECT to_regclass('app.schema_baseline')")
            assert cursor.fetchone() == ("app.schema_baseline",)
            cursor.execute("SELECT to_regclass('app.must_rollback')")
            assert cursor.fetchone() == (None,)


def test_user_accounts_migration_advances_the_previous_revision_without_data_loss() -> None:
    database = f"prm_forward_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )

    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    try:
        baseline_result = _run_alembic("upgrade", "20260813_01")
        assert baseline_result.returncode == 0, baseline_result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT baseline_key FROM app.schema_baseline")
                assert cursor.fetchone() == ("phase-1c",)
                cursor.execute("SELECT to_regclass('app.user_accounts')")
                assert cursor.fetchone() == (None,)

        head_result = _run_alembic("upgrade", "head")
        assert head_result.returncode == 0, head_result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT baseline_key FROM app.schema_baseline")
                assert cursor.fetchone() == ("phase-1c",)
                cursor.execute("SELECT to_regclass('app.user_accounts')")
                assert cursor.fetchone() == ("app.user_accounts",)
    finally:
        os.environ[MIGRATION_URL_ENV] = original_migration_url
        with psycopg.connect(admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_user_accounts_migration_refuses_destructive_downgrade() -> None:
    database = f"prm_account_downgrade_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )

    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    try:
        account_result = _run_alembic("upgrade", "20260817_02")
        assert account_result.returncode == 0, account_result.stderr

        result = _run_alembic("downgrade", "20260813_01")

        assert result.returncode != 0
        assert "DB-AUTH-001 migration is forward-only" in result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.user_accounts')")
                assert cursor.fetchone() == ("app.user_accounts",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260817_02",)
    finally:
        os.environ[MIGRATION_URL_ENV] = original_migration_url
        with psycopg.connect(admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_password_credentials_migration_refuses_destructive_downgrade() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    result = _run_alembic("downgrade", "20260817_02")

    assert result.returncode != 0
    assert "DB-AUTH-002 migration is forward-only" in result.stderr
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('app.password_credentials')")
            assert cursor.fetchone() == ("app.password_credentials",)
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == ("20260817_03",)


def test_password_credentials_migration_advances_user_accounts_without_data_loss() -> None:
    database = f"prm_credential_forward_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )

    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    actor_id = uuid.uuid4()
    try:
        account_result = _run_alembic("upgrade", "20260817_02")
        assert account_result.returncode == 0, account_result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, 'preserved-account', 'Preserved Account',
                              'preserved-account', 'active', 'optional',
                              'authorized-account-creation')
                    """,
                    (actor_id,),
                )

        head_result = _run_alembic("upgrade", "head")
        assert head_result.returncode == 0, head_result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT actor_id FROM app.user_accounts WHERE actor_id = %s",
                    (actor_id,),
                )
                assert cursor.fetchone() == (actor_id,)
                cursor.execute("SELECT to_regclass('app.password_credentials')")
                assert cursor.fetchone() == ("app.password_credentials",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260817_03",)
    finally:
        os.environ[MIGRATION_URL_ENV] = original_migration_url
        with psycopg.connect(admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_baseline_constraint_rejects_invalid_additive_row_without_data_loss() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO app.schema_baseline (baseline_key) VALUES (%s)",
                    ("",),
                )
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("SELECT baseline_key FROM app.schema_baseline")
            assert cursor.fetchall() == [("phase-1c",)]


def test_noop_upgrade_does_not_wait_on_baseline_reader() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as reader:
        with reader.cursor() as cursor:
            cursor.execute("SELECT * FROM app.schema_baseline")
            started = time.monotonic()
            result = _run_alembic("upgrade", "head")
            elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 2.0
