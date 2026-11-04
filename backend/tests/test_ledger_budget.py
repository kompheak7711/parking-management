"""Budget read for the ledger screen (phase 6 step 6 part 4): rights and query values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemoryBudget:
    property_id: UUID = field(default_factory=uuid4)
    calls: list[int | None] = field(default_factory=list)

    def sheet(self, property_id: UUID, year: int | None) -> dict[str, Any]:
        self.calls.append(year)
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        return {"today": "2027-02-10", "years": [], "year": None, "budgets": []}


def client(flow: InMemoryBudget, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_budget_flow=flow))


def test_the_ledger_readers_see_the_budget_sheet() -> None:
    flow = InMemoryBudget()
    path = f"/api/v1/properties/{flow.property_id}/ledger/budget-sheet"
    assert client(flow, "expenses.request").get(path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(path, params={"year": "2027"})
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["today"] == "2027-02-10"
    assert reader.get(path).status_code == 200
    assert reader.get(path, params={"month": "2027-01-01"}).status_code == 422
    assert reader.get(path, params={"year": "1999"}).status_code == 422
    assert reader.get(path, params={"year": "next"}).status_code == 422
    assert flow.calls == [2027, None]
