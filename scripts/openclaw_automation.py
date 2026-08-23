#!/usr/bin/env python3
"""Deterministic policy and durable evidence for Property Rental automation.

This module deliberately contains no model-driven routing.  The small shell
dispatcher calls these primitives to construct compact stage packets, enforce
the supported Hermes invocation contract, and persist resumable evidence.
"""

from __future__ import annotations

import ast
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
PRESERVATION_EVIDENCE_PATH: Final = "ops/AUTOMATION_REPAIR_EVIDENCE.json"
V1_019_ROUTING_REVISION: Final = "v1-019-sign-in-context-routing-v5"
V1_019_FRONTEND_CONTEXT_MAX_BYTES: Final = 90_000
V1_019_SUBSTAGE_IDS: Final = (
    "sign_in",
    "mfa_recovery",
    "sessions",
    "account_capability",
)
V1_019_SUBSTAGE_AUTHORITIES: Final = {
    "sign_in": ("UI-109", "UI-113", "TEST-094", "TEST-135"),
    "mfa_recovery": ("UI-110", "UI-112", "TEST-094", "TEST-135"),
    "sessions": ("UI-111", "TEST-094", "TEST-135"),
    "account_capability": ("UI-092", "UI-112", "TEST-094", "TEST-095", "TEST-135"),
}
V1_019_SUBSTAGE_ACCEPTANCE: Final = {
    substage: (
        "API contract and authorization tests",
        "frontend component/accessibility tests",
        "backend and frontend builds",
    )
    for substage in V1_019_SUBSTAGE_IDS
}
V1_019_SUBSTAGE_PATHS: Final = {
    "sign_in": (
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/styles.css",
        "frontend/src/authClient.ts",
        "frontend/src/authClient.test.ts",
    ),
    "mfa_recovery": (
        "backend/src/property_rental/account_recovery.py",
        "backend/src/property_rental/administrative_recovery.py",
        "backend/src/property_rental/mfa_policy.py",
        "backend/src/property_rental/recovery_code_lifecycle.py",
        "backend/tests/test_account_recovery.py",
        "backend/tests/test_administrative_recovery.py",
        "backend/tests/test_mfa_policy.py",
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/styles.css",
        "ops/traceability.json",
    ),
    "sessions": (
        "backend/src/property_rental/browser_session.py",
        "backend/src/property_rental/session_revocation.py",
        "backend/tests/test_browser_session.py",
        "backend/tests/test_session_revocation.py",
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/styles.css",
        "ops/traceability.json",
    ),
    "account_capability": (
        "backend/src/property_rental/access_admin_api.py",
        "backend/src/property_rental/app.py",
        "backend/tests/test_access_admin_api.py",
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/styles.css",
        "ops/traceability.json",
    ),
}
V1_020_ROUTING_REVISION: Final = "v1-020-security-hardening-routing-v2"
V1_020_SUBSTAGE_IDS: Final = (
    "authentication_core",
    "authentication_api",
    "sensitive_data_and_privileges",
    "mfa_policy",
    "recovery",
    "sessions_integration",
    "bootstrap_release",
)
V1_020_SUBSTAGE_AUTHORITIES: Final = {
    "authentication_core": (
        "TEST-108",
        "SEC-068",
        "SEC-069",
        "SEC-070",
    ),
    "authentication_api": ("TEST-109", "SEC-068", "SEC-069", "SEC-070"),
    "sensitive_data_and_privileges": (
        "TEST-110",
        "TEST-111",
        "SEC-068",
        "SEC-069",
    ),
    "mfa_policy": ("TEST-128", "SEC-068", "SEC-069", "SEC-075"),
    "recovery": (
        "TEST-129",
        "TEST-130",
        "SEC-071",
        "SEC-072",
        "SEC-075",
    ),
    "sessions_integration": (
        "TEST-131",
        "TEST-132",
        "TEST-135",
        "SEC-068",
        "SEC-069",
        "SEC-070",
        "SEC-075",
    ),
    "bootstrap_release": (
        "TEST-133",
        "TEST-134",
        "SEC-073",
        "SEC-074",
        "SEC-075",
    ),
}
V1_020_SUBSTAGE_ACCEPTANCE: Final = {
    substage: (
        "complete backend, frontend, database, integration, end-to-end, security, dependency, backup/restore, and traceability suites",
        "clean synchronized repository",
        "GitHub Actions success",
        "no unresolved non-protected v1 gap",
    )
    for substage in V1_020_SUBSTAGE_IDS
}
V1_020_SUBSTAGE_PATHS: Final = {
    "authentication_core": (
        "backend/src/property_rental/local_authentication.py",
        "backend/src/property_rental/password_security.py",
        "backend/tests/test_local_authentication.py",
        "backend/tests/test_password_security.py",
    ),
    "authentication_api": ("backend/src/property_rental/auth_api.py",),
    "sensitive_data_and_privileges": (
        "backend/src/property_rental/logging.py",
        "backend/tests/test_operations.py",
        "backend/tests/test_deployment_scaffolding.py",
        "scripts/postgres-init.sh",
        "config/deployment/identity-secret-contract.json",
    ),
    "mfa_policy": (
        "backend/src/property_rental/mfa_policy.py",
        "backend/src/property_rental/totp_security.py",
        "backend/tests/test_mfa_policy.py",
        "backend/tests/test_totp_security.py",
    ),
    "recovery": (
        "backend/src/property_rental/administrative_recovery.py",
        "backend/src/property_rental/recovery_code_lifecycle.py",
        "backend/tests/test_administrative_recovery.py",
        "backend/tests/test_recovery_code_security.py",
    ),
    "sessions_integration": (
        "backend/src/property_rental/browser_session.py",
        "backend/src/property_rental/session_revocation.py",
        "backend/tests/test_browser_session.py",
        "backend/tests/test_session_revocation.py",
    ),
    "bootstrap_release": (
        "backend/src/property_rental/initial_owner_bootstrap.py",
        "backend/src/property_rental/recovery_code_issuance.py",
        "backend/tests/test_initial_owner_bootstrap.py",
    ),
}
V1_021_ROUTING_REVISION: Final = "v1-021-audit-foundation-routing-v3"
V1_021_SUBSTAGE_IDS: Final = (
    "audit_storage",
    "append_service",
    "authorized_query",
)
V1_021_SUBSTAGE_AUTHORITIES: Final = {
    "audit_storage": (
        "DB-AUDIT-001",
        "DB-AUDIT-003",
        "SEC-031",
        "SEC-033",
    ),
    "append_service": (
        "PR-AUDIT-001",
        "PR-AUDIT-002",
        "PR-AUDIT-003",
        "PR-AUDIT-004",
        "PR-AUDIT-005",
        "PR-AUDIT-006",
        "PR-AUDIT-007",
        "PR-AUDIT-008",
        "PR-AUDIT-009",
        "PR-AUDIT-010",
        "PR-AUDIT-011",
        "DB-AUDIT-002",
        "SEC-030",
        "SEC-034",
    ),
    "authorized_query": (
        "API-023",
        "API-073",
        "API-074",
        "API-075",
        "SEC-032",
    ),
}
V1_021_SUBSTAGE_ACCEPTANCE: Final = {
    substage: (
        "forward-only migration and constraint tests on disposable real PostgreSQL",
        "domain/service tests",
        "full foundation gates",
        "GitHub Actions success",
    )
    for substage in V1_021_SUBSTAGE_IDS
}
V1_021_SUBSTAGE_PATHS: Final = {
    "audit_storage": (
        "backend/migrations/env.py",
        "backend/migrations/versions/20260820_09_protected_owner_bootstrap.py",
    ),
    "append_service": (
        "backend/src/property_rental/business_time.py",
        "backend/src/property_rental/identity.py",
        "backend/src/property_rental/property_scope.py",
        "backend/src/property_rental/local_authentication.py",
        "backend/src/property_rental/browser_session.py",
    ),
    "authorized_query": (
        "backend/src/property_rental/audit.py",
        "backend/src/property_rental/api.py",
    ),
}
V1_021_SUBSTAGE_WRITABLE_PATHS: Final = {
    "audit_storage": (
        "backend/migrations/versions/20260823_10_audit_events.py",
        "backend/tests/test_audit_migration.py",
    ),
    "append_service": (
        "backend/src/property_rental/audit.py",
        "backend/tests/test_audit.py",
    ),
    "authorized_query": (
        "backend/src/property_rental/audit_api.py",
        "backend/src/property_rental/app.py",
        "backend/tests/test_audit_api.py",
    ),
}
V1_022_ROUTING_REVISION: Final = "v1-022-property-configuration-routing-v1"
V1_022_SUBSTAGE_IDS: Final = ("property_storage", "property_api")
SUPERVISOR_OWNED_PROGRESS_CANDIDATES: Final = frozenset({"V1-022"})
V1_022_SUBSTAGE_AUTHORITIES: Final = {
    "property_storage": (
        "BR-PROP-001",
        "BR-PROP-002",
        "BR-PROP-003",
        "PR-PROP-001",
        "PR-PROP-002",
        "PR-PROP-003",
        "API-026",
        "API-027",
    ),
    "property_api": ("API-026", "API-027", "UI-091"),
}
V1_022_SUBSTAGE_ACCEPTANCE: Final = {
    substage: (
        "forward-only migration and constraint tests on disposable real PostgreSQL",
        "domain/service tests",
        "full foundation gates",
        "GitHub Actions success",
    )
    for substage in V1_022_SUBSTAGE_IDS
}
V1_022_SUBSTAGE_PATHS: Final = {
    "property_storage": (
        "backend/src/property_rental/business_time.py",
        "backend/src/property_rental/property_scope.py",
        "backend/tests/test_business_time.py",
        "backend/tests/test_property_scope.py",
        "backend/migrations/env.py",
        "backend/migrations/versions/20260823_10_audit_events.py",
    ),
    "property_api": (
        "backend/src/property_rental/property.py",
        "backend/src/property_rental/identity.py",
        "backend/src/property_rental/app.py",
        "backend/src/property_rental/settings.py",
        "backend/tests/test_property.py",
    ),
}
V1_022_SUBSTAGE_WRITABLE_PATHS: Final = {
    "property_storage": (
        "backend/migrations/versions/20260823_11_property_configuration.py",
        "backend/src/property_rental/property.py",
        "backend/tests/test_property.py",
        "backend/tests/test_property_migration.py",
    ),
    "property_api": (
        "backend/migrations/versions/20260823_11_property_configuration.py",
        "backend/migrations/versions/20260823_12_property_business_configuration.py",
        "backend/src/property_rental/property.py",
        "backend/src/property_rental/property_setup_cli.py",
        "backend/tests/test_property.py",
        "backend/tests/test_property_migration.py",
        "backend/src/property_rental/property_api.py",
        "backend/src/property_rental/app.py",
        "backend/tests/test_property_api.py",
        "backend/tests/test_traceability.py",
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/propertyClient.ts",
        "frontend/src/propertyClient.test.tsx",
    ),
}

