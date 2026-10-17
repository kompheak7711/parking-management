"""The pay-back count: a recovery counts as returned money only while its charge stands (V1-056
sub-slice 10e-2b-4b-1).

Owner answer (a) to Q-2026-10-17-125: a recovery counts as money that came back only while its
charge stands. If the charge is later forgiven by a CHARGE_REDUCTION, a credit Adjustment or a
VOID, it stops counting; an Adjustment reversal or a later Invoice of the same charge makes it count
again exactly as before. One rule for a Pet Refund-review Refund's recovery (sub-slice 10e-2b-4a)
and for a recovery that undoes another Refund's payout (sub-slice 10e-2d): the recovery counts at
its own time by what still stands of its charge now. Owner answer 5 to the 10e-2b-4a report:
with this answer the corrected receipt's own Pet Deposit can forfeit on the termination ground
again, so that case has a real-path test here.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.final_settlement import FinalSettlementStaleDraftError, SettlementDepositStep
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    IssueInvoiceCommand,
    VoidInvoiceCommand,
)
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    settlement_correction_draft_id,
)
from refund_test_support import create_pet_refund
from test_adjustment_reversal_migration import adjustments, reversals
from test_adjustment_reversal_migration import approver as reversal_approver
from test_adjustment_reversal_migration import draft_id as reversal_draft_id
from test_adjustment_reversal_migration import preparer as reversal_preparer
from test_adjustment_reversal_migration import request as reversal_request
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import invoices, version
from test_credit_migration import actor
from test_debit_adjustment_line_block_migration import debit
from test_deposit_migration import seed_historical_deposit_receipt
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_migration import held, one, outstanding
from test_final_settlement_preview_migration import pay
from test_invoice_migration import invoice_api_actor
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_move_migration import rows, value
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, reconciled, request, returns
from test_payment_return_migration import preparer as return_preparer
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refund_service
from test_settlement_adjustment_reversal_migration import confirm as confirm_restoration
from test_settlement_adjustment_reversal_migration import draft_of
from test_settlement_adjustment_reversal_migration import record as record_restoration
from test_settlement_charge_reduction_migration import invoice_of, reduction
from test_settlement_charge_reduction_migration import record as record_reduction
from test_settlement_deposit_receipt_correction_migration import (
    REASON,
    available,
    confirm,
    payload,
    record,
)
from test_settlement_deposit_receipt_correction_migration import request as receipt_request
from test_settlement_deposit_receipt_forfeiture_migration import forfeitures, path, termination_date
from test_settlement_deposit_receipt_payback_forfeiture_migration import (
    correct_pet_receipt,
    count_as,
    payback_count,
    payback_ground_case,
    record_correction,
    settlement_pet_refund,
)
from test_settlement_deposit_receipt_recovery_line_migration import recovery_line
from test_settlement_extra_charge_migration import approving, corrections, state
from test_settlement_returned_payment_migration import receipt_payment

REVISION = "20261226_152"
NEW = {"app.refund_recovery_standing_at(uuid,timestamp with time zone)"}
PATCHED = {"app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)"}


def reduce_charge(case: dict[str, Any], line: UUID, amount: int) -> None:
    """A CHARGE_REDUCTION correction of an unpaid recovery charge line, recorded and confirmed."""
    draft = record_reduction(
        case, reduction(case["settlement"], invoice_of(case["url"], line), line, amount)
    )
    corrections().confirm_charge_reduction(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def open_lease_recovery(url: str, refund: UUID) -> tuple[UUID, UUID, UUID, UUID]:
    """The RECOVERED_BY_CHARGE row of a Refund, its charge's line, Invoice and obligation."""
    found = one(
        url,
        "SELECT recovery.id,line.id,line.invoice_id,recovery.recovery_obligation_id "
        "FROM app.refund_corrections recovery JOIN app.invoice_lines line "
        "ON line.authorized_obligation_id=recovery.recovery_obligation_id "
        "WHERE recovery.refund_id=%s AND recovery.correction_kind='RECOVERED_BY_CHARGE'",
        refund,
    )
    return (
        UUID(str(found[0])),
        UUID(str(found[1])),
        UUID(str(found[2])),
        UUID(str(found[3])),
    )


def standing(url: str, recovery: UUID) -> int:
    return int(
        value(url, "SELECT app.refund_recovery_standing_at(%s,'infinity'::timestamptz)", recovery)
    )


