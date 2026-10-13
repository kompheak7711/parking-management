"""Post-settlement correction: a return's reversal undoes the money another correction paid out
(sub-slice 10e-3d-2a).

Owner answer (a) to Q-2026-10-13-100 point 1: when a later correction already paid out a mistaken
return's money, the reversal charges the paid-out part back to the person who received it, and
any debt that money paid becomes owed again; together exactly the mistaken amount. Inside the
correction that paid it out, the money it brought back pays out first, then its Refunds from the
source, the oldest first, then its applications, the newest first; an application part reverses
the application whole and applies the rest again. A part this sub-slice cannot undo yet is
refused with its own message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import (
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_FIRST, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    COUNTS,
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_pet_classification_migration import command as classification
from test_settlement_pet_classification_migration import confirm as confirm_classification
from test_settlement_pet_classification_migration import record as record_classification
from test_settlement_refund_correction_migration import (
    apply_credit,
    third_party_payment,
    unpaid_charge,
)
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
)
from test_settlement_return_reversal_migration import (
    NOT_AVAILABLE,
    OWN_RETURN,
    app_catalog,
    charge_open,
    confirm_reversal,
    correction_of,
    draft_source,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_value_left_migration import (
    CHANGED,
    DRAFTS,
    INCOMPLETE,
    REVERSED,
    counted,
)

REVISION = "20261204_130"
INTERNAL = (
    "app.settlement_returned_value_walk(uuid,text,uuid,uuid)",
    "app.settlement_returned_value_takes(uuid,text,uuid,uuid)",
)
REPLACED = "app.settlement_returned_value_left(uuid,text,uuid,uuid)"
PATCHED = {
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
    "app.settlement_return_reversal_refund(uuid,uuid)",
    "app.confirm_settlement_return_reversal(uuid,uuid,uuid,text)",
}
FORFEITED = "A forfeiture kept this return's money; the return cannot be reversed"
SHARED = (
    "This return's own corrections also paid out another return's money; "
    "reversing it waits for sub-slice 10e-3d-2b"
)
RENT_FIRST = (
    "A part applied again on an Invoice with Rent or Service lines would not follow the "
    "Rent-first order; reversing this return waits for the owner"
)


def linked(url: str, correction: object) -> list[str]:
    """The kinds of record linked to a correction, in the order they were linked."""
    names = (
        "deposit_application_reversal_id",
        "credit_application_reversal_id",
        "refund_correction_id",
        "deposit_application_id",
        "customer_credit_application_id",
    )
    with psycopg.connect(url) as connection:
        found = connection.execute(
            f"SELECT {','.join(names)} FROM app.settlement_correction_effects "
            "WHERE settlement_correction_id=%s ORDER BY effect_sequence",
            (correction,),
        ).fetchall()
    return [name for row in found for name, value in zip(names, row, strict=True) if value]


def test_the_owner_s_example_charges_back_the_refund_part_and_owes_the_debt_again(
    migrated_database_url: str,
) -> None:
    """The owner's Q-100 example (Pet Deposit, at 1/100 scale): X1 brings back 2,000 of the Pet
    Deposit Refund (return only). X2 brings back 500 with a new Refund: the Customer's own Credit
    pays 300 of a 1,500 charge, the Pet Deposit pays the other 1,200 and refunds 1,300. X2's
    Refund paid out X2's own 500 and 800 of X1's money, its application the other 1,200. Then X1
    turns out to be a mistake: its reversal charges 800 back to the Refund's recipient and
    reverses the 1,200 application whole (1,200 of the charge owed again), exactly the mistaken
    2,000; the Pet Deposit ends empty, every record is linked and the ledger reconciles."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid, customer = case["pet"], pet_refund(case), case["customer"]
    first = return_only(case, pet_paid, 2_000)
    _, charge_line = unpaid_charge(url, case, case["person"])
    paid_out = confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                500,
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 1_200),
                settlement_refund(case, "pet", 1_300),
                pet_remainder=STAFF,
            ),
        ),
    )
    second = correction_of(paid_out)
    [paid] = paid_out["refunds"]
    [applied] = paid_out["deposit_applications"]
    before = counted(url, case["settlement"], "DEPOSIT", pet)
    assert before == {str(first): (2_000, 2_000, 2_000, 0), str(second): (500, 500, 0, 0)}
    assert (held(url, pet), net(url, pet_paid), outstanding(url, charge_line)) == (0, 2_900, 0)
    draft = record_reversal(case, reversal_command(case, first))
    source = draft_source(url, draft)
    assert (
        source["swept_usd_cents"],
        source["swept_undone_usd_cents"],
        source["swept_open"],
        source["reapply"],
    ) == (2_000, 2_000, [], [])
    assert sorted(
        (item["record_kind"], item["record_id"], item["part_usd_cents"]) for item in source["swept"]
    ) == sorted([("DEPOSIT_APPLICATION", applied["id"], 1_200), ("REFUND", paid["id"], 800)])
    result = confirm_reversal(case, draft)
    [undone] = result["deposit_application_reversals"]
    assert (undone["deposit_application_id"], undone["amount_usd_cents"]) == (applied["id"], 1_200)
    [recovery] = result["recoveries"]
    assert (
        recovery["refund_id"],
        recovery["customer_id"],
        recovery["amount_usd_cents"],
        recovery["charge"],
    ) == (paid["id"], str(customer), 800, "EXTRA_CHARGE")
    assert (result["credit_application_reversals"], result["reapplied"]) == ([], [])
    assert linked(url, correction_of(result)) == [
        "deposit_application_reversal_id",
        "refund_correction_id",
        "refund_correction_id",
    ]
    assert (
        held(url, pet),
        net(url, pet_paid),
        net(url, paid["id"]),
        outstanding(url, charge_line),
        charge_open(url, recovery),
        available(url, case["new_credit"]),
    ) == (0, 4_900, 500, 1_200, 800, 0)
    # The reversal paid out exactly what it brought back, so the count does not change.
    assert counted(url, case["settlement"], "DEPOSIT", pet) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_an_application_with_other_money_on_each_side_is_applied_again(
    migrated_database_url: str,
) -> None:
    """Credit form: X1 and X1b each bring back 300 (return only); X2 brings back 900 (return only)
    and its step lets the Credit pay a 1,500 charge in full: X2's own 900 first, then X1's 300,
    then X1b's 300, all in that one application. X1's reversal reverses the application whole and
    applies 1,200 of the same Credit to the same charge again, so 300 of it is owed again and the
    Credit ends empty. Sub-slice 10e-3d-2b-1a (owner answer (a) to Q-2026-10-13-100 point 1):
    X1b's 300 is in that 1,200 put-back, so X1b's reversal reverses the put-back whole and applies
    900 again (before, it waited for sub-slice 10e-3d-2b): 600 of the charge is owed again."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    later = return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    second = return_only(case, refund, 900, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (300, 300, 300, 0),
        str(later): (300, 300, 300, 0),
        str(second): (900, 900, 0, 0),
    }
    assert (available(url, credit), net(url, refund), outstanding(url, charge_line)) == (0, 500, 0)
    draft = record_reversal(case, reversal_command(case, first))
    [part] = draft_source(url, draft)["swept"]
    assert (part["record_kind"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        "CREDIT_APPLICATION",
        1_500,
        300,
    )
    result = confirm_reversal(case, draft)
    [undone] = result["credit_application_reversals"]
    [again] = result["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (
        part["record_id"],
        1_500,
    )
    assert (again["source_kind"], again["customer_credit_id"], again["amount_usd_cents"]) == (
        "CREDIT",
        str(credit),
        1_200,
    )
    assert (available(url, credit), net(url, refund), outstanding(url, charge_line)) == (
        0,
        800,
        300,
    )
    # Sub-slice 10e-3d-2b-1a: X1b's part follows to X1's put-back.
    follow = record_reversal(case, reversal_command(case, later))
    [moved] = draft_source(url, follow)["swept"]
    assert (moved["record_id"], moved["amount_usd_cents"], moved["part_usd_cents"]) == (
        again["id"],
        1_200,
        300,
    )
    second_result = confirm_reversal(case, follow)
    assert [
        (item["credit_application_id"], item["amount_usd_cents"])
        for item in second_result["credit_application_reversals"]
    ] == [(again["id"], 1_200)]
    assert [item["amount_usd_cents"] for item in second_result["reapplied"]] == [900]
    assert (available(url, credit), net(url, refund), outstanding(url, charge_line)) == (
        0,
        1_100,
        600,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_two_applications_are_each_applied_again(migrated_database_url: str) -> None:
    """Deposit form, two parts applied again in one reversal: E and F each bring back 1,000 of the
    Pet Deposit Refund (return only); then two charges of 1,500 are issued, and the Customer's 300
    of new Credit pays 150 of each (ordinary spending). S brings back 1,000 with a new Refund: the
    Pet Deposit pays 1,350 of each charge and refunds the 300 left. S's draw (3,000: its Refund,
    then its applications, the newest first): its own 1,000 covers the Refund and 700 of the newer
    application, E's 1,000 the other 650 of it and 350 of the older one, F's 1,000 the rest. E's
    reversal reverses both applications whole and applies again what was not E's money (700 and
    1,000), so exactly 1,000 is owed again and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    earlier = return_only(case, pet_paid, 1_000)
    return_only(case, pet_paid, 1_000)
    first_invoice, first_line = unpaid_charge(url, case, case["person"])
    second_invoice, second_line = unpaid_charge(url, case, case["person"])
    apply_credit(case, case["new_credit"], first_invoice, first_line, 150)
    apply_credit(case, case["new_credit"], second_invoice, second_line, 150)
    confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                1_000,
                SettlementDepositStep(PET_REST, pet, LINE, first_line, 1_350),
                SettlementDepositStep(PET_REST, pet, LINE, second_line, 1_350),
                settlement_refund(case, "pet", 300),
                pet_remainder=STAFF,
            ),
        ),
    )
    assert (held(url, pet), outstanding(url, first_line), outstanding(url, second_line)) == (
        0,
        0,
        0,
    )
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    assert sorted(item["part_usd_cents"] for item in source["swept"]) == [350, 650]
    assert sorted(item["amount_usd_cents"] for item in source["reapply"]) == [700, 1_000]
    result = confirm_reversal(case, draft)
    assert sorted(item["amount_usd_cents"] for item in result["deposit_application_reversals"]) == [
        1_350,
        1_350,
    ]
    assert sorted(
        (item["deposit_id"], item["amount_usd_cents"]) for item in result["reapplied"]
    ) == [(str(pet), 700), (str(pet), 1_000)]
    assert result["recoveries"] == []
    assert (held(url, pet), outstanding(url, first_line) + outstanding(url, second_line)) == (
        0,
        1_000,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_parts_applied_again_at_two_stages_follow_the_dl_032_order(
    migrated_database_url: str,
) -> None:
    """Review round 2, on the real path (Pet Deposit, two DL-032 stages): E0, E and F bring back
    300, 1,000 and 400 of the Pet Deposit Refund (each return only). S1 brings back 500 of a
    correction's Credit Refund (return only): the returned Credit and the Customer's other Credit
    pay 800 of a 1,500 charge and the Pet Deposit the other 700 at the remainder stage (E0's 300,
    then 400 of E's money); the Pet Deposit keeps 1,000 (no debt is open). S2 corrects the other
    Damage line to pet damage: its Security Deposit application is reversed, the Pet Deposit pays
    1,000 of it at the pet-damage stage (E's other 600, then F's 400), the Security Deposit the
    rest, and the Security Deposit's last 1,000 is refunded. E's reversal reverses both
    applications whole and applies again 400 at the pet-damage stage first and then 300 at the
    remainder stage, although S1's application is the older one (time order would break the
    DL-032 order of the reversal's own applications): exactly 1,000 is owed again and the Pet
    Deposit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    pet, security, credit = case["pet"], case["security"], case["refund_credit"]
    pet_paid, other_line = pet_refund(case), case["other_line"]
    return_only(case, pet_paid, 300)
    earlier = return_only(case, pet_paid, 1_000)
    return_only(case, pet_paid, 400)
    _, charge_line = unpaid_charge(url, case, case["person"])
    remainder = confirm(
        case,
        record(
            case,
            return_command(
                case,
                case["refund"],
                500,
                SettlementCreditStep(credit, LINE, charge_line, 500),
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 700),
                new=False,
                pet_remainder=STAFF,
            ),
        ),
    )
    [remainder_application] = remainder["deposit_applications"]
    assert (held(url, pet), outstanding(url, charge_line)) == (1_000, 0)
    pet_damage = confirm_classification(
        case,
        record_classification(
            case,
            classification(
                case,
                other_line,
                True,
                SettlementDepositStep(PET_FIRST, pet, LINE, other_line, 1_000),
                SettlementDepositStep(SECURITY, security, LINE, other_line, 9_000),
                settlement_refund(case, "security", 1_000),
            ),
        ),
    )
    [pet_damage_application, _] = pet_damage["deposit_application_ids"]
    assert (held(url, pet), held(url, security), outstanding(url, other_line)) == (0, 0, 0)
    assert counted(url, case["settlement"], "DEPOSIT", pet)[str(earlier)] == (
        1_000,
        1_000,
        1_000,
        0,
    )
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    assert sorted(
        (item["record_id"], item["amount_usd_cents"], item["part_usd_cents"])
        for item in source["swept"]
    ) == sorted(
        [
            (remainder_application["id"], 700, 400),
            (str(pet_damage_application), 1_000, 600),
        ]
    )
    assert [
        (item["application_stage"], item["target_id"], item["amount_usd_cents"])
        for item in source["reapply"]
    ] == [
        ("PET_RELATED_FIRST", str(other_line), 400),
        ("PET_REMAINDER_EXPLICIT", str(charge_line), 300),
    ]
    result = confirm_reversal(case, draft)
    assert sorted(item["amount_usd_cents"] for item in result["deposit_application_reversals"]) == [
        700,
        1_000,
    ]
    # Written in the stage order, as listed.
    assert [
        (item["deposit_id"], item["application_stage"], item["amount_usd_cents"])
        for item in result["reapplied"]
    ] == [(str(pet), "PET_RELATED_FIRST", 400), (str(pet), "PET_REMAINDER_EXPLICIT", 300)]
    assert result["recoveries"] == []
    assert (
        held(url, pet),
        outstanding(url, other_line),
        outstanding(url, charge_line),
        net(url, pet_paid),
    ) == (0, 600, 400, 4_700)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_refund_part_with_its_own_return_is_refused(migrated_database_url: str) -> None:
    """X1 brings back 1,000 (return only); X2 brings back 500 with a new Refund of all 1,500 the
    Pet Deposit holds, so 1,000 of X2's Refund is X1's money. When 100 of X2's Refund comes back
    too, X1's reversal is refused (reverse that return first) and writes nothing."""
    url = migrated_database_url
    case = refunded_case(url)
    pet = case["pet"]
    first = return_only(case, pet_refund(case), 1_000)
    paid_out = confirm(
        case,
        record(
            case,
            return_command(case, pet_refund(case), 500, settlement_refund(case, "pet", 1_500)),
        ),
    )
    [paid] = paid_out["refunds"]
    return_only(case, paid["id"], 100)
    assert held(url, pet) == 100
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_reversal(case, reversal_command(case, first))
    assert cause(refused) == ("55000", OWN_RETURN)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged


def test_the_own_uses_and_another_correction_s_use_are_undone_together(
    migrated_database_url: str,
) -> None:
    """Review round 1, the own uses' part below the returned amount on the real path: E brings
    back 1,700 (return only) and its own step lets the Credit pay a 1,500 charge, so E keeps 200.
    A third party pays 1,000 of a second charge; S brings back 300 (return only) and its step lets
    the Credit pay the other 500: S's own 300, then E's 200. E's reversal reverses its own 1,500
    application whole (its own uses used 1,500 of E's money, not 1,700) and S's 500 application
    whole, applying 300 of it again: exactly 1,700 is owed again."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    _, first_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(
        case, refund, 1_700, SettlementCreditStep(credit, LINE, first_line, 1_500)
    )
    second_invoice, second_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, second_invoice, second_line, 1_000)
    return_only(case, refund, 300, SettlementCreditStep(credit, LINE, second_line, 500))
    assert counted(url, case["settlement"], "CREDIT", credit)[str(earlier)] == (
        1_700,
        1_700,
        200,
        0,
    )
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    [part] = source["swept"]
    assert (source["swept_usd_cents"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        200,
        500,
        200,
    )
    result = confirm_reversal(case, draft)
    assert sorted(item["amount_usd_cents"] for item in result["credit_application_reversals"]) == [
        500,
        1_500,
    ]
    [again] = result["reapplied"]
    assert (again["customer_credit_id"], again["amount_usd_cents"]) == (str(credit), 300)
    assert (
        available(url, credit),
        outstanding(url, first_line),
        outstanding(url, second_line),
        net(url, refund),
    ) == (0, 1_500, 200, 1_700)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_own_corrections_that_also_took_another_return_s_money_are_undone_per_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1: E0 brings back 300 (return only); E brings back 1,700 (return only) and its
    own step lets the Credit pay a 1,500 charge, so E keeps 200. A third party pays 1,200 of a
    second charge; a held-value Refund H names E: its step lets the Credit pay the other 300 and
    it refunds E's 200, so H paid out E's 200 and E0's 300. Sub-slice 10e-3d-2b-1b (owner answer
    (a) to Q-2026-10-13-100 point 1; this reversal waited before): the walk places E's money per
    correction, E's 1,500 on its own application and H's take of 200 on H's Refund, so E's
    reversal reverses the 1,500 application whole and charges the 200 Refund back, while H's 300
    payment, E0's money, stays: exactly 1,700 comes back."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    return_only(case, refund, 300)
    _, first_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(
        case, refund, 1_700, SettlementCreditStep(credit, LINE, first_line, 1_500)
    )
    second_invoice, second_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, second_invoice, second_line, 1_200)
    pays_debt = SettlementCreditStep(credit, LINE, second_line, 300)
    holding = confirm_held(case, record_held(case, held_command(case, earlier, pays_debt)))
    [paid] = holding["refunds"]
    assert (paid["amount_usd_cents"], available(url, credit)) == (200, 0)
    [paying] = one(
        url,
        "SELECT array_agg(id::text ORDER BY occurred_at,id) "
        "FROM app.customer_credit_applications WHERE customer_credit_id=%s",
        credit,
    )
    [own_payment, _] = paying
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    assert (source["shared_with_other_returns"], source["swept"], source["own_open"]) == (
        True,
        [],
        [],
    )
    assert sorted(
        (
            part["settlement_correction_id"],
            part["record_kind"],
            part["record_id"],
            part["amount_usd_cents"],
            part["part_usd_cents"],
        )
        for part in source["own_parts"]
    ) == sorted(
        [
            (str(earlier), "CREDIT_APPLICATION", own_payment, 1_500, 1_500),
            (str(correction_of(holding)), "REFUND", paid["id"], 200, 200),
        ]
    )
    result = confirm_reversal(case, draft)
    [undone] = result["credit_application_reversals"]
    [recovery] = result["recoveries"]
    assert (
        undone["credit_application_id"],
        undone["amount_usd_cents"],
        recovery["refund_id"],
        recovery["amount_usd_cents"],
        result["reapplied"],
    ) == (own_payment, 1_500, paid["id"], 200, [])
    assert (
        available(url, credit),
        outstanding(url, first_line),
        outstanding(url, second_line),
        charge_open(url, recovery),
        net(url, refund),
    ) == (0, 1_500, 0, 200, 1_700)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_an_own_part_and_another_correction_s_part_are_each_applied_again(
    migrated_database_url: str,
) -> None:
    """Review round 2, on the real path (Credit form): E brings back 1,000 and then E0 300 (each
    return only, no step). A third party pays 1,000 of a 1,500 charge A; S brings back 300
    (return only) and its step lets the Credit pay the other 500 of A: S's own 300, then 200 of
    E's money (E is the older return). A third party pays 500 of a 1,500 charge B; a held-value
    Refund H names E (800 left): its step lets the Credit pay the other 1,000 of B and it refunds
    the 100 the Credit still holds, so H paid out E's 800 and E0's 300. H is the only own
    correction of E with records, so the flag stays false. E's reversal charges H's Refund back
    (100), reverses H's 1,000 and S's 500 applications whole and applies again 300 of each (E0's
    money in H's, S's own money in S's, the older application first): exactly 1,000 is owed
    again and the Credit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    earlier = return_only(case, refund, 1_000)
    other = return_only(case, refund, 300)
    first_invoice, first_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, first_invoice, first_line, 1_000)
    sweeping = return_only(case, refund, 300, SettlementCreditStep(credit, LINE, first_line, 500))
    second_invoice, second_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, second_invoice, second_line, 500)
    pays_debt = SettlementCreditStep(credit, LINE, second_line, 1_000)
    [paid] = confirm_held(case, record_held(case, held_command(case, earlier, pays_debt)))[
        "refunds"
    ]
    assert (paid["amount_usd_cents"], available(url, credit)) == (100, 0)
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(earlier): (1_000, 1_000, 200, 0),
        str(other): (300, 300, 300, 0),
        str(sweeping): (300, 300, 0, 0),
    }
    draft = record_reversal(case, reversal_command(case, earlier))
    source = draft_source(url, draft)
    [part] = source["swept"]
    assert (
        source["shared_with_other_returns"],
        source["swept_usd_cents"],
        part["amount_usd_cents"],
        part["part_usd_cents"],
    ) == (False, 200, 500, 200)
    assert [
        (item["application_id"] == part["record_id"], item["amount_usd_cents"])
        for item in source["reapply"]
    ] == [(True, 300), (False, 300)]
    result = confirm_reversal(case, draft)
    assert sorted(item["amount_usd_cents"] for item in result["credit_application_reversals"]) == [
        500,
        1_000,
    ]
    assert [
        (item["customer_credit_id"], item["amount_usd_cents"]) for item in result["reapplied"]
    ] == [
        (str(credit), 300),
        (str(credit), 300),
    ]
    [recovery] = result["recoveries"]
    assert (recovery["refund_id"], recovery["customer_id"], recovery["amount_usd_cents"]) == (
        paid["id"],
        str(customer),
        100,
    )
    assert (
        available(url, credit),
        outstanding(url, first_line),
        outstanding(url, second_line),
        charge_open(url, recovery),
        net(url, refund),
    ) == (0, 200, 700, 100, 1_400)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_part_applied_again_on_a_newer_rent_invoice_application_waits(
    migrated_database_url: str,
) -> None:
    """Review round 1, on the refusal function with built sources on the Initial Invoice (it has
    a Rent line): another correction's two Credit applications on that Invoice paid out a 1,300
    return. When the rest of the newer one would be applied again without a Customer designation
    while the older one is reversed too, the Rent-first proposal would refuse it at the confirm,
    so it waits for the owner (Q-2026-10-13-104); applying again the rest of the older one, or a
    designated part, passes."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    invoice = str(case["initial"])
    credit, newer, older = (str(uuid4()) for _ in range(3))

    def built(reapplied: str, newer_part: int, older_part: int) -> dict[str, Any]:
        parts = {newer: (1_000, newer_part), older: (500, older_part)}
        return {
            "earlier": {
                "amount_usd_cents": 1_300,
                "reversed": False,
                "customer_credit_id": credit,
                "deposit_id": None,
            },
            "credit_applications": [
                {
                    "id": application,
                    "customer_credit_id": credit,
                    "invoice_id": invoice,
                    "late_payment_charge_id": None,
                    "amount_usd_cents": amount,
                }
                for application, (amount, _) in parts.items()
            ],
            "deposit_applications": [],
            "recoveries": [],
            "source": {"value_usd_cents": 0},
            "uses": {"applied_usd_cents": 0, "refunded_usd_cents": 0, "returned_refunds": 0},
            "reapply": [
                {
                    "source_kind": "CREDIT",
                    "application_id": reapplied,
                    "amount_usd_cents": parts[reapplied][0] - parts[reapplied][1],
                    "customer_credit_id": credit,
                    "target_kind": "INVOICE_LINE",
                    "target_id": str(uuid4()),
                    "customer_designation": None,
                }
            ],
            "swept_usd_cents": 1_300,
            "left_usd_cents": 0,
            "swept_undone_usd_cents": 1_300,
            "swept": [
                {
                    "record_kind": "CREDIT_APPLICATION",
                    "record_id": application,
                    "amount_usd_cents": amount,
                    "part_usd_cents": part,
                }
                for application, (amount, part) in parts.items()
            ],
            "swept_open": [],
            "shared_with_other_returns": False,
            "own_parts": None,
            "own_open": None,
        }

    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    newer_again = built(newer, 800, 500)
    designated = {
        **newer_again,
        "reapply": [{**newer_again["reapply"][0], "customer_designation": "Customer letter"}],
    }
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(built(older, 1_000, 300)),))
        connection.execute(check, (Jsonb(designated),))
    with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(newer_again),))
    assert (refused.value.sqlstate, refused.value.diag.message_primary) == ("55000", RENT_FIRST)


def test_the_swept_parts_fail_closed(migrated_database_url: str) -> None:
    """On the refusal function with a built source (the Credit form: 1,000 returned, all of it
    paid out by another correction: 800 of a 1,100 application, whose other 300 is applied
    again, and 200 of a Refund): it passes; the parts must add up and be listed exactly, else the
    source is incomplete; each part the reversal cannot undo yet has its own message. Review
    round 2: the flag of own corrections that also took another return's money must be there as
    true or false."""
    url = migrated_database_url
    credit, application, refund, line = (str(uuid4()) for _ in range(4))
    source: dict[str, Any] = {
        "earlier": {
            "amount_usd_cents": 1_000,
            "reversed": False,
            "customer_credit_id": credit,
            "deposit_id": None,
        },
        "credit_applications": [
            {
                "id": application,
                "customer_credit_id": credit,
                "late_payment_charge_id": None,
                "amount_usd_cents": 1_100,
            }
        ],
        "deposit_applications": [],
        "recoveries": [
            {"refund_id": refund, "amount_usd_cents": 200, "net_usd_cents": 500, "returns": 0}
        ],
        "source": {"value_usd_cents": 0},
        "uses": {"applied_usd_cents": 0, "refunded_usd_cents": 0, "returned_refunds": 0},
        "reapply": [
            {
                "source_kind": "CREDIT",
                "application_id": application,
                "amount_usd_cents": 300,
                "customer_credit_id": credit,
                "target_kind": "INVOICE_LINE",
                "target_id": line,
                "customer_designation": None,
            }
        ],
        "swept_usd_cents": 1_000,
        "left_usd_cents": 0,
        "swept_undone_usd_cents": 1_000,
        "swept": [
            {
                "record_kind": "CREDIT_APPLICATION",
                "record_id": application,
                "amount_usd_cents": 1_100,
                "part_usd_cents": 800,
            },
            {
                "record_kind": "REFUND",
                "record_id": refund,
                "amount_usd_cents": 500,
                "part_usd_cents": 200,
            },
        ],
        "swept_open": [],
        "shared_with_other_returns": False,
        "own_parts": None,
        "own_open": None,
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
    [application_part, refund_part] = source["swept"]
    [recovery] = source["recoveries"]
    [entry] = source["reapply"]

    def opened(kind: str) -> dict[str, Any]:
        part = {"kind": kind, "record_kind": kind, "record_id": str(uuid4()), "part_usd_cents": 5}
        return {**source, "swept_usd_cents": 1_005, "swept_open": [part]}

    for built, message in (
        ({**source, "swept_usd_cents": 999}, INCOMPLETE),
        ({**source, "swept_undone_usd_cents": 900, "swept_usd_cents": 900}, INCOMPLETE),
        ({key: item for key, item in source.items() if key != "swept"}, INCOMPLETE),
        ({key: item for key, item in source.items() if key != "swept_open"}, INCOMPLETE),
        (
            {key: item for key, item in source.items() if key != "swept_undone_usd_cents"},
            INCOMPLETE,
        ),
        ({**source, "swept": [application_part, {**refund_part, "part_usd_cents": 0}]}, INCOMPLETE),
        ({**source, "recoveries": [{**recovery, "amount_usd_cents": 100}]}, INCOMPLETE),
        ({**source, "recoveries": [{**recovery, "net_usd_cents": 150}]}, INCOMPLETE),
        ({**source, "recoveries": []}, INCOMPLETE),
        ({**source, "reapply": []}, INCOMPLETE),
        ({**source, "reapply": [{**entry, "amount_usd_cents": 200}]}, INCOMPLETE),
        (
            {
                **source,
                "credit_applications": [
                    {**source["credit_applications"][0], "amount_usd_cents": 1_000}
                ],
            },
            INCOMPLETE,
        ),
        (
            {**source, "swept": [{**application_part, "record_kind": "PAYMENT"}, refund_part]},
            INCOMPLETE,
        ),
        (opened("CHANGED_APPLICATION"), CHANGED),
        (opened("CREDIT_REVERSAL"), REVERSED),
        (opened("RECEIPT_REVERSAL"), REVERSED),
        (opened("FORFEITURE"), FORFEITED),
        (opened("RETURN_REVERSAL"), NOT_AVAILABLE),
        (opened("CHANGED_REFUND"), NOT_AVAILABLE),
        ({**source, "left_usd_cents": -1}, NOT_AVAILABLE),
        ({**source, "shared_with_other_returns": True}, SHARED),
        # Review round 2: the flag must be there as true or false.
        (
            {key: item for key, item in source.items() if key != "shared_with_other_returns"},
            INCOMPLETE,
        ),
        ({**source, "shared_with_other_returns": None}, INCOMPLETE),
        ({**source, "shared_with_other_returns": "false"}, INCOMPLETE),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), built


def test_the_swept_parts_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the walk, the takes or the count, each SECURITY DEFINER with the fixed search
    path; migration 130 adds only the walk and the takes, replaces only the count (privileges and
    settings kept), changes only the four listed functions (each patched body is exactly the old
    one with the module's replacements), no constraint and no trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (*INTERNAL, REPLACED):
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
    assert revision is not None and revision.down_revision == "20261203_129"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_swept") as temporary:
        alembic_command.upgrade(config, "20261203_129")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED | {REPLACED}
    for name in (*PATCHED, REPLACED):
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
