# ruff: noqa: E501
"""Add the bounded human Invoice lifecycle command boundary."""

from alembic import op

revision = "20260831_36"
down_revision = "20260831_35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install idempotent, audited Invoice commands without direct runtime DML."""
    op.execute(
        r"""
        CREATE TABLE app.invoice_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (action IN ('create','correct','issue','adjust','void')),
            idempotency_key uuid NOT NULL CHECK (
                idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{64}$'),
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            response_status smallint NOT NULL CHECK (response_status IN (200,201)),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot)='object'),
            completed_at timestamptz NOT NULL,
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );
        CREATE INDEX invoice_commands_invoice_history_idx
            ON app.invoice_commands(invoice_id,completed_at,idempotency_key);

        CREATE FUNCTION app.invoice_property_id(p_invoice_id uuid)
        RETURNS uuid LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid; v_property_count integer;
        BEGIN
            SELECT unit.property_id INTO v_property_id
            FROM app.invoices AS invoice
            JOIN app.leases AS lease ON lease.id=invoice.lease_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE invoice.id=p_invoice_id;
            IF v_property_id IS NOT NULL THEN RETURN v_property_id; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.invoices WHERE id=p_invoice_id) THEN RETURN NULL; END IF;
            SELECT count(*) INTO v_property_count FROM app.properties;
            IF v_property_count<>1 THEN RETURN NULL; END IF;
            SELECT id INTO v_property_id FROM app.properties ORDER BY id LIMIT 1;
            RETURN v_property_id;
        END $$;

        CREATE FUNCTION app.invoice_resource_snapshot(p_invoice_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_property_id uuid; v_timezone text;
        DECLARE v_adjusted bigint; v_lines jsonb; v_adjustments jsonb; v_void jsonb;
        BEGIN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            v_property_id:=app.invoice_property_id(p_invoice_id);
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=v_property_id;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(line.id)),0),
                COALESCE(jsonb_agg(jsonb_build_object(
                    'id',line.id,'sequence',line.line_sequence,'category',line.category,
                    'description',line.description,
                    'original_amount',jsonb_build_object(
                        'currency','USD','minor_units',line.amount_usd_cents),
                    'adjusted_amount',jsonb_build_object('currency','USD','minor_units',
                        app.invoice_adjusted_line_obligation(line.id)),
                    'outstanding_balance',jsonb_build_object('currency','USD','minor_units',
                        CASE WHEN v_invoice.status IN ('DRAFT','VOID') THEN 0
                            ELSE app.invoice_adjusted_line_obligation(line.id) END),
                    'period',CASE WHEN line.period_start IS NULL THEN NULL ELSE
                        jsonb_build_object('start',line.period_start,'end',line.period_end,
                            'end_inclusive',true) END,
                    'source',jsonb_build_object(
                        'type',CASE line.category
                            WHEN 'RENT' THEN 'LEASE'
                            WHEN 'UTILITIES' THEN 'UTILITY_CONSUMPTION_PERIOD'
                            WHEN 'SERVICE_CHARGES' THEN 'PROPERTY_SERVICE'
                            ELSE 'AUTHORIZED_NONRECURRING_OBLIGATION' END,
                        'id',COALESCE(line.source_lease_id,line.utility_consumption_period_id,
                            line.property_service_id,line.authorized_obligation_id)),
                    'calculation_evidence',line.calculation_trace,
                    'created_at',line.created_at,'created_by',line.created_by
                ) ORDER BY line.line_sequence,line.id),'[]'::jsonb)
            INTO v_adjusted,v_lines FROM app.invoice_lines AS line
            WHERE line.invoice_id=p_invoice_id;
            SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'id',adjustment.id,'invoice_line_id',adjustment.invoice_line_id,
                'type',adjustment.adjustment_type,
                'amount',jsonb_build_object('currency','USD',
                    'minor_units',adjustment.amount_usd_cents),
                'source_reference',adjustment.source_reference,'reason',adjustment.reason,
                'occurred_at',adjustment.occurred_at,'actor_id',adjustment.actor_id,
                'authorization_reference',adjustment.authorization_reference,
                'reversed',reversal.id IS NOT NULL,
                'reversal',CASE WHEN reversal.id IS NULL THEN NULL ELSE jsonb_build_object(
                    'id',reversal.id,'reason',reversal.reason,
                    'occurred_at',reversal.occurred_at,'actor_id',reversal.actor_id,
                    'authorization_reference',reversal.authorization_reference) END
            ) ORDER BY adjustment.occurred_at,adjustment.id),'[]'::jsonb)
            INTO v_adjustments FROM app.invoice_adjustments AS adjustment
            LEFT JOIN app.invoice_adjustment_reversals AS reversal
                ON reversal.invoice_adjustment_id=adjustment.id
            WHERE adjustment.invoice_id=p_invoice_id;
            SELECT jsonb_build_object('id',event.id,'reason',event.reason,
                'occurred_at',event.occurred_at,'actor_id',event.actor_id,
                'authorization_reference',event.authorization_reference)
            INTO v_void FROM app.invoice_void_events AS event
            WHERE event.invoice_id=p_invoice_id;
            RETURN jsonb_build_object(
                'id',v_invoice.id,'invoice_number',v_invoice.invoice_number,
                'property_id',v_property_id,'customer_id',v_invoice.customer_id,
                'lease_id',v_invoice.lease_id,'category',v_invoice.primary_category,
                'status',v_invoice.status,'invoice_date',v_invoice.invoice_date,
                'due_date',v_invoice.due_date,'due_date_rule',v_invoice.due_date_rule,
                'due_date_source',v_invoice.due_date_source,
                'property_timezone',v_timezone,
                'billing_period',CASE WHEN v_invoice.billing_period_start IS NULL THEN NULL
                    ELSE jsonb_build_object('start',v_invoice.billing_period_start,
                        'end',v_invoice.billing_period_end,'end_inclusive',true) END,
                'original_total',jsonb_build_object('currency','USD',
                    'minor_units',v_invoice.original_total_usd_cents),
                'adjusted_total',jsonb_build_object('currency','USD','minor_units',v_adjusted),
                'active_application_total',jsonb_build_object('currency','USD','minor_units',0),
                'outstanding_balance',jsonb_build_object('currency','USD','minor_units',
                    CASE WHEN v_invoice.status IN ('DRAFT','VOID') THEN 0 ELSE v_adjusted END),
                'lines',v_lines,'adjustments',v_adjustments,'void_event',v_void,
                'issued_at',v_invoice.issued_at,'issued_by',v_invoice.issued_by,
                'created_at',v_invoice.created_at,'created_by',v_invoice.created_by,
                'updated_at',v_invoice.updated_at,'updated_by',v_invoice.updated_by,
                'version',v_invoice.version
            );
        END $$;

        CREATE FUNCTION app.require_invoice_command_actor(p_property_id uuid,p_actor_id uuid)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            SELECT timezone_name INTO v_timezone FROM app.properties
            WHERE id=p_property_id FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Invoice Property was not found'
                USING ERRCODE='P4501'; END IF;
            PERFORM 1 FROM app.user_accounts
            WHERE actor_id=p_actor_id AND lifecycle_state='active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Invoice command requires an active human actor'
                USING ERRCODE='P4506'; END IF;
            RETURN v_timezone;
        END $$;

        CREATE FUNCTION app.invoice_command_replay(
            p_property_id uuid,p_actor_id uuid,p_action text,
            p_idempotency_key uuid,p_request_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_command app.invoice_commands%ROWTYPE;
        BEGIN
            PERFORM app.require_invoice_command_actor(p_property_id,p_actor_id);
            IF p_action NOT IN ('create','correct','issue','adjust','void')
                OR p_idempotency_key IS NULL
                OR p_idempotency_key='00000000-0000-0000-0000-000000000000'::uuid
                OR p_request_digest IS NULL
                OR p_request_digest !~ '^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Invoice command identity is invalid'
                USING ERRCODE='P4502'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'invoice-command:'||p_property_id::text||':'||p_actor_id::text||':'||
                    p_action||':'||p_idempotency_key::text,0));
            SELECT * INTO v_command FROM app.invoice_commands
            WHERE property_id=p_property_id AND actor_id=p_actor_id AND action=p_action
              AND idempotency_key=p_idempotency_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            IF v_command.request_digest<>p_request_digest THEN
                RAISE EXCEPTION 'Invoice idempotency key was reused'
                    USING ERRCODE='P4505';
            END IF;
            RETURN v_command.result_snapshot;
        END $$;

        CREATE FUNCTION app.record_invoice_command(
            p_property_id uuid,p_actor_id uuid,p_action text,p_idempotency_key uuid,
            p_request_digest text,p_invoice_id uuid,p_response_status smallint,
            p_result_snapshot jsonb,p_completed_at timestamptz
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            INSERT INTO app.invoice_commands(property_id,actor_id,action,idempotency_key,
                request_digest,invoice_id,response_status,result_snapshot,completed_at)
            VALUES (p_property_id,p_actor_id,p_action,p_idempotency_key,p_request_digest,
                p_invoice_id,p_response_status,p_result_snapshot,p_completed_at);
        END $$;

        CREATE FUNCTION app.create_invoice_draft(
            p_property_id uuid,p_obligation_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_invoice_id uuid,p_line_id uuid,p_audit_id uuid,
            p_correlation_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_result jsonb; v_source app.authorized_nonrecurring_obligations%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date; v_invoice_number text;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'create',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            SELECT * INTO v_source FROM app.authorized_nonrecurring_obligations
            WHERE id=p_obligation_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorized Invoice source was not found'
                USING ERRCODE='P4501'; END IF;
            IF v_source.authorized_at>v_now
                OR (v_source.lease_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
                    WHERE lease.id=v_source.lease_id AND unit.property_id=p_property_id))
            THEN RAISE EXCEPTION 'Authorized Invoice source is not valid for this Property'
                USING ERRCODE='P4502'; END IF;
            IF EXISTS (SELECT 1 FROM app.active_invoice_source_claims
                WHERE authorized_obligation_id=p_obligation_id)
            THEN RAISE EXCEPTION 'Authorized Invoice source is already billed'
                USING ERRCODE='P4503'; END IF;
            v_invoice_number:='INV-'||to_char(v_business_date,'YYYYMMDD')||'-'||
                upper(substr(replace(p_invoice_id::text,'-',''),1,12));
            INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,
                status,invoice_date,due_date,original_total_usd_cents,due_date_rule,
                due_date_source,created_at,created_by,updated_at,updated_by)
            VALUES (p_invoice_id,v_invoice_number,v_source.customer_id,v_source.lease_id,
                v_source.category,'DRAFT',v_business_date,v_source.governing_due_date,
                v_source.authorized_amount_usd_cents,'GOVERNING_SOURCE',v_source.due_date_source,
                v_now,p_actor_id,v_now,p_actor_id);
            INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,
                amount_usd_cents,authorized_obligation_id,calculation_trace,created_at,
                last_changed_at,created_by,last_changed_by)
            VALUES (p_line_id,p_invoice_id,1,v_source.category,v_source.description,
                v_source.authorized_amount_usd_cents,p_obligation_id,
                jsonb_build_object('formula','authorized_source_exact_amount',
                    'authorized_obligation_id',p_obligation_id,
                    'authorized_amount_usd_cents',v_source.authorized_amount_usd_cents,
                    'source_reference',v_source.source_reference),
                v_now,v_now,p_actor_id,p_actor_id);
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.created','invoice',
                p_invoice_id,'Invoice DRAFT created from authorized obligation',
                'invoices.create',p_property_id,'{}'::jsonb,v_result,p_correlation_id,'API',
                'SUCCEEDED',jsonb_build_object('capability','invoices.create',
                    'authorized_obligation_id',p_obligation_id),v_source.customer_id,v_source.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'create',
                p_idempotency_key,p_request_digest,p_invoice_id,201::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.correct_invoice_draft(
            p_property_id uuid,p_invoice_id uuid,p_obligation_id uuid,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text,p_expected_version integer,
            p_reason text,p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb;
        DECLARE v_invoice app.invoices%ROWTYPE; v_source app.authorized_nonrecurring_obligations%ROWTYPE;
        DECLARE v_line_id uuid; v_timezone text; v_now timestamptz; v_business_date date;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'correct',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504';
            END IF;
            SELECT id INTO v_line_id FROM app.invoice_lines
            WHERE invoice_id=p_invoice_id ORDER BY line_sequence,id LIMIT 1;
            IF v_invoice.status<>'DRAFT' OR v_invoice.originating_billing_run_attempt_id IS NOT NULL
                OR v_invoice.primary_category NOT IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')
                OR (SELECT count(*) FROM app.invoice_lines WHERE invoice_id=p_invoice_id)<>1
                OR NOT EXISTS (SELECT 1 FROM app.invoice_lines WHERE id=v_line_id
                    AND authorized_obligation_id IS NOT NULL)
                OR p_reason IS NULL OR p_reason<>btrim(p_reason) OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Only an authorized-source DRAFT can be corrected'
                USING ERRCODE='P4502'; END IF;
            SELECT * INTO v_source FROM app.authorized_nonrecurring_obligations
            WHERE id=p_obligation_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorized Invoice source was not found'
                USING ERRCODE='P4501'; END IF;
            IF EXISTS (SELECT 1 FROM app.active_invoice_source_claims
                WHERE authorized_obligation_id=p_obligation_id AND invoice_line_id<>v_line_id)
                OR EXISTS (SELECT 1 FROM app.invoice_lines WHERE id=v_line_id
                    AND authorized_obligation_id=p_obligation_id)
                OR (v_source.lease_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
                    WHERE lease.id=v_source.lease_id AND unit.property_id=p_property_id))
            THEN RAISE EXCEPTION 'Replacement Invoice source is invalid or already billed'
                USING ERRCODE='P4503'; END IF;
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            IF v_source.authorized_at>v_now
            THEN RAISE EXCEPTION 'Replacement Invoice source chronology is invalid'
                USING ERRCODE='P4502'; END IF;
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            PERFORM set_config('app.draft_correction_actor_id',p_actor_id::text,true);
            PERFORM set_config('app.draft_correction_reason',p_reason,true);
            UPDATE app.invoices SET customer_id=v_source.customer_id,lease_id=v_source.lease_id,
                primary_category=v_source.category,due_date=v_source.governing_due_date,
                original_total_usd_cents=v_source.authorized_amount_usd_cents,
                due_date_rule='GOVERNING_SOURCE',due_date_source=v_source.due_date_source,
                version=version+1,updated_at=v_now,updated_by=p_actor_id WHERE id=p_invoice_id;
            UPDATE app.invoice_lines SET category=v_source.category,description=v_source.description,
                amount_usd_cents=v_source.authorized_amount_usd_cents,
                authorized_obligation_id=p_obligation_id,
                calculation_trace=jsonb_build_object('formula','authorized_source_exact_amount',
                    'authorized_obligation_id',p_obligation_id,
                    'authorized_amount_usd_cents',v_source.authorized_amount_usd_cents,
                    'source_reference',v_source.source_reference),last_changed_by=p_actor_id
            WHERE id=v_line_id;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.draft_corrected',
                'invoice',p_invoice_id,p_reason,'invoices.create',p_property_id,v_before,
                v_result,p_idempotency_key,'API','SUCCEEDED',jsonb_build_object(
                    'capability','invoices.create','authorized_obligation_id',p_obligation_id),
                v_source.customer_id,v_source.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'correct',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.issue_invoice(
            p_property_id uuid,p_invoice_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_expected_version integer,p_audit_id uuid,p_correlation_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_invoice app.invoices%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'issue',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            IF v_invoice.status<>'DRAFT' THEN RAISE EXCEPTION 'Only a DRAFT Invoice may be issued'
                USING ERRCODE='P4502'; END IF;
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            UPDATE app.invoices SET status='UNPAID',issued_at=v_now,issued_by=p_actor_id,
                version=version+1,updated_at=v_now,updated_by=p_actor_id WHERE id=p_invoice_id;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.issued','invoice',
                p_invoice_id,'Invoice issued','invoices.issue',p_property_id,v_before,v_result,
                p_correlation_id,'API','SUCCEEDED',jsonb_build_object('capability','invoices.issue'),
                v_invoice.customer_id,v_invoice.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'issue',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.adjust_invoice(
            p_property_id uuid,p_invoice_id uuid,p_line_id uuid,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text,p_expected_version integer,
            p_adjustment_type text,p_amount bigint,p_source_reference text,p_reason text,
            p_adjustment_id uuid,p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_invoice app.invoices%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date; v_resulting bigint;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'adjust',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            IF v_invoice.status NOT IN ('UNPAID','PAID')
                OR NOT EXISTS (SELECT 1 FROM app.invoice_lines
                    WHERE id=p_line_id AND invoice_id=p_invoice_id)
                OR p_adjustment_type NOT IN ('DEBIT','CREDIT') OR p_amount<=0
                OR p_source_reference IS NULL OR p_source_reference<>btrim(p_source_reference)
                OR length(p_source_reference) NOT BETWEEN 1 AND 500
                OR p_reason IS NULL OR p_reason<>btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Invoice Adjustment input is invalid'
                USING ERRCODE='P4502'; END IF;
            SELECT app.invoice_adjusted_line_obligation(p_line_id)+
                CASE p_adjustment_type WHEN 'DEBIT' THEN p_amount ELSE -p_amount END
                INTO v_resulting;
            IF v_resulting<0 THEN RAISE EXCEPTION 'Invoice line balance cannot be negative'
                USING ERRCODE='P4502'; END IF;
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            INSERT INTO app.invoice_adjustments(id,invoice_id,invoice_line_id,adjustment_type,
                amount_usd_cents,source_reference,reason,occurred_at,actor_id,
                authorization_reference)
            VALUES (p_adjustment_id,p_invoice_id,p_line_id,p_adjustment_type,p_amount,
                p_source_reference,p_reason,v_now,p_actor_id,'invoices.adjust');
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(id)),0) INTO v_resulting
                FROM app.invoice_lines WHERE invoice_id=p_invoice_id;
            UPDATE app.invoices SET status=CASE WHEN v_resulting=0 THEN 'PAID' ELSE 'UNPAID' END,
                version=version+1,updated_at=v_now,updated_by=p_actor_id WHERE id=p_invoice_id;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                linked_source_event_id,customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.adjusted','invoice',
                p_invoice_id,p_reason,'invoices.adjust',p_property_id,v_before,v_result,
                p_idempotency_key,'API','SUCCEEDED',jsonb_build_object(
                    'capability','invoices.adjust','source_reference',p_source_reference,
                    'invoice_line_id',p_line_id),p_adjustment_id,v_invoice.customer_id,
                v_invoice.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'adjust',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.void_invoice(
            p_property_id uuid,p_invoice_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text,p_expected_version integer,p_reason text,p_void_event_id uuid,
            p_audit_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_before jsonb; v_result jsonb; v_invoice app.invoices%ROWTYPE;
        DECLARE v_timezone text; v_now timestamptz; v_business_date date;
        BEGIN
            v_replay:=app.invoice_command_replay(p_property_id,p_actor_id,'void',
                p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_timezone:=app.require_invoice_command_actor(p_property_id,p_actor_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=p_invoice_id FOR UPDATE;
            IF NOT FOUND OR app.invoice_property_id(p_invoice_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Invoice was not found' USING ERRCODE='P4501'; END IF;
            IF p_expected_version IS NULL OR v_invoice.version<>p_expected_version THEN
                RAISE EXCEPTION 'Invoice version:%',v_invoice.version USING ERRCODE='P4504'; END IF;
            IF v_invoice.status NOT IN ('DRAFT','UNPAID')
                OR v_invoice.originating_billing_run_attempt_id IS NOT NULL
                OR p_reason IS NULL OR p_reason<>btrim(p_reason)
                OR length(p_reason) NOT BETWEEN 1 AND 500
                OR EXISTS (SELECT 1 FROM app.invoice_adjustments AS adjustment
                    LEFT JOIN app.invoice_adjustment_reversals AS reversal
                        ON reversal.invoice_adjustment_id=adjustment.id
                    WHERE adjustment.invoice_id=p_invoice_id AND reversal.id IS NULL)
                OR EXISTS (SELECT 1 FROM app.late_payment_charges AS charge
                    WHERE charge.source_invoice_id=p_invoice_id AND NOT EXISTS (
                        SELECT 1 FROM app.late_payment_charge_corrections AS correction
                        WHERE correction.late_payment_charge_id=charge.id
                          AND correction.correction_kind='CHARGE_REVERSAL'))
            THEN RAISE EXCEPTION 'Invoice VOID dependencies are not resolved'
                USING ERRCODE='P4502'; END IF;
            v_before:=app.invoice_resource_snapshot(p_invoice_id);
            v_now:=clock_timestamp(); v_business_date:=timezone(v_timezone,v_now)::date;
            UPDATE app.invoices SET status='VOID',version=version+1,updated_at=v_now,
                updated_by=p_actor_id WHERE id=p_invoice_id;
            INSERT INTO app.invoice_void_events(id,invoice_id,reason,occurred_at,actor_id,
                authorization_reference)
            VALUES (p_void_event_id,p_invoice_id,p_reason,v_now,p_actor_id,'invoices.void');
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.invoice_resource_snapshot(p_invoice_id);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,
                entity_id,reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,authorization_evidence,
                linked_source_event_id,customer_id,lease_id)
            VALUES (p_audit_id,v_now,v_business_date,p_actor_id,'invoice.voided','invoice',
                p_invoice_id,p_reason,'invoices.void',p_property_id,v_before,v_result,
                p_idempotency_key,'API','SUCCEEDED',jsonb_build_object(
                    'capability','invoices.void','dependencies_resolved',true),p_void_event_id,
                v_invoice.customer_id,v_invoice.lease_id);
            PERFORM app.record_invoice_command(p_property_id,p_actor_id,'void',
                p_idempotency_key,p_request_digest,p_invoice_id,200::smallint,v_result,v_now);
            RETURN v_result;
        END $$;
        """
    )
    op.execute(
        r"""
        CREATE TRIGGER invoice_commands_append_only BEFORE UPDATE OR DELETE
            ON app.invoice_commands FOR EACH ROW
            EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER invoice_commands_reject_truncate BEFORE TRUNCATE
            ON app.invoice_commands FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_invoice_storage_truncate();
        REVOKE ALL ON TABLE app.invoice_commands
            FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        GRANT SELECT ON TABLE app.invoice_commands TO prm_runtime,prm_financial;
        """
    )
    functions = (
        "app.invoice_property_id(uuid)",
        "app.invoice_resource_snapshot(uuid)",
        "app.require_invoice_command_actor(uuid,uuid)",
        "app.invoice_command_replay(uuid,uuid,text,uuid,text)",
        "app.record_invoice_command(uuid,uuid,text,uuid,text,uuid,smallint,jsonb,timestamp with time zone)",
        "app.create_invoice_draft(uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,uuid)",
        "app.correct_invoice_draft(uuid,uuid,uuid,uuid,uuid,text,integer,text,uuid)",
        "app.issue_invoice(uuid,uuid,uuid,uuid,text,integer,uuid,uuid)",
        "app.adjust_invoice(uuid,uuid,uuid,uuid,uuid,text,integer,text,bigint,text,text,uuid,uuid)",
        "app.void_invoice(uuid,uuid,uuid,uuid,text,integer,text,uuid,uuid)",
    )
    for function in functions:
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.invoice_property_id(uuid),"
        "app.invoice_resource_snapshot(uuid) TO prm_runtime,prm_financial"
    )
    for function in functions[5:]:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")


def downgrade() -> None:
    """Refuse rollback that could erase Invoice command and audit evidence."""
    raise RuntimeError("Invoice lifecycle API migration is forward-only")
