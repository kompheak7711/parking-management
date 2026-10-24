"""The walk-in Security Deposit and Deposit receipt routes on real PostgreSQL (V1-056 slice
11c-4): the create and the receipts go through HTTP, and each named refusal answers its own code."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from payment_test_support import seed_payment
from test_credit_migration import actor
from test_deposit_receipt_record_migration import other_customer, payment
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_migration import held
from test_invoice import mutation_headers
from test_lease_security_deposit_migration import expire, security_deposits, walk_in_lease
from test_lease_signing_reservation_migration import reserved_unit, signed
from test_move_in_migration import migrated_database_url  # noqa: F401
from test_payment_api_migration import api
from test_reservation_lifecycle_migration import expired_reservation
from test_settlement_pet_receipt_link_migration import closed, pet_lease_case
from test_unpaid_initial_termination_migration import signed_with_initial

MANAGE = "deposits.manage"
ALLOCATE = "payments.allocate"


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json()["error"]["code"])


def _receipt(
    client: TestClient,
    deposit: UUID,
    paid_by: UUID,
    amount: int,
    *,
    key: UUID | None = None,
    receipt_id: UUID | None = None,
) -> Response:
    answer: Response = client.post(
        f"/api/v1/deposits/{deposit}/receipts",
        json={
            "receipt_id": str(receipt_id or uuid4()),
            "payment_id": str(paid_by),
            "amount_usd_cents": amount,
            "reason": "Deposit money received at the office",
        },
        headers=mutation_headers(key=key),
    )
    return answer


def test_a_walk_in_security_deposit_is_created_and_takes_receipts_over_http(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case: dict[str, Any] = walk_in_lease(url)
    human, prop, lease = case["human"], case["prop"], case["lease"]
    client = api(actor(human, prop, MANAGE, ALLOCATE))
    path = f"/api/v1/leases/{lease}/security-deposit"
    body = {"deposit_id": str(uuid4()), "required_usd_cents": 30_000, "reason": "Lease terms"}
    key = uuid4()
    created = client.post(path, json=body, headers=mutation_headers(key=key))
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert (data["deposit_id"], data["deposit_type"], data["lease_id"]) == (
        body["deposit_id"],
        "SECURITY",
        str(lease),
    )
    assert (data["required_usd_cents"], data["outstanding_required_usd_cents"]) == (30_000, 30_000)
    assert created.headers["location"] == f"/api/v1/deposits/{body['deposit_id']}"
    # The same key and form answer the same Deposit; another create is refused by name.
    again = client.post(path, json=body, headers=mutation_headers(key=key))
    assert again.status_code == 201 and again.json()["data"] == data
    other = {**body, "deposit_id": str(uuid4())}
    assert _code(client.post(path, json=other, headers=mutation_headers())) == (
        409,
        "DEPOSIT_SECURITY_ALREADY_EXISTS",
    )
    assert security_deposits(url, lease) == 1

    deposit = UUID(str(body["deposit_id"]))
    first = payment(url, human, deposit, 20_000)
    key, receipt_id = uuid4(), uuid4()
    recorded = _receipt(client, deposit, first, 5_000, key=key, receipt_id=receipt_id)
    assert recorded.status_code == 201, recorded.text
    # The same key and form answer the same receipt; another amount with that key is refused.
    replay = _receipt(client, deposit, first, 5_000, key=key, receipt_id=receipt_id)
    assert replay.status_code == 201 and replay.json()["data"] == recorded.json()["data"]
    assert _code(_receipt(client, deposit, first, 4_000, key=key, receipt_id=receipt_id)) == (
        409,
        "IDEMPOTENCY_KEY_REUSED",
    )
    receipt = recorded.json()["data"]
    assert (
        receipt["payment_id"],
        receipt["amount_usd_cents"],
        receipt["payment_available_usd_cents"],
        receipt["held_refundable_usd_cents"],
        receipt["outstanding_required_usd_cents"],
    ) == (str(first), 5_000, 15_000, 5_000, 25_000)
    assert "customer_id" not in receipt
    assert held(url, deposit) == 5_000
    assert _code(_receipt(client, deposit, first, 5_000)) == (
        409,
        "DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED",
    )
    small = payment(url, human, deposit, 1_000)
    assert _code(_receipt(client, deposit, small, 1_500)) == (422, "DEPOSIT_RECEIPT_OVER_PAYMENT")
    large = payment(url, human, deposit, 30_000)
    assert _code(_receipt(client, deposit, large, 25_001)) == (
        422,
        "DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED",
    )
    assert _code(_receipt(client, deposit, uuid4(), 1_000)) == (
        422,
        "DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND",
    )
    with psycopg.connect(url) as connection:
        foreign = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=other_customer(url, human),
            amount=1_000,
        )
    assert _code(_receipt(client, deposit, foreign, 1_000)) == (
        422,
        "DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE",
    )
    rest = _receipt(client, deposit, large, 25_000)
    assert rest.status_code == 201, rest.text
    assert rest.json()["data"]["outstanding_required_usd_cents"] == 0
    assert held(url, deposit) == 30_000
    # Without payments.allocate the Deposit is hidden; nothing is written.
    manager = api(actor(human, prop, MANAGE, "deposits.read"))
    assert _receipt(manager, deposit, small, 500).status_code == 404
    assert held(url, deposit) == 30_000


def test_a_lease_signed_from_a_reservation_keeps_its_reservation_security_deposit(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    human, prop, unit, customer, reservation, _ = reserved_unit(url)
    command, _ = signed(url, human, prop, unit, customer, reservation)
    client = api(actor(human, prop, MANAGE))
    body = {"deposit_id": str(uuid4()), "required_usd_cents": 30_000, "reason": "Lease terms"}
    answer = client.post(
        f"/api/v1/leases/{command.lease_id}/security-deposit",
        json=body,
        headers=mutation_headers(),
    )
    assert _code(answer) == (409, "DEPOSIT_SECURITY_NOT_WALK_IN")
    assert "is created here" not in answer.text
    assert security_deposits(url, command.lease_id) == 1
    assert (
        client.post(
            f"/api/v1/leases/{uuid4()}/security-deposit", json=body, headers=mutation_headers()
        ).status_code
        == 404
    )


def test_the_named_receipt_refusals_come_from_the_database_over_http(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Review round 1: each business-state refusal of the receipt reaches staff by name from the
    real database: an expired Reservation, a Payment confirmed for an Invoice that is still owed,
    a Lease whose termination ground keeps the Deposit, an active forfeiture and a closed Final
    Settlement. Nothing is written."""
    url = migrated_database_url
    with psycopg.connect(url) as setup:
        human, prop, _, _, reservation, reserved = expired_reservation(setup)
        setup.commit()
    before = held(url, reserved)
    client = api(actor(human, prop, ALLOCATE))
    assert _code(_receipt(client, reserved, payment(url, human, reserved, 5_000), 5_000)) == (
        409,
        "DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE",
    )
    assert held(url, reserved) == before
    # The expiry worker tests count Reservations past their date; expire this one (round 2).
    expire(human, prop, reservation)

    source = signed_with_initial(url, this_month(url))
    human, prop, security = source["actor"], source["property"], source["deposit"]
    with psycopg.connect(url) as connection:
        named = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=source["customer"],
            amount=10_000,
            invoice_id=source["invoice"],
        )
    before = held(url, security)
    client = api(actor(human, prop, ALLOCATE))
    assert _code(_receipt(client, security, named, 10_000)) == (
        409,
        "DEPOSIT_RECEIPT_PAYMENT_OWED",
    )
    assert held(url, security) == before

    case = pet_lease_case(url)
    human, prop, pet, security = case["human"], case["prop"], case["pet"], case["security"]
    client = api(actor(human, prop, ALLOCATE))
    pet_payment = payment(url, human, pet, 5_000)
    assert _code(_receipt(client, pet, pet_payment, 5_000)) == (
        409,
        "DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT",
    )
    before = held(url, security)
    assert _code(_receipt(client, security, payment(url, human, security, 5_000), 5_000)) == (
        409,
        "DEPOSIT_RECEIPT_FORFEITURE_ACTIVE",
    )
    assert held(url, security) == before
    closed(case)
    assert _code(_receipt(client, pet, pet_payment, 5_000)) == (409, "FINAL_SETTLEMENT_CLOSED")
    assert held(url, pet) == 0
