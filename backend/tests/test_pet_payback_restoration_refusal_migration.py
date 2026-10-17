"""A forgiven recovery charge is not restored while a forfeiture relies on it (V1-056 sub-slice
10e-2b-4b-2a).

Owner answer (a) to Q-2026-10-17-126 point 1: restoring a forgiven recovery charge is refused
while a forfeiture that relied on the lower count is active. Staff first reverse that forfeiture
with the existing reversal, then restore the charge; the Customer must never owe money that the
Property also keeps. A forfeiture relied on the lower count when it was recorded at or after the
charge's first issue while the charge stood lower than it stands after the restoration (a DEBIT
Adjustment of
its line, the reversal of a credit Adjustment of its line, or the same charge billed again and
issued after a VOID). A forfeiture recorded before the forgiveness never blocks.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from deposit_disposition_test_support import disposition_context, terminate_for_disposition
from lease_deposit_forfeiture_test_support import (
    forfeit_through_draft,
    owner_database_url,
    reverse_through_draft,
)
from property_rental.adjustment_reversal import AdjustmentReversalConflictError
from property_rental.deposit import (
    PostgresDepositService,
    RecordDepositDispositionCommand,
    deposit_request_digest,
)
from property_rental.final_settlement import SettlementDepositStep
from property_rental.invoice import (
    CreateInvoiceDraftCommand,
    InvoiceInvalidError,
    IssueInvoiceCommand,
    VoidInvoiceCommand,
    invoice_request_digest,
)
from refund_test_support import create_pet_refund
from test_adjustment_reversal_migration import adjustments, reversals
from test_adjustment_reversal_migration import approver as reversal_approver
from test_adjustment_reversal_migration import draft_id as reversal_draft_id
from test_adjustment_reversal_migration import preparer as reversal_preparer
from test_adjustment_reversal_migration import request as reversal_request
from test_credit_adjustment_excess_migration import credit as adjust_credit
from test_credit_adjustment_excess_migration import invoices, version
from test_credit_migration import actor
from test_debit_adjustment_line_block_migration import debit
from test_deposit_migration import financial_database_url, seed_historical_deposit_receipt
from test_final_settlement_draft_migration import LINE, PET_REST, STAFF
from test_final_settlement_migration import held, one, outstanding
from test_invoice_migration import invoice_api_actor
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_one_time_charges_migration import staff as invoice_staff
from test_payment_move_migration import rows
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, reconciled, request, returns
from test_payment_return_migration import preparer as return_preparer
from test_pet_payback_recovery_standing_migration import (
    bc_case,
    open_lease_recovery,
    record_own_correction,
    reduce_charge,
    standing,
)
from test_pet_refund_migration import command as pet_refund_command
from test_pet_refund_migration import qualified
from test_refund_service_migration import refund_id
from test_refund_service_migration import service as refund_service
from test_settlement_adjustment_reversal_migration import cause, draft_of
from test_settlement_adjustment_reversal_migration import confirm as confirm_restoration
from test_settlement_adjustment_reversal_migration import record as record_restoration
from test_settlement_deposit_receipt_correction_migration import confirm
from test_settlement_deposit_receipt_payback_forfeiture_migration import payback_count
from test_settlement_deposit_receipt_recovery_line_migration import recovery_line
from test_settlement_extra_charge_migration import state as draft_state
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    record_reversal,
    reversal_command,
)
from test_settlement_returned_payment_migration import receipt_payment

REVISION = "20261227_153"
NEW = {
    "app.refuse_recovery_charge_restoration(uuid)",
    "app.validate_recovery_charge_restoration()",
    "app.validate_forfeiture_recovery_standing()",
}
TRIGGERS = {
    "trigger:app.invoice_adjustments:invoice_adjustments_recovery_restoration:O",
    "trigger:app.invoice_adjustment_reversals:invoice_adjustment_reversals_recovery_restoration:O",
    "trigger:app.invoices:invoices_recovery_restoration_insert:O",
    "trigger:app.invoices:invoices_recovery_restoration_issue:O",
    "trigger:app.deposit_dispositions:deposit_dispositions_recovery_standing:O",
}
STANDING_CHANGED = (
    "A recovery charge of this Pet Deposit changed after this forfeiture's time; record it again"
)
GUARD = "could not serialize access due to concurrent update"
REFUSED = (
    "55000",
    "A forfeiture recorded while this recovery charge was forgiven is still active; "
    "reverse the forfeiture first",
)


def recovered_case(url: str, received: int) -> dict[str, Any]:
    """Before closure, on the sub-slice 10e-1c path: the `qualified` Pet Deposit pays a 15,000 Pet
    Refund-review Refund, its Payment's return recovers it by a 15,000 charge on the signed Lease
    (count 15,000, held 0), and a later receipt of `received` (seeded from another Payment, as the
    committed pay-back fixtures do) refills the Pet Deposit."""
    human, prop, customer, lease, deposit, review = qualified(url)
    refund = refund_id(
        create_pet_refund(
            refund_service(),
            prop,
            pet_refund_command(deposit, review, 15_000),
            actor=actor(human, prop, "refunds.create"),
        )
    )
    payment = receipt_payment(url, deposit)
    draft = returns().record(prop, request(payment), actor=return_preparer(human, prop))
    returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    recovery, line, invoice, obligation = open_lease_recovery(url, refund)
    seed_historical_deposit_receipt(
        url, deposit_id=deposit, actor_id=human, amount_usd_cents=received
    )
    assert (standing(url, recovery), payback_count(url, deposit), held(url, deposit)) == (
        15_000,
        15_000,
        received,
    )
    return {
        "url": url,
        "human": human,
        "prop": prop,
        "customer": customer,
        "lease": lease,
        "deposit": deposit,
        "recovery": recovery,
        "line": line,
        "invoice": invoice,
        "obligation": obligation,
        "service": PostgresDepositService(financial_database_url(), prop, human),
    }


def terminate(case: dict[str, Any]) -> None:
    """The pet noncompliance termination (BR-DEP-022) on the database's business day."""
    url = case["url"]
    [case["day"]] = one(
        url,
        "SELECT timezone(property.timezone_name,statement_timestamp())::date "
        "FROM app.properties property WHERE property.id=%s",
        case["prop"],
    )
    terminate_for_disposition(url, case["service"], case["lease"], case["day"])


