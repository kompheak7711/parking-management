"""A returned-Payment correction gives back only a shared Deposit's shortfall (V1-056 sub-slice
10e-2b-4e-2a).

Owner answer (a) to Q-2026-10-18-127 and owner answers (a) to Q-2026-10-18-134 points 1 and 2:
after closure, when one of two Payments that funded a Deposit bounces, the RETURNED_PAYMENT
correction gives back the Deposit's shortfall (the returned receipt less what the Deposit holds)
from its uses still in force, newest first: the Settlement's Refund is charged back to its
recipient, then the Settlement's Deposit applications are reversed (the debt comes back) with the
kept part written again, then the forfeiture. The other Payment's money stays where the closed
Settlement put it. Every test runs on a real closure, to the cent.
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

from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    PostgresDepositService,
)
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from test_deposit_migration import deposit_actor, seed_historical_deposit_receipt
from test_deposit_receipt_record_migration import allocator, payment, receipt_command
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_FIRST, SECURITY, leaving_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding, today
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_payment_return_recovery_migration import charge
from test_payment_return_shared_deposit_migration import active_receipts, net, recoveries
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

REVISION = "20270101_158"
NEW = {
    "app.settlement_returned_payment_shared(uuid,uuid,jsonb)",
    "app.write_settlement_shared_deposit_undo(uuid,uuid,uuid,uuid,text,jsonb,"
    "timestamp with time zone)",
    "app.settlement_shared_deposit_kept_application_allowed(uuid,app.deposit_applications)",
}
PATCHED = {
    "app.settlement_returned_payment_source(uuid,uuid,uuid,uuid)",
    "app.assert_settlement_returned_payment_allowed(uuid,uuid,jsonb)",
    "app.post_settlement_returned_payment(uuid,uuid,uuid,uuid,uuid,text)",
    "app.settlement_returned_payment_result(uuid)",
    "app.assert_payment_return_recoveries_allowed(jsonb,uuid)",
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)",
    "app.payment_return_shortfall_recovery_amount(app.refund_corrections)",
    "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)",
    "app.validate_deposit_receipt_reversal()",
    "app.validate_deposit_application()",
    "app.write_correction_deposit_forfeiture(uuid,uuid,uuid,uuid,bigint,text,"
    "timestamp with time zone)",
    "app.payment_return_shared_deposit_recoveries(uuid,uuid)",
}
KEPT_BESIDE = (
    "A Deposit this Payment funded also holds another Payment's money and keeps a forfeiture "
    "beside a Deposit application; this correction cannot return the Payment"
)
PAYBACK_BESIDE = (
    "A Deposit this Payment funded holds the Customer's pay-back money beside a forfeiture; this "
    "correction cannot return the Payment"
)
NOT_LISTED = (
    "A post-settlement correction Deposit application must be a Deposit step of its correction, "
    "once"
)
ACTIVE_FORFEITURES = (
    "SELECT disposition.id,disposition.amount_usd_cents "
    "FROM app.deposit_dispositions disposition WHERE disposition.deposit_id=%s "
    "AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal "
    "WHERE reversal.deposit_disposition_id=disposition.id) ORDER BY disposition.occurred_at"
)
KEPT_ALLOWED = (
    "SELECT app.settlement_shared_deposit_kept_application_allowed(%s,"
    "jsonb_populate_record(NULL::app.deposit_applications,to_jsonb(application)||%s::jsonb)) "
    "FROM app.deposit_applications application WHERE application.id=%s"
)


def shared_security_case(
    url: str, second_amount: int = 10_000, third_amount: int = 0
) -> dict[str, Any]:
    """The `leaving_case` Lease (terminated with no forfeiture ground): its Security Deposit holds
    the Reservation Payment A's 10,000; its required total is raised by `second_amount` and
    Payment B's receipt of that amount is recorded. The Settlement applies 400 of Credit and 12,100
    of the Security Deposit to the other damage line, the Pet Deposit pays the pet damage line
    (12,500), and it refunds the rest of the Security Deposit (7,900 with the default) and 7,500
    of the Pet Deposit; then it closes. With `third_amount` (sub-slice 10e-2b-4e-2b-2a review round
    2; none by default) the total is raised by that amount too and Payment C's receipt of it is
    recorded before the Settlement, which refunds it with the rest."""
    case: dict[str, Any] = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    human, prop, security = case["human"], case["prop"], case["security"]
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    deposits.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            security,
            DepositAdjustmentType.INCREASE,
            second_amount + third_amount,
            today(url),
            "The agreed Lease terms raise the Security Deposit",
        ),
        actor=deposit_actor(human, prop),
    )
    [first] = active_receipts(url, security)
    second = payment(url, human, security, second_amount)
    deposits.record_receipt(
        receipt_command(security, second, second_amount), actor=allocator(human, prop)
    )
    third = None
    if third_amount:
        third = payment(url, human, security, third_amount)
        deposits.record_receipt(
            receipt_command(security, third, third_amount), actor=allocator(human, prop)
        )
    assert held(url, security) == 10_000 + second_amount + third_amount
    steps = (
        SettlementCreditStep(case["credit"], LINE, case["other_line"], 400),
        SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], 12_500),
        SettlementDepositStep(SECURITY, security, LINE, case["other_line"], 12_100),
        settlement_refund(case, "security", second_amount + third_amount - 2_100),
        settlement_refund(case, "pet", 7_500),
    )
    confirm_settlement(case, record_settlement(case, steps))
    case["person"] = correction_approver(url)
    return {**case, "first": first, "second": second, "third": third}


def test_the_owner_s_example_gives_back_the_refund_then_part_of_the_application(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-18-134 point 1, on the real path: A's 10,000 bounces after
    closure; the Security Deposit holds 0, so its shortfall is 10,000. Newest first: the
    Settlement's 7,900 Security Refund is charged back to the Customer on the Lease, then 2,100 of
    the 12,100 application: the application is reversed and its kept 10,000 written again (the
    same Deposit, stage and line, linked to the correction). A's receipt and A are reversed; the
    damage line owes 2,100 again, the Deposit holds 0 and B's receipt stays applied. The draft's
    plan lists both uses; a source whose uses do not give back the shortfall, and an application's
    kept part beside a forfeiture that stays active, are refused (hand-built). The closed
    Settlement row is unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = shared_security_case(url)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    first, second = case["first"], case["second"]
    [settlement_refund_id] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.refunds WHERE source_deposit_id=%s", security)
    ]
    [applied] = [
        UUID(str(row[0]))
        for row in rows(
            url, "SELECT id FROM app.deposit_applications WHERE deposit_id=%s", security
        )
    ]
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, first))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (plan["deposit_id"], plan["shortfall_usd_cents"], plan["held_usd_cents"]) == (
        str(security),
        10_000,
        0,
    )
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("REFUND", str(settlement_refund_id), 7_900, 7_900, 0),
        ("APPLICATION", str(applied), 12_100, 2_100, 10_000),
    ]
    [recovery] = source["recoveries"]
    assert (recovery["refund_id"], recovery["amount_usd_cents"], recovery["shortfall_share"]) == (
        str(settlement_refund_id),
        7_900,
        True,
    )
    assert allowed_check(url, case, source) == (None, None)
    wrong = json.loads(json.dumps(source))
    wrong["shared_deposits"][0]["uses"][1]["undo_usd_cents"] = 2_000
    assert allowed_check(url, case, wrong) == ("55000", STILL_HOLDS)
    beside = json.loads(json.dumps(source))
    beside["forfeitures"] = [
        {
            "id": str(uuid4()),
            "deposit_id": str(security),
            "governing_lease_id": str(case["lease"]),
            "amount_usd_cents": 1,
        }
    ]
    assert allowed_check(url, case, beside) == ("55000", KEPT_BESIDE)
    # Review round 1 (security S3): inside a confirm that is rolled back, a second kept part and a
    # kept part of another amount, each linked to the correction, are refused by the table.
    with psycopg.connect(url) as connection:
        confirmed = connection.execute(
            "SELECT app.confirm_settlement_returned_payment(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], draft),
        ).fetchone()
        assert confirmed is not None
        rolled_back = cast(dict[str, Any], confirmed[0])
        for amount in (10_000, 9_999):
            again = uuid4()
            with pytest.raises(psycopg.Error) as refused, connection.transaction():
                # The confirm set its constraints immediate; the link is written before its row,
                # as the writers do it, so its foreign key is deferred again.
                connection.execute("SET CONSTRAINTS ALL DEFERRED")
                connection.execute(
                    "SELECT app.link_settlement_correction_effect(%s,'deposit_application_id',%s)",
                    (rolled_back["settlement_correction"]["id"], again),
                )
                connection.execute(
                    "SELECT app.post_deposit_application(%s,%s,%s,%s,%s,'SECURITY_EXPLICIT',"
                    "'INVOICE_LINE',%s,%s,(SELECT max(application_order)+1 "
                    "FROM app.deposit_applications WHERE final_settlement_id=%s),'Again')",
                    (
                        case["prop"],
                        case["person"],
                        case["settlement"],
                        again,
                        security,
                        other_line,
                        amount,
                        case["settlement"],
                    ),
                )
            assert (refused.value.sqlstate, refused.value.diag.message_primary) == (
                "23514",
                NOT_LISTED,
            )
        connection.rollback()
    assert status(url, first) == "RECEIVED"
    result = confirm(case, draft)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        7_900,
    )
    assert (recoveries(url, settlement_refund_id), net(url, settlement_refund_id)) == ([7_900], 0)
    [reversal] = result["deposit_application_reversal_ids"]
    assert (
        value(
            url,
            "SELECT deposit_application_id FROM app.deposit_application_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        == applied
    )
    [kept] = result["deposit_application_ids"]
    assert one(
        url,
        "SELECT deposit_id,application_stage,invoice_line_id,amount_usd_cents,actor_id,"
        "final_settlement_id FROM app.deposit_applications WHERE id=%s",
        UUID(str(kept)),
    ) == (security, "SECURITY_EXPLICIT", other_line, 10_000, case["person"], case["settlement"])
    assert result["forfeiture_ids"] == [] and result["forfeiture_reversal_ids"] == []
    assert (held(url, security), outstanding(url, other_line)) == (0, 2_100)
    assert active_receipts(url, security) == [second]
    assert (status(url, first), status(url, second)) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)
    # The kept part passes its own check only as listed and once (rolled back reads).
    correction = UUID(str(result["settlement_correction"]["id"]))
    kept_id = UUID(str(kept))
    assert value(url, KEPT_ALLOWED, correction, "{}", kept_id) is True
    assert value(url, KEPT_ALLOWED, correction, '{"amount_usd_cents": 9999}', kept_id) is False
    assert value(url, KEPT_ALLOWED, correction, json.dumps({"id": str(uuid4())}), kept_id) is False
    assert value(url, KEPT_ALLOWED, uuid4(), "{}", kept_id) is False
    # Review round 1 (independent note 2): another stage, line or Deposit is not listed.
    for changed in (
        {"application_stage": "PET_RELATED_FIRST"},
        {"invoice_line_id": str(case["pet_line"])},
        {"deposit_id": str(case["pet"])},
    ):
        assert value(url, KEPT_ALLOWED, correction, json.dumps(changed), kept_id) is False


def test_a_refund_larger_than_the_shortfall_is_charged_back_only_in_part(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 1, its set-up): B's receipt is 20,000, so the
    Settlement refunds 17,900 of the Security Deposit. A's 10,000 shortfall is given back by the
    newest use alone: 10,000 of the 17,900 Refund is charged back (its net 7,900 stays out), and
    the 12,100 application stays applied. A's receipt is reversed while the Refund is still partly
    out beside the active application; the Deposit holds 0."""
    url = migrated_database_url
    case = shared_security_case(url, 20_000)
    security, other_line, customer = case["security"], case["other_line"], case["customer"]
    [settlement_refund_id] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.refunds WHERE source_deposit_id=%s", security)
    ]
    before_row = settlement_row(url, case["settlement"])
    draft = record(case, command(case, case["first"]))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (plan["shortfall_usd_cents"], plan["held_usd_cents"]) == (10_000, 0)
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("REFUND", str(settlement_refund_id), 17_900, 10_000, 7_900)
    ]
    [recovery] = source["recoveries"]
    assert (recovery["amount_usd_cents"], recovery["net_usd_cents"]) == (10_000, 17_900)
    result = confirm(case, draft)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"])[:5] == (
        customer,
        case["lease"],
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        10_000,
    )
    assert (recoveries(url, settlement_refund_id), net(url, settlement_refund_id)) == (
        [10_000],
        7_900,
    )
    assert result["deposit_application_reversal_ids"] == []
    assert result["deposit_application_ids"] == []
    assert (held(url, security), outstanding(url, other_line)) == (0, 0)
    assert active_receipts(url, security) == [case["second"]]
    assert (status(url, case["first"]), status(url, case["second"])) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


