"""The two-person reversal of a receipt recorded while a Refund is out (V1-056 sub-slice
10e-2b-4e-2b-3).

Owner answer (a) to Q-2026-10-19-137, with the narrowing of its review rounds 2 and 3: a wrong
receipt must always be fixable by two people. The receipt reversal (the 8r draft: deposits.correct
records, financial.approve confirms) undoes a receipt recorded into a Pet Deposit whose Pet
Refund-review Refund is not fully returned, when the receipt is strictly later than every such
Refund and the Deposit held at least the receipt's amount at every balance time from the receipt
on. Every test runs on the real path, to the cent, except the hand-built parts (rolled back). The
tests: a partial verified return before or after the receipt, the round 2 counterexample (a
return that relied on the receipt's money), the round 3 one (a verified-return reversal), a
receipt recorded before the Refund, the binding to the confirmed draft (review rounds 1 to 3:
hand-built reversal rows, decisions and draft rows, with user triggers disabled inside the
rolled-back transaction where needed), a waiting return of another Payment made stale, and least
privilege.
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

from deposit_receipt_reversal_test_support import reverse_receipt_as_owner
from property_rental.deposit import (
    AdjustDepositRequiredAmountCommand,
    DepositAdjustmentType,
    DepositConflictError,
    DepositInvalidError,
    PostgresDepositService,
    ReverseDepositReceiptCommand,
)
from property_rental.deposit_receipt_reversal import DepositReceiptReversalConflictError
from property_rental.payment_return import PaymentReturnStaleDraftError
from property_rental.refund import ReverseRefundCorrectionCommand
from test_credit_migration import actor
from test_deposit_migration import deposit_actor
from test_deposit_receipt_leftover_migration import AVAILABLE, UNRESOLVED
from test_deposit_receipt_record_migration import (
    DEPENDENT,
    allocator,
    payment,
    pet_case,
    qualify_review,
    receipt_command,
    review_refund,
)
from test_deposit_receipt_reversal_draft_migration import confirm as confirm_reversal
from test_deposit_receipt_reversal_draft_migration import record as record_reversal
from test_deposit_receipt_reversal_draft_migration import withdraw as withdraw_reversal
from test_final_settlement_migration import held, one, today
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_payment_return_migration import approver as return_approver
from test_payment_return_migration import draft_id, drafts, reconciled, request, returns, status
from test_payment_return_migration import preparer as return_preparer
from test_payment_return_shared_deposit_migration import active_receipts, net, recoveries
from test_refund_service_migration import corrections, returned
from test_refund_service_migration import service as refund_service

REVISION = "20270105_162"
HELPER = "app.deposit_receipt_reversal_after_refund_allowed(uuid,uuid,uuid)"
INNER = "app.reverse_deposit_receipt(uuid,uuid,uuid,text,uuid,uuid,text,text)"
REVERSAL_CHECK = "app.validate_deposit_receipt_reversal()"
HAND_BUILT = (
    "INSERT INTO app.deposit_receipt_reversals(id,deposit_receipt_id,reason,occurred_at,actor_id,"
    "authorization_reference) VALUES (%s,%s,'Hand-built reversal',clock_timestamp(),%s,"
    "'deposits.correct')"
)
REVERSALS = (
    "SELECT count(*) FROM app.deposit_receipt_reversals reversal JOIN app.deposit_receipts "
    "receipt ON receipt.id=reversal.deposit_receipt_id WHERE receipt.deposit_id=%s"
)


def received(case: dict[str, Any], amount: int) -> tuple[UUID, UUID]:
    """A new Payment of the Pet Deposit's Customer recorded into it through the writer: the
    Payment and its receipt."""
    url, human, prop, pet = case["url"], case["human"], case["prop"], case["pet"]
    service: PostgresDepositService = case["service"]
    paid_by = payment(url, human, pet, amount)
    receipt = service.record_receipt(
        receipt_command(pet, paid_by, amount), actor=allocator(human, prop)
    ).deposit_receipt_id
    return paid_by, receipt


def verify_return(case: dict[str, Any], refund: UUID, amount: int) -> dict[str, object]:
    human, prop = case["human"], case["prop"]
    return refund_service().verify_usd_return(
        prop, refund, returned(amount), actor=actor(human, prop, "refunds.correct")
    )


def refused(case: dict[str, Any], receipt: UUID) -> None:
    """A reversal draft of the receipt is recorded; its confirm is refused by the receipt reversal
    check (55000, the dependent-history message) and the draft is withdrawn."""
    human, prop = case["human"], case["prop"]
    draft = record_reversal(prop, human, receipt)
    with pytest.raises(DepositReceiptReversalConflictError) as raised:
        confirm_reversal(prop, human, receipt, draft["draft_id"])
    cause = raised.value.__cause__
    assert isinstance(cause, psycopg.Error)
    assert (cause.sqlstate, cause.diag.message_primary) == ("55000", DEPENDENT)
    withdraw_reversal(prop, human, draft["draft_id"])


def reversed_by_two_people(case: dict[str, Any], receipt: UUID) -> None:
    human, prop = case["human"], case["prop"]
    draft = record_reversal(prop, human, receipt)
    confirm_reversal(prop, human, receipt, draft["draft_id"])


@pytest.mark.parametrize("returned_first", [False, True], ids=["return_after", "return_before"])
def test_a_receipt_beside_a_partly_returned_refund_is_reversed(
    migrated_database_url: str, returned_first: bool
) -> None:
    """A Pet Deposit takes 10,000 from Payment A and pays a 10,000 Pet Refund-review Refund (it
    holds 0). A verified return of 4,000 comes after C's 10,000 receipt, or before it; either
    way the Refund is still out when the reversal draft of C's receipt is confirmed, the receipt
    is later than the Refund and the Deposit never held less than 10,000 after it. The reversal
    passes: the Deposit holds 4,000 (the returned money), C has its 10,000 back, the Refund's net
    is 6,000 and it is still out."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    pet = case["pet"]
    received(case, 10_000)
    refund = review_refund(case, qualify_review(case), 10_000)
    if returned_first:
        verify_return(case, refund, 4_000)
    later, receipt = received(case, 10_000)
    if not returned_first:
        verify_return(case, refund, 4_000)
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (14_000, True)
    reversed_by_two_people(case, receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        1,
        4_000,
        10_000,
    )
    assert (net(url, refund), value(url, UNRESOLVED, pet)) == (6_000, True)


