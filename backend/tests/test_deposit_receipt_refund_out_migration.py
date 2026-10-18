"""A receipt into a Deposit whose Refund is out is recorded again: the end of option (d) (V1-056
sub-slice 10e-2b-4e-2b-2b).

Owner answer to Q-2026-10-18-127: option (a), and option (d) (no receipt into a Deposit whose
Refund is not fully returned, sub-slice 10e-2b-4d) only until (a) is built. Option (a) is built in
the return before closure (10e-2b-4e-1, 10e-2b-4e-2a), the RETURNED_PAYMENT correction after
closure (10e-2b-4e-2a, 10e-2b-4e-2b-1) and the receipt correction after closure (10e-2b-4e-2b-2a),
so (d) ends. Every test runs on the real path, to the cent: the deliberate one-person path of
Q-127 (4e-1 reading (4)), the known limit that such a receipt cannot be reversed while the Refund
is out (review round 1, Q-2026-10-19-137), a receipt between a return's record and its confirm,
and a receipt recorded while a Refund is out followed by a closure and a bounce (both
corrections).
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

from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    CreatePetDepositCommand,
    DepositAdjustmentType,
    PostgresDepositService,
)
from property_rental.deposit_receipt_reversal import DepositReceiptReversalConflictError
from property_rental.final_settlement import SettlementDepositStep
from property_rental.move_out_inspection import InspectionFinding, RecordMoveOutInspection
from property_rental.payment_return import PaymentReturnStaleDraftError
from test_credit_migration import actor
from test_deposit_migration import deposit_actor
from test_deposit_receipt_leftover_migration import AVAILABLE, REFUND_OUT, UNRESOLVED, WRITER
from test_deposit_receipt_record_migration import (
    DEPENDENT,
    allocator,
    payment,
    pet_case,
    qualify_review,
    receipt_command,
    review_refund,
    written,
)
from test_deposit_receipt_reversal_draft_migration import confirm as confirm_reversal
from test_deposit_receipt_reversal_draft_migration import record as record_reversal
from test_deposit_receipt_reversal_draft_migration import withdraw as withdraw_reversal
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, PET_FIRST, SECURITY
from test_final_settlement_draft_migration import record as record_settlement
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
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, drafts, reconciled, request, returns, status
from test_payment_return_migration import preparer as return_preparer
from test_payment_return_recovery_migration import charge, due_days
from test_payment_return_shared_deposit_migration import (
    active_receipts,
    net,
    recoveries,
    return_payment,
    shared_case,
)
from test_refund_service_migration import returned
from test_refund_service_migration import service as refund_service
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_correction_migration import settlement_row
from test_settlement_deposit_receipt_correction_migration import available
from test_settlement_deposit_receipt_correction_migration import confirm as confirm_correction
from test_settlement_deposit_receipt_correction_migration import record as record_correction
from test_settlement_deposit_receipt_correction_migration import request as correction_request
from test_settlement_deposit_receipt_shared_deposit_migration import receipt_by
from test_settlement_returned_payment_migration import command, confirm, payload, record
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20270104_161"
REVERSALS = (
    "SELECT count(*) FROM app.deposit_receipt_reversals reversal JOIN app.deposit_receipts "
    "receipt ON receipt.id=reversal.deposit_receipt_id WHERE receipt.deposit_id=%s"
)


def test_a_receipt_while_a_refund_is_out_lets_the_bounced_payment_charge_nothing(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-1 reading (4), the deliberate one-person path of Q-2026-10-18-127:
    a Pet Deposit (required 20,000) takes 10,000 from Payment A and pays a 10,000 Pet
    Refund-review Refund (it holds 0); C's 10,000 receipt is recorded while the Refund is out (it
    holds 10,000). A bounces: its return plans and writes no recovery (A's shortfall is 10,000
    less the 10,000 held), reverses A's receipt, and the Deposit holds 0, so the Refund is paid
    from C's money and its net stays 10,000. Then C bounces: the Deposit is no longer shared, so
    C's return charges the whole 10,000 back to the Customer on the Lease, as before."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet, customer, lease = (
        case["human"],
        case["prop"],
        case["pet"],
        case["customer"],
        case["lease"],
    )
    service: PostgresDepositService = case["service"]
    first = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, first, 10_000), actor=allocator(human, prop))
    refund = review_refund(case, qualify_review(case), 10_000)
    assert held(url, pet) == 0
    later = payment(url, human, pet, 10_000)
    service.record_receipt(receipt_command(pet, later, 10_000), actor=allocator(human, prop))
    assert (held(url, pet), value(url, UNRESOLVED, pet), written(url, pet)) == (
        10_000,
        True,
        (2, 2, 2),
    )
    draft = returns().record(prop, request(first), actor=return_preparer(human, prop))
    assert cast(dict[str, Any], draft["payload"])["source"]["recoveries"] == []
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    assert result["recoveries"] == []
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([], 10_000, 0)
    assert (active_receipts(url, pet), status(url, first)) == ([later], "REVERSED")
    reconciled(url, customer)
    result = return_payment(case, later)
    [recovered] = cast(list[dict[str, Any]], result["recoveries"])
    assert charge(url, recovered["invoice_id"]) == (
        customer,
        lease,
        "MISCELLANEOUS_CHARGES",
        "UNPAID",
        10_000,
        due_days(url, prop),
    )
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([10_000], 0, 0)
    assert (active_receipts(url, pet), status(url, later)) == ([], "REVERSED")
    reconciled(url, customer)


def test_a_receipt_recorded_while_a_refund_is_out_is_reversed_only_after_the_refund_returns(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security should-fix 1; a known limit, Q-2026-10-19-137): with (d) gone,
    one staff member can record a Payment into a Pet Deposit whose Refund is out, and before
    closure no receipt reversal undoes it while the Refund is not fully returned. A Pet Deposit
    takes 10,000 from Payment A and pays a 10,000 Pet Refund-review Refund (it holds 0); C's
    10,000 receipt is recorded (it holds 10,000). The confirm of a reversal draft of C's receipt
    is refused (55000, the dependent-history message of the receipt reversal check): nothing is
    written, the Deposit holds 10,000 and C has nothing left. The draft is withdrawn; after a
    verified return of 4,000 (the Deposit holds 14,000, the Refund still out) a new draft is refused
    the same way and withdrawn too (review round 2, independent note 2). Once the Refund is
    returned in full (the Deposit holds 20,000) a new draft's confirm reverses C's receipt: the
    Deposit holds 10,000 and C has its 10,000 back."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    service.record_receipt(
        receipt_command(pet, payment(url, human, pet, 10_000), 10_000),
        actor=allocator(human, prop),
    )
    refund = review_refund(case, qualify_review(case), 10_000)
    later = payment(url, human, pet, 10_000)
    receipt = service.record_receipt(
        receipt_command(pet, later, 10_000), actor=allocator(human, prop)
    ).deposit_receipt_id
    draft = record_reversal(prop, human, receipt)
    with pytest.raises(DepositReceiptReversalConflictError) as refused:
        confirm_reversal(prop, human, receipt, draft["draft_id"])
    cause = refused.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("55000", DEPENDENT)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        0,
        10_000,
        0,
    )
    withdraw_reversal(prop, human, draft["draft_id"])
    refund_service().verify_usd_return(
        prop, refund, returned(4_000), actor=actor(human, prop, "refunds.correct")
    )
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (14_000, True)
    partly = record_reversal(prop, human, receipt)
    with pytest.raises(DepositReceiptReversalConflictError) as refused_again:
        confirm_reversal(prop, human, receipt, partly["draft_id"])
    cause = refused_again.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("55000", DEPENDENT)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        0,
        14_000,
        0,
    )
    withdraw_reversal(prop, human, partly["draft_id"])
    refund_service().verify_usd_return(
        prop, refund, returned(6_000), actor=actor(human, prop, "refunds.correct")
    )
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (20_000, False)
    again = record_reversal(prop, human, receipt)
    confirm_reversal(prop, human, receipt, again["draft_id"])
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        1,
        10_000,
        10_000,
    )


def test_a_receipt_between_a_return_s_record_and_confirm_makes_the_return_stale(
    migrated_database_url: str,
) -> None:
    """The review round 1 set-up 1b of sub-slice 10e-2b-4e-1 (security), which option (d) kept
    off the real path until this sub-slice: Payments A and B fund 10,000 each and a 15,000 Pet
    Refund-review Refund is paid (the Deposit holds 5,000); A's return draft plans 5,000. The
    required total is raised by 5,000 and C's 5,000 receipt is recorded (the Deposit holds
    10,000), so A's confirm is stale (P5S02) and writes nothing. Withdrawn and recorded again,
    the return plans no recovery, and its confirm reverses A's receipt: the Deposit holds 0, the
    Refund's net stays 15,000 and B's and C's receipts stay."""
    url = migrated_database_url
    case = shared_case(url, (15_000,))
    human, prop, pet = case["human"], case["prop"], case["pet"]
    [refund] = case["refunds"]
    draft = returns().record(prop, request(case["first"]), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], draft["payload"])["source"]["recoveries"]
    assert plan["amount_usd_cents"] == 5_000
    service: PostgresDepositService = case["service"]
    service.adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            pet,
            DepositAdjustmentType.INCREASE,
            5_000,
            today(url),
            "Approved required amount",
        ),
        actor=deposit_actor(human, prop),
    )
    third = payment(url, human, pet, 5_000)
    service.record_receipt(receipt_command(pet, third, 5_000), actor=allocator(human, prop))
    assert held(url, pet) == 10_000
    with pytest.raises(PaymentReturnStaleDraftError):
        returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    assert (recoveries(url, refund), held(url, pet), status(url, case["first"])) == (
        [],
        10_000,
        "RECEIVED",
    )
    drafts().withdraw(
        prop,
        draft_id(draft),
        "The Deposit changed before the confirm",
        prepare_capability="payments.reverse",
        actor=return_preparer(human, prop),
    )
    again = returns().record(prop, request(case["first"]), actor=return_preparer(human, prop))
    assert cast(dict[str, Any], again["payload"])["source"]["recoveries"] == []
    result = returns().confirm(prop, draft_id(again), actor=return_approver(human, prop))
    assert result["recoveries"] == []
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([], 15_000, 0)
    assert active_receipts(url, pet) == [case["second"], third]
    assert status(url, case["first"]) == "REVERSED"
    reconciled(url, case["customer"])


