# ruff: noqa: E501
"""V1-060 migrations: the faster reads of `20270219_207` give the same answers, the
Billing Run writers of `20270220_208` lock the run row before the attempt row, and the excess
check of `20270221_209` waits only for PostgreSQL's own cleanup.

Runs last in `scripts/database-test.sh`, on the shared test database after every other module
has left its Invoices, adjustments, Payments, credit and deposit applications and their
reversals behind, so each kind of money record is a case.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from test_move_in_migration import migrated_database_url as migrated_database_url

_SPEC = importlib.util.spec_from_file_location(
    "v1_060_speed",
    Path(__file__).parents[1] / "migrations/versions/20270219_207_v1_060_speed.py",
)
assert _SPEC is not None and _SPEC.loader is not None
SPEED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(SPEED)

# The migration's set-based balance, for every Invoice line at one instant.
_BALANCE = SPEED.OWED_FIRST_CHECK.split("AND line.amount_usd_cents", 1)[1].rsplit("> 0", 1)[0]
INLINE_BALANCE = (
    "SELECT line.id, app.invoice_line_outstanding_at(line.id,statement_timestamp()) AS exact, "
    f"line.amount_usd_cents {_BALANCE} AS inline FROM app.invoice_lines AS line"
)

OLD_ALERT_LINES = """
    SELECT line.id
    FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
    JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
    WHERE u.property_id=%s AND line.category='RENT' AND line.source_lease_id=l.id
        AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
        AND i.rent_billing_kind='RECURRING'
        AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-app.rent_nonpayment_day_zero(i.id)>=20
        AND app.invoice_line_outstanding_at(line.id,statement_timestamp())>0
"""


def _alert_lines(connection: psycopg.Connection[tuple[Any, ...]], prop: UUID) -> set[str]:
    seen: set[str] = set()
    after = None
    while True:
        row = connection.execute(
            "SELECT app.rent_nonpayment_alert_page(%s,100,%s)", (prop, after)
        ).fetchone()
        assert row is not None
        page = row[0]
        seen |= {str(item["rent_invoice_line_id"]) for item in page["items"]}
        if page["next_cursor"] is None:
            return seen
        after = page["next_cursor"]


def test_the_set_based_balance_matches_the_exact_function_for_every_invoice_line(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        rows = connection.execute(INLINE_BALANCE).fetchall()
        kinds = connection.execute(
            "SELECT (SELECT count(*) FROM app.invoice_adjustments),"
            "(SELECT count(*) FROM app.payment_allocation_reversals),"
            "(SELECT count(*) FROM app.customer_credit_application_details),"
            "(SELECT count(*) FROM app.deposit_applications)"
        ).fetchone()
    assert rows, "the shared database has Invoice lines by the end of the run"
    assert kinds is not None and all(int(count) > 0 for count in kinds), kinds
    assert [row for row in rows if int(row[1]) != int(row[2])] == []


def test_the_alert_page_lists_exactly_the_lines_of_the_old_filter(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        properties = [
            UUID(str(row[0]))
            for row in connection.execute("SELECT id FROM app.properties").fetchall()
        ]
        for prop in properties:
            old = {str(row[0]) for row in connection.execute(OLD_ALERT_LINES, (prop,)).fetchall()}
            assert _alert_lines(connection, prop) == old


def test_the_invoice_list_order_has_its_index(migrated_database_url: str) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='app' "
            "AND indexname='invoices_invoice_date_order_idx'"
        ).fetchone()
    assert row is not None
    assert str(row[0]).endswith("(invoice_date, id)")


def test_every_billing_run_writer_locks_the_run_before_the_attempt(
    migrated_database_url: str,
) -> None:
    """The flaky deadlock of two executions of one run (V1-060) came from one writer locking the
    attempt first; every writer that locks both now locks the run row first."""
    with psycopg.connect(migrated_database_url) as connection:
        for name in (
            "start_scheduled_billing_run",
            "record_scheduled_rent_item",
            "record_scheduled_utility_item",
            "finish_scheduled_billing_attempt",
        ):
            row = connection.execute(
                "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND p.proname=%s",
                (name,),
            ).fetchone()
            assert row is not None, name
            source = str(row[0])
            run_lock = source.find("FROM app.billing_runs")
            attempt_lock = source.find("FROM app.billing_run_attempts")
            assert -1 < run_lock < attempt_lock, name


def test_a_session_holding_an_obligation_table_is_still_refused_at_once(
    migrated_database_url: str,
) -> None:
    """DL-067 cause (V1-060): the excess check waits only when autovacuum alone holds a
    conflicting lock. A session's lock (here the one the DL-067 test used to stand in for
    autovacuum) is still refused by the NOWAIT request itself, not by the 3 second wait."""
    with (
        psycopg.connect(migrated_database_url) as holder,
        psycopg.connect(migrated_database_url) as caller,
    ):
        holder.execute("LOCK TABLE app.invoice_lines IN SHARE UPDATE EXCLUSIVE MODE")
        row = caller.execute("SELECT id FROM app.payments ORDER BY id LIMIT 1").fetchone()
        assert row is not None
        caller.execute("SET LOCAL lock_timeout='7s'")
        try:
            caller.execute("SELECT app.assert_payment_excess_eligible(%s)", (row[0],))
        except psycopg.errors.LockNotAvailable as refused:
            assert 'could not obtain lock on relation "app.invoice_lines"' in str(refused)
        else:
            raise AssertionError("A session's conflicting lock must refuse the excess check")
        caller.rollback()
        holder.rollback()


def test_the_excess_check_waits_only_for_autovacuum_and_keeps_the_caller_s_lock_timeout(
    migrated_database_url: str,
) -> None:
    """The wait branch cannot be reached on demand (autovacuum runs when PostgreSQL decides), so
    its guard is checked in the function itself; ops/V1_060_PLAN.md records the run with a busier
    autovacuum that reached it (55P03 in most runs before the change, none after)."""
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT prosrc FROM pg_proc WHERE oid='app.assert_payment_excess_eligible(uuid)'::regprocedure"
        ).fetchone()
    assert row is not None
    source = str(row[0])
    nowait = source.find("IN SHARE MODE NOWAIT;")
    handler = source.find("EXCEPTION WHEN lock_not_available THEN")
    guard = source.find("AND holder.usesysid IS NOT NULL")
    refuse = source.find("RAISE;")
    bound = source.find("PERFORM pg_catalog.set_config('lock_timeout','3s',true);")
    wait = source.find("IN SHARE MODE;")
    restore = source.find("PERFORM pg_catalog.set_config('lock_timeout',v_lock_timeout,true);")
    assert -1 < nowait < handler < guard < refuse < bound < wait < restore
    assert source.count("LOCK TABLE") == 2
