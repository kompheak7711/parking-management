# ruff: noqa: E501
"""V1-057 review: the month facts no longer add up in the database.

`app.report_income_facts` and `app.report_payment_facts` added up each Unit, month and kind into
one bigint. The records allow any bigint amount, so a sum of several large amounts could be out
of the bigint range and the whole report failed. The two reads now return one row per part (each
part is one record's own bigint amount) and the application adds them up exactly (Python
integers). The parts, months and kinds are unchanged, so every total is the same.

Same names, arguments and result columns (CREATE OR REPLACE); the grants stay as they are.
"""

from alembic import op

revision = "20270306_225"
down_revision = "20270305_224"
branch_labels = None
depends_on = None

SQL = """
    CREATE OR REPLACE FUNCTION app.report_income_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(unit_id uuid, month date, kind text, amount_usd_cents bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        WITH invoice AS (
            SELECT i.id, i.invoice_date, i.billing_period_start, i.primary_category,
                   lease_unit.id AS unit_id
            FROM app.invoices i
            LEFT JOIN app.leases l ON l.id=i.lease_id
            LEFT JOIN app.units lease_unit ON lease_unit.id=l.unit_id
            WHERE i.status NOT IN ('DRAFT','VOID') AND app.invoice_property_id(i.id)=p_property
        ), line AS (
            SELECT line.id, line.invoice_id, line.category, line.amount_usd_cents, invoice.unit_id,
                   date_trunc('month', CASE
                       WHEN line.category IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES') THEN invoice.invoice_date
                       WHEN line.category='UTILITIES' THEN COALESCE(period.end_date, line.period_end, invoice.invoice_date)
                       ELSE COALESCE(line.period_start, invoice.billing_period_start, invoice.invoice_date)
                   END)::date AS month
            FROM app.invoice_lines line
            JOIN invoice ON invoice.id=line.invoice_id
            LEFT JOIN app.utility_consumption_periods period ON period.id=line.utility_consumption_period_id
        ), part AS (
            -- Rent lines with calculation components count by component.
            SELECT line.unit_id, date_trunc('month', component.period_start)::date AS month,
                   line.category AS kind, component.amount_usd_cents AS amount
            FROM line JOIN app.invoice_line_calculation_components component
                ON component.invoice_line_id=line.id
            WHERE line.category='RENT'
            UNION ALL
            SELECT line.unit_id, line.month, line.category, line.amount_usd_cents
            FROM line
            WHERE line.category<>'RENT' OR NOT EXISTS(SELECT 1 FROM app.invoice_line_calculation_components component
                WHERE component.invoice_line_id=line.id)
            UNION ALL
            SELECT invoice.unit_id,
                   COALESCE(line.month, (SELECT min(first_line.month) FROM line first_line
                       WHERE first_line.invoice_id=invoice.id),
                       date_trunc('month', invoice.invoice_date)::date),
                   COALESCE(line.category, invoice.primary_category),
                   CASE adjustment.adjustment_type WHEN 'DEBIT' THEN adjustment.amount_usd_cents
                       ELSE -adjustment.amount_usd_cents END
            FROM app.invoice_adjustments adjustment
            JOIN invoice ON invoice.id=adjustment.invoice_id
            LEFT JOIN line ON line.id=adjustment.invoice_line_id
            WHERE NOT EXISTS(SELECT 1 FROM app.invoice_adjustment_reversals reversal
                WHERE reversal.invoice_adjustment_id=adjustment.id)
            UNION ALL
            SELECT lease_unit.id, date_trunc('month', timezone(v_timezone, position.created_at))::date,
                   'LATE_PAYMENT_CHARGES', position.adjusted_obligation_usd_cents
            FROM app.late_payment_charge_financial_position position
            JOIN app.invoices source ON source.id=position.source_invoice_id
            LEFT JOIN app.leases l ON l.id=source.lease_id
            LEFT JOIN app.units lease_unit ON lease_unit.id=l.unit_id
            WHERE app.invoice_property_id(source.id)=p_property
            UNION ALL
            SELECT COALESCE(lease.unit_id, reservation.unit_id),
                   date_trunc('month', disposition.effective_date)::date, 'DEPOSIT_KEPT',
                   disposition.amount_usd_cents
            FROM app.deposit_dispositions disposition
            LEFT JOIN app.leases lease ON lease.id=disposition.governing_lease_id
            LEFT JOIN app.reservations reservation ON reservation.id=disposition.governing_reservation_id
            JOIN app.units unit ON unit.id=COALESCE(lease.unit_id, reservation.unit_id)
            WHERE unit.property_id=p_property
              AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                  WHERE reversal.deposit_disposition_id=disposition.id)
        )
        SELECT part.unit_id, part.month, part.kind, part.amount
        FROM part WHERE part.amount<>0
        ORDER BY part.month, part.unit_id, part.kind;
    END $$;

    CREATE OR REPLACE FUNCTION app.report_payment_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(unit_id uuid, month date, kind text, category text, amount_usd_cents bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        WITH every_part AS (
            SELECT part.unit_id, date_trunc('month', payment.payment_date)::date AS month,
                   part.kind, part.category, part.amount_usd_cents AS amount
            FROM app.report_payment_parts(p_property) part
            JOIN app.payments payment ON payment.id=part.payment_id
            UNION ALL
            SELECT lease.unit_id, date_trunc('month', timezone(v_timezone, reversal.occurred_at))::date,
                   'REVERSAL', NULL, -payment.usd_accounting_value_cents
            FROM app.payment_reversals reversal
            JOIN app.payments payment ON payment.id=reversal.payment_id
            LEFT JOIN app.leases lease ON lease.id=payment.lease_id
            WHERE payment.property_id=p_property
        )
        SELECT every_part.unit_id, every_part.month, every_part.kind, every_part.category,
               every_part.amount
        FROM every_part WHERE every_part.amount<>0
        ORDER BY every_part.month, every_part.unit_id, every_part.kind, every_part.category;
    END $$;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    """Refuse rollback; the report reads are part of the forward-only chain."""
    raise RuntimeError("V1-057 month facts parts migration is forward-only")
