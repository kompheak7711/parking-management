"""Deterministic proposals within one already selected Invoice line.

Callers must supply source-validated remaining amounts, including approved due
dates. This calculation neither assigns missing historical dates nor posts an
application. Invoice ordering, line ordering, designations and staff confirmation
belong to the existing surrounding workflow.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

MAX_POSTED_CENTS = 9_000_000_000_000_000
MAX_BALANCE_CENTS = 9_223_372_036_854_775_807


class DueSourceKind(StrEnum):
    ORIGINAL_LINE = "ORIGINAL_LINE"
    DEBIT_ADJUSTMENT = "DEBIT_ADJUSTMENT"


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("A nonzero source identity is required")


def _money(value: int, *, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Amount must be exact bounded integer USD cents")


@dataclass(frozen=True, slots=True)
class DueAmount:
    invoice_line_id: UUID
    source_kind: DueSourceKind
    source_id: UUID
    approved_due_date: date
    source_occurred_at: datetime
    remaining_usd_cents: int

    def __post_init__(self) -> None:
        _identity(self.invoice_line_id)
        _identity(self.source_id)
        if not isinstance(self.source_kind, DueSourceKind):
            raise ValueError("A supported due-amount source is required")
        if (
            self.source_kind is DueSourceKind.ORIGINAL_LINE
            and self.source_id != self.invoice_line_id
        ):
            raise ValueError("The original amount must identify its Invoice line")
        if type(self.approved_due_date) is not date:
            raise ValueError("An approved calendar due date is required")
        if (
            type(self.source_occurred_at) is not datetime
            or self.source_occurred_at.utcoffset() is None
        ):
            raise ValueError("An aware source timestamp is required")
        _money(self.remaining_usd_cents, minimum=0, maximum=MAX_BALANCE_CENTS)


@dataclass(frozen=True, slots=True)
class DueAllocation:
    source: DueAmount
    amount_usd_cents: int

    def __post_init__(self) -> None:
        if type(self.source) is not DueAmount:
            raise ValueError("A validated due amount is required")
        _money(self.amount_usd_cents, minimum=1, maximum=MAX_POSTED_CENTS)
        if self.amount_usd_cents > self.source.remaining_usd_cents:
            raise ValueError("Proposed amount exceeds its source balance")


@dataclass(frozen=True, slots=True)
class WithinLineDueProposal:
    invoice_line_id: UUID
    available_usd_cents: int
    allocations: tuple[DueAllocation, ...]

    @property
    def applied_usd_cents(self) -> int:
        return sum(item.amount_usd_cents for item in self.allocations)

    @property
    def unapplied_usd_cents(self) -> int:
        return self.available_usd_cents - self.applied_usd_cents


def propose_within_line_due_allocation(
    invoice_line_id: UUID,
    available_usd_cents: int,
    amounts: tuple[DueAmount, ...],
) -> WithinLineDueProposal:
    """Propose earliest-due application without mutating sources or moving lines.

    Equal dates use immutable source chronology then kind/identity as stable
    tie-breakers. Validate the entire source set before selecting any amount,
    including sources beyond what the available money can cover.
    """
    _identity(invoice_line_id)
    _money(available_usd_cents, minimum=1, maximum=MAX_POSTED_CENTS)
    if type(amounts) is not tuple:
        raise ValueError("An immutable due-amount snapshot is required")
    identities: set[tuple[DueSourceKind, UUID]] = set()
    total = 0
    for item in amounts:
        if type(item) is not DueAmount or item.invoice_line_id != invoice_line_id:
            raise ValueError("All due amounts must belong to the selected Invoice line")
        identity = (item.source_kind, item.source_id)
        if identity in identities:
            raise ValueError("A due-amount source may occur only once")
        identities.add(identity)
        total += item.remaining_usd_cents
        if total > MAX_BALANCE_CENTS:
            raise ValueError("Line balance exceeds the supported accounting range")
    ordered = sorted(
        amounts,
        key=lambda item: (
            item.approved_due_date,
            item.source_occurred_at,
            item.source_kind.value,
            item.source_id.int,
        ),
    )
    available = available_usd_cents
    parts: list[DueAllocation] = []
    for item in ordered:
        amount = min(available, item.remaining_usd_cents)
        if amount:
            parts.append(DueAllocation(item, amount))
            available -= amount
        if available == 0:
            break
    return WithinLineDueProposal(invoice_line_id, available_usd_cents, tuple(parts))
