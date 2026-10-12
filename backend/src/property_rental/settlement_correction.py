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

Sub-slice 10c-2b-1: the ``REFUND_RETURN`` variant, a correction's Credit Refund whose money came
back (owner answers to Q-2026-10-08-55). The confirmation records the verified return, so the value
goes back to the Credit; that Credit first pays its own Customer's open debt on the Lease through
the shared DL-032 step, and only the rest is refunded to the same Customer when the draft asks for
a new Refund, or stays as that Customer's Credit. Such a Refund is never corrected with one call.

Sub-slice 10c-2b-3: the ``HELD_VALUE_REFUND`` variant, a later correction that refunds value an
earlier return-only ``REFUND_RETURN`` correction left (a Credit, or a Deposit on the DL-032 path),
after the shared DL-032 step has let that value pay the open debt first.

Sub-slice 10c-3a: the ``CHARGE_REDUCTION`` variant also reduces an unpaid Late-payment Charge of
the Settlement's Lease within its unpaid rest, through a linked Late-payment Charge correction
(owner answer to Q-2026-10-07-38).

Sub-slice 10c-3b-1: the ``REFUND`` variant also takes a Late-payment Charge that Payments or Credits
paid (owner answer to Q-2026-10-07-38 (b)). A linked Late-payment Charge correction removes the
amount; the paid part is released newest first; released Payment value becomes Customer Credit of
the Charge's Customer (BR-CREDIT-014), which first pays that Customer's open debt on the Lease
through the shared DL-032 step, and only the rest is refunded.

Sub-slice 10e-2: the ``DEPOSIT_RECEIPT_CORRECTION`` variant, a Lease Deposit receipt that is wrong
while its Payment is real (owner answers to Q-2026-10-08-56, Q-2026-10-11-83 and Q-2026-10-11-86).
The confirmation recovers each Refund paid from the Deposit by a charge to the person who received
it, reverses the Deposit's applications and the whole receipt; the freed amount stays unallocated
with the Payment until the payer authorizes Credit (BR-CREDIT-002).

Sub-slice 10e-2b: the same correction may then write the right receipt of the Payment's freed
value, into the right Deposit or for the right amount (owner answers to Q-2026-10-12-87), and its
shared DL-032 step applies that money to the Lease's open debt and refunds the rest.

Sub-slice 10e-3: the ``RETURN_REVERSAL`` variant, the reversal of a return that an earlier
``REFUND_RETURN`` correction recorded by mistake (owner answer to Q-2026-10-08-57). The
confirmation undoes the uses of the returned Refund's own Credit or Deposit by that correction and
the held-value corrections naming it, recovers each of their Refunds from that source by a charge
to the person who received it, then reverses the return.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
# A returned-Refund correction whose Refund, its corrections or its Credit changed is stale.
REFUND_RETURN_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A held-value Refund correction whose earlier correction, Credit or Deposit changed is stale.
HELD_VALUE_REFUND_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A forfeiture reversal correction whose forfeiture, Deposit or Settlement sources changed is stale.
FORFEITURE_REVERSAL_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A returned-Payment correction whose Payment, Credits, Deposits or their records changed is stale.
RETURNED_PAYMENT_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A Deposit receipt correction whose receipt, Deposit, its records or Refunds changed is stale.
DEPOSIT_RECEIPT_CORRECTION_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# A return reversal whose earlier correction, source or records to undo changed is stale.
RETURN_REVERSAL_CONFIRM_STALE_STATES: Final = frozenset({"P5S02"})
# The staff's choice for a right receipt into a Deposit whose forfeiture was reversed (10e-2c).
RECEIPT_OUTCOMES: Final = frozenset({"DL_032", "FORFEIT"})


def settlement_correction_draft_id(
    property_id: UUID, actor_id: UUID, idempotency_key: UUID
) -> UUID:
    """Stable draft id for one preparer's command key in one Property."""
    return uuid5(
        SETTLEMENT_CORRECTION_DRAFT_NAMESPACE,
        f"settlement-correction-draft:{property_id}:{actor_id}:{idempotency_key}",
    )


