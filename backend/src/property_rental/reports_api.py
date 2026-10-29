"""V1-057 HTTP reads: the Home page, the reports and their files (API-076 to API-078).

Every route needs a signed-in person (the application adds that guard) and a read right for the
Property. A person without the right gets 403 and nothing else; a store failure is 503.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, TypeVar, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.report_exports import (
    AuditExportRequest,
    ExportRequest,
    ExportResult,
    ExportService,
)
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
    ReportNotFoundError,
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
    except ReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except ReportUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _no_query(request: Request, allowed: frozenset[str] = frozenset()) -> None:
    unknown = set(request.query_params) - allowed
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


class ExportBody(BaseModel):
    """A report file: the report, the file type and the same filters as the report page."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    report: str = Field(pattern=r"^[a-z_]{1,64}$")
    file_type: Literal["xlsx", "pdf"]
    floor: str | None = Field(default=None, min_length=1, max_length=40)
    unit_id: UUID | None = None
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")


class AuditExportBody(BaseModel):
    """The audit history file with the History page filters."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    file_type: Literal["xlsx", "pdf"]
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")
    actor_id: UUID | None = None
    action: str | None = Field(default=None, min_length=1, max_length=128)
    unit_id: UUID | None = None


def _attachment(file_name: str) -> str:
    return f"attachment; filename=\"{file_name}\"; filename*=UTF-8''{quote(file_name)}"


def _file_answer(result: ExportResult, request_id: str) -> Response:
    """A small file downloads at once; a large one answers 201 with its export job."""
    file = result.file
    if result.expires_at is None:
        return Response(
            content=file.content,
            media_type=file.media_type,
            headers={
                "Content-Disposition": _attachment(file.file_name),
                "Cache-Control": "private, no-store",
                "X-Export-Id": str(result.export_id),
                "X-Export-SHA256": file.sha256,
                "X-Export-Rows": str(file.row_count),
            },
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "private, no-store"},
        content={
            "data": {
                "export_id": str(result.export_id),
                "file_name": file.file_name,
                "row_count": file.row_count,
                "sha256": file.sha256,
                "expires_at": result.expires_at.isoformat(),
            },
            "meta": {"request_id": request_id},
        },
    )


def create_reports_router(
    resolver: ActorResolver, service: ReportService, exports: ExportService
) -> APIRouter:
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
        summary="A Totals by Parking and month report",
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

    @router.post("/properties/{property_id}/exports", summary="A report file (.xlsx or PDF)")
    def export_report(property_id: UUID, body: ExportBody, request: Request) -> Response:
        actor = _actor(request, resolver)
        chosen = ExportRequest(
            body.report, body.file_type, body.floor, body.unit_id, body.from_date, body.to_date
        )
        result = _call(lambda: exports.export(actor, property_id, chosen))
        return _file_answer(result, request.state.request_id)

    @router.post(
        "/properties/{property_id}/audit-exports",
        summary="The audit history file (.xlsx or PDF) with its SHA-256 fingerprint",
    )
    def export_audit(property_id: UUID, body: AuditExportBody, request: Request) -> Response:
        actor = _actor(request, resolver)
        chosen = AuditExportRequest(
            body.file_type, body.from_date, body.to_date, body.actor_id, body.action, body.unit_id
        )
        result = _call(lambda: exports.audit_export(actor, property_id, chosen))
        return _file_answer(result, request.state.request_id)

    @router.get(
        "/properties/{property_id}/exports/{export_id}",
        summary="A kept export file, for 24 hours",
    )
    def take_export(property_id: UUID, export_id: UUID, request: Request) -> Response:
        _no_query(request)
        actor = _actor(request, resolver)
        kept = _call(lambda: exports.take(actor, property_id, export_id))
        return Response(
            content=cast(bytes, kept["content"]),
            media_type=str(kept["media_type"]),
            headers={
                "Content-Disposition": _attachment(str(kept["file_name"])),
                "Cache-Control": "private, no-store",
                "X-Export-SHA256": str(kept["sha256"]),
            },
        )

    return router
