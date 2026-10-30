"""Vehicles (Parking Step 4, owner 2026-10-30): a record under a Customer.

A vehicle has a type (car, motorbike, tuk-tuk, food cart) and a plate as typed, Khmer or Latin,
never transliterated. A plate is matched without spaces, dashes, dots and case so the screen can
warn about a duplicate; nothing is merged. A vehicle is corrected, never deleted. Photos and
documents are not part of Step 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

import psycopg

VEHICLE_TYPES: Final = ("CAR", "MOTORBIKE", "TUK_TUK", "FOOD_CART")
PLATE_MAX_LENGTH: Final = 32


class VehicleNotFoundError(LookupError):
    """The vehicle, or the active Customer of a new vehicle, was not found."""


class VehicleVersionConflictError(RuntimeError):
    """The vehicle changed since it was read."""


class VehicleConflictError(RuntimeError):
    """The vehicle identity was reused for another vehicle."""


class VehicleInvalidError(ValueError):
    """The type or the plate is not allowed."""


class VehicleUnavailableError(RuntimeError):
    """Vehicle persistence is unavailable."""


def _check(vehicle_type: str, plate_text: str) -> None:
    if vehicle_type not in VEHICLE_TYPES:
        raise VehicleInvalidError("vehicle_type must be CAR, MOTORBIKE, TUK_TUK or FOOD_CART")
    if plate_text != plate_text.strip() or not 1 <= len(plate_text) <= PLATE_MAX_LENGTH:
        raise VehicleInvalidError("plate_text must be 1 to 32 characters, trimmed")


@dataclass(frozen=True, slots=True)
class Vehicle:
    vehicle_id: UUID
    customer_id: UUID
    customer_name: str
    vehicle_type: str
    plate_text: str
    version: int


@dataclass(frozen=True, slots=True)
class VehicleCreateCommand:
    vehicle_id: UUID
    customer_id: UUID
    vehicle_type: str
    plate_text: str

    def __post_init__(self) -> None:
        _check(self.vehicle_type, self.plate_text)


@dataclass(frozen=True, slots=True)
class VehicleUpdateCommand:
    vehicle_id: UUID
    expected_version: int
    vehicle_type: str
    plate_text: str

    def __post_init__(self) -> None:
        _check(self.vehicle_type, self.plate_text)
        if self.expected_version < 1:
            raise VehicleInvalidError("expected_version must be positive")


_COLUMNS: Final = (
    "vehicle.id, vehicle.customer_id, customer.legal_name, vehicle.vehicle_type, "
    "vehicle.plate_text, vehicle.version FROM app.vehicles AS vehicle "
    "JOIN app.customers AS customer ON customer.id = vehicle.customer_id"
)


def _vehicle(row: tuple[object, ...]) -> Vehicle:
    return Vehicle(
        vehicle_id=UUID(str(row[0])),
        customer_id=UUID(str(row[1])),
        customer_name=str(row[2]),
        vehicle_type=str(row[3]),
        plate_text=str(row[4]),
        version=int(str(row[5])),
    )


def _from_json(value: object) -> Vehicle:
    data = cast(dict[str, object], value)
    return _vehicle(
        (
            data["vehicle_id"],
            data["customer_id"],
            data["customer_name"],
            data["vehicle_type"],
            data["plate_text"],
            data["version"],
        )
    )


def _translate(exc: psycopg.Error) -> Exception:
    if exc.sqlstate == "P0002":
        return VehicleNotFoundError("Vehicle or Customer was not found")
    if exc.sqlstate == "40001":
        return VehicleVersionConflictError("Vehicle version precondition was not met")
    if exc.sqlstate == "23505":
        return VehicleConflictError("Vehicle identity was reused")
    if exc.sqlstate in {"22023", "22P02", "23514", "55000"}:
        return VehicleInvalidError("Vehicle command is invalid")
    return VehicleUnavailableError("Vehicle persistence is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresVehicleService:
    """Read and write vehicles through the database functions (the route checks the right)."""

    database_url: str

    def get(self, vehicle_id: UUID) -> Vehicle:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    f"SELECT {_COLUMNS} WHERE vehicle.id = %s", (vehicle_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise VehicleUnavailableError("Vehicle persistence is unavailable") from exc
        if row is None:
            raise VehicleNotFoundError("Vehicle was not found")
        return _vehicle(row)

    def of_customer(self, customer_id: UUID) -> tuple[Vehicle, ...]:
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(
                    f"SELECT {_COLUMNS} WHERE vehicle.customer_id = %s "
                    "ORDER BY vehicle.created_at, vehicle.id",
                    (customer_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise VehicleUnavailableError("Vehicle persistence is unavailable") from exc
        return tuple(_vehicle(row) for row in rows)

    def find_by_plate(self, plate_text: str) -> tuple[Vehicle, ...]:
        """Every vehicle whose plate matches without spaces, dashes, dots and case."""
        try:
            with psycopg.connect(self.database_url) as connection:
                rows = connection.execute(
                    f"SELECT {_COLUMNS} WHERE vehicle.plate_match_key = "
                    "upper(regexp_replace(%s, '[[:space:].-]', '', 'g')) "
                    "ORDER BY customer.legal_name, vehicle.created_at, vehicle.id",
                    (plate_text,),
                ).fetchall()
        except psycopg.Error as exc:
            raise VehicleUnavailableError("Vehicle persistence is unavailable") from exc
        return tuple(_vehicle(row) for row in rows)

    def create(self, command: VehicleCreateCommand, *, actor_id: UUID) -> Vehicle:
        return self._call(
            "SELECT app.create_vehicle(%s,%s,%s,%s,%s)",
            (
                command.vehicle_id,
                command.customer_id,
                command.vehicle_type,
                command.plate_text,
                actor_id,
            ),
        )

    def update(self, command: VehicleUpdateCommand, *, actor_id: UUID) -> Vehicle:
        return self._call(
            "SELECT app.update_vehicle(%s,%s,%s,%s,%s)",
            (
                command.vehicle_id,
                command.expected_version,
                command.vehicle_type,
                command.plate_text,
                actor_id,
            ),
        )

    def _call(self, statement: str, parameters: tuple[object, ...]) -> Vehicle:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(statement, parameters).fetchone()
        except psycopg.Error as exc:
            raise _translate(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise VehicleUnavailableError("Vehicle command returned no result")
        return _from_json(row[0])
