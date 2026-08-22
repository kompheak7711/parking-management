#!/usr/bin/env python3
"""Deterministic regression coverage for autonomous stage routing."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from openclaw_automation import (
    COMPLEX_REVIEW_TOKEN_CEILING,
    EXCEPTIONAL_REVIEW_TOKEN_CEILING,
    FAILURE_CATEGORIES,
    ORDINARY_TOKEN_CEILING,
    RECOVERABLE_ROUTING_FAILURES,
    STAGES,
    UNAVAILABLE,
    V1_019_FRONTEND_CONTEXT_MAX_BYTES,
    V1_020_SUBSTAGE_AUTHORITIES,
    V1_020_SUBSTAGE_IDS,
    V1_020_SUBSTAGE_PATHS,
    AutomationError,
    actionable_fingerprint,
    atomic_write_json,
    changed_paths,
    classify_compact_state,
    complete_small_frontend_evidence,
    consume_attempt,
    consume_continuation,
    digest,
    expand_authorities,
    health_classification,
    hermes_chat_usage,
    model_policy,
    normalize_usage,
    persist_terminal_marker,
    post_restoration_scheduler_ok,
    preservation_evidence,
    preserved_paths_fingerprint,
    publication_candidate_guard,
    release_attempt,
    relevant_processes,
    repeated_call_key,
    repeated_call_result,
    repository_fingerprint,
    reserve_attempt,
    sign_in_backend_contract,
    stage_actionable_fingerprint,
    task_packet,
    usage_record,
    v1_019_routing_identity,
    validate_usage,
)
from openclaw_hermes_guard import (
    GuardError,
    TokenEstimationUnavailable,
    bounded_tool_output,
    enforce_llm_call,
    execute_bounded_tool,
    guard_tool,
    prepare_session_home,
    register_plugin,
    reserve_tool_output_batch,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def dispatcher_ps_probe_script() -> str:
    """Use the real OS parent query while isolating dispatcher command lookup."""
    real_ps = shutil.which("ps")
    if not real_ps:
        raise RuntimeError("system ps is required for process-ancestry tests")
    return (
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  *ppid=*) exec {shlex.quote(real_ps)} "$@" ;;\n'
        "  *) printf '%s\\n' \"$PROPERTY_RENTAL_REPO/scripts/openclaw_dispatch.py\" ;;\n"
        "esac\n"
    )


class AutomationPolicyTests(unittest.TestCase):
    def test_supported_model_configuration_and_stage_separation(self) -> None:
        self.assertEqual(
            STAGES,
            (
                "reconciliation_dispatch",
                "implementation",
                "deterministic_verification",
                "independent_review",
                "publication",
                "post_publication_reconciliation",
                "next_candidate_activation",
            ),
        )
        implementation = model_policy("implementation")
        self.assertEqual(
            (
                implementation.provider,
                implementation.model,
                implementation.requested_reasoning,
            ),
            ("openai-codex", "gpt-5.6-sol", "high"),
        )
        self.assertEqual(implementation.token_ceiling, ORDINARY_TOKEN_CEILING)
        recovery = model_policy("direct_codex_recovery")
        self.assertEqual(recovery.route, "Hermes")
        self.assertEqual(recovery.requested_reasoning, "high")
        self.assertEqual(recovery.token_ceiling, ORDINARY_TOKEN_CEILING)
        review = model_policy(
            "independent_review",
            complex_review=True,
            classification_reason="complete security-sensitive diff",
        )
        self.assertEqual(review.requested_reasoning, "xhigh")
        self.assertEqual(review.token_ceiling, COMPLEX_REVIEW_TOKEN_CEILING)

    def test_review_ceiling_exception_is_bounded_and_preclassified(self) -> None:
        policy = model_policy(
            "independent_review",
            complex_review=True,
            exceptional_review=True,
            classification_reason="preclassified unusually broad cross-stack review",
        )
        self.assertEqual(policy.token_ceiling, EXCEPTIONAL_REVIEW_TOKEN_CEILING)
        with self.assertRaises(AutomationError):
            model_policy("independent_review", exceptional_review=True)
        with self.assertRaises(AutomationError):
            model_policy("independent_review", complex_review=True)

    def test_implementation_cannot_promote_its_ceiling(self) -> None:
        with self.assertRaisesRegex(AutomationError, "cannot promote"):
            model_policy(
                "implementation",
                complex_review=True,
                classification_reason="self promotion",
            )

    def test_unsupported_configuration_is_rejected_before_attempt_accounting(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory) / "attempt.json"
            with self.assertRaises(AutomationError):
                model_policy("publication")
            self.assertFalse(attempt.exists())

    def test_ci_wait_uses_exact_github_path_and_recognizes_delayed_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "calls.json"
            log = root / "endpoints.jsonl"
            fake_github = root / "gh"
            fake_github.write_text(
                """#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ['FAKE_GH_STATE'])
count = json.loads(state.read_text()) if state.exists() else 0
count += 1
state.write_text(json.dumps(count))
endpoint = sys.argv[4]
with pathlib.Path(os.environ['FAKE_GH_LOG']).open('a') as handle:
    handle.write(json.dumps(endpoint) + '\\n')
run = {'id': 12345, 'head_sha': os.environ['FAKE_SHA'], 'html_url': 'https://example.invalid/runs/12345', 'created_at': '2026-08-21T00:00:00Z'}
if endpoint.endswith('/runs'):
    run.update({'status': 'queued', 'conclusion': None})
    print(json.dumps({'workflow_runs': [run]}))
elif count == 2:
    run.update({'status': 'in_progress', 'conclusion': None})
    print(json.dumps(run))
else:
    run.update({'status': 'completed', 'conclusion': 'success'})
    print(json.dumps(run))
"""
            )
            fake_github.chmod(0o755)
            evidence = root / "ci.json"
            sha = "a" * 40
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/openclaw-wait-for-ci.sh"),
                    "--github",
                    str(fake_github),
                    "--evidence",
                    str(evidence),
                    "--expected-run-id",
                    "12345",
                    "--poll-seconds",
                    "0",
                    "--max-polls",
                    "5",
                    sha,
                ],
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_GH_STATE": str(state),
                    "FAKE_GH_LOG": str(log),
                    "FAKE_SHA": sha,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(evidence.read_text())
            self.assertEqual(observed["status"], "success")
            self.assertEqual(observed["workflow_status"], "completed")
            self.assertEqual(observed["run_id"], 12345)
            endpoints = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(sum(endpoint.endswith("/runs") for endpoint in endpoints), 1)
            self.assertTrue(all("12345" in endpoint for endpoint in endpoints[1:]))

    def test_ci_wait_missing_configured_github_fails_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "ci.json"
            started = time.monotonic()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/openclaw-wait-for-ci.sh"),
                    "--github",
                    str(Path(directory) / "missing-gh"),
                    "--evidence",
                    str(evidence),
                    "--poll-seconds",
                    "15",
                    "--max-polls",
                    "120",
                    "b" * 40,
                ],
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
                capture_output=True,
                text=True,
                check=False,
            )
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 69)
            self.assertLess(elapsed, 2)
            self.assertEqual(
                json.loads(evidence.read_text())["status"],
                "github_executable_unavailable",
            )

    def test_ci_wait_preserves_final_authoritative_failure_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "calls.json"
            fake_github = root / "gh"
            fake_github.write_text(
                """#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ['FAKE_GH_STATE'])
count = json.loads(state.read_text()) if state.exists() else 0
count += 1
state.write_text(json.dumps(count))
endpoint = sys.argv[4]
run = {'id': 67890, 'head_sha': os.environ['FAKE_SHA'], 'html_url': 'https://example.invalid/runs/67890', 'created_at': '2026-08-21T00:00:00Z'}
if endpoint.endswith('/runs'):
    run.update({'status': 'queued', 'conclusion': None})
    print(json.dumps({'workflow_runs': [run]}))
else:
    run.update({'status': 'completed', 'conclusion': 'failure'})
    if count >= 3:
        print(os.environ['GH_TOKEN'], file=sys.stderr)
        print('final authoritative stderr', file=sys.stderr)
    print(json.dumps(run))
"""
            )
            fake_github.chmod(0o755)
            evidence = root / "ci.json"
            sha = "c" * 40
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/openclaw-wait-for-ci.sh"),
                    "--github",
                    str(fake_github),
                    "--evidence",
                    str(evidence),
                    "--poll-seconds",
                    "0",
                    "--max-polls",
                    "4",
                    sha,
                ],
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_GH_STATE": str(state),
                    "FAKE_SHA": sha,
                    "GH_TOKEN": "synthetic-secret-token",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 74)
            observed = json.loads(evidence.read_text())
            self.assertEqual(observed["status"], "failure")
            self.assertEqual(observed["run_id"], 67890)
            self.assertEqual(observed["workflow_status"], "completed")
            self.assertEqual(observed["conclusion"], "failure")
            final_lookup = observed["final_authoritative_lookup"]
            self.assertEqual(final_lookup["exit_status"], 0)
            self.assertIn('"id": 67890', final_lookup["stdout"])
            self.assertTrue(final_lookup["stderr"].endswith("final authoritative stderr\n"))
            self.assertTrue(final_lookup["redactions_applied"])
            self.assertNotIn("synthetic-secret-token", evidence.read_text())

    def test_ci_wait_preserves_final_authoritative_timeout_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_github = root / "gh"
            fake_github.write_text(
                """#!/usr/bin/env python3
