"""Post-settlement correction: a returned Pet Refund-review Refund (V1-056 sub-slice 10c-2b-2b).

Owner answer 6 to Q-2026-10-08-55 (approved tightening): once the Lease's Final Settlement is
closed, a Pet Refund-review Refund (DL-053, paid while the Lease was signed) is no longer returned
with one call and no return of it is reversed with one call (P5S01); its return goes through the
REFUND_RETURN correction, so the value goes back to the Pet Deposit (BR-SETTLE-013, DL-032). The
owner instruction of 2026-10-09: an older one-call return of such a Refund is not reversed against
Pet Deposit money that a return-only correction left held. The owner answer to Q-2026-10-08-60
(approved tightening): a Lease Deposit forfeiture draft is recorded only at READ COMMITTED.
"""

from __future__ import annotations

from collections.abc import Callable
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
from property_rental.deposit import (
    PostgresDepositService,
    QualifyPetDepositRefundReviewCommand,
    RecordPetDepartureCommand,
)
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureConflictError
from property_rental.refund import RefundConflictError, ReverseRefundCorrectionCommand
from refund_test_support import create_pet_refund
from test_credit_migration import actor as refund_actor
from test_customer_ledger_migration import assert_reconciled
from test_deposit_migration import deposit_actor
from test_final_settlement_confirm_migration import confirm as confirm_settlement
from test_final_settlement_confirm_migration import this_month
from test_final_settlement_draft_migration import record as record_settlement
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, pet_deposit, start
from test_final_settlement_preview_migration import pay
from test_invoice_migration import financial_database_url
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_pet_refund_migration import command as pet_command
from test_refund_service_migration import corrections, refund_id, returned
from test_refund_service_migration import service as refunds
from test_settlement_correction_migration import approver, settlement_row
from test_settlement_deposit_refund_return_migration import effect_links, pet_refund
from test_settlement_extra_charge_migration import cause
from test_settlement_refund_return_migration import (
    RETURN_ROW,
    REVERSAL_ROW,
    confirm,
    net,
    now,
    record,
    return_command,
    return_values,
)
from test_termination_deposit_migration import terminate
from test_unpaid_initial_termination_migration import rent_line, signed_with_initial

CLOSED_PET_REFUND = (
    "A closed Final Settlement's Pet Deposit Refund is corrected only through a post-settlement "
    "correction"
)
CHANGED = {
    "app.require_correctable_usd_refund(uuid,uuid)": "CORRECTABLE_REPLACEMENTS",
    "app.validate_general_refund_correction()": "GENERAL_CORRECTION_REPLACEMENTS",
    "app.record_lease_deposit_forfeiture_draft(uuid,uuid,uuid,uuid,uuid,text,text)": (
        "FORFEITURE_RECORDER_REPLACEMENTS"
    ),
}
REPLACED = {"app.settlement_refund_return_settlement(uuid)"}


