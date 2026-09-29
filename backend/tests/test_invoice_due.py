"""Approved same-line due ordering, conservation and source boundaries."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from itertools import permutations
from typing import Any
from uuid import UUID

import pytest

from property_rental.invoice_due import (
    MAX_BALANCE_CENTS,
    MAX_POSTED_CENTS,
    DueAllocation,
    DueAmount,
    DueSourceKind,
    propose_within_line_due_allocation,
)

LINE = UUID(int=1)
AT = datetime(2026, 8, 1, tzinfo=UTC)
ORIGINAL = DueAmount(LINE, DueSourceKind.ORIGINAL_LINE, LINE, date(2026, 8, 5), AT, 80_000)
DEBIT = DueAmount(
    LINE,
    DueSourceKind.DEBIT_ADJUSTMENT,
    UUID(int=2),
    date(2026, 9, 10),
    AT + timedelta(days=30),
    20_000,
)


@pytest.mark.parametrize(
    ("available", "expected", "unapplied"),
    [
        (1, (1,), 0),
        (50_000, (50_000,), 0),
        (80_000, (80_000,), 0),
        (90_000, (80_000, 10_000), 0),
        (100_000, (80_000, 20_000), 0),
        (110_000, (80_000, 20_000), 10_000),
    ],
)
def test_owner_example_and_exact_conservation(
    available: int, expected: tuple[int, ...], unapplied: int
) -> None:
    snapshot = (DEBIT, ORIGINAL)
    result = propose_within_line_due_allocation(LINE, available, snapshot)
    assert tuple(x.amount_usd_cents for x in result.allocations) == expected
    assert result.allocations[0].source == ORIGINAL
    assert result.applied_usd_cents + result.unapplied_usd_cents == available
    assert result.unapplied_usd_cents == unapplied
    assert snapshot == (DEBIT, ORIGINAL)
    assert ORIGINAL.remaining_usd_cents == 80_000 and DEBIT.remaining_usd_cents == 20_000


def test_approved_due_date_precedes_source_creation_order() -> None:
    earlier = replace(DEBIT, approved_due_date=date(2026, 8, 3))
    result = propose_within_line_due_allocation(LINE, 30_000, (ORIGINAL, earlier))
    assert [(x.source.source_id, x.amount_usd_cents) for x in result.allocations] == [
        (earlier.source_id, 20_000),
        (ORIGINAL.source_id, 10_000),
    ]


def test_equal_due_dates_have_permutation_invariant_chronological_identity_ties() -> None:
    first = replace(DEBIT, source_id=UUID(int=4), approved_due_date=ORIGINAL.approved_due_date)
    second = replace(first, source_id=UUID(int=5))
    expected = [(LINE, 80_000), (first.source_id, 20_000), (second.source_id, 1)]
    for inputs in permutations((second, ORIGINAL, first)):
        result = propose_within_line_due_allocation(LINE, 100_001, inputs)
        assert [(x.source.source_id, x.amount_usd_cents) for x in result.allocations] == expected


def test_timestamp_offsets_describe_the_same_instant_for_ties() -> None:
    first = replace(DEBIT, source_occurred_at=AT, approved_due_date=ORIGINAL.approved_due_date)
    other = replace(
        first, source_id=UUID(int=3), source_occurred_at=AT.astimezone(timezone(timedelta(hours=7)))
    )
    result = propose_within_line_due_allocation(LINE, 20_001, (other, first))
    assert [x.source.source_id for x in result.allocations] == [first.source_id, other.source_id]


def test_zero_balances_and_empty_lines_do_not_create_allocations() -> None:
    for inputs in ((), (replace(ORIGINAL, remaining_usd_cents=0),)):
        result = propose_within_line_due_allocation(LINE, 100, inputs)
        assert result.allocations == () and result.unapplied_usd_cents == 100
    result = propose_within_line_due_allocation(
        LINE, 100, (replace(ORIGINAL, remaining_usd_cents=0), DEBIT)
    )
    assert result.allocations == (DueAllocation(DEBIT, 100),)


def test_snapshot_balances_and_posted_amounts_keep_their_distinct_exact_limits() -> None:
    source = replace(ORIGINAL, remaining_usd_cents=MAX_BALANCE_CENTS)
    result = propose_within_line_due_allocation(LINE, MAX_POSTED_CENTS, (source,))
    assert result.applied_usd_cents == MAX_POSTED_CENTS
    assert source.remaining_usd_cents == MAX_BALANCE_CENTS
    with pytest.raises(ValueError, match="accounting range"):
        propose_within_line_due_allocation(LINE, 1, (source, DEBIT))


@pytest.mark.parametrize(
    "amount", [True, False, 1.0, Decimal("1"), "1", None, -1, 0, MAX_POSTED_CENTS + 1]
)
def test_available_money_requires_positive_bounded_integer_cents(amount: Any) -> None:
    with pytest.raises(ValueError, match="integer USD cents"):
        propose_within_line_due_allocation(LINE, amount, (ORIGINAL,))


@pytest.mark.parametrize(
    "amount", [True, False, 1.0, Decimal("1"), "1", None, -1, MAX_BALANCE_CENTS + 1]
)
def test_source_balance_requires_nonnegative_bounded_integer_cents(amount: Any) -> None:
    with pytest.raises(ValueError, match="integer USD cents"):
        replace(ORIGINAL, remaining_usd_cents=amount)


@pytest.mark.parametrize("value", [None, "2026-08-05", AT])
def test_missing_or_inexact_due_date_is_never_imputed(value: Any) -> None:
    with pytest.raises(ValueError, match="approved calendar"):
        replace(ORIGINAL, approved_due_date=value)


@pytest.mark.parametrize(
    "value", [None, "2026-08-01T00:00:00Z", AT.replace(tzinfo=None), date(2026, 8, 1)]
)
def test_source_time_requires_aware_datetime(value: Any) -> None:
    with pytest.raises(ValueError, match="aware source"):
        replace(ORIGINAL, source_occurred_at=value)


@pytest.mark.parametrize("identity", [None, str(LINE), UUID(int=0)])
def test_nonzero_typed_source_and_line_identities_are_required(identity: Any) -> None:
    with pytest.raises(ValueError):
        replace(ORIGINAL, invoice_line_id=identity)
    with pytest.raises(ValueError):
        replace(ORIGINAL, source_id=identity)
    with pytest.raises(ValueError):
        propose_within_line_due_allocation(identity, 1, (ORIGINAL,))


def test_original_source_identity_and_kind_are_validated() -> None:
    with pytest.raises(ValueError, match="original amount"):
        replace(ORIGINAL, source_id=UUID(int=42))
    with pytest.raises(ValueError, match="supported due-amount"):
        invalid_kind: Any = "ORIGINAL_LINE"
        replace(ORIGINAL, source_kind=invalid_kind)


def test_all_sources_are_validated_before_covering_even_one_cent() -> None:
    other = replace(DEBIT, invoice_line_id=UUID(int=99))
    with pytest.raises(ValueError, match="selected Invoice line"):
        propose_within_line_due_allocation(LINE, 1, (ORIGINAL, other))
    with pytest.raises(ValueError, match="only once"):
        propose_within_line_due_allocation(LINE, 1, (ORIGINAL, DEBIT, DEBIT))
    malformed: Any = {"remaining_usd_cents": 0}
    with pytest.raises(ValueError, match="selected Invoice line"):
        propose_within_line_due_allocation(LINE, 1, (ORIGINAL, malformed))
    mutable: Any = [ORIGINAL]
    with pytest.raises(ValueError, match="immutable"):
        propose_within_line_due_allocation(LINE, 1, mutable)


def test_proposed_parts_cannot_exceed_source_or_command_limits() -> None:
    invalid_values: tuple[Any, ...] = (0, -1, 1.0, True, 80_001)
    for invalid in invalid_values:
        with pytest.raises(ValueError):
            DueAllocation(ORIGINAL, invalid)
    with pytest.raises(ValueError):
        DueAllocation(
            replace(ORIGINAL, remaining_usd_cents=MAX_BALANCE_CENTS), MAX_POSTED_CENTS + 1
        )


def test_source_snapshot_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        source: Any = ORIGINAL
        source.remaining_usd_cents = 0
