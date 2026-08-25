"""Real PostgreSQL migration tests for the bounded Phase 1C baseline."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from textwrap import dedent
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from psycopg.types.json import Jsonb

import property_rental.bootstrap_cli as bootstrap_cli
from property_rental.account_recovery import (
    AccountRecoveryConnection,
    AccountRecoveryMutation,
    AccountRecoveryRequest,
    PostgresAccountRecoveryRepository,
)
from property_rental.app import create_app
from property_rental.bootstrap_cli import RealBootstrapMaterialFactory
from property_rental.initial_owner_bootstrap import (
    BOOTSTRAP_ACKNOWLEDGEMENT,
    BootstrapFailed,
    BootstrapPasswordPolicy,
    BootstrapRequest,
    BootstrapSecretBundle,
    InitialOwnerBootstrapClosureConnection,
    InitialOwnerBootstrapService,
    PostgresInitialOwnerBootstrapRepository,
)
from property_rental.password_security import PasswordHashService
from property_rental.recovery_code_consumption import (
    PostgresRecoveryCodeConsumptionRepository,
    RecoveryCodeConsumptionConnection,
    RecoveryCodeConsumptionRequest,
    RecoveryCodeConsumptionService,
)
from property_rental.recovery_code_issuance import (
    RecoveryCodeSetRecord,
    RecoveryCodeVerifierRecord,
)
from property_rental.recovery_code_regeneration import (
    PostgresRecoveryCodeRegenerationRepository,
    RecoveryCodeRegenerationConnection,
)
from property_rental.recovery_code_security import Argon2idRecoveryCodeVerifierProvider
from property_rental.settings import Settings
from property_rental.totp_security import TotpSecret, TotpService

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_URL_ENV = "MIGRATION_DATABASE_URL"
RUNTIME_URL_ENV = "APP_DATABASE_URL"
ADMIN_URL_ENV = "TEST_ADMIN_DATABASE_URL"
BACKUP_URL_ENV = "BACKUP_DATABASE_URL"
RESTORE_URL_ENV = "RESTORE_DATABASE_URL"
HUMAN_ADMIN_URL_ENV = "HUMAN_ADMIN_DATABASE_URL"
BOOTSTRAP_URL_ENV = "BOOTSTRAP_DATABASE_URL"
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
        BOOTSTRAP_URL_ENV: "prm_bootstrap",
    }
    parsed_urls = {
        ADMIN_URL_ENV: urlsplit(admin_url),
        MIGRATION_URL_ENV: urlsplit(migration_url),
        RUNTIME_URL_ENV: urlsplit(runtime_url),
        BACKUP_URL_ENV: urlsplit(_required_url(BACKUP_URL_ENV)),
        RESTORE_URL_ENV: urlsplit(_required_url(RESTORE_URL_ENV)),
        HUMAN_ADMIN_URL_ENV: urlsplit(_required_url(HUMAN_ADMIN_URL_ENV)),
        BOOTSTRAP_URL_ENV: urlsplit(_required_url(BOOTSTRAP_URL_ENV)),
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


@contextmanager
def _temporary_migration_database(prefix: str) -> Iterator[str]:
    database = f"{prefix}_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    migration_url = _url_with_database(original_migration_url, database)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT CONNECT ON DATABASE {} TO prm_runtime, prm_backup, prm_restore, "
                    "prm_human_admin, prm_bootstrap"
                ).format(sql.Identifier(database))
            )
    os.environ[MIGRATION_URL_ENV] = migration_url
    try:
        yield migration_url
    finally:
        os.environ[MIGRATION_URL_ENV] = original_migration_url
        with psycopg.connect(admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


@pytest.fixture(scope="session", autouse=True)
def empty_application_database() -> Iterator[None]:
    database = f"prm_test_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    original_runtime_url = _required_url(RUNTIME_URL_ENV)
    original_backup_url = _required_url(BACKUP_URL_ENV)
    original_restore_url = _required_url(RESTORE_URL_ENV)
    original_human_admin_url = _required_url(HUMAN_ADMIN_URL_ENV)
    original_bootstrap_url = _required_url(BOOTSTRAP_URL_ENV)
    _validate_local_test_urls(admin_url, original_migration_url, original_runtime_url)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT CONNECT ON DATABASE {} TO prm_runtime, prm_backup, prm_restore, "
                    "prm_human_admin, prm_bootstrap"
                ).format(sql.Identifier(database))
            )
    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    os.environ[RUNTIME_URL_ENV] = _url_with_database(original_runtime_url, database)
    os.environ[BACKUP_URL_ENV] = _url_with_database(original_backup_url, database)
    os.environ[RESTORE_URL_ENV] = _url_with_database(original_restore_url, database)
    os.environ[HUMAN_ADMIN_URL_ENV] = _url_with_database(original_human_admin_url, database)
    os.environ[BOOTSTRAP_URL_ENV] = _url_with_database(original_bootstrap_url, database)
    yield
    os.environ[MIGRATION_URL_ENV] = original_migration_url
    os.environ[RUNTIME_URL_ENV] = original_runtime_url
    os.environ[BACKUP_URL_ENV] = original_backup_url
    os.environ[RESTORE_URL_ENV] = original_restore_url
    os.environ[HUMAN_ADMIN_URL_ENV] = original_human_admin_url
    os.environ[BOOTSTRAP_URL_ENV] = original_bootstrap_url


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
                    'prm_restore', 'prm_human_admin', 'prm_bootstrap'
                )
                ORDER BY rolname
                """
            )
            rows = cursor.fetchall()
            assert [row[0] for row in rows] == [
                "prm_backup",
                "prm_bootstrap",
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
            cursor.execute(
                """
                SELECT
                    has_database_privilege('prm_bootstrap', 'postgres', 'CONNECT,TEMP'),
                    has_database_privilege('prm_bootstrap', 'template1', 'CONNECT,TEMP')
                """
            )
            assert cursor.fetchone() == (False, False)

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
                    SET created_at = statement_timestamp()
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


def test_recovery_code_storage_has_bounded_set_and_code_columns() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name IN ('recovery_code_sets', 'recovery_codes')
                ORDER BY table_name, ordinal_position
                """
            )

            assert cursor.fetchall() == [
                ("recovery_code_sets", "set_id", "uuid", "NO"),
                ("recovery_code_sets", "actor_id", "uuid", "NO"),
                ("recovery_code_sets", "created_at", "timestamp with time zone", "NO"),
                ("recovery_code_sets", "created_by_actor_id", "uuid", "YES"),
                ("recovery_code_sets", "provenance", "text", "NO"),
                ("recovery_code_sets", "invalidated_at", "timestamp with time zone", "YES"),
                ("recovery_code_sets", "invalidated_by_actor_id", "uuid", "YES"),
                ("recovery_code_sets", "invalidation_provenance", "text", "YES"),
                ("recovery_codes", "code_id", "uuid", "NO"),
                ("recovery_codes", "set_id", "uuid", "NO"),
                ("recovery_codes", "verifier_encoding", "text", "NO"),
                ("recovery_codes", "algorithm", "text", "NO"),
                ("recovery_codes", "work_factor_metadata", "jsonb", "NO"),
                ("recovery_codes", "created_at", "timestamp with time zone", "NO"),
                ("recovery_codes", "provenance", "text", "NO"),
                ("recovery_codes", "consumed_at", "timestamp with time zone", "YES"),
                ("recovery_codes", "consumed_by_actor_id", "uuid", "YES"),
                ("recovery_codes", "consumption_provenance", "text", "YES"),
                ("recovery_codes", "invalidated_at", "timestamp with time zone", "YES"),
                ("recovery_codes", "invalidated_by_actor_id", "uuid", "YES"),
                ("recovery_codes", "invalidation_provenance", "text", "YES"),
            ]


def test_recovery_codes_have_independent_immutable_identities_and_consumption() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    first_code_id = uuid.uuid4()
    second_code_id = uuid.uuid4()
    first_verifier = f"$opaque$v=1${uuid.uuid4().hex}"
    second_verifier = f"$opaque$v=1${uuid.uuid4().hex}"
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Recovery Target', 'recovery-target',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"recovery-target-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (
                    set_id, actor_id, created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, 'protected-enrollment')
                """,
                (set_id, actor_id, actor_id),
            )
            cursor.executemany(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, 'opaque', '{"cost": 1}'::jsonb,
                          'protected-enrollment')
                """,
                [
                    (first_code_id, set_id, first_verifier),
                    (second_code_id, set_id, second_verifier),
                ],
            )
            cursor.execute(
                """
                UPDATE app.recovery_codes
                SET consumed_at = statement_timestamp(),
                    consumed_by_actor_id = %s,
                    consumption_provenance = 'successful-recovery'
                WHERE code_id = %s
                """,
                (actor_id, first_code_id),
            )
            cursor.execute(
                """
                SELECT code_id, consumed_at IS NOT NULL
                FROM app.recovery_codes
                WHERE set_id = %s
                ORDER BY code_id
                """,
                (set_id,),
            )
            assert set(cursor.fetchall()) == {
                (first_code_id, True),
                (second_code_id, False),
            }
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.recovery_codes SET code_id = %s WHERE code_id = %s",
                    (uuid.uuid4(), second_code_id),
                )
        connection.rollback()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE app.recovery_codes
                    SET consumption_provenance = 'rewritten-recovery'
                    WHERE code_id = %s
                    """,
                    (first_code_id,),
                )


