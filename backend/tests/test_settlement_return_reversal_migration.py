"""Post-settlement correction: a return recorded by mistake (V1-056 sub-slice 10e-3).

Owner answer (a) to Q-2026-10-08-57 and the Q-2026-10-11-78 rule: a RETURN_REVERSAL correction
names one return that an earlier REFUND_RETURN correction of the same closed Final Settlement
recorded by mistake. It undoes the uses of the returned Refund's own Credit or Deposit by that
correction and by the HELD_VALUE_REFUND corrections naming it (the debt comes back and stays with
its Customers, BR-SETTLE-016), charges each of their Refunds from that source back to the person
who received it, then reverses the return. Staff prepare it under final_settlements.prepare; only
financial.approve confirms it (BR-SETTLE-013, BR-AUTH-010).

Sub-slice 10e-3b: a Deposit Refund paid to an agreed Signer is charged back to that Signer (owner
answer (a) to Q-2026-10-12-94); when the uses are more than the returned amount, only the returned
amount is charged back, the oldest Refund first, and every application stays (owner answer (a) to
Q-2026-10-12-95); when the Refunds paid out less than the returned amount, the reversal waits for
the owner (Q-2026-10-12-96).
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

from property_rental.final_settlement import (
    FinalSettlementAuthorizationError,
    FinalSettlementConflictError,
    FinalSettlementKeyReused,
    FinalSettlementNotFoundError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.settlement_correction import RecordReturnReversalCorrectionCommand
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF, two_signer_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, preparer
from test_invoice_migration import register_billing_service_principal
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections, state
from test_settlement_held_value_refund_migration import (
    DEPOSIT_EMPTY,
    NOTHING_LEFT,
    confirm_held,
    deposit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_pet_payback_migration import forfeit, forfeited, path, pet_case
from test_settlement_refund_correction_migration import (
    apply_credit,
    reverse_application,
    unpaid_charge,
)
from test_settlement_refund_return_migration import (
    BEGIN,
    ONLY_THROUGH,
    REVERSAL_ROW,
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
)
from test_settlement_returned_payment_migration import command as returned_command
from test_settlement_returned_payment_migration import confirm as confirm_returned
from test_settlement_returned_payment_migration import receipt_payment
from test_settlement_returned_payment_migration import record as record_returned

REVISION = "20261129_125"
REASON = "The return was recorded by mistake"
EVIDENCE = "Bank statement 2026-10 shows the money never came back"
RECORD = "app.record_settlement_return_reversal_draft(uuid,uuid,uuid,uuid,jsonb,text,text)"
CONFIRM = "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)"
INTERNAL = (
    "app.settlement_return_reversal_input(jsonb)",
    "app.settlement_return_reversal_users(uuid)",
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
    "app.write_correction_named_deposit_application_reversals("
    "uuid,uuid,text,uuid[],timestamp with time zone)",
    "app.settlement_return_reversal_allowed(app.refund_corrections)",
    "app.settlement_return_reversal_refund(uuid,uuid)",
    "app.settlement_return_reversal_result(uuid)",
)
PATCHED = {
    "app.validate_general_refund_correction()",
    "app.refund_recovery_allowed(app.refund_corrections)",
    "app.write_payment_return_recoveries("
    "uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)",
    "app.lock_settlement_correction_plan(uuid)",
    "app.settlement_held_deposit_value(uuid,uuid)",
    "app.settlement_held_credit_value(uuid,uuid,uuid)",
}
NOT_FOUND = "The returned-Refund correction to reverse was not found"
ALREADY = "The return of this correction is already reversed"
OWN_RETURN = "A Refund paid from the returned value has its own return; reverse that return first"
NOT_AVAILABLE = "The returned value is no longer available; undo its other use first"
WAITING = "A return reversal draft of this correction is already waiting"
PAYBACK_REVISION = "20261130_126"
PAYBACK_INTERNAL = (
    "app.settlement_return_reversal_recovery_amount(app.refund_corrections)",
    "app.refund_recovery_source_reference(uuid,timestamp with time zone)",
)
PAYBACK_PATCHED = {
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
    "app.settlement_return_reversal_refund(uuid,uuid)",
    "app.validate_general_refund_correction()",
    "app.write_payment_return_recoveries("
    "uuid,uuid,uuid,uuid,uuid,jsonb,text,text,timestamp with time zone,jsonb)",
    "app.refund_recovery_allowed(app.refund_corrections)",
}
STALE_RECOVERY = "The Refund to recover changed; the draft is stale"
PAID_DEBT = (
    "The returned money also paid debt beyond what its Refunds paid out; "
    "reversing it waits for the owner"
)
RECOVERED_ONLY = "A Refund is recovered by a charge only inside the return of its Payment"
REVERSE_RETURN = (
    "INSERT INTO app.refund_corrections(id,refund_id,correction_kind,reverses_correction_id,"
    "source_balance_effect_usd_cents,source_balance_effect_original_minor,"
    "previous_net_refund_usd_cents,resulting_net_refund_usd_cents,reason,evidence_reference,"
    "occurred_at,actor_id,authorization_reference) "
    "SELECT %s,original.refund_id,'CORRECTION_REVERSAL',original.id,"
    "-original.source_balance_effect_usd_cents,-original.source_balance_effect_usd_cents,"
    "app.refund_net_value_at(original.refund_id,'infinity'),"
    "app.refund_net_value_at(original.refund_id,'infinity')"
    "+original.source_balance_effect_usd_cents,"
    "%s,%s,clock_timestamp()+interval '1 second',%s,'refunds.corrections.reverse' "
    "FROM app.refund_corrections original WHERE original.id=%s"
)
RECOVER = (
    "SELECT app.write_payment_return_recoveries(%s,%s,%s,%s,NULL,%s,%s,%s,clock_timestamp(),%s)"
)


def reversal_command(
    case: dict[str, Any], earlier: object, **changes: Any
) -> RecordReturnReversalCorrectionCommand:
    return replace(
        RecordReturnReversalCorrectionCommand(
            uuid4(), case["settlement"], UUID(str(earlier)), REASON, EVIDENCE
        ),
        **changes,
    )


def record_reversal(case: dict[str, Any], command: RecordReturnReversalCorrectionCommand) -> UUID:
    found = corrections().record_return_reversal(
        case["prop"], command, actor=preparer(case["human"], case["prop"])
    )
    return UUID(str(found["draft_id"]))


def confirm_reversal(case: dict[str, Any], draft: UUID) -> dict[str, Any]:
    return corrections().confirm_return_reversal(
        case["prop"], draft, actor=approving(case["person"], case["prop"])
    )


def correction_of(result: dict[str, Any]) -> UUID:
    return UUID(str(result["settlement_correction"]["id"]))


def lease_of(case: dict[str, Any]) -> UUID:
    return UUID(
        str(
            one(
                case["url"],
                "SELECT lease_id FROM app.final_settlements WHERE id=%s",
                case["settlement"],
            )[0]
        )
    )


def charge_open(url: str, recovery: dict[str, Any]) -> int:
    """What is still owed on the recovery charge's Invoice line."""
    line = one(url, "SELECT id FROM app.invoice_lines WHERE invoice_id=%s", recovery["invoice_id"])
    return outstanding(url, line[0])


