"""D3 (DL-232): an amount missed on a fully paid line is billed with the type of what was missed.

A debit Adjustment is refused on a fully paid line (BR-INV-021). The missed amount is billed on a
new one-time Invoice. Before, that Invoice was always "Other charges", so missed Rent showed as
Other charges income. The owner decided on 12 November 2026 (DL-226, D3) that the new charge keeps
the type of what was missed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from payment_test_support import seed_payment
from property_rental.invoice import (
    CreateItemsInvoiceDraftCommand,
    InvoiceInvalidError,
    InvoiceNotFoundError,
    IssueInvoiceCommand,
)
from test_customer_ledger_migration import canonical_invoice
from test_final_settlement_migration import today
from test_invoice_items_migration import KEYS_LOCK_CLEANING, _create, _items
from test_invoice_migration import invoice_api_actor
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_report_month_facts_migration import facts

REVISION = "20270729_395"
MISSED = 5_000


def paid_rent(url: str) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    """A $500 Rent plus $10 Trash Invoice of July 2026. The Rent line is fully paid, Trash is not.

    Gives the person, the Property, the Customer, the Lease, the Invoice, the Rent line and the
    Trash line.
    """
    human, prop, customer, invoice, rent, trash = canonical_invoice(url)
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT lease_id FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert row is not None
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=50_000
        )
    allocations().post(
        prop, payment, designated(invoice, rent, 50_000), actor=allocation_actor(human, prop)
    )
    return human, prop, customer, UUID(str(row[0])), invoice, rent, trash


def missed(
    customer: UUID, lease: UUID | None, line: UUID, amount: int = MISSED
) -> CreateItemsInvoiceDraftCommand:
    """A one-time charge for an amount missed on ``line``."""
    return replace(
        _create(customer, lease, _items(("Rent of July, missed on the Invoice", 1, amount))),
        missed_on_invoice_line_id=line,
    )


def test_the_missed_amount_migration_follows_the_type_migration_and_is_forward_only() -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "20270728_394"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "forward-only" in source
    assert "DELETE FROM" not in source and "DROP TABLE" not in source


def test_a_missed_amount_on_a_fully_paid_rent_line_is_billed_as_rent(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease, invoice, rent, _ = paid_rent(url)
    staff = invoice_api_actor(human, prop)
    command = missed(customer, lease, rent)
    draft = invoices().create_items_draft(prop, command, actor=staff)
    new = UUID(str(draft["id"]))
    with psycopg.connect(url) as connection:
        number = connection.execute(
            "SELECT invoice_number FROM app.invoices WHERE id=%s", (invoice,)
        ).fetchone()
        assert number is not None
        # The new Invoice is a one-time charge with the type of the Invoice where the amount was
        # missed, and it names that Invoice line.
        assert connection.execute(
            "SELECT primary_category, invoice_type, missed_on_invoice_line_id, status, "
            "original_total_usd_cents FROM app.invoices WHERE id=%s",
            (new,),
        ).fetchone() == ("MISCELLANEOUS_CHARGES", "RENT", rent, "DRAFT", MISSED)
        # The late-payment switch of Rent is the one this Invoice follows.
        with connection.transaction(force_rollback=True):
            connection.execute(
                "ALTER TABLE app.invoice_types DISABLE TRIGGER USER; "
                "UPDATE app.invoice_types SET late_payment = (code = 'RENT')"
            )
            assert connection.execute(
                "SELECT app.invoice_type_late_payment(%s::uuid)", (new,)
            ).fetchone() == (True,)
            connection.execute("UPDATE app.invoice_types SET late_payment = (code <> 'RENT')")
            assert connection.execute(
                "SELECT app.invoice_type_late_payment(%s::uuid)", (new,)
            ).fetchone() == (False,)
    assert draft["invoice_type"] == "RENT"
    assert draft["category"] == "MISCELLANEOUS_CHARGES"
    assert draft["missed_on"] == {
        "invoice_id": str(invoice),
        "invoice_number": number[0],
        "line_id": str(rent),
    }
    # The same request sent again gives the same Invoice.
    assert invoices().create_items_draft(prop, command, actor=staff)["id"] == draft["id"]
    # A one-time charge that names no missed line stays "Other charges".
    plain = invoices().create_items_draft(
        prop, _create(customer, lease, _items(*KEYS_LOCK_CLEANING)), actor=staff
    )
    assert plain["invoice_type"] == "MISCELLANEOUS"
    assert plain["missed_on"] is None


def test_a_missed_amount_needs_a_fully_paid_line_of_the_same_customer_and_lease(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease, _, rent, trash = paid_rent(url)
    staff = invoice_api_actor(human, prop)
    with psycopg.connect(url) as connection:
        before = connection.execute("SELECT count(*) FROM app.invoices").fetchone()
    # The Trash line still has an amount unpaid: a debit Adjustment is the way there.
    with pytest.raises(InvoiceInvalidError):
        invoices().create_items_draft(prop, missed(customer, lease, trash), actor=staff)
    # The new Invoice follows the Customer and the Lease of what was missed.
    with pytest.raises(InvoiceInvalidError):
        invoices().create_items_draft(prop, missed(customer, None, rent), actor=staff)
    with pytest.raises(InvoiceNotFoundError):
        invoices().create_items_draft(prop, missed(customer, lease, uuid4()), actor=staff)
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM app.invoices").fetchone() == before
    draft = invoices().create_items_draft(prop, missed(customer, lease, rent), actor=staff)
    new = UUID(str(draft["id"]))
    with psycopg.connect(url) as connection:
        # The link is kept as it was made, also on a Draft.
        with pytest.raises(psycopg.Error) as changed:
            with connection.transaction():
                connection.execute(
                    "UPDATE app.invoices SET missed_on_invoice_line_id=%s, version=version+1, "
                    "updated_at=statement_timestamp() WHERE id=%s",
                    (trash, new),
                )
        assert changed.value.sqlstate == "55000"
        assert "The missed line is kept as it was made" in str(changed.value)
        # No Invoice states another type than the type of what was missed.
        with pytest.raises(psycopg.Error) as unfit:
            with connection.transaction():
                connection.execute(
                    "INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,"
                    "primary_category,status,invoice_date,due_date,original_total_usd_cents,"
                    "due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,"
                    "invoice_type,missed_on_invoice_line_id) SELECT gen_random_uuid(),"
                    "'INV-D3-UNFIT',customer_id,lease_id,primary_category,'DRAFT',invoice_date,"
                    "NULL,original_total_usd_cents,due_date_rule,due_date_source,created_at,"
                    "created_by,updated_at,updated_by,'UTILITIES',missed_on_invoice_line_id "
                    "FROM app.invoices WHERE id=%s",
                    (new,),
                )
        assert unfit.value.sqlstate == "23514"
        assert "The Invoice type does not fit the Invoice category" in str(unfit.value)


def test_the_income_report_counts_a_missed_amount_with_what_was_missed(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    human, prop, customer, lease, _, rent, _ = paid_rent(url)
    staff = invoice_api_actor(human, prop)
    month = today(url).replace(day=1)

    def rent_of_the_month() -> int:
        return sum(
            cast(int, row[3])
            for row in facts("report_income_facts", human, prop)
            if row[1] == month and row[2] == "RENT"
        )

    def other_of_the_month() -> int:
        return sum(
            cast(int, row[3])
            for row in facts("report_income_facts", human, prop)
            if row[1] == month and row[2] == "MISCELLANEOUS_CHARGES"
        )

    rent_before, other_before = rent_of_the_month(), other_of_the_month()
    draft = invoices().create_items_draft(prop, missed(customer, lease, rent), actor=staff)
    invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=staff,
    )
    # The missed Rent is Rent income of the month of the new Invoice, not Other charges income.
    assert rent_of_the_month() == rent_before + MISSED
    assert other_of_the_month() == other_before
