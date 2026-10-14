"""Post-settlement correction: a return's money on a payment a later return reversal changed
(sub-slice 10e-3d-2b-1a).

Owner answer (a) to Q-2026-10-13-100 point 1: the reversal of a mistaken return makes the debt its
money paid owed again. A return reversal reverses a payment whole and puts back exactly the part
that was not its own return's money, so another return's part of that payment is in the put-back,
unchanged; its later reversal follows the part there (and through further put-backs).
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
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_held_value_refund_migration import return_only
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
    confirm_reversal,
    correction_of,
    draft_source,
    record_reversal,
    reversal_command,
)

REVISION = "20261205_131"
INTERNAL = "app.settlement_returned_value_successor(text,uuid)"
PATCHED = "app.settlement_return_reversal_source_state(uuid,uuid)"


def successor(url: str, kind: str | None, application: object) -> Any:
    """The application now holding the money (sub-slice 10e-3d-2b-1a), or None."""
    found = one(url, "SELECT app.settlement_returned_value_successor(%s,%s)", kind, application)
    return None if found[0] is None else str(found[0])


def reverse(case: dict[str, Any], earlier: object) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record and confirm the reversal of a return; its draft's source and its result."""
    draft = record_reversal(case, reversal_command(case, earlier))
    return draft_source(case["url"], draft), confirm_reversal(case, draft)


