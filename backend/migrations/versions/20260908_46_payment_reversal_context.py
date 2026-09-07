"""Narrow, coherent and paginated Payment reversal context; no write changes."""

from alembic import op

revision = "20260908_46"
down_revision = "20260907_45"
branch_labels = None
depends_on = None

# Graph CTEs carry identities only. Large proposal/audit text is never materialized.
GRAPH = """
WITH allocations AS (
 SELECT id,invoice_id,late_payment_charge_id FROM app.payment_allocations WHERE payment_id=p_payment
), credits AS (
 SELECT id FROM app.customer_credits WHERE source_payment_id=p_payment
), applications AS (
 SELECT a.id,a.customer_credit_id,a.invoice_id,a.late_payment_charge_id
 FROM app.customer_credit_applications a JOIN credits c ON c.id=a.customer_credit_id
), receipts AS (
 SELECT id,deposit_id FROM app.deposit_receipts WHERE payment_id=p_payment
), deposits AS (SELECT DISTINCT deposit_id id FROM receipts),
invoices AS (
 SELECT invoice_id id FROM allocations WHERE invoice_id IS NOT NULL UNION
 SELECT invoice_id FROM applications WHERE invoice_id IS NOT NULL
), charges AS (
 SELECT late_payment_charge_id id FROM allocations WHERE late_payment_charge_id IS NOT NULL UNION
 SELECT late_payment_charge_id FROM applications WHERE late_payment_charge_id IS NOT NULL
), target_guards AS (
 SELECT 'invoice-financial:'||id::text key FROM invoices UNION
 SELECT 'late-charge:'||id::text FROM charges
), active_allocations AS (
 SELECT id FROM allocations a WHERE NOT EXISTS(
  SELECT 1 FROM app.payment_allocation_reversals r WHERE r.payment_allocation_id=a.id)
), active_credits AS (
 SELECT id FROM credits c WHERE NOT EXISTS(
  SELECT 1 FROM app.customer_credit_reversals r WHERE r.customer_credit_id=c.id)
), active_applications AS (
 SELECT a.id FROM applications a JOIN active_credits c ON c.id=a.customer_credit_id
 WHERE NOT EXISTS(SELECT 1 FROM app.customer_credit_application_reversals r
  WHERE r.credit_application_id=a.id)
), active_receipts AS (
 SELECT r.id,r.deposit_id FROM receipts r WHERE NOT EXISTS(
  SELECT 1 FROM app.deposit_receipt_reversals rev WHERE rev.deposit_receipt_id=r.id)
), active_deposits AS (SELECT DISTINCT deposit_id id FROM active_receipts),
allocation_lines AS (
 SELECT d.id FROM app.payment_allocation_details d
 JOIN active_allocations a ON a.id=d.payment_allocation_id
), application_lines AS (
 SELECT d.id FROM app.customer_credit_application_details d
 JOIN active_applications a ON a.id=d.customer_credit_application_id
), dispositions AS (
 SELECT d.id FROM app.deposit_dispositions d JOIN active_deposits s ON s.id=d.deposit_id
 WHERE NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals r
  WHERE r.deposit_disposition_id=d.id)
), refunds AS (
 SELECT r.id FROM app.refunds r WHERE
 (r.source_payment_id=p_payment OR r.source_customer_credit_id IN(SELECT id FROM active_credits)
  OR r.source_deposit_id IN(SELECT id FROM active_deposits))
 AND r.usd_accounting_value_cents<>COALESCE((SELECT sum(c.source_balance_effect_usd_cents)
  FROM app.refund_corrections c WHERE c.refund_id=r.id),0)
)
"""


def event(
    source_kind: str, source: str, target_kind: str, target: str, amount: str, at: str
) -> str:
    return (
        "jsonb_build_object('source_kind',"
        + source_kind
        + ",'source_id',"
        + source
        + ",'target_kind',"
        + target_kind
        + ",'target_id',"
        + target
        + ",'amount_usd_cents',"
        + amount
        + ",'occurred_at',"
        + at
        + ")"
    )


