#!/usr/bin/env python3
"""Validate deployment identity contracts without exposing secret values."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
CONFIG_ROOT: Final = REPOSITORY_ROOT / "config" / "deployment"
CONTRACT_PATH: Final = CONFIG_ROOT / "identity-secret-contract.json"
IDENTITY_KINDS: Final = {
    "runtime",
    "financial",
    "migration",
    "backup",
    "restore",
    "human_admin",
    "bootstrap",
}
PLACEHOLDER_MARKERS: Final = (b"change-me", b"placeholder", b"replace-me", b"<secret>")
# V1-059 (DL-071 answers 1 to 8 and 17): the production operations configuration.
OPERATIONS_PATH: Final = CONFIG_ROOT / "production-operations.json"
TELEGRAM_TOKEN_EXAMPLE_PATH: Final = CONFIG_ROOT / "production-telegram-bot-token.example"
TELEGRAM_CHAT_IDS_EXAMPLE_PATH: Final = CONFIG_ROOT / "production-telegram-chat-ids.example.json"
TELEGRAM_HOST: Final = "api.telegram.org"
TELEGRAM_TOKEN_SHAPE: Final = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{30,64}")
OPERATIONS_KEYS: Final = {
    "schema_version",
    "environment",
    "property_time_zone",
    "remote_access",
    "egress_allowlist",
    "backup",
    "status_directory",
    "alerts",
    "logs",
}
SECRET_WORDS: Final = ("token", "password", "secret", "key", "chat_id")


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
        raise ValidationError("contract must define the seven required database identities")
    if not isinstance(secret_inputs, dict) or set(secret_inputs) != {
        "ordinary_application",
        "backup_encryption",
        "bootstrap_totp_protection",
    }:
        raise ValidationError("contract must define all separated protected secret inputs")

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
    check_operations(_load_json(OPERATIONS_PATH), _load_json(CONFIG_ROOT / "production.json"))


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"operations configuration: {name} must be an object")
    return value


def _secret_value_keys(value: object, path: str = "") -> list[str]:
    """Keys that look like secrets but are not file references."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(word in lowered for word in SECRET_WORDS) and not lowered.endswith("_file"):
                found.append(name)
            found.extend(_secret_value_keys(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_secret_value_keys(item, f"{path}[{index}]"))
    return found


def _production_secret_path(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.startswith("/run/secrets/prm_production_"):
        raise ValidationError(
            f"operations configuration: {name} must be a /run/secrets/prm_production_ file"
        )
    if ".." in Path(value).parts:
        raise ValidationError(f"operations configuration: {name} must not leave /run/secrets")
    return value


def check_no_telegram_token_in_repository_config() -> None:
    """No file of config/deployment may hold something shaped like a Telegram bot token."""
    for path in sorted(CONFIG_ROOT.rglob("*")):
        if path.is_file() and TELEGRAM_TOKEN_SHAPE.search(
            path.read_bytes().decode("utf-8", errors="replace")
        ):
            raise ValidationError(f"a Telegram bot token must never be committed: {path.name}")


def check_operations(operations: dict[str, Any], production_profile: dict[str, Any]) -> None:
    """The production operations configuration must match DL-071 exactly."""
    if set(operations) != OPERATIONS_KEYS:
        raise ValidationError("operations configuration has missing or unsupported fields")
    if operations.get("schema_version") != 1 or operations.get("environment") != "production":
        raise ValidationError("operations configuration must be schema 1 for production")
    if operations.get("property_time_zone") != "Asia/Phnom_Penh":
        raise ValidationError("operations configuration must use the Asia/Phnom_Penh time zone")
    if operations.get("remote_access") != {"enabled": False}:
        raise ValidationError("remote access must be off in V1 (DL-071 answer 6)")
    if operations.get("egress_allowlist") != [TELEGRAM_HOST]:
        raise ValidationError("the outbound allowed list must be exactly the Telegram host")
    secret_value_keys = _secret_value_keys(operations)
    if secret_value_keys:
        raise ValidationError("operations configuration holds a direct secret value field")

    backup = _object(operations.get("backup"), "backup")
    if backup.get("interval_minutes") != 60:
        raise ValidationError("backups must run every 60 minutes (DL-071 answer 1)")
    if backup.get("retention") != {"hourly_days": 2, "daily_days": 30, "monthly_months": 12}:
        raise ValidationError("backup retention must be 2 days, 30 days and 12 months")
    if backup.get("never_delete_last_good_copy") is not True:
        raise ValidationError("retention must never delete the last good backup (DEPLOY-043)")
    offhost = _object(backup.get("offhost"), "backup.offhost")
    if offhost.get("cloud_storage") is not False or not offhost.get("daily") or not offhost.get(
        "weekly"
    ):
        raise ValidationError("off-host copies must be daily and weekly, with no cloud storage")
    if backup.get("restore_test_interval_days") != 92:
        # The health page uses the same fixed 92 days (every 3 months, DL-071 answer 5).
        raise ValidationError("a restore test is due every 92 days (3 months)")
    sources = production_profile.get("sources", {})
    if _production_secret_path(
        backup.get("database_url_file"), "backup.database_url_file"
    ) != sources.get("BACKUP_DATABASE_URL_FILE"):
        raise ValidationError("the backup job must use the backup database identity")
    if _production_secret_path(
        backup.get("encryption_key_file"), "backup.encryption_key_file"
    ) != sources.get("BACKUP_ENCRYPTION_KEY_FILE"):
        raise ValidationError("the backup job must use the backup encryption key")
    for name in ("directory",):
        value = backup.get(name)
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValidationError("the backup folder must be an absolute path")
    status_directory = operations.get("status_directory")
    if not isinstance(status_directory, str) or not status_directory.startswith("/"):
        raise ValidationError("the status folder must be an absolute path")

    alerts = _object(operations.get("alerts"), "alerts")
    telegram = _object(alerts.get("telegram"), "alerts.telegram")
    if telegram.get("api_host") != TELEGRAM_HOST:
        raise ValidationError("Telegram alerts must use the Telegram host on the allowed list")
    if telegram.get("recipients") != ["owner", "manager"]:
        raise ValidationError("Telegram alerts go to the Owner and the Manager (DL-071 answer 8)")
    if telegram.get("optional") is not True:
        raise ValidationError("Telegram must stay optional (SEC-059)")
    token_file = _production_secret_path(telegram.get("bot_token_file"), "bot_token_file")
    chat_file = _production_secret_path(telegram.get("chat_ids_file"), "chat_ids_file")
    if token_file == chat_file or {token_file, chat_file} & set(sources.values()):
        raise ValidationError("the Telegram secret files must be separate from other secrets")

    logs = _object(operations.get("logs"), "logs")
    if logs.get("operational_retention_days") != 90:
        raise ValidationError("technical logs must be kept 90 days (DL-071 answer 17)")

    token_example = TELEGRAM_TOKEN_EXAMPLE_PATH.read_bytes().strip().lower()
    if not any(marker in token_example for marker in PLACEHOLDER_MARKERS):
        raise ValidationError("the committed Telegram bot token example must be a placeholder")
    chats_example = _load_json(TELEGRAM_CHAT_IDS_EXAMPLE_PATH)
    if set(chats_example) != {"owner", "manager"} or any(
        not isinstance(value, str)
        or not any(marker.decode() in value.lower() for marker in PLACEHOLDER_MARKERS)
        for value in chats_example.values()
    ):
        raise ValidationError("the committed Telegram chat id example must be placeholders")
    check_no_telegram_token_in_repository_config()


def check_resolved_operations(source_root: Path) -> str | None:
    """Telegram is optional: a missing or placeholder token gives a warning, not a failure."""
    operations = _load_json(OPERATIONS_PATH)
    telegram = _object(_object(operations.get("alerts"), "alerts").get("telegram"), "telegram")
    for key in ("bot_token_file", "chat_ids_file"):
        path = source_root / Path(str(telegram.get(key))).relative_to("/")
        try:
            value = path.read_bytes().strip().lower()
        except OSError:
            return "warning: Telegram alerts are not set up (optional; the health page warns)"
        if not value or any(marker in value for marker in PLACEHOLDER_MARKERS):
            return "warning: Telegram alerts are not set up (optional; the health page warns)"
    return None


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
            profile = _load_json(arguments.profile)
            if profile.get("environment") == "production":
                warning = check_resolved_operations(arguments.source_root)
                if warning is not None:
                    print(warning, file=sys.stderr)
    except ValidationError as error:
        print(f"deployment configuration invalid: {error}", file=sys.stderr)
        return 1
    print("deployment configuration valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
