"""HTTP routes for the move-out record and the move-out inspection (V1-058 R3 Move-out).

The two services existed since V1-055 (physical_move_out.py, move_out_inspection.py) with no
route; the Move-out screen needs them. A move-out record says the tenants left and the Unit is
not ready to let; it creates no charge and never decides Final Settlement. An inspection records
what was found; charges come from the Final Settlement steps. Both are append-only: a correction
names the record it replaces.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, Protocol, TypeVar
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.move_out_inspection import (
    InspectionFinding,
    MoveOutInspectionAuthorizationError,
    MoveOutInspectionConflictError,
    MoveOutInspectionInvalidError,
    MoveOutInspectionNotFoundError,
    MoveOutInspectionResponse,
    MoveOutInspectionUnavailableError,
    RecordMoveOutInspection,
)
from property_rental.physical_move_out import (
    EndedOccupancy,
    PhysicalMoveOutAuthorizationError,
    PhysicalMoveOutConflictError,
    PhysicalMoveOutInvalidError,
    PhysicalMoveOutNotFoundError,
    PhysicalMoveOutResponse,
    PhysicalMoveOutUnavailableError,
    RecordPhysicalMoveOut,
)
from property_rental.settings import Settings

TEXT = r"^\S(?:[\s\S]*\S)?$"
VERSION = 2_147_483_647
T = TypeVar("T")


class MoveOutFlow(Protocol):
    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]: ...

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordPhysicalMoveOut,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> PhysicalMoveOutResponse: ...


class MoveOutInspectionFlow(Protocol):
    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]: ...

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordMoveOutInspection,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> MoveOutInspectionResponse: ...


class UnavailableMoveOutFlow:
    def __getattr__(self, _: str) -> object:
        raise PhysicalMoveOutUnavailableError("Physical departure persistence is unavailable")


class UnavailableMoveOutInspectionFlow:
    def __getattr__(self, _: str) -> object:
        raise MoveOutInspectionUnavailableError("Inspection persistence is unavailable")


class OccupancyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occupancy_id: UUID
    expected_version: int = Field(strict=True, ge=1, le=VERSION)


class MoveOutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    termination_event_id: UUID
    expected_lease_version: int = Field(strict=True, ge=1, le=VERSION)
    expected_unit_version: int = Field(strict=True, ge=1, le=VERSION)
    actual_move_out_date: date
    unit_condition: Literal["CLEANING", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"]
    occupancies: list[OccupancyInput] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=500, pattern=TEXT)
    authorization_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    evidence_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    supersedes_event_id: UUID | None = None


class FindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    description: str = Field(min_length=1, max_length=1000, pattern=TEXT)
    pet_related: bool = Field(strict=True)


class InspectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspection_id: UUID
    expected_lease_version: int = Field(strict=True, ge=1, le=VERSION)
    inspection_date: date
    result_text: str = Field(min_length=1, max_length=5000, pattern=TEXT)
    authorization_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    evidence_reference: str = Field(min_length=1, max_length=500, pattern=TEXT)
    reason: str = Field(min_length=1, max_length=500, pattern=TEXT)
    findings: list[FindingInput] = Field(max_length=50)
    supersedes_inspection_id: UUID | None = None


def _invoke(call: Callable[[], T]) -> T:
    try:
        return call()
    except (PhysicalMoveOutNotFoundError, MoveOutInspectionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except (PhysicalMoveOutAuthorizationError, MoveOutInspectionAuthorizationError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except (PhysicalMoveOutConflictError, MoveOutInspectionConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except (PhysicalMoveOutInvalidError, MoveOutInspectionInvalidError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except (PhysicalMoveOutUnavailableError, MoveOutInspectionUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _number(request: Request, name: str, default: int, maximum: int, minimum: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or len(raw) > 7 or not minimum <= int(raw) <= maximum:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return int(raw)


def _page(request: Request) -> tuple[int, int]:
    if any(
        key not in {"limit", "offset"} or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return _number(request, "limit", 20, 20, 1), _number(request, "offset", 0, 1_000_000, 0)


def create_move_out_router(
    resolver: ActorResolver,
    move_out: MoveOutFlow,
    inspection: MoveOutInspectionFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["move-out"])

    def actor_for(request: Request) -> AuthenticatedActor:
        actor = resolver(request)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return actor

    def change(request: Request) -> AuthenticatedActor:
        actor = actor_for(request)
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        require_browser_mutation(request, settings)
        return actor

    @router.get("/properties/{property_id}/leases/{lease_id}/move-outs")
    def move_outs(property_id: UUID, lease_id: UUID, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        limit, offset = _page(request)
        page = _invoke(
            lambda: move_out.read(property_id, lease_id, actor=actor, limit=limit, offset=offset)
        )
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/move-outs",
        status_code=status.HTTP_201_CREATED,
    )
    def record_move_out(
        property_id: UUID,
        lease_id: UUID,
        body: MoveOutInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = change(request)
        command = _invoke(
            lambda: RecordPhysicalMoveOut(
                idempotency_key=idempotency_key,
                event_id=body.event_id,
                termination_event_id=body.termination_event_id,
                expected_lease_version=body.expected_lease_version,
                expected_unit_version=body.expected_unit_version,
                actual_move_out_date=body.actual_move_out_date,
                unit_condition=body.unit_condition,
                occupancies=tuple(
                    EndedOccupancy(item.occupancy_id, item.expected_version)
                    for item in body.occupancies
                ),
                reason=body.reason,
                authorization_reference=body.authorization_reference,
                evidence_reference=body.evidence_reference,
                supersedes_event_id=body.supersedes_event_id,
            )
        )
        reply = _invoke(
            lambda: move_out.record(
                property_id, lease_id, command, actor=actor, request_id=request.state.request_id
            )
        )
        return reply.body

    @router.get("/properties/{property_id}/leases/{lease_id}/move-out-inspections")
    def inspections(property_id: UUID, lease_id: UUID, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        limit, offset = _page(request)
        page = _invoke(
            lambda: inspection.read(property_id, lease_id, actor=actor, limit=limit, offset=offset)
        )
        return {"data": page, "meta": {"request_id": request.state.request_id}}

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/move-out-inspections",
        status_code=status.HTTP_201_CREATED,
    )
    def record_inspection(
        property_id: UUID,
        lease_id: UUID,
        body: InspectionInput,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = change(request)
        command = _invoke(
            lambda: RecordMoveOutInspection(
                idempotency_key=idempotency_key,
                inspection_id=body.inspection_id,
                expected_lease_version=body.expected_lease_version,
                inspection_date=body.inspection_date,
                result_text=body.result_text,
                authorization_reference=body.authorization_reference,
                evidence_reference=body.evidence_reference,
                reason=body.reason,
                findings=tuple(
                    InspectionFinding(item.finding_id, item.description, item.pet_related)
                    for item in body.findings
                ),
                supersedes_inspection_id=body.supersedes_inspection_id,
            )
        )
        reply = _invoke(
            lambda: inspection.record(
                property_id, lease_id, command, actor=actor, request_id=request.state.request_id
            )
        )
        return reply.body

    return router
