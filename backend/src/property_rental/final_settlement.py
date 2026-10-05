"""Final Settlement records (BR-SETTLE-001; V1-056 sub-slice 8a-1).

Staff holding ``final_settlements.prepare`` open the one Final Settlement of a TERMINATED Lease.
Opening it has no financial effect. Deposit applications (DB-DEP-005) are written only by the
Settlement confirm, which a ``financial.approve`` holder runs (sub-slice 8e); no role may write
them directly. The preview, the draft and the confirm follow in sub-slices 8b to 8e; the HTTP
routes and screens come in slice 11e.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import psycopg

from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
)
from property_rental.financial_draft import FINAL_SETTLEMENTS_PREPARE_CAPABILITY
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class FinalSettlementNotFoundError(LookupError):
    pass


class FinalSettlementAuthorizationError(PermissionError):
    pass


class FinalSettlementInvalidError(ValueError):
    pass


class FinalSettlementConflictError(RuntimeError):
    pass


class FinalSettlementUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise FinalSettlementInvalidError(f"{name} must be a nonzero UUID")
    return value


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinalSettlementAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise FinalSettlementAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class FinalSettlementService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise FinalSettlementAuthorizationError("Final Settlement action is not authorized")
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
                raise FinalSettlementNotFoundError(
                    "Lease or Final Settlement was not found"
                ) from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise FinalSettlementAuthorizationError(
                    "Final Settlement actor is not authorized"
                ) from exc
            if exc.sqlstate in {"22023", "23514"}:
                raise FinalSettlementInvalidError("Final Settlement command is invalid") from exc
            # 55000: business state (for example the Lease is not TERMINATED); a refusal caused by
            # business state reaches the user as a conflict (owner answer for slice 11c).
            if exc.sqlstate in {"55000", "55P03", "40001", "40P01", "23505"}:
                raise FinalSettlementConflictError(
                    "Final Settlement conflicts with the current state"
                ) from exc
            raise FinalSettlementUnavailableError(
                "Final Settlement outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise FinalSettlementUnavailableError("Final Settlement storage returned no result")
        return cast(dict[str, object], row[0])

    def start(
        self, property_id: UUID, lease_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Open the Lease's one Final Settlement, or return the one already open or closed."""
        actor_id = self._authorize(actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY)
        _uuid(lease_id, "lease_id")
        return self._call(
            "SELECT app.start_final_settlement(%s,%s,%s)", (property_id, actor_id, lease_id)
        )
