"""Shared financial draft routes: list, detail, reject, withdraw and confirm (V1-056 slice 11b)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.deposit_receipt_reversal import DepositReceiptReversalInvalidError
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementStaleDraftError,
)
from property_rental.financial_draft import (
    FinancialDraftAuthorizationError,
    FinancialDraftConflictError,
    FinancialDraftDecidedError,
    FinancialDraftNotFoundError,
    FinancialDraftNotPreparerError,
    FinancialDraftPage,
    FinancialDraftState,
    FinancialDraftUnavailableError,
)
from property_rental.financial_draft_confirm import DraftConfirmNotAvailable, DraftPayloadInvalid
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureConflictError
from property_rental.payment_move import PaymentMoveConflictError
from property_rental.payment_return import PaymentReturnConflictError, PaymentReturnStaleDraftError
from property_rental.refund import (
    RefundAuthorizationError,
    RefundConflictError,
    RefundInvalidError,
    RefundNotFoundError,
    RefundUnavailableError,
)
from test_invoice import actor, mutation_headers

APPROVE = "financial.approve"
REASON = {"reason": "The amount was typed wrong"}


@dataclass
class Flow:
    prop: UUID = field(default_factory=uuid4)
    draft: UUID = field(default_factory=uuid4)
    prepared_by: str = field(default_factory=lambda: str(uuid4()))
    prepare_capability: str = "refunds.create"
    variant: str = "USD"
    kind: str = "REFUND"
    other_property: bool = False
    error: Exception | None = None
    get_error: Exception | None = None
    state: str = "PENDING"
    decided_by: str | None = None
    states_after_confirm_error: str | None = None
    items: int = 1
    calls: list[tuple[str, object]] = field(default_factory=list)

    def resource(self, identity: UUID | None = None, state: str = "PENDING") -> dict[str, object]:
        return {
            "draft_id": str(identity or self.draft),
            "property_id": str(uuid4() if self.other_property else self.prop),
            "kind": self.kind,
            "prepare_capability": self.prepare_capability,
            "payload": {"variant": self.variant, "customer_id": str(uuid4())},
            "reason": "Customer asked for the rest",
            "prepared_at": "2026-10-24T10:00:00.123456+00:00",
            "prepared_by": self.prepared_by,
            "state": state,
            "decision": None if self.decided_by is None else {"decided_by": self.decided_by},
        }

    def _answer(self, name: str, value: object, answer: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error
        return answer

    def get(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self.calls.append(("get", (property_id, draft_id)))
        if self.get_error is not None:
            raise self.get_error
        return self.resource(draft_id, self.state)

    def list(
        self, property_id: UUID, *, actor: AuthenticatedActor, page: FinancialDraftPage
    ) -> dict[str, object]:
        return self._answer(
            "list", (property_id, page), {"items": [self.resource(uuid4())] * self.items}
        )

    def reject(
        self, property_id: UUID, draft_id: UUID, reason: str, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return self._answer(
            "reject", (property_id, draft_id, reason), self.resource(draft_id, "REJECTED")
        )

    def confirm(
        self, property_id: UUID, draft: dict[str, object], *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        try:
            return self._answer(
                "confirm",
                (property_id, draft["draft_id"]),
                {"refund": {"id": "r-1", "transaction_id": "4471"}, "transaction_id": "4471"},
            )
        except Exception:
            # Someone else decided the draft between the route's read and this command.
            if self.states_after_confirm_error is not None:
                self.state = self.states_after_confirm_error
            raise

    def withdraw(
        self,
        property_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        prepare_capability: str,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return self._answer(
            "withdraw",
            (property_id, draft_id, reason, prepare_capability),
            self.resource(draft_id, "WITHDRAWN"),
        )


def api(flow: Flow, who: AuthenticatedActor | None) -> TestClient:
    client = TestClient(create_app(actor_resolver=lambda _: who, financial_draft_flow=flow))
    client.cookies.set("__Host-prm_csrf", "csrf")
    return client


def path(flow: Flow, action: str = "") -> str:
    base = f"/api/v1/properties/{flow.prop}/financial-drafts/{flow.draft}"
    return f"{base}/{action}" if action else base


def preparer(flow: Flow) -> AuthenticatedActor:
    who = actor(flow.prop, flow.prepare_capability)
    flow.prepared_by = who.actor_id
    return who


def test_a_reader_lists_drafts_with_a_cursor_bound_to_the_property_and_state() -> None:
    flow = Flow(items=2)
    client = api(flow, actor(flow.prop, "refunds.create"))

    first = client.get(
        f"/api/v1/properties/{flow.prop}/financial-drafts", params={"state": "PENDING", "limit": 2}
    )

    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, no-store"
    body = first.json()
    assert len(body["data"]) == 2 and body["meta"]["property_id"] == str(flow.prop)
    cursor = body["page"]["next_cursor"]
    assert body["page"]["limit"] == 2 and isinstance(cursor, str)
    page = flow.calls[-1][1][1]  # type: ignore[index]
    assert isinstance(page, FinancialDraftPage)
    assert page.state is FinancialDraftState.PENDING and page.after_id is None

    following = client.get(
        f"/api/v1/properties/{flow.prop}/financial-drafts",
        params={"state": "PENDING", "limit": 2, "cursor": cursor},
    )
    assert following.status_code == 200
    page = flow.calls[-1][1][1]  # type: ignore[index]
    assert page.after_id is not None and page.after_prepared_at is not None
    # A cursor made for another state filter or another Property is refused.
    other_state = client.get(
        f"/api/v1/properties/{flow.prop}/financial-drafts",
        params={"state": "CONFIRMED", "limit": 2, "cursor": cursor},
    )
    assert other_state.status_code == 400
    flow.items = 1
    last = client.get(f"/api/v1/properties/{flow.prop}/financial-drafts", params={"limit": 2})
    assert last.json()["page"]["next_cursor"] is None
    assert (
        client.get(
            f"/api/v1/properties/{flow.prop}/financial-drafts", params={"other": "1"}
        ).status_code
        == 400
    )
    # A cursor of this Property is refused on another Property the person can also read.
    elsewhere = uuid4()
    both = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {CapabilityGrant("refunds.create", frozenset({str(flow.prop), str(elsewhere)}))}
        ),
    )
    assert (
        api(flow, both)
        .get(
            f"/api/v1/properties/{elsewhere}/financial-drafts",
            params={"state": "PENDING", "limit": 2, "cursor": cursor},
        )
        .status_code
        == 400
    )


def test_drafts_are_hidden_without_a_draft_capability_and_need_sign_in() -> None:
    flow = Flow()
    hidden = api(flow, actor(flow.prop, "payments.read"))

    assert hidden.get(f"/api/v1/properties/{flow.prop}/financial-drafts").status_code == 404
    assert hidden.get(path(flow)).status_code == 404
    assert api(flow, None).get(path(flow)).status_code == 401
    assert flow.calls == []


def test_the_detail_answers_one_draft_and_maps_not_found_and_outage() -> None:
    flow = Flow()
    client = api(flow, actor(flow.prop, APPROVE))

    found = client.get(path(flow))
    assert found.status_code == 200 and found.json()["data"]["draft_id"] == str(flow.draft)

    flow.get_error = FinancialDraftNotFoundError()
    assert client.get(path(flow)).status_code == 404
    flow.get_error = FinancialDraftUnavailableError()
    assert client.get(path(flow)).status_code == 503


def test_only_financial_approve_rejects_and_a_decided_draft_says_so() -> None:
    flow = Flow()
    staff = api(flow, actor(flow.prop, "refunds.create"))
    approver = api(flow, actor(flow.prop, APPROVE))

    refused = staff.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert refused.status_code == 404
    assert flow.calls == []

    rejected = approver.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert rejected.status_code == 200
    assert rejected.json()["data"]["state"] == "REJECTED"
    assert flow.calls[-1] == ("reject", (flow.prop, flow.draft, REASON["reason"]))

    flow.error = FinancialDraftDecidedError("Financial draft is already decided")
    decided = approver.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert decided.status_code == 409
    assert decided.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"
    assert decided.json()["error"]["message"] == (
        "This draft was already confirmed, rejected or withdrawn."
    )
    flow.error = FinancialDraftConflictError("rule")
    conflict = approver.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert conflict.json()["error"]["code"] == "DRAFT_DECISION_NOT_ALLOWED"


def test_reject_needs_csrf_origin_idempotency_key_and_a_trimmed_reason() -> None:
    flow = Flow()
    approver = api(flow, actor(flow.prop, APPROVE))
    headers = mutation_headers()

    no_csrf = {key: value for key, value in headers.items() if key != "X-CSRF-Token"}
    no_key = {key: value for key, value in headers.items() if key != "Idempotency-Key"}
    other_origin = {**headers, "Origin": "https://elsewhere.example"}
    assert approver.post(path(flow, "reject"), json=REASON, headers=no_csrf).status_code == 403
    assert approver.post(path(flow, "reject"), json=REASON, headers=other_origin).status_code == 403
    assert approver.post(path(flow, "reject"), json=REASON, headers=no_key).status_code == 422
    assert (
        approver.post(path(flow, "reject"), json={"reason": ""}, headers=headers).status_code == 422
    )
    assert (
        approver.post(
            path(flow, "reject"), json={**REASON, "extra": 1}, headers=headers
        ).status_code
        == 422
    )
    assert flow.calls == []


def test_only_the_preparer_withdraws_with_the_drafts_own_capability() -> None:
    flow = Flow()
    other = api(flow, actor(flow.prop, "refunds.create"))
    approver = api(flow, actor(flow.prop, APPROVE))

    for client in (other, approver):
        refused = client.post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "DRAFT_WITHDRAW_PREPARER_ONLY"
    assert [name for name, _ in flow.calls] == ["get", "get"]

    owner = api(flow, preparer(flow))
    withdrawn = owner.post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
    assert withdrawn.status_code == 200
    assert withdrawn.json()["data"]["state"] == "WITHDRAWN"
    assert flow.calls[-1] == (
        "withdraw",
        (flow.prop, flow.draft, REASON["reason"], "refunds.create"),
    )

    # The database has the last word on who prepared the draft.
    flow.error = FinancialDraftNotPreparerError("Only the preparer may withdraw a draft")
    refused = owner.post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "DRAFT_WITHDRAW_PREPARER_ONLY"
    flow.error = FinancialDraftDecidedError("Financial draft is already decided")
    decided = owner.post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
    assert decided.status_code == 409
    assert decided.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"


def test_withdraw_refusals_never_call_the_flow_and_show_no_database_text() -> None:
    flow = Flow()
    who = preparer(flow)
    # The preparer who no longer holds the draft's prepare capability.
    approve_only = AuthenticatedActor(
        actor_id=who.actor_id,
        capability_grants=frozenset({CapabilityGrant(APPROVE, frozenset({str(flow.prop)}))}),
    )
    refused = api(flow, approve_only).post(
        path(flow, "withdraw"), json=REASON, headers=mutation_headers()
    )
    assert refused.status_code == 403
    assert refused.headers["vary"] == "Cookie"
    assert refused.json()["error"] == {
        "code": "DRAFT_WITHDRAW_PREPARER_ONLY",
        "message": "Only the person who prepared this draft may withdraw it.",
        "fields": [],
        "rule_ids": ["BR-AUTH-010"],
        "current_version": None,
    }
    flow.get_error = FinancialDraftNotFoundError()
    hidden = api(flow, who).post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
    assert hidden.status_code == 404
    assert [name for name, _ in flow.calls] == ["get", "get"]

    # Any other authorization refusal of the database (an inactive person) stays a plain 403.
    flow.get_error = None
    flow.error = FinancialDraftAuthorizationError("Financial draft actor is not authorized")
    plain = api(flow, who).post(path(flow, "withdraw"), json=REASON, headers=mutation_headers())
    assert plain.status_code == 403 and plain.json()["error"]["code"] == "FORBIDDEN"
    flow.error = FinancialDraftNotPreparerError("Only the preparer may withdraw a draft")
    preparer_only = api(flow, who).post(
        path(flow, "withdraw"), json=REASON, headers=mutation_headers()
    )
    assert preparer_only.json()["error"]["code"] == "DRAFT_WITHDRAW_PREPARER_ONLY"


def test_reject_maps_authorization_and_a_draft_of_another_property() -> None:
    flow = Flow()
    approver = api(flow, actor(flow.prop, APPROVE))

    flow.error = FinancialDraftAuthorizationError("Financial draft actor is not authorized")
    assert (
        approver.post(path(flow, "reject"), json=REASON, headers=mutation_headers()).status_code
        == 403
    )
    flow.error = None
    flow.other_property = True
    assert approver.get(path(flow)).status_code == 503
    assert (
        approver.post(path(flow, "reject"), json=REASON, headers=mutation_headers()).status_code
        == 503
    )


def test_reservation_deposit_drafts_need_reservations_read() -> None:
    flow = Flow(variant="RESERVATION_OUTCOME", prepare_capability="reservation_deposits.refund")
    without = api(flow, actor(flow.prop, APPROVE))
    with_read = api(flow, actor(flow.prop, APPROVE, "reservations.read"))

    assert without.get(path(flow)).status_code == 404
    assert without.get(f"/api/v1/properties/{flow.prop}/financial-drafts").json()["data"] == []
    refused = without.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert refused.status_code == 404
    assert "reject" not in [name for name, _ in flow.calls]

    assert with_read.get(path(flow)).status_code == 200
    assert (
        len(with_read.get(f"/api/v1/properties/{flow.prop}/financial-drafts").json()["data"]) == 1
    )
    rejected = with_read.post(path(flow, "reject"), json=REASON, headers=mutation_headers())
    assert rejected.status_code == 200


def test_financial_approve_confirms_any_draft_through_its_own_command() -> None:
    flow = Flow()
    staff = api(flow, actor(flow.prop, "refunds.create"))
    approver = api(flow, actor(flow.prop, APPROVE))

    assert staff.post(path(flow, "confirm"), json={}, headers=mutation_headers()).status_code == 404
    assert flow.calls == []
    confirmed = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert confirmed.status_code == 200
    data = confirmed.json()["data"]
    assert data["draft"]["draft_id"] == str(flow.draft)
    # The database transaction id never reaches the screen.
    assert data["result"] == {"refund": {"id": "r-1"}}
    assert ("confirm", (flow.prop, str(flow.draft))) in flow.calls
    no_key = {key: value for key, value in mutation_headers().items() if key != "Idempotency-Key"}
    assert approver.post(path(flow, "confirm"), json={}, headers=no_key).status_code == 422


def test_confirm_refusals_have_stable_codes() -> None:
    flow = Flow()
    approver = api(flow, actor(flow.prop, APPROVE))
    cases: list[tuple[Exception, int, str]] = [
        (FinalSettlementStaleDraftError("database text 4471"), 409, "DRAFT_OUT_OF_DATE"),
        (PaymentReturnStaleDraftError("database text 4471"), 409, "DRAFT_OUT_OF_DATE"),
        (RefundConflictError("database text 4471"), 409, "DRAFT_CONFIRM_REFUSED"),
        (DraftConfirmNotAvailable("database text 4471"), 409, "DRAFT_CONFIRM_NOT_AVAILABLE"),
        (RefundNotFoundError("database text 4471"), 404, "NOT_FOUND"),
        (RefundAuthorizationError("database text 4471"), 403, "FORBIDDEN"),
        (RefundInvalidError("database text 4471"), 422, "VALIDATION_ERROR"),
        (RefundUnavailableError("database text 4471"), 503, "SERVICE_UNAVAILABLE"),
        (DraftPayloadInvalid("database text 4471"), 503, "SERVICE_UNAVAILABLE"),
    ]
    for error, status_code, code in cases:
        flow.error = error
        answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
        assert answer.status_code == status_code, error
        assert answer.json()["error"]["code"] == code, error
        assert str(error) not in answer.text


def test_a_rejected_or_withdrawn_draft_is_not_sent_to_its_confirm() -> None:
    flow = Flow()
    approver = api(flow, actor(flow.prop, APPROVE))
    for state in ("REJECTED", "WITHDRAWN"):
        flow.state = state
        answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"
    assert "confirm" not in [name for name, _ in flow.calls]


def test_only_the_approver_who_confirmed_a_draft_gets_its_result_again() -> None:
    flow = Flow(state="CONFIRMED")
    first = actor(flow.prop, APPROVE)
    flow.decided_by = first.actor_id
    again = api(flow, first).post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert again.status_code == 200
    assert again.json()["data"]["result"] == {"refund": {"id": "r-1"}}
    other = api(flow, actor(flow.prop, APPROVE)).post(
        path(flow, "confirm"), json={}, headers=mutation_headers()
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"
    assert [name for name, _ in flow.calls].count("confirm") == 1


def test_a_draft_decided_during_the_confirm_says_it_was_already_decided() -> None:
    approver_flow = Flow(states_after_confirm_error="REJECTED")
    approver = api(approver_flow, actor(approver_flow.prop, APPROVE))
    for error in (RefundConflictError("4471"), DraftConfirmNotAvailable("4471")):
        approver_flow.state, approver_flow.error = "PENDING", error
        answer = approver.post(path(approver_flow, "confirm"), json={}, headers=mutation_headers())
        assert answer.status_code == 409
        assert answer.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"
    # A stale draft is still out of date, whatever its state after the refusal.
    approver_flow.state, approver_flow.error = "PENDING", FinalSettlementStaleDraftError("4471")
    stale = approver.post(path(approver_flow, "confirm"), json={}, headers=mutation_headers())
    assert stale.json()["error"]["code"] == "DRAFT_OUT_OF_DATE"


def test_an_actor_id_that_is_not_a_uuid_is_refused_not_a_server_error() -> None:
    flow = Flow(state="CONFIRMED", decided_by=str(uuid4()))
    odd = AuthenticatedActor(
        actor_id="not-a-uuid",
        capability_grants=frozenset({CapabilityGrant(APPROVE, frozenset({str(flow.prop)}))}),
    )
    answer = api(flow, odd).post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert answer.status_code == 403


class DatabaseRefusal(psycopg.Error):
    @property
    def diag(self) -> SimpleNamespace:  # type: ignore[override]
        return SimpleNamespace(message_primary=str(self.args[0]))


def _caused(error: Exception, message: str) -> Exception:
    error.__cause__ = DatabaseRefusal(message)
    return error


def test_a_named_refusal_of_the_kinds_confirm_keeps_its_own_code() -> None:
    """Slice 11c: a stale Refund draft says why, through the shared confirm too."""
    flow = Flow()
    approver = api(flow, actor(flow.prop, APPROVE))
    failure = RefundInvalidError("Refund command is invalid")
    failure.__cause__ = DatabaseRefusal("Refund Method is not active")
    flow.error = failure
    answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "REFUND_METHOD_OFF"
    assert "not active" not in answer.text


def test_only_a_refund_draft_confirm_names_its_database_refusals() -> None:
    """Slice 11c-2 review round 1: a correction draft keeps its plain answer. (Since slice 11c-3
    Deposit and returned-Payment drafts name theirs too; see the test below.)"""
    closed = "A closed Final Settlement changes only through a post-settlement correction"
    flow = Flow(kind="SETTLEMENT_CORRECTION", variant="EXTRA_CHARGE")
    flow.error = _caused(FinalSettlementConflictError("4471"), closed)
    approver = api(flow, actor(flow.prop, APPROVE))
    answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert answer.json()["error"]["code"] == "DRAFT_CONFIRM_REFUSED"
    # The same refusal of a Refund draft is named.
    refund = Flow()
    refund.error = _caused(FinalSettlementConflictError("4471"), closed)
    named = api(refund, actor(refund.prop, APPROVE)).post(
        path(refund, "confirm"), json={}, headers=mutation_headers()
    )
    assert named.json()["error"]["code"] == "FINAL_SETTLEMENT_CLOSED"


def test_a_deposit_or_returned_payment_draft_confirm_names_its_database_refusals() -> None:
    """Slice 11c-3: the shared confirm answers the same codes as the record routes."""
    cases = [
        (
            "DEPOSIT_FORFEITURE",
            "LEASE_FORFEITURE",
            LeaseDepositForfeitureConflictError("4471"),
            "A Deposit receipt reversal draft for this Deposit is waiting",
            "DEPOSIT_DRAFT_WAITING",
        ),
        (
            "DEPOSIT_FORFEITURE",
            "DEPOSIT_RECEIPT_REVERSAL",
            DepositReceiptReversalInvalidError("4471"),
            "The Deposit receipt is already reversed",
            "DEPOSIT_RECEIPT_ALREADY_REVERSED",
        ),
        (
            "PAYMENT_RETURN",
            "PAYMENT_RETURN",
            PaymentReturnConflictError("4471"),
            "A draft that names this Payment or one of its records is waiting",
            "PAYMENT_RETURN_DRAFT_WAITING",
        ),
    ]
    for kind, variant, error, message, code in cases:
        flow = Flow(kind=kind, variant=variant)
        flow.error = _caused(error, message)
        answer = api(flow, actor(flow.prop, APPROVE)).post(
            path(flow, "confirm"), json={}, headers=mutation_headers()
        )
        assert (answer.status_code, answer.json()["error"]["code"]) == (409, code), kind
        assert message not in answer.text
    # A Deposit draft whose Deposit changed answers out of date (review round 1).
    for variant, message in (
        ("LEASE_FORFEITURE", "Lease Deposit forfeiture draft is stale"),
        ("LEASE_FORFEITURE_REVERSAL", "Lease Deposit forfeiture reversal draft is stale"),
        ("DEPOSIT_RECEIPT_REVERSAL", "Deposit receipt reversal draft is stale"),
    ):
        changed = Flow(kind="DEPOSIT_FORFEITURE", variant=variant)
        changed.error = _caused(DepositReceiptReversalInvalidError("4471"), message)
        answer = api(changed, actor(changed.prop, APPROVE)).post(
            path(changed, "confirm"), json={}, headers=mutation_headers()
        )
        assert (answer.status_code, answer.json()["error"]["code"]) == (
            409,
            "DRAFT_OUT_OF_DATE",
        ), variant
    # A Reservation Deposit draft (the same kind) keeps its plain answer.
    reservation = Flow(kind="DEPOSIT_FORFEITURE", variant="RESERVATION_OUTCOME")
    reservation.error = _caused(
        LeaseDepositForfeitureConflictError("4471"),
        "A Deposit receipt reversal draft for this Deposit is waiting",
    )
    answer = api(reservation, actor(reservation.prop, APPROVE, "reservations.read")).post(
        path(reservation, "confirm"), json={}, headers=mutation_headers()
    )
    assert answer.json()["error"]["code"] == "DRAFT_CONFIRM_REFUSED"
    # A returned-Payment draft whose sources changed stays out of date.
    stale = Flow(kind="PAYMENT_RETURN", variant="PAYMENT_RETURN")
    stale.error = _caused(
        PaymentReturnStaleDraftError("4471"),
        "A draft that names this Payment or one of its records is waiting",
    )
    answer = api(stale, actor(stale.prop, APPROVE)).post(
        path(stale, "confirm"), json={}, headers=mutation_headers()
    )
    assert answer.json()["error"]["code"] == "DRAFT_OUT_OF_DATE"


def test_a_payment_move_draft_confirm_names_its_database_refusals() -> None:
    """Slice 11d: the plain move names its refusals at the shared confirm; a Final Settlement
    correction of variant PAYMENT_MOVE keeps its plain answer."""
    cases = [
        (
            PaymentMoveConflictError("4471"),
            "The Payment is reversed",
            "PAYMENT_MOVE_PAYMENT_REVERSED",
        ),
        # The database raises the stale move draft as 55000, a conflict, not as P5S02.
        (PaymentMoveConflictError("4471"), "Payment move draft is stale", "DRAFT_OUT_OF_DATE"),
        (
            PaymentMoveConflictError("4471"),
            "The correct Invoice has nothing outstanding",
            "DRAFT_OUT_OF_DATE",
        ),
        (
            PaymentMoveConflictError("4471"),
            "A closed Final Settlement changes only through a post-settlement correction",
            "PAYMENT_MOVE_THROUGH_CORRECTION",
        ),
    ]
    for error, message, code in cases:
        flow = Flow(kind="PAYMENT_MOVE", variant="WRONG_UNIT_MOVE")
        flow.error = _caused(error, message)
        answer = api(flow, actor(flow.prop, APPROVE)).post(
            path(flow, "confirm"), json={}, headers=mutation_headers()
        )
        assert (answer.status_code, answer.json()["error"]["code"]) == (409, code), message
        assert message not in answer.text
    correction = Flow(kind="SETTLEMENT_CORRECTION", variant="PAYMENT_MOVE")
    correction.error = _caused(
        PaymentMoveConflictError("4471"), "This allocation was already moved"
    )
    answer = api(correction, actor(correction.prop, APPROVE)).post(
        path(correction, "confirm"), json={}, headers=mutation_headers()
    )
    assert (answer.status_code, answer.json()["error"]["code"]) == (409, "DRAFT_CONFIRM_REFUSED")


def test_an_out_of_date_refund_draft_stays_out_of_date_whatever_the_cause() -> None:
    flow = Flow()
    flow.error = _caused(FinalSettlementStaleDraftError("4471"), "Refund Method is not active")
    approver = api(flow, actor(flow.prop, APPROVE))
    answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert answer.json()["error"]["code"] == "DRAFT_OUT_OF_DATE"


def test_a_named_conflict_is_answered_without_reading_the_draft_again() -> None:
    flow = Flow(states_after_confirm_error="CONFIRMED")
    flow.error = _caused(
        RefundConflictError("4471"),
        "A Deposit receipt reversal draft for this Deposit is waiting",
    )
    approver = api(flow, actor(flow.prop, APPROVE))
    answer = approver.post(path(flow, "confirm"), json={}, headers=mutation_headers())
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "REFUND_DEPOSIT_RECEIPT_REVERSAL_WAITING"
    assert [name for name, _ in flow.calls].count("get") == 1
