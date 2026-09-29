"""As-of dated balances from a complete, source-validated line history.

This module does not approve sources, query a database or post financial events.
Callers must obtain one complete transaction-consistent history. Unpartitioned
legacy effects are never assigned using today's default allocation order.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from property_rental.invoice_due import (
    MAX_BALANCE_CENTS,
    MAX_POSTED_CENTS,
    DueAmount,
    DueSourceKind,
)


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("A nonzero financial record identity is required")


def _timestamp(value: datetime) -> None:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError("An aware financial event timestamp is required")


def _amount(value: int, maximum: int = MAX_BALANCE_CENTS) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("A positive bounded integer USD-cent amount is required")


def _reversal(occurred_at: datetime, reversed_at: datetime | None) -> None:
    _timestamp(occurred_at)
    if reversed_at is not None:
        _timestamp(reversed_at)
        if reversed_at < occurred_at:
            raise ValueError("Reversal cannot precede its source event")


@dataclass(frozen=True, slots=True)
class DueObligation:
    invoice_line_id: UUID
    source_kind: DueSourceKind
    source_id: UUID
    approved_due_date: date | None
    occurred_at: datetime
    amount_usd_cents: int
    reversed_at: datetime | None = None

    def __post_init__(self) -> None:
        _identity(self.invoice_line_id)
        _identity(self.source_id)
        if not isinstance(self.source_kind, DueSourceKind):
            raise ValueError("A supported obligation source kind is required")
        if self.approved_due_date is not None and type(self.approved_due_date) is not date:
            raise ValueError("A due date must be an approved calendar date or unknown")
        if self.source_kind is DueSourceKind.ORIGINAL_LINE:
            if self.source_id != self.invoice_line_id or self.approved_due_date is None:
                raise ValueError("The original amount requires its line identity and due date")
            if self.reversed_at is not None:
                raise ValueError("An issued original line cannot be reversed as an Adjustment")
        _amount(self.amount_usd_cents)
        _reversal(self.occurred_at, self.reversed_at)


class DueEffectKind(StrEnum):
    PAYMENT_ALLOCATION = "PAYMENT_ALLOCATION"
    CUSTOMER_CREDIT_APPLICATION = "CUSTOMER_CREDIT_APPLICATION"
    CREDIT_ADJUSTMENT = "CREDIT_ADJUSTMENT"


@dataclass(frozen=True, slots=True)
class DueSourcePart:
    source_kind: DueSourceKind
    source_id: UUID
    amount_usd_cents: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, DueSourceKind):
            raise ValueError("A supported part source kind is required")
        _identity(self.source_id)
        _amount(self.amount_usd_cents)


@dataclass(frozen=True, slots=True)
class DueReduction:
    invoice_line_id: UUID
    effect_kind: DueEffectKind
    effect_id: UUID
    occurred_at: datetime
    amount_usd_cents: int
    parts: tuple[DueSourcePart, ...] | None
    reversed_at: datetime | None = None

    def __post_init__(self) -> None:
        _identity(self.invoice_line_id)
        _identity(self.effect_id)
        if not isinstance(self.effect_kind, DueEffectKind):
            raise ValueError("A supported reduction kind is required")
        # Historical Adjustments retain their existing BIGINT storage bound.
        # Payment/Credit details retain their smaller explicit posting bound.
        maximum = (
            MAX_BALANCE_CENTS
            if self.effect_kind is DueEffectKind.CREDIT_ADJUSTMENT
            else MAX_POSTED_CENTS
        )
        _amount(self.amount_usd_cents, maximum)
        _reversal(self.occurred_at, self.reversed_at)
        if self.parts is not None:
            if type(self.parts) is not tuple or not self.parts:
                raise ValueError("Recorded parts must be a nonempty immutable tuple")
            seen: set[tuple[DueSourceKind, UUID]] = set()
            for part in self.parts:
                if type(part) is not DueSourcePart:
                    raise ValueError("A validated source part is required")
                key = (part.source_kind, part.source_id)
                if key in seen:
                    raise ValueError("A reduction may identify each source only once")
                seen.add(key)
            if sum(part.amount_usd_cents for part in self.parts) != self.amount_usd_cents:
                raise ValueError("Recorded parts must exactly conserve their reduction amount")


class DueHistoryBlockerCode(StrEnum):
    MISSING_APPROVED_DUE_DATE = "MISSING_APPROVED_DUE_DATE"
    AMBIGUOUS_LEGACY_ATTRIBUTION = "AMBIGUOUS_LEGACY_ATTRIBUTION"


@dataclass(frozen=True, slots=True)
class DueHistoryBlocker:
    code: DueHistoryBlockerCode
    record_kind: str
    record_id: UUID


@dataclass(frozen=True, slots=True)
class ProvenOriginalReduction:
    effect_kind: DueEffectKind
    effect_id: UUID


@dataclass(frozen=True, slots=True)
class LineDuePosition:
    invoice_line_id: UUID
    as_of: datetime
    aggregate_outstanding_usd_cents: int
    amounts: tuple[DueAmount, ...]
    blockers: tuple[DueHistoryBlocker, ...]
    proven_original_reductions: tuple[ProvenOriginalReduction, ...]

    @property
    def attribution_complete(self) -> bool:
        return not self.blockers

    def require_amounts(self) -> tuple[DueAmount, ...]:
        """Require completeness before using the within-line proposal calculation."""
        if self.blockers:
            raise ValueError("Dated attribution requires missing historical evidence")
        return self.amounts


def _active(occurred: datetime, reversed_at: datetime | None, as_of: datetime) -> bool:
    return occurred <= as_of and (reversed_at is None or as_of < reversed_at)


def _validate_history(
    line_id: UUID,
    obligations: tuple[DueObligation, ...],
    reductions: tuple[DueReduction, ...],
) -> dict[tuple[DueSourceKind, UUID], DueObligation]:
    if type(obligations) is not tuple or type(reductions) is not tuple:
        raise ValueError("A complete immutable line history is required")
    sources: dict[tuple[DueSourceKind, UUID], DueObligation] = {}
    for source in obligations:
        if type(source) is not DueObligation or source.invoice_line_id != line_id:
            raise ValueError("Every source must belong to the selected line")
        key = (source.source_kind, source.source_id)
        if key in sources:
            raise ValueError("Duplicate obligation source identity")
        sources[key] = source
    original = sources.get((DueSourceKind.ORIGINAL_LINE, line_id))
    if original is None:
        raise ValueError("A complete history requires its issued original amount")
    if any(source.occurred_at < original.occurred_at for source in obligations):
        raise ValueError("A debit cannot precede original issuance")
    seen: set[tuple[DueEffectKind, UUID]] = set()
    for reduction in reductions:
        if type(reduction) is not DueReduction or reduction.invoice_line_id != line_id:
            raise ValueError("Every reduction must belong to the selected line")
        identity = (reduction.effect_kind, reduction.effect_id)
        if identity in seen:
            raise ValueError("Duplicate reduction identity")
        seen.add(identity)
        if reduction.occurred_at < original.occurred_at:
            raise ValueError("A reduction cannot precede original issuance")
        for part in reduction.parts or ():
            part_source = sources.get((part.source_kind, part.source_id))
            if part_source is None:
                raise ValueError("Recorded part references a missing line source")
            if part_source.occurred_at > reduction.occurred_at or (
                part_source.reversed_at is not None
                and part_source.reversed_at <= reduction.occurred_at
            ):
                raise ValueError("Recorded part source did not exist when the reduction posted")
            if part_source.reversed_at is not None and (
                reduction.reversed_at is None or reduction.reversed_at > part_source.reversed_at
            ):
                raise ValueError("A source reversal has an unresolved application dependency")
    return sources


def reconcile_line_due_history(
    invoice_line_id: UUID,
    as_of: datetime,
    obligations: tuple[DueObligation, ...],
    reductions: tuple[DueReduction, ...],
) -> LineDuePosition:
    """Project recorded parts, never reallocate them or invent missing dates.

    A legacy reduction is provably original-only only when no debit had ever
    occurred by its posting time. Reversed debits still count for this historical
    proof. Unknown active attribution suppresses the entire usable dated set.
    """
    _identity(invoice_line_id)
    _timestamp(as_of)
    sources = _validate_history(invoice_line_id, obligations, reductions)
    balances = {
        key: source.amount_usd_cents
        for key, source in sources.items()
        if _active(source.occurred_at, source.reversed_at, as_of)
    }
    active_reductions = tuple(
        reduction
        for reduction in reductions
        if _active(reduction.occurred_at, reduction.reversed_at, as_of)
    )
    aggregate = sum(balances.values()) - sum(r.amount_usd_cents for r in active_reductions)
    if not 0 <= aggregate <= MAX_BALANCE_CENTS:
        raise ValueError("Aggregate line balance is outside the supported accounting range")
    blockers: list[DueHistoryBlocker] = []
    proven: list[ProvenOriginalReduction] = []
    for key in balances:
        source = sources[key]
        if source.approved_due_date is None:
            blockers.append(
                DueHistoryBlocker(
                    DueHistoryBlockerCode.MISSING_APPROVED_DUE_DATE,
                    source.source_kind.value,
                    source.source_id,
                )
            )
    for reduction in active_reductions:
        parts = reduction.parts
        if parts is None:
            if any(
                source.source_kind is DueSourceKind.DEBIT_ADJUSTMENT
                and source.occurred_at <= reduction.occurred_at
                for source in obligations
            ):
                blockers.append(
                    DueHistoryBlocker(
                        DueHistoryBlockerCode.AMBIGUOUS_LEGACY_ATTRIBUTION,
                        reduction.effect_kind.value,
                        reduction.effect_id,
                    )
                )
                continue
            parts = (
                DueSourcePart(
                    DueSourceKind.ORIGINAL_LINE, invoice_line_id, reduction.amount_usd_cents
                ),
            )
            proven.append(ProvenOriginalReduction(reduction.effect_kind, reduction.effect_id))
        for part in parts:
            key = (part.source_kind, part.source_id)
            if key not in balances:
                raise ValueError("An active reduction references an inactive source")
            balances[key] -= part.amount_usd_cents
            if balances[key] < 0:
                raise ValueError("Recorded reductions exceed their source amount")
    amounts: list[DueAmount] = []
    if not blockers:
        for key, remaining in balances.items():
            source = sources[key]
            due = source.approved_due_date
            if due is None:
                raise ValueError("A complete dated position cannot contain an unknown due date")
            amounts.append(
                DueAmount(
                    invoice_line_id,
                    source.source_kind,
                    source.source_id,
                    due,
                    source.occurred_at,
                    remaining,
                )
            )
        if sum(item.remaining_usd_cents for item in amounts) != aggregate:
            raise ValueError("Dated amounts do not reconcile to the aggregate line balance")
    return LineDuePosition(
        invoice_line_id,
        as_of,
        aggregate,
        tuple(sorted(amounts, key=lambda x: (x.source_kind.value, x.source_id.int))),
        tuple(sorted(blockers, key=lambda x: (x.code.value, x.record_kind, x.record_id.int))),
        tuple(sorted(proven, key=lambda x: (x.effect_kind.value, x.effect_id.int))),
    )
