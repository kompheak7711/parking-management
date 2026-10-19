"""The mistaken credit Adjustment reversal after closure (V1-056 sub-slice 10f-2).

Owner answer 7 to Q-2026-10-06-36: after the Lease's Final Settlement is closed, a mistaken credit
Adjustment is reversed only inside a correction of that Settlement (the ADJUSTMENT_REVERSAL
variant of the SETTLEMENT_CORRECTION draft), prepared under final_settlements.prepare and confirmed
by financial.approve. The confirm writes the Adjustment reversal and the put-backs of sub-slice
10f-1b (the label put back by a correction, on the Adjustment's own line; owner answer (a) to
Q-2026-10-16-118), each linked to the correction (BR-SETTLE-013, DB-SETTLE-005); the rest of each
release stays as debt on the Invoice Customer's ledger (BR-SETTLE-016); the closed Settlement is
never changed (BR-SETTLE-012). Owner answer (b) to Q-2026-10-16-119: a CHARGE_REDUCTION
correction's Adjustment may be reversed and owes exactly what the reduction removed; every other
correction's Adjustment stays refused.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.adjustment_reversal import (
    AdjustmentReversalAuthorizationError,
    AdjustmentReversalConflictError,
    AdjustmentReversalKeyReused,
    AdjustmentReversalNotFoundError,
    AdjustmentReversalService,
    AdjustmentReversalStaleDraftError,
    RecordSettlementAdjustmentReversalCommand,
)
from property_rental.credit import ReverseCreditApplicationCommand
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.financial_draft import FinancialDraftService
from property_rental.invoice import ResolveHandBackRentCommand
from property_rental.settlement_correction import (
    RecordChargeReductionCorrectionCommand,
    RecordRefundCorrectionCommand,
)
from test_adjustment_reversal_migration import (
    CLOSED,
    adjustments,
    available,
    put_back_rows,
    reconciled,
    refusal,
    reversed_rows,
    status,
    version,
)
from test_adjustment_reversal_migration import REASON as EARLY_REASON
from test_adjustment_reversal_migration import RECORD as EARLY_RECORD
from test_adjustment_reversal_migration import approver as early_approver
from test_adjustment_reversal_migration import draft_id as early_draft_id
from test_adjustment_reversal_migration import preparer as early_preparer
from test_adjustment_reversal_migration import request as early_request
from test_adjustment_reversal_migration import reversals as early_reversals
from test_adjustment_reversal_put_back_migration import (
    LABEL,
    LABEL_REFUSED,
    MESSAGE,
    listed_put_back,
    rent_and_service_invoice,
)
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import pay as pay_payment
from test_credit_application_migration import designated as credit_designated
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import outstanding, start
from test_final_settlement_preview_migration import pay as pay_line
from test_hand_back_rent_migration import (
    AUGUST,
    hand_back,
    hand_back_database,  # noqa: F401
    lease_with_invoices,
)
from test_hand_back_rent_migration import invoices as hand_back_invoices
from test_hand_back_rent_migration import lines as hand_back_lines
from test_hand_back_rent_migration import pay as hand_back_pay
from test_hand_back_rent_migration import staff as hand_back_staff
from test_hand_back_rent_migration import version as hand_back_version
from test_invoice_migration import financial_database_url, runtime_database_url
from test_invoice_migration import migrated_database_url as migrated_database_url
from test_migrations import _temporary_migration_database
from test_payment_move_migration import person, rows, value
from test_settlement_correction_migration import settlement_row
from test_settlement_extra_charge_migration import corrections
from waiting_draft_test_support import recorded_then_rolled_back, written_after_closure

RECORD = "app.record_settlement_adjustment_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)"
CONFIRM = "app.confirm_settlement_adjustment_reversal(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.begin_settlement_correction(uuid,uuid,uuid,text,jsonb)",
    "app.adjustment_reversal_source(uuid,uuid,uuid)",
    "app.settlement_adjustment_reversal_result(uuid)",
)
PATCHED = {
    "app.adjustment_reversal_result(uuid)",
    "app.validate_credit_application_put_back()",
    "app.validate_adjustment_reversal_put_back()",
    "app.adjustment_reversal_put_back_allowed(app.customer_credit_applications,"
    "app.customer_credit_application_details)",
}
REVISION = "20261221_147"
REASON = "The credit was recorded on the wrong Invoice"
WAITING = "Another Adjustment reversal draft of this Adjustment is waiting"
OTHER_CORRECTION = (
    "Of the Adjustments of post-settlement corrections, only a charge reduction's is reversed by "
    "an Adjustment reversal correction"
)


def preparer(human: UUID, prop: UUID) -> Any:
    return person(human, prop, "final_settlements.prepare")


def approver(human: UUID, prop: UUID) -> Any:
    return person(human, prop, "financial.approve")


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def command(
    settlement: UUID, adjustment: UUID, **changes: Any
) -> RecordSettlementAdjustmentReversalCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "settlement_id": settlement,
        "adjustment_id": adjustment,
        "reason": REASON,
        **changes,
    }
    return RecordSettlementAdjustmentReversalCommand(**values)


def record(case: dict[str, Any], adjustment: UUID, **changes: Any) -> dict[str, Any]:
    return reversals_record(case, command(case["settlement"], adjustment, **changes))


def reversals_record(
    case: dict[str, Any], request: RecordSettlementAdjustmentReversalCommand
) -> dict[str, Any]:
    return AdjustmentReversalService(financial_database_url()).record_correction(
        case["prop"], request, actor=preparer(case["human"], case["prop"])
    )


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return AdjustmentReversalService(financial_database_url()).confirm_correction(
        case["prop"], draft, actor=approver(case["human"], case["prop"])
    )


def draft_of(result: dict[str, Any]) -> UUID:
    return UUID(str(result["draft_id"]))


def source_of(result: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], cast(dict[str, Any], result["payload"])["source"])


def cause(failure: pytest.ExceptionInfo[Exception]) -> tuple[Any, Any]:
    error = failure.value.__cause__
    assert isinstance(error, psycopg.Error)
    return error.sqlstate, error.diag.message_primary


def lease_adjustment(url: str, lease: UUID) -> tuple[UUID, UUID, UUID]:
    """The Signer's pre-closure credit Adjustment of the two-Signer fixture: id, Invoice, line."""
    [found] = rows(
        url,
        "SELECT a.id,a.invoice_id,a.invoice_line_id FROM app.invoice_adjustments a "
        "JOIN app.invoices i ON i.id=a.invoice_id "
        "WHERE i.lease_id=%s AND a.adjustment_type='CREDIT'",
        lease,
    )
    return UUID(str(found[0])), UUID(str(found[1])), UUID(str(found[2]))


