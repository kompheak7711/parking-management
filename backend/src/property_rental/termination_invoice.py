"""Original Invoice coverage and current balances for an explicit termination review.

This observation neither authorizes a correction nor assesses every dependency.
Each page is a separate database snapshot; pages must not imply financial completion.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.lease import LeaseStatus


class TerminationInvoiceAuthorizationError(PermissionError):
    pass


class TerminationInvoiceNotFoundError(LookupError):
    pass


class TerminationInvoiceUnavailableError(RuntimeError):
    pass


class OriginalRentCoverage(StrEnum):
    NOT_TERMINATED = "NOT_TERMINATED"
    SIGNED_TERMS_REVIEW_REQUIRED = "SIGNED_TERMS_REVIEW_REQUIRED"
    VOID_HISTORY = "VOID_HISTORY"
    NON_RENT_SOURCE_REVIEW = "NON_RENT_SOURCE_REVIEW"
    BEFORE_FINAL_MONTH = "BEFORE_FINAL_MONTH"
    FINAL_MONTH = "FINAL_MONTH"
    LATER_MONTHS = "LATER_MONTHS"
    FINAL_AND_LATER_MONTHS = "FINAL_AND_LATER_MONTHS"


@dataclass(frozen=True, slots=True)
class InvoiceCalculationComponent:
    id: UUID
    sequence: int
    kind: str
    period_start: date
    period_end: date
    contractual_monthly_usd_cents: int | None
    service_monthly_rate_usd_cents: int | None
    amount_usd_cents: int


@dataclass(frozen=True, slots=True)
class TerminationInvoiceLine:
    invoice_line_id: UUID
    invoice_id: UUID
    customer_id: UUID
    invoice_version: int
    invoice_status: str
    issued: bool
    rent_billing_kind: str | None
    category: str
    period_start: date | None
    period_end: date | None
    source_type: str
    source_id: UUID
    original_usd_cents: int
    adjusted_usd_cents: int
    payment_applied_usd_cents: int
    credit_applied_usd_cents: int
    deposit_applied_usd_cents: int
    outstanding_usd_cents: int
    active_adjustment_count: int
    components: tuple[InvoiceCalculationComponent, ...]
    original_rent_coverage: OriginalRentCoverage


@dataclass(frozen=True, slots=True)
class TerminationInvoiceReadiness:
    lease_id: UUID
    property_id: UUID
    primary_tenant_id: UUID
    lease_status: str
    lease_start_date: date
    lease_end_date: date
    actual_termination_date: date | None
    termination_event_id: UUID | None
    evidence_status: str
    observed_at: datetime
    contractual_monthly_usd_cents: int | None
    full_final_month_rent_usd_cents: int | None
    items: tuple[TerminationInvoiceLine, ...]
    next_cursor: UUID | None
    currency: str = "USD"
    financial_completion_assessed: bool = False
    financial_dependencies_fully_assessed: bool = False


def _identity(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("A nonzero UUID is required")
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("Invalid response identity")
    identity = _identity(UUID(value))
    if str(identity) != value:
        raise ValueError("Invalid response identity")
    return identity


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid response amount or version")
    return value


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("Invalid response date")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("Invalid response date")
    return result


def _shape(value: object, keys: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("Invalid response shape")
    return cast(dict[str, object], value)


def _choice(value: object, values: set[str]) -> str:
    if not isinstance(value, str) or value not in values:
        raise ValueError("Invalid response enum")
    return value


def _optional_money(value: object) -> int | None:
    return None if value is None else _integer(value, minimum=1)


def _components(
    value: object,
    *,
    period_start: date | None,
    period_end: date | None,
    original: int,
    issued: bool,
    category: str,
) -> tuple[InvoiceCalculationComponent, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Invalid component bound")
    components: list[InvoiceCalculationComponent] = []
    for raw in value:
        row = _shape(
            raw,
            "id sequence kind period_start period_end contractual_monthly_usd_cents "
            "service_monthly_rate_usd_cents amount_usd_cents",
        )
        component = InvoiceCalculationComponent(
            _uuid(row["id"]),
            _integer(row["sequence"], minimum=1, maximum=32767),
            _choice(
                row["kind"],
                {
                    "PRORATED_MOVE_IN_MONTH",
                    "FULL_FOLLOWING_MONTH",
                    "FULL_RECURRING_MONTH",
                    "OTHER_APPROVED_COMPONENT",
                },
            ),
            _date(row["period_start"]),
            _date(row["period_end"]),
            _optional_money(row["contractual_monthly_usd_cents"]),
            _optional_money(row["service_monthly_rate_usd_cents"]),
            _integer(row["amount_usd_cents"], minimum=1),
        )
        if component.period_end < component.period_start:
            raise ValueError("Invalid component period")
        if components and component.sequence <= components[-1].sequence:
            raise ValueError("Invalid component order")
        components.append(component)
    if len({c.id for c in components}) != len(components):
        raise ValueError("Duplicate component identity")
    if issued:
        if bool(components) != (category in {"RENT", "SERVICE_CHARGES"}):
            raise ValueError("Issued component evidence contradicts line category")
        for component in components:
            if category == "RENT" and (
                component.contractual_monthly_usd_cents is None
                or component.service_monthly_rate_usd_cents is not None
            ):
                raise ValueError("Rent component rate evidence is incompatible")
            if category == "SERVICE_CHARGES" and (
                component.contractual_monthly_usd_cents is not None
                or component.service_monthly_rate_usd_cents is None
            ):
                raise ValueError("Service component rate evidence is incompatible")
    if components and issued:
        ordered = sorted(components, key=lambda c: c.period_start)
        if (
            ordered[0].period_start != period_start
            or ordered[-1].period_end != period_end
            or sum(c.amount_usd_cents for c in ordered) != original
            or any(a.period_end + timedelta(days=1) != b.period_start for a, b in pairwise(ordered))
        ):
            raise ValueError("Issued component coverage is inconsistent")
    return tuple(components)


def _coverage(
    evidence: str,
    actual: date | None,
    category: str,
    status: str,
    period_start: date | None,
    period_end: date | None,
) -> OriginalRentCoverage:
    if status == "VOID":
        return OriginalRentCoverage.VOID_HISTORY
    if evidence == "NO_TERMINATION":
        return OriginalRentCoverage.NOT_TERMINATED
    if evidence != "VOLUNTARY_EARLY_VERIFIED":
        return OriginalRentCoverage.SIGNED_TERMS_REVIEW_REQUIRED
    if category != "RENT":
        return OriginalRentCoverage.NON_RENT_SOURCE_REVIEW
    if actual is None or period_start is None or period_end is None:
        raise ValueError("Rent coverage requires actual dates")
    first = actual.replace(day=1)
    last = actual.replace(day=monthrange(actual.year, actual.month)[1])
    if period_end < first:
        return OriginalRentCoverage.BEFORE_FINAL_MONTH
    if period_start > last:
        return OriginalRentCoverage.LATER_MONTHS
    if period_end > last:
        return OriginalRentCoverage.FINAL_AND_LATER_MONTHS
    return OriginalRentCoverage.FINAL_MONTH


def parse_termination_invoice_readiness(
    value: object,
    *,
    lease_id: UUID,
    property_id: UUID,
    limit: int,
    after_line_id: UUID | None = None,
) -> TerminationInvoiceReadiness:
    """Validate one bounded observation; never infer a correction amount or approval."""
    try:
        _identity(lease_id)
        _identity(property_id)
        _integer(limit, minimum=1, maximum=100)
        if after_line_id is not None:
            _identity(after_line_id)
        root = _shape(
            value,
            "lease_id property_id primary_tenant_id lease_status lease_start_date "
            "lease_end_date actual_termination_date termination_event_id evide"
            "nce_status observed_at "
            "contractual_monthly_usd_cents full_final_month_rent_usd_cents currency "
            "financial_completion_assessed financial_dependencies_fully_assessed items next_cursor",
        )
        if _uuid(root["lease_id"]) != lease_id or _uuid(root["property_id"]) != property_id:
            raise ValueError("Invalid response scope")
        primary_tenant = _uuid(root["primary_tenant_id"])
        status = _choice(root["lease_status"], {item.value for item in LeaseStatus})
        evidence = _choice(
            root["evidence_status"],
            {"NO_TERMINATION", "VOLUNTARY_EARLY_VERIFIED", "SIGNED_TERMS_REVIEW_REQUIRED"},
        )
        start, end = _date(root["lease_start_date"]), _date(root["lease_end_date"])
        actual = (
            None
            if root["actual_termination_date"] is None
            else _date(root["actual_termination_date"])
        )
        event = (
            None if root["termination_event_id"] is None else _uuid(root["termination_event_id"])
        )
        monthly = _optional_money(root["contractual_monthly_usd_cents"])
        final_month = _optional_money(root["full_final_month_rent_usd_cents"])
        if (
            end < start
            or (status == "TERMINATED") != (actual is not None)
            or (evidence == "NO_TERMINATION") != (status != "TERMINATED")
            or (status != "TERMINATED" and event is not None)
            or (actual is not None and actual < start)
        ):
            raise ValueError("Invalid termination state")
        if evidence == "VOLUNTARY_EARLY_VERIFIED":
            if (
                event is None
                or actual is None
                or actual >= end
                or monthly is None
                or final_month != monthly
            ):
                raise ValueError("Unsupported full-month Rent claim")
        elif final_month is not None:
            raise ValueError("Unsupported full-month Rent claim")
        raw_time = root["observed_at"]
        if not isinstance(raw_time, str):
            raise ValueError("Invalid observation timestamp")
        observed = datetime.fromisoformat(raw_time)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("Observation needs a timezone")
        if (
            root["currency"] != "USD"
            or root["financial_completion_assessed"] is not False
            or root["financial_dependencies_fully_assessed"] is not False
        ):
            raise ValueError("Unsupported financial claim")
        rows = root["items"]
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("Invalid page bound")
        items: list[TerminationInvoiceLine] = []
        previous = after_line_id
        sources = {
            "RENT": "LEASE",
            "UTILITIES": "UTILITY_CONSUMPTION_PERIOD",
            "SERVICE_CHARGES": "PROPERTY_SERVICE",
            "DAMAGE_CHARGES": "AUTHORIZED_NONRECURRING_OBLIGATION",
            "MISCELLANEOUS_CHARGES": "AUTHORIZED_NONRECURRING_OBLIGATION",
        }
        for raw in rows:
            row = _shape(
                raw,
                "invoice_line_id invoice_id customer_id invoice_version invoice_status issued "
                "rent_billing_kind category period_start period_end source_type so"
                "urce_id original_usd_cents "
                "adjusted_usd_cents payment_applied_usd_cents credit_applied_usd_c"
                "ents deposit_applied_usd_cents outstanding_usd_cents "
                "active_adjustment_count components",
            )
            line_id, invoice_id = _uuid(row["invoice_line_id"]), _uuid(row["invoice_id"])
            customer = _uuid(row["customer_id"])
            if previous is not None and line_id <= previous:
                raise ValueError("Invalid page order")
            previous = line_id
            invoice_status = _choice(
                row["invoice_status"], {"DRAFT", "UNPAID", "PARTIALLY_PAID", "PAID", "VOID"}
            )
            issued = row["issued"]
            if (
                type(issued) is not bool
                or (invoice_status == "DRAFT" and issued)
                or (invoice_status not in {"DRAFT", "VOID"} and not issued)
            ):
                raise ValueError("Invalid issuance state")
            category = _choice(row["category"], set(sources))
            source_id = _uuid(row["source_id"])
            if row["source_type"] != sources[category] or (
                category == "RENT" and source_id != lease_id
            ):
                raise ValueError("Invalid source identity")
            kind = (
                None
                if row["rent_billing_kind"] is None
                else _choice(row["rent_billing_kind"], {"INITIAL", "RECURRING"})
            )
            begin = None if row["period_start"] is None else _date(row["period_start"])
            finish = None if row["period_end"] is None else _date(row["period_end"])
            if (begin is None) != (finish is None) or (
                begin is not None and finish is not None and finish < begin
            ):
                raise ValueError("Invalid line period")
            if category == "RENT" and (begin is None or kind is None):
                raise ValueError("Rent source needs its billing period")
            original = _integer(row["original_usd_cents"], minimum=1)
            adjusted = _integer(row["adjusted_usd_cents"])
            payment, credit, deposit = (
                _integer(row["payment_applied_usd_cents"]),
                _integer(row["credit_applied_usd_cents"]),
                _integer(row["deposit_applied_usd_cents"]),
            )
            applied = payment + credit + deposit
            outstanding = _integer(row["outstanding_usd_cents"])
            if adjusted < applied or outstanding != (
                0 if invoice_status in {"DRAFT", "VOID"} else adjusted - applied
            ):
                raise ValueError("Inconsistent current financial position")
            if invoice_status in {"DRAFT", "VOID"} and applied:
                raise ValueError("Invalid active applications on inactive Invoice")
            if (invoice_status == "PAID" and outstanding != 0) or (
                invoice_status == "UNPAID" and applied != 0
            ):
                raise ValueError("Invoice status contradicts this line's financial position")
            components = _components(
                row["components"],
                period_start=begin,
                period_end=finish,
                original=original,
                issued=issued,
                category=category,
            )
            items.append(
                TerminationInvoiceLine(
                    line_id,
                    invoice_id,
                    customer,
                    _integer(row["invoice_version"], minimum=1, maximum=2**31 - 1),
                    invoice_status,
                    issued,
                    kind,
                    category,
                    begin,
                    finish,
                    sources[category],
                    source_id,
                    original,
                    adjusted,
                    payment,
                    credit,
                    deposit,
                    outstanding,
                    _integer(row["active_adjustment_count"]),
                    components,
                    _coverage(evidence, actual, category, invoice_status, begin, finish),
                )
            )
        cursor = None if root["next_cursor"] is None else _uuid(root["next_cursor"])
        if cursor is not None and (
            len(items) != limit or not items or cursor != items[-1].invoice_line_id
        ):
            raise ValueError("Invalid continuation cursor")
        return TerminationInvoiceReadiness(
            lease_id,
            property_id,
            primary_tenant,
            status,
            start,
            end,
            actual,
            event,
            evidence,
            observed,
            monthly,
            final_month,
            tuple(items),
            cursor,
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise TerminationInvoiceUnavailableError("Invoice termination response is invalid") from exc


@dataclass(frozen=True, slots=True)
class PostgresTerminationInvoiceReadService:
    database_url: str
    property_id: UUID

    def __post_init__(self) -> None:
        _identity(self.property_id)

    def page(
        self,
        lease_id: UUID,
        *,
        actor: AuthenticatedActor,
        limit: int = 50,
        after_line_id: UUID | None = None,
    ) -> TerminationInvoiceReadiness:
        _identity(lease_id)
        _integer(limit, minimum=1, maximum=100)
        if after_line_id is not None:
            _identity(after_line_id)
        try:
            actor_id = _identity(UUID(actor.actor_id))
            if not all(
                is_authorized(actor, AuthorizationRequirement(capability, str(self.property_id)))
                for capability in ("leases.read", "invoices.read")
            ):
                raise ValueError("Both scoped read capabilities are required")
        except (ValueError, TypeError, AttributeError) as exc:
            raise TerminationInvoiceAuthorizationError(
                "Invoice termination read is not authorized"
            ) from exc
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                row = connection.execute(
                    "SELECT app.lease_termination_invoice_readiness(%s,%s,%s,%s,%s)",
                    (self.property_id, lease_id, actor_id, limit, after_line_id),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"42501", "P5406"}:
                raise TerminationInvoiceAuthorizationError(
                    "Invoice termination actor is not active"
                ) from exc
            if exc.sqlstate in {"P0002", "P5401"}:
                raise TerminationInvoiceNotFoundError(
                    "Invoice termination resource was not found"
                ) from exc
            raise TerminationInvoiceUnavailableError(
                "Invoice termination read is unavailable"
            ) from exc
        if row is None or len(row) != 1:
            raise TerminationInvoiceUnavailableError("Invoice termination response is missing")
        return parse_termination_invoice_readiness(
            cast(object, row[0]),
            lease_id=lease_id,
            property_id=self.property_id,
            limit=limit,
            after_line_id=after_line_id,
        )
