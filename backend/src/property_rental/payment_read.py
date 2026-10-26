"""Bounded, capability-scoped Payment reads; no financial command or mutation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import cast
from uuid import UUID

import psycopg
from psycopg.types.json import set_json_loads

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class PaymentReadInvalidError(ValueError):
    pass


class PaymentReadAuthorizationError(PermissionError):
    pass


class PaymentReadNotFoundError(LookupError):
    pass


class PaymentReadUnavailableError(RuntimeError):
    pass


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise PaymentReadInvalidError("A non-nil UUID is required")


def _exact_json(value: str | bytes) -> object:
    # Preserve integer money and fractional original FX as exact decimal text.
    return json.loads(value, parse_float=str)


@dataclass(frozen=True, slots=True)
class PaymentPage:
    limit: int = 50
    after_date: date | None = None
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise PaymentReadInvalidError("Payment page size must be between 1 and 100")
        if (self.after_date is None) != (self.after_id is None):
            raise PaymentReadInvalidError("Both Payment cursor fields are required")
        if self.after_date is not None:
            if type(self.after_date) is not date:
                raise PaymentReadInvalidError("Payment cursor requires a calendar date")
            _uuid(cast(UUID, self.after_id))


@dataclass(frozen=True, slots=True)
class PaymentFilters:
    customer_id: UUID | None = None
    status: str | None = None
    payment_method_id: UUID | None = None

    def __post_init__(self) -> None:
        for value in (self.customer_id, self.payment_method_id):
            if value is not None:
                _uuid(value)
        if self.status is not None and (
            not isinstance(self.status, str) or self.status not in {"RECEIVED", "REVERSED"}
        ):
            raise PaymentReadInvalidError("Payment status filter is invalid")


_CONTEXT = """
    SELECT EXISTS(SELECT 1 FROM app.properties WHERE id=%s),
        EXISTS(SELECT 1 FROM app.user_accounts account
            JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
            WHERE account.actor_id=%s AND account.lifecycle_state='active'
                AND identity.identity_kind='HUMAN')
"""

# The bounded selection precedes all per-Payment projections. Source evidence is
# linked by immutable identity: never expand unbounded FX traces or event history
# inside a list/detail resource. Original facts remain in their original tables.
_RESOURCE = """
    , dispositions AS MATERIALIZED (
        SELECT id,app.payment_disposition_summary(id) AS value FROM selected
    )
    SELECT jsonb_build_object(
        'payment',to_jsonb(payment),
        'property_timezone','Asia/Phnom_Penh',
        'position',jsonb_build_object(
            'currency','USD',
            'original_usd_cents',payment.usd_accounting_value_cents,
            'dispositions',dispositions.value,
            'available_usd_cents',CASE WHEN payment.status='REVERSED' THEN 0 ELSE
                payment.usd_accounting_value_cents-COALESCE((SELECT sum(value::numeric)
                    FROM jsonb_each_text(dispositions.value)),0)::bigint END),
        'receipt',CASE WHEN receipt.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id',receipt.id,'receipt_number',receipt.receipt_number) END,
        'reversal',to_jsonb(reversal),
        'exchange_rate_evidence_id',payment.exchange_rate_record_id,
        'exchange_rate',CASE WHEN rate.id IS NULL THEN NULL ELSE jsonb_build_object(
            'id',rate.id,'reference_rate_khr_per_usd',rate.reference_rate_khr_per_usd,
            'system_rate_khr_per_usd',rate.system_rate_khr_per_usd,
            'markup_basis_points',rate.markup_basis_points,'rate_source',rate.rate_source,
            'applicable_at',rate.applicable_at,'entered_by',rate.entered_by,
            'channel_actual_currency',rate.channel_actual_currency,
            'channel_actual_amount_minor',rate.channel_actual_amount_minor,
            'channel_actual_usd_value_cents',rate.channel_actual_usd_value_cents,
            'channel_actual_rate_khr_per_usd',rate.channel_actual_rate_khr_per_usd,
            'channel_confirmed_at',rate.channel_confirmed_at) END)
    FROM selected payment JOIN dispositions ON dispositions.id=payment.id
    LEFT JOIN app.receipts receipt ON receipt.payment_id=payment.id
    LEFT JOIN app.payment_reversals reversal ON reversal.payment_id=payment.id
    LEFT JOIN app.exchange_rate_records rate ON rate.id=payment.exchange_rate_record_id
    ORDER BY payment.payment_date DESC,payment.id DESC
"""

_DETAIL = (
    """
    WITH selected AS MATERIALIZED (
        SELECT * FROM app.payments WHERE property_id=%s AND id=%s
    )
"""
    + _RESOURCE
)

_LIST = (
    """
    WITH selected AS MATERIALIZED (
        SELECT * FROM app.payments WHERE property_id=%s
            AND (%s::uuid IS NULL OR payer_customer_id=%s)
            AND (%s::text IS NULL OR status=%s)
            AND (%s::uuid IS NULL OR payment_method_id=%s)
            AND (%s::date IS NULL OR (payment_date,id)<(%s::date,%s::uuid))
        ORDER BY payment_date DESC,id DESC LIMIT %s
    )
