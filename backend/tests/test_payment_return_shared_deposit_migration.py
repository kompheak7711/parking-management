"""A returned Payment of a shared Deposit charges back only the shortfall (V1-056 sub-slice
10e-2b-4e-1).

Owner answer (a) to Q-2026-10-18-127: when one of two or more Payments that funded a Deposit
bounces, its return reverses its receipt when the Deposit still holds at least its amount, and
otherwise first charges back only the shortfall (its amount less what the Deposit holds) to the
person who received the Refund, newest Refund first, with the same recovery charge as today.
The return after closure (the two corrections) is sub-slice 10e-2b-4e-2; option (d) (no receipt
into a Deposit whose Refund is out) stays until then (review round 2).
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

from lease_deposit_forfeiture_test_support import forfeit_through_draft
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    PostgresDepositService,
)
from property_rental.payment_return import PaymentReturnStaleDraftError
from property_rental.refund import SignerRecipient
from refund_test_support import cash, create_pet_refund
from test_credit_migration import actor
from test_deposit_migration import deposit_actor
from test_deposit_receipt_leftover_migration import REFUND_OUT
from test_deposit_receipt_record_migration import (
    SHARED,
    allocator,
    attempt,
    payment,
    pet_case,
    qualify_review,
    receipt_command,
    review_refund,
    terminated_pet_lease_case,
)
from test_final_settlement_migration import held, one, today
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import (
    draft_id,
    drafts,
    reconciled,
    request,
    returns,
    status,
)
from test_payment_return_migration import preparer as return_preparer
from test_payment_return_recovery_migration import charge, due_days, return_refused
from test_pet_payback_restoration_refusal_migration import owner
from test_pet_refund_migration import command as pet_refund_command
from test_refund_service_migration import refund_id, returned
from test_refund_service_migration import service as refund_service
from test_refund_signer_recipient_migration import joint_qualified
from test_settlement_real_path_migration import AGREEMENT

REVISION = "20261231_157"
NEW = {
    "app.payment_return_shared_deposit_recoveries(uuid,uuid)",
    "app.payment_return_draft_source(uuid,uuid,uuid)",
    "app.payment_return_shortfall_recovery_amount(app.refund_corrections)",
    "app.payment_return_shared_receipt_reversal_allowed(app.deposit_receipt_reversals)",
}
PATCHED = {
    "app.record_payment_return_draft(uuid,uuid,uuid,uuid,jsonb,text,text)",
    "app.assert_payment_return_recoveries_allowed(jsonb,uuid)",
    "app.assert_payment_return_recoveries_planned(jsonb)",
    "app.write_payment_return_recoveries(uuid,uuid,uuid,uuid,uuid,jsonb,text,text,"
    "timestamp with time zone,jsonb)",
    "app.validate_general_refund_correction()",
    "app.validate_deposit_receipt_reversal()",
    "app.confirm_payment_return(uuid,uuid,uuid,text)",
}
RECOVERED = "A Refund is recovered by a charge only inside the return of its Payment"
NEGATIVE = "Deposit historical held balance cannot be negative"
FORFEITED = "A Deposit this Payment funded has an active forfeiture; reverse the forfeiture first"


def net(url: str, refund: UUID) -> int:
    return int(value(url, "SELECT app.refund_net_value_at(%s,'infinity')", refund))


def recoveries(url: str, refund: UUID) -> list[int]:
    """The Refund's recoveries by a charge, oldest first."""
    return [
        int(row[0])
        for row in rows(
            url,
            "SELECT source_balance_effect_usd_cents FROM app.refund_corrections "
            "WHERE refund_id=%s AND correction_kind='RECOVERED_BY_CHARGE' ORDER BY occurred_at",
            refund,
        )
    ]


