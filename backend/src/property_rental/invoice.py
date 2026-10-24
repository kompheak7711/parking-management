"""Bounded Invoice resources and lifecycle commands."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import IsolationLevel

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.billing import SetInitialRentDueDateCommand
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

INVOICE_READ_CAPABILITY: Final = "invoices.read"
INVOICE_CREATE_CAPABILITY: Final = "invoices.create"
INVOICE_ISSUE_CAPABILITY: Final = "invoices.issue"
INVOICE_ADJUST_CAPABILITY: Final = "invoices.adjust"
INVOICE_VOID_CAPABILITY: Final = "invoices.void"
DAMAGE_CHARGE_BILL_CAPABILITY: Final = "damage_charges.bill"
PROPERTY_MANAGE_CAPABILITY: Final = "property.manage"
LEASE_READ_CAPABILITY: Final = "leases.read"
ONE_TIME_CHARGE_CAPABILITIES: Final = {
    "DAMAGE_CHARGES": DAMAGE_CHARGE_BILL_CAPABILITY,
    "MISCELLANEOUS_CHARGES": INVOICE_CREATE_CAPABILITY,
}
HAND_BACK_RENT_CAPABILITIES: Final = {
    "VOID": INVOICE_VOID_CAPABILITY,
    "CREDIT_ADJUSTMENT": INVOICE_ADJUST_CAPABILITY,
}
INVOICE_CONNECT_TIMEOUT_SECONDS: Final = 3
INVOICE_LOCK_TIMEOUT_MS: Final = 3_000
INVOICE_QUERY_TIMEOUT_MS: Final = 5_000
MAX_INVOICE_PAGE_SIZE: Final = 100
MAX_INVOICE_CURSOR_LENGTH: Final = 256
MAX_INVOICE_EXPECTED_VERSION: Final = 2_147_483_647
NIL_UUID: Final = UUID(int=0)


class AdjustmentType(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class InvoiceNotFoundError(LookupError):
    pass


class InvoiceConflictError(RuntimeError):
    pass


class InvoiceVersionConflict(InvoiceConflictError):
    def __init__(self, current_version: int | None = None) -> None:
        super().__init__("Invoice version precondition failed")
        self.current_version = current_version


class InvoiceIdempotencyKeyReused(InvoiceConflictError):
    pass


class InvoiceLineFullyPaid(InvoiceConflictError):
    """A debit Adjustment needs a positive line balance; bill a one-time charge instead."""

    def __init__(self, line_balance_usd_cents: int | None = None) -> None:
        super().__init__("Invoice line is fully paid")
        self.line_balance_usd_cents = line_balance_usd_cents


class InvoiceInvalidError(ValueError):
    pass


class InvoiceAuthorizationError(PermissionError):
    pass


class InvoiceServiceUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _normalized(value: str, field: str, *, maximum: int = 500) -> None:
    if not value.strip() or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be normalized, nonblank, and bounded")


def _expected_version(value: object) -> None:
    if type(value) is not int:
        raise ValueError(
            f"expected_version must be an integer from 1 to {MAX_INVOICE_EXPECTED_VERSION}"
        )
    expected_version = value
    if not 1 <= expected_version <= MAX_INVOICE_EXPECTED_VERSION:
        raise ValueError(
            f"expected_version must be an integer from 1 to {MAX_INVOICE_EXPECTED_VERSION}"
        )


@dataclass(frozen=True, slots=True)
class CreateInvoiceDraftCommand:
    idempotency_key: UUID
    authorized_obligation_id: UUID

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.authorized_obligation_id, "authorized_obligation_id")


@dataclass(frozen=True, slots=True)
class CorrectInvoiceDraftCommand:
    idempotency_key: UUID
    authorized_obligation_id: UUID
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.authorized_obligation_id, "authorized_obligation_id")
        _normalized(self.reason, "reason")
        _expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class IssueInvoiceCommand:
    idempotency_key: UUID
    expected_version: int
    due_date: date | None = None
    due_date_reason: str | None = None

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _expected_version(self.expected_version)
        if (self.due_date is None) != (self.due_date_reason is None):
            raise ValueError("due_date and due_date_reason must be provided together")
        if self.due_date is not None and type(self.due_date) is not date:
            raise ValueError("due_date must be a calendar date")
        if self.due_date_reason is not None:
            _normalized(self.due_date_reason, "due_date_reason")


@dataclass(frozen=True, slots=True)
class RecordOneTimeChargeCommand:
    """A manual Damage or Miscellaneous charge; Damage bills one inspection finding."""

    charge_id: UUID
    category: str
    customer_id: UUID
    lease_id: UUID | None
    inspection_damage_finding_id: UUID | None
    description: str
    amount_usd_cents: int
    reason: str
    evidence_reference: str

    def __post_init__(self) -> None:
        _identity(self.charge_id, "charge_id")
        _identity(self.customer_id, "customer_id")
        if self.category not in ONE_TIME_CHARGE_CAPABILITIES:
            raise ValueError("category must be DAMAGE_CHARGES or MISCELLANEOUS_CHARGES")
        damage = self.category == "DAMAGE_CHARGES"
        if damage and (self.inspection_damage_finding_id is None or self.lease_id is None):
            raise ValueError("a Damage charge requires its Lease and inspection damage finding")
        if not damage and self.inspection_damage_finding_id is not None:
            raise ValueError("a Miscellaneous charge must not reference a damage finding")
        for value, field in (
            (self.lease_id, "lease_id"),
            (self.inspection_damage_finding_id, "inspection_damage_finding_id"),
        ):
            if value is not None:
                _identity(value, field)
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= 9_000_000_000_000_000
        ):
            raise ValueError("amount_usd_cents must be a bounded positive integer")
        _normalized(self.description, "description", maximum=1000)
        _normalized(self.reason, "reason")
        _normalized(self.evidence_reference, "evidence_reference")


@dataclass(frozen=True, slots=True)
class SetUnitCleaningRateCommand:
    """A new Unit cleaning rate (BR-UNIT-014); it supersedes the current rate, if any."""

    rate_id: UUID
    unit_id: UUID
    expected_current_rate_id: UUID | None
    rate_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _identity(self.rate_id, "rate_id")
        _identity(self.unit_id, "unit_id")
        if self.expected_current_rate_id is not None:
            _identity(self.expected_current_rate_id, "expected_current_rate_id")
        if (
            type(self.rate_usd_cents) is not int
            or not 0 <= self.rate_usd_cents <= 9_000_000_000_000_000
        ):
            raise ValueError("rate_usd_cents must be a bounded nonnegative integer")
        _normalized(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class RecordUnitCleaningChargeCommand:
    """The move-out Unit cleaning charge (BR-MOVEOUT-013) from the Unit's current rate."""

    charge_id: UUID
    lease_id: UUID
    expected_rate_id: UUID

    def __post_init__(self) -> None:
        _identity(self.charge_id, "charge_id")
        _identity(self.lease_id, "lease_id")
        _identity(self.expected_rate_id, "expected_rate_id")