def restore_reduction(case: dict[str, Any], line: UUID) -> None:
    """The 10f-2 ADJUSTMENT_REVERSAL correction of the one CHARGE_REDUCTION Adjustment of a line
    (owner answer (b) to Q-2026-10-16-119), recorded and confirmed: the charge stands again."""
    [adjustment] = adjustments(case["url"], line)
    confirm_restoration(case, draft_of(record_restoration(case, adjustment)))


def billed_again(
    url: str, prop: UUID, human: UUID, obligation: UUID, meanwhile: tuple[UUID, UUID, int]
) -> None:
    """The same charge billed again after a VOID: while its Invoice is a DRAFT the charge does not
    stand (it is not owed yet), and once the Invoice is issued it does."""
    recovery, deposit, count = meanwhile
    who = invoice_staff(human, prop)
    draft = invoices().create_draft(prop, CreateInvoiceDraftCommand(uuid4(), obligation), actor=who)
    assert (standing(url, recovery), payback_count(url, deposit)) == (0, count)
    issued = invoices().issue(
        prop,
        UUID(str(draft["id"])),
        IssueInvoiceCommand(uuid4(), cast(int, draft["version"])),
        actor=who,
    )
    assert issued["status"] == "UNPAID"


def written(url: str, case: dict[str, Any]) -> tuple[Any, ...]:
    """What a refused receipt correction must leave as it was: the Pet Deposit's forfeitures,
    receipts and applications, and the Settlement's corrections."""
    return (
        forfeitures(url, case["pet"]),
        active_receipt(url, case["pet"]),
        one(url, "SELECT count(*) FROM app.deposit_applications WHERE deposit_id=%s", case["pet"]),
        one(
            url,
            "SELECT count(*) FROM app.settlement_corrections WHERE final_settlement_id=%s",
            case["settlement"],
        ),
    )


def active_charge_line(url: str, obligation: UUID) -> tuple[UUID, UUID]:
    """The line and Invoice of a charge on its one Invoice that is not VOID."""
    found = one(
        url,
        "SELECT line.id,line.invoice_id FROM app.invoice_lines line "
        "JOIN app.invoices invoice ON invoice.id=line.invoice_id "
        "WHERE line.authorized_obligation_id=%s AND invoice.status<>'VOID'",
        obligation,
    )
    return UUID(str(found[0])), UUID(str(found[1]))


def recovery_rows(url: str, refund: UUID) -> int:
    return int(
        value(
            url,
            "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s "
            "AND correction_kind='RECOVERED_BY_CHARGE'",
            refund,
        )
    )


def active_receipt(url: str, deposit: UUID) -> UUID:
    return UUID(
        str(
            value(
                url,
                "SELECT receipt.id FROM app.deposit_receipts receipt WHERE receipt.deposit_id=%s "
                "AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal "
                "WHERE reversal.deposit_receipt_id=receipt.id)",
                deposit,
            )
        )
    )


def applications(url: str, result: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ]


