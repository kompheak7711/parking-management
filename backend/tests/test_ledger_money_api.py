"""General Ledger money records API (phase 6 step 3).

The route checks the main right for the Property and the browser mutation checks; the checked
database function decides the rest (a Manager approves up to the Expense limit, owner 03/11/2026
07:03; nobody approves their own). A Staff member sees only their own Expense requests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_money_api import (
    ACTIONS,
    LedgerMoneyConflict,
    LedgerMoneyInvalid,
    LedgerMoneyNotFound,
    LedgerMoneyRefused,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=ledger-token",
    "X-CSRF-Token": "ledger-token",
}
REQUEST = {
    "kind": "REQUEST",
    "account_code": "6050",
    "description": "Pipe repair",
    "reason": "The pipe leaks",
    "amount_cents": 5000,
    "paid_how": "ADVANCE",
}


@dataclass
class InMemoryMoney:
    property_id: UUID = field(default_factory=uuid4)
    writes: list[tuple[str, str, dict[str, Any], UUID | None]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    refuse: Exception | None = None

    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> UUID | None:
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        if self.refuse is not None:
            raise self.refuse
        assert set(values) == set(ACTIONS[action].fields)
        self.writes.append((action, actor_id, values, target_id))
        if action == "submit_request":
            self.requests.append({"id": str(uuid4()), "requested_by": actor_id})
        return uuid4()

    def expense_requests(
        self, property_id: UUID, *, requested_by: str | None
    ) -> tuple[dict[str, Any], ...]:
        assert property_id == self.property_id
        return tuple(row for row in self.requests if requested_by in (None, row["requested_by"]))

    def rows(self, view: str, property_id: UUID) -> tuple[dict[str, Any], ...]:
        assert property_id == self.property_id
        return ({"view": view},)


def client(flow: InMemoryMoney, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_money_flow=flow))


def test_each_change_needs_its_right_and_the_browser_checks() -> None:
    flow = InMemoryMoney()
    base = f"/api/v1/properties/{flow.property_id}"
    target = uuid4()
    for path, right, body in (
        ("/expense-requests", "expenses.request", REQUEST),
        (f"/expense-requests/{target}/decision", "expenses.approve", {"approve": True}),
        (
            f"/expense-requests/{target}/advance",
            "expenses.record",
            {"from_code": "1010", "paid_on": "2027-01-05"},
        ),
        (
            "/ledger/money-moves",
            "ledger.money_move",
            {"moved_on": "2027-01-05", "from_code": "1010", "to_code": "1020", "amount_cents": 1},
        ),
        (
            "/ledger/owner-money",
            "ledger.owner_money",
            {
                "direction": "IN",
                "moved_on": "2027-01-05",
                "account_code": "1010",
                "amount_cents": 100,
            },
        ),
        (
            "/ledger/petty-cash-top-ups",
            "ledger.petty_cash",
            {"topped_up_on": "2027-01-05", "from_code": "1010", "amount_cents": 100},
        ),
        (
            "/ledger/cash-counts",
            "ledger.cash_count",
            {"account_code": "1010", "counted_on": "2027-01-05", "counted_cents": 0},
        ),
        (
            f"/ledger/supplier-bills/{target}/payments",
            "supplier_bills.pay",
            {"from_code": "1020", "paid_on": "2027-01-05", "amount_cents": 100},
        ),
    ):
        assert (
            client(flow, "ledger.read").post(base + path, json=body, headers=HEADERS).status_code
            == 403
        )
        holder = client(flow, right)
        assert holder.post(base + path, json=body).status_code == 403
        answer = holder.post(base + path, json=body, headers=HEADERS)
        assert answer.status_code in (200, 201), (path, answer.text)
    actions = [write[0] for write in flow.writes]
    assert actions == [
        "submit_request",
        "decide_request",
        "give_advance",
        "move_money",
        "owner_money",
        "top_up_petty_cash",
        "count_cash",
        "pay_bill",
    ]
    # A decision and an advance answer with the request they act on.
    assert flow.writes[1][3] == target
    other = f"/api/v1/properties/{uuid4()}/expense-requests"
    assert (
        client(flow, "expenses.request").post(other, json=REQUEST, headers=HEADERS).status_code
        == 403
    )


def test_bodies_are_strict_and_database_refusals_keep_their_meaning() -> None:
    flow = InMemoryMoney()
    url = f"/api/v1/properties/{flow.property_id}/expense-requests"
    staff = client(flow, "expenses.request")
    for bad in (
        {**REQUEST, "extra": 1},
        {**REQUEST, "amount_cents": "50"},
        {**REQUEST, "amount_cents": 0},
        {**REQUEST, "account_code": "60"},
        {**REQUEST, "kind": "OTHER"},
        {**REQUEST, "paid_how": "CARD"},
        {**REQUEST, "spent_on": "05/01/2027"},
    ):
        assert staff.post(url, json=bad, headers=HEADERS).status_code == 422, bad
    for error, code in (
        (LedgerMoneyRefused("Nobody approves their own Expense request"), 403),
        (LedgerMoneyInvalid("The amount is more than zero"), 422),
        (LedgerMoneyConflict("The month of 05/01/2027 is closed"), 409),
        (LedgerMoneyNotFound(), 404),
    ):
        flow.refuse = error
        answer = staff.post(url, json=REQUEST, headers=HEADERS)
        assert answer.status_code == code
        if code != 404:
            assert answer.json()["error"]["message"] == str(error)
            assert answer.json()["error"]["code"].startswith("LEDGER_MONEY_")
    flow.refuse = None


def test_staff_see_their_own_requests_and_approvers_see_all() -> None:
    flow = InMemoryMoney()
    url = f"/api/v1/properties/{flow.property_id}/expense-requests"
    first, second = client(flow, "expenses.request"), client(flow, "expenses.request")
    assert first.post(url, json=REQUEST, headers=HEADERS).status_code == 201
    assert second.post(url, json=REQUEST, headers=HEADERS).status_code == 201
    mine = first.get(url)
    assert mine.status_code == 200 and mine.headers["Cache-Control"] == "private, no-store"
    assert mine.json()["meta"]["count"] == 1
    assert (
        client(flow, "expenses.request", "expenses.approve").get(url).json()["meta"]["count"] == 2
    )
    assert client(flow, "ledger.read").get(url).status_code == 403
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    assert first.get(f"{base}/suppliers").json()["data"] == [{"view": "suppliers"}]
    for view in ("expenses", "supplier-bills"):
        assert first.get(f"{base}/{view}").status_code == 403
        assert client(flow, "ledger.read").get(f"{base}/{view}").json()["data"] == [{"view": view}]
