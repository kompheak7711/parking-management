#!/usr/bin/env python3
"""Generate a concise, model-free daily owner report."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path


def effective_next_action(state: dict[str, object]) -> str:
    """Apply approved-state handoff invariants without a model call."""
    status = state.get("status")
    approval = state.get("approval") or {}
    candidate = state.get("next_candidate") or {}
    if (
        status in {"complete_uncommitted", "complete_unpublished"}
        and isinstance(approval, dict)
        and approval.get("status") == "approved_ready"
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


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def automation_preflight() -> dict[str, object]:
    """Read executable state normalization so reporting matches dispatch behavior."""
    try:
        output = subprocess.check_output(
            [str(REPO / "scripts/openclaw-supervisor-preflight.sh")],
            cwd=REPO,
            text=True,
        )
        return json.loads(output)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def main() -> None:
    state = json.loads((REPO / "ops/STATE.json").read_text())
    preflight = automation_preflight()
    with sqlite3.connect(STATE_DB) as connection:
        supervisor = connection.execute(
            """SELECT enabled, last_run_at_ms, last_run_status, consecutive_errors,
                      running_at_ms FROM cron_jobs WHERE job_id = ?""",
            (SUPERVISOR_ID,),
        ).fetchone()
        entries = connection.execute(
            "SELECT entry_json FROM cron_run_logs WHERE job_id = ? AND ts >= ?",
            (SUPERVISOR_ID, int((time.time() - 86400) * 1000)),
        ).fetchall()

    enabled, last_run_ms, last_status, errors, running_ms = supervisor or (
        0,
        None,
        "missing",
        0,
        None,
    )
    recent_totals = []
    for (entry,) in entries:
        totals = [
            int(value) for value in re.findall(r'\\?"total\\?"\s*:\s*(\d+)', entry)
        ]
        if totals:
            recent_totals.append(max(totals))

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
    if preflight.get("actionable") is True:
        idle_reason = "Approved work is active or queued"
    elif state_issue == "published_compact_state_reconciliation_required":
        idle_reason = "Published compact state requires reconciliation"
    elif status in {
        "approved_ready",
        "active",
        "in_progress",
        "complete_uncommitted",
        "complete_unpublished",
        "failed",
        "not_verified",
        "discrepancy",
        "repair_required",
    }:
        idle_reason = (
            "Bounded automatic repair is active or queued"
            if state_issue == "bounded_automatic_repair_authorized"
            else "Approved work is active or queued"
        )
    elif candidate.get("status") == "not_approved" or "approval" in next_action.lower():
        idle_reason = "Intentionally waiting for owner approval"
    elif state.get("blockers"):
        idle_reason = "Blocked; owner attention may be required"
    else:
        idle_reason = "No actionable work is recorded"

    last_run = (
        "never"
        if not last_run_ms
        else datetime.fromtimestamp(last_run_ms / 1000)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M %Z")
    )
    health = (
        "HEALTHY"
        if enabled and last_status == "ok" and not errors
        else "ATTENTION REQUIRED"
    )
    activity = "working now" if running_ms else "idle between checks"
    token_text = (
        f"{sum(recent_totals):,} tokens across {len(recent_totals)} model cycle(s)"
        if recent_totals
        else "0 model tokens; checks were token-free"
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
    print(
        f"Git: {branch} at {head}; {'synchronized' if synchronized else 'not synchronized'}; worktree {'clean' if clean else 'changed'}"
    )
    print(f"Last meaningful state update: {state.get('timestamp', 'Not recorded')}")
    print(f"Model usage in last 24 hours: {token_text}")
    print(f"Reason idle: {idle_reason}")
    print(f"Blockers: {'None' if not blockers else '; '.join(map(str, blockers))}")
    print(f"Exact next action: {next_action}")
    print()
    print("Commits in the last 24 hours:")
    print(commits)


if __name__ == "__main__":
    main()
