"""Post-settlement correction: a right receipt into a Deposit with a forfeiture ground (V1-056
sub-slice 10e-2c).

Owner answers to Q-2026-10-12-88: point 1 (b), a right receipt into a Deposit whose termination
ground says the Property keeps it, and that was never forfeited, is forfeited in the same
DEPOSIT_RECEIPT_CORRECTION, linked to it; point 2 (c), for a Deposit whose forfeiture was reversed
first, staff choose in the draft, with a reason, DL-032 or a forfeiture again, and the
financial.approve approver confirms it. The draft shows each forfeiture; forfeited money stays out
of the plan; only the new receipt's money is forfeited (Q-2026-10-12-93).
"""

from __future__ import annotations

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
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.settlement_correction import (
    CorrectionDepositReceipt,
    deposit_receipt_recovery_line_id,
    settlement_correction_draft_id,
)
from test_deposit_migration import create_pet, deposit_actor
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, SECURITY
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, start
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_settlement_correction_migration import approver
from test_settlement_correction_plan_migration import new_credit
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
from test_settlement_deposit_receipt_recovery_line_migration import owner_refusal, recovery_line
from test_settlement_deposit_receipt_rewrite_migration import receipts_of, targets_check
from test_settlement_extra_charge_migration import cause, state
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    disposition_of,
    kept_case,
    record_reversal,
    reversal_command,
)
from test_settlement_real_path_migration import AGREEMENT, two_signer_kept_case
from test_settlement_refund_return_migration import net
from test_settlement_returned_payment_migration import closed_case, receipt_payment, reconciled
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261128_124"
INTERNAL = (
    "app.settlement_deposit_receipt_forfeitures(jsonb,text)",
    "app.write_correction_deposit_forfeiture(uuid,uuid,uuid,uuid,bigint,text,"
    "timestamp with time zone)",
)
PATCHED = {
    "app.settlement_deposit_receipt_correction_input(jsonb)",
    "app.settlement_deposit_receipt_correction_targets(uuid,jsonb,jsonb)",
    "app.assert_settlement_deposit_receipt_targets_allowed(uuid,jsonb,jsonb)",
    "app.settlement_deposit_receipt_correction_overlay(jsonb,jsonb)",
    "app.record_settlement_deposit_receipt_correction_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.post_settlement_deposit_receipt_correction(uuid,uuid,uuid,uuid,uuid,text)",
    "app.settlement_deposit_receipt_correction_result(uuid)",
}
REBUILT = {
    "app.settlement_correction_linked(uuid,text,uuid)",
    "app.link_settlement_correction_effect(uuid,text,uuid)",
}
OUTCOME_REASON = "The Customer's letter shows 8,000 was the Security Deposit; the rest was Rent"
ONLY_REVERSED = "Only a Deposit whose forfeiture was reversed takes a choice of outcome"
NEEDS_CHOICE = (
    "A new receipt into a Deposit whose forfeiture was reversed needs a choice: "
    "DL-032 or a forfeiture again"
)
ONLY_NEW_MONEY = "A forfeiture in a receipt correction takes only the new receipt's money"
NOT_NAMED = "The forfeiture is not one the correction's draft names"
OUTSIDE_CONFIRM = "A forfeiture is written only inside its correction's confirm"
INVALID_INPUT = "Deposit receipt correction input is invalid"
WRITER = "SELECT app.write_correction_deposit_forfeiture(%s,%s,%s,%s,%s,%s,clock_timestamp())"


def pet_ground_case(url: str) -> dict[str, Any]:
    """A signed Lease starting this month with its Security Deposit (10,000, received through the
    Reservation) and an approved Pet Deposit liability (20,000) that holds nothing: no function
    records Pet Deposit money before closure (Q-2026-10-12-92). The Initial Rent is paid; the Lease
    is terminated for pet noncompliance after three warnings (BR-DEP-022: the Property keeps both
    Deposits). The Security Deposit is forfeited through the draft and kept; the empty Pet Deposit
    is never forfeited (NOTHING_HELD). The Final Settlement is really closed with nothing owed. A
    correction approver is ready."""
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
    pet, _ = create_pet(deposits, deposit_actor(human, prop), lease, approval, day)
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate_for_disposition(url, deposits, lease, day)
    security = source["deposit"]
    forfeit_through_draft(deposits, security)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": security,
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }
    case["disposition"] = disposition_of(url, security)
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    assert (held(url, security), held(url, pet), path(url, case, pet)) == (0, 0, "NOTHING_HELD")
    return case


