# ruff: noqa: E501
"""V1-057 step 3: the reads of the nine registers and lists (DL-072, DL-079 answer 5).

Bounded definer reads, one row per record, worked out from the records as they are now. The
application filters them by floor and period, adds the summary, the chart data and the footer
totals, and pages the rows. Amounts are integer USD cents; KHR is information only (DL-060,
DL-072 answer 11).

- `app.report_payment_parts(property)`: where each Payment's money went (internal, not granted):
  Paid to Invoices by Invoice line category, Late-payment charges, Deposits, Customer Credit,
  Refunded from the Payment (net of a returned Refund) and the rest, Not allocated, or "received,
  reversed later" for a reversed Payment. `app.report_payment_facts` is rebuilt on it, so the
  Total Payment table and the Payments report use one split.
- `app.report_invoice_register`: each issued Invoice (not DRAFT) with its total after
  Adjustments, the part paid by Payments, the rest settled another way (Customer Credit or a
  Deposit), the amount still owed and its overdue days (DL-072 answer 2): a recurring monthly
  Rent Invoice counts from the 1st of the billed month, every other Invoice from the day after
  its Due Date; an Invoice is overdue only after its Due Date with money still owed.
- `app.report_payment_register`: each Payment with its Receipt number, method, the KHR amount
  and rate as information, its USD value, the day it was reversed, and its parts.
- `app.report_credit_ledger`: each Customer Credit with what was used, refunded, reversed and
  is left.
- `app.report_deposit_register`: each Deposit with what was received, used for debts, kept,
  refunded and is held now, and the state of its Lease or Reservation.
- `app.report_final_settlement_register`: each Final Settlement with the Deposits and Credit
  used, the Deposits kept, the refunds and the balance still due when it closed.
- `app.report_unit_occupancy`: each Unit with today's Lease or active Reservation.
- `app.report_lease_dates`: each Lease that was not left as a draft only, with its dates.
- `app.report_audit_activity(actor, property, allowed, from, to)`: the audit event counts by
  day, person and kind of action for the chosen days, either end open when not given (the events
  themselves are on the History page).

The runtime role may execute the reads only; the parts function stays internal.
"""

from alembic import op

revision = "20270304_223"
down_revision = "20270303_222"
branch_labels = None
depends_on = None

READS = (
    "app.report_payment_facts(uuid,uuid,uuid[])",
    "app.report_invoice_register(uuid,uuid,uuid[])",
    "app.report_payment_register(uuid,uuid,uuid[])",
    "app.report_credit_ledger(uuid,uuid,uuid[])",
    "app.report_deposit_register(uuid,uuid,uuid[])",
    "app.report_final_settlement_register(uuid,uuid,uuid[])",
    "app.report_unit_occupancy(uuid,uuid,uuid[])",
    "app.report_lease_dates(uuid,uuid,uuid[])",
    "app.report_audit_activity(uuid,uuid,uuid[],date,date)",
)
PARTS = "app.report_payment_parts(uuid)"

DEFINER = """LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
    SET "TimeZone"='UTC' AS $$
    #variable_conflict use_column"""

