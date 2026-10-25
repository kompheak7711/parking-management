"""Reduce or waive a Late-payment Charge: the command and its route (V1-056 slice 11g-2; DL-076
answer 4). The database effects are covered by
``test_late_payment_charge_reduction_migration.py``."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.late_payment import (
    LatePaymentAuthorizationError,
    LatePaymentConflictError,
    LatePaymentIdempotencyKeyReused,
    LatePaymentInvalidError,
    LatePaymentNotFoundError,
    LatePaymentServiceUnavailableError,
    PostgresLatePaymentService,
    ReduceLatePaymentChargeCommand,
    ReductionReason,
)
from test_late_payment import (
    InMemoryLatePaymentFlow,
    actor,
    api,
    charge_resource,
    mutation_headers,
)

BODY: dict[str, object] = {
    "new_amount": {"currency": "USD", "minor_units": 2_000},
    "reason": "PAID_ON_TIME_RECORDED_LATE",
    "what_happened": "The Customer paid at the desk on the 4th; staff entered it on the 7th.",
}


def path(charge_id: UUID) -> str:
    return f"/api/v1/late-payment-charges/{charge_id}/reductions"


def flow_and_ids() -> tuple[InMemoryLatePaymentFlow, UUID, UUID]:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    return InMemoryLatePaymentFlow(property_id, invoice_id, charge_id), property_id, charge_id


def test_the_reduce_command_takes_a_bounded_amount_a_fixed_reason_and_a_normalized_text() -> None:
    key = uuid4()
    command = ReduceLatePaymentChargeCommand(key, 0, ReductionReason.WRONG_INVOICE, "Wrong row")
    assert (command.new_amount_usd_cents, command.reason) == (0, ReductionReason.WRONG_INVOICE)
    for changes in (
        {"idempotency_key": UUID(int=0)},
        {"new_amount_usd_cents": -1},
        {"new_amount_usd_cents": 9_000_000_000_000_001},
        {"new_amount_usd_cents": True},
        {"reason": "WRONG_INVOICE"},
        {"what_happened": ""},
        {"what_happened": " padded"},
        {"what_happened": "ends with a line feed\n"},
        {"what_happened": "a bell \x07 inside"},
        {"what_happened": "a C1 control \x85 inside"},
        {"what_happened": "the first C1 control \x80 inside"},
        {"what_happened": "the last C1 control \x9f inside"},
        {"what_happened": "a lone surrogate \ud800 inside"},
        {"what_happened": "x" * 501},
    ):
        values: dict[str, object] = {
            "idempotency_key": key,
            "new_amount_usd_cents": 100,
            "reason": ReductionReason.OTHER_STAFF_MISTAKE,
            "what_happened": "Staff typed the wrong date",
            **changes,
        }
        with pytest.raises(ValueError):
            ReduceLatePaymentChargeCommand(**values)  # type: ignore[arg-type]


def test_only_a_holder_of_the_correction_capability_reduces_with_csrf_and_a_clean_body() -> None:
    flow, property_id, charge_id = flow_and_ids()
    assert (
        api(flow, None).post(path(charge_id), json=BODY, headers=mutation_headers()).status_code
        == 401
    )
    for capability in ("late_payment.review", "late_payment.final_decision"):
        hidden = api(flow, actor(property_id, capability)).post(
            path(charge_id), json=BODY, headers=mutation_headers()
        )
        assert hidden.status_code == 404
    other_property = api(flow, actor(uuid4(), "late_payment.charge_correction")).post(
        path(charge_id), json=BODY, headers=mutation_headers()
    )
    assert other_property.status_code == 404
    client = api(flow, actor(property_id, "late_payment.charge_correction"))
    no_csrf = client.post(path(charge_id), json=BODY, headers={"Idempotency-Key": str(uuid4())})
    assert no_csrf.status_code == 403
    other_origin = client.post(
        path(charge_id), json=BODY, headers={**mutation_headers(), "Origin": "https://example.com"}
    )
    assert other_origin.status_code == 403
    for body in (
        {**BODY, "amount": {"currency": "USD", "minor_units": 1}},
        {**BODY, "new_amount": {"currency": "KHR", "minor_units": 2_000}},
        {**BODY, "new_amount": {"currency": "USD", "minor_units": -1}},
        {**BODY, "reason": "CUSTOMER_ASKED"},
        {**BODY, "what_happened": ""},
        {**BODY, "what_happened": "ends with a space "},
        {**BODY, "what_happened": "\tstarts with a tab"},
        {**BODY, "what_happened": "an escape \x1b inside"},
        {**BODY, "what_happened": "a delete \x7f inside"},
        {**BODY, "what_happened": "a C1 control \x9b inside"},
        {**BODY, "what_happened": "the first C1 control \x80 inside"},
        {**BODY, "what_happened": "the last C1 control \x9f inside"},
        {**BODY, "what_happened": "ends with a no-break space\u00a0"},
        {**BODY, "what_happened": "a NUL \u0000 inside"},
        {**BODY, "what_happened": "x" * 501},
        {key: value for key, value in BODY.items() if key != "what_happened"},
    ):
        assert (
            client.post(path(charge_id), json=body, headers=mutation_headers()).status_code == 422
        )
    assert flow.reductions == []

    waived = client.post(
        path(charge_id),
        json={
            **BODY,
            "new_amount": {"currency": "USD", "minor_units": 0},
            "reason": "WRONG_INVOICE",
            "what_happened": "Payment went to the March Invoice.\nIt was for February.",
        },
        headers=mutation_headers(),
    )
    assert waived.status_code == 200
    assert "Location" not in waived.headers
    assert waived.json()["data"]["id"] == str(charge_id)
    assert flow.reductions[-1].new_amount_usd_cents == 0
    assert flow.reductions[-1].reason is ReductionReason.WRONG_INVOICE
    assert flow.reductions[-1].what_happened.endswith("for February.")


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (LatePaymentIdempotencyKeyReused(), 409, "IDEMPOTENCY_KEY_REUSED"),
        (LatePaymentConflictError(), 409, "CONFLICT"),
        (LatePaymentInvalidError(), 422, None),
        (LatePaymentNotFoundError(), 404, None),
        (LatePaymentAuthorizationError(), 403, None),
        (LatePaymentServiceUnavailableError(), 503, "SERVICE_UNAVAILABLE"),
    ],
    ids=["key reused", "business conflict", "invalid", "not found", "inactive actor", "down"],
)
def test_a_refused_reduction_answers_with_its_code_and_only_the_authorized_charge_state(
    error: Exception, status_code: int, code: str | None
) -> None:
    flow, property_id, charge_id = flow_and_ids()
    flow.reduction_error = error
    answer = api(flow, actor(property_id, "late_payment.charge_correction")).post(
        path(charge_id), json=BODY, headers=mutation_headers()
    )
    assert answer.status_code == status_code
    if code is not None:
        assert answer.json()["error"]["code"] == code
    if code == "CONFLICT":
        assert answer.json()["error"]["current_state"]["id"] == str(charge_id)
    assert "exception" not in answer.text.lower()


@pytest.mark.parametrize(
    ("sqlstate", "status_code"),
    [("40P01", 409), ("40001", 409)]
    + [(code, 503) for code in ("55P03", "23505", "23514", "55000", "57014", "08006", "XX000")],
)
def test_only_a_rolled_back_lock_conflict_answers_conflict_on_the_real_service(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str, status_code: int
) -> None:
    """Round 2 review: on this route a detected deadlock or serialization failure answers 409
    with the charge state (the transaction was rolled back after the replay check); every other
    database fault stays 503 and shows no state."""
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    fault = psycopg.errors.lookup(sqlstate)("private database fault must not reach the client")
    state = charge_resource(property_id, invoice_id, charge_id)

    def cursor(value: object) -> MagicMock:
        result = MagicMock()
        result.fetchone.return_value = (value,)
        return result

    def read_query(query: str, parameters: tuple[object, ...]) -> MagicMock:
        if "set_config" in query:
            return cursor(None)
        if "property_id" in query:
            return cursor(property_id)
        return cursor(state)

    def command_query(query: str, parameters: tuple[object, ...]) -> MagicMock:
        if "set_config" in query:
            return cursor(None)
        assert "reduce_late_payment_charge" in query
        raise fault

    def connect(database_url: str, *, connect_timeout: int) -> MagicMock:
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.__exit__.return_value = False
        connection.execute.side_effect = (
            read_query if database_url == "synthetic-read" else command_query
        )
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor(property_id, "late_payment.charge_correction"),
            late_payment_flow=PostgresLatePaymentService("synthetic-read", "synthetic-financial"),
        )
    )
    client.cookies.set("__Host-prm_csrf", "csrf-token")
    answer = client.post(path(charge_id), json=BODY, headers=mutation_headers())
    assert answer.status_code == status_code
    error = answer.json()["error"]
    if status_code == 409:
        assert error["code"] == "CONFLICT"
        assert error["current_state"]["id"] == str(charge_id)
    else:
        assert error["code"] == "SERVICE_UNAVAILABLE"
        assert "current_state" not in error
    assert "private database fault" not in answer.text