def terminate_and_forfeit(case: dict[str, Any]) -> tuple[UUID, int]:
    """The termination, then the forfeiture draft of the held money beyond the pay-back value,
    confirmed under financial.approve; the one active forfeiture is returned."""
    terminate(case)
    forfeit_through_draft(case["service"], case["deposit"])
    [found] = active_forfeitures(case["url"], case["deposit"])
    return found


def active_forfeitures(url: str, deposit: UUID) -> list[tuple[UUID, int]]:
    return [
        (UUID(str(row[0])), int(row[1]))
        for row in rows(
            url,
            "SELECT disposition.id,disposition.amount_usd_cents "
            "FROM app.deposit_dispositions disposition WHERE disposition.deposit_id=%s "
            "AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal "
            "WHERE reversal.deposit_disposition_id=disposition.id) ORDER BY disposition.id",
            deposit,
        )
    ]


def void(case: dict[str, Any]) -> None:
    url, prop, invoice = case["url"], case["prop"], case["invoice"]
    invoices().void(
        prop,
        invoice,
        VoidInvoiceCommand(uuid4(), "Issued in error", version(url, invoice)),
        actor=invoice_api_actor(case["human"], prop),
    )


def billed_again(case: dict[str, Any]) -> UUID:
    """The same charge on a new DRAFT Invoice (not owed yet, so not a restoration)."""
    who = invoice_staff(case["human"], case["prop"])
    draft = invoices().create_draft(
        case["prop"], CreateInvoiceDraftCommand(uuid4(), case["obligation"]), actor=who
    )
    return UUID(str(draft["id"]))


def issue(case: dict[str, Any], invoice: UUID) -> dict[str, object]:
    return invoices().issue(
        case["prop"],
        invoice,
        IssueInvoiceCommand(uuid4(), version(case["url"], invoice)),
        actor=invoice_staff(case["human"], case["prop"]),
    )