RECOVERABLE_ROUTING_FAILURES: Final = frozenset(
    {
        "pre_model_infrastructure_failure",
        "unsupported_invocation_configuration",
        "empty_or_invalid_task_delivery",
        "verification_tooling_unavailable",
        "lock_or_overlapping_process_failure",
        "model_session_or_token_ceiling",
        "context_materialization_required",
    }
)

OWNER_BLOCKER_CATEGORIES: Final = frozenset(
    {
        "owner_policy_decision",
        "scope_or_policy_ambiguity",
        "secret_credential_or_protected_operation",
        "destructive_or_production_operation",
        "conflicting_owner_work",
        "protected_operation",
        "bounded_attempts_exhausted",
    }
)

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
        "context_materialization_required",
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


def failure_owner_action_required(category: str, *, exhausted: bool = False) -> bool:
    """Reserve Owner action for protected decisions or an exhausted bounded repair."""
    return exhausted or category in OWNER_BLOCKER_CATEGORIES


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
        return ModelPolicy(
            stage, PROVIDER, MODEL_ID, "high", ORDINARY_TOKEN_CEILING, "Hermes"
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
        "Hermes",
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
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "HEAD",
            "--",
        ],
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


def preserved_paths_fingerprint(repo: Path, paths: Iterable[str]) -> str:
    """Hash an exact path allowlist without including unrelated automation work."""
    entries: list[dict[str, str]] = []
    for relative in sorted(set(paths)):
        path = repo / relative
        if path.is_symlink():
            kind = "symlink"
            content = digest(os.readlink(path))
        elif path.is_file():
            kind = "regular"
            content = digest(path.read_bytes())
        else:
            kind = "missing"
            content = "missing"
        entries.append({"path": relative, "kind": kind, "sha256": content})
    return digest(entries)