import json, os, sys
endpoint = sys.argv[4]
run = {'id': 24680, 'head_sha': os.environ['FAKE_SHA'], 'html_url': 'https://example.invalid/runs/24680', 'created_at': '2026-08-21T00:00:00Z', 'status': 'queued', 'conclusion': None}
print(json.dumps({'workflow_runs': [run]}) if endpoint.endswith('/runs') else json.dumps(run))
"""
            )
            fake_github.chmod(0o755)
            evidence = root / "ci.json"
            sha = "e" * 40
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/openclaw-wait-for-ci.sh"),
                    "--github",
                    str(fake_github),
                    "--evidence",
                    str(evidence),
                    "--poll-seconds",
                    "0",
                    "--max-polls",
                    "2",
                    sha,
                ],
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "FAKE_SHA": sha},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 75)
            observed = json.loads(evidence.read_text())
            self.assertEqual(observed["status"], "timeout")
            self.assertEqual(observed["workflow_status"], "queued")
            self.assertEqual(observed["run_id"], 24680)
            self.assertEqual(observed["url"], "https://example.invalid/runs/24680")
            self.assertEqual(observed["final_authoritative_lookup"]["exit_status"], 0)

    def test_effective_usage_reporting_and_unavailable_provider_fields(self) -> None:
        policy = model_policy("implementation")
        report = normalize_usage(
            {
                "model": "gpt-5.6-sol",
                "session_id": "session-1",
                "input_tokens": 10,
                "cache_read_tokens": 4,
                "output_tokens": 6,
                "reasoning_tokens": 3,
            },
            policy,
        )
        self.assertEqual(report["effective_model"], "gpt-5.6-sol")
        self.assertEqual(report["reasoning_effort"], UNAVAILABLE)
        self.assertEqual(report["requested_reasoning_effort"], "high")
        self.assertEqual(report["invocation_route"], "Hermes")
        self.assertEqual(report["session_id"], "session-1")
        self.assertEqual(report["applicable_token_ceiling"], 60_000)

    def test_usage_validation_rejects_silent_model_substitution_and_ceiling(
        self,
    ) -> None:
        policy = model_policy("implementation")
        with self.assertRaisesRegex(AutomationError, "unsupported model"):
            validate_usage(
                {
                    "model": "some-other-model",
                    "total_tokens": 1,
                    "configured_max_tokens": 60_000,
                },
                policy,
            )
        validate_usage(
            {
                "model": "openai-codex/gpt-5.6-sol",
                "total_tokens": 60_000,
                "configured_max_tokens": 60_000,
            },
            policy,
        )
        with self.assertRaisesRegex(AutomationError, "above ceiling"):
            validate_usage(
                {
                    "model": "gpt-5.6-sol",
                    "total_tokens": 60_001,
                    "configured_max_tokens": 60_000,
                },
                policy,
            )
        with self.assertRaisesRegex(AutomationError, "reasoning effort"):
            validate_usage(
                {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "low",
                    "total_tokens": 1,
                    "configured_max_tokens": 60_000,
                },
                policy,
            )
        validate_usage({"model": "gpt-5.6-sol", "configured_max_tokens": 60_000}, policy)
        with self.assertRaisesRegex(AutomationError, "max_turns"):
            validate_usage(
                {
                    "model": "gpt-5.6-sol",
                    "configured_max_tokens": 60_000,
                    "stop_reason": "max_turns",
                },
                policy,
            )
        with self.assertRaises(AutomationError) as mixed_failure:
            validate_usage(
                {
                    "model": "gpt-5.6-sol",
                    "configured_max_tokens": 60_000,
                    "total_tokens": 60_000,
                    "boundary_reached": True,
                    "context_materialization_checkpoint": True,
                    "stop_reason": "context_materialization_required",
                },
                policy,
            )
        self.assertEqual(
            mixed_failure.exception.category,
            "model_session_or_token_ceiling",
        )

    def test_complete_usage_record_has_required_fields(self) -> None:
        record = usage_record(
            usage={"model": "gpt-5.6-sol", "total_tokens": 4},
            policy=model_policy("implementation"),
            result="passed",
            repository_fingerprint_value="repo-fingerprint",
            next_action="run deterministic verification",
            session_id="session-2",
        )
        required = {
            "effective_model",
            "reasoning_effort",
            "invocation_route",
            "session_id",
            "input_token_usage",
            "cache_read_token_usage",
            "output_token_usage",
            "reasoning_token_usage",
            "applicable_token_ceiling",
            "stage_name",
            "stage_result",
            "repository_fingerprint",
            "exact_next_action",
        }
        self.assertTrue(required.issubset(record))

    def test_quiet_hermes_session_metadata_proves_effective_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (
                      id TEXT PRIMARY KEY, model TEXT, model_config TEXT,
                      end_reason TEXT, input_tokens INTEGER, output_tokens INTEGER,
                      cache_read_tokens INTEGER, reasoning_tokens INTEGER
                    );
                    CREATE TABLE session_model_usage (
                      session_id TEXT, api_call_count INTEGER, input_tokens INTEGER,
                      output_tokens INTEGER, cache_read_tokens INTEGER,
                      reasoning_tokens INTEGER
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                    (
                        "fresh-session",
                        "gpt-5.6-sol",
                        json.dumps(
                            {
                                "max_tokens": 60_000,
                                "reasoning_config": {"effort": "high"},
                            }
                        ),
                        "cli_close",
                        10,
                        4,
                        2,
                        3,
                    ),
                )
                connection.execute(
                    "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?)",
                    ("fresh-session", 1, 10, 4, 2, 3),
                )
            usage = hermes_chat_usage("\nsession_id: fresh-session\n", database)
            self.assertEqual(usage["model"], "gpt-5.6-sol")
            self.assertEqual(usage["reasoning_effort"], "high")
            self.assertEqual(usage["configured_max_tokens"], 60_000)
            self.assertEqual(usage["api_calls"], 1)
            validate_usage(usage, model_policy("implementation"))

    def test_missing_hermes_usage_remains_unavailable_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (
                      id TEXT PRIMARY KEY, model TEXT, model_config TEXT,
                      end_reason TEXT, input_tokens INTEGER, output_tokens INTEGER,
                      cache_read_tokens INTEGER, reasoning_tokens INTEGER
                    );
                    CREATE TABLE session_model_usage (
                      session_id TEXT, api_call_count INTEGER, input_tokens INTEGER,
                      output_tokens INTEGER, cache_read_tokens INTEGER,
                      reasoning_tokens INTEGER
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                    (
                        "usage-omitted",
                        "gpt-5.6-sol",
                        json.dumps(
                            {
                                "max_tokens": 60_000,
                                "reasoning_config": {"effort": "high"},
                            }
                        ),
                        "cli_close",
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            usage = hermes_chat_usage("session_id: usage-omitted\n", database)
            for field in (
                "api_calls",
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "reasoning_tokens",
                "total_tokens",
            ):
                self.assertIsNone(usage[field])
            report = normalize_usage(usage, model_policy("implementation"))
            self.assertEqual(report["input_token_usage"], "unavailable from provider")
            self.assertEqual(report["total_token_usage"], "unavailable from provider")

    def test_all_required_failure_categories_are_distinct(self) -> None:
        self.assertEqual(len(FAILURE_CATEGORIES), 17)
        self.assertIn("pre_model_infrastructure_failure", FAILURE_CATEGORIES)
        self.assertIn("gateway_or_network_failure", FAILURE_CATEGORIES)
        self.assertIn("unsupported_invocation_configuration", FAILURE_CATEGORIES)
        self.assertIn("empty_or_invalid_task_delivery", FAILURE_CATEGORIES)
        self.assertIn("empty_or_invalid_task_delivery", RECOVERABLE_ROUTING_FAILURES)
        self.assertIn("test_fixture_failure", FAILURE_CATEGORIES)
        self.assertIn("remote_ci_failure", FAILURE_CATEGORIES)
        self.assertIn("lock_or_overlapping_process_failure", RECOVERABLE_ROUTING_FAILURES)
        self.assertIn("model_session_or_token_ceiling", RECOVERABLE_ROUTING_FAILURES)
        self.assertIn("context_materialization_required", FAILURE_CATEGORIES)
        self.assertIn("context_materialization_required", RECOVERABLE_ROUTING_FAILURES)

    def test_scheduler_health_requires_success_after_latest_restoration(self) -> None:
        common = {
            "enabled": True,
            "last_status": "ok",
            "consecutive_errors": 0,
            "now_ms": 20_000,
            "heartbeat_ms": 10_000,
        }
        self.assertFalse(
            post_restoration_scheduler_ok(**common, last_run_ms=19_000, restored_at_ms=19_500)
        )
        self.assertTrue(
            post_restoration_scheduler_ok(**common, last_run_ms=19_750, restored_at_ms=19_500)
        )


class RepositoryEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process_environment = mock.patch.dict(
            os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}
        )
        self.process_environment.start()

    def tearDown(self) -> None:
        self.process_environment.stop()

    def make_repo(self, directory: Path) -> Path:
        repo = directory / "repo"
        (repo / "ops").mkdir(parents=True)
        (repo / "docs").mkdir()
        (repo / "docs/005_API_SPECIFICATION.md").write_text(
            "# API\n\n## API-100 — Test API authority\n\nExact API requirement.\n"
        )
        (repo / "docs/008_SECURITY_MODEL.md").write_text(
            "# Security\n\n## SEC-020 — Test security authority\n\nExact security requirement.\n"
        )
        (repo / "ops/NOW.md").write_text("# Compact state\n")
        (repo / "ops/QUEUE.md").write_text("durable queue\n")
        state = {
            "branch": "main",
            "status": "approved_ready",
            "roadmap": {"current_id": "V1-018", "total": 60},
            "next_candidate": {
                "id": "V1-018",
                "roadmap_id": "V1-018",
                "phase": "Identity",
                "task": "Account and capability administration API",
                "status": "approved_ready",
                "authorities": ["API-100"],
            },
            "next_action": "Implement V1-018",
        }
        atomic_write_json(repo / "ops/STATE.json", state)
        atomic_write_json(
            repo / "ops/V1_ROADMAP.json",
            {
                "total_tranches": 60,
                "tranches": [
                    {
                        "id": "V1-018",
                        "task": "Account and capability administration API",
                        "status": "approved_ready",
                        "authorization": "durable_v1",
                        "authorities": ["API-100", "SEC-020"],
                        "include": ["bounded admin API"],
                        "exclude": ["bootstrap reset"],
                        "acceptance": ["deny by default"],
                        "protected_operation": False,
                    }
                ],
            },
        )
        (repo / ".gitignore").write_text("__pycache__/\n")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "add", "--", "ops", "docs", ".gitignore"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
        return repo

    def make_activation_repo(self, directory: Path) -> tuple[Path, dict[str, Any]]:
        repo = directory / "repo"
        (repo / "ops").mkdir(parents=True)
        (repo / "scripts").mkdir()
        for name in (
            "openclaw-select-next-candidate.sh",
            "openclaw-supervisor-preflight.sh",
            "openclaw_automation.py",
        ):
            target = repo / "scripts" / name
            target.write_bytes((ROOT / "scripts" / name).read_bytes())
            target.chmod(0o755)
        wait = repo / "scripts/openclaw-wait-for-ci.sh"
        wait.write_text("#!/bin/sh\nexit 0\n")
        wait.chmod(0o755)
        (repo / "ops/NOW.md").write_text("# Compact state\n")
        (repo / "ops/QUEUE.md").write_text(
            "Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.\n"
        )
        candidate = {
            "id": "V1-018",
            "order": 18,
            "phase": "Identity",
            "task": "Account and capability administration API",
            "dependencies": ["V1-017"],
            "authorities": ["API-079-080", "SEC-019-023"],
            "include": ["bounded account administration"],
            "exclude": ["invented role authority"],
            "risk_class": "high",
            "acceptance_profile": "api_ui",
            "authorization": "durable_v1",
            "status": "approved_ready",
            "protected_operation": False,
        }
        atomic_write_json(
            repo / "ops/STATE.json",
            {
                "status": "published",
                "phase": "Identity",
                "tranche": "Protected bootstrap",
                "task": "Published V1-017",
                "active_cycle": "v1-017",
                "branch": "main",
                "commit": "published",
                "roadmap": {"current_id": "V1-017", "total": 2},
                "approval": {
                    "status": "complete",
                    "implementation_started": True,
                    "implementation_completed": True,
                    "publication_completed": True,
                },
                "next_candidate": {
                    "phase": "unselected",
                    "task": "No successor selected.",
                    "status": "not_approved",
                },
                "next_action": "materialize successor",
                "idle_reason": "awaiting deterministic selection",
                "owner_action": "none",
                "blockers": [],
            },
        )
        atomic_write_json(
            repo / "ops/V1_ROADMAP.json",
            {
                "total_tranches": 2,
                "tranches": [
                    {
                        "id": "V1-017",
                        "order": 17,
                        "phase": "Identity",
                        "task": "Protected bootstrap",
                        "dependencies": [],
                        "authorization": "durable_v1",
                        "status": "published",
                    },
                    candidate,
                ],
            },
        )
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "add", "--", "ops", "scripts"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
        origin = directory / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=repo, check=True)
        return repo, candidate

    def test_compact_task_packet_excludes_broad_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            preflight = {"actionable": True, "next_action": "Implement V1-018"}
            packet = task_packet(repo, preflight, "implementation")
            rendered = json.dumps(packet)
            self.assertEqual(packet["stage"], "implementation")
            self.assertEqual(packet["candidate"], "V1-018")
            self.assertEqual(packet["acceptance_criteria"], ["deny by default"])
            self.assertNotIn("OPENCLAW_SUPERVISOR_PROMPT", rendered)
            self.assertNotIn("previous transcript", rendered.lower())
            self.assertNotIn("reasoning history", rendered.lower())
            self.assertNotIn("compact_inputs", packet)
            self.assertNotIn("canonical_paths", packet)

    def test_v1_019_packet_embeds_only_exact_ui_and_test_authorities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for relative in (
                "docs/006_UI_SPECIFICATION.md",
                "docs/007_TESTING_STRATEGY.md",
                "backend/src/property_rental/auth_api.py",
                "frontend/src/App.tsx",
                "frontend/src/App.test.tsx",
                "frontend/src/styles.css",
            ):
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            (repo / "ops").mkdir()
            (repo / "ops/NOW.md").write_text("# V1-019 fixture\n")
            (repo / "ops/QUEUE.md").write_text("durable V1 fixture\n")
            candidate = {
                "id": "V1-019",
                "roadmap_id": "V1-019",
                "order": 19,
                "phase": "Identity",
                "task": "Authentication and account administration UI",
                "status": "approved_ready",
                "authorization": "durable_v1",
                "authorities": [
                    "UI-092",
                    "UI-109-113",
                    "TEST-094-095",
                    "TEST-135",
                ],
                "acceptance_profile": "api_ui",
                "include": ["bounded authentication UI"],
                "exclude": ["first-Owner web bootstrap"],
            }
            atomic_write_json(
                repo / "ops/STATE.json",
                {
                    "branch": "main",
                    "status": "active",
                    "roadmap": {"current_id": "V1-019", "total": 60},
                    "next_candidate": candidate,
                    "approval": {
                        "status": "approved_ready",
                        "implementation_started": True,
                        "implementation_completed": False,
                    },
                    "owner_action": "none",
                    "next_action": "Implement V1-019",
                },
            )
            atomic_write_json(
                repo / "ops/V1_ROADMAP.json",
                {
                    "total_tranches": 60,
                    "acceptance_profiles": {
                        "api_ui": [
                            "API contract and authorization tests",
                            "frontend component/accessibility tests",
                            "backend and frontend builds",
                        ]
                    },
                    "tranches": [candidate],
                },
            )
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "--", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            packet = task_packet(
                repo,
                {"actionable": True, "next_action": "Implement V1-019"},
                "implementation",
                bounded_substage={
                    "id": "sign_in",
                    "order": 1,
                    "total": 4,
                    "task": "Local sign-in",
                    "include": ["local sign-in"],
                },
                recovery_generation=1,
                recovery_state={
                    "recovery_pending": True,
                    "bounded_recovery_attempt": 1,
                    "current_failure_category": "model_session_or_token_ceiling",
                    "bounded_recovery_exhausted": False,
                },
            )
        self.assertEqual(
            [item["authority"] for item in packet["requirement_evidence"]],
            [
                "UI-109",
                "UI-113",
                "TEST-094",
                "TEST-135",
            ],
        )
        rendered = json.dumps(packet)
        self.assertIn(
            "no external skill lookup or compact-state reread is required or permitted",
            rendered,
        )
        self.assertIn("Do not spend tool calls rediscovering", rendered)
        self.assertIn("leave every later V1-019 substage", rendered)
        self.assertNotIn("UI-108", rendered)
        self.assertNotIn("TEST-093", rendered)
        self.assertTrue(packet["authorization_boundaries"]["existing_durable_v1"])
        self.assertFalse(packet["authorization_boundaries"]["renewed_owner_authorization"])
        self.assertEqual(packet["bounded_substage"]["id"], "sign_in")
        self.assertTrue(packet["candidate_state"]["recovery_pending"])
        self.assertEqual(packet["candidate_state"]["recovery_generation"], 1)
        self.assertEqual(packet["candidate_state"]["bounded_recovery_attempt"], 1)
        self.assertIsInstance(packet["candidate_state"]["preserved_changed_paths"], list)
        self.assertIn(
            "include every candidate_state.preserved_changed_paths entry",
            rendered,
        )
        self.assertEqual(
            packet["candidate_state"]["current_failure_category"],
            "model_session_or_token_ceiling",
        )
        self.assertEqual(packet["schema_version"], 5)
        self.assertEqual(len(packet["directly_relevant_paths"]), 5)
        self.assertTrue(
            all(path.startswith("frontend/src/") for path in packet["directly_relevant_paths"])
        )
        context = packet["materialized_implementation_context"]
        self.assertEqual(context["routing_revision"], "v1-019-sign-in-context-routing-v5")
        self.assertTrue(
            any(
                "Do not invoke terminal, Git, npm, make, or any verification command" in step
                for step in context["shortest_execution_sequence"]
            )
        )
        self.assertTrue(
            any(
                "deferred_to_deterministic_supervisor" in step
                for step in context["shortest_execution_sequence"]
            )
        )
        self.assertEqual(
            context["backend_contract"]["route_inventory"][0]["path"],
            "/api/v1/auth/login",
        )

        self.assertEqual(
            context["backend_contract"]["route_inventory"][0]["router_prefix"],
            "/api/v1/auth",
        )
        self.assertEqual(
            context["backend_contract"]["route_inventory"][0]["route_path"],
            "/login",
        )
        self.assertEqual(
            [item["path"] for item in context["frontend_baseline"]],
            [
                "frontend/src/App.tsx",
                "frontend/src/App.test.tsx",
                "frontend/src/styles.css",
            ],
        )
        self.assertNotIn(
            "backend/src/property_rental/auth_api.py",
            packet["directly_relevant_paths"],
        )
        self.assertNotIn("ops/STATE.json", packet["directly_relevant_paths"])
        self.assertNotIn("ops/V1_ROADMAP.json", packet["directly_relevant_paths"])
        self.assertIn("substage_complete", packet["output_contract"]["required"])
        self.assertEqual(
            packet["output_contract"]["field_contracts"],
            {
                "stage_result": "completed",
                "changed_paths": "array of every exact current candidate worktree path",
                "verification": ["deferred_to_deterministic_supervisor"],
                "blockers": [],
                "exact_next_action": "one nonempty string",
            },
        )
        self.assertTrue(
            any(
                "stage_result set to completed" in step
                and '["deferred_to_deterministic_supervisor"]' in step
                for step in context["shortest_execution_sequence"]
            )
        )
        spec = importlib.util.spec_from_file_location(
            "exact_sign_in_write_scope_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        writable = dispatcher.authorized_candidate_writes(
            {"candidate": "V1-019"}, packet, "implementation"
        )
        self.assertEqual(
            writable,
            sorted(context["exact_writable_paths"]),
        )
        self.assertNotIn("backend/src/property_rental", writable)
        self.assertNotIn("backend/tests", writable)
        self.assertNotIn("frontend/src", writable)
        predecessor = preservation_evidence(ROOT)
        self.assertEqual(predecessor["candidate"], "V1-018")
        self.assertEqual(len(predecessor["paths"]), 7)
        self.assertIsNotNone(predecessor["fingerprint"])

    def test_v1_020_packets_have_bounded_paths_and_authorities(self) -> None:
        roadmap = json.loads((ROOT / "ops/V1_ROADMAP.json").read_text())
        candidate = next(item for item in roadmap["tranches"] if item["id"] == "V1-020")
        expanded = set(expand_authorities(candidate["authorities"], repo=ROOT))
        self.assertNotIn("*", "".join(expanded))
        self.assertTrue(expand_authorities(["BR-PROP-*"], repo=ROOT))
        for substage in V1_020_SUBSTAGE_IDS:
            authorities = V1_020_SUBSTAGE_AUTHORITIES[substage]
            paths = V1_020_SUBSTAGE_PATHS[substage]
            with self.subTest(substage=substage):
                self.assertTrue(set(authorities).issubset(expanded))
                self.assertGreaterEqual(len(paths), 1)
                self.assertLessEqual(len(paths), 8)
                self.assertTrue(all((ROOT / path).is_file() for path in paths))
                self.assertLessEqual(
                    sum((ROOT / path).stat().st_size for path in paths),
                    30_000,
                    "one Hermes read batch must fit beneath the 36,000-byte session allowance",
                )
        spec = importlib.util.spec_from_file_location(
            "v1_020_substage_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        record: dict[str, Any] = {
            "candidate": "V1-020",
            "completed_implementation_substages": [],
        }
        for expected in V1_020_SUBSTAGE_IDS:
            current = dispatcher.current_bounded_substage(record)
            self.assertIsNotNone(current)
            assert current is not None
            self.assertEqual(current["id"], expected)
            record["completed_implementation_substages"].append(expected)
        self.assertIsNone(dispatcher.current_bounded_substage(record))

    def test_sign_in_contract_fails_closed_on_router_or_decorator_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            target = repo / "backend/src/property_rental/auth_api.py"
            target.parent.mkdir(parents=True)
            source = (ROOT / "backend/src/property_rental/auth_api.py").read_text()
            target.write_text(
                source.replace(
                    'APIRouter(prefix="/api/v1/auth"',
                    'APIRouter(prefix="/internal/auth"',
                ).replace(
                    '        "/login",\n        response_model=AuthenticationResponse,',
                    '        "/local-login",\n        response_model=AuthenticationResponse,',
                    1,
                )
            )
            with self.assertRaisesRegex(
                AutomationError, "exact local sign-in API symbols or route are missing"
            ):
                sign_in_backend_contract(repo)

    def test_review_packet_is_separate_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            packet = task_packet(repo, {"actionable": True}, "independent_review")
            self.assertTrue(packet["review_only"])
            self.assertIn("passed", packet["output_contract"]["required"])
            self.assertNotIn("changed_paths", packet["output_contract"]["required"])
            self.assertIn(
                "exactly severity, path, line, and evidence",
                packet["output_contract"]["field_contracts"]["findings"],
            )
            self.assertTrue(packet["output_contract"]["exact_keys_only"])

    def test_repository_fingerprint_changes_with_untracked_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            original = repository_fingerprint(repo)
            (repo / "new.txt").write_text("one\n")
            changed = repository_fingerprint(repo)
            self.assertNotEqual(original, changed)
            (repo / "new.txt").write_text("two\n")
            self.assertNotEqual(changed, repository_fingerprint(repo))
            self.assertEqual(changed_paths(repo), ["new.txt"])

    def test_repository_fingerprint_binds_untracked_mode_and_symlink_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            script = repo / "untracked.sh"
            script.write_text("#!/bin/sh\nexit 0\n")
            initial = repository_fingerprint(repo)
            script.chmod(0o755)
            executable = repository_fingerprint(repo)
            self.assertNotEqual(initial, executable)
            link = repo / "untracked-link"
            link.symlink_to("one")
            first_target = repository_fingerprint(repo)
            link.unlink()
            link.symlink_to("two")
            self.assertNotEqual(first_target, repository_fingerprint(repo))

    def test_exact_actionable_fingerprints_include_repo_state_and_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            first = actionable_fingerprint(repo, {"actionable": True, "task": "one"})
            second = actionable_fingerprint(repo, {"actionable": True, "task": "two"})
            self.assertEqual(
                set(first),
                {"repository", "compact_state", "process_state", "actionable"},
            )
            self.assertNotEqual(first["actionable"], second["actionable"])

    def test_task_packet_materializes_root_acceptance_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            roadmap_path = repo / "ops/V1_ROADMAP.json"
            roadmap = json.loads(roadmap_path.read_text())
            roadmap["tranches"][0].pop("acceptance")
            roadmap["tranches"][0]["acceptance_profile"] = "api_ui"
            roadmap["acceptance_profiles"] = {"api_ui": ["API authorization", "frontend build"]}
            atomic_write_json(roadmap_path, roadmap)
            packet = task_packet(repo, {"actionable": True}, "implementation")
            self.assertEqual(
                packet["acceptance_criteria"],
                ["API authorization", "frontend build"],
            )

    def test_successor_is_materialized_exactly_from_roadmap_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "ops").mkdir(parents=True)
            (repo / "scripts").mkdir()
            for name in (
                "openclaw-select-next-candidate.sh",
                "openclaw-supervisor-preflight.sh",
                "openclaw-wait-for-ci.sh",
                "openclaw_automation.py",
            ):
                source = ROOT / "scripts" / name
                target = repo / "scripts" / name
                target.write_bytes(source.read_bytes())
                target.chmod(0o755)
            ci_marker = root / "selection-ci-observed"
            (repo / "scripts/openclaw-wait-for-ci.sh").write_text(
                '#!/bin/sh\n: >"$PROPERTY_RENTAL_TEST_CI_MARKER"\nexit 0\n'
            )
            (repo / "scripts/openclaw-wait-for-ci.sh").chmod(0o755)
            (repo / "ops/NOW.md").write_text("# state\n")
            (repo / "ops/QUEUE.md").write_text(
                "Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.\n"
            )
            atomic_write_json(
                repo / "ops/STATE.json",
                {
                    "branch": "main",
                    "status": "published",
                    "phase": "Identity",
                    "active_cycle": "v1-017",
                    "commit": "",
                    "roadmap": {"current_id": "V1-017", "total": 2},
                    "approval": {"status": "approved_complete"},
                    "blockers": [],
                    "next_action": "materialize successor",
                    "next_candidate": {
                        "phase": "unselected",
                        "task": "No successor selected.",
                        "status": "not_approved",
                    },
                },
            )

            atomic_write_json(
                repo / "ops/V1_ROADMAP.json",
                {
                    "total_tranches": 2,
                    "tranches": [
                        {"id": "V1-017", "order": 17, "status": "complete"},
                        {
                            "id": "V1-018",
                            "order": 18,
                            "phase": "Identity",
                            "task": "Exact successor",
                            "dependencies": ["V1-017"],
                            "authorities": ["API-079"],
                            "include": ["bounded API"],
                            "exclude": ["policy invention"],
                            "status": "approved_ready",
                            "authorization": "durable_v1",
                            "risk_class": "high",
                            "protected_operation": False,
                        },
                    ],
                },
            )
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "published"], cwd=repo, check=True)
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)
            subprocess.run(["git", "push", "-qu", "-u", "origin", "HEAD"], cwd=repo, check=True)
            subprocess.run(
                [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_SELECTION_SKIP_REMOTE": "true",
                    "PROPERTY_RENTAL_TEST_CI_MARKER": str(ci_marker),
                },
                check=True,
                stdout=subprocess.PIPE,
            )
            selected = json.loads((repo / "ops/STATE.json").read_text())
            self.assertEqual(selected["next_candidate"]["roadmap_id"], "V1-018")
            self.assertEqual(selected["roadmap"]["total"], 2)
            self.assertFalse(selected["approval"]["implementation_started"])
            now = (repo / "ops/NOW.md").read_text()
            self.assertIn("V1-018 approved and active", now)
            self.assertIn("Implement the approved bounded candidate: Exact successor", now)
            self.assertTrue(ci_marker.exists())
            invalid_state = json.loads((repo / "ops/STATE.json").read_text())
            invalid_state["branch"] = 7
            atomic_write_json(repo / "ops/STATE.json", invalid_state)
            invalid_branch = subprocess.run(
                [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                cwd=repo,
                env={**os.environ, "PROPERTY_RENTAL_REPO": str(repo)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invalid_branch.returncode, 73)
            self.assertIn("no valid authorized branch", invalid_branch.stderr)

    def test_v1_019_frontend_context_preserves_larger_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "frontend/src"
            source.mkdir(parents=True)
            (source / "App.tsx").write_text("x" * 12_000)
            (source / "App.test.tsx").write_text("test\n")
            (source / "styles.css").write_text("style\n")
            evidence = complete_small_frontend_evidence(repo)
            self.assertEqual(evidence[0]["byte_length"], 12_000)
            self.assertEqual(evidence[0]["complete_content"], "x" * 12_000)

            (source / "styles.css").write_text("x" * V1_019_FRONTEND_CONTEXT_MAX_BYTES)
            with self.assertRaises(AutomationError) as raised:
                complete_small_frontend_evidence(repo)
            self.assertEqual(raised.exception.category, "context_materialization_required")

    def test_v1_019_frontend_context_represents_authorized_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "frontend/src"
            source.mkdir(parents=True)
            (source / "App.tsx").write_text("app\n")
            (source / "styles.css").write_text("style\n")

            evidence = complete_small_frontend_evidence(repo)

            by_path = {item["path"]: item for item in evidence}
            self.assertEqual(
                by_path["frontend/src/App.test.tsx"],
                {
                    "path": "frontend/src/App.test.tsx",
                    "present": False,
                    "sha256": None,
                    "byte_length": 0,
                    "complete_content": None,
                },
            )
            self.assertTrue(by_path["frontend/src/App.tsx"]["present"])

    def test_dispatcher_runs_fresh_implementation_then_persists_next_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-supervisor-dispatch.sh",
                "openclaw-supervisor-preflight.sh",
                "openclaw_dispatch.py",
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                source = ROOT / "scripts" / name
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(source.read_bytes())
                target.chmod(0o755)
            subprocess.run(["git", "add", "--", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "test dispatcher harness"],
                cwd=repo,
                check=True,
            )
            fake = root / "fake-hermes.py"
            capture = root / "prompt.txt"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if 'prompt-size' in args:
    manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
    budget = json.load(open(manifest['budget_path']))
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    open(manifest['budget_path'], 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
reasoning = args[args.index('--reasoning') + 1]
model = args[args.index('--model') + 1]
prompt = args[args.index('--query') + 1]
open(os.environ['CAPTURE'], 'w').write(prompt)
state_path = os.path.join(os.environ['PROPERTY_RENTAL_REPO'], 'ops', 'STATE.json')
state = json.load(open(state_path))
if reasoning == 'high':
    state['status'] = 'complete_uncommitted'
    state['approval'] = {'status':'approved_ready','implementation_started':True,'implementation_completed':True,'publication_completed':False}
    open(state_path, 'w').write(json.dumps(state, sort_keys=True, indent=2) + '\\n')
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget_path = manifest['budget_path']
budget = json.load(open(budget_path))
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':model,'api_calls_started':1,'api_calls_completed':1,'input_tokens':10,'cache_read_tokens':2,'output_tokens':4,'reasoning_tokens':3,'counted_total_tokens':14})
open(budget_path, 'w').write(json.dumps(budget))
print(json.dumps({'stage_result':'completed','changed_paths':['ops/STATE.json'],'verification':['focused implementation checks passed'],'blockers':[],'exact_next_action':'deterministic verification'}))
"""
            )
            fake.chmod(0o755)
            fake_ps = root / "ps"
            fake_ps.write_text(dispatcher_ps_probe_script())
            fake_ps.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            state_dir = root / "evidence"
            result = subprocess.run(
                [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "CAPTURE": str(capture),
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                    "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
                    "PATH": f"{root}:{os.environ['PATH']}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads((state_dir / "candidates/V1-018.json").read_text())
            self.assertEqual(evidence["stage"], "deterministic_verification")
            self.assertTrue(evidence["implementation_complete"])
            self.assertEqual(evidence["events"][0]["stage"], "reconciliation_dispatch")
            self.assertEqual(evidence["events"][0]["result"], "passed")
            self.assertEqual(evidence["model_usage"][0]["effective_model"], "gpt-5.6-sol")
            self.assertRegex(str(evidence["model_usage"][0]["session_id"]), r"^[0-9a-f]{32}$")
            usage = json.loads(next((state_dir / "usage").glob("*.json")).read_text())
            self.assertTrue(usage["preflight_guard_loaded"])
            self.assertTrue(usage["chat_guard_loaded"])
            self.assertGreater(usage["chat_guard_pid"], 1)
            prompt = capture.read_text()
            self.assertIn('"candidate": "V1-018"', prompt)
            self.assertNotIn("OPENCLAW_SUPERVISOR_PROMPT", prompt)

    def test_v1_019_real_wrapper_ceiling_recovery_retries_with_changed_route(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-supervisor-dispatch.sh",
                "openclaw-supervisor-preflight.sh",
                "openclaw_dispatch.py",
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
                "openclaw-visibility-watchdog.py",
            ):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            shutil.copy(
                ROOT / "docs/006_UI_SPECIFICATION.md",
                repo / "docs/006_UI_SPECIFICATION.md",
            )
            shutil.copy(
                ROOT / "docs/007_TESTING_STRATEGY.md",
                repo / "docs/007_TESTING_STRATEGY.md",
            )
            (repo / "backend/src/property_rental").mkdir(parents=True)
            shutil.copy(
                ROOT / "backend/src/property_rental/auth_api.py",
                repo / "backend/src/property_rental/auth_api.py",
            )
            (repo / "frontend/src").mkdir(parents=True)
            for name in ("App.tsx", "App.test.tsx", "styles.css"):
                shutil.copy(ROOT / "frontend/src" / name, repo / "frontend/src" / name)
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update(
                {
                    "status": "active",
                    "roadmap": {"current_id": "V1-019", "total": 60},
                    "approval": {
                        "status": "approved_ready",
                        "implementation_started": False,
                        "implementation_completed": False,
                        "publication_completed": False,
                    },
                    "next_candidate": {
                        "id": "V1-019",
                        "roadmap_id": "V1-019",
                        "phase": "Identity",
                        "task": "Authentication and account administration UI",
                        "status": "approved_ready",
                        "authorities": [
                            "UI-092",
                            "UI-109-113",
                            "TEST-094-095",
                            "TEST-135",
                        ],
                    },
                    "next_action": "Implement V1-019",
                    "owner_action": "none",
                    "blockers": [],
                    "repair": {
                        "tranche_id": "V1-019",
                        "failure": None,
                        "scope_preserved": True,
                        "attempts": 0,
                        "max_attempts": 2,
                        "requires_owner_decision": False,
                        "suspected_secret": False,
                        "scope_expansion": False,
                        "protected_operation": False,
                    },
                    "automation_repair": {"status": "restored"},
                }
            )
            atomic_write_json(repo / "ops/STATE.json", state)
            roadmap = {
                "total_tranches": 60,
                "acceptance_profiles": {
                    "api_ui": [
                        "API contract and authorization tests",
                        "frontend component/accessibility tests",
                        "backend and frontend builds",
                        "full foundation gates",
                        "GitHub Actions success",
                    ]
                },
                "tranches": [
                    {
                        "id": "V1-019",
                        "task": "Authentication and account administration UI",
                        "phase": "Identity",
                        "status": "approved_ready",
                        "authorization": "durable_v1",
                        "authorities": [
                            "UI-092",
                            "UI-109-113",
                            "TEST-094-095",
                            "TEST-135",
                        ],
                        "include": ["sign-in, MFA, recovery, session, account/capability screens"],
                        "exclude": ["first-Owner web bootstrap"],
                        "acceptance_profile": "api_ui",
                        "protected_operation": False,
                    }
                ],
            }
            atomic_write_json(repo / "ops/V1_ROADMAP.json", roadmap)
            (repo / "ops/QUEUE.md").write_text(
                "Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.\n"
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "V1-019 production-shaped fixture"],
                cwd=repo,
                check=True,
            )

            fake = root / "fake-hermes.py"
            counter = root / "chat-count"
            captures = root / "prompts"
            captures.mkdir()
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget_path = manifest['budget_path']
budget = json.load(open(budget_path))
if 'prompt-size' in args:
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    open(budget_path, 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
counter = pathlib.Path(os.environ['CHAT_COUNTER'])
number = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(number))
prompt = args[args.index('--query') + 1]
pathlib.Path(os.environ['CAPTURE_DIR'], f'{number}.txt').write_text(prompt)
if number == 1:
    budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':'gpt-5.6-sol','api_calls_started':2,'api_calls_completed':2,'input_tokens':50000,'output_tokens':4000,'cache_read_tokens':12000,'reasoning_tokens':500,'counted_total_tokens':54000,'reservation_blocked':True,'predicted_next_context_tokens':7000,'next_api_call_blocked':True,'boundary_reached':False,'in_flight_overshoot_tokens':0,'reservation_violation':False})
    open(budget_path, 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
state_path = pathlib.Path(os.environ['PROPERTY_RENTAL_REPO'], 'ops', 'STATE.json')
state = json.loads(state_path.read_text())
state['approval']['implementation_started'] = True
state_path.write_text(json.dumps(state, sort_keys=True, indent=2) + '\\n')
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':'gpt-5.6-sol','api_calls_started':1,'api_calls_completed':1,'input_tokens':8000,'output_tokens':1000,'cache_read_tokens':2000,'reasoning_tokens':100,'counted_total_tokens':9000})
open(budget_path, 'w').write(json.dumps(budget))
print(json.dumps({'stage_result':'completed','changed_paths':['ops/STATE.json'],'verification':['sign-in substage checks passed'],'blockers':[],'exact_next_action':'dispatch MFA/recovery substage','substage_complete':True}))
"""
            )
            fake.chmod(0o755)
            fake_ps = root / "ps"
            fake_ps.write_text(dispatcher_ps_probe_script())
            fake_ps.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            evidence = root / "evidence"
            environment = {
                **os.environ,
                "CHAT_COUNTER": str(counter),
                "CAPTURE_DIR": str(captures),
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(evidence),
                "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
                "PATH": f"{root}:{os.environ['PATH']}",
            }
            first = subprocess.run(
                [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first.returncode, 69, first.stderr)
            first_record = json.loads((evidence / "candidates/V1-019.json").read_text())
            self.assertIn("recovery_pending", first_record, first.stderr)
            self.assertTrue(first_record["recovery_pending"])
            self.assertEqual(first_record["recovery_generation"], 1)
            self.assertEqual(first_record["ceiling_recovery_attempts"], {"sign_in": 1})
            failure = json.loads((evidence / "last-failure.json").read_text())
            self.assertEqual(failure["category"], "model_session_or_token_ceiling")
            self.assertFalse(failure["owner_action_required"])
            self.assertTrue(list((evidence / "terminal/routing_recovery_pending").glob("*.json")))
            first_usage = json.loads(sorted((evidence / "usage").glob("*.json"))[0].read_text())
            self.assertTrue(first_usage["reservation_blocked"])
            self.assertEqual(first_usage["in_flight_overshoot_tokens"], 0)
            self.assertEqual(first_usage["configured_max_tokens"], 60_000)
            durable_usage = first_record["model_usage"][-1]
            self.assertEqual(durable_usage["api_calls_started"], 2)
            self.assertEqual(durable_usage["api_calls_completed"], 2)
            self.assertTrue(durable_usage["reservation_blocked"])
            self.assertEqual(durable_usage["predicted_next_context_tokens"], 7_000)
            self.assertEqual(durable_usage["in_flight_overshoot_tokens"], 0)
            self.assertFalse(durable_usage["reservation_violation"])

            database = root / "openclaw.sqlite"
            payload = json.dumps(
                {
                    "kind": "command",
                    "argv": [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                    "cwd": str(repo),
                    "noOutputTimeoutSeconds": 10860,
                    "outputMaxBytes": 20000,
                },
                separators=(",", ":"),
            )
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE cron_jobs (job_id TEXT, name TEXT, enabled INTEGER, schedule_kind TEXT, every_ms INTEGER, payload_kind TEXT, payload_message TEXT, last_run_at_ms INTEGER, last_run_status TEXT, consecutive_errors INTEGER, running_at_ms INTEGER, updated_at INTEGER)"
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                        "property-rental-24x7-supervisor",
                        1,
                        "every",
                        1_800_000,
                        "command",
                        payload,
                        2_000,
                        "ok",
                        0,
                        None,
                        1_000,
                    ),
                )
            watchdog = subprocess.run(
                ["python3", str(repo / "scripts/openclaw-visibility-watchdog.py")],
                cwd=repo,
                env={
                    **environment,
                    "PROPERTY_RENTAL_OPENCLAW_DB": str(database),
                    "PROPERTY_RENTAL_WATCHDOG_STATE_DIR": str(root / "watchdog"),
                    "PROPERTY_RENTAL_INSTALLED_HERMES_WRAPPER": str(
                        repo / "scripts/hermes-property-rental"
                    ),
                    "PROPERTY_RENTAL_NOW_MS": "2000",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(watchdog.returncode, 0, watchdog.stderr)
            self.assertIn("automatic recovery: in progress", watchdog.stdout)
            self.assertIn("Owner action required: false", watchdog.stdout)

            second = subprocess.run(
                [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                cwd=repo,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            second_record = json.loads((evidence / "candidates/V1-019.json").read_text())
            self.assertFalse(second_record["recovery_pending"])
            self.assertFalse((evidence / "last-failure.json").exists())
            self.assertEqual(
                list((evidence / "terminal/routing_recovery_pending").glob("*.json")),
                [],
            )
            self.assertEqual(
                len(list((evidence / "terminal/recovery_succeeded").glob("*.json"))),
                1,
            )
            self.assertEqual(len(list((evidence / "resolved-failures").glob("*.json"))), 1)
            self.assertEqual(second_record["completed_implementation_substages"], ["sign_in"])
            self.assertEqual(len(list((evidence / "manifests").glob("*.json"))), 2)
            self.assertEqual(len(list((evidence / "tasks").glob("*.json"))), 2)
            first_prompt = (captures / "1.txt").read_text()
            second_prompt = (captures / "2.txt").read_text()
            self.assertIn('"bounded_substage": {', first_prompt)
            self.assertIn('"id": "sign_in"', first_prompt)
            self.assertIn('"recovery_generation": 1', second_prompt)
            self.assertNotIn("Use the property-rental-continuity skill", first_prompt)

            second_record.update(
                {
                    "recovery_generation": 2,
                    "recovery_pending": False,
                    "bounded_recovery_exhausted": True,
                    "last_failure_category": "model_session_or_token_ceiling",
                }
            )
            atomic_write_json(evidence / "candidates/V1-019.json", second_record)
            preflight = json.loads(
                subprocess.check_output(
                    [str(repo / "scripts/openclaw-supervisor-preflight.sh")],
                    cwd=repo,
                    env=environment,
                    text=True,
                )
            )
            exhausted_fingerprint = stage_actionable_fingerprint(
                repo,
                preflight,
                candidate="V1-019",
                stage="implementation",
                routing_identity=v1_019_routing_identity(second_record, "implementation"),
            )
            persist_terminal_marker(
                evidence / "terminal",
                status="repair_exhausted",
                fingerprint=exhausted_fingerprint,
                evidence={
                    "phase": "mfa_recovery",
                    "next_action": "Owner action after bounded recovery exhaustion.",
                },
            )
            exhausted_watchdog = subprocess.run(
                ["python3", str(repo / "scripts/openclaw-visibility-watchdog.py")],
                cwd=repo,
                env={
                    **environment,
                    "PROPERTY_RENTAL_OPENCLAW_DB": str(database),
                    "PROPERTY_RENTAL_WATCHDOG_STATE_DIR": str(root / "watchdog-exhausted"),
                    "PROPERTY_RENTAL_REPAIR_EXHAUSTED_DIR": str(
                        evidence / "terminal/repair_exhausted"
                    ),
                    "PROPERTY_RENTAL_INSTALLED_HERMES_WRAPPER": str(
                        repo / "scripts/hermes-property-rental"
                    ),
                    "PROPERTY_RENTAL_NOW_MS": "2000",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(exhausted_watchdog.returncode, 0, exhausted_watchdog.stderr)
            self.assertIn("REPAIR_EXHAUSTED", exhausted_watchdog.stdout)
            self.assertIn("Owner action required: true", exhausted_watchdog.stdout)

    def test_dispatcher_runs_distinct_xhigh_read_only_review_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-supervisor-preflight.sh",
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                source = ROOT / "scripts" / name
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(source.read_bytes())
                target.chmod(0o755)
            state = json.loads((repo / "ops/STATE.json").read_text())
            state["status"] = "complete_uncommitted"
            state["approval"] = {
                "status": "approved_ready",
                "implementation_started": True,
                "implementation_completed": True,
                "publication_completed": False,
            }
            atomic_write_json(repo / "ops/STATE.json", state)
            subprocess.run(
                ["git", "add", "--", "scripts", "ops/STATE.json"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "commit", "-qm", "implementation"], cwd=repo, check=True)
            candidate_base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            fake = root / "fake-review.py"
            capture = root / "review-prompt.txt"
            capture_args = root / "review-args.json"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if 'prompt-size' in args:
    manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
    budget = json.load(open(manifest['budget_path']))
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    open(manifest['budget_path'], 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
prompt = args[args.index('--query') + 1]
open(os.environ['CAPTURE'], 'w').write(prompt)
open(os.environ['CAPTURE_ARGS'], 'w').write(json.dumps(args))
packet = json.loads(prompt[prompt.index('{'):])
result = {'passed': True, 'findings': [], 'reviewed_repository_fingerprint':packet['repository_fingerprint'],'reviewed_paths':packet['scoped_changed_paths'],'exact_next_action': 'publish'}
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget = json.load(open(manifest['budget_path']))
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':'gpt-5.6-sol','api_calls_started':1,'api_calls_completed':1,'input_tokens':20,'cache_read_tokens':5,'output_tokens':5,'reasoning_tokens':8,'counted_total_tokens':25})
open(manifest['budget_path'], 'w').write(json.dumps(budget))
print(json.dumps(result))
"""
            )
            fake.chmod(0o755)
            fake_ps = root / "ps"
            fake_ps.write_text(dispatcher_ps_probe_script())
            fake_ps.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            state_dir = root / "evidence"
            atomic_write_json(
                state_dir / "candidates/V1-018.json",
                {
                    "candidate": "V1-018",
                    "candidate_base_commit": candidate_base_commit,
                    "stage": "independent_review",
                    "implementation_complete": True,
                    "deterministic_verification_passed": True,
                    "scoped_changed_paths": [],
                    "events": [{"stage": "deterministic_verification", "exit_status": 0}],
                },
            )
            before = repository_fingerprint(repo)
            evidence_path = state_dir / "candidates/V1-018.json"
            evidence = json.loads(evidence_path.read_text())
            evidence["verified_repository_fingerprint"] = before
            evidence["verified_paths"] = []
            atomic_write_json(evidence_path, evidence)
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/openclaw_dispatch.py")],
                cwd=repo,
                env={
                    **os.environ,
                    "CAPTURE": str(capture),
                    "CAPTURE_ARGS": str(capture_args),
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                    "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
                    "PATH": f"{root}:{os.environ['PATH']}",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, repository_fingerprint(repo))
            evidence = json.loads((state_dir / "candidates/V1-018.json").read_text())
            self.assertEqual(evidence["stage"], "publication")
            self.assertTrue(evidence["review_verdict"]["passed"])
            self.assertEqual(evidence["model_usage"][0]["requested_reasoning_effort"], "xhigh")
            self.assertRegex(str(evidence["model_usage"][0]["session_id"]), r"^[0-9a-f]{32}$")
            self.assertIn('"review_only": true', capture.read_text())
            packet = json.loads(capture.read_text()[capture.read_text().index("{") :])
            self.assertEqual(packet["directly_relevant_paths"], [])
            self.assertEqual(packet["materialized_candidate_diff"]["base_commit"], candidate_base_commit)
            arguments = json.loads(capture_args.read_text())
            self.assertIn("gpt-5.6-sol", arguments)
            self.assertIn("xhigh", arguments)
            self.assertIn("file,terminal,todo", arguments)
            self.assertNotIn("--yolo", arguments)
            self.assertEqual(evidence["reviewed_paths"], [])
            self.assertEqual(
                evidence["reviewed_repository_fingerprint"],
                repository_fingerprint(repo),
            )

    def test_dispatcher_dry_run_is_model_free_and_repository_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            source = ROOT / "scripts/openclaw-supervisor-preflight.sh"
            target = repo / "scripts/openclaw-supervisor-preflight.sh"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
            target.chmod(0o755)
            automation = repo / "scripts/openclaw_automation.py"
            automation.write_bytes((ROOT / "scripts/openclaw_automation.py").read_bytes())
            subprocess.run(["git", "add", "--", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "test dispatcher harness"],
                cwd=repo,
                check=True,
            )
            before = repository_fingerprint(repo)
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/openclaw_dispatch.py")],
                cwd=repo,
                env={
                    **os.environ,
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "evidence"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    "PROPERTY_RENTAL_DISPATCH_DRY_RUN": "true",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["ready"])
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(report["repository_mutations"], 0)
            self.assertEqual(before, repository_fingerprint(repo))

    def test_automation_repair_hold_prevents_candidate_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            state_path = repo / "ops/STATE.json"
            state = json.loads(state_path.read_text())
            state["automation_repair"] = {
                "status": "published_awaiting_restoration",
                "next_action": "Complete bounded restoration gates",
            }
            atomic_write_json(state_path, state)
            subprocess.run(["git", "add", "--", "ops/STATE.json"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "record repair hold"],
                cwd=repo,
                check=True,
            )
            preflight = json.loads(
                subprocess.check_output(
                    [str(ROOT / "scripts/openclaw-supervisor-preflight.sh")],
                    cwd=repo,
                    env={**os.environ, "PROPERTY_RENTAL_REPO": str(repo)},
                    text=True,
                )
            )
            self.assertFalse(preflight["actionable"])
            self.assertEqual(preflight["state_issue"], "automation_repair_publication_required")

    def test_exact_terminal_fingerprint_suppresses_only_unchanged_dispatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            source = ROOT / "scripts/openclaw-supervisor-preflight.sh"
            target = repo / "scripts/openclaw-supervisor-preflight.sh"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
            target.chmod(0o755)
            automation = repo / "scripts/openclaw_automation.py"
            automation.write_bytes((ROOT / "scripts/openclaw_automation.py").read_bytes())
            subprocess.run(["git", "add", "--", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "test dispatcher harness"],
                cwd=repo,
                check=True,
            )
            spec = importlib.util.spec_from_file_location(
                "terminal_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            environment = {
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                "PROPERTY_RENTAL_DISPATCH_DRY_RUN": "true",
            }
            with mock.patch.dict(os.environ, environment):
                spec.loader.exec_module(dispatcher)
                preflight = dispatcher.command_json(str(target))
                actionable = dispatcher.stage_actionable_fingerprint(
                    repo,
                    preflight,
                    candidate="V1-018",
                    stage="reconciliation_dispatch",
                )
                persist_terminal_marker(
                    state_dir / "terminal",
                    status="blocked",
                    fingerprint=actionable,
                    evidence={"next_action": "preserve exact blocker"},
                )
                first_output = io.StringIO()
                with redirect_stdout(first_output):
                    self.assertEqual(dispatcher.dispatch(), 0)
                self.assertEqual(first_output.getvalue(), "")

                (repo / "ops/NOW.md").write_text("# Changed fingerprint\n")
                subprocess.run(["git", "add", "ops/NOW.md"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "commit", "-qm", "changed fingerprint"],
                    cwd=repo,
                    check=True,
                )
                changed_output = io.StringIO()
                with redirect_stdout(changed_output):
                    self.assertEqual(dispatcher.dispatch(), 0)
                self.assertTrue(json.loads(changed_output.getvalue())["ready"])

    def test_reconciliation_refuses_preexisting_unrelated_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "owner-work.txt").write_text("preserve\n")
            spec = importlib.util.spec_from_file_location(
                "dirty_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
            with self.assertRaisesRegex(AutomationError, "clean worktree"):
                dispatcher.reconciliation_dispatch(
                    {"candidate": "V1-018", "events": []},
                    {"actionable": True},
                )

    def test_implementation_rejects_same_path_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "candidate.txt").write_text("persisted content\n")
            spec = importlib.util.spec_from_file_location(
                "content_drift_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "stage": "implementation",
                "scoped_changed_paths": ["candidate.txt"],
                "repository_fingerprint": repository_fingerprint(repo),
            }
            (repo / "candidate.txt").write_text("different Owner content\n")
            with (
                mock.patch.object(dispatcher, "invoke_model") as invoked,
                self.assertRaisesRegex(AutomationError, "persisted scope"),
            ):
                dispatcher.implementation(record, {"actionable": True})
            invoked.assert_not_called()

    def test_authorized_repair_uses_distinct_direct_codex_recovery_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "direct_recovery_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "stage": "implementation",
                "repair_failure": "concrete failing check",
                "last_failure_category": "deterministic_test_failure",
                "expected_worktree_paths": [],
                "repository_fingerprint": repository_fingerprint(repo),
                "scoped_changed_paths": [],
            }
            with (
                mock.patch.object(
                    dispatcher, "invoke_model", side_effect=RuntimeError("routed")
                ) as invoked,
                self.assertRaisesRegex(RuntimeError, "routed"),
            ):
                dispatcher.implementation(record, {"actionable": True})
            packet = invoked.call_args.args[1]
            policy = invoked.call_args.args[2]
            self.assertEqual(packet["stage"], "direct_codex_recovery")
            self.assertEqual(policy.stage, "direct_codex_recovery")
            self.assertEqual(policy.route, "Hermes")

    def test_successful_recovery_clears_live_failure_for_later_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            state = json.loads((repo / "ops/STATE.json").read_text())
            state["approval"] = {
                "status": "approved_ready",
                "implementation_started": True,
                "implementation_completed": True,
                "publication_completed": False,
            }
            atomic_write_json(repo / "ops/STATE.json", state)
            subprocess.run(["git", "add", "--", "ops/STATE.json"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "record successful repair"],
                cwd=repo,
                check=True,
            )
            spec = importlib.util.spec_from_file_location(
                "successful_recovery_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "stage": "implementation",
                "repair_failure": "a previously failing required check",
                "failed_check": "backend-test",
                "last_failure_category": "deterministic_test_failure",
                "expected_worktree_paths": [],
                "scoped_changed_paths": [],
                "repository_fingerprint": repository_fingerprint(repo),
                "events": [],
            }
            result = {
                "stage_result": "completed",
                "changed_paths": [],
                "verification": ["authorized focused repair check passed"],
                "blockers": [],
                "exact_next_action": "run deterministic verification",
            }
            with mock.patch.object(
                dispatcher,
                "invoke_model",
                return_value=(
                    0,
                    json.dumps(result),
                    {"stage_name": "direct_codex_recovery"},
                ),
            ):
                dispatcher.implementation(record, {"actionable": True})
            self.assertIsNone(record["last_failure_category"])
            self.assertIsNone(record["repair_failure"])
            self.assertIsNone(record["failed_check"])
            handoff = {
                "stage_result": "model_session_or_token_ceiling",
                "implementation_complete": True,
                "required_check_failed": False,
                "known_failing_check": None,
                "repository_fingerprint": repository_fingerprint(repo),
                "compact_state_fingerprint": dispatcher.compact_state_fingerprint(repo),
                "workers_remaining": False,
                "protected_operation": False,
                "policy_question": False,
                "scope_change": False,
                "secret_or_credential": False,
                "product_code_modification_permitted": False,
                "blockers": [],
                "requested_stage": "independent_review",
            }
            self.assertEqual(
                dispatcher.verified_continuation_handoff(
                    json.dumps(handoff), record, "independent_review"
                ),
                handoff,
            )

    def test_guarded_repair_ceiling_uses_last_message_for_safe_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            spec = importlib.util.spec_from_file_location(
                "direct_ceiling_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            fingerprint = repository_fingerprint(repo)
            compact = dispatcher.compact_state_fingerprint(repo)
            handoff = {
                "stage_result": "model_session_or_token_ceiling",
                "implementation_complete": True,
                "required_check_failed": False,
                "known_failing_check": None,
                "repository_fingerprint": fingerprint,
                "compact_state_fingerprint": compact,
                "workers_remaining": False,
                "protected_operation": False,
                "policy_question": False,
                "scope_change": False,
                "secret_or_credential": False,
                "product_code_modification_permitted": False,
                "blockers": [],
                "requested_stage": "deterministic_verification",
            }
            fake = root / "fake-hermes.py"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "args = sys.argv[1:]\n"
                f"handoff = {handoff!r}\n"
                "\nif 'prompt-size' in args:\n"
                "    manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))\n"
                "    budget = json.load(open(manifest['budget_path']))\n"
                "    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})\n"
                "    open(manifest['budget_path'], 'w').write(json.dumps(budget))\n"
                "    print('{}')\n"
                "    raise SystemExit(0)\n"
                "manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))\n"
                "budget = json.load(open(manifest['budget_path']))\n"
                "budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':'gpt-5.6-sol','api_calls_started':2,'api_calls_completed':2,'input_tokens':50000,'output_tokens':10000,'cache_read_tokens':7000,'reasoning_tokens':3000,'counted_total_tokens':60000,'boundary_reached':True,'next_api_call_blocked':True})\n"
                "open(manifest['budget_path'], 'w').write(json.dumps(budget))\n"
                "print(json.dumps(handoff))\n"
                "raise SystemExit(1)\n"
            )
            fake.chmod(0o755)
            fake_ps = root / "ps"
            fake_ps.write_text(dispatcher_ps_probe_script())
            fake_ps.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            record = {
                "candidate": "V1-018",
                "stage": "implementation",
                "implementation_complete": True,
                "scoped_changed_paths": [],
                "events": [],
            }
            packet = {
                "candidate": "V1-018",
                "stage": "direct_codex_recovery",
                "repository_fingerprint": fingerprint,
                "compact_state_fingerprint": compact,
                "process_state_fingerprint": dispatcher.process_fingerprint(repo),
                "preflight_fingerprint": "focused-direct-ceiling-test",
                "scoped_changed_paths": [],
            }
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                        "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                        "PATH": f"{root}:{os.environ['PATH']}",
                    },
                ),
                self.assertRaises(AutomationError) as raised,
            ):
                dispatcher.invoke_model(record, packet, model_policy("direct_codex_recovery"))
            self.assertEqual(raised.exception.category, "model_session_or_token_ceiling")
            self.assertEqual(record["stage"], "deterministic_verification")
            self.assertEqual(record["requested_stage"], "deterministic_verification")
            usage_files = [
                path
                for path in (state_dir / "usage").glob("*.json")
                if not path.name.endswith(".result.json")
            ]
            self.assertEqual(len(usage_files), 1)
            usage = json.loads(usage_files[0].read_text())
            self.assertEqual(usage["stop_reason"], "token_ceiling")

    def test_dispatch_routes_persisted_post_publication_before_generic_reconcile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "post_publication_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "dispatch"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            atomic_write_json(
                dispatcher.stage_file("V1-018"),
                {"candidate": "V1-018", "stage": "post_publication_reconciliation"},
            )
            preflight = {
                "actionable": True,
                "state_issue": "published_compact_state_reconciliation_required",
            }
            with (
                mock.patch.object(dispatcher, "relevant_processes", return_value=[]),
                mock.patch.object(dispatcher, "command_json", return_value=preflight),
                mock.patch.object(
                    dispatcher, "post_publication", side_effect=RuntimeError("routed")
                ) as post,
                mock.patch.object(dispatcher, "run") as generic,
                self.assertRaisesRegex(RuntimeError, "routed"),
            ):
                dispatcher.dispatch()
            post.assert_called_once()
            generic.assert_not_called()

    def test_failed_reconciliation_ci_cannot_activate_the_successor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "failed_reconciliation_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "dispatch"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            atomic_write_json(
                dispatcher.stage_file("V1-017"),
                {
                    "candidate": "V1-017",
                    "stage": "post_publication_reconciliation",
                    "reconciliation_substage": "reconciliation_ci_failed",
                    "reconciliation_commit": "f" * 40,
                },
            )
            preflight = {
                "actionable": True,
                "state_issue": "authorized_candidate_selection_required",
            }
            with (
                mock.patch.object(dispatcher, "relevant_processes", return_value=[]),
                mock.patch.object(dispatcher, "command_json", return_value=preflight),
                mock.patch.object(dispatcher, "activate_next") as activate,
                self.assertRaises(AutomationError) as raised,
            ):
                dispatcher.dispatch()
            self.assertEqual(raised.exception.category, "remote_ci_failure")
            activate.assert_not_called()

    def test_dispatch_routes_remote_ci_failure_to_repair_before_reconciliation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "remote_ci_repair_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "dispatch"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            atomic_write_json(
                dispatcher.stage_file("V1-018"),
                {
                    "candidate": "V1-018",
                    "stage": "implementation",
                    "last_failure_category": "remote_ci_failure",
                    "repository_fingerprint": repository_fingerprint(repo),
                    "scoped_changed_paths": [],
                },
            )
            preflight = {
                "actionable": True,
                "state_issue": "published_compact_state_reconciliation_required",
            }
            with (
                mock.patch.object(dispatcher, "relevant_processes", return_value=[]),
                mock.patch.object(dispatcher, "command_json", return_value=preflight),
                mock.patch.object(
                    dispatcher, "implementation", side_effect=RuntimeError("repair")
                ) as repair,
                mock.patch.object(dispatcher, "run") as generic,
                self.assertRaisesRegex(RuntimeError, "repair"),
            ):
                dispatcher.dispatch()
            repair.assert_called_once()
            generic.assert_not_called()

    def test_reconciliation_ci_exit_retains_remote_ci_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "reconcile_ci_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
            failed = subprocess.CompletedProcess([], 74, "", "")
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            record = {
                "candidate": "V1-018",
                "stage": "post_publication_reconciliation",
                "reconciliation_substage": "pushed_waiting_ci",
                "reconciliation_base_commit": head,
                "reconciliation_commit": head,
            }
            with (
                mock.patch.object(dispatcher, "run", return_value=failed),
                self.assertRaises(AutomationError) as raised,
            ):
                dispatcher.post_publication(record)
            self.assertEqual(raised.exception.category, "remote_ci_failure")
            self.assertEqual(record["reconciliation_substage"], "reconciliation_ci_failed")

    def test_reconciliation_resumes_when_commit_precedes_substage_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "reconcile_resume_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                },
            ):
                spec.loader.exec_module(dispatcher)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=repo, text=True
            ).strip()
            next_action = dispatcher.RECONCILIATION_NEXT_ACTION
            (repo / "ops/NOW.md").write_text(
                dispatcher.replace_automation_status(
                    "# Compact state\n",
                    [
                        "<!-- AUTOMATION_STATUS_BEGIN -->",
                        f"- Automation publication state: published on {branch} at {base}.",
                        f"- Automation exact next action: {next_action}",
                        "<!-- AUTOMATION_STATUS_END -->",
                    ],
                )
            )
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update(
                {
                    "status": "published",
                    "branch": branch,
                    "commit": base,
                    "next_action": next_action,
                    "idle_reason": "published candidate awaits deterministic successor selection",
                    "owner_action": "none",
                    "timestamp": "2026-08-20T18:30:00Z",
                }
            )
            state.setdefault("approval", {})["publication_completed"] = True
            atomic_write_json(repo / "ops/STATE.json", state)
            subprocess.run(
                ["git", "add", "--", "ops/NOW.md", "ops/STATE.json"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "ops: reconcile published automation state"],
                cwd=repo,
                check=True,
            )
            record = {
                "candidate": "V1-017",
                "stage": "post_publication_reconciliation",
                "reconciliation_substage": "mutation_pending",
                "reconciliation_base_commit": base,
            }
            completed = subprocess.CompletedProcess([], 0, "", "")
            with (
                mock.patch.object(dispatcher, "run", return_value=completed) as invoked,
                mock.patch.object(
                    dispatcher,
                    "synchronized_repository_shas",
                    return_value={"local": "h", "upstream": "h", "remote": "h"},
                ),
            ):
                dispatcher.post_publication(record)
            self.assertEqual(record["stage"], "next_candidate_activation")
            self.assertEqual(record["reconciliation_substage"], "complete")
            self.assertTrue(
                any(call.args[:2] == ("git", "push") for call in invoked.call_args_list)
            )

    def test_reconciliation_contract_rejects_any_unexpected_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "exact_reconciliation_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=repo, text=True
            ).strip()
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update(
                {
                    "status": "published",
                    "branch": branch,
                    "commit": base,
                    "timestamp": "2026-08-20T18:31:00Z",
                    "next_action": dispatcher.RECONCILIATION_NEXT_ACTION,
                    "idle_reason": "published candidate awaits deterministic successor selection",
                    "owner_action": "none",
                }
            )
            state.setdefault("approval", {})["publication_completed"] = True
            now = dispatcher.replace_automation_status(
                "# Compact state\n",
                [
                    "<!-- AUTOMATION_STATUS_BEGIN -->",
                    f"- Automation publication state: published on {branch} at {base}.",
                    f"- Automation exact next action: {dispatcher.RECONCILIATION_NEXT_ACTION}",
                    "<!-- AUTOMATION_STATUS_END -->",
                ],
            )
            self.assertTrue(
                dispatcher.exact_reconciliation_contract(
                    base=base, branch=branch, state=state, now=now
                )
            )
            state["blockers"] = ["silently injected blocker"]
            self.assertFalse(
                dispatcher.exact_reconciliation_contract(
                    base=base, branch=branch, state=state, now=now
                )
            )

    def test_successor_activation_resumes_mutation_before_commit_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, candidate = self.make_activation_repo(root)
            spec = importlib.util.spec_from_file_location(
                "activation_resume_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                },
            ):
                spec.loader.exec_module(dispatcher)
                base = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                ).strip()
                environment = os.environ.copy()
                environment["PROPERTY_RENTAL_SELECT_MUTATE_ONLY"] = "true"
                subprocess.run(
                    [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                    cwd=repo,
                    check=True,
                    env=environment,
                )
                record = {
                    "candidate": "V1-017",
                    "stage": "next_candidate_activation",
                    "activation_substage": "selection_pending",
                    "activation_base_commit": base,
                    "activation_candidate": candidate,
                }
                with mock.patch.object(dispatcher, "cached_publication_guard", return_value=None):
                    dispatcher.activate_next(record, {})
            self.assertEqual(record["stage"], "complete")
            self.assertEqual(record["activation_substage"], "complete")
            self.assertTrue(record["activation_ci_passed"])
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=repo, text=True),
                "",
            )

    def test_staged_two_path_successor_waits_for_repository_codex_then_resumes_without_implementation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, candidate = self.make_activation_repo(root)
            roadmap_path = repo / "ops/V1_ROADMAP.json"
            roadmap = json.loads(roadmap_path.read_text())
            roadmap["tranches"][0].update({"status": "complete", "authorization": "complete"})
            atomic_write_json(roadmap_path, roadmap)
            subprocess.run(["git", "add", "--", "ops/V1_ROADMAP.json"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "reconcile predecessor"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "push", "-q"], cwd=repo, check=True)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            mutation_environment = {
                **os.environ,
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_SELECT_MUTATE_ONLY": "true",
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
            }
            subprocess.run(
                [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                cwd=repo,
                check=True,
                env=mutation_environment,
            )
            self.assertEqual(
                subprocess.check_output(
                    ["git", "diff", "--cached", "--name-only"],
                    cwd=repo,
                    text=True,
                ).splitlines(),
                ["ops/NOW.md", "ops/STATE.json"],
            )
            staged_before = subprocess.check_output(
                ["git", "diff", "--cached", "--binary"], cwd=repo
            )
            state_dir = root / "dispatch"
            spec = importlib.util.spec_from_file_location(
                "two_path_activation_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            atomic_write_json(
                dispatcher.stage_file("V1-017"),
                {
                    "candidate": "V1-017",
                    "stage": "next_candidate_activation",
                    "activation_substage": "selection_pending",
                    "activation_base_commit": base,
                    "activation_candidate": candidate,
                    "events": [],
                },
            )
            with (
                mock.patch.object(
                    dispatcher,
                    "relevant_processes",
                    return_value=["repository-codex-worker"],
                ),
                self.assertRaises(AutomationError) as blocked,
            ):
                dispatcher.dispatch()
            self.assertEqual(blocked.exception.category, "lock_or_overlapping_process_failure")
            self.assertEqual(
                subprocess.check_output(["git", "diff", "--cached", "--binary"], cwd=repo),
                staged_before,
            )
            preserved = json.loads(dispatcher.stage_file("V1-017").read_text())
            self.assertEqual(preserved["activation_substage"], "selection_pending")
            self.assertNotIn("attempts", preserved)
            with (
                mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}),
                mock.patch.object(dispatcher, "cached_publication_guard", return_value=None),
            ):
                self.assertEqual(dispatcher.dispatch(), 0)
            completed = json.loads(dispatcher.stage_file("V1-017").read_text())
            self.assertEqual(completed["activation_substage"], "complete")
            self.assertEqual(completed["activation_paths"], ["ops/NOW.md", "ops/STATE.json"])
            self.assertNotIn("attempts", completed)
            state = json.loads((repo / "ops/STATE.json").read_text())
            self.assertEqual(state["next_candidate"]["id"], "V1-018")
            self.assertFalse(state["approval"]["implementation_started"])
            self.assertFalse(dispatcher.stage_file("V1-018").exists())
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=repo, text=True),
                "",
            )

    def test_successor_activation_rejects_altered_persisted_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, candidate = self.make_activation_repo(root)
            spec = importlib.util.spec_from_file_location(
                "activation_scope_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
                base = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                ).strip()
                environment = os.environ.copy()
                environment["PROPERTY_RENTAL_SELECT_MUTATE_ONLY"] = "true"
                subprocess.run(
                    [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                    cwd=repo,
                    check=True,
                    env=environment,
                )
                state = json.loads((repo / "ops/STATE.json").read_text())
                state["next_candidate"]["authorities"] = ["invented-authority"]
                atomic_write_json(repo / "ops/STATE.json", state)
                altered_candidate = dict(candidate)
                altered_candidate["authorities"] = ["invented-authority"]
                record = {
                    "candidate": "V1-017",
                    "stage": "next_candidate_activation",
                    "activation_substage": "selection_pending",
                    "activation_base_commit": base,
                    "activation_candidate": altered_candidate,
                }
                with self.assertRaises(AutomationError) as raised:
                    dispatcher.activate_next(record, {})
            self.assertEqual(raised.exception.category, "repository_integrity_uncertainty")

    def test_already_pushed_activation_persists_successful_ci_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, candidate = self.make_activation_repo(root)
            spec = importlib.util.spec_from_file_location(
                "activation_pushed_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
                base = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                ).strip()
                subprocess.run(
                    [str(repo / "scripts/openclaw-select-next-candidate.sh")],
                    cwd=repo,
                    check=True,
                )
                record = {
                    "candidate": "V1-017",
                    "stage": "next_candidate_activation",
                    "activation_substage": "selection_pending",
                    "activation_base_commit": base,
                    "activation_candidate": candidate,
                }
                dispatcher.activate_next(record, {})
            self.assertTrue(record["activation_ci_passed"])
            self.assertEqual(record["activation_substage"], "complete")

    def test_publication_requires_exact_reviewed_content_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "candidate.txt").write_text("reviewed\n")
            spec = importlib.util.spec_from_file_location(
                "publication_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "scoped_changed_paths": ["candidate.txt"],
                "reviewed_paths": ["candidate.txt"],
                "reviewed_repository_fingerprint": repository_fingerprint(repo),
            }
            (repo / "candidate.txt").write_text("mutated after review\n")
            with self.assertRaisesRegex(AutomationError, "independent-review"):
                dispatcher.publication(record, {"actionable": True})

    def test_publication_resumes_after_commit_before_push(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            wait_script = repo / "scripts/openclaw-wait-for-ci.sh"
            wait_script.parent.mkdir(exist_ok=True)
            wait_script.write_text("#!/bin/sh\nexit 0\n")
            wait_script.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "test publication harness"],
                cwd=repo,
                check=True,
            )
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", str(origin)],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "push", "-qu", "-u", "origin", "HEAD"],
                cwd=repo,
                check=True,
            )
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            (repo / "candidate.txt").write_text("reviewed candidate\n")
            subprocess.run(["git", "add", "candidate.txt"], cwd=repo, check=True)
            reviewed_tree = subprocess.check_output(
                ["git", "write-tree"], cwd=repo, text=True
            ).strip()
            subprocess.run(["git", "commit", "-qm", "candidate"], cwd=repo, check=True)
            published = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            spec = importlib.util.spec_from_file_location(
                "resume_publication_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
                record = {
                    "candidate": "V1-018",
                    "stage": "publication",
                    "scoped_changed_paths": ["candidate.txt"],
                    "reviewed_paths": ["candidate.txt"],
                    "publication_paths": ["candidate.txt"],
                    "publication_substage": "staged_reviewed",
                    "reviewed_base_commit": base,
                    "reviewed_tree": reviewed_tree,
                }
                dispatcher.publication(record, {"actionable": True})
            self.assertEqual(record["publication_commit"], published)
            self.assertEqual(record["stage"], "post_publication_reconciliation")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "rev-parse", "@{upstream}"], cwd=repo, text=True
                ).strip(),
                published,
            )

    def test_post_publication_reconciliation_updates_now_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            prior = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            scripts = repo / "scripts"
            scripts.mkdir(exist_ok=True)
            for name in (
                "openclaw-reconcile-published-state.sh",
                "openclaw-supervisor-preflight.sh",
                "openclaw_automation.py",
            ):
                target = scripts / name
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            wait_script = scripts / "openclaw-wait-for-ci.sh"
            wait_script.write_text("#!/bin/sh\nexit 0\n")
            wait_script.chmod(0o755)
            state_path = repo / "ops/STATE.json"
            state = json.loads(state_path.read_text())
            state.update({"status": "verified_unpublished", "commit": prior})
            state["approval"] = {
                "status": "approved_ready",
                "implementation_started": True,
                "implementation_completed": True,
                "publication_completed": False,
            }
            atomic_write_json(state_path, state)
            subprocess.run(["git", "add", "ops", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "published candidate"],
                cwd=repo,
                check=True,
            )
            published = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", str(origin)],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "push", "-qu", "-u", "origin", "HEAD"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                [str(scripts / "openclaw-reconcile-published-state.sh")],
                cwd=repo,
                env={
                    **os.environ,
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_RECONCILE_SKIP_REMOTE": "true",
                },
                check=True,
            )
            reconciled = json.loads(state_path.read_text())
            self.assertEqual(reconciled["status"], "published")
            self.assertEqual(reconciled["commit"], published)
            self.assertTrue(reconciled["approval"]["publication_completed"])
            now = (repo / "ops/NOW.md").read_text()
            self.assertIn(f"Automation publication state: published on main at {published}", now)
            self.assertIn(
                "Select the exact structured approved successor from ops/V1_ROADMAP.json",
                now,
            )

    def test_failed_review_usage_is_persisted_as_failure_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "failed_review_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            fingerprint = repository_fingerprint(repo)
            candidate_base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            policy = model_policy(
                "independent_review",
                complex_review=True,
                classification_reason="test review",
            )
            usage_report = normalize_usage({"model": "gpt-5.6-sol", "total_tokens": 7}, policy)
            usage_report["repository_fingerprint"] = fingerprint
            verdict = json.dumps(
                {
                    "passed": False,
                    "findings": [
                        {
                            "severity": "high",
                            "path": "candidate.txt",
                            "line": "1",
                            "evidence": "concrete in-scope defect",
                        }
                    ],
                    "reviewed_repository_fingerprint": fingerprint,
                    "reviewed_paths": [],
                    "exact_next_action": "repair the concrete finding",
                }
            )
            record: dict[str, object] = {
                "candidate": "V1-018",
                "candidate_base_commit": candidate_base_commit,
                "stage": "independent_review",
                "scoped_changed_paths": [],
                "events": [],
                "implementation_complete": True,
                "verified_repository_fingerprint": fingerprint,
                "verified_paths": [],
            }
            with (
                mock.patch.object(
                    dispatcher,
                    "invoke_model",
                    return_value=(0, verdict, usage_report),
                ),
                self.assertRaisesRegex(AutomationError, "FAIL"),
            ):
                dispatcher.independent_review(record, {"actionable": True})
            ledger = [
                json.loads(line)
                for line in (state_dir / "model-usage.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(ledger), 1)
            self.assertEqual(ledger[0]["stage_result"], "independent_review_defect")
            self.assertNotEqual(ledger[0]["stage_result"], "passed")
            self.assertTrue(ledger[0]["exact_next_action"])

    def test_pre_model_routing_fault_is_retryable_without_product_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "model harness"], cwd=repo, check=True)
            fake = root / "fake-hermes.py"
            fake.write_text(
                """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
usage = args[args.index('--usage-file') + 1]
json.dump({'model':'gpt-5.6-sol','api_calls':0,'total_tokens':0}, open(usage, 'w'))
raise SystemExit(64)
"""
            )
            fake.chmod(0o755)
            spec = importlib.util.spec_from_file_location(
                "premodel_repeat_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            environment = {
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                "PROPERTY_RENTAL_HERMES_BIN": str(fake),
            }
            with mock.patch.dict(os.environ, environment):
                spec.loader.exec_module(dispatcher)
                record = {"candidate": "V1-018", "stage": "implementation"}
                packet = task_packet(repo, {"actionable": True}, "implementation")
                with self.assertRaises(AutomationError) as first:
                    dispatcher.invoke_model(record, packet, model_policy("implementation"))
                self.assertEqual(first.exception.category, "unsupported_invocation_configuration")
                with self.assertRaises(AutomationError) as second:
                    dispatcher.invoke_model(record, packet, model_policy("implementation"))
            self.assertEqual(second.exception.category, "unsupported_invocation_configuration")
            attempts = json.loads((state_dir / "attempts/V1-018.json").read_text())
            self.assertEqual(attempts["counters"].get("implementation", 0), 0)
            self.assertEqual(list((state_dir / "calls").glob("*.json")), [])

    def test_cached_publication_guard_uses_cached_mode(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "guard_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(dispatcher.subprocess, "run", return_value=completed) as invoked:
            dispatcher.cached_publication_guard()
        environment = invoked.call_args.kwargs["env"]
        self.assertEqual(environment["PROPERTY_RENTAL_GUARD_MODE"], "cached")

    def test_worktree_secret_guard_scans_untracked_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "untracked-secret.txt").write_text("AKIA" + "A" * 16 + "\n")
            result = subprocess.run(
                [str(ROOT / "scripts/openclaw-publication-guard.sh")],
                env={
                    **os.environ,
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_GUARD_MODE": "worktree",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 66)
            self.assertIn("Potential secret material", result.stderr)

    def test_publication_guard_rejects_underscore_named_canonical_document(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            canonical = repo / "docs/007_TESTING_STRATEGY.md"
            canonical.parent.mkdir(exist_ok=True)
            canonical.write_text("canonical\n")
            subprocess.run(["git", "add", "docs"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "canonical baseline"],
                cwd=repo,
                check=True,
            )
            canonical.write_text("unauthorized change\n")
            automation_module = repo / "scripts/openclaw_automation.py"
            automation_module.parent.mkdir(exist_ok=True)
            automation_module.write_bytes((ROOT / "scripts/openclaw_automation.py").read_bytes())
            result = subprocess.run(
                [str(ROOT / "scripts/openclaw-publication-guard.sh")],
                env={**os.environ, "PROPERTY_RENTAL_REPO": str(repo)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 65)

    def test_publication_guard_rejects_deleted_canonical_document_in_both_views(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            canonical = repo / "docs/007_TESTING_STRATEGY.md"
            canonical.parent.mkdir(exist_ok=True)
            canonical.write_text("canonical\n")
            subprocess.run(["git", "add", "docs"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "canonical baseline"],
                cwd=repo,
                check=True,
            )
            canonical.unlink()
            self.assertEqual(publication_candidate_guard(repo, "worktree"), "canonical")
            subprocess.run(
                ["git", "add", "--", "docs/007_TESTING_STRATEGY.md"],
                cwd=repo,
                check=True,
            )
            self.assertEqual(publication_candidate_guard(repo, "cached"), "canonical")

    def test_repository_fingerprint_handles_newline_untracked_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            unusual = repo / "line\nbreak.txt"
            unusual.write_text("one\n")
            first = repository_fingerprint(repo)
            unusual.write_text("two\n")
            self.assertNotEqual(first, repository_fingerprint(repo))

    def test_repository_fingerprint_and_dispatch_authority_bind_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            bound_branch = subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=repo, text=True
            ).strip()
            main_fingerprint = repository_fingerprint(repo)
            subprocess.run(
                ["git", "switch", "-qc", "same-head-other-branch"],
                cwd=repo,
                check=True,
            )
            self.assertNotEqual(main_fingerprint, repository_fingerprint(repo))
            spec = importlib.util.spec_from_file_location(
                "branch_bound_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
                with self.assertRaises(AutomationError) as raised:
                    dispatcher.authorized_branch()
            self.assertEqual(raised.exception.category, "repository_integrity_uncertainty")

            subprocess.run(["git", "switch", "-q", bound_branch], cwd=repo, check=True)
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.pop("branch")
            atomic_write_json(repo / "ops/STATE.json", state)
            with self.assertRaises(AutomationError) as missing:
                dispatcher.authorized_branch()
            self.assertEqual(missing.exception.category, "repository_integrity_uncertainty")

    def test_actual_execed_hermes_worker_is_detected(self) -> None:
        rows = [
            "4321 Thu Aug 21 12:00:00 2026 /usr/local/bin/hermes --provider openai-codex --model gpt-5.6-sol"
        ]
        self.assertEqual(len(relevant_processes(ROOT, rows)), 1)

    def test_repository_bound_interactive_codex_worker_is_detected(self) -> None:
        rows = [
            f"4321 Thu Aug 21 12:00:00 2026 /usr/local/bin/codex -C {ROOT}",
            "9876 Thu Aug 21 12:00:00 2026 /usr/local/bin/codex -C /tmp/unrelated",
        ]
        self.assertEqual(len(relevant_processes(ROOT, rows)), 1)

    def test_binary_candidate_secret_is_rejected_in_worktree_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            candidate = repo / "binary.dat"
            candidate.write_bytes(b"\x00AKIA" + b"A" * 16 + b"\xff")
            self.assertEqual(publication_candidate_guard(repo, "worktree"), "secret")
            subprocess.run(["git", "add", "binary.dat"], cwd=repo, check=True)
            self.assertEqual(publication_candidate_guard(repo, "cached"), "secret")

    def test_null_usage_fields_are_exactly_unavailable(self) -> None:
        report = normalize_usage(
            {
                "model": None,
                "reasoning_effort": None,
                "input_tokens": None,
                "cache_read_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": None,
                "total_tokens": None,
            },
            model_policy("implementation"),
        )
        for field in (
            "effective_model",
            "reasoning_effort",
            "input_token_usage",
            "cache_read_token_usage",
            "output_token_usage",
            "reasoning_token_usage",
            "total_token_usage",
        ):
            self.assertEqual(report[field], UNAVAILABLE)

    def test_review_refuses_drift_after_complete_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "drift_review", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "stage": "independent_review",
                "implementation_complete": True,
                "scoped_changed_paths": [],
                "verified_paths": [],
                "verified_repository_fingerprint": repository_fingerprint(repo),
            }
            (repo / "drift.txt").write_text("post-gate drift\n")
            with (
                mock.patch.object(dispatcher, "invoke_model") as invoke,
                self.assertRaisesRegex(AutomationError, "gates must rerun"),
            ):
                dispatcher.independent_review(record, {"actionable": True})
            invoke.assert_not_called()
            self.assertEqual(record["stage"], "deterministic_verification")

    def test_independent_review_materializes_exact_diff_without_broad_reads_or_event_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (repo / "ops/NOW.md").write_text("# Compact state\n\ncandidate review\n")
            spec = importlib.util.spec_from_file_location(
                "materialized_review", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            fingerprint = repository_fingerprint(repo)
            usage = normalize_usage(
                {"model": "gpt-5.6-sol", "total_tokens": 9},
                model_policy(
                    "independent_review",
                    complex_review=True,
                    classification_reason="test",
                ),
            )
            captured: dict[str, object] = {}

            def review_model(
                record: dict[str, object],
                packet: dict[str, object],
                policy: object,
            ) -> tuple[int, str, dict[str, object]]:
                del record, policy
                captured.update(packet)
                verdict = {
                    "passed": True,
                    "findings": [],
                    "reviewed_repository_fingerprint": fingerprint,
                    "reviewed_paths": ["ops/NOW.md"],
                    "exact_next_action": "publish",
                }
                return 0, json.dumps(verdict), usage

            record: dict[str, object] = {
                "candidate": "V1-018",
                "candidate_base_commit": base_commit,
                "stage": "independent_review",
                "implementation_complete": True,
                "deterministic_verification_passed": True,
                "scoped_changed_paths": ["ops/NOW.md"],
                "verified_paths": ["ops/NOW.md"],
                "verified_repository_fingerprint": fingerprint,
                "events": [
                    {"stage": "old", "noise": "x" * 200_000},
                    {
                        "stage": "deterministic_verification",
                        "command": "complete-profile",
                        "exit_status": 0,
                        "artifact": "verification.json",
                        "checks_passed": 15,
                    },
                ],
            }
            with mock.patch.object(dispatcher, "invoke_model", side_effect=review_model):
                dispatcher.independent_review(record, {"actionable": True})

            self.assertEqual(captured["directly_relevant_paths"], [])
            materialized = captured["materialized_candidate_diff"]
            self.assertIsInstance(materialized, dict)
            assert isinstance(materialized, dict)
            self.assertEqual(materialized["base_commit"], base_commit)
            self.assertIn("+candidate review", str(materialized["content"]))
            self.assertTrue(materialized["untracked_files_prohibited"])
            self.assertNotIn("x" * 100, json.dumps(captured))
            self.assertEqual(
                captured["verification_evidence"],
                {
                    "deterministic_verification_passed": True,
                    "command": "complete-profile",
                    "exit_status": 0,
                    "artifact": "verification.json",
                    "checks_passed": 15,
                },
            )
            self.assertEqual(record["stage"], "publication")

    def test_independent_review_refuses_untracked_candidate_before_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (repo / "candidate-review.py").write_text("print('untracked')\n")
            spec = importlib.util.spec_from_file_location(
                "untracked_review", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            fingerprint = repository_fingerprint(repo)
            record: dict[str, object] = {
                "candidate": "V1-018",
                "candidate_base_commit": base_commit,
                "stage": "independent_review",
                "implementation_complete": True,
                "deterministic_verification_passed": True,
                "scoped_changed_paths": ["candidate-review.py"],
                "verified_paths": ["candidate-review.py"],
                "verified_repository_fingerprint": fingerprint,
            }
            with (
                mock.patch.object(dispatcher, "invoke_model") as invoke,
                self.assertRaisesRegex(AutomationError, "refuses untracked candidate files"),
            ):
                dispatcher.independent_review(record, {"actionable": True})
            invoke.assert_not_called()

    def test_invalid_review_delivery_is_classified_without_unbound_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "invalid_review", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            fingerprint = repository_fingerprint(repo)
            candidate_base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            usage = normalize_usage(
                {"model": "gpt-5.6-sol"},
                model_policy(
                    "independent_review",
                    complex_review=True,
                    classification_reason="test",
                ),
            )
            record = {
                "candidate": "V1-018",
                "candidate_base_commit": candidate_base_commit,
                "stage": "independent_review",
                "implementation_complete": True,
                "scoped_changed_paths": [],
                "verified_paths": [],
                "verified_repository_fingerprint": fingerprint,
            }
            with (
                mock.patch.object(dispatcher, "invoke_model", return_value=(0, "", usage)),
                self.assertRaisesRegex(AutomationError, "JSON contract"),
            ):
                dispatcher.independent_review(record, {"actionable": True})
            self.assertEqual(record["review_verdict"], {})
            self.assertEqual(record["stage"], "independent_review")
            self.assertIsNone(record["repair_failure"])
            self.assertEqual(record["last_failure_category"], "empty_or_invalid_task_delivery")

    def test_independent_review_recovers_exact_completed_session_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            state = root / "state"
            session_id = "1" * 32
            session_directory = state / "hermes-sessions" / session_id
            session_directory.mkdir(parents=True)
            database = sqlite3.connect(session_directory / "state.db")
            database.execute(
                """CREATE TABLE messages (
                    id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    finish_reason TEXT,
                    active INTEGER NOT NULL
                )"""
            )
            fingerprint = repository_fingerprint(repo)
            verdict = {
                "passed": True,
                "findings": [],
                "reviewed_repository_fingerprint": fingerprint,
                "reviewed_paths": [],
                "exact_next_action": "publish the exact reviewed candidate",
            }
            database.execute(
                "INSERT INTO messages VALUES (1, 'assistant', ?, 'stop', 1)",
                (json.dumps(verdict),),
            )
            database.commit()
            database.close()
            spec = importlib.util.spec_from_file_location(
                "transport_recovery_review", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            usage = normalize_usage(
                {"model": "gpt-5.6-sol", "session_id": session_id, "api_calls": 1},
                model_policy(
                    "independent_review",
                    complex_review=True,
                    classification_reason="test",
                ),
            )
            record: dict[str, object] = {
                "candidate": "V1-018",
                "candidate_base_commit": base_commit,
                "stage": "independent_review",
                "implementation_complete": True,
                "deterministic_verification_passed": True,
                "scoped_changed_paths": [],
                "verified_paths": [],
                "verified_repository_fingerprint": fingerprint,
                "events": [],
            }
            with mock.patch.object(
                dispatcher, "invoke_model", return_value=(0, "", usage)
            ):
                dispatcher.independent_review(record, {"actionable": True})
            self.assertEqual(record["stage"], "publication")
            self.assertEqual(
                record["review_transport_recovery"],
                {
                    "session_id": session_id,
                    "source": "exact_completed_hermes_session",
                    "validated_through_exact_review_contract": True,
                },
            )
            self.assertTrue(record["model_usage"][-1]["output_transport_recovered"])

    def test_completed_session_recovery_rejects_symlinked_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            session_id = "2" * 32
            session_directory = state / "hermes-sessions" / session_id
            session_directory.mkdir(parents=True)
            outside = root / "outside.db"
            database = sqlite3.connect(outside)
            database.execute(
                "CREATE TABLE messages (id INTEGER, role TEXT, content TEXT, finish_reason TEXT, active INTEGER)"
            )
            database.commit()
            database.close()
            (session_directory / "state.db").symlink_to(outside)
            spec = importlib.util.spec_from_file_location(
                "transport_recovery_symlink", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state),
                },
            ):
                spec.loader.exec_module(dispatcher)
            self.assertIsNone(
                dispatcher.preserved_final_assistant_output(
                    {"session_id": session_id, "api_calls_completed": 1}
                )
            )

    def test_model_contract_rejects_blockers_extras_and_secret_evidence(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "contract_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        base = {
            "stage_result": "completed",
            "changed_paths": ["candidate.txt"],
            "verification": ["focused check passed"],
            "blockers": [],
            "exact_next_action": "run complete verification",
        }
        self.assertEqual(
            dispatcher.sanitized_implementation_result(base, ["candidate.txt"])["blockers"],
            [],
        )
        with self.assertRaisesRegex(AutomationError, "blocker"):
            dispatcher.sanitized_implementation_result(
                {**base, "blockers": ["Owner policy"]}, ["candidate.txt"]
            )
        with self.assertRaisesRegex(AutomationError, "schema"):
            dispatcher.sanitized_implementation_result(
                {**base, "transcript": "broad context"}, ["candidate.txt"]
            )
        with self.assertRaises(AutomationError) as secret:
            dispatcher.sanitized_implementation_result(
                {**base, "verification": ["AKIA" + "A" * 16]}, ["candidate.txt"]
            )
        self.assertEqual(secret.exception.category, "secret_credential_or_protected_operation")
        review = {
            "passed": False,
            "findings": [
                {
                    "severity": "high",
                    "path": "candidate.txt",
                    "line": "1",
                    "evidence": "concrete defect",
                }
            ],
            "reviewed_repository_fingerprint": "f" * 64,
            "reviewed_paths": ["AKIA" + "A" * 16],
            "exact_next_action": "repair the finding",
        }
        with self.assertRaises(AutomationError) as review_secret:
            dispatcher.sanitized_review_verdict(review)
        self.assertEqual(
            review_secret.exception.category,
            "secret_credential_or_protected_operation",
        )

    def test_rejected_bounded_completion_contract_recovers_without_model_call(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "ops").mkdir(exist_ok=True)
            state_path = repo / "ops/STATE.json"
            state_path.write_text(
                json.dumps(
                    {
                        "approval": {
                            "implementation_started": False,
                            "implementation_completed": False,
                        }
                    }
                )
                + "\n"
            )
            (repo / "candidate.txt").write_text("baseline\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "baseline"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            state_path.write_text(
                json.dumps(
                    {
                        "approval": {
                            "implementation_started": True,
                            "implementation_completed": False,
                        }
                    }
                )
                + "\n"
            )
            (repo / "candidate.txt").write_text("implemented\n")
            dispatch_state = root / "dispatch-state"
            spec = importlib.util.spec_from_file_location(
                "contract_recovery_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(dispatch_state),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            paths = ["candidate.txt", "ops/STATE.json"]
            fingerprint = repository_fingerprint(repo)
            pending_fingerprint = "a" * 64
            blocked_fingerprint = "b" * 64
            session_id = "c" * 32
            record = {
                "candidate": "V1-019",
                "candidate_base_commit": base,
                "stage": "implementation",
                "routing_revision": "v1-019-sign-in-context-routing-v5",
                "completed_implementation_substages": [],
                "expected_worktree_paths": paths,
                "repository_fingerprint": fingerprint,
                "last_failure_category": "empty_or_invalid_task_delivery",
                "pending_recovery_marker_fingerprint": pending_fingerprint,
                "pending_recovery_marker_status": "routing_recovery_pending",
                "recovery_pending": True,
                "recovery_generation": 5,
                "bounded_recovery_exhausted": False,
                "events": [],
                "model_usage": [
                    {
                        "session_id": session_id,
                        "stage_name": "implementation",
                        "stage_result": "empty_or_invalid_task_delivery",
                        "api_calls_completed": 2,
                    }
                ],
            }
            atomic_write_json(
                dispatch_state
                / "terminal/routing_recovery_pending"
                / f"{pending_fingerprint}.json",
                {
                    "actionable_fingerprint": pending_fingerprint,
                    "status": "routing_recovery_pending",
                },
            )
            atomic_write_json(
                dispatch_state / "terminal/blocked" / f"{blocked_fingerprint}.json",
                {
                    "actionable_fingerprint": blocked_fingerprint,
                    "status": "blocked",
                },
            )
            atomic_write_json(
                dispatch_state / "last-failure.json",
                {
                    "category": "empty_or_invalid_task_delivery",
                    "repository_fingerprint": fingerprint,
                    "actionable_fingerprint": blocked_fingerprint,
                },
            )
            raw = {
                "stage_result": "implemented",
                "changed_paths": paths,
                "verification": "deferred_to_deterministic_supervisor",
                "blockers": [],
                "exact_next_action": "run deterministic supervisor verification",
                "substage_complete": True,
            }
            original_usage = json.loads(json.dumps(record["model_usage"]))
            repair_paths = [
                "ops/AUTOMATION_TRACEABILITY.json",
                "scripts/openclaw_automation.py",
                "scripts/openclaw_dispatch.py",
                "scripts/test_openclaw_automation.py",
            ]
            for path in repair_paths:
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"repair {path}\n")
            subprocess.run(["git", "add", *repair_paths], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "repair"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            repair_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            preserved_fingerprint = preserved_paths_fingerprint(repo, paths)
            with mock.patch.object(dispatcher, "invoke_model") as invoke:
                evidence = dispatcher.recover_preserved_substage_result(
                    record,
                    raw,
                    session_id=session_id,
                    expected_repair_head=repair_head,
                    expected_preserved_fingerprint=preserved_fingerprint,
                )
            invoke.assert_not_called()
            self.assertEqual(evidence["result"], "recovered_without_model_call")
            self.assertEqual(evidence["model_calls_replayed"], 0)
            self.assertEqual(evidence["post_result_deterministic_repairs"], [])
            self.assertEqual(record["completed_implementation_substages"], ["sign_in"])
            self.assertEqual(record["implementation_result"]["stage_result"], "completed")
            self.assertEqual(
                record["implementation_result"]["verification"],
                ["deferred_to_deterministic_supervisor"],
            )
            self.assertEqual(record["model_usage"], original_usage)
            self.assertEqual(record["stage"], "implementation")
            self.assertEqual(record["candidate_base_commit"], repair_head)
            self.assertFalse(record["recovery_pending"])
            self.assertFalse((dispatch_state / "last-failure.json").exists())
            self.assertTrue(
                (
                    dispatch_state / "terminal/recovery_succeeded" / f"{pending_fingerprint}.json"
                ).exists()
            )
            recovered_blocked = (
                dispatch_state / "terminal/recovery_succeeded" / f"{blocked_fingerprint}.json"
            )
            self.assertTrue(recovered_blocked.exists())
            self.assertEqual(
                json.loads(recovered_blocked.read_text())["recovered_session_id"],
                session_id,
            )
            self.assertTrue((dispatch_state / "recovered-results" / f"{session_id}.json").exists())

    def test_completed_dirty_candidate_bootstraps_at_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            (repo / "candidate.txt").write_text("completed work\n")
            spec = importlib.util.spec_from_file_location(
                "completed_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {"candidate": "V1-018", "stage": "reconciliation_dispatch"}
            dispatcher.bootstrap_completed_candidate(record)
            self.assertEqual(record["stage"], "deterministic_verification")
            self.assertTrue(record["implementation_complete"])

    def test_deterministic_verification_forces_complete_and_classifies_fixture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            verification = repo / "scripts/openclaw-deterministic-verification.sh"
            verification.parent.mkdir(exist_ok=True)
            verification.write_text(
                "#!/bin/sh\n"
                "for variable in HERMES_HOME HERMES_MAX_TOKENS "
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR PROPERTY_RENTAL_HERMES_STAGE "
                "PROPERTY_RENTAL_HERMES_TOKEN_CEILING PROPERTY_RENTAL_HERMES_USAGE_FILE "
                "PROPERTY_RENTAL_INVOCATION_MANIFEST PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES "
                "PROPERTY_RENTAL_REPO PROPERTY_RENTAL_TEST_PROCESS_ROWS; do\n"
                '  eval "present=\\${${variable}+set}"\n'
                '  [ "$present" != set ] || exit 91\n'
                "done\n"
                'mkdir -p "$(dirname "$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE")"\n'
                'jq -cn --arg profile "$PROPERTY_RENTAL_VERIFICATION_PROFILE" '
                '\'{profile:$profile,result:"passed"}\' >"$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE"\n'
            )
            verification.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "verification harness"], cwd=repo, check=True)
            spec = importlib.util.spec_from_file_location(
                "verification_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_HERMES_STAGE": "implementation",
                    "PROPERTY_RENTAL_HERMES_TOKEN_CEILING": "60000",
                    "PROPERTY_RENTAL_HERMES_USAGE_FILE": str(root / "live-usage.json"),
                    "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(root / "live-manifest.json"),
                    "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "live-worker",
                    "HERMES_HOME": str(root / "live-hermes-home"),
                    "HERMES_MAX_TOKENS": "60000",
                    "PROPERTY_RENTAL_VERIFICATION_PROFILE": "automation",
                },
            ):
                spec.loader.exec_module(dispatcher)
                record = {
                    "candidate": "V1-018",
                    "stage": "deterministic_verification",
                    "candidate_base_commit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                    ).strip(),
                    "scoped_changed_paths": [],
                    "events": [],
                }
                dispatcher.deterministic_verification(record)
            artifact = json.loads((root / "state/verification/V1-018.json").read_text())
            self.assertEqual(artifact["profile"], "complete")
            self.assertEqual(record["stage"], "independent_review")

            verification.write_text(
                "#!/bin/sh\n"
                'mkdir -p "$(dirname "$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE")"\n'
                'jq -cn \'{result:"failed",failed_gate:"database-test",failure_category:"test_fixture_failure"}\' '
                '>"$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE"\nexit 125\n'
            )
            record.update(
                {
                    "stage": "deterministic_verification",
                    "candidate_base_commit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                    ).strip(),
                    "scoped_changed_paths": ["scripts/openclaw-deterministic-verification.sh"],
                }
            )
            with self.assertRaises(AutomationError) as failure:
                dispatcher.deterministic_verification(record)
            self.assertEqual(failure.exception.category, "test_fixture_failure")
            self.assertEqual(record["stage"], "deterministic_verification")
            with self.assertRaises(AutomationError) as repeated:
                dispatcher.deterministic_verification(record)
            self.assertEqual(repeated.exception.category, "repeated_identical_tool_call")
            self.assertIn("exit 125; failed gate database-test", str(repeated.exception))


class ContinuationAndAttemptTests(unittest.TestCase):
    def test_v1_019_ceiling_recovery_exhausts_only_after_two_changed_retries(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "bounded_ceiling_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        record = {
            "candidate": "V1-019",
            "stage": "implementation",
            "completed_implementation_substages": [],
            "recovery_generation": 0,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(dispatcher, "STATE_DIR", Path(directory)),
        ):
            self.assertFalse(
                dispatcher.schedule_implementation_ceiling_recovery(record, actionable="first")
            )
            self.assertFalse(record.get("bounded_recovery_exhausted", False))
            self.assertEqual(record["recovery_generation"], 1)
            self.assertFalse(
                dispatcher.schedule_implementation_ceiling_recovery(record, actionable="second")
            )
            self.assertEqual(record["recovery_generation"], 2)
            self.assertTrue(
                dispatcher.schedule_implementation_ceiling_recovery(record, actionable="third")
            )
            state_dir = Path(directory)
            self.assertEqual(record["ceiling_recovery_attempts"], {"sign_in": 3})
            self.assertTrue(record["bounded_recovery_exhausted"])
            self.assertFalse(record["recovery_pending"])
            self.assertEqual(
                len(list((state_dir / "terminal/recovery_attempted").glob("*.json"))),
                2,
            )
            exhausted = json.loads((state_dir / "terminal/repair_exhausted/third.json").read_text())
            self.assertEqual(exhausted["status"], "repair_exhausted")
            review = {
                "candidate": "V1-019",
                "stage": "independent_review",
                "completed_implementation_substages": [
                    "sign_in",
                    "mfa_recovery",
                    "sessions",
                    "account_capability",
                ],
            }
            self.assertFalse(
                dispatcher.schedule_implementation_ceiling_recovery(
                    review,
                    actionable="review-first",
                    phase="independent_review",
                )
            )
            self.assertEqual(review["stage"], "independent_review")
            self.assertTrue(review["recovery_pending"])
            self.assertEqual(review["ceiling_recovery_attempts"], {"independent_review": 1})
            review_marker = json.loads(
                (state_dir / "terminal/routing_recovery_pending/review-first.json").read_text()
            )
            self.assertIn("independent-review retry", review_marker["next_action"])

    def test_context_materialization_checkpoint_does_not_consume_ceiling_recovery(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "context_materialization_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        record = {
            "candidate": "V1-019",
            "stage": "implementation",
            "completed_implementation_substages": [],
            "recovery_generation": 0,
            "ceiling_recovery_attempts": {},
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(dispatcher, "STATE_DIR", Path(directory)),
        ):
            self.assertFalse(
                dispatcher.schedule_context_materialization(record, actionable="context-first")
            )
            self.assertEqual(record["ceiling_recovery_attempts"], {})
            self.assertEqual(record["context_materialization_attempts"], {"sign_in": 1})
            self.assertEqual(record["recovery_generation"], 1)
            self.assertTrue(record["recovery_pending"])
            marker = json.loads(
                (
                    Path(directory) / "terminal/context_materialization_pending/context-first.json"
                ).read_text()
            )
            self.assertFalse(marker["ceiling_recovery_attempt_consumed"])

    def test_pending_marker_resolution_resumes_after_marker_move_crash(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "marker_transition_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(dispatcher, "STATE_DIR", Path(directory)),
        ):
            state_dir = Path(directory)
            record = {
                "candidate": "V1-019",
                "pending_recovery_marker_fingerprint": "a" * 64,
                "pending_recovery_marker_status": "routing_recovery_pending",
            }
            source = state_dir / f"terminal/routing_recovery_pending/{'a' * 64}.json"
            atomic_write_json(
                source,
                {
                    "status": "routing_recovery_pending",
                    "actionable_fingerprint": "a" * 64,
                },
            )
            target = state_dir / f"terminal/recovery_attempted/{'a' * 64}.json"
            target.parent.mkdir(parents=True)
            source.replace(target)

            dispatcher.resolve_pending_routing_recovery(record, outcome="attempted")

            self.assertNotIn("pending_recovery_marker_fingerprint", record)
            self.assertEqual(json.loads(target.read_text())["status"], "recovery_attempted")
            journal = json.loads((state_dir / f"recovery-transitions/{'a' * 64}.json").read_text())
            self.assertEqual(journal["stage"], "candidate_update_pending")

    def test_interrupted_context_recovery_binds_only_exact_authorized_partial_work(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "partial_context_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            record = {
                "candidate": "V1-019",
                "expected_worktree_paths": [],
                "repository_fingerprint": repository_fingerprint(repo),
                "recovery_generation": 1,
            }
            allowed = "frontend/src/authClient.ts"
            (repo / "frontend/src").mkdir(parents=True, exist_ok=True)
            (repo / "frontend/src/App.tsx").write_text("export {}\n")
            subprocess.run(["git", "add", "frontend"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "frontend baseline"], cwd=repo, check=True)
            record["repository_fingerprint"] = repository_fingerprint(repo)
            (repo / allowed).write_text("export {}\n")
            with mock.patch.object(dispatcher, "REPO", repo):
                dispatcher.bind_authorized_partial_work(
                    record,
                    [allowed],
                    exact_paths=True,
                )
                self.assertEqual(record["expected_worktree_paths"], [allowed])
                self.assertEqual(record["repository_fingerprint"], repository_fingerprint(repo))
                self.assertEqual(record["preserved_partial_work"]["paths"], [allowed])
                (repo / allowed).unlink()
                unauthorized = repo / f"{allowed}/unexpected.py"
                unauthorized.parent.mkdir(parents=True)
                unauthorized.write_text("bad\n")
                with self.assertRaisesRegex(
                    AutomationError,
                    "outside its exact dispatcher-authorized scope",
                ):
                    dispatcher.bind_authorized_partial_work(
                        record,
                        [allowed],
                        exact_paths=True,
                    )

    def eligible_record(self) -> tuple[dict[str, object], dict[str, str]]:
        current = {
            "repository": "repo",
            "compact_state": "state",
            "process_state": digest([]),
        }
        record: dict[str, object] = {
            "stop_reason": "model_session_or_token_ceiling",
            "implementation_complete": True,
            "required_check_failed": False,
            "known_failing_check": None,
            "repository_fingerprint": "repo",
            "compact_state_fingerprint": "state",
            "protected_operation": False,
            "policy_question": False,
            "scope_change": False,
            "secret_or_credential": False,
            "continuation_used": False,
            "requested_stage": "deterministic_verification",
        }
        return record, current

    def test_one_mechanical_verification_only_continuation(self) -> None:
        from openclaw_automation import continuation_eligible

        record, current = self.eligible_record()
        self.assertTrue(continuation_eligible(record, current))
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "used.json"
            consume_continuation(marker, record, current)
            saved = json.loads(marker.read_text())
            self.assertFalse(saved["recursive_continuation_permitted"])
            with self.assertRaises(AutomationError):
                consume_continuation(marker, record, current)

    def test_continuation_requires_exact_fingerprint_and_no_workers(self) -> None:
        from openclaw_automation import continuation_eligible

        record, current = self.eligible_record()
        current["repository"] = "changed"
        self.assertFalse(continuation_eligible(record, current))
        record, current = self.eligible_record()
        current["process_state"] = digest(["worker"])
        self.assertFalse(continuation_eligible(record, current))

    def test_continuation_refuses_failed_required_check_or_product_edit_stage(
        self,
    ) -> None:
        from openclaw_automation import continuation_eligible

        record, current = self.eligible_record()
        record["required_check_failed"] = True
        self.assertFalse(continuation_eligible(record, current))
        record, current = self.eligible_record()
        record["requested_stage"] = "implementation"
        self.assertFalse(continuation_eligible(record, current))
        for key in ("failed_check", "repair_failure", "last_failure_category"):
            record, current = self.eligible_record()
            record[key] = "durable failure remains"
            self.assertFalse(continuation_eligible(record, current), key)

    def test_ceiling_continuation_requires_explicit_safe_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "handoff_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {"implementation_complete": True}
            self.assertIsNone(
                dispatcher.verified_continuation_handoff("{}", record, "independent_review")
            )
            safe = {
                "stage_result": "model_session_or_token_ceiling",
                "implementation_complete": True,
                "required_check_failed": False,
                "known_failing_check": None,
                "repository_fingerprint": repository_fingerprint(repo),
                "compact_state_fingerprint": dispatcher.compact_state_fingerprint(repo),
                "workers_remaining": False,
                "protected_operation": False,
                "policy_question": False,
                "scope_change": False,
                "secret_or_credential": False,
                "product_code_modification_permitted": False,
                "blockers": [],
                "requested_stage": "independent_review",
            }
            with mock.patch.object(dispatcher, "relevant_processes", return_value=[]):
                self.assertIsNotNone(
                    dispatcher.verified_continuation_handoff(
                        json.dumps(safe), record, "independent_review"
                    )
                )
            safe["required_check_failed"] = True
            with mock.patch.object(dispatcher, "relevant_processes", return_value=[]):
                self.assertIsNone(
                    dispatcher.verified_continuation_handoff(
                        json.dumps(safe), record, "independent_review"
                    )
                )
            safe["required_check_failed"] = False
            for key in ("failed_check", "repair_failure", "last_failure_category"):
                record[key] = "durable failure remains"
                with mock.patch.object(dispatcher, "relevant_processes", return_value=[]):
                    self.assertIsNone(
                        dispatcher.verified_continuation_handoff(
                            json.dumps(safe), record, "independent_review"
                        ),
                        key,
                    )
                record.pop(key)

    def test_independent_review_continuation_is_consumed_once_and_changes_call_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = RepositoryEvidenceTests()
            repo = helper.make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "continuation_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "state"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
            record = {
                "candidate": "V1-018",
                "stage": "independent_review",
                "stop_reason": "model_session_or_token_ceiling",
                "implementation_complete": True,
                "required_check_failed": False,
                "known_failing_check": None,
                "repository_fingerprint": repository_fingerprint(repo),
                "compact_state_fingerprint": dispatcher.compact_state_fingerprint(repo),
                "protected_operation": False,
                "policy_question": False,
                "scope_change": False,
                "secret_or_credential": False,
                "continuation_used": False,
                "requested_stage": "independent_review",
            }
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                before = digest(dispatcher.model_call_state(record))
                dispatcher.consume_pending_continuation(record, "independent_review")
                after = digest(dispatcher.model_call_state(record))
                self.assertNotEqual(before, after)
                self.assertTrue(record["continuation_used"])
                self.assertFalse(record["product_code_modification_permitted"])
                with self.assertRaisesRegex(AutomationError, "already consumed"):
                    dispatcher.consume_pending_continuation(record, "independent_review")

    def test_pre_model_attempt_reservation_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            reserve_attempt(path, stage="implementation", fingerprint="one")
            reserved = json.loads(path.read_text())
            self.assertEqual(reserved["counters"].get("implementation", 0), 0)
            self.assertEqual(reserved["pending"]["stage"], "implementation")
            release_attempt(path, stage="implementation")
            released = json.loads(path.read_text())
            self.assertEqual(released["counters"].get("implementation", 0), 0)
            self.assertIsNone(released["pending"])

    def test_interrupted_reservation_is_recovered_without_attempt_consumption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            reserve_attempt(path, stage="implementation", fingerprint="one")
            recovered = reserve_attempt(path, stage="implementation", fingerprint="one")
            self.assertEqual(recovered["counters"].get("implementation", 0), 0)
            self.assertEqual(
                recovered["interrupted_reservations"][0]["classification"],
                "unclassified_interruption_no_attempt_consumed",
            )
            consumed = consume_attempt(path, stage="implementation")
            self.assertEqual(consumed["counters"]["implementation"], 1)
            self.assertIsNone(consumed["pending"])

    def test_attempt_budget_resets_for_changed_actionable_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            reserve_attempt(path, stage="implementation", fingerprint="one")
            consume_attempt(path, stage="implementation")
            reserve_attempt(path, stage="implementation", fingerprint="one")
            consume_attempt(path, stage="implementation")
            changed = reserve_attempt(path, stage="implementation", fingerprint="two")
            self.assertEqual(changed["fingerprint"], "two")
            self.assertEqual(changed["counters"].get("implementation", 0), 0)

    def test_exhausted_attempt_uses_routing_fingerprint_and_preserves_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "exhaustion_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
                preflight = {"actionable": True, "next_action": "Implement V1-018"}
                packet = task_packet(repo, preflight, "implementation")
                record = {
                    "candidate": "V1-018",
                    "stage": "implementation",
                    "last_failure_category": "gateway_or_network_failure",
                }
                packet_fingerprint = dispatcher.packet_actionable_fingerprint(record, packet)
                routing_fingerprint = dispatcher.stage_actionable_fingerprint(
                    repo,
                    preflight,
                    candidate="V1-018",
                    stage="implementation",
                )
                self.assertEqual(packet_fingerprint, routing_fingerprint)
                atomic_write_json(
                    state_dir / "attempts/V1-018.json",
                    {
                        "fingerprint": packet_fingerprint,
                        "counters": {"implementation": 2},
                    },
                )
                with self.assertRaises(AutomationError) as raised:
                    dispatcher.invoke_model(record, packet, model_policy("implementation"))
            self.assertEqual(raised.exception.category, "gateway_or_network_failure")
            marker = dispatcher.terminal_marker(state_dir / "terminal", routing_fingerprint)
            self.assertIsNotNone(marker)
            assert marker is not None
            evidence = json.loads(marker.read_text())
            self.assertEqual(evidence["status"], "repair_exhausted")
            self.assertEqual(evidence["root_failure_category"], "gateway_or_network_failure")
            self.assertIn("Owner action", evidence["next_action"])

    def test_direct_recovery_exhaustion_uses_implementation_lifecycle_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            spec = importlib.util.spec_from_file_location(
                "recovery_exhaustion_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
                preflight = {"actionable": True, "next_action": "Repair V1-018"}
                packet = task_packet(repo, preflight, "direct_codex_recovery")
                record = {
                    "candidate": "V1-018",
                    "stage": "implementation",
                    "repair_failure": "authorized concrete defect",
                    "last_failure_category": "deterministic_test_failure",
                }
                packet_fingerprint = dispatcher.packet_actionable_fingerprint(record, packet)
                lifecycle_fingerprint = dispatcher.stage_actionable_fingerprint(
                    repo,
                    preflight,
                    candidate="V1-018",
                    stage="implementation",
                )
                self.assertEqual(packet_fingerprint, lifecycle_fingerprint)
                atomic_write_json(
                    state_dir / "attempts/V1-018.json",
                    {
                        "fingerprint": packet_fingerprint,
                        "counters": {"direct_codex_recovery": 2},
                    },
                )
                with self.assertRaises(AutomationError) as raised:
                    dispatcher.invoke_model(record, packet, model_policy("direct_codex_recovery"))
            self.assertEqual(raised.exception.category, "deterministic_test_failure")
            marker = dispatcher.terminal_marker(state_dir / "terminal", lifecycle_fingerprint)
            self.assertIsNotNone(marker)
            assert marker is not None
            evidence = json.loads(marker.read_text())
            self.assertEqual(evidence["status"], "repair_exhausted")
            self.assertEqual(evidence["stage"], "direct_codex_recovery")
            self.assertEqual(evidence["root_failure_category"], "deterministic_test_failure")

    def test_repeated_call_guard_preserves_underlying_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "call.json"
            fingerprints = {
                "repository": "r",
                "compact_state": "s",
                "process_state": "p",
            }
            key = repeated_call_key(
                identity="tool command",
                arguments=["--one"],
                fingerprints=fingerprints,
                prior_result_category="gateway_or_network_failure",
            )
            atomic_write_json(
                path,
                {
                    "call_key": key,
                    "result": "failed",
                    "normalized_call": "tool command --one",
                    "underlying_result": "exit 70 after one API call",
                    "exact_next_eligible_action": "run focused network diagnostic",
                },
            )
            preserved = repeated_call_result(path, key)
            assert preserved is not None
            self.assertEqual(preserved["preserved_underlying_result"], "exit 70 after one API call")
            self.assertEqual(
                preserved["exact_next_eligible_action"],
                "run focused network diagnostic",
            )
            changed_key = repeated_call_key(
                identity="tool command",
                arguments=["--one"],
                fingerprints={**fingerprints, "repository": "changed"},
                prior_result_category="gateway_or_network_failure",
            )
            self.assertIsNone(repeated_call_result(path, changed_key))

    def test_terminal_markers_are_exact_and_changed_fingerprints_remain_eligible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = persist_terminal_marker(
                root,
                status="completed",
                fingerprint="fingerprint-one",
                evidence={"candidate": "V1-018"},
            )
            self.assertTrue(first.exists())
            self.assertEqual(
                json.loads(first.read_text())["actionable_fingerprint"],
                "fingerprint-one",
            )
            self.assertFalse((root / "completed/fingerprint-two.json").exists())

    def test_automation_clause_traceability_names_executable_tests(self) -> None:
        manifest = json.loads((ROOT / "ops/AUTOMATION_TRACEABILITY.json").read_text())
        sources = "\n".join(
            [
                "test-openclaw-state-routing.sh",
                "test-openclaw-visibility-watchdog.sh",
                (ROOT / "scripts/test_openclaw_automation.py").read_text(),
                (ROOT / "scripts/test-openclaw-state-routing.sh").read_text(),
                (ROOT / "scripts/test-openclaw-visibility-watchdog.sh").read_text(),
            ]
        )
        clauses = manifest["clauses"]
        self.assertGreaterEqual(len(clauses), 20)
        self.assertEqual(len({item["clause"] for item in clauses}), len(clauses))
        for item in clauses:
            self.assertIn(item["test_id"], sources)


class LockHealthAndWrapperTests(unittest.TestCase):
    dispatch: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location(
            "openclaw_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        cls.dispatch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.dispatch)

    def test_non_overlapping_lock_and_verified_stale_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            identity = {"pid": os.getpid(), "identity": "live"}
            with (
                mock.patch.object(self.dispatch, "process_identity", return_value=identity),
                self.dispatch.CycleLock(path),
                self.assertRaises(AutomationError),
            ):
                self.dispatch.CycleLock(path).__enter__()
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".owner.json").exists())
            atomic_write_json(
                path.with_suffix(".owner.json"),
                {"pid": 999999, "identity": "dead"},
            )
            with (
                mock.patch.object(
                    self.dispatch,
                    "process_identity",
                    side_effect=lambda pid: None if pid == 999999 else identity,
                ),
                self.dispatch.CycleLock(path),
            ):
                self.assertTrue(path.with_suffix(".owner.json").exists())
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".owner.json").exists())

    def test_false_ci_failure_reconciliation_is_bound_to_exact_run_and_commit(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "post_exit_reconciliation",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "restoration/current.json"
            evidence.parent.mkdir(parents=True)
            repair_head = "e0469b6d519c0947662204869a535c7080185638"
            metadata_commit = "7c0f67d07092702229329a57176ae0fdc95afd12"
            continuation_head = "d" * 40
            atomic_write_json(
                evidence,
                {
                    "status": "failed_closed",
                    "expected_repair_head": repair_head,
                    "failure": f"restoration metadata CI failed for {metadata_commit}",
                },
            )
            executable = root / "gh"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            args = argparse.Namespace(
                expected_repair_head=repair_head,
                expected_metadata_commit=metadata_commit,
                expected_metadata_run_id=32511133186,
                expected_continuation_head=continuation_head,
                ci_evidence=str(root / "restoration/ci.json"),
                github=str(executable),
            )
            with self.assertRaisesRegex(restoration.RestorationError, "identity is not exact"):
                restoration.reconcile_false_ci_failure(args, root, evidence)

            args.expected_metadata_run_id = 32511133185
            with (
                mock.patch.object(restoration, "git", return_value=continuation_head),
                mock.patch.object(
                    restoration,
                    "restoration_metadata",
                    return_value=metadata_commit,
                ),
                mock.patch.object(
                    restoration,
                    "successful_ci_evidence",
                    return_value={
                        "run_id": 32511133185,
                        "url": "https://example.invalid/runs/32511133185",
                        "workflow_status": "completed",
                        "conclusion": "success",
                    },
                ),
            ):
                restoration.reconcile_false_ci_failure(args, root, evidence)
            reconciled = json.loads(evidence.read_text())
            self.assertEqual(reconciled["status"], "reconciled_false_ci_failure")
            self.assertEqual(reconciled["metadata_commit"], metadata_commit)
            self.assertEqual(reconciled["run_id"], 32511133185)
            self.assertIsNone(reconciled["notification"])
            self.assertTrue(Path(reconciled["prior_evidence"]).exists())

    def test_post_exit_install_failures_terminalize_with_exact_diagnostics(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "install_failure_post_exit",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)

        for failure_kind in ("validation", "reconciliation", "submit"):
            with (
                self.subTest(failure_kind=failure_kind),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repo = root / "repo"
                repo.mkdir()
                job_path = root / "job.json"
                atomic_write_json(
                    job_path,
                    {
                        "id": "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                        "declarationKey": "property-rental-24x7-v1",
                        "name": "property-rental-24x7-supervisor",
                        "agentId": "property-rental-supervisor",
                        "sessionTarget": "isolated",
                        "enabled": False,
                        "schedule": {"kind": "every", "everyMs": 1_800_000},
                        "payload": {
                            "kind": "command",
                            "argv": [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                            "cwd": str(repo),
                        },
                        "state": {
                            "lastRunAtMs": 1,
                            "lastRunStatus": "ok",
                            "consecutiveErrors": 3,
                            "runningAtMs": None,
                        },
                    },
                )
                notification_log = root / "notification.log"
                fake_openclaw = root / "openclaw"
                fake_openclaw.write_text(
                    """#!/usr/bin/env python3
import json, os, pathlib, sys
if sys.argv[1:3] == ['message', 'send']:
    with pathlib.Path(os.environ['FAKE_NOTIFICATION_LOG']).open('a') as handle:
        handle.write('failed_closed\\n')
    print('{}')
    raise SystemExit(0)
path = pathlib.Path(os.environ['FAKE_JOB'])
job = json.loads(path.read_text())
if sys.argv[2] == 'disable':
    job['enabled'] = False
path.write_text(json.dumps(job))
print(json.dumps(job))
"""
                )
                fake_openclaw.chmod(0o755)
                launchctl_log = root / "launchctl.log"
                fake_launchctl = root / "launchctl"
                fake_launchctl.write_text(
                    "#!/bin/sh\n"
                    'if [ "$1" = "submit" ]; then\n'
                    "  printf 'submit stdout\\n'\n"
                    "  printf '%s\\n' \"$GH_TOKEN\" >&2\n"
                    "  exit 7\n"
                    "fi\n"
                    'printf \'%s\\n\' "$*" >> "$FAKE_LAUNCHCTL_LOG"\n'
                )
                fake_launchctl.chmod(0o755)
                fake_github = root / "gh"
                fake_github.write_text("#!/bin/sh\nexit 0\n")
                fake_github.chmod(0o755)
                openclaw_db = root / "openclaw.sqlite"
                with sqlite3.connect(openclaw_db) as connection:
                    connection.execute(
                        """CREATE TABLE cron_jobs (
                            job_id TEXT, name TEXT, enabled INTEGER,
                            delivery_channel TEXT, delivery_to TEXT,
                            delivery_account_id TEXT
                        )"""
                    )
                    connection.execute(
                        "INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            "8db8cc98-56a1-4687-9988-fd7e3750c51b",
                            "property-rental-visibility-watchdog",
                            1,
                            "telegram",
                            "test-sensitive-target",
                            "test-sensitive-account",
                        ),
                    )
                    connection.execute(
                        """CREATE TABLE cron_run_logs (
                            job_id TEXT, seq INTEGER, ts INTEGER, status TEXT,
                            run_at_ms INTEGER, duration_ms INTEGER
                        )"""
                    )
                    connection.execute(
                        "INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                            365,
                            1,
                            "error",
                            1,
                            10,
                        ),
                    )
                evidence = root / "restoration.json"
                atomic_write_json(
                    evidence,
                    (
                        {
                            "status": "failed_closed",
                            "dispatcher_failure_category": "unknown",
                            "recovery_state": "not_running",
                            "owner_action_required": False,
                        }
                        if failure_kind == "reconciliation"
                        else {
                            "status": "failed_closed",
                            "dispatcher_failure_category": "model_session_or_token_ceiling",
                            "recovery_state": "scheduled_in_record_but_not_running_due_fail_closed_disable",
                            "owner_action_required": False,
                        }
                    ),
                )
                args = argparse.Namespace(
                    repo=str(repo),
                    dispatch_state=str(root / "dispatch"),
                    evidence=str(evidence),
                    ci_evidence=str(root / "ci.json"),
                    openclaw=str(fake_openclaw),
                    launchctl=str(fake_launchctl),
                    github=(
                        str(root / "missing-gh")
                        if failure_kind == "validation"
                        else str(fake_github)
                    ),
                    openclaw_db=str(openclaw_db),
                    notification_source_job_id=restoration.NOTIFICATION_SOURCE_JOB_ID,
                    notification_timeout=0.2,
                    terminalizer_handoff_timeout=0.2,
                    owner_pid=999999,
                    expected_repair_head=restoration.REPAIR_PUBLICATION_COMMIT,
                    expected_continuation_head=restoration.REPAIR_PUBLICATION_COMMIT,
                    expected_metadata_commit=restoration.FALSE_FAILURE_METADATA_COMMIT,
                    expected_metadata_run_id=restoration.FALSE_FAILURE_RUN_ID,
                    poll=0.01,
                    overlap_timeout=1.0,
                    natural_run_timeout=1.0,
                )
                with (
                    mock.patch.object(
                        restoration,
                        "git",
                        return_value=restoration.REPAIR_PUBLICATION_COMMIT,
                    ),
                    mock.patch.dict(
                        os.environ,
                        {
                            "FAKE_JOB": str(job_path),
                            "FAKE_NOTIFICATION_LOG": str(notification_log),
                            "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
                            "GH_TOKEN": "synthetic-secret-token",
                        },
                    ),
                ):
                    result = restoration.install(args)

                self.assertEqual(result, 69)
                terminal_text = evidence.read_text()
                terminal = json.loads(terminal_text)
                self.assertEqual(terminal["status"], "failed_closed")
                self.assertFalse(terminal["scheduler_enabled"])
                self.assertEqual(terminal["notification"]["delivery_status"], "delivered")
                self.assertEqual(terminal["unload_status"], "unloaded")
                self.assertEqual(notification_log.read_text().splitlines(), ["failed_closed"])
                self.assertEqual(
                    launchctl_log.read_text().splitlines(),
                    [
                        f"bootout gui/{os.getuid()}/com.property-rental.post-exit-restoration.e0469b6d519c"
                    ],
                )
                self.assertNotIn("synthetic-secret-token", terminal_text)
                self.assertNotIn("test-sensitive-target", terminal_text)
                self.assertNotIn("test-sensitive-account", terminal_text)
                if failure_kind == "validation":
                    self.assertEqual(terminal["failure_phase"], "argument_validation")
                    self.assertIsNone(terminal["launchctl_submit"])
                elif failure_kind == "reconciliation":
                    self.assertEqual(terminal["failure_phase"], "pending_recovery_validation")
                    self.assertIsNone(terminal["launchctl_submit"])
                else:
                    self.assertEqual(terminal["failure_phase"], "launchctl_submit")
                    self.assertEqual(terminal["launchctl_submit"]["exit_status"], 7)
                    self.assertEqual(terminal["launchctl_submit"]["stdout"], "submit stdout\n")
                    self.assertEqual(terminal["launchctl_submit"]["stderr"], "[REDACTED]\n")
                    self.assertTrue(terminal["launchctl_submit"]["redactions_applied"])

    def test_terminal_notification_claim_is_process_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            evidence = root / "restoration.json"
            repair_head = "e0469b6d519c0947662204869a535c7080185638"
            atomic_write_json(
                evidence,
                {
                    "status": "failed_closed",
                    "expected_repair_head": repair_head,
                    "failure": "synthetic terminal failure",
                    "owner_action_required": False,
                },
            )
            notification_log = root / "notification.log"
            fake_openclaw = root / "openclaw"
            fake_openclaw.write_text(
                """#!/usr/bin/env python3
import os, pathlib, sys, time
if sys.argv[1:3] == ['message', 'send']:
    time.sleep(0.1)
    with pathlib.Path(os.environ['FAKE_NOTIFICATION_LOG']).open('a') as handle:
        handle.write('sent\\n')
    print('{}')
    raise SystemExit(0)
raise SystemExit(9)
"""
            )
            fake_openclaw.chmod(0o755)
            fake_launchctl = root / "launchctl"
            fake_launchctl.write_text("#!/bin/sh\nexit 0\n")
            fake_launchctl.chmod(0o755)
            openclaw_db = root / "openclaw.sqlite"
            with sqlite3.connect(openclaw_db) as connection:
                connection.execute(
                    """CREATE TABLE cron_jobs (
                        job_id TEXT, name TEXT, enabled INTEGER,
                        delivery_channel TEXT, delivery_to TEXT,
                        delivery_account_id TEXT
                    )"""
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "8db8cc98-56a1-4687-9988-fd7e3750c51b",
                        "property-rental-visibility-watchdog",
                        1,
                        "telegram",
                        "test-sensitive-target",
                        "test-sensitive-account",
                    ),
                )
            command = [
                "python3",
                str(ROOT / "scripts/openclaw-post-exit-restoration.py"),
                "finalize",
                "--repo",
                str(repo),
                "--dispatch-state",
                str(root / "dispatch"),
                "--evidence",
                str(evidence),
                "--openclaw",
                str(fake_openclaw),
                "--launchctl",
                str(fake_launchctl),
                "--github",
                str(fake_openclaw),
                "--openclaw-db",
                str(openclaw_db),
                "--notification-timeout",
                "1",
                "--expected-repair-head",
                repair_head,
            ]
            environment = {
                **os.environ,
                "FAKE_NOTIFICATION_LOG": str(notification_log),
            }
            workers = [
                subprocess.Popen(
                    command,
                    cwd=repo,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            results = [worker.communicate(timeout=5) for worker in workers]
            self.assertTrue(all(worker.returncode == 69 for worker in workers), results)
            self.assertEqual(notification_log.read_text().splitlines(), ["sent"])
            terminal_text = evidence.read_text()
            terminal = json.loads(terminal_text)
            self.assertTrue(terminal["notification"]["attempted"])
            self.assertEqual(terminal["notification"]["delivery_status"], "delivered")
            self.assertNotIn("test-sensitive-target", terminal_text)
            self.assertNotIn("test-sensitive-account", terminal_text)

    def test_restoration_metadata_preserves_exact_dirty_product_paths(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "dirty_metadata_post_exit",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "ops").mkdir(parents=True)
            (repo / "scripts").mkdir()
            (repo / "frontend/src").mkdir(parents=True)
            (repo / "ops/NOW.md").write_text("# V1-019 repair published\n")
            atomic_write_json(
                repo / "ops/STATE.json",
                {
                    "automation_repair": {
                        "status": "published_awaiting_post_exit_restoration",
                        "scheduler_enabled": False,
                        "stop_after_candidate": "V1-019",
                    }
                },
            )
            product = repo / "frontend/src/App.tsx"
            product.write_text("baseline\n")
            wait_script = repo / "scripts/openclaw-wait-for-ci.sh"
            wait_script.write_text("#!/bin/sh\nexit 0\n")
            wait_script.chmod(0o755)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "repair"], cwd=repo, check=True)
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", str(origin)],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "push", "-qu", "-u", "origin", "HEAD"],
                cwd=repo,
                check=True,
            )
            repair_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            product.write_text("preserved V1-019 sign-in work\n")

            with self.assertRaisesRegex(
                restoration.RestorationError,
                "worktree changed before restoration metadata publication",
            ):
                restoration.restoration_metadata(repo, repair_head)
            metadata_commit = restoration.restoration_metadata(
                repo,
                repair_head,
                preserved_paths=["frontend/src/App.tsx"],
            )

            self.assertEqual(
                subprocess.check_output(
                    ["git", "rev-parse", f"{metadata_commit}^"], cwd=repo, text=True
                ).strip(),
                repair_head,
            )
            self.assertEqual(
                subprocess.check_output(
                    [
                        "git",
                        "diff-tree",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        metadata_commit,
                    ],
                    cwd=repo,
                    text=True,
                ).splitlines(),
                ["ops/NOW.md", "ops/STATE.json"],
            )
            self.assertEqual(changed_paths(repo), ["frontend/src/App.tsx"])
            self.assertEqual(product.read_text(), "preserved V1-019 sign-in work\n")

    def test_post_exit_restoration_succeeds_naturally_and_fails_closed(self) -> None:
        for (
            natural_status,
            notification_failure,
            notification_hang,
            unload_failure,
            terminate_source_on_unload,
        ) in (
            ("ok", False, False, False, False),
            ("ok", True, False, False, False),
            ("recoverable_then_ok", False, False, False, False),
            ("recoverable_then_disabled", False, False, False, False),
            ("exhausted", False, False, False, False),
            ("error", False, False, False, False),
            ("ok_no_progress", False, False, False, False),
            ("protected", False, False, False, False),
            ("error", False, True, False, False),
            ("ok", False, False, True, False),
            ("ok", False, False, False, True),
        ):
            with (
                self.subTest(
                    natural_status=natural_status,
                    notification_failure=notification_failure,
                    notification_hang=notification_hang,
                    unload_failure=unload_failure,
                    terminate_source_on_unload=terminate_source_on_unload,
                ),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repo = root / "repo"
                (repo / "ops").mkdir(parents=True)
                (repo / "scripts").mkdir()
                initial_now = "# V1-019 repair published\n"
                if natural_status == "recoverable_then_ok":
                    initial_now = initial_now.rstrip() + (
                        "\n<!-- POST_EXIT_RESTORATION_BEGIN -->\n"
                        "- Post-exit restoration metadata is published; the existing supervisor "
                        "remains disabled until the continuation enables it.\n"
                        "- V1-019 remains the only active candidate; V1-020 successor activation "
                        "is held.\n"
                        "<!-- POST_EXIT_RESTORATION_END -->\n"
                    )
                (repo / "ops/NOW.md").write_text(initial_now)
                atomic_write_json(
                    repo / "ops/STATE.json",
                    {
                        "branch": "main",
                        "status": "active",
                        "timestamp": "2026-08-21T00:00:00Z",
                        "roadmap": {"current_id": "V1-019", "total": 60},
                        "next_candidate": {
                            "id": "V1-019",
                            "roadmap_id": "V1-019",
                            "task": "Authentication and account administration UI",
                        },
                        "automation_repair": {
                            "status": "published_awaiting_post_exit_restoration",
                            "scheduler_enabled": False,
                            "stop_after_candidate": "V1-019",
                        },
                    },
                )
                wait_script = repo / "scripts/openclaw-wait-for-ci.sh"
                wait_script.write_text(
                    """#!/usr/bin/env python3
import json, pathlib, sys
if '--evidence' in sys.argv:
    path = pathlib.Path(sys.argv[sys.argv.index('--evidence') + 1])
    sha = sys.argv[-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'status':'success','workflow_status':'completed','commit':sha,'head_sha':sha,'conclusion':'success','run_id':999,'url':'https://example.invalid/runs/999'}))
"""
                )
                wait_script.chmod(0o755)
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "test@example.invalid"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-qm", "repair publication"], cwd=repo, check=True)
                origin = root / "origin.git"
                subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
                subprocess.run(
                    ["git", "remote", "add", "origin", str(origin)],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(["git", "push", "-qu", "-u", "origin", "HEAD"], cwd=repo, check=True)
                repair_head = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                ).strip()

                dispatch_state = root / "dispatch"
                stale_candidate = dispatch_state / "candidates/V1-019.json"
                pending_fingerprint = "a" * 64
                atomic_write_json(
                    stale_candidate,
                    {
                        "candidate": "V1-019",
                        "stage": "implementation",
                        "routing_revision": "v1-019-invocation-contract-repair-v2",
                        "candidate_base_commit": "d6eb7e73610b2a72cf38f4b32468226e9e76a436",
                        "repository_fingerprint": "stale",
                        "expected_worktree_paths": [],
                        "completed_implementation_substages": [],
                        "recovery_pending": True,
                        "recovery_generation": 1,
                        "ceiling_recovery_attempts": {"sign_in": 1},
                        "pending_recovery_marker_fingerprint": pending_fingerprint,
                        "model_usage": [
                            {
                                "session_id": "61d145e0655c5298cbcfa576fff3ff78",
                                "stage_result": "model_session_or_token_ceiling",
                                "api_calls_started": 2,
                                "api_calls_completed": 2,
                                "input_token_usage": 16_881,
                                "output_token_usage": 422,
                                "total_token_usage": 17_303,
                                "cache_read_token_usage": 9_216,
                                "predicted_next_context_tokens": 109_152,
                                "in_flight_overshoot_tokens": 0,
                                "unsupported_provider_parameters_removed": [],
                            }
                        ],
                        "events": [],
                    },
                )
                atomic_write_json(
                    dispatch_state / "attempts/V1-019.json",
                    {
                        "fingerprint": pending_fingerprint,
                        "counters": {"implementation": 1},
                        "pending": None,
                    },
                )
                atomic_write_json(
                    dispatch_state / "last-failure.json",
                    {
                        "actionable_fingerprint": pending_fingerprint,
                        "category": "model_session_or_token_ceiling",
                        "owner_action_required": False,
                    },
                )
                atomic_write_json(
                    dispatch_state
                    / f"terminal/routing_recovery_pending/{pending_fingerprint}.json",
                    {
                        "status": "routing_recovery_pending",
                        "actionable_fingerprint": pending_fingerprint,
                        "category": "model_session_or_token_ceiling",
                        "phase": "sign_in",
                        "attempt": 1,
                    },
                )
                atomic_write_json(
                    dispatch_state / "terminal/oversized_or_ceiling_stopped/stale.json",
                    {"fingerprint": "stale"},
                )

                job_path = root / "job.json"
                atomic_write_json(
                    job_path,
                    {
                        "id": "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                        "declarationKey": "property-rental-24x7-v1",
                        "name": "property-rental-24x7-supervisor",
                        "agentId": "property-rental-supervisor",
                        "sessionTarget": "isolated",
                        "enabled": False,
                        "schedule": {"kind": "every", "everyMs": 1_800_000},
                        "payload": {
                            "kind": "command",
                            "argv": [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                            "cwd": str(repo),
                        },
                        "state": {
                            "lastRunAtMs": 1,
                            "lastRunStatus": "ok",
                            "consecutiveErrors": 3,
                            "runningAtMs": None,
                        },
                    },
                )
                fake = root / "openclaw"
                fake.write_text(
                    """#!/usr/bin/env python3
import json, os, pathlib, sys, time
if sys.argv[1:3] == ['message', 'send']:
    message = sys.argv[sys.argv.index('--message') + 1]
    if message.startswith('RESTORATION_COMPLETE'):
        kind = 'complete'
    elif message.startswith('RECOVERY_SCHEDULED'):
        kind = 'recovery_scheduled'
    else:
        kind = 'failed_closed'
    with pathlib.Path(os.environ['FAKE_NOTIFICATION_LOG']).open('a') as handle:
        handle.write(kind + '\\n')
    if os.environ.get('FAKE_NOTIFICATION_HANG') == '1':
        time.sleep(5)
    if os.environ.get('FAKE_NOTIFICATION_FAIL') == '1':
        raise SystemExit(9)
    print('{}')
    raise SystemExit(0)
path = pathlib.Path(os.environ['FAKE_JOB'])
job = json.loads(path.read_text())
action = sys.argv[2]
if action == 'enable':
    job['enabled'] = True
elif action == 'disable':
    job['enabled'] = False
if action in {'enable', 'disable'}:
    with pathlib.Path(os.environ['FAKE_CRON_ACTION_LOG']).open('a') as handle:
        handle.write(action + '\\n')
if action == 'get' and job['enabled']:
    outcome = os.environ['FAKE_NATURAL_STATUS']
    run_number = int(job.get('fakeRunNumber', 0)) + 1
    job['fakeRunNumber'] = run_number
    status = 'error' if outcome in {'error', 'protected', 'recoverable_then_ok', 'recoverable_then_disabled', 'exhausted'} else 'ok'
    if outcome == 'recoverable_then_ok' and run_number > 1:
        status = 'ok'
    dispatch = pathlib.Path(os.environ['FAKE_DISPATCH'])
    candidate = dispatch / 'candidates/V1-019.json'
    record = json.loads(candidate.read_text())
    if outcome == 'ok' or (outcome == 'recoverable_then_ok' and run_number > 1):
        record.update({'completed_implementation_substages':['sign_in'],'recovery_pending':False,'stage':'implementation'})
        candidate.write_text(json.dumps(record))
        failure = dispatch / 'last-failure.json'
        if failure.exists():
            failure.unlink()
    elif outcome in {'recoverable_then_ok', 'recoverable_then_disabled', 'exhausted'}:
        if outcome == 'exhausted' and run_number > 1:
            record.update({'recovery_pending':False,'bounded_recovery_exhausted':True,'recovery_generation':2,'ceiling_recovery_attempts':{'sign_in':3}})
        else:
            record.update({'recovery_pending':True,'recovery_generation':1,'ceiling_recovery_attempts':{'sign_in':1}})
        candidate.write_text(json.dumps(record))
        failure = dispatch / 'last-failure.json'
        failure.write_text(json.dumps({'category':'model_session_or_token_ceiling','owner_action_required':outcome == 'exhausted' and run_number > 1,'exact_next_action':'Run the exact bounded sign_in recovery.'}))
    elif outcome == 'protected':
        failure = dispatch / 'last-failure.json'
        failure.write_text(json.dumps({'category':'protected_operation','owner_action_required':True,'exact_next_action':'Owner must decide the protected operation.'}))
    elif outcome == 'error':
        failure = dispatch / 'last-failure.json'
        failure.write_text(json.dumps({'category':'gateway_or_network_failure','owner_action_required':False,'exact_next_action':'Repair the unknown route.'}))
    elif outcome == 'ok_no_progress':
        record.update({'recovery_pending':False})
        candidate.write_text(json.dumps(record))
        failure = dispatch / 'last-failure.json'
        failure.write_text(json.dumps({'category':'repository_integrity_uncertainty','owner_action_required':False,'exact_next_action':'Repair missing progress evidence.'}))
    aggregate_errors = 0 if status == 'ok' else int(job['state'].get('consecutiveErrors', 0)) + 1
    job['state'].update({'lastRunAtMs':int(time.time() * 1000) + 10,'lastRunStatus':status,'lastStatus':status,'consecutiveErrors':aggregate_errors,'runningAtMs':None})
    if outcome == 'recoverable_then_disabled':
        job['enabled'] = False
    import sqlite3
    with sqlite3.connect(os.environ['FAKE_OPENCLAW_DB']) as connection:
        connection.execute('INSERT INTO cron_run_logs (job_id,seq,ts,status,run_at_ms,duration_ms) VALUES (?,?,?,?,?,?)', ('658ffdaf-1ac1-45a6-a842-f5f7d7a226eb',365 + run_number,int(time.time() * 1000),status,job['state']['lastRunAtMs'],10))
path.write_text(json.dumps(job))
print(json.dumps(job))
"""
                )
                fake.chmod(0o755)
                notification_log = root / "notification.log"
                openclaw_db = root / "openclaw.sqlite"
                with sqlite3.connect(openclaw_db) as connection:
                    connection.execute(
                        """CREATE TABLE cron_jobs (
                            job_id TEXT, name TEXT, enabled INTEGER,
                            delivery_channel TEXT, delivery_to TEXT,
                            delivery_account_id TEXT
                        )"""
                    )
                    connection.execute(
                        "INSERT INTO cron_jobs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            "8db8cc98-56a1-4687-9988-fd7e3750c51b",
                            "property-rental-visibility-watchdog",
                            1,
                            "telegram",
                            "test-sensitive-target",
                            "test-sensitive-account",
                        ),
                    )
                    connection.execute(
                        """CREATE TABLE cron_run_logs (
                            job_id TEXT, seq INTEGER, ts INTEGER, status TEXT,
                            run_at_ms INTEGER, duration_ms INTEGER
                        )"""
                    )
                    connection.execute(
                        "INSERT INTO cron_run_logs VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                            365,
                            1,
                            "error",
                            1,
                            10,
                        ),
                    )
                launchctl_log = root / "launchctl.log"
                cron_action_log = root / "cron-actions.log"
                fake_launchctl = root / "launchctl"
                fake_launchctl.write_text(
                    """#!/usr/bin/env python3
import os, pathlib, subprocess, sys
if sys.argv[1] == 'submit':
    separator = sys.argv.index('--')
    child_env = dict(os.environ)
    child_env['FAKE_SOURCE_PID'] = str(os.getppid())
    subprocess.Popen(
        sys.argv[separator + 1:],
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    raise SystemExit(0)
with pathlib.Path(os.environ['FAKE_LAUNCHCTL_LOG']).open('a') as handle:
    handle.write(' '.join(sys.argv[1:]) + '\\n')
if os.environ.get('FAKE_UNLOAD_FAIL') == '1' and not sys.argv[-1].endswith('.terminalizer'):
    raise SystemExit(7)
if os.environ.get('FAKE_TERMINATE_SOURCE') == '1' and not sys.argv[-1].endswith('.terminalizer'):
    os.kill(int(os.environ['FAKE_SOURCE_PID']), 15)
"""
                )
                fake_launchctl.chmod(0o755)
                evidence = root / "restoration.json"
                if natural_status == "ok":
                    spec = importlib.util.spec_from_file_location(
                        "resumable_post_exit",
                        ROOT / "scripts/openclaw-post-exit-restoration.py",
                    )
                    assert spec and spec.loader
                    resumable = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(resumable)
                    metadata_once = resumable.restoration_metadata(repo, repair_head)
                    self.assertEqual(
                        resumable.restoration_metadata(repo, repair_head), metadata_once
                    )
                result = subprocess.run(
                    [
                        "python3",
                        str(ROOT / "scripts/openclaw-post-exit-restoration.py"),
                        "run",
                        "--repo",
                        str(repo),
                        "--dispatch-state",
                        str(dispatch_state),
                        "--evidence",
                        str(evidence),
                        "--openclaw",
                        str(fake),
                        "--launchctl",
                        str(fake_launchctl),
                        "--github",
                        str(fake),
                        "--openclaw-db",
                        str(openclaw_db),
                        "--owner-pid",
                        "999999",
                        "--expected-repair-head",
                        repair_head,
                        "--notification-timeout",
                        "0.05",
                        "--poll",
                        "0.01",
                        "--overlap-timeout",
                        "1",
                        "--natural-run-timeout",
                        "1",
                    ],
                    cwd=repo,
                    env={
                        **os.environ,
                        "FAKE_JOB": str(job_path),
                        "FAKE_DISPATCH": str(dispatch_state),
                        "FAKE_NATURAL_STATUS": natural_status,
                        "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
                        "FAKE_NOTIFICATION_LOG": str(notification_log),
                        "FAKE_OPENCLAW_DB": str(openclaw_db),
                        "FAKE_CRON_ACTION_LOG": str(cron_action_log),
                        "FAKE_NOTIFICATION_FAIL": "1" if notification_failure else "0",
                        "FAKE_NOTIFICATION_HANG": "1" if notification_hang else "0",
                        "FAKE_UNLOAD_FAIL": "1" if unload_failure else "0",
                        "FAKE_TERMINATE_SOURCE": ("1" if terminate_source_on_unload else "0"),
                        "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                terminalizer_deadline = time.monotonic() + 2
                while time.monotonic() < terminalizer_deadline:
                    observed = json.loads(evidence.read_text())
                    if (
                        (observed.get("notification") or {}).get("delivery_status")
                        in {"delivered", "failed"}
                        and (observed.get("terminalizer") or {}).get("self_unload_requested_at")
                        and launchctl_log.exists()
                        and any(
                            line.endswith(".terminalizer")
                            for line in launchctl_log.read_text().splitlines()
                        )
                    ):
                        break
                    time.sleep(0.01)
                restored = json.loads(evidence.read_text())
                job = json.loads(job_path.read_text())
                if natural_status == "recoverable_then_ok":
                    metadata_head = subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                    ).strip()
                    metadata_paths = subprocess.check_output(
                        [
                            "git",
                            "diff-tree",
                            "--no-commit-id",
                            "--name-only",
                            "-r",
                            metadata_head,
                        ],
                        cwd=repo,
                        text=True,
                    ).splitlines()
                    self.assertEqual(metadata_paths, ["ops/STATE.json"])
                expected_complete = (
                    natural_status
                    in {
                        "ok",
                        "recoverable_then_ok",
                    }
                    and not unload_failure
                )
                if expected_complete:
                    self.assertEqual(
                        result.returncode,
                        -15 if terminate_source_on_unload else 0,
                        result.stderr,
                    )
                    self.assertEqual(restored["status"], "complete")
                    self.assertTrue(job["enabled"])
                    self.assertFalse(restored["v1_020_started"])
                    self.assertEqual(
                        restored["bounded_retry_progress"]["completed_implementation_substages"],
                        ["sign_in"],
                    )
                    fresh = json.loads(stale_candidate.read_text())
                    self.assertEqual(
                        fresh["routing_revision"],
                        "v1-019-sign-in-context-routing-v5",
                    )
                    self.assertEqual(fresh["candidate_base_commit"], restored["metadata_commit"])
                    self.assertEqual(fresh["completed_implementation_substages"], ["sign_in"])
                    self.assertFalse((dispatch_state / "last-failure.json").exists())
                    archived = list(
                        (dispatch_state / "superseded/v1-019-context-reservation").glob(
                            "candidate-*.json"
                        )
                    )
                    self.assertEqual(len(archived), 1)
                    self.assertTrue(
                        (
                            dispatch_state / "terminal/oversized_or_ceiling_stopped/stale.json"
                        ).exists()
                    )
                else:
                    self.assertEqual(result.returncode, 69)
                    self.assertEqual(restored["status"], "failed_closed")
                    self.assertEqual(
                        restored["owner_action_required"],
                        natural_status in {"protected", "exhausted"},
                    )
                    self.assertFalse(job["enabled"])
                    rerun = subprocess.run(
                        [
                            "python3",
                            str(ROOT / "scripts/openclaw-post-exit-restoration.py"),
                            "run",
                            "--repo",
                            str(repo),
                            "--dispatch-state",
                            str(dispatch_state),
                            "--evidence",
                            str(evidence),
                            "--openclaw",
                            str(fake),
                            "--launchctl",
                            str(fake_launchctl),
                            "--github",
                            str(fake),
                            "--openclaw-db",
                            str(openclaw_db),
                            "--owner-pid",
                            "999999",
                            "--expected-repair-head",
                            repair_head,
                            "--notification-timeout",
                            "0.05",
                        ],
                        cwd=repo,
                        env={
                            **os.environ,
                            "FAKE_JOB": str(job_path),
                            "FAKE_DISPATCH": str(dispatch_state),
                            "FAKE_NATURAL_STATUS": natural_status,
                            "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
                            "FAKE_NOTIFICATION_LOG": str(notification_log),
                            "FAKE_OPENCLAW_DB": str(openclaw_db),
                            "FAKE_CRON_ACTION_LOG": str(cron_action_log),
                            "FAKE_NOTIFICATION_FAIL": "1" if notification_failure else "0",
                            "FAKE_NOTIFICATION_HANG": "1" if notification_hang else "0",
                            "FAKE_UNLOAD_FAIL": "1" if unload_failure else "0",
                            "FAKE_TERMINATE_SOURCE": "0",
                            "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(rerun.returncode, 69)
                    self.assertEqual(json.loads(evidence.read_text())["status"], "failed_closed")
                    self.assertNotIn("pending_post_exit", evidence.read_text())
                final_evidence_text = evidence.read_text()
                final_evidence = json.loads(final_evidence_text)
                self.assertEqual(
                    final_evidence["notification"]["delivery_status"],
                    "failed" if notification_failure or notification_hang else "delivered",
                )
                expected_notification = [
                    *(
                        ["recovery_scheduled"]
                        if natural_status in {"recoverable_then_ok", "exhausted"}
                        else []
                    ),
                    "complete" if expected_complete else "failed_closed",
                ]
                self.assertEqual(notification_log.read_text().splitlines(), expected_notification)
                self.assertNotIn("test-sensitive-target", final_evidence_text)
                self.assertNotIn("test-sensitive-account", final_evidence_text)
                if natural_status == "recoverable_then_ok":
                    self.assertEqual(
                        [item["sequence"] for item in final_evidence["post_repair_runs"]],
                        [366, 367],
                    )
                    self.assertEqual(
                        final_evidence["recovery_notifications"][0]["sequence"],
                        366,
                    )
                    self.assertEqual(
                        final_evidence["post_repair_runs"][0]["aggregate_consecutive_errors"],
                        4,
                    )
                    self.assertTrue(job["enabled"])
                    self.assertEqual(cron_action_log.read_text().splitlines(), ["enable"])
                if natural_status == "recoverable_then_disabled":
                    self.assertIn(
                        "became disabled during the scheduled bounded recovery",
                        final_evidence["failure"],
                    )
                    self.assertEqual(final_evidence.get("recovery_notifications", []), [])
                    self.assertEqual(notification_log.read_text().splitlines(), ["failed_closed"])
                if natural_status == "exhausted":
                    self.assertEqual(
                        [item["sequence"] for item in final_evidence["post_repair_runs"]],
                        [366, 367],
                    )
                    self.assertEqual(
                        final_evidence["recovery_notifications"][0]["sequence"],
                        366,
                    )
                    self.assertFalse(job["enabled"])
                    self.assertEqual(cron_action_log.read_text().splitlines()[0], "enable")
                    self.assertIn("disable", cron_action_log.read_text().splitlines()[1:])
                if notification_hang:
                    self.assertEqual(
                        final_evidence["notification"]["failure"],
                        "OpenClaw Telegram message command timed out",
                    )
                if unload_failure:
                    self.assertEqual(final_evidence["unload_status"], "failed")
                    self.assertEqual(
                        final_evidence["restoration_result_before_terminal_failure"],
                        "complete",
                    )
                    self.assertFalse(job["enabled"])
                expected_target = f"bootout gui/{os.getuid()}/com.property-rental.post-exit-restoration.{repair_head[:12]}"
                launchctl_calls = launchctl_log.read_text().splitlines()
                expected_terminalizer_target = f"{expected_target}.terminalizer"
                self.assertTrue(
                    all(
                        call in {expected_target, expected_terminalizer_target}
                        for call in launchctl_calls
                    )
                )
                expected_pairs = 1 if expected_complete else 2
                self.assertEqual(launchctl_calls.count(expected_target), expected_pairs)
                self.assertEqual(
                    launchctl_calls.count(expected_terminalizer_target), expected_pairs
                )

    def test_current_context_incident_rebases_only_pending_sign_in_recovery(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "context_rebase_post_exit",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "tracked.txt").write_text("repair\n")
            (repo / "frontend/src").mkdir(parents=True)
            (repo / "frontend/src/App.tsx").write_text("baseline\n")
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "context repair"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            dispatch = root / "dispatch"
            pending_fingerprint = "a" * 64
            atomic_write_json(
                dispatch / "candidates/V1-019.json",
                {
                    "candidate": "V1-019",
                    "candidate_base_commit": restoration.INCIDENT_BASELINE,
                    "routing_revision": restoration.PRIOR_ROUTING_REVISION,
                    "stage": "implementation",
                    "completed_implementation_substages": [],
                    "expected_worktree_paths": [],
                    "recovery_pending": True,
                    "recovery_generation": 1,
                    "ceiling_recovery_attempts": {"sign_in": 1},
                    "pending_recovery_marker_fingerprint": pending_fingerprint,
                    "model_usage": [
                        {
                            "session_id": restoration.CONTEXT_INCIDENT_SESSION_ID,
                            "api_calls_started": 2,
                            "api_calls_completed": 2,
                            "input_token_usage": 16_881,
                            "output_token_usage": 422,
                            "total_token_usage": 17_303,
                            "cache_read_token_usage": 9_216,
                            "predicted_next_context_tokens": 109_152,
                            "in_flight_overshoot_tokens": 0,
                            "unsupported_provider_parameters_removed": [],
                        }
                    ],
                    "events": [],
                },
            )
            atomic_write_json(
                dispatch / "attempts/V1-019.json",
                {
                    "fingerprint": pending_fingerprint,
                    "counters": {"implementation": 1},
                    "pending": None,
                },
            )
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "model_session_or_token_ceiling",
                    "owner_action_required": False,
                },
            )
            atomic_write_json(
                dispatch / f"terminal/routing_recovery_pending/{pending_fingerprint}.json",
                {
                    "status": "routing_recovery_pending",
                    "actionable_fingerprint": pending_fingerprint,
                    "phase": "sign_in",
                    "attempt": 1,
                },
            )
            result = restoration.rebase_scheduled_v1_019_recovery(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(result["status"], "pending_sign_in_recovery_rebased")
            record = json.loads((dispatch / "candidates/V1-019.json").read_text())
            self.assertEqual(record["routing_revision"], restoration.ROUTING_REVISION)
            self.assertEqual(record["candidate_base_commit"], head)
            self.assertTrue(record["recovery_pending"])
            self.assertEqual(record["recovery_generation"], 1)
            self.assertEqual(record["ceiling_recovery_attempts"], {"sign_in": 1})
            self.assertEqual(record["completed_implementation_substages"], [])
            partial = repo / "frontend/src/App.tsx"
            partial.write_text("export {}\n")
            record["expected_worktree_paths"] = ["frontend/src/App.tsx"]
            record["repository_fingerprint"] = repository_fingerprint(repo)
            atomic_write_json(dispatch / "candidates/V1-019.json", record)
            partial_resume = restoration.rebase_scheduled_v1_019_recovery(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(partial_resume["status"], "already_rebased")
            partial.write_text("baseline\n")
            record["expected_worktree_paths"] = []
            record["repository_fingerprint"] = repository_fingerprint(repo)
            atomic_write_json(dispatch / "candidates/V1-019.json", record)
            resumed = restoration.rebase_scheduled_v1_019_recovery(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(resumed["status"], "already_rebased")
            record = json.loads((dispatch / "candidates/V1-019.json").read_text())
            record.update(
                {
                    "ceiling_recovery_attempts": {"sign_in": 1},
                    "context_materialization_attempts": {"sign_in": 1},
                    "recovery_generation": 2,
                    "pending_recovery_marker_fingerprint": "b" * 64,
                    "pending_recovery_marker_status": "context_materialization_pending",
                }
            )
            atomic_write_json(dispatch / "candidates/V1-019.json", record)
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "context_materialization_required",
                    "owner_action_required": False,
                },
            )
            atomic_write_json(
                dispatch / f"terminal/context_materialization_pending/{'b' * 64}.json",
                {
                    "status": "context_materialization_pending",
                    "actionable_fingerprint": "b" * 64,
                    "phase": "sign_in",
                    "attempt": 1,
                },
            )
            resumed_materialization = restoration.rebase_scheduled_v1_019_recovery(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(resumed_materialization["status"], "already_rebased")
            failure_path = dispatch / "last-failure.json"
            failure = json.loads(failure_path.read_text())
            failure["owner_action_required"] = True
            atomic_write_json(failure_path, failure)
            with self.assertRaisesRegex(restoration.RestorationError, "already-rebased.*drifted"):
                restoration.rebase_scheduled_v1_019_recovery(
                    repo, dispatch, candidate_base_commit=head
                )

    def test_exact_policy_rejection_loop_rebases_without_new_owner_or_attempt(
        self,
    ) -> None:
        spec = importlib.util.spec_from_file_location(
            "policy_rejection_post_exit",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "frontend/src").mkdir(parents=True)
            incident_paths = sorted(
                {
                    "frontend/src/App.tsx",
                    "frontend/src/App.test.tsx",
                    "frontend/src/styles.css",
                    "frontend/src/authClient.ts",
                    "frontend/src/authClient.test.ts",
                }
            )
            corrected_contents = {
                relative: f"corrected {relative}\n".encode()
                for relative in restoration.POLICY_REJECTION_CORRECTED_PATH_HASHES
            }
            restoration.POLICY_REJECTION_CORRECTED_PATH_HASHES = {
                relative: hashlib.sha256(content).hexdigest()
                for relative, content in corrected_contents.items()
            }
            corrected_paths = sorted(corrected_contents)
            for relative in corrected_paths:
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("baseline\n")
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "repair"], cwd=repo, check=True)
            for relative, content in corrected_contents.items():
                (repo / relative).write_bytes(content)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            dispatch = root / "dispatch"
            usage = [
                {"session_id": session_id}
                for session_id in restoration.POLICY_REJECTION_SESSIONS[:-1]
            ]
            usage.append(
                {
                    "session_id": restoration.POLICY_REJECTION_SESSIONS[-1],
                    "api_calls_started": 2,
                    "api_calls_completed": 2,
                    "input_token_usage": 31_983,
                    "output_token_usage": 1_059,
                    "total_token_usage": 33_042,
                    "cache_read_token_usage": 15_360,
                    "tool_output_batch_rejections": 1,
                    "tool_output_control_bytes": 504,
                    "context_materialization_checkpoint": True,
                }
            )
            candidate = {
                "candidate": "V1-019",
                "candidate_base_commit": restoration.POLICY_REJECTION_INCIDENT_BASELINE,
                "routing_revision": restoration.POLICY_REJECTION_ROUTING_REVISION,
                "stage": "implementation",
                "completed_implementation_substages": [],
                "expected_worktree_paths": incident_paths,
                "repository_fingerprint": restoration.POLICY_REJECTION_REPOSITORY_FINGERPRINT,
                "recovery_pending": True,
                "recovery_generation": 4,
                "ceiling_recovery_attempts": {"sign_in": 1},
                "context_materialization_attempts": {"sign_in": 2},
                "pending_recovery_marker_status": "context_materialization_pending",
                "pending_recovery_marker_fingerprint": restoration.POLICY_REJECTION_PENDING_FINGERPRINT,
                "bounded_recovery_exhausted": False,
                "stop_reason": "context_materialization_required",
                "preserved_partial_work": {
                    "paths": incident_paths,
                    "repository_fingerprint": restoration.POLICY_REJECTION_REPOSITORY_FINGERPRINT,
                },
                "owner_authorized_fresh_sign_in_sequence": {
                    "consumed": True,
                    "transition_status": "complete",
                },
                "model_stage_policy": {
                    "repository_fingerprint": restoration.POLICY_REJECTION_REPOSITORY_FINGERPRINT,
                },
                "model_usage": usage,
                "events": [],
            }
            atomic_write_json(dispatch / "candidates/V1-019.json", candidate)
            atomic_write_json(
                dispatch / "attempts/V1-019.json",
                {
                    "fingerprint": restoration.POLICY_REJECTION_PENDING_FINGERPRINT,
                    "counters": {"implementation": 1},
                    "pending": None,
                },
            )
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "context_materialization_required",
                    "owner_action_required": False,
                    "repository_fingerprint": restoration.POLICY_REJECTION_REPOSITORY_FINGERPRINT,
                },
            )
            atomic_write_json(
                dispatch
                / "terminal/context_materialization_pending"
                / f"{restoration.POLICY_REJECTION_PENDING_FINGERPRINT}.json",
                {
                    "status": "context_materialization_pending",
                    "phase": "sign_in",
                    "attempt": 2,
                    "actionable_fingerprint": restoration.POLICY_REJECTION_PENDING_FINGERPRINT,
                },
            )
            self.assertTrue(restoration.policy_rejection_rebase_required(dispatch, candidate))
            self.assertTrue(restoration.policy_rejection_corrected_worktree(repo))
            result = restoration.rebase_scheduled_v1_019_recovery(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(
                result["status"],
                "pending_sign_in_policy_rejection_recovery_rebased",
            )
            rebound = json.loads((dispatch / "candidates/V1-019.json").read_text())
            self.assertEqual(rebound["routing_revision"], restoration.ROUTING_REVISION)
            self.assertEqual(rebound["candidate_base_commit"], head)
            self.assertEqual(rebound["expected_worktree_paths"], corrected_paths)
            self.assertEqual(rebound["ceiling_recovery_attempts"], {"sign_in": 1})
            self.assertEqual(rebound["context_materialization_attempts"], {"sign_in": 2})
            self.assertTrue(rebound["recovery_pending"])
            self.assertFalse(rebound["bounded_recovery_exhausted"])
            self.assertEqual(
                json.loads((dispatch / "attempts/V1-019.json").read_text())["counters"],
                {"implementation": 1},
            )

    def test_exact_exhausted_sign_in_is_archived_and_authorized_once(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "exhausted_rebase_post_exit",
            ROOT / "scripts/openclaw-post-exit-restoration.py",
        )
        assert spec and spec.loader
        restoration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restoration)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "tracked.txt").write_text("routing v4\n")
            (repo / "frontend/src").mkdir(parents=True)
            (repo / "frontend/src/App.tsx").write_text("baseline\n")
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "routing v4"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            dispatch = root / "dispatch"
            usage = [
                {
                    "session_id": session_id,
                    "stage_result": "model_session_or_token_ceiling",
                }
                for session_id in restoration.EXHAUSTED_SIGN_IN_SESSIONS
            ]
            atomic_write_json(
                dispatch / "candidates/V1-019.json",
                {
                    "candidate": "V1-019",
                    "candidate_base_commit": "old",
                    "routing_revision": restoration.EXHAUSTED_ROUTING_REVISION,
                    "stage": "implementation",
                    "completed_implementation_substages": [],
                    "expected_worktree_paths": [],
                    "bounded_recovery_exhausted": True,
                    "recovery_pending": False,
                    "ceiling_recovery_attempts": {"sign_in": 3},
                    "model_usage": usage,
                },
            )
            atomic_write_json(
                dispatch / "attempts/V1-019.json",
                {
                    "fingerprint": restoration.EXHAUSTED_SIGN_IN_FINGERPRINT,
                    "counters": {"implementation": 1},
                    "pending": None,
                },
            )
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "model_session_or_token_ceiling",
                    "actionable_fingerprint": restoration.EXHAUSTED_SIGN_IN_FINGERPRINT,
                    "owner_action_required": True,
                },
            )
            atomic_write_json(
                dispatch
                / "terminal/repair_exhausted"
                / f"{restoration.EXHAUSTED_SIGN_IN_FINGERPRINT}.json",
                {
                    "status": "repair_exhausted",
                    "phase": "sign_in",
                    "attempts": 3,
                    "actionable_fingerprint": restoration.EXHAUSTED_SIGN_IN_FINGERPRINT,
                },
            )
            for session_id in restoration.EXHAUSTED_SIGN_IN_SESSIONS:
                atomic_write_json(
                    dispatch / f"budgets/V1-019-implementation-{session_id}.json",
                    {"schema_version": 1, "session_id": session_id},
                )
                atomic_write_json(
                    dispatch / f"usage/V1-019-implementation-{session_id}.json",
                    {"session_id": session_id},
                )
                for relative in (
                    f"hermes-sessions/{session_id}/hermes.stderr",
                    f"hermes-sessions/{session_id}/logs/agent.log",
                    f"hermes-sessions/{session_id}/logs/errors.log",
                    f"hermes-sessions/{session_id}/state.db",
                ):
                    artifact = dispatch / relative
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    artifact.write_text(f"{session_id}:{relative}\n")
                task = dispatch / f"tasks/V1-019-implementation-{session_id}.json"
                atomic_write_json(task, {"session_id": session_id})
                atomic_write_json(
                    dispatch / f"manifests/V1-019-implementation-{session_id}.json",
                    {"session_id": session_id, "task_path": str(task)},
                )
            artifacts = restoration._exhausted_incident_artifacts(dispatch)
            self.assertEqual(len(artifacts), 24)
            missing = dispatch / (
                f"hermes-sessions/{restoration.EXHAUSTED_SIGN_IN_SESSIONS[0]}/logs/errors.log"
            )
            preserved_missing = missing.read_text()
            missing.unlink()
            with self.assertRaisesRegex(
                restoration.RestorationError, "historical Hermes artifact is missing"
            ):
                restoration._exhausted_incident_artifacts(dispatch)
            missing.write_text(preserved_missing)

            extra_usage = [*usage, {"session_id": "unexpected-session"}]
            candidate_path = dispatch / "candidates/V1-019.json"
            candidate_value = json.loads(candidate_path.read_text())
            candidate_value["model_usage"] = extra_usage
            atomic_write_json(candidate_path, candidate_value)
            with self.assertRaisesRegex(
                restoration.RestorationError,
                "exact authorized exhausted sign-in incident",
            ):
                restoration.validate_exhausted_v1_019_sign_in(dispatch)
            candidate_value["model_usage"] = usage
            atomic_write_json(candidate_path, candidate_value)

            artifact = dispatch / (
                f"hermes-sessions/{restoration.EXHAUSTED_SIGN_IN_SESSIONS[0]}/logs/errors.log"
            )
            artifact_content = artifact.read_text()
            artifact.unlink()
            outside = root / "outside-artifact"
            outside.write_text(artifact_content)
            artifact.symlink_to(outside)
            with self.assertRaisesRegex(
                restoration.RestorationError,
                "escaped its boundary|not an exact regular file",
            ):
                restoration._exhausted_incident_artifacts(dispatch)
            artifact.unlink()
            artifact.write_text(artifact_content)

            manifests = dispatch / "manifests"
            preserved_manifests = root / "preserved-manifests"
            outside_manifests = root / "outside-manifests"
            manifests.rename(preserved_manifests)
            shutil.copytree(preserved_manifests, outside_manifests)
            manifests.symlink_to(outside_manifests, target_is_directory=True)
            with self.assertRaisesRegex(
                restoration.RestorationError, "manifest escaped its boundary"
            ):
                restoration._exhausted_incident_artifacts(dispatch)
            manifests.unlink()
            preserved_manifests.rename(manifests)

            original_unlink = Path.unlink
            unlink_count = 0
            live_cleanup_paths = {
                dispatch / "attempts/V1-019.json",
                dispatch / "last-failure.json",
                dispatch
                / "terminal/repair_exhausted"
                / f"{restoration.EXHAUSTED_SIGN_IN_FINGERPRINT}.json",
            }
            resolved_live_cleanup_paths = {path.resolve() for path in live_cleanup_paths}
            compact_marker = next(
                path for path in live_cleanup_paths if "repair_exhausted" in path.parts
            )
            compact_marker.write_text(
                json.dumps(json.loads(compact_marker.read_text()), separators=(",", ":"))
            )

            def interrupt_second_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
                nonlocal unlink_count
                if path.resolve() in resolved_live_cleanup_paths:
                    unlink_count += 1
                    if unlink_count == 2:
                        raise OSError("simulated transition interruption")
                original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "unlink", new=interrupt_second_unlink),
                self.assertRaisesRegex(OSError, "simulated transition interruption"),
            ):
                restoration.rebase_exhausted_v1_019_sign_in(
                    repo, dispatch, candidate_base_commit=head
                )
            pending = json.loads((dispatch / "candidates/V1-019.json").read_text())
            self.assertTrue(restoration.exhausted_rebase_required(pending))
            self.assertEqual(
                pending["owner_authorized_fresh_sign_in_sequence"]["transition_status"],
                "cleanup_pending",
            )
            for retry_failure in (
                "live exhausted sign-in evidence differs from its archive",
                "published restoration metadata does not match its exact resumable contract",
                "restoration metadata changed unexpected repository paths",
            ):
                prior_cleanup_failure = {
                    "status": "failed_closed",
                    "failure": retry_failure,
                    "recovery_state": "terminal_failure",
                    "owner_action_required": False,
                }
                self.assertTrue(
                    restoration.interrupted_exhausted_cleanup_install_required(
                        prior_cleanup_failure, dispatch
                    )
                )
            remaining_failure = dispatch / "last-failure.json"
            remaining_failure_value = remaining_failure.read_text()
            remaining_failure.unlink()
            remaining_failure.symlink_to(root / "missing-live-cleanup-evidence")
            self.assertFalse(
                restoration.interrupted_exhausted_cleanup_install_required(
                    prior_cleanup_failure, dispatch
                )
            )
            remaining_failure.unlink()
            remaining_failure.write_text(remaining_failure_value)
            (repo / "tracked.txt").write_text("routing v4 follow-up\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "cleanup comparison follow-up"],
                cwd=repo,
                check=True,
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            result = restoration.rebase_exhausted_v1_019_sign_in(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(result["status"], "cleanup_rebased_after_follow_up_repair")
            record = json.loads((dispatch / "candidates/V1-019.json").read_text())
            self.assertEqual(record["routing_revision"], restoration.ROUTING_REVISION)
            self.assertTrue(record["recovery_pending"])
            self.assertEqual(record["ceiling_recovery_attempts"], {})
            self.assertEqual(record["context_materialization_attempts"], {})
            self.assertTrue(record["owner_authorized_fresh_sign_in_sequence"]["consumed"])
            self.assertEqual(
                record["owner_authorized_fresh_sign_in_sequence"]["transition_status"],
                "complete",
            )
            self.assertFalse((dispatch / "attempts/V1-019.json").exists())
            self.assertFalse((dispatch / "last-failure.json").exists())
            self.assertFalse(
                (
                    dispatch
                    / "terminal/repair_exhausted"
                    / f"{restoration.EXHAUSTED_SIGN_IN_FINGERPRINT}.json"
                ).exists()
            )
            archive = Path(result["archive"])
            self.assertTrue((archive / "candidate.json").is_file())
            index = json.loads((archive / "artifact-index.json").read_text())
            self.assertEqual(index["sessions"], list(restoration.EXHAUSTED_SIGN_IN_SESSIONS))
            self.assertEqual(len(index["artifacts"]), 24)
            resumed = restoration.rebase_exhausted_v1_019_sign_in(
                repo, dispatch, candidate_base_commit=head
            )
            self.assertEqual(resumed["status"], "already_rebased_from_exhaustion")
            self.assertFalse(restoration.exhausted_rebase_required(record))
            self.assertTrue(restoration.eligible_bounded_recovery(dispatch)["eligible"])
            self.assertTrue(restoration.cleaned_fresh_sequence_resume_required(dispatch, record))
            crash_window_resume = restoration.resume_cleaned_fresh_sequence(
                repo,
                dispatch,
                record,
                candidate_base_commit=head,
            )
            self.assertEqual(crash_window_resume["status"], "cleaned_fresh_sequence_resumed")
            self.assertTrue(restoration.eligible_bounded_recovery(dispatch)["eligible"])
            atomic_write_json(
                dispatch / "attempts/V1-019.json",
                {
                    "fingerprint": "e" * 64,
                    "counters": {},
                    "pending": {"stage": "implementation", "reserved_at": "now"},
                },
            )
            partial = repo / "frontend/src/App.tsx"
            partial.write_text("export {}\n")
            record = json.loads((dispatch / "candidates/V1-019.json").read_text())
            interrupted = restoration.resume_cleaned_fresh_sequence(
                repo,
                dispatch,
                record,
                candidate_base_commit=head,
            )
            self.assertEqual(interrupted["status"], "interrupted_fresh_sequence_resumed")
            rebound = json.loads((dispatch / "candidates/V1-019.json").read_text())
            self.assertEqual(rebound["expected_worktree_paths"], ["frontend/src/App.tsx"])
            partial.write_text("baseline\n")
            rebound["expected_worktree_paths"] = []
            rebound["repository_fingerprint"] = repository_fingerprint(repo)
            atomic_write_json(dispatch / "candidates/V1-019.json", rebound)
            (dispatch / "attempts/V1-019.json").unlink()
            for category in (
                "pre_model_infrastructure_failure",
                "unsupported_invocation_configuration",
                "lock_or_overlapping_process_failure",
            ):
                atomic_write_json(
                    dispatch / "last-failure.json",
                    {
                        "category": category,
                        "owner_action_required": False,
                        "exact_next_action": "retry without consuming a model attempt",
                    },
                )
                recovery = restoration.eligible_bounded_recovery(dispatch)
                self.assertTrue(recovery["eligible"], category)
                self.assertTrue(recovery["owner_authorized_fresh_sequence"], category)
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "repository_integrity_uncertainty",
                    "owner_action_required": False,
                    "exact_next_action": "stop",
                },
            )
            self.assertFalse(restoration.eligible_bounded_recovery(dispatch)["eligible"])

            pending_fingerprint = "d" * 64
            record = json.loads((dispatch / "candidates/V1-019.json").read_text())
            record.update(
                {
                    "ceiling_recovery_attempts": {"sign_in": 1},
                    "context_materialization_attempts": {},
                    "recovery_generation": 2,
                    "pending_recovery_marker_fingerprint": pending_fingerprint,
                    "pending_recovery_marker_status": "routing_recovery_pending",
                }
            )
            atomic_write_json(dispatch / "candidates/V1-019.json", record)
            atomic_write_json(
                dispatch / "attempts/V1-019.json",
                {
                    "fingerprint": pending_fingerprint,
                    "counters": {"implementation": 1},
                    "pending": None,
                },
            )
            atomic_write_json(
                dispatch / "last-failure.json",
                {
                    "category": "model_session_or_token_ceiling",
                    "owner_action_required": False,
                },
            )
            self.assertFalse(restoration.exhausted_rebase_required(record))
            with self.assertRaisesRegex(
                restoration.RestorationError,
                "pending V1-019 recovery marker is missing",
            ):
                restoration.rebase_scheduled_v1_019_recovery(
                    repo, dispatch, candidate_base_commit=head
                )

    def test_atomic_lock_fails_closed_for_unprovable_owner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cycle.lock"
            path.touch()
            path.with_suffix(".owner.json").write_text("not-json\n")
            with self.assertRaisesRegex(AutomationError, "unreadable or unprovable"):
                self.dispatch.CycleLock(path).__enter__()

    def test_remote_sha_equality_is_required_after_publication(self) -> None:
        with (
            mock.patch.object(
                self.dispatch,
                "git",
                side_effect=["implementation/foundation", "local", "upstream"],
            ),
            mock.patch.object(
                self.dispatch,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "remote\tref\n", ""),
            ),
            self.assertRaisesRegex(AutomationError, "not equal"),
        ):
            self.dispatch.synchronized_repository_shas()

    def test_capability_only_continuation_requires_exact_preserved_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            candidate_path = repo / "candidate.txt"
            candidate_path.write_text("baseline\n")
            (repo / "ops/QUEUE.md").write_text(
                "Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.\n"
            )
            subprocess.run(
                ["git", "add", "--", "candidate.txt", "ops/QUEUE.md"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "preservation baseline"],
                cwd=repo,
                check=True,
            )
            baseline = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            desired_state = json.loads((repo / "ops/STATE.json").read_text())
            desired_state.update(
                {
                    "branch": "main",
                    "commit": baseline,
                    "status": "partial",
                    "owner_action": "none",
                    "blockers": [{"category": "verification_tooling_unavailable"}],
                    "approval": {
                        "status": "approved_ready",
                        "implementation_started": True,
                        "implementation_completed": False,
                        "publication_completed": False,
                    },
                    "repair": {
                        "tranche_id": "V1-018",
                        "failure": "verification_tooling_unavailable",
                        "scope_preserved": True,
                        "attempts": 0,
                        "max_attempts": 2,
                        "requires_owner_decision": False,
                        "suspected_secret": False,
                        "scope_expansion": False,
                        "protected_operation": False,
                    },
                    "tests": ["PASS: focused implementation checks"],
                }
            )
            atomic_write_json(repo / "ops/STATE.json", desired_state)
            candidate_path.write_text("preserved implementation\n")
            evidence = {
                "schema_version": 1,
                "candidate": "V1-018",
                "baseline_branch": "main",
                "baseline_head": baseline,
                "preserved_paths": {
                    "candidate.txt": digest(candidate_path.read_bytes()),
                    "ops/STATE.json": digest((repo / "ops/STATE.json").read_bytes()),
                },
                "automation_repair_may_modify_preserved_paths": False,
                "v1_019_may_start": False,
            }
            atomic_write_json(repo / "ops/AUTOMATION_REPAIR_EVIDENCE.json", evidence)
            subprocess.run(
                ["git", "add", "--", "ops/AUTOMATION_REPAIR_EVIDENCE.json"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "record preservation evidence"],
                cwd=repo,
                check=True,
            )
            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", str(origin)],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "push", "-qu", "-u", "origin", "HEAD"],
                cwd=repo,
                check=True,
            )
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                classified = classify_compact_state(repo)
            self.assertEqual(classified["lifecycle"], "verification_pending")
            self.assertEqual(classified["state_issue"], "capability_verification_continuation")
            self.assertFalse(classified["implementation_allowed"])
            self.assertTrue(classified["preservation_valid"])
            self.assertTrue(classified["exact_identity"]["no_failed_check"])
            self.assertTrue(classified["exact_identity"]["no_overlap"])

            spec = importlib.util.spec_from_file_location(
                "capability_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "dispatch"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(dispatcher)
                record = {
                    "candidate": "V1-018",
                    "stage": "implementation",
                }
                with mock.patch.object(dispatcher, "invoke_model") as invoked:
                    dispatcher.bootstrap_completed_candidate(
                        record, require_preserved_identity=True
                    )
            invoked.assert_not_called()
            self.assertEqual(record["stage"], "deterministic_verification")
            self.assertEqual(record["scoped_changed_paths"], ["candidate.txt", "ops/STATE.json"])

            candidate_path.write_text("drifted implementation\n")
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                drifted = classify_compact_state(repo)
            self.assertNotEqual(drifted["state_issue"], "capability_verification_continuation")
            self.assertFalse(drifted["preservation_valid"])

    def test_genuine_owner_category_remains_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = RepositoryEvidenceTests().make_repo(Path(directory))
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update({"owner_action": "confirm protected credential rotation"})
            state["approval"] = {
                "status": "approved_ready",
                "implementation_started": True,
                "implementation_completed": False,
                "publication_completed": False,
            }
            state["repair"] = {
                "tranche_id": "V1-018",
                "failure": "suspected secret",
                "scope_preserved": True,
                "attempts": 0,
                "max_attempts": 2,
                "requires_owner_decision": True,
                "suspected_secret": True,
                "scope_expansion": False,
                "protected_operation": False,
            }
            atomic_write_json(repo / "ops/STATE.json", state)
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                classified = classify_compact_state(repo)
            self.assertEqual(classified["lifecycle"], "owner_blocked")
            self.assertEqual(
                classified["blocker_category"],
                "secret_credential_or_protected_operation",
            )
            self.assertTrue(classified["owner_action_required"])
            self.assertFalse(classified["actionable"])
            state["status"] = "verified_unpublished"
            state["approval"]["implementation_completed"] = True
            atomic_write_json(repo / "ops/STATE.json", state)
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                verified_but_blocked = classify_compact_state(repo)
            self.assertEqual(verified_but_blocked["lifecycle"], "owner_blocked")
            self.assertEqual(
                verified_but_blocked["blocker_category"],
                "secret_credential_or_protected_operation",
            )
            self.assertFalse(verified_but_blocked["actionable"])

    def test_structured_owner_categories_and_test_blockers_route_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = RepositoryEvidenceTests().make_repo(Path(directory))
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update(
                {
                    "status": "failed",
                    "owner_action": "none",
                    "blockers": [{"category": "conflicting_owner_work"}],
                    "approval": {
                        "status": "approved_ready",
                        "implementation_started": True,
                        "implementation_completed": False,
                        "publication_completed": False,
                    },
                    "repair": {
                        "tranche_id": "V1-018",
                        "failure": "conflicting_owner_work",
                        "scope_preserved": True,
                        "attempts": 0,
                        "max_attempts": 2,
                        "requires_owner_decision": False,
                        "suspected_secret": False,
                        "scope_expansion": False,
                        "protected_operation": False,
                    },
                }
            )
            atomic_write_json(repo / "ops/STATE.json", state)
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                owner = classify_compact_state(repo)
            self.assertEqual(owner["lifecycle"], "owner_blocked")
            self.assertEqual(owner["blocker_category"], "conflicting_owner_work")
            self.assertTrue(owner["owner_action_required"])

            state["blockers"] = ["backend focused test failed"]
            state["repair"]["failure"] = "deterministic_test_failure"
            atomic_write_json(repo / "ops/STATE.json", state)
            with mock.patch.dict(os.environ, {"PROPERTY_RENTAL_TEST_PROCESS_ROWS": ""}):
                repair = classify_compact_state(repo)
            self.assertEqual(repair["lifecycle"], "bounded_repair_pending")
            self.assertEqual(repair["state_issue"], "bounded_automatic_repair_authorized")
            self.assertTrue(repair["actionable"])
            self.assertFalse(repair["owner_action_required"])

    def test_v1_019_terminal_scope_holds_v1_020_without_owner_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = RepositoryEvidenceTests().make_repo(Path(directory))
            (repo / "ops/QUEUE.md").write_text(
                "Remaining v1 application tranches are authorized when bounded by canonical documents 001-010.\n"
            )
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.update(
                {
                    "status": "published",
                    "roadmap": {"current_id": "V1-019", "total": 60},
                    "next_candidate": {
                        "id": "V1-019",
                        "roadmap_id": "V1-019",
                        "phase": "Identity",
                        "task": "Authentication UI",
                        "status": "complete",
                    },
                    "approval": {
                        "status": "approved_complete",
                        "implementation_started": True,
                        "implementation_completed": True,
                        "publication_completed": True,
                    },
                    "automation_repair": {
                        "status": "restored",
                        "stop_after_candidate": "V1-019",
                    },
                }
            )
            atomic_write_json(repo / "ops/STATE.json", state)
            atomic_write_json(
                repo / "ops/V1_ROADMAP.json",
                {
                    "total_tranches": 60,
                    "tranches": [
                        {"id": "V1-019", "order": 19, "status": "complete"},
                        {
                            "id": "V1-020",
                            "order": 20,
                            "phase": "Identity",
                            "task": "Identity hardening",
                            "status": "approved_ready",
                            "authorization": "durable_v1",
                            "dependencies": ["V1-019"],
                        },
                    ],
                },
            )
            classified = classify_compact_state(repo)
            self.assertFalse(classified["actionable"])
            self.assertFalse(classified["owner_action_required"])
            self.assertEqual(classified["state_issue"], "successor_held_by_approved_scope")
            self.assertEqual(classified["queue_candidate"]["id"], "V1-020")

    def test_installed_openai_codex_contract_uses_local_reservation_without_unsupported_parameter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "ceiling": 60_000,
                    "api_calls_started": 0,
                    "api_calls_completed": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_tokens": 0,
                    "counted_total_tokens": 0,
                    "boundary_reached": False,
                    "in_flight_overshoot_tokens": 0,
                    "next_api_call_blocked": False,
                },
            )
            atomic_write_json(manifest_path, {"budget_path": str(budget_path)})
            responses = iter(
                [
                    {
                        "model": "gpt-5.6-sol",
                        "usage": {
                            "input_tokens": 12_000,
                            "output_tokens": 4_000,
                            "cache_read_tokens": 8_000,
                        },
                    },
                    {
                        "model": "gpt-5.6-sol",
                        "usage": {
                            "input_tokens": 18_000,
                            "output_tokens": 4_000,
                            "cache_read_tokens": 4_000,
                        },
                    },
                ]
            )
            observed_requests: list[dict[str, Any]] = []

            def invoke(request: dict[str, Any]) -> dict[str, Any]:
                observed_requests.append(request)
                return next(responses)

            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                enforce_llm_call({"max_output_tokens": 40_000}, invoke)
                enforce_llm_call({"max_output_tokens": 40_000}, invoke)
                with self.assertRaisesRegex(GuardError, "PROACTIVE_BUDGET_RESERVATION_STOP"):
                    enforce_llm_call({"max_output_tokens": 40_000}, invoke)
            self.assertEqual(len(observed_requests), 2)
            self.assertTrue(
                all("max_output_tokens" not in request for request in observed_requests)
            )
            budget = json.loads(budget_path.read_text())
            self.assertEqual(budget["api_calls_started"], 2)
            self.assertEqual(budget["api_calls_completed"], 2)
            self.assertEqual(budget["counted_total_tokens"], 38_000)
            self.assertEqual(budget["cache_read_tokens"], 12_000)
            self.assertEqual(budget["in_flight_overshoot_tokens"], 0)
            self.assertFalse(budget["boundary_reached"])
            self.assertTrue(budget["reservation_blocked"])
            self.assertFalse(budget["reservation_violation"])
            self.assertTrue(budget["next_api_call_blocked"])
            self.assertEqual(
                budget["provider_completion_limit_mode"],
                "local_proactive_reservation",
            )
            self.assertTrue(budget["provider_request_omits_max_output_tokens"])
            self.assertEqual(
                budget["unsupported_provider_parameters_removed"],
                ["max_output_tokens"],
            )
            self.assertGreaterEqual(budget["locally_reserved_next_call_tokens"], 2_048)

    def test_exact_v1_019_packet_and_observed_outputs_do_not_false_reserve(
        self,
    ) -> None:
        packet = base64.b64decode(
            (ROOT / "scripts/test-fixtures/v1-019-sign-in-packet-9614.b64").read_text()
        )
        self.assertEqual(len(packet), 9_614)
        self.assertEqual(
            digest(packet),
            "2a6e8126bc9c285f5f400137ab0b97dc87c4c1ca7b40523591128a387d9ccc3b",
        )
        observed_tool_output_sizes = [
            639,
            4_202,
            26_386,
            4_508,
            16_595,
            127,
            153,
            194,
            56,
            57,
            5_333,
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "ceiling": 60_000,
                    "api_calls_started": 2,
                    "api_calls_completed": 2,
                    "input_tokens": 16_881,
                    "output_tokens": 422,
                    "cache_read_tokens": 9_216,
                    "reasoning_tokens": 60,
                    "counted_total_tokens": 17_303,
                    "last_call_input_tokens": 8_613,
                    "last_call_output_tokens": 250,
                    "boundary_reached": False,
                    "in_flight_overshoot_tokens": 0,
                    "next_api_call_blocked": False,
                    "reserved_completion_checkpoint_tokens": 2_048,
                    "context_reservation_margin_tokens": 1_024,
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_truncations": 0,
                },
            )
            atomic_write_json(
                manifest_path,
                {
                    "budget_path": str(budget_path),
                    "bounded_substage_id": "sign_in",
                },
            )
            provider_calls = 0

            def provider(_: dict[str, Any]) -> dict[str, Any]:
                nonlocal provider_calls
                provider_calls += 1
                return {
                    "model": "gpt-5.6-sol",
                    "usage": {
                        "input_tokens": 18_000,
                        "output_tokens": 500,
                        "cache_read_tokens": 9_000,
                    },
                }

            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                bounded_outputs = [
                    bounded_tool_output("read_file", "x" * size)
                    for size in observed_tool_output_sizes
                ]
                request = {
                    "messages": [
                        {"role": "user", "content": packet.decode()},
                        *[
                            {
                                "role": "tool",
                                "tool_call_id": f"observed-{index}",
                                "content": content,
                            }
                            for index, content in enumerate(bounded_outputs)
                        ],
                    ],
                    "tools": [{"type": "function", "name": "read_file"}],
                }
                enforce_llm_call(request, provider)
            budget = json.loads(budget_path.read_text())
            self.assertEqual(provider_calls, 1)
            self.assertLess(budget["predicted_next_context_tokens"], 42_697)
            self.assertNotEqual(budget["predicted_next_context_tokens"], 109_152)
            self.assertEqual(
                budget["token_estimate_method"],
                "validated_serialized_request_estimate_v1",
            )
            self.assertEqual(budget["token_estimate_inputs"]["validation_margin_tokens"], 1_024)
            self.assertEqual(budget["in_flight_overshoot_tokens"], 0)
            self.assertEqual(budget["tool_output_observed_bytes"], sum(observed_tool_output_sizes))
            self.assertLessEqual(budget["tool_output_returned_bytes"], 36_000)
            self.assertGreater(budget["tool_output_truncations"], 0)

    def test_bounded_guard_blocks_broad_context_and_caps_tool_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "frontend/src").mkdir(parents=True)
            (repo / "frontend/src/App.tsx").write_text("export {}\n")
            budget = root / "budget.json"
            manifest = root / "manifest.json"
            atomic_write_json(
                budget,
                {
                    "schema_version": 1,
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_truncations": 0,
                },
            )
            atomic_write_json(
                manifest,
                {
                    "repository": str(repo),
                    "budget_path": str(budget),
                    "stage": "implementation",
                    "bounded_substage_id": "sign_in",
                    "readable_paths": ["frontend/src/App.tsx"],
                    "writable_paths": ["frontend/src"],
                },
            )
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest)},
            ):
                guard_tool("read_file", {"path": "frontend/src/App.tsx"})
                for forbidden in (
                    "ops/NOW.md",
                    "ops/STATE.json",
                    "ops/QUEUE.md",
                    "ops/V1_ROADMAP.json",
                    "Makefile",
                ):
                    with self.assertRaisesRegex(GuardError, "materializes"):
                        guard_tool("read_file", {"path": forbidden})
                with self.assertRaisesRegex(GuardError, "planning"):
                    guard_tool("todo", {"todos": []})
                with self.assertRaisesRegex(GuardError, "explicit pathspecs"):
                    guard_tool(
                        "terminal",
                        {"command": "git diff", "workdir": str(repo)},
                    )
                guard_tool(
                    "terminal",
                    {
                        "command": "git diff -- frontend/src/App.tsx",
                        "workdir": str(repo),
                    },
                )
                atomic_write_json(
                    manifest,
                    {
                        "repository": str(repo),
                        "budget_path": str(budget),
                        "stage": "implementation",
                        "bounded_substage_id": "sign_in",
                        "readable_paths": ["frontend/src/App.tsx"],
                        "writable_paths": ["frontend/src/authClient.ts"],
                    },
                )
                guard_tool(
                    "write_file",
                    {"path": "frontend/src/authClient.ts", "content": "export {}\n"},
                )
                with self.assertRaisesRegex(GuardError, "candidate scope"):
                    guard_tool(
                        "write_file",
                        {
                            "path": "frontend/src/authClient.ts/unexpected.py",
                            "content": "bad\n",
                        },
                    )
                with self.assertRaisesRegex(GuardError, "directly relevant"):
                    guard_tool(
                        "terminal",
                        {
                            "command": "git diff -- backend/src/unrelated.py",
                            "workdir": str(repo),
                        },
                    )
                with self.assertRaisesRegex(GuardError, "relevant paths"):
                    guard_tool(
                        "search_files",
                        {"path": "frontend/src", "pattern": "*"},
                    )
                bounded = bounded_tool_output("read_file", "x" * 26_386)
            self.assertLessEqual(len(bounded.encode()), 12_000)
            ledger = json.loads(budget.read_text())
            self.assertEqual(ledger["tool_output_observed_bytes"], 26_386)
            self.assertEqual(ledger["tool_output_truncations"], 1)

            atomic_write_json(
                budget,
                {
                    "schema_version": 1,
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_truncations": 0,
                },
            )
            child_environment = {
                **os.environ,
                "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest),
                "PYTHONPATH": str(ROOT / "scripts"),
            }
            workers = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        (
                            "from openclaw_hermes_guard import bounded_tool_output; "
                            "bounded_tool_output('read_file', 'x' * 12000)"
                        ),
                    ],
                    env=child_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(4)
            ]
            results = [worker.communicate(timeout=5) for worker in workers]
            self.assertTrue(all(worker.returncode == 0 for worker in workers), results)
            concurrent_ledger = json.loads(budget.read_text())
            self.assertEqual(concurrent_ledger["tool_output_observed_bytes"], 48_000)
            self.assertLessEqual(concurrent_ledger["tool_output_returned_bytes"], 36_000)
            self.assertGreaterEqual(concurrent_ledger["tool_output_truncations"], 1)

    def test_complete_parallel_batch_is_reserved_before_any_tool_executes(self) -> None:
        observed_sizes = [
            4_202,
            26_386,
            4_508,
            16_595,
            9_310,
            7_965,
            8_200,
            1_498,
            5_333,
            12_000,
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            paths: list[str] = []
            for index, size in enumerate(observed_sizes):
                relative = f"context/file-{index}.txt"
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x" * size)
                paths.append(relative)
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "exact-batch",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "bounded_substage_id": "sign_in",
            }
            atomic_write_json(manifest_path, manifest)
            response = {
                "output": [
                    {
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": json.dumps({"path": path}),
                    }
                    for path in paths
                ]
            }
            budget = json.loads(budget_path.read_text())
            self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
            atomic_write_json(budget_path, budget)
            executed = 0

            def forbidden_execution(_: dict[str, Any]) -> str:
                nonlocal executed
                executed += 1
                return "unexpected"

            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                rejected = [
                    execute_bounded_tool("read_file", {"path": path}, forbidden_execution)
                    for path in paths
                ]
            self.assertEqual(executed, 0)
            self.assertTrue(
                all(
                    json.loads(item)["classification"] == "context_materialization_required"
                    for item in rejected
                )
            )
            retry_budget = json.loads(budget_path.read_text())
            self.assertTrue(reserve_tool_output_batch(response, manifest, retry_budget))
            self.assertTrue(retry_budget["context_materialization_checkpoint"])
            self.assertEqual(retry_budget["tool_output_returned_bytes"], 0)

    def test_v4_small_frontend_batch_executes_under_one_atomic_reservation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "frontend/src").mkdir(parents=True)
            paths = [
                "frontend/src/App.tsx",
                "frontend/src/App.test.tsx",
                "frontend/src/styles.css",
            ]
            for path in paths:
                (repo / path).write_text((ROOT / path).read_text())
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "v4-small-batch",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "bounded_substage_id": "sign_in",
            }
            atomic_write_json(manifest_path, manifest)
            response = {
                "output": [
                    {
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": json.dumps({"path": path}),
                    }
                    for path in paths
                ]
            }
            budget = json.loads(budget_path.read_text())
            self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
            atomic_write_json(budget_path, budget)
            executed = 0

            def read(arguments: dict[str, Any]) -> str:
                nonlocal executed
                executed += 1
                return (repo / str(arguments["path"])).read_text()

            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                outputs = [
                    execute_bounded_tool("read_file", {"path": path}, read) for path in paths
                ]
            self.assertEqual(executed, 3)
            self.assertTrue(all(isinstance(item, str) and item for item in outputs))
            final = json.loads(budget_path.read_text())
            self.assertEqual(final.get("tool_output_batch_rejections", 0), 0)
            self.assertLess(final["tool_output_returned_bytes"], 36_000)

    def test_atomic_batch_identity_survives_hermes_numeric_argument_coercion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            (repo / "large.txt").write_text("x\n" * 8_000)
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "coerced-arguments",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 1_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "bounded_substage_id": "sign_in",
            }
            atomic_write_json(manifest_path, manifest)
            response = {
                "output": [
                    {
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": json.dumps(
                            {"path": "large.txt", "offset": "1", "limit": "8000"}
                        ),
                    }
                ]
            }
            budget = json.loads(budget_path.read_text())
            self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
            atomic_write_json(budget_path, budget)
            executed = 0

            def forbidden(_: dict[str, Any]) -> str:
                nonlocal executed
                executed += 1
                return "unexpected"

            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                result = execute_bounded_tool(
                    "read_file",
                    {"path": "large.txt", "offset": 1, "limit": 8000},
                    forbidden,
                )
            self.assertEqual(executed, 0)
            self.assertEqual(
                json.loads(result)["classification"],
                "context_materialization_required",
            )

    def test_rejection_controls_share_the_cumulative_tool_context_allowance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            for index in range(3):
                (repo / f"large-{index}.txt").write_text("x" * 20_000)
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "charged-controls",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 4_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "bounded_substage_id": "sign_in",
            }
            atomic_write_json(manifest_path, manifest)
            prior_remaining = 4_000
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                for index in range(3):
                    response = {
                        "output": [
                            {
                                "type": "function_call",
                                "name": "read_file",
                                "arguments": json.dumps({"path": f"large-{index}.txt"}),
                            }
                        ]
                    }
                    budget = json.loads(budget_path.read_text())
                    self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
                    self.assertEqual(
                        budget["tool_output_batch_history"][-1]["remaining_bytes"],
                        prior_remaining,
                    )
                    atomic_write_json(budget_path, budget)
                    result = execute_bounded_tool(
                        "read_file",
                        {"path": f"large-{index}.txt"},
                        lambda _: self.fail("a rejected tool batch executed"),
                    )
                    self.assertTrue(json.loads(result))
                    ledger = json.loads(budget_path.read_text())
                    prior_remaining = (
                        4_000
                        - ledger["tool_output_returned_bytes"]
                        - ledger["tool_output_control_bytes"]
                    )
                    self.assertGreaterEqual(prior_remaining, 0)
            final = json.loads(budget_path.read_text())
            self.assertGreater(final["tool_output_control_bytes"], 0)
            self.assertLessEqual(
                final["tool_output_returned_bytes"] + final["tool_output_control_bytes"],
                4_000,
            )

    def test_unreserved_bounded_tool_call_fails_closed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "unreserved-call",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            atomic_write_json(
                manifest_path,
                {
                    "repository": str(repo),
                    "budget_path": str(budget_path),
                    "bounded_substage_id": "sign_in",
                },
            )
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                result = execute_bounded_tool(
                    "read_file",
                    {"path": "not-reserved.txt"},
                    lambda _: self.fail("an unreserved bounded tool call executed"),
                )
            self.assertEqual(json.loads(result)["classification"], "unreserved_tool_call")
            ledger = json.loads(budget_path.read_text())
            self.assertTrue(ledger["context_materialization_checkpoint"])
            self.assertTrue(ledger["next_api_call_blocked"])

    def test_atomic_batch_identity_mirrors_all_hermes_schema_coercions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "all-coerced-arguments",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_control_reserved_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "bounded_substage_id": "sign_in",
            }
            atomic_write_json(manifest_path, manifest)
            provider_arguments = [
                (
                    "search_files",
                    {
                        "pattern": "login",
                        "path": ".",
                        "limit": "10",
                        "offset": "2",
                        "context": "3",
                    },
                    {
                        "pattern": "login",
                        "path": ".",
                        "limit": 10,
                        "offset": 2,
                        "context": 3,
                    },
                ),
                (
                    "patch",
                    {
                        "mode": "replace",
                        "path": "App.tsx",
                        "old_string": "a",
                        "new_string": "b",
                        "replace_all": "false",
                        "cross_profile": "false",
                    },
                    {
                        "mode": "replace",
                        "path": "App.tsx",
                        "old_string": "a",
                        "new_string": "b",
                        "replace_all": False,
                        "cross_profile": False,
                    },
                ),
                (
                    "terminal",
                    {
                        "command": "git status",
                        "timeout": "3e1",
                        "background": "false",
                        "pty": "false",
                        "notify_on_complete": "false",
                        "watch_patterns": "ready",
                    },
                    {
                        "command": "git status",
                        "timeout": 30,
                        "background": False,
                        "pty": False,
                        "notify_on_complete": False,
                        "watch_patterns": ["ready"],
                    },
                ),
            ]
            response = {
                "output": [
                    {
                        "type": "function_call",
                        "name": tool,
                        "arguments": json.dumps(raw),
                    }
                    for tool, raw, _ in provider_arguments
                ]
            }
            budget = json.loads(budget_path.read_text())
            self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
            atomic_write_json(budget_path, budget)
            executed: list[str] = []
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path)},
            ):
                for tool, _, coerced in provider_arguments:
                    result = execute_bounded_tool(
                        tool,
                        coerced,
                        lambda _args, current=tool: executed.append(current) or "ok",
                    )
                    self.assertEqual(result, "ok")
            self.assertEqual(executed, ["search_files", "patch", "terminal"])
            self.assertFalse(
                json.loads(budget_path.read_text()).get("context_materialization_checkpoint", False)
            )

    def test_pre_tool_policy_rejection_allows_one_correction_then_blocks_repeat(
        self,
    ) -> None:
        class Context:
            def __init__(self) -> None:
                self.middleware: dict[str, Any] = {}
                self.hooks: dict[str, Any] = {}

            def register_middleware(self, kind: str, callback: Any) -> None:
                self.middleware[kind] = callback

            def register_hook(self, kind: str, callback: Any) -> None:
                self.hooks[kind] = callback

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "ops").mkdir(parents=True)
            (repo / "ops/NOW.md").write_text("forbidden compact state\n")
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "policy-rejection",
                    "ceiling": 60_000,
                    "api_calls_started": 0,
                    "api_calls_completed": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_tokens": 0,
                    "counted_total_tokens": 0,
                    "boundary_reached": False,
                    "in_flight_overshoot_tokens": 0,
                    "next_api_call_blocked": False,
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 2_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_control_reserved_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                    "context_materialization_checkpoint": False,
                },
            )
            manifest = {
                "repository": str(repo),
                "budget_path": str(budget_path),
                "stage": "implementation",
                "bounded_substage_id": "sign_in",
                "readable_paths": [],
                "writable_paths": [],
            }
            atomic_write_json(manifest_path, manifest)
            response = {
                "output": [
                    {
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": json.dumps({"path": "ops/NOW.md"}),
                    }
                ]
            }
            budget = json.loads(budget_path.read_text())
            self.assertFalse(reserve_tool_output_batch(response, manifest, budget))
            atomic_write_json(budget_path, budget)
            context = Context()
            provider_calls = 0

            def provider(_: dict[str, Any]) -> dict[str, Any]:
                nonlocal provider_calls
                provider_calls += 1
                return {
                    "model": "gpt-5.6-sol",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_tokens": 0,
                    },
                    "output": response["output"],
                }

            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path),
                    "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "preflight",
                },
            ):
                register_plugin(context)
                directive = context.hooks["pre_tool_call"]("read_file", {"path": "ops/NOW.md"})
                context.middleware["llm_execution"]({"messages": []}, provider)
                repeated = context.hooks["pre_tool_call"]("read_file", {"path": "ops/NOW.md"})
                with self.assertRaises(SystemExit):
                    context.middleware["llm_execution"]({"messages": []}, provider)
            self.assertEqual(directive["action"], "block")
            self.assertIn("guard_policy_rejection", directive["message"])
            self.assertEqual(repeated["action"], "block")
            self.assertEqual(provider_calls, 1)
            ledger = json.loads(budget_path.read_text())
            self.assertGreater(ledger["tool_output_control_bytes"], 0)
            self.assertEqual(ledger["tool_output_control_reserved_bytes"], 0)
            self.assertEqual(
                ledger["tool_output_pending_reservations"][0]["status"],
                "policy_rejected",
            )
            self.assertTrue(ledger["context_materialization_checkpoint"])
            self.assertTrue(ledger["next_api_call_blocked"])
            self.assertTrue(ledger["tool_output_policy_rejection_repeated"])
            self.assertEqual(len(ledger["tool_output_policy_rejection_history"]), 2)
            self.assertLessEqual(ledger["tool_output_control_bytes"], 2_000)

    def test_parallel_unreserved_rejections_reserve_control_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            budget_path = root / "budget.json"
            manifest_path = root / "manifest.json"
            atomic_write_json(
                budget_path,
                {
                    "schema_version": 1,
                    "manifest_id": "parallel-unreserved",
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 2_000,
                    "tool_output_observed_bytes": 0,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_control_reserved_bytes": 0,
                    "tool_output_truncations": 0,
                    "tool_output_batch_history": [],
                    "tool_output_pending_reservations": [],
                },
            )
            atomic_write_json(
                manifest_path,
                {
                    "repository": str(repo),
                    "budget_path": str(budget_path),
                    "bounded_substage_id": "sign_in",
                },
            )
            environment = {
                **os.environ,
                "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path),
                "PYTHONPATH": str(ROOT / "scripts"),
            }
            workers = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        (
                            "from openclaw_hermes_guard import execute_bounded_tool; "
                            "print(execute_bounded_tool('read_file', "
                            f"{{'path': 'missing-{index}.txt'}}, lambda _: 'BAD'))"
                        ),
                    ],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(12)
            ]
            results = [worker.communicate(timeout=10) for worker in workers]
            self.assertTrue(all(worker.returncode == 0 for worker in workers), results)
            ledger = json.loads(budget_path.read_text())
            self.assertEqual(ledger["tool_output_control_reserved_bytes"], 0)
            self.assertLessEqual(
                ledger["tool_output_returned_bytes"] + ledger["tool_output_control_bytes"],
                2_000,
            )
            self.assertTrue(ledger["context_materialization_checkpoint"])

    def test_unavailable_token_estimation_is_zero_call_routing_fault(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            manifest = root / "manifest.json"
            atomic_write_json(
                budget,
                {
                    "schema_version": 1,
                    "ceiling": 60_000,
                    "api_calls_started": 0,
                    "api_calls_completed": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_tokens": 0,
                    "counted_total_tokens": 0,
                    "boundary_reached": False,
                    "in_flight_overshoot_tokens": 0,
                    "next_api_call_blocked": False,
                },
            )
            atomic_write_json(manifest, {"budget_path": str(budget)})
            provider_calls = 0

            def provider(_: dict[str, Any]) -> None:
                nonlocal provider_calls
                provider_calls += 1

            with (
                mock.patch.dict(
                    os.environ,
                    {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest)},
                ),
                mock.patch(
                    "openclaw_hermes_guard.estimate_serialized_request_tokens",
                    side_effect=TokenEstimationUnavailable("no supported tokenizer"),
                ),
                self.assertRaisesRegex(GuardError, "TOKEN_ESTIMATION_UNAVAILABLE"),
            ):
                enforce_llm_call({"messages": []}, provider)
            ledger = json.loads(budget.read_text())
            self.assertEqual(provider_calls, 0)
            self.assertEqual(ledger["api_calls_started"], 0)
            self.assertFalse(ledger["boundary_reached"])
            self.assertEqual(ledger["token_estimation_status"], "unavailable")
            spec = importlib.util.spec_from_file_location(
                "token_estimation_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            token_dispatch = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(token_dispatch)
            classified = token_dispatch.zero_usage_provider_failure(
                returncode=1,
                stderr="Hermes guard stopped model execution",
                usage={
                    "api_calls": 0,
                    "api_calls_started": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "stop_reason": "token_estimation_unavailable",
                },
            )
            assert classified is not None
            self.assertEqual(classified["category"], "unsupported_invocation_configuration")
            self.assertFalse(classified["configured_ceiling_reached"])

    def test_hermes_tool_guard_enforces_repository_least_privilege(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "docs").mkdir(parents=True)
            (repo / "docs/001_DOMAIN_MODEL.md").write_text("canonical\n")
            manifest = root / "manifest.json"
            atomic_write_json(
                manifest,
                {
                    "repository": str(repo),
                    "stage": "implementation",
                    "writable_paths": ["backend/src/property_rental", "backend/tests"],
                    "readable_paths": [],
                    "bounded_substage_id": None,
                },
            )
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest)},
            ):
                guard_tool("read_file", {"path": "docs/001_DOMAIN_MODEL.md"})
                guard_tool("terminal", {"command": "git diff", "workdir": str(repo)})
                guard_tool(
                    "terminal",
                    {"command": "make database-test", "workdir": str(repo)},
                )
                writable_subdirectory = repo / "backend/src/property_rental"
                writable_subdirectory.mkdir(parents=True)
                (writable_subdirectory / "Makefile").write_text("backend-test:\n\tgit push\n")
                with self.assertRaisesRegex(GuardError, "repository root"):
                    guard_tool(
                        "terminal",
                        {
                            "command": "make backend-test",
                            "workdir": str(writable_subdirectory),
                        },
                    )
                guard_tool("write_file", {"path": "backend/src/property_rental/candidate.py"})
                guard_tool(
                    "patch",
                    {
                        "mode": "patch",
                        "patch": "*** Update File: backend/src/property_rental/candidate.py\n",
                    },
                )
                with self.assertRaisesRegex(GuardError, "candidate scope"):
                    guard_tool(
                        "patch",
                        {
                            "mode": "patch",
                            "patch": (
                                "*** Update File: backend/src/property_rental/candidate.py\n"
                                "***Move File: backend/src/property_rental/candidate.py -> scripts/escape.py\n"
                            ),
                        },
                    )
                with self.assertRaisesRegex(GuardError, "candidate scope"):
                    guard_tool(
                        "patch",
                        {"mode": "patch", "patch": "***Update File: Makefile\n"},
                    )
                with self.assertRaisesRegex(GuardError, "explicit repository paths"):
                    guard_tool(
                        "patch",
                        {
                            "mode": "patch",
                            "patch": "*** Copy File: backend/src/property_rental/candidate.py\n",
                        },
                    )
                with self.assertRaisesRegex(GuardError, "candidate scope"):
                    guard_tool("write_file", {"path": "Makefile"})
                with self.assertRaisesRegex(GuardError, "candidate scope"):
                    guard_tool("write_file", {"path": "scripts/openclaw_dispatch.py"})
                with self.assertRaises(GuardError):
                    guard_tool("write_file", {"path": "docs/001_DOMAIN_MODEL.md"})
                with self.assertRaises(GuardError):
                    guard_tool(
                        "terminal",
                        {"command": "git commit -m forbidden", "workdir": str(repo)},
                    )
                with self.assertRaises(GuardError):
                    guard_tool(
                        "terminal",
                        {
                            "command": "git diff --no-index /etc/passwd candidate.txt",
                            "workdir": str(repo),
                        },
                    )
                with self.assertRaises(GuardError):
                    guard_tool(
                        "terminal",
                        {
                            "command": "git diff --output=/tmp/escaped",
                            "workdir": str(repo),
                        },
                    )
                with self.assertRaises(GuardError):
                    guard_tool("terminal", {"command": "psql property", "workdir": str(repo)})
                with self.assertRaises(GuardError):
                    guard_tool("process", {"command": "make test"})
                with self.assertRaises(GuardError):
                    guard_tool("read_file", {"path": str(root / "outside")})
                with self.assertRaisesRegex(GuardError, "credential"):
                    guard_tool("read_file", {"path": "backend/.env.production"})
                atomic_write_json(
                    manifest,
                    {
                        "repository": str(repo),
                        "stage": "independent_review",
                        "writable_paths": [],
                        "readable_paths": [],
                        "bounded_substage_id": None,
                    },
                )
                with self.assertRaisesRegex(GuardError, "review is read-only"):
                    guard_tool("write_file", {"path": "candidate.txt"})

    def test_registered_guard_cannot_fail_open_at_policy_boundary(self) -> None:
        class Context:
            def __init__(self) -> None:
                self.middleware: dict[str, Any] = {}
                self.hooks: dict[str, Any] = {}

            def register_middleware(self, kind: str, callback: Any) -> None:
                self.middleware[kind] = callback

            def register_hook(self, kind: str, callback: Any) -> None:
                self.hooks[kind] = callback

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            budget = root / "budget.json"
            manifest = root / "manifest.json"
            atomic_write_json(
                budget,
                {
                    "schema_version": 1,
                    "ceiling": 60_000,
                    "api_calls_started": 1,
                    "api_calls_completed": 1,
                    "input_tokens": 45_000,
                    "output_tokens": 15_000,
                    "cache_read_tokens": 7_000,
                    "reasoning_tokens": 0,
                    "counted_total_tokens": 60_000,
                    "boundary_reached": True,
                    "in_flight_overshoot_tokens": 0,
                    "next_api_call_blocked": False,
                },
            )
            atomic_write_json(
                manifest,
                {
                    "repository": str(repo),
                    "budget_path": str(budget),
                    "writable_paths": [],
                    "readable_paths": [],
                    "bounded_substage_id": None,
                },
            )
            context = Context()
            provider_called = False

            def provider(_: dict[str, Any]) -> None:
                nonlocal provider_called
                provider_called = True

            tool_called = False

            def tool(_: dict[str, Any]) -> None:
                nonlocal tool_called
                tool_called = True

            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest),
                    "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "preflight",
                },
            ):
                register_plugin(context)
                with self.assertRaises(SystemExit):
                    context.middleware["llm_execution"]({}, provider)
                blocked = context.middleware["tool_execution"](
                    "terminal", {"command": "git push"}, tool
                )
                directive = context.hooks["pre_tool_call"]("terminal", {"command": "git push"})
            self.assertFalse(provider_called)
            self.assertFalse(tool_called)
            self.assertIn("only read-only git", blocked)
            self.assertEqual(directive["action"], "block")
            manifest.write_text("{ malformed\n")
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest),
                    "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "preflight",
                },
            ):
                with self.assertRaises(SystemExit):
                    context.middleware["llm_execution"]({}, provider)
                malformed_tool = context.middleware["tool_execution"](
                    "terminal", {"command": "git status"}, tool
                )
                malformed_directive = context.hooks["pre_tool_call"](
                    "terminal", {"command": "git status"}
                )
            self.assertFalse(provider_called)
            self.assertFalse(tool_called)
            self.assertIn("Expecting property name", malformed_tool)
            self.assertEqual(malformed_directive["action"], "block")

    def test_production_middleware_cannot_fallback_after_reservation_failure(
        self,
    ) -> None:
        class Context:
            def __init__(self) -> None:
                self.middleware: dict[str, Any] = {}
                self.hooks: dict[str, Any] = {}

            def register_middleware(self, kind: str, callback: Any) -> None:
                self.middleware[kind] = callback

            def register_hook(self, kind: str, callback: Any) -> None:
                self.hooks[kind] = callback

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            allowed = repo / "allowed.txt"
            allowed.write_text("bounded\n")
            budget = root / "budget.json"
            manifest = root / "manifest.json"
            atomic_write_json(
                budget,
                {
                    "schema_version": 1,
                    "tool_output_limit_bytes": 12_000,
                    "session_tool_output_limit_bytes": 36_000,
                    "tool_output_returned_bytes": 0,
                    "tool_output_control_bytes": 0,
                    "tool_output_control_reserved_bytes": 0,
                    "tool_output_pending_reservations": [],
                },
            )
            atomic_write_json(
                manifest,
                {
                    "repository": str(repo),
                    "budget_path": str(budget),
                    "stage": "implementation",
                    "bounded_substage_id": "sign_in",
                    "readable_paths": ["allowed.txt"],
                    "writable_paths": [],
                },
            )
            context = Context()
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest),
                    "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "preflight",
                },
            ):
                register_plugin(context)
                budget.unlink()
                executed = False

                def downstream(_: dict[str, Any]) -> str:
                    nonlocal executed
                    executed = True
                    return "unbounded"

                # Hermes catches Exception from middleware and calls downstream;
                # the policy boundary must therefore leave via BaseException.
                with self.assertRaises(SystemExit):
                    try:
                        context.middleware["tool_execution"](
                            "read_file", {"path": "allowed.txt"}, downstream
                        )
                    except Exception:
                        downstream({"path": "allowed.txt"})
            self.assertFalse(executed)

    def test_chat_authentication_is_released_only_by_chat_guard_registration(
        self,
    ) -> None:
        class Context:
            def register_middleware(self, _kind: str, _callback: Any) -> None:
                return None

            def register_hook(self, _kind: str, _callback: Any) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            source_home.mkdir()
            source_auth = source_home / "auth.json"
            source_auth.write_text("{}\n")
            session_home = root / "session"
            budget = root / "budget.json"
            manifest_path = root / "manifest.json"
            manifest = {
                "manifest_id": "guarded-session",
                "candidate": "V1-018",
                "stage": "implementation",
                "budget_path": str(budget),
                "token_policy": {"cumulative_ceiling": 60_000},
            }
            atomic_write_json(manifest_path, manifest)
            prepare_session_home(manifest, session_home, source_home)
            self.assertFalse((session_home / "auth.json").exists())
            common = {
                "PROPERTY_RENTAL_INVOCATION_MANIFEST": str(manifest_path),
                "HERMES_HOME": str(session_home),
            }
            with mock.patch.dict(
                os.environ,
                {**common, "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "preflight"},
            ):
                register_plugin(Context())
            self.assertFalse((session_home / "auth.json").exists())
            with mock.patch.dict(
                os.environ,
                {**common, "PROPERTY_RENTAL_HERMES_PROCESS_MODE": "chat"},
            ):
                register_plugin(Context())
            self.assertTrue((session_home / "auth.json").is_symlink())
            self.assertEqual((session_home / "auth.json").resolve(), source_auth.resolve())
            ledger = json.loads(budget.read_text())
            self.assertTrue(ledger["preflight_guard_loaded"])
            self.assertTrue(ledger["chat_guard_loaded"])
            self.assertEqual(ledger["chat_guard_pid"], os.getpid())

    def test_model_invocation_accounting_does_not_infer_missing_api_calls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = RepositoryEvidenceTests()
            repo = helper.make_repo(root)
            for name in (
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            fake = root / "fake-hermes.py"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if 'prompt-size' in args:
    manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
    budget = json.load(open(manifest['budget_path']))
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    open(manifest['budget_path'], 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget = json.load(open(manifest['budget_path']))
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':os.environ.get('RETURNED_MODEL','gpt-5.6-sol'),'api_calls_started':1,'api_calls_completed':1,'input_tokens':1,'output_tokens':0,'counted_total_tokens':1})
json.dump(budget, open(manifest['budget_path'], 'w'))
print('{}')
raise SystemExit(int(os.environ.get('FAKE_EXIT','0')))
"""
            )
            fake.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ps = fake_bin / "ps"
            fake_ps.write_text(dispatcher_ps_probe_script())
            fake_ps.chmod(0o755)
            spec = importlib.util.spec_from_file_location(
                "accounting_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            environment = {
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "FAKE_EXIT": "70",
            }
            with mock.patch.dict(os.environ, environment):
                spec.loader.exec_module(dispatcher)
                record = {"candidate": "V1-018", "stage": "implementation"}
                packet = task_packet(repo, {"actionable": True}, "implementation")
                exit_status, _, _ = dispatcher.invoke_model(
                    record, packet, model_policy("implementation")
                )
            self.assertEqual(exit_status, 70)
            attempts = json.loads((state_dir / "attempts/V1-018.json").read_text())
            self.assertEqual(attempts["counters"]["implementation"], 1)

            (repo / "ops/NOW.md").write_text("# Changed actionable state\n")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        **environment,
                        "FAKE_EXIT": "0",
                        "RETURNED_MODEL": "unsupported-model",
                    },
                ),
                self.assertRaisesRegex(AutomationError, "unsupported model"),
            ):
                dispatcher.invoke_model(
                    record,
                    task_packet(repo, {"actionable": True}, "implementation"),
                    model_policy("implementation"),
                )
            attempts = json.loads((state_dir / "attempts/V1-018.json").read_text())
            self.assertEqual(attempts["counters"].get("implementation", 0), 1)

    def test_zero_usage_provider_rejection_preserves_exact_error_and_no_attempt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            for name in (
                "hermes-property-rental",
                "openclaw_automation.py",
                "openclaw_hermes_guard.py",
            ):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "zero usage provider fixture"],
                cwd=repo,
                check=True,
            )
            fake = root / "fake-hermes.py"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget_path = manifest['budget_path']
budget = json.load(open(budget_path))
if 'prompt-size' in sys.argv[1:]:
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    json.dump(budget, open(budget_path, 'w'))
    print('{}')
    raise SystemExit(0)
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'api_calls_started':1,'api_calls_completed':0,'input_tokens':0,'output_tokens':0,'cache_read_tokens':0,'reasoning_tokens':0,'counted_total_tokens':0})
json.dump(budget, open(budget_path, 'w'))
print("Hermes guard stopped model execution: Error code: 400 - {'detail': 'Unsupported parameter: max_output_tokens'}", file=sys.stderr)
raise SystemExit(1)
"""
            )
            fake.chmod(0o755)
            fake_ps = root / "ps"
            fake_ps.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                f"  *ppid=*) printf '%s\\n' {os.getpid()} ;;\n"
                "  *) printf '%s\\n' \"$PROPERTY_RENTAL_REPO/scripts/openclaw_dispatch.py\" ;;\n"
                "esac\n"
            )
            fake_ps.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            spec = importlib.util.spec_from_file_location(
                "zero_usage_dispatch", ROOT / "scripts/openclaw_dispatch.py"
            )
            assert spec and spec.loader
            dispatcher = importlib.util.module_from_spec(spec)
            state_dir = root / "state"
            environment = {
                "PROPERTY_RENTAL_REPO": str(repo),
                "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                "PATH": f"{root}:{os.environ['PATH']}",
            }
            with mock.patch.dict(os.environ, environment):
                spec.loader.exec_module(dispatcher)
                record = {"candidate": "V1-018", "stage": "implementation"}
                packet = task_packet(repo, {"actionable": True}, "implementation")
                with self.assertRaises(AutomationError) as rejected:
                    dispatcher.invoke_model(record, packet, model_policy("implementation"))
                self.assertEqual(
                    rejected.exception.category,
                    "unsupported_invocation_configuration",
                )
                self.assertEqual(
                    str(rejected.exception),
                    "HTTP 400: Unsupported parameter: max_output_tokens",
                )
                with self.assertRaises(AutomationError) as repeated:
                    dispatcher.invoke_model(
                        record,
                        task_packet(repo, {"actionable": True}, "implementation"),
                        model_policy("implementation"),
                    )
            self.assertEqual(repeated.exception.category, "repeated_identical_tool_call")
            attempts = json.loads((state_dir / "attempts/V1-018.json").read_text())
            self.assertEqual(attempts["counters"].get("implementation", 0), 0)
            self.assertIsNone(attempts["pending"])
            durable = record["model_usage"][-1]
            self.assertEqual(durable["api_calls_started"], 1)
            self.assertEqual(durable["api_calls_completed"], 0)
            self.assertEqual(durable["total_token_usage"], 0)
            self.assertEqual(durable["provider_http_status"], 400)
            self.assertEqual(
                durable["provider_error"],
                "Unsupported parameter: max_output_tokens",
            )
            call = json.loads(next((state_dir / "calls").glob("*.json")).read_text())
            self.assertEqual(
                call["underlying_result"],
                "HTTP 400: Unsupported parameter: max_output_tokens",
            )

    def test_health_classifications_and_disabled_scheduler_accuracy(self) -> None:
        self.assertEqual(
            health_classification(
                enabled=False,
                scheduler_ok=False,
                project_stage="implementation",
                blocker_kind=None,
            ),
            "scheduler_intentionally_disabled",
        )
        self.assertEqual(
            health_classification(
                enabled=True,
                scheduler_ok=True,
                project_stage="implementation",
                blocker_kind=None,
            ),
            "implementation_in_progress",
        )
        self.assertEqual(
            health_classification(
                enabled=True,
                scheduler_ok=True,
                project_stage="idle",
                blocker_kind="owner_policy_decision",
            ),
            "project_blocked_owner_decision",
        )
        self.assertEqual(
            health_classification(
                enabled=True,
                scheduler_ok=True,
                project_stage="implementation",
                blocker_kind="conflicting_owner_work",
            ),
            "project_blocked_owner_decision",
        )
        self.assertEqual(
            health_classification(
                enabled=True,
                scheduler_ok=True,
                project_stage="implementation",
                blocker_kind="destructive_or_production_operation",
            ),
            "project_blocked_protected_operation",
        )
        self.assertEqual(
            health_classification(
                enabled=True,
                scheduler_ok=True,
                project_stage="post_publication_reconciliation",
                blocker_kind=None,
            ),
            "state_reconciliation_required",
        )
        self.assertEqual(
            health_classification(
                enabled=False,
                scheduler_ok=False,
                project_stage="idle",
                blocker_kind=None,
                installed=False,
            ),
            "scheduler_unhealthy",
        )

    def test_daily_usage_preserves_unavailable_provider_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "usage.jsonl"
            ledger.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "1970-01-01T00:00:10+00:00",
                                "total_token_usage": 5,
                                "cache_read_token_usage": 3,
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "1970-01-01T00:00:11+00:00",
                                "total_token_usage": "unavailable from provider",
                            }
                        ),
                    ]
                )
                + "\n"
            )
            spec = importlib.util.spec_from_file_location(
                "daily_usage_report", ROOT / "scripts/openclaw-daily-report.py"
            )
            assert spec and spec.loader
            report = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {"PROPERTY_RENTAL_MODEL_USAGE_LEDGER": str(ledger)},
            ):
                spec.loader.exec_module(report)
            totals, unavailable, cache_totals = report.recent_model_usage(now=20)
            self.assertEqual(totals, [5])
            self.assertEqual(unavailable, 1)
            self.assertEqual(cache_totals, [3])
            self.assertNotIn(0, totals)

    def test_daily_report_rejects_stale_success_as_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            preflight = repo / "scripts/openclaw-supervisor-preflight.sh"
            preflight.parent.mkdir(exist_ok=True)
            preflight.write_bytes((ROOT / "scripts/openclaw-supervisor-preflight.sh").read_bytes())
            preflight.chmod(0o755)
            (repo / "scripts/openclaw_automation.py").write_bytes(
                (ROOT / "scripts/openclaw_automation.py").read_bytes()
            )
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "report harness"], cwd=repo, check=True)
            database = root / "openclaw.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE cron_jobs (job_id TEXT, enabled INTEGER, last_run_at_ms INTEGER, last_run_status TEXT, consecutive_errors INTEGER, running_at_ms INTEGER)"
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?)",
                    (
                        "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                        1,
                        1_000,
                        "ok",
                        0,
                        None,
                    ),
                )
            spec = importlib.util.spec_from_file_location(
                "daily_report_stale", ROOT / "scripts/openclaw-daily-report.py"
            )
            assert spec and spec.loader
            report = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_OPENCLAW_DB": str(database),
                    "PROPERTY_RENTAL_NOW_MS": str(10_000_000),
                    "PROPERTY_RENTAL_HEARTBEAT_MS": "1000",
                    "PROPERTY_RENTAL_MODEL_USAGE_LEDGER": str(root / "usage.jsonl"),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(root / "dispatch"),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                },
            ):
                spec.loader.exec_module(report)
                output = io.StringIO()
                with redirect_stdout(output):
                    report.main()
            self.assertIn("Automation: UNHEALTHY", output.getvalue())

    def test_daily_report_rejects_duplicate_or_malformed_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            wrapper = root / "installed-hermes-property-rental"
            wrapper.write_bytes((ROOT / "scripts/hermes-property-rental").read_bytes())
            repository_wrapper = repo / "scripts/hermes-property-rental"
            repository_wrapper.parent.mkdir(exist_ok=True)
            repository_wrapper.write_bytes(wrapper.read_bytes())
            database = root / "openclaw.sqlite"
            payload = json.dumps(
                {
                    "kind": "command",
                    "argv": [str(repo / "scripts/openclaw-supervisor-dispatch.sh")],
                    "cwd": str(repo),
                    "noOutputTimeoutSeconds": 10860,
                    "outputMaxBytes": 20000,
                }
            )
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """CREATE TABLE cron_jobs (
                      job_id TEXT, name TEXT, enabled INTEGER, schedule_kind TEXT,
                      every_ms INTEGER, payload_kind TEXT, payload_message TEXT,
                      last_run_at_ms INTEGER, last_run_status TEXT,
                      consecutive_errors INTEGER, running_at_ms INTEGER,
                      updated_at INTEGER
                    )"""
                )
                row = (
                    "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                    "property-rental-24x7-supervisor",
                    1,
                    "every",
                    1_800_000,
                    "command",
                    payload,
                    9_999_999,
                    "ok",
                    0,
                    None,
                    9_999_000,
                )
                connection.execute("INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("duplicate", *row[1:]),
                )
            spec = importlib.util.spec_from_file_location(
                "daily_report_duplicate", ROOT / "scripts/openclaw-daily-report.py"
            )
            assert spec and spec.loader
            report = importlib.util.module_from_spec(spec)
            with mock.patch.dict(
                os.environ,
                {
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_OPENCLAW_DB": str(database),
                    "PROPERTY_RENTAL_INSTALLED_HERMES_WRAPPER": str(wrapper),
                },
            ):
                spec.loader.exec_module(report)
            self.assertTrue(report.supervisor_status()["present"])
            self.assertFalse(report.supervisor_status()["config_valid"])

    def test_repository_owned_wrapper_enforces_supported_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            from openclaw_hermes_guard import create_manifest

            root = Path(directory)
            capture = root / "args.json"
            fake = root / "hermes"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if 'prompt-size' in args:
    manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
    budget = json.load(open(manifest['budget_path']))
    budget.update({'guard_loaded':True,'preflight_guard_loaded':True,'guard_capabilities':['cumulative_llm_execution','least_privilege_pre_tool_block','least_privilege_tool_execution']})
    open(manifest['budget_path'], 'w').write(json.dumps(budget))
    print('{}')
    raise SystemExit(0)
