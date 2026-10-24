"""V1-059 operational log retention of 90 days (DL-071 answer 17; DEPLOY-052)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from property_rental.log_retention import expired_log_files

NOW = datetime(2027, 3, 15, 3, 0, tzinfo=UTC)


def make(path: Path, age: timedelta) -> Path:
    path.write_text("{}\n", encoding="utf-8")
    moment = (NOW - age).timestamp()
    os.utime(path, (moment, moment))
    return path


def test_only_operational_log_files_older_than_90_days_are_expired(tmp_path: Path) -> None:
    keep = timedelta(days=90)
    old_log = make(tmp_path / "backup-2026-12-01.jsonl", timedelta(days=91))
    old_gz = make(tmp_path / "app-2026-11-01.log.gz", timedelta(days=120))
    make(tmp_path / "ops-check-2027-01-01.jsonl", timedelta(days=89))
    make(tmp_path / "notes.txt", timedelta(days=400))
    make(tmp_path / "audit.sql", timedelta(days=400))
    folder = tmp_path / "old.log"
    folder.mkdir()
    os.utime(folder, (0, 0))
    inner = tmp_path / "sub"
    inner.mkdir()
    make(inner / "deep.log", timedelta(days=400))
    link = tmp_path / "link.log"
    link.symlink_to(inner / "deep.log")
    assert expired_log_files(tmp_path, keep, NOW) == sorted([old_gz, old_log])
    assert expired_log_files(tmp_path / "missing", keep, NOW) == []
