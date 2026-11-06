"""General Ledger reports on the real database (migration 20270420_270, phase 6 step 5).

The report flow reads the phase 5 report functions and the ledger tables; the Customer debt aging
and the Budget warning rules come from two checked reads that need ``ledger.read``. Each report's
check line is green on books made through the checked money functions.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.ledger_money_api import LedgerMoneyNotFound, LedgerMoneyRefused
from property_rental.ledger_reports import (
    REPORT_NAMES,
    RIEL_HELD_ON,
    TODAY,
    LedgerReport,
    PostgresLedgerReports,
    ReportParams,
    month_end,
    month_start,
)
from test_gl_money_records_migration import Books, Borrowed
from test_gl_money_records_migration import books as books
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url

POST = (
    "SELECT app.gl_post_entry(%s, %s::date, 'AUTO', 'Report test', 'TEST', NULL::uuid, %s, "
    "NULL, %s, NULL::uuid, gen_random_uuid(), %s)"
)


@pytest.fixture
def flow(books: Books, monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresLedgerReports]:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(books.connection))
    yield PostgresLedgerReports("postgresql://unused")


def made_books(books: Books) -> dict[str, Any]:
    """Owner money in the bank, a services sale in cash, a supplier bill paid in part."""
    books.owner_money_in("1020", 100_000)
    books.connection.execute(
        POST,
        (
            books.property_id,
            books.today,
            f"test:{uuid4()}",
            books.owner,
            Jsonb(
                [
                    {"account": "1010", "debit_cents": 80_000},
                    {"account": "4020", "credit_cents": 80_000},
                ]
            ),
        ),
    )
    supplier = books.call(
        "gl_add_supplier", books.property_id, books.staff, "Dara Plumbing", "012 345 678", None
    )
    request = books.submit(books.staff, 3_000, "PAY_LATER", supplier=supplier)
    books.call("gl_decide_expense_request", request, books.manager, True, None)
    expense = books.call(
        "gl_record_request_bill", request, books.manager, 3_000, books.today, "DP-55", None, None
    )
    bill = books.scalar("SELECT id FROM app.gl_supplier_bills WHERE expense_id = %s", (expense,))
    books.call("gl_pay_supplier_bill", bill, books.owner, "1020", books.today, 1_000)
    return {"bill": bill}


def report(
    flow: PostgresLedgerReports, books: Books, name: Any, actor: UUID | None = None, **params: Any
) -> LedgerReport:
    return flow.report(name, books.property_id, str(actor or books.owner), ReportParams(**params))


def named(made: LedgerReport) -> dict[str, dict[str, Any]]:
    return {str(row["name"]): row for row in made.rows if row.get("name")}


def test_every_statement_is_green_on_books_made_by_the_money_functions(
    books: Books, flow: PostgresLedgerReports
) -> None:
    made_books(books)
    today = books.today
    trial = report(flow, books, "trial-balance")
    assert trial.check_ok, trial.check_text
    assert trial.made_on == today and trial.state == "Open, may still change"
    sheet = report(flow, books, "balance-sheet", as_of=today)
    assert sheet.check_ok, sheet.check_text
    assert named(sheet)["Supplier bills to pay"]["amount"] >= 2_000
    profit = report(flow, books, "profit-and-loss", month=today)
    assert profit.check_ok, profit.check_text
    rows = named(profit)
    assert rows["Services"]["this_month"] >= 80_000
    assert rows["Repairs and maintenance"]["this_month"] >= 3_000
    cash = report(flow, books, "cash-flow", start=month_start(today), end=today)
    assert cash.check_ok, cash.check_text
    detail = report(flow, books, "account-detail", account="1020", start=month_start(today))
    assert detail.check_ok, detail.check_text
    assert detail.rows[0]["description"] == "Opening balance"
    bills = report(flow, books, "bills-aging")
    assert bills.check_ok, bills.check_text
    assert {str(row["supplier"]): row["total"] for row in bills.rows}["Dara Plumbing"] == 2_000
    assert bills.state == TODAY


def test_customer_debt_aging_reads_the_unpaid_list_with_the_ledger_right(
    books: Books, flow: PostgresLedgerReports
) -> None:
    aging = report(flow, books, "customer-aging")
    listed = books.scalar(
        "SELECT coalesce(sum(balance_cents), 0) FROM app.gl_customer_aging(%s, %s)",
        (books.property_id, books.owner),
    )
    total = next(row for row in aging.rows if row["line"] == "total")
    assert total["total"] == listed
    in_books = books.balance("1100") + books.balance("1110")
    assert aging.check_ok == (listed == in_books)
    with pytest.raises(LedgerMoneyRefused):
        report(flow, books, "customer-aging", actor=books.staff)
    with pytest.raises(LedgerMoneyRefused):
        report(flow, books, "budget", actor=books.staff, month=books.today)


def test_budget_vs_actual_uses_the_approved_budget_and_the_warning_rules(
    books: Books, flow: PostgresLedgerReports
) -> None:
    made_books(books)
    year_start = books.scalar(
        "SELECT starts_on FROM app.gl_fiscal_years WHERE property_id = %s "
        "AND starts_on <= %s AND ends_on >= %s",
        (books.property_id, books.today, books.today),
    )
    month_no = (books.today.year - year_start.year) * 12 + books.today.month - year_start.month + 1
    empty = report(flow, books, "budget", month=books.today)
    assert not empty.check_ok
    assert empty.check_text == "There is no approved budget for this year"
    lines = [
        {"account": "6050", "month_no": month_no, "amount_cents": 2_000},
        {"account": "4020", "month_no": month_no, "amount_cents": 80_000},
    ]
    books.call(
        "gl_prepare_budget",
        books.property_id,
        books.owner,
        year_start.year,
        Jsonb(lines),
        "My plan",
    )
    budget = report(flow, books, "budget", month=books.today)
    assert budget.extra["budget_version"] >= 1
    assert budget.extra["warning"] == {"percent_hundredths": 1_000, "smallest_cents": 5_000}
    repairs = named(budget)["Repairs and maintenance"]
    assert repairs["budget_month"] == 2_000
    assert repairs["actual_month"] >= 3_000
    assert repairs["month_off"] == (repairs["actual_month"] - 2_000 > 5_000)


def test_an_unknown_account_or_property_is_not_found(
    books: Books, flow: PostgresLedgerReports
) -> None:
    with pytest.raises(LedgerMoneyNotFound):
        report(flow, books, "account-detail", account="9999")
    with pytest.raises(LedgerMoneyNotFound):
        flow.report("trial-balance", uuid4(), str(books.owner), ReportParams())


def test_each_report_answers_and_makes_both_files(
    books: Books, flow: PostgresLedgerReports
) -> None:
    made_books(books)
    for name in REPORT_NAMES:
        extra: dict[str, Any] = {"account": "1010"} if name == "account-detail" else {}
        made = report(flow, books, name, **extra)
        assert made.as_json()["check"]["text"]
        assert made.file("xlsx").content[:2] == b"PK"
        assert made.file("pdf").content.startswith(b"%PDF")
    assert month_end(books.today) >= books.today


def test_the_runtime_login_reads_customer_balances_only_through_the_checked_function(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        for query in (
            "SELECT * FROM app.gl_customer_aging(gen_random_uuid(), gen_random_uuid())",
            "SELECT * FROM app.gl_budget_warning(gen_random_uuid(), gen_random_uuid(), "
            "current_date)",
        ):
            with pytest.raises(psycopg.Error) as caught:
                with runtime.transaction():
                    runtime.execute(query)
            assert caught.value.sqlstate == "42501"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with runtime.transaction():
                runtime.execute("SELECT * FROM app.customer_ledger_balance_sources LIMIT 1")
        # The Balance sheet reads the riel each riel account held (owner 05/11/2026).
        runtime.execute(RIEL_HELD_ON, {"prop": uuid4(), "day": date(2027, 1, 31)})
        runtime.rollback()


def test_the_migration_follows_write_offs() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    found = script.get_revision("20270420_270")
    assert found is not None and found.down_revision == "20270419_269"
