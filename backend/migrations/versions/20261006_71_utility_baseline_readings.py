# ruff: noqa: E501
"""Record a Utility baseline Reading event per Lease and make it the Customer's responsibility boundary.

Additive and relaxing only. A Lease without a baseline keeps every existing boundary and
billing result. The monthly Utility run skips, rather than fails, a period that no Customer
is responsible for yet (NOT_MOVED_IN) or ever (PROPERTY_BORNE_CONSUMPTION).
"""

from alembic import op
from sqlalchemy import text

revision = "20261006_71"
down_revision = "20261005_70"
branch_labels = None
depends_on = None

TABLES = ("utility_baseline_events", "utility_baseline_items", "utility_baseline_commands")
RECORD = "app.utility_baseline_record(uuid,uuid,uuid,uuid,text,jsonb,text)"
READ = "app.utility_baseline_read(uuid,uuid,uuid,integer,integer)"
WINDOW = "app.utility_responsibility_window_is_stable(uuid,date,date)"
GUARD = "app.guard_utility_responsibility_change()"
MISSING_SOURCES = "app.billing_run_has_missing_eligible_sources(uuid,integer)"
SCHEDULED_ITEM = "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamptz)"


def _definition(signature: str) -> str:
    return (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = _definition(signature)
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Utility source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def _patch_scheduled_item() -> None:
    definition = _definition(SCHEDULED_ITEM)
    declaration = "DECLARE v_consumption_period_id uuid:=p_source_id;"
    start_marker = "SELECT lease.id,lease.primary_tenant_id,lease.unit_id\n"
    end_marker = "USING ERRCODE='P0002';\n                END IF;"
    if (
        definition.count(declaration) != 1
        or definition.count(start_marker) != 1
        or definition.count(end_marker) != 1
    ):
        raise RuntimeError("Scheduled Utility responsibility contract changed")
    start = definition.index(start_marker)
    end = definition.index(end_marker, start) + len(end_marker)
    resolver = """SELECT resp.outcome,resp.lease_id,resp.customer_id,resp.unit_id
                    INTO v_resp_outcome,v_lease_id,v_customer_id,v_unit_id
                FROM app.utility_period_responsibility(
                    v_period.unit_id,v_period.start_date,v_period.end_date) AS resp;
                IF v_resp_outcome IN ('NOT_MOVED_IN','PROPERTY_BORNE') THEN
                    INSERT INTO app.billing_run_items(
                        id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                        source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                    ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                        v_run.period_start,v_run.period_end,'SKIPPED',
                        CASE v_resp_outcome WHEN 'NOT_MOVED_IN' THEN 'NOT_MOVED_IN'
                            ELSE 'PROPERTY_BORNE_CONSUMPTION' END,clock_timestamp());
                    RETURN 'SKIPPED';
                END IF;
                IF v_resp_outcome IS DISTINCT FROM 'RESPONSIBLE' THEN
                    RAISE EXCEPTION 'Utility responsibility evidence was not found'
                        USING ERRCODE='P0002';
                END IF;"""
    definition = definition[:start] + resolver + definition[end:]
    definition = definition.replace(
        declaration, declaration + "\n        DECLARE v_resp_outcome text;"
    )
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.utility_baseline_events (
            id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            baseline_date date NOT NULL CHECK(isfinite(baseline_date)),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,500)),
            evidence_reference text NOT NULL CHECK(app.lease_notice_text_valid(evidence_reference,500)),
            supersedes_event_id uuid UNIQUE REFERENCES app.utility_baseline_events(id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CHECK(supersedes_event_id IS NULL OR supersedes_event_id<>id)
        );
        CREATE UNIQUE INDEX utility_baseline_events_one_root_per_lease
            ON app.utility_baseline_events(lease_id) WHERE supersedes_event_id IS NULL;

        CREATE TABLE app.utility_baseline_items (
            event_id uuid NOT NULL REFERENCES app.utility_baseline_events(id) ON DELETE RESTRICT,
            meter_id uuid NOT NULL,
            unit_id uuid NOT NULL,
            utility_type text NOT NULL CHECK(utility_type IN ('ELECTRICITY','WATER')),
            reading_id uuid NOT NULL,
            reading_date date NOT NULL CHECK(isfinite(reading_date)),
            reading_value numeric(20,6) NOT NULL CHECK(reading_value>=0),
            reading_version integer NOT NULL CHECK(reading_version>0),
            reading_validated_at timestamptz NOT NULL CHECK(isfinite(reading_validated_at)),
            PRIMARY KEY(event_id,meter_id),
            FOREIGN KEY(meter_id,unit_id,utility_type) REFERENCES app.utility_meters(id,unit_id,utility_type) ON DELETE RESTRICT,
            FOREIGN KEY(reading_id,meter_id) REFERENCES app.utility_readings(id,meter_id) ON DELETE RESTRICT
        );

        CREATE TABLE app.utility_baseline_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            event_id uuid NOT NULL UNIQUE REFERENCES app.utility_baseline_events(id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            PRIMARY KEY(property_id,actor_id,idempotency_key)
        );

        -- First day of the Customer's responsibility: the day after the current baseline Reading.
        CREATE FUNCTION app.utility_baseline_boundary(p_lease uuid)
        RETURNS date LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT head.baseline_date+1 FROM app.utility_baseline_events AS head
            WHERE head.lease_id=p_lease AND NOT EXISTS (
                SELECT 1 FROM app.utility_baseline_events AS successor
                WHERE successor.supersedes_event_id=head.id)
        $$;

        CREATE FUNCTION app.utility_baseline_snapshot(p_event uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT jsonb_build_object('event_id',e.id,'property_id',e.property_id,'lease_id',e.lease_id,
                'unit_id',e.unit_id,'baseline_date',e.baseline_date,'responsibility_starts_on',e.baseline_date+1,
                'reason',e.reason,'evidence_reference',e.evidence_reference,
                'supersedes_event_id',e.supersedes_event_id,'occurred_at',e.occurred_at,'actor_id',e.actor_id,
                'items',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'meter_id',i.meter_id,'utility_type',i.utility_type,'reading_id',i.reading_id,
                    'reading_date',i.reading_date,'reading_value',i.reading_value::text,
                    'reading_version',i.reading_version,'validated_at',i.reading_validated_at) ORDER BY i.meter_id)
                    FROM app.utility_baseline_items i WHERE i.event_id=e.id),'[]'::jsonb),
                'creates_reading',false,'creates_charge',false)
            FROM app.utility_baseline_events e WHERE e.id=p_event
        $$;

        CREATE FUNCTION app.utility_baseline_audit_snapshot(p_event uuid,p_previous boolean)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog SET TimeZone='UTC' AS $$
            SELECT CASE WHEN p_previous THEN COALESCE(
                    (SELECT app.utility_baseline_snapshot(e.supersedes_event_id)
                        FROM app.utility_baseline_events e WHERE e.id=p_event AND e.supersedes_event_id IS NOT NULL),
                    jsonb_build_object('event_id',NULL,'items','[]'::jsonb))
                ELSE app.utility_baseline_snapshot(p_event) END
        $$;

        CREATE FUNCTION app.guard_utility_baseline_event()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_l app.leases%ROWTYPE; v_prior app.utility_baseline_events%ROWTYPE;
        BEGIN
            SELECT * INTO v_l FROM app.leases WHERE id=NEW.lease_id;
            IF v_l.id IS NULL OR v_l.status<>'SIGNED' OR v_l.unit_id IS DISTINCT FROM NEW.unit_id
                OR NOT EXISTS(SELECT 1 FROM app.units WHERE id=NEW.unit_id AND property_id=NEW.property_id)
                OR NEW.baseline_date>v_l.start_date
                OR EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=NEW.lease_id)
            THEN RAISE EXCEPTION 'Utility baseline must precede handover of a SIGNED Lease and not follow its start date'
                USING ERRCODE='23514'; END IF;
            IF NEW.supersedes_event_id IS NOT NULL THEN
                SELECT * INTO v_prior FROM app.utility_baseline_events WHERE id=NEW.supersedes_event_id;
                IF v_prior.id IS NULL OR v_prior.lease_id IS DISTINCT FROM NEW.lease_id
                    OR v_prior.baseline_date>=NEW.baseline_date OR v_prior.occurred_at>NEW.occurred_at
                THEN RAISE EXCEPTION 'Utility baseline correction source disagrees' USING ERRCODE='23514'; END IF;
            END IF;
            IF EXISTS(SELECT 1 FROM app.utility_consumption_periods AS period
                    WHERE period.unit_id=NEW.unit_id AND period.start_date<NEW.baseline_date+1
                        AND period.end_date>=NEW.baseline_date+1)
                OR EXISTS(SELECT 1 FROM app.broken_meter_estimation_cases AS estimation
                    WHERE estimation.unit_id=NEW.unit_id AND estimation.unmeasured_start_date<NEW.baseline_date+1
                        AND estimation.unmeasured_end_date>=NEW.baseline_date+1)
            THEN RAISE EXCEPTION 'Utility baseline would split an existing Utility period' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_utility_baseline_complete()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_id uuid; v_e app.utility_baseline_events%ROWTYPE; v_required uuid[];
        BEGIN
            v_id:=CASE WHEN TG_TABLE_NAME='utility_baseline_events' THEN (to_jsonb(NEW)->>'id')::uuid ELSE (to_jsonb(NEW)->>'event_id')::uuid END;
            SELECT * INTO v_e FROM app.utility_baseline_events WHERE id=v_id;
            SELECT array_agg(id ORDER BY id) INTO v_required FROM app.utility_meters
                WHERE unit_id=v_e.unit_id AND installed_date<=v_e.baseline_date
                    AND (deactivated_date IS NULL OR deactivated_date>=v_e.baseline_date);
            IF v_e.id IS NULL OR v_required IS NULL
                OR v_required IS DISTINCT FROM (SELECT array_agg(meter_id ORDER BY meter_id) FROM app.utility_baseline_items WHERE event_id=v_id)
                OR EXISTS(SELECT 1 FROM app.utility_baseline_items AS i WHERE i.event_id=v_id AND (
                    i.unit_id IS DISTINCT FROM v_e.unit_id OR i.reading_date IS DISTINCT FROM v_e.baseline_date
                    OR NOT EXISTS(SELECT 1 FROM app.utility_readings AS r
                        WHERE r.id=i.reading_id AND r.meter_id=i.meter_id AND r.reading_date=v_e.baseline_date
                            AND r.validated_at IS NOT NULL AND r.validated_at=i.reading_validated_at
                            AND r.reading_value=i.reading_value AND r.version=i.reading_version)))
            THEN RAISE EXCEPTION 'Utility baseline evidence is incomplete' USING ERRCODE='23514'; END IF;
            RETURN NULL;
        END $$;

        -- Who is responsible for a Utility period of a Unit: RESPONSIBLE with the Lease and Customer,
        -- NOT_MOVED_IN (baseline Lease with no Occupancy yet), PROPERTY_BORNE (no Lease covers any
        -- part of it) or UNRESOLVED (the existing failure). A Lease without a baseline keeps the
        -- exact earlier rule.
        CREATE FUNCTION app.utility_period_responsibility(p_unit uuid,p_start date,p_end date)
        RETURNS TABLE(outcome text,lease_id uuid,customer_id uuid,unit_id uuid)
        LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
        DECLARE v_lease uuid; v_customer uuid;
        BEGIN
            SELECT lease.id,lease.primary_tenant_id INTO v_lease,v_customer
            FROM app.leases AS lease
            WHERE lease.unit_id=p_unit AND lease.status IN ('SIGNED','TERMINATED')
              AND app.utility_baseline_boundary(lease.id) IS NULL
              AND lease.start_date<=p_start
              AND COALESCE(lease.actual_termination_date,lease.end_date)>=p_end
              AND EXISTS (SELECT 1 FROM app.lease_signers AS signer
                WHERE signer.lease_id=lease.id AND signer.customer_id=lease.primary_tenant_id
                  AND signer.signed_at IS NOT NULL)
              AND EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                WHERE occupancy.lease_id=lease.id
                  AND occupancy.customer_id=lease.primary_tenant_id
                  AND occupancy.move_in_date<=p_start
                  AND COALESCE(occupancy.move_out_date,p_end)>=p_end)
            ORDER BY lease.start_date DESC,lease.id LIMIT 1;
            IF v_lease IS NOT NULL THEN
                RETURN QUERY SELECT 'RESPONSIBLE'::text,v_lease,v_customer,p_unit; RETURN;
            END IF;
            SELECT lease.id,lease.primary_tenant_id INTO v_lease,v_customer
            FROM app.leases AS lease
            WHERE lease.unit_id=p_unit AND lease.status IN ('SIGNED','TERMINATED')
              AND app.utility_baseline_boundary(lease.id)<=p_start
              AND COALESCE(lease.actual_termination_date,lease.end_date)>=p_end
              AND EXISTS (SELECT 1 FROM app.lease_signers AS signer
                WHERE signer.lease_id=lease.id AND signer.customer_id=lease.primary_tenant_id
                  AND signer.signed_at IS NOT NULL)
            ORDER BY app.utility_baseline_boundary(lease.id) DESC,lease.id LIMIT 1;
            IF v_lease IS NOT NULL THEN
                IF EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                    WHERE occupancy.lease_id=v_lease AND occupancy.customer_id=v_customer) THEN
                    RETURN QUERY SELECT 'RESPONSIBLE'::text,v_lease,v_customer,p_unit; RETURN;
                END IF;
                RETURN QUERY SELECT 'NOT_MOVED_IN'::text,v_lease,v_customer,p_unit; RETURN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM app.leases AS lease
                WHERE lease.unit_id=p_unit AND lease.status IN ('SIGNED','TERMINATED')
                  AND COALESCE(app.utility_baseline_boundary(lease.id),lease.start_date)<=p_end
                  AND COALESCE(lease.actual_termination_date,lease.end_date)>=p_start) THEN
                RETURN QUERY SELECT 'PROPERTY_BORNE'::text,NULL::uuid,NULL::uuid,p_unit; RETURN;
            END IF;
            RETURN QUERY SELECT 'UNRESOLVED'::text,NULL::uuid,NULL::uuid,p_unit;
        END $$;

        CREATE FUNCTION app.utility_baseline_read(p_property uuid,p_lease uuid,p_actor uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_items jsonb; v_total integer;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 20 OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Utility baseline page is invalid' USING ERRCODE='P5N02'; END IF;
            SELECT count(*) INTO v_total FROM app.utility_baseline_events WHERE lease_id=p_lease;
            SELECT COALESCE(jsonb_agg(value ORDER BY occurred_at DESC,id DESC),'[]'::jsonb) INTO v_items FROM (
                SELECT e.id,e.occurred_at,app.utility_baseline_snapshot(e.id)||jsonb_build_object(
                    'event_status',CASE WHEN EXISTS(SELECT 1 FROM app.utility_baseline_events s WHERE s.supersedes_event_id=e.id)
                        THEN 'SUPERSEDED' ELSE 'CURRENT' END) value
                FROM app.utility_baseline_events e WHERE e.lease_id=p_lease
                ORDER BY e.occurred_at DESC,e.id DESC LIMIT p_limit OFFSET p_offset) page;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset,
                'creates_reading',false,'creates_charge',false);
        END $$;

        CREATE FUNCTION app.utility_baseline_record(p_property uuid,p_lease uuid,p_actor uuid,p_key uuid,
            p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
        DECLARE v_c app.utility_baseline_commands%ROWTYPE; v_l app.leases%ROWTYPE;
            v_prior app.utility_baseline_events%ROWTYPE; v_meter_row app.utility_meters%ROWTYPE;
            v_r app.utility_readings%ROWTYPE; v_item jsonb;
            v_event uuid; v_supersedes uuid; v_date date; v_meter uuid; v_reading uuid;
            v_meters uuid[]:=ARRAY[]::uuid[]; v_readings uuid[]:=ARRAY[]::uuid[]; v_required uuid[];
            v_now timestamptz; v_timezone text; v_audit uuid; v_response jsonb; v_key text; v_index integer;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE NOWAIT;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE NOWAIT;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000' OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent) IS DISTINCT FROM 'object'
            THEN RAISE EXCEPTION 'Utility baseline intent is invalid' USING ERRCODE='P5N02'; END IF;
            IF NOT pg_try_advisory_xact_lock(hashtextextended(p_property::text||'|'||p_actor::text||'|utility-baseline|'||p_key::text,0))
            THEN RAISE EXCEPTION 'Utility baseline command is in use' USING ERRCODE='P5N03'; END IF;
            SELECT * INTO v_c FROM app.utility_baseline_commands WHERE property_id=p_property AND actor_id=p_actor AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_c.lease_id IS DISTINCT FROM p_lease OR v_c.request_digest IS DISTINCT FROM p_digest OR v_c.request_intent IS DISTINCT FROM p_intent
                THEN RAISE EXCEPTION 'Utility baseline key was reused' USING ERRCODE='P5N05'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_c.response_body);
            END IF;
            IF p_intent-ARRAY['event_id','supersedes_event_id','baseline_date','reason','evidence_reference','items']<>'{}'::jsonb
                OR NOT p_intent?&ARRAY['event_id','supersedes_event_id','baseline_date','reason','evidence_reference','items']
                OR jsonb_typeof(p_intent->'event_id') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'supersedes_event_id') NOT IN ('string','null')
                OR jsonb_typeof(p_intent->'baseline_date') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'reason') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'evidence_reference') IS DISTINCT FROM 'string'
                OR jsonb_typeof(p_intent->'items') IS DISTINCT FROM 'array'
                OR NOT app.lease_notice_text_valid(p_intent->>'reason',500)
                OR NOT app.lease_notice_text_valid(p_intent->>'evidence_reference',500)
                OR jsonb_array_length(p_intent->'items') NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Utility baseline fields are invalid' USING ERRCODE='P5N02'; END IF;
            BEGIN
                v_event:=(p_intent->>'event_id')::uuid; v_supersedes:=(p_intent->>'supersedes_event_id')::uuid;
                v_date:=(p_intent->>'baseline_date')::date;
            EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow THEN
                RAISE EXCEPTION 'Utility baseline identity or date is invalid' USING ERRCODE='P5N02';
            END;
            IF v_event='00000000-0000-0000-0000-000000000000' OR v_supersedes='00000000-0000-0000-0000-000000000000'
                OR v_event=v_supersedes OR NOT isfinite(v_date)
            THEN RAISE EXCEPTION 'Utility baseline identity or date is invalid' USING ERRCODE='P5N02'; END IF;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_intent->'items') ORDER BY value->>'meter_id' LOOP
                IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
                    OR v_item-ARRAY['meter_id','reading_id']<>'{}'::jsonb
                    OR NOT v_item?&ARRAY['meter_id','reading_id']
                    OR jsonb_typeof(v_item->'meter_id') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(v_item->'reading_id') IS DISTINCT FROM 'string'
                THEN RAISE EXCEPTION 'Utility baseline item is invalid' USING ERRCODE='P5N02'; END IF;
                BEGIN
                    v_meter:=(v_item->>'meter_id')::uuid; v_reading:=(v_item->>'reading_id')::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'Utility baseline item identity is invalid' USING ERRCODE='P5N02';
                END;
                IF v_meter='00000000-0000-0000-0000-000000000000' OR v_reading='00000000-0000-0000-0000-000000000000'
                    OR v_meter=ANY(v_meters)
                THEN RAISE EXCEPTION 'Utility baseline Meters must be nonzero and unique' USING ERRCODE='P5N02'; END IF;
                v_meters:=array_append(v_meters,v_meter); v_readings:=array_append(v_readings,v_reading);
            END LOOP;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease;
            SELECT timezone_name INTO v_timezone FROM app.properties WHERE id=p_property;
            FOR v_key IN SELECT key FROM unnest(ARRAY['utility-baseline:'||p_lease::text,
                'utility-unit-type:'||v_l.unit_id::text||':'||'ELECTRICITY',
                'utility-unit-type:'||v_l.unit_id::text||':'||'WATER']) keys(key) ORDER BY key LOOP
                IF NOT pg_try_advisory_xact_lock(hashtextextended(v_key,0))
                THEN RAISE EXCEPTION 'Utility baseline source is in use' USING ERRCODE='P5N03'; END IF;
            END LOOP;
            SELECT * INTO STRICT v_l FROM app.leases WHERE id=p_lease FOR SHARE NOWAIT;
            v_now:=clock_timestamp();
            IF v_l.status<>'SIGNED' OR v_date>v_l.start_date
                OR EXISTS(SELECT 1 FROM app.occupancies WHERE lease_id=p_lease)
            THEN RAISE EXCEPTION 'Utility baseline must precede handover of a SIGNED Lease and not follow its start date' USING ERRCODE='P5N02'; END IF;
            IF EXISTS(SELECT 1 FROM app.utility_baseline_events WHERE id=v_event)
            THEN RAISE EXCEPTION 'Utility baseline source changed' USING ERRCODE='P5N03'; END IF;
            IF v_supersedes IS NULL THEN
                IF EXISTS(SELECT 1 FROM app.utility_baseline_events WHERE lease_id=p_lease)
                THEN RAISE EXCEPTION 'Utility baseline source changed' USING ERRCODE='P5N03'; END IF;
            ELSE
                SELECT * INTO v_prior FROM app.utility_baseline_events WHERE id=v_supersedes AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Utility baseline correction source not found' USING ERRCODE='P5N01'; END IF;
                IF EXISTS(SELECT 1 FROM app.utility_baseline_events WHERE supersedes_event_id=v_supersedes)
                THEN RAISE EXCEPTION 'Utility baseline correction source changed' USING ERRCODE='P5N03'; END IF;
                IF v_prior.baseline_date>=v_date
                THEN RAISE EXCEPTION 'A new baseline must be dated after the one it replaces' USING ERRCODE='P5N02'; END IF;
            END IF;
            IF EXISTS(SELECT 1 FROM app.utility_consumption_periods AS period
                    WHERE period.unit_id=v_l.unit_id AND period.start_date<v_date+1 AND period.end_date>=v_date+1)
                OR EXISTS(SELECT 1 FROM app.broken_meter_estimation_cases AS estimation
                    WHERE estimation.unit_id=v_l.unit_id AND estimation.unmeasured_start_date<v_date+1
                        AND estimation.unmeasured_end_date>=v_date+1)
            THEN RAISE EXCEPTION 'Utility baseline would split an existing Utility period' USING ERRCODE='P5N02'; END IF;
            SELECT array_agg(id ORDER BY id) INTO v_required FROM app.utility_meters
                WHERE unit_id=v_l.unit_id AND installed_date<=v_date
                    AND (deactivated_date IS NULL OR deactivated_date>=v_date);
            IF v_required IS NULL OR v_required IS DISTINCT FROM (SELECT array_agg(x ORDER BY x) FROM unnest(v_meters) x)
            THEN RAISE EXCEPTION 'Utility baseline list must cover every applicable Meter once' USING ERRCODE='P5N02'; END IF;
            SET CONSTRAINTS app.utility_baseline_events_complete,app.utility_baseline_items_complete DEFERRED;
            INSERT INTO app.utility_baseline_events(id,property_id,lease_id,unit_id,baseline_date,reason,evidence_reference,
                supersedes_event_id,occurred_at,actor_id)
            VALUES(v_event,p_property,p_lease,v_l.unit_id,v_date,p_intent->>'reason',p_intent->>'evidence_reference',
                v_supersedes,v_now,p_actor);
            FOR v_index IN 1..array_length(v_meters,1) LOOP
                SELECT * INTO STRICT v_meter_row FROM app.utility_meters WHERE id=v_meters[v_index] FOR SHARE NOWAIT;
                SELECT * INTO v_r FROM app.utility_readings WHERE id=v_readings[v_index] AND meter_id=v_meters[v_index] FOR SHARE NOWAIT;
                IF NOT FOUND THEN RAISE EXCEPTION 'Utility baseline Reading was not found' USING ERRCODE='P5N01'; END IF;
                IF v_r.validated_at IS NULL OR v_r.reading_date IS DISTINCT FROM v_date
                THEN RAISE EXCEPTION 'Utility baseline Reading must be validated and dated on the baseline date' USING ERRCODE='P5N02'; END IF;
                INSERT INTO app.utility_baseline_items(event_id,meter_id,unit_id,utility_type,reading_id,reading_date,
                    reading_value,reading_version,reading_validated_at)
                VALUES(v_event,v_meters[v_index],v_meter_row.unit_id,v_meter_row.utility_type,v_r.id,v_r.reading_date,
                    v_r.reading_value,v_r.version,v_r.validated_at);
            END LOOP;
            v_audit:=gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,reason,
                authorization_reference,property_id,previous_state,resulting_state,correlation_id,source,outcome,
                authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,timezone(v_timezone,v_now)::date,p_actor,'utility.baseline.record','utility_baseline',v_event,
                p_intent->>'reason','utility_readings.record',p_property,
                app.utility_baseline_audit_snapshot(v_event,true),app.utility_baseline_audit_snapshot(v_event,false),
                p_key,'API','SUCCEEDED',jsonb_build_object('capability','utility_readings.record','baseline_event_id',v_event),
                v_l.primary_tenant_id,p_lease,v_l.unit_id);
            v_response:=jsonb_build_object('data',app.utility_baseline_snapshot(v_event),'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.utility_baseline_commands VALUES(p_property,p_actor,p_key,p_lease,v_event,v_audit,p_digest,p_intent,v_response,v_now);
            SET CONSTRAINTS app.utility_baseline_events_complete,app.utility_baseline_items_complete IMMEDIATE;
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "CREATE TRIGGER utility_baseline_events_00_guard BEFORE INSERT ON app.utility_baseline_events FOR EACH ROW EXECUTE FUNCTION app.guard_utility_baseline_event()"
    )
    for table in ("utility_baseline_events", "utility_baseline_items"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT ON app.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_utility_baseline_complete()"
        )

    # A baseline replaces the Lease Start Date and the move-in date as the Customer's boundary.
    _patch(
        WINDOW,
        (
            (
                "SELECT lease.start_date AS boundary_date",
                "SELECT COALESCE(app.utility_baseline_boundary(lease.id),lease.start_date) AS boundary_date",
            ),
            (
                "SELECT occupancy.move_in_date",
                "SELECT CASE WHEN app.utility_baseline_boundary(lease.id) IS NULL THEN occupancy.move_in_date END",
            ),
        ),
    )
    _patch(
        GUARD,
        (
            (
                "SELECT (v_new->>'start_date')::date AS boundary_date",
                "SELECT COALESCE(app.utility_baseline_boundary((v_new->>'id')::uuid),(v_new->>'start_date')::date) AS boundary_date",
            ),
            (
                "SELECT (v_new->>'move_in_date')::date",
                "SELECT CASE WHEN app.utility_baseline_boundary((v_new->>'lease_id')::uuid) IS NULL THEN (v_new->>'move_in_date')::date END",
            ),
        ),
    )

    # The monthly run skips a period nobody is responsible for yet or ever, instead of failing.
    op.execute("""
        ALTER TABLE app.billing_run_items
            DROP CONSTRAINT billing_run_items_outcome_shape,
            ADD CONSTRAINT billing_run_items_outcome_shape CHECK (
                (outcome='GENERATED' AND invoice_id IS NOT NULL AND diagnostic_code IS NULL)
                OR (outcome='SKIPPED' AND (
                    (invoice_id IS NOT NULL
                        AND diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS')
                    OR (invoice_id IS NULL AND diagnostic_code IN (
                        'SOURCE_NO_LONGER_ELIGIBLE',
                        'PENDING_FUTURE_ACTUAL_BASIS',
                        'ZERO_AMOUNT_NO_OBLIGATION',
                        'NOT_MOVED_IN',
                        'PROPERTY_BORNE_CONSUMPTION'
                    ))
                ))
                OR (outcome IN ('CONFLICT','ERROR') AND invoice_id IS NULL
                    AND diagnostic_code IS NOT NULL
                    AND length(btrim(diagnostic_code))>0
                    AND length(diagnostic_code)<=100
                    AND diagnostic_code=btrim(diagnostic_code))
            );
    """)
    _patch(
        MISSING_SOURCES,
        (
            (
                "'SOURCE_NO_LONGER_ELIGIBLE','ZERO_AMOUNT_NO_OBLIGATION'",
                "'SOURCE_NO_LONGER_ELIGIBLE','ZERO_AMOUNT_NO_OBLIGATION','NOT_MOVED_IN','PROPERTY_BORNE_CONSUMPTION'",
            ),
        ),
    )
    _patch_scheduled_item()

    for function in (
        "app.utility_baseline_boundary(uuid)",
        "app.utility_baseline_snapshot(uuid)",
        "app.utility_baseline_audit_snapshot(uuid,boolean)",
        "app.guard_utility_baseline_event()",
        "app.validate_utility_baseline_complete()",
        "app.utility_period_responsibility(uuid,date,date)",
        READ,
        RECORD,
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {READ} TO prm_runtime")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD} TO prm_financial")


def downgrade() -> None:
    raise RuntimeError("Utility baseline migration is forward-only")
