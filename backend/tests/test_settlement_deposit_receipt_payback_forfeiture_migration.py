"""Post-settlement correction: a forfeited right receipt keeps only the pay-back money the Customer
has not received yet (V1-056 sub-slice 10e-2d).

Owner answer (a) to Q-2026-10-12-93: a right receipt that a DEPOSIT_RECEIPT_CORRECTION forfeits
(sub-slice 10e-2c) into a Pet Deposit with returned Pet Refund-review money is forfeited only
beyond the pay-back count; the rest stays in the Deposit as the Customer's money and follows DL-032
in the same correction's plan (applied to debt, then refunded). When the count covers the whole
receipt nothing is forfeited, and a staff choice to forfeit again is refused (confirmed with the
answer to Q-2026-10-17-122). Owner answer (b) to Q-2026-10-17-122: the count holds only returned
money the Customer has not received yet; money the Final Settlement or a correction already applied
or refunded from the Deposit, and did not undo, is not paid back again.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_disposition_test_support import terminate_for_disposition
from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.deposit import (
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
)
from property_rental.final_settlement import FinalSettlementConflictError, SettlementDepositStep
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    deposit_receipt_recovery_line_id,
    settlement_correction_draft_id,
)
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_deposit_migration import create_pet, deposit_actor, seed_historical_deposit_receipt
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, start
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_pet_refund_migration import command as pet_command
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver
from test_settlement_deposit_receipt_correction_migration import (
    REASON,
    available,
    confirm,
    counts,
    payload,
    receipt_of,
    record,
    request,
    source_of,
)
from test_settlement_deposit_receipt_forfeiture_migration import (
    OUTCOME_REASON,
    forfeitures,
    path,
    termination_date,
)
from test_settlement_deposit_receipt_recovery_line_migration import owner_refusal, recovery_line
from test_settlement_deposit_receipt_rewrite_migration import receipts_of, targets_check
from test_settlement_extra_charge_migration import cause
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    disposition_of,
    record_reversal,
    reversal_command,
)
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import record as record_return
from test_settlement_refund_return_migration import return_command
from test_settlement_returned_payment_migration import receipt_payment, reconciled
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261223_149"
NEW = {"app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)"}
PATCHED = {
    "app.lease_deposit_payback_count(uuid)",
    "app.lease_deposit_payback_after_return(uuid,uuid,bigint)",
    "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)",
    "app.settlement_deposit_receipt_forfeitures(jsonb,text)",
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)",
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)",
}
NOTHING_BEYOND = "Nothing beyond the Customer's pay-back money is left to forfeit; choose DL-032"
ONLY_DL_032 = "Only a Deposit that follows DL-032 and holds money may be applied"
INVALID_OVERLAY = "Post-settlement correction overlay is invalid"
PLAN_RESULT = "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)"
COUNT_AS = "SELECT app.lease_deposit_payback_count_as(%s,%s,%s,%s)"


def payback_count(url: str, deposit: UUID) -> int:
    return int(value(url, "SELECT app.lease_deposit_payback_count(%s)", deposit))


def count_as(
    url: str, deposit: UUID, refund: UUID | None, amount: int, without_payouts: bool
) -> int:
    return int(value(url, COUNT_AS, deposit, refund, amount, without_payouts))


def paid_out(url: str, deposit: UUID) -> tuple[int, int]:
    """The Deposit's Refunds other than Pet Refund-review Refunds, and its Deposit applications."""
    return (
        int(
            value(
                url,
                "SELECT COALESCE(sum(usd_accounting_value_cents),0) FROM app.refunds "
                "WHERE source_deposit_id=%s AND pet_refund_review_id IS NULL",
                deposit,
            )
        ),
        int(
            value(
                url,
                "SELECT COALESCE(sum(amount_usd_cents),0) FROM app.deposit_applications "
                "WHERE deposit_id=%s",
                deposit,
            )
        ),
    )


def settlement_pet_refund(url: str, pet: UUID) -> UUID:
    """The Final Settlement's one Refund of the Pet Deposit."""
    return UUID(
        str(
            value(
                url,
                "SELECT id FROM app.refunds WHERE source_deposit_id=%s "
                "AND pet_refund_review_id IS NULL",
                pet,
            )
        )
    )


