"""Final Utility Invoice at move-out and the explicit catch-up Invoice for a NOT_MOVED_IN period."""

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
from property_rental.invoice import INVOICE_ISSUE_CAPABILITY
from property_rental.utility import UTILITY_CALCULATE_CAPABILITY

FINAL_CAPABILITIES: Final = (INVOICE_ISSUE_CAPABILITY, UTILITY_CALCULATE_CAPABILITY)
CATCH_UP_CAPABILITIES: Final = (INVOICE_ISSUE_CAPABILITY,)
REASONS: Final = frozenset(
    {
        "UTILITY_NOTHING_TO_BILL",
        "UTILITY_LEASE_NOT_TERMINATED",
        "UTILITY_NOT_MOVED_IN",
        "UTILITY_UNRESOLVED_FINAL_INPUT",
        "UTILITY_START_READING_MISSING",
        "UTILITY_EARLIER_READING_NOT_FINALIZED",
        "UTILITY_PERIOD_ALREADY_INVOICED",
        "UTILITY_NOT_RESPONSIBLE",
        "UTILITY_PERIOD_NOT_SKIPPED",
    }
)


class FinalUtilityInvoiceInvalidError(ValueError):
    """The request is invalid; ``reason`` is a stable code when the database named one."""

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class FinalUtilityInvoiceNotFoundError(LookupError):
    pass


class FinalUtilityInvoiceAuthorizationError(PermissionError):
    pass


class FinalUtilityInvoiceConflictError(RuntimeError):
    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class FinalUtilityInvoiceKeyReused(FinalUtilityInvoiceConflictError):
    pass


class FinalUtilityInvoiceUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise FinalUtilityInvoiceInvalidError(f"{field} must be a nonzero UUID")


def _due(due_date: date | None, reason: str | None) -> None:
    if (due_date is None) != (reason is None):
        raise FinalUtilityInvoiceInvalidError("A Due Date override needs a date and a reason")
    if due_date is not None and type(due_date) is not date:
        raise FinalUtilityInvoiceInvalidError("due_date must be a date")
    if reason is not None and (
        not isinstance(reason, str)
        or not 1 <= len(reason) <= 500
        or reason != reason.strip()
        or "\x00" in reason
    ):
        raise FinalUtilityInvoiceInvalidError("due_date_reason must be normalized and bounded")


def _due_intent(due_date: date | None, reason: str | None) -> dict[str, object]:
    return {
        "due_date": due_date.isoformat() if due_date else None,
        "due_date_reason": reason,
    }


@dataclass(frozen=True, slots=True)
class CreateFinalUtilityInvoice:
    """Bill the final Readings and every unbilled period of the Lease in one Invoice."""

    idempotency_key: UUID
    invoice_id: UUID
    final_input_event_id: UUID
    due_date: date | None = None
    due_date_reason: str | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "invoice_id", "final_input_event_id"):
            _identity(getattr(self, field), field)
        _due(self.due_date, self.due_date_reason)

    def intent(self) -> dict[str, object]:
        return {
            "invoice_id": str(self.invoice_id),
            "final_input_event_id": str(self.final_input_event_id),
            **_due_intent(self.due_date, self.due_date_reason),
        }


@dataclass(frozen=True, slots=True)
class CatchUpUtilityInvoice:
    """Bill one period the monthly run skipped as NOT_MOVED_IN once the Lease has an Occupancy."""

    idempotency_key: UUID
    invoice_id: UUID
    consumption_period_id: UUID
    due_date: date | None = None
    due_date_reason: str | None = None

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "invoice_id", "consumption_period_id"):
            _identity(getattr(self, field), field)
        _due(self.due_date, self.due_date_reason)

    def intent(self) -> dict[str, object]:
        return {
            "invoice_id": str(self.invoice_id),
            "consumption_period_id": str(self.consumption_period_id),
            **_due_intent(self.due_date, self.due_date_reason),
        }


