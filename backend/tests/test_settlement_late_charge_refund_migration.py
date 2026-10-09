"""Post-settlement correction: REFUND of a paid Late-payment Charge (V1-056 sub-slice 10c-3b-1).

Owner answer to Q-2026-10-07-38 (b), BR-LATE-005 and BR-CREDIT-014 as amended: after the Lease's
Final Settlement is closed, a wrong Late-payment Charge that Payments or Credits paid is fixed by a
REFUND correction, prepared under final_settlements.prepare and confirmed only by financial.approve
(BR-SETTLE-013, BR-AUTH-010). The confirm reverses what paid the reduced part, newest first (Q-41
answer 2), writes one linked Late-payment Charge correction, re-posts each source's unreleased rest,
makes released Payment value Credit of the Charge's Customer, lets released Credit first pay its own
Customer's open debt on the Lease (Q-42 answer 2) and refunds the rest. The release record names the
Charge correction instead of an Adjustment (owner answer 2 to Q-2026-10-09-66). A Charge a Deposit
application paid is corrected since sub-slice 10c-3b-2 (its own module).
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
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.credit import (
    ApplyCreditCommand,
    CreditConflictError,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
    SettlementTargetKind,
)
from property_rental.payment_allocation import PostAllocationsCommand
from property_rental.settlement_correction import (
    RecordLateChargeRefundCorrectionCommand,
    RecordRefundCorrectionCommand,
)
from test_credit_application_migration import application_id
from test_credit_migration import actor as credit_actor
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_migration import one, outstanding, preparer
from test_final_settlement_preview_migration import pay
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_settlement_charge_reduction_migration import invoice_of
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_late_charge_reduction_migration import (
    charge_amount,
    charge_corrections,
    closed_overdue_case,
    unpaid,
)
from test_settlement_refund_correction_migration import REVERSAL_REFUSED, ledger_event_ids

REASON = "The Late-payment Charge used the wrong rate and was paid"
NOTE = "Cash handed over at the front desk"
CHARGE_REASON = "Late-payment Charge correction credit excess"
RECORD = "app.record_settlement_late_charge_refund_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_late_charge_refund(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_late_charge_refund_input(jsonb)",
    "app.settlement_late_charge_refund_sources(uuid)",
    "app.settlement_late_charge_refund_source_state(uuid,uuid)",
    "app.settlement_late_charge_refund_overlay(jsonb,uuid)",
    "app.settlement_late_charge_refund_plan(uuid,uuid,jsonb)",
    "app.settlement_late_charge_refund_result(uuid)",
    "app.settlement_late_charge_instant(uuid,uuid)",
)
CHANGED = {
    "app.confirm_settlement_refund(uuid,uuid,uuid,text)": "LINE_CONFIRM_REPLACEMENTS",
    "app.lock_settlement_correction_plan(uuid)": "PLAN_LOCK_REPLACEMENTS",
    "app.validate_invoice_credit_excess_release()": "RELEASE_VALIDATOR_REPLACEMENTS",
    "app.validate_credit_recognition()": "CREDIT_RECOGNITION_REPLACEMENTS",
    "app.settlement_correction_refund_allowed(app.refunds)": "REFUND_ALLOWED_REPLACEMENTS",
    "app.settlement_correction_credit_id(uuid,uuid)": "CREDIT_KEY_REPLACEMENTS",
    "app.audit_payment_allocation_event()": "ALLOCATION_AUDIT_REPLACEMENTS",
    "app.audit_credit_application_event()": "APPLICATION_AUDIT_REPLACEMENTS",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)": "PLAN_CHECK_REPLACEMENTS",
}
NOTHING_RELEASED = (
    "The Refund correction releases no paid value; an unpaid charge is removed by a charge "
    "reduction"
)
NOT_OPEN = "The corrected Late-payment Charge is not an open obligation of this Final Settlement"
NOT_OURS = "The corrected Late-payment Charge is not a Charge of this Final Settlement"
CREDIT_FIRST = (
    "Customer Credit the correction releases pays its own Customer's open debt on this Lease "
    "before any Refund"
)
MISMATCH = "Credit excess release does not match its reversed source"
LINKS = (
    "payment_allocation_reversal_id",
    "credit_application_reversal_id",
    "late_payment_charge_correction_id",
    "payment_allocation_id",
    "customer_credit_application_id",
    "refund_id",
)
NOT_FOUND = "Post-settlement correction draft was not found"


def settled_case(url: str) -> dict[str, Any]:
    """The overdue two-Signer Lease of sub-slice 8c, really closed (sub-slice 8e-3): the Signer's
    Credit pays 400 of the Signer's line and the remaining Pet Deposit, by staff decision, pays
    20,000 of the Primary Tenant's Rent line. The Late-payment Charge (8,000) stays unpaid at
    closure; the Primary Tenant still owes 60,000 of Rent and the 1,500 key card. A correction
    approver is ready."""
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    case["key_card"] = invoice_of(url, case["tenant_line"])
    assert (charge_amount(url, case["charge"]), unpaid(url, case["charge"])) == (8_000, 8_000)
    return case


def credit_settled_case(url: str) -> dict[str, Any]:
    """The same Lease, but before closure the Primary Tenant holds 1,500 of Credit (the excess of a
    3,000 Payment identified for the key card Invoice, which it paid). The Settlement applies that
    Credit to the Charge (owner answer 2 to Q-2026-10-05-29: each Customer's Credit first), the
    Signer's Credit to the Signer's line and the remaining Pet Deposit to the Rent line, and is
    really closed. The Charge then owes 6,500."""
    case = {**two_signer_case(url, overdue_rent=True), "url": url}
    prop, human, tenant = case["prop"], case["human"], case["tenant"]
    key_card = invoice_of(url, case["tenant_line"])
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=tenant,
            amount=3_000,
            invoice_id=key_card,
        )
    allocations().post(
        prop,
        payment,
        designated(key_card, case["tenant_line"], 1_500),
        actor=allocation_actor(human, prop),
    )
    credit = credit_id(recognize(prop, payment, human, 1_500))
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementCreditStep(
                    credit, SettlementTargetKind.LATE_PAYMENT_CHARGE, case["charge"], 1_500
                ),
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent_line"], 20_000),
            ),
            pet_remainder=STAFF,
        ),
    )
    case.update(person=approver(url), key_card=key_card, tenant_credit=credit)
    assert unpaid(url, case["charge"]) == 6_500
    return case


def pay_other_debt(case: dict[str, Any], *, key_card: bool = True) -> None:
    """After closure the Primary Tenant pays the rest of the Rent and, unless told otherwise, the
    key card (owner answer 7 to Q-2026-10-05-20: the Customer can still pay)."""
    url, prop, human, tenant = case["url"], case["prop"], case["human"], case["tenant"]
    pay(url, prop, human, tenant, case["rent"], case["rent_line"], 60_000)
    if key_card:
        pay(url, prop, human, tenant, case["key_card"], case["tenant_line"], 1_500)


def pay_charge(case: dict[str, Any], amount: int, *, payer: UUID | None = None) -> UUID:
    """A Payment allocated directly to the Charge after closure: by the Primary Tenant, or by a
    third party identified for the Lease. Returns the allocation."""
    with psycopg.connect(case["url"]) as connection:
        if payer is not None:
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,'Third-party payer',%s,%s)",
                (payer, case["human"], case["human"]),
            )
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=payer or case["tenant"],
            amount=amount,
            **({"scope": "THIRD_PARTY_IDENTIFIED", "lease_id": case["lease"]} if payer else {}),
        )
    allocations().post(
        case["prop"],
        payment,
        PostAllocationsCommand(
            uuid4(),
            {
                "mode": "DIRECT_CHARGE",
                "late_payment_charge_id": str(case["charge"]),
                "amount_usd_cents": amount,
            },
        ),
        actor=allocation_actor(case["human"], case["prop"]),
    )
    found = one(case["url"], "SELECT id FROM app.payment_allocations WHERE payment_id=%s", payment)
    return UUID(str(found[0]))


def apply_tenant_credit(case: dict[str, Any], amount: int) -> tuple[UUID, UUID]:
    """The Primary Tenant's own Credit applied directly to the Charge after closure: the excess of
    a Payment identified for the paid key card Invoice (so no open obligation of that Payment
    stops its recognition). Returns the Credit and the application."""
    url, prop, human = case["url"], case["prop"], case["human"]
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=human,
            property_id=prop,
            customer_id=case["tenant"],
            amount=amount,
            invoice_id=case["key_card"],
        )
    credit = credit_id(recognize(prop, payment, human, amount))
    application = application_id(
        credits().apply(
            prop,
            credit,
            ApplyCreditCommand(
                uuid4(),
                {
                    "mode": "DIRECT_CHARGE",
                    "late_payment_charge_id": str(case["charge"]),
                    "amount_usd_cents": amount,
                },
            ),
            actor=credit_actor(human, prop, "credits.apply"),
        )
    )
    return credit, application


def command(
    case: dict[str, Any], amount: int, **changes: Any
) -> RecordLateChargeRefundCorrectionCommand:
    return replace(
        RecordLateChargeRefundCorrectionCommand(
            uuid4(), case["settlement"], case["charge"], amount, case["cash"], NOTE, REASON
        ),
        **changes,
    )


def record(case: dict[str, Any], refund: RecordLateChargeRefundCorrectionCommand) -> UUID:
    found = corrections().record_late_charge_refund(
        case["prop"], refund, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_late_charge_refund(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def effects(url: str, correction_id: object) -> list[str]:
    """The name of each effect's one link, in effect order."""
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(LINKS)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction_id,),
        ).fetchall()
    return [next(name for name, value in zip(LINKS, row, strict=True) if value) for row in rows]