def deposit_receipt_recovery_line_id(draft_id: UUID, refund_id: UUID) -> UUID:
    """The placeholder line id under which a Deposit receipt correction's DL-032 plan names the
    recovery charge of one Refund on the Settlement's Lease (sub-slice 10e-2b-2). The draft shows
    each placeholder's Customer and exact amount; the confirm checks that the real charge equals
    it and the steps on it pay the real charge line."""
    digest = hashlib.md5(
        f"deposit-receipt-recovery:{draft_id}:{refund_id}".encode(), usedforsecurity=False
    )
    return UUID(digest.hexdigest())


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
class RecordLateChargeReductionCorrectionCommand:
    """A wrong Late-payment Charge still unpaid after closure (V1-056 sub-slice 10c-3a); the
    database checks it against current state.

    The Late-payment Charge correction reduces a Charge of an Invoice of the Settlement's Lease by
    at most its unpaid rest. The reason is at most 500 characters, because the Charge correction
    keeps it.
    """

    idempotency_key: UUID
    settlement_id: UUID
    late_payment_charge_id: UUID
    amount_usd_cents: int
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.late_payment_charge_id, "late_payment_charge_id")
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
            "late_payment_charge_id": str(self.late_payment_charge_id),
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
class RecordLateChargeRefundCorrectionCommand:
    """A wrong Late-payment Charge that was paid (V1-056 sub-slice 10c-3b-1); the database checks
    it against current state.

    The Late-payment Charge correction removes ``amount_usd_cents`` from a Charge of an Invoice of
    the Settlement's Lease, at most its current obligation, and must release paid value. Every
    Refund of the correction records the Refund method and the reference note (BR-REFUND-014). The
    reason is at most 500 characters, because the Charge correction keeps it. ``steps`` and
    ``pet_remainder`` are the DL-032 plan for the released value, as for an Invoice line.
    """

    idempotency_key: UUID
    settlement_id: UUID
    late_payment_charge_id: UUID
    amount_usd_cents: int
    refund_method_id: UUID
    reference_note: str
    reason: str
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.late_payment_charge_id, "late_payment_charge_id")
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
            "late_payment_charge_id": str(self.late_payment_charge_id),
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
class RecordRefundReturnCorrectionCommand:
    """A correction's Credit Refund whose money came back; the database checks it against current
    state (V1-056 sub-slice 10c-2b-1).

    ``returned_amount_usd_cents`` is at most the Refund's net value; ``returned_at`` is a
    timezone-aware instant not before the Refund and not in the future. The return method
    reference and the evidence reference are what the verified return records. A new Refund is
    paid only when ``new_refund_method_id`` and ``new_refund_reference_note`` are both given
    (BR-REFUND-014); it goes to the same Customer. ``steps`` and ``pet_remainder`` are the DL-032
    plan, in the Final Settlement plan format: the returned Credit first pays its own Customer's
    open debt on the Lease (owner answer 1 to Q-2026-10-08-55); staff choose every step.
    """

    idempotency_key: UUID
    settlement_id: UUID
    refund_id: UUID
    returned_amount_usd_cents: int
    returned_at: datetime
    return_method_reference: str
    evidence_reference: str
    reason: str
    new_refund_method_id: UUID | None = None
    new_refund_reference_note: str | None = None
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.refund_id, "refund_id")
        if (
            type(self.returned_amount_usd_cents) is not int
            or not 1 <= self.returned_amount_usd_cents <= MAX_USD_CENTS
        ):
            raise FinalSettlementInvalidError(
                "returned_amount_usd_cents must be a positive whole number of cents"
            )
        if not isinstance(self.returned_at, datetime):
            raise FinalSettlementInvalidError("returned_at must be a timezone-aware instant")
        try:
            offset = self.returned_at.utcoffset()
            if offset is not None:
                # An instant at the edge of the date range has no UTC form, and a broken tzinfo
                # may raise; both are invalid input, as refund.py _instant (sub-slice 10c-2b-2b).
                self.returned_at.astimezone(UTC)
        except (ValueError, TypeError, OverflowError) as exc:
            raise FinalSettlementInvalidError(
                "returned_at must be a timezone-aware instant"
            ) from exc
        if offset is None:
            raise FinalSettlementInvalidError("returned_at must be a timezone-aware instant")
        _text(self.return_method_reference, "return_method_reference", 500)
        _text(self.evidence_reference, "evidence_reference", 500)
        _text(self.reason, "reason", 500)
        if (self.new_refund_method_id is None) != (self.new_refund_reference_note is None):
            raise FinalSettlementInvalidError(
                "A new Refund needs both its Refund method and its reference note"
            )
        if self.new_refund_method_id is not None:
            _uuid(self.new_refund_method_id, "new_refund_method_id")
            _text(self.new_refund_reference_note, "new_refund_reference_note", 500)
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

    def refund_return(self) -> dict[str, object]:
        return {
            "refund_id": str(self.refund_id),
            "returned_amount_usd_cents": self.returned_amount_usd_cents,
            # In UTC: PostgreSQL refuses some offsets that Python accepts (review round 1).
            "returned_at": self.returned_at.astimezone(UTC).isoformat(),
            "return_method_reference": self.return_method_reference,
            "evidence_reference": self.evidence_reference,
            "new_refund": None
            if self.new_refund_method_id is None
            else {
                "refund_method_id": str(self.new_refund_method_id),
                "reference_note": self.new_refund_reference_note,
            },
            "plan": {
                "steps": [step.payload() for step in self.steps],
                "pet_remainder": None
                if self.pet_remainder is None
                else self.pet_remainder.payload(),
            },
        }


