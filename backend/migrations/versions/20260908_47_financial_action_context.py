"""Selected financial action facts and bounded details without financial writes."""

from alembic import op

revision = "20260908_47"
down_revision = "20260908_46"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.financial_action_context_page(
            p_property uuid,p_actor uuid,p_purpose text,p_source uuid,p_refund uuid,
            p_target_kind text,p_target uuid,p_limit integer,p_after_sequence integer,p_after_id
                uuid
        ) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_payment app.payments%ROWTYPE;
        DECLARE v_allocation app.payment_allocations%ROWTYPE;
        DECLARE v_application app.customer_credit_applications%ROWTYPE;
        DECLARE v_receipt app.receipts%ROWTYPE;
        DECLARE v_refund app.refunds%ROWTYPE;
        DECLARE v_correction app.refund_corrections%ROWTYPE;
        DECLARE v_invoice app.invoices%ROWTYPE;
        DECLARE v_charge app.late_payment_charges%ROWTYPE;
        DECLARE v_payment_id uuid; v_credit_id uuid; v_deposit_id uuid;
        DECLARE v_target_kind text:=p_target_kind; v_target_id uuid:=p_target;
        DECLARE v_context jsonb:='{}'; v_target jsonb; v_result jsonb;
        DECLARE v_customer uuid; v_current_customer uuid; v_current_lease uuid;
        DECLARE v_target_invoice uuid; v_applicable boolean;
        BEGIN
            PERFORM app.credit_refund_http_scope('property',p_property,p_actor,ARRAY[p_property]);
            IF p_purpose IS NULL OR p_purpose NOT IN('allocation','allocation_reversal',
                'receipt_reprint','credit_recognition','credit_reversal','credit_application',
                'credit_application_reversal','refund_return','refund_correction_reversal')
                OR p_source IS NULL OR p_source='00000000-0000-0000-0000-000000000000'
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR (p_target_kind IS NULL)<>(p_target IS NULL)
                OR p_target_kind NOT IN('INVOICE','LATE_PAYMENT_CHARGE')
                OR p_target='00000000-0000-0000-0000-000000000000'
                OR (p_target IS NOT NULL AND p_purpose NOT IN('allocation','credit_application'))
                OR (p_purpose='refund_correction_reversal')<>(p_refund IS NOT NULL)
                OR p_refund='00000000-0000-0000-0000-000000000000'
                OR (p_after_sequence IS NULL)<>(p_after_id IS NULL)
                OR p_after_sequence NOT BETWEEN 1 AND 32767
                OR p_after_id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Invalid financial action context' USING ERRCODE='22023'; END IF;

            CASE p_purpose
            WHEN 'allocation','credit_recognition' THEN
                v_payment_id:=p_source;
            WHEN 'allocation_reversal' THEN
                SELECT a.* INTO v_allocation FROM app.payment_allocations a
                    JOIN app.payments p ON p.id=a.payment_id
                    WHERE a.id=p_source AND p.property_id=p_property;
                v_payment_id:=v_allocation.payment_id;
                v_target_kind:=v_allocation.target_kind;
                v_target_id:=COALESCE(v_allocation.invoice_id,v_allocation.late_payment_charge_id);
                -- The proposal's original per-line amounts remain below. Large audit
                -- traces stay linked by immutable event identity, never expanded here.
                v_context:=jsonb_build_object('allocation',jsonb_build_object(
                    'id',v_allocation.id,'payment_id',v_payment_id,
                    'target_customer_id',v_allocation.target_customer_id,
                    'target_kind',v_target_kind,'target_id',v_target_id,
                    'amount_usd_cents',v_allocation.amount_usd_cents,
                    'between_invoice_basis',v_allocation.between_invoice_basis,
                    'within_invoice_basis',v_allocation.within_invoice_basis,
                    'customer_designation_reference',v_allocation.customer_designation_reference,
                    'proposal_batch_id',v_allocation.proposal_batch_id,
                    'between_invoice_sequence',v_allocation.between_invoice_sequence,
                    'selected_invoice_due_date',v_allocation.selected_invoice_due_date,
                    'selected_invoice_issued_at',v_allocation.selected_invoice_issued_at,
                    'selected_invoice_number_snapshot',
                        v_allocation.selected_invoice_number_snapshot,
                    'proposal_generated_at',v_allocation.proposal_generated_at,
                    'posted_at',v_allocation.posted_at,'posted_by',v_allocation.posted_by,
                    'authorization_reference',v_allocation.authorization_reference),
                    'reversal',(SELECT to_jsonb(r) FROM app.payment_allocation_reversals r
                        WHERE r.payment_allocation_id=p_source));
            WHEN 'receipt_reprint' THEN
                SELECT r.* INTO v_receipt FROM app.receipts r JOIN app.payments p ON
                    p.id=r.payment_id
                    WHERE r.id=p_source AND p.property_id=p_property;
                v_payment_id:=v_receipt.payment_id;
                v_context:=jsonb_build_object('receipt',to_jsonb(v_receipt));
            WHEN 'credit_reversal','credit_application' THEN
                PERFORM app.credit_refund_http_scope('credit',p_source,p_actor,ARRAY[p_property]);
                v_credit_id:=p_source;
            WHEN 'credit_application_reversal' THEN
                PERFORM app.credit_refund_http_scope('credit_application',p_source,p_actor,
                    ARRAY[p_property]);
                SELECT * INTO v_application FROM app.customer_credit_applications WHERE id=p_source;
                v_credit_id:=v_application.customer_credit_id;
                v_target_kind:=v_application.target_kind;
                v_target_id:=COALESCE(v_application.invoice_id,
                    v_application.late_payment_charge_id);
                v_context:=jsonb_build_object('application',jsonb_build_object(
                    'id',v_application.id,'customer_credit_id',v_credit_id,
                    'target_kind',v_target_kind,'target_id',v_target_id,
                    'amount_usd_cents',v_application.amount_usd_cents,
                    'within_invoice_basis',v_application.within_invoice_basis,
                    'customer_designation_reference',v_application.customer_designation_reference,
                    'proposal_generated_at',v_application.proposal_generated_at,
                    'occurred_at',v_application.occurred_at,'actor_id',v_application.actor_id,
                    'authorization_reference',v_application.authorization_reference),
                    'reversal',(SELECT to_jsonb(r) FROM app.customer_credit_application_reversals r
                        WHERE r.credit_application_id=p_source));
            WHEN 'refund_return','refund_correction_reversal' THEN
                PERFORM app.credit_refund_http_scope('refund',COALESCE(p_refund,p_source),
                    p_actor,ARRAY[p_property]);
                SELECT * INTO v_refund FROM app.refunds WHERE id=COALESCE(p_refund,p_source);
                v_payment_id:=v_refund.source_payment_id;
                v_credit_id:=v_refund.source_customer_credit_id;
                v_deposit_id:=v_refund.source_deposit_id;
                v_context:=jsonb_build_object('refund',app.refund_summary(v_refund.id),
                    'deposit_source',(SELECT jsonb_build_object('id',d.id,'deposit_type',
                        d.deposit_type,
                        'held_usd_cents',app.deposit_held_value_at(d.id,'infinity'))
                        FROM app.deposits d WHERE d.id=v_deposit_id));
                IF p_purpose='refund_correction_reversal' THEN
                    SELECT * INTO v_correction FROM app.refund_corrections
                        WHERE id=p_source AND refund_id=p_refund AND
                            correction_kind='VALUE_CORRECTION';
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Financial source not found' USING ERRCODE='P4501';
                    END IF;
                    v_context:=v_context||jsonb_build_object('correction',to_jsonb(v_correction),
                        'reversal',(SELECT to_jsonb(r) FROM app.refund_corrections r
                            WHERE r.reverses_correction_id=p_source));
                END IF;
            END CASE;
            IF v_credit_id IS NOT NULL THEN
                SELECT source_payment_id,customer_id INTO v_payment_id,v_customer
                    FROM app.customer_credits WHERE id=v_credit_id;
                v_context:=v_context||jsonb_build_object('credit',
                    app.credit_read_summary(v_credit_id));
                IF p_purpose='credit_reversal' THEN
                    v_context:=v_context||jsonb_build_object('reversal',
                        (SELECT to_jsonb(r) FROM app.customer_credit_reversals r
                            WHERE r.customer_credit_id=v_credit_id));
                END IF;
            END IF;
            IF v_payment_id IS NOT NULL THEN
                PERFORM app.credit_refund_http_scope('payment',v_payment_id,p_actor,
                    ARRAY[p_property]);
                SELECT * INTO v_payment FROM app.payments WHERE id=v_payment_id;
            ELSIF v_deposit_id IS NULL THEN
                RAISE EXCEPTION 'Financial source not found' USING ERRCODE='P4501';
            END IF;
            IF p_purpose='credit_recognition' THEN
                SELECT EXISTS(
                SELECT 1 FROM app.invoices invoice
                WHERE app.invoice_property_id(invoice.id)=v_payment.property_id
                    AND invoice.status IN ('UNPAID','PARTIALLY_PAID')
                    AND v_payment.identified_late_payment_charge_id IS NULL
                    AND (v_payment.identified_invoice_id IS NULL OR
                        invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND
                        invoice.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR
                                invoice.lease_id=v_payment.lease_id)))
                    AND EXISTS(SELECT 1 FROM app.invoice_lines line WHERE line.invoice_id=invoice.id
                        AND app.invoice_line_outstanding(line.id)>0)
            ) OR EXISTS(
                SELECT 1 FROM app.late_payment_charges charge
                JOIN app.invoices invoice ON invoice.id=charge.source_invoice_id
                JOIN app.late_payment_charge_financial_position position ON
                    position.late_payment_charge_id=charge.id
                WHERE app.invoice_property_id(invoice.id)=v_payment.property_id
                    AND position.remaining_balance_usd_cents>0
                    AND (v_payment.identified_late_payment_charge_id IS NULL OR
                        charge.id=v_payment.identified_late_payment_charge_id)
                    AND (v_payment.identified_invoice_id IS NULL OR
                        invoice.id=v_payment.identified_invoice_id)
                    AND ((v_payment.payment_scope_kind='NORMAL_CUSTOMER' AND
                        charge.customer_id=v_payment.payer_customer_id)
                        OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED'
                            AND (v_payment.lease_id IS NULL OR
                                invoice.lease_id=v_payment.lease_id)))
            ) INTO v_applicable;
                v_context:=jsonb_build_object('applicable_obligations',v_applicable);
            END IF;

            IF v_target_kind='INVOICE' THEN
                SELECT * INTO v_invoice FROM app.invoices WHERE id=v_target_id
                    AND app.invoice_property_id(id)=p_property;
                IF NOT FOUND THEN RAISE EXCEPTION 'Financial target not found' USING
                    ERRCODE='P4501'; END IF;
                v_current_customer:=v_invoice.customer_id; v_current_lease:=v_invoice.lease_id;
                v_target_invoice:=v_invoice.id;
                SELECT jsonb_build_object('kind','INVOICE','id',v_invoice.id,
                    'property_id',p_property,'customer_id',v_invoice.customer_id,
                    'lease_id',v_invoice.lease_id,'invoice_number',v_invoice.invoice_number,
                    'status',v_invoice.status,'due_date',v_invoice.due_date,
                    'issued_at',v_invoice.issued_at,'outstanding_usd_cents',
                    CASE WHEN v_invoice.status IN('DRAFT','VOID') THEN 0 ELSE
                        COALESCE((SELECT sum(app.invoice_line_outstanding(l.id))
                            FROM app.invoice_lines l WHERE l.invoice_id=v_invoice.id),0) END)
                    INTO v_target;
            ELSIF v_target_kind='LATE_PAYMENT_CHARGE' THEN
                SELECT c.* INTO v_charge FROM app.late_payment_charges c
                    WHERE c.id=v_target_id AND
                        app.invoice_property_id(c.source_invoice_id)=p_property;
                IF NOT FOUND THEN RAISE EXCEPTION 'Financial target not found' USING
                    ERRCODE='P4501'; END IF;
                SELECT * INTO v_invoice FROM app.invoices WHERE id=v_charge.source_invoice_id;
                v_current_customer:=v_charge.customer_id; v_current_lease:=v_invoice.lease_id;
                v_target_invoice:=v_invoice.id;
                SELECT jsonb_build_object('kind','LATE_PAYMENT_CHARGE','id',v_charge.id,
                    'property_id',p_property,'customer_id',v_charge.customer_id,
                    'lease_id',v_invoice.lease_id,'source_invoice_id',v_charge.source_invoice_id,
                    'payable_at',v_charge.payable_at,'original_usd_cents',
                        v_charge.original_amount_usd_cents,
                    'reversed',EXISTS(SELECT 1 FROM app.late_payment_charge_corrections x
                        WHERE x.late_payment_charge_id=v_charge.id AND
                            x.correction_kind='CHARGE_REVERSAL'),
                    'adjusted_obligation_usd_cents',
                        v_charge.original_amount_usd_cents+effects.correction,
                    'remaining_balance_usd_cents',
                        v_charge.original_amount_usd_cents+effects.correction
                        -COALESCE((SELECT sum(a.amount_usd_cents) FROM app.payment_allocations a
                            WHERE a.late_payment_charge_id=v_charge.id AND NOT EXISTS(
                                SELECT 1 FROM app.payment_allocation_reversals r WHERE
                                    r.payment_allocation_id=a.id)),0)
                        -COALESCE((SELECT sum(a.amount_usd_cents) FROM
                            app.customer_credit_applications a
                            WHERE a.late_payment_charge_id=v_charge.id AND NOT EXISTS(
                                SELECT 1 FROM app.customer_credit_application_reversals r WHERE
                                    r.credit_application_id=a.id)),0))
                INTO v_target FROM (SELECT COALESCE(sum(CASE correction_kind
                    WHEN 'REDUCTION_REVERSAL' THEN amount_usd_cents ELSE -amount_usd_cents END),
                        0) correction
                    FROM app.late_payment_charge_corrections WHERE
                        late_payment_charge_id=v_charge.id) effects;
            END IF;
            IF v_target_id IS NOT NULL THEN
                IF v_credit_id IS NOT NULL THEN
                    IF v_current_customer IS DISTINCT FROM v_customer THEN
                        RAISE EXCEPTION 'Financial target not found' USING ERRCODE='P4501';
                    END IF;
                ELSIF (v_payment.payment_scope_kind='NORMAL_CUSTOMER'
                        AND v_current_customer IS DISTINCT FROM v_payment.payer_customer_id)
                    OR (v_payment.payment_scope_kind='THIRD_PARTY_IDENTIFIED' AND
                        v_payment.lease_id IS NOT NULL
                        AND v_current_lease IS DISTINCT FROM v_payment.lease_id)
                    OR (v_payment.identified_invoice_id IS NOT NULL
                        AND v_target_invoice IS DISTINCT FROM v_payment.identified_invoice_id)
                    OR (v_payment.identified_late_payment_charge_id IS NOT NULL
                        AND (v_target_kind<>'LATE_PAYMENT_CHARGE'
                            OR v_target_id IS DISTINCT FROM
                                v_payment.identified_late_payment_charge_id))
                THEN RAISE EXCEPTION 'Financial target not found' USING ERRCODE='P4501'; END IF;
            END IF;

            -- Select identity keys before bounded original/current detail projection.
            WITH entries AS (
                SELECT d.detail_sequence sequence,d.id,'ALLOCATION_LINE'::text kind
                    FROM app.payment_allocation_details d
                    WHERE p_purpose='allocation_reversal' AND d.payment_allocation_id=p_source
                UNION ALL SELECT d.detail_sequence,d.id,'CREDIT_APPLICATION_LINE'
                    FROM app.customer_credit_application_details d
                    WHERE p_purpose='credit_application_reversal' AND
                        d.customer_credit_application_id=p_source
                UNION ALL SELECT l.line_sequence,l.id,'INVOICE_LINE' FROM app.invoice_lines l
                    WHERE p_purpose IN('allocation','credit_application')
                        AND v_target_kind='INVOICE' AND l.invoice_id=v_target_id
            ), selected AS MATERIALIZED (
                SELECT sequence,id,kind FROM entries WHERE p_after_id IS NULL
                    OR (sequence,id)>(p_after_sequence,p_after_id)
                ORDER BY sequence,id LIMIT p_limit+1
            ), deposits AS (
                SELECT DISTINCT deposit_id id FROM app.deposit_receipts WHERE
                    payment_id=v_payment_id
                UNION SELECT v_deposit_id WHERE v_deposit_id IS NOT NULL
            ), target_guards AS (
                SELECT 'invoice-financial:'||v_target_invoice::text key WHERE v_target_invoice
                    IS NOT NULL
                UNION SELECT 'late-charge:'||v_target_id::text WHERE
                    v_target_kind='LATE_PAYMENT_CHARGE'
            ) SELECT jsonb_build_object(
                'source_payment_id',v_payment_id,'context',v_context,'target',v_target,
                'revision_evidence',jsonb_build_object('property',p_property,'purpose',p_purpose,
                    'source',p_source,'refund',p_refund,'requested_target_kind',p_target_kind,
                    'requested_target',p_target,'payment',v_payment_id,'payment_status',
                        v_payment.status,
                    'payment_revision',COALESCE((SELECT revision FROM
                        app.payment_serialization_guards
                        WHERE payment_id=v_payment_id),0),
                    'deposit_count',(SELECT count(*) FROM deposits),
                    'deposit_revision',COALESCE((SELECT sum(g.revision) FROM deposits d
                        JOIN app.deposit_serialization_guards g ON g.deposit_id=d.id),0),
                    'target_count',(SELECT count(*) FROM target_guards),
                    'target_revision',COALESCE((SELECT sum(g.revision) FROM target_guards t
                        JOIN app.invoice_serialization_guards g ON g.guard_key=t.key),0)),
                'unsupported_application',EXISTS(SELECT 1 FROM deposits d
                    WHERE app.deposit_has_active_application(d.id)),
                'anchor_found',p_after_id IS NULL OR EXISTS(SELECT 1 FROM entries
                    WHERE sequence=p_after_sequence AND id=p_after_id),
                'items',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'sequence',s.sequence,'id',s.id,'kind',s.kind,'data',CASE s.kind
                    WHEN 'ALLOCATION_LINE' THEN (SELECT jsonb_build_object(
                        'allocation_id',d.payment_allocation_id,'target_kind',d.obligation_kind,
                        'target_id',COALESCE(d.invoice_line_id,d.late_payment_charge_id),
                        'category',d.invoice_line_category_snapshot,'proposed_amount_usd_cents',
                            d.proposed_amount_usd_cents,
                        'posted_amount_usd_cents',d.posted_amount_usd_cents,'attribution_basis',
                            d.attribution_basis,
                        'current_outstanding_usd_cents',CASE WHEN d.invoice_line_id IS NULL THEN
                            (v_target->>'remaining_balance_usd_cents')::numeric
                            WHEN v_invoice.status IN('DRAFT','VOID') THEN 0
                            ELSE app.invoice_line_outstanding(d.invoice_line_id) END)
                        FROM app.payment_allocation_details d WHERE d.id=s.id)
                    WHEN 'CREDIT_APPLICATION_LINE' THEN (SELECT jsonb_build_object(
                        'application_id',d.customer_credit_application_id,'target_kind',
                            d.obligation_kind,
                        'target_id',COALESCE(d.invoice_line_id,d.late_payment_charge_id),
                        'category',d.invoice_line_category_snapshot,'proposed_amount_usd_cents',
                            d.proposed_amount_usd_cents,
                        'applied_amount_usd_cents',d.applied_amount_usd_cents,
                            'attribution_basis',d.attribution_basis,
                        'current_outstanding_usd_cents',CASE WHEN d.invoice_line_id IS NULL THEN
                            (v_target->>'remaining_balance_usd_cents')::numeric
                            WHEN v_invoice.status IN('DRAFT','VOID') THEN 0
                            ELSE app.invoice_line_outstanding(d.invoice_line_id) END)
                        FROM app.customer_credit_application_details d WHERE d.id=s.id)
                    WHEN 'INVOICE_LINE' THEN (SELECT jsonb_build_object('invoice_id',l.invoice_id,
                        'category',l.category,'description',l.description,
                        'original_amount_usd_cents',l.amount_usd_cents,
                        'adjusted_amount_usd_cents',app.invoice_adjusted_line_obligation(l.id),
                        'outstanding_usd_cents',CASE WHEN v_invoice.status IN('DRAFT','VOID') THEN 0
                            ELSE app.invoice_line_outstanding(l.id) END)
                        FROM app.invoice_lines l WHERE l.id=s.id) END) ORDER BY s.sequence,s.id)
                    FROM selected s),'[]'::jsonb)) INTO v_result;
            IF octet_length(v_result::text)>1000000 THEN
                RAISE EXCEPTION 'Financial context exceeds response budget' USING ERRCODE='54000';
            END IF;
            RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,
            uuid,integer,integer,uuid) FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.financial_action_context_page(uuid,uuid,text,uuid,uuid,text,
            uuid,integer,integer,uuid) TO prm_runtime;
    """)


def downgrade() -> None:
    raise RuntimeError("Financial action contexts are forward-only")
