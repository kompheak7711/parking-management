"""Staff bot readings in Utilities (Telegram bots step 4c, DL-176, API-TG-006).

The meter reader types the readings in the Staff bot; they wait here until someone who may
record readings answers them. `GET .../staff-meter-readings` lists the waiting readings, newest
form first, with the last reading and the "look again" flag (`utility_readings.record`).
`POST .../staff-meter-readings/decisions` answers some of them: CONFIRMED saves each as a normal
meter reading on the day it was read (so billing does not change), ASK_AGAIN tells the reader in
the Staff bot which Units to read again, and NOT_USED closes them. A meter that already has a
reading that day is left waiting and named in `already`.

The database functions check the right again; the staff readings are never typed over.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol
from uuid import UUID

import psycopg
from fastapi import APIRouter, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Json,
    ProductUnavailable,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings

UTILITY_READING_RECORD = "utility_readings.record"


class StaffMeterReadingFlow(Protocol):
    def waiting(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def decide(
        self, property_id: UUID, proposal_ids: list[UUID], decision: str, *, actor_id: str
    ) -> Json: ...


class UnavailableStaffMeterReadingFlow:
    def waiting(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def decide(
        self, property_id: UUID, proposal_ids: list[UUID], decision: str, **_: object
    ) -> Json:
        raise ProductUnavailable


class PostgresStaffMeterReadingFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _one(self, query: str, parameters: tuple[object, ...]) -> object:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def waiting(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            "SELECT app.staff_meter_readings_waiting(%s, %s)", (property_id, UUID(actor_id))
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Staff readings are unavailable")
        return [dict(item) for item in found if isinstance(item, dict)]

    def decide(
        self, property_id: UUID, proposal_ids: list[UUID], decision: str, *, actor_id: str
    ) -> Json:
        found = self._one(
            "SELECT app.decide_staff_meter_readings(%s, %s, %s, %s)",
            (property_id, Jsonb([str(item) for item in proposal_ids]), decision, UUID(actor_id)),
        )
        if not isinstance(found, dict):
            raise ProductUnavailable("Staff readings are unavailable")
        return {str(key): value for key, value in found.items()}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]
    decision: Literal["CONFIRMED", "ASK_AGAIN", "NOT_USED"]


def create_staff_meter_readings_router(
    resolver: ActorResolver, flow: StaffMeterReadingFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["utilities"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    @router.get("/staff-meter-readings")
    def staff_meter_readings(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, UTILITY_READING_RECORD, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.waiting(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/staff-meter-readings/decisions")
    def decide_staff_meter_readings(
        property_id: UUID, body: Decision, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, UTILITY_READING_RECORD, property_id)
        require_browser_mutation(request, settings)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(
                request,
                flow.decide(property_id, body.proposal_ids, body.decision, actor_id=actor.actor_id),
            )
        except REFUSED as exc:
            raise _http(exc) from exc

    return router