def state(case: dict[str, Any]) -> tuple[int, int, int]:
    url = case["url"]
    return (
        standing(url, case["recovery"]),
        payback_count(url, case["deposit"]),
        held(url, case["deposit"]),
    )


def one_call(case: dict[str, Any], amount: int) -> tuple[str, tuple[object, ...]]:
    """The owner's one-call Lease Deposit disposition with its termination context (BR-DEP-022),
    as SQL for a connection of the test's own."""
    context = disposition_context(case["url"], case["deposit"])
    command = RecordDepositDispositionCommand(
        uuid4(),
        uuid4(),
        case["deposit"],
        case["lease"],
        amount,
        case["day"],
        "Approved BR-DEP-022 source",
        context=context,
    )
    return (
        "SELECT app.record_lease_deposit_disposition_with_context("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case["prop"],
            case["human"],
            command.idempotency_key,
            deposit_request_digest("deposit.disposition.record", command),
            command.disposition_id,
            command.deposit_id,
            command.governing_lease_id,
            command.amount_usd_cents,
            command.effective_date,
            command.reason,
            command.authorization_reference,
            context.termination_event_id,
            context.governing_rule,
            context.expected_state_version,
        ),
    )


def issue_sql(case: dict[str, Any], invoice: UUID) -> tuple[str, tuple[object, ...]]:
    """The Invoice issue the service sends, as SQL for a connection of the test's own."""
    current = version(case["url"], invoice)
    digest = invoice_request_digest(
        action="issue",
        property_id=case["prop"],
        invoice_id=invoice,
        payload={"expected_version": current},
    )
    return (
        "SELECT app.issue_invoice(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            case["prop"],
            invoice,
            case["human"],
            uuid4(),
            digest,
            current,
            uuid4(),
            uuid4(),
            None,
            None,
        ),
    )


def run(url: str, statement: tuple[str, tuple[object, ...]]) -> None:
    with psycopg.connect(url) as connection:
        connection.execute(*statement)


def owner() -> str:
    return owner_database_url(financial_database_url())


def wait_until_blocked_by(url: str, holder: psycopg.Connection[Any]) -> None:
    """Wait until another backend waits for a lock that `holder` holds."""
    with psycopg.connect(url, autocommit=True) as observer:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if observer.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity "
                "WHERE %s=ANY(pg_catalog.pg_blocking_pids(pid)))",
                (holder.info.backend_pid,),
            ).fetchone() == (True,):
                return
            time.sleep(0.01)
    raise AssertionError("the other transaction must wait for the Deposit lock")