manifest = json.load(open(os.environ['PROPERTY_RENTAL_INVOCATION_MANIFEST']))
budget = json.load(open(manifest['budget_path']))
budget.update({'chat_guard_loaded':True,'chat_guard_pid':os.getpid(),'effective_model':'gpt-5.6-sol','api_calls_started':1,'api_calls_completed':1,'input_tokens':8,'output_tokens':3,'cache_read_tokens':2,'reasoning_tokens':1,'counted_total_tokens':11})
open(manifest['budget_path'], 'w').write(json.dumps(budget))
open(os.environ['CAPTURE'],'w').write(json.dumps({'args':args,'ceiling':os.environ.get('HERMES_MAX_TOKENS')}))
print('{}')
"""
            )
            fake.chmod(0o755)
            hermes_home = root / "hermes-home"
            hermes_home.mkdir()
            (hermes_home / "auth.json").write_text("{}\n")
            task = root / "task.txt"
            task.write_text("compact task\n")
            state_root = root / "state"
            dispatcher_record = state_root / "candidates/V1-018.json"
            fingerprint = repository_fingerprint(ROOT)
            atomic_write_json(
                dispatcher_record,
                {
                    "candidate": "V1-018",
                    "stage": "implementation",
                    "repository_fingerprint": fingerprint,
                },
            )
            manifest_path, manifest, authorization = create_manifest(
                state_root=state_root,
                repository=ROOT,
                dispatcher_pid=os.getpid(),
                candidate="V1-018",
                stage="implementation",
                repository_fingerprint=fingerprint,
                preserved_worktree_fingerprint=preservation_evidence(ROOT).get("fingerprint"),
                task_path=task,
                provider="openai-codex",
                model="gpt-5.6-sol",
                requested_reasoning="high",
                cumulative_ceiling=60_000,
                dispatcher_record_path=dispatcher_record,
                writable_paths=["backend/src/property_rental", "backend/tests"],
                readable_paths=[],
                bounded_substage_id=None,
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "CAPTURE": str(capture),
                    "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                    "PROPERTY_RENTAL_HERMES_SOURCE_HOME": str(hermes_home),
                    "PROPERTY_RENTAL_HERMES_USAGE_FILE": str(manifest["usage_path"]),
                    "PROPERTY_RENTAL_HERMES_STAGE": "implementation",
                    "PROPERTY_RENTAL_HERMES_TOKEN_CEILING": "60000",
                    "PROPERTY_RENTAL_INVOCATION_AUTHORIZATION": authorization,
                }
            )
            direct_manifest = subprocess.run(
                [
                    str(ROOT / "scripts/hermes-property-rental"),
                    str(task),
                    str(manifest_path),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(direct_manifest.returncode, 64)
            self.assertRegex(direct_manifest.stderr, r"dispatcher|parent process")
            self.assertFalse(Path(str(manifest["usage_path"])).exists())
            direct = subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), str(task)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(direct.returncode, 64)
            self.assertIn("dispatcher-created invocation manifest", direct.stderr)

    def test_exceptional_review_manifest_requires_persisted_classification(
        self,
    ) -> None:
        from openclaw_hermes_guard import create_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "review.json"
            task.write_text("{}\n")
            preserved = preservation_evidence(ROOT).get("fingerprint")
            fingerprint = repository_fingerprint(ROOT)
            bad_record = root / "bad/candidates/V1-018.json"
            good_record = root / "good/candidates/V1-018.json"
            for record_path in (bad_record, good_record):
                atomic_write_json(
                    record_path,
                    {
                        "candidate": "V1-018",
                        "stage": "independent_review",
                        "repository_fingerprint": fingerprint,
                    },
                )
            bad_path, _, bad_authorization = create_manifest(
                state_root=root / "bad",
                repository=ROOT,
                dispatcher_pid=os.getpid(),
                candidate="V1-018",
                stage="independent_review",
                repository_fingerprint=fingerprint,
                preserved_worktree_fingerprint=preserved,
                task_path=task,
                provider="openai-codex",
                model="gpt-5.6-sol",
                requested_reasoning="xhigh",
                cumulative_ceiling=120_000,
                dispatcher_record_path=bad_record,
                writable_paths=[],
                readable_paths=[],
                bounded_substage_id=None,
            )
            with self.assertRaisesRegex(GuardError, "exceptional classification"):
                validate_manifest(
                    bad_path,
                    task_path=task,
                    consume=False,
                    authorization=bad_authorization,
                )
            good_path, _, good_authorization = create_manifest(
                state_root=root / "good",
                repository=ROOT,
                dispatcher_pid=os.getpid(),
                candidate="V1-018",
                stage="independent_review",
                repository_fingerprint=fingerprint,
                preserved_worktree_fingerprint=preserved,
                task_path=task,
                provider="openai-codex",
                model="gpt-5.6-sol",
                requested_reasoning="xhigh",
                cumulative_ceiling=120_000,
                dispatcher_record_path=good_record,
                writable_paths=[],
                readable_paths=[],
                bounded_substage_id=None,
                exceptional_review_classification="persisted broad security review",
            )
            validated = validate_manifest(
                good_path,
                task_path=task,
                consume=False,
                authorization=good_authorization,
            )
            self.assertEqual(
                validated["token_policy"]["exceptional_review_classification"],
                "persisted broad security review",
            )
            drifted_record = json.loads(good_record.read_text())
            drifted_record["stage"] = "implementation"
            atomic_write_json(good_record, drifted_record)
            with self.assertRaisesRegex(GuardError, "manifest path or repository"):
                validate_manifest(
                    good_path,
                    task_path=task,
                    consume=False,
                    authorization=good_authorization,
                )

    def test_empty_task_delivery_fails_before_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "empty"
            manifest = root / "manifest.json"
            task.write_text(" \n")
            manifest.write_text("{}\n")
            result = subprocess.run(
                [
                    str(ROOT / "scripts/openclaw-hermes-task.sh"),
                    str(task),
                    str(manifest),
                ],
                env={**os.environ, "PROPERTY_RENTAL_REPO": str(ROOT)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not be empty", result.stderr)

    def test_installed_and_repository_dispatchers_can_be_compared_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            (workspace / "bin").mkdir(parents=True)
            installed = workspace / "bin/hermes-property-rental"
            installed.write_bytes((ROOT / "scripts/hermes-property-rental").read_bytes())
            installed.chmod(0o755)
            database = root / "openclaw.sqlite"
            payload = json.dumps(
                {
                    "kind": "command",
                    "argv": [str(ROOT / "scripts/openclaw-supervisor-dispatch.sh")],
                    "cwd": str(ROOT),
                    "noOutputTimeoutSeconds": 10860,
                    "outputMaxBytes": 20000,
                },
                separators=(",", ":"),
            )
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE cron_jobs (job_id TEXT, name TEXT, enabled INTEGER, schedule_kind TEXT, every_ms INTEGER, payload_kind TEXT, payload_message TEXT)"
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?)",
                    (
                        "658ffdaf-1ac1-45a6-a842-f5f7d7a226eb",
                        "property-rental-24x7-supervisor",
                        0,
                        "every",
                        1_800_000,
                        "command",
                        payload,
                    ),
                )
            environment = {
                **os.environ,
                "PROPERTY_RENTAL_REPO": str(ROOT),
                "PROPERTY_RENTAL_OPENCLAW_WORKSPACE": str(workspace),
                "PROPERTY_RENTAL_OPENCLAW_DB": str(database),
                "PROPERTY_RENTAL_EXPECT_SCHEDULER_ENABLED": "false",
            }
            result = subprocess.run(
                [str(ROOT / "scripts/openclaw-installation-check.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?)",
                    (
                        "different-supervisor-id",
                        "property-rental-24x7-supervisor",
                        0,
                        "every",
                        1_800_000,
                        "command",
                        payload,
                    ),
                )
            duplicate = subprocess.run(
                [str(ROOT / "scripts/openclaw-installation-check.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("exactly one", duplicate.stderr)
            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM cron_jobs WHERE job_id = 'different-supervisor-id'")
                connection.execute("UPDATE cron_jobs SET every_ms = 60000")
            refused = subprocess.run(
                [str(ROOT / "scripts/openclaw-installation-check.sh")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(refused.returncode, 0)

    def test_interrupted_verification_resumes_from_durable_stage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            record = {
                "candidate": "V1-018",
                "stage": "deterministic_verification",
                "implementation_complete": True,
                "events": [
                    {
                        "stage": "deterministic_verification",
                        "command": "backend-tests",
                        "exit_status": 0,
                        "artifact": "evidence/backend-tests.json",
                    }
                ],
            }
            with mock.patch.object(self.dispatch, "STATE_DIR", state_dir):
                self.dispatch.save_stage(record)
                resumed = self.dispatch.load_stage("V1-018")
            self.assertEqual(resumed["stage"], "deterministic_verification")
            self.assertEqual(resumed["events"][0]["exit_status"], 0)
            self.assertNotEqual(resumed["stage"], "implementation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
