"""Unit inventory with dated history (V1-058 R2b; DL-078 answer 2).

A Unit's inventory is the list of items in it, each with a quantity, grouped as Furniture,
Appliances, Kitchen and Bathroom. Every save is a new numbered record kept for good; the latest is
the current inventory, and each save is written to the Unit's History. The inventory charges
nothing by itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.settings import Settings
from property_rental.unit_api import (
    UnitResourceInvalid,
    UnitResourceNotFound,
    UnitResourceUnavailable,
    UnitVersionConflict,
    _can_manage,
    _expected_version,
    _require_actor,
    _require_manager,
    _require_reader,
)

UnitInventoryGroup = Literal["FURNITURE", "APPLIANCES", "KITCHEN", "BATHROOM"]
UNIT_INVENTORY_GROUPS: Final[tuple[UnitInventoryGroup, ...]] = (
    "FURNITURE",
    "APPLIANCES",
    "KITCHEN",
    "BATHROOM",
)
MAX_INVENTORY_LINES: Final = 200
MAX_ITEM_QUANTITY: Final = 999

# The items Edit inventory always offers, besides every item already used at the Property
# (decided by Claude under the owner's 2026-10-23 22:30 rule; the owner may add others).
STARTER_ITEMS: Final[tuple[tuple[UnitInventoryGroup, str], ...]] = (
    ("FURNITURE", "Bed"),
    ("FURNITURE", "Mattress"),
    ("FURNITURE", "Wardrobe"),
    ("FURNITURE", "Bedside table"),
    ("FURNITURE", "Sofa"),
    ("FURNITURE", "Coffee table"),
    ("FURNITURE", "Dining table"),
    ("FURNITURE", "Dining chair"),
    ("FURNITURE", "Desk"),
    ("FURNITURE", "Desk chair"),
    ("FURNITURE", "Curtains"),
    ("APPLIANCES", "Air conditioner"),
    ("APPLIANCES", "Refrigerator"),
    ("APPLIANCES", "Washing machine"),
    ("APPLIANCES", "Television"),
    ("APPLIANCES", "Water heater"),
    ("APPLIANCES", "Fan"),
    ("KITCHEN", "Cooker"),
    ("KITCHEN", "Cooker hood"),
    ("KITCHEN", "Microwave"),
    ("KITCHEN", "Kettle"),
    ("KITCHEN", "Kitchen sink"),
    ("BATHROOM", "Shower"),
    ("BATHROOM", "Toilet"),
    ("BATHROOM", "Washbasin"),
    ("BATHROOM", "Mirror"),
    ("BATHROOM", "Towel rail"),
)


@dataclass(frozen=True, slots=True)
class UnitInventoryLine:
    item_group: str
    item_name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class UnitInventory:
    """The current inventory of one Unit; record number 0 means nothing was saved yet."""

    unit_id: UUID
    property_id: UUID
    record_number: int
    recorded_at: datetime | None
    recorded_by: UUID | None
    lines: tuple[UnitInventoryLine, ...]


@dataclass(frozen=True, slots=True)
class UnitInventoryItemName:
    item_group: str
    item_name: str


class UnitInventoryFlow(Protocol):
    def current(self, unit_id: UUID) -> UnitInventory: ...

    def record(
        self,
        unit_id: UUID,
        *,
        lines: Sequence[UnitInventoryLine],
        expected_record_number: int,
        actor_id: str,
    ) -> UnitInventory: ...

    def known_items(self, property_id: UUID) -> tuple[UnitInventoryItemName, ...]: ...


class UnavailableUnitInventoryFlow:
    """Fail closed until Unit persistence is configured."""

    def current(self, unit_id: UUID) -> UnitInventory:
        del unit_id
        raise UnitResourceUnavailable("Parking persistence is unavailable")

    def record(
        self,
        unit_id: UUID,
        *,
        lines: Sequence[UnitInventoryLine],
        expected_record_number: int,
        actor_id: str,
    ) -> UnitInventory:
        del unit_id, lines, expected_record_number, actor_id
        raise UnitResourceUnavailable("Parking persistence is unavailable")

    def known_items(self, property_id: UUID) -> tuple[UnitInventoryItemName, ...]:
        del property_id
        raise UnitResourceUnavailable("Parking persistence is unavailable")


def _lines(value: object) -> tuple[UnitInventoryLine, ...]:
    if not isinstance(value, list):
        raise UnitResourceUnavailable("Parking inventory lines are unreadable")
    return tuple(
        UnitInventoryLine(
            item_group=str(line["item_group"]),
            item_name=str(line["item_name"]),
            quantity=int(line["quantity"]),
        )
        for line in value
    )


class PostgresUnitInventoryFlow:
    """Reads over SELECT grants; saves only through `app.record_unit_inventory`."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def current(self, unit_id: UUID) -> UnitInventory:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT unit.id, unit.property_id, latest.record_number, latest.recorded_at,
                           latest.recorded_by,
                           CASE WHEN latest.id IS NULL THEN '[]'::jsonb
                                ELSE app.unit_inventory_lines_json(latest.id) END
                    FROM app.units AS unit
                    LEFT JOIN LATERAL (
                        SELECT record.id, record.record_number, record.recorded_at,
                               record.recorded_by
                        FROM app.unit_inventory_records AS record
                        WHERE record.unit_id = unit.id
                        ORDER BY record.record_number DESC
                        LIMIT 1
                    ) AS latest ON true
                    WHERE unit.id = %s
                    """,
                    (unit_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        if row is None:
            raise UnitResourceNotFound("Parking was not found")
        return UnitInventory(
            unit_id=UUID(str(row[0])),
            property_id=UUID(str(row[1])),
            record_number=0 if row[2] is None else int(str(row[2])),
            recorded_at=row[3] if isinstance(row[3], datetime) else None,
            recorded_by=None if row[4] is None else UUID(str(row[4])),
            lines=_lines(row[5]),
        )

    def record(
        self,
        unit_id: UUID,
        *,
        lines: Sequence[UnitInventoryLine],
        expected_record_number: int,
        actor_id: str,
    ) -> UnitInventory:
        payload = [
            {"item_group": line.item_group, "item_name": line.item_name, "quantity": line.quantity}
            for line in lines
        ]
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT unit_id, property_id, record_number, recorded_at, recorded_by, lines
                    FROM app.record_unit_inventory(%s, %s, %s, %s, %s)
                    """,
                    (uuid4(), unit_id, expected_record_number, Jsonb(payload), UUID(actor_id)),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise UnitResourceNotFound("Parking was not found") from exc
            if exc.sqlstate in {"22023", "23502", "23505", "23514", "22P02"}:
                raise UnitResourceInvalid("Parking inventory is invalid") from exc
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        if row is None:
            raise UnitVersionConflict(self.current(unit_id).record_number)
        return UnitInventory(
            unit_id=UUID(str(row[0])),
            property_id=UUID(str(row[1])),
            record_number=int(str(row[2])),
            recorded_at=row[3] if isinstance(row[3], datetime) else None,
            recorded_by=UUID(str(row[4])),
            lines=_lines(row[5]),
        )

    def known_items(self, property_id: UUID) -> tuple[UnitInventoryItemName, ...]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT line.item_group, line.item_name
                    FROM app.unit_inventory_lines AS line
                    JOIN app.unit_inventory_records AS record ON record.id = line.record_id
                    WHERE record.property_id = %s
                    GROUP BY line.item_group, line.item_name
                    -- The latest spelling of a name wins when capitals differ.
                    ORDER BY max(record.recorded_at) DESC, line.item_name
                    """,
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        return _merge_known(UnitInventoryItemName(str(group), str(name)) for group, name in rows)


def _merge_known(used: Iterable[UnitInventoryItemName]) -> tuple[UnitInventoryItemName, ...]:
    """The starter items and the used ones, one per group and name (any capitals)."""
    chosen: dict[tuple[str, str], UnitInventoryItemName] = {}
    for group, name in STARTER_ITEMS:
        chosen[(group, name.lower())] = UnitInventoryItemName(group, name)
    for item in used:
        chosen.setdefault((item.item_group, item.item_name.lower()), item)
    order: dict[str, int] = {group: index for index, group in enumerate(UNIT_INVENTORY_GROUPS)}
    return tuple(
        sorted(
            chosen.values(),
            key=lambda item: (order.get(item.item_group, len(order)), item.item_name.lower()),
        )
    )


ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class UnitInventoryLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_group: UnitInventoryGroup
    item_name: ItemName
    quantity: int = Field(ge=1, le=MAX_ITEM_QUANTITY, strict=True)


class UnitInventoryInput(BaseModel):
    """Edit inventory: every item in the Unit; an item left out is no longer there."""

    model_config = ConfigDict(extra="forbid")

    lines: list[UnitInventoryLineInput] = Field(max_length=MAX_INVENTORY_LINES)

    @field_validator("lines")
    @classmethod
    def check_unique(cls, value: list[UnitInventoryLineInput]) -> list[UnitInventoryLineInput]:
        del cls
        keys = [(line.item_group, line.item_name.lower()) for line in value]
        if len(set(keys)) != len(keys):
            raise ValueError("an item may appear once in its group")
        return value


def _body(inventory: UnitInventory, *, can_manage: bool) -> dict[str, object]:
    counts = {
        group: sum(line.quantity for line in inventory.lines if line.item_group == group)
        for group in UNIT_INVENTORY_GROUPS
    }
    return {
        "unit_id": str(inventory.unit_id),
        "record_number": inventory.record_number,
        "recorded_at": None if inventory.recorded_at is None else inventory.recorded_at.isoformat(),
        "recorded_by": None if inventory.recorded_by is None else str(inventory.recorded_by),
        "lines": [
            {"item_group": line.item_group, "item_name": line.item_name, "quantity": line.quantity}
            for line in inventory.lines
        ],
        "counts": counts,
        "can_manage": can_manage,
    }


def create_unit_inventory_router(
    resolver: ActorResolver, flow: UnitInventoryFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(tags=["units"])

    def current_or_http(unit_id: UUID) -> UnitInventory:
        try:
            return flow.current(unit_id)
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    @router.get("/units/{unit_id}/inventory")
    def unit_inventory(unit_id: UUID, request: Request, response: Response) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        _require_reader(actor, None)
        inventory = current_or_http(unit_id)
        _require_reader(actor, inventory.property_id)
        response.headers["ETag"] = f'"{inventory.record_number}"'
        return {
            "data": _body(inventory, can_manage=_can_manage(actor, inventory.property_id)),
            "meta": {"request_id": request.state.request_id},
        }

    @router.put("/units/{unit_id}/inventory")
    def save_unit_inventory(
        unit_id: UUID,
        command: UnitInventoryInput,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        current = current_or_http(unit_id)
        _require_manager(actor, current.property_id)
        require_browser_mutation(request, settings)
        expected = _expected_version(if_match, current.record_number)
        try:
            inventory = flow.record(
                unit_id,
                lines=[
                    UnitInventoryLine(line.item_group, line.item_name, line.quantity)
                    for line in command.lines
                ],
                expected_record_number=expected,
                actor_id=actor.actor_id,
            )
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{inventory.record_number}"'
        return {
            "data": _body(inventory, can_manage=True),
            "meta": {"request_id": request.state.request_id},
        }

    @router.get("/properties/{property_id}/unit-inventory-items")
    def unit_inventory_items(property_id: UUID, request: Request) -> dict[str, object]:
        """The item names Edit inventory offers: the starter items and those already used."""
        actor = _require_actor(request, resolver)
        _require_reader(actor, property_id)
        try:
            items = flow.known_items(property_id)
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return {
            "data": {
                "items": [
                    {"item_group": item.item_group, "item_name": item.item_name} for item in items
                ]
            },
            "meta": {"request_id": request.state.request_id},
        }

    return router
