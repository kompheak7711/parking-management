"""General Ledger fixed assets, riel at month end, bank matching and budgets.

Migration 20270418_268, phase 6 step 4 part 2. Owner decisions: PRD v2 PR-GL-036 (a purchase
from the Asset limit is equipment, depreciated straight-line from the month after it is bought),
PR-GL-048, PR-GL-054 (a budget is prepared and the Owner approves it) and PR-GL-055 (the bank is
matched line by line before the month closes), gap G7 (riel cash is valued at month end, the
difference to 4100), and the owner's answers of 03/11/2026 10:26: Building 20 years, Furniture
and appliances 5 years, Office equipment 3 years as Business rules; Land is never depreciated;
the value ends at $0 with the last month taking the cents left; riel at the app's system rate;
the Owner or an allowed user may change one item's years, the value left spread over the
months left.

Each test starts the ledger last year on the one Property inside its transaction and rolls back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.ledger_close_api import PostgresLedgerCloseFlow
from property_rental.ledger_money_api import LedgerMoneyConflict, LedgerMoneyRefused
from test_gl_close_migration import keep_open, month_end, period
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property


@pytest.fixture
def ledger(migrated_database_url: str) -> Iterator[Books]:
    """The ledger started on 1 January last year, with this year open too."""
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        books = Books(connection, property_id, start=False)
        books.call("gl_begin_ledger", property_id, books.owner, books.today.year - 1)
        keep_open(books)
        yield books
        connection.rollback()


def last_year(books: Books, month: int, day: int) -> date:
    return date(books.today.year - 1, month, day)


def money_in(books: Books, code: str, on: date, cents: int) -> None:
    books.call(
        "gl_record_owner_money", books.property_id, books.owner, "IN", on, code, cents, "Start"
    )


def buy(books: Books, code: str, on: date, cents: int, item: str = "Sofa, Unit 2") -> UUID:
    return UUID(
        str(
            books.call(
                "gl_record_expense",
                books.property_id,
                books.owner,
                on,
                code,
                item,
                cents,
                "USD",
                None,
                None,
                "1010",
                None,
                None,
                None,
                None,
            )
        )
    )


def asset_of(books: Books, expense: UUID) -> dict[str, Any]:
    cursor = books.connection.execute(
        "SELECT asset.id, asset.asset_number, asset.useful_life_years, asset.status, "
        "asset.depreciation_starts_on, asset.cost_cents, asset.purchase_entry_id, "
        "expense.entry_id AS expense_entry_id "
        "FROM app.gl_fixed_assets AS asset JOIN app.gl_expenses AS expense "
        "ON expense.id = asset.expense_id WHERE asset.expense_id = %s",
        (expense,),
    )
    row = cursor.fetchone()
    assert row is not None and cursor.description is not None
    return dict(zip([column.name for column in cursor.description], row, strict=True))


def due(books: Books, asset: UUID, through: date) -> int:
    return int(books.scalar("SELECT app.gl_depreciation_due(%s, %s)", (asset, through)))


def posted(books: Books, asset: UUID) -> int:
    return int(books.scalar("SELECT app.gl_asset_accumulated(%s, 'infinity')", (asset,)))


def months_from(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def check(books: Books, period_id: UUID, code: str) -> bool:
    return bool(
        books.scalar(
            "SELECT ok FROM app.gl_month_close_checks(%s) WHERE check_code = %s",
            (period_id, code),
        )
    )


def rate(books: Books, khr: int, at: datetime) -> UUID:
    rate_id = uuid4()
    reference = Decimal(khr) / Decimal("1.005")
    books.connection.execute(
        "INSERT INTO app.exchange_rate_records (id, reference_rate_khr_per_usd, "
        "markup_basis_points, system_rate_khr_per_usd, rate_source, source_reference, "
        "applicable_at, entered_by, calculation_trace) VALUES (%s, %s, 50, %s, "
        "'ABA_EQUIVALENT_MANUAL', 'Ledger test', %s, %s, %s)",
        (
            rate_id,
            reference.quantize(Decimal("0.000001"), ROUND_FLOOR),
            khr,
            at,
            books.owner,
            Jsonb({"system_rate_khr_per_usd": khr}),
        ),
    )
    return rate_id


def zone(books: Books) -> ZoneInfo:
    return ZoneInfo(
        str(
            books.scalar(
                "SELECT timezone_name FROM app.properties WHERE id = %s", (books.property_id,)
            )
        )
    )


def test_a_purchase_from_the_asset_limit_is_equipment_and_below_it_an_expense(
    ledger: Books,
) -> None:
    money_in(ledger, "1010", last_year(ledger, 1, 2), 1_000_000)
    # $499.99 of furniture is refused as equipment, for a recorded expense and for a request.
    ledger.refused(
        "22023",
        "gl_record_expense",
        ledger.property_id,
        ledger.owner,
        last_year(ledger, 1, 15),
        "1520",
        "Chair",
        49_999,
        "USD",
        None,
        None,
        "1010",
        None,
        None,
        None,
        None,
        match="Asset limit",
    )
    ledger.refused(
        "22023",
        "gl_submit_expense_request",
        ledger.property_id,
        ledger.staff,
        "REQUEST",
        "1520",
        "Chair",
        "Broken",
        49_999,
        "USD",
        None,
        None,
        None,
        None,
        None,
        "ADVANCE",
        None,
        match="Asset limit",
    )
    # Cash and money owed accounts are never spending accounts; Paid in advance is.
    for code in ("1010", "1100", "1590"):
        ledger.refused(
            "22023",
            "gl_record_expense",
            ledger.property_id,
            ledger.owner,
            last_year(ledger, 1, 15),
            code,
            "Wrong",
            60_000,
            "USD",
            None,
            None,
            "1010",
            None,
            None,
            None,
            None,
        )
    ledger.call(
        "gl_record_expense",
        ledger.property_id,
        ledger.owner,
        last_year(ledger, 1, 15),
        "1200",
        "Insurance for the year",
        12_000,
        "USD",
        None,
        None,
        "1010",
        None,
        None,
        None,
        None,
    )

    sofa = asset_of(ledger, buy(ledger, "1520", last_year(ledger, 1, 15), 100_000))
    land = asset_of(ledger, buy(ledger, "1500", last_year(ledger, 1, 20), 5_000_000, "Plot B"))
    server = asset_of(ledger, buy(ledger, "1530", last_year(ledger, 1, 31), 50_000, "Laptop"))
    # Life from the Business rules, Land never; depreciation starts the month after.
    assert (sofa["useful_life_years"], sofa["depreciation_starts_on"]) == (
        5,
        last_year(ledger, 2, 1),
    )
    assert land["useful_life_years"] is None and server["useful_life_years"] == 3
    assert sofa["purchase_entry_id"] == sofa["expense_entry_id"] and sofa["status"] == "IN_USE"
    assert str(sofa["asset_number"]).startswith("FA")
    assert ledger.balance("1520") == 100_000 and ledger.balance("1500") == 5_000_000
    values = {
        str(row[0]): row[1:]
        for row in ledger.connection.execute(
            "SELECT asset_number, monthly_cents, value_cents, useful_life_years "
            "FROM app.gl_asset_values(%s)",
            (ledger.property_id,),
        ).fetchall()
    }
    assert values[str(sofa["asset_number"])] == (1_666, 100_000, 5)
    assert values[str(land["asset_number"])] == (0, 5_000_000, None)


def test_depreciation_is_the_same_each_month_and_the_last_month_takes_the_cents_left(
    ledger: Books,
) -> None:
    money_in(ledger, "1010", last_year(ledger, 1, 2), 1_000_000)
    laptop = asset_of(ledger, buy(ledger, "1530", last_year(ledger, 1, 31), 50_000, "Laptop"))
    land = asset_of(ledger, buy(ledger, "1500", last_year(ledger, 1, 20), 5_000_000, "Plot B"))
    start = last_year(ledger, 2, 1)
    # 3 years = 36 months of $13.88; the 36th month takes $14.20, and the value ends at $0.
    assert due(ledger, laptop["id"], last_year(ledger, 1, 31)) == 0
    assert due(ledger, laptop["id"], month_end(start.year, 2)) == 1_388
    month_35 = add_months(start, 34)
    month_36 = add_months(start, 35)
    assert due(ledger, laptop["id"], month_end(month_35.year, month_35.month)) == 35 * 1_388
    assert due(ledger, laptop["id"], month_end(month_36.year, month_36.month)) == 50_000
    assert due(ledger, laptop["id"], month_end(month_36.year + 5, 1)) == 50_000
    assert 50_000 - 35 * 1_388 == 1_420
    assert due(ledger, land["id"], month_end(month_36.year, 12)) == 0

    # February: one entry, DR 6140 and CR 1590 for each item, and the close check turns green.
    february = period(ledger, start.year, 2)
    assert check(ledger, february, "DEPRECIATION_DONE") is False
    entry = ledger.call("gl_run_month_end", february, ledger.owner)
    assert entry["depreciation_entry_id"] is not None
    assert ledger.lines(f"depreciation:{february}") == [("6140", 1_388, 0), ("1590", 0, 1_388)]
    assert check(ledger, february, "DEPRECIATION_DONE") is True
    assert (
        ledger.call("gl_run_month_end", february, ledger.owner)["depreciation_entry_id"]
        == (entry["depreciation_entry_id"])
    )
    ledger.refused("42501", "gl_run_month_end", february, ledger.manager)
    this_month = period(ledger, ledger.today.year, ledger.today.month)
    ledger.refused("55000", "gl_run_month_end", this_month, ledger.owner, match="last day")

    # The posting job does every month that has ended, once.
    work = int(
        ledger.scalar("SELECT app.gl_month_end_work(%s, %s)", (ledger.property_id, ledger.owner))
    )
    ended = months_from(start, date(ledger.today.year, ledger.today.month, 1))
    assert work == ended - 1
    assert posted(ledger, laptop["id"]) == min(ended, 35) * 1_388 + (1_420 if ended >= 36 else 0)
    assert posted(ledger, land["id"]) == 0
    assert (
        int(
            ledger.scalar(
                "SELECT app.gl_month_end_work(%s, %s)", (ledger.property_id, ledger.owner)
            )
        )
        == 0
    )


def test_an_item_years_change_spreads_the_value_left_over_the_months_left(
    ledger: Books,
) -> None:
    money_in(ledger, "1010", last_year(ledger, 1, 2), 1_000_000)
    expense = buy(ledger, "1520", last_year(ledger, 1, 15), 100_000)
    sofa = asset_of(ledger, expense)
    ledger.scalar("SELECT app.gl_month_end_work(%s, %s)", (ledger.property_id, ledger.owner))
    start = last_year(ledger, 2, 1)
    this_month = date(ledger.today.year, ledger.today.month, 1)
    used = months_from(start, this_month)
    assert posted(ledger, sofa["id"]) == used * 1_666

    # Only the fixed assets right, a reason, and 1 to 100 years.
    for actor, years, reason, state in (
        (ledger.manager, 2, "Wears out fast", "42501"),
        (ledger.owner, 0, "Wears out fast", "22023"),
        (ledger.owner, 2, " ", "22023"),
    ):
        ledger.refused(state, "gl_change_asset_life", sofa["id"], actor, years, reason, match=None)
    if used >= 12:
        ledger.refused(
            "22023", "gl_change_asset_life", sofa["id"], ledger.owner, 1, "x", match="already"
        )
    ledger.call("gl_change_asset_life", sofa["id"], ledger.owner, 2, "Wears out fast")
    left = 100_000 - used * 1_666
    change = ledger.connection.execute(
        "SELECT starts_on, value_cents, months_left, useful_life_years "
        "FROM app.gl_fixed_asset_life_changes WHERE fixed_asset_id = %s",
        (sofa["id"],),
    ).fetchone()
    assert change == (this_month, left, 24 - used, 2)
    monthly = left // (24 - used)
    assert due(ledger, sofa["id"], month_end(this_month.year, this_month.month)) == monthly
    last = add_months(this_month, 24 - used - 1)
    assert due(ledger, sofa["id"], month_end(last.year, last.month)) == left
    assert (
        ledger.scalar(
            "SELECT monthly_cents FROM app.gl_asset_values(%s) WHERE id = %s",
            (ledger.property_id, sofa["id"]),
        )
        == monthly
    )
    # The change is kept; an item with depreciation posted stays in the register.
    with pytest.raises(psycopg.Error) as caught:
        with ledger.connection.transaction():
            ledger.connection.execute("DELETE FROM app.gl_fixed_asset_life_changes")
    assert caught.value.sqlstate in ("55000", "42501")
    ledger.refused("55000", "gl_void_expense", expense, ledger.owner, "Typed twice", match="stays")


def test_voiding_an_equipment_expense_before_depreciation_voids_the_item(ledger: Books) -> None:
    money_in(ledger, "1010", ledger.today, 100_000)
    expense = buy(ledger, "1530", ledger.today, 60_000, "Printer")
    ledger.call("gl_void_expense", expense, ledger.owner, "Typed twice")
    assert asset_of(ledger, expense)["status"] == "VOID"
    assert ledger.balance("1530") == 0
    land = asset_of(ledger, buy(ledger, "1500", ledger.today, 50_000, "Plot C"))
    ledger.refused(
        "55000", "gl_change_asset_life", land["id"], ledger.owner, 20, "No", match="in use"
    )


def test_riel_cash_is_valued_at_the_month_end_rate(ledger: Books) -> None:
    year = ledger.today.year - 1
    local = zone(ledger)
    money_in(ledger, "1010", date(year, 10, 2), 100_000)
    first = rate(ledger, 4_083, datetime(year, 10, 1, 9, tzinfo=local))
    ledger.call(
        "gl_move_money",
        ledger.property_id,
        ledger.owner,
        date(year, 10, 10),
        "1010",
        "1011",
        10_000,
        10_000,
        408_300,
        first,
        "Dollars to riel",
    )
    october, november = period(ledger, year, 10), period(ledger, year, 11)
    ledger.refused("55000", "gl_run_month_end", october, ledger.owner, match="Count the riel")
    ledger.call(
        "gl_count_cash",
        ledger.property_id,
        ledger.owner,
        "1011",
        date(year, 10, 20),
        None,
        408_300,
        first,
        None,
    )
    ledger.call(
        "gl_record_expense",
        ledger.property_id,
        ledger.owner,
        date(year, 10, 25),
        "6050",
        "Tap washer",
        1_000,
        "KHR",
        40_830,
        first,
        "1011",
        None,
        None,
        None,
        None,
    )
    # The rate in force when October ends: 4,100 riel to the dollar.
    month_end_rate = rate(ledger, 4_100, datetime(year, 10, 31, 23, tzinfo=local))
    rate(ledger, 3_000, datetime(year, 11, 1, 0, 30, tzinfo=local))
    assert check(ledger, october, "RIEL_VALUED") is False
    assert ledger.call("gl_run_month_end", october, ledger.owner)["riel_valued"] == 1
    # 367,470 riel at 4,100 is $89.63; the books held $90.00, so 37 cents go to 4100.
    row = ledger.connection.execute(
        "SELECT riel_held_minor, exchange_rate_record_id, book_usd_cents, new_usd_cents, "
        "entry_id IS NOT NULL FROM app.gl_fx_revaluations WHERE period_id = %s",
        (october,),
    ).fetchone()
    assert row == (367_470, month_end_rate, 9_000, 8_963, True)
    revaluation = ledger.scalar(
        "SELECT posting_key FROM app.gl_journal_entries WHERE entry_kind = 'FX_REVALUATION' "
        "AND property_id = %s",
        (ledger.property_id,),
    )
    assert ledger.lines(str(revaluation)) == [("4100", 37, 0), ("1011", 0, 37)]
    assert check(ledger, october, "RIEL_VALUED") is True
    assert ledger.call("gl_run_month_end", october, ledger.owner)["riel_valued"] == 0
    # November is not counted: the posting job leaves it; Month-end close says what is missing.
    assert check(ledger, november, "RIEL_VALUED") is False
    ledger.scalar("SELECT app.gl_month_end_work(%s, %s)", (ledger.property_id, ledger.owner))
    assert check(ledger, november, "RIEL_VALUED") is False
    ledger.refused("55000", "gl_run_month_end", november, ledger.owner, match="Count the riel")
    # Counted at November's end with no change: valued again at that month's rate.
    count_rate = rate(ledger, 4_000, datetime(year, 11, 30, 9, tzinfo=local))
    ledger.call(
        "gl_count_cash",
        ledger.property_id,
        ledger.owner,
        "1011",
        date(year, 11, 30),
        None,
        367_470,
        count_rate,
        "Rate moved",
    )
    assert ledger.call("gl_run_month_end", november, ledger.owner)["riel_valued"] == 1
    assert ledger.balance("1011") == round(367_470 * 100 / 4_000)


def test_the_bank_is_matched_month_by_month_to_the_statement(ledger: Books) -> None:
    year = ledger.today.year - 1
    money_in(ledger, "1020", date(year, 1, 5), 500_000)
    ledger.call(
        "gl_record_expense",
        ledger.property_id,
        ledger.owner,
        date(year, 1, 20),
        "6050",
        "Bank fee",
        1_000,
        "USD",
        None,
        None,
        "1020",
        None,
        None,
        None,
        None,
    )
    money_in(ledger, "1010", date(year, 1, 6), 3_000)
    january, february = period(ledger, year, 1), period(ledger, year, 2)
    bank_lines = ledger.connection.execute(
        "SELECT line_id, debit_cents, credit_cents FROM app.gl_bank_lines(%s, '1020', %s)",
        (ledger.property_id, january),
    ).fetchall()
    assert [(row[1], row[2]) for row in bank_lines] == [(500_000, 0), (0, 1_000)]
    money_in_line, fee_line = (UUID(str(row[0])) for row in bank_lines)
    cash_line = ledger.scalar(
        "SELECT line.id FROM app.gl_journal_lines AS line JOIN app.gl_accounts AS account "
        "ON account.id = line.account_id WHERE account.property_id = %s AND account.code = '1010'",
        (ledger.property_id,),
    )

    def match(month: UUID, statement: int, *lines: UUID, actor: UUID | None = None) -> Any:
        return ledger.call(
            "gl_match_bank",
            ledger.property_id,
            actor or ledger.owner,
            "1020",
            month,
            statement,
            Jsonb([{"line_id": str(line), "reference": "ABA"} for line in lines]),
        )

    def refused(state: str, *arguments: Any, text: str | None = None) -> None:
        ledger.refused(state, "gl_match_bank", ledger.property_id, *arguments, match=text)

    items = Jsonb([{"line_id": str(money_in_line)}])
    refused("42501", ledger.manager, "1020", january, 500_000, items)
    refused("22023", ledger.owner, "1010", january, 500_000, items, text="not a bank")
    refused("55000", ledger.owner, "1020", february, 499_000, Jsonb([]), text="earlier month")
    refused("22023", ledger.owner, "1020", january, 499_000, items, text="off by -1000")
    refused("23514", ledger.owner, "1020", january, 3_000, Jsonb([{"line_id": str(cash_line)}]))
    assert check(ledger, january, "BANK_MATCHED") is False
    match(january, 499_000, money_in_line, fee_line)
    assert check(ledger, january, "BANK_MATCHED") is True
    assert (
        ledger.connection.execute(
            "SELECT * FROM app.gl_bank_lines(%s, '1020', %s)", (ledger.property_id, january)
        ).fetchall()
        == []
    )
    refused("55000", ledger.owner, "1020", january, 499_000, Jsonb([]), text="already matched")
    # February has no new lines: the statement still shows what was cleared before.
    refused("55000", ledger.owner, "1020", february, 499_000, Jsonb([{"line_id": str(fee_line)}]))
    match(february, 499_000)
    assert (
        ledger.scalar(
            "SELECT status FROM app.gl_bank_reconciliations WHERE period_id = %s", (february,)
        )
        == "MATCHED"
    )


def test_a_budget_is_prepared_and_the_owner_approves_it(ledger: Books) -> None:
    year = ledger.today.year
    accountant = ledger._person("manager", {"ledger.read", "ledger.budgets.prepare"})
    rent = [{"account": "4010", "month_no": month, "amount_cents": 300_000} for month in (1, 2)]

    def prepare(actor: UUID, lines: list[dict[str, Any]], note: str | None = None) -> UUID:
        return UUID(
            str(
                ledger.call(
                    "gl_prepare_budget", ledger.property_id, actor, year, Jsonb(lines), note
                )
            )
        )

    def state(budget: UUID) -> tuple[Any, ...]:
        row = ledger.connection.execute(
            "SELECT status, version, approved_by, decision_note, own_budget_note "
            "FROM app.gl_budgets WHERE id = %s",
            (budget,),
        ).fetchone()
        assert row is not None
        return tuple(row)

    def refused(state_code: str, actor: UUID, lines: Any, note: str | None = None) -> None:
        ledger.refused(
            state_code,
            "gl_prepare_budget",
            ledger.property_id,
            actor,
            year,
            Jsonb(lines),
            note,
        )

    refused("42501", ledger.manager, rent)
    refused("22023", accountant, [])
    refused("22023", accountant, [{"account": "1010", "month_no": 1, "amount_cents": 1}])
    refused("22023", accountant, [{"account": "4010", "month_no": 13, "amount_cents": 1}])
    refused("22023", accountant, [{"account": "4010", "month_no": 1, "amount_cents": -1}])
    ledger.refused(
        "22023",
        "gl_prepare_budget",
        ledger.property_id,
        accountant,
        year + 5,
        Jsonb(rent),
        None,
        match="no year",
    )
    # The Owner's own budget is approved at once, with a note.
    refused("22023", ledger.owner, rent, " ")
    own = prepare(ledger.owner, rent, "My plan for the year")
    assert state(own) == ("APPROVED", 1, ledger.owner, None, "My plan for the year")

    # The accountant's is sent; one waits at a time; the Owner sends it back with a reason.
    sent = prepare(accountant, [*rent, {"account": "6050", "month_no": 1, "amount_cents": 20_000}])
    assert state(sent) == ("DRAFT", 2, None, None, None)
    refused("55000", accountant, rent)
    ledger.refused("42501", "gl_decide_budget", sent, accountant, True, None)
    ledger.refused("22023", "gl_decide_budget", sent, ledger.owner, False, " ")
    ledger.call("gl_decide_budget", sent, ledger.owner, False, "Repairs look low")
    assert state(sent) == ("REPLACED", 2, ledger.owner, "Repairs look low", None)
    ledger.refused("55000", "gl_decide_budget", sent, ledger.owner, True, None)

    # The next one is approved; the Owner's earlier budget is replaced and keeps its approver.
    better = prepare(accountant, rent)
    ledger.call("gl_decide_budget", better, ledger.owner, True, None)
    assert state(better) == ("APPROVED", 3, ledger.owner, None, None)
    assert state(own)[:3] == ("REPLACED", 1, ledger.owner)
    assert (
        ledger.scalar(
            "SELECT sum(amount_cents) FROM app.gl_budget_lines WHERE budget_id = %s", (better,)
        )
        == 600_000
    )
    ledger.refused("22023", "gl_decide_budget", uuid4(), ledger.owner, True, None)


def test_the_runtime_login_runs_month_end_only_through_the_checked_functions(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        for query, state in (
            ("SELECT app.gl_run_month_end(gen_random_uuid(), gen_random_uuid(), NULL)", "22023"),
            (
                "SELECT app.gl_change_asset_life(gen_random_uuid(), gen_random_uuid(), "
                "2::smallint, 'x', NULL)",
                "22023",
            ),
            (
                "SELECT app.gl_prepare_budget(gen_random_uuid(), gen_random_uuid(), "
                "2027::smallint, '[]', NULL, NULL)",
                "42501",
            ),
            (
                "SELECT app.gl_match_bank(gen_random_uuid(), gen_random_uuid(), '1020', "
                "gen_random_uuid(), 0, '[]', NULL)",
                "42501",
            ),
        ):
            with pytest.raises(psycopg.Error) as caught:
                with runtime.transaction():
                    runtime.execute(query)
            assert caught.value.sqlstate == state, caught.value
        for query in (
            "SELECT app.gl_month_end_work(gen_random_uuid(), NULL)",
            "SELECT app.gl_post_depreciation(gen_random_uuid(), NULL)",
            "SELECT app.gl_value_riel(gen_random_uuid(), NULL, true)",
            "INSERT INTO app.gl_fixed_asset_life_changes (id) VALUES (gen_random_uuid())",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with runtime.transaction():
                    runtime.execute(query)
        runtime.rollback()


def test_the_migration_follows_the_close() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    found = script.get_revision("20270418_268")
    assert found is not None and found.down_revision == "20270417_267"


def test_the_api_flow_runs_month_end_matches_the_bank_and_sends_budgets(
    ledger: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(ledger.connection))
    flow = PostgresLedgerCloseFlow("postgresql://unused")
    prop, owner = ledger.property_id, str(ledger.owner)
    year = ledger.today.year - 1
    money_in(ledger, "1020", date(year, 1, 5), 500_000)
    money_in(ledger, "1010", date(year, 1, 6), 200_000)
    sofa = asset_of(ledger, buy(ledger, "1520", date(year, 1, 15), 100_000))
    february = period(ledger, year, 2)
    answer = flow.write("run_month_end", prop, owner, {}, february)
    assert answer["depreciation_entry_id"] is not None and answer["riel_valued"] == 0
    [item] = flow.rows("fixed-assets", prop)
    assert (item["id"], item["depreciation_cents"], item["value_cents"]) == (
        str(sofa["id"]),
        1_666,
        98_334,
    )
    assert item["life_changes"] is None
    flow.write("change_asset_life", prop, owner, {"years": 3, "reason": "Heavy use"}, sofa["id"])
    [item] = flow.rows("fixed-assets", prop)
    assert item["useful_life_years"] == 3 and item["life_changes"][0]["months_left"] == 35
    with pytest.raises(LedgerMoneyRefused, match=r"ledger\.fixed_assets"):
        flow.write(
            "change_asset_life",
            prop,
            str(ledger.manager),
            {"years": 4, "reason": "x"},
            sofa["id"],
        )

    january = period(ledger, year, 1)
    [bank_line] = flow.rows("bank-lines", prop, january, {"account": "1020"})
    assert bank_line["debit_cents"] == 500_000
    values = {
        "account_code": "1020",
        "period_id": january,
        "statement_cents": 500_000,
        "items": [{"line_id": bank_line["line_id"], "statement_date": None, "reference": None}],
    }
    flow.write("match_bank", prop, owner, values)
    with pytest.raises(LedgerMoneyConflict, match="already matched"):
        flow.write("match_bank", prop, owner, values)
    [matched] = flow.rows("bank-matches", prop)
    assert (matched["account_code"], matched["status"], matched["lines"]) == ("1020", "MATCHED", 1)
    assert flow.rows("bank-lines", prop, january, {"account": "1020"}) == ()

    accountant = ledger._person("manager", {"ledger.read", "ledger.budgets.prepare"})
    budget = {
        "fiscal_year": ledger.today.year,
        "lines": [{"account": "4010", "month_no": 1, "amount_cents": 300_000}],
        "own_note": None,
    }
    made = flow.write("prepare_budget", prop, str(accountant), budget)
    flow.write("decide_budget", prop, owner, {"approve": True, "note": None}, made)
    [listed] = flow.rows("budgets", prop)
    assert (listed["id"], listed["status"], listed["version"]) == (str(made), "APPROVED", 1)
    assert listed["lines"] == [
        {
            "account_code": "4010",
            "account_name": listed["lines"][0]["account_name"],
            "month_no": 1,
            "amount_cents": 300_000,
        }
    ]
