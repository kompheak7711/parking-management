"""Post-settlement correction: every correction's use of returned money counts (sub-slice 10e-3d-1).

Owner answer (a) to Q-2026-10-12-97 and its detail of 2026-10-13: when a later correction's DL-032
step uses a Credit or Deposit, that use counts against the held money of the earlier return-only
corrections of that source (a correction's own return first, then the earlier correction it names,
then the other returns, oldest first), so their left values go down. Only uses made by corrections
count (ordinary Credit spending stays the known limit of owner answer 2 to Q-2026-10-09-63). A
reversal of an earlier return takes only that return's own left value. Sub-slice 10e-3d-2a (owner
answer (a) to Q-2026-10-13-100 point 1): when another correction paid out its money, the reversal
also undoes that payout (a Refund part charged back, an application part owed again); a payout it
cannot undo yet is refused with its own message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from property_rental.final_settlement import FinalSettlementConflictError, SettlementCreditStep
from test_final_settlement_draft_migration import LINE
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_deposit_receipt_correction_migration import confirm as confirm_receipt
from test_settlement_deposit_receipt_correction_migration import receipt_of
from test_settlement_deposit_receipt_correction_migration import record as record_receipt
from test_settlement_deposit_receipt_correction_migration import request as receipt_request
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import approving, cause, corrections
from test_settlement_held_value_refund_migration import (
    COUNTS,
    CREDIT_EMPTY,
    NOTHING_LEFT,
    confirm_held,
    credit_left,
    deposit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import (
    apply_credit,
    third_party_payment,
    unpaid_charge,
)
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import record as record_refund_correction
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
    app_catalog,
    confirm_reversal,
    correction_of,
    draft_source,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_payment_migration import closed_case, credit_payment
from test_settlement_returned_payment_migration import command as returned_command
from test_settlement_returned_payment_migration import confirm as confirm_returned
from test_settlement_returned_payment_migration import record as record_returned

REVISION = "20261203_129"
INTERNAL = ("app.settlement_returned_value_left(uuid,text,uuid,uuid)",)
PATCHED = {
    "app.settlement_held_deposit_value(uuid,uuid)",
    "app.settlement_held_credit_value(uuid,uuid,uuid)",
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
}
# Sub-slice 10e-3d-2a: the payouts of returned money a reversal cannot undo yet.
CHANGED = (
    "A later correction changed a payment made with this return's money in a way this reversal "
    "cannot follow yet; reversing it waits for the owner"
)
REVERSED = (
    "A Credit reversal or a Deposit receipt reversal paid out this return's money; "
    "reversing it waits for sub-slice 10e-3d-2c"
)
INCOMPLETE = "The return reversal source is incomplete"
DRAFTS = "SELECT count(*) FROM app.financial_drafts"


def counted(url: str, settlement: object, kind: str, source: object) -> dict[str, tuple[int, ...]]:
    """The count of each correction with a return into the source: returned, used, swept, left."""
    with psycopg.connect(url) as connection:
        found = connection.execute(
            "SELECT settlement_correction_id,returned_usd_cents,used_usd_cents,swept_usd_cents,"
            "left_usd_cents FROM app.settlement_returned_value_left(%s,%s,%s,NULL)",
            (settlement, kind, source),
        ).fetchall()
    return {str(row[0]): (int(row[1]), int(row[2]), int(row[3]), int(row[4])) for row in found}


def test_a_sweep_counts_against_the_earlier_return_and_its_reversal_charges_it_back(
    migrated_database_url: str,
) -> None:
    """The Q-97 case (Pet Deposit, at 1/100 scale): X1 brings back 1,000 (return only); X2 brings
    back 500 with a new Refund, which by BR-SETTLE-008 refunds all 1,500 the Pet Deposit holds:
    X2's own 500 first, then X1's 1,000. X1 then has nothing left, so a held-value Refund naming it
    is refused and writes nothing. Sub-slice 10e-3d-2a (owner answer (a) to Q-2026-10-13-100 point
    1): X1's reversal charges the 1,000 of X2's Refund that was X1's money back to the person who
    received it, so the Pet Deposit stays empty and X2's Refund keeps 500. X2's own reversal is
    not blocked: its uses took its own return first."""
    url = migrated_database_url
    case = refunded_case(url)
    pet = case["pet"]
    first = return_only(case, pet_refund(case), 1_000)
    assert (held(url, pet), deposit_left(url, first, pet)) == (1_000, 1_000)
    paid_out = confirm(
        case,
        record(
            case,
            return_command(case, pet_refund(case), 500, settlement_refund(case, "pet", 1_500)),
        ),
    )
    second = correction_of(paid_out)
    [paid] = paid_out["refunds"]
    assert counted(url, case["settlement"], "DEPOSIT", pet) == {
        str(first): (1_000, 1_000, 1_000, 0),
        str(second): (500, 500, 0, 0),
    }
    assert (held(url, pet), deposit_left(url, first, pet), deposit_left(url, second, pet)) == (
        0,
        0,
        0,
    )
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as nothing:
        record_held(case, held_command(case, first, settlement_refund(case, "pet", 1_000)))
    assert cause(nothing) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == before
    result = confirm_reversal(case, record_reversal(case, reversal_command(case, first)))
    [recovery] = result["recoveries"]
    assert (recovery["refund_id"], recovery["customer_id"], recovery["amount_usd_cents"]) == (
        paid["id"],
        paid["recipient_customer_id"],
        1_000,
    )
    assert (held(url, pet), net(url, paid["id"])) == (0, 500)
    own = record_reversal(case, reversal_command(case, second))
    assert draft_source(url, own)["swept_usd_cents"] == 0


def test_a_part_applied_again_counts_against_the_return_whose_money_it_is(
    migrated_database_url: str,
) -> None:
    """The Q-96 case (Credit, at 1/100 scale): X1 brings back 300 (return only); X2 brings back
    1,700 with a new Refund, and the Credit pays 1,500 of a charge and refunds 500: X2's own 1,700
    first, then X1's 300, so X1 has nothing left and a held-value Refund naming it is refused. X2's
    reversal applies 300 again (sub-slice 10e-3c); that part is X1's money, which X2 already used,
    so the count does not change: X1 still has nothing left. Sub-slice 10e-3d-2b-1a (owner answer
    (a) to Q-2026-10-13-100 point 1): X1's money sat in the application X2's reversal changed, and
    X2's reversal put exactly that 300 back, so X1's reversal reverses that put-back whole and the
    charge owes all 1,500 again (before, X1's reversal waited for sub-slice 10e-3d-2b)."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    pays_debt = SettlementCreditStep(credit, LINE, charge_line, 1_500)
    second = correction_of(
        confirm(case, record(case, return_command(case, refund, 1_700, pays_debt)))
    )
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (300, 300, 300, 0),
        str(second): (1_700, 1_700, 0, 0),
    }
    assert (available(url, credit), credit_left(url, first, credit)) == (0, 0)
    before = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as nothing:
        record_held(case, held_command(case, first))
    assert cause(nothing) == ("55000", NOTHING_LEFT)
    assert one(url, COUNTS) == before
    result = confirm_reversal(case, record_reversal(case, reversal_command(case, second)))
    assert [item["amount_usd_cents"] for item in result["reapplied"]] == [300]
    assert (available(url, credit), outstanding(url, charge_line)) == (0, 1_200)
    # Each correction counts what it did at its own time: X2's uses took its own return and X1's
    # 300; its reversal paid out exactly what it brought back (the 1,500 application and the 500
    # Refund back, the 1,700 return reversed and 300 applied again), so it takes nothing more.
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (300, 300, 300, 0),
        str(second): (1_700, 1_700, 0, 0),
    }
    assert credit_left(url, first, credit) == 0
    # Sub-slice 10e-3d-2b-1a: X1's part follows to the put-back of X2's reversal.
    [put_back] = result["reapplied"]
    draft = record_reversal(case, reversal_command(case, first))
    [part] = draft_source(url, draft)["swept"]
    assert (part["record_id"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        put_back["id"],
        300,
        300,
    )
    undone = confirm_reversal(case, draft)
    assert [item["credit_application_id"] for item in undone["credit_application_reversals"]] == [
        put_back["id"]
    ]
    assert undone["reapplied"] == []
    assert (available(url, credit), outstanding(url, charge_line), net(url, refund)) == (
        0,
        1_500,
        2_000,
    )


def test_released_money_and_ordinary_credit_spending_are_not_counted(
    migrated_database_url: str,
) -> None:
    """Only uses made by corrections count (owner answer 2 to Q-2026-10-09-63 stays the known
    limit): an ordinary Credit application of 1,500 lowers what the Credit holds (1,800 to 300),
    not what the return-only correction has left. Review round 1: a REFUND correction of 500 on
    that line releases the application (reversed whole, its 1,000 rest written again) and refunds
    the released 500; it pays out only the money it released, so the return still has 1,800 left
    and nothing swept. Its reversal is refused because the Credit no longer holds the returned
    value, not because another correction paid it out. When an ordinary application spends the
    last 300, a held-value Refund naming the return is refused because the Credit holds nothing."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 1_800)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    apply_credit(case, credit, charge_invoice, charge_line, 1_500)
    assert (available(url, credit), credit_left(url, first, credit)) == (300, 1_800)
    result = cast(
        dict[str, Any],
        corrections().confirm_refund(
            case["prop"],
            record_refund_correction(
                case, refund_correction(case, charge_invoice, charge_line, 500)
            ),
            actor=approving(case["person"], case["prop"]),
        ),
    )
    [paid] = result["refunds"]
    assert (paid["source_customer_credit_id"], paid["amount_usd_cents"]) == (str(credit), 500)
    assert (available(url, credit), outstanding(url, charge_line)) == (300, 0)
    assert counted(url, case["settlement"], "CREDIT", credit) == {str(first): (1_800, 0, 0, 1_800)}
    assert credit_left(url, first, credit) == 1_800
    with pytest.raises(FinalSettlementConflictError) as spent:
        record_reversal(case, reversal_command(case, first))
    assert cause(spent) == ("55000", NOT_AVAILABLE)
    other_invoice, other_line = unpaid_charge(url, case, case["person"])
    apply_credit(case, credit, other_invoice, other_line, 300)
    unchanged = one(url, COUNTS)
    with pytest.raises(FinalSettlementConflictError) as empty:
        record_held(case, held_command(case, first))
    assert cause(empty) == ("55000", CREDIT_EMPTY)
    assert one(url, COUNTS) == unchanged


def test_a_named_return_is_used_first_and_then_the_oldest_return(
    migrated_database_url: str,
) -> None:
    """Review round 1: three return-only corrections bring back 300 (X0), 400 (X1) and 200 (X2)
    into the Credit (900 held). A third party pays 1,000 of a 1,500 charge, so the Customer owes
    500. A held-value Refund naming X2 lets the Credit pay the 500 and refunds 200: it uses X2's
    200 first (the return it names), then the other returns oldest first, X0's 300 and 200 of
    X1's 400, so X1 keeps 200."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    oldest = return_only(case, refund, 300)
    middle = return_only(case, refund, 400)
    named = return_only(case, refund, 200)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, charge_invoice, charge_line, 1_000)
    assert (available(url, credit), outstanding(url, charge_line)) == (900, 500)
    pays_debt = SettlementCreditStep(credit, LINE, charge_line, 500)
    [paid] = confirm_held(case, record_held(case, held_command(case, named, pays_debt)))["refunds"]
    assert paid["amount_usd_cents"] == 200
    assert (available(url, credit), outstanding(url, charge_line)) == (200, 0)
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(oldest): (300, 300, 300, 0),
        str(middle): (400, 200, 200, 200),
        str(named): (200, 200, 0, 0),
    }
    assert [credit_left(url, item, credit) for item in (oldest, middle, named)] == [0, 200, 0]


