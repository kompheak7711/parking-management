#!/usr/bin/env python3
"""Model-light deterministic stage dispatcher for the Property Rental roadmap."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from openclaw_automation import (
    FAILURE_CATEGORIES,
    RECOVERABLE_ROUTING_FAILURES,
    SECRET_PATTERN,
    AutomationError,
    ModelPolicy,
    atomic_write_json,
    atomic_write_text,
    changed_paths,
    compact_state_fingerprint,
    consume_attempt,
    consume_continuation,
    digest,
    failure_owner_action_required,
    git,
    hermes_chat_usage,
    model_policy,
    normalize_usage,
    persist_terminal_marker,
    preservation_evidence,
    process_fingerprint,
    preserved_paths_fingerprint,
    release_attempt,
    relevant_processes,
    repeated_call_key,
    repeated_call_result,
    repository_fingerprint,
    reserve_attempt,
    stage_actionable_fingerprint,
    task_packet,
    utc_now,
    validate_usage,
    v1_019_routing_identity as record_routing_identity,
)
from openclaw_hermes_guard import create_manifest

REPO = Path(
    os.environ.get(
        "PROPERTY_RENTAL_REPO",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()
STATE_DIR = Path(
    os.environ.get(
        "PROPERTY_RENTAL_DISPATCH_STATE_DIR",
        "/Users/sokompheak/.openclaw/state/property-rental-supervisor-dispatch-v2",
    )
)
MAX_CYCLES = min(
    max(int(os.environ.get("PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES", "6")), 1), 6
)
RECONCILIATION_NEXT_ACTION = (
    "Select the exact structured approved successor from ops/V1_ROADMAP.json "
    "without a model; do not reimplement the published candidate."
)
MAX_CEILING_RECOVERIES_PER_SUBSTAGE = 2
MAX_CONTEXT_MATERIALIZATIONS_PER_SUBSTAGE = 2
MAX_REVIEW_PATCH_BYTES = 160_000
V1_019_SUBSTAGES: tuple[dict[str, Any], ...] = (
    {
        "id": "sign_in",
        "order": 1,
        "total": 4,
        "task": "Local sign-in and enumeration-safe authentication UI",
        "include": [
            "local username/password sign-in",
            "generic failure and recovery responses",
        ],
    },
    {
        "id": "mfa_recovery",
        "order": 2,
        "total": 4,
        "task": "MFA enrollment/challenge and protected recovery UI",
        "include": [
            "MFA enrollment and challenge",
            "recovery codes",
            "administrative recovery",
        ],
    },
    {
        "id": "sessions",
        "order": 3,
        "total": 4,
        "task": "Session expiry, reauthentication, and revocation UI",
        "include": [
            "inactivity and absolute expiry",
            "reauthentication",
            "session revocation",
        ],
    },
    {
        "id": "account_capability",
        "order": 4,
        "total": 4,
        "task": "Account, role-bundle, capability, and authorization-history UI",
        "include": [
            "account administration",
            "capability-sensitive controls",
            "authorization history",
        ],
    },
)
V1_020_SUBSTAGES: tuple[dict[str, Any], ...] = (
    {
        "id": "authentication_core",
        "order": 1,
        "total": 7,
        "task": "Authentication core and password-security hardening tests",
        "include": ["TEST-108", "SEC-068 through SEC-070"],
    },
    {
        "id": "authentication_api",
        "order": 2,
        "total": 7,
        "task": "Authentication API input and browser-security hardening",
        "include": ["TEST-109", "SEC-068 through SEC-070"],
    },
    {
        "id": "sensitive_data_and_privileges",
        "order": 3,
        "total": 7,
        "task": "Sensitive-data leakage and database-privilege hardening tests",
        "include": ["TEST-110", "TEST-111", "SEC-068", "SEC-069"],
    },
    {
        "id": "mfa_policy",
        "order": 4,
        "total": 7,
        "task": "MFA policy and TOTP hardening tests",
        "include": ["TEST-128", "MFA audit and rejection coverage"],
    },
    {
        "id": "recovery",
        "order": 5,
        "total": 7,
        "task": "Recovery-code and administrative-recovery hardening tests",
        "include": ["TEST-129", "TEST-130", "SEC-071", "SEC-072"],
    },
    {
        "id": "sessions_integration",
        "order": 6,
        "total": 7,
        "task": "Session, reauthentication, and authentication integration tests",
        "include": ["TEST-131", "TEST-132", "TEST-135"],
    },
    {
        "id": "bootstrap_release",
        "order": 7,
        "total": 7,
        "task": "Initial Owner bootstrap and release-gate hardening tests",
        "include": ["TEST-133", "TEST-134", "SEC-073 through SEC-075"],
    },
)
CANDIDATE_SUBSTAGES: dict[str, tuple[dict[str, Any], ...]] = {
    "V1-019": V1_019_SUBSTAGES,
    "V1-020": V1_020_SUBSTAGES,
}


def run(
    *arguments: str, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=REPO,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def command_json(*arguments: str) -> dict[str, Any]:
    result = run(*arguments)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"invalid JSON from deterministic command {arguments[0]!r}",
        ) from error
    if not isinstance(value, dict):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "deterministic command returned non-object JSON",
        )
    return value


def git_document(commit: str, relative: str) -> str:
    return git(REPO, "show", f"{commit}:{relative}") + "\n"


def replace_automation_status(source: str, lines: list[str]) -> str:
    kept: list[str] = []
    skipping = False
    for line in source.splitlines():
        if line == "<!-- AUTOMATION_STATUS_BEGIN -->":
            skipping = True
            continue
        if line == "<!-- AUTOMATION_STATUS_END -->":
            skipping = False
            continue
        if not skipping:
            kept.append(line)
    return "".join(f"{line}\n" for line in kept + lines)


def valid_dynamic_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value)
    )


def exact_reconciliation_contract(
    *, base: str, branch: str, state: dict[str, Any], now: str
) -> bool:
    try:
        expected_state = json.loads(git_document(base, "ops/STATE.json"))
        base_now = git_document(base, "ops/NOW.md")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    timestamp = state.get("timestamp")
    if not valid_dynamic_timestamp(timestamp):
        return False
    expected_state["status"] = "published"
    approval = expected_state.setdefault("approval", {})
    if not isinstance(approval, dict):
        return False
    approval["publication_completed"] = True
    expected_state.update(
        {
            "branch": branch,
            "commit": base,
            "timestamp": timestamp,
            "next_action": RECONCILIATION_NEXT_ACTION,
            "idle_reason": "published candidate awaits deterministic successor selection",
            "owner_action": "none",
        }
    )
    expected_now = replace_automation_status(
        base_now,
        [
            "<!-- AUTOMATION_STATUS_BEGIN -->",
            f"- Automation publication state: published on {branch} at {base}.",
            f"- Automation exact next action: {RECONCILIATION_NEXT_ACTION}",
            "<!-- AUTOMATION_STATUS_END -->",
        ],
    )
    return state == expected_state and now == expected_now


def ascii_slug(value: str) -> str:
    lowered = value.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", lowered))


def activation_documents(
    *,
    base: str,
    prior_candidate_id: str,
    candidate: dict[str, Any],
    timestamp: str,
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    try:
        expected_state = json.loads(git_document(base, "ops/STATE.json"))
        expected_roadmap = json.loads(git_document(base, "ops/V1_ROADMAP.json"))
        base_now = git_document(base, "ops/NOW.md")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    candidate_id = candidate.get("id")
    task = candidate.get("task")
    phase = candidate.get("phase")
    if not (
        valid_dynamic_timestamp(timestamp)
        and isinstance(candidate_id, str)
        and candidate_id
        and isinstance(task, str)
        and task
        and isinstance(phase, str)
        and phase
    ):
        return None
    roadmap_state = expected_state.setdefault("roadmap", {})
    if not isinstance(roadmap_state, dict):
        return None
    roadmap_state["current_id"] = candidate_id
    roadmap_state["total"] = expected_roadmap.get("total_tranches")
    expected_state.update(
        {
            "next_candidate": {**candidate, "roadmap_id": candidate_id},
            "phase": phase,
            "tranche": task,
            "task": f"Implement the approved bounded candidate: {task}",
            "status": "active",
            "active_cycle": f"{candidate_id.lower()}-{ascii_slug(task)}",
            "risk_class": candidate.get("risk_class", "high"),
            "approval": {
                "status": "approved_ready",
                "basis": "structured durable-v1 successor selection",
                "implementation_started": False,
                "implementation_completed": False,
                "publication_completed": False,
            },
            "authorities": candidate.get("authorities", []),
            "touched_areas": candidate.get("include", []),
            "tests": [],
            "relevant_docs": candidate.get("authorities", []),
            "next_action": f"Implement the approved bounded candidate: {task}",
            "owner_action": "none",
            "idle_reason": None,
            "blockers": [],
            "repair": {
                "tranche_id": candidate_id,
                "failure": None,
                "scope_preserved": True,
                "attempts": 0,
                "max_attempts": 2,
                "requires_owner_decision": False,
                "suspected_secret": False,
                "scope_expansion": False,
                "protected_operation": False,
                "last_outcome": None,
            },
            "timestamp": timestamp,
        }
    )
    tranches = expected_roadmap.get("tranches")
    if not isinstance(tranches, list):
        return None
    roadmap_candidates = [
        item
        for item in tranches
        if isinstance(item, dict) and item.get("id") == candidate_id
    ]
    if len(roadmap_candidates) != 1 or roadmap_candidates[0] != candidate:
        return None
    for item in tranches:
        if isinstance(item, dict) and item.get("id") == prior_candidate_id:
            item["status"] = "complete"
            item["authorization"] = "complete"
    expected_now = replace_automation_status(
        base_now,
        [
            "<!-- AUTOMATION_STATUS_BEGIN -->",
            f"- Automation candidate state: {candidate_id} approved and active; implementation has not started.",
            f"- Automation exact next action: Implement the approved bounded candidate: {task}",
            "<!-- AUTOMATION_STATUS_END -->",
        ],
    )
    return expected_state, expected_roadmap, expected_now


def exact_activation_contract(
    *,
    base: str,
    prior_candidate_id: str,
    candidate: dict[str, Any],
    state: dict[str, Any],
    roadmap: dict[str, Any],
    now: str,
) -> bool:
    timestamp = state.get("timestamp")
    if not isinstance(timestamp, str):
        return False
    expected = activation_documents(
        base=base,
        prior_candidate_id=prior_candidate_id,
        candidate=candidate,
        timestamp=timestamp,
    )
    if expected is None:
        return False
    expected_state, expected_roadmap, expected_now = expected
    return (
        state == expected_state and roadmap == expected_roadmap and now == expected_now
    )


ACTIVATION_PATHS = (
    "ops/NOW.md",
    "ops/STATE.json",
    "ops/V1_ROADMAP.json",
)


def render_activation_documents(
    *,
    base: str,
    prior_candidate_id: str,
    candidate: dict[str, Any],
    timestamp: str,
) -> dict[str, str] | None:
    expected = activation_documents(
        base=base,
        prior_candidate_id=prior_candidate_id,
        candidate=candidate,
        timestamp=timestamp,
    )
    if expected is None:
        return None
    state, roadmap, now = expected
    return {
        "ops/NOW.md": now,
        "ops/STATE.json": json.dumps(state, indent=2) + "\n",
        "ops/V1_ROADMAP.json": json.dumps(roadmap, indent=2) + "\n",
    }


def git_blob(specification: str) -> str:
    return run("git", "show", specification).stdout


def validate_resumable_activation_files(
    *, base: str, expected: dict[str, str]
) -> list[str]:
    def matches(relative: str, content: str, permitted: set[str]) -> bool:
        if content in permitted:
            return True
        if not relative.endswith(".json"):
            return False
        try:
            parsed = json.loads(content)
            return any(parsed == json.loads(item) for item in permitted)
        except json.JSONDecodeError:
            return False

    allowed = set(ACTIVATION_PATHS)
    current = set(changed_paths(REPO))
    cached = set(run("git", "diff", "--cached", "--name-only").stdout.splitlines())
    if not current <= allowed or not cached <= allowed:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "resumed successor mutation has paths outside the activation contract",
        )
    expected_paths: list[str] = []
    for relative in ACTIVATION_PATHS:
        base_content = git_blob(f"{base}:{relative}")
        target_content = expected[relative]
        if base_content != target_content:
            expected_paths.append(relative)
        try:
            worktree_content = (REPO / relative).read_text()
        except OSError as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation target is unreadable",
            ) from error
        permitted = {base_content, target_content}
        if not matches(relative, worktree_content, permitted):
            raise AutomationError(
                "repository_integrity_uncertainty",
                f"resumed successor worktree content for {relative} is neither the base nor deterministic target",
            )
        if relative in cached:
            try:
                index_content = git_blob(f":{relative}")
            except subprocess.CalledProcessError as error:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    f"resumed successor index content for {relative} is unreadable",
                ) from error
            if not matches(relative, index_content, permitted):
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    f"resumed successor index content for {relative} is neither the base nor deterministic target",
                )
    return expected_paths


def process_identity(pid: int) -> dict[str, Any] | None:
    if os.environ.get("PROPERTY_RENTAL_TEST_PROCESS_ROWS") is not None:
        return {"pid": pid, "identity": digest(f"test-process:{pid}")}
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode or not result.stdout.strip():
        return None
    normalized = " ".join(result.stdout.split())
    return {"pid": pid, "identity": digest(normalized)}


class CycleLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.owner = path.with_suffix(".owner.json")
        self.descriptor: int | None = None
        self.acquired = False

    def __enter__(self) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, IsADirectoryError, OSError) as error:
            if self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
            raise AutomationError(
                "lock_or_overlapping_process_failure",
                "another supervisor cycle owns the atomic lock or its state is unprovable",
            ) from error
        if self.owner.exists():
            try:
                owner = json.loads(self.owner.read_text())
                current = process_identity(int(owner["pid"]))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
                os.close(self.descriptor)
                self.descriptor = None
                raise AutomationError(
                    "lock_or_overlapping_process_failure",
                    "existing lock owner metadata is unreadable or unprovable",
                ) from error
            if current and current.get("identity") == owner.get("identity"):
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
                os.close(self.descriptor)
                self.descriptor = None
                raise AutomationError(
                    "lock_or_overlapping_process_failure",
                    "a verified supervisor process still owns the lock identity",
                )
            self.owner.unlink()
        identity = process_identity(os.getpid())
        if identity is None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None
            raise AutomationError(
                "lock_or_overlapping_process_failure",
                "cannot verify lock owner identity",
            )
        atomic_write_json(
            self.owner,
            {**identity, "repo": str(REPO), "acquired_at": utc_now()},
        )
        self.acquired = True
        return self

    def __exit__(self, *_: object) -> None:
        if not self.acquired:
            return
        self.owner.unlink(missing_ok=True)
        assert self.descriptor is not None
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = None


def candidate_id() -> str:
    state = json.loads((REPO / "ops/STATE.json").read_text())
    candidate = state.get("next_candidate") or {}
    value = (
        candidate.get("roadmap_id")
        or candidate.get("id")
        or (state.get("roadmap") or {}).get("current_id")
    )
    if not isinstance(value, str) or not re.fullmatch(r"V1-\d{3}", value):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "compact state has no exact roadmap candidate",
        )
    return value


def authorized_branch() -> str:
    current = git(REPO, "branch", "--show-current")
    if not current:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "automation cannot run from a detached HEAD",
        )
    try:
        state = json.loads((REPO / "ops/STATE.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "automation cannot prove the authorized branch from compact state",
        ) from error
    expected = state.get("branch")
    if not isinstance(expected, str) or not expected:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "compact state has no nonempty authorized branch",
        )
    if current != expected:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"automation is authorized only on branch {expected}",
        )
    return current


def stage_file(candidate: str) -> Path:
    return STATE_DIR / "candidates" / f"{candidate}.json"


def load_stage(candidate: str) -> dict[str, Any]:
    path = stage_file(candidate)
    if not path.exists():
        return {
            "candidate": candidate,
            "stage": "reconciliation_dispatch",
            "created_at": utc_now(),
            "initial_repository_fingerprint": repository_fingerprint(REPO),
            "initial_changed_paths": changed_paths(REPO),
            "continuation_used": False,
            "events": [],
        }
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise AutomationError(
            "repository_integrity_uncertainty", "candidate evidence is not an object"
        )
    if value.get("candidate") != candidate:
        raise AutomationError(
            "repository_integrity_uncertainty", "candidate evidence identity mismatch"
        )
    return {str(key): item for key, item in value.items()}


def save_stage(record: dict[str, Any]) -> None:
    record["updated_at"] = utc_now()
    atomic_write_json(stage_file(str(record["candidate"])), record)


def pending_lifecycle_record() -> dict[str, Any] | None:
    directory = STATE_DIR / "candidates"
    if not directory.exists():
        return None
    pending: list[dict[str, Any]] = []
    for path in directory.glob("V1-*.json"):
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("stage") in {
            "post_publication_reconciliation",
            "next_candidate_activation",
        }:
            pending.append(value)
    if len(pending) > 1:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "multiple publication lifecycle records are pending",
        )
    return pending[0] if pending else None


def append_usage(record: dict[str, Any], usage: dict[str, Any]) -> None:
    path = STATE_DIR / "model-usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(usage, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    record.setdefault("model_usage", []).append(usage)


def finalize_usage(
    record: dict[str, Any],
    report: dict[str, Any],
    *,
    stage_result: str,
    exact_next_action: str,
) -> None:
    report.update(
        {
            "timestamp": utc_now(),
            "stage_result": stage_result,
            "exact_next_action": exact_next_action,
        }
    )
    append_usage(record, report)


def packet_prompt(packet: dict[str, Any]) -> str:
    stage = packet["stage"]
    introduction = (
        "Implement exactly this approved bounded candidate in the current repository."
        if stage in {"implementation", "direct_codex_recovery"}
        else "Independently review the complete candidate diff and durable verification evidence. Do not edit any file."
    )
    return (
        f"{introduction}\n"
        "The packet contains the complete repository-local continuity instructions and exact authoritative excerpts. "
        "Do not attempt to load an external skill. Trust the dispatcher-supplied branch, HEAD, fingerprints, and clean/preserved-state evidence; do not rediscover them with Git or process commands. "
        "When bounded_substage is present, implement only that substage and do not begin a later one in this session. "
        "The packet already materializes compact-state and canonical evidence: do not reread ops/NOW.md, ops/STATE.json, ops/QUEUE.md, ops/V1_ROADMAP.json, Makefile, or canonical documents. "
        "Use only directly_relevant_paths; do not call todo/planning tools or perform broad repository discovery. "
        "Do not load any supervisor transcript, earlier model reasoning, unrelated diff, raw log, or broad canonical set. "
        "For an implementation substage, do not invoke terminal, Git, npm, make, or verification commands; the execution-capable supervisor runs deterministic verification after your JSON result. "
        "A verification value of deferred_to_deterministic_supervisor is required and is not a blocker. "
        "Return only the required JSON object.\n\n"
        + json.dumps(packet, sort_keys=True, indent=2)
    )


def current_bounded_substage(record: dict[str, Any]) -> dict[str, Any] | None:
    substages = CANDIDATE_SUBSTAGES.get(str(record.get("candidate") or ""))
    if substages is None:
        return None
    completed = set(record.get("completed_implementation_substages") or [])
    return next(
        (dict(item) for item in substages if item["id"] not in completed),
        None,
    )


def active_restoration_boundary(record: dict[str, Any]) -> dict[str, Any] | None:
    path = STATE_DIR / "restoration/active-v1-019-boundary.json"
    if not path.exists():
        return None
    try:
        boundary = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the post-exit restoration boundary is unreadable",
        ) from error
    routing = record_routing_identity(record, "implementation")
    if (
        not isinstance(boundary, dict)
        or boundary.get("schema_version") != 1
        or boundary.get("status") not in {"active", "progress_verified"}
        or boundary.get("candidate") != "V1-019"
        or boundary.get("bounded_substage") != "sign_in"
        or boundary.get("routing_revision") != routing.get("revision")
        or boundary.get("candidate_base_commit") != record.get("candidate_base_commit")
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the post-exit restoration boundary drifted from V1-019 sign_in",
        )
    return boundary


def restoration_boundary_reached(record: dict[str, Any]) -> bool:
    boundary = active_restoration_boundary(record)
    if boundary is None:
        return False
    completed = record.get("completed_implementation_substages") or []
    if completed[:1] != ["sign_in"]:
        return False
    boundary.update(
        {
            "status": "progress_verified",
            "verified_at": utc_now(),
            "recovery_pending": record.get("recovery_pending") is True,
            "completed_implementation_substages": completed,
        }
    )
    atomic_write_json(STATE_DIR / "restoration/active-v1-019-boundary.json", boundary)
    return True


def schedule_implementation_ceiling_recovery(
    record: dict[str, Any], *, actionable: str, phase: str | None = None
) -> bool:
    """Schedule one changed-fingerprint retry, or terminally exhaust its exact budget."""
    resolve_pending_routing_recovery(record, outcome="attempted")
    substage = current_bounded_substage(record)
    substage_id = phase or str((substage or {}).get("id") or "undivided")
    lifecycle_stage = phase or "implementation"
    recoveries = record.setdefault("ceiling_recovery_attempts", {})
    recovery_count = int(recoveries.get(substage_id, 0)) + 1
    recoveries[substage_id] = recovery_count
    if recovery_count > MAX_CEILING_RECOVERIES_PER_SUBSTAGE:
        record.update(
            {
                "stage": lifecycle_stage,
                "recovery_pending": False,
                "bounded_recovery_exhausted": True,
                "last_failure_category": "model_session_or_token_ceiling",
            }
        )
        persist_terminal_marker(
            STATE_DIR / "terminal",
            status="repair_exhausted",
            fingerprint=actionable,
            evidence={
                "candidate": record["candidate"],
                "phase": substage_id,
                "attempts": recovery_count,
                "root_failure_category": "model_session_or_token_ceiling",
                "next_action": "Owner action is required because the bounded ceiling-recovery budget is exhausted.",
            },
        )
        return True
    record.update(
        {
            "stop_reason": "model_session_or_token_ceiling",
            "recovery_pending": True,
            "recovery_generation": int(record.get("recovery_generation") or 0) + 1,
            "last_failure_category": None,
            "stage": lifecycle_stage,
            "pending_recovery_marker_fingerprint": actionable,
            "pending_recovery_marker_status": "routing_recovery_pending",
        }
    )
    next_action = (
        "Dispatch the scheduled fresh bounded independent-review retry."
        if phase == "independent_review"
        else f"Dispatch the scheduled fresh bounded implementation retry for the same {record['candidate']} substage."
    )
    persist_terminal_marker(
        STATE_DIR / "terminal",
        status="routing_recovery_pending",
        fingerprint=actionable,
        evidence={
            "candidate": record["candidate"],
            "phase": substage_id,
            "attempt": recovery_count,
            "root_failure_category": "model_session_or_token_ceiling",
            "next_action": next_action,
        },
    )
    return False


def schedule_context_materialization(
    record: dict[str, Any], *, actionable: str
) -> bool:
    """Schedule a changed-route context checkpoint without using ceiling attempts."""
    resolve_pending_routing_recovery(record, outcome="attempted")
    substage = current_bounded_substage(record)
    substage_id = str((substage or {}).get("id") or "undivided")
    attempts = record.setdefault("context_materialization_attempts", {})
    attempt = int(attempts.get(substage_id, 0)) + 1
    attempts[substage_id] = attempt
    if attempt > MAX_CONTEXT_MATERIALIZATIONS_PER_SUBSTAGE:
        record.update(
            {
                "stage": "implementation",
                "recovery_pending": False,
                "bounded_recovery_exhausted": True,
                "last_failure_category": "context_materialization_required",
            }
        )
        persist_terminal_marker(
            STATE_DIR / "terminal",
            status="repair_exhausted",
            fingerprint=actionable,
            evidence={
                "candidate": record["candidate"],
                "phase": substage_id,
                "attempts": attempt,
                "root_failure_category": "context_materialization_required",
                "next_action": "Owner action is required because the bounded context-materialization budget is exhausted.",
            },
        )
        return True
    record.update(
        {
            "stop_reason": "context_materialization_required",
            "recovery_pending": True,
            "recovery_generation": int(record.get("recovery_generation") or 0) + 1,
            "last_failure_category": None,
            "stage": "implementation",
            "pending_recovery_marker_fingerprint": actionable,
            "pending_recovery_marker_status": "context_materialization_pending",
        }
    )
    persist_terminal_marker(
        STATE_DIR / "terminal",
        status="context_materialization_pending",
        fingerprint=actionable,
        evidence={
            "candidate": record["candidate"],
            "phase": substage_id,
            "attempt": attempt,
            "root_failure_category": "context_materialization_required",
            "ceiling_recovery_attempt_consumed": False,
            "next_action": "Dispatch one fresh session from the deterministic materialized packet.",
        },
    )
    return False


def resolve_pending_routing_recovery(record: dict[str, Any], *, outcome: str) -> None:
    """Resolve one recovery marker through an idempotent two-phase transition."""
    fingerprint = record.get("pending_recovery_marker_fingerprint")
    if isinstance(fingerprint, str) and fingerprint:
        marker_status = str(
            record.get("pending_recovery_marker_status") or "routing_recovery_pending"
        )
        source = STATE_DIR / "terminal" / marker_status / f"{fingerprint}.json"
        target = STATE_DIR / "terminal" / f"recovery_{outcome}" / source.name
        journal = STATE_DIR / "recovery-transitions" / f"{fingerprint}.json"
        atomic_write_json(
            journal,
            {
                "schema_version": 1,
                "fingerprint": fingerprint,
                "source_status": marker_status,
                "outcome": outcome,
                "source": str(source),
                "target": str(target),
                "stage": "marker_transition_pending",
                "updated_at": utc_now(),
            },
        )
        if not source.exists() and not target.exists():
            raise AutomationError(
                "repository_integrity_uncertainty",
                "the persisted pending recovery marker is missing",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            source.replace(target)
        try:
            marker = json.loads(target.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "the resolved recovery marker is unreadable",
            ) from error
        if (
            not isinstance(marker, dict)
            or marker.get("actionable_fingerprint") != fingerprint
            or marker.get("status") not in {marker_status, f"recovery_{outcome}"}
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "the resolved recovery marker identity drifted",
            )
        marker.update(
            {
                "status": f"recovery_{outcome}",
                "resolved_at": utc_now(),
            }
        )
        atomic_write_json(target, marker)
        atomic_write_json(
            journal,
            {
                "schema_version": 1,
                "fingerprint": fingerprint,
                "source_status": marker_status,
                "outcome": outcome,
                "source": str(source),
                "target": str(target),
                "stage": "candidate_update_pending",
                "updated_at": utc_now(),
            },
        )
        record.pop("pending_recovery_marker_fingerprint", None)
        record.pop("pending_recovery_marker_status", None)
    else:
        return
    failure_path = STATE_DIR / "last-failure.json"
    if failure_path.exists():
        try:
            failure = json.loads(failure_path.read_text())
        except json.JSONDecodeError:
            failure = None
        if (
            isinstance(failure, dict)
            and failure.get("category")
            in {
                "model_session_or_token_ceiling",
                "context_materialization_required",
            }
            and failure.get("owner_action_required") is not True
        ):
            archive = STATE_DIR / "resolved-failures" / f"{digest(failure)[:20]}.json"
            archive.parent.mkdir(parents=True, exist_ok=True)
            failure_path.replace(archive)
            failure["status"] = f"recovery_{outcome}"
            failure["resolved_at"] = utc_now()
            atomic_write_json(archive, failure)


def packet_actionable_fingerprint(
    record: dict[str, Any], packet: dict[str, Any]
) -> str:
    lifecycle_stage = (
        "implementation"
        if packet["stage"] == "direct_codex_recovery"
        else packet["stage"]
    )
    return digest(
        {
            "repository": packet["repository_fingerprint"],
            "compact_state": packet["compact_state_fingerprint"],
            "process_state": packet["process_state_fingerprint"],
            "actionable": packet["preflight_fingerprint"],
            "candidate": record["candidate"],
            "stage": lifecycle_stage,
            "routing_identity": packet.get("routing_identity") or {},
        }
    )


def model_call_state(record: dict[str, Any]) -> dict[str, Any]:
    """Return only state whose change makes an otherwise identical call eligible."""
    keys = (
        "stop_reason",
        "continuation_used",
        "requested_stage",
        "repository_fingerprint",
        "compact_state_fingerprint",
        "repair_failure",
        "failed_check",
        "last_failure_category",
        "recovery_generation",
        "recovery_pending",
        "completed_implementation_substages",
    )
    return {key: record.get(key) for key in keys}


def terminal_marker(root: Path, fingerprint: str) -> Path | None:
    for status in (
        "completed",
        "blocked",
        "repair_exhausted",
        "successful_publication",
        "oversized_or_ceiling_stopped",
    ):
        path = root / status / f"{fingerprint}.json"
        if path.exists():
            return path
    return None


def authorized_candidate_writes(
    record: dict[str, Any], packet: dict[str, Any], stage: str
) -> list[str]:
    """Return the dispatcher-enforced write scope for one fresh model stage."""
    if stage == "independent_review":
        return []
    exact_existing = sorted(
        set(
            record.get("scoped_changed_paths")
            or record.get("expected_worktree_paths")
            or []
        )
    )
    if stage == "direct_codex_recovery" and exact_existing:
        return exact_existing
    materialized = packet.get("materialized_implementation_context") or {}
    exact_materialized = materialized.get("exact_writable_paths") or []
    if packet.get("bounded_substage", {}).get("id") == "sign_in":
        if (
            not isinstance(exact_materialized, list)
            or not exact_materialized
            or not all(isinstance(path, str) and path for path in exact_materialized)
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "the bounded sign-in packet omitted its exact writable-path allowlist",
            )
        return sorted(set(exact_materialized))
    profile = str(packet.get("acceptance_profile") or "")
    paths = {
        "backend/src/property_rental",
        "backend/tests",
        "ops/NOW.md",
        "ops/STATE.json",
        "ops/traceability.json",
    }
    if profile in {"api_ui", "release"}:
        paths.add("frontend/src")
    if profile in {"database", "financial", "release"}:
        paths.add("backend/migrations/versions")
    return sorted(paths)


def bind_authorized_partial_work(
    record: dict[str, Any],
    writable_paths: list[str],
    *,
    exact_paths: bool,
    previous_paths: list[str] | None = None,
) -> None:
    """Preserve an interrupted model stage only when every path remains authorized.

    A model may make useful bounded edits before the guard requests a fresh
    context-materialized or ceiling-recovery session.  Bind that exact worktree
    to the durable candidate record so the next preflight can resume it instead
    of misclassifying it as external drift.
    """
    previous = sorted(
        set(
            previous_paths
            if previous_paths is not None
            else record.get(
                "expected_worktree_paths", record.get("scoped_changed_paths") or []
            )
        )
    )
    current = changed_paths(REPO)
    allowed = [path.rstrip("/") for path in writable_paths]

    def authorized(path: str) -> bool:
        if exact_paths:
            return path in allowed
        return any(path == item or path.startswith(item + "/") for item in allowed)

    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    if any(not authorized(path) for path in added + removed):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "interrupted model stage changed work outside its exact dispatcher-authorized scope",
        )
    current_fingerprint = repository_fingerprint(REPO)
    if current != previous or current_fingerprint != record.get(
        "repository_fingerprint"
    ):
        record.update(
            {
                "expected_worktree_paths": current,
                "repository_fingerprint": current_fingerprint,
                "preserved_partial_work": {
                    "paths": current,
                    "repository_fingerprint": current_fingerprint,
                    "recovery_generation": int(record.get("recovery_generation") or 0),
                    "authorization": "dispatcher_exact_writable_scope",
                },
            }
        )


def zero_usage_provider_failure(
    *, returncode: int, stderr: str, usage: dict[str, Any]
) -> dict[str, Any] | None:
    """Classify a provider rejection that completed no model request.

    A transport callback may be entered (``api_calls_started == 1``) before
    the provider validates its request.  Only completed calls plus usage/model
    metadata count as a model attempt.  Preserve the exact supported diagnostic
    instead of asking model-validation code to interpret missing metadata.
    """
    completed_calls = usage.get("api_calls")
    if returncode == 0 or (isinstance(completed_calls, int) and completed_calls > 0):
        return None
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    if any(usage.get(field) not in (None, 0) for field in token_fields):
        return None
    if usage.get("stop_reason") == "token_estimation_unavailable":
        return {
            "category": "unsupported_invocation_configuration",
            "diagnostic": (
                "Reliable provider-request token estimation is unavailable; "
                "the provider was not called and the configured ceiling was not reached."
            ),
            "token_estimation_status": "unavailable",
            "configured_ceiling_reached": False,
        }
    status_match = re.search(r"Error code:\s*(\d{3})", stderr)
    parameter_match = re.search(
        r"Unsupported parameter:\s*([A-Za-z][A-Za-z0-9_.-]*)", stderr
    )
    if status_match and parameter_match:
        status = int(status_match.group(1))
        provider_error = f"Unsupported parameter: {parameter_match.group(1)}"
        return {
            "category": "unsupported_invocation_configuration",
            "diagnostic": f"HTTP {status}: {provider_error}",
            "provider_http_status": status,
            "provider_error": provider_error,
        }
    if usage.get("model") is not None or completed_calls is None and returncode != 64:
        return None
    safe_guard_lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    diagnostic = (
        safe_model_text(safe_guard_lines[-1], field="pre-model diagnostic", maximum=500)
        if safe_guard_lines
        else f"Hermes stopped before model execution (exit {returncode})"
    )
    return {
        "category": (
            "unsupported_invocation_configuration"
            if returncode == 64
            else "pre_model_infrastructure_failure"
        ),
        "diagnostic": diagnostic,
    }


def invoke_model(
    record: dict[str, Any], packet: dict[str, Any], policy: ModelPolicy
) -> tuple[int, str, dict[str, Any]]:
    invocation_worktree_paths = changed_paths(REPO)
    fingerprint = repository_fingerprint(REPO)
    stage = policy.stage
    actionable = packet_actionable_fingerprint(record, packet)
    attempt_path = STATE_DIR / "attempts" / f"{record['candidate']}.json"
    if attempt_path.exists():
        attempt_record = json.loads(attempt_path.read_text())
        existing_attempts = attempt_record.get("counters", {})
        if (
            attempt_record.get("fingerprint") == actionable
            and int(existing_attempts.get(stage, 0)) >= 2
        ):
            root_category = str(
                record.get("last_failure_category") or "empty_or_invalid_task_delivery"
            )
            if root_category not in FAILURE_CATEGORIES:
                root_category = "repository_integrity_uncertainty"
            persist_terminal_marker(
                STATE_DIR / "terminal",
                status="repair_exhausted",
                fingerprint=actionable,
                evidence={
                    "candidate": record["candidate"],
                    "stage": stage,
                    "attempts": 2,
                    "root_failure_category": root_category,
                    "next_action": "Owner action is required after the bounded repair budget is exhausted.",
                },
            )
            raise AutomationError(
                root_category,
                f"bounded {stage} attempt budget exhausted after {root_category}",
            )
    task_path = (
        STATE_DIR
        / "tasks"
        / f"{record['candidate']}-{stage}-{digest(packet)[:16]}.json"
    )
    task_path.parent.mkdir(parents=True, exist_ok=True)
    writable_paths = authorized_candidate_writes(record, packet, stage)
    readable_paths = sorted(set(packet.get("directly_relevant_paths") or []))
    packet["dispatcher_authorized_writable_paths"] = writable_paths
    atomic_write_text(task_path, packet_prompt(packet) + "\n")
    record["repository_fingerprint"] = fingerprint
    record["model_stage_policy"] = {
        "stage": stage,
        "provider": policy.provider,
        "model": policy.model,
        "requested_reasoning_effort": policy.requested_reasoning,
        "applicable_token_ceiling": policy.token_ceiling,
        "complex_review_classification_reason": policy.complex_review_reason,
        "repository_fingerprint": fingerprint,
        "review_scope": sorted(record.get("scoped_changed_paths") or []),
        "invocation_route": policy.route,
    }
    save_stage(record)
    call_fingerprints = {
        "repository": fingerprint,
        "compact_state": digest((REPO / "ops/STATE.json").read_bytes()),
        "process_state": digest(relevant_processes(REPO)),
        "stage_state": digest(model_call_state(record)),
        "actionable": actionable,
    }
    call_identity = "hermes-property-rental"
    call_key = repeated_call_key(
        identity=call_identity,
        arguments=[stage, str(task_path)],
        fingerprints=call_fingerprints,
        prior_result_category=str(record.get("last_failure_category") or "none"),
    )
    call_path = STATE_DIR / "calls" / f"{call_key}.json"
    preserved = repeated_call_result(call_path, call_key)
    if preserved:
        raise AutomationError(
            "repeated_identical_tool_call", json.dumps(preserved, sort_keys=True)
        )
    reserve_attempt(attempt_path, stage=stage, fingerprint=actionable)
    if policy.token_ceiling == 120000 and not (
        policy.complex_review_reason
        and record.get("model_stage_policy", {}).get(
            "complex_review_classification_reason"
        )
        == policy.complex_review_reason
        and record.get("model_stage_policy", {}).get("repository_fingerprint")
        == fingerprint
        and record.get("model_stage_policy", {}).get("review_scope")
        == sorted(record.get("scoped_changed_paths") or [])
    ):
        release_attempt(attempt_path, stage=stage)
        raise AutomationError(
            "unsupported_invocation_configuration",
            "exceptional review classification was not persisted before invocation",
        )
    manifest_path, manifest, invocation_authorization = create_manifest(
        state_root=STATE_DIR,
        repository=REPO,
        dispatcher_pid=os.getpid(),
        candidate=str(record["candidate"]),
        stage=stage,
        repository_fingerprint=fingerprint,
        preserved_worktree_fingerprint=packet.get("preserved_worktree_fingerprint"),
        task_path=task_path,
        provider=policy.provider,
        model=policy.model,
        requested_reasoning=policy.requested_reasoning,
        cumulative_ceiling=policy.token_ceiling,
        dispatcher_record_path=stage_file(str(record["candidate"])),
        writable_paths=writable_paths,
        readable_paths=readable_paths,
        bounded_substage_id=(
            str((packet.get("bounded_substage") or {}).get("id"))
            if packet.get("bounded_substage")
            else None
        ),
        exceptional_review_classification=(
            policy.complex_review_reason if policy.token_ceiling == 120_000 else None
        ),
    )
    usage_path = Path(str(manifest["usage_path"]))
    environment = os.environ.copy()
    environment.update(
        {
            "PROPERTY_RENTAL_REPO": str(REPO),
            "PROPERTY_RENTAL_HERMES_STAGE": stage,
            "PROPERTY_RENTAL_HERMES_USAGE_FILE": str(usage_path),
            "PROPERTY_RENTAL_HERMES_TOKEN_CEILING": str(policy.token_ceiling),
            "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path),
            "PROPERTY_RENTAL_INVOCATION_AUTHORIZATION": invocation_authorization,
        }
    )
    if policy.token_ceiling == 120000:
        environment.update(
            {
                "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_REASON": str(
                    policy.complex_review_reason or ""
                ),
                "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_REPOSITORY_FINGERPRINT": fingerprint,
                "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_SCOPE": json.dumps(
                    sorted(record.get("scoped_changed_paths") or []),
                    separators=(",", ":"),
                ),
            }
        )
    try:
        result = subprocess.run(
            [
                str(REPO / "scripts/hermes-property-rental"),
                str(task_path),
                str(manifest_path),
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
    except OSError as error:
        release_attempt(attempt_path, stage=stage)
        raise AutomationError(
            "pre_model_infrastructure_failure", "model executable could not start"
        ) from error

    usage: dict[str, Any] = {}
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text())
        except json.JSONDecodeError:
            usage = {}
    else:
        usage = hermes_chat_usage(
            result.stderr,
            Path(
                os.environ.get(
                    "PROPERTY_RENTAL_HERMES_STATE_DB",
                    str(Path.home() / ".hermes/state.db"),
                )
            ),
        )
        if usage:
            atomic_write_json(usage_path, usage)
    api_calls = usage.get("api_calls")
    api_calls_started = usage.get("api_calls_started")
    observed_api_calls = max(
        [
            value
            for value in (api_calls_started, api_calls)
            if isinstance(value, int) and value >= 0
        ],
        default=-1,
    )
    zero_usage_failure = zero_usage_provider_failure(
        returncode=result.returncode, stderr=result.stderr, usage=usage
    )
    if zero_usage_failure is not None:
        release_attempt(attempt_path, stage=stage)
        report = normalize_usage(usage, policy)
        report["repository_fingerprint"] = fingerprint
        report.update(
            {
                key: value
                for key, value in zero_usage_failure.items()
                if key not in {"category", "diagnostic"}
            }
        )
        diagnostic = str(zero_usage_failure["diagnostic"])
        category = str(zero_usage_failure["category"])
        finalize_usage(
            record,
            report,
            stage_result=category,
            exact_next_action=(
                "Correct the supported invocation boundary; no model attempt was consumed."
            ),
        )
        if "provider_http_status" in zero_usage_failure:
            atomic_write_json(
                call_path,
                {
                    "call_key": call_key,
                    "result": "failed",
                    "normalized_call": f"{call_identity} {stage}",
                    "underlying_result": diagnostic,
                    "exact_next_eligible_action": (
                        "publish a corrected routing revision before one bounded retry"
                    ),
                },
            )
        save_stage(record)
        raise AutomationError(category, diagnostic)

    report = normalize_usage(usage, policy)
    report["repository_fingerprint"] = fingerprint
    try:
        validate_usage(usage, policy)
    except AutomationError as error:
        if error.category in {
            "model_session_or_token_ceiling",
            "context_materialization_required",
        } and stage in {"implementation", "direct_codex_recovery"}:
            try:
                bind_authorized_partial_work(
                    record,
                    writable_paths,
                    exact_paths=(
                        (packet.get("bounded_substage") or {}).get("id") == "sign_in"
                    ),
                    previous_paths=invocation_worktree_paths,
                )
            except AutomationError as scope_error:
                error = scope_error
        pre_model_routing_fault = bool(
            error.category
            in {
                "unsupported_invocation_configuration",
                "pre_model_infrastructure_failure",
            }
            and observed_api_calls == 0
        )
        if pre_model_routing_fault:
            release_attempt(attempt_path, stage=stage)
        else:
            consume_attempt(attempt_path, stage=stage)
        finalize_usage(
            record,
            report,
            stage_result=error.category,
            exact_next_action="Apply the category-specific recovery without treating this stage as passed.",
        )
        atomic_write_json(
            call_path,
            {
                "call_key": call_key,
                "result": "failed",
                "normalized_call": f"{call_identity} {stage}",
                "underlying_result": str(error),
                "exact_next_eligible_action": "start one fresh eligible continuation or stop with the exact blocker",
            },
        )
        if error.category == "model_session_or_token_ceiling":
            handoff_output = result.stdout.strip()
            handoff = verified_continuation_handoff(handoff_output, record, stage)
            if handoff:
                record.update(handoff)
                record.update(
                    {
                        "stop_reason": error.category,
                        "continuation_used": bool(record.get("continuation_used")),
                        "stage": handoff["requested_stage"],
                    }
                )
                save_stage(record)
            elif stage in {"implementation", "direct_codex_recovery"}:
                schedule_implementation_ceiling_recovery(record, actionable=actionable)
            elif stage == "independent_review":
                schedule_implementation_ceiling_recovery(
                    record, actionable=actionable, phase="independent_review"
                )
        elif error.category == "context_materialization_required" and stage in {
            "implementation",
            "direct_codex_recovery",
        }:
            schedule_context_materialization(record, actionable=actionable)
        save_stage(record)
        raise
    consume_attempt(attempt_path, stage=stage)
    if result.returncode:
        api_call_evidence = usage.get("api_calls", "unavailable from provider")
        finalize_usage(
            record,
            report,
            stage_result="gateway_or_network_failure",
            exact_next_action="Use a focused diagnostic before the bounded retry path.",
        )
        atomic_write_json(
            call_path,
            {
                "call_key": call_key,
                "result": "failed",
                "normalized_call": f"{call_identity} {stage}",
                "underlying_result": f"Hermes exited {result.returncode} after {api_call_evidence} API call(s)",
                "exact_next_eligible_action": "use a different focused diagnostic or consume the bounded repair budget",
            },
        )
        record["last_failure_category"] = "gateway_or_network_failure"
        save_stage(record)
    model_output = result.stdout.strip()
    return result.returncode, model_output, report


def parse_model_json(output: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "model stage did not return its JSON contract",
        ) from error
    if not isinstance(value, dict):
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "model stage returned a non-object contract",
        )
    return value


def preserved_final_assistant_output(usage_report: dict[str, Any]) -> str | None:
    """Recover one completed Hermes answer when command output transport lost it."""
    session_id = usage_report.get("session_id")
    api_calls = usage_report.get("api_calls_completed")
    if (
        not isinstance(session_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
        or not isinstance(api_calls, int)
        or api_calls < 1
    ):
        return None
    if not STATE_DIR.is_absolute() or STATE_DIR.is_symlink():
        return None

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC

    directory_fd: int | None = None
    try:
        directory_fd = os.open(STATE_DIR, directory_flags)
        for component in ("hermes-sessions", session_id):
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd

        def stable_regular_snapshot(name: str, *, required: bool) -> bytes | None:
            assert directory_fd is not None
            try:
                descriptor = os.open(name, file_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if required:
                    raise
                return None
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size < 0
                    or before.st_size > 64 * 1024 * 1024
                ):
                    raise OSError("unsafe Hermes session database evidence")
                chunks: list[bytes] = []
                remaining = before.st_size
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        raise OSError("short Hermes session database read")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                after = os.fstat(descriptor)
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                identity = lambda value: (
                    value.st_dev,
                    value.st_ino,
                    value.st_mode,
                    value.st_nlink,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                )
                if identity(before) != identity(after) or identity(after) != identity(
                    current
                ):
                    raise OSError("Hermes session database changed during recovery")
                return b"".join(chunks)
            finally:
                os.close(descriptor)

        database_bytes = stable_regular_snapshot("state.db", required=True)
        wal_bytes = stable_regular_snapshot("state.db-wal", required=False)
        try:
            os.stat("state.db-journal", dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            return None
    except OSError:
        return None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)

    if not database_bytes:
        return None
    try:
        with tempfile.TemporaryDirectory(
            prefix="property-rental-review-recovery-"
        ) as directory:
            snapshot_database = Path(directory) / "state.db"
            snapshot_database.write_bytes(database_bytes)
            snapshot_database.chmod(0o600)
            if wal_bytes is not None:
                snapshot_wal = Path(directory) / "state.db-wal"
                snapshot_wal.write_bytes(wal_bytes)
                snapshot_wal.chmod(0o600)
            connection = sqlite3.connect(
                f"{snapshot_database.as_uri()}?mode=ro", uri=True
            )
            try:
                row = connection.execute(
                    """SELECT role, content, finish_reason
                       FROM messages
                       WHERE active = 1
                       ORDER BY id DESC
                       LIMIT 1"""
                ).fetchone()
            finally:
                connection.close()
    except (OSError, sqlite3.Error):
        return None
    if (
        row is None
        or row[0] != "assistant"
        or not isinstance(row[1], str)
        or not row[1].strip()
        or row[2] != "stop"
    ):
        return None
    return row[1].strip()


def safe_model_text(value: Any, *, field: str, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            f"model field {field} is missing or oversized",
        )
    encoded = value.encode("utf-8", "surrogatepass")
    if b"\0" in encoded or SECRET_PATTERN.search(encoded):
        raise AutomationError(
            "secret_credential_or_protected_operation",
            f"model field {field} contains prohibited secret-like evidence",
        )
    return value.strip()


def sanitized_implementation_result(
    value: dict[str, Any], actual: list[str], *, expected_substage: str | None = None
) -> dict[str, Any]:
    required = {
        "stage_result",
        "changed_paths",
        "verification",
        "blockers",
        "exact_next_action",
    }
    if expected_substage is not None:
        required.add("substage_complete")
    if set(value) != required:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "implementation result schema is not exact",
        )
    stage_result = value.get("stage_result")
    if stage_result == "implemented" and expected_substage is not None:
        # Schema-five packets historically instructed a bounded Hermes substage to
        # return "implemented" even though the receiver accepted "completed".
        # Normalize only that bounded compatibility case; new packets require the
        # canonical value explicitly.
        stage_result = "completed"
    if stage_result not in {"passed", "complete", "completed"}:
        raise AutomationError(
            "empty_or_invalid_task_delivery", "implementation did not report completion"
        )
    if expected_substage is not None and value.get("substage_complete") is not True:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            f"bounded implementation substage {expected_substage} did not report completion",
        )
    paths = value.get("changed_paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise AutomationError(
            "empty_or_invalid_task_delivery", "changed_paths is invalid"
        )
    if sorted(set(paths)) != actual:
        raise AutomationError(
            "empty_or_invalid_task_delivery", "declared paths do not match the worktree"
        )
    verification = value.get("verification")
    if (
        expected_substage is not None
        and verification == "deferred_to_deterministic_supervisor"
    ):
        # Match the exact legacy bounded-packet instruction without weakening the
        # ordinary implementation contract.
        verification = [verification]
    if not isinstance(verification, list) or not verification:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "implementation verification evidence is missing",
        )
    safe_verification = [
        safe_model_text(item, field="verification", maximum=500)
        for item in verification
    ]
    blockers = value.get("blockers")
    if blockers != []:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "implementation reported a blocker and cannot advance",
        )
    result = {
        "stage_result": str(stage_result),
        "changed_paths": actual,
        "verification": safe_verification,
        "blockers": [],
        "exact_next_action": safe_model_text(
            value.get("exact_next_action"), field="exact_next_action"
        ),
    }
    if expected_substage is not None:
        result["substage_complete"] = True
    return result


def sanitized_review_verdict(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "passed",
        "findings",
        "reviewed_repository_fingerprint",
        "reviewed_paths",
        "exact_next_action",
    }
    if set(value) != required:
        raise AutomationError(
            "empty_or_invalid_task_delivery", "review verdict schema is not exact"
        )
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise AutomationError(
            "empty_or_invalid_task_delivery", "review findings are invalid"
        )
    safe_findings: list[dict[str, str]] = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {
            "severity",
            "path",
            "line",
            "evidence",
        }:
            raise AutomationError(
                "empty_or_invalid_task_delivery", "review finding schema is not exact"
            )
        safe_findings.append(
            {
                "severity": safe_model_text(
                    finding.get("severity"), field="severity", maximum=20
                ),
                "path": safe_model_text(finding.get("path"), field="path", maximum=500),
                "line": safe_model_text(
                    str(finding.get("line")), field="line", maximum=40
                ),
                "evidence": safe_model_text(finding.get("evidence"), field="evidence"),
            }
        )
    paths = value.get("reviewed_paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise AutomationError(
            "empty_or_invalid_task_delivery", "reviewed_paths is invalid"
        )
    safe_paths = [
        safe_model_text(path, field="reviewed_paths", maximum=500) for path in paths
    ]
    return {
        "passed": value.get("passed") is True,
        "findings": safe_findings,
        "reviewed_repository_fingerprint": safe_model_text(
            value.get("reviewed_repository_fingerprint"),
            field="reviewed_repository_fingerprint",
            maximum=64,
        ),
        "reviewed_paths": sorted(set(safe_paths)),
        "exact_next_action": safe_model_text(
            value.get("exact_next_action"), field="exact_next_action"
        ),
    }


def full_candidate_paths(record: dict[str, Any]) -> list[str]:
    base = str(record.get("candidate_base_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return changed_paths(REPO)
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", base, "HEAD", "--"],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    committed = [os.fsdecode(item) for item in result.split(b"\0") if item]
    return sorted(set(committed + changed_paths(REPO)))


def recover_preserved_substage_result(
    record: dict[str, Any],
    value: dict[str, Any],
    *,
    session_id: str,
    expected_repair_head: str,
    expected_preserved_fingerprint: str,
    post_result_deterministic_repairs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Advance one exact rejected bounded result without another model call.

    This is intentionally narrower than normal implementation dispatch.  It is
    available only when the latest persisted Hermes usage and failure prove that
    the current bounded substage returned a completion contract which the former
    packet/receiver mismatch rejected.
    """
    substage = current_bounded_substage(record)
    if (
        record.get("candidate") != "V1-019"
        or record.get("stage") != "implementation"
        or not substage
        or record.get("last_failure_category") != "empty_or_invalid_task_delivery"
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "preserved-result recovery is not bound to the failed V1-019 implementation substage",
        )
    usages = record.get("model_usage")
    latest_usage = usages[-1] if isinstance(usages, list) and usages else None
    if (
        not isinstance(latest_usage, dict)
        or latest_usage.get("session_id") != session_id
        or latest_usage.get("stage_name") != "implementation"
        or latest_usage.get("stage_result") != "empty_or_invalid_task_delivery"
        or latest_usage.get("api_calls_completed") in {None, 0}
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "preserved-result recovery does not match the latest failed Hermes session",
        )
    actual = changed_paths(REPO)
    expected = sorted(record.get("expected_worktree_paths") or [])
    scoped_follow_up_repairs = sorted(set(post_result_deterministic_repairs))
    if scoped_follow_up_repairs not in ([], ["ops/traceability.json"]):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the post-result deterministic repair scope is not authorized",
        )
    prior_repository_fingerprint = record.get("repository_fingerprint")
    current_head = git(REPO, "rev-parse", "HEAD")
    base = str(record.get("candidate_base_commit") or "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", base)
        or not re.fullmatch(r"[0-9a-f]{40}", expected_repair_head)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_preserved_fingerprint)
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the contract-repair publication identity is invalid",
        )
    repair_paths = sorted(
        item
        for item in git(
            REPO, "diff", "--name-only", base, expected_repair_head, "--"
        ).splitlines()
        if item
    )
    exact_repair_paths = sorted(
        [
            "ops/AUTOMATION_TRACEABILITY.json",
            "scripts/openclaw_automation.py",
            "scripts/openclaw_dispatch.py",
            "scripts/test_openclaw_automation.py",
        ]
    )
    if (
        current_head != expected_repair_head
        or repair_paths != exact_repair_paths
        or actual != expected
        or preserved_paths_fingerprint(REPO, actual) != expected_preserved_fingerprint
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the published contract repair or preserved worktree is not exact",
        )
    try:
        state = json.loads((REPO / "ops/STATE.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the preserved compact state is unreadable",
        ) from error
    approval = state.get("approval") or {}
    if (
        approval.get("implementation_started") is not True
        or approval.get("implementation_completed") is True
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the preserved non-final V1-019 substage state is not exact",
        )
    result = sanitized_implementation_result(
        value, actual, expected_substage=str(substage["id"])
    )

    failure_path = STATE_DIR / "last-failure.json"
    try:
        failure = json.loads(failure_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the rejected-result failure evidence is unavailable",
        ) from error
    actionable = failure.get("actionable_fingerprint")
    blocked = STATE_DIR / "terminal" / "blocked" / f"{actionable}.json"
    try:
        blocked_marker = json.loads(blocked.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the rejected-result terminal marker is unavailable",
        ) from error
    if (
        failure.get("category") != "empty_or_invalid_task_delivery"
        or failure.get("repository_fingerprint") != prior_repository_fingerprint
        or not isinstance(actionable, str)
        or not isinstance(blocked_marker, dict)
        or blocked_marker.get("actionable_fingerprint") != actionable
        or blocked_marker.get("status") != "blocked"
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the rejected-result terminal evidence is not exact",
        )

    resolve_pending_routing_recovery(record, outcome="succeeded")
    target = STATE_DIR / "terminal" / "recovery_succeeded" / blocked.name
    target.parent.mkdir(parents=True, exist_ok=True)
    blocked.replace(target)
    blocked_marker.update(
        {
            "status": "recovery_succeeded",
            "resolved_at": utc_now(),
            "recovered_session_id": session_id,
            "model_calls_replayed": 0,
        }
    )
    atomic_write_json(target, blocked_marker)
    archive = STATE_DIR / "resolved-failures" / f"{digest(failure)[:20]}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    failure_path.replace(archive)
    failure.update(
        {
            "status": "recovery_succeeded",
            "resolved_at": utc_now(),
            "recovered_session_id": session_id,
            "model_calls_replayed": 0,
        }
    )
    atomic_write_json(archive, failure)

    completed = list(record.get("completed_implementation_substages") or [])
    completed.append(str(substage["id"]))
    record.setdefault("events", []).append(
        {
            "stage": "implementation_contract_recovery",
            "result": "passed",
            "bounded_substage": str(substage["id"]),
            "session_id": session_id,
            "model_calls_replayed": 0,
            "rejected_contract_recovered": True,
            "post_result_deterministic_repairs": scoped_follow_up_repairs,
            "actionable_fingerprint": actionable,
            "repository_fingerprint": repository_fingerprint(REPO),
        }
    )
    record.update(
        {
            "stage": "implementation",
            "candidate_base_commit": current_head,
            "implementation_complete": False,
            "implementation_result": result,
            "completed_implementation_substages": completed,
            "scoped_changed_paths": actual,
            "expected_worktree_paths": actual,
            "repository_fingerprint": repository_fingerprint(REPO),
            "repair_failure": None,
            "failed_check": None,
            "last_failure_category": None,
            "stop_reason": None,
            "recovery_pending": False,
            "recovery_generation": 0,
            "bounded_recovery_exhausted": False,
            "product_code_modification_permitted": True,
            "publication_substage": None,
            "reviewed_paths": [],
            "reviewed_repository_fingerprint": None,
        }
    )
    save_stage(record)
    recovery_evidence = {
        "schema_version": 1,
        "candidate": "V1-019",
        "bounded_substage": str(substage["id"]),
        "session_id": session_id,
        "result": "recovered_without_model_call",
        "model_calls_replayed": 0,
        "post_result_deterministic_repairs": scoped_follow_up_repairs,
        "repository_fingerprint": record["repository_fingerprint"],
        "completed_implementation_substages": completed,
        "timestamp": utc_now(),
    }
    atomic_write_json(
        STATE_DIR / "recovered-results" / f"{session_id}.json", recovery_evidence
    )
    return recovery_evidence


def verified_continuation_handoff(
    output: str, record: dict[str, Any], stage: str
) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    requested = (
        "independent_review"
        if stage == "independent_review"
        else "deterministic_verification"
    )
    exact = {
        "stage_result": "model_session_or_token_ceiling",
        "implementation_complete": True,
        "required_check_failed": False,
        "known_failing_check": None,
        "repository_fingerprint": repository_fingerprint(REPO),
        "compact_state_fingerprint": compact_state_fingerprint(REPO),
        "workers_remaining": False,
        "protected_operation": False,
        "policy_question": False,
        "scope_change": False,
        "secret_or_credential": False,
        "product_code_modification_permitted": False,
        "blockers": [],
        "requested_stage": requested,
    }
    durable_complete = record.get("implementation_complete") is True
    if not durable_complete:
        try:
            state = json.loads((REPO / "ops/STATE.json").read_text())
            durable_complete = bool(
                (state.get("approval") or {}).get("implementation_completed")
            )
        except (OSError, json.JSONDecodeError):
            durable_complete = False
    if not durable_complete or any(
        value.get(key) != item for key, item in exact.items()
    ):
        return None
    if any(
        record.get(key) not in (None, "")
        for key in ("failed_check", "repair_failure", "last_failure_category")
    ):
        return None
    if relevant_processes(REPO):
        return None
    return exact


def consume_pending_continuation(record: dict[str, Any], stage: str) -> None:
    if record.get("stop_reason") != "model_session_or_token_ceiling":
        return
    if record.get("continuation_used"):
        raise AutomationError(
            "model_session_or_token_ceiling",
            "the single verification-only continuation was already consumed",
        )
    if record.get("requested_stage") != stage:
        raise AutomationError(
            "model_session_or_token_ceiling",
            "the persisted continuation is not authorized for this stage",
        )
    current = {
        "repository": repository_fingerprint(REPO),
        "compact_state": compact_state_fingerprint(REPO),
        "process_state": process_fingerprint(REPO),
    }
    marker = (
        STATE_DIR
        / "continuations"
        / f"{record['candidate']}-{current['repository']}.json"
    )
    consume_continuation(marker, record, current)
    record.update(
        {
            "continuation_used": True,
            "product_code_modification_permitted": False,
            "continuation_stage": stage,
        }
    )
    save_stage(record)


def reconciliation_dispatch(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    paths = changed_paths(REPO)
    if paths:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "candidate dispatch requires a clean worktree; unrelated Owner work is preserved",
        )
    fingerprint = stage_actionable_fingerprint(
        REPO,
        preflight,
        candidate=str(record["candidate"]),
        stage="reconciliation_dispatch",
    )
    record.setdefault("events", []).append(
        {
            "stage": "reconciliation_dispatch",
            "result": "passed",
            "branch": git(REPO, "branch", "--show-current"),
            "repository_commit": git(REPO, "rev-parse", "HEAD"),
            "actionable_fingerprint": fingerprint,
            "changed_paths": [],
        }
    )
    record.update(
        {
            "stage": "implementation",
            "initial_changed_paths": [],
            "candidate_base_commit": git(REPO, "rev-parse", "HEAD"),
            "expected_worktree_paths": [],
            "repository_fingerprint": repository_fingerprint(REPO),
        }
    )
    save_stage(record)


def bootstrap_completed_candidate(
    record: dict[str, Any], *, require_preserved_identity: bool = False
) -> None:
    paths = changed_paths(REPO)
    if not paths:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "compact state says implementation is complete but no unpublished candidate diff exists",
        )
    preserved = preservation_evidence(REPO)
    if require_preserved_identity:
        preserved_paths = sorted(preserved.get("paths") or [])
        if preserved.get("valid") is not True or sorted(paths) != preserved_paths:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "capability continuation differs from the exact preserved candidate paths",
            )
        base = git(REPO, "rev-parse", "HEAD")
        scoped_paths = preserved_paths
    else:
        state = json.loads((REPO / "ops/STATE.json").read_text())
        base = state.get("commit")
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
            base = git(REPO, "rev-parse", "HEAD")
        scoped_paths = full_candidate_paths({"candidate_base_commit": base})
    record.update(
        {
            "stage": "deterministic_verification",
            "implementation_complete": True,
            "candidate_base_commit": base,
            "scoped_changed_paths": scoped_paths,
            "expected_worktree_paths": sorted(paths),
            "repository_fingerprint": repository_fingerprint(REPO),
            "product_code_modification_permitted": False,
            "capability_continuation_identity": {
                "candidate": record["candidate"],
                "branch": git(REPO, "branch", "--show-current"),
                "head": git(REPO, "rev-parse", "HEAD"),
                "repository_fingerprint": repository_fingerprint(REPO),
                "preserved_worktree_fingerprint": preserved.get("fingerprint"),
                "owner_action": "none",
                "failed_check": None,
            },
        }
    )
    save_stage(record)


