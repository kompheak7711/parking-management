"""V1-058 R5d: what the late-payment card on the Invoice page shows.

DESIGN.md "Late-payment card": under the Invoice status card, for an Invoice that has a
late-payment charge. The app adds the charge itself at the charge moment (slice 11g-1, DL-076);
the card shows what was unpaid at that moment, the rate and the amount added, every reduction or
waiver (slice 11g-2: the new amount, who, when, the fixed reason and "What happened"), what paid
it (each Receipt, Customer Credit or Deposit) and what is still owed.

`app.invoice_late_charge_card(property, actor, invoice)` returns that card, or NULL when the
Invoice is not of the Property or has no charge. It checks the Property and an active human
actor with `app.payments_read_actor` (no row locks, so a READ ONLY transaction can call it).
The card is part of the Invoice page, so the API asks for `invoices.read` (Staff see it too;
only the Owner or a Manager may reduce or waive, decided by Claude under the owner's 2026-10-23
22:30 rule, as DESIGN.md shows the button with the MANAGER badge).

Additive only: one new read function; no existing table, function or grant changes.
"""

from alembic import op

revision = "20270221_209"
down_revision = "20270220_208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION app.invoice_late_charge_card(
            p_property_id uuid,p_actor_id uuid,p_invoice_id uuid)
        RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM app.payments_read_actor(p_property_id,p_actor_id);
            IF app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RETURN NULL; END IF;
            RETURN (SELECT jsonb_build_object(
                'charge_id',charge.id,
                'invoice_id',charge.source_invoice_id,
                'customer_id',charge.customer_id,
                'payable_at',charge.payable_at,
                -- The charge moment: the amount unpaid was measured then, even when the job
                -- ran later (a missed day is caught up).
                'charged_at',decision.assessed_at,
                'decision_outcome',decision.decision_outcome,
                'calculated_default_usd_cents',decision.calculated_default_amount_usd_cents,
                'added_at',charge.created_at,
                'by_app',charge.created_by IS NULL,
                'added_by',adder.display_name,
                'unpaid_at_charge_usd_cents',decision.overdue_balance_at_assessment_usd_cents,
                'rate_basis_points',decision.default_rate_basis_points,
                'original_usd_cents',charge.original_amount_usd_cents,
                'now_usd_cents',position.adjusted_obligation_usd_cents,
                'still_owed_usd_cents',position.remaining_balance_usd_cents,
                'paid_usd_cents',position.active_applications_usd_cents,
                'changes',COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                            'kind',correction.correction_kind,
                            'previous_usd_cents',correction.previous_obligation_usd_cents,
                            'resulting_usd_cents',correction.resulting_obligation_usd_cents,
                            'at',correction.occurred_at,
                            'by',who.display_name,
                            'reason_code',reduction.reason_code,
                            'what_happened',reduction.what_happened,
                            'reason',correction.reason)
                        ORDER BY correction.occurred_at,correction.id)
                    FROM app.late_payment_charge_corrections correction
                    LEFT JOIN app.user_accounts who ON who.actor_id=correction.actor_id
                    LEFT JOIN app.late_payment_charge_reductions reduction
                        ON reduction.late_payment_charge_correction_id=correction.id
                    WHERE correction.late_payment_charge_id=charge.id),'[]'),
                'paid_by',COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                            'kind',CASE item->>'kind' WHEN 'PAYMENT_ALLOCATION' THEN 'PAYMENT'
                                WHEN 'CREDIT_APPLICATION' THEN 'CREDIT' ELSE 'DEPOSIT' END,
                            'payment_id',item->>'payment_id',
                            'receipt_number',receipt.receipt_number,
                            'amount_usd_cents',(item->>'amount_usd_cents')::bigint,
                            'at',item->>'posted_at')
                        ORDER BY item.ordinality)
                    FROM jsonb_array_elements(
                        app.late_payment_charge_application_summary(charge.id)->'items')
                        WITH ORDINALITY AS item(item,ordinality)
                    LEFT JOIN app.receipts receipt
                        ON receipt.payment_id=(item->>'payment_id')::uuid),'[]'))
            FROM app.late_payment_charges charge
            JOIN app.late_payment_decisions decision
                ON decision.id=charge.late_payment_decision_id
            JOIN app.late_payment_charge_financial_position position
                ON position.late_payment_charge_id=charge.id
            LEFT JOIN app.user_accounts adder ON adder.actor_id=charge.created_by
            WHERE charge.source_invoice_id=p_invoice_id);
        END $$;
        COMMENT ON FUNCTION app.invoice_late_charge_card(uuid,uuid,uuid) IS
            'V1-058 R5d: what the late-payment card on the Invoice page shows; read only.';
        REVOKE ALL ON FUNCTION app.invoice_late_charge_card(uuid,uuid,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.invoice_late_charge_card(uuid,uuid,uuid)
            TO prm_runtime,prm_financial;
        """
    )


def downgrade() -> None:
    raise RuntimeError("The late-payment card read is forward-only; downgrade is not supported")
