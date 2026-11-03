"""General Ledger database (migrations 20270409_259 to 20270412_262; V1.1 part 8, PR-GL).

Owner approved the ledger database plan on 2026-11-02 21:08 (bigint cents, rollback only while
the ledger is empty, month close in order and never reopened, start on 1 January 2027, write-off
through the V1 charge reduction). Each test starts the ledger for a test Property and rolls back.
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

from test_migrations import _run_alembic, _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_unit_migration import insert_actor, insert_property, insert_unit

Connection = psycopg.Connection[Any]
REVISIONS = ("20270409_259", "20270410_260", "20270411_261", "20270412_262")
BEFORE_LEDGER = "20270408_258"
POST = (
    "SELECT app.gl_post_entry(%s, %s::date, %s, %s, 'TEST', NULL::uuid, %s, %s, %s, %s::uuid, "
    "gen_random_uuid(), %s)"
)


class Ledger:
    def __init__(self, connection: Connection, property_id: UUID, actor_id: UUID) -> None:
        self.connection = connection
        self.property_id = property_id
        self.actor_id = actor_id

    def post(
        self,
        on: str,
        lines: list[dict[str, Any]],
        kind: str = "AUTO",
        key: str | None = None,
        reason: str | None = None,
        approved_by: UUID | None = None,
    ) -> UUID:
        row = self.connection.execute(
            POST,
            (
                self.property_id,
                on,
                kind,
                f"Test {kind}",
                key or f"test:{uuid4()}",
                reason,
                self.actor_id,
                approved_by,
                Jsonb(lines),
            ),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def account(self, code: str) -> UUID:
        row = self.connection.execute(
            "SELECT id FROM app.gl_accounts WHERE property_id=%s AND code=%s",
            (self.property_id, code),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def period(self, number: int, year: int = 2027) -> UUID:
        row = self.connection.execute(
            "SELECT period.id FROM app.gl_periods AS period JOIN app.gl_fiscal_years AS year "
            "ON year.id=period.fiscal_year_id WHERE year.property_id=%s AND year.fiscal_year=%s "
            "AND period.period_no=%s",
            (self.property_id, year, number),
        ).fetchone()
        assert row is not None
        return UUID(str(row[0]))

    def close_month(self, number: int) -> None:
        self.connection.execute(
            "SELECT app.gl_close_period(%s, %s, %s)",
            (self.period(number), self.actor_id, Jsonb({"books_check": True})),
        )

    def check_balanced(self) -> None:
        """Run the commit-time balance check now (it is DEFERRABLE INITIALLY DEFERRED)."""
        self.connection.execute("SET CONSTRAINTS app.gl_journal_entries_balanced IMMEDIATE")
        self.connection.execute("SET CONSTRAINTS app.gl_journal_entries_balanced DEFERRED")


def pair(debit: str, credit: str, cents: int) -> list[dict[str, Any]]:
    return [{"account": debit, "debit_cents": cents}, {"account": credit, "credit_cents": cents}]


def refused(
    connection: Connection,
    error: type[Exception],
    query: str,
    parameters: Any = (),
    match: str | None = None,
) -> None:
    with pytest.raises(error, match=match):
        with connection.transaction():
            connection.execute(query, parameters)


@pytest.fixture
def ledger(migrated_database_url: str) -> Iterator[Ledger]:
    with psycopg.connect(migrated_database_url) as connection:
        actor_id = insert_actor(connection)
        # One Property only: use the one an earlier suite left, if any.
        existing = connection.execute("SELECT id FROM app.properties").fetchone()
        property_id = UUID(str(existing[0])) if existing else insert_property(connection, actor_id)
        connection.execute(
            "SELECT app.gl_start_ledger(%s, 2027::smallint, %s)", (property_id, actor_id)
        )
        yield Ledger(connection, property_id, actor_id)
        connection.rollback()


def test_the_starter_chart_and_fiscal_year_2027_are_seeded_once(ledger: Ledger) -> None:
    connection = ledger.connection
    accounts = connection.execute(
        "SELECT code, name_en, account_type, control_source, is_tax_locked, cash_kind, "
        "bs_section, is_retained_earnings FROM app.gl_accounts WHERE property_id=%s ORDER BY code",
        (ledger.property_id,),
    ).fetchall()
    assert len(accounts) == 59
    by_code = {row[0]: row for row in accounts}
    assert by_code["1010"][1:] == (
        "Cash on hand (USD)",
        "ASSET",
        None,
        False,
        "CASH_USD",
        "CURRENT",
        False,
    )
    assert by_code["4100"][1] == "Exchange gain or loss"
    assert by_code["6160"][1] == "Customer debt written off"
    assert {code for code, *_ in accounts if by_code[code][4]} == {"2400", "6040"}
    assert {row[0]: row[3] for row in accounts if row[3]} == {
        "1100": "INVOICES",
        "1110": "LATE_CHARGES",
        "1300": "STOCK",
        "2050": "RENT_IN_ADVANCE",
        "2100": "SECURITY_DEPOSITS",
        "2110": "PET_DEPOSITS",
        "2200": "CUSTOMER_CREDIT",
        "2210": "MONEY_NOT_USED",
    }
    assert [row[0] for row in accounts if row[7]] == ["3900"]
    assert by_code["1510"][6] == "NON_CURRENT" and by_code["2600"][6] == "NON_CURRENT"
    periods = connection.execute(
        "SELECT period.period_no, period.starts_on, period.ends_on, period.status "
        "FROM app.gl_periods AS period WHERE period.property_id=%s ORDER BY period.period_no",
        (ledger.property_id,),
    ).fetchall()
    assert len(periods) == 13
    assert periods[1][:3] == (2, date(2027, 2, 1), date(2027, 2, 28))
    assert periods[12][:3] == (13, date(2027, 12, 31), date(2027, 12, 31))
    assert {row[3] for row in periods} == {"OPEN"}
    first = connection.execute(
        "SELECT id FROM app.gl_fiscal_years WHERE property_id=%s", (ledger.property_id,)
    ).fetchone()
    again = connection.execute(
        "SELECT app.gl_start_ledger(%s, 2027::smallint, %s)",
        (ledger.property_id, ledger.actor_id),
    ).fetchone()
    assert first == again
    assert connection.execute(
        "SELECT count(*) FROM app.gl_accounts WHERE property_id=%s", (ledger.property_id,)
    ).fetchone() == (59,)
    started = connection.execute(
        "SELECT count(*) FROM app.audit_events WHERE property_id=%s AND action='ledger.started'",
        (ledger.property_id,),
    ).fetchone()
    assert started is not None and started[0] >= 1


def test_every_entry_balances_with_two_or_more_one_sided_lines(ledger: Ledger) -> None:
    connection = ledger.connection
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="must equal"):
        with connection.transaction():
            ledger.post(
                "2027-01-10",
                [{"account": "1010", "debit_cents": 100}, {"account": "4010", "credit_cents": 90}],
            )
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="two or more"):
        with connection.transaction():
            ledger.post("2027-01-10", [{"account": "1010", "debit_cents": 100}])
    with pytest.raises(psycopg.errors.CheckViolation, match="gl_jl_one_side"):
        with connection.transaction():
            ledger.post(
                "2027-01-10",
                [
                    {"account": "1010", "debit_cents": 100, "credit_cents": 100},
                    {"account": "4010", "credit_cents": 0, "debit_cents": 0},
                ],
            )
    # A direct insert that skips the function is still stopped by the commit-time check.
    entry_id = uuid4()
    with pytest.raises(psycopg.errors.CheckViolation, match="does not balance"):
        with connection.transaction():
            connection.execute(
                "INSERT INTO app.gl_journal_entries(id, property_id, entry_number, entry_date, "
                "period_id, entry_kind, description, source_type, posting_key, posted_by, "
                "correlation_id) VALUES (%s,%s,'JE279999','2027-01-10',%s,'AUTO','x','TEST',"
                "'test:raw',%s,gen_random_uuid())",
                (entry_id, ledger.property_id, ledger.period(1), ledger.actor_id),
            )
            connection.execute(
                "INSERT INTO app.gl_journal_lines(id, entry_id, property_id, line_no, account_id, "
                "debit_cents) VALUES (gen_random_uuid(), %s, %s, 1, %s, 100)",
                (entry_id, ledger.property_id, ledger.account("1010")),
            )
            ledger.check_balanced()
    good = ledger.post("2027-01-10", pair("1010", "4010", 100))
    ledger.check_balanced()
    assert connection.execute(
        "SELECT entry_number FROM app.gl_journal_entries WHERE id=%s", (good,)
    ).fetchone() == ("JE270001",)


def test_posted_entries_never_change_and_a_key_posts_once(ledger: Ledger) -> None:
    connection = ledger.connection
    first = ledger.post("2027-01-10", pair("1010", "4010", 500), key="invoice:1:issued")
    again = ledger.post("2027-01-11", pair("1010", "4010", 999), key="invoice:1:issued")
    assert first == again
    assert connection.execute(
        "SELECT count(*) FROM app.gl_journal_entries WHERE property_id=%s", (ledger.property_id,)
    ).fetchone() == (1,)
    for query in (
        "UPDATE app.gl_journal_entries SET description='changed' WHERE id=%s",
        "DELETE FROM app.gl_journal_entries WHERE id=%s",
        "UPDATE app.gl_journal_lines SET debit_cents=debit_cents WHERE entry_id=%s",
        "DELETE FROM app.gl_journal_lines WHERE entry_id=%s",
    ):
        refused(
            connection,
            psycopg.errors.ObjectNotInPrerequisiteState,
            query,
            (first,),
            match="append-only",
        )
    ledger.check_balanced()
    for table in ("gl_journal_entries", "gl_journal_lines", "gl_accounts", "gl_periods"):
        refused(
            connection, psycopg.errors.ObjectNotInPrerequisiteState, f"TRUNCATE app.{table} CASCADE"
        )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "DELETE FROM app.gl_accounts WHERE id=%s",
        (ledger.account("6190"),),
        match="never deleted",
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.gl_accounts SET code='1019' WHERE id=%s",
        (ledger.account("1010"),),
        match="has entries",
    )
    connection.execute(
        "UPDATE app.gl_accounts SET name_en='Cash in the office (USD)' WHERE id=%s",
        (ledger.account("1010"),),
    )


def test_a_reversal_mirrors_its_entry_once(ledger: Ledger) -> None:
    connection = ledger.connection
    entry = ledger.post("2027-01-10", pair("6010", "1020", 1200))
    reversal = connection.execute(
        "SELECT app.gl_reverse_entry(%s, '2027-01-12', 'Wrong bill', %s, 'test:rev', "
        "gen_random_uuid())",
        (entry, ledger.actor_id),
    ).fetchone()
    assert reversal is not None
    ledger.check_balanced()
    lines = connection.execute(
        "SELECT account_code, debit_cents, credit_cents, is_reversed FROM app.gl_entry_lines_v "
        "WHERE entry_id IN (%s, %s) ORDER BY entry_number, line_no",
        (entry, reversal[0]),
    ).fetchall()
    assert lines == [
        ("6010", 1200, 0, True),
        ("1020", 0, 1200, True),
        ("6010", 0, 1200, False),
        ("1020", 1200, 0, False),
    ]
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_reverse_entry(%s, '2027-01-12', 'Again', %s, 'test:rev2', "
                "gen_random_uuid())",
                (entry, ledger.actor_id),
            )
    with pytest.raises(psycopg.errors.CheckViolation, match="cannot be reversed"):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_reverse_entry(%s, '2027-01-12', 'Back', %s, 'test:rev3', "
                "gen_random_uuid())",
                (reversal[0], ledger.actor_id),
            )
    other = ledger.post("2027-01-10", pair("6020", "1020", 300))
    with pytest.raises(psycopg.errors.CheckViolation, match="must mirror"):
        with connection.transaction():
            connection.execute(
                POST.replace("gen_random_uuid(), %s)", "gen_random_uuid(), %s, %s)"),
                (
                    ledger.property_id,
                    "2027-01-12",
                    "REVERSAL",
                    "Bad reversal",
                    "test:bad",
                    "Bad",
                    ledger.actor_id,
                    None,
                    Jsonb(pair("1020", "6020", 200)),
                    other,
                ),
            )
            ledger.check_balanced()


def test_control_tax_and_turned_off_accounts_are_guarded(ledger: Ledger) -> None:
    connection = ledger.connection
    ledger.post("2027-01-05", pair("1100", "2050", 50000))
    ledger.post("2027-02-01", pair("2050", "4010", 50000), kind="RENT_TO_INCOME")
    with pytest.raises(psycopg.errors.CheckViolation, match="only through app records"):
        with connection.transaction():
            ledger.post(
                "2027-01-31",
                pair("1100", "4010", 100),
                kind="ADJUSTING",
                reason="Fix",
                approved_by=ledger.actor_id,
            )
    ledger.post(
        "2027-01-31",
        pair("6190", "2020", 100),
        kind="ADJUSTING",
        reason="Accrue a cost",
        approved_by=ledger.actor_id,
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="tax agent"):
        with connection.transaction():
            ledger.post("2027-01-31", pair("6040", "2400", 100))
    connection.execute(
        "UPDATE app.gl_accounts SET is_active=false WHERE id=%s", (ledger.account("6150"),)
    )
    with pytest.raises(psycopg.errors.CheckViolation, match="turned off"):
        with connection.transaction():
            ledger.post("2027-01-31", pair("6150", "1020", 100))
    with pytest.raises(psycopg.errors.CheckViolation, match="gl_je_approved"):
        with connection.transaction():
            ledger.post("2027-01-31", pair("6190", "2020", 100), kind="ADJUSTING", reason="x")
    with pytest.raises(psycopg.errors.CheckViolation, match="names its fiscal year"):
        with connection.transaction():
            ledger.post("2027-12-31", pair("6190", "1020", 100), kind="YEAR_END_CLOSE")
    year = connection.execute(
        "SELECT id FROM app.gl_fiscal_years WHERE property_id=%s", (ledger.property_id,)
    ).fetchone()
    assert year is not None
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="every month"):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_post_entry(%s, '2027-12-31', 'YEAR_END_CLOSE', 'Early close', "
                "'FISCAL_YEAR', %s, 'test:early', NULL, %s, NULL, gen_random_uuid(), %s)",
                (ledger.property_id, year[0], ledger.actor_id, Jsonb(pair("4010", "3900", 1))),
            )


def test_months_close_in_order_with_green_checks_and_never_reopen(ledger: Ledger) -> None:
    connection = ledger.connection
    ledger.post("2027-01-10", pair("1010", "4010", 100))
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="every check"):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_close_period(%s, %s, %s)",
                (ledger.period(1), ledger.actor_id, Jsonb({"books_check": False})),
            )
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="month before"):
        with connection.transaction():
            ledger.close_month(2)
    ledger.close_month(1)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="is closed"):
        with connection.transaction():
            ledger.post("2027-01-20", pair("1010", "4010", 100))
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.gl_periods SET status='OPEN', closed_at=NULL, closed_by=NULL, "
        "close_checks=NULL WHERE id=%s",
        (ledger.period(1),),
        match="never reopens",
    )
    ledger.post("2027-02-03", pair("1010", "4010", 100))
    assert connection.execute(
        "SELECT action FROM app.audit_events WHERE entity_id=%s", (ledger.period(1),)
    ).fetchall() == [("ledger.period.closed",)]


def test_statements_balance_and_the_year_end_close_moves_profit_to_3900(ledger: Ledger) -> None:
    connection = ledger.connection
    pid = ledger.property_id
    ledger.post("2027-01-02", pair("1020", "3000", 100000))
    ledger.post("2027-01-05", pair("1100", "2050", 50000))
    ledger.post("2027-02-01", pair("2050", "4010", 50000), kind="RENT_TO_INCOME")
    ledger.post("2027-02-03", pair("1010", "2210", 30000))
    ledger.post("2027-02-03", pair("2210", "1100", 30000))
    ledger.post("2027-02-10", pair("6010", "1020", 12000))
    ledger.post("2027-03-01", pair("1510", "2600", 200000))
    ledger.post("2027-03-02", pair("1530", "1020", 5000))
    ledger.post("2027-03-03", pair("1010", "1020", 1000))
    ledger.check_balanced()

    def trial_balance(on: str) -> tuple[int, int]:
        row = connection.execute(
            "SELECT sum(debit_balance_cents), sum(credit_balance_cents) "
            "FROM app.gl_trial_balance(%s, %s)",
            (pid, on),
        ).fetchone()
        assert row is not None
        return int(row[0]), int(row[1])

    def balance_sheet(on: str) -> dict[str, int]:
        rows = connection.execute(
            "SELECT section, sum(amount_cents) FROM app.gl_balance_sheet(%s, %s) GROUP BY 1",
            (pid, on),
        ).fetchall()
        return {row[0]: int(row[1]) for row in rows}

    debit, credit = trial_balance("2027-06-30")
    assert debit == credit > 0
    sheet = balance_sheet("2027-06-30")
    assert sheet["ASSET"] == sheet["LIABILITY"] + sheet["EQUITY"]
    assert connection.execute(
        "SELECT amount_cents FROM app.gl_balance_sheet(%s, '2027-06-30') WHERE code IS NULL",
        (pid,),
    ).fetchone() == (38000,)
    profit = connection.execute(
        "SELECT code, amount_cents FROM app.gl_profit_and_loss(%s, '2027-01-01', '2027-12-31')",
        (pid,),
    ).fetchall()
    assert profit == [("4010", 50000), ("6010", 12000)]
    flows = connection.execute(
        "SELECT cash_flow_group, code, amount_cents "
        "FROM app.gl_cash_flow(%s, '2027-01-01', '2027-12-31')",
        (pid,),
    ).fetchall()
    assert flows == [
        ("FINANCING", "3000", 100000),
        ("INVESTING", "1530", -5000),
        ("OPERATING", "2210", 30000),
        ("OPERATING", "6010", -12000),
    ]
    cash_end = connection.execute(
        "SELECT sum(balance.balance_cents) FROM app.gl_account_balances(%s, '2027-12-31') "
        "AS balance JOIN app.gl_accounts AS account ON account.id=balance.account_id "
        "WHERE account.cash_kind IS NOT NULL",
        (pid,),
    ).fetchone()
    assert cash_end == (sum(row[2] for row in flows),)
    detail = connection.execute(
        "SELECT line_no, debit_cents, credit_cents, running_balance_cents "
        "FROM app.gl_ledger_detail(%s, '2027-02-01', '2027-12-31')",
        (ledger.account("1020"),),
    ).fetchall()
    assert detail == [
        (0, 0, 0, 100000),
        (2, 0, 12000, 88000),
        (2, 0, 5000, 83000),
        (2, 0, 1000, 82000),
    ]

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="every month"):
        with connection.transaction():
            connection.execute(
                "SELECT app.gl_close_year(id, %s, NULL) FROM app.gl_fiscal_years "
                "WHERE property_id=%s",
                (ledger.actor_id, pid),
            )
    for month in range(1, 13):
        ledger.close_month(month)
    closing = connection.execute(
        "SELECT app.gl_close_year(id, %s, 'Year 2027') FROM app.gl_fiscal_years "
        "WHERE property_id=%s",
        (ledger.actor_id, pid),
    ).fetchone()
    assert closing is not None
    ledger.check_balanced()
    balances = dict(
        connection.execute(
            "SELECT code, balance_cents FROM app.gl_account_balances(%s, '2027-12-31') "
            "WHERE code IN ('3900','4010','6010')",
            (pid,),
        ).fetchall()
    )
    assert balances == {"3900": 38000, "4010": 0, "6010": 0}
    assert trial_balance("2027-12-31")[0] == trial_balance("2027-12-31")[1]
    sheet = balance_sheet("2027-12-31")
    assert sheet["ASSET"] == sheet["LIABILITY"] + sheet["EQUITY"]
    assert connection.execute(
        "SELECT amount_cents FROM app.gl_balance_sheet(%s, '2027-12-31') WHERE code IS NULL",
        (pid,),
    ).fetchone() == (0,)
    # The year's profit and loss still shows the year: the closing entry is left out.
    assert connection.execute(
        "SELECT sum(CASE WHEN section='INCOME' THEN amount_cents ELSE -amount_cents END) "
        "FROM app.gl_profit_and_loss(%s, '2027-01-01', '2027-12-31')",
        (pid,),
    ).fetchone() == (38000,)
    assert connection.execute(
        "SELECT year.status, year.closing_entry_id, period.status FROM app.gl_fiscal_years AS "
        "year JOIN app.gl_periods AS period ON period.fiscal_year_id=year.id "
        "AND period.period_no=13 WHERE year.property_id=%s",
        (pid,),
    ).fetchone() == ("CLOSED", closing[0], "CLOSED")
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.gl_fiscal_years SET status='OPEN', closed_at=NULL, closed_by=NULL, "
        "closing_entry_id=NULL WHERE property_id=%s",
        (pid,),
        match="never reopens",
    )


def test_records_follow_their_steps_and_rules(ledger: Ledger) -> None:
    connection = ledger.connection
    pid, me = ledger.property_id, ledger.actor_id
    other = insert_actor(connection)
    unit = insert_unit(
        connection, actor_id=me, property_id=pid, unit_number=f"GL-{uuid4().hex[:8]}"
    )
    request = uuid4()
    connection.execute(
        "INSERT INTO app.gl_expense_requests(id, property_id, request_number, request_kind, "
        "requested_by, account_id, description, reason, amount_cents, status, paid_how, "
        "created_by) VALUES (%s,%s,'ER270001','REQUEST',%s,%s,'Fix tap','Leak in 3A',2500,"
        "'WAITING','ADVANCE',%s)",
        (request, pid, me, ledger.account("6050"), me),
    )
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "UPDATE app.gl_expense_requests SET status='APPROVED', decided_by=%s, "
        "decided_at=now() WHERE id=%s",
        (me, request),
        match="gl_er_not_own",
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.gl_expense_requests SET amount_cents=9999 WHERE id=%s",
        (request,),
        match="cannot change",
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "UPDATE app.gl_expense_requests SET status='DONE', decided_by=%s, decided_at=now() "
        "WHERE id=%s",
        (other, request),
        match="cannot go from WAITING to DONE",
    )
    connection.execute(
        "UPDATE app.gl_expense_requests SET status='APPROVED', decided_by=%s, decided_at=now() "
        "WHERE id=%s",
        (other, request),
    )
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "UPDATE app.gl_expense_requests SET status='PAID_OUT', paid_from_account_id=%s WHERE id=%s",
        (ledger.account("6190"), request),
        match="cash or bank",
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        "DELETE FROM app.gl_expense_requests WHERE id=%s",
        (request,),
        match="never deleted",
    )
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "INSERT INTO app.gl_expense_requests(id, property_id, request_number, request_kind, "
        "requested_by, account_id, description, reason, amount_cents, status, unit_id, "
        "paid_how, created_by) VALUES (gen_random_uuid(),%s,'ER270002','REQUEST',%s,%s,'Paper',"
        "'Office',100,'WAITING',%s,'ADVANCE',%s)",
        (pid, me, ledger.account("6130"), unit, me),
        match="does not take a Unit",
    )

    supplier = connection.execute(
        "INSERT INTO app.gl_suppliers(id, property_id, name, created_by) "
        "VALUES (gen_random_uuid(), %s, 'EDC', %s) RETURNING id",
        (pid, me),
    ).fetchone()
    assert supplier is not None
    bill = connection.execute(
        "INSERT INTO app.gl_supplier_bills(id, property_id, bill_number, supplier_id, bill_date, "
        "due_date, amount_cents, status, created_by) VALUES (gen_random_uuid(), %s, 'SB270001', "
        "%s, '2027-01-05', '2027-02-04', 10000, 'OPEN', %s) RETURNING id",
        (pid, supplier[0], me),
    ).fetchone()
    assert bill is not None
    payment = (
        "INSERT INTO app.gl_bill_payments(id, property_id, supplier_bill_id, paid_on, "
        "amount_cents, paid_from_account_id, entry_id, created_by) VALUES (gen_random_uuid(), "
        "%s, %s, '2027-01-20', %s, %s, %s, %s)"
    )
    first = ledger.post("2027-01-20", pair("2010", "1020", 6000))
    connection.execute(payment, (pid, bill[0], 6000, ledger.account("1020"), first, me))
    second = ledger.post("2027-01-21", pair("2010", "1020", 5000))
    refused(
        connection,
        psycopg.errors.CheckViolation,
        payment,
        (pid, bill[0], 5000, ledger.account("1020"), second, me),
        match="more than the bill",
    )

    move = ledger.post("2027-01-22", pair("1010", "1020", 100))
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "INSERT INTO app.gl_money_moves(id, property_id, move_number, moved_on, from_account_id, "
        "to_account_id, amount_cents, entry_id, created_by) VALUES (gen_random_uuid(), %s, "
        "'MV270001', '2027-01-22', %s, %s, 100, %s, %s)",
        (pid, ledger.account("1020"), ledger.account("1020"), move, me),
        match="gl_mv_two_accounts",
    )

    adjustment = connection.execute(
        "INSERT INTO app.gl_adjusting_entries(id, property_id, adjustment_number, entry_date, "
        "reason, prepared_by, status, created_by) VALUES (gen_random_uuid(), %s, 'AJ270001', "
        "'2027-01-31', 'Accrue water', %s, 'WAITING', %s) RETURNING id",
        (pid, me, me),
    ).fetchone()
    assert adjustment is not None
    refused(
        connection,
        psycopg.errors.CheckViolation,
        "INSERT INTO app.gl_adjusting_entry_lines(id, adjusting_entry_id, property_id, line_no, "
        "account_id, debit_cents) VALUES (gen_random_uuid(), %s, %s, 1, %s, 100)",
        (adjustment[0], pid, ledger.account("1100")),
        match="cannot take a typed line",
    )

    year = connection.execute(
        "SELECT id FROM app.gl_fiscal_years WHERE property_id=%s", (pid,)
    ).fetchone()
    assert year is not None
    budget = connection.execute(
        "INSERT INTO app.gl_budgets(id, fiscal_year_id, property_id, version, status, "
        "created_by) VALUES (gen_random_uuid(), %s, %s, 1, 'DRAFT', %s) RETURNING id",
        (year[0], pid, me),
    ).fetchone()
    assert budget is not None
    line = (
        "INSERT INTO app.gl_budget_lines(id, budget_id, property_id, account_id, month_no, "
        "amount_cents) VALUES (gen_random_uuid(), %s, %s, %s, %s, 40000)"
    )
    connection.execute(line, (budget[0], pid, ledger.account("6010"), 1))
    connection.execute(
        "UPDATE app.gl_budgets SET status='APPROVED', approved_by=%s, approved_at=now() "
        "WHERE id=%s",
        (other, budget[0]),
    )
    refused(
        connection,
        psycopg.errors.ObjectNotInPrerequisiteState,
        line,
        (budget[0], pid, ledger.account("6010"), 2),
        match="locked",
    )


def test_the_runtime_role_only_reads_the_ledger(migrated_database_url: str) -> None:
    assert migrated_database_url
    with psycopg.connect(runtime_database_url()) as runtime:
        assert runtime.execute("SELECT count(*) >= 0 FROM app.gl_journal_entries").fetchone()
        assert runtime.execute("SELECT count(*) = 59 FROM app.gl_chart_template").fetchone() == (
            True,
        )
        for query in (
            "INSERT INTO app.gl_suppliers(id, property_id, name, created_by) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'x', gen_random_uuid())",
            "SELECT app.gl_start_ledger(gen_random_uuid(), 2027::smallint, gen_random_uuid())",
            "SELECT app.gl_close_period(gen_random_uuid(), gen_random_uuid(), '{}'::jsonb)",
        ):
            refused(runtime, psycopg.errors.InsufficientPrivilege, query)
        runtime.rollback()


def test_the_migrations_chain_and_roll_back_only_while_the_ledger_is_empty(
    migrated_database_url: str,
) -> None:
    assert migrated_database_url
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    # The business rules and ledger rights (263, 264, phase 6) come after the ledger tables.
    assert script.get_revision("20270413_263").down_revision == REVISIONS[-1]
    previous = BEFORE_LEDGER
    for revision in REVISIONS:
        found = script.get_revision(revision)
        assert found is not None and found.down_revision == previous
        previous = revision
    with _temporary_migration_database("prm_general_ledger") as temporary:
        assert _run_alembic("upgrade", REVISIONS[-1]).returncode == 0
        assert _run_alembic("downgrade", BEFORE_LEDGER).returncode == 0
        assert _run_alembic("upgrade", REVISIONS[-1]).returncode == 0
        with psycopg.connect(temporary) as connection:
            actor_id = insert_actor(connection)
            property_id = insert_property(connection, actor_id)
            connection.execute(
                "SELECT app.gl_start_ledger(%s, 2027::smallint, %s)", (property_id, actor_id)
            )
            Ledger(connection, property_id, actor_id).post("2027-01-02", pair("1020", "3000", 100))
            connection.commit()
        result = _run_alembic("downgrade", BEFORE_LEDGER)
        assert result.returncode != 0
        assert "it cannot be rolled back" in result.stderr
        with psycopg.connect(temporary) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                REVISIONS[-1],
            )
