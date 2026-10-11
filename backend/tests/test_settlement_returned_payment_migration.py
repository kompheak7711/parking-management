"""Post-settlement correction: RETURNED_PAYMENT (V1-056 sub-slice 10e-1b).

Owner answer 5 to Q-2026-10-06-36 and answers 2, 3 and 5 to Q-2026-10-06-37: a returned (bounced)
Payment whose records a closed Final Settlement relied on is returned only through a correction of
that Settlement, prepared under final_settlements.prepare and confirmed only by financial.approve
(BR-SETTLE-013, BR-AUTH-010). In one transaction the confirm reverses, each record linked to the
correction, the Payment's Credit applications, Credits and allocations, the forfeitures, Deposit
applications and receipts of the Deposits it funded, and the Payment; the debt comes back on its
obligations and stays with their Customers (BR-SETTLE-016). Owner answers (a) to Q-2026-10-10-72:
a kept Deposit's forfeiture is reversed in the same correction and the Customer owes no Deposit
amount (point 2); a Payment that two closed Settlements relied on is refused (point 3).
"""

from __future__ import annotations

import json
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
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.payment_return import PaymentReturnConflictError
from property_rental.settlement_correction import RecordReturnedPaymentCorrectionCommand
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
    normal_plan,
)
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, preparer
from test_final_settlement_preview_migration import path_of, preview
from test_invoice_migration import financial_database_url, register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import WrongAllocation, allocation_ids, move, moves, rows, value
from test_payment_move_migration import approver as move_approver
from test_payment_move_migration import draft_id as move_draft_id
from test_payment_move_migration import preparer as move_preparer
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import preparer as return_preparer
from test_payment_return_migration import request as return_request
from test_payment_return_migration import returns
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_correction_migration import settlement_row
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_forfeiture_reversal_migration import kept_case
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import net, return_command
from test_settlement_refund_return_migration import record as record_return
from test_unpaid_initial_termination_migration import rent_line

RECORD = "app.record_settlement_returned_payment_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_returned_payment(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_returned_payment_input(jsonb)",
    "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
    "app.settlement_returned_payment_result(uuid)",
    "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
)
PATCHED = {"app.validate_payment_return()", "app.lock_settlement_correction_plan(uuid)"}
REASON = "The bank returned the transfer after the Final Settlement"
EVIDENCE = "Bank return notice 5120"
LINKS = (
    "credit_application_reversal_id",
    "customer_credit_reversal_id",
    "payment_allocation_reversal_id",
    "deposit_disposition_reversal_id",
    "deposit_application_reversal_id",
    "deposit_receipt_reversal_id",
    "payment_reversal_id",
)
TWO_SETTLEMENTS = (
    "Another closed Final Settlement relied on this Payment's records; a Payment that two closed "
    "Final Settlements relied on cannot be returned"
)
NOT_RELIED = (
    "This Final Settlement did not rely on this Payment's records; return it with a Payment "
    "return draft"
)
ONLY_OTHER = (
    "This Final Settlement did not rely on this Payment's records; return it through a correction "
    "of the Final Settlement that did"
)
OTHER_LEASE_FORFEITURE = (
    "A Deposit this Payment funded has an active forfeiture outside this Final Settlement's Lease; "
    "reverse the forfeiture first"
)
OTHER_SETTLEMENT_APPLICATION = (
    "A Deposit this Payment funded has a Deposit application of another Final Settlement"
)
NOT_RETURNED = "A Refund paid from this Payment's value is not fully returned"
STILL_HOLDS = "A Deposit this Payment funded would still hold money after the return"
WAITING = "A draft that names this Payment or one of its records is waiting"
SETTLEMENT_APPLICATION_REFUSED = (
    "A Final Settlement Credit application changes only through a post-settlement correction"
)
RELIED_ON = (
    "A closed Final Settlement relied on this Payment's records; "
    "return it through a correction of that Final Settlement"
)


def closed_case(url: str) -> dict[str, Any]:
    """The 8c normal-end Settlement, really closed (sub-slice 8e-3): the Initial Rent Payment's
    released Credit (400) pays the other damage line, the Pet Deposit pays the pet damage line
    (12,500), the Security Deposit (10,000) and the rest of the Pet Deposit (2,100) pay the other
    damage line, and the Pet Deposit's rest (5,400) is refunded. A correction approver is ready."""
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    confirm_settlement(case, record_settlement(case, normal_plan(case), pet_remainder=STAFF))
    case["person"] = correction_approver(url)
    return case


