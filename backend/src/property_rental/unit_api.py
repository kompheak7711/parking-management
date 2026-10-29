"""Authenticated, Property-scoped Unit API and immutable Unit timeline."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Final, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY, UNITS_READ_CAPABILITY
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings
from property_rental.unit import (
    UNIT_MAX_ROOMS,
    UNIT_NOTES_MAX_LENGTH,
    UNIT_SETUP_CODE,
    Unit,
    UnitStatus,
    unit_from_row,
)

UNIT_MANAGE_CAPABILITY: Final = "property.manage"
# DL-075 answer 10 and DL-074 answer 2: the Owner or a user ticked for Settings access.
UNIT_SETUP_MANAGE_CAPABILITY: Final = SETTINGS_MANAGE_CAPABILITY
UnitSetupListKind = Literal["FLOOR", "UNIT_TYPE", "VIEW", "KITCHEN", "ROOM_FEATURE"]
UNIT_SETUP_LIST_KINDS: Final[tuple[UnitSetupListKind, ...]] = (
    "FLOOR",
    "UNIT_TYPE",
    "VIEW",
    "KITCHEN",
    "ROOM_FEATURE",
)
MAX_ROOM_FEATURES: Final = 50
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100


class UnitResourceNotFound(LookupError):
    """Raised when a Unit is absent from the requested Property scope."""


class UnitResourceUnavailable(RuntimeError):
    """Raised when Unit persistence cannot be reached."""


class UnitResourceInvalid(ValueError):
    """Raised when Unit source data violates the approved contract."""


class UnitSetupItemInUse(RuntimeError):
    """Raised when a list item that a Unit uses would be removed (DL-075 answer 10)."""


class UnitVersionConflict(RuntimeError):
    """Raised when a Unit update does not target the current version."""

    def __init__(self, current_version: int) -> None:
        super().__init__("the Parking version precondition was not met")
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
    # Parking Step 3: the display name of who did it, for the History line.
    actor_name: str | None = None


@dataclass(frozen=True, slots=True)
class UnitDetails:
    """DL-078 answer 1: the details a Unit form saves besides its Floor, Type and status."""

    size_square_metres: Decimal | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    view_item_id: UUID | None = None
    kitchen_item_id: UUID | None = None
    notes: str | None = None
    room_feature_ids: tuple[UUID, ...] = ()

    @classmethod
    def of(cls, unit: Unit) -> UnitDetails:
        return cls(
            unit.size_square_metres,
            unit.bedrooms,
            unit.bathrooms,
            unit.view_item_id,
            unit.kitchen_item_id,
            unit.notes,
            unit.room_feature_ids,
        )


@dataclass(frozen=True, slots=True)
class UnitSetupItem:
    """One item of a Unit setup list (DL-075 answer 10)."""

    item_id: UUID
    property_id: UUID
    list_kind: str
    code: str
    name_en: str
    name_km: str | None
    sort_order: int
    removed: bool
    version: int
    in_use: bool = False


@dataclass(frozen=True, slots=True)
class UnitSetupLists:
    items: tuple[UnitSetupItem, ...] = field(default_factory=tuple)


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
        floor_item_id: UUID,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        actor_id: str,
    ) -> Unit: ...

    def patch(
        self,
        unit_id: UUID,
        *,
        floor_item_id: UUID | None,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        expected_version: int,
        actor_id: str,
        reason: str | None = None,
    ) -> Unit: ...

    def set_rent_terms(
        self,
        unit_id: UUID,
        *,
        default_monthly_rent_usd_cents: int | None,
        required_service_ids: tuple[UUID, ...],
        expected_version: int,
        actor_id: str,
        reason: str,
    ) -> Unit: ...

    def timeline(
        self,
        unit_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> UnitTimelinePage: ...

    def setup_lists(self, property_id: UUID, *, include_removed: bool) -> UnitSetupLists: ...

    def create_setup_item(
        self,
        property_id: UUID,
        *,
        list_kind: str,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        actor_id: str,
    ) -> UnitSetupItem: ...

    def get_setup_item(self, item_id: UUID) -> UnitSetupItem: ...

    def update_setup_item(
        self,
        item_id: UUID,
        *,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        expected_version: int,
        actor_id: str,
    ) -> UnitSetupItem: ...

    def remove_setup_item(
        self, item_id: UUID, *, expected_version: int, actor_id: str
    ) -> UnitSetupItem: ...


class UnavailableUnitResourceFlow:
    """Fail closed until Unit persistence is configured."""

    def _unavailable(self) -> None:
        raise UnitResourceUnavailable("Parking persistence is unavailable")

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
        floor_item_id: UUID,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        actor_id: str,
    ) -> Unit:
        del property_id, unit_number, floor_item_id, unit_type, unit_status, details, actor_id
        self._unavailable()
        raise AssertionError

    def patch(
        self,
        unit_id: UUID,
        *,
        floor_item_id: UUID | None,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        expected_version: int,
        actor_id: str,
        reason: str | None = None,
    ) -> Unit:
        del unit_id, floor_item_id, unit_type, unit_status, details, expected_version, actor_id
        del reason
        self._unavailable()
        raise AssertionError

    def set_rent_terms(
        self,
        unit_id: UUID,
        *,
        default_monthly_rent_usd_cents: int | None,
        required_service_ids: tuple[UUID, ...],
        expected_version: int,
        actor_id: str,
        reason: str,
    ) -> Unit:
        del unit_id, default_monthly_rent_usd_cents, required_service_ids, expected_version
        del actor_id, reason
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

    def setup_lists(self, property_id: UUID, *, include_removed: bool) -> UnitSetupLists:
        del property_id, include_removed
        self._unavailable()
        raise AssertionError

    def create_setup_item(
        self,
        property_id: UUID,
        *,
        list_kind: str,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        actor_id: str,
    ) -> UnitSetupItem:
        del property_id, list_kind, name_en, name_km, sort_order, actor_id
        self._unavailable()
        raise AssertionError

    def get_setup_item(self, item_id: UUID) -> UnitSetupItem:
        del item_id
        self._unavailable()
        raise AssertionError

    def update_setup_item(
        self,
        item_id: UUID,
        *,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        expected_version: int,
        actor_id: str,
    ) -> UnitSetupItem:
        del item_id, name_en, name_km, sort_order, expected_version, actor_id
        self._unavailable()
        raise AssertionError

    def remove_setup_item(
        self, item_id: UUID, *, expected_version: int, actor_id: str
    ) -> UnitSetupItem:
        del item_id, expected_version, actor_id
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
    return unit_from_row(row)


def _setup_item(row: tuple[object, ...]) -> UnitSetupItem:
    return UnitSetupItem(
        item_id=UUID(str(row[0])),
        property_id=UUID(str(row[1])),
        list_kind=str(row[2]),
        code=str(row[3]),
        name_en=str(row[4]),
        name_km=None if row[5] is None else str(row[5]),
        sort_order=int(str(row[6])),
        removed=row[7] is not None,
        version=int(str(row[8])),
        in_use=bool(row[9]) if len(row) > 9 else False,
    )


def _size_json(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


# V1-061 (DL-110): a Unit read with its default Rent and required Services.
UNIT_SELECT: Final = (
    "SELECT detail.*, terms.default_monthly_rent_usd_cents, terms.required_service_ids "
    "FROM app.unit_with_details(%s) AS detail "
    "CROSS JOIN LATERAL app.unit_rent_terms(detail.id) AS terms"
)


class PostgresUnitResourceFlow:
    """Versioned Unit commands and bounded queries over PostgreSQL."""

    _setup_columns: Final = (
        "item.id, item.property_id, item.list_kind, item.code, item.name_en, item.name_km, "
        "item.sort_order, item.removed_at, item.version"
    )

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
        clauses = ["unit.property_id = %s"]
        parameters: list[object] = [property_id]
        if unit_status is not None:
            clauses.append("unit.status = %s")
            parameters.append(unit_status.value)
        if attention is not None:
            expression = "unit.status IN ('UNDER_MAINTENANCE', 'CLEANING', 'OUT_OF_SERVICE')"
            clauses.append(expression if attention else f"NOT ({expression})")
        if decoded is not None:
            clauses.append("(unit.unit_number, unit.id) > (%s, %s)")
            parameters.extend(decoded)
        parameters.append(limit + 1)
        query = (
            "SELECT detail.*, terms.default_monthly_rent_usd_cents, terms.required_service_ids "
            "FROM app.units AS unit "
            "CROSS JOIN LATERAL app.unit_with_details(unit.id) AS detail "
            "CROSS JOIN LATERAL app.unit_rent_terms(unit.id) AS terms WHERE "
            + " AND ".join(clauses)
            + " ORDER BY unit.unit_number, unit.id LIMIT %s"
        )
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(query, tuple(parameters)).fetchall()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        units = tuple(_unit(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and units:
            last = units[-1]
            next_cursor = _encode_cursor((last.unit_number, str(last.unit_id)))
        return UnitPage(units, next_cursor)

    def get(self, unit_id: UUID) -> Unit:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
        if row is None:
            raise UnitResourceNotFound("Parking was not found")
        return _unit(row)

    @staticmethod
    def _state(unit: Unit) -> dict[str, object]:
        return {
            "unit_id": str(unit.unit_id),
            "property_id": str(unit.property_id),
            "unit_number": unit.unit_number,
            "floor": unit.floor,
            "unit_type": unit.unit_type,
            "status": unit.status.value,
            "version": unit.version,
            "floor_item_id": None if unit.floor_item_id is None else str(unit.floor_item_id),
            "size_square_metres": _size_json(unit.size_square_metres),
            "bedrooms": unit.bedrooms,
            "bathrooms": unit.bathrooms,
            "view_item_id": None if unit.view_item_id is None else str(unit.view_item_id),
            "kitchen_item_id": (
                None if unit.kitchen_item_id is None else str(unit.kitchen_item_id)
            ),
            "notes": unit.notes,
            "room_feature_ids": [str(item) for item in unit.room_feature_ids],
            "default_monthly_rent_usd_cents": unit.default_monthly_rent_usd_cents,
            "required_service_ids": [str(item) for item in unit.required_service_ids],
        }

    @staticmethod
    def _audit(
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        unit: Unit,
        actor_id: str,
        action: str,
        previous_state: dict[str, object] | None,
        reason: str | None = None,
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
                reason or "Parking source data changed through the authorized Parking API",
                unit.property_id,
                None if previous_state is None else Jsonb(previous_state),
                Jsonb(PostgresUnitResourceFlow._state(unit)),
                event_id,
                unit.unit_id,
            ),
        )

    @staticmethod
    def _details_parameters(details: UnitDetails) -> tuple[object, ...]:
        return (
            details.size_square_metres,
            details.bedrooms,
            details.bathrooms,
            details.view_item_id,
            details.kitchen_item_id,
            details.notes,
            list(details.room_feature_ids),
        )

    def create(
        self,
        property_id: UUID,
        *,
        unit_number: str,
        floor_item_id: UUID,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        actor_id: str,
    ) -> Unit:
        unit_id = uuid4()
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT * FROM app.create_unit("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s::smallint, %s::smallint, %s, %s, %s, "
                    "%s::uuid[])",
                    (
                        unit_id,
                        property_id,
                        unit_number.strip(),
                        floor_item_id,
                        unit_type,
                        unit_status.value,
                        UUID(actor_id),
                        *self._details_parameters(details),
                    ),
                ).fetchone()
                if row is None:
                    raise UnitResourceUnavailable("Parking creation returned no result")
                created = _unit(row)
                full = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
                if full is not None:
                    created = _unit(full)
                self._audit(
                    connection,
                    unit=created,
                    actor_id=actor_id,
                    action="unit.created",
                    previous_state=None,
                )
            return created
        except (
            ValueError,
            psycopg.errors.CheckViolation,
            psycopg.errors.InvalidParameterValue,
            psycopg.errors.ForeignKeyViolation,
        ) as exc:
            raise UnitResourceInvalid("Parking source fields are invalid") from exc
        except psycopg.errors.UniqueViolation as exc:
            raise UnitResourceInvalid("Parking identity or number already exists") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc

    def set_rent_terms(
        self,
        unit_id: UUID,
        *,
        default_monthly_rent_usd_cents: int | None,
        required_service_ids: tuple[UUID, ...],
        expected_version: int,
        actor_id: str,
        reason: str,
    ) -> Unit:
        """V1-061 (DL-110): set the Unit's default Rent and required Services, kept in History
        with the reason (Parking Step 3: a price change is a money action)."""
        try:
            with psycopg.connect(self._database_url) as connection:
                current_row = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
                if current_row is None:
                    raise UnitResourceNotFound("Parking was not found")
                current = _unit(current_row)
                if current.version != expected_version:
                    raise UnitVersionConflict(current.version)
                version = connection.execute(
                    "SELECT app.set_unit_rent_terms(%s, %s, %s, %s::uuid[], %s)",
                    (
                        unit_id,
                        expected_version,
                        default_monthly_rent_usd_cents,
                        list(required_service_ids),
                        UUID(actor_id),
                    ),
                ).fetchone()
                if version is None or version[0] is None:
                    latest = connection.execute(
                        "SELECT version FROM app.units WHERE id = %s", (unit_id,)
                    ).fetchone()
                    if latest is None:
                        raise UnitResourceNotFound("Parking was not found")
                    raise UnitVersionConflict(int(str(latest[0])))
                row = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
                if row is None:
                    raise UnitResourceNotFound("Parking was not found")
                updated = _unit(row)
                self._audit(
                    connection,
                    unit=updated,
                    actor_id=actor_id,
                    action="unit.rent_terms_changed",
                    previous_state=self._state(current),
                    reason=reason,
                )
            return updated
        except (UnitResourceNotFound, UnitVersionConflict):
            raise
        except (
            ValueError,
            psycopg.errors.CheckViolation,
            psycopg.errors.InvalidParameterValue,
            psycopg.errors.ForeignKeyViolation,
        ) as exc:
            raise UnitResourceInvalid("Parking Rent terms are invalid") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc

    def patch(
        self,
        unit_id: UUID,
        *,
        floor_item_id: UUID | None,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        expected_version: int,
        actor_id: str,
        reason: str | None = None,
    ) -> Unit:
        try:
            with psycopg.connect(self._database_url) as connection:
                current_row = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
                if current_row is None:
                    raise UnitResourceNotFound("Parking was not found")
                current = _unit(current_row)
                if current.version != expected_version:
                    raise UnitVersionConflict(current.version)
                row = connection.execute(
                    "SELECT * FROM app.update_unit("
                    "%s, %s, %s, %s, %s, %s, %s, %s::smallint, %s::smallint, %s, %s, %s, "
                    "%s::uuid[])",
                    (
                        unit_id,
                        floor_item_id,
                        unit_type,
                        unit_status.value,
                        expected_version,
                        UUID(actor_id),
                        *self._details_parameters(details),
                    ),
                ).fetchone()
                if row is None:
                    latest = connection.execute(
                        "SELECT version FROM app.units WHERE id = %s", (unit_id,)
                    ).fetchone()
                    if latest is None:
                        raise UnitResourceNotFound("Parking was not found")
                    raise UnitVersionConflict(int(str(latest[0])))
                updated = _unit(row)
                full = connection.execute(UNIT_SELECT, (unit_id,)).fetchone()
                if full is not None:
                    updated = _unit(full)
                # V1-058 R2: Change status keeps the person's reason in the Unit's History.
                status_changed = reason is not None and updated.status != current.status
                self._audit(
                    connection,
                    unit=updated,
                    actor_id=actor_id,
                    action="unit.status_changed" if status_changed else "unit.updated",
                    previous_state=self._state(current),
                    reason=reason if status_changed else None,
                )
            return updated
        except (UnitResourceNotFound, UnitVersionConflict):
            raise
        except (
            ValueError,
            psycopg.errors.CheckViolation,
            psycopg.errors.InvalidParameterValue,
            psycopg.errors.ForeignKeyViolation,
        ) as exc:
            raise UnitResourceInvalid("Parking source fields are invalid") from exc
        except psycopg.errors.UniqueViolation as exc:
            raise UnitResourceInvalid("Parking identity or number already exists") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc

    def setup_lists(self, property_id: UUID, *, include_removed: bool) -> UnitSetupLists:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    f"SELECT {self._setup_columns}, app.unit_setup_item_in_use(item) "
                    "FROM app.unit_setup_items AS item WHERE item.property_id = %s "
                    + ("" if include_removed else "AND item.removed_at IS NULL ")
                    + "ORDER BY item.list_kind, item.sort_order, item.name_en, item.id",
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking setup lists are unavailable") from exc
        return UnitSetupLists(tuple(_setup_item(row) for row in rows))

    def get_setup_item(self, item_id: UUID) -> UnitSetupItem:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"SELECT {self._setup_columns}, app.unit_setup_item_in_use(item) "
                    "FROM app.unit_setup_items AS item WHERE item.id = %s",
                    (item_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking setup lists are unavailable") from exc
        if row is None:
            raise UnitResourceNotFound("Parking setup item was not found")
        return _setup_item(row)

    def _setup_command(self, sql: str, parameters: tuple[object, ...]) -> UnitSetupItem | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.errors.ObjectNotInPrerequisiteState as exc:
            raise UnitSetupItemInUse("A Parking uses this item") from exc
        except (
            psycopg.errors.CheckViolation,
            psycopg.errors.InvalidParameterValue,
            psycopg.errors.ForeignKeyViolation,
        ) as exc:
            raise UnitResourceInvalid("Parking setup item fields are invalid") from exc
        except psycopg.Error as exc:
            raise UnitResourceUnavailable("Parking setup lists are unavailable") from exc
        return None if row is None else _setup_item(row)

    def create_setup_item(
        self,
        property_id: UUID,
        *,
        list_kind: str,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        actor_id: str,
    ) -> UnitSetupItem:
        created = self._setup_command(
            "SELECT * FROM app.create_unit_setup_item(%s, %s, %s, %s, %s, %s, %s)",
            (uuid4(), property_id, list_kind, name_en, name_km, sort_order, UUID(actor_id)),
        )
        if created is None:
            raise UnitResourceUnavailable("Parking setup item creation returned no result")
        return created

    def _versioned(self, item_id: UUID, result: UnitSetupItem | None) -> UnitSetupItem:
        if result is not None:
            return result
        raise UnitVersionConflict(self.get_setup_item(item_id).version)

    def update_setup_item(
        self,
        item_id: UUID,
        *,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        expected_version: int,
        actor_id: str,
    ) -> UnitSetupItem:
        return self._versioned(
            item_id,
            self._setup_command(
                "SELECT * FROM app.update_unit_setup_item(%s, %s, %s, %s, %s, %s)",
                (item_id, name_en, name_km, sort_order, expected_version, UUID(actor_id)),
            ),
        )

    def remove_setup_item(
        self, item_id: UUID, *, expected_version: int, actor_id: str
    ) -> UnitSetupItem:
        return self._versioned(
            item_id,
            self._setup_command(
                "SELECT * FROM app.remove_unit_setup_item(%s, %s, %s)",
                (item_id, expected_version, UUID(actor_id)),
            ),
        )

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
                    raise UnitResourceNotFound("Parking was not found")
                rows = connection.execute(
                    f"""
                    SELECT id, occurred_at, actor_id, action, entity_type, reason,
                           previous_state, resulting_state, correlation_id, outcome,
                           (SELECT account.display_name FROM app.user_accounts AS account
                            WHERE account.actor_id = app.audit_events.actor_id)
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
            raise UnitResourceUnavailable("Parking persistence is unavailable") from exc
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
                actor_name=None if row[10] is None else str(row[10]),
            )
            for row in rows[:limit]
        )
        next_cursor = None
        if len(rows) > limit and events:
            last = events[-1]
            next_cursor = _encode_cursor((last.occurred_at.isoformat(), str(last.event_id)))
        return UnitTimelinePage(events, next_cursor)


