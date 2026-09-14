# ruff: noqa: E501
"""Read original Invoice coverage and current positions without approving corrections."""

from alembic import op

revision = "20260914_59"
down_revision = "20260914_58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.lease_termination_invoice_readiness(
            p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_after uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_event app.lease_commands%ROWTYPE;
        DECLARE v_context app.lease_termination_contexts%ROWTYPE;
        DECLARE v_event_count bigint; v_evidence text; v_context_valid boolean:=true;
        DECLARE v_items jsonb; v_line record; v_components jsonb; v_next uuid;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_after='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Invoice termination page is invalid' USING ERRCODE='22023'; END IF;
            SELECT * INTO v_lease FROM app.leases WHERE id=p_lease;
            v_evidence:=CASE WHEN v_lease.status='TERMINATED'
                THEN 'SIGNED_TERMS_REVIEW_REQUIRED' ELSE 'NO_TERMINATION' END;
            IF v_lease.status='TERMINATED' THEN
                SELECT count(*) INTO v_event_count FROM app.lease_commands event
                WHERE event.lease_id=p_lease AND event.property_id=p_property AND event.action='lease.terminate'
                    AND event.occurred_at=v_lease.terminated_at AND event.reason=v_lease.termination_reason
                    AND event.result_snapshot->>'lease_id'=p_lease::text
                    AND event.result_snapshot->>'property_id'=p_property::text
                    AND event.result_snapshot->>'status'='TERMINATED'
                    AND event.result_snapshot->>'actual_termination_date'=v_lease.actual_termination_date::text;
                IF v_event_count=1 THEN
                    SELECT * INTO v_event FROM app.lease_commands event
                    WHERE event.lease_id=p_lease AND event.property_id=p_property AND event.action='lease.terminate'
                        AND event.occurred_at=v_lease.terminated_at AND event.reason=v_lease.termination_reason
                        AND event.result_snapshot->>'lease_id'=p_lease::text
                        AND event.result_snapshot->>'property_id'=p_property::text
                        AND event.result_snapshot->>'status'='TERMINATED'
                        AND event.result_snapshot->>'actual_termination_date'=v_lease.actual_termination_date::text;
                    SELECT * INTO v_context FROM app.lease_termination_contexts WHERE command_event_id=v_event.event_id;
                    IF FOUND THEN
                        v_context_valid:=ROW(v_context.property_id,v_context.actor_id,v_context.idempotency_key,
                            v_context.request_digest,v_context.lease_id,v_context.actual_termination_date,
                            v_context.occurred_at,v_context.governing_event_reference,v_context.reason)
                            IS NOT DISTINCT FROM ROW(v_event.property_id,v_event.actor_id,v_event.idempotency_key,
                            v_event.request_digest,v_event.lease_id,v_lease.actual_termination_date,
                            v_event.occurred_at,v_event.governing_event_reference,v_event.reason)
                            AND app.lease_termination_context_shape_valid(v_context.context_data) IS TRUE
                            AND v_context.context_data->>'basis'='VOLUNTARY_EARLY';
                    END IF;
                    IF v_event.governing_event_reference='BR-LEASE-021'
                        AND v_lease.actual_termination_date<v_lease.end_date AND v_context_valid IS TRUE
                    THEN v_evidence:='VOLUNTARY_EARLY_VERIFIED'; END IF;
                END IF;
            END IF;
            v_items:='[]'::jsonb;
            FOR v_line IN
                SELECT line.id AS invoice_line_id,i.id AS invoice_id,i.customer_id,
                    i.version AS invoice_version,i.status AS invoice_status,i.issued_at IS NOT NULL AS issued,
                    i.rent_billing_kind,line.category,line.period_start,line.period_end,
                    CASE line.category WHEN 'RENT' THEN 'LEASE' WHEN 'UTILITIES' THEN 'UTILITY_CONSUMPTION_PERIOD'
                        WHEN 'SERVICE_CHARGES' THEN 'PROPERTY_SERVICE' ELSE 'AUTHORIZED_NONRECURRING_OBLIGATION' END AS source_type,
                    CASE line.category WHEN 'RENT' THEN line.source_lease_id
                        WHEN 'UTILITIES' THEN line.utility_consumption_period_id
                        WHEN 'SERVICE_CHARGES' THEN line.property_service_id ELSE line.authorized_obligation_id END AS source_id,
                    line.amount_usd_cents AS original_usd_cents,
                    app.invoice_adjusted_line_obligation(line.id) AS adjusted_usd_cents,
                    app.invoice_line_payment_value_at(line.id,'infinity') AS payment_applied_usd_cents,
                    app.invoice_line_credit_value_at(line.id,'infinity') AS credit_applied_usd_cents,
                    CASE WHEN i.status IN ('DRAFT','VOID') THEN 0 ELSE app.invoice_line_outstanding(line.id) END AS outstanding_usd_cents,
                    (SELECT count(*) FROM app.invoice_adjustments adjustment
                        WHERE adjustment.invoice_line_id=line.id AND NOT EXISTS(
                            SELECT 1 FROM app.invoice_adjustment_reversals reversal
                            WHERE reversal.invoice_adjustment_id=adjustment.id)) AS active_adjustment_count
                FROM app.invoice_lines line JOIN app.invoices i ON i.id=line.invoice_id
                WHERE i.lease_id=p_lease AND (p_after IS NULL OR line.id>p_after)
                ORDER BY line.id LIMIT p_limit+1
            LOOP
                IF jsonb_array_length(v_items)=p_limit THEN
                    v_next:=(v_items->(p_limit-1)->>'invoice_line_id')::uuid;
                    EXIT;
                END IF;
                IF app.invoice_property_id(v_line.invoice_id) IS DISTINCT FROM p_property
                    OR (NOT (v_line.invoice_status='VOID' AND NOT v_line.issued) AND NOT EXISTS (
                        SELECT 1 FROM app.invoices invoice JOIN app.lease_signers signer
                            ON signer.lease_id=invoice.lease_id
                        WHERE invoice.id=v_line.invoice_id AND signer.customer_id=v_line.customer_id
                            AND signer.signed_at IS NOT NULL
                            AND (invoice.issued_at IS NULL OR signer.signed_at<=invoice.issued_at)
                    ))
                    OR (v_line.category='RENT' AND v_line.source_id IS DISTINCT FROM p_lease)
                THEN RAISE EXCEPTION 'Invoice termination source scope is inconsistent' USING ERRCODE='P5901'; END IF;
                SELECT COALESCE(jsonb_agg(to_jsonb(component) ORDER BY component.sequence,component.id),'[]'::jsonb)
                INTO v_components FROM (
                    SELECT id,component_sequence AS sequence,component_kind AS kind,period_start,period_end,
                        contractual_monthly_usd_cents,service_monthly_rate_usd_cents,amount_usd_cents
                    FROM app.invoice_line_calculation_components WHERE invoice_line_id=v_line.invoice_line_id
                    ORDER BY component_sequence,id LIMIT 101
                ) component;
                IF jsonb_array_length(v_components)>100 THEN
                    RAISE EXCEPTION 'Invoice component page exceeds supported cardinality' USING ERRCODE='P5901';
                END IF;
                v_items:=v_items || jsonb_build_array(to_jsonb(v_line) || jsonb_build_object('components',v_components));
            END LOOP;
            RETURN jsonb_build_object('lease_id',p_lease,'property_id',p_property,
                'primary_tenant_id',v_lease.primary_tenant_id,'lease_status',v_lease.status,
                'lease_start_date',v_lease.start_date,'lease_end_date',v_lease.end_date,
                'actual_termination_date',v_lease.actual_termination_date,'termination_event_id',v_event.event_id,
                'evidence_status',v_evidence,'observed_at',statement_timestamp(),
                'contractual_monthly_usd_cents',v_lease.monthly_rent_usd_cents,
                'full_final_month_rent_usd_cents',CASE WHEN v_evidence='VOLUNTARY_EARLY_VERIFIED' THEN v_lease.monthly_rent_usd_cents END,
                'currency','USD','financial_completion_assessed',false,'financial_dependencies_fully_assessed',false,
                'items',v_items,'next_cursor',v_next);
        END $$;
        REVOKE ALL ON FUNCTION app.lease_termination_invoice_readiness(uuid,uuid,uuid,integer,uuid)
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT EXECUTE ON FUNCTION app.lease_termination_invoice_readiness(uuid,uuid,uuid,integer,uuid)
            TO prm_runtime,prm_financial;
    """)


def downgrade() -> None:
    raise RuntimeError("Invoice termination readiness is forward-only")