def reviewed_case(
    url: str,
    *,
    pet_noncompliance: bool = False,
    before_close: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """A signed Lease starting this month with its Security Deposit (10,000) and a Pet Deposit
    (20,000). The pet leaves and a DL-053 review qualifies; a Pet Refund-review Refund pays 15,000
    while the Lease is signed and 3,000 of it comes back with the one-call return. The Initial Rent
    is paid, the Lease is terminated with no forfeiture ground, and the Final Settlement refunds
    the Security Deposit (10,000) and the Pet Deposit's 8,000 and closes. With pet_noncompliance
    the Lease is terminated for pet noncompliance after three warnings (BR-DEP-022): the 3,000
    that came back before the termination is the Customer's pay-back money (owner answer (a) to
    Q-2026-10-11-84, sub-slice 10c-2b-5), so the forfeitures take the Security Deposit's 10,000
    and the Pet Deposit's 5,000 and the Settlement refunds the 3,000 to the Customer. before_close
    runs just before the Settlement is confirmed. A correction approver is ready."""
    source = signed_with_initial(url, this_month(url))
    human, prop, lease = source["actor"], source["property"], source["lease"]
    customer, day = source["customer"], source["today"]
    pet = pet_deposit(url, human, prop, lease, day)
    deposits = PostgresDepositService(financial_database_url(), prop, human)
    who = deposit_actor(human, prop)
    departure = RecordPetDepartureCommand(uuid4(), uuid4(), pet, day, "Pet permanently left")
    deposits.record_pet_departure(departure, actor=who)
    review = QualifyPetDepositRefundReviewCommand(
        uuid4(),
        uuid4(),
        departure.departure_id,
        pet,
        30000,
        "All valid pet costs resolved separately; liability is not capped by Deposit",
        "Synthetic inspection and resolution evidence",
        "Qualified Pet exception",
    )
    deposits.qualify_pet_refund_review(review, actor=who)
    review_refund = refund_id(
        create_pet_refund(
            refunds(),
            prop,
            pet_command(pet, review.review_id, 15_000),
            actor=refund_actor(human, prop, "refunds.create"),
        )
    )
    # Before closure the one-call return still works (DL-053).
    [early_return] = corrections(
        refunds().verify_usd_return(
            prop,
            review_refund,
            returned(3_000),
            actor=refund_actor(human, prop, "refunds.correct"),
        )
    )
    rent, owed = rent_line(url, source["invoice"])
    pay(url, prop, human, customer, source["invoice"], rent, owed)
    if pet_noncompliance:
        terminate_for_disposition(url, deposits, lease, day)
    else:
        terminate(url, human, prop, lease, day, voluntary=False)
    case: dict[str, Any] = {
        "url": url,
        "human": human,
        "prop": prop,
        "lease": lease,
        "customer": customer,
        "security": source["deposit"],
        "pet": pet,
        "settlement": start(prop, human, lease),
        "cash": UUID(str(one(url, "SELECT id FROM app.refund_methods WHERE code='CASH'")[0])),
        "review_refund": review_refund,
        "early_return": UUID(str(early_return["id"])),
    }
    assert (held(url, case["security"]), held(url, pet), net(url, review_refund)) == (
        10_000,
        8_000,
        12_000,
    )
    if pet_noncompliance:
        for deposit in (case["security"], pet):
            forfeit_through_draft(deposits, deposit)
        # Owner answer (a) to Q-2026-10-11-84: the forfeiture leaves out the 3,000 returned
        # before the termination, and the Settlement refunds it.
        with psycopg.connect(url) as connection:
            forfeited = connection.execute(
                "SELECT deposit_id,amount_usd_cents FROM app.deposit_dispositions "
                "WHERE deposit_id IN (%s,%s)",
                (case["security"], pet),
            ).fetchall()
        assert sorted(forfeited) == sorted([(case["security"], 10_000), (pet, 5_000)])
        assert (held(url, case["security"]), held(url, pet)) == (0, 3_000)
        draft = record_settlement(case, (settlement_refund(case, "pet", 3_000),))
    else:
        draft = record_settlement(
            case,
            (settlement_refund(case, "security", 10_000), settlement_refund(case, "pet", 8_000)),
        )
    if before_close is not None:
        before_close(case)
    confirm_settlement(case, draft)
    assert one(
        url,
        "SELECT closed_at IS NOT NULL FROM app.final_settlements WHERE id=%s",
        case["settlement"],
    ) == (True,)
    if pet_noncompliance:
        assert one(
            url,
            "SELECT refund.usd_accounting_value_cents,refund.recipient_customer_id "
            "FROM app.final_settlement_refund_details detail "
            "JOIN app.refunds refund ON refund.id=detail.refund_id "
            "WHERE detail.final_settlement_id=%s AND detail.deposit_id=%s",
            case["settlement"],
            pet,
        ) == (3_000, customer)
        assert held(url, pet) == 0
    case["person"] = approver(url)
    return case


def count_corrections(url: str, refund: object) -> int:
    return int(
        one(url, "SELECT count(*) FROM app.refund_corrections WHERE refund_id=%s", refund)[0]
    )


def reversal() -> ReverseRefundCorrectionCommand:
    """A one-call reversal of a verified return, with a fresh key."""
    return ReverseRefundCorrectionCommand(uuid4(), "Bank recall slip", "The return was a mistake")


def test_an_older_return_is_not_reversed_against_money_a_return_only_correction_left_held(
    migrated_database_url: str,
) -> None:
    """Owner answer 6 to Q-2026-10-08-55 and the owner instruction of 2026-10-09: after closure the
    one-call return of the Pet Refund-review Refund is refused (P5S01, a conflict), and so is the
    one-call reversal of its 3,000 return recorded before closure. A return-only correction of the
    Settlement's Pet Deposit Refund (5,000) then leaves the Pet Deposit holding 5,000; the one-call
    reversal of the older return is still refused, and a reversal row or an unlinked return row
    written directly is refused by the Refund correction check (P5S01). Nothing is written; the Pet
    Deposit keeps 5,000."""
    url = migrated_database_url
    case = reviewed_case(url)
    review_refund, pet = case["review_refund"], case["pet"]
    with pytest.raises(RefundConflictError) as one_call:
        refunds().verify_usd_return(
            case["prop"],
            review_refund,
            returned(1_000),
            actor=refund_actor(case["human"], case["prop"], "refunds.correct"),
        )
    assert cause(one_call) == ("P5S01", CLOSED_PET_REFUND)
    with pytest.raises(RefundConflictError) as empty:
        refunds().reverse_correction(
            case["prop"],
            review_refund,
            case["early_return"],
            reversal(),
            actor=refund_actor(case["human"], case["prop"], "refunds.corrections.reverse"),
        )
    assert cause(empty) == ("P5S01", CLOSED_PET_REFUND)
    confirm(case, record(case, return_command(case, pet_refund(case), 5_000, new=False)))
    assert (held(url, pet), net(url, review_refund)) == (5_000, 12_000)
    before = count_corrections(url, review_refund)
    with pytest.raises(RefundConflictError) as reversed_:
        refunds().reverse_correction(
            case["prop"],
            review_refund,
            case["early_return"],
            reversal(),
            actor=refund_actor(case["human"], case["prop"], "refunds.corrections.reverse"),
        )
    assert cause(reversed_) == ("P5S01", CLOSED_PET_REFUND)
    with pytest.raises(psycopg.Error) as direct, psycopg.connect(url) as connection:
        connection.execute(
            REVERSAL_ROW,
            (
                uuid4(),
                case["human"],
                "refunds.corrections.reverse",
                case["early_return"],
                review_refund,
            ),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == (
        "P5S01",
        CLOSED_PET_REFUND,
    )
    # Review round 1: a return row written directly, unlinked, is refused too, whether it carries
    # the one-call authorization or financial.approve.
    for reference in ("refunds.correct", "financial.approve"):
        with pytest.raises(psycopg.Error) as unlinked, psycopg.connect(url) as connection:
            connection.execute(
                RETURN_ROW,
                return_values(uuid4(), 1_000, case["human"], reference, now(url), review_refund),
            )
        assert (unlinked.value.sqlstate, unlinked.value.diag.message_primary) == (
            "P5S01",
            CLOSED_PET_REFUND,
        ), reference
    assert count_corrections(url, review_refund) == before
    assert (held(url, pet), net(url, review_refund)) == (5_000, 12_000)
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_pet_refund_review_refund_is_returned_through_a_correction(
    migrated_database_url: str,
) -> None:
    """Owner answer 6 to Q-2026-10-08-55 with answer 3: after closure the Pet Refund-review Refund
    comes back through REFUND_RETURN. A return-only correction of 4,000 writes the verified return
    under financial.approve, linked first, and the Pet Deposit holds 4,000; no step runs. A later
    return of 2,000 with a new Refund runs the DL-032 step: with no open debt the plan's Deposit
    Refund step refunds the Pet Deposit's whole 6,000 to the Customer. The Settlement row is
    unchanged and the ledger reconciles."""
    url = migrated_database_url
    case = reviewed_case(url)
    review_refund, pet, customer = case["review_refund"], case["pet"], case["customer"]
    before = settlement_row(url, case["settlement"])
    held_only = confirm(case, record(case, return_command(case, review_refund, 4_000, new=False)))
    assert effect_links(url, held_only["settlement_correction"]["id"]) == ["refund_correction_id"]
    [returned_row] = held_only["refund_corrections"]
    assert (
        returned_row["refund_id"],
        returned_row["returned_amount_usd_cents"],
        returned_row["resulting_net_refund_usd_cents"],
        returned_row["authorization_reference"],
    ) == (str(review_refund), 4_000, 8_000, "financial.approve")
    assert (
        held_only["refunds"],
        held_only["credit_applications"],
        held_only["deposit_applications"],
    ) == ([], [], [])
    assert (held(url, pet), net(url, review_refund)) == (4_000, 8_000)
    paid_again = confirm(
        case,
        record(
            case,
            return_command(case, review_refund, 2_000, settlement_refund(case, "pet", 6_000)),
        ),
    )
    assert effect_links(url, paid_again["settlement_correction"]["id"]) == [
        "refund_correction_id",
        "refund_id",
    ]
    [paid] = paid_again["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
        paid["refund_method_id"],
    ) == (str(pet), str(customer), 6_000, str(case["cash"]))
    assert (held(url, pet), net(url, review_refund)) == (0, 6_000)
    assert settlement_row(url, case["settlement"]) == before
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, customer)


def test_a_returned_pet_refund_after_a_pet_noncompliance_termination_is_paid_back(
    migrated_database_url: str,
) -> None:
    """Review round 1 (Q-2026-10-09-61), changed by the owner's pay-back answers (Q-2026-10-09-61,
    Q-2026-10-10-75 (A), sub-slice 10c-2b-5; renamed, it was "is only held"): after a pet
    noncompliance termination (BR-DEP-022) the Pet Deposit is kept. Its Pet Refund-review Refund's
    return of 2,000 with a new Refund is accepted and, with no open debt, refunds the 2,000 to the
    Customer; a return-only correction of 2,000 more leaves the Pet Deposit holding 2,000 of
    pay-back money, on the DL-032 path although its forfeiture stays, and a forfeiture after
    closure still cannot take it (P5S01)."""
    url = migrated_database_url
    case = reviewed_case(url, pet_noncompliance=True)
    review_refund, pet = case["review_refund"], case["pet"]
    path = "SELECT app.lease_deposit_settlement_path(%s,%s)->>'path'"
    assert held(url, pet) == 0
    assert one(url, path, case["prop"], pet) == ("KEPT",)
    paid_back = confirm(
        case,
        record(
            case,
            return_command(case, review_refund, 2_000, settlement_refund(case, "pet", 2_000)),
        ),
    )
    [paid] = paid_back["refunds"]
    assert (
        paid["source_deposit_id"],
        paid["recipient_customer_id"],
        paid["amount_usd_cents"],
    ) == (str(pet), str(case["customer"]), 2_000)
    assert (held(url, pet), net(url, review_refund)) == (0, 10_000)
    confirm(case, record(case, return_command(case, review_refund, 2_000, new=False)))
    assert (held(url, pet), net(url, review_refund)) == (2_000, 8_000)
    assert one(url, path, case["prop"], pet) == ("DL_032",)
    with pytest.raises(LeaseDepositForfeitureConflictError) as forfeited:
        forfeit_through_draft(
            PostgresDepositService(financial_database_url(), case["prop"], case["human"]), pet
        )
    assert cause(forfeited)[0] == "P5S01"
    assert held(url, pet) == 2_000
    with psycopg.connect(url) as connection:
        assert_reconciled(connection, case["customer"])


def test_a_stale_repeatable_read_one_call_correction_fails_on_the_deposit_guard(
    migrated_database_url: str,
) -> None:
    """Security review round 1: a REPEATABLE READ transaction whose snapshot predates the closure
    does not see the closure in its plain read, but its one-call return and its reversal of the
    older return both fail first on the Pet Deposit's serialization guard that the closure updated
    (40001); the Refund keeps its net value. It checks the fail-closed claim of the migration's
    comment; the guard predates migration 109 (review round 2)."""
    url = migrated_database_url
    stale: list[psycopg.Connection[Any]] = []

    def snapshot(case: dict[str, Any]) -> None:
        for _ in range(2):
            connection: psycopg.Connection[Any] = psycopg.connect(url)
            stale.append(connection)
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            connection.execute("SET LOCAL lock_timeout='5000ms'")
            connection.execute("SELECT 1")

    # Security review round 2: the stale connections are closed on every path.
    try:
        case = reviewed_case(url, before_close=snapshot)
        review_refund = case["review_refund"]
        calls = (
            (
                "SELECT app.verify_usd_refund_return(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    case["prop"],
                    review_refund,
                    case["human"],
                    uuid4(),
                    1_000,
                    now(url),
                    "Bank return BT-9",
                    "Bank statement line 9",
                    "The transfer came back",
                ),
            ),
            (
                "SELECT app.reverse_refund_correction(%s,%s,%s,%s,%s,%s,%s)",
                (
                    case["prop"],
                    review_refund,
                    case["early_return"],
                    case["human"],
                    uuid4(),
                    "Bank recall slip",
                    "The return was a mistake",
                ),
            ),
        )
        for connection, (statement, parameters) in zip(stale, calls, strict=True):
            with pytest.raises(psycopg.Error) as failed:
                connection.execute(statement, parameters)
            assert failed.value.sqlstate == "40001", statement
            connection.rollback()
    finally:
        for connection in stale:
            connection.close()
    assert net(url, review_refund) == 12_000


