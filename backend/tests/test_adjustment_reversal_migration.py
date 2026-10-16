"""The mistaken credit Adjustment reversal before closure (V1-056 sub-slice 10f-1).

Owner answer 7 to Q-2026-10-06-36 and the slice 10 entry of the plan (owner answer to the 8f
report): an invoices.adjust holder records an ADJUSTMENT_REVERSAL draft, and only a
financial.approve holder confirms it. The confirm writes the Adjustment reversal (DB-INV-010) and
puts the released value back on the line: the part of each released value's Credit still available
is applied to the line again (BR-CREDIT-008), and any part already used elsewhere stays as debt on
the line. Until the owner answers Q-2026-10-16-118, a put-back that the Rent-first order
(BR-CREDIT-006) would put on another line, and an Adjustment that a resolution wrote, are refused.
After the Lease's Final Settlement is closed the reversal is a correction (sub-slice 10f-2).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.adjustment_reversal import (
    AdjustmentReversalAuthorizationError,
    AdjustmentReversalConflictError,
    AdjustmentReversalKeyReused,
    AdjustmentReversalNotFoundError,
    AdjustmentReversalService,
    AdjustmentReversalStaleDraftError,
    RecordAdjustmentReversalCommand,
)
from property_rental.billing import PostgresRentBillingService
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.financial_draft import FinancialDraftService
from property_rental.invoice import ResolveHandBackRentCommand
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import pay
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled
from test_debit_adjustment_line_block_migration import debit, first_line, outstanding
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_hand_back_rent_migration import (
    AUGUST,
    hand_back,
    hand_back_database,  # noqa: F401
    lease_with_invoices,
)
from test_hand_back_rent_migration import invoices as hand_back_invoices
from test_hand_back_rent_migration import lines as hand_back_lines
from test_hand_back_rent_migration import pay as hand_back_pay
from test_hand_back_rent_migration import staff as hand_back_staff
from test_hand_back_rent_migration import version as hand_back_version
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    runtime_database_url,
)
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_payment_allocation_migration import source as allocation_source
from test_payment_move_migration import person, rows, value

RECORD = "app.record_adjustment_reversal_draft(uuid,uuid,uuid,uuid,text,text)"
CONFIRM = "app.confirm_adjustment_reversal(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.adjustment_reversal_source(uuid,uuid)",
    "app.adjustment_reversal_instant(uuid)",
    "app.adjustment_reversal_result(uuid)",
)
PATCHED = {
    "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,"
    "timestamp with time zone,uuid)",
}
REVISION = "20261219_145"
REASON = "The credit was recorded on the wrong Invoice"
PLACEMENT = (
    "The Credit put-back would go on another line by the Rent-first order; this waits for the owner"
)
CLOSED = (
    "The Lease's Final Settlement is closed; the Adjustment is reversed through a correction of "
    "that Final Settlement"
)


def reversals() -> AdjustmentReversalService:
    return AdjustmentReversalService(financial_database_url())


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def preparer(human: UUID, prop: UUID) -> Any:
    return person(human, prop, "invoices.adjust")


def approver(human: UUID, prop: UUID) -> Any:
    return person(human, prop, "financial.approve")


def request(adjustment: UUID, **changes: Any) -> RecordAdjustmentReversalCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "adjustment_id": adjustment,
        "reason": REASON,
        **changes,
    }
    return RecordAdjustmentReversalCommand(**values)


def draft_id(result: dict[str, object]) -> UUID:
    return UUID(str(result["draft_id"]))


def source_of(result: dict[str, object]) -> dict[str, Any]:
    return cast(dict[str, Any], cast(dict[str, Any], result["payload"])["source"])


def adjustments(url: str, line: UUID, kind: str = "CREDIT") -> list[UUID]:
    return [
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT id FROM app.invoice_adjustments WHERE invoice_line_id=%s "
            "AND adjustment_type=%s ORDER BY occurred_at,id",
            line,
            kind,
        )
    ]


def status(url: str, invoice: UUID) -> str:
    return str(value(url, "SELECT status FROM app.invoices WHERE id=%s", invoice))


def version(url: str, invoice: UUID) -> int:
    return int(value(url, "SELECT version FROM app.invoices WHERE id=%s", invoice))


def available(url: str, credit: UUID) -> int:
    return int(value(url, "SELECT app.credit_available_value(%s)", credit))


def reversed_rows(url: str, adjustment: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT reason,actor_id,authorization_reference FROM app.invoice_adjustment_reversals "
        "WHERE invoice_adjustment_id=%s",
        adjustment,
    )


def reconciled(url: str, invoice: UUID) -> None:
    customer = value(url, "SELECT customer_id FROM app.invoices WHERE id=%s", invoice)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def refusal(prop: UUID, human: UUID, adjustment: UUID) -> tuple[str | None, str | None]:
    """The recorder's SQLSTATE and message, called as the service calls it."""
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,'invoices.adjust')",
                (prop, human, uuid4(), adjustment, REASON),
            )
        connection.rollback()
    return refused.value.sqlstate, refused.value.diag.message_primary


