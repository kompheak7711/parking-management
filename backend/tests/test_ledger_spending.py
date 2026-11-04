"""Spending reads for the ledger screens (phase 6 step 6 part 2): rights and query values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemorySpending:
    property_id: UUID = field(default_factory=uuid4)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def form(self, property_id: UUID) -> dict[str, Any]:
        self.calls.append(("form", None))
        return {"today": "2027-01-31", "report_days": 3, "accounts": []}

    def request(
        self, property_id: UUID, request_number: str, requested_by: str | None
    ) -> dict[str, Any]:
        self.calls.append(("request", requested_by))
        if request_number == "ER270099":
            raise LedgerMoneyNotFound
        return {"request_number": request_number, "steps": []}


def client(flow: InMemorySpending, actor: str, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=actor,
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_spending_flow=flow))


def test_every_role_that_sends_requests_reads_the_form_and_staff_read_only_their_own() -> None:
    flow = InMemorySpending()
    base = f"/api/v1/properties/{flow.property_id}/expense-requests"
    staff_id = str(uuid4())
    assert client(flow, staff_id, "ledger.read").get(base + "/form").status_code == 403
    assert client(flow, staff_id, "ledger.read").get(base + "/ER270001").status_code == 403
    staff = client(flow, staff_id, "expenses.request")
    answer = staff.get(base + "/form")
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["report_days"] == 3
    one = staff.get(base + "/ER270001")
    assert one.headers["Cache-Control"] == "private, no-store"
    assert one.json()["data"]["request_number"] == "ER270001"
    approver = client(flow, str(uuid4()), "expenses.request", "expenses.approve")
    assert approver.get(base + "/ER270001").status_code == 200
    payer = client(flow, str(uuid4()), "expenses.request", "expenses.record")
    assert payer.get(base + "/ER270001").status_code == 200
    assert flow.calls == [
        ("form", None),
        ("request", staff_id),
        ("request", None),
        ("request", None),
    ]


def test_the_spending_reads_refuse_unknown_values_and_say_when_a_request_is_not_there() -> None:
    flow = InMemorySpending()
    base = f"/api/v1/properties/{flow.property_id}/expense-requests"
    reader = client(flow, str(uuid4()), "expenses.request")
    assert reader.get(base + "/form", params={"as_of": "2027-01-01"}).status_code == 422
    assert reader.get(base + "/ER270001", params={"x": "1"}).status_code == 422
    assert reader.get(base + "/er-1").status_code in {404, 422}
    assert reader.get(base + "/ER270099").status_code == 404
    assert [call[0] for call in flow.calls] == ["request"]
