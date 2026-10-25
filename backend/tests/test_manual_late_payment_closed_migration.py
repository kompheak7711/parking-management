"""Real PostgreSQL coverage of closing the manual late-payment decision and the free charge
corrections (V1-056 slice 11g-3; DL-076 answers 1 and 4).

From the Property's first finished automatic pass on, a person's decision and every free
correction are refused; an exact repeat of an earlier request still gets its stored answer, and
a reduction with a fixed reason still works.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.late_payment import (
    CorrectionKind,
    CorrectLatePaymentChargeCommand,
    DecisionOutcome,
    FinalizeLatePaymentDecisionCommand,
    LatePaymentConflictError,
    ReductionReason,
)
from test_automatic_late_payment_charge_migration import (
    clear_runs,
    months_ago,
    overdue,
    seed_last_run,
)
from test_final_settlement_closed_refusal_migration import overdue_case
from test_final_settlement_migration import one
from test_final_settlement_preview_migration import issues, preview
from test_invoice_migration import register_billing_service_principal
from test_late_payment_charge_reduction_migration import charged, position, reduce
from test_late_payment_migration import migrated_database_url as migrated_database_url
from test_late_payment_migration import service as late_payments


@pytest.fixture(autouse=True)
def no_pass_yet(migrated_database_url: str) -> Iterator[None]:
    clear_runs(migrated_database_url)
    yield
    clear_runs(migrated_database_url)


def person(case: dict[str, Any]) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(case["human"]),
        capability_grants=frozenset(
            {
                CapabilityGrant(capability, frozenset({str(case["prop"])}))
                for capability in (
                    "late_payment.review",
                    "late_payment.final_decision",
                    "late_payment.charge_correction",
                )
            }
        ),
    )


def decide(case: dict[str, Any], key: UUID) -> dict[str, object]:
    return late_payments().finalize_decision(
        case["prop"],
        case["invoice"],
        FinalizeLatePaymentDecisionCommand(
            key, DecisionOutcome.CONFIRMED_DEFAULT, 8_000, "Confirmed the default charge"
        ),
        actor=person(case),
    )


def decisions_of(url: str, invoice: UUID) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.late_payment_decisions WHERE source_invoice_id=%s",
            invoice,
        )[0]
    )


def test_after_the_first_pass_a_manual_decision_is_refused_but_a_repeat_replays(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    earlier = overdue(url, months_ago(url, 18))
    later = overdue(url, months_ago(url, 19))
    key = uuid4()
    # Before any pass a person's decision is still taken (history before slice 11g-3).
    first = decide(earlier, key)

    seed_last_run(url, later["prop"], later["service"], later["due"])

    assert decide(earlier, key) == first
    with pytest.raises(LatePaymentConflictError) as failure:
        decide(later, uuid4())
    assert "added automatically" in str(failure.value.__cause__)
    assert decisions_of(url, later["invoice"]) == 0
    # Until a finished pass has covered the charge day (the day after the Due Date) the review
    # still waits for that pass; after it, the review no longer offers a decision.
    review = late_payments().review(later["invoice"], actor=person(later))
    assert review["eligible"] is True
    assert "AUTOMATIC_CHARGE_ONLY" not in cast(list[str], review["blocking_conditions"])
    seed_last_run(url, later["prop"], later["service"], later["due"] + timedelta(days=1))
    review = late_payments().review(later["invoice"], actor=person(later))
    assert review["eligible"] is False
    assert "AUTOMATIC_CHARGE_ONLY" in cast(list[str], review["blocking_conditions"])


def test_after_the_first_pass_only_a_reduction_with_a_fixed_reason_changes_a_charge(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    case = charged(url, 20)
    clear_runs(url)
    earlier = late_payments().correct_charge(
        case["prop"],
        case["charge"],
        CorrectLatePaymentChargeCommand(
            key := uuid4(), CorrectionKind.REDUCTION, "Before the pass", amount_usd_cents=1_000
        ),
        actor=person(case),
    )
    reduction = UUID(str(earlier["corrections"][0]["id"]))  # type: ignore[index]
    seed_last_run(url, case["prop"], case["service"], case["due"])

    # An exact repeat still gets its stored answer.
    assert (
        late_payments().correct_charge(
            case["prop"],
            case["charge"],
            CorrectLatePaymentChargeCommand(
                key, CorrectionKind.REDUCTION, "Before the pass", amount_usd_cents=1_000
            ),
            actor=person(case),
        )
        == earlier
    )
    for command in (
        CorrectLatePaymentChargeCommand(
            uuid4(), CorrectionKind.REDUCTION, "A free reduction", amount_usd_cents=500
        ),
        CorrectLatePaymentChargeCommand(uuid4(), CorrectionKind.CHARGE_REVERSAL, "A free waiver"),
        CorrectLatePaymentChargeCommand(
            uuid4(),
            CorrectionKind.REDUCTION_REVERSAL,
            "Raise it back",
            reverses_correction_id=reduction,
        ),
    ):
        with pytest.raises(LatePaymentConflictError) as failure:
            late_payments().correct_charge(
                case["prop"], case["charge"], command, actor=person(case)
            )
        assert "fixed reason" in str(failure.value.__cause__)
    assert position(url, case["charge"]) == (7_000, 7_000)
    # The charge read tells the old screen to hide the free correction form; the key is absent
    # before the first pass.
    assert "manual_corrections_open" not in earlier
    assert (
        late_payments().get_charge(case["charge"], actor=person(case))["manual_corrections_open"]
        is False
    )

    reduce(case, 2_000, ReductionReason.OTHER_STAFF_MISTAKE)
    assert position(url, case["charge"]) == (2_000, 2_000)


def test_after_the_first_pass_a_final_settlement_waits_for_no_manual_decision(
    migrated_database_url: str,
) -> None:
    """An overdue Invoice the pass did not charge (for example one overdue before the first pass,
    owner answer of 2026-10-25) no longer blocks the Final Settlement as waiting for a decision
    no one can record, once a finished pass has covered its charge day."""
    url = migrated_database_url
    case = overdue_case(url)
    before = preview(case["prop"], case["human"], case["settlement"])
    assert [item["invoice_id"] for item in issues(before, "LATE_PAYMENT_DECISION_MISSING")] == [
        str(case["undecided"])
    ]
    with psycopg.connect(url) as connection:
        service = register_billing_service_principal(
            connection, property_id=case["prop"], created_by=case["human"]
        )
    # A pass that has not yet covered the Invoice's charge day may still charge it, so the
    # Final Settlement still waits (review round 2).
    due = one(url, "SELECT due_date FROM app.invoices WHERE id=%s", case["undecided"])[0]
    seed_last_run(url, case["prop"], service, due)
    waiting = preview(case["prop"], case["human"], case["settlement"])
    assert [item["invoice_id"] for item in issues(waiting, "LATE_PAYMENT_DECISION_MISSING")] == [
        str(case["undecided"])
    ]
    seed_last_run(url, case["prop"], service, due + timedelta(days=1))

    after = preview(case["prop"], case["human"], case["settlement"])
    assert issues(after, "LATE_PAYMENT_DECISION_MISSING") == []