def test_recovery_code_consumption_adapter_is_atomic_and_single_use_on_postgresql() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    matching_code_id = uuid.uuid4()
    sibling_code_id = uuid.uuid4()
    matching_secret = "postgresql-single-use-recovery-secret"
    sibling_secret = "postgresql-unused-recovery-secret"
    verifier_provider = Argon2idRecoveryCodeVerifierProvider()
    matching_verifier = verifier_provider.encode(matching_secret)
    sibling_verifier = verifier_provider.encode(sibling_secret)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Recovery Consumer', 'recovery-consumer',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"recovery-consumer-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (
                    set_id, actor_id, created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, 'protected-enrollment')
                RETURNING created_at
                """,
                (set_id, actor_id, actor_id),
            )
            created_row = cursor.fetchone()
            assert created_row is not None
            set_created_at = cast(datetime, created_row[0])
            cursor.executemany(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, %s, %s::jsonb, 'protected-enrollment')
                """,
                [
                    (
                        matching_code_id,
                        set_id,
                        matching_verifier.verifier_encoding,
                        matching_verifier.algorithm,
                        '{"memory_cost": 65536}',
                    ),
                    (
                        sibling_code_id,
                        set_id,
                        sibling_verifier.verifier_encoding,
                        sibling_verifier.algorithm,
                        '{"memory_cost": 65536}',
                    ),
                ],
            )
            cursor.execute(
                "SELECT max(created_at) FROM app.recovery_codes WHERE set_id = %s",
                (set_id,),
            )
            code_created_row = cursor.fetchone()
            assert code_created_row is not None and code_created_row[0] is not None
            code_created_at = cast(datetime, code_created_row[0])
        connection.commit()

    consumed_at = max(set_created_at, code_created_at) + timedelta(microseconds=1)
    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as runtime_connection:
        audit_evidence = []

        class DatabaseTestAuditSink:
            def record(self, evidence: object) -> None:
                audit_evidence.append(evidence)

        service = RecoveryCodeConsumptionService(
            repository=PostgresRecoveryCodeConsumptionRepository(
                cast(RecoveryCodeConsumptionConnection, runtime_connection)
            ),
            verifier_provider=verifier_provider,
            audit_sink=DatabaseTestAuditSink(),
            clock=lambda: consumed_at,
        )
        request = RecoveryCodeConsumptionRequest(
            consuming_actor_id=actor_id,
            target_actor_id=actor_id,
            set_id=set_id,
            candidate=matching_secret,
            correlation_id="postgresql-consumption",
            provenance="protected-recovery",
        )

        first = service.consume(request)
        repeated = service.consume(request)

        assert first.completed
        assert first.reason == "code_consumed"
        assert not repeated.completed
        assert repeated.reason == "code_rejected"
        with runtime_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT code_id, consumed_at, consumed_by_actor_id, consumption_provenance
                FROM app.recovery_codes
                WHERE set_id = %s
                ORDER BY code_id
                """,
                (set_id,),
            )
            persisted = {row[0]: row[1:] for row in cursor.fetchall()}

    assert persisted[matching_code_id] == (
        consumed_at,
        actor_id,
        '{"correlation_id":"postgresql-consumption","previous_state":"active","provenance":"protected-recovery","reason":"code_consumed","resulting_state":"consumed"}',
    )
    assert persisted[sibling_code_id] == (None, None, None)
    assert len(audit_evidence) == 2


def test_recovery_code_regeneration_is_atomic_and_invalidates_prior_set_on_postgresql() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    prior_set_id = uuid.uuid4()
    prior_code_id = uuid.uuid4()
    replacement_set_id = uuid.uuid4()
    replacement_code_ids = (uuid.uuid4(), uuid.uuid4())
    prior_secret = "postgresql-prior-recovery-secret"
    replacement_secrets = (
        "postgresql-first-replacement-secret",
        "postgresql-second-replacement-secret",
    )
    verifier_provider = Argon2idRecoveryCodeVerifierProvider()
    prior_verifier = verifier_provider.encode(prior_secret)
    replacement_verifiers = tuple(
        verifier_provider.encode(secret) for secret in replacement_secrets
    )
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Recovery Regeneration', 'recovery-regeneration',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"recovery-regeneration-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (
                    set_id, actor_id, created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, 'protected-enrollment')
                RETURNING created_at
                """,
                (prior_set_id, actor_id, actor_id),
            )
            created_row = cursor.fetchone()
            assert created_row is not None
            prior_set_created_at = cast(datetime, created_row[0])
            cursor.execute(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, %s, %s::jsonb, 'protected-enrollment')
                """,
                (
                    prior_code_id,
                    prior_set_id,
                    prior_verifier.verifier_encoding,
                    prior_verifier.algorithm,
                    '{"memory_cost": 65536}',
                ),
            )
        connection.commit()

    occurred_at = prior_set_created_at + timedelta(microseconds=1)
    replacement = RecoveryCodeSetRecord(
        set_id=replacement_set_id,
        target_actor_id=actor_id,
        issued_by_actor_id=actor_id,
        correlation_id="postgresql-regeneration",
        provenance="protected-regeneration",
        codes=tuple(
            RecoveryCodeVerifierRecord(
                code_id=code_id,
                verifier_encoding=verifier.verifier_encoding,
                algorithm=verifier.algorithm,
                work_factor_metadata=verifier.work_factor_metadata,
            )
            for code_id, verifier in zip(
                replacement_code_ids,
                replacement_verifiers,
                strict=True,
            )
        ),
    )
    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as runtime_connection:
        repository = PostgresRecoveryCodeRegenerationRepository(
            cast(RecoveryCodeRegenerationConnection, runtime_connection)
        )
        repository.replace_atomically(prior_set_id, replacement, occurred_at)

        class RegenerationConsumptionAuditSink:
            def record(self, evidence: object) -> None:
                del evidence

        consumption = RecoveryCodeConsumptionService(
            repository=PostgresRecoveryCodeConsumptionRepository(
                cast(RecoveryCodeConsumptionConnection, runtime_connection)
            ),
            verifier_provider=verifier_provider,
            audit_sink=RegenerationConsumptionAuditSink(),
            clock=lambda: occurred_at,
        )
        prior_result = consumption.consume(
            RecoveryCodeConsumptionRequest(
                consuming_actor_id=actor_id,
                target_actor_id=actor_id,
                set_id=prior_set_id,
                candidate=prior_secret,
                correlation_id="postgresql-regeneration-prior-check",
                provenance="protected-recovery",
            )
        )

        conflicting_replacement = RecoveryCodeSetRecord(
            set_id=uuid.uuid4(),
            target_actor_id=actor_id,
            issued_by_actor_id=actor_id,
            correlation_id="postgresql-regeneration-repeat",
            provenance="protected-regeneration",
            codes=replacement.codes,
        )
        with pytest.raises(RuntimeError, match="active prior recovery-code set not found"):
            repository.replace_atomically(prior_set_id, conflicting_replacement, occurred_at)

        with runtime_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT set_id, invalidated_at, invalidated_by_actor_id, invalidation_provenance
                FROM app.recovery_code_sets
                WHERE set_id IN (%s, %s, %s)
                ORDER BY set_id
                """,
                (prior_set_id, replacement_set_id, conflicting_replacement.set_id),
            )
            persisted_sets = {row[0]: row[1:] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT code_id, verifier_encoding
                FROM app.recovery_codes
                WHERE set_id = %s
                ORDER BY code_id
                """,
                (replacement_set_id,),
            )
            persisted_codes = {row[0]: row[1] for row in cursor.fetchall()}

    assert not prior_result.completed
    assert prior_result.reason == "code_rejected"
    assert persisted_sets[prior_set_id] == (
        occurred_at,
        actor_id,
        '{"correlation_id":"postgresql-regeneration","previous_state":"active","provenance":"protected-regeneration","reason":"set_regenerated","replacement_set_id":"'
        + str(replacement_set_id)
        + '","resulting_state":"invalidated"}',
    )
    assert persisted_sets[replacement_set_id] == (None, None, None)
    assert conflicting_replacement.set_id not in persisted_sets
    assert set(persisted_codes) == set(replacement_code_ids)
    assert all(
        verifier_provider.matches(secret, persisted_codes[code_id])
        for secret, code_id in zip(replacement_secrets, replacement_code_ids, strict=True)
    )


def test_recovery_code_set_identity_and_completed_invalidation_are_immutable() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    other_actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Set Identity', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                [
                    (actor_id, f"set-owner-{uuid.uuid4().hex}", f"set-owner-{actor_id}"),
                    (
                        other_actor_id,
                        f"other-set-owner-{uuid.uuid4().hex}",
                        f"other-set-owner-{other_actor_id}",
                    ),
                ],
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (
                    set_id, actor_id, created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, 'protected-enrollment')
                """,
                (set_id, actor_id, actor_id),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.recovery_code_sets SET actor_id = %s WHERE set_id = %s",
                    (other_actor_id, set_id),
                )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.recovery_code_sets
                SET invalidated_at = statement_timestamp(),
                    invalidated_by_actor_id = %s,
                    invalidation_provenance = 'protected-regeneration'
                WHERE set_id = %s
                """,
                (actor_id, set_id),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE app.recovery_code_sets
                    SET invalidation_provenance = 'rewritten-regeneration'
                    WHERE set_id = %s
                    """,
                    (set_id,),
                )


@pytest.mark.parametrize(
    ("verifier_encoding", "algorithm", "work_factor_metadata"),
    [
        ("plaintext-recovery-code", "opaque", '{"cost": 1}'),
        ("$opaque$v=1$verifier", "   ", '{"cost": 1}'),
        ("$other$v=1$verifier", "opaque", '{"cost": 1}'),
        ("$opaque$v=1$verifier", "opaque", "{}"),
        ("$opaque$v=1$verifier", "opaque", '{"cost": 0}'),
    ],
)
def test_recovery_codes_reject_unprotected_or_incomplete_verifier_material(
    verifier_encoding: str,
    algorithm: str,
    work_factor_metadata: str,
) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Verifier Constraint', 'verifier-constraint',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"verifier-constraint-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (set_id, actor_id, provenance)
                VALUES (%s, %s, 'protected-enrollment')
                """,
                (set_id, actor_id),
            )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.recovery_codes (
                        code_id, set_id, verifier_encoding, algorithm,
                        work_factor_metadata, provenance
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, 'protected-enrollment')
                    """,
                    (
                        uuid.uuid4(),
                        set_id,
                        verifier_encoding,
                        algorithm,
                        work_factor_metadata,
                    ),
                )


@pytest.mark.parametrize("lifecycle", ["consumed", "invalidated"])
def test_recovery_code_lifecycle_timestamps_require_complete_provenance(lifecycle: str) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    code_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Lifecycle Constraint', 'lifecycle-constraint',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"lifecycle-constraint-{uuid.uuid4().hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (set_id, actor_id, provenance)
                VALUES (%s, %s, 'protected-enrollment')
                """,
                (set_id, actor_id),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, '$opaque$v=1$lifecycle-verifier', 'opaque',
                          '{"cost": 1}'::jsonb, 'protected-enrollment')
                """,
                (code_id, set_id),
            )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "UPDATE app.recovery_codes SET {} = statement_timestamp() "
                        "WHERE code_id = %s"
                    ).format(sql.Identifier(f"{lifecycle}_at")),
                    (code_id,),
                )


def test_runtime_has_only_bounded_recovery_code_lifecycle_privileges() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name, privilege_type
                FROM information_schema.column_privileges
                WHERE table_schema = 'app'
                  AND table_name IN ('recovery_code_sets', 'recovery_codes')
                  AND grantee = 'prm_runtime'
                """
            )
            actual_privileges = set(cursor.fetchall())

            set_columns = {
                "set_id",
                "actor_id",
                "created_at",
                "created_by_actor_id",
                "provenance",
                "invalidated_at",
                "invalidated_by_actor_id",
                "invalidation_provenance",
            }
            code_columns = {
                "code_id",
                "set_id",
                "verifier_encoding",
                "algorithm",
                "work_factor_metadata",
                "created_at",
                "provenance",
                "consumed_at",
                "consumed_by_actor_id",
                "consumption_provenance",
                "invalidated_at",
                "invalidated_by_actor_id",
                "invalidation_provenance",
            }
            expected_privileges = {
                *(("recovery_code_sets", column, "SELECT") for column in set_columns),
                *(("recovery_codes", column, "SELECT") for column in code_columns),
                *(
                    ("recovery_code_sets", column, "INSERT")
                    for column in {
                        "set_id",
                        "actor_id",
                        "created_by_actor_id",
                        "provenance",
                    }
                ),
                *(
                    ("recovery_codes", column, "INSERT")
                    for column in {
                        "code_id",
                        "set_id",
                        "verifier_encoding",
                        "algorithm",
                        "work_factor_metadata",
                        "provenance",
                    }
                ),
                *(
                    ("recovery_code_sets", column, "UPDATE")
                    for column in {
                        "invalidated_at",
                        "invalidated_by_actor_id",
                        "invalidation_provenance",
                    }
                ),
                *(
                    ("recovery_codes", column, "UPDATE")
                    for column in {
                        "consumed_at",
                        "consumed_by_actor_id",
                        "consumption_provenance",
                        "invalidated_at",
                        "invalidated_by_actor_id",
                        "invalidation_provenance",
                    }
                ),
            }
            assert actual_privileges == expected_privileges

            cursor.execute(
                """
                SELECT
                    has_table_privilege('prm_runtime', 'app.recovery_code_sets', 'DELETE'),
                    has_table_privilege('prm_runtime', 'app.recovery_code_sets', 'TRUNCATE'),
                    has_table_privilege('prm_runtime', 'app.recovery_codes', 'DELETE'),
                    has_table_privilege('prm_runtime', 'app.recovery_codes', 'TRUNCATE'),
                    has_function_privilege(
                        'prm_runtime',
                        'app.valid_recovery_code_work_factor_metadata(jsonb)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime', 'app.protect_recovery_code_set_lifecycle()', 'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime', 'app.protect_recovery_code_lifecycle()', 'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (False, False, False, False, True, False, False)


def test_runtime_can_insert_bounded_recovery_code_verifier_rows() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    actor_id = uuid.uuid4()
    set_id = uuid.uuid4()
    code_id = uuid.uuid4()
    verifier_encoding = f"$opaque$v=1${uuid.uuid4().hex}"
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Runtime Recovery', 'runtime-recovery',
                          'active', 'optional', 'authorized-account-creation')
                """,
                (actor_id, f"runtime-recovery-{uuid.uuid4().hex}"),
            )

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (set_id, actor_id, provenance)
                VALUES (%s, %s, 'protected-enrollment')
                """,
                (set_id, actor_id),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, 'opaque', '{"cost": 1}'::jsonb,
                          'protected-enrollment')
                """,
                (code_id, set_id, verifier_encoding),
            )
            cursor.execute(
                "SELECT code_id FROM app.recovery_codes WHERE code_id = %s",
                (code_id,),
            )
            assert cursor.fetchone() == (code_id,)


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
            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO prm_bootstrap").format(
                    sql.Identifier(database)
                )
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
    database = f"prm_credential_downgrade_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )

    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    try:
        assert _run_alembic("upgrade", "20260817_03").returncode == 0

        result = _run_alembic("downgrade", "20260817_02")

        assert result.returncode != 0
        assert "DB-AUTH-002 migration is forward-only" in result.stderr
        with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
            with connection.cursor() as cursor:
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


def test_recovery_code_migration_refuses_destructive_downgrade() -> None:
    with _temporary_migration_database("prm_recovery_downgrade") as migration_url:
        assert _run_alembic("upgrade", "20260817_04").returncode == 0

        result = _run_alembic("downgrade", "20260817_03")

        assert result.returncode != 0
        assert "DB-AUTH-003 recovery-code migration is forward-only" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.recovery_code_sets')")
                assert cursor.fetchone() == ("app.recovery_code_sets",)
                cursor.execute("SELECT to_regclass('app.recovery_codes')")
                assert cursor.fetchone() == ("app.recovery_codes",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260817_04",)


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

        credential_result = _run_alembic("upgrade", "20260817_03")
        assert credential_result.returncode == 0, credential_result.stderr
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


def test_initial_owner_bootstrap_closure_storage_is_bounded_and_secret_free() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name IN (
                      'initial_owner_bootstrap_closure',
                      'initial_owner_bootstrap_audit_events'
                  )
                ORDER BY table_name, ordinal_position
                """
            )

            assert cursor.fetchall() == [
                ("initial_owner_bootstrap_audit_events", "event_id", "bigint", "NO"),
                ("initial_owner_bootstrap_audit_events", "target_actor_id", "uuid", "NO"),
                (
                    "initial_owner_bootstrap_audit_events",
                    "occurred_at",
                    "timestamp with time zone",
                    "NO",
                ),
                (
                    "initial_owner_bootstrap_audit_events",
                    "procedure_identity",
                    "text",
                    "NO",
                ),
                ("initial_owner_bootstrap_audit_events", "correlation_id", "uuid", "NO"),
                ("initial_owner_bootstrap_audit_events", "outcome", "text", "NO"),
                ("initial_owner_bootstrap_audit_events", "reason", "text", "NO"),
                ("initial_owner_bootstrap_audit_events", "previous_state", "text", "NO"),
                ("initial_owner_bootstrap_audit_events", "resulting_state", "text", "NO"),
                (
                    "initial_owner_bootstrap_audit_events",
                    "established_actor_id",
                    "uuid",
                    "YES",
                ),
                ("initial_owner_bootstrap_closure", "singleton", "boolean", "NO"),
                ("initial_owner_bootstrap_closure", "established_actor_id", "uuid", "NO"),
                (
                    "initial_owner_bootstrap_closure",
                    "established_at",
                    "timestamp with time zone",
                    "NO",
                ),
                ("initial_owner_bootstrap_closure", "correlation_id", "uuid", "NO"),
            ]


