"""General Ledger close (migration 20270417_267, phase 6 step 4 part 1).

Owner decisions: the round 22 screens of DESIGN.md (an adjusting entry has a reason and balanced
lines, never a control account, and nobody approves their own; the Owner's own entry goes in at
once with a note; Month-end close checks itself and works only when every line is green; months
close in order and only after their last day; the Owner closes the year after December), the
PRD v2 rules PR-GL-037, PR-GL-043, PR-GL-050 and PR-GL-051, the Books check of gap G2, and the
phase 6 plan L3 (the opening balances hold what came before the ledger's first day, and the app
works out each control account from its own lists).

Each test uses a new Property inside its transaction and rolls back.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.ledger_close_api import PostgresLedgerCloseFlow
from property_rental.ledger_money_api import (
    LedgerMoneyConflict,
    LedgerMoneyNotFound,
    LedgerMoneyRefused,
)
from test_customer_ledger_migration import canonical_invoice
from test_gl_money_records_migration import Books, Borrowed
from test_gl_money_records_migration import books as books
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property

ACCOUNTANT_RIGHTS = {"ledger.read", "ledger.adjustments.prepare"}


@pytest.fixture
def fresh(migrated_database_url: str) -> Iterator[Books]:
    """The one Property, its ledger not started (other tests may have left V1 records)."""
    with psycopg.connect(migrated_database_url) as connection:
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        if existing:
            property_id = UUID(str(existing[0]))
        else:
            property_id = insert_property(connection, insert_actor(connection))
        yield Books(connection, property_id, start=False)
        connection.rollback()


def lines(*pairs: tuple[str, int, int]) -> Jsonb:
    return Jsonb(
        [
            {"account": code, "debit_cents": debit or None, "credit_cents": credit or None}
            for code, debit, credit in pairs
        ]
    )


def adjustment(books: Books, adjustment_id: UUID) -> tuple[str, UUID | None, str | None]:
    row = books.connection.execute(
        "SELECT status, decided_by, own_entry_note FROM app.gl_adjusting_entries WHERE id = %s",
        (adjustment_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1], row[2]


def period(books: Books, year: int, month: int) -> UUID:
    return UUID(
        str(
            books.scalar(
                "SELECT period.id FROM app.gl_periods AS period "
                "JOIN app.gl_fiscal_years AS year ON year.id = period.fiscal_year_id "
                "WHERE period.property_id = %s AND year.fiscal_year = %s "
                "AND period.period_no = %s",
                (books.property_id, year, month),
            )
        )
    )


def keep_open(books: Books) -> None:
    books.scalar("SELECT app.gl_keep_years_open(%s, %s)", (books.property_id, books.owner))


def preview(books: Books) -> list[tuple[str, int, int, bool]]:
    return [
        (str(code), int(debit), int(credit), bool(worked_out))
        for code, debit, credit, worked_out in books.connection.execute(
            "SELECT code, debit_cents, credit_cents, worked_out FROM app.gl_opening_preview(%s)",
            (books.property_id,),
        ).fetchall()
    ]


def worked_out_net(books: Books) -> int:
    """Debits less credits of the control lines the app works out from its own lists."""
    return sum(debit - credit for _, debit, credit, worked in preview(books) if worked)


def capital(cents: int) -> list[tuple[str, int, int]]:
    """Equity lines that balance the rest (split, as other tests leave very large balances)."""
    most = 9 * 10**15
    parts, left = [], abs(cents)
    for code in ("3000", "3100"):
        part = min(left, most)
        if part:
            parts.append((code, 0, part) if cents > 0 else (code, part, 0))
        left -= part
    assert left == 0
    return parts


def settle(books: Books) -> None:
    """Give every method a ledger account and post the app's records, as the posting job does.

    Records that wait in Needs check by design (Refund corrections) cannot be settled here; a test
    that needs a green Books check then skips (the clean-database run covers it).
    """
    for column, table in (
        ("payment_method_id", "payment_methods"),
        ("refund_method_id", "refund_methods"),
    ):
        for (method,) in books.connection.execute(
            f"SELECT method.id FROM app.{table} AS method WHERE NOT EXISTS ("
            f"SELECT 1 FROM app.gl_method_accounts AS map WHERE map.{column} = method.id)"
        ).fetchall():
            books.connection.execute(
                "SELECT app.gl_set_method_account(%s, %s, %s, '1020', DATE '2000-01-01', %s, "
                "gen_random_uuid())",
                (
                    books.property_id,
                    method if column == "payment_method_id" else None,
                    method if column == "refund_method_id" else None,
                    books.owner,
                ),
            )
    while books.connection.execute(
        "SELECT posted FROM app.gl_post_app_records(%s, %s, %s, 5000)",
        (books.property_id, books.owner, books.today),
    ).fetchone() not in (None, (0,)):
        pass
    if books.scalar(
        "SELECT count(*) FROM app.gl_posting_problems WHERE property_id = %s",
        (books.property_id,),
    ):
        pytest.skip("Records left by other tests wait in Needs check")


def begin(books: Books, year: int, cash_cents: int) -> None:
    """Start the ledger on 1 January of a year with cash; the Owner's capital balances it."""
    books.call("gl_begin_ledger", books.property_id, books.owner, year)
    if date(year, 1, 1) <= books.today:
        keep_open(books)
        settle(books)
    books.call(
        "gl_set_opening_lines",
        books.property_id,
        books.owner,
        lines(("1010", cash_cents, 0), *capital(cash_cents + worked_out_net(books))),
    )
    books.call("gl_post_opening_balances", books.property_id, books.owner)


