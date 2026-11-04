"""Spending reads for the ledger screens on the real database (phase 6 step 6 part 2).

The request and expense forms, one Expense request with its steps, and the lists of requests,
expenses and supplier bills are read with the runtime login's rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.ledger_money_api import VIEWS, LedgerMoneyNotFound, PostgresLedgerMoneyFlow
from property_rental.ledger_spending_api import (
    ADVANCE,
    EXPENSES,
    MONEY_ACCOUNTS,
    PAYBACKS,
    RATE,
    RULES,
    SPEND_ACCOUNTS,
    STEPS,
    SUPPLIERS,
    UNITS,
    PostgresLedgerSpending,
)
from test_gl_money_records_migration import Books, Borrowed
from test_gl_money_records_migration import books as books
from test_gl_reports_migration import made_books
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url


@pytest.fixture
def borrowed(books: Books, monkeypatch: pytest.MonkeyPatch) -> Iterator[Books]:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(books.connection))
    yield books


def number(books: Books, request: UUID) -> str:
    return str(
        books.scalar("SELECT request_number FROM app.gl_expense_requests WHERE id = %s", (request,))
    )


def test_the_form_answers_the_rules_accounts_suppliers_and_units(borrowed: Books) -> None:
    books = borrowed
    made_books(books)
    form = PostgresLedgerSpending("postgresql://unused").form(books.property_id)
    assert form["today"] == books.today.isoformat()
    assert form["report_days"] >= 1 and form["bill_days"] >= 1
    codes = [row["code"] for row in form["accounts"]]
    assert "6050" in codes and "1520" in codes
    # 1300 Stock of products cannot take an expense (gl_spend_account), so it is not offered.
    assert not {"6030", "6140", "6160", "1010", "1300"} & set(codes)
    assert {row["code"] for row in form["money_accounts"]} >= {"1010", "1011", "1020", "1030"}
    assert all(row["code"].startswith("10") for row in form["money_accounts"])
    assert form["suppliers"] and all(row["name"] for row in form["suppliers"])
    assert isinstance(form["units"], list)


def test_one_request_shows_its_steps_advance_bill_and_entries(borrowed: Books) -> None:
    books = borrowed
    request = books.submit(books.staff, 5_000, "ADVANCE")
    books.call("gl_decide_expense_request", request, books.manager, True, None)
    books.call("gl_give_advance", request, books.manager, "1010", books.today)
    flow = PostgresLedgerSpending("postgresql://unused")
    given = flow.request(books.property_id, number(books, request), None)
    assert given["status"] == "PAID_OUT" and given["advance_late"] is False
    assert given["advance"]["amount_cents"] == 5_000
    assert given["advance"]["from_code"] == "1010"
    assert given["advance"]["entry_number"] == given["advance_entry_number"]
    books.call(
        "gl_record_request_bill", request, books.manager, 4_000, books.today, "INV-7", None, None
    )
    done = flow.request(books.property_id, number(books, request), None)
    assert [step["step"] for step in done["steps"]][:3] == ["SUBMITTED", "APPROVED", "PAID_OUT"]
    assert done["steps"][-1]["step"] in {"BILL_BACK", "DONE"}
    assert done["expenses"][0]["amount_cents"] == 4_000
    assert done["expenses"][0]["bill_number"] == "INV-7"
    assert done["expenses"][0]["entry_number"]
    assert done["paybacks"] == []
    # A Staff member reads only their own requests.
    with pytest.raises(LedgerMoneyNotFound):
        flow.request(books.property_id, number(books, request), str(books.other_staff))
    assert flow.request(books.property_id, number(books, request), str(books.staff))["id"]
    with pytest.raises(LedgerMoneyNotFound):
        flow.request(books.property_id, "ER999999", None)


def test_the_lists_name_people_units_entries_and_bill_payments(borrowed: Books) -> None:
    books = borrowed
    made = made_books(books)
    money = PostgresLedgerMoneyFlow("postgresql://unused")
    requests = money.expense_requests(books.property_id, requested_by=None)
    assert requests[0]["account_name_km"] and "advance_late" in requests[0]
    assert "requested_by_name" in requests[0] and "unit_number" in requests[0]
    expenses = money.rows("expenses", books.property_id)
    assert all(row["entry_number"] for row in expenses if row["status"] == "POSTED")
    assert any(row["supplier_bill_number"] for row in expenses)
    bills = money.rows("supplier-bills", books.property_id)
    bill = next(row for row in bills if row["id"] == str(made["bill"]))
    assert bill["account_code"] == "6050" and bill["entry_number"]
    # Sums of cents go to the screen as whole numbers, never as strings (owner 04/11/2026).
    assert type(bill["still_to_pay_cents"]) is int
    assert all(type(row["owed_to_staff_cents"]) is int for row in requests)
    assert bill["payments"][0]["amount_cents"] == 1_000
    assert bill["payments"][0]["paid_from_code"] == "1020"
    assert bill["payments"][0]["reversed"] is False
    assert bill["payments"][0]["paid_from_name"]
    paid = next(row for row in expenses if row["supplier_bill_number"] == bill["bill_number"])
    assert paid["bill_has_payments"] is True and paid["voided_by_name"] is None

    # A reversed payment says who, when, why and its entry; the bill's expense can then be voided.
    payment = UUID(bill["payments"][0]["id"])
    books.call("gl_reverse_bill_payment", payment, books.owner, "Paid twice")
    again = next(
        row for row in money.rows("supplier-bills", books.property_id) if row["id"] == bill["id"]
    )
    reversed_payment = again["payments"][0]
    assert reversed_payment["reversed"] is True
    assert reversed_payment["reversal_reason"] == "Paid twice"
    assert reversed_payment["reversed_at"] and reversed_payment["reversal_entry_number"]
    assert "reversed_by_name" in reversed_payment
    books.call("gl_void_expense", UUID(paid["id"]), books.owner, "Wrong supplier")
    voided = next(
        row for row in money.rows("expenses", books.property_id) if row["id"] == paid["id"]
    )
    assert voided["status"] == "VOID" and voided["void_reason"] == "Wrong supplier"
    assert voided["voided_at"] and voided["void_entry_number"]
    assert voided["bill_has_payments"] is False


def test_the_runtime_login_can_run_the_spending_reads(migrated_database_url: str) -> None:
    assert migrated_database_url
    flow = PostgresLedgerSpending(runtime_database_url())
    with pytest.raises(LedgerMoneyNotFound):
        flow.form(uuid4())
    with pytest.raises(LedgerMoneyNotFound):
        flow.request(uuid4(), "ER270001", None)
    money = PostgresLedgerMoneyFlow(runtime_database_url())
    with pytest.raises(LedgerMoneyNotFound):
        money.expense_requests(uuid4(), requested_by=None)
    with psycopg.connect(runtime_database_url()) as connection:
        for query in (RULES, SPEND_ACCOUNTS, MONEY_ACCOUNTS, SUPPLIERS, UNITS):
            connection.execute(query, {"prop": uuid4(), "today": date(2027, 1, 31)})
        with pytest.raises(psycopg.errors.NoDataFound), connection.transaction():
            connection.execute(RATE, {"prop": uuid4()})
        for query in (STEPS, EXPENSES, PAYBACKS, ADVANCE):
            connection.execute(query, {"id": uuid4()})
        for view in ("expenses", "supplier-bills"):
            connection.execute(VIEWS[view], {"prop": uuid4()})