def invoice_of(url: str, line: UUID) -> UUID:
    return UUID(str(value(url, "SELECT invoice_id FROM app.invoice_lines WHERE id=%s", line)))


def closed_case(url: str, signer_paid: int, credit_used: int) -> dict[str, Any]:
    """The two-Signer Lease closed for real: the Signer pays signer_paid of the Signer's 1,000
    line first, the Settlement's Credit step uses credit_used of the Signer's 400 Credit on the
    rest, and the Pet Deposit's 20,000 pays the overdue Rent."""
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    if signer_paid:
        pay_line(
            url,
            case["prop"],
            case["human"],
            case["co_signer"],
            invoice_of(url, case["signer_line"]),
            case["signer_line"],
            signer_paid,
        )
    steps: tuple[Any, ...] = (
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),
    )
    if credit_used:
        steps = (
            SettlementCreditStep(case["credit"], LINE, case["signer_line"], credit_used),
            *steps,
        )
    confirm_settlement(case, record_settlement(case, steps, pet_remainder=STAFF))
    return case


def effects(url: str, correction: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT effect_sequence,invoice_adjustment_reversal_id,customer_credit_application_id "
        "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s "
        "ORDER BY effect_sequence",
        correction,
    )


def test_a_pre_closure_adjustment_s_released_credit_goes_back_through_a_correction(
    migrated_database_url: str,
) -> None:
    """The Signer's 400 credit Adjustment, recorded before the closure, released 400 of the
    Signer's Payment as Credit; the Signer paid the Signer's own line, so the Settlement did not
    use that Credit. After the real closure the correction reverses the Adjustment and puts the
    whole 400 back on the Adjustment's line with the label; both records are linked to the
    correction; the closed Settlement is unchanged; Staff cannot confirm; a replay returns the
    same; the ledger reconciles; the Adjustment cannot be reversed twice."""
    url = migrated_database_url
    case = closed_case(url, signer_paid=1_000, credit_used=0)
    prop, human, credit = case["prop"], case["human"], case["credit"]
    adjustment, invoice, line = lease_adjustment(url, case["lease"])
    assert (available(url, credit), outstanding(url, line)) == (400, 0)
    before = settlement_row(url, case["settlement"])
    recorded = record(case, adjustment)
    assert (
        recorded["kind"],
        recorded["state"],
        recorded["prepare_capability"],
        cast(dict[str, Any], recorded["payload"])["variant"],
    ) == ("SETTLEMENT_CORRECTION", "PENDING", "final_settlements.prepare", "ADJUSTMENT_REVERSAL")
    source = source_of(recorded)
    [release] = cast(list[dict[str, Any]], source["releases"])
    assert (
        release["source_kind"],
        release["customer_credit_id"],
        release["released_usd_cents"],
        release["put_back_usd_cents"],
        release["debt_usd_cents"],
    ) == ("PAYMENT_ALLOCATION", str(credit), 400, 400, 0)
    assert (
        source["final_settlement_id"],
        source["charge_reduction"],
        source["put_back_usd_cents"],
        source["debt_usd_cents"],
        source["refusal"],
    ) == (str(case["settlement"]), False, 400, 0, None)
    draft = draft_of(recorded)
    with pytest.raises(AdjustmentReversalAuthorizationError):
        AdjustmentReversalService(financial_database_url()).confirm_correction(
            prop, draft, actor=preparer(human, prop)
        )
    # The database refuses a confirm under the preparer's capability (42501); nothing is written.
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as staff_confirm:
            connection.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
                (prop, human, draft),
            )
        connection.rollback()
    assert (staff_confirm.value.sqlstate, staff_confirm.value.diag.message_primary) == (
        "42501",
        "Only financial.approve may confirm a post-settlement correction",
    )
    assert reversed_rows(url, adjustment) == []
    before_version = version(url, invoice)
    result = confirm(case, draft)
    assert "transaction_id" not in json.dumps(result)
    # The reversal advances the Invoice version once and the put-back's refresh once more.
    assert (version(url, invoice), status(url, invoice)) == (before_version + 2, "PAID")
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    assert (
        result["invoice_adjustment_id"],
        result["restored_usd_cents"],
        result["debt_usd_cents"],
        put_back["customer_credit_id"],
        put_back["amount_usd_cents"],
        put_back["invoice_credit_excess_release_id"],
    ) == (
        str(adjustment),
        400,
        0,
        str(credit),
        400,
        release["invoice_credit_excess_release_id"],
    )
    correction = cast(dict[str, Any], result["settlement_correction"])
    assert (correction["final_settlement_id"], correction["reason"]) == (
        str(case["settlement"]),
        REASON,
    )
    application = UUID(str(put_back["credit_application_id"]))
    assert put_back_rows(url, application) == [
        (
            credit,
            400,
            "PUT_BACK_BY_CORRECTION",
            "credits.apply",
            line,
            "PUT_BACK_BY_CORRECTION",
            "Invoice Adjustment reversal put-back",
        )
    ]
    assert effects(url, UUID(str(correction["id"]))) == [
        (1, UUID(str(result["invoice_adjustment_reversal_id"])), None),
        (2, None, application),
    ]
    assert reversed_rows(url, adjustment) == [(REASON, human, "financial.approve")]
    assert (available(url, credit), outstanding(url, line)) == (0, 0)
    assert settlement_row(url, case["settlement"]) == before
    assert confirm(case, draft) == result
    assert rows(
        url,
        "SELECT action,correlation_id FROM app.audit_events WHERE action IN "
        "('invoice.adjustment_reversed','final_settlement.correction.confirmed') "
        "AND (correlation_id=%s OR entity_id=%s) ORDER BY action",
        draft,
        UUID(str(correction["id"])),
    ) == [
        ("final_settlement.correction.confirmed", UUID(str(correction["id"]))),
        ("invoice.adjustment_reversed", draft),
    ]
    with pytest.raises(AdjustmentReversalConflictError) as twice:
        record(case, adjustment)
    assert cause(twice) == ("55000", "The Adjustment is already reversed")
    reconciled(url, invoice)