def drafts(url: str) -> int:
    return int(one(url, "SELECT count(*) FROM app.financial_drafts")[0])


def available(url: str, credit: object) -> int:
    return int(one(url, "SELECT app.credit_available_value(%s)", credit)[0])


def released_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["released_sources"])


def refunds_of(result: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result["refunds"])


def charge_correction_of(result: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], result["late_payment_charge_correction"])


def test_a_paid_charge_is_partly_refunded_and_its_rest_stays_paid_after_closure(
    migrated_database_url: str,
) -> None:
    """On a really closed Settlement, the Primary Tenant pays the other debt and the whole Charge
    after closure. Staff record a Refund of 3,000 as a draft with no effect; Staff cannot confirm
    it; the approver's confirm reverses the Payment allocation, writes one linked REDUCTION of
    3,000, re-posts the unreleased 5,000 to the Charge, recognizes 3,000 as the Primary Tenant's
    Credit named by a release row that links the Charge correction (no Adjustment), and refunds it
    with the draft's method and note; every record is a linked effect in order; an exact repeat
    replays. The Charge stays fully paid at its new amount, the Settlement row is unchanged and the
    ledger reconciles."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case)
    allocation = pay_charge(case, 8_000)
    payment = one(url, "SELECT payment_id FROM app.payment_allocations WHERE id=%s", allocation)[0]
    before = settlement_row(url, case["settlement"])
    draft = record(case, command(case, 3_000))
    assert (state(url, draft), charge_corrections(url, case["charge"])) == ("PENDING", 0)
    assert one(
        url,
        "SELECT payload->>'variant',payload->>'target_kind',payload->'refund'->>'invoice_id',"
        "payload->'released_sources' FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == (
        "REFUND",
        "LATE_PAYMENT_CHARGE",
        str(case["rent"]),
        [
            {
                "kind": "PAYMENT_ALLOCATION",
                "id": str(allocation),
                "payment_id": str(payment),
                "credit_id": None,
                "recipient_customer_id": str(case["tenant"]),
                "payer_customer_id": str(case["tenant"]),
                "released_usd_cents": 3_000,
            }
        ],
    )
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_late_charge_refund(
            case["prop"], draft, actor=preparer(case["human"], case["prop"])
        )
    result = confirm(case, draft)
    corrected = charge_correction_of(result)
    assert (
        corrected["correction_kind"],
        corrected["amount_usd_cents"],
        corrected["previous_obligation_usd_cents"],
        corrected["resulting_obligation_usd_cents"],
        corrected["reason"],
        corrected["authorization_reference"],
    ) == ("REDUCTION", 3_000, 8_000, 5_000, REASON, "financial.approve")
    [released] = released_of(result)
    assert (released["source_kind"], released["reversed_payment_allocation_id"]) == (
        "PAYMENT_ALLOCATION",
        str(allocation),
    )
    assert released["released_usd_cents"] == 3_000
    credit, repost = released["customer_credit_id"], released["replacement_payment_allocation_id"]
    assert one(
        url,
        "SELECT invoice_adjustment_id,late_payment_charge_correction_id::text,reason "
        "FROM app.invoice_credit_excess_releases WHERE customer_credit_id=%s",
        credit,
    ) == (None, corrected["id"], CHARGE_REASON)
    assert one(
        url,
        "SELECT customer_id,recognized_usd_cents,customer_authorization_reference,reason "
        "FROM app.customer_credits WHERE id=%s",
        credit,
    ) == (
        case["tenant"],
        3_000,
        f"late-payment-charge-correction:{corrected['id']}",
        CHARGE_REASON,
    )
    assert one(
        url,
        "SELECT target_kind,late_payment_charge_id,amount_usd_cents,between_invoice_basis "
        "FROM app.payment_allocations WHERE id=%s",
        repost,
    ) == ("LATE_PAYMENT_CHARGE", case["charge"], 5_000, "DIRECT_LATE_PAYMENT_CHARGE")
    # The generic audit of the re-post carries the release reason.
    assert one(
        url,
        "SELECT reason FROM app.audit_events WHERE action='payment_allocation.posted' "
        "AND entity_id=%s",
        repost,
    ) == (CHARGE_REASON,)
    [refund] = refunds_of(result)
    assert (
        refund["amount_usd_cents"],
        refund["recipient_customer_id"],
        refund["source_customer_credit_id"],
        refund["refund_method_id"],
        refund["reference_note"],
        refund["processed_by"],
    ) == (3_000, str(case["tenant"]), credit, str(case["cash"]), NOTE, str(case["person"]))
    correction = cast(dict[str, Any], result["settlement_correction"])["id"]
    assert effects(url, correction) == [
        "payment_allocation_reversal_id",
        "late_payment_charge_correction_id",
        "payment_allocation_id",
        "refund_id",
    ]
    assert one(
        url,
        "SELECT count(*) FROM app.audit_events WHERE correlation_id=%s AND action IN "
        "('late_payment.charge_corrected','final_settlement.correction.confirmed')",
        correction,
    ) == (2,)
    assert confirm(case, draft) == result
    assert (charge_amount(url, case["charge"]), unpaid(url, case["charge"])) == (5_000, 0)
    assert available(url, credit) == 0
    assert settlement_row(url, case["settlement"]) == before
    assert {credit, refund["id"]} <= ledger_event_ids(url, case["tenant"])


def test_released_credit_first_pays_its_customer_s_other_debt_and_only_the_rest_is_refunded(
    migrated_database_url: str,
) -> None:
    """Q-42 answer 2: the Primary Tenant still owes the 1,500 key card. A Refund of 3,000 whose plan
    leaves that debt open is refused and writes nothing; with a Credit step of the released value
    to the key card line the correction pays it first and refunds only the 1,500 left. The Signer's
    debt, which no step names, stays open."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case, key_card=False)
    allocation = pay_charge(case, 8_000)
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as debt_first:
        record(case, command(case, 3_000))
    assert cause(debt_first) == ("55000", CREDIT_FIRST)
    assert drafts(url) == count
    step = SettlementCreditStep(allocation, LINE, case["tenant_line"], 1_500)
    result = confirm(case, record(case, command(case, 3_000, steps=(step,))))
    [application] = cast(list[dict[str, Any]], result["credit_applications"])
    [released] = released_of(result)
    assert (application["customer_credit_id"], application["amount_usd_cents"]) == (
        released["customer_credit_id"],
        1_500,
    )
    [refund] = refunds_of(result)
    assert (refund["amount_usd_cents"], refund["recipient_customer_id"]) == (
        1_500,
        str(case["tenant"]),
    )
    assert outstanding(url, case["tenant_line"]) == 0
    assert outstanding(url, case["signer_line"]) == 600
    assert available(url, released["customer_credit_id"]) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["tenant"])
        assert_reconciled(connection, case["co_signer"])


