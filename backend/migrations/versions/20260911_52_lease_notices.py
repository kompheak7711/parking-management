# ruff: noqa: E501
"""Add immutable approved notice context without changing tenancy or finances."""

from alembic import op

revision = "20260911_52"
down_revision = "20260910_51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE TABLE app.lease_notice_contexts (
            notice_id uuid PRIMARY KEY REFERENCES app.termination_notices(id) ON DELETE RESTRICT,
            expected_lease_version integer NOT NULL CHECK(expected_lease_version>0),
            approved_grounds text NOT NULL CHECK(approved_grounds=btrim(approved_grounds) AND length(approved_grounds) BETWEEN 1 AND 2000),
            notice_period_terms text NOT NULL CHECK(notice_period_terms=btrim(notice_period_terms) AND length(notice_period_terms) BETWEEN 1 AND 2000),
            evidence_reference text NOT NULL CHECK(evidence_reference=btrim(evidence_reference) AND length(evidence_reference) BETWEEN 1 AND 500),
            communication_record text NOT NULL CHECK(communication_record=btrim(communication_record) AND length(communication_record) BETWEEN 1 AND 2000),
            authorization_reference text NOT NULL CHECK(authorization_reference=btrim(authorization_reference) AND length(authorization_reference) BETWEEN 1 AND 500),
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            supersedes_notice_id uuid UNIQUE REFERENCES app.termination_notices(id) ON DELETE RESTRICT,
            CHECK(supersedes_notice_id IS DISTINCT FROM notice_id)
        );
        CREATE TABLE app.lease_notice_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            notice_id uuid NOT NULL UNIQUE REFERENCES app.lease_notice_contexts(notice_id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            completed_at timestamptz NOT NULL CHECK(isfinite(completed_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        CREATE FUNCTION app.validate_lease_notice_context()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_notice app.termination_notices%ROWTYPE; v_lease app.leases%ROWTYPE;
        DECLARE v_previous app.termination_notices%ROWTYPE; v_timezone text; v_property uuid;
        BEGIN
            SELECT * INTO STRICT v_notice FROM app.termination_notices WHERE id=NEW.notice_id;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=v_notice.lease_id FOR UPDATE;
            SELECT p.id,p.timezone_name INTO v_property,v_timezone FROM app.properties p
                JOIN app.units u ON u.property_id=p.id WHERE u.id=v_lease.unit_id;
            PERFORM app.lease_enforcement_scope(v_property,v_lease.id,v_notice.actor_id);
            IF v_lease.status NOT IN ('SIGNED','TERMINATED') OR v_lease.signed_at IS NULL
                OR v_lease.version<>NEW.expected_lease_version
                OR NOT isfinite(v_notice.notice_date) OR NOT isfinite(v_notice.occurred_at)
                OR v_notice.notice_date<timezone(v_timezone,v_lease.signed_at)::date
                OR v_notice.notice_date>timezone(v_timezone,v_notice.occurred_at)::date
                OR v_notice.occurred_at>clock_timestamp()
                OR (v_notice.intended_termination_date IS NOT NULL AND
                    (NOT isfinite(v_notice.intended_termination_date) OR v_notice.intended_termination_date<v_notice.notice_date))
                OR length(v_notice.notice_text)>5000 OR length(v_notice.governing_lease_provision)>2000
            THEN RAISE EXCEPTION 'Notice source chronology or Lease version is invalid' USING ERRCODE='23514'; END IF;
            IF NEW.supersedes_notice_id IS NOT NULL THEN
                SELECT * INTO v_previous FROM app.termination_notices WHERE id=NEW.supersedes_notice_id;
                IF v_previous.id IS NULL OR v_previous.lease_id<>v_notice.lease_id
                    OR v_previous.occurred_at>v_notice.occurred_at
                    OR EXISTS(SELECT 1 FROM app.lease_notice_contexts WHERE supersedes_notice_id=v_previous.id)
                THEN RAISE EXCEPTION 'Notice correction source is invalid' USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER lease_notice_context_source BEFORE INSERT ON app.lease_notice_contexts
            FOR EACH ROW EXECUTE FUNCTION app.validate_lease_notice_context();

        CREATE FUNCTION app.lease_notice_snapshot(p_notice uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT to_jsonb(n)||jsonb_build_object('property_id',u.property_id,'context',to_jsonb(c),
                'current_effect',CASE WHEN EXISTS(SELECT 1 FROM app.lease_notice_contexts successor WHERE successor.supersedes_notice_id=n.id)
                    THEN 'SUPERSEDED' WHEN c.notice_id IS NULL THEN 'HISTORICAL_NOTICE_ONLY' ELSE 'NOTICE_ONLY' END,
                'changes_lease_status',false,'records_physical_move_out',false)
            FROM app.termination_notices n JOIN app.leases l ON l.id=n.lease_id JOIN app.units u ON u.id=l.unit_id
                LEFT JOIN app.lease_notice_contexts c ON c.notice_id=n.id WHERE n.id=p_notice
        $$;
        CREATE FUNCTION app.lease_notice_read(p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_items jsonb; v_total bigint;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Notice page is invalid' USING ERRCODE='P5502'; END IF;
            SELECT count(*) INTO v_total FROM app.termination_notices WHERE lease_id=p_lease;
            SELECT COALESCE(jsonb_agg(app.lease_notice_snapshot(page.id) ORDER BY page.notice_date,page.occurred_at,page.id),'[]'::jsonb)
                INTO v_items FROM (SELECT id,notice_date,occurred_at FROM app.termination_notices WHERE lease_id=p_lease
                    ORDER BY notice_date,occurred_at,id LIMIT p_limit OFFSET p_offset) page;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset);
        END $$;
        CREATE FUNCTION app.lease_notice_record(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_saved app.lease_notice_commands%ROWTYPE; v_lease app.leases%ROWTYPE;
        DECLARE v_previous app.termination_notices%ROWTYPE; v_notice uuid; v_supersedes uuid;
        DECLARE v_version integer; v_date date; v_intended date; v_now timestamptz; v_timezone text;
        DECLARE v_field text; v_max integer; v_result jsonb; v_response jsonb;
        BEGIN
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property FOR SHARE;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent)<>'object'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            THEN RAISE EXCEPTION 'Notice command identity is invalid' USING ERRCODE='P5502'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-notice:'||p_property::text||':'||p_actor::text||':'||p_key::text,0));
            SELECT * INTO v_saved FROM app.lease_notice_commands
                WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_saved.request_digest<>p_digest OR v_saved.request_intent IS DISTINCT FROM p_intent OR v_saved.lease_id<>p_lease
                THEN RAISE EXCEPTION 'Notice command key was reused' USING ERRCODE='P5505'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_saved.response_body);
            END IF;
            IF p_intent-ARRAY['notice_id','expected_lease_version','notice_date','intended_termination_date','notice_text',
                'governing_lease_provision','approved_grounds','notice_period_terms','evidence_reference','communication_record',
                'authorization_reference','reason','supersedes_notice_id']<>'{}'::jsonb
                OR jsonb_typeof(p_intent->'notice_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'expected_lease_version') IS DISTINCT FROM 'number'
                OR (p_intent->>'expected_lease_version')!~'^[1-9][0-9]{0,9}$'
                OR jsonb_typeof(p_intent->'notice_date') IS DISTINCT FROM 'string'
                OR (p_intent->>'notice_date')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                OR NOT (p_intent ? 'intended_termination_date') OR NOT (p_intent ? 'supersedes_notice_id')
                OR (p_intent->'intended_termination_date'<>'null'::jsonb AND
                    (jsonb_typeof(p_intent->'intended_termination_date')<>'string' OR (p_intent->>'intended_termination_date')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'))
                OR (p_intent->'supersedes_notice_id'<>'null'::jsonb AND jsonb_typeof(p_intent->'supersedes_notice_id')<>'string')
            THEN RAISE EXCEPTION 'Notice command input is invalid' USING ERRCODE='P5502'; END IF;
            FOREACH v_field IN ARRAY ARRAY['notice_text','governing_lease_provision','approved_grounds','notice_period_terms',
                'evidence_reference','communication_record','authorization_reference','reason'] LOOP
                v_max:=CASE WHEN v_field='notice_text' THEN 5000 WHEN v_field IN ('evidence_reference','authorization_reference','reason') THEN 500 ELSE 2000 END;
                IF jsonb_typeof(p_intent->v_field) IS DISTINCT FROM 'string' OR (p_intent->>v_field)<>btrim(p_intent->>v_field)
                    OR length(p_intent->>v_field) NOT BETWEEN 1 AND v_max
                THEN RAISE EXCEPTION 'Notice evidence is invalid' USING ERRCODE='P5502'; END IF;
            END LOOP;
            BEGIN
                v_notice:=(p_intent->>'notice_id')::uuid; v_version:=(p_intent->>'expected_lease_version')::integer;
                v_date:=(p_intent->>'notice_date')::date; v_intended:=(p_intent->>'intended_termination_date')::date;
                v_supersedes:=(p_intent->>'supersedes_notice_id')::uuid;
            EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR datetime_field_overflow OR invalid_datetime_format THEN
                RAISE EXCEPTION 'Notice date or identity is invalid' USING ERRCODE='P5502';
            END;
            IF v_notice='00000000-0000-0000-0000-000000000000' OR v_supersedes='00000000-0000-0000-0000-000000000000'
                OR v_supersedes=v_notice OR NOT isfinite(v_date)
                OR (v_intended IS NOT NULL AND (NOT isfinite(v_intended) OR v_intended<v_date))
            THEN RAISE EXCEPTION 'Notice chronology or identity is invalid' USING ERRCODE='P5502'; END IF;
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=p_lease FOR UPDATE;
            v_now:=clock_timestamp();
            IF v_lease.version<>v_version OR v_lease.status NOT IN ('SIGNED','TERMINATED') OR v_lease.signed_at IS NULL
                OR v_date<timezone(v_timezone,v_lease.signed_at)::date OR v_date>timezone(v_timezone,v_now)::date
                OR EXISTS(SELECT 1 FROM app.termination_notices WHERE id=v_notice)
            THEN RAISE EXCEPTION 'Lease or notice source changed' USING ERRCODE='P5503'; END IF;
            IF v_supersedes IS NOT NULL THEN
                SELECT * INTO v_previous FROM app.termination_notices WHERE id=v_supersedes AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Notice correction source not found' USING ERRCODE='P5501'; END IF;
                IF v_previous.occurred_at>v_now OR EXISTS(SELECT 1 FROM app.lease_notice_contexts WHERE supersedes_notice_id=v_supersedes)
                THEN RAISE EXCEPTION 'Notice correction source changed' USING ERRCODE='P5503'; END IF;
            END IF;
            INSERT INTO app.termination_notices VALUES(v_notice,p_lease,v_date,v_intended,p_intent->>'notice_text',
                p_intent->>'governing_lease_provision',v_now,p_actor);
            INSERT INTO app.lease_notice_contexts VALUES(v_notice,v_version,p_intent->>'approved_grounds',p_intent->>'notice_period_terms',
                p_intent->>'evidence_reference',p_intent->>'communication_record',p_intent->>'authorization_reference',p_intent->>'reason',v_supersedes);
            v_result:=app.lease_notice_snapshot(v_notice);
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,linked_source_event_id,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_now,timezone(v_timezone,v_now)::date,p_actor,'lease.notice.record','termination_notice',v_notice,
                p_intent->>'reason',p_intent->>'authorization_reference',p_property,
                CASE WHEN v_supersedes IS NULL THEN NULL ELSE to_jsonb(v_previous) END,v_result,p_key,'API','SUCCEEDED',
                jsonb_build_object('capability','leases.terminate','signed_lease_provision',p_intent->>'governing_lease_provision'),
                v_notice,v_lease.primary_tenant_id,p_lease);
            v_response:=jsonb_build_object('data',v_result,'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.lease_notice_commands VALUES(p_property,p_actor,p_key,p_lease,v_notice,p_digest,p_intent,v_response,v_now);
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    for table in ("lease_notice_contexts", "lease_notice_commands"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
    for signature in (
        "app.validate_lease_notice_context()",
        "app.lease_notice_snapshot(uuid)",
        "app.lease_notice_read(uuid,uuid,uuid,integer,integer)",
        "app.lease_notice_record(uuid,uuid,uuid,uuid,text,jsonb,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_notice_read(uuid,uuid,uuid,integer,integer) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_notice_record(uuid,uuid,uuid,uuid,text,jsonb,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Lease notice evidence is forward-only")
