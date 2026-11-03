# ruff: noqa: E501
"""General Ledger automatic posting from the app's money records (phase 6 step 2).

Owner decisions: accrual (01/11/2026 Q3), the automatic posting table of the General Ledger
design page and PRD v2 (PR-GL-020 to PR-GL-031), the phase 6 plan of 03/11/2026 (L3: posting starts
on the ledger's first day, older records are in the Opening balances; L4: a record dated in a
closed month posts on the first day of the first open month, with a note).

One entry per money record, built from the record itself, with a posting key so it posts once:

- Invoice issued: DR 1100 Customer debt; CR the income account of each line (4010 Rent, or 2050
  Rent billed in advance when the Rent month starts after the issue month; 4020 Services; 4030
  Electricity and 4040 Water by the line's Utility Rate; 4060 cleaning, 4070 damage, 4080 other).
- The first day of a Rent month: DR 2050, CR 4010 for what that line still holds in 2050.
- Invoice voided, Invoice adjustment and its reversal: the same accounts, by the day it happened.
- Late-payment charge: DR 1110, CR 4050; a reduction or charge reversal the other way, and a
  reduction reversal back.
- Payment received: DR the Payment Method's cash or bank account (riel cash goes to 1011),
  CR 2210 Money not used yet; a Payment reversal the other way (V1 reverses every use first).
- Allocation: DR 2210, CR 1100 or 1110; Deposit receipt: DR 2210, CR 2100 or 2110; Credit
  recognized: DR 2210, CR 2200; Credit applied: DR 2200, CR 1100 or 1110; Deposit applied:
  DR 2100 or 2110, CR 1100 or 1110; Deposit kept: DR 2100 or 2110, CR 4090; each reversal the
  other way.
- Refund: DR the source (2100, 2110, 2200 or 2210), CR the Refund method's account.

A record the job cannot post (no ledger account for a Payment or Refund method, no open period,
a refund correction, which needs an adjusting entry) is kept in ``app.gl_posting_problems`` and
shown as "Needs check"; it posts by itself once fixed. ``app.gl_set_method_account`` sets the
account of a Payment or Refund method (Owner, ``ledger.accounts.manage``).

The job function ``app.gl_post_app_records`` runs as the money login (``prm_financial``) inside
the scheduled worker. Downgrade removes these objects while no automatic entry exists.
"""

import re

from alembic import op

revision = "20270415_265"
down_revision = "20270414_264"
branch_labels = None
depends_on = None

# Rent sits in 2050 Rent billed in advance while its month starts after the day it is billed.
RENT_ACCOUNT = r"""
CREATE FUNCTION app.gl_rent_account(p_rent_month date, p_on date)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN date_trunc('month', p_rent_month) > date_trunc('month', p_on)
        THEN '2050' ELSE '4010' END
$$;
REVOKE ALL ON FUNCTION app.gl_rent_account(date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.gl_rent_account(date, date) TO prm_financial;
"""

