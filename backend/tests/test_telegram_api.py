"""Telegram app pages API (bots step 2c, DL-128, API-TG-001; step 2d part 2, DL-170; step 3a,
DL-171).

Reading the Linked tenants and Telegram health pages needs `telegram.read`; Remove link and Retry
need `telegram.operate` and the browser mutation checks. Contact office needs `telegram.contact`;
the FAQ is read with `telegram.faq` or `telegram.contact` and changed with `telegram.faq`. The
database refusals map to 403, 404 and 409. The Invoices on Telegram list (DL-211, API-TG-008)
also needs `telegram.read`. The Visit requests list (step 3a, DL-171) needs
`visit_requests.read`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import (
    Json,
    ProductConflict,
    ProductForbidden,
    ProductNotFound,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=telegram-token",
    "X-CSRF-Token": "telegram-token",
}


@dataclass
class InMemoryTelegram:
    property_id: UUID = field(default_factory=uuid4)
    link_id: UUID = field(default_factory=uuid4)
    message_id: UUID = field(default_factory=uuid4)
    removed: list[tuple[UUID, str]] = field(default_factory=list)
    retried: list[UUID] = field(default_factory=list)
    answers: list[tuple[UUID, str, str]] = field(default_factory=list)
    saved: list[Json] = field(default_factory=list)
    approved: list[UUID] = field(default_factory=list)
    steps: list[tuple[str, Json]] = field(default_factory=list)
    owner: bool = False
    starter_loaded: bool = False

    def _check(self, property_id: UUID) -> None:
        if property_id != self.property_id:
            raise ProductNotFound("the Property does not exist")

    def links(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        linked = [] if self.removed else [{"id": str(self.link_id), "name": "Sao Rina"}]
        return {"linked": linked, "tries": [], "ended": [], "rules": {"tries": 5}}

    def remove_link(self, property_id: UUID, link_id: UUID, reason: str, *, actor_id: str) -> None:
        self._check(property_id)
        if link_id != self.link_id:
            raise ProductNotFound("the link was not found")
        if self.removed:
            raise ProductConflict("the link has already ended")
        self.removed.append((link_id, reason))

    def health(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"outbox_waiting": 0, "bots": [], "outbox": [], "pulls": []}

    def invoices(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"invoices": [{"number": "INV-26-0001", "sent": []}], "rules": {"remind_days": 3}}

    def retry(self, property_id: UUID, message_id: UUID, *, actor_id: str) -> UUID:
        self._check(property_id)
        if message_id in self.retried:
            raise ProductConflict("This message was already sent again")
        self.retried.append(message_id)
        return uuid4()

    def contact(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        waiting = [] if self.answers else [{"id": str(self.message_id), "message": "Hello"}]
        return {"waiting": waiting, "answered": [{"id": str(m)} for m, _, _ in self.answers]}

    def answer(
        self, property_id: UUID, message_id: UUID, how: str, text: str, *, actor_id: str
    ) -> None:
        self._check(property_id)
        if message_id != self.message_id:
            raise ProductNotFound("the message does not exist")
        if self.answers:
            raise ProductConflict("This message was already answered")
        self.answers.append((message_id, how, text))

    def faq(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"questions": [], "owner": self.owner, "can_edit": True}

    def save_faq(self, property_id: UUID, version: Json, *, actor_id: str) -> Json:
        self._check(property_id)
        self.saved.append(version)
        return {"number": len(self.saved), "approved": self.owner}

    def approve_faq(self, property_id: UUID, version_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        if not self.owner:
            raise ProductForbidden("Only the Owner approves a FAQ answer")
        self.approved.append(version_id)
        return {"number": 1, "version_number": 1}

    def load_faq_starter(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        if self.starter_loaded:
            raise ProductConflict("The FAQ already has questions")
        self.starter_loaded = True
        return {"loaded": 15}

    def visit_requests(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"requests": [{"number": "VR260001", "joined": []}], "today": "2026-11-05"}

    def visit_request(self, property_id: UUID, request_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"id": str(request_id), "status": "NEW", "history": []}

    def visit_step(
        self, property_id: UUID, request_id: UUID, action: str, body: Json, *, actor_id: str
    ) -> None:
        self._check(property_id)
        if action == "TAKE" and self.steps:
            raise ProductConflict("Someone already took this request")
        self.steps.append((action, body))


def client(flow: InMemoryTelegram, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, telegram_page_flow=flow))


def base(flow: InMemoryTelegram) -> str:
    return f"/api/v1/properties/{flow.property_id}/telegram"


def test_the_telegram_pages_need_telegram_read() -> None:
    flow = InMemoryTelegram()
    for url in (f"{base(flow)}/links", f"{base(flow)}/health", f"{base(flow)}/invoices"):
        assert client(flow).get(url).status_code == 403
        answer = client(flow, "telegram.read").get(url)
        assert answer.status_code == 200
        assert answer.headers["Cache-Control"] == "private, no-store"
    other = InMemoryTelegram()
    wrong = client(flow, "telegram.read").get(
        f"/api/v1/properties/{other.property_id}/telegram/links"
    )
    assert wrong.status_code == 403


def test_remove_link_needs_operate_a_reason_and_the_browser_checks() -> None:
    flow = InMemoryTelegram()
    url = f"{base(flow)}/links/{flow.link_id}/remove"
    body = {"reason": "  Lost phone "}
    reader = client(flow, "telegram.read")
    assert reader.post(url, json=body, headers=HEADERS).status_code == 403
    manager = client(flow, "telegram.read", "telegram.operate")
    assert manager.post(url, json=body).status_code == 403  # no browser mutation checks
    assert manager.post(url, json={"reason": " "}, headers=HEADERS).status_code == 422
    done = manager.post(url, json=body, headers=HEADERS)
    assert done.status_code == 200 and done.json()["data"]["linked"] == []
    assert flow.removed == [(flow.link_id, "Lost phone")]
    assert manager.post(url, json=body, headers=HEADERS).status_code == 409
    missing = manager.post(f"{base(flow)}/links/{uuid4()}/remove", json=body, headers=HEADERS)
    assert missing.status_code == 404


def test_retry_sends_a_given_up_message_once() -> None:
    flow = InMemoryTelegram()
    url = f"{base(flow)}/outbox/{flow.message_id}/retry"
    assert client(flow, "telegram.read").post(url, headers=HEADERS).status_code == 403
    manager = client(flow, "telegram.read", "telegram.operate")
    sent = manager.post(url, headers=HEADERS)
    assert sent.status_code == 201 and "health" in sent.json()["data"]
    assert manager.post(url, headers=HEADERS).status_code == 409


def test_contact_office_needs_its_right_and_answers_once() -> None:
    flow = InMemoryTelegram()
    url = f"{base(flow)}/contact"
    assert client(flow, "telegram.read").get(url).status_code == 403
    staff = client(flow, "telegram.contact")
    page = staff.get(url)
    assert page.status_code == 200 and page.headers["Cache-Control"] == "private, no-store"
    answer = f"{url}/{flow.message_id}/answer"
    body = {"how": "TELEGRAM", "answer": "  We will call you at 10:00. "}
    assert staff.post(answer, json=body).status_code == 403  # no browser mutation checks
    assert staff.post(answer, json=body | {"how": "EMAIL"}, headers=HEADERS).status_code == 422
    assert staff.post(answer, json=body | {"answer": " "}, headers=HEADERS).status_code == 422
    assert staff.post(answer, json=body | {"answer": "x" * 601}, headers=HEADERS).status_code == 422
    done = staff.post(answer, json=body, headers=HEADERS)
    assert done.status_code == 200 and done.json()["data"]["waiting"] == []
    assert flow.answers == [(flow.message_id, "TELEGRAM", "We will call you at 10:00.")]
    assert staff.post(answer, json=body, headers=HEADERS).status_code == 409
    missing = staff.post(f"{url}/{uuid4()}/answer", json=body, headers=HEADERS)
    assert missing.status_code == 404


def test_the_faq_is_read_by_contact_staff_and_changed_with_its_right() -> None:
    flow = InMemoryTelegram()
    url = f"{base(flow)}/faq"
    assert client(flow, "telegram.read").get(url).status_code == 403
    assert client(flow, "telegram.contact").get(url).status_code == 200
    body = {
        "for_bots": "BOTH",
        "question_en": " Office hours? ",
        "answer_en": "07:00 to 17:00",
        "question_km": "ម៉ោងធ្វើការ?",
        "answer_km": "០៧:០០ ដល់ ១៧:០០",
    }
    staff = client(flow, "telegram.contact")
    assert staff.post(url, json=body, headers=HEADERS).status_code == 403
    manager = client(flow, "telegram.faq")
    assert manager.post(url, json=body | {"for_bots": "ALL"}, headers=HEADERS).status_code == 422
    assert manager.post(url, json=body | {"answer_km": ""}, headers=HEADERS).status_code == 422
    saved = manager.post(url, json=body, headers=HEADERS)
    assert saved.status_code == 200 and saved.json()["data"]["saved"]["approved"] is False
    assert flow.saved[0]["question_id"] is None and flow.saved[0]["question_en"] == "Office hours?"
    # A change to a saved question names it.
    question = str(uuid4())
    edited = manager.post(url, json=body | {"question_id": question}, headers=HEADERS)
    assert edited.status_code == 200 and flow.saved[1]["question_id"] == question
    version = uuid4()
    approve = f"{url}/versions/{version}/approve"
    assert manager.post(approve, headers=HEADERS).status_code == 403
    flow.owner = True
    approved = manager.post(approve, headers=HEADERS)
    assert approved.status_code == 200 and flow.approved == [version]


def test_the_starter_faq_loads_once_with_the_faq_right() -> None:
    flow = InMemoryTelegram()
    url = f"{base(flow)}/faq/starter"
    assert client(flow, "telegram.contact").post(url, headers=HEADERS).status_code == 403
    manager = client(flow, "telegram.faq")
    assert manager.post(url).status_code == 403
    loaded = manager.post(url, headers=HEADERS)
    assert loaded.status_code == 200 and loaded.json()["data"]["loaded"] == {"loaded": 15}
    assert loaded.json()["data"]["faq"]["questions"] == []
    again = manager.post(url, headers=HEADERS)
    assert again.status_code == 409


def test_the_visit_requests_list_needs_its_right() -> None:
    flow = InMemoryTelegram()
    url = f"/api/v1/properties/{flow.property_id}/visit-requests"
    assert client(flow, "telegram.read").get(url).status_code == 403
    answer = client(flow, "visit_requests.read").get(url)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["requests"][0]["number"] == "VR260001"
    other = InMemoryTelegram()
    assert client(other, "visit_requests.read").get(url).status_code == 403


def test_a_visit_request_step_needs_work_and_a_manager_gives_or_marks_spam() -> None:
    flow = InMemoryTelegram()
    request_id = uuid4()
    url = f"/api/v1/properties/{flow.property_id}/visit-requests/{request_id}"
    assert client(flow, "visit_requests.work").get(url).status_code == 403
    shown = client(flow, "visit_requests.read").get(url)
    assert shown.status_code == 200 and shown.json()["data"]["status"] == "NEW"
    staff = client(flow, "visit_requests.read", "visit_requests.work")
    assert (
        client(flow, "visit_requests.read")
        .post(f"{url}/take", json={}, headers=HEADERS)
        .status_code
        == 403
    )
    taken = staff.post(f"{url}/take", json={}, headers=HEADERS)
    assert taken.status_code == 200
    assert set(taken.json()["data"]) == {"request", "page"}
    assert staff.post(f"{url}/take", json={}, headers=HEADERS).status_code == 409
    worker = str(uuid4())
    assert staff.post(f"{url}/give", json={"staff_id": worker}, headers=HEADERS).status_code == 403
    manager = client(flow, "visit_requests.read", "visit_requests.work", "visit_requests.manage")
    assert (
        manager.post(f"{url}/give", json={"staff_id": worker}, headers=HEADERS).status_code == 200
    )
    booked = staff.post(
        f"{url}/book", json={"visit_at": "2026-11-09T10:00", "note": " Bring the keys "},
        headers=HEADERS,
    )  # fmt: skip
    assert booked.status_code == 200
    assert staff.post(f"{url}/no-show", json={}, headers=HEADERS).status_code == 200
    for wrong in (
        {"visit_at": "9 Nov 10am"},
        {"reason": "BORED"},
        {"answered": "yes"},
        {"what": "LETTER"},
        {"note": "x" * 301},
        {"extra": 1},
    ):
        assert staff.post(f"{url}/close", json=wrong, headers=HEADERS).status_code == 422
    assert staff.post(f"{url}/dance", json={}, headers=HEADERS).status_code == 422
    reserved = str(uuid4())
    assert (
        staff.post(f"{url}/reserve", json={"reservation_id": reserved}, headers=HEADERS).status_code
        == 200
    )
    assert staff.post(f"{url}/block", json={"note": "Adverts"}, headers=HEADERS).status_code == 403
    assert (
        manager.post(f"{url}/block", json={"note": "Adverts"}, headers=HEADERS).status_code == 200
    )
    assert manager.post(f"{url}/unblock", json={}, headers=HEADERS).status_code == 200
    assert flow.steps[-3:] == [
        ("RESERVE", {"reservation_id": reserved}),
        ("BLOCK", {"note": "Adverts"}),
        ("UNBLOCK", {}),
    ]
    del flow.steps[-3:]
    assert flow.steps == [
        ("TAKE", {}),
        ("GIVE", {"staff_id": worker}),
        ("BOOK", {"visit_at": "2026-11-09T10:00", "note": "Bring the keys"}),
        ("NO_SHOW", {}),
    ]
