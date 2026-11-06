"""General Ledger money records API (phase 6 step 3).

Owner decisions: the expense flow of 02/11/2026, D4 (nobody approves their own; the Owner's own
spending goes in at once with a note), the round 21 and 22 screens of DESIGN.md, and the rights
table of 03/11/2026 (06:56 plan L1; 07:03 a Manager approves up to the Expense limit).

Every change goes through one checked database function (migration `20270416_266`), which checks
the actor's right for the Property again, writes the record, its journal entry and one audit
event. The route checks the main right first so a signed-in user without it gets 403 at once.

Reads (`private, no-store`):

- `GET /api/v1/properties/{property_id}/expense-requests` (`expenses.request`): a Staff member sees
  their own; anyone who approves or records Expenses sees all. An Expense report sent more than
  `EXP_REPORT_DAYS` after the spending is marked late.
- `GET .../ledger/suppliers` (`expenses.request`), `GET .../ledger/expenses` and
  `GET .../ledger/supplier-bills` (`ledger.read`).

Changes (browser mutation checks): Expense requests and reports, decisions, advances, bills, pay
back staff, voids, expenses recorded straight, supplier bill payments and their reversal, money
moves, owner money, petty cash top-ups, cash counts and the riel paid for a Refund from a riel
account (`POST .../ledger/refund-riel`, `ledger.money_move`, DL-161).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from property_rental.api_refusals import Refusal, RefusedRequest
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

EXPENSES_REQUEST = "expenses.request"
EXPENSES_APPROVE = "expenses.approve"
EXPENSES_RECORD = "expenses.record"
LEDGER_READ = "ledger.read"


class LedgerMoneyNotFound(LookupError):
    """The Property or the record is not there."""


class LedgerMoneyRefused(PermissionError):
    """The database refused the actor (a right, or their own request)."""


class LedgerMoneyInvalid(ValueError):
    """The values are refused."""


class LedgerMoneyConflict(RuntimeError):
    """The record is not in a step that allows this (closed month, already paid, ...)."""


class LedgerMoneyUnavailable(RuntimeError):
    """Persistence is unavailable."""


def _iso_date(raw: object) -> object:
    return date.fromisoformat(raw) if isinstance(raw, str) else raw


def _uuid(raw: object) -> object:
    return UUID(raw) if isinstance(raw, str) else raw


IsoDate = Annotated[date, BeforeValidator(_iso_date)]
Id = Annotated[UUID, BeforeValidator(_uuid)]
Cents = Annotated[int, Field(ge=1, le=10**13)]
Code = Annotated[str, Field(pattern=r"^[0-9]{4}$")]
Words = Annotated[str, Field(min_length=1, max_length=500)]
Note = Annotated[str, Field(max_length=500)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SupplierBody(Body):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    phone: Annotated[str, Field(max_length=40)] | None = None
    note: Note | None = None


class ExpenseRequestBody(Body):
    kind: Literal["REQUEST", "URGENT_REPORT"]
    account_code: Code
    description: Words
    reason: Words
    amount_cents: Cents
    currency: Literal["USD", "KHR"] = "USD"
    original_amount_minor: Cents | None = None
    exchange_rate_record_id: Id | None = None
    supplier_id: Id | None = None
    unit_id: Id | None = None
    spent_on: IsoDate | None = None
    paid_how: Literal["ADVANCE", "CASH", "PAY_LATER", "OWN_MONEY"]
    paid_from_code: Code | None = None


class DecisionBody(Body):
    approve: bool
    note: Note | None = None


class PaidFromBody(Body):
    from_code: Code
    paid_on: IsoDate


class BillBody(Body):
    spent_cents: Cents
    spent_on: IsoDate
    bill_number: Annotated[str, Field(max_length=80)] | None = None
    supplier_id: Id | None = None
    due_date: IsoDate | None = None


class ReasonBody(Body):
    reason: Words


class ExpenseBody(Body):
    expense_date: IsoDate
    account_code: Code
    description: Words
    amount_cents: Cents
    currency: Literal["USD", "KHR"] = "USD"
    original_amount_minor: Cents | None = None
    exchange_rate_record_id: Id | None = None
    paid_from_code: Code | None = None
    supplier_id: Id | None = None
    bill_number: Annotated[str, Field(max_length=80)] | None = None
    due_date: IsoDate | None = None
    unit_id: Id | None = None


class BillPaymentBody(Body):
    from_code: Code
    paid_on: IsoDate
    amount_cents: Cents


class MoneyMoveBody(Body):
    moved_on: IsoDate
    from_code: Code
    to_code: Code
    amount_cents: Cents
    received_cents: Cents | None = None
    riel_amount_minor: Cents | None = None
    exchange_rate_record_id: Id | None = None
    note: Note | None = None


class OwnerMoneyBody(Body):
    direction: Literal["IN", "OUT"]
    moved_on: IsoDate
    account_code: Code
    amount_cents: Cents
    note: Note | None = None


class PettyCashBody(Body):
    topped_up_on: IsoDate
    from_code: Code
    amount_cents: Cents


class RefundRielBody(Body):
    refund_id: Id
    riel_minor: Annotated[int, Field(ge=1, le=10**15)]


class CashCountBody(Body):
    account_code: Code
    counted_on: IsoDate
    counted_cents: Annotated[int, Field(ge=0, le=10**13)] | None = None
    counted_riel: Annotated[int, Field(ge=0, le=10**15)] | None = None
    exchange_rate_record_id: Id | None = None
    reason: Note | None = None


@dataclass(frozen=True, slots=True)
class Action:
    """One checked database function: the record it acts on and its arguments in order."""

    function: str
    target: str | None
    fields: tuple[str, ...]


# The target table proves the record belongs to the Property in the path.
ACTIONS: dict[str, Action] = {
    "add_supplier": Action("gl_add_supplier", None, ("name", "phone", "note")),
    "submit_request": Action(
        "gl_submit_expense_request",
        None,
        (
            "kind",
            "account_code",
            "description",
            "reason",
            "amount_cents",
            "currency",
            "original_amount_minor",
            "exchange_rate_record_id",
            "supplier_id",
            "unit_id",
            "spent_on",
            "paid_how",
            "paid_from_code",
        ),
    ),
    "decide_request": Action(
        "gl_decide_expense_request", "gl_expense_requests", ("approve", "note")
    ),
    "give_advance": Action("gl_give_advance", "gl_expense_requests", ("from_code", "paid_on")),
    "record_bill": Action(
        "gl_record_request_bill",
        "gl_expense_requests",
        ("spent_cents", "spent_on", "bill_number", "supplier_id", "due_date"),
    ),
    "pay_back_staff": Action("gl_pay_back_staff", "gl_expense_requests", ("from_code", "paid_on")),
    "void_request": Action("gl_void_expense_request", "gl_expense_requests", ("reason",)),
    "record_expense": Action(
        "gl_record_expense",
        None,
        (
            "expense_date",
            "account_code",
            "description",
            "amount_cents",
            "currency",
            "original_amount_minor",
            "exchange_rate_record_id",
            "paid_from_code",
            "supplier_id",
            "bill_number",
            "due_date",
            "unit_id",
        ),
    ),
    "void_expense": Action("gl_void_expense", "gl_expenses", ("reason",)),
    "pay_bill": Action(
        "gl_pay_supplier_bill", "gl_supplier_bills", ("from_code", "paid_on", "amount_cents")
    ),
    "reverse_bill_payment": Action("gl_reverse_bill_payment", "gl_bill_payments", ("reason",)),
    "move_money": Action(
        "gl_move_money",
        None,
        (
            "moved_on",
            "from_code",
            "to_code",
            "amount_cents",
            "received_cents",
            "riel_amount_minor",
            "exchange_rate_record_id",
            "note",
        ),
    ),
    "owner_money": Action(
        "gl_record_owner_money",
        None,
        ("direction", "moved_on", "account_code", "amount_cents", "note"),
    ),
    "top_up_petty_cash": Action(
        "gl_top_up_petty_cash", None, ("topped_up_on", "from_code", "amount_cents")
    ),
    # A Refund paid from a riel account: the riel that left it (owner 05/11/2026, DL-161).
    "refund_riel": Action("gl_record_refund_riel", None, ("refund_id", "riel_minor")),
    "count_cash": Action(
        "gl_count_cash",
        None,
        (
            "account_code",
            "counted_on",
            "counted_cents",
            "counted_riel",
            "exchange_rate_record_id",
            "reason",
        ),
    ),
}


class LedgerMoneyFlow(Protocol):
    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> UUID | None: ...

    def expense_requests(
        self, property_id: UUID, *, requested_by: str | None
    ) -> tuple[dict[str, Any], ...]: ...

    def rows(self, view: str, property_id: UUID) -> tuple[dict[str, Any], ...]: ...


class UnavailableLedgerMoneyFlow:
    def write(self, action: str, property_id: UUID, *_: object, **__: object) -> UUID | None:
        del action, property_id
        raise LedgerMoneyUnavailable

    def expense_requests(self, property_id: UUID, **_: object) -> tuple[dict[str, Any], ...]:
        del property_id
        raise LedgerMoneyUnavailable

    def rows(self, view: str, property_id: UUID) -> tuple[dict[str, Any], ...]:
        del view, property_id
        raise LedgerMoneyUnavailable


REQUESTS_QUERY = """
    SELECT request.id, request.request_number, request.request_kind AS kind, request.status,
        request.requested_by, account.code AS account_code, account.name_en AS account_name,
        request.description, request.reason, request.amount_cents, request.original_currency,
        request.original_amount_minor, request.paid_how, paid_from.code AS paid_from_code,
        request.supplier_id, supplier.name AS supplier_name, request.unit_id, request.spent_on,
        request.decided_by, request.decided_at, request.decision_note, request.own_spending_note,
        request.void_reason, request.created_at,
        requester.display_name AS requested_by_name, account.name_km AS account_name_km,
        paid_from.name_en AS paid_from_name, paid_from.name_km AS paid_from_name_km,
        unit.unit_number, out_entry.entry_number AS advance_entry_number,
        out_entry.entry_date AS advance_date,
        (request.status = 'PAID_OUT' AND out_entry.entry_date
            + coalesce(app.business_rule_value('EXP_REPORT_DAYS', out_entry.entry_date), 3)::int
            < timezone(property.timezone_name, now())::date) AS advance_late,
        (request.request_kind = 'URGENT_REPORT'
            AND timezone(property.timezone_name, request.created_at)::date - request.spent_on
                > coalesce(app.business_rule_value('EXP_REPORT_DAYS', request.spent_on), 3))
            AS is_late,
        coalesce((SELECT sum(line.credit_cents - line.debit_cents)
                  FROM app.gl_journal_lines AS line
                  JOIN app.gl_accounts AS owed ON owed.id = line.account_id
                  WHERE line.expense_request_id = request.id AND owed.code = '2310'), 0)::bigint
            AS owed_to_staff_cents
    FROM app.gl_expense_requests AS request
    JOIN app.properties AS property ON property.id = request.property_id
    JOIN app.gl_accounts AS account ON account.id = request.account_id
    LEFT JOIN app.gl_accounts AS paid_from ON paid_from.id = request.paid_from_account_id
    LEFT JOIN app.gl_suppliers AS supplier ON supplier.id = request.supplier_id
    LEFT JOIN app.user_accounts AS requester ON requester.actor_id = request.requested_by
    LEFT JOIN app.units AS unit ON unit.id = request.unit_id
    LEFT JOIN app.gl_journal_entries AS out_entry ON out_entry.id = request.paid_out_entry_id
    WHERE request.property_id = %(prop)s
      AND (%(mine)s::uuid IS NULL OR request.requested_by = %(mine)s::uuid)
    ORDER BY request.created_at DESC, request.request_number DESC
    LIMIT 500
