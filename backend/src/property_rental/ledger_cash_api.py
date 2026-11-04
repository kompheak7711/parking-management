"""Bank and cash read for the ledger screen (General Ledger phase 6 step 6, part 3).

Owner decisions: DESIGN.md round 22 (match the bank book to the ABA statement and count the cash
at each month end; month-end close checks both), gaps G3 to G5 (Move money, Owner money, Top up
petty cash) and G7 (riel valued at the month-end rate).

- `GET /api/v1/properties/{property_id}/ledger/bank-cash?month=` (`ledger.read`) answers the
  months that have ended, the petty cash float (Petty cash business rule) with what petty cash
  holds and the requests paid from it whose bill is not recorded yet, the riel held with its
  value in the books and the last month-end valuation, and for one month (`month`, any day of
  it; default the earliest ended month not yet matched and counted): each bank account's book
  balance, its lines not yet matched and the match already made, and each cash account's book
  balance and the count already made. It also answers today's riel rate record.
- `GET /api/v1/properties/{property_id}/ledger/money-entries/{kind}/{record_id}` (`ledger.read`)
  answers the journal entry number of one Move money, Owner money or Top up petty cash record, so
  the screen can say which entry the save made.

Read-only and `private, no-store`. The changes are the checked database functions behind the
money and close APIs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status

from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import (
    FLOW_ERRORS,
    LEDGER_READ,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    _http,
    _require,
)
from property_rental.ledger_spending_api import RATE

MONTHS: Final = """
    SELECT period.id, period.starts_on, period.ends_on, period.status,
        EXISTS (SELECT 1 FROM app.gl_bank_reconciliations AS match
                JOIN app.gl_accounts AS bank ON bank.id = match.account_id
                WHERE match.period_id = period.id AND match.status = 'MATCHED'
                  AND bank.code = '1020') AS matched,
        EXISTS (SELECT 1 FROM app.gl_cash_counts AS counted
                WHERE counted.period_id = period.id) AS counted
    FROM app.gl_periods AS period
    WHERE period.property_id = %(prop)s AND period.period_no <= 12
      AND period.ends_on < %(today)s
    ORDER BY period.ends_on DESC
    LIMIT 36
"""
MONEY: Final = """
    SELECT account.id, account.code, account.name_en, account.name_km, account.cash_kind,
        balance.balance_cents
    FROM app.gl_accounts AS account
    JOIN app.gl_account_balances(%(prop)s, %(on)s) AS balance ON balance.account_id = account.id
    WHERE account.property_id = %(prop)s AND account.cash_kind IS NOT NULL AND account.is_active
    ORDER BY account.code
"""
PETTY_WAITING: Final = """
    SELECT request.request_number, request.amount_cents
    FROM app.gl_expense_requests AS request
    JOIN app.gl_accounts AS paid_from ON paid_from.id = request.paid_from_account_id
    WHERE request.property_id = %(prop)s AND request.status = 'APPROVED'
      AND paid_from.cash_kind = 'PETTY'
    ORDER BY request.created_at, request.request_number
"""
RIEL_HELD: Final = """
    WITH last_count AS (
        SELECT counted.counted_on, counted.counted_riel
        FROM app.gl_cash_counts AS counted
        WHERE counted.account_id = %(account)s AND counted.counted_riel IS NOT NULL
        ORDER BY counted.counted_on DESC, counted.created_at DESC
        LIMIT 1
    )
    SELECT coalesce((SELECT counted_riel FROM last_count), 0) + coalesce((
        SELECT sum(CASE WHEN line.debit_cents > 0 THEN line.original_amount_minor
                        ELSE -line.original_amount_minor END)
        FROM app.gl_journal_lines AS line
        JOIN app.gl_journal_entries AS entry ON entry.id = line.entry_id
        WHERE line.account_id = %(account)s AND line.original_currency = 'KHR'
          AND entry.entry_date > coalesce((SELECT counted_on FROM last_count), '-infinity')
          AND entry.entry_date <= %(today)s), 0)