def put_back_rows(url: str, application: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT a.customer_credit_id,a.amount_usd_cents,a.within_invoice_basis,"
        "a.authorization_reference,d.invoice_line_id,d.attribution_basis,"
        "d.calculation_trace->>'reason' FROM app.customer_credit_applications a "
        "JOIN app.customer_credit_application_details d "
        "ON d.customer_credit_application_id=a.id WHERE a.id=%s",
        application,
    )


def test_a_credit_adjustment_that_released_nothing_owes_again(
    migrated_database_url: str,
) -> None:
    """A credit Adjustment within the unpaid value released no paid value: the reversal restores
    the line's obligation, advances the Invoice version, keeps the reason and the approver and
    writes one audit event; only financial.approve confirms; a replay returns the same result;
    the ledger reconciles."""
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    adjust_credit(url, human, prop, invoice, line, 10_000)
    [adjustment] = adjustments(url, line)
    assert outstanding(url, line) == 50_000
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    assert (recorded["kind"], recorded["state"], recorded["prepare_capability"]) == (
        "ADJUSTMENT_REVERSAL",
        "PENDING",
        "invoices.adjust",
    )
    source = source_of(recorded)
    assert (
        source["amount_usd_cents"],
        source["line_outstanding_usd_cents"],
        source["releases"],
        source["put_back_usd_cents"],
        source["debt_usd_cents"],
        source["refusal"],
    ) == (10_000, 50_000, [], 0, 0, None)
    before = version(url, invoice)
    for staff in (preparer(human, prop), person(human, prop, "invoices.adjust", "credits.apply")):
        with pytest.raises(AdjustmentReversalAuthorizationError):
            reversals().confirm(prop, draft_id(recorded), actor=staff)
    assert reversed_rows(url, adjustment) == [] and outstanding(url, line) == 50_000
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    assert (
        result["invoice_adjustment_id"],
        result["restored_usd_cents"],
        result["put_backs"],
        result["debt_usd_cents"],
        result["reason"],
        result["authorization_reference"],
    ) == (str(adjustment), 10_000, [], 0, REASON, "financial.approve")
    assert "transaction_id" not in json.dumps(result)
    assert outstanding(url, line) == 60_000
    assert version(url, invoice) == before + 1 and status(url, invoice) == "PARTIALLY_PAID"
    assert reversed_rows(url, adjustment) == [(REASON, human, "financial.approve")]
    assert reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop)) == result
    assert rows(
        url,
        "SELECT count(*),min(correlation_id::text),min(authorization_reference) "
        "FROM app.audit_events WHERE action='invoice.adjustment_reversed' AND entity_id=%s",
        invoice,
    ) == [(1, str(draft_id(recorded)), "financial.approve")]
    assert drafts().get(prop, draft_id(recorded), actor=approver(human, prop))["state"] == (
        "CONFIRMED"
    )
    reconciled(url, invoice)


