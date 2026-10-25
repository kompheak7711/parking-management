"""The plan corrections on real PostgreSQL (V1-056 slice 11e-3; API-072): after the real closure a
preparer records a Refund correction of a paid wrong charge over HTTP, the draft shape passes the
route's answer check and an approver confirms it; each route's body-chosen record that does not fit
answers 422 on its field with no database text."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from test_credit_refund_api_migration import headers
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import APPROVE, PREPARE, leaving_case
from test_final_settlement_migration import outstanding
from test_final_settlement_preview_migration import person
from test_invoice_migration import setup_signed_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_api_migration import api
from test_settlement_refund_correction_migration import really_close
from test_unpaid_initial_termination_migration import rent_line

REASON = "The Rent was charged at the wrong amount"
NOTE = "Cash handed over at the front desk"
EVIDENCE = "Front desk log 7"


def _code(answer: Response) -> tuple[int, str, list[str]]:
    error = answer.json()["error"]
    return answer.status_code, str(error["code"]), list(error["fields"])


def test_a_refund_correction_is_recorded_and_confirmed_over_http_and_records_are_checked(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case: dict[str, Any] = leaving_case(url, start_offset=this_month(url))
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    invoice = case["initial"]
    rent, rest = rent_line(url, invoice)
    assert rest == 0
    preparer = api(person(human, prop, PREPARE))
    base = f"/api/v1/properties/{prop}/final-settlements/{settlement}/corrections"

    def post(route: str, body: dict[str, object]) -> Response:
        answer: Response = preparer.post(f"{base}/{route}", json=body, headers=headers(human))
        return answer

    refund = {
        "invoice_id": str(invoice),
        "invoice_line_id": str(rent),
        "amount_usd_cents": 1_000,
        "refund_method_id": str(case["cash"]),
        "reference_note": NOTE,
        "reason": REASON,
    }
    assert _code(post("refunds", refund)) == (409, "CORRECTION_SETTLEMENT_NOT_CLOSED", [])
    really_close(case)

    inactive = post("refunds", {**refund, "refund_method_id": str(uuid4())})
    assert _code(inactive) == (422, "CORRECTION_REFUND_METHOD_OFF", ["refund_method_id"])
    too_much = post("refunds", {**refund, "amount_usd_cents": 9_000_000_000})
    assert _code(too_much) == (422, "CORRECTION_REFUND_OVER_CHARGE", ["amount_usd_cents"])
    recorded = post("refunds", refund)
    assert recorded.status_code == 201, recorded.text
    draft = recorded.json()["data"]
    assert (draft["kind"], draft["payload"]["variant"]) == ("SETTLEMENT_CORRECTION", "REFUND")
    assert "target_kind" not in draft["payload"]

    # Each route's form names a record that is not in this Settlement or Property.
    unknown = str(uuid4())
    checks: list[tuple[str, dict[str, object], tuple[str, list[str]]]] = [
        (
            "pet-classifications",
            {
                "invoice_id": str(invoice),
                "invoice_line_id": str(rent),
                "pet_related": True,
                "evidence_reference": EVIDENCE,
                "reason": REASON,
            },
            ("CORRECTION_PET_LINE_NOT_DAMAGE", ["invoice_line_id"]),
        ),
        (
            "late-charge-refunds",
            {
                "late_payment_charge_id": unknown,
                "amount_usd_cents": 100,
                "refund_method_id": str(case["cash"]),
                "reference_note": NOTE,
                "reason": REASON,
            },
            ("CORRECTION_REFUNDED_LATE_CHARGE_NOT_OF_SETTLEMENT", ["late_payment_charge_id"]),
        ),
        (
            "refund-returns",
            {
                "refund_id": unknown,
                "returned_amount_usd_cents": 100,
                "returned_at": "2026-10-20T09:30:00+07:00",
                "return_method_reference": "ABA return 7781",
                "evidence_reference": EVIDENCE,
                "reason": REASON,
            },
            ("CORRECTION_REFUND_NOT_FOUND", ["refund_id"]),
        ),
        (
            "held-value-refunds",
            {
                "held_from_correction_id": unknown,
                "reason": REASON,
                "new_refund_method_id": str(case["cash"]),
                "new_refund_reference_note": NOTE,
            },
            ("CORRECTION_HELD_FROM_NOT_FOUND", ["held_from_correction_id"]),
        ),
        (
            "forfeiture-reversals",
            {
                "deposit_disposition_id": unknown,
                "reason": REASON,
                "evidence_reference": EVIDENCE,
                "refund_method_id": str(case["cash"]),
                "reference_note": NOTE,
            },
            ("CORRECTION_FORFEITURE_NOT_FOUND", ["deposit_disposition_id"]),
        ),
        (
            "deposit-receipt-corrections",
            {"deposit_receipt_id": unknown, "reason": REASON, "evidence_reference": EVIDENCE},
            ("RECEIPT_CORRECTION_NOT_FOUND", ["deposit_receipt_id"]),
        ),
        (
            "return-reversals",
            {"earlier_correction_id": unknown, "reason": REASON, "evidence_reference": EVIDENCE},
            ("RETURN_REVERSAL_NOT_FOUND", ["earlier_correction_id"]),
        ),
    ]
    for route, body, (code, fields) in checks:
        answer = post(route, body)
        assert _code(answer) == (422, code, fields), (route, answer.text)
        assert "was not found" not in answer.text and "only a Damage line" not in answer.text

    with psycopg.connect(url) as connection:
        approver_id = setup_signed_lease(connection)[0]
    approver: TestClient = api(person(approver_id, prop, APPROVE))
    confirmed = approver.post(
        f"/api/v1/properties/{prop}/financial-drafts/{draft['draft_id']}/confirm",
        json={},
        headers=headers(approver_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["draft"]["state"] == "CONFIRMED"
    # The credit Adjustment removed the wrong part from the Rent line.
    assert outstanding(url, UUID(str(rent))) == 0
