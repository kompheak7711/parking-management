"""Dated-source HTTP scope, finite inputs and private read-only response envelopes."""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.financial_due_sources import (
    FinancialDueSourcesChanged,
    FinancialDueSourcesRequest,
    FinancialDueSourcesService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
)
from test_financial_due_sources import PURPOSES, staff


@dataclass
class Flow:
    calls: list[tuple[UUID, FinancialDueSourcesRequest, AuthenticatedActor]] = field(
        default_factory=list
    )
    error: Exception | None = None

    def get(
        self, property_id: UUID, request: FinancialDueSourcesRequest, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((property_id, request, actor))
        if self.error is not None:
            raise self.error
        return {
            "data": {
                "property_id": str(property_id),
                "purpose": request.purpose,
                "source_id": str(request.source_id),
            },
            "next_cursor": None,
        }


def path(prop: UUID) -> str:
    return f"/api/v1/properties/{prop}/financial-due-sources"


def query(purpose: str = "allocation") -> dict[str, str]:
    return {
        "purpose": purpose,
        "source_id": str(uuid4()),
        "invoice_id": str(uuid4()),
        "invoice_line_id": str(uuid4()),
    }


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("continued", [False, True])
def test_due_sources_http_returns_bound_private_page(purpose: str, continued: bool) -> None:
    prop = uuid4()
    who, flow, parameters = staff(prop, purpose), Flow(), query(purpose)
    parameters["limit"] = "2"
    if continued:
        parameters["cursor"] = "a" * 64 + ":ORIGINAL_LINE:" + parameters["invoice_line_id"]
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.get(
            path(prop),
            params=parameters,
            headers={"X-Billing-Actor-ID": who.actor_id, "X-Financial-Property-ID": str(prop)},
        )
    assert response.status_code == 200 and len(flow.calls) == 1
    bound, req, actual = flow.calls[0]
    assert bound == prop and actual == who
    assert req == FinancialDueSourcesRequest(
        purpose,
        UUID(parameters["source_id"]),
        UUID(parameters["invoice_id"]),
        UUID(parameters["invoice_line_id"]),
        2,
        parameters.get("cursor"),
    )
    assert response.json()["page"] == {"limit": 2, "next_cursor": None}
    assert response.json()["meta"] == {
        "request_id": response.headers["X-Request-ID"],
        "actor_id": who.actor_id,
        "property_id": str(prop),
    }
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )
    assert "Location" not in response.headers


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("case", ["general_read", "other_property"])
def test_due_sources_http_action_scope_is_required_before_dispatch(purpose: str, case: str) -> None:
    prop, flow = uuid4(), Flow()
    who = (
        staff(uuid4(), purpose)
        if case == "other_property"
        else AuthenticatedActor(
            str(uuid4()), frozenset({CapabilityGrant("payments.read", frozenset({str(prop)}))})
        )
    )
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.get(
            path(prop), params=query(purpose), headers={"X-Billing-Actor-ID": who.actor_id}
        )
    assert response.status_code == 403 and flow.calls == []
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )


BAD_QUERIES = [
    "unknown",
    "duplicate",
    "missing_purpose",
    "wrong_purpose",
    "empty_purpose",
    "missing_source_id",
    "missing_invoice_id",
    "missing_invoice_line_id",
    "nil_source_id",
    "nil_invoice_id",
    "nil_invoice_line_id",
    "bad_source_id",
    "bad_invoice_id",
    "bad_invoice_line_id",
    "uppercase_uuid",
    "compact_uuid",
    "limit_zero",
    "limit_over",
    "limit_leading_zero",
    "limit_decimal",
    "limit_unicode",
    "limit_empty",
    "cursor_empty",
    "cursor_malformed",
    "cursor_uppercase",
    "cursor_nil",
    "cursor_kind",
    "cursor_long",
]


@pytest.mark.parametrize("case", BAD_QUERIES)
def test_due_sources_http_rejects_ambiguous_query_without_dispatch(case: str) -> None:
    prop, flow = uuid4(), Flow()
    who, parameters = staff(prop, "allocation"), query()
    if case == "unknown":
        parameters["unexpected"] = "1"
    elif case.startswith("missing_"):
        del parameters[case.removeprefix("missing_")]
    elif case == "wrong_purpose":
        parameters["purpose"] = "credit_recognition"
    elif case == "empty_purpose":
        parameters["purpose"] = ""
    elif case.startswith("nil_"):
        parameters[case.removeprefix("nil_")] = str(UUID(int=0))
    elif case.startswith("bad_"):
        parameters[case.removeprefix("bad_")] = "invalid"
    elif case == "uppercase_uuid":
        parameters["source_id"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    elif case == "compact_uuid":
        parameters["source_id"] = UUID(int=1).hex
    elif case.startswith("limit_"):
        parameters["limit"] = {
            "zero": "0",
            "over": "101",
            "leading_zero": "01",
            "decimal": "1.0",
            "unicode": "\uff11",
            "empty": "",
        }[case.removeprefix("limit_")]
    elif case.startswith("cursor_"):
        parameters["cursor"] = {
            "empty": "",
            "malformed": "bad",
            "uppercase": "A" * 64 + ":ORIGINAL_LINE:" + str(UUID(int=1)),
            "nil": "a" * 64 + ":ORIGINAL_LINE:" + str(UUID(int=0)),
            "kind": "a" * 64 + ":PAYMENT:" + str(UUID(int=1)),
            "long": "a" * 121,
        }[case.removeprefix("cursor_")]
    pairs = list(parameters.items())
    if case == "duplicate":
        pairs.append(("invoice_id", parameters["invoice_id"]))
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.get(
            path(prop), params=pairs, headers={"X-Billing-Actor-ID": who.actor_id}
        )
    assert response.status_code == 400 and flow.calls == []
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )


