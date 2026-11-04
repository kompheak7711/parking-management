"""Fixed asset register read for the ledger screen (General Ledger phase 6 step 6, part 4).

Owner decisions: DESIGN.md round 22 (items of the Asset limit or more are fixed assets; the app
makes the depreciation entry at the end of each month) and the 03/11/2026 10:26 answer (years
per account in Business rules, the same amount each month, the last month takes the cents left).

- `GET /api/v1/properties/{property_id}/ledger/asset-register` (`ledger.read`) answers each fixed
  asset with its item, account, Unit, cost, day bought, years, each month, depreciation so far
  and value now, the Expense and request it came from, the balance of 1590 Accumulated
  depreciation, today's Asset limit and years for each asset account, and the last depreciation
  entry.

Read-only and `private, no-store`. Adding an item is recording an Expense on an asset account;
changing its years is `POST .../ledger/fixed-assets/{asset_id}/life`.
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

REGISTER: Final = """
    SELECT asset.id, asset.asset_number, asset.item, asset.account_code, account.name_en,
        account.name_km, unit.unit_number, asset.cost_cents, asset.bought_on,
        asset.useful_life_years, asset.status, asset.monthly_cents, asset.depreciation_cents,
        asset.value_cents, expense.expense_number, request.request_number, fixed.expense_id
    FROM app.gl_asset_values(%(prop)s) AS asset
    JOIN app.gl_accounts AS account
        ON account.property_id = %(prop)s AND account.code = asset.account_code
    JOIN app.gl_fixed_assets AS fixed ON fixed.id = asset.id
    LEFT JOIN app.units AS unit ON unit.id = asset.unit_id
    LEFT JOIN app.gl_expenses AS expense ON expense.id = fixed.expense_id
    LEFT JOIN app.gl_expense_requests AS request ON request.id = expense.expense_request_id
    ORDER BY asset.asset_number
"""
ACCUMULATED: Final = """
    SELECT coalesce(sum(line.credit_cents - line.debit_cents), 0)
    FROM app.gl_journal_lines AS line
    JOIN app.gl_accounts AS account ON account.id = line.account_id
    WHERE account.property_id = %(prop)s AND account.code = '1590'
"""
RULES: Final = """
    SELECT app.business_rule_value('ASSET_LIMIT', %(today)s),
        app.business_rule_value('ASSET_LIFE_1510', %(today)s),
        app.business_rule_value('ASSET_LIFE_1520', %(today)s),
        app.business_rule_value('ASSET_LIFE_1530', %(today)s)
"""
LAST_DEPRECIATION: Final = """
    SELECT entry.entry_date, entry.entry_number
    FROM app.gl_journal_entries AS entry
    WHERE entry.property_id = %(prop)s AND entry.entry_kind = 'DEPRECIATION'
    ORDER BY entry.entry_date DESC, entry.posted_at DESC
    LIMIT 1
"""


class LedgerAssetsFlow(Protocol):
    def register(self, property_id: UUID) -> dict[str, Any]: ...


class UnavailableLedgerAssets:
    def register(self, property_id: UUID) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


def _whole(value: object) -> int | None:
    return None if value is None else int(str(value))


class PostgresLedgerAssets:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def register(self, property_id: UUID) -> dict[str, Any]:
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
        key: dict[str, Any] = {"prop": property_id, "today": today}
        assets = [
            {
                "id": str(r[0]),
                "asset_number": r[1],
                "item": r[2],
                "account_code": r[3],
                "account_name": r[4],
                "account_name_km": r[5],
                "unit_number": r[6],
                "cost_cents": r[7],
                "bought_on": r[8].isoformat(),
                "useful_life_years": r[9],
                "status": r[10],
                "monthly_cents": r[11],
                "depreciation_cents": r[12],
                "value_cents": r[13],
                "expense_number": r[14],
                "request_number": r[15],
                "expense_id": None if r[16] is None else str(r[16]),
            }
            for r in connection.execute(REGISTER, key)
        ]
        accumulated = connection.execute(ACCUMULATED, key).fetchone()
        rules = connection.execute(RULES, key).fetchone()
        last = connection.execute(LAST_DEPRECIATION, key).fetchone()
        return {
            "today": today.isoformat(),
            "assets": assets,
            "accumulated_cents": 0 if accumulated is None else int(accumulated[0]),
            "asset_limit_cents": None if rules is None else _whole(rules[0]),
            "years": {}
            if rules is None
            else {
                code: _whole(value)
                for code, value in zip(("1510", "1520", "1530"), rules[1:], strict=True)
            },
            "last_depreciation": None
            if last is None
            else {"entry_date": last[0].isoformat(), "entry_number": last[1]},
        }


def create_ledger_assets_router(resolver: ActorResolver, flow: LedgerAssetsFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/asset-register")
    def read_asset_register(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            data = flow.register(property_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    return router
