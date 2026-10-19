"""Post-settlement correction: the narrow Credit and Refund refusal of PAYMENT_MOVE (V1-056
sub-slice 10g-2).

Owner answer (a) to Q-2026-10-17-121: inside the PAYMENT_MOVE correction of a closed Final
Settlement only, a Payment's Customer Credit that is not reversed, or its Refund that is not fully
returned, no longer blocks the move of a wrong allocation that is still active, because that
allocation's value never became Credit or a Refund (BR-PAY-042, BR-SETTLE-013). The Credit, the
Refund and the Settlement's use of them stay as they are; the debt comes back on the Settlement
obligation (BR-SETTLE-016). Still refused: such a Payment where a credit Adjustment released any
part of an allocation of this Payment on the wrong Invoice. The slice 7 move draft keeps the
blanket rule (owner answer 4 to Q-2026-10-05-16).
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

from payment_test_support import seed_payment
from property_rental.credit import ReverseCreditCommand
from property_rental.final_settlement import SettlementCreditStep, SettlementDepositStep
from property_rental.payment_move import PaymentMoveConflictError, RecordPaymentMoveCommand
from property_rental.refund import CreateUsdRefundCommand, RefundService
from refund_test_support import create_usd_refund
from test_credit_adjustment_excess_migration import credit as credit_adjustment
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import invoice_of, this_month
from test_final_settlement_draft_migration import LINE, PET_FIRST, leaving_case
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import outstanding
from test_invoice_migration import financial_database_url, runtime_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_actor
from test_payment_allocation_migration import designated
from test_payment_allocation_migration import service as allocations
from test_payment_move_migration import allocation_ids, person, rows, value
from test_refund_service_migration import refund_id
from test_settlement_correction_migration import approver as correction_approver
from test_settlement_correction_migration import settlement_row
from test_settlement_payment_move_migration import (
    SOURCE_ACK,
    TARGET_ACK,
    cause,
    command,
    confirm,
    draft_count,
    draft_of,
    moves,
    reconciled,
    record,
    state,
)
from test_settlement_payment_move_migration import close as close_paid

REVISION = "20270107_164"
INTERNAL = "app.wrong_unit_move_source(uuid,uuid,uuid,boolean)"
SLICE_7_SOURCE = "app.payment_move_source(uuid,uuid,uuid)"
SETTLEMENT_SOURCE = "app.settlement_payment_move_source(uuid,uuid,uuid,uuid)"
BLANKET = "Reverse the Customer Credit or Refund from this Payment first"
RELEASE = (
    "SELECT replacement_payment_allocation_id,customer_credit_id "
    "FROM app.invoice_credit_excess_releases WHERE reversed_payment_allocation_id=%s"
)
PET_DEPOSIT = 20_000
SECURITY_DEPOSIT = 10_000


def two_leases(url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Two Leases on two Units (sub-slice 10g): the first one's Customer pays by mistake on the
    first Lease's other damage line; the second Lease's other damage line (12,500) is the
    correct one."""
    first = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    second = {**leaving_case(url, start_offset=this_month(url)), "url": url}
    return first, second


def paid_by(
    case: dict[str, Any],
    amount: int,
    identified: UUID | None = None,
    *,
    third_party: bool = False,
) -> UUID:
    """A Payment of the case's Customer of exactly amount, identified for an Invoice when one is
    named (then only that Invoice decides whether its excess may become Credit); with
    third_party, a Payment of a third party identified for the case's Lease."""
    with psycopg.connect(case["url"]) as connection:
        payer = case["customer"]
        scope: dict[str, Any] = {}
        if third_party:
            payer = uuid4()
            connection.execute(
                "INSERT INTO app.customers(id,legal_name,created_by,updated_by) "
                "VALUES (%s,'Third-party payer',%s,%s)",
                (payer, case["human"], case["human"]),
            )
            scope = {"scope": "THIRD_PARTY_IDENTIFIED", "lease_id": case["lease"]}
        return seed_payment(
            connection,
            actor_id=case["human"],
            property_id=case["prop"],
            customer_id=payer,
            amount=amount,
            invoice_id=identified,
            **scope,
        )


