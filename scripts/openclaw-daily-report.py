#!/usr/bin/env python3
"""Generate a concise, model-free daily owner report."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from openclaw_automation import (
    post_restoration_scheduler_ok,
    stage_actionable_fingerprint,
)


def effective_next_action(state: dict[str, object]) -> str:
    """Apply approved-state handoff invariants without a model call."""
    status = state.get("status")
    approval = state.get("approval") or {}
    candidate = state.get("next_candidate") or {}
    if (
        isinstance(approval, dict)
        and approval.get("status") == "approved_ready"
        and approval.get("implementation_completed") is True
        and approval.get("publication_completed") is not True
        and not state.get("blockers")
    ):
        return (
            "Independently verify and publish the completed bounded tranche under "
            "standing authorization, then dispatch the next approved candidate."
        )
    recorded = state.get("next_action")
    if recorded:
        return str(recorded)
    if (
        status == "approved_ready"
        and isinstance(candidate, dict)
        and candidate.get("status") == "approved_ready"
        and candidate.get("task")
        and not state.get("blockers")
    ):
        return f"Implement the approved bounded candidate: {candidate['task']}"
    return "Missing — automation state requires repair."


REPO = Path(os.environ.get("PROPERTY_RENTAL_REPO", Path(__file__).resolve().parents[1]))
STATE_DB = Path(
    os.environ.get(
        "PROPERTY_RENTAL_OPENCLAW_DB", Path.home() / ".openclaw/state/openclaw.sqlite"
    )
)
SUPERVISOR_ID = os.environ.get(
    "PROPERTY_RENTAL_SUPERVISOR_ID", "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb"
)
INSTALLED_WRAPPER = Path(
    os.environ.get(
        "PROPERTY_RENTAL_INSTALLED_HERMES_WRAPPER",
        Path.home()
        / ".openclaw/workspaces/property-rental-supervisor/bin/hermes-property-rental",
    )
)
USAGE_LEDGER = Path(
    os.environ.get(
        "PROPERTY_RENTAL_MODEL_USAGE_LEDGER",
        Path.home()
        / ".openclaw/state/property-rental-supervisor-dispatch-v2/model-usage.jsonl",
    )
)
REPAIR_EXHAUSTED_DIR = Path(
    os.environ.get(
        "PROPERTY_RENTAL_REPAIR_EXHAUSTED_DIR",
        Path.home()
        / ".openclaw/state/property-rental-supervisor-dispatch-v2/terminal/repair_exhausted",
    )
)
DISPATCH_STATE_DIR = Path(
    os.environ.get(
        "PROPERTY_RENTAL_DISPATCH_STATE_DIR",
        Path.home() / ".openclaw/state/property-rental-supervisor-dispatch-v2",
    )
)
NOW_MS = int(os.environ.get("PROPERTY_RENTAL_NOW_MS", str(int(time.time() * 1000))))
HEARTBEAT_MS = int(os.environ.get("PROPERTY_RENTAL_HEARTBEAT_MS", str(75 * 60 * 1000)))


def recent_model_usage(now: float | None = None) -> tuple[list[int], int, list[int]]:
    """Read actual dispatcher usage records from the last 24 hours."""
    cutoff = (time.time() if now is None else now) - 86400
    totals: list[int] = []
    cache_totals: list[int] = []
    unavailable = 0
    try:
        lines = USAGE_LEDGER.read_text().splitlines()
    except OSError:
        return totals, unavailable, cache_totals
    for line in lines:
        try:
            record = json.loads(line)
            timestamp = datetime.fromisoformat(
                str(record["timestamp"]).replace("Z", "+00:00")
            ).timestamp()
            raw_tokens = record.get("total_token_usage", record.get("total_tokens"))
            raw_cache = record.get(
                "cache_read_token_usage", record.get("cache_read_tokens")
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if timestamp < cutoff:
            continue
        if isinstance(raw_cache, int) and raw_cache >= 0:
            cache_totals.append(raw_cache)
        if raw_tokens == "unavailable from provider" or raw_tokens is None:
            unavailable += 1
            continue
        try:
            tokens = int(raw_tokens)
        except (TypeError, ValueError):
            unavailable += 1
            continue
        if tokens >= 0:
            totals.append(tokens)
    return totals, unavailable, cache_totals


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, stderr=subprocess.DEVNULL
    ).strip()


def automation_preflight() -> dict[str, object]:
    """Read executable state normalization so reporting matches dispatch behavior."""
    try:
        output = subprocess.check_output(
            [str(REPO / "scripts/openclaw-supervisor-preflight.sh")],
            cwd=REPO,
            text=True,
        )
        value = json.loads(output)
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        return {}
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def supervisor_status() -> dict[str, object]:
    """Apply the exact same schedule and installed-wrapper contract as readiness."""
    try:
        with sqlite3.connect(STATE_DB) as connection:
            count = connection.execute(
                "SELECT count(*) FROM cron_jobs WHERE name='property-rental-24x7-supervisor'"
            ).fetchone()[0]
            row = connection.execute(
                """SELECT name, enabled, schedule_kind, every_ms, payload_kind,
                          payload_message, last_run_at_ms, last_run_status,
                          consecutive_errors, running_at_ms, updated_at
                     FROM cron_jobs WHERE job_id = ?""",
                (SUPERVISOR_ID,),
            ).fetchone()
    except (sqlite3.Error, OSError):
        return {"present": False, "enabled": False, "config_valid": False}
    if row is None:
        return {"present": False, "enabled": False, "config_valid": False}
    payload_message = row[5] if isinstance(row[5], str) else None
    try:
        authoritative_prompt = (
            REPO / "ops/OPENCLAW_SUPERVISOR_PROMPT.md"
        ).read_text()
    except OSError:
        authoritative_prompt = None
    return {
        "present": True,
        "enabled": bool(row[1]),
        "config_valid": bool(
            count == 1
            and row[0] == "property-rental-24x7-supervisor"
            and row[2] == "every"
            and row[3] == 1800000
            and row[4] == "agentTurn"
            and payload_message == authoritative_prompt
        ),
        "last_run": row[6],
        "status": row[7] or "unknown",
        "errors": row[8] or 0,
        "running": row[9],
        "restored_at": row[10],
    }


def main() -> None:
    state = json.loads((REPO / "ops/STATE.json").read_text())
    preflight = automation_preflight()
    service = supervisor_status()
    installed = bool(service.get("present"))
    enabled = bool(service.get("enabled"))
    config_valid = bool(service.get("config_valid"))
    last_run_ms = service.get("last_run")
    last_status = service.get("status", "missing")
    errors = service.get("errors", 0)
    running_ms = service.get("running")
    restored_at_ms = service.get("restored_at")
    recent_totals, unavailable_totals, recent_cache_totals = recent_model_usage()

    head = git("rev-parse", "--short", "HEAD")
    branch = git("branch", "--show-current")
    clean = not git("status", "--porcelain=v1")
    try:
        synchronized = git("rev-parse", "HEAD") == git("rev-parse", "@{upstream}")
    except subprocess.CalledProcessError:
        synchronized = False
    commits = git("log", "--since=24 hours ago", "--format=- %h %s", "-5")
    next_action = str(preflight.get("next_action") or effective_next_action(state))
    state_issue = preflight.get("state_issue")
    status = state.get("status", "unknown")
    candidate = state.get("next_candidate") or {}
    candidate_id = str(
        candidate.get("roadmap_id")
        or candidate.get("id")
        or (state.get("roadmap") or {}).get("current_id")
        or "unknown"
    )
    stage = "idle"
    stage_path = DISPATCH_STATE_DIR / "candidates" / f"{candidate_id}.json"
    if stage_path.exists():
        try:
            stage_record = json.loads(stage_path.read_text())
            stage = str(stage_record.get("stage") or "idle")
        except (OSError, json.JSONDecodeError):
            stage = "state_reconciliation_required"
    actionable = stage_actionable_fingerprint(
        REPO, preflight, candidate=candidate_id, stage=stage
    )
    exhausted_path = REPAIR_EXHAUSTED_DIR / f"{actionable}.json"
    try:
        exhausted = json.loads(exhausted_path.read_text())
        repair_exhausted = exhausted.get("status") == "repair_exhausted"
    except (OSError, json.JSONDecodeError):
        repair_exhausted = False
    if repair_exhausted:
        automation_state = "REPAIR_EXHAUSTED"
        idle_reason = "A bounded repair fingerprint exhausted its permitted attempts"
    elif preflight.get("owner_action_required") is True:
        automation_state = "WAITING_FOR_OWNER"
        idle_reason = "A structured owner decision is required"
    elif state_issue == "handoff_missing":
        automation_state = "HANDOFF_MISSING"
        idle_reason = "Durable authorization exists, but no unique safe structured successor is recorded"
    elif preflight.get("actionable") is True:
        automation_state = "AUTHORIZED_WORK_QUEUED"
        idle_reason = "Approved work is active or queued"
    elif state_issue == "published_compact_state_reconciliation_required":
        automation_state = "AUTHORIZED_WORK_QUEUED"
        idle_reason = "Published compact state requires reconciliation"
    elif status in {
        "approved_ready",
        "active",
        "in_progress",
        "verified_unpublished",
        "complete_uncommitted",
        "complete_unpublished",
        "implemented_awaiting_supervisor_review",
        "failed",
        "not_verified",
        "discrepancy",
        "repair_required",
    }:
        automation_state = "AUTHORIZED_WORK_QUEUED"
        idle_reason = (
            "Bounded automatic repair is active or queued"
            if state_issue == "bounded_automatic_repair_authorized"
            else "Approved work is active or queued"
        )
    else:
        automation_state = "IDLE"
        idle_reason = "No actionable work is recorded"
    if running_ms:
        automation_state = "WORKING"

    last_run = "never"
    if isinstance(last_run_ms, int) and last_run_ms:
        last_run = (
            datetime.fromtimestamp(last_run_ms / 1000)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M %Z")
        )
    if not installed:
        health = "UNHEALTHY — SCHEDULE MISSING"
    elif not config_valid:
        health = "UNHEALTHY — SCHEDULE CONFIGURATION MISMATCH"
    elif not enabled:
        health = "INTENTIONALLY DISABLED"
    elif post_restoration_scheduler_ok(
        enabled=enabled,
        last_run_ms=last_run_ms,
        last_status=last_status,
        consecutive_errors=errors,
        restored_at_ms=restored_at_ms,
        now_ms=NOW_MS,
        heartbeat_ms=HEARTBEAT_MS,
    ):
        health = "HEALTHY"
    else:
        health = "UNHEALTHY"
    activity = "working now" if running_ms else "idle between checks"
    if unavailable_totals:
        token_text = (
            f"{sum(recent_totals):,} observed tokens across {len(recent_totals)} model cycle(s); "
            f"{unavailable_totals} model cycle(s) unavailable from provider"
        )
    elif recent_totals:
        token_text = (
            f"{sum(recent_totals):,} tokens across {len(recent_totals)} model cycle(s)"
        )
    else:
        token_text = "0 model tokens; no model cycle was recorded"
    cache_text = (
        f"{sum(recent_cache_totals):,} cache-read tokens (reported separately; not double-counted)"
        if recent_cache_totals
        else "0 cache-read tokens reported separately"
    )
    if not commits:
        commits = f"- No commits; reason: {idle_reason}"

    blockers = state.get("blockers") or []
    print(
        f"Property Rental daily report — {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"
    )
    print()
    print(f"Automation: {health}; {activity}")
    print(
        f"Last supervisor check: {last_run} — {last_status}; consecutive errors: {errors}"
    )
    print(f"Current: {state.get('phase', 'Not recorded')} — {status}")
    roadmap = preflight.get("roadmap") or {}
    if isinstance(roadmap, dict) and roadmap.get("total"):
        current_id = roadmap.get("current_id") or "unmapped"
        complete_count = int(roadmap.get("completed") or 0)
        if status == "published" and roadmap.get("current_status") != "complete":
            complete_count = min(complete_count + 1, int(roadmap["total"]))
        print(
            f"V1 roadmap: {complete_count}/{roadmap['total']} complete; current {current_id}"
        )
    print(
        f"Git: {branch} at {head}; {'synchronized' if synchronized else 'not synchronized'}; worktree {'clean' if clean else 'changed'}"
    )
    print(f"Last meaningful state update: {state.get('timestamp', 'Not recorded')}")
    print(f"Model usage in last 24 hours: {token_text}; {cache_text}")
    print(f"Workflow state: {automation_state}")
    print(f"Reason idle: {idle_reason}")
    print(f"Blockers: {'None' if not blockers else '; '.join(map(str, blockers))}")
    print(f"Exact next action: {next_action}")
    print()
    print("Commits in the last 24 hours:")
    print(commits)


if __name__ == "__main__":
    main()
