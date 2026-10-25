"""The Final Settlement start, preview and draft routes (V1-056 slice 11e-1; API-070 to API-072)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.app import create_app
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementUnavailableError,
    PetRemainderBasis,
    PetRemainderDecision,
    RecordFinalSettlementDraftCommand,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementDepositStepKind,
    SettlementTargetKind,
)
from property_rental.final_settlement_api import (
    FINAL_SETTLEMENT_CONFIRM_REFUSALS,
    FINAL_SETTLEMENT_DRAFT_REFUSALS,
    FINAL_SETTLEMENT_PLAN_REFUSALS,
    FINAL_SETTLEMENT_STATE_REFUSALS,
)
from property_rental.financial_draft import PREPARE_CAPABILITIES
from property_rental.identity import AuthenticatedActor
from test_invoice import actor, mutation_headers

PREPARE = "final_settlements.prepare"
APPROVE = "financial.approve"
CREDIT, TARGET, DEPOSIT, METHOD, CUSTOMER = (uuid4() for _ in range(5))
STEPS: list[dict[str, object]] = [
    {
        "kind": "CUSTOMER_CREDIT",
        "customer_credit_id": str(CREDIT),
        "target_kind": "INVOICE_LINE",
        "target_id": str(TARGET),
        "amount_usd_cents": 400,
        "customer_designation": "Primary Tenant, 2026-10-24, at the front desk",
    },
    {
        "kind": "PET_DEPOSIT_REMAINDER",
        "deposit_id": str(DEPOSIT),
        "target_kind": "LATE_PAYMENT_CHARGE",
        "target_id": str(TARGET),
        "amount_usd_cents": 2_100,
    },
    {
        "kind": "DEPOSIT_REFUNDS",
        "deposit_id": str(DEPOSIT),
        "amount_usd_cents": 5_400,
        "refund_method_id": str(METHOD),
        "reference_note": "Cash handed over at the front desk",
        "recipient_customer_id": str(CUSTOMER),
    },
]
BODY: dict[str, object] = {
    "steps": STEPS,
    "reason": "Final Settlement prepared from the move-out review",
    "pet_remainder": {"basis": "STAFF_REASON", "staff_reason": "The Customer will not pay"},
}


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("Final Settlement is refused")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    lease: UUID = field(default_factory=uuid4)
    settlement: UUID = field(default_factory=uuid4)
    error: Exception | None = None
    answer: object = None
    calls: list[tuple[str, UUID, object, str]] = field(default_factory=list)

    def _result(self, name: str, prop: UUID, value: object, who: AuthenticatedActor) -> object:
        self.calls.append((name, prop, value, who.actor_id))
        if self.error is not None:
            raise self.error
        return self.answer

    def _settlement(self, prop: UUID) -> dict[str, object]:
        return {
            "id": str(self.settlement),
            "property_id": str(prop),
            "lease_id": str(self.lease),
            "closed": False,
        }

    def start(
        self, property_id: UUID, lease_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        answer = self._result("start", property_id, lease_id, actor)
        return answer if isinstance(answer, dict) else self._settlement(property_id)

    def preview(
        self, property_id: UUID, settlement_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        answer = self._result("preview", property_id, settlement_id, actor)
        if isinstance(answer, dict):
            return answer
        return {"settlement": self._settlement(property_id), "blocking_issues": []}

    def record_draft(
        self,
        property_id: UUID,
        command: RecordFinalSettlementDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        answer = self._result("record_draft", property_id, command, actor)
        if isinstance(answer, dict):
            return answer
        return {
            "draft_id": str(uuid4()),
            "property_id": str(property_id),
            "kind": "FINAL_SETTLEMENT",
            "payload": {
                "variant": "FINAL_SETTLEMENT",
                "final_settlement_id": str(command.settlement_id),
            },
            "state": "PENDING",
        }


def _api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, final_settlement_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def _start(
    flow: Flow,
    who: AuthenticatedActor | None = None,
    *,
    anonymous: bool = False,
    headers: dict[str, str] | None = None,
) -> Response:
    person = None if anonymous else who or actor(flow.prop, PREPARE)
    answer: Response = _api(flow, person).post(
        f"/api/v1/properties/{flow.prop}/leases/{flow.lease}/final-settlement",
        json={},
        headers=headers or mutation_headers(),
    )
    return answer


def _preview(
    flow: Flow, who: AuthenticatedActor | None = None, *, anonymous: bool = False
) -> Response:
    person = None if anonymous else who or actor(flow.prop, PREPARE)
    answer: Response = _api(flow, person).get(
        f"/api/v1/properties/{flow.prop}/final-settlements/{flow.settlement}/preview"
    )
    return answer


def _draft(
    flow: Flow,
    *,
    who: AuthenticatedActor | None = None,
    body: dict[str, object] | None = None,
    key: UUID | None = None,
) -> Response:
    person = who if who is not None else actor(flow.prop, PREPARE)
    answer: Response = _api(flow, person).post(
        f"/api/v1/properties/{flow.prop}/final-settlements/{flow.settlement}/drafts",
        json=BODY if body is None else body,
        headers=mutation_headers(key=key),
    )
    return answer


def test_a_settlement_is_started_for_the_path_lease_by_a_preparer() -> None:
    flow = Flow()
    answer = _start(flow)
    assert answer.status_code == 200, answer.text
    assert answer.headers["Cache-Control"] == "private, no-store"
    assert answer.json()["data"]["id"] == str(flow.settlement)
    [(name, prop, lease, _)] = flow.calls
    assert (name, prop, lease) == ("start", flow.prop, flow.lease)
    # A Settlement this call opened answers 201.
    flow.answer = {**flow._settlement(flow.prop), "created": True}
    assert _start(flow).status_code == 201


def test_the_preview_is_read_by_a_preparer_or_an_approver_only() -> None:
    for capability in (PREPARE, APPROVE):
        flow = Flow()
        answer = _preview(flow, actor(flow.prop, capability))
        assert answer.status_code == 200, answer.text
        assert answer.json()["data"]["settlement"]["id"] == str(flow.settlement)
    flow = Flow()
    assert _preview(flow, actor(flow.prop, "final_settlements.read")).status_code == 404
    assert _preview(flow, actor(uuid4(), PREPARE)).status_code == 404
    assert _preview(flow, anonymous=True).status_code == 401
    assert flow.calls == []


def test_a_settlement_draft_is_recorded_with_its_steps_in_order() -> None:
    flow, key = Flow(), uuid4()
    answer = _draft(flow, key=key)
    assert answer.status_code == 201, answer.text
    assert answer.json()["data"]["kind"] == "FINAL_SETTLEMENT"
    [(name, prop, command, _)] = flow.calls
    assert (name, prop) == ("record_draft", flow.prop)
    assert command == RecordFinalSettlementDraftCommand(
        key,
        flow.settlement,
        (
            SettlementCreditStep(
                CREDIT,
                SettlementTargetKind.INVOICE_LINE,
                TARGET,
                400,
                "Primary Tenant, 2026-10-24, at the front desk",
            ),
            SettlementDepositStep(
                SettlementDepositStepKind.PET_DEPOSIT_REMAINDER,
                DEPOSIT,
                SettlementTargetKind.LATE_PAYMENT_CHARGE,
                TARGET,
                2_100,
            ),
            SettlementDepositRefund(
                DEPOSIT, 5_400, METHOD, "Cash handed over at the front desk", CUSTOMER
            ),
        ),
        "Final Settlement prepared from the move-out review",
        PetRemainderDecision(PetRemainderBasis.STAFF_REASON, "The Customer will not pay"),
    )


def test_the_commands_need_their_capability_sign_in_and_csrf() -> None:
    flow = Flow()
    approver = actor(flow.prop, APPROVE)
    assert _start(flow, approver).status_code == 404
    assert _draft(flow, who=approver).status_code == 404
    assert _draft(flow, who=actor(uuid4(), PREPARE)).status_code == 404
    assert _start(flow, anonymous=True).status_code == 401
    without_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _start(flow, headers=without_csrf).status_code == 403
    # The draft route too, and it needs an Idempotency-Key (review round 1).
    client = _api(flow, actor(flow.prop, PREPARE))
    draft_path = f"/api/v1/properties/{flow.prop}/final-settlements/{flow.settlement}/drafts"
    assert client.post(draft_path, json=BODY, headers=without_csrf).status_code == 403
    without_key = {
        name: value for name, value in mutation_headers().items() if name != "Idempotency-Key"
    }
    assert client.post(draft_path, json=BODY, headers=without_key).status_code == 422
    assert flow.calls == []


def test_the_preview_capabilities_fit_the_database_limit() -> None:
    """Review round 1: app.final_settlement_preview takes at most 10 capabilities; the read
    passes the reader's prepare capabilities and financial.approve."""
    assert len(PREPARE_CAPABILITIES | {APPROVE}) <= 10


