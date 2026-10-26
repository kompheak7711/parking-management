# ruff: noqa: E501
"""The reports and the Home page stay fast with 10 years of history (V1-060 speed test, DL-071 answer 14).

Found by the V1-060 speed test on the release candidate (300 Units, 10 years of made-up history,
33,000 Rent Invoices; ops/V1_060_PLAN.md):

1. `app.report_payment_parts` (behind Total payment and the Payments register) summed every part
   again for each Payment row (a correlated sum over the parts list): 58 s, past the 15 second
   limit, so both reports answered 503. The parts are now summed once per Payment in one grouped
   pass: 0.4 s. Same parts, same amounts.
2. `app.report_invoice_register` called the per-line functions `app.invoice_adjusted_line_obligation`
   and `app.invoice_line_outstanding` and the per-Invoice functions `app.invoice_property_id` and
   `app.rent_nonpayment_day_zero` for every row: 61 s. The same sums are now grouped per Invoice
   line in one pass per money table (the same tables and conditions as those functions at
   'infinity': only what is not reversed counts), and the Property and the Rent day zero are
   written out as those functions read them.

One exact-text replacement each (checked to match once); same signatures, settings and
privileges. No rule or amount changes; a PostgreSQL test compares the old and new answers over
the whole shared test database at the end of the run.
"""

from alembic import op
from sqlalchemy import text

revision = "20270324_243"
down_revision = "20270323_242"
branch_labels = None
depends_on = None

PARTS = "app.report_payment_parts(uuid)"
INVOICE_REGISTER = "app.report_invoice_register(uuid,uuid,uuid[])"
INCOME_FACTS = "app.report_income_facts(uuid,uuid,uuid[])"
HOME = "app.home_page(uuid,uuid,uuid[],text[])"

# app.invoice_property_id, written out: the Lease's Unit's Property, else the one Property there is.
ONLY_PROPERTY = """CROSS JOIN (SELECT CASE WHEN count(*)=1 THEN (array_agg(property.id))[1] END AS id
            FROM app.properties property) AS only_property"""

PARTS_BEFORE = """               (payment.amount-COALESCE((SELECT sum(part.amount) FROM part WHERE part.payment_id=payment.id),0))::bigint
        FROM payment
        WHERE payment.amount<>COALESCE((SELECT sum(part.amount) FROM part WHERE part.payment_id=payment.id),0)
"""

PARTS_AFTER = """               (payment.amount-COALESCE(part_total.amount,0))::bigint
        FROM payment
        -- V1-060 speed test: the parts summed once per Payment, not again for each Payment row.
        LEFT JOIN (SELECT part.payment_id, sum(part.amount) AS amount FROM part
            GROUP BY part.payment_id) AS part_total ON part_total.payment_id=payment.id
        WHERE payment.amount<>COALESCE(part_total.amount,0)
"""

REGISTER_BEFORE = """                    THEN (v_today-COALESCE(app.rent_nonpayment_day_zero(invoice.id), invoice.due_date))::integer
               END
        FROM app.invoices invoice
        JOIN app.customers customer ON customer.id=invoice.customer_id
        LEFT JOIN app.leases lease ON lease.id=invoice.lease_id
        CROSS JOIN LATERAL (
            SELECT (SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS total,
                   (SELECT COALESCE(sum(app.invoice_line_outstanding(line.id)),0)
                        FROM app.invoice_lines line WHERE line.invoice_id=invoice.id)::bigint AS owed,
                   (SELECT COALESCE(sum(allocation.amount_usd_cents),0) FROM app.payment_allocations allocation
                        WHERE allocation.invoice_id=invoice.id AND allocation.target_kind='INVOICE'
                          AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                              WHERE reversal.payment_allocation_id=allocation.id))::bigint AS paid
        ) money
        WHERE invoice.status<>'DRAFT' AND app.invoice_property_id(invoice.id)=p_property
"""