def state_contract_repair(record: dict[str, Any]) -> None:
    if changed_paths(REPO):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "compact-state repair requires a clean worktree",
        )
    state_path = REPO / "ops/STATE.json"
    state = json.loads(state_path.read_text())
    approval = state.get("approval") or {}
    if approval.get("status") not in {
        "approved_ready",
        "approved_active",
        "approved_complete",
    }:
        raise AutomationError(
            "owner_policy_decision", "compact-state approval is not repair-authorized"
        )
    if approval.get("implementation_completed") is True:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "completed compact state has no unpublished candidate content to bind",
        )
    candidate = state.get("next_candidate") or {}
    task = candidate.get("task")
    if not isinstance(task, str) or not task:
        raise AutomationError(
            "repository_integrity_uncertainty", "state repair has no exact candidate"
        )
    state.update(
        {
            "status": "active",
            "next_action": f"Implement the approved bounded candidate: {task}",
            "idle_reason": None,
            "owner_action": "none",
            "timestamp": utc_now(),
        }
    )
    atomic_write_json(state_path, state)
    try:
        run("git", "add", "--", "ops/STATE.json")
        cached_publication_guard()
    except subprocess.CalledProcessError as error:
        raise AutomationError(
            "state_reconciliation_failure", "compact-state repair staging failed"
        ) from error
    record.update(
        {
            "stage": "reconciliation_dispatch",
            "state_repair_substage": "staged",
            "state_repair_base_commit": git(REPO, "rev-parse", "HEAD"),
            "state_repair_tree": git(REPO, "write-tree"),
        }
    )
    save_stage(record)