def payback_ground_case(url: str, forfeit_pet: bool = False) -> dict[str, Any]:
    """A signed Lease starting this month with its Security Deposit (10,000, received through the
    Reservation) and an approved Pet Deposit (20,000 required) holding 5,000 (seeded, as the
    committed pay-back fixtures do: no function records Pet Deposit money before closure). The pet
    leaves and a DL-053 review qualifies; while the Lease is signed the 5,000 is paid as a Pet
    Refund-review Refund and 3,000 of it comes back (pay-back count 3,000). The Initial Rent is
    paid; the Lease is terminated for pet noncompliance after three warnings (BR-DEP-022). The
    Security Deposit is forfeited through the draft and kept; the Pet Deposit holds only pay-back
    money (DL-032), so the Final Settlement refunds its 3,000 and is really closed with nothing
    owed; the Customer has then received the pay-back money, so the count is 0 (owner answer (b)
    to Q-2026-10-17-122). The kept Security Deposit is then refunded (10,000) by a
    FORFEITURE_REVERSAL correction. A correction approver is ready.

    With forfeit_pet (the review round 1 set-up of a staff choice to forfeit again): the Pet
    Deposit is seeded with 8,000 and holds 6,000 after the review; its 3,000 beyond the count is
    forfeited through the draft before the Security Deposit's; after the closure a
    FORFEITURE_REVERSAL correction of the Pet forfeiture refunds that 3,000 too, before the
    Security Deposit's."""
    source = signed_with_initial(url, this_month(url))
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    approval = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.lease_pet_approvals(id,lease_id,approved_date,"
            "deposit_required_by_signed_terms,pet_description,approved_at,approved_by) "
            "VALUES (%s,%s,%s,true,'Synthetic approved pet',clock_timestamp(),%s)",
            (approval, lease, day, human),
        )
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    who = deposit_actor(human, prop)
    pet, _ = create_pet(deposits, who, lease, approval, day)
    seed = 8_000 if forfeit_pet else 5_000
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=seed)
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), pet, day, "Pet permanently left")
    deposits.record_pet_departure(departure, actor=who)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        pet,
        30000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=who)
    review_refund = refund_id(
        create_pet_refund(
            refunds(),
            prop,
            pet_command(pet, review.review_id, 5_000),
            actor=refund_actor(human, prop, "refunds.create"),
        )
    )
    refunds().verify_usd_return(
        prop,
        review_refund,
        returned(3_000),
        actor=refund_actor(human, prop, "refunds.correct"),
    )
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate_for_disposition(url, deposits, lease, day)
    security = source["deposit"]
    if forfeit_pet:
        forfeit_through_draft(deposits, pet)
    forfeit_through_draft(deposits, security)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": security,
        "pet": pet,
        "invoice": source["invoice"],
        "rent_line": rent,
        "review_refund": review_refund,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    assert (held(url, pet), path(url, case, pet), payback_count(url, pet)) == (
        3_000,
        "DL_032",
        3_000,
    )
    confirm_settlement(case, record_settlement(case, (settlement_refund(case, "pet", 3_000),)))
    case["person"] = approver(url)
    # Owner answer (b) to Q-2026-10-17-122: the Settlement's Refund paid the pay-back money out.
    assert (held(url, pet), payback_count(url, pet)) == (0, 0)
    assert path(url, case, pet) == ("KEPT" if forfeit_pet else "NOTHING_HELD")
    # Sub-slice 10e-2b-4a (owner answer (a) to Q-2026-10-17-123): counted as a receipt
    # correction's own Deposit, the review Refund's 2,000 still to recover counts too.
    assert count_as(url, pet, None, 0, True) == 5_000
    if forfeit_pet:
        case["disposition"] = disposition_of(url, pet)
        confirm_reversal(
            case,
            record_reversal(case, reversal_command(case, settlement_refund(case, "pet", 3_000))),
        )
        # Every forfeiture of the Pet Deposit is reversed, so its path is DL-032 again.
        assert (held(url, pet), path(url, case, pet), payback_count(url, pet)) == (
            0,
            "DL_032",
            0,
        )
    case["disposition"] = disposition_of(url, security)
    reversal = confirm_reversal(
        case,
        record_reversal(case, reversal_command(case, settlement_refund(case, "security", 10_000))),
    )
    [paid] = reversal["refunds"]
    case["refund"] = UUID(str(paid["id"]))
    assert path(url, case, security) == "DL_032"
    return case


def record_correction(
    case: dict[str, Any],
    security_amount: int,
    pet_amount: int,
    pet_outcome: str | None = None,
) -> UUID:
    """The receipt correction: the Security Deposit's 10,000 receipt was really security_amount
    Security Deposit (staff choose DL-032) and pet_amount Pet Deposit (never forfeited, so staff
    choose nothing, unless pet_outcome names a choice). The plan applies the Security Deposit's
    new money and then the Pet Deposit's pay-back part, if any, to the 10,000 recovery charge's
    placeholder line (DL-032 order)."""
    security, pet = case["security"], case["pet"]
    kept = min(pet_amount, payback_count(case["url"], pet))
    base = request(
        case,
        receipt_of(case["url"], security),
        receipts=(
            CorrectionDepositReceipt(security, security_amount, "DL_032", OUTCOME_REASON),
            CorrectionDepositReceipt(pet, pet_amount)
            if pet_outcome is None
            else CorrectionDepositReceipt(pet, pet_amount, pet_outcome, OUTCOME_REASON),
        ),
    )
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, case["refund"])
    steps = [SettlementDepositStep(SECURITY, security, LINE, placeholder, security_amount)]
    if kept:
        steps.append(SettlementDepositStep(PET_REST, pet, LINE, placeholder, kept))
    draft = record(
        case,
        replace(base, steps=tuple(steps), pet_remainder=STAFF if kept else None),
    )
    assert draft == draft_id
    return draft


