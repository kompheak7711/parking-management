"""Post-settlement correction: a returned Deposit Refund (V1-056 sub-slice 10c-2b-2a).

Owner answer 3 to Q-2026-10-07-42 and answer 3 to Q-2026-10-08-55: a returned Deposit Refund of the
Final Settlement or of one of its corrections goes back to the Deposit, never to Customer Credit. A
return-only REFUND_RETURN correction leaves it held by the Deposit; with a new Refund the same
correction runs the shared DL-032 step, so the Deposit value first pays the Lease's open debt in the
DL-032 order and only the rest is refunded (BR-SETTLE-008, BR-REFUND-014). Owner answer 5 to
Q-2026-10-08-55 (approved tightening) and the answer to Q-2026-10-08-56: after closure the receipt
reversal of a Lease Deposit is refused (P5S01). Owner answer 5 to Q-2026-10-08-52: the to-pet-damage
reversal of a pet classification correction runs on the real path, a Pet Deposit that holds money
again after its Refund came back. Owner answers to Q-2026-10-08-59: after closure a Lease Deposit
forfeiture is refused; a return-only Credit correction may leave a Deposit holding returned money
that no open debt can take (the hold rule); a receipt reversal draft is recorded only at READ
COMMITTED; the return check binds the draft's reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from deposit_receipt_reversal_test_support import approver as receipt_approver
from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.deposit import PostgresDepositService
from property_rental.deposit_receipt_reversal import (
    DepositReceiptReversalConflictError,
    DepositReceiptReversalService,
    RecordDepositReceiptReversalCommand,
)
from property_rental.final_settlement import (
    FinalSettlementConflictError,
    FinalSettlementInvalidError,
    FinalSettlementStaleDraftError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureConflictError
from property_rental.refund import RefundInvalidError
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_FIRST, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_refund_service_migration import returned
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import settlement_row
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import command as refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_extra_charge_migration import cause, state
from test_settlement_pet_classification_migration import command as classification_command
from test_settlement_pet_classification_migration import confirm as confirm_classification
from test_settlement_pet_classification_migration import is_pet
from test_settlement_pet_classification_migration import record as record_classification
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    BEGIN,
    COORDINATED,
    REASON,
    RETURN_ROW,
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
    return_values,
)

CLOSED_RECEIPT = (
    "A closed Final Settlement's Deposit receipt changes only through a post-settlement correction"
)
CHANGED = {
    "app.validate_general_refund_correction()": "GENERAL_CORRECTION_REPLACEMENTS",
    "app.validate_deposit_receipt_reversal()": "RECEIPT_TRIGGER_REPLACEMENTS",
    "app.record_deposit_receipt_reversal_draft(uuid,uuid,uuid,uuid,uuid,text,text)": (
        "RECEIPT_RECORDER_REPLACEMENTS"
    ),
    "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)": (
        "FORFEITURE_RECORDER_REPLACEMENTS"
    ),
    "app.validate_lease_deposit_disposition()": "DISPOSITION_TRIGGER_REPLACEMENTS",
    "app.settlement_correction_plan_result(uuid,uuid,uuid,jsonb,jsonb)": "PLAN_RESULT_REPLACEMENTS",
    "app.post_settlement_correction_plan(uuid,uuid,uuid)": "STEP_REPLACEMENTS",
}
REPLACED = {
    "app.settlement_refund_return_settlement(uuid)",
    "app.settlement_refund_return_allowed(app.refund_corrections)",
    "app.settlement_refund_return_source_state(uuid,uuid)",
    "app.settlement_refund_return_plan(uuid,uuid,jsonb)",
    "app.settlement_refund_return_overlay(jsonb)",
    "app.record_settlement_refund_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.confirm_settlement_refund_return(uuid,uuid,uuid,text)",
}


def effect_links(url: str, correction: object) -> list[str]:
    """The name of each effect's one link, in order (the links these corrections write)."""
    names = (
        "refund_correction_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "refund_id",
    )
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            f"SELECT {','.join(names)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    return [next(name for name, value in zip(names, row, strict=True) if value) for row in rows]


