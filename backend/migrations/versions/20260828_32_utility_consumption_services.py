# ruff: noqa: E501
"""Add Utility consumption and confirmed broken-Meter calculation services."""

from alembic import op

revision = "20260828_32"
down_revision = "20260828_31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-042 Utility calculation boundary."""
    op.execute(
        r"""
        CREATE TABLE app.utility_consumption_periods (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            utility_type text NOT NULL CHECK (utility_type IN ('ELECTRICITY','WATER')),
            start_date date NOT NULL,
            end_date date NOT NULL CHECK (end_date>=start_date),
            start_reading_id uuid REFERENCES app.utility_readings(id) ON DELETE RESTRICT,
            end_reading_id uuid REFERENCES app.utility_readings(id) ON DELETE RESTRICT,
            calculation_kind text NOT NULL CHECK (
                calculation_kind IN ('ACTUAL','BROKEN_METER_ESTIMATE')
            ),
            consumption_quantity numeric(38,6) NOT NULL CHECK (consumption_quantity>=0),
            calculation_trace jsonb NOT NULL CHECK (
                jsonb_typeof(calculation_trace)='object'
            ),
            finalized_at timestamptz NOT NULL,
            finalized_by uuid NOT NULL
                REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT utility_consumption_period_identity
                UNIQUE(id,unit_id,utility_type),
            CONSTRAINT utility_consumption_period_source_shape CHECK (
                (calculation_kind='ACTUAL'
                    AND start_reading_id IS NOT NULL AND end_reading_id IS NOT NULL
                    AND start_reading_id<>end_reading_id)
                OR (calculation_kind='BROKEN_METER_ESTIMATE'
                    AND start_reading_id IS NULL AND end_reading_id IS NULL)
            ),
            CONSTRAINT utility_consumption_period_business_key
                UNIQUE(unit_id,utility_type,start_date,end_date),
            CONSTRAINT utility_consumption_period_no_overlap EXCLUDE USING gist (
                unit_id WITH =,
                utility_type WITH =,
                daterange(start_date,end_date,'[]') WITH &&
            )
        );
        CREATE INDEX utility_consumption_period_history_idx
            ON app.utility_consumption_periods(
                unit_id,utility_type,calculation_kind,end_date DESC,start_date DESC,id
            );

        CREATE TABLE app.broken_meter_estimation_cases (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            failed_meter_id uuid NOT NULL UNIQUE
                REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            replacement_meter_id uuid NOT NULL UNIQUE
                REFERENCES app.utility_meters(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            utility_type text NOT NULL CHECK (utility_type IN ('ELECTRICITY','WATER')),
            unmeasured_start_date date NOT NULL,
            unmeasured_end_date date NOT NULL CHECK (
                unmeasured_end_date>=unmeasured_start_date
            ),
            historical_actual_period_count_at_open smallint NOT NULL CHECK (
                historical_actual_period_count_at_open>=0
            ),
            opened_reason text NOT NULL CHECK (
                length(btrim(opened_reason))>0 AND opened_reason=btrim(opened_reason)
            ),
            opened_at timestamptz NOT NULL,
            opened_by uuid NOT NULL
                REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference))>0
                AND authorization_reference=btrim(authorization_reference)
            ),
            CONSTRAINT broken_meter_case_distinct_meters CHECK (
                failed_meter_id<>replacement_meter_id
            ),
            CONSTRAINT broken_meter_case_identity
                UNIQUE(id,unit_id,utility_type)
        );
        CREATE INDEX broken_meter_case_pending_idx
            ON app.broken_meter_estimation_cases(unit_id,utility_type,opened_at,id);

        CREATE TABLE app.broken_meter_estimates (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            estimation_case_id uuid NOT NULL UNIQUE
                REFERENCES app.broken_meter_estimation_cases(id) ON DELETE RESTRICT,
            consumption_period_id uuid NOT NULL UNIQUE
                REFERENCES app.utility_consumption_periods(id) ON DELETE RESTRICT,
            basis_kind text NOT NULL CHECK (basis_kind IN (
                'LATEST_THREE_HISTORICAL',
                'ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO',
                'FIRST_COMPLETE_FUTURE_ZERO_HISTORY'
            )),
            historical_actual_period_count_at_selection smallint NOT NULL CHECK (
                historical_actual_period_count_at_selection>=0
            ),
            total_basis_consumption numeric(38,6) NOT NULL CHECK (
                total_basis_consumption>=0
            ),
            total_basis_days integer NOT NULL CHECK (total_basis_days>0),
            weighted_daily_average numeric(24,10) NOT NULL CHECK (
                weighted_daily_average>=0
            ),
            estimated_consumption numeric(38,6) NOT NULL CHECK (
                estimated_consumption>=0
            ),
            authorization_reason text NOT NULL CHECK (
                length(btrim(authorization_reason))>0
                AND authorization_reason=btrim(authorization_reason)
            ),
            authorized_at timestamptz NOT NULL,
            authorized_by uuid NOT NULL
                REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            calculation_trace jsonb NOT NULL CHECK (
                jsonb_typeof(calculation_trace)='object'
            )
        );

        CREATE TABLE app.broken_meter_estimate_basis_periods (
            broken_meter_estimate_id uuid NOT NULL
                REFERENCES app.broken_meter_estimates(id) ON DELETE RESTRICT,
            basis_consumption_period_id uuid NOT NULL
                REFERENCES app.utility_consumption_periods(id) ON DELETE RESTRICT,
            basis_order smallint NOT NULL CHECK (basis_order>0),
            PRIMARY KEY(broken_meter_estimate_id,basis_consumption_period_id),
            CONSTRAINT broken_meter_basis_order_unique
                UNIQUE(broken_meter_estimate_id,basis_order)
        );

        CREATE TABLE app.utility_reading_correction_impacts (
            id uuid PRIMARY KEY CHECK (
                id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            reading_correction_id uuid NOT NULL
                REFERENCES app.utility_reading_corrections(id) ON DELETE RESTRICT,
            consumption_period_id uuid NOT NULL
                REFERENCES app.utility_consumption_periods(id) ON DELETE RESTRICT,
            previous_consumption_quantity numeric(38,6) NOT NULL CHECK (
                previous_consumption_quantity>=0
            ),
            corrected_consumption_quantity numeric(38,6) NOT NULL CHECK (
                corrected_consumption_quantity>=0
            ),
            billing_effect_kind text NOT NULL CHECK (billing_effect_kind IN (
                'PRE_ISSUANCE_INPUT',
                'POST_ISSUANCE_NO_AMOUNT_CHANGE',
                'POST_ISSUANCE_ADJUSTMENT'
            )),
            invoice_line_id uuid REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            source_invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            calculated_difference_usd_cents bigint,
            invoice_adjustment_id uuid UNIQUE
                REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            calculation_trace jsonb NOT NULL CHECK (
                jsonb_typeof(calculation_trace)='object'
            ),
            CONSTRAINT utility_reading_correction_impact_unique
                UNIQUE(reading_correction_id,consumption_period_id),
            CONSTRAINT utility_reading_correction_effect_shape CHECK (
                (billing_effect_kind='PRE_ISSUANCE_INPUT'
                    AND invoice_line_id IS NULL AND source_invoice_id IS NULL
                    AND calculated_difference_usd_cents IS NULL
                    AND invoice_adjustment_id IS NULL)
                OR (billing_effect_kind='POST_ISSUANCE_NO_AMOUNT_CHANGE'
                    AND invoice_line_id IS NOT NULL AND source_invoice_id IS NOT NULL
                    AND calculated_difference_usd_cents=0
                    AND invoice_adjustment_id IS NULL)
                OR (billing_effect_kind='POST_ISSUANCE_ADJUSTMENT'
                    AND invoice_line_id IS NOT NULL AND source_invoice_id IS NOT NULL
                    AND calculated_difference_usd_cents<>0
                    AND invoice_adjustment_id IS NOT NULL)
            )
        );
        CREATE INDEX utility_reading_correction_impact_period_idx
            ON app.utility_reading_correction_impacts(consumption_period_id,reading_correction_id);

        CREATE TABLE app.utility_service_commands (
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL
                REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (
                idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            action text NOT NULL CHECK (action IN (
                'FINALIZE_ACTUAL',
                'OPEN_BROKEN_METER_CASE',
                'FINALIZE_BROKEN_METER_ESTIMATE'
            )),
            request_digest text NOT NULL CHECK (request_digest~'^[0-9a-f]{64}$'),
            request_evidence jsonb NOT NULL CHECK (
                jsonb_typeof(request_evidence)='object'
            ),
            result_snapshot jsonb NOT NULL CHECK (
                jsonb_typeof(result_snapshot)='object'
            ),
            completed_at timestamptz NOT NULL,
            PRIMARY KEY(property_id,actor_id,action,idempotency_key)
        );
        CREATE INDEX utility_service_command_result_idx
            ON app.utility_service_commands(action,completed_at,idempotency_key);

        ALTER TABLE app.invoice_lines
            ADD CONSTRAINT invoice_lines_utility_consumption_period_fk
            FOREIGN KEY(utility_consumption_period_id)
            REFERENCES app.utility_consumption_periods(id) ON DELETE RESTRICT;
        COMMENT ON COLUMN app.invoice_lines.utility_consumption_period_id IS
            'Stable DB-UTIL-006 identity; issuance remains prohibited until V1-044 installs the worker boundary';
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.lock_utility_consumption_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_unit_id uuid; v_utility_type text; v_property_id uuid;
        BEGIN
            IF TG_TABLE_NAME='utility_readings' THEN
                SELECT meter.unit_id,meter.utility_type,unit.property_id
                INTO STRICT v_unit_id,v_utility_type,v_property_id
                FROM app.utility_meters AS meter
                JOIN app.units AS unit ON unit.id=meter.unit_id
                WHERE meter.id=NEW.meter_id;
            ELSE
                SELECT meter.unit_id,meter.utility_type,unit.property_id
                INTO STRICT v_unit_id,v_utility_type,v_property_id
                FROM app.utility_readings AS reading
                JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                JOIN app.units AS unit ON unit.id=meter.unit_id
                WHERE reading.id=NEW.reading_id;
            END IF;
            PERFORM app.lock_utility_property_type(v_property_id,v_utility_type);
            PERFORM app.lock_utility_unit_type(v_unit_id,v_utility_type);
            IF TG_TABLE_NAME='utility_readings' THEN
                IF NEW.validated_at IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM app.broken_meter_estimation_cases AS case_record
                        WHERE case_record.unit_id=v_unit_id
                          AND case_record.utility_type=v_utility_type
                          AND NEW.reading_date<=case_record.unmeasured_start_date
                    )
                THEN
                    RAISE EXCEPTION 'Validated Utility Reading would change frozen broken-Meter evidence'
                        USING ERRCODE='55000';
                END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER utility_readings_00_consumption_lock
            BEFORE INSERT OR UPDATE ON app.utility_readings
            FOR EACH ROW EXECUTE FUNCTION app.lock_utility_consumption_source();
        CREATE TRIGGER utility_reading_corrections_00_consumption_lock
            BEFORE INSERT ON app.utility_reading_corrections
            FOR EACH ROW EXECUTE FUNCTION app.lock_utility_consumption_source();

        CREATE FUNCTION app.guard_utility_meter_estimation_unit()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid;
        BEGIN
            IF NEW.measurement_unit_code IS DISTINCT FROM OLD.measurement_unit_code THEN
                SELECT unit.property_id INTO STRICT v_property_id
                FROM app.units AS unit WHERE unit.id=OLD.unit_id;
                PERFORM app.lock_utility_property_type(v_property_id,OLD.utility_type);
                PERFORM app.lock_utility_unit_type(OLD.unit_id,OLD.utility_type);
                IF EXISTS (
                    SELECT 1
                    FROM app.broken_meter_estimation_cases AS case_record
                    WHERE OLD.id IN (
                        case_record.failed_meter_id,
                        case_record.replacement_meter_id
                    )
                ) THEN
                    RAISE EXCEPTION
                        'Meter measurement unit is immutable after broken-Meter case opening'
                        USING ERRCODE='55000';
                END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER utility_meters_00_estimation_unit_guard
            BEFORE UPDATE ON app.utility_meters
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_meter_estimation_unit();

        CREATE FUNCTION app.guard_utility_period_correction_chronology()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM app.utility_consumption_periods AS direct_period
                WHERE direct_period.calculation_kind='ACTUAL'
                  AND NEW.reading_id IN (
                      direct_period.start_reading_id,direct_period.end_reading_id
                  )
                  AND NEW.occurred_at<direct_period.finalized_at
            ) OR EXISTS (
                SELECT 1
                FROM app.broken_meter_estimates AS estimate
                JOIN app.broken_meter_estimate_basis_periods AS basis
                  ON basis.broken_meter_estimate_id=estimate.id
                JOIN app.utility_consumption_periods AS basis_period
                  ON basis_period.id=basis.basis_consumption_period_id
                WHERE NEW.reading_id IN (
                    basis_period.start_reading_id,basis_period.end_reading_id
                )
                  AND NEW.occurred_at<estimate.authorized_at
            ) THEN
                RAISE EXCEPTION 'Utility Reading correction predates an affected calculation'
                    USING ERRCODE='23514';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM app.utility_reading_correction_impacts AS impact
                JOIN app.utility_reading_corrections AS correction
                  ON correction.id=impact.reading_correction_id
                WHERE impact.consumption_period_id IN (
                    SELECT direct_period.id
                    FROM app.utility_consumption_periods AS direct_period
                    WHERE direct_period.calculation_kind='ACTUAL'
                      AND NEW.reading_id IN (
                          direct_period.start_reading_id,direct_period.end_reading_id
                      )
                    UNION
                    SELECT estimate.consumption_period_id
                    FROM app.broken_meter_estimates AS estimate
                    JOIN app.broken_meter_estimate_basis_periods AS basis
                      ON basis.broken_meter_estimate_id=estimate.id
                    JOIN app.utility_consumption_periods AS basis_period
                      ON basis_period.id=basis.basis_consumption_period_id
                    WHERE NEW.reading_id IN (
                        basis_period.start_reading_id,basis_period.end_reading_id
                    )
                )
                  AND (correction.occurred_at,correction.id)>=(NEW.occurred_at,NEW.id)
            ) THEN
                RAISE EXCEPTION 'Utility Reading correction chronology must advance every affected period'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER utility_reading_corrections_05_period_chronology
            BEFORE INSERT ON app.utility_reading_corrections
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_period_correction_chronology();

        CREATE FUNCTION app.utility_consumption_effective_quantity(p_period_id uuid)
        RETURNS numeric(38,6) LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT COALESCE(
                (
                    SELECT impact.corrected_consumption_quantity
                    FROM app.utility_reading_correction_impacts AS impact
                    JOIN app.utility_reading_corrections AS correction
                      ON correction.id=impact.reading_correction_id
                    WHERE impact.consumption_period_id=p_period_id
                    ORDER BY correction.occurred_at DESC,correction.id DESC
                    LIMIT 1
                ),
                period.consumption_quantity
            )
            FROM app.utility_consumption_periods AS period WHERE period.id=p_period_id
        $$;

        CREATE FUNCTION app.utility_estimate_effective_basis(p_estimate_id uuid)
        RETURNS TABLE(
            total_basis_consumption numeric(38,6),
            total_basis_days integer,
            weighted_daily_average numeric(24,10)
        ) LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT operands.total_basis_consumption,
                   operands.total_basis_days,
                   round(
                       operands.total_basis_consumption::numeric(50,16)
                       / operands.total_basis_days,
                       10
                   )::numeric(24,10)
            FROM (
                SELECT sum(
                           app.utility_consumption_effective_quantity(period.id)
                       )::numeric(38,6) AS total_basis_consumption,
                       sum(period.end_date-period.start_date+1)::integer
                           AS total_basis_days
                FROM app.broken_meter_estimate_basis_periods AS basis
                JOIN app.utility_consumption_periods AS period
                  ON period.id=basis.basis_consumption_period_id
                WHERE basis.broken_meter_estimate_id=p_estimate_id
            ) AS operands
            WHERE operands.total_basis_consumption IS NOT NULL
              AND operands.total_basis_days>0
        $$;

        CREATE FUNCTION app.utility_service_snapshot(p_period_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT pg_catalog.jsonb_build_object(
                'status','READY',
                'property_id',unit.property_id,
                'unit_id',period.unit_id,
                'utility_type',period.utility_type,
                'consumption_period_id',period.id,
                'calculation_kind',period.calculation_kind,
                'period_start',period.start_date,
                'period_end',period.end_date,
                'consumption_quantity',app.utility_consumption_effective_quantity(period.id),
                'represented_days',(period.end_date-period.start_date+1),
                'meter_id',start_reading.meter_id,
                'start_reading_id',period.start_reading_id,
                'end_reading_id',period.end_reading_id,
                'failed_meter_id',case_record.failed_meter_id,
                'replacement_meter_id',case_record.replacement_meter_id,
                'basis_kind',estimate.basis_kind,
                'total_basis_consumption',effective_basis.total_basis_consumption,
                'total_basis_days',effective_basis.total_basis_days,
                'weighted_daily_average',effective_basis.weighted_daily_average,
                'basis_period_ids',COALESCE(
                    (
                        SELECT pg_catalog.jsonb_agg(
                            basis.basis_consumption_period_id ORDER BY basis.basis_order
                        )
                        FROM app.broken_meter_estimate_basis_periods AS basis
                        WHERE basis.broken_meter_estimate_id=estimate.id
                    ),
                    '[]'::jsonb
                ),
                'basis_sources',COALESCE(
                    (
                        SELECT pg_catalog.jsonb_agg(
                            pg_catalog.jsonb_build_object(
                                'consumption_period_id',basis_period.id,
                                'meter_id',basis_start.meter_id,
                                'start_reading_id',basis_period.start_reading_id,
                                'end_reading_id',basis_period.end_reading_id
                            ) ORDER BY basis.basis_order
                        )
                        FROM app.broken_meter_estimate_basis_periods AS basis
                        JOIN app.utility_consumption_periods AS basis_period
                          ON basis_period.id=basis.basis_consumption_period_id
                        JOIN app.utility_readings AS basis_start
                          ON basis_start.id=basis_period.start_reading_id
                        WHERE basis.broken_meter_estimate_id=estimate.id
                    ),
                    '[]'::jsonb
                )
            )
            FROM app.utility_consumption_periods AS period
            JOIN app.units AS unit ON unit.id=period.unit_id
            LEFT JOIN app.utility_readings AS start_reading
              ON start_reading.id=period.start_reading_id
            LEFT JOIN app.broken_meter_estimates AS estimate
              ON estimate.consumption_period_id=period.id
            LEFT JOIN app.broken_meter_estimation_cases AS case_record
              ON case_record.id=estimate.estimation_case_id
            LEFT JOIN LATERAL app.utility_estimate_effective_basis(estimate.id)
              AS effective_basis ON true
            WHERE period.id=p_period_id
        $$;

        CREATE FUNCTION app.utility_case_snapshot(p_case_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT pg_catalog.jsonb_build_object(
                'status',CASE
                    WHEN case_record.historical_actual_period_count_at_open=0
                      AND NOT EXISTS (
                          SELECT 1
                          FROM app.utility_consumption_periods AS future
                          WHERE future.unit_id=case_record.unit_id
                            AND future.utility_type=case_record.utility_type
                            AND future.calculation_kind='ACTUAL'
                            AND future.start_date>case_record.unmeasured_end_date
                      )
                    THEN 'PENDING_FUTURE_ACTUAL_BASIS' ELSE 'READY' END,
                'property_id',unit.property_id,
                'unit_id',case_record.unit_id,
                'utility_type',case_record.utility_type,
                'consumption_period_id',NULL,
                'calculation_kind',NULL,
                'period_start',case_record.unmeasured_start_date,
                'period_end',case_record.unmeasured_end_date,
                'consumption_quantity',NULL,
                'represented_days',(
                    case_record.unmeasured_end_date-case_record.unmeasured_start_date+1
                ),
                'meter_id',NULL,
                'start_reading_id',NULL,
                'end_reading_id',NULL,
                'failed_meter_id',case_record.failed_meter_id,
                'replacement_meter_id',case_record.replacement_meter_id,
                'basis_kind',NULL,
                'total_basis_consumption',NULL,
                'total_basis_days',NULL,
                'weighted_daily_average',NULL,
                'basis_period_ids','[]'::jsonb,
                'basis_sources','[]'::jsonb
            )
            FROM app.broken_meter_estimation_cases AS case_record
            JOIN app.units AS unit ON unit.id=case_record.unit_id
            WHERE case_record.id=p_case_id
        $$;

        CREATE FUNCTION app.utility_case_preview_snapshot(p_case_id uuid)
        RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
        DECLARE
            v_case app.broken_meter_estimation_cases%ROWTYPE;
            v_property_id uuid; v_existing_period_id uuid;
            v_history_count integer; v_basis_kind text;
            v_basis record; v_basis_ids uuid[]:=ARRAY[]::uuid[];
            v_total numeric(38,6):=0; v_days integer:=0;
            v_average numeric(24,10); v_estimated numeric(38,6);
            v_unmeasured_days integer;
            v_basis_sources jsonb;
        BEGIN
            SELECT case_record.* INTO v_case
            FROM app.broken_meter_estimation_cases AS case_record
            WHERE case_record.id=p_case_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=v_case.unit_id;
            SELECT estimate.consumption_period_id INTO v_existing_period_id
            FROM app.broken_meter_estimates AS estimate
            WHERE estimate.estimation_case_id=p_case_id;
            IF FOUND THEN
                RETURN app.utility_service_snapshot(v_existing_period_id);
            END IF;
            SELECT count(*) INTO v_history_count
            FROM app.utility_consumption_periods AS history
            WHERE history.unit_id=v_case.unit_id
              AND history.utility_type=v_case.utility_type
              AND history.calculation_kind='ACTUAL'
              AND history.end_date<v_case.unmeasured_start_date;
            IF v_history_count<>v_case.historical_actual_period_count_at_open THEN
                RAISE EXCEPTION 'Broken-Meter historical basis changed after case opening'
                    USING ERRCODE='55000';
            END IF;
            IF v_history_count>=3 THEN
                v_basis_kind:='LATEST_THREE_HISTORICAL';
                FOR v_basis IN
                    SELECT history.id,
                           app.utility_consumption_effective_quantity(history.id) quantity,
                           history.end_date-history.start_date+1 represented_days
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_case.unit_id
                      AND history.utility_type=v_case.utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_case.unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                    LIMIT 3
                LOOP
                    v_total:=v_total+v_basis.quantity;
                    v_days:=v_days+v_basis.represented_days;
                    v_basis_ids:=array_append(v_basis_ids,v_basis.id);
                END LOOP;
            ELSIF v_history_count>0 THEN
                v_basis_kind:='ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO';
                FOR v_basis IN
                    SELECT history.id,
                           app.utility_consumption_effective_quantity(history.id) quantity,
                           history.end_date-history.start_date+1 represented_days
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_case.unit_id
                      AND history.utility_type=v_case.utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_case.unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                LOOP
                    v_total:=v_total+v_basis.quantity;
                    v_days:=v_days+v_basis.represented_days;
                    v_basis_ids:=array_append(v_basis_ids,v_basis.id);
                END LOOP;
            ELSE
                v_basis_kind:='FIRST_COMPLETE_FUTURE_ZERO_HISTORY';
                SELECT future.id,
                       app.utility_consumption_effective_quantity(future.id) quantity,
                       future.end_date-future.start_date+1 represented_days
                INTO v_basis
                FROM app.utility_consumption_periods AS future
                WHERE future.unit_id=v_case.unit_id
                  AND future.utility_type=v_case.utility_type
                  AND future.calculation_kind='ACTUAL'
                  AND future.start_date>v_case.unmeasured_end_date
                ORDER BY future.start_date,future.end_date,future.id LIMIT 1;
                IF NOT FOUND THEN RETURN app.utility_case_snapshot(p_case_id); END IF;
                v_total:=v_basis.quantity;
                v_days:=v_basis.represented_days;
                v_basis_ids:=ARRAY[v_basis.id];
            END IF;
            v_unmeasured_days:=v_case.unmeasured_end_date-v_case.unmeasured_start_date+1;
            v_average:=round(v_total::numeric(50,16)/v_days,10);
            v_estimated:=round(
                v_total::numeric(50,16)*v_unmeasured_days::numeric/v_days,
                6
            );
            SELECT pg_catalog.jsonb_agg(
                       pg_catalog.jsonb_build_object(
                           'consumption_period_id',period.id,
                           'meter_id',reading.meter_id,
                           'start_reading_id',period.start_reading_id,
                           'end_reading_id',period.end_reading_id
                       ) ORDER BY source.ordinality
                   )
            INTO v_basis_sources
            FROM unnest(v_basis_ids) WITH ORDINALITY AS source(period_id,ordinality)
            JOIN app.utility_consumption_periods AS period ON period.id=source.period_id
            JOIN app.utility_readings AS reading ON reading.id=period.start_reading_id;
            RETURN pg_catalog.jsonb_build_object(
                'status','READY','property_id',v_property_id,
                'unit_id',v_case.unit_id,'utility_type',v_case.utility_type,
                'consumption_period_id',NULL,
                'calculation_kind','BROKEN_METER_ESTIMATE',
                'period_start',v_case.unmeasured_start_date,
                'period_end',v_case.unmeasured_end_date,
                'consumption_quantity',v_estimated,
                'represented_days',v_unmeasured_days,
                'meter_id',NULL,'start_reading_id',NULL,'end_reading_id',NULL,
                'failed_meter_id',v_case.failed_meter_id,
                'replacement_meter_id',v_case.replacement_meter_id,
                'basis_kind',v_basis_kind,
                'total_basis_consumption',v_total,
                'total_basis_days',v_days,
                'weighted_daily_average',v_average,
                'basis_period_ids',to_jsonb(v_basis_ids),
                'basis_sources',COALESCE(v_basis_sources,'[]'::jsonb)
            );
        END $$;

        CREATE FUNCTION app.utility_responsibility_window_is_stable(
            p_unit_id uuid,p_start_date date,p_end_date date
        ) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT p_unit_id IS NOT NULL AND p_start_date IS NOT NULL
               AND p_end_date IS NOT NULL AND p_end_date>=p_start_date
               AND NOT EXISTS (
                    SELECT 1
                    FROM (
                        SELECT lease.start_date AS boundary_date
                        FROM app.leases AS lease
                        WHERE lease.unit_id=p_unit_id
                          AND lease.status IN ('SIGNED','TERMINATED')
                        UNION ALL
                        SELECT COALESCE(lease.actual_termination_date,lease.end_date)+1
                        FROM app.leases AS lease
                        WHERE lease.unit_id=p_unit_id
                          AND lease.status IN ('SIGNED','TERMINATED')
                        UNION ALL
                        SELECT occupancy.move_in_date
                        FROM app.occupancies AS occupancy
                        JOIN app.leases AS lease ON lease.id=occupancy.lease_id
                        JOIN app.lease_signers AS signer
                          ON signer.lease_id=occupancy.lease_id
                         AND signer.customer_id=occupancy.customer_id
                         AND signer.signed_at IS NOT NULL
                        WHERE lease.unit_id=p_unit_id
                        UNION ALL
                        SELECT occupancy.move_out_date+1
                        FROM app.occupancies AS occupancy
                        JOIN app.leases AS lease ON lease.id=occupancy.lease_id
                        JOIN app.lease_signers AS signer
                          ON signer.lease_id=occupancy.lease_id
                         AND signer.customer_id=occupancy.customer_id
                         AND signer.signed_at IS NOT NULL
                        WHERE lease.unit_id=p_unit_id
                          AND occupancy.move_out_date IS NOT NULL
                    ) AS responsibility_boundary
                    WHERE responsibility_boundary.boundary_date>p_start_date
                      AND responsibility_boundary.boundary_date<=p_end_date
               )
        $$;

        CREATE FUNCTION app.guard_utility_responsibility_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_unit_id uuid; v_property_id uuid; v_boundary_date date;
            v_new jsonb:=to_jsonb(NEW);
        BEGIN
            IF TG_TABLE_NAME='leases' THEN
                IF v_new->>'status' NOT IN ('SIGNED','TERMINATED') THEN RETURN NEW; END IF;
                v_unit_id:=(v_new->>'unit_id')::uuid;
            ELSE
                SELECT lease.unit_id INTO STRICT v_unit_id
                FROM app.leases AS lease WHERE lease.id=(v_new->>'lease_id')::uuid;
                IF NOT EXISTS (
                    SELECT 1
                    FROM app.lease_signers AS signer
                    WHERE signer.lease_id=(v_new->>'lease_id')::uuid
                      AND signer.customer_id=(v_new->>'customer_id')::uuid
                      AND signer.signed_at IS NOT NULL
                ) THEN
                    RETURN NEW;
                END IF;
            END IF;
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=v_unit_id;
            PERFORM app.lock_utility_property_type(v_property_id,'ELECTRICITY');
            PERFORM app.lock_utility_property_type(v_property_id,'WATER');
            PERFORM app.lock_utility_unit_type(v_unit_id,'ELECTRICITY');
            PERFORM app.lock_utility_unit_type(v_unit_id,'WATER');
            FOR v_boundary_date IN
                SELECT boundary_date
                FROM (
                    SELECT (v_new->>'start_date')::date AS boundary_date
                    WHERE TG_TABLE_NAME='leases'
                    UNION ALL
                    SELECT COALESCE(
                        (v_new->>'actual_termination_date')::date,
                        (v_new->>'end_date')::date
                    )+1
                    WHERE TG_TABLE_NAME='leases'
                    UNION ALL
                    SELECT (v_new->>'move_in_date')::date
                    WHERE TG_TABLE_NAME='occupancies'
                    UNION ALL
                    SELECT (v_new->>'move_out_date')::date+1
                    WHERE TG_TABLE_NAME='occupancies' AND v_new->>'move_out_date' IS NOT NULL
                ) AS proposed_boundary
                WHERE boundary_date IS NOT NULL
            LOOP
                IF EXISTS (
                    SELECT 1 FROM app.utility_consumption_periods AS period
                    WHERE period.unit_id=v_unit_id
                      AND period.start_date<v_boundary_date
                      AND period.end_date>=v_boundary_date
                ) OR EXISTS (
                    SELECT 1 FROM app.broken_meter_estimation_cases AS case_record
                    WHERE case_record.unit_id=v_unit_id
                      AND case_record.unmeasured_start_date<v_boundary_date
                      AND case_record.unmeasured_end_date>=v_boundary_date
                ) THEN
                    RAISE EXCEPTION
                        'Responsibility change requires an exact Utility Reading or estimate boundary'
                        USING ERRCODE='23514';
                END IF;
            END LOOP;
            RETURN NEW;
        END $$;

        CREATE TRIGGER leases_zz_utility_responsibility_guard
            BEFORE INSERT OR UPDATE ON app.leases
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_responsibility_change();
        CREATE TRIGGER occupancies_zz_utility_responsibility_guard
            BEFORE INSERT OR UPDATE ON app.occupancies
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_responsibility_change();

        CREATE FUNCTION app.guard_broken_meter_responsibility_window()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_property_id uuid;
        BEGIN
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=NEW.unit_id;
            PERFORM app.lock_utility_property_type(v_property_id,NEW.utility_type);
            PERFORM app.lock_utility_unit_type(NEW.unit_id,NEW.utility_type);
            IF NOT app.utility_responsibility_window_is_stable(
                NEW.unit_id,NEW.unmeasured_start_date,NEW.unmeasured_end_date
            ) THEN
                RAISE EXCEPTION
                    'Broken-Meter interval crosses a Customer responsibility boundary'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER broken_meter_estimation_cases_00_responsibility_guard
            BEFORE INSERT ON app.broken_meter_estimation_cases
            FOR EACH ROW EXECUTE FUNCTION app.guard_broken_meter_responsibility_window();

        CREATE FUNCTION app.assert_broken_meter_case()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_failed_unit_id uuid; v_replacement_unit_id uuid;
            v_failed_utility_type text; v_replacement_utility_type text;
            v_failed_measurement_unit_code text;
            v_replacement_measurement_unit_code text;
            v_failure_date date; v_replacement_date date;
            v_replacement_occurred_at timestamptz;
            v_first_replacement_reading_date date;
            v_first_replacement_validated_at timestamptz;
            v_failure_reading_validated_at timestamptz;
            v_expected_start_date date; v_expected_end_date date;
            v_historical_count integer; v_latest_historical_finalized_at timestamptz;
        BEGIN
            SELECT failed.unit_id,replacement.unit_id,
                   failed.utility_type,replacement.utility_type,
                   failed.measurement_unit_code,replacement.measurement_unit_code,
                   failed.failure_date,event.replacement_date,event.occurred_at
            INTO v_failed_unit_id,v_replacement_unit_id,
                 v_failed_utility_type,v_replacement_utility_type,
                 v_failed_measurement_unit_code,v_replacement_measurement_unit_code,
                 v_failure_date,v_replacement_date,v_replacement_occurred_at
            FROM app.utility_meter_replacements AS event
            JOIN app.utility_meters AS failed ON failed.id=event.failed_meter_id
            JOIN app.utility_meters AS replacement ON replacement.id=event.replacement_meter_id
            WHERE event.failed_meter_id=NEW.failed_meter_id
              AND event.replacement_meter_id=NEW.replacement_meter_id;
            IF NOT FOUND
                OR v_failed_unit_id<>NEW.unit_id
                OR v_replacement_unit_id<>NEW.unit_id
                OR v_failed_utility_type<>NEW.utility_type
                OR v_replacement_utility_type<>NEW.utility_type
                OR v_failed_measurement_unit_code<>v_replacement_measurement_unit_code
                OR v_failure_date IS NULL
                OR v_replacement_date<v_failure_date
            THEN
                RAISE EXCEPTION 'Broken-Meter case Meter identity is invalid'
                    USING ERRCODE='23514';
            END IF;
            SELECT reading.reading_date,reading.validated_at
            INTO v_first_replacement_reading_date,v_first_replacement_validated_at
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=NEW.replacement_meter_id
              AND reading.validated_at IS NOT NULL
            ORDER BY reading.reading_date,reading.id LIMIT 1;
            IF NOT FOUND
                OR v_first_replacement_reading_date<v_replacement_date
                OR v_first_replacement_reading_date<=v_failure_date
            THEN
                RAISE EXCEPTION 'Broken-Meter case replacement boundary is invalid'
                    USING ERRCODE='23514';
            END IF;
            SELECT reading.validated_at INTO v_failure_reading_validated_at
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=NEW.failed_meter_id
              AND reading.validated_at IS NOT NULL
              AND reading.reading_date=v_failure_date;
            v_expected_start_date:=v_failure_date;
            IF FOUND THEN v_expected_start_date:=v_failure_date+1; END IF;
            v_expected_end_date:=v_first_replacement_reading_date-1;
            SELECT count(*),max(period.finalized_at)
            INTO v_historical_count,v_latest_historical_finalized_at
            FROM app.utility_consumption_periods AS period
            WHERE period.unit_id=NEW.unit_id
              AND period.utility_type=NEW.utility_type
              AND period.calculation_kind='ACTUAL'
              AND period.end_date<v_expected_start_date;
            IF NEW.unmeasured_start_date<>v_expected_start_date
                OR NEW.unmeasured_end_date<>v_expected_end_date
                OR NEW.historical_actual_period_count_at_open<>v_historical_count
                OR NEW.opened_at>clock_timestamp()
                OR NEW.opened_at<v_replacement_occurred_at
                OR NEW.opened_at<v_first_replacement_validated_at
                OR (v_failure_reading_validated_at IS NOT NULL
                    AND NEW.opened_at<v_failure_reading_validated_at)
                OR (v_latest_historical_finalized_at IS NOT NULL
                    AND NEW.opened_at<v_latest_historical_finalized_at)
            THEN
                RAISE EXCEPTION 'Broken-Meter case derived evidence is invalid'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;

        CREATE CONSTRAINT TRIGGER broken_meter_estimation_cases_validate
            AFTER INSERT ON app.broken_meter_estimation_cases
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_broken_meter_case();

        CREATE FUNCTION app.guard_utility_consumption_period()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_start_meter uuid; v_end_meter uuid;
            v_start_unit uuid; v_end_unit uuid;
            v_start_type text; v_end_type text;
            v_start_measurement_unit_code text;
            v_start_date date; v_end_date date;
            v_start_value numeric(20,6); v_end_value numeric(20,6);
            v_start_validated timestamptz; v_end_validated timestamptz;
            v_latest_source_evidence_at timestamptz;
            v_property_id uuid;
        BEGIN
            PERFORM app.require_utility_read_committed();
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=NEW.unit_id;
            PERFORM app.lock_utility_property_type(v_property_id,NEW.utility_type);
            PERFORM app.lock_utility_unit_type(NEW.unit_id,NEW.utility_type);
            IF NOT app.utility_responsibility_window_is_stable(
                NEW.unit_id,NEW.start_date,NEW.end_date
            ) THEN
                RAISE EXCEPTION
                    'Utility period crosses a Customer responsibility boundary'
                    USING ERRCODE='23514';
            END IF;
            IF NEW.finalized_at>clock_timestamp() THEN
                RAISE EXCEPTION 'Utility finalization time must not be in the future'
                    USING ERRCODE='22023';
            END IF;
            IF NEW.calculation_kind='ACTUAL' THEN
                SELECT reading.meter_id,meter.unit_id,meter.utility_type,
                       meter.measurement_unit_code,
                       reading.reading_date,app.utility_reading_effective_value(reading.id),
                       reading.validated_at
                INTO STRICT v_start_meter,v_start_unit,v_start_type,
                     v_start_measurement_unit_code,
                     v_start_date,v_start_value,v_start_validated
                FROM app.utility_readings AS reading
                JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                WHERE reading.id=NEW.start_reading_id;
                SELECT reading.meter_id,meter.unit_id,meter.utility_type,
                       reading.reading_date,app.utility_reading_effective_value(reading.id),
                       reading.validated_at
                INTO STRICT v_end_meter,v_end_unit,v_end_type,
                     v_end_date,v_end_value,v_end_validated
                FROM app.utility_readings AS reading
                JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                WHERE reading.id=NEW.end_reading_id;
                SELECT max(source.evidence_at) INTO v_latest_source_evidence_at
                FROM (
                    SELECT reading.validated_at AS evidence_at
                    FROM app.utility_readings AS reading
                    WHERE reading.id IN (NEW.start_reading_id,NEW.end_reading_id)
                    UNION ALL
                    SELECT correction.occurred_at
                    FROM app.utility_reading_corrections AS correction
                    WHERE correction.reading_id IN (
                        NEW.start_reading_id,NEW.end_reading_id
                    )
                ) AS source;
                IF v_start_meter<>v_end_meter OR v_start_unit<>NEW.unit_id
                    OR v_end_unit<>NEW.unit_id OR v_start_type<>NEW.utility_type
                    OR v_end_type<>NEW.utility_type OR v_start_validated IS NULL
                    OR v_end_validated IS NULL OR v_end_date<=v_start_date
                    OR NEW.start_date<>v_start_date+1 OR NEW.end_date<>v_end_date
                    OR NEW.consumption_quantity<>v_end_value-v_start_value
                    OR NEW.consumption_quantity<0
                    OR NEW.finalized_at<v_latest_source_evidence_at
                    OR EXISTS (
                        SELECT 1 FROM app.utility_readings AS intermediate
                        WHERE intermediate.meter_id=v_start_meter
                          AND intermediate.validated_at IS NOT NULL
                          AND intermediate.reading_date>v_start_date
                          AND intermediate.reading_date<v_end_date
                    )
                THEN
                    RAISE EXCEPTION 'Actual Utility Consumption source is invalid'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM app.broken_meter_estimation_cases AS case_record
                    WHERE case_record.unit_id=NEW.unit_id
                      AND case_record.utility_type=NEW.utility_type
                      AND NEW.start_date<=case_record.unmeasured_end_date
                ) THEN
                    RAISE EXCEPTION 'Actual Utility period would change a frozen broken-Meter basis'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM app.broken_meter_estimation_cases AS case_record
                    WHERE case_record.unit_id=NEW.unit_id
                      AND case_record.utility_type=NEW.utility_type
                      AND case_record.historical_actual_period_count_at_open=0
                      AND NEW.start_date>case_record.unmeasured_end_date
                      AND NOT EXISTS (
                          SELECT 1 FROM app.broken_meter_estimates AS estimate
                          WHERE estimate.estimation_case_id=case_record.id
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM (
                              SELECT reading.id AS end_reading_id,
                                     reading.reading_date AS end_reading_date,
                                     lag(reading.id) OVER (
                                         PARTITION BY reading.meter_id
                                         ORDER BY reading.reading_date,reading.id
                                     ) AS start_reading_id,
                                     lag(reading.reading_date) OVER (
                                         PARTITION BY reading.meter_id
                                         ORDER BY reading.reading_date,reading.id
                                     ) AS start_reading_date
                              FROM app.utility_readings AS reading
                              JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                              WHERE meter.unit_id=NEW.unit_id
                                AND meter.utility_type=NEW.utility_type
                                AND reading.validated_at IS NOT NULL
                          ) AS candidate
                          WHERE candidate.start_reading_id IS NOT NULL
                            AND candidate.start_reading_date<candidate.end_reading_date
                            AND candidate.start_reading_date+1>
                                case_record.unmeasured_end_date
                            AND (
                                candidate.start_reading_date+1,
                                candidate.end_reading_date,
                                candidate.end_reading_id
                            ) < (NEW.start_date,NEW.end_date,NEW.end_reading_id)
                            AND app.utility_responsibility_window_is_stable(
                                NEW.unit_id,
                                candidate.start_reading_date+1,
                                candidate.end_reading_date
                            )
                            AND NOT EXISTS (
                                SELECT 1
                                FROM app.utility_consumption_periods AS finalized
                                WHERE finalized.calculation_kind='ACTUAL'
                                  AND finalized.start_reading_id=candidate.start_reading_id
                                  AND finalized.end_reading_id=candidate.end_reading_id
                            )
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Earlier eligible future Utility consumption must be finalized first'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM app.broken_meter_estimation_cases AS case_record
                    JOIN app.utility_meters AS failed_meter
                      ON failed_meter.id=case_record.failed_meter_id
                    WHERE case_record.unit_id=NEW.unit_id
                      AND case_record.utility_type=NEW.utility_type
                      AND case_record.historical_actual_period_count_at_open=0
                      AND NEW.start_date>case_record.unmeasured_end_date
                      AND failed_meter.measurement_unit_code<>
                          v_start_measurement_unit_code
                      AND NOT EXISTS (
                          SELECT 1 FROM app.broken_meter_estimates AS estimate
                          WHERE estimate.estimation_case_id=case_record.id
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM app.utility_consumption_periods AS earlier_future
                          WHERE earlier_future.unit_id=NEW.unit_id
                            AND earlier_future.utility_type=NEW.utility_type
                            AND earlier_future.calculation_kind='ACTUAL'
                            AND earlier_future.start_date>case_record.unmeasured_end_date
                            AND (
                                earlier_future.start_date,
                                earlier_future.end_date,
                                earlier_future.id
                            ) < (NEW.start_date,NEW.end_date,NEW.id)
                      )
                ) THEN
                    RAISE EXCEPTION
                        'First future Utility basis uses a different measurement unit'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM app.broken_meter_estimation_cases AS case_record
                    JOIN app.broken_meter_estimates AS estimate
                      ON estimate.estimation_case_id=case_record.id
                     AND estimate.basis_kind='FIRST_COMPLETE_FUTURE_ZERO_HISTORY'
                    JOIN app.broken_meter_estimate_basis_periods AS basis
                      ON basis.broken_meter_estimate_id=estimate.id
                    JOIN app.utility_consumption_periods AS selected_basis
                      ON selected_basis.id=basis.basis_consumption_period_id
                    WHERE case_record.unit_id=NEW.unit_id
                      AND case_record.utility_type=NEW.utility_type
                      AND NEW.start_date>case_record.unmeasured_end_date
                      AND (NEW.start_date,NEW.end_date,NEW.id)<
                          (selected_basis.start_date,selected_basis.end_date,selected_basis.id)
                ) THEN
                    RAISE EXCEPTION 'Actual Utility period would precede a frozen first future basis'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER utility_consumption_periods_guard
            BEFORE INSERT ON app.utility_consumption_periods
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_consumption_period();

        CREATE FUNCTION app.assert_utility_consumption_period()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_period app.utility_consumption_periods%ROWTYPE;
            v_period_id uuid;
        BEGIN
            v_period_id:=CASE
                WHEN TG_TABLE_NAME='broken_meter_estimates'
                THEN (to_jsonb(NEW)->>'consumption_period_id')::uuid
                ELSE (to_jsonb(NEW)->>'id')::uuid
            END;
            SELECT * INTO v_period FROM app.utility_consumption_periods
            WHERE id=v_period_id;
            IF v_period.calculation_kind='BROKEN_METER_ESTIMATE' AND NOT EXISTS (
                SELECT 1 FROM app.broken_meter_estimates AS estimate
                WHERE estimate.consumption_period_id=v_period.id
            ) THEN
                RAISE EXCEPTION 'Estimated Utility period requires exact estimate evidence'
                    USING ERRCODE='23514';
            END IF;
            IF v_period.calculation_kind='ACTUAL' AND EXISTS (
                SELECT 1 FROM app.broken_meter_estimates AS estimate
                WHERE estimate.consumption_period_id=v_period.id
            ) THEN
                RAISE EXCEPTION 'Actual Utility period cannot carry estimate evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;

        CREATE CONSTRAINT TRIGGER utility_consumption_periods_validate
            AFTER INSERT ON app.utility_consumption_periods DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_utility_consumption_period();
        CREATE CONSTRAINT TRIGGER broken_meter_estimates_validate_period
            AFTER INSERT ON app.broken_meter_estimates DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_utility_consumption_period();

        CREATE FUNCTION app.assert_broken_meter_estimate()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_estimate app.broken_meter_estimates%ROWTYPE;
            v_case app.broken_meter_estimation_cases%ROWTYPE;
            v_period app.utility_consumption_periods%ROWTYPE;
            v_count integer; v_history_count integer;
            v_total numeric(38,6); v_days integer;
            v_expected_ids uuid[]; v_actual_ids uuid[];
            v_estimate_id uuid;
            v_latest_basis_evidence_at timestamptz;
            v_measurement_unit_code text;
        BEGIN
            v_estimate_id:=CASE
                WHEN TG_TABLE_NAME='broken_meter_estimate_basis_periods'
                THEN (to_jsonb(NEW)->>'broken_meter_estimate_id')::uuid
                ELSE (to_jsonb(NEW)->>'id')::uuid
            END;
            SELECT estimate.* INTO v_estimate
            FROM app.broken_meter_estimates AS estimate
            WHERE estimate.id=v_estimate_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT * INTO STRICT v_case FROM app.broken_meter_estimation_cases
            WHERE id=v_estimate.estimation_case_id;
            SELECT * INTO STRICT v_period FROM app.utility_consumption_periods
            WHERE id=v_estimate.consumption_period_id;
            SELECT failed.measurement_unit_code INTO STRICT v_measurement_unit_code
            FROM app.utility_meters AS failed
            JOIN app.utility_meters AS replacement
              ON replacement.id=v_case.replacement_meter_id
            WHERE failed.id=v_case.failed_meter_id
              AND replacement.measurement_unit_code=failed.measurement_unit_code;
            SELECT count(*),COALESCE(sum(app.utility_consumption_effective_quantity(
                       basis.basis_consumption_period_id)),0),
                   COALESCE(sum(period.end_date-period.start_date+1),0),
                   array_agg(basis.basis_consumption_period_id ORDER BY basis.basis_order)
            INTO v_count,v_total,v_days,v_actual_ids
            FROM app.broken_meter_estimate_basis_periods AS basis
            JOIN app.utility_consumption_periods AS period
              ON period.id=basis.basis_consumption_period_id
            WHERE basis.broken_meter_estimate_id=v_estimate.id;
            IF EXISTS (
                SELECT 1
                FROM app.broken_meter_estimate_basis_periods AS basis
                JOIN app.utility_consumption_periods AS basis_period
                  ON basis_period.id=basis.basis_consumption_period_id
                JOIN app.utility_readings AS start_reading
                  ON start_reading.id=basis_period.start_reading_id
                JOIN app.utility_meters AS basis_meter
                  ON basis_meter.id=start_reading.meter_id
                WHERE basis.broken_meter_estimate_id=v_estimate.id
                  AND basis_meter.measurement_unit_code<>v_measurement_unit_code
            ) THEN
                RAISE EXCEPTION
                    'Broken-Meter basis measurement unit is inconsistent'
                    USING ERRCODE='23514';
            END IF;
            SELECT max(source.evidence_at) INTO v_latest_basis_evidence_at
            FROM (
                SELECT period.finalized_at AS evidence_at
                FROM app.utility_consumption_periods AS period
                WHERE period.id=ANY(COALESCE(v_actual_ids,ARRAY[]::uuid[]))
                UNION ALL
                SELECT correction.occurred_at
                FROM app.utility_reading_correction_impacts AS impact
                JOIN app.utility_reading_corrections AS correction
                  ON correction.id=impact.reading_correction_id
                WHERE impact.consumption_period_id=ANY(
                    COALESCE(v_actual_ids,ARRAY[]::uuid[])
                )
            ) AS source;
            SELECT count(*) INTO v_history_count
            FROM app.utility_consumption_periods AS history
            WHERE history.unit_id=v_case.unit_id
              AND history.utility_type=v_case.utility_type
              AND history.calculation_kind='ACTUAL'
              AND history.end_date<v_case.unmeasured_start_date;
            IF v_estimate.basis_kind='LATEST_THREE_HISTORICAL' THEN
                SELECT array_agg(candidate.id ORDER BY candidate.end_date DESC,
                                 candidate.start_date DESC,candidate.id DESC)
                INTO v_expected_ids FROM (
                    SELECT history.id,history.end_date,history.start_date
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_case.unit_id
                      AND history.utility_type=v_case.utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_case.unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                    LIMIT 3
                ) AS candidate;
                IF v_history_count<3 OR v_count<>3 OR v_actual_ids<>v_expected_ids THEN
                    RAISE EXCEPTION 'Broken-Meter latest-three basis is invalid'
                        USING ERRCODE='23514';
                END IF;
            ELSIF v_estimate.basis_kind='ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO' THEN
                SELECT array_agg(history.id ORDER BY history.end_date DESC,
                                 history.start_date DESC,history.id DESC)
                INTO v_expected_ids
                FROM app.utility_consumption_periods AS history
                WHERE history.unit_id=v_case.unit_id
                  AND history.utility_type=v_case.utility_type
                  AND history.calculation_kind='ACTUAL'
                  AND history.end_date<v_case.unmeasured_start_date;
                IF v_history_count NOT BETWEEN 1 AND 2
                    OR v_count<>v_history_count OR v_actual_ids<>v_expected_ids
                THEN
                    RAISE EXCEPTION 'Broken-Meter one-or-two-period basis is invalid'
                        USING ERRCODE='23514';
                END IF;
            ELSE
                SELECT ARRAY[future.id] INTO v_expected_ids
                FROM app.utility_consumption_periods AS future
                WHERE future.unit_id=v_case.unit_id
                  AND future.utility_type=v_case.utility_type
                  AND future.calculation_kind='ACTUAL'
                  AND future.start_date>v_case.unmeasured_end_date
                ORDER BY future.start_date,future.end_date,future.id LIMIT 1;
                IF v_expected_ids IS NULL OR v_history_count<>0
                    OR v_count<>1 OR v_actual_ids<>v_expected_ids
                THEN
                    RAISE EXCEPTION 'Broken-Meter future-period basis is invalid'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            IF v_period.unit_id<>v_case.unit_id
                OR v_period.utility_type<>v_case.utility_type
                OR v_period.calculation_kind<>'BROKEN_METER_ESTIMATE'
                OR v_period.start_date<>v_case.unmeasured_start_date
                OR v_period.end_date<>v_case.unmeasured_end_date
                OR v_period.consumption_quantity<>v_estimate.estimated_consumption
                OR v_period.finalized_at<>v_estimate.authorized_at
                OR v_period.finalized_by<>v_estimate.authorized_by
                OR v_estimate.authorized_at<v_case.opened_at
                OR v_estimate.authorized_at<v_latest_basis_evidence_at
                OR v_estimate.authorized_at>clock_timestamp()
                OR v_estimate.historical_actual_period_count_at_selection<>v_history_count
                OR v_estimate.total_basis_consumption<>v_total
                OR v_estimate.total_basis_days<>v_days
                OR v_estimate.weighted_daily_average<>
                    round(v_total::numeric(50,16)/v_days,10)
                OR v_estimate.estimated_consumption<>round(
                    v_total::numeric(50,16)*
                        (v_case.unmeasured_end_date-v_case.unmeasured_start_date+1)::numeric/
                        v_days,
                    6
                )
            THEN
                RAISE EXCEPTION 'Broken-Meter calculation evidence is inconsistent'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;

        CREATE CONSTRAINT TRIGGER broken_meter_estimates_validate_basis
            AFTER INSERT ON app.broken_meter_estimates DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_broken_meter_estimate();
        CREATE CONSTRAINT TRIGGER broken_meter_estimate_basis_validate
            AFTER INSERT ON app.broken_meter_estimate_basis_periods
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.assert_broken_meter_estimate();

        CREATE FUNCTION app.capture_utility_reading_correction_impacts()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_period app.utility_consumption_periods%ROWTYPE;
        DECLARE v_estimate record;
        DECLARE v_previous numeric(38,6); v_corrected numeric(38,6);
        BEGIN
            FOR v_period IN
                SELECT period.* FROM app.utility_consumption_periods AS period
                WHERE period.calculation_kind='ACTUAL'
                  AND NEW.reading_id IN (period.start_reading_id,period.end_reading_id)
                ORDER BY period.start_date,period.id
            LOOP
                IF EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    WHERE line.utility_consumption_period_id=v_period.id
                ) THEN
                    RAISE EXCEPTION 'Issued Utility correction requires linked Adjustment evidence'
                        USING ERRCODE='55000';
                END IF;
                v_corrected:=app.utility_reading_effective_value(v_period.end_reading_id)
                    - app.utility_reading_effective_value(v_period.start_reading_id);
                v_previous:=v_corrected+CASE
                    WHEN NEW.reading_id=v_period.start_reading_id
                    THEN NEW.corrected_value-NEW.previous_value
                    ELSE NEW.previous_value-NEW.corrected_value
                END;
                IF v_corrected<0 THEN
                    RAISE EXCEPTION 'Utility correction creates negative Consumption'
                        USING ERRCODE='23514';
                END IF;
                INSERT INTO app.utility_reading_correction_impacts(
                    id,reading_correction_id,consumption_period_id,
                    previous_consumption_quantity,corrected_consumption_quantity,
                    billing_effect_kind,calculation_trace
                ) VALUES (
                    md5(NEW.id::text || ':' || v_period.id::text)::uuid,
                    NEW.id,v_period.id,v_previous,v_corrected,'PRE_ISSUANCE_INPUT',
                    pg_catalog.jsonb_build_object(
                        'reading_correction_id',NEW.id,
                        'consumption_period_id',v_period.id,
                        'previous_consumption_quantity',v_previous,
                        'corrected_consumption_quantity',v_corrected
                    )
                );
            END LOOP;
            FOR v_estimate IN
                SELECT estimate.id,estimate.consumption_period_id,
                       case_record.unmeasured_end_date-case_record.unmeasured_start_date+1
                           AS unmeasured_days,
                       sum(app.utility_consumption_effective_quantity(
                           basis.basis_consumption_period_id
                       )) AS total_basis_consumption,
                       sum(basis_period.end_date-basis_period.start_date+1) AS total_basis_days
                FROM app.broken_meter_estimates AS estimate
                JOIN app.broken_meter_estimation_cases AS case_record
                  ON case_record.id=estimate.estimation_case_id
                JOIN app.broken_meter_estimate_basis_periods AS basis
                  ON basis.broken_meter_estimate_id=estimate.id
                JOIN app.utility_consumption_periods AS basis_period
                  ON basis_period.id=basis.basis_consumption_period_id
                WHERE EXISTS (
                    SELECT 1
                    FROM app.broken_meter_estimate_basis_periods AS affected_basis
                    JOIN app.utility_consumption_periods AS affected_period
                      ON affected_period.id=affected_basis.basis_consumption_period_id
                    WHERE affected_basis.broken_meter_estimate_id=estimate.id
                      AND NEW.reading_id IN (
                          affected_period.start_reading_id,affected_period.end_reading_id
                      )
                )
                GROUP BY estimate.id,estimate.consumption_period_id,
                         case_record.unmeasured_start_date,case_record.unmeasured_end_date
                ORDER BY estimate.id
            LOOP
                IF EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    WHERE line.utility_consumption_period_id=v_estimate.consumption_period_id
                ) THEN
                    RAISE EXCEPTION 'Issued Utility estimate correction requires linked Adjustment evidence'
                        USING ERRCODE='55000';
                END IF;
                v_previous:=app.utility_consumption_effective_quantity(
                    v_estimate.consumption_period_id
                );
                v_corrected:=round(
                    v_estimate.total_basis_consumption::numeric(50,16)
                        *v_estimate.unmeasured_days
                        /v_estimate.total_basis_days,
                    6
                );
                INSERT INTO app.utility_reading_correction_impacts(
                    id,reading_correction_id,consumption_period_id,
                    previous_consumption_quantity,corrected_consumption_quantity,
                    billing_effect_kind,calculation_trace
                ) VALUES (
                    md5(NEW.id::text || ':' || v_estimate.consumption_period_id::text)::uuid,
                    NEW.id,v_estimate.consumption_period_id,v_previous,v_corrected,
                    'PRE_ISSUANCE_INPUT',
                    pg_catalog.jsonb_build_object(
                        'reading_correction_id',NEW.id,
                        'broken_meter_estimate_id',v_estimate.id,
                        'consumption_period_id',v_estimate.consumption_period_id,
                        'previous_consumption_quantity',v_previous,
                        'corrected_consumption_quantity',v_corrected,
                        'total_basis_consumption',v_estimate.total_basis_consumption,
                        'total_basis_days',v_estimate.total_basis_days,
                        'unmeasured_days',v_estimate.unmeasured_days
                    )
                );
            END LOOP;
            RETURN NEW;
        END $$;

        CREATE TRIGGER utility_reading_corrections_90_capture_impacts
            AFTER INSERT ON app.utility_reading_corrections
            FOR EACH ROW EXECUTE FUNCTION app.capture_utility_reading_correction_impacts();

        CREATE FUNCTION app.utility_command_replay(
            p_property_id uuid,p_actor_id uuid,p_idempotency_key uuid,
            p_action text,p_request_digest text,p_request_evidence jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_command app.utility_service_commands%ROWTYPE;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-command:' || p_property_id::text || ':' || p_actor_id::text
                    || ':' || p_action || ':' || p_idempotency_key::text,0
            ));
            SELECT * INTO v_command FROM app.utility_service_commands
            WHERE property_id=p_property_id AND actor_id=p_actor_id
              AND action=p_action AND idempotency_key=p_idempotency_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            IF v_command.request_digest IS DISTINCT FROM p_request_digest
                OR v_command.request_evidence IS DISTINCT FROM p_request_evidence
            THEN
                RAISE EXCEPTION 'Utility idempotency key conflicts with another request'
                    USING ERRCODE='23505';
            END IF;
            RETURN v_command.result_snapshot;
        END $$;

        CREATE FUNCTION app.finalize_actual_utility_consumption(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_consumption_period_id uuid,p_unit_id uuid,p_utility_type text,
            p_start_reading_id uuid,p_end_reading_id uuid,
            p_finalized_at timestamptz,p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_evidence jsonb; v_replay jsonb; v_result jsonb;
            v_start_date date; v_end_date date;
            v_start_value numeric(20,6); v_end_value numeric(20,6);
            v_meter_id uuid;
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
                OR p_property_id IS NULL OR p_idempotency_key IS NULL
                OR p_consumption_period_id IS NULL OR p_unit_id IS NULL
                OR p_start_reading_id IS NULL OR p_end_reading_id IS NULL
                OR p_start_reading_id=p_end_reading_id OR p_finalized_at IS NULL
                OR p_actor_id IS NULL OR p_utility_type NOT IN ('ELECTRICITY','WATER')
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Actual Utility command evidence is invalid'
                    USING ERRCODE='22023';
            END IF;
            v_evidence:=pg_catalog.jsonb_build_object(
                'consumption_period_id',p_consumption_period_id,
                'unit_id',p_unit_id,'utility_type',p_utility_type,
                'start_reading_id',p_start_reading_id,
                'end_reading_id',p_end_reading_id,
                'finalized_at',p_finalized_at
            );
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            v_replay:=app.utility_command_replay(
                p_property_id,p_actor_id,p_idempotency_key,'FINALIZE_ACTUAL',
                p_request_digest,v_evidence
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            PERFORM app.lock_utility_property_type(p_property_id,p_utility_type);
            PERFORM app.lock_utility_unit_type(p_unit_id,p_utility_type);
            SELECT start_reading.reading_date,
                   app.utility_reading_effective_value(start_reading.id),
                   end_reading.reading_date,
                   app.utility_reading_effective_value(end_reading.id),
                   start_reading.meter_id
            INTO v_start_date,v_start_value,v_end_date,v_end_value,v_meter_id
            FROM app.utility_readings AS start_reading
            JOIN app.utility_readings AS end_reading
              ON end_reading.id=p_end_reading_id
             AND end_reading.meter_id=start_reading.meter_id
            JOIN app.utility_meters AS meter ON meter.id=start_reading.meter_id
            JOIN app.units AS unit ON unit.id=meter.unit_id
            WHERE start_reading.id=p_start_reading_id
              AND meter.unit_id=p_unit_id AND meter.utility_type=p_utility_type
              AND unit.property_id=p_property_id
              AND start_reading.validated_at IS NOT NULL
              AND end_reading.validated_at IS NOT NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Actual Utility Readings were not found in Property scope'
                    USING ERRCODE='P0002';
            END IF;
            INSERT INTO app.utility_consumption_periods(
                id,unit_id,utility_type,start_date,end_date,start_reading_id,end_reading_id,
                calculation_kind,consumption_quantity,calculation_trace,
                finalized_at,finalized_by
            ) VALUES (
                p_consumption_period_id,p_unit_id,p_utility_type,v_start_date+1,v_end_date,
                p_start_reading_id,p_end_reading_id,'ACTUAL',v_end_value-v_start_value,
                pg_catalog.jsonb_build_object(
                    'meter_id',v_meter_id,'start_reading_id',p_start_reading_id,
                    'start_reading_date',v_start_date,'start_effective_value',v_start_value,
                    'end_reading_id',p_end_reading_id,'end_reading_date',v_end_date,
                    'end_effective_value',v_end_value
                ),
                p_finalized_at,p_actor_id
            );
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.utility_service_snapshot(p_consumption_period_id);
            INSERT INTO app.utility_service_commands(
                property_id,actor_id,idempotency_key,action,request_digest,
                request_evidence,result_snapshot,completed_at
            ) VALUES (
                p_property_id,p_actor_id,p_idempotency_key,'FINALIZE_ACTUAL',
                p_request_digest,v_evidence,v_result,clock_timestamp()
            );
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.open_broken_meter_estimation_case(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_case_id uuid,p_failed_meter_id uuid,p_replacement_meter_id uuid,
            p_opened_reason text,p_opened_at timestamptz,p_actor_id uuid,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_evidence jsonb; v_replay jsonb; v_result jsonb;
            v_unit_id uuid; v_utility_type text;
            v_measurement_unit_code text;
            v_replacement_measurement_unit_code text;
            v_failure_date date; v_replacement_date date; v_replacement_at timestamptz;
            v_unmeasured_start_date date;
            v_first_replacement_reading_date date;
            v_first_replacement_validated_at timestamptz;
            v_failure_reading_validated_at timestamptz;
            v_latest_historical_finalized_at timestamptz;
            v_first_future_finalized_at timestamptz;
            v_first_future_start_reading_id uuid;
            v_first_future_end_reading_id uuid;
            v_first_future_measurement_unit_code text;
            v_history_count integer;
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
                OR p_property_id IS NULL OR p_idempotency_key IS NULL OR p_case_id IS NULL
                OR p_failed_meter_id IS NULL OR p_replacement_meter_id IS NULL
                OR p_failed_meter_id=p_replacement_meter_id OR p_opened_at IS NULL
                OR p_actor_id IS NULL OR p_request_digest IS NULL
                OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_opened_reason IS NULL OR length(btrim(p_opened_reason))=0
                OR p_opened_reason<>btrim(p_opened_reason)
                OR p_authorization_reference IS NULL
                OR p_authorization_reference<>'utility.estimate'
            THEN
                RAISE EXCEPTION 'Broken-Meter case evidence is invalid'
                    USING ERRCODE='22023';
            END IF;
            v_evidence:=pg_catalog.jsonb_build_object(
                'estimation_case_id',p_case_id,'failed_meter_id',p_failed_meter_id,
                'replacement_meter_id',p_replacement_meter_id,
                'opened_reason',p_opened_reason,'opened_at',p_opened_at,
                'authorization_reference',p_authorization_reference
            );
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            v_replay:=app.utility_command_replay(
                p_property_id,p_actor_id,p_idempotency_key,'OPEN_BROKEN_METER_CASE',
                p_request_digest,v_evidence
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            SELECT failed.unit_id,failed.utility_type,failed.measurement_unit_code,
                   successor.measurement_unit_code,failed.failure_date,
                   replacement.replacement_date,replacement.occurred_at
            INTO v_unit_id,v_utility_type,v_measurement_unit_code,
                 v_replacement_measurement_unit_code,v_failure_date,
                 v_replacement_date,v_replacement_at
            FROM app.utility_meter_replacements AS replacement
            JOIN app.utility_meters AS failed ON failed.id=replacement.failed_meter_id
            JOIN app.utility_meters AS successor
              ON successor.id=replacement.replacement_meter_id
            JOIN app.units AS unit ON unit.id=failed.unit_id
            WHERE replacement.failed_meter_id=p_failed_meter_id
              AND replacement.replacement_meter_id=p_replacement_meter_id
              AND successor.unit_id=failed.unit_id
              AND successor.utility_type=failed.utility_type
              AND unit.property_id=p_property_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Confirmed failed and replacement Meters were not found'
                    USING ERRCODE='P0002';
            END IF;
            PERFORM app.lock_utility_property_type(p_property_id,v_utility_type);
            PERFORM app.lock_utility_unit_type(v_unit_id,v_utility_type);
            SELECT failed.unit_id,failed.utility_type,failed.measurement_unit_code,
                   successor.measurement_unit_code,failed.failure_date,
                   replacement.replacement_date,replacement.occurred_at
            INTO v_unit_id,v_utility_type,v_measurement_unit_code,
                 v_replacement_measurement_unit_code,v_failure_date,
                 v_replacement_date,v_replacement_at
            FROM app.utility_meter_replacements AS replacement
            JOIN app.utility_meters AS failed ON failed.id=replacement.failed_meter_id
            JOIN app.utility_meters AS successor
              ON successor.id=replacement.replacement_meter_id
            JOIN app.units AS unit ON unit.id=failed.unit_id
            WHERE replacement.failed_meter_id=p_failed_meter_id
              AND replacement.replacement_meter_id=p_replacement_meter_id
              AND successor.unit_id=failed.unit_id
              AND successor.utility_type=failed.utility_type
              AND unit.property_id=p_property_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Confirmed failed and replacement Meters were not found'
                    USING ERRCODE='P0002';
            END IF;
            IF v_replacement_measurement_unit_code<>v_measurement_unit_code THEN
                RAISE EXCEPTION
                    'Broken-Meter estimation requires one measurement unit across replacement'
                    USING ERRCODE='23514';
            END IF;
            IF v_failure_date IS NULL OR v_replacement_date<v_failure_date
                OR p_opened_at<v_replacement_at OR p_opened_at>clock_timestamp()
            THEN
                RAISE EXCEPTION 'Confirmed broken-Meter boundary is invalid'
                    USING ERRCODE='23514';
            END IF;
            SELECT reading.reading_date,reading.validated_at
            INTO v_first_replacement_reading_date,v_first_replacement_validated_at
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=p_replacement_meter_id
              AND reading.validated_at IS NOT NULL
            ORDER BY reading.reading_date,reading.id LIMIT 1;
            IF NOT FOUND
                OR v_first_replacement_reading_date<v_replacement_date
                OR v_first_replacement_reading_date<=v_failure_date
                OR p_opened_at<v_first_replacement_validated_at
            THEN
                RAISE EXCEPTION 'Replacement Meter requires its first validated Reading before estimation'
                    USING ERRCODE='23514';
            END IF;
            v_unmeasured_start_date:=v_failure_date;
            SELECT reading.validated_at INTO v_failure_reading_validated_at
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=p_failed_meter_id
              AND reading.validated_at IS NOT NULL
              AND reading.reading_date=v_failure_date;
            IF FOUND THEN
                v_unmeasured_start_date:=v_failure_date+1;
            END IF;
            IF v_failure_reading_validated_at IS NOT NULL
                AND p_opened_at<v_failure_reading_validated_at
            THEN
                RAISE EXCEPTION 'Broken-Meter case opening predates boundary evidence'
                    USING ERRCODE='23514';
            END IF;
            IF v_unmeasured_start_date>v_first_replacement_reading_date-1 THEN
                RAISE EXCEPTION 'Confirmed broken-Meter boundary has no unmeasured period'
                    USING ERRCODE='23514';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT reading.id AS end_reading_id,
                           reading.reading_date AS end_reading_date,
                           lag(reading.id) OVER (
                               PARTITION BY reading.meter_id
                               ORDER BY reading.reading_date,reading.id
                           ) AS start_reading_id,
                           lag(reading.reading_date) OVER (
                               PARTITION BY reading.meter_id
                               ORDER BY reading.reading_date,reading.id
                           ) AS start_reading_date
                    FROM app.utility_readings AS reading
                    JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                    WHERE meter.unit_id=v_unit_id
                      AND meter.utility_type=v_utility_type
                      AND reading.validated_at IS NOT NULL
                ) AS candidate
                WHERE candidate.start_reading_id IS NOT NULL
                  AND candidate.start_reading_date<candidate.end_reading_date
                  AND candidate.end_reading_date<v_unmeasured_start_date
                  AND app.utility_responsibility_window_is_stable(
                      v_unit_id,
                      candidate.start_reading_date+1,
                      candidate.end_reading_date
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM app.utility_consumption_periods AS period
                      WHERE period.calculation_kind='ACTUAL'
                        AND period.start_reading_id=candidate.start_reading_id
                        AND period.end_reading_id=candidate.end_reading_id
                  )
            ) THEN
                RAISE EXCEPTION
                    'Eligible historical Utility consumption must be finalized before opening a broken-Meter case'
                    USING ERRCODE='55000';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT history.start_reading_id
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_unit_id
                      AND history.utility_type=v_utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                    LIMIT 3
                ) AS selected_history
                JOIN app.utility_readings AS start_reading
                  ON start_reading.id=selected_history.start_reading_id
                JOIN app.utility_meters AS basis_meter
                  ON basis_meter.id=start_reading.meter_id
                WHERE basis_meter.measurement_unit_code<>v_measurement_unit_code
            ) THEN
                RAISE EXCEPTION
                    'Broken-Meter historical basis uses a different measurement unit'
                    USING ERRCODE='23514';
            END IF;
            SELECT count(*),max(history.finalized_at)
            INTO v_history_count,v_latest_historical_finalized_at
            FROM app.utility_consumption_periods AS history
            WHERE history.unit_id=v_unit_id AND history.utility_type=v_utility_type
              AND history.calculation_kind='ACTUAL'
              AND history.end_date<v_unmeasured_start_date;
            IF v_latest_historical_finalized_at IS NOT NULL
                AND p_opened_at<v_latest_historical_finalized_at
            THEN
                RAISE EXCEPTION 'Broken-Meter case opening predates historical basis evidence'
                    USING ERRCODE='23514';
            END IF;
            IF v_history_count=0 THEN
                SELECT candidate.start_reading_id,candidate.end_reading_id
                INTO v_first_future_start_reading_id,v_first_future_end_reading_id
                FROM (
                    SELECT reading.id AS end_reading_id,
                           reading.reading_date AS end_reading_date,
                           lag(reading.id) OVER (
                               PARTITION BY reading.meter_id
                               ORDER BY reading.reading_date,reading.id
                           ) AS start_reading_id,
                           lag(reading.reading_date) OVER (
                               PARTITION BY reading.meter_id
                               ORDER BY reading.reading_date,reading.id
                           ) AS start_reading_date
                    FROM app.utility_readings AS reading
                    JOIN app.utility_meters AS meter ON meter.id=reading.meter_id
                    WHERE meter.unit_id=v_unit_id
                      AND meter.utility_type=v_utility_type
                      AND reading.validated_at IS NOT NULL
                ) AS candidate
                WHERE candidate.start_reading_id IS NOT NULL
                  AND candidate.start_reading_date<candidate.end_reading_date
                  AND candidate.start_reading_date+1>
                      v_first_replacement_reading_date-1
                  AND app.utility_responsibility_window_is_stable(
                      v_unit_id,
                      candidate.start_reading_date+1,
                      candidate.end_reading_date
                  )
                ORDER BY candidate.start_reading_date+1,
                         candidate.end_reading_date,candidate.end_reading_id
                LIMIT 1;
                IF FOUND AND NOT EXISTS (
                    SELECT 1
                    FROM app.utility_consumption_periods AS finalized
                    WHERE finalized.calculation_kind='ACTUAL'
                      AND finalized.start_reading_id=v_first_future_start_reading_id
                      AND finalized.end_reading_id=v_first_future_end_reading_id
                ) THEN
                    RAISE EXCEPTION
                        'Earlier eligible future Utility consumption must be finalized first'
                        USING ERRCODE='23514';
                END IF;
                SELECT future.finalized_at,basis_meter.measurement_unit_code
                INTO v_first_future_finalized_at,v_first_future_measurement_unit_code
                FROM app.utility_consumption_periods AS future
                JOIN app.utility_readings AS start_reading
                  ON start_reading.id=future.start_reading_id
                JOIN app.utility_meters AS basis_meter
                  ON basis_meter.id=start_reading.meter_id
                WHERE future.unit_id=v_unit_id
                  AND future.utility_type=v_utility_type
                  AND future.calculation_kind='ACTUAL'
                  AND future.start_date>v_first_replacement_reading_date-1
                ORDER BY future.start_date,future.end_date,future.id LIMIT 1;
                IF FOUND THEN
                    IF v_first_future_measurement_unit_code<>v_measurement_unit_code THEN
                        RAISE EXCEPTION
                            'Broken-Meter future basis uses a different measurement unit'
                            USING ERRCODE='23514';
                    END IF;
                    IF p_opened_at<v_first_future_finalized_at THEN
                        RAISE EXCEPTION
                            'Broken-Meter case opening predates future basis evidence'
                            USING ERRCODE='23514';
                    END IF;
                END IF;
            END IF;
            INSERT INTO app.broken_meter_estimation_cases(
                id,failed_meter_id,replacement_meter_id,unit_id,utility_type,
                unmeasured_start_date,unmeasured_end_date,
                historical_actual_period_count_at_open,opened_reason,opened_at,
                opened_by,authorization_reference
            ) VALUES (
                p_case_id,p_failed_meter_id,p_replacement_meter_id,v_unit_id,v_utility_type,
                v_unmeasured_start_date,v_first_replacement_reading_date-1,
                v_history_count,p_opened_reason,p_opened_at,
                p_actor_id,p_authorization_reference
            );
            v_result:=app.utility_case_snapshot(p_case_id);
            INSERT INTO app.utility_service_commands(
                property_id,actor_id,idempotency_key,action,request_digest,
                request_evidence,result_snapshot,completed_at
            ) VALUES (
                p_property_id,p_actor_id,p_idempotency_key,'OPEN_BROKEN_METER_CASE',
                p_request_digest,v_evidence,v_result,clock_timestamp()
            );
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.finalize_broken_meter_estimate(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_case_id uuid,p_estimate_id uuid,p_consumption_period_id uuid,
            p_authorization_reason text,p_authorized_at timestamptz,p_actor_id uuid,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_evidence jsonb; v_replay jsonb; v_result jsonb; v_before jsonb;
            v_case app.broken_meter_estimation_cases%ROWTYPE;
            v_history_count integer; v_basis_kind text;
            v_basis record; v_order smallint:=0;
            v_total numeric(38,6):=0; v_days integer:=0; v_unmeasured_days integer;
            v_average numeric(24,10); v_estimated numeric(38,6);
            v_basis_ids uuid[]:=ARRAY[]::uuid[];
            v_basis_id uuid;
            v_latest_basis_evidence_at timestamptz;
            v_timezone text; v_measurement_unit_code text;
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
                OR p_property_id IS NULL OR p_idempotency_key IS NULL OR p_case_id IS NULL
                OR p_estimate_id IS NULL OR p_consumption_period_id IS NULL
                OR p_authorized_at IS NULL OR p_actor_id IS NULL
                OR p_request_digest IS NULL OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_authorization_reason IS NULL
                OR length(btrim(p_authorization_reason))=0
                OR p_authorization_reason<>btrim(p_authorization_reason)
                OR p_authorization_reference IS NULL
                OR p_authorization_reference<>'utility.estimate'
            THEN
                RAISE EXCEPTION 'Broken-Meter estimate evidence is invalid'
                    USING ERRCODE='22023';
            END IF;
            v_evidence:=pg_catalog.jsonb_build_object(
                'estimation_case_id',p_case_id,'estimate_id',p_estimate_id,
                'consumption_period_id',p_consumption_period_id,
                'authorization_reason',p_authorization_reason,
                'authorized_at',p_authorized_at,
                'authorization_reference',p_authorization_reference
            );
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            v_replay:=app.utility_command_replay(
                p_property_id,p_actor_id,p_idempotency_key,
                'FINALIZE_BROKEN_METER_ESTIMATE',p_request_digest,v_evidence
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            SELECT case_record.* INTO v_case
            FROM app.broken_meter_estimation_cases AS case_record
            JOIN app.units AS unit ON unit.id=case_record.unit_id
            WHERE case_record.id=p_case_id AND unit.property_id=p_property_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Broken-Meter case was not found in Property scope'
                    USING ERRCODE='P0002';
            END IF;
            PERFORM app.lock_utility_property_type(p_property_id,v_case.utility_type);
            PERFORM app.lock_utility_unit_type(v_case.unit_id,v_case.utility_type);
            SELECT failed.measurement_unit_code INTO STRICT v_measurement_unit_code
            FROM app.utility_meters AS failed
            JOIN app.utility_meters AS replacement
              ON replacement.id=v_case.replacement_meter_id
            WHERE failed.id=v_case.failed_meter_id
              AND replacement.measurement_unit_code=failed.measurement_unit_code;
            IF v_case.historical_actual_period_count_at_open IS DISTINCT FROM (
                SELECT count(*)
                FROM app.utility_consumption_periods AS frozen_history
                WHERE frozen_history.unit_id=v_case.unit_id
                  AND frozen_history.utility_type=v_case.utility_type
                  AND frozen_history.calculation_kind='ACTUAL'
                  AND frozen_history.end_date<v_case.unmeasured_start_date
            ) THEN
                RAISE EXCEPTION 'Broken-Meter historical basis changed after case opening'
                    USING ERRCODE='55000';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.broken_meter_estimates AS existing
                WHERE existing.estimation_case_id=p_case_id
            ) THEN
                RAISE EXCEPTION 'Broken-Meter case is already finalized'
                    USING ERRCODE='23P01';
            END IF;
            IF p_authorized_at<v_case.opened_at OR p_authorized_at>clock_timestamp() THEN
                RAISE EXCEPTION 'Broken-Meter case cannot be finalized'
                    USING ERRCODE='55000';
            END IF;
            SELECT count(*) INTO v_history_count
            FROM app.utility_consumption_periods AS history
            WHERE history.unit_id=v_case.unit_id
              AND history.utility_type=v_case.utility_type
              AND history.calculation_kind='ACTUAL'
              AND history.end_date<v_case.unmeasured_start_date;
            IF v_history_count>=3 THEN
                v_basis_kind:='LATEST_THREE_HISTORICAL';
                FOR v_basis IN
                    SELECT history.id,app.utility_consumption_effective_quantity(history.id) quantity,
                           history.end_date-history.start_date+1 represented_days
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_case.unit_id
                      AND history.utility_type=v_case.utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_case.unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                    LIMIT 3
                LOOP
                    v_order:=v_order+1; v_total:=v_total+v_basis.quantity;
                    v_days:=v_days+v_basis.represented_days;
                    v_basis_ids:=array_append(v_basis_ids,v_basis.id);
                END LOOP;
            ELSIF v_history_count>0 THEN
                v_basis_kind:='ALL_AVAILABLE_HISTORICAL_ONE_OR_TWO';
                FOR v_basis IN
                    SELECT history.id,app.utility_consumption_effective_quantity(history.id) quantity,
                           history.end_date-history.start_date+1 represented_days
                    FROM app.utility_consumption_periods AS history
                    WHERE history.unit_id=v_case.unit_id
                      AND history.utility_type=v_case.utility_type
                      AND history.calculation_kind='ACTUAL'
                      AND history.end_date<v_case.unmeasured_start_date
                    ORDER BY history.end_date DESC,history.start_date DESC,history.id DESC
                LOOP
                    v_order:=v_order+1; v_total:=v_total+v_basis.quantity;
                    v_days:=v_days+v_basis.represented_days;
                    v_basis_ids:=array_append(v_basis_ids,v_basis.id);
                END LOOP;
            ELSE
                v_basis_kind:='FIRST_COMPLETE_FUTURE_ZERO_HISTORY';
                SELECT future.id AS id,
                       app.utility_consumption_effective_quantity(future.id) AS quantity,
                       future.end_date-future.start_date+1 AS represented_days
                INTO v_basis
                FROM app.utility_consumption_periods AS future
                WHERE future.unit_id=v_case.unit_id
                  AND future.utility_type=v_case.utility_type
                  AND future.calculation_kind='ACTUAL'
                  AND future.start_date>v_case.unmeasured_end_date
                ORDER BY future.start_date,future.end_date,future.id LIMIT 1;
                IF NOT FOUND THEN
                    v_result:=app.utility_case_snapshot(p_case_id);
                    INSERT INTO app.utility_service_commands(
                        property_id,actor_id,idempotency_key,action,request_digest,
                        request_evidence,result_snapshot,completed_at
                    ) VALUES (
                        p_property_id,p_actor_id,p_idempotency_key,
                        'FINALIZE_BROKEN_METER_ESTIMATE',p_request_digest,
                        v_evidence,v_result,clock_timestamp()
                    );
                    RETURN v_result;
                END IF;
                v_order:=1; v_total:=v_basis.quantity;
                v_days:=v_basis.represented_days;
                v_basis_ids:=ARRAY[v_basis.id];
            END IF;
            IF EXISTS (
                SELECT 1
                FROM app.utility_consumption_periods AS basis_period
                JOIN app.utility_readings AS start_reading
                  ON start_reading.id=basis_period.start_reading_id
                JOIN app.utility_meters AS basis_meter
                  ON basis_meter.id=start_reading.meter_id
                WHERE basis_period.id=ANY(v_basis_ids)
                  AND basis_meter.measurement_unit_code<>v_measurement_unit_code
            ) THEN
                RAISE EXCEPTION
                    'Broken-Meter selected basis uses a different measurement unit'
                    USING ERRCODE='23514';
            END IF;
            SELECT max(source.evidence_at) INTO STRICT v_latest_basis_evidence_at
            FROM (
                SELECT period.finalized_at AS evidence_at
                FROM app.utility_consumption_periods AS period
                WHERE period.id=ANY(v_basis_ids)
                UNION ALL
                SELECT correction.occurred_at
                FROM app.utility_reading_correction_impacts AS impact
                JOIN app.utility_reading_corrections AS correction
                  ON correction.id=impact.reading_correction_id
                WHERE impact.consumption_period_id=ANY(v_basis_ids)
            ) AS source;
            IF p_authorized_at<v_latest_basis_evidence_at THEN
                RAISE EXCEPTION 'Broken-Meter authorization predates selected basis evidence'
                    USING ERRCODE='23514';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=p_property_id;
            v_before:=app.utility_case_preview_snapshot(p_case_id);
            v_unmeasured_days:=v_case.unmeasured_end_date-v_case.unmeasured_start_date+1;
            v_average:=round(v_total::numeric(50,16)/v_days,10);
            v_estimated:=round(
                v_total::numeric(50,16)*v_unmeasured_days::numeric/v_days,
                6
            );
            INSERT INTO app.utility_consumption_periods(
                id,unit_id,utility_type,start_date,end_date,
                calculation_kind,consumption_quantity,calculation_trace,
                finalized_at,finalized_by
            ) VALUES (
                p_consumption_period_id,v_case.unit_id,v_case.utility_type,
                v_case.unmeasured_start_date,v_case.unmeasured_end_date,
                'BROKEN_METER_ESTIMATE',v_estimated,
                pg_catalog.jsonb_build_object(
                    'estimation_case_id',p_case_id,'basis_kind',v_basis_kind,
                    'basis_period_ids',to_jsonb(v_basis_ids),
                    'total_basis_consumption',v_total,'total_basis_days',v_days,
                    'unmeasured_days',v_unmeasured_days,'estimated_consumption',v_estimated
                ),
                p_authorized_at,p_actor_id
            );
            INSERT INTO app.broken_meter_estimates(
                id,estimation_case_id,consumption_period_id,basis_kind,
                historical_actual_period_count_at_selection,total_basis_consumption,
                total_basis_days,weighted_daily_average,estimated_consumption,
                authorization_reason,authorized_at,authorized_by,calculation_trace
            ) VALUES (
                p_estimate_id,p_case_id,p_consumption_period_id,v_basis_kind,
                v_history_count,v_total,v_days,v_average,v_estimated,
                p_authorization_reason,p_authorized_at,p_actor_id,
                pg_catalog.jsonb_build_object(
                    'basis_period_ids',to_jsonb(v_basis_ids),
                    'weighted_daily_average',v_average,
                    'unmeasured_days',v_unmeasured_days
                )
            );
            v_order:=0;
            FOREACH v_basis_id IN ARRAY v_basis_ids LOOP
                v_order:=v_order+1;
                INSERT INTO app.broken_meter_estimate_basis_periods(
                    broken_meter_estimate_id,basis_consumption_period_id,basis_order
                ) VALUES (p_estimate_id,v_basis_id,v_order);
            END LOOP;
            SET CONSTRAINTS ALL IMMEDIATE;
            v_result:=app.utility_service_snapshot(p_consumption_period_id);
            INSERT INTO app.audit_events(
                id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,
                resulting_state,correlation_id,source,outcome,
                authorization_evidence,unit_id
            ) VALUES (
                p_estimate_id,p_authorized_at,
                timezone(v_timezone,p_authorized_at)::date,p_actor_id,
                'utility.estimate.finalized','broken_meter_estimate',p_estimate_id,
                p_authorization_reason,p_authorization_reference,p_property_id,
                v_before,v_result,p_idempotency_key,'API','SUCCEEDED',
                pg_catalog.jsonb_build_object(
                    'estimation_case_id',p_case_id,
                    'consumption_period_id',p_consumption_period_id,
                    'basis_kind',v_basis_kind,'basis_period_ids',to_jsonb(v_basis_ids),
                    'total_basis_consumption',v_total,'total_basis_days',v_days,
                    'weighted_daily_average',v_average
                ),
                v_case.unit_id
            );
            INSERT INTO app.utility_service_commands(
                property_id,actor_id,idempotency_key,action,request_digest,
                request_evidence,result_snapshot,completed_at
            ) VALUES (
                p_property_id,p_actor_id,p_idempotency_key,
                'FINALIZE_BROKEN_METER_ESTIMATE',p_request_digest,
                v_evidence,v_result,clock_timestamp()
            );
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.preview_utility_calculation(
            p_property_id uuid,p_source_kind text,p_source_id uuid,
            p_generation_at timestamptz,p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_period app.utility_consumption_periods%ROWTYPE;
            v_rate app.utility_rates%ROWTYPE;
            v_timezone text; v_generation_date date;
            v_quantity numeric(38,6); v_result jsonb;
            v_unit_id uuid; v_utility_type text; v_case_id uuid;
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation')<>'read committed'
                OR p_property_id IS NULL
                OR p_source_kind NOT IN ('CONSUMPTION_PERIOD','ESTIMATION_CASE')
                OR p_source_id IS NULL
                OR p_generation_at IS NULL OR p_actor_id IS NULL
            THEN
                RAISE EXCEPTION 'Utility preview evidence is invalid'
                    USING ERRCODE='22023';
            END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            IF p_source_kind='CONSUMPTION_PERIOD' THEN
                SELECT period.* INTO v_period
                FROM app.utility_consumption_periods AS period
                JOIN app.units AS unit ON unit.id=period.unit_id
                WHERE period.id=p_source_id AND unit.property_id=p_property_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Utility calculation source was not found in Property scope'
                        USING ERRCODE='P0002';
                END IF;
                v_unit_id:=v_period.unit_id;
                v_utility_type:=v_period.utility_type;
            ELSE
                SELECT case_record.id,case_record.unit_id,case_record.utility_type
                INTO v_case_id,v_unit_id,v_utility_type
                FROM app.broken_meter_estimation_cases AS case_record
                JOIN app.units AS unit ON unit.id=case_record.unit_id
                WHERE case_record.id=p_source_id AND unit.property_id=p_property_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Utility calculation source was not found in Property scope'
                        USING ERRCODE='P0002';
                END IF;
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=p_property_id;
            PERFORM app.lock_utility_property_type(p_property_id,v_utility_type);
            PERFORM app.lock_utility_unit_type(v_unit_id,v_utility_type);
            IF v_case_id IS NULL THEN
                v_result:=app.utility_service_snapshot(v_period.id);
            ELSE
                v_result:=app.utility_case_preview_snapshot(v_case_id);
            END IF;
            IF v_result->>'status'='PENDING_FUTURE_ACTUAL_BASIS' THEN
                RETURN v_result;
            END IF;
            v_generation_date:=timezone(v_timezone,p_generation_at)::date;
            SELECT rate.* INTO v_rate FROM app.utility_rates AS rate
            WHERE rate.property_id=p_property_id
              AND rate.utility_type=v_utility_type
              AND rate.effective_date<=v_generation_date
            ORDER BY rate.effective_date DESC,rate.id DESC LIMIT 1;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Generation-date Utility Rate was not found'
                    USING ERRCODE='P0002';
            END IF;
            v_quantity:=(v_result->>'consumption_quantity')::numeric;
            v_result:=v_result || pg_catalog.jsonb_build_object(
                    'rate_id',v_rate.id,
                    'rate_effective_date',v_rate.effective_date,
                    'rate_usd_per_unit',v_rate.rate_usd_per_unit,
                    'amount_usd_cents',round(v_quantity*v_rate.rate_usd_per_unit*100,0),
                    'generation_date',v_generation_date
                );
            RETURN v_result;
        END $$;

        CREATE TRIGGER utility_consumption_periods_append_only
            BEFORE UPDATE OR DELETE ON app.utility_consumption_periods
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimation_cases_append_only
            BEFORE UPDATE OR DELETE ON app.broken_meter_estimation_cases
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimates_append_only
            BEFORE UPDATE OR DELETE ON app.broken_meter_estimates
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimate_basis_append_only
            BEFORE UPDATE OR DELETE ON app.broken_meter_estimate_basis_periods
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_reading_correction_impacts_append_only
            BEFORE UPDATE OR DELETE ON app.utility_reading_correction_impacts
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_service_commands_append_only
            BEFORE UPDATE OR DELETE ON app.utility_service_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_utility_history_mutation();

        CREATE TRIGGER utility_consumption_periods_reject_truncate
            BEFORE TRUNCATE ON app.utility_consumption_periods FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimation_cases_reject_truncate
            BEFORE TRUNCATE ON app.broken_meter_estimation_cases FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimates_reject_truncate
            BEFORE TRUNCATE ON app.broken_meter_estimates FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER broken_meter_estimate_basis_reject_truncate
            BEFORE TRUNCATE ON app.broken_meter_estimate_basis_periods FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_reading_correction_impacts_reject_truncate
            BEFORE TRUNCATE ON app.utility_reading_correction_impacts FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        CREATE TRIGGER utility_service_commands_reject_truncate
            BEFORE TRUNCATE ON app.utility_service_commands FOR EACH STATEMENT
            EXECUTE FUNCTION app.reject_utility_history_mutation();
        """
    )
    for table in (
        "utility_consumption_periods",
        "broken_meter_estimation_cases",
        "broken_meter_estimates",
        "broken_meter_estimate_basis_periods",
        "utility_reading_correction_impacts",
        "utility_service_commands",
    ):
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")
    for function in (
        "app.lock_utility_consumption_source()",
        "app.guard_utility_meter_estimation_unit()",
        "app.guard_utility_period_correction_chronology()",
        "app.utility_responsibility_window_is_stable(uuid,date,date)",
        "app.guard_utility_responsibility_change()",
        "app.guard_broken_meter_responsibility_window()",
        "app.assert_broken_meter_case()",
        "app.utility_consumption_effective_quantity(uuid)",
        "app.utility_estimate_effective_basis(uuid)",
        "app.utility_service_snapshot(uuid)",
        "app.utility_case_snapshot(uuid)",
        "app.utility_case_preview_snapshot(uuid)",
        "app.guard_utility_consumption_period()",
        "app.assert_utility_consumption_period()",
        "app.assert_broken_meter_estimate()",
        "app.capture_utility_reading_correction_impacts()",
        "app.utility_command_replay(uuid,uuid,uuid,text,text,jsonb)",
        "app.finalize_actual_utility_consumption(uuid,uuid,text,uuid,uuid,text,uuid,uuid,timestamp with time zone,uuid)",
        "app.open_broken_meter_estimation_case(uuid,uuid,text,uuid,uuid,uuid,text,timestamp with time zone,uuid,text)",
        "app.finalize_broken_meter_estimate(uuid,uuid,text,uuid,uuid,uuid,text,timestamp with time zone,uuid,text)",
        "app.preview_utility_calculation(uuid,text,uuid,timestamp with time zone,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.finalize_actual_utility_consumption(uuid,uuid,text,uuid,uuid,text,uuid,uuid,"
        "timestamp with time zone,uuid) TO prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.open_broken_meter_estimation_case(uuid,uuid,text,uuid,uuid,uuid,text,"
        "timestamp with time zone,uuid,text) TO prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.finalize_broken_meter_estimate(uuid,uuid,text,uuid,uuid,uuid,text,"
        "timestamp with time zone,uuid,text) TO prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.preview_utility_calculation(uuid,text,uuid,timestamp with time zone,uuid) "
        "TO prm_runtime, prm_financial"
    )


def downgrade() -> None:
    """Refuse destructive rollback of permanent Utility calculation history."""
    raise RuntimeError("V1-042 Utility calculation persistence is forward-only")
