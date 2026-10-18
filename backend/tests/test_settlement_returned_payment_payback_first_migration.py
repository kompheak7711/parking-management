"""A shared Deposit with pay-back money gives back from its forfeiture first (V1-056 sub-slice
10e-2b-4e-2b-1).

Owner answer (a) to Q-2026-10-18-135: when the RETURNED_PAYMENT correction gives back a shared
Deposit's shortfall and the Deposit holds the Customer's pay-back money beside an active
forfeiture, the forfeiture gives back first, so no pay-back money stays forfeited (the committed
B1 test of sub-slice 10e-2b-4e-2a, renamed, shows it on the real path). The owner also asked for a
test of the implementer's reading of newest first by time across every use: a Pet Refund-review
Refund paid before closure comes after the Settlement's applications. Every test runs on a real
closure, to the cent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import disposition_context
from lease_deposit_forfeiture_test_support import record_disposition_as_owner
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    CreatePetDepositCommand,
    DepositAdjustmentType,
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordDepositDispositionCommand,
    RecordPetDepartureCommand,
)
from property_rental.final_settlement import SettlementDepositStep
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_deposit_migration import deposit_actor, seed_historical_deposit_receipt
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_FIRST, SECURITY
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, line_of, one, outstanding, start, today
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_out_inspection_migration import actor as inspection_actor
from test_move_out_inspection_migration import flow as inspection_flow
from test_one_time_charges_migration import damage, draft_and_issue, invoices
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_move_migration import rows, value
from test_payment_return_recovery_migration import charge
from test_payment_return_shared_deposit_migration import active_receipts, net, recoveries
from test_pet_refund_migration import command as pet_command
from test_refund_service_migration import refund_id
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_correction_migration import settlement_row
from test_settlement_pet_payback_migration import forfeit, forfeited
from test_settlement_pet_payback_migration import pet_case as pet_payback_case
from test_settlement_refund_return_migration import confirm as confirm_return
from test_settlement_refund_return_migration import record as record_return
from test_settlement_refund_return_migration import return_command
from test_settlement_returned_payment_migration import (
    STILL_HOLDS,
    allowed_check,
    command,
    confirm,
    payload,
    reconciled,
    record,
    status,
)
from test_settlement_returned_payment_shared_deposit_migration import (
    ACTIVE_FORFEITURES,
    PAYBACK_BESIDE,
)
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20270102_159"
PATCHED = {
    "app.settlement_returned_payment_shared(uuid,uuid,jsonb)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
}


def review_refund_case(url: str) -> dict[str, Any]:
    """A signed Lease starting this month whose 20,000 Pet Deposit takes 10,000 from Payment A and
    10,000 from Payment B (owner inserts, as the pay-back fixtures seed receipts). The pet leaves,
    a DL-053 review qualifies and a 15,000 Pet Refund-review Refund is paid to the Customer (not
    returned), so the Deposit holds 5,000. A move-out inspection bills two Damage charges of
    12,500 (one pet-related); the Initial Rent is paid and the Lease is terminated with no
    forfeiture ground. The Settlement applies the Pet Deposit's 5,000 to the pet damage line and
    the Security Deposit's 10,000 to the other damage line; then it closes."""
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
    pet = uuid4()
    deposits.create_pet_deposit(
        CreatePetDepositCommand(
            uuid4(), pet, lease, approval, 20_000, day, "Approved signed Lease pet terms"
        ),
        actor=who,
    )
    for _ in range(2):
        seed_historical_deposit_receipt(
            url, deposit_id=pet, actor_id=human, amount_usd_cents=10_000
        )
    first, second = active_receipts(url, pet)
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
            pet_command(pet, review.review_id, 15_000),
            actor=refund_actor(human, prop, "refunds.create"),
        )
    )
    assert held(url, pet) == 5_000
    version = one(url, "SELECT version FROM app.leases WHERE id=%s", lease)
    pet_finding, other_finding = uuid4(), uuid4()
    inspection_flow().record(
        prop,
        lease,
        RecordMoveOutInspection(
            uuid4(),
            uuid4(),
            int(version[0]),
            day,
            "Recorded inspection condition",
            "Approved inspection",
            "Evidence-901",
            "Record actual inspection",
            (
                InspectionFinding(pet_finding, "Scratched door by the pet", True),
                InspectionFinding(other_finding, "Broken window latch", False),
            ),
        ),
        actor=inspection_actor(human, prop),
        request_id="payback-first-inspection",
    )
    lines: dict[str, UUID] = {}
    for name, finding in (("pet_line", pet_finding), ("other_line", other_finding)):
        charge_command = damage(customer, lease, finding)
        invoices().record_one_time_charge(prop, charge_command, actor=invoice_staff(human, prop))
        issued = draft_and_issue(prop, charge_command.charge_id, invoice_staff(human, prop))
        lines[name] = line_of(url, issued["id"])
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate(url, human, prop, lease, day, voluntary=False)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "settlement": start(prop, human, lease),
        "first": first,
        "second": second,
        "review_refund": review_refund,
        **lines,
    }
    steps = (
        SettlementDepositStep(PET_FIRST, pet, LINE, lines["pet_line"], 5_000),
        SettlementDepositStep(SECURITY, case["security"], LINE, lines["other_line"], 10_000),
    )
    confirm_settlement(case, record_settlement(case, steps))
    case["person"] = correction_approver(url)
    return case


