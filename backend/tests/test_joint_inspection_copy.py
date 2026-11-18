"""The Joint Inspection copy (DL-243 answer 6, DL-244): the PDF page, the Tenant bot sending it,
and the print page.

The page shows each room and item with its result, note and tags, the keys, the meters and both
signatures, in Khmer and English. The send job sends a copy message as the PDF with the text as
its caption; a copy that cannot be made waits and is tried again, never sent as text only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from property_rental import joint_inspection_pdf, joint_inspections_api
from property_rental.joint_inspection_pdf import file_name, joint_inspection_html
from property_rental.telegram_send_job import (
    InspectionDocument,
    InspectionFilesMissing,
    inspection_document,
    run_send,
)
from property_rental.telegram_texts import render
from test_joint_inspections_api import HEADERS, READ, RECORD, InMemoryInspections, base, client
from test_telegram_jobs import TOKEN, FakeStore

TENANT_FILE = "11111111-1111-4111-8111-111111111111"
STAFF_FILE = "22222222-2222-4222-8222-222222222222"


def done_inspection(**changes: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "inspection_id": str(uuid4()),
        "inspection_number": "JI260007",
        "kind": "MOVE_OUT",
        "status": "DONE",
        "inspection_date": "2026-11-16",
        "unit_number": "U203",
        "lease_number": "U203L0026",
        "tenant_name": "Sok Dara",
        "keys": {
            "door_keys": 2,
            "key_cards": 1,
            "mailbox_keys": 1,
            "other_keys": 1,
            "other_keys_note": "Gate remote <b>",
        },
        "meters": [
            {
                "utility_type": "ELECTRICITY",
                "serial_number": "EDC-44821",
                "measurement_unit_code": "kWh",
                "reading": "10452.5",
            }
        ],
        "lines": [
            {
                "ordinal": 2,
                "line_kind": "ITEM",
                "group_en": "Living room",
                "group_km": "បន្ទប់ទទួលភ្ញៀវ",
                "item_name": "TV remote",
                "item_name_km": "តេឡេបញ្ជា",
                "quantity": 1,
                "result": "MISSING",
                "note": "Not found",
                "tenant_caused": True,
                "pet_caused": False,
                "move_in_result": "GOOD",
                "problem_report": {"report_id": str(uuid4()), "report_number": "UP260012"},
                "photos": [{"file_id": str(uuid4())}, {"file_id": str(uuid4())}],
            },
            {
                "ordinal": 1,
                "line_kind": "PLACE",
                "group_en": "Living room",
                "group_km": "បន្ទប់ទទួលភ្ញៀវ",
                "result": "GOOD",
                "move_in_result": "GOOD",
                "photos": [],
            },
            {
                "ordinal": 3,
                "line_kind": "ITEM",
                "group_en": "Bedroom 1",
                "item_name": "Curtain",
                "quantity": 2,
                "result": "GOOD",
                "move_in_result": "GOOD",
                "photos": [],
            },
        ],
        "signatures": {
            "tenant": {"file_id": TENANT_FILE, "signed_at": "2026-11-16T09:40:00Z"},
            "staff": {
                "file_id": STAFF_FILE,
                "signed_at": "2026-11-16T09:42:00Z",
                "name": "Son Sokhen",
            },
        },
        "done_at": "2026-11-16T09:43:00Z",
        "done_by": "Son Sokhen",
        "replaces": None,
        "replaced_by": None,
    }
    return found | changes


def test_the_copy_shows_rooms_results_keys_meters_and_both_signatures() -> None:
    page = joint_inspection_html(
        done_inspection(), tenant_signature=b"tenant-png", staff_signature=b"staff-png"
    )
    assert "JI260007" in page and "Joint Inspection" in page and "ការត្រួតពិនិត្យរួម" in page
    assert "Sok Dara" in page and "Parking U203" in page and "Lease U203L0026" in page
    # The lines in their order, under their room, a new room each time it changes.
    assert page.index("The room itself") < page.index("TV remote") < page.index("Bedroom 1")
    assert "Missing" in page and "បាត់" in page and "Not found" in page
    assert "Tenant caused" in page and "Problem report UP260012" in page
    assert "2 photos in the app" in page and "Curtain \u00d7 2" in page
    # At move-out the move-in result is named only where it matters.
    assert page.count("At move-in") == 1
    assert "Door keys" in page and "Gate remote &lt;b&gt;" in page
    assert "Electricity meter" in page and "10452.5 kWh" in page and "EDC-44821" in page
    for picture in (b"tenant-png", b"staff-png"):
        import base64

        assert base64.b64encode(picture).decode() in page
    assert "Son Sokhen" in page and "Not signed" not in page
    assert file_name(done_inspection()) == "JI260007.pdf"


def test_a_missing_signature_and_a_replacement_are_said_plainly() -> None:
    page = joint_inspection_html(
        done_inspection(
            kind="MOVE_IN",
            replaces={"inspection_id": str(uuid4()), "inspection_number": "JI260003"},
            replace_reason="Wrong meter number",
        ),
        tenant_signature=None,
        staff_signature=b"staff-png",
    )
    assert "Not signed" in page
    assert "replaces JI260003" in page and "Wrong meter number" in page
    assert "At move-in" not in page, "a move-in copy has nothing to compare with"
    assert file_name({"inspection_number": "../JI 1"}) == "JI1.pdf"


def test_the_caption_names_the_inspection_in_the_persons_language() -> None:
    details = {"number": "JI260007", "unit": "U203", "kind": "move-out", "date": "16/11/2026"}
    text = render("tenant.joint_inspection", "en", details)
    assert text.startswith("📋 Joint Inspection JI260007\nU203 · move-out · 16/11/2026")
    assert "Please keep it." in text
    assert "ការត្រួតពិនិត្យរួម JI260007" in render("tenant.joint_inspection", "km", details)


def copy_message(message_id: str = "j1") -> dict[str, Any]:
    return {
        "id": message_id,
        "bot": "TENANT",
        "chat_id": 777,
        "text_code": "tenant.joint_inspection",
        "language": "en",
        "details": {"number": "JI260007", "unit": "U203", "kind": "move-out", "date": "16/11/2026"},
        "buttons": None,
        "keyboard": None,
    }


def test_a_copy_goes_as_the_pdf_and_waits_when_it_cannot_be_made() -> None:
    store = FakeStore()
    store.due = [copy_message()]
    documents: list[tuple[str, dict[str, str], tuple[str, bytes]]] = []
    lines: list[str] = []

    def post_document(
        address: str, fields: dict[str, str], document: tuple[str, bytes]
    ) -> tuple[int, bytes]:
        documents.append((address, fields, document))
        return 200, json.dumps({"ok": True, "result": {"message_id": 90}}).encode()

    def post_json(address: str, body: dict[str, Any]) -> tuple[int, bytes]:
        raise AssertionError("a copy never goes as text only")

    def missing(outbox_id: str) -> InspectionDocument | None:
        raise InspectionFilesMissing("inspection_files_not_set")

    def broken(outbox_id: str) -> InspectionDocument | None:
        raise OSError("pango missing")

    for make, code in ((missing, "inspection_files_not_set"), (broken, "inspection_pdf_failed")):
        result = run_send(
            store=store,
            api_host="api.telegram.org",
            tokens={"TENANT": TOKEN},
            post_json=post_json,
            inspection_documents=make,
            post_document=post_document,
            log=lines.append,
        )
        assert result.failed == 1 and result.sent == 0
        assert store.attempts[-1] == ("j1", "FAILED", code, None)
    assert not any("pango missing" in line for line in lines)

    result = run_send(
        store=store,
        api_host="api.telegram.org",
        tokens={"TENANT": TOKEN},
        post_json=post_json,
        inspection_documents=lambda _: InspectionDocument(b"%PDF-1.7 copy", "JI260007.pdf"),
        post_document=post_document,
    )
    assert result.sent == 1
    address, fields, document = documents[0]
    assert address == f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    assert fields["caption"].startswith("📋 Joint Inspection JI260007")
    assert document == ("JI260007.pdf", b"%PDF-1.7 copy")
    assert store.attempts[-1] == ("j1", "SENT", None, 90)


class Folder:
    def __init__(self) -> None:
        self.read_keys: list[str] = []

    def read(self, key: str, sha256: str) -> bytes:
        self.read_keys.append(key)
        return key.encode()


def test_the_copy_reads_both_signatures_and_waits_without_the_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.joint_inspections["j1"] = {
        "inspection": done_inspection(),
        "files": {
            TENANT_FILE: {"storage_key": "inspections/a/tenant.png", "sha256": "t"},
            STAFF_FILE: {"storage_key": "inspections/a/staff.png", "sha256": "s"},
        },
    }
    made: list[tuple[bytes | None, bytes | None]] = []

    def fake_pdf(
        inspection: dict[str, Any], *, tenant_signature: bytes | None, staff_signature: bytes | None
    ) -> bytes:
        made.append((tenant_signature, staff_signature))
        return b"%PDF-1.7 copy"

    monkeypatch.setattr("property_rental.telegram_send_job.joint_inspection_pdf", fake_pdf)
    assert inspection_document("other", store=store, files=Folder()) is None
    with pytest.raises(InspectionFilesMissing):
        inspection_document("j1", store=store, files=None)
    folder = Folder()
    document = inspection_document("j1", store=store, files=folder)
    assert document == InspectionDocument(b"%PDF-1.7 copy", "JI260007.pdf")
    assert made == [(b"inspections/a/tenant.png", b"inspections/a/staff.png")]


def test_staff_print_the_same_copy_once_the_inspection_is_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = InMemoryInspections()
    url = f"{base(flow)}/joint-inspections/{flow.inspection_id}/pdf"
    made: list[tuple[str, bytes | None, bytes | None]] = []

    def fake_pdf(
        inspection: dict[str, Any], *, tenant_signature: bytes | None, staff_signature: bytes | None
    ) -> bytes:
        made.append((str(inspection["status"]), tenant_signature, staff_signature))
        return b"%PDF-1.7 print"

    monkeypatch.setattr(joint_inspections_api, "joint_inspection_pdf", fake_pdf)
    assert client(flow).get(url).status_code == 403
    reader = client(flow, READ, files=tmp_path)
    draft = reader.get(url)
    assert draft.status_code == 409 and draft.json()["error"]["code"] == "CONFLICT"

    # The tenant's signature is kept; the staff one is not (an older inspection may lack one).
    picture = b"\x89PNG\r\n\x1a\nsignature"
    added = client(flow, READ, RECORD, files=tmp_path).post(
        f"{base(flow)}/joint-inspections/{flow.inspection_id}/files?role=TENANT_SIGNATURE",
        content=picture,
        headers=HEADERS | {"If-Match": '"1"', "Content-Type": "image/png"},
    )
    assert added.status_code == 201
    tenant_file: UUID = next(iter(flow.files))
    assert flow.files[tenant_file]["sha256"] == hashlib.sha256(picture).hexdigest()
    flow.status = "DONE"
    original = flow._inspection

    def with_signature() -> dict[str, object]:
        return original() | {"signatures": {"tenant": {"file_id": str(tenant_file)}, "staff": None}}

    monkeypatch.setattr(flow, "_inspection", with_signature)
    printed = reader.get(url)
    assert printed.status_code == 200 and printed.content == b"%PDF-1.7 print"
    assert printed.headers["Content-Type"] == "application/pdf"
    assert printed.headers["Content-Disposition"] == 'inline; filename="JI260001.pdf"'
    assert printed.headers["Cache-Control"] == "private, no-store"
    assert made == [("DONE", picture, None)]
    assert joint_inspection_pdf.file_name({"inspection_number": "JI260001"}) == "JI260001.pdf"