@pytest.mark.parametrize(
    ("security_amount", "pet_amount"),
    [(5_000, 5_000), (8_000, 2_000)],
    ids=["receipt-5000", "receipt-2000"],
)
def test_a_forfeited_right_receipt_does_not_pay_back_money_the_settlement_paid_out(
    migrated_database_url: str, security_amount: int, pet_amount: int
) -> None:
    """Owner answer (b) to Q-2026-10-17-122 on the security reviewer's case (round 1), in cents:
    the Pet Deposit's pay-back count was 3,000 and the Final Settlement refunded that 3,000, so the
    Customer has received it and the count is 0. The receipt correction writes the right Pet
    Deposit receipt and, in the same correction, forfeits all of it on BR-DEP-022 (5,000, or all
    of 2,000, which the count of 3,000 would have covered before the answer); nothing of it is
    applied or refunded, so the Customer has the 3,000 once. The Security Deposit's new money pays
    the 10,000 recovery charge (5,000 or 8,000 paid). The Pet Deposit's Refunds other than the
    review stay 3,000, it pays no Deposit application, the count stays 0, the Payment keeps what
    the receipts do not take, and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url)
    security, pet, customer, lease = case["security"], case["pet"], case["customer"], case["lease"]
    payment = receipt_payment(url, security)
    before_available = available(url, payment)
    draft = record_correction(case, security_amount, pet_amount)
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": pet_amount,
            "governing_rule": "BR-DEP-022",
            "basis": "TERMINATION_GROUND",
            "reason": REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): security_amount, str(pet): 0}
    assert stored["plan_overlay"]["corrected_deposit_id"] == str(security)
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
        stored["plan_result"]["deposit_ids"],
    ) == (10_000, 10_000 - security_amount, [str(security)])

    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    [disposition] = result["deposit_disposition_ids"]
    assert forfeitures(url, pet) == [
        (
            pet_amount,
            REASON,
            "deposits.dispose",
            case["person"],
            termination_date(url, lease),
            False,
            "BR-DEP-022",
            correction,
        )
    ]
    assert one(
        url,
        "SELECT disposition.occurred_at>receipt.occurred_at FROM app.deposit_dispositions "
        "disposition JOIN app.deposit_receipts receipt "
        "ON receipt.deposit_id=disposition.deposit_id AND receipt.payment_id=%s "
        "WHERE disposition.id=%s",
        payment,
        UUID(str(disposition)),
    ) == (True,)
    assert (held(url, pet), held(url, security), payback_count(url, pet)) == (0, 0, 0)
    assert path(url, case, pet) == "KEPT"
    assert paid_out(url, pet) == (3_000, 0)
    assert receipts_of(url, security) == [
        (payment, 10_000, True),
        (payment, security_amount, False),
    ]
    assert [row for row in receipts_of(url, pet) if row[0] == payment] == [
        (payment, pet_amount, False)
    ]
    real_line, *charge = recovery_line(url, case["refund"])
    assert charge == [customer, lease, 10_000, "MISCELLANEOUS_CHARGES", correction]
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(security, real_line, security_amount)]
    assert (outstanding(url, real_line), result["refund_ids"]) == (10_000 - security_amount, [])
    assert available(url, payment) == before_available
    reconciled(url, customer)


def test_a_staff_choice_to_forfeit_again_takes_the_money_already_paid_back(
    migrated_database_url: str,
) -> None:
    """The review round 1 set-up of a staff choice to forfeit again, on the real path: the Pet
    Deposit's 3,000 beyond the count was forfeited, the Final Settlement refunded its 3,000 of
    pay-back money and a FORFEITURE_REVERSAL refunded the forfeited 3,000, so the Customer has
    received everything and the count is 0 (owner answer (b) to Q-2026-10-17-122). The receipt
    correction's 5,000 Pet receipt with the staff choice FORFEIT is forfeited whole (a staff
    choice, with its reason, linked); the Pet Deposit is kept again and pays nothing; the Security
    Deposit's 5,000 pays the recovery charge and 5,000 stays owed; the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url, forfeit_pet=True)
    security, pet, customer, lease = case["security"], case["pet"], case["customer"], case["lease"]
    receipt = receipt_of(url, security)
    source = source_of(url, case, receipt)
    [target] = value(
        url,
        "SELECT app.settlement_deposit_receipt_correction_targets(%s,%s,%s)",
        case["prop"],
        Jsonb(source),
        Jsonb([{"deposit_id": str(pet), "amount_usd_cents": 5_000}]),
    )
    assert (target["payback_count"], target["path"]["forfeiture"]) == (0, "REVERSED")
    draft = record_correction(case, 5_000, 5_000, "FORFEIT")
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 5_000,
            "governing_rule": "BR-DEP-022",
            "basis": "STAFF_CHOICE",
            "reason": OUTCOME_REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 5_000, str(pet): 0}
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    [*earlier, forfeiture] = forfeitures(url, pet)
    assert [row[0] for row in earlier] == [3_000] and earlier[0][5] is True
    assert forfeiture == (
        5_000,
        OUTCOME_REASON,
        "deposits.dispose",
        case["person"],
        termination_date(url, lease),
        False,
        "BR-DEP-022",
        correction,
    )
    assert (held(url, pet), path(url, case, pet), payback_count(url, pet)) == (0, "KEPT", 0)
    assert paid_out(url, pet) == (6_000, 0)
    real_line, *_ = recovery_line(url, case["refund"])
    assert [
        one(
            url,
            "SELECT deposit_id,amount_usd_cents FROM app.deposit_applications WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(security, 5_000)]
    assert (outstanding(url, real_line), result["refund_ids"]) == (5_000, [])
    reconciled(url, customer)


def correct_pet_receipt(case: dict[str, Any]) -> None:
    """The seeded Pet Deposit receipt was not Pet Deposit money: a receipt correction reverses it
    with no right receipt, after recovering by a charge each Refund paid from the Pet Deposit (the
    Pet Refund-review Refund's 2,000 that did not come back, the Final Settlement's 3,000 and, in
    the forfeit_pet case, the forfeiture reversal's 3,000)."""
    url, pet = case["url"], case["pet"]
    confirm(case, record(case, request(case, receipt_of(url, pet))))


@pytest.mark.parametrize(
    ("security_amount", "pet_amount", "forfeited"),
    [(5_000, 5_000, 0), (3_000, 7_000, 2_000)],
    ids=["pet-5000", "pet-7000"],
)
def test_a_payout_recovered_by_a_charge_is_payback_money_again(
    migrated_database_url: str, security_amount: int, pet_amount: int, forfeited: int
) -> None:
    """Review round 2 set-ups B and C (implementer's reading (i), confirmed in review round 2):
    the Final Settlement's 3,000 Pet Refund is recovered by a charge when the seeded Pet receipt is
    reversed, so the Customer owes it back and that 3,000 is pay-back money again (held 0). Owner
    answer (a) to Q-2026-10-17-123 (sub-slice 10e-2b-4a): the Pet Refund-review Refund's 2,000
    recovered by the same correction counts like a verified return, so the count is 5,000 (it was
    3,000 before the answer). The receipt correction of the 10,000 Security receipt then puts
    pet_amount into that Pet Deposit, which is not the corrected receipt's. 5,000: the count covers
    it, so nothing is forfeited (2,000 before the answer) and the whole 5,000 follows DL-032 (after
    the Security Deposit's 5,000, on the 10,000 recovery charge; nothing stays owed, 2,000 before);
    the Pet Deposit was never forfeited (`NOTHING_HELD`, `KEPT` before). 7,000 with 3,000 Security
    (added in review round 1 so that a partial forfeiture on the ground stays tested): 2,000 beyond
    the count is forfeited on BR-DEP-022 and the pay-back 5,000 follows DL-032 after the Security
    Deposit's 3,000, 2,000 owed. The count is 0 afterwards and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url)
    security, pet, lease = case["security"], case["pet"], case["lease"]
    settled = settlement_pet_refund(url, pet)
    assert payback_count(url, pet) == 0
    correct_pet_receipt(case)
    assert (recovery_line(url, settled)[3], recovery_line(url, case["review_refund"])[3]) == (
        3_000,
        2_000,
    )
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (
        0,
        5_000,
        "NOTHING_HELD",
    )
    draft = record_correction(case, security_amount, pet_amount)
    stored = payload(url, draft)
    if forfeited:
        assert stored["deposit_receipt_forfeitures"] == [
            {
                "deposit_id": str(pet),
                "deposit_type": "PET",
                "amount_usd_cents": forfeited,
                "governing_rule": "BR-DEP-022",
                "basis": "TERMINATION_GROUND",
                "reason": REASON,
            }
        ]
    else:
        assert "deposit_receipt_forfeitures" not in stored
    assert stored["plan_overlay"]["deposits_after"] == {
        str(security): security_amount,
        str(pet): 5_000,
    }
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert forfeitures(url, pet) == (
        [
            (
                forfeited,
                REASON,
                "deposits.dispose",
                case["person"],
                termination_date(url, lease),
                False,
                "BR-DEP-022",
                correction,
            )
        ]
        if forfeited
        else []
    )
    real_line, *_ = recovery_line(url, case["refund"])
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(security, real_line, security_amount), (pet, real_line, 5_000)]
    assert (outstanding(url, real_line), result["refund_ids"]) == (5_000 - security_amount, [])
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (
        0,
        0,
        "KEPT" if forfeited else "NOTHING_HELD",
    )
    reconciled(url, case["customer"])


@pytest.mark.parametrize("amount", [4_000, 2_000])
def test_the_corrected_receipt_s_own_pet_deposit_counts_without_its_payouts(
    migrated_database_url: str, amount: int
) -> None:
    """Review round 2 set-up A, on the real path: the seeded 5,000 Pet receipt was really amount.
    The receipt correction recovers the Pet Deposit's two Refunds by a charge (2,000 and 3,000) and
    writes the right receipt into the same Pet Deposit; it undoes every payout of that Deposit, so
    its target count is counted without payouts. Owner answer (a) to Q-2026-10-17-123 (sub-slice
    10e-2b-4a): the review Refund's 2,000 that the correction charges back counts like a verified
    return, so the target count is 5,000 (3,000 before the answer). 4,000 forfeits nothing (1,000
    before the answer) and pays the Settlement Refund's 3,000 recovery charge and 1,000 of the
    review Refund's (3,000 of the first before); 2,000 forfeits nothing and pays 2,000 of the
    first, and 3,000 stays pay-back money (1,000 before). The forfeiture writer's exact check on
    the own Deposit is tested in the forfeit_pet case below (review round 1: with this fixture the
    own Deposit can no longer forfeit on the ground, so the forfeited branches are gone). The
    Payment keeps what the receipt does not take, and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url)
    pet = case["pet"]
    settled = settlement_pet_refund(url, pet)
    receipt = receipt_of(url, pet)
    payment = receipt_payment(url, pet)
    before_available = available(url, payment)
    kept = min(amount, 5_000)
    first, rest = min(kept, 3_000), max(0, kept - 3_000)
    base = request(case, receipt, receipts=(CorrectionDepositReceipt(pet, amount),))
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, settled)
    review_placeholder = deposit_receipt_recovery_line_id(draft_id, case["review_refund"])
    steps = [SettlementDepositStep(PET_REST, pet, LINE, placeholder, first)]
    if rest:
        steps.append(SettlementDepositStep(PET_REST, pet, LINE, review_placeholder, rest))
    draft = record(
        case,
        replace(base, steps=tuple(steps), pet_remainder=STAFF),
    )
    assert draft == draft_id
    stored = payload(url, draft)
    assert "deposit_receipt_forfeitures" not in stored
    assert (
        stored["plan_overlay"]["deposits_after"],
        stored["plan_overlay"]["corrected_deposit_id"],
    ) == ({str(pet): kept}, str(pet))
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
    ) == (5_000, 5_000 - kept)
    result = confirm(case, draft)
    assert forfeitures(url, pet) == []
    assert receipts_of(url, pet) == [(payment, 5_000, True), (payment, amount, False)]
    settled_line, *_ = recovery_line(url, settled)
    review_line, *_ = recovery_line(url, case["review_refund"])
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(pet, settled_line, first)] + ([(pet, review_line, rest)] if rest else [])
    assert (outstanding(url, settled_line), outstanding(url, review_line)) == (
        3_000 - first,
        2_000 - rest,
    )
    assert (held(url, pet), payback_count(url, pet), count_as(url, pet, None, 0, True)) == (
        0,
        5_000 - kept,
        5_000,
    )
    assert path(url, case, pet) == "NOTHING_HELD"
    assert available(url, payment) == before_available + 5_000 - amount
    reconciled(url, case["customer"])