def test_a_review_refund_paid_before_closure_gives_back_after_the_settlement_s_applications(
    migrated_database_url: str,
) -> None:
    """Owner answer 2 to the 10e-2b-4e-2a report (the implementer's reading of newest first by
    time across every use): A's 10,000 bounces after closure; the Pet Deposit holds 0, so its
    shortfall is 10,000. The Settlement's 5,000 application is newer than the 15,000 Pet
    Refund-review Refund paid before closure, so it gives back first (reversed, nothing kept), and
    then 5,000 of the review Refund is charged back to the Customer on the Lease (its net 10,000
    stays out). No forfeiture, so the forfeiture-first rule does not apply. The pet damage line
    owes the 5,000 again, the Deposit holds 0 and B's receipt stays. Hand-built: a plan whose
    give-backs do not reach its give_back total, or whose total is below the shortfall, is
    refused. The closed Settlement row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = review_refund_case(url)
    pet, pet_line, customer = case["pet"], case["pet_line"], case["customer"]
    first, second, review_refund = case["first"], case["second"], case["review_refund"]
    [applied] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.deposit_applications WHERE deposit_id=%s", pet)
    ]
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 7_500)
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, first))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["deposit_id"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["payback_first"],
    ) == (str(pet), 10_000, 10_000, False)
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("APPLICATION", str(applied), 5_000, 5_000, 0),
        ("REFUND", str(review_refund), 15_000, 5_000, 10_000),
    ]
    [recovery] = source["recoveries"]
    assert (recovery["refund_id"], recovery["amount_usd_cents"], recovery["net_usd_cents"]) == (
        str(review_refund),
        5_000,
        15_000,
    )
    assert allowed_check(url, case, source) == (None, None)
    for changed in (
        {"give_back_usd_cents": 10_001},
        {"give_back_usd_cents": 9_999},
        {"give_back_usd_cents": None},
    ):
        wrong = json.loads(json.dumps(source))
        wrong["shared_deposits"][0].update(changed)
        if changed["give_back_usd_cents"] == 9_999:
            wrong["shared_deposits"][0]["uses"][1]["undo_usd_cents"] = 4_999
        assert allowed_check(url, case, wrong) == ("55000", STILL_HOLDS)
    # Review round 1 (both reviewers): a total above the rule's, matched by its own uses, and a
    # duplicated plan entry are refused too. Review round 2 (independent notes 1, 2 and 4): a
    # shortfall that is not the live one, a receipt that is not the live one (with the shortfall
    # and the total raised to match it) and a plan entry for a Deposit that is not shared.
    more = json.loads(json.dumps(source))
    more["shared_deposits"][0]["give_back_usd_cents"] = 15_000
    more["shared_deposits"][0]["uses"][1].update(
        {"undo_usd_cents": 10_000, "kept_usd_cents": 5_000}
    )
    twice = json.loads(json.dumps(source))
    twice["shared_deposits"].append(twice["shared_deposits"][0])
    lower = json.loads(json.dumps(source))
    [lower_entry] = [entry for entry in lower["deposits"] if entry["id"] == str(pet)]
    lower_entry["shortfall_usd_cents"] = 9_000
    lower["shared_deposits"][0]["give_back_usd_cents"] = 9_000
    lower["shared_deposits"][0]["uses"][1].update(
        {"undo_usd_cents": 4_000, "kept_usd_cents": 11_000}
    )
    raised = json.loads(json.dumps(source))
    [raised_entry] = [entry for entry in raised["deposits"] if entry["id"] == str(pet)]
    raised_entry["shortfall_usd_cents"] = 11_000
    raised["shared_deposits"][0].update(
        {"receipt_usd_cents": 11_000, "give_back_usd_cents": 11_000}
    )
    raised["shared_deposits"][0]["uses"][1].update(
        {"undo_usd_cents": 6_000, "kept_usd_cents": 9_000}
    )
    stray = json.loads(json.dumps(source))
    stray["shared_deposits"].append(
        {**stray["shared_deposits"][0], "deposit_id": str(case["security"]), "uses": []}
    )
    for hand_built in (more, twice, lower, raised, stray):
        assert allowed_check(url, case, hand_built) == ("55000", STILL_HOLDS)
    result = confirm(case, draft)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        5_000,
    )
    assert (recoveries(url, review_refund), net(url, review_refund)) == ([5_000], 10_000)
    [reversal] = result["deposit_application_reversal_ids"]
    assert (
        value(
            url,
            "SELECT deposit_application_id FROM app.deposit_application_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        == applied
    )
    assert result["deposit_application_ids"] == [] and result["forfeiture_ids"] == []
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 12_500)
    assert active_receipts(url, pet) == [second]
    assert (status(url, first), status(url, second)) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


def kept_pet_case(url: str, pet_amount: int, second_amount: int) -> dict[str, Any]:
    """The B1 set-up of sub-slice 10e-2b-4e-2a (`pet_payback_case`): A's pet_amount funds a Pet
    Deposit, a 4,000 Pet Refund-review Refund comes back in full (pay-back count 4,000) and the
    Lease is terminated for pet noncompliance; the required total is raised by second_amount and
    B's receipt of that amount is seeded (an owner insert after the termination, as in that test;
    the checks read no event times). The Security Deposit is forfeited."""
    case: dict[str, Any] = {
        **pet_payback_case(url, (("refund", 4_000), ("return", 4_000)), pet_amount=pet_amount),
        "url": url,
    }
    human, prop, pet = case["human"], case["prop"], case["pet"]
    [first] = active_receipts(url, pet)
    PostgresDepositService(financial_database_url(), prop, human).adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            pet,
            DepositAdjustmentType.INCREASE,
            second_amount,
            today(url),
            "The agreed Lease terms raise the Pet Deposit",
        ),
        actor=deposit_actor(human, prop),
    )
    seed_historical_deposit_receipt(
        url, deposit_id=pet, actor_id=human, amount_usd_cents=second_amount
    )
    [second] = [found for found in active_receipts(url, pet) if found != first]
    forfeit(case, "security")
    return {**case, "first": first, "second": second}


def settlement_refund_of(case: dict[str, Any]) -> UUID:
    """The kept Pet Deposit's 4,000 pay-back money refunded by the Settlement, which then closes;
    the Settlement Refund's id."""
    url, pet = case["url"], case["pet"]
    assert held(url, pet) == 4_000
    confirm_settlement(case, record_settlement(case, (settlement_refund(case, "pet", 4_000),)))
    [paid_back] = rows(
        url,
        "SELECT id FROM app.refunds WHERE source_deposit_id=%s AND pet_refund_review_id IS NULL",
        pet,
    )
    case["person"] = correction_approver(url)
    return UUID(str(paid_back[0]))


