"""A Pet Deposit receipt after closure needs its correction's link (V1-056 sub-slice 10e-2b-3).

Owner answer 2 to Q-2026-10-12-89 (an approved tightening) and answer (a) to Q-2026-10-12-90:
once the Lease's Final Settlement is closed, every Pet Deposit receipt of that Lease must be linked
to a correction of that Settlement confirmed in the same transaction; the receipt table holds the
rule, not only its single internal writer. Before closure nothing changes. The linked path is the
right Pet receipts of the receipt correction tests (sub-slices 10e-2b-1 to 10e-2d).

Also the known limit of sub-slice 10e-2d (owner note 4 of 2026-10-17): a forfeited right receipt
into a Pet Deposit that holds unreceived pay-back money is refused, and staff finish it with a
HELD_VALUE_REFUND correction first.
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

from deposit_disposition_test_support import terminate_for_disposition
from lease_deposit_forfeiture_test_support import forfeit_through_draft
from payment_test_support import seed_deposit_payment
from property_rental.deposit import PostgresDepositService
from property_rental.final_settlement import FinalSettlementConflictError
from test_deposit_migration import create_pet, deposit_actor
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, start
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_move_migration import rows, value
from test_settlement_correction_migration import approver
from test_settlement_deposit_receipt_correction_migration import REASON, confirm, counts
from test_settlement_deposit_receipt_forfeiture_migration import (
    ONLY_NEW_MONEY,
    forfeitures,
    path,
)
from test_settlement_deposit_receipt_payback_forfeiture_migration import (
    payback_count,
    payback_ground_case,
    record_correction,
)
from test_settlement_extra_charge_migration import cause
from test_settlement_forfeiture_reversal_migration import (
    confirm_reversal,
    disposition_of,
    record_reversal,
    reversal_command,
)
from test_settlement_held_value_refund_migration import (
    confirm_held,
    held_command,
    record_held,
    return_only,
)
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

REVISION = "20261224_150"
PATCHED = {"app.validate_deposit_receipt()"}
CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
WITH_ITS_CORRECTION = "A correction effect is written with its correction"
RECEIPT = (
    "INSERT INTO app.deposit_receipts(id,deposit_id,payment_id,amount_usd_cents,occurred_at,"
    "actor_id) VALUES (%s,%s,%s,%s,clock_timestamp(),%s)"
)


def pet_lease_case(url: str) -> dict[str, Any]:
    """A signed Lease starting this month with its Security Deposit (10,000, received through the
    Reservation) and an approved Pet Deposit (20,000 required) that holds nothing. The Initial Rent
    is paid; the Lease is terminated for pet noncompliance after three warnings (BR-DEP-022); the
    Security Deposit is forfeited through the draft and kept. The Final Settlement is started, not
    closed."""
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
    pet, _ = create_pet(deposits, deposit_actor(human, prop), lease, approval, day)
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    terminate_for_disposition(url, deposits, lease, day)
    forfeit_through_draft(deposits, source["deposit"])
    return {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
    }


def closed(case: dict[str, Any]) -> None:
    """The real closure (sub-slice 8e-3): nothing is owed and no Deposit holds money to use."""
    confirm_settlement(case, record_settlement(case, ()))
    assert value(
        case["url"],
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        case["settlement"],
    )


def pet_receipt(
    connection: psycopg.Connection[tuple[Any, ...]],
    case: dict[str, Any],
    amount: int,
    link_to: UUID | None = None,
) -> tuple[Any, Any]:
    """Insert, as the owner and inside a savepoint, a Pet Deposit receipt of a new Payment of the
    Lease's Customer, first linked to the correction when one is given; the refusal (SQLSTATE and
    message), or (None, None) when the insert passes. The caller rolls the transaction back. On an
    autocommit connection the block is its own transaction instead, and a passing insert commits."""
    receipt = uuid4()
    # Inside an open transaction, transaction() is a savepoint and never commits.
    connection.execute("SELECT 1")
    try:
        with connection.transaction():
            payment = seed_deposit_payment(
                connection, deposit_id=case["pet"], actor_id=case["human"], amount=amount
            )
            if link_to is not None:
                connection.execute(
                    "SELECT app.link_settlement_correction_effect(%s,'deposit_receipt_id',%s)",
                    (link_to, receipt),
                )
            connection.execute(RECEIPT, (receipt, case["pet"], payment, amount, case["human"]))
    except psycopg.Error as refused:
        if refused.sqlstate is None:
            # A client-side error is not a database refusal; never read it as a pass.
            raise
        return refused.sqlstate, refused.diag.message_primary
    return None, None


def direct_pet_receipt(case: dict[str, Any], amount: int) -> tuple[Any, Any]:
    """A Pet Deposit receipt outside any correction, rolled back."""
    with psycopg.connect(case["url"]) as connection:
        found = pet_receipt(connection, case, amount)
        connection.rollback()
    return found


def committed_pet_receipt(case: dict[str, Any], amount: int) -> tuple[Any, Any]:
    """A Pet Deposit receipt outside any correction in its own transaction, which commits when the
    insert passes, so the caller's check that nothing was written is real."""
    with psycopg.connect(case["url"], autocommit=True) as connection:
        return pet_receipt(connection, case, amount)