def publish_state_contract_repair(record: dict[str, Any]) -> None:
    base = str(record.get("state_repair_base_commit") or "")
    head = git(REPO, "rev-parse", "HEAD")
    if head == base:
        try:
            run(
                "git",
                "commit",
                "-m",
                "ops: repair compact automation state",
                capture=False,
            )
        except subprocess.CalledProcessError as error:
            raise AutomationError(
                "state_reconciliation_failure", "compact-state repair commit failed"
            ) from error
        head = git(REPO, "rev-parse", "HEAD")
    if git(REPO, "rev-parse", f"{head}^") != base or git(
        REPO, "rev-parse", f"{head}^{{tree}}"
    ) != record.get("state_repair_tree"):
        raise AutomationError(
            "repository_integrity_uncertainty", "state-repair commit boundary changed"
        )
    try:
        run("git", "push", capture=False)
    except subprocess.CalledProcessError as error:
        raise AutomationError(
            "publication_failure", "compact-state repair push failed"
        ) from error
    ci = run(str(REPO / "scripts/openclaw-wait-for-ci.sh"), head, check=False)
    if ci.returncode:
        raise AutomationError(
            "remote_ci_failure", f"state-repair CI exited {ci.returncode}"
        )
    synchronized_repository_shas()
    record.update(
        {
            "stage": "reconciliation_dispatch",
            "state_repair_substage": "complete",
            "state_contract_repair_commit": head,
            "repository_fingerprint": repository_fingerprint(REPO),
        }
    )
    save_stage(record)