def draft_source(url: str, draft: UUID) -> dict[str, Any]:
    found = one(url, "SELECT payload->'source' FROM app.financial_drafts WHERE id=%s", draft)[0]
    assert isinstance(found, dict)
    return found


def test_a_mistaken_credit_return_is_reversed_and_its_new_refund_is_charged_back(
    migrated_database_url: str,
) -> None:
    """A correction's 2,000 Credit Refund is recorded as returned in full; the returned Credit
    pays the 1,500 charge the Customer owes and 500 is refunded again. Part of that 500 (200) is
    also recorded as returned: the earlier return is refused until that later return is reversed
    first. Then the reversal of the earlier return undoes the 1,500 Credit application (owed
    again), charges the 500 back to the Customer who received it (an EXTRA_CHARGE on the Lease)
    and reverses the return: the Refund's net value is 2,000 again and the Credit is empty. The
    draft shows each undo and each charge; the Settlement row is unchanged; a repeat replays; a
    second reversal is refused."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    first = confirm(
        case,
        record(
            case,
            return_command(
                case, refund, 2_000, SettlementCreditStep(credit, LINE, charge_line, 1_500)
            ),
        ),
    )
    earlier = correction_of(first)
    [again] = first["refunds"]
    assert (
        again["amount_usd_cents"],
        net(url, refund),
        available(url, credit),
        outstanding(url, charge_line),
    ) == (500, 0, 0, 0)
    later = return_only(case, again["id"], 200)
    with pytest.raises(FinalSettlementConflictError) as chained:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(chained) == ("55000", OWN_RETURN)
    undone_later = confirm_reversal(case, record_reversal(case, reversal_command(case, later)))
    assert (
        undone_later["credit_application_reversals"],
        undone_later["deposit_application_reversals"],
        undone_later["recoveries"],
        undone_later["return_reversal"]["amount_usd_cents"],
    ) == ([], [], [], 200)
    assert (net(url, again["id"]), available(url, credit)) == (500, 0)
    before = settlement_row(url, case["settlement"])
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    assert [item["amount_usd_cents"] for item in source["credit_applications"]] == [1_500]
    assert [
        (item["refund_id"], item["recipient_customer_id"], item["amount_usd_cents"], item["charge"])
        for item in source["recoveries"]
    ] == [(again["id"], str(customer), 500, "CLOSED_SETTLEMENT_LEASE")]
    result = confirm_reversal(case, draft)
    [undone] = result["credit_application_reversals"]
    assert (undone["customer_credit_id"], undone["invoice_id"], undone["amount_usd_cents"]) == (
        str(credit),
        str(charge_invoice),
        1_500,
    )
    [recovery] = result["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["lease_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (again["id"], str(customer), str(lease_of(case)), 500, "EXTRA_CHARGE")
    reversed_return = result["return_reversal"]
    assert (
        reversed_return["refund_id"],
        reversed_return["amount_usd_cents"],
        reversed_return["resulting_net_refund_usd_cents"],
        reversed_return["evidence_reference"],
    ) == (str(refund), 2_000, 2_000, EVIDENCE)
    assert (
        net(url, refund),
        net(url, again["id"]),
        available(url, credit),
        outstanding(url, charge_line),
        charge_open(url, recovery),
    ) == (2_000, 0, 0, 1_500, 500)
    assert settlement_row(url, case["settlement"]) == before
    assert confirm_reversal(case, draft) == result
    with pytest.raises(FinalSettlementConflictError) as twice:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(twice) == ("55000", ALREADY)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_mistaken_deposit_return_undoes_only_the_returned_deposit_s_uses(
    migrated_database_url: str,
) -> None:
    """The Settlement's 5,400 Pet Deposit Refund is recorded as returned with a new Refund: the
    Customer's own Credit pays 300 of a 1,500 charge, the Pet Deposit 1,200, and 4,200 is refunded
    from the Pet Deposit. The reversal undoes the 1,200 Pet Deposit application and charges the
    4,200 back to the Customer; the 300 paid from the Customer's other Credit was not paid from
    the returned value and stays. The Pet Deposit ends empty and the Refund's net value is 5,400
    again. A hand-built reversal row outside the correction's draft is refused."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    refund, pet, customer = pet_refund(case), case["pet"], case["customer"]
    _, charge_line = unpaid_charge(url, case, case["person"])
    first = confirm(
        case,
        record(
            case,
            return_command(
                case,
                refund,
                5_400,
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 1_200),
                settlement_refund(case, "pet", 4_200),
                pet_remainder=STAFF,
            ),
        ),
    )
    earlier = correction_of(first)
    [paid] = first["refunds"]
    [returned] = first["refund_corrections"]
    for reference in ("refunds.corrections.reverse", "financial.approve"):
        values = (uuid4(), case["person"], reference, returned["id"], refund)
        with pytest.raises(psycopg.Error) as alone, psycopg.connect(url) as connection:
            connection.execute(REVERSAL_ROW, values)
        assert (alone.value.sqlstate, alone.value.diag.message_primary) == (
            "23514",
            "A Final Settlement Refund is corrected only through a post-settlement correction",
        ), reference
    draft = record_reversal(case, reversal_command(case, earlier))
    # Review round 1: inside the draft's own correction, a reversal row that matches the draft
    # but comes before the undo is refused, because the Pet Deposit does not hold the returned
    # amount (the reversal branch reads every Deposit Refund's source by its Deposit).
    with pytest.raises(psycopg.Error) as early, psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
        assert found is not None
        row = uuid4()
        connection.execute(
            "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)",
            (found[0], row),
        )
        connection.execute(REVERSE_RETURN, (row, REASON, EVIDENCE, case["person"], returned["id"]))
    assert (early.value.sqlstate, early.value.diag.message_primary) == (
        "23514",
        "Returned Refund value is no longer available to reverse",
    )
    result = confirm_reversal(case, draft)
    assert result["credit_application_reversals"] == []
    [undone] = result["deposit_application_reversals"]
    assert (undone["deposit_id"], undone["amount_usd_cents"]) == (str(pet), 1_200)
    [recovery] = result["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (paid["id"], str(customer), 4_200, "EXTRA_CHARGE")
    assert (
        held(url, pet),
        net(url, refund),
        net(url, paid["id"]),
        outstanding(url, charge_line),
        available(url, case["new_credit"]),
        charge_open(url, recovery),
    ) == (0, 5_400, 0, 1_200, 0, 4_200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_mistaken_pay_back_return_into_a_kept_pet_deposit_is_reversed(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10c-2b-5 pay back: 15,000 of a 20,000 Pet Deposit was refunded while the Lease
    was signed; the forfeiture keeps the 5,000 held and the Settlement closes with 1,000 of Rent
    unpaid. After closure 3,000 is recorded as returned: as pay-back money it pays the 1,000 and
    2,000 is refunded. The reversal undoes the 1,000 Pet Deposit application (owed again), charges
    the 2,000 back and reverses the return: the Pet Deposit stays kept, empty, with no pay-back
    money, and the forfeiture is unchanged."""
    url = migrated_database_url
    case = pet_case(url, (("refund", 15_000),), debt=1_000)
    forfeit(case, "security")
    forfeit(case, "pet")
    confirm_settlement(case, record_settlement(case, ()))
    case["person"] = approver(url)
    first = confirm(
        case,
        record(
            case,
            return_command(
                case,
                case["review_refund"],
                3_000,
                SettlementDepositStep(PET_REST, case["pet"], LINE, case["rent"], 1_000),
                settlement_refund(case, "pet", 2_000),
                pet_remainder=STAFF,
            ),
        ),
    )
    [paid] = first["refunds"]
    assert (outstanding(url, case["rent"]), held(url, case["pet"])) == (0, 0)
    result = confirm_reversal(
        case, record_reversal(case, reversal_command(case, correction_of(first)))
    )
    [undone] = result["deposit_application_reversals"]
    assert (undone["deposit_id"], undone["amount_usd_cents"]) == (str(case["pet"]), 1_000)
    [recovery] = result["recoveries"]
    assert (recovery["refund_id"], recovery["customer_id"], recovery["amount_usd_cents"]) == (
        paid["id"],
        str(case["customer"]),
        2_000,
    )
    assert (
        outstanding(url, case["rent"]),
        held(url, case["pet"]),
        net(url, case["review_refund"]),
        charge_open(url, recovery),
    ) == (1_000, 0, 15_000, 2_000)
    assert (forfeited(case, "pet"), path(case, "pet")) == ([5_000], ("KEPT", 0))
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_held_value_refund_is_charged_back_and_an_agreed_signer_pays_back_their_refund(
    migrated_database_url: str,
) -> None:
    """Two Signers; the Settlement refunded the Pet Deposit's rest (17,900) to the second Signer
    with the written agreement of all Signers. 1,000 is recorded as returned (return only) and a
    HELD_VALUE_REFUND pays it to the Primary Tenant, the Deposit's own Customer; a later 500
    return is refunded again to the second Signer with the agreement. The reversal of the later
    return charges its 500 back to the second Signer, who received it, by an EXTRA_CHARGE on the
    Lease (owner answer (a) to Q-2026-10-12-94, sub-slice 10e-3b). The reversal of the first
    return charges its 1,000 back to the Primary Tenant and reverses it; nothing is then left for
    a held-value Refund naming it."""
    url = migrated_database_url
    case = {**two_signer_case(url), "url": url}
    agreement = "All Signers agreed in writing on 2026-10-12 that the Signer receives the Refund"
    pet, tenant, co_signer = case["pet"], case["tenant"], case["co_signer"]
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                SettlementCreditStep(case["credit"], LINE, case["signer_line"], 400),
                SettlementDepositStep(PET_REST, pet, LINE, case["tenant_line"], 1_500),
                SettlementDepositStep(PET_REST, pet, LINE, case["signer_line"], 600),
                settlement_refund(
                    case, "pet", 17_900, recipient_customer_id=co_signer, signer_agreement=agreement
                ),
            ),
            pet_remainder=STAFF,
        ),
    )
    case["person"] = approver(url)
    earlier = return_only(case, pet_refund(case), 1_000)
    held_result = confirm_held(
        case, record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    )
    [paid] = held_result["refunds"]
    assert (paid["recipient_customer_id"], held(url, pet)) == (str(tenant), 0)
    later = return_only(case, pet_refund(case), 500)
    to_signer = settlement_refund(
        case, "pet", 500, recipient_customer_id=co_signer, signer_agreement=agreement
    )
    [to_co_signer] = confirm_held(case, record_held(case, held_command(case, later, to_signer)))[
        "refunds"
    ]
    undone_later = confirm_reversal(case, record_reversal(case, reversal_command(case, later)))
    [signer_recovery] = undone_later["recoveries"]
    assert (
        signer_recovery["refund_id"],
        signer_recovery["customer_id"],
        signer_recovery["lease_id"],
        signer_recovery["amount_usd_cents"],
        signer_recovery["charge"],
    ) == (to_co_signer["id"], str(co_signer), str(lease_of(case)), 500, "EXTRA_CHARGE")
    assert (
        charge_open(url, signer_recovery),
        net(url, to_co_signer["id"]),
        held(url, pet),
    ) == (500, 0, 0)
    result = confirm_reversal(case, record_reversal(case, reversal_command(case, earlier)))
    [recovery] = result["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["lease_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (paid["id"], str(tenant), str(lease_of(case)), 1_000, "EXTRA_CHARGE")
    assert (held(url, pet), net(url, pet_refund(case)), deposit_left(url, earlier, pet)) == (
        0,
        17_900,
        0,
    )
    with pytest.raises(FinalSettlementConflictError) as nothing:
        record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 1_000)))
    assert cause(nothing) == ("55000", NOTHING_LEFT)
    for customer in (tenant, co_signer):
        with psycopg.connect(url) as connection:
            assert_reconciled(connection, customer)


def test_the_refusals_of_a_return_reversal(migrated_database_url: str) -> None:
    """A correction that is not a REFUND_RETURN of this Settlement is not found; a returned value
    another path used is refused until that use is undone; one draft of a return waits at a time;
    a reused draft identity is refused; Staff cannot confirm; a hand-built reversal row that
    differs from the draft is refused inside the draft's own correction; a draft whose source
    changed is stale and stays pending."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 800)
    refund_correction = one(
        url,
        "SELECT settlement_correction_id FROM app.settlement_correction_refund_details "
        "WHERE refund_id=%s",
        refund,
    )[0]
    for missing in (uuid4(), refund_correction):
        with pytest.raises(FinalSettlementNotFoundError) as unknown:
            record_reversal(case, reversal_command(case, missing))
        assert cause(unknown) == ("P0002", NOT_FOUND)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    application = apply_credit(case, credit, charge_invoice, charge_line, 500)
    with pytest.raises(FinalSettlementConflictError) as spent:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(spent) == ("55000", NOT_AVAILABLE)
    reverse_application(case, application)
    command = reversal_command(case, earlier)
    draft = record_reversal(case, command)
    assert record_reversal(case, command) == draft
    with pytest.raises(FinalSettlementConflictError) as waiting:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(waiting) == ("55000", WAITING)
    with pytest.raises(FinalSettlementKeyReused):
        record_reversal(case, replace(command, reason="Another reason"))
    with pytest.raises(FinalSettlementAuthorizationError):
        corrections().confirm_return_reversal(
            case["prop"], draft, actor=preparer(case["human"], case["prop"])
        )
    returned = draft_source(url, draft)["earlier"]["return_id"]
    for reference in ("refunds.corrections.reverse", "financial.approve"):
        values = (uuid4(), case["person"], reference, returned, refund)
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            found = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
            assert found is not None
            connection.execute(
                "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)",
                (found[0], values[0]),
            )
            connection.execute(REVERSAL_ROW, values)
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "23514",
            ONLY_THROUGH,
        ), reference
    # Review round 1 (security SF-1): inside the draft's own correction, a recovery of a Refund
    # the reversed return's correction did not pay (here the returned Refund itself) is refused.
    outside = Jsonb(
        [
            {
                "refund_id": str(refund),
                "amount_usd_cents": net(url, refund),
                "recipient_customer_id": str(case["customer"]),
                "lease_id": str(lease_of(case)),
                "closed_final_settlement_id": str(case["settlement"]),
                "reservation_outcome": False,
                "shared_deposit": False,
            }
        ]
    )
    with pytest.raises(psycopg.Error) as recovered, psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
        assert found is not None
        connection.execute(
            RECOVER,
            (
                case["prop"],
                case["person"],
                draft,
                found[0],
                outside,
                REASON,
                EVIDENCE,
                Jsonb({"variant": "RETURN_REVERSAL"}),
            ),
        )
    assert (recovered.value.sqlstate, recovered.value.diag.message_primary) == (
        "23514",
        ONLY_THROUGH,
    )
    apply_credit(case, credit, charge_invoice, charge_line, 100)
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm_reversal(case, draft)
    assert (state(url, draft), net(url, refund), available(url, credit)) == ("PENDING", 1_200, 700)


def test_the_database_guards_and_a_reversal_of_uses_beyond_the_return(
    migrated_database_url: str,
) -> None:
    """Review round 1: malformed input 22023; the recorder takes only final_settlements.prepare
    and the confirm only financial.approve (42501); a service identity that is not a person cannot
    confirm (P4506); the confirm runs only at READ COMMITTED (55000); a return of another closed
    Settlement is not found; no refusal writes anything. Q-2026-10-12-95: 1,000 of the Pet Deposit
    Refund came back return only, then 500 more with a new Refund, which refunds all 1,500 the Pet
    Deposit holds. The reversal of the 500 return charges back only the 500 (owner answer (a),
    sub-slice 10e-3b): the new Refund paid out the returned money first, its 1,000 rest stays paid
    and the Pet Deposit holds nothing, so a held-value Refund naming the first return is refused;
    a hand-built recovery of another share is refused inside the draft's own correction."""
    url = migrated_database_url
    case = refunded_case(url)
    prop, human = case["prop"], case["human"]
    earlier = return_only(case, case["refund"], 800)
    other = refunded_case(url)
    good = reversal_command(case, earlier).return_reversal()
    before = one(url, "SELECT count(*) FROM app.financial_drafts")
    for malformed in (
        {**good, "surprise": True},
        {key: item for key, item in good.items() if key != "evidence_reference"},
        {**good, "settlement_correction_id": "not-a-uuid"},
        {**good, "settlement_correction_id": str(UUID(int=0))},
        {**good, "evidence_reference": " padded"},
        {**good, "evidence_reference": "x" * 501},
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,'final_settlements.prepare')",
                (prop, human, uuid4(), case["settlement"], Jsonb(malformed), REASON),
            )
        assert refused.value.sqlstate == "22023", malformed
    for authorization in ("financial.approve", "refunds.correct", None):
        with pytest.raises(psycopg.Error) as recorder, psycopg.connect(url) as connection:
            connection.execute(
                f"SELECT {RECORD.split('(')[0]}(%s,%s,%s,%s,%s,%s,%s)",
                (prop, human, uuid4(), case["settlement"], Jsonb(good), REASON, authorization),
            )
        assert recorder.value.sqlstate == "42501", authorization
    with pytest.raises(FinalSettlementNotFoundError) as elsewhere:
        corrections().record_return_reversal(
            other["prop"],
            reversal_command(other, earlier),
            actor=preparer(other["human"], other["prop"]),
        )
    assert cause(elsewhere) == ("P0002", NOT_FOUND)
    assert one(url, "SELECT count(*) FROM app.financial_drafts") == before
    draft = record_reversal(case, reversal_command(case, earlier))
    with pytest.raises(psycopg.Error) as staff, psycopg.connect(url) as connection:
        connection.execute(
            f"SELECT {CONFIRM.split('(')[0]}(%s,%s,%s,'final_settlements.prepare')",
            (prop, case["person"], draft),
        )
    assert staff.value.sqlstate == "42501"
    with psycopg.connect(url) as connection:
        machine = register_billing_service_principal(connection, property_id=prop, created_by=human)
    with pytest.raises(FinalSettlementAuthorizationError) as not_a_person:
        corrections().confirm_return_reversal(prop, draft, actor=approving(machine, prop))
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
    assert (state(url, draft), net(url, case["refund"])) == ("PENDING", 1_200)
    pet = case["pet"]
    first_return = return_only(case, pet_refund(case), 1_000)
    settled_net = net(url, pet_refund(case))
    refund_all = settlement_refund(case, "pet", 1_500)
    mixed = confirm(case, record(case, return_command(case, pet_refund(case), 500, refund_all)))
    [paid] = mixed["refunds"]
    assert (paid["amount_usd_cents"], held(url, pet)) == (1_500, 0)
    shared = record_reversal(case, reversal_command(case, correction_of(mixed)))
    source = draft_source(url, shared)
    [planned] = source["recoveries"]
    assert (
        planned["refund_id"],
        planned["amount_usd_cents"],
        planned["net_usd_cents"],
        source["deposit_applications"],
        source["uses"],
    ) == (
        paid["id"],
        500,
        1_500,
        [],
        {"applied_usd_cents": 0, "refunded_usd_cents": 1_500, "returned_refunds": 0},
    )
    # Review round 1: the writer takes a share only inside a RETURN_REVERSAL; for any other
    # caller an entry whose amount is not the whole net is stale.
    with pytest.raises(psycopg.Error) as other_caller, psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], case["person"], shared)).fetchone()
        assert found is not None
        connection.execute(
            RECOVER,
            (
                case["prop"],
                case["person"],
                shared,
                found[0],
                Jsonb([planned]),
                REASON,
                EVIDENCE,
                Jsonb({"variant": "DEPOSIT_RECEIPT_CORRECTION"}),
            ),
        )
    assert (other_caller.value.sqlstate, other_caller.value.diag.message_primary) == (
        "P5S02",
        STALE_RECOVERY,
    )
    with pytest.raises(psycopg.Error) as other_share, psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], case["person"], shared)).fetchone()
        assert found is not None
        connection.execute(
            RECOVER,
            (
                case["prop"],
                case["person"],
                shared,
                found[0],
                Jsonb([{**planned, "amount_usd_cents": 400}]),
                REASON,
                EVIDENCE,
                Jsonb({"variant": "RETURN_REVERSAL"}),
            ),
        )
    assert (other_share.value.sqlstate, other_share.value.diag.message_primary) == (
        "23514",
        RECOVERED_ONLY,
    )
    # Review round 2: inside the draft's own correction the recorded share passes once (rolled
    # back here), and the same share a second time is refused.
    with psycopg.connect(url) as connection:
        found = connection.execute(BEGIN, (case["prop"], case["person"], shared)).fetchone()
        assert found is not None
        reversal_call = (case["prop"], case["person"], shared, found[0])
        tail = (REASON, EVIDENCE, Jsonb({"variant": "RETURN_REVERSAL"}))
        connection.execute(RECOVER, (*reversal_call, Jsonb([planned]), *tail))
        assert connection.execute(
            "SELECT app.refund_net_value_at(%s,'infinity')", (paid["id"],)
        ).fetchone() == (1_000,)
        again_entry = Jsonb([{**planned, "net_usd_cents": 1_000}])
        with pytest.raises(psycopg.Error) as twice_shared:
            connection.execute(RECOVER, (*reversal_call, again_entry, *tail))
        assert (twice_shared.value.sqlstate, twice_shared.value.diag.message_primary) == (
            "23514",
            RECOVERED_ONLY,
        )
        connection.rollback()
    result = confirm_reversal(case, shared)
    [recovery] = result["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (paid["id"], paid["recipient_customer_id"], 500, "EXTRA_CHARGE")
    assert (
        net(url, paid["id"]),
        net(url, pet_refund(case)),
        held(url, pet),
        charge_open(url, recovery),
    ) == (1_000, settled_net, 0, 500)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, UUID(str(paid["recipient_customer_id"])))
    with pytest.raises(FinalSettlementConflictError) as emptied:
        record_held(case, held_command(case, first_return, settlement_refund(case, "pet", 1_000)))
    assert cause(emptied) == ("55000", DEPOSIT_EMPTY)


