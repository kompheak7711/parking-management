"""Spending reads for the ledger screens (General Ledger phase 6 step 6, part 2).

Owner expense flow of 02/11/2026 and the phase 6 rights (DL-117): every role sends Expense
requests and reports (`expenses.request`); the Accountant, a Manager and the Owner approve and
pay (`expenses.approve`, `expenses.record`). A Staff member sees only their own requests.

- `GET /api/v1/properties/{property_id}/expense-requests/form` answers what the request and
  expense forms need: the Expense limit, the Asset limit, the report days and the pay-later days
  (business rules for today), today's riel rate record, the accounts a request or an expense may
  use, the money accounts it may be paid from, the suppliers and the Units.
- `GET /api/v1/properties/{property_id}/expense-requests/{request_number}` answers one request
  with its steps (who did what and when), the advance, the expenses its bill made and the money
  paid back to staff, each with its journal entry number.

Both are read-only and `private, no-store`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Path, Request, Response, status

from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import (
    EXPENSES_APPROVE,
    EXPENSES_RECORD,
    EXPENSES_REQUEST,
    FLOW_ERRORS,
    REQUESTS_QUERY,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    _holds,
    _http,
    _require,
)

# Accounts a request or an expense may be for: every active expense account a person spends on
# (not salaries, depreciation, write-offs, stock losses or cash short, which the app posts), and the
# asset accounts for stock, prepaid costs and equipment.
SPEND_ACCOUNTS: Final = """
    SELECT account.code, account.name_en, account.name_km, account.account_type
    FROM app.gl_accounts AS account
    WHERE account.property_id = %(prop)s AND account.is_active AND account.is_postable
      AND ((account.account_type = 'EXPENSE'
            AND account.code NOT IN ('6030', '6040', '6140', '6160', '6170', '6180'))
           OR account.code IN ('1200', '1510', '1520', '1530'))
    ORDER BY account.code
"""
MONEY_ACCOUNTS: Final = """
    SELECT account.code, account.name_en, account.name_km, account.account_type
    FROM app.gl_accounts AS account
    WHERE account.property_id = %(prop)s AND account.is_active AND account.is_postable
      AND account.cash_kind IS NOT NULL
    ORDER BY account.code
"""
RULES: Final = """
    SELECT app.business_rule_value('EXPENSE_LIMIT', %(today)s),
           app.business_rule_value('ASSET_LIMIT', %(today)s),
           app.business_rule_value('EXP_REPORT_DAYS', %(today)s),
           app.business_rule_value('SUPPLIER_BILL_DAYS', %(today)s)
"""
RATE: Final = """
    SELECT rate.id, rate.system_rate_khr_per_usd
    FROM app.list_exchange_rates_for_property(%(prop)s, 101, NULL, NULL) AS rate
    WHERE rate.applicable_at <= now()
    ORDER BY rate.applicable_at DESC
    LIMIT 1
"""
SUPPLIERS: Final = """
    SELECT supplier.id, supplier.name FROM app.gl_suppliers AS supplier
    WHERE supplier.property_id = %(prop)s AND supplier.is_active
    ORDER BY supplier.name, supplier.id
"""
UNITS: Final = """
    SELECT unit.id, unit.unit_number FROM app.units AS unit
    WHERE unit.property_id = %(prop)s
    ORDER BY unit.unit_number, unit.id
"""
STEPS: Final = """
    SELECT event.step, event.note, event.occurred_at, person.display_name
    FROM app.gl_expense_request_events AS event
    LEFT JOIN app.user_accounts AS person ON person.actor_id = event.actor_id
    WHERE event.expense_request_id = %(id)s
    ORDER BY event.occurred_at, event.id
"""
EXPENSES: Final = """
    SELECT expense.expense_number, expense.expense_date, expense.amount_cents,
        expense.bill_number, expense.status, entry.entry_number, person.display_name
    FROM app.gl_expenses AS expense
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = expense.entry_id
    LEFT JOIN app.user_accounts AS person ON person.actor_id = expense.created_by
    WHERE expense.expense_request_id = %(id)s
    ORDER BY expense.created_at, expense.id
"""
PAYBACKS: Final = """
    SELECT payback.paid_on, payback.amount_cents, account.code, entry.entry_number,
        person.display_name
    FROM app.gl_staff_paybacks AS payback
    JOIN app.gl_accounts AS account ON account.id = payback.from_account_id
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = payback.entry_id
    LEFT JOIN app.user_accounts AS person ON person.actor_id = payback.created_by
    WHERE payback.expense_request_id = %(id)s
    ORDER BY payback.created_at, payback.id
"""
ADVANCE: Final = """
    SELECT line.debit_cents, entry.entry_date, entry.entry_number, person.display_name,
        (SELECT money.code FROM app.gl_journal_lines AS credit
         JOIN app.gl_accounts AS money ON money.id = credit.account_id
         WHERE credit.entry_id = entry.id AND credit.credit_cents > 0
         ORDER BY credit.line_no LIMIT 1)
    FROM app.gl_expense_requests AS request
    JOIN app.gl_journal_entries AS entry ON entry.id = request.paid_out_entry_id
    JOIN app.gl_journal_lines AS line ON line.entry_id = entry.id
    JOIN app.gl_accounts AS advance ON advance.id = line.account_id AND advance.code = '1400'
    LEFT JOIN app.user_accounts AS person ON person.actor_id = entry.posted_by
    WHERE request.id = %(id)s AND line.debit_cents > 0
    LIMIT 1
