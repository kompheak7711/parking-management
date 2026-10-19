"""The ordinary Credit Refund draft and money a correction brought back (V1-056 sub-slice 10h-1b).

Owner answer (b) to Q-2026-10-19-141: money that a post-settlement correction brought back into a
Customer Credit (a returned Refund recorded by a correction) leaves only through a correction of
that Final Settlement, so the Customer's open debt on the Lease is paid first (DL-032,
BR-SETTLE-004, BR-SETTLE-013). The ordinary Credit Refund draft (BR-CREDIT-011; the Credit
Customer variant of BR-CREDIT-014) is refused at record and at confirm for that money, and the
draft stays pending; money a Customer's Credit holds for other reasons stays refundable through it.
Owner answer (a) to Q-2026-10-19-144: the one-call Credit reversal, which would move that money
back to its Payment, is refused while it is there, unless a correction of that Settlement links
the reversal.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

from payment_test_support import seed_payment
from property_rental.credit import (
    CLOSED_SETTLEMENT_CHANGE,
    CreditConflictError,
    ReverseCreditCommand,
)
from property_rental.final_settlement import SettlementCreditStep
from property_rental.refund import (
    CreateUsdRefundCommand,
    RefundConflictError,
    RefundInvalidError,
    RefundMethodChoice,
)
from refund_test_support import approver as refund_approver
from refund_test_support import cash, create_usd_refund
from test_credit_customer_refund_migration import command as credit_customer_refund
from test_credit_migration import actor as refund_actor
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import LINE, leaving_case
from test_final_settlement_migration import one, outstanding
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_pet_payback_restoration_refusal_migration import wait_until_blocked_by
from test_refund_service_migration import refund_id
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver
from test_settlement_correction_plan_migration import new_credit
from test_settlement_extra_charge_migration import approving, cause, corrections
from test_settlement_held_value_refund_migration import (
    COUNTS,
    RETURNED_CREDIT,
    confirm_held,
    credit_left,
    held_command,
    record_held,
    return_only,
)
from test_settlement_refund_correction_migration import (
    apply_credit,
    really_close,
    third_party_payment,
    unpaid_charge,
)
from test_settlement_refund_correction_migration import correction as refund_correction
from test_settlement_refund_correction_migration import record as record_refund_correction
from test_settlement_refund_return_migration import available, refunded_case, return_command
from test_settlement_refund_return_migration import record as record_return
from test_settlement_returned_value_other_settlements_migration import second_lease

REVISION = "20270109_166"
INTERNAL = (
    "app.credit_settlement_returned_value_by_settlement(uuid)",
    "app.credit_settlement_returned_value_left(uuid)",
    "app.refuse_credit_refund_of_returned_value(uuid,bigint)",
    "app.refuse_returned_credit_reversal()",
)
TRIGGER = "app.customer_credit_reversals:customer_credit_reversals_returned_value"
RECORD = "app.record_refund_draft(uuid,uuid,uuid,text,text,uuid,uuid,bigint,text,uuid,text,text)"
RECORD_CREDIT_CUSTOMER = (
    "app.record_credit_customer_refund_draft(uuid,uuid,uuid,uuid,bigint,text,uuid,text,text)"
)
CONFIRM = "app.confirm_refund_draft(uuid,uuid,uuid,text)"
NO_LONGER_AVAILABLE = "Refund draft amount is no longer available"


def returned_left(url: str, credit: object) -> int:
    """What every post-settlement return into the Credit has left by the returned-value count."""
    return int(one(url, "SELECT app.credit_settlement_returned_value_left(%s)", credit)[0])


def decisions(url: str, draft: object) -> int:
    return int(
        one(url, "SELECT count(*) FROM app.financial_draft_decisions WHERE draft_id=%s", draft)[0]
    )


def draft_of(found: dict[str, object]) -> UUID:
    return UUID(str(found["draft_id"]))


def reversals(url: str, credit: object) -> int:
    return int(
        one(
            url,
            "SELECT count(*) FROM app.customer_credit_reversals WHERE customer_credit_id=%s",
            credit,
        )[0]
    )


def reverse(case: dict[str, Any], credit: UUID) -> dict[str, object]:
    """The one-call Credit reversal through the Credit service (credits.reverse)."""
    return credits().reverse(
        case["prop"],
        credit,
        ReverseCreditCommand(uuid4(), "Wrong recognition"),
        actor=refund_actor(case["human"], case["prop"], "credits.reverse"),
    )


def hand_built_refund_draft(case: dict[str, Any], payload: dict[str, object]) -> UUID:
    """A waiting Credit Refund draft written by the owner connection through
    app.insert_financial_draft with the payload its recorder would store. Since sub-slice 10h-1b
    the recorder refuses money a correction brought back, and a Refund draft recorded before the
    return blocks the return-only correction ("A draft on a source of this Final Settlement is
    waiting"), so only a hand-built draft reaches the confirm's refusal (as the owner answers to
    Q-2026-10-18-131 and Q-2026-10-19-142 allowed)."""
    draft = uuid4()
    with psycopg.connect(case["url"]) as connection:
        connection.execute(
            "SELECT app.insert_financial_draft(%s,%s,%s,'REFUND','refunds.create',%s,NULL,%s)",
            (case["prop"], case["human"], draft, Jsonb(payload), payload["reason"]),
        )
    return draft


def credit_payload(
    credit: UUID, amount: int, method: RefundMethodChoice, **variant: object
) -> dict[str, object]:
    """The payload of an ordinary Credit Refund draft (variant USD unless given)."""
    return {
        "variant": "USD",
        "source_kind": "CREDIT",
        "source_id": str(credit),
        "amount_usd_cents": amount,
        "reason": "Customer asked",
        "refund_method_id": str(method.refund_method_id),
        "reference_note": method.reference_note,
        **variant,
    }


def test_returned_credit_money_is_refunded_only_through_a_correction(
    migrated_database_url: str,
) -> None:
    """The owner's example: a correction's 2,000 Credit Refund comes back through a return-only
    correction X1, so the Credit holds 2,000 and X1 has 2,000 left. An ordinary Credit Refund draft
    is refused at record, even for 1 cent, and a waiting one (hand-built) is refused at its confirm
    and stays pending; nothing is written. The Customer then owes a 1,500 charge: a held-value
    Refund naming X1 pays it first and refunds the other 500, so nothing is left; an ordinary
    draft is then recorded again, and its confirm is stale (the Credit holds nothing)."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    staff = refund_actor(case["human"], case["prop"], "refunds.create")
    method = cash(refunds(), case["prop"], staff)
    earlier = return_only(case, refund, 2_000)
    assert (
        available(url, credit),
        credit_left(url, earlier, credit),
        returned_left(url, credit),
    ) == (2_000, 2_000, 2_000)
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as recorded:
        refunds().record_usd_draft(
            case["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 1, "Customer asked"),
            method,
            actor=staff,
        )
    assert cause(recorded) == ("P5S01", RETURNED_CREDIT)
    # Review round 1 (security N4): the fourteen-argument overload with no Signer delegates to
    # the twelve-argument recorder, so it is refused the same way.
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as fourteen:
        connection.execute(
            "SELECT app.record_refund_draft(%s,%s,%s,'USD','CREDIT',%s,NULL,1,'Customer asked',"
            "%s,%s,'refunds.create',NULL,NULL)",
            (
                case["prop"],
                case["human"],
                uuid4(),
                credit,
                method.refund_method_id,
                method.reference_note,
            ),
        )
    assert (fourteen.value.sqlstate, fourteen.value.diag.message_primary) == (
        "P5S01",
        RETURNED_CREDIT,
    )
    assert one(url, COUNTS) == counted
    waiting = hand_built_refund_draft(case, credit_payload(credit, 500, method))
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as confirmed:
        refunds().confirm_draft(case["prop"], waiting, actor=refund_approver(staff, case["prop"]))
    assert cause(confirmed) == ("P5S01", RETURNED_CREDIT)
    assert one(url, COUNTS) == counted
    assert decisions(url, waiting) == 0
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.withdraw_financial_draft(%s,%s,%s,%s,'refunds.create')",
            (case["prop"], case["human"], waiting, "Paid out through the correction"),
        )
    _, charge_line = unpaid_charge(url, case, case["person"])
    result = confirm_held(
        case,
        record_held(
            case,
            held_command(case, earlier, SettlementCreditStep(credit, LINE, charge_line, 1_500)),
        ),
    )
    [paid] = result["refunds"]
    assert (paid["recipient_customer_id"], paid["amount_usd_cents"]) == (str(customer), 500)
    assert (
        available(url, credit),
        outstanding(url, charge_line),
        returned_left(url, credit),
    ) == (0, 0, 0)
    later = refunds().record_usd_draft(
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 1, "Customer asked again"),
        method,
        actor=staff,
    )
    with pytest.raises(RefundInvalidError) as stale:
        refunds().confirm_draft(
            case["prop"], draft_of(later), actor=refund_approver(staff, case["prop"])
        )
    assert cause(stale) == ("P5202", NO_LONGER_AVAILABLE)
    assert decisions(url, draft_of(later)) == 0


