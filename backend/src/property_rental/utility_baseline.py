"""Utility baseline Readings that start a Customer's Utility responsibility for a Lease."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
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
from property_rental.utility_api import UTILITY_READ_CAPABILITY, UTILITY_READING_RECORD_CAPABILITY

BASELINE_READ: Final = UTILITY_READ_CAPABILITY
BASELINE_RECORD: Final = UTILITY_READING_RECORD_CAPABILITY
MAX_BASELINE_ITEMS: Final = 20


class UtilityBaselineInvalidError(ValueError):
    pass


class UtilityBaselineNotFoundError(LookupError):
    pass


class UtilityBaselineAuthorizationError(PermissionError):
    pass


class UtilityBaselineConflictError(RuntimeError):
    pass


class UtilityBaselineKeyReused(UtilityBaselineConflictError):
    pass


class UtilityBaselineUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise UtilityBaselineInvalidError(f"{field} must be a nonzero UUID")


def _text(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 500
        or value != value.strip()
        or "\x00" in value
    ):
        raise UtilityBaselineInvalidError(f"{field} must be normalized and bounded")


@dataclass(frozen=True, slots=True)
class BaselineItem:
    """One Meter of the Unit and its validated Reading dated on the baseline date."""

    meter_id: UUID
    reading_id: UUID

    def __post_init__(self) -> None:
        _identity(self.meter_id, "meter_id")
        _identity(self.reading_id, "reading_id")

    def intent(self) -> dict[str, object]:
        return {"meter_id": str(self.meter_id), "reading_id": str(self.reading_id)}


@dataclass(frozen=True, slots=True)
class RecordUtilityBaseline:
    idempotency_key: UUID
    event_id: UUID
    baseline_date: date
    items: tuple[BaselineItem, ...]
    reason: str
    evidence_reference: str
    supersedes_event_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "event_id"):
            _identity(getattr(self, field), field)
        if type(self.baseline_date) is not date:
            raise UtilityBaselineInvalidError("baseline_date must be a date")
        if (
            type(self.items) is not tuple
            or not 1 <= len(self.items) <= MAX_BASELINE_ITEMS
            or not all(type(item) is BaselineItem for item in self.items)
        ):
            raise UtilityBaselineInvalidError("items must be a bounded typed tuple")
        if len({item.meter_id for item in self.items}) != len(self.items):
            raise UtilityBaselineInvalidError("Meter identities must be unique")
        for field in ("reason", "evidence_reference"):
            _text(getattr(self, field), field)
        if self.supersedes_event_id is not None:
            _identity(self.supersedes_event_id, "supersedes_event_id")
            if self.supersedes_event_id == self.event_id:
                raise UtilityBaselineInvalidError("A successor must reference prior evidence")

    def intent(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "supersedes_event_id": str(self.supersedes_event_id)
            if self.supersedes_event_id
            else None,
            "baseline_date": self.baseline_date.isoformat(),
            "reason": self.reason,
            "evidence_reference": self.evidence_reference,
            "items": [item.intent() for item in sorted(self.items, key=lambda item: item.meter_id)],
        }


def utility_baseline_digest(property_id: UUID, lease_id: UUID, intent: dict[str, object]) -> str:
    body = {
        "action": "utility.baseline.record",
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class UtilityBaselineResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresUtilityBaselineService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, write: bool) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise UtilityBaselineAuthorizationError("Baseline actor is invalid") from exc
        capability = BASELINE_RECORD if write else BASELINE_READ
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if not write:
                raise UtilityBaselineNotFoundError("Baseline resource was not found")
            raise UtilityBaselineAuthorizationError(
                "Recording a Utility baseline is not authorized"
            )
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        if error.sqlstate in {"P5N01", "P5401"}:
            return UtilityBaselineNotFoundError("Baseline resource was not found")
        if error.sqlstate == "P5N02":
            return UtilityBaselineInvalidError("Baseline request is invalid")
        if error.sqlstate in {"P5N03", "55P03", "40001", "40P01"}:
            return UtilityBaselineConflictError("Baseline sources changed or are in use")
        if error.sqlstate == "P5N05":
            return UtilityBaselineKeyReused("Baseline command key was reused")
        if error.sqlstate == "P5406":
            return UtilityBaselineAuthorizationError("Baseline actor is not active")
        return UtilityBaselineUnavailableError("Baseline persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise UtilityBaselineUnavailableError("Baseline persistence is unavailable")
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
            raise UtilityBaselineUnavailableError("Baseline result is unavailable")
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
            raise UtilityBaselineInvalidError("Baseline page is invalid")
        actor_id = self._authorize(actor, property_id, write=False)
        return self._query(
            "SELECT app.utility_baseline_read(%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, limit, offset),
            write=False,
        )

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordUtilityBaseline,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityBaselineResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not RecordUtilityBaseline:
            raise UtilityBaselineInvalidError("Baseline command is invalid")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise UtilityBaselineInvalidError("request_id is invalid")
        actor_id = self._authorize(actor, property_id, write=True)
        intent = command.intent()
        result = self._query(
            "SELECT app.utility_baseline_record(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                actor_id,
                command.idempotency_key,
                utility_baseline_digest(property_id, lease_id, intent),
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
        ):
            raise UtilityBaselineUnavailableError("Baseline response is unavailable")
        return UtilityBaselineResponse(201, cast(dict[str, object], body))
