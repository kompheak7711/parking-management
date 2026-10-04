"""Wrong-Unit Payment moves as drafts (BR-PAY-042, BR-AUTH-010; V1-056 slice 7).

Staff with ``payments.allocations.reverse`` record a draft that names the Invoice allocation made
on the wrong Unit's Invoice, the correct Invoice on another Unit, a reason and, as text, how each
of the two Customers acknowledged the mistake (who, the date and how). It has no financial effect
until a ``financial.approve`` holder confirms it. Confirmation reverses the wrong allocation and
allocates the same Payment to the correct Invoice in one transaction; the Payment record and its
Receipt never change and no Customer Credit moves between Customers. Rejection and withdrawal use
the shared draft decisions; the HTTP routes and screens come in slice 11d.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

PAYMENT_MOVE_PREPARE_CAPABILITY: Final = "payments.allocations.reverse"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"
PAYMENT_MOVE_CONNECT_TIMEOUT_SECONDS: Final = 3
PAYMENT_MOVE_LOCK_TIMEOUT_MS: Final = 3000
PAYMENT_MOVE_QUERY_TIMEOUT_MS: Final = 5000

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
PAYMENT_MOVE_NAMESPACE: Final = UUID("9b6e6294-9548-4a7c-b835-aafe56888ab2")


class PaymentMoveNotFoundError(LookupError):
    pass


class PaymentMoveAuthorizationError(PermissionError):
    pass


class PaymentMoveInvalidError(ValueError):
    pass


class PaymentMoveConflictError(RuntimeError):
    """The draft or the move conflicts with the current business state."""


class PaymentMoveKeyReused(PaymentMoveConflictError):
    pass


class PaymentMoveUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def payment_move_draft_id(property_id: UUID, actor_id: UUID, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(PAYMENT_MOVE_NAMESPACE, f"payment-move:{property_id}:{actor_id}:{idempotency_key}")


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise PaymentMoveInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise PaymentMoveInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


@dataclass(frozen=True, slots=True)
class RecordPaymentMoveCommand:
    """Move one Invoice allocation of a Payment to the correct Invoice on another Unit.

    Each acknowledgement states who acknowledged for that Customer, the date and how.
    """

    idempotency_key: UUID
    allocation_id: UUID
    target_invoice_id: UUID
    reason: str
    source_acknowledgement: str
    target_acknowledgement: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.allocation_id, "allocation_id")
        _uuid(self.target_invoice_id, "target_invoice_id")
        _text(self.reason, "reason", 1000)
        _text(self.source_acknowledgement, "source_acknowledgement", 2000)
        _text(self.target_acknowledgement, "target_acknowledgement", 2000)


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentMoveAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise PaymentMoveAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class PaymentMoveService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise PaymentMoveAuthorizationError("Payment move action is not authorized")
        return _actor_identity(actor)

    def _call(self, sql: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=PAYMENT_MOVE_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                    (str(PAYMENT_MOVE_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                    (str(PAYMENT_MOVE_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            # P4501: the Property is unknown (V1 holds one Property).
            if exc.sqlstate in {"P0002", "P4501", "P4901"}:
                raise PaymentMoveNotFoundError(
                    "Payment allocation, Invoice or draft was not found"
                ) from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise PaymentMoveAuthorizationError("Payment move actor is not authorized") from exc
            if exc.sqlstate == "22023":
                raise PaymentMoveInvalidError("Payment move command is invalid") from exc
            if exc.sqlstate == "P5205":
                raise PaymentMoveKeyReused("Payment move key was reused") from exc
            # Refusals caused by business state reach the user as a conflict (owner answer for
            # slice 11c): a stale or blocked draft (55000), a guard (23514), a decided draft, a
            # lock or serialization failure; nothing was written.
            if exc.sqlstate in {
                "55000",
                "23514",
                "23505",
                "23P01",
                "P4904",
                "40001",
                "40P01",
                "55P03",
            }:
                raise PaymentMoveConflictError(
                    "Payment move conflicts with the current state"
                ) from exc
            raise PaymentMoveUnavailableError(
                "Payment move outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise PaymentMoveUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        command: RecordPaymentMoveCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the move draft; it has no financial effect until confirmed."""
        actor_id = self._authorize(actor, property_id, PAYMENT_MOVE_PREPARE_CAPABILITY)
        request = RecordPaymentMoveCommand(
            command.idempotency_key,
            command.allocation_id,
            command.target_invoice_id,
            command.reason,
            command.source_acknowledgement,
            command.target_acknowledgement,
        )
        return self._call(
            "SELECT app.record_payment_move_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                payment_move_draft_id(property_id, actor_id, request.idempotency_key),
                request.allocation_id,
                request.target_invoice_id,
                request.reason,
                request.source_acknowledgement,
                request.target_acknowledgement,
                PAYMENT_MOVE_PREPARE_CAPABILITY,
            ),
        )

    def confirm(
        self,
        property_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Move the Payment as drafted; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_payment_move_draft(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
        )
