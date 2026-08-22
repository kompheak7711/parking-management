#!/usr/bin/env python3
"""Repository-owned Hermes invocation, least-privilege, and token guard."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = 2
GUARD_SCHEMA_VERSION = 1
COUNTED_TOKEN_FIELDS = ("input_tokens", "output_tokens")
CACHE_TOKEN_FIELD = "cache_read_tokens"
MINIMUM_COMPLETION_CHECKPOINT_TOKENS = 2_048
CONTEXT_RESERVATION_MARGIN_TOKENS = 1_024
CONTEXT_PREDICTION_METHOD = "validated_serialized_request_estimate_v1"
SERIALIZED_ASCII_CHARS_PER_TOKEN = 3
TOOL_OUTPUT_LIMIT_BYTES = 12_000
SESSION_TOOL_OUTPUT_LIMIT_BYTES = 36_000
STRUCTURED_TOOL_CONTROL_LIMIT_BYTES = 4_096
ALLOWED_STAGES = {"implementation", "direct_codex_recovery", "independent_review"}
ALLOWED_MAKE_TARGETS = {
    "automation-test",
    "format-check",
    "lint",
    "typecheck",
    "test",
    "build",
    "database-test",
    "deployment-config-check",
    "frontend-audit",
    "backend-test",
    "backend-format-check",
    "backend-lint",
    "backend-typecheck",
    "backend-build",
    "frontend-test",
    "frontend-format-check",
    "frontend-lint",
    "frontend-typecheck",
    "frontend-build",
}
CANONICAL_DOCUMENT = re.compile(r"^docs/(?:00[1-9]|010)_.+")
PATCH_OPERATION = re.compile(
    r"^\s*\*\*\*\s*(Add|Update|Delete|Move)\s*File:\s*(.*?)\s*$",
    re.MULTILINE,
)
PATCH_FILE_HEADER = re.compile(r"^\s*\*\*.*File:.*$", re.MULTILINE)


class GuardError(RuntimeError):
    """A repository-owned enforcement failure."""


class TokenEstimationUnavailable(GuardError):
    """The supported request shape could not be estimated before provider use."""


def digest(value: bytes | str | Any) -> str:
    if isinstance(value, str):
        value = value.encode()
    elif not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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


def _resolved_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def create_manifest(
    *,
    state_root: Path,
    repository: Path,
    dispatcher_pid: int,
    candidate: str,
    stage: str,
    repository_fingerprint: str,
    preserved_worktree_fingerprint: str | None,
    task_path: Path,
    provider: str,
    model: str,
    requested_reasoning: str,
    cumulative_ceiling: int,
    dispatcher_record_path: Path,
    writable_paths: list[str],
    readable_paths: list[str],
    bounded_substage_id: str | None,
    exceptional_review_classification: str | None = None,
) -> tuple[Path, dict[str, Any], str]:
    """Create one unique, immutable invocation authorization manifest."""
    manifest_id = secrets.token_hex(16)
    manifest_path = state_root / "manifests" / f"{candidate}-{stage}-{manifest_id}.json"
    usage_path = state_root / "usage" / f"{candidate}-{stage}-{manifest_id}.json"
    budget_path = state_root / "budgets" / f"{candidate}-{stage}-{manifest_id}.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    authorization = secrets.token_hex(32)
    dispatcher_record_path = dispatcher_record_path.resolve()
    dispatcher_record_sha256 = digest(dispatcher_record_path.read_bytes())
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": manifest_id,
        "created_by": "scripts/openclaw_dispatch.py",
        "dispatcher_pid": dispatcher_pid,
        "dispatcher_record_path": str(dispatcher_record_path),
        "dispatcher_record_sha256": dispatcher_record_sha256,
        "authorization_sha256": digest(authorization),
        "candidate": candidate,
        "stage": stage,
        "repository": str(repository.resolve()),
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=repository, text=True
        ).strip(),
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "repository_fingerprint": repository_fingerprint,
        "preserved_worktree_fingerprint": preserved_worktree_fingerprint,
        "task_path": str(task_path.resolve()),
        "task_sha256": digest(task_path.read_bytes()),
        "usage_path": str(usage_path.resolve()),
        "budget_path": str(budget_path.resolve()),
        "writable_paths": sorted(set(writable_paths)),
        "readable_paths": sorted(set(readable_paths)),
        "bounded_substage_id": bounded_substage_id,
        "token_policy": {
            "provider": provider,
            "model": model,
            "requested_reasoning": requested_reasoning,
            "cumulative_ceiling": cumulative_ceiling,
            "counted_fields": list(COUNTED_TOKEN_FIELDS),
            "cache_read_field": CACHE_TOKEN_FIELD,
            "cache_read_double_counted": False,
            "session_scope": "fresh_stage_session",
            "minimum_completion_checkpoint_tokens": MINIMUM_COMPLETION_CHECKPOINT_TOKENS,
            "context_reservation_margin_tokens": CONTEXT_RESERVATION_MARGIN_TOKENS,
            "context_prediction_method": CONTEXT_PREDICTION_METHOD,
            "serialized_ascii_chars_per_token": SERIALIZED_ASCII_CHARS_PER_TOKEN,
            "tool_output_limit_bytes": TOOL_OUTPUT_LIMIT_BYTES,
            "session_tool_output_limit_bytes": SESSION_TOOL_OUTPUT_LIMIT_BYTES,
            "exceptional_review_classification": exceptional_review_classification,
        },
    }
    atomic_json(manifest_path, manifest)
    return manifest_path, manifest, authorization


def validate_manifest(
    manifest_path: Path,
    *,
    task_path: Path,
    consume: bool,
    current_pid: int | None = None,
    authorization: str | None = None,
) -> dict[str, Any]:
    """Validate and optionally consume one dispatcher-created manifest."""
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise GuardError("invocation manifest is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise GuardError("invocation manifest schema is invalid")
    required = {
        "manifest_id",
        "created_by",
        "dispatcher_pid",
        "dispatcher_record_path",
        "dispatcher_record_sha256",
        "authorization_sha256",
        "candidate",
        "stage",
        "repository",
        "branch",
        "head",
        "repository_fingerprint",
        "preserved_worktree_fingerprint",
        "task_path",
        "task_sha256",
        "usage_path",
        "budget_path",
        "writable_paths",
        "readable_paths",
        "bounded_substage_id",
        "token_policy",
    }
    if set(manifest) != required | {"schema_version"}:
        raise GuardError("invocation manifest fields are not exact")
    if manifest.get("created_by") != "scripts/openclaw_dispatch.py":
        raise GuardError("only openclaw_dispatch.py may create model invocations")
    if manifest.get("stage") not in ALLOWED_STAGES:
        raise GuardError("invocation manifest stage is unsupported")
    repository = Path(str(manifest["repository"])).resolve()
    state_root = manifest_path.parent.parent.resolve()
    candidate = str(manifest.get("candidate") or "")
    expected_manifest_parent = state_root / "manifests"
    dispatcher_record_path = Path(str(manifest["dispatcher_record_path"])).resolve()
    expected_record_path = state_root / "candidates" / f"{candidate}.json"
    if (
        not repository.is_dir()
        or manifest_path.resolve().parent != expected_manifest_parent
        or dispatcher_record_path != expected_record_path
        or not dispatcher_record_path.is_file()
        or digest(dispatcher_record_path.read_bytes()) != manifest.get("dispatcher_record_sha256")
    ):
        raise GuardError("invocation manifest path or repository is invalid")
    try:
        dispatcher_record = json.loads(dispatcher_record_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise GuardError("dispatcher candidate record is missing or invalid") from error
    if (
        not isinstance(dispatcher_record, dict)
        or dispatcher_record.get("candidate") != candidate
        or (
            (dispatcher_record.get("model_stage_policy") or {}).get("stage")
            or dispatcher_record.get("stage")
        )
        != manifest.get("stage")
        or dispatcher_record.get("repository_fingerprint") != manifest.get("repository_fingerprint")
    ):
        raise GuardError("manifest does not match the live dispatcher candidate record")
    if Path(str(manifest["task_path"])).resolve() != task_path.resolve():
        raise GuardError("invocation task path differs from the manifest")
    if not task_path.is_file() or digest(task_path.read_bytes()) != manifest.get("task_sha256"):
        raise GuardError("invocation task hash differs from the manifest")
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repository, text=True
    ).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    if branch != manifest.get("branch") or head != manifest.get("head"):
        raise GuardError("invocation branch or HEAD changed after dispatch")
    from openclaw_automation import preservation_evidence, repository_fingerprint

    if repository_fingerprint(repository) != manifest.get("repository_fingerprint"):
        raise GuardError("repository/worktree fingerprint changed after dispatch")
    preserved = preservation_evidence(repository)
    if preserved.get("fingerprint") != manifest.get("preserved_worktree_fingerprint"):
        raise GuardError("preserved-worktree fingerprint changed after dispatch")
    policy = manifest.get("token_policy")
    if not isinstance(policy, dict) or set(policy) != {
        "provider",
        "model",
        "requested_reasoning",
        "cumulative_ceiling",
        "counted_fields",
        "cache_read_field",
        "cache_read_double_counted",
        "session_scope",
        "minimum_completion_checkpoint_tokens",
        "context_reservation_margin_tokens",
        "context_prediction_method",
        "serialized_ascii_chars_per_token",
        "tool_output_limit_bytes",
        "session_tool_output_limit_bytes",
        "exceptional_review_classification",
    }:
        raise GuardError("invocation token policy is invalid")
    if (
        policy.get("provider") != "openai-codex"
        or policy.get("model") != "gpt-5.6-sol"
        or policy.get("counted_fields") != list(COUNTED_TOKEN_FIELDS)
        or policy.get("cache_read_field") != CACHE_TOKEN_FIELD
        or policy.get("cache_read_double_counted") is not False
        or policy.get("session_scope") != "fresh_stage_session"
        or policy.get("minimum_completion_checkpoint_tokens")
        != MINIMUM_COMPLETION_CHECKPOINT_TOKENS
        or policy.get("context_reservation_margin_tokens") != CONTEXT_RESERVATION_MARGIN_TOKENS
        or policy.get("context_prediction_method") != CONTEXT_PREDICTION_METHOD
        or policy.get("serialized_ascii_chars_per_token") != SERIALIZED_ASCII_CHARS_PER_TOKEN
        or policy.get("tool_output_limit_bytes") != TOOL_OUTPUT_LIMIT_BYTES
        or policy.get("session_tool_output_limit_bytes") != SESSION_TOOL_OUTPUT_LIMIT_BYTES
        or policy.get("cumulative_ceiling") not in {60_000, 90_000, 120_000}
    ):
        raise GuardError("invocation token policy does not match repository policy")
    stage = str(manifest["stage"])
    ceiling = int(policy["cumulative_ceiling"])
    if stage in {"implementation", "direct_codex_recovery"} and ceiling != 60_000:
        raise GuardError("implementation and ordinary repair require 60000 tokens")
    if stage == "independent_review" and ceiling not in {90_000, 120_000}:
        raise GuardError("independent review requires 90000 or persisted exceptional 120000")
    exceptional = policy.get("exceptional_review_classification")
    if ceiling == 120_000 and not (isinstance(exceptional, str) and exceptional.strip()):
        raise GuardError("120000-token review requires a persisted exceptional classification")
    if ceiling != 120_000 and exceptional is not None:
        raise GuardError("exceptional review classification is valid only at 120000 tokens")
    usage_path = Path(str(manifest["usage_path"])).resolve()
    budget_path = Path(str(manifest["budget_path"])).resolve()
    if not _resolved_under(usage_path, state_root / "usage") or not _resolved_under(
        budget_path, state_root / "budgets"
    ):
        raise GuardError("usage and budget paths must be unique dispatcher state paths")
    consumed = manifest_path.with_suffix(".consumed")
    if consume and consumed.exists():
        raise GuardError("invocation manifest was already consumed")
    if usage_path.exists():
        raise GuardError("usage path was already used")
    dispatcher_pid = manifest.get("dispatcher_pid")
    if not isinstance(dispatcher_pid, int) or dispatcher_pid <= 1:
        raise GuardError("dispatcher process identity is invalid")
    if consume:
        if current_pid is None or current_pid <= 1:
            raise GuardError("wrapper process identity is required")
        try:
            parent_pid = int(os.environ["PROPERTY_RENTAL_WRAPPER_PARENT_PID"])
            wrapper_pid = int(os.environ["PROPERTY_RENTAL_WRAPPER_PID"])
            dispatcher_command = subprocess.check_output(
                ["ps", "-o", "command=", "-p", str(dispatcher_pid)], text=True
            ).strip()
        except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
            raise GuardError("dispatcher process ancestry cannot be proven") from error
        expected_dispatcher = str(repository / "scripts/openclaw_dispatch.py")
        if (
            wrapper_pid != current_pid
            or parent_pid != dispatcher_pid
            or expected_dispatcher not in dispatcher_command
        ):
            raise GuardError("wrapper was not launched by the live repository dispatcher")
    writable_paths = manifest.get("writable_paths")
    if not isinstance(writable_paths, list) or any(
        not isinstance(path, str) or not path or Path(path).is_absolute() for path in writable_paths
    ):
        raise GuardError("candidate writable paths are invalid")
    for path in writable_paths:
        resolved = (repository / path).resolve()
        if not _resolved_under(resolved, repository):
            raise GuardError("candidate writable path escapes the repository")
    readable_paths = manifest.get("readable_paths")
    if not isinstance(readable_paths, list) or any(
        not isinstance(path, str) or not path or Path(path).is_absolute() for path in readable_paths
    ):
        raise GuardError("candidate readable paths are invalid")
    for path in readable_paths:
        if not _resolved_under((repository / path).resolve(), repository):
            raise GuardError("candidate readable path escapes the repository")
    bounded_substage_id = manifest.get("bounded_substage_id")
    if bounded_substage_id is not None and (
        not isinstance(bounded_substage_id, str) or not bounded_substage_id
    ):
        raise GuardError("bounded substage identity is invalid")
    authorization = authorization or os.environ.get("PROPERTY_RENTAL_INVOCATION_AUTHORIZATION", "")
    if not authorization or digest(authorization) != manifest.get("authorization_sha256"):
        raise GuardError("dispatcher invocation authorization is missing or invalid")
    if consume:
        try:
            descriptor = os.open(consumed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise GuardError("invocation manifest was already consumed") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(manifest["manifest_id"]) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return manifest


def prepare_session_home(manifest: dict[str, Any], target: Path, source_home: Path) -> None:
    """Create one isolated nonpersistent Hermes profile for this manifest."""
    target.mkdir(parents=True, exist_ok=False)
    target.chmod(0o700)
    auth = source_home / "auth.json"
    if not auth.is_file():
        raise GuardError("OpenAI Codex authentication is unavailable in the source profile")
    # Authentication is deliberately withheld until the guard registers in the
    # actual chat process. A Hermes process in which the plugin fails to load
    # therefore cannot reach the provider with usable credentials.
    (target / "guard-source-auth-path").write_text(str(auth.resolve()) + "\n")
    (target / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - property-rental-guard\nmodel:\n  openai_runtime: direct\n"
    )
    atomic_json(
        Path(str(manifest["budget_path"])),
        {
            "schema_version": GUARD_SCHEMA_VERSION,
            "manifest_id": manifest["manifest_id"],
            "candidate": manifest["candidate"],
            "stage": manifest["stage"],
            "ceiling": manifest["token_policy"]["cumulative_ceiling"],
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
            "reservation_blocked": False,
            "predicted_next_context_tokens": 0,
            "token_estimation_status": "ready",
            "token_estimate_inputs": {},
            "token_estimate_method": CONTEXT_PREDICTION_METHOD,
            "token_estimate_validation_margin_tokens": CONTEXT_RESERVATION_MARGIN_TOKENS,
            "serialized_ascii_chars_per_token": SERIALIZED_ASCII_CHARS_PER_TOKEN,
            "reserved_completion_checkpoint_tokens": MINIMUM_COMPLETION_CHECKPOINT_TOKENS,
            "context_reservation_margin_tokens": CONTEXT_RESERVATION_MARGIN_TOKENS,
            "locally_reserved_next_call_tokens": 0,
            "provider_completion_limit_mode": "local_proactive_reservation",
            "provider_request_omits_max_output_tokens": True,
            "unsupported_provider_parameters_removed": [],
            "last_call_input_tokens": 0,
            "last_call_output_tokens": 0,
            "reservation_violation": False,
            "tool_output_limit_bytes": TOOL_OUTPUT_LIMIT_BYTES,
            "session_tool_output_limit_bytes": SESSION_TOOL_OUTPUT_LIMIT_BYTES,
            "tool_output_observed_bytes": 0,
            "tool_output_returned_bytes": 0,
            "tool_output_truncations": 0,
            "tool_output_control_bytes": 0,
            "tool_output_control_reserved_bytes": 0,
            "tool_output_batch_history": [],
            "tool_output_pending_reservations": [],
            "context_materialization_checkpoint": False,
            "guard_loaded": False,
            "preflight_guard_loaded": False,
            "chat_guard_loaded": False,
            "chat_guard_pid": None,
            "guard_capabilities": [],
        },
    )


def _value(source: Any, *names: str) -> Any:
    for name in names:
        if isinstance(source, dict) and source.get(name) is not None:
            return source[name]
        value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _metric(source: Any, *names: str) -> int:
    value = _value(source, *names)
    return value if isinstance(value, int) and value >= 0 else 0


def response_usage(response: Any) -> dict[str, Any]:
    usage = _value(response, "usage") or {}
    input_details = _value(usage, "input_tokens_details", "prompt_tokens_details") or {}
    output_details = _value(usage, "output_tokens_details", "completion_tokens_details") or {}
    return {
        "model": _value(response, "model"),
        "input_tokens": _metric(usage, "input_tokens", "prompt_tokens"),
        "output_tokens": _metric(usage, "output_tokens", "completion_tokens"),
        "cache_read_tokens": _metric(
            usage,
            "cache_read_tokens",
        )
        or _metric(input_details, "cached_tokens", "cache_read_tokens"),
        "reasoning_tokens": _metric(usage, "reasoning_tokens")
        or _metric(output_details, "reasoning_tokens"),
    }


def _load_budget(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("schema_version") != GUARD_SCHEMA_VERSION:
        raise GuardError("cumulative budget ledger is invalid")
    return value


def estimate_serialized_request_tokens(
    request: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Estimate the supported wire request without treating bytes as tokens.

    The three-ASCII-characters-per-token divisor is deliberately more
    conservative than Hermes' four-character planning heuristic. Non-ASCII
    UTF-8 bytes retain a one-byte floor. Provider-returned input usage from
    every completed call validates the estimate and any observed shortfall is
    carried into the next reservation.
    """
    if not isinstance(request, dict) or not request:
        raise TokenEstimationUnavailable("supported request object is unavailable")
    try:
        serialized = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8", "surrogatepass"
        )
    except (TypeError, UnicodeError, ValueError) as error:
        raise TokenEstimationUnavailable(
            "supported request serialization is unavailable"
        ) from error
    if not serialized:
        raise TokenEstimationUnavailable("supported request serialization is empty")
    ascii_bytes = sum(byte < 0x80 for byte in serialized)
    non_ascii_bytes = len(serialized) - ascii_bytes
    estimate = (
        ascii_bytes + SERIALIZED_ASCII_CHARS_PER_TOKEN - 1
    ) // SERIALIZED_ASCII_CHARS_PER_TOKEN + non_ascii_bytes
    return estimate, {
        "serialized_request_bytes": len(serialized),
        "serialized_ascii_bytes": ascii_bytes,
        "serialized_non_ascii_bytes": non_ascii_bytes,
        "serialized_ascii_chars_per_token": SERIALIZED_ASCII_CHARS_PER_TOKEN,
    }


