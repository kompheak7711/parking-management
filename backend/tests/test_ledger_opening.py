"""Opening balances read for the ledger screen (phase 6 step 6, lopen): rights and query."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemoryOpening:
    property_id: UUID = field(default_factory=uuid4)
    calls: int = 0

    def sheet(self, property_id: UUID) -> dict[str, Any]:
        self.calls += 1
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        return {"today": "2027-02-10", "first_year": 2027, "opening": None}


def client(flow: InMemoryOpening, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_opening_flow=flow))


def test_the_ledger_readers_see_the_opening_sheet() -> None:
    flow = InMemoryOpening()
    path = f"/api/v1/properties/{flow.property_id}/ledger/opening-sheet"
    assert client(flow, "expenses.request").get(path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(path)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["first_year"] == 2027
    assert reader.get(path, params={"year": "2027"}).status_code == 422
    assert flow.calls == 1
