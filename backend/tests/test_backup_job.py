"""V1-059 backup job storage, retention, off-host copy and secrets (DL-071 answers 1 to 5).

The full path against PostgreSQL 17.6 (backup with the read-only backup identity, restore test
into a throwaway database, a changed file refused) is `scripts/backup-restore-check.sh`.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from property_rental.backup_job import (
    BACKUP_SUFFIX,
    MANIFEST_VERSION,
    OFFHOST_MARKER,
    BackupJobError,
    newest_good_backup,
    offhost_copy,
    prune,
    read_database_source,
    remove_leftover_work,
    remove_orphans,
    restore_test,
    stored_copies,
    tool_environment,
)

NOW = datetime(2027, 3, 15, 3, 0, tzinfo=UTC)


def store(
    directory: Path,
    retention_class: str,
    backup_id: str,
    finished_at: datetime,
    outcome: str = "verified",
) -> None:
    folder = directory / retention_class
    folder.mkdir(parents=True, exist_ok=True)
    body = f"sealed {backup_id}".encode()
    (folder / f"{backup_id}{BACKUP_SUFFIX}").write_bytes(body)
    (folder / f"{backup_id}.json").write_text(
        json.dumps(
            {
                "manifest_version": MANIFEST_VERSION,
                "backup_id": backup_id,
                "finished_at": finished_at.isoformat(),
                "encrypted_sha256": hashlib.sha256(body).hexdigest(),
                "outcome": outcome,
            }
        )
    )


def test_only_verified_manifests_with_their_file_count_as_stored_copies(tmp_path: Path) -> None:
    store(tmp_path, "hourly", "prm-a", NOW)
    store(tmp_path, "hourly", "prm-b", NOW, outcome="failed")
    store(tmp_path, "daily", "prm-c", NOW)
    (tmp_path / "daily" / f"prm-c{BACKUP_SUFFIX}").unlink()
    (tmp_path / "monthly").mkdir()
    (tmp_path / "monthly" / "prm-d.json").write_text("not json")
    assert [(c.backup_id, c.retention_class) for c in stored_copies(tmp_path)] == [
        ("prm-a", "hourly")
    ]


def test_prune_deletes_expired_copies_but_never_the_newest(tmp_path: Path) -> None:
    store(tmp_path, "hourly", "prm-old", NOW - timedelta(days=3))
    store(tmp_path, "daily", "prm-old", NOW - timedelta(days=3))
    store(tmp_path, "hourly", "prm-ancient", NOW - timedelta(days=500))
    # prm-old is the newest good backup: every copy of it is kept, whatever its age.
    assert prune(tmp_path, NOW) == ["hourly/prm-ancient"]
    store(tmp_path, "hourly", "prm-new", NOW - timedelta(hours=1))
    assert prune(tmp_path, NOW) == ["hourly/prm-old"]
    assert (tmp_path / "daily" / f"prm-old{BACKUP_SUFFIX}").exists()
    # Five hundred days later only the newest copy is left.
    later = NOW + timedelta(days=500)
    assert sorted(prune(tmp_path, later)) == ["daily/prm-old"]
    assert newest_good_backup(tmp_path)[0].name == f"prm-new{BACKUP_SUFFIX}"


def test_offhost_copy_checks_the_copy_and_keeps_the_newest(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    drive = tmp_path / "drive"
    with pytest.raises(BackupJobError) as missing:
        offhost_copy(backup_directory=backups, destination=drive, kind="daily", now=NOW)
    assert missing.value.code == "offhost_destination_missing"
    drive.mkdir()
    # An empty mount folder (drive not connected) has no marker: nothing is copied.
    with pytest.raises(BackupJobError) as unmounted:
        offhost_copy(backup_directory=backups, destination=drive, kind="daily", now=NOW)
    assert unmounted.value.code == "offhost_destination_missing"
    (drive / OFFHOST_MARKER).write_text("")
    with pytest.raises(BackupJobError) as none:
        offhost_copy(backup_directory=backups, destination=drive, kind="daily", now=NOW)
    assert none.value.code == "no_good_backup"
    store(backups, "hourly", "prm-1", NOW - timedelta(days=40))
    assert (
        offhost_copy(
            backup_directory=backups, destination=drive, kind="daily", now=NOW - timedelta(days=40)
        )
        == "prm-1"
    )
    store(backups, "hourly", "prm-2", NOW)
    assert (
        offhost_copy(backup_directory=backups, destination=drive, kind="daily", now=NOW) == "prm-2"
    )
    copied = sorted(p.name for p in (drive / "prm-backups" / "daily").iterdir())
    assert copied == ["prm-2.json", f"prm-2{BACKUP_SUFFIX}"]
    (backups / "hourly" / OFFHOST_MARKER).write_text("")
    with pytest.raises(BackupJobError) as inside:
        offhost_copy(
            backup_directory=backups, destination=backups / "hourly", kind="weekly", now=NOW
        )
    assert inside.value.code == "offhost_destination_invalid"
    # A copy that differs from the manifest is refused and not kept.
    (backups / "hourly" / f"prm-2{BACKUP_SUFFIX}").write_bytes(b"changed")
    with pytest.raises(BackupJobError) as differs:
        offhost_copy(backup_directory=backups, destination=drive, kind="weekly", now=NOW)
    assert differs.value.code == "offhost_copy_differs"
    assert not (drive / "prm-backups" / "weekly" / f"prm-2{BACKUP_SUFFIX}").exists()


def test_the_password_goes_to_a_private_file_not_the_environment_or_arguments(
    tmp_path: Path,
) -> None:
    url_file = tmp_path / "url"
    url_file.write_text("postgresql://prm_backup:pa:ss%5Cword@db.local:5433/prm\n")
    source = read_database_source(url_file)
    assert source.identity == "prm_backup@db.local:5433/prm"
    work = tmp_path / "work"
    work.mkdir()
    environment = tool_environment(source, work)
    assert "pa:ss\\word" not in json.dumps(environment)
    assert environment["PGHOST"] == "db.local" and environment["PGPORT"] == "5433"
    password_file = Path(environment["PGPASSFILE"])
    assert password_file.read_text() == "db.local:5433:prm:prm_backup:pa\\:ss\\\\word\n"
    if os.name == "posix":
        assert password_file.stat().st_mode & 0o077 == 0


def test_a_restore_test_refuses_a_database_not_named_for_tests(tmp_path: Path) -> None:
    url_file = tmp_path / "url"
    url_file.write_text("postgresql://prm_admin:x@db/prm\n")
    with pytest.raises(BackupJobError) as refused:
        restore_test(
            backup_directory=tmp_path,
            target=read_database_source(url_file),
            key=bytes(32),
            pg_bin=None,
            keep_owners=True,
        )
    assert refused.value.code == "restore_target_refused"


def test_an_unreadable_database_file_is_a_fixed_failure_code(tmp_path: Path) -> None:
    with pytest.raises(BackupJobError) as missing:
        read_database_source(tmp_path / "missing")
    assert missing.value.code == "database_file_unavailable"
    (tmp_path / "bad").write_text("host=db")
    with pytest.raises(BackupJobError) as bad:
        read_database_source(tmp_path / "bad")
    assert bad.value.code == "database_file_invalid"


def test_orphan_files_and_leftover_work_folders_are_removed(tmp_path: Path) -> None:
    store(tmp_path, "hourly", "prm-good", NOW - timedelta(days=3))
    orphan = tmp_path / "hourly" / f"prm-orphan{BACKUP_SUFFIX}"
    orphan.write_bytes(b"x")
    fresh = tmp_path / "hourly" / f"prm-fresh{BACKUP_SUFFIX}"
    fresh.write_bytes(b"x")
    partial = tmp_path / "daily" / ".prm-x.pgdump.enc.partial"
    partial.parent.mkdir()
    partial.write_bytes(b"x")
    old = (NOW - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))
    os.utime(partial, (old, old))
    recent = (NOW - timedelta(hours=1)).timestamp()
    os.utime(fresh, (recent, recent))
    assert sorted(remove_orphans(tmp_path, NOW)) == [
        "daily/.prm-x.pgdump.enc.partial",
        f"hourly/prm-orphan{BACKUP_SUFFIX}",
    ]
    assert fresh.exists() and (tmp_path / "hourly" / f"prm-good{BACKUP_SUFFIX}").exists()
    leftover = tmp_path / ".work" / "work-abc"
    leftover.mkdir(parents=True)
    (leftover / "backup.pgdump").write_bytes(b"unsealed")
    remove_leftover_work(tmp_path / ".work")
    assert not leftover.exists()
