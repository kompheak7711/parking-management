"""Explicit physical departure, separate from financial source completion."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.types.json import Jsonb

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)

MOVE_OUT_READ = "leases.read"
MOVE_OUT_RECORD = "leases.move_out"
MAX_ENDED_OCCUPANCIES = 20
MOVE_OUT_CONDITIONS = frozenset({"CLEANING", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"})


class PhysicalMoveOutInvalidError(ValueError):
    pass


class PhysicalMoveOutNotFoundError(LookupError):
    pass


class PhysicalMoveOutAuthorizationError(PermissionError):
    pass


class PhysicalMoveOutConflictError(RuntimeError):
    pass


class PhysicalMoveOutUtilityConflictError(PhysicalMoveOutConflictError):
    """Existing Utility evidence requires responsibility-boundary reconciliation."""


class PhysicalMoveOutResolutionReliance(PhysicalMoveOutConflictError):
    """A hand-back resolution relies on the move-out record a correction would supersede."""


class PhysicalMoveOutKeyReused(PhysicalMoveOutConflictError):
    pass


class PhysicalMoveOutUnavailableError(RuntimeError):
    """Retain the exact original command when the outcome cannot be established."""


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise PhysicalMoveOutInvalidError(f"{field} must be a nonzero UUID")


def _version(value: int, field: str) -> None:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise PhysicalMoveOutInvalidError(f"{field} must be a positive integer")


def _text(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 500
        or value != value.strip()
        or "\x00" in value
    ):
        raise PhysicalMoveOutInvalidError(f"{field} must be normalized and bounded")


@dataclass(frozen=True, slots=True)
class EndedOccupancy:
    occupancy_id: UUID
    expected_version: int

    def __post_init__(self) -> None:
        _identity(self.occupancy_id, "occupancy_id")
        _version(self.expected_version, "expected_version")

    def intent(self) -> dict[str, object]:
        return {
            "occupancy_id": str(self.occupancy_id),
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class RecordPhysicalMoveOut:
    idempotency_key: UUID
    event_id: UUID
    termination_event_id: UUID
    expected_lease_version: int
    expected_unit_version: int
    actual_move_out_date: date
    unit_condition: str
    occupancies: tuple[EndedOccupancy, ...]
    reason: str
    authorization_reference: str
    evidence_reference: str
    supersedes_event_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "termination_event_id"):
            _identity(getattr(self, field), field)
        for field in ("expected_lease_version", "expected_unit_version"):
            _version(getattr(self, field), field)
        if type(self.actual_move_out_date) is not date:
            raise PhysicalMoveOutInvalidError("actual_move_out_date must be a calendar date")
        if type(self.unit_condition) is not str or self.unit_condition not in MOVE_OUT_CONDITIONS:
            raise PhysicalMoveOutInvalidError("An explicit nonavailable Unit condition is required")
        if (
            type(self.occupancies) is not tuple
            or not 1 <= len(self.occupancies) <= MAX_ENDED_OCCUPANCIES
            or not all(type(item) is EndedOccupancy for item in self.occupancies)
        ):
            raise PhysicalMoveOutInvalidError("Ended Occupancies must be a bounded typed tuple")
        if len({item.occupancy_id for item in self.occupancies}) != len(self.occupancies):
            raise PhysicalMoveOutInvalidError("Ended Occupancy identities must be unique")
        for field in ("reason", "authorization_reference", "evidence_reference"):
            _text(getattr(self, field), field)
        if self.supersedes_event_id is not None:
            _identity(self.supersedes_event_id, "supersedes_event_id")
            if self.supersedes_event_id == self.event_id:
                raise PhysicalMoveOutInvalidError("A successor must reference prior evidence")

    def intent(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "termination_event_id": str(self.termination_event_id),
            "expected_lease_version": self.expected_lease_version,
            "expected_unit_version": self.expected_unit_version,
            "actual_move_out_date": self.actual_move_out_date.isoformat(),
            "unit_condition": self.unit_condition,
            "occupancies": [
                item.intent()
                for item in sorted(self.occupancies, key=lambda item: item.occupancy_id)
            ],
            "reason": self.reason,
            "authorization_reference": self.authorization_reference,
            "evidence_reference": self.evidence_reference,
            "supersedes_event_id": str(self.supersedes_event_id)
            if self.supersedes_event_id
            else None,
        }


def physical_move_out_digest(property_id: UUID, lease_id: UUID, intent: dict[str, object]) -> str:
    body = {
        "action": "lease.move_out.record",
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PhysicalMoveOutResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresPhysicalMoveOutService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, write: bool) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise PhysicalMoveOutAuthorizationError("Physical departure actor is invalid") from exc
        capability = MOVE_OUT_RECORD if write else MOVE_OUT_READ
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if not write:
                raise PhysicalMoveOutNotFoundError("Physical departure resource was not found")
            raise PhysicalMoveOutAuthorizationError(
                "Recording physical departure is not authorized"
            )
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        if error.sqlstate in {"P5N01", "P5401"}:
            return PhysicalMoveOutNotFoundError("Physical departure resource was not found")
        if error.sqlstate == "P5N02":
            return PhysicalMoveOutInvalidError("Physical departure request is invalid")
        if error.sqlstate in {"P5N03", "55P03", "40001", "40P01"}:
            return PhysicalMoveOutConflictError("Physical departure sources changed or are in use")
        if error.sqlstate == "P5N04":
            return PhysicalMoveOutUtilityConflictError(
                "Existing Utility evidence requires responsibility-boundary reconciliation"
            )
        if error.sqlstate == "P5N05":
            return PhysicalMoveOutKeyReused("Physical departure command key was reused")
        if error.sqlstate == "P5N06":
            # The database names the resolution; past decisions are never changed silently.
            return PhysicalMoveOutResolutionReliance(
                error.diag.message_primary
                or "A hand-back resolution relies on this move-out record"
            )
        if error.sqlstate == "P5406":
            return PhysicalMoveOutAuthorizationError("Physical departure actor is not active")
        return PhysicalMoveOutUnavailableError("Physical departure persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise PhysicalMoveOutUnavailableError("Physical departure persistence is unavailable")
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                connection.isolation_level = (
                    IsolationLevel.READ_COMMITTED if write else IsolationLevel.REPEATABLE_READ
                )
                connection.read_only = not write
                connection.execute("SELECT set_config('lock_timeout','3000',true)")
                connection.execute("SELECT set_config('statement_timeout','5000',true)")
                connection.execute("SELECT set_config('TimeZone','UTC',true)")
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise self._error(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise PhysicalMoveOutUnavailableError("Physical departure result is unavailable")
        return cast(dict[str, object], row[0])

    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        _identity(lease_id, "lease_id")
        if (
            type(limit) is not int
            or not 1 <= limit <= 20
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise PhysicalMoveOutInvalidError("Physical departure page is invalid")
        actor_id = self._authorize(actor, property_id, write=False)
        return self._query(
            "SELECT app.physical_move_out_read(%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, limit, offset),
            write=False,
        )

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordPhysicalMoveOut,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> PhysicalMoveOutResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not RecordPhysicalMoveOut:
            raise PhysicalMoveOutInvalidError("Physical departure command is invalid")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise PhysicalMoveOutInvalidError("request_id is invalid")
        actor_id = self._authorize(actor, property_id, write=True)
        intent = command.intent()
        result = self._query(
            "SELECT app.physical_move_out_record(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                actor_id,
                command.idempotency_key,
                physical_move_out_digest(property_id, lease_id, intent),
                Jsonb(intent),
                request_id,
            ),
            write=True,
        )
        body = result.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if (
            type(result.get("status_code")) is not int
            or result["status_code"] != 201
            or not isinstance(body, dict)
            or not isinstance(data, dict)
            or data.get("event_id") != str(command.event_id)
            or data.get("lease_id") != str(lease_id)
            or data.get("property_id") != str(property_id)
            or data.get("financial_completion_assessed") is not False
            or data.get("utility_completion_assessed") is not False
        ):
            raise PhysicalMoveOutUnavailableError("Physical departure response is unavailable")
        return PhysicalMoveOutResponse(201, cast(dict[str, object], body))