@dataclass(frozen=True, slots=True)
class RecordHeldValueRefundCorrectionCommand:
    """A later correction that refunds value an earlier return-only ``REFUND_RETURN`` correction of
    the same Settlement left (V1-056 sub-slice 10c-2b-3); the database checks it against current
    state.

    ``held_from_correction_id`` names that earlier correction. The new Refund's method and
    reference note are required (BR-REFUND-014). ``steps`` and ``pet_remainder`` are the DL-032
    plan: a held Credit first pays its own Customer's open debt on the Lease, held Deposit money
    first pays the Lease's open debt in the DL-032 order; staff choose every step.
    """

    idempotency_key: UUID
    settlement_id: UUID
    held_from_correction_id: UUID
    reason: str
    new_refund_method_id: UUID
    new_refund_reference_note: str
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.held_from_correction_id, "held_from_correction_id")
        _text(self.reason, "reason", 500)
        _uuid(self.new_refund_method_id, "new_refund_method_id")
        _text(self.new_refund_reference_note, "new_refund_reference_note", 500)
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

    def held_value(self) -> dict[str, object]:
        return {
            "held_from_settlement_correction_id": str(self.held_from_correction_id),
            "new_refund": {
                "refund_method_id": str(self.new_refund_method_id),
                "reference_note": self.new_refund_reference_note,
            },
            "plan": {
                "steps": [step.payload() for step in self.steps],
                "pet_remainder": None
                if self.pet_remainder is None
                else self.pet_remainder.payload(),
            },
        }


@dataclass(frozen=True, slots=True)
class RecordForfeitureReversalCorrectionCommand:
    """The reversal of a confirmed Lease Deposit forfeiture after closure (V1-056 sub-slice 10d);
    the database checks it against current state.

    ``deposit_disposition_id`` names the forfeiture and ``evidence_reference`` the evidence for
    its reversal. The Refund method and reference note of the correction are required
    (BR-REFUND-014). ``steps`` and ``pet_remainder`` are the DL-032 plan: each Customer's Credit
    first pays that Customer's own open debt, the Deposit pays the Lease's open debt in the DL-032
    order and only the rest is refunded; staff choose every step.
    """

    idempotency_key: UUID
    settlement_id: UUID
    deposit_disposition_id: UUID
    reason: str
    evidence_reference: str
    refund_method_id: UUID
    reference_note: str
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.deposit_disposition_id, "deposit_disposition_id")
        _text(self.reason, "reason", 500)
        _text(self.evidence_reference, "evidence_reference", 500)
        _uuid(self.refund_method_id, "refund_method_id")
        _text(self.reference_note, "reference_note", 500)
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

    def forfeiture_reversal(self) -> dict[str, object]:
        return {
            "deposit_disposition_id": str(self.deposit_disposition_id),
            "evidence_reference": self.evidence_reference,
            "refund_method_id": str(self.refund_method_id),
            "reference_note": self.reference_note,
            "plan": {
                "steps": [step.payload() for step in self.steps],
                "pet_remainder": None
                if self.pet_remainder is None
                else self.pet_remainder.payload(),
            },
        }