def test_initial_owner_bootstrap_closes_once_and_audits_repeated_attempt() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    first_actor_id = uuid.uuid4()
    second_actor_id = uuid.uuid4()
    first_correlation_id = uuid.uuid4()
    second_correlation_id = uuid.uuid4()

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                (first_actor_id, first_correlation_id),
            )
            assert cursor.fetchone() == (True,)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.commit()
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM app.initial_owner_bootstrap_closure")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM app.initial_owner_bootstrap_audit_events")
            assert cursor.fetchone() == (0,)

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                (first_actor_id, first_correlation_id),
            )
            assert cursor.fetchone() == (True,)
            for actor_id, username in (
                (first_actor_id, "bootstrap-first-owner"),
                (second_actor_id, "bootstrap-second-owner"),
            ):
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, %s, %s, 'active', 'required',
                              'protected-initial-owner-bootstrap')
                    """,
                    (actor_id, username, username, username),
                )
            cursor.execute(
                "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                (second_actor_id, second_correlation_id),
            )
            assert cursor.fetchone() == (False,)
            cursor.execute(
                """
                SELECT established_actor_id, correlation_id
                FROM app.initial_owner_bootstrap_closure
                """
            )
            assert cursor.fetchall() == [(first_actor_id, first_correlation_id)]
            cursor.execute(
                """
                SELECT target_actor_id, procedure_identity, correlation_id, outcome, reason,
                       previous_state, resulting_state, established_actor_id
                FROM app.initial_owner_bootstrap_audit_events
                ORDER BY event_id
                """
            )
            assert cursor.fetchall() == [
                (
                    first_actor_id,
                    "protected_initial_owner_bootstrap",
                    first_correlation_id,
                    "completed",
                    "initial_owner_established",
                    "open",
                    "closed",
                    first_actor_id,
                ),
                (
                    second_actor_id,
                    "protected_initial_owner_bootstrap",
                    second_correlation_id,
                    "rejected",
                    "bootstrap_closed",
                    "closed",
                    "closed",
                    first_actor_id,
                ),
            ]
        connection.rollback()


def test_initial_owner_bootstrap_closure_does_not_infer_role_from_mfa_policy() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Optional MFA', 'optional-mfa', 'active', 'optional',
                          'protected-initial-owner-bootstrap')
                """,
                (actor_id, f"optional-{actor_id.hex}"),
            )
            cursor.execute(
                "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                (actor_id, correlation_id),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute("SELECT established_actor_id FROM app.initial_owner_bootstrap_closure")
            assert cursor.fetchone() == (actor_id,)
            cursor.execute(
                """
                SELECT outcome, reason, previous_state, resulting_state, established_actor_id
                FROM app.initial_owner_bootstrap_audit_events
                """
            )
            assert cursor.fetchone() == (
                "completed",
                "initial_owner_established",
                "open",
                "closed",
                actor_id,
            )
        connection.rollback()


def test_initial_owner_bootstrap_history_rejects_update_delete_and_truncate() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Immutable Owner', 'immutable-owner', 'active', 'required',
                          'protected-initial-owner-bootstrap')
                """,
                (actor_id, f"immutable-{actor_id.hex}"),
            )
            cursor.execute(
                "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                (actor_id, uuid.uuid4()),
            )
        connection.commit()
        for statement in (
            sql.SQL("UPDATE app.initial_owner_bootstrap_closure SET established_at = now()"),
            sql.SQL("DELETE FROM app.initial_owner_bootstrap_closure"),
            sql.SQL("TRUNCATE app.initial_owner_bootstrap_closure"),
            sql.SQL(
                "UPDATE app.initial_owner_bootstrap_audit_events SET reason = 'bootstrap_closed'"
            ),
            sql.SQL("DELETE FROM app.initial_owner_bootstrap_audit_events"),
            sql.SQL("TRUNCATE app.initial_owner_bootstrap_audit_events"),
        ):
            with connection.cursor() as cursor:
                cursor.execute("SAVEPOINT bootstrap_history_immutability")
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                with connection.cursor() as cursor:
                    cursor.execute(statement)
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK TO SAVEPOINT bootstrap_history_immutability")
        connection.rollback()


def test_runtime_cannot_observe_or_invoke_initial_owner_bootstrap_guard() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM app.initial_owner_bootstrap_closure")
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM app.initial_owner_bootstrap_audit_events")
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                    (uuid.uuid4(), uuid.uuid4()),
                )
        connection.rollback()

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    routine.prosecdef,
                    routine.proconfig @> ARRAY['search_path=pg_catalog'],
                    has_function_privilege(
                        'public',
                        'app.attempt_initial_owner_bootstrap_closure(uuid, uuid)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.attempt_initial_owner_bootstrap_closure(uuid, uuid)',
                        'EXECUTE'
                    )
                FROM pg_catalog.pg_proc AS routine
                WHERE routine.oid =
                    'app.attempt_initial_owner_bootstrap_closure(uuid, uuid)'::regprocedure
                """
            )
            assert cursor.fetchone() == (True, True, False, False)


def test_concurrent_initial_owner_bootstrap_attempts_establish_exactly_one_owner() -> None:
    with _temporary_migration_database("prm_bootstrap_concurrency") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        actor_ids = (uuid.uuid4(), uuid.uuid4())
        correlation_ids = (uuid.uuid4(), uuid.uuid4())

        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                for actor_id in actor_ids:
                    cursor.execute(
                        """
                        INSERT INTO app.user_accounts (
                            actor_id, normalized_username, display_name, audit_name,
                            lifecycle_state, mfa_policy_class, provenance
                        ) VALUES (%s, %s, 'Concurrent Owner', %s, 'active', 'required',
                                  'protected-initial-owner-bootstrap')
                        """,
                        (actor_id, f"concurrent-{actor_id.hex}", f"concurrent-{actor_id.hex}"),
                    )

        def attempt(parameters: tuple[uuid.UUID, uuid.UUID]) -> bool:
            with psycopg.connect(migration_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM app.attempt_initial_owner_bootstrap_closure(%s, %s)",
                        parameters,
                    )
                    row = cursor.fetchone()
                    assert row is not None
                    return cast(bool, row[0])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, zip(actor_ids, correlation_ids, strict=True)))

        assert results.count(True) == 1
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT established_actor_id FROM app.initial_owner_bootstrap_closure"
                )
                closure_rows = cursor.fetchall()
                assert len(closure_rows) == 1
                assert closure_rows[0][0] in actor_ids
                cursor.execute(
                    "SELECT outcome, count(*) FROM app.initial_owner_bootstrap_audit_events "
                    "GROUP BY outcome ORDER BY outcome"
                )
                assert cursor.fetchall() == [("completed", 1), ("rejected", 1)]


def test_initial_owner_bootstrap_closure_migration_refuses_destructive_downgrade() -> None:
    with _temporary_migration_database("prm_bootstrap_downgrade") as migration_url:
        assert _run_alembic("upgrade", "20260818_05").returncode == 0

        result = _run_alembic("downgrade", "20260817_04")

        assert result.returncode != 0
        assert "DB-AUTH-005 bootstrap-closure migration is forward-only" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.initial_owner_bootstrap_closure')")
                assert cursor.fetchone() == ("app.initial_owner_bootstrap_closure",)
                cursor.execute("SELECT to_regclass('app.initial_owner_bootstrap_audit_events')")
                assert cursor.fetchone() == ("app.initial_owner_bootstrap_audit_events",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260818_05",)


def test_totp_enrollments_store_only_protected_material_separate_from_account_authority() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'totp_mfa_enrollments'
                ORDER BY ordinal_position
                """
            )
            assert cursor.fetchall() == [
                ("enrollment_id", "uuid", "NO"),
                ("actor_id", "uuid", "NO"),
                ("secret_ciphertext", "bytea", "NO"),
                ("secret_nonce", "bytea", "NO"),
                ("key_identifier", "text", "NO"),
                ("protection_algorithm", "text", "NO"),
                ("totp_algorithm", "text", "NO"),
                ("digits", "smallint", "NO"),
                ("period_seconds", "integer", "NO"),
                ("enrollment_state", "text", "NO"),
                ("created_at", "timestamp with time zone", "NO"),
                ("created_by_actor_id", "uuid", "YES"),
                ("provenance", "text", "NO"),
                ("activated_at", "timestamp with time zone", "YES"),
                ("activated_by_actor_id", "uuid", "YES"),
                ("activation_provenance", "text", "YES"),
                ("disabled_at", "timestamp with time zone", "YES"),
                ("disabled_by_actor_id", "uuid", "YES"),
                ("disablement_provenance", "text", "YES"),
            ]
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name = 'totp_mfa_enrollments'
                  AND column_name ~ '(role|capability|plaintext|secret_value)'
                """
            )
            assert cursor.fetchall() == []