def test_a_third_party_payer_s_released_value_goes_to_the_charge_s_customer(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014 (owner answer to Q-2026-10-07-38): a third party identified for the Lease paid
    the Charge. The released value becomes the Primary Tenant's Credit and is refunded to the
    Primary Tenant, not the payer; the payer's ledger does not show the Refund; the rest stays
    allocated from the payer's Payment; the one-call reversal of that Credit back onto the payer's
    Payment is refused (8g)."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case)
    payer = uuid4()
    pay_charge(case, 8_000, payer=payer)
    result = confirm(case, record(case, command(case, 2_000)))
    [released] = released_of(result)
    credit = released["customer_credit_id"]
    assert one(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit) == (
        case["tenant"],
    )
    assert one(
        url,
        "SELECT payment.payer_customer_id,allocation.amount_usd_cents,"
        "allocation.between_invoice_basis "
        "FROM app.payment_allocations allocation JOIN app.payments payment "
        "ON payment.id=allocation.payment_id WHERE allocation.id=%s",
        released["replacement_payment_allocation_id"],
    ) == (payer, 6_000, "THIRD_PARTY_DESIGNATED")
    [refund] = refunds_of(result)
    assert (refund["amount_usd_cents"], refund["recipient_customer_id"]) == (
        2_000,
        str(case["tenant"]),
    )
    assert {credit, refund["id"]} <= ledger_event_ids(url, case["tenant"])
    assert refund["id"] not in ledger_event_ids(url, payer)
    with pytest.raises(CreditConflictError) as refused:
        credits().reverse(
            case["prop"],
            UUID(credit),
            ReverseCreditCommand(uuid4(), "Return the value to the payer"),
            actor=credit_actor(case["human"], case["prop"], "credits.reverse"),
        )
    assert cause(refused)[0] == "P4904"


def test_credit_value_returns_to_its_credit_and_the_whole_charge_is_then_reversed(
    migrated_database_url: str,
) -> None:
    """A Payment pays 3,000 of the Charge, then the Primary Tenant's own Credit pays 5,000 (newer).
    A Refund of 4,000 releases only the newest source: 4,000 of the Credit application go back to
    that Credit (no new Credit), its 1,000 rest is re-posted as an ordinary Credit application, and
    the Refund comes from that Credit. A second Refund of the whole 4,000 left is the
    CHARGE_REVERSAL: it releases the re-posted Credit application first, then the older Payment
    allocation, newest first across both kinds. After it the Charge is terminal: a further
    correction is refused."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case)
    allocation = pay_charge(case, 3_000)
    credit, application = apply_tenant_credit(case, 5_000)
    assert unpaid(url, case["charge"]) == 0
    first = confirm(case, record(case, command(case, 4_000)))
    [released] = released_of(first)
    assert (
        released["source_kind"],
        released["reversed_credit_application_id"],
        released["customer_credit_id"],
        released["released_usd_cents"],
    ) == ("CREDIT_APPLICATION", str(application), str(credit), 4_000)
    rest = released["replacement_credit_application_id"]
    assert one(
        url,
        "SELECT target_kind,late_payment_charge_id,amount_usd_cents,final_settlement_id "
        "FROM app.customer_credit_applications WHERE id=%s",
        rest,
    ) == ("LATE_PAYMENT_CHARGE", case["charge"], 1_000, None)
    assert one(
        url,
        "SELECT reason FROM app.audit_events WHERE action='credit.applied' AND entity_id=%s",
        rest,
    ) == (CHARGE_REASON,)
    [refund] = refunds_of(first)
    assert (refund["source_customer_credit_id"], refund["amount_usd_cents"]) == (str(credit), 4_000)
    assert one(
        url,
        "SELECT count(*) FROM app.customer_credits WHERE customer_id=%s",
        case["tenant"],
    ) == (1,)
    assert (charge_amount(url, case["charge"]), unpaid(url, case["charge"])) == (4_000, 0)
    second = confirm(case, record(case, command(case, 4_000)))
    assert (
        charge_correction_of(second)["correction_kind"],
        charge_correction_of(second)["resulting_obligation_usd_cents"],
    ) == ("CHARGE_REVERSAL", 0)
    assert [
        (source["source_kind"], source["released_usd_cents"]) for source in released_of(second)
    ] == [("CREDIT_APPLICATION", 1_000), ("PAYMENT_ALLOCATION", 3_000)]
    assert released_of(second)[0]["reversed_credit_application_id"] == rest
    assert released_of(second)[1]["reversed_payment_allocation_id"] == str(allocation)
    assert all(
        source["replacement_payment_allocation_id"] is None
        and source["replacement_credit_application_id"] is None
        for source in released_of(second)
    )
    assert sorted(item["amount_usd_cents"] for item in refunds_of(second)) == [1_000, 3_000]
    with pytest.raises(FinalSettlementConflictError) as terminal:
        record(case, command(case, 1))
    assert cause(terminal) == ("55000", NOT_OPEN)
    assert (charge_amount(url, case["charge"]), charge_corrections(url, case["charge"])) == (0, 2)
    assert available(url, credit) == 0
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["tenant"])


def test_a_settlement_credit_application_on_the_charge_is_released_only_through_the_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1: the Settlement applied the Primary Tenant's Credit (1,500) to the Charge at
    closure, and the Primary Tenant pays the Rent and the Charge's 6,500 after closure. A Refund of
    7,000 releases newest first: the whole Payment allocation, then 500 of the Settlement Credit
    application, whose reversal passes the 8e-2 refusal only because it is linked to the
    correction. Its 1,000 rest is re-posted as an ordinary Credit application whose one-call
    reversal stays refused (the 10c-1b remainder refusal); the 500 go back to that Credit, and both
    releases are refunded to the Primary Tenant."""
    url = migrated_database_url
    case = credit_settled_case(url)
    settlement_application = one(
        url,
        "SELECT id FROM app.customer_credit_applications "
        "WHERE late_payment_charge_id=%s AND final_settlement_id IS NOT NULL",
        case["charge"],
    )[0]
    pay_other_debt(case, key_card=False)
    allocation = pay_charge(case, 6_500)
    result = confirm(case, record(case, command(case, 7_000)))
    first, second = released_of(result)
    assert (first["source_kind"], first["reversed_payment_allocation_id"]) == (
        "PAYMENT_ALLOCATION",
        str(allocation),
    )
    assert first["released_usd_cents"] == 6_500
    assert first["replacement_payment_allocation_id"] is None
    assert (
        second["source_kind"],
        second["reversed_credit_application_id"],
        second["customer_credit_id"],
        second["released_usd_cents"],
    ) == ("CREDIT_APPLICATION", str(settlement_application), str(case["tenant_credit"]), 500)
    rest = second["replacement_credit_application_id"]
    assert one(
        url,
        "SELECT amount_usd_cents,final_settlement_id,authorization_reference "
        "FROM app.customer_credit_applications WHERE id=%s",
        rest,
    ) == (1_000, None, "credits.apply")
    assert sorted(item["amount_usd_cents"] for item in refunds_of(result)) == [500, 6_500]
    assert (charge_amount(url, case["charge"]), unpaid(url, case["charge"])) == (1_000, 0)
    assert available(url, case["tenant_credit"]) == 0
    with pytest.raises(CreditConflictError) as rest_refused:
        credits().reverse_application(
            case["prop"],
            UUID(rest),
            ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
            actor=credit_actor(case["human"], case["prop"], "credits.applications.reverse"),
        )
    assert cause(rest_refused) == ("P5S01", REVERSAL_REFUSED)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["tenant"])


