"""V1-059 operations status files and health warnings (DL-071 answers 1 to 8; DEPLOY-051)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from property_rental.operations_status import (
    PAGE_ONLY_WARNINGS,
    WARNING_MESSAGES,
    StatusFileError,
    evaluate_warnings,
    format_time,
    read_all_status,
    read_status,
    write_status,
)

NOW = datetime(2027, 3, 15, 3, 0, tzinfo=UTC)


def at(age: timedelta) -> str:
    return format_time(NOW - age)


def healthy() -> dict[str, dict[str, object] | None]:
    return {
        "backup": {"last_outcome": "succeeded", "last_success_at": at(timedelta(minutes=30))},
        "offhost-daily": {"last_outcome": "succeeded", "last_success_at": at(timedelta(hours=20))},
        "offhost-weekly": {"last_outcome": "succeeded", "last_success_at": at(timedelta(days=6))},
        "restore-test": {"last_outcome": "succeeded", "last_success_at": at(timedelta(days=30))},
        "migration": {"last_outcome": "succeeded"},
        "checks": {
            "checked_at": at(timedelta(minutes=4)),
            "found_warnings": [],
            "telegram": {"configured": True, "last_delivery_outcome": "sent"},
        },
    }


def codes(files: dict[str, dict[str, object] | None]) -> list[str]:
    return [warning.code for warning in evaluate_warnings(files, NOW)]


def test_a_healthy_system_has_no_warning() -> None:
    assert codes(healthy()) == []


def test_nothing_recorded_yet_shows_every_overdue_record() -> None:
    assert codes({}) == [
        "backup_stale",
        "offhost_daily_overdue",
        "offhost_weekly_overdue",
        "restore_test_overdue",
        "operations_check_stale",
    ]


@pytest.mark.parametrize(
    ("name", "field", "age", "expected"),
    [
        ("backup", "last_success_at", timedelta(hours=2, seconds=1), "backup_stale"),
        (
            "offhost-daily",
            "last_success_at",
            timedelta(hours=50, seconds=1),
            "offhost_daily_overdue",
        ),
        (
            "offhost-weekly",
            "last_success_at",
            timedelta(days=8, seconds=1),
            "offhost_weekly_overdue",
        ),
        ("restore-test", "last_success_at", timedelta(days=92, seconds=1), "restore_test_overdue"),
        ("checks", "checked_at", timedelta(minutes=15, seconds=1), "operations_check_stale"),
    ],
)
def test_each_record_becomes_a_warning_when_too_old(
    name: str, field: str, age: timedelta, expected: str
) -> None:
    files = healthy()
    record = files[name]
    assert record is not None
    record[field] = at(age)
    assert codes(files) == [expected]


def test_failures_and_check_findings_become_warnings() -> None:
    files = healthy()
    for name in ("backup", "offhost-weekly", "restore-test", "migration"):
        record = files[name]
        assert record is not None
        record["last_outcome"] = "failed"
    checks = files["checks"]
    assert checks is not None
    checks["found_warnings"] = ["database_unavailable", "low_disk_space", "unknown", 3]
    checks["telegram"] = {"configured": True, "last_delivery_outcome": "failed"}
    assert codes(files) == [
        "database_unavailable",
        "backup_failed",
        "offhost_copy_failed",
        "restore_test_failed",
        "low_disk_space",
        "migration_failed",
        "telegram_delivery_failed",
    ]
    critical = {w.code: w.critical for w in evaluate_warnings(files, NOW)}
    assert critical["telegram_delivery_failed"] is False
    assert critical["database_unavailable"] is True


def test_a_stale_check_hides_its_old_findings_and_telegram_not_set_up_is_shown() -> None:
    files = healthy()
    checks = files["checks"]
    assert checks is not None
    checks["telegram"] = {"configured": False}
    assert codes(files) == ["telegram_not_configured"]
    checks["checked_at"] = at(timedelta(hours=1))
    checks["found_warnings"] = ["low_disk_space"]
    assert codes(files) == ["operations_check_stale"]


def test_warning_texts_carry_no_data_and_page_only_warnings_exist() -> None:
    assert PAGE_ONLY_WARNINGS <= set(WARNING_MESSAGES)
    for message in WARNING_MESSAGES.values():
        assert "{" not in message and message.endswith(".")


def test_status_files_are_replaced_in_one_step_and_checked(tmp_path: Path) -> None:
    write_status(tmp_path, "backup", {"last_outcome": "succeeded"})
    assert read_status(tmp_path, "backup") == {"schema_version": 1, "last_outcome": "succeeded"}
    assert read_status(tmp_path, "migration") is None
    assert list(tmp_path.glob(".*partial")) == []
    (tmp_path / "checks.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(StatusFileError):
        read_status(tmp_path, "checks")
    assert read_all_status(tmp_path)["checks"] is None
    with pytest.raises(StatusFileError):
        write_status(tmp_path, "other", {})  # type: ignore[arg-type]
