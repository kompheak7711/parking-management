"""The 8e-1 closed Final Settlement refusal at READ COMMITTED only (V1-056 sub-slice 10h-4b).

Owner answer (a) to Q-2026-10-20-145 point 1 (BR-SETTLE-012, BR-SETTLE-013, DL-032): every write to
the eight tables a closed Final Settlement guards (Invoices, one-time charges, VOID events,
Adjustments and their reversals, Late-payment decisions, Charges and Charge corrections) is refused
(55000) at an isolation level other than READ COMMITTED, before any read, so a snapshot taken
before a Settlement started cannot change what the closed Settlement left. The guards that three
committed REPEATABLE READ tests proved are also shown here at READ COMMITTED, where every app path
writes: the later writer waits for the earlier one's lock and is refused after its commit.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.types.json import Jsonb

import test_final_settlement_draft_migration as final_settlement_draft_tests
from property_rental.lease_termination import TerminationBasis
from termination_test_support import terminate_test_lease
from test_final_settlement_closed_refusal_migration import CLOSED, TABLES, close, invoice_of
from test_final_settlement_draft_migration import leaving_case
from test_final_settlement_migration import one, outstanding
from test_final_settlement_migration import start as start_settlement
from test_invoice_migration import create_recurring_rent_invoice, setup_signed_lease
from test_lease_migration import create_draft, setup_sources, sign_lease
from test_migrations import _temporary_migration_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_pet_payback_restoration_refusal_migration import wait_until_blocked_by
from test_settlement_preview_waiting_drafts_migration import STRUCTURE

REVISION = "20270113_170"
GUARD = "app.refuse_closed_final_settlement_change()"
READ_COMMITTED_ONLY = "An Invoice, Adjustment or Late-payment record is written at READ COMMITTED"
STRICTER = ("REPEATABLE READ", "SERIALIZABLE")
ADJUST = (
    "INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,"
    "amount_usd_cents,source_reference,reason,occurred_at,actor_id,authorization_reference) "
    "VALUES (%s,%s,%s,'CREDIT',%s,%s,'Approved correction',clock_timestamp(),%s,'invoice.adjust')"
)
ISSUE = (
    "UPDATE app.invoices SET status='UNPAID',issued_at=statement_timestamp(),issued_by=%s,"
    "version=2,updated_at=statement_timestamp(),updated_by=%s WHERE id=%s"
)
REDUCE = (
    "INSERT INTO app.late_payment_charge_corrections(id,late_payment_charge_id,correction_kind,"
    "amount_usd_cents,reason,previous_obligation_usd_cents,resulting_obligation_usd_cents,"
    "occurred_at,actor_id,authorization_reference,correlation_id) VALUES "
    "(%s,%s,'REDUCTION',100,'Approved reduction',8000,7900,%s,%s,'late-payment.correct',%s)"
)
STALE_BALANCE = "Late-payment correction previous balance is stale"
VIOLATES = "Invoice Adjustment would violate the issued obligation"
NOT_SIGNED = "Rent Invoice requires an applicable signed Lease"


def attempt(url: str, sql: str, parameters: tuple[object, ...]) -> tuple[str, str]:
    """One READ COMMITTED writer in its own connection: its outcome after its commit."""
    try:
        with psycopg.connect(url) as connection:
            connection.execute(sql, parameters)
    except psycopg.Error as error:
        return str(error.sqlstate), str(error.diag.message_primary)
    return "committed", ""


def waits_then(
    url: str, holder: psycopg.Connection[Any], sql: str, parameters: tuple[object, ...]
) -> tuple[str, str]:
    """A second writer starts while `holder` holds its lock, waits for it, and is decided only
    after `holder` commits. If the wait is not seen, `holder` rolls back before the failure is
    raised, so the second writer never waits forever (review round 2 note)."""
    with ThreadPoolExecutor(1) as pool:
        waiting = pool.submit(attempt, url, sql, parameters)
        try:
            wait_until_blocked_by(url, holder)
        except AssertionError:
            holder.rollback()
            raise
        holder.commit()
        return waiting.result(timeout=60)


def issued_rent(url: str, period_start: date) -> tuple[UUID, UUID, UUID]:
    """An issued 80,000 Rent Invoice of a signed Lease (no Final Settlement): actor, Invoice,
    line."""
    with psycopg.connect(url) as connection:
        actor, _, customer, lease = setup_signed_lease(
            connection, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
        )
        invoice, line = create_recurring_rent_invoice(
            connection,
            actor_id=actor,
            customer_id=customer,
            lease_id=lease,
            period_start=period_start,
        )
    return actor, invoice, line


def test_an_older_snapshot_cannot_change_a_closed_lease_s_invoice(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gap of Q-2026-10-20-145 point 1: a REPEATABLE READ and a SERIALIZABLE transaction whose
    snapshots were taken before the Lease's Final Settlement started still see no Settlement row
    after it starts and closes, so the closed-Settlement read alone would let a credit Adjustment
    of the unpaid Damage line through and lower what the closed Settlement left owing. Each is
    refused (55000) before any read, and nothing is written; the same Adjustment at READ COMMITTED
    meets the closed Settlement (P5S01)."""
    url = migrated_database_url
    older = {level: psycopg.connect(url) for level in STRICTER}

    def start_after_the_snapshots(prop: UUID, human: UUID, lease: UUID) -> UUID:
        # The snapshots are taken right before leaving_case starts the Settlement.
        for level, connection in older.items():
            connection.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
            assert connection.execute(
                "SELECT count(*) FROM app.final_settlements WHERE lease_id=%s", (lease,)
            ).fetchone() == (0,), level
        return start_settlement(prop, human, lease)

    monkeypatch.setattr(final_settlement_draft_tests, "start", start_after_the_snapshots)
    refusals: dict[str, tuple[object, object]] = {}
    try:
        case = leaving_case(url)
        human, lease, line = case["human"], case["lease"], case["other_line"]
        invoice = invoice_of(url, line)
        close(url, human, case["settlement"])
        owed = outstanding(url, line)
        # The unpaid 12,500 Damage line the closure left owing (review round 1 note).
        assert owed == 12_500
        before = (
            one(url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice),
            owed,
        )
        for level, connection in older.items():
            # The older snapshot still sees no Settlement row, closed or not.
            assert connection.execute(
                "SELECT count(*) FROM app.final_settlements WHERE lease_id=%s", (lease,)
            ).fetchone() == (0,), level
            with pytest.raises(psycopg.Error) as failure:
                connection.execute(
                    ADJUST, (uuid4(), invoice, line, owed, f"older-{uuid4()}", human)
                )
            refusals[level] = (failure.value.sqlstate, failure.value.diag.message_primary)
            connection.rollback()
    finally:
        for connection in older.values():
            connection.rollback()
            connection.close()
    assert refusals == {level: ("55000", READ_COMMITTED_ONLY) for level in STRICTER}
    after = (
        one(url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice),
        outstanding(url, line),
    )
    assert after == before
    assert attempt(url, ADJUST, (uuid4(), invoice, line, owed, f"now-{uuid4()}", human)) == (
        "P5S01",
        CLOSED,
    )
    assert outstanding(url, line) == owed


