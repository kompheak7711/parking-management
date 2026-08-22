#!/usr/bin/env python3
"""Fail-closed restoration of the one existing Property Rental supervisor."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from openclaw_automation import (
    atomic_write_json,
    changed_paths,
    digest,
    relevant_processes,
    repository_fingerprint,
    utc_now,
)

SUPERVISOR_ID = "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb"
SUPERVISOR_NAME = "property-rental-24x7-supervisor"
EXPECTED_INTERVAL_MS = 1_800_000
ROUTING_REVISION = "v1-019-sign-in-context-routing-v4"
EXHAUSTED_ROUTING_REVISION = "v1-019-context-restoration-repair-v3"
PRIOR_ROUTING_REVISION = "v1-019-invocation-contract-repair-v2"
INCIDENT_BASELINE = "d6eb7e73610b2a72cf38f4b32468226e9e76a436"
LEGACY_INVOCATION_INCIDENT_BASELINE = "d877cf3b6648083f97e54d661933e3d188999dae"
REPAIR_PUBLICATION_COMMIT = "e0469b6d519c0947662204869a535c7080185638"
FAILED_ROUTING_FINGERPRINT = (
    "ab2d0cb1c2d3de9e287d595effddd4e4f9de5bdafc361deea003cbde10dcfdc2"
)
FAILED_SESSION_ID = "6baf17e6e77d7582e72b2e19a40ab806"
CONTEXT_INCIDENT_SESSION_ID = "61d145e0655c5298cbcfa576fff3ff78"
CONTEXT_INCIDENT_API_CALLS = 2
CONTEXT_INCIDENT_INPUT_TOKENS = 16_881
CONTEXT_INCIDENT_OUTPUT_TOKENS = 422
CONTEXT_INCIDENT_COUNTED_TOKENS = 17_303
CONTEXT_INCIDENT_CACHE_READ_TOKENS = 9_216
CONTEXT_INCIDENT_FALSE_PREDICTION = 109_152
EXHAUSTED_SIGN_IN_FINGERPRINT = (
    "f6a8bbead87cacf9ae60da196459bc4f2ef760dd32e6dff8624c24ef4f8b8e77"
)
EXHAUSTED_SIGN_IN_SESSIONS = (
    "61d145e0655c5298cbcfa576fff3ff78",
    "c851c8930c35456a94a9dcb2c5ef9e09",
    "990342c0dca23620d6e5958c0d4ad5d2",
)
SIGN_IN_WRITABLE_PATHS = {
    "frontend/src/App.tsx",
    "frontend/src/App.test.tsx",
    "frontend/src/styles.css",
    "frontend/src/authClient.ts",
    "frontend/src/authClient.test.ts",
    "ops/NOW.md",
    "ops/STATE.json",
    "ops/traceability.json",
}
TERMINAL_RESTORATION_STATUSES = {"complete", "failed_closed"}
FALSE_FAILURE_METADATA_COMMIT = "7c0f67d07092702229329a57176ae0fdc95afd12"
FALSE_FAILURE_RUN_ID = 32511133185
NOTIFICATION_SOURCE_JOB_ID = "8db8cc98-56a1-4687-9988-fd7e3750c51b"
DEFAULT_NOTIFICATION_TIMEOUT = 30.0
DEFAULT_TERMINALIZER_HANDOFF_TIMEOUT = 60.0


class RestorationError(RuntimeError):
    """A fail-closed restoration condition."""


def run(
    repo: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
    )


def atomic_text(path: Path, value: str) -> None:
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


def read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RestorationError(f"{description} is missing or invalid") from error
    if not isinstance(value, dict):
        raise RestorationError(f"{description} is not an object")
    return value


def exact_executable(path: str, description: str) -> str:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or not candidate.is_file()
        or not os.access(candidate, os.X_OK)
    ):
        raise RestorationError(
            f"configured {description} executable is unavailable: {path}"
        )
    return str(candidate.resolve())


def redact_sensitive_output(value: str) -> tuple[str, bool]:
    """Keep captured diagnostics without persisting credential-shaped env values."""
    redacted = value
    changed = False
    for name, secret in os.environ.items():
        upper = name.upper()
        if (
            len(secret) >= 8
            and any(
                marker in upper
                for marker in ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTH")
            )
            and secret in redacted
        ):
            redacted = redacted.replace(secret, "[REDACTED]")
            changed = True
    return redacted, changed


def wait_for_ci(
    repo: Path,
    *,
    github: str,
    commit: str,
    evidence: Path,
    expected_run_id: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(repo / "scripts/openclaw-wait-for-ci.sh"),
        "--github",
        github,
        "--evidence",
        str(evidence),
    ]
    if expected_run_id is not None:
        command.extend(["--expected-run-id", str(expected_run_id)])
    command.append(commit)
    return run(repo, *command, check=False)


def successful_ci_evidence(
    path: Path, *, commit: str, expected_run_id: int | None = None
) -> dict[str, Any]:
    value = read_json_object(path, "restoration CI evidence")
    if (
        value.get("status") != "success"
        or value.get("commit") != commit
        or value.get("head_sha") != commit
        or value.get("workflow_status") != "completed"
        or value.get("conclusion") != "success"
        or not isinstance(value.get("run_id"), int)
        or (expected_run_id is not None and value.get("run_id") != expected_run_id)
    ):
        raise RestorationError(
            "restoration CI evidence did not prove the exact successful run"
        )
    return value


def pid_exists(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cron(openclaw: str, repo: Path, action: str) -> dict[str, Any]:
    result = run(
        repo,
        openclaw,
        "cron",
        action,
        SUPERVISOR_ID,
        "--expect-final",
        check=False,
    )
    if result.returncode:
        raise RestorationError(
            f"openclaw cron {action} failed with exit {result.returncode}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RestorationError(
            f"openclaw cron {action} returned invalid JSON"
        ) from error
    if not isinstance(value, dict):
        raise RestorationError(f"openclaw cron {action} returned a non-object")
    return value


def restoration_label(expected_repair_head: str) -> str:
    return f"com.property-rental.post-exit-restoration.{expected_repair_head[:12]}"


def terminalizer_label(expected_repair_head: str) -> str:
    return f"{restoration_label(expected_repair_head)}.terminalizer"


def unload_launchd_label(launchctl: str, label: str) -> None:
    """Unload only this exact submitted one-shot job.

    ``launchctl submit`` jobs have inferred keepalive behavior.  Terminal
    evidence is written before this function is called so a delayed signal
    cannot erase the fail-closed result.
    """
    target = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        [launchctl, "bootout", target],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        combined = f"{result.stdout}\n{result.stderr}".strip()
        if "Could not find service" not in combined:
            raise RestorationError(
                f"launchctl could not unload exact restoration label {label}: "
                f"exit {result.returncode}"
            )


def unload_restoration_job(launchctl: str, expected_repair_head: str) -> None:
    unload_launchd_label(launchctl, restoration_label(expected_repair_head))


def exact_supervisor(job: dict[str, Any], repo: Path) -> None:
    schedule = job.get("schedule") or {}
    payload = job.get("payload") or {}
    checks = {
        "id": job.get("id") == SUPERVISOR_ID,
        "declaration": job.get("declarationKey") == "property-rental-24x7-v1",
        "name": job.get("name") == SUPERVISOR_NAME,
        "agent": job.get("agentId") == "property-rental-supervisor",
        "session": job.get("sessionTarget") == "isolated",
        "kind": schedule.get("kind") == "every",
        "interval": schedule.get("everyMs") == EXPECTED_INTERVAL_MS,
        "payload_kind": payload.get("kind") == "command",
        "payload_argv": isinstance(payload.get("argv"), list)
        and len(payload["argv"]) == 1
        and Path(str(payload["argv"][0])).resolve()
        == (repo / "scripts/openclaw-supervisor-dispatch.sh").resolve(),
        "payload_cwd": isinstance(payload.get("cwd"), str)
        and bool(payload["cwd"])
        and Path(payload["cwd"]).resolve() == repo.resolve(),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise RestorationError(
            "the existing supervisor identity or schedule contract drifted: "
            + ", ".join(failed)
        )


def git(repo: Path, *arguments: str) -> str:
    return run(repo, "git", *arguments).stdout.strip()


def v1_019_integrity(
    repo: Path, dispatch_state: Path, *, expected_head: str | None
) -> dict[str, Any]:
    state = json.loads((repo / "ops/STATE.json").read_text())
    branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "HEAD")
    upstream = git(repo, "rev-parse", "@{upstream}")
    candidate = state.get("next_candidate") or {}
    current = str((state.get("roadmap") or {}).get("current_id") or "")
    if branch != state.get("branch") or current != "V1-019":
        raise RestorationError(
            "compact state no longer identifies V1-019 on its authorized branch"
        )
    if candidate.get("roadmap_id") == "V1-020" or candidate.get("id") == "V1-020":
        raise RestorationError(
            "V1-020 was selected contrary to the restoration boundary"
        )
    if head != upstream:
        raise RestorationError("local HEAD is not synchronized with its upstream")
    if expected_head is not None and head != expected_head:
        raise RestorationError(
            "repair publication HEAD changed before restoration metadata"
        )
    paths = changed_paths(repo)
    if paths:
        record_path = dispatch_state / "candidates/V1-019.json"
        try:
            record = json.loads(record_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RestorationError(
                "dirty V1-019 work has no readable dispatcher record"
            ) from error
        interrupted_fresh_scope = bool(
            cleaned_fresh_sequence_resume_required(dispatch_state, record)
            and record.get("expected_worktree_paths") == []
            and all(path in SIGN_IN_WRITABLE_PATHS for path in paths)
        )
        if not interrupted_fresh_scope and (
            record.get("candidate") != "V1-019"
            or sorted(record.get("expected_worktree_paths") or []) != paths
            or record.get("repository_fingerprint") != repository_fingerprint(repo)
        ):
            raise RestorationError(
                "dirty V1-019 work is not bound to exact dispatcher evidence"
            )
    return {"branch": branch, "head": head, "paths": paths, "state": state}


def restoration_metadata(
    repo: Path,
    expected_repair_head: str,
    *,
    expected_continuation_head: str | None = None,
    github: str | None = None,
    ci_evidence: Path | None = None,
) -> str:
    state_path = repo / "ops/STATE.json"
    now_path = repo / "ops/NOW.md"
    state = json.loads(state_path.read_text())
    repair = state.setdefault("automation_repair", {})
    continuation_head = expected_continuation_head or (
        git(repo, "rev-parse", "HEAD")
        if repair.get("status") == "restored"
        else expected_repair_head
    )
    if repair.get("status") == "restored":
        restoration = repair.get("post_exit_restoration") or {}
        head = git(repo, "rev-parse", "HEAD")
        metadata_commit: str | None = None
        candidates = [
            restoration.get("metadata_commit"),
            head,
            FALSE_FAILURE_METADATA_COMMIT,
        ]
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            exists = run(
                repo, "git", "cat-file", "-e", f"{candidate}^{{commit}}", check=False
            )
            if exists.returncode:
                continue
            parent = git(repo, "rev-parse", f"{candidate}^")
            committed_paths = sorted(
                line
                for line in git(
                    repo,
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    candidate,
                ).splitlines()
                if line
            )
            if parent == expected_repair_head and committed_paths == [
                "ops/NOW.md",
                "ops/STATE.json",
            ]:
                metadata_commit = candidate
                break
        ancestor = (
            metadata_commit is not None
            and run(
                repo,
                "git",
                "merge-base",
                "--is-ancestor",
                metadata_commit,
                continuation_head,
                check=False,
            ).returncode
            == 0
        )
        if (
            restoration.get("status") != "metadata_published_waiting_enable"
            or restoration.get("repair_publication_commit") != expected_repair_head
            or metadata_commit is None
            or not ancestor
            or head != continuation_head
            or head != git(repo, "rev-parse", "@{upstream}")
        ):
            raise RestorationError(
                "published restoration metadata does not match its exact resumable contract"
            )
        if github is not None and ci_evidence is not None:
            ci = wait_for_ci(
                repo,
                github=github,
                commit=metadata_commit,
                evidence=ci_evidence,
                expected_run_id=(
                    FALSE_FAILURE_RUN_ID
                    if metadata_commit == FALSE_FAILURE_METADATA_COMMIT
                    else None
                ),
            )
            if ci.returncode:
                raise RestorationError(
                    f"restoration metadata CI failed for {metadata_commit}; "
                    f"diagnostics: {ci_evidence}"
                )
            successful_ci_evidence(
                ci_evidence,
                commit=metadata_commit,
                expected_run_id=(
                    FALSE_FAILURE_RUN_ID
                    if metadata_commit == FALSE_FAILURE_METADATA_COMMIT
                    else None
                ),
            )
        return metadata_commit
    if repair.get("status") != "published_awaiting_post_exit_restoration":
        raise RestorationError(
            "automation repair is not awaiting post-exit restoration"
        )
    if (
        continuation_head != expected_repair_head
        or git(repo, "rev-parse", "HEAD") != expected_repair_head
    ):
        raise RestorationError(
            "repair publication HEAD changed before restoration metadata"
        )
    repair.update(
        {
            "status": "restored",
            "scheduler_enabled": False,
            "stop_after_candidate": "V1-019",
            "post_exit_restoration": {
                "status": "metadata_published_waiting_enable",
                "repair_publication_commit": expected_repair_head,
                "timestamp": utc_now(),
            },
        }
    )
    state["timestamp"] = utc_now()
    atomic_write_json(state_path, state)
    now = now_path.read_text()
    marker = (
        "\n<!-- POST_EXIT_RESTORATION_BEGIN -->\n"
        "- Post-exit restoration metadata is published; the existing supervisor remains "
        "disabled until the continuation enables it.\n"
        "- V1-019 remains the only active candidate; V1-020 successor activation is held.\n"
        "<!-- POST_EXIT_RESTORATION_END -->\n"
    )
    if "<!-- POST_EXIT_RESTORATION_BEGIN -->" in now:
        before = now.split("<!-- POST_EXIT_RESTORATION_BEGIN -->", 1)[0].rstrip()
        now = before + marker
    else:
        now = now.rstrip() + marker
    atomic_text(now_path, now)
    if changed_paths(repo) != ["ops/NOW.md", "ops/STATE.json"]:
        raise RestorationError(
            "restoration metadata changed unexpected repository paths"
        )
    run(repo, "git", "add", "--", "ops/NOW.md", "ops/STATE.json")
    run(repo, "git", "diff", "--cached", "--check")
    run(repo, "git", "commit", "-m", "ops: authorize post-exit supervisor restoration")
    commit = git(repo, "rev-parse", "HEAD")
    run(repo, "git", "push")
    if github is not None and ci_evidence is not None:
        ci = wait_for_ci(
            repo,
            github=github,
            commit=commit,
            evidence=ci_evidence,
        )
    else:
        ci = run(
            repo, str(repo / "scripts/openclaw-wait-for-ci.sh"), commit, check=False
        )
    if ci.returncode:
        diagnostic = f"; diagnostics: {ci_evidence}" if ci_evidence else ""
        raise RestorationError(
            f"restoration metadata CI failed for {commit}{diagnostic}"
        )
    if ci_evidence is not None:
        successful_ci_evidence(ci_evidence, commit=commit)
    if git(repo, "rev-parse", "HEAD") != git(repo, "rev-parse", "@{upstream}"):
        raise RestorationError("restoration metadata is not synchronized after CI")
    return commit


def supersede_v1_019_incident(
    repo: Path, dispatch_state: Path, *, candidate_base_commit: str
) -> dict[str, Any]:
    """Preserve the failed incident, then create the exact fresh routing lifecycle."""
    candidate_path = dispatch_state / "candidates/V1-019.json"
    attempt_path = dispatch_state / "attempts/V1-019.json"
    last_failure_path = dispatch_state / "last-failure.json"
    try:
        current = json.loads(candidate_path.read_text())
    except FileNotFoundError:
        current = None
    except json.JSONDecodeError as error:
        raise RestorationError(
            "the stale V1-019 candidate record is invalid JSON"
        ) from error
    if current is None or (
        not isinstance(current, dict) or current.get("candidate") != "V1-019"
    ):
        raise RestorationError("the stale candidate record does not identify V1-019")

    fingerprint = repository_fingerprint(repo)
    if (
        isinstance(current, dict)
        and current.get("routing_revision") == ROUTING_REVISION
        and current.get("candidate_base_commit") == candidate_base_commit
        and current.get("repository_fingerprint") == fingerprint
    ):
        return {
            "status": "already_superseded",
            "candidate_base_commit": candidate_base_commit,
            "repository_fingerprint": fingerprint,
        }
    current_usage = current.get("model_usage") if isinstance(current, dict) else None
    failed_usage = (
        current_usage[-1] if isinstance(current_usage, list) and current_usage else {}
    )
    if current is not None and (
        current.get("stage") != "implementation"
        or current.get("routing_revision") != "v1-019-code69-repair-v1"
        or current.get("candidate_base_commit") != LEGACY_INVOCATION_INCIDENT_BASELINE
        or current.get("implementation_complete") is True
        or current.get("expected_worktree_paths") not in (None, [])
        or current.get("completed_implementation_substages") not in (None, [])
        or failed_usage.get("session_id") != FAILED_SESSION_ID
        or failed_usage.get("stage_result") != "unsupported_invocation_configuration"
        or failed_usage.get("api_calls_completed") != 0
        or failed_usage.get("total_token_usage") != 0
    ):
        raise RestorationError(
            "the V1-019 record no longer matches the exact zero-usage invocation incident"
        )

    prior_attempt: dict[str, Any] | None = None
    try:
        value = json.loads(attempt_path.read_text())
        prior_attempt = value if isinstance(value, dict) else None
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as error:
        raise RestorationError(
            "the stale V1-019 attempt evidence is invalid JSON"
        ) from error
    implementation_attempts = int(
        ((prior_attempt or {}).get("counters") or {}).get("implementation", 0)
    )
    if prior_attempt is None or implementation_attempts != 1:
        raise RestorationError(
            "the V1-019 recorded attempt evidence no longer matches the incident"
        )

    prior_failure: dict[str, Any] | None = None
    try:
        value = json.loads(last_failure_path.read_text())
        prior_failure = value if isinstance(value, dict) else None
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as error:
        raise RestorationError(
            "the stale last-failure evidence is invalid JSON"
        ) from error
    if (
        prior_failure is None
        or prior_failure.get("actionable_fingerprint") != FAILED_ROUTING_FINGERPRINT
        or prior_failure.get("category") != "unsupported_invocation_configuration"
        or prior_failure.get("owner_action_required") is not False
    ):
        raise RestorationError(
            "the current failure does not match the exact recoverable routing fingerprint"
        )
    failed_marker = (
        dispatch_state
        / "terminal/routing_recovery_pending"
        / f"{FAILED_ROUTING_FINGERPRINT}.json"
    )
    try:
        marker_evidence = json.loads(failed_marker.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RestorationError(
            "the exact failed routing marker is missing or invalid"
        ) from error
    if (
        marker_evidence.get("actionable_fingerprint") != FAILED_ROUTING_FINGERPRINT
        or marker_evidence.get("category") != "unsupported_invocation_configuration"
    ):
        raise RestorationError(
            "the exact failed routing marker changed before supersession"
        )

    # All incident identities are proven before any live evidence is moved.
    archive = dispatch_state / "superseded/v1-019-invocation-contract"
    archive.mkdir(parents=True, exist_ok=True)
    archive_key = f"{int(time.time() * 1000)}-{candidate_base_commit[:12]}"
    atomic_write_json(archive / f"candidate-{archive_key}.json", current)
    atomic_write_json(archive / f"attempt-{archive_key}.json", prior_attempt)
    atomic_write_json(archive / f"last-failure-{archive_key}.json", prior_failure)
    attempt_path.unlink()
    last_failure_path.unlink()
    failed_marker.replace(archive / f"terminal-{archive_key}.json")

    preserved_markers = sorted(
        str(path.relative_to(dispatch_state))
        for path in (dispatch_state / "terminal").glob("*/*.json")
        if path.is_file()
    )
    incident = {
        "status": "superseded_by_routing_repair",
        "timestamp": utc_now(),
        "routing_revision": ROUTING_REVISION,
        "superseded_routing_fingerprint": FAILED_ROUTING_FINGERPRINT,
        "prior_stage": current.get("stage") if current else None,
        "prior_session_id": FAILED_SESSION_ID,
        "prior_model_usage": current.get("model_usage") if current else None,
        "prior_attempt_evidence": prior_attempt,
        "prior_recorded_attempt_counter": 1,
        "model_attempts_consumed": 0,
        "prior_automatic_repair_counter": 0,
        "prior_last_failure": prior_failure,
        "preserved_terminal_markers": preserved_markers,
        "archive_key": archive_key,
    }
    atomic_write_json(archive / f"supersession-{archive_key}.json", incident)
    fresh = {
        "candidate": "V1-019",
        "stage": "implementation",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "routing_revision": ROUTING_REVISION,
        "candidate_base_commit": candidate_base_commit,
        "initial_repository_fingerprint": fingerprint,
        "repository_fingerprint": fingerprint,
        "initial_changed_paths": [],
        "expected_worktree_paths": [],
        "completed_implementation_substages": [],
        "ceiling_recovery_attempts": {},
        "recovery_generation": 0,
        "recovery_pending": False,
        "corrected_routing_retry": {
            "eligible_attempts": 1,
            "consumed_attempts": 0,
            "failed_routing_fingerprint": FAILED_ROUTING_FINGERPRINT,
            "status": "eligible_after_publication",
        },
        "continuation_used": False,
        "events": [
            {
                "stage": "automation_routing_repair",
                "result": "superseded_failed_incident",
                "routing_revision": ROUTING_REVISION,
                "repository_commit": candidate_base_commit,
                "repository_fingerprint": fingerprint,
                "original_recorded_attempts": 1,
                "model_attempts_consumed": 0,
                "original_automatic_recovery_attempts": 0,
                "archive_key": archive_key,
            }
        ],
    }
    atomic_write_json(candidate_path, fresh)
    return incident


def validate_pending_sign_in_marker(
    dispatch_state: Path,
    record: dict[str, Any],
    *,
    expected_attempt: int,
    expected_status: str = "routing_recovery_pending",
) -> None:
    pending_fingerprint = record.get("pending_recovery_marker_fingerprint")
    if not isinstance(pending_fingerprint, str) or not pending_fingerprint:
        raise RestorationError(
            "the pending sign-in recovery marker identity is missing"
        )
    marker_path = (
        dispatch_state / f"terminal/{expected_status}" / f"{pending_fingerprint}.json"
    )
    marker = read_json_object(marker_path, "pending V1-019 recovery marker")
    if (
        marker.get("status") != expected_status
        or marker.get("phase") != "sign_in"
        or marker.get("attempt") != expected_attempt
        or marker.get("actionable_fingerprint") != pending_fingerprint
    ):
        raise RestorationError("the exact pending sign-in recovery marker drifted")


def _exhausted_incident_artifacts(dispatch_state: Path) -> list[dict[str, Any]]:
    """Index exact immutable artifacts for the three exhausted sign-in sessions."""
    dispatch_state = dispatch_state.resolve()
    paths: set[Path] = set()
    for session_id in EXHAUSTED_SIGN_IN_SESSIONS:
        for relative in (
            f"budgets/V1-019-implementation-{session_id}.json",
            f"usage/V1-019-implementation-{session_id}.json",
            f"hermes-sessions/{session_id}/hermes.stderr",
            f"hermes-sessions/{session_id}/logs/agent.log",
            f"hermes-sessions/{session_id}/logs/errors.log",
            f"hermes-sessions/{session_id}/state.db",
        ):
            candidate = dispatch_state / relative
            if not candidate.exists() and not candidate.is_symlink():
                raise RestorationError(
                    f"historical Hermes artifact is missing: {relative}"
                )
            try:
                metadata = candidate.lstat()
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(dispatch_state)
            except (OSError, ValueError) as error:
                raise RestorationError(
                    f"historical Hermes artifact escaped its boundary: {relative}"
                ) from error
            if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise RestorationError(
                    f"historical Hermes artifact is not an exact regular file: {relative}"
                )
            paths.add(candidate)
        manifests = sorted(
            path
            for path in (dispatch_state / "manifests").glob(f"*{session_id}*.json")
            if path.is_file()
        )
        if len(manifests) != 1:
            raise RestorationError(
                f"historical Hermes session {session_id} must have exactly one manifest"
            )
        manifest = manifests[0]
        try:
            manifest_metadata = manifest.lstat()
            resolved_manifest = manifest.resolve(strict=True)
            resolved_manifest.relative_to(dispatch_state)
        except (OSError, ValueError) as error:
            raise RestorationError(
                f"historical Hermes manifest escaped its boundary: {manifest.name}"
            ) from error
        if manifest.is_symlink() or not stat.S_ISREG(manifest_metadata.st_mode):
            raise RestorationError(
                f"historical Hermes manifest is not an exact regular file: {manifest.name}"
            )
        paths.add(manifest)
        value = read_json_object(manifest, "historical Hermes manifest")
        raw_task_path = Path(str(value.get("task_path") or ""))
        task_path = raw_task_path.resolve()
        try:
            task_path.relative_to(dispatch_state.resolve())
        except ValueError as error:
            raise RestorationError(
                "historical Hermes task escaped the dispatch-state archive boundary"
            ) from error
        if (
            raw_task_path.is_symlink()
            or not task_path.is_file()
            or not stat.S_ISREG(task_path.lstat().st_mode)
        ):
            raise RestorationError(
                f"historical Hermes task is missing for session {session_id}"
            )
        paths.add(task_path)
    if len(paths) != len(EXHAUSTED_SIGN_IN_SESSIONS) * 8:
        raise RestorationError(
            "the exhausted sign-in artifact set is not exact and complete"
        )
    return [
        {
            "path": str(path.relative_to(dispatch_state)),
            "bytes": path.stat().st_size,
            "sha256": digest(path.read_bytes()),
        }
        for path in sorted(paths)
    ]


def validate_exhausted_v1_019_sign_in(
    dispatch_state: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = read_json_object(
        dispatch_state / "candidates/V1-019.json", "exhausted V1-019 candidate"
    )
    attempt = read_json_object(
        dispatch_state / "attempts/V1-019.json", "exhausted V1-019 attempt"
    )
    failure = read_json_object(
        dispatch_state / "last-failure.json", "exhausted V1-019 failure"
    )
    marker = read_json_object(
        dispatch_state
        / "terminal/repair_exhausted"
        / f"{EXHAUSTED_SIGN_IN_FINGERPRINT}.json",
        "exhausted V1-019 marker",
    )
    usage = candidate.get("model_usage") or []
    exact_usage = bool(
        isinstance(usage, list)
        and len(usage) == len(EXHAUSTED_SIGN_IN_SESSIONS)
        and all(isinstance(item, dict) for item in usage)
    )
    session_ids = tuple(item.get("session_id") for item in usage) if exact_usage else ()
    if (
        candidate.get("candidate") != "V1-019"
        or candidate.get("routing_revision") != EXHAUSTED_ROUTING_REVISION
        or candidate.get("stage") != "implementation"
        or candidate.get("completed_implementation_substages") != []
        or candidate.get("expected_worktree_paths") != []
        or candidate.get("bounded_recovery_exhausted") is not True
        or candidate.get("recovery_pending") is not False
        or candidate.get("ceiling_recovery_attempts") != {"sign_in": 3}
        or session_ids != EXHAUSTED_SIGN_IN_SESSIONS
        or attempt.get("fingerprint") != EXHAUSTED_SIGN_IN_FINGERPRINT
        or (attempt.get("counters") or {}).get("implementation") != 1
        or attempt.get("pending") is not None
        or failure.get("category") != "model_session_or_token_ceiling"
        or failure.get("actionable_fingerprint") != EXHAUSTED_SIGN_IN_FINGERPRINT
        or failure.get("owner_action_required") is not True
        or marker.get("status") != "repair_exhausted"
        or marker.get("phase") != "sign_in"
        or marker.get("attempts") != 3
        or marker.get("actionable_fingerprint") != EXHAUSTED_SIGN_IN_FINGERPRINT
    ):
        raise RestorationError(
            "the live V1-019 state does not match the exact authorized exhausted sign-in incident"
        )
    return candidate, attempt, failure, marker


def rebase_exhausted_v1_019_sign_in(
    repo: Path, dispatch_state: Path, *, candidate_base_commit: str
) -> dict[str, Any]:
    """Consume this Owner action once after repair CI and create one fresh sequence."""
    candidate_path = dispatch_state / "candidates/V1-019.json"
    current = read_json_object(candidate_path, "V1-019 candidate record")
    fingerprint = repository_fingerprint(repo)
    authorization = current.get("owner_authorized_fresh_sign_in_sequence") or {}
    if (
        current.get("routing_revision") == ROUTING_REVISION
        and authorization.get("exhausted_fingerprint")
        == EXHAUSTED_SIGN_IN_FINGERPRINT
        and authorization.get("consumed") is True
        and authorization.get("transition_status") == "cleanup_pending"
    ):
        _complete_exhausted_rebase_cleanup(dispatch_state, current)
        current = read_json_object(candidate_path, "resumed fresh V1-019 candidate record")
        current.update(
            {
                "candidate_base_commit": candidate_base_commit,
                "initial_repository_fingerprint": fingerprint,
                "repository_fingerprint": fingerprint,
                "updated_at": utc_now(),
            }
        )
        current.setdefault("events", []).append(
            {
                "stage": "automation_context_routing_repair",
                "result": "exhausted_cleanup_rebased_after_follow_up_repair",
                "routing_revision": ROUTING_REVISION,
                "repository_commit": candidate_base_commit,
                "repository_fingerprint": fingerprint,
                "owner_authorization_consumed": False,
            }
        )
        atomic_write_json(candidate_path, current)
        return {
            "status": "cleanup_rebased_after_follow_up_repair",
            "archive": authorization.get("archive"),
            "repository_fingerprint": fingerprint,
        }
    if (
        current.get("routing_revision") == ROUTING_REVISION
        and current.get("candidate_base_commit") == candidate_base_commit
        and current.get("repository_fingerprint") == fingerprint
        and authorization.get("exhausted_fingerprint") == EXHAUSTED_SIGN_IN_FINGERPRINT
        and authorization.get("consumed") is True
    ):
        _complete_exhausted_rebase_cleanup(dispatch_state, current)
        return {
            "status": "already_rebased_from_exhaustion",
            "archive": authorization.get("archive"),
        }
    candidate, attempt, failure, marker = validate_exhausted_v1_019_sign_in(
        dispatch_state
    )
    artifacts = _exhausted_incident_artifacts(dispatch_state)
    archive = (
        dispatch_state
        / "superseded/v1-019-sign-in-context-v3"
        / f"{int(time.time() * 1000)}-{candidate_base_commit[:12]}"
    )
    archive.mkdir(parents=True, exist_ok=False)
    atomic_write_json(archive / "candidate.json", candidate)
    atomic_write_json(archive / "attempt.json", attempt)
    atomic_write_json(archive / "last-failure.json", failure)
    atomic_write_json(archive / "repair-exhausted.json", marker)
    atomic_write_json(
        archive / "artifact-index.json",
        {
            "schema_version": 1,
            "routing_revision": EXHAUSTED_ROUTING_REVISION,
            "exhausted_fingerprint": EXHAUSTED_SIGN_IN_FINGERPRINT,
            "sessions": list(EXHAUSTED_SIGN_IN_SESSIONS),
            "artifacts": artifacts,
        },
    )
    fresh = {
        "candidate": "V1-019",
        "stage": "implementation",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "routing_revision": ROUTING_REVISION,
        "candidate_base_commit": candidate_base_commit,
        "initial_repository_fingerprint": fingerprint,
        "repository_fingerprint": fingerprint,
        "initial_changed_paths": [],
        "expected_worktree_paths": [],
        "completed_implementation_substages": [],
        "ceiling_recovery_attempts": {},
        "context_materialization_attempts": {},
        "recovery_generation": 1,
        "recovery_pending": True,
        "bounded_recovery_exhausted": False,
        "continuation_used": False,
        "owner_authorized_fresh_sign_in_sequence": {
            "authorization": "owner_direct_takeover_2026-08-22",
            "consumed": True,
            "consumed_at": utc_now(),
            "eligible_sequences": 1,
            "exhausted_fingerprint": EXHAUSTED_SIGN_IN_FINGERPRINT,
            "archive": str(archive),
            "transition_status": "cleanup_pending",
        },
        "events": [
            {
                "stage": "automation_context_routing_repair",
                "result": "exhausted_sign_in_authorized_once",
                "routing_revision": ROUTING_REVISION,
                "repository_commit": candidate_base_commit,
                "repository_fingerprint": fingerprint,
                "owner_authorization_consumed": True,
                "ceiling_recovery_attempts_reset": True,
            }
        ],
    }
    atomic_write_json(candidate_path, fresh)
    _complete_exhausted_rebase_cleanup(dispatch_state, fresh)
    return {
        "status": "exhausted_sign_in_rebased",
        "archive": str(archive),
        "artifact_count": len(artifacts),
        "repository_fingerprint": fingerprint,
    }


def exhausted_rebase_required(record: dict[str, Any]) -> bool:
    """Select only the initial exhausted transition or interrupted cleanup."""
    authorization = record.get("owner_authorized_fresh_sign_in_sequence") or {}
    return bool(
        record.get("bounded_recovery_exhausted") is True
        or (
            record.get("routing_revision") == ROUTING_REVISION
            and authorization.get("exhausted_fingerprint")
            == EXHAUSTED_SIGN_IN_FINGERPRINT
            and authorization.get("transition_status") == "cleanup_pending"
        )
    )


def cleaned_fresh_sequence_resume_required(
    dispatch_state: Path, record: dict[str, Any]
) -> bool:
    """Select the crash window after exhausted cleanup and before first enable."""
    authorization = record.get("owner_authorized_fresh_sign_in_sequence") or {}
    attempt_path = dispatch_state / "attempts/V1-019.json"
    attempt_valid = not attempt_path.exists()
    if attempt_path.exists():
        try:
            attempt = read_json_object(attempt_path, "interrupted fresh V1-019 attempt")
        except RestorationError:
            attempt = {}
        pending = attempt.get("pending") or {}
        counters = attempt.get("counters") or {}
        attempt_valid = bool(
            isinstance(pending, dict)
            and pending.get("stage") == "implementation"
            and isinstance(attempt.get("fingerprint"), str)
            and len(str(attempt.get("fingerprint"))) == 64
            and int(counters.get("implementation") or 0) == 0
        )
    return bool(
        record.get("candidate") == "V1-019"
        and record.get("routing_revision") == ROUTING_REVISION
        and record.get("stage") == "implementation"
        and record.get("completed_implementation_substages") == []
        and record.get("expected_worktree_paths") == []
        and record.get("ceiling_recovery_attempts") == {}
        and record.get("context_materialization_attempts") == {}
        and record.get("recovery_generation") == 1
        and record.get("recovery_pending") is True
        and record.get("bounded_recovery_exhausted") is False
        and authorization.get("consumed") is True
        and authorization.get("eligible_sequences") == 1
        and authorization.get("exhausted_fingerprint")
        == EXHAUSTED_SIGN_IN_FINGERPRINT
        and authorization.get("transition_status") == "complete"
        and attempt_valid
        and not (dispatch_state / "last-failure.json").exists()
    )


def resume_cleaned_fresh_sequence(
    repo: Path,
    dispatch_state: Path,
    record: dict[str, Any],
    *,
    candidate_base_commit: str,
) -> dict[str, Any]:
    """Validate and resume the sole authorized fresh sequence after a crash."""
    fingerprint = repository_fingerprint(repo)
    attempt_path = dispatch_state / "attempts/V1-019.json"
    interrupted_attempt = attempt_path.exists()
    current_paths = changed_paths(repo)
    partial_paths_valid = bool(
        interrupted_attempt
        and all(path in SIGN_IN_WRITABLE_PATHS for path in current_paths)
    )
    if (
        not cleaned_fresh_sequence_resume_required(dispatch_state, record)
        or record.get("candidate_base_commit") != candidate_base_commit
        or (
            record.get("repository_fingerprint") != fingerprint
            and not partial_paths_valid
        )
    ):
        raise RestorationError(
            "the cleaned Owner-authorized V1-019 fresh sequence drifted before enable"
        )
    if interrupted_attempt:
        if not partial_paths_valid:
            raise RestorationError(
                "the interrupted fresh sign-in attempt changed a path outside its exact scope"
            )
        record.update(
            {
                "expected_worktree_paths": current_paths,
                "repository_fingerprint": fingerprint,
                "preserved_partial_work": {
                    "paths": current_paths,
                    "repository_fingerprint": fingerprint,
                    "recovery_generation": int(record.get("recovery_generation") or 0),
                    "authorization": "post_exit_exact_sign_in_scope",
                },
                "updated_at": utc_now(),
            }
        )
        atomic_write_json(dispatch_state / "candidates/V1-019.json", record)
    else:
        _complete_exhausted_rebase_cleanup(dispatch_state, record)
    return {
        "status": (
            "interrupted_fresh_sequence_resumed"
            if interrupted_attempt
            else "cleaned_fresh_sequence_resumed"
        ),
        "archive": (record.get("owner_authorized_fresh_sign_in_sequence") or {}).get(
            "archive"
        ),
        "repository_fingerprint": fingerprint,
    }


def _complete_exhausted_rebase_cleanup(
    dispatch_state: Path, record: dict[str, Any]
) -> None:
    """Idempotently finish the post-candidate cleanup of an exhausted rebase."""
    pairs = _validate_exhausted_rebase_cleanup(dispatch_state, record)
    for live, _ in pairs:
        if live.exists() or live.is_symlink():
            live.unlink()
    current_path = dispatch_state / "candidates/V1-019.json"
    current = read_json_object(current_path, "fresh V1-019 candidate record")
    current_authorization = current.get("owner_authorized_fresh_sign_in_sequence") or {}
    if current_authorization.get("transition_status") != "complete":
        current_authorization["transition_status"] = "complete"
        current_authorization["cleanup_completed_at"] = utc_now()
        current["owner_authorized_fresh_sign_in_sequence"] = current_authorization
        current["updated_at"] = utc_now()
        atomic_write_json(current_path, current)


def _validate_exhausted_rebase_cleanup(
    dispatch_state: Path, record: dict[str, Any]
) -> tuple[tuple[Path, Path], ...]:
    """Validate an interrupted cleanup without mutating its remaining live evidence."""
    dispatch_state = dispatch_state.resolve()
    authorization = record.get("owner_authorized_fresh_sign_in_sequence") or {}
    archive = Path(str(authorization.get("archive") or "")).resolve()
    expected_root = (dispatch_state / "superseded/v1-019-sign-in-context-v3").resolve()
    try:
        archive.relative_to(expected_root)
    except ValueError as error:
        raise RestorationError(
            "the exhausted sign-in archive path escaped its boundary"
        ) from error
    pairs: tuple[tuple[Path, Path], ...] = (
        (dispatch_state / "attempts/V1-019.json", archive / "attempt.json"),
        (dispatch_state / "last-failure.json", archive / "last-failure.json"),
        (
            dispatch_state
            / "terminal/repair_exhausted"
            / f"{EXHAUSTED_SIGN_IN_FINGERPRINT}.json",
            archive / "repair-exhausted.json",
        ),
    )
    for live, archived in pairs:
        try:
            archived_metadata = archived.lstat()
            archived.resolve(strict=True).relative_to(archive)
        except (OSError, ValueError) as error:
            raise RestorationError(
                "the exhausted sign-in transition archive is incomplete"
            ) from error
        if archived.is_symlink() or not stat.S_ISREG(archived_metadata.st_mode):
            raise RestorationError(
                "the exhausted sign-in transition archive is incomplete"
            )
        archived_value = read_json_object(archived, "archived exhausted sign-in evidence")
        if live.exists() or live.is_symlink():
            try:
                live_metadata = live.lstat()
                live.resolve(strict=True).relative_to(dispatch_state)
            except (OSError, ValueError) as error:
                raise RestorationError(
                    "live exhausted sign-in evidence differs from its archive"
                ) from error
            if live.is_symlink() or not stat.S_ISREG(live_metadata.st_mode):
                raise RestorationError(
                    "live exhausted sign-in evidence differs from its archive"
                )
            live_value = read_json_object(live, "live exhausted sign-in evidence")
            if live_value != archived_value:
                raise RestorationError(
                    "live exhausted sign-in evidence differs from its archive"
                )
    return pairs


def interrupted_exhausted_cleanup_install_required(
    prior: dict[str, Any] | None, dispatch_state: Path
) -> bool:
    """Recognize only the exact formatting-mismatch cleanup crash for one safe retry."""
    if not (
        isinstance(prior, dict)
        and prior.get("status") == "failed_closed"
        and prior.get("failure")
        == "live exhausted sign-in evidence differs from its archive"
        and prior.get("recovery_state") == "terminal_failure"
        and prior.get("owner_action_required") is False
    ):
        return False
    try:
        record = read_json_object(
            dispatch_state / "candidates/V1-019.json",
            "interrupted exhausted V1-019 cleanup candidate",
        )
        authorization = record.get("owner_authorized_fresh_sign_in_sequence") or {}
        exact = bool(
            record.get("candidate") == "V1-019"
            and record.get("routing_revision") == ROUTING_REVISION
            and record.get("stage") == "implementation"
            and record.get("completed_implementation_substages") == []
            and record.get("expected_worktree_paths") == []
            and record.get("recovery_pending") is True
            and record.get("bounded_recovery_exhausted") is False
            and authorization.get("consumed") is True
            and authorization.get("eligible_sequences") == 1
            and authorization.get("exhausted_fingerprint")
            == EXHAUSTED_SIGN_IN_FINGERPRINT
            and authorization.get("transition_status") == "cleanup_pending"
        )
        if not exact:
            return False
        _validate_exhausted_rebase_cleanup(dispatch_state, record)
    except RestorationError:
        return False
    return True


def rebase_scheduled_v1_019_recovery(
    repo: Path, dispatch_state: Path, *, candidate_base_commit: str
) -> dict[str, Any]:
    """Rebind only the proven pending sign-in recovery to the repair commit."""
    candidate_path = dispatch_state / "candidates/V1-019.json"
    attempt_path = dispatch_state / "attempts/V1-019.json"
    failure_path = dispatch_state / "last-failure.json"
    record = read_json_object(candidate_path, "V1-019 candidate recovery record")
    attempt = read_json_object(attempt_path, "V1-019 attempt record")
    failure = read_json_object(failure_path, "V1-019 current failure")
    fingerprint = repository_fingerprint(repo)
    usage = record.get("model_usage") or []
    latest_usage = usage[-1] if isinstance(usage, list) and usage else {}
    recoveries = record.get("ceiling_recovery_attempts") or {}
    materializations = record.get("context_materialization_attempts") or {}
    if record.get("routing_revision") == ROUTING_REVISION:
        recovery_attempt = int(recoveries.get("sign_in") or 0)
        materialization_attempt = int(materializations.get("sign_in") or 0)
        marker_status = str(record.get("pending_recovery_marker_status") or "")
        owner_reset = record.get("owner_authorized_fresh_sign_in_sequence") or {}
        initial_generation = 1 if owner_reset.get("consumed") is True else 0
        expected_generation = (
            initial_generation + recovery_attempt + materialization_attempt
        )
        expected_attempt = (
            materialization_attempt
            if marker_status == "context_materialization_pending"
            else recovery_attempt
        )
        expected_paths = record.get("expected_worktree_paths")
        exact_partial_paths = bool(
            isinstance(expected_paths, list)
            and len(expected_paths) == len(set(expected_paths))
            and all(
                isinstance(path, str) and path in SIGN_IN_WRITABLE_PATHS
                for path in expected_paths
            )
            and sorted(expected_paths) == changed_paths(repo)
        )
        if (
            record.get("candidate") != "V1-019"
            or record.get("candidate_base_commit") != candidate_base_commit
            or record.get("repository_fingerprint") != fingerprint
            or record.get("stage") != "implementation"
            or not exact_partial_paths
            or record.get("completed_implementation_substages") != []
            or record.get("recovery_pending") is not True
            or int(record.get("recovery_generation") or 0) != expected_generation
            or marker_status
            not in {"routing_recovery_pending", "context_materialization_pending"}
            or not 1 <= expected_attempt <= 2
            or record.get("bounded_recovery_exhausted") is True
            or failure.get("category")
            not in {
                "model_session_or_token_ceiling",
                "pre_model_infrastructure_failure",
                "unsupported_invocation_configuration",
                "lock_or_overlapping_process_failure",
                "context_materialization_required",
            }
            or failure.get("owner_action_required") is not False
            or not 1
            <= int((attempt.get("counters") or {}).get("implementation") or 0)
            <= 3
            or attempt.get("pending") is not None
        ):
            raise RestorationError(
                "the already-rebased V1-019 sign-in recovery boundary drifted"
            )
        validate_pending_sign_in_marker(
            dispatch_state,
            record,
            expected_attempt=expected_attempt,
            expected_status=marker_status,
        )
        return {"status": "already_rebased", "archive": None}
    if (
        record.get("candidate") != "V1-019"
        or record.get("routing_revision") != PRIOR_ROUTING_REVISION
        or record.get("candidate_base_commit") != INCIDENT_BASELINE
        or record.get("stage") != "implementation"
        or record.get("completed_implementation_substages") != []
        or record.get("expected_worktree_paths") != []
        or record.get("recovery_pending") is not True
        or record.get("recovery_generation") != 1
        or recoveries != {"sign_in": 1}
        or record.get("bounded_recovery_exhausted") is True
        or latest_usage.get("session_id") != CONTEXT_INCIDENT_SESSION_ID
        or latest_usage.get("api_calls_started") != CONTEXT_INCIDENT_API_CALLS
        or latest_usage.get("api_calls_completed") != CONTEXT_INCIDENT_API_CALLS
        or latest_usage.get("input_token_usage") != CONTEXT_INCIDENT_INPUT_TOKENS
        or latest_usage.get("output_token_usage") != CONTEXT_INCIDENT_OUTPUT_TOKENS
        or latest_usage.get("total_token_usage") != CONTEXT_INCIDENT_COUNTED_TOKENS
        or latest_usage.get("cache_read_token_usage")
        != CONTEXT_INCIDENT_CACHE_READ_TOKENS
        or latest_usage.get("predicted_next_context_tokens")
        != CONTEXT_INCIDENT_FALSE_PREDICTION
        or latest_usage.get("in_flight_overshoot_tokens") != 0
        or latest_usage.get("unsupported_provider_parameters_removed") != []
        or failure.get("category") != "model_session_or_token_ceiling"
        or failure.get("owner_action_required") is not False
        or ((attempt.get("counters") or {}).get("implementation")) != 1
        or attempt.get("pending") is not None
    ):
        raise RestorationError(
            "the pending V1-019 sign-in recovery no longer matches the exact context incident"
        )
    validate_pending_sign_in_marker(dispatch_state, record, expected_attempt=1)

    archive = dispatch_state / "superseded/v1-019-context-reservation"
    archive.mkdir(parents=True, exist_ok=True)
    archive_key = f"{int(time.time() * 1000)}-{candidate_base_commit[:12]}"
    archived = archive / f"candidate-{archive_key}.json"
    atomic_write_json(archived, record)
    record.update(
        {
            "routing_revision": ROUTING_REVISION,
            "candidate_base_commit": candidate_base_commit,
            "initial_repository_fingerprint": fingerprint,
            "repository_fingerprint": fingerprint,
            "updated_at": utc_now(),
            "pending_recovery_marker_status": "routing_recovery_pending",
        }
    )
    record.setdefault("events", []).append(
        {
            "stage": "automation_context_restoration_repair",
            "result": "pending_sign_in_recovery_rebased",
            "routing_revision": ROUTING_REVISION,
            "repository_commit": candidate_base_commit,
            "repository_fingerprint": fingerprint,
            "recovery_generation": 1,
            "recovery_attempt": 1,
            "owner_action_required": False,
        }
    )
    atomic_write_json(candidate_path, record)
    return {
        "status": "pending_sign_in_recovery_rebased",
        "archive": str(archived),
        "repository_fingerprint": fingerprint,
    }


def restoration_boundary_path(dispatch_state: Path) -> Path:
    return dispatch_state / "restoration/active-v1-019-boundary.json"


def persist_restoration_boundary(
    dispatch_state: Path, *, candidate_base_commit: str, sequence_floor: int
) -> Path:
    path = restoration_boundary_path(dispatch_state)
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "status": "active",
            "candidate": "V1-019",
            "bounded_substage": "sign_in",
            "routing_revision": ROUTING_REVISION,
            "candidate_base_commit": candidate_base_commit,
            "sequence_floor": sequence_floor,
            "created_at": utc_now(),
        },
    )
    return path


def archive_restoration_boundary(dispatch_state: Path, *, status: str) -> str | None:
    path = restoration_boundary_path(dispatch_state)
    if not path.exists():
        return None
    boundary = read_json_object(path, "active restoration boundary")
    boundary["status"] = status
    boundary["resolved_at"] = utc_now()
    target = (
        dispatch_state
        / "restoration/boundaries"
        / f"{status}-{int(time.time() * 1000)}.json"
    )
    atomic_write_json(target, boundary)
    path.unlink()
    return str(target)


def v1_019_dispatch_progress(
    dispatch_state: Path, *, candidate_base_commit: str
) -> dict[str, Any]:
    """Prove the natural run advanced the fresh bounded V1-019 lifecycle."""
    path = dispatch_state / "candidates/V1-019.json"
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RestorationError(
            "the natural run left no readable V1-019 dispatcher record"
        ) from error
    if not isinstance(record, dict):
        raise RestorationError("the natural run left a non-object V1-019 record")
    completed = record.get("completed_implementation_substages") or []
    allowed = ["sign_in", "mfa_recovery", "sessions", "account_capability"]
    if (
        record.get("candidate") != "V1-019"
        or record.get("routing_revision") != ROUTING_REVISION
        or record.get("candidate_base_commit") != candidate_base_commit
        or not isinstance(completed, list)
        or completed != allowed[: len(completed)]
    ):
        raise RestorationError("the natural run drifted from the bounded V1-019 record")
    stage = str(record.get("stage") or "")
    progressed = bool(completed and completed[0] == "sign_in")
    if not progressed:
        raise RestorationError(
            "the natural run returned success without dispatching a bounded V1-019 substage"
        )
    return {
        "stage": stage,
        "completed_implementation_substages": completed,
        "repository_fingerprint": record.get("repository_fingerprint"),
        "recovery_generation": int(record.get("recovery_generation") or 0),
        "recovery_pending": record.get("recovery_pending") is True,
    }


def current_failure_boundary(dispatch_state: Path) -> dict[str, Any]:
    """Return only current dispatcher evidence that can legitimately require an Owner."""
    try:
        failure = json.loads((dispatch_state / "last-failure.json").read_text())
    except (OSError, json.JSONDecodeError):
        failure = {}
    try:
        record = json.loads((dispatch_state / "candidates/V1-019.json").read_text())
    except (OSError, json.JSONDecodeError):
        record = {}
    if not isinstance(failure, dict):
        failure = {}
    if not isinstance(record, dict):
        record = {}
    owner_required = bool(
        failure.get("owner_action_required") is True
        or record.get("bounded_recovery_exhausted") is True
    )
    return {
        "owner_action_required": owner_required,
        "category": failure.get("category"),
        "exact_next_action": failure.get("exact_next_action"),
        "recovery_pending_in_record": record.get("recovery_pending") is True,
    }


def job_state(job: dict[str, Any]) -> tuple[int | None, str | None, int, bool]:
    state = job.get("state") or {}
    last_run = state.get("lastRunAtMs")
    status = state.get("lastRunStatus") or state.get("lastStatus")
    errors = state.get("consecutiveErrors")
    running = state.get("runningAtMs") is not None
    return (
        last_run if isinstance(last_run, int) else None,
        str(status) if status is not None else None,
        errors if isinstance(errors, int) else 0,
        running,
    )


def supervisor_runs_after(database: Path, sequence: int) -> list[dict[str, Any]]:
    """Return completed supervisor runs strictly after one durable sequence."""
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                """
                SELECT seq, status, run_at_ms, duration_ms
                FROM cron_run_logs
                WHERE job_id = ? AND seq > ?
                ORDER BY seq ASC
                """,
                (SUPERVISOR_ID, sequence),
            ).fetchall()
    except sqlite3.Error as error:
        raise RestorationError(
            "supervisor run-sequence evidence is unavailable"
        ) from error
    return [
        {
            "sequence": int(row[0]),
            "status": str(row[1]) if row[1] is not None else None,
            "run_at_ms": int(row[2]) if row[2] is not None else None,
            "duration_ms": int(row[3]) if row[3] is not None else None,
        }
        for row in rows
    ]


def latest_supervisor_sequence(database: Path) -> int:
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT MAX(seq) FROM cron_run_logs WHERE job_id = ?",
                (SUPERVISOR_ID,),
            ).fetchone()
    except sqlite3.Error as error:
        raise RestorationError(
            "supervisor run-sequence baseline is unavailable"
        ) from error
    if row is None or not isinstance(row[0], int):
        raise RestorationError("supervisor run-sequence baseline is missing")
    return int(row[0])


def eligible_bounded_recovery(dispatch_state: Path) -> dict[str, Any]:
    """Prove a recoverable V1-019 sign-in retry remains dispatchable."""
    boundary = current_failure_boundary(dispatch_state)
    record = read_json_object(
        dispatch_state / "candidates/V1-019.json", "V1-019 recovery record"
    )
    completed = record.get("completed_implementation_substages") or []
    recoveries = record.get("ceiling_recovery_attempts") or {}
    materializations = record.get("context_materialization_attempts") or {}
    category = boundary.get("category")
    owner_reset = record.get("owner_authorized_fresh_sign_in_sequence") or {}
    zero_attempt_category = category in {
        None,
        "pre_model_infrastructure_failure",
        "unsupported_invocation_configuration",
        "lock_or_overlapping_process_failure",
    }
    owner_fresh_sequence = bool(
        owner_reset.get("consumed") is True
        and owner_reset.get("eligible_sequences") == 1
        and owner_reset.get("exhausted_fingerprint") == EXHAUSTED_SIGN_IN_FINGERPRINT
        and owner_reset.get("transition_status") == "complete"
        and zero_attempt_category
        and boundary.get("owner_action_required") is False
        and int(recoveries.get("sign_in") or 0) == 0
        and int(materializations.get("sign_in") or 0) == 0
    )
    eligible = bool(
        (
            owner_fresh_sequence
            or (
                category
                in {
                    "model_session_or_token_ceiling",
                    "context_materialization_required",
                    "pre_model_infrastructure_failure",
                    "unsupported_invocation_configuration",
                    "lock_or_overlapping_process_failure",
                }
                and boundary.get("owner_action_required") is False
            )
        )
        and boundary.get("recovery_pending_in_record") is True
        and record.get("bounded_recovery_exhausted") is not True
        and record.get("stage") == "implementation"
        and completed == []
        and int(record.get("recovery_generation") or 0) >= 1
        and (
            owner_fresh_sequence
            or 1 <= int(recoveries.get("sign_in") or 0) <= 2
            or 1 <= int(materializations.get("sign_in") or 0) <= 2
        )
    )
    return {
        "eligible": eligible,
        "category": category,
        "recovery_generation": int(record.get("recovery_generation") or 0),
        "sign_in_recovery_attempts": int(recoveries.get("sign_in") or 0),
        "sign_in_context_materializations": int(materializations.get("sign_in") or 0),
        "owner_authorized_fresh_sequence": owner_fresh_sequence,
        "owner_action_required": boundary.get("owner_action_required") is True,
        "exact_next_action": boundary.get("exact_next_action"),
    }


def wait_for_zero_overlap(
    repo: Path, owner_pid: int, timeout: float, poll: float
) -> None:
    deadline = time.monotonic() + timeout
    consecutive_clear = 0
    while time.monotonic() < deadline:
        owner_alive = pid_exists(owner_pid)
        overlaps = relevant_processes(repo)
        if not owner_alive and not overlaps:
            consecutive_clear += 1
            if consecutive_clear >= 2:
                return
        else:
            consecutive_clear = 0
        time.sleep(poll)
    raise RestorationError("repository-worker overlap did not clear before timeout")


def telegram_route(database: Path, source_job_id: str) -> tuple[str, str, str | None]:
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                """SELECT name, enabled, delivery_channel, delivery_to,
                          delivery_account_id
                     FROM cron_jobs WHERE job_id = ?""",
                (source_job_id,),
            ).fetchall()
    except (OSError, sqlite3.Error) as error:
        raise RestorationError(
            "Telegram notification route could not be read"
        ) from error
    if len(rows) != 1:
        raise RestorationError("Telegram notification source job is not unique")
    name, enabled, channel, target, account = rows[0]
    if (
        name != "property-rental-visibility-watchdog"
        or enabled != 1
        or channel != "telegram"
        or not isinstance(target, str)
        or not target
        or (account is not None and not isinstance(account, str))
    ):
        raise RestorationError("Telegram notification source job is not usable")
    return channel, target, account or None


def terminal_message(evidence: dict[str, Any]) -> str:
    if evidence.get("status") == "recovery_scheduled":
        recovery = evidence.get("bounded_recovery") or {}
        return (
            "RECOVERY_SCHEDULED — Property Rental supervisor remains enabled for "
            "the exact bounded V1-019 sign_in retry. "
            f"Post-repair run sequence: {evidence.get('last_observed_sequence')}; "
            f"recovery generation: {recovery.get('recovery_generation')}; "
            "Owner action required: no."
        )
    if evidence.get("status") == "complete":
        progress = evidence.get("bounded_retry_progress") or {}
        completed = progress.get("completed_implementation_substages") or []
        substage = (
            completed[-1] if isinstance(completed, list) and completed else "verified"
        )
        return (
            "RESTORATION_COMPLETE — Property Rental supervisor restoration succeeded. "
            "Scheduler enabled: true; zero overlap was confirmed; naturally scheduled "
            f"bounded V1-019 progress: {substage}; Owner action required: no."
        )
    return (
        "RESTORATION_FAILED_CLOSED — Property Rental supervisor restoration stopped. "
        "Scheduler enabled: false; exact diagnostics are preserved in local restoration "
        "evidence; Owner action required: "
        f"{str(bool(evidence.get('owner_action_required'))).lower()}."
    )


def notify_terminal_once(args: argparse.Namespace, evidence_path: Path) -> None:
    lock_path = evidence_path.with_name(f".{evidence_path.name}.notification.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        evidence = read_json_object(evidence_path, "terminal restoration evidence")
        prior = evidence.get("notification") or {}
        if isinstance(prior, dict) and prior.get("attempted") is True:
            return
        attempted_at = utc_now()
        evidence["notification"] = {
            "attempted": True,
            "attempted_at": attempted_at,
            "delivery_status": "attempting",
            "source_job_id": args.notification_source_job_id,
        }
        atomic_write_json(evidence_path, evidence)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    completion: dict[str, Any]
    try:
        openclaw = exact_executable(args.openclaw, "OpenClaw")
        channel, target, account = telegram_route(
            Path(args.openclaw_db).resolve(), args.notification_source_job_id
        )
        command = [
            openclaw,
            "message",
            "send",
            "--channel",
            channel,
            "--target",
            target,
            "--message",
            terminal_message(evidence),
            "--json",
        ]
        if account is not None:
            command.extend(["--account", account])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.notification_timeout,
        )
        completion = {
            "completed_at": utc_now(),
            "exit_status": result.returncode,
        }
        if result.returncode == 0:
            completion["delivery_status"] = "delivered"
        else:
            completion["delivery_status"] = "failed"
            completion["failure"] = "OpenClaw Telegram message command failed"
    except subprocess.TimeoutExpired:
        completion = {
            "completed_at": utc_now(),
            "delivery_status": "failed",
            "failure": "OpenClaw Telegram message command timed out",
            "timeout_seconds": args.notification_timeout,
        }
    except Exception:
        completion = {
            "completed_at": utc_now(),
            "delivery_status": "failed",
            "failure": "Telegram notification route or executable was unavailable",
        }
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        latest = read_json_object(evidence_path, "terminal restoration evidence")
        notification = latest.get("notification") or {}
        if notification.get("attempted_at") == attempted_at:
            notification.update(completion)
            latest["notification"] = notification
            atomic_write_json(evidence_path, latest)


def notify_recovery_scheduled_once(
    args: argparse.Namespace, evidence_path: Path, *, sequence: int
) -> None:
    """Send one nonterminal notification for one exact scheduled recovery."""
    lock_path = evidence_path.with_name(f".{evidence_path.name}.notification.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        evidence = read_json_object(evidence_path, "recovery-scheduled evidence")
        notifications = evidence.get("recovery_notifications") or []
        if any(item.get("sequence") == sequence for item in notifications):
            return
        attempted_at = utc_now()
        entry = {
            "sequence": sequence,
            "attempted": True,
            "attempted_at": attempted_at,
            "delivery_status": "attempting",
            "source_job_id": args.notification_source_job_id,
        }
        evidence["recovery_notifications"] = [*notifications, entry]
        atomic_write_json(evidence_path, evidence)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    completion: dict[str, Any]
    try:
        openclaw = exact_executable(args.openclaw, "OpenClaw")
        channel, target, account = telegram_route(
            Path(args.openclaw_db).resolve(), args.notification_source_job_id
        )
        command = [
            openclaw,
            "message",
            "send",
            "--channel",
            channel,
            "--target",
            target,
            "--message",
            terminal_message(evidence),
            "--json",
        ]
        if account is not None:
            command.extend(["--account", account])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.notification_timeout,
        )
        completion = {
            "completed_at": utc_now(),
            "exit_status": result.returncode,
            "delivery_status": "delivered" if result.returncode == 0 else "failed",
        }
        if result.returncode:
            completion["failure"] = "OpenClaw Telegram message command failed"
    except subprocess.TimeoutExpired:
        completion = {
            "completed_at": utc_now(),
            "delivery_status": "failed",
            "failure": "OpenClaw Telegram message command timed out",
            "timeout_seconds": args.notification_timeout,
        }
    except Exception:
        completion = {
            "completed_at": utc_now(),
            "delivery_status": "failed",
            "failure": "Telegram notification route or executable was unavailable",
        }
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        latest = read_json_object(evidence_path, "recovery-scheduled evidence")
        notifications = latest.get("recovery_notifications") or []
        for item in notifications:
            if (
                item.get("sequence") == sequence
                and item.get("attempted_at") == attempted_at
            ):
                item.update(completion)
        latest["recovery_notifications"] = notifications
        atomic_write_json(evidence_path, latest)


def disable_supervisor(args: argparse.Namespace, repo: Path) -> str | None:
    try:
        openclaw = exact_executable(args.openclaw, "OpenClaw")
        disabled = cron(openclaw, repo, "disable")
        exact_supervisor(disabled, repo)
        if disabled.get("enabled") is not False:
            return "disable command did not leave the supervisor disabled"
    except Exception as error:
        return str(error)
    return None


def attempt_terminal_unload(
    args: argparse.Namespace, evidence_path: Path
) -> str | None:
    unload_failure: str | None = None
    try:
        unload_restoration_job(args.launchctl, args.expected_repair_head)
    except Exception as error:
        unload_failure = str(error)
    terminal = read_json_object(evidence_path, "terminal restoration evidence")
    terminal["unload_attempted_at"] = utc_now()
    if unload_failure is None:
        terminal["unload_status"] = "unloaded"
        terminal.pop("unload_failure", None)
    else:
        terminal["unload_failure"] = unload_failure
        terminal["unload_status"] = "failed"
    atomic_write_json(evidence_path, terminal)
    return unload_failure


def finalize_terminal_direct(
    args: argparse.Namespace, evidence_path: Path, *, unload_terminalizer: bool
) -> bool:
    """Finalize from a process that is not the continuation being unloaded."""
    lock_path = evidence_path.with_name(f".{evidence_path.name}.finalize.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        terminal = read_json_object(evidence_path, "terminal restoration evidence")
        unload_failure = attempt_terminal_unload(args, evidence_path)
        if unload_failure is not None and terminal.get("status") == "complete":
            terminal = read_json_object(evidence_path, "terminal restoration evidence")
            terminal["restoration_result_before_terminal_failure"] = "complete"
            terminal["enabled_before_terminal_failure"] = terminal.get("enabled")
            terminal["status"] = "failed_closed"
            terminal["enabled"] = False
            terminal["failure"] = unload_failure
            terminal["failure_phase"] = "terminal_self_unload"
            terminal["disable_failure"] = disable_supervisor(
                args, Path(args.repo).resolve()
            )
            terminal["owner_action_required"] = False
            terminal["exact_next_action"] = (
                "Repair the exact continuation self-unload failure before another "
                "restoration attempt."
            )
            atomic_write_json(evidence_path, terminal)
        try:
            notify_terminal_once(args, evidence_path)
        finally:
            if unload_terminalizer:
                terminal = read_json_object(
                    evidence_path, "terminal restoration evidence"
                )
                terminal["terminalizer"] = {
                    **(terminal.get("terminalizer") or {}),
                    "self_unload_requested_at": utc_now(),
                }
                atomic_write_json(evidence_path, terminal)
                try:
                    unload_launchd_label(
                        args.launchctl, terminalizer_label(args.expected_repair_head)
                    )
                except Exception as error:
                    terminal = read_json_object(
                        evidence_path, "terminal restoration evidence"
                    )
                    terminal["terminalizer"]["self_unload_failure"] = str(error)
                    atomic_write_json(evidence_path, terminal)
        return (
            read_json_object(evidence_path, "terminal restoration evidence").get(
                "status"
            )
            == "complete"
        )


def terminalizer_command(args: argparse.Namespace, evidence_path: Path) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "finalize",
        "--repo",
        str(Path(args.repo).resolve()),
        "--dispatch-state",
        str(Path(args.dispatch_state).resolve()),
        "--evidence",
        str(evidence_path),
        "--openclaw",
        args.openclaw,
        "--launchctl",
        args.launchctl,
        "--github",
        args.github,
        "--openclaw-db",
        str(Path(args.openclaw_db).resolve()),
        "--notification-source-job-id",
        args.notification_source_job_id,
        "--notification-timeout",
        str(args.notification_timeout),
        "--terminalizer-handoff-timeout",
        str(args.terminalizer_handoff_timeout),
        "--expected-repair-head",
        args.expected_repair_head,
    ]


def finalize_terminal(args: argparse.Namespace, evidence_path: Path) -> bool:
    """Hand terminal work to a separate launchd job before self-bootout."""
    label = terminalizer_label(args.expected_repair_head)
    terminal = read_json_object(evidence_path, "terminal restoration evidence")
    terminal["terminalizer"] = {
        "handoff_requested_at": utc_now(),
        "label": label,
        "submit_status": "submitting",
    }
    atomic_write_json(evidence_path, terminal)
    result = subprocess.run(
        [
            args.launchctl,
            "submit",
            "-l",
            label,
            "--",
            *terminalizer_command(args, evidence_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        deadline = time.monotonic() + args.terminalizer_handoff_timeout
        while time.monotonic() < deadline:
            observed = read_json_object(evidence_path, "terminal restoration evidence")
            notification = observed.get("notification") or {}
            terminalizer = observed.get("terminalizer") or {}
            if (
                observed.get("unload_status") in {"unloaded", "failed"}
                and notification.get("delivery_status") in {"delivered", "failed"}
                and terminalizer.get("self_unload_requested_at")
            ):
                return observed.get("status") == "complete"
            time.sleep(min(args.poll, 0.25))

        terminal = read_json_object(evidence_path, "terminal restoration evidence")
        terminalizer = terminal.get("terminalizer") or {}
        terminalizer["handoff_timeout_at"] = utc_now()
        terminalizer["handoff_timeout_seconds"] = args.terminalizer_handoff_timeout
        terminal["terminalizer"] = terminalizer
        if terminal.get("status") == "complete":
            terminal["restoration_result_before_terminal_failure"] = "complete"
            terminal["enabled_before_terminal_failure"] = terminal.get("enabled")
            terminal["status"] = "failed_closed"
            terminal["enabled"] = False
            terminal["failure"] = "terminalizer handoff timed out"
            terminal["failure_phase"] = "terminalizer_handoff"
            terminal["disable_failure"] = disable_supervisor(
                args, Path(args.repo).resolve()
            )
            terminal["owner_action_required"] = False
        atomic_write_json(evidence_path, terminal)
        try:
            notify_terminal_once(args, evidence_path)
        finally:
            attempt_terminal_unload(args, evidence_path)
        return False

    stdout, stdout_redacted = redact_sensitive_output(result.stdout)
    stderr, stderr_redacted = redact_sensitive_output(result.stderr)
    terminal = read_json_object(evidence_path, "terminal restoration evidence")
    terminal["terminalizer"] = {
        **(terminal.get("terminalizer") or {}),
        "submit_status": "failed",
        "exit_status": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "redactions_applied": stdout_redacted or stderr_redacted,
    }
    if terminal.get("status") == "complete":
        terminal["restoration_result_before_terminal_failure"] = "complete"
        terminal["enabled_before_terminal_failure"] = terminal.get("enabled")
        terminal["status"] = "failed_closed"
        terminal["enabled"] = False
        terminal["failure"] = (
            f"terminalizer launchctl submit failed with exit {result.returncode}"
        )
        terminal["failure_phase"] = "terminalizer_handoff"
        terminal["disable_failure"] = disable_supervisor(
            args, Path(args.repo).resolve()
        )
        terminal["owner_action_required"] = False
    atomic_write_json(evidence_path, terminal)
    try:
        notify_terminal_once(args, evidence_path)
    finally:
        attempt_terminal_unload(args, evidence_path)
    return False


def reconcile_false_ci_failure(
    args: argparse.Namespace, repo: Path, evidence_path: Path
) -> None:
    if (
        args.expected_repair_head != REPAIR_PUBLICATION_COMMIT
        or args.expected_metadata_commit != FALSE_FAILURE_METADATA_COMMIT
        or args.expected_metadata_run_id != FALSE_FAILURE_RUN_ID
    ):
        raise RestorationError("false-failure reconciliation identity is not exact")
    continuation_head = args.expected_continuation_head
    if not continuation_head:
        raise RestorationError("installation omitted the exact continuation commit")
    if (
        git(repo, "rev-parse", "HEAD") != continuation_head
        or git(repo, "rev-parse", "@{upstream}") != continuation_head
    ):
        raise RestorationError(
            "continuation repair is not synchronized at its exact commit"
        )

    prior = read_json_object(evidence_path, "prior restoration evidence")
    if (
        prior.get("status") == "reconciled_false_ci_failure"
        and prior.get("metadata_commit") == FALSE_FAILURE_METADATA_COMMIT
        and prior.get("run_id") == FALSE_FAILURE_RUN_ID
    ):
        return
    if (
        prior.get("status") != "failed_closed"
        or prior.get("expected_repair_head") != args.expected_repair_head
        or prior.get("failure")
        != f"restoration metadata CI failed for {FALSE_FAILURE_METADATA_COMMIT}"
        or prior.get("notification") is not None
    ):
        raise RestorationError(
            "prior restoration evidence is not the exact unnotified false failure"
        )

    ci_path = Path(args.ci_evidence).resolve()
    metadata_commit = restoration_metadata(
        repo,
        args.expected_repair_head,
        expected_continuation_head=continuation_head,
        github=exact_executable(args.github, "GitHub CLI"),
        ci_evidence=ci_path,
    )
    ci = successful_ci_evidence(
        ci_path,
        commit=FALSE_FAILURE_METADATA_COMMIT,
        expected_run_id=FALSE_FAILURE_RUN_ID,
    )
    if metadata_commit != FALSE_FAILURE_METADATA_COMMIT:
        raise RestorationError(
            "reconciliation resolved the wrong restoration metadata commit"
        )

    history = evidence_path.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    archived = history / (
        f"false-failure-{FALSE_FAILURE_METADATA_COMMIT[:12]}-run-{FALSE_FAILURE_RUN_ID}.json"
    )
    if not archived.exists():
        atomic_write_json(archived, prior)
    atomic_write_json(
        evidence_path,
        {
            "status": "reconciled_false_ci_failure",
            "timestamp": utc_now(),
            "expected_repair_head": args.expected_repair_head,
            "expected_continuation_head": continuation_head,
            "metadata_commit": metadata_commit,
            "run_id": ci["run_id"],
            "url": ci["url"],
            "github_status": ci["workflow_status"],
            "conclusion": ci["conclusion"],
            "ci_evidence": str(ci_path),
            "prior_evidence": str(archived),
            "notification": None,
            "owner_action_required": False,
            "scheduler_enabled": False,
        },
    )


def execute(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    dispatch_state = Path(args.dispatch_state).resolve()
    evidence_path = Path(args.evidence).resolve()
    ci_evidence_path = (
        Path(args.ci_evidence).resolve()
        if args.ci_evidence
        else evidence_path.with_name(f"ci-{FALSE_FAILURE_METADATA_COMMIT[:12]}.json")
    )
    prior: dict[str, Any] | None = None
    try:
        value = json.loads(evidence_path.read_text())
        prior = value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        prior = None
    if (
        prior
        and prior.get("status") in TERMINAL_RESTORATION_STATUSES
        and prior.get("expected_repair_head") == args.expected_repair_head
    ):
        reentry_errors: list[str] = []
        if prior.get("status") == "failed_closed":
            try:
                terminal_job = cron(args.openclaw, repo, "get")
                exact_supervisor(terminal_job, repo)
                if terminal_job.get("enabled") is not False:
                    terminal_job = cron(args.openclaw, repo, "disable")
                    exact_supervisor(terminal_job, repo)
                    if terminal_job.get("enabled") is not False:
                        raise RestorationError(
                            "terminal restoration evidence could not keep the supervisor disabled"
                        )
            except Exception as error:
                reentry_errors.append(str(error))
        finalized = finalize_terminal(args, evidence_path)
        if reentry_errors:
            terminal = read_json_object(evidence_path, "terminal restoration evidence")
            terminal["terminal_reentry_errors"] = reentry_errors
            terminal["terminal_reentry_at"] = utc_now()
            atomic_write_json(evidence_path, terminal)
        return (
            0
            if prior.get("status") == "complete" and finalized and not reentry_errors
            else 69
        )
    atomic_write_json(
        evidence_path,
        {
            "status": "pending_post_exit",
            "started_at": utc_now(),
            "expected_repair_head": args.expected_repair_head,
            "restoration_label": restoration_label(args.expected_repair_head),
            "owner_pid": args.owner_pid,
            "superseded_evidence": (
                {
                    "status": prior.get("status"),
                    "timestamp": prior.get("timestamp"),
                    "metadata_commit": prior.get("metadata_commit"),
                    "run_id": prior.get("run_id"),
                    "ci_evidence": prior.get("ci_evidence"),
                    "prior_evidence": prior.get("prior_evidence"),
                }
                if prior
                else None
            ),
            "recovery_notifications": (
                prior.get("recovery_notifications", []) if prior else []
            ),
        },
    )
    enabled = False
    sequence_floor: int | None = None
    processed_sequence: int | None = None
    post_repair_runs: list[dict[str, Any]] = []
    try:
        github = exact_executable(args.github, "GitHub CLI")
        pre_metadata_head = args.expected_continuation_head or git(
            repo, "rev-parse", "HEAD"
        )
        initial = cron(args.openclaw, repo, "get")
        exact_supervisor(initial, repo)
        if initial.get("enabled") is not False:
            initial = cron(args.openclaw, repo, "disable")
            exact_supervisor(initial, repo)
            if initial.get("enabled") is not False:
                raise RestorationError(
                    "a resumed continuation could not fail-close the enabled supervisor"
                )
        wait_for_zero_overlap(repo, args.owner_pid, args.overlap_timeout, args.poll)
        v1_019_integrity(repo, dispatch_state, expected_head=pre_metadata_head)
        metadata_commit = restoration_metadata(
            repo,
            args.expected_repair_head,
            expected_continuation_head=args.expected_continuation_head,
            github=github,
            ci_evidence=ci_evidence_path,
        )
        continuation_head = metadata_commit
        current_candidate = read_json_object(
            dispatch_state / "candidates/V1-019.json", "V1-019 candidate record"
        )
        if current_candidate.get("routing_revision") not in {
            PRIOR_ROUTING_REVISION,
            EXHAUSTED_ROUTING_REVISION,
            ROUTING_REVISION,
        }:
            raise RestorationError(
                "post-exit restoration permits only the exact pending V1-019 sign-in recovery"
            )
        if exhausted_rebase_required(current_candidate):
            supersession = rebase_exhausted_v1_019_sign_in(
                repo, dispatch_state, candidate_base_commit=continuation_head
            )
        elif cleaned_fresh_sequence_resume_required(dispatch_state, current_candidate):
            supersession = resume_cleaned_fresh_sequence(
                repo,
                dispatch_state,
                current_candidate,
                candidate_base_commit=continuation_head,
            )
        else:
            supersession = rebase_scheduled_v1_019_recovery(
                repo, dispatch_state, candidate_base_commit=continuation_head
            )
        recovery_before_enable = eligible_bounded_recovery(dispatch_state)
        if not recovery_before_enable["eligible"]:
            raise RestorationError(
                "the exact V1-019 sign-in recovery became ineligible before enable"
            )
        wait_for_zero_overlap(repo, args.owner_pid, args.overlap_timeout, args.poll)
        v1_019_integrity(repo, dispatch_state, expected_head=continuation_head)
        before_enable = cron(args.openclaw, repo, "get")
        exact_supervisor(before_enable, repo)
        if before_enable.get("enabled") is not False:
            raise RestorationError(
                "the supervisor changed state before the exact enable operation"
            )
        sequence_floor = latest_supervisor_sequence(Path(args.openclaw_db).resolve())
        boundary_path = persist_restoration_boundary(
            dispatch_state,
            candidate_base_commit=continuation_head,
            sequence_floor=sequence_floor,
        )
        enabled_job = cron(args.openclaw, repo, "enable")
        exact_supervisor(enabled_job, repo)
        if enabled_job.get("enabled") is not True:
            raise RestorationError("the exact supervisor did not become enabled")
        enabled = True
        processed_sequence = sequence_floor
        post_repair_runs = []
        deadline = time.monotonic() + args.natural_run_timeout
        while time.monotonic() < deadline:
            observed = cron(args.openclaw, repo, "get")
            exact_supervisor(observed, repo)
            if observed.get("enabled") is not True:
                raise RestorationError(
                    "the supervisor became disabled during the scheduled bounded recovery"
                )
            _, _, inherited_errors, running = job_state(observed)
            if running:
                time.sleep(args.poll)
                continue
            runs = supervisor_runs_after(
                Path(args.openclaw_db).resolve(), processed_sequence
            )
            if not runs:
                time.sleep(args.poll)
                continue
            for run_evidence in runs:
                processed_sequence = int(run_evidence["sequence"])
                run_evidence["aggregate_consecutive_errors"] = inherited_errors
                post_repair_runs.append(run_evidence)
                if run_evidence.get("status") == "ok":
                    try:
                        progress = v1_019_dispatch_progress(
                            dispatch_state, candidate_base_commit=continuation_head
                        )
                    except RestorationError:
                        recovery = eligible_bounded_recovery(dispatch_state)
                        if recovery["eligible"]:
                            continue
                        raise
                    integrity = v1_019_integrity(
                        repo, dispatch_state, expected_head=None
                    )
                    boundary_archive = archive_restoration_boundary(
                        dispatch_state, status="progress_verified"
                    )
                    current_evidence = read_json_object(
                        evidence_path, "post-exit restoration evidence"
                    )
                    atomic_write_json(
                        evidence_path,
                        {
                            "status": "complete",
                            "timestamp": utc_now(),
                            "expected_repair_head": args.expected_repair_head,
                            "restoration_label": restoration_label(
                                args.expected_repair_head
                            ),
                            "supervisor_id": SUPERVISOR_ID,
                            "enabled": True,
                            "metadata_commit": metadata_commit,
                            "continuation_commit": continuation_head,
                            "restoration_metadata_ci_evidence": str(ci_evidence_path),
                            "post_repair_sequence_floor": sequence_floor,
                            "verified_progress_sequence": processed_sequence,
                            "post_repair_runs": post_repair_runs,
                            "inherited_consecutive_errors_ignored": inherited_errors,
                            "candidate": "V1-019",
                            "repository_branch": integrity["branch"],
                            "repository_head": integrity["head"],
                            "repository_paths": integrity["paths"],
                            "v1_020_started": False,
                            "incident_supersession": supersession,
                            "bounded_retry_progress": progress,
                            "restoration_boundary": boundary_archive,
                            "recovery_notifications": current_evidence.get(
                                "recovery_notifications", []
                            ),
                        },
                    )
                    return 0 if finalize_terminal(args, evidence_path) else 69

                recovery = eligible_bounded_recovery(dispatch_state)
                if not recovery["eligible"]:
                    raise RestorationError(
                        "post-repair supervisor sequence failed without an eligible bounded recovery"
                    )
                v1_019_integrity(repo, dispatch_state, expected_head=None)
                current_evidence = read_json_object(
                    evidence_path, "post-exit restoration evidence"
                )
                atomic_write_json(
                    evidence_path,
                    {
                        **current_evidence,
                        "status": "recovery_scheduled",
                        "timestamp": utc_now(),
                        "expected_repair_head": args.expected_repair_head,
                        "restoration_label": restoration_label(
                            args.expected_repair_head
                        ),
                        "supervisor_id": SUPERVISOR_ID,
                        "enabled": True,
                        "post_repair_sequence_floor": sequence_floor,
                        "last_observed_sequence": processed_sequence,
                        "post_repair_runs": post_repair_runs,
                        "inherited_consecutive_errors_ignored": inherited_errors,
                        "bounded_recovery": recovery,
                        "restoration_boundary": str(boundary_path),
                        "owner_action_required": False,
                        "exact_next_action": recovery["exact_next_action"],
                    },
                )
                notify_recovery_scheduled_once(
                    args, evidence_path, sequence=processed_sequence
                )
            time.sleep(args.poll)
        raise RestorationError(
            "no naturally scheduled successful run completed before timeout"
        )
    except Exception as error:
        failure_boundary = current_failure_boundary(dispatch_state)
        disable_error: str | None = None
        try:
            disabled = cron(args.openclaw, repo, "disable")
            exact_supervisor(disabled, repo)
            if disabled.get("enabled") is not False:
                disable_error = "disable command did not leave the supervisor disabled"
        except Exception as disable_failure:
            disable_error = str(disable_failure)
        boundary_archive = archive_restoration_boundary(
            dispatch_state, status="failed_closed"
        )
        try:
            current_evidence = read_json_object(
                evidence_path, "post-exit restoration evidence"
            )
        except RestorationError:
            current_evidence = {}
        atomic_write_json(
            evidence_path,
            {
                "status": "failed_closed",
                "timestamp": utc_now(),
                "expected_repair_head": args.expected_repair_head,
                "restoration_label": restoration_label(args.expected_repair_head),
                "supervisor_id": SUPERVISOR_ID,
                "enabled_before_failure": enabled,
                "failure": str(error),
                "disable_failure": disable_error,
                "owner_action_required": failure_boundary["owner_action_required"],
                "dispatcher_failure_category": failure_boundary["category"],
                "recovery_state": "terminal_failure",
                "post_repair_sequence_floor": sequence_floor,
                "last_observed_sequence": processed_sequence,
                "post_repair_runs": post_repair_runs,
                "restoration_boundary": boundary_archive,
                "recovery_notifications": current_evidence.get(
                    "recovery_notifications", []
                ),
                "exact_next_action": failure_boundary["exact_next_action"]
                or (
                    "Repair the deterministic continuation failure before another "
                    "restoration attempt."
                ),
            },
        )
        finalize_terminal(args, evidence_path)
        print(f"post-exit restoration failed closed: {error}", file=sys.stderr)
        return 69


def install(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    evidence_path = Path(args.evidence).resolve()
    installation_phase = "argument_validation"
    submit_diagnostics: dict[str, Any] | None = None
    prior: dict[str, Any] | None = None
    try:
        prior = read_json_object(evidence_path, "prior restoration evidence")
    except RestorationError:
        prior = None
    if not args.ci_evidence:
        args.ci_evidence = str(
            evidence_path.with_name(f"ci-{args.expected_repair_head[:12]}.json")
        )
    try:
        args.github = exact_executable(args.github, "GitHub CLI")
        args.openclaw = exact_executable(args.openclaw, "OpenClaw")
        args.launchctl = exact_executable(args.launchctl, "launchctl")
        telegram_route(
            Path(args.openclaw_db).resolve(), args.notification_source_job_id
        )
        installation_phase = "disabled_supervisor_validation"
        existing = cron(args.openclaw, repo, "get")
        exact_supervisor(existing, repo)
        if existing.get("enabled") is not False:
            raise RestorationError(
                "the supervisor must remain disabled during installation"
            )
        installation_phase = "pending_recovery_validation"
        exact_exhausted_install = bool(
            prior is not None
            and prior.get("status") == "failed_closed"
            and prior.get("dispatcher_failure_category")
            == "model_session_or_token_ceiling"
            and prior.get("recovery_state") == "terminal_failure"
            and prior.get("owner_action_required") is True
        )
        interrupted_cleanup_install = interrupted_exhausted_cleanup_install_required(
            prior, Path(args.dispatch_state).resolve()
        )
        if exact_exhausted_install:
            validate_exhausted_v1_019_sign_in(Path(args.dispatch_state).resolve())
        elif interrupted_cleanup_install:
            pass
        elif (
            prior is None
            or prior.get("status") != "failed_closed"
            or prior.get("dispatcher_failure_category")
            != "model_session_or_token_ceiling"
            or prior.get("recovery_state")
            != "scheduled_in_record_but_not_running_due_fail_closed_disable"
            or prior.get("owner_action_required") is not False
        ):
            raise RestorationError(
                "prior restoration evidence is not the exact pending-recovery incident"
            )
        continuation_head = args.expected_continuation_head or args.expected_repair_head
        if (
            continuation_head != args.expected_repair_head
            or git(repo, "rev-parse", "HEAD") != continuation_head
            or git(repo, "rev-parse", "@{upstream}") != continuation_head
        ):
            raise RestorationError(
                "the published context/restoration repair is not exactly synchronized"
            )

        installation_phase = "launchctl_submit"
        label = restoration_label(args.expected_repair_head)
        command = [
            args.launchctl,
            "submit",
            "-l",
            label,
            "--",
            sys.executable,
            str(Path(__file__).resolve()),
            "run",
            "--repo",
            str(Path(args.repo).resolve()),
            "--dispatch-state",
            str(Path(args.dispatch_state).resolve()),
            "--evidence",
            str(evidence_path),
            "--ci-evidence",
            str(Path(args.ci_evidence).resolve()),
            "--openclaw",
            args.openclaw,
            "--launchctl",
            args.launchctl,
            "--github",
            args.github,
            "--openclaw-db",
            str(Path(args.openclaw_db).resolve()),
            "--notification-source-job-id",
            args.notification_source_job_id,
            "--notification-timeout",
            str(args.notification_timeout),
            "--terminalizer-handoff-timeout",
            str(args.terminalizer_handoff_timeout),
            "--owner-pid",
            str(args.owner_pid),
            "--expected-repair-head",
            args.expected_repair_head,
            "--expected-continuation-head",
            continuation_head,
            "--expected-metadata-commit",
            args.expected_metadata_commit,
            "--expected-metadata-run-id",
            str(args.expected_metadata_run_id),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        stdout, stdout_redacted = redact_sensitive_output(result.stdout)
        stderr, stderr_redacted = redact_sensitive_output(result.stderr)
        submit_diagnostics = {
            "exit_status": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "redactions_applied": stdout_redacted or stderr_redacted,
        }
        if result.returncode:
            raise RestorationError(
                f"launchctl submit failed with exit {result.returncode}"
            )
        return 0
    except Exception as error:
        archived: Path | None = None
        if prior is not None:
            history = evidence_path.parent / "history"
            history.mkdir(parents=True, exist_ok=True)
            archived = history / (
                f"pre-install-failure-{args.expected_repair_head[:12]}.json"
            )
            if not archived.exists():
                atomic_write_json(archived, prior)
        disable_failure = disable_supervisor(args, repo)
        atomic_write_json(
            evidence_path,
            {
                "status": "failed_closed",
                "timestamp": utc_now(),
                "failure_phase": installation_phase,
                "failure": str(error),
                "expected_repair_head": args.expected_repair_head,
                "expected_continuation_head": args.expected_continuation_head,
                "restoration_label": restoration_label(args.expected_repair_head),
                "supervisor_id": SUPERVISOR_ID,
                "scheduler_enabled": False,
                "disable_failure": disable_failure,
                "launchctl_submit": submit_diagnostics,
                "prior_evidence": str(archived) if archived is not None else None,
                "owner_action_required": False,
                "exact_next_action": (
                    "Repair the deterministic continuation installation failure before "
                    "another restoration attempt."
                ),
            },
        )
        finalize_terminal_direct(args, evidence_path, unload_terminalizer=False)
        print(
            f"post-exit restoration installation failed closed: {error}",
            file=sys.stderr,
        )
        return 69


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    dispatch = Path.home() / ".openclaw/state/property-rental-supervisor-dispatch-v2"
    openclaw_state = Path.home() / ".openclaw/state"
    argument_parser = argparse.ArgumentParser()
    subparsers = argument_parser.add_subparsers(dest="command", required=True)
    for name in ("run", "install", "finalize"):
        child = subparsers.add_parser(name)
        child.add_argument("--repo", default=str(root))
        child.add_argument("--dispatch-state", default=str(dispatch))
        child.add_argument(
            "--evidence", default=str(dispatch / "restoration/current.json")
        )
        child.add_argument(
            "--ci-evidence",
        )
        child.add_argument(
            "--openclaw", default=str(Path.home() / ".openclaw/bin/openclaw")
        )
        child.add_argument("--launchctl", default="/bin/launchctl")
        child.add_argument("--github", required=True)
        child.add_argument(
            "--openclaw-db", default=str(openclaw_state / "openclaw.sqlite")
        )
        child.add_argument(
            "--notification-source-job-id", default=NOTIFICATION_SOURCE_JOB_ID
        )
        child.add_argument(
            "--notification-timeout",
            type=float,
            default=DEFAULT_NOTIFICATION_TIMEOUT,
        )
        child.add_argument(
            "--terminalizer-handoff-timeout",
            type=float,
            default=DEFAULT_TERMINALIZER_HANDOFF_TIMEOUT,
        )
        child.add_argument("--owner-pid", type=int, default=os.getppid())
        child.add_argument("--expected-repair-head", required=True)
        child.add_argument("--expected-continuation-head")
        child.add_argument(
            "--expected-metadata-commit", default=FALSE_FAILURE_METADATA_COMMIT
        )
        child.add_argument(
            "--expected-metadata-run-id", type=int, default=FALSE_FAILURE_RUN_ID
        )
        child.add_argument("--poll", type=float, default=15.0)
        child.add_argument("--overlap-timeout", type=float, default=6 * 60 * 60)
        child.add_argument("--natural-run-timeout", type=float, default=4 * 60 * 60)
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    if args.command == "install":
        return install(args)
    if args.command == "finalize":
        return (
            0
            if finalize_terminal_direct(
                args, Path(args.evidence).resolve(), unload_terminalizer=True
            )
            else 69
        )
    return execute(args)


if __name__ == "__main__":
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise SystemExit(main())
