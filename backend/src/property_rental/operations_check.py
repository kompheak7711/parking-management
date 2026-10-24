"""The operations check and Telegram alert routing (V1-059, DL-071 answers 6 to 8; DEPLOY-051).

`property-rental-ops-check run` is started every 5 minutes on the production computer. It looks
at the database (with the read-only backup identity), the application readiness page, the free
disk space and the security certificate, writes what it found to `checks.json` in the status
directory, works out the health warnings from every status file (the same rules the health page
uses), and sends a Telegram message to the Owner and the Manager when a critical warning starts,
again every `repeat_hours` while it lasts, and once when it ends; an undelivered message is tried
again at most once an hour. A message holds only the fixed
warning texts. When Telegram is not set up or a message cannot be sent, the check still finishes,
and the health page shows that too (SEC-059).

`property-rental-ops-check record-migration` records the outcome of a database update for the
health page; the release procedure runs it after `make migrate`.

Not covered yet (listed for V1-059 part B): an audit-write failure signal, which needs the
application to record such failures first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import psycopg
from cryptography import x509

from property_rental.backup_job import BackupJobError, read_database_source
from property_rental.operations_config import (
    OperationsConfig,
    OperationsConfigError,
    load_operations_config,
)
from property_rental.operations_status import (
    WARNING_MESSAGES,
    HealthWarning,
    StatusFileError,
    evaluate_warnings,
    format_time,
    parse_time,
    read_all_status,
    read_status,
    utc_now,
    write_status,
)
from property_rental.telegram_alerts import (
    DeliveryOutcome,
    PostForm,
    load_telegram_target,
    send_alert,
)

READINESS_TIMEOUT_SECONDS: Final = 5
# A message that could not be delivered is tried again at most once an hour (decided by Claude
# under the owner's 2026-10-23 22:30 rule), so a broken chat never sends every 5 minutes.
RETRY_INTERVAL: Final = timedelta(hours=1)
MESSAGE_TITLE: Final = "CHETANA Residence Management"
SCHEDULED_JOB_QUERY: Final = """
SELECT
  CASE WHEN to_regclass('app.billing_run_attempts') IS NULL THEN 0 ELSE (
    SELECT count(*) FROM app.billing_run_attempts
    WHERE outcome = 'FAILED' AND completed_at > now() - interval '24 hours') END,
  CASE WHEN to_regclass('app.reservation_expiration_runs') IS NULL THEN 0 ELSE (
    SELECT count(*) FROM app.reservation_expiration_runs
    WHERE status = 'FAILED' AND attempt_count >= 2
      AND completed_at > now() - interval '48 hours') END,
  CASE WHEN to_regclass('app.billing_run_attempts') IS NULL THEN NULL ELSE (
    SELECT max(completed_at) FROM app.billing_run_attempts WHERE outcome = 'SUCCEEDED') END,
  CASE WHEN to_regclass('app.reservation_expiration_runs') IS NULL THEN NULL ELSE (
    SELECT max(completed_at) FROM app.reservation_expiration_runs
    WHERE status = 'SUCCEEDED') END,
  CASE WHEN to_regclass('public.alembic_version') IS NULL THEN NULL ELSE (
    SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) END