def test_the_refund_is_refused_for_unpaid_too_large_deposit_paid_or_other_lease_charges(
    migrated_database_url: str,
) -> None:
    """Refused at record and nothing written: a Refund of an unpaid Charge (that is a
    CHARGE_REDUCTION), a Refund within the unpaid rest of a partly paid Charge, more than the
    Charge, an inactive Refund method, a Charge of another Lease (P0002) and, on a really closed
    Settlement whose Pet Deposit paid the Charge, a Deposit-paid Charge whose plan leaves the
    returned Deposit money unused (since sub-slice 10c-3b-2).
    A draft whose Charge changes (another Payment) is stale and stays pending, and it first waits
    for the Lease row or the Charge row another session holds."""
    url = migrated_database_url
    case = settled_case(url)
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as unpaid_only:
        record(case, command(case, 1))
    assert cause(unpaid_only) == ("55000", NOTHING_RELEASED)
    pay_other_debt(case)
    pay_charge(case, 3_000)
    with pytest.raises(FinalSettlementConflictError) as within_unpaid:
        record(case, command(case, 5_000))
    assert cause(within_unpaid) == ("55000", NOTHING_RELEASED)
    with pytest.raises(FinalSettlementConflictError) as too_much:
        record(case, command(case, 8_001))
    assert cause(too_much) == ("55000", "The Refund correction exceeds the Late-payment Charge")
    with pytest.raises(FinalSettlementConflictError) as no_method:
        record(case, command(case, 5_001, refund_method_id=uuid4()))
    assert cause(no_method) == ("55000", "Refund Method is not active")
    other = closed_overdue_case(url)
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        record(case, command(case, 5_001, late_payment_charge_id=other["charge"]))
    assert cause(elsewhere) == ("P0002", NOT_OURS)
    assert drafts(url) == count
    stale = record(case, command(case, 5_001))
    pay_charge(case, 1_000)
    lease = case["lease"]
    for table, row in (("leases", lease), ("late_payment_charges", case["charge"])):
        with psycopg.connect(url) as holding:
            holding.execute(f"SELECT 1 FROM app.{table} WHERE id=%s FOR UPDATE", (row,))
            with (
                pytest.raises(psycopg.errors.LockNotAvailable),
                psycopg.connect(make_conninfo(url, connect_timeout=10)) as waiting,
            ):
                waiting.execute("SET lock_timeout='1s'")
                waiting.execute(
                    f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
                    (case["prop"], case["person"], stale),
                )
            holding.rollback()
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, stale)
    assert (state(url, stale), charge_corrections(url, case["charge"])) == ("PENDING", 0)
    deposit_case = {**two_signer_case(url, overdue_rent=True), "url": url}
    confirm_settlement(
        deposit_case,
        record_settlement(
            deposit_case,
            (
                SettlementCreditStep(
                    deposit_case["credit"], LINE, deposit_case["signer_line"], 400
                ),
                SettlementDepositStep(
                    PET_REST,
                    deposit_case["pet"],
                    SettlementTargetKind.LATE_PAYMENT_CHARGE,
                    deposit_case["charge"],
                    8_000,
                ),
                SettlementDepositStep(
                    PET_REST, deposit_case["pet"], LINE, deposit_case["rent_line"], 12_000
                ),
            ),
            pet_remainder=STAFF,
        ),
    )
    count = drafts(url)
    with pytest.raises(FinalSettlementConflictError) as deposit_paid:
        record(deposit_case, command(deposit_case, 1_000))
    # Sub-slice 10c-3b-2 releases the Deposit application, so the Pet Deposit holds the money again
    # and a plan that leaves it unused is refused (BR-SETTLE-008; docs/010).
    assert cause(deposit_paid) == (
        "55000",
        "Every remaining Deposit balance must be applied or refunded",
    )
    assert drafts(url) == count
    assert charge_corrections(url, deposit_case["charge"]) == 0


