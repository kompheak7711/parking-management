"""Real PostgreSQL coverage of the Waiting for approval read (V1-058 R7a).

The page lists the drafts that wait, oldest first, and those decided today. Each draft kind keeps
its own payload, so the read adds one plain line: the variant, the amount in cents, where the
money goes (OUT, KEPT or INTERNAL), the Customer, the Unit and who prepared it.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from property_rental.financial_draft import FINANCIAL_APPROVE_CAPABILITY, FinancialDraftService
from test_financial_draft_migration import _service
from test_invoice_migration import financial_database_url, runtime_database_url
from test_lease_lifecycle_migration import actor, setup_sources
from test_lease_lifecycle_migration import migrated_database_url as migrated_database_url

FUNCTION = "app.financial_draft_approvals(uuid,uuid,text[])"


def _setup(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        sources = setup_sources(connection)
        # The account trigger records the person as HUMAN, as the read asks.
        connection.commit()
    return sources


def _draft(
    url: str, prop: UUID, preparer: UUID, kind: str, capability: str, payload: dict[str, Any]
) -> UUID:
    draft_id = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                prop,
                preparer,
                draft_id,
                kind,
                capability,
                Jsonb(payload),
                "revision-1",
                "Prepared for the Waiting for approval read",
            ),
        )
        connection.commit()
    return draft_id


def _approvals(prop: UUID, human: UUID, *capabilities: str) -> dict[str, Any]:
    service = FinancialDraftService(runtime_database_url(), financial_database_url())
    return cast("dict[str, Any]", service.approvals(prop, actor=actor(human, prop, *capabilities)))


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["draft_id"]: item for item in items}


def test_each_waiting_draft_gets_its_amount_direction_customer_and_unit(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, unit, tenant, other = _setup(url)
    refund = _draft(
        url,
        prop,
        human,
        "REFUND",
        "refunds.create",
        {
            "variant": "CREDIT_CUSTOMER",
            "source_kind": "CREDIT",
            "source_id": str(uuid4()),
            "recipient_customer_id": str(tenant),
            "amount_usd_cents": 500,
        },
    )
    kept = _draft(
        url,
        prop,
        human,
        "DEPOSIT_FORFEITURE",
        "deposits.dispose",
        {"variant": "LEASE_FORFEITURE", "deposit_id": str(uuid4()), "amount_usd_cents": 30_000},
    )
    moved = _draft(
        url,
        prop,
        human,
        "PAYMENT_MOVE",
        "payments.allocations.reverse",
        {
            "variant": "WRONG_UNIT_MOVE",
            "source": {
                "moved_usd_cents": 1_200,
                "source_customer_id": str(other),
                "target_unit_id": str(unit),
            },
        },
    )
    charge = _draft(
        url,
        prop,
        human,
        "SETTLEMENT_CORRECTION",
        "final_settlements.prepare",
        {
            "variant": "EXTRA_CHARGE",
            "customer_id": str(tenant),
            "charge": {"amount_usd_cents": 2_500},
        },
    )
    # A payload the read does not understand gives no amount and no error.
    odd = _draft(
        url,
        prop,
        human,
        "REFUND",
        "refunds.create",
        {"variant": "USD", "amount_usd_cents": "five", "customer_id": "not-an-id"},
    )

    page = _approvals(prop, human, FINANCIAL_APPROVE_CAPABILITY)
    assert set(page) == {"business_date", "waiting", "decided_today"}
    waiting = _by_id(page["waiting"])
    ours = [str(draft) for draft in (refund, kept, moved, charge, odd)]
    assert [item["draft_id"] for item in page["waiting"] if item["draft_id"] in ours] == ours
    assert waiting[str(refund)]["summary"] == {
        "variant": "CREDIT_CUSTOMER",
        "amount_usd_cents": 500,
        "direction": "OUT",
        "customer_id": str(tenant),
        "customer_name": "Primary Lease Tenant",
        "lease_id": None,
        "reservation_id": None,
        "deposit_type": None,
        "unit_id": None,
        "unit_number": None,
        "prepared_by_name": "Lease Service Actor",
        "decided_by_name": None,
    }
    assert waiting[str(refund)]["state"] == "PENDING"
    assert waiting[str(kept)]["summary"]["direction"] == "KEPT"
    assert waiting[str(kept)]["summary"]["amount_usd_cents"] == 30_000
    move = waiting[str(moved)]["summary"]
    assert move["direction"] == "INTERNAL" and move["amount_usd_cents"] == 1_200
    assert move["customer_name"] == "Additional Lease Signer"
    assert move["unit_id"] == str(unit) and move["unit_number"].startswith("LS-")
    assert waiting[str(charge)]["summary"]["amount_usd_cents"] == 2_500
    assert waiting[str(charge)]["summary"]["direction"] == "INTERNAL"
    assert waiting[str(odd)]["summary"]["amount_usd_cents"] is None
    assert waiting[str(odd)]["summary"]["customer_id"] is None

    # A reader sees only the kinds prepared under a capability it holds.
    refunds_only = _by_id(_approvals(prop, human, "refunds.create")["waiting"])
    assert str(refund) in refunds_only and str(kept) not in refunds_only

    # A decided draft leaves the waiting list and shows under decided today.
    _service().reject(
        prop,
        refund,
        "Paid back at the desk instead",
        actor=actor(human, prop, FINANCIAL_APPROVE_CAPABILITY),
    )
    after = _approvals(prop, human, FINANCIAL_APPROVE_CAPABILITY)
    assert str(refund) not in _by_id(after["waiting"])
    decided = _by_id(after["decided_today"])[str(refund)]
    assert decided["state"] == "REJECTED"
    assert decided["decision"]["reason"] == "Paid back at the desk instead"
    assert decided["summary"]["amount_usd_cents"] == 500
    assert decided["summary"]["decided_by_name"] == "Lease Service Actor"


def test_the_read_needs_an_active_person_and_only_the_read_is_granted(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, *_ = _setup(url)
    with psycopg.connect(runtime_database_url()) as connection:
        try:
            connection.execute(
                f"SELECT {FUNCTION.split('(')[0]}(%s,%s,%s)", (prop, uuid4(), ["refunds.create"])
            )
        except psycopg.Error as exc:
            assert exc.sqlstate == "42501"
        else:
            raise AssertionError("an unknown actor read the drafts")
    with psycopg.connect(url) as connection:
        granted = {
            name: connection.execute(
                "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE')", (name,)
            ).fetchone()
            for name in (
                FUNCTION,
                "app.financial_draft_summary(app.financial_drafts)",
                "app.draft_uuid(text)",
            )
        }
    assert granted == {
        FUNCTION: (True,),
        "app.financial_draft_summary(app.financial_drafts)": (False,),
        "app.draft_uuid(text)": (False,),
    }
    del human
