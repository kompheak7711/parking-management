"""Receive payment in one step (V1-058 R5c-1; DL-077).

Money pays Invoices when it is received (owner, 13/10/2026). One database transaction confirms
the Payment, issues its Receipt and posts what the money pays for, so a payment is never left
half-saved. The screen sends the ticks it showed: `OLDEST_FIRST` ticks must be exactly the
proposal the database builds (oldest Due Date first, a late-payment charge right after its own
Invoice), and `NAMED` ticks are what the Customer named (BR-PAY-024).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, NoReturn, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb, set_json_loads

from property_rental.configuration_api import ExchangeRateProvider, UnavailableExchangeRateProvider
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.khr_payment_confirmation import ConfirmKhrPaymentCommand, select_khr_reference
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationUnavailableError,
    _exact_json,
    _uuid,
)

MAX_AMOUNT = 9_000_000_000_000_000


class ReceivePaymentChanged(PaymentConfirmationConflictError):
    """The Customer's Invoices changed after the screen read them; nothing was saved."""


class ReceivePaymentLeftWhileOwing(PaymentConfirmationConflictError):
    """Named ticks leave money waiting while the payer still owes something (DL-077)."""


class ReceivePaymentTooMany(PaymentConfirmationConflictError):
    """The payer owes more than one proposal page (100 items); nothing was saved."""


@dataclass(frozen=True, slots=True)
class PaysTarget:
    kind: Literal["INVOICE", "LATE_PAYMENT_CHARGE"]
    target_id: UUID
    amount_usd_cents: int

    def __post_init__(self) -> None:
        _uuid(self.target_id)
        if self.kind not in ("INVOICE", "LATE_PAYMENT_CHARGE"):
            raise PaymentConfirmationInvalidError("A target is an Invoice or a charge")
        if type(self.amount_usd_cents) is not int or not 1 <= self.amount_usd_cents <= MAX_AMOUNT:
            raise PaymentConfirmationInvalidError("A target amount must be positive exact cents")

    def intent(self) -> dict[str, object]:
        key = "invoice_id" if self.kind == "INVOICE" else "late_payment_charge_id"
        return {key: str(self.target_id), "amount_usd_cents": self.amount_usd_cents}


@dataclass(frozen=True, slots=True)
class ReceivePaymentCommand:
    confirmation: ConfirmUsdPaymentCommand | ConfirmKhrPaymentCommand
    mode: Literal["OLDEST_FIRST", "NAMED"]
    targets: tuple[PaysTarget, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.confirmation, ConfirmUsdPaymentCommand | ConfirmKhrPaymentCommand):
            raise PaymentConfirmationInvalidError("An explicit confirmation command is required")
        if self.mode not in ("OLDEST_FIRST", "NAMED"):
            raise PaymentConfirmationInvalidError("Ticks are oldest first or named")
        if not isinstance(self.targets, tuple) or len(self.targets) > 100:
            raise PaymentConfirmationInvalidError("At most 100 ticks")
        if self.mode == "NAMED" and not self.targets:
            raise PaymentConfirmationInvalidError("Named ticks need at least one target")
        for target in self.targets:
            if not isinstance(target, PaysTarget):
                raise PaymentConfirmationInvalidError("Ticks must be explicit targets")
        if len({target.target_id for target in self.targets}) != len(self.targets):
            raise PaymentConfirmationInvalidError("A target is ticked once")
        # The payer's own money with nothing named on the Payment (review round 1): a Payment
        # that names an Invoice or a charge is recorded through the earlier form.
        confirmation = self.confirmation
        if (
            confirmation.payment_scope_kind != "NORMAL_CUSTOMER"
            or confirmation.identified_invoice_id is not None
            or confirmation.identified_late_payment_charge_id is not None
        ):
            raise PaymentConfirmationInvalidError("Receive payment takes the payer's own money")

    def pays(self) -> dict[str, object]:
        return {"mode": self.mode, "targets": [target.intent() for target in self.targets]}


