"""Post-settlement correction: a return's money on a payment a later Refund correction changed
(sub-slice 10e-3d-2b-2).

Owner answer (a) to Q-2026-10-13-107: the money a changing correction took back out of a payment
pays out first on its Refunds (the oldest first), then on its payments (the newest first), and the
mistaken money keeps its place in that stream; so the reversal of the mistaken return charges back
the part that reached a Refund to the person who received it and makes the debt the rest paid owed
again. Owner, 2026-10-14: a return reversal's put-back keeps each part's place, with the reversed
return's money cut out.
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

from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_FIRST, PET_REST, SECURITY, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_receipt_correction_migration import confirm as confirm_receipt
from test_settlement_deposit_receipt_correction_migration import receipt_of
from test_settlement_deposit_receipt_correction_migration import record as record_receipt
from test_settlement_deposit_receipt_correction_migration import request as receipt_request
from test_settlement_deposit_refund_correction_migration import command as deposit_refund_command
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_held_value_refund_migration import return_only
from test_settlement_pet_classification_migration import command as classification
from test_settlement_pet_classification_migration import confirm as confirm_classification
from test_settlement_pet_classification_migration import record as record_classification
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import unpaid_charge
from test_settlement_refund_return_migration import (
    available,
    confirm,
    net,
    record,
    refunded_case,
    return_command,
)
from test_settlement_return_reversal_migration import (
    app_catalog,
    charge_open,
    correction_of,
)
from test_settlement_return_reversal_successor_migration import reverse
from test_settlement_returned_value_left_migration import charged_back

REVISION = "20261208_134"
PLACED = "app.settlement_returned_value_placed(uuid,text,uuid,uuid,boolean)"
FOLLOW = "app.settlement_returned_value_follow(uuid,text,uuid,text,uuid,bigint,bigint,uuid)"
PARTS = "app.settlement_returned_value_parts(uuid,text,uuid,uuid,boolean)"
SOURCE = "app.settlement_return_reversal_source_state(uuid,uuid)"
SCOPE = "app.settlement_return_reversal_refund(uuid,uuid)"
ASSERT = "app.assert_settlement_return_reversal_allowed(jsonb)"


def active_payments(url: str, credit: object) -> list[str]:
    """The Credit's applications not reversed, the oldest first."""
    [found] = one(
        url,
        "SELECT array_agg(application.id::text ORDER BY application.occurred_at,application.id) "
        "FROM app.customer_credit_applications application "
        "WHERE application.customer_credit_id=%s AND NOT EXISTS(SELECT 1 "
        "FROM app.customer_credit_application_reversals reversal "
        "WHERE reversal.credit_application_id=application.id)",
        credit,
    )
    return list(found or [])


def followed(url: str, *arguments: object) -> list[tuple[Any, ...]]:
    """Every row of the follow function: record kind, record, amount, offset, part, open kind."""
    places = ",".join(["%s"] * len(arguments))
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT follow.follow_record_kind,follow.follow_record_id::text,"
            "follow.follow_amount_usd_cents,follow.follow_offset_usd_cents,"
            "follow.follow_part_usd_cents,follow.follow_open_kind "
            f"FROM app.settlement_returned_value_follow({places}) follow",
            arguments,
        ).fetchall()


