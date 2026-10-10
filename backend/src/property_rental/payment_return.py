"""Returned Payments as drafts (BR-SETTLE-013, BR-AUTH-010; V1-056 sub-slice 10e-1a).

Staff with ``payments.reverse`` record a draft that names a received Payment that was returned (a
bounced transfer), with a reason and an evidence reference. The draft lists every active
allocation, every Customer Credit recognized from the Payment with its active applications, and
every active Deposit receipt. It has no financial effect until a ``financial.approve`` holder
confirms it. Confirmation reverses, in one transaction, the Credit applications, the Credits, the
allocations, the Deposit receipts and then the Payment, and writes one Payment return record; the
debt comes back on its obligations and stays with their Customers. A Payment whose records a closed
Final Settlement relied on is returned only through a correction of that Settlement. Rejection and
withdrawal use the shared draft decisions; the HTTP routes and screens come in slice 11c.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

PAYMENT_RETURN_PREPARE_CAPABILITY: Final = "payments.reverse"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"
PAYMENT_RETURN_CONNECT_TIMEOUT_SECONDS: Final = 3
PAYMENT_RETURN_LOCK_TIMEOUT_MS: Final = 3000
PAYMENT_RETURN_QUERY_TIMEOUT_MS: Final = 5000

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
PAYMENT_RETURN_NAMESPACE: Final = UUID("4f0c2d4e-3b0a-4c55-9e1d-6a7b8c9d0e1f")


class PaymentReturnNotFoundError(LookupError):
    pass


class PaymentReturnAuthorizationError(PermissionError):
    pass


class PaymentReturnInvalidError(ValueError):
    pass


class PaymentReturnConflictError(RuntimeError):
    """The draft or the return conflicts with the current business state."""


class PaymentReturnKeyReused(PaymentReturnConflictError):
    pass


class PaymentReturnStaleDraftError(PaymentReturnConflictError):
    """The draft's sources changed since it was recorded; it stays pending."""


class PaymentReturnUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def payment_return_draft_id(property_id: UUID, actor_id: UUID, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        PAYMENT_RETURN_NAMESPACE, f"payment-return:{property_id}:{actor_id}:{idempotency_key}"
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise PaymentReturnInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise PaymentReturnInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


@dataclass(frozen=True, slots=True)
class RecordPaymentReturnCommand:
    """Return one received Payment; the evidence reference names the bank's return notice."""

    idempotency_key: UUID
    payment_id: UUID
    reason: str
    evidence_reference: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.payment_id, "payment_id")
        _text(self.reason, "reason", 1000)
        _text(self.evidence_reference, "evidence_reference", 500)


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PaymentReturnAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise PaymentReturnAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class PaymentReturnService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise PaymentReturnAuthorizationError("Payment return action is not authorized")
        return _actor_identity(actor)

    def _call(self, sql: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=PAYMENT_RETURN_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                    (str(PAYMENT_RETURN_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                    (str(PAYMENT_RETURN_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            # P4501: the Property is unknown (V1 holds one Property).
            if exc.sqlstate in {"P0002", "P4501", "P4901"}:
                raise PaymentReturnNotFoundError("Payment or draft was not found") from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise PaymentReturnAuthorizationError(
                    "Payment return actor is not authorized"
                ) from exc
            if exc.sqlstate == "22023":
                raise PaymentReturnInvalidError("Payment return command is invalid") from exc
            if exc.sqlstate == "P5205":
                raise PaymentReturnKeyReused("Payment return key was reused") from exc
            if exc.sqlstate == "P5S02":
                raise PaymentReturnStaleDraftError(
                    "Payment return draft is stale; its sources changed"
                ) from exc
            # Refusals caused by business state reach the user as a conflict (owner answer for
            # slice 11c): a blocked draft (55000), a guard (23514), a decided draft, a lock or
            # serialization failure; nothing was written.
            if exc.sqlstate in {
                "55000",
                "23514",
                "23505",
                "23P01",
                "P4904",
                "P5S01",
                "40001",
                "40P01",
                "55P03",
            }:
                raise PaymentReturnConflictError(
                    "Payment return conflicts with the current state"
                ) from exc
            raise PaymentReturnUnavailableError(
                "Payment return outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise PaymentReturnUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        command: RecordPaymentReturnCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the return draft; it has no financial effect until confirmed."""
        actor_id = self._authorize(actor, property_id, PAYMENT_RETURN_PREPARE_CAPABILITY)
        request = RecordPaymentReturnCommand(
            command.idempotency_key, command.payment_id, command.reason, command.evidence_reference
        )
        return self._call(
            "SELECT app.record_payment_return_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                payment_return_draft_id(property_id, actor_id, request.idempotency_key),
                request.payment_id,
                Jsonb({"evidence_reference": request.evidence_reference}),
                request.reason,
                PAYMENT_RETURN_PREPARE_CAPABILITY,
            ),
        )

    def confirm(
        self,
        property_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Return the Payment as drafted; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_payment_return(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
        )
