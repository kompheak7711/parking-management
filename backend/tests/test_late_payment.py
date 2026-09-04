"""Focused late-payment domain and protected API coverage for V1-046."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    CapabilityGrant,
    is_authorized,
)
from property_rental.late_payment import (
    MAX_USD_MINOR_UNITS,
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentApplicationReversalRequired,
    LatePaymentCommandResponse,
    LatePaymentConflictError,
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
        "id": str(uuid5(invoice_id, "late-payment-decision")),
        "event_type": "LATE_PAYMENT_DECISION",
        "property_id": str(property_id),
        "customer_id": str(uuid5(property_id, "customer")),
        "lease_id": str(uuid5(property_id, "lease")),
        "business_date": "2026-08-31",
        "source_invoice": {"id": str(invoice_id), "due_date": "2026-08-30"},
        "overdue_balance_at_assessment": {"currency": "USD", "minor_units": 31_005},
        "default_rate_basis_points": 1000,
        "calculated_default_amount": {"currency": "USD", "minor_units": 3_101},
        "outcome": "REDUCED",
        "approved_amount": {"currency": "USD", "minor_units": 1_500},
        "assessed_at": "2026-08-31T01:02:03Z",
        "finalized_at": "2026-08-31T01:02:03Z",
        "finalized_by": str(uuid5(property_id, "manager")),
        "reason": "Approved exact reduced amount",
        "authorization_reference": "late_payment.final_decision",
        "calculation_evidence": {"rounding": "HALF_UP_TO_USD_CENT"},
        "charge": {"id": str(charge_id)},
    }


def charge_resource(property_id: UUID, invoice_id: UUID, charge_id: UUID) -> dict[str, object]:
    return {
        "id": str(charge_id),
        "event_type": "LATE_PAYMENT_CHARGE",
        "property_id": str(property_id),
        "customer_id": str(uuid5(property_id, "customer")),
        "lease_id": str(uuid5(property_id, "lease")),
        "business_date": "2026-08-31",
        "source_invoice": {"id": str(invoice_id)},
        "decision": {"id": str(uuid5(invoice_id, "late-payment-decision"))},
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
        "created_by": str(uuid5(property_id, "manager")),
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
    decision_responses: dict[
        UUID, tuple[FinalizeLatePaymentDecisionCommand, LatePaymentCommandResponse]
    ] = field(default_factory=dict)
    correction_responses: dict[
        UUID, tuple[CorrectLatePaymentChargeCommand, LatePaymentCommandResponse]
    ] = field(default_factory=dict)

    def _authorize(self, resolved_actor: AuthenticatedActor, capability: str) -> None:
        if not is_authorized(
            resolved_actor,
            AuthorizationRequirement(capability, str(self.property_id)),
        ):
            raise LatePaymentNotFoundError

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        if invoice_id != self.invoice_id:
            raise LatePaymentNotFoundError
        return self.property_id

    def property_for_charge(self, charge_id: UUID) -> UUID:
        if charge_id != self.charge_id:
            raise LatePaymentNotFoundError
        return self.property_id

    def review(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        self._authorize(actor, "late_payment.review")
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
        self._authorize(actor, "late_payment.review")
        assert invoice_id == self.invoice_id
        return decision_resource(self.property_id, self.invoice_id, self.charge_id)

    def get_charge(self, charge_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        self._authorize(actor, "late_payment.review")
        assert charge_id == self.charge_id
        return charge_resource(self.property_id, self.invoice_id, self.charge_id)

    def decision_conflict_state(
        self, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self._authorize(actor, "late_payment.final_decision")
        assert invoice_id == self.invoice_id
        return decision_resource(self.property_id, self.invoice_id, self.charge_id)

    def charge_conflict_state(
        self, charge_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self._authorize(actor, "late_payment.charge_correction")
        assert charge_id == self.charge_id
        return charge_resource(self.property_id, self.invoice_id, self.charge_id)

    def finalize_decision(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: FinalizeLatePaymentDecisionCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse:
        self._authorize(actor, "late_payment.final_decision")
        assert property_id == self.property_id
        assert invoice_id == self.invoice_id
        if self.decision_error is not None:
            raise self.decision_error
        prior = self.decision_responses.get(command.idempotency_key)
        if prior is not None:
            if prior[0] != command:
                raise LatePaymentIdempotencyKeyReused
            return prior[1]
        self.decisions.append(command)
        response = LatePaymentCommandResponse(
            201,
            {
                "data": decision_resource(self.property_id, self.invoice_id, self.charge_id),
                "meta": {"request_id": request_id},
            },
        )
        self.decision_responses[command.idempotency_key] = (command, response)
        return response

    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse:
        self._authorize(actor, "late_payment.charge_correction")
        assert property_id == self.property_id
        assert charge_id == self.charge_id
        if self.correction_error is not None:
            raise self.correction_error
        prior = self.correction_responses.get(command.idempotency_key)
        if prior is not None:
            if prior[0] != command:
                raise LatePaymentIdempotencyKeyReused
            return prior[1]
        self.corrections.append(command)
        response = LatePaymentCommandResponse(
            200,
            {
                "data": charge_resource(self.property_id, self.invoice_id, self.charge_id),
                "meta": {"request_id": request_id},
            },
        )
        self.correction_responses[command.idempotency_key] = (command, response)
        return response


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

    correction_client = api(flow, actor(property_id, "late_payment.charge_correction"))
    correction_headers = mutation_headers()
    correction_headers["X-Request-ID"] = "late-payment-correction-original"
    corrected = correction_client.post(
        correction_path, json=correction_body, headers=correction_headers
    )
    replayed = correction_client.post(
        correction_path,
        json=correction_body,
        headers={**correction_headers, "X-Request-ID": "late-payment-correction-replay"},
    )
    assert corrected.status_code == replayed.status_code == 200
    assert "Location" not in corrected.headers
    assert "Location" not in replayed.headers
    assert replayed.json() == corrected.json()
    assert corrected.json()["meta"] == {"request_id": "late-payment-correction-original"}
    assert replayed.headers["X-Request-ID"] == "late-payment-correction-replay"
    assert len(flow.corrections) == 1
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


def test_generic_conflicts_return_only_authorized_current_safe_state() -> None:
    property_id, invoice_id, charge_id = uuid4(), uuid4(), uuid4()
    flow = InMemoryLatePaymentFlow(property_id, invoice_id, charge_id)
    decision_path = f"/api/v1/invoices/{invoice_id}/late-payment-decision"
    decision_body = {
        "outcome": "WAIVED",
        "approved_amount": {"currency": "USD", "minor_units": 0},
        "reason": "Approved waiver",
    }
    flow.decision_error = LatePaymentConflictError()

    hidden = api(flow, actor(uuid4(), "late_payment.final_decision")).post(
        decision_path,
        json=decision_body,
        headers=mutation_headers(),
    )
    assert hidden.status_code == 404
    assert "current_state" not in hidden.text

    decision_conflict = api(flow, actor(property_id, "late_payment.final_decision")).post(
        decision_path, json=decision_body, headers=mutation_headers()
    )
    assert decision_conflict.status_code == 409
    decision_error = decision_conflict.json()["error"]
    assert decision_error["code"] == "CONFLICT"
    assert decision_error["current_version"] is None
    assert decision_error["current_state"] == decision_resource(property_id, invoice_id, charge_id)

    flow.correction_error = LatePaymentConflictError()
    correction_conflict = api(flow, actor(property_id, "late_payment.charge_correction")).post(
        f"/api/v1/late-payment-charges/{charge_id}/corrections",
        json={"kind": "CHARGE_REVERSAL", "reason": "Reverse the charge"},
        headers=mutation_headers(),
    )
    assert correction_conflict.status_code == 409
    correction_error = correction_conflict.json()["error"]
    assert correction_error["current_version"] is None
    assert correction_error["current_state"] == charge_resource(property_id, invoice_id, charge_id)
    assert "exception" not in correction_conflict.text.lower()


def test_late_payment_traceability_mappings_are_truthful() -> None:
    manifest_path = Path(__file__).parents[2] / "ops" / "traceability.json"
    manifest = json.loads(manifest_path.read_text())
    late_payment_mappings = {
        entry["test_id"]: entry["upstream_ids"]
        for entry in manifest["entries"]
        if entry["test_path"]
        in {
            "backend/tests/test_late_payment.py",
            "backend/tests/test_late_payment_migration.py",
        }
    }
    assert late_payment_mappings == {
        "test_actual_cross_actor_cookie_and_csrf_replay_is_rejected_before_second_reduction": [
            "SEC-028",
            "API-015",
            "API-016",
            "DL-039",
        ],
        "test_final_decision_rejects_foreign_confirming_actor": ["SEC-028", "API-091"],
        "test_final_decision_command_preserves_only_canonical_client_intent": [
            "API-005",
            "API-091",
        ],
        "test_commands_reject_untrusted_or_inconsistent_shapes": [
            "API-005",
            "API-091",
            "TEST-123",
            "TEST-124",
        ],
        "test_all_five_routes_require_authentication_exact_capability_and_scope": [
            "API-009",
            "API-091",
            "SEC-020",
            "SEC-070",
            "TEST-123",
            "TEST-124",
        ],
        "test_mutations_enforce_independent_capabilities_csrf_and_server_owned_fields": [
            "API-009",
            "API-011",
            "API-015",
            "API-016",
            "API-091",
            "SEC-020",
            "SEC-070",
            "TEST-123",
            "TEST-124",
        ],
        "test_decision_api_rejects_noncanonical_outcomes_and_money": [
            "API-005",
            "API-091",
            "TEST-123",
        ],
        "test_late_payment_special_conflicts_return_safe_semantic_errors": [
            "API-016",
            "API-091",
            "BR-LATE-005",
            "TEST-124",
        ],
        "test_generic_conflicts_return_only_authorized_current_safe_state": [
            "API-018",
            "SEC-020",
        ],
        "test_late_payment_traceability_mappings_are_truthful": [
            "TEST-117",
            "TEST-119",
        ],
        "test_review_decisions_replay_and_source_isolation_use_authoritative_current_balance": [
            "BR-INV-051",
            "BR-INV-052",
            "BR-INV-053",
            "BR-INV-054",
            "BR-INV-055",
            "API-016",
            "API-025",
            "API-091",
            "DB-INV-007",
            "DB-INV-008",
            "TEST-123",
        ],
        "test_real_api_exact_replay_and_mutation_only_conflict_state": [
            "API-011",
            "API-016",
            "API-018",
            "SEC-020",
            "SEC-022",
            "SEC-070",
        ],
        "test_two_actors_share_uuid_without_correlation_collision_and_keep_replay_scope": [
            "API-015",
            "API-016",
            "API-017",
            "SEC-019",
            "SEC-069",
        ],
        "test_waiver_default_and_ineligible_boundaries_do_not_create_arbitrary_receivables": [
            "BR-INV-053",
            "BR-INV-054",
            "BR-INV-055",
            "BR-LATE-003",
            "API-091",
            "DB-INV-007",
            "TEST-123",
        ],
        "test_zero_rounded_confirmed_default_preserves_decision_without_charge": [
            "BR-INV-052",
            "BR-INV-053",
            "BR-INV-054",
            "BR-INV-055",
            "BR-LATE-001",
            "API-091",
            "DB-INV-007",
            "DB-INV-008",
            "TEST-123",
        ],
        "test_review_due_date_boundary_is_property_local_and_never_posts_automatically": [
            "BR-INV-051",
            "BR-INV-053",
            "API-091",
            "TEST-123",
        ],
        "test_corrections_preserve_original_history_bounds_and_future_application_boundary": [
            "BR-LATE-004",
            "BR-LATE-005",
            "API-016",
            "API-091",
            "DB-INV-009",
            "DB-DER-009",
            "DB-VIEW-007",
            "TEST-124",
        ],
        "test_concurrent_decisions_and_over_reductions_commit_at_most_one_effect": [
            "API-017",
            "API-018",
            "API-091",
            "DB-TXN-007",
            "SEC-029",
            "TEST-123",
            "TEST-124",
        ],
        "test_audit_failure_rolls_back_decision_charge_and_command": [
            "API-017",
            "API-091",
            "BR-AUDIT-006",
            "TEST-123",
        ],
        "test_late_payment_runtime_privileges_are_least_privilege_and_forward_only": [
            "API-091",
            "DB-VIEW-007",
            "SEC-025",
        ],
        "test_revision_36_upgrades_to_late_payment_api_head": ["DB-MIG-001"],
    }


class ActorScopedCorrectionFlow(InMemoryLatePaymentFlow):
    """Exercise the HTTP boundary against actor-scoped successful receipts."""

    def __init__(self, property_id: UUID, invoice_id: UUID, charge_id: UUID) -> None:
        super().__init__(property_id, invoice_id, charge_id)
        self.balance = 1500
        self.receipts: dict[tuple[str, UUID], LatePaymentCommandResponse] = {}

    def correct_charge(
        self,
        property_id: UUID,
        charge_id: UUID,
        command: CorrectLatePaymentChargeCommand,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LatePaymentCommandResponse:
        self._authorize(actor, "late_payment.charge_correction")
        identity = (actor.actor_id, command.idempotency_key)
        if identity in self.receipts:
            return self.receipts[identity]
        assert command.amount_usd_cents == 500
        self.balance -= command.amount_usd_cents
        self.corrections.append(command)
        resource = charge_resource(property_id, self.invoice_id, charge_id)
        resource["adjusted_obligation"] = {"currency": "USD", "minor_units": self.balance}
        resource["remaining_balance"] = resource["adjusted_obligation"]
        result = LatePaymentCommandResponse(
            200, {"data": resource, "meta": {"request_id": request_id}}
        )
        self.receipts[identity] = result
        return result


def test_actual_cross_actor_cookie_and_csrf_replay_is_rejected_before_second_reduction() -> None:
    property_id = uuid4()
    flow = ActorScopedCorrectionFlow(property_id, uuid4(), uuid4())
    first = actor(property_id, "late_payment.charge_correction")
    second = actor(property_id, "late_payment.charge_correction")
    identities = {"A": first, "B": second}
    client = TestClient(
        create_app(
            actor_resolver=lambda request: identities.get(request.cookies.get("test-session", "")),
            late_payment_flow=flow,
        ),
        base_url="https://localhost",
    )
    client.cookies.set("test-session", "A")
    client.cookies.set("__Host-prm_csrf", "csrf-A")
    key = uuid4()
    headers = {
        "Origin": "https://localhost",
        "X-CSRF-Token": "csrf-A",
        "Idempotency-Key": str(key),
        "X-Billing-Actor-ID": first.actor_id,
    }
    body = {
        "kind": "REDUCTION",
        "amount": {"currency": "USD", "minor_units": 500},
        "reason": "Approved",
    }
    url = f"/api/v1/late-payment-charges/{flow.charge_id}/corrections"
    committed = client.post(url, json=body, headers=headers)
    assert committed.status_code == 200
    assert flow.balance == 1000
    # A's response is lost. Another tab signs in as B; A's saved intent is unchanged.
    client.cookies.set("test-session", "B")
    client.cookies.set("__Host-prm_csrf", "csrf-B")
    headers["X-CSRF-Token"] = "csrf-B"
    rejected = client.post(url, json=body, headers=headers)
    assert rejected.status_code == 403
    assert flow.balance == 1000
    assert len(flow.corrections) == 1
    assert (second.actor_id, key) not in flow.receipts
    client.cookies.set("test-session", "A")
    client.cookies.set("__Host-prm_csrf", "csrf-A")
    headers["X-CSRF-Token"] = "csrf-A"
    assert client.post(url, json=body, headers=headers).json() == committed.json()
    assert len(flow.corrections) == 1
    # Legacy clients retain actor-scoped receipts; the binding does not globalize keys.
    client.cookies.set("test-session", "B")
    headers.pop("X-Billing-Actor-ID")
    assert client.post(url, json=body, headers=headers).status_code == 200
    assert (second.actor_id, key) in flow.receipts


def test_final_decision_rejects_foreign_confirming_actor() -> None:
    property_id = uuid4()
    flow = InMemoryLatePaymentFlow(property_id, uuid4(), uuid4())
    current = actor(property_id, "late_payment.final_decision")
    result = api(flow, current).post(
        f"/api/v1/invoices/{flow.invoice_id}/late-payment-decision",
        json={
            "outcome": "WAIVED",
            "approved_amount": {"currency": "USD", "minor_units": 0},
            "reason": "Approved",
        },
        headers={**mutation_headers(), "X-Billing-Actor-ID": str(uuid4())},
    )
    assert result.status_code == 403
    assert flow.decisions == []