"""


def log_event(event: str, **fields: object) -> None:
    payload = {"timestamp": format_time(utc_now()), "event": event, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def check_database(config: OperationsConfig) -> tuple[set[str], dict[str, object]]:
    try:
        source = read_database_source(config.backup_database_url_file)
        with psycopg.connect(source.conninfo, autocommit=True) as connection:
            row = connection.execute(SCHEDULED_JOB_QUERY).fetchone()
    except (BackupJobError, psycopg.Error):
        return {"database_unavailable"}, {"database": "unavailable"}
    if row is None:
        return {"database_unavailable"}, {"database": "unavailable"}
    billing_failures, expiration_failures, billing_last, expiration_last, revision = row
    found: set[str] = set()
    if int(billing_failures or 0) >= 2 or int(expiration_failures or 0) >= 1:
        found.add("scheduled_job_repeated_failure")
    details: dict[str, object] = {
        "database": "ok",
        "schema_revision": revision,
        "billing_last_success_at": format_time(billing_last)
        if isinstance(billing_last, datetime)
        else None,
        "reservation_expiration_last_success_at": format_time(expiration_last)
        if isinstance(expiration_last, datetime)
        else None,
    }
    return found, details


def check_readiness(url: str | None) -> set[str]:
    if url is None:
        return set()
    try:
        with urllib.request.urlopen(url, timeout=READINESS_TIMEOUT_SECONDS) as answer:
            return set() if answer.status == 200 else {"database_unavailable"}
    except urllib.error.HTTPError as error:
        return {"database_unavailable"} if error.code == 503 else {"api_unavailable"}
    except (urllib.error.URLError, OSError, ValueError):
        return {"api_unavailable"}


def check_disk(config: OperationsConfig) -> tuple[set[str], list[dict[str, object]]]:
    found: set[str] = set()
    disks: list[dict[str, object]] = []
    for path in config.disk_paths:
        if not path.exists():
            continue
        usage = shutil.disk_usage(path)
        free_percent = round(usage.free * 100 / usage.total, 1) if usage.total else 0.0
        low = (
            free_percent < config.disk_minimum_free_percent
            or usage.free < config.disk_minimum_free_bytes
        )
        if low:
            found.add("low_disk_space")
        disks.append({"path": str(path), "free_percent": free_percent, "low": low})
    return found, disks


def check_certificate(config: OperationsConfig, now: datetime) -> tuple[set[str], str | None]:
    if config.tls_certificate_file is None:
        return set(), None
    try:
        certificate = x509.load_pem_x509_certificate(config.tls_certificate_file.read_bytes())
    except (OSError, ValueError):
        return {"tls_certificate_unreadable"}, None
    expires_at = certificate.not_valid_after_utc
    if expires_at - now < config.tls_warning:
        return {"tls_certificate_expiring"}, format_time(expires_at)
    return set(), format_time(expires_at)


def alert_lines(
    starting: Sequence[HealthWarning], ongoing: Sequence[HealthWarning], ended: Sequence[str]
) -> list[str]:
    lines = [f"{MESSAGE_TITLE}: health alert"]
    lines += [f"NEW: {warning.message}" for warning in starting]
    lines += [f"STILL: {warning.message}" for warning in ongoing]
    lines += [f"FIXED: {WARNING_MESSAGES[code]}" for code in ended if code in WARNING_MESSAGES]
    lines.append("Please look at the health page on the office computer.")
    return lines


def run_check(
    config: OperationsConfig,
    *,
    now: datetime | None = None,
    post_form: PostForm | None = None,
) -> list[HealthWarning]:
    """One check: find, record, alert. Returns the warnings of the health page."""
    moment = now or utc_now()
    found, details = check_database(config)
    found |= check_readiness(config.readiness_url)
    disk_found, disks = check_disk(config)
    found |= disk_found
    certificate_found, certificate_expires_at = check_certificate(config, moment)
    found |= certificate_found

    try:
        previous = read_status(config.status_directory, "checks") or {}
    except StatusFileError:
        previous = {}
    previous_alerts = previous.get("alerts")
    active: dict[str, dict[str, object]] = (
        {
            code: dict(value)
            for code, value in previous_alerts.items()
            if isinstance(code, str) and isinstance(value, dict)
        }
        if isinstance(previous_alerts, dict)
        else {}
    )
    previous_telegram = previous.get("telegram")
    telegram: dict[str, object] = (
        dict(previous_telegram) if isinstance(previous_telegram, dict) else {}
    )

    record: dict[str, object] = {
        "checked_at": format_time(moment),
        "found_warnings": sorted(found),
        **details,
        "disks": disks,
        "tls_certificate_expires_at": certificate_expires_at,
        "alerts": active,
        "telegram": telegram,
    }
    files = read_all_status(config.status_directory)
    files["checks"] = record
    warnings = evaluate_warnings(files, moment, config.thresholds)
    critical = {warning.code: warning for warning in warnings if warning.critical}

    previous_pending = previous.get("ended_pending")
    pending: dict[str, dict[str, object]] = (
        {
            code: dict(value)
            for code, value in previous_pending.items()
            if isinstance(code, str) and isinstance(value, dict)
        }
        if isinstance(previous_pending, dict)
        else {}
    )

    def retry_due(entry: dict[str, object]) -> bool:
        last_attempt = parse_time(entry.get("last_attempt_at"))
        return last_attempt is None or moment - last_attempt >= RETRY_INTERVAL

    # NEW until a message about it was delivered (tried again at most once an hour), then
    # STILL every `repeat_hours`; FIXED once it ends, kept until that message is delivered.
    starting: list[HealthWarning] = []
    ongoing: list[HealthWarning] = []
    for code, warning in critical.items():
        pending.pop(code, None)
        entry = active.get(code)
        if entry is None:
            starting.append(warning)
            continue
        last_sent = parse_time(entry.get("last_sent_at"))
        if last_sent is None:
            if retry_due(entry):
                starting.append(warning)
        elif moment - last_sent >= config.repeat_interval:
            ongoing.append(warning)
    for code in [code for code in active if code not in critical]:
        entry = active.pop(code)
        if entry.get("last_sent_at") is not None:
            pending[code] = {}
    ended = sorted(code for code, entry in pending.items() if retry_due(entry))

    outcome: DeliveryOutcome | None = None
    if starting or ongoing or ended:
        lines = alert_lines(starting, ongoing, ended)
        outcome = (
            send_alert(config.telegram, lines)
            if post_form is None
            else send_alert(config.telegram, lines, post_form=post_form)
        )
        telegram["last_attempt_at"] = format_time(moment)
        telegram["last_delivery_outcome"] = outcome
        telegram["configured"] = outcome != "not_configured"
    else:
        # Nothing to send: still note whether Telegram is set up, for the health page.
        telegram["configured"] = load_telegram_target(config.telegram) is not None

    for code in critical:
        active.setdefault(code, {"since": format_time(moment)})
    for warning in [*starting, *ongoing]:
        active[warning.code]["last_attempt_at"] = format_time(moment)
        if outcome == "sent":
            active[warning.code]["last_sent_at"] = format_time(moment)
    for code in ended:
        if outcome == "sent":
            pending.pop(code)
        else:
            pending[code]["last_attempt_at"] = format_time(moment)

    record["ended_pending"] = pending
    record["alerts"] = active
    record["telegram"] = telegram
    write_status(config.status_directory, "checks", record)
    files["checks"] = record
    final_warnings = evaluate_warnings(files, moment, config.thresholds)
    log_event(
        "operations_check.completed",
        warnings=[warning.code for warning in final_warnings],
        telegram=outcome,
    )
    return final_warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="property-rental-ops-check")
    parser.add_argument("--config", type=Path, required=True, help="production-operations.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="check, record and send alerts")
    migration = commands.add_parser("record-migration", help="record a database update outcome")
    migration.add_argument("--outcome", choices=("succeeded", "failed"), required=True)
    migration.add_argument("--revision", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        config = load_operations_config(arguments.config)
    except OperationsConfigError as error:
        log_event("operations_check.config_invalid", detail=str(error))
        return 2
    if arguments.command == "record-migration":
        now = format_time(utc_now())
        try:
            previous = read_status(config.status_directory, "migration") or {}
        except StatusFileError:
            previous = {}
        write_status(
            config.status_directory,
            "migration",
            {
                "last_attempt_at": now,
                "last_outcome": arguments.outcome,
                "last_success_at": now
                if arguments.outcome == "succeeded"
                else previous.get("last_success_at"),
                "revision": arguments.revision,
            },
        )
        log_event("operations_check.migration_recorded", outcome=arguments.outcome)
        return 0
    run_check(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