def test_a_staff_choice_to_forfeit_again_within_the_count_is_refused_on_the_real_path(
    migrated_database_url: str,
) -> None:
    """Review round 2 set-up D: in the forfeit_pet case the seeded 8,000 Pet receipt is reversed
    with its three Refunds recovered by a charge (2,000, 3,000 and 3,000), the Pet Deposit holds
    nothing and its forfeiture stays reversed. Owner answer (a) to Q-2026-10-17-123 (sub-slice
    10e-2b-4a): the review Refund's 2,000 charged back counts like a verified return, so the count
    is 5,000 (3,000 before the answer). A 3,000 and now also a 5,000 Pet receipt with the staff
    choice FORFEIT are refused at record (55000; nothing written; 5,000 forfeited 2,000 before the
    answer); a 7,000 Pet receipt (with 3,000 Security Deposit) forfeits 2,000 as the staff's choice
    and its pay-back 5,000 follows DL-032 on the recovery charge after the Security Deposit's
    3,000, 2,000 owed (implementer's reading: the passing case moves so that no check is lost)."""
    url = migrated_database_url
    case = payback_ground_case(url, forfeit_pet=True)
    security, pet = case["security"], case["pet"]
    correct_pet_receipt(case)
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (
        0,
        5_000,
        "DL_032",
    )
    for pet_amount in (3_000, 5_000):
        before = counts(url)
        with pytest.raises(FinalSettlementConflictError) as refused:
            record_correction(case, 5_000, pet_amount, "FORFEIT")
        assert cause(refused) == ("55000", NOTHING_BEYOND), pet_amount
        assert counts(url) == before, pet_amount
    draft = record_correction(case, 3_000, 7_000, "FORFEIT")
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 2_000,
            "governing_rule": "BR-DEP-022",
            "basis": "STAFF_CHOICE",
            "reason": OUTCOME_REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 3_000, str(pet): 5_000}
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert forfeitures(url, pet)[-1] == (
        2_000,
        OUTCOME_REASON,
        "deposits.dispose",
        case["person"],
        termination_date(url, case["lease"]),
        False,
        "BR-DEP-022",
        correction,
    )
    real_line, *_ = recovery_line(url, case["refund"])
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(security, real_line, 3_000), (pet, real_line, 5_000)]
    assert outstanding(url, real_line) == 2_000
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (0, 0, "KEPT")
    reconciled(url, case["customer"])


