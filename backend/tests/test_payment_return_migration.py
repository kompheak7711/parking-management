"""Returned Payments with no closed Final Settlement relied on (V1-056 sub-slice 10e-1a).

Owner answers 2, 3 and 5 to Q-2026-10-06-37 and answer 5 to Q-2026-10-06-36: a returned Payment
(a bounced transfer) is a PAYMENT_RETURN draft that a payments.reverse holder records and only a
financial.approve holder confirms. In one transaction the confirm reverses the Payment's Credit
applications, Credits, allocations and Deposit receipts and then the Payment, and writes one
app.payment_returns row (DB-PAY-009). The debt comes back on its obligations and stays with their
Customers (BR-SETTLE-016). It ends the slice 7 and sub-slice 8g lasting blocks; a record that a
closed Final Settlement relied on is refused here and is returned through a correction of that
Settlement (sub-slice 10e-1b).
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
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.financial_draft import FinancialDraftService
from property_rental.identity import AuthenticatedActor
from property_rental.invoice import RecordOneTimeChargeCommand
from property_rental.payment_return import (
    PaymentReturnAuthorizationError,
    PaymentReturnConflictError,
    PaymentReturnKeyReused,
    PaymentReturnService,
    PaymentReturnStaleDraftError,
    RecordPaymentReturnCommand,
    payment_return_draft_id,
)
from property_rental.refund import CreateUsdRefundCommand
from refund_test_support import cash, create_pet_refund, create_usd_refund
from test_credit_application_migration import designated as credit_designated
from test_credit_application_migration import source as credit_source
from test_credit_customer_credit_reversal_migration import MOVED_REFUSED, REFUSED, direct_reversal
from test_credit_customer_refund_migration import (
    approving,
    moved_credit,
    third_party_credit,
)
from test_credit_customer_refund_migration import command as credit_customer_refund
from test_credit_customer_refund_migration import service as refunds
from test_credit_customer_refund_migration import staff as refund_staff
from test_credit_migration import actor as credit_actor
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of, this_month
from test_final_settlement_draft_migration import (
    LINE,
    PET_FIRST,
    PET_REST,
    SECURITY,
    STAFF,
    leaving_case,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import held, line_of, outstanding
from test_final_settlement_preview_migration import credit_adjustment, pay
from test_invoice_migration import (
    create_recurring_rent_invoice,
    financial_database_url,
    register_billing_service_principal,
    runtime_database_url,
)
from test_migrations import _temporary_migration_database
from test_one_time_charges_migration import draft_and_issue, invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_move_migration import person, rows, value
from test_payment_reversal_context_migration import deposit_source
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import service as refund_service
from test_reservation_migration import (
    migrated_database_url,  # noqa: F401
    setup_reservation_sources,
)
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_late_charge_reduction_migration import unpaid
from test_settlement_late_charge_refund_migration import command as charge_refund
from test_settlement_late_charge_refund_migration import confirm as confirm_charge_refund
from test_settlement_late_charge_refund_migration import (
    pay_charge,
    pay_other_debt,
    settled_case,
)
from test_settlement_late_charge_refund_migration import record as record_charge_refund
from test_settlement_refund_correction_migration import apply_credit, close_by_refunds
from test_settlement_refund_correction_migration import confirm as confirm_refund_correction
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import record as record_refund_correction
from test_settlement_refund_return_migration import confirm as confirm_refund_return
from test_settlement_refund_return_migration import net, return_command
from test_settlement_refund_return_migration import record as record_refund_return
from waiting_draft_test_support import recorded_then_rolled_back, written_after_closure

RECORD = "app.record_payment_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_payment_return(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.reject_payment_return_mutation()",
    "app.validate_payment_return()",
    "app.assert_payment_return_confirmed()",
    "app.payment_return_in_transaction(uuid)",
    "app.payment_return_source(uuid,uuid,uuid)",
    "app.assert_payment_return_allowed(jsonb)",
    "app.payment_return_result(uuid)",
    "app.payment_return_receipt_key(uuid,uuid)",
)
PATCHED = {
    "app.validate_wrong_unit_move_reversal()",
    "app.validate_moved_credit_reversal()",
    "app.validate_credit_customer_credit_reversal()",
    "app.financial_draft_resource_by_capability(uuid,uuid,uuid,text[])",
    "app.list_financial_drafts_by_capability(uuid,uuid,text[],text,integer,"
    "timestamp with time zone,uuid)",
}
REASON = "The bank returned the transfer"
EVIDENCE = "Bank return notice 4471"
RELIED_ON = (
    "A closed Final Settlement relied on this Payment's records; "
    "return it through a correction of that Final Settlement"
)
MOVED_ALLOCATION_REFUSED = (
    "A moved allocation changes only through another move draft or a credit Adjustment"
)


def returns() -> PaymentReturnService:
    return PaymentReturnService(financial_database_url())


def drafts() -> FinancialDraftService:
    return FinancialDraftService(runtime_database_url(), financial_database_url())


def preparer(human: UUID, prop: UUID) -> AuthenticatedActor:
    return person(human, prop, "payments.reverse")


def approver(human: UUID, prop: UUID) -> AuthenticatedActor:
    return person(human, prop, "financial.approve")


def request(payment: UUID, **changes: Any) -> RecordPaymentReturnCommand:
    values: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "payment_id": payment,
        "reason": REASON,
        "evidence_reference": EVIDENCE,
        **changes,
    }
    return RecordPaymentReturnCommand(**values)


def draft_id(result: dict[str, object]) -> UUID:
    return UUID(str(result["draft_id"]))


def status(url: str, payment: UUID) -> str:
    return str(value(url, "SELECT status FROM app.payments WHERE id=%s", payment))


def returned(url: str, payment: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT draft_id,actor_id,reason,authorization_reference,settlement_correction_id "
        "FROM app.payment_returns WHERE payment_id=%s",
        payment,
    )


def unchanged_payment(url: str, payment: UUID) -> dict[str, Any]:
    """The Payment row without its status, and its Receipt (DB-PAY-006: never changed)."""
    found = cast(
        dict[str, Any], value(url, "SELECT to_jsonb(p) FROM app.payments p WHERE p.id=%s", payment)
    )
    found.pop("status")
    return {
        "payment": found,
        "receipts": rows(
            url, "SELECT to_jsonb(r) FROM app.receipts r WHERE r.payment_id=%s", payment
        ),
    }


def no_transaction_id(result: object) -> None:
    assert "transaction_id" not in json.dumps(result, default=str)


def reconciled(url: str, *customers: UUID) -> None:
    with psycopg.connect(url) as connection:
        for customer in customers:
            assert_reconciled(connection, customer)


def refused_sql(url: str, sql: str, *parameters: object) -> psycopg.Error:
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(sql, parameters)
        connection.rollback()
    return refused.value


def relied_on_kinds(url: str, prop: UUID, payment: UUID) -> set[str]:
    """The kinds of record a closed Final Settlement relied on, read as the owner."""
    found = cast(
        list[dict[str, str]],
        value(url, "SELECT app.payment_return_source(%s,%s,NULL)->'relied_on'", prop, payment),
    )
    return {item["kind"] for item in found}


def test_a_returned_payment_reverses_its_credit_applications_credits_and_payment(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """The draft lists what comes back; nothing changes until a financial.approve holder confirms;
    then the Credit application, the Credit and the Payment are reversed in one transaction, the
    debt is back on the Invoice line, and the Payment row and its Receipt never change."""
    url = migrated_database_url
    human, prop, credit, invoice, line, payment = credit_source(url)
    customer = UUID(
        str(value(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit))
    )
    owed = outstanding(url, line)
    credits().apply(
        prop,
        credit,
        credit_designated(invoice, line, 30_000),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    assert outstanding(url, line) == owed - 30_000
    before = unchanged_payment(url, payment)
    command = request(payment)
    draft = returns().record(prop, command, actor=preparer(human, prop))
    identity = draft_id(draft)
    assert identity == payment_return_draft_id(prop, human, command.idempotency_key)
    assert (draft["kind"], draft["prepare_capability"], draft["state"]) == (
        "PAYMENT_RETURN",
        "payments.reverse",
        "PENDING",
    )
    payload = cast(dict[str, Any], draft["payload"])
    assert (payload["payment_id"], payload["evidence_reference"]) == (str(payment), EVIDENCE)
    source = payload["source"]
    assert source["allocations"] == [] and source["receipts"] == []
    assert [
        (item["id"], item["customer_id"], item["available_usd_cents"]) for item in source["credits"]
    ] == [(str(credit), str(customer), 70_000)]
    assert [item["amount_usd_cents"] for item in source["credits"][0]["applications"]] == [30_000]
    assert source["relied_on"] == [] and source["pending_drafts"] == []
    # A draft has no financial effect; an exact repeat returns the same draft.
    assert status(url, payment) == "RECEIVED" and outstanding(url, line) == owed - 30_000
    assert draft_id(returns().record(prop, command, actor=preparer(human, prop))) == identity
    # Staff cannot confirm, in the service and in the database.
    with pytest.raises(PaymentReturnAuthorizationError):
        returns().confirm(prop, identity, actor=preparer(human, prop))
    assert (
        refused_sql(
            financial_database_url(),
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,%s)",
            prop,
            human,
            identity,
            "payments.reverse",
        ).sqlstate
        == "42501"
    )
    # A service identity is not a person and cannot confirm (P4506, before the human check).
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    assert (
        refused_sql(
            financial_database_url(),
            "SELECT app.confirm_payment_return(%s,%s,%s,'financial.approve')",
            prop,
            machine,
            identity,
        ).sqlstate
        == "P4506"
    )
    result = returns().confirm(prop, identity, actor=approver(human, prop))
    no_transaction_id(result)
    assert result["status"] == "REVERSED" and result["payment_id"] == str(payment)
    assert len(cast(list[str], result["credit_application_reversal_ids"])) == 1
    assert len(cast(list[str], result["credit_reversal_ids"])) == 1
    assert result["allocation_reversal_ids"] == [] and result["deposit_receipt_reversal_ids"] == []
    assert result["payment_reversal_id"] is not None
    # A replay returns the same result and writes nothing.
    assert returns().confirm(prop, identity, actor=approver(human, prop)) == result
    assert status(url, payment) == "REVERSED"
    assert outstanding(url, line) == owed
    assert int(value(url, "SELECT app.credit_available_value(%s)", credit)) == 0
    assert returned(url, payment) == [(identity, human, REASON, "financial.approve", None)]
    assert unchanged_payment(url, payment) == before
    assert (
        value(
            url,
            "SELECT count(*) FROM app.audit_events WHERE action='payment.return.confirmed' "
            "AND correlation_id=%s",
            identity,
        )
        == 1
    )
    assert drafts().get(prop, identity, actor=approver(human, prop))["state"] == "CONFIRMED"
    reconciled(url, customer)


def test_a_returned_third_party_payment_ends_the_8g_lasting_block(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Owner answer 5 to Q-2026-10-06-36: a third-party Payment whose adjustment Credit was released
    to the Invoice Customer can be returned; the Credit, the allocation and the Payment are
    reversed and the debt is back on that Customer's Invoice. Outside a return the sub-slice 8g
    refusal still holds."""
    url = migrated_database_url
    case, credit, payer = third_party_credit(url)
    customer = case.customer_wrong
    assert direct_reversal(url, credit, case.human).sqlstate == "P4904"
    assert str(direct_reversal(url, credit, case.human)).startswith(REFUSED)
    owed = outstanding(url, case.line_wrong)
    assert owed == 0
    # The Invoice Customer applies 2,000 of that Credit to another Invoice of its own.
    with psycopg.connect(url) as connection:
        other_invoice, other_line = create_recurring_rent_invoice(
            connection,
            actor_id=case.human,
            customer_id=customer,
            lease_id=case.lease_wrong,
            period_start=date(2027, 3, 1),
        )
    other_owed = outstanding(url, other_line)
    credits().apply(
        case.prop,
        credit,
        credit_designated(other_invoice, other_line, 2_000),
        actor=credit_actor(case.human, case.prop, "credits.apply"),
    )
    assert outstanding(url, other_line) == other_owed - 2_000
    draft = returns().record(
        case.prop, request(case.payment), actor=preparer(case.human, case.prop)
    )
    source = cast(dict[str, Any], draft["payload"])["source"]
    assert [(item["id"], item["customer_id"]) for item in source["credits"]] == [
        (str(credit), str(customer))
    ]
    assert [item["amount_usd_cents"] for item in source["credits"][0]["applications"]] == [2_000]
    assert [item["amount_usd_cents"] for item in source["allocations"]] == [75_000]
    result = returns().confirm(case.prop, draft_id(draft), actor=approver(case.approver, case.prop))
    assert len(cast(list[str], result["credit_application_reversal_ids"])) == 1
    assert len(cast(list[str], result["credit_reversal_ids"])) == 1
    assert len(cast(list[str], result["allocation_reversal_ids"])) == 1
    assert status(url, case.payment) == "REVERSED"
    # The debt is back on both of the Invoice Customer's Invoices (BR-SETTLE-016).
    assert outstanding(url, case.line_wrong) == 75_000
    assert outstanding(url, other_line) == other_owed
    assert int(value(url, "SELECT app.credit_available_value(%s)", credit)) == 0
    reconciled(url, customer, payer)
    # The 8g refusal still holds for another such Credit outside a return.
    other, other_credit, _ = third_party_credit(url)
    assert direct_reversal(url, other_credit, other.human).sqlstate == "P4904"


