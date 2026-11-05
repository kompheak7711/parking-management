"""General Ledger books reads on the real database (phase 6 step 6 part 1).

The accounts, the journal entries and one entry are read with the runtime login's rights, and
each entry names the app record it came from.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from property_rental.ledger_books_api import PostgresLedgerBooks
from property_rental.ledger_money_api import LedgerMoneyNotFound
from test_gl_money_records_migration import Books, Borrowed
from test_gl_money_records_migration import books as books
from test_gl_reports_migration import made_books
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url


@pytest.fixture
def flow(books: Books, monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresLedgerBooks]:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(books.connection))
    yield PostgresLedgerBooks("postgresql://unused")


def test_the_chart_shows_each_balance_on_its_normal_side(
    books: Books, flow: PostgresLedgerBooks
) -> None:
    made_books(books)
    chart = flow.accounts(books.property_id, None)
    by_code = {row["code"]: row for row in chart["accounts"]}
    assert chart["as_of"] == books.today.isoformat()
    assert by_code["1010"]["balance_cents"] == books.balance("1010")
    assert by_code["4020"]["balance_cents"] == -books.balance("4020")
    assert by_code["4020"]["balance_cents"] >= 80_000
    assert by_code["1100"]["control_source"] == "INVOICES" and by_code["2400"]["tax_locked"]
    assert by_code["1010"]["used"] and not by_code["2400"]["used"]
    assert by_code["1021"]["cash_kind"] == "BANK_KHR" and by_code["4020"]["cash_kind"] is None
    early = flow.accounts(books.property_id, books.today.replace(year=books.today.year - 1))
    assert {row["code"]: row for row in early["accounts"]}["4020"]["balance_cents"] == 0


def test_the_journal_lists_entries_newest_first_with_their_app_record(
    books: Books, flow: PostgresLedgerBooks
) -> None:
    made = made_books(books)
    bill_number = books.scalar(
        "SELECT bill_number FROM app.gl_supplier_bills WHERE id = %s", (made["bill"],)
    )
    journal = flow.entries(books.property_id, None)
    assert journal["newest_only"] and journal["month"] is None
    assert books.today.replace(day=1).isoformat() in journal["months"]
    rows = journal["entries"]
    assert rows == sorted(
        rows, key=lambda row: (row["entry_date"], row["entry_number"]), reverse=True
    )
    paid = next(row for row in rows if row["source_type"] == "BILL_PAYMENT")
    assert paid["source_number"] == bill_number and paid["amount_cents"] == 1_000
    expense = next(row for row in rows if row["source_type"] == "EXPENSE")
    assert expense["source_number"] is not None and expense["source_number"].startswith("EX")
    month = flow.entries(books.property_id, books.today.replace(day=1))
    assert month["month"] == books.today.replace(day=1).isoformat() and not month["newest_only"]
    assert {row["entry_number"] for row in month["entries"]} >= {paid["entry_number"]}


def test_one_entry_shows_its_lines_and_who_posted_it(
    books: Books, flow: PostgresLedgerBooks
) -> None:
    made_books(books)
    first = flow.entries(books.property_id, None)["entries"][0]
    entry = flow.entry(books.property_id, first["entry_number"])
    assert entry["entry_number"] == first["entry_number"]
    debit = sum(line["debit_cents"] for line in entry["lines"])
    assert debit == sum(line["credit_cents"] for line in entry["lines"]) == entry["amount_cents"]
    assert entry["posted_at"] is not None and entry["month_closed"] is False
    with pytest.raises(LedgerMoneyNotFound):
        flow.entry(books.property_id, "JE999999")


def test_the_runtime_login_can_read_what_the_books_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    flow = PostgresLedgerBooks(runtime_database_url())
    with pytest.raises(LedgerMoneyNotFound):
        flow.accounts(uuid4(), None)
    with psycopg.connect(runtime_database_url()) as runtime:
        for table in (
            "gl_accounts",
            "gl_journal_entries",
            "gl_journal_lines",
            "gl_periods",
            "gl_expenses",
            "gl_expense_requests",
            "gl_staff_paybacks",
            "gl_bill_payments",
            "gl_supplier_bills",
            "gl_money_moves",
            "gl_adjusting_entries",
            "invoices",
            "invoice_lines",
            "invoice_adjustments",
            "late_payment_charges",
            "receipts",
            "payment_allocations",
            "deposit_receipts",
            "refunds",
            "refund_corrections",
            "user_accounts",
        ):
            runtime.execute(f"SELECT 1 FROM app.{table} LIMIT 1")
