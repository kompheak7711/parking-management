"""The post-settlement correction routes on real PostgreSQL (V1-056 slice 11e-2; API-072): a
preparer records a correction of a closed Final Settlement over HTTP and an approver confirms it
through the shared draft route; an open Settlement and a wrong record answer their own codes; the
plain Adjustment reversal draft is recorded under invoices.adjust."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from test_adjustment_reversal_migration import adjustments
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import pay
from test_credit_refund_api_migration import headers
from test_debit_adjustment_line_block_migration import first_line
from test_final_settlement_closed_refusal_migration import close
from test_final_settlement_draft_migration import APPROVE, PREPARE, leaving_case
from test_final_settlement_preview_migration import person
from test_invoice_migration import setup_signed_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import source as allocation_source
from test_payment_api_migration import api
from test_settlement_charge_reduction_migration import invoice_of

CHARGE = {
    "category": "MISCELLANEOUS_CHARGES",
    "description": "Replacement key card",
    "amount_usd_cents": 1_500,
    "evidence_reference": "Front desk log 7",
    "reason": "The replacement key card was missed at the Final Settlement",
}


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json()["error"]["code"])


def _charge(
    client: TestClient,
    case: dict[str, object],
    key: UUID,
    body: dict[str, object] | None = None,
) -> Response:
    answer: Response = client.post(
        f"/api/v1/properties/{case['prop']}/final-settlements/{case['settlement']}"
        "/corrections/extra-charges",
        json=CHARGE if body is None else body,
        headers=headers(UUID(str(case["human"])), key),
    )
    return answer


def test_an_extra_charge_correction_is_recorded_and_confirmed_over_http(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    preparer = api(person(human, prop, PREPARE))
    base = f"/api/v1/properties/{prop}"

    # An open Settlement takes no correction: 409 with its own code, no database text.
    refused = _charge(preparer, case, uuid4())
    assert _code(refused) == (409, "CORRECTION_SETTLEMENT_NOT_CLOSED")
    assert "needs a closed Final Settlement" not in refused.text
    close(url, human, settlement)

    # A Damage charge names a finding of the current inspection: 422 on that field.
    damage = {
        **CHARGE,
        "category": "DAMAGE_CHARGES",
        "inspection_damage_finding_id": str(uuid4()),
    }
    wrong = _charge(preparer, case, uuid4(), damage)
    assert _code(wrong) == (422, "CORRECTION_FINDING_NOT_CURRENT")
    assert wrong.json()["error"]["fields"] == ["inspection_damage_finding_id"]

    key = uuid4()
    recorded = _charge(preparer, case, key)
    assert recorded.status_code == 201, recorded.text
    draft = recorded.json()["data"]
    assert (draft["kind"], draft["state"]) == ("SETTLEMENT_CORRECTION", "PENDING")
    assert (draft["payload"]["variant"], draft["payload"]["final_settlement_id"]) == (
        "EXTRA_CHARGE",
        str(settlement),
    )
    assert recorded.headers["cache-control"] == "private, no-store"
    assert _charge(preparer, case, key).json()["data"]["draft_id"] == draft["draft_id"]
    assert _code(_charge(preparer, case, key, {**CHARGE, "amount_usd_cents": 1_600})) == (
        409,
        "IDEMPOTENCY_KEY_REUSED",
    )

    approver_id, approver = _approver(url, prop)
    # The approver confirms but cannot record a correction.
    assert _charge(approver, {**case, "human": approver_id}, uuid4()).status_code == 404
    confirmed = approver.post(
        f"{base}/financial-drafts/{draft['draft_id']}/confirm",
        json={},
        headers=headers(approver_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["draft"]["state"] == "CONFIRMED"


def _approver(url: str, prop: UUID) -> tuple[UUID, TestClient]:
    with psycopg.connect(url) as connection:
        approver_id = setup_signed_lease(connection)[0]
    return approver_id, api(person(approver_id, prop, APPROVE))


def test_a_charge_reduction_and_its_adjustment_reversal_are_recorded_over_http(
    migrated_database_url: str,
) -> None:
    """Review round 1: the real draft shapes of the reduction and the Adjustment reversal
    correction pass the route's answer checks, and the body-chosen records that are unknown
    answer 422 on their fields."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    close(url, human, settlement)
    line = case["other_line"]
    invoice = invoice_of(url, line)
    preparer = api(person(human, prop, PREPARE))
    corrections = f"/api/v1/properties/{prop}/final-settlements/{settlement}/corrections"

    def post(route: str, body: dict[str, object]) -> Response:
        answer: Response = preparer.post(
            f"{corrections}/{route}", json=body, headers=headers(human)
        )
        return answer

    reduction = {
        "invoice_id": str(invoice),
        "invoice_line_id": str(line),
        "amount_usd_cents": 2_500,
        "reason": "The window latch was charged at the wrong amount",
    }
    elsewhere = post("charge-reductions", {**reduction, "invoice_id": str(uuid4())})
    assert _code(elsewhere) == (422, "CORRECTION_REDUCED_INVOICE_NOT_OF_SETTLEMENT")
    assert elsewhere.json()["error"]["fields"] == ["invoice_id"]
    recorded = post("charge-reductions", reduction)
    assert recorded.status_code == 201, recorded.text
    draft = recorded.json()["data"]
    assert draft["payload"]["variant"] == "CHARGE_REDUCTION"
    assert "target_kind" not in draft["payload"]
    approver_id, approver = _approver(url, prop)
    confirmed = approver.post(
        f"/api/v1/properties/{prop}/financial-drafts/{draft['draft_id']}/confirm",
        json={},
        headers=headers(approver_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    [adjustment] = adjustments(url, line)

    # The plain draft does not reverse a correction's Adjustment after closure.
    plain = api(person(human, prop, "invoices.adjust")).post(
        f"/api/v1/properties/{prop}/invoice-adjustments/{adjustment}/reversal-drafts",
        json={"reason": "The reduction was recorded by mistake"},
        headers=headers(human),
    )
    assert _code(plain) in {
        (409, "ADJUSTMENT_REVERSAL_OF_CORRECTION"),
        (409, "ADJUSTMENT_REVERSAL_THROUGH_CORRECTION"),
    }
    reversal: dict[str, object] = {
        "adjustment_id": str(adjustment),
        "reason": "The reduction was recorded by mistake",
    }
    unknown = post("adjustment-reversals", {**reversal, "adjustment_id": str(uuid4())})
    assert _code(unknown) == (422, "ADJUSTMENT_REVERSAL_CORRECTION_NOT_FOUND")
    assert unknown.json()["error"]["fields"] == ["adjustment_id"]
    reversed_draft = post("adjustment-reversals", reversal)
    assert reversed_draft.status_code == 201, reversed_draft.text
    assert reversed_draft.json()["data"]["payload"]["invoice_adjustment_id"] == str(adjustment)

    # A returned Payment and a moved allocation the form names must exist in the Property.
    returned = post(
        "returned-payments",
        {
            "payment_id": str(uuid4()),
            "reason": "The bank returned the transfer",
            "evidence_reference": "Bank notice 2026-10-20",
        },
    )
    assert _code(returned) == (422, "RETURNED_PAYMENT_NOT_FOUND")
    assert returned.json()["error"]["fields"] == ["payment_id"]
    moved = post(
        "payment-moves",
        {
            "allocation_id": str(uuid4()),
            "target_invoice_id": str(invoice),
            "reason": "The money was for another Unit",
            "source_acknowledgement": "The Customer agreed on 2026-10-24",
            "target_acknowledgement": "The other Customer agreed on 2026-10-24",
        },
    )
    assert _code(moved) == (422, "MOVE_CORRECTION_ALLOCATION_NOT_FOUND")
    assert moved.json()["error"]["fields"] == ["allocation_id"]
    for answer in (elsewhere, unknown, returned, moved):
        assert "was not found" not in answer.text

    # No pending draft is left on the shared test Property.
    rejected = approver.post(
        f"/api/v1/properties/{prop}/financial-drafts/"
        f"{reversed_draft.json()['data']['draft_id']}/reject",
        json={"reason": "Recorded for the route test"},
        headers=headers(approver_id),
    )
    assert rejected.status_code == 200, rejected.text


def test_a_plain_adjustment_reversal_draft_is_recorded_over_http(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    adjust_credit(url, human, prop, invoice, line, 10_000)
    [adjustment] = adjustments(url, line)
    path = f"/api/v1/properties/{prop}/invoice-adjustments/{adjustment}/reversal-drafts"
    body = {"reason": "The reduction was recorded by mistake"}

    # A final_settlements.prepare holder cannot record it: the Property is hidden.
    assert (
        api(person(human, prop, PREPARE)).post(path, json=body, headers=headers(human)).status_code
        == 404
    )
    preparer = api(person(human, prop, "invoices.adjust"))
    recorded = preparer.post(path, json=body, headers=headers(human))
    assert recorded.status_code == 201, recorded.text
    draft = recorded.json()["data"]
    assert (draft["kind"], draft["state"], draft["payload"]["invoice_adjustment_id"]) == (
        "ADJUSTMENT_REVERSAL",
        "PENDING",
        str(adjustment),
    )
    waiting = preparer.post(path, json=body, headers=headers(human))
    assert _code(waiting) == (409, "ADJUSTMENT_REVERSAL_DRAFT_WAITING")
    unknown = preparer.post(
        f"/api/v1/properties/{prop}/invoice-adjustments/{uuid4()}/reversal-drafts",
        json=body,
        headers=headers(human),
    )
    assert unknown.status_code == 404
    # The approver rejects it, so no pending draft is left on the shared test Property.
    rejected = api(person(human, prop, APPROVE)).post(
        f"/api/v1/properties/{prop}/financial-drafts/{draft['draft_id']}/reject",
        json={"reason": "Recorded for the route test"},
        headers=headers(human),
    )
    assert rejected.status_code == 200, rejected.text
