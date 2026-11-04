"""General Ledger books reads for the ledger screens (phase 6 step 6, part 1).

Owner plan of 03/11/2026 (rights table L1): reading the ledger needs `ledger.read` (Owner and
Manager). The ledger tables are read-only for the runtime login (phase 5 grants), so these
reads never change anything.

- `GET /api/v1/properties/{property_id}/ledger/accounts` lists the chart of accounts with each
  account's balance on its normal side, as at `as_of` (default today in Property time).
- `GET /api/v1/properties/{property_id}/ledger/entries` lists journal entries, newest first:
  one month (`month`, any day of it) or, without a month, the newest 80. It also lists the
  months that have entries, for the month picker.
- `GET /api/v1/properties/{property_id}/ledger/entries/{entry_number}` shows one entry with its
  lines, who posted it, and the entry it reverses or that reverses it.

Each entry names the app record it came from (an Invoice, a Receipt, an Expense ...) when the
app knows its number. Answers are `private, no-store`.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Path, Request, Response, status

from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import (
    FLOW_ERRORS,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    _http,
    _require,
)

LEDGER_READ: Final = "ledger.read"
NEWEST: Final = 80


# The app record each automatic entry came from: its number, and the page that opens it.
def source_sql(alias: str = "entry", entry_id: str | None = "entry.id") -> str:
    """The number of the app record a ledger row came from (`alias` has source_type and
    source_id); an adjusting entry is found by its journal entry id when one is given."""
    adjusting = (
        "NULL"
        if entry_id is None
        else "(SELECT a.adjustment_number FROM app.gl_adjusting_entries AS a "
        f"WHERE a.entry_id = {entry_id})"
    )
    return f"""
    CASE {alias}.source_type
        WHEN 'INVOICE' THEN (SELECT i.invoice_number FROM app.invoices AS i
            WHERE i.id = {alias}.source_id)
        WHEN 'INVOICE_LINE' THEN (SELECT i.invoice_number FROM app.invoice_lines AS l
            JOIN app.invoices AS i ON i.id = l.invoice_id WHERE l.id = {alias}.source_id)
        WHEN 'INVOICE_ADJUSTMENT' THEN (SELECT i.invoice_number
            FROM app.invoice_adjustments AS a JOIN app.invoices AS i ON i.id = a.invoice_id
            WHERE a.id = {alias}.source_id)
        WHEN 'LATE_PAYMENT_CHARGE' THEN (SELECT i.invoice_number
            FROM app.late_payment_charges AS c JOIN app.invoices AS i
            ON i.id = c.source_invoice_id WHERE c.id = {alias}.source_id)
        WHEN 'PAYMENT' THEN (SELECT r.receipt_number FROM app.receipts AS r
            WHERE r.payment_id = {alias}.source_id)
        WHEN 'PAYMENT_ALLOCATION' THEN (SELECT r.receipt_number
            FROM app.payment_allocations AS a JOIN app.receipts AS r
            ON r.payment_id = a.payment_id WHERE a.id = {alias}.source_id)
        WHEN 'DEPOSIT_RECEIPT' THEN (SELECT r.receipt_number
            FROM app.deposit_receipts AS d JOIN app.receipts AS r
            ON r.payment_id = d.payment_id WHERE d.id = {alias}.source_id)
        WHEN 'REFUND' THEN (SELECT f.refund_number FROM app.refunds AS f
            WHERE f.id = {alias}.source_id)
        WHEN 'REFUND_CORRECTION' THEN (SELECT f.refund_number
            FROM app.refund_corrections AS c JOIN app.refunds AS f ON f.id = c.refund_id
            WHERE c.id = {alias}.source_id)
        WHEN 'EXPENSE' THEN (SELECT x.expense_number FROM app.gl_expenses AS x
            WHERE x.id = {alias}.source_id)
        WHEN 'EXPENSE_REQUEST' THEN (SELECT q.request_number
            FROM app.gl_expense_requests AS q WHERE q.id = {alias}.source_id)
        WHEN 'STAFF_PAYBACK' THEN (SELECT q.request_number FROM app.gl_staff_paybacks AS p
            JOIN app.gl_expense_requests AS q ON q.id = p.expense_request_id
            WHERE p.id = {alias}.source_id)
        WHEN 'BILL_PAYMENT' THEN (SELECT b.bill_number FROM app.gl_bill_payments AS p
            JOIN app.gl_supplier_bills AS b ON b.id = p.supplier_bill_id
            WHERE p.id = {alias}.source_id)
        WHEN 'MONEY_MOVE' THEN (SELECT m.move_number FROM app.gl_money_moves AS m
            WHERE m.id = {alias}.source_id)
        ELSE {adjusting}
    END