# The candidate entries of the money records, before the ledger checks what is already posted.
EVENTS = r"""
CREATE FUNCTION app.gl_app_record_events(p_property uuid, p_from date, p_until date)
RETURNS TABLE (source_type text, source_id uuid, posting_key text, event_date date,
    event_at timestamptz, entry_kind text, description text, problem text, lines jsonb)
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
WITH zone AS (
    SELECT property.timezone_name AS tz FROM app.properties AS property WHERE property.id = p_property
),
cash_khr AS (
    SELECT account.code FROM app.gl_accounts AS account
    WHERE account.property_id = p_property AND account.cash_kind = 'CASH_KHR' AND account.is_active
    ORDER BY account.code LIMIT 1
),
-- Invoice lines with their customer, Lease and Unit.
line AS (
    SELECT l.id AS line_id, l.invoice_id, l.category, l.amount_usd_cents AS amount, l.period_start,
        i.invoice_number, i.customer_id, i.lease_id, lease.unit_id, i.issued_at,
        i.primary_category, i.billing_period_start,
        CASE l.category
            WHEN 'UTILITIES' THEN CASE rate.utility_type WHEN 'WATER' THEN '4040' ELSE '4030' END
            WHEN 'SERVICE_CHARGES' THEN '4020'
            WHEN 'DAMAGE_CHARGES' THEN '4070'
            WHEN 'MISCELLANEOUS_CHARGES' THEN CASE WHEN cleaning.obligation_id IS NOT NULL
                THEN '4060' ELSE '4080' END
        END AS other_code
    FROM app.invoice_lines AS l
    JOIN app.invoices AS i ON i.id = l.invoice_id
    LEFT JOIN app.leases AS lease ON lease.id = i.lease_id
    LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
    LEFT JOIN app.utility_rates AS rate ON rate.id = l.utility_rate_id
    LEFT JOIN app.unit_cleaning_charges AS cleaning ON cleaning.obligation_id = l.authorized_obligation_id
    WHERE i.issued_at IS NOT NULL
      AND (i.lease_id IS NULL OR unit.property_id = p_property)
),
-- Rent sits in 2050 until the first day of its month.
line_account AS (
    SELECT line.*, date_trunc('month', line.period_start)::date AS rent_month
    FROM line
),
issue AS (
    SELECT l.invoice_id, l.invoice_number, l.customer_id, l.lease_id, l.unit_id,
        timezone(zone.tz, l.issued_at) AS local_at, l.issued_at,
        jsonb_agg(jsonb_build_object('account',
            CASE WHEN l.category = 'RENT'
                THEN app.gl_rent_account(l.rent_month, timezone(zone.tz, l.issued_at)::date)
                ELSE l.other_code END,
            'credit_cents', l.amount, 'memo', l.invoice_number, 'customer_id', l.customer_id,
            'lease_id', l.lease_id, 'unit_id', l.unit_id) ORDER BY l.line_id)
            FILTER (WHERE l.amount > 0) AS credits,
        sum(l.amount) AS total
    FROM line_account AS l CROSS JOIN zone
    GROUP BY l.invoice_id, l.invoice_number, l.customer_id, l.lease_id, l.unit_id, l.issued_at, zone.tz
),
adjustment AS (
    SELECT a.id, a.invoice_id, a.adjustment_type, a.amount_usd_cents AS amount, a.occurred_at,
        i.invoice_number, i.customer_id, i.lease_id, lease.unit_id,
        coalesce(l.category, i.primary_category) AS category,
        coalesce(l.period_start, i.billing_period_start) AS period_start,
        coalesce(lc.other_code,
            CASE i.primary_category WHEN 'SERVICE_CHARGES' THEN '4020' WHEN 'DAMAGE_CHARGES' THEN '4070'
                WHEN 'UTILITIES' THEN '4030' WHEN 'MISCELLANEOUS_CHARGES' THEN '4080' END) AS other_code
    FROM app.invoice_adjustments AS a
    JOIN app.invoices AS i ON i.id = a.invoice_id
    LEFT JOIN app.leases AS lease ON lease.id = i.lease_id
    LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
    LEFT JOIN app.invoice_lines AS l ON l.id = a.invoice_line_id
    LEFT JOIN line AS lc ON lc.line_id = a.invoice_line_id
    WHERE i.lease_id IS NULL OR unit.property_id = p_property
),
-- What a Rent line still holds in 2050 on the first day of its month.
rent_move AS (
    SELECT l.line_id, l.invoice_number, l.customer_id, l.lease_id, l.unit_id, l.rent_month,
        l.amount
        + coalesce((SELECT sum(CASE a.adjustment_type WHEN 'DEBIT' THEN a.amount_usd_cents
                ELSE -a.amount_usd_cents END)
            FROM app.invoice_adjustments AS a CROSS JOIN zone
            WHERE a.invoice_line_id = l.line_id
              AND timezone(zone.tz, a.occurred_at)::date < l.rent_month
              AND NOT EXISTS (SELECT 1 FROM app.invoice_adjustment_reversals AS r
                  WHERE r.invoice_adjustment_id = a.id
                    AND timezone(zone.tz, r.occurred_at)::date < l.rent_month)), 0) AS amount_left
    FROM line_account AS l CROSS JOIN zone
    WHERE l.category = 'RENT'
      AND app.gl_rent_account(l.rent_month, timezone(zone.tz, l.issued_at)::date) = '2050'
      AND NOT EXISTS (SELECT 1 FROM app.invoice_void_events AS v
          WHERE v.invoice_id = l.invoice_id AND timezone(zone.tz, v.occurred_at)::date < l.rent_month)
),
-- A voided Invoice: what each line holds on the void day goes back out of 1100.
void AS (
    SELECT v.id, v.invoice_id, v.occurred_at, l.invoice_number, l.customer_id, l.lease_id, l.unit_id,
        jsonb_agg(jsonb_build_object('account',
            CASE WHEN l.category = 'RENT'
                THEN app.gl_rent_account(l.rent_month, timezone(zone.tz, v.occurred_at)::date)
                ELSE l.other_code END,
            'debit_cents', l.amount + coalesce(adj.net, 0), 'memo', l.invoice_number,
            'customer_id', l.customer_id, 'lease_id', l.lease_id, 'unit_id', l.unit_id)
            ORDER BY l.line_id) FILTER (WHERE l.amount + coalesce(adj.net, 0) > 0) AS debits,
        sum(l.amount + coalesce(adj.net, 0)) AS total
    FROM app.invoice_void_events AS v
    CROSS JOIN zone
    JOIN line_account AS l ON l.invoice_id = v.invoice_id
    LEFT JOIN LATERAL (
        SELECT sum(CASE a.adjustment_type WHEN 'DEBIT' THEN a.amount_usd_cents
                ELSE -a.amount_usd_cents END) AS net
        FROM app.invoice_adjustments AS a
        WHERE a.invoice_line_id = l.line_id AND a.occurred_at <= v.occurred_at
          AND NOT EXISTS (SELECT 1 FROM app.invoice_adjustment_reversals AS r
              WHERE r.invoice_adjustment_id = a.id AND r.occurred_at <= v.occurred_at)
    ) AS adj ON true
    GROUP BY v.id, v.invoice_id, v.occurred_at, l.invoice_number, l.customer_id, l.lease_id,
        l.unit_id, zone.tz
),
charge AS (
    SELECT c.id, c.customer_id, c.original_amount_usd_cents AS amount, c.created_at,
        i.invoice_number, i.lease_id, lease.unit_id
    FROM app.late_payment_charges AS c
    JOIN app.invoices AS i ON i.id = c.source_invoice_id
    LEFT JOIN app.leases AS lease ON lease.id = i.lease_id
    LEFT JOIN app.units AS unit ON unit.id = lease.unit_id
    WHERE i.lease_id IS NULL OR unit.property_id = p_property
),
pay AS (
    SELECT p.*, method_account.code AS method_code, method_account.cash_kind
    FROM app.payments AS p
    CROSS JOIN zone
    LEFT JOIN LATERAL (
        SELECT account.code, account.cash_kind FROM app.gl_method_accounts AS map
        JOIN app.gl_accounts AS account ON account.id = map.account_id
        WHERE map.property_id = p_property AND map.payment_method_id = p.payment_method_id
          AND map.effective_from <= p.payment_date
        ORDER BY map.effective_from DESC LIMIT 1
    ) AS method_account ON true
    WHERE p.property_id = p_property
),
pay_account AS (
    SELECT pay.*, CASE WHEN pay.received_currency = 'KHR' AND pay.cash_kind = 'CASH_USD'
            THEN (SELECT code FROM cash_khr) ELSE pay.method_code END AS cash_code
    FROM pay
),
deposit AS (
    SELECT d.id, d.customer_id, coalesce(d.lease_id, reservation.resulting_lease_id) AS lease_id,
        CASE d.deposit_type WHEN 'PET' THEN '2110' ELSE '2100' END AS code,
        coalesce(lease.unit_id, reservation.unit_id) AS unit_id
    FROM app.deposits AS d
    LEFT JOIN app.leases AS lease ON lease.id = d.lease_id
    LEFT JOIN app.reservations AS reservation ON reservation.id = d.reservation_id
),
refund_method AS (
    SELECT r.id AS refund_id,
        coalesce(draft.refund_method_id, settled.refund_method_id, corrected.refund_method_id)
            AS refund_method_id
    FROM app.refunds AS r
    LEFT JOIN app.refund_draft_details AS draft ON draft.refund_id = r.id
    LEFT JOIN app.final_settlement_refund_details AS settled ON settled.refund_id = r.id
    LEFT JOIN app.settlement_correction_refund_details AS corrected ON corrected.refund_id = r.id
),
refund AS (
    SELECT r.*, rm.refund_method_id, account.code AS method_code, d.code AS deposit_code,
        d.lease_id AS deposit_lease_id, d.unit_id AS deposit_unit_id
    FROM app.refunds AS r
    JOIN refund_method AS rm ON rm.refund_id = r.id
    CROSS JOIN zone
    LEFT JOIN deposit AS d ON d.id = r.source_deposit_id
    LEFT JOIN LATERAL (
        SELECT a.code FROM app.gl_method_accounts AS map
        JOIN app.gl_accounts AS a ON a.id = map.account_id
        WHERE map.property_id = p_property AND map.refund_method_id = rm.refund_method_id
          AND map.effective_from <= timezone(zone.tz, r.processed_at)::date
        ORDER BY map.effective_from DESC LIMIT 1
    ) AS account ON true
),
target AS (
    -- The customer debt account and dimensions of an Invoice or a late-payment charge.
    SELECT 'INVOICE' AS kind, i.id, '1100' AS code, i.invoice_number AS memo, i.customer_id,
        i.lease_id, lease.unit_id
    FROM app.invoices AS i LEFT JOIN app.leases AS lease ON lease.id = i.lease_id
    UNION ALL
    SELECT 'LATE_PAYMENT_CHARGE', c.id, '1110', i.invoice_number, c.customer_id, i.lease_id,
        lease.unit_id
    FROM app.late_payment_charges AS c
    JOIN app.invoices AS i ON i.id = c.source_invoice_id
    LEFT JOIN app.leases AS lease ON lease.id = i.lease_id
),
raw AS (
    -- Invoice issued.
    SELECT 'INVOICE' AS source_type, issue.invoice_id AS source_id,
        'invoice:' || issue.invoice_id || ':issue' AS posting_key, issue.local_at::date AS event_date,
        issue.issued_at AS event_at, 'AUTO' AS entry_kind,
        'Invoice ' || issue.invoice_number || ' issued' AS description, NULL::text AS problem,
        jsonb_build_array(jsonb_build_object('account', '1100', 'debit_cents', issue.total,
            'memo', issue.invoice_number, 'customer_id', issue.customer_id,
            'lease_id', issue.lease_id, 'unit_id', issue.unit_id)) || issue.credits AS lines
    FROM issue WHERE issue.total > 0
    UNION ALL
    -- Rent moves to income on the first day of its month.
    SELECT 'INVOICE_LINE', m.line_id, 'invoice_line:' || m.line_id || ':rent_to_income',
        m.rent_month, timezone(zone.tz, m.rent_month::timestamp), 'RENT_TO_INCOME',
        'Rent of ' || to_char(m.rent_month, 'MM/YYYY') || ' for ' || m.invoice_number, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '2050', 'debit_cents', m.amount_left, 'memo', m.invoice_number,
                'customer_id', m.customer_id, 'lease_id', m.lease_id, 'unit_id', m.unit_id),
            jsonb_build_object('account', '4010', 'credit_cents', m.amount_left, 'memo', m.invoice_number,
                'customer_id', m.customer_id, 'lease_id', m.lease_id, 'unit_id', m.unit_id))
    FROM rent_move AS m CROSS JOIN zone WHERE m.amount_left > 0
    UNION ALL
    -- Invoice voided.
    SELECT 'INVOICE', v.invoice_id, 'invoice:' || v.invoice_id || ':void',
        timezone(zone.tz, v.occurred_at)::date, v.occurred_at, 'AUTO',
        'Invoice ' || v.invoice_number || ' voided', NULL,
        v.debits || jsonb_build_array(jsonb_build_object('account', '1100', 'credit_cents', v.total,
            'memo', v.invoice_number, 'customer_id', v.customer_id, 'lease_id', v.lease_id,
            'unit_id', v.unit_id))
    FROM void AS v CROSS JOIN zone WHERE v.total > 0
    UNION ALL
    -- Invoice adjustment (DEBIT adds to the debt, CREDIT takes off) and its reversal.
    SELECT 'INVOICE_ADJUSTMENT', a.id, 'invoice_adjustment:' || a.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Invoice ' || a.invoice_number || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '1100',
                CASE WHEN side.adds THEN 'debit_cents' ELSE 'credit_cents' END, a.amount,
                'memo', a.invoice_number, 'customer_id', a.customer_id, 'lease_id', a.lease_id,
                'unit_id', a.unit_id),
            jsonb_build_object('account',
                CASE WHEN a.category = 'RENT'
                    THEN app.gl_rent_account(a.period_start, timezone(zone.tz, side.at)::date)
                    ELSE a.other_code END,
                CASE WHEN side.adds THEN 'credit_cents' ELSE 'debit_cents' END, a.amount,
                'memo', a.invoice_number, 'customer_id', a.customer_id, 'lease_id', a.lease_id,
                'unit_id', a.unit_id))
    FROM adjustment AS a
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, a.occurred_at AS at, ' adjusted' AS what,
            a.adjustment_type = 'DEBIT' AS adds
        UNION ALL
        SELECT ':reversal', r.occurred_at, ' adjustment reversed', a.adjustment_type <> 'DEBIT'
        FROM app.invoice_adjustment_reversals AS r WHERE r.invoice_adjustment_id = a.id
    ) AS side
    WHERE a.amount > 0
    UNION ALL
    -- Late-payment charge.
    SELECT 'LATE_PAYMENT_CHARGE', c.id, 'late_charge:' || c.id,
        timezone(zone.tz, c.created_at)::date, c.created_at, 'AUTO',
        'Late-payment charge for ' || c.invoice_number, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '1110', 'debit_cents', c.amount, 'memo', c.invoice_number,
                'customer_id', c.customer_id, 'lease_id', c.lease_id, 'unit_id', c.unit_id),
            jsonb_build_object('account', '4050', 'credit_cents', c.amount, 'memo', c.invoice_number,
                'customer_id', c.customer_id, 'lease_id', c.lease_id, 'unit_id', c.unit_id))
    FROM charge AS c CROSS JOIN zone WHERE c.amount > 0
    UNION ALL
    -- Late-payment charge correction: a reduction or charge reversal lowers it, a reduction
    -- reversal puts it back.
    SELECT 'LATE_PAYMENT_CHARGE_CORRECTION', k.id, 'late_charge_correction:' || k.id,
        timezone(zone.tz, k.occurred_at)::date, k.occurred_at, 'AUTO',
        'Late-payment charge for ' || c.invoice_number || ' corrected', NULL,
        jsonb_build_array(
            jsonb_build_object('account', '4050',
                CASE WHEN k.correction_kind = 'REDUCTION_REVERSAL' THEN 'credit_cents' ELSE 'debit_cents' END,
                k.amount_usd_cents, 'memo', c.invoice_number, 'customer_id', c.customer_id,
                'lease_id', c.lease_id, 'unit_id', c.unit_id),
            jsonb_build_object('account', '1110',
                CASE WHEN k.correction_kind = 'REDUCTION_REVERSAL' THEN 'debit_cents' ELSE 'credit_cents' END,
                k.amount_usd_cents, 'memo', c.invoice_number, 'customer_id', c.customer_id,
                'lease_id', c.lease_id, 'unit_id', c.unit_id))
    FROM app.late_payment_charge_corrections AS k
    JOIN charge AS c ON c.id = k.late_payment_charge_id
    CROSS JOIN zone WHERE k.amount_usd_cents > 0
    UNION ALL
    -- Payment received, and its reversal.
    SELECT 'PAYMENT', p.id, 'payment:' || p.id || side.suffix, side.on_date, side.at, 'AUTO',
        'Payment ' || p.payment_number || side.what,
        CASE WHEN p.cash_code IS NULL THEN
            'No ledger account is set for the Payment Method ' || p.payment_method_name_snapshot END,
        jsonb_build_array(
            jsonb_build_object('account', p.cash_code,
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END,
                p.usd_accounting_value_cents, 'memo', p.payment_number,
                'customer_id', p.payer_customer_id, 'lease_id', p.lease_id,
                'original_currency', p.received_currency,
                'original_amount_minor',
                    CASE WHEN p.received_currency = 'KHR' THEN p.received_amount_minor END,
                'exchange_rate_record_id',
                    CASE WHEN p.received_currency = 'KHR' THEN p.exchange_rate_record_id END),
            jsonb_build_object('account', '2210',
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END,
                p.usd_accounting_value_cents, 'memo', p.payment_number,
                'customer_id', p.payer_customer_id, 'lease_id', p.lease_id))
    FROM pay_account AS p
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, p.payment_date AS on_date,
            timezone(zone.tz, p.payment_date::timestamp) AS at, ' received' AS what,
            false AS reversed
        UNION ALL
        SELECT ':reversal', timezone(zone.tz, r.occurred_at)::date, r.occurred_at, ' reversed', true
        FROM app.payment_reversals AS r WHERE r.payment_id = p.id
    ) AS side
    WHERE p.usd_accounting_value_cents > 0
    UNION ALL
    -- Allocation of a Payment to an Invoice or charge, and its reversal.
    SELECT 'PAYMENT_ALLOCATION', a.id, 'allocation:' || a.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Payment ' || p.payment_number || side.what || t.memo, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '2210',
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, a.amount_usd_cents,
                'memo', p.payment_number, 'customer_id', p.payer_customer_id, 'lease_id', p.lease_id),
            jsonb_build_object('account', t.code,
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, a.amount_usd_cents,
                'memo', t.memo, 'customer_id', t.customer_id, 'lease_id', t.lease_id,
                'unit_id', t.unit_id))
    FROM app.payment_allocations AS a
    JOIN app.payments AS p ON p.id = a.payment_id AND p.property_id = p_property
    JOIN target AS t ON t.kind = a.target_kind AND t.id = coalesce(a.invoice_id, a.late_payment_charge_id)
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, a.posted_at AS at, ' paid ' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', r.occurred_at, ' taken off ', true
        FROM app.payment_allocation_reversals AS r WHERE r.payment_allocation_id = a.id
    ) AS side
    WHERE a.amount_usd_cents > 0
    UNION ALL
    -- Deposit receipt from a Payment, and its reversal.
    SELECT 'DEPOSIT_RECEIPT', r.id, 'deposit_receipt:' || r.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Deposit received from Payment ' || p.payment_number || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '2210',
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, r.amount_usd_cents,
                'memo', p.payment_number, 'customer_id', p.payer_customer_id, 'lease_id', p.lease_id),
            jsonb_build_object('account', d.code,
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, r.amount_usd_cents,
                'memo', p.payment_number, 'customer_id', d.customer_id, 'lease_id', d.lease_id,
                'unit_id', d.unit_id))
    FROM app.deposit_receipts AS r
    JOIN app.payments AS p ON p.id = r.payment_id AND p.property_id = p_property
    JOIN deposit AS d ON d.id = r.deposit_id
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, r.occurred_at AS at, '' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', x.occurred_at, ' (reversed)', true
        FROM app.deposit_receipt_reversals AS x WHERE x.deposit_receipt_id = r.id
    ) AS side
    WHERE r.amount_usd_cents > 0
    UNION ALL
    -- Deposit applied to debt, and its reversal.
    SELECT 'DEPOSIT_APPLICATION', a.id, 'deposit_application:' || a.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Deposit used for ' || t.memo || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', d.code,
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, a.amount_usd_cents,
                'memo', t.memo, 'customer_id', d.customer_id, 'lease_id', d.lease_id, 'unit_id', d.unit_id),
            jsonb_build_object('account', t.code,
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, a.amount_usd_cents,
                'memo', t.memo, 'customer_id', t.customer_id, 'lease_id', t.lease_id,
                'unit_id', t.unit_id))
    FROM app.deposit_applications AS a
    JOIN deposit AS d ON d.id = a.deposit_id
    JOIN app.final_settlements AS s ON s.id = a.final_settlement_id AND s.property_id = p_property
    JOIN target AS t ON t.kind = CASE a.target_kind WHEN 'INVOICE_LINE' THEN 'INVOICE'
            ELSE 'LATE_PAYMENT_CHARGE' END
        AND t.id = coalesce(a.invoice_id, a.late_payment_charge_id)
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, a.occurred_at AS at, '' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', x.occurred_at, ' (reversed)', true
        FROM app.deposit_application_reversals AS x WHERE x.deposit_application_id = a.id
    ) AS side
    WHERE a.amount_usd_cents > 0
    UNION ALL
    -- Deposit kept (forfeiture), and its reversal.
    SELECT 'DEPOSIT_DISPOSITION', k.id, 'deposit_disposition:' || k.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO', 'Deposit kept' || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', d.code,
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, k.amount_usd_cents,
                'customer_id', d.customer_id, 'lease_id', d.lease_id, 'unit_id', d.unit_id),
            jsonb_build_object('account', '4090',
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, k.amount_usd_cents,
                'customer_id', d.customer_id, 'lease_id', d.lease_id, 'unit_id', d.unit_id))
    FROM app.deposit_dispositions AS k
    JOIN deposit AS d ON d.id = k.deposit_id
    JOIN app.customers AS customer ON customer.id = d.customer_id
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, k.occurred_at AS at, '' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', x.occurred_at, ' (reversed)', true
        FROM app.deposit_disposition_reversals AS x WHERE x.deposit_disposition_id = k.id
    ) AS side
    WHERE k.amount_usd_cents > 0
    UNION ALL
    -- Customer Credit recognized from a Payment, and its reversal.
    SELECT 'CUSTOMER_CREDIT', c.id, 'credit:' || c.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Customer Credit from Payment ' || p.payment_number || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '2210',
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, c.recognized_usd_cents,
                'memo', p.payment_number, 'customer_id', c.customer_id, 'lease_id', p.lease_id),
            jsonb_build_object('account', '2200',
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, c.recognized_usd_cents,
                'memo', p.payment_number, 'customer_id', c.customer_id, 'lease_id', p.lease_id))
    FROM app.customer_credits AS c
    JOIN app.payments AS p ON p.id = c.source_payment_id AND p.property_id = p_property
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, c.recognized_at AS at, '' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', x.occurred_at, ' (reversed)', true
        FROM app.customer_credit_reversals AS x WHERE x.customer_credit_id = c.id
    ) AS side
    WHERE c.recognized_usd_cents > 0
    UNION ALL
    -- Customer Credit used for debt, and its reversal.
    SELECT 'CREDIT_APPLICATION', a.id, 'credit_application:' || a.id || side.suffix,
        timezone(zone.tz, side.at)::date, side.at, 'AUTO',
        'Customer Credit used for ' || t.memo || side.what, NULL,
        jsonb_build_array(
            jsonb_build_object('account', '2200',
                CASE WHEN side.reversed THEN 'credit_cents' ELSE 'debit_cents' END, a.amount_usd_cents,
                'memo', t.memo, 'customer_id', c.customer_id, 'lease_id', t.lease_id),
            jsonb_build_object('account', t.code,
                CASE WHEN side.reversed THEN 'debit_cents' ELSE 'credit_cents' END, a.amount_usd_cents,
                'memo', t.memo, 'customer_id', t.customer_id, 'lease_id', t.lease_id,
                'unit_id', t.unit_id))
    FROM app.customer_credit_applications AS a
    JOIN app.customer_credits AS c ON c.id = a.customer_credit_id
    JOIN app.payments AS p ON p.id = c.source_payment_id AND p.property_id = p_property
    JOIN target AS t ON t.kind = a.target_kind AND t.id = coalesce(a.invoice_id, a.late_payment_charge_id)
    CROSS JOIN zone
    CROSS JOIN LATERAL (
        SELECT '' AS suffix, a.occurred_at AS at, '' AS what, false AS reversed
        UNION ALL
        SELECT ':reversal', x.occurred_at, ' (reversed)', true
        FROM app.customer_credit_application_reversals AS x WHERE x.credit_application_id = a.id
    ) AS side
    WHERE a.amount_usd_cents > 0
    UNION ALL
    -- Refund paid from a Deposit, Customer Credit or money not used yet.
    SELECT 'REFUND', r.id, 'refund:' || r.id, timezone(zone.tz, r.processed_at)::date,
        r.processed_at, 'AUTO', 'Refund ' || r.refund_number,
        CASE WHEN r.method_code IS NULL THEN 'No ledger account is set for the Refund method' END,
        jsonb_build_array(
            jsonb_build_object('account', CASE
                    WHEN r.source_deposit_id IS NOT NULL THEN r.deposit_code
                    WHEN r.source_customer_credit_id IS NOT NULL THEN '2200' ELSE '2210' END,
                'debit_cents', r.usd_accounting_value_cents, 'memo', r.refund_number,
                'customer_id', r.recipient_customer_id, 'lease_id', r.deposit_lease_id,
                'unit_id', r.deposit_unit_id),
            jsonb_build_object('account', r.method_code, 'credit_cents', r.usd_accounting_value_cents,
                'memo', r.refund_number, 'customer_id', r.recipient_customer_id))
    FROM refund AS r
    CROSS JOIN zone
    WHERE (r.source_deposit_id IS NOT NULL OR EXISTS (
        SELECT 1 FROM app.payments AS p
        LEFT JOIN app.customer_credits AS c ON c.source_payment_id = p.id
        WHERE p.property_id = p_property
          AND (p.id = r.source_payment_id OR c.id = r.source_customer_credit_id)))
    UNION ALL
    -- A Refund correction changes what a Refund took out; it needs an adjusting entry.
    SELECT 'REFUND_CORRECTION', k.id, 'refund_correction:' || k.id,
        timezone(zone.tz, k.occurred_at)::date, k.occurred_at, 'AUTO',
        'Refund ' || r.refund_number || ' corrected',
        'A Refund correction needs an adjusting entry from the Owner', '[]'::jsonb
    FROM app.refund_corrections AS k
    JOIN refund AS r ON r.id = k.refund_id
    CROSS JOIN zone
)
SELECT raw.source_type, raw.source_id, raw.posting_key, raw.event_date, raw.event_at,
    raw.entry_kind, raw.description, raw.problem, raw.lines
FROM raw
WHERE raw.event_date BETWEEN p_from AND p_until
$$;
"""

