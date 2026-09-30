"""Rent proration and fixed-Service billing over the protected Invoice boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final, cast
from uuid import UUID

import psycopg
from psycopg import IsolationLevel

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

BILLING_GENERATE_CAPABILITY: Final = "billing.generate"
BILLING_CONNECT_TIMEOUT_SECONDS: Final = 3
BILLING_LOCK_TIMEOUT_MS: Final = 3_000
BILLING_QUERY_TIMEOUT_MS: Final = 5_000
NIL_UUID: Final = UUID(int=0)


class RentBillingKind(StrEnum):
    INITIAL = "INITIAL"
    RECURRING = "RECURRING"


class FinalRentTreatment(StrEnum):
    APPROVED_PARTIAL = "APPROVED_PARTIAL"
    VOLUNTARY_FULL_MONTH = "VOLUNTARY_FULL_MONTH"


class BillingNotFoundError(LookupError):
    pass


class BillingConflictError(RuntimeError):
    pass


class BillingIdempotencyKeyReused(BillingConflictError):
    pass


class BillingInvalidError(ValueError):
    pass


class BillingAuthorizationError(PermissionError):
    pass


class BillingServiceUnavailableError(RuntimeError):
    pass


def _identity(value: UUID, field: str) -> None:
    if value == NIL_UUID:
        raise ValueError(f"{field} must not be the nil UUID")


def _normalized(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be normalized and nonblank")


def month_end(value: date) -> date:
    """Return the last calendar day in ``value``'s month."""

    next_month = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def prorated_monthly_usd_cents(monthly_usd_cents: int, period_start: date, period_end: date) -> int:
    """Calculate inclusive actual-day proration with one final half-up rounding."""

    if monthly_usd_cents <= 0:
        raise ValueError("monthly_usd_cents must be positive")
    if period_end < period_start or period_start.replace(day=1) != period_end.replace(day=1):
        raise ValueError("proration period must stay within one calendar month")
    billable_days = (period_end - period_start).days + 1
    calendar_days = month_end(period_start).day
    amount = Decimal(monthly_usd_cents) * Decimal(billable_days) / Decimal(calendar_days)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def initial_billing_period(lease_start_date: date) -> tuple[date, date, date]:
    """Return Initial Invoice coverage and its proposed Due Date (BR-RENT-005/009)."""

    end = month_end(lease_start_date)
    if lease_start_date.day >= 21:
        end = month_end(end + timedelta(days=1))
    return lease_start_date, end, lease_start_date + timedelta(days=5)


def recurring_billing_period(period_start: date) -> tuple[date, date, date, date]:
    """Return full-month coverage, generation date, and fifth-day Due Date."""

    if period_start.day != 1:
        raise ValueError("recurring period_start must be the first calendar day")
    prior_month = period_start - timedelta(days=1)
    invoice_date = prior_month.replace(day=25)
    return period_start, month_end(period_start), invoice_date, period_start + timedelta(days=4)


def final_rent_usd_cents(
    monthly_usd_cents: int,
    final_period_start: date,
    final_period_end: date,
    treatment: FinalRentTreatment,
) -> int:
    """Calculate the authorized final-month amount without inventing Invoice policy."""

    if not isinstance(treatment, FinalRentTreatment):
        raise ValueError("final Rent treatment is invalid")
    if monthly_usd_cents <= 0:
        raise ValueError("monthly_usd_cents must be positive")
    if final_period_end < final_period_start or final_period_start.replace(
        day=1
    ) != final_period_end.replace(day=1):
        raise ValueError("final Rent period must stay within one calendar month")
    if treatment is FinalRentTreatment.VOLUNTARY_FULL_MONTH:
        return monthly_usd_cents
    return prorated_monthly_usd_cents(monthly_usd_cents, final_period_start, final_period_end)


def final_service_usd_cents(
    monthly_usd_cents: int,
    final_period_start: date,
    final_period_end: date,
    treatment: FinalRentTreatment,
) -> int:
    """Calculate an approved final fixed-Service charge for the covered month."""

    return final_rent_usd_cents(
        monthly_usd_cents,
        final_period_start,
        final_period_end,
        treatment,
    )


