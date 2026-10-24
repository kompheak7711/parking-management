"""Hourly encrypted backups, off-host copies and restore tests (V1-059, DL-071 answers 1 to 5).

`property-rental-backup run` makes one backup with the read-only backup identity: it opens a
REPEATABLE READ transaction, exports its snapshot, counts the rows of every table in it, and
runs `pg_dump --snapshot` on that same snapshot, so the counts describe exactly what the dump
holds. The dump is checked (`pg_restore --list`), sealed with AES-256-GCM
(`property_rental.backup_encryption`), opened again and compared by SHA-256, and only then
stored with its manifest (DEPLOY-042: times, source identity, schema revision, sizes,
checksums, destination, retention classes, outcome). An empty, unreadable or truncated dump
fails the run. Retention then deletes expired copies, never the newest good one (DEPLOY-043).

`offhost-copy` copies the newest good backup, still encrypted, to a mounted external drive or
second computer (daily) or to the drive that leaves the building (weekly), and checks the copy.
`restore-test` restores the newest good backup into an empty throwaway database whose name
starts with `prm_restore_test` and compares the schema revision and every table's row count
with the manifest (DEPLOY-045, DEPLOY-046). `verify` checks one backup file.

The database address and password are read from a protected file and passed to the PostgreSQL
tools through a private password file, never on the command line, in a log or in a status
file. Every outcome is written to the status directory for the health page and the alerts.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from property_rental.backup_encryption import (
    BackupIntegrityError,
    BackupKeyError,
    decrypt_file,
    encrypt_file,
    load_backup_key,
)
from property_rental.backup_retention import (
    PROPERTY_TIME_ZONE,
    RETENTION_CLASSES,
    BackupCopy,
    RetentionClass,
    classes_for_new_backup,
    copies_to_delete,
)
from property_rental.operations_config import OperationsConfigError, load_operations_config
from property_rental.operations_status import (
    StatusFileError,
    StatusFileName,
    format_time,
    parse_time,
    read_status,
    utc_now,
    write_status,
)

MANIFEST_VERSION: Final = 1
BACKUP_SUFFIX: Final = ".pgdump.enc"
RESTORE_TEST_DATABASE_PREFIX: Final = "prm_restore_test"
OFFHOST_KEEP: Final[dict[str, timedelta]] = {
    "daily": timedelta(days=30),
    "weekly": timedelta(days=366),
}
CONNECT_TIMEOUT_SECONDS: Final = 10
OFFHOST_MARKER: Final = "PRM-OFFHOST-DRIVE"


class BackupJobError(RuntimeError):
    """A step failed; `code` is the fixed failure code written to the status file."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseSource:
    """Connection details read from a protected file; `identity` carries no password."""

    host: str
    port: str
    user: str
    password: str
    dbname: str

    @property
    def identity(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"

    @property
    def conninfo(self) -> str:
        return psycopg.conninfo.make_conninfo(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.dbname,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name="prm-backup",
        )


def log_event(event: str, **fields: object) -> None:
    """One JSON line on standard output, with fixed fields only."""
    payload = {"timestamp": format_time(utc_now()), "event": event, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def read_database_source(path: Path) -> DatabaseSource:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise BackupJobError(
            "database_file_unavailable", "the database file is unavailable"
        ) from error
    try:
        parts = conninfo_to_dict(text)
    except psycopg.ProgrammingError as error:
        raise BackupJobError("database_file_invalid", "the database file is not valid") from error
    values = {
        key: str(parts.get(key) or "") for key in ("host", "port", "user", "password", "dbname")
    }
    if not values["user"] or not values["dbname"]:
        raise BackupJobError("database_file_invalid", "the database file needs a user and a name")
    return DatabaseSource(
        host=values["host"] or "localhost",
        port=values["port"] or "5432",
        user=values["user"],
        password=values["password"],
        dbname=values["dbname"],
    )


def _pgpass_field(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def remove_leftover_work(parent: Path) -> None:
    """Remove work folders a crash or power loss left behind (they may hold an unsealed dump).
    Called under the lock that guards `parent`, before any new work starts."""
    if parent.is_dir():
        for leftover in parent.glob("work-*"):
            shutil.rmtree(leftover, ignore_errors=True)


@contextlib.contextmanager
def private_work_directory(parent: Path) -> Iterator[Path]:
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="work-", dir=parent))
    try:
        directory.chmod(0o700)
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def tool_environment(source: DatabaseSource, work: Path) -> dict[str, str]:
    """PostgreSQL tool settings with the password in a private file, not in the arguments."""
    password_file = work / "pgpass"
    descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(
            ":".join(
                _pgpass_field(value)
                for value in (source.host, source.port, source.dbname, source.user, source.password)
            )
            + "\n"
        )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PG") and key not in {"DATABASE_URL"}
    }
    environment.update(
        PGHOST=source.host,
        PGPORT=source.port,
        PGUSER=source.user,
        PGDATABASE=source.dbname,
        PGPASSFILE=str(password_file),
        PGCONNECT_TIMEOUT=str(CONNECT_TIMEOUT_SECONDS),
        PGAPPNAME="prm-backup",
    )
    return environment


