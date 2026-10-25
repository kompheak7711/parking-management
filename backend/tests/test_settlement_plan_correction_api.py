"""The post-settlement correction routes with a DL-032 plan, the Deposit receipt correction and
the return reversal (V1-056 slice 11e-3; API-072)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.app import create_app
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    PetRemainderBasis,
    PetRemainderDecision,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementTargetKind,
)
from property_rental.final_settlement_api import FINAL_SETTLEMENT_PLAN_REFUSALS
from property_rental.identity import AuthenticatedActor
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    RecordDepositReceiptCorrectionCommand,
    RecordForfeitureReversalCorrectionCommand,
    RecordHeldValueRefundCorrectionCommand,
    RecordLateChargeRefundCorrectionCommand,
    RecordPetClassificationCorrectionCommand,
    RecordRefundCorrectionCommand,
    RecordRefundReturnCorrectionCommand,
    RecordReturnReversalCorrectionCommand,
)
from property_rental.settlement_correction_api import (
    CORRECTION_REFUSALS,
    FORFEITURE_REVERSAL_REFUSALS,
    HELD_VALUE_REFUND_REFUSALS,
    LATE_CHARGE_REFUND_REFUSALS,
    PET_CLASSIFICATION_REFUSALS,
    PLAN_CORRECTION_REFUSALS,
    RECEIPT_CORRECTION_REFUSALS,
    REFUND_CORRECTION_REFUSALS,
    REFUND_RETURN_REFUSALS,
    RETURN_REVERSAL_REFUSALS,
)
from test_invoice import actor, mutation_headers
from test_settlement_correction_api import Route, _refused

PREPARE = "final_settlements.prepare"
INVOICE, LINE, CHARGE, METHOD, REFUND, EARLIER, DISPOSITION, RECEIPT, DEPOSIT, CREDIT = (
    uuid4() for _ in range(10)
)
CUSTOMER, TARGET = uuid4(), uuid4()
REASON = "Found after the move-out review"
NOTE = "Cash handed over at the front desk"
EVIDENCE = "Bank notice 2026-10-20"
RETURNED_AT = "2026-10-20T09:30:00+07:00"
STEPS: Final[list[dict[str, object]]] = [
    {
        "kind": "CUSTOMER_CREDIT",
        "customer_credit_id": str(CREDIT),
        "target_kind": "INVOICE_LINE",
        "target_id": str(TARGET),
        "amount_usd_cents": 400,
    },
    {
        "kind": "DEPOSIT_REFUNDS",
        "deposit_id": str(DEPOSIT),
        "amount_usd_cents": 600,
        "refund_method_id": str(METHOD),
        "reference_note": NOTE,
        "recipient_customer_id": str(CUSTOMER),
    },
]
PLAN: Final[dict[str, object]] = {
    "steps": STEPS,
    "pet_remainder": {"basis": "STAFF_REASON", "staff_reason": "The Customer will not pay"},
}
COMMAND_STEPS: Final = (
    SettlementCreditStep(CREDIT, SettlementTargetKind.INVOICE_LINE, TARGET, 400, None),
    SettlementDepositRefund(DEPOSIT, 600, METHOD, NOTE, CUSTOMER, None),
)
REMAINDER: Final = PetRemainderDecision(
    PetRemainderBasis.STAFF_REASON, "The Customer will not pay", None
)
ERROR: Final = FinalSettlementConflictError


def _route(
    name: str,
    suffix: str,
    body: Mapping[str, object],
    variant: str,
    payload: Mapping[str, object],
    refusals: Mapping[str, object],
) -> Route:
    return Route(name, f"corrections/{suffix}", body, variant, payload, refusals, ERROR)  # type: ignore[arg-type]


ROUTES: Final = (
    _route(
        "refund",
        "refunds",
        {
            **PLAN,
            "invoice_id": str(INVOICE),
            "invoice_line_id": str(LINE),
            "amount_usd_cents": 1_000,
            "refund_method_id": str(METHOD),
            "reference_note": NOTE,
            "reason": REASON,
        },
        "REFUND",
        {"refund": {"invoice_line_id": str(LINE)}},
        REFUND_CORRECTION_REFUSALS,
    ),
    _route(
        "late_charge_refund",
        "late-charge-refunds",
        {
            **PLAN,
            "late_payment_charge_id": str(CHARGE),
            "amount_usd_cents": 1_000,
            "refund_method_id": str(METHOD),
            "reference_note": NOTE,
            "reason": REASON,
        },
        "REFUND",
        {"target_kind": "LATE_PAYMENT_CHARGE", "refund": {"late_payment_charge_id": str(CHARGE)}},
        LATE_CHARGE_REFUND_REFUSALS,
    ),
    _route(
        "pet_classification",
        "pet-classifications",
        {
            **PLAN,
            "invoice_id": str(INVOICE),
            "invoice_line_id": str(LINE),
            "pet_related": True,
            "evidence_reference": EVIDENCE,
            "reason": REASON,
        },
        "PET_DAMAGE_RECLASSIFICATION",
        {"classification": {"invoice_line_id": str(LINE)}},
        PET_CLASSIFICATION_REFUSALS,
    ),
    _route(
        "refund_return",
        "refund-returns",
        {
            **PLAN,
            "refund_id": str(REFUND),
            "returned_amount_usd_cents": 1_000,
            "returned_at": RETURNED_AT,
            "return_method_reference": "ABA return 7781",
            "evidence_reference": EVIDENCE,
            "reason": REASON,
            "new_refund_method_id": str(METHOD),
            "new_refund_reference_note": NOTE,
        },
        "REFUND_RETURN",
        {"refund_return": {"refund_id": str(REFUND)}},
        REFUND_RETURN_REFUSALS,
    ),
    _route(
        "held_value_refund",
        "held-value-refunds",
        {
            **PLAN,
            "held_from_correction_id": str(EARLIER),
            "reason": REASON,
            "new_refund_method_id": str(METHOD),
            "new_refund_reference_note": NOTE,
        },
        "HELD_VALUE_REFUND",
        {"held_from_settlement_correction_id": str(EARLIER)},
        HELD_VALUE_REFUND_REFUSALS,
    ),
    _route(
        "forfeiture_reversal",
        "forfeiture-reversals",
        {
            **PLAN,
            "deposit_disposition_id": str(DISPOSITION),
            "reason": REASON,
            "evidence_reference": EVIDENCE,
            "refund_method_id": str(METHOD),
            "reference_note": NOTE,
        },
        "FORFEITURE_REVERSAL",
        {"deposit_disposition_id": str(DISPOSITION)},
        FORFEITURE_REVERSAL_REFUSALS,
    ),
    _route(
        "deposit_receipt_correction",
        "deposit-receipt-corrections",
        {
            **PLAN,
            "deposit_receipt_id": str(RECEIPT),
            "reason": REASON,
            "evidence_reference": EVIDENCE,
            "receipts": [
                {"deposit_id": str(DEPOSIT), "amount_usd_cents": 600},
                {
                    "deposit_id": str(CREDIT),
                    "amount_usd_cents": 400,
                    "outcome": "FORFEIT",
                    "outcome_reason": "The pet rule was broken",
                },
            ],
        },
        "DEPOSIT_RECEIPT_CORRECTION",
        {"deposit_receipt_id": str(RECEIPT)},
        RECEIPT_CORRECTION_REFUSALS,
    ),
    _route(
        "return_reversal",
        "return-reversals",
        {"earlier_correction_id": str(EARLIER), "reason": REASON, "evidence_reference": EVIDENCE},
        "RETURN_REVERSAL",
        {"held_from_settlement_correction_id": str(EARLIER)},
        RETURN_REVERSAL_REFUSALS,
    ),
)
BY_NAME: Final = {route.name: route for route in ROUTES}


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    settlement: UUID = field(default_factory=uuid4)
    error: Exception | None = None
    answer: object = None
    calls: list[tuple[str, UUID, object]] = field(default_factory=list)

    def result(self, name: str, prop: UUID) -> dict[str, object]:
        route = BY_NAME[name]
        return {
            "draft_id": str(uuid4()),
            "property_id": str(prop),
            "kind": "SETTLEMENT_CORRECTION",
            "payload": {
                **route.payload,
                "variant": route.variant,
                "final_settlement_id": str(self.settlement),
            },
            "state": "PENDING",
        }

    def __getattr__(self, name: str) -> Callable[..., object]:
        if name not in BY_NAME:
            raise AttributeError(name)

        def call(property_id: UUID, command: object, *, actor: AuthenticatedActor) -> object:
            self.calls.append((name, property_id, command))
            if self.error is not None:
                raise self.error
            return self.answer if self.answer is not None else self.result(name, property_id)

        return call


def _post(
    flow: Flow,
    route: Route,
    *,
    who: AuthenticatedActor | None = None,
    body: Mapping[str, object] | None = None,
    key: UUID | None = None,
) -> Response:
    person = who or actor(flow.prop, PREPARE)
    client = TestClient(
        create_app(actor_resolver=lambda _: person, settlement_correction_flow=flow)  # type: ignore[arg-type]
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    answer: Response = client.post(
        f"/api/v1/properties/{flow.prop}/final-settlements/{flow.settlement}/{route.suffix}",
        json=dict(route.body if body is None else body),
        headers=mutation_headers(key=key),
    )
    return answer


def _commands(flow: Flow, key: UUID) -> dict[str, object]:
    s = flow.settlement
    plan = (COMMAND_STEPS, REMAINDER)
    return {
        "refund": RecordRefundCorrectionCommand(
            key, s, INVOICE, LINE, 1_000, METHOD, NOTE, REASON, *plan
        ),
        "late_charge_refund": RecordLateChargeRefundCorrectionCommand(
            key, s, CHARGE, 1_000, METHOD, NOTE, REASON, *plan
        ),
        "pet_classification": RecordPetClassificationCorrectionCommand(
            key, s, INVOICE, LINE, True, EVIDENCE, REASON, *plan
        ),
        "refund_return": RecordRefundReturnCorrectionCommand(
            key,
            s,
            REFUND,
            1_000,
            datetime(2026, 10, 20, 2, 30, tzinfo=UTC),
            "ABA return 7781",
            EVIDENCE,
            REASON,
            METHOD,
            NOTE,
            *plan,
        ),
        "held_value_refund": RecordHeldValueRefundCorrectionCommand(
            key, s, EARLIER, REASON, METHOD, NOTE, *plan
        ),
        "forfeiture_reversal": RecordForfeitureReversalCorrectionCommand(
            key, s, DISPOSITION, REASON, EVIDENCE, METHOD, NOTE, *plan
        ),
        "deposit_receipt_correction": RecordDepositReceiptCorrectionCommand(
            key,
            s,
            RECEIPT,
            REASON,
            EVIDENCE,
            (
                CorrectionDepositReceipt(DEPOSIT, 600),
                CorrectionDepositReceipt(CREDIT, 400, "FORFEIT", "The pet rule was broken"),
            ),
            *plan,
        ),
        "return_reversal": RecordReturnReversalCorrectionCommand(key, s, EARLIER, REASON, EVIDENCE),
    }


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_each_plan_correction_draft_is_recorded_from_its_form(route: Route) -> None:
    flow, key = Flow(), uuid4()
    answer = _post(flow, route, key=key)
    assert answer.status_code == 201, answer.text
    assert answer.json()["data"]["payload"]["variant"] == route.variant
    [(name, prop, command)] = flow.calls
    assert (name, prop, command) == (route.name, flow.prop, _commands(flow, key)[route.name])


def test_a_refund_return_records_the_instant_it_was_returned() -> None:
    """The return instant keeps its offset to the command; the command keeps it in UTC."""
    flow = Flow()
    _post(flow, BY_NAME["refund_return"])
    [(_, _, command)] = flow.calls
    assert isinstance(command, RecordRefundReturnCorrectionCommand)
    assert command.returned_at == datetime(2026, 10, 20, 2, 30, tzinfo=UTC)


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_each_plan_route_needs_final_settlements_prepare(route: Route) -> None:
    flow = Flow()
    assert _post(flow, route, who=actor(flow.prop, "financial.approve")).status_code == 404
    assert _post(flow, route, who=actor(uuid4(), PREPARE)).status_code == 404
    assert flow.calls == []


@pytest.mark.parametrize(
    ("name", "change", "fields"),
    [
        ("refund", {"amount_usd_cents": 0}, ["body.amount_usd_cents"]),
        ("refund", {"reason": "x" * 501}, ["body.reason"]),
        ("refund", {"steps": [{**STEPS[0], "kind": "OTHER"}]}, ["body.steps"]),
        ("refund", {"steps": [STEPS[0]] * 201}, ["body.steps"]),
        ("late_charge_refund", {"reference_note": ""}, ["body.reference_note"]),
        ("pet_classification", {"pet_related": "true"}, ["body.pet_related"]),
        ("refund_return", {"returned_at": "2026-10-20T09:30:00"}, ["body.returned_at"]),
        ("refund_return", {"new_refund_reference_note": None}, ["body.new_refund_reference_note"]),
        ("held_value_refund", {"new_refund_method_id": None}, ["body.new_refund_method_id"]),
        ("forfeiture_reversal", {"evidence_reference": " x"}, ["body.evidence_reference"]),
        (
            "deposit_receipt_correction",
            {"receipts": [{"deposit_id": str(DEPOSIT), "amount_usd_cents": 1}] * 3},
            ["body.receipts"],
        ),
        (
            "deposit_receipt_correction",
            {"receipts": [{"deposit_id": str(DEPOSIT), "amount_usd_cents": 1, "outcome": "KEEP"}]},
            ["body.receipts.outcome"],
        ),
        (
            "deposit_receipt_correction",
            {
                "receipts": [
                    {"deposit_id": str(DEPOSIT), "amount_usd_cents": 1, "outcome": "FORFEIT"}
                ]
            },
            ["body.receipts.outcome_reason"],
        ),
        (
            "deposit_receipt_correction",
            {"receipts": [{"deposit_id": str(DEPOSIT), "amount_usd_cents": 1}] * 2},
            ["body.receipts"],
        ),
        ("deposit_receipt_correction", {"receipts": []}, ["body.receipts"]),
        ("refund_return", {"returned_at": 1729400000}, ["body.returned_at"]),
        ("refund_return", {"returned_at": "2026-10-20 09:30:00+07:00"}, ["body.returned_at"]),
        ("return_reversal", {"steps": []}, ["body.steps"]),
    ],
)
def test_a_bad_plan_form_is_refused_on_its_field_before_any_command(
    name: str, change: dict[str, object], fields: list[str]
) -> None:
    flow, route = Flow(), BY_NAME[name]
    answer = _post(flow, route, body={**route.body, **change})
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"]["fields"] == fields
    assert flow.calls == []


def test_a_correction_with_no_steps_is_recorded_with_an_empty_plan() -> None:
    """A correction whose released value pays nothing records no step and no remainder."""
    flow, route = Flow(), BY_NAME["refund"]
    body = {key: value for key, value in route.body.items() if key not in PLAN}
    assert _post(flow, route, body=body).status_code == 201
    [(_, _, command)] = flow.calls
    assert isinstance(command, RecordRefundCorrectionCommand)
    assert (command.steps, command.pet_remainder) == ((), None)


NAMED: Final = [(route.name, message) for route in ROUTES for message in route.refusals]


@pytest.mark.parametrize(("name", "message"), NAMED)
def test_each_named_plan_correction_refusal_answers_its_own_code(name: str, message: str) -> None:
    route = BY_NAME[name]
    flow = Flow(error=_refused(message, ERROR))
    answer = _post(flow, route)
    refusal = route.refusals[message]
    body = answer.json()["error"]
    assert (answer.status_code, body["code"]) == (refusal.status_code, refusal.code)
    assert (body["rule_ids"], body["fields"]) == (list(refusal.rule_ids), list(refusal.fields))
    assert body["message"] == refusal.message


def test_the_plan_correction_codes_are_pinned() -> None:
    plan_routes = [route for route in ROUTES if route.name != "return_reversal"]
    method, not_terminated = "Refund Method is not active", "The Lease is not terminated"
    for route in plan_routes:
        assert {
            message: route.refusals.get(message)
            for message in PLAN_CORRECTION_REFUSALS
            if message not in {method, not_terminated}
        } == {
            message: refusal
            for message, refusal in PLAN_CORRECTION_REFUSALS.items()
            if message not in {method, not_terminated}
        }, route.name
    # The plan rules answer as the Final Settlement draft does, on the same form fields.
    shared = set(FINAL_SETTLEMENT_PLAN_REFUSALS) & set(PLAN_CORRECTION_REFUSALS)
    assert len(shared) == len(FINAL_SETTLEMENT_PLAN_REFUSALS) - 2
    assert all(PLAN_CORRECTION_REFUSALS[m] == FINAL_SETTLEMENT_PLAN_REFUSALS[m] for m in shared)
    # Review round 1: a form that names the Refund method answers on that field; a method named
    # only in a step answers on the steps as the Final Settlement draft does.
    method_answers = {route.name: route.refusals[method] for route in plan_routes}
    assert {name: (refusal.code, refusal.fields) for name, refusal in method_answers.items()} == {
        "refund": ("CORRECTION_REFUND_METHOD_OFF", ("refund_method_id",)),
        "late_charge_refund": ("CORRECTION_REFUND_METHOD_OFF", ("refund_method_id",)),
        "forfeiture_reversal": ("CORRECTION_REFUND_METHOD_OFF", ("refund_method_id",)),
        "refund_return": ("CORRECTION_NEW_REFUND_METHOD_OFF", ("new_refund_method_id",)),
        "held_value_refund": ("CORRECTION_NEW_REFUND_METHOD_OFF", ("new_refund_method_id",)),
        "pet_classification": ("FINAL_SETTLEMENT_REFUND_METHOD_OFF", ("steps",)),
        "deposit_receipt_correction": ("FINAL_SETTLEMENT_REFUND_METHOD_OFF", ("steps",)),
    }
    # A new receipt into a Deposit of no Lease, or of another Lease, names the wrong Deposit.
    for message in ("Lease Deposit was not found", not_terminated):
        assert (
            RECEIPT_CORRECTION_REFUSALS[message].code == "RECEIPT_CORRECTION_DEPOSIT_NOT_OF_LEASE"
        )
    assert "Lease Deposit was not found" not in PLAN_CORRECTION_REFUSALS
    assert "A closed Final Settlement is never reopened or changed" not in PLAN_CORRECTION_REFUSALS
    # The return reversal has no plan; it refuses an open Settlement like every correction.
    assert not shared & set(RETURN_REVERSAL_REFUSALS)
    assert set(CORRECTION_REFUSALS) <= set(RETURN_REVERSAL_REFUSALS)
    for route in ROUTES:
        for refusal in route.refusals.values():
            assert refusal.status_code in {409, 422}
            assert refusal.status_code == 409 or refusal.fields


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_an_answer_for_another_plan_correction_is_never_shown(route: Route) -> None:
    flow = Flow()
    good = flow.result(route.name, flow.prop)
    payload = good["payload"]
    assert isinstance(payload, dict)
    for wrong in (
        {**good, "property_id": str(uuid4())},
        {**good, "kind": "FINAL_SETTLEMENT"},
        {**good, "payload": {**payload, "variant": "EXTRA_CHARGE"}},
        {**good, "payload": {**payload, "final_settlement_id": str(uuid4())}},
        {**good, "payload": {**payload, **{key: str(uuid4()) for key in route.payload}}},
    ):
        flow.answer = wrong
        assert _post(flow, route).status_code == 503, wrong


def test_an_invoice_line_refund_and_a_late_charge_refund_are_told_apart() -> None:
    flow = Flow()
    flow.answer = flow.result("late_charge_refund", flow.prop)
    assert _post(flow, BY_NAME["refund"]).status_code == 503
    flow.answer = flow.result("refund", flow.prop)
    assert _post(flow, BY_NAME["late_charge_refund"]).status_code == 503