def test_a_receipt_a_later_return_relied_on_is_not_reversed(migrated_database_url: str) -> None:
    """Review round 2 of 10e-2b-4e-2b-2b (independent should-fix 1), the counterexample of the
    narrowing: A 10,000; a 10,000 Pet Refund-review Refund (the Deposit holds 0); C 10,000 (it
    holds 10,000); A bounces and its return charges nothing, because C's money covers the
    Refund (it holds 0); then D 10,000 (it holds 10,000). The reversal of C's receipt is refused
    (55000), because A's return relied on C's money: nothing is written, the Deposit holds
    10,000 and C has nothing left. D's receipt, which nothing relied on, is reversed by two
    people: the Deposit holds 0 and D has its 10,000 back; the Refund's net stays 10,000."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    first, _ = received(case, 10_000)
    refund = review_refund(case, qualify_review(case), 10_000)
    later, receipt = received(case, 10_000)
    draft = returns().record(prop, request(first), actor=return_preparer(human, prop))
    result = returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    assert result["recoveries"] == []
    assert (held(url, pet), status(url, first)) == (0, "REVERSED")
    last, last_receipt = received(case, 10_000)
    assert held(url, pet) == 10_000
    refused(case, receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        1,
        10_000,
        0,
    )
    reversed_by_two_people(case, last_receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, last)) == (
        2,
        0,
        10_000,
    )
    assert active_receipts(url, pet) == [later]
    assert (net(url, refund), value(url, UNRESOLVED, pet)) == (10_000, True)


def test_a_receipt_a_verified_return_reversal_relied_on_is_not_reversed(
    migrated_database_url: str,
) -> None:
    """Review round 3 of 10e-2b-4e-2b-2b (security note 1), why the narrowing is stated by its
    effect: A 10,000; a 10,000 Pet Refund-review Refund verified returned in full (the Deposit
    holds 10,000, the Refund resolved); C 10,000 (it holds 20,000); A's receipt reversed by two
    people (it holds 10,000); the verified return reversed (it holds 0, the Refund out again);
    D 10,000 (it holds 10,000). The return's reversal took C's money, so the reversal of C's
    receipt is refused (55000): nothing is written, the Deposit holds 10,000, C has nothing left
    and the Refund's net is 10,000."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    first, first_receipt = received(case, 10_000)
    refund = review_refund(case, qualify_review(case), 10_000)
    correction = corrections(verify_return(case, refund, 10_000))[0]
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (10_000, False)
    later, receipt = received(case, 10_000)
    reversed_by_two_people(case, first_receipt)
    assert (held(url, pet), value(url, AVAILABLE, first)) == (10_000, 10_000)
    refund_service().reverse_correction(
        prop,
        refund,
        UUID(str(correction["id"])),
        ReverseRefundCorrectionCommand(uuid4(), "Reviewed evidence", "Incorrect correction"),
        actor=actor(human, prop, "refunds.corrections.reverse"),
    )
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (0, True)
    received(case, 10_000)
    assert held(url, pet) == 10_000
    refused(case, receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        1,
        10_000,
        0,
    )
    assert net(url, refund) == 10_000


