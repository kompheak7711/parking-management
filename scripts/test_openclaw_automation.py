#!/usr/bin/env python3
"""Deterministic regression coverage for autonomous stage routing."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import tempfile
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
    STAGES,
    UNAVAILABLE,
    AutomationError,
    actionable_fingerprint,
    atomic_write_json,
    changed_paths,
    consume_attempt,
    consume_continuation,
    digest,
    health_classification,
    hermes_chat_usage,
    model_policy,
    normalize_usage,
    persist_terminal_marker,
    publication_candidate_guard,
    release_attempt,
    relevant_processes,
    repeated_call_key,
    repeated_call_result,
    repository_fingerprint,
    reserve_attempt,
    task_packet,
    usage_record,
    validate_usage,
)

ROOT = Path(__file__).resolve().parents[1]


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
        self.assertEqual(recovery.route, "direct Codex")
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
        validate_usage(
            {"model": "gpt-5.6-sol", "configured_max_tokens": 60_000}, policy
        )
        with self.assertRaisesRegex(AutomationError, "max_turns"):
            validate_usage(
                {
                    "model": "gpt-5.6-sol",
                    "configured_max_tokens": 60_000,
                    "stop_reason": "max_turns",
                },
                policy,
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
        self.assertEqual(len(FAILURE_CATEGORIES), 16)
        self.assertIn("pre_model_infrastructure_failure", FAILURE_CATEGORIES)
        self.assertIn("gateway_or_network_failure", FAILURE_CATEGORIES)
        self.assertIn("unsupported_invocation_configuration", FAILURE_CATEGORIES)
        self.assertIn("empty_or_invalid_task_delivery", FAILURE_CATEGORIES)
        self.assertIn("test_fixture_failure", FAILURE_CATEGORIES)
        self.assertIn("remote_ci_failure", FAILURE_CATEGORIES)


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
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "add", "--", "ops"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
        return repo

    def make_activation_repo(self, directory: Path) -> tuple[Path, dict[str, Any]]:
        repo = directory / "repo"
        (repo / "ops").mkdir(parents=True)
        (repo / "scripts").mkdir()
        for name in (
            "openclaw-select-next-candidate.sh",
            "openclaw-supervisor-preflight.sh",
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
        subprocess.run(
            ["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True
        )
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
            self.assertEqual(len(packet["compact_inputs"]), 4)

    def test_review_packet_is_separate_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            packet = task_packet(repo, {"actionable": True}, "independent_review")
            self.assertTrue(packet["review_only"])
            self.assertIn("passed", packet["output_contract"]["required"])
            self.assertNotIn("changed_paths", packet["output_contract"]["required"])

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
            roadmap["acceptance_profiles"] = {
                "api_ui": ["API authorization", "frontend build"]
            }
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
            subprocess.run(
                ["git", "init", "-q", "--bare", str(origin)], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "push", "-qu", "-u", "origin", "HEAD"], cwd=repo, check=True
            )
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
            self.assertIn(
                "Implement the approved bounded candidate: Exact successor", now
            )
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

    def test_dispatcher_runs_fresh_implementation_then_persists_next_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-supervisor-preflight.sh",
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
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
usage = os.environ['PROPERTY_RENTAL_HERMES_USAGE_FILE']
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
json.dump({'model':model,'reasoning_effort':reasoning,'configured_max_tokens':int(os.environ['HERMES_MAX_TOKENS']),'session_id':'fresh-' + reasoning,'input_tokens':10,'cache_read_tokens':2,'output_tokens':4,'reasoning_tokens':3,'total_tokens':17,'api_calls':1}, open(usage, 'w'))
print(json.dumps({'stage_result':'completed','changed_paths':['ops/STATE.json'],'verification':['focused implementation checks passed'],'blockers':[],'exact_next_action':'deterministic verification'}))
"""
            )
            fake.chmod(0o755)
            state_dir = root / "evidence"
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/openclaw_dispatch.py")],
                cwd=repo,
                env={
                    **os.environ,
                    "CAPTURE": str(capture),
                    "PROPERTY_RENTAL_REPO": str(repo),
                    "PROPERTY_RENTAL_DISPATCH_STATE_DIR": str(state_dir),
                    "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
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
            self.assertEqual(
                evidence["model_usage"][0]["effective_model"], "gpt-5.6-sol"
            )
            self.assertEqual(evidence["model_usage"][0]["session_id"], "fresh-high")
            prompt = capture.read_text()
            self.assertIn('"candidate": "V1-018"', prompt)
            self.assertNotIn("OPENCLAW_SUPERVISOR_PROMPT", prompt)

    def test_dispatcher_runs_distinct_xhigh_read_only_review_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in (
                "openclaw-supervisor-preflight.sh",
                "openclaw-hermes-task.sh",
                "hermes-property-rental",
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
            subprocess.run(
                ["git", "commit", "-qm", "implementation"], cwd=repo, check=True
            )
            fake = root / "fake-review.py"
            capture = root / "review-prompt.txt"
            capture_args = root / "review-args.json"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
open(os.environ['CAPTURE'], 'w').write(prompt)
open(os.environ['CAPTURE_ARGS'], 'w').write(json.dumps(args))
packet = json.loads(prompt[prompt.index('{'):])
result = {'passed': True, 'findings': [], 'reviewed_repository_fingerprint':packet['repository_fingerprint'],'reviewed_paths':packet['scoped_changed_paths'],'exact_next_action': 'publish'}
open(args[args.index('--output-last-message') + 1], 'w').write(json.dumps(result))
print(json.dumps({'type':'thread.started','thread_id':'fresh-review'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':20,'cached_input_tokens':5,'output_tokens':5,'reasoning_output_tokens':8}}))
"""
            )
            fake.chmod(0o755)
            state_dir = root / "evidence"
            atomic_write_json(
                state_dir / "candidates/V1-018.json",
                {
                    "candidate": "V1-018",
                    "stage": "independent_review",
                    "implementation_complete": True,
                    "deterministic_verification_passed": True,
                    "scoped_changed_paths": [],
                    "events": [
                        {"stage": "deterministic_verification", "exit_status": 0}
                    ],
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
                    "PROPERTY_RENTAL_CODEX_BIN": str(fake),
                    "PROPERTY_RENTAL_TEST_PROCESS_ROWS": "",
                    "PROPERTY_RENTAL_MAX_IMMEDIATE_CYCLES": "1",
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
            self.assertEqual(
                evidence["model_usage"][0]["requested_reasoning_effort"], "xhigh"
            )
            self.assertEqual(evidence["model_usage"][0]["session_id"], "fresh-review")
            self.assertIn('"review_only": true', capture.read_text())
            arguments = json.loads(capture_args.read_text())
            self.assertIn("read-only", arguments)
            self.assertIn("gpt-5.6-sol", arguments)
            self.assertIn('model_reasoning_effort="xhigh"', arguments)
            self.assertIn("model_context_window=90000", arguments)
            self.assertIn("--ephemeral", arguments)
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
            subprocess.run(
                ["git", "add", "--", "ops/STATE.json"], cwd=repo, check=True
            )
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
            self.assertEqual(
                preflight["state_issue"], "automation_repair_publication_required"
            )

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
            self.assertEqual(policy.route, "direct Codex")

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
            subprocess.run(
                ["git", "add", "--", "ops/STATE.json"], cwd=repo, check=True
            )
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
                return_value=(0, json.dumps(result), {"stage_name": "direct_codex_recovery"}),
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

    def test_direct_codex_ceiling_uses_last_message_for_safe_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
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
            fake = root / "fake-codex.py"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "args = sys.argv[1:]\n"
                f"handoff = {handoff!r}\n"
                "open(args[args.index('--output-last-message') + 1], 'w').write(json.dumps(handoff))\n"
                "print(json.dumps({'type':'thread.started','thread_id':'ceiling-session'}))\n"
                "print(json.dumps({'type':'turn.failed','error':{'code':'context_length_exceeded','message':'maximum tokens reached'}}))\n"
                "raise SystemExit(1)\n"
            )
            fake.chmod(0o755)
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
                    {"PROPERTY_RENTAL_CODEX_BIN": str(fake)},
                ),
                self.assertRaises(AutomationError) as raised,
            ):
                dispatcher.invoke_model(
                    record, packet, model_policy("direct_codex_recovery")
                )
            self.assertEqual(
                raised.exception.category, "model_session_or_token_ceiling"
            )
            self.assertEqual(record["stage"], "deterministic_verification")
            self.assertEqual(record["requested_stage"], "deterministic_verification")
            usage_files = [
                path
                for path in (state_dir / "usage").glob("*.json")
                if not path.name.endswith(".result.json")
            ]
            self.assertEqual(len(usage_files), 1)
            usage = json.loads(usage_files[0].read_text())
            self.assertEqual(usage["stop_reason"], "length")

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
            self.assertEqual(
                record["reconciliation_substage"], "reconciliation_ci_failed"
            )

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
                with mock.patch.object(
                    dispatcher, "cached_publication_guard", return_value=None
                ):
                    dispatcher.activate_next(record, {})
            self.assertEqual(record["stage"], "complete")
            self.assertEqual(record["activation_substage"], "complete")
            self.assertTrue(record["activation_ci_passed"])
            self.assertEqual(
                subprocess.check_output(
                    ["git", "status", "--porcelain=v1"], cwd=repo, text=True
                ),
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
            self.assertEqual(
                raised.exception.category, "repository_integrity_uncertainty"
            )

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
            self.assertIn(
                f"Automation publication state: published on main at {published}", now
            )
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
            policy = model_policy(
                "independent_review",
                complex_review=True,
                classification_reason="test review",
            )
            usage_report = normalize_usage(
                {"model": "gpt-5.6-sol", "total_tokens": 7}, policy
            )
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

    def test_pre_model_failure_is_suppressed_when_exact_call_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            for name in ("openclaw-hermes-task.sh", "hermes-property-rental"):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "model harness"], cwd=repo, check=True
            )
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
                    dispatcher.invoke_model(
                        record, packet, model_policy("implementation")
                    )
                self.assertEqual(
                    first.exception.category, "unsupported_invocation_configuration"
                )
                with self.assertRaises(AutomationError) as second:
                    dispatcher.invoke_model(
                        record, packet, model_policy("implementation")
                    )
            self.assertEqual(second.exception.category, "repeated_identical_tool_call")
            self.assertIn("preserved_underlying_result", str(second.exception))
            attempts = json.loads((state_dir / "attempts/V1-018.json").read_text())
            self.assertEqual(attempts["counters"].get("implementation", 0), 0)

    def test_cached_publication_guard_uses_cached_mode(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "guard_dispatch", ROOT / "scripts/openclaw_dispatch.py"
        )
        assert spec and spec.loader
        dispatcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatcher)
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(
            dispatcher.subprocess, "run", return_value=completed
        ) as invoked:
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
            canonical.parent.mkdir()
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
            automation_module.write_bytes(
                (ROOT / "scripts/openclaw_automation.py").read_bytes()
            )
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
            canonical.parent.mkdir()
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
            self.assertEqual(
                raised.exception.category, "repository_integrity_uncertainty"
            )

            subprocess.run(["git", "switch", "-q", bound_branch], cwd=repo, check=True)
            state = json.loads((repo / "ops/STATE.json").read_text())
            state.pop("branch")
            atomic_write_json(repo / "ops/STATE.json", state)
            with self.assertRaises(AutomationError) as missing:
                dispatcher.authorized_branch()
            self.assertEqual(
                missing.exception.category, "repository_integrity_uncertainty"
            )

    def test_actual_execed_hermes_worker_is_detected(self) -> None:
        rows = [
            "4321 Thu Aug 21 12:00:00 2026 /usr/local/bin/hermes --provider openai-codex --model gpt-5.6-sol"
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
                "stage": "independent_review",
                "implementation_complete": True,
                "scoped_changed_paths": [],
                "verified_paths": [],
                "verified_repository_fingerprint": fingerprint,
            }
            with (
                mock.patch.object(
                    dispatcher, "invoke_model", return_value=(0, "", usage)
                ),
                self.assertRaisesRegex(AutomationError, "JSON contract"),
            ):
                dispatcher.independent_review(record, {"actionable": True})
            self.assertEqual(record["review_verdict"], {})
            self.assertEqual(record["stage"], "independent_review")
            self.assertIsNone(record["repair_failure"])
            self.assertEqual(
                record["last_failure_category"], "empty_or_invalid_task_delivery"
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
            dispatcher.sanitized_implementation_result(base, ["candidate.txt"])[
                "blockers"
            ],
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
        self.assertEqual(
            secret.exception.category, "secret_credential_or_protected_operation"
        )
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
                'mkdir -p "$(dirname "$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE")"\n'
                'jq -cn --arg profile "$PROPERTY_RENTAL_VERIFICATION_PROFILE" '
                '\'{profile:$profile,result:"passed"}\' >"$PROPERTY_RENTAL_VERIFICATION_EVIDENCE_FILE"\n'
            )
            verification.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "verification harness"], cwd=repo, check=True
            )
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
                    "scoped_changed_paths": [
                        "scripts/openclaw-deterministic-verification.sh"
                    ],
                }
            )
            with self.assertRaises(AutomationError) as failure:
                dispatcher.deterministic_verification(record)
            self.assertEqual(failure.exception.category, "test_fixture_failure")
            self.assertEqual(record["stage"], "deterministic_verification")
            with self.assertRaises(AutomationError) as repeated:
                dispatcher.deterministic_verification(record)
            self.assertEqual(
                repeated.exception.category, "repeated_identical_tool_call"
            )
            self.assertIn("exit 125; failed gate database-test", str(repeated.exception))


class ContinuationAndAttemptTests(unittest.TestCase):
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
                dispatcher.verified_continuation_handoff(
                    "{}", record, "independent_review"
                )
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
                with mock.patch.object(
                    dispatcher, "relevant_processes", return_value=[]
                ):
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
                    dispatcher.consume_pending_continuation(
                        record, "independent_review"
                    )

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

    def test_interrupted_reservation_is_recovered_without_attempt_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt.json"
            reserve_attempt(path, stage="implementation", fingerprint="one")
            recovered = reserve_attempt(
                path, stage="implementation", fingerprint="one"
            )
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
                packet_fingerprint = dispatcher.packet_actionable_fingerprint(
                    record, packet
                )
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
                    dispatcher.invoke_model(
                        record, packet, model_policy("implementation")
                    )
            self.assertEqual(raised.exception.category, "gateway_or_network_failure")
            marker = dispatcher.terminal_marker(
                state_dir / "terminal", routing_fingerprint
            )
            self.assertIsNotNone(marker)
            assert marker is not None
            evidence = json.loads(marker.read_text())
            self.assertEqual(evidence["status"], "repair_exhausted")
            self.assertEqual(
                evidence["root_failure_category"], "gateway_or_network_failure"
            )
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
                packet_fingerprint = dispatcher.packet_actionable_fingerprint(
                    record, packet
                )
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
                    dispatcher.invoke_model(
                        record, packet, model_policy("direct_codex_recovery")
                    )
            self.assertEqual(raised.exception.category, "deterministic_test_failure")
            marker = dispatcher.terminal_marker(
                state_dir / "terminal", lifecycle_fingerprint
            )
            self.assertIsNotNone(marker)
            assert marker is not None
            evidence = json.loads(marker.read_text())
            self.assertEqual(evidence["status"], "repair_exhausted")
            self.assertEqual(evidence["stage"], "direct_codex_recovery")
            self.assertEqual(
                evidence["root_failure_category"], "deterministic_test_failure"
            )

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
            self.assertEqual(
                preserved["preserved_underlying_result"], "exit 70 after one API call"
            )
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
                mock.patch.object(
                    self.dispatch, "process_identity", return_value=identity
                ),
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

    def test_model_invocation_accounting_does_not_infer_missing_api_calls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = RepositoryEvidenceTests()
            repo = helper.make_repo(root)
            for name in ("openclaw-hermes-task.sh", "hermes-property-rental"):
                target = repo / "scripts" / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes((ROOT / "scripts" / name).read_bytes())
                target.chmod(0o755)
            fake = root / "fake-hermes.py"
            fake.write_text(
                """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
usage = os.environ['PROPERTY_RENTAL_HERMES_USAGE_FILE']
data = {'model':os.environ.get('RETURNED_MODEL','gpt-5.6-sol'),'configured_max_tokens':int(os.environ['HERMES_MAX_TOKENS']),'total_tokens':1}
if os.environ.get('INCLUDE_API_CALLS') == 'true': data['api_calls'] = 1
json.dump(data, open(usage, 'w'))
print('{}')
raise SystemExit(int(os.environ.get('FAKE_EXIT','0')))
"""
            )
            fake.chmod(0o755)
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
                        "INCLUDE_API_CALLS": "true",
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
            self.assertEqual(attempts["counters"].get("implementation", 0), 0)

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
            totals, unavailable = report.recent_model_usage(now=20)
            self.assertEqual(totals, [5])
            self.assertEqual(unavailable, 1)
            self.assertNotIn(0, totals)

    def test_daily_report_rejects_stale_success_as_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = RepositoryEvidenceTests().make_repo(root)
            preflight = repo / "scripts/openclaw-supervisor-preflight.sh"
            preflight.parent.mkdir(exist_ok=True)
            preflight.write_bytes(
                (ROOT / "scripts/openclaw-supervisor-preflight.sh").read_bytes()
            )
            preflight.chmod(0o755)
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "report harness"], cwd=repo, check=True
            )
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
                      consecutive_errors INTEGER, running_at_ms INTEGER
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
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)", row
                )
                connection.execute(
                    "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
            capture = Path(directory) / "args.json"
            fake = Path(directory) / "hermes"
            fake.write_text(
                '#!/bin/sh\npython3 -c \'import json,os,sys; open(os.environ["CAPTURE"],"w").write(json.dumps({"args":sys.argv[1:],"ceiling":os.environ.get("HERMES_MAX_TOKENS")}))\' "$@"\n'
            )
            fake.chmod(0o755)
            usage = Path(directory) / "usage.json"
            environment = os.environ.copy()
            environment.update(
                {
                    "CAPTURE": str(capture),
                    "PROPERTY_RENTAL_HERMES_BIN": str(fake),
                    "PROPERTY_RENTAL_HERMES_USAGE_FILE": str(usage),
                    "PROPERTY_RENTAL_HERMES_STAGE": "implementation",
                    "PROPERTY_RENTAL_HERMES_TOKEN_CEILING": "60000",
                }
            )
            subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), "compact task"],
                env=environment,
                check=True,
            )
            captured = json.loads(capture.read_text())
            arguments = captured["args"]
            self.assertEqual(captured["ceiling"], "60000")
            self.assertEqual(
                arguments[:7],
                [
                    "chat",
                    "--provider",
                    "openai-codex",
                    "--model",
                    "gpt-5.6-sol",
                    "--reasoning",
                    "high",
                ],
            )
            self.assertIn("file,skills,todo", arguments)
            self.assertIn("--quiet", arguments)
            self.assertNotIn("--oneshot", arguments)
            self.assertNotIn("--yolo", arguments)
            self.assertNotIn("--resume", arguments)
            self.assertNotIn("--continue", arguments)
            environment["PROPERTY_RENTAL_HERMES_STAGE"] = "independent_review"
            environment["PROPERTY_RENTAL_HERMES_TOKEN_CEILING"] = "90000"
            subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), "review"],
                env=environment,
                check=True,
            )
            captured = json.loads(capture.read_text())
            self.assertIn("xhigh", captured["args"])
            self.assertEqual(captured["ceiling"], "90000")
            environment["PROPERTY_RENTAL_HERMES_TOKEN_CEILING"] = "120000"
            exceptional_rejected = subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), "review"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(exceptional_rejected.returncode, 64)
            environment.update(
                {
                    "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_REASON": "preclassified broad review",
                    "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_REPOSITORY_FINGERPRINT": "f"
                    * 64,
                    "PROPERTY_RENTAL_EXCEPTIONAL_REVIEW_SCOPE": '["scripts/example"]',
                }
            )
            subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), "review"],
                env=environment,
                check=True,
            )
            self.assertEqual(json.loads(capture.read_text())["ceiling"], "120000")
            environment["PROPERTY_RENTAL_HERMES_STAGE"] = "implementation"
            environment["PROPERTY_RENTAL_HERMES_TOKEN_CEILING"] = "90000"
            rejected = subprocess.run(
                [str(ROOT / "scripts/hermes-property-rental"), "implementation"],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rejected.returncode, 64)
            self.assertIn("exact 60000-token ceiling", rejected.stderr)

    def test_empty_task_delivery_fails_before_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "empty"
            task.write_text(" \n")
            result = subprocess.run(
                [str(ROOT / "scripts/openclaw-hermes-task.sh"), str(task)],
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
            installed.write_bytes(
                (ROOT / "scripts/hermes-property-rental").read_bytes()
            )
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
                connection.execute(
                    "DELETE FROM cron_jobs WHERE job_id = 'different-supervisor-id'"
                )
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