def _database_error(exc: psycopg.Error) -> NoReturn:
    state = exc.sqlstate
    if state in {"P5301", "P4501", "P0002"}:
        raise PaymentConfirmationNotFoundError("Payment source was not found") from exc
    if state in {"P5305", "P4905"}:
        raise PaymentConfirmationKeyReused("Receive payment key was reused") from exc
    if state in {"P4506", "42501"}:
        raise PaymentConfirmationAuthorizationError("Receive payment is not authorized") from exc
    if state == "P4904":
        raise ReceivePaymentChanged("What the money pays changed; nothing was saved") from exc
    if state == "P5R01":
        raise ReceivePaymentLeftWhileOwing("Money is left while other Invoices are unpaid") from exc
    if state == "P5R02":
        raise ReceivePaymentTooMany("Too many unpaid items for one payment") from exc
    # P4901: a named Invoice or charge that is not in this Property is a bad request.
    if state in {"P5302", "P4902", "P4901"} or (state is not None and state.startswith("22")):
        raise PaymentConfirmationInvalidError("Receive payment input is invalid") from exc
    if state in {"23503", "23505", "23514", "55000", "P5S01"}:
        raise PaymentConfirmationConflictError(
            "Payment source state conflicts with receiving"
        ) from exc
    # Serialization, deadlock, timeout and connection failures cannot prove that an earlier
    # transmission of this key did not commit: the client replays the same key.
    raise PaymentConfirmationUnavailableError("Receive payment outcome is unavailable") from exc


@dataclass(frozen=True, slots=True)
class ReceivePaymentService:
    financial_database_url: str
    provider: ExchangeRateProvider = field(default_factory=UnavailableExchangeRateProvider)

    def receive(
        self, property_id: UUID, command: ReceivePaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        _uuid(property_id)
        if not isinstance(command, ReceivePaymentCommand):
            raise PaymentConfirmationInvalidError("An explicit Receive payment command is required")
        confirmation = command.confirmation
        needed = ["payments.record"]
        if command.targets:
            needed.append("payments.allocate")
        if isinstance(confirmation, ConfirmKhrPaymentCommand) and confirmation.manual_reference:
            needed.append("exchange_rates.manage")
        for capability in needed:
            if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
                raise PaymentConfirmationAuthorizationError("Receive payment is not authorized")
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PaymentConfirmationAuthorizationError(
                "Payment actor identity is invalid"
            ) from exc
        request = confirmation.intent()
        pays = command.pays()
        # The rate the database records is chosen once; a replay never asks for it again.
        digest = hashlib.sha256(
            json.dumps(
                {"property_id": str(property_id), "request": request, "pays": pays},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        key = confirmation.idempotency_key
        try:
            with psycopg.connect(self.financial_database_url, connect_timeout=3) as connection:
                set_json_loads(_exact_json, connection)
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute("SET LOCAL TIME ZONE 'UTC'")
                row = connection.execute(
                    "SELECT app.receive_payment_replay(%s,%s,%s,%s)",
                    (property_id, actor_id, key, digest),
                ).fetchone()
                if row is None:
                    raise PaymentConfirmationUnavailableError(
                        "Receive payment replay is unavailable"
                    )
                if row[0] is None:
                    selection = (
                        select_khr_reference(self.provider, confirmation.manual_reference)
                        if isinstance(confirmation, ConfirmKhrPaymentCommand)
                        else None
                    )
                    row = connection.execute(
                        "SELECT app.receive_payment(%s,%s,%s,%s,%s,%s,%s)",
                        (
                            property_id,
                            actor_id,
                            key,
                            digest,
                            Jsonb(request),
                            Jsonb(selection) if selection is not None else None,
                            Jsonb(pays),
                        ),
                    ).fetchone()
        except psycopg.Error as exc:
            _database_error(exc)
        if row is None or not isinstance(row[0], dict):
            raise PaymentConfirmationUnavailableError("Receive payment outcome is unavailable")
        return cast(dict[str, object], row[0])


def read_payable(
    database_url: str, property_id: UUID, customer_id: UUID, *, actor: AuthenticatedActor
) -> dict[str, object]:
    """What the Customer owes, in the order oldest-first ticks pay it (the screen's list)."""
    _uuid(property_id)
    _uuid(customer_id)
    if not is_authorized(actor, AuthorizationRequirement("payments.record", str(property_id))):
        raise PaymentConfirmationAuthorizationError("Receive payment is not authorized")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            set_json_loads(_exact_json, connection)
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL statement_timeout='5000ms'")
            row = connection.execute(
                "SELECT app.receive_payment_payable(%s,%s)", (property_id, customer_id)
            ).fetchone()
    except psycopg.Error as exc:
        raise PaymentConfirmationUnavailableError("What is owed is unavailable") from exc
    if row is None or not isinstance(row[0], dict):
        raise PaymentConfirmationUnavailableError("What is owed is unavailable")
    return cast(dict[str, object], row[0])
