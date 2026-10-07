"""Post-settlement correction: Refund of a Deposit-paid charge (V1-056 sub-slice 10c-2a-3).

The REFUND correction of sub-slice 10c-1b also corrects a line a Deposit application paid when the
Final Settlement closed. The release takes whole sources newest first across Deposit applications,
Payment allocations and Credit applications (owner answer 2 to Q-2026-10-07-41); a released Deposit
application is reversed and its value goes back to its Deposit, never to Customer Credit. Every
REFUND correction then runs the shared DL-032 step of sub-slice 10c-2a-2: released Credit first
pays its own Customer's open debt on the Lease (answer 2 to Q-2026-10-07-42), released Deposit value
pays the Lease's open debt in the DL-032 order, and only the rest is refunded. The 8a-1 refusal lets
the correction's own Adjustment through (answer to Q-2026-10-07-46); a remaining Pet Deposit step at
a BR-DEP-027 termination needs a new Customer choice (answer 3 to Q-2026-10-07-44); the confirm
locks the Lease row in the 8e-3 order (answer 4 to Q-2026-10-07-44). Every Settlement here closes
through the real confirm (owner answer to Q-2026-10-07-47).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import make_conninfo

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.billing import PostgresRentBillingService
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.settlement_correction import RecordRefundCorrectionCommand
from rent_month_test_support import bill_unbilled_rent_months
from test_billing_service_migration import add_service, authenticated, initial_command
from test_customer_ledger_migration import assert_reconciled
from test_deposit_application_reversal_migration import begin, reverse
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import (
    CHOICE,
    CREDIT_FIRST,
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    leaving_case,
    record,
)
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import (
    held,
    one,
    outstanding,
    pet_deposit,
    preparer,
    start,
    today,
)
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_migration import (
    LINK,
    approver,
    correction_draft,
    credit_adjustment,
    invoice_of,
    settlement_row,
)
from test_settlement_correction_plan_migration import (
    POST_PLAN,
    blocked_by,
    closed_case,
    failure,
    main_plan,
    overlay,
    plan_draft,
    released_overlay,
)
from test_settlement_correction_plan_migration import release as release_by_hand
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_refund_correction_migration import unpaid_charge
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line

CHANGED = (
    "app.refuse_deposit_applied_obligation_change()",
    "app.settlement_refund_input(jsonb)",
    "app.settlement_refund_line_sources(uuid,uuid)",
    "app.settlement_refund_plan(uuid,uuid,jsonb)",
    "app.record_settlement_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.settlement_refund_result(uuid)",
    "app.confirm_settlement_refund(uuid,uuid,uuid,text)",
    "app.lock_settlement_correction_plan(uuid)",
)
INTERNAL = (
    "app.settlement_correction_adjustment_allowed(uuid,uuid,uuid)",
    "app.settlement_refund_overlay(jsonb,uuid)",
)
REASON = "The window latch was charged twice and paid"
NOTE = "Cash handed over at the front desk"
DEPOSIT_APPLIED = "A Deposit application paid this obligation at Final Settlement"
NEW_CHOICE = (
    "Primary Tenant agreed on 2026-10-07, by signed note, that the Pet Deposit pays this debt"
)
EFFECTS = (
    "payment_allocation_reversal_id",
    "credit_application_reversal_id",
    "deposit_application_reversal_id",
    "invoice_adjustment_id",
    "payment_allocation_id",
    "customer_credit_application_id",
    "deposit_application_id",
    "refund_id",
)
ADJUSTMENT = (
    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
    "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
    "VALUES (%s,%s,%s,'CREDIT',%s,'settlement-correction:test',%s,"
    "app.credit_excess_instant(%s,NULL),%s,'financial.approve')"
)


def command(
    case: dict[str, Any], line: UUID, amount: int, *steps: Any, **changes: Any
) -> RecordRefundCorrectionCommand:
    return replace(
        RecordRefundCorrectionCommand(
            uuid4(),
            case["settlement"],
            invoice_of(case["url"], line),
            line,
            amount,
            case["cash"],
            NOTE,
            REASON,
            tuple(steps),
        ),
        **changes,
    )


def record_refund(case: dict[str, Any], refund: RecordRefundCorrectionCommand) -> UUID:
    found = corrections().record_refund(
        case["prop"], refund, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm_refund(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_refund(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def effects(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(EFFECTS)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    return [next(name for name, value in zip(EFFECTS, row, strict=True) if value) for row in rows]


def active(url: str, application: object) -> bool:
    return not bool(
        one(
            url,
            "SELECT EXISTS(SELECT 1 FROM app.deposit_application_reversals "
            "WHERE deposit_application_id=%s)",
            application,
        )[0]
    )


def application_on(url: str, case: dict[str, Any], stage: str, line: UUID) -> UUID:
    return UUID(
        str(
            one(
                url,
                "SELECT id FROM app.deposit_applications WHERE final_settlement_id=%s "
                "AND application_stage=%s AND invoice_line_id=%s",
                case["settlement"],
                stage,
                line,
            )[0]
        )
    )


def credits_of(url: str, customer: UUID) -> int:
    return int(
        one(url, "SELECT count(*) FROM app.customer_credits WHERE customer_id=%s", customer)[0]
    )


def test_a_deposit_paid_line_is_refunded_after_the_released_value_pays_the_open_debt(
    migrated_database_url: str,
) -> None:
    """DL-032, BR-SETTLE-008, BR-SETTLE-013 and owner answers 1 and 2 to Q-2026-10-07-41: a 4,000
    Refund of the other Damage line, which the Settlement paid with 400 of Credit, 10,000 of the
    Security Deposit and 2,100 of the remaining Pet Deposit, reverses the two Deposit applications
    newest first (the Pet Deposit's 2,100, then the Security Deposit's 10,000), writes the linked
    credit Adjustment, and then runs the step: the Customer's own Credit (300) first, the Security
    Deposit pays the 8,100 the line still owes less that Credit, and only the rest of each Deposit
    is refunded. The released Deposit value never becomes Customer Credit; the Settlement row is
    unchanged; the ledger reconciles; an exact repeat replays."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    security, pet, line, customer = (
        case["security"],
        case["pet"],
        case["other_line"],
        case["customer"],
    )
    pet_rest = application_on(url, case, "PET_REMAINDER_EXPLICIT", line)
    security_application = application_on(url, case, "SECURITY_EXPLICIT", line)
    before = settlement_row(url, case["settlement"])
    credits_before = credits_of(url, customer)
    refund = command(
        case,
        line,
        4_000,
        SettlementCreditStep(case["new_credit"], LINE, line, 300),
        SettlementDepositStep(SECURITY, security, LINE, line, 7_800),
        settlement_refund(case, "security", 2_200),
        settlement_refund(case, "pet", 2_100),
    )
    # Without a plan for the released Deposit value the step refuses the draft (BR-SETTLE-008).
    with pytest.raises(FinalSettlementConflictError) as unplanned:
        record_refund(case, replace(refund, idempotency_key=uuid4(), steps=()))
    assert cause(unplanned) == (
        "55000",
        "Every remaining Deposit balance must be applied or refunded",
    )
    draft = record_refund(case, refund)
    stored = one(
        url,
        "SELECT payload->'released_sources',payload->'plan_overlay' FROM app.financial_drafts "
        "WHERE id=%s",
        draft,
    )
    assert [
        (
            source["kind"],
            source["id"],
            source["application_usd_cents"],
            source["released_usd_cents"],
        )
        for source in stored[0]
    ] == [
        ("DEPOSIT_APPLICATION", str(pet_rest), 2_100, 2_100),
        ("DEPOSIT_APPLICATION", str(security_application), 10_000, 1_900),
    ]
    assert stored[1] == released_overlay(case)
    result = confirm_refund(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effects(url, correction) == [
        "deposit_application_reversal_id",
        "deposit_application_reversal_id",
        "invoice_adjustment_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "refund_id",
        "refund_id",
    ]
    assert [
        (item["deposit_application_id"], item["amount_usd_cents"])
        for item in result["deposit_application_reversals"]
    ] == [(str(pet_rest), 2_100), (str(security_application), 10_000)]
    [credit_application] = result["credit_applications"]
    assert (credit_application["customer_credit_id"], credit_application["amount_usd_cents"]) == (
        str(case["new_credit"]),
        300,
    )
    [deposit_application] = result["deposit_applications"]
    assert (
        deposit_application["deposit_id"],
        deposit_application["application_stage"],
        deposit_application["amount_usd_cents"],
        deposit_application["application_order"],
    ) == (str(security), "SECURITY_EXPLICIT", 7_800, 4)
    assert result["released_sources"] == []
    assert sorted(
        (paid["source_deposit_id"], paid["amount_usd_cents"], paid["recipient_customer_id"])
        for paid in result["refunds"]
    ) == sorted([(str(security), 2_200, str(customer)), (str(pet), 2_100, str(customer))])
    assert (held(url, security), held(url, pet), outstanding(url, line)) == (0, 0, 0)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line) == (8_500,)
    # Deposit value goes back to the Deposit only: the correction recognized no Credit.
    assert credits_of(url, customer) == credits_before
    assert settlement_row(url, case["settlement"]) == before
    confirmed = one(
        url,
        "SELECT resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction,
    )[0]
    assert confirmed["deposit_application_reversals"] == result["deposit_application_reversals"]
    assert confirmed["credit_application_ids"] == [credit_application["id"]]
    assert confirmed["deposit_application_ids"] == [deposit_application["id"]]
    assert len(confirmed["deposit_refund_ids"]) == 2
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
    assert confirm_refund(case, draft) == result