def refund_then_receipt_case(url: str) -> dict[str, Any]:
    """A signed Lease starting this month whose 20,000 Pet Deposit takes 10,000 from Payment A
    through the writer and pays a 10,000 Pet Refund-review Refund (it holds 0); then Payment C's
    10,000 receipt is recorded while that Refund is out (it holds 10,000). A move-out inspection
    bills two Damage charges of 12,500 (one pet-related); the Initial Rent is paid and the Lease is
    terminated with no forfeiture ground. The Settlement applies the Pet Deposit's 10,000 to the
    pet damage line and the Security Deposit's 10,000 to the other damage line; then it closes
    (the set-up of `review_refund_case` in sub-slice 10e-2b-4e-2b-1, with C's receipt after the
    Refund)."""
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
    pet = uuid4()
    deposits.create_pet_deposit(
        CreatePetDepositCommand(
            uuid4(), pet, lease, approval, 20_000, day, "Approved signed Lease pet terms"
        ),
        actor=deposit_actor(human, prop),
    )
    first = payment(url, human, pet, 10_000)
    deposits.record_receipt(receipt_command(pet, first, 10_000), actor=allocator(human, prop))
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "service": deposits,
        "first": first,
    }
    case["review_refund"] = review_refund(case, qualify_review(case), 10_000)
    assert held(url, pet) == 0
    second = payment(url, human, pet, 10_000)
    deposits.record_receipt(receipt_command(pet, second, 10_000), actor=allocator(human, prop))
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (10_000, True)
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
            "Evidence-902",
            "Record actual inspection",
            (
                InspectionFinding(pet_finding, "Scratched door by the pet", True),
                InspectionFinding(other_finding, "Broken window latch", False),
            ),
        ),
        actor=inspection_actor(human, prop),
        request_id="refund-out-inspection",
    )
    for name, finding in (("pet_line", pet_finding), ("other_line", other_finding)):
        charge_command = damage(customer, lease, finding)
        invoices().record_one_time_charge(prop, charge_command, actor=invoice_staff(human, prop))
        issued = draft_and_issue(prop, charge_command.charge_id, invoice_staff(human, prop))
        case[name] = line_of(url, issued["id"])
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate(url, human, prop, lease, day, voluntary=False)
    case["settlement"] = start(prop, human, lease)
    steps = (
        SettlementDepositStep(PET_FIRST, pet, LINE, case["pet_line"], 10_000),
        SettlementDepositStep(SECURITY, case["security"], LINE, case["other_line"], 10_000),
    )
    confirm_settlement(case, record_settlement(case, steps))
    case["second"] = second
    case["person"] = correction_approver(url)
    return case