def _tool_call_items(response: Any) -> list[Any]:
    """Extract the complete assistant function-call batch from supported responses."""
    output = _value(response, "output", "tool_calls")
    if isinstance(output, list):
        return output
    choices = _value(response, "choices")
    if isinstance(choices, list) and choices:
        message = _value(choices[0], "message")
        calls = _value(message, "tool_calls")
        if isinstance(calls, list):
            return calls
    return []


def _canonical_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Mirror Hermes' schema coercion for fields used by reservation identity."""
    canonical = dict(arguments)
    integer_fields = {
        "read_file": {"offset", "limit"},
        "search_files": {"offset", "limit", "context"},
        "terminal": {"timeout"},
    }.get(tool_name, set())
    boolean_fields = {
        "write_file": {"cross_profile"},
        "patch": {"replace_all", "cross_profile"},
        "terminal": {"background", "pty", "notify_on_complete"},
    }.get(tool_name, set())
    for field in integer_fields:
        value = canonical.get(field)
        if isinstance(value, str):
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError):
                pass
            else:
                if numeric == numeric and numeric not in {float("inf"), float("-inf")}:
                    integer = int(numeric)
                    if numeric == integer:
                        canonical[field] = integer
    for field in boolean_fields:
        value = canonical.get(field)
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            canonical[field] = value.strip().lower() == "true"
    if tool_name == "terminal" and "watch_patterns" in canonical:
        value = canonical["watch_patterns"]
        if value is not None and not isinstance(value, (list, tuple)):
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError):
                    parsed = None
                canonical["watch_patterns"] = parsed if isinstance(parsed, list) else [value]
            else:
                canonical["watch_patterns"] = [value]
    return canonical