def test_a_charge_billed_again_after_a_void_waits_until_the_forfeiture_is_reversed(
    migrated_database_url: str,
) -> None:
    """The 10e-2b-4b-1 security set-up B2 on the real path: a 15,000 Pet receipt refills the Pet
    Deposit (count 15,000, all pay-back money). A VOID of the recovery charge's Invoice forgives
    it (count 0), so the BR-DEP-022 forfeiture takes all 15,000. The same charge billed again would
    make the Customer owe 15,000 that the Property keeps: its issue is refused (55000; the Invoice
    stays a DRAFT and nothing else changes). Once the forfeiture is reversed with the 6b draft,
    the issue passes: the charge stands again and the 15,000 the Pet Deposit holds is pay-back
    money (DL-032 would apply it to that charge)."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    assert state(case) == (0, 0, 15_000)
    disposition, amount = terminate_and_forfeit(case)
    assert (amount, state(case)) == (15_000, (0, 0, 0))
    again = billed_again(case)
    with pytest.raises(InvoiceInvalidError) as failure:
        issue(case, again)
    assert cause(failure) == REFUSED
    assert one(url, "SELECT status,issued_at FROM app.invoices WHERE id=%s", again) == (
        "DRAFT",
        None,
    )
    assert state(case) == (0, 0, 0)
    assert active_forfeitures(url, case["deposit"]) == [(disposition, 15_000)]
    reverse_through_draft(case["service"], disposition)
    assert active_forfeitures(url, case["deposit"]) == []
    assert issue(case, again)["status"] == "UNPAID"
    assert state(case) == (15_000, 15_000, 15_000)
    reconciled(url, case["customer"])


def test_a_debit_and_an_adjustment_reversal_wait_until_the_forfeiture_is_reversed(
    migrated_database_url: str,
) -> None:
    """A credit Adjustment forgives 4,000 of the 15,000 recovery charge (count 11,000), so the
    forfeiture takes the 4,000 of the 15,000 held money beyond it. A DEBIT Adjustment of the
    charge's line and the 10f-1 reversal of that credit (confirmed under financial.approve) would
    each restore the charge: both are refused (55000), the line keeps its value and the reversal
    draft stays pending. Once the forfeiture is reversed, the same reversal draft confirms (count
    15,000) and a later DEBIT passes."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    human, prop, line, invoice = case["human"], case["prop"], case["line"], case["invoice"]
    adjust_credit(url, human, prop, invoice, line, 4_000)
    assert state(case) == (11_000, 11_000, 15_000)
    disposition, amount = terminate_and_forfeit(case)
    assert (amount, state(case)) == (4_000, (11_000, 11_000, 11_000))
    with pytest.raises(InvoiceInvalidError) as failure:
        debit(url, human, prop, invoice, line, 1_000)
    assert cause(failure) == REFUSED
    assert (outstanding(url, line), adjustments(url, line, "DEBIT")) == (11_000, [])
    [adjustment] = adjustments(url, line)
    recorded = reversals().record(
        prop, reversal_request(adjustment), actor=reversal_preparer(human, prop)
    )
    with pytest.raises(AdjustmentReversalConflictError) as refused:
        reversals().confirm(prop, reversal_draft_id(recorded), actor=reversal_approver(human, prop))
    assert cause(refused) == REFUSED
    reversal_rows = (
        "SELECT count(*) FROM app.invoice_adjustment_reversals WHERE invoice_adjustment_id=%s"
    )
    assert one(url, reversal_rows, adjustment) == (0,)
    assert draft_state(url, reversal_draft_id(recorded)) == "PENDING"
    assert state(case) == (11_000, 11_000, 11_000)
    reverse_through_draft(case["service"], disposition)
    assert state(case) == (11_000, 11_000, 15_000)
    reversals().confirm(prop, reversal_draft_id(recorded), actor=reversal_approver(human, prop))
    assert one(url, reversal_rows, adjustment) == (1,)
    assert state(case) == (15_000, 15_000, 15_000)
    debit(url, human, prop, invoice, line, 1_000)
    assert (outstanding(url, line), state(case)) == (16_000, (15_000, 15_000, 15_000))
    reconciled(url, case["customer"])