def implementation(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    is_recovery = bool(record.get("repair_failure"))
    model_stage = "direct_codex_recovery" if is_recovery else "implementation"
    substage = current_bounded_substage(record)
    boundary = active_restoration_boundary(record)
    if boundary is not None and (
        substage is None or substage.get("id") != boundary.get("bounded_substage")
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "post-exit restoration permits only the exact V1-019 sign_in recovery",
        )
    candidate = str(record.get("candidate") or "")
    candidate_substages = CANDIDATE_SUBSTAGES.get(candidate)
    if candidate_substages is not None and substage is None:
        record["stage"] = "deterministic_verification"
        record["implementation_complete"] = True
        save_stage(record)
        return
    packet = task_packet(
        REPO,
        preflight,
        model_stage,
        bounded_substage=substage,
        recovery_generation=int(record.get("recovery_generation") or 0),
        recovery_state={
            "recovery_pending": record.get("recovery_pending") is True,
            "bounded_recovery_attempt": int(
                (record.get("ceiling_recovery_attempts") or {}).get(
                    str((substage or {}).get("id") or "")
                )
                or 0
            ),
            "current_failure_category": record.get("last_failure_category")
            or record.get("stop_reason"),
            "bounded_recovery_exhausted": record.get("bounded_recovery_exhausted")
            is True,
            "context_materialization_attempt": int(
                (record.get("context_materialization_attempts") or {}).get(
                    str((substage or {}).get("id") or "")
                )
                or 0
            ),
        },
    )
    packet["routing_identity"] = record_routing_identity(record, "implementation")
    if is_recovery:
        packet["repair"] = {
            "authorized": True,
            "failure_category": record.get("last_failure_category"),
            "exact_defect": record.get("repair_failure"),
            "failed_check": record.get("failed_check"),
            "review_findings": record.get("review_verdict"),
            "scope": "only the proven defect inside the original approved candidate",
            "required_after_repair": [
                "rerun affected focused checks",
                "rerun the complete deterministic acceptance profile",
                "obtain a fresh independent review",
            ],
        }
    before = changed_paths(REPO)
    expected_before = sorted(
        record.get("expected_worktree_paths", record.get("scoped_changed_paths") or [])
    )
    persisted_fingerprint = record.get("repository_fingerprint")
    if before != expected_before or (
        persisted_fingerprint is not None
        and persisted_fingerprint != repository_fingerprint(REPO)
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "worktree content or paths differ from the candidate's persisted scope before implementation",
        )
    exit_status, output, usage_report = invoke_model(
        record, packet, model_policy(model_stage)
    )
    if exit_status:
        raise AutomationError(
            "gateway_or_network_failure", f"Hermes implementation exited {exit_status}"
        )
    try:
        raw_result = parse_model_json(output)
        state = json.loads((REPO / "ops/STATE.json").read_text())
        approval = state.get("approval") or {}
        completed = bool(approval.get("implementation_completed"))
        started = bool(approval.get("implementation_started"))
        final_substage = bool(
            substage and substage.get("order") == substage.get("total")
        )
        if substage and not started:
            raise AutomationError(
                "empty_or_invalid_task_delivery",
                f"implementation did not durably record that {candidate} started",
            )
        if (substage is None or final_substage) and not completed:
            raise AutomationError(
                "empty_or_invalid_task_delivery",
                "implementation did not durably record completion",
            )
        if substage and not final_substage and completed:
            raise AutomationError(
                "empty_or_invalid_task_delivery",
                f"a non-final {candidate} substage prematurely marked the candidate complete",
            )
        after = changed_paths(REPO)
        result = sanitized_implementation_result(
            raw_result,
            after,
            expected_substage=str(substage["id"]) if substage else None,
        )
    except AutomationError as error:
        finalize_usage(
            record,
            usage_report,
            stage_result=error.category,
            exact_next_action="Correct the invalid implementation result contract before continuing.",
        )
        record["last_failure_category"] = error.category
        save_stage(record)
        raise
    completed_substages = list(record.get("completed_implementation_substages") or [])
    if substage:
        completed_substages.append(str(substage["id"]))
    all_substages_complete = bool(
        candidate_substages is None
        or len(completed_substages) == len(candidate_substages)
    )
    next_action = (
        "Run deterministic verification in a separate stage."
        if all_substages_complete
        else f"Dispatch the next fresh bounded {candidate} implementation substage."
    )
    resolve_pending_routing_recovery(record, outcome="succeeded")
    finalize_usage(
        record,
        usage_report,
        stage_result="passed",
        exact_next_action=next_action,
    )
    record.update(
        {
            "stage": (
                "deterministic_verification"
                if all_substages_complete
                else "implementation"
            ),
            "implementation_complete": all_substages_complete,
            "implementation_result": result,
            "completed_implementation_substages": completed_substages,
            "scoped_changed_paths": full_candidate_paths(record),
            "expected_worktree_paths": after,
            "repository_fingerprint": repository_fingerprint(REPO),
            "repair_failure": None,
            "failed_check": None,
            "last_failure_category": None,
            "stop_reason": None,
            "recovery_pending": False,
            "recovery_generation": 0,
            "product_code_modification_permitted": True,
            "publication_substage": None,
            "reviewed_paths": [],
            "reviewed_repository_fingerprint": None,
        }
    )
    save_stage(record)


def deterministic_verification(record: dict[str, Any]) -> None:
    consume_pending_continuation(record, "deterministic_verification")
    current_paths = full_candidate_paths(record)
    if current_paths != sorted(record.get("scoped_changed_paths") or []):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "candidate scope changed before deterministic verification",
        )
    evidence_path = STATE_DIR / "verification" / f"{record['candidate']}.json"
    environment = os.environ.copy()
    for variable in (
        "HERMES_ENABLE_PROJECT_PLUGINS",
        "HERMES_HOME",
        "HERMES_MAX_TOKENS",
        "PROPERTY_RENTAL_DISPATCH_STATE_DIR",
        "PROPERTY_RENTAL_HERMES_STAGE",
        "PROPERTY_RENTAL_HERMES_TOKEN_CEILING",
        "PROPERTY_RENTAL_HERMES_USAGE_FILE",
        "PROPERTY_RENTAL_INVOCATION_MANIFEST",
        "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES",
        "PROPERTY_RENTAL_REPO",
        "PROPERTY_RENTAL_TEST_PROCESS_ROWS",
    ):
        environment.pop(variable, None)
    environment["PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE"] = str(evidence_path)
    environment["PROPERTY_RENTAL_VERIFICATION_PROFILE"] = "complete"
    fixture_call_fingerprints = {
        "repository": repository_fingerprint(REPO),
        "compact_state": compact_state_fingerprint(REPO),
        "process_state": process_fingerprint(REPO),
    }
    fixture_call_key = repeated_call_key(
        identity="scripts/openclaw-deterministic-verification.sh",
        arguments=["complete"],
        fingerprints=fixture_call_fingerprints,
        prior_result_category="test_fixture_failure",
    )
    fixture_call_path = STATE_DIR / "calls" / f"{fixture_call_key}.json"
    if record.get("last_failure_category") == "test_fixture_failure":
        preserved = repeated_call_result(fixture_call_path, fixture_call_key)
        if preserved:
            raise AutomationError(
                "repeated_identical_tool_call", json.dumps(preserved, sort_keys=True)
            )
    result = subprocess.run(
        [str(REPO / "scripts/openclaw-deterministic-verification.sh")],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    evidence = {
        "command": "scripts/openclaw-deterministic-verification.sh",
        "exit_status": result.returncode,
        "artifact": str(evidence_path),
    }
    if not evidence_path.exists():
        atomic_write_json(evidence_path, evidence)
    record.setdefault("events", []).append(
        {"stage": "deterministic_verification", **evidence}
    )
    if result.returncode:
        category = "deterministic_test_failure"
        failed_gate = "complete repository acceptance profile"
        try:
            artifact = json.loads(evidence_path.read_text())
            if artifact.get("failure_category") == "test_fixture_failure":
                category = "test_fixture_failure"
            if isinstance(artifact.get("failed_gate"), str) and artifact["failed_gate"]:
                failed_gate = artifact["failed_gate"]
        except (OSError, json.JSONDecodeError):
            pass
        if category == "test_fixture_failure":
            atomic_write_json(
                fixture_call_path,
                {
                    "call_key": fixture_call_key,
                    "result": "failed",
                    "normalized_call": "scripts/openclaw-deterministic-verification.sh complete",
                    "underlying_result": (
                        f"exit {result.returncode}; failed gate {failed_gate}; "
                        f"artifact {evidence_path}"
                    ),
                    "exact_next_eligible_action": (
                        "repair the fixture or change the repository, compact-state, or process fingerprint before retrying"
                    ),
                },
            )
        record.update(
            {
                "last_failure_category": category,
                "failed_check": failed_gate,
                "repair_failure": f"deterministic verification exited {result.returncode}; inspect concise artifact {evidence_path}",
                "stage": "implementation"
                if category == "deterministic_test_failure"
                else "deterministic_verification",
                "product_code_modification_permitted": category
                == "deterministic_test_failure",
            }
        )
        save_stage(record)
        raise AutomationError(
            category,
            f"deterministic verification exited {result.returncode}",
        )
    verified_fingerprint = repository_fingerprint(REPO)
    record.update(
        {
            "stage": "independent_review",
            "deterministic_verification_passed": True,
            "repository_fingerprint": verified_fingerprint,
            "verified_repository_fingerprint": verified_fingerprint,
            "verified_paths": current_paths,
        }
    )
    save_stage(record)


def independent_review(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    consume_pending_continuation(record, "independent_review")
    current_fingerprint = repository_fingerprint(REPO)
    current_paths = full_candidate_paths(record)
    if (
        record.get("verified_repository_fingerprint") != current_fingerprint
        or sorted(record.get("verified_paths") or []) != current_paths
    ):
        record.update(
            {
                "stage": "deterministic_verification",
                "deterministic_verification_passed": False,
                "repository_fingerprint": current_fingerprint,
            }
        )
        save_stage(record)
        raise AutomationError(
            "repository_integrity_uncertainty",
            "repository drifted after deterministic verification; complete gates must rerun",
        )
    packet = task_packet(REPO, preflight, "independent_review")
    expected_paths = sorted(record.get("scoped_changed_paths") or [])
    base_commit = str(record.get("candidate_base_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "independent review omitted the exact candidate base commit",
        )
    untracked_result = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *expected_paths,
        ],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    if any(item for item in untracked_result.split(b"\0") if item):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "independent review refuses untracked candidate files because their contents are absent from the exact Git diff",
        )
    if expected_paths:
        patch_result = subprocess.run(
            [
                "git",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--binary",
                base_commit,
                "--",
                *expected_paths,
            ],
            cwd=REPO,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
    else:
        patch_result = b""
    if len(patch_result) > MAX_REVIEW_PATCH_BYTES:
        raise AutomationError(
            "context_materialization_required",
            "the exact candidate review patch exceeds the bounded materialization limit",
        )
    verification_event = next(
        (
            event
            for event in reversed(record.get("events") or [])
            if isinstance(event, dict)
            and event.get("stage") == "deterministic_verification"
        ),
        {},
    )
    packet["scoped_changed_paths"] = expected_paths
    packet["directly_relevant_paths"] = []
    packet["materialized_candidate_diff"] = {
        "base_commit": base_commit,
        "format": "git_diff_binary",
        "byte_count": len(patch_result),
        "content": patch_result.decode("utf-8", errors="replace"),
        "untracked_files_prohibited": True,
    }
    packet["verification_evidence"] = {
        "deterministic_verification_passed": record.get(
            "deterministic_verification_passed"
        )
        is True,
        "command": verification_event.get("command"),
        "exit_status": verification_event.get("exit_status"),
        "artifact": verification_event.get("artifact"),
        "checks_passed": verification_event.get("checks_passed"),
    }
    packet.setdefault("continuity_instructions", []).append(
        "Review only materialized_candidate_diff and the compact verification evidence. "
        "Do not call any tool or reread any repository file; return the review JSON directly."
    )
    policy = model_policy(
        "independent_review",
        complex_review=True,
        classification_reason="security-sensitive complete candidate diff and publication evidence",
    )
    before = repository_fingerprint(REPO)
    exit_status, output, usage_report = invoke_model(record, packet, policy)
    after = repository_fingerprint(REPO)
    if before != after:
        finalize_usage(
            record,
            usage_report,
            stage_result="independent_review_defect",
            exact_next_action="Preserve the modified worktree and stop; a reviewer must never edit it.",
        )
        save_stage(record)
        raise AutomationError(
            "independent_review_defect", "reviewer modified the repository"
        )
    if exit_status:
        raise AutomationError(
            "gateway_or_network_failure", f"independent reviewer exited {exit_status}"
        )
    verdict: dict[str, Any] | None = None
    delivery_error: AutomationError | None = None
    try:
        verdict = sanitized_review_verdict(parse_model_json(output))
    except AutomationError as error:
        delivery_error = error
    if (
        verdict is None
        and delivery_error is not None
        and delivery_error.category == "empty_or_invalid_task_delivery"
    ):
        preserved_output = preserved_final_assistant_output(usage_report)
        if preserved_output is not None:
            try:
                verdict = sanitized_review_verdict(parse_model_json(preserved_output))
            except AutomationError as error:
                delivery_error = error
            else:
                usage_report["output_transport_recovered"] = True
                usage_report["output_transport_recovery_source"] = (
                    "exact_completed_hermes_session"
                )
                record["review_transport_recovery"] = {
                    "session_id": usage_report["session_id"],
                    "source": "exact_completed_hermes_session",
                    "validated_through_exact_review_contract": True,
                }
    if verdict is None:
        error = delivery_error or AutomationError(
            "empty_or_invalid_task_delivery",
            "model stage did not return its JSON contract",
        )
        finalize_usage(
            record,
            usage_report,
            stage_result=error.category,
            exact_next_action="Obtain a new fresh review with a valid exact output contract; do not authorize product repair.",
        )
        record.update(
            {
                "last_failure_category": error.category,
                "review_verdict": {},
                "repair_failure": None,
                "stage": "independent_review",
            }
        )
        save_stage(record)
        raise error
    findings = verdict["findings"]
    if (
        verdict["reviewed_repository_fingerprint"] != after
        or verdict["reviewed_paths"] != expected_paths
    ):
        binding_error = AutomationError(
            "empty_or_invalid_task_delivery",
            "independent review did not bind the exact fingerprint and path allowlist",
        )
        finalize_usage(
            record,
            usage_report,
            stage_result=binding_error.category,
            exact_next_action="Obtain a fresh exact review for the unchanged verified candidate.",
        )
        record.update(
            {
                "last_failure_category": binding_error.category,
                "review_verdict": verdict,
                "repair_failure": None,
                "stage": "independent_review",
            }
        )
        save_stage(record)
        raise binding_error
    if verdict["passed"] is not True:
        if not findings:
            missing_findings_error = AutomationError(
                "empty_or_invalid_task_delivery",
                "failed review omitted concrete findings",
            )
            finalize_usage(
                record,
                usage_report,
                stage_result=missing_findings_error.category,
                exact_next_action="Obtain a fresh review with concrete findings or PASS.",
            )
            record.update(
                {
                    "last_failure_category": missing_findings_error.category,
                    "review_verdict": verdict,
                    "repair_failure": None,
                    "stage": "independent_review",
                }
            )
            save_stage(record)
            raise missing_findings_error
        finalize_usage(
            record,
            usage_report,
            stage_result="independent_review_defect",
            exact_next_action="Repair only the concrete in-scope findings, rerun all gates, and obtain a fresh review.",
        )
        record.update(
            {
                "last_failure_category": "independent_review_defect",
                "review_verdict": verdict,
                "repair_failure": "fresh independent review returned concrete in-scope findings",
                "stage": "implementation",
            }
        )
        save_stage(record)
        raise AutomationError(
            "independent_review_defect", "independent reviewer returned FAIL"
        )
    if findings:
        inconsistent_verdict_error = AutomationError(
            "empty_or_invalid_task_delivery",
            "passing review cannot contain findings",
        )
        finalize_usage(
            record,
            usage_report,
            stage_result=inconsistent_verdict_error.category,
            exact_next_action="Obtain a fresh internally consistent review verdict.",
        )
        record.update(
            {
                "last_failure_category": inconsistent_verdict_error.category,
                "review_verdict": verdict,
                "repair_failure": None,
                "stage": "independent_review",
            }
        )
        save_stage(record)
        raise inconsistent_verdict_error
    resolve_pending_routing_recovery(record, outcome="succeeded")
    finalize_usage(
        record,
        usage_report,
        stage_result="passed",
        exact_next_action="Publish only this exact reviewed fingerprint and path allowlist.",
    )
    record.update(
        {
            "stage": "publication",
            "review_verdict": verdict,
            "repository_fingerprint": after,
            "reviewed_repository_fingerprint": after,
            "reviewed_paths": expected_paths,
            "publication_paths": changed_paths(REPO),
            "publication_substage": None,
            "stop_reason": None,
            "recovery_pending": False,
            "recovery_generation": 0,
            "bounded_recovery_exhausted": False,
        }
    )
    save_stage(record)


def synchronized_repository_shas() -> dict[str, str]:
    branch = authorized_branch()
    local = git(REPO, "rev-parse", "HEAD")
    try:
        upstream = git(REPO, "rev-parse", "@{upstream}")
        remote_output = run(
            "git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"
        ).stdout.split()
    except subprocess.CalledProcessError as error:
        raise AutomationError(
            "publication_failure", "could not resolve upstream and remote branch SHAs"
        ) from error
    remote = remote_output[0] if remote_output else ""
    if not remote or len({local, upstream, remote}) != 1:
        raise AutomationError(
            "publication_failure",
            "local HEAD, configured upstream, and remote branch HEAD are not equal",
        )
    return {"local": local, "upstream": upstream, "remote": remote, "branch": branch}


def cached_publication_guard() -> None:
    environment = os.environ.copy()
    environment["PROPERTY_RENTAL_GUARD_MODE"] = "cached"
    guard = subprocess.run(
        [str(REPO / "scripts/openclaw-publication-guard.sh")],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    if guard.returncode:
        raise AutomationError(
            "publication_failure",
            f"cached publication guard failed with exit {guard.returncode}",
        )


def publication(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    reviewed = sorted(record.get("reviewed_paths") or [])
    expected = sorted(record.get("publication_paths") or [])
    scoped = sorted(record.get("scoped_changed_paths") or [])
    substage = record.get("publication_substage")
    if substage is None:
        actual = changed_paths(REPO)
        reviewed_fingerprint = record.get("reviewed_repository_fingerprint")
        if not actual and not expected:
            base_commit = str(record.get("candidate_base_commit") or "")
            current_head = git(REPO, "rev-parse", "HEAD")
            if (
                not reviewed
                or reviewed != scoped
                or full_candidate_paths(record) != scoped
                or reviewed_fingerprint != repository_fingerprint(REPO)
                or not re.fullmatch(r"[0-9a-f]{40}", base_commit)
                or base_commit == current_head
            ):
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "clean cumulative publication differs from the exact independent-review evidence",
                )
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base_commit, current_head],
                cwd=REPO,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ancestor.returncode:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "clean cumulative publication base is not an ancestor of HEAD",
                )
            if relevant_processes(REPO):
                raise AutomationError(
                    "lock_or_overlapping_process_failure",
                    "publication refused while a relevant worker or verification process remains",
                )
            synchronized = synchronized_repository_shas()
            guard = subprocess.run(
                [str(REPO / "scripts/openclaw-publication-guard.sh")],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            if guard.returncode:
                raise AutomationError(
                    "publication_failure",
                    "clean cumulative publication guard failed",
                )
            if (
                changed_paths(REPO)
                or git(REPO, "rev-parse", "HEAD") != current_head
                or repository_fingerprint(REPO) != reviewed_fingerprint
                or full_candidate_paths(record) != scoped
            ):
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "clean cumulative publication drifted during validation",
                )
            record.update(
                {
                    "publication_mode": "reviewed_cumulative_already_published",
                    "publication_paths": scoped,
                    "publication_substage": "pushed_waiting_ci",
                    "publication_commit": current_head,
                    "publication_shas": synchronized,
                }
            )
            save_stage(record)
            expected = scoped
            substage = "pushed_waiting_ci"
        if (
            substage is None
            and (
                not reviewed
                or reviewed != scoped
                or not expected
                or actual != expected
                or reviewed_fingerprint != repository_fingerprint(REPO)
            )
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "publication content or paths differ from the exact independent-review evidence",
            )
    if substage is None:
        overlaps = relevant_processes(REPO)
        if overlaps:
            raise AutomationError(
                "lock_or_overlapping_process_failure",
                "publication refused while a relevant worker or verification process remains",
            )
        try:
            for relative in expected:
                run("git", "add", "--", relative)
            run("git", "diff", "--cached", "--check")
        except subprocess.CalledProcessError as error:
            raise AutomationError(
                "publication_failure", "candidate staging or cached diff check failed"
            ) from error
        cached = run("git", "diff", "--cached", "--name-only").stdout.splitlines()
        if sorted(cached) != expected:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "cached paths differ from reviewed paths",
            )
        cached_publication_guard()
        record.update(
            {
                "publication_substage": "staged_reviewed",
                "reviewed_base_commit": git(REPO, "rev-parse", "HEAD"),
                "reviewed_tree": git(REPO, "write-tree"),
            }
        )
        save_stage(record)
        substage = "staged_reviewed"

    candidate = str(record["candidate"])
    if substage == "staged_reviewed":
        base = str(record.get("reviewed_base_commit") or "")
        reviewed_tree = str(record.get("reviewed_tree") or "")
        head = git(REPO, "rev-parse", "HEAD")
        if head == base:
            cached = run("git", "diff", "--cached", "--name-only").stdout.splitlines()
            if sorted(cached) != expected or git(REPO, "write-tree") != reviewed_tree:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "resumed staged index differs from the reviewed tree or allowlist",
                )
            try:
                run(
                    "git",
                    "commit",
                    "-m",
                    f"feat: complete {candidate} approved tranche",
                    capture=False,
                )
            except subprocess.CalledProcessError as error:
                raise AutomationError(
                    "publication_failure", "reviewed candidate commit failed"
                ) from error
            head = git(REPO, "rev-parse", "HEAD")
        try:
            parent = git(REPO, "rev-parse", f"{head}^")
            committed_tree = git(REPO, "rev-parse", f"{head}^{{tree}}")
            committed_paths = git(
                REPO, "diff-tree", "--no-commit-id", "--name-only", "-r", head
            ).splitlines()
        except subprocess.CalledProcessError as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "cannot prove the resumed publication commit boundary",
            ) from error
        if (
            parent != base
            or committed_tree != reviewed_tree
            or sorted(committed_paths) != expected
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "publication commit does not exactly match the reviewed tree and paths",
            )
        record.update(
            {
                "publication_substage": "committed_unpushed",
                "publication_commit": head,
            }
        )
        save_stage(record)
        substage = "committed_unpushed"

    published = str(record.get("publication_commit") or "")
    if substage == "committed_unpushed":
        if git(REPO, "rev-parse", "HEAD") != published:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "local HEAD moved after the reviewed publication commit",
            )
        try:
            run("git", "push", capture=False)
        except subprocess.CalledProcessError as error:
            raise AutomationError(
                "publication_failure", "normal publication push failed"
            ) from error
        record["publication_substage"] = "pushed_waiting_ci"
        save_stage(record)
        substage = "pushed_waiting_ci"

    if substage != "pushed_waiting_ci" or not published:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"unknown publication substage {substage!r}",
        )
    ci_arguments = [str(REPO / "scripts/openclaw-wait-for-ci.sh"), published]
    ci_evidence_path: Path | None = None
    if record.get("publication_mode") == "reviewed_cumulative_already_published":
        ci_evidence_path = STATE_DIR / "ci" / f"{candidate}-{published}.json"
        ci_arguments.extend(["--evidence", str(ci_evidence_path)])
    ci = run(*ci_arguments, check=False)
    if ci.returncode:
        record.update(
            {
                "stage": "implementation",
                "publication_commit": published,
                "last_failure_category": "remote_ci_failure",
                "repair_failure": f"remote CI exited {ci.returncode} for published candidate commit {published}",
                "scoped_changed_paths": full_candidate_paths(record),
                "expected_worktree_paths": [],
                "reviewed_paths": [],
                "reviewed_repository_fingerprint": None,
                "verified_repository_fingerprint": None,
                "verified_paths": [],
                "publication_paths": [],
                "publication_substage": "remote_ci_failed_repair_required",
                "repository_fingerprint": repository_fingerprint(REPO),
            }
        )
        save_stage(record)
        raise AutomationError(
            "remote_ci_failure", f"CI exited {ci.returncode} for {published}"
        )
    if ci_evidence_path is not None:
        try:
            ci_evidence = json.loads(ci_evidence_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "clean cumulative publication has no readable exact-CI evidence",
            ) from error
        if (
            not isinstance(ci_evidence, dict)
            or ci_evidence.get("status") != "success"
            or ci_evidence.get("commit") != published
            or ci_evidence.get("head_sha") != published
            or not isinstance(ci_evidence.get("run_id"), int)
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "clean cumulative publication CI evidence is not bound to the exact successful HEAD",
            )
        record.update(
            {
                "publication_ci_evidence": str(ci_evidence_path),
                "publication_ci_run_id": ci_evidence["run_id"],
                "publication_ci_url": ci_evidence.get("url"),
            }
        )
    synchronized = synchronized_repository_shas()
    if record.get("publication_mode") == "reviewed_cumulative_already_published" and (
        changed_paths(REPO)
        or synchronized["local"] != published
        or repository_fingerprint(REPO)
        != record.get("reviewed_repository_fingerprint")
        or full_candidate_paths(record) != sorted(record.get("reviewed_paths") or [])
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "clean cumulative publication drifted before final CI binding",
        )
    record.update(
        {
            "stage": "post_publication_reconciliation",
            "publication_commit": published,
            "remote_ci_passed": True,
            "publication_shas": synchronized,
            "publication_substage": "ci_passed_reconciliation_pending",
        }
    )
    persist_terminal_marker(
        STATE_DIR / "terminal",
        status="successful_publication",
        fingerprint=stage_actionable_fingerprint(
            REPO,
            preflight,
            candidate=str(record["candidate"]),
            stage="post_publication_reconciliation",
        ),
        evidence={
            "candidate": record["candidate"],
            "commit": published,
            "next_action": "Reconcile compact publication state and verify final SHA equality.",
        },
    )
    save_stage(record)