def credit_payment(url: str, credit: UUID) -> UUID:
    return UUID(
        str(value(url, "SELECT source_payment_id FROM app.customer_credits WHERE id=%s", credit))
    )


def receipt_payment(url: str, deposit: UUID) -> UUID:
    return UUID(
        str(value(url, "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", deposit))
    )


def command(
    case: dict[str, Any], payment: UUID, **changes: Any
) -> RecordReturnedPaymentCorrectionCommand:
    return replace(
        RecordReturnedPaymentCorrectionCommand(
            uuid4(), case["settlement"], payment, REASON, EVIDENCE
        ),
        **changes,
    )


def record(case: dict[str, Any], request: RecordReturnedPaymentCorrectionCommand) -> UUID:
    found = corrections().record_returned_payment(
        case["prop"], request, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_returned_payment(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def payload(url: str, draft: UUID) -> dict[str, Any]:
    return cast(
        dict[str, Any], value(url, "SELECT payload FROM app.financial_drafts WHERE id=%s", draft)
    )


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order."""
    found = rows(
        url,
        f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
        "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
        correction,
    )
    return [LINKS[[item is not None for item in row].index(True)] for row in found]


def status(url: str, payment: UUID) -> str:
    return str(value(url, "SELECT status FROM app.payments WHERE id=%s", payment))


def counts(url: str) -> tuple[Any, ...]:
    return one(
        url,
        "SELECT (SELECT count(*) FROM app.financial_drafts),"
        "(SELECT count(*) FROM app.settlement_corrections),"
        "(SELECT count(*) FROM app.payment_returns),(SELECT count(*) FROM app.payment_reversals),"
        "(SELECT count(*) FROM app.deposit_receipt_reversals),"
        "(SELECT count(*) FROM app.deposit_application_reversals)",
    )


def reconciled(url: str, *customers: UUID) -> None:
    with psycopg.connect(url) as connection:
        for customer in customers:
            assert_reconciled(connection, customer)


def allowed_check(url: str, case: dict[str, Any], source: dict[str, Any]) -> tuple[Any, Any]:
    """The refusal of the correction's check on a (changed) source, read as the owner; (None,
    None) when it passes."""
    with psycopg.connect(url) as connection:
        try:
            connection.execute(
                "SELECT app.assert_settlement_returned_payment_allowed(%s,%s,%s)",
                (case["settlement"], case["lease"], Jsonb(source)),
            )
        except psycopg.Error as refused:
            connection.rollback()
            return refused.sqlstate, refused.diag.message_primary
    return None, None


def payment_reversed_last(url: str, payment: UUID, correction: object) -> bool:
    """The Payment reversal is dated after every other reversal the correction linked."""
    return bool(
        value(
            url,
            "SELECT (SELECT occurred_at FROM app.payment_reversals WHERE payment_id=%s) > ALL("
            "SELECT r.occurred_at FROM app.customer_credit_application_reversals r "
            "JOIN app.settlement_correction_effects e ON e.credit_application_reversal_id=r.id "
            "WHERE e.settlement_correction_id=%s UNION ALL SELECT r.occurred_at "
            "FROM app.customer_credit_reversals r JOIN app.settlement_correction_effects e "
            "ON e.customer_credit_reversal_id=r.id WHERE e.settlement_correction_id=%s "
            "UNION ALL SELECT r.occurred_at FROM app.payment_allocation_reversals r "
            "JOIN app.settlement_correction_effects e ON e.payment_allocation_reversal_id=r.id "
            "WHERE e.settlement_correction_id=%s UNION ALL SELECT r.occurred_at "
            "FROM app.deposit_application_reversals r JOIN app.settlement_correction_effects e "
            "ON e.deposit_application_reversal_id=r.id WHERE e.settlement_correction_id=%s "
            "UNION ALL SELECT r.occurred_at FROM app.deposit_receipt_reversals r "
            "JOIN app.settlement_correction_effects e ON e.deposit_receipt_reversal_id=r.id "
            "WHERE e.settlement_correction_id=%s UNION ALL SELECT r.occurred_at "
            "FROM app.deposit_disposition_reversals r JOIN app.settlement_correction_effects e "
            "ON e.deposit_disposition_reversal_id=r.id WHERE e.settlement_correction_id=%s)",
            payment,
            *([correction] * 6),
        )
    )


def test_a_bounced_payment_whose_credit_the_settlement_used_is_returned_by_a_correction(
    migrated_database_url: str,
) -> None:
    """The owner's case: the Initial Rent Payment's released Credit paid 400 through a Final
    Settlement Credit application. Outside a correction that application is never reversed
    (8e-2). The draft lists what comes back and moves nothing; Staff cannot confirm it. The
    approver's confirm reverses, each linked to the correction, the Settlement Credit application,
    the Credit, the Payment's allocation and the Payment; the debt is back on the other damage line
    and the Initial Rent line of the same Customer; the Settlement row and its closure snapshots
    are unchanged; the payment_returns row names the correction; an exact repeat replays and no
    result shows the decision's transaction id; the ledger reconciles."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human, customer = case["prop"], case["human"], case["customer"]
    payment = credit_payment(url, case["credit"])
    rent, _ = rent_line(url, case["initial"])
    application = UUID(
        str(
            value(
                url,
                "SELECT id FROM app.customer_credit_applications WHERE customer_credit_id=%s "
                "AND final_settlement_id=%s",
                case["credit"],
                case["settlement"],
            )
        )
    )
    # The 8e-2 refusal holds outside a correction (a reversal row written as the table owner).
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as one_call:
            connection.execute(
                "INSERT INTO app.customer_credit_application_reversals(id,credit_application_id,"
                "reason,occurred_at,actor_id,authorization_reference) VALUES (gen_random_uuid(),"
                "%s,'Bank return',clock_timestamp(),%s,'credits.applications.reverse')",
                (application, human),
            )
    assert (one_call.value.sqlstate, one_call.value.diag.message_primary) == (
        "P5S01",
        SETTLEMENT_APPLICATION_REFUSED,
    )
    before_row = settlement_row(url, case["settlement"])
    before_counts = counts(url)
    assert (outstanding(url, case["other_line"]), outstanding(url, rent)) == (0, 0)
    request = command(case, payment)
    draft = record(case, request)
    stored = payload(url, draft)
    assert (stored["variant"], stored["payment_id"], stored["returned_payment"]) == (
        "RETURNED_PAYMENT",
        str(payment),
        {"payment_id": str(payment), "evidence_reference": EVIDENCE},
    )
    source = stored["source"]
    [allocated] = source["allocations"]
    [credit] = source["credits"]
    assert (credit["id"], credit["available_usd_cents"]) == (str(case["credit"]), 0)
    assert [item["id"] for item in credit["applications"]] == [str(application)]
    assert source["receipts"] == [] and source["deposit_applications"] == []
    assert {item["kind"] for item in source["relied_on"]} == {
        "PAYMENT_ALLOCATION",
        "CREDIT_APPLICATION",
        "CUSTOMER_CREDIT",
    }
    assert {item["final_settlement_id"] for item in source["relied_on"]} == {
        str(case["settlement"])
    }
    # A draft moves nothing; an exact repeat returns the same draft.
    assert counts(url)[1:] == before_counts[1:] and status(url, payment) == "RECEIVED"
    assert (
        UUID(
            str(
                corrections().record_returned_payment(prop, request, actor=preparer(human, prop))[
                    "draft_id"
                ]
            )
        )
        == draft
    )
    # Staff cannot confirm, in the service and in the database.
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_returned_payment(prop, draft, actor=preparer(human, prop))
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as staff:
            connection.execute(
                "SELECT app.confirm_settlement_returned_payment(%s,%s,%s,%s)",
                (prop, human, draft, "final_settlements.prepare"),
            )
    assert staff.value.sqlstate == "42501" and state(url, draft) == "PENDING"
    # A service identity is not a person (P4506), as for every other confirm.
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with psycopg.connect(financial_database_url()) as connection:
        with pytest.raises(psycopg.Error) as service_identity:
            connection.execute(
                "SELECT app.confirm_settlement_returned_payment(%s,%s,%s,'financial.approve')",
                (prop, machine, draft),
            )
    assert service_identity.value.sqlstate == "P4506" and state(url, draft) == "PENDING"
    result = confirm(case, draft)
    assert "transaction_id" not in json.dumps(result, default=str)
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "credit_application_reversal_id",
        "customer_credit_reversal_id",
        "payment_allocation_reversal_id",
        "payment_reversal_id",
    ]
    assert payment_reversed_last(url, payment, correction)
    assert result["payment_return"]["settlement_correction_id"] == correction
    assert result["payment_return"]["status"] == "REVERSED"
    assert rows(
        url,
        "SELECT draft_id,actor_id,reason,authorization_reference,settlement_correction_id::text "
        "FROM app.payment_returns WHERE payment_id=%s",
        payment,
    ) == [(draft, case["person"], REASON, "financial.approve", correction)]
    assert rows(
        url,
        "SELECT actor_id,authorization_reference,reason "
        "FROM app.customer_credit_application_reversals WHERE credit_application_id=%s",
        application,
    ) == [(case["person"], "credits.applications.reverse", REASON)]
    # The debt is back on its obligations, with the same Customer (BR-SETTLE-016).
    assert outstanding(url, case["other_line"]) == 400
    assert outstanding(url, rent) == allocated["amount_usd_cents"]
    assert int(value(url, "SELECT app.credit_available_value(%s)", case["credit"])) == 0
    assert status(url, payment) == "REVERSED" and state(url, draft) == "CONFIRMED"
    assert settlement_row(url, case["settlement"]) == before_row
    audit = one(
        url,
        "SELECT customer_id,lease_id,resulting_state FROM app.audit_events "
        "WHERE action='final_settlement.correction.confirmed' AND correlation_id=%s",
        correction,
    )
    assert (audit[0], audit[1]) == (customer, case["lease"])
    assert (audit[2]["variant"], audit[2]["payment_id"], audit[2]["status"]) == (
        "RETURNED_PAYMENT",
        str(payment),
        "REVERSED",
    )
    assert confirm(case, draft) == result
    with pytest.raises(FinalSettlementConflictError) as decided:
        corrections().confirm_returned_payment(
            prop, draft, actor=approving(correction_approver(url), prop)
        )
    assert cause(decided) == ("55000", "Financial draft is already decided")
    reconciled(url, customer)