def test_a_forfeiture_smaller_than_the_shortfall_gives_back_whole_then_the_refund(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-18-135, its second clause (review round 1, both reviewers):
    A's 5,000 and B's 1,000 fund the kept Pet Deposit with 4,000 of pay-back money; the
    forfeiture takes the 2,000 beyond it and the Settlement refunds the 4,000. A bounces: the
    shortfall is 5,000, more than the 2,000 forfeiture, so the forfeiture gives back first and in
    full (newest first would have charged the whole 4,000 Refund back and kept 1,000 forfeited),
    and only the 3,000 left is charged back on the Settlement Refund (its net 1,000 stays out). No
    forfeiture stays; the Deposit holds 0; B's receipt stays."""
    url = migrated_database_url
    case = kept_pet_case(url, 5_000, 1_000)
    pet, customer = case["pet"], case["customer"]
    forfeit(case, "pet")
    assert forfeited(case, "pet") == [2_000]
    paid_back = settlement_refund_of(case)
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, case["first"]))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["payback_first"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["payback_usd_cents"],
    ) == (True, 5_000, 5_000, 0)
    keys = ("kind", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("FORFEITURE", 2_000, 2_000, 0),
        ("REFUND", 4_000, 3_000, 1_000),
    ]
    [recovery] = source["recoveries"]
    assert (recovery["refund_id"], recovery["amount_usd_cents"], recovery["net_usd_cents"]) == (
        str(paid_back),
        3_000,
        4_000,
    )
    result = confirm(case, draft)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        3_000,
    )
    assert (recoveries(url, paid_back), net(url, paid_back)) == ([3_000], 1_000)
    assert (len(result["forfeiture_reversal_ids"]), result["forfeiture_ids"]) == (1, [])
    assert rows(url, ACTIVE_FORFEITURES, pet) == []
    assert (held(url, pet), active_receipts(url, pet)) == (0, [case["second"]])
    # Review round 2 (security note 2): the 3,000 charge-back undoes that much of the Settlement
    # Refund's payout, so the pay-back count is 3,000 while the Deposit holds 0; with no
    # forfeiture nothing keeps it (the pay-back value is the smaller of the two, 0).
    assert value(url, "SELECT app.lease_deposit_payback_count_as(%s,NULL,0,false)", pet) == 3_000
    assert value(url, "SELECT app.lease_deposit_payback_value(%s)", pet) == 0
    assert (status(url, case["first"]), status(url, case["second"])) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


