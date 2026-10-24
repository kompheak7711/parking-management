"""Domain and persistence boundary for Property-scoped Units."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

import psycopg

NIL_UUID = UUID(int=0)
# V1-058 R2a (DL-075 answer 10): a Unit Type is the code of a Unit Types list item.
UNIT_SETUP_CODE: Final = re.compile(r"[A-Z0-9][A-Z0-9_]{0,39}")
UNIT_NOTES_MAX_LENGTH: Final = 2000
UNIT_MAX_ROOMS: Final = 20
UNIT_MAX_SIZE: Final = Decimal("10000")


class UnitType(StrEnum):
    """The default Unit Types every Property starts with (BR-UNIT-001; a Settings list since
    DL-075, so a Unit may hold any code of that list)."""

    STUDIO = "STUDIO"
    ONE_BEDROOM = "ONE_BEDROOM"
    TWO_BEDROOM = "TWO_BEDROOM"
    THREE_BEDROOM = "THREE_BEDROOM"


class UnitStatus(StrEnum):
    """Supported stored operational Unit statuses."""

    VACANT = "VACANT"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    CLEANING = "CLEANING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


@dataclass(frozen=True, slots=True)
class SignedLeasePeriod:
    """Inclusive contractual coverage for one authoritative SIGNED Lease."""

    starts_on: date
    ends_on: date

    def __post_init__(self) -> None:
        if self.ends_on < self.starts_on:
            raise ValueError("signed Lease period must not end before it starts")

    def overlaps(self, starts_on: date, ends_on: date) -> bool:
        """Return whether this Lease covers any part of the requested period."""
        return self.starts_on <= ends_on and starts_on <= self.ends_on


@dataclass(frozen=True, slots=True)
class UnitAvailabilityFacts:
    """Authoritative facts used to decide whether a Unit can be reserved."""

    requested_starts_on: date
    requested_ends_on: date
    is_ready_for_rental: bool
    has_active_reservation: bool = False
    signed_lease_periods: tuple[SignedLeasePeriod, ...] = ()
    is_actually_occupied: bool = False
    requires_cleaning: bool = False
    is_under_maintenance: bool = False
    is_out_of_service: bool = False
    restoration_authorized: bool = False

    def __post_init__(self) -> None:
        if self.requested_ends_on < self.requested_starts_on:
            raise ValueError("requested period must not end before it starts")

    @property
    def has_overlapping_signed_lease(self) -> bool:
        """Use contractual overlap, rather than Lease existence, as authority."""
        return any(
            period.overlaps(self.requested_starts_on, self.requested_ends_on)
            for period in self.signed_lease_periods
        )


@dataclass(frozen=True, slots=True)
class UnitAvailabilityDecision:
    """A non-destructive availability and summary-status decision for a Unit."""

    unit_id: UUID
    property_id: UUID
    is_available: bool
    status: UnitStatus
    blockers: tuple[str, ...]

    @property
    def available_for_reservation(self) -> bool:
        """Expose the decision in reservation-specific terms."""
        return self.is_available


def evaluate_unit_availability(
    unit: Unit, facts: UnitAvailabilityFacts
) -> UnitAvailabilityDecision:
    """Decide availability from authoritative facts, never stored status alone."""
    blockers: list[str] = []
    if facts.has_active_reservation:
        blockers.append("ACTIVE_RESERVATION")
    if facts.has_overlapping_signed_lease:
        blockers.append("SIGNED_LEASE_OVERLAP")
    if facts.is_actually_occupied:
        blockers.append("ACTUAL_OCCUPANCY")
    if facts.is_under_maintenance:
        blockers.append("UNDER_MAINTENANCE")
    if facts.requires_cleaning:
        blockers.append("CLEANING")
    if facts.is_out_of_service:
        blockers.append("OUT_OF_SERVICE")
    if (
        unit.status in {UnitStatus.UNDER_MAINTENANCE, UnitStatus.OUT_OF_SERVICE}
        and not facts.restoration_authorized
        and not facts.is_under_maintenance
        and not facts.is_out_of_service
    ):
        blockers.append("AUTHORIZED_RESTORATION_REQUIRED")
    if not facts.is_ready_for_rental and not any(
        (
            facts.is_actually_occupied,
            facts.is_under_maintenance,
            facts.requires_cleaning,
            facts.is_out_of_service,
        )
    ):
        blockers.append("NOT_READY_FOR_RENTAL")

    return UnitAvailabilityDecision(
        unit_id=unit.unit_id,
        property_id=unit.property_id,
        is_available=not blockers,
        status=restored_unit_status(unit, facts),
        blockers=tuple(blockers),
    )


def restored_unit_status(unit: Unit, facts: UnitAvailabilityFacts) -> UnitStatus:
    """Derive summary status after a state decision from authoritative facts."""
    if (
        unit.status in {UnitStatus.UNDER_MAINTENANCE, UnitStatus.OUT_OF_SERVICE}
        and not facts.restoration_authorized
    ):
        return unit.status
    if facts.is_actually_occupied:
        return UnitStatus.OCCUPIED
    if facts.has_active_reservation:
        return UnitStatus.RESERVED
    if facts.has_overlapping_signed_lease:
        return UnitStatus.RESERVED
    if facts.is_out_of_service:
        return UnitStatus.OUT_OF_SERVICE
    if facts.is_under_maintenance:
        return UnitStatus.UNDER_MAINTENANCE
    if facts.requires_cleaning:
        return UnitStatus.CLEANING
    if facts.is_ready_for_rental:
        return UnitStatus.VACANT
    return unit.status


class UnitNumberAlreadyExistsError(ValueError):
    """Raised when a Unit number is already used within its Property."""


class UnitIdentityAlreadyExistsError(ValueError):
    """Raised when a stable Unit UUID is already assigned."""


class UnitOutsidePropertyScopeError(ValueError):
    """Raised when a Unit is assigned to a different Property."""


@dataclass(frozen=True, slots=True)
class Unit:
    """A stable Unit identity and its stored operational attributes."""

    unit_id: UUID
    property_id: UUID
    unit_number: str
    floor: str
    unit_type: str
    status: UnitStatus
    version: int = 1
    # DL-078 answer 1 (V1-058 R2a): the details, picked from the Unit setup lists where one exists.
    floor_item_id: UUID | None = None
    size_square_metres: Decimal | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    view_item_id: UUID | None = None
    kitchen_item_id: UUID | None = None
    notes: str | None = None
    room_feature_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        """Enforce Unit identity and supported-value invariants."""
        if self.unit_id == NIL_UUID:
            raise ValueError("unit_id must not be the nil UUID")
        if self.property_id == NIL_UUID:
            raise ValueError("property_id must not be the nil UUID")
        if not self.unit_number.strip():
            raise ValueError("unit_number must not be blank")
        if self.unit_number != self.unit_number.strip():
            raise ValueError("unit_number must not have surrounding whitespace")
        if not self.floor.strip():
            raise ValueError("floor must not be blank")
        if self.floor != self.floor.strip():
            raise ValueError("floor must not have surrounding whitespace")
        if not isinstance(self.unit_type, str) or UNIT_SETUP_CODE.fullmatch(self.unit_type) is None:
            raise ValueError("unit_type is not supported")
        if self.size_square_metres is not None and not (
            Decimal(0) < self.size_square_metres <= UNIT_MAX_SIZE
            and self.size_square_metres == self.size_square_metres.quantize(Decimal("0.01"))
        ):
            raise ValueError("size_square_metres must be above 0 and at most 10000, in 0.01 m2")
        for rooms in (self.bedrooms, self.bathrooms):
            if rooms is not None and not 0 <= rooms <= UNIT_MAX_ROOMS:
                raise ValueError("bedrooms and bathrooms must be from 0 to 20")
        if self.notes is not None and (
            self.notes != self.notes.strip() or not 1 <= len(self.notes) <= UNIT_NOTES_MAX_LENGTH
        ):
            raise ValueError("notes must be trimmed text of at most 2000 characters")
        if len(set(self.room_feature_ids)) != len(self.room_feature_ids):
            raise ValueError("room_feature_ids must not repeat")
        if not isinstance(self.status, UnitStatus):
            raise ValueError("status is not supported")
        if self.version < 1:
            raise ValueError("version must be positive")


class UnitRepository(Protocol):
    """Persistence operations required by the Unit service."""

    def get_by_unit_number(self, property_id: UUID, unit_number: str) -> Unit | None:
        """Return the Unit with this number in the Property, if present."""
        ...

    def add(self, unit: Unit) -> None:
        """Persist a new Unit without replacing an existing identity."""
        ...


@dataclass(frozen=True, slots=True)
class PostgresUnitRepository:
    """Read and create Units through the protected PostgreSQL boundary."""

    database_url: str
    actor_id: UUID

    def get_by_unit_number(self, property_id: UUID, unit_number: str) -> Unit | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT id, property_id, unit_number, floor, unit_type, status, version
                FROM app.units
                WHERE property_id = %s
                  AND unit_number = %s
                """,
                (property_id, unit_number),
            ).fetchone()
        return None if row is None else _unit_from_row(row)

    def add(self, unit: Unit) -> None:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    """
                    SELECT id, property_id, unit_number, floor, unit_type, status, version
                    FROM app.create_unit(%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        unit.unit_id,
                        unit.property_id,
                        unit.unit_number,
                        unit.floor,
                        unit.unit_type,
                        unit.status.value,
                        self.actor_id,
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            if error.diag.constraint_name == "units_property_unit_number_unique":
                raise UnitNumberAlreadyExistsError(
                    f"Unit number {unit.unit_number!r} already exists in this Property"
                ) from error
            if error.diag.constraint_name == "units_pkey":
                raise UnitIdentityAlreadyExistsError(
                    f"Unit identity {unit.unit_id} already exists"
                ) from error
            raise
        if row is None or _unit_from_row(row) != unit:
            raise RuntimeError("Unit creation returned an invalid result")


@dataclass(frozen=True, slots=True)
class UnitService:
    """Create Units only within one authoritative Property scope."""

    property_id: UUID
    repository: UnitRepository

    def __post_init__(self) -> None:
        if self.property_id == NIL_UUID:
            raise ValueError("property_id must not be the nil UUID")

    def create(
        self,
        unit_id: UUID,
        *,
        property_id: UUID,
        unit_number: str,
        floor: str,
        unit_type: str,
        status: UnitStatus,
    ) -> Unit:
        """Validate and persist a new stable Unit identity."""
        if property_id != self.property_id:
            raise UnitOutsidePropertyScopeError("Unit is assigned to a different Property ID")

        normalized_number = unit_number.strip()
        if self.repository.get_by_unit_number(property_id, normalized_number) is not None:
            raise UnitNumberAlreadyExistsError(
                f"Unit number {normalized_number!r} already exists in this Property"
            )

        unit = Unit(
            unit_id=unit_id,
            property_id=property_id,
            unit_number=normalized_number,
            floor=floor.strip(),
            unit_type=unit_type,
            status=status,
        )
        self.repository.add(unit)
        return unit


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def unit_from_row(row: tuple[object, ...]) -> Unit:
    """Map a Unit row: the seven base columns, then the details of `app.unit_with_details`."""
    details = row[7:15] if len(row) >= 15 else (None,) * 7 + ((),)
    features = details[7]
    return Unit(
        unit_id=UUID(str(row[0])),
        property_id=UUID(str(row[1])),
        unit_number=str(row[2]),
        floor=str(row[3]),
        unit_type=str(row[4]),
        status=UnitStatus(str(row[5])),
        version=int(str(row[6])),
        floor_item_id=_optional_uuid(details[0]),
        size_square_metres=None if details[1] is None else Decimal(str(details[1])),
        bedrooms=_optional_int(details[2]),
        bathrooms=_optional_int(details[3]),
        view_item_id=_optional_uuid(details[4]),
        kitchen_item_id=_optional_uuid(details[5]),
        notes=None if details[6] is None else str(details[6]),
        room_feature_ids=tuple(
            UUID(str(item)) for item in (features if isinstance(features, list | tuple) else ())
        ),
    )


_unit_from_row = unit_from_row
