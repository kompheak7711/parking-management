"""The 15 starter FAQ questions (migration 20270625_336, DL-179).

Owner OK of 5 Nov 2026: load the 15 questions of the FAQ draft, ready for the Owner to approve.
They load only into an empty FAQ, each waits for the Owner (even when the Owner loads them), and
no bot shows one until it is approved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import TelegramDatabase, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_contact_faq_migration import APPROVE, FAQ_PAGE, FOR_BOT, SAVE, version

LOAD = "SELECT app.telegram_faq_load_starter(%s, %s)"
REVISION = "20270625_336"


def test_the_starter_questions_load_once_and_wait_for_the_owner(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    # Staff read the FAQ but cannot load it.
    refused(db.runtime_url, "42501", LOAD, db.property_id, db.staff)
    # The Owner loads them, and still each one waits for approval.
    assert run(db.runtime_url, LOAD, db.property_id, db.owner) == {"loaded": 15}
    page = run(db.runtime_url, FAQ_PAGE, db.property_id, db.owner)
    questions = page["questions"]
    assert [question["number"] for question in questions] == list(range(1, 16))
    assert all(question["current"] is None for question in questions)
    pending = [question["pending"] for question in questions]
    assert pending[0]["question_en"] == "Where is CHETANA Residence located?"
    assert pending[14]["question_km"] == "តើអាចទាក់ទងផ្នែកបម្រើអតិថិជនបានទេ?"
    who = [entry["for_bots"] for entry in pending]
    assert who == ["CUSTOMER"] * 5 + ["BOTH"] + ["CUSTOMER"] * 4 + ["BOTH"] + ["TENANT"] * 3 + [
        "BOTH"
    ]
    for bot in ("CUSTOMER", "TENANT"):
        assert run(db.runtime_url, FOR_BOT, db.property_id, bot, db.owner) == []

    # Once approved, a question shows in its bots only.
    run(db.runtime_url, APPROVE, db.property_id, pending[11]["version_id"], db.owner)
    tenant = run(db.runtime_url, FOR_BOT, db.property_id, "TENANT", db.owner)
    assert [row["number"] for row in tenant] == [12]
    assert run(db.runtime_url, FOR_BOT, db.property_id, "CUSTOMER", db.owner) == []

    # Never twice, and not into a FAQ that has questions.
    refused(db.runtime_url, "55000", LOAD, db.property_id, db.owner)
    refused(db.runtime_url, "55000", LOAD, db.property_id, db.manager)
    # The usual save still numbers on after the starter questions.
    made = run(db.runtime_url, SAVE, db.property_id, None, version(), db.manager)
    assert made["number"] == 16 and made["approved"] is False


def test_the_starter_words_fit_the_faq_limits() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270624_335"
    starter = revision.module.STARTER
    assert len(starter) == 15
    for who, question_en, answer_en, question_km, answer_km in starter:
        assert who in {"BOTH", "CUSTOMER", "TENANT"}
        assert 1 <= len(question_en) <= 160 and 1 <= len(question_km) <= 160
        assert 1 <= len(answer_en) <= 800 and 1 <= len(answer_km) <= 800
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
