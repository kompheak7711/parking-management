"""Month-end close read for the ledger screen on the real database (phase 6 step 6 part 4).

The months with who closed them, the years with their close, and one month's checks, its
depreciation entry and its riel valuation are read with the runtime login's rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.ledger_money_api import LedgerMoneyNotFound
from property_rental.ledger_month_end_api import (
    CHECKS,
    DEPRECIATION,
    MONTHS,
    RIEL,
    YEARS,
    PostgresLedgerMonthEnd,
)
from test_gl_close_migration import begin, count_cash, month_end, period
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property


@pytest.fixture
def fresh(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Books]:
    """The one Property, its ledger not started, lent to the read inside a savepoint."""
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
        yield Books(connection, property_id, start=False)
        connection.rollback()


def test_the_month_to_close_shows_its_checks_and_closed_months_say_who(fresh: Books) -> None:
    year = fresh.today.year - 1
    begin(fresh, year, 50_000)
    flow = PostgresLedgerMonthEnd("postgresql://unused")
    answer = flow.month_end(fresh.property_id, None)
    january = answer["month"]
    assert january is not None and january["starts_on"] == f"{year}-01-01"
    checks = {check["code"]: check for check in answer["checks"]}
    assert set(checks) == {
        "BOOKS_CHECK",
        "NOTHING_WAITING",
        "NO_LATE_ADVANCE",
        "BANK_MATCHED",
        "CASH_COUNTED",
        "DEPRECIATION_DONE",
        "RIEL_VALUED",
        "PAYROLL_APPROVED",
    }
    assert checks["CASH_COUNTED"]["ok"] is False and checks["CASH_COUNTED"]["open_items"] >= 1
    assert answer["depreciation_entry"] is None
    assert all(month["starts_on"] <= fresh.today.isoformat() for month in answer["months"])
    last_year = next(item for item in answer["years"] if item["fiscal_year"] == year)
    assert last_year["status"] == "OPEN" and last_year["december_closed"] is False

    count_cash(fresh, month_end(year, 1), 50_000)
    assert fresh.call("gl_close_month", period(fresh, year, 1), fresh.owner)["closed"] is True
    again = flow.month_end(fresh.property_id, None)
    assert again["month"]["starts_on"] == f"{year}-02-01"
    closed = next(month for month in again["months"] if month["id"] == january["id"])
    assert closed["status"] == "CLOSED" and closed["closed_at"] is not None
    picked = flow.month_end(fresh.property_id, date(year, 1, 20))
    assert picked["month"]["id"] == january["id"]
    assert all(check["ok"] for check in picked["checks"] if check["code"] == "CASH_COUNTED")


def test_the_runtime_login_can_run_the_month_end_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    with pytest.raises(LedgerMoneyNotFound):
        PostgresLedgerMonthEnd(runtime_database_url()).month_end(uuid4(), None)
    with psycopg.connect(runtime_database_url()) as connection:
        for query in (MONTHS, YEARS):
            connection.execute(query, {"prop": uuid4(), "today": date(2027, 1, 31)})
        place = {"prop": uuid4(), "period": uuid4()}
        for query in (DEPRECIATION, RIEL):
            connection.execute(query, place)
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(CHECKS, place)