def count_cash(books: Books, on: date, cents: int) -> None:
    books.call("gl_count_cash", books.property_id, books.owner, "1010", on, cents, None, None, None)


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def test_an_adjusting_entry_needs_another_approver_and_never_a_control_account(
    books: Books,
) -> None:
    accountant = books._person("manager", ACCOUNTANT_RIGHTS)
    accrual = lines(("6050", 2_500, 0), ("2010", 0, 2_500))
    # Only a holder of the prepare right; a reason, 2 to 500 lines that balance.
    books.refused(
        "42501",
        "gl_prepare_adjusting_entry",
        books.property_id,
        books.manager,
        books.today,
        "Repair not billed yet",
        accrual,
        None,
    )
    books.refused(
        "22023",
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        " ",
        accrual,
        None,
        match="reason",
    )
    books.refused(
        "22023",
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        "One line",
        lines(("6050", 2_500, 0)),
        None,
        match="2 to 500",
    )
    books.refused(
        "22023",
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        "Off by a cent",
        lines(("6050", 2_500, 0), ("2010", 0, 2_499)),
        None,
        match="must equal",
    )
    # Customer debt and the other control accounts change only through app records.
    books.refused(
        "23514",
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        "Write it down",
        lines(("6050", 2_500, 0), ("1100", 0, 2_500)),
        None,
        match="1100",
    )

    waiting = UUID(
        str(
            books.call(
                "gl_prepare_adjusting_entry",
                books.property_id,
                accountant,
                books.today,
                "Repair not billed yet",
                accrual,
                None,
            )
        )
    )
    assert adjustment(books, waiting) == ("WAITING", None, None)
    assert books.lines(f"adjusting_entry:{waiting}") == []
    books.refused("42501", "gl_decide_adjusting_entry", waiting, accountant, True, None)
    books.refused(
        "22023", "gl_decide_adjusting_entry", waiting, books.owner, False, " ", match="why"
    )
    books.call("gl_decide_adjusting_entry", waiting, books.owner, True, None)
    assert adjustment(books, waiting) == ("POSTED", books.owner, None)
    assert books.lines(f"adjusting_entry:{waiting}") == [("6050", 2_500, 0), ("2010", 0, 2_500)]
    assert (
        books.scalar(
            "SELECT entry_kind || ' ' || approved_by FROM app.gl_journal_entries "
            "WHERE posting_key = %s",
            (f"adjusting_entry:{waiting}",),
        )
        == f"ADJUSTING {books.owner}"
    )
    books.refused("55000", "gl_decide_adjusting_entry", waiting, books.owner, True, None)
    books.refused(
        "55000", "gl_void_adjusting_entry", waiting, books.owner, "Wrong", match="reversed"
    )

    # Refused with a note, or voided by the one who prepared it, nothing posts.
    refused = books.call(
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        "Second try",
        accrual,
        None,
    )
    books.call("gl_decide_adjusting_entry", refused, books.owner, False, "Already billed")
    assert adjustment(books, refused)[0] == "REFUSED"
    voided = books.call(
        "gl_prepare_adjusting_entry",
        books.property_id,
        accountant,
        books.today,
        "Third try",
        accrual,
        None,
    )
    books.refused("22023", "gl_void_adjusting_entry", voided, accountant, None, match="reason")
    books.call("gl_void_adjusting_entry", voided, accountant, "Typed twice")
    assert adjustment(books, voided)[0] == "VOID"
    assert books.balance("6050") == 2_500

    # The Owner approves adjusting entries, so the Owner's own goes in at once with a note.
    books.refused(
        "22023",
        "gl_prepare_adjusting_entry",
        books.property_id,
        books.owner,
        books.today,
        "Owner's fix",
        accrual,
        None,
        match="note",
    )
    own = books.call(
        "gl_prepare_adjusting_entry",
        books.property_id,
        books.owner,
        books.today,
        "Owner's fix",
        accrual,
        "I checked the bill myself",
    )
    assert adjustment(books, own) == ("POSTED", books.owner, "I checked the bill myself")
    assert books.balance("6050") == 5_000
    numbers = [
        str(row[0])
        for row in books.connection.execute(
            "SELECT adjustment_number FROM app.gl_adjusting_entries WHERE property_id = %s "
            "ORDER BY adjustment_number",
            (books.property_id,),
        ).fetchall()
    ]
    assert len(numbers) == 4 and all(number.startswith("AJ") for number in numbers)


