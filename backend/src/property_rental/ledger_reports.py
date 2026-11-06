"""General Ledger reports (phase 6 step 5): the Financial statements and their files.

Owner decisions: DESIGN.md round 22 (Financial statements: Profit and loss with This month, Last
month, Same month last year, Year to date and Difference, Gross profit, Profit (or loss) and the
three margins; Balance sheet within and after 12 months, with Profit this year; Cash flow by the
direct method from cash at start to cash at end; Customer debt and Supplier bill aging in Not yet
due, 1-30, 31-60, 61-90 and Over 90 days; Budget vs actual for the month and the year to date,
marked when more than the Budget warning percent and amount off; each report ends with a green or
red check line), gap G1 (round 25: Excel and PDF files that show the month and Closed or "Open,
may still change"; the aging reports say "As at today") and the phase 6 plan (step 5: Trial
balance, Account detail).

The builders here are pure: they take the rows the database gives and work out the totals, the
groups and the check line, in whole cents. ``PostgresLedgerReports`` reads those rows with the
runtime login; the route has checked ``ledger.read`` first, and the two reads the runtime login
cannot make alone (Customer balances, the Budget warning rules) check it again in the database
(migration ``20270420_270``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import psycopg

from property_rental.ledger_money_api import (
    LedgerMoneyInvalid,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    _json,
    _refusal,
)
from property_rental.report_files import Column, ExportFile, FileType, build_file

ReportName = Literal[
    "trial-balance",
    "profit-and-loss",
    "balance-sheet",
    "cash-flow",
    "account-detail",
    "customer-aging",
    "bills-aging",
    "budget",
]
REPORT_NAMES: Final[tuple[ReportName, ...]] = (
    "trial-balance",
    "profit-and-loss",
    "balance-sheet",
    "cash-flow",
    "account-detail",
    "customer-aging",
    "bills-aging",
    "budget",
)
CLOSED: Final = "Closed"
OPEN: Final = "Open, may still change"
TODAY: Final = "As at today"
C = Column
CODE = C("code", "Account")
NAME = C("name", "Name")
BUCKETS: Final = (
    C("not_due", "Not yet due", "money"),
    C("days_1_30", "1-30 days", "money"),
    C("days_31_60", "31-60 days", "money"),
    C("days_61_90", "61-90 days", "money"),
    C("over_90", "Over 90 days", "money"),
    C("total", "Total", "money"),
)
P_AND_L_SECTIONS: Final = (
    ("INCOME", "Income"),
    ("COST_OF_SALES", "Cost of products sold"),
    ("EXPENSE", "Expenses"),
)
MARGINS: Final = (
    ("Margin: products (4080 less 5010)", "4080", "5010"),
    ("Margin: electricity (4030 less 6010)", "4030", "6010"),
    ("Margin: water (4040 less 6020)", "4040", "6020"),
)
RIEL_HELD_ON: Final = """
    SELECT account.code,
        coalesce(counted.counted_riel, 0) + coalesce((
            SELECT sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
                            ELSE -line.original_amount_minor END)
            FROM app.gl_journal_lines AS line
            JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
            WHERE line.account_id = account.id AND line.original_currency = 'KHR'
              AND entry.entry_date <= %(day)s
              AND entry.entry_date > coalesce(counted.counted_on, '-infinity')), 0)
    FROM app.gl_accounts AS account
    LEFT JOIN LATERAL (
        SELECT item.counted_on, item.counted_riel
        FROM app.gl_cash_counts AS item
        WHERE account.cash_kind = 'CASH_KHR' AND item.account_id = account.id
          AND item.counted_riel IS NOT NULL AND item.counted_on <= %(day)s
        ORDER BY item.counted_on DESC, item.created_at DESC
        LIMIT 1
    ) AS counted ON true
    WHERE account.property_id = %(prop)s AND account.cash_kind IN ('CASH_KHR', 'BANK_KHR')
