"""The tenant hears each report step, checks the repair and sees My requests (migration
20270523_285, DL-129, bots step 2d part 1).

Owner-approved tenant mock-up v15: each step of a report the tenant made sends a Telegram message
in the person's language; at Done the tenant taps Fixed (closes it) or Not fixed (opens it again
with the same number); My requests lists the person's reports.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import TelegramDatabase, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_tenant_problem_report_migration import ids, link_tenant, send_form

STEP = "SELECT app.problem_report_step(%s, %s, %s, %s, %s::jsonb, %s, NULL)"
CHECK = "SELECT app.telegram_tenant_report_check(%s, %s, %s, %s)"
MINE = "SELECT app.telegram_tenant_my_reports(%s, %s, %s)"


def step(db: TelegramDatabase, report_id: str, name: str, body: dict[str, Any]) -> None:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT version FROM app.problem_reports WHERE id = %s", (report_id,)
        ).fetchone()
    assert row is not None
    run(db.runtime_url, STEP, db.property_id, report_id, row[0], name, json.dumps(body), db.owner)


def messages_to(db: TelegramDatabase, chat: int) -> list[tuple[str, str, dict[str, Any], str]]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute(
            "SELECT text_code, language, details, keyboard FROM app.telegram_outbox "
            "WHERE bot_code = 'TENANT' AND chat_id = %s AND text_code LIKE 'tenant.step_%%' "
            "ORDER BY created_at, id",
            (chat,),
        ).fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def tomorrow(db: TelegramDatabase) -> str:
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute("SELECT app.gl_today(%s)", (db.property_id,)).fetchone()
    assert row is not None
    today: datetime.date = row[0]
    return (today + datetime.timedelta(days=1)).isoformat()


def unit_form(db: TelegramDatabase, bedroom: uuid.UUID) -> dict[str, Any]:
    return {
        "kind": "UNIT",
        "problem_type_id": ids(db)["AIR_CONDITIONER"],
        "place_item_id": str(bedroom),
        "place_number": 1,
        "description": "The air conditioner drips",
        "urgent": False,
        "may_enter": True,
        "best_time": "ANY",
    }


def test_each_step_of_a_tenant_report_sends_the_tenant_a_message_and_fixed_closes_it(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 930001
    bedroom = link_tenant(db, user, "Lim Dara", "701", "+85512700100")
    run(
        db.runtime_url,
        "SELECT app.telegram_choose_language(%s, 'TENANT', %s, 'en', %s)",
        db.property_id,
        user,
        db.owner,
    )
    added = send_form(db, user, "item-upd-0001", unit_form(db, bedroom))
    report, number = added["report_id"], added["report_number"]
    # The bot answered the form itself: no step message for RECEIVED.
    assert messages_to(db, user) == []
    day = tomorrow(db)
    step(db, report, "PLAN", {"technician": "Sok Khen", "visit_on": day, "visit_at": "09:00"})
    step(db, report, "CHECKED", {"cause": "WEAR"})
    step(db, report, "DECIDE", {"pays": "OWNER"})
    step(db, report, "DONE", {})
    sent = messages_to(db, user)
    assert [row[0] for row in sent] == [
        "tenant.step_planned",
        "tenant.step_checked",
        "tenant.step_owner_pays",
        "tenant.step_done_check",
    ]
    assert all(row[1] == "en" for row in sent)
    planned = sent[0][2]
    assert planned["number"] == number and planned["technician"] == "Sok Khen"
    assert planned["day"] == "/".join(reversed(day.split("-"))) and planned["time"] == "09:00"
    assert sent[3][3] == "tenant.check" and sent[3][2]["days"] == 3
    # Not fixed opens it again with the same number; the bot answers, so no step message.
    again = run(db.runtime_url, CHECK, db.property_id, user, False, db.owner)
    assert again["result"] == "REOPENED" and again["report_number"] == number
    assert len(messages_to(db, user)) == 4
    step(db, report, "DONE", {})
    fixed = run(db.runtime_url, CHECK, db.property_id, user, True, db.owner)
    assert fixed == {"result": "CLOSED", "report_number": number, "technician": "Sok Khen"}
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT status FROM app.problem_reports WHERE id = %s", (report,)
        ).fetchone()
        steps = connection.execute(
            "SELECT step, details ->> 'via' FROM app.problem_report_events "
            "WHERE report_id = %s AND step IN ('FIXED', 'NOT_FIXED') ORDER BY occurred_at",
            (report,),
        ).fetchall()
    assert row == ("CLOSED",)
    assert steps == [("NOT_FIXED", "TELEGRAM"), ("FIXED", "TELEGRAM")]
    nothing = run(db.runtime_url, CHECK, db.property_id, user, True, db.owner)
    assert nothing == {"result": "NOTHING"}
    mine = run(db.runtime_url, MINE, db.property_id, user, db.owner)
    assert mine["result"] == "OK" and mine["unit_number"] == "701"
    assert [(row["report_number"], row["state"]) for row in mine["reports"]] == [(number, "CLOSED")]
    assert mine["reports"][0]["type_en"] == "Air conditioner"


def test_a_phone_report_tells_the_linked_tenant_and_a_joined_report_follows_its_main(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    first, second = 930002, 930003
    bedroom = link_tenant(db, first, "Pich Rotha", "702", "+85512700200")
    # A Building problem joined to another follows the main report's steps.
    kinds = ids(db)
    building = {
        "kind": "BUILDING",
        "problem_type_id": kinds["ELECTRICITY"],
        "problem_place_id": kinds["PLACE_PARKING"],
        "floor": "B1",
        "description": "The light at the stairs is off",
    }
    link_tenant(db, second, "Sum Vanna", "703", "+85512700300")
    main = send_form(db, first, "item-upd-0002", building)
    joined = send_form(
        db, second, "item-upd-0003", building | {"same_as": main["report_id"], "description": None}
    )
    assert joined["joined_to"] == main["report_number"]
    assert messages_to(db, second) == []  # the bot answered "Same problem" itself
    step(db, main["report_id"], "MAKE_JOB", {})
    for chat in (first, second):
        codes = messages_to(db, chat)
        assert [(row[0], row[1], row[2]["number"]) for row in codes] == [
            ("tenant.step_repair_job", "km", main["report_number"])
        ]
    # A report the office takes by phone for the Unit tells the linked tenant it was received.
    with psycopg.connect(db.owner_url) as connection:
        unit = connection.execute(
            "SELECT unit_id FROM app.tenant_telegram_links WHERE telegram_user_id = %s", (first,)
        ).fetchone()
    assert unit is not None
    phoned = str(
        run(
            db.runtime_url,
            "SELECT app.add_problem_report(%s, %s::jsonb, %s, NULL)",
            db.property_id,
            json.dumps(
                {
                    "kind": "UNIT",
                    "unit_id": str(unit[0]),
                    "problem_type_id": kinds["WATER"],
                    "source": "PHONE",
                    "urgent": False,
                    "description": "The tap leaks",
                    "place_item_id": str(bedroom),
                    "place_number": 1,
                }
            ),
            db.owner,
        )
    )
    received = messages_to(db, first)[-1]
    assert received[0] == "tenant.step_received"
    mine = run(db.runtime_url, MINE, db.property_id, first, db.owner)
    with psycopg.connect(db.owner_url) as connection:
        phoned_number = connection.execute(
            "SELECT report_number FROM app.problem_reports WHERE id = %s", (phoned,)
        ).fetchone()
    assert phoned_number is not None and received[2]["number"] == phoned_number[0]
    assert [row["report_number"] for row in mine["reports"]] == [
        phoned_number[0],
        main["report_number"],
    ]
    mine_second = run(db.runtime_url, MINE, db.property_id, second, db.owner)
    assert [
        (row["report_number"], row["state"], row["main_number"]) for row in mine_second["reports"]
    ] == [(joined["report_number"], "JOINED", main["report_number"])]
    assert run(db.runtime_url, MINE, db.property_id, 939999, db.owner) == {"result": "NOT_LINKED"}
    assert run(db.runtime_url, CHECK, db.property_id, 939999, True, db.owner) == {
        "result": "NOT_LINKED"
    }
    refused(db.runtime_url, "42501", MINE, db.property_id, first, db.staff)
    refused(db.runtime_url, "42501", CHECK, db.property_id, first, True, db.staff)