"""
VIEWS = {
    "suppliers": """
        SELECT supplier.id, supplier.name, supplier.phone, supplier.note, supplier.is_active
        FROM app.gl_suppliers AS supplier WHERE supplier.property_id = %(prop)s
        ORDER BY supplier.name, supplier.id
    """,
    "expenses": """
        SELECT expense.id, expense.expense_number, expense.expense_date, expense.status,
            account.code AS account_code, account.name_en AS account_name, expense.description,
            expense.amount_cents, expense.original_currency, expense.original_amount_minor,
            paid_from.code AS paid_from_code, expense.bill_number, expense.supplier_id,
            supplier.name AS supplier_name, expense.unit_id, expense.expense_request_id,
            request.request_number, expense.void_reason, expense.created_at,
            account.name_km AS account_name_km, paid_from.name_en AS paid_from_name,
            paid_from.name_km AS paid_from_name_km, unit.unit_number,
            entry.entry_number, bill.bill_number AS supplier_bill_number,
            voider.display_name AS voided_by_name, expense.voided_at,
            void_entry.entry_number AS void_entry_number,
            EXISTS (SELECT 1 FROM app.gl_bill_payments AS payment
                    WHERE payment.supplier_bill_id = bill.id
                      AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
                                      WHERE reversal.bill_payment_id = payment.id))
                AS bill_has_payments
        FROM app.gl_expenses AS expense
        LEFT JOIN app.user_accounts AS voider ON voider.actor_id = expense.voided_by
        LEFT JOIN app.gl_journal_entries AS void_entry ON void_entry.id = expense.void_entry_id
        LEFT JOIN app.units AS unit ON unit.id = expense.unit_id
        LEFT JOIN app.gl_journal_entries AS entry ON entry.id = expense.entry_id
        LEFT JOIN app.gl_supplier_bills AS bill ON bill.expense_id = expense.id
        JOIN app.gl_accounts AS account ON account.id = expense.account_id
        LEFT JOIN app.gl_accounts AS paid_from ON paid_from.id = expense.paid_from_account_id
        LEFT JOIN app.gl_suppliers AS supplier ON supplier.id = expense.supplier_id
        LEFT JOIN app.gl_expense_requests AS request ON request.id = expense.expense_request_id
        WHERE expense.property_id = %(prop)s
        ORDER BY expense.expense_date DESC, expense.expense_number DESC
        LIMIT 500
    """,
    "supplier-bills": """
        SELECT bill.id, bill.bill_number, bill.status, bill.supplier_id,
            supplier.name AS supplier_name, bill.supplier_reference, bill.bill_date,
            bill.due_date, bill.amount_cents, bill.expense_id,
            bill.amount_cents - coalesce((
                SELECT sum(payment.amount_cents) FROM app.gl_bill_payments AS payment
                WHERE payment.supplier_bill_id = bill.id
                  AND NOT EXISTS (SELECT 1 FROM app.gl_bill_payment_reversals AS reversal
                                  WHERE reversal.bill_payment_id = payment.id)), 0)
                ::bigint AS still_to_pay_cents,
            account.code AS account_code, account.name_en AS account_name,
            account.name_km AS account_name_km, entry.entry_number,
            coalesce((
                SELECT jsonb_agg(jsonb_build_object(
                    'id', payment.id, 'paid_on', payment.paid_on,
                    'amount_cents', payment.amount_cents, 'paid_from_code', paid_from.code,
                    'paid_from_name', paid_from.name_en, 'paid_from_name_km', paid_from.name_km,
                    'entry_number', paid_entry.entry_number,
                    'reversed', reversal.id IS NOT NULL,
                    'reversal_reason', reversal.reason,
                    'reversed_at', reversal.created_at,
                    'reversed_by_name', reverser.display_name,
                    'reversal_entry_number', reversal_entry.entry_number)
                    ORDER BY payment.paid_on, payment.created_at)
                FROM app.gl_bill_payments AS payment
                JOIN app.gl_accounts AS paid_from ON paid_from.id = payment.paid_from_account_id
                LEFT JOIN app.gl_journal_entries AS paid_entry
                    ON paid_entry.id = payment.entry_id
                LEFT JOIN app.gl_bill_payment_reversals AS reversal
                    ON reversal.bill_payment_id = payment.id
                LEFT JOIN app.user_accounts AS reverser ON reverser.actor_id = reversal.created_by
                LEFT JOIN app.gl_journal_entries AS reversal_entry
                    ON reversal_entry.id = reversal.entry_id
                WHERE payment.supplier_bill_id = bill.id), '[]'::jsonb) AS payments
        FROM app.gl_supplier_bills AS bill
        JOIN app.gl_suppliers AS supplier ON supplier.id = bill.supplier_id
        LEFT JOIN app.gl_expenses AS expense ON expense.id = bill.expense_id
        LEFT JOIN app.gl_accounts AS account ON account.id = expense.account_id
        LEFT JOIN app.gl_journal_entries AS entry ON entry.id = expense.entry_id
        WHERE bill.property_id = %(prop)s
        ORDER BY bill.due_date, bill.bill_number
        LIMIT 500
    """,
}


def _json(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    # A SQL sum of cents is numeric: send it as a whole number, never as a string.
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return value


class PostgresLedgerMoneyFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _property(self, connection: psycopg.Connection[Any], property_id: UUID) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM app.properties WHERE id = %s", (property_id,)
            ).fetchone()
            is None
        ):
            raise LedgerMoneyNotFound

    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> UUID | None:
        step = ACTIONS[action]
        arguments = [values.get(name) for name in step.fields]
        try:
            with psycopg.connect(self._database_url) as connection:
                self._property(connection, property_id)
                if step.target is None:
                    leading: list[Any] = [property_id, UUID(actor_id)]
                else:
                    owner = connection.execute(
                        f"SELECT property_id FROM app.{step.target} WHERE id = %s",
                        (target_id,),
                    ).fetchone()
                    if owner is None or owner[0] != property_id:
                        raise LedgerMoneyNotFound
                    leading = [target_id, UUID(actor_id)]
                parameters = [*leading, *arguments, uuid4()]
                marks = ", ".join(["%s"] * len(parameters))
                row = connection.execute(
                    f"SELECT app.{step.function}({marks})", parameters
                ).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        result = None if row is None else row[0]
        return result if isinstance(result, UUID) else None

    def _select(self, query: str, parameters: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._property(connection, parameters["prop"])
                cursor = connection.execute(query, parameters)
                names = [column.name for column in cursor.description or ()]
                return tuple(
                    {name: _json(value) for name, value in zip(names, row, strict=True)}
                    for row in cursor.fetchall()
                )
        except psycopg.Error as exc:
            raise LedgerMoneyUnavailable from exc

    def expense_requests(
        self, property_id: UUID, *, requested_by: str | None
    ) -> tuple[dict[str, Any], ...]:
        return self._select(
            REQUESTS_QUERY,
            {"prop": property_id, "mine": None if requested_by is None else UUID(requested_by)},
        )

    def rows(self, view: str, property_id: UUID) -> tuple[dict[str, Any], ...]:
        return self._select(VIEWS[view], {"prop": property_id})


# The ledger functions raise their own plain sentences for the screen (SQLSTATE 42501, 22023 and
# 55000). Any other database refusal (a table check) answers a fixed sentence, never its text.
OWN_SENTENCES = frozenset({"42501", "22023", "55000"})


def _refusal(exc: psycopg.Error) -> Exception:
    state = exc.sqlstate or ""
    message = (exc.diag.message_primary or "Refused") if state in OWN_SENTENCES else ""
    if state == "42501":
        return LedgerMoneyRefused(message)
    if state in ("55000", "23505"):
        return LedgerMoneyConflict(message or "This record is already there")
    if state in ("22023", "23514", "22P02", "23502", "23503"):
        return LedgerMoneyInvalid(message or "These values are refused")
    if state == "P0002":
        # A V1 record the change names is not there (a Final Settlement correction).
        return LedgerMoneyNotFound()
    return LedgerMoneyUnavailable()


def _require(
    request: Request, resolver: ActorResolver, capability: str, property_id: UUID
) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not _holds(actor, capability, property_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return actor


def _holds(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    )


def _http(exc: Exception) -> Exception:
    if isinstance(exc, LedgerMoneyNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    for kind, status_code, code in (
        (LedgerMoneyRefused, status.HTTP_403_FORBIDDEN, "LEDGER_MONEY_REFUSED"),
        (LedgerMoneyInvalid, status.HTTP_422_UNPROCESSABLE_CONTENT, "LEDGER_MONEY_INVALID"),
        (LedgerMoneyConflict, status.HTTP_409_CONFLICT, "LEDGER_MONEY_CONFLICT"),
    ):
        if isinstance(exc, kind):
            return RefusedRequest(Refusal(status_code, code, str(exc) or "Refused"))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


# These answer with the record they act on; the others with the record they make.
TARGET_ANSWERS = frozenset(
    {"decide_request", "give_advance", "void_request", "void_expense", "reverse_bill_payment"}
)
FLOW_ERRORS = (
    LedgerMoneyNotFound,
    LedgerMoneyRefused,
    LedgerMoneyInvalid,
    LedgerMoneyConflict,
    LedgerMoneyUnavailable,
)


def create_ledger_money_router(
    resolver: ActorResolver, flow: LedgerMoneyFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["ledger"])

    def run(
        request: Request,
        property_id: UUID,
        capability: str,
        action: str,
        body: BaseModel,
        target_id: UUID | None = None,
    ) -> dict[str, object]:
        actor = _require(request, resolver, capability, property_id)
        require_browser_mutation(request, settings)
        try:
            made = flow.write(action, property_id, actor.actor_id, body.model_dump(), target_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {
            "data": {"id": str(target_id if action in TARGET_ANSWERS else made)},
            "meta": {"request_id": request.state.request_id},
        }

    def listing(request: Request, rows: tuple[dict[str, Any], ...]) -> dict[str, object]:
        return {
            "data": list(rows),
            "meta": {"request_id": request.state.request_id, "count": len(rows)},
        }

    @router.get("/expense-requests")
    def list_expense_requests(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        actor = _require(request, resolver, EXPENSES_REQUEST, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        sees_all = _holds(actor, EXPENSES_APPROVE, property_id) or _holds(
            actor, EXPENSES_RECORD, property_id
        )
        try:
            rows = flow.expense_requests(
                property_id, requested_by=None if sees_all else actor.actor_id
            )
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return listing(request, rows)

    def read_view(view: str, capability: str) -> None:
        def handler(property_id: UUID, request: Request, response: Response) -> dict[str, object]:
            _require(request, resolver, capability, property_id)
            response.headers["Cache-Control"] = "private, no-store"
            try:
                rows = flow.rows(view, property_id)
            except FLOW_ERRORS as exc:
                raise _http(exc) from exc
            return listing(request, rows)

        handler.__name__ = f"list_ledger_{view.replace('-', '_')}"
        router.add_api_route(f"/ledger/{view}", handler, methods=["GET"])

    read_view("suppliers", EXPENSES_REQUEST)
    read_view("expenses", LEDGER_READ)
    read_view("supplier-bills", LEDGER_READ)

    @router.post("/ledger/suppliers", status_code=status.HTTP_201_CREATED)
    def add_supplier(property_id: UUID, body: SupplierBody, request: Request) -> dict[str, object]:
        return run(request, property_id, EXPENSES_REQUEST, "add_supplier", body)

    @router.post("/expense-requests", status_code=status.HTTP_201_CREATED)
    def submit_expense_request(
        property_id: UUID, body: ExpenseRequestBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_REQUEST, "submit_request", body)

    @router.post("/expense-requests/{request_id}/decision")
    def decide_expense_request(
        property_id: UUID, request_id: UUID, body: DecisionBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_APPROVE, "decide_request", body, request_id)

    @router.post("/expense-requests/{request_id}/advance", status_code=status.HTTP_201_CREATED)
    def give_advance(
        property_id: UUID, request_id: UUID, body: PaidFromBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_RECORD, "give_advance", body, request_id)

    @router.post("/expense-requests/{request_id}/bill", status_code=status.HTTP_201_CREATED)
    def record_request_bill(
        property_id: UUID, request_id: UUID, body: BillBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_RECORD, "record_bill", body, request_id)

    @router.post("/expense-requests/{request_id}/pay-back", status_code=status.HTTP_201_CREATED)
    def pay_back_staff(
        property_id: UUID, request_id: UUID, body: PaidFromBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_RECORD, "pay_back_staff", body, request_id)

    @router.post("/expense-requests/{request_id}/void")
    def void_expense_request(
        property_id: UUID, request_id: UUID, body: ReasonBody, request: Request
    ) -> dict[str, object]:
        # The sender takes back a waiting request; the database asks an approver otherwise.
        return run(request, property_id, EXPENSES_REQUEST, "void_request", body, request_id)

    @router.post("/ledger/expenses", status_code=status.HTTP_201_CREATED)
    def record_expense(property_id: UUID, body: ExpenseBody, request: Request) -> dict[str, object]:
        return run(request, property_id, EXPENSES_RECORD, "record_expense", body)

    @router.post("/ledger/expenses/{expense_id}/void")
    def void_expense(
        property_id: UUID, expense_id: UUID, body: ReasonBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, EXPENSES_RECORD, "void_expense", body, expense_id)

    @router.post("/ledger/supplier-bills/{bill_id}/payments", status_code=status.HTTP_201_CREATED)
    def pay_supplier_bill(
        property_id: UUID, bill_id: UUID, body: BillPaymentBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, "supplier_bills.pay", "pay_bill", body, bill_id)

    @router.post("/ledger/bill-payments/{payment_id}/reversal")
    def reverse_bill_payment(
        property_id: UUID, payment_id: UUID, body: ReasonBody, request: Request
    ) -> dict[str, object]:
        return run(
            request, property_id, "supplier_bills.pay", "reverse_bill_payment", body, payment_id
        )

    @router.post("/ledger/money-moves", status_code=status.HTTP_201_CREATED)
    def move_money(property_id: UUID, body: MoneyMoveBody, request: Request) -> dict[str, object]:
        return run(request, property_id, "ledger.money_move", "move_money", body)

    @router.post("/ledger/owner-money", status_code=status.HTTP_201_CREATED)
    def record_owner_money(
        property_id: UUID, body: OwnerMoneyBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, "ledger.owner_money", "owner_money", body)

    @router.post("/ledger/petty-cash-top-ups", status_code=status.HTTP_201_CREATED)
    def top_up_petty_cash(
        property_id: UUID, body: PettyCashBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, "ledger.petty_cash", "top_up_petty_cash", body)

    @router.post("/ledger/refund-riel", status_code=status.HTTP_201_CREATED)
    def record_refund_riel(
        property_id: UUID, body: RefundRielBody, request: Request
    ) -> dict[str, object]:
        return run(request, property_id, "ledger.money_move", "refund_riel", body)

    @router.post("/ledger/cash-counts", status_code=status.HTTP_201_CREATED)
    def count_cash(property_id: UUID, body: CashCountBody, request: Request) -> dict[str, object]:
        return run(request, property_id, "ledger.cash_count", "count_cash", body)

    return router