def test_every_guarded_write_outside_read_committed_is_refused_before_any_read(
    migrated_database_url: str,
) -> None:
    """A bare insert into each of the eight tables (only an id: every other check would refuse it
    later) is refused at REPEATABLE READ and at SERIALIZABLE with the isolation refusal, so the
    check runs before any read and before every other trigger; the issue of a DRAFT Rent Invoice of
    a signed Lease (the guarded UPDATE) is refused the same way and the Invoice stays a DRAFT."""
    url = migrated_database_url
    with psycopg.connect(url) as connection:
        actor, _, customer, lease = setup_signed_lease(
            connection, start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)
        )
        draft, _ = create_recurring_rent_invoice(
            connection,
            actor_id=actor,
            customer_id=customer,
            lease_id=lease,
            period_start=date(2027, 3, 1),
            issue=False,
        )
    statements: list[tuple[str, str, tuple[object, ...]]] = [
        (table, f"INSERT INTO app.{table}(id) VALUES (%s)", (uuid4(),)) for table in TABLES
    ]
    statements.append(("invoice issue", ISSUE, (actor, actor, draft)))
    refused: dict[tuple[str, str], tuple[object, object]] = {}
    for level in STRICTER:
        for name, sql, parameters in statements:
            with pytest.raises(psycopg.Error) as failure, psycopg.connect(url) as connection:
                connection.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
                connection.execute(sql, parameters)
            refused[(name, level)] = (failure.value.sqlstate, failure.value.diag.message_primary)
    assert refused == {
        (name, level): ("55000", READ_COMMITTED_ONLY)
        for level in STRICTER
        for name, _, _ in statements
    }
    assert one(url, "SELECT status,version FROM app.invoices WHERE id=%s", draft) == ("DRAFT", 1)
    for table in TABLES:
        assert one(
            url,
            f"SELECT count(*) FROM app.{table} WHERE id=ANY(%s)",
            [parameters[0] for name, _, parameters in statements if name == table],
        ) == (0,), table


