"""The full financial route set binds selected Property without altering money events."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from test_allocation_receipt_api import Flow as AllocationFlow
from test_allocation_receipt_api import api as allocation_api
from test_allocation_receipt_api import routes as allocation_routes
from test_credit_refund_api import Flow as CreditFlow
from test_credit_refund_api import api as credit_api
from test_credit_refund_api import routes as credit_routes
from test_invoice import actor, mutation_headers
from test_payment_api import Flow as PaymentFlow
from test_payment_api import api as payment_api
from test_payment_api import payload

HEADER = "X-Financial-Property-ID"


@dataclass
class Boundary:
    client: TestClient
    property_id: UUID
    method: str
    path: str
    body: dict[str, object] | None
    params: dict[str, str]
    headers: dict[str, str]
    status: int
    dispatched: Callable[[], bool]


def boundary(index: int, denial: Literal["anonymous", "grant"] | None = None) -> Boundary:
    """Use existing accepted service doubles and the actual FastAPI routers."""
    if index < 3:
        payment = PaymentFlow()
        prop = payment.property_id
        capability = "payments.record" if index == 2 else "payments.read"
        method = "POST" if index == 2 else "GET"
        path = (
            f"/api/v1/payments/{payment.payment_id}"
            if index == 1
            else f"/api/v1/properties/{prop}/payments"
        )
        body = payload() if index == 2 else None
        params: dict[str, str] = {}
        status = 201 if index == 2 else 200
        # Detail's authorized read resolves its Property; all effects remain forbidden.

        def dispatched() -> bool:
            return bool(payment.calls) and index != 1
    elif index < 11:
        allocation = AllocationFlow()
        prop = allocation.prop
        method, path, body, capability, operation = allocation_routes(allocation)[index - 3]
        params = {}
        status = 201 if operation == "post" else 200

        def dispatched() -> bool:
            return any(name != "resolve" for name, _ in allocation.calls)
    else:
        credit = CreditFlow()
        prop = credit.prop
        route = credit_routes(credit)[index - 11]
        method, path, body = route.method, "/api/v1" + route.path, route.body
        capability, params = route.capability, route.params
        status = 201 if index - 11 in (3, 6, 12) else 200
        if index - 11 == 12:
            # V1-056 slice 3a: a Refund is created through its draft; POST /refunds records nothing.
            path = "/api/v1/refund-drafts"
            body = {**(body or {}), "refund_method_id": str(uuid4()), "reference_note": "Cash"}
            credit.refund_service.record_usd_draft.return_value = {
                "draft_id": str(uuid4()),
                "property_id": str(prop),
                "kind": "REFUND",
            }

        def dispatched() -> bool:
            return any(name != "resolve" for name, _ in credit.calls)

    who = actor(prop, capability)
    headers = {**mutation_headers(), "X-Billing-Actor-ID": who.actor_id}
    authenticated = None if denial == "anonymous" else who
    if denial == "grant":
        authenticated = replace(who, capability_grants=frozenset())
    client = (
        payment_api(payment, authenticated)
        if index < 3
        else allocation_api(allocation, authenticated)
        if index < 11
        else credit_api(credit, authenticated)
    )
    return Boundary(client, prop, method, path, body, params, headers, status, dispatched)


@pytest.mark.parametrize("index", range(26))
@pytest.mark.parametrize("mode", ["absent", "matching", "uppercase"])
def test_financial_context_all_routes_report_authorized_property(index: int, mode: str) -> None:
    case = boundary(index)
    headers = dict(case.headers)
    if mode != "absent":
        value = str(case.property_id)
        headers[HEADER] = value.upper() if mode == "uppercase" else value
    response = case.client.request(
        case.method, case.path, json=case.body, params=case.params, headers=headers
    )
    assert response.status_code == case.status
    assert response.json()["meta"] == {
        "request_id": response.headers["x-request-id"],
        "property_id": str(case.property_id),
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert "Cookie" in response.headers["vary"]


@pytest.mark.parametrize("index", range(26))
def test_financial_context_rejects_mismatched_property_before_dispatch(index: int) -> None:
    case = boundary(index)
    response = case.client.request(
        case.method,
        case.path,
        json=case.body,
        params=case.params,
        headers={**case.headers, HEADER: str(uuid4())},
    )
    assert response.status_code == 404
    assert not case.dispatched()
    assert "data" not in response.json() and "property_id" not in response.json()["meta"]
    assert str(case.property_id) not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("index", range(26))
@pytest.mark.parametrize("mode", ["empty", "malformed", "zero", "compact", "duplicate", "combined"])
def test_financial_context_rejects_invalid_headers_without_dispatch(index: int, mode: str) -> None:
    case = boundary(index)
    values = {
        "empty": "",
        "malformed": "private-path/../untrusted",
        "zero": str(UUID(int=0)),
        "compact": case.property_id.hex,
        "duplicate": str(case.property_id),
        "combined": f"{case.property_id},{case.property_id}",
    }
    headers = [*case.headers.items(), (HEADER, values[mode])]
    if mode == "duplicate":
        headers.append((HEADER.lower(), str(case.property_id)))
    response = case.client.request(
        case.method, case.path, json=case.body, params=case.params, headers=headers
    )
    assert response.status_code == 400
    assert not case.dispatched()
    assert str(case.property_id) not in response.text and "private-path" not in response.text
    assert "property_id" not in response.json()["meta"]


@pytest.mark.parametrize("index", range(26))
@pytest.mark.parametrize("denial", ["anonymous", "grant"])
def test_financial_context_never_replaces_authorization(
    index: int, denial: Literal["anonymous", "grant"]
) -> None:
    case = boundary(index, denial)
    response = case.client.request(
        case.method,
        case.path,
        json=case.body,
        params=case.params,
        headers={**case.headers, HEADER: "malformed"},
    )
    assert response.status_code == (
        401 if denial == "anonymous" else 403 if index != 1 and index < 3 else 404
    )
    assert not case.dispatched()
    assert "property_id" not in response.json()["meta"]


def test_financial_context_replay_preserves_original_data_and_request_key() -> None:
    flow = PaymentFlow()
    who = actor(flow.property_id, "payments.record")
    client = payment_api(flow, who)
    body = payload("KHR")
    headers = {**mutation_headers(), "X-Billing-Actor-ID": who.actor_id}
    path = f"/api/v1/properties/{flow.property_id}/payments"
    original = client.post(path, json=body, headers=headers)
    replay = client.post(path, json=body, headers={**headers, HEADER: str(flow.property_id)})
    assert original.status_code == replay.status_code == 201
    assert original.json()["data"] == replay.json()["data"]
    assert original.headers["location"] == replay.headers["location"]
    assert len(flow.responses) == 1
    mismatch = client.post(path, json=body, headers={**headers, HEADER: str(uuid4())})
    assert mismatch.status_code == 404 and len(flow.calls) == 2 and len(flow.responses) == 1
    assert replay.json()["meta"]["property_id"] == str(flow.property_id)


def test_financial_context_empty_page_still_identifies_authorized_scope() -> None:
    flow = CreditFlow()
    flow.credit_service.list.return_value = {"items": [], "next_cursor": None}
    client = credit_api(flow, actor(flow.prop, "credits.read"))
    response = client.get(f"/api/v1/customers/{flow.customer}/credits")
    assert response.status_code == 200 and response.json()["data"] == []
    assert response.json()["meta"]["property_id"] == str(flow.prop)
    assert response.json()["page"] == {"limit": 50, "next_cursor": None}


@pytest.mark.parametrize("index", range(26))
def test_financial_context_preserves_resource_data_pages_and_locations(index: int) -> None:
    case = boundary(index)
    original = case.client.request(
        case.method, case.path, json=case.body, params=case.params, headers=case.headers
    )
    checked = case.client.request(
        case.method,
        case.path,
        json=case.body,
        params=case.params,
        headers={**case.headers, HEADER: str(case.property_id)},
    )
    assert original.status_code == checked.status_code == case.status
    assert original.json()["data"] == checked.json()["data"]
    assert original.json().get("page") == checked.json().get("page")
    assert original.headers.get("location") == checked.headers.get("location")
    assert checked.json()["meta"]["property_id"] == str(case.property_id)