def rows(database: str, statement: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(database) as connection:
        return connection.execute(statement).fetchall()


def test_return_reversal_records_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the internal functions; only the financial role calls the recorder and the
    confirm; each new function is SECURITY DEFINER with the fixed search path; the migration adds
    only its functions, changes only the listed functions (privileges and settings kept; each
    patched body is exactly the old one with the module's replacements), no constraint and no
    trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (*INTERNAL, RECORD, CONFIRM):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                allowed = role == "prm_financial" and function in (RECORD, CONFIRM)
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (allowed,), (function, role)
            assert connection.execute(
                "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
                "WHERE p.oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "search_path=pg_catalog"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261128_124"
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

    with _temporary_migration_database("settlement_return_reversal") as temporary:
        alembic_command.upgrade(config, "20261128_124")
        before_functions, before_constraints, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {*INTERNAL, RECORD, CONFIRM}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for name in PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function


def test_returned_money_that_also_paid_debt_beyond_its_refunds_waits_for_the_owner(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-12-96 (sub-slice 10e-3b), the Credit form: 300 of a correction's Credit Refund
    came back return only, then 1,700 more with a new Refund; the Credit, now 2,000, pays the
    1,500 charge and refunds 500. The new Refund paid out only 500 of the mistaken 1,700, so the
    rest paid debt; the reversal of that return is refused until the owner answers, and nothing is
    written."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    return_only(case, refund, 300)
    charge_line = unpaid_charge(url, case, case["person"])[1]
    pays_debt = SettlementCreditStep(credit, LINE, charge_line, 1_500)
    later = confirm(case, record(case, return_command(case, refund, 1_700, pays_debt)))
    [again] = later["refunds"]
    assert (
        again["amount_usd_cents"],
        available(url, credit),
        outstanding(url, charge_line),
    ) == (500, 0, 0)
    before = one(url, "SELECT count(*) FROM app.financial_drafts")
    with pytest.raises(FinalSettlementConflictError) as paid_debt:
        record_reversal(case, reversal_command(case, correction_of(later)))
    assert cause(paid_debt) == ("55000", PAID_DEBT)
    assert (
        one(url, "SELECT count(*) FROM app.financial_drafts"),
        net(url, again["id"]),
        outstanding(url, charge_line),
    ) == (before, 500, 0)


def test_a_reversal_keeps_the_applications_when_its_refund_paid_out_the_returned_money(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-12-95 (sub-slice 10e-3b, review round 1), the Credit form
    with an application: 1,800 of a correction's 2,000 Credit Refund came back return only; after
    a 1,500 charge, the other 200 comes back with a new Refund, and the Credit (2,000) pays the
    charge, refunds 200 and keeps 300. Reversing the 200 return charges back only the 200 Refund,
    which paid out the returned money first; the 1,500 application, paid from the Credit's other
    money, stays, and the Credit keeps its 300."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    return_only(case, refund, 1_800)
    charge_line = unpaid_charge(url, case, case["person"])[1]
    pays_debt = SettlementCreditStep(credit, LINE, charge_line, 1_500)
    later = confirm(case, record(case, return_command(case, refund, 200, pays_debt)))
    [again] = later["refunds"]
    assert (
        again["amount_usd_cents"],
        available(url, credit),
        outstanding(url, charge_line),
    ) == (200, 300, 0)
    draft = record_reversal(case, reversal_command(case, correction_of(later)))
    source = draft_source(url, draft)
    assert (
        source["credit_applications"],
        source["uses"],
        [
            (item["refund_id"], item["amount_usd_cents"], item["net_usd_cents"])
            for item in source["recoveries"]
        ],
    ) == (
        [],
        {"applied_usd_cents": 1_500, "refunded_usd_cents": 200, "returned_refunds": 0},
        [(again["id"], 200, 200)],
    )
    result = confirm_reversal(case, draft)
    [recovery] = result["recoveries"]
    assert (
        result["credit_application_reversals"],
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == ([], again["id"], str(customer), 200, "EXTRA_CHARGE")
    assert (
        net(url, again["id"]),
        net(url, refund),
        available(url, credit),
        outstanding(url, charge_line),
        charge_open(url, recovery),
    ) == (0, 200, 300, 0, 200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_the_rest_of_a_partly_charged_back_refund_is_charged_back_when_its_payment_bounces(
    migrated_database_url: str,
) -> None:
    """Review round 1 (sub-slice 10e-3b): a reversal charged back only 500 of a 1,500 Pet
    Deposit Refund; then the Payment that funded the Pet Deposit bounces. Its RETURNED_PAYMENT
    correction charges the Refund's 1,000 rest back to the person who received it, under its own
    charge reference (the first recovery keeps the plain one), and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    pet = case["pet"]
    return_only(case, pet_refund(case), 1_000)
    refund_all = settlement_refund(case, "pet", 1_500)
    mixed = confirm(case, record(case, return_command(case, pet_refund(case), 500, refund_all)))
    [paid] = mixed["refunds"]
    confirm_reversal(case, record_reversal(case, reversal_command(case, correction_of(mixed))))
    assert net(url, paid["id"]) == 1_000
    payment = receipt_payment(url, pet)
    returned = confirm_returned(case, record_returned(case, returned_command(case, payment)))
    [rest] = [item for item in returned["recoveries"] if item["refund_id"] == paid["id"]]
    assert (rest["customer_id"], rest["amount_usd_cents"], rest["charge"]) == (
        paid["recipient_customer_id"],
        1_000,
        "EXTRA_CHARGE",
    )
    assert (net(url, paid["id"]), held(url, pet)) == (0, 0)
    assert one(
        url,
        "SELECT array_agg(source_reference ORDER BY source_reference) "
        "FROM app.authorized_nonrecurring_obligations WHERE source_reference LIKE %s",
        f"refund-recovery:{paid['id']}%",
    )[0] == [f"refund-recovery:{paid['id']}", f"refund-recovery:{paid['id']}:2"]
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, UUID(str(paid["recipient_customer_id"])))


def test_the_shared_path_refusals_fail_closed(migrated_database_url: str) -> None:
    """Review round 1 (sub-slice 10e-3b), on the refusal function: on the shared path a Refund of
    the uses with its own return (also one returned in full, so not listed) is refused; Refunds
    that paid out less than the returned amount wait for the owner (Q-2026-10-12-96); missing
    totals are refused."""
    url = migrated_database_url
    shared: dict[str, Any] = {
        "earlier": {"amount_usd_cents": 500, "reversed": False},
        "credit_applications": [],
        "deposit_applications": [],
        "recoveries": [{"amount_usd_cents": 500, "returns": 0}],
        "source": {"value_usd_cents": 0},
        "uses": {"applied_usd_cents": 0, "refunded_usd_cents": 1_500, "returned_refunds": 0},
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(shared),))
    for changed, message in (
        ({"returned_refunds": 1}, OWN_RETURN),
        ({"applied_usd_cents": 1_100, "refunded_usd_cents": 400}, PAID_DEBT),
    ):
        source = {**shared, "uses": {**shared["uses"], **changed}}
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(source),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), changed
    missing = {key: item for key, item in shared.items() if key != "uses"}
    with pytest.raises(psycopg.Error) as closed, psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(missing),))
    assert (closed.value.sqlstate, closed.value.diag.message_primary) == (
        "55000",
        "The return reversal source is incomplete",
    )


def app_catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
    """Every app function (definition, privileges, owner, definer, settings), constraint and
    trigger."""
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


def test_the_return_reversal_payback_rules_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-3b: no role calls the two new internal functions, each SECURITY DEFINER with
    the fixed search path; migration 126 adds only those functions, changes only the six listed
    functions (privileges and settings kept; each patched body is exactly the old one with the
    module's replacements), no constraint and no trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in PAYBACK_INTERNAL:
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
    revision = scripts.get_revision(PAYBACK_REVISION)
    assert revision is not None and revision.down_revision == REVISION
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_payback") as temporary:
        alembic_command.upgrade(config, REVISION)
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, PAYBACK_REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == set(PAYBACK_INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PAYBACK_PATCHED
    for name in PAYBACK_PATCHED:
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PAYBACK_PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