def pet_refund(case: dict[str, Any]) -> UUID:
    """The Final Settlement's own Deposit Refund of the Pet Deposit's rest (5,400, sub-slice 8d)."""
    return UUID(
        str(
            one(
                case["url"],
                "SELECT refund_id FROM app.final_settlement_refund_details "
                "WHERE final_settlement_id=%s AND deposit_id=%s",
                case["settlement"],
                case["pet"],
            )[0]
        )
    )


def test_a_returned_settlement_deposit_refund_stays_held_by_its_deposit(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-07-42: the Settlement's Pet Deposit Refund (5,400) is not
    returned with one call; a return-only correction of 2,000 writes the verified return under
    financial.approve, linked first, and the Pet Deposit holds 2,000 again; no step runs, so no
    Customer Credit, Deposit application or Refund is written; a return-only form refuses a plan.
    The Settlement row is unchanged, the ledger reconciles and an exact repeat replays."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    refund, pet, customer = pet_refund(case), case["pet"], case["customer"]
    assert (held(url, pet), net(url, refund)) == (0, 5_400)
    with pytest.raises(RefundInvalidError) as one_call:
        refunds().verify_usd_return(
            case["prop"],
            refund,
            returned(500),
            actor=refund_actor(case["human"], case["prop"], "refunds.correct"),
        )
    assert cause(one_call) == ("P5202", COORDINATED)
    with pytest.raises(FinalSettlementInvalidError) as planned:
        record(
            case,
            return_command(case, refund, 2_000, settlement_refund(case, "pet", 2_000), new=False),
        )
    assert cause(planned)[0] == "22023"
    with pytest.raises(FinalSettlementInvalidError) as stepped:
        record(
            case,
            return_command(
                case,
                refund,
                2_000,
                SettlementCreditStep(case["new_credit"], LINE, case["other_line"], 100),
                new=False,
            ),
        )
    assert cause(stepped) == ("22023", "A return-only Deposit Refund correction has no DL-032 step")
    with pytest.raises(FinalSettlementInvalidError) as decided:
        record(case, return_command(case, refund, 2_000, new=False, pet_remainder=STAFF))
    assert cause(decided) == (
        "22023",
        "A return-only Deposit Refund correction has no DL-032 step",
    )
    before = settlement_row(url, case["settlement"])
    credits = one(url, "SELECT count(*) FROM app.customer_credits WHERE customer_id=%s", customer)
    draft = record(case, return_command(case, refund, 2_000, new=False))
    other = record(case, return_command(case, refund, 1_000, new=False))
    assert one(
        url,
        "SELECT payload->'runs_step',payload->>'deposit_id',payload->'plan_result' "
        "FROM app.financial_drafts WHERE id=%s",
        draft,
    ) == (False, str(pet), None)
    result = confirm(case, draft)
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert effect_links(url, correction) == ["refund_correction_id"]
    [returned_row] = result["refund_corrections"]
    assert (
        returned_row["refund_id"],
        returned_row["returned_amount_usd_cents"],
        returned_row["resulting_net_refund_usd_cents"],
        returned_row["authorization_reference"],
    ) == (str(refund), 2_000, 3_400, "financial.approve")
    assert (
        result["refunds"],
        result["credit_applications"],
        result["deposit_applications"],
    ) == ([], [], [])
    assert (held(url, pet), net(url, refund)) == (2_000, 3_400)
    assert (
        one(url, "SELECT count(*) FROM app.customer_credits WHERE customer_id=%s", customer)
        == credits
    )
    assert settlement_row(url, case["settlement"]) == before
    confirmed = one(
        url,
        "SELECT resulting_state FROM app.audit_events WHERE correlation_id=%s "
        "AND action='final_settlement.correction.confirmed'",
        correction,
    )[0]
    assert (
        confirmed["deposit_id"],
        confirmed["customer_credit_id"],
        confirmed["deposit_refund_ids"],
    ) == (str(pet), None, [])
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)
    assert confirm(case, draft) == result
    # Review round 1: a second draft on the same Refund is stale after the first and waits.
    with pytest.raises(FinalSettlementStaleDraftError):
        confirm(case, other)
    assert state(url, other) == "PENDING"


