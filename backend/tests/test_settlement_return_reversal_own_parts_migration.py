"""Post-settlement correction: a return's own uses placed by the walk (sub-slice 10e-3d-2b-1b).

Owner answer (a) to Q-2026-10-13-100 point 1: the reversal of a mistaken return charges the paid-out
part back to the person who received it and makes the debt its money paid owed again. The return's
own correction and the held-value Refunds naming it place its money as any other correction does:
after what they brought back, on their Refunds (the oldest first) and then on their applications
(the newest first), each payment a later return reversal changed followed to its put-back. The
pooled own path of sub-slices 10e-3b and 10e-3c stays where the two agree.
"""

from __future__ import annotations

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
    FinalSettlementConflictError,
    SettlementCreditStep,
    SettlementDepositStep,
)
from test_customer_ledger_migration import assert_reconciled
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_settlement_correction_plan_migration import closed_case
from test_settlement_deposit_refund_correction_migration import confirm_refund, record_refund
from test_settlement_deposit_refund_return_migration import pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_held_value_refund_migration import (
    COUNTS,
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import third_party_payment, unpaid_charge
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
    charge_open,
    correction_of,
    record_reversal,
    reversal_command,
)
from test_settlement_return_reversal_successor_migration import reverse, successor
from test_settlement_return_reversal_swept_migration import FORFEITED, SHARED
from test_settlement_returned_value_left_migration import (
    CHANGED,
    DRAFTS,
    INCOMPLETE,
    REVERSED,
)

REVISION = "20261206_132"
INTERNAL = "app.settlement_returned_value_parts(uuid,text,uuid,uuid,boolean)"
REPLACED = "app.settlement_returned_value_takes(uuid,text,uuid,uuid)"
PATCHED = {
    "app.settlement_return_reversal_source_state(uuid,uuid)",
    "app.assert_settlement_return_reversal_allowed(jsonb)",
}


def payments(url: str, credit: object) -> list[str]:
    """The Credit's applications, the oldest first."""
    [found] = one(
        url,
        "SELECT array_agg(id::text ORDER BY occurred_at,id) "
        "FROM app.customer_credit_applications WHERE customer_credit_id=%s",
        credit,
    )
    return list(found)


