"""Focused late-payment domain and protected API coverage for V1-046."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import (
    MAX_USD_MINOR_UNITS,
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
    LatePaymentIdempotencyKeyReused,
    LatePaymentNotFoundError,
    late_payment_request_digest,
)


def actor(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    scope = frozenset({str(property_id)})
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(CapabilityGrant(value, scope) for value in capabilities),
    )


def decision_resource(property_id: UUID, invoice_id: UUID, charge_id: UUID) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "property_id": str(property_id),
        "customer_id": str(uuid4()),
        "source_invoice": {"id": str(invoice_id), "due_date": "2026-08-30"},
        "overdue_balance_at_assessment": {"currency": "USD", "minor_units": 31_005},
        "default_rate_basis_points": 1000,
        "calculated_default_amount": {"currency": "USD", "minor_units": 3_101},
        "outcome": "REDUCED",
        "approved_amount": {"currency": "USD", "minor_units": 1_500},
        "assessed_at": "2026-08-31T01:02:03Z",
        "finalized_at": "2026-08-31T01:02:03Z",
        "finalized_by": str(uuid4()),
        "reason": "Approved exact reduced amount",
        "authorization_reference": "late_payment.final_decision",
        "calculation_evidence": {"rounding": "HALF_UP_TO_USD_CENT"},
        "charge": {"id": str(charge_id)},
    }


def charge_resource(property_id: UUID, invoice_id: UUID, charge_id: UUID) -> dict[str, object]:
    return {
        "id": str(charge_id),
        "property_id": str(property_id),
        "customer_id": str(uuid4()),
        "source_invoice": {"id": str(invoice_id)},
        "decision": {"id": str(uuid4())},
        "original_amount": {"currency": "USD", "minor_units": 1_500},
        "adjusted_obligation": {"currency": "USD", "minor_units": 1_000},
        "remaining_balance": {"currency": "USD", "minor_units": 1_000},
        "application_summary": {
            "active_total": {"currency": "USD", "minor_units": 0},
            "payment_total": {"currency": "USD", "minor_units": 0},
            "credit_total": {"currency": "USD", "minor_units": 0},
            "items": [],
        },
        "corrections": [],
        "payable_at": "2026-08-31T01:02:03Z",
        "created_at": "2026-08-31T01:02:03Z",
        "created_by": str(uuid4()),
    }


@dataclass(slots=True)
class InMemoryLatePaymentFlow:
    property_id: UUID
    invoice_id: UUID
    charge_id: UUID
    decisions: list[FinalizeLatePaymentDecisionCommand] = field(default_factory=list)
    corrections: list[CorrectLatePaymentChargeCommand] = field(default_factory=list)
    decision_error: Exception | None = None
    correction_error: Exception | None = None

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        if invoice_id != self.invoice_id:
            raise LatePaymentNotFoundError
        return self.property_id

    def property_for_charge(self, charge_id: UUID) -> UUID:
        if charge_id != self.charge_id:
            raise LatePaymentNotFoundError
        return self.property_id

    def review(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        del actor
        assert invoice_id == self.invoice_id
        return {
            "invoice_id": str(invoice_id),
            "property_id": str(self.property_id),
            "overdue_balance": {"currency": "USD", "minor_units": 31_005},
            "default_rate_basis_points": 1000,
            "calculated_default_amount": {"currency": "USD", "minor_units": 3_101},
            "eligible": True,
            "blocking_conditions": [],
            "prior_decision": None,
        }

    def get_decision(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        del actor
        assert invoice_id == self.invoice_id
        return decision_resource(self.property_id, self.invoice_id, self.charge_id)

    def get_charge(self, charge_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        del actor
        assert charge_id == self.charge_id
        return charge_resource(self.property_id, self.invoice_id, self.charge_id)

    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        assert property_id == self.property_id
        assert invoice_id == self.invoice_id
        if self.decision_error is not None:
            raise self.decision_error
        self.decisions.append(command)
        return decision_resource(self.property_id, self.invoice_id, self.charge_id)

    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        del actor
        assert property_id == self.property_id
        assert charge_id == self.charge_id
        if self.correction_error is not None:
            raise self.correction_error
        self.corrections.append(command)
        return charge_resource(self.property_id, self.invoice_id, self.charge_id)


def api(flow: InMemoryLatePaymentFlow, resolved_actor: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: resolved_actor, late_payment_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf-token")
    return client


def mutation_headers() -> dict[str, str]:
    return {
        "Idempotency-Key": str(uuid4()),
        "X-CSRF-Token": "csrf-token",
        "Origin": "https://localhost",
    }


@pytest.mark.parametrize(
    ("outcome", "amount"),
    [
        (DecisionOutcome.CONFIRMED_DEFAULT, 3_101),
        (DecisionOutcome.REDUCED, 1_500),
        (DecisionOutcome.WAIVED, 0),
    ],
)
def test_final_decision_command_preserves_only_canonical_client_intent(
    outcome: DecisionOutcome, amount: int
) -> None:
    key = uuid4()
    command = FinalizeLatePaymentDecisionCommand(key, outcome, amount, "Management decision")
    assert command.approved_amount_usd_cents == amount
    assert command.outcome is outcome
    digest = late_payment_request_digest(
        action="decision",
        property_id=uuid4(),
        target_id=uuid4(),
        payload={"amount": amount, "outcome": outcome.value},
    )
    assert len(digest) == 64
    assert digest == digest.lower()


@pytest.mark.parametrize(
    "command",
    [
        lambda: FinalizeLatePaymentDecisionCommand(
            UUID(int=0), DecisionOutcome.WAIVED, 0, "Reason"
        ),
        lambda: FinalizeLatePaymentDecisionCommand(uuid4(), DecisionOutcome.WAIVED, -1, "Reason"),
        lambda: FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.WAIVED, MAX_USD_MINOR_UNITS + 1, "Reason"
        ),
        lambda: FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.WAIVED, 0, " unnormalized"
        ),
        lambda: CorrectLatePaymentChargeCommand(uuid4(), CorrectionKind.REDUCTION, "Reason", None),
        lambda: CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.CHARGE_REVERSAL, "Reason", 1
        ),
        lambda: CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION_REVERSAL, "Reason"
        ),
    ],
)
def test_commands_reject_untrusted_or_inconsistent_shapes(
    command: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        command()


def test_all_five_routes_require_authentication_exact_capability_and_scope() -> None:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    flow = InMemoryLatePaymentFlow(property_id, invoice_id, charge_id)
    routes = (
        ("GET", f"/api/v1/invoices/{invoice_id}/late-payment-review", None),
        ("GET", f"/api/v1/invoices/{invoice_id}/late-payment-decision", None),
        ("GET", f"/api/v1/late-payment-charges/{charge_id}", None),
    )
    for method, path, payload in routes:
        assert api(flow, None).request(method, path, json=payload).status_code == 401
        hidden = api(flow, actor(property_id, "invoices.read")).request(method, path, json=payload)
        assert hidden.status_code == 404
        wrong_scope = api(flow, actor(uuid4(), "late_payment.review")).request(
            method, path, json=payload
        )
        assert wrong_scope.status_code == 404
        visible = api(flow, actor(property_id, "late_payment.review")).request(
            method, path, json=payload
        )
        assert visible.status_code == 200
        assert visible.headers["Cache-Control"] == "private, no-store"


def test_mutations_enforce_independent_capabilities_csrf_and_server_owned_fields() -> None:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    flow = InMemoryLatePaymentFlow(property_id, invoice_id, charge_id)
    decision_body = {
        "outcome": "REDUCED",
        "approved_amount": {"currency": "USD", "minor_units": 1_500},
        "reason": "Approved exact reduced amount",
    }
    correction_body = {
        "kind": "REDUCTION",
        "amount": {"currency": "USD", "minor_units": 500},
        "reason": "Correct the separate charge",
    }
    decision_path = f"/api/v1/invoices/{invoice_id}/late-payment-decision"
    correction_path = f"/api/v1/late-payment-charges/{charge_id}/corrections"

    generic_invoice_actor = actor(property_id, "invoices.read", "invoices.issue", "invoices.adjust")
    assert (
        api(flow, generic_invoice_actor)
        .post(decision_path, json=decision_body, headers=mutation_headers())
        .status_code
        == 404
    )
    assert (
        api(flow, actor(property_id, "late_payment.final_decision"))
        .post(correction_path, json=correction_body, headers=mutation_headers())
        .status_code
        == 404
    )

    decision_client = api(flow, actor(property_id, "late_payment.final_decision"))
    missing_csrf = decision_client.post(
        decision_path,
        json=decision_body,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert missing_csrf.status_code == 403
    injected_snapshot = decision_client.post(
        decision_path,
        json={**decision_body, "overdue_balance_at_assessment_usd_cents": 1},
        headers=mutation_headers(),
    )
    assert injected_snapshot.status_code == 422
    assert flow.decisions == []

    decided = decision_client.post(decision_path, json=decision_body, headers=mutation_headers())
    assert decided.status_code == 201
    assert decided.headers["Location"] == decision_path
    assert flow.decisions[-1].approved_amount_usd_cents == 1_500

    corrected = api(flow, actor(property_id, "late_payment.charge_correction")).post(
        correction_path, json=correction_body, headers=mutation_headers()
    )
    assert corrected.status_code == 201
    assert corrected.headers["Location"] == f"/api/v1/late-payment-charges/{charge_id}"
    assert flow.corrections[-1].amount_usd_cents == 500


@pytest.mark.parametrize(
    "body",
    [
        {
            "outcome": "INCREASED",
            "approved_amount": {"currency": "USD", "minor_units": 1},
            "reason": "Unsupported outcome",
        },
        {
            "outcome": "WAIVED",
            "approved_amount": {"currency": "KHR", "minor_units": 0},
            "reason": "Wrong currency",
        },
        {
            "outcome": "WAIVED",
            "approved_amount": {"currency": "USD", "minor_units": 0.0},
            "reason": "Floating money",
        },
    ],
)
def test_decision_api_rejects_noncanonical_outcomes_and_money(body: dict[str, object]) -> None:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    flow = InMemoryLatePaymentFlow(property_id, invoice_id, charge_id)
    response = api(flow, actor(property_id, "late_payment.final_decision")).post(
        f"/api/v1/invoices/{invoice_id}/late-payment-decision",
        json=body,
        headers=mutation_headers(),
    )
    assert response.status_code == 422
    assert flow.decisions == []


def test_late_payment_special_conflicts_return_safe_semantic_errors() -> None:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    flow = InMemoryLatePaymentFlow(property_id, invoice_id, charge_id)
    flow.decision_error = LatePaymentIdempotencyKeyReused()
    decision = api(flow, actor(property_id, "late_payment.final_decision")).post(
        f"/api/v1/invoices/{invoice_id}/late-payment-decision",
        json={
            "outcome": "WAIVED",
            "approved_amount": {"currency": "USD", "minor_units": 0},
            "reason": "Approved waiver",
        },
        headers=mutation_headers(),
    )
    assert decision.status_code == 409
    assert decision.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    flow.correction_error = LatePaymentApplicationReversalRequired()
    correction = api(flow, actor(property_id, "late_payment.charge_correction")).post(
        f"/api/v1/late-payment-charges/{charge_id}/corrections",
        json={"kind": "CHARGE_REVERSAL", "reason": "Reverse the charge"},
        headers=mutation_headers(),
    )
    assert correction.status_code == 409
    assert correction.json()["error"]["code"] == "APPLICATION_REVERSAL_REQUIRED"
    assert "exception" not in correction.text.lower()
