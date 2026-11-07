"""The Telegram bots on the Mac mini test run (owner ask 07/11/2026): the setup's database and
operations-file steps (scripts/local/telegram-setup.sh)."""

from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from property_rental.operations_config import load_operations_config
from property_rental.telegram_local_setup_cli import (
    LocalSetupError,
    mac_test_config,
    main,
    property_and_owner,
    service_actor,
    write_config,
)
from test_hr_employees_migration import HrDatabase, make_hr_database
from test_move_in_migration import migrated_database_url as migrated_database_url

TEMPLATE = Path(__file__).resolve().parents[2] / "config/deployment/production-operations.json"


def test_the_mac_operations_file_keeps_every_bot_path_in_its_folder(tmp_path: Path) -> None:
    target = write_config(TEMPLATE, tmp_path, "https://chetana-relay.example.workers.dev/")
    assert target == tmp_path / "operations.json"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    config = load_operations_config(target)
    bots = config.telegram_bots
    assert bots is not None and bots.enabled is True
    assert bots.relay_host == "chetana-relay.example.workers.dev"
    assert bots.api_host == "api.telegram.org"
    paths = [
        bots.relay_pull_key_file,
        bots.office_private_key_file,
        bots.media_directory,
        config.status_directory,
        *bots.bot_token_files.values(),
    ]
    assert all(path.is_relative_to(tmp_path) for path in paths)
    assert bots.bot_token_files["STAFF"] == tmp_path / "staff_bot_token"
    # The committed production file is not changed.
    assert json.loads(TEMPLATE.read_text())["telegram_bots"]["enabled"] is False


def test_a_wrong_relay_address_or_folder_is_refused(tmp_path: Path) -> None:
    template = json.loads(TEMPLATE.read_text())
    for host in ("", "https://", "chetana relay.dev", "example.dev/telegram"):
        with pytest.raises(LocalSetupError):
            mac_test_config(template, tmp_path, host)
    with pytest.raises(LocalSetupError):
        mac_test_config(template, Path("relative"), "chetana-relay.example.workers.dev")


def test_the_database_steps_say_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    assert main(["ids"]) == 1
    assert capsys.readouterr().err.strip() == "telegram_setup:APP_DATABASE_URL is required"


@pytest.fixture(scope="module")
def setup_database(migrated_database_url: str) -> Iterator[HrDatabase]:
    assert migrated_database_url
    yield from make_hr_database("prm_tg_local_setup")


def test_the_setup_finds_the_property_the_owner_and_the_service_actor(
    setup_database: HrDatabase,
) -> None:
    db = setup_database
    assert property_and_owner(db.runtime_url) == (db.property_id, db.owner)
    # The active service actor is used again; nothing new is registered.
    assert service_actor(db.owner_url, db.property_id, db.owner) == db.bot
    assert service_actor(db.owner_url, db.property_id, db.owner) == db.bot