@contextmanager
def applied_by_hand(
    url: str, case: dict[str, Any], amount: int
) -> Iterator[psycopg.Connection[Any]]:
    """In an owner transaction that is always rolled back, with the user triggers of the two
    tables disabled: a Pet Deposit application of amount on the Initial Rent line, written now.
    Yields the connection; afterwards the real rows are unchanged."""
    with psycopg.connect(url) as connection:
        try:
            for table in ("deposit_applications", "deposit_application_reversals"):
                connection.execute(f"ALTER TABLE app.{table} DISABLE TRIGGER USER")
            connection.execute(
                "INSERT INTO app.deposit_applications(id,final_settlement_id,deposit_id,"
                "target_kind,invoice_id,invoice_line_id,application_stage,amount_usd_cents,"
                "application_order,reason,occurred_at,actor_id,authorization_reference) "
                "VALUES (%s,%s,%s,'INVOICE_LINE',%s,%s,'PET_REMAINDER_EXPLICIT',%s,99,"
                "'Hand-built application',clock_timestamp(),%s,'financial.approve')",
                (
                    uuid4(),
                    case["settlement"],
                    case["pet"],
                    case["invoice"],
                    case["rent_line"],
                    amount,
                    case["person"],
                ),
            )
            yield connection
        finally:
            connection.rollback()


