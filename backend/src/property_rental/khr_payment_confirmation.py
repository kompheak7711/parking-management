"""Incoming KHR conversion only; accounting and every Refund remain USD.

Original caller intent is distinct from the server-selected rate. Exact replay
precedes source lookup, and FX, Payment, Receipt and response commit together.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal, NoReturn, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.configuration_api import (
    ExchangeRateProvider,
    ExchangeRateQuote,
    ExchangeRateSourceUnavailable,
    UnavailableExchangeRateProvider,
)
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.payment_confirmation import (
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationUnavailableError,
    _exact_json,
    _instant,
    _text,
    _uuid,
)


def _money(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 9_000_000_000_000_000:
        raise PaymentConfirmationInvalidError(
            "Positive bounded integer monetary units are required"
        )


def _rate(value: Decimal) -> str:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or not Decimal("0") < value < Decimal("100000000000000")
    ):
        raise PaymentConfirmationInvalidError("A positive numeric(20,6) reference rate is required")
    # Inspect the exact coefficient instead of rounding under ambient Decimal
    # precision/traps. Trailing zeros do not change the numeric(20,6) value.
    parts = value.as_tuple()
    digits = list(parts.digits)
    exponent = cast(int, parts.exponent)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    if exponent < -6:
        raise PaymentConfirmationInvalidError("Reference rates support at most six decimal places")
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    millionths = coefficient * 10 ** (exponent + 6)
    return f"{millionths // 1_000_000}.{millionths % 1_000_000:06d}"


@dataclass(frozen=True, slots=True)
class ManualKhrReference:
    reference_rate_khr_per_usd: Decimal
    source_reference: str
    applicable_at: datetime
    fallback_reason: str

    def __post_init__(self) -> None:
        _rate(self.reference_rate_khr_per_usd)
        _text(self.source_reference, 500)
        _text(self.fallback_reason, 500)
        object.__setattr__(self, "applicable_at", _instant(self.applicable_at))

    def intent(self) -> dict[str, object]:
        value = replace(self)
        return {
            "reference_rate_khr_per_usd": _rate(value.reference_rate_khr_per_usd),
            "source_reference": value.source_reference,
            "applicable_at": value.applicable_at.isoformat(),
            "fallback_reason": value.fallback_reason,
        }


@dataclass(frozen=True, slots=True)
class KhrChannelEvidence:
    """Only actual supplied channel facts; unavailable values stay absent."""

    transaction_reference: str
    confirmed_at: datetime
    actual_currency: Literal["KHR"] | None = None
    actual_amount_minor: int | None = None
    actual_usd_value_cents: int | None = None
    actual_rate_khr_per_usd: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.transaction_reference, 500)
        object.__setattr__(self, "confirmed_at", _instant(self.confirmed_at))
        if self.actual_currency not in (None, "KHR"):
            raise PaymentConfirmationInvalidError("Incoming KHR channel currency must agree")
        for amount in (self.actual_amount_minor, self.actual_usd_value_cents):
            if amount is not None:
                _money(amount)
        if self.actual_rate_khr_per_usd is not None:
            _rate(self.actual_rate_khr_per_usd)
        if all(
            value is None
            for value in (
                self.actual_currency,
                self.actual_amount_minor,
                self.actual_usd_value_cents,
                self.actual_rate_khr_per_usd,
            )
        ):
            raise PaymentConfirmationInvalidError("At least one actual channel fact is required")

    def intent(self) -> dict[str, object]:
        value = replace(self)
        return {
            "transaction_reference": value.transaction_reference,
            "confirmed_at": value.confirmed_at.isoformat(),
            "actual_currency": value.actual_currency,
            "actual_amount_minor": value.actual_amount_minor,
            "actual_usd_value_cents": value.actual_usd_value_cents,
            "actual_rate_khr_per_usd": _rate(value.actual_rate_khr_per_usd)
            if value.actual_rate_khr_per_usd is not None
            else None,
        }


@dataclass(frozen=True, slots=True)
class ConfirmKhrPaymentCommand:
    idempotency_key: UUID
    payer_customer_id: UUID
    payment_method_id: UUID
    received_amount_minor: int
    usd_amount_cents: int
    received_at: datetime
    evidence_reference: str
    payment_scope_kind: Literal["NORMAL_CUSTOMER", "THIRD_PARTY_IDENTIFIED"] = "NORMAL_CUSTOMER"
    lease_id: UUID | None = None
    identified_invoice_id: UUID | None = None
    identified_late_payment_charge_id: UUID | None = None
    payer_intent_memo: str | None = None
    channel_transaction_reference: str | None = None
    manual_reference: ManualKhrReference | None = None
    channel_evidence: KhrChannelEvidence | None = None

    def __post_init__(self) -> None:
        for identity in (self.idempotency_key, self.payer_customer_id, self.payment_method_id):
            _uuid(identity)
        for optional_identity in (
            self.lease_id,
            self.identified_invoice_id,
            self.identified_late_payment_charge_id,
        ):
            if optional_identity is not None:
                _uuid(optional_identity)
        _money(self.received_amount_minor)
        _money(self.usd_amount_cents)
        object.__setattr__(self, "received_at", _instant(self.received_at))
        _text(self.evidence_reference, 500)
        for value, limit in (
            (self.payer_intent_memo, 2000),
            (self.channel_transaction_reference, 500),
        ):
            if value is not None:
                _text(value, limit)
        if self.payment_scope_kind not in ("NORMAL_CUSTOMER", "THIRD_PARTY_IDENTIFIED"):
            raise PaymentConfirmationInvalidError("Payment intent scope is invalid")
        if self.payment_scope_kind == "THIRD_PARTY_IDENTIFIED" and all(
            value is None
            for value in (
                self.lease_id,
                self.identified_invoice_id,
                self.identified_late_payment_charge_id,
            )
        ):
            raise PaymentConfirmationInvalidError("Third-party Payment requires explicit intent")
        if self.manual_reference is not None:
            if not isinstance(self.manual_reference, ManualKhrReference):
                raise PaymentConfirmationInvalidError("Explicit manual source evidence is required")
            self.manual_reference.intent()
        if self.channel_evidence is not None:
            if not isinstance(self.channel_evidence, KhrChannelEvidence):
                raise PaymentConfirmationInvalidError("Explicit channel evidence is required")
            self.channel_evidence.intent()
            if self.channel_evidence.transaction_reference != self.channel_transaction_reference:
                raise PaymentConfirmationInvalidError("Channel references must match exactly")

    def intent(self) -> dict[str, object]:
        value = replace(self)
        return {
            "received_currency": "KHR",
            "payer_customer_id": str(value.payer_customer_id),
            "payment_method_id": str(value.payment_method_id),
            "received_amount_minor": value.received_amount_minor,
            "usd_amount_cents": value.usd_amount_cents,
            "received_at": value.received_at.isoformat(),
            "evidence_reference": value.evidence_reference,
            "payment_scope_kind": value.payment_scope_kind,
            "lease_id": str(value.lease_id) if value.lease_id is not None else None,
            "identified_invoice_id": str(value.identified_invoice_id)
            if value.identified_invoice_id is not None
            else None,
            "identified_late_payment_charge_id": str(value.identified_late_payment_charge_id)
            if value.identified_late_payment_charge_id is not None
            else None,
            "payer_intent_memo": value.payer_intent_memo,
            "channel_transaction_reference": value.channel_transaction_reference,
            "manual_reference": value.manual_reference.intent()
            if value.manual_reference is not None
            else None,
            "channel_evidence": value.channel_evidence.intent()
            if value.channel_evidence is not None
            else None,
        }


def _database_error(exc: psycopg.Error) -> NoReturn:
    if exc.sqlstate in {"P5301", "P4501", "P0002"}:
        raise PaymentConfirmationNotFoundError("Payment source was not found") from exc
    if exc.sqlstate == "P5305":
        raise PaymentConfirmationKeyReused("Payment confirmation key was reused") from exc
    if exc.sqlstate in {"P4506", "42501"}:
        raise PaymentConfirmationAuthorizationError(
            "Payment confirmation is not authorized"
        ) from exc
    if exc.sqlstate == "P5302" or (exc.sqlstate is not None and exc.sqlstate.startswith("22")):
        raise PaymentConfirmationInvalidError("KHR confirmation input is invalid") from exc
    if exc.sqlstate in {"23503", "23505", "23514", "55000", "40001", "40P01"}:
        raise PaymentConfirmationConflictError(
            "Payment source state conflicts with confirmation"
        ) from exc
    raise PaymentConfirmationUnavailableError(
        "Payment confirmation outcome is unavailable"
    ) from exc


class ApprovedKhrSourceUnavailable(PaymentConfirmationUnavailableError):
    """The approved provider explicitly reports no source; manual fallback may apply."""


def select_khr_reference(
    provider: ExchangeRateProvider, manual: ManualKhrReference | None
) -> dict[str, object]:
    try:
        quote = provider.current_sell_rate()
    except ExchangeRateSourceUnavailable as exc:
        if manual is None:
            raise ApprovedKhrSourceUnavailable("Approved rate source is unavailable") from exc
        return {
            **manual.intent(),
            "rate_source": "ABA_EQUIVALENT_MANUAL",
            "automatic_source_unavailable": True,
        }
    except Exception as exc:
        raise PaymentConfirmationUnavailableError("Approved rate source is unavailable") from exc
    if manual is not None:
        raise PaymentConfirmationConflictError(
            "Automatic source is available; manual fallback is not permitted"
        )
    try:
        if not isinstance(quote, ExchangeRateQuote):
            raise PaymentConfirmationInvalidError("Approved source response is invalid")
        _text(quote.source_reference, 500)
        return {
            "reference_rate_khr_per_usd": _rate(quote.reference_rate_khr_per_usd),
            "source_reference": quote.source_reference,
            "applicable_at": _instant(quote.applicable_at).isoformat(),
            "fallback_reason": None,
            "rate_source": "ABA_AUTOMATIC",
            "automatic_source_unavailable": False,
        }
    except PaymentConfirmationInvalidError as exc:
        raise PaymentConfirmationUnavailableError("Approved source response is invalid") from exc


@dataclass(frozen=True, slots=True)
class KhrPaymentConfirmationService:
    financial_database_url: str
    provider: ExchangeRateProvider = field(default_factory=UnavailableExchangeRateProvider)

    def _selection(self, manual: ManualKhrReference | None) -> dict[str, object]:
        return select_khr_reference(self.provider, manual)

    def confirm_khr(
        self, property_id: UUID, command: ConfirmKhrPaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement("payments.record", str(property_id))):
            raise PaymentConfirmationAuthorizationError("Payment confirmation is not authorized")
        if not isinstance(command, ConfirmKhrPaymentCommand):
            raise PaymentConfirmationInvalidError("An explicit incoming KHR command is required")
        intent = command.intent()
        if command.manual_reference is not None and not is_authorized(
            actor, AuthorizationRequirement("exchange_rates.manage", str(property_id))
        ):
            raise PaymentConfirmationAuthorizationError(
                "Manual reference confirmation is not authorized"
            )
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PaymentConfirmationAuthorizationError(
                "Payment actor identity is invalid"
            ) from exc
        try:
            with psycopg.connect(self.financial_database_url, connect_timeout=3) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                row = connection.execute(
                    "SELECT app.replay_khr_payment_confirmation(%s,%s,%s,%s)",
                    (property_id, actor_id, command.idempotency_key, Jsonb(intent)),
                ).fetchone()
                if row is None:
                    raise PaymentConfirmationUnavailableError(
                        "Payment replay outcome is unavailable"
                    )
                if row[0] is None:
                    selection = self._selection(command.manual_reference)
                    row = connection.execute(
                        "SELECT app.confirm_khr_payment(%s,%s,%s,%s,%s)",
                        (
                            property_id,
                            actor_id,
                            command.idempotency_key,
                            Jsonb(intent),
                            Jsonb(selection),
                        ),
                    ).fetchone()
        except psycopg.Error as exc:
            _database_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise PaymentConfirmationUnavailableError("Payment confirmation outcome is unavailable")
        return cast(dict[str, object], row[0])