def test_a_lease_deposit_forfeiture_draft_is_recorded_only_at_read_committed(
    migrated_database_url: str,
) -> None:
    """Owner answer to Q-2026-10-08-60 (approved tightening, as the answers to Q-2026-10-08-51 and
    Q-2026-10-08-59): a Lease Deposit forfeiture draft is refused outside READ COMMITTED (55000) and
    nothing is written; at READ COMMITTED the same call reaches the closure refusal (P5S01)."""
    url = migrated_database_url
    case = reviewed_case(url)
    call = "SELECT app.record_lease_deposit_forfeiture_draft(%s,%s,%s,%s,%s,%s,'deposits.dispose')"
    for level in ("REPEATABLE READ", "SERIALIZABLE"):
        draft = uuid4()
        with pytest.raises(psycopg.Error) as isolation, psycopg.connect(url) as connection:
            connection.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
            connection.execute(
                call, (case["prop"], case["human"], draft, case["security"], uuid4(), "Kept")
            )
        assert (isolation.value.sqlstate, isolation.value.diag.message_primary) == (
            "55000",
            "A Lease Deposit forfeiture draft is recorded at READ COMMITTED",
        ), level
        assert one(url, "SELECT count(*) FROM app.financial_drafts WHERE id=%s", draft) == (0,)
    with pytest.raises(psycopg.Error) as closed, psycopg.connect(url) as connection:
        connection.execute(
            call, (case["prop"], case["human"], uuid4(), case["security"], uuid4(), "Kept")
        )
    assert (closed.value.sqlstate, closed.value.diag.message_primary) == (
        "P5S01",
        "A closed Final Settlement's Deposit is forfeited only through a post-settlement "
        "correction",
    )


