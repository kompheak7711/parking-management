"""Lease Deposit forfeitures as drafts (BR-AUTH-010, BR-DEP-026; V1-056 slice 6).

Staff with ``deposits.dispose`` record a draft that forfeits the whole held Lease Deposit; it has
no financial effect until a ``financial.approve`` holder confirms it. The forfeiture ground is
worked out by the database from the termination record (voluntary early leaving, pet
noncompliance, unpaid Initial obligation, non-pet violation, 30-day Rent nonpayment default);
a forfeited Security Deposit is never applied to what the Customer owes. The BR-DEP-027 Pet
Deposit outcome is decided at Final Settlement. Rejection and withdrawal use the shared draft
decisions; their HTTP routes come with the draft screens.
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

DEPOSIT_DISPOSE_CAPABILITY: Final = "deposits.dispose"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
LEASE_DEPOSIT_FORFEITURE_NAMESPACE: Final = UUID("6c1d9f2a-3b4e-4f6a-9c7d-1e2f3a4b5c6d")


class LeaseDepositForfeitureNotFoundError(LookupError):
    pass


class LeaseDepositForfeitureAuthorizationError(PermissionError):
    pass


class LeaseDepositForfeitureInvalidError(ValueError):
    pass


class LeaseDepositForfeitureConflictError(RuntimeError):
    pass


class LeaseDepositForfeitureKeyReused(LeaseDepositForfeitureConflictError):
    pass


class LeaseDepositForfeitureUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def lease_deposit_forfeiture_draft_id(
    property_id: UUID, actor_id: UUID, idempotency_key: UUID
) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        LEASE_DEPOSIT_FORFEITURE_NAMESPACE,
        f"lease-deposit-forfeiture:{property_id}:{actor_id}:{idempotency_key}",
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise LeaseDepositForfeitureInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise LeaseDepositForfeitureInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


@dataclass(frozen=True, slots=True)
class RecordLeaseDepositForfeitureCommand:
    """Forfeit the whole held Deposit of a terminated Lease."""

    idempotency_key: UUID
    deposit_id: UUID
    disposition_id: UUID
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.deposit_id, "deposit_id")
        _uuid(self.disposition_id, "disposition_id")
        _text(self.reason, "reason", 1000)


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LeaseDepositForfeitureAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise LeaseDepositForfeitureAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class LeaseDepositForfeitureService:
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
        _uuid(property_id, "property_id")
        if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
            raise LeaseDepositForfeitureAuthorizationError(
                "Lease Deposit forfeiture action is not authorized"
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
                raise LeaseDepositForfeitureNotFoundError(
                    "Lease Deposit or draft was not found"
                ) from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise LeaseDepositForfeitureAuthorizationError(
                    "Lease Deposit forfeiture actor is not authorized"
                ) from exc
            if exc.sqlstate in {"22023", "23514"}:
                raise LeaseDepositForfeitureInvalidError(
                    "Lease Deposit forfeiture command is invalid"
                ) from exc
            if exc.sqlstate == "P5205":
                raise LeaseDepositForfeitureKeyReused(
                    "Lease Deposit forfeiture key was reused"
                ) from exc
            # P5801: the Deposit's financial observation changed during confirmation;
            # 23P01: an exclusion constraint met a concurrent record.
            if exc.sqlstate in {"55000", "55P03", "40001", "23505", "23P01", "P5801", "P0001"}:
                raise LeaseDepositForfeitureConflictError(
                    "Lease Deposit forfeiture conflicts with the current state"
                ) from exc
            raise LeaseDepositForfeitureUnavailableError(
                "Lease Deposit forfeiture outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise LeaseDepositForfeitureUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        command: RecordLeaseDepositForfeitureCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the forfeiture draft; it has no financial effect until confirmed."""
        actor_id = self._authorize(actor, property_id, DEPOSIT_DISPOSE_CAPABILITY)
        request = RecordLeaseDepositForfeitureCommand(
            command.idempotency_key, command.deposit_id, command.disposition_id, command.reason
        )
        return self._call(
            "SELECT app.record_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                lease_deposit_forfeiture_draft_id(property_id, actor_id, request.idempotency_key),
                request.deposit_id,
                request.disposition_id,
                request.reason,
                DEPOSIT_DISPOSE_CAPABILITY,
            ),
        )

    def confirm(
        self,
        property_id: UUID,
        deposit_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Forfeit the Deposit as drafted; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(deposit_id, "deposit_id")
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s)",
            (property_id, actor_id, deposit_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
        )