def preservation_evidence(repo: Path) -> dict[str, Any]:
    """Validate the recorded preserved candidate paths and return safe evidence."""
    path = repo / PRESERVATION_EVIDENCE_PATH
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {
            "valid": False,
            "candidate": None,
            "branch": None,
            "baseline_head": None,
            "paths": [],
            "fingerprint": None,
        }
    if isinstance(value.get("predecessor_preservation_evidence"), dict):
        value = value["predecessor_preservation_evidence"]
    recorded = value.get("preserved_paths")
    if not isinstance(recorded, dict) or not recorded:
        return {
            "valid": False,
            "candidate": value.get("candidate"),
            "branch": value.get("baseline_branch"),
            "baseline_head": value.get("baseline_head"),
            "paths": [],
            "fingerprint": None,
        }
    paths = sorted(str(item) for item in recorded)
    hashes_match = all(
        isinstance(expected, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
        and (repo / relative).is_file()
        and digest((repo / relative).read_bytes()) == expected
        for relative, expected in recorded.items()
    )
    return {
        "valid": bool(
            hashes_match
            and value.get("automation_repair_may_modify_preserved_paths") is False
            and value.get("v1_019_may_start") is False
        ),
        "candidate": value.get("candidate"),
        "branch": value.get("baseline_branch"),
        "baseline_head": value.get("baseline_head"),
        "paths": paths,
        "fingerprint": preserved_paths_fingerprint(repo, paths),
    }


def _integer(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    ):
        return value
    return default


def _required_check_failed(state: dict[str, Any]) -> bool:
    repair = state.get("repair") or {}
    if isinstance(repair, dict) and any(
        repair.get(key) not in (None, "", False)
        for key in ("failed_check", "known_failing_check", "required_check_failed")
    ):
        return True
    tests = state.get("tests") or []
    return isinstance(tests, list) and any(
        isinstance(item, str) and item.strip().upper().startswith("FAIL:")
        for item in tests
    )


def _queue_successor(roadmap: dict[str, Any], current_id: str) -> dict[str, Any] | None:
    tranches = roadmap.get("tranches") or []
    if not isinstance(tranches, list):
        return None
    current = next(
        (
            item
            for item in tranches
            if isinstance(item, dict) and item.get("id") == current_id
        ),
        None,
    )
    if not isinstance(current, dict) or not isinstance(current.get("order"), int):
        return None
    status_by_id = {
        str(item.get("id")): item.get("status")
        for item in tranches
        if isinstance(item, dict) and item.get("id")
    }
    candidates = [
        item
        for item in tranches
        if isinstance(item, dict)
        and item.get("order") == current["order"] + 1
        and item.get("status") == "approved_ready"
        and item.get("authorization") == "durable_v1"
        and all(
            dependency == current_id or status_by_id.get(str(dependency)) == "complete"
            for dependency in item.get("dependencies") or []
        )
    ]
    return candidates[0] if len(candidates) == 1 else None


def classify_compact_state(repo: Path) -> dict[str, Any]:
    """Return the one authoritative lifecycle and blocker classification."""
    state = json.loads((repo / "ops/STATE.json").read_text())
    roadmap_path = repo / "ops/V1_ROADMAP.json"
    roadmap = json.loads(roadmap_path.read_text()) if roadmap_path.is_file() else {}
    queue_text = (repo / "ops/QUEUE.md").read_text()
    status = str(state.get("status") or "unknown")
    approval = state.get("approval") or {}
    candidate = state.get("next_candidate") or {}
    repair = state.get("repair") or {}
    if not isinstance(approval, dict):
        approval = {}
    if not isinstance(candidate, dict):
        candidate = {}
    if not isinstance(repair, dict):
        repair = {}

    branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "HEAD")
    upstream = git(repo, "rev-parse", "@{upstream}", check=False)
    state_branch = state.get("branch")
    roadmap_state = state.get("roadmap") or {}
    roadmap_current_id = str(
        (roadmap_state.get("current_id") if isinstance(roadmap_state, dict) else "")
        or ""
    )
    candidate_id = str(
        candidate.get("roadmap_id") or candidate.get("id") or roadmap_current_id
    )
    attempt_tranche_id = (
        candidate_id
        or roadmap_current_id
        or str(state.get("active_cycle") or state.get("task") or "unknown")
    )
    repair_tranche_id = str(repair.get("tranche_id") or "")
    repair_matches = bool(repair_tranche_id and repair_tranche_id == attempt_tranche_id)
    repair_attempts = _integer(
        repair.get("attempts") if repair_matches else 0,
        0,
        minimum=0,
        maximum=2,
    )
    repair_max_attempts = _integer(
        repair.get("max_attempts") if repair_matches else 2,
        2,
        minimum=1,
        maximum=2,
    )
    repair_failure = str(repair.get("failure") or "") if repair_matches else ""
    owner_action = str(state.get("owner_action") or "").strip()
    protected_flags = {
        "requires_owner_decision": repair.get("requires_owner_decision") is True,
        "suspected_secret": repair.get("suspected_secret") is True,
        "scope_expansion": repair.get("scope_expansion") is True,
        "protected_operation": repair.get("protected_operation") is True
        or candidate.get("protected_operation") is True,
    }
    owner_category: str | None = None
    if repair_failure in OWNER_BLOCKER_CATEGORIES:
        owner_category = repair_failure
    elif protected_flags["suspected_secret"]:
        owner_category = "secret_credential_or_protected_operation"
    elif protected_flags["protected_operation"]:
        owner_category = "protected_operation"
    elif protected_flags["scope_expansion"]:
        owner_category = "scope_or_policy_ambiguity"
    elif protected_flags["requires_owner_decision"] or owner_action not in {"", "none"}:
        owner_category = "owner_policy_decision"
    elif repair_attempts >= repair_max_attempts and repair_failure:
        owner_category = "bounded_attempts_exhausted"

    blockers = state.get("blockers") or []
    blocker_count = len(blockers) if isinstance(blockers, list) else 1
    recorded_next_action = str(state.get("next_action") or "")
    next_action = recorded_next_action
    durable_v1 = (
        "Remaining v1 application tranches are authorized when bounded by canonical documents"
        in queue_text
    )
    automation_repair = state.get("automation_repair") or {}
    if not isinstance(automation_repair, dict):
        automation_repair = {}
    successor_hold = bool(
        status == "published"
        and roadmap_current_id == "V1-019"
        and automation_repair.get("stop_after_candidate") == "V1-019"
    )
    implementation_started = approval.get("implementation_started") is True
    implementation_completed = approval.get("implementation_completed") is True
    publication_completed = approval.get("publication_completed") is True
    approval_status = str(approval.get("status") or "unknown")
    candidate_status = str(candidate.get("status") or "unknown")
    candidate_task = str(candidate.get("task") or "")
    candidate_concrete = bool(
        candidate_id and candidate_task and candidate.get("phase")
    )
    candidate_current = bool(candidate_id and candidate_id == roadmap_current_id)
    changed = changed_paths(repo)
    preservation = preservation_evidence(repo)
    branch_exact = bool(branch and state_branch == branch)
    head_synchronized = bool(head and upstream == head)
    state_commit = str(state.get("commit") or "")
    state_commit_ancestor = bool(
        re.fullmatch(r"[0-9a-f]{40}", state_commit)
        and subprocess.run(
            ["git", "merge-base", "--is-ancestor", state_commit, head],
            cwd=repo,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    try:
        no_overlap = relevant_processes(repo) == []
    except (OSError, subprocess.SubprocessError):
        no_overlap = False
    capability_continuation = bool(
        status == "partial"
        and approval_status == "approved_ready"
        and implementation_started
        and not publication_completed
        and repair_matches
        and repair_failure == "verification_tooling_unavailable"
        and repair.get("scope_preserved") is True
        and repair_attempts < repair_max_attempts
        and owner_category is None
        and owner_action == "none"
        and not _required_check_failed(state)
        and candidate_current
        and branch_exact
        and head_synchronized
        and state_commit_ancestor
        and no_overlap
        and preservation.get("valid") is True
        and preservation.get("candidate") == candidate_id
        and preservation.get("branch") == branch
        and sorted(changed) == sorted(preservation.get("paths") or [])
    )

    known_statuses = {
        "approved_ready",
        "active",
        "in_progress",
        "partial",
        "verified_for_review",
        "complete_unpublished",
        "complete_uncommitted",
        "published",
        "failed",
        "not_verified",
        "discrepancy",
        "repair_required",
        "verified_unpublished",
        "implemented_awaiting_supervisor_review",
    }
    state_issue = ""
    lifecycle = "idle"
    blocker_category = owner_category or (repair_failure or None)
    owner_action_required = owner_category is not None
    actionable = False
    implementation_allowed = False
    normalized = False

    if owner_category is not None:
        lifecycle = "owner_blocked"
        state_issue = owner_category
        actionable = False
        normalized = True
    elif (
        status == "verified_unpublished"
        and implementation_completed
        and not publication_completed
    ):
        lifecycle = "post_publication_reconciliation_pending"
        state_issue = "published_compact_state_reconciliation_required"
        next_action = (
            "Reconcile the already-published candidate into compact state after "
            "proving synchronized HEAD and successful CI."
        )
        actionable = True
        normalized = True
    elif capability_continuation:
        lifecycle = "verification_pending"
        state_issue = "capability_verification_continuation"
        next_action = (
            "Resume the exact preserved candidate at deterministic verification; "
            "do not rerun implementation."
        )
        actionable = True
        normalized = True
        implementation_allowed = False
    elif implementation_completed and not publication_completed:
        lifecycle = "review_publication_pending"
        state_issue = "completed_tranche_publication_action_enforced"
        next_action = (
            "Independently verify and publish the completed bounded tranche under "
            "standing authorization, then dispatch the next approved candidate."
        )
        actionable = True
        normalized = True
    elif (
        status == "approved_ready"
        and not next_action
        and candidate_status == "approved_ready"
        and candidate_task
    ):
        lifecycle = "implementation_pending"
        state_issue = "missing_next_action_derived_from_approved_candidate"
        next_action = f"Implement the approved bounded candidate: {candidate_task}"
        actionable = True
        implementation_allowed = True
        normalized = True
    elif (
        status == "published"
        and not candidate_current
        and candidate_status == "approved_ready"
        and candidate_task
    ):
        lifecycle = "implementation_pending"
        state_issue = "published_next_candidate_dispatch_required"
        next_action = f"Implement the approved bounded candidate: {candidate_task}"
        actionable = True
        implementation_allowed = True
        normalized = True
    elif successor_hold:
        lifecycle = "scheduler_healthy_idle"
        state_issue = "successor_held_by_approved_scope"
        next_action = (
            "Keep V1-020 unselected; V1-019 is the approved terminal boundary for "
            "this restoration workflow."
        )
        actionable = False
        implementation_allowed = False
        normalized = True
    elif (
        status == "published"
        and durable_v1
        and (not candidate_concrete or candidate_current)
    ):
        successor = _queue_successor(roadmap, roadmap_current_id)
        if successor and successor.get("protected_operation") is not True:
            lifecycle = "successor_activation_pending"
            state_issue = "authorized_candidate_selection_required"
            next_action = (
                "Materialize the exact structured approved successor from "
                "ops/V1_ROADMAP.json without a model, then dispatch it immediately."
            )
            actionable = True
        else:
            lifecycle = "owner_blocked"
            state_issue = "handoff_missing"
            next_action = (
                "No unique safe structured successor exists for the published phase. "
                "Record an explicit bounded candidate or protected Owner-decision reason."
            )
        normalized = True
    elif (
        status in {"failed", "not_verified", "discrepancy", "repair_required"}
        and approval_status
        in {"approved_ready", "approved_active", "approved_complete"}
        and repair.get("scope_preserved") is True
        and repair_failure
        and repair_attempts < repair_max_attempts
    ):
        lifecycle = "bounded_repair_pending"
        state_issue = "bounded_automatic_repair_authorized"
        next_action = (
            f"Perform bounded automatic repair attempt {repair_attempts + 1} of "
            f"{repair_max_attempts} for the already-approved tranche: {repair_failure}."
        )
        actionable = True
        implementation_allowed = True
        normalized = True
    elif blocker_count:
        lifecycle = "blocked_unclassified"
        state_issue = "structured_blocker_required"
        blocker_category = "repository_integrity_uncertainty"
        actionable = False
        normalized = True
    elif (
        status not in known_statuses
        and approval_status
        in {"approved_ready", "approved_active", "approved_complete"}
        and durable_v1
    ):
        lifecycle = "state_contract_repair_pending"
        state_issue = "state_contract_repair_authorized"
        next_action = f"Perform a bounded compact-state contract repair for unrecognized status {status!r}."
        actionable = True
        normalized = True
    elif status in {"approved_ready", "active", "in_progress"} and next_action:
        lifecycle = "implementation_pending"
        actionable = True
        implementation_allowed = True
    elif (
        status
        in {
            "verified_for_review",
            "verified_unpublished",
            "complete_unpublished",
            "complete_uncommitted",
            "implemented_awaiting_supervisor_review",
        }
        and next_action
    ):
        lifecycle = "review_publication_pending"
        actionable = True
    elif status not in known_statuses:
        lifecycle = "owner_blocked"
        state_issue = "state_contract_violation"
        blocker_category = "scope_or_policy_ambiguity"
        owner_action_required = True
        next_action = (
            "Resolve the unrecognized compact-state contract before dispatch; "
            "no safe authorized normalization is available."
        )
        normalized = True

    if (
        isinstance(automation_repair, dict)
        and automation_repair.get("status", "restored") != "restored"
    ):
        lifecycle = "automation_repair_hold"
        state_issue = "automation_repair_publication_required"
        next_action = str(
            automation_repair.get("next_action")
            or "Publish and restore the bounded automation repair before candidate dispatch."
        )
        actionable = False
        normalized = True
        implementation_allowed = False

    current_roadmap = next(
        (
            item
            for item in roadmap.get("tranches") or []
            if isinstance(item, dict) and item.get("id") == roadmap_current_id
        ),
        {},
    )
    return {
        "head": head,
        "branch": branch,
        "upstream": upstream,
        "status": status,
        "lifecycle": lifecycle,
        "blocker_category": blocker_category,
        "owner_action_required": owner_action_required,
        "active_cycle": state.get("active_cycle") or state.get("task") or "unknown",
        "attempt_tranche_id": attempt_tranche_id,
        "candidate": candidate_id,
        "next_action": next_action,
        "recorded_next_action": recorded_next_action,
        "state_issue": state_issue,
        "automation_repair_status": (
            automation_repair.get("status", "restored")
            if isinstance(automation_repair, dict)
            else "restored"
        ),
        "repair_tranche_id": repair_tranche_id,
        "repair_matches_tranche": repair_matches,
        "repair_failure": repair_failure,
        "normalized": normalized,
        "blockers": blocker_count,
        "repair_attempts": repair_attempts,
        "repair_max_attempts": repair_max_attempts,
        "durable_v1_authorization": durable_v1,
        "candidate_is_concrete": candidate_concrete,
        "status_known": status in known_statuses,
        "implementation_started": implementation_started,
        "implementation_completed": implementation_completed,
        "implementation_allowed": implementation_allowed,
        "publication_completed": publication_completed,
        "queue_candidate": _queue_successor(roadmap, roadmap_current_id),
        "roadmap": {
            "current_id": roadmap_current_id,
            "current_status": current_roadmap.get("status", "unknown"),
            "total": roadmap.get("total_tranches", 0),
            "completed": sum(
                1
                for item in roadmap.get("tranches") or []
                if isinstance(item, dict) and item.get("status") == "complete"
            ),
        },
        "worktree": repository_fingerprint(repo),
        "preserved_worktree_fingerprint": preservation.get("fingerprint"),
        "preservation_valid": preservation.get("valid") is True,
        "exact_identity": {
            "candidate": candidate_id,
            "branch": branch,
            "head": head,
            "preserved_worktree_fingerprint": preservation.get("fingerprint"),
            "no_failed_check": not _required_check_failed(state),
            "no_overlap": no_overlap,
            "approved_scope": repair.get("scope_preserved") is True,
            "owner_action_none": owner_action == "none",
        },
        "actionable": actionable,
    }


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
    repositories = {str(repo), str(repo.resolve())}
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
        normalized_lower = normalized.lower()
        repository_codex_worker = bool(
            any(repository in normalized for repository in repositories)
            and re.search(r"(?:^|\s)\S*codex\S*(?:\s|$)", normalized_lower)
        )
        if (
            not hermes_worker
            and not repository_codex_worker
            and not any(needle in normalized for needle in needles)
        ):
            continue
        # A generic OpenClaw gateway is not a candidate worker. Repository-bound
        # Codex processes are workers; persist only a digest, never raw arguments.
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
    routing_identity: dict[str, Any] | None = None,
) -> str:
    """Bind a terminal/attempt decision to every actionable state input."""
    return digest(
        {
            **actionable_fingerprint(repo, preflight),
            "candidate": candidate,
            "stage": stage,
            "routing_identity": routing_identity or {},
        }
    )


def v1_019_routing_identity(
    record: dict[str, Any], stage: str | None = None
) -> dict[str, Any]:
    """Return the shared dispatcher/health identity for a bounded candidate route."""
    candidate = record.get("candidate")
    routes = {
        "V1-019": (V1_019_ROUTING_REVISION, V1_019_SUBSTAGE_IDS),
        "V1-020": (V1_020_ROUTING_REVISION, V1_020_SUBSTAGE_IDS),
        "V1-022": (V1_022_ROUTING_REVISION, V1_022_SUBSTAGE_IDS),
    }
    route = routes.get(candidate)
    if route is None:
        return {}
    revision, substages = route
    completed = set(record.get("completed_implementation_substages") or [])
    substage = next((item for item in substages if item not in completed), None)
    return {
        "revision": revision,
        "lifecycle_stage": stage or record.get("stage"),
        "bounded_substage": substage,
        "recovery_generation": int(record.get("recovery_generation") or 0),
    }


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
        "api_calls_started": available("api_calls_started"),
        "api_calls_completed": available("api_calls"),
        "counted_token_definition": available("counted_token_definition"),
        "cache_read_double_counted": available("cache_read_double_counted"),
        "cumulative_boundary": available("cumulative_boundary"),
        "boundary_reached": available("boundary_reached"),
        "next_api_call_blocked": available("next_api_call_blocked"),
        "reservation_blocked": available("reservation_blocked"),
        "predicted_next_context_tokens": available("predicted_next_context_tokens"),
        "token_estimation_status": available("token_estimation_status"),
        "token_estimate_method": available("token_estimate_method"),
        "token_estimate_inputs": available("token_estimate_inputs"),
        "token_estimate_validation_margin_tokens": available(
            "token_estimate_validation_margin_tokens"
        ),
        "token_estimate_provider_validated": available(
            "token_estimate_provider_validated"
        ),
        "token_estimate_observed_shortfall_tokens": available(
            "token_estimate_observed_shortfall_tokens"
        ),
        "reserved_completion_checkpoint_tokens": available(
            "reserved_completion_checkpoint_tokens"
        ),
        "context_reservation_margin_tokens": available(
            "context_reservation_margin_tokens"
        ),
        "locally_reserved_next_call_tokens": available(
            "locally_reserved_next_call_tokens"
        ),
        "provider_completion_limit_mode": available("provider_completion_limit_mode"),
        "provider_request_omits_max_output_tokens": available(
            "provider_request_omits_max_output_tokens"
        ),
        "unsupported_provider_parameters_removed": available(
            "unsupported_provider_parameters_removed"
        ),
        "reservation_violation": available("reservation_violation"),
        "in_flight_overshoot_tokens": available("in_flight_overshoot_tokens"),
        "tool_output_limit_bytes": available("tool_output_limit_bytes"),
        "session_tool_output_limit_bytes": available("session_tool_output_limit_bytes"),
        "tool_output_observed_bytes": available("tool_output_observed_bytes"),
        "tool_output_returned_bytes": available("tool_output_returned_bytes"),
        "tool_output_truncations": available("tool_output_truncations"),
        "tool_output_control_bytes": available("tool_output_control_bytes"),
        "tool_output_batch_rejections": available("tool_output_batch_rejections"),
        "tool_output_batch_rejections_delivered": available(
            "tool_output_batch_rejections_delivered"
        ),
        "context_materialization_checkpoint": available(
            "context_materialization_checkpoint"
        ),
        "applicable_token_ceiling": policy.token_ceiling,
        "stage_name": policy.stage,
        "complex_review_classification_reason": policy.complex_review_reason,
    }


