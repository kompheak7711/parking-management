"""Deterministic deployment identity and secret-source scaffold tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
CONFIG_ROOT: Final = REPOSITORY_ROOT / "config" / "deployment"
VALIDATOR: Final = REPOSITORY_ROOT / "scripts" / "validate-deployment-config.py"
DATABASE_TEST_SCRIPT: Final = REPOSITORY_ROOT / "scripts" / "database-test.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _run_database_test_with_fake_tools(
    tmp_path: Path, docker_script: str
) -> subprocess.CompletedProcess[str]:
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    _write_executable(bin_directory / "docker", docker_script)
    _write_executable(
        bin_directory / "uv",
        """
        #!/bin/sh
        exit 0
        """,
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{bin_directory}{os.pathsep}{environment['PATH']}"
    environment["TMPDIR"] = str(tmp_path)
    environment["FAKE_DOCKER_CALLS"] = str(tmp_path / "docker-calls")
    return subprocess.run(
        [str(DATABASE_TEST_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_validator(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VALIDATOR), *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_development_server_disables_access_logs_that_can_capture_customer_queries() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    backend_dev = re.search(r"^backend-dev:\n\t([^\n]+)$", makefile, re.MULTILINE)

    assert backend_dev is not None
    assert "uvicorn property_rental.app:app" in backend_dev.group(1)
    assert "--no-access-log" in backend_dev.group(1)


def test_deployment_examples_define_seven_distinct_database_identities() -> None:
    contract = json.loads((CONFIG_ROOT / "identity-secret-contract.json").read_text())
    identities = contract["database_identities"]

    assert set(identities) == {
        "runtime",
        "financial",
        "migration",
        "backup",
        "restore",
        "human_admin",
        "bootstrap",
    }
    assert len({identity["database_role"] for identity in identities.values()}) == 7
    assert len({identity["source_key"] for identity in identities.values()}) == 7
    assert "financial orchestration only" in identities["financial"]["standing_access"]
    assert "no standing table mutation" in identities["human_admin"]["standing_access"]
    assert "Connect only by default" in identities["restore"]["standing_access"]
    assert "one-time" in identities["bootstrap"]["standing_access"]


def test_readme_password_file_inventory_matches_env_compose_and_postgres_init() -> None:
    expected_names = {
        "postgres_admin_password",
        "postgres_migration_password",
        "postgres_runtime_password",
        "postgres_financial_password",
        "postgres_backup_password",
        "postgres_restore_password",
        "postgres_human_admin_password",
        "postgres_bootstrap_password",
    }
    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    postgres_init = (REPOSITORY_ROOT / "scripts" / "postgres-init.sh").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    env_names = set(
        re.findall(
            r"^POSTGRES_[A-Z_]+_PASSWORD_FILE=.local/secrets/(postgres_[a-z_]+_password)$",
            env_example,
            re.MULTILINE,
        )
    )
    compose_names = set(re.findall(r"^  (postgres_[a-z_]+_password):$", compose, re.MULTILINE))
    init_source_keys = set(re.findall(r"\$\{(POSTGRES_[A-Z_]+_PASSWORD_FILE):", postgres_init))
    init_names = {
        f"postgres_{source_key.removeprefix('POSTGRES_').removesuffix('_PASSWORD_FILE').lower()}_password"
        for source_key in init_source_keys
    }
    if '"$POSTGRES_PASSWORD"' in postgres_init:
        init_names.add("postgres_admin_password")
    readme_names = set(re.findall(r"`(postgres_[a-z_]+_password)`", readme))

    assert env_names == compose_names == init_names == readme_names == expected_names


def test_deployment_examples_use_separate_environment_bound_protected_sources() -> None:
    result = _run_validator("check-examples")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "deployment configuration valid\n"


def test_production_profile_fails_closed_without_resolved_secret_sources(tmp_path: Path) -> None:
    result = _run_validator(
        "check-profile",
        str(CONFIG_ROOT / "production.json"),
        "--source-root",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "required protected secret source is unavailable" in result.stderr
    assert "postgresql://" not in result.stderr


def test_validator_rejects_direct_secret_values(tmp_path: Path) -> None:
    profile = json.loads((CONFIG_ROOT / "development.json").read_text())
    profile["APP_DATABASE_URL"] = "forbidden-direct-value"
    profile_path = tmp_path / "development.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    result = _run_validator("check-profile", str(profile_path))

    assert result.returncode == 1
    assert "unsupported fields" in result.stderr
    assert "forbidden-direct-value" not in result.stderr


def test_validator_rejects_protected_source_path_traversal(tmp_path: Path) -> None:
    profile = json.loads((CONFIG_ROOT / "development.json").read_text())
    profile["sources"]["APP_SECRET_KEY_FILE"] = "/run/secrets/../prm_development_application_secret"
    profile_path = tmp_path / "development.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    result = _run_validator("check-profile", str(profile_path), "--source-root", str(tmp_path))

    assert result.returncode == 1
    assert "must not traverse" in result.stderr


def test_backup_encryption_source_is_separate_from_database_and_application_sources() -> None:
    contract = json.loads((CONFIG_ROOT / "identity-secret-contract.json").read_text())
    profile = json.loads((CONFIG_ROOT / "test.json").read_text())
    database_source_keys = {
        identity["source_key"] for identity in contract["database_identities"].values()
    }
    application_source_key = contract["secret_inputs"]["ordinary_application"]["source_key"]
    backup_key_source = contract["secret_inputs"]["backup_encryption"]["source_key"]

    assert backup_key_source not in database_source_keys
    assert backup_key_source != application_source_key
    assert profile["sources"][backup_key_source] not in {
        profile["sources"][key] for key in database_source_keys | {application_source_key}
    }


def test_server_secret_source_names_cannot_be_frontend_environment_inputs() -> None:
    contract = json.loads((CONFIG_ROOT / "identity-secret-contract.json").read_text())
    source_keys = {
        identity["source_key"] for identity in contract["database_identities"].values()
    } | {secret["source_key"] for secret in contract["secret_inputs"].values()}
    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "frontend" / "src").glob("**/*")
        if path.is_file()
    )

    assert all(not key.startswith("VITE_") for key in source_keys)
    assert all(key not in frontend_sources for key in source_keys)


def test_postgres_bootstrap_avoids_secret_command_arguments_and_limits_admin_roles() -> None:
    init_script = (REPOSITORY_ROOT / "scripts" / "postgres-init.sh").read_text()

    assert "--set=" + "migration_password=" not in init_script
    assert "\\getenv migration_password POSTGRES_MIGRATION_PASSWORD" in init_script
    assert "GRANT pg_read_all_data TO prm_backup" in init_script
    assert "GRANT pg_monitor TO prm_human_admin" in init_script
    assert "GRANT CONNECT ON DATABASE prm TO prm_restore" in init_script
    assert "GRANT CONNECT ON DATABASE prm TO prm_human_admin" in init_script
    assert "GRANT pg_read_all_data TO prm_restore" not in init_script
    assert "GRANT pg_write_all_data TO prm_human_admin" not in init_script
    assert (
        "CREATE ROLE prm_bootstrap LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
        "NOREPLICATION" in init_script
    )
    assert (
        "CREATE ROLE prm_financial LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOREPLICATION" in init_script
    )
    assert "NOBYPASSRLS CONNECTION LIMIT 1" in init_script
    assert "GRANT CONNECT ON DATABASE prm TO prm_bootstrap" in init_script
    assert "REVOKE ALL ON DATABASE postgres FROM PUBLIC" in init_script
    assert "REVOKE ALL ON DATABASE template1 FROM PUBLIC" in init_script
    assert "GRANT CONNECT, TEMPORARY ON DATABASE postgres TO prm_admin" in init_script
    assert "GRANT CONNECT, TEMPORARY ON DATABASE template1 TO prm_admin" in init_script
    assert "GRANT pg_read_all_data TO prm_bootstrap" not in init_script
    assert "GRANT pg_write_all_data TO prm_bootstrap" not in init_script


def test_protected_bootstrap_migration_requires_preprovisioned_bounded_role() -> None:
    migration = (
        REPOSITORY_ROOT / "backend/migrations/versions/20260820_09_protected_owner_bootstrap.py"
    ).read_text(encoding="utf-8")
    init_script = (REPOSITORY_ROOT / "scripts/postgres-init.sh").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "FROM pg_catalog.pg_roles" in migration
    assert "WHERE rolname = 'prm_bootstrap'" in migration
    assert "bootstrap_role.rolsuper" in migration
    assert "bootstrap_role.rolbypassrls" in migration
    assert "bootstrap_role.rolinherit" in migration
    assert "bootstrap_role.rolconnlimit <> 1" in migration
    assert "pg_catalog.pg_auth_members" in migration
    assert "pg_catalog.pg_shdepend" in migration
    assert "before migration" in migration
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION" in init_script
    assert "unused in every other database" in readme
    assert "connect separately to every connectable" in readme
    assert "no runtime cross-database introspection" in readme
    assert "reset an existing volume" in readme


def test_v1_031_migration_requires_preprovisioned_bounded_financial_role() -> None:
    migration = (
        REPOSITORY_ROOT / "backend/migrations/versions/20260825_21_reservation_deposit_outcomes.py"
    ).read_text(encoding="utf-8")
    init_script = (REPOSITORY_ROOT / "scripts/postgres-init.sh").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert migration.index("prm_financial role must exist before V1-031 migration") < (
        migration.index("CREATE TABLE app.deposit_dispositions")
    )
    assert "financial_role.rolsuper" in migration
    assert "financial_role.rolbypassrls" in migration
    assert "pg_catalog.pg_auth_members" in migration
    assert "pg_catalog.pg_shdepend" in migration
    assert "large_object.lomowner = financial_role.oid" in migration
    assert "safe attributes and only bounded CONNECT authority" in migration
    assert "CREATE ROLE prm_financial" not in migration
    assert "CREATE ROLE prm_financial LOGIN NOINHERIT" in init_script
    assert "existing cluster created before V1-031" in readme
    assert "fails before creating any V1-031 schema" in readme


def test_database_test_secret_files_are_readable_by_native_linux_container_user(
    tmp_path: Path,
) -> None:
    result = _run_database_test_with_fake_tools(
        tmp_path,
        """
        #!/usr/bin/env python3
        import os
        import stat
        import sys

        if "up" in sys.argv:
            source_names = (
                "POSTGRES_ADMIN_PASSWORD_FILE",
                "POSTGRES_MIGRATION_PASSWORD_FILE",
                "POSTGRES_RUNTIME_PASSWORD_FILE",
                "POSTGRES_FINANCIAL_PASSWORD_FILE",
                "POSTGRES_BACKUP_PASSWORD_FILE",
                "POSTGRES_RESTORE_PASSWORD_FILE",
                "POSTGRES_HUMAN_ADMIN_PASSWORD_FILE",
                "POSTGRES_BOOTSTRAP_PASSWORD_FILE",
            )
            source_paths = [os.environ[name] for name in source_names]
            modes = [stat.S_IMODE(os.stat(path).st_mode) for path in source_paths]
            directory_mode = stat.S_IMODE(os.stat(os.path.dirname(source_paths[0])).st_mode)
            sys.exit(0 if all(mode == 0o444 for mode in modes) and directory_mode == 0o700 else 17)
        if "port" in sys.argv:
            print("127.0.0.1:54321")
        """,
    )

    assert result.returncode == 0, result.stderr
    _assert_database_test_explicitly_runs_every_postgresql_migration_suite()


def test_database_test_reports_redacted_container_logs_before_cleanup(tmp_path: Path) -> None:
    result = _run_database_test_with_fake_tools(
        tmp_path,
        """
        #!/usr/bin/env python3
        import os
        import sys
        from pathlib import Path

        action = next((name for name in ("up", "logs", "down") if name in sys.argv), "other")
        with Path(os.environ["FAKE_DOCKER_CALLS"]).open("a", encoding="utf-8") as calls:
            calls.write(f"{action}\\n")
        if action == "up":
            sys.exit(19)
        if action == "logs":
            secret = Path(os.environ["POSTGRES_ADMIN_PASSWORD_FILE"]).read_text().strip()
            print(f"container-init-failure leaked={secret}")
        """,
    )

    calls = (tmp_path / "docker-calls").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 19
    assert calls == ["up", "logs", "down"]
    assert "container-init-failure" in result.stderr
    assert "[REDACTED]" in result.stderr
    assert re.search(r"\b[0-9a-f]{64}\b", result.stderr) is None


def _assert_database_test_explicitly_runs_every_postgresql_migration_suite() -> None:
    source = DATABASE_TEST_SCRIPT.read_text(encoding="utf-8")
    listed = set(
        re.findall(
            r"^  (tests/test_(?:migrations|[a-z0-9_]+_migration)\.py)$",
            source,
            re.MULTILINE,
        )
    )
    backend_root = REPOSITORY_ROOT / "backend"
    expected = {"tests/test_migrations.py"} | {
        path.relative_to(backend_root).as_posix()
        for path in (backend_root / "tests").glob("test_*_migration.py")
    }

    assert listed == expected
    assert "for database_test_file in tests/test_*_migration.py" in source
    assert "PostgreSQL suite is omitted from database-test" in source
    assert "if [ -f tests/test_" not in source