def test_opening_balances_balance_and_are_fixed_once_posted(fresh: Books) -> None:
    # The ledger starts next year here, so no record falls after its first day.
    year = fresh.today.year + 1
    fresh.refused("42501", "gl_begin_ledger", fresh.property_id, fresh.manager, year)
    fresh.refused("55000", "gl_set_opening_lines", fresh.property_id, fresh.owner, lines())
    fresh.call("gl_begin_ledger", fresh.property_id, fresh.owner, year)
    fresh.refused("55000", "gl_begin_ledger", fresh.property_id, fresh.owner, year - 1)
    assert (
        fresh.scalar(
            "SELECT status || ' ' || start_date FROM app.gl_opening_balances "
            "WHERE property_id = %s",
            (fresh.property_id,),
        )
        == f"DRAFT {year}-01-01"
    )
    # Control accounts are worked out by the app, never typed.
    fresh.refused(
        "23514",
        "gl_set_opening_lines",
        fresh.property_id,
        fresh.owner,
        lines(("1100", 1_000, 0), ("3000", 0, 1_000)),
        match="1100",
    )
    worked = worked_out_net(fresh)
    fresh.call(
        "gl_set_opening_lines",
        fresh.property_id,
        fresh.owner,
        lines(("1010", 50_000, 0), ("1520", 120_000, 0), *capital(160_000 + worked)),
    )
    fresh.refused(
        "22023",
        "gl_post_opening_balances",
        fresh.property_id,
        fresh.owner,
        match="off by 10000 cents",
    )
    # Typed again, the list is replaced whole.
    typed = [("1010", 50_000, 0), ("1520", 120_000, 0), *capital(170_000 + worked)]
    fresh.call("gl_set_opening_lines", fresh.property_id, fresh.owner, lines(*typed))
    assert [row[:3] for row in preview(fresh) if not row[3]] == typed
    fresh.refused("42501", "gl_post_opening_balances", fresh.property_id, fresh.manager)
    entry = fresh.call("gl_post_opening_balances", fresh.property_id, fresh.owner)
    opening = fresh.scalar(
        "SELECT id FROM app.gl_opening_balances WHERE property_id = %s", (fresh.property_id,)
    )
    posted = fresh.lines(f"opening_balance:{opening}")
    assert [line for line in posted if line[0] in ("1010", "1520", "3000", "3100")] == typed
    assert sum(debit - credit for _, debit, credit in posted) == 0
    assert (
        fresh.scalar(
            "SELECT entry_kind || ' ' || entry_date FROM app.gl_journal_entries WHERE id = %s",
            (entry,),
        )
        == f"OPENING {year}-01-01"
    )
    fresh.refused("55000", "gl_post_opening_balances", fresh.property_id, fresh.owner)
    fresh.refused(
        "55000",
        "gl_set_opening_lines",
        fresh.property_id,
        fresh.owner,
        lines(("1010", 1, 0), ("3000", 0, 1)),
        match="fixed once posted",
    )


