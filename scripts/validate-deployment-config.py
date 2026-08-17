#!/usr/bin/env python3
"""Validate deployment identity contracts without exposing secret values."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
CONFIG_ROOT: Final = REPOSITORY_ROOT / "config" / "deployment"
CONTRACT_PATH: Final = CONFIG_ROOT / "identity-secret-contract.json"
IDENTITY_KINDS: Final = {"runtime", "migration", "backup", "restore", "human_admin"}
PLACEHOLDER_MARKERS: Final = (b"change-me", b"placeholder", b"replace-me", b"<secret>")


class ValidationError(ValueError):
    """A deployment profile violates the checked contract."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot load configuration: {path}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"configuration must be an object: {path}")
    return value


def _required_source_keys(contract: dict[str, Any]) -> set[str]:
    identities = contract.get("database_identities")
    secret_inputs = contract.get("secret_inputs")
    if not isinstance(identities, dict) or set(identities) != IDENTITY_KINDS:
        raise ValidationError("contract must define the five required database identities")
    if not isinstance(secret_inputs, dict) or set(secret_inputs) != {
        "ordinary_application",
        "backup_encryption",
    }:
        raise ValidationError("contract must define separated application and backup secrets")

    roles: set[str] = set()
    source_keys: set[str] = set()
    for identity in identities.values():
        if not isinstance(identity, dict):
            raise ValidationError("database identity definitions must be objects")
        role = identity.get("database_role")
        source_key = identity.get("source_key")
        standing_access = identity.get("standing_access")
        if not isinstance(role, str) or not role:
            raise ValidationError("database identity role is missing")
        if not isinstance(source_key, str) or not source_key:
            raise ValidationError("database identity source key is missing")
        if not isinstance(standing_access, str) or not standing_access:
            raise ValidationError("database identity definitions are incomplete")
        roles.add(role)
        source_keys.add(source_key)
    if len(roles) != len(identities) or len(source_keys) != len(identities):
        raise ValidationError("database roles and credential source keys must be distinct")

    for secret_input in secret_inputs.values():
        if not isinstance(secret_input, dict):
            raise ValidationError("secret input definitions must be objects")
        source_key = secret_input.get("source_key")
        if not isinstance(source_key, str) or not source_key:
            raise ValidationError("secret input source key is missing")
        source_keys.add(source_key)

    if len(source_keys) != len(identities) + len(secret_inputs):
        raise ValidationError("all database and non-database secret inputs must be separate")
    return source_keys


def validate_profile_schema(
    contract: dict[str, Any], profile: dict[str, Any], expected_environment: str
) -> set[Path]:
    """Validate source references only; never accept direct secret values."""
    if set(profile) != {"schema_version", "environment", "sources"}:
        raise ValidationError("profile contains unsupported fields")
    if profile.get("schema_version") != contract.get("schema_version"):
        raise ValidationError("profile schema version does not match the contract")
    if profile.get("environment") != expected_environment:
        raise ValidationError("profile environment does not match its selected environment")

    source_policy = contract.get("source_policy")
    if not isinstance(source_policy, dict) or source_policy.get("kind") != "protected_file":
        raise ValidationError("contract must require protected-file secret sources")
    prefix = source_policy.get("required_path_prefix")
    if not isinstance(prefix, str) or not prefix.startswith("/"):
        raise ValidationError("protected-file path prefix must be absolute")

    prohibited = source_policy.get("direct_value_keys_prohibited")
    if not isinstance(prohibited, list) or not all(isinstance(key, str) for key in prohibited):
        raise ValidationError("contract direct-value prohibition is invalid")
    if set(profile).intersection(prohibited):
        raise ValidationError("profile contains a prohibited direct secret value")

    sources = profile.get("sources")
    if not isinstance(sources, dict) or set(sources) != _required_source_keys(contract):
        raise ValidationError(
            "profile must provide exactly the required protected source references"
        )

    paths: set[Path] = set()
    for source_key, raw_path in sources.items():
        if source_key in prohibited or not source_key.endswith("_FILE"):
            raise ValidationError("secret source keys must be file references, not direct values")
        if not isinstance(raw_path, str) or not raw_path.startswith(prefix):
            raise ValidationError("secret source paths must use the protected absolute prefix")
        if ".." in Path(raw_path).parts:
            raise ValidationError("secret source paths must not traverse outside the protected prefix")
        if f"prm_{expected_environment}_" not in raw_path:
            raise ValidationError("secret source path must be namespaced to its environment")
        path = Path(raw_path)
        if path in paths:
            raise ValidationError("secret source paths must be distinct within an environment")
        paths.add(path)
    return paths


def check_examples() -> None:
    """Check every committed source-reference profile without resolving secrets."""
    contract = _load_json(CONTRACT_PATH)
    environments = contract.get("environments")
    if not isinstance(environments, list) or environments != [
        "development",
        "test",
        "staging",
        "production",
    ]:
        raise ValidationError("contract environments must be explicit and ordered")

    all_paths: set[Path] = set()
    for environment in environments:
        profile = _load_json(CONFIG_ROOT / f"{environment}.json")
        paths = validate_profile_schema(contract, profile, environment)
        if all_paths.intersection(paths):
            raise ValidationError("secret source paths must not cross environment boundaries")
        all_paths.update(paths)


def check_resolved_profile(profile_path: Path, source_root: Path = Path("/")) -> None:
    """Fail closed unless every referenced protected source is present and non-placeholder."""
    contract = _load_json(CONTRACT_PATH)
    profile = _load_json(profile_path)
    environment = profile.get("environment")
    if not isinstance(environment, str):
        raise ValidationError("profile environment is missing")
    paths = validate_profile_schema(contract, profile, environment)
    for path in paths:
        resolved_path = source_root / path.relative_to("/")
        try:
            value = resolved_path.read_bytes()
        except OSError as error:
            raise ValidationError("a required protected secret source is unavailable") from error
        lowered = value.strip().lower()
        if not lowered or any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            raise ValidationError("a required protected secret source is empty or placeholder-only")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-examples", help="validate committed source-reference profiles")
    profile_parser = subparsers.add_parser(
        "check-profile", help="validate a profile and require every protected source"
    )
    profile_parser.add_argument("profile", type=Path)
    profile_parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("/"),
        help="filesystem root containing the referenced protected sources",
    )
    arguments = parser.parse_args()

    try:
        if arguments.command == "check-examples":
            check_examples()
        else:
            check_resolved_profile(arguments.profile, arguments.source_root)
    except ValidationError as error:
        print(f"deployment configuration invalid: {error}", file=sys.stderr)
        return 1
    print("deployment configuration valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
