"""Authorization, bounded strict requests, no-store and correlation for references."""

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.financial_reference import ReferencePage, capabilities
from property_rental.identity import AuthenticatedActor
from property_rental.khr_payment_confirmation import ManualKhrReference
from property_rental.payment_read import PaymentReadUnavailableError
from test_credit_migration import actor
from test_invoice import mutation_headers as invoice_headers


def mutation_headers() -> dict[str, str]:
    return {key: value for key, value in invoice_headers().items() if key != "Idempotency-Key"}


@dataclass
class Flow:
    calls: list[object] = field(default_factory=list)
    error: Exception | None = None

    def observe(self, value: object) -> None:
        self.calls.append(value)
        if self.error is not None:
            raise self.error

    def workspaces(self, page: ReferencePage, *, actor: AuthenticatedActor) -> dict[str, object]:
        self.observe((page, actor))
        return {"items": [], "next_cursor": None}

    def capability_view(self, property_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        self.observe((property_id, actor))
        return {"property_id": str(property_id), "capabilities": capabilities(actor, property_id)}

    def methods(
        self, property_id: UUID, page: ReferencePage, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.observe((property_id, page, actor))
        return {"items": [], "next_cursor": None}

    def preview(
        self,
        property_id: UUID,
        usd_amount_cents: int,
        manual: ManualKhrReference | None,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.observe((property_id, usd_amount_cents, manual, actor))
        return {
            "property_id": str(property_id),
            "usd_amount_cents": usd_amount_cents,
            "status": "source_unavailable",
            "provisional": True,
            "manual_fallback_allowed": False,
        }


def client(flow: Flow, current: AuthenticatedActor | None) -> TestClient:
    result = TestClient(create_app(actor_resolver=lambda _: current, financial_reference_flow=flow))
    result.cookies.set("__Host-prm_csrf", "csrf")
    return result


def route(kind: str, prop: UUID) -> str:
    return (
        "/api/v1/financial-workspaces"
        if kind == "workspaces"
        else f"/api/v1/properties/{prop}/"
        + {
            "capabilities": "financial-capabilities",
            "methods": "payment-methods",
            "preview": "payments/khr-preview",
        }[kind]
    )


@pytest.mark.parametrize("kind", ["workspaces", "capabilities", "methods", "preview"])
def test_financial_reference_http_actor_bound_success_and_private_no_store(kind: str) -> None:
    prop, human = uuid4(), uuid4()
    flow = Flow()
    current = actor(human, prop, "payments.record")
    headers = mutation_headers() | {"X-Billing-Actor-ID": str(human)}
    if kind != "workspaces":
        headers["X-Financial-Property-ID"] = str(prop)
    with client(flow, current) as api:
        response = api.request(
            "POST" if kind == "preview" else "GET",
            route(kind, prop),
            headers=headers,
            json={"usd_amount_cents": 1001} if kind == "preview" else None,
        )
    assert response.status_code == 200 and len(flow.calls) == 1
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )
    meta = response.json()["meta"]
    assert meta["actor_id"] == str(human) and meta["request_id"] == response.headers["X-Request-ID"]
    if kind != "workspaces":
        assert meta["property_id"] == str(prop)
    else:
        assert "property_id" not in meta


@pytest.mark.parametrize("kind", ["workspaces", "capabilities", "methods", "preview"])
@pytest.mark.parametrize(
    "mode,status", [("anonymous", 401), ("wrong_actor", 403), ("duplicate_actor", 400)]
)
def test_financial_reference_http_denies_actor_mismatch_before_flow(
    kind: str, mode: str, status: int
) -> None:
    prop, human = uuid4(), uuid4()
    flow = Flow()
    current = actor(human, prop, "payments.record")
    headers = [
        *mutation_headers().items(),
        ("X-Billing-Actor-ID", str(uuid4()) if mode == "wrong_actor" else str(human)),
    ]
    if mode == "duplicate_actor":
        headers.append(("X-Billing-Actor-ID", str(human)))
    with client(flow, None if mode == "anonymous" else current) as api:
        response = api.request(
            "POST" if kind == "preview" else "GET",
            route(kind, prop),
            headers=headers,
            json={"usd_amount_cents": 1001} if kind == "preview" else None,
        )
    assert response.status_code == status and not flow.calls
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "property_id" not in response.json()["meta"]


@pytest.mark.parametrize("kind", ["methods", "preview"])
@pytest.mark.parametrize(
    "cap", ["payments.read", "property.manage", "exchange_rates.manage", "receipts.read"]
)
def test_financial_reference_http_requires_record_without_configuration_manager_dependency(
    kind: str, cap: str
) -> None:
    prop = uuid4()
    flow = Flow()
    with client(flow, actor(uuid4(), prop, cap)) as api:
        response = api.request(
            "POST" if kind == "preview" else "GET",
            route(kind, prop),
            headers=mutation_headers(),
            json={"usd_amount_cents": 1001} if kind == "preview" else None,
        )
    assert response.status_code == 403 and not flow.calls


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=01",
        "limit=1.0",
        "limit=+1",
        "limit=1&limit=2",
        "unknown=x",
        "cursor=",
        "cursor=00000000-0000-0000-0000-000000000000",
        "cursor=not-a-cursor",
    ],
)
@pytest.mark.parametrize("kind", ["workspaces", "methods"])
def test_financial_reference_http_rejects_noncanonical_or_duplicate_pages(
    kind: str, query: str
) -> None:
    prop = uuid4()
    flow = Flow()
    with client(flow, actor(uuid4(), prop, "payments.record")) as api:
        response = api.get(route(kind, prop) + "?" + query)
    assert response.status_code == 400 and not flow.calls