def test_a_returned_moved_payment_ends_the_slice_7_lasting_block(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """BR-PAY-042: a Payment moved to the correct Unit's Invoice, whose credit Adjustment released a
    Credit to that Invoice's Customer, can be returned: the moved allocation and the moved-value
    Credit are reversed; the move record stays."""
    url = migrated_database_url
    case, credit = moved_credit(url)
    error = direct_reversal(url, credit, case.human)
    assert error.sqlstate == "P4904" and str(error).startswith(MOVED_REFUSED)
    moves_before = rows(
        url, "SELECT to_jsonb(m) FROM app.payment_moves m WHERE m.payment_id=%s", case.payment
    )
    draft = returns().record(
        case.prop, request(case.payment), actor=preparer(case.human, case.prop)
    )
    source = cast(dict[str, Any], draft["payload"])["source"]
    assert [item["between_invoice_basis"] for item in source["allocations"]] == ["WRONG_UNIT_MOVE"]
    returns().confirm(case.prop, draft_id(draft), actor=approver(case.approver, case.prop))
    assert status(url, case.payment) == "REVERSED"
    assert outstanding(url, case.line_right) == 75_000
    assert outstanding(url, case.line_wrong) == 80_000
    assert int(value(url, "SELECT app.credit_available_value(%s)", credit)) == 0
    assert (
        rows(url, "SELECT to_jsonb(m) FROM app.payment_moves m WHERE m.payment_id=%s", case.payment)
        == moves_before
    )
    reconciled(url, case.customer_wrong, case.customer_right)


def test_a_returned_payment_reverses_its_deposit_receipt(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """A Deposit receipt of the returned Payment is reversed through the existing receipt reversal
    (deposits.correct, its command record and audit event); the Deposit keeps the receipt another
    Payment funded."""
    url = migrated_database_url
    service, _, _, deposit, payment, receipts = deposit_source(url)
    human, prop = service.actor_id, service.property_id
    assert held(url, deposit) == 20_000
    draft = returns().record(prop, request(payment), actor=preparer(human, prop))
    source = cast(dict[str, Any], draft["payload"])["source"]
    assert [(item["id"], item["amount_usd_cents"]) for item in source["receipts"]] == [
        (str(receipts[0]), 10_000)
    ]
    result = returns().confirm(prop, draft_id(draft), actor=approver(human, prop))
    reversal_ids = cast(list[str], result["deposit_receipt_reversal_ids"])
    assert len(reversal_ids) == 1
    assert held(url, deposit) == 10_000 and status(url, payment) == "REVERSED"
    assert rows(
        url,
        "SELECT deposit_receipt_id,authorization_reference FROM app.deposit_receipt_reversals "
        "WHERE id=%s",
        UUID(reversal_ids[0]),
    ) == [(receipts[0], "deposits.correct")]
    assert (
        value(
            url,
            "SELECT count(*) FROM app.audit_events "
            "WHERE id=%s AND action='deposit.receipt.reversed'",
            UUID(reversal_ids[0]),
        )
        == 1
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.deposit_receipt_reversals WHERE deposit_receipt_id=%s",
            receipts[1],
        )
        == 0
    )


def test_a_closed_settlement_s_records_are_refused_and_a_later_payment_is_returned(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Owner answer 5 to Q-2026-10-06-37: a Payment whose allocation paid a Settlement obligation
    before the closure, whose Credit a Final Settlement Credit application used, or whose Deposit
    receipt the Settlement relied on, is refused here; a draft recorded before the closure is stale
    after it and stays pending; a Payment made after the closure is returned, and the closed
    Settlement keeps its closing balance. Since sub-slice 10h-3 such a waiting draft blocks the
    closure, so the draft recorded before it is written by hand after it."""
    url = migrated_database_url
    case = leaving_case(url, start_offset=this_month(url))
    human, prop, customer, settlement = (
        case["human"],
        case["prop"],
        case["customer"],
        case["settlement"],
    )
    staff = invoice_staff(human, prop)
    appliances = RecordOneTimeChargeCommand(
        uuid4(),
        "MISCELLANEOUS_CHARGES",
        customer,
        case["lease"],
        None,
        "Unreturned furniture",
        15_000,
        "Furniture missing at the move-out review",
        "Move-out log 812",
    )
    invoices().record_one_time_charge(prop, appliances, actor=staff)
    extra_line = line_of(url, draft_and_issue(prop, appliances.charge_id, staff)["id"])
    # Before the closure a Payment pays 1,000 of the extra charge, and its return is recorded.
    # Since sub-slice 10h-3 a waiting return draft of it blocks the closure (asserted in a
    # rolled-back recording), so the same draft is written by hand after the closure.
    early = pay(url, prop, human, customer, invoice_of(url, extra_line), extra_line, 1_000)
    held_id = uuid4()
    held_return = recorded_then_rolled_back(
        url,
        "SELECT app.record_payment_return_draft(%s,%s,%s,%s,%s,%s,'payments.reverse')",
        (prop, human, held_id, early, Jsonb({"evidence_reference": EVIDENCE}), REASON),
        draft=held_id,
        prop=prop,
        actor=human,
        settlement=settlement,
    )
    plan = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
        SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 2_100),
        SettlementDepositStep(PET_REST, case["pet"], LINE, extra_line, 5_400),
    )
    confirm_settlement(case, record_settlement(case, plan, pet_remainder=STAFF))
    early_draft = written_after_closure(url, prop, held_return)
    closed = rows(url, "SELECT to_jsonb(s) FROM app.final_settlements s WHERE s.id=%s", settlement)
    assert outstanding(url, extra_line) == 8_600
    # The closure changed what the draft depends on: it is stale and stays pending.
    with pytest.raises(PaymentReturnStaleDraftError):
        returns().confirm(prop, early_draft, actor=approver(human, prop))
    assert drafts().get(prop, early_draft, actor=approver(human, prop))["state"] == "PENDING"
    assert status(url, early) == "RECEIVED" and outstanding(url, extra_line) == 8_600
    credit_payment = UUID(
        str(
            value(
                url,
                "SELECT source_payment_id FROM app.customer_credits WHERE id=%s",
                case["credit"],
            )
        )
    )
    receipt_payments = [
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT DISTINCT payment_id FROM app.deposit_receipts WHERE deposit_id=%s",
            case["security"],
        )
    ]
    # Each branch of the rule: the early Payment's only record is its allocation made before the
    # closure; the Credit's Payment funded a Final Settlement Credit application; the receipt's
    # Payment funded the Security Deposit the Settlement applied.
    expected = {
        early: {"PAYMENT_ALLOCATION"},
        credit_payment: {"CREDIT_APPLICATION", "CUSTOMER_CREDIT"},
        **{payment: {"DEPOSIT_RECEIPT"} for payment in receipt_payments},
    }
    for payment, kinds in expected.items():
        assert kinds <= relied_on_kinds(url, prop, payment), payment
        with pytest.raises(PaymentReturnConflictError) as refused:
            returns().record(prop, request(payment), actor=preparer(human, prop))
        assert cast(psycopg.Error, refused.value.__cause__).diag.message_primary == RELIED_ON
        assert status(url, payment) == "RECEIVED"
        assert value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='PAYMENT_RETURN' "
            "AND payload->>'payment_id'=%s",
            str(payment),
        ) == (1 if payment == early else 0)
    assert relied_on_kinds(url, prop, early) == {"PAYMENT_ALLOCATION"}
    # A Payment made after the closure pays the open debt and can be returned.
    later = pay(url, prop, human, customer, invoice_of(url, extra_line), extra_line, 8_600)
    assert outstanding(url, extra_line) == 0
    draft = returns().record(prop, request(later), actor=preparer(human, prop))
    assert cast(dict[str, Any], draft["payload"])["source"]["relied_on"] == []
    returns().confirm(prop, draft_id(draft), actor=approver(human, prop))
    assert outstanding(url, extra_line) == 8_600 and status(url, later) == "REVERSED"
    assert (
        rows(url, "SELECT to_jsonb(s) FROM app.final_settlements s WHERE s.id=%s", settlement)
        == closed
    )
    assert (held(url, case["security"]), held(url, case["pet"])) == (0, 0)
    reconciled(url, customer)


def test_refusals_stale_drafts_withdrawal_and_reads(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """A Refund paid from the Payment's value is recovered by a charge (sub-slice 10e-1c); a
    waiting draft and a reused key are refused; a draft whose sources changed is stale and stays
    pending; a confirm outside READ COMMITTED is refused; the preparer may withdraw; an approver
    reads the drafts of all eight preparer capabilities."""
    url = migrated_database_url
    # Q-2026-10-10-72 point 1: a Refund of the Payment's Credit that is not returned. Sub-slice
    # 10e-1c (owner answer (a) to Q-2026-10-11-79; changed expectation, was the 55000 refusal
    # with no draft written): the return is recorded and confirmed, and the 30.00 is charged to
    # the Invoice Customer who received it, on the Lease of the Invoice whose release created the
    # Credit (owner answer A to Q-2026-10-11-78), issued and unpaid.
    case, credit, _ = third_party_credit(url)
    choice = cash(refunds(), case.prop, refund_staff(case))
    refund_draft = refunds().record_credit_customer_draft(
        case.prop, credit_customer_refund(credit, 3_000), choice, actor=refund_staff(case)
    )
    refunds().confirm_draft(case.prop, draft_id(refund_draft), actor=approving(case))
    recovering = returns().record(
        case.prop, request(case.payment), actor=preparer(case.human, case.prop)
    )
    [(invoice_customer, invoice_lease)] = rows(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", case.invoice_wrong
    )
    recovered = returns().confirm(
        case.prop, draft_id(recovering), actor=approver(case.human, case.prop)
    )
    [charged] = cast(list[dict[str, Any]], recovered["recoveries"])
    assert (
        charged["customer_id"],
        charged["lease_id"],
        charged["amount_usd_cents"],
        charged["charge"],
    ) == (str(invoice_customer), str(invoice_lease), 3_000, "LEASE")
    assert rows(
        url,
        "SELECT customer_id,lease_id,status,original_total_usd_cents FROM app.invoices WHERE id=%s",
        UUID(str(charged["invoice_id"])),
    ) == [(invoice_customer, invoice_lease, "UNPAID", 3_000)]
    assert status(url, case.payment) == "REVERSED"

    human, prop, credit, invoice, line, payment = credit_source(url)
    first = request(payment)
    draft = returns().record(prop, first, actor=preparer(human, prop))
    identity = draft_id(draft)
    # A reused key with other content; a second draft while one waits.
    with pytest.raises(PaymentReturnKeyReused):
        returns().record(
            prop,
            request(payment, idempotency_key=first.idempotency_key, reason="Other"),
            actor=preparer(human, prop),
        )
    with pytest.raises(PaymentReturnConflictError):
        returns().record(prop, request(payment), actor=preparer(human, prop))
    # Recording outside READ COMMITTED is refused by its own guard (review rounds 1 and 2): a
    # Payment with no waiting draft, the guard's message, and no draft written.
    free_human, free_prop, _, _, _, free_payment = credit_source(url)
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as recorded:
            connection.execute(
                "SELECT app.record_payment_return_draft(%s,%s,%s,%s,%s,%s,'payments.reverse')",
                (
                    free_prop,
                    free_human,
                    uuid4(),
                    free_payment,
                    Jsonb({"evidence_reference": EVIDENCE}),
                    REASON,
                ),
            )
        connection.rollback()
    assert (recorded.value.sqlstate, recorded.value.diag.message_primary) == (
        "55000",
        "A Payment return draft is recorded at READ COMMITTED",
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.financial_drafts WHERE kind='PAYMENT_RETURN' "
            "AND payload->>'payment_id'=%s",
            str(free_payment),
        )
        == 0
    )
    # The same call at READ COMMITTED records the draft.
    free_draft = returns().record(
        free_prop, request(free_payment), actor=preparer(free_human, free_prop)
    )
    assert free_draft["state"] == "PENDING"
    # An approver holding financial.approve reads it with all eight preparer capabilities.
    assert drafts().get(prop, identity, actor=approver(human, prop))["kind"] == "PAYMENT_RETURN"
    assert identity in {
        UUID(str(item["draft_id"]))
        for item in cast(
            list[dict[str, object]], drafts().list(prop, actor=approver(human, prop))["items"]
        )
    }
    # A change of the sources makes the draft stale; it stays pending and nothing is written.
    credits().apply(
        prop,
        credit,
        credit_designated(invoice, line, 10_000),
        actor=credit_actor(human, prop, "credits.apply"),
    )
    with pytest.raises(PaymentReturnStaleDraftError):
        returns().confirm(prop, identity, actor=approver(human, prop))
    assert drafts().get(prop, identity, actor=approver(human, prop))["state"] == "PENDING"
    assert status(url, payment) == "RECEIVED" and returned(url, payment) == []
    # A confirm outside READ COMMITTED is refused.
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as isolation:
            connection.execute(
                "SELECT app.confirm_payment_return(%s,%s,%s,'financial.approve')",
                (prop, human, identity),
            )
        connection.rollback()
    assert isolation.value.sqlstate == "55000"
    # The preparer withdraws it under payments.reverse.
    withdrawn = drafts().withdraw(
        prop,
        identity,
        "Recorded against the wrong Payment",
        prepare_capability="payments.reverse",
        actor=preparer(human, prop),
    )
    assert withdrawn["state"] == "WITHDRAWN"


def test_each_refusal_of_the_source_state_is_checked(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Each case the return refuses, on the source state the recorder and the confirm read: an
    unknown or reversed Payment, a record a closed Final Settlement relied on, a Deposit with an
    active forfeiture (Q-2026-10-10-72 point 2) or Deposit application, and a waiting draft. A
    Refund of the Payment, of one of its Credits or of a Deposit it funded that is not fully
    returned is no longer refused (sub-slice 10e-1c, Q-2026-10-11-79): the source names its
    recovery charge."""
    url = migrated_database_url
    deposit = {"active_forfeiture": False, "unresolved_refund": False, "active_application": False}
    base: dict[str, Any] = {
        "payment": {"status": "RECEIVED", "refunded_usd_cents": 0},
        "credits": [{"refunded_usd_cents": 0}],
        "deposits": [deposit],
        "relied_on": [],
        "pending_drafts": [],
    }
    with psycopg.connect(url) as connection:
        connection.execute("SELECT app.assert_payment_return_allowed(%s)", (Jsonb(base),))
    # Sub-slice 10e-1c (owner answer (a) to Q-2026-10-11-79; changed expectation, was the 55000
    # refusal "A Refund paid from this Payment's value is not fully returned"): on real sources
    # (review round 1), a Refund of the Payment, of its released Credit and of the Pet Deposit it
    # funded each passes the check, and the source plans its recovery exactly: the Refund's kind
    # and source, who is charged (its recipient), on which Lease or with no Lease, the net amount
    # and the charge form. The written charges are checked in
    # test_refusals_stale_drafts_withdrawal_and_reads and test_payment_return_recovery_migration.py.
    with psycopg.connect(url) as connection:
        human, prop, _, payer = setup_reservation_sources(connection)
        payment = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=payer, amount=900
        )
    create_usd_refund(
        refund_service(),
        prop,
        CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the unused part"),
        actor=credit_actor(human, prop, "refunds.create"),
    )
    case, credit, _ = third_party_credit(url)
    refund_draft = refunds().record_credit_customer_draft(
        case.prop,
        credit_customer_refund(credit, 3_000),
        cash(refunds(), case.prop, refund_staff(case)),
        actor=refund_staff(case),
    )
    refunds().confirm_draft(case.prop, draft_id(refund_draft), actor=approving(case))
    [(invoice_customer, invoice_lease)] = rows(
        url, "SELECT customer_id,lease_id FROM app.invoices WHERE id=%s", case.invoice_wrong
    )
    pet_human, pet_prop, pet_customer, pet_lease, pet, review = qualified(url)
    create_pet_refund(
        refund_service(),
        pet_prop,
        pet_refund_command(pet, review, 15_000),
        actor=credit_actor(pet_human, pet_prop, "refunds.create"),
    )
    pet_payment = value(url, "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", pet)
    for source_property, refunded_payment, expected in (
        (prop, payment, ("PAYMENT", payment, payer, None, 300, "NO_LEASE")),
        (
            case.prop,
            case.payment,
            ("CREDIT", credit, invoice_customer, invoice_lease, 3_000, "LEASE"),
        ),
        (pet_prop, pet_payment, ("DEPOSIT", pet, pet_customer, pet_lease, 15_000, "LEASE")),
    ):
        with psycopg.connect(url) as connection:
            found = connection.execute(
                "SELECT app.payment_return_source(%s,%s,NULL)", (source_property, refunded_payment)
            ).fetchone()
            assert found is not None
            source = cast(dict[str, Any], found[0])
            [recovery] = source["recoveries"]
            kind, source_id, recipient, charge_lease, amount, charge_form = expected
            assert (
                recovery["source_kind"],
                recovery["source_id"],
                recovery["recipient_customer_id"],
                recovery["lease_id"],
                recovery["amount_usd_cents"],
                recovery["charge"],
                recovery["closed_final_settlement_id"],
                recovery["reservation_outcome"],
                recovery["shared_deposit"],
            ) == (
                kind,
                str(source_id),
                str(recipient),
                None if charge_lease is None else str(charge_lease),
                amount,
                charge_form,
                None,
                False,
                False,
            ), kind
            connection.execute("SELECT app.assert_payment_return_allowed(%s)", (Jsonb(source),))
    for change, sqlstate, message in (
        ({"payment": None}, "P4901", "Payment not found"),
        (
            {"payment": {"status": "REVERSED", "refunded_usd_cents": 0}},
            "55000",
            "Only a received Payment can be returned",
        ),
        ({"relied_on": [{"kind": "PAYMENT_ALLOCATION"}]}, "55000", RELIED_ON),
        (
            {"deposits": [{**deposit, "active_forfeiture": True}]},
            "55000",
            "A Deposit this Payment funded has an active forfeiture; reverse the forfeiture first",
        ),
        (
            {"deposits": [{**deposit, "active_application": True}]},
            "55000",
            "A Deposit this Payment funded has an active Deposit application",
        ),
        (
            {"pending_drafts": [str(uuid4())]},
            "55000",
            "A draft that names this Payment or one of its records is waiting",
        ),
    ):
        error = refused_sql(
            url, "SELECT app.assert_payment_return_allowed(%s)", Jsonb({**base, **change})
        )
        assert (error.sqlstate, error.diag.message_primary) == (sqlstate, message), change


def test_a_late_charge_allocation_is_returned_and_a_correction_s_records_are_refused(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """After closure a Payment allocated to the Late-payment Charge is returned and the Charge is
    owed again; a Payment whose Charge allocation a post-settlement REFUND correction released and
    re-posted is relied on by that correction (the linked re-posted allocation and the released
    Credit) and is refused here."""
    url = migrated_database_url
    case = settled_case(url)
    prop, human, charge = case["prop"], case["human"], case["charge"]
    first = pay_charge(case, 1_000)
    first_payment = UUID(
        str(value(url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", first))
    )
    assert unpaid(url, charge) == 7_000
    draft = returns().record(prop, request(first_payment), actor=preparer(human, prop))
    source = cast(dict[str, Any], draft["payload"])["source"]
    assert [
        (item["target_kind"], item["late_payment_charge_id"]) for item in source["allocations"]
    ] == [("LATE_PAYMENT_CHARGE", str(charge))]
    assert source["relied_on"] == []
    result = returns().confirm(prop, draft_id(draft), actor=approver(human, prop))
    assert len(cast(list[str], result["allocation_reversal_ids"])) == 1
    assert unpaid(url, charge) == 8_000 and status(url, first_payment) == "REVERSED"
    # A correction's records: the Charge paid after closure, then partly refunded by a correction.
    pay_other_debt(case)
    allocation = pay_charge(case, 8_000)
    payment = UUID(
        str(value(url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", allocation))
    )
    confirm_charge_refund(case, record_charge_refund(case, charge_refund(case, 3_000)))
    assert {"PAYMENT_ALLOCATION", "CUSTOMER_CREDIT"} <= relied_on_kinds(url, prop, payment)
    with pytest.raises(PaymentReturnConflictError) as refused:
        returns().record(prop, request(payment), actor=preparer(human, prop))
    assert cast(psycopg.Error, refused.value.__cause__).diag.message_primary == RELIED_ON
    assert status(url, payment) == "RECEIVED"


def test_a_credit_a_correction_left_held_keeps_its_payment_for_that_correction(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Review round 2 (independent SF-1), the round-1 example on the real path: before closure a
    credit Adjustment releases the Customer's newest Payment on the other Damage line whole into a
    Credit, which the Customer applies to the pet line; after the real closure a REFUND correction
    releases that application whole and refunds it, and a return-only REFUND_RETURN brings the
    whole Refund back, so the value is held on the Credit. The Payment then has no active
    allocation or Credit application and nothing refunded; only the Credit records of review
    round 1 are relied on, and they alone refuse its return."""
    url = migrated_database_url
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    prop, human, customer = case["prop"], case["human"], case["customer"]
    case["person"] = correction_approver(url)
    other, pet = case["other_line"], case["pet_line"]
    other_invoice, pet_invoice = invoice_of(url, other), invoice_of(url, pet)
    pay(url, prop, human, customer, other_invoice, other, 12_100)
    payment = pay(url, prop, human, customer, other_invoice, other, 400)
    credit_adjustment(url, human, prop, other_invoice, other)
    credit = UUID(
        str(value(url, "SELECT id FROM app.customer_credits WHERE source_payment_id=%s", payment))
    )
    pay(url, prop, human, customer, pet_invoice, pet, 12_100)
    applied = apply_credit(case, credit, pet_invoice, pet, 400)
    close_by_refunds(case)
    # At closure only the ordinary application on the pet line is relied on.
    assert relied_on_kinds(url, prop, payment) == {"CREDIT_APPLICATION"}
    result = confirm_refund_correction(
        case,
        case["person"],
        record_refund_correction(case, refund_correction(case, pet_invoice, pet, 400)),
    )
    [released] = cast(list[dict[str, Any]], result["released_sources"])
    assert (released["reversed_credit_application_id"], released["released_usd_cents"]) == (
        str(applied),
        400,
    )
    [paid] = cast(list[dict[str, Any]], result["refunds"])
    refund = UUID(str(paid["id"]))
    assert paid["source_customer_credit_id"] == str(credit)
    confirm_refund_return(
        case, record_refund_return(case, return_command(case, refund, 400, new=False))
    )
    assert net(url, refund) == 0
    assert int(value(url, "SELECT app.credit_available_value(%s)", credit)) == 400
    source = cast(
        dict[str, Any],
        value(url, "SELECT app.payment_return_source(%s,%s,NULL)", prop, payment),
    )
    assert source["allocations"] == [] and source["receipts"] == []
    assert [
        (item["id"], item["applications"], item["refunded_usd_cents"]) for item in source["credits"]
    ] == [(str(credit), [], 0)]
    assert {
        (item["kind"], item["id"], item["final_settlement_id"]) for item in source["relied_on"]
    } == {("CUSTOMER_CREDIT", str(credit), str(case["settlement"]))}
    # Without those records nothing else would refuse the return.
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.assert_payment_return_allowed(%s)", (Jsonb({**source, "relied_on": []}),)
        )
    with pytest.raises(PaymentReturnConflictError) as refused:
        returns().record(prop, request(payment), actor=preparer(human, prop))
    assert cast(psycopg.Error, refused.value.__cause__).diag.message_primary == RELIED_ON
    assert status(url, payment) == "RECEIVED"
    assert int(value(url, "SELECT app.credit_available_value(%s)", credit)) == 400


def test_the_relaxed_refusals_open_only_for_the_payment_returned_in_the_transaction(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Review round 2 (security S1): in one financial-role transaction that confirms the return of
    a third-party Payment, the slice 7 and sub-slice 8g refusals still hold for other Payments: the
    one-call reversal of another third-party Payment's Credit released to the Invoice Customer, of
    a moved Payment's moved-value Credit and of its moved allocation is refused (P4904). Then the
    transaction rolls back and nothing of it stays."""
    url = migrated_database_url
    case, credit, _ = third_party_credit(url)
    other, other_credit, _ = third_party_credit(url)
    moved, moved_value = moved_credit(url)
    moved_allocation = UUID(
        str(
            value(
                url,
                "SELECT allocation.id FROM app.payment_allocations allocation "
                "WHERE allocation.payment_id=%s "
                "AND allocation.between_invoice_basis='WRONG_UNIT_MOVE' "
                "AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal "
                "WHERE reversal.payment_allocation_id=allocation.id)",
                moved.payment,
            )
        )
    )
    draft = draft_id(
        returns().record(case.prop, request(case.payment), actor=preparer(case.human, case.prop))
    )
    attempts: tuple[tuple[str, tuple[object, ...], str], ...] = (
        (
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (other.prop, other_credit, other.human, uuid4(), "Return the value to the payer"),
            REFUSED,
        ),
        (
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (moved.prop, moved_value, moved.human, uuid4(), "Return the value to the payer"),
            MOVED_REFUSED,
        ),
        (
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (moved.prop, moved_allocation, moved.human, uuid4(), "0" * 64, "Undo the move"),
            MOVED_ALLOCATION_REFUSED,
        ),
    )
    with psycopg.connect(financial_database_url()) as connection:
        confirmed = connection.execute(
            "SELECT app.confirm_payment_return(%s,%s,%s,'financial.approve')",
            (case.prop, case.approver, draft),
        ).fetchone()
        assert confirmed is not None
        assert cast(dict[str, Any], confirmed[0])["status"] == "REVERSED"
        for statement, parameters, message in attempts:
            connection.execute("SAVEPOINT attempt")
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(statement, parameters)
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "P4904",
                message,
            ), statement
            connection.execute("ROLLBACK TO SAVEPOINT attempt")
        connection.rollback()
    assert status(url, case.payment) == "RECEIVED" and returned(url, case.payment) == []
    assert drafts().get(case.prop, draft, actor=approver(case.approver, case.prop))["state"] == (
        "PENDING"
    )
    for found in (credit, other_credit, moved_value):
        assert (
            value(
                url,
                "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
                found,
            )
            == 0
        )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.payment_allocation_reversals WHERE payment_allocation_id=%s",
            moved_allocation,
        )
        == 0
    )


def test_payment_return_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,  # noqa: F811
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions or
    touches app.payment_returns, which is append-only; the migration adds its table, triggers and
    functions, relaxes only the listed functions, and is forward-only."""
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
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.payment_returns',%s)", (role, privilege)
                ).fetchone() == (False,), (role, privilege)
    human, prop, _, _, _, payment = credit_source(url)
    identity = draft_id(returns().record(prop, request(payment), actor=preparer(human, prop)))
    returns().confirm(prop, identity, actor=approver(human, prop))
    for statement in (
        "UPDATE app.payment_returns SET reason='Changed' WHERE payment_id=%s",
        "DELETE FROM app.payment_returns WHERE payment_id=%s",
    ):
        assert refused_sql(url, statement, payment).sqlstate == "55000"
    # A row written outside the confirm is refused at commit (no decision in its transaction).
    other_human, other_prop, _, _, _, other_payment = credit_source(url)
    other = draft_id(
        returns().record(
            other_prop, request(other_payment), actor=preparer(other_human, other_prop)
        )
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES (gen_random_uuid(),%s,%s,%s,%s,"
            "clock_timestamp(),%s,'financial.approve')",
            (other_prop, other_payment, other, REASON, other_human),
        )
        with pytest.raises(psycopg.Error) as unconfirmed:
            connection.commit()
    assert unconfirmed.value.sqlstate == "42501"
    assert returned(url, other_payment) == [] and status(url, other_payment) == "RECEIVED"
    # With a decision of this transaction but the Payment not reversed, the commit is refused too.
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.financial_draft_decisions(draft_id,decision,reason,decided_at,"
            "decided_by,authorization_reference,result) VALUES (%s,'CONFIRMED',NULL,"
            "clock_timestamp(),%s,'financial.approve',"
            "jsonb_build_object('transaction_id',pg_current_xact_id()::text))",
            (other, other_human),
        )
        connection.execute(
            "INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES (gen_random_uuid(),%s,%s,%s,%s,"
            "clock_timestamp(),%s,'financial.approve')",
            (other_prop, other_payment, other, REASON, other_human),
        )
        with pytest.raises(psycopg.Error) as unreversed:
            connection.commit()
    assert unreversed.value.sqlstate == "23514"
    assert returned(url, other_payment) == [] and status(url, other_payment) == "RECEIVED"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261120_116")
    assert revision is not None and revision.down_revision == "20261119_115"
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

    with _temporary_migration_database("payment_returns") as temporary:
        alembic_command.upgrade(config, "20261119_115")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261120_116")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert after_relations - before_relations == {"app.payment_returns"}
    assert before_relations <= after_relations
    assert after_triggers - before_triggers == {
        "app.payment_returns:payment_returns_validate",
        "app.payment_returns:payment_returns_confirmed",
        "app.payment_returns:payment_returns_immutable",
        "app.payment_returns:payment_returns_no_truncate",
    }
    assert before_triggers <= after_triggers
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
