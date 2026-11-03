"""General Ledger reports API (phase 6 step 5).

`GET /api/v1/properties/{property_id}/ledger/reports/{report}` (`ledger.read`,
`private, no-store`) answers one Financial statement (see ``ledger_reports``) as JSON, or as an
Excel (`format=xlsx`) or A4 PDF (`format=pdf`) file to download (gap G1). Each answer says the
period, Closed or "Open, may still change" ("As at today" for the aging reports), and the check
line.

- `trial-balance`, `balance-sheet`: `as_of` (default today).
- `profit-and-loss`, `budget`: `month` (any day of the month; default this month).
- `cash-flow`: `from` and `to` (default this month up to today).
- `account-detail`: `account` (the four-digit code) with `from` and `to`.
- `customer-aging`, `bills-aging`: as at today.

Any other query value is refused (422).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Final, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from property_rental.identity import ActorResolver
from property_rental.ledger_money_api import FLOW_ERRORS, _http, _require
from property_rental.ledger_reports import LedgerReportFlow, ReportName, ReportParams

LEDGER_READ: Final = "ledger.read"
LONGEST_RANGE_DAYS: Final = 3_660
ALLOWED: Final[dict[str, frozenset[str]]] = {
    "trial-balance": frozenset({"as_of"}),
    "balance-sheet": frozenset({"as_of"}),
    "profit-and-loss": frozenset({"month"}),
    "budget": frozenset({"month"}),
    "cash-flow": frozenset({"from", "to"}),
    "account-detail": frozenset({"account", "from", "to"}),
    "customer-aging": frozenset(),
    "bills-aging": frozenset(),
}


def _attachment(file_name: str) -> str:
    return f"attachment; filename=\"{file_name}\"; filename*=UTF-8''{quote(file_name)}"


def create_ledger_reports_router(resolver: ActorResolver, flow: LedgerReportFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}/ledger", tags=["ledger"])

    @router.get("/reports/{report}", response_model=None)
    def read_report(
        property_id: UUID,
        report: ReportName,
        request: Request,
        response: Response,
        file_format: Annotated[Literal["json", "xlsx", "pdf"], Query(alias="format")] = "json",
        as_of: date | None = None,
        month: date | None = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        account: Annotated[str | None, Query(pattern=r"^[0-9]{4}$")] = None,
    ) -> dict[str, object] | Response:
        actor = _require(request, resolver, LEDGER_READ, property_id)
        unknown = set(request.query_params) - ALLOWED[report] - {"format"}
        if unknown:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if report == "account-detail" and account is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if (
            start is not None
            and end is not None
            and (start > end or (end - start).days > LONGEST_RANGE_DAYS)
        ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        params = ReportParams(as_of=as_of, month=month, start=start, end=end, account=account)
        try:
            made = flow.report(report, property_id, actor.actor_id, params)
        except FLOW_ERRORS as exc:
            raise _http(exc) from exc
        if file_format == "json":
            response.headers["Cache-Control"] = "private, no-store"
            return {"data": made.as_json(), "meta": {"request_id": request.state.request_id}}
        file = made.file(file_format)
        return Response(
            content=file.content,
            media_type=file.media_type,
            headers={
                "Content-Disposition": _attachment(file.file_name),
                "Cache-Control": "private, no-store",
                "X-Export-SHA256": file.sha256,
                "X-Export-Rows": str(file.row_count),
            },
        )

    return router