def test_financial_reference_http_page_passes_exact_uuid_and_limit() -> None:
    prop, cursor = uuid4(), uuid4()
    flow = Flow()
    with client(flow, actor(uuid4(), prop, "payments.record")) as api:
        response = api.get(route("methods", prop), params={"limit": "1", "cursor": str(cursor)})
    assert response.status_code == 200
    call = cast(tuple[UUID, ReferencePage, AuthenticatedActor], flow.calls[0])
    assert call[1] == ReferencePage(1, cursor)


@pytest.mark.parametrize("kind", ["capabilities", "methods", "preview"])
@pytest.mark.parametrize("header,status", [("wrong", 404), ("malformed", 400), ("duplicate", 400)])
def test_financial_reference_http_property_binding_precedes_lookup(
    kind: str, header: str, status: int
) -> None:
    prop = uuid4()
    flow = Flow()
    headers = list(mutation_headers().items())
    headers.append(
        (
            "X-Financial-Property-ID",
            str(uuid4()) if header == "wrong" else str(prop) if header == "duplicate" else "bad",
        )
    )
    if header == "duplicate":
        headers.append(("X-Financial-Property-ID", str(prop)))
    with client(flow, actor(uuid4(), prop, "payments.record")) as api:
        response = api.request(
            "POST" if kind == "preview" else "GET",
            route(kind, prop),
            headers=headers,
            json={"usd_amount_cents": 1001} if kind == "preview" else None,
        )
    assert response.status_code == status and not flow.calls


@pytest.mark.parametrize(
    "body,status",
    [
        ('{"usd_amount_cents":1,"usd_amount_cents":2}', 400),
        ('{"usd_amount_cents":true}', 422),
        ('{"usd_amount_cents":1.0}', 422),
        ('{"usd_amount_cents":0}', 422),
        ('{"usd_amount_cents":9000000000000001}', 422),
        ('{"usd_amount_cents":1,"markup_basis_points":0}', 422),
        ('{"usd_amount_cents":1,"padding":"' + "x" * 32768 + '"}', 400),
    ],
)
def test_financial_reference_preview_strict_bounded_body_cannot_set_derived_values(
    body: str, status: int
) -> None:
    prop = uuid4()
    flow = Flow()
    with client(flow, actor(uuid4(), prop, "payments.record")) as api:
        response = api.post(
            route("preview", prop),
            content=body,
            headers=mutation_headers() | {"Content-Type": "application/json"},
        )
    assert response.status_code == status and not flow.calls


@pytest.mark.parametrize(
    "mode,status",
    [("missing_csrf", 403), ("wrong_origin", 403), ("idempotency", 400), ("query", 400)],
)
def test_financial_reference_preview_requires_browser_protection_without_reservation(
    mode: str, status: int
) -> None:
    prop = uuid4()
    flow = Flow()
    headers = mutation_headers()
    if mode == "missing_csrf":
        headers.pop("X-CSRF-Token", None)
    if mode == "wrong_origin":
        headers["Origin"] = "https://foreign.invalid"
    if mode == "idempotency":
        headers["Idempotency-Key"] = str(uuid4())
    with client(flow, actor(uuid4(), prop, "payments.record")) as api:
        response = api.post(
            route("preview", prop) + ("?x=1" if mode == "query" else ""),
            json={"usd_amount_cents": 1},
            headers=headers,
        )
    assert response.status_code == status and not flow.calls


def test_financial_reference_preview_manual_grant_checked_before_flow_and_error_is_safe() -> None:
    prop = uuid4()
    flow = Flow()
    current = actor(uuid4(), prop, "payments.record")
    manual = {
        "reference_rate_khr_per_usd": "4062",
        "source_reference": "synthetic ABA quote",
        "applicable_at": "2026-05-01T00:00:00Z",
        "fallback_reason": "unavailable source",
    }
    with client(flow, current) as api:
        denied = api.post(
            route("preview", prop),
            json={"usd_amount_cents": 1001, "manual_reference": manual},
            headers=mutation_headers(),
        )
        assert denied.status_code == 403 and not flow.calls
        flow.error = PaymentReadUnavailableError("private SQL must stay hidden")
        error = api.get(route("methods", prop))
    assert error.status_code == 503 and "private SQL" not in error.text
    assert error.json()["meta"]["request_id"] == error.headers["X-Request-ID"]