def test_the_count_takes_only_payouts_that_are_not_undone(migrated_database_url: str) -> None:
    """Owner answer (b) to Q-2026-10-17-122: the Final Settlement's 3,000 Pet Refund took the
    count to 0. A return-only correction of 1,000 of that Refund (real path, financial.approve)
    puts 1,000 back: the Pet Deposit holds 1,000 of pay-back money again and follows DL-032. A
    Deposit application of 400 (by hand, rolled back) takes 400 out, and its reversal puts it back.
    The returned-Refund check counts the rest of that Refund's return (2,000 more) as pay-back
    money; a Pet Refund-review Refund's return still adds at the end, as built; without payouts
    the count is 5,000: the built 3,000 and, since sub-slice 10e-2b-4a (owner answer (a) to
    Q-2026-10-17-123), the review Refund's 2,000 still to recover (3,000 before the answer)."""
    url = migrated_database_url
    case = payback_ground_case(url)
    pet = case["pet"]
    refund = settlement_pet_refund(url, pet)
    assert (count_as(url, pet, refund, 1_000, False), count_as(url, pet, refund, 9_000, False)) == (
        1_000,
        3_000,
    )
    confirm_return(case, record_return(case, return_command(case, refund, 1_000, new=False)))
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (
        1_000,
        1_000,
        "DL_032",
    )
    with applied_by_hand(url, case, 400) as connection:
        count = "SELECT app.lease_deposit_payback_count(%s)"
        assert connection.execute(count, (pet,)).fetchone() == (600,)
        connection.execute(
            "INSERT INTO app.deposit_application_reversals(id,deposit_application_id,reason,"
            "occurred_at,actor_id,authorization_reference) SELECT %s,id,'Hand-built reversal',"
            "clock_timestamp(),actor_id,'financial.approve' FROM app.deposit_applications "
            "WHERE deposit_id=%s",
            (uuid4(), pet),
        )
        assert connection.execute(count, (pet,)).fetchone() == (1_000,)
    assert payback_count(url, pet) == 1_000
    assert value(url, "SELECT app.lease_deposit_payback_after_return(%s,%s,%s)", pet, refund, 2_000)
    assert (
        count_as(url, pet, refund, 2_000, False),
        count_as(url, pet, case["review_refund"], 500, False),
        count_as(url, pet, None, 0, True),
    ) == (3_000, 1_500, 5_000)


def test_the_plan_check_and_the_forfeiture_list_follow_the_payback_count(
    migrated_database_url: str,
) -> None:
    """With the stored draft of the 5,000 Pet receipt, the plan check (read as the owner) accepts
    the empty Pet Deposit with a ground at 0 after the correction and refuses 1 cent (55000),
    because the Customer has received its pay-back money (count 0). Counted as the corrected
    receipt's own Deposit (the overlay's `corrected_deposit_id`, whose payouts that correction
    undoes), the same Pet Deposit is counted without payouts and refuses 5,001 (the real-path
    own-Deposit test records a draft at the count); a
    `corrected_deposit_id` that is not a named Deposit or not a string is refused (22023). The
    target count is 0, or 5,000 when a hand-built source names the Pet Deposit as the corrected
    receipt's (owner answer (a) to Q-2026-10-17-123, sub-slice 10e-2b-4a: with the review Refund's
    2,000 that such a correction charges back; 3,000 and a refusal at 3,001 before the answer).
    The forfeiture list of the real Pet target names 5,000 and of the own target nothing (2,000
    before the answer); on hand-built counts an
    8,000 receipt gives 8,000, 5,000 and nothing for counts 0, 3,000, 8,000 and 9,000. A staff
    choice to forfeit again is refused while the count covers the receipt and passes one cent
    below it."""
    url = migrated_database_url
    case = payback_ground_case(url)
    pet = case["pet"]
    draft = record_correction(case, 5_000, 5_000)
    stored = payload(url, draft)
    after = stored["plan_overlay"]["deposits_after"]

    def plan_check(overlay: dict[str, Any]) -> tuple[str | None, str | None]:
        return owner_refusal(
            url,
            PLAN_RESULT,
            case["prop"],
            case["human"],
            case["settlement"],
            Jsonb(stored["plan"]),
            Jsonb(overlay),
        )

    for pet_after, own, refusal in (
        (1, False, ("55000", ONLY_DL_032)),
        (0, False, (None, None)),
        (5_001, True, ("55000", ONLY_DL_032)),
    ):
        overlay = {**stored["plan_overlay"], "deposits_after": {**after, str(pet): pet_after}}
        if own:
            overlay["corrected_deposit_id"] = str(pet)
        assert plan_check(overlay) == refusal, (pet_after, own)
    for wrong in (str(uuid4()), 7, None):
        assert plan_check({**stored["plan_overlay"], "corrected_deposit_id": wrong}) == (
            "22023",
            INVALID_OVERLAY,
        ), wrong

    receipt = receipt_of(url, case["security"])
    source = source_of(url, case, receipt)
    own_source = {**source, "receipt": {**source["receipt"], "deposit_id": str(pet)}}
    targets = []
    for named in (source, own_source):
        [found] = value(
            url,
            "SELECT app.settlement_deposit_receipt_correction_targets(%s,%s,%s)",
            case["prop"],
            Jsonb(named),
            Jsonb([{"deposit_id": str(pet), "amount_usd_cents": 5_000}]),
        )
        targets.append(found)
    target, own_target = targets
    assert (target["payback_count"], target["path"]["ground"], target["path"]["forfeiture"]) == (
        0,
        "BR-DEP-022",
        "NONE",
    )
    assert own_target["payback_count"] == 5_000

    def listed(targets: list[dict[str, Any]]) -> list[int]:
        return [
            int(entry["amount_usd_cents"])
            for entry in value(
                url,
                "SELECT app.settlement_deposit_receipt_forfeitures(%s,%s)",
                Jsonb(targets),
                REASON,
            )
        ]

    assert (listed([target]), listed([own_target])) == ([5_000], [])
    eight = {**target, "amount_usd_cents": 8_000}
    for count, amounts in ((0, [8_000]), (3_000, [5_000]), (8_000, []), (9_000, [])):
        assert listed([{**eight, "payback_count": count}]) == amounts, count
    forfeit_again = {
        **eight,
        "path": {**target["path"], "forfeiture": "REVERSED"},
        "outcome": "FORFEIT",
        "outcome_reason": OUTCOME_REASON,
    }
    for count, refusal in (
        (8_000, ("55000", NOTHING_BEYOND)),
        (9_000, ("55000", NOTHING_BEYOND)),
        (7_999, (None, None)),
    ):
        assert (
            targets_check(url, case, source, [{**forfeit_again, "payback_count": count}]) == refusal
        ), count
    assert listed([{**forfeit_again, "payback_count": 7_999}]) == [1]


