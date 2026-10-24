"""The walk-in Security Deposit and Deposit receipt routes (V1-056 slice 11c-4)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from httpx import Response

from property_rental.deposit import (
    CreateLeaseSecurityDepositCommand,
    DepositConflictError,
    DepositIdempotencyKeyReused,
    DepositInvalidError,
    DepositNotFoundError,
    RecordDepositReceiptCommand,
)
from property_rental.deposit_api import DEPOSIT_RECEIPT_REFUSALS, SECURITY_DEPOSIT_REFUSALS
from test_deposit_api import InMemoryDepositFlow, actor, client, mutation_headers, snapshot

SECURITY = "security"
CONFLICT = DepositConflictError
RECEIPT = "receipt"
CAPABILITY = {SECURITY: "deposits.manage", RECEIPT: "payments.allocate"}
TABLES = {SECURITY: SECURITY_DEPOSIT_REFUSALS, RECEIPT: DEPOSIT_RECEIPT_REFUSALS}


def _body(route: str) -> dict[str, object]:
    if route == SECURITY:
        return {"deposit_id": str(uuid4()), "required_usd_cents": 60_000, "reason": "Lease terms"}
    return {
        "receipt_id": str(uuid4()),
        "payment_id": str(uuid4()),
        "amount_usd_cents": 10_000,
        "reason": "Second part of the Deposit",
    }


def _post(
    flow: InMemoryDepositFlow,
    route: str,
    *,
    body: dict[str, object] | None = None,
    capabilities: tuple[str, ...] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    granted = (CAPABILITY[route],) if capabilities is None else capabilities
    path = (
        f"/api/v1/leases/{uuid4()}/security-deposit"
        if route == SECURITY
        else f"/api/v1/deposits/{flow.value.deposit_id}/receipts"
    )
    answer: Response = client(flow, actor(flow.value.property_id, *granted)).post(
        path,
        json=_body(route) if body is None else body,
        headers=mutation_headers() if headers is None else headers,
    )
    return answer


def _last(flow: InMemoryDepositFlow) -> object:
    return flow.last_command


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("Deposit command is refused")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


def test_a_walk_in_security_deposit_is_created_with_deposits_manage_and_csrf() -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    for capabilities in (("deposits.read",), ("payments.allocate",)):
        assert _post(flow, SECURITY, capabilities=capabilities).status_code == 404
    other_property = client(flow, actor(uuid4(), "deposits.manage")).post(
        f"/api/v1/leases/{uuid4()}/security-deposit",
        json=_body(SECURITY),
        headers=mutation_headers(),
    )
    assert other_property.status_code == 404
    no_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _post(flow, SECURITY, headers=no_csrf).status_code == 403
    assert flow.last_command is None
    body = _body(SECURITY)
    created = _post(flow, SECURITY, body=body)
    assert created.status_code == 201
    command = _last(flow)
    assert isinstance(command, CreateLeaseSecurityDepositCommand)
    assert (str(command.deposit_id), command.required_usd_cents, command.reason) == (
        body["deposit_id"],
        60_000,
        "Lease terms",
    )
    assert created.headers["location"] == f"/api/v1/deposits/{body['deposit_id']}"
    assert created.headers["cache-control"] == "private, no-store"
    assert created.json()["data"]["deposit_id"] == body["deposit_id"]
    assert created.json()["data"]["deposit_type"] == "SECURITY"


def test_a_deposit_receipt_needs_payments_allocate_and_answers_only_the_receipt() -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    for capabilities in (("deposits.read",), ("deposits.manage",)):
        assert _post(flow, RECEIPT, capabilities=capabilities).status_code == 404
    no_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _post(flow, RECEIPT, headers=no_csrf).status_code == 403
    assert flow.last_command is None
    body = _body(RECEIPT)
    recorded = _post(flow, RECEIPT, body=body)
    assert recorded.status_code == 201
    command = _last(flow)
    assert isinstance(command, RecordDepositReceiptCommand)
    assert (str(command.receipt_id), str(command.payment_id), command.deposit_id) == (
        body["receipt_id"],
        body["payment_id"],
        flow.value.deposit_id,
    )
    # No Location: a holder of payments.allocate alone may not read the Deposit.
    assert "location" not in recorded.headers
    data = recorded.json()["data"]
    assert set(data) == {
        "deposit_receipt_id",
        "deposit_id",
        "payment_id",
        "amount_usd_cents",
        "occurred_at",
        "payment_available_usd_cents",
        "required_usd_cents",
        "held_refundable_usd_cents",
        "outstanding_required_usd_cents",
        "version",
    }
    assert (data["deposit_receipt_id"], data["amount_usd_cents"]) == (body["receipt_id"], 10_000)
    assert data["held_refundable_usd_cents"] == flow.value.held_refundable_usd_cents


@pytest.mark.parametrize("route", [SECURITY, RECEIPT])
@pytest.mark.parametrize(
    "change",
    [
        {"reason": ""},
        {"reason": "x" * 1001},
        {"unexpected": 1},
        {"amount": 0},
        {"amount": -5},
        {"amount": 2**63},
        {"amount": 1.5},
    ],
)
def test_bad_input_answers_422_before_any_command(route: str, change: dict[str, object]) -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    body = _body(route)
    amount = "required_usd_cents" if route == SECURITY else "amount_usd_cents"
    body.update({amount if key == "amount" else key: value for key, value in change.items()})
    assert _post(flow, route, body=body).status_code == 422
    assert flow.last_command is None


# The service error each database SQLSTATE becomes: 55000 and 22023 invalid, P5S01 and 23505
# conflict, P0002 not found (the service's own mapping).
ERRORS: dict[str, type[Exception]] = {
    "Signed Lease was not found": DepositNotFoundError,
    "Payment was not found": DepositNotFoundError,
    "A Deposit holds at most one active receipt from each Payment": DepositConflictError,
    "A closed Final Settlement changes only through a post-settlement correction": (
        DepositConflictError
    ),
}


@pytest.mark.parametrize(
    ("route", "message"),
    [(route, message) for route, table in TABLES.items() for message in table],
)
def test_each_named_deposit_refusal_answers_its_own_code(route: str, message: str) -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    flow.error = _refused(message, ERRORS.get(message, DepositInvalidError))
    answer = _post(flow, route)
    refusal = TABLES[route][message]
    error = answer.json()["error"]
    assert (answer.status_code, error["code"]) == (refusal.status_code, refusal.code)
    assert error["rule_ids"] == list(refusal.rule_ids)
    assert error["fields"] == list(refusal.fields)
    assert message not in answer.text


def test_the_named_codes_are_pinned() -> None:
    assert {message: value.code for message, value in SECURITY_DEPOSIT_REFUSALS.items()} == {
        "Signed Lease was not found": "DEPOSIT_SECURITY_LEASE_NOT_SIGNED",
        "Only a walk-in Lease's Security Deposit is created here": "DEPOSIT_SECURITY_NOT_WALK_IN",
        "A renewal Lease's Security Deposit is not created here": "DEPOSIT_SECURITY_RENEWAL",
        "The Lease already has a Security Deposit": "DEPOSIT_SECURITY_ALREADY_EXISTS",
        "A closed Final Settlement changes only through a post-settlement correction": (
            "FINAL_SETTLEMENT_CLOSED"
        ),
    }
    assert {value.code for value in DEPOSIT_RECEIPT_REFUSALS.values()} == {
        "DEPOSIT_RECEIPT_PAYMENT_NOT_FOUND",
        "DEPOSIT_RECEIPT_LEASE_NOT_SIGNED",
        "DEPOSIT_RECEIPT_RESERVATION_NOT_ACTIVE",
        "DEPOSIT_RECEIPT_GROUND_KEEPS_DEPOSIT",
        "DEPOSIT_RECEIPT_FORFEITURE_ACTIVE",
        "DEPOSIT_RECEIPT_PAYMENT_OWED",
        "DEPOSIT_RECEIPT_PAYMENT_INELIGIBLE",
        "DEPOSIT_RECEIPT_OVER_PAYMENT",
        "DEPOSIT_RECEIPT_PAYMENT_ALREADY_USED",
        "DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED",
        "DEPOSIT_RECEIPT_OVER_REQUIRED",
        "FINAL_SETTLEMENT_CLOSED",
    }
    assert {
        message for message, value in DEPOSIT_RECEIPT_REFUSALS.items() if value.status_code == 422
    } == {
        "Payment was not found",
        "Deposit receipt Payment source is ineligible",
        "Deposit receipt exceeds Payment availability",
        "Deposit receipt does not preserve the accepted or required amount",
        "Pet Deposit receipt exceeds its approved liability",
    }
    for message in ("Payment was not found", "Deposit receipt Payment source is ineligible"):
        assert DEPOSIT_RECEIPT_REFUSALS[message].fields == ("payment_id",)
    assert (
        DEPOSIT_RECEIPT_REFUSALS[
            "Deposit receipt does not preserve the accepted or required amount"
        ].code,
        DEPOSIT_RECEIPT_REFUSALS["Pet Deposit receipt exceeds its approved liability"].code,
    ) == ("DEPOSIT_RECEIPT_AMOUNT_NOT_ALLOWED", "DEPOSIT_RECEIPT_OVER_REQUIRED")
    assert DEPOSIT_RECEIPT_REFUSALS["Deposit receipt exceeds Payment availability"].fields == (
        "amount_usd_cents",
    )


@pytest.mark.parametrize("route", [SECURITY, RECEIPT])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (_refused("Security Deposit evidence is invalid", DepositInvalidError), 422),
        (_refused("Deposit receipt evidence is invalid", DepositInvalidError), 422),
        (_refused("Deposit audit identity conflicts with existing evidence", CONFLICT), 409),
        (DepositConflictError("Deposit command conflicted"), 409),
        (_refused("Deposit was not found", DepositNotFoundError), 404),
    ],
)
def test_unnamed_refusals_keep_their_plain_answers(
    route: str, error: Exception, status: int
) -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    flow.error = error
    answer = _post(flow, route)
    assert answer.status_code == status
    assert "evidence" not in answer.text and "identity" not in answer.text


@pytest.mark.parametrize("route", [SECURITY, RECEIPT])
def test_a_reused_key_answers_idempotency_key_reused(route: str) -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    flow.error = _refused(
        "Deposit idempotency key conflicts with another request", DepositIdempotencyKeyReused
    )
    answer = _post(flow, route)
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


def test_a_receipt_for_a_deposit_of_another_property_is_hidden() -> None:
    flow = InMemoryDepositFlow(snapshot(uuid4()))
    answer = client(flow, actor(uuid4(), "payments.allocate")).post(
        f"/api/v1/deposits/{flow.value.deposit_id}/receipts",
        json=_body(RECEIPT),
        headers=mutation_headers(),
    )
    assert answer.status_code == 404
    assert flow.last_command is None
