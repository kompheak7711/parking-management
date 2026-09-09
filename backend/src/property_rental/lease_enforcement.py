"""Separate authorized Lease warnings and Rent-line nonpayment services."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

WARNING_READ = "leases.read"
WARNING_CREATE = "leases.warn"
NONPAYMENT_READ = "rent_nonpayment.read"
NONPAYMENT_OPEN = "rent_nonpayment.case_manage"
NONPAYMENT_EVENT = "rent_nonpayment.event_post"
NIL_UUID = UUID(int=0)


class NonpaymentEventKind(StrEnum):
    TWENTY_DAY_WARNING = "TWENTY_DAY_WARNING"
    THIRTY_DAY_SERIOUS_DEFAULT = "THIRTY_DAY_SERIOUS_DEFAULT"
    CURE = "CURE"
    AUTHORIZED_FOLLOW_UP = "AUTHORIZED_FOLLOW_UP"


class LeaseEnforcementNotFoundError(LookupError):
    pass


class LeaseEnforcementAuthorizationError(PermissionError):
    pass


class LeaseEnforcementInvalidError(ValueError):
    pass


class LeaseEnforcementConflictError(RuntimeError):
    pass


class LeaseEnforcementKeyReused(LeaseEnforcementConflictError):
    pass


class LeaseEnforcementUnavailableError(RuntimeError):
    """The outcome may be unknown; retain exact intent and key for recovery."""


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value == NIL_UUID:
        raise LeaseEnforcementInvalidError(f"{field} must be a nonzero UUID")


def _text(value: str, field: str, maximum: int = 500) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or "\x00" in value
    ):
        raise LeaseEnforcementInvalidError(f"{field} must be normalized, nonblank, and bounded")


@dataclass(frozen=True, slots=True)
class RecordLeaseWarning:
    idempotency_key: UUID
    warning_sequence: int
    violation_date: date
    warning_date: date
    violation_description: str
    lease_provision: str
    communication_record: str
    reason: str

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if type(self.warning_sequence) is not int or not 1 <= self.warning_sequence <= 32767:
            raise LeaseEnforcementInvalidError("warning_sequence must be a positive small integer")
        if type(self.violation_date) is not date or type(self.warning_date) is not date:
            raise LeaseEnforcementInvalidError("Warning dates must be calendar dates")
        for field in ("violation_description", "lease_provision", "communication_record"):
            _text(getattr(self, field), field, 2000)
        _text(self.reason, "reason")

    def intent(self) -> dict[str, object]:
        return {
            "warning_sequence": self.warning_sequence,
            "violation_date": self.violation_date.isoformat(),
            "warning_date": self.warning_date.isoformat(),
            "violation_description": self.violation_description,
            "lease_provision": self.lease_provision,
            "communication_record": self.communication_record,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OpenRentNonpaymentCase:
    idempotency_key: UUID
    rent_invoice_line_id: UUID
    reason: str

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.rent_invoice_line_id, "rent_invoice_line_id")
        _text(self.reason, "reason")

    def intent(self) -> dict[str, object]:
        return {"rent_invoice_line_id": str(self.rent_invoice_line_id), "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RecordRentNonpaymentEvent:
    idempotency_key: UUID
    event_kind: NonpaymentEventKind
    reason: str
    notice_document_reference: str | None = None
    communication_record: str | None = None
    authorization_reference: str | None = None

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if not isinstance(self.event_kind, NonpaymentEventKind):
            raise LeaseEnforcementInvalidError("Nonpayment event kind is invalid")
        _text(self.reason, "reason")
        for field in (
            "notice_document_reference",
            "communication_record",
            "authorization_reference",
        ):
            value = getattr(self, field)
            if value is not None:
                _text(value, field, 2000 if field == "communication_record" else 500)
        if (
            self.event_kind is NonpaymentEventKind.TWENTY_DAY_WARNING
            and self.notice_document_reference is None
        ):
            raise LeaseEnforcementInvalidError("A formal Warning Notice reference is required")
        if (
            self.event_kind is NonpaymentEventKind.AUTHORIZED_FOLLOW_UP
            and self.authorization_reference is None
        ):
            raise LeaseEnforcementInvalidError("An explicit follow-up authorization is required")

    def intent(self) -> dict[str, object]:
        return {
            "event_kind": self.event_kind.value,
            "reason": self.reason,
            "notice_document_reference": self.notice_document_reference,
            "communication_record": self.communication_record,
            "authorization_reference": self.authorization_reference,
        }


@dataclass(frozen=True, slots=True)
class LeaseEnforcementResponse:
    status_code: int
    body: dict[str, object]


def enforcement_request_digest(
    action: str,
    property_id: UUID,
    lease_id: UUID,
    case_id: UUID | None,
    intent: dict[str, object],
) -> str:
    """Bind a stable command key to intent, action and exact resource identities."""
    body = {
        "action": action,
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "case_id": str(case_id) if case_id is not None else None,
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PostgresLeaseEnforcementService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _authorize(
        actor: AuthenticatedActor, property_id: UUID, capability: str, *, hide: bool = False
    ) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise LeaseEnforcementAuthorizationError("Lease enforcement actor is invalid") from exc
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            if hide:
                raise LeaseEnforcementNotFoundError("Lease enforcement resource was not found")
            raise LeaseEnforcementAuthorizationError("Lease enforcement action is not authorized")
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        if error.sqlstate == "P5401":
            return LeaseEnforcementNotFoundError("Lease enforcement resource was not found")
        if error.sqlstate == "P5402":
            return LeaseEnforcementInvalidError("Lease enforcement request is invalid")
        if error.sqlstate == "P5403":
            return LeaseEnforcementConflictError(
                "Lease enforcement action is not currently eligible"
            )
        if error.sqlstate == "P5405":
            return LeaseEnforcementKeyReused("Lease enforcement command key was reused")
        if error.sqlstate == "P5406":
            return LeaseEnforcementAuthorizationError("Lease enforcement actor is not active")
        # Generic integrity, lock, transport and commit errors do not prove no receipt exists.
        return LeaseEnforcementUnavailableError("Lease enforcement persistence is unavailable")

    def _query(
        self, query: str, parameters: tuple[object, ...], *, write: bool
    ) -> dict[str, object]:
        url = self.financial_database_url if write else self.database_url
        if not url:
            raise LeaseEnforcementUnavailableError("Lease enforcement persistence is unavailable")
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.read_only = not write
                connection.execute("SELECT set_config('lock_timeout','3000',true)")
                connection.execute("SELECT set_config('statement_timeout','5000',true)")
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise self._error(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise LeaseEnforcementUnavailableError("Lease enforcement result is unavailable")
        return cast(dict[str, object], row[0])

    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        kind: Literal["WARNINGS", "CASES", "CASE", "EVENTS"],
        *,
        actor: AuthenticatedActor,
        case_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        _identity(lease_id, "lease_id")
        if (
            kind not in {"WARNINGS", "CASES", "CASE", "EVENTS"}
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 1_000_000
        ):
            raise LeaseEnforcementInvalidError("Lease enforcement page is invalid")
        if kind in {"CASE", "EVENTS"}:
            if case_id is None:
                raise LeaseEnforcementInvalidError("case_id is required")
            _identity(case_id, "case_id")
        elif case_id is not None:
            raise LeaseEnforcementInvalidError("case_id is not applicable")
        actor_id = self._authorize(
            actor, property_id, WARNING_READ if kind == "WARNINGS" else NONPAYMENT_READ, hide=True
        )
        return self._query(
            "SELECT app.lease_enforcement_read(%s,%s,%s,%s,%s,%s,%s)",
            (property_id, lease_id, actor_id, kind, case_id, limit, offset),
            write=False,
        )

    def _command(
        self,
        property_id: UUID,
        lease_id: UUID,
        case_id: UUID | None,
        action: Literal["WARNING", "OPEN_CASE", "EVENT"],
        key: UUID,
        intent: dict[str, object],
        request_id: str,
        actor: AuthenticatedActor,
    ) -> LeaseEnforcementResponse:
        _identity(lease_id, "lease_id")
        if case_id is not None:
            _identity(case_id, "case_id")
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise LeaseEnforcementInvalidError("request_id is invalid")
        capability = {
            "WARNING": WARNING_CREATE,
            "OPEN_CASE": NONPAYMENT_OPEN,
            "EVENT": NONPAYMENT_EVENT,
        }[action]
        actor_id = self._authorize(actor, property_id, capability)
        result = self._query(
            "SELECT app.lease_enforcement_command(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                lease_id,
                case_id,
                actor_id,
                action,
                key,
                enforcement_request_digest(action, property_id, lease_id, case_id, intent),
                Jsonb(intent),
                request_id,
            ),
            write=True,
        )
        body = result.get("body")
        if (
            result.get("status_code") != 201
            or not isinstance(body, dict)
            or not isinstance(body.get("data"), dict)
        ):
            raise LeaseEnforcementUnavailableError(
                "Lease enforcement command result is unavailable"
            )
        return LeaseEnforcementResponse(201, cast(dict[str, object], body))

    def record_warning(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordLeaseWarning,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse:
        return self._command(
            property_id,
            lease_id,
            None,
            "WARNING",
            command.idempotency_key,
            command.intent(),
            request_id,
            actor,
        )

    def open_case(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: OpenRentNonpaymentCase,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse:
        return self._command(
            property_id,
            lease_id,
            None,
            "OPEN_CASE",
            command.idempotency_key,
            command.intent(),
            request_id,
            actor,
        )

    def record_event(
        self,
        property_id: UUID,
        lease_id: UUID,
        case_id: UUID,
        command: RecordRentNonpaymentEvent,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse:
        return self._command(
            property_id,
            lease_id,
            case_id,
            "EVENT",
            command.idempotency_key,
            command.intent(),
            request_id,
            actor,
        )
