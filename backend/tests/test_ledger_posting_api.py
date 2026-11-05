"""Ledger "Needs check" and method accounts API (General Ledger phase 6 step 2).

Reading needs `ledger.read` (Owner and Manager, plan L1); setting a method's account needs
`ledger.accounts.manage` (Owner only) and the browser mutation checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.ledger_posting_api import (
    LedgerPostingInvalid,
    LedgerPostingNotFound,
    MethodAccount,
    PostingProblem,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=ledger-token",
    "X-CSRF-Token": "ledger-token",
}
CASH = uuid4()
AT = datetime(2027, 1, 5, 2, tzinfo=UTC)


@dataclass
class InMemoryPosting:
    property_id: UUID = field(default_factory=uuid4)
    accounts: dict[UUID, str] = field(default_factory=dict)
    riel: dict[UUID, str | None] = field(default_factory=dict)
    changes: list[tuple[str, UUID, str, date, str]] = field(default_factory=list)

    def _check(self, property_id: UUID) -> None:
        if property_id != self.property_id:
            raise LedgerPostingNotFound

    def needs_check(self, property_id: UUID) -> tuple[PostingProblem, ...]:
        self._check(property_id)
        if CASH in self.accounts:
            return ()
        return (
            PostingProblem(
                f"payment:{CASH}",
                "PAYMENT",
                CASH,
                date(2027, 1, 5),
                "No ledger account is set for the Payment Method Cash",
                AT,
                AT,
            ),
        )

    def method_accounts(self, property_id: UUID) -> tuple[MethodAccount, ...]:
        self._check(property_id)
        code = self.accounts.get(CASH)
        return (
            MethodAccount(
                "PAYMENT",
                CASH,
                "CASH",
                "Cash",
                code,
                "Cash on hand (USD)" if code else None,
                date(2027, 1, 1) if code else None,
                self.riel.get(CASH),
                "ABA Bank · KHR account" if self.riel.get(CASH) else None,
            ),
        )

    def set_method_account(
        self,
        property_id: UUID,
        *,
        kind: str,
        method_id: UUID,
        account_code: str,
        effective_from: date,
        actor_id: str,
        riel_account_code: str | None = None,
    ) -> None:
        self._check(property_id)
        if method_id != CASH:
            raise LedgerPostingNotFound
        if account_code != "1010":
            raise LedgerPostingInvalid("A method goes to an active cash or bank account")
        if riel_account_code not in (None, "1011", "1021"):
            raise LedgerPostingInvalid(
                "The riel account is an active riel cash or riel bank account"
            )
        self.accounts[method_id] = account_code
        self.riel[method_id] = riel_account_code
        self.changes.append((kind, method_id, account_code, effective_from, actor_id))


def client(flow: InMemoryPosting, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, ledger_posting_flow=flow))


def test_needs_check_and_method_accounts_need_ledger_read() -> None:
    flow = InMemoryPosting()
    base = f"/api/v1/properties/{flow.property_id}/ledger"
    for path in ("needs-check", "method-accounts"):
        assert client(flow).get(f"{base}/{path}").status_code == 403
        assert client(flow, "configuration.read").get(f"{base}/{path}").status_code == 403
    reader = client(flow, "ledger.read")
    waiting = reader.get(f"{base}/needs-check")
    assert waiting.status_code == 200
    assert waiting.headers["Cache-Control"] == "private, no-store"
    assert waiting.json()["meta"]["count"] == 1
    [row] = waiting.json()["data"]
    assert row["posting_key"] == f"payment:{CASH}" and row["event_date"] == "2027-01-05"
    [method] = reader.get(f"{base}/method-accounts").json()["data"]
    assert method == {
        "kind": "PAYMENT",
        "method_id": str(CASH),
        "code": "CASH",
        "name": "Cash",
        "account_code": None,
        "account_name": None,
        "effective_from": None,
        "riel_account_code": None,
        "riel_account_name": None,
    }
    other = reader.get(f"/api/v1/properties/{uuid4()}/ledger/needs-check")
    assert other.status_code == 403


def test_only_ledger_accounts_manage_sets_a_method_account() -> None:
    flow = InMemoryPosting()
    url = f"/api/v1/properties/{flow.property_id}/ledger/method-accounts"
    body = {
        "kind": "PAYMENT",
        "method_id": str(CASH),
        "account_code": "1010",
        "effective_from": "2027-01-01",
    }
    manager = client(flow, "ledger.read")
    assert manager.put(url, json=body, headers=HEADERS).status_code == 403
    owner = client(flow, "ledger.read", "ledger.accounts.manage")
    assert owner.put(url, json=body).status_code == 403
    answer = owner.put(url, json=body, headers=HEADERS)
    assert answer.status_code == 200
    assert answer.json()["data"][0]["account_code"] == "1010"
    assert flow.changes[0][:4] == ("PAYMENT", CASH, "1010", date(2027, 1, 1))
    assert owner.get(f"{url[: -len('method-accounts')]}needs-check").json()["data"] == []
    assert owner.put(url, json={**body, "account_code": "4010"}, headers=HEADERS).status_code == (
        422
    )
    assert owner.put(
        url, json={**body, "method_id": str(uuid4())}, headers=HEADERS
    ).status_code == (404)
    for bad in (
        {**body, "kind": "OTHER"},
        {**body, "account_code": "10"},
        {**body, "effective_from": "01/01/2027"},
        {**body, "extra": 1},
    ):
        assert owner.put(url, json=bad, headers=HEADERS).status_code == 422, bad


def test_a_payment_method_takes_a_riel_account() -> None:
    flow = InMemoryPosting()
    url = f"/api/v1/properties/{flow.property_id}/ledger/method-accounts"
    body = {
        "kind": "PAYMENT",
        "method_id": str(CASH),
        "account_code": "1010",
        "effective_from": "2027-01-01",
        "riel_account_code": "1021",
    }
    owner = client(flow, "ledger.read", "ledger.accounts.manage")
    answer = owner.put(url, json=body, headers=HEADERS)
    assert answer.status_code == 200
    [method] = answer.json()["data"]
    assert method["riel_account_code"] == "1021"
    assert method["riel_account_name"] == "ABA Bank · KHR account"
    refused = owner.put(url, json={**body, "riel_account_code": "1020"}, headers=HEADERS)
    assert refused.status_code == 422
    assert owner.put(
        url, json={**body, "riel_account_code": "21"}, headers=HEADERS
    ).status_code == (422)
    cleared = owner.put(url, json={**body, "riel_account_code": None}, headers=HEADERS)
    assert cleared.json()["data"][0]["riel_account_code"] is None
