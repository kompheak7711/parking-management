#!/usr/bin/env python3
"""Emit only new Property Rental automation events for Telegram delivery."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO = Path(os.environ.get("PROPERTY_RENTAL_REPO", Path(__file__).resolve().parents[1]))
STATE_DB = Path(
    os.environ.get(
        "PROPERTY_RENTAL_OPENCLAW_DB", Path.home() / ".openclaw/state/openclaw.sqlite"
    )
)
LEDGER_DIR = Path(
    os.environ.get(
        "PROPERTY_RENTAL_WATCHDOG_STATE_DIR",
        Path.home() / ".openclaw/state/property-rental-visibility",
    )
)
SUPERVISOR_ID = os.environ.get(
    "PROPERTY_RENTAL_SUPERVISOR_ID", "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb"
)
NOW_MS = int(os.environ.get("PROPERTY_RENTAL_NOW_MS", str(int(time.time() * 1000))))
STALE_MS = int(os.environ.get("PROPERTY_RENTAL_STALE_MS", str(2 * 60 * 60 * 1000)))
HEARTBEAT_MS = int(os.environ.get("PROPERTY_RENTAL_HEARTBEAT_MS", str(75 * 60 * 1000)))
EXHAUSTED_DIR = Path(
    os.environ.get(
        "PROPERTY_RENTAL_REPAIR_EXHAUSTED_DIR",
        Path.home()
        / ".openclaw/state/property-rental-supervisor-dispatch/repair-exhausted",
    )
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def load_ledger() -> dict[str, str]:
    path = LEDGER_DIR / "events.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_ledger(ledger: dict[str, str]) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / "events.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, sort_keys=True) + "\n")
    temporary.replace(path)


def supervisor() -> dict[str, object]:
    with sqlite3.connect(STATE_DB) as connection:
        row = connection.execute(
            """SELECT enabled, last_run_at_ms, last_run_status, consecutive_errors,
                      running_at_ms
                 FROM cron_jobs WHERE job_id = ?""",
            (SUPERVISOR_ID,),
        ).fetchone()
    if row is None:
        return {
            "enabled": False,
            "last_run": None,
            "status": "missing",
            "errors": 0,
            "running": None,
        }
    return {
        "enabled": bool(row[0]),
        "last_run": row[1],
        "status": row[2] or "unknown",
        "errors": row[3] or 0,
        "running": row[4],
    }


def emit_once(
    ledger: dict[str, str], category: str, signature: str, message: str
) -> None:
    if ledger.get(category) == signature:
        return
    print(message)
    ledger[category] = signature


def effective_next_action(state: dict[str, object]) -> str:
    """Apply the same approved-state handoff invariants as model-free preflight."""
    status = state.get("status")
    approval = state.get("approval") or {}
    candidate = state.get("next_candidate") or {}
    if (
        status
        in {
            "verified_unpublished",
            "complete_uncommitted",
            "complete_unpublished",
            "implemented_awaiting_supervisor_review",
        }
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
    return "No next action is recorded."


def automation_preflight() -> dict[str, object]:
    """Read executable state normalization so owner alerts match dispatch behavior."""
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
    service = supervisor()
    ledger = load_ledger()
    head = git("rev-parse", "--short", "HEAD")
    phase = state.get("phase", "unrecorded phase")
    status = state.get("status", "unknown")
    next_action = str(preflight.get("next_action") or effective_next_action(state))
    state_issue = preflight.get("state_issue")
    candidate = state.get("next_candidate") or {}

    exhausted_records = sorted(EXHAUSTED_DIR.glob("*.json"))
    for exhausted_path in exhausted_records:
        try:
            exhausted = json.loads(exhausted_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if exhausted.get("status") != "repair_exhausted":
            continue
        if exhausted.get("next_action") != next_action:
            continue
        signature = str(exhausted.get("attempt_key") or exhausted_path.stem)
        emit_once(
            ledger,
            "repair_exhausted",
            signature,
            "REPAIR_EXHAUSTED — Property Rental automation stopped after its bounded "
            f"attempt limit for {exhausted.get('phase', 'the active tranche')}. "
            f"Exact next action: {exhausted.get('next_action', 'Investigate the saved attempts before retrying.')}",
        )
        if not exhausted.get("alerted"):
            exhausted["alerted"] = True
            temporary = exhausted_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(exhausted, sort_keys=True) + "\n")
            temporary.replace(exhausted_path)
        break
    if not exhausted_records:
        ledger.pop("repair_exhausted", None)

    last_run = service["last_run"]
    healthy = bool(
        service["enabled"]
        and last_run
        and NOW_MS - int(last_run) <= HEARTBEAT_MS
        and service["status"] == "ok"
        and int(service["errors"]) == 0
    )
    health_signature = "healthy" if healthy else json.dumps(service, sort_keys=True)
    prior_health = ledger.get("health")
    if not healthy:
        emit_once(
            ledger,
            "health",
            health_signature,
            "AUTOMATION_HEALTH — Property Rental supervisor is not healthy. "
            f"Enabled: {service['enabled']}; last status: {service['status']}; "
            f"consecutive errors: {service['errors']}. Investigation is required.",
        )
    elif prior_health and prior_health != "healthy":
        print(
            "SCHEDULER_RECOVERED — Property Rental supervisor scheduling is healthy again. "
            "This confirms scheduled checks resumed; it does not resolve any separate project discrepancy or blocker."
        )
        ledger["health"] = "healthy"
    else:
        ledger["health"] = "healthy"

    if state_issue == "published_compact_state_reconciliation_required":
        emit_once(
            ledger,
            "state_reconciliation",
            f"{head}:{state.get('commit', '')}",
            "STATE_RECONCILIATION_REQUIRED — The published repository is ahead of its "
            f"pre-publication compact state. Exact next action: {next_action}",
        )
    else:
        ledger.pop("state_reconciliation", None)

    if state_issue == "handoff_missing":
        emit_once(
            ledger,
            "handoff_missing",
            f"{phase}:{head}:{next_action}",
            "HANDOFF_MISSING — Property Rental published work has durable authorization "
            "but no unique safe structured successor. "
            f"Exact next action: {next_action}",
        )
    else:
        ledger.pop("handoff_missing", None)

    if status == "published":
        published_commit = str(state.get("commit") or head)[:7]
        signature = f"{phase}:{published_commit}"
        roadmap = state.get("roadmap") or {}
        roadmap_id = str(roadmap.get("current_id") or "unrecorded")
        roadmap_total = roadmap.get("total")
        roadmap_progress = ""
        try:
            roadmap_data = json.loads((REPO / "ops/V1_ROADMAP.json").read_text())
            tranches = roadmap_data.get("tranches") or []
            complete = sum(item.get("status") == "complete" for item in tranches)
            total = int(roadmap_total or roadmap_data.get("total_tranches") or len(tranches))
            roadmap_progress = f" Roadmap progress: {complete}/{total} complete; current {roadmap_id}."
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            if roadmap_total:
                roadmap_progress = f" Roadmap current: {roadmap_id} of {roadmap_total}."
        approval_waiting = (
            candidate.get("status") == "not_approved"
            or "approval" in next_action.lower()
        )
        suffix = (
            f" Waiting for owner approval. Exact next action: {next_action}"
            if approval_waiting
            else f" Next: {next_action}"
        )
        emit_once(
            ledger,
            "publication",
            signature,
            f"PHASE_COMPLETED — Property Rental {phase} is independently verified, "
            f"committed, pushed, and published at {published_commit}."
            f"{roadmap_progress}{suffix}",
        )

    if status in {
        "approved_ready",
        "active",
        "in_progress",
        "verified_unpublished",
        "complete_uncommitted",
        "complete_unpublished",
        "failed",
        "not_verified",
        "discrepancy",
        "repair_required",
    }:
        timestamp = state.get("timestamp")
        try:
            updated_ms = int(
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
                * 1000
            )
        except (AttributeError, TypeError, ValueError):
            updated_ms = 0
        if updated_ms and NOW_MS - updated_ms > STALE_MS and not service["running"]:
            signature = f"{phase}:{status}:{timestamp}:{head}"
            emit_once(
                ledger,
                "stall",
                signature,
                f"STALLED — Property Rental {phase} is approved/active but has recorded no progress for more than two hours. "
                f"Current commit: {head}. Next action: {next_action}",
            )
        else:
            ledger.pop("stall", None)

    save_ledger(ledger)


if __name__ == "__main__":
    main()