def test_a_released_allocation_s_credit_goes_back_on_its_line(
    migrated_database_url: str,
) -> None:
    """A credit Adjustment of 70,000 on an 80,000 line a Payment paid 20,000 of released 10,000
    as the Invoice Customer's new Credit. The reversal applies that Credit again to the same line
    with the Rent-first proposal: the line owes 60,000 (80,000 less what the Payment paid) and the
    Credit holds nothing."""
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    effect = cast(
        dict[str, Any], adjust_credit(url, human, prop, invoice, line, 70_000)["adjustment_effect"]
    )
    [credit] = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    assert (effect["customer_credit_usd_cents"], available(url, credit)) == (10_000, 10_000)
    assert outstanding(url, line) == 0 and status(url, invoice) == "PAID"
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    source = source_of(recorded)
    [release] = cast(list[dict[str, Any]], source["releases"])
    assert (
        release["source_kind"],
        release["customer_credit_id"],
        release["released_usd_cents"],
        release["available_usd_cents"],
        release["put_back_usd_cents"],
        release["debt_usd_cents"],
    ) == ("PAYMENT_ALLOCATION", str(credit), 10_000, 10_000, 10_000, 0)
    assert (source["put_back_usd_cents"], source["debt_usd_cents"]) == (10_000, 0)
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    assert (
        put_back["customer_credit_id"],
        put_back["amount_usd_cents"],
        put_back["invoice_credit_excess_release_id"],
    ) == (str(credit), 10_000, release["invoice_credit_excess_release_id"])
    assert put_back_rows(url, UUID(str(put_back["credit_application_id"]))) == [
        (
            credit,
            10_000,
            "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
            "credits.apply",
            line,
            "RENT_FIRST_PROPOSAL",
            "Invoice Adjustment reversal put-back",
        )
    ]
    assert rows(
        url,
        "SELECT a.actor_id,d.calculation_trace->>'invoice_adjustment_reversal_id',"
        "d.calculation_trace->>'invoice_credit_excess_release_id' "
        "FROM app.customer_credit_applications a JOIN app.customer_credit_application_details d "
        "ON d.customer_credit_application_id=a.id WHERE a.id=%s",
        UUID(str(put_back["credit_application_id"])),
    ) == [
        (
            human,
            result["invoice_adjustment_reversal_id"],
            release["invoice_credit_excess_release_id"],
        )
    ]
    assert outstanding(url, line) == 60_000 and available(url, credit) == 0
    assert status(url, invoice) == "PARTIALLY_PAID"
    reconciled(url, invoice)


def test_a_released_credit_application_goes_back_only_with_what_is_left(
    migrated_database_url: str,
) -> None:
    """A 5,000 credit Adjustment on a line the Customer's Credit paid in full returned 5,000 to
    that Credit; the Customer then used 22,000 of the Credit on the next Invoice, leaving 3,000.
    The reversal puts back only those 3,000; the other 2,000 stays as debt on the line."""
    url = migrated_database_url
    human, prop, credit, invoice, line, _ = credit_source(url)
    staff = credit_actor(human, prop, "credits.apply")
    credits().apply(prop, credit, credit_designated(invoice, line, 80_000), actor=staff)
    effect = cast(
        dict[str, Any], adjust_credit(url, human, prop, invoice, line, 5_000)["adjustment_effect"]
    )
    assert effect["returned_to_customer_credit_usd_cents"] == 5_000
    assert available(url, credit) == 25_000
    [(customer, lease)] = rows(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", invoice
    )
    with psycopg.connect(url) as connection:
        later, later_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 4, 1),
        )
    credits().apply(prop, credit, credit_designated(later, later_line, 22_000), actor=staff)
    assert available(url, credit) == 3_000
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    [release] = cast(list[dict[str, Any]], source_of(recorded)["releases"])
    assert (
        release["source_kind"],
        release["customer_credit_id"],
        release["released_usd_cents"],
        release["available_usd_cents"],
        release["put_back_usd_cents"],
        release["debt_usd_cents"],
    ) == ("CREDIT_APPLICATION", str(credit), 5_000, 3_000, 3_000, 2_000)
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    assert (put_back["customer_credit_id"], put_back["amount_usd_cents"]) == (str(credit), 3_000)
    assert result["debt_usd_cents"] == 2_000
    assert outstanding(url, line) == 2_000 and available(url, credit) == 0
    assert outstanding(url, later_line) == 58_000
    reconciled(url, invoice)


