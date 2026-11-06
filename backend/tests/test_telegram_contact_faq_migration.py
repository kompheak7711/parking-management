"""Contact office and the FAQ (migration 20270524_286, DL-170, bots step 2d part 2).

Owner-approved app screens (round 29): Contact office lists the messages from both bots, Waiting
and Answered; each is answered once, by Reply (the bot sends it) or Answered by phone (a note).
The FAQ keeps every version; a Manager's change waits for the Owner, the Owner's save is used at
once, and the bots show only the newest approved version.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, TelegramDatabase, item, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_tenant_link_migration import LINK, add_lease, share_phone

ADD = "SELECT app.telegram_contact_add(%s, %s, %s, %s, %s, %s, %s, %s, %s)"
PAGE = "SELECT app.telegram_contact_page(%s, %s)"
ANSWER = "SELECT app.telegram_contact_answer(%s, %s, %s, %s, %s)::text"
FAQ_PAGE = "SELECT app.telegram_faq_page(%s, %s)"
SAVE = "SELECT app.telegram_faq_save(%s, %s, %s::jsonb, %s)"
APPROVE = "SELECT app.telegram_faq_approve(%s, %s, %s)"
FOR_BOT = "SELECT app.telegram_faq_for_bot(%s, %s, %s)"


def inbound(db: TelegramDatabase, user: int, relay_id: str, text: str) -> str:
    body = json.loads(item(relay_id, None))
    body.update(telegram_user_id=user, chat_id=user, payload={"message": {"text": text}})
    saved = run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.owner)
    return str(saved["inbound_id"])


def version(**changes: str) -> str:
    body = {
        "for_bots": "BOTH",
        "question_en": "What are your office hours?",
        "answer_en": "Monday to Saturday, 07:00 to 17:00.",
        "question_km": "ការិយាល័យបើកម៉ោងប៉ុន្មាន?",
        "answer_km": "ពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។",
    }
    return json.dumps(body | changes)


def test_contact_office_messages_are_answered_once_by_reply_or_by_phone(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    linked, stranger = 940001, 940002
    add_lease(db, name="Lim Dara", phone="+85512800100", unit_number="801")
    share_phone(db, linked, "+85512800100", "item-contact-phone")
    assert (
        run(db.runtime_url, LINK, db.property_id, linked, "Lim Dara", "801", db.owner)["result"]
        == "LINKED"
    )
    first = inbound(db, linked, "item-contact-1", "The light is weak")
    saved = run(
        db.runtime_url, ADD, db.property_id, first, "TENANT", linked, linked, "en",
        "Dara on Telegram", "  The light is weak  ", db.owner,
    )  # fmt: skip
    assert saved["result"] == "SAVED"
    again = run(
        db.runtime_url, ADD, db.property_id, first, "TENANT", linked, linked, "en",
        None, "The light is weak", db.owner,
    )  # fmt: skip
    assert again == {"result": "REPEATED", "id": saved["id"]}
    second = inbound(db, stranger, "item-contact-2", "I cannot link")
    run(
        db.runtime_url, ADD, db.property_id, second, "TENANT", stranger, stranger, "km",
        "Sok", "I cannot link", db.owner,
    )  # fmt: skip
    # Only the jobs' account saves messages; an empty message is refused.
    refused(
        db.runtime_url, "42501", ADD, db.property_id, second, "TENANT", stranger, stranger,
        "km", None, "x", db.staff,
    )  # fmt: skip
    third = inbound(db, stranger, "item-contact-3", " ")
    refused(
        db.runtime_url, "22023", ADD, db.property_id, third, "TENANT", stranger, stranger,
        "km", None, "   ", db.owner,
    )  # fmt: skip

    # Staff see and answer Contact office (owner-approved rights, round 29).
    page = run(db.runtime_url, PAGE, db.property_id, db.staff)
    assert page["answered"] == []
    assert [(row["name"], row["unit_number"], row["phone"]) for row in page["waiting"]] == [
        ("Lim Dara", "801", "+85512800100"),
        ("Sok", None, None),
    ]
    assert page["waiting"][0]["message"] == "The light is weak"
    run(
        db.runtime_url, ANSWER, db.property_id, saved["id"], "TELEGRAM",
        "We will call you at 10:00.", db.staff,
    )  # fmt: skip
    refused(
        db.runtime_url, "55000", ANSWER, db.property_id, saved["id"], "PHONE", "Again",
        db.staff,
    )  # fmt: skip
    stranger_id = page["waiting"][1]["id"]
    refused(db.runtime_url, "22023", ANSWER, db.property_id, stranger_id, "PHONE", " ", db.staff)
    refused(db.runtime_url, "22023", ANSWER, db.property_id, stranger_id, "EMAIL", "Hi", db.staff)
    run(
        db.runtime_url, ANSWER, db.property_id, stranger_id, "PHONE",
        "Called and explained the link steps.", db.manager,
    )  # fmt: skip
    with psycopg.connect(db.owner_url) as connection:
        sent = connection.execute(
            "SELECT chat_id, text_code, language, details, keyboard FROM app.telegram_outbox "
            "WHERE text_code = 'contact.reply'"
        ).fetchall()
    assert sent == [
        (linked, "contact.reply", "en", {"text": "We will call you at 10:00."}, "tenant.menu")
    ]
    page = run(db.runtime_url, PAGE, db.property_id, db.owner)
    assert page["waiting"] == []
    answers: list[dict[str, Any]] = [row["answer"] for row in page["answered"]]
    assert [(answer["how"], answer["text"]) for answer in answers] == [
        ("PHONE", "Called and explained the link steps."),
        ("TELEGRAM", "We will call you at 10:00."),
    ]
    assert all(answer["by"] for answer in answers)
    # The messages are kept as they are.
    refused(
        db.owner_url, "55000", "UPDATE app.telegram_contact_answers SET answer = 'x' RETURNING 1"
    )


def test_a_managers_faq_change_waits_for_the_owner_and_the_bots_show_only_approved(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    made = run(db.runtime_url, SAVE, db.property_id, None, version(), db.manager)
    assert made["number"] == 1 and made["approved"] is False
    question = made["question_id"]
    assert run(db.runtime_url, FOR_BOT, db.property_id, "TENANT", db.owner) == []
    page = run(db.runtime_url, FAQ_PAGE, db.property_id, db.manager)
    assert page["owner"] is False and page["can_edit"] is True
    entry = page["questions"][0]
    assert entry["current"] is None and entry["pending"]["version_id"] == made["version_id"]
    # Only the Owner approves.
    refused(db.runtime_url, "42501", APPROVE, db.property_id, made["version_id"], db.manager)
    approved = run(db.runtime_url, APPROVE, db.property_id, made["version_id"], db.owner)
    assert approved == {"number": 1, "version_number": 1}
    refused(db.runtime_url, "55000", APPROVE, db.property_id, made["version_id"], db.owner)
    for bot in ("TENANT", "CUSTOMER"):
        shown = run(db.runtime_url, FOR_BOT, db.property_id, bot, db.owner)
        assert [row["question_en"] for row in shown] == ["What are your office hours?"]

    # The Owner's save is used at once.
    owners = run(
        db.runtime_url, SAVE, db.property_id, question,
        version(for_bots="TENANT", answer_en="Monday to Saturday, 07:00 to 17:00. Closed Sunday."),
        db.owner,
    )  # fmt: skip
    assert owners["approved"] is True and owners["number"] == 1
    assert run(db.runtime_url, FOR_BOT, db.property_id, "CUSTOMER", db.owner) == []
    tenant = run(db.runtime_url, FOR_BOT, db.property_id, "TENANT", db.owner)
    assert tenant[0]["answer_en"].endswith("Closed Sunday.")

    # A Manager's change the Owner then overtakes is no longer waiting.
    waiting = run(
        db.runtime_url, SAVE, db.property_id, question, version(answer_km="ថ្មី"), db.manager
    )
    page = run(db.runtime_url, FAQ_PAGE, db.property_id, db.owner)
    assert page["owner"] is True
    assert page["questions"][0]["pending"]["answer_km"] == "ថ្មី"
    assert page["questions"][0]["current"]["version_number"] == 2
    run(db.runtime_url, SAVE, db.property_id, question, version(for_bots="BOTH"), db.owner)
    page = run(db.runtime_url, FAQ_PAGE, db.property_id, db.owner)
    assert page["questions"][0]["pending"] is None
    assert page["questions"][0]["current"]["version_number"] == 3
    refused(db.runtime_url, "55000", APPROVE, db.property_id, waiting["version_id"], db.owner)

    # A hidden question is kept but no bot shows it; numbers follow on.
    hidden = run(
        db.runtime_url, SAVE, db.property_id, None,
        version(for_bots="HIDDEN", question_en="Old question"), db.owner,
    )  # fmt: skip
    assert hidden["number"] == 2
    shown = run(db.runtime_url, FOR_BOT, db.property_id, "TENANT", db.owner)
    assert [row["number"] for row in shown] == [1]

    # Staff see the FAQ (they answer Contact office) but do not edit it.
    staff_page = run(db.runtime_url, FAQ_PAGE, db.property_id, db.staff)
    assert staff_page["can_edit"] is False and len(staff_page["questions"]) == 2
    refused(db.runtime_url, "42501", SAVE, db.property_id, None, version(), db.staff)
    refused(db.runtime_url, "22023", SAVE, db.property_id, None, version(question_km=" "), db.owner)
    refused(db.runtime_url, "22023", SAVE, db.property_id, None, version(for_bots="ALL"), db.owner)
    refused(db.runtime_url, "42501", FOR_BOT, db.property_id, "TENANT", db.staff)
