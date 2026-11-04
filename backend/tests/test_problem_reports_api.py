"""Problem reports API (V1.1 part 7, DL-124, API-PR-001).

Reading needs `problem_reports.read`, adding `problem_reports.add`, a step
`problem_reports.plan` (Join and Undo join `problem_reports.join`) and the tenant's answer
`problem_reports.plan`. Each change needs the browser mutation checks; steps and answers need
If-Match. The database refusals map to 403, 404, 409, 412 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import Json, ProductConflict, ProductNotFound, ProductStale

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=problems-token",
    "X-CSRF-Token": "problems-token",
}


@dataclass
class InMemoryProblems:
    property_id: UUID = field(default_factory=uuid4)
    report_id: UUID = field(default_factory=uuid4)
    version: int = 1
    status: str = "RECEIVED"
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _check(self, property_id: UUID, report_id: UUID | None = None) -> None:
        if property_id != self.property_id or report_id not in (None, self.report_id):
            raise ProductNotFound("the Problem report does not exist")

    def _report(self) -> Json:
        return {
            "report_id": str(self.report_id),
            "report_number": "UP260001",
            "state": self.status,
            "version": self.version,
        }

    def reports(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        return [self._report()]

    def report(self, property_id: UUID, report_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id, report_id)
        return self._report()

    def choices(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"types": [], "places": [], "units": [], "rules": {}}

    def add(self, property_id: UUID, report: Json, *, actor_id: str) -> UUID:
        self._check(property_id)
        self.calls.append(("add", report))
        return self.report_id

    def step(
        self, property_id: UUID, report_id: UUID, version: int, step: Json, *, actor_id: str
    ) -> None:
        self._check(property_id, report_id)
        if version != self.version:
            raise ProductStale
        if step["step"] == "DONE" and self.status != "REPAIR_PLANNED":
            raise ProductConflict("Only a planned repair is marked done")
        self.version += 1
        self.calls.append(("step", step))

    def answer(
        self, property_id: UUID, report_id: UUID, version: int, answer: Json, *, actor_id: str
    ) -> None:
        self._check(property_id, report_id)
        if version != self.version:
            raise ProductStale
        self.version += 1
        self.status = "REPAIR_PLANNED"
        self.calls.append(("answer", answer))


def client(flow: InMemoryProblems, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, problem_report_flow=flow))


def base(flow: InMemoryProblems) -> str:
    return f"/api/v1/properties/{flow.property_id}"


def test_reading_problem_reports_needs_problem_reports_read() -> None:
    flow = InMemoryProblems()
    for url in (
        f"{base(flow)}/problem-reports",
        f"{base(flow)}/problem-reports/{flow.report_id}",
        f"{base(flow)}/problem-report-choices",
    ):
        assert client(flow).get(url).status_code == 403
        answer = client(flow, "problem_reports.read").get(url)
        assert answer.status_code == 200
        assert answer.headers["Cache-Control"] == "private, no-store"
    missing = client(flow, "problem_reports.read").get(f"{base(flow)}/problem-reports/{uuid4()}")
    assert missing.status_code == 404


def test_adding_a_report_needs_its_right_and_a_valid_form() -> None:
    flow = InMemoryProblems()
    body = {
        "kind": "UNIT",
        "source": "PHONE",
        "problem_type_id": str(uuid4()),
        "description": " The tap leaks ",
        "urgent": False,
        "unit_id": str(uuid4()),
    }
    url = f"{base(flow)}/problem-reports"
    assert (
        client(flow, "problem_reports.read").post(url, json=body, headers=HEADERS).status_code
        == 403
    )
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    assert staff.post(url, json=body).status_code == 403  # no browser mutation checks
    assert staff.post(url, json=body | {"source": "EMAIL"}, headers=HEADERS).status_code == 422
    made = staff.post(url, json=body, headers=HEADERS)
    assert made.status_code == 201 and made.json()["data"]["report_number"] == "UP260001"
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict)
    assert sent["description"] == "The tap leaks" and "floor" not in sent
    assert sent["best_time"] == "ANY" and sent["may_enter"] is False


def test_steps_need_the_plan_right_if_match_and_the_join_right_to_join() -> None:
    flow = InMemoryProblems()
    url = f"{base(flow)}/problem-reports/{flow.report_id}/steps"
    plan = {
        "step": "PLAN",
        "technician": "Chan Rith",
        "visit_on": "2026-11-05",
        "visit_at": "09:30",
    }
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    assert staff.post(url, json=plan, headers=HEADERS | {"If-Match": '"1"'}).status_code == 403
    manager = client(flow, "problem_reports.read", "problem_reports.plan")
    assert manager.post(url, json=plan, headers=HEADERS).status_code == 428
    assert manager.post(url, json=plan, headers=HEADERS | {"If-Match": '"7"'}).status_code == 412
    done = manager.post(url, json=plan, headers=HEADERS | {"If-Match": '"1"'})
    assert done.status_code == 200 and done.json()["data"]["version"] == 2
    sent = flow.calls[-1][1]
    assert sent == {
        "step": "PLAN",
        "technician": "Chan Rith",
        "visit_on": "2026-11-05",
        "visit_at": "09:30",
    }
    finished = manager.post(url, json={"step": "DONE"}, headers=HEADERS | {"If-Match": '"2"'})
    assert finished.status_code == 409
    join = {"step": "JOIN", "main_id": str(uuid4()), "reason": "Same lift"}
    assert manager.post(url, json=join, headers=HEADERS | {"If-Match": '"2"'}).status_code == 403
    joiner = client(flow, "problem_reports.read", "problem_reports.join")
    assert joiner.post(url, json=join, headers=HEADERS | {"If-Match": '"2"'}).status_code == 200
    assert (
        manager.post(url, json={"step": "FLY"}, headers=HEADERS | {"If-Match": '"3"'}).status_code
        == 422
    )


def test_the_tenant_answer_needs_the_plan_right_and_if_match() -> None:
    flow = InMemoryProblems(status="WAITING_TENANT")
    url = f"{base(flow)}/problem-reports/{flow.report_id}/tenant-answer"
    agreed = {"answer": "AGREED", "how": "PHONE", "answered_on": "2026-11-04"}
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    assert staff.post(url, json=agreed, headers=HEADERS | {"If-Match": '"1"'}).status_code == 403
    manager = client(flow, "problem_reports.read", "problem_reports.plan")
    assert manager.post(url, json=agreed, headers=HEADERS).status_code == 428
    assert (
        manager.post(
            url, json=agreed | {"how": "EMAIL"}, headers=HEADERS | {"If-Match": '"1"'}
        ).status_code
        == 422
    )
    answer = manager.post(url, json=agreed, headers=HEADERS | {"If-Match": '"1"'})
    assert answer.status_code == 200 and answer.json()["data"]["state"] == "REPAIR_PLANNED"
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict)
    assert sent["answer"] == "AGREED" and sent["said"] is None and sent["after_refusal"] is None