def test_a_returned_settlement_deposit_refund_first_pays_the_lease_s_open_debt(
    migrated_database_url: str,
) -> None:
    """Owner answer 3 to Q-2026-10-08-55 (DL-032, BR-SETTLE-008): the Customer owes a 1,500
    charge issued after closure; the whole Pet Deposit Refund (5,400) comes back with a new
    Refund. Without a plan the correction is refused (every Deposit balance is applied or
    refunded); with the plan the Customer's own Credit pays 300 first, the remaining Pet Deposit
    pays the other 1,200, and only the rest (4,200) is refunded from the Pet Deposit."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    refund, pet, customer = pet_refund(case), case["pet"], case["customer"]
    _, charge_line = unpaid_charge(url, case, case["person"])
    with pytest.raises(FinalSettlementConflictError) as unplanned:
        record(case, return_command(case, refund, 5_400))
    assert cause(unplanned) == (
        "55000",
        "Every remaining Deposit balance must be applied or refunded",
    )
    draft = record(
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
    )
    result = confirm(case, draft)
    assert effect_links(url, result["settlement_correction"]["id"]) == [
        "refund_correction_id",
        "customer_credit_application_id",
        "deposit_application_id",
        "refund_id",
    ]
    [applied] = result["credit_applications"]
    assert (applied["customer_credit_id"], applied["amount_usd_cents"]) == (
        str(case["new_credit"]),
        300,
    )
    [deposit_application] = result["deposit_applications"]
    assert (
        deposit_application["deposit_id"],
        deposit_application["application_stage"],
        deposit_application["amount_usd_cents"],
    ) == (str(pet), "PET_REMAINDER_EXPLICIT", 1_200)
    [paid] = result["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
    ) == (str(pet), str(customer), 4_200, str(case["cash"]))
    assert (held(url, pet), net(url, refund), outstanding(url, charge_line)) == (0, 0, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_correction_s_deposit_refund_is_returned_to_its_deposit(
    migrated_database_url: str,
) -> None:
    """A correction's Deposit Refund (sub-slice 10c-2a-3: a 4,000 Refund of the other Damage line
    refunds 2,200 of the Security Deposit) comes back in part (1,000) through a return-only
    correction: the Security Deposit holds 1,000 again; the one-call return stays refused."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    security, line = case["security"], case["other_line"]
    result = confirm_refund(
        case,
        record_refund(
            case,
            refund_command(
                case,
                line,
                4_000,
                SettlementCreditStep(case["new_credit"], LINE, line, 300),
                SettlementDepositStep(SECURITY, security, LINE, line, 7_800),
                settlement_refund(case, "security", 2_200),
                settlement_refund(case, "pet", 2_100),
            ),
        ),
    )
    [security_refund] = [
        UUID(str(item["id"]))
        for item in result["refunds"]
        if item["source_deposit_id"] == str(security)
    ]
    with pytest.raises(RefundInvalidError) as one_call:
        refunds().verify_usd_return(
            case["prop"],
            security_refund,
            returned(500),
            actor=refund_actor(case["human"], case["prop"], "refunds.correct"),
        )
    assert cause(one_call) == ("P5202", COORDINATED)
    returned_result = confirm(
        case, record(case, return_command(case, security_refund, 1_000, new=False))
    )
    [returned_row] = returned_result["refund_corrections"]
    assert (returned_row["refund_id"], returned_row["returned_amount_usd_cents"]) == (
        str(security_refund),
        1_000,
    )
    assert (held(url, security), net(url, security_refund)) == (1_000, 1_200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_to_pet_reversal_runs_on_a_pet_deposit_that_holds_its_returned_refund(
    migrated_database_url: str,
) -> None:
    """Owner answer 5 to Q-2026-10-08-52, on the real path: the Settlement's Pet Deposit Refund
    (5,400) comes back return-only, so the Pet Deposit on the DL-032 path holds 5,400; a pet
    classification correction of the other Damage line to pet damage then reverses that line's
    Security Deposit application (10,000), and the plan pays the line again with the Customer's
    own Credit first (300), the Pet Deposit as pet damage (5,400) and the Security Deposit (4,300),
    refunding the Security Deposit's rest (5,700)."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, security, line = case["pet"], case["security"], case["other_line"]
    confirm(case, record(case, return_command(case, pet_refund(case), 5_400, new=False)))
    assert (held(url, pet), held(url, security), is_pet(case, line)) == (5_400, 0, False)
    result = confirm_classification(
        case,
        record_classification(
            case,
            classification_command(
                case,
                line,
                True,
                SettlementCreditStep(case["new_credit"], LINE, line, 300),
                SettlementDepositStep(PET_FIRST, pet, LINE, line, 5_400),
                SettlementDepositStep(SECURITY, security, LINE, line, 4_300),
                settlement_refund(case, "security", 5_700),
            ),
        ),
    )
    [reversal] = result["deposit_application_reversals"]
    assert reversal["deposit_application_id"] == str(case["security_application"])
    with psycopg.connect(url) as connection:
        stages = sorted(
            cast(tuple[str, int], tuple(row))
            for row in connection.execute(
                "SELECT application_stage,amount_usd_cents FROM app.deposit_applications "
                "WHERE id=ANY(%s::uuid[])",
                ([str(item) for item in result["deposit_application_ids"]],),
            ).fetchall()
        )
    assert stages == [("PET_RELATED_FIRST", 5_400), ("SECURITY_EXPLICIT", 4_300)]
    assert len(result["deposit_refund_ids"]) == 1
    assert (held(url, pet), held(url, security), outstanding(url, line), is_pet(case, line)) == (
        0,
        0,
        0,
        True,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_lease_deposit_receipt_is_not_reversed_after_closure(
    migrated_database_url: str,
) -> None:
    """Owner answer 5 to Q-2026-10-08-55 (approved tightening) and the answer to
    Q-2026-10-08-56: once the Final Settlement is closed, a receipt reversal draft for the Security
    Deposit's receipt is refused at record (a conflict, P5S01), and a receipt reversal row written
    directly is refused too unless a correction of that Settlement links it."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    receipt = UUID(
        str(
            one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["security"])[0]
        )
    )
    service = DepositReceiptReversalService(financial_database_url())
    with pytest.raises(DepositReceiptReversalConflictError) as recorded:
        service.record(
            case["prop"],
            RecordDepositReceiptReversalCommand(uuid4(), receipt, uuid4(), "Transfer returned"),
            actor=receipt_approver(case["human"], case["prop"]),
        )
    assert cause(recorded) == ("P5S01", CLOSED_RECEIPT)
    with pytest.raises(psycopg.Error) as direct, psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,"
            "actor_id,authorization_reference) VALUES (%s,%s,'Direct',clock_timestamp(),%s,"
            "'deposits.correct')",
            (uuid4(), receipt, case["human"]),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == ("P5S01", CLOSED_RECEIPT)
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_receipt_reversals WHERE deposit_receipt_id=%s",
        receipt,
    ) == (0,)


