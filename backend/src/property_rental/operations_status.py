"""Operations status files and health warnings (V1-059, DL-071 answers 1 to 8 and 17).

The backup job, the off-host copy, the restore test, the migration record and the operations
check each write their own small JSON file in one status directory, so two writers never
overwrite each other. A file is replaced in one step (write, fsync, rename). The files hold only
times, outcomes, fixed codes, backup names and the schema revision: never a Customer detail, a
database address with a password, a key or a token.

`evaluate_warnings` turns the files into the fixed list of warnings that the health page shows
(API-081, UI-093) and that the operations check sends by Telegram (DEPLOY-051). It is a pure
function of the files, the thresholds and the current time, so the page and the alerts always
agree.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

StatusFileName = Literal[
    "backup", "offhost-daily", "offhost-weekly", "restore-test", "migration", "checks"
]
STATUS_FILE_NAMES: Final[tuple[StatusFileName, ...]] = (
    "backup",
    "offhost-daily",
    "offhost-weekly",
    "restore-test",
    "migration",
    "checks",
)
STATUS_SCHEMA_VERSION: Final = 1

# Every warning the system can show. The text is fixed and plain; it never carries data.
WARNING_MESSAGES: Final[dict[str, str]] = {
    "database_unavailable": "The database is not answering.",
    "api_unavailable": "The application is not answering.",
    "backup_failed": "The last backup failed.",
    "backup_stale": "There is no good backup from the last 2 hours.",
    "offhost_daily_overdue": (
        "The daily backup copy to the external drive or second computer is overdue."
    ),
    "offhost_weekly_overdue": "The weekly backup copy kept outside the building is overdue.",
    "offhost_copy_failed": "The last backup copy to another place failed.",
    "restore_test_failed": "The last restore test failed.",
    "restore_test_overdue": "A restore test is due (every 3 months and before every release).",
    "scheduled_job_repeated_failure": "A scheduled job failed more than once.",
    "low_disk_space": "Disk space is low.",
    "migration_failed": "The last database update (migration) failed.",
    "tls_certificate_expiring": "The security certificate expires soon.",
    "tls_certificate_unreadable": "The security certificate cannot be read.",
    "operations_check_stale": "The health checks have not run in the last 15 minutes.",
    "telegram_not_configured": "Telegram alerts are not set up yet.",
    "telegram_delivery_failed": "The last Telegram alert could not be sent.",
}
# Warnings that are not sent by Telegram: they are about Telegram itself, or they mean the
# check that sends the alerts is not running.
PAGE_ONLY_WARNINGS: Final = frozenset(
    {"operations_check_stale", "telegram_not_configured", "telegram_delivery_failed"}
)


class StatusFileError(ValueError):
    """A status file is missing its fields or is not this system's status file."""


@dataclass(frozen=True, slots=True)
class WarningThresholds:
    """How old each record may be before it is a warning (decided by Claude, V1-059)."""

    backup_max_age: timedelta = timedelta(hours=2)
    offhost_daily_max_age: timedelta = timedelta(hours=50)
    offhost_weekly_max_age: timedelta = timedelta(days=8)
    restore_test_max_age: timedelta = timedelta(days=92)
    check_max_age: timedelta = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class HealthWarning:
    """One warning of the health page."""

    code: str
    message: str
    critical: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_time(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("status times must carry a time zone")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment


def write_status(directory: Path, name: StatusFileName, record: Mapping[str, object]) -> None:
    """Replace one status file in one step."""
    if name not in STATUS_FILE_NAMES:
        raise StatusFileError("unknown status file")
    if not directory.is_dir():
        directory.mkdir(parents=True, exist_ok=True)
        # Group-readable with the set-group-id bit, whatever the job's umask: the backend reads
        # these files through a read-only mount as a member of the folder's group (runbook 6).
        directory.chmod(0o2750)
    target = directory / f"{name}.json"
    partial = directory / f".{name}.json.partial"
    payload = {"schema_version": STATUS_SCHEMA_VERSION, **record}
    data = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def read_status(directory: Path, name: StatusFileName) -> dict[str, object] | None:
    """One status file, or None when it does not exist yet."""
    path = directory / f"{name}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        raise StatusFileError("a status file cannot be read") from error
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise StatusFileError("a status file is not valid JSON") from error
    if not isinstance(value, dict) or value.get("schema_version") != STATUS_SCHEMA_VERSION:
        raise StatusFileError("a status file has an unknown format")
    return value


def read_all_status(directory: Path) -> dict[str, dict[str, object] | None]:
    """Every status file; one that cannot be read counts as missing."""
    files: dict[str, dict[str, object] | None] = {}
    for name in STATUS_FILE_NAMES:
        try:
            files[name] = read_status(directory, name)
        except StatusFileError:
            files[name] = None
    return files


def _older_than(
    record: Mapping[str, object] | None, field: str, limit: timedelta, now: datetime
) -> bool:
    moment = parse_time(record.get(field)) if record is not None else None
    return moment is None or now - moment > limit


def _failed(record: Mapping[str, object] | None) -> bool:
    return record is not None and record.get("last_outcome") == "failed"


def evaluate_warnings(
    files: Mapping[str, Mapping[str, object] | None],
    now: datetime,
    thresholds: WarningThresholds | None = None,
) -> list[HealthWarning]:
    """The warnings the files show at `now`, in the fixed order of WARNING_MESSAGES."""
    limits = thresholds or WarningThresholds()
    backup = files.get("backup")
    daily = files.get("offhost-daily")
    weekly = files.get("offhost-weekly")
    restore = files.get("restore-test")
    migration = files.get("migration")
    checks = files.get("checks")

    codes: set[str] = set()
    if _failed(backup):
        codes.add("backup_failed")
    if _older_than(backup, "last_success_at", limits.backup_max_age, now):
        codes.add("backup_stale")
    if _failed(daily) or _failed(weekly):
        codes.add("offhost_copy_failed")
    if _older_than(daily, "last_success_at", limits.offhost_daily_max_age, now):
        codes.add("offhost_daily_overdue")
    if _older_than(weekly, "last_success_at", limits.offhost_weekly_max_age, now):
        codes.add("offhost_weekly_overdue")
    if _failed(restore):
        codes.add("restore_test_failed")
    if _older_than(restore, "last_success_at", limits.restore_test_max_age, now):
        codes.add("restore_test_overdue")
    if _failed(migration):
        codes.add("migration_failed")

    if _older_than(checks, "checked_at", limits.check_max_age, now):
        codes.add("operations_check_stale")
    elif checks is not None:
        found = checks.get("found_warnings")
        if isinstance(found, list):
            codes.update(
                code
                for code in found
                if isinstance(code, str)
                and code in WARNING_MESSAGES
                and code not in {"operations_check_stale"}
            )
        telegram = checks.get("telegram")
        if isinstance(telegram, dict):
            if telegram.get("configured") is not True:
                codes.add("telegram_not_configured")
            elif telegram.get("last_delivery_outcome") == "failed":
                codes.add("telegram_delivery_failed")

    return [
        HealthWarning(code=code, message=message, critical=code not in PAGE_ONLY_WARNINGS)
        for code, message in WARNING_MESSAGES.items()
        if code in codes
    ]