def receipts(url: str, deposit: UUID) -> list[tuple[Any, ...]]:
    return rows(
        url,
        "SELECT payment_id,amount_usd_cents FROM app.deposit_receipts WHERE deposit_id=%s",
        deposit,
    )


def test_after_closure_a_pet_deposit_receipt_needs_its_own_settlement_s_correction(
    migrated_database_url: str,
) -> None:
    """Before closure (the Settlement started, not closed) a direct Pet Deposit receipt passes as
    before. After the real closure the same receipt is refused (P5S01, the 8e-1 message), also in
    a transaction of its own that would commit it, and nothing is written. A correction of the
    same Settlement confirmed in an earlier transaction cannot link a receipt at all (the effect
    trigger refuses the link, 23514). A correction of another Lease's closed Settlement, confirmed
    in the same transaction, does not open the first Lease's Pet Deposit: only a correction of its
    own Settlement does (a hand-built, rolled-back transaction in which the other Lease's
    FORFEITURE_REVERSAL is confirmed and links both receipts)."""
    url = migrated_database_url
    first = pet_lease_case(url)
    assert direct_pet_receipt(first, 1_000) == (None, None)
    closed(first)
    assert direct_pet_receipt(first, 1_000) == ("P5S01", CLOSED)
    assert committed_pet_receipt(first, 1_000) == ("P5S01", CLOSED)
    assert receipts(url, first["pet"]) == []
    first["person"] = approver(url)
    first["disposition"] = disposition_of(url, first["security"])
    confirm_reversal(
        first,
        record_reversal(
            first, reversal_command(first, settlement_refund(first, "security", 10_000))
        ),
    )
    [earlier] = rows(
        url,
        "SELECT id FROM app.settlement_corrections WHERE final_settlement_id=%s",
        first["settlement"],
    )
    with psycopg.connect(url) as connection:
        assert pet_receipt(connection, first, 1_000, earlier[0]) == ("23514", WITH_ITS_CORRECTION)
        connection.rollback()
    assert receipts(url, first["pet"]) == []

    other = pet_lease_case(url)
    assert other["lease"] != first["lease"]
    closed(other)
    other["person"] = approver(url)
    other["disposition"] = disposition_of(url, other["security"])
    draft = record_reversal(
        other, reversal_command(other, settlement_refund(other, "security", 10_000))
    )
    with psycopg.connect(url) as connection:
        connection.execute(
            "SELECT app.confirm_settlement_forfeiture_reversal(%s,%s,%s,'financial.approve')",
            (other["prop"], other["person"], draft),
        )
        [correction] = connection.execute(
            "SELECT id FROM app.settlement_corrections WHERE final_settlement_id=%s",
            (other["settlement"],),
        ).fetchall()
        # The confirm sets its constraints immediate; a link is written before its receipt.
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        assert pet_receipt(connection, first, 1_000, correction[0]) == ("P5S01", CLOSED)
        assert pet_receipt(connection, first, 1_000) == ("P5S01", CLOSED)
        assert pet_receipt(connection, other, 1_000, correction[0]) == (None, None)
        assert pet_receipt(connection, other, 1_000) == ("P5S01", CLOSED)
        connection.rollback()
    assert (receipts(url, first["pet"]), receipts(url, other["pet"])) == ([], [])
    assert (
        rows(
            url,
            "SELECT id FROM app.settlement_corrections WHERE final_settlement_id=%s",
            other["settlement"],
        )
        == []
    )