"""

BALANCE_GROUPS: Final = (
    ("ASSET", "CURRENT", "Assets within 12 months"),
    ("ASSET", "NON_CURRENT", "Building and equipment after depreciation"),
    ("LIABILITY", "CURRENT", "Owed within 12 months"),
    ("LIABILITY", "NON_CURRENT", "Owed after 12 months"),
    ("EQUITY", None, "Owner's equity"),
)
CASH_GROUPS: Final = (
    ("OPERATING", "Daily business"),
    ("INVESTING", "Equipment"),
    ("FINANCING", "Owner money and loans"),
)
PROFIT_NAME: Final = "Profit this year not closed yet"


@dataclass(frozen=True, slots=True)
class ReportParams:
    """What the report covers; a missing value takes today or this month."""

    as_of: date | None = None
    month: date | None = None
    start: date | None = None
    end: date | None = None
    account: str | None = None


@dataclass(frozen=True, slots=True)
class LedgerReport:
    name: str
    title: str
    period: str
    state: str
    columns: tuple[Column, ...]
    rows: tuple[dict[str, Any], ...]
    check_ok: bool
    check_text: str
    made_on: date | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "report": self.name,
            "title": self.title,
            "period": self.period,
            "state": self.state,
            "columns": [
                {"key": column.key, "label": column.label, "kind": column.kind}
                for column in self.columns
            ],
            "rows": [{key: _json(value) for key, value in row.items()} for row in self.rows],
            "check": {"ok": self.check_ok, "text": self.check_text},
            **self.extra,
        }

    def file(self, file_type: FileType) -> ExportFile:
        made = "" if self.made_on is None else f" Made on {_day(self.made_on)}."
        lines = (
            self.period,
            self.state,
            f"Check: {self.check_text}",
            f"Amounts in US dollars.{made}",
        )
        return build_file(
            file_type,
            f"{self.name}-{(self.made_on or date.today()).isoformat()}",
            self.title,
            lines,
            self.columns,
            self.rows,
        )


def _day(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _money(cents: int) -> str:
    return f"-${-cents / 100:,.2f}" if cents < 0 else f"${cents / 100:,.2f}"


def _check(ok: bool, good: str, bad: str, off: int) -> tuple[bool, str]:
    return ok, good if ok else f"{bad} by {_money(abs(off))}"


def _account(code: str, name: str, **values: Any) -> dict[str, Any]:
    return {"line": "account", "code": code, "name": name, **values}


def _total(name: str, **values: Any) -> dict[str, Any]:
    return {"line": "total", "code": None, "name": name, **values}


def _heading(name: str) -> dict[str, Any]:
    return {"line": "heading", "code": None, "name": name}


def trial_balance(
    rows: Iterable[tuple[str, str, int, int]], *, period: str, state: str
) -> LedgerReport:
    """Each account's debit or credit balance; the totals are the same."""
    lines = [_account(code, name, debit=debit, credit=credit) for code, name, debit, credit in rows]
    debit = sum(line["debit"] for line in lines)
    credit = sum(line["credit"] for line in lines)
    lines.append(_total("Total", debit=debit, credit=credit))
    ok, text = _check(
        debit == credit, "Debits equal credits", "Debits and credits differ", debit - credit
    )
    return LedgerReport(
        "trial-balance",
        "Trial balance",
        period,
        state,
        (CODE, NAME, C("debit", "Debit", "money"), C("credit", "Credit", "money")),
        tuple(lines),
        ok,
        text,
    )


P_AND_L_COLUMNS: Final = (
    "this_month",
    "last_month",
    "same_month_last_year",
    "year_to_date",
)