@pytest.mark.parametrize(
    "case,status",
    [
        ("key", 400),
        ("property_duplicate", 400),
        ("property_wrong", 404),
        ("property_invalid", 400),
        ("property_nil", 400),
        ("actor_duplicate", 400),
        ("actor_conflicting_duplicate", 400),
        ("actor_wrong", 403),
    ],
)
def test_due_sources_http_rejects_command_keys_and_header_context(case: str, status: int) -> None:
    prop, flow = uuid4(), Flow()
    who = staff(prop, "allocation")
    headers = [("X-Billing-Actor-ID", who.actor_id), ("X-Financial-Property-ID", str(prop))]
    if case == "key":
        headers.append(("Idempotency-Key", str(uuid4())))
    elif case == "property_duplicate":
        headers.append(("X-Financial-Property-ID", str(prop)))
    elif case == "property_wrong":
        headers[1] = ("X-Financial-Property-ID", str(uuid4()))
    elif case == "property_invalid":
        headers[1] = ("X-Financial-Property-ID", "invalid")
    elif case == "property_nil":
        headers[1] = ("X-Financial-Property-ID", str(UUID(int=0)))
    elif case == "actor_duplicate":
        headers.append(("X-Billing-Actor-ID", who.actor_id))
    elif case == "actor_conflicting_duplicate":
        headers.append(("X-Billing-Actor-ID", str(uuid4())))
    else:
        headers[0] = ("X-Billing-Actor-ID", str(uuid4()))
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.get(path(prop), params=query(), headers=headers)
    assert response.status_code == status and flow.calls == []
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize(
    "error,status",
    [
        (PaymentReadInvalidError, 400),
        (PaymentReadNotFoundError, 404),
        (PaymentReadAuthorizationError, 403),
        (PaymentReadUnavailableError, 503),
        (FinancialDueSourcesChanged, 409),
    ],
)
def test_due_sources_http_redacts_service_failures(
    purpose: str, error: type[Exception], status: int
) -> None:
    prop = uuid4()
    who, flow = staff(prop, purpose), Flow(error=error("Synthetic private SQL detail"))
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.get(
            path(prop), params=query(purpose), headers={"X-Billing-Actor-ID": who.actor_id}
        )
    assert response.status_code == status and len(flow.calls) == 1
    assert "Synthetic private SQL detail" not in response.text
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )


@pytest.mark.parametrize("purpose", PURPOSES)
def test_due_sources_http_default_factory_uses_new_read_service(purpose: str) -> None:
    prop = uuid4()
    who = staff(prop, purpose)
    calls: list[
        tuple[FinancialDueSourcesService, UUID, FinancialDueSourcesRequest, AuthenticatedActor]
    ] = []

    def read(
        service: FinancialDueSourcesService,
        selected: UUID,
        request: FinancialDueSourcesRequest,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, Any]:
        calls.append((service, selected, request, actor))
        return {"data": {"items": []}, "next_cursor": None}

    with (
        patch.object(FinancialDueSourcesService, "get", read),
        TestClient(create_app(actor_resolver=lambda _: who)) as client,
    ):
        response = client.get(
            path(prop), params=query(purpose), headers={"X-Billing-Actor-ID": who.actor_id}
        )
    assert response.status_code == 200 and len(calls) == 1
    assert calls[0][1] == prop and calls[0][2].purpose == purpose and calls[0][3] == who


@pytest.mark.parametrize("case,status", [("anonymous", 401), ("invalid_actor", 403), ("post", 405)])
def test_due_sources_http_authentication_and_read_only_method(case: str, status: int) -> None:
    prop, flow = uuid4(), Flow()
    who: AuthenticatedActor | None = staff(prop, "allocation")
    if case == "anonymous":
        who = None
    elif case == "invalid_actor":
        who = AuthenticatedActor("invalid", frozenset())
    with TestClient(
        create_app(actor_resolver=lambda _: who, financial_due_sources_flow=flow)
    ) as client:
        response = client.request("POST" if case == "post" else "GET", path(prop), params=query())
    assert response.status_code == status and flow.calls == []
    assert response.headers["Cache-Control"] == "private, no-store"
