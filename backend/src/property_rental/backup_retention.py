"""Backup retention classes (V1-059, DL-071 answer 3; DEPLOY-043).

Every backup is an hourly copy. The first good backup of a local day (Asia/Phnom_Penh) is also
the daily copy of that day, and the first good backup of a local month is also the monthly copy.
Hourly copies are kept 2 days, daily copies 30 days and monthly copies 12 months. The newest
good copy is never deleted, whatever its age, and nothing is deleted while no good copy exists.
These are pure functions: the backup job lists its copies, asks which to delete, and deletes
only those.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

RetentionClass = Literal["hourly", "daily", "monthly"]
RETENTION_CLASSES: Final[tuple[RetentionClass, ...]] = ("hourly", "daily", "monthly")
PROPERTY_TIME_ZONE: Final = ZoneInfo("Asia/Phnom_Penh")
HOURLY_KEEP: Final = timedelta(days=2)
DAILY_KEEP: Final = timedelta(days=30)
MONTHLY_KEEP_MONTHS: Final = 12


@dataclass(frozen=True, slots=True)
class BackupCopy:
    """One stored copy of one backup in one retention class."""

    backup_id: str
    retention_class: RetentionClass
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("backup times must carry a time zone")
        if self.retention_class not in RETENTION_CLASSES:
            raise ValueError("unknown retention class")


def add_months(moment: datetime, months: int) -> datetime:
    """The same local day `months` later, or the month's last day when it is shorter."""
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def is_expired(copy: BackupCopy, now: datetime) -> bool:
    """Whether the copy is older than its class keeps it."""
    if copy.retention_class == "hourly":
        return now - copy.created_at > HOURLY_KEEP
    if copy.retention_class == "daily":
        return now - copy.created_at > DAILY_KEEP
    local_created = copy.created_at.astimezone(PROPERTY_TIME_ZONE)
    return add_months(local_created, MONTHLY_KEEP_MONTHS) < now.astimezone(PROPERTY_TIME_ZONE)


def classes_for_new_backup(
    created_at: datetime, existing: Iterable[BackupCopy]
) -> tuple[RetentionClass, ...]:
    """Hourly always; daily and monthly when it is the first good backup of its day or month."""
    local = created_at.astimezone(PROPERTY_TIME_ZONE)
    has_daily = False
    has_monthly = False
    for copy in existing:
        copy_local = copy.created_at.astimezone(PROPERTY_TIME_ZONE)
        if copy.retention_class == "daily" and copy_local.date() == local.date():
            has_daily = True
        if copy.retention_class == "monthly" and (copy_local.year, copy_local.month) == (
            local.year,
            local.month,
        ):
            has_monthly = True
    classes: list[RetentionClass] = ["hourly"]
    if not has_daily:
        classes.append("daily")
    if not has_monthly:
        classes.append("monthly")
    return tuple(classes)


def copies_to_delete(copies: Sequence[BackupCopy], now: datetime) -> list[BackupCopy]:
    """The expired copies, never a copy of the newest good backup (DEPLOY-043)."""
    if now.tzinfo is None:
        raise ValueError("the current time must carry a time zone")
    if not copies:
        return []
    newest = max(copies, key=lambda copy: (copy.created_at, copy.backup_id))
    return [copy for copy in copies if copy.backup_id != newest.backup_id and is_expired(copy, now)]
