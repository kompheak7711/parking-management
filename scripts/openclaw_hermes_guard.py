#!/usr/bin/env python3
"""Repository-owned Hermes invocation, least-privilege, and token guard."""

from __future__ import annotations

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

MANIFEST_SCHEMA_VERSION = 1
GUARD_SCHEMA_VERSION = 1
COUNTED_TOKEN_FIELDS = ("input_tokens", "output_tokens")
CACHE_TOKEN_FIELD = "cache_read_tokens"
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


def digest(value: bytes | str | Any) -> str:
    if isinstance(value, str):
        value = value.encode()
    elif not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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
        "token_policy": {
            "provider": provider,
            "model": model,
            "requested_reasoning": requested_reasoning,
            "cumulative_ceiling": cumulative_ceiling,
            "counted_fields": list(COUNTED_TOKEN_FIELDS),
            "cache_read_field": CACHE_TOKEN_FIELD,
            "cache_read_double_counted": False,
            "session_scope": "fresh_stage_session",
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
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
    ):
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
        or digest(dispatcher_record_path.read_bytes())
        != manifest.get("dispatcher_record_sha256")
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
        or dispatcher_record.get("repository_fingerprint")
        != manifest.get("repository_fingerprint")
    ):
        raise GuardError("manifest does not match the live dispatcher candidate record")
    if Path(str(manifest["task_path"])).resolve() != task_path.resolve():
        raise GuardError("invocation task path differs from the manifest")
    if not task_path.is_file() or digest(task_path.read_bytes()) != manifest.get(
        "task_sha256"
    ):
        raise GuardError("invocation task hash differs from the manifest")
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repository, text=True
    ).strip()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
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
        or policy.get("cumulative_ceiling") not in {60_000, 90_000, 120_000}
    ):
        raise GuardError("invocation token policy does not match repository policy")
    stage = str(manifest["stage"])
    ceiling = int(policy["cumulative_ceiling"])
    if stage in {"implementation", "direct_codex_recovery"} and ceiling != 60_000:
        raise GuardError("implementation and ordinary repair require 60000 tokens")
    if stage == "independent_review" and ceiling not in {90_000, 120_000}:
        raise GuardError(
            "independent review requires 90000 or persisted exceptional 120000"
        )
    exceptional = policy.get("exceptional_review_classification")
    if ceiling == 120_000 and not (
        isinstance(exceptional, str) and exceptional.strip()
    ):
        raise GuardError(
            "120000-token review requires a persisted exceptional classification"
        )
    if ceiling != 120_000 and exceptional is not None:
        raise GuardError(
            "exceptional review classification is valid only at 120000 tokens"
        )
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
            raise GuardError(
                "wrapper was not launched by the live repository dispatcher"
            )
    writable_paths = manifest.get("writable_paths")
    if not isinstance(writable_paths, list) or any(
        not isinstance(path, str) or not path or Path(path).is_absolute()
        for path in writable_paths
    ):
        raise GuardError("candidate writable paths are invalid")
    for path in writable_paths:
        resolved = (repository / path).resolve()
        if not _resolved_under(resolved, repository):
            raise GuardError("candidate writable path escapes the repository")
    authorization = authorization or os.environ.get(
        "PROPERTY_RENTAL_INVOCATION_AUTHORIZATION", ""
    )
    if not authorization or digest(authorization) != manifest.get(
        "authorization_sha256"
    ):
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


def prepare_session_home(
    manifest: dict[str, Any], target: Path, source_home: Path
) -> None:
    """Create one isolated nonpersistent Hermes profile for this manifest."""
    target.mkdir(parents=True, exist_ok=False)
    target.chmod(0o700)
    auth = source_home / "auth.json"
    if not auth.is_file():
        raise GuardError(
            "OpenAI Codex authentication is unavailable in the source profile"
        )
    # Authentication is deliberately withheld until the guard registers in the
    # actual chat process. A Hermes process in which the plugin fails to load
    # therefore cannot reach the provider with usable credentials.
    (target / "guard-source-auth-path").write_text(str(auth.resolve()) + "\n")
    (target / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - property-rental-guard\n"
        "model:\n  openai_runtime: direct\n"
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
    output_details = (
        _value(usage, "output_tokens_details", "completion_tokens_details") or {}
    )
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
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != GUARD_SCHEMA_VERSION
    ):
        raise GuardError("cumulative budget ledger is invalid")
    return value


def enforce_llm_call(
    request: dict[str, Any], next_call: Callable[[dict[str, Any]], Any]
) -> Any:
    """Block before the next API call once observed cumulative usage reaches policy."""
    manifest_path = Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"])
    manifest = json.loads(manifest_path.read_text())
    budget_path = Path(str(manifest["budget_path"]))
    budget = _load_budget(budget_path)
    ceiling = int(budget["ceiling"])
    if int(budget["counted_total_tokens"]) >= ceiling:
        budget["boundary_reached"] = True
        budget["next_api_call_blocked"] = True
        atomic_json(budget_path, budget)
        raise GuardError("PROPERTY_RENTAL_CUMULATIVE_TOKEN_CEILING_REACHED")
    remaining = ceiling - int(budget["counted_total_tokens"])
    guarded_request = dict(request)
    for key in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        current = guarded_request.get(key)
        if isinstance(current, int) and current > 0:
            guarded_request[key] = min(current, remaining)
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
    budget["counted_total_tokens"] = int(budget["input_tokens"]) + int(
        budget["output_tokens"]
    )
    budget["effective_model"] = observed.get("model")
    if int(budget["counted_total_tokens"]) >= ceiling:
        budget["boundary_reached"] = True
        budget["in_flight_overshoot_tokens"] = max(
            0, int(budget["counted_total_tokens"]) - ceiling
        )
    atomic_json(budget_path, budget)
    return response


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