@pytest.mark.parametrize(
    ("ciphertext", "nonce", "key_identifier", "protection_algorithm", "totp_algorithm"),
    [
        (b"too-short", b"n" * 12, "key-1", "aes-256-gcm", "sha1"),
        (b"c" * 36, b"short", "key-1", "aes-256-gcm", "sha1"),
        (b"c" * 36, b"n" * 12, " key-1 ", "aes-256-gcm", "sha1"),
        (b"c" * 36, b"n" * 12, "key-1", "not-authenticated", "sha1"),
        (b"c" * 36, b"n" * 12, "key-1", "aes-256-gcm", "md5"),
    ],
)
def test_totp_enrollments_reject_unprotected_or_malformed_verifier_material(
    ciphertext: bytes,
    nonce: bytes,
    key_identifier: str,
    protection_algorithm: str,
    totp_algorithm: str,
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
                ) VALUES (%s, %s, 'TOTP Constraint', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"totp-constraint-{actor_id.hex}", f"totp-{actor_id.hex}"),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.totp_mfa_enrollments (
                        enrollment_id, actor_id, secret_ciphertext, secret_nonce,
                        key_identifier, protection_algorithm, totp_algorithm, provenance
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'protected-enrollment')
                    """,
                    (
                        uuid.uuid4(),
                        actor_id,
                        ciphertext,
                        nonce,
                        key_identifier,
                        protection_algorithm,
                        totp_algorithm,
                    ),
                )


def test_totp_enrollment_lifecycle_preserves_secret_and_single_live_enrollment() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    enrollment_id = uuid.uuid4()
    lifecycle_actor_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            for account_id, label in ((actor_id, "target"), (lifecycle_actor_id, "operator")):
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'TOTP Lifecycle', %s, 'active', 'required',
                              'authorized-account-creation')
                    """,
                    (account_id, f"totp-{label}-{account_id.hex}", f"totp-{label}"),
                )
            cursor.execute(
                """
                INSERT INTO app.totp_mfa_enrollments (
                    enrollment_id, actor_id, secret_ciphertext, secret_nonce,
                    key_identifier, protection_algorithm, totp_algorithm,
                    created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, %s, 'key-1', 'aes-256-gcm', 'sha1', %s,
                          'protected-enrollment')
                """,
                (enrollment_id, actor_id, b"c" * 36, b"n" * 12, lifecycle_actor_id),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.totp_mfa_enrollments (
                        enrollment_id, actor_id, secret_ciphertext, secret_nonce,
                        key_identifier, protection_algorithm, totp_algorithm, provenance
                    ) VALUES (%s, %s, %s, %s, 'key-1', 'aes-256-gcm', 'sha1',
                              'duplicate-live-enrollment')
                    """,
                    (uuid.uuid4(), actor_id, b"d" * 36, b"m" * 12),
                )
        connection.rollback()

        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.totp_mfa_enrollments (
                        enrollment_id, actor_id, secret_ciphertext, secret_nonce,
                        key_identifier, protection_algorithm, totp_algorithm, provenance
                    ) VALUES (%s, %s, %s, %s, 'key-1', 'aes-256-gcm', 'sha1',
                              'duplicate-key-nonce')
                    """,
                    (uuid.uuid4(), lifecycle_actor_id, b"e" * 36, b"n" * 12),
                )
        connection.rollback()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.totp_mfa_enrollments SET secret_ciphertext = %s "
                    "WHERE enrollment_id = %s",
                    (b"x" * 36, enrollment_id),
                )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.totp_mfa_enrollments
                SET enrollment_state = 'active',
                    activated_at = statement_timestamp(),
                    activated_by_actor_id = %s,
                    activation_provenance = 'correct-challenge'
                WHERE enrollment_id = %s
                """,
                (lifecycle_actor_id, enrollment_id),
            )
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.totp_mfa_enrollments
                SET enrollment_state = 'disabled',
                    disabled_at = statement_timestamp(),
                    disabled_by_actor_id = %s,
                    disablement_provenance = 'authorized-disablement'
                WHERE enrollment_id = %s
                """,
                (lifecycle_actor_id, enrollment_id),
            )
            cursor.execute(
                """
                INSERT INTO app.totp_mfa_enrollments (
                    enrollment_id, actor_id, secret_ciphertext, secret_nonce,
                    key_identifier, protection_algorithm, totp_algorithm, provenance
                ) VALUES (%s, %s, %s, %s, 'key-2', 'aes-256-gcm', 'sha1',
                          'replacement-enrollment')
                """,
                (uuid.uuid4(), actor_id, b"r" * 36, b"q" * 12),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.totp_mfa_enrollments SET enrollment_state = 'active' "
                    "WHERE enrollment_id = %s",
                    (enrollment_id,),
                )
        connection.rollback()

        for statement in (
            sql.SQL("DELETE FROM app.totp_mfa_enrollments"),
            sql.SQL("TRUNCATE app.totp_mfa_enrollments"),
        ):
            with connection.cursor() as cursor:
                cursor.execute("SAVEPOINT totp_enrollment_history_immutability")
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                with connection.cursor() as cursor:
                    cursor.execute(statement)
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK TO SAVEPOINT totp_enrollment_history_immutability")


def test_runtime_has_only_bounded_totp_enrollment_privileges() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    has_table_privilege('prm_runtime', 'app.totp_mfa_enrollments', 'SELECT'),
                    has_table_privilege('prm_runtime', 'app.totp_mfa_enrollments', 'INSERT'),
                    has_table_privilege('prm_runtime', 'app.totp_mfa_enrollments', 'UPDATE'),
                    has_table_privilege('prm_runtime', 'app.totp_mfa_enrollments', 'DELETE'),
                    has_table_privilege('prm_runtime', 'app.totp_mfa_enrollments', 'TRUNCATE'),
                    has_column_privilege(
                        'prm_runtime', 'app.totp_mfa_enrollments', 'secret_ciphertext', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.totp_mfa_enrollments', 'secret_ciphertext', 'UPDATE'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.totp_mfa_enrollments', 'enrollment_state', 'UPDATE'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.totp_mfa_enrollments', 'provenance', 'SELECT'
                    ),
                    has_function_privilege(
                        'prm_runtime', 'app.protect_totp_mfa_enrollment_lifecycle()', 'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.reject_totp_mfa_enrollment_history_destruction()',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (
                False,
                False,
                False,
                False,
                False,
                True,
                False,
                True,
                False,
                False,
                False,
            )


def test_totp_enrollment_migration_refuses_destructive_downgrade() -> None:
    with _temporary_migration_database("prm_totp_downgrade") as migration_url:
        assert _run_alembic("upgrade", "20260819_06").returncode == 0

        result = _run_alembic("downgrade", "20260818_05")

        assert result.returncode != 0
        assert "DB-AUTH-003 TOTP enrollment migration is forward-only" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.totp_mfa_enrollments')")
                assert cursor.fetchone() == ("app.totp_mfa_enrollments",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260819_06",)


def test_browser_sessions_store_only_bounded_protected_lifetime_and_revocation_state() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'app' AND table_name = 'browser_sessions'
                ORDER BY ordinal_position
                """
            )
            assert cursor.fetchall() == [
                ("session_id", "uuid", "NO"),
                ("actor_id", "uuid", "NO"),
                ("token_verifier", "bytea", "NO"),
                ("verifier_algorithm", "text", "NO"),
                ("created_at", "timestamp with time zone", "NO"),
                ("last_activity_at", "timestamp with time zone", "NO"),
                ("idle_expires_at", "timestamp with time zone", "NO"),
                ("absolute_expires_at", "timestamp with time zone", "NO"),
                ("creation_provenance", "text", "NO"),
                ("revoked_at", "timestamp with time zone", "YES"),
                ("revoked_by_actor_id", "uuid", "YES"),
                ("revocation_reason", "text", "YES"),
                ("revocation_provenance", "text", "YES"),
            ]
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name = 'browser_sessions'
                  AND column_name ~ '(token$|plaintext|cookie|role|capability)'
                """
            )
            assert cursor.fetchall() == []


@pytest.mark.parametrize(
    ("token_verifier", "verifier_algorithm", "creation_provenance"),
    [
        (b"short", "sha256", "local-login"),
        (b"v" * 32, "plaintext", "local-login"),
        (b"v" * 32, "sha256", "   "),
    ],
)
def test_browser_sessions_reject_unprotected_or_incomplete_token_verifiers(
    token_verifier: bytes,
    verifier_algorithm: str,
    creation_provenance: str,
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
                ) VALUES (%s, %s, 'Session Actor', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"session-{actor_id.hex}", f"session-{actor_id.hex}"),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.browser_sessions (
                        session_id, actor_id, token_verifier, verifier_algorithm,
                        creation_provenance
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4(),
                        actor_id,
                        token_verifier,
                        verifier_algorithm,
                        creation_provenance,
                    ),
                )


@pytest.mark.parametrize(
    ("last_activity_delta", "idle_expiry_delta", "absolute_expiry_delta"),
    [
        (-1, 30, 24 * 60),
        (0, 31, 24 * 60),
        (0, 30, 25 * 60),
        (24 * 60, 24 * 60, 24 * 60),
    ],
)
def test_browser_session_creation_rejects_invalid_fixed_lifetime_state(
    last_activity_delta: int,
    idle_expiry_delta: int,
    absolute_expiry_delta: int,
) -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    created_at = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Lifetime Actor', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"lifetime-{actor_id.hex}", f"lifetime-{actor_id.hex}"),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.browser_sessions (
                        session_id, actor_id, token_verifier, verifier_algorithm,
                        created_at, last_activity_at, idle_expires_at,
                        absolute_expires_at, creation_provenance
                    ) VALUES (%s, %s, %s, 'sha256', %s, %s, %s, %s, 'local-login')
                    """,
                    (
                        uuid.uuid4(),
                        actor_id,
                        os.urandom(32),
                        created_at,
                        created_at + timedelta(minutes=last_activity_delta),
                        created_at + timedelta(minutes=idle_expiry_delta),
                        created_at + timedelta(minutes=absolute_expiry_delta),
                    ),
                )


def test_browser_session_creation_rejects_revocation_before_creation() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    created_at = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Revoked Session', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"revoked-session-{actor_id.hex}", f"revoked-{actor_id.hex}"),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.browser_sessions (
                        session_id, actor_id, token_verifier, verifier_algorithm,
                        created_at, last_activity_at, idle_expires_at,
                        absolute_expires_at, creation_provenance, revoked_at,
                        revoked_by_actor_id, revocation_reason, revocation_provenance
                    ) VALUES (
                        %s, %s, %s, 'sha256', %s, %s, %s, %s, 'local-login',
                        %s, %s, 'logout', 'invalid-pre-creation-revocation'
                    )
                    """,
                    (
                        uuid.uuid4(),
                        actor_id,
                        os.urandom(32),
                        created_at,
                        created_at,
                        created_at + timedelta(minutes=30),
                        created_at + timedelta(hours=24),
                        created_at - timedelta(seconds=1),
                        actor_id,
                    ),
                )


def test_browser_session_activity_and_revocation_are_forward_only_and_retain_history() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    operator_id = uuid.uuid4()
    session_id = uuid.uuid4()
    token_verifier = os.urandom(32)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            for account_id, label in ((actor_id, "target"), (operator_id, "operator")):
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'Browser Session', %s, 'active', 'optional',
                              'authorized-account-creation')
                    """,
                    (
                        account_id,
                        f"browser-session-{label}-{account_id.hex}",
                        f"browser-session-{label}",
                    ),
                )
            cursor.execute(
                """
                INSERT INTO app.browser_sessions (
                    session_id, actor_id, token_verifier, verifier_algorithm,
                    creation_provenance
                ) VALUES (%s, %s, %s, 'sha256', 'local-login')
                RETURNING created_at, last_activity_at, idle_expires_at, absolute_expires_at
                """,
                (session_id, actor_id, token_verifier),
            )
            creation_row = cursor.fetchone()
            assert creation_row is not None
            created_at, first_activity_at, first_idle_expiry, absolute_expiry = creation_row
            assert first_activity_at == created_at
            assert first_idle_expiry == created_at + timedelta(minutes=30)
            assert absolute_expiry == created_at + timedelta(hours=24)
        connection.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.browser_sessions (
                        session_id, actor_id, token_verifier, verifier_algorithm,
                        creation_provenance
                    ) VALUES (%s, %s, %s, 'sha256', 'duplicate-verifier')
                    """,
                    (uuid.uuid4(), actor_id, token_verifier),
                )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.browser_sessions
                SET last_activity_at = statement_timestamp()
                WHERE session_id = %s
                RETURNING last_activity_at, idle_expires_at, absolute_expires_at
                """,
                (session_id,),
            )
            activity_row = cursor.fetchone()
            assert activity_row is not None
            last_activity_at, idle_expiry, unchanged_absolute_expiry = activity_row
            assert last_activity_at > first_activity_at
            assert idle_expiry == last_activity_at + timedelta(minutes=30)
            assert unchanged_absolute_expiry == absolute_expiry
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.browser_sessions
                SET revoked_by_actor_id = %s,
                    revocation_reason = 'account_disabled',
                    revocation_provenance = 'authorized-account-disablement'
                WHERE session_id = %s
                RETURNING revoked_at, revoked_by_actor_id, revocation_reason,
                          revocation_provenance
                """,
                (operator_id, session_id),
            )
            revocation_row = cursor.fetchone()
            assert revocation_row is not None
            revoked_at, revoked_by, reason, provenance = revocation_row
            assert revoked_at is not None
            assert revoked_by == operator_id
            assert reason == "account_disabled"
            assert provenance == "authorized-account-disablement"
        connection.commit()

        for statement in (
            sql.SQL("UPDATE app.browser_sessions SET last_activity_at = statement_timestamp()"),
            sql.SQL("UPDATE app.browser_sessions SET revocation_reason = 'logout'"),
            sql.SQL(
                "UPDATE app.browser_sessions SET token_verifier = decode(repeat('00', 32), 'hex')"
            ),
            sql.SQL("DELETE FROM app.browser_sessions"),
            sql.SQL("TRUNCATE app.browser_sessions"),
        ):
            with connection.cursor() as cursor:
                cursor.execute("SAVEPOINT browser_session_history_immutability")
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                with connection.cursor() as cursor:
                    cursor.execute(statement)
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK TO SAVEPOINT browser_session_history_immutability")