def test_after_closure_a_receipt_recorded_while_a_refund_was_out_is_given_back_by_the_correction(
    migrated_database_url: str,
) -> None:
    """The review round 2 concern of sub-slice 10e-2b-4e-1 (why option (d) stayed until the
    corrections were built): a receipt recorded while a Refund is out, then a closure and a
    bounce. A's 10,000 bounces after closure; the Pet Deposit holds 0, so its shortfall is
    10,000. The RETURNED_PAYMENT correction is not refused: the Settlement's 10,000 application
    is newer than the Pet Refund-review Refund, so it gives back the whole shortfall (reversed,
    nothing kept) and nobody is charged. The pet damage line owes 12,500 again, the Deposit holds
    0, C's receipt stays, the Refund's net stays 10,000, the closed Settlement row is unchanged and
    the ledger reconciles."""
    url = migrated_database_url
    case = refund_then_receipt_case(url)
    pet, pet_line, customer = case["pet"], case["pet_line"], case["customer"]
    first, second, refund = case["first"], case["second"], case["review_refund"]
    [applied] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.deposit_applications WHERE deposit_id=%s", pet)
    ]
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 2_500)
    # Review round 1 (independent note 2): the Security Deposit and the other line too.
    assert (held(url, case["security"]), outstanding(url, case["other_line"])) == (0, 2_500)
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
    # The plan stops at the shortfall: the older review Refund is not a use of it.
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("APPLICATION", str(applied), 10_000, 10_000, 0)
    ]
    assert source["recoveries"] == []
    result = confirm(case, draft)
    assert result["recoveries"] == []
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
    assert (recoveries(url, refund), net(url, refund)) == ([], 10_000)
    assert active_receipts(url, pet) == [second]
    assert (status(url, first), status(url, second)) == ("REVERSED", "RECEIVED")
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