def test_a_reversal_takes_no_more_than_its_return_has_left(migrated_database_url: str) -> None:
    """Review round 2: C1 brings back 100 into the Credit (return only); a held-value Refund naming
    C1 pays it out, so C1 has nothing left; that Refund itself comes back (C4, return only), so
    the Credit holds 100 again, C4's money. C1's reversal has nothing to undo (the Refund's net is
    0) and would take 100 from the Credit: it is refused and writes nothing, because C1 has
    nothing left; C4's own reversal is not blocked."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 100)
    [paid] = confirm_held(case, record_held(case, held_command(case, first)))["refunds"]
    later = return_only(case, paid["id"], 100)
    assert available(url, credit) == 100
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (100, 100, 0, 0),
        str(later): (100, 0, 0, 100),
    }
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as taken:
        record_reversal(case, reversal_command(case, first))
    assert cause(taken) == ("55000", NOT_AVAILABLE)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged
    source = draft_source(url, record_reversal(case, reversal_command(case, later)))
    assert (source["swept_usd_cents"], source["left_usd_cents"]) == (0, 100)


def test_a_correction_s_own_return_is_used_first(migrated_database_url: str) -> None:
    """Review round 3: X1 brings back 300 into the Credit (return only); X2 brings back 1,700
    (return only) and its own step lets the Credit pay 1,500 of a charge. The step takes X2's own
    return first, so X1 keeps its 300 and X2 has 200 left (oldest return first would have left
    X1 nothing and refused its reversal). X1's reversal is not blocked: it takes exactly its 300
    from the Credit and puts it back on the Refund, X2 still has 200 left, and a held-value Refund
    naming X2 refunds them."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    first = return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    second = return_only(
        case, refund, 1_700, SettlementCreditStep(credit, LINE, charge_line, 1_500)
    )
    assert (available(url, credit), outstanding(url, charge_line)) == (500, 0)
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (300, 0, 0, 300),
        str(second): (1_700, 1_500, 0, 200),
    }
    assert (credit_left(url, first, credit), credit_left(url, second, credit)) == (300, 200)
    draft = record_reversal(case, reversal_command(case, first))
    source = draft_source(url, draft)
    assert (source["swept_usd_cents"], source["left_usd_cents"]) == (0, 300)
    confirm_reversal(case, draft)
    assert (available(url, credit), net(url, refund)) == (200, 300)
    assert counted(url, case["settlement"], "CREDIT", credit) == {
        str(first): (300, 300, 0, 0),
        str(second): (1_700, 1_500, 0, 200),
    }
    [paid] = confirm_held(case, record_held(case, held_command(case, second)))["refunds"]
    assert (paid["recipient_customer_id"], paid["amount_usd_cents"]) == (str(customer), 200)
    assert (available(url, credit), credit_left(url, second, credit)) == (0, 0)


