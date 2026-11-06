"""Employees and payroll API (HRIS phase 6).

Each route checks its right before calling the database; a change also needs the browser
mutation checks, and an employee step needs If-Match. Database refusals map to 403, 404, 409,
412 and 422. Documents are saved on disk with their SHA-256 and removed again if the database
refuses them; a download checks the SHA-256 first.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.hr_api import FUNCTIONS
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import (
    ProductConflict,
    ProductForbidden,
    ProductNotFound,
    ProductRefused,
    ProductStale,
)
from property_rental.settings import Settings

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=hr-token",
    "X-CSRF-Token": "hr-token",
}


@dataclass
class InMemoryHr:
    property_id: UUID = field(default_factory=uuid4)
    employee_id: UUID = field(default_factory=uuid4)
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    refuse: Exception | None = None
    file: dict[str, object] = field(default_factory=dict)

    def call(self, function: str, parameters: tuple[object, ...]) -> object:
        assert FUNCTIONS[function] == len(parameters)
        if parameters[0] != self.property_id:
            raise ProductNotFound("the Property does not exist")
        self.calls.append((function, parameters))
        if self.refuse is not None and not function.endswith(("_read", "_day", "_week")):
            raise self.refuse
        if function in ("hr_employee_document_file", "hr_scan_photo_file"):
            return self.file
        if function in ("hr_new_place_qr", "hr_new_card_qr"):
            return "CHETANA-P-sample"
        if function.startswith(("hr_add", "hr_make", "hr_pay", "hr_reverse")) and not (
            function.endswith("_read")
        ):
            return str(self.employee_id)
        return {"function": function}

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def client(flow: InMemoryHr, *capabilities: str, files: Path | None = None) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    settings = Settings(_env_file=None, hr_files_directory=None if files is None else str(files))
    return TestClient(create_app(settings=settings, actor_resolver=lambda _: who, hr_flow=flow))


def base(flow: InMemoryHr) -> str:
    return f"/api/v1/properties/{flow.property_id}/hr"


READS = (
    ("/employees", "hr.employees.read", "hr_employees_read"),
    ("/choices", "hr.employees.read", "hr_choices"),
    ("/employees/{employee}", "hr.employees.read", "hr_employee_read"),
    ("/staff-requests", "hr.employees.read", "hr_staff_requests_read"),
    ("/loans", "hr.salaries.read", "hr_loans_read"),
    ("/payrolls", "hr.salaries.read", "hr_payrolls_read"),
    ("/payrolls/{employee}", "hr.salaries.read", "hr_payroll_read"),
    ("/attendance/day?day=2026-11-03", "hr.attendance.read", "hr_attendance_day"),
    ("/attendance/week", "hr.attendance.read", "hr_attendance_week"),
    ("/attendance/month?month=2026-10-01", "hr.attendance.read", "hr_attendance_month"),
    ("/overtime", "hr.attendance.read", "hr_overtime_read"),
    ("/attendance/places", "hr.attendance.read", "hr_attendance_places"),
)


@pytest.mark.parametrize(("path", "right", "function"), READS)
def test_each_read_needs_its_right(path: str, right: str, function: str) -> None:
    flow = InMemoryHr()
    url = base(flow) + path.format(employee=flow.employee_id)
    assert client(flow, "hr.employees.manage").get(url).status_code == 403
    answer = client(flow, right).get(url)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"] == {"function": function}


def test_salary_steps_need_manage_salaries_and_if_match() -> None:
    flow = InMemoryHr()
    url = f"{base(flow)}/employees/{flow.employee_id}/steps"
    pay = {"step": "PAY", "monthly_salary_usd_cents": 22500, "payment_method": "CASH_USD"}
    manager = client(flow, "hr.employees.manage", "hr.employees.read")
    assert manager.post(url, json=pay, headers=HEADERS | {"If-Match": '"1"'}).status_code == 403
    owner = client(flow, "hr.employees.manage", "hr.employees.read", "hr.salaries.manage")
    assert owner.post(url, json=pay, headers=HEADERS).status_code == 428
    assert owner.post(url, json=pay).status_code == 403
    done = owner.post(url, json=pay | {"reason": "Raise"}, headers=HEADERS | {"If-Match": '"3"'})
    assert done.status_code == 200
    step = next(item for name, item in flow.calls if name == "hr_employee_step")
    assert step[2:5] == (
        3,
        "PAY",
        {
            "reason": "Raise",
            "monthly_salary_usd_cents": 22500,
            "payment_method": "CASH_USD",
        },
    )
    leave = manager.post(
        url,
        json={"step": "LEAVE", "effective_date": "2026-11-30", "reason": "Moving away"},
        headers=HEADERS | {"If-Match": "4"},
    )
    assert leave.status_code == 200
    assert (
        manager.post(url, json={"step": "SALARY"}, headers=HEADERS | {"If-Match": "4"}).status_code
        == 422
    )


def test_new_employee_with_pay_needs_manage_salaries(tmp_path: Path) -> None:
    flow = InMemoryHr()
    photo = b"\xff\xd8\xff sample ID card"
    form = {
        "name_en": "Sample Person",
        "name_km": "គំរូ",
        "job_title_id": str(uuid4()),
        "usual_day_off": 7,
        "start_date": "2026-11-01",
        "identity": {
            "id_type": "NATIONAL_ID",
            "id_number": "010101010",
            "date_of_birth": "1995-04-14",
            "home_address": "Sample street, Phnom Penh",
            "place_of_birth": "Kandal",
        },
        "id_photo": {
            "file_name": "id-card.jpg",
            "media_type": "image/jpeg",
            "content_base64": base64.b64encode(photo).decode(),
        },
    }
    manager = client(flow, "hr.employees.manage", files=tmp_path)
    made = manager.post(f"{base(flow)}/employees", json=form, headers=HEADERS)
    assert made.status_code == 201
    assert flow.names() == ["hr_add_employee", "hr_employee_read"]
    # The Manager sends the ID details and photo; the database gets the saved file's record.
    sent = flow.calls[0][1][1]
    assert isinstance(sent, dict)
    document: dict[str, Any] = sent["id_document"]
    assert "id_photo" not in sent and sent["identity"]["id_type"] == "NATIONAL_ID"
    assert document["sha256"] == hashlib.sha256(photo).hexdigest()
    assert (tmp_path / document["storage_key"]).read_bytes() == photo
    with_pay = form | {"pay": {"monthly_salary_usd_cents": 20000, "payment_method": "CASH_USD"}}
    assert manager.post(f"{base(flow)}/employees", json=with_pay, headers=HEADERS).status_code == (
        403
    )
    # Without the ID details or the photo the form is refused before the database.
    for missing in ("identity", "id_photo"):
        short = {key: value for key, value in form.items() if key != missing}
        assert manager.post(f"{base(flow)}/employees", json=short, headers=HEADERS).status_code == (
            422
        )
    bad_photo = {"file_name": "id.jpg", "media_type": "image/jpeg", "content_base64": "no!"}
    broken = form | {"id_photo": bad_photo}
    assert manager.post(f"{base(flow)}/employees", json=broken, headers=HEADERS).status_code == 422
    # A refused employee leaves no file behind.
    flow.refuse = ProductRefused("An employee is at least 15 years old on the start date")
    assert manager.post(f"{base(flow)}/employees", json=form, headers=HEADERS).status_code == 422
    assert len(list((tmp_path / "hr" / "documents").rglob("*.jpg"))) == 1


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (ProductForbidden("Nobody approves their own request"), 403),
        (ProductNotFound("The loan was not found"), 404),
        (ProductConflict("The loan is already decided"), 409),
        (ProductStale("changed"), 412),
        (ProductRefused("Say why it is refused"), 422),
    ],
)
def test_database_refusals_map_to_http(refusal: Exception, code: int) -> None:
    flow = InMemoryHr(refuse=refusal)
    answer = client(flow, "hr.loans.approve").post(
        f"{base(flow)}/loans/{uuid4()}/decision",
        json={"decision": "REFUSED", "reason": "Too much"},
        headers=HEADERS,
    )
    assert answer.status_code == code


def test_payroll_steps_take_the_right_of_the_step() -> None:
    flow = InMemoryHr()
    url = f"{base(flow)}/payrolls/{uuid4()}/steps"
    preparer = client(flow, "hr.payroll.prepare", "hr.salaries.read")
    approver = client(flow, "hr.payroll.approve", "hr.salaries.read")
    assert preparer.post(url, json={"step": "SEND"}, headers=HEADERS).status_code == 200
    assert preparer.post(url, json={"step": "APPROVE"}, headers=HEADERS).status_code == 403
    assert approver.post(url, json={"step": "APPROVE"}, headers=HEADERS).status_code == 200
    assert approver.post(url, json={"step": "SEND"}, headers=HEADERS).status_code == 403
    line = {
        "step": "ADD_LINE",
        "employee_id": str(uuid4()),
        "component": "BONUS",
        "amount_usd_cents": 1000,
        "reason": "Good month",
    }
    assert preparer.post(url, json=line, headers=HEADERS).status_code == 200
    bad = line | {"component": "BASE_SALARY"}
    assert preparer.post(url, json=bad, headers=HEADERS).status_code == 422


def test_attendance_entry_and_overtime() -> None:
    flow = InMemoryHr()
    manager = client(flow, "hr.attendance.manage", "hr.attendance.read")
    entry = {
        "employee_id": str(uuid4()),
        "work_date": "2026-11-03",
        "status": "WORKED",
        "check_in": "06:30",
        "check_out": "15:30",
        "reason": "Phone broken",
    }
    assert manager.post(
        f"{base(flow)}/attendance/entries", json=entry, headers=HEADERS
    ).status_code == (201)
    bad_time = entry | {"check_in": "6.30"}
    assert (
        manager.post(f"{base(flow)}/attendance/entries", json=bad_time, headers=HEADERS).status_code
        == 422
    )
    decide = f"{base(flow)}/overtime/{uuid4()}/decision"
    assert manager.post(decide, json={"decision": "APPROVED"}, headers=HEADERS).status_code == 403
    boss = client(flow, "hr.overtime.approve")
    assert boss.post(decide, json={"decision": "APPROVED"}, headers=HEADERS).status_code == 200


def test_qr_codes_come_back_once_and_are_not_cached() -> None:
    flow = InMemoryHr()
    manager = client(flow, "hr.attendance.manage")
    answer = manager.post(
        f"{base(flow)}/attendance/places/{uuid4()}/qr", json={"reason": "Torn"}, headers=HEADERS
    )
    assert answer.status_code == 201
    assert answer.json()["data"]["code"] == "CHETANA-P-sample"
    assert answer.headers["Cache-Control"] == "private, no-store"


def test_documents_are_saved_with_their_hash(tmp_path: Path) -> None:
    flow = InMemoryHr()
    manager = client(flow, "hr.employees.manage", "hr.employees.read", files=tmp_path)
    url = f"{base(flow)}/employees/{flow.employee_id}/documents"
    content = b"%PDF-1.4 sample contract"
    query = {"kind": "CONTRACT", "title": "Work contract", "file_name": "contract.pdf"}
    wrong = manager.post(
        url, params=query, content=b"x", headers=HEADERS | {"Content-Type": "text/plain"}
    )
    assert wrong.status_code == 415
    saved = manager.post(
        url, params=query, content=content, headers=HEADERS | {"Content-Type": "application/pdf"}
    )
    assert saved.status_code == 201
    found = next(item[2] for name, item in flow.calls if name == "hr_add_employee_document")
    assert isinstance(found, dict)
    record: dict[str, Any] = found
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert record["byte_size"] == len(content)
    assert (tmp_path / record["storage_key"]).read_bytes() == content

    # A refused document leaves no file behind.
    flow.refuse = ProductRefused("The title is at most 120 letters")
    again = manager.post(
        url, params=query, content=content, headers=HEADERS | {"Content-Type": "application/pdf"}
    )
    assert again.status_code == 422
    assert len(list((tmp_path / "hr" / "documents").rglob("*.pdf"))) == 1

    # A download checks the hash first.
    flow.refuse = None
    flow.file = {
        "storage_key": record["storage_key"],
        "sha256": record["sha256"],
        "media_type": "application/pdf",
        "original_name": "contract.pdf",
    }
    got = manager.get(f"{base(flow)}/documents/{uuid4()}/file")
    assert got.status_code == 200
    assert got.content == content
    assert got.headers["X-Content-Type-Options"] == "nosniff"
    flow.file = flow.file | {"sha256": "0" * 64}
    assert manager.get(f"{base(flow)}/documents/{uuid4()}/file").status_code == 503
    flow.file = flow.file | {"storage_key": "../outside.pdf"}
    assert manager.get(f"{base(flow)}/documents/{uuid4()}/file").status_code == 404


def test_without_a_files_folder_uploads_answer_503() -> None:
    flow = InMemoryHr()
    manager = client(flow, "hr.employees.manage")
    answer = manager.post(
        f"{base(flow)}/employees/{flow.employee_id}/documents",
        params={"kind": "OTHER", "title": "Note", "file_name": "note.png"},
        content=b"\x89PNG sample",
        headers=HEADERS | {"Content-Type": "image/png"},
    )
    assert answer.status_code == 503
    assert flow.calls == []