def allocate(case: dict[str, Any], payment: UUID, line: str, amount: int) -> UUID:
    posted = allocations().post(
        case["prop"],
        payment,
        designated(invoice_of(case["url"], case[line]), case[line], amount),
        actor=allocation_actor(case["human"], case["prop"]),
    )
    return allocation_ids(posted)[0]


def close_other_line_paid(case: dict[str, Any], applied: tuple[tuple[UUID, int], ...]) -> None:
    """The real closure (sub-slice 8e-3) of a Lease whose other damage line is paid: the applied
    Credits pay the pet damage line first, the Pet Deposit pays its rest, and both Deposits' rests
    are refunded."""
    url = case["url"]
    assert outstanding(url, case["other_line"]) == 0
    pet_paid = outstanding(url, case["pet_line"]) - sum(amount for _, amount in applied)
    confirm_settlement(
        case,
        record_settlement(
            case,
            (
                *(
                    SettlementCreditStep(credit, LINE, case["pet_line"], amount)
                    for credit, amount in applied
                ),
                SettlementDepositStep(PET_FIRST, case["pet"], LINE, case["pet_line"], pet_paid),
                settlement_refund(case, "pet", PET_DEPOSIT - pet_paid),
                settlement_refund(case, "security", SECURITY_DEPOSIT),
            ),
        ),
    )
    case["person"] = correction_approver(url)


def slice_7_draft_refusal(case: dict[str, Any], allocation: UUID, target: UUID) -> tuple[Any, Any]:
    """The slice 7 move draft of the same allocation: its refusal's SQLSTATE and message."""
    with pytest.raises(PaymentMoveConflictError) as refused:
        moves().record(
            case["prop"],
            RecordPaymentMoveCommand(
                idempotency_key=uuid4(),
                allocation_id=allocation,
                target_invoice_id=target,
                reason="Paid on the first Lease's Unit by mistake",
                source_acknowledgement=SOURCE_ACK,
                target_acknowledgement=TARGET_ACK,
            ),
            actor=person(case["human"], case["prop"], "payments.allocations.reverse"),
        )
    return cause(refused)


def credit_uses(url: str, credit: UUID) -> list[tuple[Any, ...]]:
    """The Credit's applications, each with its reversal count, and the Credit's reversal count."""
    return rows(
        url,
        "SELECT application.id,application.invoice_id,application.amount_usd_cents,"
        "(SELECT count(*) FROM app.customer_credit_application_reversals reversal "
        "WHERE reversal.credit_application_id=application.id),"
        "(SELECT count(*) FROM app.customer_credit_reversals reversal "
        "WHERE reversal.customer_credit_id=application.customer_credit_id) "
        "FROM app.customer_credit_applications application "
        "WHERE application.customer_credit_id=%s ORDER BY application.id",
        credit,
    )


def moved(case: dict[str, Any], allocation: UUID, target: UUID) -> dict[str, Any]:
    """Record and confirm the PAYMENT_MOVE correction; its stored move."""
    recorded = record(case, command(case["settlement"], allocation, target))
    return cast(dict[str, Any], confirm(case, draft_of(recorded))["move"])


