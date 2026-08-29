"""Apply forward-only corrections to the published V1-042 Utility schema."""

from alembic import op

revision = "20260829_33"
down_revision = "20260828_32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Converge databases already stamped at the published V1-042 revision."""
    op.execute(
        r"""
        -- Drain and block the two revision-32 entry points that this migration
        -- replaces.  Without these object locks, a call can enter the old
        -- function, wait behind the table gate below, and then deadlock when
        -- this transaction later replaces or drops that same function.
        ALTER FUNCTION app.open_broken_meter_estimation_case(
            uuid,uuid,text,uuid,uuid,uuid,text,timestamp with time zone,uuid,text
        ) SET search_path=pg_catalog;
        ALTER FUNCTION app.preview_utility_calculation(
            uuid,text,uuid,timestamp with time zone,uuid
        ) SET search_path=pg_catalog;

        -- Take supported write-entry gates before any source scan.  The command
        -- table drains revision-32 service calls; the three direct persistence
        -- targets drain Reading corrections, Readings, and Rates.  ACCESS
        -- EXCLUSIVE is intentional: taking the final DDL lock mode up front
        -- avoids a later lock upgrade while a newly admitted writer holds a
        -- source-table read lock and waits for a destination-table write lock.
        LOCK TABLE app.utility_service_commands,
                   app.utility_reading_corrections,
                   app.utility_readings,
                   app.utility_rates,
                   app.utility_reading_correction_impacts,
                   app.utility_consumption_periods,
                   app.broken_meter_estimation_cases,
                   app.broken_meter_estimates,
                   app.broken_meter_estimate_basis_periods
            IN ACCESS EXCLUSIVE MODE;

        DO $validation$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.utility_readings
                WHERE NOT (reading_value<'Infinity'::numeric)
            ) OR EXISTS (
                SELECT 1 FROM app.utility_reading_corrections
                WHERE NOT (
                    previous_value<'Infinity'::numeric
                    AND corrected_value<'Infinity'::numeric
                )
            ) OR EXISTS (
                SELECT 1 FROM app.utility_rates
                WHERE NOT (rate_usd_per_unit<'Infinity'::numeric)
            ) OR EXISTS (
                SELECT 1 FROM app.utility_consumption_periods
                WHERE NOT (
                    consumption_quantity BETWEEN 0 AND 99999999999999.999999
                )
            ) OR EXISTS (
                SELECT 1 FROM app.broken_meter_estimates
                WHERE NOT (
                    total_basis_consumption BETWEEN 0 AND 99999999999999.999999
                    AND weighted_daily_average BETWEEN 0 AND 9999999999.9999999999
                    AND estimated_consumption BETWEEN 0 AND 99999999999999.999999
                )
            ) OR EXISTS (
                SELECT 1 FROM app.utility_reading_correction_impacts
                WHERE NOT (
                    previous_consumption_quantity BETWEEN 0 AND 99999999999999.999999
                    AND corrected_consumption_quantity BETWEEN 0 AND 99999999999999.999999
                )
            ) OR EXISTS (
                SELECT 1
                FROM (
                    SELECT estimate.id,
                           sum(app.utility_consumption_effective_quantity(
                               basis_period.id
                           )) AS total_basis_consumption,
                           sum(
                               basis_period.end_date-basis_period.start_date+1
                           )::integer AS total_basis_days,
                           case_record.unmeasured_end_date
                               -case_record.unmeasured_start_date+1 AS unmeasured_days
                    FROM app.broken_meter_estimates AS estimate
                    JOIN app.broken_meter_estimation_cases AS case_record
                      ON case_record.id=estimate.estimation_case_id
                    JOIN app.broken_meter_estimate_basis_periods AS basis
                      ON basis.broken_meter_estimate_id=estimate.id
                    JOIN app.utility_consumption_periods AS basis_period
                      ON basis_period.id=basis.basis_consumption_period_id
                    GROUP BY estimate.id,case_record.unmeasured_start_date,
                             case_record.unmeasured_end_date
                ) AS effective_basis
                WHERE effective_basis.total_basis_consumption IS NULL
                   OR effective_basis.total_basis_days<=0
                   OR effective_basis.unmeasured_days<=0
                   OR NOT (
                        effective_basis.total_basis_consumption
                            BETWEEN 0 AND 99999999999999.999999
                        AND round(
                            effective_basis.total_basis_consumption::numeric(50,16)
                                /effective_basis.total_basis_days,
                            10
                        ) BETWEEN 0 AND 9999999999.9999999999
                        AND round(
                            effective_basis.total_basis_consumption::numeric(50,16)
                                *effective_basis.unmeasured_days
                                /effective_basis.total_basis_days,
                            6
                        ) BETWEEN 0 AND 99999999999999.999999
                   )
            ) THEN
                RAISE EXCEPTION
                    'Published V1-042 effective basis exceeds corrected canonical precision'
                    USING ERRCODE='22003';
            END IF;
        END $validation$;

        ALTER TABLE app.utility_readings
            ADD CONSTRAINT utility_readings_reading_value_finite
            CHECK (reading_value<'Infinity'::numeric);
        ALTER TABLE app.utility_reading_corrections
            ADD CONSTRAINT utility_reading_corrections_values_finite
            CHECK (
                previous_value<'Infinity'::numeric
                AND corrected_value<'Infinity'::numeric
            );
        ALTER TABLE app.utility_rates
            ADD CONSTRAINT utility_rates_rate_finite
            CHECK (rate_usd_per_unit<'Infinity'::numeric);

        ALTER TABLE app.utility_consumption_periods
            ALTER COLUMN consumption_quantity TYPE numeric(20,6)
            USING consumption_quantity::numeric(20,6);
        ALTER TABLE app.utility_consumption_periods
            ADD CONSTRAINT utility_consumption_periods_quantity_finite
            CHECK (consumption_quantity<'Infinity'::numeric);

        ALTER TABLE app.broken_meter_estimates
            ALTER COLUMN total_basis_consumption TYPE numeric(20,6)
            USING total_basis_consumption::numeric(20,6),
            ALTER COLUMN weighted_daily_average TYPE numeric(20,10)
            USING weighted_daily_average::numeric(20,10),
            ALTER COLUMN estimated_consumption TYPE numeric(20,6)
            USING estimated_consumption::numeric(20,6);
        ALTER TABLE app.broken_meter_estimates
            ADD CONSTRAINT broken_meter_estimates_values_finite
            CHECK (
                total_basis_consumption<'Infinity'::numeric
                AND weighted_daily_average<'Infinity'::numeric
                AND estimated_consumption<'Infinity'::numeric
            );

        ALTER TABLE app.utility_reading_correction_impacts
            ALTER COLUMN previous_consumption_quantity TYPE numeric(20,6)
            USING previous_consumption_quantity::numeric(20,6),
            ALTER COLUMN corrected_consumption_quantity TYPE numeric(20,6)
            USING corrected_consumption_quantity::numeric(20,6);
        ALTER TABLE app.utility_reading_correction_impacts
            ADD CONSTRAINT utility_reading_correction_impacts_values_finite
            CHECK (
                previous_consumption_quantity<'Infinity'::numeric
                AND corrected_consumption_quantity<'Infinity'::numeric
            );

        ALTER TABLE app.broken_meter_estimation_cases
            DROP CONSTRAINT broken_meter_estimation_cases_failed_meter_id_key,
            DROP CONSTRAINT broken_meter_estimation_cases_replacement_meter_id_key;
        ALTER TABLE app.broken_meter_estimation_cases
            ADD CONSTRAINT broken_meter_case_segment_unique UNIQUE (
                failed_meter_id,replacement_meter_id,
                unmeasured_start_date,unmeasured_end_date
            );
        ALTER TABLE app.broken_meter_estimation_cases
            ADD CONSTRAINT broken_meter_case_segment_no_overlap EXCLUDE USING gist (
                failed_meter_id WITH =,
                replacement_meter_id WITH =,
                daterange(unmeasured_start_date,unmeasured_end_date,'[]') WITH &&
            );
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION app.utility_consumption_effective_quantity(p_period_id uuid)
        RETURNS numeric(20,6) LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
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

        CREATE OR REPLACE FUNCTION app.utility_estimate_effective_basis(p_estimate_id uuid)
        RETURNS TABLE(
            total_basis_consumption numeric(20,6),
            total_basis_days integer,
            weighted_daily_average numeric(20,10)
        ) LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT operands.total_basis_consumption,
                   operands.total_basis_days,
                   round(
                       operands.total_basis_consumption::numeric(50,16)
                       / operands.total_basis_days,
                       10
                   )::numeric(20,10)
            FROM (
                SELECT sum(
                           app.utility_consumption_effective_quantity(period.id)
                       )::numeric(20,6) AS total_basis_consumption,
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

        CREATE OR REPLACE FUNCTION app.utility_case_preview_snapshot(p_case_id uuid)
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
            IF v_total>99999999999999.999999
                OR v_average>9999999999.9999999999
                OR v_estimated>99999999999999.999999
            THEN
                RAISE EXCEPTION
                    'Broken-Meter calculation exceeds canonical persistence precision'
                    USING ERRCODE='22003';
            END IF;
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

        CREATE OR REPLACE FUNCTION app.assert_broken_meter_case()
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
            v_window_stable boolean; v_start_aligned boolean; v_end_aligned boolean;
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
              AND period.end_date<NEW.unmeasured_start_date;
            SELECT
                NOT COALESCE(bool_or(
                    boundary.boundary_date>NEW.unmeasured_start_date
                    AND boundary.boundary_date<=NEW.unmeasured_end_date
                ),false),
                NEW.unmeasured_start_date=v_expected_start_date OR COALESCE(
                    bool_or(boundary.boundary_date=NEW.unmeasured_start_date),false
                ),
                NEW.unmeasured_end_date=v_expected_end_date OR COALESCE(
                    bool_or(boundary.boundary_date=NEW.unmeasured_end_date+1),false
                )
            INTO v_window_stable,v_start_aligned,v_end_aligned
            FROM (
                SELECT lease.start_date AS boundary_date
                FROM app.leases AS lease
                WHERE lease.unit_id=NEW.unit_id
                  AND lease.status IN ('SIGNED','TERMINATED')
                UNION ALL
                SELECT COALESCE(lease.actual_termination_date,lease.end_date)+1
                FROM app.leases AS lease
                WHERE lease.unit_id=NEW.unit_id
                  AND lease.status IN ('SIGNED','TERMINATED')
                UNION ALL
                SELECT occupancy.move_in_date
                FROM app.occupancies AS occupancy
                JOIN app.leases AS lease ON lease.id=occupancy.lease_id
                JOIN app.lease_signers AS signer
                  ON signer.lease_id=occupancy.lease_id
                 AND signer.customer_id=occupancy.customer_id
                 AND signer.signed_at IS NOT NULL
                WHERE lease.unit_id=NEW.unit_id
                UNION ALL
                SELECT occupancy.move_out_date+1
                FROM app.occupancies AS occupancy
                JOIN app.leases AS lease ON lease.id=occupancy.lease_id
                JOIN app.lease_signers AS signer
                  ON signer.lease_id=occupancy.lease_id
                 AND signer.customer_id=occupancy.customer_id
                 AND signer.signed_at IS NOT NULL
                WHERE lease.unit_id=NEW.unit_id
                  AND occupancy.move_out_date IS NOT NULL
            ) AS boundary;
            IF NEW.unmeasured_start_date<v_expected_start_date
                OR NEW.unmeasured_end_date>v_expected_end_date
                OR NOT v_window_stable
                OR NOT v_start_aligned
                OR NOT v_end_aligned
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

        CREATE OR REPLACE FUNCTION app.capture_utility_reading_correction_impacts()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_period app.utility_consumption_periods%ROWTYPE;
        DECLARE v_estimate record;
        DECLARE v_previous numeric(38,6); v_corrected numeric(38,6);
        DECLARE v_average numeric(38,10);
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
                v_average:=round(
                    v_estimate.total_basis_consumption::numeric(50,16)
                        /v_estimate.total_basis_days,
                    10
                );
                IF v_estimate.total_basis_consumption>99999999999999.999999
                    OR v_average>9999999999.9999999999
                    OR v_corrected>99999999999999.999999
                THEN
                    RAISE EXCEPTION
                        'Reading correction makes Broken-Meter calculation exceed canonical persistence precision'
                        USING ERRCODE='22003';
                END IF;
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

        CREATE FUNCTION app.open_broken_meter_estimation_case(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_case_id uuid,p_failed_meter_id uuid,p_replacement_meter_id uuid,
            p_unmeasured_start_date date,p_unmeasured_end_date date,
            p_opened_reason text,p_opened_at timestamptz,p_actor_id uuid,
            p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_evidence jsonb; v_replay jsonb; v_result jsonb;
            v_unit_id uuid; v_utility_type text;
            v_measurement_unit_code text;
            v_replacement_measurement_unit_code text;
            v_failure_date date; v_replacement_date date; v_replacement_at timestamptz;
            v_derived_start_date date; v_derived_end_date date;
            v_unmeasured_start_date date; v_unmeasured_end_date date;
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
                OR (p_unmeasured_start_date IS NULL)<>
                    (p_unmeasured_end_date IS NULL)
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
            ) || CASE WHEN p_unmeasured_start_date IS NULL THEN '{}'::jsonb ELSE
                pg_catalog.jsonb_build_object(
                    'unmeasured_start_date',p_unmeasured_start_date,
                    'unmeasured_end_date',p_unmeasured_end_date
                )
            END;
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
            v_derived_start_date:=v_failure_date;
            SELECT reading.validated_at INTO v_failure_reading_validated_at
            FROM app.utility_readings AS reading
            WHERE reading.meter_id=p_failed_meter_id
              AND reading.validated_at IS NOT NULL
              AND reading.reading_date=v_failure_date;
            IF FOUND THEN
                v_derived_start_date:=v_failure_date+1;
            END IF;
            IF v_failure_reading_validated_at IS NOT NULL
                AND p_opened_at<v_failure_reading_validated_at
            THEN
                RAISE EXCEPTION 'Broken-Meter case opening predates boundary evidence'
                    USING ERRCODE='23514';
            END IF;
            v_derived_end_date:=v_first_replacement_reading_date-1;
            IF v_derived_start_date>v_derived_end_date THEN
                RAISE EXCEPTION 'Confirmed broken-Meter boundary has no unmeasured period'
                    USING ERRCODE='23514';
            END IF;
            v_unmeasured_start_date:=COALESCE(
                p_unmeasured_start_date,v_derived_start_date
            );
            v_unmeasured_end_date:=COALESCE(
                p_unmeasured_end_date,v_derived_end_date
            );
            IF v_unmeasured_start_date<v_derived_start_date
                OR v_unmeasured_end_date>v_derived_end_date
                OR v_unmeasured_end_date<v_unmeasured_start_date
                OR NOT app.utility_responsibility_window_is_stable(
                    v_unit_id,v_unmeasured_start_date,v_unmeasured_end_date
                )
                OR (
                    v_unmeasured_start_date<>v_derived_start_date
                    AND app.utility_responsibility_window_is_stable(
                        v_unit_id,
                        v_unmeasured_start_date-1,
                        v_unmeasured_start_date
                    )
                )
                OR (
                    v_unmeasured_end_date<>v_derived_end_date
                    AND app.utility_responsibility_window_is_stable(
                        v_unit_id,
                        v_unmeasured_end_date,
                        v_unmeasured_end_date+1
                    )
                )
            THEN
                RAISE EXCEPTION
                    'Broken-Meter segment requires exact Customer responsibility boundaries'
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
                v_unmeasured_start_date,v_unmeasured_end_date,
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

        CREATE OR REPLACE FUNCTION app.preview_utility_calculation(
            p_property_id uuid,p_source_kind text,p_source_id uuid,
            p_generation_at timestamptz,p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_period app.utility_consumption_periods%ROWTYPE;
            v_rate app.utility_rates%ROWTYPE;
            v_timezone text; v_generation_date date;
            v_quantity numeric(38,6); v_amount_usd_cents numeric; v_result jsonb;
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
            IF v_quantity<0 OR v_quantity>99999999999999.999999 THEN
                RAISE EXCEPTION
                    'Utility consumption exceeds the supported billing-source range'
                    USING ERRCODE='22003';
            END IF;
            v_amount_usd_cents:=round(v_quantity*v_rate.rate_usd_per_unit*100,0);
            IF v_amount_usd_cents>9223372036854775807 THEN
                RAISE EXCEPTION 'Utility charge exceeds the supported whole-cent range'
                    USING ERRCODE='22003';
            END IF;
            v_result:=v_result || pg_catalog.jsonb_build_object(
                    'rate_id',v_rate.id,
                    'rate_effective_date',v_rate.effective_date,
                    'rate_usd_per_unit',v_rate.rate_usd_per_unit,
                    'amount_usd_cents',v_amount_usd_cents::bigint,
                    'generation_date',v_generation_date
                );
            RETURN v_result;
        END $$;
        """
    )
    op.execute(
        r"""
        DROP TRIGGER broken_meter_estimation_cases_validate
            ON app.broken_meter_estimation_cases;
        CREATE CONSTRAINT TRIGGER broken_meter_estimation_cases_validate
            AFTER INSERT ON app.broken_meter_estimation_cases
            FOR EACH ROW EXECUTE FUNCTION app.assert_broken_meter_case();

        REVOKE ALL ON FUNCTION
            app.open_broken_meter_estimation_case(
                uuid,uuid,text,uuid,uuid,uuid,date,date,text,
                timestamp with time zone,uuid,text
            ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            app.open_broken_meter_estimation_case(
                uuid,uuid,text,uuid,uuid,uuid,date,date,text,
                timestamp with time zone,uuid,text
            ) TO prm_financial;
        REVOKE ALL ON FUNCTION
            app.open_broken_meter_estimation_case(
                uuid,uuid,text,uuid,uuid,uuid,text,
                timestamp with time zone,uuid,text
            ) FROM PUBLIC,prm_financial;
        DROP FUNCTION app.open_broken_meter_estimation_case(
            uuid,uuid,text,uuid,uuid,uuid,text,
            timestamp with time zone,uuid,text
        );
        """
    )


def downgrade() -> None:
    """Keep published Utility financial history forward-only."""
    raise RuntimeError("V1-042 Utility corrections are forward-only")