def test_a_recovery_charge_reduced_after_closure_stops_counting(
    migrated_database_url: str,
) -> None:
    """After closure, on the 10e-2d set-up B/C: the seeded Pet receipt's correction recovers the
    Final Settlement's 3,000 Pet Refund and the Pet Refund-review Refund's 2,000 by charges, so the
    count is 5,000 (the 3,000 payout undone and the 2,000 charged back, owner answer (a) to
    Q-2026-10-17-123). A CHARGE_REDUCTION of 1,000 of the Settlement Refund's 3,000 recovery charge
    makes 1,000 of that payout count again from its time (4,000; review round 1: a part of the
    charge); one of 1,500 of the review Refund's recovery charge counts that recovery as 500
    (2,500); one of the Settlement Refund's other 2,000 gives 500. A right 5,000 Pet receipt from
    the Security receipt's correction then keeps only 500 as pay-back money (DL-032, onto the
    Security Refund's 10,000 recovery charge after the Security Deposit's 5,000) and forfeits
    4,500 on BR-DEP-022; the count is 0 afterwards and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url)
    security, pet, lease = case["security"], case["pet"], case["lease"]
    settled = settlement_pet_refund(url, pet)
    correct_pet_receipt(case)
    settled_line, *_ = recovery_line(url, settled)
    review_line, *_ = recovery_line(url, case["review_refund"])
    assert (outstanding(url, settled_line), outstanding(url, review_line)) == (3_000, 2_000)
    assert payback_count(url, pet) == 5_000
    reduce_charge(case, settled_line, 1_000)
    assert (outstanding(url, settled_line), payback_count(url, pet)) == (2_000, 4_000)
    reduce_charge(case, review_line, 1_500)
    assert (outstanding(url, review_line), payback_count(url, pet)) == (500, 2_500)
    reduce_charge(case, settled_line, 2_000)
    assert (outstanding(url, settled_line), payback_count(url, pet)) == (0, 500)
    # The receipt correction's own-Deposit count of the Pet Deposit follows the same rule.
    assert count_as(url, pet, None, 0, True) == 3_500
    draft = record_correction(case, 5_000, 5_000)
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 4_500,
            "governing_rule": "BR-DEP-022",
            "basis": "TERMINATION_GROUND",
            "reason": REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 5_000, str(pet): 500}
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert forfeitures(url, pet) == [
        (
            4_500,
            REASON,
            "deposits.dispose",
            case["person"],
            termination_date(url, lease),
            False,
            "BR-DEP-022",
            correction,
        )
    ]
    real_line, *_ = recovery_line(url, case["refund"])
    assert applications(url, result) == [(security, real_line, 5_000), (pet, real_line, 500)]
    assert (outstanding(url, real_line), result["refund_ids"]) == (4_500, [])
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (0, 0, "KEPT")
    reconciled(url, case["customer"])


def test_a_recovery_charge_forgiven_on_an_open_lease_stops_counting_until_it_stands_again(
    migrated_database_url: str,
) -> None:
    """Before closure, on the sub-slice 10e-1c path (a Pet Deposit seeded with 20,000 from one
    Payment, as the committed pay-back fixtures do): a 15,000 Pet Refund-review Refund is paid and
    the Payment's return recovers it by an ordinary charge on the signed Lease, so the count is
    15,000. A credit Adjustment of 4,000 of the charge's line lowers it to 11,000; the reversal of
    that Adjustment (the 10f-1 draft, confirmed under financial.approve) puts it back to 15,000; a
    VOID of the charge's Invoice takes all of it (0); the same charge billed again on a later
    Invoice counts again only once that Invoice is issued (15,000). The standing function shows
    each step; a VOID Invoice with no void event (hand-built, rolled back) counts as VOID (fail
    closed). Review round 1 (security set-ups; the recovery counts at its own time by what stands
    now): a second Pet receipt of 15,000 (seeded, from another Payment) pays a later 10,000 Pet
    Refund-review Refund (5,000); a VOID of the charge's Invoice and the charge billed again give 0
    and then 5,000 again (not 15,000: the later Refund paid that money out); 3,000 of the later
    Refund comes back (8,000); a credit Adjustment of the whole charge then leaves exactly that
    3,000 (the forgiveness never takes money that came back later)."""
    url = migrated_database_url
    human, prop, customer, _, deposit, review = qualified(url)
    refund = refund_id(
        create_pet_refund(
            refund_service(),
            prop,
            pet_refund_command(deposit, review, 15_000),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    assert payback_count(url, deposit) == 0
    payment = receipt_payment(url, deposit)
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    recovery, line, invoice, obligation = open_lease_recovery(url, refund)
    assert (held(url, deposit), outstanding(url, line), standing(url, recovery)) == (
        0,
        15_000,
        15_000,
    )
    assert payback_count(url, deposit) == 15_000
    adjust_credit(url, human, prop, invoice, line, 4_000)
    assert (standing(url, recovery), payback_count(url, deposit)) == (11_000, 11_000)
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(
        prop, reversal_request(adjustment), actor=reversal_preparer(human, prop)
    )
    reversals().confirm(prop, reversal_draft_id(recorded), actor=reversal_approver(human, prop))
    assert (standing(url, recovery), payback_count(url, deposit)) == (15_000, 15_000)
    invoices().void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Issued in error", version(url, invoice)),
        actor=invoice_api_actor(human, prop),
    )
    assert (standing(url, recovery), payback_count(url, deposit)) == (0, 0)
    void_time = "SELECT occurred_at FROM app.invoice_void_events WHERE invoice_id=%s"
    [void_at] = one(url, void_time, invoice)
    just_before = "SELECT app.refund_recovery_standing_at(%s,%s-interval '1 microsecond')"
    assert one(url, just_before, recovery, void_at) == (15_000,)
    with psycopg.connect(url) as connection:
        # Hand-built and rolled back: the VOID Invoice without its void event still counts as VOID,
        # also just before the VOID's time.
        connection.execute("ALTER TABLE app.invoice_void_events DISABLE TRIGGER USER")
        connection.execute("DELETE FROM app.invoice_void_events WHERE invoice_id=%s", (invoice,))
        assert connection.execute(
            "SELECT app.refund_recovery_standing_at(%s,'infinity'::timestamptz),"
            "app.lease_deposit_payback_count(%s)",
            (recovery, deposit),
        ).fetchone() == (0, 0)
        assert connection.execute(just_before, (recovery, void_at)).fetchone() == (0,)
        connection.rollback()
    void_events = "SELECT count(*) FROM app.invoice_void_events WHERE invoice_id=%s"
    assert one(url, void_events, invoice) == (1,)
    billed_again(url, prop, human, obligation, (recovery, deposit, 0))
    assert (standing(url, recovery), payback_count(url, deposit)) == (15_000, 15_000)
    seed_historical_deposit_receipt(
        url, deposit_id=deposit, actor_id=human, amount_usd_cents=15_000
    )
    later = refund_id(
        create_pet_refund(
            refund_service(),
            prop,
            pet_refund_command(deposit, review, 10_000),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    assert (held(url, deposit), payback_count(url, deposit)) == (5_000, 5_000)
    line, invoice = active_charge_line(url, obligation)
    invoices().void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Issued in error", version(url, invoice)),
        actor=invoice_api_actor(human, prop),
    )
    assert (standing(url, recovery), payback_count(url, deposit)) == (0, 0)
    billed_again(url, prop, human, obligation, (recovery, deposit, 0))
    assert (standing(url, recovery), payback_count(url, deposit)) == (15_000, 5_000)
    refund_service().verify_usd_return(
        prop, later, returned(3_000), actor=actor(human, prop, "refunds.correct")
    )
    assert payback_count(url, deposit) == 8_000
    line, invoice = active_charge_line(url, obligation)
    adjust_credit(url, human, prop, invoice, line, 15_000)
    assert (standing(url, recovery), payback_count(url, deposit)) == (0, 3_000)
    reconciled(url, customer)


def test_the_own_pet_deposit_forfeits_on_the_ground_once_its_review_recovery_is_forgiven(
    migrated_database_url: str,
) -> None:
    """Owner answer 5 to the 10e-2b-4a report, on the real path (the follow-up review's route in
    ops/reviews/V1-056-slice-10e-2b-4a-review-refund-recovery.md, made concrete): set-up B/C with
    a 5,000 Pet receipt from the Security receipt's correction (the count 5,000 covers it, nothing
    forfeited, it pays the Security Refund's recovery charge). A CHARGE_REDUCTION of the whole
    unpaid 2,000 recovery charge of the Pet Refund-review Refund lowers the count without changing
    what the Pet Deposit paid, so the Pet receipt's own-Deposit count is 3,000. A receipt correction
    of that 5,000 Pet receipt itself, with a 4,500 right receipt into the same never-forfeited Pet
    Deposit, forfeits 1,500 on BR-DEP-022 (`TERMINATION_GROUND`, linked to the correction; the
    forfeiture writer's exact check passes) and the pay-back 3,000 follows DL-032 onto the
    Settlement Refund's 3,000 recovery charge (staff steps). The Payment keeps the other 500, the
    count is 0 afterwards and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url)
    security, pet, lease = case["security"], case["pet"], case["lease"]
    settled = settlement_pet_refund(url, pet)
    correct_pet_receipt(case)
    confirm(case, record_correction(case, 5_000, 5_000))
    assert forfeitures(url, pet) == []
    settled_line, *_ = recovery_line(url, settled)
    review_line, *_ = recovery_line(url, case["review_refund"])
    real_line, *_ = recovery_line(url, case["refund"])
    assert (
        outstanding(url, settled_line),
        outstanding(url, review_line),
        outstanding(url, real_line),
    ) == (3_000, 2_000, 0)
    assert (count_as(url, pet, None, 0, True), payback_count(url, pet)) == (5_000, 0)
    reduce_charge(case, review_line, 2_000)
    assert (count_as(url, pet, None, 0, True), payback_count(url, pet)) == (3_000, 0)
    receipt = active_receipt(url, pet)
    payment = UUID(
        str(value(url, "SELECT payment_id FROM app.deposit_receipts WHERE id=%s", receipt))
    )
    before_available = available(url, payment)
    base = receipt_request(case, receipt, receipts=(CorrectionDepositReceipt(pet, 4_500),))
    draft = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    steps = (SettlementDepositStep(PET_REST, pet, LINE, settled_line, 3_000),)
    assert record(case, replace(base, steps=steps, pet_remainder=STAFF)) == draft
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 1_500,
            "governing_rule": "BR-DEP-022",
            "basis": "TERMINATION_GROUND",
            "reason": REASON,
        }
    ]
    assert (
        stored["plan_overlay"]["deposits_after"],
        stored["plan_overlay"]["corrected_deposit_id"],
    ) == ({str(pet): 3_000}, str(pet))
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert forfeitures(url, pet) == [
        (
            1_500,
            REASON,
            "deposits.dispose",
            case["person"],
            termination_date(url, lease),
            False,
            "BR-DEP-022",
            correction,
        )
    ]
    assert applications(url, result) == [(pet, settled_line, 3_000)]
    assert (
        outstanding(url, settled_line),
        outstanding(url, review_line),
        outstanding(url, real_line),
    ) == (0, 0, 5_000)
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (0, 0, "KEPT")
    assert held(url, security) == 0
    assert available(url, payment) == before_available + 500
    # The forgiven review recovery is not charged back again (review round 1 note).
    assert recovery_rows(url, case["review_refund"]) == 1
    reconciled(url, case["customer"])


