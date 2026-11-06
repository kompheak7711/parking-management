"""The riel bank account and the riel account of a Payment Method (migration 20270609_320).

Owner 04/11/2026: NBC requires a riel account in every bank; one ABA QR code takes both riel and
dollars. Card 12:05 "Riel bank account per method": 1021 "ABA Bank · KHR account", and a riel
payment goes to its method's riel account. Card 17:52 "Same as riel cash": at month end the riel
in the bank is valued at the app's system rate and the difference goes to 4100.

Each test works inside its transaction on the one Property and rolls back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from property_rental.ledger_cash_api import PostgresLedgerCash
from property_rental.ledger_month_end_api import PostgresLedgerMonthEnd
from property_rental.ledger_posting_api import PostgresLedgerPostingFlow
from property_rental.ledger_reports import PostgresLedgerReports, ReportParams
from test_gl_assets_migration import check, money_in, rate, zone
from test_gl_auto_posting_migration import SET_ACCOUNT, invoice_paid, method_of, post
from test_gl_close_migration import keep_open, lines, period
from test_gl_money_records_migration import Books, Borrowed
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_unit_migration import insert_actor, insert_property

Connection = psycopg.Connection[Any]
SET_RIEL = (
    "SELECT app.gl_set_method_account(%s, %s, %s, %s, DATE '2026-01-01', %s, gen_random_uuid(), %s)"
)

__all__ = ["invoice_paid"]


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


def riel_payment(
    connection: Connection, prop: UUID, human: UUID, like: UUID, riel: int, cents: int
) -> UUID:
    """A riel Payment by the same customer and method as ``like``, at 4,100 riel."""
    rate_id = uuid4()
    connection.execute(
        "INSERT INTO app.exchange_rate_records (id, reference_rate_khr_per_usd, "
        "markup_basis_points, system_rate_khr_per_usd, rate_source, source_reference, "
        "applicable_at, entered_by, calculation_trace) VALUES (%s, 4079.601990, 50, 4100, "
        "'ABA_EQUIVALENT_MANUAL', 'Riel bank test', statement_timestamp(), %s, %s)",
        (
            rate_id,
            human,
            Jsonb(
                {
                    "system_rate_khr_per_usd": 4100,
                    "automatic_source_unavailable": True,
                    "fallback_reason": "Riel bank test",
                }
            ),
        ),
    )
    payment = uuid4()
    connection.execute(
        """
        INSERT INTO app.payments(id, payment_number, property_id, payer_customer_id,
            payment_scope_kind, payment_date, payment_method_id, received_currency,
            received_amount_minor, usd_accounting_value_cents, exchange_rate_record_id,
            confirmed_at, confirmed_by, authorization_reference)
        SELECT %s, %s, property_id, payer_customer_id, 'NORMAL_CUSTOMER', payment_date,
            payment_method_id, 'KHR', %s, %s, %s, clock_timestamp(), %s, 'payments.record'
        FROM app.payments WHERE id = %s AND property_id = %s
        """,
        (payment, f"TEST-{payment}", riel, cents, rate_id, human, like, prop),
    )
    return payment


def riel_lines(connection: Connection, key: str) -> list[tuple[str, int, int, str, int | None]]:
    return [
        (str(code), int(debit), int(credit), str(currency), amount)
        for code, debit, credit, currency, amount in connection.execute(
            "SELECT account.code, line.debit_cents, line.credit_cents, line.original_currency, "
            "line.original_amount_minor FROM app.gl_journal_entries AS entry "
            "JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id "
            "JOIN app.gl_accounts AS account ON account.id = line.account_id "
            "WHERE entry.posting_key = %s ORDER BY line.line_no",
            (key,),
        ).fetchall()
    ]


def test_the_chart_has_the_riel_bank_account(ledger: Books) -> None:
    template = ledger.connection.execute(
        "SELECT name_en, account_type, cash_kind FROM app.gl_chart_template WHERE code = '1021'"
    ).fetchone()
    assert template == ("ABA Bank · KHR account", "ASSET", "BANK_KHR")
    account = ledger.connection.execute(
        "SELECT name_en, cash_kind, bs_section, is_active FROM app.gl_accounts "
        "WHERE property_id = %s AND code = '1021'",
        (ledger.property_id,),
    ).fetchone()
    assert account == ("ABA Bank · KHR account", "BANK_KHR", "CURRENT", True)


def test_a_riel_payment_goes_to_the_methods_riel_account(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, prop, human, _, payment, _ = invoice_paid
    method = method_of(connection, payment)
    riel = riel_payment(connection, prop, human, payment, 410_000, 10_000)
    connection.execute(SET_RIEL, (prop, method, None, "1020", human, "1021"))
    post(connection, prop, human)
    # Dollars go to the dollar bank; riel to the riel bank, with its riel.
    assert riel_lines(connection, f"payment:{payment}")[0][:3] == ("1020", 30_000, 0)
    assert riel_lines(connection, f"payment:{riel}") == [
        ("1021", 10_000, 0, "KHR", 410_000),
        ("2210", 0, 10_000, "USD", None),
    ]
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(connection))
    flow = PostgresLedgerPostingFlow("postgresql://unused")
    [row] = [m for m in flow.method_accounts(prop) if m.kind == "PAYMENT" and m.method_id == method]
    assert (row.account_code, row.riel_account_code) == ("1020", "1021")
    assert row.riel_account_name == "ABA Bank · KHR account"


def test_without_a_riel_account_riel_goes_where_it_went_before(
    invoice_paid: tuple[Connection, UUID, UUID, UUID, UUID, UUID],
) -> None:
    connection, prop, human, _, payment, _ = invoice_paid
    riel = riel_payment(connection, prop, human, payment, 410_000, 10_000)
    # A dollar cash method sends riel to riel cash (1011), as before migration 320.
    connection.execute(SET_ACCOUNT, (prop, method_of(connection, payment), None, "1010", human))
    post(connection, prop, human)
    assert riel_lines(connection, f"payment:{riel}")[0] == ("1011", 10_000, 0, "KHR", 410_000)


def test_a_method_account_save_checks_the_riel_account(ledger: Books) -> None:
    method = ledger.scalar("SELECT id FROM app.payment_methods ORDER BY code LIMIT 1")
    refund = ledger.scalar("SELECT id FROM app.refund_methods ORDER BY code LIMIT 1")
    owner, prop = ledger.owner, ledger.property_id

    def refused(match: str, payment: Any, refund_method: Any, code: str, riel: Any) -> None:
        with pytest.raises(psycopg.Error, match=match) as caught:
            with ledger.connection.transaction():
                ledger.connection.execute(
                    SET_RIEL, (prop, payment, refund_method, code, owner, riel)
                )
        assert caught.value.sqlstate == "22023"

    refused("keeps riel", method, None, "1021", None)
    refused("riel cash or riel bank", method, None, "1020", "1020")
    refused("riel cash or riel bank", method, None, "1020", "1030")
    refused("no riel account", None, refund, "1020", "1021")
    ledger.connection.execute(SET_RIEL, (prop, method, None, "1020", owner, "1021"))
    ledger.connection.execute(SET_RIEL, (prop, method, None, "1010", owner, "1011"))
    ledger.connection.execute(SET_RIEL, (prop, None, refund, "1020", owner, None))
    # Even written straight in, the rows follow the same rules.
    for bad in ("1020", "1010"):
        with pytest.raises(psycopg.errors.CheckViolation):
            with ledger.connection.transaction():
                ledger.connection.execute(
                    "INSERT INTO app.gl_method_accounts (id, property_id, payment_method_id, "
                    "account_id, riel_account_id, effective_from, created_by) "
                    "SELECT gen_random_uuid(), %s, %s, main.id, riel.id, DATE '2026-01-01', %s "
                    "FROM app.gl_accounts AS main JOIN app.gl_accounts AS riel "
                    "ON riel.property_id = main.property_id "
                    "WHERE main.property_id = %s AND main.code = '1020' AND riel.code = %s",
                    (prop, method, owner, prop, bad),
                )
    with pytest.raises(psycopg.errors.CheckViolation):
        with ledger.connection.transaction():
            ledger.connection.execute(
                "INSERT INTO app.gl_method_accounts (id, property_id, refund_method_id, "
                "account_id, riel_account_id, effective_from, created_by) "
                "SELECT gen_random_uuid(), %s, %s, main.id, riel.id, DATE '2026-01-01', %s "
                "FROM app.gl_accounts AS main JOIN app.gl_accounts AS riel "
                "ON riel.property_id = main.property_id "
                "WHERE main.property_id = %s AND main.code = '1020' AND riel.code = '1021'",
                (prop, refund, owner, prop),
            )


def test_money_in_the_riel_bank_keeps_its_riel_and_is_valued_at_month_end(
    ledger: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    year = ledger.today.year - 1
    local = zone(ledger)
    money_in(ledger, "1020", date(year, 10, 2), 100_000)
    first = rate(ledger, 4_083, datetime(year, 10, 1, 9, tzinfo=local))

    def move(on: date, frm: str, to: str, cents: int, riel: int | None) -> Any:
        return ledger.call(
            "gl_move_money",
            ledger.property_id,
            ledger.owner,
            on,
            frm,
            to,
            cents,
            cents,
            riel,
            None if riel is None else first,
            "Dollars to riel",
        )

    ledger.refused(
        "22023",
        "gl_move_money",
        ledger.property_id,
        ledger.owner,
        date(year, 10, 10),
        "1020",
        "1021",
        10_000,
        10_000,
        None,
        None,
        "No riel typed",
        match="typed in riel",
    )
    move(date(year, 10, 10), "1020", "1021", 10_000, 408_300)
    # Money in or out of the riel bank without its riel is refused, whatever the record.
    ledger.refused(
        "23514",
        "gl_record_owner_money",
        ledger.property_id,
        ledger.owner,
        "IN",
        date(year, 10, 11),
        "1021",
        5_000,
        "Dollars",
        match="keeps riel",
    )
    expense = (
        ledger.property_id,
        ledger.owner,
        date(year, 10, 25),
        "6050",
        "Tap washer",
        1_000,
    )
    ledger.refused(
        "23514",
        "gl_record_expense",
        *expense,
        "USD",
        None,
        None,
        "1021",
        None,
        None,
        None,
        None,
        match="keeps riel",
    )
    ledger.call("gl_record_expense", *expense, "KHR", 40_830, first, "1021", None, None, None, None)
    # A typed line carries no riel, so adjusting entries cannot use the riel bank.
    ledger.refused(
        "23514",
        "gl_prepare_adjusting_entry",
        ledger.property_id,
        ledger.owner,
        date(year, 10, 26),
        "Bank fee",
        lines(("6050", 100, 0), ("1021", 0, 100)),
        "My own fix",
        match="cannot take a typed line",
    )
    october = period(ledger, year, 10)
    month_end_rate = rate(ledger, 4_100, datetime(year, 10, 31, 23, tzinfo=local))
    assert check(ledger, october, "RIEL_VALUED") is False
    # No count: the riel bank holds the riel on its lines, 408,300 - 40,830 = 367,470.
    assert ledger.call("gl_run_month_end", october, ledger.owner)["riel_valued"] == 1
    row = ledger.connection.execute(
        "SELECT valued.riel_held_minor, valued.exchange_rate_record_id, valued.book_usd_cents, "
        "valued.new_usd_cents, entry.description, entry.posting_key "
        "FROM app.gl_fx_revaluations AS valued "
        "JOIN app.gl_journal_entries AS entry ON entry.id = valued.entry_id "
        "WHERE valued.period_id = %s",
        (october,),
    ).fetchone()
    assert row is not None
    assert row[:4] == (367_470, month_end_rate, 9_000, 8_963)
    assert str(row[4]).startswith("Riel bank valued at the month-end rate")
    assert ledger.lines(str(row[5])) == [("4100", 37, 0), ("1021", 0, 37)]
    assert check(ledger, october, "RIEL_VALUED") is True
    assert check(ledger, october, "BANK_MATCHED") is False
    # Month end and the Balance sheet show the riel (owner 05/11/2026).
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(ledger.connection))
    end = PostgresLedgerMonthEnd("postgresql://unused").month_end(
        ledger.property_id, date(year, 10, 15)
    )
    valued = {item["code"]: item for item in end["riel_accounts"]}
    assert valued["1021"] | {"entry_number": None} == {
        "code": "1021",
        "name_en": "ABA Bank · KHR account",
        "name_km": "ធនាគារ ABA · រៀល",
        "cash_kind": "BANK_KHR",
        "riel_held": 367_470,
        "khr_per_usd": 4_100,
        "before_cents": 9_000,
        "after_cents": 8_963,
        "gain_cents": -37,
        "entry_number": None,
    }
    assert valued["1021"]["entry_number"] is not None
    sheet = PostgresLedgerReports("postgresql://unused").report(
        "balance-sheet",
        ledger.property_id,
        str(ledger.owner),
        ReportParams(as_of=date(year, 10, 31)),
    )
    names = {row["code"]: row["name"] for row in sheet.rows if row["line"] == "account"}
    assert names["1021"] == "ABA Bank · KHR account (367,470 riel)"
    assert "riel" not in names["1020"]


def test_the_riel_bank_is_matched_in_riel(ledger: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    year = ledger.today.year - 1
    local = zone(ledger)
    money_in(ledger, "1020", date(year, 1, 2), 100_000)
    first = rate(ledger, 4_000, datetime(year, 1, 1, 9, tzinfo=local))
    ledger.call(
        "gl_move_money",
        ledger.property_id,
        ledger.owner,
        date(year, 1, 10),
        "1020",
        "1021",
        10_000,
        10_000,
        400_000,
        first,
        "Riel for the bank",
    )
    rate(ledger, 4_100, datetime(year, 1, 31, 23, tzinfo=local))
    january = period(ledger, year, 1)
    ledger.call("gl_run_month_end", january, ledger.owner)
    # The month-end valuation is not on the statement, so it is not a line to mark.
    bank_lines = ledger.connection.execute(
        "SELECT line_id, debit_cents, riel_minor FROM app.gl_bank_lines(%s, '1021', %s)",
        (ledger.property_id, january),
    ).fetchall()
    assert [(row[1], row[2]) for row in bank_lines] == [(10_000, 400_000)]
    items = Jsonb([{"line_id": str(bank_lines[0][0])}])
    valuation = ledger.scalar(
        "SELECT line.id FROM app.gl_journal_lines AS line "
        "JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id "
        "JOIN app.gl_accounts AS account ON account.id = line.account_id "
        "WHERE entry.entry_kind = 'FX_REVALUATION' AND account.code = '1021' "
        "AND account.property_id = %s",
        (ledger.property_id,),
    )

    def refused(state: str, cents: Any, riel: Any, marked: Jsonb, text: str) -> None:
        ledger.refused(
            state,
            "gl_match_bank",
            ledger.property_id,
            ledger.owner,
            "1021",
            january,
            cents,
            riel,
            marked,
            match=text,
        )

    refused("22023", 10_000, None, items, "in riel")
    refused("22023", 10_000, 400_000, items, "in riel")
    refused("22023", None, 399_000, items, "off by -1000 riel")
    refused("23514", None, 400_000, Jsonb([{"line_id": str(valuation)}]), "cannot be matched")
    ledger.refused(
        "22023",
        "gl_match_bank",
        ledger.property_id,
        ledger.owner,
        "1020",
        january,
        None,
        90_000,
        Jsonb([]),
        match="Type the statement balance",
    )
    assert check(ledger, january, "BANK_MATCHED") is False
    ledger.call(
        "gl_match_bank", ledger.property_id, ledger.owner, "1021", january, None, 400_000, items
    )
    saved = ledger.connection.execute(
        "SELECT match.statement_balance_cents, match.statement_riel, match.status "
        "FROM app.gl_bank_reconciliations AS match JOIN app.gl_accounts AS account "
        "ON account.id = match.account_id WHERE account.code = '1021' AND match.period_id = %s",
        (january,),
    ).fetchone()
    assert saved == (10_000, 400_000, "MATCHED")

    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: Borrowed(ledger.connection))
    answer = PostgresLedgerCash("postgresql://unused").bank_cash(
        ledger.property_id, date(year, 1, 15)
    )
    [bank] = [row for row in answer["banks"] if row["code"] == "1021"]
    assert bank["cash_kind"] == "BANK_KHR" and bank["riel_held"] == 400_000
    assert bank["match"]["statement_riel"] == 400_000 and bank["lines"] == []
    # 400,000 riel at the January month-end rate of 4,100.
    assert bank["book_cents"] == round(400_000 * 100 / 4_100)
