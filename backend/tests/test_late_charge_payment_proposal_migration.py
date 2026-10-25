"""Real PostgreSQL coverage of the late-payment charge in the payment proposal (V1-056 slice
11g-4; DL-076 answer 5).

Money pays oldest Due Date first, and a late-payment charge is paid right after its own Invoice,
before newer Invoices. Only a payer's own Payment with nothing named gets charge targets; a
third-party or named Payment is proposed as before.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from payment_test_support import seed_payment
from property_rental.payment_allocation import (
    AllocationConflictError,
    PostAllocationsCommand,
    ReverseAllocationCommand,
)
from test_automatic_late_payment_charge_migration import (
    backdate_issue,
    clear_runs,
    due_of,
    moment,
    record,
    seed_last_run,
)
from test_final_settlement_migration import one
from test_invoice_migration import create_recurring_rent_invoice
from test_late_payment_charge_reduction_migration import charged, pay_charge, position, reduce
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import service as allocations

POLICY = "DUE_ISSUED_NUMBER_ID_CHARGE_AFTER_INVOICE/RENT_SERVICE_SOURCE_ORDER"
OLD_POLICY = "DUE_ISSUED_NUMBER_ID/RENT_SERVICE_SOURCE_ORDER"
RENT = 80_000
CHARGE = 8_000


@pytest.fixture(autouse=True)
def no_pass_yet(migrated_database_url: str) -> Iterator[None]:
    clear_runs(migrated_database_url)
    yield
    clear_runs(migrated_database_url)


def two_months(url: str) -> dict[str, Any]:
    """An unpaid Rent Invoice of 800.00 with its charge of 80.00, and the next month's unpaid
    Rent Invoice of the same Lease (no charge)."""
    case = charged(url, 20)
    period = (case["due"].replace(day=1) + timedelta(days=32)).replace(day=1)
    with psycopg.connect(url) as connection:
        later, _ = create_recurring_rent_invoice(
            connection,
            actor_id=case["human"],
            customer_id=case["customer"],
            lease_id=case["lease"],
            period_start=period,
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    backdate_issue(url, later, moment(due_of(period)) - timedelta(days=10))
    return {**case, "later": later}


def payment(case: dict[str, Any], amount: int, **kinds: Any) -> UUID:
    with psycopg.connect(case["url"]) as connection:
        return seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=kinds.pop("payer", case["customer"]),
            amount=amount,
            **kinds,
        )


def proposal(case: dict[str, Any], paid_by: UUID) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        allocations().proposal(
            case["prop"], paid_by, actor=allocation_actor(case["human"], case["prop"])
        ),
    )


def targets(found: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Each target as (kind, id, amount)."""
    return [
        ("INVOICE", target["invoice_id"], target["amount_usd_cents"])
        if "invoice_id" in target
        else ("CHARGE", target["late_payment_charge_id"], target["amount_usd_cents"])
        for target in found["targets"]
    ]


def post(case: dict[str, Any], paid_by: UUID, found: dict[str, Any]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        allocations().post(
            case["prop"],
            paid_by,
            PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": found}),
            actor=allocation_actor(case["human"], case["prop"]),
        ),
    )


def status(url: str, invoice: UUID) -> str:
    return str(one(url, "SELECT status FROM app.invoices WHERE id=%s", invoice)[0])


def test_a_payer_s_own_payment_pays_the_charge_right_after_its_invoice(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    paid_by = payment(case, 2 * RENT + CHARGE + 2_000)
    found = proposal(case, paid_by)
    assert targets(found) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("CHARGE", str(case["charge"]), CHARGE),
        ("INVOICE", str(case["later"]), RENT),
    ]
    assert found["policy"] == POLICY
    assert found["unallocated_after_usd_cents"] == 2_000
    charge_target = found["targets"][1]
    assert charge_target == {
        "late_payment_charge_id": str(case["charge"]),
        "target_customer_id": str(case["customer"]),
        "source_invoice_id": str(case["invoice"]),
        "due_date": found["targets"][0]["due_date"],
        "issued_at": found["targets"][0]["issued_at"],
        "invoice_number": found["targets"][0]["invoice_number"],
        "sequence": 2,
        "outstanding_usd_cents": CHARGE,
        "amount_usd_cents": CHARGE,
    }

    posted = post(case, paid_by, found)
    assert posted["available_usd_cents"] == 2_000
    assert position(url, case["charge"]) == (CHARGE, 0)
    assert status(url, case["invoice"]) == "PAID"
    assert status(url, case["later"]) == "PAID"
    row = one(
        url,
        "SELECT allocation.target_kind,allocation.proposal_batch_id,"
        "allocation.between_invoice_basis,allocation.proposal_trace IS NULL,"
        "detail.calculation_trace "
        "FROM app.payment_allocations allocation "
        "JOIN app.payment_allocation_details detail ON detail.payment_allocation_id=allocation.id "
        "WHERE allocation.payment_id=%s AND allocation.late_payment_charge_id=%s",
        paid_by,
        case["charge"],
    )
    assert row[:4] == ("LATE_PAYMENT_CHARGE", None, "DIRECT_LATE_PAYMENT_CHARGE", True)
    assert row[4] == {
        "designation_reference": None,
        "proposal_batch_id": found["proposal_batch_id"],
        "proposal_sequence": 2,
    }
    # The Invoice allocations keep the batch and the confirmed proposal as their trace.
    batch = one(
        url,
        "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s "
        "AND proposal_batch_id=%s AND target_kind='INVOICE' AND proposal_trace IS NOT NULL",
        paid_by,
        found["proposal_batch_id"],
    )
    assert batch == (2,)


