"""Budget read for the ledger screen on the real database (phase 6 step 6 part 4).

The years, the accounts a budget can use, the year's budgets with who sent, approved or sent
back each and their lines, and last year's approved lines are read with the runtime login's
rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.ledger_budget_api import (
    ACCOUNTS,
    BUDGETS,
    EARLIER,
    YEARS,
    PostgresLedgerBudget,
)
from property_rental.ledger_money_api import LedgerMoneyNotFound
from test_gl_close_migration import keep_open
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


def test_the_budget_sheet_shows_the_years_budgets_and_last_years_lines(ledger: Books) -> None:
    year = ledger.today.year
    rent = [{"account": "4010", "month_no": month, "amount_cents": 300_000} for month in (1, 2)]
    ledger.call(
        "gl_prepare_budget", ledger.property_id, ledger.owner, year - 1, Jsonb(rent), "Last year"
    )
    accountant = ledger._person("manager", {"ledger.read", "ledger.budgets.prepare"})
    sent = UUID(
        str(
            ledger.call(
                "gl_prepare_budget", ledger.property_id, accountant, year, Jsonb(rent), None
            )
        )
    )
    ledger.call("gl_decide_budget", sent, ledger.owner, False, "Repairs look low")
    again = UUID(
        str(
            ledger.call(
                "gl_prepare_budget", ledger.property_id, accountant, year, Jsonb(rent), None
            )
        )
    )

    flow = PostgresLedgerBudget("postgresql://unused")
    sheet = flow.sheet(ledger.property_id, None)
    assert sheet["year"] == year
    assert {item["fiscal_year"] for item in sheet["years"]} >= {year - 1, year}
    codes = {account["code"]: account for account in sheet["accounts"]}
    assert "4010" in codes and "1010" not in codes
    assert {account["account_type"] for account in sheet["accounts"]} <= {
        "INCOME",
        "COST_OF_SALES",
        "EXPENSE",
    }
    latest, earlier = sheet["budgets"][:2]
    assert latest["id"] == str(again) and latest["status"] == "DRAFT"
    assert latest["created_by"] == str(accountant) and latest["approved_at"] is None
    assert latest["lines"] == [
        {"account_code": "4010", "month_no": 1, "amount_cents": 300_000},
        {"account_code": "4010", "month_no": 2, "amount_cents": 300_000},
    ]
    assert earlier["id"] == str(sent) and earlier["status"] == "REPLACED"
    assert earlier["decision_note"] == "Repairs look low" and earlier["approved_at"] is not None
    assert sheet["earlier_lines"] == latest["lines"]

    last = flow.sheet(ledger.property_id, year - 1)
    assert last["year"] == year - 1
    assert [item["status"] for item in last["budgets"]] == ["APPROVED"]
    assert last["budgets"][0]["own_note"] == "Last year"
    assert last["earlier_lines"] == []
    assert flow.sheet(ledger.property_id, 2001)["year"] == year


def test_the_runtime_login_can_run_the_budget_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    with pytest.raises(LedgerMoneyNotFound):
        PostgresLedgerBudget(runtime_database_url()).sheet(uuid4(), None)
    with psycopg.connect(runtime_database_url()) as connection:
        key = {"prop": uuid4(), "year": 2027}
        for query in (YEARS, ACCOUNTS, BUDGETS, EARLIER):
            connection.execute(query, key)