def _tool_call(call: Any) -> dict[str, Any] | None:
    kind = _value(call, "type")
    function = _value(call, "function")
    name = _value(call, "name") or _value(function, "name")
    raw_arguments = _value(call, "arguments") or _value(function, "arguments") or "{}"
    if kind not in {None, "function", "function_call"} or not isinstance(name, str):
        return None
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}
    else:
        arguments = raw_arguments
    if not isinstance(arguments, dict):
        arguments = {}
    arguments = _canonical_tool_arguments(name, arguments)
    signature = digest({"tool": name, "arguments": arguments})
    return {"tool": name, "arguments": arguments, "signature": signature}


def response_tool_call_batch(response: Any) -> list[dict[str, Any]]:
    return [
        parsed for item in _tool_call_items(response) if (parsed := _tool_call(item)) is not None
    ]


def _estimated_read_output_bytes(
    repository: Path, arguments: dict[str, Any], per_call_limit: int
) -> int:
    try:
        source = _repo_path(str(arguments.get("path") or ""), repository)
        if not source.is_file():
            return min(per_call_limit, 512)
        lines = source.read_bytes().splitlines(keepends=True)
        offset = max(1, int(arguments.get("offset") or 1))
        raw_limit = arguments.get("limit")
        selected = lines[offset - 1 :]
        if isinstance(raw_limit, int) and raw_limit >= 0:
            selected = selected[:raw_limit]
        payload_bytes = sum(len(line) for line in selected)
        # Hermes adds line numbers and a JSON result envelope. This deliberately
        # overestimates before capping at the enforced per-call maximum.
        estimate = payload_bytes + len(selected) * 12 + 512
        return min(per_call_limit, max(512, estimate))
    except (GuardError, OSError, TypeError, ValueError):
        return min(per_call_limit, 512)