def test_credit_the_settlement_used_from_the_payment_s_other_value_no_longer_blocks_the_move(
    migrated_database_url: str,
) -> None:
    """The owner's Q-2026-10-17-121 example on the real path: the first Customer's Payment of
    12,700, identified for the first Lease's other damage Invoice, pays that whole line (12,500)
    by mistake; its 200 excess becomes that Customer's Credit, which the closure applies to the
    pet damage line. The correction moves the 12,500: the first line owes it again, the second
    line is paid, and the Credit and its Settlement application are unchanged. The slice 7 move
    draft still refuses that Payment."""
    url = migrated_database_url
    first, second = two_leases(url)
    other_invoice = invoice_of(url, first["other_line"])
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 12_700, other_invoice)
    allocation = allocate(first, payment, "other_line", 12_500)
    credit = credit_id(recognize(first["prop"], payment, first["human"], 200))
    close_other_line_paid(first, ((first["credit"], 400), (credit, 200)))
    applied = credit_uses(url, credit)
    assert [(row[1], row[2], row[3], row[4]) for row in applied] == [
        (invoice_of(url, first["pet_line"]), 200, 0, 0)
    ]
    assert (
        outstanding(url, first["other_line"]),
        outstanding(url, first["pet_line"]),
        outstanding(url, second["other_line"]),
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
    ) == (0, 0, 12_500, 200)
    assert slice_7_draft_refusal(first, allocation, target) == ("55000", BLANKET)
    # The one body: a NULL fourth argument reads as the blanket rule, true as the narrow one
    # (review round 2, independent note N2).
    with psycopg.connect(url) as connection:
        with pytest.raises(psycopg.Error) as blanket:
            connection.execute(
                "SELECT app.wrong_unit_move_source(%s,%s,%s,NULL)",
                (first["prop"], allocation, target),
            )
        connection.rollback()
        assert (blanket.value.sqlstate, blanket.value.diag.message_primary) == ("55000", BLANKET)
        narrow = connection.execute(
            "SELECT app.wrong_unit_move_source(%s,%s,%s,true)",
            (first["prop"], allocation, target),
        ).fetchone()
    assert narrow is not None and narrow[0]["moved_usd_cents"] == 12_500
    before = settlement_row(url, first["settlement"])
    move = moved(first, allocation, target)
    assert (
        move["source_allocation_id"],
        move["moved_usd_cents"],
        move["left_on_payment_usd_cents"],
    ) == (str(allocation), 12_500, 0)
    assert (
        outstanding(url, first["other_line"]),
        outstanding(url, second["other_line"]),
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
        value(url, "SELECT app.credit_available_value(%s)", credit),
    ) == (12_500, 0, 200, 0)
    assert credit_uses(url, credit) == applied
    assert settlement_row(url, first["settlement"]) == before
    reconciled(url, first["customer"], second["customer"])


def test_a_refund_of_the_payment_s_other_value_does_not_block_the_correction(
    migrated_database_url: str,
) -> None:
    """A Payment of 1,200 pays 1,000 of the first Lease's other damage line by mistake; the Lease
    closes; the correction is recorded, then the Payment's other 200 is refunded. The confirm
    still moves the 1,000 (the source does not carry the Refund, so the draft is not stale), the
    Refund stays as it is and the slice 7 move draft refuses that Payment."""
    url = migrated_database_url
    first, second = two_leases(url)
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 1_200)
    allocation = allocate(first, payment, "other_line", 1_000)
    close_paid(first)
    recorded = record(first, command(first["settlement"], allocation, target))
    refund = create_usd_refund(
        RefundService(runtime_database_url(), financial_database_url()),
        first["prop"],
        CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 200, "Return the payer's excess"),
        actor=person(first["human"], first["prop"], "refunds.create", "refunds.read"),
    )
    refunded = (
        "SELECT app.payment_refunded_value_at(%s,'infinity'),"
        "(SELECT to_jsonb(r) FROM app.refunds r WHERE r.id=%s)"
    )
    held = rows(url, refunded, payment, refund_id(refund))
    assert held[0][0] == 200
    assert slice_7_draft_refusal(first, allocation, target) == ("55000", BLANKET)
    move = cast(dict[str, Any], confirm(first, draft_of(recorded))["move"])
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (1_000, 0)
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        1_000,
        11_500,
    )
    assert rows(url, refunded, payment, refund_id(refund)) == held
    reconciled(url, first["customer"], second["customer"])


