#!/usr/bin/env python3
"""Deterministic policy and durable evidence for Property Rental automation.

This module deliberately contains no model-driven routing.  The small shell
dispatcher calls these primitives to construct compact stage packets, enforce
the supported Hermes invocation contract, and persist resumable evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

UNAVAILABLE: Final = "unavailable from provider"
ORDINARY_TOKEN_CEILING: Final = 60_000
COMPLEX_REVIEW_TOKEN_CEILING: Final = 90_000
EXCEPTIONAL_REVIEW_TOKEN_CEILING: Final = 120_000
MODEL_ID: Final = "gpt-5.6-sol"
PROVIDER: Final = "openai-codex"

STAGES: Final = (
    "reconciliation_dispatch",
    "implementation",
    "deterministic_verification",
    "independent_review",
    "publication",
    "post_publication_reconciliation",
    "next_candidate_activation",
)

FAILURE_CATEGORIES: Final = frozenset(
    {
        "pre_model_infrastructure_failure",
        "gateway_or_network_failure",
        "unsupported_invocation_configuration",
        "empty_or_invalid_task_delivery",
        "model_session_or_token_ceiling",
        "repeated_identical_tool_call",
        "deterministic_test_failure",
        "test_fixture_failure",
        "independent_review_defect",
        "publication_failure",
        "remote_ci_failure",
        "state_reconciliation_failure",
        "lock_or_overlapping_process_failure",
        "owner_policy_decision",
        "secret_credential_or_protected_operation",
        "repository_integrity_uncertainty",
    }
)


class AutomationError(RuntimeError):
    """A safely classified automation failure."""

    def __init__(self, category: str, message: str) -> None:
        if category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown failure category: {category}")
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ModelPolicy:
    stage: str
    provider: str
    model: str
    requested_reasoning: str
    token_ceiling: int
    route: str
    complex_review_reason: str | None = None


def model_policy(
    stage: str,
    *,
    complex_review: bool = False,
    exceptional_review: bool = False,
    classification_reason: str | None = None,
) -> ModelPolicy:
    """Return the only supported model configuration for a model stage."""
    if stage in {"implementation", "direct_codex_recovery"}:
        if complex_review or exceptional_review:
            raise AutomationError(
                "unsupported_invocation_configuration",
                "implementation cannot promote itself to a review ceiling",
            )
        route = "Hermes" if stage == "implementation" else "direct Codex"
        return ModelPolicy(
            stage, PROVIDER, MODEL_ID, "high", ORDINARY_TOKEN_CEILING, route
        )
    if stage != "independent_review":
        raise AutomationError(
            "unsupported_invocation_configuration",
            f"stage {stage!r} is not a model stage",
        )
    if exceptional_review and not complex_review:
        raise AutomationError(
            "unsupported_invocation_configuration",
            "120000 tokens require advance complex-review classification",
        )
    if (complex_review or exceptional_review) and not classification_reason:
        raise AutomationError(
            "unsupported_invocation_configuration",
            "complex review requires a recorded deterministic classification reason",
        )
    ceiling = (
        EXCEPTIONAL_REVIEW_TOKEN_CEILING
        if exceptional_review
        else COMPLEX_REVIEW_TOKEN_CEILING
    )
    return ModelPolicy(
        stage,
        PROVIDER,
        MODEL_ID,
        "xhigh",
        ceiling,
        "direct Codex",
        classification_reason,
    )


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes | str | Any) -> str:
    if isinstance(value, str):
        value = value.encode()
    elif not isinstance(value, bytes):
        value = canonical_json(value)
    return hashlib.sha256(value).hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def changed_paths(repo: Path) -> list[str]:
    output = git(repo, "status", "--porcelain=v1", "-z")
    paths: list[str] = []
    entries = output.split("\0") if output else []
    index = 0
    while index < len(entries):
        entry = entries[index]
        if not entry:
            index += 1
            continue
        status = entry[:2]
        path = entry[2:].removeprefix(" ")
        paths.append(path)
        if status[0] in {"R", "C"}:
            index += 1
            if index < len(entries):
                paths.append(entries[index])
        index += 1
    return sorted(set(paths))


def repository_fingerprint(repo: Path) -> str:
    """Hash branch, HEAD, and exact tracked and untracked working-tree content."""
    branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "HEAD")
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    raw_untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    untracked: list[dict[str, str]] = []
    for encoded in raw_untracked.split(b"\0"):
        if not encoded:
            continue
        relative = os.fsdecode(encoded)
        path = repo / relative
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            object_type = "symlink"
            content = digest(os.readlink(path))
        elif stat.S_ISREG(metadata.st_mode):
            object_type = "regular"
            content = digest(path.read_bytes())
        else:
            object_type = "other"
            content = "non_file"
        untracked.append(
            {
                "path": relative,
                "object_type": object_type,
                "mode": oct(stat.S_IMODE(metadata.st_mode)),
                "content": content,
            }
        )
    return digest(
        {"branch": branch, "head": head, "diff": digest(diff), "untracked": untracked}
    )


def compact_state_fingerprint(repo: Path) -> str:
    inputs = ["ops/NOW.md", "ops/STATE.json", "ops/QUEUE.md", "ops/V1_ROADMAP.json"]
    content = {
        relative: digest((repo / relative).read_bytes())
        for relative in inputs
        if (repo / relative).is_file()
    }
    return digest(content)


def relevant_processes(
    repo: Path, process_rows: Iterable[str] | None = None
) -> list[str]:
    """Return stable, redacted identities of workers that can overlap a cycle."""
    if process_rows is None:
        test_snapshot = os.environ.get("PROPERTY_RENTAL_TEST_PROCESS_ROWS")
        if test_snapshot is not None:
            process_rows = test_snapshot.splitlines()
    if process_rows is None:
        output = subprocess.run(
            ["ps", "-axo", "pid=,lstart=,command="],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
        process_rows = output.splitlines()
    needles = (
        "openclaw-supervisor-dispatch",
        "openclaw-hermes-task",
        "hermes-property-rental",
        "pytest",
        "vitest",
        "database-test.sh",
        "docker compose",
        "codex exec",
    )
    own_pid = os.getpid()
    identities: list[str] = []
    for row in process_rows:
        normalized = " ".join(row.split())
        if not normalized:
            continue
        first = normalized.split(" ", 1)[0]
        if first.isdigit() and int(first) == own_pid:
            continue
        hermes_worker = bool(
            re.search(r"(?:^|\s)(?:[^\s]*/)?hermes(?:\s|$)", normalized)
            and "--provider openai-codex" in normalized
        )
        if not hermes_worker and not any(needle in normalized for needle in needles):
            continue
        # Generic OpenClaw gateway and the controlling Codex process are not a
        # candidate worker.  Persist only a digest, never raw process arguments.
        if "openclaw gateway" in normalized and str(repo) not in normalized:
            continue
        identities.append(digest(normalized))
    return sorted(set(identities))


def process_fingerprint(repo: Path, rows: Iterable[str] | None = None) -> str:
    return digest(relevant_processes(repo, rows))


def actionable_fingerprint(repo: Path, preflight: dict[str, Any]) -> dict[str, str]:
    return {
        "repository": repository_fingerprint(repo),
        "compact_state": compact_state_fingerprint(repo),
        "process_state": process_fingerprint(repo),
        "actionable": digest(preflight),
    }


def stage_actionable_fingerprint(
    repo: Path,
    preflight: dict[str, Any],
    *,
    candidate: str,
    stage: str,
) -> str:
    """Bind a terminal/attempt decision to every actionable state input."""
    return digest(
        {
            **actionable_fingerprint(repo, preflight),
            "candidate": candidate,
            "stage": stage,
        }
    )


def normalize_usage(
    usage: dict[str, Any], policy: ModelPolicy, *, session_id: str | None = None
) -> dict[str, Any]:
    """Preserve provider-returned values; never invent unavailable metadata."""

    def available(key: str) -> Any:
        value = usage.get(key)
        return UNAVAILABLE if value is None else value

    exact_model = available("model")
    exact_session = usage.get("session_id") or session_id or UNAVAILABLE
    return {
        "effective_model": exact_model,
        "reasoning_effort": available("reasoning_effort"),
        "requested_reasoning_effort": policy.requested_reasoning,
        "invocation_route": policy.route,
        "session_id": exact_session,
        "input_token_usage": available("input_tokens"),
        "cache_read_token_usage": available("cache_read_tokens"),
        "output_token_usage": available("output_tokens"),
        "reasoning_token_usage": available("reasoning_tokens"),
        "total_token_usage": available("total_tokens"),
        "applicable_token_ceiling": policy.token_ceiling,
        "stage_name": policy.stage,
        "complex_review_classification_reason": policy.complex_review_reason,
    }


def validate_usage(usage: dict[str, Any], policy: ModelPolicy) -> None:
    returned_model = usage.get("model")
    if returned_model is None and policy.route == "direct Codex":
        if usage.get("invocation_config_verified") is not True:
            raise AutomationError(
                "unsupported_invocation_configuration",
                "direct Codex invocation configuration was not proved",
            )
    elif (
        not isinstance(returned_model, str) or returned_model.split("/")[-1] != MODEL_ID
    ):
        raise AutomationError(
            "unsupported_invocation_configuration",
            f"provider returned unsupported model {returned_model!r}",
        )
    returned_reasoning = usage.get("reasoning_effort")
    if (
        returned_reasoning is not None
        and returned_reasoning != policy.requested_reasoning
    ):
        raise AutomationError(
            "unsupported_invocation_configuration",
            "provider returned a reasoning effort different from the requested policy",
        )
    if usage.get("configured_max_tokens") != policy.token_ceiling:
        raise AutomationError(
            "unsupported_invocation_configuration",
            "the invocation did not prove the exact configured token ceiling",
        )
    total = usage.get("total_tokens")
    stop_reason = usage.get("stop_reason") or usage.get("finish_reason")
    if stop_reason in {
        "tool_ceiling",
        "session_ceiling",
        "token_ceiling",
        "length",
        "max_tokens",
        "max_turns",
    }:
        raise AutomationError(
            "model_session_or_token_ceiling",
            f"provider reported {stop_reason} at the configured ceiling",
        )
    if total is None:
        return
    if not isinstance(total, int) or total < 0:
        raise AutomationError(
            "pre_model_infrastructure_failure",
            "provider returned malformed total_tokens metadata",
        )
    if total > policy.token_ceiling:
        raise AutomationError(
            "model_session_or_token_ceiling",
            f"observed {total} tokens above ceiling {policy.token_ceiling}",
        )


def hermes_chat_usage(stderr: str, database: Path) -> dict[str, Any]:
    """Read exact metadata for the fresh quiet Hermes chat session.

    The supported ``hermes chat -Q`` route emits only ``session_id`` on
    stderr.  Token and effective-model evidence is therefore read from the
    installed Hermes session database, never inferred from requested values.
    """
    match = re.search(r"(?:^|\n)session_id:\s*([A-Za-z0-9_.-]+)\s*(?:\n|$)", stderr)
    if not match:
        return {}
    session_id = match.group(1)
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        session = connection.execute(
            """SELECT model, model_config, end_reason, input_tokens,
                      output_tokens, cache_read_tokens, reasoning_tokens
                 FROM sessions WHERE id = ?""",
            (session_id,),
        ).fetchone()
        usage = connection.execute(
            """SELECT SUM(api_call_count) AS api_calls,
                      SUM(input_tokens) AS input_tokens,
                      SUM(output_tokens) AS output_tokens,
                      SUM(cache_read_tokens) AS cache_read_tokens,
                      SUM(reasoning_tokens) AS reasoning_tokens
                 FROM session_model_usage WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
    except (OSError, sqlite3.Error):
        return {"session_id": session_id}
    finally:
        if "connection" in locals():
            connection.close()
    if session is None or usage is None:
        return {"session_id": session_id}
    try:
        config = json.loads(session["model_config"] or "{}")
    except json.JSONDecodeError:
        config = {}
    reasoning = config.get("reasoning_config")
    effort = reasoning.get("effort") if isinstance(reasoning, dict) else None
    def exact_metric(aggregate: object, session_value: object) -> int | None:
        value = aggregate if aggregate is not None else session_value
        return int(value) if value is not None else None

    input_tokens = exact_metric(usage["input_tokens"], session["input_tokens"])
    output_tokens = exact_metric(usage["output_tokens"], session["output_tokens"])
    cache_read = exact_metric(
        usage["cache_read_tokens"], session["cache_read_tokens"]
    )
    reasoning_tokens = exact_metric(
        usage["reasoning_tokens"], session["reasoning_tokens"]
    )
    api_calls = exact_metric(usage["api_calls"], None)
    result: dict[str, Any] = {
        "session_id": session_id,
        "model": session["model"],
        "reasoning_effort": effort,
        "configured_max_tokens": config.get("max_tokens"),
        "api_calls": api_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
    }
    end_reason = session["end_reason"]
    if end_reason in {
        "tool_ceiling",
        "session_ceiling",
        "token_ceiling",
        "length",
        "max_tokens",
        "max_turns",
    }:
        result["stop_reason"] = end_reason
    return result


