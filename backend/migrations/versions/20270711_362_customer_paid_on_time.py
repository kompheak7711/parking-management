"""UI v81 pilot (owner 08/11/2026): "Paid on time" for one Customer.

The Lease page's Customer card (design v81) shows how many of the Customer's Invoices of the
last 12 months were paid in full by the end of their Due Date. It is the Home card's rule
(migration 20270710_361) for one Customer: only Invoices whose Due Date has passed count, and
nothing about money changes. Read-only; no table changes.

Revision ID: 20270711_362
Revises: 20270710_361
"""

from __future__ import annotations

from alembic import op

revision = "20270711_362"
down_revision = "20270710_361"
branch_labels = None
depends_on = None

PAID_ON_TIME = "app.customer_paid_on_time(uuid,uuid,uuid[],uuid)"

PAID_ON_TIME_SQL = """    CREATE OR REPLACE FUNCTION app.customer_paid_on_time(
        p_actor uuid, p_property uuid, p_allowed uuid[], p_customer uuid)
    RETURNS TABLE(on_time integer, invoice_count integer)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_today date := timezone(v_timezone, statement_timestamp())::date;
    BEGIN
        RETURN QUERY
        WITH due AS (
            SELECT (SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
                    FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS total,
                (SELECT COALESCE(sum(app.invoice_line_payment_value_at(line.id,
                        timezone(v_timezone, (invoice.due_date + 1)::timestamp))),0)
                    FROM app.invoice_lines line
                    WHERE line.invoice_id=invoice.id)::bigint AS paid_by_due
            FROM app.invoices invoice
            WHERE invoice.customer_id=p_customer
              AND invoice.status IN ('UNPAID','PARTIALLY_PAID','PAID')
              AND invoice.due_date < v_today
              AND invoice.due_date >= (v_today - interval '12 months')::date
              AND app.invoice_property_id(invoice.id)=p_property
        )
        SELECT count(*) FILTER (WHERE due.total>0 AND due.paid_by_due>=due.total)::integer,
            count(*) FILTER (WHERE due.total>0)::integer
        FROM due;
    END;
    $$;
"""


def upgrade() -> None:
    op.execute(PAID_ON_TIME_SQL)
    op.execute(f"REVOKE ALL ON FUNCTION {PAID_ON_TIME} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {PAID_ON_TIME} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the read is part of the forward-only chain."""
    raise RuntimeError("UI v81 pilot Customer paid-on-time migration is forward-only")