def bc_case(url: str) -> dict[str, Any]:
    """Set-up B/C with a 5,000 Pet receipt from the Security receipt's correction (nothing
    forfeited; it pays the Security Refund's recovery charge): the Pet Deposit's own-Deposit count
    is 5,000 and its count 0; the two recovery charges of its Refunds are unpaid."""
    case = payback_ground_case(url)
    pet = case["pet"]
    correct_pet_receipt(case)
    confirm(case, record_correction(case, 5_000, 5_000))
    case["settled_line"] = recovery_line(url, settlement_pet_refund(url, pet))[0]
    case["review_line"] = recovery_line(url, case["review_refund"])[0]
    case["receipt"] = active_receipt(url, pet)
    assert (count_as(url, pet, None, 0, True), payback_count(url, pet)) == (5_000, 0)
    return case


def record_own_correction(case: dict[str, Any], steps: tuple[SettlementDepositStep, ...]) -> UUID:
    """A receipt correction of the 5,000 Pet receipt itself: really 4,500 Pet Deposit money."""
    base = receipt_request(
        case, case["receipt"], receipts=(CorrectionDepositReceipt(case["pet"], 4_500),)
    )
    draft = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    assert record(case, replace(base, steps=steps, pet_remainder=STAFF)) == draft
    return draft