def path(url: str, case: dict[str, Any], deposit: UUID) -> str:
    return str(
        value(
            url,
            "SELECT app.lease_deposit_settlement_path(%s,%s)->>'path'",
            case["prop"],
            deposit,
        )
    )


def forfeitures(url: str, deposit: UUID) -> list[tuple[Any, ...]]:
    """Each forfeiture of the Deposit in date order: amount, reason, authorization reference,
    actor, effective date, whether it is reversed, its ground rule and its correction link."""
    return rows(
        url,
        "SELECT disposition.amount_usd_cents,disposition.reason,"
        "disposition.authorization_reference,disposition.actor_id,disposition.effective_date,"
        "EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal "
        "WHERE reversal.deposit_disposition_id=disposition.id),context.governing_rule,"
        "effect.settlement_correction_id FROM app.deposit_dispositions disposition "
        "JOIN app.lease_deposit_disposition_contexts context "
        "ON context.disposition_id=disposition.id "
        "LEFT JOIN app.settlement_correction_effects effect "
        "ON effect.deposit_disposition_id=disposition.id "
        "WHERE disposition.deposit_id=%s ORDER BY disposition.occurred_at",
        deposit,
    )


def termination_date(url: str, lease: UUID) -> Any:
    return value(url, "SELECT actual_termination_date FROM app.leases WHERE id=%s", lease)


