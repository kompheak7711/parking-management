"""V1-059 production operations configuration checks (DL-071 answers 1 to 8 and 17).

`scripts/validate-deployment-config.py check-examples` refuses an operations configuration that
turns remote access on, adds an outbound host other than Telegram, changes the backup times,
retention or 90-day log rule, puts a secret value in the file, or commits a Telegram token.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from property_rental.operations_config import load_operations_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPOSITORY_ROOT / "config" / "deployment"
VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate-deployment-config.py"


def validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_deployment_config", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operations() -> dict[str, Any]:
    value: dict[str, Any] = json.loads((CONFIG_ROOT / "production-operations.json").read_text())
    return value


def production() -> dict[str, Any]:
    value: dict[str, Any] = json.loads((CONFIG_ROOT / "production.json").read_text())
    return value


def test_the_committed_configuration_passes_and_loads() -> None:
    result = subprocess.run(
        ["python3", str(VALIDATOR), "check-examples"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    config = load_operations_config(CONFIG_ROOT / "production-operations.json")
    assert config.telegram.recipients == ("owner", "manager")
    assert config.log_retention.days == 90
    assert config.restore_test_interval.days == 92


def _set(document: dict[str, Any], path: str, value: object) -> None:
    *parents, last = path.split(".")
    target = document
    for part in parents:
        target = target[part]
    target[last] = value


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("remote_access.enabled", True, "remote access must be off"),
        ("egress_allowlist", ["api.telegram.org", "example.com"], "allowed list"),
        ("egress_allowlist", [], "allowed list"),
        ("backup.interval_minutes", 120, "every 60 minutes"),
        ("backup.retention.hourly_days", 1, "retention"),
        ("backup.never_delete_last_good_copy", False, "last good backup"),
        ("backup.offhost.cloud_storage", True, "no cloud storage"),
        ("backup.restore_test_interval_days", 120, "92 days"),
        ("backup.restore_test_interval_days", 30, "92 days"),
        (
            "backup.database_url_file",
            "/run/secrets/prm_production_runtime_database_url",
            "backup database identity",
        ),
        ("backup.encryption_key_file", "/etc/key", "/run/secrets/prm_production_"),
        ("alerts.telegram.api_host", "telegram.example", "Telegram host"),
        ("alerts.telegram.recipients", ["owner"], "Owner and the Manager"),
        ("alerts.telegram.optional", False, "optional"),
        (
            "alerts.telegram.bot_token_file",
            "/run/secrets/prm_production_application_secret",
            "separate",
        ),
        ("alerts.telegram.bot_token", "x", "direct secret value"),
        ("logs.operational_retention_days", 30, "90 days"),
        ("property_time_zone", "UTC", "Asia/Phnom_Penh"),
    ],
)
def test_a_configuration_that_breaks_dl_071_is_refused(
    path: str, value: object, message: str
) -> None:
    module = validator()
    document = copy.deepcopy(operations())
    _set(document, path, value)
    with pytest.raises(module.ValidationError, match=message):
        module.check_operations(document, production())


def test_a_committed_telegram_token_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = validator()
    (tmp_path / "leak.json").write_text('{"x": "123456789:' + "C" * 35 + '"}', encoding="utf-8")
    monkeypatch.setattr(module, "CONFIG_ROOT", tmp_path)
    with pytest.raises(module.ValidationError, match="never be committed"):
        module.check_no_telegram_token_in_repository_config()


def test_resolved_production_warns_but_passes_without_telegram(tmp_path: Path) -> None:
    module = validator()
    warning = module.check_resolved_operations(tmp_path)
    assert warning is not None and "optional" in warning
    secrets = tmp_path / "run" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "prm_production_telegram_bot_token").write_text("123456789:" + "D" * 35)
    (secrets / "prm_production_telegram_chat_ids").write_text('{"owner":"1","manager":"2"}')
    assert module.check_resolved_operations(tmp_path) is None
