"""Record routes for Deposit forfeiture, Deposit correction and returned-Payment drafts
(V1-056 slice 11c-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.app import create_app
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalConflictError,
    DepositReceiptReversalInvalidError,
    DepositReceiptReversalKeyReused,
    RecordDepositReceiptReversalCommand,
)
from property_rental.draft_record_api import (
    FORFEITURE_REFUSALS,
    FORFEITURE_REVERSAL_REFUSALS,
    PAYMENT_RETURN_REFUSALS,
    RECEIPT_REVERSAL_REFUSALS,
    DraftRecordUnavailable,
)
from property_rental.identity import AuthenticatedActor
from property_rental.lease_deposit_forfeiture import (
    LeaseDepositForfeitureAuthorizationError,
    LeaseDepositForfeitureConflictError,
    LeaseDepositForfeitureInvalidError,
    LeaseDepositForfeitureKeyReused,
    LeaseDepositForfeitureNotFoundError,
    LeaseDepositForfeitureUnavailableError,
    RecordLeaseDepositForfeitureCommand,
    RecordLeaseDepositReversalCommand,
)
from property_rental.payment_move import RecordPaymentMoveCommand
from property_rental.payment_return import (
    PaymentReturnConflictError,
    PaymentReturnInvalidError,
    RecordPaymentReturnCommand,
)
from test_invoice import actor, mutation_headers

FORFEIT = "forfeiture"
REVERSE = "forfeiture_reversal"
RECEIPT = "receipt_reversal"
RETURN = "payment_return"
# Slice 11d: the wrong-Unit Payment move (its tests are in test_payment_move_api.py).
MOVE = "payment_move"
CAPABILITY = {
    FORFEIT: "deposits.dispose",
    REVERSE: "deposits.correct",
    RECEIPT: "deposits.correct",
    RETURN: "payments.reverse",
    MOVE: "payments.allocations.reverse",
}
KIND = {
    FORFEIT: ("DEPOSIT_FORFEITURE", "LEASE_FORFEITURE"),
    REVERSE: ("DEPOSIT_FORFEITURE", "LEASE_FORFEITURE_REVERSAL"),
    RECEIPT: ("DEPOSIT_FORFEITURE", "DEPOSIT_RECEIPT_REVERSAL"),
    RETURN: ("PAYMENT_RETURN", None),
    MOVE: ("PAYMENT_MOVE", "WRONG_UNIT_MOVE"),
}
SUBJECT_KEY = {
    FORFEIT: "deposit_id",
    REVERSE: "disposition_id",
    RECEIPT: "receipt_id",
    RETURN: "payment_id",
    MOVE: "source_allocation_id",
}


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    error: Exception | None = None
    answer: dict[str, object] | None = None
    calls: list[tuple[str, UUID, object, str]] = field(default_factory=list)

    def _record(
        self, name: str, property_id: UUID, command: object, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append((name, property_id, command, actor.actor_id))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        kind, variant = KIND[name]
        payload: dict[str, object] = {SUBJECT_KEY[name]: str(SUBJECT)}
        if variant is not None:
            payload["variant"] = variant
        return {
            "draft_id": str(uuid4()),
            "property_id": str(property_id),
            "kind": kind,
            "prepare_capability": CAPABILITY[name],
            "payload": payload,
            "state": "PENDING",
        }

    def forfeiture(
        self,
        property_id: UUID,
        command: RecordLeaseDepositForfeitureCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._record(FORFEIT, property_id, command, actor)

    def forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordLeaseDepositReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._record(REVERSE, property_id, command, actor)

    def receipt_reversal(
        self,
        property_id: UUID,
        command: RecordDepositReceiptReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._record(RECEIPT, property_id, command, actor)

    def payment_return(
        self,
        property_id: UUID,
        command: RecordPaymentReturnCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._record(RETURN, property_id, command, actor)

    def payment_move(
        self,
        property_id: UUID,
        command: RecordPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._record(MOVE, property_id, command, actor)


SUBJECT = uuid4()
BODY: dict[str, dict[str, str]] = {
    FORFEIT: {"disposition_id": str(uuid4()), "reason": "Left before the End Date"},
    REVERSE: {
        "reversal_id": str(uuid4()),
        "reason": "The Lease was ended by mistake",
        "evidence_reference": "Manager note 24/10",
    },
    RECEIPT: {"reversal_id": str(uuid4()), "reason": "The transfer came back"},
    RETURN: {"reason": "The transfer came back", "evidence_reference": "ABA return notice 4471"},
    MOVE: {
        "target_invoice_id": str(uuid4()),
        "reason": "Paid for Unit 204 by mistake",
        "source_acknowledgement": "Sokha, by phone, 24/10",
        "target_acknowledgement": "Dara, in person, 24/10",
    },
}


def _path(flow: Flow, route: str) -> str:
    base = f"/api/v1/properties/{flow.prop}"
    return {
        FORFEIT: f"{base}/deposits/{SUBJECT}/forfeiture-drafts",
        REVERSE: f"{base}/deposit-dispositions/{SUBJECT}/reversal-drafts",
        RECEIPT: f"{base}/deposit-receipts/{SUBJECT}/reversal-drafts",
        RETURN: f"{base}/payments/{SUBJECT}/return-drafts",
        MOVE: f"{base}/payment-allocations/{SUBJECT}/move-drafts",
    }[route]


def _api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, draft_record_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def _post(
    flow: Flow,
    route: str,
    *,
    who: AuthenticatedActor | None = None,
    body: dict[str, str] | None = None,
    key: UUID | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    person = who if who is not None else actor(flow.prop, CAPABILITY[route])
    answer: Response = _api(flow, person).post(
        _path(flow, route),
        json=BODY[route] if body is None else body,
        headers=mutation_headers(key=key) if headers is None else headers,
    )
    return answer


ROUTES = (FORFEIT, REVERSE, RECEIPT, RETURN)


@pytest.mark.parametrize("route", ROUTES)
def test_each_draft_is_recorded_with_its_own_capability_and_command(route: str) -> None:
    flow, key = Flow(), uuid4()
    answer = _post(flow, route, key=key)
    assert answer.status_code == 201, answer.text
    assert answer.headers["Cache-Control"] == "private, no-store"
    data = answer.json()["data"]
    assert (data["kind"], data["payload"].get("variant")) == KIND[route]
    [(name, prop, command, _)] = flow.calls
    assert (name, prop) == (route, flow.prop)
    assert command == _command(route, key)


def _command(route: str, key: UUID) -> object:
    body = BODY[route]
    if route == FORFEIT:
        return RecordLeaseDepositForfeitureCommand(
            key, SUBJECT, UUID(body["disposition_id"]), body["reason"]
        )
    if route == REVERSE:
        return RecordLeaseDepositReversalCommand(
            key, SUBJECT, UUID(body["reversal_id"]), body["reason"], body["evidence_reference"]
        )
    if route == RECEIPT:
        return RecordDepositReceiptReversalCommand(
            key, SUBJECT, UUID(body["reversal_id"]), body["reason"]
        )
    return RecordPaymentReturnCommand(key, SUBJECT, body["reason"], body["evidence_reference"])


@pytest.mark.parametrize("route", ROUTES)
def test_a_draft_is_recorded_only_by_a_signed_in_holder_of_its_capability(route: str) -> None:
    flow = Flow()
    other = {"deposits.dispose", "deposits.correct", "payments.reverse"} - {CAPABILITY[route]}
    assert _post(flow, route, who=actor(flow.prop, *other, "financial.approve")).status_code == 404
    assert _post(flow, route, who=actor(uuid4(), CAPABILITY[route])).status_code == 404
    assert (
        _api(flow, None)
        .post(_path(flow, route), json=BODY[route], headers=mutation_headers())
        .status_code
        == 401
    )
    without_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _post(flow, route, headers=without_csrf).status_code == 403
    assert (
        _post(
            flow, route, headers={**mutation_headers(), "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert flow.calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_a_bad_form_is_refused_before_any_command(route: str) -> None:
    flow = Flow()
    headers = mutation_headers()
    del headers["Idempotency-Key"]
    assert _post(flow, route, headers=headers).status_code == 422
    assert _post(flow, route, body={**BODY[route], "amount_usd_cents": "1"}).status_code == 422
    assert _post(flow, route, body={**BODY[route], "reason": ""}).status_code == 422
    assert _post(flow, route, body={**BODY[route], "reason": "a\x00b"}).status_code == 422
    missing = dict(BODY[route])
    missing.pop(next(key for key in missing if key != "reason"))
    assert _post(flow, route, body=missing).status_code == 422
    assert flow.calls == []


def test_a_reversal_id_equal_to_its_subject_is_bad_input() -> None:
    flow = Flow()
    for route in (REVERSE, RECEIPT):
        body = {**BODY[route], "reversal_id": str(SUBJECT)}
        assert _post(flow, route, body=body).status_code == 422
    assert flow.calls == []


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("Draft command is refused")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


# The service error each route's service raises for the database's SQLSTATE: 22023 invalid,
# 55000 and P5S01 conflict, P5205 a reused key or id.
ERRORS: dict[str, type[Exception]] = {
    FORFEIT: LeaseDepositForfeitureInvalidError,
    REVERSE: LeaseDepositForfeitureConflictError,
    RECEIPT: DepositReceiptReversalKeyReused,
    RETURN: PaymentReturnConflictError,
}
TABLES = {
    FORFEIT: FORFEITURE_REFUSALS,
    REVERSE: FORFEITURE_REVERSAL_REFUSALS,
    RECEIPT: RECEIPT_REVERSAL_REFUSALS,
    RETURN: PAYMENT_RETURN_REFUSALS,
}


@pytest.mark.parametrize(
    ("route", "message"),
    [(route, message) for route, table in TABLES.items() for message in table],
)
def test_each_named_refusal_answers_its_own_code(route: str, message: str) -> None:
    flow = Flow(error=_refused(message, ERRORS[route]))
    answer = _post(flow, route)
    refusal = TABLES[route][message]
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, refusal.code)
    assert answer.json()["error"]["rule_ids"] == list(refusal.rule_ids)
    assert message not in answer.text and message.replace("'", "''") not in answer.text


def test_the_named_codes_are_the_ones_the_screens_expect() -> None:
    """A few codes by name, so a table change that renames one is seen here."""
    assert FORFEITURE_REFUSALS["The Lease is not terminated"].code == (
        "DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED"
    )
    assert FORFEITURE_REFUSALS["Deposit disposition identity was reused"].code == (
        "DRAFT_RECORD_ID_IN_USE"
    )
    assert RECEIPT_REVERSAL_REFUSALS["A draft for this Deposit is already waiting"].code == (
        "DEPOSIT_DRAFT_WAITING"
    )
    assert PAYMENT_RETURN_REFUSALS["Only a received Payment can be returned"].code == (
        "PAYMENT_RETURN_NOT_RECEIVED"
    )
    closed = {
        refusal.code
        for table in TABLES.values()
        for message, refusal in table.items()
        if "closed" in message and "Final Settlement" in message
    }
    assert closed == {
        "FINAL_SETTLEMENT_CLOSED",
        "PAYMENT_RETURN_THROUGH_CORRECTION",
        "PAYMENT_RETURN_SETTLEMENT_NOT_CORRECTABLE",
    }


def test_an_id_reused_by_another_command_is_named_before_the_key_reuse_answer() -> None:
    flow = Flow(
        error=_refused(
            "Deposit receipt reversal identity was reused", DepositReceiptReversalKeyReused
        )
    )
    assert _post(flow, RECEIPT).json()["error"]["code"] == "DRAFT_RECORD_ID_IN_USE"
    flow = Flow(
        error=_refused(
            "Deposit receipt reversal draft identity was reused", DepositReceiptReversalKeyReused
        )
    )
    assert _post(flow, RECEIPT).json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize(
    ("route", "error", "status"),
    [
        (FORFEIT, LeaseDepositForfeitureNotFoundError("Lease Deposit or draft was not found"), 404),
        (FORFEIT, LeaseDepositForfeitureAuthorizationError("not authorized"), 403),
        (FORFEIT, LeaseDepositForfeitureInvalidError("invalid"), 422),
        (REVERSE, LeaseDepositForfeitureConflictError("conflict"), 409),
        (RECEIPT, DepositReceiptReversalConflictError("conflict"), 409),
        (RECEIPT, DepositReceiptReversalInvalidError("invalid"), 422),
        (RETURN, PaymentReturnConflictError("conflict"), 409),
        (RETURN, PaymentReturnInvalidError("invalid"), 422),
        (FORFEIT, LeaseDepositForfeitureUnavailableError("unresolved"), 503),
        (RETURN, DraftRecordUnavailable("Financial drafts are unavailable"), 503),
    ],
)
def test_a_refusal_that_is_not_named_keeps_its_plain_answer(
    route: str, error: Exception, status: int
) -> None:
    answer = _post(Flow(error=error), route)
    assert answer.status_code == status
    assert answer.json()["error"]["code"] != "DRAFT_RECORD_ID_IN_USE"


@pytest.mark.parametrize(
    ("route", "error"),
    [
        (FORFEIT, LeaseDepositForfeitureKeyReused("key reused")),
        (RECEIPT, DepositReceiptReversalKeyReused("key reused")),
    ],
)
def test_a_reused_key_with_other_input_answers_idempotency_key_reused(
    route: str, error: Exception
) -> None:
    answer = _post(Flow(error=error), route)
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


@pytest.mark.parametrize("route", ROUTES)
def test_a_draft_answer_of_another_property_kind_or_record_is_never_shown(route: str) -> None:
    """Review round 1: the exact variant (none for a returned Payment) and the path's record."""
    kind, variant = KIND[route]
    subject = {SUBJECT_KEY[route]: str(SUBJECT)}
    payload = subject if variant is None else {**subject, "variant": variant}
    wrong: list[dict[str, object]] = [
        {"property_id": str(uuid4()), "kind": kind, "payload": payload},
        {"kind": "REFUND", "payload": payload},
        {"kind": kind, "payload": {**subject, "variant": "RESERVATION_OUTCOME"}},
        {"kind": kind, "payload": {**payload, SUBJECT_KEY[route]: str(uuid4())}},
        {"kind": kind, "payload": subject if variant is not None else {**subject, "variant": ""}},
        {"kind": kind, "payload": None},
    ]
    for answer in wrong:
        flow = Flow()
        flow.answer = {"property_id": str(flow.prop), **answer}
        assert _post(flow, route).status_code == 503, answer


def test_a_billing_actor_other_than_the_signed_in_person_is_refused() -> None:
    flow = Flow()
    headers = {**mutation_headers(), "X-Billing-Actor-ID": str(uuid4())}
    for route in ROUTES:
        assert _post(flow, route, headers=headers).status_code == 403
    assert flow.calls == []


def test_a_forfeiture_id_in_use_or_a_closed_settlement_is_named_through_its_own_error() -> None:
    reused = Flow(
        error=_refused("Deposit disposition identity was reused", LeaseDepositForfeitureKeyReused)
    )
    assert _post(reused, FORFEIT).json()["error"]["code"] == "DRAFT_RECORD_ID_IN_USE"
    closed = Flow(
        error=_refused(
            "A closed Final Settlement's Deposit is forfeited only through a post-settlement "
            "correction",
            LeaseDepositForfeitureConflictError,
        )
    )
    answer = _post(closed, FORFEIT)
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, "FINAL_SETTLEMENT_CLOSED")
