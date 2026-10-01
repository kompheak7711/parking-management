"""Credit Adjustment excess becomes Customer Credit through append-only reversal and re-post."""

from datetime import date
from pathlib import Path
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
    InvoiceInvalidError,
    PostgresInvoiceService,
    VoidInvoiceCommand,
)
from property_rental.payment_allocation import PostAllocationsCommand
from test_billing_service_migration import authenticated, initial_command, setup_billing_source
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credit_service
from test_debit_adjustment_line_block_migration import finalize_default, first_line, outstanding
from test_invoice_migration import financial_database_url, invoice_api_actor, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import setup_invoice
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated as allocation_designated
from test_payment_allocation_migration import service as allocation_service
from test_payment_allocation_migration import source as allocation_source

REASON = "Invoice adjustment credit excess"


def invoices() -> PostgresInvoiceService:
    return PostgresInvoiceService(runtime_database_url(), financial_database_url())


def version(url: str, invoice: UUID) -> int:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT version FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
    assert row is not None
    return int(str(row[0]))


def credit_command(url: str, invoice: UUID, line: UUID, amount: int) -> AdjustInvoiceCommand:
    return AdjustInvoiceCommand(
        uuid4(),
        line,
        AdjustmentType.CREDIT,
        amount,
        f"approved-credit/{uuid4()}",
        "Approved credit",
        version(url, invoice),
    )


def credit(
    url: str, human: UUID, prop: UUID, invoice: UUID, line: UUID, amount: int
) -> dict[str, object]:
    return invoices().adjust(
        prop,
        invoice,
        credit_command(url, invoice, line, amount),
        actor=invoice_api_actor(human, prop),
    )