@pytest.mark.parametrize(
    "change",
    [
        {"reason": ""},
        {"steps": [{**STEPS[0], "kind": "OTHER"}]},
        {"steps": [{**STEPS[0], "amount_usd_cents": 0}]},
        {"steps": [{**STEPS[0], "amount_usd_cents": "400"}]},
        {"steps": [{**STEPS[1], "target_kind": "INVOICE"}]},
        {"steps": [{**STEPS[2], "reference_note": ""}]},
        {"steps": [{**STEPS[2], "extra": "x"}]},
        {"steps": [STEPS[0]] * 201},
        {"reason": " Untrimmed reason"},
        {"pet_remainder": {"basis": "STAFF_REASON", "staff_reason": " x"}},
        {"amount_usd_cents": 1},
    ],
)
def test_a_bad_draft_form_is_refused_before_any_command(change: dict[str, object]) -> None:
    flow = Flow()
    assert _draft(flow, body={**BODY, **change}).status_code == 422
    assert flow.calls == []


@pytest.mark.parametrize(
    "remainder",
    [
        {"basis": "STAFF_REASON", "staff_reason": "x", "customer_choice": "y"},
        {"basis": "CUSTOMER_CHOICE", "staff_reason": "x"},
    ],
)
def test_a_wrong_pet_remainder_decision_is_refused_on_its_field(
    remainder: dict[str, object],
) -> None:
    """Review round 1: the Customer's choice comes exactly with the CUSTOMER_CHOICE basis."""
    flow = Flow()
    answer = _draft(flow, body={**BODY, "pet_remainder": remainder})
    assert answer.status_code == 422
    assert answer.json()["error"]["fields"] == ["body.pet_remainder"]
    assert flow.calls == []