POSTER = r"""
CREATE FUNCTION app.gl_post_app_records(p_property uuid, p_actor uuid, p_until date,
    p_limit integer DEFAULT 500)
RETURNS TABLE (posted integer, needs_check integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_from date;
    v_event record;
    v_date date;
    v_period record;
    v_posted integer := 0;
    v_problems integer := 0;
    v_note text;
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 5000 THEN
        RAISE EXCEPTION 'The posting batch is 1 to 5000 records' USING ERRCODE = '22023';
    END IF;
    -- L3: posting starts on the ledger's first day; older records are in the Opening balances.
    SELECT min(period.starts_on) INTO v_from FROM app.gl_periods AS period
    WHERE period.property_id = p_property;
    IF v_from IS NULL THEN
        RETURN QUERY SELECT 0, 0;
        RETURN;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('gl-post-app-records:' || p_property::text, 0));
    FOR v_event IN
        SELECT event.* FROM app.gl_app_record_events(p_property, v_from, p_until) AS event
        WHERE NOT EXISTS (SELECT 1 FROM app.gl_journal_entries AS entry
            WHERE entry.posting_key = event.posting_key)
        -- Records already in "Needs check" go last, so they never hold back new records.
        ORDER BY EXISTS (SELECT 1 FROM app.gl_posting_problems AS known
                WHERE known.posting_key = event.posting_key),
            event.event_at, event.posting_key
        LIMIT p_limit
    LOOP
        IF v_event.problem IS NOT NULL THEN
            INSERT INTO app.gl_posting_problems AS problem (posting_key, property_id, source_type,
                source_id, event_date, problem)
            VALUES (v_event.posting_key, p_property, v_event.source_type, v_event.source_id,
                v_event.event_date, v_event.problem)
            ON CONFLICT (posting_key) DO UPDATE SET problem = EXCLUDED.problem,
                last_seen_at = statement_timestamp();
            v_problems := v_problems + 1;
            CONTINUE;
        END IF;
        -- L4: a record dated in a closed month posts on the first day of the first open month.
        v_date := v_event.event_date;
        v_note := NULL;
        SELECT period.* INTO v_period FROM app.gl_periods AS period
        WHERE period.property_id = p_property AND period.period_no <= 12
          AND v_date BETWEEN period.starts_on AND period.ends_on;
        IF FOUND AND v_period.status = 'CLOSED' THEN
            SELECT period.starts_on INTO v_date FROM app.gl_periods AS period
            WHERE period.property_id = p_property AND period.period_no <= 12
              AND period.status = 'OPEN' AND period.starts_on > v_event.event_date
            ORDER BY period.starts_on LIMIT 1;
            v_note := 'Dated ' || to_char(v_event.event_date, 'DD/MM/YYYY')
                || ' in a closed month; posted in the first open month';
        END IF;
        BEGIN
            IF v_date IS NULL THEN
                RAISE EXCEPTION 'No open ledger month after %', v_event.event_date
                    USING ERRCODE = '55000';
            END IF;
            PERFORM app.gl_post_entry(p_property, v_date, v_event.entry_kind,
                left(v_event.description, 500), v_event.source_type, v_event.source_id,
                v_event.posting_key, v_note, p_actor, NULL, gen_random_uuid(),
                (SELECT jsonb_agg(line) FROM jsonb_array_elements(v_event.lines) AS line
                 WHERE coalesce((line ->> 'debit_cents')::bigint, 0)
                     + coalesce((line ->> 'credit_cents')::bigint, 0) > 0));
            -- The commit-time balance check runs now, so a bad entry is caught here.
            SET CONSTRAINTS app.gl_journal_entries_balanced IMMEDIATE;
            SET CONSTRAINTS app.gl_journal_entries_balanced DEFERRED;
            DELETE FROM app.gl_posting_problems WHERE posting_key = v_event.posting_key;
            v_posted := v_posted + 1;
        EXCEPTION WHEN OTHERS THEN
            INSERT INTO app.gl_posting_problems AS problem (posting_key, property_id, source_type,
                source_id, event_date, problem)
            VALUES (v_event.posting_key, p_property, v_event.source_type, v_event.source_id,
                v_event.event_date, left(SQLERRM, 500))
            ON CONFLICT (posting_key) DO UPDATE SET problem = EXCLUDED.problem,
                last_seen_at = statement_timestamp();
            v_problems := v_problems + 1;
        END;
    END LOOP;
    RETURN QUERY SELECT v_posted, v_problems;
END $$;
"""


