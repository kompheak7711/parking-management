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


class OccupantMoveOutRefusedError(ValueError):
    """V1-061 (DL-111): a move-out of one occupant that the Lease's rules refuse, by its reason:
    PRIMARY_TENANT, LAST_SIGNER, SIGNERS_AGREE, DATE or NOT_LIVING_THERE."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Occupant move-out is refused: {reason}")
        self.reason = reason


OCCUPANT_MOVE_OUT_REASONS: Final = frozenset(
    {"PRIMARY_TENANT", "LAST_SIGNER", "SIGNERS_AGREE", "DATE", "NOT_LIVING_THERE"}
)


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


@dataclass(frozen=True, slots=True)
class RecordLeaseMoveInCommand:
    """Begin Occupancy for a Lease whose signing already completed the Reservation (DL-066)."""

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_lease_version: int
    actual_move_in_date: date
    occupants: tuple[MoveInOccupant, ...]
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_lease_version < 1:
            raise ValueError("expected versions must be positive")
        if not self.occupants or len(self.occupants) > 20:
            raise ValueError("between 1 and 20 Occupants must begin in one move-in")
        if len({occupant.occupancy_id for occupant in self.occupants}) != len(self.occupants):
            raise ValueError("occupancy identities must be unique")
        if len({occupant.customer_id for occupant in self.occupants}) != len(self.occupants):
            raise ValueError("an Occupant may appear only once")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class AddLeaseOccupantCommand:
    """V1-060 B6 (DL-102): one more person lives in the Unit of a draft or running Lease.

    Before the move-in the person is planned (no Occupancy and no date) and moves in with the
    Lease; after it their own Occupancy starts on ``move_in_date`` (BR-OCC-004).
    """

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_lease_version: int
    customer_id: UUID
    occupancy_id: UUID | None
    move_in_date: date | None
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "customer_id"):
            _require_identity(getattr(self, field), field)
        if self.occupancy_id is not None:
            _require_identity(self.occupancy_id, "occupancy_id")
        if (self.occupancy_id is None) != (self.move_in_date is None):
            raise ValueError("an Occupancy and its move-in date come together")
        if self.expected_lease_version < 1:
            raise ValueError("expected versions must be positive")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


@dataclass(frozen=True, slots=True)
class OccupantMoveOutCommand:
    """V1-061 (owner 2026-10-29, DL-111): one person of a signed Lease moves out on their own day.

    Never the Primary Tenant. A Joint Signer needs every other Signer of the Lease to agree
    (``agreed_signer_customer_ids``), and the last Signer living there leaves only with the Lease.
    """

    idempotency_key: UUID
    event_id: UUID
    lease_id: UUID
    expected_lease_version: int
    occupancy_id: UUID
    move_out_date: date
    agreed_signer_customer_ids: tuple[UUID, ...]
    reason: str
    authorization_reference: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "lease_id", "occupancy_id"):
            _require_identity(getattr(self, field), field)
        if self.expected_lease_version < 1:
            raise ValueError("expected versions must be positive")
        if len(set(self.agreed_signer_customer_ids)) != len(self.agreed_signer_customer_ids):
            raise ValueError("a Signer may agree only once")
        if len(self.agreed_signer_customer_ids) > 100:
            raise ValueError("at most 100 Signers agree")
        _require_nonblank(self.reason, "reason")
        _require_nonblank(self.authorization_reference, "authorization_reference")


def move_in_request_digest(
    command: CompleteMoveInCommand
    | RecordLeaseMoveInCommand
    | AddLeaseOccupantCommand
    | OccupantMoveOutCommand,
) -> str:
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

    def record_lease_move_in(
        self, command: RecordLeaseMoveInCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Record physical move-in for a Lease signed with its Reservation outcome."""
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise MoveInAuthorizationError("Move-in actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise MoveInAuthorizationError("Move-in actor does not match the command")
        if command.authorization_reference != MOVE_IN_CAPABILITY or not is_authorized(
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
                    "SELECT app.record_signed_lease_move_in(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.property_id,
                        command.idempotency_key,
                        move_in_request_digest(command),
                        command.event_id,
                        command.lease_id,
                        command.expected_lease_version,
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
        if row is None or not isinstance(row[0], dict):
            raise MoveInServiceUnavailableError("Move-in command returned no result")
        return cast(dict[str, object], row[0])

    def add_lease_occupant(
        self, command: AddLeaseOccupantCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Add a planned occupant, or an Occupancy with its own move-in date (DL-102)."""
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise MoveInAuthorizationError("Move-in actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise MoveInAuthorizationError("Move-in actor does not match the command")
        if command.authorization_reference != MOVE_IN_CAPABILITY or not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=MOVE_IN_CAPABILITY, property_id=str(self.property_id)
            ),
        ):
            raise MoveInAuthorizationError("Move-in capability is not authorized")
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    "SELECT app.add_lease_occupant(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.property_id,
                        command.idempotency_key,
                        move_in_request_digest(command),
                        command.event_id,
                        command.lease_id,
                        command.expected_lease_version,
                        command.customer_id,
                        command.occupancy_id,
                        command.move_in_date,
                        command.reason,
                        command.authorization_reference,
                        self.actor_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise MoveInNotFoundError("Occupant addition source was not found") from exc
            if exc.sqlstate == "40001":
                raise MoveInVersionConflictError(
                    "Occupant addition version precondition was not met"
                ) from exc
            if exc.sqlstate in {"23505", "23P01"}:
                raise MoveInConflictError("Occupant addition conflicted") from exc
            if exc.sqlstate in {"22023", "22P02", "23514", "55000"}:
                raise MoveInInvalidError("Occupant addition is invalid") from exc
            raise MoveInServiceUnavailableError(
                "Occupant addition persistence is unavailable"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise MoveInServiceUnavailableError("Occupant addition returned no result")
        return cast(dict[str, object], row[0])

    def move_out_lease_occupant(
        self, command: OccupantMoveOutCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """End one person's Occupancy on their own move-out day (DL-111)."""
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise MoveInAuthorizationError("Move-in actor is invalid") from exc
        if authenticated_actor_id != self.actor_id:
            raise MoveInAuthorizationError("Move-in actor does not match the command")
        if command.authorization_reference != MOVE_IN_CAPABILITY or not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=MOVE_IN_CAPABILITY, property_id=str(self.property_id)
            ),
        ):
            raise MoveInAuthorizationError("Move-in capability is not authorized")
        try:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    "SELECT app.move_out_lease_occupant("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid[],%s,%s,%s)",
                    (
                        self.property_id,
                        command.idempotency_key,
                        move_in_request_digest(command),
                        command.event_id,
                        command.lease_id,
                        command.expected_lease_version,
                        command.occupancy_id,
                        command.move_out_date,
                        list(command.agreed_signer_customer_ids),
                        command.reason,
                        command.authorization_reference,
                        self.actor_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise MoveInNotFoundError("Occupant move-out source was not found") from exc
            if exc.sqlstate == "40001":
                raise MoveInVersionConflictError(
                    "Occupant move-out version precondition was not met"
                ) from exc
            if exc.sqlstate in {"23505", "23P01"}:
                raise MoveInConflictError("Occupant move-out conflicted") from exc
            hint = exc.diag.message_hint
            if exc.sqlstate == "23514" and hint in OCCUPANT_MOVE_OUT_REASONS:
                raise OccupantMoveOutRefusedError(hint) from exc
            if exc.sqlstate in {"22023", "22P02", "23514", "55000"}:
                raise MoveInInvalidError("Occupant move-out is invalid") from exc
            raise MoveInServiceUnavailableError(
                "Occupant move-out persistence is unavailable"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise MoveInServiceUnavailableError("Occupant move-out returned no result")
        return cast(dict[str, object], row[0])