def active_receipts(url: str, deposit: UUID) -> list[UUID]:
    return [
        UUID(str(row[0]))
        for row in rows(
            url,
            "SELECT receipt.payment_id FROM app.deposit_receipts receipt "
            "WHERE receipt.deposit_id=%s AND NOT EXISTS("
            "SELECT 1 FROM app.deposit_receipt_reversals reversal "
            "WHERE reversal.deposit_receipt_id=receipt.id) ORDER BY receipt.occurred_at",
            deposit,
        )
    ]


def shared_case(url: str, refunds: tuple[int, ...]) -> dict[str, Any]:
    """A Pet Deposit (required 20,000) that takes 10,000 from Payment A and then 10,000 from
    Payment B, then pays the given Pet Refund-review Refunds in that order."""
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    first, second = payment(url, human, pet, 10_000), payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, first, 10_000), actor=allocator(human, prop))
    service.record_receipt(receipt_command(pet, second, 10_000), actor=allocator(human, prop))
    review = qualify_review(case)
    paid = [review_refund(case, review, amount) for amount in refunds]
    return {**case, "first": first, "second": second, "refunds": paid}


def return_payment(case: dict[str, Any], paid_by: UUID) -> dict[str, Any]:
    """Record and confirm the Payment's return (a PAYMENT_RETURN draft)."""
    human, prop = case["human"], case["prop"]
    draft = returns().record(prop, request(paid_by), actor=return_preparer(human, prop))
    return returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))


def test_a_shared_deposit_charges_back_only_the_shortfall_then_the_rest_as_before(
    migrated_database_url: str,
) -> None:
    """The Q-2026-10-18-127 example: 10,000 from Payment A and 10,000 from Payment B, then a
    15,000 Pet Refund-review Refund (the Deposit holds 5,000). A bounces: its return charges back
    only the 5,000 shortfall to the Customer on the Lease, reverses A's receipt and leaves the
    Deposit at 0; the Refund's net is 10,000, B's receipt stays and the pay-back count rises by the
    5,000 charged back. Then B bounces: the Deposit is no longer shared, so B's return charges back
    the remaining 10,000 whole, as before this sub-slice."""
    url = migrated_database_url
    case = shared_case(url, (15_000,))
    human, prop, pet, customer, lease = (
        case["human"],
        case["prop"],
        case["pet"],
        case["customer"],
        case["lease"],
    )
    [refund] = case["refunds"]
    assert held(url, pet) == 5_000
    count = int(value(url, "SELECT app.lease_deposit_payback_count(%s)", pet))
    draft = returns().record(prop, request(case["first"]), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert (plan["refund_id"], plan["amount_usd_cents"], plan["net_usd_cents"]) == (
        str(refund),
        5_000,
        15_000,
    )
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        5_000,
        due_days(url, prop),
    )
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([5_000], 10_000, 0)
    assert (active_receipts(url, pet), status(url, case["first"])) == (
        [case["second"]],
        "REVERSED",
    )
    assert int(value(url, "SELECT app.lease_deposit_payback_count(%s)", pet)) == count + 5_000
    reconciled(url, customer)
    return_payment(case, case["second"])
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == (
        [5_000, 10_000],
        0,
        0,
    )
    assert (active_receipts(url, pet), status(url, case["second"])) == ([], "REVERSED")
    reconciled(url, customer)


def test_a_shared_deposit_that_still_holds_the_receipt_charges_nothing(
    migrated_database_url: str,
) -> None:
    """A shortfall of 0: 10,000 and 10,000 with a 5,000 Refund (the Deposit holds 15,000). A's
    return plans and writes no recovery, reverses A's receipt through the shared writer although
    the Refund is still out, and the Deposit holds 5,000 of B's money with the Refund unchanged."""
    url = migrated_database_url
    case = shared_case(url, (5_000,))
    pet = case["pet"]
    [refund] = case["refunds"]
    draft = returns().record(
        case["prop"], request(case["first"]), actor=return_preparer(case["human"], case["prop"])
    )
    assert cast(dict[str, Any], draft["payload"])["source"]["recoveries"] == []
    result = returns().confirm(
        case["prop"], draft_id(draft), actor=return_approver(case["human"], case["prop"])
    )
    assert result["recoveries"] == []
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([], 5_000, 5_000)
    assert active_receipts(url, pet) == [case["second"]]
    assert value(url, "SELECT app.deposit_has_unresolved_refund(%s)", pet) is True


