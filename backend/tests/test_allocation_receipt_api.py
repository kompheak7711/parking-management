"""Full-app boundaries for the eight explicit Allocation/Receipt endpoints."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from property_rental.allocation_read import AllocationHistoryPage
from property_rental.allocation_receipt_api import (
    MAX_ALLOCATION_RECEIPT_BODY_BYTES,
    PostgresAllocationReceiptFlow,
    Resource,
    _history_page,
)
from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationIdempotencyKeyReused,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
)
from property_rental.payment_api import _cursor
from property_rental.receipt import (
    ReceiptAuthorizationError,
    ReceiptIdempotencyKeyReused,
    ReceiptInvalidError,
    ReceiptNotFoundError,
    ReceiptUnavailableError,
    ReprintReceiptCommand,
)
from test_invoice import actor, mutation_headers
from test_payment_read import connection


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    payment: UUID = field(default_factory=uuid4)
    allocation: UUID = field(default_factory=uuid4)
    receipt_id: UUID = field(default_factory=uuid4)
    event: UUID = field(default_factory=uuid4)
    calls: list[tuple[str, object]] = field(default_factory=list)
    error: Exception | None = None

    def resolve(
        self,
        resource: Resource,
        identity: UUID,
        capability: str,
        *,
        actor: AuthenticatedActor,
    ) -> UUID:
        self.calls.append(("resolve", (resource, identity, capability, actor)))
        return self.prop

    def result(self, operation: str, value: object) -> None:
        self.calls.append((operation, value))
        if self.error is not None:
            raise self.error

    def proposal(
        self, prop: UUID, payment: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.result("proposal", (prop, payment, actor))
        return {
            "property_id": str(prop),
            "payment_id": str(payment),
            "targets": [],
            "available_usd_cents": 9_000_000_000_000_000,
        }

    def history(
        self,
        prop: UUID,
        payment: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
        allocation_id: UUID | None,
    ) -> dict[str, object]:
        self.result("history", (prop, payment, page, actor, allocation_id))
        return {
            "property_id": str(prop),
            "payment_id": str(payment),
            "allocation": {
                "id": str(allocation_id),
                "proposal_trace": {"original": True},
            }
            if allocation_id
            else None,
            "items": [
                {
                    "id": str(self.allocation),
                    "amount_usd_cents": 9_223_372_036_854_775_807,
                }
            ],
            "next_cursor": {
                "payment_id": str(payment),
                "allocation_id": str(allocation_id) if allocation_id else None,
                "after_id": str(self.allocation),
            },
        }

    def post(
        self,
        prop: UUID,
        payment: UUID,
        command: PostAllocationsCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.result("post", (prop, payment, command, actor))
        return {
            "payment_id": str(payment),
            "allocation_ids": [str(self.allocation)],
            "available_usd_cents": 0,
        }

    def reverse_allocation(
        self,
        prop: UUID,
        allocation: UUID,
        command: ReverseAllocationCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.result("reverse_allocation", (prop, allocation, command, actor))
        return {"allocation_id": str(allocation), "reversal_id": str(self.event)}

    def reverse_payment(
        self,
        prop: UUID,
        payment: UUID,
        command: ReversePaymentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.result("reverse_payment", (prop, payment, command, actor))
        return {
            "payment_id": str(payment),
            "status": "REVERSED",
            "reversal_id": str(self.event),
        }

    def receipt(
        self, prop: UUID, identity: UUID, *, actor: AuthenticatedActor, by_payment: bool
    ) -> dict[str, object]:
        self.result("receipt", (prop, identity, actor, by_payment))
        return {
            "receipt": {
                "id": str(self.receipt_id),
                "payment_id": str(self.payment),
                "receipt_number": "R-1",
            },
            "payment": {"id": str(self.payment), "property_id": str(prop)},
            "fx": {"system_rate_khr_per_usd": "4062.123456"},
        }

    def receipt_history(
        self,
        prop: UUID,
        receipt: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.result("receipt_history", (prop, receipt, page, actor))
        return {
            "events": [{"id": str(self.event), "receipt_id": str(receipt)}],
            "has_more": True,
        }

    def reprint(
        self,
        prop: UUID,
        receipt: UUID,
        command: ReprintReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.result("reprint", (prop, receipt, command, actor))
        return {"receipt_id": str(receipt), "reprint": {"id": str(self.event)}}


def api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, allocation_receipt_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def routes(flow: Flow) -> list[tuple[str, str, dict[str, object] | None, str, str]]:
    payment, allocation, receipt = (
        str(flow.payment),
        str(flow.allocation),
        str(flow.receipt_id),
    )
    return [
        (
            "GET",
            f"/api/v1/payments/{payment}/allocation-proposal",
            None,
            "payments.allocate",
            "proposal",
        ),
        (
            "POST",
            f"/api/v1/payments/{payment}/allocations",
            {
                "intent": {
                    "mode": "DIRECT_CHARGE",
                    "late_payment_charge_id": str(uuid4()),
                    "amount_usd_cents": 1,
                }
            },
            "payments.allocate",
            "post",
        ),
        (
            "GET",
            f"/api/v1/payments/{payment}/allocations",
            None,
            "payments.read",
            "history",
        ),
        (
            "POST",
            f"/api/v1/payment-allocations/{allocation}/reverse",
            {"reason": "Correct target"},
            "payments.allocations.reverse",
            "reverse_allocation",
        ),
        (
            "POST",
            f"/api/v1/payments/{payment}/reverse",
            {"reason": "Duplicate", "expected_status": "RECEIVED"},
            "payments.reverse",
            "reverse_payment",
        ),
        (
            "GET",
            f"/api/v1/payments/{payment}/receipt",
            None,
            "receipts.read",
            "receipt",
        ),
        ("GET", f"/api/v1/receipts/{receipt}", None, "receipts.read", "receipt"),
        (
            "POST",
            f"/api/v1/receipts/{receipt}/reprints",
            {"reason": "Requested copy", "delivery_reference": "Counter"},
            "receipts.reprint",
            "reprint",
        ),
    ]


@pytest.mark.parametrize("index", range(8))
def test_allocation_receipt_http_exact_routes_actor_scope_and_private_envelopes(
    index: int,
) -> None:
    flow = Flow()
    method, path, body, capability, operation = routes(flow)[index]
    who = actor(flow.prop, capability)
    key = uuid4()
    headers = {
        **mutation_headers(key=key),
        "X-Billing-Actor-ID": who.actor_id,
        "X-Request-ID": "allocation-receipt-boundary",
    }
    response = api(flow, who).request(method, path, json=body, headers=headers)
    assert response.status_code == (201 if operation == "post" else 200), response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert response.json()["meta"]["request_id"] == headers["X-Request-ID"]
    resolution = cast(tuple[Resource, UUID, str, AuthenticatedActor], flow.calls[0][1])
    assert resolution[2:] == (capability, who)
    assert operation in [name for name, _ in flow.calls]
    call = next(value for name, value in flow.calls if name == operation)
    if method == "POST":
        prop, _, command, actual_actor = cast(
            tuple[
                UUID,
                UUID,
                PostAllocationsCommand
                | ReverseAllocationCommand
                | ReversePaymentCommand
                | ReprintReceiptCommand,
                AuthenticatedActor,
            ],
            call,
        )
        assert prop == flow.prop and actual_actor is who and command.idempotency_key == key
        if operation != "post":
            assert isinstance(
                command, (ReverseAllocationCommand, ReversePaymentCommand, ReprintReceiptCommand)
            )
            assert body is not None and command.reason == body["reason"]
    if operation == "post":
        assert response.headers["location"] == f"/api/v1/payments/{flow.payment}/allocations"
    if operation == "history":
        assert response.json()["data"][0]["amount_usd_cents"] == 9_223_372_036_854_775_807
    if operation == "receipt":
        assert response.json()["data"]["fx"]["system_rate_khr_per_usd"] == "4062.123456"


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize(
    "denial", ["anonymous", "other_capability", "other_property", "different_actor"]
)
def test_allocation_receipt_http_denies_before_financial_dispatch(index: int, denial: str) -> None:
    flow = Flow()
    method, path, body, capability, _ = routes(flow)[index]
    who = (
        None
        if denial == "anonymous"
        else actor(
            uuid4() if denial == "other_property" else flow.prop,
            "payments.record" if denial == "other_capability" else capability,
        )
    )
    headers = mutation_headers()
    if denial == "different_actor":
        headers["X-Billing-Actor-ID"] = str(uuid4())
    response = api(flow, who).request(method, path, json=body, headers=headers)
    assert response.status_code == (
        401 if denial == "anonymous" else 403 if denial == "different_actor" else 404
    )
    assert all(name == "resolve" for name, _ in flow.calls)
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("index", [1, 3, 4, 7])
@pytest.mark.parametrize(
    "boundary",
    ["csrf_missing", "wrong_origin", "key_missing", "duplicate_key", "duplicate_actor"],
)
def test_allocation_receipt_mutations_require_browser_and_single_command_identity(
    index: int, boundary: str
) -> None:
    flow = Flow()
    method, path, body, capability, _ = routes(flow)[index]
    who = actor(flow.prop, capability)
    headers = mutation_headers()
    if boundary == "csrf_missing":
        del headers["X-CSRF-Token"]
    if boundary == "wrong_origin":
        headers["Origin"] = "https://untrusted.example"
    if boundary == "key_missing":
        del headers["Idempotency-Key"]
    values = list(headers.items())
    if boundary == "duplicate_key":
        values.append(("Idempotency-Key", str(uuid4())))
    if boundary == "duplicate_actor":
        values.extend([("X-Billing-Actor-ID", who.actor_id)] * 2)
    result = api(flow, who).request(method, path, json=body, headers=values)
    assert result.status_code in {400, 403, 422}
    assert flow.calls == []


@pytest.mark.parametrize(
    "error,code",
    [
        (AllocationNotFoundError, 404),
        (AllocationAuthorizationError, 404),
        (ReceiptNotFoundError, 404),
        (ReceiptAuthorizationError, 404),
        (AllocationInvalidError, 422),
        (ReceiptInvalidError, 422),
        (AllocationConflictError, 409),
        (AllocationUnavailableError, 503),
        (ReceiptUnavailableError, 503),
        (AllocationIdempotencyKeyReused, 409),
        (ReceiptIdempotencyKeyReused, 409),
    ],
)
def test_allocation_receipt_error_families_map_to_safe_full_app_responses(
    error: type[Exception], code: int
) -> None:
    flow = Flow(error=error("private SQL evidence"))
    method, path, body, capability, _ = routes(flow)[1]
    response = api(flow, actor(flow.prop, capability)).request(
        method, path, json=body, headers=mutation_headers()
    )
    assert response.status_code == code
    assert "private" not in response.text and "SQL" not in response.text
    if error in (AllocationIdempotencyKeyReused, ReceiptIdempotencyKeyReused):
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("index", [1, 3, 4, 7])
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-32", "utf-32-be"])
def test_allocation_receipt_rejects_non_utf8_before_dispatch(index: int, encoding: str) -> None:
    flow = Flow()
    method, path, body, capability, _ = routes(flow)[index]
    response = api(flow, actor(flow.prop, capability)).request(
        method,
        path,
        content=json.dumps(body).encode(encoding),
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == 400 and flow.calls == []


@pytest.mark.parametrize(
    "raw",
    [
        b'{"reason":"first","reason":"second"}',
        b'{"reason":NaN}',
        b'{"reason":"\\ud800"}',
        b'{"reason":"ok","nested":{"a":1,"a":2}}',
    ],
)
def test_allocation_receipt_rejects_duplicate_non_json_and_invalid_unicode(
    raw: bytes,
) -> None:
    flow = Flow()
    path = f"/api/v1/receipts/{flow.receipt_id}/reprints"
    response = api(flow, actor(flow.prop, "receipts.reprint")).post(
        path,
        content=raw,
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422} and flow.calls == []


def test_allocation_http_accepts_large_exact_intent_but_preserves_canonical_budget() -> None:
    flow = Flow()
    client = api(flow, actor(flow.prop, "payments.allocate"))
    path = f"/api/v1/payments/{flow.payment}/allocations"
    body = {"intent": {"mode": "PROPOSAL", "proposal": {"evidence": "ក" * 60_000}}}
    result = client.post(
        path,
        content=json.dumps(body, ensure_ascii=False).encode(),
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    assert result.status_code == 201
    flow.calls.clear()
    oversized = {"intent": {"mode": "PROPOSAL", "proposal": {"evidence": "x" * 250_000}}}
    assert client.post(path, json=oversized, headers=mutation_headers()).status_code == 422
    assert all(name == "resolve" for name, _ in flow.calls)


@pytest.mark.parametrize("amount", [True, 1.5, "1", 0, -1, 9_000_000_000_000_001])
def test_allocation_http_rejects_inexact_or_out_of_range_money(amount: object) -> None:
    flow = Flow()
    method, path, body, capability, _ = routes(flow)[1]
    assert body is not None
    cast(dict[str, object], body["intent"])["amount_usd_cents"] = amount
    response = api(flow, actor(flow.prop, capability)).request(
        method, path, json=body, headers=mutation_headers()
    )
    assert response.status_code == 422
    assert all(name == "resolve" for name, _ in flow.calls)


def test_allocation_and_receipt_cursor_grammar_is_opaque_and_bound_to_selected_resource() -> None:
    payment, allocation, receipt, after = (uuid4() for _ in range(4))
    cursor = _cursor(
        {
            "payment_id": str(payment),
            "allocation_id": str(allocation),
            "after_id": str(after),
        }
    )
    assert _history_page(1, cursor, resource_id=payment, allocation_id=allocation).after_id == after
    for selected_payment, selected_allocation in [
        (uuid4(), allocation),
        (payment, uuid4()),
        (payment, None),
    ]:
        with pytest.raises(Exception) as caught:
            _history_page(
                1,
                cursor,
                resource_id=selected_payment,
                allocation_id=selected_allocation,
            )
        assert getattr(caught.value, "status_code", None) == 400
    receipt_cursor = _cursor({"receipt_id": str(receipt), "after_id": str(after)})
    assert _history_page(1, receipt_cursor, resource_id=receipt, receipt=True).after_id == after
    with pytest.raises(Exception) as caught:
        _history_page(1, receipt_cursor, resource_id=uuid4(), receipt=True)
    assert getattr(caught.value, "status_code", None) == 400


@pytest.mark.parametrize("resource", ["payment", "allocation", "receipt"])
def test_financial_scope_resolution_rechecks_active_human_before_financial_lookup(
    resource: Resource,
) -> None:
    prop = uuid4()
    who = actor(prop, "receipts.read")
    conn = connection()
    conn.execute.return_value.fetchone.return_value = (False,)
    with (
        patch("property_rental.allocation_receipt_api.psycopg.connect", return_value=conn),
        pytest.raises(AllocationAuthorizationError),
    ):
        PostgresAllocationReceiptFlow("runtime", "writer").resolve(
            resource, uuid4(), "receipts.read", actor=who
        )
    assert len(conn.execute.call_args_list) == 4


@pytest.mark.parametrize("content_length", [None, "1", "9999999"])
@pytest.mark.parametrize("path_kind", ["allocation", "receipt"])
def test_allocation_receipt_streaming_limit_stops_before_json_decode_or_dispatch(
    content_length: str | None, path_kind: str
) -> None:
    flow = Flow()
    app = create_app(
        actor_resolver=lambda _: actor(flow.prop, "payments.allocate", "receipts.reprint"),
        allocation_receipt_flow=flow,
    )
    path = (
        f"/api/v1/payments/{flow.payment}/allocations"
        if path_kind == "allocation"
        else f"/api/v1/receipts/{flow.receipt_id}/reprints"
    )
    headers = {
        **mutation_headers(),
        "Content-Type": "application/json",
        "Cookie": "__Host-prm_csrf=csrf",
    }
    if content_length is not None:
        headers["Content-Length"] = content_length
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 1234),
    }
    chunks = [b" " * MAX_ALLOCATION_RECEIPT_BODY_BYTES, b" ", b"never consumed"]
    consumed = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal consumed
        if consumed == len(chunks):
            await asyncio.Event().wait()
            raise AssertionError("Response completion cancels the listener")
        body = chunks[consumed]
        consumed += 1
        return {"type": "http.request", "body": body, "more_body": True}

    async def send(message: Message) -> None:
        sent.append(message)

    with patch(
        "json.loads",
        side_effect=AssertionError("Oversized request must not be decoded"),
    ):
        asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 400 and consumed == 2 and flow.calls == []


@pytest.mark.parametrize("index", [0, 2, 5, 6])
@pytest.mark.parametrize("query", ["unknown=secret", "limit=1&limit=2", "limit=01", "limit=1.0"])
def test_allocation_receipt_http_rejects_unsupported_or_ambiguous_query_grammar(
    index: int, query: str
) -> None:
    flow = Flow()
    method, path, _, capability, _ = routes(flow)[index]
    response = api(flow, actor(flow.prop, capability)).request(method, path + "?" + query)
    assert response.status_code == 400
    assert flow.calls == [] and "secret" not in response.text


@pytest.mark.parametrize(
    "index,body",
    [
        (3, {"reason": "   "}),
        (3, {"reason": ""}),
        (3, {"reason": "x" * 1001}),
        (4, {"reason": "Expected state is required"}),
        (4, {"reason": "Unsupported state", "expected_status": "REVERSED"}),
        (7, {"reason": "Copy", "property_id": str(uuid4())}),
        (7, {"reason": "Copy", "delivery_reference": " trailing "}),
    ],
)
def test_allocation_receipt_http_requires_normalized_reasons_explicit_state_and_strict_schema(
    index: int, body: dict[str, object]
) -> None:
    flow = Flow()
    method, path, _, capability, _ = routes(flow)[index]
    response = api(flow, actor(flow.prop, capability)).request(
        method, path, json=body, headers=mutation_headers()
    )
    assert response.status_code == 422
    assert all(name == "resolve" for name, _ in flow.calls)


def test_allocation_receipt_http_exact_raw_body_boundary_and_unicode_reason_are_preserved() -> None:
    flow = Flow()
    who = actor(flow.prop, "receipts.reprint")
    reason = "បង្កាន់ដៃ café original copy"
    body = json.dumps({"reason": reason}, ensure_ascii=False).encode("utf-8")
    body += b" " * (MAX_ALLOCATION_RECEIPT_BODY_BYTES - len(body))
    path = f"/api/v1/receipts/{flow.receipt_id}/reprints"
    response = api(flow, who).post(
        path, content=body, headers={**mutation_headers(), "Content-Type": "application/json"}
    )
    assert response.status_code == 200
    command = cast(tuple[UUID, UUID, ReprintReceiptCommand, AuthenticatedActor], flow.calls[-1][1])[
        2
    ]
    assert command.reason == reason
    flow.calls.clear()
    oversized = api(flow, who).post(
        path,
        content=body + b" ",
        headers={**mutation_headers(), "Content-Type": "application/json"},
    )
    assert oversized.status_code == 400 and flow.calls == []
