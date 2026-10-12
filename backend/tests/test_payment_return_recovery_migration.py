"""A Refund already paid from a returned Payment's value (V1-056 sub-slice 10e-1c).

Owner answer (a) to Q-2026-10-10-72 point 1 and owner answers A, B and C to Q-2026-10-11-78: the
person who received the refund money pays it back. A returned Payment (the PAYMENT_RETURN draft,
sub-slice 10e-1a, or the RETURNED_PAYMENT correction of the closed Final Settlement that relied on
it, sub-slice 10e-1b) recovers each Refund paid from its value that is not fully returned: a
RECOVERED_BY_CHARGE Refund correction (DB-REFUND-002 amendment) gives the Refund's net amount back
to its source on paper, and a Miscellaneous one-time charge of the same amount goes to the
Refund's recipient, issued in the same confirm: on the Lease the money came from when the
recipient is its signed Customer (an EXTRA_CHARGE inside the correction when that Lease's Final
Settlement is closed), otherwise with no Lease. The correction's own receipt reversal checks that
the Deposit belongs to the Property (owner check of 2026-10-11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.credit import CreditLedgerPage
from property_rental.deposit import QualifyPetDepositRefundReviewCommand, RecordPetDepartureCommand
from property_rental.payment_return import PaymentReturnConflictError
from property_rental.refund import CreateUsdRefundCommand, SignerRecipient
from refund_test_support import cash, create_pet_refund, create_usd_refund
from test_credit_customer_refund_migration import approving, third_party_credit
from test_credit_customer_refund_migration import command as credit_customer_refund
from test_credit_customer_refund_migration import service as credit_refunds
from test_credit_customer_refund_migration import staff as credit_refund_staff
from test_credit_migration import actor
from test_final_settlement_draft_migration import STAFF, leaving_case, normal_plan
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, today
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import wrong_allocation
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, reconciled, request, returns, status
from test_payment_return_migration import preparer as return_preparer
from test_payment_reversal_context_migration import deposit_source
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refund_service
from test_refund_signer_recipient_migration import joint_qualified
from test_reservation_lifecycle_migration import active_reservation, cancel
from test_reservation_migration import setup_reservation_sources
from test_settlement_correction_migration import settlement_row
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    record_reversal,
    reversal_command,
)
from test_settlement_real_path_migration import AGREEMENT, two_signer_kept_case
from test_settlement_refund_return_migration import net
from test_settlement_returned_payment_migration import (
    closed_case,
    command,
    confirm,
    payload,
    receipt_payment,
    record,
)

REVISION = "20261122_118"
INTERNAL = (
    "app.refund_recovery_allowed(app.refund_corrections)",
    "app.payment_return_recoveries(uuid,uuid)",
    "app.assert_payment_return_recoveries_allowed(jsonb,uuid)",
    "app.assert_payment_return_recoveries_planned(jsonb)",
    "app.write_correction_one_time_charge(uuid,uuid,uuid,uuid,uuid,uuid,text,uuid,text,bigint,"
    "date,text,text,text,text,jsonb,text,timestamp with time zone,text,text)",
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)",
    "app.write_payment_return_receipt_reversal(uuid,uuid,uuid,uuid,text,uuid,text,"
    "timestamp with time zone)",
    "app.refund_recovery_json(uuid)",
    "app.payment_return_recoveries_written(uuid)",
)
PATCHED = {
    "app.validate_general_refund_correction()",
    "app.audit_general_refund_event()",
    "app.customer_credit_ledger(uuid,uuid,uuid,integer,timestamp with time zone,text,uuid)",
    "app.payment_return_source(uuid,uuid,uuid)",
    "app.assert_payment_return_allowed(jsonb)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
    "app.confirm_payment_return(uuid,uuid,uuid,text)",
    "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
    "app.confirm_settlement_returned_payment(uuid,uuid,uuid,text)",
    "app.payment_return_result(uuid)",
    "app.settlement_returned_payment_result(uuid)",
    "app.confirm_settlement_extra_charge(uuid,uuid,uuid,text)",
    "app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,uuid,integer,integer,uuid)",
    "app.refund_resource(uuid,uuid,uuid,integer,timestamp with time zone,uuid)",
}
# The keys of a Refund correction in the whole-row reads (the staff screens accept exactly these).
CORRECTION_KEYS = {
    "id",
    "refund_id",
    "correction_kind",
    "reverses_correction_id",
    "source_balance_effect_usd_cents",
    "previous_net_refund_usd_cents",
    "resulting_net_refund_usd_cents",
    "reason",
    "evidence_reference",
    "occurred_at",
    "actor_id",
    "authorization_reference",
    "source_balance_effect_original_minor",
    "verified_return_amount_minor",
    "verified_return_currency",
    "verified_returned_at",
    "return_method_reference",
}
NOT_PLANNED = "A Refund paid from this Payment's value has no planned recovery"
RESERVATION = "A Reservation Deposit Refund paid from this Payment's value is not fully returned"
SHARED = (
    "A Deposit this Payment funded also holds another Payment's money and has a Refund that is "
    "not fully returned"
)
CLOSED = (
    "A Refund paid from this Payment's value would be charged on a Lease whose closed Final "
    "Settlement this return cannot correct"
)
# Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81): the PAYMENT_RETURN draft names the
# correction that returns such a Payment.
NAMES_CORRECTION = (
    "A Refund paid from this Payment's value would be charged on a Lease whose Final Settlement "
    "is closed; return the Payment through a returned-Payment correction of that Final Settlement"
)
ONLY_INSIDE = "A Refund is recovered by a charge only inside the return of its Payment"
DEPENDENT = "Deposit receipt has active dependent financial history"
REASON = "The bank returned the transfer"


def return_refused(prop: UUID, human: UUID, payment: object) -> tuple[Any, Any]:
    """The refusal of recording a PAYMENT_RETURN draft: SQLSTATE and message."""
    with pytest.raises(PaymentReturnConflictError) as refused:
        returns().record(prop, request(UUID(str(payment))), actor=return_preparer(human, prop))
    error = refused.value.__cause__
    assert isinstance(error, psycopg.Error)
    return error.sqlstate, error.diag.message_primary


def due_days(url: str, prop: UUID) -> int:
    return int(one(url, "SELECT one_time_charge_due_days FROM app.properties WHERE id=%s", prop)[0])


def charge(url: str, invoice: object) -> tuple[Any, ...]:
    """The recovery Invoice: Customer, Lease, category, status, total and Due Date offset."""
    return one(
        url,
        "SELECT customer_id,lease_id,primary_category,status,original_total_usd_cents,"
        "due_date-invoice_date FROM app.invoices WHERE id=%s",
        UUID(str(invoice)),
    )


def recovery_row(url: str, row: object) -> tuple[Any, ...]:
    return one(
        url,
        "SELECT correction_kind,source_balance_effect_usd_cents,previous_net_refund_usd_cents,"
        "resulting_net_refund_usd_cents,authorization_reference,recovery_obligation_id::text "
        "FROM app.refund_corrections WHERE id=%s",
        UUID(str(row)),
    )


def planned(recovery: dict[str, Any]) -> tuple[Any, ...]:
    """Who is charged, on which Lease (or none), how much, and the charge form of a plan entry."""
    return (
        recovery["source_kind"],
        recovery["recipient_customer_id"],
        recovery["lease_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
        recovery["reservation_outcome"],
        recovery["shared_deposit"],
    )


def written(recovery: dict[str, Any]) -> tuple[Any, ...]:
    """Who was charged, on which Lease (or none), how much, and the charge form of a result."""
    return (
        recovery["customer_id"],
        recovery["lease_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    )


def links(url: str, correction: object) -> tuple[Any, ...]:
    """The correction's links to the charge, its Invoice and the recovery row."""
    return one(
        url,
        "SELECT count(*) FILTER (WHERE authorized_nonrecurring_obligation_id IS NOT NULL),"
        "count(*) FILTER (WHERE invoice_id IS NOT NULL),"
        "count(*) FILTER (WHERE refund_correction_id IS NOT NULL) "
        "FROM app.settlement_correction_effects WHERE settlement_correction_id=%s",
        UUID(str(correction)),
    )