def test_two_releases_of_one_credit_count_the_earlier_put_back(
    migrated_database_url: str,
) -> None:
    """Review round 1 set-up: the Credit paid the 80,000 line in two applications (50,000, then
    30,000). A 40,000 credit Adjustment released the newer one whole (30,000) and 10,000 of the
    older one, so the Credit held 60,000; the Customer then used 25,000 of it on the next Invoice.
    The reversal puts back 30,000 for the first release and only the 5,000 left for the second,
    which counts the first put-back; 5,000 stays as debt on the line."""
    url = migrated_database_url
    human, prop, credit, invoice, line, _ = credit_source(url)
    staff = credit_actor(human, prop, "credits.apply")
    credits().apply(prop, credit, credit_designated(invoice, line, 50_000), actor=staff)
    credits().apply(prop, credit, credit_designated(invoice, line, 30_000), actor=staff)
    assert outstanding(url, line) == 0
    adjust_credit(url, human, prop, invoice, line, 40_000)
    assert available(url, credit) == 60_000
    [(customer, lease)] = rows(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", invoice
    )
    with psycopg.connect(url) as connection:
        later, later_line = create_recurring_rent_invoice(
            connection,
            actor_id=human,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 4, 1),
        )
    credits().apply(prop, credit, credit_designated(later, later_line, 25_000), actor=staff)
    assert available(url, credit) == 35_000
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    source = source_of(recorded)
    assert [
        (
            item["released_usd_cents"],
            item["available_usd_cents"],
            item["put_back_usd_cents"],
            item["debt_usd_cents"],
        )
        for item in cast(list[dict[str, Any]], source["releases"])
    ] == [(30_000, 35_000, 30_000, 0), (10_000, 5_000, 5_000, 5_000)]
    assert (source["put_back_usd_cents"], source["debt_usd_cents"]) == (35_000, 5_000)
    before = version(url, invoice)
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    put_backs = cast(list[dict[str, Any]], result["put_backs"])
    assert [item["amount_usd_cents"] for item in put_backs] == [30_000, 5_000]
    assert result["debt_usd_cents"] == 5_000
    applied = rows(
        url,
        "SELECT d.invoice_line_id,a.occurred_at FROM app.customer_credit_applications a "
        "JOIN app.customer_credit_application_details d ON d.customer_credit_application_id=a.id "
        "WHERE a.id=ANY(%s) ORDER BY a.occurred_at",
        [UUID(str(item["credit_application_id"])) for item in put_backs],
    )
    assert [found for found, _ in applied] == [line, line]
    assert applied[0][1] < applied[1][1]
    assert outstanding(url, line) == 5_000 and available(url, credit) == 0
    assert status(url, invoice) == "PARTIALLY_PAID" and version(url, invoice) == before + 2
    reconciled(url, invoice)


def test_a_put_back_goes_only_where_the_rent_first_order_also_puts_it(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-16-118 point 1 (fail closed until the owner answers): a credit Adjustment on a
    paid Service line released its value as Credit while the Rent line still owes; the Rent-first
    order would put that Credit on the Rent line, so the draft is refused and nothing is written.
    Once the Rent line is paid, the reversal puts the Credit back on the Service line."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, customer, lease, _ = setup_billing_source(connection)
    invoice = (
        PostgresRentBillingService(financial_database_url(), prop, human)
        .generate(initial_command(lease, uuid4()), actor=authenticated(human, prop))
        .invoice_id
    )
    lines = rows(
        url,
        "SELECT category,id FROM app.invoice_lines WHERE invoice_id=%s "
        "AND category IN ('RENT','SERVICE_CHARGES') ORDER BY line_sequence",
        invoice,
    )
    rent = UUID(str(next(found for kind, found in lines if kind == "RENT")))
    service = UUID(str(next(found for kind, found in lines if kind == "SERVICE_CHARGES")))
    rent_due, service_due = outstanding(url, rent), outstanding(url, service)
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=rent_due + service_due,
        )
    pay(prop, payment, invoice, service, service_due, human)
    adjust_credit(url, human, prop, invoice, service, service_due)
    [adjustment] = adjustments(url, service)
    assert outstanding(url, service) == 0 and outstanding(url, rent) == rent_due
    assert refusal(prop, human, adjustment) == ("55000", PLACEMENT)
    with pytest.raises(AdjustmentReversalConflictError):
        reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='ADJUSTMENT_REVERSAL' "
            "AND payload->>'invoice_adjustment_id'=%s",
            str(adjustment),
        )
        == 0
    )
    pay(prop, payment, invoice, rent, rent_due, human)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    assert source_of(recorded)["put_back_usd_cents"] == service_due
    result = reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    [(_, amount, _, _, on_line, basis, _)] = put_back_rows(
        url, UUID(str(put_back["credit_application_id"]))
    )
    assert (amount, on_line, basis) == (service_due, service, "SERVICE_PROPOSAL")
    assert outstanding(url, service) == 0 and outstanding(url, rent) == 0
    reconciled(url, invoice)