@dataclass(frozen=True, slots=True)
class RecordReturnedPaymentCorrectionCommand:
    """A returned (bounced) Payment whose records a closed Final Settlement relied on (V1-056
    sub-slice 10e-1b), or that names that Settlement's Lease, or whose money or a Refund of whose
    value is on that Lease after closure (sub-slice 10e-4); the database checks it against current
    state.

    ``payment_id`` names the Payment and ``evidence_reference`` the bank's return notice. The
    confirmation reverses the Payment's Credit applications, Credits, allocations, the forfeitures,
    Deposit applications and receipts of the Deposits it funded, and the Payment itself, each
    linked to the correction; there is no DL-032 plan.
    """

    idempotency_key: UUID
    settlement_id: UUID
    payment_id: UUID
    reason: str
    evidence_reference: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.payment_id, "payment_id")
        _text(self.reason, "reason", 500)
        _text(self.evidence_reference, "evidence_reference", 500)

    def returned_payment(self) -> dict[str, object]:
        return {
            "payment_id": str(self.payment_id),
            "evidence_reference": self.evidence_reference,
        }


@dataclass(frozen=True, slots=True)
class RecordDepositReceiptCorrectionCommand:
    """A Lease Deposit receipt that is wrong while its Payment is real, after closure (V1-056
    sub-slice 10e-2); the database checks it against current state.

    ``deposit_receipt_id`` names the wrong receipt and ``evidence_reference`` the evidence. The
    confirmation recovers each Refund paid from the Deposit by a charge to the person who received
    it, reverses the Deposit's applications and the whole receipt, each linked to the correction;
    the freed amount stays unallocated with the Payment; there is no DL-032 plan.

    ``receipts`` (sub-slice 10e-2b) are the right receipts of the same Payment's freed value, one
    or two, into distinct Deposits of the Settlement's Lease, together at most the corrected
    receipt; with them ``steps`` and ``pet_remainder`` are the DL-032 plan for their money, in the
    Final Settlement plan format: the Customer's Credit first, the Deposits in the DL-032 order,
    only the rest refunded. Without receipts there is no plan. A recovery charge on the Lease is
    named in the plan by its placeholder line id (``deposit_receipt_recovery_line_id``; sub-slice
    10e-2b-2). A receipt correction must change the Deposit or the amount (owner answer 1 to
    Q-2026-10-12-89). A right receipt into a Deposit with a forfeiture ground is forfeited in the
    same correction, or for a Deposit whose forfeiture was reversed as the receipt's ``outcome``
    chooses; forfeited money is not in the plan (sub-slice 10e-2c).
    """

    idempotency_key: UUID
    settlement_id: UUID
    deposit_receipt_id: UUID
    reason: str
    evidence_reference: str
    receipts: tuple[CorrectionDepositReceipt, ...] = ()
    steps: tuple[SettlementStep, ...] = ()
    pet_remainder: PetRemainderDecision | None = None

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.deposit_receipt_id, "deposit_receipt_id")
        _text(self.reason, "reason", 500)
        _text(self.evidence_reference, "evidence_reference", 500)
        if not isinstance(self.receipts, tuple) or len(self.receipts) > 2:
            raise FinalSettlementInvalidError("receipts must be a tuple of at most 2 receipts")
        for receipt in self.receipts:
            if not isinstance(receipt, CorrectionDepositReceipt):
                raise FinalSettlementInvalidError("Deposit receipt is invalid")
        if len({receipt.deposit_id for receipt in self.receipts}) != len(self.receipts):
            raise FinalSettlementInvalidError("Each new receipt goes into a different Deposit")
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
        if not self.receipts and (self.steps or self.pet_remainder is not None):
            raise FinalSettlementInvalidError("A DL-032 plan needs a new receipt")

    def deposit_receipt_correction(self) -> dict[str, object]:
        found: dict[str, object] = {
            "deposit_receipt_id": str(self.deposit_receipt_id),
            "evidence_reference": self.evidence_reference,
        }
        if self.receipts:
            found["receipts"] = [receipt.payload() for receipt in self.receipts]
            found["plan"] = {
                "steps": [step.payload() for step in self.steps],
                "pet_remainder": (
                    None if self.pet_remainder is None else self.pet_remainder.payload()
                ),
            }
        return found