def test_at_read_committed_a_second_credit_adjustment_waits_and_is_refused(
    migrated_database_url: str,
) -> None:
    """The guard of the REPEATABLE READ Adjustment race of test_invoice_migration.py, at READ
    COMMITTED: two credits of 50,000 on an 80,000 line. The second waits for the first's Invoice
    lock and, once the first commits, reads it and is refused; 30,000 stays owed."""
    url = migrated_database_url
    actor, invoice, line = issued_rent(url, date(2027, 4, 1))
    with psycopg.connect(url) as first:
        first.execute(ADJUST, (uuid4(), invoice, line, 50_000, f"first-{uuid4()}", actor))
        second = waits_then(
            url, first, ADJUST, (uuid4(), invoice, line, 50_000, f"second-{uuid4()}", actor)
        )
    assert second == ("23514", VIOLATES)
    assert one(
        url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice
    ) == (1,)
    assert outstanding(url, line) == 30_000


def test_at_read_committed_an_adjustment_waits_for_a_void_and_is_refused(
    migrated_database_url: str,
) -> None:
    """The guard of the REPEATABLE READ VOID-and-Adjustment race of test_invoice_migration.py, at
    READ COMMITTED: an Adjustment started while the Invoice's VOID is not committed waits for the
    Invoice lock and, once the VOID commits, finds the Invoice VOID and is refused; no Adjustment
    is written."""
    url = migrated_database_url
    actor, invoice, line = issued_rent(url, date(2027, 5, 1))
    with psycopg.connect(url) as voiding:
        voiding.execute("SET CONSTRAINTS ALL DEFERRED")
        voiding.execute(
            "UPDATE app.invoices SET status='VOID',version=3,updated_at=statement_timestamp(),"
            "updated_by=%s WHERE id=%s",
            (actor, invoice),
        )
        voiding.execute(
            "INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,"
            "authorization_reference) VALUES (%s,%s,'Charged by mistake',now(),%s,'invoice.void')",
            (uuid4(), invoice, actor),
        )
        voiding.execute("SET CONSTRAINTS ALL IMMEDIATE")
        adjustment = waits_then(
            url, voiding, ADJUST, (uuid4(), invoice, line, 1_000, f"late-{uuid4()}", actor)
        )
    assert adjustment == ("23514", VIOLATES)
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", invoice) == ("VOID",)
    assert one(
        url, "SELECT count(*) FROM app.invoice_adjustments WHERE invoice_id=%s", invoice
    ) == (0,)


def test_at_read_committed_a_second_charge_reduction_waits_and_is_refused(
    migrated_database_url: str,
) -> None:
    """The guard of the REPEATABLE READ Charge correction race of test_invoice_migration.py, at
    READ COMMITTED (review round 1): of two reductions of 100 from the same 8,000 Charge balance,
    the second waits for the first's Charge lock and, once the first commits, reads it and is
    refused at its commit (its previous balance is stale); one correction, 7,900 left."""
    url = migrated_database_url
    actor, invoice, _ = issued_rent(url, date(2027, 7, 1))
    decision, charge = uuid4(), uuid4()
    assessed = datetime(2028, 1, 1, tzinfo=UTC)
    with psycopg.connect(url) as setup:
        customer = one(url, "SELECT customer_id FROM app.invoices WHERE id=%s", invoice)[0]
        setup.execute("SET CONSTRAINTS ALL DEFERRED")
        setup.execute(
            "INSERT INTO app.late_payment_decisions(id,source_invoice_id,customer_id,"
            "source_due_date,overdue_balance_at_assessment_usd_cents,"
            "default_rate_basis_points,calculated_default_amount_usd_cents,decision_outcome,"
            "approved_amount_usd_cents,assessed_at,finalized_at,finalized_by,reason,"
            "authorization_reference,calculation_trace) VALUES "
            "(%s,%s,%s,'2027-07-05',80000,1000,8000,'CONFIRMED_DEFAULT',8000,%s,%s,%s,"
            "'Overdue Rent','late-payment.decide',%s)",
            (decision, invoice, customer, assessed, assessed, actor, Jsonb({"formula": "10%"})),
        )
        setup.execute(
            "INSERT INTO app.late_payment_charges(id,customer_id,source_invoice_id,"
            "late_payment_decision_id,original_amount_usd_cents,payable_at,created_at,created_by) "
            "VALUES (%s,%s,%s,%s,8000,%s,%s,%s)",
            (charge, customer, invoice, decision, assessed, assessed, actor),
        )
        setup.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with psycopg.connect(url) as first:
        first.execute(REDUCE, (uuid4(), charge, assessed + timedelta(hours=1), actor, uuid4()))
        first.execute("SET CONSTRAINTS ALL IMMEDIATE")
        second = waits_then(
            url, first, REDUCE, (uuid4(), charge, assessed + timedelta(hours=2), actor, uuid4())
        )
    assert second == ("40001", STALE_BALANCE)
    assert one(
        url,
        "SELECT count(*),min(resulting_obligation_usd_cents) "
        "FROM app.late_payment_charge_corrections WHERE late_payment_charge_id=%s",
        charge,
    ) == (1, 7_900)