def test_a_settlement_refund_paid_from_a_bounced_payment_is_charged_back_as_an_extra_charge(
    migrated_database_url: str,
) -> None:
    """The owner's Q-2026-10-10-72 example on the real closure: the Pet Deposit (20,000, one
    Payment) paid 12,500 and 2,100 of debt and the Settlement refunded its rest (5,400); the
    Payment bounces. The RETURNED_PAYMENT correction reverses the two Deposit applications (the
    debt comes back on its lines), recovers the 5,400 Refund by an EXTRA_CHARGE of 5,400 to the
    Deposit owner on the Lease (linked, issued, the Property's Due Date days), reverses the receipt
    (the Pet Deposit ends at 0) and the Payment. The Refund stays; its net is 0. The Customer owes
    the bounced 20,000 again; the Settlement row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    prop, pet, customer, lease = case["prop"], case["pet"], case["customer"], case["lease"]
    payment = receipt_payment(url, pet)
    refund = pet_refund(case)
    before = settlement_row(url, case["settlement"])
    assert (held(url, pet), net(url, refund)) == (0, 5_400)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (0, 0)
    draft = record(case, command(case, payment))
    [plan] = payload(url, draft)["source"]["recoveries"]
    assert planned(plan) == (
        "DEPOSIT",
        str(customer),
        str(lease),
        5_400,
        "CLOSED_SETTLEMENT_LEASE",
        False,
        False,
    )
    assert (plan["refund_id"], plan["closed_final_settlement_id"]) == (
        str(refund),
        str(case["settlement"]),
    )
    result = confirm(case, draft)
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(customer), str(lease), 5_400, "EXTRA_CHARGE")
    assert recovered["refund_id"] == str(refund)
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        5_400,
        due_days(url, prop),
    )
    assert recovery_row(url, recovered["refund_correction_id"]) == (
        "RECOVERED_BY_CHARGE",
        5_400,
        5_400,
        0,
        "financial.approve",
        recovered["authorized_nonrecurring_obligation_id"],
    )
    assert links(url, result["settlement_correction"]["id"]) == (1, 1, 1)
    assert one(url, "SELECT usd_accounting_value_cents FROM app.refunds WHERE id=%s", refund) == (
        5_400,
    )
    assert (net(url, refund), held(url, pet), status(url, payment)) == (0, 0, "REVERSED")
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (
        12_500,
        2_100,
    )
    assert settlement_row(url, case["settlement"]) == before
    reconciled(url, customer)


def test_a_kept_deposit_refunded_to_the_agreed_signer_is_charged_to_that_signer(
    migrated_database_url: str,
) -> None:
    """Owner answer C to Q-2026-10-11-78: on the really closed two-Signer Lease a
    FORFEITURE_REVERSAL refunded the kept Security Deposit (10,000) to the second Signer with
    the written agreement of all Signers; the Reservation Payment that funded the Deposit
    bounces. The RETURNED_PAYMENT correction charges the 10,000 to the second Signer, who received
    it, as an EXTRA_CHARGE on the Lease; the Deposit ends at 0 and the Payment is reversed; both
    ledgers reconcile."""
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
    payment = receipt_payment(url, security)
    result = confirm(case, record(case, command(case, payment)))
    [recovered] = result["recoveries"]
    assert written(recovered) == (str(co_signer), str(lease), 10_000, "EXTRA_CHARGE")
    assert recovered["refund_id"] == paid["id"]
    assert charge(url, recovered["invoice_id"])[:5] == (
        co_signer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        10_000,
    )
    assert (net(url, UUID(str(paid["id"]))), held(url, security)) == (0, 0)
    assert status(url, payment) == "REVERSED"
    reconciled(url, case["customer"], co_signer)


def test_a_pet_refund_on_a_signed_lease_is_charged_on_the_lease_when_its_payment_bounces(
    migrated_database_url: str,
) -> None:
    """With no closed Settlement (the PAYMENT_RETURN draft): a Pet Refund-review Refund of 15,000
    was paid from the Pet Deposit (20,000, one Payment) while the Lease is signed; the Payment
    bounces. The draft plans the recovery; the confirm charges the 15,000 to the Customer who
    received it, an ordinary Miscellaneous one-time charge on the Lease, issued; the receipt
    reversal is dated after the recovery (the shared writer); the Deposit ends at 0."""
    url = migrated_database_url
    human, prop, customer, lease, deposit, review = qualified(url)
    paid = create_pet_refund(
        refund_service(),
        prop,
        pet_refund_command(deposit, review, 15_000),
        actor=actor(human, prop, "refunds.create"),
    )
    refund = refund_id(paid)
    payment = UUID(
        str(one(url, "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", deposit)[0])
    )
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert planned(plan) == ("DEPOSIT", str(customer), str(lease), 15_000, "LEASE", False, False)
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert written(recovered) == (str(customer), str(lease), 15_000, "LEASE")
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        15_000,
        due_days(url, prop),
    )
    [reversal] = cast(list[str], result["deposit_receipt_reversal_ids"])
    assert one(
        url,
        "SELECT r.occurred_at>c.occurred_at FROM app.deposit_receipt_reversals r,"
        "app.refund_corrections c WHERE r.id=%s AND c.id=%s",
        UUID(reversal),
        UUID(recovered["refund_correction_id"]),
    ) == (True,)
    assert (net(url, refund), held(url, deposit), status(url, payment)) == (0, 0, "REVERSED")
    reconciled(url, customer)


def test_a_pet_refund_paid_to_an_agreed_signer_is_charged_to_that_signer_on_the_open_lease(
    migrated_database_url: str,
) -> None:
    """Owner answer C to Q-2026-10-11-78 with no closed Settlement: a Pet Refund-review Refund of
    12,000 was paid from the Pet Deposit (20,000, one Payment) to the second Signer with the
    written agreement of all Signers while the Lease is signed; the Payment bounces. The
    PAYMENT_RETURN charges the 12,000 to that Signer, who received it (not the Primary Tenant),
    as an ordinary Miscellaneous one-time charge on the Lease, issued; the Deposit ends at 0 and
    both ledgers reconcile."""
    url = migrated_database_url
    human, prop, tenant, co_signer, deposit, review = joint_qualified(url)
    preparer = actor(human, prop, "refunds.create")
    refund_draft = refund_service().record_pet_draft(
        prop,
        pet_refund_command(deposit, review, 12_000),
        cash(refund_service(), prop, preparer),
        actor=preparer,
        recipient=SignerRecipient(co_signer, AGREEMENT),
    )
    confirmed = refund_service().confirm_draft(
        prop, UUID(str(refund_draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    refund = refund_id(cast(dict[str, object], confirmed["refund"]))
    lease = UUID(str(one(url, "SELECT lease_id FROM app.deposits WHERE id=%s", deposit)[0]))
    payment = UUID(
        str(one(url, "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", deposit)[0])
    )
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert planned(plan) == ("DEPOSIT", str(co_signer), str(lease), 12_000, "LEASE", False, False)
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert written(recovered) == (str(co_signer), str(lease), 12_000, "LEASE")
    assert charge(url, recovered["invoice_id"]) == (
        co_signer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        12_000,
        due_days(url, prop),
    )
    assert (net(url, refund), held(url, deposit), status(url, payment)) == (0, 0, "REVERSED")
    reconciled(url, tenant, co_signer)


def test_a_payment_refund_with_no_lease_is_charged_with_no_lease(
    migrated_database_url: str,
) -> None:
    """Owner answer B to Q-2026-10-11-78: a Payment that names no Lease, 300 of it refunded to the
    payer, 100 of that verified returned; the Payment bounces. The return charges the 200 still
    out (the net amount, not the original) to the payer as a Miscellaneous one-time charge with no
    Lease (nothing is refused), and reverses the Payment. The Refund's corrections read with
    exactly the keys the staff screens accept (review round 1)."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=900
        )
    refund = refund_id(
        create_usd_refund(
            refund_service(),
            prop,
            CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the unused part"),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    refund_service().verify_usd_return(
        prop, refund, returned(100), actor=actor(human, prop, "refunds.correct")
    )
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert planned(plan) == ("PAYMENT", str(customer), None, 200, "NO_LEASE", False, False)
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert written(recovered) == (str(customer), None, 200, "NO_LEASE")
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        None,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        200,
        due_days(url, prop),
    )
    assert (net(url, refund), status(url, payment)) == (0, "REVERSED")
    items = cast(
        list[dict[str, Any]],
        cast(
            dict[str, Any],
            refund_service().get(prop, refund, actor=actor(human, prop, "refunds.read"))[
                "corrections"
            ],
        )["items"],
    )
    assert [item["correction_kind"] for item in items] == [
        "RECOVERED_BY_CHARGE",
        "VALUE_CORRECTION",
    ]
    assert all(set(item) == CORRECTION_KEYS for item in items)
    reconciled(url, customer)


