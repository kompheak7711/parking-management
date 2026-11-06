"""Month-end close read for the ledger screen (General Ledger phase 6 step 6, part 4).

Owner decisions: DESIGN.md round 22 (Month-end close checks itself and works only when every line
is green; months close in order and only after their last day; the Owner closes the year after
December) and gaps G2 and G7 (the Books check, riel valued at the month-end rate).

- `GET /api/v1/properties/{property_id}/ledger/month-end?month=` (`ledger.read`) answers the
  months of the ledger up to today with who closed each, the years with the entry and profit of
  their close, and for one month (`month`, any day of it; default the earliest open month that
  has ended): each close check with what is still open, the month's depreciation entry and its
  riel valuation, and for each riel account (1011 riel cash, 1021 riel bank) the riel held at the
  month end, the rate, the dollar value before and after and the gain or loss to 4100 (owner
  05/11/2026: month end shows the riel).

Read-only and `private, no-store`. Closing is the checked database functions behind the close
API (`POST .../ledger/periods/{period_id}/close` and `.../fiscal-years/{year_id}/close`).
"""

from __future__ import annotations

from datetime import date
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

MONTHS: Final = """
    SELECT period.id, period.starts_on, period.ends_on, period.status, year.fiscal_year,
        person.display_name, period.closed_at
    FROM app.gl_periods AS period
    JOIN app.gl_fiscal_years AS year ON year.id = period.fiscal_year_id
    LEFT JOIN app.user_accounts AS person ON person.actor_id = period.closed_by
    WHERE period.property_id = %(prop)s AND period.period_no <= 12
      AND period.starts_on <= %(today)s
    ORDER BY period.starts_on DESC
    LIMIT 60
"""
YEARS: Final = """
    SELECT year.id, year.fiscal_year, year.status, entry.entry_number,
        (SELECT coalesce(sum(line.credit_cents - line.debit_cents), 0)
         FROM app.gl_journal_lines AS line
         JOIN app.gl_accounts AS account ON account.id = line.account_id
         WHERE line.entry_id = entry.id AND account.code = '3900'),
        EXISTS (SELECT 1 FROM app.gl_periods AS period
                WHERE period.fiscal_year_id = year.id AND period.period_no = 12
                  AND period.status = 'CLOSED')
    FROM app.gl_fiscal_years AS year
    LEFT JOIN app.gl_journal_entries AS entry
        ON entry.posting_key = 'fiscal_year:' || year.id || ':close'
    WHERE year.property_id = %(prop)s
    ORDER BY year.fiscal_year DESC
"""
CHECKS: Final = """
    SELECT item.check_code, item.ok, item.open_items
    FROM app.gl_month_close_checks(%(period)s) AS item
"""
DEPRECIATION: Final = """
    SELECT entry.entry_number
    FROM app.gl_journal_entries AS entry
    WHERE entry.property_id = %(prop)s AND entry.period_id = %(period)s
      AND entry.entry_kind = 'DEPRECIATION'
    ORDER BY entry.posted_at DESC
    LIMIT 1
"""
RIEL: Final = """
    SELECT entry.entry_number
    FROM app.gl_fx_revaluations AS valuation
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = valuation.entry_id
    WHERE valuation.property_id = %(prop)s AND valuation.period_id = %(period)s
    ORDER BY valuation.created_at DESC
    LIMIT 1
"""

# Each riel account's latest valuation in the month (owner 05/11/2026).
RIEL_ACCOUNTS: Final = """
    SELECT DISTINCT ON (account.code) account.code, account.name_en, account.name_km,
        account.cash_kind, valuation.riel_held_minor, rate.system_rate_khr_per_usd,
        valuation.book_usd_cents, valuation.new_usd_cents, entry.entry_number
    FROM app.gl_fx_revaluations AS valuation
    JOIN app.gl_accounts AS account ON account.id = valuation.account_id
    JOIN app.exchange_rate_records AS rate ON rate.id = valuation.exchange_rate_record_id
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = valuation.entry_id
    WHERE valuation.property_id = %(prop)s AND valuation.period_id = %(period)s
    ORDER BY account.code, valuation.created_at DESC
"""


class LedgerMonthEndFlow(Protocol):
    def month_end(self, property_id: UUID, month: date | None) -> dict[str, Any]: ...


class UnavailableLedgerMonthEnd:
    def month_end(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


class PostgresLedgerMonthEnd:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def month_end(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._read(connection, property_id, month)
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

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
                "fiscal_year": r[4],
                "closed_by_name": r[5],
                "closed_at": None if r[6] is None else r[6].isoformat(),
            }
            for r in connection.execute(MONTHS, key)
        ]
        years = [
            {
                "id": str(r[0]),
                "fiscal_year": r[1],
                "status": r[2],
                "entry_number": r[3],
                "profit_cents": None if r[3] is None else int(r[4]),
                "december_closed": r[5],
            }
            for r in connection.execute(YEARS, key)
        ]
        chosen = None
        if month is not None:
            chosen = next(
                (m for m in months if m["starts_on"] <= month.isoformat() <= m["ends_on"]), None
            )
        if chosen is None:
            chosen = next(
                (
                    m
                    for m in reversed(months)
                    if m["status"] == "OPEN" and m["ends_on"] < today.isoformat()
                ),
                None,
            )
        answer: dict[str, Any] = {
            "today": today.isoformat(),
            "months": months,
            "years": years,
            "month": chosen,
            "checks": [],
            "depreciation_entry": None,
            "riel": None,
            "riel_accounts": [],
        }
        if chosen is None:
            return answer
        place = {"prop": property_id, "period": UUID(str(chosen["id"]))}
        answer["checks"] = [
            {"code": r[0], "ok": bool(r[1]), "open_items": int(r[2] or 0)}
            for r in connection.execute(CHECKS, place)
        ]
        depreciation = connection.execute(DEPRECIATION, place).fetchone()
        answer["depreciation_entry"] = None if depreciation is None else depreciation[0]
        riel = connection.execute(RIEL, place).fetchone()
        answer["riel"] = None if riel is None else {"entry_number": riel[0]}
        answer["riel_accounts"] = [
            {
                "code": r[0],
                "name_en": r[1],
                "name_km": r[2],
                "cash_kind": r[3],
                "riel_held": int(r[4]),
                "khr_per_usd": int(r[5]),
                "before_cents": int(r[6]),
                "after_cents": int(r[7]),
                "gain_cents": int(r[7]) - int(r[6]),
                "entry_number": r[8],
            }
            for r in connection.execute(RIEL_ACCOUNTS, place)
        ]
        return answer


def create_ledger_month_end_router(resolver: ActorResolver, flow: LedgerMonthEndFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/month-end")
    def read_month_end(
        property_id: UUID, request: Request, response: Response, month: date | None = None
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if set(request.query_params) - {"month"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            data = flow.month_end(property_id, month)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    return router
