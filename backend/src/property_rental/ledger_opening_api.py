"""Opening balances read for the ledger screen (General Ledger phase 6 step 6, mock-up lopen).

Owner decisions: DESIGN.md round 22 (Opening balances from the Chart of accounts; fixed once
posted; a later fix is an adjusting entry), the phase 6 plan L3 (posting starts on 1 January
2027; opening balances are as at 31 December 2026) and DL-117 step 4 part 1 (the Owner types the
accounts that are not control accounts; the app works out Customer debt, Deposits, Customer
Credit, money not used yet and Rent billed in advance from its own lists).

- `GET /api/v1/properties/{property_id}/ledger/opening-sheet` (`ledger.read`) answers today, the
  ledger's first year, the opening balances (day, status, who posted and when, the entry), the
  accounts the Owner may type, the typed lines with their notes, the control-account lines the
  app works out now, the posted entry's lines, and how many records wait in Needs check (posting
  is refused until that list is clear).

Read-only and `private, no-store`. Starting the books, typing the lines and posting them are
`POST .../ledger/opening-balances`, `PUT .../ledger/opening-balances/lines` and
`POST .../ledger/opening-balances/post` (`ledger.opening_balances`).
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

FIRST_YEAR: Final = """
    SELECT min(year.fiscal_year) FROM app.gl_fiscal_years AS year
    WHERE year.property_id = %(prop)s
"""
OPENING: Final = """
    SELECT opening.id, opening.start_date, opening.status, entry.entry_number,
        poster.display_name, opening.posted_at, opening.entry_id
    FROM app.gl_opening_balances AS opening
    LEFT JOIN app.gl_journal_entries AS entry ON entry.id = opening.entry_id
    LEFT JOIN app.user_accounts AS poster ON poster.actor_id = opening.posted_by
    WHERE opening.property_id = %(prop)s
"""
# The accounts the Owner types: postable, in use, not a control account and not tax-locked.
# The riel bank account keeps riel on every line, which a typed line has not (migration 320).
ACCOUNTS: Final = """
    SELECT account.code, account.name_en, account.name_km, account.account_type,
        account.normal_side
    FROM app.gl_accounts AS account
    WHERE account.property_id = %(prop)s AND account.is_postable AND account.is_active
      AND account.control_source IS NULL AND NOT account.is_tax_locked
      AND account.cash_kind IS DISTINCT FROM 'BANK_KHR'
    ORDER BY account.code
"""
TYPED: Final = """
    SELECT account.code, account.name_en, account.name_km, line.debit_cents, line.credit_cents,
        line.memo
    FROM app.gl_opening_balance_lines AS line
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE line.opening_balance_id = %(opening)s
    ORDER BY account.code
"""
WORKED_OUT: Final = """
    SELECT preview.code, account.name_en, account.name_km, preview.debit_cents,
        preview.credit_cents
    FROM app.gl_opening_preview(%(prop)s) AS preview
    JOIN app.gl_accounts AS account ON account.property_id = %(prop)s
        AND account.code = preview.code
    WHERE preview.worked_out
    ORDER BY preview.code
"""
POSTED: Final = """
    SELECT account.code, account.name_en, account.name_km, line.debit_cents, line.credit_cents,
        line.memo
    FROM app.gl_journal_lines AS line
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE line.entry_id = %(entry)s
    ORDER BY line.line_no
"""
# The same records `app.gl_post_opening_balances` refuses for: the kept Needs check list and the
# app records with a problem the posting job has not met yet (migration 20270427_277).
NEEDS_CHECK: Final = """
    SELECT count(*) FROM app.gl_waiting_records(%(prop)s)
"""


class LedgerOpeningFlow(Protocol):
    def sheet(self, property_id: UUID) -> dict[str, Any]: ...


class UnavailableLedgerOpening:
    def sheet(self, property_id: UUID) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


def _line(row: Any, memo: bool) -> dict[str, Any]:
    line: dict[str, Any] = {
        "account_code": str(row[0]),
        "account_name": row[1],
        "account_name_km": row[2],
        "debit_cents": int(row[3]),
        "credit_cents": int(row[4]),
    }
    if memo:
        line["memo"] = row[5]
    return line


class PostgresLedgerOpening:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def sheet(self, property_id: UUID) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                return self._read(connection, property_id)
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

    def _read(self, connection: psycopg.Connection[Any], property_id: UUID) -> dict[str, Any]:
        row = connection.execute(
            "SELECT timezone(property.timezone_name, now())::date FROM app.properties AS property"
            " WHERE property.id = %(prop)s",
            {"prop": property_id},
        ).fetchone()
        if row is None:
            raise LedgerMoneyNotFound
        today: date = row[0]
        key: dict[str, Any] = {"prop": property_id}
        first = connection.execute(FIRST_YEAR, key).fetchone()
        waiting = connection.execute(NEEDS_CHECK, key).fetchone()
        answer: dict[str, Any] = {
            "today": today.isoformat(),
            "first_year": None if first is None or first[0] is None else int(first[0]),
            "opening": None,
            "accounts": [
                {
                    "code": r[0],
                    "name_en": r[1],
                    "name_km": r[2],
                    "account_type": r[3],
                    "normal_side": r[4],
                }
                for r in connection.execute(ACCOUNTS, key)
            ],
            "typed": [],
            "worked_out": [],
            "posted": [],
            "needs_check": 0 if waiting is None else int(waiting[0]),
        }
        opening = connection.execute(OPENING, key).fetchone()
        if opening is None:
            return answer
        answer["opening"] = {
            "id": str(opening[0]),
            "start_date": opening[1].isoformat(),
            "status": opening[2],
            "entry_number": opening[3],
            "posted_by_name": opening[4],
            "posted_at": None if opening[5] is None else opening[5].isoformat(),
        }
        if opening[2] == "POSTED":
            answer["posted"] = [
                _line(r, True) for r in connection.execute(POSTED, {"entry": opening[6]})
            ]
            return answer
        answer["typed"] = [
            _line(r, True) for r in connection.execute(TYPED, {"opening": opening[0]})
        ]
        answer["worked_out"] = [_line(r, False) for r in connection.execute(WORKED_OUT, key)]
        return answer


def create_ledger_opening_router(resolver: ActorResolver, flow: LedgerOpeningFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/opening-sheet")
    def read_opening_sheet(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            data = flow.sheet(property_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    return router
