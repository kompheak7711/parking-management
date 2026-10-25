"""The wrong-Unit Payment move draft route (V1-056 slice 11d; BR-PAY-042)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.allocation_receipt_api import ALLOCATION_REVERSAL_REFUSALS
from property_rental.draft_record_api import (
    PAYMENT_MOVE_CONFIRM_REFUSALS,
    PAYMENT_MOVE_REFUSALS,
)
from property_rental.payment_allocation import (
    AllocationConflictError,
    AllocationIdempotencyKeyReused,
)
from property_rental.payment_move import (
    PaymentMoveConflictError,
    PaymentMoveInvalidError,
    PaymentMoveKeyReused,
    PaymentMoveNotFoundError,
    RecordPaymentMoveCommand,
)
from test_allocation_receipt_api import Flow as AllocationFlow
from test_allocation_receipt_api import api as allocation_api
from test_draft_record_api import BODY, CAPABILITY, MOVE, SUBJECT, Flow, _api, _path, _post
from test_invoice import actor, mutation_headers


class _DatabaseRefusal(psycopg.Error):
    """A database error whose primary message the route reads (no server needed)."""

    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _refused(message: str, error: type[Exception]) -> Exception:
    mapped = error("Payment move is refused")
    mapped.__cause__ = _DatabaseRefusal(message)
    return mapped


# The service error each SQLSTATE becomes (payment_move.py): 22023 invalid, P0002 not found,
# 55000 and 23514 conflict.
ERRORS: dict[str, type[Exception]] = {
    "Only an Invoice allocation can move": PaymentMoveInvalidError,
    "The correct Invoice must belong to a Lease of another Unit": PaymentMoveInvalidError,
    "Invoice was not found": PaymentMoveNotFoundError,
    "The move draft exceeds the stored draft size of 16000 bytes (acknowledgements and the "
    "line split of the correct Invoice)": PaymentMoveInvalidError,
}


def test_a_move_draft_is_recorded_with_its_capability_and_command() -> None:
    flow, key = Flow(), uuid4()
    answer = _post(flow, MOVE, key=key)
    assert answer.status_code == 201, answer.text
    data = answer.json()["data"]
    assert (data["kind"], data["payload"]["variant"]) == ("PAYMENT_MOVE", "WRONG_UNIT_MOVE")
    [(name, prop, command, _)] = flow.calls
    body = BODY[MOVE]
    assert (name, prop) == (MOVE, flow.prop)
    assert command == RecordPaymentMoveCommand(
        key,
        SUBJECT,
        UUID(body["target_invoice_id"]),
        body["reason"],
        body["source_acknowledgement"],
        body["target_acknowledgement"],
    )


def test_a_move_draft_needs_its_capability_sign_in_and_csrf() -> None:
    flow = Flow()
    others = ("payments.reverse", "payments.allocate", "financial.approve")
    assert _post(flow, MOVE, who=actor(flow.prop, *others)).status_code == 404
    assert _post(flow, MOVE, who=actor(uuid4(), CAPABILITY[MOVE])).status_code == 404
    assert (
        _api(flow, None)
        .post(_path(flow, MOVE), json=BODY[MOVE], headers=mutation_headers())
        .status_code
        == 401
    )
    without_csrf = {"Origin": "https://localhost", "Idempotency-Key": str(uuid4())}
    assert _post(flow, MOVE, headers=without_csrf).status_code == 403
    assert flow.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"reason": ""},
        {"source_acknowledgement": ""},
        {"target_acknowledgement": "x" * 2001},
        {"target_invoice_id": "not-an-id"},
        {"amount_usd_cents": "1"},
    ],
)
def test_a_bad_move_form_is_refused_before_any_command(change: dict[str, str]) -> None:
    flow = Flow()
    assert _post(flow, MOVE, body={**BODY[MOVE], **change}).status_code == 422
    missing = {key: value for key, value in BODY[MOVE].items() if key != "target_invoice_id"}
    assert _post(flow, MOVE, body=missing).status_code == 422
    assert flow.calls == []


@pytest.mark.parametrize("message", list(PAYMENT_MOVE_REFUSALS))
def test_each_named_move_refusal_answers_its_own_code(message: str) -> None:
    flow = Flow(error=_refused(message, ERRORS.get(message, PaymentMoveConflictError)))
    answer = _post(flow, MOVE)
    refusal = PAYMENT_MOVE_REFUSALS[message]
    error = answer.json()["error"]
    assert (answer.status_code, error["code"]) == (refusal.status_code, refusal.code)
    assert (error["rule_ids"], error["fields"]) == (list(refusal.rule_ids), list(refusal.fields))
    assert message not in answer.text


def test_the_move_codes_are_pinned() -> None:
    assert {
        message: (value.status_code, value.code, value.fields)
        for message, value in PAYMENT_MOVE_REFUSALS.items()
        if value.status_code == 422
    } == {
        "Invoice was not found": (
            422,
            "PAYMENT_MOVE_TARGET_NOT_FOUND",
            ("target_invoice_id",),
        ),
        "The correct Invoice must belong to a Lease of another Unit": (
            422,
            "PAYMENT_MOVE_TARGET_SAME_UNIT",
            ("target_invoice_id",),
        ),
        "The correct Invoice has nothing outstanding": (
            422,
            "PAYMENT_MOVE_TARGET_NOTHING_OWED",
            ("target_invoice_id",),
        ),
        "The move draft exceeds the stored draft size of 16000 bytes (acknowledgements and the "
        "line split of the correct Invoice)": (
            422,
            "PAYMENT_MOVE_TOO_LARGE",
            ("source_acknowledgement", "target_acknowledgement"),
        ),
    }
    assert {value.code for value in PAYMENT_MOVE_CONFIRM_REFUSALS.values()} == {
        "PAYMENT_MOVE_NOT_INVOICE_ALLOCATION",
        "PAYMENT_MOVE_PAYMENT_REVERSED",
        "PAYMENT_MOVE_ALREADY_MOVED",
        "PAYMENT_MOVE_RELEASED_BY_ADJUSTMENT",
        "PAYMENT_MOVE_CREDIT_OR_REFUND_FIRST",
        "PAYMENT_MOVE_VALUE_GONE",
        "PAYMENT_MOVE_TARGET_TOO_LARGE",
        "PAYMENT_MOVE_THROUGH_CORRECTION",
        "DRAFT_OUT_OF_DATE",
    }
    assert {value.code for value in ALLOCATION_REVERSAL_REFUSALS.values()} == {
        "ALLOCATION_MOVED",
        "FINAL_SETTLEMENT_CLOSED",
    }


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (_refused("Payment move draft input is invalid", PaymentMoveInvalidError), 422),
        (_refused("Payment allocation was not found", PaymentMoveNotFoundError), 404),
        (PaymentMoveConflictError("Payment move conflicts with the current state"), 409),
    ],
)
def test_unnamed_move_refusals_keep_their_plain_answers(error: Exception, status: int) -> None:
    answer = _post(Flow(error=error), MOVE)
    assert answer.status_code == status
    assert "invalid" not in answer.text and "allocation was not found" not in answer.text


def test_a_reused_move_key_answers_idempotency_key_reused() -> None:
    flow = Flow(error=_refused("Payment move draft identity was reused", PaymentMoveKeyReused))
    answer = _post(flow, MOVE)
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")


def test_a_move_answer_for_another_allocation_or_kind_is_never_shown() -> None:
    for payload in (
        {"variant": "WRONG_UNIT_MOVE", "source_allocation_id": str(uuid4())},
        {"source_allocation_id": str(SUBJECT)},
        {"variant": "PAYMENT_MOVE", "source_allocation_id": str(SUBJECT)},
    ):
        flow = Flow()
        flow.answer = {
            "draft_id": str(uuid4()),
            "property_id": str(flow.prop),
            "kind": "PAYMENT_MOVE",
            "payload": payload,
            "state": "PENDING",
        }
        assert _post(flow, MOVE).status_code == 503
    # Another Property or another kind (review round 1).
    right = {"variant": "WRONG_UNIT_MOVE", "source_allocation_id": str(SUBJECT)}
    for prop_of, kind in ((lambda _: str(uuid4()), "PAYMENT_MOVE"), (str, "SETTLEMENT_CORRECTION")):
        flow = Flow()
        flow.answer = {
            "draft_id": str(uuid4()),
            "property_id": prop_of(flow.prop),
            "kind": kind,
            "payload": right,
            "state": "PENDING",
        }
        assert _post(flow, MOVE).status_code == 503
    # The same answer with the path's Property and kind is shown.
    shown = Flow()
    shown.answer = {
        "draft_id": str(uuid4()),
        "property_id": str(shown.prop),
        "kind": "PAYMENT_MOVE",
        "payload": right,
        "state": "PENDING",
    }
    assert _post(shown, MOVE).status_code == 201


def _reverse(error: Exception) -> tuple[int, str | None]:
    flow = AllocationFlow(error=error)
    who = actor(flow.prop, "payments.allocations.reverse")
    answer = allocation_api(flow, who).post(
        f"/api/v1/payment-allocations/{flow.allocation}/reverse",
        json={"reason": "Correct target"},
        headers={**mutation_headers(), "X-Billing-Actor-ID": who.actor_id},
    )
    body = answer.json()
    assert "changes only through" not in answer.text
    return answer.status_code, body.get("error", {}).get("code")


def test_the_one_call_reversal_names_a_moved_or_relied_on_allocation() -> None:
    """Review round 1: the one-call reversal route answers its two named refusals over HTTP."""
    for message, refusal in ALLOCATION_REVERSAL_REFUSALS.items():
        error = AllocationConflictError("Allocation reversal conflicts")
        error.__cause__ = _DatabaseRefusal(message)
        assert _reverse(error) == (409, refusal.code)
    # An unnamed conflict keeps its plain 409; a reused key still answers its own code.
    unnamed = AllocationConflictError("Allocation reversal conflicts")
    unnamed.__cause__ = _DatabaseRefusal("Payment allocation changed meanwhile")
    status, code = _reverse(unnamed)
    assert status == 409 and code not in {"ALLOCATION_MOVED", "FINAL_SETTLEMENT_CLOSED"}
    assert _reverse(AllocationIdempotencyKeyReused("reused")) == (409, "IDEMPOTENCY_KEY_REUSED")
