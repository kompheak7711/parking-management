"""Post-settlement corrections (BR-SETTLE-013; V1-056 slice 10).

A closed Final Settlement is never reopened. A later fix is a new correction linked to it, with a
reason: Staff holding ``final_settlements.prepare`` record a ``SETTLEMENT_CORRECTION`` draft, and
only a ``financial.approve`` holder confirms it (BR-AUTH-010). The confirmation writes new records
linked to the Settlement (DB-SETTLE-003, DB-SETTLE-005); there is no time limit.

Sub-slice 10b: the ``EXTRA_CHARGE`` variant, a missed amount billed after closure as a one-time
Miscellaneous or Damage charge (BR-INV-044) on a new issued Invoice with the Lease. It goes to the
Customer of the corrected Invoice when the draft names one, otherwise to the Primary Tenant
(BR-SETTLE-016; owner answer 6 to Q-2026-10-06-36). The HTTP routes come in slice 11e.

Sub-slice 10c-1a: the ``CHARGE_REDUCTION`` variant, a wrong charge that is still unpaid removed by
a credit Adjustment of its Invoice line (owner answer 1 to Q-2026-10-06-36). The amount is at most
the line's unpaid rest; releasing paid value is a ``REFUND`` correction.

Sub-slice 10c-1b: the ``REFUND`` variant, a wrong charge that was paid. A credit Adjustment of the
line releases the paid part as a credit Adjustment always does (newest Payment allocation or Credit
application first; released Payment value becomes Customer Credit of the Invoice Customer,
BR-CREDIT-014), and one Credit Refund per released source pays it to that Credit's Customer, each
with the draft's Refund method and reference note (BR-REFUND-014; owner answers to
Q-2026-10-07-39).

Sub-slice 10c-2a-5: the ``PET_DAMAGE_RECLASSIFICATION`` variant, a Damage line whose pet
classification is wrong after closure, in both directions (owner answer to Q-2026-10-07-45). The
charge amount stays the same and the closed inspection is not changed: the confirmation records
the corrected classification, reverses the line's Deposit applications where it changes which
Deposit should pay, and runs the shared DL-032 step after closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    MAX_SETTLEMENT_STEPS,
    MAX_USD_CENTS,
    FinalSettlementInvalidError,
    FinalSettlementService,
    PetRemainderDecision,
    SettlementCreditStep,
    SettlementDepositRefund,
    SettlementDepositStep,
    SettlementStep,
)
from property_rental.financial_draft import (
    FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
    FINANCIAL_APPROVE_CAPABILITY,
)
from property_rental.identity import AuthenticatedActor

# Draft keys keep the command-key scope (Property, preparer and key), as other drafts do.
SETTLEMENT_CORRECTION_DRAFT_NAMESPACE: Final = UUID("0b6f6d2e-4c1a-4f0e-9a57-3d8c2e91b7a4")
# The confirm reports a draft whose sources changed as stale (P5S02); the draft stays pending. Two
# confirms on one Lease are serialized by the database locks, so a finding billed by the other is
# seen as a changed source; any other refusal keeps the Final Settlement error mapping.
EXTRA_CHARGE_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A charge reduction whose line changed since the draft (a Payment, Credit or Adjustment) is stale.
CHARGE_REDUCTION_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A Refund correction whose line or paying sources changed since the draft is stale.
REFUND_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A pet classification correction whose line, Deposit applications or Deposits changed is stale.
PET_CLASSIFICATION_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})


def settlement_correction_draft_id(
    property_id: UUID, actor_id: UUID, idempotency_key: UUID
) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        SETTLEMENT_CORRECTION_DRAFT_NAMESPACE,
        f"settlement-correction-draft:{property_id}:{actor_id}:{idempotency_key}",
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


class ExtraChargeCategory(StrEnum):
    MISCELLANEOUS_CHARGES = "MISCELLANEOUS_CHARGES"
    DAMAGE_CHARGES = "DAMAGE_CHARGES"


@dataclass(frozen=True, slots=True)
class RecordExtraChargeCorrectionCommand:
    """An extra charge after closure; the database checks every rule against current state.

    A Damage charge names the inspection finding it bills (BR-INV-044); a Miscellaneous charge
    names none. ``corrects_invoice_id`` names the Settlement obligation the charge corrects,
    whose Customer is charged. The Due Date override and its reason come together. The reason is
    at most 500 characters, because the one-time charge record keeps it.
    """

    idempotency_key: UUID
    settlement_id: UUID
    category: ExtraChargeCategory
    description: str
    amount_usd_cents: int
    evidence_reference: str
    reason: str
    inspection_damage_finding_id: UUID | None = None
    corrects_invoice_id: UUID | None = None
    due_date: date | None = None
    due_date_reason: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        if not isinstance(self.category, ExtraChargeCategory):
            raise FinalSettlementInvalidError("Extra charge category is invalid")
        _text(self.description, "description", 1000)
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= MAX_USD_CENTS
        ):
            raise FinalSettlementInvalidError(
                "amount_usd_cents must be a positive whole number of cents"
            )
        _text(self.evidence_reference, "evidence_reference", 500)
        _text(self.reason, "reason", 500)
        damage = self.category is ExtraChargeCategory.DAMAGE_CHARGES
        if damage != (self.inspection_damage_finding_id is not None):
            raise FinalSettlementInvalidError(
                "A Damage charge names one inspection finding; a Miscellaneous charge names none"
            )
        if self.inspection_damage_finding_id is not None:
            _uuid(self.inspection_damage_finding_id, "inspection_damage_finding_id")
        if self.corrects_invoice_id is not None:
            _uuid(self.corrects_invoice_id, "corrects_invoice_id")
        if (self.due_date is None) != (self.due_date_reason is None):
            raise FinalSettlementInvalidError("Due Date override and its reason come together")
        if self.due_date is not None and (
            not isinstance(self.due_date, date) or isinstance(self.due_date, datetime)
        ):
            raise FinalSettlementInvalidError("due_date must be a calendar date")
        if self.due_date_reason is not None:
            _text(self.due_date_reason, "due_date_reason", 500)

    def charge(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "description": self.description,
            "amount_usd_cents": self.amount_usd_cents,
            "evidence_reference": self.evidence_reference,
            "inspection_damage_finding_id": None
            if self.inspection_damage_finding_id is None
            else str(self.inspection_damage_finding_id),
            "corrects_invoice_id": None
            if self.corrects_invoice_id is None
            else str(self.corrects_invoice_id),
            "due_date": None if self.due_date is None else self.due_date.isoformat(),
            "due_date_reason": self.due_date_reason,
        }


@dataclass(frozen=True, slots=True)
class RecordChargeReductionCorrectionCommand:
    """A wrong charge still unpaid after closure; the database checks it against current state.

    The credit Adjustment reduces one line of an issued Invoice of the Settlement's Lease by at most
    the line's unpaid rest. The reason is at most 500 characters, because the Adjustment keeps it.
    """

    idempotency_key: UUID
    settlement_id: UUID
    invoice_id: UUID
    invoice_line_id: UUID
    amount_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.invoice_id, "invoice_id")
        _uuid(self.invoice_line_id, "invoice_line_id")
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= MAX_USD_CENTS
        ):
            raise FinalSettlementInvalidError(
                "amount_usd_cents must be a positive whole number of cents"
            )
        _text(self.reason, "reason", 500)

    def reduction(self) -> dict[str, object]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_line_id": str(self.invoice_line_id),
            "amount_usd_cents": self.amount_usd_cents,
        }


@dataclass(frozen=True, slots=True)
class RecordRefundCorrectionCommand:
    """A wrong charge that was paid; the database checks it against current state.

    The credit Adjustment removes ``amount_usd_cents`` from one line of an issued Invoice of the
    Settlement's Lease, at most the line's charge, and must release paid value. Every Refund of
    the correction records the Refund method and the reference note (BR-REFUND-014). The reason is
    at most 500 characters, because the Adjustment keeps it.

    ``steps`` and ``pet_remainder`` are the DL-032 plan for the released value, in the Final
    Settlement plan format (V1-056 sub-slice 10c-2a-3): released Credit first pays its own
    Customer's open debt on the Lease, released Deposit value then pays the Lease's open debt in
    the DL-032 order, and only the rest is refunded; staff choose every step. Every Deposit Refund
    step uses this command's Refund method and reference note.
    """

    idempotency_key: UUID
    settlement_id: UUID
    invoice_id: UUID
    invoice_line_id: UUID
    amount_usd_cents: int
    refund_method_id: UUID
    reference_note: str
    reason: str
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.invoice_id, "invoice_id")
        _uuid(self.invoice_line_id, "invoice_line_id")
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= MAX_USD_CENTS
        ):
            raise FinalSettlementInvalidError(
                "amount_usd_cents must be a positive whole number of cents"
            )
        _uuid(self.refund_method_id, "refund_method_id")
        _text(self.reference_note, "reference_note", 500)
        _text(self.reason, "reason", 500)
        if not isinstance(self.steps, tuple) or len(self.steps) > MAX_SETTLEMENT_STEPS:
            raise FinalSettlementInvalidError(
                f"steps must be a tuple of at most {MAX_SETTLEMENT_STEPS} steps"
            )
        for step in self.steps:
            if not isinstance(
                step, (SettlementCreditStep, SettlementDepositStep, SettlementDepositRefund)
            ):
                raise FinalSettlementInvalidError("Settlement step is invalid")
        if self.pet_remainder is not None and not isinstance(
            self.pet_remainder, PetRemainderDecision
        ):
            raise FinalSettlementInvalidError("Pet Deposit remainder decision is invalid")

    def plan(self) -> dict[str, object]:
        return {
            "steps": [step.payload() for step in self.steps],
            "pet_remainder": None if self.pet_remainder is None else self.pet_remainder.payload(),
        }

    def refund(self) -> dict[str, object]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_line_id": str(self.invoice_line_id),
            "amount_usd_cents": self.amount_usd_cents,
            "refund_method_id": str(self.refund_method_id),
            "reference_note": self.reference_note,
        }


@dataclass(frozen=True, slots=True)
class RecordPetClassificationCorrectionCommand:
    """A Damage line whose pet classification is wrong; the database checks it against current
    state (V1-056 sub-slice 10c-2a-5).

    ``pet_related`` is the corrected classification of one Damage line billed from an inspection
    finding on an issued Invoice of the Settlement's Lease; it must differ from the current one.
    The evidence reference and the reason are at most 500 characters, because the classification
    record keeps them. ``steps`` and ``pet_remainder`` are the DL-032 plan for the Deposit value
    the reversals give back, in the Final Settlement plan format; staff choose every step.
    """

    idempotency_key: UUID
    settlement_id: UUID
    invoice_id: UUID
    invoice_line_id: UUID
    pet_related: bool
    evidence_reference: str
    reason: str
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.invoice_id, "invoice_id")
        _uuid(self.invoice_line_id, "invoice_line_id")
        if type(self.pet_related) is not bool:
            raise FinalSettlementInvalidError("pet_related must be true or false")
        _text(self.evidence_reference, "evidence_reference", 500)
        _text(self.reason, "reason", 500)
        if not isinstance(self.steps, tuple) or len(self.steps) > MAX_SETTLEMENT_STEPS:
            raise FinalSettlementInvalidError(
                f"steps must be a tuple of at most {MAX_SETTLEMENT_STEPS} steps"
            )
        for step in self.steps:
            if not isinstance(
                step, (SettlementCreditStep, SettlementDepositStep, SettlementDepositRefund)
            ):
                raise FinalSettlementInvalidError("Settlement step is invalid")
        if self.pet_remainder is not None and not isinstance(
            self.pet_remainder, PetRemainderDecision
        ):
            raise FinalSettlementInvalidError("Pet Deposit remainder decision is invalid")

    def classification(self) -> dict[str, object]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_line_id": str(self.invoice_line_id),
            "pet_related": self.pet_related,
            "evidence_reference": self.evidence_reference,
            "plan": {
                "steps": [step.payload() for step in self.steps],
                "pet_remainder": None
                if self.pet_remainder is None
                else self.pet_remainder.payload(),
            },
        }


@dataclass(frozen=True, slots=True)
class SettlementCorrectionService:
    """Commands under the financial role; capabilities are checked before any connection."""

    financial_database_url: str

    def record_extra_charge(
        self,
        property_id: UUID,
        command: RecordExtraChargeCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record an extra charge correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordExtraChargeCorrectionCommand):
            raise FinalSettlementInvalidError("Extra charge correction command is invalid")
        request = RecordExtraChargeCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.category,
            command.description,
            command.amount_usd_cents,
            command.evidence_reference,
            command.reason,
            command.inspection_damage_finding_id,
            command.corrects_invoice_id,
            command.due_date,
            command.due_date_reason,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_extra_charge_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.charge()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_extra_charge(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending extra charge correction (financial.approve only).

        A draft whose sources changed is stale and stays pending; an exact repeat by the same
        approver writes nothing and returns the result again, rebuilt from the stored records.
        The decision's transaction id is never returned.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_extra_charge(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=EXTRA_CHARGE_CONFIRM_STALE_STATES,
        )

    def record_charge_reduction(
        self,
        property_id: UUID,
        command: RecordChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a charge reduction correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordChargeReductionCorrectionCommand):
            raise FinalSettlementInvalidError("Charge reduction correction command is invalid")
        request = RecordChargeReductionCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.invoice_id,
            command.invoice_line_id,
            command.amount_usd_cents,
            command.reason,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_charge_reduction_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.reduction()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_charge_reduction(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending charge reduction correction (financial.approve only).

        A draft whose line changed since it was recorded is stale and stays pending; an exact
        repeat by the same approver writes nothing and returns the result again, rebuilt from the
        stored records (the Invoice as it is now). The result never returns the decision's
        transaction id; the general draft reads still do until slice 11e.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_charge_reduction(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=CHARGE_REDUCTION_CONFIRM_STALE_STATES,
        )

    def record_refund(
        self,
        property_id: UUID,
        command: RecordRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a Refund correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordRefundCorrectionCommand):
            raise FinalSettlementInvalidError("Refund correction command is invalid")
        request = RecordRefundCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.invoice_id,
            command.invoice_line_id,
            command.amount_usd_cents,
            command.refund_method_id,
            command.reference_note,
            command.reason,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_refund_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb({**request.refund(), "plan": request.plan()}),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_refund(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending Refund correction (financial.approve only).

        A draft whose line or paying sources changed since it was recorded is stale and stays
        pending; an inactive Refund method is a conflict; an exact repeat by the same approver
        writes nothing and returns the result again, rebuilt from the stored records. The result
        never returns the decision's transaction id.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_refund(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=REFUND_CONFIRM_STALE_STATES,
        )

    def record_pet_classification(
        self,
        property_id: UUID,
        command: RecordPetClassificationCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a pet classification correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordPetClassificationCorrectionCommand):
            raise FinalSettlementInvalidError("Pet classification correction command is invalid")
        request = RecordPetClassificationCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.invoice_id,
            command.invoice_line_id,
            command.pet_related,
            command.evidence_reference,
            command.reason,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_pet_classification_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.classification()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_pet_classification(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending pet classification correction (financial.approve only).

        A draft whose line, Deposit applications or Deposits changed since it was recorded is
        stale and stays pending; an exact repeat by the same approver writes nothing and returns
        the result again. The result never returns the decision's transaction id.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_pet_classification(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=PET_CLASSIFICATION_CONFIRM_STALE_STATES,
        )
