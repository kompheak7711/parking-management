#!/usr/bin/env python3
"""Wait for one exact GitHub Actions run without relying on interactive PATH."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY = "kompheak7711/property-rental-management"
BRANCH = "implementation/foundation"
DEFAULT_WORKFLOW_ID = "334806147"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def redact_credentials(value: str) -> tuple[str, bool]:
    redacted = value
    for name, secret in os.environ.items():
        upper = name.upper()
        if (
            isinstance(secret, str)
            and len(secret) >= 8
            and any(
                marker in upper for marker in ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTH")
            )
        ):
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted, redacted != value


def command_record(result: subprocess.CompletedProcess[str], endpoint: str) -> dict[str, Any]:
    stdout, stdout_redacted = redact_credentials(result.stdout)
    stderr, stderr_redacted = redact_credentials(result.stderr)
    return {
        "endpoint": endpoint,
        "exit_status": result.returncode,
        "redactions_applied": stdout_redacted or stderr_redacted,
        "stderr": stderr,
        "stdout": stdout,
        "timestamp": timestamp(),
    }


def github_request(
    executable: str, endpoint: str, *fields: tuple[str, str]
) -> subprocess.CompletedProcess[str]:
    command = [executable, "api", "-X", "GET", endpoint]
    for key, value in fields:
        command.extend(["-f", f"{key}={value}"])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def parse_object(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if result.returncode != 0:
        raise ValueError(f"GitHub command exited {result.returncode}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("GitHub command returned a non-object")
    return value


def select_run(
    payload: dict[str, Any], sha: str, expected_run_id: int | None
) -> dict[str, Any] | None:
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("workflow-runs response omitted workflow_runs")
    matches = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == sha
        and (expected_run_id is None or run.get("id") == expected_run_id)
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda run: (str(run.get("created_at") or ""), int(run.get("id") or 0)),
        reverse=True,
    )
    return matches[0]


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("workflow run omitted a valid integer id")
    status = run.get("status")
    if not isinstance(status, str) or not status:
        raise ValueError("workflow run omitted status")
    conclusion = run.get("conclusion")
    if conclusion is not None and not isinstance(conclusion, str):
        raise ValueError("workflow run conclusion is invalid")
    url = run.get("html_url")
    if not isinstance(url, str) or not url:
        raise ValueError("workflow run omitted html_url")
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError("workflow run omitted head_sha")
    return {
        "conclusion": conclusion,
        "head_sha": head_sha,
        "run_id": run_id,
        "workflow_status": status,
        "url": url,
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("sha")
    argument_parser.add_argument(
        "--github", default=os.environ.get("PROPERTY_RENTAL_GITHUB_EXECUTABLE")
    )
    argument_parser.add_argument("--evidence")
    argument_parser.add_argument("--expected-run-id", type=int)
    argument_parser.add_argument(
        "--workflow-id",
        default=os.environ.get("PROPERTY_RENTAL_GITHUB_WORKFLOW_ID", DEFAULT_WORKFLOW_ID),
    )
    argument_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.environ.get("PROPERTY_RENTAL_CI_POLL_SECONDS", "15")),
    )
    argument_parser.add_argument(
        "--max-polls",
        type=int,
        default=int(os.environ.get("PROPERTY_RENTAL_CI_MAX_POLLS", "120")),
    )
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    evidence_path = Path(args.evidence).resolve() if args.evidence else None
    evidence: dict[str, Any] = {
        "branch": BRANCH,
        "commit": args.sha,
        "configured_github_executable": args.github,
        "expected_run_id": args.expected_run_id,
        "max_polls": args.max_polls,
        "poll_seconds": args.poll_seconds,
        "repository": REPOSITORY,
        "schema_version": 1,
        "started_at": timestamp(),
        "status": "starting",
        "workflow_id": str(args.workflow_id),
    }
    atomic_json(evidence_path, evidence)

    executable = args.github or shutil.which("gh")
    if not executable:
        evidence.update(
            {
                "completed_at": timestamp(),
                "diagnostic": "GitHub executable was not configured and gh was not found",
                "status": "github_executable_unavailable",
            }
        )
        atomic_json(evidence_path, evidence)
        print(evidence["diagnostic"], file=sys.stderr)
        return 69
    executable_path = Path(executable)
    if (
        not executable_path.is_absolute()
        or not executable_path.is_file()
        or not os.access(executable_path, os.X_OK)
    ):
        evidence.update(
            {
                "completed_at": timestamp(),
                "diagnostic": f"Configured GitHub executable is unavailable: {executable}",
                "status": "github_executable_unavailable",
            }
        )
        atomic_json(evidence_path, evidence)
        print(evidence["diagnostic"], file=sys.stderr)
        return 69
    executable = str(executable_path.resolve())
    evidence["configured_github_executable"] = executable

    if args.max_polls <= 0 or args.poll_seconds < 0:
        print(
            "CI polling bounds must be non-negative and include at least one poll", file=sys.stderr
        )
        return 64

    list_endpoint = f"repos/{REPOSITORY}/actions/workflows/{args.workflow_id}/runs"
    run_id: int | None = None
    run_url: str | None = None
    polls = 0

    while polls < args.max_polls:
        polls += 1
        if run_id is None:
            result = github_request(
                executable,
                list_endpoint,
                ("branch", BRANCH),
                ("head_sha", args.sha),
                ("per_page", "10"),
            )
            evidence["latest_resolution_command"] = command_record(result, list_endpoint)
            if result.returncode != 0:
                evidence.update(
                    {
                        "diagnostic": f"GitHub run resolution failed with exit {result.returncode}",
                        "polls": polls,
                    }
                )
                break
            try:
                selected = select_run(parse_object(result), args.sha, args.expected_run_id)
                if selected is not None:
                    summary = run_summary(selected)
                    if summary["head_sha"] != args.sha:
                        raise ValueError("resolved workflow run does not match the exact commit")
                    run_id = int(summary["run_id"])
                    run_url = str(summary["url"])
                    evidence.update(summary)
                    evidence["resolved_at"] = timestamp()
                    evidence["status"] = "polling_exact_run"
                    atomic_json(evidence_path, evidence)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                evidence.update(
                    {
                        "diagnostic": f"GitHub run resolution response was invalid: {error}",
                        "polls": polls,
                    }
                )
                break
        else:
            run_endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
            result = github_request(executable, run_endpoint)
            evidence["latest_poll_command"] = command_record(result, run_endpoint)
            if result.returncode != 0:
                evidence.update(
                    {
                        "diagnostic": f"GitHub exact-run poll failed with exit {result.returncode}",
                        "polls": polls,
                    }
                )
                break
            try:
                summary = run_summary(parse_object(result))
                if summary["run_id"] != run_id or summary["head_sha"] != args.sha:
                    raise ValueError("exact-run response changed run or commit identity")
                evidence.update(summary)
                evidence["polls"] = polls
                atomic_json(evidence_path, evidence)
                if summary["workflow_status"] == "completed":
                    if summary["conclusion"] == "success":
                        evidence.update({"completed_at": timestamp(), "status": "success"})
                        atomic_json(evidence_path, evidence)
                        return 0
                    evidence["diagnostic"] = (
                        f"GitHub Actions run {run_id} concluded "
                        f"{summary['conclusion']} for {args.sha}"
                    )
                    break
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                evidence["diagnostic"] = f"GitHub exact-run response was invalid: {error}"
                break
        if polls < args.max_polls:
            time.sleep(args.poll_seconds)

    if run_id is not None:
        final_endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
        final_result = github_request(executable, final_endpoint)
    else:
        final_endpoint = list_endpoint
        final_result = github_request(
            executable,
            final_endpoint,
            ("branch", BRANCH),
            ("head_sha", args.sha),
            ("per_page", "10"),
        )
    evidence["final_authoritative_lookup"] = command_record(final_result, final_endpoint)
    final_summary: dict[str, Any] | None = None
    if final_result.returncode == 0:
        try:
            payload = parse_object(final_result)
            final_run = (
                payload
                if run_id is not None
                else select_run(payload, args.sha, args.expected_run_id)
            )
            if final_run is not None:
                final_summary = run_summary(final_run)
                if final_summary["head_sha"] != args.sha or (
                    run_id is not None and final_summary["run_id"] != run_id
                ):
                    raise ValueError("final lookup changed run or commit identity")
                evidence.update(final_summary)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            evidence["final_lookup_parse_error"] = str(error)

    evidence["completed_at"] = timestamp()
    evidence["polls"] = polls
    if final_summary and final_summary["workflow_status"] == "completed":
        if final_summary["conclusion"] == "success":
            evidence["status"] = "success"
            atomic_json(evidence_path, evidence)
            return 0
        evidence["status"] = "failure"
        evidence.setdefault(
            "diagnostic",
            f"GitHub Actions run {final_summary['run_id']} concluded "
            f"{final_summary['conclusion']} for {args.sha}",
        )
        atomic_json(evidence_path, evidence)
        print(evidence["diagnostic"], file=sys.stderr)
        return 74
    if "diagnostic" in evidence:
        evidence["status"] = "failure"
        atomic_json(evidence_path, evidence)
        print(evidence["diagnostic"], file=sys.stderr)
        return 74
    evidence["status"] = "timeout"
    evidence.setdefault(
        "diagnostic",
        f"Timed out waiting for GitHub Actions for {args.sha}"
        + (f" at exact run {run_id}" if run_id is not None else " before run resolution"),
    )
    if run_id is not None:
        evidence["run_id"] = run_id
        evidence["url"] = run_url
    atomic_json(evidence_path, evidence)
    print(evidence["diagnostic"], file=sys.stderr)
    return 75


if __name__ == "__main__":
    raise SystemExit(main())