def test_a_forgiven_then_restored_charge_counts_as_before_and_a_draft_between_is_stale(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent blocker B1 and should-fix S3a): on bc_case, a receipt
    correction of the Pet receipt with a 4,500 right receipt is recorded while the own-Deposit
    count is 5,000 (nothing forfeited; 3,000 and 1,500 onto the two recovery charges). A
    CHARGE_REDUCTION of the whole 2,000 review recovery charge lowers that count to 3,000, so the
    draft is stale at its confirm (P5S02) and writes nothing. The 10f-2 ADJUSTMENT_REVERSAL of the
    reduction's Adjustment then makes the charge stand again: the count is exactly as before the
    forgiveness (0, own-Deposit 5,000), although the 5,000 application paid that money out
    before the forgiveness."""
    url = migrated_database_url
    case = bc_case(url)
    pet = case["pet"]
    steps = (
        SettlementDepositStep(PET_REST, pet, LINE, case["settled_line"], 3_000),
        SettlementDepositStep(PET_REST, pet, LINE, case["review_line"], 1_500),
    )
    draft = record_own_correction(case, steps)
    assert "deposit_receipt_forfeitures" not in payload(url, draft)
    reduce_charge(case, case["review_line"], 2_000)
    assert (count_as(url, pet, None, 0, True), payback_count(url, pet)) == (3_000, 0)
    before = written(url, case)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, draft)
    assert (written(url, case), state(url, draft)) == (before, "PENDING")
    assert (forfeitures(url, pet), active_receipt(url, pet)) == ([], case["receipt"])
    restore_reduction(case, case["review_line"])
    [(recovery,)] = rows(
        url,
        "SELECT id FROM app.refund_corrections WHERE refund_id=%s "
        "AND correction_kind='RECOVERED_BY_CHARGE'",
        case["review_refund"],
    )
    assert standing(url, UUID(str(recovery))) == 2_000
    assert outstanding(url, case["review_line"]) == 2_000
    assert (count_as(url, pet, None, 0, True), payback_count(url, pet)) == (5_000, 0)


def test_a_restored_charge_makes_a_waiting_forfeiture_stale(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix S3b, the direction that would take the Customer's
    money): on bc_case, after a CHARGE_REDUCTION of the whole 2,000 review recovery charge, a
    receipt correction of the Pet receipt with a 4,500 right receipt is recorded with 1,500
    forfeited on BR-DEP-022 (own-Deposit count 3,000). The 10f-2 reversal of the reduction's
    Adjustment makes the count 5,000 again, so the draft is stale at its confirm (P5S02): nothing
    is forfeited and the receipt stays."""
    url = migrated_database_url
    case = bc_case(url)
    pet = case["pet"]
    reduce_charge(case, case["review_line"], 2_000)
    steps = (SettlementDepositStep(PET_REST, pet, LINE, case["settled_line"], 3_000),)
    draft = record_own_correction(case, steps)
    assert [
        item["amount_usd_cents"] for item in payload(url, draft)["deposit_receipt_forfeitures"]
    ] == [1_500]
    restore_reduction(case, case["review_line"])
    assert count_as(url, pet, None, 0, True) == 5_000
    before = written(url, case)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, draft)
    assert (written(url, case), state(url, draft)) == (before, "PENDING")
    assert (forfeitures(url, pet), active_receipt(url, pet)) == ([], case["receipt"])


