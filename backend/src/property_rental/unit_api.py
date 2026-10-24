"""Authenticated, Property-scoped Unit API and immutable Unit timeline."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import UNITS_READ_CAPABILITY
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings
from property_rental.unit import Unit, UnitStatus, UnitType

UNIT_MANAGE_CAPABILITY: Final = "property.manage"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100


class UnitResourceNotFound(LookupError):
    """Raised when a Unit is absent from the requested Property scope."""


class UnitResourceUnavailable(RuntimeError):
    """Raised when Unit persistence cannot be reached."""


class UnitResourceInvalid(ValueError):
    """Raised when Unit source data violates the approved contract."""


class UnitVersionConflict(RuntimeError):
    """Raised when a Unit update does not target the current version."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Unit version precondition was not met")
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class UnitTimelineEvent:
    """A secret-free immutable event summary for one Unit."""

    event_id: UUID
    occurred_at: datetime
    actor_id: UUID
    action: str
    entity_type: str
    reason: str
    previous_state: object | None
    resulting_state: object | None
    correlation_id: UUID
    outcome: str


@dataclass(frozen=True, slots=True)
class UnitPage:
    """One stable keyset page of Units."""

    items: tuple[Unit, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class UnitTimelinePage:
    """One stable keyset page of Unit events."""

    items: tuple[UnitTimelineEvent, ...]
    next_cursor: str | None


class UnitResourceFlow(Protocol):
    """Application operations required by Unit routes."""

    def list(
        self,
        property_id: UUID,
        *,
        unit_status: UnitStatus | None,
        attention: bool | None,
        limit: int,
        cursor: str | None,
    ) -> UnitPage: ...

    def get(self, unit_id: UUID) -> Unit: ...

    def create(
        self,
        property_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        actor_id: str,
    ) -> Unit: ...

    def patch(
        self,
        unit_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        expected_version: int,
        actor_id: str,
    ) -> Unit: ...

    def timeline(
        self,
        unit_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> UnitTimelinePage: ...


class UnavailableUnitResourceFlow:
    """Fail closed until Unit persistence is configured."""

    def _unavailable(self) -> None:
        raise UnitResourceUnavailable("Unit persistence is unavailable")

    def list(
        self,
        property_id: UUID,
        *,
        unit_status: UnitStatus | None,
        attention: bool | None,
        limit: int,
        cursor: str | None,
    ) -> UnitPage:
        del property_id, unit_status, attention, limit, cursor
        self._unavailable()
        raise AssertionError

    def get(self, unit_id: UUID) -> Unit:
        del unit_id
        self._unavailable()
        raise AssertionError

    def create(
        self,
        property_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        actor_id: str,
    ) -> Unit:
        del property_id, unit_number, floor, unit_type, unit_status, actor_id
        self._unavailable()
        raise AssertionError

    def patch(
        self,
        unit_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        expected_version: int,
        actor_id: str,
    ) -> Unit:
        del unit_id, unit_number, floor, unit_type, unit_status, expected_version, actor_id
        self._unavailable()
        raise AssertionError

    def timeline(
        self,
        unit_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> UnitTimelinePage:
        del unit_id, limit, cursor
        self._unavailable()
        raise AssertionError


def _encode_cursor(values: tuple[str, str]) -> str:
    payload = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[str, UUID] | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        return str(decoded[0]), UUID(str(decoded[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise UnitResourceInvalid("cursor is invalid") from exc


def _unit(row: tuple[object, ...]) -> Unit:
    return Unit(
        unit_id=UUID(str(row[0])),
        property_id=UUID(str(row[1])),
        unit_number=str(row[2]),
        floor=str(row[3]),
        unit_type=UnitType(str(row[4])),
        status=UnitStatus(str(row[5])),
        version=int(str(row[6])),
    )


class PostgresUnitResourceFlow:
    """Versioned Unit commands and bounded queries over PostgreSQL."""

    _columns: Final = "id, property_id, unit_number, floor, unit_type, status, version"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list(
        self,
        property_id: UUID,
        *,
        unit_status: UnitStatus | None,
        attention: bool | None,
        limit: int,
        cursor: str | None,
    ) -> UnitPage:
        decoded = _decode_cursor(cursor)
        clauses = ["property_id = %s"]
        parameters: list[object] = [property_id]
        if unit_status is not None:
            clauses.append("status = %s")
            parameters.append(unit_status.value)
        if attention is not None:
            expression = "status IN ('UNDER_MAINTENANCE', 'CLEANING', 'OUT_OF_SERVICE')"
            clauses.append(expression if attention else f"NOT ({expression})")
        if decoded is not None:
            clauses.append("(unit_number, id) > (%s, %s)")
            parameters.extend(decoded)
        parameters.append(limit + 1)
        query = (
            f"SELECT {self._columns} FROM app.units WHERE "
            + " AND ".join(clauses)
            + " ORDER BY unit_number, id LIMIT %s"
        )
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(query, tuple(parameters)).fetchall()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Unit persistence is unavailable") from exc
        units = tuple(_unit(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and units:
            last = units[-1]
            next_cursor = _encode_cursor((last.unit_number, str(last.unit_id)))
        return UnitPage(units, next_cursor)

    def get(self, unit_id: UUID) -> Unit:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"SELECT {self._columns} FROM app.units WHERE id = %s",
                    (unit_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Unit persistence is unavailable") from exc
        if row is None:
            raise UnitResourceNotFound("Unit was not found")
        return _unit(row)

    @staticmethod
    def _state(unit: Unit) -> dict[str, object]:
        return {
            "unit_id": str(unit.unit_id),
            "property_id": str(unit.property_id),
            "unit_number": unit.unit_number,
            "floor": unit.floor,
            "unit_type": unit.unit_type.value,
            "status": unit.status.value,
            "version": unit.version,
        }

    @staticmethod
    def _audit(
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        unit: Unit,
        actor_id: str,
        action: str,
        previous_state: dict[str, object] | None,
    ) -> None:
        event_id = uuid4()
        connection.execute(
            """
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, property_id, previous_state, resulting_state,
                correlation_id, source, outcome, unit_id
            ) VALUES (
                %s, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                %s, %s, 'unit', %s, %s, %s, %s, %s, %s, 'API', 'SUCCEEDED', %s
            )
            """,
            (
                event_id,
                UUID(actor_id),
                action,
                unit.unit_id,
                "Unit source data changed through the authorized Unit API",
                unit.property_id,
                None if previous_state is None else Jsonb(previous_state),
                Jsonb(PostgresUnitResourceFlow._state(unit)),
                event_id,
                unit.unit_id,
            ),
        )

    def create(
        self,
        property_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        actor_id: str,
    ) -> Unit:
        unit_id = uuid4()
        try:
            candidate = Unit(
                unit_id,
                property_id,
                unit_number.strip(),
                floor.strip(),
                unit_type,
                unit_status,
            )
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT * FROM app.create_unit(%s, %s, %s, %s, %s, %s, %s)",
                    (
                        candidate.unit_id,
                        candidate.property_id,
                        candidate.unit_number,
                        candidate.floor,
                        candidate.unit_type.value,
                        candidate.status.value,
                        UUID(actor_id),
                    ),
                ).fetchone()
                if row is None:
                    raise UnitResourceUnavailable("Unit creation returned no result")
                created = _unit(row)
                self._audit(
                    connection,
                    unit=created,
                    actor_id=actor_id,
                    action="unit.created",
                    previous_state=None,
                )
            return created
        except (ValueError, psycopg.errors.CheckViolation) as exc:
            raise UnitResourceInvalid("Unit source fields are invalid") from exc
        except psycopg.errors.UniqueViolation as exc:
            raise UnitResourceInvalid("Unit identity or number already exists") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Unit persistence is unavailable") from exc

    def patch(
        self,
        unit_id: UUID,
        *,
        unit_number: str,
        floor: str,
        unit_type: UnitType,
        unit_status: UnitStatus,
        expected_version: int,
        actor_id: str,
    ) -> Unit:
        try:
            with psycopg.connect(self._database_url) as connection:
                current_row = connection.execute(
                    f"SELECT {self._columns} FROM app.units WHERE id = %s",
                    (unit_id,),
                ).fetchone()
                if current_row is None:
                    raise UnitResourceNotFound("Unit was not found")
                current = _unit(current_row)
                if current.version != expected_version:
                    raise UnitVersionConflict(current.version)
                Unit(
                    unit_id,
                    current.property_id,
                    unit_number.strip(),
                    floor.strip(),
                    unit_type,
                    unit_status,
                    expected_version + 1,
                )
                row = connection.execute(
                    "SELECT * FROM app.update_unit(%s, %s, %s, %s, %s, %s, %s)",
                    (
                        unit_id,
                        unit_number.strip(),
                        floor.strip(),
                        unit_type.value,
                        unit_status.value,
                        expected_version,
                        UUID(actor_id),
                    ),
                ).fetchone()
                if row is None:
                    latest = connection.execute(
                        "SELECT version FROM app.units WHERE id = %s", (unit_id,)
                    ).fetchone()
                    if latest is None:
                        raise UnitResourceNotFound("Unit was not found")
                    raise UnitVersionConflict(int(str(latest[0])))
                updated = _unit(row)
                self._audit(
                    connection,
                    unit=updated,
                    actor_id=actor_id,
                    action="unit.updated",
                    previous_state=self._state(current),
                )
            return updated
        except (UnitResourceNotFound, UnitVersionConflict):
            raise
        except (ValueError, psycopg.errors.CheckViolation) as exc:
            raise UnitResourceInvalid("Unit source fields are invalid") from exc
        except psycopg.errors.UniqueViolation as exc:
            raise UnitResourceInvalid("Unit identity or number already exists") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Unit persistence is unavailable") from exc

    def timeline(
        self,
        unit_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> UnitTimelinePage:
        decoded = _decode_cursor(cursor)
        parameters: list[object] = [unit_id]
        cursor_clause = ""
        if decoded is not None:
            cursor_clause = "AND (occurred_at, id) < (%s::timestamptz, %s)"
            parameters.extend(decoded)
        parameters.append(limit + 1)
        try:
            with psycopg.connect(self._database_url) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM app.units WHERE id = %s", (unit_id,)
                ).fetchone()
                if exists is None:
                    raise UnitResourceNotFound("Unit was not found")
                rows = connection.execute(
                    f"""
                    SELECT id, occurred_at, actor_id, action, entity_type, reason,
                           previous_state, resulting_state, correlation_id, outcome
                    FROM app.audit_events
                    WHERE unit_id = %s {cursor_clause}
                    ORDER BY occurred_at DESC, id DESC
                    LIMIT %s
                    """,
                    tuple(parameters),
                ).fetchall()
        except UnitResourceNotFound:
            raise
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Unit persistence is unavailable") from exc
        events = tuple(
            UnitTimelineEvent(
                event_id=UUID(str(row[0])),
                occurred_at=row[1],
                actor_id=UUID(str(row[2])),
                action=str(row[3]),
                entity_type=str(row[4]),
                reason=str(row[5]),
                previous_state=row[6],
                resulting_state=row[7],
                correlation_id=UUID(str(row[8])),
                outcome=str(row[9]),
            )
            for row in rows[:limit]
        )
        next_cursor = None
        if len(rows) > limit and events:
            last = events[-1]
            next_cursor = _encode_cursor((last.occurred_at.isoformat(), str(last.event_id)))
        return UnitTimelinePage(events, next_cursor)


class UnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: str = Field(min_length=1, max_length=100)
    floor: str = Field(min_length=1, max_length=100)
    unit_type: UnitType
    status: UnitStatus = UnitStatus.VACANT


class UnitPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: str | None = Field(default=None, min_length=1, max_length=100)
    floor: str | None = Field(default=None, min_length=1, max_length=100)
    unit_type: UnitType | None = None
    status: UnitStatus | None = None


def _require_actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _can_manage(actor: AuthenticatedActor, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(
            capability=UNIT_MANAGE_CAPABILITY,
            property_id=str(property_id),
        ),
    )


def _require_manager(actor: AuthenticatedActor, property_id: UUID) -> None:
    if not _can_manage(actor, property_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _require_reader(actor: AuthenticatedActor, property_id: UUID | None) -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): `units.read` for the Property.
    Without a Property (a Unit not read yet), any `units.read` grant, so a person without it
    learns nothing about which Units exist."""
    if property_id is not None:
        allowed = is_authorized(
            actor,
            AuthorizationRequirement(
                capability=UNITS_READ_CAPABILITY, property_id=str(property_id)
            ),
        )
    else:
        allowed = any(
            grant.capability == UNITS_READ_CAPABILITY for grant in actor.capability_grants
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def _expected_version(value: str | None, current: int) -> int:
    if value is None:
        raise UnitVersionConflict(current)
    candidate = value.strip()
    if candidate.startswith("W/"):
        raise UnitVersionConflict(current)
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    try:
        parsed = int(candidate)
    except ValueError as exc:
        raise UnitVersionConflict(current) from exc
    if parsed != current:
        raise UnitVersionConflict(current)
    return parsed


def _alerts(unit: Unit) -> list[str]:
    return (
        [unit.status.value]
        if unit.status
        in {UnitStatus.UNDER_MAINTENANCE, UnitStatus.CLEANING, UnitStatus.OUT_OF_SERVICE}
        else []
    )


def _body(unit: Unit) -> dict[str, object]:
    return {
        "unit_id": str(unit.unit_id),
        "property_id": str(unit.property_id),
        "unit_number": unit.unit_number,
        "floor": unit.floor,
        "unit_type": unit.unit_type.value,
        "status": unit.status.value,
        "version": unit.version,
        "current_reservation": None,
        "current_lease": None,
        "current_occupancy": None,
        "active_meter_summary": None,
        "operational_alerts": _alerts(unit),
    }


def create_unit_router(
    resolver: ActorResolver, flow: UnitResourceFlow, settings: Settings
) -> APIRouter:
    """Create Unit collection, detail, mutation, and timeline routes."""
    router = APIRouter(tags=["units"])

    def get_unit_or_http(unit_id: UUID) -> Unit:
        try:
            return flow.get(unit_id)
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    @router.get("/properties/{property_id}/units")
    def list_units(
        property_id: UUID,
        request: Request,
        unit_status: Annotated[UnitStatus | None, Query(alias="status")] = None,
        attention: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_reader(actor, property_id)
        try:
            page = flow.list(
                property_id,
                unit_status=unit_status,
                attention=attention,
                limit=limit,
                cursor=cursor,
            )
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return {
            "data": {
                "items": [_body(unit) for unit in page.items],
                "next_cursor": page.next_cursor,
                "can_manage": _can_manage(actor, property_id),
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/properties/{property_id}/units", status_code=status.HTTP_201_CREATED)
    def create_unit(
        property_id: UUID,
        command: UnitCreate,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_manager(actor, property_id)
        require_browser_mutation(request, settings)
        try:
            unit = flow.create(
                property_id,
                unit_number=command.unit_number,
                floor=command.floor,
                unit_type=command.unit_type,
                unit_status=command.status,
                actor_id=actor.actor_id,
            )
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{unit.version}"'
        return {"data": _body(unit), "meta": {"request_id": request.state.request_id}}

    @router.get("/units/{unit_id}")
    def get_unit(unit_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_reader(actor, None)
        unit = get_unit_or_http(unit_id)
        _require_reader(actor, unit.property_id)
        response.headers["ETag"] = f'"{unit.version}"'
        body = _body(unit)
        body["can_manage"] = _can_manage(actor, unit.property_id)
        return {"data": body, "meta": {"request_id": request.state.request_id}}

    @router.patch("/units/{unit_id}")
    def patch_unit(
        unit_id: UUID,
        patch: UnitPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        current = get_unit_or_http(unit_id)
        _require_manager(actor, current.property_id)
        require_browser_mutation(request, settings)
        if not patch.model_fields_set:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if any(getattr(patch, field_name) is None for field_name in patch.model_fields_set):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        expected = _expected_version(if_match, current.version)
        try:
            unit = flow.patch(
                unit_id,
                unit_number=patch.unit_number or current.unit_number,
                floor=patch.floor or current.floor,
                unit_type=patch.unit_type or current.unit_type,
                unit_status=patch.status or current.status,
                expected_version=expected,
                actor_id=actor.actor_id,
            )
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{unit.version}"'
        return {"data": _body(unit), "meta": {"request_id": request.state.request_id}}

    @router.get("/units/{unit_id}/timeline")
    def unit_timeline(
        unit_id: UUID,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_reader(actor, None)
        _require_reader(actor, get_unit_or_http(unit_id).property_id)
        try:
            page = flow.timeline(unit_id, limit=limit, cursor=cursor)
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return {
            "data": {
                "items": [
                    {
                        **asdict(event),
                        "event_id": str(event.event_id),
                        "occurred_at": event.occurred_at.isoformat(),
                        "actor_id": str(event.actor_id),
                        "correlation_id": str(event.correlation_id),
                    }
                    for event in page.items
                ],
                "next_cursor": page.next_cursor,
            },
            "meta": {"request_id": request.state.request_id},
        }

    return router