def test_a_bounced_payment_whose_security_deposit_the_settlement_applied_is_returned(
    migrated_database_url: str,
) -> None:
    """The owner's case: the Payment that funded the Security Deposit, which the Settlement applied
    (10,000) to the other damage line. The confirm reverses the Settlement's Deposit application
    (linked, financial.approve, the approver) and then the receipt (linked; deposits.correct, its
    command record and deposit.receipt.reversed audit event, dated after the application
    reversal) and the Payment. The Deposit is empty and the 10,000 is owed again by the same
    Customer; the closure snapshots are unchanged."""
    url = migrated_database_url
    case = closed_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    payment = receipt_payment(url, security)
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    [receipt] = source["receipts"]
    [applied] = source["deposit_applications"]
    assert (receipt["deposit_id"], receipt["amount_usd_cents"]) == (str(security), 10_000)
    assert (applied["deposit_id"], applied["invoice_line_id"], applied["amount_usd_cents"]) == (
        str(security),
        str(other_line),
        10_000,
    )
    assert source["forfeitures"] == [] and source["allocations"] == []
    # The check passes on the real source; with the application named as another Settlement's
    # it refuses (review round 1, SF-2).
    assert allowed_check(url, case, source) == (None, None)
    other = json.loads(json.dumps(source))
    other["deposit_applications"][0]["final_settlement_id"] = str(uuid4())
    assert allowed_check(url, case, other) == ("55000", OTHER_SETTLEMENT_APPLICATION)
    result = confirm(case, draft)
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
        "payment_reversal_id",
    ]
    assert payment_reversed_last(url, payment, correction)
    [application_reversal] = result["deposit_application_reversal_ids"]
    [receipt_reversal] = result["deposit_receipt_reversal_ids"]
    application_at, application_actor, application_authorization = one(
        url,
        "SELECT occurred_at,actor_id,authorization_reference "
        "FROM app.deposit_application_reversals WHERE id=%s",
        application_reversal,
    )
    receipt_at, receipt_actor, receipt_authorization = one(
        url,
        "SELECT occurred_at,actor_id,authorization_reference FROM app.deposit_receipt_reversals "
        "WHERE id=%s",
        receipt_reversal,
    )
    assert (application_actor, application_authorization) == (case["person"], "financial.approve")
    assert (receipt_actor, receipt_authorization) == (case["person"], "deposits.correct")
    assert receipt_at > application_at
    assert (
        value(
            url,
            "SELECT count(*) FROM app.audit_events WHERE id=%s "
            "AND action='deposit.receipt.reversed' AND actor_id=%s",
            UUID(receipt_reversal),
            case["person"],
        )
        == 1
    )
    assert (
        value(
            url,
            "SELECT count(*) FROM app.deposit_commands WHERE deposit_id=%s "
            "AND action='deposit.receipt.reverse' AND actor_id=%s",
            security,
            case["person"],
        )
        == 1
    )
    assert (held(url, security), outstanding(url, other_line)) == (0, 10_000)
    assert status(url, payment) == "REVERSED"
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


