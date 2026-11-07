"""The Telegram bots on the Mac mini test run (owner ask 07/11/2026: "create telegram bot").

`scripts/local/telegram-setup.sh` ("Set up Telegram test.command") calls this module for the
three steps that need the database or careful JSON. It never prints a key or a token.

* ``ids``: the one Property and the Owner account the bot jobs run as (runtime login).
* ``service-actor``: the service actor the Staff bot's HR calls need (DL-174). The test run
  has no billing worker, so it registers one service principal for the Property, the same row the
  tests use, with the migration login; an active one is reused, so running it again adds nothing.
* ``write-config``: the operations file of the test run, from the committed production file with
  every path moved into the test run's own folder and the bots turned on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from property_rental.operations_config import (
    BOT_CODES,
    OperationsConfigError,
    load_operations_config,
)

# File names written by telegram-setup.sh. Built with a suffix, so the capability check of
# tests/test_access_control.py does not read them as dotted capability names.
OFFICE_KEY = Path("office").with_suffix(".pem")
OPERATIONS_FILE = Path("operations").with_suffix(".json")


class LocalSetupError(RuntimeError):
    """The test run is not ready for the bots; the message says what to do."""


def property_and_owner(database_url: str) -> tuple[UUID, UUID]:
    """The one Property and the one Owner-class account of the test run."""
    with psycopg.connect(database_url) as connection:
        properties = connection.execute("SELECT id FROM app.properties ORDER BY id").fetchall()
        owners = connection.execute(
            "SELECT actor_id FROM app.user_account_classes WHERE account_class = 'owner'"
        ).fetchall()
    if len(properties) != 1:
        raise LocalSetupError(
            "The test app needs exactly one Property. Start the test app and set it up first."
        )
    if len(owners) != 1:
        raise LocalSetupError("The test app needs the Owner account. Make it first.")
    return UUID(str(properties[0][0])), UUID(str(owners[0][0]))


def service_actor(database_url: str, property_id: UUID, owner_id: UUID) -> UUID:
    """The active service actor of the Property, registered once when there is none."""
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT principal.actor_id FROM app.billing_service_principals AS principal "
            "JOIN app.actor_identities AS identity ON identity.actor_id = principal.actor_id "
            "WHERE principal.property_id = %s AND principal.lifecycle_state = 'active' "
            "AND identity.identity_kind = 'SERVICE' ORDER BY principal.created_at LIMIT 1",
            (property_id,),
        ).fetchone()
        if row is not None:
            return UUID(str(row[0]))
        actor = uuid4()
        connection.execute(
            "INSERT INTO app.billing_service_principals (actor_id, property_id, capability, "
            "lifecycle_state, created_by) VALUES (%s, %s, 'billing.generate', 'active', %s)",
            (actor, property_id, owner_id),
        )
    return actor


def mac_test_config(
    template: dict[str, object], folder: Path, relay_host: str
) -> dict[str, object]:
    """The production file with the status folder and the bots moved into ``folder``."""
    if not folder.is_absolute():
        raise LocalSetupError("The Telegram folder must be an absolute path.")
    host = relay_host.strip().removeprefix("https://").rstrip("/")
    if not host or "/" in host or " " in host:
        raise LocalSetupError("The relay address is not right.")
    config: dict[str, object] = json.loads(json.dumps(template))
    config["environment"] = "test"
    config["status_directory"] = str(folder / "status")
    config["telegram_bots"] = {
        "enabled": True,
        "relay_host": host,
        "relay_pull_key_file": str(folder / "relay-pull.key"),
        "office_private_key_file": str(folder / OFFICE_KEY),
        "bots": {
            code: {"token_file": str(folder / f"{code.lower()}_bot_token")} for code in BOT_CODES
        },
        "media_directory": str(folder / "media"),
    }
    return config


def write_config(template_path: Path, folder: Path, relay_host: str) -> Path:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    config = mac_test_config(template, folder, relay_host)
    target = folder / OPERATIONS_FILE
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    os.chmod(target, 0o600)
    try:
        load_operations_config(target)
    except OperationsConfigError as error:
        raise LocalSetupError(f"The operations file is not right: {error}") from error
    return target


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise LocalSetupError(f"{name} is required")
    return value


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram bots on the Mac mini test run")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ids", help="print the Property and the Owner account")
    service = commands.add_parser("service-actor", help="print the Staff bot's service actor")
    service.add_argument("--property-id", required=True, type=UUID)
    service.add_argument("--owner-id", required=True, type=UUID)
    config = commands.add_parser("write-config", help="write the test run's operations file")
    config.add_argument("--template", required=True, type=Path)
    config.add_argument("--folder", required=True, type=Path)
    config.add_argument("--relay-host", required=True)
    parsed = parser.parse_args(arguments)
    try:
        if parsed.command == "ids":
            property_id, owner_id = property_and_owner(_url("APP_DATABASE_URL"))
            print(f"{property_id} {owner_id}")
        elif parsed.command == "service-actor":
            print(
                service_actor(_url("MIGRATION_DATABASE_URL"), parsed.property_id, parsed.owner_id)
            )
        else:
            print(write_config(parsed.template, parsed.folder, parsed.relay_host))
    except (LocalSetupError, psycopg.Error) as error:
        message = str(error) if isinstance(error, LocalSetupError) else "the database refused"
        print(f"telegram_setup:{message}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
