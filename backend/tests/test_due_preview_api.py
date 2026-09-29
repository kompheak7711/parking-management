"""Full-app POST preview reads retain browser, scope and exact-input boundaries."""

import json
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from property_rental.allocation_receipt_api import PostgresAllocationReceiptFlow
from property_rental.credit import (
    CreditAuthorizationError,
    CreditConflictError,
    CreditInvalidError,
    CreditNotFoundError,
    CreditUnavailableError,
)
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
)
from test_allocation_receipt_api import Flow as PaymentFlow
from test_allocation_receipt_api import api as payment_api
from test_credit_refund_api import Flow as CreditFlow
from test_credit_refund_api import api as credit_api
from test_due_preview import KINDS, Kind, selected_target, selection
from test_invoice import actor, mutation_headers


def setup(
    kind: Kind, mode: str = "default", denial: str = ""
) -> tuple[Any, Any, str, dict[str, Any], Any]:
    flow: Any = PaymentFlow() if kind == "PAYMENT" else CreditFlow()
    cap = "payments.allocate" if kind == "PAYMENT" else "credits.apply"
    who = (
        None
        if denial == "anonymous"
        else actor(
            uuid4() if denial == "other_property" else flow.prop,
            "payments.read" if denial == "other_capability" else cap,
        )
    )
    body: dict[str, Any] = {"intent": selection(kind, mode)}
    if kind == "PAYMENT":
        client = payment_api(flow, who)
        path = f"/api/v1/payments/{flow.payment}/allocation-preview"
    else:
        client = credit_api(flow, who)
        path = f"/api/v1/customer-credits/{flow.credit}/application-preview"
        body["currency"] = "USD"
        flow.credit_service.application_preview.return_value = {
            "property_id": str(flow.prop),
            "credit_id": str(flow.credit),
            "intent": body["intent"],
        }
    return flow, client, path, body, who


def headers() -> dict[str, str]:
    values = mutation_headers()
    del values["Idempotency-Key"]
    return values


def no_preview(kind: Kind, flow: Any) -> None:
    if kind == "PAYMENT":
        assert all(name == "resolve" for name, _ in flow.calls)
    else:
        assert not flow.credit_service.mock_calls and not flow.refund_service.mock_calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["default", "explicit", "charge"])
def test_due_http_preview_is_a_scoped_read_with_exact_selected_body(kind: Kind, mode: str) -> None:
    flow, client, path, body, who = setup(kind, mode)
    h = headers() | {"X-Financial-Property-ID": str(flow.prop), "X-Request-ID": str(uuid4())}
    response = client.post(path, json=body, headers=h)
    assert response.status_code == 200
    assert "location" not in response.headers
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert response.json()["meta"] == {
        "request_id": h["X-Request-ID"],
        "property_id": str(flow.prop),
    }
    assert response.json()["data"]["intent"] == body["intent"]
    if kind == "PAYMENT":
        assert [name for name, _ in flow.calls] == ["resolve", "designation_preview"]
        assert flow.calls[-1][1] == (flow.prop, flow.payment, body["intent"], who)
    else:
        assert [name for name, _ in flow.calls] == ["resolve", "credits"]
        assert flow.calls[-1] == ("credits", False)
        flow.credit_service.application_preview.assert_called_once_with(
            flow.prop, flow.credit, body["intent"], actor=who
        )
        flow.credit_service.apply.assert_not_called()
        assert not flow.refund_service.mock_calls


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "denial", ["anonymous", "other_capability", "other_property", "different_actor"]
)
def test_due_http_preview_denies_actor_and_scope_before_read_dispatch(
    kind: Kind, denial: str
) -> None:
    flow, client, path, body, _ = setup(kind, denial=denial)
    h = headers()
    if denial == "different_actor":
        h["X-Billing-Actor-ID"] = str(uuid4())
    response = client.post(path, json=body, headers=h)
    assert response.status_code == (
        401 if denial == "anonymous" else 403 if denial == "different_actor" else 404
    )
    no_preview(kind, flow)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case",
    [
        "csrf_missing",
        "cookie_missing",
        "origin_wrong",
        "key_present",
        "duplicate_csrf",
        "duplicate_origin",
        "duplicate_actor",
        "duplicate_key",
        "wrong_expected_property",
        "duplicate_property",
        "query",
        "duplicate_query",
    ],
)
def test_due_http_preview_retains_browser_controls_and_rejects_command_identity(
    kind: Kind, case: str
) -> None:
    flow, client, path, body, who = setup(kind)
    h = headers()
    expected = 400
    if case == "csrf_missing":
        del h["X-CSRF-Token"]
        expected = 403
    elif case == "cookie_missing":
        client.cookies.clear()
        expected = 403
    elif case == "origin_wrong":
        h["Origin"] = "https://untrusted.invalid"
        expected = 403
    elif case == "key_present":
        h["Idempotency-Key"] = str(uuid4())
    elif case == "wrong_expected_property":
        h["X-Financial-Property-ID"] = str(uuid4())
        expected = 404
    elif case == "query":
        path += "?unexpected=1"
    elif case == "duplicate_query":
        path += "?unexpected=1&unexpected=2"
    duplicate = {
        "duplicate_csrf": "X-CSRF-Token",
        "duplicate_origin": "Origin",
        "duplicate_actor": "X-Billing-Actor-ID",
        "duplicate_key": "Idempotency-Key",
        "duplicate_property": "X-Financial-Property-ID",
    }.get(case)
    values = list(h.items())
    if duplicate:
        values = [(key, value) for key, value in values if key.lower() != duplicate.lower()]
        value = (
            "csrf"
            if duplicate == "X-CSRF-Token"
            else "https://localhost"
            if duplicate == "Origin"
            else str(uuid4())
        )
        if duplicate == "X-Billing-Actor-ID":
            value = who.actor_id
        values += [(duplicate, value), (duplicate, value)]
    response = client.post(path, json=body, headers=values)
    assert response.status_code == expected
    no_preview(kind, flow)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "case",
    [
        "mode",
        "extra_body",
        "currency",
        "bool",
        "float",
        "total",
        "computed",
        "source_extra",
        "nul",
        "empty",
        "duplicate_json",
        "nonfinite",
        "not_json",
        "oversize",
    ],
)
def test_due_http_preview_rejects_invalid_or_unbounded_body_before_service(
    kind: Kind, case: str
) -> None:
    flow, client, path, body, _ = setup(kind, "explicit")
    target = selected_target(kind, body["intent"])
    expected = 422
    if case == "mode":
        body["intent"]["mode"] = "PROPOSAL"
    elif case == "extra_body":
        body["idempotency_key"] = str(uuid4())
    elif case == "currency":
        body["currency"] = "KHR"
    elif case == "bool":
        target["amount_usd_cents"] = True
    elif case == "float":
        target["amount_usd_cents"] = 100.0
    elif case == "total":
        target["amount_usd_cents"] = 99
    elif case == "computed":
        target["invoice_version"] = 3
    elif case == "source_extra":
        target["details"][0]["source_parts"][0]["approved_due_date"] = "2027-01-01"
    elif case == "nul":
        body["intent"]["designation_reference"] = "x\x00y"
    elif case == "empty":
        body["intent"] = {}
    data = json.dumps(body)
    content_type = "application/json"
    if case == "duplicate_json":
        data = '{"intent":{},"intent":{}}'
        expected = 400
    elif case == "nonfinite":
        data = '{"intent":{"amount":NaN}}'
        expected = 400
    elif case == "not_json":
        content_type = "text/plain"
        expected = 400
    elif case == "oversize":
        data = json.dumps({"intent": {"text": "x" * 270_000}})
        expected = 400
    response = client.post(path, content=data, headers=headers() | {"Content-Type": content_type})
    assert response.status_code == expected
    no_preview(kind, flow)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["property", "source", "missing", "shape"])