def test_the_forfeiture_gives_back_at_most_what_it_keeps(
    migrated_database_url: str,
) -> None:
    """Review round 2 (independent should-fix 1, its set-up): A's 5,000 and B's 2,000 fund the
    kept Pet Deposit with 4,000 of pay-back money; the forfeiture takes the 3,000 beyond it, the
    Settlement refunds the 4,000 and a return-only correction brings it back (the Deposit holds
    4,000). A's shortfall is 1,000, but the rule asks for 5,000 (the receipt less the held value
    plus the 4,000 pay-back count), more than the 3,000 the forfeiture keeps; so the forfeiture
    gives back its 3,000 in full and no more, nobody is charged and the Deposit ends holding
    2,000, all of B's money."""
    url = migrated_database_url
    case = kept_pet_case(url, 5_000, 2_000)
    pet = case["pet"]
    forfeit(case, "pet")
    assert forfeited(case, "pet") == [3_000]
    paid_back = settlement_refund_of(case)
    confirm_return(case, record_return(case, return_command(case, paid_back, 4_000, new=False)))
    assert held(url, pet) == 4_000
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, case["first"]))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["payback_first"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["payback_usd_cents"],
    ) == (True, 1_000, 3_000, 4_000)
    keys = ("kind", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("FORFEITURE", 3_000, 3_000, 0)
    ]
    assert source["recoveries"] == []
    # Review round 3 (independent should-fix 1, its set-up): a hand-built source with a
    # forfeiture the database does not hold passes the record check's total (it reads the live
    # forfeitures) and is refused by the B1 end-held branch (4,000 > 4,000 + 3,000 - 5,000);
    # with a forged held value or receipt that would hide it, the total refuses it first.
    extra = json.loads(json.dumps(source))
    extra["forfeitures"].append(
        {
            "id": str(uuid4()),
            "deposit_id": str(pet),
            "governing_lease_id": str(case["lease"]),
            "amount_usd_cents": 1_000,
        }
    )
    assert allowed_check(url, case, extra) == ("55000", PAYBACK_BESIDE)
    extra["shared_deposits"][0]["held_usd_cents"] = 6_000
    assert allowed_check(url, case, extra) == ("55000", STILL_HOLDS)
    extra["shared_deposits"][0]["held_usd_cents"] = 4_000
    extra["shared_deposits"][0]["receipt_usd_cents"] = 3_000
    assert allowed_check(url, case, extra) == ("55000", STILL_HOLDS)
    result = confirm(case, draft)
    assert result["recoveries"] == []
    assert (len(result["forfeiture_reversal_ids"]), result["forfeiture_ids"]) == (1, [])
    assert rows(url, ACTIVE_FORFEITURES, pet) == []
    assert (held(url, pet), net(url, paid_back)) == (2_000, 0)
    assert active_receipts(url, pet) == [case["second"]]
    assert (status(url, case["first"]), status(url, case["second"])) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, case["customer"])