# The sums of app.invoice_adjusted_line_obligation and app.invoice_line_outstanding (that is,
# app.invoice_line_payment_value_at, app.invoice_line_credit_value_at and
# app.invoice_line_deposit_value_at at 'infinity'), grouped per Invoice line and then per Invoice.
LINE_MONEY = """            SELECT line.invoice_id,
                   sum(line.amount_usd_cents+COALESCE(adjusted.amount,0)) AS total,
                   sum(line.amount_usd_cents+COALESCE(adjusted.amount,0)-COALESCE(paid.amount,0)
                       -COALESCE(credited.amount,0)-COALESCE(deposited.amount,0)) AS owed
            FROM app.invoice_lines line
            LEFT JOIN (SELECT adjustment.invoice_line_id,sum(CASE adjustment.adjustment_type
                    WHEN 'DEBIT' THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END) AS amount
                FROM app.invoice_adjustments adjustment
                LEFT JOIN app.invoice_adjustment_reversals reversal ON reversal.invoice_adjustment_id=adjustment.id
                WHERE reversal.id IS NULL
                GROUP BY adjustment.invoice_line_id) AS adjusted ON adjusted.invoice_line_id=line.id
            LEFT JOIN (SELECT detail.invoice_line_id,sum(detail.posted_amount_usd_cents) AS amount
                FROM app.payment_allocation_details detail
                JOIN app.payment_allocations allocation ON allocation.id=detail.payment_allocation_id
                LEFT JOIN app.payment_allocation_reversals reversal ON reversal.payment_allocation_id=allocation.id
                WHERE reversal.id IS NULL
                GROUP BY detail.invoice_line_id) AS paid ON paid.invoice_line_id=line.id
            LEFT JOIN (SELECT detail.invoice_line_id,sum(detail.applied_amount_usd_cents) AS amount
                FROM app.customer_credit_application_details detail
                JOIN app.customer_credit_applications application ON application.id=detail.customer_credit_application_id
                LEFT JOIN app.customer_credit_application_reversals reversal ON reversal.credit_application_id=application.id
                WHERE reversal.id IS NULL
                GROUP BY detail.invoice_line_id) AS credited ON credited.invoice_line_id=line.id
            LEFT JOIN (SELECT application.invoice_line_id,sum(application.amount_usd_cents) AS amount
                FROM app.deposit_applications application
                WHERE NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals reversal
                    WHERE reversal.deposit_application_id=application.id)
                GROUP BY application.invoice_line_id) AS deposited ON deposited.invoice_line_id=line.id
            GROUP BY line.invoice_id
"""

REGISTER_AFTER = (
    """                    -- app.rent_nonpayment_day_zero(invoice.id), written out.
                    THEN (v_today-COALESCE(CASE WHEN invoice.rent_billing_kind='RECURRING'
                        THEN invoice.billing_period_start-1 END, invoice.due_date))::integer
               END
        FROM app.invoices invoice
        JOIN app.customers customer ON customer.id=invoice.customer_id
        LEFT JOIN app.leases lease ON lease.id=invoice.lease_id
        LEFT JOIN app.units unit ON unit.id=lease.unit_id
        """
    + ONLY_PROPERTY
    + """
        -- V1-060 speed test: one grouped pass per money table instead of functions per line.
        LEFT JOIN (
"""
    + LINE_MONEY
    + """        ) AS line_money ON line_money.invoice_id=invoice.id
        LEFT JOIN (SELECT allocation.invoice_id, sum(allocation.amount_usd_cents) AS amount
            FROM app.payment_allocations allocation
            WHERE allocation.target_kind='INVOICE'
              AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                  WHERE reversal.payment_allocation_id=allocation.id)
            GROUP BY allocation.invoice_id) AS allocated ON allocated.invoice_id=invoice.id
        CROSS JOIN LATERAL (
            SELECT COALESCE(line_money.total,0)::bigint AS total,
                   COALESCE(line_money.owed,0)::bigint AS owed,
                   COALESCE(allocated.amount,0)::bigint AS paid
        ) money
        WHERE invoice.status<>'DRAFT' AND COALESCE(unit.property_id, only_property.id)=p_property
"""
)

INCOME_BEFORE = """            LEFT JOIN app.units lease_unit ON lease_unit.id=l.unit_id
            WHERE i.status NOT IN ('DRAFT','VOID') AND app.invoice_property_id(i.id)=p_property
"""

INCOME_AFTER = (
    """            LEFT JOIN app.units lease_unit ON lease_unit.id=l.unit_id
            """
    + ONLY_PROPERTY
    + """
            -- V1-060 speed test: no function call per Invoice.
            WHERE i.status NOT IN ('DRAFT','VOID') AND COALESCE(lease_unit.property_id, only_property.id)=p_property
"""
)

# A CTE used more than once in the aggregates was inlined into each use, so every Invoice's
# balance functions ran once per use (six times for the open Invoices). MATERIALIZED runs them
# once per Invoice; the rows and sums are the same.
HOME_REPLACEMENTS = (
    ("WITH open_invoice AS (", "WITH open_invoice AS MATERIALIZED ("),
    ("WITH billed AS (", "WITH billed AS MATERIALIZED ("),
)

REPLACEMENTS = (
    (PARTS, ((PARTS_BEFORE, PARTS_AFTER),)),
    (INVOICE_REGISTER, ((REGISTER_BEFORE, REGISTER_AFTER),)),
    (INCOME_FACTS, ((INCOME_BEFORE, INCOME_AFTER),)),
    (HOME, HOME_REPLACEMENTS),
)


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
            raise RuntimeError(f"V1-060 report speed contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    for signature, replacements in REPLACEMENTS:
        _patch(signature, replacements)


def downgrade() -> None:
    raise RuntimeError("V1-060 report speed migration is forward-only")
