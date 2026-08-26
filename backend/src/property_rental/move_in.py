"""Atomic Reservation-to-Lease move-in orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Final, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)

MOVE_IN_CAPABILITY: Final = "reservations.complete"
NIL_UUID: Final = UUID(int=0)


class MoveInNotFoundError(LookupError):
    """Raised when a source is absent or outside the Property scope."""


class MoveInVersionConflictError(RuntimeError):
    """Raised when an optimistic version is stale."""


class MoveInConflictError(RuntimeError):
    """Raised for replay identity or Unit/Occupancy conflicts."""


class MoveInInvalidError(ValueError):
    """Raised when a move-in prerequisite is not satisfied."""


class MoveInAuthorizationError(PermissionError):
    """Raised before persistence when capability evidence is absent."""


class MoveInServiceUnavailableError(RuntimeError):
    """Raised when the transactional boundary cannot be reached safely."""


def _require_identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _require_nonblank(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")


@dataclass(frozen=True, slots=True)
class MoveInOccupant:
    """One explicitly recorded Occupant, independent of signer status."""

    occupancy_id: UUID
    customer_id: UUID

    def __post_init__(self) -> None:
        _require_identity(self.occupancy_id, "occupancy_id")
        _require_identity(self.customer_id, "customer_id")


@dataclass(frozen=True, slots=True)
class CompleteMoveInCommand:
    """Complete one Reservation and begin its Lease Occupancy atomically."""

    idempotency_key: UUID
    event_id: UUID
    reservation_id: UUID
    lease_id: UUID
    expected_reservation_version: int
    expected_lease_version: int
    expected_unit_version: int
    actual_move_in_date: date
    occupants: tuple[MoveInOccupant, ...]
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "reservation_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if (
            min(
                self.expected_reservation_version,
                self.expected_lease_version,
                self.expected_unit_version,
            )
            < 1
        ):
            raise ValueError("expected versions must be positive")
        if not self.occupants:
            raise ValueError("at least one Occupant is required")
        if len(self.occupants) > 20:
            raise ValueError("at most 20 Occupants may begin in one move-in")
        occupancy_ids = {occupant.occupancy_id for occupant in self.occupants}
        customer_ids = {occupant.customer_id for occupant in self.occupants}
        if len(occupancy_ids) != len(self.occupants):
            raise ValueError("occupancy identities must be unique")
        if len(customer_ids) != len(self.occupants):
            raise ValueError("an Occupant may appear only once")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


def move_in_request_digest(command: CompleteMoveInCommand) -> str:
    """Bind stable replay identity to every move-in input."""

    payload = asdict(command)
    serialized = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class MoveInSnapshot:
    """Bounded result of one completed or replayed move-in."""

    event_id: UUID
    property_id: UUID
    reservation_id: UUID
    reservation_version: int
    lease_id: UUID
    lease_version: int
    unit_id: UUID
    unit_version: int
    deposit_id: UUID
    deposit_version: int
    actual_move_in_date: date
    occupancy_ids: tuple[UUID, ...]


def _snapshot(row: tuple[object, ...]) -> MoveInSnapshot:
    payload = cast(dict[str, object], row[0])
    occupancy_values = cast(list[object], payload["occupancy_ids"])
    return MoveInSnapshot(
        event_id=UUID(str(payload["event_id"])),
        property_id=UUID(str(payload["property_id"])),
        reservation_id=UUID(str(payload["reservation_id"])),
        reservation_version=int(str(payload["reservation_version"])),
        lease_id=UUID(str(payload["lease_id"])),
        lease_version=int(str(payload["lease_version"])),
        unit_id=UUID(str(payload["unit_id"])),
        unit_version=int(str(payload["unit_version"])),
        deposit_id=UUID(str(payload["deposit_id"])),
        deposit_version=int(str(payload["deposit_version"])),
        actual_move_in_date=date.fromisoformat(str(payload["actual_move_in_date"])),
        occupancy_ids=tuple(UUID(str(value)) for value in occupancy_values),
    )


@dataclass(frozen=True, slots=True)
class PostgresMoveInService:
    """Execute the Property-scoped move-in command through PostgreSQL."""

    database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _require_identity(self.property_id, "property_id")
        _require_identity(self.actor_id, "actor_id")

    def complete(
        self, command: CompleteMoveInCommand, *, actor: AuthenticatedActor
    ) -> MoveInSnapshot:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise MoveInAuthorizationError("Move-in actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise MoveInAuthorizationError("Move-in actor does not match the command")
        if command.authorization_reference != MOVE_IN_CAPABILITY:
            raise MoveInAuthorizationError("Move-in authorization evidence is not authoritative")
        if not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=MOVE_IN_CAPABILITY, property_id=str(self.property_id)
            ),
        ):
            raise MoveInAuthorizationError("Move-in capability is not authorized")

        occupants = [
            {"occupancy_id": str(value.occupancy_id), "customer_id": str(value.customer_id)}
            for value in command.occupants
        ]
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    "SELECT app.complete_reservation_move_in("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.property_id,
                        command.idempotency_key,
                        move_in_request_digest(command),
                        command.event_id,
                        command.reservation_id,
                        command.lease_id,
                        command.expected_reservation_version,
                        command.expected_lease_version,
                        command.expected_unit_version,
                        command.actual_move_in_date,
                        Jsonb(occupants),
                        command.reason,
                        command.authorization_reference,
                        self.actor_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise MoveInNotFoundError("Move-in source was not found") from exc
            if exc.sqlstate == "40001":
                raise MoveInVersionConflictError(
                    "Move-in version precondition was not met"
                ) from exc
            if exc.sqlstate in {"23505", "23P01"}:
                raise MoveInConflictError("Move-in command conflicted") from exc
            if exc.sqlstate in {"22023", "22P02", "23514", "55000"}:
                raise MoveInInvalidError("Move-in command is invalid") from exc
            raise MoveInServiceUnavailableError("Move-in persistence is unavailable") from exc
        if row is None:
            raise MoveInServiceUnavailableError("Move-in command returned no result")
        return _snapshot(row)
