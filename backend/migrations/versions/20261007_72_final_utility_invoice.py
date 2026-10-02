# ruff: noqa: E501
"""Create the final Utility Invoice at move-out and the explicit NOT_MOVED_IN catch-up Invoice.

Additive only. Both commands create one off-cycle Utility Invoice from existing consumption
periods, propose the issue date plus the Property's configured days as its Due Date (with an
authorized override and reason through the existing issue command) and never touch a period that
already has an Invoice line.
"""

from alembic import op

revision = "20261007_72"
down_revision = "20261006_71"
branch_labels = None
depends_on = None

FINAL = "app.utility_final_invoice_create(uuid,uuid,uuid,uuid,text,jsonb,text)"
CATCH_UP = "app.utility_catch_up_invoice_create(uuid,uuid,uuid,uuid,text,jsonb,text)"
BUILD = "app.utility_invoice_build(uuid,uuid,uuid,uuid,uuid,text,uuid[],date,text)"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.utility_invoice_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            action text NOT NULL CHECK(action IN ('FINAL','CATCH_UP')),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            final_input_event_id uuid REFERENCES app.move_out_final_input_events(id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            CHECK((action='FINAL')=(final_input_event_id IS NOT NULL)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );
        CREATE UNIQUE INDEX utility_invoice_commands_one_final_per_event
            ON app.utility_invoice_commands(final_input_event_id) WHERE action='FINAL';

        -- One DRAFT Utility Invoice with one line per consumption period, issued at once through
        -- the existing issue command so the Due Date rule, override audit and chronology are shared.
        CREATE FUNCTION app.utility_invoice_build(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_invoice uuid,p_kind text,p_periods uuid[],p_due_date date,p_due_reason text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_l app.leases%ROWTYPE; v_tz text; v_now timestamptz; v_bd date; v_gen timestamptz;
            v_pid uuid; v_period app.utility_consumption_periods%ROWTYPE; v_prev jsonb; v_lines jsonb:='[]'::jsonb;
            v_e jsonb; v_seq bigint; v_total bigint:=0; v_min date; v_max date; v_issue jsonb;
        BEGIN
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease;
            SELECT timezone_name INTO STRICT v_tz FROM app.properties WHERE id=p_property;
            v_now:=clock_timestamp(); v_bd:=timezone(v_tz,v_now)::date; v_gen:=v_bd::timestamp AT TIME ZONE v_tz;
            FOREACH v_pid IN ARRAY p_periods LOOP
                SELECT * INTO STRICT v_period FROM app.utility_consumption_periods WHERE id=v_pid;
                v_prev:=app.preview_utility_calculation(p_property,'CONSUMPTION_PERIOD',v_pid,v_gen,p_actor);
                IF v_prev->>'status'='PENDING_FUTURE_ACTUAL_BASIS' OR (v_prev->>'amount_usd_cents')::bigint<=0 THEN
                    CONTINUE;
                END IF;
                v_lines:=v_lines||jsonb_build_array(jsonb_build_object('period_id',v_pid,'utility_type',v_period.utility_type,
                    'start',v_period.start_date,'end',v_period.end_date,'preview',v_prev));
            END LOOP;
            IF jsonb_array_length(v_lines)=0 THEN
                RAISE EXCEPTION 'UTILITY_NOTHING_TO_BILL' USING ERRCODE='P5N02';
            END IF;
            SELECT sum((e->'preview'->>'amount_usd_cents')::bigint),min((e->>'start')::date),max((e->>'end')::date)
                INTO v_total,v_min,v_max FROM jsonb_array_elements(v_lines) AS e;
            INSERT INTO app.invoices(id,invoice_number,customer_id,lease_id,primary_category,status,invoice_date,due_date,
                billing_period_start,billing_period_end,original_total_usd_cents,due_date_rule,due_date_source,version,
                created_at,created_by,updated_at,updated_by)
            VALUES(p_invoice,'UTIL-'||p_kind||'-'||to_char(v_bd,'YYYYMMDD')||'-'||substr(replace(p_invoice::text,'-',''),1,12),
                v_l.primary_tenant_id,p_lease,'UTILITIES','DRAFT',v_bd,NULL,v_min,v_max,v_total,
                'ONE_TIME_ISSUE_PLUS_CONFIGURED_DAYS','BR-UTIL-021',1,v_now,p_actor,v_now,p_actor);
            FOR v_e,v_seq IN SELECT value,ordinality FROM jsonb_array_elements(v_lines) WITH ORDINALITY LOOP
                INSERT INTO app.invoice_lines(id,invoice_id,line_sequence,category,description,amount_usd_cents,period_start,
                    period_end,source_lease_id,utility_consumption_period_id,utility_rate_id,quantity,unit_rate_usd,
                    calculation_trace,created_at,last_changed_at,created_by,last_changed_by)
                VALUES(md5(p_invoice::text||'/line/'||(v_e->>'period_id'))::uuid,p_invoice,v_seq::smallint,'UTILITIES',
                    CASE v_e->>'utility_type' WHEN 'ELECTRICITY' THEN 'Electricity' ELSE 'Water' END,
                    (v_e->'preview'->>'amount_usd_cents')::bigint,(v_e->>'start')::date,(v_e->>'end')::date,p_lease,
                    (v_e->>'period_id')::uuid,(v_e->'preview'->>'rate_id')::uuid,
                    (v_e->'preview'->>'consumption_quantity')::numeric(20,6),(v_e->'preview'->>'rate_usd_per_unit')::numeric(20,8),
                    (v_e->'preview')||jsonb_build_object('responsible_customer_id',v_l.primary_tenant_id,
                        'responsible_lease_id',p_lease,'unit_id',v_l.unit_id,'billing_kind',p_kind,
                        'rate_effective_date',v_e->'preview'->>'rate_effective_date'),
                    v_now,v_now,p_actor,p_actor);
            END LOOP;
            v_issue:=app.issue_invoice(p_property,p_invoice,p_actor,
                md5(p_key::text||'/utility-invoice-issue')::uuid,
                encode(sha256(convert_to(p_key::text||'/utility-invoice-issue-digest','UTF8')),'hex'),
                1,gen_random_uuid(),gen_random_uuid(),p_due_date,p_due_reason);
            RETURN jsonb_build_object('invoice',v_issue,'total_usd_cents',v_total,'lines',v_lines);
        END $$;

        CREATE FUNCTION app.utility_final_invoice_create(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_c app.utility_invoice_commands%ROWTYPE; v_l app.leases%ROWTYPE; v_fin app.move_out_final_input_events%ROWTYPE;
            v_item app.move_out_final_input_items%ROWTYPE; v_invoice uuid; v_final uuid; v_due date; v_reason text;
            v_start_id uuid; v_start_date date; v_last_end date; v_last_reading uuid; v_start_value numeric; v_end_value numeric;
            v_created uuid[]:=ARRAY[]::uuid[]; v_periods uuid[]; v_built jsonb; v_audit uuid; v_response jsonb;
            v_now timestamptz; v_tz text; v_key text; v_responsibility_start date; v_new uuid;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE NOWAIT;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE NOWAIT;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Final Utility Invoice intent is invalid' USING ERRCODE='P5N02'; END IF;
            IF NOT pg_try_advisory_xact_lock(hashtextextended(p_property::text||'|'||p_actor::text||'|utility-invoice|'||p_key::text,0))
            THEN RAISE EXCEPTION 'Final Utility Invoice command is in use' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_c FROM app.utility_invoice_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_c.action<>'FINAL' OR v_c.lease_id IS DISTINCT FROM p_lease OR v_c.request_digest IS DISTINCT FROM p_digest
                    OR v_c.request_intent IS DISTINCT FROM p_intent
                THEN RAISE EXCEPTION 'Utility Invoice key was reused' USING ERRCODE='P5N05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_c.response_body);
            END IF;
            IF p_intent-ARRAY['invoice_id','final_input_event_id','due_date','due_date_reason']<>'{}'::jsonb
                OR NOT p_intent?&ARRAY['invoice_id','final_input_event_id','due_date','due_date_reason']
                OR jsonb_typeof(p_intent->'invoice_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'final_input_event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'due_date') NOT IN ('string','null')
                OR jsonb_typeof(p_intent->'due_date_reason') NOT IN ('string','null')
                OR (jsonb_typeof(p_intent->'due_date')='null')<>(jsonb_typeof(p_intent->'due_date_reason')='null')
                OR (jsonb_typeof(p_intent->'due_date_reason')='string' AND NOT app.lease_notice_text_valid(p_intent->>'due_date_reason',500))
            THEN RAISE EXCEPTION 'Final Utility Invoice fields are invalid' USING ERRCODE='P5N02'; END IF;
            BEGIN
                v_invoice:=(p_intent->>'invoice_id')::uuid; v_final:=(p_intent->>'final_input_event_id')::uuid;
                v_due:=(p_intent->>'due_date')::date; v_reason:=p_intent->>'due_date_reason';
            EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow THEN
                RAISE EXCEPTION 'Final Utility Invoice identity or date is invalid' USING ERRCODE='P5N02';
            END;
            IF v_invoice='00000000-0000-0000-0000-000000000000' OR v_final='00000000-0000-0000-0000-000000000000'
                OR (v_due IS NOT NULL AND NOT isfinite(v_due))
            THEN RAISE EXCEPTION 'Final Utility Invoice identity or date is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease;
            SELECT timezone_name INTO STRICT v_tz FROM app.properties WHERE id=p_property;
            FOR v_key IN SELECT key FROM unnest(ARRAY['utility-invoice:'||p_lease::text,
                'utility-unit-type:'||v_l.unit_id::text||':'||'ELECTRICITY',
                'utility-unit-type:'||v_l.unit_id::text||':'||'WATER']) keys(key) ORDER BY key LOOP
                IF NOT pg_try_advisory_xact_lock(hashtextextended(v_key,0))
                THEN RAISE EXCEPTION 'Final Utility Invoice source is in use' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease FOR SHARE NOWAIT;
            SELECT * INTO v_fin FROM app.move_out_final_input_events WHERE id=v_final AND lease_id=p_lease AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Final Utility input event was not found' USING ERRCODE='P5N01'; END IF;
            IF v_l.status<>'TERMINATED' THEN RAISE EXCEPTION 'UTILITY_LEASE_NOT_TERMINATED' USING ERRCODE='P5N02'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=p_lease AND customer_id=v_l.primary_tenant_id)
            THEN RAISE EXCEPTION 'UTILITY_NOT_MOVED_IN' USING ERRCODE='P5N02'; END IF;
            IF EXISTS(SELECT 1 FROM app.move_out_final_input_events WHERE supersedes_event_id=v_final)
                OR EXISTS(SELECT 1 FROM app.physical_move_out_events WHERE supersedes_event_id=v_fin.move_out_event_id)
                OR EXISTS(SELECT 1 FROM app.utility_invoice_commands WHERE final_input_event_id=v_final)
                OR EXISTS(SELECT 1 FROM app.invoices WHERE id=v_invoice)
            THEN RAISE EXCEPTION 'Final Utility Invoice source changed' USING ERRCODE='P5N03'; END IF;
            IF EXISTS(SELECT 1 FROM app.move_out_final_input_items WHERE event_id=v_final AND resolution='UNRESOLVED')
            THEN RAISE EXCEPTION 'UTILITY_UNRESOLVED_FINAL_INPUT' USING ERRCODE='P5N02'; END IF;
            v_responsibility_start:=COALESCE(app.utility_baseline_boundary(p_lease),v_l.start_date);
            PERFORM app.lock_utility_property_type(p_property,'ELECTRICITY');
            PERFORM app.lock_utility_property_type(p_property,'WATER');
            PERFORM app.lock_utility_unit_type(v_l.unit_id,'ELECTRICITY');
            PERFORM app.lock_utility_unit_type(v_l.unit_id,'WATER');
            FOR v_item IN SELECT * FROM app.move_out_final_input_items WHERE event_id=v_final AND resolution='READING' ORDER BY meter_id LOOP
                v_last_end:=NULL; v_last_reading:=NULL; v_start_id:=NULL; v_start_date:=NULL;
                SELECT period.end_date,period.end_reading_id INTO v_last_end,v_last_reading
                FROM app.utility_consumption_periods AS period JOIN app.utility_readings AS r ON r.id=period.end_reading_id
                WHERE period.unit_id=v_l.unit_id AND period.utility_type=v_item.utility_type
                    AND period.calculation_kind='ACTUAL' AND r.meter_id=v_item.meter_id
                ORDER BY period.end_date DESC LIMIT 1;
                IF v_last_end IS NOT NULL AND v_last_end>=v_item.reading_date THEN CONTINUE; END IF;
                IF v_last_reading IS NOT NULL THEN
                    v_start_id:=v_last_reading;
                ELSE
                    SELECT bi.reading_id INTO v_start_id
                    FROM app.utility_baseline_items AS bi JOIN app.utility_baseline_events AS be ON be.id=bi.event_id
                    WHERE be.lease_id=p_lease AND bi.meter_id=v_item.meter_id
                        AND NOT EXISTS(SELECT 1 FROM app.utility_baseline_events AS s WHERE s.supersedes_event_id=be.id);
                    IF v_start_id IS NULL THEN
                        SELECT r.id INTO v_start_id FROM app.utility_readings AS r
                        JOIN app.utility_meters AS m ON m.id=r.meter_id
                        WHERE r.meter_id=v_item.meter_id AND r.validated_at IS NOT NULL
                            AND m.installed_date>=v_responsibility_start
                        ORDER BY r.reading_date,r.id LIMIT 1;
                    END IF;
                END IF;
                IF v_start_id IS NOT NULL THEN
                    SELECT reading_date,app.utility_reading_effective_value(id) INTO v_start_date,v_start_value
                    FROM app.utility_readings WHERE id=v_start_id AND validated_at IS NOT NULL;
                END IF;
                IF v_start_id IS NULL OR v_start_date IS NULL OR v_start_date>=v_item.reading_date
                THEN RAISE EXCEPTION 'UTILITY_START_READING_MISSING' USING ERRCODE='P5N02'; END IF;
                IF EXISTS(SELECT 1 FROM app.utility_readings AS r WHERE r.meter_id=v_item.meter_id AND r.validated_at IS NOT NULL
                    AND r.reading_date>v_start_date AND r.reading_date<v_item.reading_date)
                THEN RAISE EXCEPTION 'UTILITY_EARLIER_READING_NOT_FINALIZED' USING ERRCODE='P5N02'; END IF;
                v_end_value:=app.utility_reading_effective_value(v_item.reading_id);
                v_new:=gen_random_uuid();
                INSERT INTO app.utility_consumption_periods(id,unit_id,utility_type,start_date,end_date,start_reading_id,end_reading_id,
                    calculation_kind,consumption_quantity,calculation_trace,finalized_at,finalized_by)
                VALUES(v_new,v_l.unit_id,v_item.utility_type,v_start_date+1,v_item.reading_date,v_start_id,v_item.reading_id,'ACTUAL',
                    v_end_value-v_start_value,
                    jsonb_build_object('meter_id',v_item.meter_id,'start_reading_id',v_start_id,'start_reading_date',v_start_date,
                        'start_effective_value',v_start_value,'end_reading_id',v_item.reading_id,
                        'end_reading_date',v_item.reading_date,'end_effective_value',v_end_value,
                        'final_input_event_id',v_final),
                    clock_timestamp(),p_actor);
                v_created:=array_append(v_created,v_new);
            END LOOP;
            SET CONSTRAINTS ALL IMMEDIATE;
            SELECT array_agg(period.id ORDER BY period.start_date,period.utility_type,period.id) INTO v_periods
            FROM app.utility_consumption_periods AS period
            CROSS JOIN LATERAL app.utility_period_responsibility(period.unit_id,period.start_date,period.end_date) AS resp
            WHERE period.unit_id=v_l.unit_id AND resp.outcome='RESPONSIBLE' AND resp.lease_id=p_lease
                AND NOT EXISTS(SELECT 1 FROM app.invoice_lines AS line WHERE line.utility_consumption_period_id=period.id);
            IF v_periods IS NULL THEN RAISE EXCEPTION 'UTILITY_NOTHING_TO_BILL' USING ERRCODE='P5N02'; END IF;
            v_built:=app.utility_invoice_build(p_property,p_lease,p_actor,p_key,v_invoice,'FINAL',v_periods,v_due,v_reason);
            v_audit:=gen_random_uuid(); v_now:=clock_timestamp();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_tz,v_now)::date,p_actor,'utility.final_invoice.create','invoice',v_invoice,
                'Final Utility Invoice created at move-out','invoices.issue',p_property,'{}'::jsonb,
                jsonb_build_object('invoice_id',v_invoice,'final_input_event_id',v_final,'created_period_ids',to_jsonb(v_created),
                    'total_usd_cents',v_built->'total_usd_cents','lines',v_built->'lines'),
                p_key,'API','SUCCEEDED',jsonb_build_object('capability','invoices.issue','also','utility.calculate'),
                v_l.primary_tenant_id,p_lease,v_l.unit_id);
            v_response:=jsonb_build_object('data',jsonb_build_object('kind','FINAL','invoice_id',v_invoice,'lease_id',p_lease,
                'property_id',p_property,'final_input_event_id',v_final,'created_period_ids',to_jsonb(v_created),
                'period_ids',(SELECT jsonb_agg(e->'period_id') FROM jsonb_array_elements(v_built->'lines') AS e),
                'total_usd_cents',v_built->'total_usd_cents','invoice',v_built->'invoice',
                'creates_reading',false),'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.utility_invoice_commands(property_id,actor_id,idempotency_key,action,lease_id,invoice_id,audit_event_id,
                final_input_event_id,request_digest,request_intent,response_body,occurred_at)
            VALUES(p_property,p_actor,p_key,'FINAL',p_lease,v_invoice,v_audit,v_final,p_digest,p_intent,v_response,v_now);
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;

        CREATE FUNCTION app.utility_catch_up_invoice_create(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_c app.utility_invoice_commands%ROWTYPE; v_l app.leases%ROWTYPE; v_p app.utility_consumption_periods%ROWTYPE;
            v_invoice uuid; v_period uuid; v_due date; v_reason text; v_resp record; v_built jsonb; v_audit uuid;
            v_response jsonb; v_now timestamptz; v_tz text; v_key text;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE NOWAIT;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE NOWAIT;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Utility catch-up intent is invalid' USING ERRCODE='P5N02'; END IF;
            IF NOT pg_try_advisory_xact_lock(hashtextextended(p_property::text||'|'||p_actor::text||'|utility-invoice|'||p_key::text,0))
            THEN RAISE EXCEPTION 'Utility catch-up command is in use' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_c FROM app.utility_invoice_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_c.action<>'CATCH_UP' OR v_c.lease_id IS DISTINCT FROM p_lease OR v_c.request_digest IS DISTINCT FROM p_digest
                    OR v_c.request_intent IS DISTINCT FROM p_intent
                THEN RAISE EXCEPTION 'Utility Invoice key was reused' USING ERRCODE='P5N05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_c.response_body);
            END IF;
            IF p_intent-ARRAY['invoice_id','consumption_period_id','due_date','due_date_reason']<>'{}'::jsonb
                OR NOT p_intent?&ARRAY['invoice_id','consumption_period_id','due_date','due_date_reason']
                OR jsonb_typeof(p_intent->'invoice_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'consumption_period_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'due_date') NOT IN ('string','null')
                OR jsonb_typeof(p_intent->'due_date_reason') NOT IN ('string','null')
                OR (jsonb_typeof(p_intent->'due_date')='null')<>(jsonb_typeof(p_intent->'due_date_reason')='null')
                OR (jsonb_typeof(p_intent->'due_date_reason')='string' AND NOT app.lease_notice_text_valid(p_intent->>'due_date_reason',500))
            THEN RAISE EXCEPTION 'Utility catch-up fields are invalid' USING ERRCODE='P5N02'; END IF;
            BEGIN
                v_invoice:=(p_intent->>'invoice_id')::uuid; v_period:=(p_intent->>'consumption_period_id')::uuid;
                v_due:=(p_intent->>'due_date')::date; v_reason:=p_intent->>'due_date_reason';
            EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow THEN
                RAISE EXCEPTION 'Utility catch-up identity or date is invalid' USING ERRCODE='P5N02';
            END;
            IF v_invoice='00000000-0000-0000-0000-000000000000' OR v_period='00000000-0000-0000-0000-000000000000'
                OR (v_due IS NOT NULL AND NOT isfinite(v_due))
            THEN RAISE EXCEPTION 'Utility catch-up identity or date is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease;
            SELECT timezone_name INTO STRICT v_tz FROM app.properties WHERE id=p_property;
            FOR v_key IN SELECT key FROM unnest(ARRAY['utility-invoice:'||p_lease::text,
                'utility-unit-type:'||v_l.unit_id::text||':'||'ELECTRICITY',
                'utility-unit-type:'||v_l.unit_id::text||':'||'WATER']) keys(key) ORDER BY key LOOP
                IF NOT pg_try_advisory_xact_lock(hashtextextended(v_key,0))
                THEN RAISE EXCEPTION 'Utility catch-up source is in use' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SELECT period.* INTO v_p FROM app.utility_consumption_periods AS period
            WHERE period.id=v_period AND period.unit_id=v_l.unit_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Utility period was not found for this Lease' USING ERRCODE='P5N01'; END IF;
            IF EXISTS(SELECT 1 FROM app.invoice_lines WHERE utility_consumption_period_id=v_period)
                OR EXISTS(SELECT 1 FROM app.invoices WHERE id=v_invoice)
            THEN RAISE EXCEPTION 'UTILITY_PERIOD_ALREADY_INVOICED' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_resp FROM app.utility_period_responsibility(v_l.unit_id,v_p.start_date,v_p.end_date);
            IF v_resp.outcome='NOT_MOVED_IN' AND v_resp.lease_id=p_lease THEN
                RAISE EXCEPTION 'UTILITY_NOT_MOVED_IN' USING ERRCODE='P5N02';
            END IF;
            IF v_resp.outcome IS DISTINCT FROM 'RESPONSIBLE' OR v_resp.lease_id IS DISTINCT FROM p_lease THEN
                RAISE EXCEPTION 'UTILITY_NOT_RESPONSIBLE' USING ERRCODE='P5N02';
            END IF;
            IF NOT EXISTS(SELECT 1 FROM app.billing_run_items AS item
                WHERE item.outcome='SKIPPED' AND item.diagnostic_code='NOT_MOVED_IN'
                    AND ((item.source_kind='UTILITY_PERIOD' AND item.source_id=v_period)
                        OR (item.source_kind='UTILITY_CASE' AND item.source_id IN (
                            SELECT estimate.estimation_case_id FROM app.broken_meter_estimates AS estimate
                            WHERE estimate.consumption_period_id=v_period))))
            THEN RAISE EXCEPTION 'UTILITY_PERIOD_NOT_SKIPPED' USING ERRCODE='P5N02'; END IF;
            PERFORM app.lock_utility_property_type(p_property,v_p.utility_type);
            PERFORM app.lock_utility_unit_type(v_l.unit_id,v_p.utility_type);
            v_built:=app.utility_invoice_build(p_property,p_lease,p_actor,p_key,v_invoice,'CATCH-UP',ARRAY[v_period],v_due,v_reason);
            v_audit:=gen_random_uuid(); v_now:=clock_timestamp();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_tz,v_now)::date,p_actor,'utility.catch_up_invoice.create','invoice',v_invoice,
                'Utility Invoice created for a period skipped as NOT_MOVED_IN','invoices.issue',p_property,'{}'::jsonb,
                jsonb_build_object('invoice_id',v_invoice,'consumption_period_id',v_period,
                    'total_usd_cents',v_built->'total_usd_cents'),
                p_key,'API','SUCCEEDED',jsonb_build_object('capability','invoices.issue'),
                v_l.primary_tenant_id,p_lease,v_l.unit_id);
            v_response:=jsonb_build_object('data',jsonb_build_object('kind','CATCH_UP','invoice_id',v_invoice,'lease_id',p_lease,
                'property_id',p_property,'consumption_period_id',v_period,'period_ids',jsonb_build_array(v_period),
                'total_usd_cents',v_built->'total_usd_cents','invoice',v_built->'invoice','creates_reading',false),
                'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.utility_invoice_commands(property_id,actor_id,idempotency_key,action,lease_id,invoice_id,audit_event_id,
                final_input_event_id,request_digest,request_intent,response_body,occurred_at)
            VALUES(p_property,p_actor,p_key,'CATCH_UP',p_lease,v_invoice,v_audit,NULL,p_digest,p_intent,v_response,v_now);
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER utility_invoice_commands_reject_mutation BEFORE UPDATE OR DELETE ON app.utility_invoice_commands FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER utility_invoice_commands_reject_truncate BEFORE TRUNCATE ON app.utility_invoice_commands FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.utility_invoice_commands FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    for function in (BUILD, FINAL, CATCH_UP):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {FINAL},{CATCH_UP} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Final Utility Invoice migration is forward-only")