@dataclass(frozen=True, slots=True)
class GenerateRentInvoiceCommand:
    idempotency_key: UUID
    invoice_id: UUID
    invoice_number: str
    lease_id: UUID
    billing_kind: RentBillingKind
    period_start: date
    issued_at: datetime
    source_occupancy_id: UUID | None = None
    originating_billing_run_attempt_id: UUID | None = None
    authorization_reference: str = BILLING_GENERATE_CAPABILITY

    def __post_init__(self) -> None:
        for field in ("idempotency_key", "invoice_id", "lease_id"):
            _identity(getattr(self, field), field)
        if self.source_occupancy_id is not None:
            _identity(self.source_occupancy_id, "source_occupancy_id")
        if self.originating_billing_run_attempt_id is not None:
            _identity(
                self.originating_billing_run_attempt_id,
                "originating_billing_run_attempt_id",
            )
        _normalized(self.invoice_number, "invoice_number")
        if len(self.invoice_number) > 100:
            raise ValueError("invoice_number must not exceed 100 characters")
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        if not isinstance(self.billing_kind, RentBillingKind):
            raise ValueError("billing_kind must be a RentBillingKind")
        if self.source_occupancy_id is not None:
            raise ValueError("rent billing references the signed Lease, not source_occupancy_id")
        if self.billing_kind is RentBillingKind.RECURRING and self.period_start.day != 1:
            raise ValueError("recurring period_start must be the first calendar day")


