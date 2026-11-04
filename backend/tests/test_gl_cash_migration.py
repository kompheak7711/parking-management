"""Bank and cash read for the ledger screen on the real database (phase 6 step 6 part 3).

The months that have ended, each bank account's lines not yet matched and its match, each cash
account's count, the petty cash float and the riel held are read with the runtime login's rights.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.ledger_cash_api import (
    BANK_LINES,
    BANK_MATCH,
    CASH_COUNT,
    LAST_VALUATION,
    MONEY,
    MONTHS,
    PETTY_WAITING,
    RIEL_HELD,
    SOURCE_ENTRY,
    PostgresLedgerCash,
)
from property_rental.ledger_money_api import LedgerMoneyNotFound
from test_gl_assets_migration import rate as rate_at
from test_gl_close_migration import keep_open, period
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


def money_in(books: Books, code: str, on: date, cents: int) -> None:
    books.call(
        "gl_record_owner_money", books.property_id, books.owner, "IN", on, code, cents, "Start"
    )


def by_code(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["code"]: row for row in rows}


def test_a_month_shows_the_bank_lines_to_match_and_the_cash_to_count(ledger: Books) -> None:
    year = ledger.today.year - 1
    money_in(ledger, "1020", date(year, 1, 5), 500_000)
    money_in(ledger, "1010", date(year, 1, 6), 3_000)
    flow = PostgresLedgerCash("postgresql://unused")

    answer = flow.bank_cash(ledger.property_id, None)
    assert answer["today"] == ledger.today.isoformat()
    january = answer["month"]
    assert january is not None and january["starts_on"] == f"{year}-01-01"
    assert january["matched"] is False and january["counted"] is False
    assert all(month["ends_on"] < ledger.today.isoformat() for month in answer["months"])
    banks = by_code(answer["banks"])
    assert set(banks) == {"1020"}
    bank = banks["1020"]
    assert bank["book_cents"] == 500_000 and bank["match"] is None
    lines = bank["lines"]
    assert isinstance(lines, list)
    assert [(line["debit_cents"], line["credit_cents"]) for line in lines] == [(500_000, 0)]
    cash = by_code(answer["cash"])
    assert set(cash) == {"1010", "1011", "1030"}
    assert cash["1010"]["book_cents"] == 3_000 and cash["1010"]["count"] is None
    assert {row["code"] for row in answer["money_accounts"]} == {"1010", "1011", "1020", "1030"}

    ledger.call(
        "gl_match_bank",
        ledger.property_id,
        ledger.owner,
        "1020",
        period(ledger, year, 1),
        500_000,
        Jsonb([{"line_id": lines[0]["line_id"]}]),
    )
    ledger.call(
        "gl_count_cash",
        ledger.property_id,
        ledger.owner,
        "1010",
        date(year, 1, 31),
        2_900,
        None,
        None,
        "Short by one dollar",
    )
    again = flow.bank_cash(ledger.property_id, date(year, 1, 15))
    assert again["month"]["id"] == january["id"]
    assert again["month"]["matched"] is True and again["month"]["counted"] is True
    bank = by_code(again["banks"])["1020"]
    assert bank["lines"] == []
    assert bank["match"]["status"] == "MATCHED" and bank["match"]["lines"] == 1
    assert bank["match"]["statement_balance_cents"] == 500_000
    count = by_code(again["cash"])["1010"]["count"]
    assert count["counted_cents"] == 2_900 and count["book_cents"] == 3_000
    assert count["note"] == "Short by one dollar" and count["entry_number"]
    assert by_code(again["cash"])["1010"]["book_cents"] == 2_900
    # With January done, the next month to look at is February.
    assert flow.bank_cash(ledger.property_id, None)["month"]["starts_on"] == f"{year}-02-01"


def test_petty_cash_and_riel_cash_show_what_they_hold(ledger: Books) -> None:
    money_in(ledger, "1010", ledger.today, 100_000)
    top_up = ledger.call(
        "gl_top_up_petty_cash", ledger.property_id, ledger.manager, ledger.today, "1010", 10_000
    )
    reader = PostgresLedgerCash("postgresql://unused")
    number = reader.entry_of(ledger.property_id, "petty-cash-top-up", top_up)
    assert ledger.scalar(
        "SELECT source_id FROM app.gl_journal_entries WHERE entry_number = %s", (number,)
    ) == UUID(str(top_up))
    with pytest.raises(LedgerMoneyNotFound):
        reader.entry_of(ledger.property_id, "money-move", top_up)
    request = ledger.submit(ledger.staff, 1_500, "CASH", paid_from="1030")
    ledger.call("gl_decide_expense_request", request, ledger.manager, True, None)
    rate = rate_at(ledger, 4_083, datetime.now(UTC) - timedelta(days=1))
    ledger.call(
        "gl_count_cash",
        ledger.property_id,
        ledger.owner,
        "1011",
        ledger.today,
        None,
        40_830,
        rate,
        "Riel found in the drawer",
    )
    answer = PostgresLedgerCash("postgresql://unused").bank_cash(ledger.property_id, None)
    petty = answer["petty"]
    assert petty["code"] == "1030" and petty["balance_cents"] == 10_000
    assert isinstance(petty["float_cents"], int) and petty["float_cents"] > 0
    assert [row["amount_cents"] for row in petty["waiting"]] == [1_500]
    assert answer["rate"]["id"] == str(rate) and answer["rate"]["khr_per_usd"] == 4_083
    riel = answer["riel"]
    assert riel["code"] == "1011" and riel["held_riel"] == 40_830
    assert riel["book_cents"] == 1_000
    assert riel["last_month_end"] is None and riel["last_entry_number"] is None


def test_the_runtime_login_can_run_the_bank_and_cash_read(migrated_database_url: str) -> None:
    assert migrated_database_url
    with pytest.raises(LedgerMoneyNotFound):
        PostgresLedgerCash(runtime_database_url()).bank_cash(uuid4(), None)
    with psycopg.connect(runtime_database_url()) as connection:
        place = {"prop": uuid4(), "today": date(2027, 1, 31), "on": date(2027, 1, 31)}
        for query in (MONTHS, MONEY, PETTY_WAITING):
            connection.execute(query, place)
        connection.execute(RIEL_HELD, {**place, "account": uuid4()})
        connection.execute(LAST_VALUATION, {"account": uuid4()})
        connection.execute(SOURCE_ENTRY, {"prop": uuid4(), "kind": "MONEY_MOVE", "id": uuid4()})
        for query in (BANK_MATCH, CASH_COUNT):
            connection.execute(query, {"account": uuid4(), "period": uuid4()})
        connection.execute(BANK_LINES, {"prop": uuid4(), "code": "1020", "period": uuid4()})
