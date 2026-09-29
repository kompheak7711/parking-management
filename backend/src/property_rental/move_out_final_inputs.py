"""Final Utility inputs for a physical departure, referencing existing Readings only."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.types.json import Jsonb

from property_rental.identity import (
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.physical_move_out import MOVE_OUT_READ, MOVE_OUT_RECORD

FINAL_INPUTS_READ: Final = MOVE_OUT_READ
FINAL_INPUTS_RECORD: Final = MOVE_OUT_RECORD
MAX_FINAL_INPUT_ITEMS: Final = 20
RESOLUTIONS: Final = frozenset({"READING", "ESTIMATE", "UNRESOLVED"})
UNRESOLVED_REASONS: Final = frozenset(
    {"MISSING_READING", "READING_NOT_VALIDATED", "BROKEN_METER_ESTIMATE_PENDING"}
)


class MoveOutFinalInputsInvalidError(ValueError):
    pass


class MoveOutFinalInputsNotFoundError(LookupError):
    pass


class MoveOutFinalInputsAuthorizationError(PermissionError):
    pass


class MoveOutFinalInputsConflictError(RuntimeError):
    pass


class MoveOutFinalInputsKeyReused(MoveOutFinalInputsConflictError):
    pass


class MoveOutFinalInputsUnavailableError(RuntimeError):
    """Retain the exact original command when the outcome cannot be established."""


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise MoveOutFinalInputsInvalidError(f"{field} must be a nonzero UUID")


def _text(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 500
        or value != value.strip()
        or "\x00" in value
    ):
        raise MoveOutFinalInputsInvalidError(f"{field} must be normalized and bounded")


@dataclass(frozen=True, slots=True)
class FinalInputItem:
    """One applicable Meter resolved by an existing source, or explicitly unresolved."""

    meter_id: UUID
    resolution: str
    reading_id: UUID | None = None
    estimate_id: UUID | None = None
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        _identity(self.meter_id, "meter_id")
        if type(self.resolution) is not str or self.resolution not in RESOLUTIONS:
            raise MoveOutFinalInputsInvalidError("resolution is not supported")
        for field in ("reading_id", "estimate_id"):
            value = getattr(self, field)
            if value is not None:
                _identity(value, field)
        expected = {
            "READING": (True, False, False),
            "ESTIMATE": (False, True, False),
            "UNRESOLVED": (False, False, True),
        }[self.resolution]
        present = (
            self.reading_id is not None,
            self.estimate_id is not None,
            self.unresolved_reason is not None,
        )
        if present != expected:
            raise MoveOutFinalInputsInvalidError("item fields do not match its resolution")
        if self.unresolved_reason is not None and (
            type(self.unresolved_reason) is not str
            or self.unresolved_reason not in UNRESOLVED_REASONS
        ):
            raise MoveOutFinalInputsInvalidError("unresolved_reason is not supported")

    def intent(self) -> dict[str, object]:
        return {
            "meter_id": str(self.meter_id),
            "resolution": self.resolution,
            "reading_id": str(self.reading_id) if self.reading_id else None,
            "estimate_id": str(self.estimate_id) if self.estimate_id else None,
            "unresolved_reason": self.unresolved_reason,
        }


@dataclass(frozen=True, slots=True)
class RecordMoveOutFinalInputs:
    idempotency_key: UUID
    event_id: UUID
    move_out_event_id: UUID
    items: tuple[FinalInputItem, ...]
    reason: str
    authorization_reference: str
    evidence_reference: str
    supersedes_event_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id", "move_out_event_id"):
            _identity(getattr(self, field), field)
        if (
            type(self.items) is not tuple
            or not 1 <= len(self.items) <= MAX_FINAL_INPUT_ITEMS
            or not all(type(item) is FinalInputItem for item in self.items)
        ):
            raise MoveOutFinalInputsInvalidError("items must be a bounded typed tuple")
        if len({item.meter_id for item in self.items}) != len(self.items):
            raise MoveOutFinalInputsInvalidError("Meter identities must be unique")
        for field in ("reason", "authorization_reference", "evidence_reference"):
            _text(getattr(self, field), field)
        if self.supersedes_event_id is not None:
            _identity(self.supersedes_event_id, "supersedes_event_id")
            if self.supersedes_event_id == self.event_id:
                raise MoveOutFinalInputsInvalidError("A successor must reference prior evidence")

    def intent(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "move_out_event_id": str(self.move_out_event_id),
            "supersedes_event_id": str(self.supersedes_event_id)
            if self.supersedes_event_id
            else None,
            "reason": self.reason,
            "authorization_reference": self.authorization_reference,
            "evidence_reference": self.evidence_reference,
            "items": [item.intent() for item in sorted(self.items, key=lambda item: item.meter_id)],
        }


def move_out_final_inputs_digest(
    property_id: UUID, lease_id: UUID, intent: dict[str, object]
) -> str:
    body = {
        "action": "lease.move_out.final_inputs.record",
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MoveOutFinalInputsResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresMoveOutFinalInputsService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, write: bool) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise MoveOutFinalInputsAuthorizationError("Final input actor is invalid") from exc
        capability = FINAL_INPUTS_RECORD if write else FINAL_INPUTS_READ
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if not write:
                raise MoveOutFinalInputsNotFoundError("Final input resource was not found")
            raise MoveOutFinalInputsAuthorizationError(
                "Recording final Utility inputs is not authorized"
            )
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        if error.sqlstate in {"P5N01", "P5401"}:
            return MoveOutFinalInputsNotFoundError("Final input resource was not found")
        if error.sqlstate == "P5N02":
            return MoveOutFinalInputsInvalidError("Final input request is invalid")
        if error.sqlstate in {"P5N03", "55P03", "40001", "40P01"}:
            return MoveOutFinalInputsConflictError("Final input sources changed or are in use")
        if error.sqlstate == "P5N05":
            return MoveOutFinalInputsKeyReused("Final input command key was reused")
        if error.sqlstate == "P5406":
            return MoveOutFinalInputsAuthorizationError("Final input actor is not active")
        return MoveOutFinalInputsUnavailableError("Final input persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise MoveOutFinalInputsUnavailableError("Final input persistence is unavailable")
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
            raise MoveOutFinalInputsUnavailableError("Final input result is unavailable")
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
            raise MoveOutFinalInputsInvalidError("Final input page is invalid")
        actor_id = self._authorize(actor, property_id, write=False)
        return self._query(
            "SELECT app.move_out_final_inputs_read(%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, limit, offset),
            write=False,
        )

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordMoveOutFinalInputs,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> MoveOutFinalInputsResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not RecordMoveOutFinalInputs:
            raise MoveOutFinalInputsInvalidError("Final input command is invalid")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise MoveOutFinalInputsInvalidError("request_id is invalid")
        actor_id = self._authorize(actor, property_id, write=True)
        intent = command.intent()
        result = self._query(
            "SELECT app.move_out_final_inputs_record(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                actor_id,
                command.idempotency_key,
                move_out_final_inputs_digest(property_id, lease_id, intent),
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
            or data.get("creates_reading") is not False
            or data.get("creates_charge") is not False
            or data.get("financial_completion_assessed") is not False
            or data.get("utility_completion_assessed") is not False
        ):
            raise MoveOutFinalInputsUnavailableError("Final input response is unavailable")
        return MoveOutFinalInputsResponse(201, cast(dict[str, object], body))