def test_a_credit_return_only_correction_leaves_a_deposit_holding_returned_money(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to Q-2026-10-08-59: returns come back together, and each is recorded before
    anything is paid again. The Pet Deposit holds 2,000 of its returned Settlement Refund and the
    Customer owes nothing, so a return-only correction of a correction's Credit Refund (500) is
    accepted: the Credit keeps 500 and the Pet Deposit keeps its 2,000. Once the Customer owes a
    1,500 charge, a Credit return-only correction still lets the returned Credit pay first (owner
    answer 1 to Q-2026-10-08-55), with the Customer's other Credit, and the Pet Deposit pay the rest
    a staff decision lets it pay; a plan that leaves that debt open while the Deposit keeps money
    is refused; with the full plan the Pet Deposit keeps only what no debt can take (1,600)."""
    url = migrated_database_url
    case = refunded_case(url)
    pet, credit = case["pet"], case["refund_credit"]
    confirm(case, record(case, return_command(case, pet_refund(case), 2_000, new=False)))
    assert held(url, pet) == 2_000
    kept = confirm(case, record(case, return_command(case, case["refund"], 500, new=False)))
    assert (kept["refunds"], kept["credit_applications"], kept["deposit_applications"]) == (
        [],
        [],
        [],
    )
    assert (held(url, pet), available(url, credit), net(url, case["refund"])) == (
        2_000,
        500,
        1_500,
    )
    _, charge_line = unpaid_charge(url, case, case["person"])
    with pytest.raises(FinalSettlementConflictError) as open_debt:
        record(
            case,
            return_command(
                case,
                case["refund"],
                300,
                SettlementCreditStep(credit, LINE, charge_line, 800),
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                new=False,
            ),
        )
    assert cause(open_debt) == (
        "55000",
        "A Deposit keeps returned money only when no open debt can take it",
    )
    paid = confirm(
        case,
        record(
            case,
            return_command(
                case,
                case["refund"],
                300,
                SettlementCreditStep(credit, LINE, charge_line, 800),
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 400),
                new=False,
                pet_remainder=STAFF,
            ),
        ),
    )
    assert [item["amount_usd_cents"] for item in paid["credit_applications"]] == [800, 300]
    assert [item["amount_usd_cents"] for item in paid["deposit_applications"]] == [400]
    assert paid["refunds"] == []
    assert (held(url, pet), available(url, credit), outstanding(url, charge_line)) == (
        1_600,
        0,
        0,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_hold_rule_keeps_only_money_no_open_debt_can_take(migrated_database_url: str) -> None:
    """Owner answer 2 to Q-2026-10-08-59, the plan check's hold rule on its own (overlay
    ``hold_deposits``, as a return-only Credit correction records it): a Security Deposit keeps no
    money while debt stays open; a Pet Deposit keeps no money while pet damage stays open after its
    own step, even when the Security Deposit pays that pet damage instead (review round 2); with the
    Customer's Credit first and the Pet Deposit paying the pet damage, both may keep the rest."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    hold = "A Deposit keeps returned money only when no open debt can take it"

    def check(owed: dict[str, int], deposits: dict[str, int], *steps: Any) -> None:
        with psycopg.connect(url) as connection:
            connection.execute(
                "SELECT app.settlement_correction_plan_result(%s,%s,%s,%s,%s)",
                (
                    case["prop"],
                    case["human"],
                    case["settlement"],
                    Jsonb({"steps": [step.payload() for step in steps], "pet_remainder": None}),
                    Jsonb(
                        {
                            "obligations": owed,
                            "credits": {},
                            "deposits": deposits,
                            "hold_deposits": True,
                        }
                    ),
                ),
            )

    pet_line, other_line = f"INVOICE_LINE:{case['pet_line']}", f"INVOICE_LINE:{case['other_line']}"
    pet, security = str(case["pet"]), str(case["security"])
    credit_first = SettlementCreditStep(case["new_credit"], LINE, case["other_line"], 300)
    with pytest.raises(psycopg.Error) as security_kept:
        check({other_line: 500}, {security: 1_000}, credit_first)
    assert (security_kept.value.sqlstate, security_kept.value.diag.message_primary) == (
        "55000",
        hold,
    )
    pet_credit = SettlementCreditStep(case["new_credit"], LINE, case["pet_line"], 300)
    with pytest.raises(psycopg.Error) as pet_kept:
        check(
            {pet_line: 1_000},
            {pet: 2_000, security: 2_000},
            pet_credit,
            SettlementDepositStep(SECURITY, case["security"], LINE, case["pet_line"], 700),
        )
    assert (pet_kept.value.sqlstate, pet_kept.value.diag.message_primary) == ("55000", hold)
    check(
        {pet_line: 1_000},
        {pet: 2_000, security: 2_000},
        pet_credit,
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 700),
    )


