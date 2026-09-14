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

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

INVOICE_READ_CAPABILITY: Final = "invoices.read"
INVOICE_CREATE_CAPABILITY: Final = "invoices.create"
INVOICE_ISSUE_CAPABILITY: Final = "invoices.issue"
INVOICE_ADJUST_CAPABILITY: Final = "invoices.adjust"
INVOICE_VOID_CAPABILITY: Final = "invoices.void"
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

    def __post_init__(self) -> None:
        _identity(self.idempotency_key, "idempotency_key")
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
        if exc.sqlstate in {"P4503", "P4507", "23505", "23P01", "40001", "55P03"}:
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
        digest = invoice_request_digest(
            action="issue",
            property_id=property_id,
            invoice_id=invoice_id,
            payload={"expected_version": command.expected_version},
        )
        return self._execute(
            "SELECT app.issue_invoice(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                invoice_id,
                self._actor_id(actor),
                command.idempotency_key,
                digest,
                command.expected_version,
                uuid4(),
                uuid4(),
            ),
        )

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
