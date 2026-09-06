"""Explicit USD Payment confirmation; KHR confirmation is a separate pending bridge.

The input amount is money actually received, not a balance or an allocation.
Receipt identity is issued by the existing database trigger in the same transaction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class PaymentConfirmationInvalidError(ValueError):
    pass


class PaymentConfirmationAuthorizationError(PermissionError):
    pass


class PaymentConfirmationNotFoundError(LookupError):
    pass


class PaymentConfirmationConflictError(RuntimeError):
    pass


class PaymentConfirmationKeyReused(PaymentConfirmationConflictError):
    pass


class PaymentConfirmationUnavailableError(RuntimeError):
    """Outcome may be unknown; retain the exact intent/key and never create a new one."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise PaymentConfirmationInvalidError("A non-nil UUID is required")


def _text(value: str, limit: int) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise PaymentConfirmationInvalidError("Normalized bounded evidence is required")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise PaymentConfirmationInvalidError("Evidence must use valid UTF-8") from exc
    if "\x00" in value:
        raise PaymentConfirmationInvalidError("Evidence must not contain NUL")


def _instant(value: datetime) -> datetime:
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware received timestamp is required")
        return value.astimezone(UTC)
    except (ValueError, TypeError, OverflowError) as exc:
        raise PaymentConfirmationInvalidError("Received timestamp must be timezone-aware") from exc


@dataclass(frozen=True, slots=True)
class ConfirmUsdPaymentCommand:
    idempotency_key: UUID
    payer_customer_id: UUID
    payment_method_id: UUID
    received_amount_minor: int
    received_at: datetime
    evidence_reference: str
    payment_scope_kind: Literal["NORMAL_CUSTOMER", "THIRD_PARTY_IDENTIFIED"] = "NORMAL_CUSTOMER"
    lease_id: UUID | None = None
    identified_invoice_id: UUID | None = None
    identified_late_payment_charge_id: UUID | None = None
    payer_intent_memo: str | None = None
    channel_transaction_reference: str | None = None

    def __post_init__(self) -> None:
        for identity in (self.idempotency_key, self.payer_customer_id, self.payment_method_id):
            _uuid(identity)
        for optional in (
            self.lease_id,
            self.identified_invoice_id,
            self.identified_late_payment_charge_id,
        ):
            if optional is not None:
                _uuid(optional)
        if (
            type(self.received_amount_minor) is not int
            or not 1 <= self.received_amount_minor <= 9_000_000_000_000_000
        ):
            raise PaymentConfirmationInvalidError(
                "Received USD must use positive bounded exact cents"
            )
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
            item is None
            for item in (
                self.lease_id,
                self.identified_invoice_id,
                self.identified_late_payment_charge_id,
            )
        ):
            raise PaymentConfirmationInvalidError(
                "Third-party Payment requires explicit designation"
            )

    def intent(self) -> dict[str, object]:
        # Revalidate even a frozen envelope altered by unsafe internal construction.
        value = replace(self)
        return {
            "received_currency": "USD",
            "payer_customer_id": str(value.payer_customer_id),
            "payment_method_id": str(value.payment_method_id),
            "received_amount_minor": value.received_amount_minor,
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
        }


def _exact_json(value: str | bytes) -> object:
    return json.loads(value, parse_float=str)


@dataclass(frozen=True, slots=True)
class PaymentConfirmationService:
    financial_database_url: str

    def confirm_usd(
        self, property_id: UUID, command: ConfirmUsdPaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement("payments.record", str(property_id))):
            raise PaymentConfirmationAuthorizationError("Payment confirmation is not authorized")
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PaymentConfirmationAuthorizationError(
                "Payment actor identity is invalid"
            ) from exc
        if not isinstance(command, ConfirmUsdPaymentCommand):
            raise PaymentConfirmationInvalidError(
                "An explicit USD confirmation command is required"
            )
        intent = command.intent()
        try:
            with psycopg.connect(self.financial_database_url, connect_timeout=3) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                row = connection.execute(
                    "SELECT app.confirm_usd_payment(%s,%s,%s,%s)",
                    (property_id, actor_id, command.idempotency_key, Jsonb(intent)),
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5301", "P4501", "P0002"}:
                raise PaymentConfirmationNotFoundError("Payment source was not found") from exc
            if exc.sqlstate == "P5305":
                raise PaymentConfirmationKeyReused("Payment confirmation key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise PaymentConfirmationAuthorizationError(
                    "Payment confirmation is not authorized"
                ) from exc
            if exc.sqlstate == "P5302" or (
                exc.sqlstate is not None and exc.sqlstate.startswith("22")
            ):
                raise PaymentConfirmationInvalidError(
                    "Payment confirmation input is invalid"
                ) from exc
            if exc.sqlstate in {"23503", "23505", "23514", "55000", "40001", "40P01"}:
                raise PaymentConfirmationConflictError(
                    "Payment source state conflicts with confirmation"
                ) from exc
            raise PaymentConfirmationUnavailableError(
                "Payment confirmation outcome is unavailable"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise PaymentConfirmationUnavailableError("Payment confirmation outcome is unavailable")
        return cast(dict[str, object], row[0])