def _writable_path(path: Path, repository: Path, writable_paths: list[str]) -> None:
    relative = path.relative_to(repository).as_posix()
    if not any(
        relative == allowed.rstrip("/")
        or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in writable_paths
    ):
        raise GuardError("write is outside the dispatcher-authorized candidate scope")


def _guard_patch(patch: str, repository: Path, writable_paths: list[str]) -> None:
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
            _writable_path(resolved, repository, writable_paths)


def guard_tool(tool_name: str, args: dict[str, Any]) -> None:
    manifest = json.loads(
        Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text()
    )
    repository = Path(str(manifest["repository"])).resolve()
    review_only = manifest.get("stage") == "independent_review"
    writable_paths = manifest.get("writable_paths")
    if not isinstance(writable_paths, list) or any(
        not isinstance(path, str) for path in writable_paths
    ):
        raise GuardError("dispatcher-authorized candidate write scope is invalid")
    if tool_name in {"read_file", "search_files"}:
        _repo_path(str(args.get("path") or "."), repository)
        return
    if tool_name in {"write_file", "patch"}:
        if review_only:
            raise GuardError("independent review is read-only")
        if tool_name == "patch" and args.get("mode") == "patch":
            _guard_patch(str(args.get("patch") or ""), repository, writable_paths)
            return
        resolved = _repo_path(str(args.get("path") or ""), repository)
        relative = resolved.relative_to(repository).as_posix()
        if CANONICAL_DOCUMENT.fullmatch(relative):
            raise GuardError("canonical policy documents are read-only")
        _writable_path(resolved, repository, writable_paths)
        return
    if tool_name == "process":
        raise GuardError("background process control is not permitted")
    if tool_name != "terminal":
        if tool_name in {"todo", "todo_read", "todo_write"}:
            return
        raise GuardError("tool is outside the stage-appropriate allowlist")
    if args.get("background") or args.get("pty"):
        raise GuardError("background and interactive terminal execution are forbidden")
    workdir = _repo_path(str(args.get("workdir") or repository), repository)
    command = str(args.get("command") or "")
    if not command or re.search(r"[\n\r;&|`<>]|\$\(", command):
        raise GuardError(
            "shell composition, redirection, and substitution are forbidden"
        )
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
        if any(
            word in dangerous_git_options or word.startswith("--output")
            for word in words[2:]
        ):
            raise GuardError(
                "Git options that execute helpers or escape scope are forbidden"
            )
        path_mode = False
        for word in words[2:]:
            if word == "--":
                path_mode = True
                continue
            if path_mode:
                _repo_path(word, repository)
        return
    if words[0] == "make":
        if review_only:
            raise GuardError(
                "independent review cannot run mutating verification targets"
            )
        if len(words) != 2 or words[1] not in ALLOWED_MAKE_TARGETS:
            raise GuardError(
                "only one repository-owned verification make target is permitted"
            )
        if workdir != repository:
            raise GuardError(
                "verification make targets must run from the repository root"
            )
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
            raise SystemExit(
                f"Hermes guard stopped model execution: {error}"
            ) from error

    def pre_tool_call(tool_name: str, args: dict[str, Any], **_: Any) -> Any:
        try:
            guard_tool(tool_name, args)
        except Exception as error:  # noqa: BLE001 - policy failures must fail closed
            return {"action": "block", "message": f"Hermes guard: {error}"}
        return None

    def tool_execution(
        tool_name: str,
        args: dict[str, Any],
        next_call: Callable,
        **_: Any,
    ) -> Any:
        try:
            guard_tool(tool_name, args)
        except Exception as error:  # noqa: BLE001 - policy failures must fail closed
            # Short-circuit without raising: Hermes deliberately treats an
            # ordinary middleware Exception as fail-open.
            return json.dumps({"error": f"Hermes guard: {error}"})
        return next_call(args)

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_middleware("llm_execution", llm_execution)
    ctx.register_middleware("tool_execution", tool_execution)
    try:
        manifest = json.loads(
            Path(os.environ["PROPERTY_RENTAL_INVOCATION_MANIFEST"]).read_text()
        )
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
                raise GuardError(
                    "guarded provider authentication target already exists"
                )
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
            "in_flight_overshoot_tokens": budget["in_flight_overshoot_tokens"],
            "guard_loaded": budget.get("guard_loaded") is True,
            "preflight_guard_loaded": budget.get("preflight_guard_loaded") is True,
            "chat_guard_loaded": budget.get("chat_guard_loaded") is True,
            "chat_guard_pid": budget.get("chat_guard_pid"),
            "guard_capabilities": budget.get("guard_capabilities") or [],
            **({"stop_reason": "token_ceiling"} if budget["boundary_reached"] else {}),
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
        manifest = validate_manifest(
            Path(sys.argv[2]), task_path=Path(sys.argv[3]), consume=False
        )
        source_home = Path(
            os.environ.get(
                "PROPERTY_RENTAL_HERMES_SOURCE_HOME", str(Path.home() / ".hermes")
            )
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