def test_the_late_charge_refund_guards_and_the_two_refund_confirms_take_only_their_own_drafts(
    migrated_database_url: str,
) -> None:
    """The database guards: malformed input 22023; the recorder takes only
    final_settlements.prepare and the confirm only financial.approve (42501); a reused key P5205
    and an exact repeat replays; a service identity that is not a person cannot confirm (P4506);
    the confirm runs only at READ COMMITTED (55000). The Invoice-line REFUND confirm refuses a
    Charge draft and the Charge confirm an Invoice-line REFUND draft (not found), pending and, on
    the replay path, confirmed. Nothing of a refused call is written."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case)
    pay_charge(case, 8_000)
    prop, human = case["prop"], case["human"]
    count = drafts(url)
    good = command(case, 1_000).refund()
    for malformed in (
        {**good, "surprise": True},
        {"late_payment_charge_id": str(case["charge"])},
        {**good, "late_payment_charge_id": "not-a-uuid"},
        {**good, "invoice_id": str(case["rent"])},
        {**good, "amount_usd_cents": 0},
        {**good, "amount_usd_cents": "500"},
        {**good, "amount_usd_cents": 9_000_000_000_000_001},
        {**good, "refund_method_id": None},
        {**good, "reference_note": " padded"},
        {**good, "plan": []},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    for authorization in ("financial.approve", "refunds.create", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    assert drafts(url) == count
    reused = command(case, 1_000)
    draft = record(case, reused)
    assert record(case, reused) == draft
    # Review round 1: the lock function itself takes this draft's Charge FOR UPDATE, so a key-share
    # lock of the Charge waits (the Charge pass takes the Lease's other Charges FOR NO KEY UPDATE,
    # which a key-share lock does not wait for), and the source Invoice FOR UPDATE too.
    with psycopg.connect(url) as holding:
        holding.execute("SELECT app.lock_settlement_correction_plan(%s)", (draft,))
        for table, row in (("late_payment_charges", case["charge"]), ("invoices", case["rent"])):
            with pytest.raises(psycopg.errors.LockNotAvailable), psycopg.connect(url) as probe:
                probe.execute(f"SELECT 1 FROM app.{table} WHERE id=%s FOR KEY SHARE NOWAIT", (row,))
        holding.rollback()
    with pytest.raises(FinalSettlementKeyReused):
        record(case, replace(reused, amount_usd_cents=900))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (prop, case["person"], draft),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_late_charge_refund(prop, draft, actor=approving(machine, prop))
    assert cause(not_a_person)[0] == "P4506"
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'financial.approve')",
            (prop, case["person"], draft),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A post-settlement correction is confirmed at READ COMMITTED",
    )
    with pytest.raises(FinalSettlementNotFoundError) as line_confirm:
        corrections().confirm_refund(prop, draft, actor=approving(case["person"], prop))
    assert cause(line_confirm) == ("P0002", NOT_FOUND)
    line_draft = UUID(
        str(
            corrections().record_refund(
                prop,
                RecordRefundCorrectionCommand(
                    uuid4(),
                    case["settlement"],
                    case["key_card"],
                    case["tenant_line"],
                    500,
                    case["cash"],
                    NOTE,
                    REASON,
                ),
                actor=preparer(human, prop),
            )["draft_id"]
        )
    )
    with pytest.raises(FinalSettlementNotFoundError) as charge_confirm:
        confirm(case, line_draft)
    assert cause(charge_confirm) == ("P0002", NOT_FOUND)
    assert (state(url, draft), state(url, line_draft), charge_corrections(url, case["charge"])) == (
        "PENDING",
        "PENDING",
        0,
    )
    result = confirm(case, draft)
    assert charge_correction_of(result)["amount_usd_cents"] == 1_000
    # The replay path keeps the two forms apart too.
    with pytest.raises(FinalSettlementNotFoundError) as line_replay:
        corrections().confirm_refund(prop, draft, actor=approving(case["person"], prop))
    assert cause(line_replay) == ("P0002", NOT_FOUND)
    line_result = corrections().confirm_refund(
        prop, line_draft, actor=approving(case["person"], prop)
    )
    assert cast(dict[str, Any], line_result["invoice_adjustment"])["amount_usd_cents"] == 500
    with pytest.raises(FinalSettlementNotFoundError) as charge_replay:
        confirm(case, line_draft)
    assert cause(charge_replay) == ("P0002", NOT_FOUND)
    assert confirm(case, draft) == result
    assert charge_corrections(url, case["charge"]) == 1
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["tenant"])


def test_the_relaxed_release_record_keeps_exactly_one_link_and_its_rules(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-09-66: a release row names exactly one of an Adjustment or a
    Late-payment Charge correction, each with its own reason; a Charge release must match a
    reversed source on that Charge with the same reason and at most what it applied; the table
    stays append-only and no application role may write it (the runtime and financial roles keep
    their read grant). Every existing Adjustment release (the 8c fixture's) is unchanged."""
    url = migrated_database_url
    case = settled_case(url)
    pay_other_debt(case)
    pay_charge(case, 8_000)
    result = confirm(case, record(case, command(case, 3_000)))
    corrected = charge_correction_of(result)["id"]
    [released] = released_of(result)
    adjustment = one(
        url,
        "SELECT release.invoice_adjustment_id FROM app.invoice_credit_excess_releases release "
        "JOIN app.customer_credits credit ON credit.id=release.customer_credit_id "
        "WHERE credit.customer_id=%s",
        case["co_signer"],
    )[0]
    assert adjustment is not None
    insert = (
        "INSERT INTO app.invoice_credit_excess_releases(id,invoice_adjustment_id,"
        "late_payment_charge_correction_id,source_kind,reversed_payment_allocation_id,"
        "customer_credit_id,released_usd_cents,reason,actor_id,created_at) "
        "VALUES (%s,%s,%s,'PAYMENT_ALLOCATION',%s,%s,%s,%s,%s,clock_timestamp())"
    )
    reversed_ = released["reversed_payment_allocation_id"]
    for link_adjustment, link_charge, amount, reason, constraint, message in (
        (adjustment, corrected, 1, CHARGE_REASON, "invoice_credit_excess_release_one_link", None),
        (None, None, 1, CHARGE_REASON, None, MISMATCH),
        (None, corrected, 1, "Invoice adjustment credit excess", None, MISMATCH),
        (None, corrected, 8_001, CHARGE_REASON, None, MISMATCH),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                insert,
                (
                    uuid4(),
                    link_adjustment,
                    link_charge,
                    reversed_,
                    uuid4(),
                    amount,
                    reason,
                    case["human"],
                ),
            )
        assert refused.value.sqlstate == "23514"
        if constraint is not None:
            assert refused.value.diag.constraint_name == constraint
        if message is not None:
            assert refused.value.diag.message_primary == message
    # Review round 1: the two checks themselves. The release validator refuses every other bad row
    # first, so the checks are shown by their exact definitions.
    with psycopg.connect(url) as connection:
        checks = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
                "WHERE conrelid='app.invoice_credit_excess_releases'::regclass AND contype='c'"
            ).fetchall()
        }
    assert checks["invoice_credit_excess_release_one_link"] == (
        "CHECK ((num_nonnulls(invoice_adjustment_id, late_payment_charge_correction_id) = 1))"
    )
    assert checks["invoice_credit_excess_releases_reason_check"] == (
        "CHECK ((((invoice_adjustment_id IS NOT NULL) AND "
        "(reason = 'Invoice adjustment credit excess'::text)) OR "
        "((late_payment_charge_correction_id IS NOT NULL) AND "
        f"(reason = '{CHARGE_REASON}'::text))))"
    )
    for statement in (
        "UPDATE app.invoice_credit_excess_releases SET released_usd_cents=1 "
        "WHERE late_payment_charge_correction_id=%s",
        "DELETE FROM app.invoice_credit_excess_releases WHERE late_payment_charge_correction_id=%s",
    ):
        with pytest.raises(psycopg.Error) as mutation, psycopg.connect(url) as connection:
            connection.execute(statement, (corrected,))
        assert (mutation.value.sqlstate, mutation.value.diag.message_primary) == (
            "55000",
            "Financial event history is append-only",
        )
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap"):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,'app.invoice_credit_excess_releases',%s)",
                    (role, privilege),
                ).fetchone() == (False,), (role, privilege)
    assert one(
        url,
        "SELECT count(*) FROM app.invoice_credit_excess_releases WHERE NOT ("
        "(invoice_adjustment_id IS NOT NULL AND reason='Invoice adjustment credit excess') "
        "OR (late_payment_charge_correction_id IS NOT NULL AND reason=%s))",
        CHARGE_REASON,
    ) == (0,)


