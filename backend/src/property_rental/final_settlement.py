"""Final Settlement records (BR-SETTLE-001; V1-056 sub-slice 8a-1).

Staff holding ``final_settlements.prepare`` open the one Final Settlement of a TERMINATED Lease.
Opening it has no financial effect. Deposit applications (DB-DEP-005) are written only by the
Settlement confirm, which a ``financial.approve`` holder runs (sub-slice 8e); no role may write
them directly. The preview (sub-slice 8b) is a read under the runtime role for holders of
``final_settlements.prepare`` or ``financial.approve``; it writes nothing. Staff record the
Settlement draft (sub-slice 8c) under ``final_settlements.prepare``: the DL-032 steps in order with
amounts in cents. The draft has no financial effect; only a ``financial.approve`` holder confirms
it (sub-slice 8e), and withdraw and reject use the shared draft decisions. A ``financial.approve``
holder confirms the draft (sub-slice 8e-3): in one transaction the database checks the plan again,
writes the Credit applications, Deposit applications and Refunds, the closure snapshots and the
closing balance, and closes the Settlement for good. The HTTP routes and screens come in slice 11e.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from property_rental.deposit import (
    DEPOSIT_CONNECT_TIMEOUT_SECONDS,
    DEPOSIT_LOCK_TIMEOUT_MS,
    DEPOSIT_QUERY_TIMEOUT_MS,
)
from property_rental.financial_draft import (
    FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
    FINANCIAL_APPROVE_CAPABILITY,
    PREPARE_CAPABILITIES,
)
from property_rental.identity import AuthenticatedActor, AuthorizationRequirement, is_authorized


class FinalSettlementNotFoundError(LookupError):
    pass


class FinalSettlementAuthorizationError(PermissionError):
    pass


class FinalSettlementInvalidError(ValueError):
    pass


class FinalSettlementConflictError(RuntimeError):
    pass


class FinalSettlementKeyReused(FinalSettlementConflictError):
    pass


class FinalSettlementStaleDraftError(FinalSettlementConflictError):
    """The draft no longer matches its sources; it stays pending and is prepared again."""


class FinalSettlementUnavailableError(RuntimeError):
    """An outcome may be unknown: preserve and replay the original command."""


# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
FINAL_SETTLEMENT_DRAFT_NAMESPACE: Final = UUID("5c0f3c55-0f43-4b8e-9d4a-7f1d2b6a8e31")
MAX_SETTLEMENT_STEPS: Final = 200
MAX_USD_CENTS: Final = 9_000_000_000_000_000
# The confirm (sub-slice 8e-3) reports a draft its sources no longer match as stale (P5S02); the
# Settlement writers it calls refuse such a step with 23514, 23505 or a Credit proposal code.
CONFIRM_STALE_STATES: Final = frozenset({"P5S02", "23514", "23505", "P5101", "P5102", "P5104"})


def final_settlement_draft_id(property_id: UUID, actor_id: UUID, idempotency_key: UUID) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        FINAL_SETTLEMENT_DRAFT_NAMESPACE,
        f"final-settlement-draft:{property_id}:{actor_id}:{idempotency_key}",
    )


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise FinalSettlementInvalidError(f"{name} must be a nonzero UUID")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= limit
        or "\x00" in value
    ):
        raise FinalSettlementInvalidError(f"{name} must be trimmed text of 1 to {limit}")
    return value


def _cents(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_USD_CENTS:
        raise FinalSettlementInvalidError(
            "amount_usd_cents must be a positive whole number of cents"
        )
    return value


class SettlementTargetKind(StrEnum):
    INVOICE_LINE = "INVOICE_LINE"
    LATE_PAYMENT_CHARGE = "LATE_PAYMENT_CHARGE"


class SettlementDepositStepKind(StrEnum):
    """The DL-032 steps that apply a Deposit (steps 3, 4 and 5)."""

    PET_DEPOSIT_PET_DAMAGE = "PET_DEPOSIT_PET_DAMAGE"
    SECURITY_DEPOSIT = "SECURITY_DEPOSIT"
    PET_DEPOSIT_REMAINDER = "PET_DEPOSIT_REMAINDER"


class PetRemainderBasis(StrEnum):
    CUSTOMER_CHOICE = "CUSTOMER_CHOICE"
    STAFF_REASON = "STAFF_REASON"


@dataclass(frozen=True, slots=True)
class SettlementCreditStep:
    """DL-032 step 2: a Customer's Credit pays one of that Customer's obligations.

    On an Invoice with Rent or Service lines, Credit follows the Rent-first proposal order unless
    ``customer_designation`` records, as text, who designated the line, the date and how
    (BR-CREDIT-006; owner answer 1 to Q-2026-10-05-29).
    """

    customer_credit_id: UUID
    target_kind: SettlementTargetKind
    target_id: UUID
    amount_usd_cents: int
    customer_designation: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.customer_credit_id, "customer_credit_id")
        if not isinstance(self.target_kind, SettlementTargetKind):
            raise FinalSettlementInvalidError("target_kind is invalid")
        _uuid(self.target_id, "target_id")
        _cents(self.amount_usd_cents)
        if self.customer_designation is not None:
            _text(self.customer_designation, "customer_designation", 500)

    def payload(self) -> dict[str, object]:
        return {
            "kind": "CUSTOMER_CREDIT",
            "customer_credit_id": str(self.customer_credit_id),
            "target_kind": self.target_kind.value,
            "target_id": str(self.target_id),
            "amount_usd_cents": self.amount_usd_cents,
            "customer_designation": self.customer_designation,
        }


@dataclass(frozen=True, slots=True)
class SettlementDepositStep:
    """DL-032 steps 3 to 5: a Deposit pays one obligation of the Lease."""

    kind: SettlementDepositStepKind
    deposit_id: UUID
    target_kind: SettlementTargetKind
    target_id: UUID
    amount_usd_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SettlementDepositStepKind):
            raise FinalSettlementInvalidError("Deposit step kind is invalid")
        _uuid(self.deposit_id, "deposit_id")
        if not isinstance(self.target_kind, SettlementTargetKind):
            raise FinalSettlementInvalidError("target_kind is invalid")
        _uuid(self.target_id, "target_id")
        _cents(self.amount_usd_cents)

    def payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "deposit_id": str(self.deposit_id),
            "target_kind": self.target_kind.value,
            "target_id": str(self.target_id),
            "amount_usd_cents": self.amount_usd_cents,
        }


@dataclass(frozen=True, slots=True)
class SettlementDepositRefund:
    """DL-032 step 7: the Refund of what remains in one Deposit (BR-REFUND-014, BR-REFUND-015).

    The recipient is the Primary Tenant, or another signed Signer with the written agreement of
    all Signers recorded as text.
    """

    deposit_id: UUID
    amount_usd_cents: int
    refund_method_id: UUID
    reference_note: str
    recipient_customer_id: UUID
    signer_agreement: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.deposit_id, "deposit_id")
        _cents(self.amount_usd_cents)
        _uuid(self.refund_method_id, "refund_method_id")
        _text(self.reference_note, "reference_note", 500)
        _uuid(self.recipient_customer_id, "recipient_customer_id")
        if self.signer_agreement is not None:
            _text(self.signer_agreement, "signer_agreement", 2000)

    def payload(self) -> dict[str, object]:
        return {
            "kind": "DEPOSIT_REFUNDS",
            "deposit_id": str(self.deposit_id),
            "amount_usd_cents": self.amount_usd_cents,
            "refund_method_id": str(self.refund_method_id),
            "reference_note": self.reference_note,
            "recipient_customer_id": str(self.recipient_customer_id),
            "signer_agreement": self.signer_agreement,
        }


@dataclass(frozen=True, slots=True)
class PetRemainderDecision:
    """Why the remaining Pet Deposit pays other debt (DL-032 step 5).

    CUSTOMER_CHOICE records the Customer's choice as text (who, the date and how) with the staff
    reason; STAFF_REASON records only the staff reason when the Customer will not pay, which the
    database refuses at the three BR-DEP-027 terminations.
    """

    basis: PetRemainderBasis
    staff_reason: str
    customer_choice: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.basis, PetRemainderBasis):
            raise FinalSettlementInvalidError("Pet Deposit remainder basis is invalid")
        _text(self.staff_reason, "staff_reason", 1000)
        if self.basis is PetRemainderBasis.CUSTOMER_CHOICE:
            _text(self.customer_choice, "customer_choice", 2000)
        elif self.customer_choice is not None:
            raise FinalSettlementInvalidError("A staff decision records no Customer choice")

    def payload(self) -> dict[str, object]:
        return {
            "basis": self.basis.value,
            "staff_reason": self.staff_reason,
            "customer_choice": self.customer_choice,
        }


SettlementStep = SettlementCreditStep | SettlementDepositStep | SettlementDepositRefund


@dataclass(frozen=True, slots=True)
class RecordFinalSettlementDraftCommand:
    """The Settlement draft: the DL-032 steps in order; the database checks every rule."""

    idempotency_key: UUID
    settlement_id: UUID
    steps: tuple[SettlementStep, ...]
    reason: str
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        if not isinstance(self.steps, tuple) or len(self.steps) > MAX_SETTLEMENT_STEPS:
            raise FinalSettlementInvalidError(
                f"steps must be a tuple of at most {MAX_SETTLEMENT_STEPS} steps"
            )
        for step in self.steps:
            if not isinstance(
                step, (SettlementCreditStep, SettlementDepositStep, SettlementDepositRefund)
            ):
                raise FinalSettlementInvalidError("Settlement step is invalid")
        _text(self.reason, "reason", 1000)
        if self.pet_remainder is not None and not isinstance(
            self.pet_remainder, PetRemainderDecision
        ):
            raise FinalSettlementInvalidError("Pet Deposit remainder decision is invalid")

    def plan(self) -> dict[str, object]:
        return {
            "steps": [step.payload() for step in self.steps],
            "pet_remainder": None if self.pet_remainder is None else self.pet_remainder.payload(),
        }


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

    def _call(
        self,
        sql: str,
        parameters: tuple[object, ...],
        *,
        read_only: bool | None = None,
        stale: frozenset[str] = frozenset(),
    ) -> dict[str, object]:
        try:
            with psycopg.connect(
                self.financial_database_url, connect_timeout=DEPOSIT_CONNECT_TIMEOUT_SECONDS
            ) as connection:
                # A read runs in a read-only transaction, so any write fails (sub-slice 8b); None
                # keeps the server default for commands.
                connection.read_only = read_only
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
            if exc.sqlstate in stale:
                raise FinalSettlementStaleDraftError(
                    "Final Settlement draft is stale; prepare it again"
                ) from exc
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
            if exc.sqlstate == "P5205":
                raise FinalSettlementKeyReused("Final Settlement draft key was reused") from exc
            # 55000: business state (for example the Lease is not TERMINATED, a blocking issue or
            # a plan the current Settlement does not allow); P5S01: a closed Settlement (8e-1); a
            # refusal caused by business state reaches the user as a conflict (owner answer for
            # slice 11c). A lock that cannot be taken or a detected deadlock is a conflict too.
            if exc.sqlstate in {"55000", "55P03", "40001", "40P01", "23505", "P5S01"}:
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

    def record_draft(
        self,
        property_id: UUID,
        command: RecordFinalSettlementDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record the Settlement draft; it has no financial effect until confirmed (8e)."""
        actor_id = self._authorize(actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY)
        if not isinstance(command, RecordFinalSettlementDraftCommand):
            raise FinalSettlementInvalidError("Final Settlement draft command is invalid")
        request = RecordFinalSettlementDraftCommand(
            command.idempotency_key,
            command.settlement_id,
            command.steps,
            command.reason,
            command.pet_remainder,
        )
        return self._call(
            "SELECT app.record_final_settlement_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                final_settlement_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.plan()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending Settlement draft and close its Settlement (financial.approve only).

        An inactive or missing approver is an authorization error; a draft whose sources changed
        is stale and stays pending; an exact repeat by the same approver replays the stored result.
        """
        actor_id = self._authorize(actor, property_id, FINANCIAL_APPROVE_CAPABILITY)
        _uuid(draft_id, "draft_id")
        return self._call(
            "SELECT app.confirm_final_settlement_draft(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=CONFIRM_STALE_STATES,
        )


@dataclass(frozen=True, slots=True)
class FinalSettlementReadService:
    """Reads under the runtime role (``database_url``); nothing here writes."""

    database_url: str

    def preview(
        self, property_id: UUID, settlement_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """The Settlement's obligations, Credit, Deposits, DL-032 steps and blocking issues."""
        _uuid(property_id, "property_id")
        if not any(
            is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))
            for capability in (FINAL_SETTLEMENTS_PREPARE_CAPABILITY, FINANCIAL_APPROVE_CAPABILITY)
        ):
            raise FinalSettlementAuthorizationError("Final Settlement preview is not authorized")
        actor_id = _actor_identity(actor)
        _uuid(settlement_id, "settlement_id")
        # The reader's draft capabilities on the Property: a pending draft's identity is shown
        # only to a financial.approve holder or a holder of its prepare capability.
        capabilities = [
            capability
            for capability in sorted(PREPARE_CAPABILITIES | {FINANCIAL_APPROVE_CAPABILITY})
            if is_authorized(actor, AuthorizationRequirement(capability, str(property_id)))
        ]
        # The same connection settings and error mapping as the commands, on the runtime role.
        return FinalSettlementService(self.database_url)._call(
            "SELECT app.final_settlement_preview(%s,%s,%s,%s)",
            (property_id, actor_id, settlement_id, capabilities),
            read_only=True,
        )
