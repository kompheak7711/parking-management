"""Bank and cash read for the ledger screen (phase 6 step 6 part 3): rights and query values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import LedgerMoneyNotFound, LedgerMoneyUnavailable


@dataclass
class InMemoryCash:
    property_id: UUID = field(default_factory=uuid4)
    calls: list[date | None] = field(default_factory=list)

    def bank_cash(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        self.calls.append(month)
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        if month == date(2027, 3, 1):
            raise LedgerMoneyUnavailable
        return {"today": "2027-02-10", "months": [], "banks": [], "cash": []}

    def entry_of(self, property_id: UUID, kind: str, record_id: UUID) -> str:
        if record_id == UUID(int=0):
            raise LedgerMoneyNotFound
        return f"{kind}:JE270001"


def client(flow: InMemoryCash, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_cash_flow=flow))


def test_the_ledger_readers_see_bank_and_cash_for_a_month() -> None:
    flow = InMemoryCash()
    path = f"/api/v1/properties/{flow.property_id}/ledger/bank-cash"
    assert client(flow, "expenses.request").get(path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(path)
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["today"] == "2027-02-10"
    assert reader.get(path, params={"month": "2027-01-15"}).status_code == 200
    assert flow.calls == [None, date(2027, 1, 15)]


def test_the_bank_and_cash_read_refuses_unknown_values() -> None:
    flow = InMemoryCash()
    path = f"/api/v1/properties/{flow.property_id}/ledger/bank-cash"
    reader = client(flow, "ledger.read")
    assert reader.get(path, params={"as_of": "2027-01-01"}).status_code == 422
    assert reader.get(path, params={"month": "January"}).status_code == 422
    assert reader.get(path, params={"month": "2027-03-01"}).status_code == 503
    assert flow.calls == [date(2027, 3, 1)]


def test_the_entry_of_a_money_record_is_read_by_its_kind() -> None:
    flow = InMemoryCash()
    base = f"/api/v1/properties/{flow.property_id}/ledger/money-entries"
    record = uuid4()
    assert client(flow, "expenses.request").get(f"{base}/money-move/{record}").status_code == 403
    reader = client(flow, "ledger.read")
    for kind in ("money-move", "owner-money", "petty-cash-top-up"):
        answer = reader.get(f"{base}/{kind}/{record}")
        assert answer.status_code == 200
        assert answer.headers["Cache-Control"] == "private, no-store"
        assert answer.json()["data"]["entry_number"] == f"{kind}:JE270001"
    assert reader.get(f"{base}/expense/{record}").status_code == 422
    assert reader.get(f"{base}/money-move/{record}", params={"x": "1"}).status_code == 422
    assert reader.get(f"{base}/money-move/not-an-id").status_code == 422
    assert reader.get(f"{base}/money-move/{UUID(int=0)}").status_code == 404