def test_browser_session_activity_cannot_revive_an_expired_session() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC) - timedelta(hours=1)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Expired Session', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"expired-session-{actor_id.hex}", f"expired-{actor_id.hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.browser_sessions (
                    session_id, actor_id, token_verifier, verifier_algorithm,
                    created_at, last_activity_at, idle_expires_at,
                    absolute_expires_at, creation_provenance
                ) VALUES (%s, %s, %s, 'sha256', %s, %s, %s, %s, 'local-login')
                """,
                (
                    session_id,
                    actor_id,
                    os.urandom(32),
                    created_at,
                    created_at,
                    created_at + timedelta(minutes=30),
                    created_at + timedelta(hours=24),
                ),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE app.browser_sessions SET last_activity_at = statement_timestamp() "
                    "WHERE session_id = %s",
                    (session_id,),
                )


def test_runtime_has_only_bounded_browser_session_lifecycle_privileges() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    has_table_privilege('prm_runtime', 'app.browser_sessions', 'SELECT'),
                    has_table_privilege('prm_runtime', 'app.browser_sessions', 'INSERT'),
                    has_table_privilege('prm_runtime', 'app.browser_sessions', 'UPDATE'),
                    has_table_privilege('prm_runtime', 'app.browser_sessions', 'DELETE'),
                    has_table_privilege('prm_runtime', 'app.browser_sessions', 'TRUNCATE'),
                    has_column_privilege(
                        'prm_runtime', 'app.browser_sessions', 'token_verifier', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.browser_sessions', 'creation_provenance', 'SELECT'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.browser_sessions', 'token_verifier', 'UPDATE'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.browser_sessions', 'last_activity_at', 'UPDATE'
                    ),
                    has_column_privilege(
                        'prm_runtime', 'app.browser_sessions', 'revocation_reason', 'UPDATE'
                    ),
                    has_function_privilege(
                        'prm_runtime', 'app.protect_browser_session_lifecycle()', 'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.reject_browser_session_history_destruction()',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (
                False,
                False,
                False,
                False,
                False,
                True,
                False,
                False,
                True,
                True,
                False,
                False,
            )


def test_runtime_can_persist_and_advance_bounded_browser_session_lifecycle() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    actor_id = uuid.uuid4()
    session_id = uuid.uuid4()
    token_verifier = os.urandom(32)
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Runtime Session', %s, 'active', 'optional',
                          'authorized-account-creation')
                """,
                (actor_id, f"runtime-session-{actor_id.hex}", f"runtime-{actor_id.hex}"),
            )
        connection.commit()

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.browser_sessions (
                    session_id, actor_id, token_verifier, verifier_algorithm,
                    creation_provenance
                ) VALUES (%s, %s, %s, 'sha256', 'runtime-local-login')
                RETURNING created_at, last_activity_at, idle_expires_at, absolute_expires_at
                """,
                (session_id, actor_id, token_verifier),
            )
            created_at, last_activity_at, idle_expires_at, absolute_expires_at = cast(
                tuple[datetime, datetime, datetime, datetime], cursor.fetchone()
            )
            assert last_activity_at == created_at
            assert idle_expires_at == created_at + timedelta(minutes=30)
            assert absolute_expires_at == created_at + timedelta(hours=24)
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.browser_sessions
                SET last_activity_at = statement_timestamp()
                WHERE token_verifier = %s
                RETURNING last_activity_at, idle_expires_at, absolute_expires_at
                """,
                (token_verifier,),
            )
            advanced_activity, advanced_idle_expiry, fixed_absolute_expiry = cast(
                tuple[datetime, datetime, datetime], cursor.fetchone()
            )
            assert advanced_activity > last_activity_at
            assert advanced_idle_expiry == advanced_activity + timedelta(minutes=30)
            assert fixed_absolute_expiry == absolute_expires_at
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE app.browser_sessions
                SET revoked_by_actor_id = %s,
                    revocation_reason = 'logout',
                    revocation_provenance = 'authenticated-runtime-logout'
                WHERE session_id = %s
                RETURNING revoked_at, revocation_reason
                """,
                (actor_id, session_id),
            )
            revoked_at, revocation_reason = cast(tuple[datetime, str], cursor.fetchone())
            assert revoked_at >= advanced_activity
            assert revocation_reason == "logout"
        connection.commit()


def test_browser_session_migration_refuses_destructive_downgrade() -> None:
    with _temporary_migration_database("prm_browser_session_downgrade") as migration_url:
        assert _run_alembic("upgrade", "20260819_07").returncode == 0

        result = _run_alembic("downgrade", "20260819_06")

        assert result.returncode != 0
        assert "DB-AUTH-004 browser-session migration is forward-only" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.browser_sessions')")
                assert cursor.fetchone() == ("app.browser_sessions",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260819_07",)


def test_account_recovery_audit_storage_is_bounded_immutable_and_secret_free() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name = 'account_recovery_audit_events'
                ORDER BY ordinal_position
                """
            )
            assert [row[0] for row in cursor.fetchall()] == [
                "event_id",
                "actor_id",
                "target_actor_id",
                "occurred_at",
                "correlation_id",
                "recovery_mode",
                "procedure_identity",
                "reason",
                "outcome",
                "previous_state",
                "resulting_state",
                "password_changed",
                "mfa_disabled",
                "recovery_code_consumed",
                "sessions_revoked",
            ]
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'app'
                  AND table_name = 'account_recovery_audit_events'
                  AND column_name ~ '(password|verifier|ciphertext|nonce|token|candidate)'
                """
            )
            assert cursor.fetchall() == [("password_changed",)]


def test_account_recovery_functions_are_the_only_runtime_password_and_audit_boundary() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    has_column_privilege(
                        'prm_runtime', 'app.password_credentials',
                        'verifier_encoding', 'UPDATE'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.account_recovery_audit_events', 'INSERT'
                    ),
                    has_sequence_privilege(
                        'prm_runtime', 'app.account_recovery_audit_events_event_id_seq', 'USAGE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.perform_account_recovery(uuid,uuid,uuid,text,text,text,text,text,jsonb,boolean,uuid)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'prm_runtime',
                        'app.record_account_recovery_rejection(uuid,uuid,timestamptz,uuid,text,text,text)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (False, False, False, True, True)
            cursor.execute(
                """
                SELECT prosecdef, proconfig
                FROM pg_proc
                WHERE oid IN (
                    'app.perform_account_recovery(uuid,uuid,uuid,text,text,text,text,text,jsonb,boolean,uuid)'::regprocedure,
                    'app.record_account_recovery_rejection(uuid,uuid,timestamptz,uuid,text,text,text)'::regprocedure
                )
                ORDER BY proname
                """
            )
            assert cursor.fetchall() == [
                (True, ["search_path=pg_catalog"]),
                (True, ["search_path=pg_catalog"]),
            ]


def test_account_recovery_repository_atomically_resets_password_revokes_sessions_and_audits() -> (
    None
):
    assert _run_alembic("upgrade", "head").returncode == 0
    owner_id = uuid.uuid4()
    target_id = uuid.uuid4()
    session_id = uuid.uuid4()
    initial = PasswordHashService().hash_password("initial-password")
    replacement = PasswordHashService().hash_password("replacement-password")

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            for actor_id, username, policy in (
                (owner_id, "recovery-owner", "required"),
                (target_id, "recovery-manager", "required"),
            ):
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, %s, %s, 'active', %s, 'recovery-test')
                    """,
                    (actor_id, username, username, username, policy),
                )
            cursor.execute(
                """
                INSERT INTO app.password_credentials (
                    actor_id, verifier_encoding, algorithm, work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, %s::jsonb, 'initial-credential')
                """,
                (
                    target_id,
                    initial.verifier_encoding,
                    initial.algorithm,
                    json.dumps(dict(initial.work_factor_metadata)),
                ),
            )
            cursor.execute(
                """
                INSERT INTO app.browser_sessions (
                    session_id, actor_id, token_verifier, verifier_algorithm,
                    creation_provenance
                ) VALUES (%s, %s, %s, 'sha256', 'recovery-test-session')
                """,
                (session_id, target_id, os.urandom(32)),
            )
        connection.commit()

    request = AccountRecoveryRequest(
        mode="administrative",
        actor_id=owner_id,
        target_actor_id=target_id,
        actor_class="owner",
        target_class="manager",
        request_source="authenticated-owner",
        correlation_id=uuid.uuid4(),
        reason="authorized_account_recovery",
    )
    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as runtime_connection:
        result = PostgresAccountRecoveryRepository(
            connection=cast(AccountRecoveryConnection, runtime_connection),
            recovery_code_verifier=Argon2idRecoveryCodeVerifierProvider(),
        ).recover_atomically(
            request,
            AccountRecoveryMutation(password_credential=replacement),
            None,
        )

    assert result.password_changed
    assert result.sessions_revoked == 1
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT verifier_encoding FROM app.password_credentials WHERE actor_id = %s",
                (target_id,),
            )
            assert cursor.fetchone() == (replacement.verifier_encoding,)
            cursor.execute(
                "SELECT revocation_reason FROM app.browser_sessions WHERE session_id = %s",
                (session_id,),
            )
            assert cursor.fetchone() == ("password_reset",)
            cursor.execute(
                """
                SELECT recovery_mode, outcome, password_changed, sessions_revoked
                FROM app.account_recovery_audit_events
                WHERE correlation_id = %s
                """,
                (request.correlation_id,),
            )
            assert cursor.fetchone() == ("administrative", "completed", True, 1)


def test_owner_recovery_code_consumption_revocation_and_audit_are_one_transaction() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    owner_id = uuid.uuid4()
    set_id = uuid.uuid4()
    code_id = uuid.uuid4()
    session_id = uuid.uuid4()
    candidate = "owner-recovery-code"
    provider = Argon2idRecoveryCodeVerifierProvider()
    verifier = provider.encode(candidate)

    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Recovery Owner', 'recovery-owner', 'active',
                          'required', 'recovery-code-test')
                """,
                (owner_id, f"recovery-code-owner-{owner_id.hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_code_sets (
                    set_id, actor_id, created_by_actor_id, provenance
                ) VALUES (%s, %s, %s, 'protected-owner-enrollment')
                """,
                (set_id, owner_id, owner_id),
            )
            cursor.execute(
                """
                INSERT INTO app.recovery_codes (
                    code_id, set_id, verifier_encoding, algorithm,
                    work_factor_metadata, provenance
                ) VALUES (%s, %s, %s, %s, %s::jsonb, 'protected-owner-enrollment')
                """,
                (
                    code_id,
                    set_id,
                    verifier.verifier_encoding,
                    verifier.algorithm,
                    json.dumps(dict(verifier.work_factor_metadata)),
                ),
            )
            cursor.execute(
                """
                INSERT INTO app.browser_sessions (
                    session_id, actor_id, token_verifier, verifier_algorithm,
                    creation_provenance
                ) VALUES (%s, %s, %s, 'sha256', 'recovery-code-session')
                """,
                (session_id, owner_id, os.urandom(32)),
            )
        connection.commit()

    request = AccountRecoveryRequest(
        mode="recovery_code",
        actor_id=owner_id,
        target_actor_id=owner_id,
        actor_class="owner",
        target_class="owner",
        request_source="password-verified-preauth",
        correlation_id=uuid.uuid4(),
        reason="mfa_recovery",
    )
    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as runtime_connection:
        result = PostgresAccountRecoveryRepository(
            connection=cast(AccountRecoveryConnection, runtime_connection),
            recovery_code_verifier=provider,
        ).recover_atomically(request, AccountRecoveryMutation(), candidate)

    assert result.recovery_code_consumed
    assert result.sessions_revoked == 1
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT consumed_at IS NOT NULL FROM app.recovery_codes WHERE code_id = %s",
                (code_id,),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT revocation_reason FROM app.browser_sessions WHERE session_id = %s",
                (session_id,),
            )
            assert cursor.fetchone() == ("mfa_recovery",)
            cursor.execute(
                """
                SELECT recovery_mode, outcome, recovery_code_consumed, sessions_revoked
                FROM app.account_recovery_audit_events
                WHERE correlation_id = %s
                """,
                (request.correlation_id,),
            )
            assert cursor.fetchone() == ("recovery_code", "completed", True, 1)


