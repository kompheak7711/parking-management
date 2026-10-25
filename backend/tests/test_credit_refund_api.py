"""Full-app Credit/USD Refund transport, exact commands and bounded histories."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from starlette.types import Message, Scope

from property_rental.app import create_app
from property_rental.credit import (
    CreditAuthorizationError,
    CreditConflictError,
    CreditIdempotencyKeyReused,
    CreditInvalidError,
    CreditNotFoundError,
    CreditUnavailableError,
    CustomerCreditService,
)
from property_rental.credit_refund_api import PostgresCreditRefundFlow, _binding, _decode_cursor
from property_rental.credit_refund_read import (
    FinancialReadAuthorizationError,
    FinancialReadInvalidError,
    FinancialReadNotFoundError,
    FinancialReadUnavailableError,
    Resource,
)
from property_rental.identity import AuthenticatedActor
from property_rental.payment_api import _cursor
from property_rental.refund import (
    AddRefundMethodCommand,
    RefundAuthorizationError,
    RefundConflictError,
    RefundIdempotencyKeyReused,
    RefundInvalidError,
    RefundNotFoundError,
    RefundService,
    RefundUnavailableError,
)
from test_invoice import actor, mutation_headers


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    customer: UUID = field(default_factory=uuid4)
    payment: UUID = field(default_factory=uuid4)
    credit: UUID = field(default_factory=uuid4)
    application: UUID = field(default_factory=uuid4)
    invoice: UUID = field(default_factory=uuid4)
    line: UUID = field(default_factory=uuid4)
    refund: UUID = field(default_factory=uuid4)
    correction: UUID = field(default_factory=uuid4)
    calls: list[tuple[str, object]] = field(default_factory=list)
    credit_service: MagicMock = field(default_factory=lambda: MagicMock(spec=CustomerCreditService))
    refund_service: MagicMock = field(default_factory=lambda: MagicMock(spec=RefundService))
    scope_error: Exception | None = None

    def __post_init__(self) -> None:
        credit = {
            "id": str(self.credit),
            "customer_id": str(self.customer),
            "source_payment_id": str(self.payment),
            "recognized_usd_cents": 1000,
        }
        payment = {
            "id": str(self.payment),
            "property_id": str(self.prop),
            "received_currency": "KHR",
            "received_amount_minor": 4143,
            "usd_accounting_value_cents": 101,
        }
        result = {"credit": credit, "source_payment": payment, "available_usd_cents": 1000}
        for name in ("get", "recognize", "reverse"):
            getattr(self.credit_service, name).return_value = result
        self.credit_service.list.return_value = {"items": [result], "next_cursor": None}
        self.credit_service.ledger.return_value = {
            **result,
            "history": {"items": [], "next_cursor": None},
        }
        self.credit_service.application_proposal.return_value = {
            "property_id": str(self.prop),
            "credit_id": str(self.credit),
            "invoice_id": str(self.invoice),
            "amount_usd_cents": 1000,
            "details": [],
        }
        for name in ("apply", "get_application", "reverse_application"):
            getattr(self.credit_service, name).return_value = {
                "application": {"id": str(self.application)},
                "details": [{"invoice_line_id": str(self.line), "amount_usd_cents": 1000}],
            }
        refund = {
            "refund": {
                "id": str(self.refund),
                "refund_currency": "USD",
                "refund_amount_minor": 1000,
            },
            "source": {"type": "PAYMENT", "id": str(self.payment), "property_id": str(self.prop)},
            "net_refund_usd_cents": 1000,
            "corrections": {"items": [], "next_cursor": None},
        }
        for name in ("get", "verify_usd_return", "reverse_correction"):
            getattr(self.refund_service, name).return_value = refund
        self.refund_service.list.return_value = {"items": [refund], "next_cursor": None}
        self.refund_service.usd_source.return_value = {
            "source_type": "PAYMENT",
            "source_id": str(self.payment),
            "property_id": str(self.prop),
            "refund_currency": "USD",
            "available_usd_cents": 1000,
            "eligible": True,
        }

    def resolve(
        self, resource: Resource, identity: UUID, capability: str, *, actor: AuthenticatedActor
    ) -> UUID:
        self.calls.append(("resolve", (resource, identity, capability, actor)))
        if self.scope_error is not None:
            raise self.scope_error
        return self.prop

    def credits(self, *, mutation: bool = False) -> CustomerCreditService:
        self.calls.append(("credits", mutation))
        return cast(CustomerCreditService, self.credit_service)

    def refunds(self, *, mutation: bool = False) -> RefundService:
        self.calls.append(("refunds", mutation))
        return cast(RefundService, self.refund_service)

    def source_audit(
        self, prop: UUID, kind: str, identity: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append(("audit", (prop, kind, identity, actor)))
        return {
            "source_payment": {
                "id": str(self.payment),
                "property_id": str(prop),
                "received_currency": "KHR",
                "received_amount_minor": 4143,
                "usd_accounting_value_cents": 101,
            },
            "source_exchange_rate": {"channel_actual_rate_khr_per_usd": "4100.123456"},
            "receipt_evidence": {"evidence_reference": "Original receipt"},
        }


def api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, credit_refund_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    capability: str
    resource: Resource
    resource_id: UUID
    family: str
    operation: str
    body: dict[str, object] | None = None
    params: dict[str, str] = field(default_factory=dict)


def routes(f: Flow) -> list[Route]:
    return [
        Route(
            "GET",
            f"/customers/{f.customer}/credits",
            "credits.read",
            "customer",
            f.customer,
            "credits",
            "list",
        ),
        Route(
            "GET",
            f"/customer-credits/{f.credit}",
            "credits.read",
            "credit",
            f.credit,
            "credits",
            "get",
        ),
        Route(
            "GET",
            f"/customer-credits/{f.credit}/ledger",
            "credits.read",
            "credit",
            f.credit,
            "credits",
            "ledger",
        ),
        Route(
            "POST",
            f"/payments/{f.payment}/credit-recognitions",
            "credits.recognize",
            "payment",
            f.payment,
            "credits",
            "recognize",
            {
                "currency": "USD",
                "amount_usd_cents": 1000,
                "payer_authorization_reference": "Payer consent",
                "reason": "Retain eligible excess",
            },
        ),
        Route(
            "POST",
            f"/customer-credits/{f.credit}/reverse",
            "credits.reverse",
            "credit",
            f.credit,
            "credits",
            "reverse",
            {"reason": "Correct recognition"},
        ),
        Route(
            "GET",
            f"/customer-credits/{f.credit}/application-proposal",
            "credits.apply",
            "credit",
            f.credit,
            "credits",
            "application_proposal",
            params={"invoice_id": str(f.invoice), "amount_usd_cents": "1000"},
        ),
        Route(
            "POST",
            f"/customer-credits/{f.credit}/applications",
            "credits.apply",
            "credit",
            f.credit,
            "credits",
            "apply",
            {
                "currency": "USD",
                "intent": {
                    "mode": "DESIGNATED",
                    "invoice_id": str(f.invoice),
                    "amount_usd_cents": 1000,
                    "designation_reference": "Payer target",
                    "details": [{"invoice_line_id": str(f.line), "amount_usd_cents": 1000}],
                },
            },
        ),
        Route(
            "GET",
            f"/credit-applications/{f.application}",
            "credits.read",
            "credit_application",
            f.application,
            "credits",
            "get_application",
        ),
        Route(
            "POST",
            f"/credit-applications/{f.application}/reverse",
            "credits.applications.reverse",
            "credit_application",
            f.application,
            "credits",
            "reverse_application",
            {"reason": "Correct target"},
        ),
        Route(
            "GET",
            f"/properties/{f.prop}/refunds",
            "refunds.read",
            "property",
            f.prop,
            "refunds",
            "list",
        ),
        Route("GET", f"/refunds/{f.refund}", "refunds.read", "refund", f.refund, "refunds", "get"),
        Route(
            "GET",
            f"/refund-sources/PAYMENT/{f.payment}",
            "refunds.create",
            "payment",
            f.payment,
            "refunds",
            "usd_source",
        ),
        Route(
            "POST",
            "/refunds",
            "refunds.create",
            "payment",
            f.payment,
            "refunds",
            "create_usd",
            {
                "currency": "USD",
                "source_type": "PAYMENT",
                "source_id": str(f.payment),
                "amount_usd_cents": 1000,
                "reason": "Return eligible excess",
            },
        ),
        Route(
            "POST",
            f"/refunds/{f.refund}/verified-returns",
            "refunds.correct",
            "refund",
            f.refund,
            "refunds",
            "verify_usd_return",
            {
                "currency": "USD",
                "returned_amount_minor": 1000,
                "returned_at": "2026-09-07T10:00:00.123456+07:00",
                "return_method_reference": "Verified bank return",
                "evidence_reference": "Original evidence",
                "reason": "Verified returned value",
            },
        ),
        Route(
            "POST",
            f"/refunds/{f.refund}/verified-returns/{f.correction}/reverse",
            "refunds.corrections.reverse",
            "refund",
            f.refund,
            "refunds",
            "reverse_correction",
            {"evidence_reference": "Review evidence", "reason": "Correct return record"},
        ),
    ]


POSTS = [3, 4, 6, 8, 12, 13, 14]


@pytest.mark.parametrize("index", range(15))
def test_credit_refund_http_exact_service_dispatch_and_private_response(index: int) -> None:
    flow = Flow()
    route = routes(flow)[index]
    who = actor(flow.prop, route.capability)
    key = uuid4()
    response = api(flow, who).request(
        route.method,
        "/api/v1" + route.path,
        json=route.body,
        params=route.params,
        headers=mutation_headers(key=key),
    )
    if index == 12:
        # V1-056 slice 3a: a Refund is a draft now; the old route records nothing (BR-AUTH-010).
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "REFUND_DRAFT_REQUIRED"
        assert flow.refund_service.method_calls == []
        return
    assert response.status_code == (201 if index in (3, 6, 12) else 200), response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert flow.calls[0] == ("resolve", (route.resource, route.resource_id, route.capability, who))
    assert (route.family, route.method == "POST") in flow.calls
    service = flow.credit_service if route.family == "credits" else flow.refund_service
    command_call = getattr(service, route.operation)
    command_call.assert_called_once()
    assert command_call.call_args.args[0] == flow.prop
    assert command_call.call_args.kwargs["actor"] == who
    if route.method == "POST":
        command = next(
            arg for arg in command_call.call_args.args if hasattr(arg, "idempotency_key")
        )
        assert command.idempotency_key == key
        if route.body is not None and "reason" in route.body:
            assert command.reason == route.body["reason"]
    if index == 13:
        assert command.returned_at == datetime(2026, 9, 7, 3, 0, 0, 123456, tzinfo=UTC)
    if index in (3, 6, 12):
        assert response.headers["location"].startswith("/api/v1/")
    if index == 11:
        assert (
            response.json()["data"]["source_exchange_rate"]["channel_actual_rate_khr_per_usd"]
            == "4100.123456"
        )
        assert response.json()["data"]["source_payment"]["received_currency"] == "KHR"


@pytest.mark.parametrize("index", range(15))
@pytest.mark.parametrize("denial", ["missing_actor", "wrong_capability", "wrong_property"])
def test_credit_refund_http_denied_actor_or_grant_never_calls_financial_service(
    index: int, denial: str
) -> None:
    flow = Flow()
    route = routes(flow)[index]
    who = (
        None
        if denial == "missing_actor"
        else actor(
            uuid4() if denial == "wrong_property" else flow.prop,
            route.capability if denial == "wrong_property" else "payments.read",
        )
    )
    response = api(flow, who).request(
        route.method,
        "/api/v1" + route.path,
        json=route.body,
        params=route.params,
        headers=mutation_headers(),
    )
    assert response.status_code == (401 if denial == "missing_actor" else 404)
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("index", POSTS)
@pytest.mark.parametrize(
    "failure",
    [
        "missing_key",
        "missing_csrf",
        "missing_cookie",
        "bad_origin",
        "duplicate_key",
        "duplicate_csrf",
        "duplicate_origin",
        "duplicate_actor",
    ],
)
def test_credit_refund_http_browser_and_idempotency_boundaries(index: int, failure: str) -> None:
    flow = Flow()
    route = routes(flow)[index]
    who = actor(flow.prop, route.capability)
    client = api(flow, who)
    headers = mutation_headers()
    if failure == "missing_key":
        del headers["Idempotency-Key"]
    elif failure == "missing_csrf":
        del headers["X-CSRF-Token"]
    elif failure == "missing_cookie":
        client.cookies.clear()
    elif failure == "bad_origin":
        headers["Origin"] = "https://untrusted.invalid"
    pairs = list(headers.items())
    if failure.startswith("duplicate_"):
        name = {
            "duplicate_key": "Idempotency-Key",
            "duplicate_csrf": "X-CSRF-Token",
            "duplicate_origin": "Origin",
            "duplicate_actor": "X-Billing-Actor-ID",
        }[failure]
        if name == "X-Billing-Actor-ID":
            pairs.extend([(name, who.actor_id), (name, who.actor_id)])
        else:
            pairs.append((name, headers[name]))
    response = client.post("/api/v1" + route.path, json=route.body, headers=pairs)
    assert response.status_code == (
        422 if failure == "missing_key" else 400 if failure.startswith("duplicate_") else 403
    ), response.text
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", POSTS)
@pytest.mark.parametrize(
    "invalid",
    [
        "extra",
        "nul",
        "whitespace",
        "invalid_unicode",
        "duplicate_json",
        "nan",
        "utf16",
        "oversized",
    ],
)
def test_credit_refund_http_strict_json_and_text_before_financial_dispatch(
    index: int, invalid: str
) -> None:
    flow = Flow()
    route = routes(flow)[index]
    body = dict(route.body or {})
    if invalid == "extra":
        body["financial_status"] = "PENDING"
    elif invalid in ("nul", "whitespace", "invalid_unicode"):
        # Application's designation_reference is inside its exact immutable intent.
        text = {"nul": "bad\x00text", "whitespace": " unnormalized ", "invalid_unicode": "\ud800"}[
            invalid
        ]
        if index == 6:
            intent = dict(cast(dict[str, object], body["intent"]))
            intent["designation_reference"] = text
            body["intent"] = intent
        else:
            body["reason"] = text
    raw = json.dumps(body).encode()
    if invalid == "duplicate_json":
        raw = b'{"reason":"one",' + raw[1:]
        if index == 6:
            raw = b'{"currency":"USD",' + json.dumps(body).encode()[1:]
    elif invalid == "nan":
        raw = b'{"amount_usd_cents":NaN,' + raw[1:]
    elif invalid == "utf16":
        raw = json.dumps(body).encode("utf-16")
    elif invalid == "oversized":
        raw = b" " * 262_145
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path,
        content=raw,
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    expected = (
        400
        if invalid == "oversized"
        else 400
        if invalid in {"duplicate_json", "nan", "utf16", "invalid_unicode"}
        else 422
    )
    assert response.status_code == expected, response.text
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", [3, 6, 12, 13])
@pytest.mark.parametrize("currency", [None, "KHR", "usd", True])
def test_credit_refund_http_requires_explicit_usd_currency(index: int, currency: object) -> None:
    flow = Flow()
    route = routes(flow)[index]
    body = dict(route.body or {})
    if currency is None:
        body.pop("currency")
    else:
        body["currency"] = currency
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path, json=body, headers=mutation_headers()
    )
    assert response.status_code == 422
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", [3, 12, 13])
@pytest.mark.parametrize("amount", [0, -1, True, 1.5, "1", 9_000_000_000_000_001])
def test_credit_refund_http_rejects_nonexact_or_out_of_range_amounts(
    index: int, amount: object
) -> None:
    flow = Flow()
    route = routes(flow)[index]
    body = {
        **(route.body or {}),
        "returned_amount_minor" if index == 13 else "amount_usd_cents": amount,
    }
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path, json=body, headers=mutation_headers()
    )
    assert response.status_code == 422
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize(
    "value",
    [
        0,
        1.5,
        "2026-09-07",
        "2026-09-07T01:00:00",
        "2026-09-07T01:00:00.1234567Z",
        "2026-09-07T25:00:00Z",
        "2026-09-07T01:00:00+24:00",
    ],
)
def test_credit_refund_http_return_timestamp_must_be_exact_rfc3339(value: object) -> None:
    flow = Flow()
    route = routes(flow)[13]
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path,
        json={**(route.body or {}), "returned_at": value},
        headers=mutation_headers(),
    )
    assert response.status_code == 422
    assert not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", range(15))
def test_credit_refund_http_unknown_or_duplicate_query_rejected(index: int) -> None:
    for duplicate in (False, True):
        flow = Flow()
        route = routes(flow)[index]
        params = [*route.params.items(), ("unknown_filter", "1")]
        if duplicate:
            params = [*route.params.items(), ("limit", "1"), ("limit", "2")]
        response = api(flow, actor(flow.prop, route.capability)).request(
            route.method,
            "/api/v1" + route.path,
            json=route.body,
            params=params,
            headers=mutation_headers(),
        )
        assert response.status_code == 400
        assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", [0, 2, 9, 10])
@pytest.mark.parametrize("limit", ["0", "101", "01", "1.0", "+1", " 1 "])
def test_credit_refund_http_page_limits_are_bounded_and_canonical(index: int, limit: str) -> None:
    flow = Flow()
    route = routes(flow)[index]
    response = api(flow, actor(flow.prop, route.capability)).get(
        "/api/v1" + route.path, params={"limit": limit}
    )
    assert response.status_code == (422 if limit in {"0", "101"} else 400)
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", [0, 2, 9, 10])
def test_credit_refund_http_cursor_binds_collection_resource_property_filter_and_event(
    index: int,
) -> None:
    flow = Flow()
    route = routes(flow)[index]
    service = flow.credit_service if route.family == "credits" else flow.refund_service
    method = getattr(service, route.operation)
    result = method.return_value
    collection = (
        result["history"] if index == 2 else result["corrections"] if index == 10 else result
    )
    event = {"occurred_at": "2026-09-07T03:00:00.123456+00:00", "id": str(flow.correction)}
    if index == 2:
        event["event_kind"] = "APPLICATION_REVERSAL"
    collection["next_cursor"] = event
    client = api(flow, actor(flow.prop, route.capability))
    response = client.get("/api/v1" + route.path, params={"limit": "1"})
    assert response.status_code == 200, response.text
    page = (
        response.json()["data"]["history" if index == 2 else "corrections"]["page"]
        if index in (2, 10)
        else response.json()["page"]
    )
    token = page["next_cursor"]
    assert isinstance(token, str) and page["limit"] == 1
    import base64

    decoded = json.loads(base64.urlsafe_b64decode(token))
    assert decoded["property_id"] == str(flow.prop)
    assert decoded["resource_id"] == str(route.resource_id)
    assert decoded["customer_id"] is None
    assert client.get("/api/v1" + route.path, params={"cursor": token}).status_code == 200
    call = method.call_args
    requested = call.args[2] if index in (0, 2) else call.kwargs["page"]
    assert requested.after_at == datetime(2026, 9, 7, 3, 0, 0, 123456, tzinfo=UTC)
    assert requested.after_id == flow.correction
    if index == 2:
        assert requested.after_kind == "APPLICATION_REVERSAL"
    for key in ("collection", "property_id", "resource_id", "customer_id", "occurred_at", "id"):
        changed = {**decoded, key: "wrong"}
        method.reset_mock()
        assert (
            client.get("/api/v1" + route.path, params={"cursor": _cursor(changed)}).status_code
            == 400
        )
        method.assert_not_called()
    if index == 9:
        assert (
            client.get(
                "/api/v1" + route.path, params={"cursor": token, "customer_id": str(flow.customer)}
            ).status_code
            == 400
        )


@pytest.mark.parametrize(
    "value", ["", "garbage", "[]", "x" * 1025, "\u00e9", _cursor({}), _cursor({"id": str(uuid4())})]
)
def test_credit_refund_http_cursor_malformed_encoding_is_not_an_empty_page(value: str) -> None:
    with pytest.raises(HTTPException) as caught:
        _decode_cursor(value, _binding("credit-ledger", uuid4(), uuid4()), ledger=True)
    assert caught.value.status_code == 400


@pytest.mark.parametrize(
    "error,status",
    [
        (CreditNotFoundError, 404),
        (CreditAuthorizationError, 404),
        (CreditInvalidError, 422),
        (CreditConflictError, 409),
        (CreditIdempotencyKeyReused, 409),
        (CreditUnavailableError, 503),
        (RefundNotFoundError, 404),
        (RefundAuthorizationError, 404),
        (RefundInvalidError, 422),
        (RefundIdempotencyKeyReused, 409),
        (RefundUnavailableError, 503),
    ],
)
def test_credit_refund_http_service_failures_keep_safe_unknown_outcome_and_key_reuse(
    error: type[Exception], status: int
) -> None:
    flow = Flow()
    # V1-056 slice 3a: POST /refunds no longer reaches the service; the verified-return
    # route (13) still dispatches to the Refund service and keeps the same error mapping.
    route = routes(flow)[13 if error.__name__.startswith("Refund") else 3]
    service = flow.refund_service if route.family == "refunds" else flow.credit_service
    getattr(service, route.operation).side_effect = error("private SQL and persisted evidence")
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path, json=route.body, headers=mutation_headers()
    )
    assert response.status_code == status
    assert "private SQL" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    if "Idempotency" in error.__name__:
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize(
    "error,status",
    [
        (FinancialReadAuthorizationError, 404),
        (FinancialReadNotFoundError, 404),
        (FinancialReadInvalidError, 422),
        (FinancialReadUnavailableError, 503),
    ],
)
def test_credit_refund_http_scope_failure_prevents_financial_dispatch(
    error: type[Exception], status: int
) -> None:
    flow = Flow(scope_error=error("private scope data"))
    route = routes(flow)[12]
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path, json=route.body, headers=mutation_headers()
    )
    assert response.status_code == status and "private scope" not in response.text
    assert not flow.refund_service.mock_calls


@pytest.mark.parametrize(
    "source_type,review",
    [
        ("KHR", None),
        ("FINAL_SETTLEMENT", None),
        ("SECURITY_DEPOSIT", None),
        ("PET_DEPOSIT", None),
        ("PAYMENT", str(uuid4())),
        ("CREDIT", str(uuid4())),
    ],
)
def test_credit_refund_http_unsupported_sources_and_mismatched_pet_review_fail_closed(
    source_type: str, review: str | None
) -> None:
    flow = Flow()
    route = routes(flow)[12]
    body = {**(route.body or {}), "source_type": source_type}
    if review is not None:
        body["pet_refund_review_id"] = review
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1/refunds", json=body, headers=mutation_headers()
    )
    assert response.status_code == 422
    assert not flow.refund_service.mock_calls


def test_credit_refund_http_pet_creation_uses_only_qualified_existing_service() -> None:
    flow = Flow()
    deposit, review = uuid4(), uuid4()
    body = {
        **(routes(flow)[12].body or {}),
        "source_type": "PET_DEPOSIT",
        "source_id": str(deposit),
        "pet_refund_review_id": str(review),
    }
    response = api(flow, actor(flow.prop, "refunds.create")).post(
        "/api/v1/refunds", json=body, headers=mutation_headers()
    )
    # V1-056 slice 3a: a Pet Refund is a draft now; the old route records nothing.
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REFUND_DRAFT_REQUIRED"
    assert flow.refund_service.method_calls == []


def test_credit_refund_http_runtime_readers_never_borrow_writer_and_mutations_require_it() -> None:
    flow = PostgresCreditRefundFlow("runtime-only", None)
    assert flow.credits().database_url == flow.refunds().database_url == "runtime-only"
    assert flow.credits().financial_database_url == flow.refunds().financial_database_url == ""
    for method in (flow.credits, flow.refunds):
        with pytest.raises(FinancialReadUnavailableError):
            method(mutation=True)
    flow = PostgresCreditRefundFlow("runtime-only", "financial-only")
    assert (
        flow.credits(mutation=True).financial_database_url
        == flow.refunds(mutation=True).financial_database_url
        == "financial-only"
    )
    with patch("property_rental.credit_refund_api.CreditRefundReadService") as reader:
        flow.resolve("credit", uuid4(), "credits.read", actor=actor(uuid4(), "credits.read"))
        reader.assert_called_once_with("runtime-only")


@pytest.mark.parametrize("index", POSTS)
def test_credit_refund_http_actual_stream_bound_precedes_financial_dispatch(index: int) -> None:
    flow = Flow()
    route = routes(flow)[index]
    who = actor(flow.prop, route.capability)
    app = create_app(actor_resolver=lambda _: who, credit_refund_flow=flow)
    received = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal received
        received += 1
        if received <= 3:
            return {"type": "http.request", "body": b" " * 100_000, "more_body": True}
        await asyncio.Event().wait()
        raise AssertionError("Response completion cancels the listener")

    async def send(message: Message) -> None:
        sent.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1" + route.path,
            "raw_path": ("/api/v1" + route.path).encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"localhost"),
                (b"content-type", b"application/json"),
                (b"content-length", b"2"),
            ],
            "server": ("localhost", 443),
            "client": ("127.0.0.1", 12345),
        },
    )
    asyncio.run(app(scope, receive, send))
    assert any(m["type"] == "http.response.start" and m["status"] == 400 for m in sent)
    assert received == 3 and flow.calls == []
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("size", [1, 500, 501])
def test_credit_refund_http_application_detail_bound_and_immutable_intent(size: int) -> None:
    from property_rental.credit import ApplyCreditCommand

    flow = Flow()
    route = routes(flow)[6]
    details = [{"invoice_line_id": str(uuid4()), "amount_usd_cents": 1} for _ in range(size)]
    intent = {
        "mode": "DESIGNATED",
        "invoice_id": str(flow.invoice),
        "amount_usd_cents": size,
        "designation_reference": "Payer target",
        "details": details,
    }
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path,
        json={"currency": "USD", "intent": intent},
        headers=mutation_headers(),
    )
    if size > 500:
        assert response.status_code == 422
        flow.credit_service.apply.assert_not_called()
        return
    assert response.status_code == 201, response.text
    command = flow.credit_service.apply.call_args.args[2]
    assert isinstance(command, ApplyCreditCommand) and command.intent == intent
    detached = command.intent
    cast(list[dict[str, object]], detached["details"])[0]["amount_usd_cents"] = 999
    assert command.intent == intent


@pytest.mark.parametrize("amount", [True, 1.0, "1", 0, -1, 9_000_000_000_000_001])
def test_credit_refund_http_nested_application_money_is_exact_before_dispatch(
    amount: object,
) -> None:
    flow = Flow()
    route = routes(flow)[6]
    assert route.body is not None
    body = dict(route.body)
    intent = dict(cast(dict[str, object], body["intent"]))
    intent["details"] = [{"invoice_line_id": str(flow.line), "amount_usd_cents": amount}]
    body["intent"] = intent
    response = api(flow, actor(flow.prop, route.capability)).post(
        "/api/v1" + route.path,
        json=body,
        headers=mutation_headers(),
    )
    assert response.status_code == 422
    flow.credit_service.apply.assert_not_called()


@pytest.mark.parametrize(
    "index,field",
    [
        (0, "limit"),
        (2, "limit"),
        (9, "limit"),
        (10, "limit"),
        (0, "cursor"),
        (2, "cursor"),
        (9, "cursor"),
        (10, "cursor"),
        (5, "invoice_id"),
        (5, "amount_usd_cents"),
        (9, "customer_id"),
        (11, "pet_refund_review_id"),
    ],
)
@pytest.mark.parametrize(
    "mode",
    ["duplicate_valid_last", "duplicate_invalid_last", "unknown_and_invalid", "single_invalid"],
)
def test_credit_refund_http_raw_query_guard_precedes_typed_validation(
    index: int,
    field: str,
    mode: str,
) -> None:
    flow = Flow()
    route = routes(flow)[index]
    valid = str(flow.invoice) if field.endswith("_id") else "opaque" if field == "cursor" else "1"
    invalid = "x" * 1025 if field == "cursor" else "invalid"
    params = [(key, value) for key, value in route.params.items() if key != field]
    if mode == "duplicate_valid_last":
        params.extend([(field, invalid), (field, valid)])
    elif mode == "duplicate_invalid_last":
        params.extend([(field, valid), (field, invalid)])
    else:
        params.append((field, invalid))
        if mode == "unknown_and_invalid":
            params.append(("unknown_filter", "value"))
    response = api(flow, actor(flow.prop, route.capability)).get(
        "/api/v1" + route.path,
        params=params,
    )
    assert response.status_code == (422 if mode == "single_invalid" else 400), response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert flow.calls == []
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("index", range(15))
def test_credit_refund_http_query_guard_preserves_unsupported_method_response(index: int) -> None:
    flow = Flow()
    route = routes(flow)[index]
    method = "GET" if route.method == "POST" else "POST"
    response = api(flow, actor(flow.prop, route.capability)).request(
        method,
        "/api/v1" + route.path,
        params=[("limit", "1"), ("limit", "invalid"), ("unknown_filter", "value")],
        content=b"not JSON",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 405
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert flow.calls == []
    assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


def _draft_body(flow: Flow) -> dict[str, object]:
    return {
        "currency": "USD",
        "source_type": "PAYMENT",
        "source_id": str(flow.payment),
        "amount_usd_cents": 1000,
        "reason": "Return eligible excess",
        "refund_method_id": str(uuid4()),
        "reference_note": "Cash at the office",
    }


def test_refund_draft_http_records_a_draft_only_under_refunds_create() -> None:
    flow = Flow()
    draft_id = uuid4()
    flow.refund_service.record_usd_draft.return_value = {
        "draft_id": str(draft_id),
        "property_id": str(flow.prop),
        "kind": "REFUND",
        "state": "PENDING",
    }
    key = uuid4()
    for who in (actor(flow.prop, "financial.approve"), actor(uuid4(), "refunds.create"), None):
        denied = api(flow, who).post(
            "/api/v1/refund-drafts", json=_draft_body(flow), headers=mutation_headers(key=key)
        )
        assert denied.status_code in {401, 404}
    flow.refund_service.record_usd_draft.assert_not_called()
    for header in ("X-CSRF-Token", "Idempotency-Key"):
        headers = mutation_headers(key=key)
        del headers[header]
        refused = api(flow, actor(flow.prop, "refunds.create")).post(
            "/api/v1/refund-drafts", json=_draft_body(flow), headers=headers
        )
        assert refused.status_code in {400, 403, 422}
    flow.refund_service.record_usd_draft.assert_not_called()

    who = actor(flow.prop, "refunds.create")
    response = api(flow, who).post(
        "/api/v1/refund-drafts", json=_draft_body(flow), headers=mutation_headers(key=key)
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "location" not in response.headers
    call = flow.refund_service.record_usd_draft.call_args
    assert call.args[0] == flow.prop and call.kwargs["actor"] == who
    assert call.args[1].idempotency_key == key and call.args[1].amount_usd_cents == 1000
    assert call.args[2].reference_note == "Cash at the office"
    flow.refund_service.confirm_draft.assert_not_called()


def test_refund_draft_http_confirm_needs_financial_approve_and_returns_the_refund() -> None:
    flow = Flow()
    draft_id = uuid4()
    refund = {
        "refund": {"id": str(flow.refund), "refund_currency": "USD", "refund_amount_minor": 1000},
        "source": {"type": "PAYMENT", "id": str(flow.payment), "property_id": str(flow.prop)},
        "net_refund_usd_cents": 1000,
        "corrections": {"items": [], "next_cursor": None},
    }
    flow.refund_service.confirm_draft.return_value = {
        "draft": {"draft_id": str(draft_id), "state": "CONFIRMED"},
        "refund": refund,
    }
    path = f"/api/v1/properties/{flow.prop}/refund-drafts/{draft_id}/confirm"
    for who in (
        actor(flow.prop, "refunds.create"),
        actor(uuid4(), "financial.approve"),
        None,
    ):
        assert api(flow, who).post(path, headers=mutation_headers()).status_code in {401, 404}
    headers = mutation_headers()
    del headers["X-CSRF-Token"]
    assert api(flow, actor(flow.prop, "financial.approve")).post(
        path, headers=headers
    ).status_code in {400, 403}
    flow.refund_service.confirm_draft.assert_not_called()

    who = actor(flow.prop, "financial.approve")
    response = api(flow, who).post(path, headers=mutation_headers())
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["location"] == f"/api/v1/refunds/{flow.refund}"
    assert response.json()["data"]["refund"]["id"] == str(flow.refund)
    assert "draft" not in response.json()["data"]
    flow.refund_service.confirm_draft.assert_called_once_with(flow.prop, draft_id, actor=who)

    flow.refund_service.confirm_draft.side_effect = RefundConflictError("private detail")
    conflict = api(flow, who).post(path, headers=mutation_headers())
    assert conflict.status_code == 409 and "private detail" not in conflict.text


def test_refund_draft_http_signer_recipient_needs_a_pet_source_and_the_agreement() -> None:
    flow = Flow()
    deposit, review, signer = uuid4(), uuid4(), uuid4()
    flow.refund_service.record_pet_draft.return_value = {
        "draft_id": str(uuid4()),
        "property_id": str(flow.prop),
        "kind": "REFUND",
    }
    who = actor(flow.prop, "refunds.create")
    pet = {
        **_draft_body(flow),
        "source_type": "PET_DEPOSIT",
        "source_id": str(deposit),
        "pet_refund_review_id": str(review),
    }
    for body in (
        {**pet, "recipient_customer_id": str(signer)},
        {**pet, "signer_agreement": "All Signers agreed"},
        {
            **_draft_body(flow),
            "recipient_customer_id": str(signer),
            "signer_agreement": "All Signers agreed",
        },
    ):
        refused = api(flow, who).post(
            "/api/v1/refund-drafts", json=body, headers=mutation_headers()
        )
        assert refused.status_code == 422, refused.text
    flow.refund_service.record_pet_draft.assert_not_called()
    flow.refund_service.record_usd_draft.assert_not_called()
    response = api(flow, who).post(
        "/api/v1/refund-drafts",
        json={
            **pet,
            "recipient_customer_id": str(signer),
            "signer_agreement": "All Signers agreed in writing on 2026-10-04",
        },
        headers=mutation_headers(),
    )
    assert response.status_code == 201, response.text
    recipient = flow.refund_service.record_pet_draft.call_args.kwargs["recipient"]
    assert recipient.customer_id == signer
    assert recipient.agreement == "All Signers agreed in writing on 2026-10-04"


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("Refund command is invalid")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


def test_refund_draft_http_credit_customer_variant_records_only_for_a_credit() -> None:
    """V1-056 slice 11c (BR-CREDIT-014): a released Credit is refunded to its own Customer."""
    flow = Flow()
    flow.refund_service.record_credit_customer_draft.return_value = {
        "draft_id": str(uuid4()),
        "property_id": str(flow.prop),
        "kind": "REFUND",
        "payload": {"variant": "CREDIT_CUSTOMER"},
    }
    who = actor(flow.prop, "refunds.create")
    body = {
        **_draft_body(flow),
        "source_type": "CREDIT",
        "source_id": str(flow.credit),
        "variant": "CREDIT_CUSTOMER",
    }
    for wrong in (
        {**body, "source_type": "PAYMENT"},
        {**body, "variant": "USD"},
        {**body, "recipient_customer_id": str(uuid4()), "signer_agreement": "Signed note"},
    ):
        refused = api(flow, who).post(
            "/api/v1/refund-drafts", json=wrong, headers=mutation_headers()
        )
        assert refused.status_code == 422, refused.text
    flow.refund_service.record_credit_customer_draft.assert_not_called()
    key = uuid4()
    response = api(flow, who).post(
        "/api/v1/refund-drafts", json=body, headers=mutation_headers(key=key)
    )
    assert response.status_code == 201, response.text
    call = flow.refund_service.record_credit_customer_draft.call_args
    assert call.args[0] == flow.prop and call.kwargs["actor"] == who
    assert (call.args[1].idempotency_key, call.args[1].credit_id) == (key, flow.credit)
    assert call.args[1].amount_usd_cents == 1000
    flow.refund_service.record_usd_draft.assert_not_called()
    # A command answer that is not this variant's draft is a server fault, not a success.
    for answer in (
        {"draft_id": str(uuid4()), "property_id": str(flow.prop), "kind": "DEPOSIT_FORFEITURE"},
        {"draft_id": str(uuid4()), "property_id": str(flow.prop), "kind": "REFUND"},
    ):
        flow.refund_service.record_credit_customer_draft.return_value = answer
        wrong_answer = api(flow, who).post(
            "/api/v1/refund-drafts", json=body, headers=mutation_headers()
        )
        assert wrong_answer.status_code == 503


_RETURN_BODY = {
    "currency": "USD",
    "returned_amount_minor": 1000,
    "returned_at": "2026-10-24T10:00:00Z",
    "return_method_reference": "Cash back at the office",
    "evidence_reference": "Signed slip",
    "reason": "The Customer returned the money",
}
_RECORD = "record"
_CONFIRM = "confirm"
_VERIFY = "verify"
_REVERSE = "reverse"


def _refund_answer(flow: Flow, route: str, failure: Exception) -> Response:
    """Each Refund route, its service method failing with ``failure``."""
    answer: Response
    if route == _RECORD:
        flow.refund_service.record_usd_draft.side_effect = failure
        answer = api(flow, actor(flow.prop, "refunds.create")).post(
            "/api/v1/refund-drafts", json=_draft_body(flow), headers=mutation_headers()
        )
        return answer
    if route == _CONFIRM:
        flow.refund_service.confirm_draft.side_effect = failure
        answer = api(flow, actor(flow.prop, "financial.approve")).post(
            f"/api/v1/properties/{flow.prop}/refund-drafts/{uuid4()}/confirm",
            headers=mutation_headers(),
        )
        return answer
    corrector = api(flow, actor(flow.prop, "refunds.correct", "refunds.corrections.reverse"))
    if route == _VERIFY:
        flow.refund_service.verify_usd_return.side_effect = failure
        answer = corrector.post(
            f"/api/v1/refunds/{flow.refund}/verified-returns",
            json=_RETURN_BODY,
            headers=mutation_headers(),
        )
        return answer
    flow.refund_service.reverse_correction.side_effect = failure
    answer = corrector.post(
        f"/api/v1/refunds/{flow.refund}/verified-returns/{flow.correction}/reverse",
        json={"evidence_reference": "Bank statement", "reason": "Recorded in error"},
        headers=mutation_headers(),
    )
    return answer


@pytest.mark.parametrize(
    ("route", "message", "error", "status", "code"),
    [
        # A method or recipient chosen on the form is bad input; at confirm it is state.
        (
            _RECORD,
            "Refund Method is not active",
            RefundInvalidError,
            422,
            "REFUND_METHOD_NOT_AVAILABLE",
        ),
        (_CONFIRM, "Refund Method is not active", RefundInvalidError, 409, "REFUND_METHOD_OFF"),
        (
            _RECORD,
            "The Refund recipient must be a Signer of the Lease",
            RefundInvalidError,
            422,
            "REFUND_RECIPIENT_NOT_A_SIGNER",
        ),
        (
            _CONFIRM,
            "The Refund recipient must be a Signer of the Lease",
            RefundConflictError,
            409,
            "REFUND_RECIPIENT_NOT_SIGNER",
        ),
        (
            _CONFIRM,
            "Refund draft is stale: the payer has unpaid obligations",
            RefundInvalidError,
            409,
            "REFUND_PAYER_HAS_UNPAID",
        ),
        (
            _CONFIRM,
            "Refund draft amount is no longer available",
            RefundInvalidError,
            409,
            "REFUND_AMOUNT_NOT_AVAILABLE",
        ),
        (
            _CONFIRM,
            "Financial draft is already decided",
            RefundConflictError,
            409,
            "DRAFT_ALREADY_DECIDED",
        ),
        (
            _CONFIRM,
            "A Deposit receipt reversal draft for this Deposit is waiting",
            RefundConflictError,
            409,
            "REFUND_DEPOSIT_RECEIPT_REVERSAL_WAITING",
        ),
        (
            _CONFIRM,
            "Refund Credit recipient mismatch",
            RefundUnavailableError,
            409,
            "REFUND_CREDIT_FOR_ANOTHER_CUSTOMER",
        ),
        (
            _RECORD,
            "Only a Credit that a credit Adjustment released to a Customer other than the payer "
            "is refunded to that Customer",
            RefundConflictError,
            409,
            "REFUND_CREDIT_CUSTOMER_ONLY",
        ),
        (
            _VERIFY,
            "Refund requires its source-specific coordinated correction path",
            RefundInvalidError,
            409,
            "REFUND_RETURN_THROUGH_CORRECTION",
        ),
        (
            _VERIFY,
            "A closed Final Settlement's Pet Deposit Refund is corrected only through a "
            "post-settlement correction",
            RefundConflictError,
            409,
            "REFUND_RETURN_THROUGH_CORRECTION",
        ),
        (
            _VERIFY,
            "Refund correction requires exact demonstrated return evidence",
            RefundUnavailableError,
            422,
            "REFUND_RETURN_EVIDENCE_NOT_EXACT",
        ),
        (
            _REVERSE,
            "Returned Refund value is no longer available to reverse",
            RefundUnavailableError,
            409,
            "REFUND_RETURN_REVERSAL_REFUSED",
        ),
        (
            _REVERSE,
            "Refund correction reversal must reverse one active exact correction",
            RefundUnavailableError,
            409,
            "REFUND_RETURN_ALREADY_REVERSED",
        ),
    ],
)
def test_refund_command_refusals_answer_their_own_code(
    route: str, message: str, error: type[Exception], status: int, code: str
) -> None:
    answer = _refund_answer(Flow(), route, _refused(message, error))
    assert answer.status_code == status, answer.text
    assert answer.json()["error"]["code"] == code
    assert message not in answer.text


def test_each_draft_record_answers_a_method_from_the_form_as_bad_input() -> None:
    """Slice 11c-2 review round 2: the record table covers the Pet and CREDIT_CUSTOMER drafts."""
    flow = Flow()
    off = _refused("Refund Method is not active", RefundInvalidError)
    not_signer = _refused("The Refund recipient must be a Signer of the Lease", RefundInvalidError)
    drafter = api(flow, actor(flow.prop, "refunds.create"))
    flow.refund_service.record_credit_customer_draft.side_effect = off
    credit = drafter.post(
        "/api/v1/refund-drafts",
        json={
            **_draft_body(flow),
            "source_type": "CREDIT",
            "source_id": str(flow.credit),
            "variant": "CREDIT_CUSTOMER",
        },
        headers=mutation_headers(),
    )
    assert credit.status_code == 422
    assert credit.json()["error"]["code"] == "REFUND_METHOD_NOT_AVAILABLE"
    assert credit.json()["error"]["fields"] == ["refund_method_id"]
    pet_body = {
        **_draft_body(flow),
        "source_type": "PET_DEPOSIT",
        "source_id": str(uuid4()),
        "pet_refund_review_id": str(uuid4()),
        "recipient_customer_id": str(uuid4()),
        "signer_agreement": "Written agreement of every Signer",
    }
    for failure, code, field_name in (
        (off, "REFUND_METHOD_NOT_AVAILABLE", "refund_method_id"),
        (not_signer, "REFUND_RECIPIENT_NOT_A_SIGNER", "recipient_customer_id"),
    ):
        flow.refund_service.record_pet_draft.side_effect = failure
        pet = drafter.post("/api/v1/refund-drafts", json=pet_body, headers=mutation_headers())
        assert pet.status_code == 422, pet.text
        assert pet.json()["error"]["code"] == code
        assert pet.json()["error"]["fields"] == [field_name]


def test_a_credit_command_refused_by_a_closed_final_settlement_names_it() -> None:
    flow = Flow()
    flow.credit_service.reverse.side_effect = _refused(
        "A closed Final Settlement changes only through a post-settlement correction",
        CreditConflictError,
    )
    answer = api(flow, actor(flow.prop, "credits.reverse")).post(
        f"/api/v1/customer-credits/{flow.credit}/reverse",
        json={"reason": "Correct recognition"},
        headers=mutation_headers(),
    )
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "FINAL_SETTLEMENT_CLOSED"


def test_a_read_is_never_answered_with_a_command_refusal() -> None:
    flow = Flow()
    flow.refund_service.get.side_effect = _refused(
        "Refund Method is not active", RefundUnavailableError
    )
    answer = api(flow, actor(flow.prop, "refunds.read")).get(f"/api/v1/refunds/{flow.refund}")
    assert answer.status_code == 503
    assert "REFUND_METHOD" not in answer.text


def test_the_primary_tenant_agreement_refusal_stays_bad_input() -> None:
    flow = Flow()
    flow.refund_service.record_usd_draft.side_effect = _refused(
        "The Primary Tenant needs no Signer agreement", RefundInvalidError
    )
    answer = api(flow, actor(flow.prop, "refunds.create")).post(
        "/api/v1/refund-drafts", json=_draft_body(flow), headers=mutation_headers()
    )
    assert answer.status_code == 422
    assert "Primary Tenant" not in answer.text


def test_refund_methods_are_listed_for_a_refund_reader_preparer_or_property_manager() -> None:
    """V1-056 slice 11c-1 (BR-REFUND-014): the methods a Refund draft may name."""
    flow = Flow()
    method = {
        "id": str(uuid4()),
        "code": "CASH",
        "display_name": "Cash",
        "active": True,
        "seeded": True,
        "updated_at": "2026-10-24T10:00:00+00:00",
    }
    flow.refund_service.refund_methods.return_value = {"items": [method]}
    path = f"/api/v1/properties/{flow.prop}/refund-methods"
    assert api(flow, None).get(path).status_code == 401
    assert api(flow, actor(flow.prop, "payments.read")).get(path).status_code == 404
    assert api(flow, actor(uuid4(), "refunds.read")).get(path).status_code == 404
    flow.refund_service.refund_methods.assert_not_called()
    for capability in ("refunds.read", "refunds.create", "property.manage"):
        who = actor(flow.prop, capability)
        answer = api(flow, who).get(path)
        assert answer.status_code == 200, answer.text
        assert answer.json()["data"] == [method]
        assert answer.headers["cache-control"] == "private, no-store"
        flow.refund_service.refund_methods.assert_called_with(flow.prop, actor=who)
    assert api(flow, actor(flow.prop, "refunds.read")).get(f"{path}?x=1").status_code == 400
    flow.refund_service.refund_methods.return_value = {"items": [{"active": "yes"}]}
    assert api(flow, actor(flow.prop, "refunds.read")).get(path).status_code == 503


def _method(identity: UUID, *, active: bool = True) -> dict[str, object]:
    return {
        "id": str(identity),
        "code": "WING",
        "display_name": "Wing money transfer",
        "active": active,
        "seeded": False,
        "updated_at": "2026-10-25T10:00:00+00:00",
    }


def test_a_refund_method_is_added_only_with_settings_access() -> None:
    """V1-056 slice 11h (owner answer of 2026-10-25; BR-REFUND-014): only the Owner and people
    ticked for Settings access add a Refund method; it starts turned on."""
    flow = Flow()
    identity = uuid4()
    flow.refund_service.add_refund_method.return_value = _method(identity)
    path = f"/api/v1/properties/{flow.prop}/refund-methods"
    body = {
        "refund_method_id": str(identity),
        "code": "WING",
        "display_name": "Wing money transfer",
    }
    assert api(flow, None).post(path, json=body, headers=mutation_headers()).status_code == 401
    for capability in ("property.manage", "refunds.create", "financial.approve"):
        refused = api(flow, actor(flow.prop, capability)).post(
            path, json=body, headers=mutation_headers()
        )
        assert refused.status_code == 404
    assert api(flow, actor(flow.prop, "settings.manage")).post(path, json=body).status_code == 403
    flow.refund_service.add_refund_method.assert_not_called()
    who = actor(flow.prop, "settings.manage")
    answer = api(flow, who).post(path, json=body, headers=mutation_headers())
    assert answer.status_code == 201, answer.text
    assert answer.json()["data"] == _method(identity)
    command = flow.refund_service.add_refund_method.call_args.args[1]
    assert (command.refund_method_id, command.code, command.display_name) == (
        identity,
        "WING",
        "Wing money transfer",
    )
    for bad in (
        {**body, "code": "wing"},
        {**body, "code": "W"},
        {**body, "display_name": " Wing"},
        {**body, "display_name": ""},
        {**body, "display_name": "x" * 121},
        {**body, "extra": 1},
        {key: value for key, value in body.items() if key != "code"},
    ):
        assert api(flow, who).post(path, json=bad, headers=mutation_headers()).status_code == 422
    # A repeat of the request answers the method as it is now, turned off since included.
    flow.refund_service.add_refund_method.return_value = _method(identity, active=False)
    replay = api(flow, who).post(path, json=body, headers=mutation_headers())
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["active"] is False
    flow.refund_service.add_refund_method.return_value = _method(uuid4())
    assert api(flow, who).post(path, json=body, headers=mutation_headers()).status_code == 503


def test_a_refund_method_is_turned_off_or_on_only_with_settings_access() -> None:
    """V1-056 slice 11h: turning a Refund method off or on again needs Settings access."""
    flow = Flow()
    identity = uuid4()
    flow.refund_service.set_refund_method_on.return_value = _method(identity, active=False)
    path = f"/api/v1/properties/{flow.prop}/refund-methods/{identity}/state"
    assert (
        api(flow, actor(flow.prop, "property.manage"))
        .post(path, json={"active": False}, headers=mutation_headers())
        .status_code
        == 404
    )
    flow.refund_service.set_refund_method_on.assert_not_called()
    who = actor(flow.prop, "settings.manage")
    answer = api(flow, who).post(path, json={"active": False}, headers=mutation_headers())
    assert answer.status_code == 200, answer.text
    assert answer.json()["data"]["active"] is False
    flow.refund_service.set_refund_method_on.assert_called_with(
        flow.prop, identity, False, actor=who
    )
    for bad in ({"active": "false"}, {"active": 0}, {}, {"active": False, "reason": "x"}):
        assert api(flow, who).post(path, json=bad, headers=mutation_headers()).status_code == 422
    # The answer must show the state that was asked for.
    assert (
        api(flow, who).post(path, json={"active": True}, headers=mutation_headers()).status_code
        == 503
    )


@pytest.mark.parametrize(
    ("message", "code", "fields"),
    [
        ("Refund Method code is already used", "REFUND_METHOD_CODE_USED", ["code"]),
        ("Refund Method identity was reused", "REFUND_METHOD_ID_REUSED", ["refund_method_id"]),
        ("At least one Refund Method stays on", "REFUND_METHOD_LAST_ON", []),
    ],
)
def test_a_refused_refund_method_change_answers_409_with_its_code(
    message: str, code: str, fields: list[str]
) -> None:
    flow = Flow()
    identity = uuid4()
    error = _refused(message, RefundConflictError)
    flow.refund_service.add_refund_method.side_effect = error
    flow.refund_service.set_refund_method_on.side_effect = error
    who = actor(flow.prop, "settings.manage")
    client = api(flow, who)
    for path, body in (
        (
            f"/api/v1/properties/{flow.prop}/refund-methods",
            {"refund_method_id": str(identity), "code": "WING", "display_name": "Wing"},
        ),
        (f"/api/v1/properties/{flow.prop}/refund-methods/{identity}/state", {"active": False}),
    ):
        answer = client.post(path, json=body, headers=mutation_headers())
        assert answer.status_code == 409, answer.text
        assert answer.json()["error"]["code"] == code
        assert answer.json()["error"]["fields"] == fields


def test_a_settings_access_holder_reads_the_refund_methods() -> None:
    """V1-056 slice 11h: the Settings screen lists the methods it changes."""
    flow = Flow()
    flow.refund_service.refund_methods.return_value = {"items": [_method(uuid4())]}
    who = actor(flow.prop, "settings.manage")
    answer = api(flow, who).get(f"/api/v1/properties/{flow.prop}/refund-methods")
    assert answer.status_code == 200, answer.text


class _Sqlstate(psycopg.Error):
    def __init__(self, sqlstate: str) -> None:
        self._sqlstate = sqlstate
        super().__init__("refused")

    @property
    def sqlstate(self) -> str:  # type: ignore[override]
        return self._sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "error"),
    [
        ("P0002", RefundNotFoundError),
        ("22023", RefundInvalidError),
        ("42501", RefundAuthorizationError),
        ("23505", RefundConflictError),
        ("55000", RefundConflictError),
        ("40P01", RefundConflictError),
        ("40001", RefundConflictError),
        ("57014", RefundUnavailableError),
    ],
)
def test_the_refund_method_service_maps_each_database_answer(
    sqlstate: str, error: type[Exception]
) -> None:
    prop = uuid4()
    service = RefundService("runtime", "")
    who = actor(prop, "settings.manage")
    with patch.object(RefundService, "_attempt", side_effect=_Sqlstate(sqlstate)):
        with pytest.raises(error):
            service.set_refund_method_on(prop, uuid4(), False, actor=who)
        with pytest.raises(error):
            service.add_refund_method(
                prop, AddRefundMethodCommand(uuid4(), "WING", "Wing"), actor=who
            )
    with pytest.raises(RefundAuthorizationError):
        service.set_refund_method_on(prop, uuid4(), False, actor=actor(prop, "property.manage"))
    with pytest.raises(RefundInvalidError):
        AddRefundMethodCommand(uuid4(), "wing", "Wing")
    with pytest.raises(RefundInvalidError):
        AddRefundMethodCommand(uuid4(), "WING", " Wing")