def validate_usage(usage: dict[str, Any], policy: ModelPolicy) -> None:
    returned_model = usage.get("model")
    if not isinstance(returned_model, str) or returned_model.split("/")[-1] != MODEL_ID:
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
    ceiling_stop = stop_reason in {
        "tool_ceiling",
        "session_ceiling",
        "token_ceiling",
        "proactive_budget_reservation",
        "length",
        "max_tokens",
        "max_turns",
    }
    if total is not None and (not isinstance(total, int) or total < 0):
        raise AutomationError(
            "pre_model_infrastructure_failure",
            "provider returned malformed total_tokens metadata",
        )
    if (
        ceiling_stop
        or usage.get("boundary_reached") is True
        or usage.get("reservation_violation") is True
        or usage.get("reservation_blocked") is True
        or isinstance(total, int)
        and total > policy.token_ceiling
    ):
        raise AutomationError(
            "model_session_or_token_ceiling",
            (
                f"provider reported {stop_reason} at the configured ceiling"
                if ceiling_stop
                else f"observed {total} tokens above ceiling {policy.token_ceiling}"
                if isinstance(total, int) and total > policy.token_ceiling
                else f"observed token-boundary evidence at ceiling {policy.token_ceiling}"
            ),
        )
    if stop_reason == "context_materialization_required":
        raise AutomationError(
            "context_materialization_required",
            "the complete parallel tool batch exceeded its atomic context allowance",
        )
    if total is None:
        return


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
        if isinstance(value, (int, str, bytes, bytearray)):
            return int(value)
        return None

    input_tokens = exact_metric(usage["input_tokens"], session["input_tokens"])
    output_tokens = exact_metric(usage["output_tokens"], session["output_tokens"])
    cache_read = exact_metric(usage["cache_read_tokens"], session["cache_read_tokens"])
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