def run_tool(
    arguments: Sequence[str], environment: dict[str, str], code: str, secret: str
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(arguments),
        env=environment,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        # Only the tool's own message lines: a CONTEXT or DETAIL line can quote a row of data.
        prefix = f"{Path(arguments[0]).name}:"
        lines = [line for line in result.stderr.splitlines() if line.startswith(prefix)]
        detail = "\n".join(lines[-5:])[:1000]
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
        log_event(
            "backup.tool_failed",
            code=code,
            tool=Path(arguments[0]).name,
            exit_status=result.returncode,
            detail=detail,
        )
        raise BackupJobError(code, f"{Path(arguments[0]).name} failed")
    return result


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tool_path(bin_directory: Path | None, name: str) -> str:
    return str(bin_directory / name) if bin_directory is not None else name


def check_dump(dump: Path, pg_bin: Path | None, environment: dict[str, str], secret: str) -> int:
    """`pg_restore --list` must read the whole table of contents; returns its entry count."""
    if dump.stat().st_size == 0:
        raise BackupJobError("dump_empty", "the dump is empty")
    listing = run_tool(
        [tool_path(pg_bin, "pg_restore"), "--list", str(dump)],
        environment,
        "dump_unreadable",
        secret,
    )
    entries = [line for line in listing.stdout.splitlines() if line and not line.startswith(";")]
    if not entries:
        raise BackupJobError("dump_empty", "the dump has no entries")
    return len(entries)


def _table_counts(cursor: psycopg.Cursor[tuple[object, ...]]) -> dict[str, int]:
    cursor.execute(
        """
        SELECT n.nspname, c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%'
          AND n.nspname NOT LIKE 'pg_temp%'
        ORDER BY 1, 2
        """
    )
    tables = [(str(schema), str(name)) for schema, name in cursor.fetchall()]
    counts: dict[str, int] = {}
    for schema, name in tables:
        cursor.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(name)
            )
        )
        row = cursor.fetchone()
        value = row[0] if row is not None else 0
        counts[f"{schema}.{name}"] = value if isinstance(value, int) else 0
    return counts


def _schema_revision(cursor: psycopg.Cursor[tuple[object, ...]]) -> str | None:
    cursor.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    row = cursor.fetchone()
    if row is None or row[0] is not True:
        return None
    cursor.execute("SELECT version_num FROM public.alembic_version")
    revisions = sorted(str(item[0]) for item in cursor.fetchall())
    return ",".join(revisions) if revisions else None


# --- stored copies ---------------------------------------------------------------------------


def class_directory(backup_directory: Path, retention_class: RetentionClass) -> Path:
    return backup_directory / retention_class


def stored_copies(backup_directory: Path) -> list[BackupCopy]:
    """Copies with a verified manifest and their encrypted file; anything else is ignored."""
    copies: list[BackupCopy] = []
    for retention_class in RETENTION_CLASSES:
        directory = class_directory(backup_directory, retention_class)
        if not directory.is_dir():
            continue
        for manifest_path in sorted(directory.glob("prm-*.json")):
            manifest = _read_manifest(manifest_path)
            if manifest is None:
                continue
            backup_id = manifest_path.name.removesuffix(".json")
            created_at = parse_time(manifest.get("finished_at"))
            if created_at is None or not (directory / f"{backup_id}{BACKUP_SUFFIX}").is_file():
                continue
            copies.append(BackupCopy(backup_id, retention_class, created_at))
    return copies


def _read_manifest(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("manifest_version") != MANIFEST_VERSION
        or value.get("outcome") != "verified"
    ):
        return None
    return value