def estimate_tool_output_bytes(
    repository: Path,
    tool_name: str,
    arguments: dict[str, Any],
    per_call_limit: int,
) -> int:
    if tool_name == "read_file":
        return _estimated_read_output_bytes(repository, arguments, per_call_limit)
    if tool_name in {"write_file", "patch"}:
        return min(per_call_limit, 1_024)
    return per_call_limit


def reserve_tool_output_batch(
    response: Any, manifest: dict[str, Any], budget: dict[str, Any]
) -> bool:
    """Atomically reserve one complete provider-returned tool batch.

    Returns true only when an identical rejected batch requires a deterministic
    context-materialization checkpoint before any tool executes.
    """
    if manifest.get("bounded_substage_id") is None:
        return False
    calls = response_tool_call_batch(response)
    if not calls:
        return False
    per_call_limit = int(budget.get("tool_output_limit_bytes", TOOL_OUTPUT_LIMIT_BYTES))
    session_limit = int(
        budget.get("session_tool_output_limit_bytes", SESSION_TOOL_OUTPUT_LIMIT_BYTES)
    )
    returned = int(budget.get("tool_output_returned_bytes", 0))
    control = int(budget.get("tool_output_control_bytes", 0))
    control_reserved = int(budget.get("tool_output_control_reserved_bytes", 0))
    remaining = max(0, session_limit - returned - control - control_reserved)
    repository = Path(str(manifest["repository"])).resolve()
    estimates = [
        estimate_tool_output_bytes(
            repository, str(call["tool"]), dict(call["arguments"]), per_call_limit
        )
        for call in calls
    ]
    batch_signature = digest([str(call["signature"]) for call in calls])
    history = budget.setdefault("tool_output_batch_history", [])
    repeated_rejected = any(
        isinstance(item, dict)
        and item.get("batch_signature") == batch_signature
        and item.get("status") == "rejected"
        for item in history
    )
    estimated_total = sum(estimates)
    rejected = estimated_total > remaining
    control_per_call = (
        min(STRUCTURED_TOOL_CONTROL_LIMIT_BYTES, remaining // len(calls)) if rejected else 0
    )
    cannot_report_rejection = rejected and control_per_call < 2
    status = "checkpoint" if cannot_report_rejection else "rejected" if rejected else "reserved"
    batch_id = digest(
        {
            "manifest": budget.get("manifest_id"),
            "sequence": len(history) + 1,
            "signature": batch_signature,
        }
    )[:24]
    history.append(
        {
            "batch_id": batch_id,
            "batch_signature": batch_signature,
            "call_count": len(calls),
            "estimated_bytes": estimated_total,
            "remaining_bytes": remaining,
            "status": status,
            "identical_rejected_retry": repeated_rejected,
            "reserved_control_bytes_per_call": control_per_call,
        }
    )
    history[:] = history[-20:]
    reservations = budget.setdefault("tool_output_pending_reservations", [])
    for ordinal, (call, estimate) in enumerate(zip(calls, estimates)):  # noqa: B905
        reservations.append(
            {
                "reservation_id": f"{batch_id}:{ordinal}",
                "batch_id": batch_id,
                "signature": call["signature"],
                "tool": call["tool"],
                "reserved_bytes": estimate,
                "status": "rejected" if rejected else "pending",
                "reserved_control_bytes": control_per_call,
                "batch_call_count": len(calls),
                "estimated_batch_bytes": estimated_total,
                "remaining_batch_bytes": remaining,
                "identical_rejected_retry": repeated_rejected,
            }
        )
    if rejected:
        budget["tool_output_control_reserved_bytes"] = control_reserved + control_per_call * len(
            calls
        )
    if rejected:
        budget["tool_output_batch_rejections"] = (
            int(budget.get("tool_output_batch_rejections", 0)) + 1
        )
    if repeated_rejected or cannot_report_rejection:
        budget["context_materialization_checkpoint"] = True
        budget["next_api_call_blocked"] = True
    return repeated_rejected or cannot_report_rejection


def enforce_llm_call(request: dict[str, Any], next_call: Callable[[dict[str, Any]], Any]) -> Any:
    """Reserve predicted input plus checkpoint output before every provider call.

    The installed ``openai-codex`` transport targets the Codex backend, whose
    request contract deliberately omits ``max_output_tokens``.  The cumulative
    ceiling is therefore enforced entirely in this local ledger before the
    provider callback is entered; no output-limit parameter is injected into
    the transport request.
    """
    manifest_path = Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"])
    manifest = json.loads(manifest_path.read_text())
    budget_path = Path(str(manifest["budget_path"]))
    budget = _load_budget(budget_path)
    budget.setdefault("reservation_blocked", False)
    budget.setdefault("reservation_violation", False)
    budget.setdefault("in_flight_overshoot_tokens", 0)
    ceiling = int(budget["ceiling"])
    if int(budget["counted_total_tokens"]) >= ceiling:
        budget["boundary_reached"] = True
        budget["next_api_call_blocked"] = True
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_CUMULATIVE_TOKEN_CEILING_REACHED")
    if budget.get("context_materialization_checkpoint") is True:
        budget["next_api_call_blocked"] = True
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_CONTEXT_MATERIALIZATION_REQUIRED")
    if budget.get("next_api_call_blocked") is True:
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_PROVIDER_CALL_BLOCKED")
    remaining = ceiling - int(budget["counted_total_tokens"])
    try:
        serialized_prediction, estimate_inputs = estimate_serialized_request_tokens(request)
    except TokenEstimationUnavailable as error:
        budget["token_estimation_status"] = "unavailable"
        budget["token_estimation_failure"] = str(error)
        budget["next_api_call_blocked"] = True
        budget["reservation_blocked"] = False
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_TOKEN_ESTIMATION_UNAVAILABLE") from error
    calibration_shortfall = max(0, int(budget.get("token_estimate_observed_shortfall_tokens", 0)))
    prior_prediction = (
        int(budget.get("last_call_input_tokens", 0))
        + int(budget.get("last_call_output_tokens", 0))
        + CONTEXT_RESERVATION_MARGIN_TOKENS
    )
    predicted_context = max(serialized_prediction + calibration_shortfall, prior_prediction)
    minimum_completion = int(
        budget.get(
            "reserved_completion_checkpoint_tokens",
            MINIMUM_COMPLETION_CHECKPOINT_TOKENS,
        )
    )
    margin = int(budget.get("context_reservation_margin_tokens", CONTEXT_RESERVATION_MARGIN_TOKENS))
    required = predicted_context + minimum_completion + margin
    budget["predicted_next_context_tokens"] = predicted_context
    budget["token_estimation_status"] = "estimated"
    budget["token_estimate_method"] = CONTEXT_PREDICTION_METHOD
    budget["token_estimate_inputs"] = {
        **estimate_inputs,
        "serialized_estimate_tokens": serialized_prediction,
        "prior_observed_context_floor_tokens": prior_prediction,
        "carried_observed_shortfall_tokens": calibration_shortfall,
        "completion_checkpoint_tokens": minimum_completion,
        "validation_margin_tokens": margin,
    }
    budget["last_estimated_context_tokens"] = predicted_context
    if required > remaining:
        budget["reservation_blocked"] = True
        budget["next_api_call_blocked"] = True
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_PROACTIVE_BUDGET_RESERVATION_STOP")
    guarded_request = dict(request)
    removed_unsupported = "max_output_tokens" in guarded_request
    guarded_request.pop("max_output_tokens", None)
    budget["provider_completion_limit_mode"] = "local_proactive_reservation"
    budget["provider_request_omits_max_output_tokens"] = True
    budget["unsupported_provider_parameters_removed"] = (
        ["max_output_tokens"] if removed_unsupported else []
    )
    budget["locally_reserved_next_call_tokens"] = required
    budget["api_calls_started"] = int(budget["api_calls_started"]) + 1
    atomic_json(budget_path, budget)
    response = next_call(guarded_request)
    observed = response_usage(response)
    budget = _load_budget(budget_path)
    budget["api_calls_completed"] = int(budget["api_calls_completed"]) + 1
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "reasoning_tokens",
    ):
        budget[field] = int(budget[field]) + int(observed[field])
    budget["counted_total_tokens"] = int(budget["input_tokens"]) + int(budget["output_tokens"])
    budget["last_call_input_tokens"] = int(observed["input_tokens"])
    budget["last_call_output_tokens"] = int(observed["output_tokens"])
    observed_shortfall = max(
        0,
        int(observed["input_tokens"]) - int(budget.get("last_estimated_context_tokens", 0)),
    )
    budget["token_estimate_observed_shortfall_tokens"] = observed_shortfall
    budget["token_estimate_provider_validated"] = observed_shortfall == 0
    budget["effective_model"] = observed.get("model")
    if int(budget["counted_total_tokens"]) >= ceiling:
        budget["boundary_reached"] = True
        budget["in_flight_overshoot_tokens"] = max(0, int(budget["counted_total_tokens"]) - ceiling)
        budget["reservation_violation"] = int(budget["counted_total_tokens"]) > ceiling
    context_checkpoint = reserve_tool_output_batch(response, manifest, budget)
    atomic_json(budget_path, budget)
    if context_checkpoint:
        raise GuardError("PROPERTY_RENTAL_CONTEXT_MATERIALIZATION_REQUIRED")
    return response