def test_released_credit_pays_its_own_customer_s_debt_before_any_refund(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-07-42 (an approved change of sub-slice 10c-1b), both cases: a
    Customer with no open debt on the Lease gets the released Credit back as a Refund, as before;
    once that Customer owes a 1,500 charge issued after closure, a Refund correction without a plan
    is refused, and with the plan the released Credit pays that charge first and only the rest
    (500 of 2,000) is refunded."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    customer, invoice = case["customer"], case["initial"]
    rent, _ = rent_line(url, invoice)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", rent)[0] > 2_300

    def allocation_on_rent() -> UUID:
        return UUID(
            str(
                one(
                    url,
                    "SELECT allocation.id FROM app.payment_allocations allocation "
                    "JOIN app.payment_allocation_details detail "
                    "ON detail.payment_allocation_id=allocation.id WHERE detail.invoice_line_id=%s "
                    "AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal "
                    "WHERE reversal.payment_allocation_id=allocation.id) "
                    "ORDER BY allocation.posted_at DESC LIMIT 1",
                    rent,
                )[0]
            )
        )

    # No open debt: the whole released value is refunded, as in sub-slice 10c-1b.
    first = confirm_refund(case, record_refund(case, command(case, rent, 300)))
    [paid] = first["refunds"]
    assert (paid["amount_usd_cents"], paid["recipient_customer_id"]) == (300, str(customer))
    assert first["credit_applications"] == []
    # Open debt: the released Credit pays it first.
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    with pytest.raises(FinalSettlementConflictError) as unplanned:
        record_refund(case, command(case, rent, 2_000))
    assert cause(unplanned) == (
        "55000",
        "Customer Credit the correction releases pays its own Customer's open debt on this Lease "
        "before any Refund",
    )
    released = allocation_on_rent()
    second = confirm_refund(
        case,
        record_refund(
            case,
            command(case, rent, 2_000, SettlementCreditStep(released, LINE, charge_line, 1_500)),
        ),
    )
    [source] = second["released_sources"]
    credit = source["customer_credit_id"]
    [applied] = second["credit_applications"]
    assert (applied["customer_credit_id"], applied["invoice_id"], applied["amount_usd_cents"]) == (
        credit,
        str(charge_invoice),
        1_500,
    )
    [rest] = second["refunds"]
    assert (rest["source_customer_credit_id"], rest["amount_usd_cents"]) == (credit, 500)
    assert one(url, "SELECT app.credit_available_value(%s)", credit) == (0,)
    assert outstanding(url, charge_line) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def paid_elsewhere(url: str, lease: UUID, line: UUID) -> list[tuple[str, Any]]:
    """The active paying sources of every other line of the Lease's Invoices."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT other.id,app.settlement_refund_line_sources(invoice.id,other.id) "
            "FROM app.invoices invoice JOIN app.invoice_lines other ON other.invoice_id=invoice.id "
            "WHERE invoice.lease_id=%s AND other.id<>%s ORDER BY other.id",
            (lease, line),
        ).fetchall()
    return [(str(row[0]), row[1]) for row in rows]


def pet_paid_case(url: str) -> dict[str, Any]:
    """An unpaid-Initial termination (BR-LEASE-005, a BR-DEP-027 termination) with the Security
    Deposit kept: the real closure applies the Pet Deposit's 20,000 to the pet damage (12,500) and,
    by the Customer's choice, to 7,500 of the other Damage line, which owes 5,000 after closure."""
    case = {**leaving_case(url, unpaid_initial=True), "url": url}
    prop, human, pet = case["prop"], case["human"], case["pet"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human), case["security"]
    )
    confirm_settlement(
        case,
        record(
            case,
            (
                SettlementDepositStep(PET_FIRST, pet, LINE, case["pet_line"], 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, case["other_line"], 7_500),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    assert (held(url, pet), outstanding(url, case["other_line"])) == (0, 5_000)
    return case


def test_a_mixed_line_releases_the_newest_payment_before_the_deposit_application(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-07-41 (review round 1): at an unpaid-Initial termination the
    Security Deposit is kept, the Pet Deposit pays the pet damage and, by the Customer's choice,
    7,500 of the other Damage line, and the Customer pays the 5,000 left by a Payment after
    closure. A 6,000 Refund of that line releases whole sources newest first, only until the paid
    part is covered: the Payment allocation (5,000), then 1,000 of the Pet Deposit application,
    which is reversed whole. The released Payment value becomes the Customer's Credit and pays
    that Customer's open debt before the Deposit (owner answer 2 to Q-2026-10-07-42); the Pet
    Deposit pays the rest of the line by a new Customer choice and its last 6,000 is refunded
    while the unpaid Initial Rent stays (BR-DEP-027). No other line changes how it is paid, and
    no Credit is refunded. A plan in which the Pet Deposit pays before that Credit is refused."""
    url = migrated_database_url
    case = pet_paid_case(url)
    prop, human, pet, customer = case["prop"], case["human"], case["pet"], case["customer"]
    line = case["other_line"]
    invoice = invoice_of(url, line)
    pay(url, prop, human, customer, invoice, line, 5_000)
    allocation = UUID(
        str(
            one(
                url,
                "SELECT allocation.id FROM app.payment_allocations allocation "
                "JOIN app.payment_allocation_details detail "
                "ON detail.payment_allocation_id=allocation.id WHERE detail.invoice_line_id=%s",
                line,
            )[0]
        )
    )
    pet_rest = application_on(url, case, "PET_REMAINDER_EXPLICIT", line)
    elsewhere = paid_elsewhere(url, case["lease"], line)
    assert any(sources for _, sources in elsewhere)
    credits_before = credits_of(url, customer)
    # A plan in which the Pet Deposit pays before the released Credit is refused (review round 2).
    with pytest.raises(FinalSettlementConflictError) as deposit_first:
        record_refund(
            case,
            command(
                case,
                line,
                6_000,
                SettlementDepositStep(PET_REST, pet, LINE, line, 6_500),
                settlement_refund(case, "pet", 1_000),
                pet_remainder=replace(CHOICE, customer_choice=NEW_CHOICE),
            ),
        )
    assert cause(deposit_first) == ("55000", CREDIT_FIRST)
    draft = record_refund(
        case,
        command(
            case,
            line,
            6_000,
            SettlementCreditStep(allocation, LINE, line, 5_000),
            SettlementDepositStep(PET_REST, pet, LINE, line, 1_500),
            settlement_refund(case, "pet", 6_000),
            pet_remainder=replace(CHOICE, customer_choice=NEW_CHOICE),
        ),
    )
    stored = one(
        url, "SELECT payload->'released_sources' FROM app.financial_drafts WHERE id=%s", draft
    )
    assert [
        (
            source["kind"],
            source["id"],
            source.get("application_usd_cents"),
            source["released_usd_cents"],
        )
        for source in stored[0]
    ] == [
        ("PAYMENT_ALLOCATION", str(allocation), None, 5_000),
        ("DEPOSIT_APPLICATION", str(pet_rest), 7_500, 1_000),
    ]
    result = confirm_refund(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effects(url, correction) == [
        "payment_allocation_reversal_id",
        "deposit_application_reversal_id",
        "invoice_adjustment_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    [released] = result["released_sources"]
    credit = released["customer_credit_id"]
    assert (
        released["source_kind"],
        released["reversed_payment_allocation_id"],
        released["replacement_payment_allocation_id"],
        released["released_usd_cents"],
    ) == ("PAYMENT_ALLOCATION", str(allocation), None, 5_000)
    assert [
        (item["deposit_application_id"], item["amount_usd_cents"])
        for item in result["deposit_application_reversals"]
    ] == [(str(pet_rest), 7_500)]
    [applied] = result["credit_applications"]
    assert (applied["customer_credit_id"], applied["amount_usd_cents"]) == (credit, 5_000)
    [paid_again] = result["deposit_applications"]
    assert (
        paid_again["deposit_id"],
        paid_again["application_stage"],
        paid_again["invoice_line_id"],
        paid_again["amount_usd_cents"],
    ) == (str(pet), "PET_REMAINDER_EXPLICIT", str(line), 1_500)
    [paid_back] = result["refunds"]
    assert (
        paid_back["source_deposit_id"],
        paid_back["source_customer_credit_id"],
        paid_back["amount_usd_cents"],
        paid_back["recipient_customer_id"],
    ) == (str(pet), None, 6_000, str(customer))
    assert one(url, "SELECT app.credit_available_value(%s)", credit) == (0,)
    assert credits_of(url, customer) == credits_before + 1
    assert (held(url, pet), outstanding(url, line)) == (0, 0)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line) == (6_500,)
    assert paid_elsewhere(url, case["lease"], line) == elsewhere
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_refund_above_the_paid_part_also_removes_the_unpaid_part(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-08-48 (the case 10c-1b tests 5 and 6 covered before their
    rebuild): a 1,500 charge issued after closure, of which the Customer paid 1,000, is refunded
    for 1,200. The correction removes the unpaid 500 and releases 700 of the paid part: the
    Payment allocation (1,000) is reversed whole, its unreleased 300 is re-posted on the line, and
    700 becomes the Customer's Credit; the Customer owes nothing else on the Lease and no Deposit
    holds money, so all 700 is refunded. The line's charge is then 300, fully paid."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    customer = case["customer"]
    invoice, line = unpaid_charge(url, case, case["person"])
    payment = pay(url, case["prop"], case["human"], customer, invoice, line, 1_000)
    assert outstanding(url, line) == 500
    allocation = UUID(
        str(one(url, "SELECT id FROM app.payment_allocations WHERE payment_id=%s", payment)[0])
    )
    draft = record_refund(case, command(case, line, 1_200))
    stored = one(
        url, "SELECT payload->'released_sources' FROM app.financial_drafts WHERE id=%s", draft
    )
    assert [
        (source["kind"], source["id"], source["released_usd_cents"]) for source in stored[0]
    ] == [("PAYMENT_ALLOCATION", str(allocation), 700)]
    result = confirm_refund(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effects(url, correction) == [
        "payment_allocation_reversal_id",
        "invoice_adjustment_id",
        "payment_allocation_id",
        "refund_id",
    ]
    assert result["invoice_adjustment"]["amount_usd_cents"] == 1_200
    [released] = result["released_sources"]
    assert (
        released["source_kind"],
        released["reversed_payment_allocation_id"],
        released["released_usd_cents"],
    ) == ("PAYMENT_ALLOCATION", str(allocation), 700)
    credit = released["customer_credit_id"]
    assert one(
        url,
        "SELECT payment_id,amount_usd_cents FROM app.payment_allocations WHERE id=%s",
        released["replacement_payment_allocation_id"],
    ) == (payment, 300)
    assert one(
        url,
        "SELECT customer_id,source_payment_id,recognized_usd_cents FROM app.customer_credits "
        "WHERE id=%s",
        credit,
    ) == (customer, payment, 700)
    assert (result["credit_applications"], result["deposit_applications"]) == ([], [])
    [paid_back] = result["refunds"]
    assert (
        paid_back["source_customer_credit_id"],
        paid_back["amount_usd_cents"],
        paid_back["recipient_customer_id"],
    ) == (credit, 700, str(customer))
    assert one(url, "SELECT app.credit_available_value(%s)", credit) == (0,)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line) == (300,)
    assert outstanding(url, line) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_deposit_paid_line_that_still_owes_is_refunded_above_its_paid_part(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-08-48: the other Damage line (12,500) was paid 7,500 by the Pet
    Deposit at closure and still owes 5,000. A Refund of 6,000 removes the unpaid 5,000 and
    releases 1,000 of the paid part: the Pet Deposit application (7,500) is reversed whole, so the
    Pet Deposit gets 7,500 back, and the line then owes 6,500, its new charge, with nothing paid.
    The plan pays that 6,500 from the Pet Deposit by a new Customer choice and refunds the last
    1,000 while the unpaid Initial Rent stays (BR-DEP-027). The released Deposit value never
    becomes Customer Credit, and no other line changes how it is paid."""
    url = migrated_database_url
    case = pet_paid_case(url)
    pet, customer, line = case["pet"], case["customer"], case["other_line"]
    pet_rest = application_on(url, case, "PET_REMAINDER_EXPLICIT", line)
    elsewhere = paid_elsewhere(url, case["lease"], line)
    credits_before = credits_of(url, customer)
    draft = record_refund(
        case,
        command(
            case,
            line,
            6_000,
            SettlementDepositStep(PET_REST, pet, LINE, line, 6_500),
            settlement_refund(case, "pet", 1_000),
            pet_remainder=replace(CHOICE, customer_choice=NEW_CHOICE),
        ),
    )
    stored = one(
        url,
        "SELECT payload->'released_sources',payload->'plan_overlay' FROM app.financial_drafts "
        "WHERE id=%s",
        draft,
    )
    assert [
        (
            source["kind"],
            source["id"],
            source["application_usd_cents"],
            source["released_usd_cents"],
        )
        for source in stored[0]
    ] == [("DEPOSIT_APPLICATION", str(pet_rest), 7_500, 1_000)]
    # The overlay equals the state after the release: the line owes the application's unreleased
    # 6,500 and the Pet Deposit gets back the whole 7,500; no Credit.
    assert stored[1] == overlay({f"INVOICE_LINE:{line}": 6_500}, {str(pet): 7_500})
    result = confirm_refund(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effects(url, correction) == [
        "deposit_application_reversal_id",
        "invoice_adjustment_id",
        "deposit_application_id",
        "refund_id",
    ]
    assert result["invoice_adjustment"]["amount_usd_cents"] == 6_000
    assert result["released_sources"] == []
    assert [
        (item["deposit_application_id"], item["amount_usd_cents"])
        for item in result["deposit_application_reversals"]
    ] == [(str(pet_rest), 7_500)]
    [paid_again] = result["deposit_applications"]
    assert (
        paid_again["deposit_id"],
        paid_again["application_stage"],
        paid_again["invoice_line_id"],
        paid_again["amount_usd_cents"],
    ) == (str(pet), "PET_REMAINDER_EXPLICIT", str(line), 6_500)
    [paid_back] = result["refunds"]
    assert (
        paid_back["source_deposit_id"],
        paid_back["source_customer_credit_id"],
        paid_back["amount_usd_cents"],
        paid_back["recipient_customer_id"],
    ) == (str(pet), None, 1_000, str(customer))
    assert (held(url, pet), outstanding(url, line)) == (0, 0)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line) == (6_500,)
    # The Pet Deposit to the cent: 12,500 pet damage and 6,500 on the line still applied, 1,000
    # refunded; 20,000 in all.
    assert one(
        url,
        "SELECT sum(application.amount_usd_cents) FROM app.deposit_applications application "
        "WHERE application.deposit_id=%s AND NOT EXISTS(SELECT 1 FROM "
        "app.deposit_application_reversals reversal "
        "WHERE reversal.deposit_application_id=application.id)",
        pet,
    ) == (19_000,)
    assert credits_of(url, customer) == credits_before
    assert paid_elsewhere(url, case["lease"], line) == elsewhere
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_an_older_deposit_application_on_the_line_stays_and_unlinked_adjustments_stay_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-07-46: a 2,000 Refund of the other Damage line releases only its
    newest source, the remaining Pet Deposit's 2,100; the Security Deposit's older application on
    the same line stays active, and the correction's own Adjustment passes the 8a-1 refusal. The
    Customer's Credit pays the 100 the line owes again and the Pet Deposit's 2,100 is refunded. An
    unlinked Adjustment stays refused, an Adjustment linked by another person is refused by 8a-1,
    and a linked Adjustment that would leave the line paid above its new amount is refused at
    commit (no line is paid more than its new amount)."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, line, person = case["pet"], case["other_line"], case["person"]
    security_application = application_on(url, case, "SECURITY_EXPLICIT", line)
    invoice = invoice_of(url, line)
    # Refusals inside a hand-built correction (no variant's confirm), each rolled back.
    draft = correction_draft(url, case)

    def adjust(
        connection: psycopg.Connection[Any], actor: UUID, amount: int, *, linked: bool
    ) -> None:
        correction = begin(connection, case, draft)
        adjustment = uuid4()
        if linked:
            connection.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        connection.execute(ADJUSTMENT, (adjustment, invoice, line, amount, REASON, invoice, actor))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    # Unlinked: the 8e-1 closure refusal fires before the 8a-1 refusal; either way it is refused.
    assert failure(url, lambda connection: adjust(connection, person, 100, linked=False))[0] == (
        "P5S01"
    )
    assert failure(url, lambda connection: adjust(connection, case["human"], 100, linked=True)) == (
        "55000",
        DEPOSIT_APPLIED,
    )
    assert failure(url, lambda connection: adjust(connection, person, 100, linked=True)) == (
        "23514",
        "Invoice Adjustment would violate the issued obligation",
    )
    assert state(url, draft) == "PENDING"
    # The real correction.
    result = confirm_refund(
        case,
        record_refund(
            case,
            command(
                case,
                line,
                2_000,
                SettlementCreditStep(case["new_credit"], LINE, line, 100),
                settlement_refund(case, "pet", 2_100),
            ),
        ),
    )
    [reversed_rest] = result["deposit_application_reversals"]
    assert (reversed_rest["deposit_id"], reversed_rest["amount_usd_cents"]) == (str(pet), 2_100)
    assert active(url, security_application)
    assert (outstanding(url, line), held(url, pet)) == (0, 0)
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line) == (10_500,)
    assert one(url, "SELECT app.credit_available_value(%s)", case["new_credit"]) == (200,)


def test_a_deposit_application_on_another_line_of_the_invoice_stays(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-07-46: at the Settlement the remaining Pet Deposit, by the
    Customer's choice, paid both Service lines of one Initial Invoice and part of its Rent line (no
    Credit, no Security Deposit), and the rest of the Rent stayed as debt. A Refund of the first
    Service line reverses only that line's application; the applications on the other lines of the
    same Invoice stay active, and the correction's own Adjustment passes the 8a-1 refusal. The
    released Pet Deposit value pays the Rent still owed under a new Customer choice given for this
    correction (owner answer 3 to Q-2026-10-07-44), so nothing is refunded (owner answer 2 to
    Q-2026-10-07-42). The services use the shared Property's existing terms (as mixed_rent_case),
    so no approval period overlaps."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, unit, tenant, _ = setup_sources(connection)
        lease = create_draft(
            connection,
            actor_id=human,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=date(2026, 7, 27),
            end_date=date(2027, 6, 30),
        )
        sign_lease(connection, lease, human)
        for code, name, first_rate, second_rate in (
            ("TRASH_COLLECTION", "Trash Collection", 1_000, 1_200),
            ("INTERNET", "Internet", 2_500, 2_700),
        ):
            add_service(
                connection,
                actor_id=human,
                property_id=prop,
                lease_id=lease,
                code=code,
                display_name=name,
                first_rate=first_rate,
                second_rate=second_rate,
            )
    issued = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, uuid4()), actor=authenticated(human, prop)
    )
    pet = pet_deposit(url, human, prop, lease, today(url))
    terminate(url, human, prop, lease, today(url), voluntary=False)
    bill_unbilled_rent_months(url, human, prop, lease)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": tenant,
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    with psycopg.connect(url) as connection:
        lines = [
            (UUID(str(row[0])), str(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT id,category,app.invoice_line_outstanding(id) FROM app.invoice_lines "
                "WHERE invoice_id=%s ORDER BY line_sequence,id",
                (issued.invoice_id,),
            ).fetchall()
        ]
    [(rent, rent_owed)] = [(line, owed) for line, category, owed in lines if category == "RENT"]
    [(service, service_owed), (other_service, other_owed)] = [
        (line, owed) for line, category, owed in lines if category != "RENT"
    ]
    deposit = held(url, pet)
    rent_paid = deposit - service_owed - other_owed
    # The Invoice owes more than the Pet Deposit holds: the Rent line keeps debt after closure.
    assert service_owed > 0 and other_owed > 0 and 0 < rent_paid < rent_owed
    assert credits_of(url, tenant) == 0
    confirm_settlement(
        case,
        record(
            case,
            (
                SettlementDepositStep(PET_REST, pet, LINE, service, service_owed),
                SettlementDepositStep(PET_REST, pet, LINE, other_service, other_owed),
                SettlementDepositStep(PET_REST, pet, LINE, rent, rent_paid),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    kept = [
        application_on(url, case, "PET_REMAINDER_EXPLICIT", line) for line in (other_service, rent)
    ]
    assert (held(url, pet), outstanding(url, rent)) == (0, rent_owed - rent_paid)
    before = settlement_row(url, case["settlement"])
    result = confirm_refund(
        case,
        record_refund(
            case,
            command(
                case,
                service,
                service_owed,
                SettlementDepositStep(PET_REST, pet, LINE, rent, service_owed),
                pet_remainder=replace(CHOICE, customer_choice=NEW_CHOICE),
            ),
        ),
    )
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effects(url, correction) == [
        "deposit_application_reversal_id",
        "invoice_adjustment_id",
        "deposit_application_id",
    ]
    [reversed_service] = result["deposit_application_reversals"]
    assert (reversed_service["deposit_id"], reversed_service["amount_usd_cents"]) == (
        str(pet),
        service_owed,
    )
    assert all(active(url, application) for application in kept)
    [paid_again] = result["deposit_applications"]
    assert (
        paid_again["deposit_id"],
        paid_again["application_stage"],
        paid_again["invoice_line_id"],
        paid_again["amount_usd_cents"],
    ) == (str(pet), "PET_REMAINDER_EXPLICIT", str(rent), service_owed)
    # Nothing is left to refund, and the released Deposit value never became Customer Credit.
    assert (result["released_sources"], result["refunds"]) == ([], [])
    assert (held(url, pet), credits_of(url, tenant)) == (0, 0)
    assert [outstanding(url, line) for line in (service, other_service, rent)] == [
        0,
        0,
        rent_owed - rent_paid - service_owed,
    ]
    assert one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", service) == (0,)
    assert settlement_row(url, case["settlement"]) == before


def test_a_br_dep_027_correction_needs_a_new_customer_choice(migrated_database_url: str) -> None:
    """Owner answer 3 to Q-2026-10-07-44 and BR-DEP-027: at an unpaid-Initial termination the
    remaining Pet Deposit pays other debt in a correction only by a Customer choice given for that
    correction; the choice recorded at the Settlement is not reused. With a new choice the
    released pet damage value is applied again, the remaining Pet Deposit pays the other line and
    its rest is refunded while other debt stays open. A later correction does not reuse that
    correction's choice either (review round 1); the database compares the recorded text only."""
    url = migrated_database_url
    case = {**leaving_case(url, unpaid_initial=True), "url": url}
    prop, human, pet = case["prop"], case["human"], case["pet"]
    pet_line, other_line = case["pet_line"], case["other_line"]
    forfeit_through_draft(
        PostgresDepositService(financial_database_url(), prop, human), case["security"]
    )
    confirm_settlement(
        case,
        record(
            case,
            (
                SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 12_500),
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
                settlement_refund(case, "pet", 5_500),
            ),
            pet_remainder=CHOICE,
        ),
    )
    case["person"] = approver(url)
    steps = (
        SettlementDepositStep(PET_FIRST, pet, LINE, pet_line, 8_500),
        SettlementDepositStep(PET_REST, pet, LINE, other_line, 2_000),
        settlement_refund(case, "pet", 2_000),
    )
    with pytest.raises(FinalSettlementConflictError) as reused:
        record_refund(case, command(case, pet_line, 4_000, *steps, pet_remainder=CHOICE))
    assert cause(reused) == (
        "55000",
        "A correction needs the Customer's choice for this correction; the Final Settlement's "
        "choice is not reused",
    )
    new_choice = replace(CHOICE, customer_choice=NEW_CHOICE)
    result = confirm_refund(
        case,
        record_refund(case, command(case, pet_line, 4_000, *steps, pet_remainder=new_choice)),
    )
    assert [
        (item["application_stage"], item["amount_usd_cents"])
        for item in result["deposit_applications"]
    ] == [("PET_RELATED_FIRST", 8_500), ("PET_REMAINDER_EXPLICIT", 2_000)]
    [paid] = result["refunds"]
    assert (paid["source_deposit_id"], paid["amount_usd_cents"]) == (str(pet), 2_000)
    assert (held(url, pet), outstanding(url, pet_line), outstanding(url, other_line)) == (
        0,
        0,
        8_500,
    )
    # One agreement per correction: a later correction does not reuse this correction's choice.
    with pytest.raises(FinalSettlementConflictError) as again:
        record_refund(case, command(case, pet_line, 1_000, *steps, pet_remainder=new_choice))
    assert cause(again) == (
        "55000",
        "A correction needs the Customer's choice for this correction; an earlier correction's "
        "choice is not reused",
    )


def test_the_refund_confirm_and_the_step_hold_the_lease_row_lock(
    migrated_database_url: str,
) -> None:
    """Owner answer 4 to Q-2026-10-07-44: the Refund correction's confirm locks the Lease row FOR
    UPDATE right after the two draft locks and before the first source Payment (the 8e-3 order),
    so another session's lock on the Lease waits; the step's lock function takes the released
    sources' Payments and Credits in its single id-ordered passes (security review round 2) and the
    corrected Invoice FOR UPDATE only after the step's Payments (security review round 1), also
    when no step pays that Invoice; the step takes the Lease lock
    itself when a variant did not (review round 3 of sub-slice 10c-2a-2). A correction Credit
    application whose basis is not the one BR-CREDIT-006 gives its step is refused."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    lease = case["lease"]
    rent, _ = rent_line(url, case["initial"])
    draft = record_refund(case, command(case, rent, 300))

    def nowait(connection: psycopg.Connection[Any]) -> object:
        return connection.execute(
            "SELECT 1 FROM app.leases WHERE id=%s FOR UPDATE NOWAIT", (lease,)
        ).fetchone()

    def no_key_update(connection: psycopg.Connection[Any]) -> object:
        return connection.execute(
            "SELECT 1 FROM app.leases WHERE id=%s FOR NO KEY UPDATE NOWAIT", (lease,)
        ).fetchone()

    with psycopg.connect(url) as holding, psycopg.connect(url) as probe:
        holding.execute(
            "SELECT app.confirm_settlement_refund(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        )
        with pytest.raises(psycopg.errors.LockNotAvailable):
            nowait(probe)
        probe.rollback()
        holding.rollback()
    assert state(url, draft) == "PENDING"
    source = str(
        one(
            url,
            "SELECT prosrc FROM pg_catalog.pg_proc "
            "WHERE oid='app.confirm_settlement_refund(uuid,uuid,uuid,text)'::regprocedure",
        )[0]
    )
    settlement_lock = source.index("'final-settlement-draft:'")
    lease_lock = source.index("FROM app.leases WHERE id=v_settlement.lease_id FOR UPDATE")
    plan_lock = source.index("PERFORM app.lock_settlement_correction_plan(p_draft);")
    invoice_lock = source.index(
        "FROM app.invoices WHERE id=(v_refund->>'invoice_id')::uuid FOR UPDATE"
    )
    assert settlement_lock < lease_lock < plan_lock < invoice_lock
    # Security review round 2: no Payment or Credit lock of its own; the lock function takes them
    # all, each kind in one id-ordered pass.
    assert "app.payments WHERE id=" not in source
    assert "app.customer_credits WHERE id=" not in source
    assert "serialize_payment_state" not in source
    # Review round 3: the lock function has one Payment pass and one Credit pass.
    locks = str(
        one(
            url,
            "SELECT prosrc FROM pg_catalog.pg_proc "
            "WHERE oid='app.lock_settlement_correction_plan(uuid)'::regprocedure",
        )[0]
    )
    assert locks.count("serialize_payment_state(") == 1
    assert locks.count("FROM app.payments WHERE id=v_id FOR UPDATE") == 1
    assert (
        locks.count("FROM app.customer_credits WHERE id=ANY(v_credits) ORDER BY id FOR UPDATE") == 1
    )
    # The lock function alone, for a REFUND draft with an empty plan (no step pays its Invoice):
    # it locks the released source's Payment and the corrected Invoice FOR UPDATE (a FOR NO KEY
    # UPDATE lock would let FOR KEY SHARE through).
    released_payment = one(
        url,
        "SELECT payload->'released_sources'->0->>'payment_id' FROM app.financial_drafts "
        "WHERE id=%s",
        draft,
    )[0]
    assert released_payment is not None
    with psycopg.connect(url) as holding, psycopg.connect(url) as probe:
        holding.execute("SELECT app.lock_settlement_correction_plan(%s)", (draft,))
        for statement, row in (
            ("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE NOWAIT", released_payment),
            ("SELECT 1 FROM app.invoices WHERE id=%s FOR KEY SHARE NOWAIT", case["initial"]),
        ):
            with pytest.raises(psycopg.errors.LockNotAvailable):
                probe.execute(statement, (row,))
            probe.rollback()
        holding.rollback()
    # Security review round 1: the corrected Invoice is locked only after the step's Payments,
    # Credits and Charges, as the one-call writers lock a Payment or a Charge before an Invoice.
    # While another session holds the Payment of a Credit the plan names, the confirm waits there
    # and holds no lock on the corrected Invoice.
    line = case["other_line"]
    invoice = invoice_of(url, line)
    ordered = record_refund(
        case,
        command(
            case,
            line,
            4_000,
            SettlementCreditStep(case["new_credit"], LINE, line, 300),
            SettlementDepositStep(SECURITY, case["security"], LINE, line, 7_800),
            settlement_refund(case, "security", 2_200),
            settlement_refund(case, "pet", 2_100),
        ),
    )
    step_payment = one(
        url, "SELECT source_payment_id FROM app.customer_credits WHERE id=%s", case["new_credit"]
    )[0]
    application_name = f"v1056-refund-invoice-lock-{uuid4().hex}"

    def confirm_and_roll_back() -> None:
        with psycopg.connect(make_conninfo(url, application_name=application_name)) as waiting:
            waiting.execute(
                "SELECT app.confirm_settlement_refund(%s,%s,%s,'financial.approve')",
                (case["prop"], case["person"], ordered),
            )
            waiting.rollback()

    with psycopg.connect(url) as holding:
        holding.execute("SELECT 1 FROM app.payments WHERE id=%s FOR UPDATE", (step_payment,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(confirm_and_roll_back)
            try:
                assert blocked_by(application_name, holding), (
                    "The confirm must wait on the step Credit's Payment"
                )
                assert holding.execute(
                    "SELECT 1 FROM app.invoices WHERE id=%s FOR UPDATE NOWAIT", (invoice,)
                ).fetchone() == (1,)
            finally:
                holding.rollback()
            future.result(timeout=30)
    assert state(url, ordered) == "PENDING"
    # The step alone, without the variant's call of the lock function, takes the Lease lock
    # (round-3 hardening of sub-slice 10c-2a-2). The release is written by hand without that call;
    # the probe asks FOR NO KEY UPDATE, which only a FOR UPDATE lock refuses (key locks of the
    # release's own inserts do not).
    step_draft = plan_draft(url, case, main_plan(case), released_overlay(case))
    with psycopg.connect(url) as holding, psycopg.connect(url) as probe:
        correction = begin(holding, case, step_draft)
        for stage in ("PET_REMAINDER_EXPLICIT", "SECURITY_EXPLICIT"):
            application = application_on(url, case, stage, case["other_line"])
            reverse(holding, correction, application, case["person"])
        adjustment = uuid4()
        holding.execute(LINK, (correction, "invoice_adjustment_id", adjustment))
        credit_adjustment(holding, case, adjustment, 4_000)
        assert no_key_update(probe) == (1,)
        probe.rollback()
        holding.execute(POST_PLAN, (case["prop"], case["person"], step_draft))
        with pytest.raises(psycopg.errors.LockNotAvailable):
            no_key_update(probe)
        probe.rollback()
        holding.rollback()

    # BR-CREDIT-006: a correction Credit application with a basis other than its step's.
    def wrong_basis(connection: psycopg.Connection[Any]) -> None:
        correction = release_by_hand(connection, case, step_draft)
        application = uuid4()
        connection.execute(
            "SET CONSTRAINTS app.settlement_correction_effects_customer_credit_application__fkey "
            "DEFERRED"
        )
        connection.execute(LINK, (correction, "customer_credit_application_id", application))
        connection.execute(
            "INSERT INTO app.customer_credit_applications(id,customer_credit_id,target_kind,"
            "invoice_id,final_settlement_id,amount_usd_cents,within_invoice_basis,"
            "customer_designation_reference,occurred_at,actor_id,authorization_reference) VALUES "
            "(%s,%s,'INVOICE',%s,%s,300,'CUSTOMER_DESIGNATED','The Customer asked',"
            "clock_timestamp(),%s,'financial.approve')",
            (
                application,
                case["new_credit"],
                invoice_of(url, case["other_line"]),
                case["settlement"],
                case["person"],
            ),
        )

    assert failure(url, wrong_basis) == (
        "23514",
        "A post-settlement correction Credit application must be a Credit step of its correction",
    )
    assert state(url, step_draft) == "PENDING"


def test_the_deposit_refund_correction_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
        # The Refund correction's record and confirm keep their grants: the financial role only.
        for function in (CHANGED[4], CHANGED[6]):
            assert [
                connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone()
                for role in ("prm_financial", "prm_runtime", "prm_bootstrap")
            ] == [(True,), (False,), (False,)], function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261107_103")
    assert revision is not None and revision.down_revision == "20261106_102"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_deposit_refund_correction") as temporary:
        alembic_command.upgrade(config, "20261106_102")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261107_103")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for name in CHANGED:
        assert "10c-2a-3" in str(after_functions[name]), name
        assert "10c-2a-3" not in str(before_functions[name]), name
    # No time limit (BR-SETTLE-013): no age() call.
    for name in (*CHANGED, *INTERNAL):
        assert re.search(r"(?<![a-z_])age\(", str(after_functions[name])) is None, name
