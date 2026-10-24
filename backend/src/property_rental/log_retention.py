"""Operational log retention (V1-059, DL-071 answer 17; DEPLOY-052).

Technical (operational) log files are kept 90 days; `property-rental-log-retention` deletes the
older ones once a day. It only looks at regular files directly inside the configured log
folder whose names end in `.log`, `.jsonl`, `.log.gz` or `.jsonl.gz`; it never follows a link,
never enters a sub-folder and never touches anything else. Audit and money history live in the
database and are kept forever; this job cannot reach them.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from property_rental.operations_config import OperationsConfigError, load_operations_config
from property_rental.operations_status import format_time, utc_now

LOG_SUFFIXES: Final = (".log", ".jsonl", ".log.gz", ".jsonl.gz")


def expired_log_files(directory: Path, keep: timedelta, now: datetime) -> list[Path]:
    """Operational log files last changed more than `keep` ago."""
    if not directory.is_dir():
        return []
    cutoff = now.timestamp() - keep.total_seconds()
    expired: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.name.endswith(LOG_SUFFIXES):
            continue
        file_status = path.lstat()
        if not stat.S_ISREG(file_status.st_mode):
            continue
        if file_status.st_mtime < cutoff:
            expired.append(path)
    return expired


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="property-rental-log-retention")
    parser.add_argument("--config", type=Path, required=True, help="production-operations.json")
    parser.add_argument("--dry-run", action="store_true", help="list, do not delete")
    arguments = parser.parse_args(argv)
    try:
        config = load_operations_config(arguments.config)
    except OperationsConfigError as error:
        print(json.dumps({"event": "log_retention.config_invalid", "detail": str(error)}))
        return 2
    expired = expired_log_files(config.log_directory, config.log_retention, utc_now())
    if not arguments.dry_run:
        for path in expired:
            path.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "timestamp": format_time(utc_now()),
                "event": "log_retention.completed",
                "dry_run": arguments.dry_run,
                "deleted" if not arguments.dry_run else "would_delete": [p.name for p in expired],
                "retention_days": config.log_retention.days,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