def test_the_shortfall_goes_on_the_newest_refund_first(migrated_database_url: str) -> None:
    """Two Refunds, 6,000 and then 9,000 (the Deposit holds 5,000): A's 5,000 shortfall is
    charged back on the newer 9,000 Refund only; the older 6,000 Refund is untouched."""
    url = migrated_database_url
    case = shared_case(url, (6_000, 9_000))
    older, newer = case["refunds"]
    return_payment(case, case["first"])
    assert (recoveries(url, older), recoveries(url, newer)) == ([], [5_000])
    assert (net(url, older), net(url, newer), held(url, case["pet"])) == (6_000, 4_000, 0)


@pytest.mark.parametrize(
    ("share", "refusal"),
    [(5_001, RECOVERED), (4_999, NEGATIVE)],
    ids=["above_the_shortfall", "below_the_shortfall"],
)
def test_the_table_checks_hold_a_share_to_the_shortfall(
    migrated_database_url: str, share: int, refusal: str
) -> None:
    """Hand-built in a rolled-back owner transaction: the plan is replaced so it asks for one cent
    more or less than the 5,000 shortfall of the Q-2026-10-18-127 example, and its planned check
    is switched off. One cent more is refused by the recovery insert check (23514); one cent less
    is refused by the Deposit's held-history check when A's receipt is reversed (23514). Nothing
    is written."""
    url = migrated_database_url
    case = shared_case(url, (15_000,))
    human, prop, pet = case["human"], case["prop"], case["pet"]
    with psycopg.connect(owner()) as connection:
        connection.execute(
            "CREATE OR REPLACE FUNCTION app.payment_return_shared_deposit_recoveries("
            "p_property uuid,p_payment uuid) RETURNS jsonb LANGUAGE sql STABLE "
            "SECURITY DEFINER SET search_path=pg_catalog AS $$ "
            "SELECT COALESCE(jsonb_agg(recovery || jsonb_build_object('amount_usd_cents',"
            f"{int(share)}::bigint,'net_usd_cents',(recovery->>'amount_usd_cents')::bigint,"
            "'shortfall_share',true)),'[]'::jsonb) "
            "FROM jsonb_array_elements(app.payment_return_recoveries(p_property,p_payment)) "
            "recovery $$"
        )
        connection.execute(
            "CREATE OR REPLACE FUNCTION app.assert_payment_return_recoveries_planned("
            "p_source jsonb) RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$"
        )
        draft = uuid4()
        connection.execute(
            "SELECT app.record_payment_return_draft(%s,%s,%s,%s,%s,%s,'payments.reverse')",
            (
                prop,
                human,
                draft,
                case["first"],
                Jsonb({"evidence_reference": "Bank return notice"}),
                "Payment returned by the bank",
            ),
        )
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            connection.execute(
                "SELECT app.confirm_payment_return(%s,%s,%s,'financial.approve')",
                (prop, human, draft),
            )
        assert refused.value.diag.message_primary == refusal
        connection.rollback()
    assert (held(url, pet), active_receipts(url, pet)) == (5_000, [case["first"], case["second"]])


def test_a_shortfall_larger_than_the_newest_refund_reaches_the_older_one(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 3a): Refunds of 12,000 and then 5,000 (the Deposit
    holds 3,000). A's 7,000 shortfall takes the newer Refund's whole 5,000 net and 2,000 of the
    older one; the Deposit ends at 0 and B's receipt stays."""
    url = migrated_database_url
    case = shared_case(url, (12_000, 5_000))
    older, newer = case["refunds"]
    return_payment(case, case["first"])
    assert (recoveries(url, older), recoveries(url, newer)) == ([2_000], [5_000])
    assert (net(url, older), net(url, newer), held(url, case["pet"])) == (10_000, 0, 0)
    assert active_receipts(url, case["pet"]) == [case["second"]]