def test_a_third_party_payer_who_is_not_a_signed_customer_is_charged_with_no_lease(
    migrated_database_url: str,
) -> None:
    """Owner answer B to Q-2026-10-11-78, the other half: a third party's Payment names a Lease
    whose signed Customer the payer is not; 3,000 of its unallocated value is refunded to the
    payer; the Payment bounces. The return charges the 3,000 to the payer with no Lease and
    reverses the allocation and the Payment; both ledgers reconcile."""
    url = migrated_database_url
    case = wrong_allocation(url, scope="THIRD_PARTY_IDENTIFIED", amount=90_000, allocated=80_000)
    payer = UUID(
        str(one(url, "SELECT payer_customer_id FROM app.payments WHERE id=%s", case.payment)[0])
    )
    refund = refund_id(
        create_usd_refund(
            refund_service(),
            case.prop,
            CreateUsdRefundCommand(uuid4(), "PAYMENT", case.payment, 3_000, "Return the excess"),
            actor=actor(case.human, case.prop, "refunds.create"),
        )
    )
    draft = returns().record(
        case.prop, request(case.payment), actor=return_preparer(case.human, case.prop)
    )
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert planned(plan) == ("PAYMENT", str(payer), None, 3_000, "NO_LEASE", False, False)
    result = returns().confirm(
        case.prop, draft_id(draft), actor=return_approver(case.human, case.prop)
    )
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert written(recovered) == (str(payer), None, 3_000, "NO_LEASE")
    assert charge(url, recovered["invoice_id"])[:5] == (
        payer,
        None,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        3_000,
    )
    assert (net(url, refund), status(url, case.payment)) == (0, "REVERSED")
    assert outstanding(url, case.line_wrong) == 80_000
    reconciled(url, payer, case.customer_wrong)


