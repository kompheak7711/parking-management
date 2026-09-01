# ruff: noqa: E501
"""Add the bounded late-payment Decision, Charge, and correction API boundary."""

from alembic import op

revision = "20260831_37"
down_revision = "20260831_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install protected reads and idempotent audited late-payment commands."""
    op.execute(
        r"""
        ALTER TABLE app.late_payment_decisions
            DROP CONSTRAINT late_payment_decisions_outcome_amount;
        ALTER TABLE app.late_payment_decisions
            ADD CONSTRAINT late_payment_decisions_outcome_amount CHECK (
                (decision_outcome='WAIVED' AND approved_amount_usd_cents=0)
                OR (decision_outcome='CONFIRMED_DEFAULT'
                    AND approved_amount_usd_cents=calculated_default_amount_usd_cents)
                OR (decision_outcome='REDUCED' AND approved_amount_usd_cents>0
                    AND approved_amount_usd_cents<calculated_default_amount_usd_cents)
            );

        CREATE TABLE app.late_payment_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (action IN ('decision','correction')),
            idempotency_key uuid NOT NULL CHECK (
                idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{64}$'),
            target_kind text NOT NULL CHECK (target_kind IN ('INVOICE','CHARGE')),
            target_id uuid NOT NULL CHECK (
                target_id<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            result_entity_id uuid NOT NULL CHECK (
                result_entity_id<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            response_status smallint NOT NULL,
            response_body jsonb NOT NULL CHECK (
                jsonb_typeof(response_body)='object'
                AND jsonb_typeof(response_body->'data')='object'
                AND jsonb_typeof(response_body->'meta')='object'
                AND jsonb_typeof(response_body->'meta'->'request_id')='string'
            ),
            completed_at timestamptz NOT NULL,
            PRIMARY KEY(property_id,actor_id,action,idempotency_key),
            CONSTRAINT late_payment_command_shape CHECK (
                (action='decision' AND target_kind='INVOICE')
                OR (action='correction' AND target_kind='CHARGE')
            ),
            CONSTRAINT late_payment_command_response_status CHECK (
                (action='decision' AND response_status=201)
                OR (action='correction' AND response_status=200)
            )
        );
        CREATE INDEX late_payment_commands_target_history_idx
            ON app.late_payment_commands(target_kind,target_id,completed_at,idempotency_key);

        CREATE FUNCTION app.late_payment_charge_property_id(p_charge_id uuid)
        RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT app.invoice_property_id(charge.source_invoice_id)
            FROM app.late_payment_charges AS charge WHERE charge.id=p_charge_id
        $$;

        CREATE FUNCTION app.late_payment_charge_application_summary(p_charge_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM app.late_payment_charges WHERE id=p_charge_id
            ) THEN jsonb_build_object(
                'active_total_usd_cents',0,
                'payment_total_usd_cents',0,
                'credit_total_usd_cents',0,
                'items','[]'::jsonb
            ) ELSE NULL END
        $$;

        CREATE VIEW app.late_payment_charge_financial_position
        WITH (security_invoker = true)
        AS
        SELECT
            charge.id AS late_payment_charge_id,
            charge.customer_id,
            charge.source_invoice_id,
            charge.late_payment_decision_id,
            charge.original_amount_usd_cents,
            correction.reduction_usd_cents,
            correction.reduction_reversal_usd_cents,
            correction.active_reduction_usd_cents,
            correction.charge_reversal_usd_cents,
            correction.active_reduction_usd_cents
                + correction.charge_reversal_usd_cents
                AS active_correction_effect_usd_cents,
            COALESCE((applications.summary->>'payment_total_usd_cents')::bigint,0)
                AS payment_applied_usd_cents,
            COALESCE((applications.summary->>'credit_total_usd_cents')::bigint,0)
                AS credit_applied_usd_cents,
            COALESCE((applications.summary->>'active_total_usd_cents')::bigint,0)
                AS active_applications_usd_cents,
            charge.original_amount_usd_cents
                - correction.active_reduction_usd_cents
                - correction.charge_reversal_usd_cents
                AS adjusted_obligation_usd_cents,
            charge.original_amount_usd_cents
                - correction.active_reduction_usd_cents
                - correction.charge_reversal_usd_cents
                - COALESCE((applications.summary->>'active_total_usd_cents')::bigint,0)
                AS remaining_balance_usd_cents,
            correction.correction_count,
            charge.payable_at,
            charge.created_at,
            charge.created_by
        FROM app.late_payment_charges AS charge
        CROSS JOIN LATERAL (
            SELECT
                COALESCE(sum(correction.amount_usd_cents) FILTER (
                    WHERE correction.correction_kind='REDUCTION'),0)::bigint
                    AS reduction_usd_cents,
                COALESCE(sum(correction.amount_usd_cents) FILTER (
                    WHERE correction.correction_kind='REDUCTION_REVERSAL'),0)::bigint
                    AS reduction_reversal_usd_cents,
                COALESCE(sum(correction.amount_usd_cents) FILTER (
                    WHERE correction.correction_kind='REDUCTION'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM app.late_payment_charge_corrections AS reversal
                          WHERE reversal.reverses_correction_id=correction.id
                      )),0)::bigint AS active_reduction_usd_cents,
                COALESCE(sum(correction.amount_usd_cents) FILTER (
                    WHERE correction.correction_kind='CHARGE_REVERSAL'),0)::bigint
                    AS charge_reversal_usd_cents,
                count(correction.id)::bigint AS correction_count
            FROM app.late_payment_charge_corrections AS correction
            WHERE correction.late_payment_charge_id=charge.id
        ) AS correction
        CROSS JOIN LATERAL (
            SELECT app.late_payment_charge_application_summary(charge.id) AS summary
        ) AS applications;

        CREATE FUNCTION app.late_payment_decision_snapshot(p_decision_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_decision app.late_payment_decisions%ROWTYPE; v_property_id uuid;
        DECLARE v_charge_id uuid; v_lease_id uuid; v_business_date date;
        BEGIN
            SELECT * INTO v_decision FROM app.late_payment_decisions WHERE id=p_decision_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            v_property_id:=app.invoice_property_id(v_decision.source_invoice_id);
            SELECT invoice.lease_id,
                timezone(property.timezone_name,v_decision.finalized_at)::date
            INTO v_lease_id,v_business_date
            FROM app.invoices AS invoice
            JOIN app.properties AS property ON property.id=v_property_id
            WHERE invoice.id=v_decision.source_invoice_id;
            SELECT id INTO v_charge_id FROM app.late_payment_charges
            WHERE late_payment_decision_id=v_decision.id;
            RETURN jsonb_build_object(
                'id',v_decision.id,'event_type','LATE_PAYMENT_DECISION',
                'property_id',v_property_id,'customer_id',v_decision.customer_id,
                'lease_id',v_lease_id,'business_date',v_business_date,
                'source_invoice',jsonb_build_object(
                    'id',v_decision.source_invoice_id,'due_date',v_decision.source_due_date),
                'overdue_balance_at_assessment',jsonb_build_object(
                    'currency','USD','minor_units',
                    v_decision.overdue_balance_at_assessment_usd_cents),
                'default_rate_basis_points',v_decision.default_rate_basis_points,
                'calculated_default_amount',jsonb_build_object(
                    'currency','USD','minor_units',
                    v_decision.calculated_default_amount_usd_cents),
                'outcome',v_decision.decision_outcome,
                'approved_amount',jsonb_build_object(
                    'currency','USD','minor_units',v_decision.approved_amount_usd_cents),
                'assessed_at',v_decision.assessed_at,'finalized_at',v_decision.finalized_at,
                'finalized_by',v_decision.finalized_by,'reason',v_decision.reason,
                'authorization_reference',v_decision.authorization_reference,
                'calculation_evidence',v_decision.calculation_trace,
                'charge',CASE WHEN v_charge_id IS NULL THEN NULL
                    ELSE jsonb_build_object('id',v_charge_id) END
            );
        END $$;

        CREATE FUNCTION app.late_payment_decision_snapshot_for_invoice(p_invoice_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT app.late_payment_decision_snapshot(decision.id)
            FROM app.late_payment_decisions AS decision
            WHERE decision.source_invoice_id=p_invoice_id
        $$;

        CREATE FUNCTION app.late_payment_review_snapshot(p_invoice_id uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_property_id uuid; v_timezone text;
        DECLARE v_now timestamptz; v_business_date date; v_balance bigint; v_default bigint;
        DECLARE v_decision jsonb; v_blockers jsonb:='[]'::jsonb; v_lease_status text;
        BEGIN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            v_property_id:=app.invoice_property_id(p_invoice_id);
            IF v_property_id IS NULL THEN RETURN NULL; END IF;
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=v_property_id;
            v_now:=statement_timestamp();
            v_business_date:=timezone(v_timezone,v_now)::date;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
            INTO v_balance FROM app.invoice_lines AS line WHERE line.invoice_id=p_invoice_id;
            v_default:=floor((v_balance::numeric+5)/10)::bigint;
            IF v_invoice.lease_id IS NOT NULL THEN
                SELECT status INTO v_lease_status FROM app.leases WHERE id=v_invoice.lease_id;
            END IF;
            v_decision:=app.late_payment_decision_snapshot_for_invoice(p_invoice_id);
            IF v_invoice.lease_id IS NULL OR v_lease_status NOT IN ('SIGNED','TERMINATED') THEN
                v_blockers:=v_blockers||jsonb_build_array('INVOICE_NOT_LEASE_PAYABLE');
            END IF;
            IF v_invoice.status<>'UNPAID' THEN
                v_blockers:=v_blockers||jsonb_build_array('INVOICE_NOT_UNPAID');
            END IF;
            IF v_invoice.due_date>=v_business_date THEN
                v_blockers:=v_blockers||jsonb_build_array('DUE_DATE_NOT_PASSED');
            END IF;
            IF v_balance<=0 THEN
                v_blockers:=v_blockers||jsonb_build_array('NO_REMAINING_BALANCE');
            END IF;
            IF v_balance>9000000000000000 THEN
                v_blockers:=v_blockers||jsonb_build_array('BALANCE_OUT_OF_SUPPORTED_RANGE');
            END IF;
            IF v_decision IS NOT NULL THEN
                v_blockers:=v_blockers||jsonb_build_array('FINAL_DECISION_EXISTS');
            END IF;
            RETURN jsonb_build_object(
                'invoice_id',v_invoice.id,'property_id',v_property_id,
                'customer_id',v_invoice.customer_id,'lease_id',v_invoice.lease_id,
                'source_due_date',v_invoice.due_date,'property_timezone',v_timezone,
                'business_date',v_business_date,'reviewed_at',v_now,
                'overdue_balance',jsonb_build_object(
                    'currency','USD','minor_units',v_balance),
                'default_rate_basis_points',1000,
                'calculated_default_amount',jsonb_build_object(
                    'currency','USD','minor_units',v_default),
                'eligible',jsonb_array_length(v_blockers)=0,
                'blocking_conditions',v_blockers,'prior_decision',v_decision
            );
        END $$;

        CREATE FUNCTION app.late_payment_charge_snapshot(p_charge_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_charge app.late_payment_charges%ROWTYPE; v_property_id uuid;
        DECLARE v_position app.late_payment_charge_financial_position%ROWTYPE;
        DECLARE v_applications jsonb; v_corrections jsonb;
        DECLARE v_lease_id uuid; v_business_date date;
        BEGIN
            SELECT * INTO v_charge FROM app.late_payment_charges WHERE id=p_charge_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            v_property_id:=app.invoice_property_id(v_charge.source_invoice_id);
            SELECT * INTO STRICT v_position
            FROM app.late_payment_charge_financial_position
            WHERE late_payment_charge_id=p_charge_id;
            SELECT invoice.lease_id,
                timezone(property.timezone_name,v_charge.payable_at)::date
            INTO v_lease_id,v_business_date
            FROM app.invoices AS invoice
            JOIN app.properties AS property ON property.id=v_property_id
            WHERE invoice.id=v_charge.source_invoice_id;
            SELECT COALESCE(jsonb_agg(jsonb_build_object(
                    'id',correction.id,'kind',correction.correction_kind,
                    'amount',jsonb_build_object('currency','USD',
                        'minor_units',correction.amount_usd_cents),
                    'reverses_correction_id',correction.reverses_correction_id,
                    'reason',correction.reason,
                    'previous_obligation',jsonb_build_object('currency','USD',
                        'minor_units',correction.previous_obligation_usd_cents),
                    'resulting_obligation',jsonb_build_object('currency','USD',
                        'minor_units',correction.resulting_obligation_usd_cents),
                    'occurred_at',correction.occurred_at,'actor_id',correction.actor_id,
                    'authorization_reference',correction.authorization_reference,
                    'active',CASE WHEN correction.correction_kind='REDUCTION' THEN NOT EXISTS (
                        SELECT 1 FROM app.late_payment_charge_corrections AS reversal
                        WHERE reversal.reverses_correction_id=correction.id
                    ) ELSE correction.correction_kind='CHARGE_REVERSAL' END
                ) ORDER BY correction.occurred_at,correction.id),'[]'::jsonb)
            INTO v_corrections
            FROM app.late_payment_charge_corrections AS correction
            WHERE correction.late_payment_charge_id=p_charge_id;
            v_applications:=app.late_payment_charge_application_summary(p_charge_id);
            RETURN jsonb_build_object(
                'id',v_charge.id,'event_type','LATE_PAYMENT_CHARGE',
                'property_id',v_property_id,'customer_id',v_charge.customer_id,
                'lease_id',v_lease_id,'business_date',v_business_date,
                'source_invoice',jsonb_build_object('id',v_charge.source_invoice_id),
                'decision',app.late_payment_decision_snapshot(v_charge.late_payment_decision_id),
                'original_amount',jsonb_build_object(
                    'currency','USD','minor_units',v_charge.original_amount_usd_cents),
                'adjusted_obligation',jsonb_build_object(
                    'currency','USD','minor_units',
                    v_position.adjusted_obligation_usd_cents),
                'remaining_balance',jsonb_build_object(
                    'currency','USD','minor_units',
                    v_position.remaining_balance_usd_cents),
                'application_summary',jsonb_build_object(
                    'active_total',jsonb_build_object(
                        'currency','USD','minor_units',
                        v_position.active_applications_usd_cents),
                    'payment_total',jsonb_build_object('currency','USD','minor_units',
                        v_position.payment_applied_usd_cents),
                    'credit_total',jsonb_build_object('currency','USD','minor_units',
                        v_position.credit_applied_usd_cents),
                    'items',COALESCE(v_applications->'items','[]'::jsonb)),
                'corrections',v_corrections,'payable_at',v_charge.payable_at,
                'created_at',v_charge.created_at,'created_by',v_charge.created_by
            );
        END $$;

        CREATE FUNCTION app.require_late_payment_actor(p_property_id uuid,p_actor_id uuid)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            SELECT timezone_name INTO v_timezone FROM app.properties
            WHERE id=p_property_id FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Late-payment Property was not found'
                USING ERRCODE='P4601'; END IF;
            PERFORM 1 FROM app.user_accounts
            WHERE actor_id=p_actor_id AND lifecycle_state='active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Late-payment command requires an active human actor'
                USING ERRCODE='P4606'; END IF;
            RETURN v_timezone;
        END $$;

        CREATE FUNCTION app.late_payment_command_replay(
            p_property_id uuid,p_actor_id uuid,p_action text,
            p_idempotency_key uuid,p_request_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.late_payment_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_late_payment_actor(p_property_id,p_actor_id);
            IF p_action NOT IN ('decision','correction')
                OR p_idempotency_key IS NULL
                OR p_idempotency_key='00000000-0000-0000-0000-000000000000'::uuid
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Late-payment command identity is invalid'
                USING ERRCODE='P4602'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'late-payment-command:'||p_property_id::text||':'||p_actor_id::text||':'||
                    p_action||':'||p_idempotency_key::text,0));
            SELECT * INTO v_command FROM app.late_payment_commands
            WHERE property_id=p_property_id AND actor_id=p_actor_id AND action=p_action
              AND idempotency_key=p_idempotency_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            IF v_command.request_digest<>p_request_digest THEN
                RAISE EXCEPTION 'Late-payment idempotency key was reused'
                    USING ERRCODE='P4605';
            END IF;
            RETURN jsonb_build_object(
                'status_code',v_command.response_status,'body',v_command.response_body
            );
        END $$;

        CREATE FUNCTION app.record_late_payment_command(
            p_property_id uuid,p_actor_id uuid,p_action text,p_idempotency_key uuid,
            p_request_digest text,p_target_kind text,p_target_id uuid,
            p_result_entity_id uuid,p_response_body jsonb,p_completed_at timestamptz
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            INSERT INTO app.late_payment_commands(property_id,actor_id,action,idempotency_key,
                request_digest,target_kind,target_id,result_entity_id,response_status,
                response_body,completed_at)
            VALUES (p_property_id,p_actor_id,p_action,p_idempotency_key,p_request_digest,
                p_target_kind,p_target_id,p_result_entity_id,
                CASE p_action WHEN 'decision' THEN 201 ELSE 200 END,
                p_response_body,p_completed_at);
        END $$;

        CREATE FUNCTION app.finalize_late_payment_decision(
            p_property_id uuid,p_invoice_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_request_id text,p_outcome text,
            p_approved_amount bigint,p_reason text,
            p_decision_id uuid,p_charge_id uuid,p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_response jsonb;
        DECLARE v_invoice app.invoices%ROWTYPE; v_timezone text; v_now timestamptz;
        DECLARE v_business_date date; v_balance bigint; v_default bigint;
        DECLARE v_lease_status text;
        BEGIN
            IF p_request_id IS NULL
                OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            THEN RAISE EXCEPTION 'Late-payment request identity is invalid'
                USING ERRCODE='P4602'; END IF;
            v_replay:=app.late_payment_command_replay(p_property_id,p_actor_id,'decision',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_late_payment_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Late-payment Invoice was not found'
                USING ERRCODE='P4601'; END IF;
            IF p_decision_id IS NULL OR p_decision_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_charge_id IS NULL OR p_charge_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_audit_id IS NULL OR p_audit_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_reason IS NULL OR p_reason<>btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_outcome NOT IN ('CONFIRMED_DEFAULT','REDUCED','WAIVED')
                OR p_approved_amount IS NULL OR p_approved_amount<0
                OR p_approved_amount>9000000000000000
            THEN RAISE EXCEPTION 'Late-payment Decision input is invalid'
                USING ERRCODE='P4602'; END IF;
            IF EXISTS (SELECT 1 FROM app.late_payment_decisions
                WHERE source_invoice_id=p_invoice_id)
            THEN RAISE EXCEPTION 'Late-payment Decision is already final'
                USING ERRCODE='P4603'; END IF;
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            SELECT status INTO v_lease_status FROM app.leases WHERE id=v_invoice.lease_id;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0)
            INTO v_balance FROM app.invoice_lines AS line WHERE line.invoice_id=p_invoice_id;
            v_default:=floor((v_balance::numeric+5)/10)::bigint;
            IF v_invoice.lease_id IS NULL OR v_lease_status NOT IN ('SIGNED','TERMINATED')
                OR v_invoice.status<>'UNPAID' OR v_invoice.due_date>=v_business_date
                OR v_balance<=0 OR v_balance>9000000000000000
            THEN RAISE EXCEPTION 'Invoice is not eligible for a late-payment Decision'
                USING ERRCODE='P4603'; END IF;
            IF (p_outcome='CONFIRMED_DEFAULT' AND p_approved_amount<>v_default)
                OR (p_outcome='WAIVED' AND p_approved_amount<>0)
                OR (p_outcome='REDUCED'
                    AND (p_approved_amount<=0 OR p_approved_amount>=v_default))
            THEN RAISE EXCEPTION 'Late-payment Decision amount is inconsistent'
                USING ERRCODE='P4602'; END IF;
            v_before:=app.late_payment_review_snapshot(p_invoice_id);
            INSERT INTO app.late_payment_decisions(
                id,source_invoice_id,customer_id,source_due_date,
                overdue_balance_at_assessment_usd_cents,default_rate_basis_points,
                calculated_default_amount_usd_cents,decision_outcome,
                approved_amount_usd_cents,assessed_at,finalized_at,finalized_by,reason,
                authorization_reference,calculation_trace)
            VALUES (p_decision_id,p_invoice_id,v_invoice.customer_id,v_invoice.due_date,
                v_balance,1000,v_default,p_outcome,p_approved_amount,v_now,v_now,p_actor_id,
                p_reason,'late_payment.final_decision',jsonb_build_object(
                    'formula','remaining_overdue_balance_x_10_percent',
                    'source_invoice_id',p_invoice_id,'source_due_date',v_invoice.due_date,
                    'overdue_balance_usd_cents',v_balance,'rate_basis_points',1000,
                    'rounding','HALF_UP_TO_USD_CENT','calculated_amount_usd_cents',v_default,
                    'property_timezone',v_timezone,'assessment_business_date',v_business_date));
            IF p_approved_amount>0 THEN
                INSERT INTO app.late_payment_charges(
                    id,customer_id,source_invoice_id,late_payment_decision_id,
                    original_amount_usd_cents,payable_at,created_at,created_by)
                VALUES (p_charge_id,v_invoice.customer_id,p_invoice_id,p_decision_id,
                    p_approved_amount,v_now,v_now,p_actor_id);
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.late_payment_decision_snapshot(p_decision_id);
            INSERT INTO app.audit_events(
                id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,
                correlation_id,source,outcome,authorization_evidence,linked_source_event_id,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'late_payment.decision_finalized',
                'late_payment_decision',p_decision_id,p_reason,
                'late_payment.final_decision',p_property_id,v_before,v_result,p_idempotency_key,
                'API','SUCCEEDED',jsonb_build_object(
                    'capability','late_payment.final_decision','outcome',p_outcome,
                    'approved_amount_usd_cents',p_approved_amount),p_decision_id,
                v_invoice.customer_id,v_invoice.lease_id);
            PERFORM app.record_late_payment_command(p_property_id,p_actor_id,'decision',
                p_idempotency_key,p_request_digest,'INVOICE',p_invoice_id,p_decision_id,
                jsonb_build_object('data',v_result,'meta',
                    jsonb_build_object('request_id',p_request_id)),v_now);
            v_response:=jsonb_build_object('data',v_result,'meta',
                jsonb_build_object('request_id',p_request_id));
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;

        CREATE FUNCTION app.correct_late_payment_charge(
            p_property_id uuid,p_charge_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_request_id text,p_kind text,p_amount bigint,
            p_reverses_correction_id uuid,
            p_reason text,p_correction_id uuid,p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_response jsonb;
        DECLARE v_charge app.late_payment_charges%ROWTYPE;
        DECLARE v_source app.late_payment_charge_corrections%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date;
        DECLARE v_current bigint; v_resulting bigint; v_resolved_amount bigint;
        DECLARE v_active_applications bigint; v_correlation_id uuid;
        BEGIN
            IF p_request_id IS NULL
                OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            THEN RAISE EXCEPTION 'Late-payment request identity is invalid'
                USING ERRCODE='P4602'; END IF;
            v_replay:=app.late_payment_command_replay(p_property_id,p_actor_id,'correction',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_late_payment_actor(p_property_id,p_actor_id);
            SELECT * INTO v_charge FROM app.late_payment_charges
            WHERE id=p_charge_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(v_charge.source_invoice_id)
                IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Late-payment Charge was not found'
                USING ERRCODE='P4601'; END IF;
            PERFORM 1 FROM app.invoices WHERE id=v_charge.source_invoice_id FOR UPDATE;
            IF p_correction_id IS NULL
                OR p_correction_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_audit_id IS NULL OR p_audit_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_reason IS NULL OR p_reason<>btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
                OR p_kind NOT IN ('REDUCTION','CHARGE_REVERSAL','REDUCTION_REVERSAL')
            THEN RAISE EXCEPTION 'Late-payment correction input is invalid'
                USING ERRCODE='P4602'; END IF;
            IF EXISTS (SELECT 1 FROM app.late_payment_charge_corrections
                WHERE late_payment_charge_id=p_charge_id
                  AND correction_kind='CHARGE_REVERSAL')
            THEN RAISE EXCEPTION 'A reversed Late-payment Charge is terminal'
                USING ERRCODE='P4603'; END IF;
            SELECT v_charge.original_amount_usd_cents+COALESCE(sum(
                CASE correction_kind WHEN 'REDUCTION' THEN -amount_usd_cents
                    WHEN 'CHARGE_REVERSAL' THEN -amount_usd_cents
                    ELSE amount_usd_cents END),0)
            INTO v_current FROM app.late_payment_charge_corrections
            WHERE late_payment_charge_id=p_charge_id;
            IF p_kind='REDUCTION' THEN
                IF p_amount IS NULL OR p_amount<=0 OR p_amount>=v_current
                    OR p_amount>9000000000000000 OR p_reverses_correction_id IS NOT NULL
                THEN RAISE EXCEPTION 'Late-payment reduction is invalid'
                    USING ERRCODE='P4602'; END IF;
                v_resolved_amount:=p_amount; v_resulting:=v_current-p_amount;
            ELSIF p_kind='CHARGE_REVERSAL' THEN
                IF p_amount IS NOT NULL OR p_reverses_correction_id IS NOT NULL
                    OR v_current<=0
                THEN RAISE EXCEPTION 'Late-payment Charge reversal is invalid'
                    USING ERRCODE='P4602'; END IF;
                v_resolved_amount:=v_current; v_resulting:=0;
            ELSE
                IF p_amount IS NOT NULL OR p_reverses_correction_id IS NULL THEN
                    RAISE EXCEPTION 'Late-payment reduction reversal is invalid'
                        USING ERRCODE='P4602'; END IF;
                SELECT * INTO v_source FROM app.late_payment_charge_corrections
                WHERE id=p_reverses_correction_id AND late_payment_charge_id=p_charge_id
                  AND correction_kind='REDUCTION' FOR SHARE;
                IF NOT FOUND OR EXISTS (SELECT 1 FROM app.late_payment_charge_corrections
                    WHERE reverses_correction_id=p_reverses_correction_id)
                THEN RAISE EXCEPTION 'Late-payment reduction is not active'
                    USING ERRCODE='P4603'; END IF;
                v_resolved_amount:=v_source.amount_usd_cents;
                v_resulting:=v_current+v_resolved_amount;
                IF v_resulting>v_charge.original_amount_usd_cents THEN
                    RAISE EXCEPTION 'Late-payment reduction reversal exceeds original amount'
                        USING ERRCODE='P4603'; END IF;
            END IF;
            v_active_applications:=COALESCE((
                app.late_payment_charge_application_summary(p_charge_id)
                    ->>'active_total_usd_cents')::bigint,0);
            IF v_resulting<v_active_applications THEN
                RAISE EXCEPTION 'Active applications require explicit reversal'
                    USING ERRCODE='P4608'; END IF;
            v_before:=app.late_payment_charge_snapshot(p_charge_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            v_correlation_id:=pg_catalog.md5(
                'late-payment-command:'||p_property_id::text||':'||p_actor_id::text||
                ':correction:'||p_idempotency_key::text
            )::uuid;
            INSERT INTO app.late_payment_charge_corrections(
                id,late_payment_charge_id,correction_kind,amount_usd_cents,
                reverses_correction_id,reason,previous_obligation_usd_cents,
                resulting_obligation_usd_cents,occurred_at,actor_id,
                authorization_reference,correlation_id)
            VALUES (p_correction_id,p_charge_id,p_kind,v_resolved_amount,
                p_reverses_correction_id,p_reason,v_current,v_resulting,v_now,p_actor_id,
                'late_payment.charge_correction',v_correlation_id);
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.late_payment_charge_snapshot(p_charge_id);
            INSERT INTO app.audit_events(
                id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,
                correlation_id,source,outcome,authorization_evidence,linked_source_event_id,
                customer_id,lease_id)
            SELECT p_audit_id,v_now,v_business_date,p_actor_id,
                'late_payment.charge_corrected','late_payment_charge',p_charge_id,p_reason,
                'late_payment.charge_correction',p_property_id,v_before,v_result,
                v_correlation_id,'API','SUCCEEDED',jsonb_build_object(
                    'capability','late_payment.charge_correction','kind',p_kind,
                    'amount_usd_cents',v_resolved_amount,
                    'reverses_correction_id',p_reverses_correction_id),p_correction_id,
                v_charge.customer_id,invoice.lease_id
            FROM app.invoices AS invoice WHERE invoice.id=v_charge.source_invoice_id;
            PERFORM app.record_late_payment_command(p_property_id,p_actor_id,'correction',
                p_idempotency_key,p_request_digest,'CHARGE',p_charge_id,p_correction_id,
                jsonb_build_object('data',v_result,'meta',
                    jsonb_build_object('request_id',p_request_id)),v_now);
            v_response:=jsonb_build_object('data',v_result,'meta',
                jsonb_build_object('request_id',p_request_id));
            RETURN jsonb_build_object('status_code',200,'body',v_response);
        END $$;
        """
    )
    op.execute(
        r"""
        CREATE TRIGGER late_payment_commands_append_only BEFORE UPDATE OR DELETE
            ON app.late_payment_commands FOR EACH ROW
            EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER late_payment_commands_reject_truncate BEFORE TRUNCATE
            ON app.late_payment_commands FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_invoice_storage_truncate();
        REVOKE ALL ON TABLE app.late_payment_commands
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT SELECT ON TABLE app.late_payment_commands TO prm_runtime,prm_financial;
        REVOKE ALL ON TABLE app.late_payment_charge_financial_position
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT SELECT ON TABLE app.late_payment_charge_financial_position
            TO prm_runtime,prm_financial;
        """
    )
    functions = (
        "app.late_payment_charge_property_id(uuid)",
        "app.late_payment_charge_application_summary(uuid)",
        "app.late_payment_decision_snapshot(uuid)",
        "app.late_payment_decision_snapshot_for_invoice(uuid)",
        "app.late_payment_review_snapshot(uuid)",
        "app.late_payment_charge_snapshot(uuid)",
        "app.require_late_payment_actor(uuid,uuid)",
        "app.late_payment_command_replay(uuid,uuid,text,uuid,text)",
        "app.record_late_payment_command(uuid,uuid,text,uuid,text,text,uuid,uuid,jsonb,timestamp with time zone)",
        "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid)",
        "app.correct_late_payment_charge(uuid,uuid,uuid,uuid,text,text,text,bigint,uuid,text,uuid,uuid)",
    )
    for function in functions:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.late_payment_charge_property_id(uuid),"
        "app.late_payment_charge_application_summary(uuid),"
        "app.late_payment_decision_snapshot(uuid),"
        "app.late_payment_decision_snapshot_for_invoice(uuid),"
        "app.late_payment_review_snapshot(uuid),"
        "app.late_payment_charge_snapshot(uuid) TO prm_runtime,prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.finalize_late_payment_decision(uuid,uuid,uuid,uuid,text,text,text,bigint,text,uuid,uuid,uuid),"
        "app.correct_late_payment_charge(uuid,uuid,uuid,uuid,text,text,text,bigint,uuid,text,uuid,uuid) "
        "TO prm_financial"
    )


def downgrade() -> None:
    """Refuse rollback that could erase permanent Decision and correction command evidence."""
    raise RuntimeError("Late-payment API migration is forward-only")