SQL = f"""
    CREATE FUNCTION app.report_payment_parts(p_property uuid)
    RETURNS TABLE(payment_id uuid, unit_id uuid, kind text, category text, amount_usd_cents bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        WITH payment AS (
            SELECT p.id, p.status, p.usd_accounting_value_cents AS amount, l.unit_id AS lease_unit
            FROM app.payments p LEFT JOIN app.leases l ON l.id=p.lease_id
            WHERE p.property_id=p_property
        ), allocation AS (
            SELECT a.* FROM app.payment_allocations a
            JOIN payment ON payment.id=a.payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                WHERE reversal.payment_allocation_id=a.id)
        ), part AS (
            SELECT allocation.payment_id, l.unit_id, 'INVOICES'::text AS kind,
                   COALESCE(detail.category, i.primary_category) AS category,
                   COALESCE(detail.amount, allocation.amount_usd_cents)::bigint AS amount
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
            SELECT allocation.payment_id, l.unit_id, 'LATE_PAYMENT_CHARGES', NULL,
                   allocation.amount_usd_cents
            FROM allocation
            JOIN app.late_payment_charges charge ON charge.id=allocation.late_payment_charge_id
            JOIN app.invoices source ON source.id=charge.source_invoice_id
            LEFT JOIN app.leases l ON l.id=source.lease_id
            WHERE allocation.target_kind='LATE_PAYMENT_CHARGE'
            UNION ALL
            SELECT payment.id, COALESCE(lease.unit_id, reservation.unit_id), 'DEPOSITS',
                   deposit.deposit_type, receipt.amount_usd_cents
            FROM app.deposit_receipts receipt
            JOIN payment ON payment.id=receipt.payment_id
            JOIN app.deposits deposit ON deposit.id=receipt.deposit_id
            LEFT JOIN app.leases lease ON lease.id=deposit.lease_id
            LEFT JOIN app.reservations reservation ON reservation.id=deposit.reservation_id
            WHERE NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals reversal
                WHERE reversal.deposit_receipt_id=receipt.id)
            UNION ALL
            SELECT payment.id, payment.lease_unit, 'CREDIT', NULL, credit.recognized_usd_cents
            FROM app.customer_credits credit JOIN payment ON payment.id=credit.source_payment_id
            WHERE NOT EXISTS(SELECT 1 FROM app.customer_credit_reversals reversal
                WHERE reversal.customer_credit_id=credit.id)
            UNION ALL
            SELECT payment.id, payment.lease_unit, 'REFUNDED', NULL,
                   app.refund_net_value_at(refund.id, 'infinity'::timestamptz)
            FROM app.refunds refund JOIN payment ON payment.id=refund.source_payment_id
        )
        SELECT part.payment_id, part.unit_id, part.kind, part.category, part.amount FROM part
        WHERE part.amount<>0
        UNION ALL
        SELECT payment.id, payment.lease_unit,
               CASE WHEN payment.status='REVERSED' THEN 'REVERSED_LATER' ELSE 'NOT_ALLOCATED' END,
               NULL::text,
               (payment.amount-COALESCE((SELECT sum(part.amount) FROM part WHERE part.payment_id=payment.id),0))::bigint
        FROM payment
        WHERE payment.amount<>COALESCE((SELECT sum(part.amount) FROM part WHERE part.payment_id=payment.id),0)
    $$;

    CREATE OR REPLACE FUNCTION app.report_payment_facts(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(unit_id uuid, month date, kind text, category text, amount_usd_cents bigint)
    {DEFINER}
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
               sum(every_part.amount)::bigint
        FROM every_part GROUP BY every_part.unit_id, every_part.month, every_part.kind, every_part.category
        HAVING sum(every_part.amount)<>0
        ORDER BY every_part.month, every_part.unit_id, every_part.kind, every_part.category;
    END $$;

    CREATE FUNCTION app.report_invoice_register(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(invoice_id uuid, invoice_number text, status text, customer_id uuid,
        customer_name text, lease_id uuid, unit_id uuid, primary_category text,
        rent_billing_kind text, invoice_date date, due_date date, total_usd_cents bigint,
        paid_usd_cents bigint, other_settled_usd_cents bigint, owed_usd_cents bigint,
        overdue_days integer)
    {DEFINER}
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_today date := timezone(v_timezone, statement_timestamp())::date;
    BEGIN
        RETURN QUERY
        SELECT invoice.id, invoice.invoice_number, invoice.status, customer.id, customer.legal_name,
               invoice.lease_id, lease.unit_id, invoice.primary_category, invoice.rent_billing_kind,
               invoice.invoice_date, invoice.due_date, money.total, money.paid,
               money.total-money.paid-money.owed, money.owed,
               CASE WHEN invoice.status IN ('UNPAID','PARTIALLY_PAID') AND money.owed>0
                         AND invoice.due_date<v_today
                    THEN (v_today-COALESCE(app.rent_nonpayment_day_zero(invoice.id), invoice.due_date))::integer
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
        ORDER BY invoice.invoice_date, invoice.invoice_number, invoice.id;
    END $$;

    CREATE FUNCTION app.report_payment_register(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(payment_id uuid, receipt_number text, payment_date date, status text,
        customer_id uuid, customer_name text, unit_id uuid, method_name text,
        received_currency text, received_amount_minor bigint, rate_khr_per_usd bigint,
        amount_usd_cents bigint, reversed_on date, parts jsonb)
    {DEFINER}
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        WITH parts AS (
            SELECT part.payment_id, jsonb_agg(jsonb_build_object('kind', part.kind,
                       'category', part.category, 'unit_id', part.unit_id,
                       'amount_usd_cents', part.amount_usd_cents)
                       ORDER BY part.kind, part.category NULLS LAST, part.unit_id) AS parts
            FROM app.report_payment_parts(p_property) part GROUP BY part.payment_id
        )
        SELECT payment.id, payment.payment_number, payment.payment_date, payment.status,
               customer.id, customer.legal_name,
               COALESCE(lease.unit_id, (SELECT min(part->>'unit_id')::uuid
                   FROM jsonb_array_elements(parts.parts) part
                   HAVING count(DISTINCT part->>'unit_id')=1)),
               payment.payment_method_name_snapshot, payment.received_currency,
               payment.received_amount_minor, rate.system_rate_khr_per_usd,
               payment.usd_accounting_value_cents,
               timezone(v_timezone, reversal.occurred_at)::date,
               COALESCE(parts.parts, '[]'::jsonb)
        FROM app.payments payment
        JOIN app.customers customer ON customer.id=payment.payer_customer_id
        LEFT JOIN app.leases lease ON lease.id=payment.lease_id
        LEFT JOIN app.exchange_rate_records rate ON rate.id=payment.exchange_rate_record_id
        LEFT JOIN app.payment_reversals reversal ON reversal.payment_id=payment.id
        LEFT JOIN parts ON parts.payment_id=payment.id
        WHERE payment.property_id=p_property
        ORDER BY payment.payment_date, payment.payment_number, payment.id;
    END $$;

    CREATE FUNCTION app.report_credit_ledger(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(credit_id uuid, customer_id uuid, customer_name text, unit_id uuid,
        source_payment_id uuid, receipt_number text, recognized_on date,
        recognized_usd_cents bigint, applied_usd_cents bigint, refunded_usd_cents bigint,
        reversed_usd_cents bigint, available_usd_cents bigint)
    {DEFINER}
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        SELECT position.customer_credit_id, customer.id, customer.legal_name, lease.unit_id,
               payment.id, payment.payment_number,
               timezone(v_timezone, credit.recognized_at)::date,
               position.recognized_usd_cents, position.applied_usd_cents::bigint,
               position.refunded_usd_cents::bigint, position.reversed_usd_cents,
               position.available_usd_cents::bigint
        FROM app.customer_credit_financial_position position
        JOIN app.customer_credits credit ON credit.id=position.customer_credit_id
        JOIN app.customers customer ON customer.id=credit.customer_id
        JOIN app.payments payment ON payment.id=credit.source_payment_id
        LEFT JOIN app.leases lease ON lease.id=payment.lease_id
        WHERE position.property_id=p_property
        ORDER BY credit.recognized_at, credit.id;
    END $$;

    CREATE FUNCTION app.report_deposit_register(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(deposit_id uuid, deposit_type text, lease_id uuid, reservation_id uuid,
        unit_id uuid, customer_id uuid, customer_name text, required_usd_cents bigint,
        received_usd_cents bigint, applied_usd_cents bigint, kept_usd_cents bigint,
        refunded_usd_cents bigint, held_usd_cents bigint, record_status text,
        settlement_closed boolean)
    {DEFINER}
    BEGIN
        PERFORM app.report_actor_property(p_actor, p_property, p_allowed);
        RETURN QUERY
        SELECT deposit.id, deposit.deposit_type, deposit.lease_id, deposit.reservation_id,
               unit.id, customer.id, customer.legal_name, deposit.required_usd_cents,
               (SELECT COALESCE(sum(receipt.amount_usd_cents),0) FROM app.deposit_receipts receipt
                   WHERE receipt.deposit_id=deposit.id AND NOT EXISTS(SELECT 1
                       FROM app.deposit_receipt_reversals reversal WHERE reversal.deposit_receipt_id=receipt.id))::bigint,
               (SELECT COALESCE(sum(application.amount_usd_cents),0) FROM app.deposit_applications application
                   WHERE application.deposit_id=deposit.id AND NOT EXISTS(SELECT 1
                       FROM app.deposit_application_reversals reversal WHERE reversal.deposit_application_id=application.id))::bigint,
               (SELECT COALESCE(sum(disposition.amount_usd_cents),0) FROM app.deposit_dispositions disposition
                   WHERE disposition.deposit_id=deposit.id AND NOT EXISTS(SELECT 1
                       FROM app.deposit_disposition_reversals reversal WHERE reversal.deposit_disposition_id=disposition.id))::bigint,
               (SELECT COALESCE(sum(app.refund_net_value_at(refund.id, 'infinity'::timestamptz)),0)
                   FROM app.refunds refund WHERE refund.source_deposit_id=deposit.id)::bigint,
               app.deposit_held_value_at(deposit.id, statement_timestamp()),
               COALESCE(lease.status, reservation.status),
               EXISTS(SELECT 1 FROM app.final_settlements settlement
                   WHERE settlement.lease_id=deposit.lease_id AND settlement.closed_at IS NOT NULL)
        FROM app.deposits deposit
        JOIN app.customers customer ON customer.id=deposit.customer_id
        LEFT JOIN app.leases lease ON lease.id=deposit.lease_id
        LEFT JOIN app.reservations reservation ON reservation.id=deposit.reservation_id
        JOIN app.units unit ON unit.id=COALESCE(lease.unit_id, reservation.unit_id)
        WHERE unit.property_id=p_property
        ORDER BY unit.unit_number, deposit.created_at, deposit.id;
    END $$;

    CREATE FUNCTION app.report_final_settlement_register(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(final_settlement_id uuid, lease_id uuid, unit_id uuid, customer_id uuid,
        customer_name text, started_on date, move_out_date date, closed_on date,
        deposits_applied_usd_cents bigint, credit_applied_usd_cents bigint,
        deposits_kept_usd_cents bigint, refunded_usd_cents bigint, balance_due_usd_cents bigint)
    {DEFINER}
    DECLARE v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
    BEGIN
        RETURN QUERY
        SELECT settlement.id, settlement.lease_id, lease.unit_id, customer.id, customer.legal_name,
               timezone(v_timezone, settlement.started_at)::date, settlement.move_out_date_snapshot,
               timezone(v_timezone, settlement.closed_at)::date,
               (SELECT COALESCE(sum(application.amount_usd_cents),0) FROM app.deposit_applications application
                   WHERE application.final_settlement_id=settlement.id AND NOT EXISTS(SELECT 1
                       FROM app.deposit_application_reversals reversal WHERE reversal.deposit_application_id=application.id))::bigint,
               (SELECT COALESCE(sum(application.amount_usd_cents),0) FROM app.customer_credit_applications application
                   WHERE application.final_settlement_id=settlement.id AND NOT EXISTS(SELECT 1
                       FROM app.customer_credit_application_reversals reversal WHERE reversal.credit_application_id=application.id))::bigint,
               (SELECT COALESCE(sum(disposition.amount_usd_cents),0) FROM app.deposit_dispositions disposition
                   JOIN app.deposits deposit ON deposit.id=disposition.deposit_id
                   WHERE deposit.lease_id=settlement.lease_id AND NOT EXISTS(SELECT 1
                       FROM app.deposit_disposition_reversals reversal WHERE reversal.deposit_disposition_id=disposition.id))::bigint,
               (SELECT COALESCE(sum(app.refund_net_value_at(detail.refund_id, 'infinity'::timestamptz)),0)
                   FROM app.final_settlement_refund_details detail WHERE detail.final_settlement_id=settlement.id)::bigint,
               settlement.closing_balance_due_usd_cents
        FROM app.final_settlements settlement
        JOIN app.leases lease ON lease.id=settlement.lease_id
        JOIN app.customers customer ON customer.id=lease.primary_tenant_id
        WHERE settlement.property_id=p_property
        ORDER BY settlement.started_at, settlement.id;
    END $$;

    CREATE FUNCTION app.report_unit_occupancy(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(unit_id uuid, unit_status text, lease_id uuid, reservation_id uuid,
        customer_id uuid, customer_name text, monthly_rent_usd_cents bigint, until_date date)
    {DEFINER}
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_today date := timezone(v_timezone, statement_timestamp())::date;
    BEGIN
        RETURN QUERY
        SELECT unit.id, unit.status, lease.id, reservation.id,
               COALESCE(lease_customer.id, reservation_customer.id),
               COALESCE(lease_customer.legal_name, reservation_customer.legal_name),
               COALESCE(lease.monthly_rent_usd_cents, reservation.agreed_monthly_rent_usd_cents)::bigint,
               COALESCE(lease.end_date, reservation.effective_expiration_date)
        FROM app.units unit
        LEFT JOIN LATERAL (
            SELECT current.* FROM app.leases current
            WHERE current.unit_id=unit.id AND current.status='SIGNED'
              AND current.start_date<=v_today AND current.end_date>=v_today
            ORDER BY current.start_date DESC LIMIT 1
        ) lease ON true
        LEFT JOIN app.customers lease_customer ON lease_customer.id=lease.primary_tenant_id
        LEFT JOIN LATERAL (
            SELECT active.* FROM app.reservations active
            WHERE active.unit_id=unit.id AND active.status='ACTIVE' AND lease.id IS NULL
            ORDER BY active.reservation_date DESC, active.id LIMIT 1
        ) reservation ON true
        LEFT JOIN app.customers reservation_customer ON reservation_customer.id=reservation.customer_id
        WHERE unit.property_id=p_property
        ORDER BY unit.unit_number, unit.id;
    END $$;

    CREATE FUNCTION app.report_lease_dates(p_actor uuid, p_property uuid, p_allowed uuid[])
    RETURNS TABLE(lease_id uuid, unit_id uuid, customer_id uuid, customer_name text,
        status text, start_date date, end_date date, actual_termination_date date,
        monthly_rent_usd_cents bigint, days_to_end integer, renewal_drafted boolean)
    {DEFINER}
    DECLARE
        v_timezone text := app.report_actor_property(p_actor, p_property, p_allowed);
        v_today date := timezone(v_timezone, statement_timestamp())::date;
    BEGIN
        RETURN QUERY
        SELECT lease.id, unit.id, customer.id, customer.legal_name, lease.status,
               lease.start_date, lease.end_date, lease.actual_termination_date,
               lease.monthly_rent_usd_cents::bigint,
               CASE WHEN lease.status='SIGNED' THEN (lease.end_date-v_today)::integer END,
               EXISTS(SELECT 1 FROM app.leases renewal WHERE renewal.predecessor_lease_id=lease.id
                   AND renewal.status IN ('DRAFTED','SIGNED'))
        FROM app.leases lease
        JOIN app.units unit ON unit.id=lease.unit_id
        JOIN app.customers customer ON customer.id=lease.primary_tenant_id
        WHERE unit.property_id=p_property AND lease.status IN ('SIGNED','TERMINATED')
        ORDER BY COALESCE(lease.actual_termination_date, lease.end_date), unit.unit_number, lease.id;
    END $$;

    CREATE FUNCTION app.report_audit_activity(p_actor uuid, p_property uuid, p_allowed uuid[],
        p_from date, p_to date)
    RETURNS TABLE(day date, actor_id uuid, actor_name text, action_family text, event_count bigint)
    {DEFINER}
    BEGIN
        PERFORM app.report_actor_property(p_actor, p_property, p_allowed);
        IF p_from>p_to THEN
            RAISE EXCEPTION 'Audit activity days are invalid' USING ERRCODE='22023';
        END IF;
        RETURN QUERY
        SELECT event.business_date, event.actor_id,
               COALESCE(account.display_name, 'System'),
               split_part(event.action, '.', 1), count(*)
        FROM app.audit_events event
        LEFT JOIN app.user_accounts account ON account.actor_id=event.actor_id
        WHERE event.property_id=p_property
          AND (p_from IS NULL OR event.business_date>=p_from)
          AND (p_to IS NULL OR event.business_date<=p_to)
        GROUP BY event.business_date, event.actor_id, account.display_name, split_part(event.action, '.', 1)
        ORDER BY event.business_date DESC, 5 DESC, 2;
    END $$;
"""


def upgrade() -> None:
    op.execute(SQL)
    op.execute(f"REVOKE ALL ON FUNCTION {PARTS} FROM PUBLIC")
    for function in READS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback; the reads are part of the forward-only chain."""
    raise RuntimeError("V1-057 report registers migration is forward-only")