"""
LAST_VALUATION: Final = """
    SELECT period.ends_on, entry.entry_number
    FROM app.gl_fx_revaluations AS valuation
    JOIN app.gl_periods AS period ON period.id = valuation.period_id
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = valuation.entry_id
    WHERE valuation.account_id = %(account)s
    ORDER BY period.ends_on DESC
    LIMIT 1
"""
BANK_LINES: Final = """
    SELECT line.line_id, line.entry_number, line.entry_date, line.description, line.memo,
        line.debit_cents, line.credit_cents
    FROM app.gl_bank_lines(%(prop)s, %(code)s, %(period)s) AS line
    ORDER BY line.entry_date, line.entry_number
"""
BANK_MATCH: Final = """
    SELECT match.statement_balance_cents, match.status, person.display_name,
        coalesce(match.matched_at, match.created_at),
        (SELECT count(*) FROM app.gl_bank_reconciliation_items AS item
         WHERE item.reconciliation_id = match.id)
    FROM app.gl_bank_reconciliations AS match
    LEFT JOIN app.user_accounts AS person
        ON person.actor_id = coalesce(match.matched_by, match.created_by)
    WHERE match.account_id = %(account)s AND match.period_id = %(period)s
"""
CASH_COUNT: Final = """
    SELECT counted.counted_on, counted.counted_minor, counted.book_minor, counted.counted_riel,
        counted.note, entry.entry_number, person.display_name, counted.created_at
    FROM app.gl_cash_counts AS counted
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = counted.difference_entry_id
    LEFT JOIN app.user_accounts AS person ON person.actor_id = counted.created_by
    WHERE counted.account_id = %(account)s AND counted.period_id = %(period)s
"""

SOURCE_TYPES: Final = {
    "money-move": "MONEY_MOVE",
    "owner-money": "OWNER_MONEY",
    "petty-cash-top-up": "PETTY_CASH_TOPUP",
}
SOURCE_ENTRY: Final = """
    SELECT entry.entry_number
    FROM app.gl_journal_entries AS entry
    WHERE entry.property_id = %(prop)s AND entry.source_type = %(kind)s
      AND entry.source_id = %(id)s
    ORDER BY entry.posted_at
    LIMIT 1
