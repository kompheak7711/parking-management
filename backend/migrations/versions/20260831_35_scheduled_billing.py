# ruff: noqa: E501
"""Activate idempotent scheduled Rent, Service, and Utility billing runs."""

from alembic import op

revision = "20260831_35"
down_revision = "20260829_34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the V1-044 command ledger and atomic issuance boundary."""
    op.execute(
        r"""
        DROP TRIGGER billing_runs_protect_history ON app.billing_runs;
        DROP TRIGGER billing_run_eligible_sources_protect_history
            ON app.billing_run_eligible_sources;

        ALTER TABLE app.billing_runs
            ADD COLUMN request_digest text DEFAULT repeat('0',64),
            ADD COLUMN correlation_id uuid DEFAULT gen_random_uuid(),
            ADD COLUMN invocation_source text DEFAULT 'SCHEDULED',
            ADD COLUMN requester_actor_id uuid;
        UPDATE app.billing_runs SET
            request_digest=md5(id::text)||md5(id::text),
            correlation_id=id,
            invocation_source='SCHEDULED',
            requester_actor_id=system_actor_id;
        ALTER TABLE app.billing_runs
            ALTER COLUMN request_digest SET NOT NULL,
            ALTER COLUMN correlation_id SET NOT NULL,
            ALTER COLUMN invocation_source SET NOT NULL,
            ALTER COLUMN requester_actor_id SET NOT NULL,
            ADD CONSTRAINT billing_runs_request_digest_shape
                CHECK (request_digest~'^[0-9a-f]{64}$'),
            ADD CONSTRAINT billing_runs_correlation_non_nil
                CHECK (correlation_id<>'00000000-0000-0000-0000-000000000000'::uuid),
            ADD CONSTRAINT billing_runs_invocation_source_allowed
                CHECK (invocation_source IN ('API','SCHEDULED')),
            ADD CONSTRAINT billing_runs_logical_key_bounded
                CHECK (length(logical_run_key)<=200),
            ADD CONSTRAINT billing_runs_requester_actor_fkey
                FOREIGN KEY(requester_actor_id)
                REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT;

        ALTER TABLE app.billing_runs
            DROP CONSTRAINT billing_runs_utility_source_deferred;
        ALTER TABLE app.invoice_lines
            DROP CONSTRAINT invoice_lines_utility_source_deferred;

        ALTER TABLE app.billing_run_eligible_sources
            DROP CONSTRAINT billing_run_eligible_sources_source_id_fkey,
            DROP CONSTRAINT billing_run_eligible_sources_source_kind_check,
            ADD COLUMN source_evidence jsonb;
        UPDATE app.billing_run_eligible_sources SET source_evidence='{}'::jsonb;
        ALTER TABLE app.billing_run_eligible_sources
            ALTER COLUMN source_evidence SET NOT NULL,
            ADD CONSTRAINT billing_run_eligible_sources_source_kind_check
                CHECK (source_kind IN ('LEASE_PERIOD','UTILITY_PERIOD','UTILITY_CASE')),
            ADD CONSTRAINT billing_run_eligible_sources_evidence_shape
                CHECK (jsonb_typeof(source_evidence)='object');
        CREATE TRIGGER billing_run_eligible_sources_protect_history
            BEFORE INSERT OR UPDATE OR DELETE ON app.billing_run_eligible_sources
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_eligible_source_history();

        ALTER TABLE app.billing_run_items
            DROP CONSTRAINT billing_run_items_source_kind_check,
            DROP CONSTRAINT billing_run_items_outcome_shape,
            ADD CONSTRAINT billing_run_items_source_kind_check
                CHECK (source_kind IN ('LEASE_PERIOD','UTILITY_PERIOD','UTILITY_CASE')),
            ADD CONSTRAINT billing_run_items_outcome_shape CHECK (
                (outcome='GENERATED' AND invoice_id IS NOT NULL AND diagnostic_code IS NULL)
                OR (outcome='SKIPPED' AND (
                    (invoice_id IS NOT NULL
                        AND diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS')
                    OR (invoice_id IS NULL AND diagnostic_code IN (
                        'SOURCE_NO_LONGER_ELIGIBLE',
                        'PENDING_FUTURE_ACTUAL_BASIS',
                        'ZERO_AMOUNT_NO_OBLIGATION'
                    ))
                ))
                OR (outcome IN ('CONFLICT','ERROR') AND invoice_id IS NULL
                    AND diagnostic_code IS NOT NULL
                    AND length(btrim(diagnostic_code))>0
                    AND length(diagnostic_code)<=100
                    AND diagnostic_code=btrim(diagnostic_code))
            );

        CREATE UNIQUE INDEX billing_runs_correlation_unique
            ON app.billing_runs(correlation_id);
        CREATE INDEX billing_run_eligible_sources_order_idx
            ON app.billing_run_eligible_sources(
                billing_run_id,source_period_start,source_period_end,source_kind,source_id
            );
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION app.snapshot_billing_run_eligible_sources()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_cutoff timestamptz;
        BEGIN
            IF NEW.predecessor_run_id IS NOT NULL THEN
                INSERT INTO app.billing_run_eligible_sources(
                    billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                    snapshotted_at,source_evidence
                )
                SELECT NEW.id,source_kind,source_id,source_period_start,source_period_end,
                    statement_timestamp(),source_evidence
                FROM app.billing_run_eligible_sources
                WHERE billing_run_id=NEW.predecessor_run_id;
                RETURN NEW;
            END IF;
            v_cutoff:=statement_timestamp();
            INSERT INTO app.billing_run_eligible_sources(
                billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                snapshotted_at,source_evidence
            )
            SELECT NEW.id,'LEASE_PERIOD',lease.id,NEW.period_start,NEW.period_end,
                statement_timestamp(),pg_catalog.jsonb_build_object(
                    'lease_id',lease.id,'signed_at',lease.signed_at,
                    'monthly_rent_usd_cents',lease.monthly_rent_usd_cents,
                    'source_cutoff',v_cutoff
                )
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE NEW.run_kind='RENT' AND unit.property_id=NEW.property_id
              AND lease.signed_at IS NOT NULL
              AND app.lease_is_billable_for_recurring_period(
                  lease.id,NEW.period_start,NEW.period_end,v_cutoff
              )
            ORDER BY lease.id;

            INSERT INTO app.billing_run_eligible_sources(
                billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                snapshotted_at,source_evidence
            )
            SELECT NEW.id,'UTILITY_PERIOD',period.id,period.start_date,period.end_date,
                statement_timestamp(),pg_catalog.jsonb_build_object(
                    'unit_id',period.unit_id,'utility_type',period.utility_type,
                    'calculation_kind',period.calculation_kind,
                    'consumption_quantity',app.utility_consumption_effective_quantity(period.id),
                    'finalized_at',period.finalized_at,'finalized_by',period.finalized_by,
                    'calculation_trace',period.calculation_trace
                )
            FROM app.utility_consumption_periods AS period
            JOIN app.units AS unit ON unit.id=period.unit_id
            WHERE NEW.run_kind='UTILITIES' AND unit.property_id=NEW.property_id
              AND period.start_date=NEW.period_start AND period.end_date=NEW.period_end
              AND period.finalized_at<=statement_timestamp()
            ORDER BY period.id;

            INSERT INTO app.billing_run_eligible_sources(
                billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                snapshotted_at,source_evidence
            )
            SELECT NEW.id,'UTILITY_CASE',case_record.id,
                case_record.unmeasured_start_date,case_record.unmeasured_end_date,
                statement_timestamp(),app.utility_case_snapshot(case_record.id)
            FROM app.broken_meter_estimation_cases AS case_record
            JOIN app.units AS unit ON unit.id=case_record.unit_id
            WHERE NEW.run_kind='UTILITIES' AND unit.property_id=NEW.property_id
              AND case_record.unmeasured_start_date=NEW.period_start
              AND case_record.unmeasured_end_date=NEW.period_end
              AND NOT EXISTS (
                  SELECT 1 FROM app.broken_meter_estimates AS estimate
                  WHERE estimate.estimation_case_id=case_record.id
              )
            ORDER BY case_record.id;
            RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION app.protect_billing_run_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_latest_attempt_id uuid; v_latest_attempt_number integer; v_latest_outcome text;
        DECLARE v_latest_completed_at timestamptz; v_latest_diagnostic text;
        DECLARE v_latest_item_at timestamptz; v_timezone text;
        DECLARE v_predecessor app.billing_runs%ROWTYPE;
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.requester_actor_id IS NULL AND NEW.invocation_source='SCHEDULED' THEN
                    NEW.requester_actor_id:=NEW.system_actor_id;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM app.actor_identities AS identity
                    WHERE identity.actor_id=NEW.system_actor_id
                      AND identity.identity_kind='SERVICE'
                ) THEN RAISE EXCEPTION 'Billing Run requires a scoped service principal'
                    USING ERRCODE='55000'; END IF;
                PERFORM app.assert_active_financial_actor(NEW.system_actor_id,NEW.property_id);
                SELECT property.timezone_name INTO STRICT v_timezone
                FROM app.properties AS property WHERE property.id=NEW.property_id;
                IF NEW.status<>'RUNNING'
                    OR timezone(v_timezone,NEW.started_at)::date<NEW.business_date
                    OR NEW.request_digest!~'^[0-9a-f]{64}$'
                    OR NEW.invocation_source NOT IN ('API','SCHEDULED')
                THEN RAISE EXCEPTION 'Billing Run command evidence is invalid'
                    USING ERRCODE='23514'; END IF;
                IF NEW.run_kind='RENT' AND (
                    extract(day FROM NEW.business_date)<>25
                    OR NEW.period_start<>(date_trunc('month',NEW.business_date)::date
                        + interval '1 month')::date
                    OR NEW.period_end<>(date_trunc('month',NEW.business_date)::date
                        + interval '2 months - 1 day')::date
                ) THEN RAISE EXCEPTION 'Rent Billing Run schedule and period are invalid'
                    USING ERRCODE='23514'; END IF;
                IF NEW.run_kind='UTILITIES' AND (
                    NEW.period_end>NEW.business_date
                    OR NEW.period_end-NEW.period_start>62
                ) THEN RAISE EXCEPTION 'Utility Billing Run period is invalid'
                    USING ERRCODE='23514'; END IF;
                IF NEW.predecessor_run_id IS NOT NULL THEN
                    SELECT * INTO v_predecessor FROM app.billing_runs
                    WHERE id=NEW.predecessor_run_id FOR UPDATE;
                    IF v_predecessor.id IS NULL OR v_predecessor.status<>'FAILED'
                        OR NEW.property_id<>v_predecessor.property_id
                        OR NEW.run_kind<>v_predecessor.run_kind
                        OR NEW.business_date<>v_predecessor.business_date
                        OR NEW.period_start<>v_predecessor.period_start
                        OR NEW.period_end<>v_predecessor.period_end
                        OR NEW.started_at<v_predecessor.completed_at
                    THEN RAISE EXCEPTION 'Billing Run successor must continue one failed run'
                        USING ERRCODE='23514'; END IF;
                END IF;
                PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                    'billing-run:' || NEW.property_id::text || '/' || NEW.run_kind || '/'
                        || NEW.period_start::text || '/' || NEW.period_end::text,0
                ));
                PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                    'billing-run-eligibility:' || NEW.property_id::text,0
                ));
                PERFORM app.advance_invoice_serialization_guard(
                    'billing-run-eligibility:' || NEW.property_id::text
                );
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' OR OLD.status<>'RUNNING' OR NEW.id<>OLD.id
                OR NEW.property_id<>OLD.property_id OR NEW.run_kind<>OLD.run_kind
                OR NEW.logical_run_key<>OLD.logical_run_key OR NEW.business_date<>OLD.business_date
                OR NEW.period_start IS DISTINCT FROM OLD.period_start
                OR NEW.period_end IS DISTINCT FROM OLD.period_end
                OR NEW.idempotency_key<>OLD.idempotency_key
                OR NEW.request_digest<>OLD.request_digest
                OR NEW.correlation_id<>OLD.correlation_id
                OR NEW.invocation_source<>OLD.invocation_source
                OR NEW.requester_actor_id<>OLD.requester_actor_id
                OR NEW.predecessor_run_id IS DISTINCT FROM OLD.predecessor_run_id
                OR NEW.system_actor_id<>OLD.system_actor_id OR NEW.started_at<>OLD.started_at
                OR NEW.created_at<>OLD.created_at OR NEW.status='RUNNING'
            THEN RAISE EXCEPTION 'Billing Run identity and terminal history are protected'
                USING ERRCODE='55000'; END IF;
            SELECT id,attempt_number,outcome,completed_at,diagnostic_code
                INTO v_latest_attempt_id,v_latest_attempt_number,v_latest_outcome,
                    v_latest_completed_at,v_latest_diagnostic
            FROM app.billing_run_attempts WHERE billing_run_id=OLD.id
            ORDER BY attempt_number DESC LIMIT 1;
            SELECT max(recorded_at) INTO v_latest_item_at
            FROM app.billing_run_items WHERE billing_run_id=OLD.id;
            IF EXISTS (
                SELECT 1 FROM app.billing_run_attempts
                WHERE billing_run_id=OLD.id AND outcome='RUNNING'
            ) OR v_latest_outcome IS DISTINCT FROM NEW.status
            THEN RAISE EXCEPTION 'Billing Run terminal status requires matching latest attempt evidence'
                USING ERRCODE='23514'; END IF;
            IF NEW.completed_at<v_latest_completed_at
                OR NEW.completed_at<COALESCE(v_latest_item_at,'-infinity'::timestamptz)
                OR (NEW.status='FAILED' AND NEW.failure_code<>v_latest_diagnostic)
            THEN RAISE EXCEPTION 'Billing Run terminal summary contradicts its latest attempt'
                USING ERRCODE='23514'; END IF;
            IF NEW.status='SUCCEEDED' AND (
                EXISTS (SELECT 1 FROM app.billing_run_items
                    WHERE billing_run_attempt_id=v_latest_attempt_id
                      AND outcome IN ('CONFLICT','ERROR'))
                OR app.billing_run_has_unresolved_sources(OLD.id,v_latest_attempt_number)
                OR app.billing_run_has_missing_eligible_sources(OLD.id,v_latest_attempt_number)
            ) THEN RAISE EXCEPTION 'Successful Billing Run cannot retain unresolved errors'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER billing_runs_protect_history
            BEFORE INSERT OR UPDATE OR DELETE ON app.billing_runs
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_history();
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION app.protect_invoice_header_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_attempt_status text; v_run_status text;
        DECLARE v_attempt_started_at timestamptz; v_run_kind text; v_run_property_id uuid;
        DECLARE v_run_system_actor_id uuid; v_adjusted_total bigint;
        DECLARE v_run_business_date date; v_run_period_start date; v_run_period_end date;
        DECLARE v_invoice_property_id uuid;
        BEGIN
            SELECT unit.property_id INTO v_invoice_property_id
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE lease.id=CASE WHEN TG_OP='DELETE' THEN OLD.lease_id ELSE NEW.lease_id END;
            IF TG_OP='INSERT' THEN
                PERFORM app.assert_active_financial_actor(NEW.created_by,v_invoice_property_id);
                PERFORM app.assert_active_financial_actor(NEW.updated_by,v_invoice_property_id);
                PERFORM app.advance_invoice_serialization_guard(
                    'invoice-financial:' || NEW.id::text
                );
                IF NEW.status<>'DRAFT' THEN RAISE EXCEPTION 'Invoice must begin in DRAFT status'
                    USING ERRCODE='23514'; END IF;
                IF NEW.originating_billing_run_attempt_id IS NULL AND EXISTS (
                    SELECT 1 FROM app.actor_identities AS identity
                    WHERE identity.identity_kind='SERVICE'
                      AND identity.actor_id IN (NEW.created_by,NEW.updated_by)
                ) THEN RAISE EXCEPTION
                    'Service-authored Invoice requires an active Billing Run attempt'
                    USING ERRCODE='55000'; END IF;
                IF NEW.originating_billing_run_attempt_id IS NOT NULL THEN
                    SELECT attempt.outcome,run.status,attempt.started_at,run.run_kind,
                        run.property_id,run.business_date,run.period_start,run.period_end,
                        run.system_actor_id
                    INTO v_attempt_status,v_run_status,v_attempt_started_at,v_run_kind,
                        v_run_property_id,v_run_business_date,v_run_period_start,v_run_period_end,
                        v_run_system_actor_id
                    FROM app.billing_run_attempts AS attempt
                    JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                    WHERE attempt.id=NEW.originating_billing_run_attempt_id
                    FOR UPDATE OF attempt,run;
                    IF v_attempt_status IS DISTINCT FROM 'RUNNING'
                        OR v_run_status IS DISTINCT FROM 'RUNNING'
                        OR NEW.created_at<v_attempt_started_at
                        OR NEW.created_by<>v_run_system_actor_id
                        OR NEW.updated_by<>v_run_system_actor_id
                        OR NEW.invoice_date<>v_run_business_date
                        OR NEW.billing_period_start IS DISTINCT FROM v_run_period_start
                        OR NEW.billing_period_end IS DISTINCT FROM v_run_period_end
                        OR NOT EXISTS (
                            SELECT 1 FROM app.billing_service_principals AS principal
                            WHERE principal.actor_id=v_run_system_actor_id
                              AND principal.property_id=v_run_property_id
                              AND principal.capability='billing.generate'
                              AND principal.lifecycle_state='active'
                        )
                        OR NOT (
                            (v_run_kind='RENT' AND NEW.primary_category='RENT'
                              AND EXISTS (
                                SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                                JOIN app.billing_run_attempts AS source_attempt
                                  ON source_attempt.billing_run_id=eligible.billing_run_id
                                WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                                  AND eligible.source_kind='LEASE_PERIOD'
                                  AND eligible.source_id=NEW.lease_id
                                  AND eligible.source_period_start=NEW.billing_period_start
                                  AND eligible.source_period_end=NEW.billing_period_end
                              ))
                            OR (v_run_kind='UTILITIES' AND NEW.primary_category='UTILITIES'
                              AND EXISTS (
                                SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                                JOIN app.billing_run_attempts AS source_attempt
                                  ON source_attempt.billing_run_id=eligible.billing_run_id
                                WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                                  AND eligible.source_kind IN ('UTILITY_PERIOD','UTILITY_CASE')
                                  AND eligible.source_period_start=NEW.billing_period_start
                                  AND eligible.source_period_end=NEW.billing_period_end
                              ))
                        )
                    THEN RAISE EXCEPTION 'Generated Invoice requires an active Billing Run attempt'
                        USING ERRCODE='55000'; END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Invoice history cannot be deleted'
                USING ERRCODE='55000'; END IF;
            PERFORM app.assert_active_financial_actor(NEW.updated_by,v_invoice_property_id);
            IF OLD.status='DRAFT' AND NEW.status NOT IN ('DRAFT','VOID') THEN
                PERFORM app.assert_active_financial_actor(NEW.issued_by,v_invoice_property_id);
            END IF;
            IF NEW.originating_billing_run_attempt_id IS NULL AND EXISTS (
                SELECT 1 FROM app.actor_identities AS identity
                WHERE identity.identity_kind='SERVICE'
                  AND identity.actor_id IN (NEW.updated_by,NEW.issued_by)
            ) THEN RAISE EXCEPTION
                'Service-authored Invoice requires an active Billing Run attempt'
                USING ERRCODE='55000'; END IF;
            IF NEW.id<>OLD.id OR NEW.created_at<>OLD.created_at
                OR NEW.created_by<>OLD.created_by OR NEW.version<>OLD.version+1
                OR NEW.updated_at<OLD.updated_at
            THEN RAISE EXCEPTION 'Invoice identity and provenance are protected'
                USING ERRCODE='55000'; END IF;
            IF NEW.originating_billing_run_attempt_id
                IS DISTINCT FROM OLD.originating_billing_run_attempt_id
            THEN RAISE EXCEPTION 'Billing Run provenance is write-once'
                USING ERRCODE='55000'; END IF;
            IF NEW.originating_billing_run_attempt_id IS NOT NULL
                AND OLD.status='DRAFT' AND NEW.status='DRAFT'
            THEN RAISE EXCEPTION 'Generated DRAFT identity and detail are immutable'
                USING ERRCODE='55000'; END IF;
            IF NEW.originating_billing_run_attempt_id IS NOT NULL
                AND OLD.status='DRAFT' AND NEW.status<>'DRAFT'
            THEN
                SELECT attempt.outcome,run.status,attempt.started_at,run.run_kind,
                    run.property_id,run.business_date,run.period_start,run.period_end,
                    run.system_actor_id
                INTO v_attempt_status,v_run_status,v_attempt_started_at,v_run_kind,
                    v_run_property_id,v_run_business_date,v_run_period_start,v_run_period_end,
                    v_run_system_actor_id
                FROM app.billing_run_attempts AS attempt
                JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                WHERE attempt.id=NEW.originating_billing_run_attempt_id
                FOR UPDATE OF attempt,run;
                IF v_attempt_status IS DISTINCT FROM 'RUNNING'
                    OR v_run_status IS DISTINCT FROM 'RUNNING'
                    OR NEW.created_at<v_attempt_started_at
                    OR NEW.created_by<>v_run_system_actor_id
                    OR (NEW.status<>'VOID' AND (
                        NEW.issued_by<>v_run_system_actor_id
                        OR NEW.updated_by<>v_run_system_actor_id
                    ))
                    OR EXISTS (SELECT 1 FROM app.invoice_lines AS line
                        WHERE line.invoice_id=NEW.id AND line.created_by<>v_run_system_actor_id)
                    OR NEW.invoice_date<>v_run_business_date
                    OR NEW.billing_period_start IS DISTINCT FROM v_run_period_start
                    OR NEW.billing_period_end IS DISTINCT FROM v_run_period_end
                    OR (NEW.status<>'VOID' AND NOT EXISTS (
                        SELECT 1 FROM app.billing_service_principals AS principal
                        WHERE principal.actor_id=v_run_system_actor_id
                          AND principal.property_id=v_run_property_id
                          AND principal.capability='billing.generate'
                          AND principal.lifecycle_state='active'
                    ))
                    OR NOT (
                        (v_run_kind='RENT' AND NEW.primary_category='RENT'
                          AND EXISTS (
                            SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                            JOIN app.billing_run_attempts AS source_attempt
                              ON source_attempt.billing_run_id=eligible.billing_run_id
                            WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                              AND eligible.source_kind='LEASE_PERIOD'
                              AND eligible.source_id=NEW.lease_id
                              AND eligible.source_period_start=NEW.billing_period_start
                              AND eligible.source_period_end=NEW.billing_period_end
                          ))
                        OR (v_run_kind='UTILITIES' AND NEW.primary_category='UTILITIES'
                          AND EXISTS (
                            SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                            JOIN app.billing_run_attempts AS source_attempt
                              ON source_attempt.billing_run_id=eligible.billing_run_id
                            JOIN app.invoice_lines AS line
                              ON line.invoice_id=NEW.id
                            WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                              AND (
                                (eligible.source_kind='UTILITY_PERIOD'
                                  AND line.utility_consumption_period_id=eligible.source_id)
                                OR (eligible.source_kind='UTILITY_CASE' AND EXISTS (
                                    SELECT 1 FROM app.broken_meter_estimates AS estimate
                                    WHERE estimate.estimation_case_id=eligible.source_id
                                      AND estimate.consumption_period_id
                                          =line.utility_consumption_period_id
                                ))
                              )
                              AND eligible.source_period_start=NEW.billing_period_start
                              AND eligible.source_period_end=NEW.billing_period_end
                          ))
                    )
                THEN RAISE EXCEPTION 'Generated Invoice requires an active Billing Run attempt'
                    USING ERRCODE='55000'; END IF;
            END IF;
            IF OLD.status='DRAFT' AND NEW.status='DRAFT' THEN
                PERFORM app.record_invoice_draft_revision(
                    NEW.id,'INVOICE',NEW.id,'UPDATE',to_jsonb(OLD),to_jsonb(NEW),NEW.updated_by
                );
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NEW.status='VOID' THEN
                PERFORM app.advance_invoice_serialization_guard(
                    'invoice-financial:' || NEW.id::text
                );
            END IF;
            IF (OLD.status='DRAFT' AND NEW.status<>'DRAFT')
                OR (NEW.status IS DISTINCT FROM OLD.status AND NEW.status='VOID')
            THEN PERFORM app.lock_invoice_source_evidence(NEW.id,NEW.lease_id); END IF;
            IF OLD.status<>'DRAFT' AND (
                NEW.invoice_number<>OLD.invoice_number OR NEW.customer_id<>OLD.customer_id
                OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
                OR NEW.source_occupancy_id IS DISTINCT FROM OLD.source_occupancy_id
                OR NEW.primary_category<>OLD.primary_category OR NEW.invoice_date<>OLD.invoice_date
                OR NEW.due_date<>OLD.due_date
                OR NEW.billing_period_start IS DISTINCT FROM OLD.billing_period_start
                OR NEW.billing_period_end IS DISTINCT FROM OLD.billing_period_end
                OR NEW.rent_billing_kind IS DISTINCT FROM OLD.rent_billing_kind
                OR NEW.originating_billing_run_attempt_id
                    IS DISTINCT FROM OLD.originating_billing_run_attempt_id
                OR NEW.original_total_usd_cents<>OLD.original_total_usd_cents
                OR NEW.due_date_rule<>OLD.due_date_rule
                OR NEW.due_date_source<>OLD.due_date_source
                OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                OR NEW.issued_by IS DISTINCT FROM OLD.issued_by
            ) THEN RAISE EXCEPTION 'Issued Invoice facts are immutable'
                USING ERRCODE='55000'; END IF;
            IF OLD.status='DRAFT' AND NEW.status='VOID'
                AND (NEW.issued_at IS NOT NULL OR NEW.issued_by IS NOT NULL)
            THEN RAISE EXCEPTION 'Abandoned DRAFT cannot fabricate issuance provenance'
                USING ERRCODE='55000'; END IF;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(id)),0)
                INTO v_adjusted_total FROM app.invoice_lines WHERE invoice_id=NEW.id;
            IF NOT (OLD.status=NEW.status
                OR (OLD.status='DRAFT' AND NEW.status IN ('UNPAID','VOID'))
                OR (OLD.status='UNPAID' AND NEW.status='VOID'))
                AND NOT (OLD.status='UNPAID' AND NEW.status='PAID' AND v_adjusted_total=0)
                AND NOT (OLD.status='PAID' AND NEW.status='UNPAID' AND v_adjusted_total>0)
            THEN RAISE EXCEPTION
                'Payment-dependent Invoice status transition is unavailable before Payment persistence'
                USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION app.protect_billing_run_item_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_parent_status text; v_attempt_status text; v_run_kind text;
        DECLARE v_property_id uuid; v_attempt_started_at timestamptz; v_system_actor_id uuid;
        DECLARE v_attempt_run_id uuid; v_run_period_start date; v_run_period_end date;
        BEGIN
            IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Billing Run item history is append-only'
                USING ERRCODE='55000'; END IF;
            SELECT outcome,started_at,billing_run_id
                INTO v_attempt_status,v_attempt_started_at,v_attempt_run_id
            FROM app.billing_run_attempts
            WHERE id=NEW.billing_run_attempt_id AND billing_run_id=NEW.billing_run_id
            FOR UPDATE;
            SELECT status,run_kind,property_id,period_start,period_end,system_actor_id
                INTO v_parent_status,v_run_kind,v_property_id,v_run_period_start,v_run_period_end,
                    v_system_actor_id
            FROM app.billing_runs WHERE id=NEW.billing_run_id FOR UPDATE;
            PERFORM app.assert_active_financial_actor(v_system_actor_id,v_property_id);
            IF (v_run_kind='RENT' AND NEW.source_kind<>'LEASE_PERIOD')
                OR (v_run_kind='UTILITIES'
                    AND NEW.source_kind NOT IN ('UTILITY_PERIOD','UTILITY_CASE'))
            THEN RAISE EXCEPTION 'Billing Run source kind does not match its run kind'
                USING ERRCODE='23514'; END IF;
            IF v_parent_status IS DISTINCT FROM 'RUNNING'
                OR v_attempt_status IS DISTINCT FROM 'RUNNING'
                OR v_attempt_run_id IS DISTINCT FROM NEW.billing_run_id
                OR NEW.recorded_at<v_attempt_started_at
                OR NEW.source_period_start<>v_run_period_start
                OR NEW.source_period_end<>v_run_period_end
            THEN RAISE EXCEPTION 'Billing Run item is outside its immutable source snapshot'
                USING ERRCODE='55000'; END IF;
            IF (NEW.source_kind='LEASE_PERIOD'
                    AND NOT EXISTS (SELECT 1 FROM app.leases WHERE id=NEW.source_id))
                OR (NEW.source_kind='UTILITY_PERIOD' AND NOT EXISTS (
                    SELECT 1 FROM app.utility_consumption_periods WHERE id=NEW.source_id))
                OR (NEW.source_kind='UTILITY_CASE' AND NOT EXISTS (
                    SELECT 1 FROM app.broken_meter_estimation_cases WHERE id=NEW.source_id))
            THEN RAISE EXCEPTION 'Billing Run source identity does not exist'
                USING ERRCODE='23514'; END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                WHERE eligible.billing_run_id=NEW.billing_run_id
                  AND eligible.source_kind=NEW.source_kind
                  AND eligible.source_id=NEW.source_id
                  AND eligible.source_period_start=NEW.source_period_start
                  AND eligible.source_period_end=NEW.source_period_end
            ) THEN RAISE EXCEPTION 'Billing Run item source is absent from its snapshot'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='SKIPPED'
                AND NEW.diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS'
                AND NOT EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    WHERE invoice.id=NEW.invoice_id AND invoice.status<>'VOID'
                      AND invoice.issued_at IS NOT NULL AND invoice.issued_at<=NEW.recorded_at
                      AND (
                        (v_run_kind='RENT' AND invoice.primary_category='RENT'
                          AND invoice.lease_id=NEW.source_id
                          AND invoice.billing_period_start=NEW.source_period_start
                          AND invoice.billing_period_end=NEW.source_period_end)
                        OR (v_run_kind='UTILITIES' AND invoice.primary_category='UTILITIES'
                          AND EXISTS (SELECT 1 FROM app.invoice_lines AS line
                            WHERE line.invoice_id=invoice.id
                              AND (
                                (NEW.source_kind='UTILITY_PERIOD'
                                  AND line.utility_consumption_period_id=NEW.source_id)
                                OR (NEW.source_kind='UTILITY_CASE' AND EXISTS (
                                    SELECT 1 FROM app.broken_meter_estimates AS estimate
                                    WHERE estimate.estimation_case_id=NEW.source_id
                                      AND estimate.consumption_period_id
                                          =line.utility_consumption_period_id
                                ))
                              )
                              AND line.period_start=NEW.source_period_start
                              AND line.period_end=NEW.source_period_end))
                      )
                      AND invoice.originating_billing_run_attempt_id
                          IS DISTINCT FROM NEW.billing_run_attempt_id
                )
            THEN RAISE EXCEPTION 'Skipped source requires one matching active Invoice'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='SKIPPED' AND NEW.diagnostic_code='SOURCE_NO_LONGER_ELIGIBLE'
                AND v_run_kind='RENT'
                AND app.lease_is_billable_for_recurring_period(
                    NEW.source_id,NEW.source_period_start,NEW.source_period_end,NEW.recorded_at
                )
            THEN RAISE EXCEPTION 'Skipped source is still eligible for billing'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='GENERATED' AND NOT EXISTS (
                SELECT 1 FROM app.invoices AS invoice
                WHERE invoice.id=NEW.invoice_id
                  AND invoice.originating_billing_run_attempt_id=NEW.billing_run_attempt_id
                  AND invoice.created_at>=v_attempt_started_at
                  AND invoice.issued_at>=v_attempt_started_at
                  AND invoice.issued_at<=NEW.recorded_at
                  AND invoice.created_by=v_system_actor_id
                  AND invoice.updated_by=v_system_actor_id
                  AND invoice.issued_by=v_system_actor_id
                  AND NOT EXISTS (SELECT 1 FROM app.invoice_lines AS line
                    WHERE line.invoice_id=invoice.id AND line.created_by<>v_system_actor_id)
            ) THEN RAISE EXCEPTION 'Generated Invoice was not created by this Billing Run attempt'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='GENERATED' AND (
                (v_run_kind='RENT' AND NOT EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    WHERE invoice.id=NEW.invoice_id AND invoice.status='UNPAID'
                      AND invoice.primary_category='RENT' AND invoice.lease_id=NEW.source_id
                      AND invoice.invoice_date=(SELECT run.business_date
                        FROM app.billing_runs AS run WHERE run.id=NEW.billing_run_id)
                      AND invoice.billing_period_start=NEW.source_period_start
                      AND invoice.billing_period_end=NEW.source_period_end))
                OR (v_run_kind='UTILITIES' AND NOT EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
                    JOIN app.utility_rates AS rate ON rate.id=line.utility_rate_id
                    WHERE invoice.id=NEW.invoice_id AND invoice.status='UNPAID'
                      AND invoice.primary_category='UTILITIES'
                      AND (
                        (NEW.source_kind='UTILITY_PERIOD'
                          AND line.utility_consumption_period_id=NEW.source_id)
                        OR (NEW.source_kind='UTILITY_CASE' AND EXISTS (
                            SELECT 1 FROM app.broken_meter_estimates AS estimate
                            WHERE estimate.estimation_case_id=NEW.source_id
                              AND estimate.consumption_period_id
                                  =line.utility_consumption_period_id
                        ))
                      )
                      AND line.period_start=NEW.source_period_start
                      AND line.period_end=NEW.source_period_end
                      AND rate.property_id=v_property_id))
            ) THEN RAISE EXCEPTION 'Generated Billing Run item Invoice provenance is invalid'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION app.billing_run_has_missing_eligible_sources(
            p_billing_run_id uuid,p_through_attempt_number integer
        ) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                WHERE eligible.billing_run_id=p_billing_run_id
                  AND NOT EXISTS (
                    SELECT 1 FROM (
                        SELECT item.outcome,item.invoice_id,item.diagnostic_code,item.recorded_at
                        FROM app.billing_run_items AS item
                        JOIN app.billing_run_attempts AS attempt
                          ON attempt.id=item.billing_run_attempt_id
                        WHERE item.billing_run_id=eligible.billing_run_id
                          AND attempt.attempt_number<=p_through_attempt_number
                          AND item.source_kind=eligible.source_kind
                          AND item.source_id=eligible.source_id
                          AND item.source_period_start=eligible.source_period_start
                          AND item.source_period_end=eligible.source_period_end
                        ORDER BY attempt.attempt_number DESC LIMIT 1
                    ) AS latest
                    WHERE latest.outcome IN ('GENERATED','SKIPPED')
                      AND (
                        (latest.invoice_id IS NULL AND latest.diagnostic_code IN (
                            'SOURCE_NO_LONGER_ELIGIBLE','ZERO_AMOUNT_NO_OBLIGATION'
                        ))
                        OR EXISTS (SELECT 1 FROM app.invoices AS invoice
                            WHERE invoice.id=latest.invoice_id AND invoice.status<>'VOID')
                      )
                  )
            )
        $$;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.start_scheduled_billing_run(
            p_run_id uuid,p_property_id uuid,p_run_kind text,p_logical_run_key text,
            p_business_date date,p_period_start date,p_period_end date,
            p_idempotency_key uuid,p_request_digest text,p_requester_actor_id uuid,
            p_system_actor_id uuid,p_correlation_id uuid,p_invocation_source text
        ) RETURNS TABLE(run_id uuid,attempt_id uuid,should_execute boolean)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_run app.billing_runs%ROWTYPE; v_attempt app.billing_run_attempts%ROWTYPE;
        DECLARE v_attempt_number integer; v_started_at timestamptz:=clock_timestamp();
        BEGIN
            IF p_run_id IS NULL OR p_property_id IS NULL OR p_requester_actor_id IS NULL
                OR p_system_actor_id IS NULL
                OR p_idempotency_key IS NULL OR p_correlation_id IS NULL
                OR p_run_kind NOT IN ('RENT','UTILITIES')
                OR p_logical_run_key IS NULL OR p_logical_run_key<>btrim(p_logical_run_key)
                OR length(p_logical_run_key)=0 OR length(p_logical_run_key)>200
                OR p_business_date IS NULL OR p_period_start IS NULL OR p_period_end IS NULL
                OR p_period_end<p_period_start OR p_request_digest!~'^[0-9a-f]{64}$'
                OR p_invocation_source NOT IN ('API','SCHEDULED')
            THEN RAISE EXCEPTION 'Scheduled Billing command evidence is invalid'
                USING ERRCODE='22023'; END IF;
            PERFORM app.assert_active_financial_actor(p_requester_actor_id,p_property_id);
            IF NOT EXISTS (
                SELECT 1 FROM app.actor_identities AS identity
                WHERE identity.actor_id=p_system_actor_id AND identity.identity_kind='SERVICE'
            ) THEN RAISE EXCEPTION 'Scheduled Billing requires a service principal'
                USING ERRCODE='55000'; END IF;
            PERFORM app.assert_active_financial_actor(p_system_actor_id,p_property_id);
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'scheduled-billing/' || p_property_id::text || '/' || p_run_kind || '/'
                    || p_period_start::text || '/' || p_period_end::text,0
            ));
            SELECT run.* INTO v_run FROM app.billing_runs AS run
            WHERE run.property_id=p_property_id AND (
                run.idempotency_key=p_idempotency_key
                OR run.logical_run_key=p_logical_run_key
                OR (run.run_kind=p_run_kind AND run.period_start=p_period_start
                    AND run.period_end=p_period_end AND run.predecessor_run_id IS NULL)
            ) ORDER BY run.created_at,run.id LIMIT 1 FOR UPDATE;
            IF FOUND THEN
                IF v_run.run_kind<>p_run_kind
                    OR v_run.logical_run_key<>p_logical_run_key
                    OR v_run.business_date<>p_business_date
                    OR v_run.period_start<>p_period_start OR v_run.period_end<>p_period_end
                    OR v_run.idempotency_key<>p_idempotency_key
                    OR v_run.request_digest<>p_request_digest
                    OR v_run.requester_actor_id<>p_requester_actor_id
                    OR v_run.system_actor_id<>p_system_actor_id
                    OR v_run.correlation_id<>p_correlation_id
                    OR v_run.invocation_source<>p_invocation_source
                THEN RAISE EXCEPTION 'Scheduled Billing idempotency key conflicts with another input'
                    USING ERRCODE='23505'; END IF;
                IF v_run.status='SUCCEEDED' THEN
                    SELECT attempt.* INTO v_attempt FROM app.billing_run_attempts AS attempt
                    WHERE attempt.billing_run_id=v_run.id
                    ORDER BY attempt.attempt_number DESC LIMIT 1;
                    RETURN QUERY SELECT v_run.id,v_attempt.id,false;
                    RETURN;
                END IF;
                IF v_run.status<>'RUNNING' THEN
                    RAISE EXCEPTION 'Terminal failed Billing Run requires explicit successor policy'
                        USING ERRCODE='55000';
                END IF;
                SELECT attempt.* INTO v_attempt FROM app.billing_run_attempts AS attempt
                WHERE attempt.billing_run_id=v_run.id
                ORDER BY attempt.attempt_number DESC LIMIT 1 FOR UPDATE;
                IF v_attempt.outcome='RUNNING' THEN
                    RETURN QUERY SELECT v_run.id,v_attempt.id,true;
                    RETURN;
                END IF;
                v_attempt_number:=v_attempt.attempt_number+1;
            ELSE
                INSERT INTO app.billing_runs(
                    id,property_id,run_kind,logical_run_key,business_date,period_start,period_end,
                    idempotency_key,request_digest,requester_actor_id,system_actor_id,correlation_id,
                    invocation_source,status,started_at
                ) VALUES (
                    p_run_id,p_property_id,p_run_kind,p_logical_run_key,p_business_date,
                    p_period_start,p_period_end,p_idempotency_key,p_request_digest,
                    p_requester_actor_id,p_system_actor_id,
                    p_correlation_id,p_invocation_source,'RUNNING',v_started_at
                ) RETURNING * INTO v_run;
                v_attempt_number:=1;
            END IF;
            INSERT INTO app.billing_run_attempts(
                id,billing_run_id,attempt_number,started_at,outcome
            ) VALUES (
                md5(v_run.id::text || '/attempt/' || v_attempt_number::text)::uuid,
                v_run.id,v_attempt_number,v_started_at,'RUNNING'
            ) RETURNING * INTO v_attempt;
            RETURN QUERY SELECT v_run.id,v_attempt.id,true;
        END $$;

        CREATE FUNCTION app.record_scheduled_rent_item(
            p_run_id uuid,p_attempt_id uuid,p_source_id uuid,p_invoice_id uuid,
            p_invoice_number text,p_command_key uuid,p_request_digest text,p_audit_event_id uuid,
            p_issued_at timestamptz
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_run app.billing_runs%ROWTYPE; v_attempt app.billing_run_attempts%ROWTYPE;
        DECLARE v_result jsonb; v_item_id uuid; v_recorded_at timestamptz;
        DECLARE v_existing app.billing_run_items%ROWTYPE; v_existing_invoice_id uuid;
        DECLARE v_sqlstate text;
        BEGIN
            SELECT * INTO STRICT v_run FROM app.billing_runs WHERE id=p_run_id FOR UPDATE;
            SELECT * INTO STRICT v_attempt FROM app.billing_run_attempts
            WHERE id=p_attempt_id AND billing_run_id=p_run_id FOR UPDATE;
            SELECT * INTO v_existing FROM app.billing_run_items
            WHERE billing_run_attempt_id=p_attempt_id AND source_kind='LEASE_PERIOD'
              AND source_id=p_source_id AND source_period_start=v_run.period_start
              AND source_period_end=v_run.period_end;
            IF FOUND THEN RETURN v_existing.outcome; END IF;
            v_item_id:=md5(p_attempt_id::text || '/rent/' || p_source_id::text)::uuid;
            SELECT invoice.id INTO v_existing_invoice_id
            FROM app.invoices AS invoice
            JOIN app.billing_run_attempts AS prior_attempt
              ON prior_attempt.id=invoice.originating_billing_run_attempt_id
            WHERE invoice.id=p_invoice_id AND invoice.status<>'VOID'
              AND invoice.primary_category='RENT' AND invoice.lease_id=p_source_id
              AND invoice.billing_period_start=v_run.period_start
              AND invoice.billing_period_end=v_run.period_end
              AND prior_attempt.billing_run_id=p_run_id
              AND prior_attempt.id<>p_attempt_id
            FOR UPDATE OF invoice;
            IF FOUND THEN
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,invoice_id,
                    diagnostic_code,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,'LEASE_PERIOD',p_source_id,
                    v_run.period_start,v_run.period_end,'SKIPPED',v_existing_invoice_id,
                    'ACTIVE_INVOICE_ALREADY_EXISTS',clock_timestamp());
                RETURN 'SKIPPED';
            END IF;
            IF NOT app.lease_is_billable_for_recurring_period(
                p_source_id,v_run.period_start,v_run.period_end,clock_timestamp()
            ) THEN
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,'LEASE_PERIOD',p_source_id,
                    v_run.period_start,v_run.period_end,'SKIPPED','SOURCE_NO_LONGER_ELIGIBLE',
                    clock_timestamp());
                RETURN 'SKIPPED';
            END IF;
            BEGIN
                v_result:=app.generate_rent_service_invoice(
                    v_run.property_id,p_command_key,p_request_digest,p_invoice_id,p_invoice_number,
                    p_source_id,NULL,'RECURRING',v_run.period_start,p_issued_at,
                    v_run.system_actor_id,p_attempt_id
                );
                v_recorded_at:=clock_timestamp();
                INSERT INTO app.audit_events(
                    id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                    reason,authorization_reference,property_id,previous_state,resulting_state,
                    correlation_id,source,outcome,authorization_evidence,lease_id
                ) VALUES (
                    p_audit_event_id,v_recorded_at,v_run.business_date,v_run.system_actor_id,
                    'billing.rent.generated','invoice',p_invoice_id,
                    'Deterministic scheduled Rent and Service issuance','billing.generate',
                    v_run.property_id,'{}'::jsonb,v_result,v_run.correlation_id,
                    v_run.invocation_source,'SUCCEEDED',
                    pg_catalog.jsonb_build_object('billing_run_id',p_run_id,
                        'billing_run_attempt_id',p_attempt_id,'source_lease_id',p_source_id,
                        'requester_actor_id',v_run.requester_actor_id,
                        'system_actor_id',v_run.system_actor_id),
                    p_source_id
                );
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,invoice_id,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,'LEASE_PERIOD',p_source_id,
                    v_run.period_start,v_run.period_end,'GENERATED',p_invoice_id,v_recorded_at);
                SET CONSTRAINTS ALL IMMEDIATE;
                RETURN 'GENERATED';
            EXCEPTION WHEN OTHERS THEN
                GET STACKED DIAGNOSTICS v_sqlstate=RETURNED_SQLSTATE;
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,'LEASE_PERIOD',p_source_id,
                    v_run.period_start,v_run.period_end,'ERROR',
                    'RENT_PERSISTENCE_'||v_sqlstate,clock_timestamp());
                RETURN 'ERROR';
            END;
        END $$;

        CREATE FUNCTION app.billing_run_generation_at(p_run_id uuid)
        RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_run app.billing_runs%ROWTYPE; v_timezone text;
        BEGIN
            SELECT * INTO STRICT v_run FROM app.billing_runs WHERE id=p_run_id;
            PERFORM app.assert_active_financial_actor(v_run.system_actor_id,v_run.property_id);
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=v_run.property_id;
            RETURN v_run.business_date::timestamp AT TIME ZONE v_timezone;
        END $$;

        CREATE FUNCTION app.try_scheduled_billing_worker_lock(
            p_property_id uuid,p_actor_id uuid
        ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        BEGIN
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            RETURN pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
                'scheduled-billing-worker/' || p_property_id::text,0
            ));
        END $$;

        CREATE FUNCTION app.billing_worker_property_date(
            p_property_id uuid,p_actor_id uuid,p_as_of timestamptz
        ) RETURNS date LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text;
        BEGIN
            IF p_as_of IS NULL THEN RAISE EXCEPTION 'Worker instant is required'
                USING ERRCODE='22023'; END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=p_property_id;
            RETURN timezone(v_timezone,p_as_of)::date;
        END $$;

        CREATE FUNCTION app.scheduled_billing_worker_candidates(
            p_property_id uuid,p_actor_id uuid,p_as_of timestamptz,p_limit integer
        ) RETURNS TABLE(
            business_date date,period_start date,period_end date,run_kind text
        ) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_timezone text; v_current_date date;
        BEGIN
            IF p_as_of IS NULL OR p_limit<1 OR p_limit>100 THEN
                RAISE EXCEPTION 'Worker candidate bounds are invalid' USING ERRCODE='22023';
            END IF;
            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id=p_property_id;
            v_current_date:=timezone(v_timezone,p_as_of)::date;
            RETURN QUERY
            WITH rent_candidates AS (
                SELECT candidate::date AS candidate_business_date,
                    (date_trunc('month',candidate)::date+interval '1 month')::date
                        AS candidate_period_start,
                    (date_trunc('month',candidate)::date
                        +interval '2 months - 1 day')::date AS candidate_period_end,
                    'RENT'::text AS candidate_run_kind
                FROM generate_series(
                    v_current_date-(p_limit*interval '32 days'),v_current_date,interval '1 day'
                ) AS candidate
                WHERE extract(day FROM candidate)=25
                  AND EXISTS (
                    SELECT 1 FROM app.leases AS lease
                    JOIN app.units AS unit ON unit.id=lease.unit_id
                    WHERE unit.property_id=p_property_id
                      AND app.lease_is_billable_for_recurring_period(
                        lease.id,
                        (date_trunc('month',candidate)::date+interval '1 month')::date,
                        (date_trunc('month',candidate)::date
                            +interval '2 months - 1 day')::date,
                        p_as_of
                      )
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM app.billing_runs AS run
                    WHERE run.property_id=p_property_id AND run.run_kind='RENT'
                      AND run.business_date=candidate::date AND run.status='SUCCEEDED'
                  )
            ), utility_candidates AS (
                SELECT COALESCE((
                           SELECT run.business_date FROM app.billing_runs AS run
                           WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'
                             AND run.period_start=period.start_date
                             AND run.period_end=period.end_date AND run.status='RUNNING'
                           ORDER BY run.created_at,run.id LIMIT 1
                       ),greatest(period.end_date,
                           timezone(v_timezone,period.finalized_at)::date)),
                       period.start_date,period.end_date,'UTILITIES'::text
                FROM app.utility_consumption_periods AS period
                JOIN app.units AS unit ON unit.id=period.unit_id
                WHERE unit.property_id=p_property_id
                  AND greatest(period.end_date,
                        timezone(v_timezone,period.finalized_at)::date)<=v_current_date
                  AND NOT EXISTS (
                    SELECT 1 FROM app.billing_runs AS run
                    WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'
                      AND run.period_start=period.start_date AND run.period_end=period.end_date
                      AND run.status='SUCCEEDED'
                  )
                UNION
                SELECT COALESCE((
                           SELECT run.business_date FROM app.billing_runs AS run
                           WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'
                             AND run.period_start=case_record.unmeasured_start_date
                             AND run.period_end=case_record.unmeasured_end_date
                             AND run.status='RUNNING'
                           ORDER BY run.created_at,run.id LIMIT 1
                       ),greatest(case_record.unmeasured_end_date,
                           timezone(v_timezone,case_record.opened_at)::date)),
                       case_record.unmeasured_start_date,case_record.unmeasured_end_date,
                       'UTILITIES'::text
                FROM app.broken_meter_estimation_cases AS case_record
                JOIN app.units AS unit ON unit.id=case_record.unit_id
                WHERE unit.property_id=p_property_id
                  AND greatest(case_record.unmeasured_end_date,
                        timezone(v_timezone,case_record.opened_at)::date)<=v_current_date
                  AND NOT EXISTS (SELECT 1 FROM app.broken_meter_estimates AS estimate
                    WHERE estimate.estimation_case_id=case_record.id)
                  AND NOT EXISTS (
                    SELECT 1 FROM app.billing_runs AS run
                    WHERE run.property_id=p_property_id AND run.run_kind='UTILITIES'
                      AND run.period_start=case_record.unmeasured_start_date
                      AND run.period_end=case_record.unmeasured_end_date
                      AND run.status='SUCCEEDED'
                  )
            )
            SELECT due.candidate_business_date,due.candidate_period_start,
                due.candidate_period_end,due.candidate_run_kind
            FROM (
                SELECT * FROM rent_candidates
                UNION
                SELECT * FROM utility_candidates
            ) AS due
            ORDER BY due.candidate_business_date,due.candidate_period_start,
                due.candidate_period_end,due.candidate_run_kind
            LIMIT p_limit;
        END $$;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.record_scheduled_utility_item(
            p_run_id uuid,p_attempt_id uuid,p_source_kind text,p_source_id uuid,
            p_invoice_id uuid,p_invoice_number text,p_audit_event_id uuid,
            p_generation_at timestamptz
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_run app.billing_runs%ROWTYPE; v_attempt app.billing_run_attempts%ROWTYPE;
        DECLARE v_period app.utility_consumption_periods%ROWTYPE; v_existing app.billing_run_items%ROWTYPE;
        DECLARE v_existing_invoice_id uuid; v_existing_attempt_id uuid;
        DECLARE v_preview jsonb; v_lease_id uuid; v_customer_id uuid; v_unit_id uuid;
        DECLARE v_item_id uuid; v_line_id uuid; v_now timestamptz; v_due_date date;
        DECLARE v_consumption_period_id uuid:=p_source_id;
        DECLARE v_amount bigint; v_quantity numeric(38,6); v_rate numeric(20,8);
        DECLARE v_rate_id uuid; v_rate_effective_date date; v_sqlstate text;
        BEGIN
            SELECT * INTO STRICT v_run FROM app.billing_runs WHERE id=p_run_id FOR UPDATE;
            SELECT * INTO STRICT v_attempt FROM app.billing_run_attempts
            WHERE id=p_attempt_id AND billing_run_id=p_run_id FOR UPDATE;
            SELECT * INTO v_existing FROM app.billing_run_items
            WHERE billing_run_attempt_id=p_attempt_id AND source_kind=p_source_kind
              AND source_id=p_source_id AND source_period_start=v_run.period_start
              AND source_period_end=v_run.period_end;
            IF FOUND THEN RETURN v_existing.outcome; END IF;
            v_item_id:=md5(p_attempt_id::text || '/' || p_source_kind || '/'
                || p_source_id::text)::uuid;
            IF p_source_kind='UTILITY_CASE' THEN
                SELECT estimate.consumption_period_id INTO v_consumption_period_id
                FROM app.broken_meter_estimates AS estimate
                JOIN app.utility_consumption_periods AS period
                  ON period.id=estimate.consumption_period_id
                JOIN app.units AS unit ON unit.id=period.unit_id
                WHERE estimate.estimation_case_id=p_source_id
                  AND unit.property_id=v_run.property_id
                  AND period.start_date=v_run.period_start
                  AND period.end_date=v_run.period_end
                  AND period.finalized_at<=clock_timestamp();
                IF NOT FOUND THEN
                    INSERT INTO app.billing_run_items(
                        id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                        source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                    ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                        v_run.period_start,v_run.period_end,'SKIPPED',
                        'PENDING_FUTURE_ACTUAL_BASIS',clock_timestamp());
                    RETURN 'SKIPPED';
                END IF;
            END IF;
            BEGIN
                SELECT period.* INTO STRICT v_period
                FROM app.utility_consumption_periods AS period
                JOIN app.units AS unit ON unit.id=period.unit_id
                WHERE period.id=v_consumption_period_id AND unit.property_id=v_run.property_id
                  AND period.start_date=v_run.period_start AND period.end_date=v_run.period_end;
                SELECT invoice.id,invoice.originating_billing_run_attempt_id
                    INTO v_existing_invoice_id,v_existing_attempt_id
                FROM app.invoices AS invoice
                JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
                WHERE line.utility_consumption_period_id=v_consumption_period_id
                  AND invoice.status<>'VOID'
                ORDER BY invoice.id LIMIT 1 FOR UPDATE OF invoice;
                IF FOUND THEN
                    v_now:=clock_timestamp();
                    INSERT INTO app.billing_run_items(
                        id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                        source_period_start,source_period_end,outcome,invoice_id,
                        diagnostic_code,recorded_at
                    ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                        v_run.period_start,v_run.period_end,
                        CASE WHEN v_existing_attempt_id=p_attempt_id THEN 'GENERATED' ELSE 'SKIPPED' END,
                        v_existing_invoice_id,
                        CASE WHEN v_existing_attempt_id=p_attempt_id THEN NULL
                            ELSE 'ACTIVE_INVOICE_ALREADY_EXISTS' END,v_now);
                    RETURN CASE WHEN v_existing_attempt_id=p_attempt_id
                        THEN 'GENERATED' ELSE 'SKIPPED' END;
                END IF;
                v_preview:=app.preview_utility_calculation(
                    v_run.property_id,'CONSUMPTION_PERIOD',v_consumption_period_id,
                    p_generation_at,v_run.system_actor_id
                );
                v_amount:=(v_preview->>'amount_usd_cents')::bigint;
                v_quantity:=(v_preview->>'consumption_quantity')::numeric;
                v_rate:=(v_preview->>'rate_usd_per_unit')::numeric;
                v_rate_id:=(v_preview->>'rate_id')::uuid;
                v_rate_effective_date:=(v_preview->>'rate_effective_date')::date;
                IF v_amount=0 THEN
                    INSERT INTO app.billing_run_items(
                        id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                        source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                    ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                        v_run.period_start,v_run.period_end,'SKIPPED',
                        'ZERO_AMOUNT_NO_OBLIGATION',clock_timestamp());
                    RETURN 'SKIPPED';
                END IF;
                SELECT lease.id,lease.primary_tenant_id,lease.unit_id
                    INTO v_lease_id,v_customer_id,v_unit_id
                FROM app.leases AS lease
                WHERE lease.unit_id=v_period.unit_id AND lease.status IN ('SIGNED','TERMINATED')
                  AND lease.start_date<=v_period.start_date
                  AND COALESCE(lease.actual_termination_date,lease.end_date)>=v_period.end_date
                  AND EXISTS (SELECT 1 FROM app.lease_signers AS signer
                    WHERE signer.lease_id=lease.id AND signer.customer_id=lease.primary_tenant_id
                      AND signer.signed_at IS NOT NULL)
                  AND EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                    WHERE occupancy.lease_id=lease.id
                      AND occupancy.customer_id=lease.primary_tenant_id
                      AND occupancy.move_in_date<=v_period.start_date
                      AND COALESCE(occupancy.move_out_date,v_period.end_date)>=v_period.end_date)
                ORDER BY lease.start_date DESC,lease.id LIMIT 1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Utility responsibility evidence was not found'
                        USING ERRCODE='P0002';
                END IF;
                v_now:=clock_timestamp();
                v_due_date:=(date_trunc('month',v_period.end_date)::date
                    + interval '1 month')::date+4;
                INSERT INTO app.invoices(
                    id,invoice_number,customer_id,lease_id,primary_category,status,
                    invoice_date,due_date,billing_period_start,billing_period_end,
                    original_total_usd_cents,due_date_rule,due_date_source,version,
                    created_at,created_by,updated_at,updated_by,originating_billing_run_attempt_id
                ) VALUES (
                    p_invoice_id,p_invoice_number,v_customer_id,v_lease_id,'UTILITIES','DRAFT',
                    v_run.business_date,v_due_date,v_period.start_date,v_period.end_date,
                    v_amount,'GOVERNING_SOURCE','BR-UTIL-022',1,v_now,v_run.system_actor_id,
                    v_now,v_run.system_actor_id,p_attempt_id
                );
                v_line_id:=md5(p_invoice_id::text || '/utility-line')::uuid;
                INSERT INTO app.invoice_lines(
                    id,invoice_id,line_sequence,category,description,amount_usd_cents,
                    period_start,period_end,source_lease_id,utility_consumption_period_id,
                    utility_rate_id,quantity,unit_rate_usd,calculation_trace,
                    created_at,last_changed_at,created_by,last_changed_by
                ) VALUES (
                    v_line_id,p_invoice_id,1,'UTILITIES',
                    CASE v_period.utility_type WHEN 'ELECTRICITY' THEN 'Electricity' ELSE 'Water' END,
                    v_amount,v_period.start_date,v_period.end_date,v_lease_id,
                    v_consumption_period_id,
                    v_rate_id,v_quantity,v_rate,
                    v_preview || pg_catalog.jsonb_build_object(
                        'responsible_customer_id',v_customer_id,
                        'responsible_lease_id',v_lease_id,'unit_id',v_unit_id,
                        'rate_effective_date',v_rate_effective_date,
                        'source_evidence',(SELECT eligible.source_evidence
                            FROM app.billing_run_eligible_sources AS eligible
                            WHERE eligible.billing_run_id=p_run_id
                              AND eligible.source_kind=p_source_kind
                              AND eligible.source_id=p_source_id)
                    ),v_now,v_now,v_run.system_actor_id,v_run.system_actor_id
                );
                UPDATE app.invoices SET status='UNPAID',issued_at=v_now,
                    issued_by=v_run.system_actor_id,version=2,updated_at=v_now,
                    updated_by=v_run.system_actor_id WHERE id=p_invoice_id;
                INSERT INTO app.audit_events(
                    id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                    reason,authorization_reference,property_id,previous_state,resulting_state,
                    correlation_id,source,outcome,authorization_evidence,
                    customer_id,unit_id,lease_id
                ) VALUES (
                    p_audit_event_id,v_now,v_run.business_date,v_run.system_actor_id,
                    'billing.utility.generated','invoice',p_invoice_id,
                    'Deterministic scheduled Utility issuance','billing.generate',
                    v_run.property_id,'{}'::jsonb,
                    pg_catalog.jsonb_build_object('invoice_id',p_invoice_id,
                        'amount_usd_cents',v_amount,'utility_snapshot',v_preview),
                    v_run.correlation_id,v_run.invocation_source,'SUCCEEDED',
                    pg_catalog.jsonb_build_object('billing_run_id',p_run_id,
                        'billing_run_attempt_id',p_attempt_id,
                        'requester_actor_id',v_run.requester_actor_id,
                        'system_actor_id',v_run.system_actor_id,
                        'utility_consumption_period_id',v_consumption_period_id,
                        'estimation_case_id',CASE WHEN p_source_kind='UTILITY_CASE'
                            THEN p_source_id ELSE NULL END,
                        'responsible_customer_id',v_customer_id,
                        'responsible_lease_id',v_lease_id),
                    v_customer_id,v_unit_id,v_lease_id
                );
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,invoice_id,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                    v_run.period_start,v_run.period_end,'GENERATED',p_invoice_id,v_now);
                SET CONSTRAINTS ALL IMMEDIATE;
                RETURN 'GENERATED';
            EXCEPTION WHEN OTHERS THEN
                GET STACKED DIAGNOSTICS v_sqlstate=RETURNED_SQLSTATE;
                INSERT INTO app.billing_run_items(
                    id,billing_run_id,billing_run_attempt_id,source_kind,source_id,
                    source_period_start,source_period_end,outcome,diagnostic_code,recorded_at
                ) VALUES (v_item_id,p_run_id,p_attempt_id,p_source_kind,p_source_id,
                    v_run.period_start,v_run.period_end,'ERROR',
                    'UTILITY_PERSISTENCE_'||v_sqlstate,clock_timestamp());
                RETURN 'ERROR';
            END;
        END $$;

        CREATE FUNCTION app.finish_scheduled_billing_attempt(
            p_run_id uuid,p_attempt_id uuid
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE v_attempt app.billing_run_attempts%ROWTYPE; v_completed_at timestamptz;
        DECLARE v_failed boolean;
        BEGIN
            SELECT * INTO STRICT v_attempt FROM app.billing_run_attempts
            WHERE id=p_attempt_id AND billing_run_id=p_run_id FOR UPDATE;
            IF v_attempt.outcome<>'RUNNING' THEN RETURN v_attempt.outcome; END IF;
            SELECT EXISTS (SELECT 1 FROM app.billing_run_items
                WHERE billing_run_attempt_id=p_attempt_id AND outcome IN ('CONFLICT','ERROR'))
                OR app.billing_run_has_missing_eligible_sources(p_run_id,v_attempt.attempt_number)
                INTO v_failed;
            v_completed_at:=clock_timestamp();
            IF v_failed THEN
                UPDATE app.billing_run_attempts SET outcome='FAILED',
                    completed_at=v_completed_at,diagnostic_code='ITEM_FAILURE'
                WHERE id=p_attempt_id;
                RETURN 'FAILED';
            END IF;
            UPDATE app.billing_run_attempts SET outcome='SUCCEEDED',completed_at=v_completed_at
            WHERE id=p_attempt_id;
            UPDATE app.billing_runs SET status='SUCCEEDED',completed_at=clock_timestamp()
            WHERE id=p_run_id;
            RETURN 'SUCCEEDED';
        END $$;
        """
    )
    for function in (
        "app.start_scheduled_billing_run(uuid,uuid,text,text,date,date,date,uuid,text,uuid,uuid,uuid,text)",
        "app.billing_run_generation_at(uuid)",
        "app.try_scheduled_billing_worker_lock(uuid,uuid)",
        "app.billing_worker_property_date(uuid,uuid,timestamp with time zone)",
        "app.scheduled_billing_worker_candidates(uuid,uuid,timestamp with time zone,integer)",
        "app.record_scheduled_rent_item(uuid,uuid,uuid,uuid,text,uuid,text,uuid,timestamp with time zone)",
        "app.record_scheduled_utility_item(uuid,uuid,text,uuid,uuid,text,uuid,timestamp with time zone)",
        "app.finish_scheduled_billing_attempt(uuid,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_financial")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.preview_utility_calculation(uuid,text,uuid,timestamp with time zone,uuid) "
        "TO prm_financial"
    )
    op.execute(
        "COMMENT ON COLUMN app.invoice_lines.utility_consumption_period_id IS "
        "'Stable DB-UTIL-006 identity issued only through the V1-044 billing-run boundary'"
    )


def downgrade() -> None:
    """Refuse destructive rollback of durable financial run history."""
    raise RuntimeError("scheduled billing migration is forward-only")
