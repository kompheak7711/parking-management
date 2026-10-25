# ruff: noqa: E501
"""The excess check waits a moment for PostgreSQL's own cleanup only (V1-060, DL-067 cause, DL-071 answer 13).

The known intermittent `LockNotAvailable` (DL-067) comes from
`app.assert_payment_excess_eligible`: it takes SHARE locks on the twelve obligation tables with
NOWAIT, so it never waits while it holds the Payment source lock. PostgreSQL's automatic cleanup
(autovacuum, also its ANALYZE) holds SHARE UPDATE EXCLUSIVE on a table while it works on it; that
conflicts with SHARE, and a NOWAIT request never waits for the cleanup to step aside. The V1-060
check proved it: with a busier autovacuum, the named tests fail with 55P03 on `app.invoices` or
`app.invoice_lines` in 2 of 3 runs, with nothing else running.

Now, when the NOWAIT request fails and every session that holds a conflicting lock on those
tables is an autovacuum worker (a holder with no user in `pg_stat_activity`; its `backend_type`
is hidden from the function's owner), the function waits for the same locks, for at most 3
seconds. A waiting request makes PostgreSQL cancel the cleanup after `deadlock_timeout` (1 second), so the
wait ends at once after that. When any other session holds a conflicting lock, the function still
refuses at once with the same 55P03, as before. Same locks, same order, same answers; one exact-text
replacement each (checked to match once); same signature, settings and privileges.
"""

from alembic import op
from sqlalchemy import text

revision = "20270221_209"
down_revision = "20270220_208"
branch_labels = None
depends_on = None

EXCESS = "app.assert_payment_excess_eligible(uuid)"

TABLES = (
    "app.invoices",
    "app.invoice_lines",
    "app.invoice_adjustments",
    "app.invoice_adjustment_reversals",
    "app.invoice_void_events",
    "app.late_payment_charges",
    "app.late_payment_charge_corrections",
    "app.late_payment_decisions",
    "app.payment_allocations",
    "app.payment_allocation_reversals",
    "app.customer_credit_applications",
    "app.customer_credit_application_reversals",
)

LOCK_BEFORE = """            LOCK TABLE app.invoices,app.invoice_lines,app.invoice_adjustments,
                app.invoice_adjustment_reversals,app.invoice_void_events,
                app.late_payment_charges,app.late_payment_charge_corrections,
                app.late_payment_decisions,app.payment_allocations,
                app.payment_allocation_reversals,app.customer_credit_applications,
                app.customer_credit_application_reversals IN SHARE MODE NOWAIT;
"""

LOCK_AFTER = (
    """            BEGIN
                LOCK TABLE app.invoices,app.invoice_lines,app.invoice_adjustments,
                    app.invoice_adjustment_reversals,app.invoice_void_events,
                    app.late_payment_charges,app.late_payment_charge_corrections,
                    app.late_payment_decisions,app.payment_allocations,
                    app.payment_allocation_reversals,app.customer_credit_applications,
                    app.customer_credit_application_reversals IN SHARE MODE NOWAIT;
            EXCEPTION WHEN lock_not_available THEN
                -- V1-060 (DL-067 cause): only PostgreSQL's own cleanup may make this wait.
                -- A waiting request makes PostgreSQL cancel the cleanup after deadlock_timeout.
                -- Any other session holding a conflicting lock is still refused at once.
                IF EXISTS(
                    SELECT 1 FROM pg_catalog.pg_locks held
                    JOIN pg_catalog.pg_stat_activity holder ON holder.pid=held.pid
                    WHERE held.granted AND held.pid<>pg_catalog.pg_backend_pid()
                        AND held.database=(SELECT oid FROM pg_catalog.pg_database
                            WHERE datname=pg_catalog.current_database())
                        AND held.relation=ANY(ARRAY["""
    + ",".join(f"'{table}'::regclass" for table in TABLES)
    + """])
                        AND held.mode IN ('RowExclusiveLock','ShareUpdateExclusiveLock',
                            'ShareRowExclusiveLock','ExclusiveLock','AccessExclusiveLock')
                        -- Every session shows its user here; an autovacuum worker has none
                        -- (its backend_type is hidden from this role, its user is not).
                        AND holder.usesysid IS NOT NULL
                ) THEN
                    RAISE;
                END IF;
                v_lock_timeout := pg_catalog.current_setting('lock_timeout');
                PERFORM pg_catalog.set_config('lock_timeout','3s',true);
                LOCK TABLE app.invoices,app.invoice_lines,app.invoice_adjustments,
                    app.invoice_adjustment_reversals,app.invoice_void_events,
                    app.late_payment_charges,app.late_payment_charge_corrections,
                    app.late_payment_decisions,app.payment_allocations,
                    app.payment_allocation_reversals,app.customer_credit_applications,
                    app.customer_credit_application_reversals IN SHARE MODE;
                PERFORM pg_catalog.set_config('lock_timeout',v_lock_timeout,true);
            END;
"""
)

DECLARE_BEFORE = "        DECLARE v_payment app.payments%ROWTYPE;\n"
DECLARE_AFTER = "        DECLARE v_payment app.payments%ROWTYPE; v_lock_timeout text;\n"

EXCESS_REPLACEMENTS = ((DECLARE_BEFORE, DECLARE_AFTER), (LOCK_BEFORE, LOCK_AFTER))


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"V1-060 excess lock contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    _patch(EXCESS, EXCESS_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("V1-060 excess lock migration is forward-only")
