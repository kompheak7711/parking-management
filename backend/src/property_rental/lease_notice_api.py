"""HTTP routes for termination notices (V1-058 R3 Terminate step).

DL-073 (owner, 2026-10-20): for a Rent nonpayment termination the termination notice is the
third letter, after the day-20 and day-30 letters; DL-070 keeps the 30-day landlord notice of
the standard Lease. A notice is evidence only: recording one never terminates a Lease. The
termination then names the notice (TerminationContextSource.notice_id), and the database
checks that it belongs to the same Lease and matches the provision and grounds.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.lease_notices import (
    LeaseNoticeAuthorizationError,
    LeaseNoticeConflictError,
    LeaseNoticeInvalidError,
    LeaseNoticeNotFoundError,
    LeaseNoticeResponse,
    LeaseNoticeUnavailableError,
    RecordLeaseNotice,
)
from property_rental.settings import Settings

TEXT = r"^\S(?:[\s\S]*\S)?$"
T = TypeVar("T")


class LeaseNoticeFlow(Protocol):
    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]: ...

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordLeaseNotice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseNoticeResponse: ...


class UnavailableLeaseNoticeFlow:
    def __getattr__(self, _: str) -> object:
        raise LeaseNoticeUnavailableError("Lease notice persistence is unavailable")


class NoticeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_id: UUID
    expected_lease_version: int = Field(strict=True, ge=1, le=2_147_483_647)
    notice_date: date
    intended_termination_date: date | None = None
    notice_text: str = Field(min_length=1, max_length=5000, pattern=TEXT)
    governing_lease_provision: str = Field(min_length=1, max_length=2000, pattern=TEXT)
    approved_grounds: str = Field(min_length=1, max_length=2000, pattern=TEXT)
    notice_period_terms: str = Field(min_length=1, max_length=2000, pattern=TEXT)
    evidence_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    communication_record: str = Field(min_length=1, max_length=2000, pattern=TEXT)
    authorization_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    reason: str = Field(min_length=1, max_length=500, pattern=TEXT)
    supersedes_notice_id: UUID | None = None


def _invoke(call: Callable[[], T]) -> T:
    try:
        return call()
    except LeaseNoticeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except LeaseNoticeAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except LeaseNoticeConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except (LeaseNoticeInvalidError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except LeaseNoticeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _number(request: Request, name: str, default: int, maximum: int, minimum: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or len(raw) > 7 or not minimum <= int(raw) <= maximum:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return int(raw)


def create_lease_notice_router(
    resolver: ActorResolver,
    flow: LeaseNoticeFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["lease notices"])

    def actor_for(request: Request) -> AuthenticatedActor:
        actor = resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return actor

    @router.get("/properties/{property_id}/leases/{lease_id}/termination-notices")
    def notices(property_id: UUID, lease_id: UUID, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        if any(
            key not in {"limit", "offset"} or len(request.query_params.getlist(key)) != 1
            for key in request.query_params
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        limit = _number(request, "limit", 50, 100, 1)
        offset = _number(request, "offset", 0, 1_000_000, 0)
        page = _invoke(
            lambda: flow.read(property_id, lease_id, actor=actor, limit=limit, offset=offset)
        )
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/termination-notices",
        status_code=status.HTTP_201_CREATED,
    )
    def record(
        property_id: UUID,
        lease_id: UUID,
        body: NoticeInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = actor_for(request)
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        require_browser_mutation(request, settings)
        command = _invoke(
            lambda: RecordLeaseNotice(
                idempotency_key=idempotency_key,
                notice_id=body.notice_id,
                expected_lease_version=body.expected_lease_version,
                notice_date=body.notice_date,
                intended_termination_date=body.intended_termination_date,
                notice_text=body.notice_text,
                governing_lease_provision=body.governing_lease_provision,
                approved_grounds=body.approved_grounds,
                notice_period_terms=body.notice_period_terms,
                evidence_reference=body.evidence_reference,
                communication_record=body.communication_record,
                authorization_reference=body.authorization_reference,
                reason=body.reason,
                supersedes_notice_id=body.supersedes_notice_id,
            )
        )
        reply = _invoke(
            lambda: flow.record(
                property_id,
                lease_id,
                command,
                actor=actor,
                request_id=request.state.request_id,
            )
        )
        return reply.body

    return router