def test_a_kept_deposit_paid_by_a_bounced_payment_is_returned_without_a_charge(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-10-72 point 2: voluntary early leaving kept the Security
    Deposit (10,000, BR-DEP-023), then its Payment bounced. One correction reverses the
    forfeiture (linked, through the existing reversal function: the approver, deposits.correct,
    the draft's reason and evidence), then the receipt, then the Payment. The Deposit ends empty
    and back on the DL-032 path; no Invoice or charge is made for the Deposit amount; the 4,600
    that stayed open on the other damage line is unchanged."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, security = case["prop"], case["human"], case["security"]
    payment = receipt_payment(url, security)
    invoices_before = value(
        url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", case["lease"]
    )
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    assert [(item["id"], item["amount_usd_cents"]) for item in source["forfeitures"]] == [
        (str(case["disposition"]), 10_000)
    ]
    # The check passes on the real source; a forfeiture governed by another Lease is refused
    # (review round 1, SF-2).
    assert allowed_check(url, case, source) == (None, None)
    other = json.loads(json.dumps(source))
    other["forfeitures"][0]["governing_lease_id"] = str(uuid4())
    assert allowed_check(url, case, other) == ("55000", OTHER_LEASE_FORFEITURE)
    result = confirm(case, draft)
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "deposit_disposition_reversal_id",
        "deposit_receipt_reversal_id",
        "payment_reversal_id",
    ]
    [reversal] = result["forfeiture_reversal_ids"]
    assert one(
        url,
        "SELECT deposit_disposition_id,actor_id,authorization_reference,reason,evidence_reference "
        "FROM app.deposit_disposition_reversals WHERE id=%s",
        UUID(reversal),
    ) == (case["disposition"], case["person"], "deposits.correct", REASON, EVIDENCE)
    assert held(url, security) == 0 and status(url, payment) == "REVERSED"
    assert path_of(preview(prop, human, case["settlement"]), security) == (
        "BR-DEP-023",
        "REVERSED",
        "DL_032",
        0,
    )
    assert (
        value(url, "SELECT count(*) FROM app.invoices WHERE lease_id=%s", case["lease"])
        == invoices_before
    )
    assert outstanding(url, case["other_line"]) == 4_600
    assert payment_reversed_last(url, payment, correction)
    reconciled(url, case["customer"])


def test_a_funded_deposit_whose_refund_came_back_in_full_ends_empty(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-10-77: the Settlement refunded the Pet Deposit's rest (5,400)
    and a return-only correction brought all of it back, so the Pet Deposit holds 5,400 again on
    the DL-032 path. A Refund paid and fully returned cancels out: the check accepts the Pet
    Deposit's bounced Payment, the confirm reverses both of the Settlement's Pet Deposit
    applications and the receipt (20,000), and the Pet Deposit ends at 0; the debt (12,500 and
    2,100) is back on the two damage lines; the Refund and its return stay as written."""
    url = migrated_database_url
    case = closed_case(url)
    pet, refund = case["pet"], pet_refund(case)
    confirm_return(case, record_return(case, return_command(case, refund, 5_400, new=False)))
    assert (held(url, pet), net(url, refund)) == (5_400, 0)
    payment = receipt_payment(url, pet)
    draft = record(case, command(case, payment))
    source = payload(url, draft)["source"]
    [deposit] = source["deposits"]
    assert (deposit["held_usd_cents"], deposit["unresolved_refund"]) == (5_400, False)
    assert sorted(item["amount_usd_cents"] for item in source["deposit_applications"]) == [
        2_100,
        12_500,
    ]
    assert [item["amount_usd_cents"] for item in source["receipts"]] == [20_000]
    result = confirm(case, draft)
    assert effect_links(url, result["settlement_correction"]["id"]) == [
        "deposit_application_reversal_id",
        "deposit_application_reversal_id",
        "deposit_receipt_reversal_id",
        "payment_reversal_id",
    ]
    assert (held(url, pet), status(url, payment), net(url, refund)) == (0, "REVERSED", 0)
    assert (outstanding(url, case["pet_line"]), outstanding(url, case["other_line"])) == (
        12_500,
        2_100,
    )
    reconciled(url, case["customer"])


def two_settlements_case(url: str, *, close_second: bool = True) -> dict[str, Any]:
    """Owner answer (a) to Q-2026-10-10-72 point 3: one Payment of the first Lease's Customer pays
    1,000 of that Lease's other damage line twice; one allocation is moved (a confirmed wrong-Unit
    move, BR-PAY-042) to the second Lease's other damage line. The Final Settlements then close
    (the second only with close_second): Credit 400, the Pet Deposit pays the pet damage, the
    Security Deposit and 1,100 of the Pet Deposit pay the other damage line, and the Pet Deposit's
    rest (6,400) is refunded."""
    first = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    second = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    prop, human = first["prop"], first["human"]
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=first["customer"],
            amount=2_000,
        )
    invoice = invoice_of(url, first["other_line"])
    posted = [
        allocation_ids(
            allocations().post(
                prop,
                payment,
                designated(invoice, first["other_line"], 1_000),
                actor=allocation_actor(human, prop),
            )
        )[0]
        for _ in range(2)
    ]
    wrong = WrongAllocation(
        human,
        human,
        prop,
        first["customer"],
        second["customer"],
        first["lease"],
        invoice,
        first["other_line"],
        invoice_of(url, second["other_line"]),
        second["other_line"],
        payment,
        posted[1],
    )
    moves().confirm(
        prop,
        move_draft_id(moves().record(prop, move(wrong), actor=move_preparer(wrong))),
        actor=move_approver(wrong),
    )
    for case in (first, second) if close_second else (first,):
        assert outstanding(url, case["other_line"]) == 11_500
        confirm_settlement(
            case,
            record_settlement(
                case,
                (
                    SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
                    SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
                    SettlementDepositStep(
                        SECURITY, case["security"], LINE, case["other_line"], 10_000
                    ),
                    SettlementDepositStep(PET_REST, case["pet"], LINE, case["other_line"], 1_100),
                    settlement_refund(case, "pet", 6_400),
                ),
                pet_remainder=STAFF,
            ),
        )
        case["person"] = correction_approver(url)
    return {"first": first, "second": second, "payment": payment}


def test_a_payment_that_two_closed_settlements_relied_on_is_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-10-72 point 3 (a known limit): one correction belongs to one
    Settlement, so a correction of either Settlement refuses the Payment (55000) and writes
    nothing, and the PAYMENT_RETURN draft refuses it as relied on."""
    url = migrated_database_url
    found = two_settlements_case(url)
    payment, first, second = found["payment"], found["first"], found["second"]
    relied = cast(
        list[dict[str, str]],
        value(
            url,
            "SELECT app.payment_return_source(%s,%s,NULL)->'relied_on'",
            first["prop"],
            payment,
        ),
    )
    assert {item["final_settlement_id"] for item in relied} == {
        str(first["settlement"]),
        str(second["settlement"]),
    }
    before = counts(url)
    for case in (first, second):
        with pytest.raises(FinalSettlementConflictError) as refused:
            record(case, command(case, payment))
        assert cause(refused) == ("55000", TWO_SETTLEMENTS)
    with pytest.raises(PaymentReturnConflictError) as plain:
        returns().record(
            first["prop"],
            return_request(payment),
            actor=return_preparer(first["human"], first["prop"]),
        )
    assert cast(psycopg.Error, plain.value.__cause__).diag.message_primary == RELIED_ON
    # Review round 1 (SF-1): a Payment that only the first Settlement relied on, recorded under the
    # second Settlement, is pointed to the first Settlement's correction.
    with pytest.raises(FinalSettlementConflictError) as wrong_settlement:
        record(second, command(second, credit_payment(url, first["credit"])))
    assert cause(wrong_settlement) == ("55000", ONLY_OTHER)
    assert counts(url) == before and status(url, payment) == "RECEIVED"
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        0,
        0,
    )