def test_only_the_credit_still_available_goes_back_and_the_rest_stays_as_debt(
    migrated_database_url: str,
) -> None:
    """The Signer paid 850 of the Signer's 1,000 line, and the Settlement's Credit step used 150
    of the released 400 Credit on the rest. The correction puts back only the 250 still
    available; the other 150 stays as debt on the Adjustment's line, on the Signer's ledger."""
    url = migrated_database_url
    case = closed_case(url, signer_paid=850, credit_used=150)
    credit = case["credit"]
    adjustment, invoice, line = lease_adjustment(url, case["lease"])
    assert available(url, credit) == 250
    recorded = record(case, adjustment)
    [release] = cast(list[dict[str, Any]], source_of(recorded)["releases"])
    assert (
        release["available_usd_cents"],
        release["put_back_usd_cents"],
        release["debt_usd_cents"],
    ) == (250, 250, 150)
    result = confirm(case, draft_of(recorded))
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    assert (put_back["amount_usd_cents"], result["debt_usd_cents"]) == (250, 150)
    assert (available(url, credit), outstanding(url, line)) == (0, 150)
    assert (
        value(url, "SELECT customer_id FROM app.invoices WHERE id=%s", invoice)
        == (case["co_signer"])
    )
    assert outstanding(url, case["signer_line"]) == 0
    reconciled(url, invoice)


