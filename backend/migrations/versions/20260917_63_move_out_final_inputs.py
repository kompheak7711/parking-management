# ruff: noqa: E501
"""Record final Utility inputs for a physical departure without creating readings or charges."""

from alembic import op

revision = "20260917_63"
down_revision = "20260915_61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.move_out_final_input_events (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            move_out_event_id uuid NOT NULL REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            actual_move_out_date date NOT NULL CHECK(isfinite(actual_move_out_date)),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,500)),
            authorization_reference text NOT NULL CHECK(app.lease_notice_text_valid(authorization_reference,500)),
            evidence_reference text NOT NULL CHECK(app.lease_notice_text_valid(evidence_reference,500)),
            supersedes_event_id uuid UNIQUE REFERENCES app.move_out_final_input_events(id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CHECK(supersedes_event_id IS NULL OR supersedes_event_id<>id)
        );
        CREATE INDEX move_out_final_input_events_lease_idx ON app.move_out_final_input_events(lease_id,occurred_at,id);
        CREATE UNIQUE INDEX move_out_final_input_events_root_idx ON app.move_out_final_input_events(lease_id) WHERE supersedes_event_id IS NULL;

        CREATE TABLE app.move_out_final_input_items (
            event_id uuid NOT NULL REFERENCES app.move_out_final_input_events(id) ON DELETE RESTRICT,
            meter_id uuid NOT NULL,
            unit_id uuid NOT NULL,
            utility_type text NOT NULL CHECK(utility_type IN ('ELECTRICITY','WATER')),
            resolution text NOT NULL CHECK(resolution IN ('READING','ESTIMATE','UNRESOLVED')),
            reading_id uuid,
            reading_date date,
            reading_value numeric(20,6) CHECK(reading_value IS NULL OR reading_value>=0),
            reading_version integer CHECK(reading_version IS NULL OR reading_version>0),
            reading_validated_at timestamptz,
            estimate_id uuid REFERENCES app.broken_meter_estimates(id) ON DELETE RESTRICT,
            consumption_period_id uuid REFERENCES app.utility_consumption_periods(id) ON DELETE RESTRICT,
            unresolved_reason text CHECK(unresolved_reason IN ('MISSING_READING','READING_NOT_VALIDATED','BROKEN_METER_ESTIMATE_PENDING')),
            PRIMARY KEY(event_id,meter_id),
            FOREIGN KEY(meter_id,unit_id,utility_type) REFERENCES app.utility_meters(id,unit_id,utility_type) ON DELETE RESTRICT,
            FOREIGN KEY(reading_id,meter_id) REFERENCES app.utility_readings(id,meter_id) ON DELETE RESTRICT,
            CHECK(
                (resolution='READING' AND reading_id IS NOT NULL AND reading_date IS NOT NULL
                    AND reading_value IS NOT NULL AND reading_version IS NOT NULL AND reading_validated_at IS NOT NULL
                    AND estimate_id IS NULL AND consumption_period_id IS NULL AND unresolved_reason IS NULL)
                OR (resolution='ESTIMATE' AND estimate_id IS NOT NULL AND consumption_period_id IS NOT NULL
                    AND reading_id IS NULL AND reading_date IS NULL AND reading_value IS NULL
                    AND reading_version IS NULL AND reading_validated_at IS NULL AND unresolved_reason IS NULL)
                OR (resolution='UNRESOLVED' AND unresolved_reason IS NOT NULL
                    AND reading_id IS NULL AND reading_date IS NULL AND reading_value IS NULL
                    AND reading_version IS NULL AND reading_validated_at IS NULL
                    AND estimate_id IS NULL AND consumption_period_id IS NULL)
            )
        );

        CREATE TABLE app.move_out_final_input_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            event_id uuid NOT NULL UNIQUE REFERENCES app.move_out_final_input_events(id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        CREATE FUNCTION app.move_out_final_inputs_snapshot(p_event uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('event_id',e.id,'property_id',e.property_id,'lease_id',e.lease_id,
                'unit_id',e.unit_id,'move_out_event_id',e.move_out_event_id,
                'actual_move_out_date',e.actual_move_out_date,'reason',e.reason,
                'authorization_reference',e.authorization_reference,'evidence_reference',e.evidence_reference,
                'supersedes_event_id',e.supersedes_event_id,'occurred_at',e.occurred_at,'actor_id',e.actor_id,
                'items',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'meter_id',i.meter_id,'utility_type',i.utility_type,'resolution',i.resolution,
                    'reading',CASE WHEN i.resolution='READING' THEN jsonb_build_object(
                        'reading_id',i.reading_id,'reading_date',i.reading_date,'reading_value',i.reading_value::text,
                        'reading_version',i.reading_version,'validated_at',i.reading_validated_at) END,
                    'estimate',CASE WHEN i.resolution='ESTIMATE' THEN jsonb_build_object(
                        'estimate_id',i.estimate_id,'consumption_period_id',i.consumption_period_id) END,
                    'unresolved_reason',i.unresolved_reason) ORDER BY i.meter_id)
                    FROM app.move_out_final_input_items i WHERE i.event_id=e.id),'[]'::jsonb),
                'unresolved_item_count',(SELECT count(*) FROM app.move_out_final_input_items i
                    WHERE i.event_id=e.id AND i.resolution='UNRESOLVED'),
                'final_inputs_status',CASE WHEN EXISTS(SELECT 1 FROM app.move_out_final_input_items i
                    WHERE i.event_id=e.id AND i.resolution='UNRESOLVED') THEN 'PENDING_RECONCILIATION' ELSE 'INPUTS_RECORDED' END,
                'creates_reading',false,'utility_completion_assessed',false,
                'financial_completion_assessed',false,'creates_charge',false)
            FROM app.move_out_final_input_events e WHERE e.id=p_event
        $$;

        CREATE FUNCTION app.move_out_final_inputs_audit_snapshot(p_event uuid,p_previous boolean)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT CASE WHEN p_previous THEN COALESCE(
                    (SELECT app.move_out_final_inputs_snapshot(e.supersedes_event_id)
                        FROM app.move_out_final_input_events e WHERE e.id=p_event AND e.supersedes_event_id IS NOT NULL),
                    jsonb_build_object('final_inputs_status','NOT_RECORDED','event_id',NULL,'items','[]'::jsonb))
                ELSE app.move_out_final_inputs_snapshot(p_event) END
        $$;

        CREATE FUNCTION app.validate_move_out_final_inputs_complete()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_id uuid; v_e app.move_out_final_input_events%ROWTYPE; v_c app.move_out_final_input_commands%ROWTYPE;
            v_a app.audit_events%ROWTYPE; v_l app.leases%ROWTYPE; v_m app.physical_move_out_events%ROWTYPE;
            v_old app.move_out_final_input_events%ROWTYPE; v_count integer; v_required uuid[]; v_intent jsonb;
        BEGIN
            v_id:=CASE WHEN TG_TABLE_NAME='move_out_final_input_events' THEN (to_jsonb(NEW)->>'id')::uuid ELSE (to_jsonb(NEW)->>'event_id')::uuid END;
            SELECT * INTO v_e FROM app.move_out_final_input_events WHERE id=v_id;
            SELECT * INTO v_c FROM app.move_out_final_input_commands WHERE event_id=v_id;
            SELECT * INTO v_a FROM app.audit_events WHERE id=v_c.audit_event_id;
            SELECT * INTO v_l FROM app.leases WHERE id=v_e.lease_id;
            SELECT * INTO v_m FROM app.physical_move_out_events WHERE id=v_e.move_out_event_id;
            SELECT count(*) INTO v_count FROM app.move_out_final_input_items WHERE event_id=v_id;
            SELECT array_agg(id ORDER BY id) INTO v_required FROM app.utility_meters
                WHERE unit_id=v_e.unit_id AND installed_date<=v_e.actual_move_out_date
                    AND (deactivated_date IS NULL OR deactivated_date>=v_e.actual_move_out_date);
            IF v_e.id IS NULL OR v_c.event_id IS NULL OR v_a.id IS NULL OR v_count NOT BETWEEN 1 AND 20
                OR v_l.unit_id IS DISTINCT FROM v_e.unit_id
                OR NOT EXISTS(SELECT 1 FROM app.units WHERE id=v_e.unit_id AND property_id=v_e.property_id)
                OR v_m.id IS NULL OR v_m.lease_id IS DISTINCT FROM v_e.lease_id OR v_m.unit_id IS DISTINCT FROM v_e.unit_id
                OR v_m.property_id IS DISTINCT FROM v_e.property_id
                OR v_m.actual_move_out_date IS DISTINCT FROM v_e.actual_move_out_date OR v_e.occurred_at<v_m.occurred_at
                OR v_c.property_id IS DISTINCT FROM v_e.property_id OR v_c.lease_id IS DISTINCT FROM v_e.lease_id
                OR v_c.actor_id IS DISTINCT FROM v_e.actor_id OR v_c.occurred_at IS DISTINCT FROM v_e.occurred_at
                OR v_c.response_body->'data' IS DISTINCT FROM app.move_out_final_inputs_snapshot(v_id)
                OR jsonb_typeof(v_c.response_body->'meta') IS DISTINCT FROM 'object'
                OR jsonb_typeof(v_c.response_body#>'{meta,request_id}') IS DISTINCT FROM 'string'
                OR v_c.response_body#>>'{meta,request_id}'!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR v_required IS DISTINCT FROM (SELECT array_agg(meter_id ORDER BY meter_id) FROM app.move_out_final_input_items WHERE event_id=v_id)
            THEN RAISE EXCEPTION 'Final Utility input evidence is incomplete' USING ERRCODE='23514'; END IF;
            v_intent:=jsonb_build_object('event_id',v_e.id,'move_out_event_id',v_e.move_out_event_id,
                'supersedes_event_id',v_e.supersedes_event_id,'reason',v_e.reason,
                'authorization_reference',v_e.authorization_reference,'evidence_reference',v_e.evidence_reference,
                'items',(SELECT jsonb_agg(jsonb_build_object('meter_id',i.meter_id,'resolution',i.resolution,
                    'reading_id',i.reading_id,'estimate_id',i.estimate_id,'unresolved_reason',i.unresolved_reason) ORDER BY i.meter_id)
                    FROM app.move_out_final_input_items i WHERE i.event_id=v_id));
            IF v_c.request_intent IS DISTINCT FROM v_intent OR EXISTS(
                SELECT 1 FROM app.move_out_final_input_items i WHERE i.event_id=v_id AND i.unit_id IS DISTINCT FROM v_e.unit_id)
                OR EXISTS(SELECT 1 FROM app.move_out_final_input_items i WHERE i.event_id=v_id AND (
                    (i.resolution='READING' AND NOT EXISTS(SELECT 1 FROM app.utility_readings r
                        WHERE r.id=i.reading_id AND r.meter_id=i.meter_id AND r.reading_date=v_e.actual_move_out_date
                            AND i.reading_date=v_e.actual_move_out_date AND r.validated_at IS NOT NULL
                            AND r.validated_at=i.reading_validated_at AND r.reading_value=i.reading_value AND r.version=i.reading_version))
                    OR (i.resolution='ESTIMATE' AND NOT EXISTS(SELECT 1 FROM app.broken_meter_estimates est
                        JOIN app.broken_meter_estimation_cases k ON k.id=est.estimation_case_id
                        JOIN app.utility_consumption_periods p ON p.id=est.consumption_period_id
                        WHERE est.id=i.estimate_id AND p.id=i.consumption_period_id AND p.calculation_kind='BROKEN_METER_ESTIMATE'
                            AND k.unit_id=v_e.unit_id AND k.utility_type=i.utility_type
                            AND i.meter_id IN (k.failed_meter_id,k.replacement_meter_id)
                            AND p.start_date<=v_e.actual_move_out_date AND v_e.actual_move_out_date<=p.end_date))))
            THEN RAISE EXCEPTION 'Final Utility input sources disagree' USING ERRCODE='23514'; END IF;
            IF v_e.supersedes_event_id IS NOT NULL THEN
                SELECT * INTO v_old FROM app.move_out_final_input_events WHERE id=v_e.supersedes_event_id;
                IF v_old.id IS NULL OR v_old.lease_id IS DISTINCT FROM v_e.lease_id OR v_old.occurred_at>v_e.occurred_at
                THEN RAISE EXCEPTION 'Final Utility input correction source disagrees' USING ERRCODE='23514'; END IF;
            END IF;
            IF v_a.actor_id IS DISTINCT FROM v_e.actor_id OR v_a.property_id IS DISTINCT FROM v_e.property_id
                OR v_a.unit_id IS DISTINCT FROM v_e.unit_id
                OR v_a.lease_id IS DISTINCT FROM v_e.lease_id OR v_a.customer_id IS DISTINCT FROM v_l.primary_tenant_id
                OR v_a.action IS DISTINCT FROM 'lease.move_out.final_inputs.record'
                OR v_a.entity_type IS DISTINCT FROM 'move_out_final_inputs'
                OR v_a.entity_id IS DISTINCT FROM v_e.id OR v_a.linked_source_event_id IS DISTINCT FROM v_e.move_out_event_id
                OR v_a.correlation_id IS DISTINCT FROM v_c.idempotency_key OR v_a.occurred_at IS DISTINCT FROM v_e.occurred_at
                OR v_a.business_date IS DISTINCT FROM (SELECT timezone(timezone_name,v_e.occurred_at)::date FROM app.properties WHERE id=v_e.property_id)
                OR v_a.reason IS DISTINCT FROM v_e.reason OR v_a.authorization_reference IS DISTINCT FROM v_e.authorization_reference
                OR v_a.source IS DISTINCT FROM 'API' OR v_a.outcome IS DISTINCT FROM 'SUCCEEDED'
                OR v_a.authorization_evidence IS DISTINCT FROM jsonb_build_object('capability','leases.move_out','final_input_event_id',v_e.id)
                OR v_a.previous_state IS DISTINCT FROM app.move_out_final_inputs_audit_snapshot(v_e.id,true)
                OR v_a.resulting_state IS DISTINCT FROM app.move_out_final_inputs_audit_snapshot(v_e.id,false)
            THEN RAISE EXCEPTION 'Final Utility input audit evidence disagrees' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.move_out_final_inputs_read(p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_items jsonb; v_total integer;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 20 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Final Utility input page is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT count(*) INTO v_total FROM app.move_out_final_input_events WHERE lease_id=p_lease;
            SELECT COALESCE(jsonb_agg(value ORDER BY occurred_at DESC,id DESC),'[]'::jsonb) INTO v_items FROM (
                SELECT e.id,e.occurred_at,app.move_out_final_inputs_snapshot(e.id)||jsonb_build_object(
                    'event_status',CASE WHEN EXISTS(SELECT 1 FROM app.move_out_final_input_events s WHERE s.supersedes_event_id=e.id) THEN 'SUPERSEDED' ELSE 'CURRENT' END,
                    'physical_event_status',CASE WHEN EXISTS(SELECT 1 FROM app.physical_move_out_events s WHERE s.supersedes_event_id=e.move_out_event_id) THEN 'SUPERSEDED' ELSE 'CURRENT' END,
                    'changed_reading_meter_ids',COALESCE((SELECT jsonb_agg(i.meter_id ORDER BY i.meter_id)
                        FROM app.move_out_final_input_items i JOIN app.utility_readings r ON r.id=i.reading_id
                        WHERE i.event_id=e.id AND i.resolution='READING'
                            AND (r.version<>i.reading_version OR r.reading_value<>i.reading_value)),'[]'::jsonb)) value
                FROM app.move_out_final_input_events e WHERE e.lease_id=p_lease
                ORDER BY e.occurred_at DESC,e.id DESC LIMIT p_limit OFFSET p_offset) page;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset,
                'creates_reading',false,'utility_completion_assessed',false,
                'financial_completion_assessed',false,'creates_charge',false);
        END $$;

        CREATE FUNCTION app.move_out_final_inputs_record(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_c app.move_out_final_input_commands%ROWTYPE; v_l app.leases%ROWTYPE; v_m app.physical_move_out_events%ROWTYPE;
            v_meter_row app.utility_meters%ROWTYPE; v_r app.utility_readings%ROWTYPE; v_est app.broken_meter_estimates%ROWTYPE;
            v_case app.broken_meter_estimation_cases%ROWTYPE; v_period app.utility_consumption_periods%ROWTYPE;
            v_prior app.move_out_final_input_events%ROWTYPE; v_item jsonb;
            v_event uuid; v_move uuid; v_supersedes uuid; v_meter uuid; v_reading uuid; v_estimate uuid; v_resolution text; v_reason text;
            v_meters uuid[]:=ARRAY[]::uuid[]; v_resolutions text[]:=ARRAY[]::text[]; v_readings uuid[]:=ARRAY[]::uuid[];
            v_estimates uuid[]:=ARRAY[]::uuid[]; v_reasons text[]:=ARRAY[]::text[]; v_required uuid[];
            v_now timestamptz; v_timezone text; v_audit uuid; v_response jsonb; v_key text; v_index integer;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE NOWAIT;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE NOWAIT;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Final Utility input intent is invalid' USING ERRCODE='P5N02'; END IF;
            IF NOT pg_try_advisory_xact_lock(hashtextextended(p_property::text||'|'||p_actor::text||'|move-out-final-inputs|'||p_key::text,0))
            THEN RAISE EXCEPTION 'Final Utility input command is in use' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_c FROM app.move_out_final_input_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_c.lease_id IS DISTINCT FROM p_lease OR v_c.request_digest IS DISTINCT FROM p_digest OR v_c.request_intent IS DISTINCT FROM p_intent
                THEN RAISE EXCEPTION 'Final Utility input key was reused' USING ERRCODE='P5N05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_c.response_body);
            END IF;
            IF p_intent-ARRAY['event_id','move_out_event_id','supersedes_event_id','reason','authorization_reference','evidence_reference','items']<>'{}'::jsonb
                OR NOT p_intent?&ARRAY['event_id','move_out_event_id','supersedes_event_id','reason','authorization_reference','evidence_reference','items']
                OR jsonb_typeof(p_intent->'event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'move_out_event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'supersedes_event_id') NOT IN ('string','null')
                OR jsonb_typeof(p_intent->'reason') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'authorization_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'evidence_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'items') IS DISTINCT FROM 'array'
                OR NOT app.lease_notice_text_valid(p_intent->>'reason',500)
                OR NOT app.lease_notice_text_valid(p_intent->>'authorization_reference',500)
                OR NOT app.lease_notice_text_valid(p_intent->>'evidence_reference',500)
            THEN RAISE EXCEPTION 'Final Utility input fields are invalid' USING ERRCODE='P5N02'; END IF;
            IF jsonb_array_length(p_intent->'items') NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Final Utility input list is invalid' USING ERRCODE='P5N02'; END IF;
            BEGIN
                v_event:=(p_intent->>'event_id')::uuid; v_move:=(p_intent->>'move_out_event_id')::uuid;
                v_supersedes:=(p_intent->>'supersedes_event_id')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Final Utility input identity is invalid' USING ERRCODE='P5N02';
            END;
            IF v_event='00000000-0000-0000-0000-000000000000' OR v_move='00000000-0000-0000-0000-000000000000'
                OR v_supersedes='00000000-0000-0000-0000-000000000000' OR v_event=v_supersedes
            THEN RAISE EXCEPTION 'Final Utility input identity is invalid' USING ERRCODE='P5N02'; END IF;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_intent->'items') ORDER BY value->>'meter_id' LOOP
                IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
                    OR v_item-ARRAY['meter_id','resolution','reading_id','estimate_id','unresolved_reason']<>'{}'::jsonb
                    OR NOT v_item?&ARRAY['meter_id','resolution','reading_id','estimate_id','unresolved_reason']
                    OR jsonb_typeof(v_item->'meter_id') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_item->'resolution') IS DISTINCT FROM 'string'
                    OR v_item->>'resolution' NOT IN ('READING','ESTIMATE','UNRESOLVED')
                    OR jsonb_typeof(v_item->'reading_id') NOT IN ('string','null')
                    OR jsonb_typeof(v_item->'estimate_id') NOT IN ('string','null')
                    OR jsonb_typeof(v_item->'unresolved_reason') NOT IN ('string','null')
                    OR (v_item->>'resolution'='READING' AND (jsonb_typeof(v_item->'reading_id') IS DISTINCT FROM 'string'
                        OR jsonb_typeof(v_item->'estimate_id') IS DISTINCT FROM 'null'
                        OR jsonb_typeof(v_item->'unresolved_reason') IS DISTINCT FROM 'null'))
                    OR (v_item->>'resolution'='ESTIMATE' AND (jsonb_typeof(v_item->'estimate_id') IS DISTINCT FROM 'string'
                        OR jsonb_typeof(v_item->'reading_id') IS DISTINCT FROM 'null'
                        OR jsonb_typeof(v_item->'unresolved_reason') IS DISTINCT FROM 'null'))
                    OR (v_item->>'resolution'='UNRESOLVED' AND (jsonb_typeof(v_item->'unresolved_reason') IS DISTINCT FROM 'string'
                        OR v_item->>'unresolved_reason' NOT IN ('MISSING_READING','READING_NOT_VALIDATED','BROKEN_METER_ESTIMATE_PENDING')
                        OR jsonb_typeof(v_item->'reading_id') IS DISTINCT FROM 'null'
                        OR jsonb_typeof(v_item->'estimate_id') IS DISTINCT FROM 'null'))
                THEN RAISE EXCEPTION 'Final Utility input item is invalid' USING ERRCODE='P5N02'; END IF;
                BEGIN
                    v_meter:=(v_item->>'meter_id')::uuid; v_reading:=(v_item->>'reading_id')::uuid;
                    v_estimate:=(v_item->>'estimate_id')::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'Final Utility input item identity is invalid' USING ERRCODE='P5N02';
                END;
                IF v_meter='00000000-0000-0000-0000-000000000000' OR v_reading='00000000-0000-0000-0000-000000000000'
                    OR v_estimate='00000000-0000-0000-0000-000000000000' OR v_meter=ANY(v_meters)
                THEN RAISE EXCEPTION 'Final Utility input Meters must be nonzero and unique' USING ERRCODE='P5N02'; END IF;
                v_meters:=array_append(v_meters,v_meter); v_resolutions:=array_append(v_resolutions,v_item->>'resolution');
                v_readings:=array_append(v_readings,v_reading); v_estimates:=array_append(v_estimates,v_estimate);
                v_reasons:=array_append(v_reasons,v_item->>'unresolved_reason');
            END LOOP;
            SELECT * INTO v_l FROM app.leases WHERE id=p_lease;
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property;
            FOR v_key IN SELECT key FROM unnest(ARRAY['move-out-final-inputs:'||p_lease::text,
                'utility-unit-type:'||v_l.unit_id::text||':'||'ELECTRICITY',
                'utility-unit-type:'||v_l.unit_id::text||':'||'WATER']) keys(key) ORDER BY key LOOP
                IF NOT pg_try_advisory_xact_lock(hashtextextended(v_key,0))
                THEN RAISE EXCEPTION 'Final Utility input source is in use' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease FOR SHARE NOWAIT;
            v_now:=clock_timestamp();
            SELECT * INTO v_m FROM app.physical_move_out_events WHERE id=v_move AND lease_id=p_lease AND property_id=p_property;
            IF NOT FOUND THEN RAISE EXCEPTION 'Physical departure was not found' USING ERRCODE='P5N01'; END IF;
            IF v_l.status<>'TERMINATED' OR v_m.unit_id IS DISTINCT FROM v_l.unit_id
                OR EXISTS(SELECT 1 FROM app.physical_move_out_events WHERE supersedes_event_id=v_move)
                OR EXISTS(SELECT 1 FROM app.move_out_final_input_events WHERE id=v_event)
                OR v_m.occurred_at>v_now
            THEN RAISE EXCEPTION 'Final Utility input source changed' USING ERRCODE='P5N03'; END IF;
            IF v_supersedes IS NULL THEN
                IF EXISTS(SELECT 1 FROM app.move_out_final_input_events WHERE lease_id=p_lease)
                THEN RAISE EXCEPTION 'Final Utility input source changed' USING ERRCODE='P5N03'; END IF;
            ELSE
                SELECT * INTO v_prior FROM app.move_out_final_input_events WHERE id=v_supersedes AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Final Utility input correction source not found' USING ERRCODE='P5N01'; END IF;
                IF EXISTS(SELECT 1 FROM app.move_out_final_input_events WHERE supersedes_event_id=v_supersedes)
                    OR v_prior.occurred_at>v_now
                THEN RAISE EXCEPTION 'Final Utility input correction source changed' USING ERRCODE='P5N03'; END IF;
            END IF;
            SELECT array_agg(id ORDER BY id) INTO v_required FROM app.utility_meters
                WHERE unit_id=v_m.unit_id AND installed_date<=v_m.actual_move_out_date
                    AND (deactivated_date IS NULL OR deactivated_date>=v_m.actual_move_out_date);
            IF v_required IS NULL OR v_required IS DISTINCT FROM (SELECT array_agg(x ORDER BY x) FROM unnest(v_meters) x)
            THEN RAISE EXCEPTION 'Final Utility input list must cover every applicable Meter once' USING ERRCODE='P5N02'; END IF;
            SET CONSTRAINTS app.move_out_final_input_events_complete,app.move_out_final_input_items_complete,
                app.move_out_final_input_commands_complete DEFERRED;
            INSERT INTO app.move_out_final_input_events(id,property_id,lease_id,unit_id,move_out_event_id,actual_move_out_date,
                reason,authorization_reference,evidence_reference,supersedes_event_id,occurred_at,actor_id)
            VALUES(v_event,p_property,p_lease,v_m.unit_id,v_move,v_m.actual_move_out_date,p_intent->>'reason',
                p_intent->>'authorization_reference',p_intent->>'evidence_reference',v_supersedes,v_now,p_actor);
            FOR v_index IN 1..array_length(v_meters,1) LOOP
                SELECT * INTO STRICT v_meter_row FROM app.utility_meters WHERE id=v_meters[v_index] FOR SHARE NOWAIT;
                v_resolution:=v_resolutions[v_index]; v_reason:=v_reasons[v_index];
                IF v_resolution='READING' THEN
                    SELECT * INTO v_r FROM app.utility_readings WHERE id=v_readings[v_index] AND meter_id=v_meters[v_index] FOR SHARE NOWAIT;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Final Utility Reading was not found' USING ERRCODE='P5N01'; END IF;
                    IF v_r.validated_at IS NULL OR v_r.reading_date IS DISTINCT FROM v_m.actual_move_out_date
                    THEN RAISE EXCEPTION 'Final Utility Reading must be validated and dated on the actual Move-out Date' USING ERRCODE='P5N02'; END IF;
                    INSERT INTO app.move_out_final_input_items(event_id,meter_id,unit_id,utility_type,resolution,reading_id,
                        reading_date,reading_value,reading_version,reading_validated_at)
                    VALUES(v_event,v_meters[v_index],v_meter_row.unit_id,v_meter_row.utility_type,'READING',v_r.id,
                        v_r.reading_date,v_r.reading_value,v_r.version,v_r.validated_at);
                ELSIF v_resolution='ESTIMATE' THEN
                    SELECT * INTO v_est FROM app.broken_meter_estimates WHERE id=v_estimates[v_index];
                    IF NOT FOUND THEN RAISE EXCEPTION 'Approved broken-Meter estimate was not found' USING ERRCODE='P5N01'; END IF;
                    SELECT * INTO STRICT v_case FROM app.broken_meter_estimation_cases WHERE id=v_est.estimation_case_id;
                    SELECT * INTO STRICT v_period FROM app.utility_consumption_periods WHERE id=v_est.consumption_period_id;
                    IF v_case.unit_id IS DISTINCT FROM v_m.unit_id OR v_case.utility_type IS DISTINCT FROM v_meter_row.utility_type
                        OR NOT (v_meters[v_index] IN (v_case.failed_meter_id,v_case.replacement_meter_id))
                        OR v_period.calculation_kind IS DISTINCT FROM 'BROKEN_METER_ESTIMATE'
                        OR v_period.start_date>v_m.actual_move_out_date OR v_period.end_date<v_m.actual_move_out_date
                    THEN RAISE EXCEPTION 'Broken-Meter estimate does not bound this Meter at the actual Move-out Date' USING ERRCODE='P5N02'; END IF;
                    INSERT INTO app.move_out_final_input_items(event_id,meter_id,unit_id,utility_type,resolution,estimate_id,consumption_period_id)
                    VALUES(v_event,v_meters[v_index],v_meter_row.unit_id,v_meter_row.utility_type,'ESTIMATE',v_est.id,v_period.id);
                ELSE
                    IF (v_reason='MISSING_READING' AND EXISTS(SELECT 1 FROM app.utility_readings
                            WHERE meter_id=v_meters[v_index] AND reading_date=v_m.actual_move_out_date))
                        OR (v_reason='READING_NOT_VALIDATED' AND NOT EXISTS(SELECT 1 FROM app.utility_readings
                            WHERE meter_id=v_meters[v_index] AND reading_date=v_m.actual_move_out_date AND validated_at IS NULL))
                        OR (v_reason='BROKEN_METER_ESTIMATE_PENDING' AND (v_meter_row.failure_date IS NULL OR EXISTS(
                            SELECT 1 FROM app.broken_meter_estimates est
                            JOIN app.broken_meter_estimation_cases k ON k.id=est.estimation_case_id
                            JOIN app.utility_consumption_periods p ON p.id=est.consumption_period_id
                            WHERE v_meters[v_index] IN (k.failed_meter_id,k.replacement_meter_id)
                                AND p.start_date<=v_m.actual_move_out_date AND v_m.actual_move_out_date<=p.end_date)))
                    THEN RAISE EXCEPTION 'Unresolved reason is not supported by current Utility evidence' USING ERRCODE='P5N02'; END IF;
                    INSERT INTO app.move_out_final_input_items(event_id,meter_id,unit_id,utility_type,resolution,unresolved_reason)
                    VALUES(v_event,v_meters[v_index],v_meter_row.unit_id,v_meter_row.utility_type,'UNRESOLVED',v_reason);
                END IF;
            END LOOP;
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,linked_source_event_id,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'lease.move_out.final_inputs.record','move_out_final_inputs',v_event,
                p_intent->>'reason',p_intent->>'authorization_reference',p_property,
                app.move_out_final_inputs_audit_snapshot(v_event,true),app.move_out_final_inputs_audit_snapshot(v_event,false),
                p_key,'API','SUCCEEDED',jsonb_build_object('capability','leases.move_out','final_input_event_id',v_event),
                v_move,v_l.primary_tenant_id,p_lease,v_m.unit_id);
            v_response:=jsonb_build_object('data',app.move_out_final_inputs_snapshot(v_event),'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.move_out_final_input_commands VALUES(p_property,p_actor,p_key,p_lease,v_event,v_audit,p_digest,p_intent,v_response,v_now);
            SET CONSTRAINTS app.move_out_final_input_events_complete,app.move_out_final_input_items_complete,
                app.move_out_final_input_commands_complete IMMEDIATE;
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    for table in (
        "move_out_final_input_events",
        "move_out_final_input_items",
        "move_out_final_input_commands",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON app.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_move_out_final_inputs_complete()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    for function in (
        "app.move_out_final_inputs_snapshot(uuid)",
        "app.move_out_final_inputs_audit_snapshot(uuid,boolean)",
        "app.validate_move_out_final_inputs_complete()",
        "app.move_out_final_inputs_read(uuid,uuid,uuid,integer,integer)",
        "app.move_out_final_inputs_record(uuid,uuid,uuid,uuid,text,jsonb,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.move_out_final_inputs_read(uuid,uuid,uuid,integer,integer) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.move_out_final_inputs_record(uuid,uuid,uuid,uuid,text,jsonb,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Move-out final Utility input evidence is forward-only")