def _fit_structured_result(payload: dict[str, Any], limit: int) -> str:
    """Return valid JSON at any practical control/result limit."""
    rendered = json.dumps(payload, sort_keys=True)
    if len(rendered.encode()) <= limit:
        return rendered
    reduced = {key: value for key, value in payload.items() if key != "preview"}
    rendered = json.dumps(reduced, sort_keys=True)
    if len(rendered.encode()) <= limit:
        return rendered
    minimal = {
        "error": "Hermes guard: tool output unavailable",
        "retry_allowed": False,
    }
    rendered = json.dumps(minimal, sort_keys=True)
    if len(rendered.encode()) <= limit:
        return rendered
    return "{}" if limit >= 2 else ""


def _next_offset(arguments: dict[str, Any] | None) -> int | None:
    if not arguments:
        return None
    offset = arguments.get("offset")
    limit = arguments.get("limit")
    if isinstance(limit, int) and limit > 0:
        return max(1, int(offset) if isinstance(offset, int) else 1) + limit
    return None


def _deliver_policy_rejection(
    tool_name: str,
    arguments: dict[str, Any],
    error: Exception,
) -> str:
    """Charge a pre-execution policy block to the bounded context allowance."""
    manifest = json.loads(Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text())
    message = f"Hermes guard: {error}"
    if manifest.get("bounded_substage_id") is None:
        return message
    budget_path = Path(str(manifest["budget_path"]))
    lock_path = budget_path.with_name(f".{budget_path.name}.tool-output.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = _load_budget(budget_path)
        signature = digest(
            {
                "tool": tool_name,
                "arguments": _canonical_tool_arguments(tool_name, arguments),
            }
        )
        reservations = budget.get("tool_output_pending_reservations") or []
        reservation = next(
            (
                item
                for item in reservations
                if isinstance(item, dict)
                and item.get("signature") == signature
                and item.get("status") in {"pending", "rejected"}
            ),
            None,
        )
        released = 0
        if reservation is not None:
            if reservation.get("status") == "rejected":
                released = int(reservation.get("reserved_control_bytes") or 0)
            reservation["status"] = "policy_rejected"
        prior_reserved = int(budget.get("tool_output_control_reserved_bytes", 0))
        remaining = max(
            0,
            int(budget.get("session_tool_output_limit_bytes", SESSION_TOOL_OUTPUT_LIMIT_BYTES))
            - int(budget.get("tool_output_returned_bytes", 0))
            - int(budget.get("tool_output_control_bytes", 0))
            - max(0, prior_reserved - released),
        )
        rendered = _fit_structured_result(
            {
                "error": message,
                "classification": "guard_policy_rejection",
                "tool": tool_name,
                "retry_allowed": False,
                "next_action": "Use only the dispatcher-authorized bounded packet and paths.",
            },
            min(STRUCTURED_TOOL_CONTROL_LIMIT_BYTES, remaining),
        )
        budget["tool_output_control_reserved_bytes"] = max(0, prior_reserved - released)
        budget["tool_output_control_bytes"] = int(budget.get("tool_output_control_bytes", 0)) + len(
            rendered.encode()
        )
        budget["tool_output_policy_rejections_delivered"] = (
            int(budget.get("tool_output_policy_rejections_delivered", 0)) + 1
        )
        budget["context_materialization_checkpoint"] = True
        budget["next_api_call_blocked"] = True
        atomic_json(budget_path, budget)
        return rendered


def _claim_tool_reservation(
    tool_name: str, arguments: dict[str, Any], budget_path: Path
) -> dict[str, Any] | None:
    lock_path = budget_path.with_name(f".{budget_path.name}.tool-output.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = _load_budget(budget_path)
        canonical_arguments = _canonical_tool_arguments(tool_name, arguments)
        signature = digest({"tool": tool_name, "arguments": canonical_arguments})
        reservations = budget.get("tool_output_pending_reservations") or []
        reservation = next(
            (
                item
                for item in reservations
                if isinstance(item, dict)
                and item.get("signature") == signature
                and item.get("status") in {"pending", "rejected"}
            ),
            None,
        )
        if reservation is None:
            session_limit = int(
                budget.get("session_tool_output_limit_bytes", SESSION_TOOL_OUTPUT_LIMIT_BYTES)
            )
            remaining = max(
                0,
                session_limit
                - int(budget.get("tool_output_returned_bytes", 0))
                - int(budget.get("tool_output_control_bytes", 0))
                - int(budget.get("tool_output_control_reserved_bytes", 0)),
            )
            control_allocation = min(STRUCTURED_TOOL_CONTROL_LIMIT_BYTES, remaining)
            budget["tool_output_control_reserved_bytes"] = (
                int(budget.get("tool_output_control_reserved_bytes", 0)) + control_allocation
            )
            budget["context_materialization_checkpoint"] = True
            budget["next_api_call_blocked"] = True
            atomic_json(budget_path, budget)
            return {
                "status": "delivered_rejection",
                "classification": "unreserved_tool_call",
                "reserved_control_bytes": control_allocation,
                "batch_call_count": 1,
                "estimated_batch_bytes": 0,
                "remaining_batch_bytes": remaining,
            }
        rejected = reservation.get("status") == "rejected"
        reservation["status"] = "delivered_rejection" if rejected else "claimed"
        atomic_json(budget_path, budget)
        return dict(reservation)


def _rejected_batch_result(
    tool_name: str,
    arguments: dict[str, Any],
    reservation: dict[str, Any],
    budget_path: Path,
) -> str:
    payload = {
        "error": "Hermes guard: atomic tool-output batch exceeds the remaining allowance",
        "classification": reservation.get("classification") or "context_materialization_required",
        "tool": tool_name,
        "batch_id": reservation.get("batch_id"),
        "batch_call_count": reservation.get("batch_call_count"),
        "estimated_batch_bytes": reservation.get("estimated_batch_bytes"),
        "remaining_batch_bytes": reservation.get("remaining_batch_bytes"),
        "next_offset": _next_offset(arguments),
        "retry_allowed": False,
        "next_action": "Use the packet's materialized evidence; do not repeat this batch.",
    }
    rendered = _fit_structured_result(
        payload,
        int(reservation.get("reserved_control_bytes") or 0),
    )
    lock_path = budget_path.with_name(f".{budget_path.name}.tool-output.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = _load_budget(budget_path)
        reserved_control = int(reservation.get("reserved_control_bytes") or 0)
        budget["tool_output_control_reserved_bytes"] = max(
            0,
            int(budget.get("tool_output_control_reserved_bytes", 0)) - reserved_control,
        )
        budget["tool_output_control_bytes"] = int(budget.get("tool_output_control_bytes", 0)) + len(
            rendered.encode()
        )
        budget["tool_output_batch_rejections_delivered"] = (
            int(budget.get("tool_output_batch_rejections_delivered", 0)) + 1
        )
        atomic_json(budget_path, budget)
    return rendered


def bounded_tool_output(
    tool_name: str,
    result: Any,
    *,
    arguments: dict[str, Any] | None = None,
    reserved_limit: int | None = None,
) -> Any:
    """Cap one tool result and the cumulative bounded-session tool context."""
    manifest = json.loads(Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text())
    if manifest.get("bounded_substage_id") is None:
        return result
    budget_path = Path(str(manifest["budget_path"]))
    lock_path = budget_path.with_name(f".{budget_path.name}.tool-output.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _bounded_tool_output_locked(
            tool_name,
            result,
            budget_path,
            arguments=arguments,
            reserved_limit=reserved_limit,
        )


def _bounded_tool_output_locked(
    tool_name: str,
    result: Any,
    budget_path: Path,
    *,
    arguments: dict[str, Any] | None = None,
    reserved_limit: int | None = None,
) -> Any:
    budget = _load_budget(budget_path)
    rendered = result if isinstance(result, str) else json.dumps(result, default=str)
    encoded = rendered.encode("utf-8", "replace")
    observed = len(encoded)
    prior_returned = int(budget.get("tool_output_returned_bytes", 0))
    prior_control = int(budget.get("tool_output_control_bytes", 0))
    per_call_limit = int(budget.get("tool_output_limit_bytes", TOOL_OUTPUT_LIMIT_BYTES))
    session_remaining = max(
        0,
        int(budget.get("session_tool_output_limit_bytes", SESSION_TOOL_OUTPUT_LIMIT_BYTES))
        - prior_returned
        - prior_control
        - int(budget.get("tool_output_control_reserved_bytes", 0)),
    )
    returned_limit = min(
        per_call_limit,
        session_remaining,
        reserved_limit if reserved_limit is not None else per_call_limit,
    )
    budget["tool_output_observed_bytes"] = (
        int(budget.get("tool_output_observed_bytes", 0)) + observed
    )
    if observed <= returned_limit:
        budget["tool_output_returned_bytes"] = prior_returned + observed
        atomic_json(budget_path, budget)
        return result
    preview_bytes = encoded[: max(0, returned_limit - 640)]
    preview = preview_bytes.decode("utf-8", "ignore")
    bounded = _fit_structured_result(
        {
            "error": "Hermes guard: bounded tool-output limit reached",
            "classification": "bounded_truncation",
            "tool": tool_name,
            "observed_bytes": observed,
            "returned_limit_bytes": returned_limit,
            "next_offset": _next_offset(arguments),
            "retry_allowed": _next_offset(arguments) is not None,
            "preview": preview,
        },
        returned_limit,
    )
    bounded_size = len(bounded.encode("utf-8"))
    budget["tool_output_returned_bytes"] = prior_returned + bounded_size
    budget["tool_output_truncations"] = int(budget.get("tool_output_truncations", 0)) + 1
    atomic_json(budget_path, budget)
    return bounded


def execute_bounded_tool(tool_name: str, arguments: dict[str, Any], next_call: Callable) -> Any:
    manifest = json.loads(Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text())
    if manifest.get("bounded_substage_id") is None:
        return next_call(arguments)
    budget_path = Path(str(manifest["budget_path"]))
    reservation = _claim_tool_reservation(tool_name, arguments, budget_path)
    if reservation is not None and reservation.get("status") == "delivered_rejection":
        return _rejected_batch_result(tool_name, arguments, reservation, budget_path)
    if reservation is None:
        raise GuardError("bounded tool call lacked an atomic batch reservation")
    result = next_call(arguments)
    return bounded_tool_output(
        tool_name,
        result,
        arguments=arguments,
        reserved_limit=(
            int(reservation["reserved_bytes"])
            if reservation is not None and isinstance(reservation.get("reserved_bytes"), int)
            else None
        ),
    )


def _repo_path(value: str, repository: Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (repository / path).resolve()
    if not _resolved_under(resolved, repository):
        raise GuardError("file access outside the repository is forbidden")
    relative = resolved.relative_to(repository).as_posix()
    if relative == ".git" or relative.startswith(".git/"):
        raise GuardError("direct Git metadata access is forbidden")
    parts = Path(relative).parts
    if (
        any(part == ".env" or part.startswith(".env.") for part in parts)
        or "secrets" in parts
        or Path(relative).name in {"auth.json", "credentials.json"}
        or Path(relative).suffix.lower() in {".key", ".pem", ".p12", ".pfx"}
    ):
        raise GuardError("secret and credential paths are forbidden")
    return resolved


def _writable_path(
    path: Path,
    repository: Path,
    writable_paths: list[str],
    *,
    exact_paths: bool = False,
) -> None:
    relative = path.relative_to(repository).as_posix()
    normalized = [allowed.rstrip("/") for allowed in writable_paths]
    permitted = (
        relative in normalized
        if exact_paths
        else any(relative == allowed or relative.startswith(allowed + "/") for allowed in normalized)
    )
    if not permitted:
        raise GuardError("write is outside the dispatcher-authorized candidate scope")


def _guard_patch(
    patch: str,
    repository: Path,
    writable_paths: list[str],
    *,
    exact_paths: bool = False,
) -> None:
    raw_headers = PATCH_FILE_HEADER.findall(patch)
    operations = PATCH_OPERATION.findall(patch)
    if not operations or len(raw_headers) != len(operations):
        raise GuardError("patch mode requires explicit repository paths")
    for operation, raw_value in operations:
        endpoints = (
            [value.strip() for value in raw_value.split("->")]
            if operation == "Move"
            else [raw_value.strip()]
        )
        if (
            any(not value for value in endpoints)
            or (operation == "Move" and len(endpoints) != 2)
            or (operation != "Move" and len(endpoints) != 1)
        ):
            raise GuardError("patch operation endpoints are invalid")
        for value in endpoints:
            resolved = _repo_path(value, repository)
            relative = resolved.relative_to(repository).as_posix()
            if CANONICAL_DOCUMENT.fullmatch(relative):
                raise GuardError("canonical policy documents are read-only")
            _writable_path(
                resolved,
                repository,
                writable_paths,
                exact_paths=exact_paths,
            )


def guard_tool(tool_name: str, args: dict[str, Any]) -> None:
    manifest = json.loads(Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text())
    repository = Path(str(manifest["repository"])).resolve()
    review_only = manifest.get("stage") == "independent_review"
    bounded_substage = manifest.get("bounded_substage_id")
    writable_paths = manifest.get("writable_paths")
    readable_paths = manifest.get("readable_paths")
    if not isinstance(writable_paths, list) or any(
        not isinstance(path, str) for path in writable_paths
    ):
        raise GuardError("dispatcher-authorized candidate write scope is invalid")
    if not isinstance(readable_paths, list) or any(
        not isinstance(path, str) for path in readable_paths
    ):
        raise GuardError("dispatcher-authorized candidate read scope is invalid")
    if tool_name in {"read_file", "search_files"}:
        resolved = _repo_path(str(args.get("path") or "."), repository)
        relative = resolved.relative_to(repository).as_posix()
        if bounded_substage is not None:
            forbidden = {
                "Makefile",
                "ops/NOW.md",
                "ops/STATE.json",
                "ops/QUEUE.md",
                "ops/V1_ROADMAP.json",
            }
            if relative in forbidden or CANONICAL_DOCUMENT.fullmatch(relative):
                raise GuardError(
                    "bounded packet already materializes compact and canonical evidence"
                )
            if relative not in readable_paths:
                raise GuardError("read is outside the dispatcher-identified relevant paths")
            if tool_name == "search_files" and int(args.get("limit") or 50) > 50:
                raise GuardError("bounded search result limit exceeds 50")
        return
    if tool_name in {"write_file", "patch"}:
        if review_only:
            raise GuardError("independent review is read-only")
        if tool_name == "patch" and args.get("mode") == "patch":
            _guard_patch(
                str(args.get("patch") or ""),
                repository,
                writable_paths,
                exact_paths=(bounded_substage == "sign_in"),
            )
            return
        resolved = _repo_path(str(args.get("path") or ""), repository)
        relative = resolved.relative_to(repository).as_posix()
        if CANONICAL_DOCUMENT.fullmatch(relative):
            raise GuardError("canonical policy documents are read-only")
        _writable_path(
            resolved,
            repository,
            writable_paths,
            exact_paths=(bounded_substage == "sign_in"),
        )
        return
    if tool_name == "process":
        raise GuardError("background process control is not permitted")
    if tool_name != "terminal":
        if tool_name in {"todo", "todo_read", "todo_write"}:
            if bounded_substage is not None:
                raise GuardError("todo and planning tools are forbidden for a bounded substage")
            return
        raise GuardError("tool is outside the stage-appropriate allowlist")
    if args.get("background") or args.get("pty"):
        raise GuardError("background and interactive terminal execution are forbidden")
    workdir = _repo_path(str(args.get("workdir") or repository), repository)
    command = str(args.get("command") or "")
    if not command or re.search(r"[\n\r;&|`<>]|\$\(", command):
        raise GuardError("shell composition, redirection, and substitution are forbidden")
    try:
        words = shlex.split(command)
    except ValueError as error:
        raise GuardError("terminal command is not safely parseable") from error
    if not words:
        raise GuardError("empty terminal command is forbidden")
    if words[0] == "git":
        if len(words) < 2 or words[1] not in {"status", "diff"}:
            raise GuardError("only read-only git status and git diff are permitted")
        dangerous_git_options = {
            "--ext-diff",
            "--no-index",
            "--textconv",
            "--ita-invisible-in-index",
            "--ita-visible-in-index",
        }
        if any(word in dangerous_git_options or word.startswith("--output") for word in words[2:]):
            raise GuardError("Git options that execute helpers or escape scope are forbidden")
        path_mode = False
        pathspec_count = 0
        for word in words[2:]:
            if word == "--":
                path_mode = True
                continue
            if path_mode:
                resolved = _repo_path(word, repository)
                pathspec_count += 1
                if (
                    bounded_substage is not None
                    and resolved.relative_to(repository).as_posix() not in readable_paths
                ):
                    raise GuardError("bounded git diff path is outside the directly relevant paths")
        if (
            bounded_substage is not None
            and words[1] == "diff"
            and (not path_mode or pathspec_count == 0)
        ):
            raise GuardError("bounded git diff requires directly relevant explicit pathspecs")
        return
    if words[0] == "make":
        if review_only:
            raise GuardError("independent review cannot run mutating verification targets")
        if len(words) != 2 or words[1] not in ALLOWED_MAKE_TARGETS:
            raise GuardError("only one repository-owned verification make target is permitted")
        if workdir != repository:
            raise GuardError("verification make targets must run from the repository root")
        return
    raise GuardError("terminal command is outside the repository-owned allowlist")


def register_plugin(ctx: Any) -> None:
    def llm_execution(request: dict[str, Any], next_call: Callable, **_: Any) -> Any:
        try:
            return enforce_llm_call(request, next_call)
        except Exception as error:
            # Hermes execution middleware is intentionally fail-open for ordinary
            # plugin bugs. A policy boundary must therefore leave the isolated
            # worker via BaseException so the provider callback cannot run.
            raise SystemExit(f"Hermes guard stopped model execution: {error}") from error

    def pre_tool_call(tool_name: str, args: dict[str, Any], **_: Any) -> Any:
        try:
            guard_tool(tool_name, args)
        except Exception as error:
            try:
                message = _deliver_policy_rejection(tool_name, args, error)
            except Exception as accounting_error:
                message = (
                    f"Hermes guard: {error}; bounded rejection accounting unavailable: "
                    f"{accounting_error}"
                )
            return {
                "action": "block",
                "message": message,
            }
        return None

    def tool_execution(
        tool_name: str,
        args: dict[str, Any],
        next_call: Callable,
        **_: Any,
    ) -> Any:
        try:
            guard_tool(tool_name, args)
        except Exception as error:
            # Short-circuit without raising: Hermes deliberately treats an
            # ordinary middleware Exception as fail-open.
            try:
                return _deliver_policy_rejection(tool_name, args, error)
            except Exception as accounting_error:
                return (
                    f"Hermes guard: {error}; bounded rejection accounting unavailable: "
                    f"{accounting_error}"
                )
        try:
            return execute_bounded_tool(tool_name, args, next_call)
        except Exception as error:
            # Hermes deliberately continues to the downstream tool when ordinary
            # execution middleware raises before calling next_call. Reservation,
            # execution, and result-accounting failures are policy-boundary
            # failures, so leave via BaseException and never permit that fallback.
            raise SystemExit(f"Hermes guard stopped tool execution: {error}") from error

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_middleware("llm_execution", llm_execution)
    ctx.register_middleware("tool_execution", tool_execution)
    try:
        manifest = json.loads(Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text())
        budget_path = Path(str(manifest["budget_path"]))
        budget = _load_budget(budget_path)
        process_mode = os.environ.get("PROPERTY_RENTAL_HERMES_PROCESS_MODE")
        if process_mode not in {"preflight", "chat"}:
            raise GuardError("Hermes guard process mode is missing or invalid")
        budget["guard_loaded"] = True
        budget[f"{process_mode}_guard_loaded"] = True
        budget["guard_capabilities"] = [
            "cumulative_llm_execution",
            "least_privilege_pre_tool_block",
            "least_privilege_tool_execution",
        ]
        if process_mode == "chat":
            budget["chat_guard_pid"] = os.getpid()
        atomic_json(budget_path, budget)
        if process_mode == "chat":
            session_home = Path(os.environ["HERMES_HOME"]).resolve()
            source_path = session_home / "guard-source-auth-path"
            source_auth = Path(source_path.read_text().strip()).resolve()
            if not source_auth.is_file():
                raise GuardError("guarded provider authentication is unavailable")
            auth_target = session_home / "auth.json"
            if auth_target.exists() or auth_target.is_symlink():
                raise GuardError("guarded provider authentication target already exists")
            auth_target.symlink_to(source_auth)
    except Exception as error:
        raise SystemExit(f"Hermes guard registration failed: {error}") from error


def finalize_usage(manifest: dict[str, Any], usage_path: Path) -> None:
    budget = _load_budget(Path(str(manifest["budget_path"])))
    if budget.get("chat_guard_loaded") is not True:
        raise GuardError("guard did not attach to the actual Hermes chat process")
    policy = manifest["token_policy"]
    atomic_json(
        usage_path,
        {
            "model": budget.get("effective_model"),
            "reasoning_effort": policy["requested_reasoning"],
            "configured_max_tokens": policy["cumulative_ceiling"],
            "session_id": manifest["manifest_id"],
            "api_calls": budget["api_calls_completed"],
            "api_calls_started": budget["api_calls_started"],
            "input_tokens": budget["input_tokens"],
            "output_tokens": budget["output_tokens"],
            "cache_read_tokens": budget["cache_read_tokens"],
            "reasoning_tokens": budget["reasoning_tokens"],
            "total_tokens": budget["counted_total_tokens"],
            "counted_token_definition": "input_tokens + output_tokens",
            "cache_read_double_counted": False,
            "cumulative_boundary": budget["ceiling"],
            "boundary_reached": budget["boundary_reached"],
            "next_api_call_blocked": budget["next_api_call_blocked"],
            "reservation_blocked": budget.get("reservation_blocked") is True,
            "predicted_next_context_tokens": budget.get("predicted_next_context_tokens", 0),
            "token_estimation_status": budget.get("token_estimation_status"),
            "token_estimate_method": budget.get("token_estimate_method"),
            "token_estimate_inputs": budget.get("token_estimate_inputs") or {},
            "token_estimate_validation_margin_tokens": budget.get(
                "token_estimate_validation_margin_tokens",
                CONTEXT_RESERVATION_MARGIN_TOKENS,
            ),
            "token_estimate_provider_validated": budget.get("token_estimate_provider_validated"),
            "token_estimate_observed_shortfall_tokens": budget.get(
                "token_estimate_observed_shortfall_tokens", 0
            ),
            "reserved_completion_checkpoint_tokens": budget.get(
                "reserved_completion_checkpoint_tokens",
                MINIMUM_COMPLETION_CHECKPOINT_TOKENS,
            ),
            "context_reservation_margin_tokens": budget.get(
                "context_reservation_margin_tokens", CONTEXT_RESERVATION_MARGIN_TOKENS
            ),
            "locally_reserved_next_call_tokens": budget.get("locally_reserved_next_call_tokens", 0),
            "provider_completion_limit_mode": budget.get(
                "provider_completion_limit_mode", "local_proactive_reservation"
            ),
            "provider_request_omits_max_output_tokens": budget.get(
                "provider_request_omits_max_output_tokens"
            )
            is True,
            "unsupported_provider_parameters_removed": budget.get(
                "unsupported_provider_parameters_removed", []
            ),
            "reservation_violation": budget.get("reservation_violation") is True,
            "in_flight_overshoot_tokens": budget["in_flight_overshoot_tokens"],
            "tool_output_limit_bytes": budget.get("tool_output_limit_bytes"),
            "session_tool_output_limit_bytes": budget.get("session_tool_output_limit_bytes"),
            "tool_output_observed_bytes": budget.get("tool_output_observed_bytes", 0),
            "tool_output_returned_bytes": budget.get("tool_output_returned_bytes", 0),
            "tool_output_truncations": budget.get("tool_output_truncations", 0),
            "tool_output_control_bytes": budget.get("tool_output_control_bytes", 0),
            "tool_output_batch_rejections": budget.get("tool_output_batch_rejections", 0),
            "tool_output_batch_rejections_delivered": budget.get(
                "tool_output_batch_rejections_delivered", 0
            ),
            "context_materialization_checkpoint": budget.get("context_materialization_checkpoint")
            is True,
            "guard_loaded": budget.get("guard_loaded") is True,
            "preflight_guard_loaded": budget.get("preflight_guard_loaded") is True,
            "chat_guard_loaded": budget.get("chat_guard_loaded") is True,
            "chat_guard_pid": budget.get("chat_guard_pid"),
            "guard_capabilities": budget.get("guard_capabilities") or [],
            **(
                {"stop_reason": "context_materialization_required"}
                if budget.get("context_materialization_checkpoint") is True
                else {"stop_reason": "token_estimation_unavailable"}
                if budget.get("token_estimation_status") == "unavailable"
                else {"stop_reason": "proactive_budget_reservation"}
                if budget.get("reservation_blocked") is True
                else ({"stop_reason": "token_ceiling"} if budget["boundary_reached"] else {})
            ),
        },
    )


def main() -> int:
    if len(sys.argv) < 2:
        raise GuardError("guard command is required")
    command = sys.argv[1]
    if command == "validate" and len(sys.argv) == 4:
        validate_manifest(
            Path(sys.argv[2]),
            task_path=Path(sys.argv[3]),
            consume=True,
            current_pid=os.getppid(),
        )
        return 0
    if command == "prepare-home" and len(sys.argv) == 5:
        manifest = validate_manifest(Path(sys.argv[2]), task_path=Path(sys.argv[3]), consume=False)
        source_home = Path(
            os.environ.get("PROPERTY_RENTAL_HERMES_SOURCE_HOME", str(Path.home() / ".hermes"))
        )
        prepare_session_home(manifest, Path(sys.argv[4]), source_home)
        return 0
    if command == "finalize-usage" and len(sys.argv) == 3:
        path = Path(sys.argv[2])
        manifest = json.loads(path.read_text())
        finalize_usage(manifest, Path(str(manifest["usage_path"])))
        return 0
    raise GuardError("unsupported guard command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as error:
        print(f"Hermes guard: {error}", file=sys.stderr)
        raise SystemExit(64)
