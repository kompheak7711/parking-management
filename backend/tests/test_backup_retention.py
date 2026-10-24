"""V1-059 backup retention classes (DL-071 answer 3; DEPLOY-043)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from property_rental.backup_retention import (
    BackupCopy,
    add_months,
    classes_for_new_backup,
    copies_to_delete,
)

# 2027-03-15 10:00 in Phnom Penh (UTC+7).
NOW = datetime(2027, 3, 15, 3, 0, tzinfo=UTC)


def copy(backup_id: str, retention_class: str, age: timedelta) -> BackupCopy:
    return BackupCopy(backup_id, retention_class, NOW - age)  # type: ignore[arg-type]


def test_the_first_backup_of_a_local_day_and_month_is_also_daily_and_monthly() -> None:
    assert classes_for_new_backup(NOW, []) == ("hourly", "daily", "monthly")
    same_day = [copy("a", "daily", timedelta(hours=2)), copy("a", "monthly", timedelta(hours=2))]
    assert classes_for_new_backup(NOW, same_day) == ("hourly",)
    # 23:30 UTC on 14 March is 06:30 on 15 March in Phnom Penh: the same local day.
    late_utc = [copy("b", "daily", timedelta(hours=3, minutes=30))]
    assert classes_for_new_backup(NOW, late_utc) == ("hourly", "monthly")
    # 16:30 UTC on 14 March is 23:30 on 14 March in Phnom Penh: the day before.
    yesterday_local = [copy("c", "daily", timedelta(hours=10, minutes=30))]
    assert classes_for_new_backup(NOW, yesterday_local) == ("hourly", "daily", "monthly")


def test_hourly_copies_are_kept_2_days_daily_30_days_monthly_12_months() -> None:
    copies = [
        copy("newest", "hourly", timedelta(minutes=5)),
        copy("h-keep", "hourly", timedelta(days=2)),
        copy("h-drop", "hourly", timedelta(days=2, seconds=1)),
        copy("d-keep", "daily", timedelta(days=30)),
        copy("d-drop", "daily", timedelta(days=30, seconds=1)),
        copy("m-keep", "monthly", timedelta(days=360)),
        copy("m-drop", "monthly", timedelta(days=370)),
    ]
    assert {c.backup_id for c in copies_to_delete(copies, NOW)} == {"h-drop", "d-drop", "m-drop"}


def test_the_newest_good_backup_is_never_deleted_whatever_its_age() -> None:
    old = [
        copy("only", "hourly", timedelta(days=400)),
        copy("only", "daily", timedelta(days=400)),
        copy("only", "monthly", timedelta(days=400)),
        copy("older", "monthly", timedelta(days=800)),
    ]
    deleted = copies_to_delete(old, NOW)
    assert [c.backup_id for c in deleted] == ["older"]
    assert copies_to_delete([], NOW) == []


def test_month_arithmetic_keeps_the_last_day_of_a_short_month() -> None:
    assert add_months(datetime(2027, 1, 31, tzinfo=UTC), 1) == datetime(2027, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2026, 3, 15, tzinfo=UTC), 12) == datetime(2027, 3, 15, tzinfo=UTC)


def test_times_without_a_time_zone_are_refused() -> None:
    with pytest.raises(ValueError):
        BackupCopy("x", "hourly", datetime(2027, 1, 1))
    with pytest.raises(ValueError):
        copies_to_delete([], datetime(2027, 1, 1))