def test_money_that_runs_out_pays_part_of_the_charge_before_any_newer_invoice(
    migrated_database_url: str,
) -> None:
    case = two_months(migrated_database_url)
    paid_by = payment(case, RENT + 5_000)
    found = proposal(case, paid_by)
    assert targets(found) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("CHARGE", str(case["charge"]), 5_000),
    ]
    post(case, paid_by, found)
    assert position(migrated_database_url, case["charge"]) == (CHARGE, CHARGE - 5_000)
    assert status(migrated_database_url, case["later"]) == "UNPAID"


def test_the_charge_of_a_paid_invoice_comes_before_newer_invoices(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    first = payment(case, RENT)
    found = proposal(case, first)
    assert targets(found) == [("INVOICE", str(case["invoice"]), RENT)]
    post(case, first, found)
    assert status(url, case["invoice"]) == "PAID"

    second = payment(case, CHARGE + 2_000)
    found = proposal(case, second)
    assert targets(found) == [
        ("CHARGE", str(case["charge"]), CHARGE),
        ("INVOICE", str(case["later"]), 2_000),
    ]
    post(case, second, found)
    assert position(url, case["charge"]) == (CHARGE, 0)


def test_a_third_party_or_named_payment_is_proposed_as_before(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    payer = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Third-party payer',%s,%s)",
            (payer, case["human"], case["human"]),
        )
    third = payment(
        case,
        2 * RENT + CHARGE,
        payer=payer,
        scope="THIRD_PARTY_IDENTIFIED",
        lease_id=case["lease"],
    )
    found = proposal(case, third)
    assert targets(found) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("INVOICE", str(case["later"]), RENT),
    ]
    assert found["policy"] == OLD_POLICY

    named = payment(case, RENT + CHARGE, invoice_id=case["later"])
    found = proposal(case, named)
    assert targets(found) == [("INVOICE", str(case["later"]), RENT)]
    assert found["policy"] == OLD_POLICY


def test_a_proposal_whose_charge_was_paid_meanwhile_is_refused_and_writes_nothing(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    paid_by = payment(case, RENT + CHARGE)
    found = proposal(case, paid_by)
    pay_charge(case, 3_000)
    with pytest.raises(AllocationConflictError):
        post(case, paid_by, found)
    assert one(
        url, "SELECT count(*) FROM app.payment_allocations WHERE payment_id=%s", paid_by
    ) == (0,)
    assert targets(proposal(case, paid_by))[1] == ("CHARGE", str(case["charge"]), CHARGE - 3_000)


def test_a_payment_that_names_the_charge_or_a_reduced_or_waived_charge_is_proposed_right(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    named = payment(case, CHARGE, late_payment_charge_id=case["charge"])
    found = proposal(case, named)
    assert targets(found) == []
    assert found["policy"] == OLD_POLICY

    reduce(case, 3_000)
    paid_by = payment(case, RENT + CHARGE)
    assert targets(proposal(case, paid_by)) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("CHARGE", str(case["charge"]), 3_000),
        ("INVOICE", str(case["later"]), CHARGE - 3_000),
    ]
    reduce(case, 0)
    assert targets(proposal(case, paid_by)) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("INVOICE", str(case["later"]), CHARGE),
    ]


def test_each_charge_follows_its_own_invoice(migrated_database_url: str) -> None:
    url = migrated_database_url
    case = two_months(url)
    later_due = one(url, "SELECT due_date FROM app.invoices WHERE id=%s", case["later"])[0]
    seed_last_run(url, case["prop"], case["service"], later_due)
    outcome = record(case, case["later"])
    assert outcome["outcome"] == "CHARGED"
    later_charge = str(outcome["charge"]["id"])
    paid_by = payment(case, 2 * (RENT + CHARGE))
    assert targets(proposal(case, paid_by)) == [
        ("INVOICE", str(case["invoice"]), RENT),
        ("CHARGE", str(case["charge"]), CHARGE),
        ("INVOICE", str(case["later"]), RENT),
        ("CHARGE", later_charge, CHARGE),
    ]


def test_a_charge_allocation_from_a_proposal_is_reversed_like_a_direct_one(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = two_months(url)
    paid_by = payment(case, RENT + CHARGE)
    post(case, paid_by, proposal(case, paid_by))
    allocation = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.payment_allocations WHERE payment_id=%s "
                "AND late_payment_charge_id=%s",
                paid_by,
                case["charge"],
            )[0]
        )
    )
    allocations().reverse_allocation(
        case["prop"],
        allocation,
        ReverseAllocationCommand(uuid4(), "Posted to the wrong charge by mistake"),
        actor=allocation_actor(case["human"], case["prop"]),
    )
    assert position(url, case["charge"]) == (CHARGE, CHARGE)
    assert status(url, case["invoice"]) == "PAID"
    # The reversed value is available again and the charge is proposed again.
    assert targets(proposal(case, paid_by)) == [("CHARGE", str(case["charge"]), CHARGE)]