def test_point_1_forfeits_a_right_receipt_into_an_empty_kept_deposit(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-12-88, the owner's example in cents: the Lease ended for pet
    noncompliance; the 10,000 Security Deposit was kept and the Pet Deposit was empty. Staff
    reverse the Security forfeiture first (a FORFEITURE_REVERSAL refunds the 10,000), then find the
    receipt was really 8,000 Security Deposit and 2,000 Pet Deposit. The receipt correction
    recovers the 10,000 Refund by a charge (a placeholder line in the draft), writes 8,000 into the
    Security Deposit (staff choose DL-032: it pays 8,000 of the charge, 2,000 stays owed) and 2,000
    into the Pet Deposit, which the same correction forfeits on BR-DEP-022 (linked, dated after its
    receipt; staff choose nothing). The forfeiture writer refuses an amount its draft does not name
    inside the confirm, and the named one after the commit."""
    url = migrated_database_url
    case = pet_ground_case(url)
    security, pet, customer, lease = case["security"], case["pet"], case["customer"], case["lease"]
    reversal = confirm_reversal(
        case,
        record_reversal(case, reversal_command(case, settlement_refund(case, "security", 10_000))),
    )
    [paid] = reversal["refunds"]
    refund = UUID(str(paid["id"]))
    assert path(url, case, security) == "DL_032"
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_available = available(url, payment)
    before = counts(url)
    for receipts, refusal in (
        (
            (
                CorrectionDepositReceipt(security, 8_000, "DL_032", OUTCOME_REASON),
                CorrectionDepositReceipt(pet, 2_000, "DL_032", OUTCOME_REASON),
            ),
            ONLY_REVERSED,
        ),
        (
            (CorrectionDepositReceipt(security, 8_000), CorrectionDepositReceipt(pet, 2_000)),
            NEEDS_CHOICE,
        ),
    ):
        with pytest.raises(FinalSettlementConflictError) as refused:
            record(case, request(case, receipt, receipts=receipts))
        assert cause(refused) == ("55000", refusal)
    assert counts(url) == before

    base = request(
        case,
        receipt,
        receipts=(
            CorrectionDepositReceipt(security, 8_000, "DL_032", OUTCOME_REASON),
            CorrectionDepositReceipt(pet, 2_000),
        ),
    )
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, refund)
    draft = record(
        case,
        replace(base, steps=(SettlementDepositStep(SECURITY, security, LINE, placeholder, 8_000),)),
    )
    assert draft == draft_id
    stored = payload(url, draft)
    # The draft shows the approver the forfeiture: the Deposit, the amount, the rule and why.
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(pet),
            "deposit_type": "PET",
            "amount_usd_cents": 2_000,
            "governing_rule": "BR-DEP-022",
            "basis": "TERMINATION_GROUND",
            "reason": REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 8_000, str(pet): 0}
    assert stored["plan_overlay"]["new_obligations"][str(placeholder)]["amount_usd_cents"] == 10_000
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
        stored["plan_result"]["deposit_ids"],
    ) == (10_000, 2_000, [str(security)])

    recorded = counts(url)
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_deposit_receipt_correction("
            "%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        )
        found = connection.execute(
            "SELECT id FROM app.settlement_corrections WHERE correlation_id=%s", (draft,)
        ).fetchone()
        assert found is not None
        for amount, reason in ((1_999, REASON), (2_000, OUTCOME_REASON)):
            with pytest.raises(psycopg.Error) as unnamed, connection.transaction():
                connection.execute(
                    WRITER, (case["prop"], found[0], case["person"], pet, amount, reason)
                )
            assert (unnamed.value.sqlstate, unnamed.value.diag.message_primary) == (
                "55000",
                NOT_NAMED,
            ), amount
        connection.rollback()
    assert (state(url, draft), counts(url)) == ("PENDING", recorded)

    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    [disposition] = result["deposit_disposition_ids"]
    assert forfeitures(url, pet) == [
        (
            2_000,
            REASON,
            "deposits.dispose",
            case["person"],
            termination_date(url, lease),
            False,
            "BR-DEP-022",
            correction,
        )
    ]
    # The forfeiture is dated after the Pet Deposit's new receipt; the Pet Deposit is kept.
    assert one(
        url,
        "SELECT disposition.occurred_at>receipt.occurred_at FROM app.deposit_dispositions "
        "disposition JOIN app.deposit_receipts receipt "
        "ON receipt.deposit_id=disposition.deposit_id "
        "WHERE disposition.id=%s",
        UUID(str(disposition)),
    ) == (True,)
    assert (path(url, case, pet), held(url, pet), held(url, security)) == ("KEPT", 0, 0)
    assert receipts_of(url, security) == [(payment, 10_000, True), (payment, 8_000, False)]
    assert receipts_of(url, pet) == [(payment, 2_000, False)]
    real_line, *charge = recovery_line(url, refund)
    assert charge == [customer, lease, 10_000, "MISCELLANEOUS_CHARGES", correction]
    assert [
        one(
            url,
            "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
            "WHERE id=%s",
            UUID(str(application)),
        )
        for application in result["deposit_application_ids"]
    ] == [(security, real_line, 8_000)]
    assert (outstanding(url, real_line), result["refund_ids"], net(url, refund)) == (2_000, [], 0)
    assert available(url, payment) == before_available
    # The Deposit audit event and command record of the forfeiture.
    assert one(
        url,
        "SELECT action,authorization_reference,correlation_id,actor_id FROM app.audit_events "
        "WHERE id=%s",
        UUID(str(disposition)),
    ) == ("deposit.disposition.recorded", "financial.approve", correction, case["person"])
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_commands command "
        "JOIN app.lease_deposit_disposition_contexts context "
        "ON context.actor_id=command.actor_id AND context.property_id=command.property_id "
        "AND context.idempotency_key=command.idempotency_key "
        "WHERE context.disposition_id=%s AND command.action='deposit.disposition.record'",
        UUID(str(disposition)),
    ) == (1,)
    reconciled(url, customer)
    assert owner_refusal(
        url, WRITER, case["prop"], correction, case["person"], pet, 2_000, REASON
    ) == ("55000", OUTSIDE_CONFIRM)


def test_point_2_forfeits_a_right_receipt_again_when_staff_choose_it(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-12-88 (FORFEIT): voluntary early leaving kept the 10,000
    Security Deposit (BR-DEP-023). A FORFEITURE_REVERSAL pays the 4,600 still open and refunds
    5,400; then the receipt is found to be really 8,000. Without a choice the correction is
    refused. Staff choose to forfeit again, with a reason: the 4,600 application is reversed (owed
    again), the 5,400 Refund is recovered by a charge (owed), the 8,000 receipt is written and kept
    again on BR-DEP-023 with the staff reason; the plan pays nothing, and 2,000 stays with the
    Payment."""
    url = migrated_database_url
    case = kept_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    reversal = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                SettlementDepositStep(SECURITY, security, LINE, other_line, 4_600),
                settlement_refund(case, "security", 5_400),
            ),
        ),
    )
    [paid] = reversal["refunds"]
    refund = UUID(str(paid["id"]))
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_available = available(url, payment)
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as unchosen:
        record(case, request(case, receipt, receipts=(CorrectionDepositReceipt(security, 8_000),)))
    assert cause(unchosen) == ("55000", NEEDS_CHOICE)
    assert counts(url) == before
    draft = record(
        case,
        request(
            case,
            receipt,
            receipts=(CorrectionDepositReceipt(security, 8_000, "FORFEIT", OUTCOME_REASON),),
        ),
    )
    stored = payload(url, draft)
    assert stored["deposit_receipt_forfeitures"] == [
        {
            "deposit_id": str(security),
            "deposit_type": "SECURITY",
            "amount_usd_cents": 8_000,
            "governing_rule": "BR-DEP-023",
            "basis": "STAFF_CHOICE",
            "reason": OUTCOME_REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 0}
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
        stored["plan_result"]["deposit_ids"],
    ) == (10_000, 10_000, [])
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert len(result["deposit_disposition_ids"]) == 1
    assert (result["deposit_application_ids"], result["refund_ids"]) == ([], [])
    [first, again] = forfeitures(url, security)
    assert (first[0], first[5], first[6], first[7]) == (10_000, True, "BR-DEP-023", None)
    assert again == (
        8_000,
        OUTCOME_REASON,
        "deposits.dispose",
        case["person"],
        termination_date(url, case["lease"]),
        False,
        "BR-DEP-023",
        correction,
    )
    assert (path(url, case, security), held(url, security)) == ("KEPT", 0)
    real_line, *charge = recovery_line(url, refund)
    assert charge[:3] == [customer, case["lease"], 5_400]
    assert (outstanding(url, other_line), outstanding(url, real_line), net(url, refund)) == (
        4_600,
        5_400,
        0,
    )
    assert available(url, payment) == before_available + 2_000
    reconciled(url, customer)


