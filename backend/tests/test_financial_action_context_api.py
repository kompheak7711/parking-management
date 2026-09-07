"""Purpose-specific HTTP authorization, strict inputs and safe error envelopes."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.financial_action_context import (
    ACTION_CAPABILITIES,
    FinancialActionContextChanged,
    FinancialActionContextRequest,
)
from property_rental.financial_action_context_api import ACTION_CONTEXT_PATHS
from property_rental.identity import AuthenticatedActor
from property_rental.payment_read import (
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadUnavailableError,
)
from test_credit_migration import actor


@dataclass
class Flow:
    calls: list[tuple[UUID, FinancialActionContextRequest, AuthenticatedActor]] = field(
        default_factory=list
    )
    error: Exception | None = None

    def get(
        self,
        property_id: UUID,
        request: FinancialActionContextRequest,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self.calls.append((property_id, request, actor))
        if self.error is not None:
            raise self.error
        return {
            "data": {"purpose": request.purpose, "source_id": str(request.source_id)},
            "next_cursor": None,
        }


def path(prop: UUID, source: UUID, purpose: str, refund: UUID | None = None) -> str:
    return f"/api/v1/properties/{prop}" + ACTION_CONTEXT_PATHS[purpose].format(
        source_id=source, refund_id=refund
    )


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
def test_financial_action_context_http_only_own_action_needed(purpose: str) -> None:
    prop, source, human, refund = uuid4(), uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, ACTION_CAPABILITIES[purpose]),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, purpose, refund),
            params={"limit": 2},
            headers={"X-Billing-Actor-ID": str(human), "X-Financial-Property-ID": str(prop)},
        )
    assert response.status_code == 200 and len(flow.calls) == 1
    captured_prop, req, staff = flow.calls[0]
    assert (
        captured_prop == prop
        and req.source_id == source
        and req.purpose == purpose
        and req.limit == 2
    )
    assert req.refund_id == (refund if purpose == "refund_correction_reversal" else None)
    assert staff.actor_id == str(human)
    assert response.json()["page"] == {"limit": 2, "next_cursor": None}
    assert response.json()["meta"] == {
        "request_id": response.headers["X-Request-ID"],
        "actor_id": str(human),
        "property_id": str(prop),
    }
    assert (
        response.headers["Cache-Control"] == "private, no-store"
        and "Cookie" in response.headers["Vary"]
    )


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
def test_financial_action_context_http_general_read_never_implies_action(purpose: str) -> None:
    prop, human, source, refund = uuid4(), uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, "payments.read"),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, purpose, refund), headers={"X-Billing-Actor-ID": str(human)}
        )
    assert response.status_code == 403 and flow.calls == []
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
        "cursor=",
        "cursor=x",
        "unexpected=1",
        "target_kind=INVOICE",
        "target_id=00000000-0000-0000-0000-000000000001",
        "target_kind=SETTLEMENT&target_id=00000000-0000-0000-0000-000000000001",
        "target_kind=INVOICE&target_id=00000000-0000-0000-0000-000000000000",
    ],
)
def test_financial_action_context_http_rejects_invalid_queries_before_dispatch(query: str) -> None:
    prop, human, source = uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, "payments.allocate"),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, "allocation") + "?" + query,
            headers={"X-Billing-Actor-ID": str(human)},
        )
    assert response.status_code == 400 and flow.calls == []


@pytest.mark.parametrize("purpose", ["allocation", "credit_application"])
def test_financial_action_context_http_selected_targets_captured_exactly(purpose: str) -> None:
    prop, human, source, target = uuid4(), uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, ACTION_CAPABILITIES[purpose]),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, purpose),
            params={"target_kind": "LATE_PAYMENT_CHARGE", "target_id": str(target)},
            headers={"X-Billing-Actor-ID": str(human)},
        )
    assert response.status_code == 200
    assert (
        flow.calls[0][1].target_kind == "LATE_PAYMENT_CHARGE"
        and flow.calls[0][1].target_id == target
    )


@pytest.mark.parametrize(
    "purpose", ACTION_CAPABILITIES.keys() - {"allocation", "credit_application"}
)
def test_financial_action_context_http_reversal_cannot_supply_replacement_target(
    purpose: str,
) -> None:
    prop, human, source, refund = uuid4(), uuid4(), uuid4(), uuid4()
    flow = Flow()
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, ACTION_CAPABILITIES[purpose]),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, purpose, refund),
            params={"target_kind": "INVOICE", "target_id": str(uuid4())},
            headers={"X-Billing-Actor-ID": str(human)},
        )
    assert response.status_code == 400 and flow.calls == []


@pytest.mark.parametrize(
    "header,value,status",
    [
        ("X-Billing-Actor-ID", "different", 403),
        ("X-Financial-Property-ID", "different", 404),
        ("Idempotency-Key", "key", 400),
    ],
)
def test_financial_action_context_http_actor_property_and_read_only_headers(
    header: str, value: str, status: int
) -> None:
    prop, human, source = uuid4(), uuid4(), uuid4()
    flow = Flow()
    headers = {"X-Billing-Actor-ID": str(human)}
    headers[header] = str(uuid4()) if value == "different" else value
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, "receipts.reprint"),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(path(prop, source, "receipt_reprint"), headers=headers)
    assert response.status_code == status and flow.calls == []


@pytest.mark.parametrize("purpose", ACTION_CAPABILITIES)
@pytest.mark.parametrize(
    "error,status",
    [
        (PaymentReadNotFoundError, 404),
        (PaymentReadAuthorizationError, 403),
        (PaymentReadInvalidError, 400),
        (PaymentReadUnavailableError, 503),
        (FinancialActionContextChanged, 409),
    ],
)
def test_financial_action_context_http_safe_correlated_failure(
    error: type[Exception], status: int, purpose: str
) -> None:
    prop, human, source = uuid4(), uuid4(), uuid4()
    flow = Flow(error=error("private SQL / configuration details"))
    with TestClient(
        create_app(
            actor_resolver=lambda _: actor(human, prop, ACTION_CAPABILITIES[purpose]),
            financial_action_context_flow=flow,
        )
    ) as client:
        response = client.get(
            path(prop, source, purpose, uuid4()), headers={"X-Billing-Actor-ID": str(human)}
        )
    assert response.status_code == status and len(flow.calls) == 1
    assert "private SQL" not in response.text and "configuration details" not in response.text
    assert response.json()["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_financial_action_context_http_unauthenticated_and_default_flow_fail_closed() -> None:
    prop, source = uuid4(), uuid4()
    with TestClient(create_app()) as client:
        assert client.get(path(prop, source, "credit_reversal")).status_code == 401
    human = uuid4()
    with TestClient(
        create_app(actor_resolver=lambda _: actor(human, prop, "credits.reverse"))
    ) as client:
        assert (
            client.get(
                path(prop, source, "credit_reversal"), headers={"X-Billing-Actor-ID": str(human)}
            ).status_code
            == 503
        )