def test_a_receipt_recorded_before_the_refund_is_not_reversed(migrated_database_url: str) -> None:
    """A receipt recorded before a Refund that is not fully returned stays refused (the Refund's
    approver relied on the Deposit's money): A 10,000 and C 10,000 (the Deposit holds 20,000),
    then a 10,000 Pet Refund-review Refund (it holds 10,000). The reversal of C's receipt is
    refused (55000): nothing is written and C has nothing left."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    pet = case["pet"]
    received(case, 10_000)
    later, receipt = received(case, 10_000)
    refund = review_refund(case, qualify_review(case), 10_000)
    assert (held(url, pet), value(url, UNRESOLVED, pet)) == (10_000, True)
    refused(case, receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        0,
        10_000,
        0,
    )
    assert net(url, refund) == 10_000


def hand_built(
    url: str,
    receipt: UUID,
    reversal: UUID,
    human: UUID,
    first: tuple[str, tuple[Any, ...]] | None = None,
) -> tuple[Any, Any]:
    """A reversal row of the receipt written by hand as the owner, after an optional first
    statement in the same transaction (all rolled back): its refusal."""
    with psycopg.connect(url) as connection:
        if first is not None:
            connection.execute(*first)
        try:
            connection.execute(HAND_BUILT, (reversal, receipt, human))
        except psycopg.Error as refusal:
            connection.rollback()
            return refusal.sqlstate, refusal.diag.message_primary
        connection.rollback()
    return None, None


def test_only_the_confirmed_draft_s_reversal_passes(migrated_database_url: str) -> None:
    """The relaxation belongs to the two-person draft only (review round 1, both reviewers). On
    the set-up of the renamed test (A 10,000, a 10,000 Pet Refund-review Refund, C 10,000), each
    of these is refused by the receipt reversal checks (55000) and writes nothing: a reversal row
    of C's receipt written by hand with no draft; the owner one-call path; a hand-built row that
    reuses the reversal id of a draft withdrawn, or rejected, in the same transaction (review
    round 2, security should-fix 1: so only the CONFIRMED filter refuses it); a hand-built row
    whose draft has a CONFIRMED decision dated before the transaction began (the same decision
    dated in it lets the check pass, but not for another actor or reversal id, nor once the
    draft names another Deposit: review round 2, security should-fix 2; A's receipt is refused
    too, but by conditions (3) and (4) as well, review round 3); and a hand-built row of C's
    receipt that reuses the reversal id of D's draft confirmed in the same transaction (the
    receipt binding alone refuses it, review round 3). Then the draft's confirm reverses C's
    receipt."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    _, first_receipt = received(case, 10_000)
    review_refund(case, qualify_review(case), 10_000)
    later, receipt = received(case, 10_000)
    refusal = ("55000", DEPENDENT)
    assert hand_built(url, receipt, uuid4(), human) == refusal
    # The owner one-call path has no draft (review round 1, independent note 3).
    with pytest.raises((DepositInvalidError, DepositConflictError)) as one_call:
        reverse_receipt_as_owner(
            case["service"],
            ReverseDepositReceiptCommand(uuid4(), uuid4(), receipt, "Transfer returned"),
            actor=deposit_actor(human, prop),
        )
    cause = one_call.value.__cause__
    assert isinstance(cause, psycopg.Error) and cause.diag.message_primary == DEPENDENT
    assert cause.sqlstate == "55000"
    # Review round 1 (security should-fix 1): (a) a withdrawn draft, (b) a rejected draft, each
    # decided in the same transaction as the hand-built row (review round 2, should-fix 1).
    for function, reason, capability in (
        ("withdraw_financial_draft", "Recorded against the wrong receipt", "deposits.correct"),
        ("reject_financial_draft", "Transfer arrived after all", "financial.approve"),
    ):
        decided = uuid4()
        draft = record_reversal(prop, human, receipt, reversal=decided)
        first = (
            f"SELECT app.{function}(%s,%s,%s,%s,%s)",
            (prop, human, UUID(str(draft["draft_id"])), reason, capability),
        )
        assert hand_built(url, receipt, decided, human, first) == refusal
        withdraw_reversal(prop, human, draft["draft_id"])
    # (c) The time binding: a CONFIRMED decision dated before this transaction began.
    pending = uuid4()
    draft = record_reversal(prop, human, receipt, reversal=pending)
    with psycopg.connect(url) as connection:
        connection.execute("ALTER TABLE app.financial_draft_decisions DISABLE TRIGGER USER")
        connection.execute(
            "INSERT INTO app.financial_draft_decisions(draft_id,decision,reason,decided_at,"
            "decided_by,authorization_reference,result) VALUES (%s,'CONFIRMED',NULL,"
            "transaction_timestamp()-interval '1 second',%s,'financial.approve','{}'::jsonb)",
            (UUID(str(draft["draft_id"])), human),
        )
        with pytest.raises(psycopg.Error) as early, connection.transaction():
            connection.execute(HAND_BUILT, (pending, receipt, human))
        assert (early.value.sqlstate, early.value.diag.message_primary) == refusal
        allowed = "SELECT app.deposit_receipt_reversal_after_refund_allowed(%s,%s,%s)"
        assert connection.execute(allowed, (receipt, pending, human)).fetchone() == (False,)
        connection.execute(
            "UPDATE app.financial_draft_decisions SET decided_at=clock_timestamp() "
            "WHERE draft_id=%s",
            (UUID(str(draft["draft_id"])),),
        )
        assert connection.execute(allowed, (receipt, pending, human)).fetchone() == (True,)
        # Review round 2 (security should-fix 2): the actor, reversal and Deposit bindings.
        # A's receipt also fails conditions (3) and (4) (review round 3); D's case below shows
        # the receipt binding alone.
        for others in ((receipt, pending, uuid4()), (receipt, uuid4(), human)):
            assert connection.execute(allowed, others).fetchone() == (False,)
        assert connection.execute(allowed, (first_receipt, pending, human)).fetchone() == (False,)
        connection.execute("ALTER TABLE app.financial_drafts DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE app.financial_drafts SET payload=jsonb_set(payload,'{deposit_id}',"
            "to_jsonb(gen_random_uuid()::text)) WHERE id=%s",
            (UUID(str(draft["draft_id"])),),
        )
        assert connection.execute(allowed, (receipt, pending, human)).fetchone() == (False,)
        connection.rollback()
    withdraw_reversal(prop, human, draft["draft_id"])
    # (d) Another receipt's draft confirmed in the same transaction.
    case["service"].adjust_required_amount(
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            uuid4(),
            pet,
            DepositAdjustmentType.INCREASE,
            10_000,
            today(url),
            "Approved required amount",
        ),
        actor=deposit_actor(human, prop),
    )
    _, other_receipt = received(case, 10_000)
    other_reversal = uuid4()
    other = record_reversal(prop, human, other_receipt, reversal=other_reversal)
    with pytest.raises(psycopg.Error) as reused, psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_deposit_receipt_reversal_draft(%s,%s,%s,%s,'financial.approve')",
            (prop, human, other_receipt, UUID(str(other["draft_id"]))),
        )
        connection.execute(HAND_BUILT, (other_reversal, receipt, human))
        connection.rollback()
    assert (reused.value.sqlstate, reused.value.diag.message_primary) == refusal
    # Review round 3 (security should-fix 1): the refusal is the hand-built row's insert check,
    # not D's confirm.
    context = str(reused.value.diag.context)
    assert "validate_deposit_receipt_reversal" in context
    assert "confirm_deposit_receipt_reversal_draft" not in context
    withdraw_reversal(prop, human, other["draft_id"])
    assert (value(url, REVERSALS, pet), held(url, pet)) == (0, 20_000)
    reversed_by_two_people(case, receipt)
    assert (value(url, REVERSALS, pet), held(url, pet), value(url, AVAILABLE, later)) == (
        1,
        10_000,
        10_000,
    )