def test_the_app_works_out_the_control_accounts_from_its_lists(
    migrated_database_url: str,
) -> None:
    """A Customer owes $510 from before the ledger's first day: the opening entry carries it."""
    _, prop, *_ = canonical_invoice(migrated_database_url)
    with psycopg.connect(migrated_database_url) as connection:
        books = Books(connection, prop, start=False)
        books.call("gl_begin_ledger", prop, books.owner, books.today.year + 1)
        listed = {
            str(code): int(cents)
            for code, cents in connection.execute(
                "SELECT code, cents FROM app.gl_control_lists(%s)", (prop,)
            ).fetchall()
        }
        assert listed["1100"] >= 51_000
        worked = {code: (debit, credit) for code, debit, credit, flag in preview(books) if flag}
        assert worked["1100"] == (listed["1100"], 0)
        assert set(worked) == {code for code, cents in listed.items() if cents}
        books.call(
            "gl_set_opening_lines", prop, books.owner, lines(*capital(worked_out_net(books)))
        )
        books.call("gl_post_opening_balances", prop, books.owner)
        checks = connection.execute(
            "SELECT check_code, in_books, in_list, ok FROM app.gl_books_check(%s)", (prop,)
        ).fetchall()
        assert all(row[3] for row in checks), checks
        assert (checks[0][1], checks[0][2]) == (
            listed["1100"] + listed["1110"],
            listed["1100"] + listed["1110"],
        )
        connection.rollback()


def test_the_books_check_has_eight_lines(fresh: Books) -> None:
    begin(fresh, fresh.today.year + 1, 10_000)
    rows = fresh.connection.execute(
        "SELECT check_code, in_books, in_list, ok FROM app.gl_books_check(%s)",
        (fresh.property_id,),
    ).fetchall()
    assert [row[0] for row in rows] == [
        "CUSTOMER_DEBT",
        "RENT_IN_ADVANCE",
        "SECURITY_DEPOSITS",
        "PET_DEPOSITS",
        "CUSTOMER_CREDIT",
        "MONEY_NOT_USED",
        "EVERY_RECORD_POSTED",
        "EVERY_ENTRY_BALANCED",
    ]
    assert all(row[3] for row in rows)