def test_a_charge_reduction_s_adjustment_is_reversed_and_owes_exactly_what_it_removed(
    migrated_database_url: str,
) -> None:
    """Owner answer (b) to Q-2026-10-16-119: after closure a CHARGE_REDUCTION correction removed
    500 of the Primary Tenant's unpaid 1,500 key card line by mistake. The Adjustment reversal
    correction reverses that Adjustment: the line owes 1,500 again, nothing is put back (the
    reduction released nothing), and the reversal is linked to the new correction. The 10f-1
    draft still refuses a correction's Adjustment."""
    url = migrated_database_url
    case = closed_case(url, signer_paid=1_000, credit_used=0)
    prop, human, line = case["prop"], case["human"], case["tenant_line"]
    invoice = invoice_of(url, line)
    assert outstanding(url, line) == 1_500
    reduced = corrections().record_charge_reduction(
        prop,
        RecordChargeReductionCorrectionCommand(
            uuid4(), case["settlement"], invoice, line, 500, "The key card was charged twice"
        ),
        actor=preparer(human, prop),
    )
    corrections().confirm_charge_reduction(
        prop, UUID(str(reduced["draft_id"])), actor=approver(human, prop)
    )
    assert outstanding(url, line) == 1_000
    [(reduction,)] = rows(
        url,
        "SELECT id FROM app.invoice_adjustments WHERE invoice_line_id=%s "
        "AND adjustment_type='CREDIT'",
        line,
    )
    reduction = UUID(str(reduction))
    assert refusal(prop, human, reduction) == (
        "55000",
        "An Adjustment of a post-settlement correction is not reversed by an Adjustment "
        "reversal draft",
    )
    recorded = record(case, reduction)
    source = source_of(recorded)
    assert (
        source["charge_reduction"],
        source["releases"],
        source["put_back_usd_cents"],
        source["debt_usd_cents"],
        source["amount_usd_cents"],
    ) == (True, [], 0, 0, 500)
    result = confirm(case, draft_of(recorded))
    assert (result["restored_usd_cents"], result["put_backs"], result["debt_usd_cents"]) == (
        500,
        [],
        0,
    )
    assert outstanding(url, line) == 1_500
    correction = UUID(str(cast(dict[str, Any], result["settlement_correction"])["id"]))
    assert effects(url, correction) == [
        (1, UUID(str(result["invoice_adjustment_reversal_id"])), None)
    ]
    reconciled(url, invoice)


