"""A debit Adjustment needs a positive line balance; the Invoice lock orders late fees."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.billing import PostgresRentBillingService
from property_rental.invoice import (
    AdjustInvoiceCommand,
    AdjustmentType,
    InvoiceLineFullyPaid,
    PostgresInvoiceService,
)
from property_rental.late_payment import (
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
    LatePaymentInvalidError,
)
from property_rental.payment_allocation import ReverseAllocationCommand
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credit_service
from test_invoice_migration import financial_database_url, invoice_api_actor, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import late_payment_actor, setup_invoice
from test_late_payment_migration import service as late_service
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_payment_allocation_migration import source as allocation_source


def invoices() -> PostgresInvoiceService:
    return PostgresInvoiceService(runtime_database_url(), financial_database_url())


def first_line(url: str, invoice: UUID) -> UUID:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT id FROM app.invoice_lines WHERE invoice_id=%s ORDER BY line_sequence",
            (invoice,),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def outstanding(url: str, line: UUID) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute("SELECT app.invoice_line_outstanding(%s)", (line,)).fetchone()
    assert row is not None
    return int(str(row[0]))


def debit(
    url: str, human: UUID, prop: UUID, invoice: UUID, line: UUID, amount: int
) -> dict[str, object]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
    assert row is not None
    return invoices().adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.DEBIT,
            amount,
            f"approved-debit/{uuid4()}",
            "Approved missed amount",
            int(str(row[0])),
        ),
        actor=invoice_api_actor(human, prop),
    )


def test_debit_needs_a_positive_line_balance_and_reopens_after_payment_reversal(
    migrated_database_url: str,
) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    staff = allocation_actor(human, prop)
    debit(migrated_database_url, human, prop, invoice, line, 500)
    allocation_service().post(
        prop, payment, allocation_designated(invoice, line, 20_000), actor=staff
    )
    debit(migrated_database_url, human, prop, invoice, line, 100)
    remaining = outstanding(migrated_database_url, line)
    assert remaining == 60_600
    paid = allocation_service().post(
        prop, payment, allocation_designated(invoice, line, remaining), actor=staff
    )
    assert outstanding(migrated_database_url, line) == 0
    with pytest.raises(InvoiceLineFullyPaid) as blocked:
        debit(migrated_database_url, human, prop, invoice, line, 1)
    assert blocked.value.line_balance_usd_cents == 0
    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_line_id=%s", (line,)
        ).fetchone() == (2,)
    allocation = cast(list[object], paid["allocation_ids"])[0]
    allocation_service().reverse_allocation(
        prop,
        UUID(str(allocation)),
        ReverseAllocationCommand(uuid4(), "Undo final allocation"),
        actor=staff,
    )
    assert outstanding(migrated_database_url, line) == 60_600
    debit(migrated_database_url, human, prop, invoice, line, 1)
    assert outstanding(migrated_database_url, line) == 60_601


def test_mixed_invoice_blocks_the_paid_rent_line_but_not_the_unpaid_service_line(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, _ = setup_billing_source(connection)
    result = PostgresRentBillingService(financial_database_url(), prop, human).generate(
        initial_command(lease, uuid4()), actor=authenticated(human, prop)
    )
    invoice = result.invoice_id
    with psycopg.connect(migrated_database_url) as connection:
        lines: dict[str, object] = dict(
            connection.execute(
                "SELECT category,id FROM app.invoice_lines WHERE invoice_id=%s "
                "AND category IN ('RENT','SERVICE_CHARGES') ORDER BY line_sequence",
                (invoice,),
            ).fetchall()
        )
        rent, service_line = UUID(str(lines["RENT"])), UUID(str(lines["SERVICE_CHARGES"]))
        rent_due = outstanding(migrated_database_url, rent)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=rent_due
        )
    allocation_service().post(
        prop,
        payment,
        allocation_designated(invoice, rent, rent_due),
        actor=allocation_actor(human, prop),
    )
    with pytest.raises(InvoiceLineFullyPaid):
        debit(migrated_database_url, human, prop, invoice, rent, 1)
    service_due = outstanding(migrated_database_url, service_line)
    debit(migrated_database_url, human, prop, invoice, service_line, 50)
    assert outstanding(migrated_database_url, service_line) == service_due + 50


def test_debit_is_rejected_on_a_line_paid_by_customer_credit(migrated_database_url: str) -> None:
    human, prop, credit, invoice, line, _ = credit_source(migrated_database_url)
    credit_service().apply(
        prop,
        credit,
        credit_designated(invoice, line, outstanding(migrated_database_url, line)),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    with pytest.raises(InvoiceLineFullyPaid):
        debit(migrated_database_url, human, prop, invoice, line, 1)


def test_direct_debit_on_a_fully_paid_line_is_rejected_by_storage(
    migrated_database_url: str,
) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    allocation_service().post(
        prop,
        payment,
        allocation_designated(invoice, line, outstanding(migrated_database_url, line)),
        actor=allocation_actor(human, prop),
    )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as rejected:
            with connection.transaction():
                connection.execute(
                    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,"
                    "adjustment_type,amount_usd_cents,source_reference,reason,occurred_at,"
                    "actor_id,authorization_reference) VALUES (%s,%s,%s,'DEBIT',1,"
                    "'direct-paid-debit','Bypasses the command',clock_timestamp(),%s,"
                    "'invoices.adjust')",
                    (uuid4(), invoice, line, human),
                )
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert rejected.value.sqlstate == "23514"


def overdue_invoice(url: str) -> tuple[UUID, UUID, UUID, UUID]:
    with psycopg.connect(url) as connection:
        human, prop, _, invoice, line = setup_invoice(connection, period_start=date(2026, 5, 1))
    return human, prop, invoice, line


def finalize_default(human: UUID, prop: UUID, invoice: UUID) -> dict[str, object]:
    who = late_payment_actor(human, prop)
    review = late_service().review(invoice, actor=who)
    amount = cast(dict[str, int], review["calculated_default_amount"])["minor_units"]
    return late_service().finalize_decision(
        prop,
        invoice,
        FinalizeLatePaymentDecisionCommand(
            uuid4(), DecisionOutcome.CONFIRMED_DEFAULT, amount, "Approved default"
        ),
        actor=who,
    )


def decision_and_charge(url: str, invoice: UUID) -> tuple[Any, ...]:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT to_jsonb(d),to_jsonb(c) FROM app.late_payment_decisions d "
            "LEFT JOIN app.late_payment_charges c ON c.late_payment_decision_id=d.id "
            "WHERE d.source_invoice_id=%s",
            (invoice,),
        ).fetchone()
    assert row is not None
    return row


def test_debit_before_decision_counts_and_after_decision_is_not_counted(
    migrated_database_url: str,
) -> None:
    human, prop, invoice, line = overdue_invoice(migrated_database_url)
    before_balance = outstanding(migrated_database_url, line)
    debit(migrated_database_url, human, prop, invoice, line, 1_000)
    finalize_default(human, prop, invoice)
    decided = decision_and_charge(migrated_database_url, invoice)
    assert decided[0]["overdue_balance_at_assessment_usd_cents"] == before_balance + 1_000
    debit(migrated_database_url, human, prop, invoice, line, 2_000)
    assert outstanding(migrated_database_url, line) == before_balance + 3_000
    assert decision_and_charge(migrated_database_url, invoice) == decided


def test_concurrent_debit_and_decision_are_ordered_by_the_invoice_lock(
    migrated_database_url: str,
) -> None:
    human, prop, invoice, line = overdue_invoice(migrated_database_url)
    base = outstanding(migrated_database_url, line)
    barrier = Barrier(2)

    def run_debit() -> object:
        barrier.wait()
        return debit(migrated_database_url, human, prop, invoice, line, 700)

    def run_decision() -> object:
        barrier.wait()
        try:
            return finalize_default(human, prop, invoice)
        except (LatePaymentConflictError, LatePaymentInvalidError) as exc:
            return exc

    with ThreadPoolExecutor(2) as pool:
        debit_future = pool.submit(run_debit)
        decision_future = pool.submit(run_decision)
        debit_future.result()
        decision_result = decision_future.result()
    if isinstance(decision_result, Exception):
        # The debit landed inside the review window; a fresh review is required.
        finalize_default(human, prop, invoice)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT adjustment.occurred_at<decision.assessed_at,"
            "decision.overdue_balance_at_assessment_usd_cents "
            "FROM app.invoice_adjustments adjustment "
            "JOIN app.late_payment_decisions decision "
            "ON decision.source_invoice_id=adjustment.invoice_id "
            "WHERE adjustment.invoice_line_id=%s",
            (line,),
        ).fetchone()
    assert row is not None
    debit_first, counted = row
    assert counted == (base + 700 if debit_first else base)


def test_fully_paid_conflict_maps_to_its_line_balance() -> None:
    class Rejected(psycopg.Error):
        sqlstate = "P4509"

    mapped = PostgresInvoiceService._map_error(Rejected("Invoice line is fully paid; balance:0"))
    assert isinstance(mapped, InvoiceLineFullyPaid) and mapped.line_balance_usd_cents == 0


def test_debit_adjustment_line_block_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261003_66")
    assert revision is not None and revision.down_revision == "20261002_65"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