AUTHORITY_PATHS: Final = {
    "BR": "docs/002_BUSINESS_RULES.md",
    "PR": "docs/003_PRODUCT_REQUIREMENTS.md",
    "DB": "docs/004_DATABASE_MODEL.md",
    "API": "docs/005_API_SPECIFICATION.md",
    "UI": "docs/006_UI_SPECIFICATION.md",
    "TEST": "docs/007_TESTING_STRATEGY.md",
    "SEC": "docs/008_SECURITY_MODEL.md",
    "DEPLOY": "docs/009_DEPLOYMENT_ARCHITECTURE.md",
    "DL": "docs/010_DECISION_LOG.md",
}


def expand_authorities(
    authorities: list[object], *, repo: Path | None = None
) -> list[str]:
    """Expand compact numeric ranges and repository-backed wildcard authorities."""
    expanded: list[str] = []
    for raw in authorities:
        authority = str(raw)
        if "*" in authority and repo is not None:
            prefix = authority.split("-", 1)[0]
            relative = AUTHORITY_PATHS.get(prefix)
            if relative is None:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    f"authority wildcard {authority!r} has no canonical document route",
                )
            document = (repo / relative).read_text()
            expression = re.compile(
                "^" + re.escape(authority).replace(r"\*", ".*") + "$"
            )
            matches = [
                match.group(1)
                for match in re.finditer(
                    r"^#{2,6} ([A-Z]+-[A-Z0-9][A-Z0-9-]*)(?:\s+—[^\n]*)?$",
                    document,
                    re.MULTILINE,
                )
                if expression.fullmatch(match.group(1))
            ]
            if not matches:
                raise AutomationError(
                    "repository_integrity_uncertainty",
                    f"authority wildcard {authority!r} matched no canonical requirement",
                )
            expanded.extend(matches)
            continue
        match = re.fullmatch(r"([A-Z]+)-(\d+)(?:-(\d+))?", authority)
        if not match:
            expanded.append(authority)
            continue
        prefix, first_text, last_text = match.groups()
        if last_text is None:
            expanded.append(authority)
            continue
        first = int(first_text)
        last = int(last_text)
        if last < first or last - first > 20:
            raise AutomationError(
                "repository_integrity_uncertainty",
                f"authority range {authority!r} is invalid",
            )
        width = len(first_text)
        expanded.extend(
            f"{prefix}-{number:0{width}d}" for number in range(first, last + 1)
        )
    return list(dict.fromkeys(expanded))