@dataclass(frozen=True, slots=True)
class CorrectionDepositReceipt:
    """A right receipt of a Deposit receipt correction (sub-slice 10e-2b): the Deposit of the
    Settlement's Lease and the amount of the corrected receipt's Payment it takes.

    ``outcome`` and ``outcome_reason`` (sub-slice 10e-2c, owner answer 2 to Q-2026-10-12-88; both
    or neither) are the staff's choice for a Deposit with a forfeiture ground whose forfeiture was
    reversed: ``DL_032`` (the plan applies the money and refunds the rest) or ``FORFEIT``
    (forfeited again on the same ground). A Deposit with a ground that was never forfeited is
    forfeited without a choice; any other Deposit takes none. The database checks both."""

    deposit_id: UUID
    amount_usd_cents: int
    outcome: str | None = None
    outcome_reason: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.deposit_id, "deposit_id")
        if (
            type(self.amount_usd_cents) is not int
            or not 1 <= self.amount_usd_cents <= MAX_USD_CENTS
        ):
            raise FinalSettlementInvalidError(
                "amount_usd_cents must be a positive whole number of cents"
            )
        if (self.outcome is None) != (self.outcome_reason is None):
            raise FinalSettlementInvalidError("outcome and outcome_reason go together")
        if self.outcome is not None:
            if self.outcome not in RECEIPT_OUTCOMES:
                raise FinalSettlementInvalidError("outcome must be DL_032 or FORFEIT")
            _text(self.outcome_reason, "outcome_reason", 500)

    def payload(self) -> dict[str, object]:
        found: dict[str, object] = {
            "deposit_id": str(self.deposit_id),
            "amount_usd_cents": self.amount_usd_cents,
        }
        if self.outcome is not None:
            found["outcome"] = self.outcome
            found["outcome_reason"] = self.outcome_reason
        return found