def test_point_2_dl032_takes_the_joint_signer_path_in_full(migrated_database_url: str) -> None:
    """Owner answer 2 to Q-2026-10-12-88 (DL_032), the full record-and-confirm path the sub-slice
    10e-2b-2 review asked for: on the real two-Signer closure a FORFEITURE_REVERSAL refunded the
    kept 10,000 to the second Signer (with the Signers' agreement), who holds 300 of Credit. The
    receipt was really 1,000. Staff choose DL-032: the recovery charge to the second Signer is a
    placeholder line; that Signer's Credit pays 300 of it first and the new 1,000 Security receipt
    pays 1,000; 8,700 stays owed by the second Signer, nothing is forfeited, and 9,000 stays with
    the Payment."""
    url = migrated_database_url
    case = two_signer_kept_case(url)
    security, co_signer, lease = case["security"], case["co_signer"], case["lease"]
    reversal = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                settlement_refund(
                    case,
                    "security",
                    10_000,
                    recipient_customer_id=co_signer,
                    signer_agreement=AGREEMENT,
                ),
            ),
        ),
    )
    [paid] = reversal["refunds"]
    refund = UUID(str(paid["id"]))
    credit = new_credit(url, case, 300, co_signer)
    receipt = receipt_of(url, security)
    payment = receipt_payment(url, security)
    before_available = available(url, payment)
    base = request(
        case,
        receipt,
        receipts=(CorrectionDepositReceipt(security, 1_000, "DL_032", OUTCOME_REASON),),
    )
    draft_id = settlement_correction_draft_id(case["prop"], case["human"], base.idempotency_key)
    placeholder = deposit_receipt_recovery_line_id(draft_id, refund)
    draft = record(
        case,
        replace(
            base,
            steps=(
                SettlementCreditStep(credit, LINE, placeholder, 300),
                SettlementDepositStep(SECURITY, security, LINE, placeholder, 1_000),
            ),
        ),
    )
    stored = payload(url, draft)
    assert "deposit_receipt_forfeitures" not in stored
    assert stored["deposit_receipt_correction"]["receipts"] == [
        {
            "deposit_id": str(security),
            "amount_usd_cents": 1_000,
            "outcome": "DL_032",
            "outcome_reason": OUTCOME_REASON,
        }
    ]
    assert stored["plan_overlay"]["deposits_after"] == {str(security): 1_000}
    assert stored["plan_overlay"]["new_obligations"] == {
        str(placeholder): {
            "refund_id": str(refund),
            "customer_id": str(co_signer),
            "lease_id": str(lease),
            "amount_usd_cents": 10_000,
        }
    }
    assert (
        stored["plan_result"]["open_total_usd_cents"],
        stored["plan_result"]["closing_balance_usd_cents"],
        stored["plan_result"]["closing_balances"],
    ) == (10_000, 8_700, [{"customer_id": str(co_signer), "open_usd_cents": 8_700}])
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    real_line, *charge = recovery_line(url, refund)
    assert charge == [co_signer, lease, 10_000, "MISCELLANEOUS_CHARGES", correction]
    [credit_application] = result["credit_application_ids"]
    assert one(
        url,
        "SELECT application.customer_credit_id,detail.invoice_line_id,application.amount_usd_cents "
        "FROM app.customer_credit_applications application "
        "JOIN app.customer_credit_application_details detail "
        "ON detail.customer_credit_application_id=application.id WHERE application.id=%s",
        UUID(str(credit_application)),
    ) == (credit, real_line, 300)
    [application] = result["deposit_application_ids"]
    assert one(
        url,
        "SELECT deposit_id,invoice_line_id,amount_usd_cents FROM app.deposit_applications "
        "WHERE id=%s",
        UUID(str(application)),
    ) == (security, real_line, 1_000)
    assert (result["deposit_disposition_ids"], result["refund_ids"]) == ([], [])
    assert (outstanding(url, real_line), held(url, security), path(url, case, security)) == (
        8_700,
        0,
        "DL_032",
    )
    assert len(forfeitures(url, security)) == 1
    assert available(url, payment) == before_available + 9_000
    reconciled(url, case["customer"])
    reconciled(url, co_signer)


