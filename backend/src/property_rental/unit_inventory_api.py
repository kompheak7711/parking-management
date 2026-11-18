"""Unit inventory with dated history (V1-058 R2b; DL-078 answer 2).

A Unit's inventory is the list of items in it, each with a quantity, an Item type and (V1.1,
DL-115 (I)) an optional place: one of the Unit's own features. Every save is a new numbered
record kept for good; the latest is the current inventory, and each save is written to the
Unit's History. The inventory charges nothing by itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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

MAX_INVENTORY_LINES: Final = 200
MAX_ITEM_QUANTITY: Final = 999
MAX_PLACE_NUMBER: Final = 9

# V1.1 (DL-115 (I)): the items Edit inventory always offers, by Item type code, besides every
# item already used at the Property (decided by Claude under the owner's 2026-10-23 22:30 rule;
# the owner may add others).
STARTER_ITEMS: Final[tuple[tuple[str, str], ...]] = (
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
    ("FURNITURE", "Mirror"),
    ("APPLIANCE", "Air conditioner"),
    ("APPLIANCE", "Refrigerator"),
    ("APPLIANCE", "Washing machine"),
    ("APPLIANCE", "Water heater"),
    ("APPLIANCE", "Fan"),
    ("APPLIANCE", "Cooker"),
    ("APPLIANCE", "Cooker hood"),
    ("APPLIANCE", "Microwave"),
    ("APPLIANCE", "Kettle"),
    ("ELECTRONICS", "Television"),
    ("ELECTRONICS", "Wi-Fi router"),
    ("LINEN", "Bed sheet"),
    ("LINEN", "Pillow"),
    ("LINEN", "Towel"),
    ("KEYS", "Door key"),
    ("KEYS", "Key card"),
    ("KEYS", "Air conditioner remote"),
    ("KEYS", "Television remote"),
)


@dataclass(frozen=True, slots=True)
class UnitInventoryLine:
    """One line: an Item type, a name, an optional place (a Unit feature and which one) and how
    many."""

    item_type_item_id: UUID
    item_name: str
    quantity: int
    where_item_id: UUID | None = None
    where_number: int | None = None


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
    item_type_item_id: UUID
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
            item_type_item_id=UUID(str(line["item_type_item_id"])),
            item_name=str(line["item_name"]),
            quantity=int(line["quantity"]),
            where_item_id=(
                None if line.get("where_item_id") is None else UUID(str(line["where_item_id"]))
            ),
            where_number=(None if line.get("where_number") is None else int(line["where_number"])),
        )
        for line in value
    )


def _line_json(line: UnitInventoryLine) -> dict[str, object]:
    return {
        "item_type_item_id": str(line.item_type_item_id),
        "item_name": line.item_name,
        "where_item_id": None if line.where_item_id is None else str(line.where_item_id),
        "where_number": line.where_number,
        "quantity": line.quantity,
    }


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
                                ELSE app.unit_inventory_items_json(latest.id) END
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
        payload = [_line_json(line) for line in lines]
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT unit_id, property_id, record_number, recorded_at, recorded_by, lines
                    FROM app.record_unit_inventory_items(%s, %s, %s, %s, %s)
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
                types = connection.execute(
                    "SELECT item.code, item.id FROM app.unit_setup_items AS item "
                    "WHERE item.property_id = %s AND item.list_kind = 'ITEM_TYPE' "
                    "AND item.removed_at IS NULL ORDER BY item.sort_order, item.name_en",
                    (property_id,),
                ).fetchall()
                rows = connection.execute(
                    """
                    SELECT line.item_type_item_id, line.item_name
                    FROM app.unit_inventory_items AS line
                    JOIN app.unit_inventory_records AS record ON record.id = line.record_id
                    JOIN app.unit_setup_items AS kind ON kind.id = line.item_type_item_id
                    WHERE record.property_id = %s AND kind.removed_at IS NULL
                    GROUP BY line.item_type_item_id, line.item_name
                    -- The latest spelling of a name wins when capitals differ.
                    ORDER BY max(record.recorded_at) DESC, line.item_name
                    """,
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        return _merge_known(
            [(str(code), UUID(str(item_id))) for code, item_id in types],
            (UnitInventoryItemName(UUID(str(kind)), str(name)) for kind, name in rows),
        )


def _merge_known(
    types: Sequence[tuple[str, UUID]], used: Iterable[UnitInventoryItemName]
) -> tuple[UnitInventoryItemName, ...]:
    """The starter items of the Item types the Property has, and the used ones, one per type
    and name (any capitals), in the Item types' order."""
    by_code = dict(types)
    chosen: dict[tuple[UUID, str], UnitInventoryItemName] = {}
    for code, name in STARTER_ITEMS:
        if code in by_code:
            chosen[(by_code[code], name.lower())] = UnitInventoryItemName(by_code[code], name)
    order = {item_id: index for index, (_, item_id) in enumerate(types)}
    for item in used:
        if item.item_type_item_id in order:
            chosen.setdefault((item.item_type_item_id, item.item_name.lower()), item)
    return tuple(
        sorted(
            chosen.values(),
            key=lambda item: (order[item.item_type_item_id], item.item_name.lower()),
        )
    )


ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class UnitInventoryLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type_item_id: UUID
    item_name: ItemName
    quantity: int = Field(ge=1, le=MAX_ITEM_QUANTITY, strict=True)
    # V1.1 (DL-115 (I)): "Where" is optional: one of the Unit's features and which one.
    where_item_id: UUID | None = None
    where_number: int | None = Field(default=None, ge=1, le=MAX_PLACE_NUMBER, strict=True)

    @model_validator(mode="after")
    def check_place(self) -> UnitInventoryLineInput:
        if (self.where_item_id is None) != (self.where_number is None):
            raise ValueError("a place names the Parking feature and which one")
        return self


class UnitInventoryInput(BaseModel):
    """Edit inventory: every item in the Unit; an item left out is no longer there."""

    model_config = ConfigDict(extra="forbid")

    lines: list[UnitInventoryLineInput] = Field(max_length=MAX_INVENTORY_LINES)

    @field_validator("lines")
    @classmethod
    def check_unique(cls, value: list[UnitInventoryLineInput]) -> list[UnitInventoryLineInput]:
        del cls
        keys = [
            (line.item_type_item_id, line.item_name.lower(), line.where_item_id, line.where_number)
            for line in value
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("an item may appear once for its type and place")
        return value


def _body(inventory: UnitInventory, *, can_manage: bool) -> dict[str, object]:
    counts: dict[str, int] = {}
    for line in inventory.lines:
        kind = str(line.item_type_item_id)
        counts[kind] = counts.get(kind, 0) + line.quantity
    return {
        "unit_id": str(inventory.unit_id),
        "record_number": inventory.record_number,
        "recorded_at": None if inventory.recorded_at is None else inventory.recorded_at.isoformat(),
        "recorded_by": None if inventory.recorded_by is None else str(inventory.recorded_by),
        "lines": [_line_json(line) for line in inventory.lines],
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
                    UnitInventoryLine(
                        line.item_type_item_id,
                        line.item_name,
                        line.quantity,
                        line.where_item_id,
                        line.where_number,
                    )
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
                    {"item_type_item_id": str(item.item_type_item_id), "item_name": item.item_name}
                    for item in items
                ]
            },
            "meta": {"request_id": request.state.request_id},
        }

    return router
