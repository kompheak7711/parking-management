# ruff: noqa: E501
"""Two reads stay fast with 10 years of history (V1-060 speed test, DL-071 answer 14).

Found by the V1-060 speed test (300 Units, 10 years of made-up history; ops/V1_060_PLAN.md):

1. The Invoices list sorts by Invoice date and id and keeps the Property's Invoices with a
   function per row; without an index on that order PostgreSQL read and checked every Invoice
   (0.7 s for 33,000). The new index lets it walk the list in order and stop after one page
   (6 ms). Additive only.
2. The Rent nonpayment alerts page called `app.invoice_line_outstanding_at` for every recurring
   Rent line of the Property (about 0.8 ms each: 28 s for 33,300 lines, past the 5 second
   statement limit, so the page answered 503). A first, set-based balance check now keeps only the
   lines with money still owed, written with the same tables and conditions as the four functions
   behind `app.invoice_line_outstanding_at`; the exact function check stays after it, so the page
   can never show a line the function says is paid. A PostgreSQL test compares both filters over
   the whole shared test database at the end of the run. One exact-text replacement (checked to
   match once); same signature, settings and privileges. No rule or amount changes.
"""

from alembic import op
from sqlalchemy import text

revision = "20270219_207"
down_revision = "20270218_206"
branch_labels = None
depends_on = None

ALERT_PAGE = "app.rent_nonpayment_alert_page(uuid,integer,uuid)"

# The same tables and conditions as app.invoice_adjusted_line_obligation_at,
# app.invoice_line_payment_value_at, app.invoice_line_credit_value_at and
# app.invoice_line_deposit_value_at at statement_timestamp().
OWED_FIRST_CHECK = """                    -- V1-060 speed test: a set-based balance first, then the exact function.
                    AND line.amount_usd_cents
                        + COALESCE((SELECT sum(CASE adjustment.adjustment_type WHEN 'DEBIT'
                                THEN adjustment.amount_usd_cents ELSE -adjustment.amount_usd_cents END)
                            FROM app.invoice_adjustments AS adjustment
                            LEFT JOIN app.invoice_adjustment_reversals AS reversal
                                ON reversal.invoice_adjustment_id=adjustment.id
                            WHERE adjustment.invoice_line_id=line.id
                              AND adjustment.occurred_at<=statement_timestamp()
                              AND (reversal.id IS NULL OR reversal.occurred_at>statement_timestamp())),0)
                        - COALESCE((SELECT sum(detail.posted_amount_usd_cents)
                            FROM app.payment_allocation_details AS detail
                            JOIN app.payment_allocations AS allocation
                                ON allocation.id=detail.payment_allocation_id
                            LEFT JOIN app.payment_allocation_reversals AS reversal
                                ON reversal.payment_allocation_id=allocation.id
                            WHERE detail.invoice_line_id=line.id
                              AND allocation.posted_at<=statement_timestamp()
                              AND (reversal.id IS NULL OR reversal.occurred_at>statement_timestamp())),0)
                        - COALESCE((SELECT sum(detail.applied_amount_usd_cents)
                            FROM app.customer_credit_application_details AS detail
                            JOIN app.customer_credit_applications AS application
                                ON application.id=detail.customer_credit_application_id
                            LEFT JOIN app.customer_credit_application_reversals AS reversal
                                ON reversal.credit_application_id=application.id
                            WHERE detail.invoice_line_id=line.id
                              AND application.occurred_at<=statement_timestamp()
                              AND (reversal.id IS NULL OR reversal.occurred_at>statement_timestamp())),0)
                        - COALESCE((SELECT sum(application.amount_usd_cents)
                            FROM app.deposit_applications AS application
                            WHERE application.invoice_line_id=line.id
                              AND application.occurred_at<=statement_timestamp()
                              AND NOT EXISTS(SELECT 1 FROM app.deposit_application_reversals AS reversal
                                  WHERE reversal.deposit_application_id=application.id
                                    AND reversal.occurred_at<=statement_timestamp())),0) > 0
"""

ALERT_PAGE_BEFORE = """                SELECT line.id,app.rent_nonpayment_source_context(line.id,statement_timestamp()) AS context
                FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
                JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
                WHERE u.property_id=p_property AND line.category='RENT' AND line.source_lease_id=l.id
                    AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
                    AND i.rent_billing_kind='RECURRING'
                    AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-app.rent_nonpayment_day_zero(i.id)>=20
                    AND app.invoice_line_outstanding_at(line.id,statement_timestamp())>0
                    AND (p_after IS NULL OR line.id>p_after) ORDER BY line.id LIMIT p_limit+1
"""

ALERT_PAGE_AFTER = (
    """                SELECT owed.id,app.rent_nonpayment_source_context(owed.id,statement_timestamp()) AS context
                FROM (
                SELECT line.id
                FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
                JOIN app.leases l ON l.id=i.lease_id JOIN app.units u ON u.id=l.unit_id
                WHERE u.property_id=p_property AND line.category='RENT' AND line.source_lease_id=l.id
                    AND i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=statement_timestamp()
                    AND i.rent_billing_kind='RECURRING'
                    AND timezone('Asia/Phnom_Penh',statement_timestamp())::date-app.rent_nonpayment_day_zero(i.id)>=20
"""
    + OWED_FIRST_CHECK
    + """                    AND (p_after IS NULL OR line.id>p_after)
                -- OFFSET 0 keeps this list apart, so the exact check below runs on its rows only.
                OFFSET 0
                ) AS owed
                WHERE app.invoice_line_outstanding_at(owed.id,statement_timestamp())>0
                ORDER BY owed.id LIMIT p_limit+1
"""
)

ALERT_PAGE_REPLACEMENTS = ((ALERT_PAGE_BEFORE, ALERT_PAGE_AFTER),)


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
            raise RuntimeError(f"V1-060 speed contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner, settings and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("CREATE INDEX invoices_invoice_date_order_idx ON app.invoices (invoice_date, id)")
    _patch(ALERT_PAGE, ALERT_PAGE_REPLACEMENTS)


def downgrade() -> None:
    raise RuntimeError("V1-060 speed migration is forward-only")
