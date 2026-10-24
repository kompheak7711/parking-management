"""V1-059 Telegram alerts to the Owner and the Manager (DL-071 answer 8; DEPLOY-051, SEC-059)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from property_rental.operations_config import TelegramConfig
from property_rental.telegram_alerts import load_telegram_target, send_alert

# Made-up token of the right shape; never a real one.
FAKE_TOKEN = "123456789:" + "A" * 35


def config(tmp_path: Path, token: str = FAKE_TOKEN, chats: object = None) -> TelegramConfig:
    (tmp_path / "token").write_text(token + "\n", encoding="utf-8")
    (tmp_path / "chats").write_text(
        json.dumps(chats if chats is not None else {"owner": "111", "manager": -222}),
        encoding="utf-8",
    )
    return TelegramConfig(
        api_host="api.telegram.org",
        bot_token_file=tmp_path / "token",
        chat_ids_file=tmp_path / "chats",
        recipients=("owner", "manager"),
    )


def test_a_message_goes_to_the_owner_and_the_manager(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def post(address: str, form: dict[str, str]) -> int:
        calls.append((address, form))
        return 200

    assert send_alert(config(tmp_path), ["Disk space is low."], post_form=post) == "sent"
    assert [form["chat_id"] for _, form in calls] == ["111", "-222"]
    assert all(
        address == f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage" for address, _ in calls
    )
    assert calls[0][1]["text"] == "Disk space is low."


@pytest.mark.parametrize(
    ("token", "chats"),
    [
        ("placeholder-telegram-bot-token", None),
        ("", None),
        (FAKE_TOKEN, {"owner": "replace-me", "manager": "1"}),
        (FAKE_TOKEN, {"owner": "1"}),
        (FAKE_TOKEN, {"owner": True, "manager": "1"}),
        (FAKE_TOKEN, ["1", "2"]),
    ],
)
def test_placeholders_mean_not_set_up_and_nothing_is_sent(
    tmp_path: Path, token: str, chats: object
) -> None:
    def post(address: str, form: dict[str, str]) -> int:
        raise AssertionError("nothing may be sent")

    telegram = config(tmp_path, token, chats)
    assert load_telegram_target(telegram) is None
    assert send_alert(telegram, ["x"], post_form=post) == "not_configured"


def test_missing_files_mean_not_set_up(tmp_path: Path) -> None:
    telegram = TelegramConfig("api.telegram.org", tmp_path / "a", tmp_path / "b", ("owner",))
    assert send_alert(telegram, ["x"]) == "not_configured"


def test_a_network_failure_is_a_failed_delivery_and_shows_no_token(tmp_path: Path) -> None:
    def post(address: str, form: dict[str, str]) -> int:
        if form["chat_id"] == "111":
            raise OSError(f"cannot reach {address}")
        return 200

    assert send_alert(config(tmp_path), ["x"], post_form=post) == "failed"
    assert send_alert(config(tmp_path), ["x"], post_form=lambda a, f: 500) == "failed"
    target = load_telegram_target(config(tmp_path))
    assert target is not None
    assert FAKE_TOKEN not in repr(target)