def joint_shared_case(url: str, to_tenant: int, to_co_signer: int) -> dict[str, Any]:
    """A qualified Pet Deposit of a two-Signer Lease that holds 20,000 from Payment A; its required
    total is raised by 20,000, Payment B's 10,000 receipt is recorded, and then Pet Refund-review
    Refunds go to the Primary Tenant and, with the Signers' written agreement, to the second
    Signer (BR-REFUND-015)."""
    human, prop, _, co_signer, pet, review = joint_qualified(url)
    service = PostgresDepositService(financial_database_url(), prop, human)
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            pet,
            DepositAdjustmentType.INCREASE,
            20_000,
            today(url),
            "Approved required amount",
        ),
        actor=deposit_actor(human, prop),
    )
    receipt = one(url, "SELECT payment_id FROM app.deposit_receipts WHERE deposit_id=%s", pet)
    first = UUID(str(receipt[0]))
    second = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, second, 10_000), actor=allocator(human, prop))
    preparer = actor(human, prop, "refunds.create")
    refunds = refund_service()
    paid = [
        refund_id(
            create_pet_refund(
                refunds, prop, pet_refund_command(pet, review, to_tenant), actor=preparer
            )
        )
    ]
    draft = refunds.record_pet_draft(
        prop,
        pet_refund_command(pet, review, to_co_signer),
        cash(refunds, prop, preparer),
        actor=preparer,
        recipient=SignerRecipient(co_signer, AGREEMENT),
    )
    confirmed = refunds.confirm_draft(
        prop, UUID(str(draft["draft_id"])), actor=actor(human, prop, "financial.approve")
    )
    paid.append(refund_id(cast(dict[str, object], confirmed["refund"])))
    return {
        "human": human,
        "prop": prop,
        "pet": pet,
        "first": first,
        "second": second,
        "refunds": paid,
        "service": service,
    }


def test_two_recipients_keep_the_shared_refusal_while_a_shortfall_is_charged(
    migrated_database_url: str,
) -> None:
    """Q-2026-10-18-134 point 2 (review round 1, both reviewers): A 20,000 and B 10,000, then
    Refunds of 8,000 to the Primary Tenant and 7,000 to the second Signer (the Deposit holds
    15,000, so A's shortfall is 5,000). Who pays depends on the order, so A's return stays refused
    (55000, the shared-Deposit message) and nothing is written; option (d) still refuses a receipt
    from Payment C (55000) and C keeps its value. With Refunds of 3,000 and 2,000 (the Deposit
    holds 25,000, shortfall 0) nobody is charged, so A's return is recorded and confirmed with no
    recovery and the Deposit holds B's 5,000 left."""
    url = migrated_database_url
    case = joint_shared_case(url, 8_000, 7_000)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    assert held(url, pet) == 15_000
    assert return_refused(prop, human, case["first"]) == ("55000", SHARED)
    later = payment(url, human, pet, 5_000)
    assert attempt(prop, human, pet, later, 5_000) == ("55000", REFUND_OUT)
    assert [recoveries(url, refund) for refund in case["refunds"]] == [[], []]
    assert (held(url, pet), status(url, case["first"])) == (15_000, "RECEIVED")
    assert int(value(url, "SELECT app.payment_available_value(%s)", later)) == 5_000

    case = joint_shared_case(url, 3_000, 2_000)
    assert held(url, case["pet"]) == 25_000
    result = return_payment(case, case["first"])
    assert result["recoveries"] == []
    assert [recoveries(url, refund) for refund in case["refunds"]] == [[], []]
    assert (held(url, case["pet"]), status(url, case["first"])) == (5_000, "REVERSED")


