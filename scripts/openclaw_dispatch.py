#!/usr/bin/env python3
"""Model-light deterministic stage dispatcher for the Property Rental roadmap."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from openclaw_automation import (
    FAILURE_CATEGORIES,
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
    git,
    hermes_chat_usage,
    model_policy,
    normalize_usage,
    persist_terminal_marker,
    process_fingerprint,
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
)

REPO = Path(
    os.environ.get(
        "PROPERTY_RENTAL_REPO",
        "/Users/sokompheak/Development/property-rental-management",
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


def exact_activation_contract(
    *,
    base: str,
    prior_candidate_id: str,
    candidate: dict[str, Any],
    state: dict[str, Any],
    roadmap: dict[str, Any],
    now: str,
) -> bool:
    try:
        expected_state = json.loads(git_document(base, "ops/STATE.json"))
        expected_roadmap = json.loads(git_document(base, "ops/V1_ROADMAP.json"))
        base_now = git_document(base, "ops/NOW.md")
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    timestamp = state.get("timestamp")
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
        return False
    roadmap_state = expected_state.setdefault("roadmap", {})
    if not isinstance(roadmap_state, dict):
        return False
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
        return False
    roadmap_candidates = [
        item
        for item in tranches
        if isinstance(item, dict) and item.get("id") == candidate_id
    ]
    if len(roadmap_candidates) != 1 or roadmap_candidates[0] != candidate:
        return False
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
    return (
        state == expected_state and roadmap == expected_roadmap and now == expected_now
    )


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
        "Use the property-rental-continuity skill and only the compact paths and authorities listed below. "
        "Do not load any supervisor transcript, earlier model reasoning, unrelated diff, raw log, or broad canonical set. "
        "Return only the required JSON object.\n\n"
        + json.dumps(packet, sort_keys=True, indent=2)
    )


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


def direct_codex_jsonl_usage(stdout: str, token_ceiling: int) -> dict[str, Any]:
    """Extract only provider metadata from the direct Codex JSONL event stream."""
    thread_id: str | None = None
    stop_reason: str | None = None
    totals: dict[str, int | None] = {
        "input_tokens": None,
        "cache_read_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
    }

    def ceiling_reason(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        exact = {
            "length": "length",
            "max_tokens": "max_tokens",
            "token_ceiling": "token_ceiling",
            "session_ceiling": "session_ceiling",
            "tool_ceiling": "tool_ceiling",
            "max_turns": "max_turns",
        }
        if normalized in exact:
            return exact[normalized]
        phrases = {
            "max_tokens": ("maximum_tokens", "max_token", "token_limit"),
            "token_ceiling": ("token_ceiling", "weighted_token_limit"),
            "session_ceiling": ("session_limit", "session_ceiling"),
            "length": ("context_window", "context_length"),
            "max_turns": ("maximum_turns", "max_turns", "turn_limit"),
        }
        for reason, needles in phrases.items():
            if any(needle in normalized for needle in needles):
                return reason
        return None

    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        event_usage = event.get("usage")
        if isinstance(event_usage, dict):
            mappings = {
                "input_tokens": "input_tokens",
                "cached_input_tokens": "cache_read_tokens",
                "output_tokens": "output_tokens",
                "reasoning_output_tokens": "reasoning_tokens",
            }
            for source, target in mappings.items():
                value = event_usage.get(source)
                if isinstance(value, int) and value >= 0:
                    previous = totals[target]
                    totals[target] = value if previous is None else max(previous, value)
        for key in ("stop_reason", "finish_reason", "termination_reason"):
            stop_reason = stop_reason or ceiling_reason(event.get(key))
        if event_type in {"turn.failed", "error"}:
            failure = event.get("error")
            if isinstance(failure, dict):
                for key in ("code", "type", "reason", "message"):
                    stop_reason = stop_reason or ceiling_reason(failure.get(key))
            elif isinstance(failure, str):
                stop_reason = stop_reason or ceiling_reason(failure)
            for key in ("code", "reason", "message"):
                stop_reason = stop_reason or ceiling_reason(event.get(key))

    input_total = totals["input_tokens"]
    output_total = totals["output_tokens"]
    return {
        **totals,
        "session_id": thread_id,
        "configured_max_tokens": token_ceiling,
        "invocation_config_verified": True,
        "total_tokens": (
            input_total + output_total
            if isinstance(input_total, int) and isinstance(output_total, int)
            else None
        ),
        "api_calls": "unavailable from provider",
        **({"stop_reason": stop_reason} if stop_reason else {}),
    }


def invoke_model(
    record: dict[str, Any], packet: dict[str, Any], policy: ModelPolicy
) -> tuple[int, str, dict[str, Any]]:
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
    atomic_write_text(task_path, packet_prompt(packet) + "\n")
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
    call_identity = (
        "codex exec" if policy.route == "direct Codex" else "openclaw-hermes-task"
    )
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
    attempts = reserve_attempt(attempt_path, stage=stage, fingerprint=actionable)
    attempt_number = int(attempts.get("counters", {}).get(stage, 0)) + 1
    usage_path = (
        STATE_DIR
        / "usage"
        / f"{record['candidate']}-{stage}-{attempt_number}-{digest(call_key + utc_now())[:12]}.json"
    )
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "PROPERTY_RENTAL_REPO": str(REPO),
            "PROPERTY_RENTAL_HERMES_STAGE": stage,
            "PROPERTY_RENTAL_HERMES_USAGE_FILE": str(usage_path),
            "PROPERTY_RENTAL_HERMES_TOKEN_CEILING": str(policy.token_ceiling),
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
    output_path = usage_path.with_suffix(".result.json")
    try:
        if policy.route == "direct Codex":
            result = subprocess.run(
                [
                    os.environ.get("PROPERTY_RENTAL_CODEX_BIN", "codex"),
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--strict-config",
                    "--cd",
                    str(REPO),
                    "--sandbox",
                    "read-only" if stage == "independent_review" else "workspace-write",
                    "--model",
                    policy.model,
                    "--config",
                    f'model_reasoning_effort="{policy.requested_reasoning}"',
                    "--config",
                    f"model_context_window={policy.token_ceiling}",
                    "--output-last-message",
                    str(output_path),
                    "-",
                ],
                cwd=REPO,
                text=True,
                input=packet_prompt(packet),
                capture_output=True,
                check=False,
                env=environment,
            )
        else:
            result = subprocess.run(
                [str(REPO / "scripts/openclaw-hermes-task.sh"), str(task_path)],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
    except OSError as error:
        release_attempt(attempt_path, stage=stage)
        atomic_write_json(
            call_path,
            {
                "call_key": call_key,
                "result": "failed",
                "normalized_call": f"{call_identity} {stage}",
                "underlying_result": "model executable could not start",
                "exact_next_eligible_action": "restore the executable or infrastructure before retrying this unchanged call",
            },
        )
        raise AutomationError(
            "pre_model_infrastructure_failure", "model executable could not start"
        ) from error

    usage: dict[str, Any] = {}
    if policy.route == "direct Codex":
        usage = direct_codex_jsonl_usage(result.stdout, policy.token_ceiling)
        atomic_write_json(usage_path, usage)
    elif usage_path.exists():
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
    stopped_before_model = bool(
        result.returncode
        and (
            (isinstance(api_calls, int) and api_calls == 0)
            or (
                policy.route == "direct Codex"
                and not usage.get("session_id")
                and not usage.get("stop_reason")
            )
        )
    )
    if stopped_before_model:
        release_attempt(attempt_path, stage=stage)
        category = (
            "unsupported_invocation_configuration"
            if result.returncode == 64
            else "pre_model_infrastructure_failure"
        )
        diagnostic = f"Hermes stopped before model execution (exit {result.returncode})"
        atomic_write_json(
            call_path,
            {
                "call_key": call_key,
                "result": "failed",
                "normalized_call": f"{call_identity} {stage}",
                "underlying_result": diagnostic,
                "exact_next_eligible_action": "change the supported infrastructure or invocation configuration before retrying",
            },
        )
        raise AutomationError(category, diagnostic)

    report = normalize_usage(usage, policy)
    report["repository_fingerprint"] = fingerprint
    try:
        validate_usage(usage, policy)
    except AutomationError as error:
        if error.category == "model_session_or_token_ceiling":
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
            persist_terminal_marker(
                STATE_DIR / "terminal",
                status="oversized_or_ceiling_stopped",
                fingerprint=actionable,
                evidence={
                    "candidate": record["candidate"],
                    "stage": stage,
                    "underlying_result": str(error),
                    "next_action": "Consume the one eligible fresh verification-only continuation for this exact fingerprint.",
                },
            )
            handoff_output = (
                output_path.read_text().strip()
                if policy.route == "direct Codex" and output_path.exists()
                else result.stdout.strip()
            )
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
        if error.category in {
            "unsupported_invocation_configuration",
            "pre_model_infrastructure_failure",
        }:
            release_attempt(attempt_path, stage=stage)
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
    model_output = (
        output_path.read_text().strip()
        if policy.route == "direct Codex" and output_path.exists()
        else result.stdout.strip()
    )
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
    value: dict[str, Any], actual: list[str]
) -> dict[str, Any]:
    required = {
        "stage_result",
        "changed_paths",
        "verification",
        "blockers",
        "exact_next_action",
    }
    if set(value) != required:
        raise AutomationError(
            "empty_or_invalid_task_delivery",
            "implementation result schema is not exact",
        )
    if value.get("stage_result") not in {"passed", "complete", "completed"}:
        raise AutomationError(
            "empty_or_invalid_task_delivery", "implementation did not report completion"
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
    return {
        "stage_result": str(value["stage_result"]),
        "changed_paths": actual,
        "verification": safe_verification,
        "blockers": [],
        "exact_next_action": safe_model_text(
            value.get("exact_next_action"), field="exact_next_action"
        ),
    }


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


def bootstrap_completed_candidate(record: dict[str, Any]) -> None:
    paths = changed_paths(REPO)
    if not paths:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "compact state says implementation is complete but no unpublished candidate diff exists",
        )
    state = json.loads((REPO / "ops/STATE.json").read_text())
    base = state.get("commit")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        base = git(REPO, "rev-parse", "HEAD")
    record.update(
        {
            "stage": "deterministic_verification",
            "implementation_complete": True,
            "candidate_base_commit": base,
            "scoped_changed_paths": full_candidate_paths(
                {"candidate_base_commit": base}
            ),
            "expected_worktree_paths": paths,
            "repository_fingerprint": repository_fingerprint(REPO),
            "product_code_modification_permitted": False,
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
    packet = task_packet(REPO, preflight, model_stage)
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
        completed = bool((state.get("approval") or {}).get("implementation_completed"))
        if not completed:
            raise AutomationError(
                "empty_or_invalid_task_delivery",
                "implementation did not durably record completion",
            )
        after = changed_paths(REPO)
        result = sanitized_implementation_result(raw_result, after)
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
    finalize_usage(
        record,
        usage_report,
        stage_result="passed",
        exact_next_action="Run deterministic verification in a separate stage.",
    )
    record.update(
        {
            "stage": "deterministic_verification",
            "implementation_complete": True,
            "implementation_result": result,
            "scoped_changed_paths": full_candidate_paths(record),
            "expected_worktree_paths": after,
            "repository_fingerprint": repository_fingerprint(REPO),
            "repair_failure": None,
            "failed_check": None,
            "last_failure_category": None,
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
    packet["scoped_changed_paths"] = record.get("scoped_changed_paths", [])
    packet["verification_evidence"] = record.get("events", [])
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
    try:
        verdict = sanitized_review_verdict(parse_model_json(output))
    except AutomationError as error:
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
        raise
    expected_paths = sorted(record.get("scoped_changed_paths") or [])
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
        if (
            not reviewed
            or reviewed != scoped
            or not expected
            or actual != expected
            or reviewed_fingerprint != repository_fingerprint(REPO)
        ):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "publication content or paths differ from the exact independent-review evidence",
            )
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
    ci = run(str(REPO / "scripts/openclaw-wait-for-ci.sh"), published, check=False)
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
    synchronized = synchronized_repository_shas()
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
            "stage": "next_candidate_activation",
            "reconciliation_substage": "complete",
            "reconciliation_commit": commit,
            "reconciliation_shas": synchronized,
        }
    )
    save_stage(record)


def activate_next(record: dict[str, Any], preflight: dict[str, Any]) -> None:
    preflight = command_json(str(REPO / "scripts/openclaw-supervisor-preflight.sh"))
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
            }
        )
        save_stage(record)
        substage = "selection_pending"
    base = str(record.get("activation_base_commit") or "")
    head = git(REPO, "rev-parse", "HEAD")
    expected_paths = ["ops/NOW.md", "ops/STATE.json", "ops/V1_ROADMAP.json"]
    if substage == "selection_pending" and head == base:
        current = changed_paths(REPO)
        if not current:
            environment = os.environ.copy()
            environment["PROPERTY_RENTAL_SELECT_MUTATE_ONLY"] = "true"
            result = subprocess.run(
                [str(REPO / "scripts/openclaw-select-next-candidate.sh")],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if result.returncode:
                raise AutomationError(
                    "state_reconciliation_failure",
                    f"candidate activation mutation exited {result.returncode}",
                )
            current = changed_paths(REPO)
        if current != expected_paths:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "resumed successor mutation has unexpected paths",
            )
        expected_candidate = record.get("activation_candidate")
        if not isinstance(expected_candidate, dict):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation has no persisted deterministic candidate",
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
        if (
            git(REPO, "rev-parse", f"{head}^") != base
            or sorted(committed_paths) != expected_paths
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
        expected_candidate = record.get("activation_candidate")
        if not isinstance(expected_candidate, dict):
            raise AutomationError(
                "repository_integrity_uncertainty",
                "successor activation has no persisted deterministic candidate",
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
            "next_action": "Begin reconciliation and dispatch for the newly activated approved candidate.",
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
                    continue
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
                continue
            candidate = (
                str(record["candidate"])
                if record is not None
                else (candidate or candidate_id())
            )
            record = record or load_stage(candidate)
            if (
                issue
                in {
                    "completed_tranche_publication_action_enforced",
                    "completed_status_alias_publication_enforced",
                }
                and record.get("stage") == "reconciliation_dispatch"
            ):
                bootstrap_completed_candidate(record)
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
            "model_session_or_token_ceiling": "Use the single eligible fresh verification-only continuation for the exact preserved fingerprint, or stop if it was already consumed.",
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
        try:
            preflight = command_json(
                str(REPO / "scripts/openclaw-supervisor-preflight.sh")
            )
            candidate = candidate_id()
            existing = stage_file(candidate)
            stage = "reconciliation_dispatch"
            if existing.exists():
                stage = str(json.loads(existing.read_text()).get("stage") or stage)
            actionable = stage_actionable_fingerprint(
                REPO, preflight, candidate=candidate, stage=stage
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
        if exhausted_marker.exists():
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
        }
        atomic_write_json(STATE_DIR / "last-failure.json", failure)
        marker_status = (
            "repair_exhausted"
            if exhausted_marker.exists()
            else {
                "deterministic_test_failure": "repair_pending",
                "test_fixture_failure": "repair_pending",
                "independent_review_defect": "repair_pending",
                "remote_ci_failure": "repair_pending",
                "pre_model_infrastructure_failure": "infrastructure_failure",
                "gateway_or_network_failure": "infrastructure_failure",
                "unsupported_invocation_configuration": "unsupported_configuration",
                "model_session_or_token_ceiling": "oversized_or_ceiling_stopped",
                "repeated_identical_tool_call": "repeated_identical_tool_call",
            }.get(error.category, "blocked")
        )
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