def profit_and_loss(
    amounts: Mapping[str, Iterable[tuple[str, str, str, int]]],
    *,
    book_profit: int | None,
    period: str,
    state: str,
) -> LedgerReport:
    """Income, cost of products sold and expenses in the four columns, with Difference.

    ``amounts`` holds, for each column, (section, code, name, amount) rows: income as a credit
    balance, costs as a debit balance. ``book_profit`` is the Balance sheet's Profit this year at
    the month's end, or None when the year is closed (its profit has moved to 3900)."""
    sections: dict[str, str] = {}
    names: dict[str, str] = {}
    values: dict[str, dict[str, int]] = defaultdict(dict)
    for column in P_AND_L_COLUMNS:
        for section, code, name, amount in amounts.get(column, ()):
            sections[code] = section
            names[code] = name
            values[code][column] = amount

    def cells(source: Mapping[str, int]) -> dict[str, int]:
        found = {column: int(source.get(column, 0)) for column in P_AND_L_COLUMNS}
        return {**found, "difference": found["this_month"] - found["last_month"]}

    def add(*parts: tuple[int, Mapping[str, int]]) -> dict[str, int]:
        return {
            column: sum(sign * part[column] for sign, part in parts)
            for column in (*P_AND_L_COLUMNS, "difference")
        }

    rows: list[dict[str, Any]] = []
    totals: dict[str, dict[str, int]] = {}
    for section, title in P_AND_L_SECTIONS:
        rows.append(_heading(title))
        codes = sorted(code for code, found in sections.items() if found == section)
        section_rows = [cells(values[code]) for code in codes]
        rows.extend(
            _account(code, names[code], **found)
            for code, found in zip(codes, section_rows, strict=True)
        )
        totals[section] = (
            add(*((1, found) for found in section_rows)) if section_rows else cells({})
        )
        rows.append(_total(f"Total {title.lower()}", **totals[section]))
        if section == "COST_OF_SALES":
            gross = add((1, totals["INCOME"]), (-1, totals["COST_OF_SALES"]))
            rows.append(_total("Gross profit", **gross))
    profit = add((1, totals["INCOME"]), (-1, totals["COST_OF_SALES"]), (-1, totals["EXPENSE"]))
    rows.append(_total("Profit (or loss)", **profit))
    rows.append(_heading("Margins"))
    for title, income, cost in MARGINS:
        rows.append(_total(title, **add((1, cells(values[income])), (-1, cells(values[cost])))))
    if book_profit is None:
        ok, text = True, "The year is closed; its profit is in 3900 Profit kept from past years"
    else:
        ok, text = _check(
            profit["year_to_date"] == book_profit,
            "Profit this year matches the Balance sheet",
            "Profit this year and the Balance sheet differ",
            profit["year_to_date"] - book_profit,
        )
    return LedgerReport(
        "profit-and-loss",
        "Profit and loss",
        period,
        state,
        (
            CODE,
            NAME,
            C("this_month", "This month", "money"),
            C("last_month", "Last month", "money"),
            C("same_month_last_year", "Same month last year", "money"),
            C("year_to_date", "Year to date", "money"),
            C("difference", "Difference", "money"),
        ),
        tuple(rows),
        ok,
        text,
    )


def balance_sheet(
    balances: Iterable[tuple[str, str, str, str | None, int, int]],
    *,
    period: str,
    state: str,
    riel: Mapping[str, int] | None = None,
) -> LedgerReport:
    """Assets against what is owed and the Owner's equity, with Profit this year.

    ``balances`` holds (code, name, account type, balance sheet section, debits, credits) for every
    account up to the day; income and cost accounts make Profit this year. ``riel`` holds the riel
    each riel account (1011, 1021) held on the day; its line says it (owner 05/11/2026)."""
    held = riel or {}
    groups: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    profit = 0
    for code, name, account_type, section, debit, credit in balances:
        if account_type in ("INCOME", "COST_OF_SALES", "EXPENSE"):
            profit += credit - debit
            continue
        amount = debit - credit if account_type == "ASSET" else credit - debit
        if amount or held.get(code):
            key = (account_type, section if account_type != "EQUITY" else None)
            if code in held:
                name = f"{name} ({held[code]:,} riel)"
            groups[key].append(_account(code, name, amount=amount))
    groups[("EQUITY", None)].append(_account("", PROFIT_NAME, amount=profit) | {"code": None})
    rows: list[dict[str, Any]] = []
    kinds: dict[str, int] = defaultdict(int)
    for account_type, section, title in BALANCE_GROUPS:
        found = groups.get((account_type, section), [])
        if not found:
            continue
        rows.append(_heading(title))
        rows.extend(found)
        subtotal = sum(line["amount"] for line in found)
        kinds[account_type] += subtotal
        rows.append(_total(f"Total {title[0].lower()}{title[1:]}", amount=subtotal))
    assets, owed, equity = kinds["ASSET"], kinds["LIABILITY"], kinds["EQUITY"]
    rows.append(_total("Total assets", amount=assets))
    rows.append(_total("Owed plus Owner's equity", amount=owed + equity))
    ok, text = _check(
        assets == owed + equity,
        "Assets equal what is owed plus the Owner's equity",
        "Assets and what is owed plus equity differ",
        assets - owed - equity,
    )
    return LedgerReport(
        "balance-sheet",
        "Balance sheet",
        period,
        state,
        (CODE, NAME, C("amount", "Amount", "money")),
        tuple(rows),
        ok,
        text,
        extra={"profit_this_year_cents": profit},
    )


