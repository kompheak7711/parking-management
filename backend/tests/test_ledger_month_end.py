"""Month-end close read for the ledger screen (phase 6 step 6 part 4): rights and query values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemoryMonthEnd:
    property_id: UUID = field(default_factory=uuid4)
    calls: list[date | None] = field(default_factory=list)

    def month_end(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        self.calls.append(month)
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        return {"today": "2027-02-10", "months": [], "years": [], "checks": []}


def client(flow: InMemoryMonthEnd, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_month_end_flow=flow))


def test_the_ledger_readers_see_the_month_end_checks() -> None:
    flow = InMemoryMonthEnd()
    path = f"/api/v1/properties/{flow.property_id}/ledger/month-end"
    assert client(flow, "expenses.request").get(path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(path, params={"month": "2027-01-15"})
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["today"] == "2027-02-10"
    assert reader.get(path, params={"as_of": "2027-01-01"}).status_code == 422
    assert reader.get(path, params={"month": "January"}).status_code == 422
    assert flow.calls == [date(2027, 1, 15)]