def test_a_verified_return_between_the_record_and_the_confirm_makes_the_return_stale(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security should-fix 1b), adapted in review round 2 (option (d) stays, so no
    receipt can come in while the Refund is out): the Q-2026-10-18-127 example's return draft plans
    5,000; then 2,000 of the Refund is verified returned (the Deposit holds 7,000). The confirm is
    stale (P5S02) and writes nothing; the draft is withdrawn and recorded again, plans 3,000, and
    its confirm charges back 3,000, leaves the Refund's net at 10,000 and the Deposit at 0."""
    url = migrated_database_url
    case = shared_case(url, (15_000,))
    human, prop, pet = case["human"], case["prop"], case["pet"]
    [refund] = case["refunds"]
    draft = returns().record(prop, request(case["first"]), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert plan["amount_usd_cents"] == 5_000
    refund_service().verify_usd_return(
        prop, refund, returned(2_000), actor=actor(human, prop, "refunds.correct")
    )
    with pytest.raises(PaymentReturnStaleDraftError):
        returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    assert (recoveries(url, refund), held(url, pet), status(url, case["first"])) == (
        [],
        7_000,
        "RECEIVED",
    )
    drafts().withdraw(
        prop,
        draft_id(draft),
        "The Deposit changed before the confirm",
        prepare_capability="payments.reverse",
        actor=return_preparer(human, prop),
    )
    result = return_payment(case, case["first"])
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert recovered["amount_usd_cents"] == 3_000
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([3_000], 10_000, 0)
    assert active_receipts(url, pet) == [case["second"]]


def test_an_active_forfeiture_is_refused_before_the_shortfall_is_compared(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 1): a Pet Deposit takes 5,000 from each of two
    Payments before a pet noncompliance termination, and its forfeiture keeps all 10,000 (no
    closure). A's return meets a shortfall of 5,000 with no Refund, but it is refused for the
    active forfeiture (55000), as before this sub-slice, not for a missing planned recovery;
    nothing is written."""
    url = migrated_database_url
    case = terminated_pet_lease_case(url, receipts=(5_000, 5_000))
    human, prop, pet = case["human"], case["prop"], case["pet"]
    forfeit_through_draft(PostgresDepositService(financial_database_url(), prop, human), pet)
    assert held(url, pet) == 0
    first = case["payments"][0]
    assert return_refused(prop, human, first) == ("55000", FORFEITED)
    assert status(url, first) == "RECEIVED"


def test_the_shortfall_share_passes_the_recovery_check_only_without_a_settlement(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent note 5), hand-built: a shared Deposit's entry with
    `shortfall_share` passes the recovery check of the PAYMENT_RETURN path (no Settlement) and is
    still refused (55000, the shared-Deposit message) when a Settlement is given; an entry without
    it is refused in both."""
    url = migrated_database_url
    base = {"reservation_outcome": False, "shared_deposit": True}

    def check(entry: dict[str, Any], settlement: UUID | None) -> tuple[Any, Any]:
        with psycopg.connect(url) as connection:
            try:
                connection.execute(
                    "SELECT app.assert_payment_return_recoveries_allowed(%s,%s)",
                    (Jsonb([{**base, **entry}]), settlement),
                )
            except psycopg.Error as refused:
                return refused.sqlstate, refused.diag.message_primary
        return None, None

    assert check({"shortfall_share": True}, None) == (None, None)
    assert check({"shortfall_share": True}, uuid4()) == ("55000", SHARED)
    assert check({}, None) == ("55000", SHARED)


def test_the_shared_deposit_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-1 adds four internal functions that no application role may run and
    patches only the listed functions, by exactly their listed replacements, with the same owner,
    privileges and settings; no constraint or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261230_156"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    for function in NEW:
        assert one(
            migrated_database_url,
            "SELECT has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_financial',p.oid,'EXECUTE') "
            "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
            function,
        ) == (False, False)

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

    with _temporary_migration_database("payment_return_shared_deposit") as temporary:
        alembic_command.upgrade(config, "20261230_156")
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