@pytest.mark.parametrize("wrong", ["first", "second"], ids=["a_s_receipt", "c_s_receipt"])
def test_after_closure_the_receipt_correction_gives_back_the_same_shortfall(
    migrated_database_url: str, wrong: str
) -> None:
    """Review round 1 (independent should-fix 2): the owner rule names both corrections, so the
    receipt correction is shown on the set-up of the test above too. One 10,000 receipt was wrong
    and has no right receipt: A's, or (review round 2, independent note 4, the way out the known
    limit names) C's, recorded while the Refund was out. The Pet Deposit holds 0 beside the other
    receipt, so its shortfall is 10,000, given back from the Settlement's newer 10,000 application
    (reversed, nothing kept); nobody is charged. The pet damage line owes 12,500 again, the
    Deposit holds 0, the other receipt stays, the corrected receipt's Payment stays RECEIVED with
    its 10,000 available again, the closed Settlement row is unchanged and the ledger
    reconciles."""
    url = migrated_database_url
    case = refund_then_receipt_case(url)
    pet, pet_line, customer = case["pet"], case["pet_line"], case["customer"]
    refund = case["review_refund"]
    corrected = case[wrong]
    [kept] = [case[name] for name in ("first", "second") if name != wrong]
    [applied] = [
        UUID(str(row[0]))
        for row in rows(url, "SELECT id FROM app.deposit_applications WHERE deposit_id=%s", pet)
    ]
    before_row = settlement_row(url, case["settlement"])
    draft = record_correction(case, correction_request(case, receipt_by(url, pet, corrected)))
    source = payload(url, draft)["source"]
    [plan] = source["shared_deposits"]
    assert (
        plan["deposit_id"],
        plan["shortfall_usd_cents"],
        plan["give_back_usd_cents"],
        plan["payback_first"],
    ) == (str(pet), 10_000, 10_000, False)
    keys = ("kind", "id", "amount_usd_cents", "undo_usd_cents", "kept_usd_cents")
    # Review round 2 (independent note 1): the full list, as in the test above.
    assert [tuple(use[key] for key in keys) for use in plan["uses"]] == [
        ("APPLICATION", str(applied), 10_000, 10_000, 0)
    ]
    assert source["recoveries"] == []
    result = confirm_correction(case, draft)
    assert result["recoveries"] == []
    [reversal] = result["deposit_application_reversal_ids"]
    assert (
        value(
            url,
            "SELECT deposit_application_id FROM app.deposit_application_reversals WHERE id=%s",
            UUID(str(reversal)),
        )
        == applied
    )
    assert result["deposit_application_ids"] == [] and result["new_deposit_receipts"] == []
    assert (held(url, pet), outstanding(url, pet_line)) == (0, 12_500)
    assert (recoveries(url, refund), net(url, refund)) == ([], 10_000)
    assert active_receipts(url, pet) == [kept]
    assert (available(url, corrected), status(url, corrected), status(url, kept)) == (
        10_000,
        "RECEIVED",
        "RECEIVED",
    )
    assert settlement_row(url, case["settlement"]) == before_row
    reconciled(url, customer)


def test_the_refund_out_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-2b-2b patches only the receipt writer, by exactly its one listed
    replacement, with the same owner, privileges and settings; the option (d) refusal is gone
    from it, no other function, constraint or trigger changes, and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270103_160"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert one(
        migrated_database_url,
        "SELECT has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_financial',p.oid,'EXECUTE') "
        "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
        WRITER,
    ) == (False, True)

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

    with _temporary_migration_database("deposit_receipt_refund_out") as temporary:
        alembic_command.upgrade(config, "20270103_160")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {WRITER}
    expected = before_functions[WRITER][0]
    for before, after in revision.module.WRITER_REPLACEMENTS:
        assert expected.count(before) == 1
        expected = expected.replace(before, after)
    assert after_functions[WRITER][0] == expected
    assert after_functions[WRITER][1:] == before_functions[WRITER][1:]
    assert REFUND_OUT in str(before_functions[WRITER][0])
    assert REFUND_OUT not in str(after_functions[WRITER][0])
