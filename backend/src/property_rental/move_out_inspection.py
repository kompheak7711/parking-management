"""Authorized operational inspection evidence, separate from charges and departure."""

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

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

INSPECTION_READ = "leases.read"
INSPECTION_RECORD = "leases.inspect"
MAX_FINDINGS = 50


class MoveOutInspectionInvalidError(ValueError):
    pass


class MoveOutInspectionNotFoundError(LookupError):
    pass


class MoveOutInspectionAuthorizationError(PermissionError):
    pass


class MoveOutInspectionConflictError(RuntimeError):
    pass


class MoveOutInspectionKeyReused(MoveOutInspectionConflictError):
    pass


class MoveOutInspectionUnavailableError(RuntimeError):
    """An uncertain outcome requires retaining the complete original command."""


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise MoveOutInspectionInvalidError(f"{field} must be a nonzero UUID")


def _text(value: str, field: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or "\x00" in value
    ):
        raise MoveOutInspectionInvalidError(f"{field} must be normalized and bounded")


@dataclass(frozen=True, slots=True)
class InspectionFinding:
    finding_id: UUID
    description: str
    pet_related: bool

    def __post_init__(self) -> None:
        _identity(self.finding_id, "finding_id")
        _text(self.description, "description", 1000)
        if type(self.pet_related) is not bool:
            raise MoveOutInspectionInvalidError("pet_related must be a boolean")

    def intent(self) -> dict[str, object]:
        return {
            "finding_id": str(self.finding_id),
            "description": self.description,
            "pet_related": self.pet_related,
        }


@dataclass(frozen=True, slots=True)
class RecordMoveOutInspection:
    idempotency_key: UUID
    inspection_id: UUID
    expected_lease_version: int
    inspection_date: date
    result_text: str
    authorization_reference: str
    evidence_reference: str
    reason: str
    findings: tuple[InspectionFinding, ...]
    supersedes_inspection_id: UUID | None = None

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.inspection_id, "inspection_id")
        if self.supersedes_inspection_id is not None:
            _identity(self.supersedes_inspection_id, "supersedes_inspection_id")
            if self.supersedes_inspection_id == self.inspection_id:
                raise MoveOutInspectionInvalidError("A correction must reference prior evidence")
        if (
            type(self.expected_lease_version) is not int
            or not 1 <= self.expected_lease_version <= 2_147_483_647
        ):
            raise MoveOutInspectionInvalidError("Expected Lease version must be a positive integer")
        if type(self.inspection_date) is not date:
            raise MoveOutInspectionInvalidError("inspection_date must be a calendar date")
        for field, maximum in (
            ("result_text", 5000),
            ("authorization_reference", 500),
            ("evidence_reference", 500),
            ("reason", 500),
        ):
            _text(getattr(self, field), field, maximum)
        if type(self.findings) is not tuple or len(self.findings) > MAX_FINDINGS:
            raise MoveOutInspectionInvalidError("Findings must be an immutable bounded tuple")
        if not all(type(finding) is InspectionFinding for finding in self.findings):
            raise MoveOutInspectionInvalidError("Every finding must contain typed evidence")
        if len({finding.finding_id for finding in self.findings}) != len(self.findings):
            raise MoveOutInspectionInvalidError("Finding identities must be unique")

    def intent(self) -> dict[str, object]:
        return {
            "inspection_id": str(self.inspection_id),
            "expected_lease_version": self.expected_lease_version,
            "inspection_date": self.inspection_date.isoformat(),
            "result_text": self.result_text,
            "authorization_reference": self.authorization_reference,
            "evidence_reference": self.evidence_reference,
            "reason": self.reason,
            "findings": [finding.intent() for finding in self.findings],
            "supersedes_inspection_id": (
                str(self.supersedes_inspection_id)
                if self.supersedes_inspection_id is not None
                else None
            ),
        }


def inspection_request_digest(property_id: UUID, lease_id: UUID, intent: dict[str, object]) -> str:
    body = {
        "action": "lease.inspection.record",
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MoveOutInspectionResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresMoveOutInspectionService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *, write: bool) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise MoveOutInspectionAuthorizationError("Inspection actor is invalid") from exc
        capability = INSPECTION_RECORD if write else INSPECTION_READ
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if not write:
                raise MoveOutInspectionNotFoundError("Inspection resource was not found")
            raise MoveOutInspectionAuthorizationError(
                "Recording inspection evidence is not authorized"
            )
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        if error.sqlstate in {"P5M01", "P5401"}:
            return MoveOutInspectionNotFoundError("Inspection resource was not found")
        if error.sqlstate == "P5M02":
            return MoveOutInspectionInvalidError("Inspection request is invalid")
        if error.sqlstate == "P5M03":
            return MoveOutInspectionConflictError(
                "Lease or inspection evidence changed; refresh it"
            )
        # P5S01: the Lease's Final Settlement is closed, so its inspections are not superseded
        # (V1-056 sub-slice 10c-2a-4); later damage is recorded as a new inspection.
        if error.sqlstate == "P5S01":
            return MoveOutInspectionConflictError(
                "The Final Settlement is closed; record later damage as a new inspection"
            )
        if error.sqlstate == "P5M05":
            return MoveOutInspectionKeyReused("Inspection command key was reused")
        if error.sqlstate == "P5406":
            return MoveOutInspectionAuthorizationError("Inspection actor is not active")
        return MoveOutInspectionUnavailableError("Inspection persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise MoveOutInspectionUnavailableError("Inspection persistence is unavailable")
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
            raise MoveOutInspectionUnavailableError("Inspection result is unavailable")
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
            raise MoveOutInspectionInvalidError("Inspection page is invalid")
        actor_id = self._authorize(actor, property_id, write=False)
        return self._query(
            "SELECT app.move_out_inspection_read(%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, limit, offset),
            write=False,
        )

    def record(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordMoveOutInspection,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> MoveOutInspectionResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not RecordMoveOutInspection:
            raise MoveOutInspectionInvalidError("Inspection command is invalid")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise MoveOutInspectionInvalidError("request_id is invalid")
        actor_id = self._authorize(actor, property_id, write=True)
        intent = command.intent()
        result = self._query(
            "SELECT app.move_out_inspection_record(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                actor_id,
                command.idempotency_key,
                inspection_request_digest(property_id, lease_id, intent),
                Jsonb(intent),
                request_id,
            ),
            write=True,
        )
        body = result.get("body")
        if (
            type(result.get("status_code")) is not int
            or result["status_code"] != 201
            or not isinstance(body, dict)
        ):
            raise MoveOutInspectionUnavailableError("Inspection response is unavailable")
        return MoveOutInspectionResponse(201, cast(dict[str, object], body))