def projection() -> str:
    # Every payload query is evaluated only after the limit+1 identity selection.
    kinds = [
        (
            "impact",
            1,
            "ALLOCATION",
            "active_allocations",
            "SELECT "
            + event(
                "'PAYMENT'",
                "a.payment_id",
                "a.target_kind",
                "COALESCE(a.invoice_id,a.late_payment_charge_id)",
                "a.amount_usd_cents",
                "a.posted_at",
            )
            + " FROM app.payment_allocations a WHERE a.id=s.id",
        ),
        (
            "impact",
            2,
            "ALLOCATION_LINE",
            "allocation_lines",
            "SELECT "
            + event(
                "'ALLOCATION'",
                "d.payment_allocation_id",
                "d.obligation_kind",
                "COALESCE(d.invoice_line_id,d.late_payment_charge_id)",
                "d.posted_amount_usd_cents",
                "a.posted_at",
            )
            + " FROM app.payment_allocation_details d JOIN app.payment_allocations a"
            " ON a.id=d.payment_allocation_id WHERE d.id=s.id",
        ),
        (
            "impact",
            3,
            "CREDIT",
            "active_credits",
            "SELECT "
            + event(
                "'PAYMENT'",
                "c.source_payment_id",
                "'CREDIT'",
                "c.id",
                "c.recognized_usd_cents",
                "c.recognized_at",
            )
            + " FROM app.customer_credits c WHERE c.id=s.id",
        ),
        (
            "impact",
            4,
            "CREDIT_APPLICATION",
            "active_applications",
            "SELECT "
            + event(
                "'CREDIT'",
                "a.customer_credit_id",
                "a.target_kind",
                "COALESCE(a.invoice_id,a.late_payment_charge_id)",
                "a.amount_usd_cents",
                "a.occurred_at",
            )
            + " FROM app.customer_credit_applications a WHERE a.id=s.id",
        ),
        (
            "impact",
            5,
            "CREDIT_APPLICATION_LINE",
            "application_lines",
            "SELECT "
            + event(
                "'CREDIT_APPLICATION'",
                "d.customer_credit_application_id",
                "d.obligation_kind",
                "COALESCE(d.invoice_line_id,d.late_payment_charge_id)",
                "d.applied_amount_usd_cents",
                "a.occurred_at",
            )
            + " FROM app.customer_credit_application_details d"
            " JOIN app.customer_credit_applications a"
            " ON a.id=d.customer_credit_application_id WHERE d.id=s.id",
        ),
        (
            "impact",
            6,
            "DEPOSIT_RECEIPT",
            "active_receipts",
            "SELECT "
            + event(
                "'PAYMENT'",
                "r.payment_id",
                "'DEPOSIT'",
                "r.deposit_id",
                "r.amount_usd_cents",
                "r.occurred_at",
            )
            + " FROM app.deposit_receipts r WHERE r.id=s.id",
        ),
        (
            "impact",
            7,
            "DEPOSIT_DISPOSITION",
            "dispositions",
            "SELECT "
            + event(
                "'DEPOSIT'",
                "d.deposit_id",
                "'DEPOSIT'",
                "d.deposit_id",
                "d.amount_usd_cents",
                "d.occurred_at",
            )
            + " FROM app.deposit_dispositions d WHERE d.id=s.id",
        ),
        (
            "impact",
            8,
            "REFUND",
            "refunds",
            """SELECT jsonb_build_object(
            'source_kind',CASE WHEN r.source_payment_id IS NOT NULL THEN 'PAYMENT'
                WHEN r.source_customer_credit_id IS NOT NULL THEN 'CREDIT' ELSE 'DEPOSIT' END,
            'source_id',COALESCE(r.source_payment_id,r.source_customer_credit_id,
                r.source_deposit_id),
            'amount_usd_cents',r.usd_accounting_value_cents,'occurred_at',r.processed_at,
            'refund_number',r.refund_number,'unreturned_usd_cents',r.usd_accounting_value_cents
                -COALESCE((SELECT sum(c.source_balance_effect_usd_cents) FROM
                app.refund_corrections c
                    WHERE c.refund_id=r.id),0)) FROM app.refunds r WHERE r.id=s.id""",
        ),
        (
            "result",
            1,
            "INVOICE",
            "invoices",
            """SELECT jsonb_build_object(
            'invoice_number',i.invoice_number,'status',i.status,'outstanding_usd_cents',
            CASE WHEN i.status IN('DRAFT','VOID') THEN 0 ELSE
                COALESCE((SELECT sum(app.invoice_line_outstanding(l.id)) FROM app.invoice_lines l
                WHERE l.invoice_id=i.id),0) END) FROM app.invoices i WHERE i.id=s.id""",
        ),
        (
            "result",
            2,
            "LATE_PAYMENT_CHARGE",
            "charges",
            """SELECT jsonb_build_object(
            'source_invoice_id',c.source_invoice_id,'original_usd_cents',
                c.original_amount_usd_cents,
            'reversed',EXISTS(SELECT 1 FROM app.late_payment_charge_corrections x
                WHERE x.late_payment_charge_id=c.id AND x.correction_kind='CHARGE_REVERSAL'),
            'adjusted_obligation_usd_cents',c.original_amount_usd_cents+effects.correction,
            'remaining_balance_usd_cents',c.original_amount_usd_cents+effects.correction
                -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.payment_allocations a
                    WHERE a.late_payment_charge_id=c.id AND NOT EXISTS(
                        SELECT 1 FROM app.payment_allocation_reversals r WHERE
                r.payment_allocation_id=a.id)),0)
                -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.customer_credit_applications a
                    WHERE a.late_payment_charge_id=c.id AND NOT EXISTS(
                        SELECT 1 FROM app.customer_credit_application_reversals r WHERE
                r.credit_application_id=a.id)),0))
            FROM app.late_payment_charges c CROSS JOIN LATERAL(
                SELECT COALESCE(sum(CASE correction_kind WHEN 'REDUCTION_REVERSAL' THEN
                amount_usd_cents
                    ELSE -amount_usd_cents END),0) correction
                FROM app.late_payment_charge_corrections x WHERE x.late_payment_charge_id=c.id
            ) effects WHERE c.id=s.id""",
        ),
        (
            "result",
            3,
            "CREDIT",
            "credits",
            """SELECT jsonb_build_object(
            'recognized_usd_cents',p.recognized_usd_cents,'applied_usd_cents',p.applied_usd_cents,
            'refunded_usd_cents',p.refunded_usd_cents,'reversed_usd_cents',p.reversed_usd_cents,
            'available_usd_cents',p.available_usd_cents)
            FROM app.customer_credit_financial_position p WHERE p.customer_credit_id=s.id""",
        ),
        (
            "result",
            4,
            "DEPOSIT",
            "deposits",
            """SELECT jsonb_build_object(
            'deposit_type',d.deposit_type,'held_usd_cents',app.deposit_held_value_at(d.id,
                'infinity'),
            'received_usd_cents',COALESCE((SELECT sum(r.amount_usd_cents) FROM
                app.deposit_receipts r
                WHERE r.deposit_id=d.id AND NOT EXISTS(SELECT 1 FROM app.deposit_receipt_reversals x
                    WHERE x.deposit_receipt_id=r.id)),0),
            'disposed_usd_cents',COALESCE((SELECT sum(x.amount_usd_cents) FROM
                app.deposit_dispositions x
                WHERE x.deposit_id=d.id AND NOT EXISTS(SELECT 1 FROM
                app.deposit_disposition_reversals r
                    WHERE r.deposit_disposition_id=x.id)),0),
            'refunded_usd_cents',COALESCE((SELECT sum(r.usd_accounting_value_cents-COALESCE(
                (SELECT sum(x.source_balance_effect_usd_cents) FROM app.refund_corrections x
                WHERE x.refund_id=r.id),0))
                FROM app.refunds r WHERE r.source_deposit_id=d.id),0)) FROM app.deposits d
                WHERE d.id=s.id""",
        ),
    ]
    keys = "\nUNION ALL\n".join(
        f"SELECT {ordinal} ordinal,'{kind}'::text kind,id FROM {table} WHERE p_view='{view}'"
        for view, ordinal, kind, table, _ in kinds
    )
    payload = (
        "CASE "
        + "\n".join(
            f"WHEN p_view='{view}' AND s.ordinal={ordinal} THEN ({sql})"
            for view, ordinal, _, _, sql in kinds
        )
        + " END"
    )
    return (
        GRAPH
        + f""",
    entries AS ({keys}), selected AS MATERIALIZED (
        SELECT ordinal,kind,id FROM entries
        WHERE p_after_id IS NULL OR (ordinal,id)>(p_after_kind,p_after_id)
        ORDER BY ordinal,id LIMIT p_limit+1
    ) SELECT jsonb_build_object(
        'revision_evidence',jsonb_build_object('property',p_property,'payment',p_payment,'view',
                p_view,
            'payment_status',(SELECT status FROM app.payments WHERE id=p_payment),
            'payment_revision',COALESCE((SELECT revision FROM app.payment_serialization_guards
                WHERE payment_id=p_payment),0),
            'deposit_count',(SELECT count(*) FROM deposits),
            'deposit_revision',COALESCE((SELECT sum(g.revision) FROM deposits d
                JOIN app.deposit_serialization_guards g ON g.deposit_id=d.id),0),
            'target_count',CASE WHEN p_view='result' THEN (SELECT count(*) FROM target_guards)
                ELSE 0 END,
            'target_revision',CASE WHEN p_view='result' THEN COALESCE((SELECT sum(g.revision)
                FROM target_guards t JOIN app.invoice_serialization_guards g ON
                g.guard_key=t.key),0) ELSE 0 END),
        'unsupported_application',EXISTS(SELECT 1 FROM deposits d WHERE
                (p_view='result' OR d.id IN(SELECT id FROM active_deposits))
                AND app.deposit_has_active_application(d.id)),
        'anchor_found',p_after_id IS NULL OR EXISTS(SELECT 1 FROM entries WHERE
                ordinal=p_after_kind AND id=p_after_id),
        'items',COALESCE((SELECT jsonb_agg(jsonb_build_object('ordinal',s.ordinal,'kind',s.kind,
                'id',s.id,
            'data',{payload}) ORDER BY s.ordinal,s.id) FROM selected s),'[]'::jsonb))
    """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.payment_reversal_context_page(
            p_property uuid,p_payment uuid,p_actor uuid,p_view text,p_limit integer,
            p_after_kind integer,p_after_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.credit_refund_http_scope('payment',p_payment,p_actor,ARRAY[p_property]);
            IF p_view IS NULL OR p_view NOT IN('impact','result') OR p_limit IS NULL OR p_limit
                NOT BETWEEN 1 AND 100
                OR (p_after_kind IS NULL)<>(p_after_id IS NULL)
                OR p_after_kind NOT BETWEEN 1 AND (CASE WHEN p_view='impact' THEN 8 ELSE 4 END)
                OR p_after_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Invalid reversal context page' USING ERRCODE='22023'; END IF;
    """
        + projection().rstrip()
        + """ INTO v_result;
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.payment_reversal_context_page(uuid,uuid,uuid,text,integer,
                integer,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.payment_reversal_context_page(uuid,uuid,uuid,text,integer,
                integer,uuid)
            TO prm_runtime;
    """
    )


def downgrade() -> None:
    raise RuntimeError("Payment reversal context is forward-only")
