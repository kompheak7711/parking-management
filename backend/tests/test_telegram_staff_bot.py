"""The Staff bot conversation and forms (step 4a, DL-174), with the database in memory.

Join with Start and the person's own phone, the Reports button for linked staff, check-in and
card scan answers, the card photo kept in the HR files folder (and removed when refused or
old), and the scanned codes kept out of the saved message.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import rsa

from property_rental.telegram_pull_job import run_pull
from property_rental.telegram_staff_bot import (
    handle_staff_form,
    handle_staff_update,
    remove_old_card_photos,
)
from property_rental.telegram_texts import TEXTS, keyboard_markup, render
from test_telegram_jobs import FakeRelay, FakeStore, _client
from test_telegram_jobs import office_key as office_key

USER = 880001
NAME = "យ៉ន់ ដានេ"


def say(store: FakeStore, text: str | None = None, **message: Any) -> list[dict[str, Any]]:
    before = len(store.replies)
    body: dict[str, Any] = {
        "from": {"id": USER, "first_name": "Dane", "last_name": "Yon"},
        "chat": {"id": USER, "type": message.pop("chat_type", "private")},
        **message,
    }
    if text is not None:
        body["text"] = text
    plain = {"telegram_user_id": USER, "chat_id": USER, "payload": {"message": body}}
    handle_staff_update("STAFF", plain, {"saved": True, "inbound_id": "in-1"}, store)
    return store.replies[before:]


def send(
    store: FakeStore, form: dict[str, Any], *, folder: Path | None = None, held: Any = None
) -> list[dict[str, Any]]:
    before = len(store.replies)
    plain = {
        "telegram_user_id": USER,
        "chat_id": USER,
        "payload": {"form": form, "role": "STAFF"},
        "office": {
            "received_at": "2026-11-05T00:35:00+00:00",
            "held_media": held or [],
            "hr_files": str(folder) if folder else "",
        },
    }
    handle_staff_form("STAFF", plain, {"saved": True, "inbound_id": "in-2"}, store)
    return store.replies[before:]


def codes(replies: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(reply["text_code"], reply.get("keyboard")) for reply in replies]


def test_a_new_person_shares_their_phone_and_waits_for_the_answer() -> None:
    store = FakeStore()
    assert codes(say(store, "/start")) == [("staff.ask_phone", "staff.share_phone")]
    # Someone else's contact does not count.
    other = {"user_id": 999, "phone_number": "85512345678"}
    assert codes(say(store, contact=other)) == [("staff.ask_phone", "staff.share_phone")]
    own = {"user_id": USER, "phone_number": "012 345 678"}
    waiting = say(store, contact=own)
    assert codes(waiting) == [("staff.waiting", "remove")]
    assert waiting[0]["language"] == "km"
    assert store.staff_joins == [(USER, "Dane Yon", "+85512345678")]
    assert codes(say(store, "hello")) == [("staff.waiting", "remove")]
    # Only private chats; the shared base answers "ping".
    assert say(store, "/start", chat_type="group") == []
    assert say(store, "ping") == []

    store.staff[USER] = {"name_km": NAME, "roles": ["CLEANER"]}
    hello = say(store, "/start")
    assert codes(hello) == [("staff.hello", "staff.open")]
    assert hello[0]["details"] == {"name": NAME}
    markup = keyboard_markup("staff.open", "km", "relay.example.workers.dev")
    assert markup == {
        "inline_keyboard": [
            [
                {
                    "text": "របាយការណ៍",
                    "web_app": {
                        "url": "https://relay.example.workers.dev/app/staff?form=home&lang=km"
                    },
                }
            ]
        ]
    }


def test_without_the_service_actor_the_bot_says_it_is_not_ready() -> None:
    store = FakeStore()
    store.staff_ready = False
    assert codes(say(store, "/start")) == [("staff.not_ready", "remove")]
    assert codes(send(store, {"type": "CHECK", "mode": "IN", "qr": "x"})) == [
        ("staff.not_ready", None)
    ]


def test_check_in_and_out_answers_with_the_time() -> None:
    store = FakeStore()
    store.staff_answers += [
        {"ok": True, "reply_key": "check_in_ok", "time": "06:35", "place_km": "ប៉ុស្តិ៍យាម"},
        {"ok": True, "reply_key": "check_in_late", "time": "06:52", "late_minutes": 22},
        {"ok": False, "reason": "TOO_EARLY", "reply_key": "check_refused_too_early",
         "starts": "06:30"},
        {"ok": False, "reason": "NEW_RULE", "reply_key": "check_refused_new_rule"},
        {"ok": True, "reply_key": "check_out_ok", "time": "15:31"},
    ]  # fmt: skip
    form = {
        "type": "CHECK",
        "mode": "IN",
        "qr": "CHETANA-P-abc",
        "location": {"status": "OK", "latitude": 11.55, "longitude": 104.92, "extra": "x"},
        "phone_time": "2026-11-05T07:35:00+07:00",
        "anything": "else",
    }
    first = send(store, form)
    assert codes(first) == [("staff.check_in_ok", None)]
    assert first[0]["details"] == {"time": "06:35", "place": "ប៉ុស្តិ៍យាម"}
    kind, user, scan, at = store.staff_scans[0]
    assert (kind, user, at) == ("CHECK", USER, "2026-11-05T00:35:00+00:00")
    # Only what the HR rules read goes on.
    assert scan == {
        "mode": "IN",
        "qr": "CHETANA-P-abc",
        "location": {"status": "OK", "latitude": 11.55, "longitude": 104.92},
        "phone_time": "2026-11-05T07:35:00+07:00",
    }
    assert send(store, form)[0]["details"] == {"time": "06:52", "minutes": 22}
    early = send(store, form | {"location": {"status": "OFF"}})
    assert codes(early) == [("staff.check_refused_too_early", None)]
    assert early[0]["details"] == {"starts": "06:30"}
    assert store.staff_scans[2][2]["location"] == {"status": "OFF"}
    # A refusal the bot has no words for gets the general answer.
    assert codes(send(store, form)) == [("staff.refused_other", None)]
    assert codes(send(store, form | {"mode": "OUT"})) == [("staff.check_out_ok", None)]
    # Every answer renders in Khmer.
    for reply in store.replies:
        assert render(reply["text_code"], "km", reply["details"])


def test_card_scan_keeps_the_photo_in_the_hr_folder(tmp_path: Path) -> None:
    store = FakeStore()
    photo = b"\xff\xd8\xff half-body photo"
    sha = hashlib.sha256(photo).hexdigest()
    held = [{"content_type": "image/jpeg", "sha256": sha, "data": photo}]
    form = {"type": "CARD", "mode": "IN", "card": "CHETANA-E-xyz", "reason": "NO_PHONE"}

    # Without the HR files folder nothing is sent on.
    assert codes(send(store, form, held=held)) == [("staff.card_not_ready", None)]
    assert store.staff_scans == []

    store.staff_answers.append(
        {"ok": True, "direction": "IN", "time": "06:40", "name_km": "គំរូ គ្មានទូរស័ព្ទ"}
    )
    done = send(store, form, folder=tmp_path, held=held)
    assert codes(done) == [("staff.card_in_ok", None)]
    assert done[0]["details"] == {"name": "គំរូ គ្មានទូរស័ព្ទ", "time": "06:40"}
    scan = store.staff_scans[0][2]
    key = f"card-photos/{sha}.jpg"
    assert scan == {
        "mode": "IN",
        "card": "CHETANA-E-xyz",
        "reason": "NO_PHONE",
        "reason_text": "",
        "photo": {"sha256": sha, "byte_size": len(photo), "media_type": "image/jpeg",
                  "storage_key": key},
    }  # fmt: skip
    assert (tmp_path / key).read_bytes() == photo

    # A refused scan keeps no photo; a file kept before is not touched.
    other = b"\xff\xd8\xff another photo"
    other_key = f"card-photos/{hashlib.sha256(other).hexdigest()}.jpg"
    store.staff_answers.append({"ok": False, "reply_key": "check_refused_need_reason"})
    refused = send(
        store,
        form | {"reason": "OTHER"},
        folder=tmp_path,
        held=[{"content_type": "image/jpeg", "sha256": "x", "data": other}],
    )
    assert codes(refused) == [("staff.check_refused_need_reason", None)]
    assert not (tmp_path / other_key).exists()
    store.staff_answers.append({"ok": False, "reply_key": "check_refused_already_in"})
    send(store, form, folder=tmp_path, held=held)
    assert (tmp_path / key).exists()
    # No photo: HR answers that one is needed.
    store.staff_answers.append({"ok": False, "reply_key": "check_refused_need_photo"})
    assert codes(send(store, form, folder=tmp_path)) == [("staff.check_refused_need_photo", None)]
    assert "photo" not in store.staff_scans[-1][2]

    # The HR rule's old photos: the file goes, then the removal is recorded.
    store.photos_due = [
        {"file_id": "f1", "storage_key": key},
        {"file_id": "f2", "storage_key": "../outside.jpg"},
    ]
    assert remove_old_card_photos(store, tmp_path) == 1
    assert not (tmp_path / key).exists()
    assert store.photos_removed == ["f1"]
    assert remove_old_card_photos(store, None) == 0


def test_the_pull_holds_card_photos_and_keeps_codes_out(
    office_key: rsa.RSAPrivateKey, tmp_path: Path
) -> None:
    relay, store = FakeRelay(office_key), FakeStore()
    photo = b"\xff\xd8\xff card photo"
    sha = hashlib.sha256(photo).hexdigest()
    plain = {
        "v": 1,
        "telegram_user_id": USER,
        "chat_id": USER,
        "language_code": "km",
        "payload": {
            "form": {"type": "CARD", "mode": "IN", "card": "CHETANA-E-secret",
                     "reason": "PHONE_BROKEN"},
            "role": "STAFF",
        },
        "media": [{"id": "media-0101", "content_type": "image/jpeg", "sha256": sha,
                   "size": len(photo)}],
    }  # fmt: skip
    relay.add("item-0101", plain, {"media-0101": photo})
    relay.items["item-0101"] |= {"bot": "STAFF", "kind": "form"}
    store.staff_answers.append({"ok": True, "direction": "IN", "time": "06:40", "name_km": NAME})
    media, hr = tmp_path / "media", tmp_path / "hr"
    result = run_pull(
        client=_client(relay), key=office_key, store=store, media_directory=media,
        hr_files_directory=hr,
    )  # fmt: skip
    assert result.saved == 1
    saved = store.items["item-0101"]
    assert saved["media"] == [] and saved["summary"]["held_media"] == 1
    assert "card" not in saved["payload"]["form"]
    assert not media.exists()
    assert (hr / f"card-photos/{sha}.jpg").read_bytes() == photo
    assert store.staff_scans[0][2]["card"] == "CHETANA-E-secret"
    assert codes(store.replies) == [("staff.card_in_ok", None)]


def test_staff_texts_are_khmer_only() -> None:
    for code, texts in TEXTS.items():
        if code.startswith("staff."):
            assert texts["km"] == texts["en"], code


def test_report_a_problem_and_close_job_answer_in_the_chat() -> None:
    store = FakeStore()
    store.staff_answers += [
        {"result": "ADDED", "repeated": False, "report_number": "UP260007", "urgent": False},
        {"result": "ADDED", "repeated": False, "report_number": "BP260003", "urgent": True},
        {"result": "ADDED", "repeated": False, "report_number": "BP260004",
         "joined_to": "BP260003"},
        {"result": "INVALID", "reason": "photo"},
        {"result": "NOT_LINKED"},
        {"result": "ADDED", "repeated": True, "report_number": "UP260007"},
    ]  # fmt: skip
    report = {"type": "REPORT", "kind": "UNIT", "unit_id": "u-1", "description": "Leak"}
    saved = {"saved": True, "inbound_id": "in-9", "media_ids": ["m-1", 2]}

    def report_once() -> list[dict[str, Any]]:
        before = len(store.replies)
        plain = {"telegram_user_id": USER, "chat_id": USER,
                 "payload": {"form": report, "role": "STAFF"}, "office": {}}  # fmt: skip
        handle_staff_form("STAFF", plain, saved, store)
        return store.replies[before:]

    first = report_once()
    assert codes(first) == [("staff.report_saved", None)]
    assert first[0]["details"] == {"number": "UP260007"}
    assert store.staff_scans[0] == ("REPORT", 0, {"form": report, "media": ["m-1", "2"]}, "in-9")
    assert codes(report_once()) == [("staff.report_urgent", None)]
    joined = report_once()
    assert joined[0]["details"] == {"number": "BP260004", "main": "BP260003"}
    assert codes(report_once()) == [("staff.report_invalid", None)]
    assert codes(report_once()) == [("staff.check_refused_not_linked", None)]
    # The same form again (a second pull) is not answered twice.
    assert report_once() == []

    store.staff_answers += [
        {"result": "DONE", "report_number": "UP260007", "cost": "PAID", "total_usd_cents": 1205},
        {"result": "DONE", "report_number": "UP260008", "cost": "NONE"},
        {"result": "NOT_OPEN", "report_number": "UP260007"},
        {"result": "COST_CHECKED", "report_number": "UP260007"},
        {"result": "NOT_TECHNICIAN"},
        {"result": "INVALID", "reason": "receipt"},
    ]
    close = {"type": "CLOSE", "report_id": "r-1", "after_photos": 1, "cost": "PAID"}
    answers = []
    for _ in range(6):
        answers += send(store, close)
    assert [code for code, _ in codes(answers)] == [
        "staff.close_done_cost",
        "staff.close_done",
        "staff.close_not_open",
        "staff.close_cost_checked",
        "staff.close_not_technician",
        "staff.close_invalid",
    ]
    assert answers[0]["details"] == {"number": "UP260007", "amount": "12.05"}
    for reply in store.replies:
        assert render(reply["text_code"], "km", reply["details"])
    # The urgent alert the database queues renders too.
    assert render("staff.urgent", "km", {"number": "BP260003", "type": "សុវត្ថិភាព", "where": "B1"})


def test_utility_reading_and_meter_check_answer_in_the_chat() -> None:
    store = FakeStore()
    store.staff_answers += [
        {"result": "SENT", "repeated": False, "count": 12, "flagged": 0},
        {"result": "SENT", "repeated": False, "count": 12, "flagged": 3},
        {"result": "NOT_METER_READER"},
        {"result": "INVALID", "reason": "value"},
        {"result": "NOT_LINKED"},
        {"result": "SENT", "repeated": True, "count": 12, "flagged": 3},
        {"result": "ADDED", "repeated": False, "report_number": "UP260031"},
        {"result": "INVALID", "reason": "say_what"},
    ]
    meter = {"type": "METER", "readings": [{"unit_id": "u-1", "electricity": 4236}]}
    answers = []
    for _ in range(6):
        answers += send(store, meter)
    assert [code for code, _ in codes(answers)] == [
        "staff.meter_sent",
        "staff.meter_sent_flagged",
        "staff.meter_not_reader",
        "staff.meter_invalid",
        "staff.check_refused_not_linked",
    ]
    assert answers[1]["details"] == {"count": "12", "flagged": "3"}
    assert store.staff_scans[0][0] == "METER" and store.staff_scans[0][2]["media"] == []
    check = {"type": "METER_CHECK", "unit_id": "u-1", "meter": "WATER", "problem": "BROKEN"}
    answers = send(store, check) + send(store, check)
    assert [code for code, _ in codes(answers)] == [
        "staff.meter_check_saved",
        "staff.meter_check_invalid",
    ]
    assert answers[0]["details"] == {"number": "UP260031"}
    for reply in store.replies:
        assert render(reply["text_code"], "km", reply["details"])
    # The database's "read again" message renders too.
    assert render("staff.meter_again", "km", {"units": "A103 ភ្លើង, B105 ទឹក"})


def test_daily_checklists_and_patrol_rounds_answer_in_the_chat() -> None:
    store = FakeStore()
    store.staff_answers += [
        {"result": "SENT", "repeated": False, "again": False, "done": 9, "problems": 0},
        {"result": "SENT", "repeated": False, "again": True, "done": 7, "problems": 2},
        {"result": "NOT_ROLE", "kind": "CLEANING"},
        {"result": "NOT_ROLE", "kind": "TECHNICAL"},
        {"result": "NO_SHIFT"},
        {"result": "NOTHING_DUE"},
        {"result": "INVALID", "reason": "answers"},
        {"result": "SENT", "repeated": True, "done": 9, "problems": 0},
    ]
    checklist = {"type": "CHECKLIST", "code": "CLEAN_BUILDING", "answers": {"d1": "OK"}}
    answers = []
    for _ in range(8):
        answers += send(store, checklist)
    assert [code for code, _ in codes(answers)] == [
        "staff.checklist_sent",
        "staff.checklist_sent_problems",
        "staff.checklist_not_cleaner",
        "staff.checklist_not_technician",
        "staff.checklist_no_shift",
        "staff.checklist_nothing_due",
        "staff.checklist_invalid",
    ]
    assert answers[0]["details"] == {"done": "9", "total": "9"}
    assert answers[1]["details"] == {"done": "7", "total": "9", "problems": "2"}
    assert store.staff_scans[0][0] == "CHECKLIST" and store.staff_scans[0][2]["media"] == []

    store.staff_answers += [
        {"result": "SENT", "repeated": False, "round": "11:30", "at": "11:42"},
        {"result": "ROUND_DONE", "round": "11:30", "at": "11:42"},
        {"result": "TOO_EARLY", "round": "14:00"},
        {"result": "NOT_ROLE", "kind": "CARETAKER"},
        {"result": "INVALID", "reason": "places"},
    ]
    patrol = {"type": "PATROL", "round": "11:30", "places": ["CHETANA", "PARKING"]}
    answers = []
    for _ in range(5):
        answers += send(store, patrol)
    assert [code for code, _ in codes(answers)] == [
        "staff.patrol_sent",
        "staff.patrol_done_before",
        "staff.patrol_too_early",
        "staff.checklist_not_caretaker",
        "staff.patrol_invalid",
    ]
    assert answers[0]["details"] == {"round": "11:30", "at": "11:42"}
    for reply in store.replies:
        assert render(reply["text_code"], "km", reply["details"])
    # The database's 18:00 summary renders too.
    summary = render(
        "staff.daily_summary", "km", {"date": "05/11/2026", "list": "🧹 សម្អាត៖ ផ្ញើ 2/2 នាក់"}
    )
    assert summary.startswith("📋 សង្ខេបប្រចាំថ្ងៃ 05/11/2026\n\n🧹")


def test_unit_checks_and_maintenance_checks_answer_in_the_chat() -> None:
    store = FakeStore()
    store.staff_answers += [
        {"result": "SENT", "repeated": False, "findings": 0, "numbers": []},
        {"result": "SENT", "repeated": False, "findings": 2, "numbers": ["UP000101", "UP000102"]},
        {"result": "NOT_ROLE"},
        {"result": "INVALID", "reason": "findings"},
        {"result": "SENT", "repeated": True, "findings": 0, "numbers": []},
    ]
    unit_check = {"type": "UNIT_CHECK", "unit_id": "u-1", "kind": "REGULAR", "areas": {}}
    answers = []
    for _ in range(5):
        answers += send(store, unit_check)
    assert [code for code, _ in codes(answers)] == [
        "staff.unit_check_good",
        "staff.unit_check_findings",
        "staff.tech_only",
        "staff.unit_check_invalid",
    ]
    assert answers[1]["details"] == {"count": "2", "numbers": "UP000101, UP000102"}
    assert store.staff_scans[0][0] == "UNIT_CHECK"

    store.staff_answers += [
        {"result": "CHECKED", "repeated": False, "report_number": "UP000103", "fixed": False},
        {"result": "CHECKED", "repeated": False, "report_number": "UP000104", "fixed": True},
        {"result": "NOT_PLANNED", "report_number": "UP000103"},
        {"result": "NOT_ROLE"},
        {"result": "INVALID", "reason": "fixed"},
    ]
    maintenance = {"type": "MAINT_CHECK", "report_id": "r-1", "entry": "URGENT", "cause": "WEAR"}
    answers = []
    for _ in range(5):
        answers += send(store, maintenance)
    assert [code for code, _ in codes(answers)] == [
        "staff.maint_checked",
        "staff.maint_fixed",
        "staff.maint_not_planned",
        "staff.tech_only",
        "staff.maint_invalid",
    ]
    assert answers[0]["details"] == {"number": "UP000103"}
    for reply in store.replies:
        assert render(reply["text_code"], "km", reply["details"])