def post_publication(record: dict[str, Any]) -> None:
    """Resume the metadata commit across mutation, commit, push, and CI."""
    substage = record.get("reconciliation_substage")
    if substage is None:
        synchronized_repository_shas()
        record.update(
            {
                "reconciliation_substage": "mutation_pending",
                "reconciliation_base_commit": git(REPO, "rev-parse", "HEAD"),
            }
        )
        save_stage(record)
        substage = "mutation_pending"

    base = str(record.get("reconciliation_base_commit") or "")
    head = git(REPO, "rev-parse", "HEAD")
    expected = ["ops/NOW.md", "ops/STATE.json"]
    if substage == "mutation_pending" and head == base:
        current = changed_paths(REPO)
        if not current:
            environment = os.environ.copy()
            environment["PROPERTY_RENTAL_RECONCILE_MUTATE_ONLY"] = "true"
            result = subprocess.run(
                [str(REPO / "scripts/openclaw-reconcile-published-state.sh")],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if result.returncode:
                raise AutomationError(
                    "state_reconciliation_failure",
                    f"state reconciliation mutation exited {result.returncode}",
                )
            current = changed_paths(REPO)
        if current != expected:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "resumed reconciliation mutation has unexpected paths",
            )
        try:
            for relative in expected:
                run("git", "add", "--", relative)
            run("git", "diff", "--cached", "--check")
            cached_publication_guard()
        except (subprocess.CalledProcessError, AutomationError) as error:
            raise AutomationError(
                "state_reconciliation_failure",
                "reconciliation staging or cached validation failed",
            ) from error
        record.update(
            {
                "reconciliation_substage": "staged",
                "reconciliation_tree": git(REPO, "write-tree"),
            }
        )
        save_stage(record)
        substage = "staged"

    if substage in {"mutation_pending", "staged"}:
        head = git(REPO, "rev-parse", "HEAD")
        if head == base:
            if substage != "staged":
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "reconciliation state lost its staged tree",
                )
            try:
                run(
                    "git",
                    "commit",
                    "-m",
                    "ops: reconcile published automation state",
                    capture=False,
                )
            except subprocess.CalledProcessError as error:
                raise AutomationError(
                    "state_reconciliation_failure",
                    "reconciliation metadata commit failed",
                ) from error
            head = git(REPO, "rev-parse", "HEAD")
        committed_paths = git(
            REPO, "diff-tree", "--no-commit-id", "--name-only", "-r", head
        ).splitlines()
        if (
            git(REPO, "rev-parse", f"{head}^") != base
            or sorted(committed_paths) != expected
            or (
                record.get("reconciliation_tree")
                and git(REPO, "rev-parse", f"{head}^{{tree}}")
                != record.get("reconciliation_tree")
            )
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "reconciliation commit boundary is not exact",
            )
        try:
            state = json.loads(git_document(head, "ops/STATE.json"))
            now = git_document(head, "ops/NOW.md")
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "reconciliation commit content is unreadable",
            ) from error
        branch = git(REPO, "branch", "--show-current")
        if not exact_reconciliation_contract(
            base=base, branch=branch, state=state, now=now
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "reconciliation commit content does not match the deterministic publication contract",
            )
        record.update(
            {
                "reconciliation_substage": "committed_unpushed",
                "reconciliation_commit": head,
            }
        )
        save_stage(record)
        substage = "committed_unpushed"

    commit = str(record.get("reconciliation_commit") or "")
    if substage == "committed_unpushed":
        if git(REPO, "rev-parse", "HEAD") != commit:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "local HEAD moved after reconciliation commit",
            )
        try:
            run("git", "push", capture=False)
        except subprocess.CalledProcessError as error:
            raise AutomationError(
                "publication_failure", "reconciliation metadata push failed"
            ) from error
        record["reconciliation_substage"] = "pushed_waiting_ci"
        save_stage(record)
        substage = "pushed_waiting_ci"

    if substage == "reconciliation_ci_failed":
        raise AutomationError(
            "remote_ci_failure",
            f"preserved reconciliation CI failure for {commit}; no duplicate wait invoked",
        )
    if substage != "pushed_waiting_ci" or not commit:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"unknown reconciliation substage {substage!r}",
        )
    ci = run(str(REPO / "scripts/openclaw-wait-for-ci.sh"), commit, check=False)
    if ci.returncode:
        record.update(
            {
                "reconciliation_substage": "reconciliation_ci_failed",
                "last_failure_category": "remote_ci_failure",
                "failed_check": f"remote CI for reconciliation commit {commit}",
            }
        )
        save_stage(record)
        raise AutomationError(
            "remote_ci_failure",
            f"reconciliation CI exited {ci.returncode} for {commit}",
        )
    synchronized = synchronized_repository_shas()
    record.update(
        {
            "stage": (
                "complete"
                if record.get("candidate") == "V1-019"
                else "next_candidate_activation"
            ),
            "reconciliation_substage": "complete",
            "reconciliation_commit": commit,
            "reconciliation_shas": synchronized,
            "successor_activation_held": record.get("candidate") == "V1-019",
        }
    )
    save_stage(record)