def test_adjustment_reversal_refusals_stale_drafts_withdrawal_and_reads(
    migrated_database_url: str,
) -> None:
    """A debit Adjustment, an unknown Adjustment, a reused key, a second waiting draft and a
    reversed Adjustment are refused; an exact repeat replays; a draft whose sources changed is
    stale and stays pending; the recorder and the confirm need READ COMMITTED; the preparer may
    withdraw; the preparer and an approver read the draft."""
    url = migrated_database_url
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    debit(url, human, prop, invoice, line, 1_000)
    [debited] = adjustments(url, line, "DEBIT")
    assert refusal(prop, human, debited) == (
        "55000",
        "Only a credit Adjustment is reversed by an Adjustment reversal draft",
    )
    with pytest.raises(AdjustmentReversalNotFoundError):
        reversals().record(prop, request(uuid4()), actor=preparer(human, prop))
    adjust_credit(url, human, prop, invoice, line, 10_000)
    [adjustment] = adjustments(url, line)
    first = request(adjustment)
    recorded = reversals().record(prop, first, actor=preparer(human, prop))
    identity = draft_id(recorded)
    assert reversals().record(prop, first, actor=preparer(human, prop)) == recorded
    with pytest.raises(AdjustmentReversalKeyReused):
        reversals().record(
            prop,
            request(adjustment, idempotency_key=first.idempotency_key, reason="Other"),
            actor=preparer(human, prop),
        )
    assert refusal(prop, human, adjustment) == (
        "55000",
        "Another Adjustment reversal draft of this Adjustment is waiting",
    )
    # The database refuses a confirm under the preparer's capability (42501); nothing is written.
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as staff_confirm:
            connection.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'invoices.adjust')",
                (prop, human, identity),
            )
        connection.rollback()
    assert (staff_confirm.value.sqlstate, staff_confirm.value.diag.message_primary) == (
        "42501",
        "Only financial.approve may confirm an Adjustment reversal",
    )
    assert reversed_rows(url, adjustment) == []
    for capabilities in (("invoices.adjust",), ("financial.approve",)):
        assert drafts().get(prop, identity, actor=person(human, prop, *capabilities))["kind"] == (
            "ADJUSTMENT_REVERSAL"
        )
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as isolation:
            connection.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                (prop, human, identity),
            )
        connection.rollback()
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "An Adjustment reversal is confirmed at READ COMMITTED",
    )
    # Another allocation on the line changes the draft's sources: it is stale and stays pending.
    pay(prop, payment, invoice, line, 5_000, human)
    with pytest.raises(AdjustmentReversalStaleDraftError):
        reversals().confirm(prop, identity, actor=approver(human, prop))
    assert drafts().get(prop, identity, actor=approver(human, prop))["state"] == "PENDING"
    assert reversed_rows(url, adjustment) == [] and outstanding(url, line) == 46_000
    withdrawn = drafts().withdraw(
        prop,
        identity,
        "Recorded before the second payment",
        prepare_capability="invoices.adjust",
        actor=preparer(human, prop),
    )
    assert withdrawn["state"] == "WITHDRAWN"
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as recording:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,'invoices.adjust')",
                (prop, human, uuid4(), adjustment, REASON),
            )
        connection.rollback()
    assert (recording.value.sqlstate, recording.value.diag.message_primary) == (
        "55000",
        "An Adjustment reversal draft is recorded at READ COMMITTED",
    )
    again = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    reversals().confirm(prop, draft_id(again), actor=approver(human, prop))
    assert outstanding(url, line) == 56_000
    assert refusal(prop, human, adjustment) == ("55000", "The Adjustment is already reversed")
    reconciled(url, invoice)