def test_account_recovery_audit_history_rejects_change_and_destruction() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0
    target_id = uuid.uuid4()
    with psycopg.connect(_required_url(MIGRATION_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s, %s, 'Audit Target', 'audit-target', 'active',
                          'required', 'recovery-audit-test')
                """,
                (target_id, f"audit-target-{target_id.hex}"),
            )
            cursor.execute(
                """
                INSERT INTO app.account_recovery_audit_events (
                    target_actor_id, correlation_id, recovery_mode,
                    procedure_identity, reason, outcome, previous_state,
                    resulting_state
                ) VALUES (%s, %s, 'emergency', 'controlled-test-procedure',
                          'documented_emergency_recovery', 'rejected', '{"state":"unknown"}',
                          '{"state":"unchanged"}')
                """,
                (target_id, uuid.uuid4()),
            )
        connection.commit()

        for statement in (
            "UPDATE app.account_recovery_audit_events SET reason = 'changed'",
            "DELETE FROM app.account_recovery_audit_events",
            "TRUNCATE app.account_recovery_audit_events",
        ):
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
                with connection.cursor() as cursor:
                    cursor.execute(statement)
            connection.rollback()


def test_account_recovery_migration_refuses_destructive_downgrade() -> None:
    with _temporary_migration_database("prm_account_recovery_downgrade") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0

        result = _run_alembic("downgrade", "20260819_07")

        assert result.returncode != 0
        assert "DB-AUTH-005 account-recovery migration is forward-only" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.account_recovery_audit_events')")
                assert cursor.fetchone() == ("app.account_recovery_audit_events",)
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260819_08",)


def test_protected_bootstrap_migration_rejects_overprivileged_existing_cluster_role() -> None:
    admin_url = _required_url(ADMIN_URL_ENV)
    with _temporary_migration_database("prm_bootstrap_role_precondition") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("ALTER ROLE prm_bootstrap SUPERUSER")

            result = _run_alembic("upgrade", "head")

            assert result.returncode != 0
            assert "safe attributes and only bounded CONNECT authority" in result.stderr
            with psycopg.connect(migration_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version_num FROM alembic_version")
                    assert cursor.fetchone() == ("20260819_08",)
                    cursor.execute(
                        "SELECT to_regprocedure(%s)",
                        (
                            "app.establish_initial_owner_bootstrap("
                            "uuid,uuid,uuid,uuid,text,text,text,text,text,jsonb,bytea,bytea,text,"
                            "uuid[],text[],text,jsonb)",
                        ),
                    )
                    assert cursor.fetchone() == (None,)
        finally:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("ALTER ROLE prm_bootstrap NOSUPERUSER")


def test_protected_bootstrap_migration_requires_existing_cluster_role_before_schema_change() -> (
    None
):
    admin_url = _required_url(ADMIN_URL_ENV)
    with _temporary_migration_database("prm_bootstrap_missing_role") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER ROLE prm_bootstrap RENAME TO prm_bootstrap_temporarily_absent"
                    )

            result = _run_alembic("upgrade", "head")

            assert result.returncode != 0
            assert "prm_bootstrap role must exist before migration" in result.stderr
            with psycopg.connect(migration_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version_num FROM alembic_version")
                    assert cursor.fetchone() == ("20260819_08",)
                    cursor.execute(
                        "SELECT to_regprocedure(%s)",
                        ("app.begin_initial_owner_bootstrap_attempt(uuid,uuid)",),
                    )
                    assert cursor.fetchone() == (None,)
        finally:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER ROLE prm_bootstrap_temporarily_absent RENAME TO prm_bootstrap"
                    )


def test_protected_bootstrap_migration_rejects_preexisting_object_privilege() -> None:
    with _temporary_migration_database("prm_bootstrap_preexisting_acl") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("GRANT SELECT ON app.user_accounts TO prm_bootstrap")
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode != 0
        assert "only bounded CONNECT authority" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260819_08",)
                cursor.execute(
                    "SELECT to_regprocedure(%s)",
                    ("app.begin_initial_owner_bootstrap_attempt(uuid,uuid)",),
                )
                assert cursor.fetchone() == (None,)


def test_protected_bootstrap_migration_rejects_public_table_authority() -> None:
    with _temporary_migration_database("prm_bootstrap_public_table_acl") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("GRANT SELECT ON app.user_accounts TO PUBLIC")
            connection.commit()

        result = _run_alembic("upgrade", "head")

        _assert_bootstrap_authority_rejection_before_mutation(
            migration_url=migration_url,
            result=result,
            expected_error="safe attributes and only bounded CONNECT authority",
        )


def test_protected_bootstrap_migration_rejects_unsafe_role_membership() -> None:
    admin_url = _required_url(ADMIN_URL_ENV)
    marker_role = f"prm_bootstrap_marker_{uuid.uuid4().hex}"
    with _temporary_migration_database("prm_bootstrap_membership") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(marker_role)))
                    cursor.execute(
                        sql.SQL("GRANT {} TO prm_bootstrap").format(sql.Identifier(marker_role))
                    )

            result = _run_alembic("upgrade", "head")

            assert result.returncode != 0
            assert "safe attributes and only bounded CONNECT authority" in result.stderr
            with psycopg.connect(migration_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version_num FROM alembic_version")
                    assert cursor.fetchone() == ("20260819_08",)
        finally:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("REVOKE {} FROM prm_bootstrap").format(sql.Identifier(marker_role))
                    )
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(marker_role)))


def test_protected_bootstrap_migration_rejects_target_database_ownership() -> None:
    with _temporary_migration_database("prm_bootstrap_ownership") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("ALTER SCHEMA app OWNER TO prm_bootstrap")
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode != 0
        assert "safe attributes and only bounded CONNECT authority" in result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260819_08",)


def _assert_bootstrap_authority_rejection_before_mutation(
    *,
    migration_url: str,
    result: subprocess.CompletedProcess[str],
    expected_error: str,
) -> None:
    assert result.returncode != 0
    assert expected_error in result.stderr
    password = urlsplit(migration_url).password
    assert password
    assert password not in result.stdout
    assert password not in result.stderr
    with psycopg.connect(migration_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == ("20260819_08",)
            cursor.execute(
                """
                SELECT
                    to_regprocedure('app.begin_initial_owner_bootstrap_attempt(uuid,uuid)'),
                    to_regprocedure(
                        'app.establish_initial_owner_bootstrap('
                        'uuid,uuid,uuid,uuid,text,text,text,text,text,jsonb,bytea,bytea,text,'
                        'uuid[],text[],text,jsonb)'
                    )
                """
            )
            assert cursor.fetchone() == (None, None)


def _create_large_object(connection: psycopg.Connection[tuple[object, ...]]) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT lo_create(0)")
        row = cursor.fetchone()
        assert row is not None
        large_object_oid = row[0]
        assert isinstance(large_object_oid, int)
    connection.commit()
    return large_object_oid


def _bootstrap_has_large_object_acl_authority(
    connection: psycopg.Connection[tuple[object, ...]], large_object_oid: int
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_largeobject_metadata AS large_object
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        large_object.lomacl,
                        pg_catalog.acldefault('L', large_object.lomowner)
                    )
                ) AS privilege
                WHERE large_object.oid = %s
                  AND (
                      privilege.grantee = 0
                      OR pg_catalog.pg_has_role(
                          'prm_bootstrap', privilege.grantee, 'USAGE'
                      )
                      OR pg_catalog.pg_has_role(
                          'prm_bootstrap', privilege.grantee, 'MEMBER'
                      )
                  )
            )
            """,
            (large_object_oid,),
        )
        row = cursor.fetchone()
        assert row is not None
        return row[0] is True


def test_protected_bootstrap_migration_accepts_large_object_without_bootstrap_authority() -> None:
    with _temporary_migration_database("prm_bootstrap_clean_large_object") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            large_object_oid = _create_large_object(connection)
            assert not _bootstrap_has_large_object_acl_authority(connection, large_object_oid)

        result = _run_alembic("upgrade", "head")

        assert result.returncode == 0, result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260825_20",)


def test_customer_migration_accepts_a_malformed_revision_15_email_domain() -> None:
    with _temporary_migration_database("prm_customer_legacy_email") as migration_url:
        assert _run_alembic("upgrade", "20260824_15").returncode == 0
        actor_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'Legacy Customer Import', 'legacy-import',
                              'active', 'optional', 'migration-regression')
                    """,
                    (actor_id, f"legacy-customer-{actor_id.hex}"),
                )
                cursor.execute(
                    """
                    INSERT INTO app.customers (
                        id, legal_name, email_address, created_by, updated_by
                    ) VALUES (%s, 'Legacy Email Customer', 'user@a..com', %s, %s)
                    """,
                    (customer_id, actor_id, actor_id),
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode == 0, result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT customer.email_address, match_key.match_digest
                    FROM app.customers AS customer
                    JOIN app.customer_email_match_keys AS match_key
                      ON match_key.customer_id = customer.id
                    WHERE customer.id = %s
                    """,
                    (customer_id,),
                )
                row = cursor.fetchone()
        assert row is not None
        assert row[0] == "user@a..com"
        assert isinstance(row[1], str) and len(row[1]) == 32


def test_protected_bootstrap_migration_rejects_large_object_ownership() -> None:
    with _temporary_migration_database("prm_bootstrap_large_object_owner") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            large_object_oid = _create_large_object(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER LARGE OBJECT {} OWNER TO prm_bootstrap").format(
                        sql.Literal(large_object_oid)
                    )
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        _assert_bootstrap_authority_rejection_before_mutation(
            migration_url=migration_url,
            result=result,
            expected_error="safe attributes and only bounded CONNECT authority",
        )


def test_protected_bootstrap_migration_rejects_direct_large_object_acl_authority() -> None:
    with _temporary_migration_database("prm_bootstrap_large_object_acl") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            large_object_oid = _create_large_object(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT SELECT ON LARGE OBJECT {} TO prm_bootstrap").format(
                        sql.Literal(large_object_oid)
                    )
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        _assert_bootstrap_authority_rejection_before_mutation(
            migration_url=migration_url,
            result=result,
            expected_error="safe attributes and only bounded CONNECT authority",
        )


def test_protected_bootstrap_migration_rejects_effective_large_object_role_authority() -> None:
    admin_url = _required_url(ADMIN_URL_ENV)
    marker_role = f"prm_bootstrap_large_object_{uuid.uuid4().hex}"
    with _temporary_migration_database("prm_bootstrap_large_object_inherited") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(admin_url, database)
        large_object_oid: int | None = None
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(marker_role)))
                    cursor.execute(
                        sql.SQL("GRANT {} TO prm_bootstrap WITH INHERIT TRUE, SET TRUE").format(
                            sql.Identifier(marker_role)
                        )
                    )
            with psycopg.connect(admin_target_url) as connection:
                large_object_oid = _create_large_object(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("GRANT SELECT ON LARGE OBJECT {} TO {}").format(
                            sql.Literal(large_object_oid), sql.Identifier(marker_role)
                        )
                    )
                connection.commit()
                assert _bootstrap_has_large_object_acl_authority(connection, large_object_oid)

            result = _run_alembic("upgrade", "head")

            _assert_bootstrap_authority_rejection_before_mutation(
                migration_url=migration_url,
                result=result,
                expected_error="safe attributes and only bounded CONNECT authority",
            )
        finally:
            if large_object_oid is not None:
                with psycopg.connect(admin_target_url, autocommit=True) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("REVOKE ALL ON LARGE OBJECT {} FROM {}").format(
                                sql.Literal(large_object_oid), sql.Identifier(marker_role)
                            )
                        )
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("REVOKE {} FROM prm_bootstrap").format(sql.Identifier(marker_role))
                    )
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(marker_role)))


def test_protected_bootstrap_migration_rejects_public_large_object_authority() -> None:
    with _temporary_migration_database("prm_bootstrap_large_object_public") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url) as connection:
            large_object_oid = _create_large_object(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT UPDATE ON LARGE OBJECT {} TO PUBLIC").format(
                        sql.Literal(large_object_oid)
                    )
                )
            connection.commit()
            assert _bootstrap_has_large_object_acl_authority(connection, large_object_oid)

        result = _run_alembic("upgrade", "head")

        _assert_bootstrap_authority_rejection_before_mutation(
            migration_url=migration_url,
            result=result,
            expected_error="safe attributes and only bounded CONNECT authority",
        )