def test_a_month_closes_in_order_after_its_last_day_when_every_check_is_green(
    fresh: Books,
) -> None:
    year = fresh.today.year - 1
    begin(fresh, year, 50_000)
    january, february = period(fresh, year, 1), period(fresh, year, 2)
    fresh.refused("42501", "gl_close_month", january, fresh.manager)
    fresh.refused("55000", "gl_close_month", february, fresh.owner, match="in order")

    # Cash with lines in January is not counted yet: the close is kept as a run and answers no.
    answer = fresh.call("gl_close_month", january, fresh.owner)
    assert answer["closed"] is False and answer["checks"]["cash_counted"] is False
    assert {name for name, ok in answer["checks"].items() if not ok} == {"cash_counted"}
    assert set(answer["checks"]) == {
        "books_check",
        "nothing_waiting",
        "no_late_advance",
        "bank_matched",
        "cash_counted",
        "depreciation_done",
        "riel_valued",
        "payroll_approved",
    }
    assert (
        fresh.scalar(
            "SELECT count(*) FILTER (WHERE NOT all_green) FROM app.gl_close_runs "
            "WHERE period_id = %s",
            (january,),
        )
        == 1
    )

    # A waiting adjusting entry dated in the month also holds it open.
    accountant = fresh._person("manager", ACCOUNTANT_RIGHTS)
    waiting = fresh.call(
        "gl_prepare_adjusting_entry",
        fresh.property_id,
        accountant,
        date(year, 1, 20),
        "Interest earned",
        lines(("1010", 1_000, 0), ("4080", 0, 1_000)),
        None,
    )
    count_cash(fresh, date(year, 1, 31), 50_000)
    checks = fresh.connection.execute(
        "SELECT check_code, ok, open_items FROM app.gl_month_close_checks(%s)", (january,)
    ).fetchall()
    assert ("NOTHING_WAITING", False, 1) in [tuple(row) for row in checks]
    assert fresh.call("gl_close_month", january, fresh.owner)["closed"] is False
    fresh.call("gl_decide_adjusting_entry", waiting, fresh.owner, True, None)

    assert fresh.call("gl_close_month", january, fresh.owner)["closed"] is True
    assert fresh.scalar("SELECT status FROM app.gl_periods WHERE id = %s", (january,)) == "CLOSED"
    fresh.refused("55000", "gl_close_month", january, fresh.owner, match="already closed")
    fresh.refused(
        "55000",
        "gl_prepare_adjusting_entry",
        fresh.property_id,
        fresh.owner,
        date(year, 1, 31),
        "Too late",
        lines(("1010", 1, 0), ("4080", 0, 1)),
        "Owner",
        match="closed",
    )
    keep_open(fresh)
    this_month = period(fresh, fresh.today.year, fresh.today.month)
    fresh.refused("55000", "gl_close_month", this_month, fresh.owner, match="after its last day")

    # The rest of the year, then the year: profit moves to 3900 and the next year opens.
    for month in range(2, 13):
        count_cash(fresh, month_end(year, month), 51_000)
        assert fresh.call("gl_close_month", period(fresh, year, month), fresh.owner)["closed"]
    year_id = fresh.scalar(
        "SELECT id FROM app.gl_fiscal_years WHERE property_id = %s AND fiscal_year = %s",
        (fresh.property_id, year),
    )
    fresh.refused("42501", "gl_close_fiscal_year", year_id, fresh.manager)
    entry = fresh.call("gl_close_fiscal_year", year_id, fresh.owner)
    assert fresh.lines(f"fiscal_year:{year_id}:close") == [("4080", 1_000, 0), ("3900", 0, 1_000)]
    assert entry is not None
    assert (
        fresh.scalar("SELECT status FROM app.gl_fiscal_years WHERE id = %s", (year_id,)) == "CLOSED"
    )
    fresh.refused("22023", "gl_close_fiscal_year", year_id, fresh.owner, match="No open year")


def test_the_year_of_today_is_kept_open(fresh: Books) -> None:
    # No ledger yet: nothing to keep open.
    keep_open(fresh)
    assert (
        fresh.scalar(
            "SELECT count(*) FROM app.gl_fiscal_years WHERE property_id = %s", (fresh.property_id,)
        )
        == 0
    )
    fresh.call("gl_begin_ledger", fresh.property_id, fresh.owner, fresh.today.year - 1)
    keep_open(fresh)
    keep_open(fresh)
    assert [
        int(row[0])
        for row in fresh.connection.execute(
            "SELECT fiscal_year FROM app.gl_fiscal_years WHERE property_id = %s "
            "ORDER BY fiscal_year",
            (fresh.property_id,),
        ).fetchall()
    ] == [fresh.today.year - 1, fresh.today.year]