def test_a_reversal_makes_a_waiting_return_of_another_payment_stale(
    migrated_database_url: str,
) -> None:
    """Review round 1 (security should-fix 2): the 8r recorder's waiting-draft check does not
    cover a PAYMENT_RETURN draft; the return's source digest does. A 10,000; a 10,000 Pet
    Refund-review Refund; C 10,000. A's return draft plans no recovery (C's money covers the
    Refund). C's receipt is reversed by two people (the Deposit holds 0), so A's confirm is stale
    (P5S02) and writes nothing. Withdrawn and recorded again, A's return plans a 10,000 recovery
    (the Deposit is no longer shared), and its confirm charges it back and reverses A's receipt:
    the Deposit holds 0 and the Refund's net is 0."""
    url = migrated_database_url
    case: dict[str, Any] = pet_case(url)
    human, prop, pet = case["human"], case["prop"], case["pet"]
    first, _ = received(case, 10_000)
    refund = review_refund(case, qualify_review(case), 10_000)
    later, receipt = received(case, 10_000)
    draft = returns().record(prop, request(first), actor=return_preparer(human, prop))
    assert cast(dict[str, Any], draft["payload"])["source"]["recoveries"] == []
    reversed_by_two_people(case, receipt)
    assert (held(url, pet), value(url, AVAILABLE, later)) == (0, 10_000)
    with pytest.raises(PaymentReturnStaleDraftError):
        returns().confirm(prop, draft_id(draft), actor=return_approver(human, prop))
    assert (recoveries(url, refund), held(url, pet), status(url, first)) == ([], 0, "RECEIVED")
    drafts().withdraw(
        prop,
        draft_id(draft),
        "The Deposit changed before the confirm",
        prepare_capability="payments.reverse",
        actor=return_preparer(human, prop),
    )
    again = returns().record(prop, request(first), actor=return_preparer(human, prop))
    [plan] = cast(dict[str, Any], again["payload"])["source"]["recoveries"]
    assert plan["amount_usd_cents"] == 10_000
    result = returns().confirm(prop, draft_id(again), actor=return_approver(human, prop))
    assert len(cast(list[Any], result["recoveries"])) == 1
    assert (recoveries(url, refund), net(url, refund), held(url, pet)) == ([10_000], 0, 0)
    assert status(url, first) == "REVERSED"
    reconciled(url, case["customer"])


