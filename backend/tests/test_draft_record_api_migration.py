"""The Deposit forfeiture, Deposit correction and returned-Payment draft routes on real
PostgreSQL (V1-056 slice 11c-3): each draft is recorded over HTTP, confirmed through the shared
draft route, and a named refusal answers its own code."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import Response

from test_credit_migration import actor, source
from test_credit_refund_api_migration import headers
from test_deposit_receipt_reversal_draft_migration import available
from test_lease_deposit_forfeiture_migration import forfeited, held
from test_move_in_migration import migrated_database_url  # noqa: F401
from test_payment_api_migration import api
from test_payment_move_migration import value
from test_payment_reversal_context_migration import deposit_source
from test_termination_deposit_migration import setup_deposits
from test_termination_deposit_migration import terminate as terminate_voluntary

APPROVE = "financial.approve"


def _post(client: TestClient, human: UUID, path: str, body: dict[str, str]) -> Response:
    answer: Response = client.post(path, json=body, headers=headers(human))
    return answer


def _confirm(client: TestClient, human: UUID, prop: UUID, answer: Response) -> dict[str, Any]:
    assert answer.status_code == 201, answer.text
    draft = cast(dict[str, Any], answer.json()["data"])
    assert draft["state"] == "PENDING"
    confirmed = client.post(
        f"/api/v1/properties/{prop}/financial-drafts/{draft['draft_id']}/confirm",
        json={},
        headers=headers(human),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["draft"]["state"] == "CONFIRMED"
    return cast(dict[str, Any], confirmed.json()["data"]["result"])


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json()["error"]["code"])


def test_a_lease_forfeiture_and_its_reversal_are_drafts_recorded_over_http(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    human, prop, lease, security, _pet, day = setup_deposits(url)
    client = api(actor(human, prop, "deposits.dispose", "deposits.correct", APPROVE))
    path = f"/api/v1/properties/{prop}/deposits/{security}/forfeiture-drafts"
    body = {"disposition_id": str(uuid4()), "reason": "Left before the End Date"}
    assert _code(_post(client, human, path, body)) == (
        409,
        "DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED",
    )
    terminate_voluntary(url, human, prop, lease, day)
    amount = held(url, security)
    key = uuid4()
    recorded = client.post(path, json=body, headers=headers(human, key))
    assert recorded.status_code == 201, recorded.text
    payload = recorded.json()["data"]["payload"]
    assert (payload["variant"], payload["amount_usd_cents"], payload["governing_rule"]) == (
        "LEASE_FORFEITURE",
        amount,
        "BR-DEP-023",
    )
    # The same key and form answer the same draft; nothing changes before confirmation.
    again = client.post(path, json=body, headers=headers(human, key))
    assert again.status_code == 201 and again.json()["data"] == recorded.json()["data"]
    assert held(url, security) == amount
    other = {"disposition_id": str(uuid4()), "reason": "Left before the End Date"}
    assert _code(_post(client, human, path, other)) == (409, "DEPOSIT_FORFEITURE_DRAFT_WAITING")
    _confirm(client, human, prop, recorded)
    assert (held(url, security), forfeited(url, security)) == (0, [(amount, "BR-DEP-023")])

    reverse = (
        f"/api/v1/properties/{prop}/deposit-dispositions/{body['disposition_id']}/reversal-drafts"
    )
    correction = {
        "reversal_id": str(uuid4()),
        "reason": "The Lease was ended by mistake",
        "evidence_reference": "Manager note 24/10",
    }
    _confirm(client, human, prop, _post(client, human, reverse, correction))
    assert held(url, security) == amount
    twice = {**correction, "reversal_id": str(uuid4())}
    assert _code(_post(client, human, reverse, twice)) == (
        409,
        "DEPOSIT_FORFEITURE_ALREADY_REVERSED",
    )


def test_a_deposit_receipt_reversal_is_a_draft_recorded_over_http(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    service, _staff, _lease, deposit, payment, receipts = deposit_source(url)
    prop, human = service.property_id, service.actor_id
    client = api(actor(human, prop, "deposits.correct", APPROVE))
    path = f"/api/v1/properties/{prop}/deposit-receipts/{receipts[0]}/reversal-drafts"
    first = {"reversal_id": str(uuid4()), "reason": "The transfer came back"}
    recorded = _post(client, human, path, first)
    second = {"reversal_id": str(uuid4()), "reason": "The transfer came back"}
    assert _code(_post(client, human, path, second)) == (409, "DEPOSIT_DRAFT_WAITING")
    before = held(url, deposit), available(url, payment)
    _confirm(client, human, prop, recorded)
    assert (held(url, deposit), available(url, payment)) == (before[0] - 10_000, before[1] + 10_000)
    assert _code(_post(client, human, path, second)) == (409, "DEPOSIT_RECEIPT_ALREADY_REVERSED")
    # The other receipt cannot take the reversal id the first draft chose.
    reused = f"/api/v1/properties/{prop}/deposit-receipts/{receipts[1]}/reversal-drafts"
    assert _code(_post(client, human, reused, first)) == (409, "DRAFT_RECORD_ID_IN_USE")


def test_a_returned_payment_is_a_draft_recorded_over_http(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    human, prop, _customer, payment = source(url)
    client = api(actor(human, prop, "payments.reverse", APPROVE))
    path = f"/api/v1/properties/{prop}/payments/{payment}/return-drafts"
    body = {"reason": "The transfer came back", "evidence_reference": "ABA return notice 4471"}
    recorded = _post(client, human, path, body)
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["data"]["payload"]["payment_id"] == str(payment)
    assert _code(_post(client, human, path, body)) == (409, "PAYMENT_RETURN_DRAFT_WAITING")
    result = _confirm(client, human, prop, recorded)
    assert "transaction_id" not in str(result)
    assert value(url, "SELECT status FROM app.payments WHERE id=%s", payment) == "REVERSED"
    assert _code(_post(client, human, path, body)) == (409, "PAYMENT_RETURN_NOT_RECEIVED")
    # Without payments.reverse the Payment's Property is hidden.
    reader = api(actor(human, prop, "payments.read", APPROVE))
    assert _post(reader, human, path, body).status_code == 404