def test_a_recovered_credit_refund_shows_in_the_credit_history(
    migrated_database_url: str,
) -> None:
    """Owner answer A to Q-2026-10-11-78: a third-party Payment's released Credit (the Invoice
    Customer's), 3,000 of it refunded to that Customer; the Payment bounces. The charge goes to
    the Invoice Customer on the Lease of the Invoice whose release created the Credit; the
    Credit's history shows the recovery as REFUND_RECOVERED_BY_CHARGE (+3,000), and the Credit
    ledger cursor accepts that event family; both ledgers reconcile."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    choice = cash(credit_refunds(), case.prop, credit_refund_staff(case))
    refunded = credit_refunds().record_credit_customer_draft(
        case.prop, credit_customer_refund(credit, 3_000), choice, actor=credit_refund_staff(case)
    )
    credit_refunds().confirm_draft(case.prop, draft_id(refunded), actor=approving(case))
    invoice_customer, invoice_lease = one(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", case.invoice_wrong
    )
    draft = returns().record(
        case.prop, request(case.payment), actor=return_preparer(case.human, case.prop)
    )
    result = returns().confirm(
        case.prop, draft_id(draft), actor=return_approver(case.human, case.prop)
    )
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert written(recovered) == (str(invoice_customer), str(invoice_lease), 3_000, "LEASE")
    with psycopg.connect(url) as connection:
        events = connection.execute(
            "SELECT event_kind,balance_effect_usd_cents,event_id,occurred_at FROM "
            "app.credit_history_events(%s) WHERE event_kind='REFUND_RECOVERED_BY_CHARGE'",
            (credit,),
        ).fetchall()
        assert [(kind, effect) for kind, effect, _, _ in events] == [
            ("REFUND_RECOVERED_BY_CHARGE", 3_000)
        ]
        page = connection.execute(
            "SELECT app.customer_credit_ledger(%s,%s,%s,10,%s,'REFUND_RECOVERED_BY_CHARGE',%s)",
            (case.prop, credit, case.human, events[0][3], events[0][2]),
        ).fetchone()
        assert page is not None
    reconciled(url, invoice_customer)


def test_the_cases_a_return_still_refuses(migrated_database_url: str) -> None:
    """The recoveries a return may not write (55000): a Reservation outcome Refund
    (Q-2026-10-11-81), a Refund of a Deposit another Payment also funded, and a charge on a Lease
    whose closed Final Settlement the return cannot correct (the PAYMENT_RETURN draft: any, with a
    message that names the correction since sub-slice 10e-4; a correction: another Settlement's).
    A charge on the correction's own Settlement's Lease, on an open Lease or with no Lease passes.
    The PAYMENT_RETURN check refuses the same."""
    url = migrated_database_url
    settlement, other = str(uuid4()), str(uuid4())
    base = {
        "source_kind": "DEPOSIT",
        "recipient_customer_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "amount_usd_cents": 100,
        "charge": "LEASE",
        "closed_final_settlement_id": None,
        "reservation_outcome": False,
        "shared_deposit": False,
    }

    def check(recovery: dict[str, Any], settlement_id: str | None) -> tuple[Any, Any]:
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "SELECT app.assert_payment_return_recoveries_allowed(%s,%s)",
                    (Jsonb([{**base, **recovery}]), settlement_id),
                )
            except psycopg.Error as refused:
                return refused.sqlstate, refused.diag.message_primary
        return None, None

    closed = {"charge": "CLOSED_SETTLEMENT_LEASE", "closed_final_settlement_id": settlement}
    assert check({"reservation_outcome": True}, None) == ("55000", RESERVATION)
    assert check({"shared_deposit": True}, None) == ("55000", SHARED)
    # Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81; changed expectation, was CLOSED): the
    # PAYMENT_RETURN draft's message names the correction.
    assert check(closed, None) == ("55000", NAMES_CORRECTION)
    assert check(closed, other) == ("55000", CLOSED)
    assert check(closed, settlement) == (None, None)
    assert check({}, None) == (None, None)
    assert check({"lease_id": None, "charge": "NO_LEASE"}, None) == (None, None)
    source = {
        "payment": {"status": "RECEIVED", "refunded_usd_cents": 0},
        "credits": [],
        "deposits": [],
        "relied_on": [],
        "pending_drafts": [],
        "recoveries": [{**base, **closed}],
    }
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute("SELECT app.assert_payment_return_allowed(%s)", (Jsonb(source),))
    # Sub-slice 10e-4: changed expectation, was CLOSED.
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
        "55000",
        NAMES_CORRECTION,
    )
    # The cross-check (review round 1): a Refund out with no planned recovery is refused.
    for missed in (
        {"payment": {"status": "RECEIVED", "refunded_usd_cents": 100}, "recoveries": []},
        {"credits": [{"id": str(uuid4()), "refunded_usd_cents": 100}], "recoveries": []},
        {
            "deposits": [
                {
                    "id": str(uuid4()),
                    "active_forfeiture": False,
                    "unresolved_refund": True,
                    "active_application": False,
                }
            ],
            "recoveries": [],
        },
    ):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as unplanned:
                connection.execute(
                    "SELECT app.assert_payment_return_allowed(%s)", (Jsonb({**source, **missed}),)
                )
        assert (unplanned.value.sqlstate, unplanned.value.diag.message_primary) == (
            "55000",
            NOT_PLANNED,
        ), missed


def test_the_refused_cases_on_real_sources(migrated_database_url: str) -> None:
    """Review round 1: each refusal on a real source, with nothing written for a refused case.
    (1) A cancelled Reservation's Deposit Refund (the Reservation outcome path, Q-2026-10-11-81).
    (2) A Pet Refund-review Refund of a Deposit two Payments funded. (3) A Payment that names a
    Lease whose Final Settlement is closed, refunded in part to its signed Customer after closure:
    the PAYMENT_RETURN draft refuses it and names the correction; since sub-slice 10e-4 (owner
    answer (c) to Q-2026-10-11-81) the correction of that Settlement records it, although the
    Settlement did not rely on the Payment (its confirm is checked in
    test_returned_payment_after_closure_migration.py)."""
    url = migrated_database_url
    with psycopg.connect(url) as setup:
        human, prop, _, _, reservation = active_reservation(setup)
        setup.commit()
    with psycopg.connect(financial_database_url()) as runtime:
        cancel(
            runtime,
            actor_id=human,
            property_id=prop,
            reservation_id=reservation,
            idempotency_key=uuid4(),
            event_id=uuid4(),
            responsibility="PROPERTY",
            property_could_provide_unit=False,
            coordination_reference="CASE-RETURN-1",
        )
        runtime.commit()
    reservation_payment = one(
        url,
        "SELECT receipt.payment_id FROM app.deposit_receipts receipt "
        "JOIN app.deposits deposit ON deposit.id=receipt.deposit_id "
        "WHERE deposit.reservation_id=%s",
        reservation,
    )[0]
    assert return_refused(prop, human, reservation_payment) == ("55000", RESERVATION)

    service, staff, _, deposit, shared_payment, _ = deposit_source(url)
    departure = RecordPetDepartureCommand(
        uuid4(), uuid4(), deposit, today(url), "Pet permanently left"
    )
    service.record_pet_departure(departure, actor=staff)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        deposit,
        30_000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    service.qualify_pet_refund_review(review, actor=staff)
    create_pet_refund(
        refund_service(),
        service.property_id,
        pet_refund_command(deposit, review.review_id, 5_000),
        actor=actor(service.actor_id, service.property_id, "refunds.create"),
    )
    assert return_refused(service.property_id, service.actor_id, shared_payment) == (
        "55000",
        SHARED,
    )

    case = closed_case(url)
    with psycopg.connect(url) as connection:
        late = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=case["customer"],
            amount=900,
            scope="THIRD_PARTY_IDENTIFIED",
            lease_id=case["lease"],
        )
    create_usd_refund(
        refund_service(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "PAYMENT", late, 300, "Return the unused part"),
        actor=actor(case["human"], case["prop"], "refunds.create"),
    )
    # Sub-slice 10e-4 (owner answer (c) to Q-2026-10-11-81; changed expectations, were CLOSED and
    # the correction's NOT_RELIED refusal): the PAYMENT_RETURN draft names the correction, and the
    # correction records the Payment, its 300 Refund planned as an EXTRA_CHARGE on this Lease.
    assert return_refused(case["prop"], case["human"], late) == ("55000", NAMES_CORRECTION)
    draft = record(case, command(case, late))
    [plan] = payload(url, draft)["source"]["recoveries"]
    assert planned(plan) == (
        "PAYMENT",
        str(case["customer"]),
        str(case["lease"]),
        300,
        "CLOSED_SETTLEMENT_LEASE",
        False,
        False,
    )
    assert one(
        url,
        "SELECT count(*) FROM app.payment_returns WHERE payment_id IN (%s,%s,%s)",
        reservation_payment,
        shared_payment,
        late,
    ) == (0,)
    assert one(
        url,
        "SELECT count(*) FROM app.financial_drafts WHERE kind IN ('PAYMENT_RETURN',"
        "'SETTLEMENT_CORRECTION') AND payload->>'payment_id' IN (%s,%s)",
        str(reservation_payment),
        str(shared_payment),
    ) == (0,)
    assert one(
        url,
        "SELECT count(*),min(id::text) FROM app.financial_drafts WHERE kind IN "
        "('PAYMENT_RETURN','SETTLEMENT_CORRECTION') AND payload->>'payment_id'=%s",
        str(late),
    ) == (1, str(draft))


def test_a_recovery_is_written_only_inside_the_return_of_its_payment(
    migrated_database_url: str,
) -> None:
    """A RECOVERED_BY_CHARGE row outside a confirmed return of the Refund's Payment is refused
    (23514), even naming a charge of the right Customer and amount, also inside the confirmed
    return of another Payment; the kind needs its charge and the other kinds take none (23514,
    also the table's shape check for a valid return); nothing is written."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        human, prop, _, customer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=900
        )
    refund = refund_id(
        create_usd_refund(
            refund_service(),
            prop,
            CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the unused part"),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    obligation = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.record_one_time_charge(%s,%s,%s,'MISCELLANEOUS_CHARGES',%s,NULL,NULL,"
            "'A charge of the right amount',300,'Recorded by hand','Evidence 1')",
            (prop, human, obligation, customer),
        )

    def insert(kind: str, linked: UUID | None) -> tuple[Any, Any]:
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
                    "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
                    "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,"
                    "evidence_reference,occurred_at,actor_id,authorization_reference,"
                    "recovery_obligation_id) VALUES (gen_random_uuid(),%s,%s,300,300,300,0,"
                    "'Charged back by hand','Evidence 1',clock_timestamp(),%s,"
                    "'financial.approve',%s)",
                    (refund, kind, human, linked),
                )
            except psycopg.Error as refused:
                return refused.sqlstate, refused.diag.message_primary
        return None, None

    assert insert("RECOVERED_BY_CHARGE", obligation) == ("23514", ONLY_INSIDE)
    assert insert("RECOVERED_BY_CHARGE", None)[0] == "23514"
    assert insert("VALUE_CORRECTION", obligation)[0] == "23514"
    # Review round 1 (N7): a VALUE_CORRECTION with valid return evidence that names a charge
    # passes the correction check and is refused by the table's shape check.
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as shaped:
            connection.execute(
                "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
                "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
                "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,"
                "evidence_reference,occurred_at,actor_id,authorization_reference,"
                "verified_return_amount_minor,verified_return_currency,verified_returned_at,"
                "return_method_reference,recovery_obligation_id) VALUES (gen_random_uuid(),%s,"
                "'VALUE_CORRECTION',100,100,300,200,'Returned by the bank','Evidence 1',"
                "clock_timestamp(),%s,'refunds.correct',100,'USD',statement_timestamp(),"
                "'Bank return 1',%s)",
                (refund, human, obligation),
            )
    assert (shaped.value.sqlstate, shaped.value.diag.constraint_name) == (
        "23514",
        "refund_recovery_obligation_shape",
    )
    # Review round 1 (N7, security): inside the confirmed return of another Payment of the same
    # payer (as the owner, in one transaction), a refund-recovery charge for this Refund and a
    # RECOVERED_BY_CHARGE row naming it are refused, because the return is not of this Refund's
    # Payment; the whole transaction rolls back.
    with psycopg.connect(url) as connection:
        other = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=customer, amount=500
        )
    other_draft = returns().record(prop, request(other), actor=return_preparer(human, prop))
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as outside:
            connection.execute(
                "SELECT app.confirm_payment_return(%s,%s,%s,'financial.approve')",
                (prop, human, draft_id(other_draft)),
            )
            written_charge = connection.execute(
                "SELECT app.write_correction_one_time_charge(%s,%s,NULL,%s,%s,NULL,"
                "'MISCELLANEOUS_CHARGES',NULL,'Recovery by hand',300,NULL,NULL,'By hand',"
                "'Evidence 1','refund-recovery:' || %s::text,'{}'::jsonb,"
                "(SELECT timezone_name FROM app.properties WHERE id=%s),clock_timestamp(),"
                "'Created by hand','Issued by hand')",
                (prop, human, draft_id(other_draft), customer, refund, prop),
            ).fetchone()
            assert written_charge is not None
            connection.execute(
                "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,"
                "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
                "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,"
                "evidence_reference,occurred_at,actor_id,authorization_reference,"
                "recovery_obligation_id) VALUES (gen_random_uuid(),%s,'RECOVERED_BY_CHARGE',300,"
                "300,300,0,'Charged back by hand','Evidence 1',clock_timestamp(),%s,"
                "'financial.approve',%s)",
                (refund, human, UUID(str(written_charge[0]["obligation_id"]))),
            )
    assert (outside.value.sqlstate, outside.value.diag.message_primary) == ("23514", ONLY_INSIDE)
    assert status(url, other) == "RECEIVED"
    assert net(url, refund) == 300
    assert one(url, "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s", refund) == (
        0,
    )