def test_the_reversal_after_refund_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """Sub-slice 10e-2b-4e-2b-3 adds one internal function that no application role may run and
    patches the receipt reversal's two checks, each by exactly its one listed replacement, with
    the same owner, privileges and settings; no other function, constraint or trigger changes,
    and it is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270104_161"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
    assert one(
        migrated_database_url,
        "SELECT has_function_privilege('prm_runtime',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_financial',p.oid,'EXECUTE'),"
        "has_function_privilege('prm_bootstrap',p.oid,'EXECUTE') "
        "FROM pg_catalog.pg_proc p WHERE p.oid=CAST(%s AS regprocedure)",
        HELPER,
    ) == (False, False, False)
    # Review round 1 (security note 5): only the owner holds any privilege on it.
    assert one(
        migrated_database_url,
        "SELECT bool_and(acl.grantee=p.proowner) FROM pg_catalog.pg_proc p "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) acl "
        "WHERE p.oid=CAST(%s AS regprocedure)",
        HELPER,
    ) == (True,)
    # Review round 2 (security note 3): it keeps SECURITY DEFINER and its search path.
    assert one(
        migrated_database_url,
        "SELECT p.prosecdef,p.proconfig::text FROM pg_catalog.pg_proc p "
        "WHERE p.oid=CAST(%s AS regprocedure)",
        HELPER,
    ) == (True, "{search_path=pg_catalog}")

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

    with _temporary_migration_database("deposit_receipt_reversal_after_refund") as temporary:
        alembic_command.upgrade(config, "20270104_161")
        before_functions, before_others = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_others = catalog(temporary)
    assert after_others == before_others
    assert set(after_functions) - set(before_functions) == {HELPER}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {INNER, REVERSAL_CHECK}
    for name, replacements in (
        (INNER, revision.module.INNER_REPLACEMENTS),
        (REVERSAL_CHECK, revision.module.REVERSAL_CHECK_REPLACEMENTS),
    ):
        expected = before_functions[name][0]
        for before, after in replacements:
            assert expected.count(before) == 1
            expected = expected.replace(before, after)
        assert after_functions[name][0] == expected
        assert after_functions[name][1:] == before_functions[name][1:]
