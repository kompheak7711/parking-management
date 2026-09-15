# ruff: noqa: E501
"""Add explicit physical-departure evidence under existing financial source guards."""

from alembic import op

revision = "20260915_61"
down_revision = "20260915_60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.physical_move_out_events (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            termination_event_id uuid NOT NULL REFERENCES app.lease_commands(event_id) ON DELETE RESTRICT,
            expected_lease_version integer NOT NULL CHECK(expected_lease_version>0),
            expected_unit_version integer NOT NULL CHECK(expected_unit_version>0),
            actual_move_out_date date NOT NULL CHECK(isfinite(actual_move_out_date)),
            unit_condition text NOT NULL CHECK(unit_condition IN ('CLEANING','UNDER_MAINTENANCE','OUT_OF_SERVICE')),
            previous_unit_status text NOT NULL CHECK(previous_unit_status IN ('VACANT','RESERVED','OCCUPIED','CLEANING','UNDER_MAINTENANCE','OUT_OF_SERVICE')),
            resulting_unit_status text NOT NULL CHECK(resulting_unit_status IN ('OCCUPIED','CLEANING','UNDER_MAINTENANCE','OUT_OF_SERVICE')),
            resulting_unit_version integer NOT NULL CHECK(resulting_unit_version>=expected_unit_version),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,500)),
            authorization_reference text NOT NULL CHECK(app.lease_notice_text_valid(authorization_reference,500)),
            evidence_reference text NOT NULL CHECK(app.lease_notice_text_valid(evidence_reference,500)),
            supersedes_event_id uuid UNIQUE REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CHECK(supersedes_event_id IS NULL OR supersedes_event_id<>id)
        );
        CREATE INDEX physical_move_out_events_lease_idx ON app.physical_move_out_events(lease_id,occurred_at,id);

        CREATE TABLE app.physical_move_out_occupancies (
            event_id uuid NOT NULL REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            occupancy_id uuid NOT NULL REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            previous_version integer NOT NULL CHECK(previous_version>0),
            resulting_version integer NOT NULL CHECK(resulting_version>=previous_version),
            PRIMARY KEY(event_id,occupancy_id),
            FOREIGN KEY(occupancy_id,previous_version) REFERENCES app.occupancy_revisions(occupancy_id,version) ON DELETE RESTRICT,
            FOREIGN KEY(occupancy_id,resulting_version) REFERENCES app.occupancy_revisions(occupancy_id,version) ON DELETE RESTRICT
        );

        CREATE TABLE app.physical_move_out_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            event_id uuid NOT NULL UNIQUE REFERENCES app.physical_move_out_events(id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        CREATE FUNCTION app.physical_move_out_snapshot(p_event uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('event_id',e.id,'property_id',e.property_id,'lease_id',e.lease_id,
                'unit_id',e.unit_id,'termination_event_id',e.termination_event_id,
                'expected_lease_version',e.expected_lease_version,'expected_unit_version',e.expected_unit_version,
                'actual_move_out_date',e.actual_move_out_date,'unit_condition',e.unit_condition,
                'previous_unit_status',e.previous_unit_status,'resulting_unit_status',e.resulting_unit_status,
                'resulting_unit_version',e.resulting_unit_version,'reason',e.reason,
                'authorization_reference',e.authorization_reference,'evidence_reference',e.evidence_reference,
                'supersedes_event_id',e.supersedes_event_id,'occurred_at',e.occurred_at,'actor_id',e.actor_id,
                'occupancies',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'occupancy_id',link.occupancy_id,'customer_id',r.customer_id,'move_in_date',r.move_in_date,
                    'previous_version',link.previous_version,'previous_move_out_date',old.move_out_date,
                    'resulting_version',link.resulting_version,'move_out_date',r.move_out_date)
                    ORDER BY link.occupancy_id) FROM app.physical_move_out_occupancies link
                    JOIN app.occupancy_revisions r ON r.occupancy_id=link.occupancy_id AND r.version=link.resulting_version
                    JOIN app.occupancy_revisions old ON old.occupancy_id=link.occupancy_id AND old.version=link.previous_version
                    WHERE link.event_id=e.id),'[]'::jsonb),
                'final_inputs_status','PENDING_RECONCILIATION','utility_completion_assessed',false,
                'financial_completion_assessed',false,'creates_charge',false)
            FROM app.physical_move_out_events e WHERE e.id=p_event
        $$;

        CREATE FUNCTION app.physical_move_out_audit_snapshot(p_event uuid,p_previous boolean)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('move_out_event_id',e.id,'property_id',e.property_id,
                'lease_id',e.lease_id,'unit_id',e.unit_id,'termination_event_id',e.termination_event_id,
                'unit_status',CASE WHEN p_previous THEN e.previous_unit_status ELSE e.resulting_unit_status END,
                'version',CASE WHEN p_previous THEN e.expected_unit_version ELSE e.resulting_unit_version END,
                'occurred_at',e.occurred_at,'actor_id',e.actor_id,'supersedes_event_id',e.supersedes_event_id,
                'occupancies',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'occupancy_id',r.occupancy_id,'customer_id',r.customer_id,'version',r.version,
                    'move_in_date',r.move_in_date,'move_out_date',r.move_out_date) ORDER BY r.occupancy_id)
                    FROM app.physical_move_out_occupancies link JOIN app.occupancy_revisions r
                    ON r.occupancy_id=link.occupancy_id AND r.version=CASE WHEN p_previous THEN link.previous_version ELSE link.resulting_version END
                    WHERE link.event_id=e.id),'[]'::jsonb),
                'utility_completion_assessed',false,'financial_completion_assessed',false,'creates_charge',false)
            FROM app.physical_move_out_events e WHERE e.id=p_event
        $$;

        CREATE FUNCTION app.validate_physical_move_out_complete()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_id uuid; v_e app.physical_move_out_events%ROWTYPE;
            v_c app.physical_move_out_commands%ROWTYPE; v_a app.audit_events%ROWTYPE;
            v_l app.leases%ROWTYPE; v_t app.lease_commands%ROWTYPE; v_members jsonb; v_intent jsonb;
            v_count integer; v_old app.physical_move_out_events%ROWTYPE;
        BEGIN
            v_id:=CASE WHEN TG_TABLE_NAME='physical_move_out_events' THEN (to_jsonb(NEW)->>'id')::uuid ELSE (to_jsonb(NEW)->>'event_id')::uuid END;
            SELECT * INTO v_e FROM app.physical_move_out_events WHERE id=v_id;
            SELECT * INTO v_c FROM app.physical_move_out_commands WHERE event_id=v_id;
            SELECT * INTO v_a FROM app.audit_events WHERE id=v_c.audit_event_id;
            SELECT * INTO v_l FROM app.leases WHERE id=v_e.lease_id;
            SELECT * INTO v_t FROM app.lease_commands WHERE event_id=v_e.termination_event_id;
            SELECT count(*),jsonb_agg(jsonb_build_object('occupancy_id',occupancy_id,'expected_version',previous_version) ORDER BY occupancy_id)
                INTO v_count,v_members FROM app.physical_move_out_occupancies WHERE event_id=v_id;
            IF v_e.id IS NULL OR v_c.event_id IS NULL OR v_a.id IS NULL OR v_count NOT BETWEEN 1 AND 20
                OR v_l.unit_id IS DISTINCT FROM v_e.unit_id
                OR NOT EXISTS(SELECT 1 FROM app.units WHERE id=v_e.unit_id AND property_id=v_e.property_id)
                OR v_t.action IS DISTINCT FROM 'lease.terminate' OR v_t.lease_id IS DISTINCT FROM v_e.lease_id
                OR v_t.property_id IS DISTINCT FROM v_e.property_id OR v_t.authorization_reference IS DISTINCT FROM 'leases.terminate'
                OR v_t.result_snapshot->>'status' IS DISTINCT FROM 'TERMINATED'
                OR v_t.result_snapshot->>'lease_id' IS DISTINCT FROM v_e.lease_id::text
                OR v_e.occurred_at<v_t.occurred_at
                OR v_c.property_id IS DISTINCT FROM v_e.property_id OR v_c.lease_id IS DISTINCT FROM v_e.lease_id
                OR v_c.actor_id IS DISTINCT FROM v_e.actor_id OR v_c.occurred_at IS DISTINCT FROM v_e.occurred_at
                OR v_c.response_body->'data' IS DISTINCT FROM app.physical_move_out_snapshot(v_id)
                OR jsonb_typeof(v_c.response_body->'meta') IS DISTINCT FROM 'object'
                OR jsonb_typeof(v_c.response_body#>'{meta,request_id}') IS DISTINCT FROM 'string'
                OR v_c.response_body#>>'{meta,request_id}'!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            THEN RAISE EXCEPTION 'Physical departure evidence is incomplete' USING ERRCODE='23514'; END IF;
            v_intent:=jsonb_build_object('event_id',v_e.id,'termination_event_id',v_e.termination_event_id,
                'expected_lease_version',v_e.expected_lease_version,'expected_unit_version',v_e.expected_unit_version,
                'actual_move_out_date',to_char(v_e.actual_move_out_date,'YYYY-MM-DD'),'unit_condition',v_e.unit_condition,
                'occupancies',v_members,'reason',v_e.reason,'authorization_reference',v_e.authorization_reference,
                'evidence_reference',v_e.evidence_reference,'supersedes_event_id',v_e.supersedes_event_id);
            IF v_c.request_intent IS DISTINCT FROM v_intent OR EXISTS(
                SELECT 1 FROM app.physical_move_out_occupancies link
                JOIN app.occupancy_revisions prior_revision ON prior_revision.occupancy_id=link.occupancy_id AND prior_revision.version=link.previous_version
                JOIN app.occupancy_revisions result ON result.occupancy_id=link.occupancy_id AND result.version=link.resulting_version
                WHERE link.event_id=v_id AND (prior_revision.lease_id<>v_e.lease_id OR result.lease_id<>v_e.lease_id
                    OR prior_revision.customer_id<>result.customer_id OR prior_revision.move_in_date<>result.move_in_date
                    OR result.move_out_date IS DISTINCT FROM v_e.actual_move_out_date
                    OR (v_e.supersedes_event_id IS NULL AND prior_revision.move_out_date IS NOT NULL)
                    OR link.resulting_version<>link.previous_version+CASE WHEN prior_revision.move_out_date IS DISTINCT FROM v_e.actual_move_out_date THEN 1 ELSE 0 END))
                OR v_e.resulting_unit_version<>v_e.expected_unit_version+(CASE WHEN v_e.previous_unit_status<>v_e.resulting_unit_status THEN 1 ELSE 0 END)
                OR (v_e.previous_unit_status IN ('UNDER_MAINTENANCE','OUT_OF_SERVICE') AND v_e.resulting_unit_status<>v_e.previous_unit_status)
            THEN RAISE EXCEPTION 'Physical departure source revisions disagree' USING ERRCODE='23514'; END IF;
            IF v_e.supersedes_event_id IS NOT NULL THEN
                SELECT * INTO v_old FROM app.physical_move_out_events WHERE id=v_e.supersedes_event_id;
                IF v_old.lease_id IS DISTINCT FROM v_e.lease_id OR v_old.termination_event_id IS DISTINCT FROM v_e.termination_event_id
                    OR v_old.occurred_at>v_e.occurred_at
                    OR (SELECT array_agg(occupancy_id ORDER BY occupancy_id) FROM app.physical_move_out_occupancies WHERE event_id=v_old.id)
                        IS DISTINCT FROM (SELECT array_agg(occupancy_id ORDER BY occupancy_id) FROM app.physical_move_out_occupancies WHERE event_id=v_e.id)
                    OR EXISTS(SELECT 1 FROM app.physical_move_out_occupancies link
                        JOIN app.occupancy_revisions prior_revision ON prior_revision.occupancy_id=link.occupancy_id AND prior_revision.version=link.previous_version
                        WHERE link.event_id=v_id AND prior_revision.move_out_date IS DISTINCT FROM v_old.actual_move_out_date)
                THEN RAISE EXCEPTION 'Physical departure correction source disagrees' USING ERRCODE='23514'; END IF;
            END IF;
            IF v_a.actor_id IS DISTINCT FROM v_e.actor_id OR v_a.property_id IS DISTINCT FROM v_e.property_id
                OR v_a.lease_id IS DISTINCT FROM v_e.lease_id OR v_a.customer_id IS DISTINCT FROM v_l.primary_tenant_id
                OR v_a.action IS DISTINCT FROM 'lease.move_out.record' OR v_a.entity_type IS DISTINCT FROM 'physical_move_out'
                OR v_a.entity_id IS DISTINCT FROM v_e.id OR v_a.linked_source_event_id IS DISTINCT FROM v_e.id
                OR v_a.correlation_id IS DISTINCT FROM v_c.idempotency_key OR v_a.occurred_at IS DISTINCT FROM v_e.occurred_at
                OR v_a.business_date IS DISTINCT FROM (SELECT timezone(timezone_name,v_e.occurred_at)::date FROM app.properties WHERE id=v_e.property_id)
                OR v_a.reason IS DISTINCT FROM v_e.reason OR v_a.authorization_reference IS DISTINCT FROM v_e.authorization_reference
                OR v_a.source IS DISTINCT FROM 'API' OR v_a.outcome IS DISTINCT FROM 'SUCCEEDED'
                OR v_a.authorization_evidence IS DISTINCT FROM jsonb_build_object('capability','leases.move_out','move_out_event_id',v_e.id)
                OR v_a.previous_state IS DISTINCT FROM app.physical_move_out_audit_snapshot(v_e.id,true)
                OR v_a.resulting_state IS DISTINCT FROM app.physical_move_out_audit_snapshot(v_e.id,false)
            THEN RAISE EXCEPTION 'Physical departure audit evidence disagrees' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.physical_move_out_read(p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_items jsonb; v_total integer; v_open jsonb; v_open_count integer;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 20 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Physical departure page is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT count(*) INTO v_total FROM app.physical_move_out_events WHERE lease_id=p_lease;
            SELECT COALESCE(jsonb_agg(value ORDER BY occurred_at DESC,id DESC),'[]'::jsonb) INTO v_items FROM (
                SELECT e.id,e.occurred_at,app.physical_move_out_snapshot(e.id)||jsonb_build_object(
                    'event_status',CASE WHEN EXISTS(SELECT 1 FROM app.physical_move_out_events WHERE supersedes_event_id=e.id) THEN 'SUPERSEDED' ELSE 'CURRENT' END) value
                FROM app.physical_move_out_events e WHERE e.lease_id=p_lease ORDER BY e.occurred_at DESC,e.id DESC LIMIT p_limit OFFSET p_offset) page;
            SELECT count(*) INTO v_open_count FROM app.occupancies WHERE lease_id=p_lease AND move_out_date IS NULL;
            SELECT COALESCE(jsonb_agg(jsonb_build_object('occupancy_id',id,'customer_id',customer_id,
                'move_in_date',move_in_date,'version',version) ORDER BY id),'[]'::jsonb) INTO v_open FROM (
                SELECT id,customer_id,move_in_date,version FROM app.occupancies WHERE lease_id=p_lease AND move_out_date IS NULL ORDER BY id LIMIT 20) rows;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset,
                'open_occupancies',v_open,'open_occupancy_count',v_open_count,
                'final_inputs_status','PENDING_RECONCILIATION','utility_completion_assessed',false,
                'financial_completion_assessed',false,'creates_charge',false);
        END $$;

        CREATE FUNCTION app.physical_move_out_record(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_c app.physical_move_out_commands%ROWTYPE; v_l app.leases%ROWTYPE; v_u app.units%ROWTYPE;
            v_t app.lease_commands%ROWTYPE; v_prior app.physical_move_out_events%ROWTYPE;
            v_o app.occupancies%ROWTYPE; v_item jsonb; v_ids uuid[]:=ARRAY[]::uuid[];
            v_versions integer[]:=ARRAY[]::integer[]; v_results integer[]:=ARRAY[]::integer[];
            v_event uuid; v_termination uuid; v_supersedes uuid; v_date date;
            v_lease_version integer; v_unit_version integer; v_id uuid; v_version integer;
            v_timezone text; v_now timestamptz; v_key text; v_status text; v_audit uuid;
            v_response jsonb; v_message text; v_index integer; v_new_unit_version integer;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE NOWAIT;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE NOWAIT;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Physical departure intent is invalid' USING ERRCODE='P5N02'; END IF;
            IF NOT pg_try_advisory_xact_lock(hashtextextended(p_property::text||'|'||p_actor::text||'|physical-move-out|'||p_key::text,0))
            THEN RAISE EXCEPTION 'Physical departure command is in use' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_c FROM app.physical_move_out_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_c.lease_id IS DISTINCT FROM p_lease OR v_c.request_digest IS DISTINCT FROM p_digest OR v_c.request_intent IS DISTINCT FROM p_intent
                THEN RAISE EXCEPTION 'Physical departure key was reused' USING ERRCODE='P5N05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_c.response_body);
            END IF;
            IF p_intent-ARRAY['event_id','termination_event_id','expected_lease_version','expected_unit_version',
                'actual_move_out_date','unit_condition','occupancies','reason','authorization_reference','evidence_reference','supersedes_event_id']<>'{}'::jsonb
                OR NOT p_intent?&ARRAY['event_id','termination_event_id','expected_lease_version','expected_unit_version',
                'actual_move_out_date','unit_condition','occupancies','reason','authorization_reference','evidence_reference','supersedes_event_id']
                OR jsonb_typeof(p_intent->'event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'termination_event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'expected_lease_version') IS DISTINCT FROM 'number'
                OR jsonb_typeof(p_intent->'expected_unit_version') IS DISTINCT FROM 'number'
                OR p_intent->>'expected_lease_version'!~'^[1-9][0-9]{0,9}$'
                OR p_intent->>'expected_unit_version'!~'^[1-9][0-9]{0,9}$'
                OR jsonb_typeof(p_intent->'actual_move_out_date') IS DISTINCT FROM 'string'
                OR p_intent->>'actual_move_out_date'!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                OR jsonb_typeof(p_intent->'unit_condition') IS DISTINCT FROM 'string'
                OR p_intent->>'unit_condition' NOT IN ('CLEANING','UNDER_MAINTENANCE','OUT_OF_SERVICE')
                OR jsonb_typeof(p_intent->'occupancies') IS DISTINCT FROM 'array'
                OR jsonb_typeof(p_intent->'supersedes_event_id') NOT IN ('string','null')
                OR jsonb_typeof(p_intent->'reason') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'authorization_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'evidence_reference') IS DISTINCT FROM 'string'
                OR NOT app.lease_notice_text_valid(p_intent->>'reason',500)
                OR NOT app.lease_notice_text_valid(p_intent->>'authorization_reference',500)
                OR NOT app.lease_notice_text_valid(p_intent->>'evidence_reference',500)
            THEN RAISE EXCEPTION 'Physical departure fields are invalid' USING ERRCODE='P5N02'; END IF;
            IF jsonb_array_length(p_intent->'occupancies') NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Ended Occupancy list is invalid' USING ERRCODE='P5N02'; END IF;
            BEGIN
                v_event:=(p_intent->>'event_id')::uuid; v_termination:=(p_intent->>'termination_event_id')::uuid;
                v_supersedes:=(p_intent->>'supersedes_event_id')::uuid; v_date:=(p_intent->>'actual_move_out_date')::date;
                v_lease_version:=(p_intent->>'expected_lease_version')::integer; v_unit_version:=(p_intent->>'expected_unit_version')::integer;
            EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR datetime_field_overflow THEN
                RAISE EXCEPTION 'Physical departure identity or date is invalid' USING ERRCODE='P5N02';
            END;
            IF v_event='00000000-0000-0000-0000-000000000000' OR v_termination='00000000-0000-0000-0000-000000000000'
                OR v_supersedes='00000000-0000-0000-0000-000000000000' OR v_event=v_supersedes OR NOT isfinite(v_date)
            THEN RAISE EXCEPTION 'Physical departure identity or date is invalid' USING ERRCODE='P5N02'; END IF;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_intent->'occupancies') ORDER BY value->>'occupancy_id' LOOP
                IF jsonb_typeof(v_item) IS DISTINCT FROM 'object' OR v_item-ARRAY['occupancy_id','expected_version']<>'{}'::jsonb
                    OR jsonb_typeof(v_item->'occupancy_id') IS DISTINCT FROM 'string' OR jsonb_typeof(v_item->'expected_version') IS DISTINCT FROM 'number'
                    OR v_item->>'expected_version'!~'^[1-9][0-9]{0,9}$'
                THEN RAISE EXCEPTION 'Ended Occupancy is invalid' USING ERRCODE='P5N02'; END IF;
                BEGIN v_id:=(v_item->>'occupancy_id')::uuid; v_version:=(v_item->>'expected_version')::integer;
                EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                    RAISE EXCEPTION 'Ended Occupancy identity or version is invalid' USING ERRCODE='P5N02'; END;
                IF v_id='00000000-0000-0000-0000-000000000000' OR v_id=ANY(v_ids)
                THEN RAISE EXCEPTION 'Ended Occupancy identities must be nonzero and unique' USING ERRCODE='P5N02'; END IF;
                v_ids:=array_append(v_ids,v_id); v_versions:=array_append(v_versions,v_version);
            END LOOP;
            SELECT l.* INTO v_l FROM app.leases l JOIN app.units u ON u.id=l.unit_id WHERE l.id=p_lease AND u.property_id=p_property;
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property;
            -- The source triggers acquire these same keys. Acquire them without waiting
            -- before row locks; conflicting legacy row-first callers can finish safely.
            FOR v_key IN SELECT key FROM unnest(ARRAY[
                'billing-run-eligibility:'||p_property::text,'invoice-lease:'||p_lease::text,
                'invoice-property-service:'||p_property::text,
                'utility-property-type:'||p_property::text||':'||'ELECTRICITY','utility-property-type:'||p_property::text||':'||'WATER',
                'utility-unit-type:'||v_l.unit_id::text||':'||'ELECTRICITY','utility-unit-type:'||v_l.unit_id::text||':'||'WATER']) keys(key) ORDER BY key LOOP
                IF NOT pg_try_advisory_xact_lock(hashtextextended(v_key,0))
                THEN RAISE EXCEPTION 'Physical departure source is in use' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease FOR UPDATE NOWAIT;
            SELECT * INTO STRICT v_u FROM app.units WHERE id=v_l.unit_id FOR UPDATE NOWAIT;
            v_now:=clock_timestamp();
            SELECT * INTO v_t FROM app.lease_commands WHERE event_id=v_termination;
            IF v_u.property_id IS DISTINCT FROM p_property OR v_l.version<>v_lease_version OR v_u.version<>v_unit_version
                OR v_l.status<>'TERMINATED' OR v_l.signed_at IS NULL OR v_l.terminated_at IS NULL
                OR v_t.action IS DISTINCT FROM 'lease.terminate' OR v_t.lease_id IS DISTINCT FROM p_lease
                OR v_t.property_id IS DISTINCT FROM p_property OR v_t.authorization_reference IS DISTINCT FROM 'leases.terminate'
                OR v_t.result_snapshot->>'status' IS DISTINCT FROM 'TERMINATED'
                OR v_t.result_snapshot->>'lease_id' IS DISTINCT FROM p_lease::text
                OR v_t.result_snapshot->>'actual_termination_date' IS DISTINCT FROM v_l.actual_termination_date::text
                OR v_t.occurred_at IS DISTINCT FROM v_l.terminated_at
                OR v_date<timezone(v_timezone,v_l.signed_at)::date OR v_date>timezone(v_timezone,v_now)::date
                OR v_t.occurred_at>v_now
                OR EXISTS(SELECT 1 FROM app.physical_move_out_events WHERE id=v_event)
            THEN RAISE EXCEPTION 'Physical departure source changed' USING ERRCODE='P5N03'; END IF;
            IF v_supersedes IS NOT NULL THEN
                SELECT * INTO v_prior FROM app.physical_move_out_events WHERE id=v_supersedes AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Physical departure correction source not found' USING ERRCODE='P5N01'; END IF;
                IF v_prior.termination_event_id<>v_termination OR EXISTS(SELECT 1 FROM app.physical_move_out_events WHERE supersedes_event_id=v_supersedes)
                    OR (SELECT array_agg(occupancy_id ORDER BY occupancy_id) FROM app.physical_move_out_occupancies WHERE event_id=v_supersedes)
                        IS DISTINCT FROM (SELECT array_agg(id ORDER BY id) FROM unnest(v_ids) ids(id))
                THEN RAISE EXCEPTION 'Physical departure correction source changed' USING ERRCODE='P5N03'; END IF;
            END IF;
            FOR v_index IN 1..array_length(v_ids,1) LOOP
                SELECT * INTO v_o FROM app.occupancies WHERE id=v_ids[v_index] AND lease_id=p_lease FOR UPDATE NOWAIT;
                IF NOT FOUND THEN RAISE EXCEPTION 'Ended Occupancy was not found' USING ERRCODE='P5N01'; END IF;
                IF v_o.version<>v_versions[v_index] OR v_date<v_o.move_in_date
                    OR (v_supersedes IS NULL AND v_o.move_out_date IS NOT NULL)
                    OR (v_supersedes IS NOT NULL AND v_o.move_out_date IS DISTINCT FROM v_prior.actual_move_out_date)
                    OR (v_o.move_out_date IS DISTINCT FROM v_date AND v_o.version=2147483647)
                THEN RAISE EXCEPTION 'Ended Occupancy source changed' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SET CONSTRAINTS app.physical_move_out_events_complete,app.physical_move_out_occupancies_complete,
                app.physical_move_out_commands_complete DEFERRED;
            FOR v_index IN 1..array_length(v_ids,1) LOOP
                SELECT * INTO STRICT v_o FROM app.occupancies WHERE id=v_ids[v_index];
                IF v_o.move_out_date IS DISTINCT FROM v_date THEN
                    UPDATE app.occupancies SET move_out_date=v_date,version=version+1,
                        updated_at=v_now,updated_by=p_actor WHERE id=v_o.id RETURNING version INTO v_version;
                ELSE v_version:=v_o.version; END IF;
                v_results:=array_append(v_results,v_version);
            END LOOP;
            v_status:=CASE WHEN v_u.status IN ('UNDER_MAINTENANCE','OUT_OF_SERVICE') THEN v_u.status
                WHEN EXISTS(SELECT 1 FROM app.occupancies o JOIN app.leases l ON l.id=o.lease_id WHERE l.unit_id=v_u.id AND o.move_out_date IS NULL)
                THEN 'OCCUPIED' ELSE p_intent->>'unit_condition' END;
            v_new_unit_version:=v_u.version;
            IF v_u.status<>v_status THEN
                IF v_u.version=2147483647 THEN RAISE EXCEPTION 'Unit version is exhausted' USING ERRCODE='P5N03'; END IF;
                UPDATE app.units SET status=v_status,version=version+1,updated_at=v_now,updated_by=p_actor WHERE id=v_u.id RETURNING version INTO v_new_unit_version;
            END IF;
            INSERT INTO app.physical_move_out_events VALUES(v_event,p_property,p_lease,v_u.id,v_termination,v_lease_version,v_unit_version,
                v_date,p_intent->>'unit_condition',v_u.status,v_status,v_new_unit_version,p_intent->>'reason',
                p_intent->>'authorization_reference',p_intent->>'evidence_reference',v_supersedes,v_now,p_actor);
            FOR v_index IN 1..array_length(v_ids,1) LOOP
                INSERT INTO app.physical_move_out_occupancies VALUES(v_event,v_ids[v_index],v_versions[v_index],v_results[v_index]);
            END LOOP;
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,linked_source_event_id,customer_id,lease_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'lease.move_out.record','physical_move_out',v_event,
                p_intent->>'reason',p_intent->>'authorization_reference',p_property,
                app.physical_move_out_audit_snapshot(v_event,true),app.physical_move_out_audit_snapshot(v_event,false),
                p_key,'API','SUCCEEDED',jsonb_build_object('capability','leases.move_out','move_out_event_id',v_event),
                v_event,v_l.primary_tenant_id,p_lease);
            v_response:=jsonb_build_object('data',app.physical_move_out_snapshot(v_event),'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.physical_move_out_commands VALUES(p_property,p_actor,p_key,p_lease,v_event,v_audit,p_digest,p_intent,v_response,v_now);
            SET CONSTRAINTS app.physical_move_out_events_complete,app.physical_move_out_occupancies_complete,
                app.physical_move_out_commands_complete IMMEDIATE;
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS v_message=MESSAGE_TEXT;
            IF v_message='Responsibility change requires an exact Utility Reading or estimate boundary' THEN
                RAISE EXCEPTION 'Existing Utility evidence requires responsibility-boundary reconciliation' USING ERRCODE='P5N04';
            END IF;
            RAISE;
        END $$;
    """)
    for table in (
        "physical_move_out_events",
        "physical_move_out_occupancies",
        "physical_move_out_commands",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON app.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_physical_move_out_complete()"
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
        "app.physical_move_out_snapshot(uuid)",
        "app.physical_move_out_audit_snapshot(uuid,boolean)",
        "app.validate_physical_move_out_complete()",
        "app.physical_move_out_read(uuid,uuid,uuid,integer,integer)",
        "app.physical_move_out_record(uuid,uuid,uuid,uuid,text,jsonb,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.physical_move_out_read(uuid,uuid,uuid,integer,integer) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.physical_move_out_record(uuid,uuid,uuid,uuid,text,jsonb,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Physical departure evidence is forward-only")