@dataclass(frozen=True, slots=True)
class ResolveHandBackRentCommand:
    """BR-RENT-030 for one monthly Rent Invoice: VOID it, or remove each line's unpaid rest."""

    idempotency_key: UUID
    expected_action: str
    expected_outstanding_usd_cents: int
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        if self.expected_action not in HAND_BACK_RENT_CAPABILITIES:
            raise ValueError("expected_action must be VOID or CREDIT_ADJUSTMENT")
        if (
            type(self.expected_outstanding_usd_cents) is not int
            or not 1 <= self.expected_outstanding_usd_cents <= 9_000_000_000_000_000
        ):
            raise ValueError("expected_outstanding_usd_cents must be a bounded positive integer")
        _normalized(self.reason, "reason")
        _expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class SetOneTimeChargeDueDaysCommand:
    days: int
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        if type(self.days) is not int or not 1 <= self.days <= 90:
            raise ValueError("days must be an integer from 1 to 90")
        _normalized(self.reason, "reason")
        _expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class AdjustInvoiceCommand:
    idempotency_key: UUID
    invoice_line_id: UUID
    adjustment_type: AdjustmentType
    amount_usd_cents: int
    source_reference: str
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _identity(self.invoice_line_id, "invoice_line_id")
        if not isinstance(self.adjustment_type, AdjustmentType):
            raise ValueError("adjustment_type is invalid")
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= 9_000_000_000_000_000
        ):
            raise ValueError("amount_usd_cents must be a bounded positive integer")
        _normalized(self.source_reference, "source_reference")
        _normalized(self.reason, "reason")
        _expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class VoidInvoiceCommand:
    idempotency_key: UUID
    reason: str
    expected_version: int

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
        _normalized(self.reason, "reason")
        _expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class InvoicePage:
    items: tuple[dict[str, object], ...]
    next_cursor: str | None