def activate_next(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    preflight = command_json(str(REPO / "scripts/openclaw-supervisor-preflight.sh"))
    overlaps = relevant_processes(REPO)
    if overlaps:
        raise AutomationError(
            "lock_or_overlapping_process_failure",
            "successor activation refused before mutation while a relevant repository worker remains",
        )
    substage = record.get("activation_substage")
    if substage is None:
        if preflight.get("state_issue") != "authorized_candidate_selection_required":
            raise AutomationError(
                "state_reconciliation_failure",
                "exact successor selection is not currently authorized",
            )
        record.update(
            {
                "activation_substage": "selection_pending",
                "activation_base_commit": git(REPO, "rev-parse", "HEAD"),
                "activation_candidate": preflight.get("queue_candidate"),
                "activation_timestamp": utc_now(),
            }
        )
        save_stage(record)
        substage = "selection_pending"
    base = str(record.get("activation_base_commit") or "")
    head = git(REPO, "rev-parse", "HEAD")
    expected_candidate = record.get("activation_candidate")
    if not isinstance(expected_candidate, dict):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "successor activation has no persisted deterministic candidate",
        )
    timestamp = record.get("activation_timestamp")
    if not valid_dynamic_timestamp(timestamp):
        current_paths = changed_paths(REPO)
        if head == base and not current_paths:
            timestamp = utc_now()
        else:
            try:
                if head == base:
                    observed_state = json.loads((REPO / "ops/STATE.json").read_text())
                else:
                    observed_state = json.loads(git_document(head, "ops/STATE.json"))
                observed_timestamp = observed_state.get("timestamp")
            except (
                OSError,
                subprocess.CalledProcessError,
                json.JSONDecodeError,
            ) as error:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "resumed successor activation has no recoverable timestamp",
                ) from error
            if not valid_dynamic_timestamp(observed_timestamp):
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "resumed successor activation timestamp is invalid",
                )
            timestamp = observed_timestamp
        record["activation_timestamp"] = timestamp
        save_stage(record)
    assert isinstance(timestamp, str)
    expected_documents = render_activation_documents(
        base=base,
        prior_candidate_id=str(record["candidate"]),
        candidate=expected_candidate,
        timestamp=timestamp,
    )
    if expected_documents is None:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "successor activation documents cannot be derived from the persisted candidate",
        )
    expected_paths = [
        relative
        for relative in ACTIVATION_PATHS
        if git_blob(f"{base}:{relative}") != expected_documents[relative]
    ]
    if substage == "selection_pending" and head == base:
        resumable_paths = validate_resumable_activation_files(
            base=base, expected=expected_documents
        )
        if resumable_paths != expected_paths:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation derived inconsistent deterministic paths",
            )
        for relative, content in expected_documents.items():
            atomic_write_text(REPO / relative, content)
        current = changed_paths(REPO)
        if current != expected_paths:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "deterministic successor mutation did not produce its exact path set",
            )
        try:
            state = json.loads((REPO / "ops/STATE.json").read_text())
            roadmap = json.loads((REPO / "ops/V1_ROADMAP.json").read_text())
            now = (REPO / "ops/NOW.md").read_text()
        except (OSError, json.JSONDecodeError) as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor mutation content is unreadable",
            ) from error
        if not exact_activation_contract(
            base=base,
            prior_candidate_id=str(record["candidate"]),
            candidate=expected_candidate,
            state=state,
            roadmap=roadmap,
            now=now,
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor mutation differs from the exact persisted structured candidate",
            )
        try:
            for relative in expected_paths:
                run("git", "add", "--", relative)
            run("git", "diff", "--cached", "--check")
            cached = run("git", "diff", "--cached", "--name-only").stdout.splitlines()
            if cached != expected_paths:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "successor activation index does not match its deterministic path set",
                )
            cached_publication_guard()
        except (subprocess.CalledProcessError, AutomationError) as error:
            raise AutomationError(
                "state_reconciliation_failure",
                "successor activation staging or cached validation failed",
            ) from error
        record.update(
            {
                "activation_substage": "staged",
                "activation_tree": git(REPO, "write-tree"),
                "activation_paths": expected_paths,
            }
        )
        save_stage(record)
        substage = "staged"

    if substage in {"selection_pending", "staged"}:
        head = git(REPO, "rev-parse", "HEAD")
        if head == base:
            if substage != "staged":
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "successor activation state lost its staged tree",
                )
            resumable_paths = validate_resumable_activation_files(
                base=base, expected=expected_documents
            )
            if resumable_paths != expected_paths:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "staged successor activation no longer has its deterministic path set",
                )
            for relative, content in expected_documents.items():
                atomic_write_text(REPO / relative, content)
            for relative in expected_paths:
                run("git", "add", "--", relative)
            if (
                run("git", "diff", "--cached", "--name-only").stdout.splitlines()
                != expected_paths
                or changed_paths(REPO) != expected_paths
                or git(REPO, "write-tree") != record.get("activation_tree")
            ):
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    "staged successor activation changed before its commit boundary",
                )
            try:
                run(
                    "git",
                    "commit",
                    "-m",
                    "ops: select structured authorized successor",
                    capture=False,
                )
            except subprocess.CalledProcessError as error:
                raise AutomationError(
                    "state_reconciliation_failure",
                    "successor activation metadata commit failed",
                ) from error
            head = git(REPO, "rev-parse", "HEAD")
        committed_paths = git(
            REPO, "diff-tree", "--no-commit-id", "--name-only", "-r", head
        ).splitlines()
        persisted_paths = record.get("activation_paths")
        if persisted_paths is None:
            persisted_paths = expected_paths
            record["activation_paths"] = persisted_paths
            save_stage(record)
        if not isinstance(persisted_paths, list) or persisted_paths != expected_paths:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation path evidence differs from the deterministic contract",
            )
        if (
            git(REPO, "rev-parse", f"{head}^") != base
            or sorted(committed_paths) != sorted(persisted_paths)
            or (
                record.get("activation_tree")
                and git(REPO, "rev-parse", f"{head}^{{tree}}")
                != record.get("activation_tree")
            )
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor selection commit boundary is not exact",
            )
        try:
            state = json.loads(git_document(head, "ops/STATE.json"))
            roadmap = json.loads(git_document(head, "ops/V1_ROADMAP.json"))
            now = git_document(head, "ops/NOW.md")
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation commit content is unreadable",
            ) from error
        if not exact_activation_contract(
            base=base,
            prior_candidate_id=str(record["candidate"]),
            candidate=expected_candidate,
            state=state,
            roadmap=roadmap,
            now=now,
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation commit differs from the exact persisted structured candidate",
            )
        record.update(
            {
                "activation_substage": "selection_committed",
                "activation_commit": head,
                "activation_ci_passed": False,
            }
        )
        save_stage(record)
        substage = "selection_committed"

    head = str(record.get("activation_commit") or "")
    if substage == "activation_ci_failed":
        raise AutomationError(
            "remote_ci_failure",
            f"preserved successor activation CI failure for {head}; no duplicate wait invoked",
        )
    if substage == "selection_committed":
        upstream = git(REPO, "rev-parse", "@{upstream}")
        if upstream != head:
            try:
                run("git", "push", capture=False)
            except subprocess.CalledProcessError as error:
                raise AutomationError(
                    "publication_failure", "successor selection push failed"
                ) from error
        record.update(
            {"activation_substage": "pushed_waiting_ci", "activation_commit": head}
        )
        save_stage(record)
        substage = "pushed_waiting_ci"
    if substage != "pushed_waiting_ci" or not head:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"unknown successor activation substage {substage!r}",
        )
    ci = (
        subprocess.CompletedProcess([], 0, "", "")
        if record.get("activation_ci_passed") is True
        else run(str(REPO / "scripts/openclaw-wait-for-ci.sh"), head, check=False)
    )
    if ci.returncode:
        record.update(
            {
                "activation_substage": "activation_ci_failed",
                "last_failure_category": "remote_ci_failure",
                "failed_check": f"remote CI for successor activation commit {head}",
            }
        )
        save_stage(record)
        raise AutomationError(
            "remote_ci_failure", f"successor selection CI exited {ci.returncode}"
        )
    synchronized = synchronized_repository_shas()
    record.update(
        {
            "stage": "complete",
            "activation_substage": "complete",
            "activation_ci_passed": True,
            "activation_shas": synchronized,
            "completed_at": utc_now(),
        }
    )
    save_stage(record)
    persist_terminal_marker(
        STATE_DIR / "terminal",
        status="completed",
        fingerprint=stage_actionable_fingerprint(
            REPO,
            preflight,
            candidate=str(record["candidate"]),
            stage="next_candidate_activation",
        ),
        evidence={
            "candidate": record["candidate"],
            "next_action": "Activation is complete; implementation remains a separate later scheduled cycle.",
        },
    )