@pytest.mark.parametrize("third_party", (False, True), ids=("payer", "third_party"))
def test_a_release_of_the_wrong_money_still_blocks_the_correction(
    migrated_database_url: str, third_party: bool
) -> None:
    """A Payment pays the whole first Lease's other damage line (12,500) by mistake; before the
    closure a credit Adjustment of 300 on that line releases 300 of it as the Lease Customer's
    Credit (the 12,200 rest is re-posted), and the closure applies that Credit. The correction of
    the re-posted allocation is refused: that Credit came from the wrong money. Nothing is
    written. With third_party, the Payment is a third party's identified for the Lease, so the
    released Credit belongs to a Customer who is not the payer (review round 1, security
    should-fix 3)."""
    url = migrated_database_url
    first, second = two_leases(url)
    other_invoice = invoice_of(url, first["other_line"])
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 12_500, third_party=third_party)
    original = allocate(first, payment, "other_line", 12_500)
    credit_adjustment(url, first["human"], first["prop"], other_invoice, first["other_line"], 300)
    [(replacement, released)] = rows(url, RELEASE, original)
    replaced = "SELECT amount_usd_cents FROM app.payment_allocations WHERE id=%s"
    assert value(url, replaced, replacement) == 12_200
    released_to = "SELECT customer_id FROM app.customer_credits WHERE id=%s"
    assert value(url, released_to, released) == first["customer"]
    close_other_line_paid(first, ((first["credit"], 400), (released, 300)))
    count = draft_count(url)
    with pytest.raises(PaymentMoveConflictError) as refused:
        record(first, command(first["settlement"], replacement, target))
    assert cause(refused) == ("55000", BLANKET)
    assert draft_count(url) == count
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        0,
        12_500,
    )


def test_a_release_on_another_invoice_of_the_payment_does_not_block_the_correction(
    migrated_database_url: str,
) -> None:
    """A Payment of 25,000 pays the first Lease's other damage line (12,500, by mistake) and its
    pet damage line (12,500); a credit Adjustment of 300 on the pet damage line releases 300 of
    the pet line's allocation as the Customer's Credit. The release is not on the wrong Invoice,
    so the correction moves the other line's 12,500; the slice 7 move draft refuses that
    Payment."""
    url = migrated_database_url
    first, second = two_leases(url)
    pet_invoice = invoice_of(url, first["pet_line"])
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 25_000)
    allocation = allocate(first, payment, "other_line", 12_500)
    allocate(first, payment, "pet_line", 12_500)
    credit_adjustment(url, first["human"], first["prop"], pet_invoice, first["pet_line"], 300)
    assert (
        outstanding(url, first["other_line"]),
        outstanding(url, first["pet_line"]),
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
    ) == (0, 0, 300)
    confirm_settlement(
        first,
        record_settlement(
            first,
            (
                settlement_refund(first, "pet", PET_DEPOSIT),
                settlement_refund(first, "security", SECURITY_DEPOSIT),
            ),
        ),
    )
    first["person"] = correction_approver(url)
    assert slice_7_draft_refusal(first, allocation, target) == ("55000", BLANKET)
    move = moved(first, allocation, target)
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (12_500, 0)
    assert (
        outstanding(url, first["other_line"]),
        outstanding(url, second["other_line"]),
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
    ) == (12_500, 0, 300)
    reconciled(url, first["customer"], second["customer"])


