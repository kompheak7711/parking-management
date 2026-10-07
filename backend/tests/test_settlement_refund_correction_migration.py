"""Post-settlement correction: Refund of a paid wrong charge (V1-056 sub-slice 10c-1b).

BR-SETTLE-013 (owner answer 1 to Q-2026-10-06-36): a wrong charge that was paid when a Final
Settlement closed is fixed by a REFUND correction. Staff record it under final_settlements.prepare
with a reason, a Refund method and a reference note; only a financial.approve holder confirms it
(BR-AUTH-010). The confirmation writes, each linked to the correction (DB-SETTLE-005), the release
of the paid part as a credit Adjustment always releases it (newest first), the credit Adjustment,
and one Credit Refund per released source, paid to that Credit's Customer (BR-CREDIT-014,
BR-CREDIT-008) with its own details row (BR-REFUND-014; owner answer 1 to Q-2026-10-07-39). The
re-posted remainder of a Settlement Credit application cannot be reversed with one call (owner
answer 2 to Q-2026-10-07-39). The closed Settlement is never changed (BR-SETTLE-012).
"""

from __future__ import annotations

import re
from dataclasses import replace
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
from property_rental.credit import CreditConflictError, ReverseCreditApplicationCommand
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
)
from property_rental.invoice import AdjustInvoiceCommand, AdjustmentType, InvoiceConflictError
from property_rental.settlement_correction import RecordRefundCorrectionCommand
from test_credit_application_migration import application_id
from test_credit_application_migration import designated as credit_designated
from test_credit_customer_refund_migration import third_party_credit
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled, history
from test_final_settlement_closed_refusal_migration import close, closed_refusal
from test_final_settlement_credit_application_migration import decide, write
from test_final_settlement_draft_migration import STAFF, leaving_case, normal_plan
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import apply, one, outstanding, preparer
from test_final_settlement_preview_migration import credit_adjustment, pay
from test_invoice_migration import invoice_api_actor, runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import invoices
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_settlement_charge_reduction_migration import invoice_of
from test_settlement_correction_migration import approver, correction_draft, count, settlement_row
from test_settlement_extra_charge_migration import (
    approving,
    cause,
    corrections,
    extra_charge,
    state,
)
from test_settlement_extra_charge_migration import record as record_extra_charge
from test_unpaid_initial_termination_migration import rent_line

RECORD = "app.record_settlement_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_refund(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.reject_settlement_correction_refund_detail_mutation()",
    "app.validate_settlement_correction_refund_detail()",
    "app.assert_settlement_correction_refund_detail()",
    "app.settlement_correction_refund_allowed(app.refunds)",
    "app.refuse_settlement_credit_application_remainder_reversal()",
    "app.settlement_refund_input(jsonb)",
    "app.settlement_refund_line_sources(uuid,uuid)",
    "app.settlement_refund_source_state(uuid,uuid,uuid)",
    "app.settlement_refund_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_result(uuid)",
)
CHANGED = (
    "app.validate_general_refund_source()",
    "app.assert_credit_customer_refund_confirmed()",
)
REASON = "The window latch was charged twice and paid"
NOTE = "Cash handed over at the front desk"
NOTHING_RELEASED = (
    "The Refund correction releases no paid value; an unpaid charge is removed by a charge "
    "reduction"
)
REVERSAL_REFUSED = (
    "A Final Settlement Credit application changes only through a post-settlement correction"
)
BEGIN = "SELECT app.begin_settlement_correction(%s,%s,%s,'financial.approve')"
LINK = "SELECT app.link_settlement_correction_effect(%s,'refund_id',%s)"
DETAIL = (
    "INSERT INTO app.settlement_correction_refund_details(refund_id,settlement_correction_id,"
    "draft_id,refund_method_id,reference_note,recorded_at) "
    "VALUES (%s,%s,%s,%s,%s,clock_timestamp())"
)
DIRECT_REFUND = (
    "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,source_customer_credit_id,"
    "usd_accounting_value_cents,refund_currency,refund_amount_minor,reason,processed_at,"
    "processed_by,authorization_reference) VALUES (%s,%s,%s,%s,100,'USD',100,'Direct',"
    "clock_timestamp(),%s,'refunds.create')"
)
LINKS = (
    "payment_allocation_reversal_id",
    "credit_application_reversal_id",
    "invoice_adjustment_id",
    "payment_allocation_id",
    "customer_credit_application_id",
    "refund_id",
)


def correction(
    case: dict[str, Any], invoice: UUID, line: UUID, amount: int, **changes: Any
) -> RecordRefundCorrectionCommand:
    return replace(
        RecordRefundCorrectionCommand(
            uuid4(), case["settlement"], invoice, line, amount, case["cash"], NOTE, REASON
        ),
        **changes,
    )


def record(case: dict[str, Any], command: RecordRefundCorrectionCommand) -> UUID:
    found = corrections().record_refund(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], person: UUID, draft: UUID) -> dict[str, Any]:
    return corrections().confirm_refund(case["prop"], draft, actor=approving(person, case["prop"]))


