"""The production operations configuration (V1-059, DL-071 answers 1 to 8 and 17).

`config/deployment/production-operations.json` holds paths, hosts and limits only; every secret
is a file path under `/run/secrets/`. `scripts/validate-deployment-config.py` checks the
committed file against DL-071; this module reads it for the backup job and the operations check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from property_rental.operations_status import WarningThresholds


class OperationsConfigError(ValueError):
    """The operations configuration is missing a field or has a wrong value."""


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    api_host: str
    bot_token_file: Path
    chat_ids_file: Path
    recipients: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationsConfig:
    backup_directory: Path
    backup_database_url_file: Path
    backup_encryption_key_file: Path
    restore_test_interval: timedelta
    status_directory: Path
    telegram: TelegramConfig
    repeat_interval: timedelta
    readiness_url: str | None
    tls_certificate_file: Path | None
    tls_warning: timedelta
    disk_paths: tuple[Path, ...]
    disk_minimum_free_percent: float
    disk_minimum_free_bytes: int
    log_directory: Path
    log_retention: timedelta

    @property
    def thresholds(self) -> WarningThresholds:
        return WarningThresholds(restore_test_max_age=self.restore_test_interval)


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OperationsConfigError(f"{name} must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OperationsConfigError(f"{name} must be text")
    return value


def _path(value: object, name: str) -> Path:
    path = Path(_text(value, name))
    if not path.is_absolute():
        raise OperationsConfigError(f"{name} must be an absolute path")
    return path


def _number(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OperationsConfigError(f"{name} must be a positive whole number")
    return value


def load_operations_config(path: Path) -> OperationsConfig:
    """Read the configuration; refuse a file that does not have every field."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OperationsConfigError("the operations configuration cannot be read") from error
    root = _object(document, "configuration")
    backup = _object(root.get("backup"), "backup")
    alerts = _object(root.get("alerts"), "alerts")
    telegram = _object(alerts.get("telegram"), "alerts.telegram")
    logs = _object(root.get("logs"), "logs")
    recipients = telegram.get("recipients")
    if not isinstance(recipients, list) or not all(isinstance(r, str) for r in recipients):
        raise OperationsConfigError("alerts.telegram.recipients must be a list of names")
    disk_paths = alerts.get("disk_paths")
    if not isinstance(disk_paths, list):
        raise OperationsConfigError("alerts.disk_paths must be a list")
    readiness_url = alerts.get("readiness_url")
    certificate = alerts.get("tls_certificate_file")
    return OperationsConfig(
        backup_directory=_path(backup.get("directory"), "backup.directory"),
        backup_database_url_file=_path(backup.get("database_url_file"), "backup.database_url_file"),
        backup_encryption_key_file=_path(
            backup.get("encryption_key_file"), "backup.encryption_key_file"
        ),
        restore_test_interval=timedelta(
            days=_number(backup.get("restore_test_interval_days"), "restore test interval")
        ),
        status_directory=_path(root.get("status_directory"), "status_directory"),
        telegram=TelegramConfig(
            api_host=_text(telegram.get("api_host"), "alerts.telegram.api_host"),
            bot_token_file=_path(telegram.get("bot_token_file"), "bot_token_file"),
            chat_ids_file=_path(telegram.get("chat_ids_file"), "chat_ids_file"),
            recipients=tuple(recipients),
        ),
        repeat_interval=timedelta(hours=_number(alerts.get("repeat_hours"), "repeat_hours")),
        readiness_url=None if readiness_url is None else _text(readiness_url, "readiness_url"),
        tls_certificate_file=None
        if certificate is None
        else _path(certificate, "tls_certificate_file"),
        tls_warning=timedelta(days=_number(alerts.get("tls_warning_days"), "tls_warning_days")),
        disk_paths=tuple(_path(item, "alerts.disk_paths") for item in disk_paths),
        disk_minimum_free_percent=float(
            _number(alerts.get("disk_minimum_free_percent"), "disk_minimum_free_percent")
        ),
        disk_minimum_free_bytes=_number(
            alerts.get("disk_minimum_free_gigabytes"), "disk_minimum_free_gigabytes"
        )
        * 1024**3,
        log_directory=_path(logs.get("directory"), "logs.directory"),
        log_retention=timedelta(
            days=_number(logs.get("operational_retention_days"), "operational_retention_days")
        ),
    )