def test_refusals_waiting_drafts_stale_drafts_and_withdrawal(
    migrated_database_url: str,
) -> None:
    """An open Settlement refuses the correction. A 10f-1 draft recorded before the closure is
    refused at its confirm after the closure and stays pending; while it waits, the correction is
    refused; after its withdrawal the correction is recorded. A reused key, a second waiting
    draft, another Lease's Adjustment, a REFUND correction's Adjustment and a READ COMMITTED
    breach are refused; an exact repeat replays; a draft whose Invoice changed is stale and stays
    pending; the 10f-1 recorder still refuses a closed Settlement's Adjustment. Since sub-slice
    10h-3 a waiting 10f-1 draft blocks the closure, so the draft recorded before it is written by
    hand after it."""
    url = migrated_database_url
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    prop, human = case["prop"], case["human"]
    adjustment, invoice, line = lease_adjustment(url, case["lease"])
    with pytest.raises(AdjustmentReversalConflictError) as still_open:
        record(case, adjustment)
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    signer_invoice = invoice_of(url, case["signer_line"])
    pay_line(url, prop, human, case["co_signer"], signer_invoice, case["signer_line"], 1_000)
    # Since sub-slice 10h-3 a waiting 10f-1 draft blocks the closure (asserted in a rolled-back
    # recording), so the draft recorded before it is written by hand after it.
    held_id = uuid4()
    held = recorded_then_rolled_back(
        url,
        f"SELECT {EARLY_RECORD.split('(')[0]}(%s,%s,%s,%s,%s,'invoices.adjust')",
        (prop, human, held_id, adjustment, EARLY_REASON),
        draft=held_id,
        prop=prop,
        actor=human,
        settlement=case["settlement"],
    )
    confirm_settlement(
        case,
        record_settlement(
            case,
            (SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),),
            pet_remainder=STAFF,
        ),
    )
    early = {"draft_id": str(written_after_closure(url, prop, held))}
    # The 10f-1 source's refusal is part of its digest, so after the closure the 10f-1 draft is
    # stale (P5S02) and stays pending (review round 1).
    with pytest.raises(AdjustmentReversalStaleDraftError) as early_stale:
        early_reversals().confirm(prop, UUID(str(early["draft_id"])), actor=approver(human, prop))
    assert cause(early_stale) == (
        "P5S02",
        "The Adjustment reversal draft is stale; its sources changed",
    )
    assert drafts().get(prop, UUID(str(early["draft_id"])), actor=approver(human, prop))[
        "state"
    ] == ("PENDING")
    assert refusal(prop, human, adjustment) == ("55000", CLOSED)
    with pytest.raises(AdjustmentReversalConflictError) as waiting:
        record(case, adjustment)
    assert cause(waiting) == ("55000", WAITING)
    drafts().withdraw(
        prop,
        UUID(str(early["draft_id"])),
        "Recorded before the closure",
        prepare_capability="invoices.adjust",
        actor=person(human, prop, "invoices.adjust"),
    )
    first = command(case["settlement"], adjustment)
    recorded = reversals_record(case, first)
    assert reversals_record(case, first) == recorded
    with pytest.raises(AdjustmentReversalKeyReused):
        reversals_record(
            case,
            command(
                case["settlement"],
                adjustment,
                reason="Other",
                idempotency_key=first.idempotency_key,
            ),
        )
    with pytest.raises(AdjustmentReversalConflictError) as second:
        record(case, adjustment)
    assert cause(second) == ("55000", WAITING)
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as isolation:
            connection.execute(
                f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                (prop, human, draft_of(recorded)),
            )
        connection.rollback()
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    # The decision keeps a variant's own result keys, and the framework keys always win; a
    # result that is not an object is refused (round 1 security note 1). Rolled back.
    with psycopg.connect(url) as owner:
        with pytest.raises(psycopg.Error) as not_an_object:
            owner.execute(
                "SELECT app.begin_settlement_correction(%s,%s,%s,'financial.approve','[]'::jsonb)",
                (prop, human, draft_of(recorded)),
            )
        owner.rollback()
        assert not_an_object.value.sqlstate == "22023"
        correction = owner.execute(
            "SELECT app.begin_settlement_correction(%s,%s,%s,'financial.approve',"
            "jsonb_build_object('transaction_id','1','settlement_correction_id','x',"
            "'final_settlement_id','y','marker','kept'))",
            (prop, human, draft_of(recorded)),
        ).fetchone()
        assert owner.execute(
            "SELECT result->>'transaction_id'=pg_current_xact_id()::text,"
            "result->>'settlement_correction_id',result->>'final_settlement_id',"
            "result->>'marker' FROM app.financial_draft_decisions WHERE draft_id=%s",
            (draft_of(recorded),),
        ).fetchone() == (
            True,
            str(correction[0] if correction else None),
            str(case["settlement"]),
            "kept",
        )
        owner.rollback()
    assert drafts().get(prop, draft_of(recorded), actor=approver(human, prop))["state"] == (
        "PENDING"
    )
    with pytest.raises(AdjustmentReversalNotFoundError):
        record(case, uuid4())
    # Another Lease of the same Property: its Adjustment is not this Settlement's to reverse.
    other = two_signer_case(url)
    other_adjustment, _, _ = lease_adjustment(url, other["lease"])
    with pytest.raises(AdjustmentReversalConflictError) as elsewhere:
        record(case, other_adjustment)
    assert cause(elsewhere) == (
        "55000",
        "The Adjustment is not on an Invoice of this Final Settlement's Lease",
    )
    # A REFUND correction of 100 of the paid line changes the Invoice: the waiting draft is
    # stale and stays pending; the REFUND's own Adjustment is refused (Q-2026-10-16-119 (b)).
    refund = corrections().record_refund(
        prop,
        RecordRefundCorrectionCommand(
            uuid4(),
            case["settlement"],
            invoice,
            line,
            100,
            case["cash"],
            "Cash at the office",
            "The replacement key was charged too much",
        ),
        actor=preparer(human, prop),
    )
    corrections().confirm_refund(prop, UUID(str(refund["draft_id"])), actor=approver(human, prop))
    with pytest.raises(AdjustmentReversalStaleDraftError):
        confirm(case, draft_of(recorded))
    assert drafts().get(prop, draft_of(recorded), actor=approver(human, prop))["state"] == (
        "PENDING"
    )
    assert reversed_rows(url, adjustment) == []
    [(refunded,)] = rows(
        url,
        "SELECT a.id FROM app.invoice_adjustments a JOIN app.settlement_correction_effects e "
        "ON e.invoice_adjustment_id=a.id WHERE a.invoice_line_id=%s",
        line,
    )
    with pytest.raises(AdjustmentReversalConflictError) as refund_adjustment:
        record(case, UUID(str(refunded)))
    assert cause(refund_adjustment) == ("55000", OTHER_CORRECTION)
    # The preparer withdraws the stale correction draft and records it again (review round 1):
    # the reversal restores 400 and puts the unused 400 Credit back, so the line owes nothing.
    withdrawn = drafts().withdraw(
        prop,
        draft_of(recorded),
        "Recorded before the Refund correction",
        prepare_capability="final_settlements.prepare",
        actor=preparer(human, prop),
    )
    assert withdrawn["state"] == "WITHDRAWN"
    again = confirm(case, draft_of(record(case, adjustment)))
    assert (again["restored_usd_cents"], again["debt_usd_cents"]) == (400, 0)
    assert (outstanding(url, line), available(url, case["credit"])) == (0, 0)
    reconciled(url, invoice)


