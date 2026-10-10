"""Financial drafts: Staff prepare, only ``financial.approve`` confirms (BR-AUTH-010, DL-069).

A draft has no financial effect. Each draft kind adds its own record and confirm commands in a
later V1-056 slice; those commands call ``require_financial_approver`` before they confirm.
This module owns the shared reads and the reject and withdraw decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, cast
from uuid import UUID

import psycopg

from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized

FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"
FINAL_SETTLEMENTS_PREPARE_CAPABILITY: Final = "final_settlements.prepare"


class FinancialDraftKind(StrEnum):
    REFUND = "REFUND"
    DEPOSIT_FORFEITURE = "DEPOSIT_FORFEITURE"
    PAYMENT_MOVE = "PAYMENT_MOVE"
    FINAL_SETTLEMENT = "FINAL_SETTLEMENT"
    SETTLEMENT_CORRECTION = "SETTLEMENT_CORRECTION"
    PAYMENT_RETURN = "PAYMENT_RETURN"


class FinancialDraftState(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# Capabilities that let Staff prepare each draft kind; the database enforces the same pairs.
# A reader without financial.approve sees only the drafts prepared under a capability it holds
# (V1-056 sub-slice 6b), so a holder of only reservation_deposits.dispose cannot read Lease
# forfeiture drafts and the reverse.
KIND_PREPARE_CAPABILITIES: Final[dict[FinancialDraftKind, frozenset[str]]] = {
    FinancialDraftKind.REFUND: frozenset({"refunds.create", "reservation_deposits.refund"}),
    # deposits.correct prepares a Lease forfeiture reversal draft (V1-056 sub-slice 6b) and a
    # Deposit receipt reversal draft (V1-056 sub-slice 8r).
    FinancialDraftKind.DEPOSIT_FORFEITURE: frozenset(
        {"deposits.dispose", "reservation_deposits.dispose", "deposits.correct"}
    ),
    FinancialDraftKind.PAYMENT_MOVE: frozenset({"payments.allocations.reverse"}),
    FinancialDraftKind.FINAL_SETTLEMENT: frozenset({FINAL_SETTLEMENTS_PREPARE_CAPABILITY}),
    FinancialDraftKind.SETTLEMENT_CORRECTION: frozenset({FINAL_SETTLEMENTS_PREPARE_CAPABILITY}),
    # A returned Payment with no closed Final Settlement relied on (V1-056 sub-slice 10e-1a).
    FinancialDraftKind.PAYMENT_RETURN: frozenset({"payments.reverse"}),
}
PREPARE_CAPABILITIES: Final = frozenset().union(*KIND_PREPARE_CAPABILITIES.values())


class FinancialDraftAuthorizationError(PermissionError):
    pass


class FinancialDraftNotFoundError(LookupError):
    pass


class FinancialDraftInvalidError(ValueError):
    pass


class FinancialDraftConflictError(RuntimeError):
    pass


class FinancialDraftUnavailableError(RuntimeError):
    pass


def _identity(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise FinancialDraftInvalidError(f"{name} must be a nonzero UUID")
    return value


def _reason(value: object) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 1000:
        raise FinancialDraftInvalidError("Reason must be trimmed text of 1 to 1000 characters")
    return value


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialDraftAuthorizationError("Financial draft actor is invalid") from exc
    if identity.int == 0:
        raise FinancialDraftAuthorizationError("Financial draft actor is invalid")
    return identity


def _holds(actor: AuthenticatedActor, capability: str, property_id: UUID) -> bool:
    return is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))


def require_financial_approver(actor: AuthenticatedActor, property_id: UUID) -> UUID:
    """Return the actor identity only when it holds financial.approve for the Property."""
    _identity(property_id, "property_id")
    if not _holds(actor, FINANCIAL_APPROVE_CAPABILITY, property_id):
        raise FinancialDraftAuthorizationError("Only financial.approve may decide a draft")
    return _actor_identity(actor)


def require_draft_preparer(actor: AuthenticatedActor, property_id: UUID, capability: str) -> UUID:
    """Return the actor identity only when it holds the kind's prepare capability."""
    _identity(property_id, "property_id")
    if not isinstance(capability, str):
        raise FinancialDraftInvalidError("Prepare capability must be text")
    if capability not in PREPARE_CAPABILITIES or not _holds(actor, capability, property_id):
        raise FinancialDraftAuthorizationError("Draft preparation is not authorized")
    return _actor_identity(actor)