def test_protected_bootstrap_migration_fails_closed_when_large_object_state_is_unprovable() -> None:
    with _temporary_migration_database("prm_bootstrap_large_object_unprovable") as migration_url:
        assert _run_alembic("upgrade", "20260819_08").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        admin_target_url = _url_with_database(_required_url(ADMIN_URL_ENV), database)
        with psycopg.connect(admin_target_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "ALTER DATABASE {} SET prm.test_force_large_object_authority_query_error "
                        "TO 'force-query-error'"
                    ).format(sql.Identifier(database))
                )

        result = _run_alembic("upgrade", "head")

        _assert_bootstrap_authority_rejection_before_mutation(
            migration_url=migration_url,
            result=result,
            expected_error="large-object authority state could not be proven safe",
        )


def _execute_atomic_owner_bootstrap(
    connection: psycopg.Connection[tuple[object, ...]],
) -> uuid.UUID:
    actor_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    code_ids = [uuid.uuid4() for _ in range(10)]
    verifiers = [
        f"$argon2id$v=19$m=65536,t=3,p=4$bootstrap-salt-{index}$bootstrap-hash-{index}"
        for index in range(10)
    ]
    work_factors = json.dumps({"memory_cost": 65536, "time_cost": 3, "parallelism": 4})
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app.begin_initial_owner_bootstrap_attempt(%s, %s)",
            (actor_id, correlation_id),
        )
        assert cursor.fetchone() == (True,)
        cursor.execute(
            """
            SELECT app.establish_initial_owner_bootstrap(
                %s, %s, %s, %s, %s, %s, %s, %s, 'argon2id', %s::jsonb,
                %s, %s, %s, %s::uuid[], %s::text[], 'argon2id', %s::jsonb
            )
            """,
            (
                actor_id,
                correlation_id,
                uuid.uuid4(),
                uuid.uuid4(),
                "initial-owner",
                "Initial Owner",
                "initial-owner",
                "$argon2id$v=19$m=65536,t=3,p=4$password-salt$password-hash",
                work_factors,
                b"c" * 36,
                b"n" * 12,
                "bootstrap-test-key",
                code_ids,
                verifiers,
                work_factors,
            ),
        )
        assert cursor.fetchone() == (True,)
    return actor_id


