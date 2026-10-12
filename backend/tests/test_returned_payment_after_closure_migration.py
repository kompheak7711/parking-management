"""A returned Payment used on a closed Lease after closure (V1-056 sub-slice 10e-4).

Owner answer (c) to Q-2026-10-11-81 point 3 and the owner answer to Q-2026-10-11-82: a Payment
that no closed Final Settlement relied on, but that names a closed Settlement's Lease (with no time
or use condition) or whose money is used on it (such uses came after closure, since that Settlement
did not rely on them), is returned through the RETURNED_PAYMENT correction of that Settlement. Its
records are reversed as linked records, so the debt comes back on its obligations and stays with
their Customers (BR-SETTLE-016); each Refund paid from its value is charged back to the person who
received it by the sub-slice 10e-1c rules: an EXTRA_CHARGE on that Lease when the Refund's charge
goes on it (for a Payment Refund, when the Payment names the Lease) and that person is its signed
Customer. When no one was refunded no charge is written: the reversed allocation puts the debt
back on the Customer whose debt the Payment paid. The PAYMENT_RETURN draft keeps refusing such a
Payment and names the correction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.final_settlement import FinalSettlementConflictError
from property_rental.payment_allocation import ReverseAllocationCommand
from property_rental.refund import CreateUsdRefundCommand
from refund_test_support import create_usd_refund
from test_credit_application_migration import designated as designated_credit
from test_credit_migration import actor, credit_id, recognize
from test_credit_migration import service as credits
from test_final_settlement_confirm_migration import invoice_of
from test_final_settlement_migration import one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import allocation_ids, person, wrong_allocation
from test_payment_return_migration import reconciled, status
from test_payment_return_recovery_migration import (
    CLOSED,
    NAMES_CORRECTION,
    charge,
    due_days,
    links,
    planned,
    recovery_row,
    return_refused,
    written,
)
from test_refund_service_migration import refund_id
from test_refund_service_migration import service as refund_service
from test_settlement_correction_migration import settlement_row
from test_settlement_extra_charge_migration import cause
from test_settlement_real_path_migration import extra_charge_line, two_signer_kept_case
from test_settlement_return_reversal_migration import PAYBACK_REVISION, app_catalog
from test_settlement_returned_payment_migration import (
    NOT_RELIED,
    ONLY_OTHER,
    closed_case,
    command,
    confirm,
    payload,
    record,
)

REVISION = "20261201_127"
INCOMPLETE = "The returned-Payment correction source is incomplete"
PATCHED = {
    "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
    "app.assert_payment_return_recoveries_allowed(jsonb,uuid)",
}


def lease_payment(case: dict[str, Any], payer: UUID, amount: int) -> UUID:
    """A Payment received after closure that names the closed Lease (its payer may pay any
    Invoice of that Lease)."""
    with psycopg.connect(case["url"]) as connection:
        return seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=payer,
            amount=amount,
            scope="THIRD_PARTY_IDENTIFIED",
            lease_id=case["lease"],
        )


def refund_part(case: dict[str, Any], payment: UUID, amount: int) -> UUID:
    """A Refund of the Payment's unallocated value to its payer."""
    created = create_usd_refund(
        refund_service(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, amount, "Return the unused part"),
        actor=actor(case["human"], case["prop"], "refunds.create"),
    )
    return refund_id(created)


def allocate(case: dict[str, Any], payment: UUID, line: UUID, amount: int) -> UUID:
    posted = allocations().post(
        case["prop"],
        payment,
        designated(invoice_of(case["url"], line), line, amount),
        actor=person(case["human"], case["prop"], "payments.allocate"),
    )
    return allocation_ids(posted)[0]


def customer_payment(case: dict[str, Any], amount: int) -> UUID:
    """A Payment of the Lease's Customer received after closure that names no Lease."""
    with psycopg.connect(case["url"]) as connection:
        return seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=case["customer"],
            amount=amount,
        )


def reversal_links(url: str, correction: object) -> tuple[Any, ...]:
    """How many allocation, Credit application, Credit and Payment reversals the correction
    links."""
    return one(
        url,
        "SELECT count(*) FILTER (WHERE payment_allocation_reversal_id IS NOT NULL),"
        "count(*) FILTER (WHERE credit_application_reversal_id IS NOT NULL),"
        "count(*) FILTER (WHERE customer_credit_reversal_id IS NOT NULL),"
        "count(*) FILTER (WHERE payment_reversal_id IS NOT NULL) "
        "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s",
        UUID(str(correction)),
    )


def lease_invoices(case: dict[str, Any]) -> int:
    return int(
        one(case["url"], "SELECT count(*) FROM app.invoices WHERE lease_id=%s", case["lease"])[0]
    )


