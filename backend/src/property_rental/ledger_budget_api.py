"""Budget read for the ledger screen (General Ledger phase 6 step 6, part 4).

Owner decisions: DESIGN.md round 22 (the Accountant prepares the budget by month for the year;
the Owner approves it; nobody approves their own; the Owner's own budget is approved at once
with a note) and PR-GL-054.

- `GET /api/v1/properties/{property_id}/ledger/budget-sheet?year=` (`ledger.read`) answers the
  years of the ledger, the chosen year (default the year of today, else the latest), the income,
  cost and expense accounts a budget can use, the year's budgets newest first with who sent,
  approved or sent back each and their lines, and the approved lines of the year before as a
  start for a new budget.

Read-only and `private, no-store`. Sending is `POST .../ledger/budgets` (`ledger.budgets.prepare`)
and the decision `POST .../ledger/budgets/{budget_id}/decision` (`ledger.budgets.approve`).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import (
    FLOW_ERRORS,
    LEDGER_READ,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    _http,
    _require,
)

YEARS: Final = """
    SELECT year.fiscal_year, year.status
    FROM app.gl_fiscal_years AS year
    WHERE year.property_id = %(prop)s
    ORDER BY year.fiscal_year
"""
ACCOUNTS: Final = """
    SELECT account.code, account.name_en, account.name_km, account.account_type
    FROM app.gl_accounts AS account
    WHERE account.property_id = %(prop)s AND account.is_postable AND account.is_active
      AND account.account_type IN ('INCOME', 'COST_OF_SALES', 'EXPENSE')
    ORDER BY account.code
"""
BUDGETS: Final = """
    SELECT budget.id, budget.version, budget.status, budget.created_by::text, sender.display_name,
        budget.created_at, approver.display_name, budget.approved_at, budget.decision_note,
        budget.own_budget_note,
        (SELECT coalesce(json_agg(json_build_object('account_code', account.code,
                'month_no', line.month_no, 'amount_cents', line.amount_cents)
                ORDER BY account.code, line.month_no), '[]'::json)
         FROM app.gl_budget_lines AS line
         JOIN app.gl_accounts AS account ON account.id = line.account_id
         WHERE line.budget_id = budget.id)
    FROM app.gl_budgets AS budget
    JOIN app.gl_fiscal_years AS year ON year.id = budget.fiscal_year_id
    LEFT JOIN app.user_accounts AS sender ON sender.actor_id = budget.created_by
    LEFT JOIN app.user_accounts AS approver ON approver.actor_id = budget.approved_by
    WHERE budget.property_id = %(prop)s AND year.fiscal_year = %(year)s
    ORDER BY budget.version DESC
    LIMIT 20
"""
EARLIER: Final = """
    SELECT account.code, line.month_no, line.amount_cents
    FROM app.gl_budgets AS budget
    JOIN app.gl_fiscal_years AS year ON year.id = budget.fiscal_year_id
    JOIN app.gl_budget_lines AS line ON line.budget_id = budget.id
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE budget.property_id = %(prop)s AND year.fiscal_year = %(year)s - 1
      AND budget.status = 'APPROVED'
    ORDER BY account.code, line.month_no
"""


class LedgerBudgetFlow(Protocol):
    def sheet(self, property_id: UUID, year: int | None) -> dict[str, Any]: ...


class UnavailableLedgerBudget:
    def sheet(self, property_id: UUID, year: int | None) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


def _moment(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


class PostgresLedgerBudget:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def sheet(self, property_id: UUID, year: int | None) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._read(connection, property_id, year)
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

    def _read(
        self, connection: psycopg.Connection[Any], property_id: UUID, year: int | None
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT timezone(property.timezone_name, now())::date FROM app.properties AS property"
            " WHERE property.id = %(prop)s",
            {"prop": property_id},
        ).fetchone()
        if row is None:
            raise LedgerMoneyNotFound
        today: date = row[0]
        years = [
            {"fiscal_year": int(r[0]), "status": r[1]}
            for r in connection.execute(YEARS, {"prop": property_id})
        ]
        known = [item["fiscal_year"] for item in years]
        chosen = (
            year
            if year in known
            else today.year
            if today.year in known
            else (known[-1] if known else None)
        )
        answer: dict[str, Any] = {
            "today": today.isoformat(),
            "years": years,
            "year": chosen,
            "accounts": [
                {"code": r[0], "name_en": r[1], "name_km": r[2], "account_type": r[3]}
                for r in connection.execute(ACCOUNTS, {"prop": property_id})
            ],
            "budgets": [],
            "earlier_lines": [],
        }
        if chosen is None:
            return answer
        key = {"prop": property_id, "year": chosen}
        answer["budgets"] = [
            {
                "id": str(r[0]),
                "version": int(r[1]),
                "status": r[2],
                "created_by": r[3],
                "created_by_name": r[4],
                "created_at": _moment(r[5]),
                "approved_by_name": r[6],
                "approved_at": _moment(r[7]),
                "decision_note": r[8],
                "own_note": r[9],
                "lines": [
                    {
                        "account_code": str(line["account_code"]),
                        "month_no": int(line["month_no"]),
                        "amount_cents": int(line["amount_cents"]),
                    }
                    for line in (r[10] or [])
                ],
            }
            for r in connection.execute(BUDGETS, key)
        ]
        answer["earlier_lines"] = [
            {"account_code": r[0], "month_no": int(r[1]), "amount_cents": int(r[2])}
            for r in connection.execute(EARLIER, key)
        ]
        return answer


def create_ledger_budget_router(resolver: ActorResolver, flow: LedgerBudgetFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/budget-sheet")
    def read_budget_sheet(
        property_id: UUID,
        request: Request,
        response: Response,
        year: Annotated[int | None, Query(ge=2000, le=2099)] = None,
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if set(request.query_params) - {"year"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            data = flow.sheet(property_id, year)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    return router