def test_a_closed_settlement_s_adjustment_waits_for_a_correction(
    migrated_database_url: str,
) -> None:
    """The Signer's 400 Credit of the two-Signer Lease came from a credit Adjustment on the
    Signer's paid Invoice. A reversal draft recorded before the Final Settlement is stale after
    the real closure (the Settlement used that Credit) and stays pending; after the closure the
    recorder refuses the Adjustment, which only a correction of that Settlement may reverse
    (sub-slice 10f-2)."""
    url = migrated_database_url
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    human, prop = case["human"], case["prop"]
    [adjustment] = [
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT a.id FROM app.invoice_adjustments a JOIN app.invoices i ON i.id=a.invoice_id "
            "WHERE i.lease_id=%s AND a.adjustment_type='CREDIT'",
            case["lease"],
        )
    ]
    early = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    [release] = cast(list[dict[str, Any]], source_of(early)["releases"])
    assert (release["customer_credit_id"], release["put_back_usd_cents"]) == (
        str(case["credit"]),
        400,
    )
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    with pytest.raises(AdjustmentReversalStaleDraftError):
        reversals().confirm(prop, draft_id(early), actor=approver(human, prop))
    assert drafts().get(prop, draft_id(early), actor=approver(human, prop))["state"] == "PENDING"
    assert reversed_rows(url, adjustment) == []
    assert refusal(prop, human, adjustment) == ("55000", CLOSED)


def test_an_adjustment_a_hand_back_resolution_wrote_is_refused(
    hand_back_database: str,  # noqa: F811
) -> None:
    """Q-2026-10-16-118 point 2: a hand-back resolution's credit Adjustment stays with its
    resolution; the reversal draft refuses it and nothing is written."""
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    [(rent, _, _)] = hand_back_lines(url, august)
    hand_back_pay(url, scenario, august, rent, 20_000)
    hand_back(url, scenario, date(2026, 8, 4))
    hand_back_invoices().resolve_hand_back_rent(
        scenario.prop,
        august,
        ResolveHandBackRentCommand(
            uuid4(), "CREDIT_ADJUSTMENT", 60_000, "Unpaid rest", hand_back_version(url, august)
        ),
        actor=hand_back_staff(scenario.human, scenario.prop),
    )
    [adjustment] = adjustments(url, rent)
    assert refusal(scenario.prop, scenario.human, adjustment) == (
        "55000",
        "An Adjustment that a resolution wrote is not reversed by an Adjustment reversal draft",
    )
    assert (
        value(url, "SELECT count(*) FROM app.financial_drafts WHERE kind='ADJUSTMENT_REVERSAL'")
        == 0
    )


def test_adjustment_reversal_drafts_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions or
    writes Adjustment reversals; a reversal is append-only; the migration adds only its
    functions, relaxes only the two draft reads and the draft checks, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
            definer = connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert definer == (True, "search_path=pg_catalog"), function
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.invoice_adjustment_reversals',%s)",
                    (role, privilege),
                ).fetchone() == (False,), (role, privilege)
    human, prop, payment, invoice_ids = allocation_source(url)
    invoice = invoice_ids[0]
    line = first_line(url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    adjust_credit(url, human, prop, invoice, line, 10_000)
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(prop, request(adjustment), actor=preparer(human, prop))
    reversals().confirm(prop, draft_id(recorded), actor=approver(human, prop))
    for statement in (
        "UPDATE app.invoice_adjustment_reversals SET reason='Changed' "
        "WHERE invoice_adjustment_id=%s",
        "DELETE FROM app.invoice_adjustment_reversals WHERE invoice_adjustment_id=%s",
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error):
                connection.execute(statement, (adjustment,))
            connection.rollback()
    assert reversed_rows(url, adjustment) == [(REASON, human, "financial.approve")]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261218_144"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
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

    with _temporary_migration_database("adjustment_reversal_drafts") as temporary:
        alembic_command.upgrade(config, "20261218_144")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