def test_a_closed_settlement_s_deposit_is_not_forfeited_and_receipt_drafts_need_read_committed(
    migrated_database_url: str,
) -> None:
    """Owner answers 1 and 4 to Q-2026-10-08-59 (approved tightenings): once the Final Settlement is
    closed, a Lease Deposit forfeiture draft is refused at record (P5S01, before any other check
    of the Deposit); a receipt reversal draft is recorded only at READ COMMITTED (55000)."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    with pytest.raises(LeaseDepositForfeitureConflictError) as forfeited:
        forfeit_through_draft(
            PostgresDepositService(financial_database_url(), case["prop"], case["human"]),
            case["security"],
        )
    error = forfeited.value.__cause__
    assert isinstance(error, psycopg.Error)
    assert (error.sqlstate, error.diag.message_primary) == (
        "P5S01",
        "A closed Final Settlement's Deposit is forfeited only through a post-settlement "
        "correction",
    )
    receipt = one(url, "SELECT id FROM app.deposit_receipts WHERE deposit_id=%s", case["pet"])[0]
    with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute(
            "SELECT app.record_deposit_receipt_reversal_draft("
            "%s,%s,%s,%s,%s,%s,'deposits.correct')",
            (case["prop"], case["human"], uuid4(), receipt, uuid4(), "Transfer returned"),
        )
    assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
        "55000",
        "A Deposit receipt reversal draft is recorded at READ COMMITTED",
    )


def test_the_return_check_binds_the_draft_s_reason(migrated_database_url: str) -> None:
    """Owner answer 3 to Q-2026-10-08-59: inside a return-only correction of the Settlement's Pet
    Deposit Refund confirmed by hand, a return row with every field of the draft but another reason
    is refused by the Settlement Refund check (23514), and the same row with the draft's reason
    passes; each attempt rolls back and the draft stays pending."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    refund = pet_refund(case)
    draft = record(case, return_command(case, refund, 1_000, new=False))
    returned_at = one(
        url,
        "SELECT (payload->'refund_return'->>'returned_at')::timestamptz FROM app.financial_drafts "
        "WHERE id=%s",
        draft,
    )[0]
    for reason, passes in (("Another reason", False), (REASON, True)):
        row = uuid4()
        with psycopg.connect(url) as connection:
            found = connection.execute(BEGIN, (case["prop"], case["person"], draft)).fetchone()
            assert found is not None
            connection.execute(
                "SELECT app.link_settlement_correction_effect(%s,'refund_correction_id',%s)",
                (found[0], row),
            )
            values = return_values(
                row, 1_000, case["person"], "financial.approve", returned_at, refund, reason=reason
            )
            if passes:
                connection.execute(RETURN_ROW, values)
                assert connection.execute(
                    "SELECT app.refund_net_value_at(%s,'infinity')", (refund,)
                ).fetchone() == (4_400,)
            else:
                with pytest.raises(psycopg.Error) as refused:
                    connection.execute(RETURN_ROW, values)
                assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                    "23514",
                    "A Final Settlement Refund is corrected only through a post-settlement "
                    "correction",
                )
            connection.rollback()
    assert state(url, draft) == "PENDING"
    assert net(url, refund) == 5_400


def test_the_deposit_refund_return_migration_is_forward_only(migrated_database_url: str) -> None:
    """The migration replaces only the returned-Refund correction functions of sub-slice 10c-2b-1
    and patches seven functions (the Refund correction check, the receipt reversal recorder and
    trigger, the Lease forfeiture recorder, the disposition check, the plan check and the step; each
    new body exactly the old one with its replacements); every changed function keeps its owner,
    SECURITY DEFINER, settings and privileges; only the financial role records and confirms."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (
            "app.record_settlement_refund_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
            "app.confirm_settlement_refund_return(uuid,uuid,uuid,text)",
        ):
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (role == "prm_financial",), (function, role)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261112_108")
    assert revision is not None and revision.down_revision == "20261111_107"
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

    with _temporary_migration_database("settlement_deposit_refund_return") as temporary:
        alembic_command.upgrade(config, "20261111_107")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261112_108")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED) | REPLACED
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
    for function in set(CHANGED) | REPLACED:
        assert after_functions[function][1:] == before_functions[function][1:], function