def test_a_refund_after_the_record_refuses_the_confirm_when_the_wrong_money_was_released(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 1, security should-fix 2), the reviewer's set-up: a
    Payment pays the whole first Lease's other damage line (12,500) by mistake; before the closure
    a credit Adjustment of 300 on that line releases 300 of it as Credit, which is reversed again
    in one call, so the 300 is back on the Payment. After the closure the correction of the
    re-posted 12,200 is recorded (no Credit or Refund then); the Payment's 300 is then refunded.
    The confirm reads the source again under its locks and refuses; the draft stays pending and
    nothing moves."""
    url = migrated_database_url
    first, second = two_leases(url)
    other_invoice = invoice_of(url, first["other_line"])
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 12_500)
    original = allocate(first, payment, "other_line", 12_500)
    credit_adjustment(url, first["human"], first["prop"], other_invoice, first["other_line"], 300)
    [(replacement, released)] = rows(url, RELEASE, original)
    credits().reverse(
        first["prop"],
        released,
        ReverseCreditCommand(uuid4(), "Credit Adjustment was a mistake"),
        actor=person(first["human"], first["prop"], "credits.reverse"),
    )
    close_other_line_paid(first, ((first["credit"], 400),))
    recorded = record(first, command(first["settlement"], replacement, target))
    create_usd_refund(
        RefundService(runtime_database_url(), financial_database_url()),
        first["prop"],
        CreateUsdRefundCommand(uuid4(), "PAYMENT", payment, 300, "Return the payer's excess"),
        actor=person(first["human"], first["prop"], "refunds.create", "refunds.read"),
    )
    # The Refund and the release refuse, not a Credit (review round 2, independent note N3).
    assert (
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
        value(url, "SELECT app.payment_refunded_value_at(%s,'infinity')", payment),
        rows(
            url,
            "SELECT allocation.payment_id,allocation.invoice_id "
            "FROM app.invoice_credit_excess_releases release JOIN app.payment_allocations "
            "allocation ON allocation.id=release.reversed_payment_allocation_id "
            "WHERE release.reversed_payment_allocation_id=%s",
            original,
        ),
    ) == (0, 300, [(payment, other_invoice)])
    with pytest.raises(PaymentMoveConflictError) as refused:
        confirm(first, draft_of(recorded))
    assert cause(refused) == ("55000", BLANKET)
    assert state(url, draft_of(recorded)) == "PENDING"
    assert (outstanding(url, first["other_line"]), outstanding(url, second["other_line"])) == (
        0,
        12_500,
    )


def test_another_payment_s_release_on_the_wrong_invoice_does_not_block_the_correction(
    migrated_database_url: str,
) -> None:
    """Review round 1 (independent should-fix 2), the reviewer's set-up: a Payment of 12,400,
    identified for the first Lease's other damage Invoice, pays 12,000 of that line by mistake and
    its 400 excess becomes Credit; another Payment pays the line's last 500. A credit Adjustment of
    300 releases from the other Payment's allocation (newest first). Only this Payment's releases
    count, so the correction moves the 12,000; the slice 7 move draft refuses that Payment."""
    url = migrated_database_url
    first, second = two_leases(url)
    other_invoice = invoice_of(url, first["other_line"])
    target = invoice_of(url, second["other_line"])
    payment = paid_by(first, 12_400, other_invoice)
    allocation = allocate(first, payment, "other_line", 12_000)
    other = paid_by(first, 500)
    allocate(first, other, "other_line", 500)
    credit = credit_id(recognize(first["prop"], payment, first["human"], 400))
    credit_adjustment(url, first["human"], first["prop"], other_invoice, first["other_line"], 300)
    [(released_payment, released)] = rows(
        url,
        "SELECT allocation.payment_id,release.customer_credit_id "
        "FROM app.invoice_credit_excess_releases release JOIN app.payment_allocations allocation "
        "ON allocation.id=release.reversed_payment_allocation_id WHERE allocation.invoice_id=%s",
        other_invoice,
    )
    assert released_payment == other
    close_other_line_paid(first, ((first["credit"], 400), (credit, 400), (released, 300)))
    assert slice_7_draft_refusal(first, allocation, target) == ("55000", BLANKET)
    move = moved(first, allocation, target)
    assert (move["moved_usd_cents"], move["left_on_payment_usd_cents"]) == (12_000, 0)
    assert (
        outstanding(url, first["other_line"]),
        outstanding(url, second["other_line"]),
        value(url, "SELECT app.payment_credit_value_at(%s,'infinity')", payment),
    ) == (12_000, 500, 400)
    reconciled(url, first["customer"], second["customer"])


def test_the_narrow_refusal_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The new source has no grant and the slice 7 source's owner and settings; the migration
    adds only that function and changes only the two sources: the new one is the slice 7 body
    with the two replacements, the slice 7 source calls it with false, the correction's source
    with true; privileges and settings stay; it is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        for role in ("prm_runtime", "prm_financial", "prm_bootstrap", "public"):
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, INTERNAL)
            ).fetchone() == (False,), role
        settings = connection.execute(
            "SELECT p.proowner,p.prosecdef,p.proconfig::text FROM pg_catalog.pg_proc p "
            "WHERE p.oid=CAST(%s AS regprocedure) OR p.oid=CAST(%s AS regprocedure) "
            "ORDER BY p.proname",
            (SLICE_7_SOURCE, INTERNAL),
        ).fetchall()
    assert len(settings) == 2 and settings[0] == settings[1]
    assert settings[0][1] is True
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270106_163"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(
        database: str,
    ) -> tuple[dict[str, tuple[Any, ...]], set[str], set[str], set[str]]:
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
            relations = {
                f"{row[0]}:{row[1]}"
                for row in connection.execute(
                    "SELECT c.oid::regclass::text,c.relacl::text FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND c.relkind IN ('r','v','m','p')"
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
            # Review round 2 (independent note N5): no constraint changes either.
            constraints = {
                f"{row[0]}:{row[1]}:{row[2]}"
                for row in connection.execute(
                    "SELECT con.conrelid::regclass::text,con.conname,"
                    "pg_catalog.pg_get_constraintdef(con.oid) FROM pg_catalog.pg_constraint con "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=con.connamespace "
                    "WHERE n.nspname='app'"
                ).fetchall()
            }
        return functions, relations, triggers, constraints

    with _temporary_migration_database("settlement_payment_move_credit") as temporary:
        alembic_command.upgrade(config, "20270106_163")
        before_functions, before_relations, before_triggers, before_constraints = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_relations, after_triggers, after_constraints = catalog(temporary)
    assert after_relations == before_relations
    assert after_triggers == before_triggers
    assert after_constraints == before_constraints
    assert set(after_functions) - set(before_functions) == {INTERNAL}
    assert set(before_functions) <= set(after_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {SLICE_7_SOURCE, SETTLEMENT_SOURCE}
    for name in (SLICE_7_SOURCE, SETTLEMENT_SOURCE):
        assert after_functions[name][1:] == before_functions[name][1:], name
    module = revision.module
    expected = before_functions[SLICE_7_SOURCE][0]
    (old_header, new_header), (old_refusal, new_refusal) = module.NEW_SOURCE_REPLACEMENTS
    assert expected.count(old_header) == 1 and expected.count(old_refusal) == 1
    expected = expected.replace(
        old_header, new_header.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
    ).replace(old_refusal, new_refusal)
    assert after_functions[INTERNAL][0] == expected
    # The same revoked privileges, owner and settings as the slice 7 source.
    assert after_functions[INTERNAL][1:] == before_functions[SLICE_7_SOURCE][1:]
    # The slice 7 source keeps its header and its body is only the call (review round 1,
    # independent should-fix 3).
    head = before_functions[SLICE_7_SOURCE][0].split("AS $function$")[0]
    assert after_functions[SLICE_7_SOURCE][0] == (
        head + "AS $function$\n    BEGIN\n        RETURN app.wrong_unit_move_source("
        "p_property,p_allocation,p_target_invoice,false);\n    END $function$\n"
    )
    [(old_return, new_return)] = module.SETTLEMENT_SOURCE_REPLACEMENTS
    assert after_functions[SETTLEMENT_SOURCE][0] == before_functions[SETTLEMENT_SOURCE][0].replace(
        old_return, new_return
    )
    assert before_functions[SETTLEMENT_SOURCE][0].count(old_return) == 1
