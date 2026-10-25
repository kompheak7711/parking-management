"""V1-058 R5c-3a: what the Payments page shows for a period.

The Payments page (DESIGN.md "Summary cards (Payments)") shows eight cards for the payments
received in a period and a list of those payments. Each payment is split by what it paid:

- RENT, UTIL and SVC: Invoice lines of category RENT, UTILITIES and SERVICE_CHARGES, from the
  allocation details that are not reversed (inside a mixed Invoice the details already hold
  Rent first, BR-PAY-036);
- LATE: late-payment charges;
- DEPOSIT: Deposit receipts that are not reversed;
- MOVEOUT: Invoice lines of category DAMAGE_CHARGES and MISCELLANEOUS_CHARGES (move-out cleaning
  and damage, and other one-time charges);
- CREDIT: Customer Credit recognized from the payment and not reversed.

Money refunded straight from a payment is not one of the seven kinds; the totals and each row
carry it as `refunded_usd_cents`, so the seven kinds, the refunded money and what is left add up
to what was received (decided by Claude under the owner's 2026-10-23 22:30 rule). What is left is
`app.payment_available_value`, the value nothing has used yet (UI-068: it is not Credit). The
split is as it stands now, not as it stood at the end of the period. A period is at most two
years, so the read stays quick.

Both functions check the property and an active human actor (`app.payments_read_actor`, the
checks of `app.require_invoice_command_actor` without its row locks), and read under the caller's
Repeatable Read snapshot (the Python reader sets it). The Receipt read needs a Receipt. A reversed payment is listed with its status and counts in no card. Riel payments count
at the dollar value recorded when they were received.

`app.payments_period_summary(property, actor, from, to, row_limit)` returns the totals of every
payment in the period and at most `row_limit` rows, newest first, with `truncated` when more exist.

`app.payment_receipt_lines(property, actor, payment)` returns what the printed Receipt shows for one
payment: who received it, the reference and payer note, and what it paid, one line per Invoice
(a late-payment charge right after its Invoice), Deposit, Customer Credit and refund, then what
is left;
and the last 50 reprints with who made them.

Additive only: three new read functions; no existing table, function or grant changes.
"""

from alembic import op