def billing_request_digest(command: GenerateRentInvoiceCommand) -> str:
    payload = json.dumps(
        {
            "authorization_reference": command.authorization_reference,
            "billing_kind": command.billing_kind.value,
            "idempotency_key": str(command.idempotency_key),
            "invoice_id": str(command.invoice_id),
            "invoice_number": command.invoice_number,
            "issued_at": command.issued_at.astimezone(UTC).isoformat(),
            "lease_id": str(command.lease_id),
            "originating_billing_run_attempt_id": (
                str(command.originating_billing_run_attempt_id)
                if command.originating_billing_run_attempt_id is not None
                else None
            ),
            "period_start": command.period_start.isoformat(),
            "source_occupancy_id": (
                str(command.source_occupancy_id)
                if command.source_occupancy_id is not None
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RentInvoiceSnapshot:
    invoice_id: UUID
    property_id: UUID
    lease_id: UUID
    customer_id: UUID
    billing_kind: RentBillingKind
    invoice_date: date
    due_date: date
    period_start: date
    period_end: date
    rent_usd_cents: int
    service_usd_cents: int
    total_usd_cents: int
    service_line_count: int
    status: str


def _snapshot(row: tuple[object, ...]) -> RentInvoiceSnapshot:
    value = cast(dict[str, object], row[0])
    return RentInvoiceSnapshot(
        invoice_id=UUID(str(value["invoice_id"])),
        property_id=UUID(str(value["property_id"])),
        lease_id=UUID(str(value["lease_id"])),
        customer_id=UUID(str(value["customer_id"])),
        billing_kind=RentBillingKind(str(value["billing_kind"])),
        invoice_date=date.fromisoformat(str(value["invoice_date"])),
        due_date=date.fromisoformat(str(value["due_date"])),
        period_start=date.fromisoformat(str(value["period_start"])),
        period_end=date.fromisoformat(str(value["period_end"])),
        rent_usd_cents=int(str(value["rent_usd_cents"])),
        service_usd_cents=int(str(value["service_usd_cents"])),
        total_usd_cents=int(str(value["total_usd_cents"])),
        service_line_count=int(str(value["service_line_count"])),
        status=str(value["status"]),
    )


@dataclass(frozen=True, slots=True)
class PostgresRentBillingService:
    financial_database_url: str
    property_id: UUID
    actor_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id, "property_id")
        _identity(self.actor_id, "actor_id")

    def generate(
        self, command: GenerateRentInvoiceCommand, *, actor: AuthenticatedActor
    ) -> RentInvoiceSnapshot:
        try:
            authenticated_actor_id = UUID(actor.actor_id)
        except ValueError as exc:
            raise BillingAuthorizationError("Billing actor is invalid") from exc
        if (
            authenticated_actor_id != self.actor_id
            or command.authorization_reference != BILLING_GENERATE_CAPABILITY
            or not is_authorized(
                actor,
                AuthorizationRequirement(
                    capability=BILLING_GENERATE_CAPABILITY,
                    property_id=str(self.property_id),
                ),
            )
        ):
            raise BillingAuthorizationError("Billing capability is not authorized")
        try:
            with psycopg.connect(
                self.financial_database_url,
                connect_timeout=BILLING_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                connection.isolation_level = IsolationLevel.READ_COMMITTED
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout',%s,true)",
                    (str(BILLING_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout',%s,true)",
                    (str(BILLING_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(
                    "SELECT app.generate_rent_service_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.property_id,
                        command.idempotency_key,
                        billing_request_digest(command),
                        command.invoice_id,
                        command.invoice_number,
                        command.lease_id,
                        command.source_occupancy_id,
                        command.billing_kind,
                        command.period_start,
                        command.issued_at.astimezone(UTC),
                        self.actor_id,
                        command.originating_billing_run_attempt_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "P0002":
                raise BillingNotFoundError("Billing source was not found") from exc
            if exc.sqlstate == "55000" and "active" in str(exc).lower():
                raise BillingAuthorizationError("Billing actor is no longer active") from exc
            if exc.sqlstate == "23505" and "idempotency key" in str(exc).lower():
                raise BillingIdempotencyKeyReused("Billing idempotency key was reused") from exc
            if exc.sqlstate in {"23505", "23P01", "40001"}:
                raise BillingConflictError("Billing command conflicted") from exc
            if exc.sqlstate in {"22023", "23514", "55000"}:
                raise BillingInvalidError("Billing command is invalid") from exc
            raise BillingServiceUnavailableError("Billing persistence is unavailable") from exc
        if row is None:
            raise BillingServiceUnavailableError("Billing command returned no result")
        return _snapshot(row)


@dataclass(frozen=True, slots=True)
class SetInitialRentDueDateCommand:
    """An authorized Initial Rent Due Date that replaces the proposed Lease Start + 5 days."""

    override_id: UUID
    lease_id: UUID
    due_date: date
    reason: str

    def __post_init__(self) -> None:
        _identity(self.override_id, "override_id")
        _identity(self.lease_id, "lease_id")
        if type(self.due_date) is not date:
            raise ValueError("due_date must be a calendar date")
        _normalized(self.reason, "reason")
        if len(self.reason) > 500:
            raise ValueError("reason must not exceed 500 characters")


def set_initial_rent_due_date(
    service: PostgresRentBillingService,
    command: SetInitialRentDueDateCommand,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    """Record the authorized Due Date before the Initial Rent Invoice is issued."""

    try:
        authenticated_actor_id = UUID(actor.actor_id)
    except ValueError as exc:
        raise BillingAuthorizationError("Billing actor is invalid") from exc
    if authenticated_actor_id != service.actor_id or not is_authorized(
        actor,
        AuthorizationRequirement(
            capability=BILLING_GENERATE_CAPABILITY, property_id=str(service.property_id)
        ),
    ):
        raise BillingAuthorizationError("Billing capability is not authorized")
    try:
        with psycopg.connect(
            service.financial_database_url, connect_timeout=BILLING_CONNECT_TIMEOUT_SECONDS
        ) as connection:
            connection.isolation_level = IsolationLevel.READ_COMMITTED
            connection.execute(
                "SELECT pg_catalog.set_config('lock_timeout',%s,true)",
                (str(BILLING_LOCK_TIMEOUT_MS),),
            )
            row = connection.execute(
                "SELECT app.set_initial_rent_due_date(%s,%s,%s,%s,%s,%s)",
                (
                    service.property_id,
                    command.lease_id,
                    service.actor_id,
                    command.override_id,
                    command.due_date,
                    command.reason,
                ),
            ).fetchone()
    except psycopg.Error as exc:
        if exc.sqlstate == "P0002":
            raise BillingNotFoundError("Lease was not found") from exc
        if exc.sqlstate == "23505":
            raise BillingIdempotencyKeyReused("Due Date override identity was reused") from exc
        if exc.sqlstate in {"22023", "55000"}:
            raise BillingInvalidError("Due Date override is invalid") from exc
        raise BillingServiceUnavailableError("Billing persistence is unavailable") from exc
    if row is None or not isinstance(row[0], dict):
        raise BillingServiceUnavailableError("Due Date override returned no result")
    return cast(dict[str, object], row[0])
