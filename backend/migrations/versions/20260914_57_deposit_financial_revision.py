# ruff: noqa: E501
"""Expose a read-only revision over existing immutable Deposit financial history."""

from alembic import op

revision = "20260914_57"
down_revision = "20260914_56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- Financial observation, not the mutable MVCC coordination counter.
        -- Count every immutable original/correction event, including net-zero histories.
        CREATE FUNCTION app.deposit_disposition_state_version(p_deposit uuid)
        RETURNS bigint LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT (deposit.version::numeric
                + (SELECT count(*) FROM app.deposit_required_amount_adjustments adjustment
                    WHERE adjustment.deposit_id=deposit.id)
                + (SELECT count(*) FROM app.deposit_balance_events(deposit.id)))::bigint
            FROM app.deposits deposit WHERE deposit.id=p_deposit
        $$;
        REVOKE ALL ON FUNCTION app.deposit_disposition_state_version(uuid) FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;

        CREATE OR REPLACE FUNCTION app.lease_termination_deposit_readiness(p_property uuid,p_lease uuid,p_actor uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            WITH source AS (
                SELECT lease.*,command.event_id AS termination_event_id,
                    CASE WHEN lease.status<>'TERMINATED' THEN 'NO_TERMINATION'
                        WHEN command.governing_event_reference='BR-LEASE-021'
                            AND lease.actual_termination_date<lease.end_date
                            AND (context.command_event_id IS NULL OR (
                                context.context_data->>'basis'='VOLUNTARY_EARLY'
                                AND context.lease_id=lease.id AND context.property_id=p_property
                                AND context.actual_termination_date=lease.actual_termination_date
                                AND context.occurred_at=lease.terminated_at))
                        THEN 'VOLUNTARY_EARLY_VERIFIED'
                        ELSE 'SIGNED_TERMS_REVIEW_REQUIRED' END AS evidence_status
                FROM app.leases lease
                LEFT JOIN LATERAL (
                    SELECT event.* FROM app.lease_commands event
                    WHERE lease.status='TERMINATED' AND event.lease_id=lease.id
                        AND event.property_id=p_property AND event.action='lease.terminate'
                        AND event.occurred_at=lease.terminated_at
                        AND event.result_snapshot->>'lease_id'=lease.id::text
                        AND event.result_snapshot->>'property_id'=p_property::text
                        AND event.result_snapshot->>'status'='TERMINATED'
                        AND event.result_snapshot->>'actual_termination_date'=lease.actual_termination_date::text
                    ORDER BY event.occurred_at DESC,event.event_id LIMIT 1
                ) command ON true
                LEFT JOIN app.lease_termination_contexts context ON context.command_event_id=command.event_id
                WHERE lease.id=p_lease
            ), balances AS (
                SELECT deposit.id,deposit.deposit_type,deposit.customer_id,
                    app.deposit_snapshot(deposit.id) AS snapshot,
                    COALESCE((SELECT sum(disposition.amount_usd_cents)
                        FROM app.deposit_dispositions disposition WHERE disposition.deposit_id=deposit.id
                            AND NOT EXISTS(SELECT 1 FROM app.deposit_disposition_reversals reversal
                                WHERE reversal.deposit_disposition_id=disposition.id)),0) AS active_disposition_usd_cents
                FROM app.deposits deposit WHERE deposit.lease_id=p_lease
                ORDER BY deposit.deposit_type,deposit.id LIMIT 3
            )
            SELECT jsonb_build_object(
                'lease_id',source.id,'property_id',p_property,'observed_at',statement_timestamp(),
                'lease_status',source.status,'actual_termination_date',source.actual_termination_date,
                'termination_event_id',source.termination_event_id,'evidence_status',source.evidence_status,
                'currency','USD','financial_completion_assessed',false,
                'deposits',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'deposit_id',balance.id,'deposit_type',balance.deposit_type,'customer_id',balance.customer_id,
                    'version',balance.snapshot->'version',
                    'disposition_state_version',app.deposit_disposition_state_version(balance.id),
                    'required_usd_cents',balance.snapshot->'required_usd_cents',
                    'received_usd_cents',balance.snapshot->'received_usd_cents',
                    'held_refundable_usd_cents',balance.snapshot->'held_refundable_usd_cents',
                    'outstanding_required_usd_cents',balance.snapshot->'outstanding_required_usd_cents',
                    'active_disposition_usd_cents',balance.active_disposition_usd_cents,
                    'consequence',CASE WHEN source.evidence_status='NO_TERMINATION' THEN 'NOT_TERMINATED'
                        WHEN source.evidence_status='VOLUNTARY_EARLY_VERIFIED' THEN CASE balance.deposit_type
                            WHEN 'SECURITY' THEN 'NON_REFUNDABLE_SECURITY' ELSE 'SEPARATE_PET_SETTLEMENT' END
                        ELSE 'SIGNED_TERMS_REVIEW_REQUIRED' END,
                    'business_rule',CASE WHEN source.evidence_status='VOLUNTARY_EARLY_VERIFIED'
                        THEN CASE balance.deposit_type WHEN 'SECURITY' THEN 'BR-DEP-023' ELSE 'BR-DEP-024' END
                        ELSE NULL END,
                    'explicit_disposition_pending',source.evidence_status='VOLUNTARY_EARLY_VERIFIED'
                        AND balance.deposit_type='SECURITY'
                        AND (balance.snapshot->>'held_refundable_usd_cents')::numeric>0
                ) ORDER BY balance.deposit_type,balance.id) FROM balances balance),'[]'::jsonb)
            ) INTO v_result FROM source;
            IF jsonb_array_length(v_result->'deposits')>2 THEN
                RAISE EXCEPTION 'Termination Deposit response exceeds the supported cardinality' USING ERRCODE='P5501';
            END IF;
            RETURN v_result;
        END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Deposit financial revision is forward-only")
