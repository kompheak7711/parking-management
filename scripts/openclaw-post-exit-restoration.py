#!/usr/bin/env python3
"""Fail-closed restoration of the one existing Property Rental supervisor."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from openclaw_automation import (
    atomic_write_json,
    changed_paths,
    relevant_processes,
    repository_fingerprint,
    utc_now,
)

SUPERVISOR_ID = "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb"
SUPERVISOR_NAME = "property-rental-24x7-supervisor"
EXPECTED_INTERVAL_MS = 1_800_000
ROUTING_REVISION = "v1-019-invocation-contract-repair-v2"
INCIDENT_BASELINE = "d877cf3b6648083f97e54d661933e3d188999dae"
FAILED_ROUTING_FINGERPRINT = (
    "ab2d0cb1c2d3de9e287d595effddd4e4f9de5bdafc361deea003cbde10dcfdc2"
)
FAILED_SESSION_ID = "6baf17e6e77d7582e72b2e19a40ab806"
TERMINAL_RESTORATION_STATUSES = {"complete", "failed_closed"}


class RestorationError(RuntimeError):
    """A fail-closed restoration condition."""


def run(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(arguments),
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
    )


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
        raise RestorationError(f"openclaw cron {action} failed with exit {result.returncode}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RestorationError(f"openclaw cron {action} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RestorationError(f"openclaw cron {action} returned a non-object")
    return value


def restoration_label(expected_repair_head: str) -> str:
    return f"com.property-rental.post-exit-restoration.{expected_repair_head[:12]}"


def unload_restoration_job(launchctl: str, expected_repair_head: str) -> None:
    """Unload only this exact submitted one-shot job.

    ``launchctl submit`` jobs have inferred keepalive behavior.  Terminal
    evidence is written before this function is called so a delayed signal
    cannot erase the fail-closed result.
    """
    label = restoration_label(expected_repair_head)
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
            "the existing supervisor identity or schedule contract drifted: " + ", ".join(failed)
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
        raise RestorationError("compact state no longer identifies V1-019 on its authorized branch")
    if candidate.get("roadmap_id") == "V1-020" or candidate.get("id") == "V1-020":
        raise RestorationError("V1-020 was selected contrary to the restoration boundary")
    if head != upstream:
        raise RestorationError("local HEAD is not synchronized with its upstream")
    if expected_head is not None and head != expected_head:
        raise RestorationError("repair publication HEAD changed before restoration metadata")
    paths = changed_paths(repo)
    if paths:
        record_path = dispatch_state / "candidates/V1-019.json"
        try:
            record = json.loads(record_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise RestorationError("dirty V1-019 work has no readable dispatcher record") from error
        if (
            record.get("candidate") != "V1-019"
            or sorted(record.get("expected_worktree_paths") or []) != paths
            or record.get("repository_fingerprint") != repository_fingerprint(repo)
        ):
            raise RestorationError("dirty V1-019 work is not bound to exact dispatcher evidence")
    return {"branch": branch, "head": head, "paths": paths, "state": state}


def restoration_metadata(repo: Path, expected_repair_head: str) -> str:
    state_path = repo / "ops/STATE.json"
    now_path = repo / "ops/NOW.md"
    state = json.loads(state_path.read_text())
    repair = state.setdefault("automation_repair", {})
    if repair.get("status") == "restored":
        restoration = repair.get("post_exit_restoration") or {}
        head = git(repo, "rev-parse", "HEAD")
        parent = git(repo, "rev-parse", "HEAD^")
        committed_paths = sorted(
            line
            for line in git(
                repo,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "HEAD",
            ).splitlines()
            if line
        )
        if (
            restoration.get("status") != "metadata_published_waiting_enable"
            or restoration.get("repair_publication_commit") != expected_repair_head
            or parent != expected_repair_head
            or head != git(repo, "rev-parse", "@{upstream}")
            or committed_paths != ["ops/NOW.md", "ops/STATE.json"]
        ):
            raise RestorationError(
                "published restoration metadata does not match its exact resumable contract"
            )
        return head
    if repair.get("status") != "published_awaiting_post_exit_restoration":
        raise RestorationError("automation repair is not awaiting post-exit restoration")
    if git(repo, "rev-parse", "HEAD") != expected_repair_head:
        raise RestorationError("repair publication HEAD changed before restoration metadata")
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
        raise RestorationError("restoration metadata changed unexpected repository paths")
    run(repo, "git", "add", "--", "ops/NOW.md", "ops/STATE.json")
    run(repo, "git", "diff", "--cached", "--check")
    run(repo, "git", "commit", "-m", "ops: authorize post-exit supervisor restoration")
    commit = git(repo, "rev-parse", "HEAD")
    run(repo, "git", "push")
    ci = run(repo, str(repo / "scripts/openclaw-wait-for-ci.sh"), commit, check=False)
    if ci.returncode:
        raise RestorationError(f"restoration metadata CI failed for {commit}")
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
        raise RestorationError("the stale V1-019 candidate record is invalid JSON") from error
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
    failed_usage = current_usage[-1] if isinstance(current_usage, list) and current_usage else {}
    if current is not None and (
        current.get("stage") != "implementation"
        or current.get("routing_revision") != "v1-019-code69-repair-v1"
        or current.get("candidate_base_commit") != INCIDENT_BASELINE
        or current.get("implementation_complete") is True
        or current.get("expected_worktree_paths") not in (None, [])
        or current.get("completed_implementation_substages") not in (None, [])
        or failed_usage.get("session_id") != FAILED_SESSION_ID
        or failed_usage.get("stage_result")
        != "unsupported_invocation_configuration"
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
        raise RestorationError("the stale V1-019 attempt evidence is invalid JSON") from error
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
        raise RestorationError("the stale last-failure evidence is invalid JSON") from error
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
        marker_evidence.get("actionable_fingerprint")
        != FAILED_ROUTING_FINGERPRINT
        or marker_evidence.get("category")
        != "unsupported_invocation_configuration"
    ):
        raise RestorationError("the exact failed routing marker changed before supersession")

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
    progressed = bool(completed) or stage != "implementation"
    if not progressed:
        raise RestorationError(
            "the natural run returned success without dispatching a bounded V1-019 substage"
        )
    return {
        "stage": stage,
        "completed_implementation_substages": completed,
        "repository_fingerprint": record.get("repository_fingerprint"),
        "recovery_generation": int(record.get("recovery_generation") or 0),
    }


def current_failure_boundary(dispatch_state: Path) -> dict[str, Any]:
    """Return only current dispatcher evidence that can legitimately require an Owner."""
    try:
        failure = json.loads((dispatch_state / "last-failure.json").read_text())
    except (OSError, json.JSONDecodeError):
        failure = {}
    try:
        record = json.loads(
            (dispatch_state / "candidates/V1-019.json").read_text()
        )
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


def wait_for_zero_overlap(repo: Path, owner_pid: int, timeout: float, poll: float) -> None:
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


def execute(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    dispatch_state = Path(args.dispatch_state).resolve()
    evidence_path = Path(args.evidence).resolve()
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
        try:
            unload_restoration_job(args.launchctl, args.expected_repair_head)
        except Exception as error:
            reentry_errors.append(str(error))
        if reentry_errors:
            prior["terminal_reentry_errors"] = reentry_errors
            prior["terminal_reentry_at"] = utc_now()
            atomic_write_json(evidence_path, prior)
        return 0 if prior.get("status") == "complete" and not reentry_errors else 69
    atomic_write_json(
        evidence_path,
        {
            "status": "pending_post_exit",
            "started_at": utc_now(),
            "expected_repair_head": args.expected_repair_head,
            "restoration_label": restoration_label(args.expected_repair_head),
            "owner_pid": args.owner_pid,
            "superseded_evidence": (
                {"status": prior.get("status"), "timestamp": prior.get("timestamp")}
                if prior
                else None
            ),
        },
    )
    enabled = False
    try:
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
        v1_019_integrity(repo, dispatch_state, expected_head=None)
        metadata_commit = restoration_metadata(repo, args.expected_repair_head)
        supersession = supersede_v1_019_incident(
            repo, dispatch_state, candidate_base_commit=metadata_commit
        )
        wait_for_zero_overlap(repo, args.owner_pid, args.overlap_timeout, args.poll)
        v1_019_integrity(repo, dispatch_state, expected_head=metadata_commit)
        before_enable = cron(args.openclaw, repo, "get")
        exact_supervisor(before_enable, repo)
        if before_enable.get("enabled") is not False:
            raise RestorationError("the supervisor changed state before the exact enable operation")
        prior_run, _, _, _ = job_state(before_enable)
        enabled_job = cron(args.openclaw, repo, "enable")
        exact_supervisor(enabled_job, repo)
        if enabled_job.get("enabled") is not True:
            raise RestorationError("the exact supervisor did not become enabled")
        enabled = True
        enabled_at_ms = int(time.time() * 1000)
        deadline = time.monotonic() + args.natural_run_timeout
        while time.monotonic() < deadline:
            observed = cron(args.openclaw, repo, "get")
            exact_supervisor(observed, repo)
            last_run, status, errors, running = job_state(observed)
            if (
                last_run is not None
                and last_run >= enabled_at_ms
                and (prior_run is None or last_run > prior_run)
                and not running
            ):
                if status != "ok" or errors != 0:
                    raise RestorationError("the naturally scheduled supervisor run failed")
                progress = v1_019_dispatch_progress(
                    dispatch_state, candidate_base_commit=metadata_commit
                )
                integrity = v1_019_integrity(repo, dispatch_state, expected_head=None)
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
                        "natural_run_at_ms": last_run,
                        "natural_run_status": status,
                        "consecutive_errors": errors,
                        "candidate": "V1-019",
                        "repository_branch": integrity["branch"],
                        "repository_head": integrity["head"],
                        "repository_paths": integrity["paths"],
                        "v1_020_started": False,
                        "incident_supersession": supersession,
                        "bounded_retry_progress": progress,
                    },
                )
                unload_restoration_job(args.launchctl, args.expected_repair_head)
                return 0
            time.sleep(args.poll)
        raise RestorationError("no naturally scheduled successful run completed before timeout")
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
        atomic_write_json(
            evidence_path,
            {
                "status": "failed_closed",
                "timestamp": utc_now(),
                "expected_repair_head": args.expected_repair_head,
                "restoration_label": restoration_label(
                    args.expected_repair_head
                ),
                "supervisor_id": SUPERVISOR_ID,
                "enabled_before_failure": enabled,
                "failure": str(error),
                "disable_failure": disable_error,
                "owner_action_required": failure_boundary["owner_action_required"],
                "dispatcher_failure_category": failure_boundary["category"],
                "recovery_state": (
                    "scheduled_in_record_but_not_running_due_fail_closed_disable"
                    if failure_boundary["recovery_pending_in_record"]
                    else "not_running"
                ),
                "exact_next_action": failure_boundary["exact_next_action"]
                or (
                    "Repair the deterministic continuation failure before another "
                    "restoration attempt."
                ),
            },
        )
        unload_failure: str | None = None
        try:
            unload_restoration_job(args.launchctl, args.expected_repair_head)
        except Exception as unload_error:
            unload_failure = str(unload_error)
        if unload_failure is not None:
            terminal = json.loads(evidence_path.read_text())
            terminal["unload_failure"] = unload_failure
            atomic_write_json(evidence_path, terminal)
        print(f"post-exit restoration failed closed: {error}", file=sys.stderr)
        return 69


def install(args: argparse.Namespace) -> int:
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
        str(Path(args.evidence).resolve()),
        "--openclaw",
        args.openclaw,
        "--launchctl",
        args.launchctl,
        "--owner-pid",
        str(args.owner_pid),
        "--expected-repair-head",
        args.expected_repair_head,
    ]
    result = subprocess.run(command, check=False)
    return result.returncode


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    dispatch = Path.home() / ".openclaw/state/property-rental-supervisor-dispatch-v2"
    argument_parser = argparse.ArgumentParser()
    subparsers = argument_parser.add_subparsers(dest="command", required=True)
    for name in ("run", "install"):
        child = subparsers.add_parser(name)
        child.add_argument("--repo", default=str(root))
        child.add_argument("--dispatch-state", default=str(dispatch))
        child.add_argument("--evidence", default=str(dispatch / "restoration/current.json"))
        child.add_argument("--openclaw", default=str(Path.home() / ".openclaw/bin/openclaw"))
        child.add_argument("--launchctl", default="launchctl")
        child.add_argument("--owner-pid", type=int, default=os.getppid())
        child.add_argument("--expected-repair-head", required=True)
        child.add_argument("--poll", type=float, default=15.0)
        child.add_argument("--overlap-timeout", type=float, default=6 * 60 * 60)
        child.add_argument("--natural-run-timeout", type=float, default=4 * 60 * 60)
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    if args.command == "install":
        return install(args)
    return execute(args)


if __name__ == "__main__":
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise SystemExit(main())
