"""The wrong-Unit Payment move draft route on real PostgreSQL (V1-056 slice 11d; BR-PAY-042):
the draft is recorded over HTTP, confirmed through the shared draft route, and each named refusal
answers its own code."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from payment_test_support import seed_payment
from test_credit_refund_api_migration import headers
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_api_migration import api
from test_payment_move_migration import (
    SOURCE_ACK,
    TARGET_ACK,
    WrongAllocation,
    approver,
    nothing_moved,
    person,
    preparer,
    statuses,
    value,
    wrong_allocation,
)
from test_reservation_migration import migrated_database_url  # noqa: F401

MOVE_PREPARE = "payments.allocations.reverse"


def _body(case: WrongAllocation, target: UUID | None = None) -> dict[str, str]:
    return {
        "target_invoice_id": str(target or case.invoice_right),
        "reason": "Paid on Parking 203 by mistake; meant for Parking 201",
        "source_acknowledgement": SOURCE_ACK,
        "target_acknowledgement": TARGET_ACK,
    }


def _record(
    client: TestClient,
    case: WrongAllocation,
    *,
    allocation: UUID | None = None,
    target: UUID | None = None,
    key: UUID | None = None,
) -> Response:
    answer: Response = client.post(
        f"/api/v1/properties/{case.prop}/payment-allocations/"
        f"{allocation or case.allocation}/move-drafts",
        json=_body(case, target),
        headers=headers(case.human, key),
    )
    return answer


def _confirm(client: TestClient, case: WrongAllocation, draft: str) -> Response:
    answer: Response = client.post(
        f"/api/v1/properties/{case.prop}/financial-drafts/{draft}/confirm",
        json={},
        headers=headers(case.approver),
    )
    return answer


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json()["error"]["code"])


def test_a_wrong_unit_move_is_recorded_over_http_and_confirmed_by_an_approver(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    staff = api(preparer(case))
    assert _code(_record(staff, case, target=case.invoice_wrong)) == (
        422,
        "PAYMENT_MOVE_TARGET_SAME_UNIT",
    )
    assert _code(_record(staff, case, target=uuid4())) == (422, "PAYMENT_MOVE_TARGET_NOT_FOUND")
    assert _record(staff, case, allocation=uuid4()).status_code == 404
    hidden = api(person(case.human, case.prop, "payments.allocate", "payments.reverse"))
    assert _record(hidden, case).status_code == 404
    nothing_moved(url, case)

    key = uuid4()
    recorded = _record(staff, case, key=key)
    assert recorded.status_code == 201, recorded.text
    draft = cast(dict[str, Any], recorded.json()["data"])
    assert (draft["kind"], draft["state"], draft["payload"]["variant"]) == (
        "PAYMENT_MOVE",
        "PENDING",
        "WRONG_UNIT_MOVE",
    )
    again = _record(staff, case, key=key)
    assert again.status_code == 201 and again.json()["data"] == draft
    assert _code(_record(staff, case)) == (409, "PAYMENT_MOVE_DRAFT_WAITING")
    nothing_moved(url, case)

    confirmed = _confirm(api(approver(case)), case, draft["draft_id"])
    assert confirmed.status_code == 200, confirmed.text
    result = cast(dict[str, Any], confirmed.json()["data"]["result"])
    moved = UUID(str(result["move"]["target_allocation_id"]))
    assert statuses(url, case.invoice_wrong, case.invoice_right) == {
        case.invoice_wrong: "UNPAID",
        case.invoice_right: "PAID",
    }
    assert _code(_record(staff, case)) == (409, "PAYMENT_MOVE_ALREADY_MOVED")
    # The one-call reversal names a moved allocation (Q-2026-10-05-17).
    undo = staff.post(
        f"/api/v1/payment-allocations/{moved}/reverse",
        json={"reason": "Undo the move"},
        headers=headers(case.human),
    )
    assert _code(undo) == (409, "ALLOCATION_MOVED")
    assert (
        value(
            url,
            "SELECT count(*) FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s",
            moved,
        )
        == 0
    )


def test_a_move_draft_whose_correct_invoice_was_paid_meanwhile_is_out_of_date(
    migrated_database_url: str,  # noqa: F811
) -> None:
    url = migrated_database_url
    case = wrong_allocation(url)
    recorded = _record(api(preparer(case)), case)
    assert recorded.status_code == 201, recorded.text
    with psycopg.connect(url) as connection:
        other = seed_payment(
            connection,
            actor_id=case.human,
            property_id=case.prop,
            customer_id=case.customer_right,
            amount=80_000,
        )
    allocations().post(
        case.prop,
        other,
        designated(case.invoice_right, case.line_right, 80_000),
        actor=person(case.human, case.prop, "payments.allocate"),
    )
    answer = _confirm(api(approver(case)), case, recorded.json()["data"]["draft_id"])
    assert _code(answer) == (409, "DRAFT_OUT_OF_DATE")
    # The draft stays pending, to be rejected and recorded again; nothing moved.
    draft = recorded.json()["data"]["draft_id"]
    decided = "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s"
    assert value(url, decided, draft) == 0
    assert (
        value(url, "SELECT count(*) FROM app.payment_moves WHERE payment_id=%s", case.payment) == 0
    )
    # The approver rejects it, so no pending draft is left behind for the shared list tests.
    rejected = api(approver(case)).post(
        f"/api/v1/properties/{case.prop}/financial-drafts/{draft}/reject",
        json={"reason": "The correct Invoice was paid meanwhile"},
        headers=headers(case.approver),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["state"] == "REJECTED"