def candidate_relevant_paths(
    repo: Path, authorities: list[str], candidate: dict[str, Any]
) -> list[str]:
    """Derive a small deterministic path set for non-specialized candidates.

    Exact traceability paths win. Existing source siblings and bounded profile
    templates provide implementation context without granting broad discovery.
    """
    paths: list[str] = []
    traceability_path = repo / "ops/traceability.json"
    if traceability_path.is_file():
        try:
            traceability = json.loads(traceability_path.read_text())
        except json.JSONDecodeError as error:
            raise AutomationError(
                "repository_integrity_uncertainty",
                "candidate traceability is not valid JSON",
            ) from error
        authority_set = set(authorities)
        for entry in traceability.get("entries") or []:
            if not isinstance(entry, dict) or not authority_set.intersection(
                str(item) for item in entry.get("upstream_ids") or []
            ):
                continue
            relative = entry.get("test_path")
            if isinstance(relative, str) and (repo / relative).is_file():
                paths.append(relative)
                match = re.fullmatch(r"backend/tests/test_(.+)\.py", relative)
                if match:
                    source = f"backend/src/property_rental/{match.group(1)}.py"
                    if (repo / source).is_file():
                        paths.append(source)
                frontend = re.fullmatch(r"frontend/src/(.+)\.test\.(tsx?|jsx?)", relative)
                if frontend:
                    for extension in ("tsx", "ts", "jsx", "js"):
                        source = f"frontend/src/{frontend.group(1)}.{extension}"
                        if (repo / source).is_file():
                            paths.append(source)
                            break

    profile = str(candidate.get("acceptance_profile") or "")
    templates = {
        "api_ui": (
            "backend/src/property_rental/app.py",
            "backend/src/property_rental/api.py",
            "frontend/src/App.tsx",
            "frontend/src/App.test.tsx",
        ),
        "database": (
            "backend/tests/test_migrations.py",
            "backend/src/property_rental/identity.py",
        ),
        "financial": (
            "backend/src/property_rental/api.py",
            "backend/tests/test_migrations.py",
        ),
        "release": (
            "backend/tests/test_traceability.py",
            "ops/traceability.json",
        ),
    }
    paths.extend(
        relative
        for relative in templates.get(profile, ())
        if (repo / relative).is_file()
    )
    return list(dict.fromkeys(paths))[:16]


def authoritative_excerpt(repo: Path, authority: str, relative: str) -> str:
    """Return exactly one canonical requirement section, never the full document."""
    document = (repo / relative).read_text()
    heading = re.compile(
        rf"^(?P<depth>\#{{2,6}}) {re.escape(authority)}(?:\s+—[^\n]*)?\n(?:\n)?",
        re.MULTILINE,
    )
    match = heading.search(document)
    if match is None:
        raise AutomationError(
            "repository_integrity_uncertainty",
            f"authoritative requirement {authority} is missing from {relative}",
        )
    depth = len(match.group("depth"))
    next_heading = re.search(
        rf"^\#{{1,{depth}}}\s", document[match.end() :], re.MULTILINE
    )
    end = match.end() + next_heading.start() if next_heading else len(document)
    return document[match.start() : end].strip()


def _ast_excerpt(source: str, node: ast.AST) -> str:
    """Return one decorator-aware, line-bounded Python syntax excerpt."""
    start = int(getattr(node, "lineno", 1))
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        start = min(start, *(int(item.lineno) for item in decorators))
    end = int(getattr(node, "end_lineno", start))
    return "\n".join(source.splitlines()[start - 1 : end]).rstrip()


def sign_in_backend_contract(repo: Path) -> dict[str, Any]:
    """Materialize only the login transport contract needed by the frontend.

    The dispatcher, rather than Hermes, performs this deterministic source read.
    Full backend modules and test suites are never exposed to the bounded worker.
    """
    relative = "backend/src/property_rental/auth_api.py"
    source = (repo / relative).read_text()
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the local authentication API cannot be materialized",
        ) from error
    wanted = {
        "AuthenticationPhase",
        "LoginRequest",
        "SessionData",
        "AuthenticationData",
        "AuthenticationResponse",
    }
    symbols: list[dict[str, Any]] = []
    login_route: dict[str, Any] | None = None
    router_prefix: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "router"
            for target in node.targets
        ):
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "APIRouter"
            ):
                prefix = next(
                    (item.value for item in call.keywords if item.arg == "prefix"), None
                )
                if isinstance(prefix, ast.Constant) and isinstance(prefix.value, str):
                    router_prefix = prefix.value
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in wanted and isinstance(node, ast.ClassDef):
                symbols.append(
                    {
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "excerpt": _ast_excerpt(source, node),
                    }
                )
            login_decorator = next(
                (
                    decorator
                    for decorator in node.decorator_list
                    if isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "router"
                    and decorator.func.attr == "post"
                ),
                None,
            )
            if node.name == "login" and login_decorator is not None:
                route_argument = (
                    login_decorator.args[0]
                    if isinstance(login_decorator, ast.Call) and login_decorator.args
                    else None
                )
                route_path = (
                    route_argument.value
                    if isinstance(route_argument, ast.Constant)
                    and isinstance(route_argument.value, str)
                    else None
                )
                if router_prefix is None or route_path is None:
                    raise AutomationError(
                        "repository_integrity_uncertainty",
                        "the local sign-in router prefix or route path is not a string literal",
                    )
                login_route = {
                    "method": "POST",
                    "router_prefix": router_prefix,
                    "route_path": route_path,
                    "path": router_prefix.rstrip("/") + "/" + route_path.lstrip("/"),
                    "start_line": min(
                        [node.lineno] + [item.lineno for item in node.decorator_list]
                    ),
                    "end_line": node.end_lineno,
                    "excerpt": _ast_excerpt(source, node),
                }
    if (
        {item["name"] for item in symbols} != wanted
        or login_route is None
        or login_route["path"] != "/api/v1/auth/login"
    ):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the exact local sign-in API symbols or route are missing",
        )
    return {
        "path": relative,
        "source_sha256": digest(source),
        "symbols": sorted(symbols, key=lambda item: int(item["start_line"])),
        "route_inventory": [login_route],
    }


def complete_small_frontend_evidence(repo: Path) -> list[dict[str, Any]]:
    """Embed current bounded frontend evidence, including authorized partial work."""
    evidence: list[dict[str, Any]] = []
    total_bytes = 0
    for relative in (
        "frontend/src/App.tsx",
        "frontend/src/App.test.tsx",
        "frontend/src/styles.css",
    ):
        source = repo / relative
        if not source.exists():
            evidence.append(
                {
                    "path": relative,
                    "present": False,
                    "sha256": None,
                    "byte_length": 0,
                    "complete_content": None,
                }
            )
            continue
        if not source.is_file():
            raise AutomationError(
                "repository_integrity_uncertainty",
                f"authorized frontend evidence is not a regular file: {relative}",
            )
        content = source.read_text()
        content_bytes = len(content.encode())
        total_bytes += content_bytes
        evidence.append(
            {
                "path": relative,
                "present": True,
                "sha256": digest(content),
                "byte_length": content_bytes,
                "complete_content": content,
            }
        )
    if total_bytes > V1_019_FRONTEND_CONTEXT_MAX_BYTES:
        raise AutomationError(
            "context_materialization_required",
            "the complete current frontend evidence exceeded the aggregate "
            f"{V1_019_FRONTEND_CONTEXT_MAX_BYTES}-byte packet bound",
        )
    return evidence


def v1_021_authorized_query_integration_contract(repo: Path) -> dict[str, Any]:
    """Materialize only the application-factory syntax needed for audit wiring."""
    relative = "backend/src/property_rental/app.py"
    source = (repo / relative).read_text()
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as error:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the application factory cannot be materialized for audit routing",
        ) from error

    excerpts: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        include = False
        label = ""
        if isinstance(node, ast.ImportFrom) and node.module == "property_rental.audit_api":
            include = True
            label = "audit_api_import"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "audit_query_unavailable",
            "audit_query_forbidden",
            "audit_query_not_found",
            "audit_query_invalid",
        }:
            include = True
            label = node.name
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            rendered = _ast_excerpt(source, node)
            if "app.include_router" in rendered and "create_audit_router" in rendered:
                include = True
                label = "audit_router_registration"
        if include:
            excerpts.append(
                {
                    "label": label,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                    "excerpt": _ast_excerpt(source, node),
                }
            )

    create_app = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "create_app"
        ),
        None,
    )
    labels = {item["label"] for item in excerpts}
    required = {
        "audit_api_import",
        "audit_query_unavailable",
        "audit_query_forbidden",
        "audit_query_not_found",
        "audit_query_invalid",
        "audit_router_registration",
    }
    if create_app is None or labels != required:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the exact audit application integration points are unavailable",
        )
    arguments = [*create_app.args.posonlyargs, *create_app.args.args]
    parameter_index = next(
        (
            index
            for index, argument in enumerate(arguments)
            if argument.arg == "audit_query_flow"
        ),
        None,
    )
    default_start = len(arguments) - len(create_app.args.defaults)
    if parameter_index is None or parameter_index < default_start:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the exact audit query factory parameter is unavailable",
        )
    parameter = arguments[parameter_index]
    default = create_app.args.defaults[parameter_index - default_start]
    if parameter.annotation is None:
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the audit query factory parameter has no materialized annotation",
        )
    rendered_parameter = (
        f"{parameter.arg}: {ast.unparse(parameter.annotation)} = {ast.unparse(default)}"
    )
    if rendered_parameter != "audit_query_flow: AuditEventQueryFlow | None = None":
        raise AutomationError(
            "repository_integrity_uncertainty",
            "the audit query factory parameter drifted from the bounded integration contract",
        )
    return {
        "path": relative,
        "factory_parameter": rendered_parameter,
        "factory_start_line": create_app.lineno,
        "syntax_excerpts": sorted(excerpts, key=lambda item: int(item["start_line"])),
    }