def test_the_payback_forfeiture_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration adds one internal function (no grant, SECURITY DEFINER, a fixed search path)
    and no constraint or trigger, changes only the eight listed functions (privileges, owner and
    settings kept; each patched body is exactly the old one with the module's replacements) and is
    forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261222_148"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
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
        constraints = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app'",
            )
        }
        triggers = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, constraints, triggers

    with _temporary_migration_database("settlement_deposit_receipt_payback") as temporary:
        alembic_command.upgrade(config, "20261222_148")
        before_functions, before_constraints, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = catalog(temporary)
        grantees = rows(
            temporary,
            "SELECT grantee FROM information_schema.routine_privileges "
            "WHERE routine_schema='app' AND routine_name='lease_deposit_payback_count_as' "
            "AND grantee<>(SELECT pg_get_userbyid(p.proowner) FROM pg_catalog.pg_proc p "
            "WHERE p.oid='app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)'"
            "::regprocedure)",
        )
    assert (after_constraints, after_triggers) == (before_constraints, before_triggers)
    assert set(after_functions) == set(before_functions) | NEW
    [new] = NEW
    assert after_functions[new][3:] == (True, "{search_path=pg_catalog}")
    assert grantees == []
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    assert set(revision.module.INTERNAL) == NEW
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function


REVISION_4A = "20261225_151"
PATCHED_4A = {"app.lease_deposit_payback_count_as(uuid,uuid,bigint,boolean)"}