def rows(url: str, query: str, *parameters: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as connection:
        return connection.execute(query, parameters).fetchall()


def pay(prop: UUID, payment: UUID, invoice: UUID, line: UUID, amount: int, human: UUID) -> object:
    return allocation_service().post(
        prop,
        payment,
        allocation_designated(invoice, line, amount),
        actor=allocation_actor(human, prop),
    )


def test_credit_within_unpaid_value_records_no_customer_credit(migrated_database_url: str) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    result = credit(migrated_database_url, human, prop, invoice, line, 10_000)
    assert "adjustment_effect" not in result
    assert outstanding(migrated_database_url, line) == 50_000
    assert rows(
        migrated_database_url,
        "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
        payment,
    ) == [(0,)]


def test_credit_beyond_unpaid_value_reverses_and_reposts_with_reason(
    migrated_database_url: str,
) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    posted = cast(dict[str, object], pay(prop, payment, invoice, line, 20_000, human))
    original = UUID(str(cast(list[object], posted["allocation_ids"])[0]))
    command = credit_command(migrated_database_url, invoice, line, 70_000)
    result = invoices().adjust(prop, invoice, command, actor=invoice_api_actor(human, prop))
    effect = cast(dict[str, object], result["adjustment_effect"])
    assert effect["customer_credit_usd_cents"] == 10_000
    assert result["status"] == "PAID"
    assert outstanding(migrated_database_url, line) == 0
    assert invoices().adjust(prop, invoice, command, actor=invoice_api_actor(human, prop)) == result
    assert rows(
        migrated_database_url,
        "SELECT reason FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s",
        original,
    ) == [(REASON,)]
    release = rows(
        migrated_database_url,
        "SELECT r.replacement_payment_allocation_id,r.released_usd_cents,a.amount_usd_cents,"
        "a.between_invoice_basis,c.customer_id,c.recognized_usd_cents,c.reason,i.customer_id "
        "FROM app.invoice_credit_excess_releases r "
        "JOIN app.payment_allocations a ON a.id=r.replacement_payment_allocation_id "
        "JOIN app.customer_credits c ON c.id=r.customer_credit_id "
        "JOIN app.invoices i ON i.id=a.invoice_id WHERE r.reversed_payment_allocation_id=%s",
        original,
    )
    assert len(release) == 1
    replacement, released, amount, basis, owner, recognized, reason, invoice_customer = release[0]
    assert (released, amount, basis, recognized, reason) == (
        10_000,
        10_000,
        "CUSTOMER_DESIGNATED",
        10_000,
        REASON,
    )
    assert owner == invoice_customer
    assert rows(
        migrated_database_url,
        "SELECT reason FROM app.audit_events WHERE action='payment_allocation.posted' "
        "AND entity_id=%s",
        replacement,
    ) == [(REASON,)]
    assert rows(
        migrated_database_url,
        "SELECT allocated_usd_cents,available_usd_cents FROM app.payment_financial_position "
        "WHERE payment_id=%s",
        payment,
    ) == [(10_000, 80_000)]


def test_credit_on_fully_paid_line_becomes_customer_credit_whole(
    migrated_database_url: str,
) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    pay(prop, payment, invoice, line, 80_000, human)
    result = credit(migrated_database_url, human, prop, invoice, line, 5_000)
    effect = cast(dict[str, object], result["adjustment_effect"])
    assert effect["customer_credit_usd_cents"] == 5_000
    assert rows(
        migrated_database_url,
        "SELECT sum(recognized_usd_cents) FROM app.customer_credits WHERE source_payment_id=%s",
        payment,
    ) == [(5_000,)]


def test_newest_payment_allocation_is_released_first(migrated_database_url: str) -> None:
    human, prop, older_payment, invoice_ids = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    with psycopg.connect(migrated_database_url) as connection:
        customer = connection.execute(
            "SELECT customer_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert customer is not None
        newer_payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer[0], amount=30_000
        )
    pay(prop, older_payment, invoice, line, 30_000, human)
    pay(prop, newer_payment, invoice, line, 30_000, human)
    credit(migrated_database_url, human, prop, invoice, line, 30_000)
    assert rows(
        migrated_database_url,
        "SELECT source_payment_id,recognized_usd_cents FROM app.customer_credits "
        "WHERE source_payment_id IN (%s,%s)",
        older_payment,
        newer_payment,
    ) == [(newer_payment, 10_000)]
    assert rows(
        migrated_database_url,
        "SELECT count(*) FROM app.payment_allocation_reversals r JOIN app.payment_allocations a "
        "ON a.id=r.payment_allocation_id WHERE a.payment_id=%s",
        older_payment,
    ) == [(0,)]


def test_multi_line_allocation_keeps_other_line_value_after_repost(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, lease, _ = setup_billing_source(connection)
    invoice = (
        PostgresRentBillingService(financial_database_url(), prop, human)
        .generate(initial_command(lease, uuid4()), actor=authenticated(human, prop))
        .invoice_id
    )
    lines = rows(
        migrated_database_url,
        "SELECT category,id FROM app.invoice_lines WHERE invoice_id=%s "
        "AND category IN ('RENT','SERVICE_CHARGES') ORDER BY line_sequence",
        invoice,
    )
    rent = UUID(str(next(value for kind, value in lines if kind == "RENT")))
    other = UUID(str(next(value for kind, value in lines if kind == "SERVICE_CHARGES")))
    rent_due = outstanding(migrated_database_url, rent)
    other_due = outstanding(migrated_database_url, other)
    with psycopg.connect(migrated_database_url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=customer,
            amount=rent_due + other_due,
        )
    allocation_service().post(
        prop,
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DESIGNATED",
                "designation_reference": "Explicit customer instruction",
                "targets": [
                    {
                        "invoice_id": str(invoice),
                        "amount_usd_cents": rent_due + other_due,
                        "details": [
                            {"invoice_line_id": str(rent), "amount_usd_cents": rent_due},
                            {"invoice_line_id": str(other), "amount_usd_cents": other_due},
                        ],
                    }
                ],
            },
        ),
        actor=allocation_actor(human, prop),
    )
    credit(migrated_database_url, human, prop, invoice, rent, 1_000)
    assert outstanding(migrated_database_url, other) == 0
    assert rows(
        migrated_database_url,
        "SELECT d.invoice_line_id,d.posted_amount_usd_cents "
        "FROM app.invoice_credit_excess_releases r "
        "JOIN app.payment_allocation_details d "
        "ON d.payment_allocation_id=r.replacement_payment_allocation_id "
        "JOIN app.payment_allocations a ON a.id=r.reversed_payment_allocation_id "
        "WHERE a.payment_id=%s ORDER BY d.detail_sequence",
        payment,
    ) == [(rent, rent_due - 1_000), (other, other_due)]


