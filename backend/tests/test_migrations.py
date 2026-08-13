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
    }
    parsed_urls = {
        ADMIN_URL_ENV: urlsplit(admin_url),
        MIGRATION_URL_ENV: urlsplit(migration_url),
        RUNTIME_URL_ENV: urlsplit(runtime_url),
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
        pytest.fail("PostgreSQL bootstrap, migration, and runtime test passwords must be distinct")


@pytest.fixture(scope="session", autouse=True)
def empty_application_database() -> Iterator[None]:
    database = f"prm_test_{uuid.uuid4().hex}"
    admin_url = _required_url(ADMIN_URL_ENV)
    original_migration_url = _required_url(MIGRATION_URL_ENV)
    original_runtime_url = _required_url(RUNTIME_URL_ENV)
    _validate_local_test_urls(admin_url, original_migration_url, original_runtime_url)
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER prm_migrator").format(sql.Identifier(database))
            )
    os.environ[MIGRATION_URL_ENV] = _url_with_database(original_migration_url, database)
    os.environ[RUNTIME_URL_ENV] = _url_with_database(original_runtime_url, database)
    yield
    os.environ[MIGRATION_URL_ENV] = original_migration_url
    os.environ[RUNTIME_URL_ENV] = original_runtime_url


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


def test_runtime_identity_is_distinct_and_cannot_change_schema() -> None:
    assert _run_alembic("upgrade", "head").returncode == 0

    with psycopg.connect(_required_url(RUNTIME_URL_ENV)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT baseline_key FROM app.schema_baseline")
            assert cursor.fetchone() == ("phase-1c",)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE app.forbidden_runtime_ddl (id integer)")


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