def test_late_charge_refund_functions_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Only the financial role records and confirms; no role calls the internal functions; no new
    function has a time limit (BR-SETTLE-013); the migration adds only its functions, changes only
    the nine patched functions (each new body exactly the old one with its replacements, privileges,
    owner, SECURITY DEFINER and settings kept) and, on the release table, only the new link, its
    index and the two checks; it is forward-only."""
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
    # BR-SETTLE-013, no time limit: no age check and no interval other than the chronology step.
    for function in (RECORD, CONFIRM, *INTERNAL):
        source = str(
            one(url, "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure", function)[
                0
            ]
        )
        assert "age(" not in source, function
        assert set(re.findall(r"interval '([^']*)'", source)) <= {"1 microsecond"}, function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261117_113")
    assert revision is not None and revision.down_revision == "20261116_112"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def acl(database: str) -> object:
        return one(
            database,
            "SELECT relacl::text FROM pg_catalog.pg_class "
            "WHERE oid='app.invoice_credit_excess_releases'::regclass",
        )[0]

    def catalog(
        database: str,
    ) -> tuple[dict[str, tuple[object, ...]], set[str], set[str], dict[str, str], set[str]]:
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
            constraints = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT conname,pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint "
                    "WHERE conrelid='app.invoice_credit_excess_releases'::regclass"
                ).fetchall()
            }
            indexes = {
                str(row[0])
                for row in connection.execute(
                    "SELECT indexrelid::regclass::text FROM pg_catalog.pg_index "
                    "WHERE indrelid='app.invoice_credit_excess_releases'::regclass"
                ).fetchall()
            }
        return functions, relations, triggers, constraints, indexes

    with _temporary_migration_database("settlement_late_charge_refund") as temporary:
        alembic_command.upgrade(config, "20261116_112")
        before_functions, before_relations, before_triggers, before_checks, before_indexes = (
            catalog(temporary)
        )
        before_acl = acl(temporary)
        alembic_command.upgrade(config, "20261117_113")
        after_functions, after_relations, after_triggers, after_checks, after_indexes = catalog(
            temporary
        )
        after_acl = acl(temporary)
    # No grant changes: the runtime and financial roles keep their read grant, no role writes.
    assert after_acl == before_acl
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) - set(before_functions) == {RECORD, CONFIRM, *INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED)
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
        assert after_functions[function][1:] == before_functions[function][1:], function
    added = set(after_checks) - set(before_checks)
    assert added == {
        "invoice_credit_excess_release_one_link",
        "invoice_credit_excess_release_charge_correction_fkey",
    }
    assert set(before_checks) <= set(after_checks)
    assert {name for name in before_checks if after_checks[name] != before_checks[name]} == {
        "invoice_credit_excess_releases_reason_check"
    }
    assert after_indexes - before_indexes == {
        "app.invoice_credit_excess_release_charge_correction_idx"
    }