def test_due_http_preview_binds_result_to_authorized_source_and_property(
    kind: Kind, case: str
) -> None:
    flow, client, path, body, _ = setup(kind)
    result: Any = {
        "property_id": str(flow.prop),
        "payment_id" if kind == "PAYMENT" else "credit_id": str(
            flow.payment if kind == "PAYMENT" else flow.credit
        ),
    }
    if case == "property":
        result["property_id"] = str(uuid4())
    elif case == "source":
        result["payment_id" if kind == "PAYMENT" else "credit_id"] = str(uuid4())
    elif case == "missing":
        result = {}
    else:
        result = []
    if kind == "PAYMENT":
        with patch.object(flow, "designation_preview", return_value=result):
            response = client.post(path, json=body, headers=headers())
    else:
        flow.credit_service.application_preview.return_value = result
        response = client.post(path, json=body, headers=headers())
    assert response.status_code == (503 if case == "shape" else 404)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "category,status",
    [
        ("missing", 404),
        ("authorization", 404),
        ("invalid", 400),
        ("conflict", 409),
        ("unavailable", 503),
    ],
)
def test_due_http_preview_safe_query_errors_do_not_become_command_responses(
    kind: Kind, category: str, status: int
) -> None:
    flow, client, path, body, _ = setup(kind)
    types = (
        (
            AllocationNotFoundError,
            AllocationAuthorizationError,
            AllocationInvalidError,
            AllocationConflictError,
            AllocationUnavailableError,
        )
        if kind == "PAYMENT"
        else (
            CreditNotFoundError,
            CreditAuthorizationError,
            CreditInvalidError,
            CreditConflictError,
            CreditUnavailableError,
        )
    )
    index = ["missing", "authorization", "invalid", "conflict", "unavailable"].index(category)
    error = types[index]("private source evidence")
    if kind == "PAYMENT":
        flow.error = error
    else:
        flow.credit_service.application_preview.side_effect = error
    response = client.post(path, json=body, headers=headers())
    assert response.status_code == status
    assert "private source evidence" not in response.text
    assert "location" not in response.headers


@pytest.mark.parametrize("kind", KINDS)
def test_due_http_preview_schema_requires_body_but_no_command_key(kind: Kind) -> None:
    _, client, path, _, _ = setup(kind)
    schema = client.get("/openapi.json").json()
    template = (
        "/api/v1/payments/{payment_id}/allocation-preview"
        if kind == "PAYMENT"
        else "/api/v1/customer-credits/{credit_id}/application-preview"
    )
    operation = schema["paths"][template]["post"]
    assert operation["requestBody"]["required"]
    assert all(p["name"].lower() != "idempotency-key" for p in operation.get("parameters", []))
    assert "200" in operation["responses"] and "201" not in operation["responses"]
    assert client.get(path).status_code == 405


def test_due_http_payment_preview_flow_uses_only_runtime_service() -> None:
    prop, payment = uuid4(), uuid4()
    who = actor(prop, "payments.allocate")
    intent = selection("PAYMENT")
    value = {"property_id": str(prop), "payment_id": str(payment)}
    with patch("property_rental.allocation_receipt_api.AllocationReadService") as service:
        service.return_value.designation_preview.return_value = value
        assert (
            PostgresAllocationReceiptFlow("runtime-only", None).designation_preview(
                prop, payment, intent, actor=who
            )
            == value
        )
        service.assert_called_once_with("runtime-only")
        service.return_value.designation_preview.assert_called_once_with(
            prop, payment, intent, actor=who
        )
