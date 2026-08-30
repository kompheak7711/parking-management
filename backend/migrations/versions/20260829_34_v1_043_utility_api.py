# ruff: noqa: E501
"""Add the least-privilege V1-043 Utility resource command boundary."""

from alembic import op

revision = "20260829_34"
down_revision = "20260829_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Expose append-only, idempotent Meter and Reading commands."""
    op.execute(
        r"""
        ALTER TABLE app.utility_readings
            ADD COLUMN source_kind text NOT NULL DEFAULT 'MIGRATED'
                CHECK (source_kind IN ('MIGRATED','MANUAL','METER_INSTALLATION','METER_REPLACEMENT')),
            ADD COLUMN source_evidence text NOT NULL DEFAULT 'Published historical Utility Reading'
                CHECK (length(btrim(source_evidence))>0 AND source_evidence=btrim(source_evidence));
        CREATE TABLE app.utility_api_commands (
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (
                idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            action text NOT NULL CHECK (action IN (
                'INSTALL_METER','REPLACE_METER','RECORD_READING','RECORD_READING_BATCH',
                'CORRECT_READING'
            )),
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{64}$'),
            resource_id uuid NOT NULL CHECK (
                resource_id<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            completed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY(actor_id,idempotency_key),
            UNIQUE(actor_id,idempotency_key,resource_id)
        );
        CREATE INDEX utility_api_commands_completed_idx
            ON app.utility_api_commands(completed_at,idempotency_key);
        CREATE TRIGGER utility_api_commands_append_only
            BEFORE UPDATE OR DELETE ON app.utility_api_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_api_commands_reject_truncate
            BEFORE TRUNCATE ON app.utility_api_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TABLE app.utility_api_batch_items (
            actor_id uuid NOT NULL,
            batch_idempotency_key uuid NOT NULL,
            batch_id uuid NOT NULL,
            item_index integer NOT NULL CHECK (item_index>=0 AND item_index<100),
            item_idempotency_key uuid NOT NULL CHECK (
                item_idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            reading_id uuid REFERENCES app.utility_readings(id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
            error_code text CHECK (error_code IN (
                'NOT_FOUND','CONFLICT','VALIDATION_ERROR','ATOMIC_ROLLBACK'
            )),
            PRIMARY KEY(actor_id,batch_idempotency_key,item_index),
            UNIQUE(batch_id,item_index),
            UNIQUE(batch_id,item_idempotency_key),
            FOREIGN KEY(actor_id,batch_idempotency_key,batch_id)
                REFERENCES app.utility_api_commands(actor_id,idempotency_key,resource_id)
                ON DELETE RESTRICT,
            CONSTRAINT utility_api_batch_items_result_shape CHECK (
                (status='SUCCEEDED' AND reading_id IS NOT NULL AND error_code IS NULL)
                OR (status='FAILED' AND reading_id IS NULL AND error_code IS NOT NULL)
            )
        );
        CREATE TRIGGER utility_api_batch_items_append_only
            BEFORE UPDATE OR DELETE ON app.utility_api_batch_items
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_api_batch_items_reject_truncate
            BEFORE TRUNCATE ON app.utility_api_batch_items
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_utility_history_mutation();

        CREATE FUNCTION app.install_utility_meter_api(
            p_unit_id uuid,p_meter_id uuid,p_reading_id uuid,p_utility_type text,
            p_serial_number text,p_measurement_unit_code text,p_description text,
            p_installed_date date,p_memo text,p_reading_date date,
            p_reading_value numeric,p_source_evidence text,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid; v_replay app.utility_api_commands%ROWTYPE;
        BEGIN
            IF p_unit_id IS NULL OR p_meter_id IS NULL OR p_reading_id IS NULL
                OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_utility_type NOT IN ('ELECTRICITY','WATER')
                OR p_serial_number IS NULL OR length(btrim(p_serial_number))=0
                OR p_serial_number<>btrim(p_serial_number)
                OR p_measurement_unit_code IS NULL
                OR length(btrim(p_measurement_unit_code))=0
                OR p_measurement_unit_code<>btrim(p_measurement_unit_code)
                OR p_installed_date IS NULL OR p_reading_date<>p_installed_date
                OR p_reading_value IS NULL OR p_reading_value<0
                OR NOT (p_reading_value<'Infinity'::numeric)
                OR p_source_evidence IS NULL OR length(btrim(p_source_evidence))=0
                OR p_source_evidence<>btrim(p_source_evidence)
            THEN RAISE EXCEPTION 'Meter installation evidence is invalid' USING ERRCODE='22023';
            END IF;
            SELECT property_id INTO v_property_id FROM app.units WHERE id=p_unit_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Unit was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,v_property_id);
            PERFORM app.lock_utility_unit_type(p_unit_id,p_utility_type);
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'INSTALL_METER' OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay.resource_id;
            END IF;
            INSERT INTO app.utility_meters(
                id,unit_id,serial_number,utility_type,measurement_unit_code,description,
                installed_date,memo,created_by,updated_by
            ) VALUES (p_meter_id,p_unit_id,p_serial_number,p_utility_type,
                p_measurement_unit_code,p_description,p_installed_date,p_memo,p_actor_id,p_actor_id);
            INSERT INTO app.utility_readings(
                id,meter_id,reading_date,reading_value,validated_at,validated_by,
                created_by,updated_by,source_kind,source_evidence
            ) VALUES (p_reading_id,p_meter_id,p_reading_date,p_reading_value,
                statement_timestamp(),p_actor_id,p_actor_id,p_actor_id,
                'METER_INSTALLATION',p_source_evidence);
            INSERT INTO app.utility_api_commands(actor_id,idempotency_key,action,request_digest,resource_id)
            VALUES(p_actor_id,p_idempotency_key,'INSTALL_METER',p_request_digest,p_meter_id);
            RETURN p_meter_id;
        END $$;

        CREATE FUNCTION app.record_utility_reading_api(
            p_meter_id uuid,p_reading_id uuid,p_expected_meter_version integer,
            p_reading_date date,p_reading_value numeric,p_source_kind text,
            p_source_evidence text,p_actor_id uuid,p_idempotency_key uuid,
            p_request_digest text
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid; v_version integer; v_replay app.utility_api_commands%ROWTYPE;
        BEGIN
            IF p_meter_id IS NULL OR p_reading_id IS NULL OR p_actor_id IS NULL
                OR p_idempotency_key IS NULL OR p_expected_meter_version<1
                OR p_reading_date IS NULL OR p_reading_value IS NULL OR p_reading_value<0
                OR NOT (p_reading_value<'Infinity'::numeric) OR p_source_kind<>'MANUAL'
                OR p_source_evidence IS NULL OR length(btrim(p_source_evidence))=0
                OR p_source_evidence<>btrim(p_source_evidence)
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Utility Reading evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT unit.property_id INTO v_property_id FROM app.utility_meters meter
              JOIN app.units unit ON unit.id=meter.unit_id WHERE meter.id=p_meter_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Meter was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,v_property_id);
            PERFORM app.lock_utility_meter_sequence(p_meter_id);
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'RECORD_READING' OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay.resource_id;
            END IF;
            SELECT version INTO v_version FROM app.utility_meters WHERE id=p_meter_id FOR UPDATE;
            IF v_version<>p_expected_meter_version THEN
                RAISE EXCEPTION 'Utility Meter version changed' USING ERRCODE='PRV01',DETAIL=v_version::text;
            END IF;
            UPDATE app.utility_meters SET version=version+1,updated_at=statement_timestamp(),updated_by=p_actor_id
             WHERE id=p_meter_id;
            INSERT INTO app.utility_readings(
                id,meter_id,reading_date,reading_value,validated_at,validated_by,
                created_by,updated_by,source_kind,source_evidence
            ) VALUES(p_reading_id,p_meter_id,p_reading_date,p_reading_value,
                statement_timestamp(),p_actor_id,p_actor_id,p_actor_id,p_source_kind,p_source_evidence);
            INSERT INTO app.utility_api_commands(actor_id,idempotency_key,action,request_digest,resource_id)
            VALUES(p_actor_id,p_idempotency_key,'RECORD_READING',p_request_digest,p_reading_id);
            RETURN p_reading_id;
        END $$;

        CREATE FUNCTION app.record_utility_reading_batch_api(
            p_property_id uuid,p_batch_id uuid,p_items jsonb,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_replay app.utility_api_commands%ROWTYPE;
            v_item jsonb;
            v_ordinality integer;
            v_index integer;
            v_item_idempotency_key uuid;
            v_item_idempotency_keys uuid[]:=ARRAY[]::uuid[];
            v_meter_id uuid;
            v_meter_property_id uuid;
            v_reading_id uuid;
            v_expected_version integer;
            v_current_version integer;
            v_reading_date date;
            v_reading_value numeric;
            v_source_kind text;
            v_source_evidence text;
            v_failed_index integer;
            v_error_code text;
            v_results jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_batch_id IS NULL
                OR p_batch_id='00000000-0000-0000-0000-000000000000'::uuid
                OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_idempotency_key='00000000-0000-0000-0000-000000000000'::uuid
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_items IS NULL OR jsonb_typeof(p_items)<>'array'
            THEN RAISE EXCEPTION 'Atomic Reading batch evidence is invalid' USING ERRCODE='22023';
            END IF;
            IF jsonb_array_length(p_items)<1 OR jsonb_array_length(p_items)>100 THEN
                RAISE EXCEPTION 'Atomic Reading batch size is invalid' USING ERRCODE='22023';
            END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-api-command:' || p_actor_id::text || ':' || p_idempotency_key::text,0
            ));
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'RECORD_READING_BATCH'
                    OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                SELECT jsonb_agg(jsonb_build_object(
                    'index',item_index,'idempotency_key',item_idempotency_key,
                    'status',status,'reading_id',reading_id,'error_code',error_code
                ) ORDER BY item_index) INTO v_results
                FROM app.utility_api_batch_items
                WHERE actor_id=p_actor_id AND batch_idempotency_key=p_idempotency_key
                  AND batch_id=v_replay.resource_id;
                IF v_results IS NULL THEN
                    RAISE EXCEPTION 'Atomic Reading batch result is unavailable' USING ERRCODE='55000';
                END IF;
                RETURN v_results;
            END IF;

            FOR v_item,v_ordinality IN
                SELECT value,ordinality::integer
                FROM jsonb_array_elements(p_items) WITH ORDINALITY
            LOOP
                BEGIN
                    v_index:=(v_item->>'index')::integer;
                    v_item_idempotency_key:=(v_item->>'idempotency_key')::uuid;
                    v_meter_id:=(v_item->>'meter_id')::uuid;
                    v_reading_id:=(v_item->>'reading_id')::uuid;
                    v_expected_version:=(v_item->>'expected_meter_version')::integer;
                    v_reading_date:=(v_item->>'reading_date')::date;
                    v_reading_value:=(v_item->>'reading_value')::numeric;
                    v_source_kind:=v_item->>'source_kind';
                    v_source_evidence:=v_item->>'source_evidence';
                EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                    RAISE EXCEPTION 'Atomic Reading batch item is invalid' USING ERRCODE='22023';
                END;
                IF jsonb_typeof(v_item)<>'object' OR v_index<>v_ordinality-1
                    OR v_item_idempotency_key IS NULL
                    OR v_item_idempotency_key='00000000-0000-0000-0000-000000000000'::uuid
                    OR v_item_idempotency_key=ANY(v_item_idempotency_keys)
                    OR v_meter_id IS NULL
                    OR v_meter_id='00000000-0000-0000-0000-000000000000'::uuid
                    OR v_reading_id IS NULL
                    OR v_reading_id='00000000-0000-0000-0000-000000000000'::uuid
                    OR v_expected_version IS NULL OR v_expected_version<1
                    OR v_reading_date IS NULL OR v_reading_value IS NULL OR v_reading_value<0
                    OR NOT (v_reading_value<'Infinity'::numeric) OR v_source_kind<>'MANUAL'
                    OR v_source_evidence IS NULL OR length(btrim(v_source_evidence))=0
                    OR v_source_evidence<>btrim(v_source_evidence)
                THEN RAISE EXCEPTION 'Atomic Reading batch item is invalid' USING ERRCODE='22023';
                END IF;
                v_item_idempotency_keys:=array_append(
                    v_item_idempotency_keys,v_item_idempotency_key
                );
            END LOOP;

            v_error_code:=NULL;
            BEGIN
                FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
                LOOP
                    v_failed_index:=(v_item->>'index')::integer;
                    v_meter_id:=(v_item->>'meter_id')::uuid;
                    v_reading_id:=(v_item->>'reading_id')::uuid;
                    v_expected_version:=(v_item->>'expected_meter_version')::integer;
                    v_reading_date:=(v_item->>'reading_date')::date;
                    v_reading_value:=(v_item->>'reading_value')::numeric;
                    v_source_kind:=v_item->>'source_kind';
                    v_source_evidence:=v_item->>'source_evidence';
                    SELECT unit.property_id INTO v_meter_property_id
                    FROM app.utility_meters meter
                    JOIN app.units unit ON unit.id=meter.unit_id
                    WHERE meter.id=v_meter_id;
                    IF NOT FOUND OR v_meter_property_id<>p_property_id THEN
                        RAISE EXCEPTION 'Meter was not found' USING ERRCODE='P0002';
                    END IF;
                    PERFORM app.lock_utility_meter_sequence(v_meter_id);
                    SELECT version INTO v_current_version FROM app.utility_meters
                    WHERE id=v_meter_id FOR UPDATE;
                    IF v_current_version<>v_expected_version THEN
                        RAISE EXCEPTION 'Utility Meter version changed'
                            USING ERRCODE='PRV01',DETAIL=v_current_version::text;
                    END IF;
                    UPDATE app.utility_meters
                    SET version=version+1,updated_at=statement_timestamp(),updated_by=p_actor_id
                    WHERE id=v_meter_id;
                    INSERT INTO app.utility_readings(
                        id,meter_id,reading_date,reading_value,validated_at,validated_by,
                        created_by,updated_by,source_kind,source_evidence
                    ) VALUES(v_reading_id,v_meter_id,v_reading_date,v_reading_value,
                        statement_timestamp(),p_actor_id,p_actor_id,p_actor_id,
                        v_source_kind,v_source_evidence);
                END LOOP;
            EXCEPTION
                WHEN SQLSTATE 'P0002' THEN v_error_code:='NOT_FOUND';
                WHEN SQLSTATE 'PRV01' OR unique_violation OR exclusion_violation
                    OR SQLSTATE '55000'
                    THEN v_error_code:='CONFLICT';
                WHEN numeric_value_out_of_range OR invalid_parameter_value
                    OR check_violation OR not_null_violation OR invalid_text_representation
                    THEN v_error_code:='VALIDATION_ERROR';
            END;

            INSERT INTO app.utility_api_commands(
                actor_id,idempotency_key,action,request_digest,resource_id
            ) VALUES(
                p_actor_id,p_idempotency_key,'RECORD_READING_BATCH',p_request_digest,p_batch_id
            );
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_items)
            LOOP
                v_index:=(v_item->>'index')::integer;
                v_item_idempotency_key:=(v_item->>'idempotency_key')::uuid;
                v_reading_id:=(v_item->>'reading_id')::uuid;
                INSERT INTO app.utility_api_batch_items(
                    actor_id,batch_idempotency_key,batch_id,item_index,
                    item_idempotency_key,reading_id,status,error_code
                ) VALUES(
                    p_actor_id,p_idempotency_key,p_batch_id,v_index,v_item_idempotency_key,
                    CASE WHEN v_error_code IS NULL THEN v_reading_id ELSE NULL END,
                    CASE WHEN v_error_code IS NULL THEN 'SUCCEEDED' ELSE 'FAILED' END,
                    CASE WHEN v_error_code IS NULL THEN NULL
                         WHEN v_index=v_failed_index THEN v_error_code
                         ELSE 'ATOMIC_ROLLBACK' END
                );
            END LOOP;
            SELECT jsonb_agg(jsonb_build_object(
                'index',item_index,'idempotency_key',item_idempotency_key,
                'status',status,'reading_id',reading_id,'error_code',error_code
            ) ORDER BY item_index) INTO v_results
            FROM app.utility_api_batch_items
            WHERE actor_id=p_actor_id AND batch_idempotency_key=p_idempotency_key
              AND batch_id=p_batch_id;
            RETURN v_results;
        END $$;

        CREATE FUNCTION app.replace_utility_meter_api(
            p_failed_meter_id uuid,p_replacement_meter_id uuid,p_reading_id uuid,
            p_event_id uuid,p_expected_version integer,p_boundary_reading_id uuid,
            p_failure_date date,p_replacement_date date,p_reason text,
            p_serial_number text,p_description text,p_memo text,p_reading_date date,
            p_reading_value numeric,p_source_evidence text,p_actor_id uuid,
            p_idempotency_key uuid,p_request_digest text
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_failed app.utility_meters%ROWTYPE; v_property_id uuid;
                v_unit_id uuid; v_utility_type text;
                v_boundary app.utility_readings%ROWTYPE; v_replay app.utility_api_commands%ROWTYPE;
        BEGIN
            IF p_failed_meter_id IS NULL OR p_replacement_meter_id IS NULL
                OR p_failed_meter_id=p_replacement_meter_id OR p_reading_id IS NULL
                OR p_event_id IS NULL OR p_boundary_reading_id IS NULL OR p_actor_id IS NULL
                OR p_idempotency_key IS NULL OR p_expected_version<1
                OR p_failure_date IS NULL OR p_replacement_date<=p_failure_date
                OR p_reading_date<>p_replacement_date OR p_reason IS NULL
                OR length(btrim(p_reason))=0 OR p_reason<>btrim(p_reason)
                OR p_serial_number IS NULL OR length(btrim(p_serial_number))=0
                OR p_serial_number<>btrim(p_serial_number)
                OR p_reading_value IS NULL OR p_reading_value<0
                OR NOT (p_reading_value<'Infinity'::numeric)
                OR p_source_evidence IS NULL OR length(btrim(p_source_evidence))=0
                OR p_source_evidence<>btrim(p_source_evidence)
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Meter replacement evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT meter.unit_id,meter.utility_type,unit.property_id
            INTO v_unit_id,v_utility_type,v_property_id
            FROM app.utility_meters meter JOIN app.units unit ON unit.id=meter.unit_id
            WHERE meter.id=p_failed_meter_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Meter was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,v_property_id);
            PERFORM app.lock_utility_unit_type(v_unit_id,v_utility_type);
            PERFORM app.lock_utility_meter_sequence(p_failed_meter_id);
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'REPLACE_METER' OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay.resource_id;
            END IF;
            SELECT * INTO v_failed FROM app.utility_meters WHERE id=p_failed_meter_id FOR UPDATE;
            IF v_failed.version<>p_expected_version THEN
                RAISE EXCEPTION 'Utility Meter version changed' USING ERRCODE='PRV01',DETAIL=v_failed.version::text;
            END IF;
            IF v_failed.deactivated_date IS NOT NULL THEN
                RAISE EXCEPTION 'Utility Meter is already replaced' USING ERRCODE='55000';
            END IF;
            SELECT * INTO v_boundary FROM app.utility_readings WHERE id=p_boundary_reading_id;
            IF NOT FOUND OR v_boundary.meter_id<>p_failed_meter_id
                OR v_boundary.validated_at IS NULL OR v_boundary.reading_date>p_failure_date
            THEN RAISE EXCEPTION 'Failed Meter boundary Reading is invalid' USING ERRCODE='23514'; END IF;
            UPDATE app.utility_meters SET failure_date=p_failure_date,deactivated_date=p_replacement_date,
                version=version+1,updated_at=statement_timestamp(),updated_by=p_actor_id
             WHERE id=p_failed_meter_id;
            INSERT INTO app.utility_meters(
                id,unit_id,serial_number,utility_type,measurement_unit_code,description,
                installed_date,memo,created_by,updated_by
            ) VALUES(p_replacement_meter_id,v_failed.unit_id,p_serial_number,v_failed.utility_type,
                v_failed.measurement_unit_code,p_description,p_replacement_date,p_memo,p_actor_id,p_actor_id);
            INSERT INTO app.utility_readings(
                id,meter_id,reading_date,reading_value,validated_at,validated_by,
                created_by,updated_by,source_kind,source_evidence
            ) VALUES(p_reading_id,p_replacement_meter_id,p_reading_date,p_reading_value,
                statement_timestamp(),p_actor_id,p_actor_id,p_actor_id,'METER_REPLACEMENT',p_source_evidence);
            INSERT INTO app.utility_meter_replacements(
                id,failed_meter_id,replacement_meter_id,replacement_date,reason,actor_id
            ) VALUES(p_event_id,p_failed_meter_id,p_replacement_meter_id,p_replacement_date,p_reason,p_actor_id);
            INSERT INTO app.utility_api_commands(actor_id,idempotency_key,action,request_digest,resource_id)
            VALUES(p_actor_id,p_idempotency_key,'REPLACE_METER',p_request_digest,p_replacement_meter_id);
            RETURN p_replacement_meter_id;
        END $$;

        CREATE FUNCTION app.correct_utility_reading_api(
            p_reading_id uuid,p_correction_id uuid,p_expected_version integer,
            p_corrected_value numeric,p_reason text,p_authorization_reference text,
            p_actor_id uuid,p_idempotency_key uuid,p_request_digest text
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid; v_meter_id uuid; v_version integer;
                v_previous numeric(20,6); v_replay app.utility_api_commands%ROWTYPE;
        BEGIN
            IF p_reading_id IS NULL OR p_correction_id IS NULL OR p_expected_version<1
                OR p_corrected_value IS NULL OR p_corrected_value<0
                OR NOT (p_corrected_value<'Infinity'::numeric)
                OR p_reason IS NULL OR length(btrim(p_reason))=0 OR p_reason<>btrim(p_reason)
                OR p_authorization_reference IS NULL OR length(btrim(p_authorization_reference))=0
                OR p_authorization_reference<>btrim(p_authorization_reference)
                OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN RAISE EXCEPTION 'Reading correction evidence is invalid' USING ERRCODE='22023'; END IF;
            SELECT meter.id,unit.property_id INTO v_meter_id,v_property_id
            FROM app.utility_readings reading JOIN app.utility_meters meter ON meter.id=reading.meter_id
            JOIN app.units unit ON unit.id=meter.unit_id WHERE reading.id=p_reading_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Reading was not found' USING ERRCODE='P0002'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,v_property_id);
            PERFORM app.lock_utility_meter_sequence(v_meter_id);
            SELECT * INTO v_replay FROM app.utility_api_commands
             WHERE actor_id=p_actor_id AND idempotency_key=p_idempotency_key FOR UPDATE;
            IF FOUND THEN
                IF v_replay.action<>'CORRECT_READING' OR v_replay.request_digest<>p_request_digest
                THEN RAISE EXCEPTION 'Utility API idempotency key reused' USING ERRCODE='23505'; END IF;
                RETURN v_replay.resource_id;
            END IF;
            SELECT reading.version+count(correction.id),app.utility_reading_effective_value(reading.id)
            INTO v_version,v_previous FROM app.utility_readings reading
            LEFT JOIN app.utility_reading_corrections correction ON correction.reading_id=reading.id
            WHERE reading.id=p_reading_id GROUP BY reading.id;
            IF v_version<>p_expected_version THEN
                RAISE EXCEPTION 'Utility Reading version changed' USING ERRCODE='PRV01',DETAIL=v_version::text;
            END IF;
            INSERT INTO app.utility_reading_corrections(
                id,reading_id,previous_value,corrected_value,reason,occurred_at,actor_id,authorization_reference
            ) VALUES(p_correction_id,p_reading_id,v_previous,p_corrected_value,p_reason,
                statement_timestamp(),p_actor_id,p_authorization_reference);
            INSERT INTO app.utility_api_commands(actor_id,idempotency_key,action,request_digest,resource_id)
            VALUES(p_actor_id,p_idempotency_key,'CORRECT_READING',p_request_digest,p_correction_id);
            RETURN p_correction_id;
        END $$;
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.utility_api_commands FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.utility_api_batch_items FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.utility_api_commands TO prm_financial")
    op.execute("GRANT SELECT ON TABLE app.utility_api_batch_items TO prm_financial")
    signatures = (
        "app.install_utility_meter_api(uuid,uuid,uuid,text,text,text,text,date,text,date,numeric,text,uuid,uuid,text)",
        "app.record_utility_reading_api(uuid,uuid,integer,date,numeric,text,text,uuid,uuid,text)",
        "app.record_utility_reading_batch_api(uuid,uuid,jsonb,uuid,uuid,text)",
        "app.replace_utility_meter_api(uuid,uuid,uuid,uuid,integer,uuid,date,date,text,text,text,text,date,numeric,text,uuid,uuid,text)",
        "app.correct_utility_reading_api(uuid,uuid,integer,numeric,text,text,uuid,uuid,text)",
    )
    for signature in signatures:
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,prm_runtime,prm_financial,prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback that could orphan published Utility command evidence."""
    raise RuntimeError("V1-043 Utility API migration is forward-only")