def test_other_credit_money_stays_refundable_through_the_ordinary_draft(
    migrated_database_url: str,
) -> None:
    """Money a Customer's Credit holds for other reasons stays refundable: while the Credit a
    correction returned 300 into refuses an ordinary Refund of 1 cent, the same Customer's own
    300 of Credit (recognized after the closure, no return in it) is refunded in full through the
    ordinary draft. The refusal compares the amount with the Credit's available value less what
    the returns left, so on the returned Credit (300 held, 300 left) no amount above 0 passes."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit = case["refund"], case["refund_credit"]
    staff = refund_actor(case["human"], case["prop"], "refunds.create")
    return_only(case, refund, 300)
    assert (available(url, credit), returned_left(url, credit)) == (300, 300)
    assert (available(url, case["new_credit"]), returned_left(url, case["new_credit"])) == (300, 0)
    with pytest.raises(RefundConflictError) as refused:
        create_usd_refund(
            refunds(),
            case["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 1, "Customer asked"),
            actor=staff,
        )
    assert cause(refused) == ("P5S01", RETURNED_CREDIT)
    paid = create_usd_refund(
        refunds(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", case["new_credit"], 300, "Customer asked"),
        actor=staff,
    )
    assert one(
        url,
        "SELECT source_customer_credit_id,usd_accounting_value_cents FROM app.refunds WHERE id=%s",
        refund_id(paid),
    ) == (case["new_credit"], 300)
    assert (available(url, case["new_credit"]), available(url, credit)) == (0, 300)
    with psycopg.connect(url) as connection:
        connection.execute("SELECT app.refuse_credit_refund_of_returned_value(%s,0)", (credit,))
        with pytest.raises(psycopg.Error) as one_cent:
            connection.execute("SELECT app.refuse_credit_refund_of_returned_value(%s,1)", (credit,))
    assert (one_cent.value.sqlstate, one_cent.value.diag.message_primary) == (
        "P5S01",
        RETURNED_CREDIT,
    )


def test_a_third_party_credit_s_returned_money_is_not_refunded_by_the_credit_customer_draft(
    migrated_database_url: str,
) -> None:
    """BR-CREDIT-014: a correction's Credit Refund to the Invoice Customer of value released from
    a third-party Payment comes back through a return-only correction (200). A Credit Customer
    draft is refused at record, and a waiting one (hand-built) is refused at its confirm and stays
    pending; nothing is written."""
    url = migrated_database_url
    case = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    case["person"] = approver(url)
    really_close(case)
    invoice, line = unpaid_charge(url, case, case["person"])
    third_party_payment(url, case, invoice, line, 1_500)
    result = cast(
        dict[str, Any],
        corrections().confirm_refund(
            case["prop"],
            record_refund_correction(case, refund_correction(case, invoice, line, 500)),
            actor=approving(case["person"], case["prop"]),
        ),
    )
    [paid] = result["refunds"]
    refund, credit = UUID(str(paid["id"])), UUID(str(paid["source_customer_credit_id"]))
    staff = refund_actor(case["human"], case["prop"], "refunds.create")
    method = cash(refunds(), case["prop"], staff)
    return_only(case, refund, 200)
    assert (available(url, credit), returned_left(url, credit)) == (200, 200)
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as recorded:
        refunds().record_credit_customer_draft(
            case["prop"], credit_customer_refund(credit, 100), method, actor=staff
        )
    assert cause(recorded) == ("P5S01", RETURNED_CREDIT)
    assert one(url, COUNTS) == counted
    owner = one(url, "SELECT customer_id FROM app.customer_credits WHERE id=%s", credit)[0]
    waiting = hand_built_refund_draft(
        case,
        credit_payload(
            credit,
            100,
            method,
            variant="CREDIT_CUSTOMER",
            recipient_customer_id=str(owner),
        ),
    )
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as confirmed:
        refunds().confirm_draft(case["prop"], waiting, actor=refund_approver(staff, case["prop"]))
    assert cause(confirmed) == ("P5S01", RETURNED_CREDIT)
    assert one(url, COUNTS) == counted
    assert decisions(url, waiting) == 0


def test_other_money_in_the_returned_credit_stays_refundable(migrated_database_url: str) -> None:
    """Review round 1 (independent S2, the reviewer's real-path set-up): the Customer's own 2,000
    Credit pays a 1,500 charge after the closure; a REFUND correction of 500 on that line releases
    part of the application and refunds 500 from the Credit, which keeps its other 500; a
    return-only correction brings the 500 back (1,000 held, 500 left). An ordinary draft of 501 is
    refused, one of 500 is refunded, then 1 cent is refused; a held-value Refund naming the return
    pays out the rest, and nothing is left."""
    url = migrated_database_url
    case = refunded_case(url)
    staff = refund_actor(case["human"], case["prop"], "refunds.create")
    method = cash(refunds(), case["prop"], staff)
    credit = new_credit(url, case, 2_000)
    invoice, line = unpaid_charge(url, case, case["person"])
    apply_credit(case, credit, invoice, line, 1_500)
    result = cast(
        dict[str, Any],
        corrections().confirm_refund(
            case["prop"],
            record_refund_correction(case, refund_correction(case, invoice, line, 500)),
            actor=approving(case["person"], case["prop"]),
        ),
    )
    [paid] = result["refunds"]
    assert (paid["source_customer_credit_id"], paid["amount_usd_cents"]) == (str(credit), 500)
    assert available(url, credit) == 500
    earlier = return_only(case, UUID(str(paid["id"])), 500)
    assert (
        available(url, credit),
        credit_left(url, earlier, credit),
        returned_left(url, credit),
    ) == (1_000, 500, 500)
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as over:
        refunds().record_usd_draft(
            case["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 501, "Customer asked"),
            method,
            actor=staff,
        )
    assert cause(over) == ("P5S01", RETURNED_CREDIT)
    assert one(url, COUNTS) == counted
    other = create_usd_refund(
        refunds(),
        case["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 500, "Customer asked"),
        actor=staff,
    )
    assert one(
        url,
        "SELECT source_customer_credit_id,usd_accounting_value_cents FROM app.refunds WHERE id=%s",
        refund_id(other),
    ) == (credit, 500)
    assert (available(url, credit), returned_left(url, credit)) == (500, 500)
    with pytest.raises(RefundConflictError) as one_cent:
        refunds().record_usd_draft(
            case["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 1, "Customer asked"),
            method,
            actor=staff,
        )
    assert cause(one_cent) == ("P5S01", RETURNED_CREDIT)
    [held_paid] = confirm_held(case, record_held(case, held_command(case, earlier)))["refunds"]
    assert (held_paid["source_customer_credit_id"], held_paid["amount_usd_cents"]) == (
        str(credit),
        500,
    )
    assert (available(url, credit), returned_left(url, credit)) == (0, 0)


def test_returns_of_two_settlements_into_one_credit_are_counted_once(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 1 (independent S1, the reviewer's set-up): one Credit of the Customer pays a
    charge on each of two closed Leases; a REFUND correction of each Settlement refunds 500 from
    it and a return-only correction of each brings the 500 back. Each Settlement's walk also lists
    the other Settlement's entry, so each counts only its own: 1,000 left of the 1,500 held, and
    an ordinary Refund of the other 500 is accepted; one more cent is refused (review round 2
    note)."""
    url = migrated_database_url
    first = refunded_case(url)
    staff = refund_actor(first["human"], first["prop"], "refunds.create")
    # second_lease expects the Customer's only Credit with value to be the second Lease's own, so
    # the first case's other 300 of Credit (no return in it) is refunded first.
    create_usd_refund(
        refunds(),
        first["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", first["new_credit"], 300, "Customer asked"),
        actor=staff,
    )
    second = second_lease(url, monkeypatch, first["customer"])
    credit = new_credit(url, first, 3_500)
    charges = []
    for case in (first, second):
        invoice, line = unpaid_charge(url, case, case["person"])
        apply_credit(case, credit, invoice, line, 1_500)
        charges.append((case, invoice, line))
    assert available(url, credit) == 500
    returns = []
    for case, invoice, line in charges:
        [paid] = cast(
            dict[str, Any],
            corrections().confirm_refund(
                case["prop"],
                record_refund_correction(case, refund_correction(case, invoice, line, 500)),
                actor=approving(case["person"], case["prop"]),
            ),
        )["refunds"]
        assert (paid["source_customer_credit_id"], paid["amount_usd_cents"]) == (str(credit), 500)
        returns.append(return_only(case, UUID(str(paid["id"])), 500))
    assert available(url, credit) == 1_500
    assert [credit_left(url, item, credit) for item in returns] == [500, 500]
    assert returned_left(url, credit) == 1_000
    create_usd_refund(
        refunds(),
        first["prop"],
        CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 500, "Customer asked"),
        actor=staff,
    )
    assert (available(url, credit), returned_left(url, credit)) == (1_000, 1_000)
    counted = one(url, COUNTS)
    with pytest.raises(RefundConflictError) as one_cent:
        create_usd_refund(
            refunds(),
            first["prop"],
            CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 1, "Customer asked"),
            actor=staff,
        )
    assert cause(one_cent) == ("P5S01", RETURNED_CREDIT)
    assert one(url, COUNTS) == counted


