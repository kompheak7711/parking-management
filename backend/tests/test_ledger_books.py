"""General Ledger books reads for the screens (phase 6 step 6 part 1): rights and query values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_books_api import source_link
from property_rental.ledger_money_api import LedgerMoneyNotFound


@dataclass
class InMemoryBooks:
    property_id: UUID = field(default_factory=uuid4)
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def accounts(self, property_id: UUID, as_of: date | None) -> dict[str, Any]:
        self.calls.append(("accounts", as_of))
        return {"as_of": "2027-01-31", "accounts": [{"code": "1010", "balance_cents": 500}]}

    def entries(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        self.calls.append(("entries", month))
        return {"month": None, "months": [], "newest_only": True, "entries": []}

    def entry(self, property_id: UUID, entry_number: str) -> dict[str, Any]:
        self.calls.append(("entry", entry_number))
        if entry_number == "JE270099":
            raise LedgerMoneyNotFound
        return {"entry_number": entry_number, "lines": []}


def client(flow: InMemoryBooks, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_books_flow=flow))


def test_the_books_need_the_ledger_right_and_are_not_cached() -> None:
    flow = InMemoryBooks()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    for path in ("/accounts", "/entries", "/entries/JE270001"):
        assert client(flow, "invoices.read").get(base + path).status_code == 403
    reader = client(flow, "ledger.read")
    answer = reader.get(base + "/accounts", params={"as_of": "2027-01-31"})
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["accounts"][0]["balance_cents"] == 500
    assert reader.get(base + "/entries", params={"month": "2027-01-15"}).status_code == 200
    assert reader.get(base + "/entries/JE270001").json()["data"]["entry_number"] == "JE270001"
    assert flow.calls == [
        ("accounts", date(2027, 1, 31)),
        ("entries", date(2027, 1, 15)),
        ("entry", "JE270001"),
    ]


def test_the_books_refuse_unknown_values_and_say_when_an_entry_is_not_there() -> None:
    flow = InMemoryBooks()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    reader = client(flow, "ledger.read")
    assert reader.get(base + "/accounts", params={"month": "2027-01-01"}).status_code == 422
    assert reader.get(base + "/entries", params={"as_of": "2027-01-01"}).status_code == 422
    assert reader.get(base + "/entries", params={"month": "01/2027"}).status_code == 422
    assert reader.get(base + "/entries/1; DROP").status_code in {404, 422}
    assert reader.get(base + "/entries/JE270099").status_code == 404
    assert flow.calls == [("entry", "JE270099")]


def test_a_source_links_to_its_invoice_or_receipt_page() -> None:
    target = uuid4()
    assert source_link("INVOICE_LINE", target) == {"page": "invoices", "detail": f"inv:{target}"}
    assert source_link("PAYMENT_ALLOCATION", target) == {
        "page": "payments",
        "detail": f"receipt:{target}",
    }
    assert source_link("EXPENSE", target) is None
    assert source_link("INVOICE", None) is None