UnitSize = Annotated[Decimal, Field(gt=0, le=10000, max_digits=7, decimal_places=2)]
UnitRooms = Annotated[int, Field(ge=0, le=UNIT_MAX_ROOMS, strict=True)]
UnitNotes = Annotated[str, Field(min_length=1, max_length=UNIT_NOTES_MAX_LENGTH)]
UnitTypeCode = Annotated[str, Field(min_length=1, max_length=40)]


def _unit_type_code(value: str | None) -> str | None:
    if value is not None and UNIT_SETUP_CODE.fullmatch(value) is None:
        raise ValueError("unit_type must be a code of the Parking Types list")
    return value


def _normalized_notes(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _distinct_features(value: list[UUID] | None) -> list[UUID] | None:
    if value is not None and len(set(value)) != len(value):
        raise ValueError("room_feature_ids must not repeat")
    return value


class UnitCreate(BaseModel):
    """DL-078 answer 1: the Floor and Unit Type come from the Unit setup lists."""

    model_config = ConfigDict(extra="forbid")

    unit_number: str = Field(min_length=1, max_length=100)
    floor_item_id: UUID
    unit_type: UnitTypeCode
    status: UnitStatus = UnitStatus.VACANT
    size_square_metres: UnitSize | None = None
    bedrooms: UnitRooms | None = None
    bathrooms: UnitRooms | None = None
    view_item_id: UUID | None = None
    kitchen_item_id: UUID | None = None
    notes: UnitNotes | None = None
    room_feature_ids: list[UUID] = Field(default_factory=list, max_length=MAX_ROOM_FEATURES)

    @field_validator("unit_type")
    @classmethod
    def check_type(cls, value: str | None) -> str | None:
        del cls
        return _unit_type_code(value)

    @field_validator("notes", mode="before")
    @classmethod
    def trim_notes(cls, value: object) -> object:
        del cls
        return _normalized_notes(value)

    @field_validator("room_feature_ids")
    @classmethod
    def check_features(cls, value: list[UUID] | None) -> list[UUID] | None:
        del cls
        return _distinct_features(value)


class UnitRentTermsSource(BaseModel):
    """V1-061 (DL-110): the Unit's default Rent (integer cents, or null for none) and the
    Services every new Lease draft of the Unit must hold."""

    model_config = ConfigDict(extra="forbid", strict=True)

    default_monthly_rent_usd_cents: int | None = Field(ge=1, le=100_000_000)
    required_service_ids: list[UUID] = Field(max_length=20)
    # Parking Step 3 (owner 2026-10-29): a price change is a money action, so it says why.
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        del cls
        return value.strip() if isinstance(value, str) else value

    @field_validator("required_service_ids", mode="before")
    @classmethod
    def ids_from_text(cls, value: object) -> object:
        del cls
        if isinstance(value, list):
            return [UUID(item) if isinstance(item, str) else item for item in value]
        return value


class UnitPatch(BaseModel):
    """The Unit number cannot change (owner, 2026-10-24); a detail sent as null is cleared."""

    model_config = ConfigDict(extra="forbid")

    unit_number: str | None = Field(default=None, min_length=1, max_length=100)
    floor_item_id: UUID | None = None
    unit_type: UnitTypeCode | None = None
    status: UnitStatus | None = None
    size_square_metres: UnitSize | None = None
    bedrooms: UnitRooms | None = None
    bathrooms: UnitRooms | None = None
    view_item_id: UUID | None = None
    kitchen_item_id: UUID | None = None
    notes: UnitNotes | None = None
    room_feature_ids: list[UUID] | None = Field(default=None, max_length=MAX_ROOM_FEATURES)
    # V1-058 R2: the reason given in Change status; it is written to the Unit's History.
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("unit_type")
    @classmethod
    def check_type(cls, value: str | None) -> str | None:
        del cls
        return _unit_type_code(value)

    @field_validator("notes", mode="before")
    @classmethod
    def trim_notes(cls, value: object) -> object:
        del cls
        return _normalized_notes(value)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        del cls
        return value.strip() if isinstance(value, str) else value

    @field_validator("room_feature_ids")
    @classmethod
    def check_features(cls, value: list[UUID] | None) -> list[UUID] | None:
        del cls
        return _distinct_features(value)


# Fields a patch may not send as null: the Unit must keep them.
UNIT_REQUIRED_PATCH_FIELDS: Final = frozenset(
    {"unit_number", "floor_item_id", "unit_type", "status", "room_feature_ids"}
)


class UnitSetupItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_kind: UnitSetupListKind
    name_en: str = Field(min_length=1, max_length=100)
    name_km: str | None = Field(default=None, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=10000, strict=True)

    @field_validator("name_en", "name_km", mode="before")
    @classmethod
    def trim_names(cls, value: object) -> object:
        del cls
        return value.strip() if isinstance(value, str) else value


class UnitSetupItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=100)
    name_km: str | None = Field(default=None, max_length=100)
    sort_order: int | None = Field(default=None, ge=0, le=10000, strict=True)

    @field_validator("name_en", "name_km", mode="before")
    @classmethod
    def trim_names(cls, value: object) -> object:
        del cls
        return value.strip() if isinstance(value, str) else value


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