def _require_reader(actor: AuthenticatedActor, property_id: UUID) -> tuple[UUID, list[str]]:
    """Return the actor identity and the prepare capabilities whose drafts it may read."""
    _identity(property_id, "property_id")
    approver = _holds(actor, FINANCIAL_APPROVE_CAPABILITY, property_id)
    capabilities = sorted(
        capability
        for capability in PREPARE_CAPABILITIES
        if approver or _holds(actor, capability, property_id)
    )
    if not capabilities:
        raise FinancialDraftAuthorizationError("Financial draft read is not authorized")
    return _actor_identity(actor), capabilities


@dataclass(frozen=True, slots=True)
class FinancialDraftPage:
    limit: int = 50
    state: FinancialDraftState | None = None
    after_prepared_at: datetime | None = None
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise FinancialDraftInvalidError("Page limit must be between 1 and 100")
        if self.state is not None and not isinstance(self.state, FinancialDraftState):
            raise FinancialDraftInvalidError("Draft state filter is invalid")
        if self.after_prepared_at is not None and not isinstance(self.after_prepared_at, datetime):
            raise FinancialDraftInvalidError("Page cursor time must be a datetime")
        if (self.after_prepared_at is None) != (self.after_id is None):
            raise FinancialDraftInvalidError("Page cursor needs both time and identity")
        if self.after_prepared_at is not None and self.after_prepared_at.tzinfo is None:
            raise FinancialDraftInvalidError("Page cursor time must carry a time zone")
        if self.after_id is not None:
            _identity(self.after_id, "after_id")


@dataclass(frozen=True, slots=True)
class FinancialDraftService:
    database_url: str
    financial_database_url: str

    def _call(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool
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
            if exc.sqlstate in {"P0002", "P4501"}:
                raise FinancialDraftNotFoundError("Financial draft was not found") from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise FinancialDraftAuthorizationError(
                    "Financial draft actor is not authorized"
                ) from exc
            if exc.sqlstate == "22023":
                raise FinancialDraftInvalidError("Financial draft command is invalid") from exc
            if exc.sqlstate == "55000":
                raise FinancialDraftConflictError("Financial draft is already decided") from exc
            # A refusal by a database rule (for example a decision the draft's recorded
            # capability does not allow) is a conflict, not unavailable storage.
            if exc.sqlstate in {"23514", "23505"}:
                raise FinancialDraftConflictError(
                    "Financial draft decision conflicts with the draft's rules"
                ) from exc
            raise FinancialDraftUnavailableError("Financial draft storage is unavailable") from exc
        if row is None or not isinstance(row[0], dict):
            raise FinancialDraftUnavailableError("Financial draft storage returned no result")
        return cast(dict[str, object], row[0])

    def get(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id, capabilities = _require_reader(actor, property_id)
        _identity(draft_id, "draft_id")
        return self._call(
            "SELECT app.financial_draft_resource_by_capability(%s,%s,%s,%s::text[])",
            (property_id, actor_id, draft_id, capabilities),
            mutation=False,
        )

    def list(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: FinancialDraftPage | None = None,
    ) -> dict[str, object]:
        actor_id, capabilities = _require_reader(actor, property_id)
        selected = page or FinancialDraftPage()
        return self._call(
            "SELECT app.list_financial_drafts_by_capability(%s,%s,%s::text[],%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                capabilities,
                None if selected.state is None else selected.state.value,
                selected.limit,
                selected.after_prepared_at,
                selected.after_id,
            ),
            mutation=False,
        )

    def reject(
        self, property_id: UUID, draft_id: UUID, reason: str, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        actor_id = require_financial_approver(actor, property_id)
        _identity(draft_id, "draft_id")
        return self._call(
            "SELECT app.reject_financial_draft(%s,%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, _reason(reason), FINANCIAL_APPROVE_CAPABILITY),
            mutation=True,
        )

    def withdraw(
        self,
        property_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        prepare_capability: str,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        actor_id = require_draft_preparer(actor, property_id, prepare_capability)
        _identity(draft_id, "draft_id")
        return self._call(
            "SELECT app.withdraw_financial_draft(%s,%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, _reason(reason), prepare_capability),
            mutation=True,
        )