def newest_good_backup(backup_directory: Path) -> tuple[Path, dict[str, object]]:
    copies = stored_copies(backup_directory)
    if not copies:
        raise BackupJobError("no_good_backup", "there is no good backup")
    newest = max(copies, key=lambda copy: (copy.created_at, copy.backup_id))
    directory = class_directory(backup_directory, newest.retention_class)
    manifest = _read_manifest(directory / f"{newest.backup_id}.json")
    if manifest is None:
        raise BackupJobError("no_good_backup", "there is no good backup")
    return directory / f"{newest.backup_id}{BACKUP_SUFFIX}", manifest


def _write_json_private(path: Path, value: object) -> None:
    partial = path.with_name(f".{path.name}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(path)


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def delete_copy(backup_directory: Path, copy: BackupCopy) -> None:
    directory = class_directory(backup_directory, copy.retention_class)
    (directory / f"{copy.backup_id}{BACKUP_SUFFIX}").unlink(missing_ok=True)
    (directory / f"{copy.backup_id}.json").unlink(missing_ok=True)


@contextlib.contextmanager
def exclusive_lock(backup_directory: Path, name: str = ".lock") -> Iterator[None]:
    backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (backup_directory / name).open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupJobError(
                "backup_already_running", "another backup step is running"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# --- commands --------------------------------------------------------------------------------


def make_backup(
    *,
    backup_directory: Path,
    source: DatabaseSource,
    key: bytes,
    pg_bin: Path | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Make, check, seal and store one backup; returns its manifest."""
    started_at = now or utc_now()
    backup_id = "prm-" + started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    with private_work_directory(backup_directory / ".work") as work:
        environment = tool_environment(source, work)
        dump = work / "backup.pgdump"
        try:
            connection = psycopg.connect(source.conninfo, autocommit=False)
        except psycopg.Error as error:
            raise BackupJobError("database_unavailable", "the database is not answering") from error
        with connection:
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_export_snapshot()")
                snapshot_row = cursor.fetchone()
                if snapshot_row is None:
                    raise BackupJobError("snapshot_failed", "no snapshot")
                snapshot = str(snapshot_row[0])
                schema_revision = _schema_revision(cursor)
                counts = _table_counts(cursor)
                run_tool(
                    [
                        tool_path(pg_bin, "pg_dump"),
                        "--format=custom",
                        "--no-password",
                        f"--snapshot={snapshot}",
                        f"--file={dump}",
                    ],
                    environment,
                    "dump_failed",
                    source.password,
                )
            connection.rollback()
        entries = check_dump(dump, pg_bin, environment, source.password)
        plain_size = dump.stat().st_size
        plain_sha = sha256_of(dump)
        sealed = work / f"{backup_id}{BACKUP_SUFFIX}"
        encrypt_file(dump, sealed, key)
        opened = work / "opened.pgdump"
        try:
            decrypt_file(sealed, opened, key)
        except BackupIntegrityError as error:
            raise BackupJobError(
                "encryption_check_failed", "the sealed copy does not open"
            ) from error
        if sha256_of(opened) != plain_sha:
            raise BackupJobError("encryption_check_failed", "the sealed copy differs")
        opened.unlink()
        dump.unlink()
        finished_at = utc_now() if now is None else now
        classes = classes_for_new_backup(finished_at, stored_copies(backup_directory))
        manifest: dict[str, object] = {
            "manifest_version": MANIFEST_VERSION,
            "backup_id": backup_id,
            "started_at": format_time(started_at),
            "finished_at": format_time(finished_at),
            "local_time": finished_at.astimezone(PROPERTY_TIME_ZONE).isoformat(timespec="seconds"),
            "source": source.identity,
            "schema_revision": schema_revision,
            "dump_entries": entries,
            "table_row_counts": counts,
            "plain_size_bytes": plain_size,
            "plain_sha256": plain_sha,
            "encrypted_size_bytes": sealed.stat().st_size,
            "encrypted_sha256": sha256_of(sealed),
            "encryption": "AES-256-GCM",
            "destination": str(backup_directory),
            "retention_classes": list(classes),
            "outcome": "verified",
        }
        first_directory: Path | None = None
        for retention_class in classes:
            directory = class_directory(backup_directory, retention_class)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = directory / f"{backup_id}{BACKUP_SUFFIX}"
            if first_directory is None:
                sealed.replace(target)
                first_directory = directory
            else:
                _link_or_copy(first_directory / f"{backup_id}{BACKUP_SUFFIX}", target)
            _write_json_private(directory / f"{backup_id}.json", manifest)
    return manifest


ORPHAN_AGE: Final = timedelta(days=1)


def remove_orphans(backup_directory: Path, now: datetime) -> list[str]:
    """Sealed or partial files with no verified manifest, older than a day (a crash between the
    file and its manifest); they are never counted as good copies."""
    removed: list[str] = []
    for retention_class in RETENTION_CLASSES:
        directory = class_directory(backup_directory, retention_class)
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.name.endswith(BACKUP_SUFFIX):
                if _read_manifest(directory / f"{path.name.removesuffix(BACKUP_SUFFIX)}.json"):
                    continue
            elif not path.name.endswith(".partial"):
                continue
            if now.timestamp() - path.lstat().st_mtime > ORPHAN_AGE.total_seconds():
                path.unlink(missing_ok=True)
                removed.append(f"{retention_class}/{path.name}")
    return removed


def prune(backup_directory: Path, now: datetime) -> list[str]:
    deleted: list[str] = remove_orphans(backup_directory, now)
    for copy in copies_to_delete(stored_copies(backup_directory), now):
        delete_copy(backup_directory, copy)
        deleted.append(f"{copy.retention_class}/{copy.backup_id}")
    return deleted


def offhost_copy(*, backup_directory: Path, destination: Path, kind: str, now: datetime) -> str:
    """Copy the newest good backup, still encrypted, and check the copy by SHA-256."""
    if kind not in OFFHOST_KEEP:
        raise BackupJobError("offhost_kind_invalid", "the copy kind must be daily or weekly")
    if not (destination / OFFHOST_MARKER).is_file():
        # An unmounted drive leaves an empty mount folder on the production disk: without the
        # marker file placed on the drive itself, nothing is copied.
        raise BackupJobError("offhost_destination_missing", "the copy place is not connected")
    resolved_destination = destination.resolve()
    if resolved_destination == backup_directory.resolve() or backup_directory.resolve() in (
        resolved_destination.parents
    ):
        raise BackupJobError("offhost_destination_invalid", "the copy place is the backup folder")
    sealed, manifest = newest_good_backup(backup_directory)
    backup_id = str(manifest["backup_id"])
    target_directory = destination / "prm-backups" / kind
    target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = target_directory / sealed.name
    partial = target_directory / f".{sealed.name}.partial"
    shutil.copyfile(sealed, partial)
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
        if hasattr(os, "posix_fadvise"):
            # Drop the cached pages so the check below reads the copy back from the drive.
            os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    if sha256_of(partial) != manifest.get("encrypted_sha256"):
        partial.unlink(missing_ok=True)
        raise BackupJobError("offhost_copy_differs", "the copy differs from the backup")
    partial.replace(target)
    _write_json_private(target_directory / f"{backup_id}.json", manifest)
    keep = OFFHOST_KEEP[kind]
    copies: list[tuple[datetime, str]] = []
    for manifest_path in target_directory.glob("prm-*.json"):
        copied = _read_manifest(manifest_path)
        moment = parse_time(copied.get("finished_at")) if copied is not None else None
        if moment is not None:
            copies.append((moment, manifest_path.name.removesuffix(".json")))
    if copies:
        newest_id = max(copies)[1]
        for moment, copy_id in copies:
            if copy_id != newest_id and now - moment > keep:
                (target_directory / f"{copy_id}{BACKUP_SUFFIX}").unlink(missing_ok=True)
                (target_directory / f"{copy_id}.json").unlink(missing_ok=True)
    return backup_id


def verify_backup_file(sealed: Path, key: bytes, pg_bin: Path | None) -> dict[str, object]:
    manifest = _read_manifest(sealed.with_name(sealed.name.removesuffix(BACKUP_SUFFIX) + ".json"))
    if manifest is None:
        raise BackupJobError("manifest_missing", "the backup has no verified manifest")
    if sha256_of(sealed) != manifest.get("encrypted_sha256"):
        raise BackupJobError("backup_file_differs", "the backup file differs from its manifest")
    with private_work_directory(sealed.parent / ".work") as work:
        opened = work / "opened.pgdump"
        try:
            decrypt_file(sealed, opened, key)
        except BackupIntegrityError as error:
            raise BackupJobError("backup_file_damaged", "the backup file does not open") from error
        if sha256_of(opened) != manifest.get("plain_sha256"):
            raise BackupJobError("backup_file_differs", "the opened backup differs")
        check_dump(opened, pg_bin, dict(os.environ), "")
    return manifest


def restore_test(
    *,
    backup_directory: Path,
    target: DatabaseSource,
    key: bytes,
    pg_bin: Path | None,
    keep_owners: bool,
) -> dict[str, object]:
    """Restore the newest good backup into an empty throwaway database and compare it."""
    if not target.dbname.startswith(RESTORE_TEST_DATABASE_PREFIX):
        raise BackupJobError(
            "restore_target_refused",
            f"the restore test database name must start with {RESTORE_TEST_DATABASE_PREFIX}",
        )
    sealed, manifest = newest_good_backup(backup_directory)
    try:
        with psycopg.connect(target.conninfo, autocommit=True) as connection:
            counts_before = _table_counts(connection.cursor())
    except psycopg.Error as error:
        raise BackupJobError(
            "restore_target_unavailable", "the restore database is not answering"
        ) from error
    if counts_before:
        raise BackupJobError("restore_target_not_empty", "the restore database is not empty")
    with private_work_directory(backup_directory / ".work-restore") as work:
        opened = work / "restore.pgdump"
        try:
            decrypt_file(sealed, opened, key)
        except BackupIntegrityError as error:
            raise BackupJobError("backup_file_damaged", "the backup file does not open") from error
        if sha256_of(opened) != manifest.get("plain_sha256"):
            raise BackupJobError("backup_file_differs", "the opened backup differs")
        environment = tool_environment(target, work)
        arguments = [
            tool_path(pg_bin, "pg_restore"),
            "--no-password",
            "--exit-on-error",
            "--single-transaction",
            f"--dbname={target.dbname}",
        ]
        if not keep_owners:
            arguments += ["--no-owner", "--no-privileges"]
        run_tool([*arguments, str(opened)], environment, "restore_failed", target.password)
    try:
        with psycopg.connect(target.conninfo, autocommit=True) as connection:
            cursor = connection.cursor()
            restored_revision = _schema_revision(cursor)
            restored_counts = _table_counts(cursor)
    except psycopg.Error as error:
        raise BackupJobError(
            "restore_target_unavailable", "the restore database is not answering"
        ) from error
    expected_counts = manifest.get("table_row_counts")
    if not isinstance(expected_counts, dict):
        raise BackupJobError("manifest_missing", "the manifest has no row counts")
    if restored_revision != manifest.get("schema_revision"):
        raise BackupJobError("restore_revision_differs", "the restored schema revision differs")
    differences = sorted(
        name
        for name in set(expected_counts) | set(restored_counts)
        if expected_counts.get(name) != restored_counts.get(name)
    )
    if differences:
        log_event("restore_test.counts_differ", tables=differences[:50])
        raise BackupJobError("restore_counts_differ", "restored row counts differ")
    return {
        "backup_id": manifest.get("backup_id"),
        "schema_revision": restored_revision,
        "tables_compared": len(restored_counts),
        "rows_compared": sum(restored_counts.values()),
    }


# --- command line ----------------------------------------------------------------------------


def _record(
    directory: Path,
    name: StatusFileName,
    outcome: str,
    code: str | None,
    previous_success: str | None,
    now: datetime,
    **extra: object,
) -> None:
    record: dict[str, object] = {
        "last_attempt_at": format_time(now),
        "last_outcome": outcome,
        "last_failure_code": code,
        "last_success_at": format_time(now) if outcome == "succeeded" else previous_success,
        **extra,
    }
    write_status(directory, name, record)


def _previous_success(directory: Path, name: StatusFileName) -> str | None:
    try:
        record = read_status(directory, name)
    except StatusFileError:
        return None
    value = record.get("last_success_at") if record is not None else None
    return value if isinstance(value, str) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="property-rental-backup", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--config", type=Path, required=True, help="production-operations.json")
    parser.add_argument(
        "--pg-bin", type=Path, default=None, help="folder of pg_dump and pg_restore"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="make one hourly backup and apply retention")
    copy_parser = commands.add_parser("offhost-copy", help="copy the newest good backup")
    copy_parser.add_argument("--kind", choices=sorted(OFFHOST_KEEP), required=True)
    copy_parser.add_argument("--destination", type=Path, required=True)
    restore_parser = commands.add_parser("restore-test", help="restore into a throwaway database")
    restore_parser.add_argument("--target-database-url-file", type=Path, required=True)
    restore_parser.add_argument(
        "--without-owners",
        action="store_true",
        help="skip owners and grants (when the roles do not exist)",
    )
    verify_parser = commands.add_parser("verify", help="check one backup file")
    verify_parser.add_argument("file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    os.umask(0o077)
    try:
        config = load_operations_config(arguments.config)
    except OperationsConfigError as error:
        log_event("backup.config_invalid", detail=str(error))
        return 2
    status_directory = config.status_directory
    backup_directory = config.backup_directory
    now = utc_now()
    name: StatusFileName = "backup"
    if arguments.command == "offhost-copy":
        name = "offhost-daily" if arguments.kind == "daily" else "offhost-weekly"
    elif arguments.command == "restore-test":
        name = "restore-test"
    previous = _previous_success(status_directory, name)
    try:
        key = load_backup_key(config.backup_encryption_key_file)
        # A restore test can take long: it has its own lock and work folder, so the hourly
        # backup is never skipped because of it. Retention never deletes the newest backup,
        # which is the one a restore test reads.
        restore = arguments.command == "restore-test"
        with exclusive_lock(backup_directory, ".restore-lock" if restore else ".lock"):
            remove_leftover_work(backup_directory / (".work-restore" if restore else ".work"))
            if arguments.command == "run":
                source = read_database_source(config.backup_database_url_file)
                manifest = make_backup(
                    backup_directory=backup_directory,
                    source=source,
                    key=key,
                    pg_bin=arguments.pg_bin,
                )
                deleted = prune(backup_directory, utc_now())
                _record(
                    status_directory,
                    name,
                    "succeeded",
                    None,
                    previous,
                    utc_now(),
                    backup_id=manifest["backup_id"],
                    schema_revision=manifest["schema_revision"],
                    retention_classes=manifest["retention_classes"],
                )
                log_event(
                    "backup.succeeded",
                    backup_id=manifest["backup_id"],
                    retention_classes=manifest["retention_classes"],
                    deleted=deleted,
                )
            elif arguments.command == "offhost-copy":
                backup_id = offhost_copy(
                    backup_directory=backup_directory,
                    destination=arguments.destination,
                    kind=arguments.kind,
                    now=now,
                )
                _record(
                    status_directory,
                    name,
                    "succeeded",
                    None,
                    previous,
                    utc_now(),
                    backup_id=backup_id,
                )
                log_event("backup.offhost_copy_succeeded", kind=arguments.kind, backup_id=backup_id)
            elif arguments.command == "restore-test":
                target = read_database_source(arguments.target_database_url_file)
                result = restore_test(
                    backup_directory=backup_directory,
                    target=target,
                    key=key,
                    pg_bin=arguments.pg_bin,
                    keep_owners=not arguments.without_owners,
                )
                _record(status_directory, name, "succeeded", None, previous, utc_now(), **result)
                log_event("restore_test.succeeded", **result)
            else:
                manifest = verify_backup_file(arguments.file, key, arguments.pg_bin)
                log_event("backup.verified", backup_id=manifest.get("backup_id"))
    except BackupKeyError as error:
        return _fail(
            arguments.command, status_directory, name, "backup_key_invalid", str(error), previous
        )
    except BackupJobError as error:
        if error.code == "backup_already_running":
            log_event("backup.skipped", code=error.code)
            return 75
        return _fail(arguments.command, status_directory, name, error.code, str(error), previous)
    except psycopg.Error:
        return _fail(
            arguments.command,
            status_directory,
            name,
            "database_error",
            "the database answered with an error",
            previous,
        )
    except OSError:
        return _fail(
            arguments.command,
            status_directory,
            name,
            "file_error",
            "a file could not be read or written",
            previous,
        )
    except Exception:
        # Anything unexpected still leaves a failed record for the health page and the alerts.
        return _fail(
            arguments.command,
            status_directory,
            name,
            "unexpected_error",
            "an unexpected error stopped the step",
            previous,
        )
    return 0


def _fail(
    command: str,
    status_directory: Path,
    name: StatusFileName,
    code: str,
    message: str,
    previous: str | None,
) -> int:
    if command != "verify":
        with contextlib.suppress(OSError):
            _record(status_directory, name, "failed", code, previous, utc_now())
    log_event(f"{command}.failed", code=code, detail=message)
    return 1


if __name__ == "__main__":
    sys.exit(main())