def invoice_request_digest(
    *,
    action: str,
    property_id: UUID,
    invoice_id: UUID | None,
    payload: dict[str, object],
) -> str:
    """Return a stable digest containing only canonical client intent."""
    serialized = json.dumps(
        {
            "action": action,
            "invoice_id": str(invoice_id) if invoice_id is not None else None,
            "payload": payload,
            "property_id": str(property_id),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _encode_cursor(invoice_date: date, invoice_id: UUID) -> str:
    raw = json.dumps([invoice_date.isoformat(), str(invoice_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def validate_invoice_cursor(value: str | None) -> None:
    if value is not None and len(value) > MAX_INVOICE_CURSOR_LENGTH:
        raise InvoiceInvalidError("Invoice cursor is invalid")


def _decode_cursor(value: str | None) -> tuple[date, UUID] | None:
    if value is None:
        return None
    validate_invoice_cursor(value)
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError
        return date.fromisoformat(str(decoded[0])), UUID(str(decoded[1]))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvoiceInvalidError("Invoice cursor is invalid") from exc


@dataclass(frozen=True, slots=True)
class PostgresInvoiceService:
    database_url: str
    financial_database_url: str | None = None

    @staticmethod
    def _bound_query(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout',%s,true)",
            (str(INVOICE_LOCK_TIMEOUT_MS),),
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout',%s,true)",
            (str(INVOICE_QUERY_TIMEOUT_MS),),
        )

    @staticmethod
    def _actor_id(actor: AuthenticatedActor) -> UUID:
        try:
            value = UUID(actor.actor_id)
        except ValueError as exc:
            raise InvoiceAuthorizationError("Invoice actor identity is invalid") from exc
        _identity(value, "actor_id")
        return value

    @staticmethod
    def _authorize(
        actor: AuthenticatedActor,
        property_id: UUID,
        capability: str,
        *,
        hide: bool = False,
    ) -> None:
        if is_authorized(
            actor,
            AuthorizationRequirement(capability=capability, property_id=str(property_id)),
        ):
            return
        if hide:
            raise InvoiceNotFoundError("Invoice was not found")
        raise InvoiceAuthorizationError("Invoice capability is not authorized")

    @staticmethod
    def _resource(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise InvoiceServiceUnavailableError("Invoice snapshot is unavailable")
        return cast(dict[str, object], value)

    @staticmethod
    def _map_error(exc: psycopg.Error) -> Exception:
        if exc.sqlstate in {"P4501", "P0002"}:
            return InvoiceNotFoundError("Invoice source was not found")
        if exc.sqlstate == "P4505":
            return InvoiceIdempotencyKeyReused("Invoice idempotency key was reused")
        if exc.sqlstate == "P4506":
            return InvoiceAuthorizationError("Invoice actor is not active")
        if exc.sqlstate == "P4504":
            current: int | None = None
            match = re.search(r"Invoice version:(\d+)", str(exc))
            if match is not None:
                current = int(match.group(1))
            return InvoiceVersionConflict(current)
        if exc.sqlstate == "P4509":
            balance = re.search(r"balance:(-?\d+)", str(exc))
            return InvoiceLineFullyPaid(int(balance.group(1)) if balance else None)
        # P5S01: a closed Final Settlement (V1-056 sub-slice 8e-1) is business state.
        if exc.sqlstate in {"P4503", "P4507", "P5S01", "23505", "23P01", "40001", "55P03"}:
            return InvoiceConflictError("Invoice command conflicted")
        if exc.sqlstate in {"P4502", "P4508", "22023", "23503", "23514", "55000"}:
            return InvoiceInvalidError("Invoice command is invalid")
        return InvoiceServiceUnavailableError("Invoice persistence is unavailable")

    def _read_connection(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(
            self.database_url,
            connect_timeout=INVOICE_CONNECT_TIMEOUT_SECONDS,
        )

    def _command_connection(self) -> psycopg.Connection[tuple[object, ...]]:
        if self.financial_database_url is None:
            raise InvoiceServiceUnavailableError("Invoice command persistence is unavailable")
        connection = psycopg.connect(
            self.financial_database_url,
            connect_timeout=INVOICE_CONNECT_TIMEOUT_SECONDS,
        )
        connection.isolation_level = IsolationLevel.READ_COMMITTED
        return connection

    def list(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        status_filter: str | None,
        category: str | None,
        customer_id: UUID | None,
        lease_id: UUID | None,
        limit: int,
        cursor: str | None,
        descending: bool,
    ) -> InvoicePage:
        self._authorize(actor, property_id, INVOICE_READ_CAPABILITY)
        decoded = _decode_cursor(cursor)
        clauses = ["property.id=%s", "app.invoice_property_id(invoice.id)=property.id"]
        parameters: list[object] = [property_id]
        if status_filter is not None:
            clauses.append("invoice.status=%s")
            parameters.append(status_filter)
        if category is not None:
            clauses.append("invoice.primary_category=%s")
            parameters.append(category)
        if customer_id is not None:
            clauses.append("invoice.customer_id=%s")
            parameters.append(customer_id)
        if lease_id is not None:
            clauses.append("invoice.lease_id=%s")
            parameters.append(lease_id)
        direction = "DESC" if descending else "ASC"
        operator = "<" if descending else ">"
        if decoded is not None:
            clauses.append(f"(invoice.invoice_date,invoice.id) {operator} (%s,%s)")
            parameters.extend(decoded)
        parameters.append(limit + 1)
        query = (
            "SELECT app.invoice_resource_snapshot(invoice.id) FROM app.invoices AS invoice "
            "CROSS JOIN app.properties AS property WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY invoice.invoice_date {direction},invoice.id {direction} LIMIT %s"
        )
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                rows = connection.execute(query, tuple(parameters)).fetchall()
                property_exists = connection.execute(
                    "SELECT 1 FROM app.properties WHERE id=%s", (property_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if property_exists is None:
            raise InvoiceNotFoundError("Property was not found")
        resources = tuple(self._resource(row[0]) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and resources:
            last = resources[-1]
            next_cursor = _encode_cursor(
                date.fromisoformat(str(last["invoice_date"])), UUID(str(last["id"]))
            )
        return InvoicePage(resources, next_cursor)

    def get(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        _identity(invoice_id, "invoice_id")
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT app.invoice_resource_snapshot(%s)", (invoice_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None or row[0] is None:
            raise InvoiceNotFoundError("Invoice was not found")
        resource = self._resource(row[0])
        self._authorize(
            actor,
            UUID(str(resource["property_id"])),
            INVOICE_READ_CAPABILITY,
            hide=True,
        )
        return resource

    def property_for_invoice(self, invoice_id: UUID) -> UUID:
        if invoice_id == NIL_UUID:
            raise InvoiceNotFoundError("Invoice was not found")
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT (app.invoice_resource_snapshot(%s)->>'property_id')::uuid",
                    (invoice_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None or row[0] is None:
            raise InvoiceNotFoundError("Invoice was not found")
        return UUID(str(row[0]))

    def _execute(self, query: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with self._command_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(query, parameters).fetchone()
        except (InvoiceServiceUnavailableError, InvoiceAuthorizationError):
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None:
            raise InvoiceServiceUnavailableError("Invoice command returned no result")
        return self._resource(row[0])

    def create_draft(
        self,
        property_id: UUID,
        command: CreateInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self._authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        actor_id = self._actor_id(actor)
        digest = invoice_request_digest(
            action="create",
            property_id=property_id,
            invoice_id=None,
            payload={"authorized_obligation_id": str(command.authorized_obligation_id)},
        )
        return self._execute(
            "SELECT app.create_invoice_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                command.authorized_obligation_id,
                actor_id,
                command.idempotency_key,
                digest,
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            ),
        )

    def correct_draft(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: CorrectInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self._authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        digest = invoice_request_digest(
            action="correct",
            property_id=property_id,
            invoice_id=invoice_id,
            payload={
                "authorized_obligation_id": str(command.authorized_obligation_id),
                "expected_version": command.expected_version,
                "reason": command.reason,
            },
        )
        return self._execute(
            "SELECT app.correct_invoice_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                command.authorized_obligation_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                command.expected_version,
                command.reason,
                uuid4(),
            ),
        )

    def issue(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: IssueInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self._authorize(actor, property_id, INVOICE_ISSUE_CAPABILITY)
        payload: dict[str, object] = {"expected_version": command.expected_version}
        if command.due_date is not None:
            payload["due_date"] = command.due_date.isoformat()
            payload["due_date_reason"] = command.due_date_reason
        digest = invoice_request_digest(
            action="issue",
            property_id=property_id,
            invoice_id=invoice_id,
            payload=payload,
        )
        return self._execute(
            "SELECT app.issue_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                command.expected_version,
                uuid4(),
                uuid4(),
                command.due_date,
                command.due_date_reason,
            ),
        )

    def record_one_time_charge(
        self,
        property_id: UUID,
        command: RecordOneTimeChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the authorized source; an Invoice DRAFT is then created from it."""
        self._authorize(actor, property_id, ONE_TIME_CHARGE_CAPABILITIES[command.category])
        return self._execute(
            "SELECT app.record_one_time_charge(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                self._actor_id(actor),
                command.charge_id,
                command.category,
                command.customer_id,
                command.lease_id,
                command.inspection_damage_finding_id,
                command.description,
                command.amount_usd_cents,
                command.reason,
                command.evidence_reference,
            ),
        )

    def record_unit_cleaning_charge(
        self,
        property_id: UUID,
        command: RecordUnitCleaningChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the cleaning charge source; an Invoice DRAFT is then created from it."""
        self._authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        return self._execute(
            "SELECT app.record_unit_cleaning_charge(%s,%s,%s,%s,%s)",
            (
                property_id,
                self._actor_id(actor),
                command.charge_id,
                command.lease_id,
                command.expected_rate_id,
            ),
        )

    def set_unit_cleaning_rate(
        self,
        property_id: UUID,
        command: SetUnitCleaningRateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Append a Unit cleaning rate; issued cleaning charges keep their amounts."""
        self._authorize(actor, property_id, PROPERTY_MANAGE_CAPABILITY)
        return self._runtime_execute(
            "SELECT app.set_unit_cleaning_rate(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                self._actor_id(actor),
                command.unit_id,
                command.rate_id,
                command.expected_current_rate_id,
                command.rate_usd_cents,
                command.reason,
            ),
        )

    def unit_cleaning_rate(
        self,
        property_id: UUID,
        unit_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object] | None:
        """Return the Unit's current cleaning rate, or None when no rate is configured."""
        if not is_authorized(
            actor,
            AuthorizationRequirement(
                capability=INVOICE_CREATE_CAPABILITY, property_id=str(property_id)
            ),
        ):
            self._authorize(actor, property_id, PROPERTY_MANAGE_CAPABILITY)
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT app.unit_cleaning_rate_current(%s,%s,%s)",
                    (property_id, self._actor_id(actor), unit_id),
                ).fetchone()
        except InvoiceAuthorizationError:
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None:
            raise InvoiceServiceUnavailableError("Unit cleaning rate read returned no result")
        return None if row[0] is None else self._resource(row[0])

    def _runtime_execute(self, query: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(query, parameters).fetchone()
        except InvoiceAuthorizationError:
            raise
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None:
            raise InvoiceServiceUnavailableError("Invoice command returned no result")
        return self._resource(row[0])

    def hand_back_rent_assessment(
        self,
        property_id: UUID,
        invoice_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Show which BR-RENT-030 action applies to a monthly Rent Invoice; changes nothing.

        The answer reveals the Lease termination basis and move-out window, so it needs
        leases.read as well, like the termination Invoice readiness read.
        """
        self._authorize(actor, property_id, INVOICE_READ_CAPABILITY)
        self._authorize(actor, property_id, LEASE_READ_CAPABILITY)
        return self._runtime_execute(
            "SELECT app.hand_back_rent_invoice_assessment(%s,%s,%s)",
            (property_id, self._actor_id(actor), invoice_id),
        )

    def resolve_hand_back_rent(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: ResolveHandBackRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """VOID the Invoice (invoices.void) or remove each line's unpaid rest (invoices.adjust)."""
        self._authorize(actor, property_id, HAND_BACK_RENT_CAPABILITIES[command.expected_action])
        return self._execute(
            "SELECT app.resolve_hand_back_rent_invoice(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                self._actor_id(actor),
                invoice_id,
                command.idempotency_key,
                command.expected_action,
                command.expected_version,
                command.expected_outstanding_usd_cents,
                command.reason,
            ),
        )

    def set_initial_rent_due_date(
        self,
        property_id: UUID,
        command: SetInitialRentDueDateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the authorized Initial Rent Due Date before the Invoice is issued."""
        self._authorize(actor, property_id, INVOICE_ISSUE_CAPABILITY)
        return self._execute(
            "SELECT app.set_initial_rent_due_date(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                command.lease_id,
                self._actor_id(actor),
                command.override_id,
                command.due_date,
                command.reason,
                INVOICE_ISSUE_CAPABILITY,
            ),
        )

    def set_one_time_charge_due_days(
        self,
        property_id: UUID,
        command: SetOneTimeChargeDueDaysCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Change the Property setting; issued Invoices keep their fixed Due Dates."""
        # Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): a Settings item.
        self._authorize(actor, property_id, SETTINGS_MANAGE_CAPABILITY)
        try:
            with self._read_connection() as connection:
                self._bound_query(connection)
                row = connection.execute(
                    "SELECT property_id,one_time_charge_due_days,version "
                    "FROM app.set_one_time_charge_due_days(%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        self._actor_id(actor),
                        command.expected_version,
                        command.days,
                        command.reason,
                        uuid4(),
                    ),
                ).fetchone()
                current = connection.execute(
                    "SELECT version FROM app.properties WHERE id=%s", (property_id,)
                ).fetchone()
        except psycopg.Error as exc:
            raise self._map_error(exc) from exc
        if row is None:
            if current is None:
                raise InvoiceNotFoundError("Property was not found")
            raise InvoiceVersionConflict(int(cast(int, current[0])))
        return {
            "property_id": str(row[0]),
            "one_time_charge_due_days": row[1],
            "version": row[2],
        }

    def adjust(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: AdjustInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self._authorize(actor, property_id, INVOICE_ADJUST_CAPABILITY)
        digest = invoice_request_digest(
            action="adjust",
            property_id=property_id,
            invoice_id=invoice_id,
            payload={
                "adjustment_type": command.adjustment_type.value,
                "amount": {"currency": "USD", "minor_units": command.amount_usd_cents},
                "expected_version": command.expected_version,
                "invoice_line_id": str(command.invoice_line_id),
                "reason": command.reason,
                "source_reference": command.source_reference,
            },
        )
        return self._execute(
            "SELECT app.adjust_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                command.invoice_line_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                command.expected_version,
                command.adjustment_type.value,
                command.amount_usd_cents,
                command.source_reference,
                command.reason,
                uuid4(),
                uuid4(),
            ),
        )

    def void(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: VoidInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        self._authorize(actor, property_id, INVOICE_VOID_CAPABILITY)
        digest = invoice_request_digest(
            action="void",
            property_id=property_id,
            invoice_id=invoice_id,
            payload={"expected_version": command.expected_version, "reason": command.reason},
        )
        return self._execute(
            "SELECT app.void_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                command.expected_version,
                command.reason,
                uuid4(),
                uuid4(),
            ),
        )