def during_a_return(
    case: dict[str, Any],
    isolation: str,
    statement: Callable[[], tuple[str, tuple[object, ...]]],
) -> tuple[str | None, str | None]:
    """Review round 1 (security S1, the reviewer's set-up): a return-only correction of the case's
    whole 2,000 Refund is confirmed and holds the Credit locks uncommitted while the statement is
    prepared (it reads no return yet); the statement then runs at the given isolation with its
    snapshot taken first, waits for those locks, and the return commits. The statement's SQLSTATE
    and message, or two Nones."""
    url = case["url"]
    returning = record_return(case, return_command(case, case["refund"], 2_000, new=False))
    state: dict[str, str | None] = {}
    with psycopg.connect(url) as holder:
        holder.execute(
            "SELECT app.confirm_settlement_refund_return(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], returning),
        )
        sql, parameters = statement()
        refunder = psycopg.connect(url, autocommit=True)
        try:
            refunder.execute(
                {
                    "READ COMMITTED": "BEGIN ISOLATION LEVEL READ COMMITTED",
                    "REPEATABLE READ": "BEGIN ISOLATION LEVEL REPEATABLE READ",
                    "SERIALIZABLE": "BEGIN ISOLATION LEVEL SERIALIZABLE",
                }[isolation]
            )
            refunder.execute("SELECT 1")
        except BaseException:
            # Review round 2 note: the connection is closed when its transaction never starts.
            refunder.close()
            raise

        def run() -> None:
            try:
                refunder.execute(sql, parameters)
                state["sqlstate"], state["message"] = None, None
            except psycopg.Error as exc:
                state["sqlstate"], state["message"] = exc.sqlstate, exc.diag.message_primary
            finally:
                refunder.execute("ROLLBACK")
                refunder.close()

        worker = threading.Thread(target=run)
        worker.start()
        try:
            wait_until_blocked_by(url, holder)
            holder.commit()
        finally:
            worker.join(30)
    assert not worker.is_alive()
    return state["sqlstate"], state["message"]