def cash_flow(
    start: int,
    flows: Iterable[tuple[str, str, str, int]],
    end: int,
    *,
    period: str,
    state: str,
) -> LedgerReport:
    """Cash at start, money in (plus) and out (minus) by group, cash at end.

    ``flows`` holds (cash-flow group, code, name, amount) for the other side of each entry that
    touches cash; a move between two cash accounts is not a flow."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group, code, name, amount in flows:
        grouped[group].append(_account(code, name, amount=amount))
    rows: list[dict[str, Any]] = [_total("Cash at start", amount=start)]
    change = 0
    known = [group for group, _ in CASH_GROUPS]
    titles = [*CASH_GROUPS, *((group, group.title()) for group in grouped if group not in known)]
    for group, title in titles:
        found = grouped.get(group, [])
        rows.append(_heading(title))
        rows.extend(found)
        subtotal = sum(line["amount"] for line in found)
        change += subtotal
        rows.append(_total(f"Total {title[0].lower()}{title[1:]}", amount=subtotal))
    rows.append(_total("Change in cash", amount=change))
    rows.append(_total("Cash at end", amount=end))
    ok, text = _check(
        start + change == end,
        "Cash at start plus the flows equals cash at end",
        "Cash at start plus the flows and cash at end differ",
        start + change - end,
    )
    return LedgerReport(
        "cash-flow",
        "Cash flow",
        period,
        state,
        (CODE, NAME, C("amount", "Amount", "money")),
        tuple(rows),
        ok,
        text,
    )


def account_detail(
    code: str,
    name: str,
    lines: Iterable[tuple[str | None, date, str | None, str | None, int, int, int]],
    closing: int,
    *,
    period: str,
    state: str,
) -> LedgerReport:
    """The opening balance, each line with the running balance, and the closing balance.

    ``lines`` holds (entry number, date, description, memo, debit, credit, running balance); the
    first one is the opening balance."""
    rows: list[dict[str, Any]] = [
        {
            "line": "total" if number is None else "account",
            "entry_date": day,
            "entry_number": number,
            "description": description,
            "memo": memo,
            "debit": debit or None,
            "credit": credit or None,
            "balance": balance,
        }
        for number, day, description, memo, debit, credit, balance in lines
    ]
    last = int(rows[-1]["balance"]) if rows else 0
    ok, text = _check(
        last == closing,
        "The closing balance matches the account",
        "The closing balance and the account differ",
        last - closing,
    )
    return LedgerReport(
        "account-detail",
        f"Account detail: {code} {name}",
        period,
        state,
        (
            C("entry_date", "Date", "date"),
            C("entry_number", "Entry"),
            C("description", "Description"),
            C("memo", "Memo"),
            C("debit", "Debit", "money"),
            C("credit", "Credit", "money"),
            C("balance", "Balance", "money"),
        ),
        tuple(rows),
        ok,
        text,
        extra={"account": {"code": code, "name": name}, "closing_cents": closing},
    )


def _bucket(today: date, due: date | None) -> str:
    late = 0 if due is None else (today - due).days
    if late <= 0:
        return "not_due"
    if late <= 30:
        return "days_1_30"
    if late <= 60:
        return "days_31_60"
    if late <= 90:
        return "days_61_90"
    return "over_90"


def _aging_rows(
    items: Iterable[tuple[tuple[str, ...], date | None, int]], today: date, keys: Sequence[str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[tuple[str, ...], dict[str, int]] = {}
    for key, due, cents in items:
        found = grouped.setdefault(key, {column.key: 0 for column in BUCKETS})
        found[_bucket(today, due)] += cents
        found["total"] += cents
    totals = {
        column.key: sum(found[column.key] for found in grouped.values()) for column in BUCKETS
    }
    rows: list[dict[str, Any]] = [
        {"line": "account", **dict(zip(keys, key, strict=True)), **found}
        for key, found in sorted(grouped.items())
    ]
    return rows, totals


def customer_aging(
    items: Iterable[tuple[str, str | None, date | None, int]],
    today: date,
    in_books: int,
) -> LedgerReport:
    """Unpaid Invoices and Late-payment charges by Customer and Unit, by how late they are.

    ``items`` holds (Customer, Unit, due day, unpaid cents); ``in_books`` is 1100 + 1110."""
    rows, totals = _aging_rows(
        (((customer, unit or ""), due, cents) for customer, unit, due, cents in items),
        today,
        ("customer_name", "unit_number"),
    )
    rows.append({"line": "total", "customer_name": "Total", "unit_number": None, **totals})
    ok, text = _check(
        totals["total"] == in_books,
        "The total equals 1100 + 1110 in the books",
        "The total and 1100 + 1110 in the books differ",
        totals["total"] - in_books,
    )
    return LedgerReport(
        "customer-aging",
        "Customer debt aging",
        f"{TODAY}, {_day(today)}",
        TODAY,
        (C("customer_name", "Customer"), C("unit_number", "Unit"), *BUCKETS),
        tuple(rows),
        ok,
        text,
    )


def bills_aging(
    bills: Iterable[tuple[str, date, int]],
    today: date,
    in_books: int,
    staff_advances: int,
    owed_to_staff: int,
) -> LedgerReport:
    """Supplier bills still to pay by supplier, by how late they are, with the open staff
    advances (1400) and the money owed to staff (2310).

    ``bills`` holds (supplier, due day, cents still to pay); ``in_books`` is 2010."""
    rows, totals = _aging_rows(
        (((supplier,), due, cents) for supplier, due, cents in bills), today, ("supplier",)
    )
    rows.append({"line": "total", "supplier": "Total supplier bills", **totals})
    rows.append({"line": "total", "supplier": "Staff advances (1400)", "total": staff_advances})
    rows.append({"line": "total", "supplier": "Money owed to staff (2310)", "total": owed_to_staff})
    ok, text = _check(
        totals["total"] == in_books,
        "Supplier bills equal 2010 in the books",
        "Supplier bills and 2010 in the books differ",
        totals["total"] - in_books,
    )
    return LedgerReport(
        "bills-aging",
        "Supplier bill aging",
        f"{TODAY}, {_day(today)}",
        TODAY,
        (C("supplier", "Supplier"), *BUCKETS),
        tuple(rows),
        ok,
        text,
    )


def _off(budget: int, actual: int, percent_hundredths: int, smallest: int) -> bool:
    gap = abs(actual - budget)
    return gap > smallest and gap * 10_000 > percent_hundredths * abs(budget)


def budget_against_actual(
    budget_lines: Iterable[tuple[str, str, int, int]],
    month_actual: Mapping[str, int],
    year_actual: Mapping[str, int],
    names: Mapping[str, str],
    *,
    month_no: int,
    percent_hundredths: int,
    smallest: int,
    approved_version: int | None,
    period: str,
    state: str,
) -> LedgerReport:
    """The month and the year to date against the approved budget, line by line.

    ``budget_lines`` holds (code, name, month number, cents); actuals are as in Profit and loss.
    A line is marked when it is more than the Budget warning percent and amount off."""
    month_budget: dict[str, int] = defaultdict(int)
    year_budget: dict[str, int] = defaultdict(int)
    all_names = dict(names)
    for code, name, number, cents in budget_lines:
        all_names.setdefault(code, name)
        if number == month_no:
            month_budget[code] += cents
        if number <= month_no:
            year_budget[code] += cents
    codes = sorted({*month_budget, *year_budget, *month_actual, *year_actual})
    rows: list[dict[str, Any]] = []
    for code in codes:
        month = (month_budget.get(code, 0), int(month_actual.get(code, 0)))
        year = (year_budget.get(code, 0), int(year_actual.get(code, 0)))
        rows.append(
            _account(
                code,
                all_names.get(code, ""),
                budget_month=month[0],
                actual_month=month[1],
                difference_month=month[1] - month[0],
                month_off=_off(*month, percent_hundredths, smallest),
                budget_year=year[0],
                actual_year=year[1],
                difference_year=year[1] - year[0],
                year_off=_off(*year, percent_hundredths, smallest),
            )
        )
    marked = sum(1 for row in rows if row["month_off"] or row["year_off"])
    if approved_version is None:
        ok, text = False, "There is no approved budget for this year"
    elif marked:
        ok, text = False, f"{marked} lines are more than the Budget warning off"
    else:
        ok, text = True, "Every line is within the Budget warning"
    return LedgerReport(
        "budget",
        "Budget vs actual",
        period,
        state,
        (
            CODE,
            NAME,
            C("budget_month", "Budget this month", "money"),
            C("actual_month", "Actual this month", "money"),
            C("difference_month", "Difference this month", "money"),
            C("month_off", "Marked this month", "bool"),
            C("budget_year", "Budget year to date", "money"),
            C("actual_year", "Actual year to date", "money"),
            C("difference_year", "Difference year to date", "money"),
            C("year_off", "Marked year to date", "bool"),
        ),
        tuple(rows),
        ok,
        text,
        extra={
            "budget_version": approved_version,
            "warning": {"percent_hundredths": percent_hundredths, "smallest_cents": smallest},
        },
    )


class LedgerReportFlow(Protocol):
    def report(
        self, name: ReportName, property_id: UUID, actor_id: str, params: ReportParams
    ) -> LedgerReport: ...


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    following = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def months_back(day: date, months: int) -> date:
    """The first day of the month that many months before ``day``'s month."""
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