"""


class LedgerSpendingFlow(Protocol):
    def form(self, property_id: UUID) -> dict[str, Any]: ...

    def request(
        self, property_id: UUID, request_number: str, requested_by: str | None
    ) -> dict[str, Any]: ...


class UnavailableLedgerSpending:
    def form(self, property_id: UUID) -> dict[str, Any]:
        raise LedgerMoneyUnavailable

    def request(
        self, property_id: UUID, request_number: str, requested_by: str | None
    ) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


def _plain(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _account(row: tuple[Any, ...]) -> dict[str, Any]:
    return {"code": row[0], "name_en": row[1], "name_km": row[2], "account_type": row[3]}


class PostgresLedgerSpending:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _today(self, connection: psycopg.Connection[Any], property_id: UUID) -> date:
        row = connection.execute(
            "SELECT timezone(property.timezone_name, now())::date FROM app.properties AS property"
            " WHERE property.id = %(prop)s",
            {"prop": property_id},
        ).fetchone()
        if row is None:
            raise LedgerMoneyNotFound
        today: date = row[0]
        return today

    def form(self, property_id: UUID) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                today = self._today(connection, property_id)
                key = {"prop": property_id, "today": today}
                rules = connection.execute(RULES, key).fetchone() or (None, None, None, None)
                rate = connection.execute(RATE, key).fetchone()
                return {
                    "today": today.isoformat(),
                    "expense_limit_cents": rules[0],
                    "asset_limit_cents": rules[1],
                    "report_days": rules[2] if rules[2] is not None else 3,
                    "bill_days": rules[3] if rules[3] is not None else 30,
                    "rate": None
                    if rate is None
                    else {"id": str(rate[0]), "khr_per_usd": int(rate[1])},
                    "accounts": [_account(row) for row in connection.execute(SPEND_ACCOUNTS, key)],
                    "money_accounts": [
                        _account(row) for row in connection.execute(MONEY_ACCOUNTS, key)
                    ],
                    "suppliers": [
                        {"id": str(row[0]), "name": row[1]}
                        for row in connection.execute(SUPPLIERS, key)
                    ],
                    "units": [
                        {"id": str(row[0]), "unit_number": row[1]}
                        for row in connection.execute(UNITS, key)
                    ],
                }
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

    def request(
        self, property_id: UUID, request_number: str, requested_by: str | None
    ) -> dict[str, Any]:
        query = REQUESTS_QUERY.replace(
            "ORDER BY request.created_at",
            "AND request.request_number = %(number)s ORDER BY request.created_at",
        )
        try:
            with psycopg.connect(self._database_url) as connection:
                self._today(connection, property_id)
                cursor = connection.execute(
                    query,
                    {
                        "prop": property_id,
                        "mine": None if requested_by is None else UUID(requested_by),
                        "number": request_number,
                    },
                )
                names = [column.name for column in cursor.description or ()]
                row = cursor.fetchone()
                if row is None:
                    raise LedgerMoneyNotFound
                found = {name: _plain(value) for name, value in zip(names, row, strict=True)}
                key = {"id": UUID(str(found["id"]))}
                found["steps"] = [
                    {"step": r[0], "note": r[1], "at": _plain(r[2]), "by_name": r[3]}
                    for r in connection.execute(STEPS, key)
                ]
                advance = connection.execute(ADVANCE, key).fetchone()
                found["advance"] = (
                    None
                    if advance is None
                    else {
                        "amount_cents": advance[0],
                        "paid_on": _plain(advance[1]),
                        "entry_number": advance[2],
                        "by_name": advance[3],
                        "from_code": advance[4],
                    }
                )
                found["expenses"] = [
                    {
                        "expense_number": r[0],
                        "expense_date": _plain(r[1]),
                        "amount_cents": r[2],
                        "bill_number": r[3],
                        "status": r[4],
                        "entry_number": r[5],
                        "by_name": r[6],
                    }
                    for r in connection.execute(EXPENSES, key)
                ]
                found["paybacks"] = [
                    {
                        "paid_on": _plain(r[0]),
                        "amount_cents": r[1],
                        "from_code": r[2],
                        "entry_number": r[3],
                        "by_name": r[4],
                    }
                    for r in connection.execute(PAYBACKS, key)
                ]
                return found
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc


def create_ledger_spending_router(resolver: ActorResolver, flow: LedgerSpendingFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["ledger"])

    def answer(request: Request, response: Response, data: dict[str, Any]) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def no_query(request: Request) -> None:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    @router.get("/expense-requests/form")
    def read_spending_form(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, EXPENSES_REQUEST, property_id)
        no_query(request)
        try:
            return answer(request, response, flow.form(property_id))
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc

    @router.get("/expense-requests/{request_number}")
    def read_expense_request(
        property_id: UUID,
        request_number: Annotated[str, Path(pattern=r"^[A-Z]{2,5}[0-9]{6,9}$")],
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require(request, resolver, EXPENSES_REQUEST, property_id)
        no_query(request)
        sees_all = _holds(actor, EXPENSES_APPROVE, property_id) or _holds(
            actor, EXPENSES_RECORD, property_id
        )
        try:
            found = flow.request(property_id, request_number, None if sees_all else actor.actor_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return answer(request, response, found)

    return router
