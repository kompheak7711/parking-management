"""The Final Settlement routes on real PostgreSQL (V1-056 slice 11e-1; API-070 to API-072): a
preparer starts the Settlement, reads the preview and records the draft over HTTP; an approver
confirms it through the shared draft route and the Settlement closes; each named refusal answers
its own code."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from property_rental.final_settlement import SettlementStep
from test_credit_refund_api_migration import headers
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import (
    APPROVE,
    PREPARE,
    STAFF,
    leaving_case,
    normal_plan,
)
from test_final_settlement_preview_migration import person
from test_invoice_migration import setup_signed_lease
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_api_migration import api

REASON = "Final Settlement prepared from the move-out review"


def _steps(plan: tuple[SettlementStep, ...]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in step.payload().items() if value is not None} for step in plan
    ]


def _record(
    client: TestClient,
    case: dict[str, Any],
    steps: list[dict[str, object]],
    key: UUID,
    who: UUID | None = None,
) -> Response:
    answer: Response = client.post(
        f"/api/v1/properties/{case['prop']}/final-settlements/{case['settlement']}/drafts",
        json={
            "steps": steps,
            "reason": REASON,
            # The normal plan uses the rest of the Pet Deposit for the other damage.
            "pet_remainder": {
                key: value for key, value in STAFF.payload().items() if value is not None
            },
        },
        headers=headers(who or case["human"], key),
    )
    return answer


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json()["error"]["code"])


def test_a_settlement_is_started_previewed_drafted_and_closed_over_http(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    prop, human, settlement = case["prop"], case["human"], case["settlement"]
    preparer = api(person(human, prop, PREPARE))
    base = f"/api/v1/properties/{prop}"

    # Starting again returns the one Settlement of the Lease.
    started = preparer.post(
        f"{base}/leases/{case['lease']}/final-settlement", json={}, headers=headers(human)
    )
    assert started.status_code == 200, started.text
    assert (started.json()["data"]["id"], started.json()["data"]["closed"]) == (
        str(settlement),
        False,
    )
    preview = preparer.get(f"{base}/final-settlements/{settlement}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["settlement"]["id"] == str(settlement)
    assert preview.headers["cache-control"] == "private, no-store"

    # A Deposit before the Customer's own Credit breaks DL-032 step 2: 422 on the steps.
    plan = _steps(normal_plan(case))
    refused = _record(preparer, case, plan[1:], uuid4())
    assert _code(refused) == (422, "FINAL_SETTLEMENT_CREDIT_FIRST")
    assert refused.json()["error"]["fields"] == ["steps"]

    key = uuid4()
    recorded = _record(preparer, case, plan, key)
    assert recorded.status_code == 201, recorded.text
    draft = recorded.json()["data"]
    assert (draft["kind"], draft["state"]) == ("FINAL_SETTLEMENT", "PENDING")
    assert _record(preparer, case, plan, key).json()["data"]["draft_id"] == draft["draft_id"]
    assert _code(_record(preparer, case, plan[:-1], key)) == (409, "IDEMPOTENCY_KEY_REUSED")
    assert _code(_record(preparer, case, plan, uuid4())) == (409, "FINAL_SETTLEMENT_DRAFT_WAITING")

    with psycopg.connect(url) as connection:
        approver_id = setup_signed_lease(connection)[0]
    approver = api(person(approver_id, prop, APPROVE))
    # The approver reads the preview too, but cannot start or prepare.
    assert approver.get(f"{base}/final-settlements/{settlement}/preview").status_code == 200
    assert _record(approver, case, plan, uuid4(), approver_id).status_code == 404
    confirmed = approver.post(
        f"{base}/financial-drafts/{draft['draft_id']}/confirm",
        json={},
        headers=headers(approver_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["draft"]["state"] == "CONFIRMED"

    closed = preparer.post(
        f"{base}/leases/{case['lease']}/final-settlement", json={}, headers=headers(human)
    )
    assert closed.status_code == 200 and closed.json()["data"]["closed"] is True
    again = _record(preparer, case, plan, uuid4())
    assert again.status_code == 409, again.text
    # A closed Settlement is a blocking issue of the preview (SETTLEMENT_CLOSED).
    assert again.json()["error"]["code"] == "FINAL_SETTLEMENT_BLOCKING_ISSUES"
    issues = approver.get(f"{base}/final-settlements/{settlement}/preview").json()["data"]
    assert {"code": "SETTLEMENT_CLOSED"} in issues["blocking_issues"]


def test_a_settlement_starts_only_for_a_terminated_lease(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, _, lease = setup_signed_lease(connection)
    answer = api(person(human, prop, PREPARE)).post(
        f"/api/v1/properties/{prop}/leases/{lease}/final-settlement",
        json={},
        headers=headers(human),
    )
    assert _code(answer) == (409, "FINAL_SETTLEMENT_LEASE_NOT_TERMINATED")
    assert "TERMINATED Lease" not in answer.text
    unknown = api(person(human, prop, PREPARE)).post(
        f"/api/v1/properties/{prop}/leases/{uuid4()}/final-settlement",
        json={},
        headers=headers(human),
    )
    assert unknown.status_code == 404
    assert cast(dict[str, object], unknown.json())["error"] is not None
