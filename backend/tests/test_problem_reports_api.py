"""Problem reports API (V1.1 part 7, DL-124, API-PR-001).

Reading needs `problem_reports.read`, adding `problem_reports.add`, a step
`problem_reports.plan` (Join and Undo join `problem_reports.join`) and the tenant's answer
`problem_reports.plan`. The repair cost needs `problem_reports.add` and its check
`problem_reports.costs` (DL-130). Each change needs the browser mutation checks; steps, answers,
the cost and the check need If-Match. The database refusals map to 403, 404, 409, 412 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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

    def cost(
        self, property_id: UUID, report_id: UUID, version: int, cost: Json, *, actor_id: str
    ) -> None:
        self._check(property_id, report_id)
        if version != self.version:
            raise ProductStale
        if self.status != "DONE":
            raise ProductConflict("The cost is typed after the repair is done")
        self.version += 1
        self.calls.append(("cost", cost))

    def check_cost(
        self, property_id: UUID, report_id: UUID, version: int, check: Json, *, actor_id: str
    ) -> None:
        self._check(property_id, report_id)
        if version != self.version:
            raise ProductStale
        self.version += 1
        self.calls.append(("check_cost", check))

    def summary(self, property_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        return {"open": 2, "urgent": 1, "late": 0, "costs_to_check": []}

    def month(self, property_id: UUID, first_day: date, *, actor_id: str) -> Json:
        self._check(property_id)
        self.calls.append(("month", first_day))
        return {"month": first_day.isoformat(), "received": 3}

    def finding(self, property_id: UUID, finding_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id)
        self.calls.append(("finding", finding_id))
        return {"finding_id": str(finding_id), "unit_number": "U101", "report": None}


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


def test_the_repair_cost_needs_the_add_right_and_its_check_the_costs_right() -> None:
    flow = InMemoryProblems(status="DONE")
    report = f"{base(flow)}/problem-reports/{flow.report_id}"
    lines = [
        {"kind": "PARTS", "description": " New tap ", "currency": "USD", "amount_minor": 1250},
        {
            "kind": "OUTSIDE_WORKER",
            "description": "Plumber",
            "currency": "KHR",
            "amount_minor": 40000,
        },
    ]
    reader = client(flow, "problem_reports.read")
    first = HEADERS | {"If-Match": '"1"'}
    assert reader.post(f"{report}/cost", json={"lines": lines}, headers=first).status_code == 403
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    assert staff.post(f"{report}/cost", json={"lines": lines}, headers=HEADERS).status_code == 428
    for wrong in (
        {"lines": [lines[0] | {"amount_minor": 0}]},
        {"lines": [lines[0] | {"amount_minor": 12.5}]},
        {"lines": [lines[0] | {"currency": "EUR"}]},
        {"lines": [lines[0] | {"kind": "STAFF"}]},
        {"lines": [lines[0]] * 21},
        {"lines": lines, "total": 1},
    ):
        assert staff.post(f"{report}/cost", json=wrong, headers=first).status_code == 422
    typed = staff.post(f"{report}/cost", json={"lines": lines, "note": "Riel"}, headers=first)
    assert typed.status_code == 200 and typed.json()["data"]["version"] == 2
    assert flow.calls[-1] == (
        "cost",
        {
            "no_cost": False,
            "note": "Riel",
            "lines": [lines[0] | {"description": "New tap"}, lines[1]],
        },
    )
    check = {"receipt_seen": True, "spent_on": "2026-11-04", "paid_how": "CASH",
             "paid_from_code": "1030"}  # fmt: skip
    second = HEADERS | {"If-Match": '"2"'}
    assert staff.post(f"{report}/cost-check", json=check, headers=second).status_code == 403
    planner = client(flow, "problem_reports.read", "problem_reports.plan")
    assert planner.post(f"{report}/cost-check", json=check, headers=second).status_code == 403
    manager = client(flow, "problem_reports.read", "problem_reports.costs")
    assert (
        manager.post(
            f"{report}/cost-check", json=check | {"receipt_seen": False}, headers=second
        ).status_code
        == 422
    )
    assert manager.post(f"{report}/cost-check", json=check, headers=first).status_code == 412
    checked = manager.post(f"{report}/cost-check", json=check, headers=second)
    assert checked.status_code == 200 and flow.calls[-1] == ("check_cost", check)
    flow.status = "PLANNED"
    late = staff.post(
        f"{report}/cost", json={"no_cost": True}, headers=HEADERS | {"If-Match": '"3"'}
    )
    assert late.status_code == 409


def test_the_home_card_needs_read_and_the_monthly_report_the_plan_right() -> None:
    flow = InMemoryProblems()
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    card = staff.get(f"{base(flow)}/problem-report-summary")
    assert card.status_code == 200 and card.json()["data"]["open"] == 2
    assert card.headers["Cache-Control"] == "private, no-store"
    assert client(flow).get(f"{base(flow)}/problem-report-summary").status_code == 403
    url = f"{base(flow)}/problem-report-month"
    assert staff.get(url, params={"month": "2026-11"}).status_code == 403
    manager = client(flow, "problem_reports.read", "problem_reports.plan")
    for wrong in ("2026-13", "2026-1", "november", ""):
        assert manager.get(url, params={"month": wrong}).status_code == 422
    assert manager.get(url).status_code == 422
    found = manager.get(url, params={"month": "2026-11"})
    assert found.status_code == 200 and found.json()["data"]["received"] == 3
    assert flow.calls[-1] == ("month", date(2026, 11, 1))


def test_a_report_from_an_inspection_finding_needs_the_add_right() -> None:
    flow = InMemoryProblems()
    finding = uuid4()
    url = f"{base(flow)}/problem-report-findings/{finding}"
    assert client(flow, "problem_reports.read").get(url).status_code == 403
    staff = client(flow, "problem_reports.read", "problem_reports.add")
    found = staff.get(url)
    assert found.status_code == 200 and found.json()["data"]["unit_number"] == "U101"
    assert found.headers["Cache-Control"] == "private, no-store"
    assert flow.calls.pop() == ("finding", finding)
    assert staff.get(f"{base(flow)}/problem-report-findings/not-an-id").status_code == 422
    body = {
        "kind": "UNIT",
        "source": "INSPECTION",
        "problem_type_id": str(uuid4()),
        "description": "Bedroom door handle broken",
        "urgent": False,
        "unit_id": str(uuid4()),
        "finding_id": str(finding),
    }
    made = staff.post(f"{base(flow)}/problem-reports", json=body, headers=HEADERS)
    assert made.status_code == 201
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict)
    assert sent["source"] == "INSPECTION" and sent["finding_id"] == str(finding)