"""
    + _RESOURCE
)


@dataclass(frozen=True, slots=True)
class PaymentReadService:
    database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement("payments.read", str(property_id))):
            raise PaymentReadAuthorizationError("Payment read is not authorized")
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PaymentReadAuthorizationError("Payment actor identity is invalid") from exc
        return actor_id

    def _query(
        self, property_id: UUID, actor_id: UUID, sql: str, parameters: tuple[object, ...]
    ) -> list[dict[str, object]]:
        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                # Existing disposition helpers are VOLATILE. Repeatable Read is
                # required even inside one SQL statement so their nested queries
                # cannot observe a later commit than the Payment status/facts.
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                set_json_loads(_exact_json, connection)
                context = connection.execute(_CONTEXT, (property_id, actor_id)).fetchone()
                if context is None or context[1] is not True:
                    raise PaymentReadAuthorizationError("Payment actor is not active")
                if context[0] is not True:
                    raise PaymentReadNotFoundError("Payment Property was not found")
                rows = connection.execute(sql, parameters).fetchall()
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise PaymentReadAuthorizationError("Payment read is not authorized") from exc
            raise PaymentReadUnavailableError("Payment read is temporarily unavailable") from exc
        if any(len(row) != 1 or not isinstance(row[0], dict) for row in rows):
            raise PaymentReadUnavailableError("Payment read is temporarily unavailable")
        return [cast(dict[str, object], row[0]) for row in rows]

    def get(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id)
        _uuid(payment_id)
        rows = self._query(property_id, actor_id, _DETAIL, (property_id, payment_id))
        if not rows:
            raise PaymentReadNotFoundError("Payment was not found")
        return rows[0]

    def list(
        self,
        property_id: UUID,
        page: PaymentPage | None = None,
        filters: PaymentFilters | None = None,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id)
        original_page, original_filters = page or PaymentPage(), filters or PaymentFilters()
        # Revalidate frozen envelopes at transmission, including forged instances.
        checked = PaymentPage(original_page.limit, original_page.after_date, original_page.after_id)
        selected = PaymentFilters(
            original_filters.customer_id,
            original_filters.status,
            original_filters.payment_method_id,
        )
        rows = self._query(
            property_id,
            actor_id,
            _LIST,
            (
                property_id,
                selected.customer_id,
                selected.customer_id,
                selected.status,
                selected.status,
                selected.payment_method_id,
                selected.payment_method_id,
                checked.after_date,
                checked.after_date,
                checked.after_id,
                checked.limit + 1,
            ),
        )
        items = rows[: checked.limit]
        cursor = None
        if len(rows) > checked.limit:
            last = cast(dict[str, object], items[-1]["payment"])
            cursor = {"payment_date": last["payment_date"], "id": last["id"]}
        return {"items": items, "next_cursor": cursor, "limit": checked.limit}


SUMMARY_ROW_LIMIT = 500
# At most two years, so the read of every payment in the period stays quick.
SUMMARY_MAX_DAYS = 731


def summarize_period(
    service: PaymentReadService,
    property_id: UUID,
    start: date,
    end: date,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    """V1-058 R5c-3a: the Payments page cards and list for one period (read only)."""
    actor_id = service._authorize(actor, property_id)
    if type(start) is not date or type(end) is not date or start > end:
        raise PaymentReadInvalidError("Payment period is invalid")
    if (end - start).days > SUMMARY_MAX_DAYS:
        raise PaymentReadInvalidError("Payment period is too long")
    rows = service._query(
        property_id,
        actor_id,
        "SELECT app.payments_period_summary(%s,%s,%s,%s,%s)",
        (property_id, actor_id, start, end, SUMMARY_ROW_LIMIT),
    )
    if len(rows) != 1:
        raise PaymentReadUnavailableError("Payment read is temporarily unavailable")
    return rows[0]


def receipt_lines(
    service: PaymentReadService,
    property_id: UUID,
    payment_id: UUID,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object]:
    """V1-058 R5c-3a: what the printed Receipt shows for one payment (read only)."""
    _uuid(property_id)
    _uuid(payment_id)
    if not is_authorized(actor, AuthorizationRequirement("receipts.read", str(property_id))):
        raise PaymentReadAuthorizationError("Receipt read is not authorized")
    try:
        actor_id = UUID(actor.actor_id)
        _uuid(actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentReadAuthorizationError("Payment actor identity is invalid") from exc
    rows = service._query(
        property_id,
        actor_id,
        "SELECT value FROM (SELECT app.payment_receipt_lines(%s,%s,%s) AS value) item "
        "WHERE value IS NOT NULL",
        (property_id, actor_id, payment_id),
    )
    if not rows:
        raise PaymentReadNotFoundError("Payment was not found")
    return rows[0]


def late_charge_card(
    service: PaymentReadService,
    property_id: UUID,
    invoice_id: UUID,
    *,
    actor: AuthenticatedActor,
) -> dict[str, object] | None:
    """V1-058 R5d: the late-payment card of one Invoice, or None without a charge (read only)."""
    _uuid(property_id)
    _uuid(invoice_id)
    if not is_authorized(actor, AuthorizationRequirement("invoices.read", str(property_id))):
        raise PaymentReadAuthorizationError("Invoice read is not authorized")
    try:
        actor_id = UUID(actor.actor_id)
        _uuid(actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentReadAuthorizationError("Payment actor identity is invalid") from exc
    rows = service._query(
        property_id,
        actor_id,
        "SELECT value FROM (SELECT app.invoice_late_charge_card(%s,%s,%s) AS value) item "
        "WHERE value IS NOT NULL",
        (property_id, actor_id, invoice_id),
    )
    return rows[0] if rows else None