def test_bootstrap_identity_atomically_persists_complete_owner_and_permanently_loses_mutation() -> (
    None
):
    with _temporary_migration_database("prm_atomic_bootstrap") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            actor_id = _execute_atomic_owner_bootstrap(bootstrap_connection)
            bootstrap_connection.commit()
            with bootstrap_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT app.begin_initial_owner_bootstrap_attempt(%s, %s)",
                    (uuid.uuid4(), uuid.uuid4()),
                )
                assert cursor.fetchone() == (False,)
            bootstrap_connection.commit()

        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                for table_name, expected_count in (
                    ("user_accounts", 1),
                    ("password_credentials", 1),
                    ("totp_mfa_enrollments", 1),
                    ("recovery_code_sets", 1),
                    ("recovery_codes", 10),
                    ("initial_owner_bootstrap_closure", 1),
                    ("initial_owner_bootstrap_audit_events", 2),
                ):
                    cursor.execute(
                        sql.SQL("SELECT count(*) FROM app.{}").format(sql.Identifier(table_name))
                    )
                    assert cursor.fetchone() == (expected_count,)
                cursor.execute(
                    "SELECT enrollment_state FROM app.totp_mfa_enrollments WHERE actor_id = %s",
                    (actor_id,),
                )
                assert cursor.fetchone() == ("active",)
                cursor.execute(
                    """
                    SELECT
                        has_function_privilege(
                            'prm_bootstrap',
                            'app.begin_initial_owner_bootstrap_attempt(uuid, uuid)', 'EXECUTE'
                        ),
                        has_function_privilege(
                            'prm_bootstrap',
                            'app.establish_initial_owner_bootstrap('
                            'uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb, '
                            'bytea, bytea, text, uuid[], text[], text, jsonb)',
                            'EXECUTE'
                        ),
                        has_table_privilege('prm_bootstrap', 'app.user_accounts', 'SELECT'),
                        has_table_privilege('prm_bootstrap', 'app.user_accounts', 'INSERT')
                    """
                )
                assert cursor.fetchone() == (True, False, False, False)
                cursor.execute(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'app'
                      AND CASE
                          WHEN relation.relkind = 'S' THEN has_sequence_privilege(
                              'prm_bootstrap', relation.oid, 'USAGE,SELECT,UPDATE'
                          )
                          ELSE has_table_privilege(
                              'prm_bootstrap', relation.oid,
                              'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                          )
                      END
                    """
                )
                assert cursor.fetchone() == (0,)
                cursor.execute(
                    """
                    SELECT
                        has_database_privilege(
                            'prm_bootstrap', current_database(), 'CREATE,TEMP'
                        ),
                        has_schema_privilege('prm_bootstrap', 'app', 'CREATE')
                    """
                )
                assert cursor.fetchone() == (False, False)


def test_bootstrap_acknowledgement_rollback_removes_every_effect_and_preserves_one_time_grant() -> (
    None
):
    with _temporary_migration_database("prm_bootstrap_rollback") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            _execute_atomic_owner_bootstrap(bootstrap_connection)
            bootstrap_connection.rollback()

        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                for table_name in (
                    "user_accounts",
                    "password_credentials",
                    "totp_mfa_enrollments",
                    "recovery_code_sets",
                    "recovery_codes",
                    "initial_owner_bootstrap_closure",
                    "initial_owner_bootstrap_audit_events",
                ):
                    cursor.execute(
                        sql.SQL("SELECT count(*) FROM app.{}").format(sql.Identifier(table_name))
                    )
                    assert cursor.fetchone() == (0,)
                cursor.execute(
                    """
                    SELECT has_function_privilege(
                        'prm_bootstrap',
                        'app.establish_initial_owner_bootstrap('
                        'uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb, '
                        'bytea, bytea, text, uuid[], text[], text, jsonb)',
                        'EXECUTE'
                    )
                    """
                )
                assert cursor.fetchone() == (True,)


def _bootstrap_service_request() -> BootstrapRequest:
    return BootstrapRequest(
        actor_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        enrollment_id=uuid.uuid4(),
        recovery_set_id=uuid.uuid4(),
        recovery_code_ids=tuple(uuid.uuid4() for _ in range(10)),
        username="initial-owner",
        display_name="Initial Owner",
        audit_name="initial-owner",
    )


def test_real_postgresql_production_service_pseudo_tty_failure_rolls_back_every_effect() -> None:
    class DeterministicFactory:
        def create(
            self, *, request: BootstrapRequest, normalized_password: str
        ) -> BootstrapSecretBundle:
            del request
            assert normalized_password == "correct horse battery staple"
            return BootstrapSecretBundle(
                password_verifier=("$argon2id$v=19$m=65536,t=3,p=4$password-salt$password-hash"),
                password_algorithm="argon2id",
                password_work_factors={
                    "memory_cost": 65536,
                    "time_cost": 3,
                    "parallelism": 4,
                },
                totp_plaintext="TOTP-SECRET",
                totp_ciphertext=b"c" * 36,
                totp_nonce=b"n" * 12,
                totp_key_identifier="bootstrap-test-key",
                recovery_plaintexts=tuple(f"recovery-{index}" for index in range(10)),
                recovery_verifiers=tuple(
                    f"$argon2id$v=19$m=65536,t=3,p=4$salt-{index}$hash-{index}"
                    for index in range(10)
                ),
                recovery_algorithm="argon2id",
                recovery_work_factors={
                    "memory_cost": 65536,
                    "time_cost": 3,
                    "parallelism": 4,
                },
            )

        def verify_totp(self, bundle: BootstrapSecretBundle, candidate: str) -> bool:
            del bundle
            return candidate == "123456"

    with _temporary_migration_database("prm_bootstrap_pseudo_tty_rollback") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        master_fd, slave_fd = os.openpty()
        terminal = object.__new__(bootstrap_cli.ControllingTerminal)
        terminal._fd = slave_fd
        transcript = bytearray()
        driver_failures: list[BaseException] = []

        def respond(marker: bytes, response: bytes) -> None:
            while marker not in transcript:
                transcript.extend(os.read(master_fd, 4096))
            os.write(master_fd, response + b"\n")

        def drive_terminal() -> None:
            try:
                respond(b"Initial Owner password: ", b"correct horse battery staple")
                respond(b"Confirm password: ", b"correct horse battery staple")
                respond(b"Enter the current six-digit code: ", b"123456")
                respond(b"to commit: ", b"not acknowledged")
            except BaseException as error:
                driver_failures.append(error)

        driver = threading.Thread(target=drive_terminal)
        driver.start()
        try:
            with psycopg.connect(bootstrap_url) as bootstrap_connection:
                service = InitialOwnerBootstrapService(
                    repository=PostgresInitialOwnerBootstrapRepository(
                        cast(InitialOwnerBootstrapClosureConnection, bootstrap_connection)
                    ),
                    terminal=terminal,
                    password_policy=BootstrapPasswordPolicy(blocked_passwords=set()),
                    material_factory=DeterministicFactory(),
                    ceremony_timeout_seconds=30,
                )
                with pytest.raises(BootstrapFailed, match=r"^initial Owner bootstrap failed$"):
                    service.run(_bootstrap_service_request())
        finally:
            driver.join(timeout=5)
            os.close(master_fd)
            os.close(slave_fd)

        assert not driver.is_alive()
        assert driver_failures == []
        assert b"correct horse battery staple" not in transcript
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                for table_name in (
                    "user_accounts",
                    "password_credentials",
                    "totp_mfa_enrollments",
                    "recovery_code_sets",
                    "recovery_codes",
                    "initial_owner_bootstrap_closure",
                    "initial_owner_bootstrap_audit_events",
                ):
                    cursor.execute(
                        sql.SQL("SELECT count(*) FROM app.{}").format(sql.Identifier(table_name))
                    )
                    assert cursor.fetchone() == (0,)


def test_production_recovery_factory_persists_random_codes_with_independent_salts() -> None:
    fixed_totp_time = 1_700_000_000

    class ConfirmingTerminal:
        recovery_codes: tuple[str, ...] = ()

        def read_password(self) -> str:
            return "correct horse battery staple"

        def present_totp_and_read_code(self, secret: str, *, deadline: float) -> str:
            assert deadline > time.monotonic()
            return TotpService().generate_code(
                TotpSecret.from_base32(secret), at_time=fixed_totp_time
            )

        def present_recovery_codes(self, codes: tuple[str, ...], *, deadline: float) -> None:
            assert deadline > time.monotonic()
            self.recovery_codes = codes

        def read_acknowledgement(self, *, deadline: float) -> str:
            assert deadline > time.monotonic()
            return BOOTSTRAP_ACKNOWLEDGEMENT

    with _temporary_migration_database("prm_bootstrap_production_factory") as migration_url:
        assert _run_alembic("upgrade", "head").returncode == 0
        database = urlsplit(migration_url).path.removeprefix("/")
        bootstrap_url = _url_with_database(_required_url(BOOTSTRAP_URL_ENV), database)
        terminal = ConfirmingTerminal()
        request = _bootstrap_service_request()
        with psycopg.connect(bootstrap_url) as bootstrap_connection:
            service = InitialOwnerBootstrapService(
                repository=PostgresInitialOwnerBootstrapRepository(
                    cast(InitialOwnerBootstrapClosureConnection, bootstrap_connection)
                ),
                terminal=terminal,
                password_policy=BootstrapPasswordPolicy(blocked_passwords=set()),
                material_factory=RealBootstrapMaterialFactory(
                    totp_key=b"k" * 32,
                    totp_key_identifier="bootstrap-production-factory-test",
                    clock=lambda: fixed_totp_time,
                ),
                ceremony_timeout_seconds=120,
            )
            service.run(request)

        assert len(terminal.recovery_codes) == 10
        assert len(set(terminal.recovery_codes)) == 10
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT verifier_encoding, created_at FROM app.recovery_codes")
                stored_rows = cursor.fetchall()
                stored_verifiers = [cast(str, row[0]) for row in stored_rows]
                consumption_time = max(cast(datetime, row[1]) for row in stored_rows) + (
                    timedelta(seconds=1)
                )

        assert len(stored_verifiers) == 10
        salts = [verifier.split("$")[4] for verifier in stored_verifiers]
        assert len(set(salts)) == 10
        verifier_provider = Argon2idRecoveryCodeVerifierProvider()
        assert all(
            sum(verifier_provider.matches(code, verifier) for verifier in stored_verifiers) == 1
            for code in terminal.recovery_codes
        )
        assert all(code not in stored_verifiers for code in terminal.recovery_codes)

        class DatabaseTestAuditSink:
            def __init__(self) -> None:
                self.evidence: list[object] = []

            def record(self, evidence: object) -> None:
                self.evidence.append(evidence)

        runtime_url = _url_with_database(_required_url(RUNTIME_URL_ENV), database)
        with psycopg.connect(runtime_url) as runtime_connection:
            consumer = RecoveryCodeConsumptionService(
                repository=PostgresRecoveryCodeConsumptionRepository(
                    cast(RecoveryCodeConsumptionConnection, runtime_connection)
                ),
                verifier_provider=verifier_provider,
                audit_sink=DatabaseTestAuditSink(),
                clock=lambda: consumption_time,
            )
            consumption = RecoveryCodeConsumptionRequest(
                consuming_actor_id=request.actor_id,
                target_actor_id=request.actor_id,
                set_id=request.recovery_set_id,
                candidate=terminal.recovery_codes[0],
                correlation_id="bootstrap-production-factory-consumption",
                provenance="protected-bootstrap-recovery-test",
            )

            first = consumer.consume(consumption)
            repeated = consumer.consume(consumption)

        assert first.completed is True
        assert first.reason == "code_consumed"
        assert repeated.completed is False
        assert repeated.reason == "code_rejected"


def test_v1_027_upgrade_preserves_v1_022_payment_configuration() -> None:
    """Upgrade revision 16 data without rewriting configured Payment Method identity."""
    with _temporary_migration_database("prm_v1_027_upgrade") as migration_url:
        assert _run_alembic("upgrade", "20260824_16").returncode == 0
        actor_id = uuid.uuid4()
        property_id = uuid.uuid4()
        method_id = uuid.uuid4()
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'V1-027 Upgrade Actor', 'V1-027 Upgrade Actor',
                              'active', 'optional', 'migration-regression')
                    """,
                    (actor_id, f"v1-027-upgrade-{actor_id.hex}"),
                )
                cursor.execute(
                    """
                    INSERT INTO app.properties (id, name, created_by, updated_by)
                    VALUES (%s, 'V1-027 Upgrade Property', %s, %s)
                    """,
                    (property_id, actor_id, actor_id),
                )
                cursor.execute(
                    """
                    INSERT INTO app.payment_methods (
                        id, code, display_name, accepted, created_by, updated_by
                    ) VALUES (%s, 'LEGACY_BANK', 'Legacy bank transfer', true, %s, %s)
                    """,
                    (method_id, actor_id, actor_id),
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode == 0, result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260825_20",)
                cursor.execute(
                    """
                    SELECT id, code, display_name, accepted, created_by, updated_by
                    FROM app.payment_methods
                    WHERE id = %s
                    """,
                    (method_id,),
                )
                assert cursor.fetchone() == (
                    method_id,
                    "LEGACY_BANK",
                    "Legacy bank transfer",
                    True,
                    actor_id,
                    actor_id,
                )
                cursor.execute(
                    """
                    SELECT
                        to_regclass('app.property_services'),
                        to_regclass('app.service_rates'),
                        to_regclass('app.property_service_approval_periods'),
                        to_regclass('app.utility_rates'),
                        to_regclass('app.exchange_rate_records')
                    """
                )
                assert cursor.fetchone() == (
                    "app.property_services",
                    "app.service_rates",
                    "app.property_service_approval_periods",
                    "app.utility_rates",
                    "app.exchange_rate_records",
                )


def test_v1_028_upgrade_preserves_v1_027_exchange_rate_history() -> None:
    """Upgrade revision 17 history into the Property-scoped API without rewriting it."""
    with _temporary_migration_database("prm_v1_028_upgrade") as migration_url:
        assert _run_alembic("upgrade", "20260825_17").returncode == 0
        actor_id = uuid.uuid4()
        property_id = uuid.uuid4()
        rate_id = uuid.uuid4()
        applicable_at = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)
        trace = {
            "usd_amount_cents": 10001,
            "unrounded_payable_khr": "408340.83",
            "payable_khr": 408341,
            "markup_basis_points": 50,
            "rounding": "CEILING_WHOLE_KHR",
        }
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'V1-028 Upgrade Actor', 'V1-028 Upgrade Actor',
                              'active', 'optional', 'migration-regression')
                    """,
                    (actor_id, f"v1-028-upgrade-{actor_id.hex}"),
                )
                cursor.execute(
                    """
                    INSERT INTO app.properties (id, name, created_by, updated_by)
                    VALUES (%s, 'V1-028 Upgrade Property', %s, %s)
                    """,
                    (property_id, actor_id, actor_id),
                )
                cursor.execute(
                    """
                    INSERT INTO app.exchange_rate_records (
                        id, reference_rate_khr_per_usd, markup_basis_points,
                        system_rate_khr_per_usd, rate_source, source_reference,
                        applicable_at, calculation_trace
                    ) VALUES (%s, 4062.500000, 50, 4083, 'ABA_AUTOMATIC',
                              'Preserved V1-027 quote', %s, %s)
                    """,
                    (rate_id, applicable_at, Jsonb(trace)),
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode == 0, result.stderr
        with psycopg.connect(migration_url) as connection:
            row = connection.execute(
                "SELECT * FROM app.list_exchange_rates_for_property(%s, 25, NULL, NULL)",
                (property_id,),
            ).fetchone()
            assert row is not None
            assert row[0] == rate_id
            assert row[1] == Decimal("4062.500000")
            assert row[2] == 4083
            assert row[3] == "ABA_AUTOMATIC"
            assert row[4] == "Preserved V1-027 quote"
            assert row[5] == applicable_at
            assert row[6] == trace


def test_v1_029_upgrade_preserves_v1_028_property_unit_and_customer_data() -> None:
    """Upgrade revision 18 without rewriting predecessor identities or granting DML."""
    with _temporary_migration_database("prm_v1_029_upgrade") as migration_url:
        assert _run_alembic("upgrade", "20260825_18").returncode == 0
        actor_id = uuid.uuid4()
        property_id = uuid.uuid4()
        unit_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app.user_accounts (
                        actor_id, normalized_username, display_name, audit_name,
                        lifecycle_state, mfa_policy_class, provenance
                    ) VALUES (%s, %s, 'V1-029 Upgrade Actor', 'V1-029 Upgrade Actor',
                              'active', 'optional', 'migration-regression')
                    """,
                    (actor_id, f"v1-029-upgrade-{actor_id.hex}"),
                )
                cursor.execute(
                    """
                    INSERT INTO app.properties (id, name, created_by, updated_by)
                    VALUES (%s, 'V1-029 Upgrade Property', %s, %s)
                    """,
                    (property_id, actor_id, actor_id),
                )
                cursor.execute(
                    """
                    INSERT INTO app.units (
                        id, property_id, unit_number, floor, unit_type, status,
                        created_by, updated_by
                    ) VALUES (%s, %s, 'UPGRADE-029', '1', 'ONE_BEDROOM',
                              'VACANT', %s, %s)
                    """,
                    (unit_id, property_id, actor_id, actor_id),
                )
                cursor.execute(
                    """
                    INSERT INTO app.customers (
                        id, legal_name, created_by, updated_by
                    ) VALUES (%s, 'V1-029 Upgrade Customer', %s, %s)
                    """,
                    (customer_id, actor_id, actor_id),
                )
            connection.commit()

        result = _run_alembic("upgrade", "head")

        assert result.returncode == 0, result.stderr
        with psycopg.connect(migration_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone() == ("20260825_20",)
                cursor.execute(
                    """
                    SELECT unit.id, unit.property_id, unit.status, customer.id
                    FROM app.units AS unit
                    CROSS JOIN app.customers AS customer
                    WHERE unit.id = %s AND customer.id = %s
                    """,
                    (unit_id, customer_id),
                )
                assert cursor.fetchone() == (unit_id, property_id, "VACANT", customer_id)
                cursor.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM app.reservations),
                        (SELECT count(*) FROM app.deposits),
                        has_table_privilege('prm_runtime', 'app.reservations', 'SELECT'),
                        has_table_privilege('prm_runtime', 'app.reservations', 'INSERT'),
                        has_table_privilege(
                            'prm_runtime', 'app.reservation_commands', 'SELECT'
                        )
                    """
                )
                assert cursor.fetchone() == (0, 0, True, False, False)


def test_v1_030_upgrade_preserves_active_v1_029_reservation_and_deposit() -> None:
    """Upgrade revision 19 without rewriting an active Reservation or its Deposit."""
    with _temporary_migration_database("prm_v1_030_upgrade") as migration_url:
        assert _run_alembic("upgrade", "20260825_19").returncode == 0
        actor_id = uuid.uuid4()
        property_id = uuid.uuid4()
        unit_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        reservation_id = uuid.uuid4()
        deposit_id = uuid.uuid4()
        with psycopg.connect(migration_url) as connection:
            connection.execute(
                """
                INSERT INTO app.user_accounts (
                    actor_id, normalized_username, display_name, audit_name,
                    lifecycle_state, mfa_policy_class, provenance
                ) VALUES (%s,%s,'V1-030 Upgrade Actor','V1-030 Upgrade Actor',
                          'active','optional','migration-regression')
                """,
                (actor_id, f"v1-030-upgrade-{actor_id.hex}"),
            )
            connection.execute(
                """
                INSERT INTO app.properties (id, name, created_by, updated_by)
                VALUES (%s,'V1-030 Upgrade Property',%s,%s)
                """,
                (property_id, actor_id, actor_id),
            )
            connection.execute(
                """
                INSERT INTO app.units (
                    id, property_id, unit_number, floor, unit_type, status,
                    created_by, updated_by
                ) VALUES (%s,%s,'UPGRADE-030','1','ONE_BEDROOM','VACANT',%s,%s)
                """,
                (unit_id, property_id, actor_id, actor_id),
            )
            connection.execute(
                """
                INSERT INTO app.customers (id, legal_name, created_by, updated_by)
                VALUES (%s,'V1-030 Upgrade Customer',%s,%s)
                """,
                (customer_id, actor_id, actor_id),
            )
            business_date_row = connection.execute(
                """
                SELECT timezone(timezone_name, clock_timestamp())::date
                FROM app.properties WHERE id = %s
                """,
                (property_id,),
            ).fetchone()
            assert business_date_row is not None
            business_date = business_date_row[0]
            occurred_at = datetime.now(UTC)
            result = connection.execute(
                """
                SELECT * FROM app.create_reservation(
                    %s,%s,%s,%s,%s,%s,%s,50000,%s,
                    %s,10000,'NORMAL_SUGGESTION',%s,%s,%s,%s,
                    %s,50000,%s,%s,%s,%s
                )
                """,
                (
                    property_id,
                    uuid.uuid4(),
                    "3" * 64,
                    reservation_id,
                    unit_id,
                    customer_id,
                    business_date,
                    business_date + timedelta(days=10),
                    uuid.uuid4(),
                    occurred_at,
                    "Explicitly accepted initial Security Deposit",
                    "reservations.manage",
                    Jsonb(
                        {
                            "agreed_monthly_rent_usd_cents": 50_000,
                            "suggested_rate_basis_points": 2000,
                            "suggested_amount_usd_cents": 10_000,
                        }
                    ),
                    deposit_id,
                    uuid.uuid4(),
                    uuid.uuid4(),
                    occurred_at,
                    actor_id,
                ),
            ).fetchone()
            assert result is not None
            connection.commit()

        upgraded = _run_alembic("upgrade", "head")

        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(migration_url) as connection:
            row = connection.execute(
                """
                SELECT reservation.id, reservation.status, reservation.version,
                       unit.status, deposit.id, deposit.required_usd_cents,
                       (SELECT count(*) FROM app.reservation_lifecycle_events)
                FROM app.reservations AS reservation
                JOIN app.units AS unit ON unit.id = reservation.unit_id
                JOIN app.deposits AS deposit ON deposit.reservation_id = reservation.id
                WHERE reservation.id = %s
                """,
                (reservation_id,),
            ).fetchone()
            assert row == (reservation_id, "ACTIVE", 1, "RESERVED", deposit_id, 50_000, 0)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260825_20",
            )
            assert connection.execute(
                """
                SELECT
                    has_function_privilege(
                        'prm_runtime',
                        'app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)',
                        'EXECUTE'
                    ),
                    has_table_privilege(
                        'prm_runtime', 'app.reservation_lifecycle_events', 'INSERT'
                    )
                """
            ).fetchone() == (True, False)