"""


def link_sql(alias: str = "entry") -> str:
    """The record a source opens on: an Invoice, or a Receipt by its Payment."""
    return f"""
    CASE {alias}.source_type
        WHEN 'INVOICE' THEN {alias}.source_id
        WHEN 'INVOICE_LINE' THEN (SELECT l.invoice_id FROM app.invoice_lines AS l
            WHERE l.id = {alias}.source_id)
        WHEN 'INVOICE_ADJUSTMENT' THEN (SELECT a.invoice_id FROM app.invoice_adjustments AS a
            WHERE a.id = {alias}.source_id)
        WHEN 'LATE_PAYMENT_CHARGE' THEN (SELECT c.source_invoice_id
            FROM app.late_payment_charges AS c WHERE c.id = {alias}.source_id)
        WHEN 'PAYMENT' THEN {alias}.source_id
        WHEN 'PAYMENT_ALLOCATION' THEN (SELECT a.payment_id FROM app.payment_allocations AS a
            WHERE a.id = {alias}.source_id)
        WHEN 'DEPOSIT_RECEIPT' THEN (SELECT d.payment_id FROM app.deposit_receipts AS d
            WHERE d.id = {alias}.source_id)
    END
"""


INVOICE_SOURCES: Final = frozenset(
    {"INVOICE", "INVOICE_LINE", "INVOICE_ADJUSTMENT", "LATE_PAYMENT_CHARGE"}
)
RECEIPT_SOURCES: Final = frozenset({"PAYMENT", "PAYMENT_ALLOCATION", "DEPOSIT_RECEIPT"})


class LedgerBooksFlow(Protocol):
    def accounts(self, property_id: UUID, as_of: date | None) -> dict[str, Any]: ...

    def entries(self, property_id: UUID, month: date | None) -> dict[str, Any]: ...

    def entry(self, property_id: UUID, entry_number: str) -> dict[str, Any]: ...


class UnavailableLedgerBooks:
    def accounts(self, property_id: UUID, as_of: date | None) -> dict[str, Any]:
        raise LedgerMoneyUnavailable

    def entries(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        raise LedgerMoneyUnavailable

    def entry(self, property_id: UUID, entry_number: str) -> dict[str, Any]:
        raise LedgerMoneyUnavailable


def _iso(value: object) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return str(iso()) if callable(iso) else str(value)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def source_link(source_type: str, target: object) -> dict[str, str] | None:
    if target is None:
        return None
    if source_type in INVOICE_SOURCES:
        return {"page": "invoices", "detail": f"inv:{target}"}
    if source_type in RECEIPT_SOURCES:
        return {"page": "payments", "detail": f"receipt:{target}"}
    return None


class PostgresLedgerBooks:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _today(self, connection: psycopg.Connection[Any], property_id: UUID) -> date:
        row = connection.execute(
            "SELECT timezone(timezone_name, statement_timestamp())::date "
            "FROM app.properties WHERE id = %s",
            (property_id,),
        ).fetchone()
        if row is None:
            raise LedgerMoneyNotFound
        today: date = row[0]
        return today

    def accounts(self, property_id: UUID, as_of: date | None) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                day = as_of or self._today(connection, property_id)
                rows = connection.execute(
                    """
                    SELECT account.code, account.name_en, account.name_km,
                        account.account_type, account.normal_side, account.control_source,
                        account.is_tax_locked, account.is_active, account.is_postable,
                        coalesce(sum(line.debit_cents), 0), coalesce(sum(line.credit_cents), 0),
                        count(line.id) > 0
                    FROM app.gl_accounts AS account
                    LEFT JOIN app.gl_journal_lines AS line ON line.account_id = account.id
                        AND EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
                            WHERE entry.id = line.entry_id AND entry.entry_date <= %s)
                    WHERE account.property_id = %s
                    GROUP BY account.id
                    ORDER BY account.code
                    """,
                    (day, property_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc
        accounts = []
        for (
            code,
            name_en,
            name_km,
            account_type,
            normal_side,
            control_source,
            tax_locked,
            active,
            postable,
            debit,
            credit,
            used,
        ) in rows:
            natural = int(debit) - int(credit)
            accounts.append(
                {
                    "code": str(code),
                    "name_en": str(name_en),
                    "name_km": _text(name_km),
                    "account_type": str(account_type),
                    "normal_side": str(normal_side),
                    "control_source": _text(control_source),
                    "tax_locked": bool(tax_locked),
                    "active": bool(active),
                    "postable": bool(postable),
                    "used": bool(used),
                    "balance_cents": natural if normal_side == "DEBIT" else -natural,
                }
            )
        return {"as_of": day.isoformat(), "accounts": accounts}

    def entries(self, property_id: UUID, month: date | None) -> dict[str, Any]:
        start = None if month is None else month.replace(day=1)
        try:
            with psycopg.connect(self._database_url) as connection:
                self._today(connection, property_id)
                months = connection.execute(
                    "SELECT DISTINCT date_trunc('month', entry_date)::date AS month "
                    "FROM app.gl_journal_entries WHERE property_id = %s ORDER BY month DESC",
                    (property_id,),
                ).fetchall()
                rows = connection.execute(
                    f"""
                    SELECT entry.entry_number, entry.entry_date, entry.entry_kind,
                        entry.description, entry.source_type,
                        ({source_sql()}), ({link_sql()}),
                        (SELECT sum(line.debit_cents) FROM app.gl_journal_lines AS line
                            WHERE line.entry_id = entry.id),
                        (SELECT original.entry_number FROM app.gl_journal_entries AS original
                            WHERE original.id = entry.reverses_entry_id),
                        (SELECT later.entry_number FROM app.gl_journal_entries AS later
                            WHERE later.reverses_entry_id = entry.id)
                    FROM app.gl_journal_entries AS entry
                    WHERE entry.property_id = %s
                        AND (%s::date IS NULL OR (entry.entry_date >= %s::date
                            AND entry.entry_date < (%s::date + interval '1 month')::date))
                    ORDER BY entry.entry_date DESC, entry.entry_number DESC
                    LIMIT %s
                    """,
                    (property_id, start, start, start, NEWEST if start is None else 100_000),
                ).fetchall()
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc
        return {
            "month": None if start is None else start.isoformat(),
            "months": [row[0].isoformat() for row in months],
            "newest_only": start is None,
            "entries": [self._entry_row(row) for row in rows],
        }

    @staticmethod
    def _entry_row(row: tuple[Any, ...]) -> dict[str, Any]:
        number, day, kind, description, source_type, source, target, amount, reverses, later = row
        return {
            "entry_number": str(number),
            "entry_date": _iso(day),
            "entry_kind": str(kind),
            "description": str(description),
            "source_type": str(source_type),
            "source_number": _text(source),
            "source_link": source_link(str(source_type), target),
            "amount_cents": int(amount or 0),
            "reverses": _text(reverses),
            "reversed_by": _text(later),
        }

    def entry(self, property_id: UUID, entry_number: str) -> dict[str, Any]:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._today(connection, property_id)
                row = connection.execute(
                    f"""
                    SELECT entry.entry_number, entry.entry_date, entry.entry_kind,
                        entry.description, entry.source_type,
                        ({source_sql()}), ({link_sql()}),
                        (SELECT sum(line.debit_cents) FROM app.gl_journal_lines AS line
                            WHERE line.entry_id = entry.id),
                        (SELECT original.entry_number FROM app.gl_journal_entries AS original
                            WHERE original.id = entry.reverses_entry_id),
                        (SELECT later.entry_number FROM app.gl_journal_entries AS later
                            WHERE later.reverses_entry_id = entry.id),
                        entry.id, entry.reason, entry.posted_at,
                        poster.display_name, approver.display_name, period.status
                    FROM app.gl_journal_entries AS entry
                    JOIN app.gl_periods AS period ON period.id = entry.period_id
                    LEFT JOIN app.user_accounts AS poster ON poster.actor_id = entry.posted_by
                    LEFT JOIN app.user_accounts AS approver
                        ON approver.actor_id = entry.approved_by
                    WHERE entry.property_id = %s AND entry.entry_number = %s
                    """,
                    (property_id, entry_number),
                ).fetchone()
                if row is None:
                    raise LedgerMoneyNotFound
                lines = connection.execute(
                    """
                    SELECT account.code, account.name_en, account.name_km, line.debit_cents,
                        line.credit_cents, line.memo
                    FROM app.gl_journal_lines AS line
                    JOIN app.gl_accounts AS account ON account.id = line.account_id
                    WHERE line.entry_id = %s
                    ORDER BY line.line_no
                    """,
                    (row[10],),
                ).fetchall()
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc
        body = self._entry_row(row[:10])
        body.update(
            {
                "reason": _text(row[11]),
                "posted_at": _iso(row[12]),
                "posted_by_name": _text(row[13]),
                "approved_by_name": _text(row[14]),
                "month_closed": row[15] != "OPEN",
                "lines": [
                    {
                        "account_code": str(code),
                        "account_name_en": str(name_en),
                        "account_name_km": _text(name_km),
                        "debit_cents": int(debit),
                        "credit_cents": int(credit),
                        "memo": _text(memo),
                    }
                    for code, name_en, name_km, debit, credit, memo in lines
                ],
            }
        )
        return body


def create_ledger_books_router(resolver: ActorResolver, flow: LedgerBooksFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    def answer(request: Request, response: Response, data: dict[str, Any]) -> dict[str, object]:
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def unknown_query(request: Request, allowed: frozenset[str]) -> None:
        if set(request.query_params) - allowed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    @router.get("/accounts")
    def list_accounts(
        property_id: UUID, request: Request, response: Response, as_of: date | None = None
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        unknown_query(request, frozenset({"as_of"}))
        try:
            return answer(request, response, flow.accounts(property_id, as_of))
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc

    @router.get("/entries")
    def list_entries(
        property_id: UUID, request: Request, response: Response, month: date | None = None
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        unknown_query(request, frozenset({"month"}))
        try:
            return answer(request, response, flow.entries(property_id, month))
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc

    @router.get("/entries/{entry_number}")
    def read_entry(
        property_id: UUID,
        entry_number: Annotated[str, Path(pattern=r"^[A-Z]{2,5}[0-9]{6,9}$")],
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        unknown_query(request, frozenset())
        try:
            return answer(request, response, flow.entry(property_id, entry_number))
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc

    return router
