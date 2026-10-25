"""V1-057 HTTP reads: the Home page, the reports and their files (API-076 to API-078).

Every route needs a signed-in person (the application adds that guard) and a read right for the
Property. A person without the right gets 403 and nothing else; a store failure is 503.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.report_registers import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    RegisterFilter,
    RegisterName,
)
from property_rental.report_totals import TotalsFilter, TotalsReport
from property_rental.reports import (
    ReportForbiddenError,
    ReportInvalidError,
    ReportService,
    ReportUnavailableError,
)

T = TypeVar("T")


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except ReportForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except ReportInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except ReportUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _no_query(request: Request, allowed: frozenset[str] = frozenset()) -> None:
    unknown = set(request.query_params) - allowed
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def create_reports_router(resolver: ActorResolver, service: ReportService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["reports"])

    @router.get("/properties/{property_id}/home", summary="The Home cards and to-do list")
    def home_page(property_id: UUID, request: Request, response: Response) -> dict[str, object]:
        _no_query(request)
        actor = _actor(request, resolver)
        page = _call(lambda: service.home_page(actor, property_id))
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    @router.get(
        "/properties/{property_id}/reports/totals/{report}",
        summary="A Totals by Unit and month report",
    )
    def totals(
        property_id: UUID,
        report: TotalsReport,
        request: Request,
        response: Response,
        unit_id: UUID | None = None,
        floor: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
        from_date: Annotated[date | None, Query(alias="from")] = None,
        to_date: Annotated[date | None, Query(alias="to")] = None,
    ) -> dict[str, object]:
        _no_query(request, frozenset({"unit_id", "floor", "from", "to"}))
        actor = _actor(request, resolver)
        chosen = TotalsFilter(unit_id, floor, from_date, to_date)
        page = _call(lambda: service.totals(actor, property_id, report, chosen))
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    @router.get(
        "/properties/{property_id}/reports/{name}",
        summary="One of the nine registers and lists",
    )
    def register(
        property_id: UUID,
        name: RegisterName,
        request: Request,
        response: Response,
        floor: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
        from_date: Annotated[date | None, Query(alias="from")] = None,
        to_date: Annotated[date | None, Query(alias="to")] = None,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    ) -> dict[str, object]:
        _no_query(request, frozenset({"floor", "from", "to", "offset", "limit"}))
        actor = _actor(request, resolver)
        chosen = RegisterFilter(floor, from_date, to_date, offset, limit)
        page = _call(lambda: service.register(actor, property_id, name, chosen))
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    return router
