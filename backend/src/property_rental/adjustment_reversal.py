"""Mistaken credit Adjustment reversals as drafts (BR-INV-044, BR-AUTH-010; V1-056 sub-slice 10f-1).

Staff with ``invoices.adjust`` record a draft that names a credit Adjustment recorded by mistake,
with a reason. The draft lists the line the reversal restores and, for each paid value the
Adjustment released, the Customer Credit that holds it, the part of that Credit still available
and the part that stays as debt. It has no financial effect until a ``financial.approve`` holder
confirms it. Confirmation writes, in one transaction, the Adjustment reversal and puts the part
still available back on the line as Credit applications. After the Lease's Final Settlement is
closed, the reversal is a correction of that Settlement instead (sub-slice 10f-2). Rejection and
withdrawal use the shared draft decisions; the HTTP routes and screens come in slice 11.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

ADJUSTMENT_REVERSAL_PREPARE_CAPABILITY: Final = "invoices.adjust"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"
ADJUSTMENT_REVERSAL_CONNECT_TIMEOUT_SECONDS: Final = 3
ADJUSTMENT_REVERSAL_LOCK_TIMEOUT_MS: Final = 3000
ADJUSTMENT_REVERSAL_QUERY_TIMEOUT_MS: Final = 5000

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
ADJUSTMENT_REVERSAL_NAMESPACE: Final = UUID("a6d1c7e2-58b4-4f0e-9c3a-2b7e41d09f53")


class AdjustmentReversalNotFoundError(LookupError):
    pass


class AdjustmentReversalAuthorizationError(PermissionError):
    pass


class AdjustmentReversalInvalidError(ValueError):
    pass


class AdjustmentReversalConflictError(RuntimeError):
    """The draft or the reversal conflicts with the current business state."""


class AdjustmentReversalKeyReused(AdjustmentReversalConflictError):
    pass


class AdjustmentReversalStaleDraftError(AdjustmentReversalConflictError):
    """The draft's sources changed since it was recorded; it stays pending."""


class AdjustmentReversalUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def adjustment_reversal_draft_id(property_id: UUID, actor_id: UUID, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        ADJUSTMENT_REVERSAL_NAMESPACE,
        f"adjustment-reversal:{property_id}:{actor_id}:{idempotency_key}",
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise AdjustmentReversalInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise AdjustmentReversalInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


@dataclass(frozen=True, slots=True)
class RecordAdjustmentReversalCommand:
    """Reverse one credit Adjustment recorded by mistake."""

    idempotency_key: UUID
    adjustment_id: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.adjustment_id, "adjustment_id")
        _text(self.reason, "reason", 1000)


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AdjustmentReversalAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise AdjustmentReversalAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class AdjustmentReversalService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise AdjustmentReversalAuthorizationError(
                "Adjustment reversal action is not authorized"
            )
        return _actor_identity(actor)

    def _call(self, sql: str, parameters: tuple[object, ...]) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url,
                connect_timeout=ADJUSTMENT_REVERSAL_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                connection.execute(
                    "SELECT pg_catalog.set_config('lock_timeout', %s, true)",
                    (str(ADJUSTMENT_REVERSAL_LOCK_TIMEOUT_MS),),
                )
                connection.execute(
                    "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                    (str(ADJUSTMENT_REVERSAL_QUERY_TIMEOUT_MS),),
                )
                row = connection.execute(sql, parameters).fetchone()
        except psycopg.Error as exc:
            # P4501: the Property is unknown (V1 holds one Property).
            if exc.sqlstate in {"P0002", "P4501"}:
                raise AdjustmentReversalNotFoundError("Adjustment or draft was not found") from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise AdjustmentReversalAuthorizationError(
                    "Adjustment reversal actor is not authorized"
                ) from exc
            if exc.sqlstate == "22023":
                raise AdjustmentReversalInvalidError(
                    "Adjustment reversal command is invalid"
                ) from exc
            if exc.sqlstate == "P5205":
                raise AdjustmentReversalKeyReused("Adjustment reversal key was reused") from exc
            if exc.sqlstate == "P5S02":
                raise AdjustmentReversalStaleDraftError(
                    "Adjustment reversal draft is stale; its sources changed"
                ) from exc
            # Refusals caused by business state reach the user as a conflict: a blocked draft
            # (55000), a guard (23514), a decided draft, a closed Final Settlement (P5S01), a lock
            # or serialization failure; nothing was written.
            if exc.sqlstate in {
                "55000",
                "23514",
                "23505",
                "23P01",
                "P5S01",
                "40001",
                "40P01",
                "55P03",
            }:
                raise AdjustmentReversalConflictError(
                    "Adjustment reversal conflicts with the current state"
                ) from exc
            raise AdjustmentReversalUnavailableError(
                "Adjustment reversal outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise AdjustmentReversalUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        command: RecordAdjustmentReversalCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the reversal draft; it has no financial effect until confirmed."""
        actor_id = self._authorize(actor, property_id, ADJUSTMENT_REVERSAL_PREPARE_CAPABILITY)
        request = RecordAdjustmentReversalCommand(
            command.idempotency_key, command.adjustment_id, command.reason
        )
        return self._call(
            "SELECT app.record_adjustment_reversal_draft(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                adjustment_reversal_draft_id(property_id, actor_id, request.idempotency_key),
                request.adjustment_id,
                request.reason,
                ADJUSTMENT_REVERSAL_PREPARE_CAPABILITY,
            ),
        )

    def confirm(
        self,
        property_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Reverse the Adjustment as drafted; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_adjustment_reversal(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
        )