SECRET_PATTERN = re.compile(
    rb"(?:BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|"
    rb"gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    rb"postgres(?:ql)?://[^\s]+:[^\s@]+@)",
    re.IGNORECASE,
)


def candidate_paths(repo: Path, mode: str) -> list[str]:
    """Return every candidate path, including deleted paths, NUL-safely."""
    if mode == "cached":
        raw = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z", "--"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
    elif mode == "worktree":
        paths = changed_paths(repo)
        return paths
    else:
        raise AutomationError(
            "unsupported_invocation_configuration", "unsupported guard mode"
        )
    return sorted(os.fsdecode(encoded) for encoded in raw.split(b"\0") if encoded)


def candidate_content(repo: Path, mode: str) -> list[tuple[str, bytes]]:
    """Return bytes for candidate objects that still exist in the selected view."""
    result: list[tuple[str, bytes]] = []
    for relative in candidate_paths(repo, mode):
        if mode == "cached":
            blob = subprocess.run(
                ["git", "show", f":{relative}"],
                cwd=repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if blob.returncode:
                continue
            content = blob.stdout
        else:
            path = repo / relative
            if path.is_symlink():
                content = os.fsencode(os.readlink(path))
            elif path.is_file():
                content = path.read_bytes()
            else:
                continue
        result.append((relative, content))
    return result


def publication_candidate_guard(repo: Path, mode: str) -> str | None:
    """Return a stable failure kind without ever echoing candidate contents."""
    for relative in candidate_paths(repo, mode):
        if re.fullmatch(r"docs/(?:00[1-9]|010)_.+", relative):
            return "canonical"
    for relative, content in candidate_content(repo, mode):
        if SECRET_PATTERN.search(content):
            return "secret"
    return None


def continuation_eligible(record: dict[str, Any], current: dict[str, str]) -> bool:
    """Enforce the single mechanical verification-only continuation contract."""
    return bool(
        record.get("stop_reason") == "model_session_or_token_ceiling"
        and record.get("implementation_complete") is True
        and record.get("required_check_failed") is not True
        and record.get("known_failing_check") in (None, "")
        and record.get("failed_check") in (None, "")
        and record.get("repair_failure") in (None, "")
        and record.get("last_failure_category") in (None, "")
        and record.get("repository_fingerprint") == current.get("repository")
        and record.get("compact_state_fingerprint") == current.get("compact_state")
        and current.get("process_state") == digest([])
        and record.get("protected_operation") is not True
        and record.get("policy_question") is not True
        and record.get("scope_change") is not True
        and record.get("secret_or_credential") is not True
        and record.get("continuation_used") is not True
        and record.get("requested_stage")
        in {
            "deterministic_verification",
            "independent_review",
            "publication",
            "post_publication_reconciliation",
        }
    )


def consume_continuation(
    path: Path, record: dict[str, Any], current: dict[str, str]
) -> None:
    if path.exists() or not continuation_eligible(record, current):
        raise AutomationError(
            "model_session_or_token_ceiling",
            "verification-only continuation is unavailable for this fingerprint",
        )
    atomic_write_json(
        path,
        {
            "used_at": utc_now(),
            "repository_fingerprint": current["repository"],
            "compact_state_fingerprint": current["compact_state"],
            "recursive_continuation_permitted": False,
        },
    )


def repeated_call_key(
    *,
    identity: str,
    arguments: list[str],
    fingerprints: dict[str, str],
    prior_result_category: str,
) -> str:
    return digest(
        {
            "identity": " ".join(identity.split()),
            "arguments": [" ".join(argument.split()) for argument in arguments],
            "fingerprints": fingerprints,
            "prior_result_category": prior_result_category,
        }
    )


def repeated_call_result(path: Path, key: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get("call_key") != key or record.get("result") != "failed":
        return None
    return {
        "category": "repeated_identical_tool_call",
        "suppressed_call": record.get("normalized_call", UNAVAILABLE),
        "preserved_underlying_result": record.get("underlying_result", UNAVAILABLE),
        "unchanged_state_reason": "repository, compact-state, process, arguments, and prior result fingerprints match",
        "exact_next_eligible_action": record.get(
            "exact_next_eligible_action", UNAVAILABLE
        ),
    }


def reserve_attempt(path: Path, *, stage: str, fingerprint: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if path.exists():
        record = json.loads(path.read_text())
    if record.get("fingerprint") != fingerprint:
        record = {"counters": {}, "previous_fingerprint": record.get("fingerprint")}
    record.setdefault("counters", {})
    prior_pending = record.get("pending")
    if isinstance(prior_pending, dict):
        record.setdefault("interrupted_reservations", []).append(
            {
                "stage": prior_pending.get("stage"),
                "reserved_at": prior_pending.get("reserved_at"),
                "recovered_at": utc_now(),
                "classification": "unclassified_interruption_no_attempt_consumed",
            }
        )
    reserved_at = utc_now()
    record.update(
        {
            "fingerprint": fingerprint,
            "pending": {"stage": stage, "reserved_at": reserved_at},
            "reserved_at": reserved_at,
        }
    )
    atomic_write_json(path, record)
    return record


def consume_attempt(path: Path, *, stage: str) -> dict[str, Any]:
    if not path.exists():
        raise AutomationError(
            "repository_integrity_uncertainty", "attempt reservation is missing"
        )
    record = json.loads(path.read_text())
    pending = record.get("pending")
    if not isinstance(pending, dict) or pending.get("stage") != stage:
        raise AutomationError(
            "repository_integrity_uncertainty", "attempt reservation is not exact"
        )
    counters = record.setdefault("counters", {})
    counters[stage] = int(counters.get(stage, 0)) + 1
    record["pending"] = None
    record["classified_at"] = utc_now()
    atomic_write_json(path, record)
    return record


def release_attempt(path: Path, *, stage: str) -> None:
    if not path.exists():
        return
    record = json.loads(path.read_text())
    pending = record.get("pending")
    if isinstance(pending, dict) and pending.get("stage") == stage:
        record["pending"] = None
    record["released_at"] = utc_now()
    atomic_write_json(path, record)


def persist_terminal_marker(
    root: Path, *, status: str, fingerprint: str, evidence: dict[str, Any]
) -> Path:
    """Atomically tombstone exactly one terminal actionable fingerprint."""
    path = root / status / f"{fingerprint}.json"
    atomic_write_json(
        path,
        {
            "status": status,
            "actionable_fingerprint": fingerprint,
            "timestamp": utc_now(),
            **evidence,
        },
    )
    return path


def task_packet(repo: Path, preflight: dict[str, Any], stage: str) -> dict[str, Any]:
    state = json.loads((repo / "ops/STATE.json").read_text())
    roadmap = json.loads((repo / "ops/V1_ROADMAP.json").read_text())
    candidate = state.get("next_candidate") or {}
    candidate_id = (
        candidate.get("roadmap_id")
        or candidate.get("id")
        or (state.get("roadmap") or {}).get("current_id")
    )
    roadmap_item: dict[str, Any] = next(
        (
            item
            for item in roadmap.get("tranches", [])
            if item.get("id") == candidate_id
        ),
        {},
    )
    fingerprints = actionable_fingerprint(repo, preflight)
    packet = {
        "schema_version": 2,
        "candidate": candidate_id,
        "stage": stage,
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "HEAD"),
        "repository_fingerprint": fingerprints["repository"],
        "compact_state_fingerprint": fingerprints["compact_state"],
        "process_state_fingerprint": fingerprints["process_state"],
        "preflight_fingerprint": fingerprints["actionable"],
        "task": roadmap_item.get("task")
        or candidate.get("task")
        or preflight.get("next_action"),
        "authorities": roadmap_item.get("authorities")
        or candidate.get("authorities")
        or [],
        "include": roadmap_item.get("include") or [],
        "exclude": roadmap_item.get("exclude") or [],
        "compact_inputs": [
            "ops/NOW.md",
            "ops/STATE.json",
            "ops/QUEUE.md",
            "ops/V1_ROADMAP.json",
        ],
        "acceptance_criteria": roadmap_item.get("acceptance")
        or (roadmap.get("acceptance_profiles") or {}).get(
            roadmap_item.get("acceptance_profile") or "complete", []
        ),
        "acceptance_profile": roadmap_item.get("acceptance_profile") or "complete",
        "canonical_paths": sorted(
            {
                path
                for authority in (roadmap_item.get("authorities") or [])
                for prefix, path in (
                    ("PR", "docs/003_PRODUCT_REQUIREMENTS.md"),
                    ("DB", "docs/004_DATABASE_MODEL.md"),
                    ("API", "docs/005_API_SPECIFICATION.md"),
                    ("TEST", "docs/007_TESTING_STRATEGY.md"),
                    ("SEC", "docs/008_SECURITY_MODEL.md"),
                    ("DEPLOY", "docs/009_DEPLOYMENT_ARCHITECTURE.md"),
                    ("DL", "docs/010_DECISION_LOG.md"),
                )
                if str(authority).startswith(prefix)
            }
        ),
        "durable_evidence_paths": [
            "ops/STATE.json",
            "ops/traceability.json",
            ".openclaw-automation-evidence (external, secret-free)",
        ],
        "authorization_boundaries": {
            "standing_authorization": roadmap_item.get("authorization") == "durable_v1",
            "protected_operation": bool(roadmap_item.get("protected_operation")),
            "prohibited": [
                "canonical policy invention",
                "scope expansion",
                "secrets or credentials",
                "production or destructive operations",
                "force push or history rewrite",
            ],
        },
        "output_contract": {
            "format": "one JSON object",
            "required": [
                "stage_result",
                "changed_paths",
                "verification",
                "blockers",
                "exact_next_action",
            ],
        },
    }
    if stage == "independent_review":
        packet["review_only"] = True
        packet["output_contract"] = {
            "format": "one JSON object",
            "required": [
                "passed",
                "findings",
                "reviewed_repository_fingerprint",
                "reviewed_paths",
                "exact_next_action",
            ],
        }
    return packet


def health_classification(
    *,
    enabled: bool,
    scheduler_ok: bool,
    project_stage: str,
    blocker_kind: str | None,
    installed: bool = True,
) -> str:
    if not installed:
        return "scheduler_unhealthy"
    if not enabled:
        return "scheduler_intentionally_disabled"
    if not scheduler_ok:
        return "scheduler_unhealthy"
    if blocker_kind == "owner_policy_decision":
        return "project_blocked_owner_decision"
    if blocker_kind == "secret_credential_or_protected_operation":
        return "project_blocked_protected_operation"
    mapping = {
        "implementation": "implementation_in_progress",
        "deterministic_verification": "verification_in_progress",
        "independent_review": "independent_review_in_progress",
        "publication": "publication_pending",
        "post_publication_reconciliation": "state_reconciliation_required",
        "complete": "candidate_completed",
        "repair_exhausted": "bounded_repair_exhausted",
        "recovered": "automation_recovered",
    }
    return mapping.get(project_stage, "scheduler_healthy_idle")


def usage_record(
    *,
    usage: dict[str, Any],
    policy: ModelPolicy,
    result: str,
    repository_fingerprint_value: str,
    next_action: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    record = normalize_usage(usage, policy, session_id=session_id)
    record.update(
        {
            "timestamp": utc_now(),
            "stage_result": result,
            "repository_fingerprint": repository_fingerprint_value,
            "exact_next_action": next_action,
        }
    )
    return record


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "publication-guard":
        failure = publication_candidate_guard(Path.cwd(), sys.argv[2])
        if failure == "canonical":
            print(
                "Canonical document change requires separate authorization",
                file=sys.stderr,
            )
            raise SystemExit(65)
        if failure == "secret":
            print(
                "Potential secret material detected in candidate content",
                file=sys.stderr,
            )
            raise SystemExit(66)
        raise SystemExit(0)
    print("usage: openclaw_automation.py publication-guard MODE", file=sys.stderr)
    raise SystemExit(64)
