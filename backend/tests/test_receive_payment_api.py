"""Receive payment in one step over HTTP (V1-058 R5c-1; DL-077)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import Response

from property_rental.identity import AuthenticatedActor
from property_rental.khr_payment_confirmation import ConfirmKhrPaymentCommand
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationUnavailableError,
)
from property_rental.receive_payment import (
    PaysTarget,
    ReceivePaymentChanged,
    ReceivePaymentCommand,
    ReceivePaymentLeftWhileOwing,
    ReceivePaymentTooMany,
    _database_error,
)
from test_invoice import actor, mutation_headers
from test_payment_api import Flow, api, payload


@dataclass
class ReceiveFlow(Flow):
    received: list[tuple[UUID, ReceivePaymentCommand, AuthenticatedActor]] = field(
        default_factory=list
    )

    def receive(
        self, property_id: UUID, command: ReceivePaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.received.append((property_id, command, actor))
        self.fail()
        return {**self.value(), "allocations": [], "left_usd_cents": 0}

    def payable(
        self, property_id: UUID, customer_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((property_id, customer_id, actor))
        self.fail()
        return {"customer_id": str(customer_id), "items": []}


def receive(flow: ReceiveFlow, who: AuthenticatedActor | None, body: dict[str, object]) -> Response:
    result = api(flow, who).post(
        f"/api/v1/properties/{flow.property_id}/payments/receive",
        json=body,
        headers=mutation_headers(),
    )
    return cast(Response, result)


def body(currency: str = "USD", **pays: object) -> dict[str, object]:
    return {**payload(currency), "pays": pays or {"mode": "OLDEST_FIRST", "targets": []}}


@pytest.mark.parametrize("currency", ["USD", "KHR"])
def test_receive_payment_sends_the_payment_and_the_ticks_as_one_command(currency: str) -> None:
    flow = ReceiveFlow()
    who = actor(flow.property_id, "payments.record", "payments.allocate")
    invoice, charge = uuid4(), uuid4()
    ticks = [
        {"invoice_id": str(invoice), "amount_usd_cents": 80_000},
        {"late_payment_charge_id": str(charge), "amount_usd_cents": 8_000},
    ]
    result = receive(flow, who, body(currency, mode="OLDEST_FIRST", targets=ticks))
    assert result.status_code == 201
    assert result.headers["Location"] == f"/api/v1/payments/{flow.payment_id}"
    assert result.json()["data"]["left_usd_cents"] == 0
    prop, command, actual = flow.received[0]
    assert prop == flow.property_id and actual is who
    assert isinstance(
        command.confirmation,
        ConfirmUsdPaymentCommand if currency == "USD" else ConfirmKhrPaymentCommand,
    )
    assert command.mode == "OLDEST_FIRST"
    assert command.targets == (
        PaysTarget("INVOICE", invoice, 80_000),
        PaysTarget("LATE_PAYMENT_CHARGE", charge, 8_000),
    )
    assert command.pays() == {"mode": "OLDEST_FIRST", "targets": ticks}


def test_receive_payment_needs_record_and_allocate_only_when_something_is_ticked() -> None:
    flow = ReceiveFlow()
    ticked = body(mode="NAMED", targets=[{"invoice_id": str(uuid4()), "amount_usd_cents": 100}])
    record_only = actor(flow.property_id, "payments.record")
    assert receive(flow, record_only, ticked).status_code == 403
    assert receive(flow, actor(flow.property_id, "payments.allocate"), body()).status_code == 403
    assert receive(flow, None, body()).status_code == 401
    assert not flow.received
    # Nothing owed: the money waits on the Receipt, so recording is enough.
    assert receive(flow, record_only, body()).status_code == 201


@pytest.mark.parametrize(
    "pays",
    [
        {"mode": "NAMED", "targets": []},
        {"mode": "LATER", "targets": []},
        {"mode": "OLDEST_FIRST"},
        {"mode": "OLDEST_FIRST", "targets": [], "keep": "credit"},
        {"mode": "NAMED", "targets": [{"amount_usd_cents": 100}]},
        {
            "mode": "NAMED",
            "targets": [
                {
                    "invoice_id": str(uuid4()),
                    "late_payment_charge_id": str(uuid4()),
                    "amount_usd_cents": 100,
                }
            ],
        },
        {"mode": "NAMED", "targets": [{"invoice_id": str(uuid4()), "amount_usd_cents": 0}]},
        {"mode": "NAMED", "targets": [{"invoice_id": str(uuid4()), "amount_usd_cents": "1"}]},
        {"mode": "NAMED", "targets": [{"invoice_id": str(uuid4()), "amount_usd_cents": 1.5}]},
        {
            "mode": "NAMED",
            "targets": [{"invoice_id": str(UUID(int=7)), "amount_usd_cents": 1}] * 2,
        },
        {
            "mode": "NAMED",
            "targets": [{"invoice_id": str(uuid4()), "amount_usd_cents": 1} for _ in range(101)],
        },
    ],
)
def test_receive_payment_refuses_unclear_ticks_before_anything_is_saved(
    pays: dict[str, object],
) -> None:
    flow = ReceiveFlow()
    who = actor(flow.property_id, "payments.record", "payments.allocate")
    assert receive(flow, who, {**payload(), "pays": pays}).status_code == 422
    assert not flow.received


def test_receive_payment_without_ticks_field_or_csrf_is_refused() -> None:
    flow = ReceiveFlow()
    who = actor(flow.property_id, "payments.record", "payments.allocate")
    assert receive(flow, who, payload()).status_code == 422
    headers = {key: value for key, value in mutation_headers().items() if key != "X-CSRF-Token"}
    result = api(flow, who).post(
        f"/api/v1/properties/{flow.property_id}/payments/receive", json=body(), headers=headers
    )
    assert result.status_code == 403 and not flow.received


@pytest.mark.parametrize(
    "error,code",
    [
        (ReceivePaymentChanged, "RECEIVE_PAYMENT_CHANGED"),
        (ReceivePaymentLeftWhileOwing, "RECEIVE_PAYMENT_LEFT_WHILE_OWING"),
        (ReceivePaymentTooMany, "RECEIVE_PAYMENT_TOO_MANY"),
        (PaymentConfirmationKeyReused, "IDEMPOTENCY_KEY_REUSED"),
    ],
)
def test_receive_payment_refusals_name_what_the_screen_explains(
    error: type[Exception], code: str
) -> None:
    flow = ReceiveFlow(error=error("private SQL evidence"))
    who = actor(flow.property_id, "payments.record", "payments.allocate")
    result = receive(flow, who, body())
    assert result.status_code == 409 and result.json()["error"]["code"] == code
    assert "private SQL" not in result.text
    assert result.json()["meta"]["request_id"] == result.headers["X-Request-ID"]


def test_the_payable_list_needs_recording_and_one_customer() -> None:
    flow = ReceiveFlow()
    customer = uuid4()
    path = f"/api/v1/properties/{flow.property_id}/payments/payable"
    allowed = api(flow, actor(flow.property_id, "payments.record"))
    result = allowed.get(path, params={"customer_id": str(customer)})
    assert result.status_code == 200
    assert result.json()["data"] == {"customer_id": str(customer), "items": []}
    assert flow.calls[-1][:2] == (flow.property_id, customer)
    before = len(flow.calls)
    assert allowed.get(path).status_code == 422
    assert allowed.get(path, params={"customer_id": str(customer), "x": "1"}).status_code == 400
    denied = api(flow, actor(flow.property_id, "invoices.read"))
    assert denied.get(path, params={"customer_id": str(customer)}).status_code == 403
    assert len(flow.calls) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("payment_scope_kind", "THIRD_PARTY_IDENTIFIED"),
        ("identified_invoice_id", str(uuid4())),
        ("identified_late_payment_charge_id", str(uuid4())),
    ],
)
def test_receive_payment_takes_only_the_payer_s_own_money(field: str, value: str) -> None:
    flow = ReceiveFlow()
    who = actor(flow.property_id, "payments.record", "payments.allocate")
    named = {**body(), field: value, "lease_id": str(uuid4())}
    assert receive(flow, who, named).status_code == 422 and not flow.received


@pytest.mark.parametrize(
    "state,error",
    [
        ("P5301", PaymentConfirmationNotFoundError),
        ("P5305", PaymentConfirmationKeyReused),
        ("P4905", PaymentConfirmationKeyReused),
        ("P4506", PaymentConfirmationAuthorizationError),
        ("P4904", ReceivePaymentChanged),
        ("P5R01", ReceivePaymentLeftWhileOwing),
        ("P5R02", ReceivePaymentTooMany),
        ("P4901", PaymentConfirmationInvalidError),
        ("P5302", PaymentConfirmationInvalidError),
        ("22003", PaymentConfirmationInvalidError),
        ("P5S01", PaymentConfirmationConflictError),
        ("40001", PaymentConfirmationUnavailableError),
        ("40P01", PaymentConfirmationUnavailableError),
        ("57014", PaymentConfirmationUnavailableError),
    ],
)
def test_each_database_refusal_becomes_its_own_answer(state: str, error: type[Exception]) -> None:
    class Refusal(psycopg.Error):
        sqlstate = state  # type: ignore[assignment]

    with pytest.raises(error) as raised:
        _database_error(Refusal("private SQL"))
    assert type(raised.value) is error