def test_a_standing_charge_counts_at_most_the_recovered_amount_paid_or_not(
    migrated_database_url: str,
) -> None:
    """Review round 2 (both reviewers): on the 10e-1c open-Lease path the 15,000 recovery counts
    15,000. A DEBIT Adjustment of 2,000 on its line (17,000) counts nothing more (at most the
    recovered amount); a credit of 3,000 then forgives the part above the recovered amount first
    (14,000 stands and counts; implementer's reading, put to the owner with Q-2026-10-17-126); a
    DEBIT of 1,000 brings it back to 15,000; a Payment of 5,000 on the line changes nothing (a paid
    charge stands); a credit of 12,000 leaves a 3,000 obligation (2,000 of the Payment goes to the
    Customer's Credit), so 3,000 stands and counts. The ledger reconciles."""
    url = migrated_database_url
    human, prop, customer, _, deposit, review = qualified(url)
    refund = refund_id(
        create_pet_refund(
            refund_service(),
            prop,
            pet_refund_command(deposit, review, 15_000),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    payment = receipt_payment(url, deposit)
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    recovery, line, invoice, _ = open_lease_recovery(url, refund)

    def seen() -> tuple[int, int, int]:
        return outstanding(url, line), standing(url, recovery), payback_count(url, deposit)

    assert seen() == (15_000, 15_000, 15_000)
    debit(url, human, prop, invoice, line, 2_000)
    assert seen() == (17_000, 15_000, 15_000)
    adjust_credit(url, human, prop, invoice, line, 3_000)
    assert seen() == (14_000, 14_000, 14_000)
    debit(url, human, prop, invoice, line, 1_000)
    assert seen() == (15_000, 15_000, 15_000)
    pay(url, prop, human, customer, invoice, line, 5_000)
    assert seen() == (10_000, 15_000, 15_000)
    adjust_credit(url, human, prop, invoice, line, 12_000)
    assert seen() == (0, 3_000, 3_000)
    reconciled(url, customer)


def test_the_recovery_standing_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4b-1 adds one internal function (no grant to any application role or
    PUBLIC, SECURITY DEFINER with the fixed search path), changes only the pay-back count function
    (privileges, owner and settings kept; its body is exactly the old one with the module's two
    replacements), adds no constraint or trigger and is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261225_151"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert set(revision.module.INTERNAL) == NEW
    for function in NEW:
        assert one(
            migrated_database_url,
            "SELECT p.prosecdef,p.proconfig::text,"
            "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE'),"
            "p.proacl IS NOT NULL AND p.proacl::text !~ '(^|[{,])=X' "
            "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
            function,
        ) == (True, "{search_path=pg_catalog}", False, False, False, True), function

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str]]:
        functions = {
            str(row[0]): tuple(row[1:])
            for row in rows(
                database,
                "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'",
            )
        }
        others = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT 'constraint',c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("pet_payback_recovery_standing") as temporary:
        alembic_command.upgrade(config, "20261225_151")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions) | NEW
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        assert after_functions[function][1:] == before_functions[function][1:], function
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
