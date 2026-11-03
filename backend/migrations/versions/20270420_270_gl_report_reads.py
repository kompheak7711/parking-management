# ruff: noqa: E501
"""General Ledger report reads that need more than the ledger tables (phase 6 step 5).

Owner decisions: DESIGN.md round 22 (Financial statements: Customer debt aging in Not yet due,
1-30, 31-60, 61-90 and Over 90 days, with a total that equals 1100 + 1110; Budget vs actual
marks a line more than the Budget warning percent and more than its smallest amount off) and gap
G1 (round 25: Excel and PDF files). Reads only; nothing here writes.

- ``app.gl_customer_aging(property, actor)`` (``ledger.read``): every unpaid Invoice line and
  Late-payment charge with its Customer, Unit and the day it fell due. It reads the Customer
  balances the Books check uses, which the runtime login cannot read by itself.
- ``app.gl_budget_warning(property, actor, day)`` (``ledger.read``): the two Budget warning
  Business rules (percent off in hundredths, smallest amount off in cents) on a day.

The other reports read the phase 5 report functions (migration ``20270411_261``) and the ledger
tables with the runtime login, after the route has checked ``ledger.read``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270420_270"
down_revision: str | None = "20270419_269"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = (
    "app.gl_customer_aging(uuid, uuid)",
    "app.gl_budget_warning(uuid, uuid, date)",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.gl_customer_aging(p_property uuid, p_actor uuid)
        RETURNS TABLE (customer_id uuid, customer_name text, unit_number text, kind text,
            invoice_id uuid, invoice_number text, late_payment_charge_id uuid, due_date date,
            balance_cents numeric)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.gl_require(p_actor, p_property, 'ledger.read');
            RETURN QUERY
            SELECT source.customer_id, customer.legal_name, unit.unit_number,
                source.balance_kind, invoice.id, invoice.invoice_number,
                source.late_payment_charge_id,
                CASE WHEN source.balance_kind = 'LATE_PAYMENT_CHARGE'
                    THEN timezone(property.timezone_name, charge.payable_at)::date
                    ELSE invoice.due_date END,
                source.balance_usd_cents
            FROM app.customer_ledger_balance_sources AS source
            JOIN app.properties AS property ON property.id = source.property_id
            JOIN app.customers AS customer ON customer.id = source.customer_id
            JOIN app.invoices AS invoice ON invoice.id = source.invoice_id
            LEFT JOIN app.leases AS lease ON lease.id = invoice.lease_id
            LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
            LEFT JOIN app.late_payment_charges AS charge
                ON charge.id = source.late_payment_charge_id
            WHERE source.property_id = p_property
              AND source.balance_kind IN ('INVOICE', 'LATE_PAYMENT_CHARGE')
              AND source.balance_usd_cents > 0
            ORDER BY customer.legal_name, unit.unit_number, invoice.invoice_number;
        END $$;

        CREATE FUNCTION app.gl_budget_warning(p_property uuid, p_actor uuid, p_day date)
        RETURNS TABLE (percent_hundredths bigint, smallest_cents bigint)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.gl_require(p_actor, p_property, 'ledger.read');
            RETURN QUERY
            SELECT app.gl_rule_on('BUDGET_PCT', p_day), app.gl_rule_on('BUDGET_MIN', p_day);
        END $$;
        """
    )
    for function in FUNCTIONS:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC; "
            f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime"
        )


def downgrade() -> None:
    """Reads only, so removing them loses nothing."""
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