def task_packet(
    repo: Path,
    preflight: dict[str, Any],
    stage: str,
    *,
    candidate_id_override: str | None = None,
    bounded_substage: dict[str, Any] | None = None,
    recovery_generation: int = 0,
    recovery_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = json.loads((repo / "ops/STATE.json").read_text())
    roadmap = json.loads((repo / "ops/V1_ROADMAP.json").read_text())
    candidate = state.get("next_candidate") or {}
    candidate_id = candidate_id_override or (
        candidate.get("roadmap_id")
        or candidate.get("id")
        or (state.get("roadmap") or {}).get("current_id")
    )
    supervisor_owned_progress = (
        str(candidate_id) in SUPERVISOR_OWNED_PROGRESS_CANDIDATES
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
    preserved = preservation_evidence(repo)
    raw_authorities = (
        roadmap_item.get("authorities") or candidate.get("authorities") or []
    )
    candidate_authorities = expand_authorities(raw_authorities, repo=repo)
    substage_id = str((bounded_substage or {}).get("id") or "")
    substage_authorities = {
        "V1-019": V1_019_SUBSTAGE_AUTHORITIES,
        "V1-020": V1_020_SUBSTAGE_AUTHORITIES,
        "V1-021": V1_021_SUBSTAGE_AUTHORITIES,
        "V1-022": V1_022_SUBSTAGE_AUTHORITIES,
    }.get(str(candidate_id), {})
    authorities = list(
        substage_authorities.get(substage_id, tuple(candidate_authorities))
    )
    if any(authority not in candidate_authorities for authority in authorities):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "bounded substage authority routing exceeds the approved candidate",
        )
    excerpts = [
        {
            "authority": authority,
            "path": path,
            "excerpt": authoritative_excerpt(repo, authority, path),
        }
        for authority in authorities
        for prefix, path in AUTHORITY_PATHS.items()
        if authority.startswith(prefix + "-")
    ]
    complete_acceptance = roadmap_item.get("acceptance") or (
        roadmap.get("acceptance_profiles") or {}
    ).get(roadmap_item.get("acceptance_profile") or "complete", [])
    substage_acceptance_map = {
        "V1-019": V1_019_SUBSTAGE_ACCEPTANCE,
        "V1-020": V1_020_SUBSTAGE_ACCEPTANCE,
        "V1-021": V1_021_SUBSTAGE_ACCEPTANCE,
        "V1-022": V1_022_SUBSTAGE_ACCEPTANCE,
    }.get(str(candidate_id), {})
    substage_acceptance = list(
        substage_acceptance_map.get(substage_id, tuple(complete_acceptance))
    )
    if any(item not in complete_acceptance for item in substage_acceptance):
        raise AutomationError(
            "repository_integrity_uncertainty",
            "bounded substage acceptance routing exceeds the approved profile",
        )
    substage_paths = {
        "V1-019": V1_019_SUBSTAGE_PATHS,
        "V1-020": V1_020_SUBSTAGE_PATHS,
        "V1-021": V1_021_SUBSTAGE_PATHS,
        "V1-022": V1_022_SUBSTAGE_PATHS,
    }.get(str(candidate_id), {})
    directly_relevant_paths = list(substage_paths.get(substage_id, ()))
    materialized_repository_evidence: list[dict[str, str]] = []
    if str(candidate_id) in {"V1-021", "V1-022"} and substage_id in {
        *V1_021_SUBSTAGE_IDS,
        *V1_022_SUBSTAGE_IDS,
    }:
        for relative in directly_relevant_paths:
            path = repo / relative
            if not path.is_file():
                raise AutomationError(
                    "context_materialization_required",
                    f"{candidate_id} materialized evidence path is unavailable: {relative}",
                )
            materialized_repository_evidence.append(
                {"path": relative, "complete_content": path.read_text()}
            )
        directly_relevant_paths = []
    if not directly_relevant_paths:
        if not materialized_repository_evidence:
            directly_relevant_paths = candidate_relevant_paths(
                repo, authorities, roadmap_item or candidate
            )
    candidate_number_match = re.fullmatch(r"V1-(\d+)", str(candidate_id))
    candidate_number = (
        int(candidate_number_match.group(1)) if candidate_number_match else 0
    )
    if (
        not directly_relevant_paths
        and not materialized_repository_evidence
        and candidate_number >= 20
    ):
        raise AutomationError(
            "context_materialization_required",
            f"no deterministic repository paths were materialized for {candidate_id}",
        )
    materialized_recovery = recovery_state or {}
    packet = {
        "schema_version": 5,
        "candidate": candidate_id,
        "stage": stage,
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "HEAD"),
        "repository_fingerprint": fingerprints["repository"],
        "compact_state_fingerprint": fingerprints["compact_state"],
        "process_state_fingerprint": fingerprints["process_state"],
        "preflight_fingerprint": fingerprints["actionable"],
        "preserved_worktree_fingerprint": preserved.get("fingerprint"),
        "task": roadmap_item.get("task")
        or candidate.get("task")
        or preflight.get("next_action"),
        "candidate_state": {
            "approval_status": (state.get("approval") or {}).get("status"),
            "implementation_started": bool(
                (state.get("approval") or {}).get("implementation_started")
            ),
            "implementation_completed": bool(
                (state.get("approval") or {}).get("implementation_completed")
            ),
            "owner_action": state.get("owner_action"),
            "active_roadmap_id": (state.get("roadmap") or {}).get("current_id"),
            "bounded_substage": substage_id or None,
            "recovery_pending": materialized_recovery.get("recovery_pending") is True,
            "recovery_generation": recovery_generation,
            "bounded_recovery_attempt": int(
                materialized_recovery.get("bounded_recovery_attempt") or 0
            ),
            "current_failure_category": materialized_recovery.get(
                "current_failure_category"
            ),
            "bounded_recovery_exhausted": materialized_recovery.get(
                "bounded_recovery_exhausted"
            )
            is True,
            "context_materialization_attempt": int(
                materialized_recovery.get("context_materialization_attempt") or 0
            ),
            "preserved_changed_paths": changed_paths(repo),
        },
        "candidate_scope": {
            "include": roadmap_item.get("include") or [],
            "exclude": roadmap_item.get("exclude") or [],
        },
        "controlling_authorities": authorities,
        "acceptance_criteria": substage_acceptance,
        "acceptance_profile": roadmap_item.get("acceptance_profile") or "complete",
        "requirement_evidence": excerpts,
        "directly_relevant_paths": directly_relevant_paths,
        "continuity_instructions": [
            "Use this packet as the complete continuity and authority record; no external skill lookup or compact-state reread is required or permitted.",
            "The exact candidate, authorization, acceptance, state, and controlling requirement excerpts are materialized here.",
            "Read only directly_relevant_paths. Do not read ops/STATE.json, ops/V1_ROADMAP.json, ops/NOW.md, ops/QUEUE.md, Makefile, a canonical document, or an unrelated source tree.",
            "Do not call todo/planning tools or rediscover repository paths with broad searches.",
            f"When bounded_substage is present, implement only that substage and leave every later {candidate_id} substage for its own fresh session.",
            "Keep business logic outside route handlers, keep frontend API access in a dedicated typed client, and preserve audit/data-integrity boundaries.",
            (
                "Do not edit compact operational state; the deterministic supervisor records bounded progress after verification."
                if supervisor_owned_progress
                else "Write concise secret-free substage evidence to the authorized state paths without rereading their complete contents."
            ),
            "In changed_paths, include every candidate_state.preserved_changed_paths entry plus every path changed in this session; do not read a preserved operational path merely to rediscover it.",
        ],
        "dispatcher_evidence_trust": {
            "instruction": "Trust these dispatcher-supplied values. Do not spend tool calls rediscovering them with Git or process commands.",
            "branch": git(repo, "branch", "--show-current"),
            "head": git(repo, "rev-parse", "HEAD"),
            "repository_fingerprint": fingerprints["repository"],
            "compact_state_fingerprint": fingerprints["compact_state"],
            "process_state_fingerprint": fingerprints["process_state"],
            "changed_path_count": len(changed_paths(repo)),
            "worktree_clean": changed_paths(repo) == [],
            "preserved_worktree_fingerprint": preserved.get("fingerprint"),
        },
        "recovery_generation": recovery_generation,
        "durable_state_write_paths": (
            []
            if supervisor_owned_progress
            else ["ops/NOW.md", "ops/STATE.json", "ops/traceability.json"]
        ),
        "authorization_boundaries": {
            "authorization": roadmap_item.get("authorization"),
            "existing_durable_v1": roadmap_item.get("authorization") == "durable_v1",
            "renewed_owner_authorization": False,
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
            "field_contracts": {
                "stage_result": "completed",
                "changed_paths": "array of every exact current candidate worktree path",
                "verification": ["deferred_to_deterministic_supervisor"],
                "blockers": [],
                "exact_next_action": "one nonempty string",
            },
        },
    }
    if substage_id == "sign_in":
        packet["materialized_implementation_context"] = {
            "routing_revision": V1_019_ROUTING_REVISION,
            "backend_contract": sign_in_backend_contract(repo),
            "frontend_baseline": complete_small_frontend_evidence(repo),
            "exact_writable_paths": [
                "frontend/src/App.tsx",
                "frontend/src/App.test.tsx",
                "frontend/src/styles.css",
                "frontend/src/authClient.ts",
                "frontend/src/authClient.test.ts",
                "ops/NOW.md",
                "ops/STATE.json",
                "ops/traceability.json",
            ],
            "shortest_execution_sequence": [
                "Create a dedicated typed local-authentication client in frontend/src/authClient.ts.",
                "Replace only the bootstrap App surface with an accessible local username/password sign-in experience.",
                "Use one generic authentication failure message and expose no account, lifecycle, MFA-enrollment, or privilege details.",
                "Add focused client and component tests, including keyboard/label/error announcement coverage and proof that no first-Owner route exists.",
                "Do not invoke terminal, Git, npm, make, or any verification command; the execution-capable supervisor owns all tests and builds after this implementation result.",
                "Patch ops/STATE.json without reading it so approval.implementation_started is true; for this non-final substage leave implementation_completed and publication_completed false.",
                "Return stage_result set to completed, the exact changed paths, verification set to the one-item array [\"deferred_to_deterministic_supervisor\"], blockers set to [], and substage_complete true when the bounded code and tests are ready.",
            ],
        }
    if str(candidate_id) == "V1-021" and substage_id in V1_021_SUBSTAGE_IDS:
        packet["materialized_implementation_context"] = {
            "routing_revision": V1_021_ROUTING_REVISION,
            "repository_evidence": materialized_repository_evidence,
            "application_integration_contract": (
                v1_021_authorized_query_integration_contract(repo)
                if substage_id == "authorized_query"
                else None
            ),
            "exact_writable_paths": [
                *V1_021_SUBSTAGE_WRITABLE_PATHS[substage_id],
                "ops/NOW.md",
                "ops/STATE.json",
                "ops/traceability.json",
            ],
            "shortest_execution_sequence": [
                f"Implement only the {substage_id} audit-foundation substage.",
                "Use only the materialized repository evidence, integration contract, and authority excerpts already in this packet.",
                "Do not call any read, search, listing, terminal, Git, database, make, or verification tool; none is necessary or authorized.",
                "Create or update only exact_writable_paths and do not begin the next audit substage.",
                "Patch the authorized compact evidence paths without rereading their full contents.",
                "Return stage_result completed, substage_complete true, every exact changed path, deferred_to_deterministic_supervisor verification, no blockers, and one exact next action.",
            ],
        }
    if str(candidate_id) == "V1-022" and substage_id in V1_022_SUBSTAGE_IDS:
        packet["materialized_implementation_context"] = {
            "routing_revision": V1_022_ROUTING_REVISION,
            "repository_evidence": materialized_repository_evidence,
            "exact_writable_paths": [
                *V1_022_SUBSTAGE_WRITABLE_PATHS[substage_id],
            ],
            "shortest_execution_sequence": [
                f"Implement only the {substage_id} Property-configuration substage.",
                "Use only the materialized repository evidence and authority excerpts already in this packet.",
                "Do not call any read, search, listing, terminal, Git, database, make, or verification tool.",
                "Create or update only exact_writable_paths in one complete parallel tool batch and do not begin the next Property substage.",
                "Do not edit ops files; the deterministic supervisor owns compact progress state.",
                "Return the exact completed substage JSON contract with deferred supervisor verification and no blockers.",
            ],
        }
    if bounded_substage is not None:
        packet["bounded_substage"] = bounded_substage
        packet["output_contract"]["required"].append("substage_complete")
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
            "field_contracts": {
                "passed": "boolean",
                "findings": (
                    "array of objects; every object has exactly severity, path, line, and evidence "
                    "as nonempty strings; use [] when passed is true"
                ),
                "reviewed_repository_fingerprint": "the exact 64-character packet repository_fingerprint",
                "reviewed_paths": "the exact sorted scoped_changed_paths array",
                "exact_next_action": "one nonempty string",
            },
            "exact_keys_only": True,
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
    if blocker_kind in OWNER_BLOCKER_CATEGORIES:
        if blocker_kind in {
            "secret_credential_or_protected_operation",
            "destructive_or_production_operation",
            "protected_operation",
        }:
            return "project_blocked_protected_operation"
        return "project_blocked_owner_decision"
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


def post_restoration_scheduler_ok(
    *,
    enabled: bool,
    last_run_ms: object,
    last_status: object,
    consecutive_errors: object,
    restored_at_ms: object,
    now_ms: int,
    heartbeat_ms: int,
) -> bool:
    """Require a fresh successful check after the latest schedule mutation."""
    return bool(
        enabled
        and isinstance(last_run_ms, int)
        and isinstance(restored_at_ms, int)
        and last_run_ms >= restored_at_ms
        and 0 <= now_ms - last_run_ms <= heartbeat_ms
        and last_status == "ok"
        and consecutive_errors == 0
    )


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
    if len(sys.argv) in {2, 3} and sys.argv[1] == "classify-state":
        target = Path(sys.argv[2] if len(sys.argv) == 3 else os.getcwd()).resolve()
        print(json.dumps(classify_compact_state(target), sort_keys=True))
        raise SystemExit(0)
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
