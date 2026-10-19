"""The 6b forfeiture reversal after closure, and reversals only at READ COMMITTED (V1-056
sub-slice 10h-2).

Owner answer 4 to Q-2026-10-06-36 and answer 6 to Q-2026-10-10-69 (BR-SETTLE-012, BR-SETTLE-013,
BR-DEP-019, DL-032): once a Lease's Final Settlement is closed, a kept Deposit's forfeiture is
reversed only inside a FORFEITURE_REVERSAL correction of that Settlement, which follows DL-032; the
6b draft is refused at record and at confirm (a waiting draft stays pending), and every other
writer is refused at insert unless such a correction links the reversal. Owner answer (a) to
Q-2026-10-19-143: a Payment allocation or Credit application reversal is recorded only at READ
COMMITTED, so the 10h-1 refusals cannot miss a Final Settlement through an older snapshot.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.credit import ReverseCreditApplicationCommand
from property_rental.final_settlement import SettlementDepositStep
from property_rental.lease_deposit_forfeiture import LeaseDepositForfeitureConflictError
from property_rental.payment_allocation import PostAllocationsCommand, ReverseAllocationCommand
from test_credit_application_migration import application_id
from test_credit_application_migration import designated as designated_credit
from test_credit_application_migration import source as application_source
from test_credit_migration import actor as credit_actor
from test_credit_migration import credit_id, recognize
from test_credit_migration import service as credits
from test_final_settlement_confirm_migration import invoice_of
from test_final_settlement_draft_migration import LINE, SECURITY, drafts
from test_final_settlement_draft_migration import refund as settlement_refund
from test_final_settlement_migration import held, one, outstanding
from test_final_settlement_preview_migration import APPROVE, forfeitures, person
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_payment_allocation_migration import actor as allocation_staff
from test_payment_allocation_migration import service as allocations
from test_payment_allocation_migration import source as allocation_source
from test_payment_move_migration import person as move_person
from test_returned_payment_after_closure_migration import allocate as allocate_line
from test_returned_payment_after_closure_migration import customer_payment
from test_settlement_extra_charge_migration import cause, state
from test_settlement_forfeiture_reversal_migration import (
    CLOSED_FORFEITURE,
    COUNTS,
    confirm_reversal,
    effect_links,
    kept_case,
    record_reversal,
    reversal_command,
    reversals,
    waiting_six_b_draft,
)
from test_settlement_real_path_migration import extra_charge_line
from test_settlement_returned_payment_migration import closed_case as returned_payment_case

REVISION = "20270110_167"
INTERNAL = ("app.refuse_closed_settlement_forfeiture_reversal()",)
SOURCE = "app.lease_deposit_reversal_source(uuid,uuid)"
ALLOCATION_TRIGGER = "app.refuse_relied_on_allocation_reversal()"
CREDIT_TRIGGER = "app.refuse_relied_on_credit_application_reversal()"
TRIGGER = "app.deposit_disposition_reversals:a0_deposit_disposition_reversals_final_settlement"
CLOSED = "A closed Final Settlement changes only through a post-settlement correction"
READ_COMMITTED = (
    "A reversal of a Payment allocation or Credit application is recorded at READ COMMITTED"
)


def test_after_closure_a_forfeiture_is_reversed_only_through_its_correction(
    migrated_database_url: str,
) -> None:
    """A really closed Settlement kept the 10,000 Security Deposit and left 4,600 open. A 6b
    reversal draft is refused at record (a conflict, P5S01, nothing written); a waiting 6b draft
    (hand-built, as the recorder would store it, because a 6b draft waiting at the closure blocks
    it with PENDING_DRAFT; review round 1) is refused at its confirm and stays pending, with
    nothing written; the 6b reversal's own writer, run as the owner outside a correction, is
    refused at insert (P5S01). Once the waiting draft is withdrawn, the FORFEITURE_REVERSAL
    correction reverses the forfeiture (linked first): the Deposit pays the 4,600 and refunds
    5,400, and is empty again."""
    url = migrated_database_url
    case = kept_case(url)
    prop, human, security, other_line = (
        case["prop"],
        case["human"],
        case["security"],
        case["other_line"],
    )
    waiting = UUID(str(waiting_six_b_draft(case)["draft_id"]))
    counts = one(url, COUNTS)
    with pytest.raises(LeaseDepositForfeitureConflictError) as confirmed:
        forfeitures().confirm_reversal(
            prop, case["disposition"], waiting, actor=person(human, prop, APPROVE)
        )
    assert cause(confirmed) == ("P5S01", CLOSED_FORFEITURE)
    assert (state(url, waiting), one(url, COUNTS), reversals(url, case["disposition"])) == (
        "PENDING",
        counts,
        0,
    )
    assert held(url, security) == 0
    with psycopg.connect(url) as connection, pytest.raises(psycopg.Error) as direct:
        connection.execute(
            "SELECT app.reverse_deposit_disposition_v2(%s,%s,%s,%s,%s,%s,%s,%s,'deposits.correct')",
            (
                prop,
                human,
                uuid4(),
                hashlib.sha256(b"outside a correction").hexdigest(),
                uuid4(),
                case["disposition"],
                "Approved forfeiture correction",
                "Reviewed correction evidence",
            ),
        )
    assert (direct.value.sqlstate, direct.value.diag.message_primary) == ("P5S01", CLOSED)
    assert (one(url, COUNTS), reversals(url, case["disposition"])) == (counts, 0)
    drafts().withdraw(
        prop,
        waiting,
        "Paid out through the correction",
        prepare_capability="deposits.correct",
        actor=person(human, prop, "deposits.correct"),
    )
    result = confirm_reversal(
        case,
        record_reversal(
            case,
            reversal_command(
                case,
                SettlementDepositStep(SECURITY, security, LINE, other_line, 4_600),
                settlement_refund(case, "security", 5_400),
            ),
        ),
    )
    assert effect_links(url, result["settlement_correction"]["id"])[0] == (
        "deposit_disposition_reversal_id"
    )
    [paid] = result["refunds"]
    assert paid["amount_usd_cents"] == 5_400
    assert (
        reversals(url, case["disposition"]),
        held(url, security),
        outstanding(url, other_line),
    ) == (1, 0, 0)


def isolation_refusal(url: str, isolation: psycopg.IsolationLevel, sql: str, args: Any) -> Any:
    """The SQLSTATE and message of one statement at the given isolation level, rolled back."""
    with psycopg.connect(url) as connection:
        connection.isolation_level = isolation
        with pytest.raises(psycopg.Error) as refused:
            connection.execute(sql, args)
        connection.rollback()
    return refused.value.sqlstate, refused.value.diag.message_primary


def test_reversals_are_recorded_only_at_read_committed(migrated_database_url: str) -> None:
    """Owner answer (a) to Q-2026-10-19-143: after a closure the Customer's 10,000 Payment becomes
    Credit, then a 30,000 Payment and that Credit pay a 40,000 EXTRA_CHARGE Invoice of the closed
    Lease (records the Settlement did not rely on). Their one-call reversals at REPEATABLE READ or
    SERIALIZABLE are refused (55000) with nothing written; at READ COMMITTED both pass and the
    40,000 is owed again."""
    url = migrated_database_url
    case = returned_payment_case(url)
    prop, human = case["prop"], case["human"]
    credit = credit_id(recognize(prop, customer_payment(case, 10_000), human, 10_000))
    line = extra_charge_line(case, amount_usd_cents=40_000)
    allocation = allocate_line(case, customer_payment(case, 30_000), line, 30_000)
    applied = application_id(
        credits().apply(
            prop,
            credit,
            designated_credit(invoice_of(url, line), line, 10_000),
            actor=credit_actor(human, prop, "credits.apply"),
        )
    )
    assert outstanding(url, line) == 0
    for isolation in (psycopg.IsolationLevel.REPEATABLE_READ, psycopg.IsolationLevel.SERIALIZABLE):
        assert isolation_refusal(
            url,
            isolation,
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (
                prop,
                allocation,
                human,
                uuid4(),
                hashlib.sha256(b"stale snapshot").hexdigest(),
                "Posted on the wrong Invoice",
            ),
        ) == ("55000", READ_COMMITTED), isolation
        assert isolation_refusal(
            url,
            isolation,
            "SELECT app.reverse_credit_application(%s,%s,%s,%s,%s)",
            (prop, applied, human, uuid4(), "Customer changed the instruction"),
        ) == ("55000", READ_COMMITTED), isolation
    assert outstanding(url, line) == 0
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Posted on the wrong Invoice"),
        actor=move_person(human, prop, "payments.allocations.reverse"),
    )
    credits().reverse_application(
        prop,
        applied,
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(human, prop, "credits.applications.reverse"),
    )
    assert outstanding(url, line) == 40_000


def test_on_a_lease_with_no_settlement_a_reversal_is_recorded_only_at_read_committed(
    migrated_database_url: str,
) -> None:
    """Review round 1 (both reviewers): the case Q-2026-10-19-143 closes is a Lease with no Final
    Settlement row yet, where the 10h-1 triggers exit early; their isolation check comes before
    that exit. A Payment allocation and a Credit application on Leases with no Final Settlement
    are refused at REPEATABLE READ and SERIALIZABLE (55000) with nothing written, and both
    reverse through the services at READ COMMITTED, so the 10,000 is owed again."""
    url = migrated_database_url
    human, prop, payment, rent_invoices = allocation_source(url)
    staff = allocation_staff(human, prop)
    proposal = allocations().proposal(prop, payment, actor=staff)
    allocations().post(
        prop,
        payment,
        PostAllocationsCommand(uuid4(), {"mode": "PROPOSAL", "proposal": proposal}),
        actor=staff,
    )
    allocation = UUID(
        str(
            one(
                url,
                "SELECT id FROM app.payment_allocations WHERE payment_id=%s "
                "ORDER BY posted_at,id LIMIT 1",
                payment,
            )[0]
        )
    )
    other_human, other_prop, credit, invoice, line, _ = application_source(url, 10_000)
    applied = application_id(
        credits().apply(
            other_prop,
            credit,
            designated_credit(invoice, line, 10_000),
            actor=credit_actor(other_human, other_prop, "credits.apply"),
        )
    )
    settlements = (
        "SELECT count(*) FROM app.final_settlements settlement JOIN app.invoices invoice "
        "ON invoice.lease_id=settlement.lease_id WHERE invoice.id=%s"
    )
    assert (one(url, settlements, rent_invoices[0]), one(url, settlements, invoice)) == ((0,), (0,))
    owed = outstanding(url, line)
    written = (
        "SELECT (SELECT count(*) FROM app.payment_allocation_reversals),"
        "(SELECT count(*) FROM app.customer_credit_application_reversals)"
    )
    counts = one(url, written)
    for isolation in (psycopg.IsolationLevel.REPEATABLE_READ, psycopg.IsolationLevel.SERIALIZABLE):
        assert isolation_refusal(
            url,
            isolation,
            "SELECT app.reverse_payment_allocation_command(%s,%s,%s,%s,%s,%s)",
            (
                prop,
                allocation,
                human,
                uuid4(),
                hashlib.sha256(b"stale snapshot").hexdigest(),
                "Posted on the wrong Invoice",
            ),
        ) == ("55000", READ_COMMITTED), isolation
        assert isolation_refusal(
            url,
            isolation,
            "SELECT app.reverse_credit_application(%s,%s,%s,%s,%s)",
            (other_prop, applied, other_human, uuid4(), "Customer changed the instruction"),
        ) == ("55000", READ_COMMITTED), isolation
    assert one(url, written) == counts
    allocations().reverse_allocation(
        prop,
        allocation,
        ReverseAllocationCommand(uuid4(), "Posted on the wrong Invoice"),
        actor=staff,
    )
    credits().reverse_application(
        other_prop,
        applied,
        ReverseCreditApplicationCommand(uuid4(), "Customer changed the instruction"),
        actor=credit_actor(other_human, other_prop, "credits.applications.reverse"),
    )
    assert one(url, written) == (int(counts[0]) + 1, int(counts[1]) + 1)
    assert outstanding(url, line) == owed + 10_000


def test_the_forfeiture_reversal_refusal_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The new function has no grant and the definer settings; the new trigger is a BEFORE INSERT
    row trigger that runs before the Deposit balance trigger; the migration adds only them,
    changes only the 6b source and the two 10h-1 trigger functions (each keeps its owner,
    privileges and settings) and is forward-only."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
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
        # BEFORE (2), ROW (1) and INSERT (4).
        assert connection.execute(
            "SELECT tgtype,tgfoid::regprocedure::text FROM pg_catalog.pg_trigger "
            "WHERE tgrelid='app.deposit_disposition_reversals'::regclass "
            "AND tgname='a0_deposit_disposition_reversals_final_settlement'"
        ).fetchone() == (7, INTERNAL[0])
        names = [
            row[0]
            for row in connection.execute(
                "SELECT tgname FROM pg_catalog.pg_trigger "
                "WHERE tgrelid='app.deposit_disposition_reversals'::regclass AND NOT tgisinternal "
                "AND tgtype & 7 = 7 ORDER BY tgname"
            ).fetchall()
        ]
    assert names[0] == "a0_deposit_disposition_reversals_final_settlement"
    assert "b_deposit_balance_source" in names
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270109_166"
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

    with _temporary_migration_database("settlement_forfeiture_reversal_after_closure") as temporary:
        alembic_command.upgrade(config, "20270109_166")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) - set(before_functions) == set(INTERNAL)
    assert set(before_functions) <= set(after_functions)
    changed = {SOURCE, ALLOCATION_TRIGGER, CREDIT_TRIGGER}
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == changed
    for name in changed:
        # Owner, privileges, definer and settings stay; only the body changes.
        assert after_functions[name][1:] == before_functions[name][1:], name
    assert "P5S01" in str(after_functions[SOURCE][0])
    for name in (ALLOCATION_TRIGGER, CREDIT_TRIGGER):
        assert "transaction_isolation" in str(after_functions[name][0]), name
    assert after_triggers - before_triggers == {TRIGGER}
    assert before_triggers <= after_triggers
    assert after_structure == before_structure