def _literal_colons(sql: str) -> str:
    """Keep ``'invoice:...:issue'`` text from reading as a SQLAlchemy bind parameter."""
    return re.sub(r"(?<![:\w\\]):(?=\w)", r"\\:", sql)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.gl_posting_problems (
            posting_key text PRIMARY KEY,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            source_type text NOT NULL,
            source_id uuid NOT NULL,
            event_date date NOT NULL,
            problem text NOT NULL CHECK (btrim(problem) <> ''),
            first_seen_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            last_seen_at timestamptz NOT NULL DEFAULT statement_timestamp()
        );
        CREATE INDEX gl_posting_problems_property_idx
            ON app.gl_posting_problems (property_id, event_date);
        COMMENT ON TABLE app.gl_posting_problems IS
            'Money records the automatic posting could not post yet ("Needs check"); a row goes '
            'when its record posts. Not a financial record.';
        REVOKE ALL ON TABLE app.gl_posting_problems FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.gl_posting_problems TO prm_runtime, prm_financial;
        """
    )
    op.execute(RENT_ACCOUNT)
    op.execute(_literal_colons(EVENTS))
    op.execute(_literal_colons(POSTER))
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.gl_app_record_events(uuid, date, date) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.gl_post_app_records(uuid, uuid, date, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.gl_post_app_records(uuid, uuid, date, integer)
            TO prm_financial;

        -- The Owner sets the ledger account of a Payment or Refund method (from a date).
        CREATE FUNCTION app.gl_set_method_account(p_property uuid, p_payment_method uuid,
            p_refund_method uuid, p_account_code text, p_effective_from date, p_actor uuid,
            p_correlation uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_account app.gl_accounts%ROWTYPE;
            v_id uuid := gen_random_uuid();
        BEGIN
            IF (p_payment_method IS NULL) = (p_refund_method IS NULL) THEN
                RAISE EXCEPTION 'Name one Payment Method or one Refund method'
                    USING ERRCODE = '22023';
            END IF;
            SELECT account.* INTO v_account FROM app.gl_accounts AS account
            WHERE account.property_id = p_property AND account.code = p_account_code;
            IF NOT FOUND OR v_account.cash_kind IS NULL OR NOT v_account.is_active THEN
                RAISE EXCEPTION 'A method goes to an active cash or bank account'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO app.gl_method_accounts (id, property_id, payment_method_id,
                refund_method_id, account_id, effective_from, created_by)
            VALUES (v_id, p_property, p_payment_method, p_refund_method, v_account.id,
                p_effective_from, p_actor);
            PERFORM app.gl_audit(p_property, p_actor, 'ledger.method_account.set',
                'gl_method_account', v_id, 'Ledger account of a payment or refund method',
                p_correlation, jsonb_build_object('payment_method_id', p_payment_method,
                    'refund_method_id', p_refund_method, 'account', p_account_code,
                    'effective_from', p_effective_from));
            RETURN v_id;
        END $$;
        REVOKE ALL ON FUNCTION app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid)
            TO prm_runtime;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.gl_journal_entries
                       WHERE entry_kind IN ('AUTO', 'RENT_TO_INCOME')) THEN
                RAISE EXCEPTION 'Automatic ledger entries exist; it cannot be rolled back'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        DROP FUNCTION app.gl_set_method_account(uuid, uuid, uuid, text, date, uuid, uuid);
        DROP FUNCTION app.gl_post_app_records(uuid, uuid, date, integer);
        DROP FUNCTION app.gl_app_record_events(uuid, date, date);
        DROP FUNCTION app.gl_rent_account(date, date);
        DROP TABLE app.gl_posting_problems;
        """
    )
