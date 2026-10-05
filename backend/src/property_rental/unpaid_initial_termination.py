"""Explicit follow-up after a termination for an unpaid Initial obligation (BR-LEASE-005)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Final, cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel

from property_rental.deposit import DEPOSIT_DISPOSE_CAPABILITY
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.invoice import INVOICE_ADJUST_CAPABILITY, INVOICE_VOID_CAPABILITY
from property_rental.lease import LEASE_TERMINATE_CAPABILITY

UNIT_MANAGE_CAPABILITY: Final = "property.manage"
NIL_UUID: Final = UUID(int=0)


class UnpaidInitialTerminationNotFoundError(LookupError):
    pass


class UnpaidInitialTerminationConflictError(RuntimeError):
    pass


class UnpaidInitialTerminationInvalidError(ValueError):
    pass


class UnpaidInitialTerminationAuthorizationError(PermissionError):
    pass


class UnpaidInitialTerminationUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value == NIL_UUID:
        raise ValueError(f"{field} must be a nonzero UUID")


def _reason(value: str | None, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 500
    ):
        raise ValueError(f"{field} must be normalized, nonblank, and bounded")


@dataclass(frozen=True, slots=True)
class ResolveNeverMovedInCommand:
    """Forfeit the Security Deposit, VOID or credit Initial Rent, and release the Unit."""

    idempotency_key: UUID
    resolution_id: UUID
    termination_event_id: UUID
    unit_status: str
    reason: str
    unit_status_reason: str | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "resolution_id", "termination_event_id"):
            _identity(getattr(self, field), field)
        if self.unit_status not in {"VACANT", "CLEANING"}:
            raise ValueError("unit_status must be VACANT or CLEANING")
        if (self.unit_status == "CLEANING") != (self.unit_status_reason is not None):
            raise ValueError("CLEANING needs a reason; VACANT takes none")
        if self.unit_status_reason is not None:
            _reason(self.unit_status_reason, "unit_status_reason")
        _reason(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class CreditMovedInInitialRentCommand:
    """Credit Initial Rent for the days after the termination date (BR-RENT-007)."""

    idempotency_key: UUID
    resolution_id: UUID
    termination_event_id: UUID
    reason: str

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "resolution_id", "termination_event_id"):
            _identity(getattr(self, field), field)
        _reason(self.reason, "reason")


def _digest(
    action: str, command: ResolveNeverMovedInCommand | CreditMovedInInitialRentCommand
) -> str:
    serialized = json.dumps(
        {"action": action, "command": asdict(command)},
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PostgresUnpaidInitialTerminationService:
    financial_database_url: str
    property_id: UUID

    def _authorize(self, actor: AuthenticatedActor, capabilities: tuple[str, ...]) -> UUID:
        try:
            actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise UnpaidInitialTerminationAuthorizationError("Actor is invalid") from exc
        for capability in capabilities:
            if not is_authorized(
                actor, AuthorizationRequirement(capability, str(self.property_id))
            ):
                raise UnpaidInitialTerminationAuthorizationError(
                    "Unpaid Initial termination capability is not authorized"
                )
        return actor_id

    def _execute(self, query: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(self.financial_database_url, connect_timeout=3) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise UnpaidInitialTerminationNotFoundError("Termination was not found") from exc
            # P5S01: a closed Final Settlement (V1-056 sub-slice 8e-1).
            if exc.sqlstate in {
                "23505",
                "23P01",
                "40001",
                "55P03",
                "P4503",
                "P4504",
                "P4509",
                "P5S01",
            }:
                raise UnpaidInitialTerminationConflictError("Resolution conflicted") from exc
            if exc.sqlstate in {"22023", "23514", "55000", "P4502", "P4508"}:
                raise UnpaidInitialTerminationInvalidError("Resolution is invalid") from exc
            raise UnpaidInitialTerminationUnavailableError("Persistence is unavailable") from exc
        if row is None or not isinstance(row[0], dict):
            raise UnpaidInitialTerminationUnavailableError("Resolution returned no result")
        return cast(dict[str, object], row[0])

    def resolve_never_moved_in(
        self, command: ResolveNeverMovedInCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        needed: tuple[str, ...] = (
            LEASE_TERMINATE_CAPABILITY,
            DEPOSIT_DISPOSE_CAPABILITY,
            INVOICE_VOID_CAPABILITY,
            INVOICE_ADJUST_CAPABILITY,
        )
        if command.unit_status == "CLEANING":
            needed += (UNIT_MANAGE_CAPABILITY,)
        actor_id = self._authorize(actor, needed)
        return self._execute(
            "SELECT app.resolve_unpaid_initial_never_moved_in(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                actor_id,
                command.idempotency_key,
                _digest("unpaid_initial.never_moved_in", command),
                command.resolution_id,
                command.termination_event_id,
                command.unit_status,
                command.unit_status_reason,
                command.reason,
            ),
        )

    def credit_moved_in_initial_rent(
        self, command: CreditMovedInInitialRentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, (LEASE_TERMINATE_CAPABILITY, INVOICE_ADJUST_CAPABILITY))
        return self._execute(
            "SELECT app.credit_initial_rent_after_termination(%s,%s,%s,%s,%s,%s,%s)",
            (
                self.property_id,
                actor_id,
                command.idempotency_key,
                _digest("unpaid_initial.moved_in_credit", command),
                command.resolution_id,
                command.termination_event_id,
                command.reason,
            ),
        )
