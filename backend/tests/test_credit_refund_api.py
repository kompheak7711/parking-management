"""Full-app Credit/USD Refund transport, exact commands and bounded histories."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
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
    CreatePetRefundCommand,
    RefundAuthorizationError,
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
        for name in ("get", "create_usd", "create_pet", "verify_usd_return", "reverse_correction"):
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
    route = routes(flow)[12 if error.__name__.startswith("Refund") else 3]
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
    assert response.status_code == 201, response.text
    flow.refund_service.create_usd.assert_not_called()
    request = flow.refund_service.create_pet.call_args.args[1]
    assert isinstance(request, CreatePetRefundCommand)
    assert request.deposit_id == deposit and request.pet_refund_review_id == review


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
