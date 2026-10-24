"""Reservation Deposit Refunds and forfeitures as drafts (BR-AUTH-010; V1-056 slice 3b).

A cancelled or expired Reservation keeps its Security Deposit held until a ``financial.approve``
holder confirms a Staff draft of its outcome. The outcome follows the cancellation
responsibility (BR-RES-021, BR-RES-022): a Customer-caused cancellation or expiration gives a
forfeiture draft (``reservation_deposits.dispose``), a Property-caused cancellation a Refund
draft (``reservation_deposits.refund``) to the Reservation Customer with a Refund method and
reference note (BR-REFUND-014). A correction that replaces a confirmed outcome is a draft too
and also needs ``reservation_deposits.correct``. The database checks the active human actor,
the Property, the recorded authorization references and every outcome rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg

from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
)
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized
from property_rental.refund import RefundMethodChoice

RESERVATION_READ_CAPABILITY: Final = "reservations.read"
DEPOSIT_DISPOSITION_CAPABILITY: Final = "reservation_deposits.dispose"
DEPOSIT_REFUND_CAPABILITY: Final = "reservation_deposits.refund"
DEPOSIT_OUTCOME_CORRECT_CAPABILITY: Final = "reservation_deposits.correct"
FINANCIAL_APPROVE_CAPABILITY: Final = "financial.approve"

# Draft keys keep the command-key scope (Property, preparer and key), as Refund drafts do.
RESERVATION_DEPOSIT_DRAFT_NAMESPACE: Final = UUID("2f8f0a4e-7c35-4d0b-a3b1-8e5c4d6a9b17")


class ReservationDepositDecision(StrEnum):
    """The draft kind that a cancellation responsibility allows."""

    REFUND = "REFUND"
    DEPOSIT_FORFEITURE = "DEPOSIT_FORFEITURE"


DECISION_CAPABILITIES: Final[dict[ReservationDepositDecision, str]] = {
    ReservationDepositDecision.REFUND: DEPOSIT_REFUND_CAPABILITY,
    ReservationDepositDecision.DEPOSIT_FORFEITURE: DEPOSIT_DISPOSITION_CAPABILITY,
}


class ReservationDepositDraftNotFoundError(LookupError):
    pass


class ReservationDepositDraftAuthorizationError(PermissionError):
    pass


class ReservationDepositDraftInvalidError(ValueError):
    pass


class ReservationDepositDraftConflictError(RuntimeError):
    pass


class ReservationDepositDraftKeyReused(ReservationDepositDraftConflictError):
    pass


class ReservationDepositDraftUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


def reservation_deposit_draft_id(property_id: UUID, actor_id: UUID, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        RESERVATION_DEPOSIT_DRAFT_NAMESPACE,
        f"reservation-deposit:{property_id}:{actor_id}:{idempotency_key}",
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ReservationDepositDraftInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise ReservationDepositDraftInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


def draft_refund_reference(outcome_id: UUID) -> str:
    """The internal reference of a Refund draft; the database gives the Refund its number.

    DL-071 answer 10 (V1-059 part B): staff no longer type a Refund number. The Refund gets the
    next RFD number when the draft is confirmed and the Refund is recorded.
    """
    return f"DRAFT-{outcome_id}"


def _refund_details(
    decision: ReservationDepositDecision,
    outcome_id: UUID,
    method: RefundMethodChoice | None,
) -> tuple[str | None, UUID | None, str | None]:
    if decision is ReservationDepositDecision.REFUND:
        if method is None:
            raise ReservationDepositDraftInvalidError(
                "A Reservation Refund draft needs a Refund method and reference note"
            )
        choice = RefundMethodChoice(method.refund_method_id, method.reference_note)
        return (
            draft_refund_reference(outcome_id),
            choice.refund_method_id,
            choice.reference_note,
        )
    if method is not None:
        raise ReservationDepositDraftInvalidError("A forfeiture draft takes no Refund details")
    return None, None, None


@dataclass(frozen=True, slots=True)
class RecordReservationDepositDraftCommand:
    """The Deposit decision of a cancelled or expired Reservation."""

    idempotency_key: UUID
    reservation_id: UUID
    outcome_id: UUID
    reason: str
    method: RefundMethodChoice | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.reservation_id, "reservation_id")
        _uuid(self.outcome_id, "outcome_id")
        _text(self.reason, "reason", 1000)


@dataclass(frozen=True, slots=True)
class RecordReservationDepositCorrectionDraftCommand:
    """Replace the confirmed outcome with a new outcome of the same kind."""

    idempotency_key: UUID
    reservation_id: UUID
    expected_outcome_id: UUID
    correction_id: UUID
    replacement_outcome_id: UUID
    reason: str
    evidence_reference: str
    method: RefundMethodChoice | None = None

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "reservation_id",
            "expected_outcome_id",
            "correction_id",
            "replacement_outcome_id",
        ):
            _uuid(getattr(self, name), name)
        if self.correction_id == self.replacement_outcome_id:
            raise ReservationDepositDraftInvalidError("Correction and replacement ids must differ")
        _text(self.reason, "reason", 1000)
        _text(self.evidence_reference, "evidence_reference", 500)


@dataclass(frozen=True, slots=True)
class ReservationDepositDecisionPage:
    limit: int = 50
    after_cancelled_at: datetime | None = None
    after_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ReservationDepositDraftInvalidError("Page limit must be between 1 and 100")
        if (self.after_cancelled_at is None) != (self.after_id is None):
            raise ReservationDepositDraftInvalidError("Page cursor needs both time and identity")
        if self.after_cancelled_at is not None:
            if (
                not isinstance(self.after_cancelled_at, datetime)
                or self.after_cancelled_at.tzinfo is None
                or self.after_cancelled_at.utcoffset() is None
            ):
                raise ReservationDepositDraftInvalidError("Page cursor time must carry a time zone")
            object.__setattr__(self, "after_cancelled_at", self.after_cancelled_at.astimezone(UTC))
        if self.after_id is not None:
            _uuid(self.after_id, "after_id")


def _actor_identity(actor: AuthenticatedActor) -> UUID:
    try:
        identity = UUID(actor.actor_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReservationDepositDraftAuthorizationError("Actor identity is invalid") from exc
    if identity.int == 0:
        raise ReservationDepositDraftAuthorizationError("Actor identity is invalid")
    return identity


@dataclass(frozen=True, slots=True)
class ReservationDepositDraftService:
    database_url: str
    financial_database_url: str

    @staticmethod
    def _authorize(actor: AuthenticatedActor, property_id: UUID, *capabilities: str) -> UUID:
        _uuid(property_id, "property_id")
        for capability in capabilities:
            if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
                raise ReservationDepositDraftAuthorizationError(
                    "Reservation Deposit draft action is not authorized"
                )
        return _actor_identity(actor)

    def _call(
        self, sql: str, parameters: tuple[object, ...], *, mutation: bool
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url if mutation else self.database_url,
                connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS,
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
                raise ReservationDepositDraftNotFoundError(
                    "Reservation or draft was not found"
                ) from exc
            if exc.sqlstate in {"42501", "P4506"}:
                raise ReservationDepositDraftAuthorizationError(
                    "Reservation Deposit draft actor is not authorized"
                ) from exc
            if exc.sqlstate in {"22023", "23514"}:
                raise ReservationDepositDraftInvalidError(
                    "Reservation Deposit draft command is invalid"
                ) from exc
            if exc.sqlstate == "P5205":
                raise ReservationDepositDraftKeyReused(
                    "Reservation Deposit draft key was reused"
                ) from exc
            if exc.sqlstate in {"55000", "40001", "23505", "P0001"}:
                raise ReservationDepositDraftConflictError(
                    "Reservation Deposit draft conflicts with the current state"
                ) from exc
            raise ReservationDepositDraftUnavailableError(
                "Reservation Deposit draft outcome unresolved; preserve and replay the command"
            ) from exc
        if row is None or not isinstance(row[0], dict):
            raise ReservationDepositDraftUnavailableError("Draft storage returned no result")
        return cast(dict[str, object], row[0])

    def record(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the Deposit decision draft; it has no financial effect until confirmed."""
        if not isinstance(decision, ReservationDepositDecision):
            raise ReservationDepositDraftInvalidError("Reservation Deposit decision is invalid")
        capability = DECISION_CAPABILITIES[decision]
        actor_id = self._authorize(actor, property_id, capability)
        request = RecordReservationDepositDraftCommand(
            command.idempotency_key,
            command.reservation_id,
            command.outcome_id,
            command.reason,
            command.method,
        )
        refund_reference, method_id, note = _refund_details(
            decision, request.outcome_id, request.method
        )
        return self._call(
            "SELECT app.record_reservation_deposit_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                reservation_deposit_draft_id(property_id, actor_id, request.idempotency_key),
                request.reservation_id,
                decision.value,
                request.outcome_id,
                request.reason,
                refund_reference,
                method_id,
                note,
                capability,
            ),
            mutation=True,
        )

    def record_correction(
        self,
        property_id: UUID,
        decision: ReservationDepositDecision,
        command: RecordReservationDepositCorrectionDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a draft that replaces the confirmed outcome; nothing changes until confirmed."""
        if not isinstance(decision, ReservationDepositDecision):
            raise ReservationDepositDraftInvalidError("Reservation Deposit decision is invalid")
        capability = DECISION_CAPABILITIES[decision]
        actor_id = self._authorize(
            actor, property_id, DEPOSIT_OUTCOME_CORRECT_CAPABILITY, capability
        )
        request = RecordReservationDepositCorrectionDraftCommand(
            command.idempotency_key,
            command.reservation_id,
            command.expected_outcome_id,
            command.correction_id,
            command.replacement_outcome_id,
            command.reason,
            command.evidence_reference,
            command.method,
        )
        refund_reference, method_id, note = _refund_details(
            decision, request.replacement_outcome_id, request.method
        )
        return self._call(
            "SELECT app.record_reservation_deposit_correction_draft("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                reservation_deposit_draft_id(property_id, actor_id, request.idempotency_key),
                request.reservation_id,
                decision.value,
                request.expected_outcome_id,
                request.correction_id,
                request.replacement_outcome_id,
                request.reason,
                request.evidence_reference,
                refund_reference,
                method_id,
                note,
                DEPOSIT_OUTCOME_CORRECT_CAPABILITY,
                capability,
            ),
            mutation=True,
        )

    def confirm(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Apply the draft's outcome; only a financial.approve holder may confirm."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(reservation_id, "reservation_id")
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_reservation_deposit_draft(%s,%s,%s,%s,%s)",
            (property_id, actor_id, reservation_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            mutation=True,
        )

    def reject(
        self,
        property_id: UUID,
        reservation_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Reject a pending draft; only a financial.approve holder may. No money moves."""
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(reservation_id, "reservation_id")
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.reject_reservation_deposit_draft(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                reservation_id,
                draft_id,
                _text(reason, "reason", 1000),
                FINANCIAL_APPROVE_CAPABILITY,
            ),
            mutation=True,
        )

    def withdraw(
        self,
        property_id: UUID,
        reservation_id: UUID,
        decision: ReservationDepositDecision,
        draft_id: UUID,
        reason: str,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Withdraw a pending draft; only its preparer, with its capability. No money moves."""
        if not isinstance(decision, ReservationDepositDecision):
            raise ReservationDepositDraftInvalidError("Reservation Deposit decision is invalid")
        capability = DECISION_CAPABILITIES[decision]
        actor_id = self._authorize(actor, property_id, capability)
        _uuid(reservation_id, "reservation_id")
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.withdraw_reservation_deposit_draft(%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                reservation_id,
                draft_id,
                _text(reason, "reason", 1000),
                capability,
            ),
            mutation=True,
        )

    def awaiting(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        page: ReservationDepositDecisionPage | None = None,
    ) -> dict[str, object]:
        """Reservations waiting for a Deposit decision, oldest cancellation first."""
        actor_id = self._authorize(actor, property_id, RESERVATION_READ_CAPABILITY)
        selected = page or ReservationDepositDecisionPage()
        return self._call(
            "SELECT app.list_reservations_awaiting_deposit_decision(%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                selected.limit,
                selected.after_cancelled_at,
                selected.after_id,
            ),
            mutation=False,
        )
