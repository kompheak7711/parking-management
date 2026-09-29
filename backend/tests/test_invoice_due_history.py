"""History projections preserve attribution and explicitly refuse missing evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from typing import Any
from uuid import UUID

import pytest

from property_rental.invoice_due import (
    MAX_BALANCE_CENTS,
    MAX_POSTED_CENTS,
    DueSourceKind,
    propose_within_line_due_allocation,
)
from property_rental.invoice_due_history import (
    DueEffectKind,
    DueHistoryBlockerCode,
    DueObligation,
    DueReduction,
    DueSourcePart,
    LineDuePosition,
    ProvenOriginalReduction,
    reconcile_line_due_history,
)

LINE = UUID(int=1)
AT = datetime(2026, 8, 1, tzinfo=UTC)
AS_OF = AT + timedelta(days=50)
ORIGINAL = DueObligation(LINE, DueSourceKind.ORIGINAL_LINE, LINE, date(2026, 8, 5), AT, 80_000)
DEBIT = DueObligation(
    LINE,
    DueSourceKind.DEBIT_ADJUSTMENT,
    UUID(int=2),
    date(2026, 9, 10),
    AT + timedelta(days=20),
    20_000,
)


def original_part(amount: int) -> DueSourcePart:
    return DueSourcePart(DueSourceKind.ORIGINAL_LINE, LINE, amount)


def debit_part(amount: int) -> DueSourcePart:
    return DueSourcePart(DEBIT.source_kind, DEBIT.source_id, amount)


def payment() -> DueReduction:
    return DueReduction(
        LINE,
        DueEffectKind.PAYMENT_ALLOCATION,
        UUID(int=3),
        AT + timedelta(days=30),
        50_000,
        (original_part(50_000),),
    )


def balances(position: LineDuePosition) -> dict[UUID, int]:
    return {x.source_id: x.remaining_usd_cents for x in position.require_amounts()}


def test_recorded_owner_example_feeds_existing_proposal_without_changing_dates() -> None:
    position = reconcile_line_due_history(LINE, AS_OF, (DEBIT, ORIGINAL), (payment(),))
    assert position.attribution_complete
    assert position.aggregate_outstanding_usd_cents == 50_000
    assert balances(position) == {LINE: 30_000, DEBIT.source_id: 20_000}
    proposal = propose_within_line_due_allocation(LINE, 40_000, position.require_amounts())
    assert [(x.source.source_id, x.amount_usd_cents) for x in proposal.allocations] == [
        (LINE, 30_000),
        (DEBIT.source_id, 10_000),
    ]
    assert [x.source.approved_due_date for x in proposal.allocations] == [
        ORIGINAL.approved_due_date,
        DEBIT.approved_due_date,
    ]
    assert position.proven_original_reductions == ()


def test_reversing_earlier_payment_never_moves_a_later_credit_to_new_sources() -> None:
    first = replace(payment(), reversed_at=AT + timedelta(days=40))
    credit = DueReduction(
        LINE,
        DueEffectKind.CUSTOMER_CREDIT_APPLICATION,
        UUID(int=4),
        AT + timedelta(days=35),
        40_000,
        (original_part(30_000), debit_part(10_000)),
    )
    before = reconcile_line_due_history(
        LINE, AT + timedelta(days=39), (ORIGINAL, DEBIT), (first, credit)
    )
    after = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (first, credit))
    assert balances(before) == {LINE: 0, DEBIT.source_id: 10_000}
    assert balances(after) == {LINE: 50_000, DEBIT.source_id: 10_000}
    assert after.aggregate_outstanding_usd_cents == 60_000
    assert credit.parts == (original_part(30_000), debit_part(10_000))
    reversed_credit = replace(credit, reversed_at=AS_OF)
    restored = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (first, reversed_credit))
    assert balances(restored) == {LINE: 80_000, DEBIT.source_id: 20_000}


@pytest.mark.parametrize("kind", list(DueEffectKind))
def test_each_reduction_kind_uses_its_explicit_parts_and_exact_reversal(
    kind: DueEffectKind,
) -> None:
    correction = replace(
        payment(),
        effect_kind=kind,
        amount_usd_cents=15_000,
        parts=(debit_part(15_000),),
        reversed_at=AS_OF,
    )
    before = reconcile_line_due_history(
        LINE, AS_OF - timedelta(microseconds=1), (ORIGINAL, DEBIT), (correction,)
    )
    after = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (correction,))
    assert balances(before) == {LINE: 80_000, DEBIT.source_id: 5_000}
    assert balances(after) == {LINE: 80_000, DEBIT.source_id: 20_000}


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (-1, 0),
        (0, 80_000),
        (19, 80_000),
        (20, 100_000),
        (29, 100_000),
        (30, 50_000),
        (39, 50_000),
        (40, 100_000),
    ],
)
def test_as_of_boundaries_use_event_times_instead_of_current_state(day: int, expected: int) -> None:
    effect = replace(payment(), reversed_at=AT + timedelta(days=40))
    result = reconcile_line_due_history(
        LINE, AT + timedelta(days=day), (ORIGINAL, DEBIT), (effect,)
    )
    assert result.aggregate_outstanding_usd_cents == expected
    assert sum(balances(result).values()) == expected


def test_history_input_permutations_cannot_change_recorded_positions_or_proof() -> None:
    second = replace(
        payment(),
        effect_id=UUID(int=4),
        effect_kind=DueEffectKind.CREDIT_ADJUSTMENT,
        amount_usd_cents=5_000,
        parts=(debit_part(5_000),),
    )
    expected = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (payment(), second))
    for sources in permutations((ORIGINAL, DEBIT)):
        for effects in permutations((payment(), second)):
            assert reconcile_line_due_history(LINE, AS_OF, sources, effects) == expected


@pytest.mark.parametrize("kind", list(DueEffectKind))
def test_legacy_reduction_before_any_debit_has_labeled_original_only_proof(
    kind: DueEffectKind,
) -> None:
    old = replace(payment(), effect_kind=kind, occurred_at=AT + timedelta(days=10), parts=None)
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (old,))
    assert balances(result) == {LINE: 30_000, DEBIT.source_id: 20_000}
    assert result.proven_original_reductions == (ProvenOriginalReduction(kind, old.effect_id),)
    assert old.parts is None


@pytest.mark.parametrize("day", [20, 21, 30])
def test_legacy_after_or_at_debit_time_is_not_backfilled_by_default_order(day: int) -> None:
    old = replace(payment(), occurred_at=AT + timedelta(days=day), parts=None)
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (old,))
    assert result.aggregate_outstanding_usd_cents == 50_000
    assert not result.attribution_complete and result.amounts == ()
    assert result.proven_original_reductions == ()
    assert [(x.code, x.record_id) for x in result.blockers] == [
        (DueHistoryBlockerCode.AMBIGUOUS_LEGACY_ATTRIBUTION, old.effect_id)
    ]
    with pytest.raises(ValueError, match="historical evidence"):
        result.require_amounts()


def test_later_debit_reversal_does_not_rewrite_legacy_attribution() -> None:
    source = replace(DEBIT, reversed_at=AT + timedelta(days=25))
    old = replace(payment(), parts=None)
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (old,))
    assert result.aggregate_outstanding_usd_cents == 30_000
    assert not result.attribution_complete and result.amounts == ()
    assert result.blockers[0].code is DueHistoryBlockerCode.AMBIGUOUS_LEGACY_ATTRIBUTION


def test_missing_debit_date_and_ambiguous_payment_remain_separate_blockers() -> None:
    source = replace(DEBIT, approved_due_date=None)
    old = replace(payment(), parts=None)
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (old,))
    assert result.aggregate_outstanding_usd_cents == 50_000
    assert result.amounts == () and len(result.blockers) == 2
    assert {x.code for x in result.blockers} == set(DueHistoryBlockerCode)
    with pytest.raises(ValueError, match="historical evidence"):
        result.require_amounts()
    assert source.approved_due_date is None and old.parts is None


def test_reversals_remove_current_blockers_without_erasing_historical_blockers() -> None:
    source = replace(DEBIT, approved_due_date=None, reversed_at=AS_OF)
    old = replace(payment(), parts=None, reversed_at=AT + timedelta(days=40))
    current = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (old,))
    history = reconcile_line_due_history(LINE, AT + timedelta(days=35), (ORIGINAL, source), (old,))
    assert balances(current) == {LINE: 80_000}
    assert len(history.blockers) == 2 and history.aggregate_outstanding_usd_cents == 50_000


def test_zero_aggregate_is_not_evidence_of_known_dates() -> None:
    source = replace(DEBIT, approved_due_date=None)
    effect = replace(
        payment(), amount_usd_cents=100_000, parts=(original_part(80_000), debit_part(20_000))
    )
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (effect,))
    assert result.aggregate_outstanding_usd_cents == 0
    assert not result.attribution_complete and result.amounts == ()


def test_customer_designated_debit_parts_do_not_follow_default_original_first() -> None:
    designated = replace(payment(), amount_usd_cents=10_000, parts=(debit_part(10_000),))
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (designated,))
    assert balances(result) == {LINE: 80_000, DEBIT.source_id: 10_000}


def test_typed_effect_identity_allows_same_uuid_in_different_relations() -> None:
    other = replace(
        payment(),
        effect_kind=DueEffectKind.CUSTOMER_CREDIT_APPLICATION,
        amount_usd_cents=10_000,
        parts=(debit_part(10_000),),
    )
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (payment(), other))
    assert result.aggregate_outstanding_usd_cents == 40_000
    with pytest.raises(ValueError, match="Duplicate reduction"):
        reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (payment(), payment()))


@pytest.mark.parametrize(
    "bad", [True, False, 0, -1, 1.0, Decimal("1"), "1", None, MAX_BALANCE_CENTS + 1]
)
def test_all_posted_history_amounts_require_exact_positive_bounded_cents(bad: Any) -> None:
    with pytest.raises(ValueError, match="integer USD-cent"):
        replace(ORIGINAL, amount_usd_cents=bad)
    with pytest.raises(ValueError, match="integer USD-cent"):
        replace(payment(), amount_usd_cents=bad)
    with pytest.raises(ValueError, match="integer USD-cent"):
        original_part(bad)


def test_parts_require_exact_sum_unique_sources_and_immutable_shape() -> None:
    invalid: tuple[Any, ...] = (
        (),
        [original_part(50_000)],
        ({"amount": 50_000},),
        (original_part(49_999),),
        (original_part(25_000), original_part(25_000)),
    )
    for parts in invalid:
        with pytest.raises(ValueError):
            replace(payment(), parts=parts)


@pytest.mark.parametrize("bad", [None, str(LINE), UUID(int=0)])
def test_history_identities_reject_missing_string_and_zero_uuid(bad: Any) -> None:
    with pytest.raises(ValueError):
        replace(DEBIT, source_id=bad)
    with pytest.raises(ValueError):
        replace(payment(), effect_id=bad)
    with pytest.raises(ValueError):
        reconcile_line_due_history(bad, AS_OF, (ORIGINAL, DEBIT), ())


def test_source_and_effect_kinds_require_typed_values() -> None:
    bad: Any = "DEBIT_ADJUSTMENT"
    with pytest.raises(ValueError, match="source kind"):
        replace(DEBIT, source_kind=bad)
    with pytest.raises(ValueError, match="source kind"):
        DueSourcePart(bad, DEBIT.source_id, 1)
    bad_effect: Any = "PAYMENT_ALLOCATION"
    with pytest.raises(ValueError, match="reduction kind"):
        replace(payment(), effect_kind=bad_effect)


def test_original_identity_due_and_reversal_cannot_be_reinterpreted() -> None:
    variants: tuple[dict[str, Any], ...] = (
        {"source_id": UUID(int=99)},
        {"approved_due_date": None},
        {"reversed_at": AS_OF},
    )
    for fields in variants:
        with pytest.raises(ValueError):
            replace(ORIGINAL, **fields)
    bad_due: Any = AT
    with pytest.raises(ValueError, match="calendar date"):
        replace(DEBIT, approved_due_date=bad_due)


def test_reversal_and_posting_timestamps_require_aware_valid_chronology() -> None:
    naive = AT.replace(tzinfo=None)
    with pytest.raises(ValueError, match="aware"):
        replace(payment(), occurred_at=naive)
    with pytest.raises(ValueError, match="aware"):
        replace(payment(), reversed_at=naive)
    with pytest.raises(ValueError, match="precede"):
        replace(payment(), reversed_at=AT)
    with pytest.raises(ValueError, match="aware"):
        reconcile_line_due_history(LINE, naive, (ORIGINAL,), ())
    with pytest.raises(ValueError, match="precede original"):
        reconcile_line_due_history(
            LINE, AS_OF, (ORIGINAL, replace(DEBIT, occurred_at=AT - timedelta(days=1))), ()
        )
    with pytest.raises(ValueError, match="precede original"):
        reconcile_line_due_history(
            LINE, AS_OF, (ORIGINAL,), (replace(payment(), occurred_at=AT - timedelta(days=1)),)
        )


def test_complete_history_rejects_duplicates_cross_line_and_missing_original() -> None:
    for sources in (
        (),
        (DEBIT,),
        (ORIGINAL, DEBIT, DEBIT),
        (ORIGINAL, replace(DEBIT, invoice_line_id=UUID(int=99))),
    ):
        with pytest.raises(ValueError):
            reconcile_line_due_history(LINE, AS_OF, sources, ())
    with pytest.raises(ValueError, match="selected line"):
        reconcile_line_due_history(
            LINE, AS_OF, (ORIGINAL,), (replace(payment(), invoice_line_id=UUID(int=99)),)
        )
    mutable: Any = [ORIGINAL]
    with pytest.raises(ValueError, match="immutable"):
        reconcile_line_due_history(LINE, AS_OF, mutable, ())


def test_explicit_parts_cannot_reference_missing_future_or_reversed_sources() -> None:
    wrong_part = DueSourcePart(DueSourceKind.DEBIT_ADJUSTMENT, LINE, 50_000)
    with pytest.raises(ValueError, match="missing line source"):
        reconcile_line_due_history(
            LINE, AS_OF, (ORIGINAL, DEBIT), (replace(payment(), parts=(wrong_part,)),)
        )
    effect = replace(payment(), amount_usd_cents=5_000, parts=(debit_part(5_000),))
    for source in (
        replace(DEBIT, occurred_at=AS_OF),
        replace(DEBIT, reversed_at=payment().occurred_at),
    ):
        with pytest.raises(ValueError, match="did not exist"):
            reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (effect,))


def test_debit_reversal_requires_its_exact_dependencies_resolved_first() -> None:
    source = replace(DEBIT, reversed_at=AS_OF)
    effect = replace(payment(), amount_usd_cents=5_000, parts=(debit_part(5_000),))
    for active in (effect, replace(effect, reversed_at=AS_OF + timedelta(microseconds=1))):
        with pytest.raises(ValueError, match="unresolved application dependency"):
            reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (active,))
    resolved = replace(effect, reversed_at=AS_OF)
    assert balances(reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, source), (resolved,))) == {
        LINE: 80_000
    }


def test_aggregate_balance_cannot_mask_overapplication_of_one_source() -> None:
    wrong = replace(payment(), amount_usd_cents=30_000, parts=(debit_part(30_000),))
    with pytest.raises(ValueError, match="exceed their source"):
        reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (wrong,))
    too_much = replace(payment(), amount_usd_cents=100_001, parts=None)
    with pytest.raises(ValueError, match="accounting range"):
        reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (too_much,))


def test_inputs_and_output_are_immutable_without_history_backfill() -> None:
    legacy = replace(payment(), parts=None)
    result = reconcile_line_due_history(LINE, AS_OF, (ORIGINAL, DEBIT), (legacy,))
    for obj, field, value in (
        (legacy, "parts", (original_part(50_000),)),
        (result, "blockers", ()),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
    assert legacy.parts is None and not result.attribution_complete


def test_historical_source_and_credit_adjustment_keep_existing_bigint_range() -> None:
    source = replace(ORIGINAL, amount_usd_cents=MAX_BALANCE_CENTS)
    amount = MAX_POSTED_CENTS + 1
    correction = replace(
        payment(),
        effect_kind=DueEffectKind.CREDIT_ADJUSTMENT,
        amount_usd_cents=amount,
        parts=(original_part(amount),),
    )
    position = reconcile_line_due_history(LINE, AS_OF, (source,), (correction,))
    assert balances(position) == {LINE: MAX_BALANCE_CENTS - amount}
    assert position.aggregate_outstanding_usd_cents == MAX_BALANCE_CENTS - amount
    proposed = propose_within_line_due_allocation(
        LINE, MAX_POSTED_CENTS, position.require_amounts()
    )
    assert proposed.applied_usd_cents == MAX_POSTED_CENTS
    with pytest.raises(ValueError, match="integer USD cents"):
        propose_within_line_due_allocation(LINE, amount, position.require_amounts())


@pytest.mark.parametrize(
    "kind", [DueEffectKind.PAYMENT_ALLOCATION, DueEffectKind.CUSTOMER_CREDIT_APPLICATION]
)
def test_payment_and_credit_history_retain_their_smaller_persisted_limit(
    kind: DueEffectKind,
) -> None:
    with pytest.raises(ValueError, match="integer USD-cent"):
        replace(
            payment(),
            effect_kind=kind,
            amount_usd_cents=MAX_POSTED_CENTS + 1,
            parts=(original_part(MAX_POSTED_CENTS + 1),),
        )


def test_projected_aggregate_cannot_overflow_bigint_even_when_sources_fit() -> None:
    source = replace(ORIGINAL, amount_usd_cents=MAX_BALANCE_CENTS)
    with pytest.raises(ValueError, match="accounting range"):
        reconcile_line_due_history(LINE, AS_OF, (source, DEBIT), ())