# The service error each message arrives as (SQLSTATE 22023 is invalid, 55000 a conflict).
INVALID_MESSAGES = frozenset(
    {
        "The Lease is not terminated",
        "The termination record is ambiguous",
        "Final Settlement steps must follow the DL-032 order",
        "A Deposit has at most one Refund in a Final Settlement draft",
        "A Refund to another Signer needs the written agreement of all Signers",
        "The Primary Tenant needs no Signer agreement",
        "The remaining Pet Deposit needs the Customer's choice or the staff reason",
        "A remaining Pet Deposit basis needs a remaining Pet Deposit step",
        "The Final Settlement draft exceeds the stored draft size of 16000 bytes",
    }
)


def _error(message: str) -> type[Exception]:
    if message in INVALID_MESSAGES:
        return FinalSettlementInvalidError
    return FinalSettlementConflictError


@pytest.mark.parametrize("message", list(FINAL_SETTLEMENT_DRAFT_REFUSALS))
def test_each_named_settlement_refusal_answers_its_own_code(message: str) -> None:
    error = _error(message)
    flow = Flow(error=_refused(message, error))
    answer = _draft(flow)
    refusal = FINAL_SETTLEMENT_DRAFT_REFUSALS[message]
    body = answer.json()["error"]
    assert (answer.status_code, body["code"]) == (refusal.status_code, refusal.code)
    assert (body["rule_ids"], body["fields"]) == (list(refusal.rule_ids), list(refusal.fields))
    assert message not in answer.text