def confirm_during_a_return(url: str, isolation: str) -> tuple[str | None, str | None, int, int]:
    """A Credit Refund draft of 500 is recorded while the return holds the locks; its confirm's
    result and message, the draft's decisions and the left value."""
    case = refunded_case(url)
    credit = case["refund_credit"]
    staff = refund_actor(case["human"], case["prop"], "refunds.create")
    method = cash(refunds(), case["prop"], staff)
    drafts: list[UUID] = []

    def confirm() -> tuple[str, tuple[object, ...]]:
        drafts.append(
            draft_of(
                refunds().record_usd_draft(
                    case["prop"],
                    CreateUsdRefundCommand(uuid4(), "CREDIT", credit, 500, "Customer asked"),
                    method,
                    actor=staff,
                )
            )
        )
        return (
            "SELECT app.confirm_refund_draft(%s,%s,%s,'financial.approve')",
            (case["prop"], case["person"], drafts[0]),
        )

    sqlstate, message = during_a_return(case, isolation, confirm)
    return sqlstate, message, decisions(url, drafts[0]), returned_left(url, credit)


def test_a_refund_confirm_waiting_for_a_return_reads_the_returned_money(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security S1): the confirm takes the Credit Refund locks before its refusal,
    so at READ COMMITTED it waits for a return that is being confirmed and then refuses (P5S01,
    its message checked since review round 2); at REPEATABLE READ or SERIALIZABLE the Payment
    state guard refuses it (40001). Each draft stays pending and the return keeps its 2,000
    left."""
    url = migrated_database_url
    assert confirm_during_a_return(url, "READ COMMITTED") == ("P5S01", RETURNED_CREDIT, 0, 2_000)
    for isolation in ("REPEATABLE READ", "SERIALIZABLE"):
        sqlstate, _, waiting, left = confirm_during_a_return(url, isolation)
        assert (sqlstate, waiting, left) == ("40001", 0, 2_000), isolation


def test_the_one_call_credit_reversal_of_returned_money_is_refused(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-19-144 (the round 1 security reviewer's set-up, the owner's
    example): a correction's 2,000 Credit Refund comes back through a return-only correction X1,
    so the Credit's whole recognized value is available again. The one-call Credit reversal, which
    would move that 2,000 back to its Payment, is refused through the service as a conflict (P5S01),
    and a direct insert as the owner too; nothing is written, and the Payment's available value
    stays 0. The Customer then owes a 1,500 charge: a held-value Refund naming X1 pays it first
    and refunds the other 500, so nothing is left."""
    url = migrated_database_url
    case = refunded_case(url)
    refund, credit, customer = case["refund"], case["refund_credit"], case["customer"]
    payment = one(url, "SELECT source_payment_id FROM app.customer_credits WHERE id=%s", credit)[0]
    earlier = return_only(case, refund, 2_000)
    recognized = "SELECT recognized_usd_cents FROM app.customer_credits WHERE id=%s"
    assert one(url, recognized, credit) == (2_000,)
    assert (available(url, credit), returned_left(url, credit)) == (2_000, 2_000)
    payment_available = "SELECT app.payment_available_value(%s)"
    assert one(url, payment_available, payment) == (0,)
    counted = one(url, COUNTS)
    with pytest.raises(CreditConflictError) as refused:
        reverse(case, credit)
    assert str(refused.value) == CLOSED_SETTLEMENT_CHANGE
    assert cause(refused) == ("P5S01", CLOSED_SETTLEMENT_CHANGE)
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as direct:
        connection.execute(
            "INSERT INTO app.customer_credit_reversals(id,customer_credit_id,reason,occurred_at,"
            "actor_id,authorization_reference) "
            "VALUES (gen_random_uuid(),%s,'Wrong recognition',clock_timestamp(),%s,"
            "'credits.reverse')",
            (credit, case["human"]),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == (
        "P5S01",
        CLOSED_SETTLEMENT_CHANGE,
    )
    assert (one(url, COUNTS), reversals(url, credit)) == (counted, 0)
    assert (available(url, credit), returned_left(url, credit)) == (2_000, 2_000)
    assert one(url, payment_available, payment) == (0,)
    _, charge_line = unpaid_charge(url, case, case["person"])
    result = confirm_held(
        case,
        record_held(
            case,
            held_command(case, earlier, SettlementCreditStep(credit, LINE, charge_line, 1_500)),
        ),
    )
    [paid] = result["refunds"]
    assert (paid["recipient_customer_id"], paid["amount_usd_cents"]) == (str(customer), 500)
    assert (
        available(url, credit),
        outstanding(url, charge_line),
        returned_left(url, credit),
    ) == (0, 0, 0)


def test_a_credit_from_a_payment_for_a_named_invoice_is_not_reversed_while_debt_is_open(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-19-144 (the round 2 security reviewer's set-up): a 1,500
    Payment confirmed for the paid Initial Invoice becomes Credit C and pays a 1,500 charge; a
    REFUND correction refunds that 1,500 from C, and a return-only correction brings it back; the
    Customer owes a second 1,500 charge on the closed Lease. The Payment Refund's check reads only
    the named Invoice, so the reversal would let the 1,500 leave in cash while the debt is open;
    it is refused (P5S01), nothing is written, and the Payment's available value stays 0."""
    url = migrated_database_url
    case = refunded_case(url)
    with psycopg.connect(url) as connection:
        payment = seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=case["customer"],
            amount=1_500,
            invoice_id=case["initial"],
        )
    credit = credit_id(recognize(case["prop"], payment, case["human"], 1_500))
    invoice, line = unpaid_charge(url, case, case["person"])
    apply_credit(case, credit, invoice, line, 1_500)
    result = cast(
        dict[str, Any],
        corrections().confirm_refund(
            case["prop"],
            record_refund_correction(case, refund_correction(case, invoice, line, 1_500)),
            actor=approving(case["person"], case["prop"]),
        ),
    )
    [paid] = result["refunds"]
    assert (paid["source_customer_credit_id"], paid["amount_usd_cents"]) == (str(credit), 1_500)
    return_only(case, UUID(str(paid["id"])), 1_500)
    _, owed = unpaid_charge(url, case, case["person"])
    assert (available(url, credit), returned_left(url, credit), outstanding(url, owed)) == (
        1_500,
        1_500,
        1_500,
    )
    payment_available = "SELECT app.payment_available_value(%s)"
    assert one(url, payment_available, payment) == (0,)
    counted = one(url, COUNTS)
    with pytest.raises(CreditConflictError) as refused:
        reverse(case, credit)
    assert cause(refused) == ("P5S01", CLOSED_SETTLEMENT_CHANGE)
    assert (one(url, COUNTS), reversals(url, credit)) == (counted, 0)
    assert (available(url, credit), returned_left(url, credit), outstanding(url, owed)) == (
        1_500,
        1_500,
        1_500,
    )
    assert one(url, payment_available, payment) == (0,)


def test_a_credit_reversal_waiting_for_a_return_reads_the_returned_money(
    migrated_database_url: str,
) -> None:
    """Owner answer (a) to Q-2026-10-19-144: the reversal's refusal takes the Credit Refund locks
    first, so a one-call reversal at READ COMMITTED waits for a return that is being confirmed
    and then refuses (P5S01); at REPEATABLE READ or SERIALIZABLE the Payment state guard refuses
    it (40001). Nothing is written and the return keeps its 2,000 left."""
    url = migrated_database_url
    assert reverse_during_a_return(url, "READ COMMITTED") == (
        "P5S01",
        CLOSED_SETTLEMENT_CHANGE,
        0,
        2_000,
    )
    # SERIALIZABLE too since review round 3 (security note 3).
    for isolation in ("REPEATABLE READ", "SERIALIZABLE"):
        sqlstate, _, written, left = reverse_during_a_return(url, isolation)
        assert (sqlstate, written, left) == ("40001", 0, 2_000), isolation


def reverse_during_a_return(url: str, isolation: str) -> tuple[str | None, str | None, int, int]:
    """The one-call Credit reversal of the case's Credit runs while the return holds the locks;
    its result and message, the Credit's reversals and the left value."""
    case = refunded_case(url)
    credit = case["refund_credit"]

    def reversal() -> tuple[str, tuple[object, ...]]:
        return (
            "SELECT app.reverse_customer_credit(%s,%s,%s,%s,%s)",
            (case["prop"], credit, case["human"], uuid4(), "Wrong recognition"),
        )

    sqlstate, message = during_a_return(case, isolation, reversal)
    return sqlstate, message, reversals(url, credit), returned_left(url, credit)


def test_the_returned_credit_refusal_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The four new functions have no grant and the definer settings; the migration adds only them
    and one BEFORE INSERT row trigger on the Credit reversals (Q-2026-10-19-144), which runs after
    the slice 7 and 8g refusals and before the insert check; it changes only the two Credit Refund
    draft recorders and the confirm (each keeps its owner, privileges and settings, and calls the
    refusal) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        # BEFORE (2), ROW (1) and INSERT (4).
        assert connection.execute(
            "SELECT tgtype,tgfoid::regprocedure::text FROM pg_catalog.pg_trigger "
            "WHERE tgrelid='app.customer_credit_reversals'::regclass "
            "AND tgname='customer_credit_reversals_returned_value'"
        ).fetchone() == (7, "app.refuse_returned_credit_reversal()")
        assert [
            row[0]
            for row in connection.execute(
                "SELECT tgname FROM pg_catalog.pg_trigger "
                "WHERE tgrelid='app.customer_credit_reversals'::regclass AND NOT tgisinternal "
                "AND tgtype & 6 = 6 ORDER BY tgname"
            ).fetchall()
        ] == [
            "customer_credit_reversals_moved_payment",
            "customer_credit_reversals_other_customer",
            "customer_credit_reversals_returned_value",
            "customer_credit_reversals_validate",
        ]
        for function in INTERNAL:
            for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
                assert connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, function)
                ).fetchone() == (False,), (role, function)
            assert connection.execute(
                "SELECT prosecdef,proconfig::text FROM pg_catalog.pg_proc "
                "WHERE oid=CAST(%s AS regprocedure)",
                (function,),
            ).fetchone() == (True, "{search_path=pg_catalog}"), function
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270108_165"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str]]:
        with psycopg.connect(database) as connection:
            functions = {
                str(row[0]): tuple(row[1:])
                for row in connection.execute(
                    "SELECT p.oid::regprocedure::text,pg_catalog.pg_get_functiondef(p.oid),"
                    "p.proacl::text,p.proowner,p.prosecdef,p.proconfig::text "
                    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.prokind='f'"
                ).fetchall()
            }
            triggers = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
            structure = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT c.oid::regclass::text,c.relacl::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
                ).fetchall()
            } | {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT con.conrelid::regclass::text,con.conname,"
                    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace "
                    "WHERE n.nspname='app'"
                ).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_returned_credit_refund") as temporary:
        alembic_command.upgrade(config, "20270108_165")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    changed = {RECORD, RECORD_CREDIT_CUSTOMER, CONFIRM}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == changed
    for name in changed:
        # Owner, privileges, definer and settings stay; only the body changes.
        assert after_functions[name][1:] == before_functions[name][1:], name
        assert "app.refuse_credit_refund_of_returned_value(" in str(after_functions[name][0])
    assert "app.lock_refund_payment_source(" in str(after_functions[CONFIRM][0])
    assert after_triggers - before_triggers == {TRIGGER}
    assert before_triggers <= after_triggers
    assert after_structure == before_structure