@dataclass(frozen=True, slots=True)
class RecordReturnReversalCorrectionCommand:
    """The reversal of a return recorded by mistake by an earlier ``REFUND_RETURN`` correction of a
    closed Final Settlement (V1-056 sub-slice 10e-3); the database checks it against current state.

    ``earlier_correction_id`` names that correction and ``evidence_reference`` the evidence that
    the return never happened. The confirmation undoes the uses of the returned Refund's own Credit
    or Deposit by that correction and the held-value corrections naming it, recovers each of their
    Refunds from that source by a charge to the person who received it, then reverses the return,
    each linked to the correction; staff enter no DL-032 step. Only the mistaken amount comes back
    (sub-slices 10e-3b and 10e-3c): when the Refunds paid out less than the returned amount, the
    newest applications are undone until the rest of it is reached, and the part of the last one
    that was not returned money is applied again to the same obligation from the same source.
    """

    idempotency_key: UUID
    settlement_id: UUID
    earlier_correction_id: UUID
    reason: str
    evidence_reference: str

    def __post_init__(self) -> None:
        _uuid(self.idempotency_key, "idempotency_key")
        _uuid(self.settlement_id, "settlement_id")
        _uuid(self.earlier_correction_id, "earlier_correction_id")
        _text(self.reason, "reason", 500)
        _text(self.evidence_reference, "evidence_reference", 500)

    def return_reversal(self) -> dict[str, object]:
        return {
            "settlement_correction_id": str(self.earlier_correction_id),
            "evidence_reference": self.evidence_reference,
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

    def record_late_charge_reduction(
        self,
        property_id: UUID,
        command: RecordLateChargeReductionCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a Late-payment Charge reduction correction draft; no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordLateChargeReductionCorrectionCommand):
            raise FinalSettlementInvalidError(
                "Late-payment Charge reduction correction command is invalid"
            )
        request = RecordLateChargeReductionCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.late_payment_charge_id,
            command.amount_usd_cents,
            command.reason,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_late_charge_reduction_draft(%s,%s,%s,%s,%s,%s,%s)",
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

    def confirm_late_charge_reduction(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending Late-payment Charge reduction correction (financial.approve only).

        A draft whose Charge changed since it was recorded is stale and stays pending; an exact
        repeat by the same approver writes nothing and returns the result again.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_late_charge_reduction(%s,%s,%s,%s)",
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
        pending; an inactive Refund method is a conflict; a Customer choice for the remaining Pet
        Deposit that the Final Settlement or another confirmed correction already used is a
        conflict and the draft stays pending (sub-slice 10c-2a-6, checked in the shared step); an
        exact repeat by the same approver writes nothing and returns the result again, rebuilt
        from the stored records. The result never returns the decision's transaction id.
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

    def record_late_charge_refund(
        self,
        property_id: UUID,
        command: RecordLateChargeRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a Late-payment Charge Refund correction draft; no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordLateChargeRefundCorrectionCommand):
            raise FinalSettlementInvalidError(
                "Late-payment Charge Refund correction command is invalid"
            )
        request = RecordLateChargeRefundCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.late_payment_charge_id,
            command.amount_usd_cents,
            command.refund_method_id,
            command.reference_note,
            command.reason,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_late_charge_refund_draft(%s,%s,%s,%s,%s,%s,%s)",
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

    def confirm_late_charge_refund(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending Late-payment Charge Refund correction (financial.approve only).

        A draft whose Charge or paying sources changed since it was recorded is stale and stays
        pending; an inactive Refund method is a conflict; an exact repeat by the same approver
        writes nothing and returns the result again, rebuilt from the stored records.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_late_charge_refund(%s,%s,%s,%s)",
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

    def record_refund_return(
        self,
        property_id: UUID,
        command: RecordRefundReturnCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a returned-Refund correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordRefundReturnCorrectionCommand):
            raise FinalSettlementInvalidError("Returned Refund correction command is invalid")
        request = RecordRefundReturnCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.refund_id,
            command.returned_amount_usd_cents,
            command.returned_at,
            command.return_method_reference,
            command.evidence_reference,
            command.reason,
            command.new_refund_method_id,
            command.new_refund_reference_note,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_refund_return_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.refund_return()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_refund_return(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending returned-Refund correction (financial.approve only).

        A draft whose Refund, its corrections or its Credit changed since it was recorded is stale
        and stays pending; an inactive Refund method or a reused Customer choice is a conflict; an
        exact repeat by the same approver writes nothing and returns the result again. The result
        never returns the decision's transaction id.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_refund_return(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=REFUND_RETURN_CONFIRM_STALE_STATES,
        )

    def record_held_value_refund(
        self,
        property_id: UUID,
        command: RecordHeldValueRefundCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a held-value Refund correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordHeldValueRefundCorrectionCommand):
            raise FinalSettlementInvalidError("Held value Refund correction command is invalid")
        request = RecordHeldValueRefundCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.held_from_correction_id,
            command.reason,
            command.new_refund_method_id,
            command.new_refund_reference_note,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_held_value_refund_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.held_value()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_held_value_refund(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending held-value Refund correction (financial.approve only).

        A draft whose earlier correction, Credit or Deposit changed since it was recorded is stale
        and stays pending; an inactive Refund method or a reused Customer choice is a conflict; an
        exact repeat by the same approver writes nothing and returns the result again.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_held_value_refund(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=HELD_VALUE_REFUND_CONFIRM_STALE_STATES,
        )

    def record_forfeiture_reversal(
        self,
        property_id: UUID,
        command: RecordForfeitureReversalCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a forfeiture reversal correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordForfeitureReversalCorrectionCommand):
            raise FinalSettlementInvalidError("Forfeiture reversal correction command is invalid")
        request = RecordForfeitureReversalCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.deposit_disposition_id,
            command.reason,
            command.evidence_reference,
            command.refund_method_id,
            command.reference_note,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_forfeiture_reversal_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.forfeiture_reversal()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_forfeiture_reversal(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending forfeiture reversal correction (financial.approve only).

        A draft whose forfeiture, Deposit or Settlement sources changed since it was recorded is
        stale and stays pending; an inactive Refund method or a reused Customer choice is a
        conflict; an exact repeat by the same approver writes nothing and returns the result again.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_forfeiture_reversal(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=FORFEITURE_REVERSAL_CONFIRM_STALE_STATES,
        )

    def record_returned_payment(
        self,
        property_id: UUID,
        command: RecordReturnedPaymentCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a returned-Payment correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordReturnedPaymentCorrectionCommand):
            raise FinalSettlementInvalidError("Returned-Payment correction command is invalid")
        request = RecordReturnedPaymentCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.payment_id,
            command.reason,
            command.evidence_reference,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_returned_payment_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.returned_payment()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_returned_payment(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending returned-Payment correction (financial.approve only).

        A draft whose Payment, Credits, Deposits or their records changed since it was recorded is
        stale and stays pending; a Payment another closed Final Settlement relied on, a Refund not
        fully returned or a waiting draft is a conflict; an exact repeat by the same approver
        writes nothing and returns the result again.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_returned_payment(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=RETURNED_PAYMENT_CONFIRM_STALE_STATES,
        )

    def record_deposit_receipt_correction(
        self,
        property_id: UUID,
        command: RecordDepositReceiptCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a Deposit receipt correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordDepositReceiptCorrectionCommand):
            raise FinalSettlementInvalidError("Deposit receipt correction command is invalid")
        request = RecordDepositReceiptCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.deposit_receipt_id,
            command.reason,
            command.evidence_reference,
            command.receipts,
            command.steps,
            command.pet_remainder,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_deposit_receipt_correction_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.deposit_receipt_correction()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_deposit_receipt_correction(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending Deposit receipt correction (financial.approve only).

        A draft whose receipt, Deposit, Deposit applications or Refunds changed since it was
        recorded is stale and stays pending; a kept Deposit, a receipt of another Lease or a
        waiting draft is a conflict; an exact repeat by the same approver writes nothing and
        returns the result again.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_deposit_receipt_correction(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=DEPOSIT_RECEIPT_CORRECTION_CONFIRM_STALE_STATES,
        )

    def record_return_reversal(
        self,
        property_id: UUID,
        command: RecordReturnReversalCorrectionCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        """Record a return reversal correction draft; it has no effect until confirmed."""
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINAL_SETTLEMENTS_PREPARE_CAPABILITY
        )
        if not isinstance(command, RecordReturnReversalCorrectionCommand):
            raise FinalSettlementInvalidError("Return reversal correction command is invalid")
        request = RecordReturnReversalCorrectionCommand(
            command.idempotency_key,
            command.settlement_id,
            command.earlier_correction_id,
            command.reason,
            command.evidence_reference,
        )
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.record_settlement_return_reversal_draft(%s,%s,%s,%s,%s,%s,%s)",
            (
                property_id,
                actor_id,
                settlement_correction_draft_id(property_id, actor_id, request.idempotency_key),
                request.settlement_id,
                Jsonb(request.return_reversal()),
                request.reason,
                FINAL_SETTLEMENTS_PREPARE_CAPABILITY,
            ),
        )

    def confirm_return_reversal(
        self, property_id: UUID, draft_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        """Confirm a pending return reversal correction (financial.approve only).

        A draft whose earlier correction, returned Credit or Deposit, or records to undo changed
        since it was recorded is stale and stays pending; a return already reversed, a value no
        longer available or a Refund with its own return is a conflict; a draft whose stored plan
        or keys differ from what its source gives is not found; an exact repeat by the same
        approver writes nothing and returns the result again. When part of an application is
        applied again (sub-slice 10e-3c), the existing Credit and Deposit application checks
        still apply, so a state they refuse (for example a Rent-first proposal that no longer
        gives the line) refuses the confirmation.
        """
        actor_id = FinalSettlementService._authorize(
            actor, property_id, FINANCIAL_APPROVE_CAPABILITY
        )
        _uuid(draft_id, "draft_id")
        return FinalSettlementService(self.financial_database_url)._call(
            "SELECT app.confirm_settlement_return_reversal(%s,%s,%s,%s)",
            (property_id, actor_id, draft_id, FINANCIAL_APPROVE_CAPABILITY),
            stale=RETURN_REVERSAL_CONFIRM_STALE_STATES,
        )