def test_an_own_payment_follows_a_chain_of_put_backs(migrated_database_url: str) -> None:
    """Round 2 note N3 of sub-slice 10e-3d-2a, through two put-backs (Credit form): X1 and X2 each
    bring back 300 (return only); E brings back 900 (return only) and its own step lets the Credit
    pay a 1,500 charge in one payment: E's own 900, then X1's 300 and X2's 300. X1's reversal
    reverses that payment and puts 1,200 back; X2's reversal follows its 300 there, reverses the
    1,200 and puts 900 back. E's own 900 follows through both put-backs, so E's reversal reverses
    the 900 payment whole (before this sub-slice it was refused: the own payment was no longer
    active). The whole 1,500 of the charge is owed again and the Credit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    before = net(url, refund)
    first = return_only(case, refund, 300)
    second = return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(case, refund, 900, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = payments(url, credit)
    put_backs = []
    for other, rest in ((first, 1_200), (second, 900)):
        _, result = reverse(case, other)
        [again] = result["reapplied"]
        assert again["amount_usd_cents"] == rest
        put_backs.append((correction_of(result), again["id"]))
        assert successor(url, "CREDIT", paying) == again["id"]
    assert (available(url, credit), outstanding(url, charge_line)) == (0, 600)
    source, result = reverse(case, earlier)
    holder, holding = put_backs[-1]
    assert (source["swept"], source["own_open"], source["reapply"]) == ([], [], [])
    assert [
        (
            part["settlement_correction_id"],
            part["record_kind"],
            part["record_id"],
            part["amount_usd_cents"],
            part["part_usd_cents"],
        )
        for part in source["own_parts"]
    ] == [(str(holder), "CREDIT_APPLICATION", holding, 900, 900)]
    [undone] = result["credit_application_reversals"]
    assert (
        undone["credit_application_id"],
        undone["amount_usd_cents"],
        result["reapplied"],
        result["recoveries"],
    ) == (holding, 900, [], [])
    assert successor(url, "CREDIT", paying) is None
    assert (available(url, credit), outstanding(url, charge_line), net(url, refund)) == (
        0,
        1_500,
        before,
    )
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_an_own_deposit_payment_follows_to_its_put_back(migrated_database_url: str) -> None:
    """Round 2 note N3 of sub-slice 10e-3d-2a, Deposit form: X brings back 1,000 of the Pet Deposit
    Refund (return only). E brings back 500 with a new Refund: the Customer's other Credit pays
    300 of a 1,500 charge, the Pet Deposit the other 1,200, and it refunds 300. E's own 500 is its
    300 Refund and 200 of its payment; X's 1,000 the rest of the payment. X's reversal reverses the
    payment and puts 200 back. E's reversal then charges its 300 Refund back and follows its 200
    to that put-back, which it reverses whole (before this sub-slice it was refused): the 1,200
    of the charge is owed again and the Pet Deposit ends empty."""
    url = migrated_database_url
    case = {**closed_case(url), "url": url}
    pet, pet_paid = case["pet"], pet_refund(case)
    before = net(url, pet_paid)
    other = return_only(case, pet_paid, 1_000)
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
    earlier = correction_of(paid_out)
    [applied] = paid_out["deposit_applications"]
    [own_refund] = paid_out["refunds"]
    _, result = reverse(case, other)
    [again] = result["reapplied"]
    assert (again["amount_usd_cents"], result["recoveries"]) == (200, [])
    assert (held(url, pet), outstanding(url, charge_line)) == (0, 1_000)
    source, result = reverse(case, earlier)
    assert (source["swept"], source["own_open"], source["reapply"]) == ([], [], [])
    parts = {part["record_kind"]: part for part in source["own_parts"]}
    assert set(parts) == {"REFUND", "DEPOSIT_APPLICATION"}
    assert (
        parts["REFUND"]["settlement_correction_id"],
        parts["REFUND"]["record_id"],
        parts["REFUND"]["part_usd_cents"],
        parts["DEPOSIT_APPLICATION"]["record_id"],
        parts["DEPOSIT_APPLICATION"]["amount_usd_cents"],
        parts["DEPOSIT_APPLICATION"]["part_usd_cents"],
    ) == (str(earlier), own_refund["id"], 300, again["id"], 200, 200)
    [undone] = result["deposit_application_reversals"]
    [recovery] = result["recoveries"]
    assert (
        undone["deposit_application_id"],
        recovery["refund_id"],
        recovery["amount_usd_cents"],
        result["reapplied"],
    ) == (again["id"], own_refund["id"], 300, [])
    assert successor(url, "DEPOSIT", applied["id"]) is None
    assert (
        held(url, pet),
        outstanding(url, charge_line),
        charge_open(url, recovery),
        net(url, pet_paid),
    ) == (0, 1_200, 300, before)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_an_own_part_on_a_put_back_with_other_money_is_applied_again(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent SF1), the rest of an own part applied again on the real path
    (Credit form): X1 and X2 each bring back 300 (return only); E brings back 900 (return only) and
    its own step lets the Credit pay a 1,500 charge in one payment (E's 900, X1's 300, X2's 300).
    X1's reversal puts 1,200 back, holding E's 900 and X2's 300. E's reversal reverses that
    put-back whole and applies X2's 300 again, although E's own correction has no active payment
    left (its pooled totals are 0): 1,200 of the charge is owed again and the Credit ends empty."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    first = return_only(case, refund, 300)
    return_only(case, refund, 300)
    _, charge_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(case, refund, 900, SettlementCreditStep(credit, LINE, charge_line, 1_500))
    [paying] = payments(url, credit)
    _, result = reverse(case, first)
    [put_back] = result["reapplied"]
    source, result = reverse(case, earlier)
    assert (source["swept"], source["own_open"], source["uses"]) == (
        [],
        [],
        {"applied_usd_cents": 0, "refunded_usd_cents": 0, "returned_refunds": 0},
    )
    assert [
        (
            part["record_kind"],
            part["record_id"],
            part["amount_usd_cents"],
            part["part_usd_cents"],
        )
        for part in source["own_parts"]
    ] == [("CREDIT_APPLICATION", put_back["id"], 1_200, 900)]
    assert [(item["application_id"], item["amount_usd_cents"]) for item in source["reapply"]] == [
        (put_back["id"], 300)
    ]
    [undone] = result["credit_application_reversals"]
    [again] = result["reapplied"]
    assert (undone["credit_application_id"], undone["amount_usd_cents"]) == (put_back["id"], 1_200)
    assert again["amount_usd_cents"] == 300
    assert successor(url, "CREDIT", paying) == again["id"]
    assert (available(url, credit), outstanding(url, charge_line)) == (0, 1_200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_an_own_refund_returned_later_waits_for_that_return_s_reversal(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security SF3), on the walk path: the shape of
    test_own_corrections_that_also_took_another_return_s_money_are_undone_per_correction, then 50
    of the held-value Refund comes back (return only). E's part of that Refund (200) is now more
    than its net (150), so E's reversal is refused and writes nothing; after that later return is
    reversed, E's reversal goes through as before."""
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
    later = return_only(case, UUID(str(paid["id"])), 50)
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(refused) == ("55000", NOT_AVAILABLE)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged
    reverse(case, later)
    _, result = reverse(case, earlier)
    [undone] = result["credit_application_reversals"]
    [recovery] = result["recoveries"]
    assert (undone["amount_usd_cents"], recovery["refund_id"], recovery["amount_usd_cents"]) == (
        1_500,
        paid["id"],
        200,
    )
    assert (
        available(url, credit),
        outstanding(url, first_line),
        outstanding(url, second_line),
        charge_open(url, recovery),
    ) == (0, 1_500, 0, 200)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_an_own_payment_a_refund_correction_changed_waits(migrated_database_url: str) -> None:
    """Review round 1 (security SF4), on the walk path through a reversed own payment with no
    put-back: E brings back 1,500 (return only) and its own step lets the Credit pay a 1,500
    charge; a Refund correction then releases 300 of that payment (reversed, 1,200 written again)
    and refunds the 300. Where E's money now sits is the 10e-3d-2b-2 case (Q-2026-10-13-107), so
    the source lists the own part as open and E's reversal is refused with the 10e-3d-2b message,
    writing nothing."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    charge_invoice, charge_line = unpaid_charge(url, case, case["person"])
    earlier = return_only(
        case, refund, 1_500, SettlementCreditStep(credit, LINE, charge_line, 1_500)
    )
    [paying] = payments(url, credit)
    confirm_refund(
        case, record_refund(case, refund_correction(case, charge_invoice, charge_line, 300))
    )
    assert successor(url, "CREDIT", paying) is None
    [source] = one(
        url,
        "SELECT app.settlement_return_reversal_source_state(%s,%s)",
        case["settlement"],
        earlier,
    )
    assert (
        source["own_parts"],
        source["swept"],
        source["swept_open"],
        source["credit_applications"],
    ) == ([], [], [], [])
    assert [
        (part["kind"], part["record_kind"], part["record_id"], part["part_usd_cents"])
        for part in source["own_open"]
    ] == [("CHANGED_APPLICATION", "CREDIT_APPLICATION", paying, 1_500)]
    unchanged = (one(url, COUNTS), one(url, DRAFTS))
    with pytest.raises(FinalSettlementConflictError) as changed:
        record_reversal(case, reversal_command(case, earlier))
    assert cause(changed) == ("55000", CHANGED)
    assert (one(url, COUNTS), one(url, DRAFTS)) == unchanged


def test_the_own_parts_fail_closed(migrated_database_url: str) -> None:
    """On the refusal function with a built walk-path source (the Credit form: 1,000 returned, all
    of it paid out by the return's own uses: 800 of a 1,100 application, whose other 300 is applied
    again, and 200 of a Refund): it passes, also with pooled totals that would refuse a pooled
    source and with the flag of own corrections that also took another return's money; the own
    parts must add up to the part of the returned money the own uses used, be listed exactly and
    cover every listed record, else the source is incomplete; an own part the reversal cannot undo
    yet has the message of its kind; both own keys are null or lists together, and with both null
    the source is a pooled one, which the flag refuses."""
    url = migrated_database_url
    credit, application, refund, line = (str(uuid4()) for _ in range(4))
    application_part = {
        "settlement_correction_id": str(uuid4()),
        "record_kind": "CREDIT_APPLICATION",
        "record_id": application,
        "amount_usd_cents": 1_100,
        "part_usd_cents": 800,
    }
    refund_part = {
        "settlement_correction_id": str(uuid4()),
        "record_kind": "REFUND",
        "record_id": refund,
        "amount_usd_cents": 500,
        "part_usd_cents": 200,
    }
    entry = {
        "source_kind": "CREDIT",
        "application_id": application,
        "amount_usd_cents": 300,
        "customer_credit_id": credit,
        "target_kind": "INVOICE_LINE",
        "target_id": line,
        "customer_designation": None,
    }
    listed = {
        "id": application,
        "customer_credit_id": credit,
        "late_payment_charge_id": None,
        "amount_usd_cents": 1_100,
    }
    recovery = {"refund_id": refund, "amount_usd_cents": 200, "net_usd_cents": 500, "returns": 0}
    source: dict[str, Any] = {
        "earlier": {
            "amount_usd_cents": 1_000,
            "reversed": False,
            "customer_credit_id": credit,
            "deposit_id": None,
        },
        "credit_applications": [listed],
        "deposit_applications": [],
        "recoveries": [recovery],
        "source": {"value_usd_cents": 0},
        "uses": {"applied_usd_cents": 1_100, "refunded_usd_cents": 500, "returned_refunds": 1},
        "reapply": [entry],
        "swept_usd_cents": 0,
        "left_usd_cents": 0,
        "swept_undone_usd_cents": 0,
        "swept": [],
        "swept_open": [],
        "shared_with_other_returns": True,
        "own_parts": [application_part, refund_part],
        "own_open": [],
    }
    check = "SELECT app.assert_settlement_return_reversal_allowed(%s)"
    no_uses = {"applied_usd_cents": 0, "refunded_usd_cents": 0, "returned_refunds": 0}
    with psycopg.connect(url) as connection:
        connection.execute(check, (Jsonb(source),))
        # Review round 1: with pooled totals of 0, as on a real walk-path source whose own
        # payment was reversed since, the part applied again passes as an own part's rest.
        connection.execute(check, (Jsonb({**source, "uses": no_uses}),))
    stranger = str(uuid4())

    def opened(kind: str) -> dict[str, Any]:
        part = {"kind": kind, "record_kind": kind, "record_id": str(uuid4()), "part_usd_cents": 5}
        return {**source, "own_open": [part]}

    for built, message in (
        ({**source, "left_usd_cents": 100}, INCOMPLETE),
        # Review round 1: the sums agree, so only the check that no record is a part twice
        # refuses.
        (
            {
                **source,
                "earlier": {**source["earlier"], "amount_usd_cents": 1_200},
                "swept": [refund_part],
                "swept_usd_cents": 200,
                "swept_undone_usd_cents": 200,
            },
            INCOMPLETE,
        ),
        # Review round 1: on the walk path the totals must be there as numbers.
        ({**source, "uses": {}}, INCOMPLETE),
        ({**source, "uses": {**no_uses, "returned_refunds": None}}, INCOMPLETE),
        # Review round 2: each total on its own, and an unknown earlier amount.
        ({**source, "uses": {**no_uses, "refunded_usd_cents": "0"}}, INCOMPLETE),
        ({**source, "uses": {**no_uses, "applied_usd_cents": None}}, INCOMPLETE),
        ({**source, "earlier": {**source["earlier"], "amount_usd_cents": None}}, INCOMPLETE),
        # Review round 2: the sums agree and the zero part is listed, so only the check that
        # every part is above 0 refuses.
        (
            {
                **source,
                "earlier": {**source["earlier"], "amount_usd_cents": 800},
                "own_parts": [application_part, {**refund_part, "part_usd_cents": 0}],
                "recoveries": [{**recovery, "amount_usd_cents": 0}],
            },
            INCOMPLETE,
        ),
        ({**source, "own_parts": [application_part]}, INCOMPLETE),
        ({**source, "recoveries": [{**recovery, "amount_usd_cents": 100}]}, INCOMPLETE),
        ({**source, "reapply": [{**entry, "amount_usd_cents": 200}]}, INCOMPLETE),
        (
            {
                **source,
                "credit_applications": [listed, {**listed, "id": stranger, "amount_usd_cents": 50}],
            },
            INCOMPLETE,
        ),
        (
            {
                **source,
                "recoveries": [
                    recovery,
                    {
                        "refund_id": stranger,
                        "amount_usd_cents": 50,
                        "net_usd_cents": 50,
                        "returns": 0,
                    },
                ],
            },
            INCOMPLETE,
        ),
        ({**source, "reapply": [entry, {**entry, "application_id": stranger}]}, INCOMPLETE),
        (opened("CHANGED_APPLICATION"), CHANGED),
        (opened("CREDIT_REVERSAL"), REVERSED),
        (opened("RECEIPT_REVERSAL"), REVERSED),
        (opened("FORFEITURE"), FORFEITED),
        (opened("CHANGED_REFUND"), NOT_AVAILABLE),
        ({key: item for key, item in source.items() if key != "own_parts"}, INCOMPLETE),
        ({key: item for key, item in source.items() if key != "own_open"}, INCOMPLETE),
        ({**source, "own_parts": None}, INCOMPLETE),
        ({**source, "own_parts": "[]", "own_open": "[]"}, INCOMPLETE),
        ({**source, "own_parts": None, "own_open": None}, SHARED),
    ):
        with pytest.raises(psycopg.Error) as refused, psycopg.connect(url) as connection:
            connection.execute(check, (Jsonb(built),))
        assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
            "55000",
            message,
        ), built


def test_the_own_parts_are_least_privilege_and_forward_only(migrated_database_url: str) -> None:
    """No role calls the parts function or the takes, each SECURITY DEFINER with the fixed search
    path; migration 132 adds only the parts function, replaces only the takes (privileges and
    settings kept), changes only the two listed functions (each patched body is exactly the old
    one with the module's replacements), no constraint and no trigger, and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for function in (INTERNAL, REPLACED):
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
    assert revision is not None and revision.down_revision == "20261205_131"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    with _temporary_migration_database("settlement_return_reversal_own_parts") as temporary:
        alembic_command.upgrade(config, "20261205_131")
        before_functions, before_constraints, before_triggers = app_catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = app_catalog(temporary)
    assert (after_triggers, after_constraints) == (before_triggers, before_constraints)
    assert set(after_functions) - set(before_functions) == {INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == PATCHED | {REPLACED}
    for name in (*PATCHED, REPLACED):
        assert after_functions[name][1:] == before_functions[name][1:], name
    # Review round 1: the parts function has the takes' rights list and owner, so no role beyond
    # those the takes allow may call it.
    assert after_functions[INTERNAL][1:3] == after_functions[REPLACED][1:3]
    assert {function for function, _ in revision.module.PATCHES} == PATCHED
    for function, replacements in revision.module.PATCHES:
        body = str(before_functions[function][0])
        for anchor, replacement in replacements:
            assert body.count(anchor) == 1, function
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
