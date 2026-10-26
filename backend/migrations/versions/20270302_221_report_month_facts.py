# ruff: noqa: E501
"""V1-057 step 2: the month facts of the four "Totals by Unit and month" reports (DL-079 answers 1 to 4).

Three bounded definer reads, one row per Unit, month and kind, worked out from the records as
they are now. The application adds them up into the year-by-month tables. Amounts are integer
USD cents; quantities are exact numbers.

- `app.report_income_facts`: Total Income (DL-079 answer 2). Each Invoice line counts in the
  month it is for: Rent by its calculation components (a first Rent Invoice that covers two
  months is split), Service lines in their period month, Utility lines in the month their
  reading period ends, Damage and Miscellaneous (cleaning) lines in the month the Invoice is
  dated. A DEBIT Adjustment adds and a CREDIT Adjustment takes off, in the month of the line it
  changes (an Invoice-level Adjustment: the Invoice's first month); a reversed Adjustment does
  not count. DRAFT and VOID Invoices do not count. A Late-payment Charge counts in the month it
  is added, at its amount after its reductions and reversals (decided by Claude: a reduction or
  waiver is a minus in the charge's own month, the same way a credit Adjustment is a minus in the
  month of the Invoice it reduces). A kept (forfeited) Deposit, Security or Pet, counts in the
  month it is kept, unless the keeping was reversed. Deposits held are not income.
- `app.report_payment_facts`: Total Payment (DL-079 answer 3) and the Payments report lines
  (DL-072 answer 10, DL-079 answer 7). Every Payment counts on the day the money came in, deposits
  included; a reversal (a returned Payment ends in one) is a minus in the month it happens. The
  money of a month is split as the records are now (decided by Claude under the owner's
  2026-10-23 22:30 rule, the DL-072 open point: a later Allocation change moves money between the
  lines of the month; the month's total never changes): Paid to Invoices by Invoice category
  (from the Allocation details), Late-payment charges, Deposits, Customer Credit, Refunded from
  the Payment, and the rest as Not allocated, or, for a Payment reversed later, as "received,
  reversed later". Each part counts for the Unit of the record it paid; the rest counts for the
  Payment's Lease Unit, or no Unit.
- `app.report_utility_facts`: Total Electricity and Total Water (DL-079 answer 4) and the Utility
  consumption report: each finalized reading period with its quantity, whether it is a
  broken-meter estimate, and the amount of its lines on issued Invoices; the month is the month
  the reading period ends.

The runtime role may execute the three reads only.
"""

from alembic import op

revision = "20270302_221"
down_revision = "20270301_220"
branch_labels = None
depends_on = None

INCOME = "app.report_income_facts(uuid,uuid,uuid[])"
PAYMENT = "app.report_payment_facts(uuid,uuid,uuid[])"
UTILITY = "app.report_utility_facts(uuid,uuid,uuid[])"