def test_the_pet_refund_return_migration_is_forward_only(migrated_database_url: str) -> None:
    """The migration replaces only the returned-Refund Settlement lookup and patches three
    functions (the one-call Refund correction source check, the Refund correction check and the
    Lease forfeiture recorder; each new body exactly the old one with its replacements); every
    changed function keeps its owner, SECURITY DEFINER, settings and privileges."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("20261113_109")
    assert revision is not None and revision.down_revision == "20261112_108"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()

    def catalog(database: str) -> tuple[dict[str, tuple[object, ...]], set[str], set[str]]:
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
                str(row[0])
                for row in connection.execute(
                    "SELECT c.oid::regclass::text FROM pg_catalog.pg_class c "
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
        return functions, relations, triggers

    with _temporary_migration_database("settlement_pet_refund_return") as temporary:
        alembic_command.upgrade(config, "20261112_108")
        before_functions, before_relations, before_triggers = catalog(temporary)
        alembic_command.upgrade(config, "20261113_109")
        after_functions, after_relations, after_triggers = catalog(temporary)
    assert (after_relations, after_triggers) == (before_relations, before_triggers)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == set(CHANGED) | REPLACED
    for function, replacements in CHANGED.items():
        body = str(before_functions[function][0])
        for anchor, replacement in getattr(revision.module, replacements):
            body = body.replace(anchor, replacement)
        assert after_functions[function][0] == body, function
    for function in set(CHANGED) | REPLACED:
        assert after_functions[function][1:] == before_functions[function][1:], function