def test_staff_finish_a_forfeited_right_receipt_after_a_held_value_refund_empties_the_deposit(
    migrated_database_url: str,
) -> None:
    """The known limit of sub-slice 10e-2d on the real path (owner note 4 of 2026-10-17; the review
    round 1 set-up): after closure the Final Settlement's 3,000 Pet Refund comes back by a
    return-only correction, so the Pet Deposit (pet noncompliance ground, never forfeited) holds
    3,000 of unreceived pay-back money (count 3,000, DL-032). A receipt correction whose right Pet
    receipt the ground forfeits is refused while that money is held (55000), and writes nothing. A
    HELD_VALUE_REFUND correction naming the return refunds the 3,000 (no debt is open), so the Pet
    Deposit is empty and the Customer has the pay-back money once (count 0); the same receipt
    correction then passes and forfeits the whole 5,000 Pet receipt, linked."""
    url = migrated_database_url
    case = payback_ground_case(url)
    pet = case["pet"]
    [settlement_pet_refund] = rows(
        url,
        "SELECT id FROM app.refunds WHERE source_deposit_id=%s AND pet_refund_review_id IS NULL",
        pet,
    )
    earlier = return_only(case, settlement_pet_refund[0], 3_000)
    assert (held(url, pet), payback_count(url, pet), path(url, case, pet)) == (
        3_000,
        3_000,
        "DL_032",
    )
    before = counts(url)
    with pytest.raises(FinalSettlementConflictError) as refused:
        record_correction(case, 5_000, 5_000)
    assert cause(refused) == ("55000", ONLY_NEW_MONEY)
    assert counts(url) == before
    held_back = confirm_held(
        case, record_held(case, held_command(case, earlier, settlement_refund(case, "pet", 3_000)))
    )
    [again] = held_back["refunds"]
    assert (again["source_deposit_id"], again["amount_usd_cents"]) == (str(pet), 3_000)
    assert (held(url, pet), payback_count(url, pet)) == (0, 0)
    result = confirm(case, record_correction(case, 5_000, 5_000))
    correction = UUID(str(result["settlement_correction"]["id"]))
    assert [(row[0], row[1], row[5], row[6], row[7]) for row in forfeitures(url, pet)] == [
        (5_000, REASON, False, "BR-DEP-022", correction)
    ]
    assert one(
        url,
        "SELECT count(*) FROM app.settlement_correction_effects effect "
        "JOIN app.deposit_receipts receipt ON receipt.id=effect.deposit_receipt_id "
        "WHERE effect.settlement_correction_id=%s AND receipt.deposit_id=%s "
        "AND receipt.amount_usd_cents=5000",
        correction,
        pet,
    ) == (1,)
    assert (held(url, pet), payback_count(url, pet)) == (0, 0)


def test_the_pet_receipt_link_migration_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration adds no function, constraint or trigger and changes only the receipt check
    (privileges, owner and settings kept; its body is exactly the old one with the module's
    replacement), and is forward-only."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20261223_149"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
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
        constraints = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT c.conrelid::regclass::text,c.conname,"
                "pg_catalog.pg_get_constraintdef(c.oid) "
                "FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.connamespace WHERE n.nspname='app'",
            )
        }
        triggers = {
            ":".join(str(item) for item in row)
            for row in rows(
                database,
                "SELECT t.tgrelid::regclass::text,t.tgname,t.tgenabled,"
                "pg_catalog.pg_get_triggerdef(t.oid) FROM pg_catalog.pg_trigger t "
                "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND NOT t.tgisinternal",
            )
        }
        return functions, constraints, triggers

    with _temporary_migration_database("settlement_pet_receipt_link") as temporary:
        alembic_command.upgrade(config, "20261223_149")
        before_functions, before_constraints, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_constraints, after_triggers = catalog(temporary)
    assert (after_constraints, after_triggers) == (before_constraints, before_triggers)
    assert set(after_functions) == set(before_functions)
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