revision = "20270220_208"
down_revision = "20270219_207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.payments_read_actor(p_property_id uuid,p_actor_id uuid)
        RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            -- The same checks as app.require_invoice_command_actor, without its row locks, so a
            -- READ ONLY transaction can call it.
            IF NOT EXISTS(SELECT 1 FROM app.properties WHERE id=p_property_id)
            THEN RAISE EXCEPTION 'Payments Property was not found' USING ERRCODE='P4501'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                    JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                    WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                        AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Payments read requires an active human actor'
                USING ERRCODE='P4506'; END IF;
        END $$;
        REVOKE ALL ON FUNCTION app.payments_read_actor(uuid,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE FUNCTION app.payments_period_summary(
            p_property_id uuid,p_actor_id uuid,p_from date,p_to date,p_row_limit integer)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF p_property_id IS NULL OR p_from IS NULL OR p_to IS NULL OR p_from>p_to
                OR p_to-p_from>731 OR p_row_limit IS NULL OR p_row_limit NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Payments summary input is invalid' USING ERRCODE='P4902'; END IF;
            PERFORM app.payments_read_actor(p_property_id,p_actor_id);
            RETURN (
            WITH split AS MATERIALIZED (
                SELECT payment.id AS payment_id,payment.payment_date,payment.confirmed_at,
                    payment.status,payment.received_currency,payment.received_amount_minor,
                    payment.payer_customer_id,payment.payment_method_name_snapshot,
                    payment.payment_method_code_snapshot,
                    payment.usd_accounting_value_cents AS usd_cents,
                    COALESCE(lines.rent,0) AS rent,COALESCE(lines.util,0) AS util,
                    COALESCE(lines.svc,0) AS svc,COALESCE(lines.late,0) AS late,
                    COALESCE((SELECT sum(receipt.amount_usd_cents) FROM app.deposit_receipts receipt
                        WHERE receipt.payment_id=payment.id AND NOT EXISTS(
                            SELECT 1 FROM app.deposit_receipt_reversals reversal
                            WHERE reversal.deposit_receipt_id=receipt.id)),0)::bigint AS deposit,
                    COALESCE(lines.moveout,0) AS moveout,
                    app.payment_credit_value_at(payment.id,'infinity'::timestamptz) AS credit,
                    app.payment_refunded_value_at(payment.id,'infinity'::timestamptz) AS refunded,
                    app.payment_available_value(payment.id) AS left_cents
                FROM app.payments payment
                LEFT JOIN LATERAL (
                    SELECT sum(detail.posted_amount_usd_cents) FILTER (
                            WHERE detail.invoice_line_category_snapshot='RENT') AS rent,
                        sum(detail.posted_amount_usd_cents) FILTER (
                            WHERE detail.invoice_line_category_snapshot='UTILITIES') AS util,
                        sum(detail.posted_amount_usd_cents) FILTER (
                            WHERE detail.invoice_line_category_snapshot='SERVICE_CHARGES') AS svc,
                        sum(detail.posted_amount_usd_cents) FILTER (
                            WHERE detail.obligation_kind='LATE_PAYMENT_CHARGE') AS late,
                        sum(detail.posted_amount_usd_cents) FILTER (
                            WHERE detail.invoice_line_category_snapshot IN (
                                'DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')) AS moveout
                    FROM app.payment_allocations allocation
                    JOIN app.payment_allocation_details detail
                        ON detail.payment_allocation_id=allocation.id
                    WHERE allocation.payment_id=payment.id AND NOT EXISTS(
                        SELECT 1 FROM app.payment_allocation_reversals reversal
                        WHERE reversal.payment_allocation_id=allocation.id)) lines ON true
                WHERE payment.property_id=p_property_id
                    AND payment.payment_date BETWEEN p_from AND p_to),
            live AS (SELECT * FROM split WHERE status<>'REVERSED'),
            totals AS (
                SELECT jsonb_build_object(
                    'payments',count(*),
                    'received_usd_cents',COALESCE(sum(usd_cents),0),
                    'left_usd_cents',COALESCE(sum(left_cents),0),
                    'left_payments',count(*) FILTER (WHERE left_cents>0),
                    'refunded_usd_cents',COALESCE(sum(refunded),0),
                    'riel_received_minor',COALESCE(sum(received_amount_minor) FILTER (
                        WHERE received_currency='KHR'),0),
                    'riel_usd_cents',COALESCE(sum(usd_cents) FILTER (WHERE received_currency='KHR'),0),
                    'kinds',jsonb_build_object(
                        'RENT',jsonb_build_object('usd_cents',COALESCE(sum(rent),0),
                            'payments',count(*) FILTER (WHERE rent>0)),
                        'UTIL',jsonb_build_object('usd_cents',COALESCE(sum(util),0),
                            'payments',count(*) FILTER (WHERE util>0)),
                        'SVC',jsonb_build_object('usd_cents',COALESCE(sum(svc),0),
                            'payments',count(*) FILTER (WHERE svc>0)),
                        'LATE',jsonb_build_object('usd_cents',COALESCE(sum(late),0),
                            'payments',count(*) FILTER (WHERE late>0)),
                        'DEPOSIT',jsonb_build_object('usd_cents',COALESCE(sum(deposit),0),
                            'payments',count(*) FILTER (WHERE deposit>0)),
                        'MOVEOUT',jsonb_build_object('usd_cents',COALESCE(sum(moveout),0),
                            'payments',count(*) FILTER (WHERE moveout>0)),
                        'CREDIT',jsonb_build_object('usd_cents',COALESCE(sum(credit),0),
                            'payments',count(*) FILTER (WHERE credit>0)))) AS value
                FROM live),
            shown AS (
                SELECT split.* FROM split
                ORDER BY split.payment_date DESC,split.confirmed_at DESC,split.payment_id DESC
                LIMIT p_row_limit),
            rows AS (
                SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'payment_id',shown.payment_id,
                    'receipt_number',receipt.receipt_number,
                    'payment_date',shown.payment_date,
                    'received_at',COALESCE(evidence.received_at,
                        to_char(shown.confirmed_at AT TIME ZONE 'Asia/Phnom_Penh',
                            'YYYY-MM-DD"T"HH24:MI:SS"+07:00"')),
                    'customer_id',shown.payer_customer_id,
                    'method_name',shown.payment_method_name_snapshot,
                    'method_code',shown.payment_method_code_snapshot,
                    'status',shown.status,
                    'received_currency',shown.received_currency,
                    'received_amount_minor',shown.received_amount_minor,
                    'usd_cents',shown.usd_cents,
                    'left_usd_cents',CASE WHEN shown.status='REVERSED' THEN 0 ELSE shown.left_cents END,
                    'refunded_usd_cents',CASE WHEN shown.status='REVERSED' THEN 0 ELSE shown.refunded END,
                    'kinds',CASE WHEN shown.status='REVERSED' THEN '{}'::jsonb ELSE jsonb_strip_nulls(
                        jsonb_build_object(
                            'RENT',NULLIF(shown.rent,0),'UTIL',NULLIF(shown.util,0),
                            'SVC',NULLIF(shown.svc,0),'LATE',NULLIF(shown.late,0),
                            'DEPOSIT',NULLIF(shown.deposit,0),'MOVEOUT',NULLIF(shown.moveout,0),
                            'CREDIT',NULLIF(shown.credit,0))) END)
                    ORDER BY shown.payment_date DESC,shown.confirmed_at DESC,shown.payment_id DESC),
                    '[]') AS value
                FROM shown
                LEFT JOIN app.receipts receipt ON receipt.payment_id=shown.payment_id
                LEFT JOIN app.payment_receipt_evidence evidence
                    ON evidence.payment_id=shown.payment_id)
            SELECT jsonb_build_object('property_id',p_property_id,'from',p_from,'to',p_to,
                'totals',totals.value,'rows',rows.value,
                'truncated',(SELECT count(*) FROM split)>p_row_limit)
            FROM totals,rows);
        END $$;
        COMMENT ON FUNCTION app.payments_period_summary(uuid,uuid,date,date,integer) IS
            'V1-058 R5c-3a (DESIGN.md Summary cards (Payments)): payments received in a period, split by what they paid; read only.';
        REVOKE ALL ON FUNCTION app.payments_period_summary(uuid,uuid,date,date,integer)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.payments_period_summary(uuid,uuid,date,date,integer)
            TO prm_runtime,prm_financial;
        CREATE FUNCTION app.payment_receipt_lines(p_property_id uuid,p_actor_id uuid,p_payment_id uuid)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM app.payments_read_actor(p_property_id,p_actor_id);
            RETURN (SELECT jsonb_build_object(
                'payment_id',payment.id,
                'receipt_id',receipt.id,
                'receipt_number',receipt.receipt_number,
                'status',payment.status,
                'customer_id',payment.payer_customer_id,
                'payment_date',payment.payment_date,
                'received_at',COALESCE(evidence.received_at,
                    to_char(payment.confirmed_at AT TIME ZONE 'Asia/Phnom_Penh',
                        'YYYY-MM-DD"T"HH24:MI:SS"+07:00"')),
                'received_currency',payment.received_currency,
                'received_amount_minor',payment.received_amount_minor,
                'usd_cents',payment.usd_accounting_value_cents,
                'system_rate_khr_per_usd',rate.system_rate_khr_per_usd::text,
                'method_name',payment.payment_method_name_snapshot,
                'method_code',payment.payment_method_code_snapshot,
                'reference',COALESCE(payment.channel_transaction_reference,
                    evidence.evidence_reference),
                'payer_note',payment.payer_intent_memo,
                'received_by',account.display_name,
                'left_usd_cents',app.payment_available_value(payment.id),
                'reprints',COALESCE((
                    SELECT jsonb_agg(jsonb_build_object('reprinted_at',latest.reprinted_at,
                            'reprinted_by',latest.display_name,'reason',latest.reason)
                        ORDER BY latest.reprinted_at,latest.id)
                    FROM (SELECT reprint.id,reprint.reprinted_at,reprint.reason,who.display_name
                        FROM app.receipt_reprints reprint
                        JOIN app.user_accounts who ON who.actor_id=reprint.reprinted_by
                        WHERE reprint.receipt_id=receipt.id
                        ORDER BY reprint.reprinted_at DESC,reprint.id DESC LIMIT 50) latest),'[]'),
                'reprint_count',(SELECT count(*) FROM app.receipt_reprints reprint
                    WHERE reprint.receipt_id=receipt.id),
                'lines',COALESCE((
                    SELECT jsonb_agg(line.value ORDER BY line.due_date NULLS LAST,
                        line.invoice_number COLLATE "C" NULLS LAST,line.rank,line.id)
                    FROM (
                        SELECT allocation.invoice_id AS id,invoice.due_date,invoice.invoice_number,
                            0 AS rank,jsonb_build_object('kind','INVOICE',
                                'invoice_id',invoice.id,'invoice_number',invoice.invoice_number,
                                'category',invoice.primary_category,'due_date',invoice.due_date,
                                'amount_usd_cents',sum(allocation.amount_usd_cents)) AS value
                        FROM app.payment_allocations allocation
                        JOIN app.invoices invoice ON invoice.id=allocation.invoice_id
                        WHERE allocation.payment_id=payment.id AND allocation.target_kind='INVOICE'
                            AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                                WHERE reversal.payment_allocation_id=allocation.id)
                        GROUP BY allocation.invoice_id,invoice.id
                        UNION ALL
                        SELECT allocation.late_payment_charge_id,invoice.due_date,invoice.invoice_number,
                            1,jsonb_build_object('kind','LATE_PAYMENT_CHARGE',
                                'late_payment_charge_id',allocation.late_payment_charge_id,
                                'invoice_id',invoice.id,'invoice_number',invoice.invoice_number,
                                'category',NULL,'due_date',invoice.due_date,
                                'amount_usd_cents',sum(allocation.amount_usd_cents))
                        FROM app.payment_allocations allocation
                        JOIN app.late_payment_charges charge
                            ON charge.id=allocation.late_payment_charge_id
                        JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                        WHERE allocation.payment_id=payment.id
                            AND allocation.target_kind='LATE_PAYMENT_CHARGE'
                            AND NOT EXISTS(SELECT 1 FROM app.payment_allocation_reversals reversal
                                WHERE reversal.payment_allocation_id=allocation.id)
                        GROUP BY allocation.late_payment_charge_id,invoice.id
                        UNION ALL
                        SELECT deposit_receipt.id,NULL,NULL,2,jsonb_build_object('kind','DEPOSIT',
                                'deposit_type',deposit.deposit_type,
                                'amount_usd_cents',deposit_receipt.amount_usd_cents)
                        FROM app.deposit_receipts deposit_receipt
                        JOIN app.deposits deposit ON deposit.id=deposit_receipt.deposit_id
                        WHERE deposit_receipt.payment_id=payment.id AND NOT EXISTS(
                            SELECT 1 FROM app.deposit_receipt_reversals reversal
                            WHERE reversal.deposit_receipt_id=deposit_receipt.id)
                        UNION ALL
                        SELECT payment.id,NULL,NULL,4,jsonb_build_object('kind','REFUND',
                                'amount_usd_cents',app.payment_refunded_value_at(payment.id,
                                    'infinity'::timestamptz))
                        WHERE app.payment_refunded_value_at(payment.id,'infinity'::timestamptz)>0
                        UNION ALL
                        SELECT credit.id,NULL,NULL,3,jsonb_build_object('kind','CREDIT',
                                'amount_usd_cents',credit.recognized_usd_cents)
                        FROM app.customer_credits credit
                        WHERE credit.source_payment_id=payment.id AND NOT EXISTS(
                            SELECT 1 FROM app.customer_credit_reversals reversal
                            WHERE reversal.customer_credit_id=credit.id)) line),'[]'))
            FROM app.payments payment
            JOIN app.receipts receipt ON receipt.payment_id=payment.id
            LEFT JOIN app.payment_receipt_evidence evidence ON evidence.payment_id=payment.id
            LEFT JOIN app.exchange_rate_records rate ON rate.id=payment.exchange_rate_record_id
            LEFT JOIN app.user_accounts account ON account.actor_id=payment.confirmed_by
            WHERE payment.id=p_payment_id AND payment.property_id=p_property_id);
        END $$;
        COMMENT ON FUNCTION app.payment_receipt_lines(uuid,uuid,uuid) IS
            'V1-058 R5c-3a: what the printed Receipt and the Receipt page show for one payment; read only.';
        REVOKE ALL ON FUNCTION app.payment_receipt_lines(uuid,uuid,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.payment_receipt_lines(uuid,uuid,uuid) TO prm_runtime,prm_financial;
        """
    )


def downgrade() -> None:
    raise RuntimeError("The Payments page reads are forward-only; downgrade is not supported")