def test_the_own_pet_deposit_forfeits_beyond_the_review_refund_it_charges_back(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-17-123 (sub-slice 10e-2b-4a) on the corrected receipt's own
    Deposit: in the forfeit_pet case the seeded 8,000 Pet receipt was really 7,000. The receipt
    correction recovers the Pet Deposit's three Refunds by a charge (the review Refund's 2,000, the
    Settlement's 3,000 and the forfeiture reversal's 3,000) and undoes every payout, so its target
    count is 5,000: the review Refund's 3,000 that came back and its 2,000 that this correction
    charges back. With the staff choice FORFEIT, 2,000 is forfeited (linked to the correction;
    the forfeiture writer's exact check passes against the real count after the recoveries) and
    the pay-back 5,000 follows DL-032 onto the recovery charges. The Payment keeps the other 1,000,
    the count is 0 afterwards and the ledger reconciles."""
    url = migrated_database_url
    case = payback_ground_case(url, forfeit_pet=True)
    pet, lease = case["pet"], case["lease"]
    settled, reversed_refund = (
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT id FROM app.refunds WHERE source_deposit_id=%s "
            "AND pet_refund_review_id IS NULL ORDER BY processed_at,id",
            pet,
        )
    )
    receipt = receipt_of(url, pet)
    payment = receipt_payment(url, pet)
    before_available = available(url, payment)
    assert count_as(url, pet, None, 0, True) == 5_000
    base = request(
        case,
        receipt,
        receipts=(CorrectionDepositReceipt(pet, 7_000, "FORFEIT", OUTCOME_REASON),),
    )
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    steps = (
        SettlementDepositStep(
            PET_REST, pet, LINE, deposit_receipt_recovery_line_id(draft_id, settled), 3_000
        ),
        SettlementDepositStep(
            PET_REST, pet, LINE, deposit_receipt_recovery_line_id(draft_id, reversed_refund), 2_000
        ),
    )
    draft = record(case, replace(base, steps=steps, pet_remainder=STAFF))
    assert draft == draft_id
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 2_000,
            "governing_rule": "BR-DEP-022",
            "basis": "STAFF_CHOICE",
            "reason": OUTCOME_REASON,
        }
    ]
    assert (
        stored["plan_overlay"]["deposits_after"],
        stored["plan_overlay"]["corrected_deposit_id"],
    ) == ({str(pet): 5_000}, str(pet))
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert forfeitures(url, pet)[-1] == (
        2_000,
        OUTCOME_REASON,
        "deposits.dispose",
        case["person"],
        termination_date(url, lease),
        False,
        "BR-DEP-022",
        correction,
    )
    assert receipts_of(url, pet) == [(payment, 8_000, True), (payment, 7_000, False)]
    settled_line, *_ = recovery_line(url, settled)
    reversed_line, *_ = recovery_line(url, reversed_refund)
    review_line, *_ = recovery_line(url, case["review_refund"])
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(pet, settled_line, 3_000), (pet, reversed_line, 2_000)]
    assert (
        outstanding(url, settled_line),
        outstanding(url, reversed_line),
        outstanding(url, review_line),
    ) == (0, 1_000, 2_000)
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (0, 0, "KEPT")
    assert available(url, payment) == before_available + 1_000
    reconciled(url, case["customer"])


def test_a_charge_back_at_the_instant_of_a_return_reversal_counts_alike_in_either_id_order(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4a review round 1 (security blocker): a return reversal can write a
    charge-back of a Pet Refund-review Refund at the same instant as its CORRECTION_REVERSAL
    (sub-slice 10e-3d-2c, migration 20261210_136). After the Final Settlement's Refund the count
    is 0. By hand, in an owner transaction that is always rolled back (user triggers of the Refund
    corrections off, the recovery charge's foreign key dropped), the review Refund's 3,000 return
    is reversed (-3,000) and 3,000 is charged back (+3,000) at one instant, once with the
    reversal's id first and once with the charge-back's: the charge-back alone gives 3,000, and
    with the reversal the count is 0 both times, because at the same moment and order an addition
    comes first (the ids alone would have given 3,000 in one order). Afterwards nothing of it is
    left (review round 2)."""
    url = migrated_database_url
    case = payback_ground_case(url)
    pet, review = case["pet"], case["review_refund"]
    [(returned_id,)] = rows(
        url,
        "SELECT id FROM app.refund_corrections WHERE refund_id=%s "
        "AND correction_kind='VALUE_CORRECTION'",
        review,
    )
    assert payback_count(url, pet) == 0
    insert = (
        "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,"
        "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
        "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,"
        "occurred_at,actor_id,authorization_reference,recovery_obligation_id) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s,'Hand-built','Hand-built',"
        "transaction_timestamp()+interval '1 second',%s,%s,%s)"
    )
    low, high = UUID(int=1), UUID(int=2**128 - 1)
    counts_seen = []
    for reversal, charge_back in ((low, high), (high, low)):
        with psycopg.connect(url) as connection:
            try:
                connection.execute("ALTER TABLE app.refund_corrections DISABLE TRIGGER USER")
                [(foreign_key,)] = connection.execute(
                    "SELECT conname FROM pg_catalog.pg_constraint "
                    "WHERE conrelid='app.refund_corrections'::regclass AND contype='f' "
                    "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%%recovery_obligation_id%%'"
                ).fetchall()
                connection.execute(
                    f'ALTER TABLE app.refund_corrections DROP CONSTRAINT "{foreign_key}"'
                )
                connection.execute(
                    insert,
                    (
                        charge_back,
                        review,
                        "RECOVERED_BY_CHARGE",
                        None,
                        3_000,
                        3_000,
                        5_000,
                        2_000,
                        case["person"],
                        "financial.approve",
                        uuid4(),
                    ),
                )
                alone = connection.execute(COUNT_AS, (pet, None, 0, False)).fetchone()
                assert alone is not None and int(alone[0]) == 3_000
                connection.execute(
                    insert,
                    (
                        reversal,
                        review,
                        "CORRECTION_REVERSAL",
                        returned_id,
                        -3_000,
                        -3_000,
                        2_000,
                        5_000,
                        case["person"],
                        "refunds.corrections.reverse",
                        None,
                    ),
                )
                found = connection.execute(COUNT_AS, (pet, None, 0, False)).fetchone()
                assert found is not None
                counts_seen.append(int(found[0]))
            finally:
                connection.rollback()
    assert counts_seen == [0, 0]
    assert payback_count(url, pet) == 0
    assert rows(url, "SELECT id FROM app.refund_corrections WHERE refund_id=%s", review) == [
        (returned_id,)
    ]
    assert (
        value(
            url,
            "SELECT count(*) FROM pg_catalog.pg_constraint "
            "WHERE conrelid='app.refund_corrections'::regclass AND contype='f' "
            "AND pg_catalog.pg_get_constraintdef(oid) LIKE '%%recovery_obligation_id%%'",
        )
        == 1
    )


def test_the_review_refund_recovery_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4a adds no function, constraint or trigger, changes only the pay-back
    count function (privileges, owner and settings kept; its body is exactly the old one with the
    module's two replacements) and is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION_4A)
    assert revision is not None and revision.down_revision == "20261224_150"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

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

    with _temporary_migration_database("pet_review_refund_recovery_payback") as temporary:
        alembic_command.upgrade(config, "20261224_150")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION_4A)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED_4A
    assert {function for function, _ in revision.module.PATCHES} == PATCHED_4A
    for function, replacements in revision.module.PATCHES:
        assert after_functions[function][1:] == before_functions[function][1:], function
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
