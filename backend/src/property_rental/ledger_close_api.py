"""General Ledger close API (phase 6 step 4, parts 1 and 2).

Owner decisions: the round 22 screens of DESIGN.md (Adjusting entries, Opening balances,
Month-end close, Year-end close, Fixed assets, Bank matching, Budgets), gaps G2 (the Books check)
and G7 (riel at month end), the phase 6 plan L3, and the owner's answers of 03/11/2026 10:26
(equipment years as Business rules, changeable per item).

Every change goes through one checked database function (migrations `20270417_267` and
`20270418_268`), which checks the actor's right for the Property again. The route checks the
main right first.

Reads (`ledger.read`, `private, no-store`): adjusting entries, the opening balances with the
entry they would post, the Books check, the months, one month's close checks, the fixed assets
with their value now, a bank account's lines not yet matched up to a month, the bank matches,
the budgets and the write-offs.

Changes (browser mutation checks): prepare, approve or refuse, and void an adjusting entry;
start the ledger, type the opening balances and post them; run a month's month-end work; close a
month; close a year. A month whose checks are not all green answers `closed: false` with the
checks, and the try is kept. Change one item's years; mark a month's bank lines as matched to
the statement; send a budget, and approve it or send it back with a reason. Write off an unpaid
Invoice line or Late-payment charge after the Final Settlement is closed (Owner only, gap G6;
part 3, migration `20270419_269`); written-off debts are listed too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import (
    FLOW_ERRORS,
    Body,
    Cents,
    Code,
    Id,
    IsoDate,
    LedgerMoneyNotFound,
    LedgerMoneyUnavailable,
    Note,
    Words,
    _holds,
    _http,
    _json,
    _refusal,
    _require,
)
from property_rental.settings import Settings

LEDGER_READ = "ledger.read"
PREPARE = "ledger.adjustments.prepare"
APPROVE = "ledger.adjustments.approve"
OPENING = "ledger.opening_balances"
CLOSE = "ledger.close"
FIXED_ASSETS = "ledger.fixed_assets"
RECONCILE = "ledger.reconcile"
BUDGET_PREPARE = "ledger.budgets.prepare"
BUDGET_APPROVE = "ledger.budgets.approve"
WRITE_OFF = "ledger.write_off"

LineCents = Annotated[int, Field(ge=0, le=9 * 10**15)]


class Line(Body):
    account_code: Code
    debit_cents: LineCents = 0
    credit_cents: LineCents = 0
    memo: Note | None = None

    @model_validator(mode="after")
    def one_side(self) -> Line:
        if (self.debit_cents > 0) == (self.credit_cents > 0):
            raise ValueError("A line is a debit or a credit, more than zero")
        return self

    def as_json(self) -> dict[str, Any]:
        line: dict[str, Any] = {"account": self.account_code, "memo": self.memo}
        if self.debit_cents:
            line["debit_cents"] = self.debit_cents
        if self.credit_cents:
            line["credit_cents"] = self.credit_cents
        return line


class AdjustingLine(Line):
    unit_id: Id | None = None
    customer_id: Id | None = None
    supplier_id: Id | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            **super().as_json(),
            "unit_id": None if self.unit_id is None else str(self.unit_id),
            "customer_id": None if self.customer_id is None else str(self.customer_id),
            "supplier_id": None if self.supplier_id is None else str(self.supplier_id),
        }


class AdjustingEntryBody(Body):
    entry_date: IsoDate
    reason: Words
    lines: Annotated[list[AdjustingLine], Field(min_length=2, max_length=500)]
    own_note: Note | None = None


class DecisionBody(Body):
    approve: bool
    note: Note | None = None


class ReasonBody(Body):
    reason: Words


class StartBody(Body):
    first_year: Annotated[int, Field(ge=2000, le=2100)]


class OpeningLinesBody(Body):
    lines: Annotated[list[Line], Field(max_length=500)]


class NoBody(Body):
    pass


class AssetLifeBody(Body):
    years: Annotated[int, Field(ge=1, le=100)]
    reason: Words


class BankLine(Body):
    line_id: Id
    statement_date: IsoDate | None = None
    reference: Annotated[str, Field(max_length=100)] | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "statement_date": None
            if self.statement_date is None
            else self.statement_date.isoformat(),
            "reference": self.reference,
        }


class BankMatchBody(Body):
    account_code: Code
    period_id: Id
    statement_balance_cents: Annotated[int, Field(ge=-(9 * 10**15), le=9 * 10**15)]
    lines: Annotated[list[BankLine], Field(max_length=5000)]


class BudgetLine(Body):
    account_code: Code
    month_no: Annotated[int, Field(ge=1, le=12)]
    amount_cents: Annotated[int, Field(ge=0, le=10**13)]

    def as_json(self) -> dict[str, Any]:
        return {
            "account": self.account_code,
            "month_no": self.month_no,
            "amount_cents": self.amount_cents,
        }


class WriteOffBody(Body):
    """An Invoice line (invoice_id and invoice_line_id) or a Late-payment charge, after the
    Final Settlement is closed."""

    final_settlement_id: Id
    invoice_id: Id | None = None
    invoice_line_id: Id | None = None
    late_payment_charge_id: Id | None = None
    amount_cents: Cents
    reason: Words

    @model_validator(mode="after")
    def one_target(self) -> WriteOffBody:
        line = self.invoice_id is not None and self.invoice_line_id is not None
        partial = (self.invoice_id is None) != (self.invoice_line_id is None)
        late = self.late_payment_charge_id is not None
        if partial or line == late:
            raise ValueError("Name an Invoice line or a Late-payment charge")
        return self

    def target(self) -> dict[str, Any]:
        if self.late_payment_charge_id is not None:
            return {
                "late_payment_charge_id": str(self.late_payment_charge_id),
                "amount_usd_cents": self.amount_cents,
            }
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_line_id": str(self.invoice_line_id),
            "amount_usd_cents": self.amount_cents,
        }


class BudgetBody(Body):
    fiscal_year: Annotated[int, Field(ge=2000, le=2100)]
    lines: Annotated[list[BudgetLine], Field(min_length=1, max_length=5000)]
    own_note: Note | None = None


@dataclass(frozen=True, slots=True)
class Action:
    function: str
    target: str | None
    fields: tuple[str, ...]
    smallint_field: str | None = None


JSON_FIELDS = frozenset({"lines", "items", "target"})


ACTIONS: dict[str, Action] = {
    "prepare_adjustment": Action(
        "gl_prepare_adjusting_entry", None, ("entry_date", "reason", "lines", "own_note")
    ),
    "decide_adjustment": Action(
        "gl_decide_adjusting_entry", "gl_adjusting_entries", ("approve", "note")
    ),
    "void_adjustment": Action("gl_void_adjusting_entry", "gl_adjusting_entries", ("reason",)),
    "begin_ledger": Action("gl_begin_ledger", None, ("first_year",), smallint_field="first_year"),
    "set_opening_lines": Action("gl_set_opening_lines", None, ("lines",)),
    "post_opening": Action("gl_post_opening_balances", None, ()),
    "close_month": Action("gl_close_month", "gl_periods", ()),
    "close_year": Action("gl_close_fiscal_year", "gl_fiscal_years", ()),
    "run_month_end": Action("gl_run_month_end", "gl_periods", ()),
    "change_asset_life": Action(
        "gl_change_asset_life", "gl_fixed_assets", ("years", "reason"), smallint_field="years"
    ),
    "match_bank": Action(
        "gl_match_bank", None, ("account_code", "period_id", "statement_cents", "items")
    ),
    "prepare_budget": Action(
        "gl_prepare_budget",
        None,
        ("fiscal_year", "lines", "own_note"),
        smallint_field="fiscal_year",
    ),
    "decide_budget": Action("gl_decide_budget", "gl_budgets", ("approve", "note")),
    "write_off": Action("gl_write_off", None, ("final_settlement_id", "target", "reason")),
}


class LedgerCloseFlow(Protocol):
    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> Any: ...

    def rows(
        self,
        view: str,
        property_id: UUID,
        target_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]: ...


class UnavailableLedgerCloseFlow:
    def write(self, action: str, property_id: UUID, *_: object, **__: object) -> Any:
        del action, property_id
        raise LedgerMoneyUnavailable

    def rows(self, view: str, property_id: UUID, *_: object) -> tuple[dict[str, Any], ...]:
        del view, property_id
        raise LedgerMoneyUnavailable


VIEWS = {
    "adjusting-entries": """
        SELECT adjustment.id, adjustment.adjustment_number, adjustment.entry_date,
            adjustment.reason, adjustment.status, adjustment.prepared_by, adjustment.decided_by,
            adjustment.decided_at, adjustment.decision_note, adjustment.own_entry_note,
            adjustment.entry_id, adjustment.created_at,
            (SELECT json_agg(json_build_object('account_code', account.code,
                    'account_name', account.name_en, 'debit_cents', line.debit_cents,
                    'credit_cents', line.credit_cents, 'memo', line.memo,
                    'unit_id', line.unit_id, 'customer_id', line.customer_id,
                    'supplier_id', line.supplier_id) ORDER BY line.line_no)
             FROM app.gl_adjusting_entry_lines AS line
             JOIN app.gl_accounts AS account ON account.id = line.account_id
             WHERE line.adjusting_entry_id = adjustment.id) AS lines
        FROM app.gl_adjusting_entries AS adjustment
        WHERE adjustment.property_id = %(prop)s
        ORDER BY adjustment.entry_date DESC, adjustment.adjustment_number DESC
        LIMIT 500
    """,
    "opening-balances": """
        SELECT opening.id, opening.start_date, opening.status, opening.entry_id,
            opening.posted_by, opening.posted_at,
            (SELECT json_agg(json_build_object('account_code', preview.code,
                    'debit_cents', preview.debit_cents, 'credit_cents', preview.credit_cents,
                    'worked_out', preview.worked_out) ORDER BY preview.code)
             FROM app.gl_opening_preview(%(prop)s) AS preview) AS lines,
            (SELECT coalesce(sum(preview.debit_cents - preview.credit_cents), 0)
             FROM app.gl_opening_preview(%(prop)s) AS preview) AS difference_cents
        FROM app.gl_opening_balances AS opening
        WHERE opening.property_id = %(prop)s
    """,
    "books-check": """
        SELECT check_code, accounts, in_books, in_list, ok
        FROM app.gl_books_check(%(prop)s)
    """,
    "periods": """
        SELECT period.id, year.id AS fiscal_year_id, year.fiscal_year, year.status AS year_status,
            period.period_no, period.starts_on, period.ends_on, period.status,
            period.closed_at, period.closed_by
        FROM app.gl_periods AS period
        JOIN app.gl_fiscal_years AS year ON year.id = period.fiscal_year_id
        WHERE period.property_id = %(prop)s AND period.period_no <= 12
        ORDER BY period.starts_on
    """,
    "close-checks": """
        SELECT item.check_code, item.ok, item.open_items
        FROM app.gl_periods AS period
        CROSS JOIN LATERAL app.gl_month_close_checks(period.id) AS item
        WHERE period.id = %(target)s AND period.property_id = %(prop)s
    """,
    "fixed-assets": """
        SELECT asset.*,
            (SELECT json_agg(json_build_object('useful_life_years', change.useful_life_years,
                    'starts_on', change.starts_on, 'value_cents', change.value_cents,
                    'months_left', change.months_left, 'reason', change.reason,
                    'created_by', change.created_by, 'created_at', change.created_at)
                    ORDER BY change.created_at)
             FROM app.gl_fixed_asset_life_changes AS change
             WHERE change.fixed_asset_id = asset.id) AS life_changes
        FROM app.gl_asset_values(%(prop)s) AS asset
        ORDER BY asset.asset_number
    """,
    "bank-lines": """
        SELECT line.*
        FROM app.gl_periods AS period
        CROSS JOIN LATERAL app.gl_bank_lines(%(prop)s, %(account)s, period.id) AS line
        WHERE period.id = %(target)s AND period.property_id = %(prop)s
    """,
    "bank-matches": """
        SELECT match.id, account.code AS account_code, match.period_id, period.ends_on,
            match.statement_balance_cents, match.status, match.created_by, match.created_at,
            match.matched_by, match.matched_at,
            (SELECT count(*) FROM app.gl_bank_reconciliation_items AS item
             WHERE item.reconciliation_id = match.id) AS lines
        FROM app.gl_bank_reconciliations AS match
        JOIN app.gl_accounts AS account ON account.id = match.account_id
        JOIN app.gl_periods AS period ON period.id = match.period_id
        WHERE match.property_id = %(prop)s
        ORDER BY period.ends_on DESC, account.code
        LIMIT 500
    """,
    "write-offs": """
        SELECT write_off.id, write_off.invoice_id, invoice.invoice_number, invoice.customer_id,
            write_off.amount_cents, write_off.reason, write_off.approved_by, write_off.created_at,
            write_off.settlement_correction_id,
            app.gl_write_off_settlement(write_off.settlement_correction_id)
                AS final_settlement_id
        FROM app.gl_write_offs AS write_off
        JOIN app.invoices AS invoice ON invoice.id = write_off.invoice_id
        WHERE write_off.property_id = %(prop)s
        ORDER BY write_off.created_at DESC
        LIMIT 500
    """,
    "budgets": """
        SELECT budget.id, year.fiscal_year, budget.version, budget.status, budget.created_by,
            budget.created_at, budget.approved_by, budget.approved_at, budget.decision_note,
            budget.own_budget_note,
            (SELECT json_agg(json_build_object('account_code', account.code,
                    'account_name', account.name_en, 'month_no', line.month_no,
                    'amount_cents', line.amount_cents) ORDER BY account.code, line.month_no)
             FROM app.gl_budget_lines AS line
             JOIN app.gl_accounts AS account ON account.id = line.account_id
             WHERE line.budget_id = budget.id) AS lines
        FROM app.gl_budgets AS budget
        JOIN app.gl_fiscal_years AS year ON year.id = budget.fiscal_year_id
        WHERE budget.property_id = %(prop)s
        ORDER BY year.fiscal_year DESC, budget.version DESC
        LIMIT 200
    """,
}


class PostgresLedgerCloseFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @staticmethod
    def _property(connection: psycopg.Connection[Any], property_id: UUID) -> None:
        found = connection.execute(
            "SELECT 1 FROM app.properties WHERE id = %s", (property_id,)
        ).fetchone()
        if found is None:
            raise LedgerMoneyNotFound

    def write(
        self,
        action: str,
        property_id: UUID,
        actor_id: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> Any:
        step = ACTIONS[action]
        arguments: list[Any] = []
        for name in step.fields:
            value = values.get(name)
            if name in JSON_FIELDS:
                value = Jsonb(value)
            arguments.append(value)
        marks = ["%s"] * (len(arguments) + 3)
        if step.smallint_field is not None:
            marks[2 + step.fields.index(step.smallint_field)] = "%s::smallint"
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
                row = connection.execute(
                    f"SELECT app.{step.function}({', '.join(marks)})",
                    [*leading, *arguments, uuid4()],
                ).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def rows(
        self,
        view: str,
        property_id: UUID,
        target_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                self._property(connection, property_id)
                cursor = connection.execute(
                    VIEWS[view], {**(extra or {}), "prop": property_id, "target": target_id}
                )
                names = [column.name for column in cursor.description or ()]
                return tuple(
                    {name: _json(value) for name, value in zip(names, row, strict=True)}
                    for row in cursor.fetchall()
                )
        except psycopg.Error as exc:
            raise _refusal(exc) from exc


def create_ledger_close_router(
    resolver: ActorResolver, flow: LedgerCloseFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    def change(
        request: Request,
        property_id: UUID,
        capabilities: tuple[str, ...],
        action: str,
        values: dict[str, Any],
        target_id: UUID | None = None,
    ) -> Any:
        actor = resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not any(_holds(actor, capability, property_id) for capability in capabilities):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        require_browser_mutation(request, settings)
        try:
            return flow.write(action, property_id, actor.actor_id, values, target_id)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc

    def answer(request: Request, data: object) -> dict[str, object]:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def read(
        request: Request,
        response: Response,
        property_id: UUID,
        view: str,
        target_id: UUID | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        _require(request, resolver, LEDGER_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            rows = flow.rows(view, property_id, target_id, extra)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        return {
            "data": list(rows),
            "meta": {"request_id": request.state.request_id, "count": len(rows)},
        }

    @router.get("/adjusting-entries")
    def list_adjusting_entries(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        return read(request, response, property_id, "adjusting-entries")

    @router.post("/adjusting-entries", status_code=status.HTTP_201_CREATED)
    def prepare_adjusting_entry(
        property_id: UUID, body: AdjustingEntryBody, request: Request
    ) -> dict[str, object]:
        values = body.model_dump()
        values["lines"] = [line.as_json() for line in body.lines]
        made = change(request, property_id, (PREPARE,), "prepare_adjustment", values)
        return answer(request, {"id": str(made)})

    @router.post("/adjusting-entries/{adjustment_id}/decision")
    def decide_adjusting_entry(
        property_id: UUID, adjustment_id: UUID, body: DecisionBody, request: Request
    ) -> dict[str, object]:
        change(
            request, property_id, (APPROVE,), "decide_adjustment", body.model_dump(), adjustment_id
        )
        return answer(request, {"id": str(adjustment_id)})

    @router.post("/adjusting-entries/{adjustment_id}/void")
    def void_adjusting_entry(
        property_id: UUID, adjustment_id: UUID, body: ReasonBody, request: Request
    ) -> dict[str, object]:
        # The one who prepared it, or an approver; the database tells them apart.
        change(
            request,
            property_id,
            (PREPARE, APPROVE),
            "void_adjustment",
            body.model_dump(),
            adjustment_id,
        )
        return answer(request, {"id": str(adjustment_id)})

    @router.get("/opening-balances")
    def read_opening_balances(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        return read(request, response, property_id, "opening-balances")

    @router.post("/opening-balances", status_code=status.HTTP_201_CREATED)
    def start_ledger(property_id: UUID, body: StartBody, request: Request) -> dict[str, object]:
        made = change(request, property_id, (OPENING,), "begin_ledger", body.model_dump())
        return answer(request, {"id": str(made)})

    @router.put("/opening-balances/lines")
    def set_opening_lines(
        property_id: UUID, body: OpeningLinesBody, request: Request
    ) -> dict[str, object]:
        values = {"lines": [line.as_json() for line in body.lines]}
        change(request, property_id, (OPENING,), "set_opening_lines", values)
        return answer(request, {"lines": len(body.lines)})

    @router.post("/opening-balances/post", status_code=status.HTTP_201_CREATED)
    def post_opening_balances(
        property_id: UUID, body: NoBody, request: Request
    ) -> dict[str, object]:
        del body
        entry = change(request, property_id, (OPENING,), "post_opening", {})
        return answer(request, {"entry_id": str(entry)})

    @router.get("/books-check")
    def books_check(property_id: UUID, request: Request, response: Response) -> dict[str, object]:
        return read(request, response, property_id, "books-check")

    @router.get("/periods")
    def list_periods(property_id: UUID, request: Request, response: Response) -> dict[str, object]:
        return read(request, response, property_id, "periods")

    @router.get("/periods/{period_id}/close-checks")
    def close_checks(
        property_id: UUID, period_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        found = read(request, response, property_id, "close-checks", period_id)
        if not found["data"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return found

    @router.post("/periods/{period_id}/close")
    def close_month(
        property_id: UUID, period_id: UUID, body: NoBody, request: Request
    ) -> dict[str, object]:
        del body
        result = change(request, property_id, (CLOSE,), "close_month", {}, period_id)
        return answer(request, result)

    @router.post("/fiscal-years/{year_id}/close")
    def close_year(
        property_id: UUID, year_id: UUID, body: NoBody, request: Request
    ) -> dict[str, object]:
        del body
        entry = change(request, property_id, (CLOSE,), "close_year", {}, year_id)
        return answer(request, {"entry_id": None if entry is None else str(entry)})

    @router.post("/periods/{period_id}/month-end")
    def run_month_end(
        property_id: UUID, period_id: UUID, body: NoBody, request: Request
    ) -> dict[str, object]:
        # The month's depreciation and riel valuation; what is missing is refused with words.
        del body
        result = change(request, property_id, (CLOSE,), "run_month_end", {}, period_id)
        return answer(request, result)

    @router.get("/fixed-assets")
    def list_fixed_assets(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        return read(request, response, property_id, "fixed-assets")

    @router.post("/fixed-assets/{asset_id}/life", status_code=status.HTTP_201_CREATED)
    def change_asset_life(
        property_id: UUID, asset_id: UUID, body: AssetLifeBody, request: Request
    ) -> dict[str, object]:
        made = change(
            request, property_id, (FIXED_ASSETS,), "change_asset_life", body.model_dump(), asset_id
        )
        return answer(request, {"id": str(made)})

    @router.get("/periods/{period_id}/bank-lines/{account_code}")
    def bank_lines(
        property_id: UUID,
        period_id: UUID,
        account_code: Annotated[str, Path(pattern=r"^[0-9]{4}$")],
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        return read(
            request, response, property_id, "bank-lines", period_id, {"account": account_code}
        )

    @router.get("/bank-matches")
    def list_bank_matches(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        return read(request, response, property_id, "bank-matches")

    @router.post("/bank-matches", status_code=status.HTTP_201_CREATED)
    def match_bank(property_id: UUID, body: BankMatchBody, request: Request) -> dict[str, object]:
        values = {
            "account_code": body.account_code,
            "period_id": body.period_id,
            "statement_cents": body.statement_balance_cents,
            "items": [line.as_json() for line in body.lines],
        }
        made = change(request, property_id, (RECONCILE,), "match_bank", values)
        return answer(request, {"id": str(made)})

    @router.get("/write-offs")
    def list_write_offs(
        property_id: UUID, request: Request, response: Response
    ) -> dict[str, object]:
        return read(request, response, property_id, "write-offs")

    @router.post("/write-offs", status_code=status.HTTP_201_CREATED)
    def write_off(property_id: UUID, body: WriteOffBody, request: Request) -> dict[str, object]:
        # Owner only (G6); the database checks the closed Settlement and the unpaid rest.
        values = {
            "final_settlement_id": body.final_settlement_id,
            "target": body.target(),
            "reason": body.reason,
        }
        made = change(request, property_id, (WRITE_OFF,), "write_off", values)
        return answer(request, {"id": str(made)})

    @router.get("/budgets")
    def list_budgets(property_id: UUID, request: Request, response: Response) -> dict[str, object]:
        return read(request, response, property_id, "budgets")

    @router.post("/budgets", status_code=status.HTTP_201_CREATED)
    def prepare_budget(property_id: UUID, body: BudgetBody, request: Request) -> dict[str, object]:
        values = {
            "fiscal_year": body.fiscal_year,
            "lines": [line.as_json() for line in body.lines],
            "own_note": body.own_note,
        }
        made = change(request, property_id, (BUDGET_PREPARE,), "prepare_budget", values)
        return answer(request, {"id": str(made)})

    @router.post("/budgets/{budget_id}/decision")
    def decide_budget(
        property_id: UUID, budget_id: UUID, body: DecisionBody, request: Request
    ) -> dict[str, object]:
        change(
            request, property_id, (BUDGET_APPROVE,), "decide_budget", body.model_dump(), budget_id
        )
        return answer(request, {"id": str(budget_id)})

    return router