def test_two_forfeitures_give_back_newest_first_and_keep_part_of_the_older(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security should-fix 1): A's 5,000 and B's 5,000 fund the kept Pet Deposit
    with 4,000 of pay-back money; two one-call forfeitures of 3,000 each (owner calls) take the
    6,000 beyond it and the Settlement refunds the 4,000. A's 5,000 shortfall is given back by the
    forfeitures, newest first: the newer one in full and 2,000 of the older one, whose kept 1,000
    is forfeited again; nobody is charged and the Settlement Refund stays out; the Deposit holds
    0."""
    url = migrated_database_url
    case = kept_pet_case(url, 5_000, 5_000)
    pet = case["pet"]
    for _ in range(2):
        record_disposition_as_owner(
            case["deposits"],
            RecordDepositDispositionCommand(
                uuid4(),
                uuid4(),
                pet,
                case["lease"],
                3_000,
                case["day"],
                "Approved BR-DEP-022 source",
                context=disposition_context(url, pet),
            ),
            actor=deposit_actor(case["human"], case["prop"]),
        )
    [(older, _), (newer, _)] = rows(url, ACTIVE_FORFEITURES, pet)
    paid_back = settlement_refund_of(case)
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, case["first"]))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (plan["payback_first"], plan["shortfall_usd_cents"], plan["give_back_usd_cents"]) == (
        True,
        5_000,
        5_000,
    )
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("FORFEITURE", str(newer), 3_000, 3_000, 0),
        ("FORFEITURE", str(older), 3_000, 2_000, 1_000),
    ]
    assert source["recoveries"] == []
    result = confirm(case, draft)
    assert result["recoveries"] == []
    assert {
        value(
            url,
            "SELECT deposit_disposition_id FROM app.deposit_disposition_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        for reversal in result["forfeiture_reversal_ids"]
    } == {older, newer}
    [kept] = result["forfeiture_ids"]
    assert rows(url, ACTIVE_FORFEITURES, pet) == [(UUID(str(kept)), 1_000)]
    assert (held(url, pet), net(url, paid_back)) == (0, 4_000)
    assert active_receipts(url, pet) == [case["second"]]
    assert (status(url, case["first"]), status(url, case["second"])) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, case["customer"])


def test_the_payback_first_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-2b-1 adds no function and patches only the two listed functions, by
    exactly their listed replacements, with the same owner, privileges and settings; no constraint
    or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270101_158"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str]]:
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
                "ON n.oid=c.connamespace WHERE n.nspname='app' AND c.contype<>'t' "
                "UNION ALL SELECT 'trigger',t.tgrelid::regclass::text,t.tgname,t.tgenabled::text "
                "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, others

    with _temporary_migration_database("returned_payment_payback_first") as temporary:
        alembic_command.upgrade(config, "20270101_158")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED
    for signature, replacements in revision.module.PATCHES:
        name = str(signature)
        expected = before_functions[name][0]
        for before, after in replacements:
            assert expected.count(before) == 1
            expected = expected.replace(before, after)
        assert after_functions[name][0] == expected
        assert after_functions[name][1:] == before_functions[name][1:]
