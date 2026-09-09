# ruff: noqa: E501
"""Add separate immutable Lease warnings and Rent nonpayment workflows."""

from alembic import op

revision = "20260910_50"
down_revision = "20260909_49"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE TABLE app.rent_nonpayment_cases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            rent_invoice_line_id uuid NOT NULL UNIQUE REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            due_date_snapshot date NOT NULL CHECK(isfinite(due_date_snapshot)),
            opened_at timestamptz NOT NULL CHECK(isfinite(opened_at)),
            opened_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT
        );
        CREATE INDEX rent_nonpayment_cases_lease_history_idx
            ON app.rent_nonpayment_cases(lease_id,opened_at,id);
        CREATE TABLE app.rent_nonpayment_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rent_nonpayment_case_id uuid NOT NULL REFERENCES app.rent_nonpayment_cases(id) ON DELETE RESTRICT,
            event_kind text NOT NULL CHECK(event_kind IN
                ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT','CURE','AUTHORIZED_FOLLOW_UP')),
            event_date date NOT NULL CHECK(isfinite(event_date)),
            remaining_rent_usd_cents bigint NOT NULL CHECK(remaining_rent_usd_cents>=0),
            notice_document_reference text CHECK(notice_document_reference=btrim(notice_document_reference)
                AND length(notice_document_reference) BETWEEN 1 AND 500),
            communication_record text CHECK(communication_record=btrim(communication_record)
                AND length(communication_record) BETWEEN 1 AND 2000),
            reason text NOT NULL CHECK(reason=btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            authorization_reference text CHECK(authorization_reference=btrim(authorization_reference)
                AND length(authorization_reference) BETWEEN 1 AND 500),
            CHECK(event_kind<>'TWENTY_DAY_WARNING' OR notice_document_reference IS NOT NULL),
            CHECK(event_kind<>'AUTHORIZED_FOLLOW_UP' OR authorization_reference IS NOT NULL)
        );
        CREATE UNIQUE INDEX rent_nonpayment_warning_once_idx ON app.rent_nonpayment_events(rent_nonpayment_case_id)
            WHERE event_kind='TWENTY_DAY_WARNING';
        CREATE UNIQUE INDEX rent_nonpayment_default_once_idx ON app.rent_nonpayment_events(rent_nonpayment_case_id)
            WHERE event_kind='THIRTY_DAY_SERIOUS_DEFAULT';
        CREATE INDEX rent_nonpayment_events_case_history_idx ON app.rent_nonpayment_events(rent_nonpayment_case_id,occurred_at,id);
        CREATE TABLE app.lease_enforcement_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK(action IN ('WARNING','OPEN_CASE','EVENT')),
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            request_intent jsonb NOT NULL CHECK(jsonb_typeof(request_intent)='object'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            case_id uuid REFERENCES app.rent_nonpayment_cases(id) ON DELETE RESTRICT,
            response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
            completed_at timestamptz NOT NULL,
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );

        CREATE FUNCTION app.lease_enforcement_scope(p_property uuid,p_lease uuid,p_actor uuid)
        RETURNS void LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Lease enforcement actor is not active' USING ERRCODE='P5406'; END IF;
            IF p_property IS NULL OR p_lease IS NULL OR NOT EXISTS(
                SELECT 1 FROM app.leases lease JOIN app.units unit ON unit.id=lease.unit_id
                    WHERE lease.id=p_lease AND unit.property_id=p_property)
            THEN RAISE EXCEPTION 'Lease enforcement resource not found' USING ERRCODE='P5401'; END IF;
        END $$;

        CREATE FUNCTION app.rent_nonpayment_milestone_eligible(p_kind text,p_due date,
            p_as_of timestamptz,p_balance bigint,p_prior_milestone boolean)
        RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
            SELECT COALESCE(CASE p_kind
                WHEN 'TWENTY_DAY_WARNING' THEN p_balance>0 AND timezone('Asia/Phnom_Penh',p_as_of)::date-p_due>=20
                WHEN 'THIRTY_DAY_SERIOUS_DEFAULT' THEN p_balance>0 AND timezone('Asia/Phnom_Penh',p_as_of)::date-p_due>=30
                WHEN 'CURE' THEN p_balance=0 AND p_prior_milestone
                WHEN 'AUTHORIZED_FOLLOW_UP' THEN p_balance>=0
                ELSE false END,false)
        $$;

        CREATE FUNCTION app.validate_rent_nonpayment_case()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_line app.invoice_lines%ROWTYPE;
        BEGIN
            PERFORM app.lock_payment_allocation_target('INVOICE',NEW.invoice_id);
            SELECT * INTO v_invoice FROM app.invoices WHERE id=NEW.invoice_id;
            SELECT * INTO v_line FROM app.invoice_lines WHERE id=NEW.rent_invoice_line_id FOR SHARE;
            PERFORM app.lease_enforcement_scope(app.invoice_property_id(NEW.invoice_id),NEW.lease_id,NEW.opened_by);
            IF v_invoice.id IS NULL OR v_line.id IS NULL OR v_line.invoice_id IS DISTINCT FROM v_invoice.id
                OR v_invoice.lease_id IS DISTINCT FROM NEW.lease_id
                OR v_line.source_lease_id IS DISTINCT FROM NEW.lease_id
                OR v_invoice.customer_id IS DISTINCT FROM NEW.customer_id
                OR v_line.category IS DISTINCT FROM 'RENT' OR v_invoice.status IN ('DRAFT','VOID')
                OR v_invoice.issued_at IS NULL OR v_invoice.issued_at>NEW.opened_at OR NEW.opened_at>clock_timestamp()
                OR v_invoice.due_date IS DISTINCT FROM NEW.due_date_snapshot
                OR NEW.id='00000000-0000-0000-0000-000000000000'
            THEN RAISE EXCEPTION 'Rent nonpayment case source is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER rent_nonpayment_case_source BEFORE INSERT ON app.rent_nonpayment_cases
            FOR EACH ROW EXECUTE FUNCTION app.validate_rent_nonpayment_case();

        CREATE FUNCTION app.validate_rent_nonpayment_event()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_case app.rent_nonpayment_cases%ROWTYPE; v_invoice app.invoices%ROWTYPE;
        DECLARE v_balance bigint; v_days integer; v_latest timestamptz;
        BEGIN
            SELECT * INTO STRICT v_case FROM app.rent_nonpayment_cases WHERE id=NEW.rent_nonpayment_case_id;
            PERFORM app.lock_payment_allocation_target('INVOICE',v_case.invoice_id);
            PERFORM 1 FROM app.invoice_lines WHERE id=v_case.rent_invoice_line_id FOR SHARE;
            SELECT * INTO STRICT v_invoice FROM app.invoices WHERE id=v_case.invoice_id;
            PERFORM app.lease_enforcement_scope(app.invoice_property_id(v_case.invoice_id),v_case.lease_id,NEW.actor_id);
            v_balance:=app.invoice_line_outstanding(v_case.rent_invoice_line_id);
            v_days:=NEW.event_date-v_case.due_date_snapshot;
            SELECT greatest(v_case.opened_at,app.allocation_target_latest_at('INVOICE',v_case.invoice_id),
                max(event.occurred_at)) INTO v_latest FROM app.rent_nonpayment_events event
                WHERE event.rent_nonpayment_case_id=v_case.id;
            IF v_invoice.status IN ('DRAFT','VOID') OR v_invoice.issued_at IS NULL
                OR NEW.occurred_at<v_latest OR NEW.occurred_at>clock_timestamp() OR NEW.event_date IS DISTINCT FROM timezone('Asia/Phnom_Penh',NEW.occurred_at)::date
                OR NEW.remaining_rent_usd_cents IS DISTINCT FROM v_balance
                OR NEW.id='00000000-0000-0000-0000-000000000000'
                OR NOT app.rent_nonpayment_milestone_eligible(NEW.event_kind,v_case.due_date_snapshot,NEW.occurred_at,v_balance,EXISTS(
                    SELECT 1 FROM app.rent_nonpayment_events previous
                    WHERE previous.rent_nonpayment_case_id=v_case.id
                        AND previous.event_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT')))
            THEN RAISE EXCEPTION 'Rent nonpayment event source or eligibility is invalid' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER rent_nonpayment_event_source BEFORE INSERT ON app.rent_nonpayment_events
            FOR EACH ROW EXECUTE FUNCTION app.validate_rent_nonpayment_event();

        CREATE FUNCTION app.rent_nonpayment_case_snapshot(p_case uuid,p_as_of timestamptz)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
            SELECT jsonb_build_object(
                'id',c.id,'lease_id',c.lease_id,'customer_id',c.customer_id,
                'property_id',app.invoice_property_id(c.invoice_id),'invoice_id',c.invoice_id,
                'rent_invoice_line_id',c.rent_invoice_line_id,'due_date_snapshot',c.due_date_snapshot,
                'opened_at',c.opened_at,'opened_by',c.opened_by,
                'assessment',jsonb_build_object('as_of',p_as_of,'timezone','Asia/Phnom_Penh',
                    'business_date',timezone('Asia/Phnom_Penh',p_as_of)::date,
                    'days_overdue',greatest(0,timezone('Asia/Phnom_Penh',p_as_of)::date-c.due_date_snapshot),
                    'invoice_status',i.status,'source_applicable',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of,
                    'remaining_rent',jsonb_build_object('currency','USD','minor_units',balance.amount),
                    'twenty_day_warning_eligible',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                        AND app.rent_nonpayment_milestone_eligible('TWENTY_DAY_WARNING',c.due_date_snapshot,p_as_of,balance.amount,history.warning OR history.serious_default)
                        AND NOT history.warning,
                    'thirty_day_default_eligible',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                        AND app.rent_nonpayment_milestone_eligible('THIRTY_DAY_SERIOUS_DEFAULT',c.due_date_snapshot,p_as_of,balance.amount,history.warning OR history.serious_default)
                        AND NOT history.serious_default,
                    'cure_eligible',i.status NOT IN ('DRAFT','VOID') AND i.issued_at<=p_as_of
                        AND app.rent_nonpayment_milestone_eligible('CURE',c.due_date_snapshot,p_as_of,balance.amount,history.warning OR history.serious_default),
                    'warning_recorded',history.warning,'serious_default_recorded',history.serious_default),
                'event_count',history.event_count)
            FROM app.rent_nonpayment_cases c JOIN app.invoices i ON i.id=c.invoice_id
            CROSS JOIN LATERAL (SELECT app.invoice_line_outstanding_at(c.rent_invoice_line_id,p_as_of) AS amount) balance
            CROSS JOIN LATERAL (SELECT count(*) AS event_count,
                COALESCE(bool_or(event_kind='TWENTY_DAY_WARNING'),false) AS warning,
                COALESCE(bool_or(event_kind='THIRTY_DAY_SERIOUS_DEFAULT'),false) AS serious_default
                FROM app.rent_nonpayment_events e WHERE e.rent_nonpayment_case_id=c.id AND e.occurred_at<=p_as_of) history
            WHERE c.id=p_case
        $$;

        CREATE FUNCTION app.lease_enforcement_read(p_property uuid,p_lease uuid,p_actor uuid,
            p_kind text,p_case uuid,p_limit integer,p_offset integer)
        RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_items jsonb; v_total bigint; v_case app.rent_nonpayment_cases%ROWTYPE;
        BEGIN
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_kind IS NULL OR p_kind NOT IN ('WARNINGS','CASES','CASE','EVENTS')
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_offset IS NULL OR p_offset NOT BETWEEN 0 AND 1000000
            THEN RAISE EXCEPTION 'Lease enforcement read is invalid' USING ERRCODE='P5402'; END IF;
            IF p_kind IN ('CASE','EVENTS') THEN
                SELECT * INTO v_case FROM app.rent_nonpayment_cases WHERE id=p_case AND lease_id=p_lease;
                IF NOT FOUND THEN RAISE EXCEPTION 'Rent nonpayment case not found' USING ERRCODE='P5401'; END IF;
            END IF;
            IF p_kind='CASE' THEN RETURN app.rent_nonpayment_case_snapshot(p_case,statement_timestamp());
            ELSIF p_kind='WARNINGS' THEN
                SELECT count(*) INTO v_total FROM app.lease_violation_warnings WHERE lease_id=p_lease;
                SELECT COALESCE(jsonb_agg(to_jsonb(item) ORDER BY warning_sequence,id),'[]'::jsonb) INTO v_items
                FROM (SELECT * FROM app.lease_violation_warnings WHERE lease_id=p_lease
                    ORDER BY warning_sequence,id LIMIT p_limit OFFSET p_offset) item;
            ELSIF p_kind='CASES' THEN
                SELECT count(*) INTO v_total FROM app.rent_nonpayment_cases WHERE lease_id=p_lease;
                SELECT COALESCE(jsonb_agg(app.rent_nonpayment_case_snapshot(id,statement_timestamp()) ORDER BY opened_at,id),'[]'::jsonb) INTO v_items
                FROM (SELECT * FROM app.rent_nonpayment_cases WHERE lease_id=p_lease
                    ORDER BY opened_at,id LIMIT p_limit OFFSET p_offset) item;
            ELSE
                SELECT count(*) INTO v_total FROM app.rent_nonpayment_events WHERE rent_nonpayment_case_id=p_case;
                SELECT COALESCE(jsonb_agg(to_jsonb(item) ORDER BY occurred_at,id),'[]'::jsonb) INTO v_items
                FROM (SELECT * FROM app.rent_nonpayment_events WHERE rent_nonpayment_case_id=p_case
                    ORDER BY occurred_at,id LIMIT p_limit OFFSET p_offset) item;
            END IF;
            RETURN jsonb_build_object('items',v_items,'total',v_total,'limit',p_limit,'offset',p_offset);
        END $$;

        CREATE FUNCTION app.lease_enforcement_command(p_property uuid,p_lease uuid,p_case uuid,
            p_actor uuid,p_action text,p_key uuid,p_digest text,p_intent jsonb,p_request_id text)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET timezone='UTC' AS $$
        DECLARE v_saved app.lease_enforcement_commands%ROWTYPE;
        DECLARE v_invoice app.invoices%ROWTYPE; v_case app.rent_nonpayment_cases%ROWTYPE;
        DECLARE v_line app.invoice_lines%ROWTYPE; v_event app.rent_nonpayment_events%ROWTYPE;
        DECLARE v_result jsonb; v_response jsonb; v_now timestamptz; v_id uuid; v_reason text;
        DECLARE v_capability text; v_entity text; v_customer uuid; v_balance bigint;
        DECLARE v_kind text; v_date date; v_days integer; v_sequence integer;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property FOR SHARE;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            IF p_action IS NULL OR p_action NOT IN ('WARNING','OPEN_CASE','EVENT')
                OR p_key IS NULL OR p_key='00000000-0000-0000-0000-000000000000'
                OR p_digest IS NULL OR p_digest!~'^[0-9a-f]{64}$'
                OR p_intent IS NULL OR jsonb_typeof(p_intent)<>'object'
                OR p_request_id IS NULL OR p_request_id!~'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
                OR (p_action='EVENT') IS DISTINCT FROM (p_case IS NOT NULL)
            THEN RAISE EXCEPTION 'Lease enforcement command identity is invalid' USING ERRCODE='P5402'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('lease-enforcement:'||p_property::text||':'||p_actor::text||':'||p_action||':'||p_key::text,0));
            SELECT * INTO v_saved FROM app.lease_enforcement_commands
                WHERE property_id=p_property AND actor_id=p_actor AND action=p_action AND idempotency_key=p_key;
            IF FOUND THEN
                IF v_saved.request_digest<>p_digest OR v_saved.request_intent IS DISTINCT FROM p_intent
                    OR v_saved.lease_id<>p_lease OR v_saved.case_id IS DISTINCT FROM p_case
                THEN RAISE EXCEPTION 'Lease enforcement key was reused' USING ERRCODE='P5405'; END IF;
                RETURN jsonb_build_object('status_code',201,'body',v_saved.response_body);
            END IF;
            v_reason:=p_intent->>'reason';
            IF jsonb_typeof(p_intent->'reason') IS DISTINCT FROM 'string'
                OR v_reason<>btrim(v_reason) OR length(v_reason) NOT BETWEEN 1 AND 500
            THEN RAISE EXCEPTION 'Lease enforcement reason is invalid' USING ERRCODE='P5402'; END IF;
            v_id:=gen_random_uuid();
            IF p_action='WARNING' THEN
                IF p_intent-ARRAY['reason','warning_sequence','violation_date','warning_date','violation_description','lease_provision','communication_record']<>'{}'::jsonb
                    OR jsonb_typeof(p_intent->'warning_sequence') IS DISTINCT FROM 'number'
                    OR (p_intent->>'warning_sequence')!~'^[1-9][0-9]{0,4}$'
                    OR jsonb_typeof(p_intent->'violation_date') IS DISTINCT FROM 'string'
                    OR jsonb_typeof(p_intent->'warning_date') IS DISTINCT FROM 'string'
                    OR (p_intent->>'violation_date')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                    OR (p_intent->>'warning_date')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN RAISE EXCEPTION 'Lease warning input is invalid' USING ERRCODE='P5402'; END IF;
                FOREACH v_kind IN ARRAY ARRAY['violation_description','lease_provision','communication_record'] LOOP
                    IF jsonb_typeof(p_intent->v_kind) IS DISTINCT FROM 'string'
                        OR (p_intent->>v_kind)<>btrim(p_intent->>v_kind)
                        OR length(p_intent->>v_kind) NOT BETWEEN 1 AND 2000
                    THEN RAISE EXCEPTION 'Lease warning evidence is invalid' USING ERRCODE='P5402'; END IF;
                END LOOP;
                v_sequence:=(p_intent->>'warning_sequence')::integer;
                IF v_sequence>32767 OR NOT isfinite((p_intent->>'violation_date')::date)
                    OR NOT isfinite((p_intent->>'warning_date')::date)
                THEN RAISE EXCEPTION 'Lease warning dates or sequence invalid' USING ERRCODE='P5402'; END IF;
                PERFORM 1 FROM app.leases WHERE id=p_lease FOR UPDATE;
                IF EXISTS(SELECT 1 FROM app.lease_violation_warnings WHERE lease_id=p_lease AND warning_sequence=v_sequence)
                THEN RAISE EXCEPTION 'Lease warning sequence exists' USING ERRCODE='P5403'; END IF;
                v_now:=clock_timestamp();
                INSERT INTO app.lease_violation_warnings VALUES(v_id,p_lease,v_sequence,
                    (p_intent->>'violation_date')::date,(p_intent->>'warning_date')::date,
                    p_intent->>'violation_description',p_intent->>'lease_provision',p_intent->>'communication_record',v_now,p_actor);
                SELECT to_jsonb(warning) INTO v_result FROM app.lease_violation_warnings warning WHERE id=v_id;
                SELECT primary_tenant_id INTO v_customer FROM app.leases WHERE id=p_lease;
                v_capability:='leases.warn'; v_entity:='lease_violation_warning';
            ELSE
                IF p_action='OPEN_CASE' THEN
                    IF p_intent-ARRAY['reason','rent_invoice_line_id']<>'{}'::jsonb
                        OR jsonb_typeof(p_intent->'rent_invoice_line_id') IS DISTINCT FROM 'string'
                    THEN RAISE EXCEPTION 'Rent case input is invalid' USING ERRCODE='P5402'; END IF;
                    SELECT * INTO v_line FROM app.invoice_lines WHERE id=(p_intent->>'rent_invoice_line_id')::uuid;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Rent source not found' USING ERRCODE='P5401'; END IF;
                    SELECT * INTO v_invoice FROM app.invoices WHERE id=v_line.invoice_id FOR UPDATE;
                    IF v_invoice.lease_id IS DISTINCT FROM p_lease OR app.invoice_property_id(v_invoice.id) IS DISTINCT FROM p_property
                    THEN RAISE EXCEPTION 'Rent source not found' USING ERRCODE='P5401'; END IF;
                    IF v_line.category<>'RENT' OR v_line.source_lease_id IS DISTINCT FROM p_lease
                        OR v_invoice.status IN ('DRAFT','VOID') OR v_invoice.issued_at IS NULL
                    THEN RAISE EXCEPTION 'Rent source is not applicable' USING ERRCODE='P5403'; END IF;
                    IF EXISTS(SELECT 1 FROM app.rent_nonpayment_cases WHERE rent_invoice_line_id=v_line.id)
                    THEN RAISE EXCEPTION 'Rent case already exists' USING ERRCODE='P5403'; END IF;
                    v_now:=clock_timestamp();
                    INSERT INTO app.rent_nonpayment_cases VALUES(v_id,p_lease,v_invoice.customer_id,v_invoice.id,v_line.id,v_invoice.due_date,v_now,p_actor);
                    v_result:=app.rent_nonpayment_case_snapshot(v_id,v_now);
                    v_capability:='rent_nonpayment.case_manage'; v_entity:='rent_nonpayment_case';
                ELSE
                    IF p_intent-ARRAY['reason','event_kind','notice_document_reference','communication_record','authorization_reference']<>'{}'::jsonb
                        OR jsonb_typeof(p_intent->'event_kind') IS DISTINCT FROM 'string'
                        OR (p_intent->>'event_kind') NOT IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT','CURE','AUTHORIZED_FOLLOW_UP')
                    THEN RAISE EXCEPTION 'Rent event kind is invalid' USING ERRCODE='P5402'; END IF;
                    FOREACH v_kind IN ARRAY ARRAY['notice_document_reference','communication_record','authorization_reference'] LOOP
                        IF p_intent->v_kind IS NOT NULL AND p_intent->v_kind<>'null'::jsonb AND
                            (jsonb_typeof(p_intent->v_kind)<>'string' OR (p_intent->>v_kind)<>btrim(p_intent->>v_kind)
                                OR length(p_intent->>v_kind) NOT BETWEEN 1 AND CASE WHEN v_kind='communication_record' THEN 2000 ELSE 500 END)
                        THEN RAISE EXCEPTION 'Rent event evidence is invalid' USING ERRCODE='P5402'; END IF;
                    END LOOP;
                    v_kind:=p_intent->>'event_kind';
                    IF (v_kind='TWENTY_DAY_WARNING' AND p_intent->>'notice_document_reference' IS NULL)
                        OR (v_kind='AUTHORIZED_FOLLOW_UP' AND p_intent->>'authorization_reference' IS NULL)
                    THEN RAISE EXCEPTION 'Rent event evidence is required' USING ERRCODE='P5402'; END IF;
                    SELECT * INTO v_case FROM app.rent_nonpayment_cases WHERE id=p_case AND lease_id=p_lease;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Rent case not found' USING ERRCODE='P5401'; END IF;
                    SELECT * INTO v_invoice FROM app.invoices WHERE id=v_case.invoice_id FOR UPDATE;
                    PERFORM 1 FROM app.invoice_lines WHERE id=v_case.rent_invoice_line_id FOR SHARE;
                    IF v_invoice.status IN ('DRAFT','VOID') OR v_invoice.issued_at IS NULL
                    THEN RAISE EXCEPTION 'Rent source is no longer applicable' USING ERRCODE='P5403'; END IF;
                    v_now:=clock_timestamp(); v_date:=timezone('Asia/Phnom_Penh',v_now)::date;
                    v_balance:=app.invoice_line_outstanding(v_case.rent_invoice_line_id);
                    v_days:=v_date-v_case.due_date_snapshot;
                    IF (v_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT') AND
                        EXISTS(SELECT 1 FROM app.rent_nonpayment_events WHERE rent_nonpayment_case_id=p_case AND event_kind=v_kind))
                        OR NOT app.rent_nonpayment_milestone_eligible(v_kind,v_case.due_date_snapshot,v_now,v_balance,
                            EXISTS(SELECT 1 FROM app.rent_nonpayment_events WHERE rent_nonpayment_case_id=p_case
                                AND event_kind IN ('TWENTY_DAY_WARNING','THIRTY_DAY_SERIOUS_DEFAULT')))
                    THEN RAISE EXCEPTION 'Rent milestone is not eligible' USING ERRCODE='P5403'; END IF;
                    INSERT INTO app.rent_nonpayment_events VALUES(v_id,p_case,v_kind,v_date,v_balance,
                        p_intent->>'notice_document_reference',p_intent->>'communication_record',v_reason,v_now,p_actor,p_intent->>'authorization_reference')
                        RETURNING * INTO v_event;
                    v_result:=to_jsonb(v_event)||jsonb_build_object('lease_id',p_lease,'customer_id',v_case.customer_id,
                        'property_id',p_property,'invoice_id',v_case.invoice_id,'rent_invoice_line_id',v_case.rent_invoice_line_id,
                        'due_date_snapshot',v_case.due_date_snapshot);
                    v_capability:='rent_nonpayment.event_post'; v_entity:='rent_nonpayment_event';
                END IF;
                v_customer:=v_invoice.customer_id;
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,linked_source_event_id,customer_id,lease_id)
            VALUES(gen_random_uuid(),v_now,timezone('Asia/Phnom_Penh',v_now)::date,p_actor,v_capability,
                v_entity,v_id,v_reason,COALESCE(p_intent->>'authorization_reference',v_capability),p_property,NULL,
                v_result,p_key,'API','SUCCEEDED',jsonb_build_object('capability',v_capability),v_id,v_customer,p_lease);
            v_response:=jsonb_build_object('data',v_result,'meta',jsonb_build_object('request_id',p_request_id));
            INSERT INTO app.lease_enforcement_commands VALUES(p_property,p_actor,p_action,p_key,p_digest,p_intent,p_lease,p_case,v_response,v_now);
            RETURN jsonb_build_object('status_code',201,'body',v_response);
        END $$;
    """)
    for table in ("rent_nonpayment_cases", "rent_nonpayment_events", "lease_enforcement_commands"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();
            REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap;
        """)
    for signature in (
        "app.lease_enforcement_scope(uuid,uuid,uuid)",
        "app.rent_nonpayment_milestone_eligible(text,date,timestamptz,bigint,boolean)",
        "app.validate_rent_nonpayment_case()",
        "app.validate_rent_nonpayment_event()",
        "app.rent_nonpayment_case_snapshot(uuid,timestamptz)",
        "app.lease_enforcement_read(uuid,uuid,uuid,text,uuid,integer,integer)",
        "app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_enforcement_read(uuid,uuid,uuid,text,uuid,integer,integer) TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.lease_enforcement_command(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,text) TO prm_financial"
    )


def downgrade() -> None:
    raise RuntimeError("Lease warning and Rent nonpayment history is forward-only")
