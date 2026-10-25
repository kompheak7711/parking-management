"""The post-settlement correction draft routes and the Adjustment reversal draft route (V1-056
slice 11e-2; API-072)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Final
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.adjustment_reversal import (
    AdjustmentReversalConflictError,
    AdjustmentReversalKeyReused,
    AdjustmentReversalNotFoundError,
    RecordAdjustmentReversalCommand,
    RecordSettlementAdjustmentReversalCommand,
)
from property_rental.api_refusals import Refusal
from property_rental.app import create_app
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementUnavailableError,
)
from property_rental.identity import AuthenticatedActor
from property_rental.payment_move import (
    PaymentMoveConflictError,
    RecordSettlementPaymentMoveCommand,
)
from property_rental.settlement_correction import (
    ExtraChargeCategory,
    RecordChargeReductionCorrectionCommand,
    RecordExtraChargeCorrectionCommand,
    RecordLateChargeReductionCorrectionCommand,
    RecordReturnedPaymentCorrectionCommand,
)
from property_rental.settlement_correction_api import (
    ADJUSTMENT_CORRECTION_REFUSALS,
    ADJUSTMENT_REVERSAL_REFUSALS,
    CORRECTION_REFUSALS,
    EXTRA_CHARGE_REFUSALS,
    MOVE_CORRECTION_REFUSALS,
    REDUCTION_REFUSALS,
    RETURNED_PAYMENT_REFUSALS,
)
from test_invoice import actor, mutation_headers

PREPARE = "final_settlements.prepare"
ADJUST = "invoices.adjust"
INVOICE, LINE, CHARGE, PAYMENT, ALLOCATION, TARGET, ADJUSTMENT, FINDING = (
    uuid4() for _ in range(8)
)
REASON = "Found after the move-out review"


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("The correction is refused")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


@dataclass(frozen=True)
class Route:
    """One record route: its path, form, flow call, the variant and payload it answers with,
    its refusal table and the service error family it raises."""

    name: str
    suffix: str
    body: Mapping[str, object]
    variant: str
    payload: Mapping[str, object]
    refusals: Mapping[str, Refusal]
    error: type[Exception]
    capability: str = PREPARE
    kind: str = "SETTLEMENT_CORRECTION"


ROUTES: Final = (
    Route(
        "extra_charge",
        "corrections/extra-charges",
        {
            "category": "DAMAGE_CHARGES",
            "description": "Broken window found after closure",
            "amount_usd_cents": 3_500,
            "evidence_reference": "Photo 12 of the move-out file",
            "reason": REASON,
            "inspection_damage_finding_id": str(FINDING),
            "corrects_invoice_id": str(INVOICE),
            "due_date": "2026-11-05",
            "due_date_reason": "The Customer asked for the 5th",
        },
        "EXTRA_CHARGE",
        {"charge": {"amount_usd_cents": 3_500}},
        EXTRA_CHARGE_REFUSALS,
        FinalSettlementConflictError,
    ),
    Route(
        "charge_reduction",
        "corrections/charge-reductions",
        {
            "invoice_id": str(INVOICE),
            "invoice_line_id": str(LINE),
            "amount_usd_cents": 700,
            "reason": REASON,
        },
        "CHARGE_REDUCTION",
        {"reduction": {"invoice_line_id": str(LINE)}},
        REDUCTION_REFUSALS,
        FinalSettlementConflictError,
    ),
    Route(
        "late_charge_reduction",
        "corrections/late-charge-reductions",
        {"late_payment_charge_id": str(CHARGE), "amount_usd_cents": 200, "reason": REASON},
        "CHARGE_REDUCTION",
        {
            "target_kind": "LATE_PAYMENT_CHARGE",
            "reduction": {"late_payment_charge_id": str(CHARGE)},
        },
        REDUCTION_REFUSALS,
        FinalSettlementConflictError,
    ),
    Route(
        "returned_payment",
        "corrections/returned-payments",
        {
            "payment_id": str(PAYMENT),
            "reason": "The bank returned the transfer",
            "evidence_reference": "Bank notice 2026-10-20",
        },
        "RETURNED_PAYMENT",
        {"payment_id": str(PAYMENT)},
        RETURNED_PAYMENT_REFUSALS,
        FinalSettlementConflictError,
    ),
    Route(
        "payment_move",
        "corrections/payment-moves",
        {
            "allocation_id": str(ALLOCATION),
            "target_invoice_id": str(TARGET),
            "reason": "The money was for Unit 205",
            "source_acknowledgement": "The Unit 204 Customer agreed on 2026-10-24",
            "target_acknowledgement": "The Unit 205 Customer agreed on 2026-10-24",
        },
        "PAYMENT_MOVE",
        {"source_allocation_id": str(ALLOCATION)},
        MOVE_CORRECTION_REFUSALS,
        PaymentMoveConflictError,
    ),
    Route(
        "adjustment_reversal_correction",
        "corrections/adjustment-reversals",
        {"adjustment_id": str(ADJUSTMENT), "reason": "The reduction was recorded by mistake"},
        "ADJUSTMENT_REVERSAL",
        {"invoice_adjustment_id": str(ADJUSTMENT)},
        ADJUSTMENT_CORRECTION_REFUSALS,
        AdjustmentReversalConflictError,
    ),
    Route(
        "adjustment_reversal",
        "",
        {"reason": "The reduction was recorded by mistake"},
        "",
        {"invoice_adjustment_id": str(ADJUSTMENT)},
        ADJUSTMENT_REVERSAL_REFUSALS,
        AdjustmentReversalConflictError,
        ADJUST,
        "ADJUSTMENT_REVERSAL",
    ),
)
BY_NAME: Final = {route.name: route for route in ROUTES}


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    settlement: UUID = field(default_factory=uuid4)
    error: Exception | None = None
    answer: object = None
    calls: list[tuple[str, UUID, object, str]] = field(default_factory=list)

    def _result(self, name: str, prop: UUID, command: object, who: AuthenticatedActor) -> object:
        self.calls.append((name, prop, command, who.actor_id))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        route = BY_NAME[name]
        payload: dict[str, object] = {**route.payload}
        if route.kind == "SETTLEMENT_CORRECTION":
            payload |= {"variant": route.variant, "final_settlement_id": str(self.settlement)}
        return {
            "draft_id": str(uuid4()),
            "property_id": str(prop),
            "kind": route.kind,
            "payload": payload,
            "state": "PENDING",
        }

    def extra_charge(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("extra_charge", property_id, command, actor)

    def charge_reduction(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("charge_reduction", property_id, command, actor)

    def late_charge_reduction(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("late_charge_reduction", property_id, command, actor)

    def returned_payment(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("returned_payment", property_id, command, actor)

    def payment_move(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("payment_move", property_id, command, actor)

    def adjustment_reversal_correction(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("adjustment_reversal_correction", property_id, command, actor)

    def adjustment_reversal(
        self, property_id: UUID, command: object, *, actor: AuthenticatedActor
    ) -> object:
        return self._result("adjustment_reversal", property_id, command, actor)


def _path(flow: Flow, route: Route) -> str:
    if route.name == "adjustment_reversal":
        return f"/api/v1/properties/{flow.prop}/invoice-adjustments/{ADJUSTMENT}/reversal-drafts"
    return f"/api/v1/properties/{flow.prop}/final-settlements/{flow.settlement}/{route.suffix}"


def _post(
    flow: Flow,
    route: Route,
    *,
    who: AuthenticatedActor | None = None,
    anonymous: bool = False,
    body: Mapping[str, object] | None = None,
    key: UUID | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    person = None if anonymous else who or actor(flow.prop, route.capability)
    client = TestClient(
        create_app(actor_resolver=lambda _: person, settlement_correction_flow=flow)  # type: ignore[arg-type]
    )
    client.cookies.set("__Host-prm_csrf", "csrf")
    answer: Response = client.post(
        _path(flow, route),
        json=dict(route.body if body is None else body),
        headers=headers or mutation_headers(key=key),
    )
    return answer


def _commands(flow: Flow, key: UUID) -> dict[str, object]:
    settlement = flow.settlement
    return {
        "extra_charge": RecordExtraChargeCorrectionCommand(
            key,
            settlement,
            ExtraChargeCategory.DAMAGE_CHARGES,
            "Broken window found after closure",
            3_500,
            "Photo 12 of the move-out file",
            REASON,
            FINDING,
            INVOICE,
            date(2026, 11, 5),
            "The Customer asked for the 5th",
        ),
        "charge_reduction": RecordChargeReductionCorrectionCommand(
            key, settlement, INVOICE, LINE, 700, REASON
        ),
        "late_charge_reduction": RecordLateChargeReductionCorrectionCommand(
            key, settlement, CHARGE, 200, REASON
        ),
        "returned_payment": RecordReturnedPaymentCorrectionCommand(
            key,
            settlement,
            PAYMENT,
            "The bank returned the transfer",
            "Bank notice 2026-10-20",
        ),
        "payment_move": RecordSettlementPaymentMoveCommand(
            key,
            settlement,
            ALLOCATION,
            TARGET,
            "The money was for Unit 205",
            "The Unit 204 Customer agreed on 2026-10-24",
            "The Unit 205 Customer agreed on 2026-10-24",
        ),
        "adjustment_reversal_correction": RecordSettlementAdjustmentReversalCommand(
            key, settlement, ADJUSTMENT, "The reduction was recorded by mistake"
        ),
        "adjustment_reversal": RecordAdjustmentReversalCommand(
            key, ADJUSTMENT, "The reduction was recorded by mistake"
        ),
    }


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_each_correction_draft_is_recorded_from_its_form(route: Route) -> None:
    flow, key = Flow(), uuid4()
    answer = _post(flow, route, key=key)
    assert answer.status_code == 201, answer.text
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["kind"] == route.kind
    [(name, prop, command, _)] = flow.calls
    assert (name, prop, command) == (route.name, flow.prop, _commands(flow, key)[route.name])


def test_a_miscellaneous_charge_needs_no_finding_or_due_date() -> None:
    route = BY_NAME["extra_charge"]
    flow = Flow()
    body = {
        key: value
        for key, value in route.body.items()
        if key not in {"inspection_damage_finding_id", "due_date", "due_date_reason"}
    }
    answer = _post(flow, route, body={**body, "category": "MISCELLANEOUS_CHARGES"})
    assert answer.status_code == 201, answer.text
    [(_, _, command, _)] = flow.calls
    assert isinstance(command, RecordExtraChargeCorrectionCommand)
    assert command.category is ExtraChargeCategory.MISCELLANEOUS_CHARGES
    assert (command.inspection_damage_finding_id, command.due_date) == (None, None)


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_each_route_needs_its_capability_sign_in_csrf_and_key(route: Route) -> None:
    flow = Flow()
    other = PREPARE if route.capability == ADJUST else ADJUST
    assert _post(flow, route, who=actor(flow.prop, other)).status_code == 404
    assert _post(flow, route, who=actor(flow.prop, "financial.approve")).status_code == 404
    assert _post(flow, route, who=actor(uuid4(), route.capability)).status_code == 404
    assert _post(flow, route, anonymous=True).status_code == 401
    without_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _post(flow, route, headers=without_csrf).status_code == 403
    without_key = {
        name: value for name, value in mutation_headers().items() if name != "Idempotency-Key"
    }
    assert _post(flow, route, headers=without_key).status_code == 422
    assert flow.calls == []


@pytest.mark.parametrize(
    ("name", "change", "fields"),
    [
        ("extra_charge", {"category": "RENT"}, ["body.category"]),
        ("extra_charge", {"amount_usd_cents": 0}, ["body.amount_usd_cents"]),
        ("extra_charge", {"amount_usd_cents": "3500"}, ["body.amount_usd_cents"]),
        ("extra_charge", {"reason": "x" * 501}, ["body.reason"]),
        ("extra_charge", {"description": ""}, ["body.description"]),
        ("extra_charge", {"due_date": "05/11/2026"}, ["body.due_date"]),
        ("charge_reduction", {"invoice_line_id": "line"}, ["body.invoice_line_id"]),
        ("charge_reduction", {"extra": "x"}, ["body.extra"]),
        ("late_charge_reduction", {"amount_usd_cents": -1}, ["body.amount_usd_cents"]),
        ("returned_payment", {"evidence_reference": " x"}, ["body.evidence_reference"]),
        ("payment_move", {"source_acknowledgement": ""}, ["body.source_acknowledgement"]),
        ("adjustment_reversal_correction", {"reason": " untrimmed"}, ["body.reason"]),
        ("adjustment_reversal", {"adjustment_id": str(ADJUSTMENT)}, ["body.adjustment_id"]),
    ],
)
def test_a_bad_form_is_refused_on_its_field_before_any_command(
    name: str, change: dict[str, object], fields: list[str]
) -> None:
    flow, route = Flow(), BY_NAME[name]
    answer = _post(flow, route, body={**route.body, **change})
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"]["fields"] == fields
    assert flow.calls == []


@pytest.mark.parametrize(
    ("change", "drop", "field"),
    [
        ({}, "due_date_reason", "body.due_date_reason"),
        ({"due_date_reason": "Asked by the Customer"}, "due_date", "body.due_date_reason"),
        ({}, "inspection_damage_finding_id", "body.inspection_damage_finding_id"),
        ({"category": "MISCELLANEOUS_CHARGES"}, None, "body.inspection_damage_finding_id"),
    ],
)
def test_a_cross_field_mistake_is_refused_on_its_field(
    change: dict[str, object], drop: str | None, field: str
) -> None:
    """Review round 1: a Damage charge names its finding and a Miscellaneous charge none; the Due
    Date override and its reason come together."""
    flow, route = Flow(), BY_NAME["extra_charge"]
    body = {key: value for key, value in route.body.items() if key != drop}
    answer = _post(flow, route, body={**body, **change})
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"]["fields"] == [field]
    assert flow.calls == []


NAMED: Final = [(route.name, message) for route in ROUTES for message in route.refusals]


@pytest.mark.parametrize(("name", "message"), NAMED)
def test_each_named_correction_refusal_answers_its_own_code(name: str, message: str) -> None:
    route = BY_NAME[name]
    flow = Flow(error=_refused(message, route.error))
    answer = _post(flow, route)
    refusal = route.refusals[message]
    body = answer.json()["error"]
    assert (answer.status_code, body["code"]) == (refusal.status_code, refusal.code)
    assert (body["rule_ids"], body["fields"]) == (list(refusal.rule_ids), list(refusal.fields))
    # Only the refusal's own words are shown, never the database text.
    assert body["message"] == refusal.message


def test_the_correction_codes_are_pinned() -> None:
    # Every correction route names the closed-Settlement refusal with the same answer.
    for route in ROUTES[:-1]:
        assert {message: route.refusals.get(message) for message in CORRECTION_REFUSALS} == dict(
            CORRECTION_REFUSALS
        ), route.name
    # The plain draft is recorded before closure: it never answers the closed-Settlement codes.
    assert not set(CORRECTION_REFUSALS) & set(ADJUSTMENT_REVERSAL_REFUSALS)
    for route in ROUTES:
        for refusal in route.refusals.values():
            assert refusal.status_code in {409, 422}
            # A 422 names the fields of the form that chose the wrong record or text.
            assert refusal.status_code == 409 or refusal.fields
    # A body-chosen Adjustment that is unknown is 422 on its field; in the path it stays 404.
    unknown = "Invoice Adjustment was not found"
    assert ADJUSTMENT_CORRECTION_REFUSALS[unknown].fields == ("adjustment_id",)
    assert unknown not in ADJUSTMENT_REVERSAL_REFUSALS


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (_refused("Adjustment row missing", AdjustmentReversalNotFoundError), 404, None),
        (_refused("Correction text malformed", FinalSettlementInvalidError), 422, None),
        (FinalSettlementConflictError("conflict"), 409, None),
        (AdjustmentReversalKeyReused("reused"), 409, "IDEMPOTENCY_KEY_REUSED"),
        (FinalSettlementUnavailableError("unavailable"), 503, None),
    ],
)
def test_unnamed_correction_refusals_keep_their_plain_answers(
    error: Exception, status: int, code: str | None
) -> None:
    for route in (BY_NAME["extra_charge"], BY_NAME["adjustment_reversal"]):
        answer = _post(Flow(error=error), route)
        assert answer.status_code == status
        if code is not None:
            assert answer.json()["error"]["code"] == code
        assert "row missing" not in answer.text and "malformed" not in answer.text


def test_no_financial_database_answers_503() -> None:
    """Without the financial database the real flow is unavailable, not a crash."""
    route = BY_NAME["charge_reduction"]
    prop = uuid4()
    person = actor(prop, PREPARE)
    client = TestClient(create_app(actor_resolver=lambda _: person))
    client.cookies.set("__Host-prm_csrf", "csrf")
    answer = client.post(
        f"/api/v1/properties/{prop}/final-settlements/{uuid4()}/{route.suffix}",
        json=dict(route.body),
        headers=mutation_headers(),
    )
    assert answer.status_code == 503


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: route.name)
def test_an_answer_for_another_record_is_never_shown(route: Route) -> None:
    flow = Flow()
    good = flow._result(route.name, flow.prop, None, actor(flow.prop))
    flow.calls.clear()
    assert isinstance(good, dict)
    payload = good["payload"]
    assert isinstance(payload, dict)
    wrong: list[dict[str, object]] = [
        {**good, "property_id": str(uuid4())},
        {**good, "kind": "REFUND"},
        {**good, "payload": "not an object"},
        {**good, "payload": {**payload, **{key: str(uuid4()) for key in route.payload}}},
    ]
    if route.kind == "SETTLEMENT_CORRECTION":
        wrong += [
            {**good, "payload": {**payload, "variant": "REFUND"}},
            {**good, "payload": {**payload, "final_settlement_id": str(uuid4())}},
        ]
    for answer in wrong:
        flow.answer = answer
        assert _post(flow, route).status_code == 503, answer


def test_an_invoice_reduction_and_a_late_charge_reduction_are_told_apart() -> None:
    """Both record the CHARGE_REDUCTION variant; only the late one carries its target kind."""
    flow = Flow()
    invoice, late = BY_NAME["charge_reduction"], BY_NAME["late_charge_reduction"]
    late_answer = flow._result(late.name, flow.prop, None, actor(flow.prop))
    flow.answer = late_answer
    assert _post(flow, invoice).status_code == 503
    invoice_answer = Flow(prop=flow.prop, settlement=flow.settlement)._result(
        invoice.name, flow.prop, None, actor(flow.prop)
    )
    flow.answer = invoice_answer
    assert _post(flow, late).status_code == 503
