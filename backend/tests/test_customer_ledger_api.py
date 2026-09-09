"""Ledger-only HTTP authorization, strict reads and safe response metadata."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.customer_ledger import (
    LedgerInvalidError,
    LedgerPosition,
    LedgerSnapshotChangedError,
)
from property_rental.customer_ledger_query import LEDGER_CAPABILITY, LedgerReadRequest
from property_rental.customer_ledger_read import (
    LedgerAuthorizationError,
    LedgerNotFoundError,
    LedgerUnavailableError,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

PROP = UUID(int=91)
CUSTOMER = UUID(int=92)
HUMAN = UUID(int=93)


def actor(capability: str = LEDGER_CAPABILITY) -> AuthenticatedActor:
    return AuthenticatedActor(
        str(HUMAN), frozenset({CapabilityGrant(capability, frozenset({str(PROP)}))})
    )


@dataclass
class Flow:
    calls: list[object] = field(default_factory=list)
    error: Exception | None = None
    wrong_property: bool = False

    def get(
        self,
        customer_id: UUID,
        query: LedgerReadRequest,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]:
        self.calls.append((customer_id, query, actor, expected_property))
        if self.error:
            raise self.error
        return {
            "data": {
                "property_id": str(uuid4()) if self.wrong_property else str(PROP),
                "customer_id": str(customer_id),
                "position": LedgerPosition().as_wire(),
                "customer_name": "Synthetic Customer",
                "source_revision": "a" * 64,
                "section": query.section,
                "items": [],
                "event_count": 0,
            },
            "next_cursor": None,
        }

    def customers(
        self,
        limit: int,
        after: UUID | None,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]:
        self.calls.append((limit, after, actor, expected_property))
        if self.error:
            raise self.error
        return {
            "property_id": str(uuid4()) if self.wrong_property else str(PROP),
            "items": [{"id": str(CUSTOMER), "legal_name": "Synthetic Customer"}],
            "next_cursor": None,
        }


def path(kind: str = "ledger") -> str:
    return (
        f"/api/v1/customers/{CUSTOMER}/account-ledger"
        if kind == "ledger"
        else "/api/v1/customer-ledger/customers"
    )


def client(flow: Flow, current: AuthenticatedActor | None) -> TestClient:
    return TestClient(create_app(actor_resolver=lambda _: current, customer_ledger_flow=flow))


@pytest.mark.parametrize("kind", ["ledger", "customers"])
def test_ledger_http_success_is_read_only_private_and_actor_property_bound(kind: str) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(
            path(kind),
            headers={"X-Billing-Actor-ID": str(HUMAN), "X-Financial-Property-ID": str(PROP)},
        )
    assert response.status_code == 200 and len(flow.calls) == 1
    assert (
        response.headers["cache-control"] == "private, no-store"
        and "Cookie" in response.headers["vary"]
    )
    assert response.json()["meta"] == {
        "actor_id": str(HUMAN),
        "property_id": str(PROP),
        "request_id": response.headers["x-request-id"],
    }
    assert response.json()["page"] == {"limit": 50, "next_cursor": None}
    if kind == "customers":
        assert response.json()["data"] == [
            {"id": str(CUSTOMER), "legal_name": "Synthetic Customer"}
        ]


@pytest.mark.parametrize("kind", ["ledger", "customers"])
@pytest.mark.parametrize(
    "capability",
    [
        "customers.read",
        "customers.manage",
        "payments.read",
        "payments.record",
        "credits.read",
        "refunds.create",
        "deposits.manage",
    ],
)
def test_ledger_http_requires_separate_read_permission_before_any_flow(
    kind: str, capability: str
) -> None:
    flow = Flow()
    with client(flow, actor(capability)) as api:
        response = api.get(path(kind))
    assert response.status_code == 403 and not flow.calls
    assert response.headers["cache-control"] == "private, no-store"
    assert "property_id" not in response.json()["meta"]


@pytest.mark.parametrize("kind", ["ledger", "customers"])
def test_ledger_http_anonymous_request_is_denied_without_source_details(kind: str) -> None:
    flow = Flow()
    with client(flow, None) as api:
        response = api.get(path(kind))
    assert response.status_code == 401 and not flow.calls
    assert str(CUSTOMER) not in response.text and str(PROP) not in response.text


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
        "cursor=bad",
        "revision=bad",
        "section=write",
        "kind=UNKNOWN",
        "from=yesterday",
        "from=2026-09-09T00:00:00",
        "through=2026-02-30T00:00:00Z",
        "section=composition&kind=PAYMENT_RECEIVED",
        "section=components",
        "event_kind=PAYMENT_RECEIVED",
        "event_id=00000000-0000-0000-0000-000000000000",
    ],
)
def test_ledger_http_rejects_ambiguous_malformed_or_noncanonical_query_before_flow(
    query: str,
) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(path() + "?" + query)
    assert response.status_code == 400 and not flow.calls
    assert response.headers["cache-control"] == "private, no-store"


def test_ledger_http_translates_history_filter_and_component_selection_exactly() -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(
            path(),
            params={
                "from": "2026-09-09T07:00:00+07:00",
                "through": "2026-09-10T00:00:00Z",
                "kind": "PAYMENT_RECEIVED",
                "limit": "1",
            },
        )
        assert response.status_code == 200
        response = api.get(
            path(),
            params={
                "section": "components",
                "event_kind": "PAYMENT_RECEIVED",
                "event_id": str(CUSTOMER),
                "revision": "b" * 64,
            },
        )
        assert response.status_code == 200
    first = flow.calls[0]
    second = flow.calls[1]
    assert isinstance(first, tuple) and isinstance(second, tuple)
    assert first[1].filters.from_instant.isoformat() == "2026-09-09T00:00:00+00:00"
    assert first[1].limit == 1 and first[1].filters.event_kind == "PAYMENT_RECEIVED"
    assert (
        second[1].event_id == CUSTOMER
        and second[1].event_kind == "PAYMENT_RECEIVED"
        and second[1].revision == "b" * 64
    )


@pytest.mark.parametrize("kind", ["ledger", "customers"])
@pytest.mark.parametrize(
    "headers",
    [
        [("Idempotency-Key", "")],
        [("Idempotency-Key", "private-key")],
        [("X-Billing-Actor-ID", str(HUMAN)), ("X-Billing-Actor-ID", str(HUMAN))],
        [("X-Financial-Property-ID", str(PROP)), ("X-Financial-Property-ID", str(PROP))],
        [("X-Financial-Property-ID", "invalid")],
    ],
)
def test_ledger_http_rejects_command_or_duplicate_scope_headers(
    kind: str, headers: list[tuple[str, str]]
) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(path(kind), headers=headers)
    assert response.status_code == 400 and not flow.calls


@pytest.mark.parametrize("kind", ["ledger", "customers"])
def test_ledger_http_rejects_get_body_and_wrong_actor_before_flow(kind: str) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.request("GET", path(kind), content=b"x" * 65536)
        assert response.status_code == 400
        response = api.get(path(kind), headers={"X-Billing-Actor-ID": str(uuid4())})
        assert response.status_code == 403
    assert not flow.calls


@pytest.mark.parametrize("kind", ["ledger", "customers"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_ledger_http_has_no_financial_command_methods(kind: str, method: str) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.request(method, path(kind))
    assert response.status_code == 405 and not flow.calls
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "error,status",
    [
        (LedgerInvalidError("sensitive input"), 400),
        (LedgerNotFoundError("private record"), 404),
        (LedgerAuthorizationError("private grant"), 403),
        (LedgerSnapshotChangedError("private revision"), 409),
        (LedgerUnavailableError("private database"), 503),
    ],
)
@pytest.mark.parametrize("kind", ["ledger", "customers"])
def test_ledger_http_safe_correlated_failures_never_expose_source_diagnostics(
    kind: str, error: Exception, status: int
) -> None:
    flow = Flow(error=error)
    with client(flow, actor()) as api:
        response = api.get(path(kind))
    assert response.status_code == status and len(flow.calls) == 1
    assert str(error) not in response.text and "property_id" not in response.json()["meta"]
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("kind", ["ledger", "customers"])
def test_ledger_http_rechecks_returned_property_against_exact_ledger_grant(kind: str) -> None:
    flow = Flow(wrong_property=True)
    with client(flow, actor()) as api:
        response = api.get(path(kind))
    assert response.status_code == 503 and "property_id" not in response.json()["meta"]


@pytest.mark.parametrize(
    "identifier",
    [
        str(CUSTOMER).upper(),
        CUSTOMER.hex,
        "{" + str(CUSTOMER) + "}",
        "urn:uuid:" + str(CUSTOMER),
        str(CUSTOMER).replace("-", "--"),
        str(UUID(int=0)),
        "not-a-customer-id",
    ],
)
def test_ledger_http_rejects_noncanonical_customer_path_before_flow(identifier: str) -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(f"/api/v1/customers/{identifier}/account-ledger")
    assert response.status_code == 422 and not flow.calls
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert "property_id" not in response.json()["meta"]
    assert identifier not in response.text and str(PROP) not in response.text


def test_ledger_http_canonical_customer_path_preserves_exact_uuid() -> None:
    flow = Flow()
    with client(flow, actor()) as api:
        response = api.get(path())
    assert response.status_code == 200 and len(flow.calls) == 1
    call = flow.calls[0]
    assert isinstance(call, tuple) and call[0] == CUSTOMER
    assert response.json()["data"]["customer_id"] == str(CUSTOMER)