def test_the_q81_payment_is_returned_through_the_correction_of_the_closed_settlement(
    migrated_database_url: str,
) -> None:
    """The owner's Q-2026-10-11-81 example to the cent: after closure the Customer sends $900
    naming the closed Lease and $300 of it is refunded; the transfer bounces. No closed Settlement
    relied on the Payment, so the PAYMENT_RETURN draft refuses it and names the correction; the
    RETURNED_PAYMENT correction of that Settlement records it (its money is used on the Lease) and
    charges the $300 back to the Customer by an EXTRA_CHARGE on that Lease (linked, issued, the
    Property's Due Date days); the Refund's net is 0 and the Payment is reversed. The Settlement
    row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    prop, customer, lease = case["prop"], case["customer"], case["lease"]
    late = lease_payment(case, customer, 90_000)
    refund = refund_part(case, late, 30_000)
    before = settlement_row(url, case["settlement"])
    assert return_refused(prop, case["human"], late) == ("55000", NAMES_CORRECTION)
    draft = record(case, command(case, late))
    source = payload(url, draft)["source"]
    assert (source["used_on_lease"], source["relied_on"]) == (True, [])
    [plan] = source["recoveries"]
    assert planned(plan) == (
        "PAYMENT",
        str(customer),
        str(lease),
        30_000,
        "CLOSED_SETTLEMENT_LEASE",
        False,
        False,
    )
    assert (plan["refund_id"], plan["closed_final_settlement_id"]) == (
        str(refund),
        str(case["settlement"]),
    )
    result = confirm(case, draft)
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(customer), str(lease), 30_000, "EXTRA_CHARGE")
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        30_000,
        due_days(url, prop),
    )
    assert recovery_row(url, recovered["refund_correction_id"]) == (
        "RECOVERED_BY_CHARGE",
        30_000,
        30_000,
        0,
        "financial.approve",
        recovered["authorized_nonrecurring_obligation_id"],
    )
    assert links(url, result["settlement_correction"]["id"]) == (1, 1, 1)
    assert status(url, late) == "REVERSED"
    assert one(
        url,
        "SELECT settlement_correction_id::text FROM app.payment_returns WHERE payment_id=%s",
        late,
    ) == (result["settlement_correction"]["id"],)
    assert reversal_links(url, result["settlement_correction"]["id"]) == (0, 0, 0, 1)
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, customer)


def test_a_signers_payment_of_the_primary_tenants_charge_is_returned_and_the_signer_pays_back(
    migrated_database_url: str,
) -> None:
    """The owner's Q-2026-10-11-82 case on a really closed two-Signer Lease: after closure an
    EXTRA_CHARGE bills the Primary Tenant A $600; the second Signer B sends $900 naming the Lease;
    $600 pays A's charge and the $300 left is refunded to B; the transfer bounces. The correction
    reverses the allocation (A owes the $600 again, no second charge) and charges B, who received
    the $300, by an EXTRA_CHARGE of $300 on the Lease; the Payment is reversed; both ledgers
    reconcile and the Settlement row is unchanged."""
    url = migrated_database_url
    case = two_signer_kept_case(url)
    prop, lease, tenant, signer = case["prop"], case["lease"], case["customer"], case["co_signer"]
    line = extra_charge_line(case, amount_usd_cents=60_000)
    assert one(url, "SELECT customer_id FROM app.invoices WHERE id=%s", invoice_of(url, line)) == (
        tenant,
    )
    payment = lease_payment(case, signer, 90_000)
    allocate(case, payment, line, 60_000)
    refund_part(case, payment, 30_000)
    assert outstanding(url, line) == 0
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    assert (source["used_on_lease"], source["relied_on"]) == (True, [])
    [plan] = source["recoveries"]
    assert planned(plan) == (
        "PAYMENT",
        str(signer),
        str(lease),
        30_000,
        "CLOSED_SETTLEMENT_LEASE",
        False,
        False,
    )
    result = confirm(case, draft)
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(signer), str(lease), 30_000, "EXTRA_CHARGE")
    assert charge(url, recovered["invoice_id"]) == (
        signer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        30_000,
        due_days(url, prop),
    )
    correction = result["settlement_correction"]["id"]
    assert links(url, correction) == (1, 1, 1)
    assert reversal_links(url, correction) == (1, 0, 0, 1)
    assert outstanding(url, line) == 60_000
    assert status(url, payment) == "REVERSED"
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, tenant, signer)


def test_with_nothing_refunded_the_debt_comes_back_and_no_charge_is_written(
    migrated_database_url: str,
) -> None:
    """The second case of the owner answer to Q-2026-10-11-82: the same Payment of B pays $600 of
    A's charge and nothing is refunded. The correction reverses the allocation, so A owes the $600
    again on the same Invoice; no recovery and no new Invoice are written; the Payment is
    reversed and its $300 unallocated value goes with it."""
    url = migrated_database_url
    case = two_signer_kept_case(url)
    tenant, signer = case["customer"], case["co_signer"]
    line = extra_charge_line(case, amount_usd_cents=60_000)
    payment = lease_payment(case, signer, 90_000)
    allocate(case, payment, line, 60_000)
    assert outstanding(url, line) == 0
    invoices = lease_invoices(case)
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    assert (source["used_on_lease"], source["relied_on"], source["recoveries"]) == (True, [], [])
    result = confirm(case, draft)
    assert result["recoveries"] == []
    correction = result["settlement_correction"]["id"]
    assert links(url, correction) == (0, 0, 0)
    assert reversal_links(url, correction) == (1, 0, 0, 1)
    assert outstanding(url, line) == 60_000
    assert lease_invoices(case) == invoices
    assert status(url, payment) == "REVERSED"
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, tenant, signer)


def test_a_payment_allocated_on_the_lease_after_closure_is_returned_and_a_reversed_one_is_not(
    migrated_database_url: str,
) -> None:
    """The allocation branch of `used_on_lease` (review round 1): a Payment of the Customer that
    names no Lease, allocated after closure to an EXTRA_CHARGE Invoice of the closed Lease, is
    used on that Lease; its correction reverses the allocation (the 40,000 is owed again) and the
    Payment, both linked. A second such Payment whose allocation was reversed before is not used
    on the Lease: the correction refuses it and writes nothing."""
    url = migrated_database_url
    case = closed_case(url)
    line = extra_charge_line(case, amount_usd_cents=40_000)
    payment = customer_payment(case, 40_000)
    allocate(case, payment, line, 40_000)
    assert outstanding(url, line) == 0
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    assert (source["used_on_lease"], source["relied_on"], source["recoveries"]) == (True, [], [])
    result = confirm(case, draft)
    assert reversal_links(url, result["settlement_correction"]["id"]) == (1, 0, 0, 1)
    assert (outstanding(url, line), status(url, payment)) == (40_000, "REVERSED")
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, case["customer"])
    undone = customer_payment(case, 40_000)
    allocations().reverse_allocation(
        case["prop"],
        allocate(case, undone, line, 40_000),
        ReverseAllocationCommand(uuid4(), "Posted on the wrong Invoice"),
        actor=person(case["human"], case["prop"], "payments.allocations.reverse"),
    )
    assert outstanding(url, line) == 40_000
    drafts = one(url, "SELECT count(*) FROM app.financial_drafts")
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(case, command(case, undone))
    assert cause(refused) == ("55000", NOT_RELIED)
    assert one(url, "SELECT count(*) FROM app.financial_drafts") == drafts
    assert status(url, undone) == "RECEIVED"


def test_a_credit_applied_on_the_lease_after_closure_is_returned_through_the_correction(
    migrated_database_url: str,
) -> None:
    """The Credit-application branch of `used_on_lease` (review round 1): a Payment of the
    Customer that names no Lease becomes a 25,000 Credit with the payer's consent; after closure
    the Credit pays an EXTRA_CHARGE of the closed Lease. The correction reverses the Credit
    application (the 25,000 is owed again), the Credit and the Payment, each linked; the Settlement
    row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human = case["prop"], case["human"]
    payment = customer_payment(case, 25_000)
    credit = credit_id(recognize(prop, payment, human, 25_000))
    line = extra_charge_line(case, amount_usd_cents=25_000)
    credits().apply(
        prop,
        credit,
        designated_credit(invoice_of(url, line), line, 25_000),
        actor=actor(human, prop, "credits.apply"),
    )
    assert outstanding(url, line) == 0
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    assert (source["used_on_lease"], source["relied_on"], source["recoveries"]) == (True, [], [])
    result = confirm(case, draft)
    assert reversal_links(url, result["settlement_correction"]["id"]) == (0, 1, 1, 1)
    assert (outstanding(url, line), status(url, payment)) == (25_000, "REVERSED")
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, case["customer"])