def test_a_resolution_s_adjustment_is_refused_by_the_correction_too(
    hand_back_database: str,  # noqa: F811
) -> None:
    """Q-2026-10-16-118 point 2 (a) also holds for the correction: a hand-back resolution's
    credit Adjustment stays with its resolution, and nothing is written. The Settlement is only
    started (the hand-back fixture does not close it): the resolution refusal comes before the
    open-Settlement refusal in the source, so it is the one shown."""
    url = hand_back_database
    scenario = lease_with_invoices(url, (AUGUST,))
    august = scenario.invoices[AUGUST]
    [(rent, _, _)] = hand_back_lines(url, august)
    hand_back_pay(url, scenario, august, rent, 20_000)
    hand_back(url, scenario, date(2026, 8, 4))
    hand_back_invoices().resolve_hand_back_rent(
        scenario.prop,
        august,
        ResolveHandBackRentCommand(
            uuid4(), "CREDIT_ADJUSTMENT", 60_000, "Unpaid rest", hand_back_version(url, august)
        ),
        actor=hand_back_staff(scenario.human, scenario.prop),
    )
    [(adjustment,)] = rows(
        url,
        "SELECT id FROM app.invoice_adjustments WHERE invoice_line_id=%s",
        rent,
    )
    case = {
        "prop": scenario.prop,
        "human": scenario.human,
        "settlement": start(scenario.prop, scenario.human, scenario.lease),
    }
    with pytest.raises(AdjustmentReversalConflictError) as resolution:
        record(case, UUID(str(adjustment)))
    assert cause(resolution) == (
        "55000",
        "An Adjustment that a resolution wrote is not reversed by an Adjustment reversal draft",
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='SETTLEMENT_CORRECTION' "
            "AND payload->>'variant'='ADJUSTMENT_REVERSAL'",
        )
        == 0
    )