@pytest.mark.parametrize("returned_first", [False, True])
def test_a_kept_pet_deposit_with_pay_back_money_gives_back_from_the_forfeiture_first(
    migrated_database_url: str, returned_first: bool
) -> None:
    """Review round 1 (security B1, its set-up); owner answer (a) to Q-2026-10-18-135 (sub-slice
    10e-2b-4e-2b-1): A's 5,000 funds a Pet Deposit, a 4,000 Pet Refund-review Refund comes back in
    full (pay-back count 4,000), and the Lease is terminated for pet noncompliance; B's 5,000
    receipt follows (the required total raised), the forfeiture takes the 6,000 beyond the pay-back
    money and the Settlement refunds the 4,000 to the Customer. A's correction gives back from the
    forfeiture first: 5,000 of the 6,000 (1,000 forfeited again), nobody is charged and the 4,000
    Settlement Refund stays out; the Deposit holds 0. B's receipt is seeded by an owner insert
    after the termination, an order the receipt writer refuses (sub-slice 10e-2b-4d); the real
    path records it after the return and before the termination, and the checks read no event
    times. Review round 2 (security should-fix 1, its set-up; returned_first): after a return-only
    correction brings the 4,000 back into the Pet Deposit, the shortfall is 1,000, but the
    forfeiture still gives back 5,000 and keeps 1,000, so no pay-back money stays forfeited and
    the Deposit ends holding the 4,000 pay-back money. Until the owner's answer both were refused
    (55000), so the test is renamed (standing rule)."""
    url = migrated_database_url
    case: dict[str, Any] = {
        **pet_payback_case(url, (("refund", 4_000), ("return", 4_000)), pet_amount=5_000),
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
            5_000,
            today(url),
            "The agreed Lease terms raise the Pet Deposit",
        ),
        actor=deposit_actor(human, prop),
    )
    seed_historical_deposit_receipt(url, deposit_id=pet, actor_id=human, amount_usd_cents=5_000)
    assert held(url, pet) == 10_000
    forfeit(case, "security")
    forfeit(case, "pet")
    assert (forfeited(case, "pet"), held(url, pet)) == ([6_000], 4_000)
    confirm_settlement(case, record_settlement(case, (settlement_refund(case, "pet", 4_000),)))
    [second] = [found for found in active_receipts(url, pet) if found != first]
    [paid_back] = rows(
        url,
        "SELECT id FROM app.refunds WHERE source_deposit_id=%s AND pet_refund_review_id IS NULL",
        pet,
    )
    paid_back_id = UUID(str(paid_back[0]))
    case["person"] = correction_approver(url)
    if returned_first:
        confirm_return(
            case, record_return(case, return_command(case, paid_back_id, 4_000, new=False))
        )
        assert held(url, pet) == 4_000
    draft = record(case, command(case, first))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["payback_first"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["payback_usd_cents"],
    ) == (True, 1_000 if returned_first else 5_000, 5_000, 4_000 if returned_first else 0)
    keys = ("kind", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("FORFEITURE", 6_000, 5_000, 1_000)
    ]
    assert source["recoveries"] == []
    assert allowed_check(url, case, source) == (None, None)
    if not returned_first:
        # The B1 refusal stays as defence: the newest-first plan of sub-slice 10e-2b-4e-2a, which
        # charges the 4,000 pay-back money back and keeps 5,000 forfeited, is still refused.
        newest = json.loads(json.dumps(source))
        newest["shared_deposits"][0]["uses"] = [
            {
                "kind": "REFUND",
                "id": str(paid_back_id),
                "amount_usd_cents": 4_000,
                "undo_usd_cents": 4_000,
                "kept_usd_cents": 0,
            },
            {**plan["uses"][0], "undo_usd_cents": 1_000, "kept_usd_cents": 5_000},
        ]
        assert allowed_check(url, case, newest) == ("55000", PAYBACK_BESIDE)
        # Review round 2 (security should-fix 1, set-up (a)): a plan that drops its receipt and
        # claims no shortfall is refused; the receipt is read live.
        dropped = json.loads(json.dumps(source))
        [pet_entry] = [entry for entry in dropped["deposits"] if entry["id"] == str(pet)]
        pet_entry["shortfall_usd_cents"] = 0
        del dropped["shared_deposits"][0]["receipt_usd_cents"]
        dropped["shared_deposits"][0].update({"give_back_usd_cents": 0, "uses": []})
        assert allowed_check(url, case, dropped) == ("55000", STILL_HOLDS)
    else:
        # Review rounds 1 and 2 (both reviewers): a forfeiture-only plan that would keep the
        # pay-back money is refused by the ends check: its total is not the rule's 5,000; with
        # the Deposit marked not plain it gives back something (a Deposit that is not plain
        # gives back nothing), also with a forged held value (set-up (b)); a plan whose
        # give-backs miss its total and a source with no plan entry are refused too. No source
        # the database builds reaches the B1 end-held branch; a hand-built forfeiture list can
        # (test_settlement_returned_payment_payback_first_migration.py, the cap test).
        short = json.loads(json.dumps(source))
        short["shared_deposits"][0]["give_back_usd_cents"] = 1_000
        short["shared_deposits"][0]["uses"][0].update(
            {"undo_usd_cents": 1_000, "kept_usd_cents": 5_000}
        )
        assert allowed_check(url, case, short) == ("55000", STILL_HOLDS)
        short["shared_deposits"][0]["plain"] = False
        assert allowed_check(url, case, short) == ("55000", STILL_HOLDS)
        short["shared_deposits"][0]["held_usd_cents"] = 8_000
        assert allowed_check(url, case, short) == ("55000", STILL_HOLDS)
        missed = json.loads(json.dumps(source))
        missed["shared_deposits"][0]["uses"][0]["undo_usd_cents"] = 4_999
        gone = json.loads(json.dumps(source))
        gone["shared_deposits"] = []
        for hand_built in (missed, gone):
            assert allowed_check(url, case, hand_built) == ("55000", STILL_HOLDS)
    [(original, _)] = rows(url, ACTIVE_FORFEITURES, pet)
    before_row = settlement_row(url, case["settlement"])
    result = confirm(case, draft)
    assert result["recoveries"] == [] and result["deposit_application_ids"] == []
    [reversal] = result["forfeiture_reversal_ids"]
    assert (
        value(
            url,
            "SELECT deposit_disposition_id FROM app.deposit_disposition_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        == original
    )
    [kept] = result["forfeiture_ids"]
    assert rows(url, ACTIVE_FORFEITURES, pet) == [(UUID(str(kept)), 1_000)]
    assert forfeited(case, "pet") == [6_000, 1_000]
    assert settlement_row(url, case["settlement"]) == before_row
    assert (held(url, pet), net(url, paid_back_id)) == (
        (4_000, 0) if returned_first else (0, 4_000)
    )
    assert active_receipts(url, pet) == [second]
    assert (status(url, first), status(url, second)) == ("REVERSED", "RECEIVED")
    reconciled(url, case["customer"])


def test_the_shared_deposit_correction_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-2a adds three internal functions that no application role may run and
    patches only the listed functions, by exactly their listed replacements, with the same owner,
    privileges and settings; no constraint or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261231_157"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    for function in NEW:
        assert one(
            migrated_database_url,
            "SELECT has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE'),p.prosecdef,"
            "p.proconfig::text LIKE '%%search_path=pg_catalog%%' "
            "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
            function,
        ) == (False, False, False, True, True)

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

    with _temporary_migration_database("returned_payment_shared_deposit") as temporary:
        alembic_command.upgrade(config, "20261231_157")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) - set(before_functions) == NEW
    assert set(before_functions) <= set(after_functions)
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