def test_at_read_committed_an_issue_waits_for_a_termination_and_is_refused(
    migrated_database_url: str,
) -> None:
    """The guard of the REPEATABLE READ issue-and-termination race of test_invoice_migration.py,
    at READ COMMITTED: the issue of next month's DRAFT Rent Invoice, started while the Lease's
    termination is not committed, waits for the Lease's source lock and, once the termination
    commits, is refused at its commit (the Lease is no longer signed for that month); the Invoice
    stays a DRAFT."""
    url = migrated_database_url
    with psycopg.connect(url) as setup:
        day_row = setup.execute("SELECT current_date").fetchone()
        assert day_row is not None and isinstance(day_row[0], date)
        day: date = day_row[0]
        lease_start = day.replace(day=1)
        period_start = (lease_start + timedelta(days=32)).replace(day=1)
        actor, prop, unit, tenant, _ = setup_sources(setup)
        lease = create_draft(
            setup,
            actor_id=actor,
            unit_id=unit,
            primary_tenant_id=tenant,
            start_date=lease_start,
            end_date=date(period_start.year + 1, period_start.month, 1) - timedelta(days=1),
        )
        sign_lease(setup, lease, actor)
        draft, _ = create_recurring_rent_invoice(
            setup,
            actor_id=actor,
            customer_id=tenant,
            lease_id=lease,
            period_start=period_start,
            issue=False,
        )
        version_row = setup.execute(
            "SELECT version FROM app.leases WHERE id=%s", (lease,)
        ).fetchone()
        assert version_row is not None
        lease_version = int(str(version_row[0]))
    with psycopg.connect(url) as terminating:
        terminate_test_lease(
            terminating,
            property_id=prop,
            actor_id=actor,
            lease_id=lease,
            expected_version=lease_version,
            actual_date=day,
            governing="BR-LEASE-021",
            reason="Leaving early",
            basis=TerminationBasis.VOLUNTARY_EARLY,
            request_digest="c" * 64,
        )
        issue = waits_then(url, terminating, ISSUE, (actor, actor, draft))
    assert issue == ("23514", NOT_SIGNED)
    assert one(url, "SELECT status FROM app.leases WHERE id=%s", lease) == ("TERMINATED",)
    assert one(url, "SELECT status FROM app.invoices WHERE id=%s", draft) == ("DRAFT",)


def test_the_closed_change_isolation_is_least_privilege_and_forward_only(
    migrated_database_url: str,
) -> None:
    """The migration changes only the body of the 8e-1 refusal (owner, privileges, definer flag
    and settings kept), adds the isolation check once, before the first per-table branch, adds no
    function, changes no trigger, relation, column, privilege or constraint, and is forward-only."""
    assert migrated_database_url
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision(REVISION)
    assert revision is not None and revision.down_revision == "20270112_169"
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
                ":".join(str(value) for value in row)
                for row in connection.execute(
                    "SELECT t.tgrelid::regclass::text,t.tgname,t.tgfoid::regprocedure::text,"
                    "pg_catalog.pg_get_triggerdef(t.oid) "
                    "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='app' AND NOT t.tgisinternal"
                ).fetchall()
            }
            structure = {
                ":".join(str(value) for value in row)
                for query in STRUCTURE
                for row in connection.execute(query).fetchall()
            }
        return functions, triggers, structure

    with _temporary_migration_database("settlement_closed_change_isolation") as temporary:
        alembic_command.upgrade(config, "20270112_169")
        before_functions, before_triggers, before_structure = catalog(temporary)
        alembic_command.upgrade(config, REVISION)
        after_functions, after_triggers, after_structure = catalog(temporary)
    assert set(after_functions) == set(before_functions)
    assert {
        name for name in before_functions if after_functions[name] != before_functions[name]
    } == {GUARD}
    # Owner, privileges, definer and settings stay; only the body changes.
    assert after_functions[GUARD][1:] == before_functions[GUARD][1:]
    body = str(after_functions[GUARD][0])
    assert str(before_functions[GUARD][0]).count("transaction_isolation") == 0
    assert body.count(READ_COMMITTED_ONLY) == 1
    assert body.index(READ_COMMITTED_ONLY) < body.index("IF TG_TABLE_NAME IN")
    assert (after_triggers, after_structure) == (before_triggers, before_structure)