SQL = """
    CREATE FUNCTION app.report_income_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
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
        SELECT part.unit_id, part.month, part.kind, sum(part.amount)::bigint
        FROM part GROUP BY part.unit_id, part.month, part.kind
        HAVING sum(part.amount)<>0
        ORDER BY part.month, part.unit_id, part.kind;
    END $$;

    CREATE FUNCTION app.report_payment_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(unit_id uuid, month date, kind text, category text, amount_usd_cents bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        WITH payment AS (
            SELECT p.id, p.status, p.usd_accounting_value_cents AS amount,
                   date_trunc('month', p.payment_date)::date AS month, l.unit_id AS lease_unit
            FROM app.payments p LEFT JOIN app.leases l ON l.id=p.lease_id
            WHERE p.property_id=p_property
        ), allocation AS (
            SELECT a.*, payment.month FROM app.payment_allocations a
            JOIN payment ON payment.id=a.payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                WHERE reversal.payment_allocation_id=a.id)
        ), part AS (
            SELECT allocation.payment_id, l.unit_id, allocation.month, 'INVOICES'::text AS kind,
                   COALESCE(detail.category, i.primary_category) AS category,
                   COALESCE(detail.amount, allocation.amount_usd_cents) AS amount
            FROM allocation
            JOIN app.invoices i ON i.id=allocation.invoice_id
            LEFT JOIN app.leases l ON l.id=i.lease_id
            LEFT JOIN LATERAL (
                SELECT d.invoice_line_category_snapshot AS category, sum(d.posted_amount_usd_cents)::bigint AS amount
                FROM app.payment_allocation_details d
                WHERE d.payment_allocation_id=allocation.id AND d.obligation_kind='INVOICE_LINE'
                GROUP BY d.invoice_line_category_snapshot
            ) detail ON true
            WHERE allocation.target_kind='INVOICE'
            UNION ALL
            SELECT allocation.payment_id, l.unit_id, allocation.month, 'LATE_PAYMENT_CHARGES', NULL,
                   allocation.amount_usd_cents
            FROM allocation
            JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
            JOIN app.invoices source ON source.id=charge.source_invoice_id
            LEFT JOIN app.leases l ON l.id=source.lease_id
            WHERE allocation.target_kind='LATE_PAYMENT_CHARGE'
            UNION ALL
            SELECT payment.id, COALESCE(lease.unit_id, reservation.unit_id), payment.month, 'DEPOSITS',
                   deposit.deposit_type, receipt.amount_usd_cents
            FROM app.deposit_receipts receipt
            JOIN payment ON payment.id=receipt.payment_id
            JOIN app.deposits deposit ON deposit.id=receipt.deposit_id
            LEFT JOIN app.leases lease ON lease.id=deposit.lease_id
            LEFT JOIN app.reservations reservation ON reservation.id=deposit.reservation_id
            WHERE NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                WHERE reversal.deposit_receipt_id=receipt.id)
            UNION ALL
            SELECT payment.id, payment.lease_unit, payment.month, 'CREDIT', NULL, credit.recognized_usd_cents
            FROM app.customer_credits credit JOIN payment ON payment.id=credit.source_payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                WHERE reversal.customer_credit_id=credit.id)
            UNION ALL
            SELECT payment.id, payment.lease_unit, payment.month, 'REFUNDED', NULL, refund.usd_accounting_value_cents
            FROM app.refunds refund JOIN payment ON payment.id=refund.source_payment_id
        ), rest AS (
            SELECT payment.id AS payment_id, payment.lease_unit AS unit_id, payment.month,
                   CASE WHEN payment.status='REVERSED' THEN 'REVERSED_LATER' ELSE 'NOT_ALLOCATED' END AS kind,
                   NULL::text AS category,
                   payment.amount-COALESCE((SELECT sum(part.amount) FROM part WHERE part.payment_id=payment.id),0) AS amount
            FROM payment
        ), reversal AS (
            SELECT payment.id AS payment_id, payment.lease_unit AS unit_id,
                   date_trunc('month', timezone(v_timezone, reversal.occurred_at))::date AS month,
                   'REVERSAL'::text AS kind, NULL::text AS category, -payment.amount AS amount
            FROM app.payment_reversals reversal JOIN payment ON payment.id=reversal.payment_id
        ), every_part AS (
            SELECT part.unit_id, part.month, part.kind, part.category, part.amount FROM part
            UNION ALL SELECT rest.unit_id, rest.month, rest.kind, rest.category, rest.amount FROM rest
            UNION ALL SELECT reversal.unit_id, reversal.month, reversal.kind, reversal.category, reversal.amount FROM reversal
        )
        SELECT every_part.unit_id, every_part.month, every_part.kind, every_part.category,
               sum(every_part.amount)::bigint
        FROM every_part GROUP BY every_part.unit_id, every_part.month, every_part.kind, every_part.category
        HAVING sum(every_part.amount)<>0
        ORDER BY every_part.month, every_part.unit_id, every_part.kind, every_part.category;
    END $$;

    CREATE FUNCTION app.report_utility_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(period_id uuid, unit_id uuid, month date, utility_type text, period_start date,
        period_end date, quantity numeric, is_estimate boolean, amount_usd_cents bigint, billed boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column
    BEGIN
        PERFORM app.report_actor_property(p_actor, p_property, p_allowed);
        RETURN QUERY
        SELECT period.id, period.unit_id, date_trunc('month', period.end_date)::date,
               period.utility_type, period.start_date, period.end_date, period.consumption_quantity,
               period.calculation_kind='BROKEN_METER_ESTIMATE',
               COALESCE(billed.amount, 0)::bigint, billed.amount IS NOT NULL
        FROM app.utility_consumption_periods period
        JOIN app.units unit ON unit.id=period.unit_id
        LEFT JOIN LATERAL (
            SELECT sum(line.amount_usd_cents) AS amount FROM app.invoice_lines line
            JOIN app.invoices invoice ON invoice.id=line.invoice_id
            WHERE line.utility_consumption_period_id=period.id
              AND invoice.status NOT IN ('DRAFT','VOID')
        ) billed ON true
        WHERE unit.property_id=p_property AND period.finalized_at IS NOT NULL
        ORDER BY period.end_date, period.unit_id, period.utility_type, period.id;
    END $$;
"""


def upgrade() -> None:
    op.execute(SQL)
    for function in (INCOME, PAYMENT, UTILITY):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the reads are part of the forward-only chain."""
    raise RuntimeError("V1-057 report month facts migration is forward-only")