def test_a_stretch_over_a_refund_and_its_payment_written_again_is_split_between_them(
    migrated_database_url: str,
) -> None:
    """Credit form, the owner's Q-107 example shape: E brings back 1,000 (return only); S brings
    back 500 (return only) and its step lets the Credit pay a 1,500 charge (S's own 500 first, then
    E's 1,000, in one payment). A Refund correction Q then releases 800 of that payment (reversed,
    700 written again) and refunds the 800. Of the money Q took back, its Refund pays out the first
    800 and the 700 payment the rest, so E's 1,000 (from 500 to 1,500) is 300 in the Refund and
    700 in the payment. E's reversal charges 300 back to the Customer who received the Refund and
    reverses the 700 payment whole with nothing put back: 700 of the charge is owed again, together
    exactly the mistaken 1,000, and the Credit ends as before."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 1_000)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    return_only(case, refund, 500, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = active_payments(url, credit)
    released = confirm_refund(
        case, record_refund(case, refund_correction(case, charge_invoice, charge_line, 800))
    )
    [paid] = released["refunds"]
    [written_again] = active_payments(url, credit)
    assert (paid["amount_usd_cents"], outstanding(url, charge_line)) == (800, 0)
    # The follow function on its own: E's stretch of the reversed payment, from 500 for 1,000.
    assert sorted(
        followed(
            url, case["settlement"], "CREDIT", credit, "CREDIT_APPLICATION", paying, 500, 1_000
        )
    ) == sorted(
        [
            ("CREDIT_APPLICATION", written_again, 700, 0, 700, None),
            ("REFUND", str(paid["id"]), 800, 500, 300, None),
        ]
    )
    before = available(url, credit)
    source, result = reverse(case, earlier)
    assert sorted(
        (part["record_kind"], part["record_id"], part["amount_usd_cents"], part["part_usd_cents"])
        for part in source["swept"]
    ) == sorted(
        [
            ("CREDIT_APPLICATION", written_again, 700, 700),
            ("REFUND", str(paid["id"]), 800, 300),
        ]
    )
    assert source["swept_open"] == []
    [undone] = result["credit_application_reversals"]
    [recovery] = result["recoveries"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"], result["reapplied"]) == (
        written_again,
        700,
        [],
    )
    assert (str(recovery["refund_id"]), recovery["amount_usd_cents"]) == (str(paid["id"]), 300)
    assert (
        available(url, credit),
        outstanding(url, charge_line),
        charge_open(url, recovery),
        net(url, paid["id"]),
    ) == (before, 700, 300, 500)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_part_keeps_its_place_through_a_refund_correction_and_a_return_reversal(
    migrated_database_url: str,
) -> None:
    """Credit form: X1 and X1b each bring back 300 (return only); X2 brings back 900 (return only)
    and its step lets the Credit pay a 1,500 charge: X2's own 900, then X1's 300, then X1b's 300,
    in one payment. A Refund correction Q releases 300 of it (its Refund pays out the first 300 of
    what Q took back, the 1,200 payment written again the rest), so X1's 300 sits from 600 and
    X1b's from 900 in the 1,200 payment. X1's reversal reverses it whole and puts 900 back (X1's
    300 cut out). X1b's 300 keeps its place in that put-back (from 600, X1's stretch before it cut
    out), so X1b's reversal reverses the 900 put-back whole and puts 600 back: 600 of the charge
    is owed again, Q's Refund untouched, and the Credit ends as before."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    later = return_only(case, refund, 300)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    return_only(case, refund, 900, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    released = confirm_refund(
        case, record_refund(case, refund_correction(case, charge_invoice, charge_line, 300))
    )
    [paid] = released["refunds"]
    [written_again] = active_payments(url, credit)
    before = available(url, credit)
    source, result = reverse(case, first)
    [part] = source["swept"]
    assert (part["record_id"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        written_again,
        1_200,
        300,
    )
    [again] = result["reapplied"]
    assert (again["amount_usd_cents"], outstanding(url, charge_line)) == (900, 300)
    source, result = reverse(case, later)
    [moved] = source["swept"]
    assert (moved["record_id"], moved["amount_usd_cents"], moved["part_usd_cents"]) == (
        again["id"],
        900,
        300,
    )
    [undone] = result["credit_application_reversals"]
    [restored] = result["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (again["id"], 900)
    assert (restored["amount_usd_cents"], result["recoveries"]) == (600, [])
    assert (
        available(url, credit),
        outstanding(url, charge_line),
        net(url, paid["id"]),
    ) == (before, 600, 300)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_deposit_part_follows_into_the_refund_of_a_refund_correction(
    migrated_database_url: str,
) -> None:
    """Deposit form through a Refund correction of a Deposit-paid line (migration 103): E brings
    back 1,000 of the Pet Deposit Refund (return only). S brings back 500 with a new Refund: the
    Customer's other Credit pays 300 of a 1,500 charge, the Pet Deposit the other 1,200, and it
    refunds 300; S's own 500 is in its Refund and the first 200 of its payment, so E's 1,000 sits
    from 200 in the 1,200 payment. A Refund correction Q then removes the whole
    charge: both payments are reversed, the released Pet Deposit value is refunded (1,200). Of
    what Q took back from the Pet Deposit its Refund pays out all, so E's 1,000 is in that Refund:
    E's reversal charges 1,000 back to the Customer who received it, nothing is owed on the
    charge, and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    earlier = return_only(case, pet_paid, 1_000)
    _, charge_line = unpaid_charge(url, case, case["person"])
    confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                500,
                SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 1_200),
                settlement_refund(case, "pet", 300),
                pet_remainder=STAFF,
            ),
        ),
    )
    released = confirm_refund(
        case,
        record_refund(
            case,
            deposit_refund_command(case, charge_line, 1_500, settlement_refund(case, "pet", 1_200)),
        ),
    )
    [pet_refunded] = [paid for paid in released["refunds"] if paid["source_deposit_id"] == str(pet)]
    assert (pet_refunded["amount_usd_cents"], held(url, pet), outstanding(url, charge_line)) == (
        1_200,
        0,
        0,
    )
    source, result = reverse(case, earlier)
    assert [
        (part["record_kind"], part["record_id"], part["part_usd_cents"]) for part in source["swept"]
    ] == [("REFUND", str(pet_refunded["id"]), 1_000)]
    assert (source["swept_open"], result["deposit_application_reversals"]) == ([], [])
    [recovery] = result["recoveries"]
    assert (str(recovery["refund_id"]), recovery["amount_usd_cents"]) == (
        str(pet_refunded["id"]),
        1_000,
    )
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        charge_open(url, recovery),
        net(url, pet_refunded["id"]),
    ) == (0, 0, 1_000, 200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_deposit_part_follows_into_the_refund_and_payment_of_a_refund_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1 set-up (Pet Deposit, migration 103): a return-only correction lets the
    Credits pay 800 of a 1,500 charge; E brings back 1,000 of the Pet Deposit Refund (return only);
    S brings back 500 with a new Refund: the Pet Deposit pays the other 700 and refunds 800, so E's
    1,000 (from 500) is 300 in S's Refund and the whole 700 payment. A Refund correction Q of 300
    releases that 700 payment (the newest on the line), pays 400 of it again and refunds 300: of
    the 700 Q took back, its Refund pays out the first 300 and its 400 payment the rest. E's
    reversal charges back 300 of S's Refund and 300 of Q's and reverses the 400 payment whole with
    nothing put back: 400 of the charge is owed again and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    pet, credit, pet_paid = case["pet"], case["refund_credit"], pet_refund(case)
    _, charge_line = unpaid_charge(url, case, case["person"])
    return_only(
        case,
        case["refund"],
        500,
        SettlementCreditStep(credit, LINE, charge_line, 500),
        SettlementCreditStep(case["new_credit"], LINE, charge_line, 300),
    )
    earlier = return_only(case, pet_paid, 1_000)
    paid_out = confirm(
        case,
        record(
            case,
            return_command(
                case,
                pet_paid,
                500,
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 700),
                settlement_refund(case, "pet", 800),
                pet_remainder=STAFF,
            ),
        ),
    )
    [first_refund] = paid_out["refunds"]
    released = confirm_refund(
        case,
        record_refund(
            case,
            deposit_refund_command(
                case,
                charge_line,
                300,
                SettlementDepositStep(PET_REST, pet, LINE, charge_line, 400),
                settlement_refund(case, "pet", 300),
                pet_remainder=STAFF,
            ),
        ),
    )
    [second_refund] = released["refunds"]
    [paid_again] = released["deposit_applications"]
    assert (held(url, pet), outstanding(url, charge_line)) == (0, 0)
    source, result = reverse(case, earlier)
    assert sorted(
        (part["record_kind"], part["record_id"], part["part_usd_cents"]) for part in source["swept"]
    ) == sorted(
        [
            ("REFUND", str(first_refund["id"]), 300),
            ("REFUND", str(second_refund["id"]), 300),
            ("DEPOSIT_APPLICATION", str(paid_again["id"]), 400),
        ]
    )
    assert source["swept_open"] == []
    [undone] = result["deposit_application_reversals"]
    assert (undone["deposit_application_id"], undone["amount_usd_cents"], result["reapplied"]) == (
        str(paid_again["id"]),
        400,
        [],
    )
    assert sorted(
        (str(recovery["refund_id"]), recovery["amount_usd_cents"])
        for recovery in result["recoveries"]
    ) == sorted([(str(first_refund["id"]), 300), (str(second_refund["id"]), 300)])
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        net(url, first_refund["id"]),
        net(url, second_refund["id"]),
    ) == (0, 400, 500, 0)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_deposit_part_follows_into_the_payment_of_a_pet_damage_reclassification(
    migrated_database_url: str,
) -> None:
    """Review round 1 set-up (Pet Deposit, migration 105), from the two-stage test of sub-slice
    10e-3d-2a: E0, E and F bring back 300, 1,000 and 400 (return only); S1's step lets the Pet
    Deposit pay 700 of a charge at the remainder stage (E0's 300, then 400 of E's money); S2
    corrects the other Damage line to pet damage, so the Pet Deposit pays 1,000 of it at the
    pet-damage stage (E's other 600, then F's 400). Q corrects that line back to not pet damage:
    the 1,000 is reversed and paid again at the remainder stage, so E's 600 keeps its place in the
    new payment. E's reversal reverses S1's 700 and Q's 1,000 whole and puts back 300 and 400 at
    the remainder stage, S1's first: exactly 1,000 is owed again and the Pet Deposit ends empty."""
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
    confirm_classification(
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
    reclassified = confirm_classification(
        case,
        record_classification(
            case,
            classification(
                case,
                other_line,
                False,
                SettlementDepositStep(PET_REST, pet, LINE, other_line, 1_000),
                pet_remainder=STAFF,
            ),
        ),
    )
    [paid_again] = reclassified["deposit_application_ids"]
    assert (held(url, pet), outstanding(url, other_line)) == (0, 0)
    source, result = reverse(case, earlier)
    assert sorted(
        (item["record_id"], item["amount_usd_cents"], item["part_usd_cents"])
        for item in source["swept"]
    ) == sorted([(remainder_application["id"], 700, 400), (str(paid_again), 1_000, 600)])
    assert source["swept_open"] == []
    assert [
        (item["application_stage"], item["target_id"], item["amount_usd_cents"])
        for item in source["reapply"]
    ] == [
        ("PET_REMAINDER_EXPLICIT", str(charge_line), 300),
        ("PET_REMAINDER_EXPLICIT", str(other_line), 400),
    ]
    assert sorted(item["amount_usd_cents"] for item in result["deposit_application_reversals"]) == [
        700,
        1_000,
    ]
    assert result["recoveries"] == []
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        outstanding(url, other_line),
    ) == (0, 400, 600)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_part_on_a_payment_a_receipt_correction_reversed_is_charged_to_the_refund_s_recipient(
    migrated_database_url: str,
) -> None:
    """Review round 2, a change the follow function cannot follow, on the real path (Pet
    Deposit): E brings back 1,000 of the Settlement's Pet Deposit Refund (return only); S brings
    back 500 with a new Refund: the Customer's other Credit pays 300 of a 1,500 charge, the Pet
    Deposit the other 1,200, and it refunds 300, so E's 1,000 sits from 200 in S's 1,200 payment.
    The Pet Deposit's receipt is then found wrong: its DEPOSIT_RECEIPT_CORRECTION reverses every
    Deposit payment, S's included, and the receipt itself. Sub-slice 10e-3d-2c (owner answer (a)
    to Q-2026-10-13-103 point 1; renamed from `..._reversed_waits`, which expected the part to stay
    open at that payment and the reversal to be refused): the part went back into the Pet Deposit
    and out with the receipt reversal, so E's reversal charges the 1,000 to the person who
    received the returned Refund (who pays back the whole 5,400 less S's real 500 return), and
    the charge's debt stays as the receipt correction left it."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    earlier = return_only(case, pet_paid, 1_000)
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
                settlement_refund(case, "pet", 300),
                pet_remainder=STAFF,
            ),
        ),
    )
    [paying] = paid_out["deposit_applications"]
    receipt = receipt_of(url, pet)
    corrected = confirm_receipt(case, record_receipt(case, receipt_request(case, receipt)))
    assert one(
        url,
        "SELECT count(*) FROM app.deposit_application_reversals WHERE deposit_application_id=%s",
        paying["id"],
    ) == (1,)
    owed = outstanding(url, charge_line)
    charged_back(url, case, earlier, pet_paid, correction_of(corrected), 1_000, 4_900)
    assert (held(url, pet), outstanding(url, charge_line)) == (0, owed)


def test_the_follow_function_fails_closed(migrated_database_url: str) -> None:
    """Built by hand on real rows (the first test's shape: a 1,500 payment a Refund correction
    reversed, 800 refunded and 700 written again): an unknown payment, a payment of another
    source, no offset, a negative offset, no part or a part of 0, a stretch not inside the reversed
    payment, and a Settlement other than the one whose correction reversed it each stop open at the
    record; with p_until the Refund correction a stretch stops at the payment it reversed, and with
    p_until an older correction it stops open there (review round 1: the recursion reads only
    earlier corrections); an active payment holds a stretch inside it and stops open past its
    end."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 1_000)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    return_only(case, refund, 500, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = active_payments(url, credit)
    released = confirm_refund(
        case, record_refund(case, refund_correction(case, charge_invoice, charge_line, 800))
    )
    changer = released["settlement_correction"]["id"]
    [written_again] = active_payments(url, credit)
    settlement = case["settlement"]
    unknown = str(uuid4())
    for kind, record_id, offset, part in (
        ("CREDIT_APPLICATION", unknown, 0, 100),
        ("DEPOSIT_APPLICATION", paying, 0, 100),
        ("REFUND", paying, 0, 100),
        ("CREDIT_APPLICATION", paying, None, 100),
        ("CREDIT_APPLICATION", paying, -1, 100),
        ("CREDIT_APPLICATION", paying, 0, None),
        ("CREDIT_APPLICATION", paying, 0, 0),
    ):
        [(_, record_seen, _, _, _, open_kind)] = followed(
            url, settlement, "CREDIT", credit, kind, record_id, offset, part
        )
        assert (record_seen, open_kind) == (record_id, "CHANGED_APPLICATION"), (kind, offset)
    # Review round 1: a stretch not inside the reversed 1,500 payment stops open there.
    assert followed(
        url, settlement, "CREDIT", credit, "CREDIT_APPLICATION", paying, 1_400, 200
    ) == [("CREDIT_APPLICATION", paying, 1_500, 1_400, 200, "CHANGED_APPLICATION")]
    # The Refund correction belongs to this Settlement only.
    assert followed(url, uuid4(), "CREDIT", credit, "CREDIT_APPLICATION", paying, 0, 100) == [
        ("CREDIT_APPLICATION", paying, 1_500, 0, 100, "CHANGED_APPLICATION")
    ]
    # p_until: the payment the Refund correction reversed is where the stretch stops; an older
    # correction as p_until stops it open.
    assert followed(
        url, settlement, "CREDIT", credit, "CREDIT_APPLICATION", paying, 500, 100, changer
    ) == [("CREDIT_APPLICATION", paying, 1_500, 500, 100, None)]
    assert followed(
        url, settlement, "CREDIT", credit, "CREDIT_APPLICATION", paying, 500, 100, earlier
    ) == [("CREDIT_APPLICATION", paying, 1_500, 500, 100, "CHANGED_APPLICATION")]
    # Another source: the payment is not a payment of another Credit.
    assert followed(
        url, settlement, "CREDIT", uuid4(), "CREDIT_APPLICATION", written_again, 0, 100
    ) == [("CREDIT_APPLICATION", written_again, None, 0, 100, "CHANGED_APPLICATION")]
    assert followed(
        url, settlement, "CREDIT", credit, "CREDIT_APPLICATION", written_again, 600, 100
    ) == [("CREDIT_APPLICATION", written_again, 700, 600, 100, None)]
    assert followed(
        url, settlement, "CREDIT", credit, "CREDIT_APPLICATION", written_again, 650, 100
    ) == [("CREDIT_APPLICATION", written_again, 700, 650, 100, "CHANGED_APPLICATION")]


def test_the_changed_payment_functions_are_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the placed or follow function or the replaced parts function, each SECURITY
    DEFINER with the fixed search path; migration 134 adds only those two functions, replaces the
    parts function (privileges and settings kept), changes only the return reversal source, the
    recovery scope and the refusal function (each body exactly the old one with the module's
    replacements), no constraint and no trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (PLACED, FOLLOW, PARTS):
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
    assert revision is not None and revision.down_revision == "20261207_133"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_changed_payment") as temporary:
        alembic_command.upgrade(config, "20261207_133")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {PLACED, FOLLOW}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PARTS, SOURCE, SCOPE, ASSERT}
    for name in (PARTS, SOURCE, SCOPE, ASSERT):
        assert after_functions[name][1:] == before_functions[name][1:], name
    patched = dict(revision.module.PATCHES)
    assert set(patched) == {SOURCE, SCOPE, ASSERT}
    for name, replacements in patched.items():
        body = str(before_functions[name][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, name
            body = body.replace(anchor, replacement)
        assert after_functions[name][0] == body, name
