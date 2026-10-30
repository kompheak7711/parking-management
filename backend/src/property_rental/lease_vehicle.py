"""The vehicle of a Lease (Parking Step 4, owner 2026-10-30).

One Lease = one Parking = one vehicle at a time. The vehicle takes the Occupancy slot (hidden
names stay Property Rental's): `record_lease_vehicle_move_in` moves one vehicle in through
Property Rental's move-in; `change_lease_vehicle` ends the old vehicle's row and starts the new
one the same day. The only vehicle never moves out alone: Termination and the Move-out page end
it. The database refuses with a reason the screen shows by its own code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Final, cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    MoveInAuthorizationError,
    MoveInConflictError,
    MoveInInvalidError,
    MoveInNotFoundError,
    MoveInServiceUnavailableError,
    MoveInVersionConflictError,
)

VEHICLE_REASONS: Final = frozenset(
    {
        "VEHICLE_SECOND",
        "VEHICLE_NOT_OF_LEASE",
        "VEHICLE_TYPE",
        "VEHICLE_PARKED",
        "VEHICLE_NONE_IN",
        "VEHICLE_SAME",
        "VEHICLE_DATE",
    }
)


class VehicleRefusedError(ValueError):
    """A vehicle move-in or change the Lease's rules refuse, by its reason (VEHICLE_SECOND,
    VEHICLE_NOT_OF_LEASE, VEHICLE_TYPE, VEHICLE_PARKED, VEHICLE_NONE_IN, VEHICLE_SAME,
    VEHICLE_DATE)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Vehicle command is refused: {reason}")
        self.reason = reason


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


ZERO: Final = UUID(int=0)


@dataclass(frozen=True, slots=True)
class RecordLeaseVehicleMoveInCommand:
    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_lease_version: int
    actual_move_in_date: date
    occupancy_id: UUID
    vehicle_id: UUID
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "occupancy_id", "vehicle_id"):
            _require(getattr(self, field) != ZERO, f"{field} must be a real identity")
        _require(self.expected_lease_version >= 1, "expected versions must be positive")
        _require(self.reason.strip() != "", "reason must not be blank")
        _require(self.authorization_reference.strip() != "", "authorization_reference required")


@dataclass(frozen=True, slots=True)
class ChangeLeaseVehicleCommand:
    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_lease_version: int
    change_date: date
    occupancy_id: UUID
    vehicle_id: UUID
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "occupancy_id", "vehicle_id"):
            _require(getattr(self, field) != ZERO, f"{field} must be a real identity")
        _require(self.expected_lease_version >= 1, "expected versions must be positive")
        _require(self.reason.strip() != "", "reason must not be blank")
        _require(self.authorization_reference.strip() != "", "authorization_reference required")


def _digest(command: RecordLeaseVehicleMoveInCommand | ChangeLeaseVehicleCommand) -> str:
    serialized = json.dumps(asdict(command), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PostgresLeaseVehicleService:
    """Execute the vehicle move-in and change through PostgreSQL, under the move-in right."""

    database_url: str
    property_id: UUID
    actor_id: UUID

    def record_lease_vehicle_move_in(
        self, command: RecordLeaseVehicleMoveInCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self._authorize(command.authorization_reference, actor)
        return self._call(
            "SELECT app.record_lease_vehicle_move_in(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                _digest(command),
                command.event_id,
                command.lease_id,
                command.expected_lease_version,
                command.actual_move_in_date,
                command.occupancy_id,
                command.vehicle_id,
                command.reason,
                command.authorization_reference,
                self.actor_id,
            ),
        )

    def change_lease_vehicle(
        self, command: ChangeLeaseVehicleCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        self._authorize(command.authorization_reference, actor)
        return self._call(
            "SELECT app.change_lease_vehicle(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                command.idempotency_key,
                _digest(command),
                command.event_id,
                command.lease_id,
                command.expected_lease_version,
                command.occupancy_id,
                command.vehicle_id,
                command.change_date,
                command.reason,
                command.authorization_reference,
                self.actor_id,
            ),
        )

    def _authorize(self, authorization_reference: str, actor: AuthenticatedActor) -> None:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise MoveInAuthorizationError("Move-in actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise MoveInAuthorizationError("Move-in actor does not match the command")
        if authorization_reference != MOVE_IN_CAPABILITY or not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=MOVE_IN_CAPABILITY, property_id=str(self.property_id)
            ),
        ):
            raise MoveInAuthorizationError("Move-in capability is not authorized")

    def _call(self, statement: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(statement, parameters).fetchone()
        except psycopg.Error as exc:
            hint = exc.diag.message_hint
            if exc.sqlstate == "23514" and hint in VEHICLE_REASONS:
                raise VehicleRefusedError(hint) from exc
            if exc.sqlstate == "P0002":
                raise MoveInNotFoundError("Vehicle command source was not found") from exc
            if exc.sqlstate == "40001":
                raise MoveInVersionConflictError(
                    "Vehicle command version precondition was not met"
                ) from exc
            if exc.sqlstate in {"23505", "23P01"}:
                raise MoveInConflictError("Vehicle command conflicted") from exc
            if exc.sqlstate in {"22023", "22P02", "23514", "55000"}:
                raise MoveInInvalidError("Vehicle command is invalid") from exc
            raise MoveInServiceUnavailableError("Vehicle persistence is unavailable") from exc
        if row is None or not isinstance(row[0], dict):
            raise MoveInServiceUnavailableError("Vehicle command returned no result")
        return cast(dict[str, object], row[0])
