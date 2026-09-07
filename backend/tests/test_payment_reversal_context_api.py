"""Action-only HTTP context, strict queries and safe response correlation."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
)
from property_rental.payment_reversal_context import (
    PaymentReversalContextChanged,
    ReversalContextPage,
)
from test_credit_migration import actor


@dataclass
class Flow:
    calls: list[object] = field(default_factory=list)
    error: Exception | None = None

    def get(
        self,
        property_id: UUID,
        payment_id: UUID,
        page: ReversalContextPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.calls.append((property_id, payment_id, page, actor))
        if self.error is not None:
            raise self.error
        return {
            "data": {"payment_id": str(payment_id), "view": page.view, "items": []},
            "next_cursor": None,
        }


def path(prop: UUID, payment: UUID) -> str:
    return f"/api/v1/properties/{prop}/payments/{payment}/reversal-context"


@pytest.mark.parametrize("view", ["impact", "result"])
def test_payment_reversal_context_http_action_only_success_no_store_and_scope(view: str) -> None:
    prop, payment, human = uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, "payments.reverse"),
            payment_reversal_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, payment),
            params={"view": view, "limit": 3},
            headers={"X-Billing-Actor-ID": str(human), "X-Financial-Property-ID": str(prop)},
        )
    assert response.status_code == 200 and len(flow.calls) == 1
    assert response.json()["meta"] == {
        "request_id": response.headers["X-Request-ID"],
        "actor_id": str(human),
        "property_id": str(prop),
    }
    assert response.json()["page"] == {"limit": 3, "next_cursor": None}
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=01",
        "limit=1.0",
        "limit=1&limit=2",
        "view=all",
        "view=impact&view=result",
        "cursor=",
        "cursor=x",
        "extra=1",
    ],
)
def test_payment_reversal_context_http_rejects_invalid_queries_before_projection(
    query: str,
) -> None:
    prop, payment = uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(uuid4(), prop, "payments.reverse"),
            payment_reversal_context_flow=flow,
        )
    ) as client:
        response = client.get(path(prop, payment) + "?" + query)
    assert response.status_code == 400 and not flow.calls
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "failure,status",
    [
        ("anonymous", 401),
        ("read-only", 403),
        ("other-property", 403),
        ("actor-header", 403),
        ("property-header", 404),
        ("duplicate-header", 400),
        ("idempotency", 400),
    ],
)
def test_payment_reversal_context_http_identity_and_scope_precede_projection(
    failure: str, status: int
) -> None:
    prop, payment, human = uuid4(), uuid4(), uuid4()
    flow = Flow()
    headers = []
    current = (
        None
        if failure == "anonymous"
        else actor(
            human,
            uuid4() if failure == "other-property" else prop,
            "payments.read" if failure == "read-only" else "payments.reverse",
        )
    )
    if failure == "actor-header":
        headers = [("X-Billing-Actor-ID", str(uuid4()))]
    elif failure == "property-header":
        headers = [("X-Financial-Property-ID", str(uuid4()))]
    elif failure == "duplicate-header":
        headers = [("X-Financial-Property-ID", str(prop))] * 2
    elif failure == "idempotency":
        headers = [("Idempotency-Key", str(uuid4()))]
    with TestClient(
        create_app(actor_resolver=lambda _: current, payment_reversal_context_flow=flow)
    ) as client:
        response = client.get(path(prop, payment), headers=headers)
    assert response.status_code == status and not flow.calls


@pytest.mark.parametrize(
    "error,status",
    [
        (PaymentReadAuthorizationError("private detail"), 403),
        (PaymentReadNotFoundError("private detail"), 404),
        (PaymentReadUnavailableError("private detail"), 503),
        (PaymentReversalContextChanged("private detail"), 409),
    ],
)
def test_payment_reversal_context_http_safe_source_and_changed_snapshot_errors(
    error: Exception, status: int
) -> None:
    prop, payment = uuid4(), uuid4()
    flow = Flow(error=error)
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(uuid4(), prop, "payments.reverse"),
            payment_reversal_context_flow=flow,
        )
    ) as client:
        response = client.get(path(prop, payment))
    assert response.status_code == status and len(flow.calls) == 1
    assert (
        "private detail" not in response.text
        and response.headers["Cache-Control"] == "private, no-store"
    )
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
