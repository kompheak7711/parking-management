"""The Customer bot's Visit requests (migration 20270525_287, DL-171, bots step 3a).

Owner-approved CRM mock-up (customer bot view): an inquiry is saved with how to contact the
person, their own shared phone, the name, the Unit Type, the visit day and part, the move-in
month and a note, and gets a number. A second inquiry from the same person or phone joins the
first one and keeps its place (owner rule 28 Oct 2026, first come, first served).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, TelegramDatabase, item, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_contact_faq_migration import ADD as CONTACT_ADD
from test_telegram_contact_faq_migration import ANSWER as CONTACT_ANSWER

CHOICES = "SELECT app.telegram_customer_choices(%s, %s, %s)"
INQUIRY = "SELECT app.telegram_visit_request_add(%s, %s, %s, %s, %s, %s::jsonb, %s)"
PAGE = "SELECT app.visit_requests_page(%s, %s)"


def inbound(db: TelegramDatabase, user: int, relay_id: str, phone: str | None = None) -> str:
    body = json.loads(item(relay_id, None))
    body.update(
        bot="CUSTOMER",
        telegram_user_id=user,
        chat_id=user,
        account={"language": "en", "phone": phone},
        payload={"message": {"text": "Send an inquiry"}},
    )
    saved = run(db.runtime_url, RECORD, db.property_id, json.dumps(body), db.owner)
    return str(saved["inbound_id"])


def visit_day(today: date) -> date:
    day = today + timedelta(days=2)
    return day + timedelta(days=1) if day.isoweekday() == 7 else day


def request(today: date, **changes: Any) -> str:
    body: dict[str, Any] = {
        "contact_by": "EMAIL",
        "email": "sokha@example.com",
        "name": " Sokha Chan ",
        "unit_type": "TWO_BEDROOM",
        "visit_on": visit_day(today).isoformat(),
        "visit_part": "AFTERNOON",
        "move_in": f"{today + timedelta(days=40):%Y-%m}",
        "note": "A high floor, please.",
    }
    return json.dumps(body | changes)


def test_an_inquiry_is_saved_with_a_number_and_a_repeat_joins_it(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    sokha, other = 950001, 950002
    choices = run(db.runtime_url, CHOICES, db.property_id, sokha, db.owner)
    assert [entry["code"] for entry in choices["unit_types"]] == [
        "STUDIO",
        "ONE_BEDROOM",
        "TWO_BEDROOM",
        "THREE_BEDROOM",
    ]
    assert choices["phone"] is None
    today = date.fromisoformat(choices["today"])
    refused(db.runtime_url, "42501", CHOICES, db.property_id, sokha, db.staff)

    first = inbound(db, sokha, "item-inquiry-1")
    add = (db.runtime_url, INQUIRY, db.property_id, first, sokha, sokha, "en")

    def refuse(state: str, body: str, actor: Any) -> None:
        refused(db.runtime_url, state, *add[1:], body, actor)

    # No phone shared yet: the bot asks for it.
    assert run(*add, request(today), db.owner) == {"result": "NO_PHONE"}
    inbound(db, sokha, "item-inquiry-phone", phone="+85512800200")
    assert run(db.runtime_url, CHOICES, db.property_id, sokha, db.owner)["phone"] == (
        "+85512800200"
    )
    # What the bot sends is checked again here.
    for wrong in (
        request(today, contact_by="FAX"),
        request(today, email="not an email"),
        request(today, name="  "),
        request(today, unit_type="CASTLE"),
        request(today, visit_on=(today + timedelta(days=1)).isoformat()),
        request(today, visit_on=(today + timedelta(days=31)).isoformat()),
        request(today, visit_on="2026-13-01"),
        request(today, visit_part=None),
        request(today, move_in="2020-01"),
        request(today, move_in="soon"),
        request(today, note="x" * 501),
    ):
        refuse("22023", wrong, db.owner)
    sunday = today + timedelta(days=(7 - today.isoweekday()) or 7)
    if sunday < today + timedelta(days=2):
        sunday += timedelta(days=7)
    refuse("22023", request(today, visit_on=sunday.isoformat()), db.owner)
    refuse("42501", request(today), db.staff)

    saved = run(*add, request(today), db.owner)
    year = f"{today:%y}"
    assert saved == {"result": "ADDED", "number": f"VR{year}0001", "main_number": None}
    assert run(*add, request(today), db.owner) == {
        "result": "REPEATED",
        "number": f"VR{year}0001",
        "main_number": None,
    }
    # A Tenant bot message is not an inquiry.
    tenant_item = json.loads(item("item-inquiry-tenant", None))
    tenant_item.update(telegram_user_id=sokha, chat_id=sokha)
    tenant_saved = run(db.runtime_url, RECORD, db.property_id, json.dumps(tenant_item), db.owner)
    refused(
        db.runtime_url, "22023", INQUIRY, db.property_id, tenant_saved["inbound_id"], sokha,
        sokha, "en", request(today), db.owner,
    )  # fmt: skip

    # The same person asks again: the new inquiry joins the first.
    again = inbound(db, sokha, "item-inquiry-2")
    joined = run(
        db.runtime_url, INQUIRY, db.property_id, again, sokha, sokha, "km",
        request(today, contact_by="WHATSAPP", email=None, visit_on=None, visit_part=None,
                move_in="LATER", note=None, unit_type="STUDIO"),
        db.owner,
    )  # fmt: skip
    assert joined == {
        "result": "JOINED",
        "number": f"VR{year}0002",
        "main_number": f"VR{year}0001",
    }
    # Another person: a request of their own.
    third = inbound(db, other, "item-inquiry-3", phone="+85512800300")
    run(
        db.runtime_url, INQUIRY, db.property_id, third, other, other, "en",
        request(today, contact_by="TELEGRAM", email="ignored@example.com", name="Rithy"),
        db.owner,
    )  # fmt: skip

    # Staff see the list (owner rule: the front desk works it), oldest first.
    page = run(db.runtime_url, PAGE, db.property_id, db.staff)
    rows = page["requests"]
    assert [(row["number"], row["name"], row["status"]) for row in rows] == [
        (f"VR{year}0001", "Sokha Chan", "NEW"),
        (f"VR{year}0003", "Rithy", "NEW"),
    ]
    first_row = rows[0]
    assert first_row["phone"] == "+85512800200" and first_row["email"] == "sokha@example.com"
    assert first_row["unit_type_en"] == "2 bedrooms" and first_row["visit_part"] == "AFTERNOON"
    assert first_row["move_in_month"] == f"{today + timedelta(days=40):%Y-%m}"
    assert [kid["number"] for kid in first_row["joined"]] == [f"VR{year}0002"]
    assert first_row["joined"][0]["move_in_month"] is None
    assert rows[1]["email"] is None and rows[1]["joined"] == []
    for actor in (db.owner, db.manager):
        assert len(run(db.runtime_url, PAGE, db.property_id, actor)["requests"]) == 2
    # Requests are kept as they are.
    refused(db.owner_url, "55000", "UPDATE app.visit_requests SET note = 'x' RETURNING 1")
    with psycopg.connect(db.owner_url) as connection:
        rule = connection.execute(
            "SELECT format FROM app.number_rules WHERE document_type = 'VISIT_REQUEST' LIMIT 1"
        ).fetchone()
    assert rule == ("VRyy000n",)


def test_the_offices_reply_to_a_customer_shows_the_customer_menu(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    person = 950010
    message = inbound(db, person, "item-customer-contact", phone="+85512800400")
    saved = run(
        db.runtime_url, CONTACT_ADD, db.property_id, message, "CUSTOMER", person, person, "en",
        "Chenda", "Is there parking?", db.owner,
    )  # fmt: skip
    run(
        db.runtime_url, CONTACT_ANSWER, db.property_id, saved["id"], "TELEGRAM",
        "Yes, there is parking.", db.staff,
    )  # fmt: skip
    with psycopg.connect(db.owner_url) as connection:
        sent = connection.execute(
            "SELECT bot_code, keyboard FROM app.telegram_outbox WHERE chat_id = %s", (person,)
        ).fetchall()
    assert sent == [("CUSTOMER", "customer.menu")]
    page = run(db.runtime_url, "SELECT app.telegram_contact_page(%s, %s)", db.property_id, db.staff)
    shown = [row for row in page["answered"] if row["name"] == "Chenda"]
    assert shown[0]["phone"] == "+85512800400"
