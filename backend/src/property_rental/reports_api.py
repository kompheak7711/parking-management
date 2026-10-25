"""V1-057 HTTP reads: the Home page, the reports and their files (API-076 to API-078).

Every route needs a signed-in person (the application adds that guard) and a read right for the
Property. A person without the right gets 403 and nothing else; a store failure is 503.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from property_rental.identity import ActorResolver, AuthenticatedActor
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

    return router
