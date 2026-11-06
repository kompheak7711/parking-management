"""Tenant bot Problem reports on the real database (migration 20270521_283, DL-127, step 2b).

Owner rules (3 Nov 2026, tenant mock-up v15): a linked tenant sends a Unit Problem or a Building
problem from one form; text or a voice note (or both) is needed, up to 5 photos; safety, flooding
and electric shock are always urgent; "Same problem" joins an open Building problem; the report
goes into the one Problem reports list with source TENANT_BOT.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url
from test_telegram_base_migration import RECORD, TelegramDatabase, item, refused, run
from test_telegram_base_migration import telegram_database as telegram_database
from test_telegram_tenant_link_migration import LINK, add_lease, share_phone

FORM = "SELECT app.telegram_tenant_problem_report(%s, %s, %s::jsonb, %s::jsonb, %s)"
FORM_DATA = "SELECT app.telegram_tenant_form_data(%s, %s)"


def link_tenant(db: TelegramDatabase, user: int, name: str, unit: str, phone: str) -> uuid.UUID:
    lease_id, _ = add_lease(db, name=name, phone=phone, unit_number=unit)
    share_phone(db, user, phone, f"item-pr-link-{user}")
    linked = run(db.runtime_url, LINK, db.property_id, user, name, unit, db.owner)
    assert linked["result"] == "LINKED"
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT unit_id FROM app.leases WHERE id = %s", (lease_id,)
        ).fetchone()
        assert row is not None
        bedroom = connection.execute(
            "SELECT id FROM app.unit_setup_items WHERE property_id = %s "
            "AND list_kind = 'UNIT_FEATURE' AND code = 'BEDROOM'",
            (db.property_id,),
        ).fetchone()
        assert bedroom is not None
        connection.execute(
            "INSERT INTO app.unit_features (unit_id, item_id, feature_count) VALUES (%s, %s, 2)",
            (row[0], bedroom[0]),
        )
    return uuid.UUID(str(bedroom[0]))


def ids(db: TelegramDatabase) -> dict[str, str]:
    with psycopg.connect(db.owner_url) as connection:
        rows = connection.execute("SELECT code, id FROM app.problem_types").fetchall()
        places = connection.execute("SELECT 'PLACE_' || code, id FROM app.problem_places")
        return {code: str(value) for code, value in [*rows, *places.fetchall()]}


def file(name: str, content_type: str, duration: int | None = None) -> dict[str, Any]:
    sha = hashlib.sha256(name.encode()).hexdigest()
    return {
        "sha256": sha,
        "content_type": content_type,
        "size_bytes": 2048,
        "storage_path": f"{sha[:2]}/{sha}",
        "duration_seconds": duration,
    }


def send_form(
    db: TelegramDatabase,
    user: int,
    relay_id: str,
    form: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = item(
        relay_id,
        None,
        kind="form",
        telegram_user_id=user,
        chat_id=user,
        summary={"kind": "form", "media": len(files or [])},
        payload={"form": form, "role": "TENANT"},
        media=files or [],
    )
    saved = run(db.runtime_url, RECORD, db.property_id, body, db.owner)
    answer = run(
        db.runtime_url,
        FORM,
        db.property_id,
        saved["inbound_id"],
        json.dumps(form),
        json.dumps(saved.get("media_ids", [])),
        db.owner,
    )
    assert isinstance(answer, dict)
    answer["inbound_id"] = saved["inbound_id"]
    answer["media_ids"] = saved.get("media_ids", [])
    return answer


def test_a_unit_problem_with_photos_and_a_voice_note_is_saved_once(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 910001
    bedroom = link_tenant(db, user, "Chan Sok", "501", "+85512100200")
    kinds = ids(db)
    form = {
        "kind": "UNIT",
        "problem_type_id": kinds["AIR_CONDITIONER"],
        "place_item_id": str(bedroom),
        "place_number": 2,
        "description": "  The air conditioner is not cold  ",
        "urgent": False,
        "may_enter": True,
        "best_time": "AM",
    }
    files = [file("pr-photo-1", "image/jpeg"), file("pr-voice-1", "audio/webm", 20)]
    added = send_form(db, user, "item-pr-unit-0001", form, files)
    assert added["result"] == "ADDED" and added["repeated"] is False
    assert added["report_number"].startswith("UP") and added["urgent"] is False
    assert added["urgent_hours"] == 1 and added["plan_workdays"] == 1
    report = run(
        db.runtime_url,
        "SELECT app.problem_report_read(%s, %s, %s)",
        db.property_id,
        added["report_id"],
        db.owner,
    )
    assert report["report_number"] == added["report_number"]
    with psycopg.connect(db.owner_url) as connection:
        saved = connection.execute(
            "SELECT source, description, best_time, may_enter, place_number, reported_by "
            "FROM app.problem_reports WHERE id = %s",
            (added["report_id"],),
        ).fetchone()
        media = connection.execute(
            "SELECT kind, position FROM app.problem_report_media WHERE report_id = %s "
            "ORDER BY position",
            (added["report_id"],),
        ).fetchall()
    assert saved == (
        "TENANT_BOT",
        "The air conditioner is not cold",
        "AM",
        True,
        2,
        "Chan Sok, Unit 501",
    )
    assert media == [("PHOTO", 1), ("VOICE", 2)]
    refused(db.owner_url, "55000", "DELETE FROM app.problem_report_media RETURNING 1")
    # The same form again gives the same report.
    again = run(
        db.runtime_url,
        FORM,
        db.property_id,
        added["inbound_id"],
        json.dumps(form),
        json.dumps(added["media_ids"]),
        db.owner,
    )
    assert again["repeated"] is True and again["report_number"] == added["report_number"]


def test_safety_and_danger_are_always_urgent_and_a_voice_note_alone_is_enough(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 910002
    link_tenant(db, user, "Lim Bopha", "502", "+85512100300")
    kinds = ids(db)
    safety = send_form(
        db,
        user,
        "item-pr-unit-0002",
        {
            "kind": "UNIT",
            "problem_type_id": kinds["SAFETY"],
            "description": "Smell of gas",
            "urgent": False,
            "may_enter": False,
        },
    )
    assert safety["result"] == "ADDED" and safety["urgent"] is True
    flood = send_form(
        db,
        user,
        "item-pr-unit-0003",
        {"kind": "UNIT", "problem_type_id": kinds["WATER"], "danger": True, "may_enter": True},
        [file("pr-voice-2", "audio/ogg", 30)],
    )
    assert flood["result"] == "ADDED" and flood["urgent"] is True
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT description, always_urgent FROM app.problem_reports WHERE id = %s",
            (flood["report_id"],),
        ).fetchone()
    assert row == ("Voice note only", False)


def test_a_form_that_is_not_complete_or_not_from_a_linked_tenant_is_refused(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 910003
    link_tenant(db, user, "Keo Rith", "503", "+85512100400")
    kinds = ids(db)
    unit = {"kind": "UNIT", "problem_type_id": kinds["WINDOW"], "urgent": False, "may_enter": True}
    cases: list[tuple[dict[str, Any], list[dict[str, Any]], str]] = [
        (unit, [], "say_what"),
        (unit | {"description": "x" * 1001}, [], "description"),
        (unit | {"description": "Broken", "urgent": None}, [], "urgent"),
        (unit | {"description": "Broken", "best_time": "NIGHT"}, [], "best_time"),
        (
            unit | {"description": "Broken", "place_item_id": str(uuid.uuid4()), "place_number": 1},
            [],
            "place",
        ),
        (unit | {"description": "Broken", "problem_type_id": "nope"}, [], "not_a_form"),
        (
            unit | {"description": "Broken"},
            [file("pr-voice-3", "audio/ogg", 10), file("pr-voice-4", "audio/ogg", 10)],
            "files",
        ),
        (unit | {"description": "Broken"}, [file("pr-voice-5", "audio/ogg", 75)], "files"),
        (
            {"kind": "BUILDING", "problem_type_id": kinds["NOISE"], "description": "Loud"},
            [],
            "place",
        ),
        ({"kind": "ROOF", "problem_type_id": kinds["NOISE"]}, [], "kind"),
    ]
    for number, (form, files, reason) in enumerate(cases):
        answer = send_form(db, user, f"item-pr-bad-{number:04d}", form, files)
        assert answer["result"] == "INVALID" and answer["reason"] == reason, (form, answer)
    stranger = send_form(db, 910099, "item-pr-stranger-01", unit | {"description": "Broken"})
    assert stranger["result"] == "NOT_LINKED"


def test_a_building_problem_can_join_the_open_report_at_the_same_place(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    first_user, second_user = 910004, 910005
    link_tenant(db, first_user, "Heng Mony", "504", "+85512100500")
    link_tenant(db, second_user, "Ouk Sina", "505", "+85512100600")
    kinds = ids(db)
    building = {
        "kind": "BUILDING",
        "problem_type_id": kinds["ELECTRICITY"],
        "problem_place_id": kinds["PLACE_PARKING"],
        "floor": "G",
        "description": "Two lights off near the gate",
    }
    first = send_form(db, first_user, "item-pr-bp-0001", building)
    assert first["result"] == "ADDED" and first["report_number"].startswith("BP")
    assert first["joined_to"] is None and first["urgent"] is False
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.owner)
    open_here = [
        row for row in data["choices"]["open_building"] if row["report_id"] == first["report_id"]
    ]
    assert open_here == [
        {
            "report_id": first["report_id"],
            "report_number": first["report_number"],
            "problem_place_id": kinds["PLACE_PARKING"],
            "problem_type_id": kinds["ELECTRICITY"],
            "floor": "G",
        }
    ]
    same = send_form(
        db,
        second_user,
        "item-pr-bp-0002",
        building | {"same_as": first["report_id"], "description": None},
    )
    assert same["result"] == "ADDED" and same["joined_to"] == first["report_number"]
    with psycopg.connect(db.owner_url) as connection:
        row = connection.execute(
            "SELECT description, status FROM app.problem_reports WHERE id = %s",
            (same["report_id"],),
        ).fetchone()
    assert row == (f"Same problem as {first['report_number']}", "JOINED")
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.owner)
    numbers = [row["report_number"] for row in data["choices"]["open_building"]]
    assert first["report_number"] in numbers and same["report_number"] not in numbers
    # "Same problem" with a report at another place is refused as a wrong place.
    elsewhere = send_form(
        db,
        second_user,
        "item-pr-bp-0003",
        building | {"problem_place_id": kinds["PLACE_LIFT"], "same_as": first["report_id"]},
    )
    assert elsewhere["result"] == "ADDED" and elsewhere["joined_to"] is None


def test_the_form_data_has_places_but_no_names_and_stays_behind_the_functions(
    telegram_database: TelegramDatabase,
) -> None:
    db = telegram_database
    user = 910006
    link_tenant(db, user, "Pich Vanna", "506", "+85512100700")
    data = run(db.runtime_url, FORM_DATA, db.property_id, db.owner)
    assert len(data["choices"]["types"]) == 12 and len(data["choices"]["places"]) == 9
    mine = [row for row in data["users"] if row["id"] == user]
    assert mine and mine[0]["role"] == "TENANT"
    assert [place["number"] for place in mine[0]["data"]["places"]] == [1, 2]
    text = json.dumps(data)
    assert "Pich Vanna" not in text and "+855" not in text
    refused(db.runtime_url, "42501", FORM_DATA, db.property_id, db.staff)
    for table in ("problem_report_media", "tenant_problem_report_sources"):
        refused(db.runtime_url, "42501", f"SELECT count(*) FROM app.{table}")