def listed_correction_put_back(
    url: str,
    prop: UUID,
    human: UUID,
    adjustment: UUID,
    result: dict[str, Any],
    put_back: dict[str, Any],
    invoice: UUID,
    variant: str,
    binding: str,
) -> psycopg.Error | None:
    """As the table owner, in a transaction that is always rolled back: a hand-written
    SETTLEMENT_CORRECTION draft of the variant, with no correction header and no effect link,
    has a confirmed decision that names the stored reversal and lists a new labelled put-back of 1
    from the stored put-back's Credit and release; that put-back is written on the Adjustment's
    line and the deferred checks run. The decision is of this transaction (THIS_TRANSACTION),
    names the transaction before it (OTHER_TRANSACTION), or is dated before this transaction
    began (BEFORE_THIS_TRANSACTION, written directly into the decisions table)."""
    application, draft = uuid4(), uuid4()
    decision_result = (
        "jsonb_build_object('invoice_adjustment_reversal_id',%s::text,"
        "'invoice_adjustment_id',%s::text,'put_backs',jsonb_build_array("
        "jsonb_build_object('credit_application_id',%s::text,"
        "'customer_credit_id',%s::text,'invoice_credit_excess_release_id',%s::text,"
        "'amount_usd_cents',1)),'debt_usd_cents',0,'transaction_id',"
        + (
            "(pg_current_xact_id()::text::bigint-1)::text)"
            if binding == "OTHER_TRANSACTION"
            else "pg_current_xact_id()::text)"
        )
    )
    values = (
        str(result["invoice_adjustment_reversal_id"]),
        adjustment,
        application,
        str(put_back["customer_credit_id"]),
        str(put_back["invoice_credit_excess_release_id"]),
    )
    line = value(url, "SELECT invoice_line_id FROM app.invoice_adjustments WHERE id=%s", adjustment)
    with psycopg.connect(url) as connection:
        try:
            connection.execute(
                "SELECT app.insert_financial_draft(%s,%s,%s,'SETTLEMENT_CORRECTION',"
                "'final_settlements.prepare',jsonb_build_object('variant',%s::text,"
                "'invoice_adjustment_id',%s::text),'settlement-correction:test',"
                "'A correction written by hand')",
                (prop, human, draft, variant, adjustment),
            )
            if binding == "BEFORE_THIS_TRANSACTION":
                connection.execute(
                    "INSERT INTO app.financial_draft_decisions(draft_id,decision,reason,"
                    "decided_at,decided_by,authorization_reference,result) VALUES "
                    "(%s,'CONFIRMED',NULL,transaction_timestamp()-interval '1 second',%s,"
                    f"'financial.approve',{decision_result})",
                    (draft, human, *values),
                )
            else:
                connection.execute(
                    "SELECT app.confirm_financial_draft_record(%s,%s,%s,'SETTLEMENT_CORRECTION',"
                    f"{decision_result},'financial.approve')",
                    (prop, human, draft, *values),
                )
            connection.execute(
                "INSERT INTO app.customer_credit_applications(id,customer_credit_id,"
                "target_kind,invoice_id,amount_usd_cents,within_invoice_basis,occurred_at,"
                "actor_id,authorization_reference) VALUES (%s,%s,'INVOICE',%s,1,%s,"
                "clock_timestamp(),%s,'credits.apply')",
                (application, str(put_back["customer_credit_id"]), invoice, LABEL, human),
            )
            connection.execute(
                "INSERT INTO app.customer_credit_application_details(id,"
                "customer_credit_application_id,invoice_line_id,obligation_kind,"
                "invoice_line_category_snapshot,applied_amount_usd_cents,attribution_basis,"
                "detail_sequence,calculation_trace) SELECT %s,%s,line.id,'INVOICE_LINE',"
                "line.category,1,%s,1,jsonb_build_object('invoice_adjustment_reversal_id',"
                "%s::text,'invoice_credit_excess_release_id',%s::text) "
                "FROM app.invoice_lines line WHERE line.id=%s",
                (uuid4(), application, LABEL, values[0], values[4], line),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        except psycopg.Error as error:
            return error
        finally:
            connection.rollback()
    return None


def test_a_correction_s_put_back_needs_its_link_and_this_transaction_s_decision(
    migrated_database_url: str,
) -> None:
    """Review round 1 (both reviewers; the 10f-1b room set-up): a Payment paid the whole Service
    line, a credit Adjustment released it as Credit, half of which paid the Rent line; the 10f-1
    reversal put the rest back, and after the Rent-line application is reversed the Credit holds
    the half and the release has room. A hand-written put-back of 1 listed by a confirmed 10f-1
    decision passes (the set-up is sound). Listed instead by a SETTLEMENT_CORRECTION decision of
    the variant ADJUSTMENT_REVERSAL with no effect link, it is refused by the deferred check
    (23514); with a decision of another transaction, one dated before this transaction, or one of
    the variant CHARGE_REDUCTION, the label insert trigger refuses it. Everything is rolled
    back."""
    url = migrated_database_url
    human, prop, invoice, rent, service, payment = rent_and_service_invoice(url)
    service_due = outstanding(url, service)
    part = service_due // 2
    pay_payment(prop, payment, invoice, service, service_due, human)
    effect = cast(
        dict[str, Any],
        adjust_credit(url, human, prop, invoice, service, service_due)["adjustment_effect"],
    )
    [credit] = [UUID(str(item)) for item in cast(list[str], effect["customer_credit_ids"])]
    credits().apply(
        prop,
        credit,
        credit_designated(invoice, rent, part),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    [adjustment] = adjustments(url, service)
    recorded = early_reversals().record(
        prop, early_request(adjustment), actor=early_preparer(human, prop)
    )
    result = early_reversals().confirm(
        prop, early_draft_id(recorded), actor=early_approver(human, prop)
    )
    [put_back] = cast(list[dict[str, Any]], result["put_backs"])
    [(rent_application,)] = rows(
        url,
        "SELECT id FROM app.customer_credit_applications WHERE customer_credit_id=%s "
        "AND within_invoice_basis='CUSTOMER_DESIGNATED'",
        credit,
    )
    credits().reverse_application(
        prop,
        UUID(str(rent_application)),
        ReverseCreditApplicationCommand(uuid4(), "Applied to the wrong line"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert available(url, credit) == part
    assert (
        listed_put_back(
            url, prop, human, adjustment, result, put_back, invoice, service, "THIS_TRANSACTION"
        )
        is None
    )
    expected = {
        ("ADJUSTMENT_REVERSAL", "THIS_TRANSACTION"): MESSAGE,
        ("ADJUSTMENT_REVERSAL", "OTHER_TRANSACTION"): LABEL_REFUSED,
        ("ADJUSTMENT_REVERSAL", "BEFORE_THIS_TRANSACTION"): LABEL_REFUSED,
        ("CHARGE_REDUCTION", "THIS_TRANSACTION"): LABEL_REFUSED,
    }
    for (variant, binding), message in expected.items():
        refused = listed_correction_put_back(
            url, prop, human, adjustment, result, put_back, invoice, variant, binding
        )
        assert refused is not None, (variant, binding)
        assert (refused.sqlstate, refused.diag.message_primary) == ("23514", message), (
            variant,
            binding,
        )
    assert outstanding(url, service) == part and available(url, credit) == part
    reconciled(url, invoice)


def test_settlement_adjustment_reversals_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; the
    migration adds only its functions, patches only the 10f-1 result and the three 10f-1b
    put-back checks, keeps their privileges and settings, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial" and function in (RECORD, CONFIRM),), (
                    function,
                    role,
                )
            definer = connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone()
            assert definer == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261220_146"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            relations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
        return functions, relations, triggers

    with _temporary_migration_database("settlement_adjustment_reversal") as temporary:
        alembic_command.upgrade(config, "20261220_146")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
