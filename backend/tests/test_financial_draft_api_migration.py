"""The shared financial draft routes on real PostgreSQL (V1-056 slice 11b)."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

import psycopg
from httpx import Response

from property_rental.refund import RefundService
from refund_test_support import cash
from test_credit_migration import actor, source
from test_credit_refund_api_migration import CAPABILITIES, headers
from test_invoice_migration import financial_database_url, runtime_database_url
from test_payment_api_migration import api
from test_reservation_migration import migrated_database_url  # noqa: F401


def record_draft(client: object, prop: UUID, human: UUID, payment: UUID, cents: int) -> str:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    choice = cash(
        RefundService(runtime_database_url(), financial_database_url()),
        prop,
        actor(human, prop, "refunds.read"),
    )
    answer: Response = client.post(
        "/api/v1/refund-drafts",
        json={
            "currency": "USD",
            "source_type": "PAYMENT",
            "source_id": str(payment),
            "amount_usd_cents": cents,
            "reason": "Return eligible USD excess",
            "refund_method_id": str(choice.refund_method_id),
            "reference_note": choice.reference_note,
        },
        headers=headers(human),
    )
    assert answer.status_code == 201, answer.text
    return str(answer.json()["data"]["draft_id"])


def test_drafts_are_listed_confirmed_rejected_and_withdrawn_through_the_shared_routes(
    migrated_database_url: str,  # noqa: F811
) -> None:
    human, prop, _, payment = source(migrated_database_url)
    client = api(actor(human, prop, *CAPABILITIES))
    base = f"/api/v1/properties/{prop}/financial-drafts"
    confirmed_id = record_draft(client, prop, human, payment, 100)
    rejected_id = record_draft(client, prop, human, payment, 200)
    withdrawn_id = record_draft(client, prop, human, payment, 300)

    pending = client.get(base, params={"state": "PENDING", "limit": 2})
    assert pending.status_code == 200, pending.text
    assert pending.headers["cache-control"] == "private, no-store"
    first_page = [item["draft_id"] for item in pending.json()["data"]]
    assert first_page == [withdrawn_id, rejected_id]
    following = client.get(
        base,
        params={"state": "PENDING", "limit": 2, "cursor": pending.json()["page"]["next_cursor"]},
    )
    assert [item["draft_id"] for item in following.json()["data"]] == [confirmed_id]
    assert following.json()["page"]["next_cursor"] is None

    confirmed = client.post(f"{base}/{confirmed_id}/confirm", json={}, headers=headers(human))
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["draft"]["state"] == "CONFIRMED"
    # The Refund confirm answers the draft and the Refund read (GET /refunds/{id} body).
    read = cast(dict[str, object], cast(dict[str, object], data["result"])["refund"])
    refund = cast(dict[str, object], read["refund"])
    assert refund["refund_amount_minor"] == 100
    assert "transaction_id" not in json.dumps(data)
    # Confirming again answers the first result; nothing is recorded twice.
    again = client.post(f"{base}/{confirmed_id}/confirm", json={}, headers=headers(human))
    assert again.status_code == 200 and again.json()["data"]["result"] == data["result"]

    rejected = client.post(
        f"{base}/{rejected_id}/reject", json={"reason": "Wrong amount"}, headers=headers(human)
    )
    assert rejected.status_code == 200 and rejected.json()["data"]["state"] == "REJECTED"
    late = client.post(f"{base}/{rejected_id}/confirm", json={}, headers=headers(human))
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"

    withdrawn = client.post(
        f"{base}/{withdrawn_id}/withdraw", json={"reason": "Not needed"}, headers=headers(human)
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["data"]["state"] == "WITHDRAWN"
    decided = client.post(
        f"{base}/{withdrawn_id}/reject", json={"reason": "Too late"}, headers=headers(human)
    )
    assert decided.status_code == 409
    assert decided.json()["error"]["code"] == "DRAFT_ALREADY_DECIDED"

    detail = client.get(f"{base}/{confirmed_id}")
    assert detail.status_code == 200 and "transaction_id" not in detail.text
    assert client.get(base, params={"state": "PENDING"}).json()["data"] == []
    # A person who holds no draft capability of this Property does not see its drafts.
    stranger = api(actor(human, prop, "payments.read"))
    assert stranger.get(base).status_code == 404


def test_every_named_refusal_message_is_still_raised_at_head(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """The routes name a refusal by the database's exact message (slice 11c-2 review round 1)."""
    from property_rental.credit_refund_api import REFUND_REFUSALS_BY_DATABASE_MESSAGE
    from property_rental.deposit_api import DEPOSIT_RECEIPT_REFUSALS, SECURITY_DEPOSIT_REFUSALS
    from property_rental.draft_record_api import (
        DEPOSIT_DRAFT_CONFIRM_REFUSALS,
        PAYMENT_RETURN_REFUSALS,
    )
    from property_rental.invoice_api import REFUSALS_BY_DATABASE_MESSAGE
    from property_rental.lease import END_DATE_NOT_MONTH_END

    messages = {*REFUND_REFUSALS_BY_DATABASE_MESSAGE, *REFUSALS_BY_DATABASE_MESSAGE}
    # Slice 11c-3: the Deposit and returned-Payment draft routes and their confirm.
    messages |= {*DEPOSIT_DRAFT_CONFIRM_REFUSALS, *PAYMENT_RETURN_REFUSALS}
    # Slice 11c-4: the walk-in Security Deposit create and the Deposit receipt.
    messages |= {*SECURITY_DEPOSIT_REFUSALS, *DEPOSIT_RECEIPT_REFUSALS}
    # Slice 11d: the wrong-Unit Payment move and the one-call allocation reversal.
    from property_rental.allocation_receipt_api import ALLOCATION_REVERSAL_REFUSALS
    from property_rental.draft_record_api import (
        PAYMENT_MOVE_CONFIRM_REFUSALS,
        PAYMENT_MOVE_REFUSALS,
    )

    messages |= {*PAYMENT_MOVE_REFUSALS, *PAYMENT_MOVE_CONFIRM_REFUSALS}
    messages |= set(ALLOCATION_REVERSAL_REFUSALS)
    messages.add(END_DATE_NOT_MONTH_END)
    with psycopg.connect(migrated_database_url) as connection:
        missing = [
            message
            for message in sorted(messages)
            if not connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p"
                " JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'app' AND strpos(p.prosrc, %s) > 0)",
                ("'" + message.replace("'", "''") + "'",),
            ).fetchone()[0]  # type: ignore[index]
        ]
    assert missing == []