def utility_invoice_digest(
    action: str, property_id: UUID, lease_id: UUID, intent: dict[str, object]
) -> str:
    body = {
        "action": action,
        "property_id": str(property_id),
        "lease_id": str(lease_id),
        "intent": intent,
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class UtilityInvoiceResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PostgresFinalUtilityInvoiceService:
    financial_database_url: str

    @staticmethod
    def _authorize(
        actor: AuthenticatedActor, property_id: UUID, capabilities: tuple[str, ...]
    ) -> UUID:
        _identity(property_id, "property_id")
        try:
            actor_id = UUID(actor.actor_id)
            _identity(actor_id, "actor_id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise FinalUtilityInvoiceAuthorizationError("Invoice actor is invalid") from exc
        for capability in capabilities:
            if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
                raise FinalUtilityInvoiceAuthorizationError(
                    "Creating this Utility Invoice is not authorized"
                )
        return actor_id

    @staticmethod
    def _error(error: psycopg.Error) -> Exception:
        message = error.diag.message_primary or ""
        reason = message if message in REASONS else None
        state = error.sqlstate
        if state in {"P5N01", "P5401"}:
            return FinalUtilityInvoiceNotFoundError("Utility Invoice resource was not found")
        if state == "P5N02" or state in {"P4502", "P0002", "23514", "22023"}:
            return FinalUtilityInvoiceInvalidError("Utility Invoice request is invalid", reason)
        if state in {"P5N03", "55P03", "40001", "40P01", "23505"}:
            return FinalUtilityInvoiceConflictError(
                "Utility Invoice sources changed or are in use", reason
            )
        if state == "P5N05":
            return FinalUtilityInvoiceKeyReused("Utility Invoice command key was reused")
        if state in {"P5406", "P4506"}:
            return FinalUtilityInvoiceAuthorizationError("Invoice actor is not active")
        return FinalUtilityInvoiceUnavailableError("Utility Invoice persistence is unavailable")

    def _call(
        self,
        function: str,
        action: str,
        property_id: UUID,
        lease_id: UUID,
        intent: dict[str, object],
        key: UUID,
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]:
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id) is None
        ):
            raise FinalUtilityInvoiceInvalidError("request_id is invalid")
        try:
            with psycopg.connect(self.financial_database_url, connect_timeout=3) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.execute("SELECT set_config('lock_timeout','3000',true)")
                connection.execute("SELECT set_config('statement_timeout','10000',true)")
                connection.execute("SELECT set_config('TimeZone','UTC',true)")
                row = connection.execute(
                    f"SELECT {function}(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        lease_id,
                        actor_id,
                        key,
                        utility_invoice_digest(action, property_id, lease_id, intent),
                        Jsonb(intent),
                        request_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise self._error(exc) from exc
        if row is None or not isinstance(row[0], dict):
            raise FinalUtilityInvoiceUnavailableError("Utility Invoice result is unavailable")
        return cast(dict[str, object], row[0])

    @staticmethod
    def _checked(
        result: dict[str, object], kind: str, invoice_id: UUID, lease_id: UUID, property_id: UUID
    ) -> UtilityInvoiceResponse:
        body = result.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if (
            type(result.get("status_code")) is not int
            or result["status_code"] != 201
            or not isinstance(body, dict)
            or not isinstance(data, dict)
            or data.get("kind") != kind
            or data.get("invoice_id") != str(invoice_id)
            or data.get("lease_id") != str(lease_id)
            or data.get("property_id") != str(property_id)
            or data.get("creates_reading") is not False
        ):
            raise FinalUtilityInvoiceUnavailableError("Utility Invoice response is unavailable")
        return UtilityInvoiceResponse(201, cast(dict[str, object], body))

    def create_final(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CreateFinalUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not CreateFinalUtilityInvoice:
            raise FinalUtilityInvoiceInvalidError("Final Utility Invoice command is invalid")
        actor_id = self._authorize(actor, property_id, FINAL_CAPABILITIES)
        result = self._call(
            "app.utility_final_invoice_create",
            "utility.final_invoice.create",
            property_id,
            lease_id,
            command.intent(),
            command.idempotency_key,
            actor_id,
            request_id,
        )
        return self._checked(result, "FINAL", command.invoice_id, lease_id, property_id)

    def catch_up(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: CatchUpUtilityInvoice,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> UtilityInvoiceResponse:
        _identity(lease_id, "lease_id")
        if type(command) is not CatchUpUtilityInvoice:
            raise FinalUtilityInvoiceInvalidError("Catch-up Utility Invoice command is invalid")
        actor_id = self._authorize(actor, property_id, CATCH_UP_CAPABILITIES)
        result = self._call(
            "app.utility_catch_up_invoice_create",
            "utility.catch_up_invoice.create",
            property_id,
            lease_id,
            command.intent(),
            command.idempotency_key,
            actor_id,
            request_id,
        )
        return self._checked(result, "CATCH_UP", command.invoice_id, lease_id, property_id)
