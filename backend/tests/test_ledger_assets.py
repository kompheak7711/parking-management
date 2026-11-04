"""Fixed asset register read for the ledger screen (phase 6 step 6 part 4): rights and values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemoryAssets:
    property_id: UUID = field(default_factory=uuid4)

    def register(self, property_id: UUID) -> dict[str, Any]:
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        return {"today": "2027-02-10", "assets": [], "accumulated_cents": 0}


def client(flow: InMemoryAssets, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_assets_flow=flow))


def test_the_ledger_readers_see_the_fixed_asset_register() -> None:
    flow = InMemoryAssets()
    path = f"/api/v1/properties/{flow.property_id}/ledger/asset-register"
    assert client(flow, "expenses.request").get(path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(path)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["today"] == "2027-02-10"
    assert reader.get(path, params={"as_of": "2027-01-01"}).status_code == 422
    other = f"/api/v1/properties/{uuid4()}/ledger/asset-register"
    assert client(flow, "ledger.read").get(other).status_code in {403, 404}
