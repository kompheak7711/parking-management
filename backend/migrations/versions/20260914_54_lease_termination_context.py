# ruff: noqa: E501
"""Bind fresh termination to explicit signed authority and real prerequisite sources."""

from alembic import op
from sqlalchemy import text

revision = "20260914_54"
down_revision = "20260914_53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE FUNCTION app.lease_termination_context_shape_valid(p_context jsonb)
        RETURNS boolean LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
        DECLARE v_field text; v_value jsonb; v_uuid uuid; v_date date; v_count integer;
        BEGIN
            IF p_context IS NULL OR jsonb_typeof(p_context) IS DISTINCT FROM 'object'
                OR NOT (p_context ?& ARRAY['basis','signed_lease_provision','approved_grounds',
                    'management_authorization_reference','evidence_reference','notice_required',
                    'notice_id','notice_period_ends_on','notice_exception_reason','warning_ids'])
                OR p_context-ARRAY['basis','signed_lease_provision','approved_grounds',
                    'management_authorization_reference','evidence_reference','notice_required',
                    'notice_id','notice_period_ends_on','notice_exception_reason','warning_ids']<>'{}'::jsonb
                OR jsonb_typeof(p_context->'basis') IS DISTINCT FROM 'string'
                OR p_context->>'basis' NOT IN ('VOLUNTARY_EARLY','CUSTOMER_VIOLATION','SIGNED_LEASE_OTHER')
                OR jsonb_typeof(p_context->'notice_required') IS DISTINCT FROM 'boolean'
                OR jsonb_typeof(p_context->'warning_ids') IS DISTINCT FROM 'array'
            THEN RETURN false; END IF;
            FOREACH v_field IN ARRAY ARRAY['signed_lease_provision','approved_grounds',
                'management_authorization_reference','evidence_reference'] LOOP
                IF jsonb_typeof(p_context->v_field) IS DISTINCT FROM 'string'
                    OR NOT app.lease_notice_text_valid(p_context->>v_field,
                        CASE WHEN v_field IN ('signed_lease_provision','approved_grounds') THEN 2000 ELSE 500 END)
                THEN RETURN false; END IF;
            END LOOP;
            IF (p_context->>'notice_required')::boolean THEN
                IF jsonb_typeof(p_context->'notice_id') IS DISTINCT FROM 'string'
                    OR (p_context->>'notice_id')!~'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    OR jsonb_typeof(p_context->'notice_period_ends_on') IS DISTINCT FROM 'string'
                    OR (p_context->>'notice_period_ends_on')!~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                    OR p_context->'notice_exception_reason'<>'null'::jsonb
                THEN RETURN false; END IF;
                v_uuid:=(p_context->>'notice_id')::uuid;
                v_date:=(p_context->>'notice_period_ends_on')::date;
                IF v_uuid='00000000-0000-0000-0000-000000000000' OR NOT isfinite(v_date)
                THEN RETURN false; END IF;
            ELSE
                IF p_context->'notice_id'<>'null'::jsonb OR p_context->'notice_period_ends_on'<>'null'::jsonb
                    OR jsonb_typeof(p_context->'notice_exception_reason') IS DISTINCT FROM 'string'
                    OR NOT app.lease_notice_text_valid(p_context->>'notice_exception_reason',2000)
                THEN RETURN false; END IF;
            END IF;
            v_count:=jsonb_array_length(p_context->'warning_ids');
            IF v_count>100 OR (p_context->>'basis'='CUSTOMER_VIOLATION' AND v_count<3)
                OR (p_context->>'basis'<>'CUSTOMER_VIOLATION' AND v_count<>0)
                OR (SELECT count(DISTINCT item) FROM jsonb_array_elements(p_context->'warning_ids') item)<>v_count
            THEN RETURN false; END IF;
            FOR v_value IN SELECT value FROM jsonb_array_elements(p_context->'warning_ids') LOOP
                IF jsonb_typeof(v_value) IS DISTINCT FROM 'string'
                    OR (v_value#>>'{}')!~'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                THEN RETURN false; END IF;
                v_uuid:=(v_value#>>'{}')::uuid;
                IF v_uuid='00000000-0000-0000-0000-000000000000' THEN RETURN false; END IF;
            END LOOP;
            RETURN true;
        EXCEPTION WHEN invalid_text_representation OR datetime_field_overflow OR invalid_datetime_format THEN
            RETURN false;
        END $$;

        CREATE TABLE app.lease_termination_contexts (
            command_event_id uuid PRIMARY KEY REFERENCES app.lease_commands(event_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK(idempotency_key<>'00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            expected_lease_version integer NOT NULL CHECK(expected_lease_version>0),
            actual_termination_date date NOT NULL CHECK(isfinite(actual_termination_date)),
            occurred_at timestamptz NOT NULL CHECK(isfinite(occurred_at)),
            governing_event_reference text NOT NULL CHECK(app.lease_notice_text_valid(governing_event_reference,500)),
            reason text NOT NULL CHECK(app.lease_notice_text_valid(reason,500)),
            context_data jsonb NOT NULL CHECK(app.lease_termination_context_shape_valid(context_data)),
            notice_id uuid REFERENCES app.lease_notice_contexts(notice_id) ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp() CHECK(isfinite(recorded_at)),
            UNIQUE(property_id,actor_id,idempotency_key),
            CHECK(command_event_id<>'00000000-0000-0000-0000-000000000000'),
            CHECK(occurred_at<=recorded_at),
            CHECK(notice_id IS NOT DISTINCT FROM (context_data->>'notice_id')::uuid)
        );
        CREATE INDEX lease_termination_contexts_lease_idx ON app.lease_termination_contexts(lease_id,recorded_at,command_event_id);
        CREATE TABLE app.lease_termination_warning_sources (
            command_event_id uuid NOT NULL REFERENCES app.lease_termination_contexts(command_event_id) ON DELETE RESTRICT,
            warning_id uuid NOT NULL REFERENCES app.lease_violation_warnings(id) ON DELETE RESTRICT,
            PRIMARY KEY(command_event_id,warning_id)
        );

        CREATE FUNCTION app.require_lease_termination_context(
            p_property uuid,p_key uuid,p_digest text,p_event uuid,p_lease uuid,p_version integer,
            p_actual date,p_occurred timestamptz,p_governing text,p_reason text,p_actor uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_context app.lease_termination_contexts%ROWTYPE; v_lease app.leases%ROWTYPE;
        DECLARE v_notice app.termination_notices%ROWTYPE; v_notice_context app.lease_notice_contexts%ROWTYPE;
        DECLARE v_notice_end date; v_count integer;
        BEGIN
            SELECT * INTO v_context FROM app.lease_termination_contexts WHERE command_event_id=p_event;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Approved termination context is required' USING ERRCODE='22023';
            END IF;
            IF v_context.property_id IS DISTINCT FROM p_property OR v_context.actor_id IS DISTINCT FROM p_actor
                OR v_context.idempotency_key IS DISTINCT FROM p_key OR v_context.request_digest IS DISTINCT FROM p_digest
                OR v_context.lease_id IS DISTINCT FROM p_lease OR v_context.expected_lease_version IS DISTINCT FROM p_version
                OR v_context.actual_termination_date IS DISTINCT FROM p_actual OR v_context.occurred_at IS DISTINCT FROM p_occurred
                OR v_context.governing_event_reference IS DISTINCT FROM p_governing OR v_context.reason IS DISTINCT FROM p_reason
            THEN RAISE EXCEPTION 'Termination context does not match the exact command' USING ERRCODE='22023'; END IF;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor FOR SHARE;
            PERFORM app.lease_enforcement_scope(p_property,p_lease,p_actor);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id=p_lease FOR UPDATE;
            IF NOT app.lease_termination_context_shape_valid(v_context.context_data)
                OR ((v_context.context_data->>'basis'='VOLUNTARY_EARLY') IS DISTINCT FROM (p_governing='BR-LEASE-021'))
                OR (v_context.context_data->>'basis'='VOLUNTARY_EARLY' AND p_actual>=v_lease.end_date)
            THEN RAISE EXCEPTION 'Termination context governing basis is invalid' USING ERRCODE='22023'; END IF;
            IF (v_context.context_data->>'notice_required')::boolean THEN
                SELECT * INTO v_notice FROM app.termination_notices WHERE id=v_context.notice_id FOR SHARE;
                SELECT * INTO v_notice_context FROM app.lease_notice_contexts WHERE notice_id=v_context.notice_id;
                v_notice_end:=(v_context.context_data->>'notice_period_ends_on')::date;
                IF v_notice.id IS NULL OR v_notice_context.notice_id IS NULL OR v_notice.lease_id<>p_lease
                    OR v_notice.occurred_at>p_occurred OR v_notice.notice_date>p_actual
                    OR v_notice_end<v_notice.notice_date OR p_actual<v_notice_end
                    OR v_notice.governing_lease_provision IS DISTINCT FROM v_context.context_data->>'signed_lease_provision'
                    OR v_notice_context.approved_grounds IS DISTINCT FROM v_context.context_data->>'approved_grounds'
                    OR EXISTS(SELECT 1 FROM app.lease_notice_contexts WHERE supersedes_notice_id=v_notice.id)
                THEN RAISE EXCEPTION 'Applicable termination notice or period is invalid' USING ERRCODE='22023'; END IF;
            END IF;
            SELECT count(*) INTO v_count FROM app.lease_termination_warning_sources WHERE command_event_id=p_event;
            IF v_count<>jsonb_array_length(v_context.context_data->'warning_ids')
                OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(v_context.context_data->'warning_ids') item
                    WHERE NOT EXISTS(SELECT 1 FROM app.lease_termination_warning_sources source
                        WHERE source.command_event_id=p_event AND source.warning_id=item::uuid))
                OR EXISTS(SELECT 1 FROM app.lease_termination_warning_sources source
                    JOIN app.lease_violation_warnings warning ON warning.id=source.warning_id
                    WHERE source.command_event_id=p_event AND (warning.lease_id<>p_lease
                        OR NOT isfinite(warning.warning_date) OR NOT isfinite(warning.violation_date)
                        OR NOT isfinite(warning.occurred_at) OR warning.occurred_at>p_occurred
                        OR warning.warning_date>p_actual OR warning.violation_date>warning.warning_date
                        OR NOT app.lease_notice_text_valid(warning.lease_provision,2000)
                        OR NOT app.lease_notice_text_valid(warning.violation_description,2000)
                        OR NOT app.lease_notice_text_valid(warning.communication_record,2000)))
            THEN RAISE EXCEPTION 'Termination general warning sources are invalid' USING ERRCODE='22023'; END IF;
        END $$;

        CREATE FUNCTION app.terminate_lease_with_context(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_event_id uuid,p_lease_id uuid,p_expected_version integer,
            p_actual_termination_date date,p_occurred_at timestamptz,
            p_governing_event_reference text,p_reason text,p_actor_id uuid,p_context jsonb)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_replay jsonb; v_saved app.lease_termination_contexts%ROWTYPE;
        BEGIN
            PERFORM 1 FROM app.properties WHERE id=p_property_id FOR SHARE;
            PERFORM 1 FROM app.user_accounts WHERE actor_id=p_actor_id FOR SHARE;
            PERFORM app.lease_enforcement_scope(p_property_id,p_lease_id,p_actor_id);
            IF p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_event_id IS NULL OR p_event_id='00000000-0000-0000-0000-000000000000'
                OR p_expected_version IS NULL OR p_expected_version<1
                OR p_actual_termination_date IS NULL OR NOT isfinite(p_actual_termination_date)
                OR p_occurred_at IS NULL OR NOT isfinite(p_occurred_at)
                OR NOT app.lease_notice_text_valid(p_governing_event_reference,500)
                OR NOT app.lease_notice_text_valid(p_reason,500)
                OR NOT app.lease_termination_context_shape_valid(p_context)
            THEN RAISE EXCEPTION 'Termination context is invalid' USING ERRCODE='22023'; END IF;
            v_replay:=app.replay_lease_command(p_property_id,p_actor_id,'lease.terminate',p_idempotency_key,p_request_digest);
            IF v_replay IS NOT NULL THEN
                SELECT * INTO v_saved FROM app.lease_termination_contexts
                    WHERE property_id=p_property_id AND actor_id=p_actor_id AND idempotency_key=p_idempotency_key;
                IF NOT FOUND OR v_saved.context_data IS DISTINCT FROM p_context
                    OR v_saved.command_event_id IS DISTINCT FROM p_event_id OR v_saved.lease_id IS DISTINCT FROM p_lease_id
                    OR v_saved.request_digest IS DISTINCT FROM p_request_digest
                    OR v_saved.expected_lease_version IS DISTINCT FROM p_expected_version
                    OR v_saved.actual_termination_date IS DISTINCT FROM p_actual_termination_date
                    OR v_saved.occurred_at IS DISTINCT FROM p_occurred_at
                    OR v_saved.governing_event_reference IS DISTINCT FROM p_governing_event_reference
                    OR v_saved.reason IS DISTINCT FROM p_reason
                THEN RAISE EXCEPTION 'Termination context command key was reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay;
            END IF;
            -- Match the original command's Lease/Unit order before child FKs
            -- take key-share locks. Concurrent commands serialize here.
            PERFORM 1 FROM app.leases lease JOIN app.units unit ON unit.id=lease.unit_id
                WHERE lease.id=p_lease_id AND unit.property_id=p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE='P0002'; END IF;
            PERFORM 1 FROM app.units unit JOIN app.leases lease ON lease.unit_id=unit.id
                WHERE lease.id=p_lease_id FOR UPDATE OF unit;
            -- This new FK alone spans context creation and the existing command.
            -- Validate it before returning, even if the caller requested IMMEDIATE.
            SET CONSTRAINTS app.lease_termination_contexts_command_event_id_fkey DEFERRED;
            INSERT INTO app.lease_termination_contexts(command_event_id,property_id,actor_id,idempotency_key,
                request_digest,lease_id,expected_lease_version,actual_termination_date,occurred_at,
                governing_event_reference,reason,context_data,notice_id)
            VALUES(p_event_id,p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_lease_id,
                p_expected_version,p_actual_termination_date,p_occurred_at,p_governing_event_reference,p_reason,
                p_context,(p_context->>'notice_id')::uuid);
            INSERT INTO app.lease_termination_warning_sources(command_event_id,warning_id)
                SELECT p_event_id,item::uuid FROM jsonb_array_elements_text(p_context->'warning_ids') item;
            v_replay:=app.terminate_lease(p_property_id,p_idempotency_key,p_request_digest,p_event_id,p_lease_id,
                p_expected_version,p_actual_termination_date,p_occurred_at,p_governing_event_reference,p_reason,p_actor_id);
            SET CONSTRAINTS app.lease_termination_contexts_command_event_id_fkey IMMEDIATE;
            RETURN v_replay;
        EXCEPTION WHEN foreign_key_violation THEN
            RAISE EXCEPTION 'Termination context source was not found' USING ERRCODE='22023';
        END $$;
    """)

    signature = (
        "app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)"
    )
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    before = "            v_before := app.lease_snapshot(p_lease_id);"
    after = """            PERFORM app.require_lease_termination_context(
                p_property_id,p_idempotency_key,p_request_digest,p_event_id,p_lease_id,
                p_expected_version,p_actual_termination_date,p_occurred_at,
                p_governing_event_reference,p_reason,p_actor_id);
            v_before := app.lease_snapshot(p_lease_id);"""
    if definition.count(before) != 1:
        raise RuntimeError("Termination prerequisite integration source contract changed")
    op.execute(definition.replace(before, after))

    for table in ("lease_termination_contexts", "lease_termination_warning_sources"):
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
        op.execute(f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC,prm_runtime,prm_bootstrap")
    for function in (
        "app.lease_termination_context_shape_valid(jsonb)",
        "app.require_lease_termination_context(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)",
        "app.terminate_lease_with_context(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid,jsonb)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,prm_runtime,prm_bootstrap")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.terminate_lease_with_context(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid,jsonb) TO prm_runtime"
    )


def downgrade() -> None:
    raise RuntimeError("Lease termination context is forward-only")