Connection = psycopg.Connection[Any]


class PostgresLedgerReports:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def report(
        self, name: ReportName, property_id: UUID, actor_id: str, params: ReportParams
    ) -> LedgerReport:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT timezone(timezone_name, statement_timestamp())::date "
                    "FROM app.properties WHERE id = %s",
                    (property_id,),
                ).fetchone()
                if row is None:
                    raise LedgerMoneyNotFound
                today: date = row[0]
                made = self._make(connection, name, property_id, UUID(actor_id), params, today)
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return replace(made, made_on=today)

    def _make(
        self,
        connection: Connection,
        name: ReportName,
        prop: UUID,
        actor: UUID,
        params: ReportParams,
        today: date,
    ) -> LedgerReport:
        if name == "trial-balance":
            day = params.as_of or today
            rows = connection.execute(
                "SELECT code, name_en, debit_balance_cents, credit_balance_cents "
                "FROM app.gl_trial_balance(%s, %s)",
                (prop, day),
            ).fetchall()
            return trial_balance(
                rows, period=f"As at {_day(day)}", state=self._state(connection, prop, day, day)
            )
        if name == "balance-sheet":
            day = params.as_of or today
            return balance_sheet(
                self._balances(connection, prop, day),
                period=f"As at {_day(day)}",
                state=self._state(connection, prop, day, day),
                riel=self._riel(connection, prop, day),
            )
        if name == "profit-and-loss":
            return self._profit_and_loss(connection, prop, params.month or today)
        if name == "cash-flow":
            start, end = self._range(params, today)
            return cash_flow(
                self._cash(connection, prop, start - timedelta(days=1)),
                connection.execute(
                    "SELECT cash_flow_group, code, name_en, amount_cents "
                    "FROM app.gl_cash_flow(%s, %s, %s)",
                    (prop, start, end),
                ).fetchall(),
                self._cash(connection, prop, end),
                period=f"{_day(start)} to {_day(end)}",
                state=self._state(connection, prop, start, end),
            )
        if name == "account-detail":
            return self._account_detail(connection, prop, params, today)
        if name == "customer-aging":
            items = connection.execute(
                "SELECT customer_name, unit_number, due_date, balance_cents "
                "FROM app.gl_customer_aging(%s, %s)",
                (prop, actor),
            ).fetchall()
            return customer_aging(
                ((customer, unit, due, int(cents)) for customer, unit, due, cents in items),
                today,
                self._natural(connection, prop, today, ("1100", "1110")),
            )
        if name == "bills-aging":
            bills = connection.execute(
                """
                SELECT supplier.name, bill.due_date, bill.amount_cents - coalesce((
                    SELECT sum(payment.amount_cents) FROM app.gl_bill_payments AS payment
                    WHERE payment.supplier_bill_id = bill.id
                      AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS undone
                                      WHERE undone.bill_payment_id = payment.id)), 0)
                FROM app.gl_supplier_bills AS bill
                JOIN app.gl_suppliers AS supplier ON supplier.id = bill.supplier_id
                WHERE bill.property_id = %s AND bill.status = 'OPEN'
                """,
                (prop,),
            ).fetchall()
            return bills_aging(
                ((supplier, due, int(cents)) for supplier, due, cents in bills if cents),
                today,
                self._natural(connection, prop, today, ("2010",)),
                self._natural(connection, prop, today, ("1400",)),
                self._natural(connection, prop, today, ("2310",)),
            )
        return self._budget(connection, prop, actor, params.month or today)

    @staticmethod
    def _range(params: ReportParams, today: date) -> tuple[date, date]:
        start = params.start or month_start(params.end or today)
        end = params.end or (today if start <= today <= month_end(start) else month_end(start))
        if start > end:
            raise LedgerMoneyInvalid("The first day is after the last day")
        return start, end

    @staticmethod
    def _state(connection: Connection, prop: UUID, start: date, end: date) -> str:
        """Closed when every month the report covers is closed."""
        row = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE status = 'CLOSED') FROM app.gl_periods "
            "WHERE property_id = %s AND period_no <= 12 AND starts_on <= %s AND ends_on >= %s",
            (prop, end, start),
        ).fetchone()
        assert row is not None
        return CLOSED if row[0] and row[0] == row[1] else OPEN

    @staticmethod
    def _balances(
        connection: Connection, prop: UUID, day: date
    ) -> list[tuple[str, str, str, str | None, int, int]]:
        return [
            (str(code), str(name), str(kind), section, int(debit), int(credit))
            for code, name, kind, section, debit, credit in connection.execute(
                "SELECT balance.code, balance.name_en, balance.account_type, account.bs_section, "
                "balance.debit_cents, balance.credit_cents "
                "FROM app.gl_account_balances(%s, %s) AS balance "
                "JOIN app.gl_accounts AS account ON account.id = balance.account_id",
                (prop, day),
            ).fetchall()
        ]

    @staticmethod
    def _riel(connection: Connection, prop: UUID, day: date) -> dict[str, int]:
        """The riel each riel account held on the day: riel cash is its last count on or before
        the day plus the riel lines after it; the riel bank is the sum of its riel lines."""
        return {
            str(code): int(riel)
            for code, riel in connection.execute(RIEL_HELD_ON, {"prop": prop, "day": day})
        }

    @staticmethod
    def _natural(connection: Connection, prop: UUID, day: date, codes: Sequence[str]) -> int:
        row = connection.execute(
            "SELECT coalesce(sum(balance_cents), 0) FROM app.gl_account_balances(%s, %s) "
            "WHERE code = ANY(%s)",
            (prop, day, list(codes)),
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _cash(connection: Connection, prop: UUID, day: date) -> int:
        row = connection.execute(
            "SELECT coalesce(sum(balance.debit_cents - balance.credit_cents), 0) "
            "FROM app.gl_account_balances(%s, %s) AS balance "
            "JOIN app.gl_accounts AS account ON account.id = balance.account_id "
            "WHERE account.cash_kind IS NOT NULL",
            (prop, day),
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _year(connection: Connection, prop: UUID, day: date) -> tuple[UUID | None, date, str]:
        row = connection.execute(
            "SELECT id, starts_on, status FROM app.gl_fiscal_years "
            "WHERE property_id = %s AND starts_on <= %s AND ends_on >= %s",
            (prop, day, day),
        ).fetchone()
        if row is None:
            return None, date(day.year, 1, 1), "OPEN"
        return row[0], row[1], str(row[2])

    @staticmethod
    def _p_and_l(
        connection: Connection, prop: UUID, start: date, end: date
    ) -> list[tuple[str, str, str, int]]:
        return [
            (str(section), str(code), str(name), int(amount))
            for section, code, name, amount in connection.execute(
                "SELECT section, code, name_en, amount_cents "
                "FROM app.gl_profit_and_loss(%s, %s, %s)",
                (prop, start, end),
            ).fetchall()
        ]

    def _profit_and_loss(self, connection: Connection, prop: UUID, day: date) -> LedgerReport:
        first, last = month_start(day), month_end(day)
        year_id, year_start, year_status = self._year(connection, prop, first)
        before, last_year = months_back(first, 1), months_back(first, 12)
        amounts = {
            "this_month": self._p_and_l(connection, prop, first, last),
            "last_month": self._p_and_l(connection, prop, before, month_end(before)),
            "same_month_last_year": self._p_and_l(
                connection, prop, last_year, month_end(last_year)
            ),
            "year_to_date": self._p_and_l(connection, prop, year_start, last),
        }
        book_profit = None
        if year_id is None or year_status != "CLOSED":
            book_profit = balance_sheet(
                self._balances(connection, prop, last), period="", state=""
            ).extra["profit_this_year_cents"]
        return profit_and_loss(
            amounts,
            book_profit=book_profit,
            period=f"{first.strftime('%B %Y')} ({_day(first)} to {_day(last)})",
            state=self._state(connection, prop, first, last),
        )

    def _account_detail(
        self, connection: Connection, prop: UUID, params: ReportParams, today: date
    ) -> LedgerReport:
        found = connection.execute(
            "SELECT id, code, name_en FROM app.gl_accounts WHERE property_id = %s AND code = %s",
            (prop, params.account),
        ).fetchone()
        if found is None:
            raise LedgerMoneyNotFound
        start, end = self._range(params, today)
        lines = connection.execute(
            "SELECT entry_number, entry_date, description, memo, debit_cents, credit_cents, "
            "running_balance_cents FROM app.gl_ledger_detail(%s, %s, %s)",
            (found[0], start, end),
        ).fetchall()
        return account_detail(
            str(found[1]),
            str(found[2]),
            [
                (number, day, text, memo, int(debit), int(credit), int(balance))
                for number, day, text, memo, debit, credit, balance in lines
            ],
            self._natural(connection, prop, end, (str(found[1]),)),
            period=f"{_day(start)} to {_day(end)}",
            state=self._state(connection, prop, start, end),
        )

    def _budget(self, connection: Connection, prop: UUID, actor: UUID, day: date) -> LedgerReport:
        first, last = month_start(day), month_end(day)
        year_id, year_start, _ = self._year(connection, prop, first)
        month_no = (first.year - year_start.year) * 12 + first.month - year_start.month + 1
        warning = connection.execute(
            "SELECT percent_hundredths, smallest_cents FROM app.gl_budget_warning(%s, %s, %s)",
            (prop, actor, last),
        ).fetchone()
        percent, smallest = (int(warning[0] or 0), int(warning[1] or 0)) if warning else (0, 0)
        version: int | None = None
        lines: list[tuple[str, str, int, int]] = []
        if year_id is not None:
            budget = connection.execute(
                "SELECT id, version FROM app.gl_budgets WHERE fiscal_year_id = %s "
                "AND status = 'APPROVED' ORDER BY version DESC LIMIT 1",
                (year_id,),
            ).fetchone()
            if budget is not None:
                version = int(budget[1])
                lines = [
                    (str(code), str(name), int(number), int(cents))
                    for code, name, number, cents in connection.execute(
                        "SELECT account.code, account.name_en, line.month_no, line.amount_cents "
                        "FROM app.gl_budget_lines AS line "
                        "JOIN app.gl_accounts AS account ON account.id = line.account_id "
                        "WHERE line.budget_id = %s",
                        (budget[0],),
                    ).fetchall()
                ]
        month = self._p_and_l(connection, prop, first, last)
        year = self._p_and_l(connection, prop, year_start, last)
        names = {code: name for _, code, name, _ in (*month, *year)}
        return budget_against_actual(
            lines,
            {code: amount for _, code, _, amount in month},
            {code: amount for _, code, _, amount in year},
            names,
            month_no=month_no,
            percent_hundredths=percent,
            smallest=smallest,
            approved_version=version,
            period=f"{first.strftime('%B %Y')} and the year to date",
            state=self._state(connection, prop, first, last),
        )


class UnavailableLedgerReports:
    def report(self, *_: object, **__: object) -> LedgerReport:
        raise LedgerMoneyUnavailable
