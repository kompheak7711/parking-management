"""Fixed asset register read for the ledger screen on the real database (phase 6 step 6 part 4).

Each item with its account, cost, years, each month, depreciation so far and value now, the
Expense it came from, the 1590 balance, today's Asset limit and years, and the last depreciation
entry are read with the runtime login's rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.ledger_assets_api import (
    ACCUMULATED,
    LAST_DEPRECIATION,
    REGISTER,
    RULES,
    PostgresLedgerAssets,
)
from property_rental.ledger_money_api import LedgerMoneyNotFound
from test_gl_assets_migration import buy, last_year, money_in
from test_gl_close_migration import keep_open, month_end, period
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property


@pytest.fixture
def ledger(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Books]:
    """The ledger started on 1 January last year, lent to the read inside a savepoint."""
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        books = Books(connection, property_id, start=False)
        books.call("gl_begin_ledger", property_id, books.owner, books.today.year - 1)
        keep_open(books)
        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
        yield books
        connection.rollback()


def test_the_register_lists_each_item_with_its_value_and_the_1590_balance(ledger: Books) -> None:
    money_in(ledger, "1010", last_year(ledger, 1, 2), 1_000_000)
    expense = buy(ledger, "1530", last_year(ledger, 1, 31), 50_000, "Laptop")
    flow = PostgresLedgerAssets("postgresql://unused")
    before = flow.register(ledger.property_id)
    assert before["today"] == ledger.today.isoformat()
    assert before["accumulated_cents"] == 0 and before["last_depreciation"] is None
    assert before["asset_limit_cents"] == 50_000
    assert set(before["years"]) == {"1510", "1520", "1530"}
    assert before["years"]["1530"] == 3
    laptop = next(item for item in before["assets"] if item["item"] == "Laptop")
    assert laptop["account_code"] == "1530" and laptop["account_name"]
    assert (
        laptop["cost_cents"] == 50_000
        and laptop["bought_on"] == last_year(ledger, 1, 31).isoformat()
    )
    assert laptop["useful_life_years"] == 3 and laptop["monthly_cents"] == 1_388
    assert laptop["depreciation_cents"] == 0 and laptop["value_cents"] == 50_000
    number = ledger.scalar("SELECT expense_number FROM app.gl_expenses WHERE id = %s", (expense,))
    assert laptop["expense_number"] == number and laptop["request_number"] is None
    assert laptop["expense_id"] == str(expense)

    february = period(ledger, ledger.today.year - 1, 2)
    ledger.call("gl_run_month_end", february, ledger.owner)
    after = flow.register(ledger.property_id)
    laptop = next(item for item in after["assets"] if item["item"] == "Laptop")
    assert laptop["depreciation_cents"] == 1_388 and laptop["value_cents"] == 50_000 - 1_388
    assert after["accumulated_cents"] == 1_388
    assert after["last_depreciation"] is not None
    assert (
        after["last_depreciation"]["entry_date"] == month_end(ledger.today.year - 1, 2).isoformat()
    )


def test_the_runtime_login_can_run_the_register_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    with pytest.raises(LedgerMoneyNotFound):
        PostgresLedgerAssets(runtime_database_url()).register(uuid4())
    with psycopg.connect(runtime_database_url()) as connection:
        key = {"prop": uuid4(), "today": date(2027, 1, 31)}
        for query in (REGISTER, ACCUMULATED, RULES, LAST_DEPRECIATION):
            connection.execute(query, key)