def test_a_payment_used_only_on_another_lease_is_still_refused(
    migrated_database_url: str,
) -> None:
    """A Payment of the same Property that names no Lease and pays an Invoice of another, open
    Lease is not used on the closed Lease: the correction still refuses it (the PAYMENT_RETURN
    draft returns it), and nothing is written."""
    url = migrated_database_url
    case = closed_case(url)
    other = wrong_allocation(url)
    assert other.prop == case["prop"]
    drafts = one(url, "SELECT count(*) FROM app.financial_drafts")
    with pytest.raises(FinalSettlementConflictError) as refused:
        record(case, command(case, other.payment))
    assert cause(refused) == ("55000", NOT_RELIED)
    assert one(url, "SELECT count(*) FROM app.financial_drafts") == drafts
    assert status(url, other.payment) == "RECEIVED"


def test_the_refusal_lets_through_only_a_payment_used_on_this_lease(
    migrated_database_url: str,
) -> None:
    """The correction's check on hand-built sources: with no closed Settlement relying on the
    Payment, it passes only when `used_on_lease` is true or a planned recovery is charged on this
    Settlement's Lease; false, missing or null `used_on_lease` and a recovery on another closed
    Settlement's Lease are refused; another Settlement's reliance is still refused first; a
    Payment used on this Lease with a recovery on another closed Lease is refused by the recovery
    check (the known limit). Fail closed (review round 1): only a JSON true flag counts, and a
    source without a reliance list is refused."""
    url = migrated_database_url
    settlement, other, lease = str(uuid4()), str(uuid4()), str(uuid4())
    recovery = {
        "source_kind": "PAYMENT",
        "source_id": str(uuid4()),
        "recipient_customer_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "amount_usd_cents": 100,
        "charge": "CLOSED_SETTLEMENT_LEASE",
        "closed_final_settlement_id": settlement,
        "reservation_outcome": False,
        "shared_deposit": False,
    }
    base: dict[str, Any] = {
        "payment": {"status": "RECEIVED", "refunded_usd_cents": 0},
        "relied_on": [],
        "recoveries": [],
        "credits": [],
        "deposits": [],
        "forfeitures": [],
        "deposit_applications": [],
        "receipts": [],
        "pending_drafts": [],
    }
    refunded = {"payment": {"status": "RECEIVED", "refunded_usd_cents": 100}}

    def check(**changes: Any) -> tuple[Any, Any]:
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "SELECT app.assert_settlement_returned_payment_allowed(%s,%s,%s)",
                    (settlement, lease, Jsonb({**base, **changes})),
                )
            except psycopg.Error as refused:
                return refused.sqlstate, refused.diag.message_primary
        return None, None

    assert check(used_on_lease=True) == (None, None)
    assert check(used_on_lease=False) == ("55000", NOT_RELIED)
    assert check() == ("55000", NOT_RELIED)
    assert check(used_on_lease=None) == ("55000", NOT_RELIED)
    # Fail closed (review round 1): only a JSON true counts, and a source without a reliance list
    # is refused.
    for loose in ("true", "t", 1):
        assert check(used_on_lease=loose) == ("55000", NOT_RELIED), loose
    unlisted = {key: item for key, item in base.items() if key != "relied_on"}
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as incomplete:
            connection.execute(
                "SELECT app.assert_settlement_returned_payment_allowed(%s,%s,%s)",
                (settlement, lease, Jsonb({**unlisted, "used_on_lease": True})),
            )
    assert (incomplete.value.sqlstate, incomplete.value.diag.message_primary) == (
        "55000",
        INCOMPLETE,
    )
    # A reliance list that is not a list cannot be read at all (22023), also fail closed.
    assert check(used_on_lease=True, relied_on=None)[0] == "22023"
    assert check(used_on_lease=True, relied_on={})[0] == "22023"
    assert check(**refunded, recoveries=[recovery]) == (None, None)
    assert check(**refunded, used_on_lease=False, recoveries=[recovery]) == (None, None)
    elsewhere = {**recovery, "closed_final_settlement_id": other}
    assert check(**refunded, recoveries=[elsewhere]) == ("55000", NOT_RELIED)
    assert check(**refunded, used_on_lease=True, recoveries=[elsewhere]) == ("55000", CLOSED)
    relied = [{"kind": "PAYMENT_ALLOCATION", "id": str(uuid4()), "final_settlement_id": other}]
    assert check(used_on_lease=True, relied_on=relied) == ("55000", ONLY_OTHER)


def test_returned_payment_after_closure_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Migration 127 adds no function, constraint or trigger; it changes only the three listed
    functions (privileges, owner and settings kept; each patched body is exactly the old one with
    the module's replacements), and it is forward-only. The financial role still runs none of
    the three; the source and the check stay SECURITY DEFINER with the fixed search path."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in PATCHED:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == PAYBACK_REVISION
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("returned_payment_after_closure") as temporary:
        alembic_command.upgrade(config, PAYBACK_REVISION)
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
