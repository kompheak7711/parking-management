"""Explicit payer-authorized Credit recognition and permanent reversal services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class CreditNotFoundError(LookupError):
    pass


class CreditAuthorizationError(PermissionError):
    pass


class CreditInvalidError(ValueError):
    pass


class CreditIdempotencyKeyReused(RuntimeError):
    pass


class CreditUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise CreditInvalidError("A non-nil UUID is required")


def _text(value: str, limit: int) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise CreditInvalidError("A normalized bounded value is required")


@dataclass(frozen=True, slots=True)
class RecognizeCreditCommand:
    idempotency_key: UUID
    amount_usd_cents: int
    payer_authorization_reference: str
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= 9_000_000_000_000_000
        ):
            raise CreditInvalidError("Credit amount must be positive bounded exact USD cents")
        _text(self.payer_authorization_reference, 500)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class ReverseCreditCommand:
    idempotency_key: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _text(self.reason, 1000)


@dataclass(frozen=True, slots=True)
class CustomerCreditService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise CreditAuthorizationError("Credit action is not authorized")
        try:
            identity = UUID(actor.actor_id)
            _uuid(identity)
        except (ValueError, TypeError, AttributeError) as exc:
            raise CreditAuthorizationError("Credit actor identity is invalid") from exc
        return identity

    def _query(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool = False
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url if mutation else self.database_url,
                connect_timeout=3,
            ) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5101", "P4501"}:
                raise CreditNotFoundError("Credit source or resource was not found") from exc
            if exc.sqlstate == "P5102":
                raise CreditInvalidError("Credit command is invalid") from exc
            if exc.sqlstate == "P5105":
                raise CreditIdempotencyKeyReused("Credit command key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise CreditAuthorizationError("Credit actor is not authorized") from exc
            # A serialization/timeout/deferred constraint failure does not prove
            # an earlier transmission with the same key did not commit.
            raise CreditUnavailableError(
                "Credit outcome unresolved; preserve and replay the original command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise CreditNotFoundError("Credit source or resource was not found")
        return cast(dict[str, object], row[0])

    def get(
        self, property_id: UUID, credit_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.read")
        _uuid(credit_id)
        return self._query(
            "SELECT app.credit_resource(%s,%s,%s)", (property_id, credit_id, actor_id)
        )

    def recognize(
        self,
        property_id: UUID,
        payment_id: UUID,
        command: RecognizeCreditCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.recognize")
        _uuid(payment_id)
        # Revalidate the immutable scalar envelope at transmission.
        request = RecognizeCreditCommand(
            command.idempotency_key,
            command.amount_usd_cents,
            command.payer_authorization_reference,
            command.reason,
        )
        return self._query(
            "SELECT app.recognize_customer_credit(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                payment_id,
                actor_id,
                request.idempotency_key,
                request.amount_usd_cents,
                request.payer_authorization_reference,
                request.reason,
            ),
            mutation=True,
        )

    def reverse(
        self,
        property_id: UUID,
        credit_id: UUID,
        command: ReverseCreditCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "credits.reverse")
        _uuid(credit_id)
        request = ReverseCreditCommand(command.idempotency_key, command.reason)
        return self._query(
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (property_id, credit_id, actor_id, request.idempotency_key, request.reason),
            mutation=True,
        )