def test_a_forfeiture_recorded_before_the_forgiveness_does_not_block_a_restoration(
    migrated_database_url: str,
) -> None:
    """A 20,000 receipt with the 15,000 count: the forfeiture takes the 5,000 beyond the count
    while the charge stands whole, so it never relied on a lower count. A VOID and the same charge
    billed again then pass (count 15,000 again). Hand-built and rolled back: the refusal function
    passes for that forfeiture; one timed before the charge's first issue never blocks (review round
    1, independent S3: standing at that time is 0, so without that filter it would refuse); one
    timed at or after the restoring transaction's start is refused (it committed while that
    transaction ran, so its own check could not see the restoration)."""
    url = migrated_database_url
    case = recovered_case(url, 20_000)
    disposition, amount = terminate_and_forfeit(case)
    assert (amount, state(case)) == (5_000, (15_000, 15_000, 15_000))
    with psycopg.connect(url) as connection:
        refuse = "SELECT app.refuse_recovery_charge_restoration(%s)"
        connection.execute(refuse, (case["obligation"],))
        connection.execute("ALTER TABLE app.deposit_dispositions DISABLE TRIGGER USER")
        retime = "UPDATE app.deposit_dispositions SET occurred_at=%s WHERE id=%s"
        first_issue = connection.execute(
            "SELECT issued_at FROM app.invoices WHERE id=%s", (case["invoice"],)
        ).fetchone()
        assert first_issue is not None
        connection.execute(retime, (first_issue[0] - timedelta(microseconds=1), disposition))
        assert connection.execute(
            "SELECT app.refund_recovery_standing_at(%s,%s)",
            (case["recovery"], first_issue[0] - timedelta(microseconds=1)),
        ).fetchone() == (0,)
        connection.execute(refuse, (case["obligation"],))
        connection.execute(
            "UPDATE app.deposit_dispositions SET occurred_at=clock_timestamp() WHERE id=%s",
            (disposition,),
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as failure:
            connection.execute(refuse, (case["obligation"],))
        assert failure.value.diag.message_primary == REFUSED[1]
        connection.rollback()
    void(case)
    assert state(case) == (0, 0, 15_000)
    again = billed_again(case)
    assert issue(case, again)["status"] == "UNPAID"
    assert state(case) == (15_000, 15_000, 15_000)
    assert active_forfeitures(url, case["deposit"]) == [(disposition, 5_000)]
    reconciled(url, case["customer"])


def test_after_closure_a_charge_reduction_is_not_reversed_while_its_forfeiture_is_active(
    migrated_database_url: str,
) -> None:
    """After closure, the 10e-2b-4b-1 set-up of owner answer 5 to the 10e-2b-4a report: a
    CHARGE_REDUCTION of the whole unpaid 2,000 recovery charge of the Pet Refund-review Refund
    lowers the own-Deposit count to 3,000, so a receipt correction of the 5,000 Pet receipt with a
    4,500 right receipt forfeits 1,500 on BR-DEP-022. The 10f-2 ADJUSTMENT_REVERSAL correction of
    that reduction would make the Customer owe the 2,000 again while the Property keeps the 1,500:
    its confirm is refused (55000), writes nothing and the draft stays pending. Once a
    FORFEITURE_REVERSAL correction reverses the forfeiture (its 1,500 pays the open recovery charge
    of the Security Refund, DL-032), the same draft confirms and the 2,000 is owed again."""
    url = migrated_database_url
    case = bc_case(url)
    pet, review_line = case["pet"], case["review_line"]
    reduce_charge(case, review_line, 2_000)
    steps = (SettlementDepositStep(PET_REST, pet, LINE, case["settled_line"], 3_000),)
    confirm(case, record_own_correction(case, steps))
    [(forfeiture, forfeited)] = active_forfeitures(url, pet)
    assert forfeited == 1_500
    [reduced] = adjustments(url, review_line)
    corrections = (
        "SELECT count(*) FROM app.settlement_corrections WHERE final_settlement_id=%s",
        case["settlement"],
    )
    before = (one(url, *corrections), outstanding(url, review_line), held(url, pet))
    restoring = draft_of(record_restoration(case, reduced))
    with pytest.raises(AdjustmentReversalConflictError) as failure:
        confirm_restoration(case, restoring)
    assert cause(failure) == REFUSED
    assert draft_state(url, restoring) == "PENDING"
    assert one(
        url,
        "SELECT count(*) FROM app.invoice_adjustment_reversals WHERE invoice_adjustment_id=%s",
        reduced,
    ) == (0,)
    assert (one(url, *corrections), outstanding(url, review_line), held(url, pet)) == before
    assert outstanding(url, review_line) == 0
    assert active_forfeitures(url, pet) == [(forfeiture, 1_500)]
    # Review round 1 (both reviewers): staff reverse the forfeiture first with a
    # FORFEITURE_REVERSAL correction (the 1,500 follows DL-032 onto the open recovery charge of
    # the Security Refund); then the same reversal draft confirms and the 2,000 is owed again.
    real_line = recovery_line(url, case["refund"])[0]
    case["disposition"] = forfeiture
    step = SettlementDepositStep(PET_REST, pet, LINE, real_line, 1_500)
    confirm_reversal(case, record_reversal(case, reversal_command(case, step, pet_remainder=STAFF)))
    assert (active_forfeitures(url, pet), held(url, pet)) == ([], 0)
    confirm_restoration(case, restoring)
    assert (outstanding(url, review_line), draft_state(url, restoring)) == (2_000, "CONFIRMED")
    reconciled(url, case["customer"])


def test_a_forgiveness_committed_while_a_forfeiture_waits_refuses_that_forfeiture(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent S1, the reviewer's set-up): a forfeiture is timed by its
    statement's start, before it waits for the Deposit lock and reads the count, and a forgiveness
    takes no Deposit lock. With the 15,000 count covering the 15,000 held, the owner's one-call
    forfeiture of 15,000 waits for the Deposit lock; meanwhile a VOID of the recovery charge
    commits (count 0), so its count read would allow all 15,000 while its time says the charge
    still stood. Its own insert refuses it (40001, record it again) and nothing is written. Recorded
    again, it is timed after the VOID and passes; the charge billed again is then refused."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    terminate(case)
    with psycopg.connect(url) as holder:
        holder.execute("SELECT 1 FROM app.deposits WHERE id=%s FOR UPDATE", (case["deposit"],))
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(run, owner(), one_call(case, 15_000))
            wait_until_blocked_by(url, holder)
            void(case)
            holder.rollback()
            with pytest.raises(psycopg.errors.SerializationFailure) as failure:
                waiting.result(timeout=60)
    assert failure.value.diag.message_primary == STANDING_CHANGED
    assert (active_forfeitures(url, case["deposit"]), state(case)) == ([], (0, 0, 15_000))
    run(owner(), one_call(case, 15_000))
    assert [amount for _, amount in active_forfeitures(url, case["deposit"])] == [15_000]
    with pytest.raises(InvoiceInvalidError) as refused:
        issue(case, billed_again(case))
    assert cause(refused) == REFUSED
    reconciled(url, case["customer"])


def test_a_forfeiture_timed_before_a_charge_issued_ahead_of_the_clock_is_refused(
    migrated_database_url: str,
) -> None:
    """Review round 2 (security S1, hand-built and rolled back): a recovery charge can be issued at
    a time chained ahead of the clock (by up to about 5 seconds), and a forfeiture timed before that
    issue still reads the charge in its count. Here the forgiven (VOID) recovery charge's issue is
    moved 30 seconds ahead: the owner's one-call forfeiture of 15,000, which its count of 0 would
    allow, is refused by its own insert (40001, record it again), so the restoration check's
    first-issue filter never drops a forfeiture that read the charge."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    terminate(case)
    statement = one_call(case, 15_000)
    with psycopg.connect(url) as connection:
        connection.execute("ALTER TABLE app.invoices DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.invoices SET issued_at=moved.at,updated_at=GREATEST(updated_at,moved.at) "
            "FROM (SELECT clock_timestamp()+interval '30 seconds' AS at) moved WHERE id=%s",
            (case["invoice"],),
        )
        connection.execute("ALTER TABLE app.invoices ENABLE TRIGGER USER")
        with pytest.raises(psycopg.errors.SerializationFailure) as failure:
            connection.execute(*statement)
        assert failure.value.diag.message_primary == STANDING_CHANGED
        connection.rollback()
    assert (active_forfeitures(url, case["deposit"]), state(case)) == ([], (0, 0, 15_000))


def test_a_restoration_and_a_forfeiture_racing_for_the_deposit_lock_never_both_commit(
    migrated_database_url: str,
) -> None:
    """Review round 1 (both reviewers): the restoration check takes the Pet Deposit's lock, which
    every forfeiture insert takes. Forfeiture first: the owner's 15,000 one-call forfeiture after
    the VOID (count 0) is written but not committed; the issue of the charge billed again waits for
    the lock and, once the forfeiture commits, is refused (55000; the Invoice stays a DRAFT).
    Restoration first, after the forfeiture is reversed: the issue is written but not committed
    (it holds the lock); the 15,000 one-call forfeiture waits and, once the issue commits, reads the
    15,000 count and is refused (23514, it would forfeit returned pay-back money)."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    terminate(case)
    again = billed_again(case)
    with psycopg.connect(owner()) as forfeiting:
        forfeiting.execute(*one_call(case, 15_000))
        with ThreadPoolExecutor(1) as pool:
            issuing = pool.submit(issue, case, again)
            wait_until_blocked_by(url, forfeiting)
            forfeiting.commit()
            with pytest.raises(InvoiceInvalidError) as failure:
                issuing.result(timeout=60)
    assert cause(failure) == REFUSED
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", again) == ("DRAFT",)
    [(disposition, amount)] = active_forfeitures(url, case["deposit"])
    assert (amount, state(case)) == (15_000, (0, 0, 0))
    reverse_through_draft(case["service"], disposition)
    with psycopg.connect(owner()) as issuing_first:
        issuing_first.execute(*issue_sql(case, again))
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(run, owner(), one_call(case, 15_000))
            wait_until_blocked_by(url, issuing_first)
            issuing_first.commit()
            with pytest.raises(psycopg.errors.CheckViolation) as refused:
                waiting.result(timeout=60)
    assert refused.value.diag.message_primary == (
        "Lease Deposit disposition would forfeit returned pay-back money"
    )
    assert (active_forfeitures(url, case["deposit"]), state(case)) == (
        [],
        (15_000, 15_000, 15_000),
    )
    reconciled(url, case["customer"])


def test_at_repeatable_read_the_later_writer_fails_on_the_deposit_guard(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security S1): a writer that keeps an older REPEATABLE READ snapshot fails
    on the Pet Deposit's serialization guard (40001) when the other side committed after that
    snapshot: an issue of the charge billed again after a committed forfeiture, and a forfeiture
    after a committed issue. Nothing is written by the failed side."""
    url = migrated_database_url
    case = recovered_case(url, 15_000)
    void(case)
    terminate(case)
    again = billed_again(case)
    with psycopg.connect(owner()) as reading:
        reading.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        reading.execute("SELECT 1")
        run(owner(), one_call(case, 15_000))
        with pytest.raises(psycopg.errors.SerializationFailure) as issued:
            reading.execute(*issue_sql(case, again))
        # The Deposit guard, not the forfeiture's own recovery check (review round 2).
        assert issued.value.diag.message_primary == GUARD
        reading.rollback()
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", again) == ("DRAFT",)
    [(disposition, _)] = active_forfeitures(url, case["deposit"])
    reverse_through_draft(case["service"], disposition)
    with psycopg.connect(owner()) as reading:
        reading.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        reading.execute("SELECT 1")
        assert issue(case, again)["status"] == "UNPAID"
        with pytest.raises(psycopg.errors.SerializationFailure) as forfeited:
            reading.execute(*one_call(case, 15_000))
        assert forfeited.value.diag.message_primary == GUARD
        reading.rollback()
    assert (active_forfeitures(url, case["deposit"]), state(case)) == (
        [],
        (15_000, 15_000, 15_000),
    )
    reconciled(url, case["customer"])


def test_the_restoration_refusal_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4b-2a adds three internal functions (no grant to any application role or
    PUBLIC, SECURITY DEFINER with the fixed search path), four deferred constraint triggers and one
    AFTER INSERT trigger on the forfeiture table, changes no existing function, constraint or
    trigger and is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261226_152"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert set(revision.module.INTERNAL) == NEW
    for function in NEW:
        assert one(
            migrated_database_url,
            "SELECT p.prosecdef,p.proconfig::text,"
            "has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
            "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE'),"
            "p.proacl IS NOT NULL AND p.proacl::text !~ '(^|[{,])=X' "
            "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
            function,
        ) == (True, "{search_path=pg_catalog}", False, False, False, True), function
    deferred = (
        "SELECT t.tgname,t.tgdeferrable,t.tginitdeferred FROM pg_catalog.pg_trigger t "
        "WHERE t.tgname LIKE '%%recovery_restoration%%' ORDER BY t.tgname"
    )
    assert rows(migrated_database_url, deferred) == [
        ("invoice_adjustment_reversals_recovery_restoration", True, True),
        ("invoice_adjustments_recovery_restoration", True, True),
        ("invoices_recovery_restoration_insert", True, True),
        ("invoices_recovery_restoration_issue", True, True),
    ]

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str]]:
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

    with _temporary_migration_database("pet_payback_restoration_refusal") as temporary:
        alembic_command.upgrade(config, "20261226_152")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others | TRIGGERS
    assert set(after_functions) == set(before_functions) | NEW
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set()
    assert cast(str, revision.module.SQL).count("CREATE CONSTRAINT TRIGGER") == len(TRIGGERS) - 1
    assert cast(str, revision.module.SQL).count("CREATE TRIGGER ") == 1