def test_a_payment_return_and_a_receipt_correction_count_what_they_take_from_a_return(
    migrated_database_url: str,
) -> None:
    """Review round 3 (the review round 2 terms of the count). Credit: X1 brings back 300 of the
    correction's 2,000 Credit Refund (return only); then the Payment behind that Credit bounces,
    and its RETURNED_PAYMENT correction charges the Refund's 1,700 rest back and reverses the
    Credit, which takes all the Credit still holds, so X1 has nothing left. Deposit: X1 brings
    back 1,000 of the Settlement's 5,400 Pet Deposit Refund (return only); then the Pet Deposit's
    20,000 receipt is found wrong, and its DEPOSIT_RECEIPT_CORRECTION brings back both Deposit
    applications (14,600) and charges the Refund's 4,400 rest back, but its receipt reversal pays
    out 20,000, so X1 has nothing left (without the receipt term its net draw would be 0 and X1
    would keep 1,000 while the Pet Deposit holds nothing). In both cases a Credit reversal or a
    receipt reversal paid out X1's money, so X1's reversal waits for sub-slice 10e-3d-2c (owner
    answer (a) to Q-2026-10-13-103 point 1), and a held-value Refund naming the Credit's X1 is
    refused; neither writes anything."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    assert counted(url, case["settlement"], "CREDIT", credit) == {str(first): (300, 0, 0, 300)}
    returned = confirm_returned(
        case, record_returned(case, returned_command(case, credit_payment(url, credit)))
    )
    [rest] = [item for item in returned["recoveries"] if item["refund_id"] == str(refund)]
    assert rest["amount_usd_cents"] == 1_700
    assert one(
        url,
        "SELECT count(*) FROM app.settlement_correction_effects effect "
        "JOIN app.customer_credit_reversals reversal "
        "ON reversal.id=effect.customer_credit_reversal_id "
        "WHERE effect.settlement_correction_id=%s AND reversal.customer_credit_id=%s",
        correction_of(returned),
        credit,
    ) == (1,)
    assert (available(url, credit), net(url, refund)) == (0, 0)
    assert counted(url, case["settlement"], "CREDIT", credit) == {str(first): (300, 300, 300, 0)}
    assert credit_left(url, first, credit) == 0
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as nothing:
        record_held(case, held_command(case, first))
    assert cause(nothing) == ("55000", NOTHING_LEFT)
    with pytest.raises(FinalSettlementConflictError) as swept:
        record_reversal(case, reversal_command(case, first))
    assert cause(swept) == ("55000", REVERSED)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged
    deposit_case = closed_case(url)
    pet, pet_paid = deposit_case["pet"], pet_refund(deposit_case)
    earlier = return_only(deposit_case, pet_paid, 1_000)
    assert (held(url, pet), net(url, pet_paid)) == (1_000, 4_400)
    assert counted(url, deposit_case["settlement"], "DEPOSIT", pet) == {
        str(earlier): (1_000, 0, 0, 1_000)
    }
    receipt = receipt_of(url, pet)
    corrected = confirm_receipt(
        deposit_case, record_receipt(deposit_case, receipt_request(deposit_case, receipt))
    )
    [recovered] = corrected["recoveries"]
    assert (recovered["refund_id"], recovered["amount_usd_cents"]) == (str(pet_paid), 4_400)
    assert one(
        url,
        "SELECT count(*) FROM app.settlement_correction_effects effect "
        "JOIN app.deposit_receipt_reversals reversal "
        "ON reversal.id=effect.deposit_receipt_reversal_id "
        "WHERE effect.settlement_correction_id=%s AND reversal.deposit_receipt_id=%s",
        correction_of(corrected),
        receipt,
    ) == (1,)
    assert (held(url, pet), net(url, pet_paid)) == (0, 0)
    assert counted(url, deposit_case["settlement"], "DEPOSIT", pet) == {
        str(earlier): (1_000, 1_000, 1_000, 0)
    }
    assert deposit_left(url, earlier, pet) == 0
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as paid_out:
        record_reversal(deposit_case, reversal_command(deposit_case, earlier))
    assert cause(paid_out) == ("55000", REVERSED)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged


def test_the_count_and_the_reversal_limit_fail_closed(migrated_database_url: str) -> None:
    """The count refuses an unknown source kind or a missing Settlement or source (22023); the
    reversal check on a built source passes with no money swept and refuses money another
    correction paid out that the source does not list as parts (sub-slice 10e-3d-2a), and a
    missing or malformed part; review round 2: it refuses a missing or malformed left value and a
    reversal that would take more than the left value."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for arguments in (
            (UUID(int=1), "CASH", UUID(int=2)),
            (None, "CREDIT", UUID(int=2)),
            (UUID(int=1), "DEPOSIT", None),
            (UUID(int=1), None, UUID(int=2)),
        ):
            with pytest.raises(psycopg.Error) as invalid:
                connection.execute(
                    "SELECT * FROM app.settlement_returned_value_left(%s,%s,%s,NULL)", arguments
                )
            assert (invalid.value.sqlstate, invalid.value.diag.message_primary) == (
                "22023",
                "Returned value source is invalid",
            ), arguments
            connection.rollback()
    source: dict[str, Any] = {
        "earlier": {"amount_usd_cents": 500, "reversed": False},
        "credit_applications": [],
        "deposit_applications": [],
        "recoveries": [{"amount_usd_cents": 500, "returns": 0}],
        "source": {"value_usd_cents": 0},
        "uses": {"applied_usd_cents": 0, "refunded_usd_cents": 500, "returned_refunds": 0},
        "reapply": [],
        "swept_usd_cents": 0,
        "left_usd_cents": 0,
        # Sub-slice 10e-3d-2a: no part of the returned money paid out by another correction.
        "swept_undone_usd_cents": 0,
        "swept": [],
        "swept_open": [],
        # 10e-3d-2a review round 2: the flag is required; no own correction took other money.
        "shared_with_other_returns": False,
        "own_parts": None,
        "own_open": None,
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
    missing = {key: item for key, item in source.items() if key != "swept_usd_cents"}
    no_left = {key: item for key, item in source.items() if key != "left_usd_cents"}
    # Review round 2: nothing undone, so the reversal would take the whole 500 from the source.
    taking = {
        **source,
        "recoveries": [],
        "uses": {"applied_usd_cents": 0, "refunded_usd_cents": 0, "returned_refunds": 0},
        "source": {"value_usd_cents": 500},
    }
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb({**taking, "left_usd_cents": 500}),))
    for built, message in (
        ({**source, "swept_usd_cents": 1}, INCOMPLETE),
        ({**source, "swept_usd_cents": 500}, INCOMPLETE),
        (missing, INCOMPLETE),
        ({**source, "swept_usd_cents": None}, INCOMPLETE),
        ({**source, "swept_usd_cents": "0"}, INCOMPLETE),
        (no_left, INCOMPLETE),
        ({**source, "left_usd_cents": None}, INCOMPLETE),
        ({**source, "left_usd_cents": "0"}, INCOMPLETE),
        ({**source, "left_usd_cents": -1}, NOT_AVAILABLE),
        (taking, NOT_AVAILABLE),
        ({**taking, "left_usd_cents": 499}, NOT_AVAILABLE),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), built


def test_the_returned_value_count_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """No role calls the new count, SECURITY DEFINER with the fixed search path; migration 129
    adds only that function, changes only the four listed functions (privileges and settings
    kept; each patched body is exactly the old one with the module's replacements), no constraint
    and no trigger, and is forward-only."""
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
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261202_128"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_returned_value_left") as temporary:
        alembic_command.upgrade(config, "20261202_128")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
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