def test_the_direct_receipt_reversal_path_is_refused_in_a_bad_state(
    migrated_database_url: str,
) -> None:
    """The owner check of 2026-10-11, on the shared receipt reversal writer that the correction
    and the PAYMENT_RETURN confirm use (called directly, as the owner): a Deposit of another
    Property is not found (P0002, the explicit check), a blank reason is invalid (22023), a
    Deposit with a waiting Final Settlement draft has active dependent history (55000) and a
    closed Final Settlement's receipt needs a linked correction (P5S01), both from the shared
    BEFORE INSERT check; nothing is written."""
    url = migrated_database_url
    case = leaving_case(url)
    record_settlement(case, normal_plan(case), pet_remainder=STAFF)
    open_receipt = UUID(
        str(one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["pet"])[0])
    )
    closed = closed_case(url)
    closed_receipt = UUID(
        str(
            one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", closed["security"])[
                0
            ]
        )
    )

    def direct(prop: UUID, human: UUID, receipt: UUID, reason: str) -> tuple[Any, Any]:
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "SELECT app.write_payment_return_receipt_reversal(%s,%s,NULL,%s,%s,%s,"
                    "'digest',clock_timestamp())",
                    (prop, human, receipt, reason, uuid4()),
                )
            except psycopg.Error as refused:
                return refused.sqlstate, refused.diag.message_primary
        return None, None

    # The fixtures share one Property, so another Property is one the Deposit is not of.
    assert direct(uuid4(), case["human"], open_receipt, REASON) == (
        "P0002",
        "Deposit receipt was not found",
    )
    assert direct(case["prop"], case["human"], open_receipt, " ") == (
        "22023",
        "Deposit receipt reversal evidence is invalid",
    )
    assert direct(case["prop"], case["human"], open_receipt, REASON) == ("55000", DEPENDENT)
    assert direct(closed["prop"], closed["human"], closed_receipt, REASON) == (
        "P5S01",
        "A closed Final Settlement's Deposit receipt changes only through a post-settlement "
        "correction",
    )
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_receipt_reversals WHERE deposit_receipt_id IN (%s,%s)",
        open_receipt,
        closed_receipt,
    ) == (0,)


