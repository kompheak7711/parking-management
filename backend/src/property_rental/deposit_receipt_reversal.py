"""Deposit receipt reversals as drafts (BR-AUTH-010; V1-056 sub-slice 8r).

A receipt reversal records that money recorded as received for a Lease or Reservation Deposit
was not received (for example a returned transfer). It returns the receipt's value to its
Payment, so it is a draft (owner answer to Q-2026-10-05-22): Staff with ``deposits.correct``
record it, and it has no financial effect until a ``financial.approve`` holder confirms it. The
confirmation runs the earlier receipt reversal, so every earlier rule applies. Rejection and
withdrawal use the shared draft decisions; their HTTP routes come with the draft screens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg

from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
)
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

DEPOSIT_CORRECT_CAPABILITY: Final = "deposits.correct"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
DEPOSIT_RECEIPT_REVERSAL_NAMESPACE: Final = UUID("8e3b1f57-4c2d-4a9e-b6f0-2d7c5a1e9b43")


class DepositReceiptReversalNotFoundError(LookupError):
    pass


class DepositReceiptReversalAuthorizationError(PermissionError):
    pass


class DepositReceiptReversalInvalidError(ValueError):
    pass


class DepositReceiptReversalConflictError(RuntimeError):
    pass


class DepositReceiptReversalKeyReused(DepositReceiptReversalConflictError):
    pass


class DepositReceiptReversalUnavailableError(RuntimeError):
    pass


def deposit_receipt_reversal_draft_id(
    property_id: UUID, actor_id: UUID, idempotency_key: UUID
) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        DEPOSIT_RECEIPT_REVERSAL_NAMESPACE,
        f"deposit-receipt-reversal:{property_id}:{actor_id}:{idempotency_key}",
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise DepositReceiptReversalInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise DepositReceiptReversalInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


@dataclass(frozen=True, slots=True)
class RecordDepositReceiptReversalCommand:
    """Reverse one Deposit receipt, with the reason the money was not received."""

    idempotency_key: UUID
    receipt_id: UUID
    reversal_id: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.receipt_id, "receipt_id")
        _uuid(self.reversal_id, "reversal_id")
        if self.reversal_id == self.receipt_id:
            raise DepositReceiptReversalInvalidError("reversal_id must differ from receipt_id")
        _text(self.reason, "reason", 500)


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DepositReceiptReversalAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise DepositReceiptReversalAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class DepositReceiptReversalService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise DepositReceiptReversalAuthorizationError(
                "Deposit receipt reversal action is not authorized"
            )
        return _actor_identity(actor)

    def _call(self, sql: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                    (str(DEPOSIT_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                    (str(DEPOSIT_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate in {"P0002", "P4501"}:
                raise DepositReceiptReversalNotFoundError(
                    "Deposit receipt or draft was not found"
                ) from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise DepositReceiptReversalAuthorizationError(
                    "Deposit receipt reversal actor is not authorized"
                ) from exc
            if exc.sqlstate in {"22023", "23514"}:
                raise DepositReceiptReversalInvalidError(
                    "Deposit receipt reversal command is invalid"
                ) from exc
            if exc.sqlstate == "P5205":
                raise DepositReceiptReversalKeyReused(
                    "Deposit receipt reversal key was reused"
                ) from exc
            # 55000: dependent history or a pending draft; P5801: the Deposit's financial
            # observation changed during confirmation.
            if exc.sqlstate in {"55000", "55P03", "40001", "23505", "23P01", "P5801", "P0001"}:
                raise DepositReceiptReversalConflictError(
                    "Deposit receipt reversal conflicts with the current state"
                ) from exc
            raise DepositReceiptReversalUnavailableError(
                "Deposit receipt reversal outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise DepositReceiptReversalUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        command: RecordDepositReceiptReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the receipt reversal draft; it has no financial effect until confirmed."""
        actor_id = self._authorize(actor, property_id, DEPOSIT_CORRECT_CAPABILITY)
        request = RecordDepositReceiptReversalCommand(
            command.idempotency_key, command.receipt_id, command.reversal_id, command.reason
        )
        return self._call(
            "SELECT app.record_deposit_receipt_reversal_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                deposit_receipt_reversal_draft_id(property_id, actor_id, request.idempotency_key),
                request.receipt_id,
                request.reversal_id,
                request.reason,
                DEPOSIT_CORRECT_CAPABILITY,
            ),
        )

    def confirm(
        self,
        property_id: UUID,
        receipt_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Reverse the receipt as drafted; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(receipt_id, "receipt_id")
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_deposit_receipt_reversal_draft(%s,%s,%s,%s,%s)",
            (property_id, actor_id, receipt_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
        )