"""


class LedgerCashFlow(Protocol):
    def bank_cash(self, property_id: UUID, month: date | None) -> dict[str, Any]: ...

    def entry_of(self, property_id: UUID, kind: str, record_id: UUID) -> str: ...


class UnavailableLedgerCash:
    def bank_cash(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        raise LedgerMoneyUnavailable

    def entry_of(self, property_id: UUID, kind: str, record_id: UUID) -> str:
        raise LedgerMoneyUnavailable


def _plain(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


class PostgresLedgerCash:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def bank_cash(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._read(connection, property_id, month)
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

    def entry_of(self, property_id: UUID, kind: str, record_id: UUID) -> str:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    SOURCE_ENTRY,
                    {"prop": property_id, "kind": SOURCE_TYPES[kind], "id": record_id},
                ).fetchone()
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc
        if row is None:
            raise LedgerMoneyNotFound
        return str(row[0])

    def _read(
        self, connection: psycopg.Connection[Any], property_id: UUID, month: date | None
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT timezone(property.timezone_name, now())::date FROM app.properties AS property"
            " WHERE property.id = %(prop)s",
            {"prop": property_id},
        ).fetchone()
        if row is None:
            raise LedgerMoneyNotFound
        today: date = row[0]
        key: dict[str, Any] = {"prop": property_id, "today": today}
        months = [
            {
                "id": str(r[0]),
                "starts_on": r[1].isoformat(),
                "ends_on": r[2].isoformat(),
                "status": r[3],
                "matched": r[4],
                "counted": r[5],
            }
            for r in connection.execute(MONTHS, key)
        ]
        chosen = None
        if month is not None:
            chosen = next(
                (m for m in months if m["starts_on"] <= month.isoformat() <= m["ends_on"]), None
            )
        if chosen is None and months:
            chosen = next(
                (m for m in reversed(months) if not (m["matched"] and m["counted"])), months[0]
            )
        now = [*connection.execute(MONEY, {**key, "on": today})]
        petty = next((r for r in now if r[4] == "PETTY"), None)
        riel = next((r for r in now if r[4] == "CASH_KHR"), None)
        float_row = connection.execute(
            "SELECT app.business_rule_value('PETTY_CASH', %(today)s)", key
        ).fetchone()
        waiting = [
            {"request_number": r[0], "amount_cents": r[1]}
            for r in connection.execute(PETTY_WAITING, key)
        ]
        riel_part = None
        if riel is not None:
            held = connection.execute(RIEL_HELD, {**key, "account": riel[0]}).fetchone()
            last = connection.execute(LAST_VALUATION, {"account": riel[0]}).fetchone()
            riel_part = {
                "code": riel[1],
                "held_riel": int(held[0]) if held is not None else 0,
                "book_cents": riel[5],
                "last_month_end": None if last is None else last[0].isoformat(),
                "last_entry_number": None if last is None else last[1],
            }
        rate = connection.execute(RATE, key).fetchone()
        answer: dict[str, Any] = {
            "today": today.isoformat(),
            "months": months,
            "month": chosen,
            "rate": None if rate is None else {"id": str(rate[0]), "khr_per_usd": int(rate[1])},
            "petty": None
            if petty is None
            else {
                "code": petty[1],
                "float_cents": None if float_row is None else float_row[0],
                "balance_cents": petty[5],
                "waiting": waiting,
            },
            "riel": riel_part,
            "money_accounts": [
                {
                    "code": r[1],
                    "name_en": r[2],
                    "name_km": r[3],
                    "cash_kind": r[4],
                    "balance_cents": r[5],
                }
                for r in now
            ],
            "banks": [],
            "cash": [],
        }
        if chosen is None:
            return answer
        period = UUID(str(chosen["id"]))
        ends_on = date.fromisoformat(str(chosen["ends_on"]))
        for account in connection.execute(MONEY, {**key, "on": ends_on}).fetchall():
            place = {"account": account[0], "period": period}
            base = {
                "code": account[1],
                "name_en": account[2],
                "name_km": account[3],
                "cash_kind": account[4],
                "book_cents": account[5],
            }
            if account[4] == "BANK":
                match = connection.execute(BANK_MATCH, place).fetchone()
                lines = [
                    {
                        "line_id": str(r[0]),
                        "entry_number": r[1],
                        "entry_date": _plain(r[2]),
                        "description": r[3],
                        "memo": r[4],
                        "debit_cents": r[5],
                        "credit_cents": r[6],
                    }
                    for r in connection.execute(
                        BANK_LINES, {"prop": property_id, "code": account[1], "period": period}
                    )
                ]
                answer["banks"].append(
                    {
                        **base,
                        "lines": lines,
                        "match": None
                        if match is None
                        else {
                            "statement_balance_cents": match[0],
                            "status": match[1],
                            "by_name": match[2],
                            "at": _plain(match[3]),
                            "lines": match[4],
                        },
                    }
                )
            else:
                count = connection.execute(CASH_COUNT, place).fetchone()
                answer["cash"].append(
                    {
                        **base,
                        "count": None
                        if count is None
                        else {
                            "counted_on": _plain(count[0]),
                            "counted_cents": count[1],
                            "book_cents": count[2],
                            "counted_riel": count[3],
                            "note": count[4],
                            "entry_number": count[5],
                            "by_name": count[6],
                            "at": _plain(count[7]),
                        },
                    }
                )
        return answer


def create_ledger_cash_router(resolver: ActorResolver, flow: LedgerCashFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/bank-cash")
    def read_bank_cash(
        property_id: UUID, request: Request, response: Response, month: date | None = None
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if set(request.query_params) - {"month"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            data = flow.bank_cash(property_id, month)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    @router.get("/money-entries/{kind}/{record_id}")
    def read_money_entry(
        property_id: UUID, kind: str, record_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if kind not in SOURCE_TYPES or request.query_params:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            number = flow.entry_of(property_id, kind, record_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {
            "data": {"entry_number": number},
            "meta": {"request_id": request.state.request_id},
        }

    return router