def test_asset_life_rules_are_seeded_for_the_owner_to_change(fresh: Books) -> None:
    rows = fresh.connection.execute(
        "SELECT name.code, name.value_unit, name.area, rule.value "
        "FROM app.business_rule_names AS name "
        "JOIN app.business_rules AS rule ON rule.rule_name_id = name.id "
        "WHERE name.code LIKE 'ASSET_LIFE_%%' ORDER BY name.code"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("ASSET_LIFE_1510", "COUNT", "LEDGER", 20),
        ("ASSET_LIFE_1520", "COUNT", "LEDGER", 5),
        ("ASSET_LIFE_1530", "COUNT", "LEDGER", 3),
    ]


def test_the_runtime_login_closes_only_through_the_checked_functions(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        for query, state in (
            (
                "SELECT app.gl_close_month(gen_random_uuid(), gen_random_uuid(), "
                "gen_random_uuid())",
                "22023",
            ),
            (
                "SELECT app.gl_begin_ledger(gen_random_uuid(), gen_random_uuid(), "
                "2026::smallint, gen_random_uuid())",
                "42501",
            ),
        ):
            with pytest.raises(psycopg.Error) as caught:
                with runtime.transaction():
                    runtime.execute(query)
            assert caught.value.sqlstate == state, caught.value
        for query in (
            "SELECT app.gl_keep_years_open(gen_random_uuid(), gen_random_uuid())",
            "SELECT app.gl_post_adjusting(gen_random_uuid(), gen_random_uuid(), gen_random_uuid())",
            "UPDATE app.gl_periods SET status = 'CLOSED'",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with runtime.transaction():
                    runtime.execute(query)
        runtime.rollback()


def test_the_migration_follows_money_records() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    found = script.get_revision("20270417_267")
    assert found is not None and found.down_revision == "20270416_266"


def test_the_close_api_flow_calls_each_function_and_reads_the_records(
    books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(books.connection))
    flow = PostgresLedgerCloseFlow("postgresql://unused")
    prop = books.property_id
    accountant = books._person("manager", ACCOUNTANT_RIGHTS)
    entry_lines = [
        {"account": "6050", "debit_cents": 2_500, "memo": None},
        {"account": "2010", "credit_cents": 2_500, "memo": "Dara Plumbing"},
    ]
    made = flow.write(
        "prepare_adjustment",
        prop,
        str(accountant),
        {"entry_date": books.today, "reason": "Not billed yet", "lines": entry_lines},
    )
    with pytest.raises(LedgerMoneyRefused, match=r"adjustments\.approve"):
        flow.write("decide_adjustment", prop, str(accountant), {"approve": True}, made)
    flow.write("decide_adjustment", prop, str(books.owner), {"approve": True}, made)
    [listed] = flow.rows("adjusting-entries", prop)
    assert (listed["id"], listed["status"]) == (str(made), "POSTED")
    assert [line["account_code"] for line in listed["lines"]] == ["6050", "2010"]
    with pytest.raises(LedgerMoneyNotFound):
        flow.write("decide_adjustment", prop, str(books.owner), {"approve": True}, uuid4())
    # The ledger here started without opening balances, this year; an earlier start is refused.
    with pytest.raises(LedgerMoneyConflict, match="earlier year"):
        flow.write("begin_ledger", prop, str(books.owner), {"first_year": books.today.year + 1})
    assert len(flow.rows("books-check", prop)) == 8
    months = flow.rows("periods", prop)
    assert [month["period_no"] for month in months][:12] == list(range(1, 13))
    january = UUID(months[0]["id"])
    checks = flow.rows("close-checks", prop, january)
    assert {row["check_code"] for row in checks} >= {"BOOKS_CHECK", "CASH_COUNTED"}
    if books.today.month > 1:
        answer = flow.write("close_month", prop, str(books.owner), {}, january)
        assert set(answer) == {"closed", "checks"}
    assert flow.rows("close-checks", prop, uuid4()) == ()