@pytest.mark.parametrize("message", list(FINAL_SETTLEMENT_STATE_REFUSALS))
def test_start_and_preview_name_the_lease_and_settlement_state(message: str) -> None:
    code = FINAL_SETTLEMENT_STATE_REFUSALS[message].code
    for call in (_start, _preview):
        flow = Flow(error=_refused(message, _error(message)))
        answer = call(flow)
        assert (answer.status_code, answer.json()["error"]["code"]) == (409, code)
        assert message not in answer.text


def test_the_codes_are_pinned() -> None:
    assert all(value.status_code == 409 for value in FINAL_SETTLEMENT_STATE_REFUSALS.values())
    assert all(
        value.status_code == 422 and value.fields in {("steps",), ("pet_remainder",)}
        for value in FINAL_SETTLEMENT_PLAN_REFUSALS.values()
    )
    # At the shared confirm a plan refusal means the records changed: out of date.
    assert {
        message: value.code
        for message, value in FINAL_SETTLEMENT_CONFIRM_REFUSALS.items()
        if message not in FINAL_SETTLEMENT_STATE_REFUSALS
    } == {message: "DRAFT_OUT_OF_DATE" for message in FINAL_SETTLEMENT_PLAN_REFUSALS}


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (_refused("Lease was not found", FinalSettlementNotFoundError), 404, None),
        (_refused("Final Settlement plan is invalid", FinalSettlementInvalidError), 422, None),
        (FinalSettlementConflictError("conflict"), 409, None),
        (FinalSettlementKeyReused("reused"), 409, "IDEMPOTENCY_KEY_REUSED"),
        (FinalSettlementUnavailableError("unavailable"), 503, None),
    ],
)
def test_unnamed_settlement_refusals_keep_their_plain_answers(
    error: Exception, status: int, code: str | None
) -> None:
    answer = _draft(Flow(error=error))
    assert answer.status_code == status
    if code is not None:
        assert answer.json()["error"]["code"] == code
    assert "Lease was not found" not in answer.text and "is invalid" not in answer.text


def test_an_answer_for_another_property_lease_or_settlement_is_never_shown() -> None:
    flow = Flow()
    for wrong in (
        {"property_id": str(uuid4())},
        {"lease_id": str(uuid4())},
    ):
        flow.answer = {**flow._settlement(flow.prop), **wrong}
        assert _start(flow).status_code == 503
    flow.answer = {"settlement": {**flow._settlement(flow.prop), "id": str(uuid4())}}
    assert _preview(flow).status_code == 503
    for payload, kind in (
        ({"variant": "FINAL_SETTLEMENT", "final_settlement_id": str(uuid4())}, "FINAL_SETTLEMENT"),
        ({"final_settlement_id": str(flow.settlement)}, "FINAL_SETTLEMENT"),
        ({"variant": "FINAL_SETTLEMENT", "final_settlement_id": str(flow.settlement)}, "REFUND"),
    ):
        flow.answer = {"property_id": str(flow.prop), "kind": kind, "payload": payload}
        assert _draft(flow).status_code == 503
    flow.answer = {
        "property_id": str(uuid4()),
        "kind": "FINAL_SETTLEMENT",
        "payload": {"variant": "FINAL_SETTLEMENT", "final_settlement_id": str(flow.settlement)},
    }
    assert _draft(flow).status_code == 503