def test_the_credit_ledger_cursor_accepts_a_recovered_refund_event() -> None:
    """The Credit ledger cursor names the new event family (no database needed)."""
    page = CreditLedgerPage(
        after_at=datetime.now(UTC), after_kind="REFUND_RECOVERED_BY_CHARGE", after_id=uuid4()
    )
    assert page.after_kind == "REFUND_RECOVERED_BY_CHARGE"


def test_refund_recoveries_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the new internal functions (their only privilege entry is the owner's); the
    refund correction table gains only the new
    kind, its charge column and their checks; the migration adds the listed functions, changes
    only the listed ones (each exactly as its patch says, privileges and settings kept) and is
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
            # Review round 1 (security note): the only entry of the function's privileges is
            # its owner's.
            assert connection.execute(
                "SELECT count(*) FILTER (WHERE acl.grantee=p.proowner),"
                "count(*) FILTER (WHERE acl.grantee<>p.proowner) "
                "FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) acl "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (1, 0), function
        checks: dict[str, str] = dict(
            connection.execute(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.refund_corrections'::regclass AND conname IN ("
                "'refund_corrections_correction_kind_check','reservation_refund_correction_shape',"
                "'refund_recovery_obligation_shape')"
            ).fetchall()
        )
    assert "RECOVERED_BY_CHARGE" in checks["refund_corrections_correction_kind_check"]
    assert "RECOVERED_BY_CHARGE" in checks["reservation_refund_correction_shape"]
    assert "recovery_obligation_id IS NOT NULL" in checks["refund_recovery_obligation_shape"]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261121_117"
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

    with _temporary_migration_database("payment_return_recovery") as temporary:
        alembic_command.upgrade(config, "20261121_117")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    module = revision.module
    spans = {signature: (start, end, block) for signature, start, end, block in module.SPANS}
    patches = dict(module.PATCHES)
    for name in PATCHED:
        body = str(before_functions[name][0])
        if name in spans:
            start, end, block = spans[name]
            body = body[: body.index(start)] + block + body[body.index(end) + len(end) :]
        for anchor, replacement in patches.get(name, ()):
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
        assert after_functions[name][1:] == before_functions[name][1:], name
