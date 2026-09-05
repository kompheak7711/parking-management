"""Authorized Receipt lookup and explicit idempotent reprint; neither moves money."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class ReceiptNotFoundError(LookupError):
    pass


class ReceiptAuthorizationError(PermissionError):
    pass


class ReceiptInvalidError(ValueError):
    pass


class ReceiptIdempotencyKeyReused(RuntimeError):
    pass


class ReceiptUnavailableError(RuntimeError):
    """Outcome may be unknown; retain the original reprint command for exact replay."""


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ReceiptInvalidError("A non-nil UUID is required")


def _text(value: str, limit: int) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= limit:
        raise ReceiptInvalidError("A normalized bounded value is required")


@dataclass(frozen=True, slots=True)
class ReprintReceiptCommand:
    idempotency_key: UUID
    reason: str
    delivery_reference: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key)
        _text(self.reason, 1000)
        if self.delivery_reference is not None:
            _text(self.delivery_reference, 500)


@dataclass(frozen=True, slots=True)
class ReceiptService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id)
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise ReceiptAuthorizationError("Receipt action is not authorized")
        try:
            identity = UUID(actor.actor_id)
            _uuid(identity)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ReceiptAuthorizationError("Receipt actor identity is invalid") from exc
        return identity

    def _query(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool = False
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url if mutation else self.database_url, connect_timeout=3
            ) as connection:
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P5001", "P4501"}:
                raise ReceiptNotFoundError("Receipt was not found") from exc
            if exc.sqlstate == "P5002":
                raise ReceiptInvalidError("Receipt command is invalid") from exc
            if exc.sqlstate == "P5005":
                raise ReceiptIdempotencyKeyReused("Receipt reprint key was reused") from exc
            if exc.sqlstate in {"P4506", "42501"}:
                raise ReceiptAuthorizationError("Receipt actor is not authorized") from exc
            raise ReceiptUnavailableError(
                "Receipt outcome unresolved; preserve and replay the original command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise ReceiptNotFoundError("Receipt was not found")
        return cast(dict[str, object], row[0])

    def get(
        self, property_id: UUID, receipt_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "receipts.read")
        _uuid(receipt_id)
        return self._query(
            "SELECT app.receipt_resource(%s,%s,%s)", (property_id, receipt_id, actor_id)
        )

    def for_payment(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "receipts.read")
        _uuid(payment_id)
        return self._query(
            "SELECT app.receipt_for_payment(%s,%s,%s)", (property_id, payment_id, actor_id)
        )

    def history(
        self,
        property_id: UUID,
        receipt_id: UUID,
        *,
        actor: AuthenticatedActor,
        after_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "receipts.read")
        _uuid(receipt_id)
        if after_id is not None:
            _uuid(after_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReceiptInvalidError("Receipt history page size is invalid")
        return self._query(
            "SELECT app.receipt_reprint_history(%s,%s,%s,%s,%s)",
            (property_id, receipt_id, actor_id, after_id, limit),
        )

    def reprint(
        self,
        property_id: UUID,
        receipt_id: UUID,
        command: ReprintReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = self._authorize(actor, property_id, "receipts.reprint")
        _uuid(receipt_id)
        command = ReprintReceiptCommand(
            command.idempotency_key, command.reason, command.delivery_reference
        )
        return self._query(
            "SELECT app.reprint_receipt(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                receipt_id,
                actor_id,
                command.idempotency_key,
                command.reason,
                command.delivery_reference,
            ),
            mutation=True,
        )
