# ruff: noqa: E501
"""Add immutable operational inspection evidence without posting financial effects."""

from alembic import op

revision = "20260915_60"
down_revision = "20260914_59"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE TABLE app.move_out_inspections (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            expected_lease_version integer NOT NULL CHECK(expected_lease_version>0),
            inspection_date date NOT NULL CHECK(isfinite(inspection_date)),
            result_text text NOT NULL CHECK(app.lease_notice_text_valid(result_text,5000)),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            completed_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK(app.lease_notice_text_valid(authorization_reference,500)),
            evidence_reference text NOT NULL CHECK(app.lease_notice_text_valid(evidence_reference,500)),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,500)),
            supersedes_inspection_id uuid UNIQUE REFERENCES app.move_out_inspections(id) ON DELETE RESTRICT,
            CHECK(supersedes_inspection_id IS DISTINCT FROM id)
        );
        CREATE INDEX move_out_inspections_lease_page ON app.move_out_inspections(lease_id,completed_at,id);
        CREATE TABLE app.inspection_damage_findings (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            inspection_id uuid NOT NULL REFERENCES app.move_out_inspections(id) ON DELETE RESTRICT,
            ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 50),
            description text NOT NULL CHECK(app.lease_notice_text_valid(description,1000)),
            pet_related boolean NOT NULL,
            created_at timestamptz NOT NULL CHECK(isfinite(created_at)),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            UNIQUE(inspection_id,ordinal)
        );
        CREATE TABLE app.move_out_inspection_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            inspection_id uuid NOT NULL UNIQUE REFERENCES app.move_out_inspections(id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        CREATE FUNCTION app.move_out_inspection_snapshot(p_inspection uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT to_jsonb(i)||jsonb_build_object('findings',COALESCE((
                SELECT jsonb_agg(to_jsonb(f) ORDER BY f.ordinal) FROM app.inspection_damage_findings f WHERE f.inspection_id=i.id
            ),'[]'::jsonb),'current_effect',CASE WHEN EXISTS(
                SELECT 1 FROM app.move_out_inspections s WHERE s.supersedes_inspection_id=i.id
            ) THEN 'SUPERSEDED' ELSE 'INSPECTION_ONLY' END,
                'records_physical_departure',false,'financial_completion_assessed',false,'creates_charge',false)
            FROM app.move_out_inspections i WHERE i.id=p_inspection
        $$;

        CREATE FUNCTION app.validate_move_out_inspection_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_prior app.move_out_inspections%ROWTYPE; v_timezone text;
        BEGIN
            PERFORM app.lease_enforcement_scope(NEW.property_id,NEW.lease_id,NEW.completed_by);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=NEW.lease_id FOR UPDATE;
            SELECT timezone_name INTO STRICT v_timezone FROM app.properties WHERE id=NEW.property_id;
            IF v_lease.status NOT IN ('SIGNED','TERMINATED') OR v_lease.signed_at IS NULL
                OR v_lease.version<>NEW.expected_lease_version OR NEW.completed_at>clock_timestamp()
                OR NEW.inspection_date<timezone(v_timezone,v_lease.signed_at)::date
                OR NEW.inspection_date>timezone(v_timezone,NEW.completed_at)::date
            THEN RAISE EXCEPTION 'Inspection Lease, date or version is invalid' USING ERRCODE='23514'; END IF;
            IF NEW.supersedes_inspection_id IS NOT NULL THEN
                SELECT * INTO v_prior FROM app.move_out_inspections WHERE id=NEW.supersedes_inspection_id;
                IF v_prior.id IS NULL OR v_prior.property_id<>NEW.property_id OR v_prior.lease_id<>NEW.lease_id
                    OR v_prior.completed_at>NEW.completed_at
                    OR EXISTS(SELECT 1 FROM app.move_out_inspections WHERE supersedes_inspection_id=v_prior.id)
                THEN RAISE EXCEPTION 'Inspection correction source is invalid' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER move_out_inspections_source BEFORE INSERT ON app.move_out_inspections
            FOR EACH ROW EXECUTE FUNCTION app.validate_move_out_inspection_source();

        CREATE FUNCTION app.validate_inspection_finding_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_inspection app.move_out_inspections%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_inspection FROM app.move_out_inspections WHERE id=NEW.inspection_id;
            IF NEW.created_at<>v_inspection.completed_at OR NEW.created_by<>v_inspection.completed_by
            THEN RAISE EXCEPTION 'Inspection finding attribution is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER inspection_damage_findings_source BEFORE INSERT ON app.inspection_damage_findings
            FOR EACH ROW EXECUTE FUNCTION app.validate_inspection_finding_source();

        CREATE FUNCTION app.validate_move_out_inspection_complete()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_id uuid; v_i app.move_out_inspections%ROWTYPE; v_c app.move_out_inspection_commands%ROWTYPE;
        DECLARE v_a app.audit_events%ROWTYPE; v_findings jsonb; v_intent jsonb; v_snapshot jsonb;
        BEGIN
            v_id:=CASE WHEN TG_TABLE_NAME='move_out_inspections' THEN (to_jsonb(NEW)->>'id')::uuid ELSE (to_jsonb(NEW)->>'inspection_id')::uuid END;
            SELECT * INTO STRICT v_i FROM app.move_out_inspections WHERE id=v_id;
            SELECT * INTO v_c FROM app.move_out_inspection_commands WHERE inspection_id=v_id;
            IF v_c.inspection_id IS NULL THEN RAISE EXCEPTION 'Inspection command evidence is required' USING ERRCODE='23514'; END IF;
            SELECT * INTO STRICT v_a FROM app.audit_events WHERE id=v_c.audit_event_id;
            SELECT COALESCE(jsonb_agg(jsonb_build_object('finding_id',id,'description',description,'pet_related',pet_related) ORDER BY ordinal),'[]'::jsonb)
                INTO v_findings FROM app.inspection_damage_findings WHERE inspection_id=v_id;
            v_intent:=jsonb_build_object('inspection_id',v_i.id,'expected_lease_version',v_i.expected_lease_version,
                'inspection_date',v_i.inspection_date,'result_text',v_i.result_text,'authorization_reference',v_i.authorization_reference,
                'evidence_reference',v_i.evidence_reference,'reason',v_i.reason,'findings',v_findings,'supersedes_inspection_id',v_i.supersedes_inspection_id);
            -- Completion evidence binds the original response even if a later command
            -- in this same transaction supersedes the inspection.
            v_snapshot:=app.move_out_inspection_snapshot(v_id)||jsonb_build_object('current_effect','INSPECTION_ONLY');
            IF v_c.property_id<>v_i.property_id OR v_c.lease_id<>v_i.lease_id OR v_c.actor_id<>v_i.completed_by
                OR v_c.completed_at<>v_i.completed_at OR v_c.request_intent IS DISTINCT FROM v_intent
                OR v_c.response_body->'data' IS DISTINCT FROM v_snapshot
                OR v_a.property_id IS DISTINCT FROM v_i.property_id OR v_a.lease_id IS DISTINCT FROM v_i.lease_id
                OR v_a.actor_id IS DISTINCT FROM v_i.completed_by OR v_a.occurred_at IS DISTINCT FROM v_i.completed_at
                OR v_a.action IS DISTINCT FROM 'lease.inspection.record' OR v_a.entity_type IS DISTINCT FROM 'move_out_inspection'
                OR v_a.entity_id IS DISTINCT FROM v_id OR v_a.linked_source_event_id IS DISTINCT FROM v_id
                OR v_a.correlation_id IS DISTINCT FROM v_c.idempotency_key OR v_a.resulting_state IS DISTINCT FROM v_snapshot
                OR v_a.reason IS DISTINCT FROM v_i.reason OR v_a.authorization_reference IS DISTINCT FROM v_i.authorization_reference
            THEN RAISE EXCEPTION 'Inspection source, command and audit evidence must agree' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.move_out_inspection_read(p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_items jsonb; v_total bigint;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 20 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Inspection page is invalid' USING ERRCODE='P5M02'; END IF;
            SELECT count(*) INTO v_total FROM app.move_out_inspections WHERE lease_id=p_lease;
            SELECT COALESCE(jsonb_agg(app.move_out_inspection_snapshot(page.id) ORDER BY page.completed_at,page.id),'[]'::jsonb)
                INTO v_items FROM (SELECT id,completed_at FROM app.move_out_inspections WHERE lease_id=p_lease
                    ORDER BY completed_at,id LIMIT p_limit OFFSET p_offset) page;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset,
                'records_physical_departure',false,'financial_completion_assessed',false,'creates_charge',false);
        END $$;

        CREATE FUNCTION app.move_out_inspection_record(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_saved app.move_out_inspection_commands%ROWTYPE; v_lease app.leases%ROWTYPE;
        DECLARE v_i uuid; v_supersedes uuid; v_version integer; v_date date; v_timezone text; v_now timestamptz;
        DECLARE v_field text; v_max integer; v_f jsonb; v_fid uuid; v_fids uuid[]:='{}'; v_ordinal integer;
        DECLARE v_previous jsonb; v_result jsonb; v_response jsonb; v_audit uuid;
        BEGIN
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property FOR SHARE;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent)<>'object'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            THEN RAISE EXCEPTION 'Inspection command identity is invalid' USING ERRCODE='P5M02'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('move-out-inspection:'||p_property::text||':'||p_actor::text||':'||p_key::text,0));
            SELECT * INTO v_saved FROM app.move_out_inspection_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_saved.request_digest<>p_digest OR v_saved.request_intent IS DISTINCT FROM p_intent OR v_saved.lease_id<>p_lease
                THEN RAISE EXCEPTION 'Inspection command key was reused' USING ERRCODE='P5M05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_saved.response_body);
            END IF;
            IF p_intent-ARRAY['inspection_id','expected_lease_version','inspection_date','result_text','authorization_reference',
                    'evidence_reference','reason','findings','supersedes_inspection_id']<>'{}'::jsonb
                OR jsonb_typeof(p_intent->'inspection_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'expected_lease_version') IS DISTINCT FROM 'number'
                OR (p_intent->>'expected_lease_version')!~'^[1-9][0-9]{0,9}$'
                OR jsonb_typeof(p_intent->'inspection_date') IS DISTINCT FROM 'string'
                OR (p_intent->>'inspection_date')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                OR NOT (p_intent ? 'supersedes_inspection_id')
                OR (p_intent->'supersedes_inspection_id'<>'null'::jsonb AND jsonb_typeof(p_intent->'supersedes_inspection_id')<>'string')
                OR jsonb_typeof(p_intent->'findings') IS DISTINCT FROM 'array'
            THEN RAISE EXCEPTION 'Inspection command input is invalid' USING ERRCODE='P5M02'; END IF;
            IF jsonb_array_length(p_intent->'findings')>50 THEN RAISE EXCEPTION 'Too many inspection findings' USING ERRCODE='P5M02'; END IF;
            FOREACH v_field IN ARRAY ARRAY['result_text','authorization_reference','evidence_reference','reason'] LOOP
                v_max:=CASE WHEN v_field='result_text' THEN 5000 ELSE 500 END;
                IF jsonb_typeof(p_intent->v_field) IS DISTINCT FROM 'string' OR NOT app.lease_notice_text_valid(p_intent->>v_field,v_max)
                THEN RAISE EXCEPTION 'Inspection evidence is invalid' USING ERRCODE='P5M02'; END IF;
            END LOOP;
            BEGIN
                v_i:=(p_intent->>'inspection_id')::uuid; v_supersedes:=(p_intent->>'supersedes_inspection_id')::uuid;
                v_version:=(p_intent->>'expected_lease_version')::integer; v_date:=(p_intent->>'inspection_date')::date;
            EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR datetime_field_overflow OR invalid_datetime_format THEN
                RAISE EXCEPTION 'Inspection date or identity is invalid' USING ERRCODE='P5M02';
            END;
            IF v_i='00000000-0000-0000-0000-000000000000' OR v_supersedes='00000000-0000-0000-0000-000000000000'
                OR v_supersedes=v_i OR NOT isfinite(v_date)
            THEN RAISE EXCEPTION 'Inspection identity or date is invalid' USING ERRCODE='P5M02'; END IF;
            FOR v_f IN SELECT value FROM jsonb_array_elements(p_intent->'findings') LOOP
                IF jsonb_typeof(v_f) IS DISTINCT FROM 'object' OR v_f-ARRAY['finding_id','description','pet_related']<>'{}'::jsonb
                    OR jsonb_typeof(v_f->'finding_id') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_f->'description') IS DISTINCT FROM 'string'
                    OR NOT app.lease_notice_text_valid(v_f->>'description',1000)
                    OR jsonb_typeof(v_f->'pet_related') IS DISTINCT FROM 'boolean'
                THEN RAISE EXCEPTION 'Inspection finding is invalid' USING ERRCODE='P5M02'; END IF;
                BEGIN v_fid:=(v_f->>'finding_id')::uuid;
                EXCEPTION WHEN invalid_text_representation THEN RAISE EXCEPTION 'Finding identity is invalid' USING ERRCODE='P5M02'; END;
                IF v_fid='00000000-0000-0000-0000-000000000000' OR v_fid=ANY(v_fids)
                THEN RAISE EXCEPTION 'Finding identities must be nonzero and unique' USING ERRCODE='P5M02'; END IF;
                v_fids:=array_append(v_fids,v_fid);
            END LOOP;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=p_lease FOR UPDATE;
            v_now:=clock_timestamp();
            IF v_lease.version<>v_version OR v_lease.status NOT IN ('SIGNED','TERMINATED') OR v_lease.signed_at IS NULL
                OR v_date<timezone(v_timezone,v_lease.signed_at)::date OR v_date>timezone(v_timezone,v_now)::date
                OR EXISTS(SELECT 1 FROM app.move_out_inspections WHERE id=v_i)
                OR EXISTS(SELECT 1 FROM app.inspection_damage_findings WHERE id=ANY(v_fids))
            THEN RAISE EXCEPTION 'Lease or inspection source changed' USING ERRCODE='P5M03'; END IF;
            IF v_supersedes IS NOT NULL THEN
                SELECT app.move_out_inspection_snapshot(id) INTO v_previous FROM app.move_out_inspections WHERE id=v_supersedes AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Inspection correction source not found' USING ERRCODE='P5M01'; END IF;
                IF EXISTS(SELECT 1 FROM app.move_out_inspections WHERE supersedes_inspection_id=v_supersedes)
                THEN RAISE EXCEPTION 'Inspection correction source changed' USING ERRCODE='P5M03'; END IF;
            END IF;
            INSERT INTO app.move_out_inspections VALUES(v_i,p_property,p_lease,v_version,v_date,p_intent->>'result_text',v_now,p_actor,
                p_intent->>'authorization_reference',p_intent->>'evidence_reference',p_intent->>'reason',v_supersedes);
            v_ordinal:=0;
            FOR v_f IN SELECT value FROM jsonb_array_elements(p_intent->'findings') LOOP
                v_ordinal:=v_ordinal+1;
                INSERT INTO app.inspection_damage_findings VALUES((v_f->>'finding_id')::uuid,v_i,v_ordinal,
                    v_f->>'description',(v_f->>'pet_related')::boolean,v_now,p_actor);
            END LOOP;
            v_result:=app.move_out_inspection_snapshot(v_i); v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,linked_source_event_id,customer_id,lease_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'lease.inspection.record','move_out_inspection',v_i,
                p_intent->>'reason',p_intent->>'authorization_reference',p_property,v_previous,v_result,p_key,'API','SUCCEEDED',
                jsonb_build_object('capability','leases.inspect','evidence_reference',p_intent->>'evidence_reference'),
                v_i,v_lease.primary_tenant_id,p_lease);
            v_response:=jsonb_build_object('data',v_result,'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.move_out_inspection_commands VALUES(p_property,p_actor,p_key,p_lease,v_i,v_audit,p_digest,p_intent,v_response,v_now);
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    for table in (
        "move_out_inspections",
        "inspection_damage_findings",
        "move_out_inspection_commands",
    ):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON app.{table}
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_move_out_inspection_complete();
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
    for signature in (
        "app.move_out_inspection_snapshot(uuid)",
        "app.validate_move_out_inspection_source()",
        "app.validate_inspection_finding_source()",
        "app.validate_move_out_inspection_complete()",
        "app.move_out_inspection_read(uuid,uuid,uuid,integer,integer)",
        "app.move_out_inspection_record(uuid,uuid,uuid,uuid,text,jsonb,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.move_out_inspection_read(uuid,uuid,uuid,integer,integer) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.move_out_inspection_record(uuid,uuid,uuid,uuid,text,jsonb,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Move-out inspection evidence is forward-only")