def test_a_record_on_another_open_lease_is_reversed_and_linked(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent N6): the returned Payment's moved allocation sits on another
    Lease whose Final Settlement is not closed. The first Lease's correction locks that Invoice
    (outside its Lease) and reverses both allocations, the moved one through the slice 7 refusal
    only because the Payment is returned in the same transaction; each reversal is linked. The
    debt is back on both damage lines, each with its own Customer."""
    url = migrated_database_url
    found = two_settlements_case(url, close_second=False)
    payment, first, second = found["payment"], found["first"], found["second"]
    assert value(
        url, "SELECT closed_at IS NULL FROM app.final_settlements WHERE id=%s", second["settlement"]
    )
    assert outstanding(url, second["other_line"]) == 11_500
    result = confirm(first, record(first, command(first, payment)))
    correction = result["settlement_correction"]["id"]
    assert effect_links(url, correction) == [
        "payment_allocation_reversal_id",
        "payment_allocation_reversal_id",
        "payment_reversal_id",
    ]
    assert rows(
        url,
        "SELECT invoice.lease_id FROM app.payment_allocation_reversals reversal "
        "JOIN app.payment_allocations allocation ON allocation.id=reversal.payment_allocation_id "
        "JOIN app.invoices invoice ON invoice.id=allocation.invoice_id "
        "JOIN app.settlement_correction_effects effect "
        "ON effect.payment_allocation_reversal_id=reversal.id "
        "WHERE effect.settlement_correction_id=%s ORDER BY effect.effect_sequence",
        correction,
    ) == [(second["lease"],), (first["lease"],)]
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        1_000,
        12_500,
    )
    assert status(url, payment) == "REVERSED"
    reconciled(url, first["customer"], second["customer"])


def test_refusals_stale_drafts_and_a_deposit_that_would_still_hold_money(
    migrated_database_url: str,
) -> None:
    """Refused with nothing written: a Payment this Settlement did not rely on (the PAYMENT_RETURN
    draft returns it); an unknown Payment (not found); a Settlement that is not closed; a second
    draft while one waits; a reused draft id; a recorder outside READ COMMITTED. The Pet
    Deposit's Payment, from which the Settlement refunded 5,400, is recorded with its recovery
    planned (sub-slice 10e-1c). A draft whose Payment changed after it was recorded is stale and
    stays pending. A funded Deposit that would still hold money after the return is refused (the
    check, read as the owner on a changed source)."""
    url = migrated_database_url
    case = closed_case(url)
    prop, human = case["prop"], case["human"]
    before = counts(url)
    with psycopg.connect(url) as connection:
        loose = seed_payment(
            connection, actor_id=human, property_id=prop, customer_id=case["customer"], amount=900
        )
    with pytest.raises(FinalSettlementConflictError) as unrelied:
        record(case, command(case, loose))
    assert cause(unrelied) == ("55000", NOT_RELIED)
    with pytest.raises(FinalSettlementNotFoundError) as unknown:
        record(case, command(case, uuid4()))
    assert cause(unknown) == ("P0002", "Payment was not found")
    # Sub-slice 10e-1c (owner answer (a) to Q-2026-10-11-79; changed expectation, was the 55000
    # refusal NOT_RETURNED): the Pet Deposit's Payment is recorded; its draft plans to charge the
    # 5,400 the Settlement refunded to the Deposit owner, on this Lease, inside this correction
    # (an EXTRA_CHARGE); the confirm is checked in test_payment_return_recovery_migration.py.
    pet_draft = record(case, command(case, receipt_payment(url, case["pet"])))
    [planned] = payload(url, pet_draft)["source"]["recoveries"]
    assert (
        planned["recipient_customer_id"],
        planned["lease_id"],
        planned["amount_usd_cents"],
        planned["charge"],
        planned["closed_final_settlement_id"],
    ) == (
        str(case["customer"]),
        str(case["lease"]),
        5_400,
        "CLOSED_SETTLEMENT_LEASE",
        str(case["settlement"]),
    )
    open_case = leaving_case(url)
    with pytest.raises(FinalSettlementConflictError) as not_closed:
        record(open_case, command(open_case, credit_payment(url, open_case["credit"])))
    assert cause(not_closed) == (
        "55000",
        "A post-settlement correction needs a closed Final Settlement",
    )
    assert counts(url)[1:] == before[1:]
    payment = credit_payment(url, case["credit"])
    request = command(case, payment)
    draft = record(case, request)
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(request, reason="Another reason"))
    with pytest.raises(FinalSettlementConflictError) as waiting:
        record(case, command(case, payment))
    assert cause(waiting) == ("55000", WAITING)
    with psycopg.connect(financial_database_url()) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with pytest.raises(psycopg.Error) as isolation:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (
                    prop,
                    human,
                    uuid4(),
                    case["settlement"],
                    Jsonb({"payment_id": str(loose), "evidence_reference": EVIDENCE}),
                    REASON,
                ),
            )
    assert isolation.value.sqlstate == "55000"
    assert isolation.value.diag.message_primary == (
        "A returned-Payment correction draft is recorded at READ COMMITTED"
    )
    # The funded-Deposit check on the Security Deposit's real source with one cent more held.
    security_payment = receipt_payment(url, case["security"])
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT app.settlement_returned_payment_source(%s,%s,%s,NULL)",
            (prop, case["settlement"], security_payment),
        ).fetchone()
        assert found is not None
        source = cast(dict[str, Any], found[0])
        connection.execute(
            "SELECT app.assert_settlement_returned_payment_allowed(%s,%s,%s)",
            (case["settlement"], case["lease"], Jsonb(source)),
        )
        source["deposits"][0]["held_usd_cents"] += 1
        with pytest.raises(psycopg.Error) as holds:
            connection.execute(
                "SELECT app.assert_settlement_returned_payment_allowed(%s,%s,%s)",
                (case["settlement"], case["lease"], Jsonb(source)),
            )
    assert (holds.value.sqlstate, holds.value.diag.message_primary) == ("55000", STILL_HOLDS)
    # A change to the Payment's records after the draft makes it stale; it stays pending.
    rent, _ = rent_line(url, case["initial"])
    allocation = UUID(
        str(
            value(
                url,
                "SELECT allocation.id FROM app.payment_allocations allocation "
                "WHERE allocation.payment_id=%s AND NOT EXISTS(SELECT 1 FROM "
                "app.payment_allocation_reversals reversal "
                "WHERE reversal.payment_allocation_id=allocation.id)",
                payment,
            )
        )
    )
    # As the one-call allocation reversal writes it (still open before sub-slice 10h).
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.payment_allocation_reversals(id,payment_allocation_id,reason,"
            "occurred_at,actor_id,authorization_reference) VALUES (gen_random_uuid(),%s,"
            "'Posted to the wrong line',app.credit_excess_instant(%s,NULL),%s,"
            "'payments.allocations.reverse')",
            (allocation, invoice_of(url, rent), human),
        )
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, draft)
    assert state(url, draft) == "PENDING" and status(url, payment) == "RECEIVED"
    assert counts(url)[1:] == before[1:]


def test_the_payment_return_row_names_only_its_own_correction(
    migrated_database_url: str,
) -> None:
    """The relaxed app.validate_payment_return: a RETURNED_PAYMENT correction draft needs the
    correction it confirms, and a PAYMENT_RETURN draft still takes no correction (23514)."""
    url = migrated_database_url
    case = closed_case(url)
    payment = credit_payment(url, case["credit"])
    draft = record(case, command(case, payment))
    # No correction; another id; the draft's own correction id before any correction is written.
    own = UUID(str(value(url, "SELECT app.settlement_correction_id(%s)", draft)))
    for correction in (None, uuid4(), own):
        with psycopg.connect(url) as connection:
            with pytest.raises(psycopg.Error) as refused:
                connection.execute(
                    "INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,"
                    "settlement_correction_id,reason,occurred_at,actor_id,authorization_reference) "
                    "VALUES (gen_random_uuid(),%s,%s,%s,%s,%s,clock_timestamp(),%s,"
                    "'financial.approve')",
                    (case["prop"], payment, draft, correction, REASON, case["person"]),
                )
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "23514",
            "Payment return does not match its Payment and draft",
        )
    plain = UUID(
        str(
            returns().record(
                case["prop"],
                return_request(seed_loose_payment(url, case)),
                actor=return_preparer(case["human"], case["prop"]),
            )["draft_id"]
        )
    )
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as with_correction:
            connection.execute(
                "INSERT INTO app.payment_returns(id,property_id,payment_id,draft_id,"
                "settlement_correction_id,reason,occurred_at,actor_id,authorization_reference) "
                "SELECT gen_random_uuid(),%s,(payload->>'payment_id')::uuid,id,%s,reason,"
                "clock_timestamp(),%s,'financial.approve' FROM app.financial_drafts WHERE id=%s",
                (case["prop"], own, case["person"], plain),
            )
    assert with_correction.value.sqlstate == "23514"
    returns().confirm(case["prop"], plain, actor=return_approver(case["person"], case["prop"]))


def seed_loose_payment(url: str, case: dict[str, Any]) -> UUID:
    """A received Payment of the Customer with no record a Settlement relied on."""
    with psycopg.connect(url) as connection:
        return seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=case["customer"],
            amount=700,
        )


def test_returned_payment_corrections_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; each new
    function is SECURITY DEFINER with the fixed search path; the migration adds only its functions,
    changes only the two listed functions (their privileges and settings kept) and is
    forward-only."""
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
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261121_117")
    assert revision is not None and revision.down_revision == "20261120_116"
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

    with _temporary_migration_database("settlement_returned_payment") as temporary:
        alembic_command.upgrade(config, "20261120_116")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261121_117")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    # Each patched function changed only its definition, never its privileges or settings.
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