def test_a_part_follows_a_chain_of_put_backs(migrated_database_url: str) -> None:
    """Credit form: X1, X1b and X1c each bring back 300 (return only); X2 brings back 600 (return
    only) and its step lets the Credit pay a 1,500 charge: X2's own 600, then 300 of each, in that
    one application. X1's reversal reverses it and puts 1,200 back; X1b's 300 follows to that
    put-back, which its reversal reverses and puts 900 back; X1c's 300 follows through both
    put-backs to the 900, which its reversal reverses and puts 600 back. Each time exactly the
    mistaken 300 of the charge is owed again and the Credit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    middle = return_only(case, refund, 300)
    last = return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    holder = return_only(case, refund, 600, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = one(
        url,
        "SELECT array_agg(id::text) FROM app.customer_credit_applications "
        "WHERE customer_credit_id=%s",
        credit,
    )
    [application] = paying
    assert successor(url, "CREDIT", application) == application
    owed = []
    for earlier, rest in ((first, 1_200), (middle, 900), (last, 600)):
        source, result = reverse(case, earlier)
        [part] = source["swept"]
        [undone] = result["credit_application_reversals"]
        [again] = result["reapplied"]
        # Review round 1: the part names the correction that wrote the payment holding it.
        assert (part["settlement_correction_id"], part["record_id"], part["part_usd_cents"]) == (
            str(holder),
            undone["credit_application_id"],
            300,
        )
        assert (undone["amount_usd_cents"], again["amount_usd_cents"]) == (rest + 300, rest)
        assert successor(url, "CREDIT", application) == again["id"]
        holder = correction_of(result)
        owed.append((available(url, credit), outstanding(url, charge_line)))
    assert owed == [(0, 300), (0, 600), (0, 900)]
    assert net(url, refund) == 1_400
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_part_follows_to_the_second_put_back_of_a_reversal(migrated_database_url: str) -> None:
    """Review round 2, the n-th put-back of a reversal is its n-th payment written: X0, X1 and X3
    bring back 300, 600 and 300 (return only); X2 brings back 300 (return only) and its step lets
    the Credit pay 600 of one charge (A1) and then 900 of another (A2). X2's draw, its newest
    payment first: its own 300 and X0's 300 on A2, X1's 600 split 300 on A2 and 300 on A1, X3's
    300 on A1. X1's reversal reverses both and puts back 300 on A1 and 600 on A2, in that order.
    X0's 300 then follows to the second put-back (600), which X0's reversal reverses whole and
    puts 300 back: the second charge owes 1,200 and the Credit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    split = return_only(case, refund, 600)
    return_only(case, refund, 300)
    _, first_line = unpaid_charge(url, case, case["person"])
    _, second_line = unpaid_charge(url, case, case["person"])
    return_only(
        case,
        refund,
        300,
        SettlementCreditStep(credit, LINE, first_line, 600),
        SettlementCreditStep(credit, LINE, second_line, 900),
    )
    [paying] = one(
        url,
        "SELECT array_agg(id::text ORDER BY occurred_at,id) "
        "FROM app.customer_credit_applications WHERE customer_credit_id=%s",
        credit,
    )
    [_, newer] = paying
    source, result = reverse(case, split)
    assert [item["amount_usd_cents"] for item in source["reapply"]] == [300, 600]
    [_, second_put_back] = result["reapplied"]
    assert (outstanding(url, first_line), outstanding(url, second_line)) == (1_200, 900)
    source, again = reverse(case, first)
    [part] = source["swept"]
    assert (
        part["settlement_correction_id"],
        part["record_id"],
        part["amount_usd_cents"],
        part["part_usd_cents"],
    ) == (str(correction_of(result)), second_put_back["id"], 600, 300)
    [undone] = again["credit_application_reversals"]
    [restored] = again["reapplied"]
    assert (undone["amount_usd_cents"], restored["amount_usd_cents"]) == (600, 300)
    assert successor(url, "CREDIT", newer) == restored["id"]
    assert (
        available(url, credit),
        outstanding(url, first_line),
        outstanding(url, second_line),
    ) == (0, 1_200, 1_200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_deposit_part_follows_to_its_put_back(migrated_database_url: str) -> None:
    """Deposit form: E1 and E2 each bring back 1,000 of the Pet Deposit Refund (return only). S
    brings back 500 with a new Refund: the Customer's other Credit pays 300 of a 1,500 charge, the
    Pet Deposit the other 1,200, and it refunds 1,300. S's own 500 and 800 of E1's money are in its
    Refund; E1's other 200 and E2's 1,000 in its application. E1's reversal charges 800 back,
    reverses the application and puts 1,000 back; E2's 1,000 follows to that put-back, which E2's
    reversal reverses whole with nothing put back (then nothing holds that money any more). The
    charge owes the 1,200 again and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    first = return_only(case, pet_paid, 1_000)
    second = return_only(case, pet_paid, 1_000)
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
    [applied] = paid_out["deposit_applications"]
    source, result = reverse(case, first)
    [recovery] = result["recoveries"]
    [again] = result["reapplied"]
    assert (recovery["amount_usd_cents"], again["amount_usd_cents"]) == (800, 1_000)
    assert successor(url, "DEPOSIT", applied["id"]) == again["id"]
    assert (held(url, pet), outstanding(url, charge_line)) == (0, 200)
    source, result = reverse(case, second)
    [part] = source["swept"]
    assert (part["record_id"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        again["id"],
        1_000,
        1_000,
    )
    [undone] = result["deposit_application_reversals"]
    assert (undone["deposit_application_id"], result["reapplied"], result["recoveries"]) == (
        again["id"],
        [],
        [],
    )
    assert successor(url, "DEPOSIT", applied["id"]) is None
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        charge_open(url, recovery),
        net(url, pet_paid),
    ) == (0, 1_200, 800, 4_900)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_part_on_a_payment_a_refund_correction_changed_is_followed_into_its_payment_written_again(
    migrated_database_url: str,
) -> None:
    """Review round 1 set-up, allowed since sub-slice 10e-3d-2b-2 (owner answer (a) to
    Q-2026-10-13-107): E brings back 300 (return only); S brings back 1,200 (return only) and its
    step lets the Credit pay a 1,500 charge (S's own 1,200, then E's 300, in one payment). A Refund
    correction then finds 300 of the charge wrong: it releases 300 of that payment (reversed, 1,200
    written again) and refunds the 300. Of the money it took back, its Refund pays out the first
    300 and the payment written again the rest, so E's 300 (the last 300) sits in the 1,200
    payment: E's reversal reverses it whole and puts 900 back, 300 of the charge is owed again and
    the Refund stays as it is."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    earlier = return_only(case, refund, 300)
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    return_only(case, refund, 1_200, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = one(
        url,
        "SELECT array_agg(id::text) FROM app.customer_credit_applications "
        "WHERE customer_credit_id=%s",
        credit,
    )
    [application] = paying
    released = confirm_refund(
        case, record_refund(case, refund_correction(case, charge_invoice, charge_line, 300))
    )
    [paid] = released["refunds"]
    assert (paid["amount_usd_cents"], outstanding(url, charge_line)) == (300, 0)
    assert successor(url, "CREDIT", application) is None
    [written_again] = one(
        url,
        "SELECT array_agg(application.id::text) FROM app.customer_credit_applications application "
        "WHERE application.customer_credit_id=%s AND NOT EXISTS(SELECT 1 "
        "FROM app.customer_credit_application_reversals reversal "
        "WHERE reversal.credit_application_id=application.id)",
        credit,
    )[0]
    before = available(url, credit)
    source, result = reverse(case, earlier)
    [part] = source["swept"]
    assert (part["record_id"], part["amount_usd_cents"], part["part_usd_cents"]) == (
        written_again,
        1_200,
        300,
    )
    assert (source["swept_open"], source["recoveries"]) == ([], [])
    [undone] = result["credit_application_reversals"]
    [again] = result["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (written_again, 1_200)
    assert (again["amount_usd_cents"], result["recoveries"]) == (900, [])
    assert (available(url, credit), outstanding(url, charge_line), net(url, paid["id"])) == (
        before,
        300,
        300,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_the_successor_fails_closed(migrated_database_url: str) -> None:
    """An unknown kind, no application or an application that does not exist gives no successor."""
    url = migrated_database_url
    for kind, application in (
        ("CASH", uuid4()),
        (None, uuid4()),
        ("CREDIT", None),
        ("CREDIT", uuid4()),
        ("DEPOSIT", uuid4()),
    ):
        assert successor(url, kind, application) is None, (kind, application)


def test_the_successor_is_least_privilege_and_forward_only(migrated_database_url: str) -> None:
    """No role calls the successor, SECURITY DEFINER with the fixed search path; migration 131 adds
    only the successor, changes only the return reversal source (privileges and settings kept,
    the body exactly the old one with the module's replacements), no constraint and no trigger,
    and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, INTERNAL)
            ).fetchone() == (False,), role
        assert connection.execute(
            "SELECT p.prosecdef,p.proconfig[1] FROM pg_catalog.pg_proc p "
            "WHERE p.oid=CAST(%s AS regprocedure)",
            (INTERNAL,),
        ).fetchone() == (True, "search_path=pg_catalog")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261204_130"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_successor") as temporary:
        alembic_command.upgrade(config, "20261204_130")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {PATCHED}
    assert after_functions[PATCHED][1:] == before_functions[PATCHED][1:]
    [(function, replacements)] = revision.module.PATCHES
    assert function == PATCHED
    body = str(before_functions[PATCHED][0])
    for anchor, replacement in replacements:
        assert body.count(anchor) == 1
        body = body.replace(anchor, replacement)
    assert after_functions[PATCHED][0] == body
