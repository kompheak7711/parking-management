"""Strict staff Payment HTTP contracts without introducing financial policy."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.khr_payment_confirmation import ConfirmKhrPaymentCommand
from property_rental.payment_api import Confirmation, PaymentFlow, PostgresPaymentFlow, _cursor
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationUnavailableError,
)
from property_rental.payment_read import PaymentFilters, PaymentPage, PaymentReadUnavailableError
from test_invoice import actor, mutation_headers


@dataclass
class Flow:
    property_id: UUID = field(default_factory=uuid4)
    payment_id: UUID = field(default_factory=uuid4)
    calls: list[object] = field(default_factory=list)
    error: Exception | None = None
    responses: dict[tuple[str, UUID, UUID], tuple[dict[str, object], dict[str, object]]] = field(
        default_factory=dict
    )

    def value(self) -> dict[str, object]:
        return {
            "payment": {
                "id": str(self.payment_id),
                "property_id": str(self.property_id),
                "status": "RECEIVED",
                "payment_date": "2026-08-01",
                "received_amount_minor": 9_000_000_000_000_000,
            },
            "exchange_rate": {"reference": "4062.000001"},
        }

    def fail(self) -> None:
        if self.error is not None:
            raise self.error

    def list(
        self,
        property_id: UUID,
        page: PaymentPage,
        filters: PaymentFilters,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.calls.append((property_id, page, filters, actor))
        self.fail()
        return {
            "items": [self.value()],
            "next_cursor": {"payment_date": "2026-08-01", "id": str(self.payment_id)},
            "limit": page.limit,
        }

    def get(self, payment_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        self.calls.append((payment_id, actor))
        self.fail()
        return self.value()

    def confirm(
        self, property_id: UUID, command: Confirmation, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((property_id, command, actor))
        self.fail()
        key = (actor.actor_id, property_id, command.idempotency_key)
        intent = command.intent()
        if key in self.responses:
            previous, response = self.responses[key]
            if previous != intent:
                raise PaymentConfirmationKeyReused("private SQL evidence")
            return response
        response = {**self.value(), "original_intent": intent, "receipt": {"id": str(uuid4())}}
        self.responses[key] = (intent, response)
        return response


def api(flow: PaymentFlow, authenticated: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: authenticated, payment_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def payload(currency: str = "USD") -> dict[str, object]:
    value: dict[str, object] = {
        "amount": {"currency": currency, "minor_units": 100},
        "payer_customer_id": str(uuid4()),
        "payment_method_id": str(uuid4()),
        "received_at": "2026-08-01T12:00:00+07:00",
        "evidence_reference": "Original receipt evidence",
    }
    if currency == "KHR":
        value["amount"] = {"currency": "KHR", "minor_units": 4083}
        value["usd_accounting_amount"] = {"currency": "USD", "minor_units": 100}
    return value


def post(client: TestClient, flow: Flow, body: dict[str, object]) -> Response:
    result = client.post(
        f"/api/v1/properties/{flow.property_id}/payments", json=body, headers=mutation_headers()
    )
    return cast(Response, result)


def test_payment_api_list_filters_cursor_envelope_and_exact_money() -> None:
    flow = Flow()
    reader = actor(flow.property_id, "payments.read")
    client = api(flow, reader)
    customer, method = uuid4(), uuid4()
    path = f"/api/v1/properties/{flow.property_id}/payments"
    response = client.get(
        path,
        params={
            "customer_id": str(customer),
            "payment_method_id": str(method),
            "status": "REVERSED",
            "limit": "1",
            "sort": "-payment_date",
        },
        headers={"X-Request-ID": "payment-api-test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"][0] == flow.value()
    assert data["page"]["limit"] == 1 and isinstance(data["page"]["next_cursor"], str)
    assert (
        "9000000000000000" in response.text
        and data["data"][0]["exchange_rate"]["reference"] == "4062.000001"
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie" and data["meta"]["request_id"] == "payment-api-test"
    assert flow.calls[-1] == (
        flow.property_id,
        PaymentPage(1),
        PaymentFilters(customer, "REVERSED", method),
        reader,
    )
    assert client.get(path, params={"cursor": data["page"]["next_cursor"]}).status_code == 200
    assert cast(tuple[object, ...], flow.calls[-1])[1] == PaymentPage(
        50, datetime(2026, 8, 1).date(), flow.payment_id
    )
    assert client.get(f"/api/v1/payments/{flow.payment_id}").json()["data"] == flow.value()


@pytest.mark.parametrize(
    "query",
    [
        "unknown=1",
        "status=REFUNDED",
        "limit=0",
        "limit=101",
        "limit=1.0",
        "limit=01",
        "limit=1&limit=2",
        "sort=payment_date",
        "cursor=not-base64",
        "cursor=" + "a" * 257,
        "customer_id=00000000-0000-0000-0000-000000000000",
    ],
)
def test_payment_api_rejects_unsupported_and_ambiguous_queries(query: str) -> None:
    flow = Flow()
    response = api(flow, actor(flow.property_id, "payments.read")).get(
        f"/api/v1/properties/{flow.property_id}/payments?{query}"
    )
    assert response.status_code in (400, 422) and flow.calls == []
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "value",
    [
        {"payment_date": "20260801", "id": str(uuid4())},
        {"payment_date": "2026-02-31", "id": str(uuid4())},
        {"payment_date": "2026-08-01", "id": str(UUID(int=0))},
        {"payment_date": "2026-08-01", "id": 12},
        {"payment_date": "2026-08-01", "id": str(uuid4()), "extra": True},
    ],
)
def test_payment_api_cursor_rejects_malformed_dates_ids_and_extra_fields(
    value: dict[str, object],
) -> None:
    flow = Flow()
    cursor = _cursor(value)
    assert cursor is not None
    result = api(flow, actor(flow.property_id, "payments.read")).get(
        f"/api/v1/properties/{flow.property_id}/payments", params={"cursor": cursor}
    )
    assert result.status_code == 400 and flow.calls == []


def test_payment_api_requires_actor_exact_property_and_separate_capabilities() -> None:
    flow = Flow()
    path = f"/api/v1/properties/{flow.property_id}/payments"
    for who, code in [
        (None, 401),
        (AuthenticatedActor("SYSTEM:job"), 403),
        (actor(uuid4(), "payments.read"), 403),
        (actor(flow.property_id, "payments.record"), 403),
    ]:
        assert api(flow, who).get(path).status_code == code
    assert flow.calls == []
    reader = actor(flow.property_id, "payments.read")
    assert post(api(flow, reader), flow, payload()).status_code == 403
    assert post(api(flow, actor(uuid4(), "payments.record")), flow, payload()).status_code == 403
    assert flow.calls == []
    # Detail denies a foreign returned Property or mismatched immutable ID.
    assert (
        api(flow, actor(uuid4(), "payments.read"))
        .get(f"/api/v1/payments/{flow.payment_id}")
        .status_code
        == 404
    )
    assert api(flow, reader).get(f"/api/v1/payments/{uuid4()}").status_code == 404


@pytest.mark.parametrize(
    "change",
    ["origin", "csrf", "cookie", "empty", "actor", "duplicate_key", "missing_key", "nil_key"],
)
def test_payment_api_browser_actor_and_idempotency_preconditions_precede_dispatch(
    change: str,
) -> None:
    flow = Flow()
    who = actor(flow.property_id, "payments.record")
    client = api(flow, who)
    headers = mutation_headers()
    if change == "origin":
        headers["Origin"] = "https://other.invalid"
    if change == "csrf":
        headers["X-CSRF-Token"] = "wrong"
    if change == "cookie":
        client.cookies.clear()
    if change == "empty":
        headers["X-CSRF-Token"] = ""
        client.cookies.set("__Host-prm_csrf", "")
    if change == "actor":
        headers["X-Billing-Actor-ID"] = str(uuid4())
    if change == "missing_key":
        del headers["Idempotency-Key"]
    if change == "nil_key":
        headers["Idempotency-Key"] = str(UUID(int=0))
    supplied = list(headers.items())
    if change == "duplicate_key":
        supplied.append(("Idempotency-Key", str(uuid4())))
    response = client.post(
        f"/api/v1/properties/{flow.property_id}/payments", json=payload(), headers=supplied
    )
    assert response.status_code in (400, 403, 412, 422) and flow.calls == []


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("amount", {"currency": "USD", "minor_units": value})
        for value in [True, 1.0, "100", 0, -1, 9_000_000_000_000_001]
    ]
    + [
        ("received_at", x)
        for x in [1, "2026-08-01", "2026-08-01T00:00:00", "2026-08-01T00:00:00+00:60"]
    ]
    + [
        ("evidence_reference", x)
        for x in ["", "\t", " padded", "\u00a0padded", "nul\x00", "x" * 501]
    ]
    + [
        ("status", "RECEIVED"),
        ("allocations", []),
        ("usd_accounting_amount", {"currency": "USD", "minor_units": 100}),
        ("payer_customer_id", str(UUID(int=0))),
        ("payment_scope_kind", "CUSTOM"),
    ],
)
def test_payment_api_rejects_coerced_money_invalid_evidence_and_caller_derived_fields(
    field_name: str, value: object
) -> None:
    flow = Flow()
    body = payload()
    body[field_name] = value
    response = post(api(flow, actor(flow.property_id, "payments.record")), flow, body)
    assert response.status_code == 422 and flow.calls == []
    assert "stack" not in response.text and "Original receipt evidence" not in response.text


def test_payment_api_rejects_duplicate_json_keys_nested_keys_and_oversized_input() -> None:
    flow = Flow()
    client = api(flow, actor(flow.property_id, "payments.record"))
    body = payload()
    encoded = json.dumps(body)
    duplicate = encoded[:-1] + ',"evidence_reference":"other"}'
    nested = encoded.replace('"minor_units": 100', '"minor_units": 1,"minor_units": 100')
    for raw in [duplicate, nested, encoded + " " * 32768]:
        result = client.post(
            f"/api/v1/properties/{flow.property_id}/payments",
            content=raw,
            headers={**mutation_headers(), "Content-Type": "application/json"},
        )
        assert result.status_code == 400 and flow.calls == []
    # Equivalent noncanonical JSON cursor bytes do not bypass the opaque contract.
    raw_cursor = base64.urlsafe_b64encode(
        json.dumps({"id": str(flow.payment_id), "payment_date": "2026-08-01"}).encode()
    ).decode()
    assert (
        api(flow, actor(flow.property_id, "payments.read"))
        .get(f"/api/v1/properties/{flow.property_id}/payments", params={"cursor": raw_cursor})
        .status_code
        == 400
    )


@pytest.mark.parametrize("currency", ["USD", "KHR"])
def test_payment_api_confirmation_preserves_command_actor_and_exact_replay(currency: str) -> None:
    flow = Flow()
    who = actor(flow.property_id, "payments.record")
    client = api(flow, who)
    body, key = payload(currency), uuid4()
    headers = {**mutation_headers(key=key), "X-Billing-Actor-ID": who.actor_id}
    path = f"/api/v1/properties/{flow.property_id}/payments"
    first = client.post(path, json=body, headers=headers)
    second = client.post(path, json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert first.headers["Location"] == f"/api/v1/payments/{flow.payment_id}"
    assert "no-store" in first.headers["cache-control"]
    prop, command, actual_actor = cast(tuple[UUID, Confirmation, AuthenticatedActor], flow.calls[0])
    assert prop == flow.property_id and actual_actor is who and command.idempotency_key == key
    assert command.received_at == datetime(2026, 8, 1, 5, tzinfo=UTC)
    assert isinstance(
        command, ConfirmUsdPaymentCommand if currency == "USD" else ConfirmKhrPaymentCommand
    )
    conflict = client.post(path, json={**body, "evidence_reference": "changed"}, headers=headers)
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    assert "private SQL" not in conflict.text and len(flow.responses) == 1


def test_payment_api_khr_fallback_channel_inputs_and_independent_permission() -> None:
    flow = Flow()
    body = payload("KHR")
    body["manual_reference"] = {
        "reference_rate_khr_per_usd": "4062.000001",
        "source_reference": "approved-source",
        "applicable_at": body["received_at"],
        "fallback_reason": "verified source outage",
    }
    body["channel_transaction_reference"] = "actual channel"
    body["channel_evidence"] = {
        "transaction_reference": "actual channel",
        "confirmed_at": body["received_at"],
        "actual_rate_khr_per_usd": "4083.000000",
    }
    assert (
        post(api(flow, actor(flow.property_id, "payments.record")), flow, body).status_code == 403
        and not flow.calls
    )
    allowed = api(flow, actor(flow.property_id, "payments.record", "exchange_rates.manage"))
    assert post(allowed, flow, body).status_code == 201
    command = cast(tuple[UUID, ConfirmKhrPaymentCommand, AuthenticatedActor], flow.calls[-1])[1]
    assert (
        command.manual_reference is not None
        and command.manual_reference.reference_rate_khr_per_usd == Decimal("4062.000001")
    )
    assert (
        command.channel_evidence is not None
        and command.channel_evidence.actual_amount_minor is None
    )
    before = len(flow.calls)
    for rate in [4062.1, "NaN", "1e3", "0", "1.0000001"]:
        broken = json.loads(json.dumps(body))
        broken["manual_reference"]["reference_rate_khr_per_usd"] = rate
        assert post(allowed, flow, broken).status_code == 422
    assert len(flow.calls) == before


@pytest.mark.parametrize(
    "error,status",
    [
        (PaymentConfirmationAuthorizationError, 403),
        (PaymentConfirmationInvalidError, 422),
        (PaymentConfirmationConflictError, 409),
        (PaymentConfirmationNotFoundError, 404),
        (PaymentConfirmationUnavailableError, 503),
    ],
)
def test_payment_api_safe_errors_preserve_unknown_outcome_without_automatic_retry(
    error: type[Exception], status: int
) -> None:
    flow = Flow(error=error("private SQL / credentials / evidence"))
    result = post(api(flow, actor(flow.property_id, "payments.record")), flow, payload())
    assert result.status_code == status and len(flow.calls) == 1
    assert "private SQL" not in result.text and "credentials" not in result.text
    assert result.json()["meta"]["request_id"] == result.headers["X-Request-ID"]


def test_payment_api_missing_runtime_and_financial_dependencies_fail_closed() -> None:
    prop = uuid4()
    who = actor(prop, "payments.read", "payments.record")
    client = api(PostgresPaymentFlow(None, None), who)
    assert client.get(f"/api/v1/properties/{prop}/payments").status_code == 503
    assert client.get(f"/api/v1/payments/{uuid4()}").status_code == 503
    assert (
        client.post(
            f"/api/v1/properties/{prop}/payments", json=payload(), headers=mutation_headers()
        ).status_code
        == 503
    )
    with pytest.raises(PaymentReadUnavailableError):
        PostgresPaymentFlow(None, "not-used").list(prop, PaymentPage(), PaymentFilters(), actor=who)