def dispatch() -> int:
    with CycleLock(STATE_DIR / "cycle.lock"):
        authorized_branch()
        overlaps = relevant_processes(REPO)
        if overlaps:
            raise AutomationError(
                "lock_or_overlapping_process_failure",
                f"{len(overlaps)} relevant process identity/identities remain active",
            )
        for _ in range(MAX_CYCLES):
            preflight = command_json(
                str(REPO / "scripts/openclaw-supervisor-preflight.sh")
            )
            record: dict[str, Any] | None = pending_lifecycle_record()
            if record is not None:
                pending_stage = record.get("stage")
                if pending_stage == "post_publication_reconciliation":
                    post_publication(record)
                    continue
                if pending_stage == "next_candidate_activation":
                    activate_next(record, preflight)
                    return 0
            if preflight.get("actionable") is not True:
                return 0
            issue = preflight.get("state_issue")
            candidate: str | None = None
            if issue != "authorized_candidate_selection_required":
                candidate = candidate_id()
                if record is None and stage_file(candidate).exists():
                    record = load_stage(candidate)
            if issue == "published_compact_state_reconciliation_required" and not (
                record
                and record.get("stage") == "implementation"
                and record.get("last_failure_category") == "remote_ci_failure"
            ):
                candidate = candidate or candidate_id()
                record = record or load_stage(candidate)
                record["stage"] = "post_publication_reconciliation"
                save_stage(record)
                post_publication(record)
                continue
            if issue == "authorized_candidate_selection_required":
                if record is None:
                    candidate = candidate_id()
                    record = load_stage(candidate)
                    record["stage"] = "next_candidate_activation"
                    save_stage(record)
                activate_next(record, preflight)
                return 0
            candidate = (
                str(record["candidate"])
                if record is not None
                else (candidate or candidate_id())
            )
            record = record or load_stage(candidate)
            if issue in {
                "completed_tranche_publication_action_enforced",
                "completed_status_alias_publication_enforced",
                "capability_verification_continuation",
            } and record.get("stage") in {"reconciliation_dispatch", "implementation"}:
                bootstrap_completed_candidate(
                    record,
                    require_preserved_identity=(
                        issue == "capability_verification_continuation"
                    ),
                )
            elif issue == "state_contract_repair_authorized":
                state_contract_repair(record)
                publish_state_contract_repair(record)
                continue
            if record.get("state_repair_substage") == "staged":
                publish_state_contract_repair(record)
                continue
            stage = record.get("stage")
            actionable = stage_actionable_fingerprint(
                REPO,
                preflight,
                candidate=candidate,
                stage=str(stage),
                routing_identity=record_routing_identity(record, str(stage)),
            )
            existing_terminal = terminal_marker(STATE_DIR / "terminal", actionable)
            continuation_pending = bool(
                existing_terminal
                and existing_terminal.parent.name == "oversized_or_ceiling_stopped"
                and record.get("stop_reason") == "model_session_or_token_ceiling"
                and not record.get("continuation_used")
            )
            if existing_terminal and not continuation_pending:
                return 0
            if os.environ.get("PROPERTY_RENTAL_DISPATCH_DRY_RUN") == "true":
                if stage == "reconciliation_dispatch" and changed_paths(REPO):
                    raise AutomationError(
                        "repository_integrity_uncertainty",
                        "readiness requires a clean worktree before candidate dispatch",
                    )
                print(
                    json.dumps(
                        {
                            "ready": True,
                            "candidate": candidate,
                            "stage": stage,
                            "actionable_fingerprint": actionable,
                            "model_calls": 0,
                            "repository_mutations": 0,
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if stage == "reconciliation_dispatch":
                reconciliation_dispatch(record, preflight)
                stage = "implementation"
            if stage == "implementation":
                implementation(record, preflight)
                if restoration_boundary_reached(record):
                    return 0
            elif stage == "deterministic_verification":
                deterministic_verification(record)
            elif stage == "independent_review":
                independent_review(record, preflight)
            elif stage == "publication":
                publication(record, preflight)
            elif stage == "post_publication_reconciliation":
                post_publication(record)
            elif stage == "next_candidate_activation":
                activate_next(record, preflight)
                return 0
            elif stage == "complete":
                return 0
            else:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    f"unknown persisted stage {stage!r}",
                )
    return 0


def main() -> int:
    try:
        return dispatch()
    except AutomationError as error:
        fingerprint = repository_fingerprint(REPO)
        next_actions = {
            "pre_model_infrastructure_failure": "Retry the same compact stage once infrastructure is available; no model attempt was consumed.",
            "gateway_or_network_failure": "Run a focused gateway diagnostic, then use the bounded retry only if the actionable fingerprint changes.",
            "unsupported_invocation_configuration": "Correct the supported invocation boundary without changing product scope; no model attempt was consumed.",
            "empty_or_invalid_task_delivery": "Retry the exact unchanged stage through one fresh bounded session with the explicit output schema; require Owner action only after bounded attempts exhaust.",
            "model_session_or_token_ceiling": "Run the scheduled fresh bounded recovery for the exact candidate model stage or substage; request Owner action only if its bounded recovery budget is exhausted.",
            "context_materialization_required": "Run the scheduled fresh materialized-context route for the exact candidate substage; do not consume a ceiling-recovery attempt.",
            "repeated_identical_tool_call": "Use the preserved underlying result to choose a different focused diagnostic; do not repeat the unchanged call.",
            "deterministic_test_failure": "Repair only the proven in-scope failing check, rerun the complete profile, and obtain a fresh review.",
            "independent_review_defect": "Repair only the concrete in-scope review findings, rerun all gates, and obtain a fresh review.",
            "remote_ci_failure": "Diagnose the exact remote CI failure and enter the bounded in-scope repair path.",
            "publication_failure": "Preserve the reviewed work and repair the exact publication gate before another push.",
            "state_reconciliation_failure": "Reconcile published compact state deterministically after verifying local/upstream/remote equality.",
            "lock_or_overlapping_process_failure": "Wait for the verified owner or relevant process to end, then rerun readiness for the changed process fingerprint.",
            "repository_integrity_uncertainty": "Preserve the repository unchanged and resolve the exact integrity mismatch before dispatch.",
        }
        exact_next_action = next_actions.get(
            error.category,
            "Request Owner action only if the recorded blocker crosses a protected boundary.",
        )
        actionable = fingerprint
        routing_record: dict[str, Any] = {}
        try:
            preflight = command_json(
                str(REPO / "scripts/openclaw-supervisor-preflight.sh")
            )
            candidate = candidate_id()
            existing = stage_file(candidate)
            stage = "reconciliation_dispatch"
            if existing.exists():
                routing_record = json.loads(existing.read_text())
                stage = str(routing_record.get("stage") or stage)
            actionable = stage_actionable_fingerprint(
                REPO,
                preflight,
                candidate=candidate,
                stage=stage,
                routing_identity=record_routing_identity(routing_record, stage),
            )
        except (AutomationError, OSError, json.JSONDecodeError):
            actionable = digest(
                {
                    "repository": fingerprint,
                    "compact_state": compact_state_fingerprint(REPO),
                    "process_state": process_fingerprint(REPO),
                    "failure_category": error.category,
                }
            )
        exhausted_marker = (
            STATE_DIR / "terminal" / "repair_exhausted" / f"{actionable}.json"
        )
        bounded_recovery_exhausted = bool(
            routing_record.get("bounded_recovery_exhausted") is True
        )
        if exhausted_marker.exists() or bounded_recovery_exhausted:
            exact_next_action = (
                "Owner action is required after the bounded repair budget is exhausted; "
                f"the preserved root failure category is {error.category}."
            )
        failure = {
            "timestamp": utc_now(),
            "category": error.category,
            "diagnostic": str(error),
            "repository_fingerprint": fingerprint,
            "actionable_fingerprint": actionable,
            "exact_next_action": exact_next_action,
            "owner_action_required": bool(
                exhausted_marker.exists()
                or bounded_recovery_exhausted
                or failure_owner_action_required(error.category)
            ),
        }
        atomic_write_json(STATE_DIR / "last-failure.json", failure)
        marker_status = (
            "repair_exhausted"
            if exhausted_marker.exists() or bounded_recovery_exhausted
            else {
                "deterministic_test_failure": "repair_pending",
                "test_fixture_failure": "repair_pending",
                "independent_review_defect": "repair_pending",
                "remote_ci_failure": "repair_pending",
                "pre_model_infrastructure_failure": "routing_recovery_pending",
                "lock_or_overlapping_process_failure": "routing_recovery_pending",
                "gateway_or_network_failure": "infrastructure_failure",
                "unsupported_invocation_configuration": "routing_recovery_pending",
                "empty_or_invalid_task_delivery": "routing_recovery_pending",
                "model_session_or_token_ceiling": "routing_recovery_pending",
                "context_materialization_required": "context_materialization_pending",
                "repeated_identical_tool_call": "repeated_identical_tool_call",
            }.get(error.category, "blocked")
        )
        recovery_marker_already_persisted = bool(
            error.category
            in {"model_session_or_token_ceiling", "context_materialization_required"}
            and (
                routing_record.get("recovery_pending") is True
                or bounded_recovery_exhausted
            )
        )
        if not recovery_marker_already_persisted:
            persist_terminal_marker(
                STATE_DIR / "terminal",
                status=marker_status,
                fingerprint=actionable,
                evidence={
                    "category": error.category,
                    "root_failure_category": error.category,
                    "next_action": exact_next_action,
                    "exact_next_action": failure["exact_next_action"],
                },
            )
        print(f"{error.category}: {error}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