def _setup_body(item: UnitSetupItem) -> dict[str, object]:
    return {
        "item_id": str(item.item_id),
        "list_kind": item.list_kind,
        "code": item.code,
        "name_en": item.name_en,
        "name_km": item.name_km,
        "sort_order": item.sort_order,
        "removed": item.removed,
        "in_use": item.in_use,
        "version": item.version,
    }


def _can_manage_setup(actor: AuthenticatedActor, property_id: UUID) -> bool:
    return is_authorized(
        actor,
        AuthorizationRequirement(
            capability=UNIT_SETUP_MANAGE_CAPABILITY, property_id=str(property_id)
        ),
    )


def _body(unit: Unit) -> dict[str, object]:
    return {
        "unit_id": str(unit.unit_id),
        "property_id": str(unit.property_id),
        "unit_number": unit.unit_number,
        "floor": unit.floor,
        "unit_type": unit.unit_type,
        "status": unit.status.value,
        "version": unit.version,
        "floor_item_id": None if unit.floor_item_id is None else str(unit.floor_item_id),
        "size_square_metres": _size_json(unit.size_square_metres),
        "bedrooms": unit.bedrooms,
        "bathrooms": unit.bathrooms,
        "view_item_id": None if unit.view_item_id is None else str(unit.view_item_id),
        "kitchen_item_id": None if unit.kitchen_item_id is None else str(unit.kitchen_item_id),
        "notes": unit.notes,
        "room_feature_ids": [str(item) for item in unit.room_feature_ids],
        "default_monthly_rent_usd_cents": unit.default_monthly_rent_usd_cents,
        "required_service_ids": [str(item) for item in unit.required_service_ids],
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
                floor_item_id=command.floor_item_id,
                unit_type=command.unit_type,
                unit_status=command.status,
                details=UnitDetails(
                    command.size_square_metres,
                    command.bedrooms,
                    command.bathrooms,
                    command.view_item_id,
                    command.kitchen_item_id,
                    command.notes,
                    tuple(command.room_feature_ids),
                ),
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
        given = patch.model_fields_set
        if any(getattr(patch, name) is None for name in given & UNIT_REQUIRED_PATCH_FIELDS):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if "reason" in given and "status" not in given:
            # A reason belongs to Change status; alone it would be lost (V1-058 R2).
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if "unit_number" in given and (patch.unit_number or "").strip() != current.unit_number:
            # The owner's 2026-10-24 answer: the Unit number cannot change after creation.
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        expected = _expected_version(if_match, current.version)
        kept = UnitDetails.of(current)

        # A detail left out keeps its value; a detail sent as null is cleared.
        details = replace(
            kept,
            **{
                name: getattr(patch, name)
                for name in given
                & {
                    "size_square_metres",
                    "bedrooms",
                    "bathrooms",
                    "view_item_id",
                    "kitchen_item_id",
                    "notes",
                }
            },
        )
        if patch.room_feature_ids is not None:
            details = replace(details, room_feature_ids=tuple(patch.room_feature_ids))
        try:
            unit = flow.patch(
                unit_id,
                floor_item_id=patch.floor_item_id or current.floor_item_id,
                unit_type=patch.unit_type or current.unit_type,
                unit_status=patch.status or current.status,
                details=details,
                expected_version=expected,
                actor_id=actor.actor_id,
                reason=patch.reason,
            )
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{unit.version}"'
        return {"data": _body(unit), "meta": {"request_id": request.state.request_id}}

    @router.put("/units/{unit_id}/rent-terms")
    def put_unit_rent_terms(
        unit_id: UUID,
        source: UnitRentTermsSource,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        """V1-061 (DL-110): a Manager or the Owner sets the default Rent and required Services."""
        actor = _require_actor(request, resolver)
        current = get_unit_or_http(unit_id)
        _require_manager(actor, current.property_id)
        require_browser_mutation(request, settings)
        if len(set(source.required_service_ids)) != len(source.required_service_ids):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        expected = _expected_version(if_match, current.version)
        try:
            unit = flow.set_rent_terms(
                unit_id,
                default_monthly_rent_usd_cents=source.default_monthly_rent_usd_cents,
                required_service_ids=tuple(source.required_service_ids),
                expected_version=expected,
                actor_id=actor.actor_id,
                reason=source.reason,
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

    @router.get("/properties/{property_id}/unit-setup")
    def unit_setup_lists(
        property_id: UUID,
        request: Request,
        include_removed: bool = False,
    ) -> dict[str, object]:
        """DL-075 answer 10: the lists New Unit and Update Unit pick from."""
        actor = _require_actor(request, resolver)
        can_manage_setup = _can_manage_setup(actor, property_id)
        if not can_manage_setup:
            _require_reader(actor, property_id)
        try:
            lists = flow.setup_lists(
                property_id, include_removed=include_removed and can_manage_setup
            )
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return {
            "data": {
                "lists": {
                    kind: [_setup_body(item) for item in lists.items if item.list_kind == kind]
                    for kind in UNIT_SETUP_LIST_KINDS
                },
                "can_manage": can_manage_setup,
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/properties/{property_id}/unit-setup/items", status_code=status.HTTP_201_CREATED)
    def create_unit_setup_item(
        property_id: UUID,
        command: UnitSetupItemCreate,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        actor = _require_actor(request, resolver)
        if not _can_manage_setup(actor, property_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        require_browser_mutation(request, settings)
        try:
            item = flow.create_setup_item(
                property_id,
                list_kind=command.list_kind,
                name_en=command.name_en,
                name_km=command.name_km or None,
                sort_order=command.sort_order,
                actor_id=actor.actor_id,
            )
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{item.version}"'
        return {"data": _setup_body(item), "meta": {"request_id": request.state.request_id}}

    def setup_item_for_change(request: Request, item_id: UUID) -> tuple[str, UnitSetupItem]:
        actor = _require_actor(request, resolver)
        try:
            current = flow.get_setup_item(item_id)
        except UnitResourceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        if not _can_manage_setup(actor, current.property_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        require_browser_mutation(request, settings)
        return actor.actor_id, current

    @router.patch("/unit-setup/items/{item_id}")
    def update_unit_setup_item(
        item_id: UUID,
        patch: UnitSetupItemPatch,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        actor_id, current = setup_item_for_change(request, item_id)
        given = patch.model_fields_set
        if not given or any(
            getattr(patch, name) is None for name in given & {"name_en", "sort_order"}
        ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        expected = _expected_version(if_match, current.version)
        try:
            item = flow.update_setup_item(
                item_id,
                name_en=patch.name_en if patch.name_en is not None else current.name_en,
                name_km=(patch.name_km or None) if "name_km" in given else current.name_km,
                sort_order=(
                    patch.sort_order if patch.sort_order is not None else current.sort_order
                ),
                expected_version=expected,
                actor_id=actor_id,
            )
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{item.version}"'
        return {"data": _setup_body(item), "meta": {"request_id": request.state.request_id}}

    @router.post("/unit-setup/items/{item_id}/remove")
    def remove_unit_setup_item(
        item_id: UUID,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, object]:
        """An item used by a Unit cannot be removed (DL-075 answer 10)."""
        actor_id, current = setup_item_for_change(request, item_id)
        expected = _expected_version(if_match, current.version)
        try:
            item = flow.remove_setup_item(item_id, expected_version=expected, actor_id=actor_id)
        except UnitSetupItemInUse as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
        except UnitResourceInvalid as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
        except UnitResourceUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        response.headers["ETag"] = f'"{item.version}"'
        return {"data": _setup_body(item), "meta": {"request_id": request.state.request_id}}

    return router
