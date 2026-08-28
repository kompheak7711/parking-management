# ruff: noqa: E501
"""Add protected Utility Meter, Reading, replacement, and correction persistence."""

from alembic import op

revision = "20260828_31"
down_revision = "20260828_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-041 Utility persistence boundary."""
    op.execute(
        r"""
        CREATE TABLE app.utility_meters (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            serial_number text NOT NULL CHECK (
                length(btrim(serial_number)) > 0 AND serial_number = btrim(serial_number)
            ),
            utility_type text NOT NULL CHECK (utility_type IN ('ELECTRICITY','WATER')),
            measurement_unit_code text NOT NULL CHECK (
                length(btrim(measurement_unit_code)) > 0
                AND measurement_unit_code = btrim(measurement_unit_code)
            ),
            description text CHECK (
                description IS NULL
                OR (length(btrim(description)) > 0 AND description = btrim(description))
            ),
            installed_date date NOT NULL,
            failure_date date,
            deactivated_date date,
            memo text CHECK (
                memo IS NULL OR (length(btrim(memo)) > 0 AND memo = btrim(memo))
            ),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT utility_meters_date_shape CHECK (
                (failure_date IS NULL OR failure_date >= installed_date)
                AND (deactivated_date IS NULL OR deactivated_date >= installed_date)
                AND (failure_date IS NULL OR deactivated_date IS NULL
                    OR failure_date <= deactivated_date)
                AND (deactivated_date IS NULL OR failure_date IS NOT NULL)
            ),
            CONSTRAINT utility_meters_provenance CHECK (updated_at >= created_at),
            CONSTRAINT utility_meters_unit_identity UNIQUE (id,unit_id,utility_type)
        );
        CREATE UNIQUE INDEX utility_meters_one_active_type_idx
            ON app.utility_meters(unit_id,utility_type)
            WHERE deactivated_date IS NULL;
        CREATE INDEX utility_meters_unit_history_idx
            ON app.utility_meters(unit_id,utility_type,installed_date DESC,id);

        CREATE TABLE app.utility_meter_replacements (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            failed_meter_id uuid NOT NULL UNIQUE
                REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            replacement_meter_id uuid NOT NULL UNIQUE
                REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            replacement_date date NOT NULL,
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT utility_meter_replacements_distinct
                CHECK (failed_meter_id <> replacement_meter_id),
            CONSTRAINT utility_meter_replacements_chronology CHECK (
                timezone('Asia/Phnom_Penh',occurred_at)::date >= replacement_date
            )
        );

        CREATE TABLE app.utility_readings (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            meter_id uuid NOT NULL REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            reading_date date NOT NULL,
            reading_value numeric(20,6) NOT NULL CHECK (reading_value >= 0),
            validated_at timestamptz,
            validated_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT utility_readings_validation_shape CHECK (
                (validated_at IS NULL AND validated_by IS NULL)
                OR (validated_at IS NOT NULL AND validated_by IS NOT NULL
                    AND validated_at >= created_at AND updated_at >= validated_at)
            ),
            CONSTRAINT utility_readings_provenance CHECK (updated_at >= created_at),
            CONSTRAINT utility_readings_meter_date_unique UNIQUE(meter_id,reading_date),
            CONSTRAINT utility_readings_meter_identity_unique UNIQUE(id,meter_id)
        );
        CREATE INDEX utility_readings_meter_history_idx
            ON app.utility_readings(meter_id,reading_date DESC,id);
        CREATE INDEX utility_readings_pending_validation_idx
            ON app.utility_readings(meter_id,reading_date,id)
            WHERE validated_at IS NULL;

        CREATE TABLE app.utility_reading_corrections (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            reading_id uuid NOT NULL REFERENCES app.utility_readings(id) ON DELETE RESTRICT,
            previous_value numeric(20,6) NOT NULL CHECK (previous_value >= 0),
            corrected_value numeric(20,6) NOT NULL CHECK (corrected_value >= 0),
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            ),
            CONSTRAINT utility_reading_corrections_changes_value
                CHECK (previous_value <> corrected_value)
        );
        CREATE INDEX utility_reading_corrections_history_idx
            ON app.utility_reading_corrections(reading_id,occurred_at,id);

        CREATE FUNCTION app.require_utility_read_committed()
        RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Utility persistence requires READ COMMITTED isolation'
                    USING ERRCODE='25001';
            END IF;
        END $$;

        CREATE FUNCTION app.lock_utility_property_type(p_property_id uuid,p_utility_type text)
        RETURNS void LANGUAGE sql SET search_path=pg_catalog AS $$
            SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-property-type:' || p_property_id::text || ':' || p_utility_type,0
            ))
        $$;

        CREATE FUNCTION app.lock_utility_unit_type(p_unit_id uuid,p_utility_type text)
        RETURNS void LANGUAGE sql SET search_path=pg_catalog AS $$
            SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-unit-type:' || p_unit_id::text || ':' || p_utility_type,0
            ))
        $$;

        CREATE FUNCTION app.lock_utility_meter_sequence(p_meter_id uuid)
        RETURNS void LANGUAGE sql SET search_path=pg_catalog AS $$
            SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-meter-sequence:' || p_meter_id::text,0
            ))
        $$;

        CREATE FUNCTION app.utility_reading_effective_value(p_reading_id uuid)
        RETURNS numeric(20,6) LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT COALESCE(
                (
                    SELECT correction.corrected_value
                    FROM app.utility_reading_corrections AS correction
                    WHERE correction.reading_id=p_reading_id
                    ORDER BY correction.occurred_at DESC,correction.id DESC
                    LIMIT 1
                ),
                reading.reading_value
            )
            FROM app.utility_readings AS reading
            WHERE reading.id=p_reading_id
        $$;

        CREATE FUNCTION app.guard_utility_meter()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid;
        BEGIN
            PERFORM app.require_utility_read_committed();
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=NEW.unit_id;
            PERFORM app.lock_utility_property_type(v_property_id,NEW.utility_type);
            PERFORM app.lock_utility_unit_type(NEW.unit_id,NEW.utility_type);
            PERFORM app.lock_utility_meter_sequence(NEW.id);
            IF TG_OP='UPDATE' THEN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
                    OR NEW.serial_number IS DISTINCT FROM OLD.serial_number
                    OR NEW.utility_type IS DISTINCT FROM OLD.utility_type
                    OR NEW.installed_date IS DISTINCT FROM OLD.installed_date
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.created_by IS DISTINCT FROM OLD.created_by
                    OR NEW.version<>OLD.version+1
                    OR NEW.updated_at<OLD.updated_at
                    OR (OLD.failure_date IS NOT NULL AND NEW.failure_date IS DISTINCT FROM OLD.failure_date)
                    OR (OLD.deactivated_date IS NOT NULL
                        AND NEW.deactivated_date IS DISTINCT FROM OLD.deactivated_date)
                THEN
                    RAISE EXCEPTION 'Utility Meter identity and history are protected'
                        USING ERRCODE='55000';
                END IF;
                IF NEW.measurement_unit_code IS DISTINCT FROM OLD.measurement_unit_code
                    AND EXISTS (
                        SELECT 1 FROM app.utility_readings AS reading
                        WHERE reading.meter_id=OLD.id
                    )
                THEN
                    RAISE EXCEPTION 'Meter measurement unit is immutable after first Reading'
                        USING ERRCODE='55000';
                END IF;
                IF NEW.failure_date IS NOT NULL AND EXISTS (
                    SELECT 1 FROM app.utility_readings AS reading
                    WHERE reading.meter_id=OLD.id
                      AND reading.reading_date>NEW.failure_date
                ) THEN
                    RAISE EXCEPTION 'Meter failure date conflicts with Reading history'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.utility_rates AS rate
                WHERE rate.property_id=v_property_id
                  AND rate.utility_type=NEW.utility_type
                  AND rate.measurement_unit_code<>NEW.measurement_unit_code
            ) THEN
                RAISE EXCEPTION 'Meter measurement unit conflicts with Utility Rate history'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.guard_utility_rate_meter_unit()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM app.require_utility_read_committed();
            PERFORM app.lock_utility_property_type(NEW.property_id,NEW.utility_type);
            IF EXISTS (
                SELECT 1
                FROM app.utility_meters AS meter
                JOIN app.units AS unit ON unit.id=meter.unit_id
                WHERE unit.property_id=NEW.property_id
                  AND meter.utility_type=NEW.utility_type
                  AND meter.measurement_unit_code<>NEW.measurement_unit_code
            ) THEN
                RAISE EXCEPTION 'Utility Rate measurement unit conflicts with Meter history'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.assert_utility_meter_replacement()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_failed app.utility_meters%ROWTYPE;
            v_replacement app.utility_meters%ROWTYPE;
            v_event app.utility_meter_replacements%ROWTYPE;
        BEGIN
            IF TG_TABLE_NAME='utility_meters' THEN
                IF NEW.deactivated_date IS NULL THEN RETURN NULL; END IF;
                SELECT * INTO v_event FROM app.utility_meter_replacements
                WHERE failed_meter_id=NEW.id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Deactivated Utility Meter requires replacement history'
                        USING ERRCODE='23514';
                END IF;
            ELSE
                v_event:=NEW;
            END IF;
            SELECT * INTO STRICT v_failed FROM app.utility_meters
            WHERE id=v_event.failed_meter_id;
            SELECT * INTO STRICT v_replacement FROM app.utility_meters
            WHERE id=v_event.replacement_meter_id;
            IF v_failed.unit_id<>v_replacement.unit_id
                OR v_failed.utility_type<>v_replacement.utility_type
                OR v_failed.failure_date IS NULL
                OR v_failed.failure_date>v_event.replacement_date
                OR v_failed.deactivated_date IS DISTINCT FROM v_event.replacement_date
                OR v_replacement.installed_date<>v_event.replacement_date
            THEN
                RAISE EXCEPTION 'Utility Meter replacement boundary is inconsistent'
                    USING ERRCODE='23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.utility_readings
                WHERE meter_id=v_failed.id AND reading_date>v_failed.failure_date
            ) OR EXISTS (
                SELECT 1 FROM app.utility_readings
                WHERE meter_id=v_replacement.id AND reading_date<v_event.replacement_date
            ) THEN
                RAISE EXCEPTION 'Utility Reading crosses its Meter replacement boundary'
                    USING ERRCODE='23514';
            END IF;
            IF EXISTS (
                WITH RECURSIVE replacement_chain(meter_id,path) AS (
                    SELECT v_event.replacement_meter_id,
                           ARRAY[v_event.replacement_meter_id]::uuid[]
                    UNION ALL
                    SELECT replacement.replacement_meter_id,
                           replacement_chain.path || replacement.replacement_meter_id
                    FROM replacement_chain
                    JOIN app.utility_meter_replacements AS replacement
                      ON replacement.failed_meter_id=replacement_chain.meter_id
                    WHERE NOT replacement.replacement_meter_id=ANY(replacement_chain.path)
                )
                SELECT 1 FROM replacement_chain
                WHERE meter_id=v_event.failed_meter_id
            ) THEN
                RAISE EXCEPTION 'Utility Meter replacement history must be acyclic'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;

        CREATE FUNCTION app.guard_utility_reading()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_meter app.utility_meters%ROWTYPE;
            v_previous_id uuid;
            v_previous_value numeric(20,6);
        BEGIN
            PERFORM app.require_utility_read_committed();
            PERFORM app.lock_utility_meter_sequence(NEW.meter_id);
            SELECT * INTO STRICT v_meter FROM app.utility_meters WHERE id=NEW.meter_id;
            IF NEW.reading_date<v_meter.installed_date
                OR (v_meter.failure_date IS NOT NULL
                    AND NEW.reading_date>v_meter.failure_date)
                OR (v_meter.deactivated_date IS NOT NULL
                    AND NEW.reading_date>v_meter.deactivated_date)
            THEN
                RAISE EXCEPTION 'Utility Reading is outside its Meter installation boundary'
                    USING ERRCODE='23514';
            END IF;
            IF TG_OP='UPDATE' THEN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.meter_id IS DISTINCT FROM OLD.meter_id
                    OR NEW.reading_date IS DISTINCT FROM OLD.reading_date
                    OR NEW.reading_value IS DISTINCT FROM OLD.reading_value
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.created_by IS DISTINCT FROM OLD.created_by
                    OR NEW.version<>OLD.version+1
                    OR NEW.updated_at<OLD.updated_at
                    OR OLD.validated_at IS NOT NULL
                    OR NEW.validated_at IS NULL OR NEW.validated_by IS NULL
                THEN
                    RAISE EXCEPTION 'Utility Reading identity and history are protected'
                        USING ERRCODE='55000';
                END IF;
            END IF;
            IF NEW.validated_at IS NOT NULL THEN
                IF NEW.validated_at>statement_timestamp() THEN
                    RAISE EXCEPTION 'Utility Reading validation cannot be future-dated'
                        USING ERRCODE='23514';
                END IF;
                SELECT reading.id,app.utility_reading_effective_value(reading.id)
                INTO v_previous_id,v_previous_value
                FROM app.utility_readings AS reading
                WHERE reading.meter_id=NEW.meter_id
                  AND reading.validated_at IS NOT NULL
                  AND reading.id<>NEW.id
                ORDER BY reading.reading_date DESC,reading.id DESC LIMIT 1;
                IF v_previous_id IS NOT NULL THEN
                    IF EXISTS (
                        SELECT 1 FROM app.utility_readings AS reading
                        WHERE reading.id=v_previous_id
                          AND reading.reading_date>=NEW.reading_date
                    ) OR NEW.reading_value<v_previous_value THEN
                        RAISE EXCEPTION 'Validated Utility Reading sequence is invalid'
                            USING ERRCODE='23514';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.guard_utility_reading_correction()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_reading app.utility_readings%ROWTYPE;
            v_meter_id uuid;
            v_current numeric(20,6);
            v_previous_neighbor numeric(20,6);
            v_next_neighbor numeric(20,6);
            v_latest_occurred_at timestamptz;
            v_latest_id uuid;
        BEGIN
            PERFORM app.require_utility_read_committed();
            SELECT reading.meter_id INTO STRICT v_meter_id
            FROM app.utility_readings AS reading WHERE reading.id=NEW.reading_id;
            PERFORM app.lock_utility_meter_sequence(v_meter_id);
            SELECT * INTO STRICT v_reading FROM app.utility_readings
            WHERE id=NEW.reading_id;
            IF v_reading.validated_at IS NULL THEN
                RAISE EXCEPTION 'Only a validated Utility Reading may be corrected'
                    USING ERRCODE='23514';
            END IF;
            v_current:=app.utility_reading_effective_value(NEW.reading_id);
            IF NEW.previous_value<>v_current THEN
                RAISE EXCEPTION 'Utility Reading correction is based on stale evidence'
                    USING ERRCODE='40001';
            END IF;
            SELECT correction.occurred_at,correction.id
            INTO v_latest_occurred_at,v_latest_id
            FROM app.utility_reading_corrections AS correction
            WHERE correction.reading_id=NEW.reading_id
            ORDER BY correction.occurred_at DESC,correction.id DESC
            LIMIT 1;
            IF NEW.occurred_at<v_reading.validated_at
                OR (v_latest_occurred_at IS NOT NULL
                    AND (NEW.occurred_at,NEW.id)<=(v_latest_occurred_at,v_latest_id))
                OR NEW.occurred_at>statement_timestamp()
            THEN
                RAISE EXCEPTION 'Utility Reading correction chronology is invalid'
                    USING ERRCODE='23514';
            END IF;
            SELECT app.utility_reading_effective_value(reading.id)
            INTO v_previous_neighbor
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=v_reading.meter_id
              AND reading.validated_at IS NOT NULL
              AND reading.reading_date<v_reading.reading_date
            ORDER BY reading.reading_date DESC,reading.id DESC LIMIT 1;
            SELECT app.utility_reading_effective_value(reading.id)
            INTO v_next_neighbor
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=v_reading.meter_id
              AND reading.validated_at IS NOT NULL
              AND reading.reading_date>v_reading.reading_date
            ORDER BY reading.reading_date,reading.id LIMIT 1;
            IF (v_previous_neighbor IS NOT NULL AND NEW.corrected_value<v_previous_neighbor)
                OR (v_next_neighbor IS NOT NULL AND NEW.corrected_value>v_next_neighbor)
            THEN
                RAISE EXCEPTION 'Utility Reading correction breaks adjacent history'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.reject_utility_history_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Utility operational history is append-preserved'
                USING ERRCODE='55000';
        END $$;

        CREATE TRIGGER utility_meters_guard
            BEFORE INSERT OR UPDATE ON app.utility_meters
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_meter();
        CREATE TRIGGER utility_meters_reject_delete
            BEFORE DELETE ON app.utility_meters
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE CONSTRAINT TRIGGER utility_meters_replacement_consistency
            AFTER INSERT OR UPDATE ON app.utility_meters DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_utility_meter_replacement();

        CREATE FUNCTION app.guard_utility_meter_replacement_insert()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_failed app.utility_meters%ROWTYPE; v_replacement app.utility_meters%ROWTYPE;
        BEGIN
            PERFORM app.require_utility_read_committed();
            SELECT * INTO STRICT v_failed FROM app.utility_meters WHERE id=NEW.failed_meter_id;
            SELECT * INTO STRICT v_replacement FROM app.utility_meters WHERE id=NEW.replacement_meter_id;
            IF v_failed.unit_id<>v_replacement.unit_id
                OR v_failed.utility_type<>v_replacement.utility_type THEN
                RAISE EXCEPTION 'Replacement Meter must retain Unit and Utility Type'
                    USING ERRCODE='23514';
            END IF;
            PERFORM app.lock_utility_unit_type(v_failed.unit_id,v_failed.utility_type);
            IF v_failed.id::text<v_replacement.id::text THEN
                PERFORM app.lock_utility_meter_sequence(v_failed.id);
                PERFORM app.lock_utility_meter_sequence(v_replacement.id);
            ELSE
                PERFORM app.lock_utility_meter_sequence(v_replacement.id);
                PERFORM app.lock_utility_meter_sequence(v_failed.id);
            END IF;
            SELECT * INTO STRICT v_failed FROM app.utility_meters
            WHERE id=NEW.failed_meter_id;
            SELECT * INTO STRICT v_replacement FROM app.utility_meters
            WHERE id=NEW.replacement_meter_id;
            RETURN NEW;
        END $$;
        CREATE TRIGGER utility_meter_replacements_guard
            BEFORE INSERT ON app.utility_meter_replacements
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_meter_replacement_insert();
        CREATE TRIGGER utility_meter_replacements_append_only
            BEFORE UPDATE OR DELETE ON app.utility_meter_replacements
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE CONSTRAINT TRIGGER utility_meter_replacements_consistency
            AFTER INSERT ON app.utility_meter_replacements DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_utility_meter_replacement();

        CREATE TRIGGER utility_readings_guard
            BEFORE INSERT OR UPDATE ON app.utility_readings
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_reading();
        CREATE TRIGGER utility_readings_reject_delete
            BEFORE DELETE ON app.utility_readings
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_reading_corrections_guard
            BEFORE INSERT ON app.utility_reading_corrections
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_reading_correction();
        CREATE TRIGGER utility_reading_corrections_append_only
            BEFORE UPDATE OR DELETE ON app.utility_reading_corrections
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_rates_00_meter_unit_guard
            BEFORE INSERT ON app.utility_rates
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_rate_meter_unit();

        CREATE TRIGGER utility_meters_reject_truncate
            BEFORE TRUNCATE ON app.utility_meters FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_meter_replacements_reject_truncate
            BEFORE TRUNCATE ON app.utility_meter_replacements FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_readings_reject_truncate
            BEFORE TRUNCATE ON app.utility_readings FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_reading_corrections_reject_truncate
            BEFORE TRUNCATE ON app.utility_reading_corrections FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        """
    )
    for table in (
        "utility_meters",
        "utility_meter_replacements",
        "utility_readings",
        "utility_reading_corrections",
    ):
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")
    for function in (
        "app.require_utility_read_committed()",
        "app.lock_utility_property_type(uuid,text)",
        "app.lock_utility_unit_type(uuid,text)",
        "app.lock_utility_meter_sequence(uuid)",
        "app.utility_reading_effective_value(uuid)",
        "app.guard_utility_meter()",
        "app.guard_utility_rate_meter_unit()",
        "app.assert_utility_meter_replacement()",
        "app.guard_utility_reading()",
        "app.guard_utility_reading_correction()",
        "app.guard_utility_meter_replacement_insert()",
        "app.reject_utility_history_mutation()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )


def downgrade() -> None:
    """Refuse destructive rollback of permanent Utility operational history."""
    raise RuntimeError("V1-041 Utility persistence is forward-only")
