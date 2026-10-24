"""V1-059 operations check and Telegram alert routing (DL-071 answers 6 to 8; DEPLOY-051)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from property_rental import operations_check
from property_rental.operations_check import main, run_check
from property_rental.operations_config import load_operations_config
from property_rental.operations_status import format_time, read_status, write_status

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2027, 3, 15, 3, 0, tzinfo=UTC)
FAKE_TOKEN = "123456789:" + "B" * 35


def make_config(tmp_path: Path, *, telegram: bool = True) -> Path:
    document = json.loads(
        (REPOSITORY_ROOT / "config/deployment/production-operations.json").read_text()
    )
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "token").write_text(FAKE_TOKEN if telegram else "placeholder", encoding="utf-8")
    (secrets / "chats").write_text('{"owner": "1", "manager": "2"}', encoding="utf-8")
    document["backup"]["directory"] = str(tmp_path / "backups")
    document["backup"]["database_url_file"] = str(secrets / "missing-database-file")
    document["status_directory"] = str(tmp_path / "status")
    document["alerts"]["telegram"]["bot_token_file"] = str(secrets / "token")
    document["alerts"]["telegram"]["chat_ids_file"] = str(secrets / "chats")
    document["alerts"]["readiness_url"] = None
    document["alerts"]["disk_paths"] = [str(tmp_path)]
    document["alerts"]["disk_minimum_free_gigabytes"] = 1
    document["alerts"]["disk_minimum_free_percent"] = 1
    document["logs"]["directory"] = str(tmp_path / "logs")
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def all_good(status: Path, now: datetime) -> None:
    good = {"last_outcome": "succeeded", "last_success_at": format_time(now)}
    for name in ("backup", "offhost-daily", "offhost-weekly", "restore-test"):
        write_status(status, name, good)


class Recorder:
    def __init__(self, answer: int = 200) -> None:
        self.texts: list[str] = []
        self.answer = answer

    def __call__(self, address: str, form: dict[str, str]) -> int:
        if form["chat_id"] == "1":
            self.texts.append(form["text"])
        return self.answer


@pytest.fixture
def database_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        operations_check,
        "check_database",
        lambda config: (set(), {"database": "ok", "schema_revision": "20270204_192"}),
    )


def test_an_alert_starts_repeats_after_12_hours_and_ends_once(
    tmp_path: Path, database_ok: None
) -> None:
    config = load_operations_config(make_config(tmp_path))
    all_good(config.status_directory, NOW)
    write_status(
        config.status_directory,
        "backup",
        {"last_outcome": "failed", "last_success_at": format_time(NOW)},
    )
    sender = Recorder()

    assert [w.code for w in run_check(config, now=NOW, post_form=sender)] == ["backup_failed"]
    assert len(sender.texts) == 1 and "NEW: The last backup failed." in sender.texts[0]
    assert "Please look at the health page" in sender.texts[0]

    run_check(config, now=NOW + timedelta(minutes=5), post_form=sender)
    assert len(sender.texts) == 1
    run_check(config, now=NOW + timedelta(hours=12), post_form=sender)
    assert len(sender.texts) == 2 and "STILL: The last backup failed." in sender.texts[1]

    later = NOW + timedelta(hours=12, minutes=5)
    all_good(config.status_directory, later)
    assert run_check(config, now=later, post_form=sender) == []
    assert len(sender.texts) == 3 and "FIXED: The last backup failed." in sender.texts[2]
    checks = read_status(config.status_directory, "checks")
    assert checks is not None and checks["alerts"] == {}


def test_a_failed_delivery_is_tried_again_once_an_hour_and_shown_on_the_page(
    tmp_path: Path, database_ok: None
) -> None:
    config = load_operations_config(make_config(tmp_path))
    all_good(config.status_directory, NOW)
    write_status(config.status_directory, "migration", {"last_outcome": "failed"})
    failing = Recorder(answer=500)
    codes = [w.code for w in run_check(config, now=NOW, post_form=failing)]
    assert codes == ["migration_failed", "telegram_delivery_failed"]
    working = Recorder()
    soon = [w.code for w in run_check(config, now=NOW + timedelta(minutes=5), post_form=working)]
    assert working.texts == []
    assert soon == ["migration_failed", "telegram_delivery_failed"]
    run_check(config, now=NOW + timedelta(hours=1), post_form=working)
    assert len(working.texts) == 1 and "NEW: The last database update" in working.texts[0]
    after = [
        w.code
        for w in run_check(config, now=NOW + timedelta(hours=1, minutes=5), post_form=working)
    ]
    assert after == ["migration_failed"] and len(working.texts) == 1


def test_a_fixed_message_waits_until_delivered_and_an_unsent_alert_ends_silently(
    tmp_path: Path, database_ok: None
) -> None:
    config = load_operations_config(make_config(tmp_path))
    all_good(config.status_directory, NOW)
    write_status(config.status_directory, "migration", {"last_outcome": "failed"})
    sender = Recorder()
    run_check(config, now=NOW, post_form=sender)
    write_status(config.status_directory, "migration", {"last_outcome": "succeeded"})
    failing = Recorder(answer=500)
    run_check(config, now=NOW + timedelta(minutes=5), post_form=failing)
    run_check(config, now=NOW + timedelta(minutes=10), post_form=sender)
    assert len(sender.texts) == 1
    run_check(config, now=NOW + timedelta(hours=1, minutes=5), post_form=sender)
    assert len(sender.texts) == 2 and "FIXED: The last database update" in sender.texts[1]
    checks = read_status(config.status_directory, "checks")
    assert checks is not None and checks["ended_pending"] == {} and checks["alerts"] == {}

    # A warning whose NEW message never reached anyone ends without a FIXED message.
    all_good(config.status_directory, NOW + timedelta(hours=2))
    write_status(config.status_directory, "migration", {"last_outcome": "failed"})
    run_check(config, now=NOW + timedelta(hours=2), post_form=failing)
    write_status(config.status_directory, "migration", {"last_outcome": "succeeded"})
    all_good(config.status_directory, NOW + timedelta(hours=4))
    run_check(config, now=NOW + timedelta(hours=4), post_form=sender)
    assert len(sender.texts) == 2


def test_without_telegram_the_check_finishes_and_the_page_warns(tmp_path: Path) -> None:
    config = load_operations_config(make_config(tmp_path, telegram=False))
    all_good(config.status_directory, NOW)
    codes = [w.code for w in run_check(config, now=NOW, post_form=Recorder())]
    # No database file: the check reports the database as not answering.
    assert codes == ["database_unavailable", "telegram_not_configured"]


def test_no_finding_and_telegram_set_up_shows_nothing(tmp_path: Path, database_ok: None) -> None:
    config = load_operations_config(make_config(tmp_path))
    all_good(config.status_directory, NOW)
    sender = Recorder()
    assert run_check(config, now=NOW, post_form=sender) == []
    assert sender.texts == []
    checks = read_status(config.status_directory, "checks")
    assert checks is not None
    assert checks["telegram"] == {"configured": True}
    assert FAKE_TOKEN not in json.dumps(checks)


def test_low_disk_and_an_unreadable_certificate_are_found(
    tmp_path: Path, database_ok: None
) -> None:
    path = make_config(tmp_path)
    document = json.loads(path.read_text())
    document["alerts"]["disk_minimum_free_gigabytes"] = 10**9
    document["alerts"]["tls_certificate_file"] = str(tmp_path / "missing.pem")
    path.write_text(json.dumps(document))
    config = load_operations_config(path)
    all_good(config.status_directory, NOW)
    codes = [w.code for w in run_check(config, now=NOW, post_form=Recorder())]
    assert codes == ["low_disk_space", "tls_certificate_unreadable"]


def test_record_migration_writes_the_outcome(tmp_path: Path) -> None:
    path = make_config(tmp_path)
    assert (
        main(
            [
                "--config",
                str(path),
                "record-migration",
                "--outcome",
                "failed",
                "--revision",
                "20270204_192",
            ]
        )
        == 0
    )
    record = read_status(tmp_path / "status", "migration")
    assert record is not None
    assert record["last_outcome"] == "failed" and record["revision"] == "20270204_192"
