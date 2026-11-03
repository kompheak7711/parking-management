"""General Ledger close API (phase 6 step 4 part 1).

The route checks the main right for the Property and the browser mutation checks; the checked
database function decides the rest (nobody approves their own adjusting entry; Close works only
when every check is green; months close in order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_close_api import ACTIONS
from property_rental.ledger_money_api import (
    LedgerMoneyConflict,
    LedgerMoneyNotFound,
    LedgerMoneyRefused,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=ledger-token",
    "X-CSRF-Token": "ledger-token",
}
ENTRY = {
    "entry_date": "2027-01-31",
    "reason": "Repair not billed yet",
    "lines": [
        {"account_code": "6050", "debit_cents": 2500},
        {"account_code": "2010", "credit_cents": 2500, "memo": "Dara Plumbing"},
    ],
}


@dataclass
class InMemoryClose:
    property_id: UUID = field(default_factory=uuid4)
    writes: list[tuple[str, dict[str, Any], UUID | None]] = field(default_factory=list)
    refuse: Exception | None = None
    answer: Any = None

    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> Any:
        del actor_id
        if property_id != self.property_id:
            raise LedgerMoneyNotFound
        if self.refuse is not None:
            raise self.refuse
        assert set(values) <= set(ACTIONS[action].fields)
        self.writes.append((action, values, target_id))
        return self.answer if self.answer is not None else uuid4()

    def rows(
        self,
        view: str,
        property_id: UUID,
        target_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        assert property_id == self.property_id
        return (
            {
                "view": view,
                "target": None if target_id is None else str(target_id),
                **(extra or {}),
            },
        )


def client(flow: InMemoryClose, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_close_flow=flow))


def test_each_close_change_needs_its_right_and_the_browser_checks() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    target = uuid4()
    for method, path, right, body in (
        ("post", "/adjusting-entries", "ledger.adjustments.prepare", ENTRY),
        (
            "post",
            f"/adjusting-entries/{target}/decision",
            "ledger.adjustments.approve",
            {"approve": False, "note": "Already billed"},
        ),
        (
            "post",
            f"/adjusting-entries/{target}/void",
            "ledger.adjustments.prepare",
            {"reason": "x"},
        ),
        ("post", "/opening-balances", "ledger.opening_balances", {"first_year": 2027}),
        (
            "put",
            "/opening-balances/lines",
            "ledger.opening_balances",
            {"lines": [{"account_code": "1010", "debit_cents": 100}]},
        ),
        ("post", "/opening-balances/post", "ledger.opening_balances", {}),
        ("post", f"/periods/{target}/close", "ledger.close", {}),
        ("post", f"/fiscal-years/{target}/close", "ledger.close", {}),
    ):
        reader = client(flow, "ledger.read")
        assert reader.request(method, base + path, json=body, headers=HEADERS).status_code == 403
        holder = client(flow, right)
        assert holder.request(method, base + path, json=body).status_code == 403
        answer = holder.request(method, base + path, json=body, headers=HEADERS)
        assert answer.status_code in (200, 201), (path, answer.text)
    assert [write[0] for write in flow.writes] == [
        "prepare_adjustment",
        "decide_adjustment",
        "void_adjustment",
        "begin_ledger",
        "set_opening_lines",
        "post_opening",
        "close_month",
        "close_year",
    ]
    # Lines reach the database by account code, one side each.
    assert [
        {key: value for key, value in line.items() if value is not None}
        for line in flow.writes[0][1]["lines"]
    ] == [
        {"account": "6050", "debit_cents": 2500},
        {"account": "2010", "memo": "Dara Plumbing", "credit_cents": 2500},
    ]
    assert flow.writes[1][2] == target
    # An approver may void an entry too.
    voided = client(flow, "ledger.adjustments.approve").post(
        f"{base}/adjusting-entries/{target}/void", json={"reason": "Typed twice"}, headers=HEADERS
    )
    assert voided.status_code == 200


def test_bodies_are_strict_and_a_red_close_answers_with_its_checks() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    owner = client(flow, "ledger.adjustments.prepare", "ledger.opening_balances", "ledger.close")
    one_line = {**ENTRY, "lines": ENTRY["lines"][:1]}
    both_sides = {
        **ENTRY,
        "lines": [{"account_code": "6050", "debit_cents": 1, "credit_cents": 1}] * 2,
    }
    for bad in (
        {**ENTRY, "extra": 1},
        {**ENTRY, "reason": ""},
        {**ENTRY, "entry_date": "31/01/2027"},
        one_line,
        both_sides,
        {**ENTRY, "lines": [{"account_code": "60", "debit_cents": 1}] * 2},
    ):
        assert owner.post(f"{base}/adjusting-entries", json=bad, headers=HEADERS).status_code == 422
    assert (
        owner.post(
            f"{base}/opening-balances", json={"first_year": 1990}, headers=HEADERS
        ).status_code
        == 422
    )
    flow.answer = {"closed": False, "checks": {"cash_counted": False, "books_check": True}}
    red = owner.post(f"{base}/periods/{uuid4()}/close", json={}, headers=HEADERS)
    assert red.status_code == 200 and red.json()["data"]["closed"] is False
    flow.answer = None
    for error, code in (
        (LedgerMoneyRefused("Nobody approves their own adjusting entry"), 403),
        (LedgerMoneyConflict("Months close in order: close the oldest open month first"), 409),
        (LedgerMoneyNotFound(), 404),
    ):
        flow.refuse = error
        answer = owner.post(f"{base}/periods/{uuid4()}/close", json={}, headers=HEADERS)
        assert answer.status_code == code
        if code != 404:
            assert answer.json()["error"]["message"] == str(error)
    flow.refuse = None


def test_reads_need_the_ledger_right_and_are_not_cached() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    period = uuid4()
    reader = client(flow, "ledger.read")
    for path, view in (
        ("/adjusting-entries", "adjusting-entries"),
        ("/opening-balances", "opening-balances"),
        ("/books-check", "books-check"),
        ("/periods", "periods"),
        (f"/periods/{period}/close-checks", "close-checks"),
    ):
        answer = reader.get(base + path)
        assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
        assert answer.json()["data"][0]["view"] == view
        assert client(flow, "expenses.request").get(base + path).status_code == 403
    assert reader.get(f"{base}/periods/{period}/close-checks").json()["data"][0]["target"] == str(
        period
    )


def test_part_two_changes_need_their_right_and_reach_the_database_in_its_shape() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    target, month, line = uuid4(), uuid4(), uuid4()
    rent: dict[str, Any] = {"account_code": "4010", "month_no": 1, "amount_cents": 300_000}
    budget = {"fiscal_year": 2027, "lines": [rent], "own_note": "My plan"}
    match = {
        "account_code": "1020",
        "period_id": str(month),
        "statement_balance_cents": -2_500,
        "lines": [{"line_id": str(line), "statement_date": "2027-01-31", "reference": "ABA 7"}],
    }
    for method, path, right, body in (
        ("post", f"/periods/{target}/month-end", "ledger.close", {}),
        (
            "post",
            f"/fixed-assets/{target}/life",
            "ledger.fixed_assets",
            {"years": 8, "reason": "Wears out fast"},
        ),
        ("post", "/bank-matches", "ledger.reconcile", match),
        ("post", "/budgets", "ledger.budgets.prepare", budget),
        (
            "post",
            f"/budgets/{target}/decision",
            "ledger.budgets.approve",
            {"approve": False, "note": "Repairs look low"},
        ),
    ):
        reader = client(flow, "ledger.read")
        assert reader.request(method, base + path, json=body, headers=HEADERS).status_code == 403
        holder = client(flow, right)
        assert holder.request(method, base + path, json=body).status_code == 403
        answer = holder.request(method, base + path, json=body, headers=HEADERS)
        assert answer.status_code in (200, 201), (path, answer.text)
    assert [write[0] for write in flow.writes] == [
        "run_month_end",
        "change_asset_life",
        "match_bank",
        "prepare_budget",
        "decide_budget",
    ]
    assert flow.writes[1][1:] == ({"years": 8, "reason": "Wears out fast"}, target)
    assert flow.writes[2][1] == {
        "account_code": "1020",
        "period_id": month,
        "statement_cents": -2_500,
        "items": [{"line_id": str(line), "statement_date": "2027-01-31", "reference": "ABA 7"}],
    }
    assert flow.writes[3][1] == {
        "fiscal_year": 2027,
        "lines": [{"account": "4010", "month_no": 1, "amount_cents": 300_000}],
        "own_note": "My plan",
    }
    owner = client(flow, "ledger.fixed_assets", "ledger.budgets.prepare", "ledger.reconcile")
    for path, bad in (
        (f"/fixed-assets/{target}/life", {"years": 0, "reason": "x"}),
        (f"/fixed-assets/{target}/life", {"years": 101, "reason": "x"}),
        (f"/fixed-assets/{target}/life", {"years": 5, "reason": ""}),
        ("/budgets", {**budget, "lines": []}),
        ("/budgets", {**budget, "lines": [{**rent, "month_no": 13}]}),
        ("/budgets", {**budget, "lines": [{**rent, "amount_cents": -1}]}),
        ("/bank-matches", {**match, "account_code": "BANK"}),
        ("/bank-matches", {**match, "lines": [{"line_id": "x"}]}),
    ):
        assert owner.post(base + path, json=bad, headers=HEADERS).status_code == 422, (path, bad)


def test_part_two_reads_need_the_ledger_right() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    month = uuid4()
    reader = client(flow, "ledger.read")
    for path, view in (
        ("/fixed-assets", "fixed-assets"),
        ("/bank-matches", "bank-matches"),
        ("/budgets", "budgets"),
        (f"/periods/{month}/bank-lines/1020", "bank-lines"),
    ):
        answer = reader.get(base + path)
        assert answer.status_code == 200 and answer.headers["Cache-Control"] == "private, no-store"
        assert answer.json()["data"][0]["view"] == view
        assert client(flow, "expenses.request").get(base + path).status_code == 403
    lines = reader.get(f"{base}/periods/{month}/bank-lines/1020").json()["data"][0]
    assert (lines["target"], lines["account"]) == (str(month), "1020")
    assert reader.get(f"{base}/periods/{month}/bank-lines/10x0").status_code == 422


def test_a_write_off_is_owner_only_and_names_one_line_or_one_late_charge() -> None:
    flow = InMemoryClose()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    settlement, invoice, line, charge = uuid4(), uuid4(), uuid4(), uuid4()
    body = {
        "final_settlement_id": str(settlement),
        "invoice_id": str(invoice),
        "invoice_line_id": str(line),
        "amount_cents": 2_500,
        "reason": "Left the country",
    }
    assert (
        client(flow, "ledger.read")
        .post(f"{base}/write-offs", json=body, headers=HEADERS)
        .status_code
        == 403
    )
    owner = client(flow, "ledger.write_off")
    assert owner.post(f"{base}/write-offs", json=body).status_code == 403
    assert owner.post(f"{base}/write-offs", json=body, headers=HEADERS).status_code == 201
    late = {
        "final_settlement_id": str(settlement),
        "late_payment_charge_id": str(charge),
        "amount_cents": 1_000,
        "reason": "Left the country",
    }
    assert owner.post(f"{base}/write-offs", json=late, headers=HEADERS).status_code == 201
    assert [write[1] for write in flow.writes] == [
        {
            "final_settlement_id": settlement,
            "target": {
                "invoice_id": str(invoice),
                "invoice_line_id": str(line),
                "amount_usd_cents": 2_500,
            },
            "reason": "Left the country",
        },
        {
            "final_settlement_id": settlement,
            "target": {"late_payment_charge_id": str(charge), "amount_usd_cents": 1_000},
            "reason": "Left the country",
        },
    ]
    without_line = {key: value for key, value in body.items() if key != "invoice_line_id"}
    for bad in (
        {**body, "late_payment_charge_id": str(charge)},
        without_line,
        {key: value for key, value in late.items() if key != "late_payment_charge_id"},
        {**body, "amount_cents": 0},
        {**body, "reason": ""},
    ):
        assert owner.post(f"{base}/write-offs", json=bad, headers=HEADERS).status_code == 422
    flow.refuse = LedgerMoneyNotFound()
    assert owner.post(f"{base}/write-offs", json=body, headers=HEADERS).status_code == 404
    flow.refuse = None
    reader = client(flow, "ledger.read")
    listed = reader.get(f"{base}/write-offs")
    assert listed.status_code == 200 and listed.json()["data"][0]["view"] == "write-offs"
    assert listed.headers["Cache-Control"] == "private, no-store"