def test_credit_application_excess_returns_to_that_credit(migrated_database_url: str) -> None:
    human, prop, customer_credit, invoice, line, payment = credit_source(migrated_database_url)
    credit_service().apply(
        prop,
        customer_credit,
        credit_designated(invoice, line, outstanding(migrated_database_url, line)),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    available = rows(
        migrated_database_url, "SELECT app.credit_available_value(%s)", customer_credit
    )[0][0]
    result = credit(migrated_database_url, human, prop, invoice, line, 5_000)
    effect = cast(dict[str, object], result["adjustment_effect"])
    assert effect["returned_to_customer_credit_usd_cents"] == 5_000
    assert effect["customer_credit_usd_cents"] == 0
    assert rows(
        migrated_database_url, "SELECT app.credit_available_value(%s)", customer_credit
    ) == [(available + 5_000,)]
    assert rows(
        migrated_database_url,
        "SELECT count(*) FROM app.customer_credits WHERE source_payment_id=%s",
        payment,
    ) == [(1,)]
    assert rows(
        migrated_database_url,
        "SELECT r.reason FROM app.customer_credit_application_reversals r "
        "JOIN app.invoice_credit_excess_releases e "
        "ON e.reversed_credit_application_id=r.credit_application_id "
        "JOIN app.customer_credit_applications a ON a.id=r.credit_application_id "
        "WHERE a.customer_credit_id=%s",
        customer_credit,
    ) == [(REASON,)]


def test_credit_beyond_obligation_or_on_a_void_invoice_is_rejected(
    migrated_database_url: str,
) -> None:
    human, prop, payment, invoice_ids = allocation_source(migrated_database_url)
    invoice, other_invoice = invoice_ids
    line = first_line(migrated_database_url, invoice)
    pay(prop, payment, invoice, line, 20_000, human)
    with pytest.raises(InvoiceInvalidError):
        credit(migrated_database_url, human, prop, invoice, line, 80_001)
    other_line = first_line(migrated_database_url, other_invoice)
    invoices().void(
        prop,
        other_invoice,
        VoidInvoiceCommand(
            uuid4(), "Issued in error", version(migrated_database_url, other_invoice)
        ),
        actor=invoice_api_actor(human, prop),
    )
    with pytest.raises(InvoiceInvalidError):
        credit(migrated_database_url, human, prop, other_invoice, other_line, 1_000)


def test_third_party_paid_excess_belongs_to_the_invoice_customer(
    migrated_database_url: str,
) -> None:
    human, prop, _, invoice_ids = allocation_source(migrated_database_url)
    _, _, other_payment, _ = allocation_source(migrated_database_url)
    invoice = invoice_ids[0]
    line = first_line(migrated_database_url, invoice)
    with psycopg.connect(migrated_database_url) as connection:
        payer = connection.execute(
            "SELECT payer_customer_id FROM app.payments WHERE id=%s", (other_payment,)
        ).fetchone()
        assert payer is not None
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=UUID(str(payer[0])),
            amount=100_000,
            scope="THIRD_PARTY_IDENTIFIED",
            invoice_id=invoice,
        )
    staff = allocation_actor(human, prop)
    proposal = allocation_service().proposal(prop, payment, actor=staff)
    allocation_service().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    assert outstanding(migrated_database_url, line) == 0
    credit(migrated_database_url, human, prop, invoice, line, 5_000)
    owners = rows(
        migrated_database_url,
        "SELECT c.customer_id,i.customer_id,c.recognized_usd_cents FROM app.customer_credits c "
        "JOIN app.invoice_credit_excess_releases r ON r.customer_credit_id=c.id "
        "JOIN app.invoice_adjustments a ON a.id=r.invoice_adjustment_id "
        "JOIN app.invoices i ON i.id=a.invoice_id WHERE c.source_payment_id=%s",
        payment,
    )
    assert len(owners) == 1
    assert owners[0][0] == owners[0][1] != payer[0] and owners[0][2] == 5_000


HISTORY = {
    "decisions": "SELECT to_jsonb(d) FROM app.late_payment_decisions d "
    "WHERE d.source_invoice_id=%s",
    "charges": "SELECT to_jsonb(c) FROM app.late_payment_charges c WHERE c.source_invoice_id=%s",
    "payment": "SELECT to_jsonb(p) FROM app.payments p WHERE p.id=%s",
    "receipts": "SELECT to_jsonb(r) FROM app.receipts r WHERE r.payment_id=%s ORDER BY r.id",
    "cases": "SELECT to_jsonb(c) FROM app.rent_nonpayment_cases c "
    "WHERE c.lease_id=%s ORDER BY c.id",
    "events": "SELECT to_jsonb(e) FROM app.rent_nonpayment_events e "
    "JOIN app.rent_nonpayment_cases c ON c.id=e.rent_nonpayment_case_id "
    "WHERE c.lease_id=%s ORDER BY e.id",
    "original_allocations": "SELECT to_jsonb(a) FROM app.payment_allocations a "
    "WHERE a.payment_id=%s AND NOT EXISTS(SELECT 1 FROM app.invoice_credit_excess_releases r "
    "WHERE r.replacement_payment_allocation_id=a.id) ORDER BY a.id",
}


def history(url: str, lease: UUID, payment: UUID, invoice: UUID) -> dict[str, list[Any]]:
    argument = {
        "decisions": invoice,
        "charges": invoice,
        "payment": payment,
        "receipts": payment,
        "cases": lease,
        "events": lease,
        "original_allocations": payment,
    }
    with psycopg.connect(url) as connection:
        return {
            name: connection.execute(query, (argument[name],)).fetchall()
            for name, query in HISTORY.items()
        }


def test_excess_release_rewrites_no_late_fee_nonpayment_payment_or_receipt_history(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        human, prop, customer, invoice, line = setup_invoice(
            connection, period_start=date(2026, 5, 1)
        )
        lease_row = connection.execute(
            "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert lease_row is not None
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=30_000
        )
    lease = UUID(str(lease_row[0]))
    pay(prop, payment, invoice, line, 30_000, human)
    finalize_default(human, prop, invoice)
    before = history(migrated_database_url, lease, payment, invoice)
    assert len(before["decisions"]) == 1
    due = outstanding(migrated_database_url, line)
    result = credit(migrated_database_url, human, prop, invoice, line, due + 2_000)
    effect = cast(dict[str, object], result["adjustment_effect"])
    assert effect["customer_credit_usd_cents"] == 2_000
    assert history(migrated_database_url, lease, payment, invoice) == before


def test_credit_adjustment_excess_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261003_67")
    assert revision is not None and revision.down_revision == "20261003_66"
    module = cast(Any, revision.module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