def test_the_outcome_input_and_the_new_money_refusals(migrated_database_url: str) -> None:
    """On the normal-end closure (no ground): a choice on a Deposit without a ground is refused at
    record (55000). The input refuses a choice without its reason, an unknown choice and a bad
    reason (22023) and keeps a valid one. On changed targets: a choice on a Deposit never
    forfeited is refused; a reversed Deposit needs a choice; a forfeiture that would take other
    money (the Deposit holds money after the correction, or has a pay-back count) is refused
    (Q-2026-10-12-93); the forfeitures read from the targets name each forfeited receipt."""
    url = migrated_database_url
    case = closed_case(url)
    security = case["security"]
    receipt = receipt_of(url, security)
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as no_ground:
        record(
            case,
            request(
                case,
                receipt,
                receipts=(CorrectionDepositReceipt(security, 8_000, "FORFEIT", OUTCOME_REASON),),
                steps=(SettlementDepositStep(SECURITY, security, LINE, case["other_line"], 8_000),),
            ),
        )
    assert cause(no_ground) == ("55000", ONLY_REVERSED)
    assert counts(url) == before

    def entered(item: dict[str, Any]) -> tuple[Any, Any]:
        return owner_refusal(
            url,
            "SELECT app.settlement_deposit_receipt_correction_input(%s)",
            Jsonb(
                {
                    "deposit_receipt_id": str(receipt),
                    "evidence_reference": "Bank statement line 5120",
                    "receipts": [item],
                    "plan": {"steps": [], "pet_remainder": None},
                }
            ),
        )

    item = {"deposit_id": str(security), "amount_usd_cents": 8_000}
    for malformed in (
        {**item, "outcome": "FORFEIT"},
        {**item, "outcome_reason": OUTCOME_REASON},
        {**item, "outcome": "KEEP", "outcome_reason": OUTCOME_REASON},
        {**item, "outcome": 1, "outcome_reason": OUTCOME_REASON},
        {**item, "outcome": "FORFEIT", "outcome_reason": ""},
        {**item, "outcome": "FORFEIT", "outcome_reason": " padded"},
        {**item, "outcome": "FORFEIT", "outcome_reason": "x" * 501},
        {**item, "outcome": "FORFEIT", "outcome_reason": None},
    ):
        assert entered(malformed) == ("22023", INVALID_INPUT), malformed
    chosen = {**item, "outcome": "DL_032", "outcome_reason": OUTCOME_REASON}
    assert entered(chosen) == (None, None)
    assert value(
        url,
        "SELECT app.settlement_deposit_receipt_correction_input(%s)->'receipts'",
        Jsonb(
            {
                "deposit_receipt_id": str(receipt),
                "evidence_reference": "Bank statement line 5120",
                "receipts": [chosen],
                "plan": {"steps": [], "pet_remainder": None},
            }
        ),
    ) == [chosen]

    source = source_of(url, case, receipt)
    [target] = value(
        url,
        "SELECT app.settlement_deposit_receipt_correction_targets(%s,%s,%s)",
        case["prop"],
        Jsonb(source),
        Jsonb([item]),
    )
    assert (target["outcome"], target["outcome_reason"], target["payback_count"]) == (None, None, 0)
    never = {"path": {**target["path"], "ground": "BR-DEP-023", "forfeiture": "NONE"}}
    reversed_ground = {"path": {**target["path"], "ground": "BR-DEP-023", "forfeiture": "REVERSED"}}
    choice = {"outcome": "FORFEIT", "outcome_reason": OUTCOME_REASON}
    other = {"deposit_id": str(case["pet"])}
    for change, refusal in (
        ({**never, **choice}, ONLY_REVERSED),
        (choice, ONLY_REVERSED),
        (reversed_ground, NEEDS_CHOICE),
        ({**never, "payback_count": 1}, ONLY_NEW_MONEY),
        ({**reversed_ground, **choice, "payback_count": 1}, ONLY_NEW_MONEY),
        ({**never, **other, "held_usd_cents": 500}, ONLY_NEW_MONEY),
    ):
        assert targets_check(url, case, source, [{**target, **change}]) == (
            "55000",
            refusal,
        ), change
    for change in (
        never,
        {**reversed_ground, **choice},
        {**reversed_ground, "outcome": "DL_032", "outcome_reason": OUTCOME_REASON},
        {**never, **other, "held_usd_cents": 0},
    ):
        assert targets_check(url, case, source, [{**target, **change}]) == (None, None), change
    listed = value(
        url,
        "SELECT app.settlement_deposit_receipt_forfeitures(%s,%s)",
        Jsonb(
            [
                {**target, **never},
                {**target, **reversed_ground, **choice},
                {**target, **reversed_ground, "outcome": "DL_032", "outcome_reason": "Pays debt"},
                target,
            ]
        ),
        REASON,
    )
    assert [(entry["basis"], entry["reason"], entry["governing_rule"]) for entry in listed] == [
        ("TERMINATION_GROUND", REASON, "BR-DEP-023"),
        ("STAFF_CHOICE", OUTCOME_REASON, "BR-DEP-023"),
    ]


