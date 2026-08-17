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


def test_deployment_examples_define_five_distinct_database_identities() -> None:
    contract = json.loads((CONFIG_ROOT / "identity-secret-contract.json").read_text())
    identities = contract["database_identities"]

    assert set(identities) == {"runtime", "migration", "backup", "restore", "human_admin"}
    assert len({identity["database_role"] for identity in identities.values()}) == 5
    assert len({identity["source_key"] for identity in identities.values()}) == 5
    assert "no standing table mutation" in identities["human_admin"]["standing_access"]
    assert "Connect only by default" in identities["restore"]["standing_access"]


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
                "POSTGRES_BACKUP_PASSWORD_FILE",
                "POSTGRES_RESTORE_PASSWORD_FILE",
                "POSTGRES_HUMAN_ADMIN_PASSWORD_FILE",
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