def effects(url: str, correction_id: object) -> list[tuple[int, str]]:
    """Each effect of the correction, in order, with the name of its one link."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT effect_sequence,{','.join(LINKS)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction_id,),
        ).fetchall()
    return [
        (int(row[0]), next(name for name, value in zip(LINKS, row[1:], strict=True) if value))
        for row in rows
    ]


def refunds_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["refunds"])


def released_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["released_sources"])


def available(url: str, credit: object) -> int:
    return int(one(url, "SELECT app.credit_available_value(%s)", credit)[0])


def obligation(url: str, line: UUID) -> int:
    return int(one(url, "SELECT app.invoice_adjusted_line_obligation(%s)", line)[0])


def ledger_event_ids(url: str, customer: UUID) -> set[str]:
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
        return {str(event["event_id"]) for event in history(connection, customer)}


def third_party_payment(
    url: str, case: dict[str, Any], invoice: UUID, line: UUID, amount: int
) -> tuple[UUID, UUID]:
    """A Payment by a third party identified for the Lease, allocated to the line."""
    payer = uuid4()
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
            "VALUES (%s,'Third-party payer',%s,%s)",
            (payer, case["human"], case["human"]),
        )
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=payer,
            amount=amount,
            scope="THIRD_PARTY_IDENTIFIED",
            lease_id=case["lease"],
        )
    allocations().post(
        case["prop"],
        payment,
        designated(invoice, line, amount),
        actor=allocation_actor(case["human"], case["prop"]),
    )
    return payer, payment


def third_party_released_credit(url: str, case: dict[str, Any]) -> tuple[UUID, UUID]:
    """Before closure, a third-party Payment pays the other Damage line and an ordinary credit
    Adjustment of 400 releases a Credit to the Invoice Customer, who is not the payer."""
    other = case["other_line"]
    other_invoice = invoice_of(url, other)
    payer, payment = third_party_payment(url, case, other_invoice, other, 12_500)
    credit_adjustment(url, case["human"], case["prop"], other_invoice, other)
    credit = UUID(
        str(
            one(
                url,
                "SELECT release.customer_credit_id FROM app.invoice_credit_excess_releases release "
                "JOIN app.payment_allocations allocation "
                "ON allocation.id=release.reversed_payment_allocation_id "
                "WHERE allocation.payment_id=%s",
                payment,
            )[0]
        )
    )
    assert one(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == (
        case["customer"],
    )
    assert payer != case["customer"]
    return payer, credit


def apply_credit(
    case: dict[str, Any], credit: object, invoice: UUID, line: UUID, amount: int
) -> UUID:
    """An ordinary Credit application designated by the Customer (credits.apply)."""
    return application_id(
        credits().apply(
            case["prop"],
            UUID(str(credit)),
            credit_designated(invoice, line, amount),
            actor=credit_actor(case["human"], case["prop"], "credits.apply"),
        )
    )


def reverse_application(case: dict[str, Any], application: object) -> None:
    credits().reverse_application(
        case["prop"],
        UUID(str(application)),
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(case["human"], case["prop"], "credits.applications.reverse"),
    )


def test_a_refund_correction_releases_a_paid_wrong_charge_and_refunds_it_to_the_invoice_customer(
    migrated_database_url: str,
) -> None:
    """Owner answer 1 to Q-2026-10-06-36 and BR-CREDIT-014: Staff record the Refund correction as
    a draft with no effect; Staff cannot confirm it; a financial.approve holder confirms it, which
    reverses the Payment allocation that paid the line, re-posts its unreleased rest, recognizes
    the released value as the Invoice Customer's Credit, writes the credit Adjustment and pays the
    Credit back in one Refund with the draft's method and note, every record linked to the
    correction; the Settlement row stays unchanged; an exact repeat replays. An open Settlement,
    an unpaid line (a charge reduction), more than the line's charge, an unknown Refund method and
    malformed input are refused; the one-call Adjustment stays refused after closure."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    person = approver(url)
    invoice = case["initial"]
    rent, rest = rent_line(url, invoice)
    assert rest == 0
    charge = obligation(url, rent)
    command = correction(case, invoice, rent, 1_000)
    with pytest.raises(FinalSettlementConflictError) as still_open:
        record(case, command)
    assert cause(still_open) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    close(url, human, case["settlement"])
    # The database refuses malformed input on its own and writes no draft.
    drafts_before = count(url, "SELECT count(*) FROM app.financial_drafts")
    good = command.refund()
    for malformed in (
        {**good, "surprise": True},
        {**good, "amount_usd_cents": 0},
        {**good, "amount_usd_cents": "1000"},
        {**good, "amount_usd_cents": 9_000_000_000_000_001},
        {**good, "refund_method_id": None},
        {**good, "reference_note": " padded"},
        {**good, "reference_note": "x" * 501},
        {**good, "reference_note": 7},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_refund_draft(%s,%s,%s,%s,%s,%s,"
                "'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    assert count(url, "SELECT count(*) FROM app.financial_drafts") == drafts_before
    # Nothing paid on the line would be released: that is a charge reduction, not a Refund.
    other = case["other_line"]
    with pytest.raises(FinalSettlementConflictError) as unpaid:
        record(case, correction(case, invoice_of(url, other), other, 1_000))
    assert cause(unpaid) == ("55000", NOTHING_RELEASED)
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, correction(case, invoice, rent, charge + 1))
    assert cause(too_much) == ("55000", "The Refund correction exceeds the charge on the line")
    with pytest.raises(FinalSettlementConflictError) as no_method:
        record(case, correction(case, invoice, rent, 1_000, refund_method_id=uuid4()))
    assert cause(no_method) == ("55000", "Refund Method is not active")

    allocation, allocated, payment = one(
        url,
        "SELECT allocation.id,allocation.amount_usd_cents,allocation.payment_id "
        "FROM app.payment_allocations allocation JOIN app.payment_allocation_details detail "
        "ON detail.payment_allocation_id=allocation.id WHERE detail.invoice_line_id=%s "
        "AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal "
        "WHERE reversal.payment_allocation_id=allocation.id)",
        rent,
    )
    before = settlement_row(url, case["settlement"])
    refunds_before = count(url, "SELECT count(*) FROM app.refunds")
    draft = record(case, command)
    assert state(url, draft) == "PENDING"
    assert count(url, "SELECT count(*) FROM app.refunds") == refunds_before
    stored = one(
        url,
        "SELECT kind,prepare_capability,reason,payload->>'variant',payload->>'customer_id',"
        "payload->'released_sources' FROM app.financial_drafts WHERE id=%s",
        draft,
    )
    assert stored[:5] == (
        "SETTLEMENT_CORRECTION",
        "final_settlements.prepare",
        REASON,
        "REFUND",
        str(customer),
    )
    assert stored[5] == [
        {
            "kind": "PAYMENT_ALLOCATION",
            "id": str(allocation),
            "payment_id": str(payment),
            "credit_id": None,
            "recipient_customer_id": str(customer),
            "payer_customer_id": str(customer),
            "released_usd_cents": 1_000,
        }
    ]
    # Staff cannot confirm: the service refuses before any connection, and the database refuses
    # any other authorization reference; the recorder takes only final_settlements.prepare.
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_refund(prop, draft, actor=preparer(human, prop))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_refund(%s,%s,%s,%s)",
            (prop, human, draft, "final_settlements.prepare"),
        )
    assert staff.value.sqlstate == "42501"
    for authorization in ("financial.approve", "refunds.create", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.record_settlement_refund_draft(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert state(url, draft) == "PENDING"

    result = confirm(case, person, draft)
    header = cast(dict[str, Any], result["settlement_correction"])
    correction_id = UUID(str(header["id"]))
    adjustment = UUID(str(cast(dict[str, Any], result["invoice_adjustment"])["id"]))
    decision = cast(dict[str, Any], cast(dict[str, Any], result["draft"])["decision"])
    assert decision["decision"] == "CONFIRMED" and "transaction_id" not in decision["result"]
    assert one(
        url,
        "SELECT invoice_id,invoice_line_id,adjustment_type,amount_usd_cents,source_reference,"
        "reason,actor_id,authorization_reference FROM app.invoice_adjustments WHERE id=%s",
        adjustment,
    ) == (
        invoice,
        rent,
        "CREDIT",
        1_000,
        f"settlement-correction:{correction_id}",
        REASON,
        person,
        "financial.approve",
    )
    [source] = released_of(result)
    credit = UUID(str(source["customer_credit_id"]))
    remainder = UUID(str(source["replacement_payment_allocation_id"]))
    assert (source["source_kind"], source["reversed_payment_allocation_id"]) == (
        "PAYMENT_ALLOCATION",
        str(allocation),
    )
    assert source["released_usd_cents"] == 1_000
    assert one(
        url,
        "SELECT payment_id,amount_usd_cents FROM app.payment_allocations WHERE id=%s",
        remainder,
    ) == (payment, int(allocated) - 1_000)
    assert one(
        url,
        "SELECT customer_id,source_payment_id,recognized_usd_cents,authorization_reference "
        "FROM app.customer_credits WHERE id=%s",
        credit,
    ) == (customer, payment, 1_000, "credits.recognize")
    [paid] = refunds_of(result)
    refund = UUID(str(paid["id"]))
    assert one(
        url,
        "SELECT recipient_customer_id,source_customer_credit_id,source_payment_id,"
        "usd_accounting_value_cents,refund_currency,reason,processed_by,authorization_reference "
        "FROM app.refunds WHERE id=%s",
        refund,
    ) == (customer, credit, None, 1_000, "USD", REASON, person, "refunds.create")
    assert one(
        url,
        "SELECT settlement_correction_id,draft_id,refund_method_id,reference_note "
        "FROM app.settlement_correction_refund_details WHERE refund_id=%s",
        refund,
    ) == (correction_id, draft, case["cash"], NOTE)
    assert (paid["refund_method_id"], paid["reference_note"]) == (str(case["cash"]), NOTE)
    assert effects(url, correction_id) == [
        (1, "payment_allocation_reversal_id"),
        (2, "invoice_adjustment_id"),
        (3, "payment_allocation_id"),
        (4, "refund_id"),
    ]
    assert available(url, credit) == 0
    assert (obligation(url, rent), outstanding(url, rent)) == (charge - 1_000, 0)
    with psycopg.connect(url) as connection:
        audits = connection.execute(
            "SELECT action,authorization_reference FROM app.audit_events "
            "WHERE correlation_id=%s ORDER BY action",
            (correction_id,),
        ).fetchall()
    assert audits == [
        ("final_settlement.correction.confirmed", "financial.approve"),
        ("invoice.adjusted", "financial.approve"),
    ]
    # The correction's audit event names every released source, re-post, Credit and Refund
    # (design note point 2; review round 1).
    confirmed = one(
        url,
        "SELECT resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction_id,
    )[0]
    assert confirmed["released_sources"] == result["released_sources"]
    assert [item["refund_id"] for item in confirmed["refunds"]] == [str(refund)]
    # The Credit and its Refund are on the Invoice Customer's Customer Ledger.
    assert {str(credit), str(refund)} <= ledger_event_ids(url, customer)
    assert settlement_row(url, case["settlement"]) == before
    assert state(url, draft) == "CONFIRMED"
    # An exact repeat by the same approver replays; another approver finds the draft decided.
    assert confirm(case, person, draft) == result
    replayed = corrections().record_refund(prop, command, actor=preparer(human, prop))
    assert replayed["state"] == "CONFIRMED"
    with pytest.raises(FinalSettlementConflictError):
        confirm(case, human, draft)
    assert count(url, "SELECT count(*) FROM app.refunds") == refunds_before + 1
    # The one-call credit Adjustment is not linked, so the 8e-1 refusal still holds.
    closed_refusal(InvoiceConflictError, credit_adjustment, url, human, prop, invoice, rent)


def test_one_refund_correction_pays_a_payment_and_a_settlement_credit_back_in_two_refunds(
    migrated_database_url: str,
) -> None:
    """Staff need not split a correction by hand (owner answer 1 to Q-2026-10-07-39): a line paid
    by a Payment after closure and by the Settlement's Credit application is released newest
    first and refunded in two Refunds, each with its own details row. The Settlement Credit
    application is reversed only because it is linked, and its re-posted rest is an ordinary
    Credit application whose one-call reversal is refused (owner answer 2 to Q-2026-10-07-39),
    also after a second correction re-posts it again."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    person = approver(url)
    settlement_draft = record_settlement(case, normal_plan(case), pet_remainder=STAFF)["draft_id"]
    with psycopg.connect(url) as connection:
        decide(connection, case, settlement_draft)
        settlement_application = UUID(write(connection, case, settlement_draft, 1)["id"])
    close(url, human, case["settlement"])
    line = case["other_line"]
    invoice = invoice_of(url, line)
    assert outstanding(url, line) == 12_100
    payment = pay(url, prop, human, customer, invoice, line, 12_100)
    assert outstanding(url, line) == 0

    result = confirm(case, person, record(case, correction(case, invoice, line, 12_300)))
    correction_id = UUID(str(cast(dict[str, Any], result["settlement_correction"])["id"]))
    allocation_source, application_source = released_of(result)
    assert (
        allocation_source["source_kind"],
        allocation_source["released_usd_cents"],
        allocation_source["replacement_payment_allocation_id"],
    ) == ("PAYMENT_ALLOCATION", 12_100, None)
    assert (
        application_source["source_kind"],
        application_source["reversed_credit_application_id"],
        application_source["customer_credit_id"],
        application_source["released_usd_cents"],
    ) == ("CREDIT_APPLICATION", str(settlement_application), str(case["credit"]), 200)
    remainder = UUID(str(application_source["replacement_credit_application_id"]))
    assert one(
        url,
        "SELECT customer_credit_id,amount_usd_cents,final_settlement_id,authorization_reference "
        "FROM app.customer_credit_applications WHERE id=%s",
        remainder,
    ) == (case["credit"], 200, None, "credits.apply")
    assert [
        (paid["source_customer_credit_id"], paid["amount_usd_cents"], paid["recipient_customer_id"])
        for paid in refunds_of(result)
    ] == [
        (allocation_source["customer_credit_id"], 12_100, str(customer)),
        (str(case["credit"]), 200, str(customer)),
    ]
    assert (
        count(
            url,
            "SELECT count(*) FROM app.settlement_correction_refund_details "
            "WHERE settlement_correction_id=%s AND refund_method_id=%s AND reference_note=%s",
            correction_id,
            case["cash"],
            NOTE,
        )
        == 2
    )
    assert [name for _, name in effects(url, correction_id)] == [
        "payment_allocation_reversal_id",
        "credit_application_reversal_id",
        "invoice_adjustment_id",
        "customer_credit_application_id",
        "refund_id",
        "refund_id",
    ]
    assert (available(url, case["credit"]), outstanding(url, line), obligation(url, line)) == (
        0,
        0,
        200,
    )
    assert one(url, "SELECT payer_customer_id FROM app.payments WHERE id=%s", payment) == (
        customer,
    )
    # Owner answer 2 to Q-2026-10-07-39: the re-posted rest is still money the closed Settlement
    # relied on, so its one-call reversal is refused as a conflict.
    with pytest.raises(CreditConflictError) as rest_refused:
        reverse_application(case, remainder)
    rest_cause = rest_refused.value.__cause__
    assert isinstance(rest_cause, psycopg.Error)
    assert (rest_cause.sqlstate, rest_cause.diag.message_primary) == ("P5S01", REVERSAL_REFUSED)
    # A second correction may release part of the rest; its own rest stays protected.
    second = confirm(case, person, record(case, correction(case, invoice, line, 100)))
    [again] = released_of(second)
    assert (again["reversed_credit_application_id"], again["released_usd_cents"]) == (
        str(remainder),
        100,
    )
    [second_refund] = refunds_of(second)
    assert (second_refund["source_customer_credit_id"], second_refund["amount_usd_cents"]) == (
        str(case["credit"]),
        100,
    )
    last_rest = again["replacement_credit_application_id"]
    assert one(
        url, "SELECT amount_usd_cents FROM app.customer_credit_applications WHERE id=%s", last_rest
    ) == (100,)
    with pytest.raises(CreditConflictError) as last_refused:
        reverse_application(case, last_rest)
    last_cause = last_refused.value.__cause__
    assert isinstance(last_cause, psycopg.Error)
    assert (last_cause.sqlstate, last_cause.diag.message_primary) == ("P5S01", REVERSAL_REFUSED)
    assert outstanding(url, line) == 0


def test_a_third_party_payment_is_refunded_to_the_invoice_customer_not_the_payer(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014: value a correction releases from a third-party Payment is the Invoice
    Customer's Credit and is refunded to that Customer, not the payer, through the relaxed Refund
    source checks. The relaxation accepts nothing outside a correction: a details row is refused
    outside its correction's transaction, and a Credit Refund to a Customer other than the payer
    still needs its own draft or correction."""
    url = migrated_database_url
    case = leaving_case(url)
    human, customer = case["human"], case["customer"]
    person = approver(url)
    close(url, human, case["settlement"])
    line = case["other_line"]
    invoice = invoice_of(url, line)
    payer, _ = third_party_payment(url, case, invoice, line, 12_500)
    assert outstanding(url, line) == 0
    draft = record(case, correction(case, invoice, line, 5_000))
    assert one(
        url,
        "SELECT payload->'released_sources'->0->>'payer_customer_id',"
        "payload->'released_sources'->0->>'recipient_customer_id' "
        "FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == (str(payer), str(customer))
    result = confirm(case, person, draft)
    [source] = released_of(result)
    credit = UUID(str(source["customer_credit_id"]))
    assert one(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == (
        customer,
    )
    [paid] = refunds_of(result)
    refund = UUID(str(paid["id"]))
    assert one(
        url,
        "SELECT recipient_customer_id,usd_accounting_value_cents FROM app.refunds WHERE id=%s",
        refund,
    ) == (customer, 5_000)
    assert one(
        url,
        "SELECT amount_usd_cents FROM app.payment_allocations WHERE id=%s",
        source["replacement_payment_allocation_id"],
    ) == (7_500,)
    assert available(url, credit) == 0
    assert str(refund) in ledger_event_ids(url, customer)
    assert str(refund) not in ledger_event_ids(url, payer)
    # A details row is written only with its correction, in the same transaction.
    with pytest.raises(psycopg.Error) as detached, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.settlement_correction_refund_details(refund_id,"
            "settlement_correction_id,draft_id,refund_method_id,reference_note,recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,clock_timestamp())",
            (uuid4(), result["settlement_correction"]["id"], draft, case["cash"], NOTE),
        )
    assert (detached.value.sqlstate, detached.value.diag.message_primary) == (
        "23514",
        "A post-settlement correction Refund detail is written with its correction",
    )
    # Outside a correction or its own draft, a Credit Refund to a Customer other than the payer is
    # still refused (sub-slice 8f).
    other, other_credit, other_payer = third_party_credit(url)
    with pytest.raises(psycopg.Error) as outside, psycopg.connect(url) as connection:
        recipient = connection.execute(
            "SELECT customer_id FROM app.customer_credits WHERE id=%s", (other_credit,)
        ).fetchone()
        assert recipient is not None and recipient[0] != other_payer
        connection.execute(
            "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,"
            "source_customer_credit_id,usd_accounting_value_cents,refund_currency,"
            "refund_amount_minor,reason,processed_at,processed_by,authorization_reference) "
            "VALUES (%s,%s,%s,%s,1000,'USD',1000,'Direct',clock_timestamp(),%s,'refunds.create')",
            (uuid4(), f"REF-{uuid4()}", recipient[0], other_credit, other.human),
        )
    assert (outside.value.sqlstate, outside.value.diag.message_primary) == (
        "23514",
        "Refund source, amount, authorization or chronology is invalid",
    )


def test_a_changed_line_is_stale_an_inactive_method_conflicts_and_a_deposit_paid_invoice_waits(
    migrated_database_url: str,
) -> None:
    """A draft whose line or paying sources changed since it was recorded is stale and stays
    pending; a Refund method deactivated after the draft is a conflict (BR-REFUND-014) and the
    draft stays pending; the confirm runs only at READ COMMITTED; a reused key is refused, also
    across variants, and one variant's confirm refuses the other's draft. An Invoice that a Deposit
    application paid stays refused until sub-slice 10c-2."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    person = approver(url)
    pet_line = case["pet_line"]
    apply(
        url,
        prop,
        human,
        case["settlement"],
        case["pet"],
        "PET_RELATED_FIRST",
        "INVOICE_LINE",
        pet_line,
        1_000,
        1,
    )
    close(url, human, case["settlement"])
    with pytest.raises(FinalSettlementConflictError) as deposit:
        record(case, correction(case, invoice_of(url, pet_line), pet_line, 500))
    assert cause(deposit) == (
        "55000",
        "A Deposit application paid this obligation at Final Settlement",
    )
    line = case["other_line"]
    invoice = invoice_of(url, line)
    pay(url, prop, human, customer, invoice, line, 12_500)
    command = correction(case, invoice, line, 2_000)
    first = record(case, command)
    assert record(case, command) == first
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(command, amount_usd_cents=1_999))
    second = record(case, replace(command, idempotency_key=uuid4(), amount_usd_cents=3_000))
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            "SELECT app.confirm_settlement_refund(%s,%s,%s,'financial.approve')",
            (prop, person, first),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    assert state(url, first) == "PENDING"
    confirm(case, person, first)
    refunds_before = count(url, "SELECT count(*) FROM app.refunds")
    with pytest.raises(FinalSettlementStaleDraftError) as stale:
        confirm(case, person, second)
    assert cause(stale)[0] == "P5S02"
    assert state(url, second) == "PENDING"
    # The draft's own method, deactivated after the draft, is a conflict; nothing is written.
    method = uuid4()
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.create_refund_method(%s,%s,%s,%s,%s,%s)",
            (
                prop,
                human,
                method,
                f"FIX_{method.hex[:8].upper()}",
                "Correction test",
                "property.manage",
            ),
        )
    third = record(case, correction(case, invoice, line, 1_000, refund_method_id=method))
    with psycopg.connect(runtime_database_url()) as connection:
        connection.execute(
            "SELECT app.set_refund_method_active(%s,%s,%s,false,%s)",
            (prop, human, method, "property.manage"),
        )
    with pytest.raises(FinalSettlementConflictError) as inactive:
        confirm(case, person, third)
    assert cause(inactive) == ("55000", "Refund Method is not active")
    assert state(url, third) == "PENDING"
    assert count(url, "SELECT count(*) FROM app.refunds") == refunds_before
    # The recorder refuses an inactive method too (review round 1).
    with pytest.raises(FinalSettlementConflictError) as inactive_record:
        record(case, correction(case, invoice, line, 1_000, refund_method_id=method))
    assert cause(inactive_record) == ("55000", "Refund Method is not active")
    # The confirms do not cross, and a draft key of one variant is refused for the other.
    extra = record_extra_charge(case, extra_charge(case["settlement"]))
    with pytest.raises(FinalSettlementNotFoundError) as crossed:
        corrections().confirm_refund(prop, extra, actor=approving(person, prop))
    assert cause(crossed) == ("P0002", "Post-settlement correction draft was not found")
    with pytest.raises(FinalSettlementNotFoundError) as reverse:
        corrections().confirm_charge_reduction(prop, third, actor=approving(person, prop))
    assert cause(reverse) == ("P0002", "Post-settlement correction draft was not found")
    with pytest.raises(FinalSettlementKeyReused):
        corrections().record_extra_charge(
            prop,
            extra_charge(case["settlement"], idempotency_key=command.idempotency_key),
            actor=preparer(human, prop),
        )
    assert (state(url, extra), state(url, third)) == ("PENDING", "PENDING")


def test_a_credit_released_before_closure_to_the_invoice_customer_is_refunded_to_that_customer(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014 and BR-CREDIT-008, the Credit-application half of the relaxed Refund checks
    (review round 1): a Credit that an ordinary credit Adjustment released before closure from a
    third-party Payment to the Invoice Customer, and that the Customer applied to another line, is
    released again by a Refund correction and refunded to the Invoice Customer, not the payer."""
    url = migrated_database_url
    case = leaving_case(url)
    human, customer = case["human"], case["customer"]
    person = approver(url)
    payer, credit = third_party_released_credit(url, case)
    pet = case["pet_line"]
    pet_invoice = invoice_of(url, pet)
    applied = apply_credit(case, credit, pet_invoice, pet, 400)
    close(url, human, case["settlement"])
    assert outstanding(url, pet) == 12_100
    result = confirm(case, person, record(case, correction(case, pet_invoice, pet, 12_200)))
    [source] = released_of(result)
    assert (
        source["source_kind"],
        source["reversed_credit_application_id"],
        source["customer_credit_id"],
        source["released_usd_cents"],
    ) == ("CREDIT_APPLICATION", str(applied), str(credit), 100)
    [paid] = refunds_of(result)
    assert one(
        url,
        "SELECT recipient_customer_id,source_customer_credit_id,usd_accounting_value_cents "
        "FROM app.refunds WHERE id=%s",
        paid["id"],
    ) == (customer, credit, 100)
    assert (available(url, credit), outstanding(url, pet)) == (0, 0)
    assert paid["id"] in ledger_event_ids(url, customer)
    assert paid["id"] not in ledger_event_ids(url, payer)


def test_the_relaxed_refund_checks_hold_inside_a_hand_built_correction(
    migrated_database_url: str,
) -> None:
    """Security review round 1 notes N1 and N2, tested after review round 2: inside a correction
    confirmed in the same transaction (written by hand through the internal 10a functions, as no
    role can), (a) a Refund of a Credit to its Customer who is not the payer is refused even with
    its details row and link, because the correction's own Adjustment released nothing to that
    Credit; (b) a details row needs its Refund linked to the correction first; (c) a Refund to the
    payer with a details row commits only when the correction's approver processed it. Each
    attempt rolls back and the draft stays pending."""
    url = migrated_database_url
    case = leaving_case(url)
    human, customer = case["human"], case["customer"]
    person = approver(url)
    _, credit = third_party_released_credit(url, case)
    close(url, human, case["settlement"])
    draft = correction_draft(url, case)

    def begin(connection: psycopg.Connection[Any]) -> UUID:
        found = connection.execute(BEGIN, (case["prop"], person, draft)).fetchone()
        assert found is not None
        return UUID(str(found[0]))

    refund = uuid4()
    with pytest.raises(psycopg.Error) as uncapped, psycopg.connect(url) as connection:
        correction_id = begin(connection)
        connection.execute(LINK, (correction_id, refund))
        connection.execute(DETAIL, (refund, correction_id, draft, case["cash"], NOTE))
        # Linked to this correction with its details row; only the cap is not met.
        assert connection.execute(
            "SELECT app.settlement_correction_linked(%s,'refunds',%s),"
            "app.settlement_correction_refund_allowed(jsonb_populate_record(NULL::app.refunds,%s))",
            (
                case["settlement"],
                refund,
                Jsonb(
                    {
                        "id": str(refund),
                        "recipient_customer_id": str(customer),
                        "source_customer_credit_id": str(credit),
                        "usd_accounting_value_cents": 100,
                        "processed_by": str(person),
                    }
                ),
            ),
        ).fetchone() == (True, False)
        connection.execute(DIRECT_REFUND, (refund, f"REF-{refund}", customer, credit, person))
    assert (uncapped.value.sqlstate, uncapped.value.diag.message_primary) == (
        "23514",
        "Refund source, amount, authorization or chronology is invalid",
    )
    with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
        correction_id = begin(connection)
        connection.execute(DETAIL, (uuid4(), correction_id, draft, case["cash"], NOTE))
    assert (unlinked.value.sqlstate, unlinked.value.diag.message_primary) == (
        "23514",
        "A post-settlement correction Refund detail is written with its correction",
    )
    payer_refund = uuid4()
    with pytest.raises(psycopg.Error) as other_actor, psycopg.connect(url) as connection:
        correction_id = begin(connection)
        connection.execute(LINK, (correction_id, payer_refund))
        connection.execute(DETAIL, (payer_refund, correction_id, draft, case["cash"], NOTE))
        # The Customer paid this Credit's Payment, so the general check passes the recipient.
        connection.execute(
            DIRECT_REFUND, (payer_refund, f"REF-{payer_refund}", customer, case["credit"], human)
        )
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert (other_actor.value.sqlstate, other_actor.value.diag.message_primary) == (
        "42501",
        "A post-settlement correction Refund is processed by the correction's approver",
    )
    assert state(url, draft) == "PENDING"
    assert (
        count(url, "SELECT count(*) FROM app.refunds WHERE id IN (%s,%s)", refund, payer_refund)
        == 0
    )


def test_a_second_refund_of_the_same_credit_beyond_what_the_correction_released_is_refused(
    migrated_database_url: str,
) -> None:
    """The cap of the relaxed check is cumulative (review round 3; owner answer (a) to
    Q-2026-10-07-40): in one transaction a real confirm releases 100 to a Credit whose Customer is
    not the payer and refunds it; a second Refund of 1 cent from the same Credit, linked to the
    same correction with its details row and processed by the approver, is refused although the
    Credit still has value, because together with the correction's first Refund it is more than
    the correction released to that Credit. Everything rolls back and the draft stays pending."""
    url = migrated_database_url
    case = leaving_case(url)
    customer = case["customer"]
    person = approver(url)
    _, credit = third_party_released_credit(url, case)
    pet = case["pet_line"]
    pet_invoice = invoice_of(url, pet)
    apply_credit(case, credit, pet_invoice, pet, 300)
    close(url, case["human"], case["settlement"])
    assert (available(url, credit), outstanding(url, pet)) == (100, 12_200)
    draft = record(case, correction(case, pet_invoice, pet, 12_300))
    second = uuid4()
    with pytest.raises(psycopg.Error) as capped, psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.confirm_settlement_refund(%s,%s,%s,'financial.approve')",
            (case["prop"], person, draft),
        ).fetchone()
        assert found is not None
        result = cast(dict[str, Any], found[0])
        [source] = released_of(result)
        assert (source["customer_credit_id"], source["released_usd_cents"]) == (str(credit), 100)
        [paid] = refunds_of(result)
        assert connection.execute(
            "SELECT recipient_customer_id,source_customer_credit_id,usd_accounting_value_cents "
            "FROM app.refunds WHERE id=%s",
            (paid["id"],),
        ).fetchone() == (customer, credit, 100)
        correction_id = result["settlement_correction"]["id"]
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(LINK, (correction_id, second))
        connection.execute(DETAIL, (second, correction_id, draft, case["cash"], NOTE))
        # The Credit still has value and the Refund is linked with its details row; only the
        # cumulative cap is not met.
        assert connection.execute(
            "SELECT app.credit_available_value(%s),"
            "app.settlement_correction_linked(%s,'refunds',%s),"
            "app.settlement_correction_refund_allowed(jsonb_populate_record(NULL::app.refunds,%s))",
            (
                credit,
                case["settlement"],
                second,
                Jsonb(
                    {
                        "id": str(second),
                        "recipient_customer_id": str(customer),
                        "source_customer_credit_id": str(credit),
                        "usd_accounting_value_cents": 1,
                        "processed_by": str(person),
                    }
                ),
            ),
        ).fetchone() == (100, True, False)
        connection.execute(
            "INSERT INTO app.refunds(id,refund_number,recipient_customer_id,"
            "source_customer_credit_id,usd_accounting_value_cents,refund_currency,"
            "refund_amount_minor,reason,processed_at,processed_by,authorization_reference) "
            "VALUES (%s,%s,%s,%s,1,'USD',1,'Direct',GREATEST(clock_timestamp(),"
            "app.credit_latest_at(%s)+interval '1 microsecond'),%s,'refunds.create')",
            (second, f"REF-{second}", customer, credit, credit, person),
        )
    assert (capped.value.sqlstate, capped.value.diag.message_primary) == (
        "23514",
        "Refund source, amount, authorization or chronology is invalid",
    )
    assert state(url, draft) == "PENDING"
    assert count(url, "SELECT count(*) FROM app.refunds WHERE id=%s", second) == 0
    assert available(url, credit) == 100


def test_an_ordinary_re_posted_credit_application_still_reverses_with_one_call(
    migrated_database_url: str,
) -> None:
    """The approved remainder refusal reaches only the re-posts of a Settlement Credit application
    (owner answer 2 to Q-2026-10-07-39; review round 1): on a Lease whose Final Settlement is not
    closed, a one-call credit Adjustment that releases part of an ordinary Credit application
    re-posts its rest, and that rest still reverses with one call."""
    url = migrated_database_url
    case = leaving_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    line = case["other_line"]
    invoice = invoice_of(url, line)
    pay(url, prop, human, customer, invoice, line, 12_100)
    applied = apply_credit(case, case["credit"], invoice, line, 400)
    assert outstanding(url, line) == 0
    version = int(one(url, "SELECT version FROM app.invoices WHERE id=%s", invoice)[0])
    invoices().adjust(
        prop,
        invoice,
        AdjustInvoiceCommand(
            uuid4(),
            line,
            AdjustmentType.CREDIT,
            100,
            f"approved-credit/{uuid4()}",
            "Approved credit",
            version,
        ),
        actor=invoice_api_actor(human, prop),
    )
    rest = one(
        url,
        "SELECT replacement_credit_application_id FROM app.invoice_credit_excess_releases "
        "WHERE reversed_credit_application_id=%s",
        applied,
    )[0]
    assert one(
        url,
        "SELECT amount_usd_cents,final_settlement_id FROM app.customer_credit_applications "
        "WHERE id=%s",
        rest,
    ) == (300, None)
    reverse_application(case, rest)
    assert (
        count(
            url,
            "SELECT count(*) FROM app.customer_credit_application_reversals "
            "WHERE credit_application_id=%s",
            rest,
        )
        == 1
    )
    assert available(url, case["credit"]) == 400


def test_refund_correction_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (RECORD, CONFIRM, *INTERNAL):
            definer, settings = cast(
                tuple[bool, list[str] | None],
                connection.execute(
                    "SELECT prosecdef,proconfig FROM pg_catalog.pg_proc "
                    "WHERE oid=CAST(%s AS regprocedure)",
                    (function,),
                ).fetchone(),
            )
            assert settings is not None and "search_path=pg_catalog" in settings, function
            # Only the append-only refusal runs with the caller's rights, as 8d's.
            assert definer is (function != INTERNAL[0]), function
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                allowed = role == "prm_financial" and function in (RECORD, CONFIRM)
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (allowed,), (role, function)
            # BR-SETTLE-013, no time limit: no age or deadline; the only interval orders a Refund
            # after its Credit's latest event.
            source = connection.execute(
                "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", (function,)
            ).fetchone()
            assert source is not None and "age(" not in str(source[0]), function
            assert set(re.findall(r"interval '([^']*)'", str(source[0]))) <= {"1 microsecond"}
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_table_privilege(%s,'app.settlement_correction_refund_details',"
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                (role,),
            ).fetchone() == (False,), role
        assert connection.execute(
            "SELECT tgname FROM pg_catalog.pg_trigger WHERE "
            "tgrelid='app.settlement_correction_refund_details'::regclass AND NOT tgisinternal "
            "ORDER BY tgname"
        ).fetchall() == [
            ("settlement_correction_refund_details_approver",),
            ("settlement_correction_refund_details_immutable",),
            ("settlement_correction_refund_details_no_truncate",),
            ("settlement_correction_refund_details_validate",),
        ]
    with pytest.raises(psycopg.Error) as truncate, psycopg.connect(url) as connection:
        connection.execute("TRUNCATE app.settlement_correction_refund_details")
    assert (truncate.value.sqlstate, truncate.value.diag.message_primary) == (
        "55000",
        "Post-settlement correction Refund details are append-only",
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("20261104_100")
    assert revision is not None and revision.down_revision == "20261103_99"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, object], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): row[1]
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid) "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            tables = {
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
        return functions, tables, triggers

    with _temporary_migration_database("settlement_refund_correction") as temporary:
        alembic_command.upgrade(config, "20261103_99")
        before_functions, before_tables, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261104_100")
        after_functions, after_tables, after_triggers = catalog(temporary)
    assert after_tables - before_tables == {"app.settlement_correction_refund_details"}
    assert before_tables <= after_tables
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert after_triggers - before_triggers == {
        "app.settlement_correction_refund_details:settlement_correction_refund_details_approver",
        "app.settlement_correction_refund_details:settlement_correction_refund_details_immutable",
        "app.settlement_correction_refund_details:settlement_correction_refund_details_no_truncate",
        "app.settlement_correction_refund_details:settlement_correction_refund_details_validate",
        "app.customer_credit_application_reversals:"
        "a0_customer_credit_application_reversals_settlement_remainder",
    }
    assert before_triggers <= after_triggers
    # Relaxing patches only: the two Refund source checks gain the correction's own Refund; no
    # other earlier function changes.
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for name in CHANGED:
        assert "app.settlement_correction_refund_allowed(NEW)" in str(after_functions[name])
        assert "app.settlement_correction_refund_allowed(NEW)" not in str(before_functions[name])