def test_receipt_forfeitures_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the new internal functions; each is SECURITY DEFINER with the fixed search
    path; the migration adds only its functions and the deposit_disposition_id link (column, key,
    unique key, the one-link check rebuilt), changes only the listed functions (privileges and
    settings kept; each patched body is exactly the old one with the module's replacements) and is
    forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261127_123"
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

    with _temporary_migration_database("settlement_deposit_receipt_forfeiture") as temporary:
        alembic_command.upgrade(config, "20261127_123")
        before_functions, before_constraints, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = catalog(temporary)
    assert after_triggers == before_triggers
    removed = before_constraints - after_constraints
    added = after_constraints - before_constraints
    assert {item.split(":")[1] for item in removed} == {"settlement_correction_effect_one_link"}
    assert {item.split(":")[1] for item in added} == {
        "settlement_correction_effect_one_link",
        "settlement_correction_effects_deposit_disposition_id_fkey",
        "settlement_correction_effects_deposit_disposition_id_key",
    }
    assert (
        "app.settlement_correction_effects:settlement_correction_effects_deposit_disposition_id_fkey:"
        "FOREIGN KEY (deposit_disposition_id) REFERENCES app.deposit_dispositions(id) "
        "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"
    ) in added
    [one_link] = [item for item in added if ":settlement_correction_effect_one_link:" in item]
    assert one_link.endswith("deposit_disposition_id) = 1))")
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED | REBUILT
    for name in PATCHED | REBUILT:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
