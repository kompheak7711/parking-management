"""Add transactional Rent proration and fixed-Service billing."""

from alembic import op

revision = "20260828_30"
down_revision = "20260827_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-040 billing service and replay ledger."""
    op.execute(
        r"""
        CREATE TABLE app.rent_billing_commands (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (
                idempotency_key<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            requested_invoice_id uuid NOT NULL CHECK (
                requested_invoice_id<>'00000000-0000-0000-0000-000000000000'::uuid
            ),
            requested_invoice_number text NOT NULL CHECK (
                length(btrim(requested_invoice_number))>0
                AND requested_invoice_number=btrim(requested_invoice_number)
                AND length(requested_invoice_number)<=100
            ),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            source_occupancy_id uuid REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            billing_kind text NOT NULL CHECK (billing_kind IN ('INITIAL','RECURRING')),
            period_start date NOT NULL,
            period_end date NOT NULL CHECK (period_end>=period_start),
            requested_issued_at timestamptz NOT NULL,
            source_selection_cutoff timestamptz NOT NULL,
            originating_billing_run_attempt_id uuid
                REFERENCES app.billing_run_attempts(id) ON DELETE RESTRICT,
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot)='object'),
            completed_at timestamptz NOT NULL,
            CONSTRAINT rent_billing_commands_idempotency_unique
                UNIQUE(property_id,actor_id,idempotency_key)
        );
        CREATE INDEX rent_billing_commands_invoice_history_idx
            ON app.rent_billing_commands(invoice_id,completed_at,id);

        CREATE FUNCTION app.calculate_prorated_monthly_usd_cents(
            p_monthly_usd_cents bigint,p_period_start date,p_period_end date
        ) RETURNS bigint LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
        DECLARE v_calendar_days integer; v_billable_days integer;
        BEGIN
            IF p_monthly_usd_cents<=0 OR p_period_start IS NULL OR p_period_end IS NULL
                OR p_period_end<p_period_start
                OR date_trunc('month',p_period_start)<>date_trunc('month',p_period_end)
            THEN RAISE EXCEPTION 'Monthly proration evidence is invalid'
                USING ERRCODE='22023'; END IF;
            v_calendar_days:=extract(day FROM (
                date_trunc('month',p_period_start)+interval '1 month - 1 day'
            ))::integer;
            v_billable_days:=p_period_end-p_period_start+1;
            RETURN round(
                p_monthly_usd_cents::numeric*v_billable_days/v_calendar_days,0
            )::bigint;
        END $$;

        CREATE FUNCTION app.rent_invoice_snapshot(p_invoice_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT jsonb_build_object(
                'invoice_id',invoice.id,
                'property_id',unit.property_id,
                'lease_id',invoice.lease_id,
                'customer_id',invoice.customer_id,
                'billing_kind',invoice.rent_billing_kind,
                'invoice_date',invoice.invoice_date,
                'due_date',invoice.due_date,
                'period_start',invoice.billing_period_start,
                'period_end',invoice.billing_period_end,
                'rent_usd_cents',COALESCE(sum(line.amount_usd_cents)
                    FILTER (WHERE line.category='RENT'),0),
                'service_usd_cents',COALESCE(sum(line.amount_usd_cents)
                    FILTER (WHERE line.category='SERVICE_CHARGES'),0),
                'total_usd_cents',invoice.original_total_usd_cents,
                'service_line_count',count(*)
                    FILTER (WHERE line.category='SERVICE_CHARGES'),
                'status',invoice.status
            )
            FROM app.invoices AS invoice
            JOIN app.leases AS lease ON lease.id=invoice.lease_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            LEFT JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
            WHERE invoice.id=p_invoice_id
            GROUP BY invoice.id,unit.property_id
        $$;

        CREATE FUNCTION app.serialize_rent_service_property_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            v_new_property_id uuid; v_old_property_id uuid;
            v_property_id uuid; v_key text;
        BEGIN
            IF TG_TABLE_NAME='property_services' THEN
                IF TG_OP<>'DELETE' THEN v_new_property_id:=NEW.property_id; END IF;
                IF TG_OP<>'INSERT' THEN v_old_property_id:=OLD.property_id; END IF;
            ELSIF TG_TABLE_NAME='leases' THEN
                IF TG_OP<>'DELETE' THEN
                    SELECT unit.property_id INTO v_new_property_id
                    FROM app.units AS unit WHERE unit.id=NEW.unit_id;
                END IF;
                IF TG_OP<>'INSERT' THEN
                    SELECT unit.property_id INTO v_old_property_id
                    FROM app.units AS unit WHERE unit.id=OLD.unit_id;
                END IF;
            ELSIF TG_TABLE_NAME='occupancies' THEN
                IF TG_OP<>'DELETE' THEN
                    SELECT unit.property_id INTO v_new_property_id
                    FROM app.leases AS lease
                    JOIN app.units AS unit ON unit.id=lease.unit_id
                    WHERE lease.id=NEW.lease_id;
                END IF;
                IF TG_OP<>'INSERT' THEN
                    SELECT unit.property_id INTO v_old_property_id
                    FROM app.leases AS lease
                    JOIN app.units AS unit ON unit.id=lease.unit_id
                    WHERE lease.id=OLD.lease_id;
                END IF;
            ELSE
                IF TG_OP<>'DELETE' THEN
                    SELECT service.property_id INTO v_new_property_id
                    FROM app.property_services AS service
                    WHERE service.id=NEW.property_service_id;
                END IF;
                IF TG_OP<>'INSERT' THEN
                    SELECT service.property_id INTO v_old_property_id
                    FROM app.property_services AS service
                    WHERE service.id=OLD.property_service_id;
                END IF;
            END IF;
            FOR v_property_id IN
                SELECT DISTINCT property_id
                FROM unnest(ARRAY[v_new_property_id,v_old_property_id]) AS ids(property_id)
                WHERE property_id IS NOT NULL ORDER BY property_id
            LOOP
                v_key:='invoice-property-service:' || v_property_id::text;
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(v_key,0)
                );
                PERFORM app.advance_invoice_serialization_guard(v_key);
            END LOOP;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER property_services_00_serialize_invoice_property_source
            BEFORE INSERT OR UPDATE OR DELETE ON app.property_services
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();
        CREATE TRIGGER leases_00_property_service_source
            BEFORE INSERT OR UPDATE ON app.leases
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();
        CREATE TRIGGER occupancies_00_property_service_source
            BEFORE INSERT OR UPDATE OR DELETE ON app.occupancies
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();
        CREATE TRIGGER service_rates_00_property_source
            BEFORE INSERT ON app.service_rates
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();
        CREATE TRIGGER property_service_approval_periods_00_property_source
            BEFORE INSERT OR UPDATE ON app.property_service_approval_periods
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();
        CREATE TRIGGER lease_service_terms_00_property_source
            BEFORE INSERT ON app.lease_service_terms
            FOR EACH ROW EXECUTE FUNCTION app.serialize_rent_service_property_source();

        CREATE OR REPLACE FUNCTION app.stamp_invoice_detail_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_TABLE_NAME='invoice_lines' THEN
                IF TG_OP='INSERT' THEN NEW.last_changed_by:=NEW.created_by; END IF;
                NEW.last_changed_at:=GREATEST(statement_timestamp(),NEW.created_at);
            ELSE
                IF TG_OP='INSERT' THEN
                    -- Preserve an explicit durable source cutoff. Callers that
                    -- omit created_at still receive the column's statement-time default.
                    NEW.last_changed_by:=NEW.created_by;
                END IF;
                NEW.last_changed_at:=GREATEST(statement_timestamp(),NEW.created_at);
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.generate_rent_service_invoice(
            p_property_id uuid,p_idempotency_key uuid,p_request_digest text,
            p_invoice_id uuid,p_invoice_number text,p_lease_id uuid,
            p_source_occupancy_id uuid,p_billing_kind text,p_period_start date,
            p_issued_at timestamptz,p_actor_id uuid,
            p_originating_billing_run_attempt_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
        DECLARE
            v_replay app.rent_billing_commands%ROWTYPE;
            v_lease app.leases%ROWTYPE;
            v_customer_id uuid; v_occupancy_date date;
            v_occupancy_created_at timestamptz; v_occupancy_updated_at timestamptz;
            v_period_end date; v_first_month_end date; v_invoice_date date; v_due_date date;
            v_source_selection_cutoff timestamptz;
            v_completed_at timestamptz;
            v_existing_invoice_id uuid; v_result jsonb;
            v_current_result jsonb;
            v_existing_status text; v_existing_billing_kind text;
            v_existing_period_start date; v_existing_period_end date;
            v_existing_source_occupancy_id uuid; v_existing_run_attempt_id uuid;
            v_provenance_run_attempt_id uuid;
            v_existing_invoice_date date; v_existing_due_date date;
            v_existing_primary_category text;
            v_rent_line_id uuid; v_service_line_id uuid;
            v_rent_first bigint; v_rent_second bigint:=0; v_rent_total bigint;
            v_service_first bigint:=0; v_service_second bigint:=0; v_service_total bigint:=0;
            v_first_days smallint; v_first_calendar_days smallint;
            v_second_start date; v_second_days smallint; v_second_calendar_days smallint;
            v_service_id_1 uuid; v_service_rate_id_1 uuid;
            v_service_rate_1 bigint; v_service_rate_2 bigint;
            v_service_term_id_1 uuid; v_service_approval_id_1 uuid;
            v_service_id_2 uuid; v_service_rate_id_2 uuid;
            v_service_term_id_2 uuid; v_service_approval_id_2 uuid;
            v_next_line_sequence smallint:=2;
            v_service_lock_id uuid;
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation')<>'read committed' THEN
                RAISE EXCEPTION 'Rent billing requires READ COMMITTED isolation'
                    USING ERRCODE='25001';
            END IF;
            IF p_property_id IS NULL OR p_idempotency_key IS NULL OR p_invoice_id IS NULL
                OR p_lease_id IS NULL OR p_actor_id IS NULL OR p_period_start IS NULL
                OR p_issued_at IS NULL OR p_request_digest IS NULL
                OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_invoice_number IS NULL OR length(p_invoice_number)>100
                OR length(btrim(p_invoice_number))=0 OR p_invoice_number<>btrim(p_invoice_number)
                OR p_billing_kind IS NULL OR p_billing_kind NOT IN ('INITIAL','RECURRING')
                OR (p_billing_kind='INITIAL' AND p_source_occupancy_id IS NULL)
                OR (p_billing_kind='RECURRING' AND p_source_occupancy_id IS NOT NULL)
            THEN RAISE EXCEPTION 'Rent billing command evidence is invalid'
                USING ERRCODE='22023'; END IF;

            IF p_issued_at>clock_timestamp() THEN
                RAISE EXCEPTION 'Rent billing business issuance time must not be in the future'
                    USING ERRCODE='22023';
            END IF;

            PERFORM app.assert_active_financial_actor(p_actor_id,p_property_id);

            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'rent-billing-command:' || p_property_id::text || ':' || p_actor_id::text
                    || ':' || p_idempotency_key::text,0
            ));
            SELECT * INTO v_replay FROM app.rent_billing_commands
            WHERE property_id=p_property_id AND actor_id=p_actor_id
              AND idempotency_key=p_idempotency_key;
            IF FOUND THEN
                IF v_replay.request_digest IS DISTINCT FROM p_request_digest
                    OR v_replay.requested_invoice_id IS DISTINCT FROM p_invoice_id
                    OR v_replay.requested_invoice_number IS DISTINCT FROM p_invoice_number
                    OR v_replay.lease_id IS DISTINCT FROM p_lease_id
                    OR v_replay.source_occupancy_id IS DISTINCT FROM p_source_occupancy_id
                    OR v_replay.billing_kind IS DISTINCT FROM p_billing_kind
                    OR v_replay.period_start IS DISTINCT FROM p_period_start
                    OR v_replay.requested_issued_at IS DISTINCT FROM p_issued_at
                    OR v_replay.originating_billing_run_attempt_id
                        IS DISTINCT FROM p_originating_billing_run_attempt_id
                THEN
                    RAISE EXCEPTION 'Rent billing idempotency key conflicts with another request'
                        USING ERRCODE='23505';
                END IF;
                RETURN v_replay.result_snapshot;
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'invoice-property-service:' || p_property_id::text,0
            ));
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('rent:' || p_lease_id::text,0)
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('invoice-lease:' || p_lease_id::text,0)
            );
            SELECT lease.* INTO v_lease
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE lease.id=p_lease_id AND unit.property_id=p_property_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found in Property scope'
                USING ERRCODE='P0002'; END IF;
            IF v_lease.status NOT IN ('SIGNED','TERMINATED')
                OR v_lease.monthly_rent_usd_cents IS NULL
            THEN RAISE EXCEPTION 'Rent billing requires an applicable signed Lease'
                USING ERRCODE='55000'; END IF;
            v_customer_id:=v_lease.primary_tenant_id;
            v_invoice_date:=timezone('Asia/Phnom_Penh',p_issued_at)::date;

            IF p_billing_kind='INITIAL' THEN
                SELECT occupancy.move_in_date,occupancy.created_at,occupancy.updated_at
                INTO v_occupancy_date,v_occupancy_created_at,v_occupancy_updated_at
                FROM app.occupancies AS occupancy
                WHERE occupancy.id=p_source_occupancy_id
                  AND occupancy.lease_id=p_lease_id
                  AND occupancy.customer_id=v_customer_id;
                IF NOT FOUND OR v_occupancy_date<>p_period_start
                    OR v_invoice_date<>v_occupancy_date
                THEN RAISE EXCEPTION 'Initial Rent billing source is invalid'
                    USING ERRCODE='22023'; END IF;
                v_first_month_end:=(date_trunc('month',v_occupancy_date)
                    + interval '1 month - 1 day')::date;
                v_period_end:=v_first_month_end;
                IF extract(day FROM v_occupancy_date)>=21 THEN
                    v_period_end:=(date_trunc('month',v_occupancy_date)
                        + interval '2 months - 1 day')::date;
                END IF;
                v_due_date:=v_occupancy_date+7;
            ELSE
                IF p_period_start<>date_trunc('month',p_period_start)::date THEN
                    RAISE EXCEPTION 'Recurring Rent must begin on the first calendar day'
                        USING ERRCODE='22023'; END IF;
                v_first_month_end:=(date_trunc('month',p_period_start)
                    + interval '1 month - 1 day')::date;
                v_period_end:=v_first_month_end;
                v_invoice_date:=(date_trunc('month',p_period_start)
                    - interval '1 month' + interval '24 days')::date;
                IF timezone('Asia/Phnom_Penh',p_issued_at)::date<>v_invoice_date THEN
                    RAISE EXCEPTION 'Recurring Rent billing source is invalid'
                    USING ERRCODE='22023'; END IF;
                v_due_date:=p_period_start+4;
            END IF;

            -- The Property-level lock prevents new Service identities and all
            -- rate, approval, and Lease-term source writes. Lock and re-read the
            -- complete stable Service set before fixing the single cutoff.
            FOR v_service_lock_id IN
                SELECT service.id FROM app.property_services AS service
                WHERE service.property_id=p_property_id ORDER BY service.id
            LOOP
                PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                    'invoice-service:' || v_service_lock_id::text,0
                ));
            END LOOP;

            -- Do not acquire Lease or Occupancy tuple locks while holding the
            -- Property boundary: PostgreSQL acquires an UPDATE tuple lock before
            -- its BEFORE ROW trigger can wait on that boundary, so doing so here
            -- would create the reverse edge of a deadlock. Under READ COMMITTED,
            -- the Property advisory lock makes these plain reads a stable
            -- serialization point: committed pre-boundary evidence is visible,
            -- while in-flight source writes finish after this billing transaction
            -- and must pass the existing issued-Invoice invalidation guards.
            -- Capture the one durable source/issuance instant only after the
            -- stable sources have been re-read.
            v_source_selection_cutoff:=clock_timestamp();
            IF v_lease.signed_at IS NULL
                OR v_lease.signed_at>v_source_selection_cutoff
                OR v_lease.updated_at>v_source_selection_cutoff
                OR (
                    p_billing_kind='INITIAL'
                    AND (
                        v_occupancy_created_at>v_source_selection_cutoff
                        OR v_occupancy_updated_at>v_source_selection_cutoff
                    )
                )
                OR (
                    p_billing_kind='RECURRING'
                    AND EXISTS (
                        SELECT 1 FROM app.occupancies AS occupancy
                        WHERE occupancy.lease_id=p_lease_id
                          AND occupancy.updated_at>v_source_selection_cutoff
                    )
                )
            THEN
                RAISE EXCEPTION 'Rent billing source chronology is invalid'
                    USING ERRCODE='22023';
            END IF;

            IF v_lease.start_date>p_period_start OR v_lease.end_date<v_period_end
                OR (
                    v_lease.status='TERMINATED'
                    AND v_lease.actual_termination_date<v_period_end
                )
            THEN
                RAISE EXCEPTION 'Rent billing period is outside contractual Lease coverage'
                    USING ERRCODE='22023';
            END IF;

            IF p_originating_billing_run_attempt_id IS NOT NULL THEN
                PERFORM 1
                FROM app.billing_run_attempts AS attempt
                JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                JOIN app.billing_run_eligible_sources AS eligible
                  ON eligible.billing_run_id=run.id
                WHERE attempt.id=p_originating_billing_run_attempt_id
                  AND attempt.outcome='RUNNING' AND run.status='RUNNING'
                  AND attempt.started_at<=v_source_selection_cutoff
                  AND run.property_id=p_property_id
                  AND run.run_kind='RENT'
                  AND run.business_date=v_invoice_date
                  AND run.period_start=p_period_start
                  AND run.period_end=v_period_end
                  AND run.system_actor_id=p_actor_id
                  AND eligible.source_kind='LEASE_PERIOD'
                  AND eligible.source_id=p_lease_id
                  AND eligible.source_period_start=p_period_start
                  AND eligible.source_period_end=v_period_end
                FOR UPDATE OF attempt,run;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Billing Run attempt is outside Rent command scope'
                        USING ERRCODE='55000';
                END IF;
            END IF;

            SELECT invoice.id,invoice.status,invoice.rent_billing_kind,
                invoice.billing_period_start,invoice.billing_period_end,
                invoice.source_occupancy_id,invoice.originating_billing_run_attempt_id,
                invoice.invoice_date,invoice.due_date,invoice.primary_category
            INTO v_existing_invoice_id,v_existing_status,v_existing_billing_kind,
                v_existing_period_start,v_existing_period_end,
                v_existing_source_occupancy_id,v_existing_run_attempt_id,
                v_existing_invoice_date,v_existing_due_date,v_existing_primary_category
            FROM app.invoices AS invoice
            WHERE invoice.lease_id=p_lease_id
              AND EXISTS (
                  SELECT 1 FROM app.invoice_lines AS line
                  WHERE line.invoice_id=invoice.id AND line.category='RENT'
                    AND line.source_lease_id=p_lease_id
              )
              AND daterange(invoice.billing_period_start,invoice.billing_period_end,'[]')
                  && daterange(p_period_start,v_period_end,'[]')
              AND invoice.status<>'VOID'
            ORDER BY invoice.id LIMIT 1 FOR UPDATE OF invoice;
            IF FOUND THEN
                IF v_existing_billing_kind IS DISTINCT FROM p_billing_kind
                    OR v_existing_period_start IS DISTINCT FROM p_period_start
                    OR v_existing_period_end IS DISTINCT FROM v_period_end
                    OR v_existing_source_occupancy_id IS DISTINCT FROM p_source_occupancy_id
                    OR v_existing_invoice_date IS DISTINCT FROM v_invoice_date
                    OR v_existing_due_date IS DISTINCT FROM v_due_date
                    OR v_existing_primary_category IS DISTINCT FROM 'RENT'
                THEN
                    RAISE EXCEPTION 'Non-identical overlapping Rent Invoice conflicts'
                        USING ERRCODE='23P01';
                END IF;
                IF v_existing_status='DRAFT' THEN
                    RAISE EXCEPTION 'Overlapping Rent Invoice is still DRAFT'
                        USING ERRCODE='23P01';
                END IF;
                SELECT command.result_snapshot,command.originating_billing_run_attempt_id,
                    command.source_selection_cutoff
                INTO v_result,v_provenance_run_attempt_id,v_source_selection_cutoff
                FROM app.rent_billing_commands AS command
                WHERE command.invoice_id=v_existing_invoice_id
                  AND command.property_id=p_property_id
                  AND command.lease_id=p_lease_id
                  AND command.billing_kind=p_billing_kind
                  AND command.period_start=p_period_start
                  AND command.period_end=v_period_end
                ORDER BY command.id LIMIT 1;
                IF NOT FOUND
                    OR v_existing_run_attempt_id IS DISTINCT FROM v_provenance_run_attempt_id
                    OR (v_result->>'invoice_id')::uuid<>v_existing_invoice_id
                    OR (v_result->>'property_id')::uuid<>p_property_id
                    OR (v_result->>'lease_id')::uuid<>p_lease_id
                    OR v_result->>'billing_kind'<>p_billing_kind
                    OR (v_result->>'period_start')::date<>p_period_start
                    OR (v_result->>'period_end')::date<>v_period_end
                THEN
                    RAISE EXCEPTION 'Overlapping Rent Invoice lacks compatible billing provenance'
                        USING ERRCODE='23P01';
                END IF;
                v_current_result:=app.rent_invoice_snapshot(v_existing_invoice_id);
                IF v_current_result->>'customer_id' IS DISTINCT FROM v_result->>'customer_id'
                    OR v_current_result->>'rent_usd_cents'
                        IS DISTINCT FROM v_result->>'rent_usd_cents'
                    OR v_current_result->>'service_usd_cents'
                        IS DISTINCT FROM v_result->>'service_usd_cents'
                    OR v_current_result->>'total_usd_cents'
                        IS DISTINCT FROM v_result->>'total_usd_cents'
                    OR v_current_result->>'service_line_count'
                        IS DISTINCT FROM v_result->>'service_line_count'
                THEN
                    RAISE EXCEPTION 'Overlapping Rent Invoice evidence changed after generation'
                        USING ERRCODE='23P01';
                END IF;
                v_completed_at:=clock_timestamp();
                INSERT INTO app.rent_billing_commands(
                    property_id,actor_id,idempotency_key,request_digest,invoice_id,
                    requested_invoice_id,requested_invoice_number,lease_id,
                    source_occupancy_id,billing_kind,period_start,period_end,
                    requested_issued_at,source_selection_cutoff,
                    originating_billing_run_attempt_id,
                    result_snapshot,completed_at
                ) VALUES (
                    p_property_id,p_actor_id,p_idempotency_key,p_request_digest,
                    v_existing_invoice_id,p_invoice_id,p_invoice_number,p_lease_id,
                    p_source_occupancy_id,p_billing_kind,p_period_start,v_period_end,
                    p_issued_at,v_source_selection_cutoff,
                    p_originating_billing_run_attempt_id,v_result,v_completed_at
                );
                RETURN v_result;
            END IF;

            IF p_billing_kind='RECURRING'
                AND NOT app.lease_is_billable_for_recurring_period(
                    p_lease_id,p_period_start,v_period_end,v_source_selection_cutoff
                )
            THEN RAISE EXCEPTION 'Recurring Rent billing source is invalid'
                USING ERRCODE='22023'; END IF;

            v_first_days:=(v_first_month_end-p_period_start+1)::smallint;
            v_first_calendar_days:=extract(day FROM v_first_month_end)::smallint;
            v_rent_first:=app.calculate_prorated_monthly_usd_cents(
                v_lease.monthly_rent_usd_cents,p_period_start,v_first_month_end
            );
            IF v_period_end>v_first_month_end THEN
                v_second_start:=v_first_month_end+1;
                v_second_days:=extract(day FROM v_period_end)::smallint;
                v_second_calendar_days:=v_second_days;
                v_rent_second:=v_lease.monthly_rent_usd_cents;
            END IF;
            v_rent_total:=v_rent_first+v_rent_second;

            IF EXISTS (
                SELECT 1 FROM app.property_services AS service
                JOIN app.lease_service_terms AS term
                  ON term.property_service_id=service.id AND term.lease_id=p_lease_id
                JOIN app.property_service_approval_periods AS approval
                  ON approval.id=term.service_approval_period_id
                WHERE service.property_id=p_property_id
                  AND service.service_code='TRASH_COLLECTION'
                  AND service.configured_at<=v_source_selection_cutoff
                  AND term.recorded_at<=v_source_selection_cutoff
                  AND approval.approved_at<=v_source_selection_cutoff
                  AND term.applicable_from<=v_first_month_end
                  AND COALESCE(term.applicable_through,v_first_month_end)>=p_period_start
                  AND approval.effective_from<=v_first_month_end
                  AND COALESCE(approval.effective_through,v_first_month_end)>=p_period_start
            ) AND NOT EXISTS (
                SELECT 1 FROM app.property_services AS service
                JOIN app.lease_service_terms AS term
                  ON term.property_service_id=service.id AND term.lease_id=p_lease_id
                JOIN app.property_service_approval_periods AS approval
                  ON approval.id=term.service_approval_period_id
                WHERE service.property_id=p_property_id
                  AND service.service_code='TRASH_COLLECTION'
                  AND service.configured_at<=v_source_selection_cutoff
                  AND term.recorded_at<=v_source_selection_cutoff
                  AND approval.approved_at<=v_source_selection_cutoff
                  AND p_period_start>=term.applicable_from
                  AND v_first_month_end<=COALESCE(term.applicable_through,v_first_month_end)
                  AND p_period_start>=approval.effective_from
                  AND v_first_month_end<=COALESCE(approval.effective_through,v_first_month_end)
            ) THEN
                RAISE EXCEPTION 'Partial-month Trash Collection configuration is unsupported'
                    USING ERRCODE='22023';
            END IF;

            SELECT service.id,term.id,approval.id
            INTO v_service_id_1,v_service_term_id_1,v_service_approval_id_1
            FROM app.property_services AS service
            JOIN app.lease_service_terms AS term
              ON term.property_service_id=service.id AND term.lease_id=p_lease_id
            JOIN app.property_service_approval_periods AS approval
              ON approval.id=term.service_approval_period_id
            WHERE service.property_id=p_property_id
              AND service.service_code='TRASH_COLLECTION'
              AND service.configured_at<=v_source_selection_cutoff
              AND term.recorded_at<=v_source_selection_cutoff
              AND approval.approved_at<=v_source_selection_cutoff
              AND p_period_start>=term.applicable_from
              AND v_first_month_end<=COALESCE(term.applicable_through,v_first_month_end)
              AND p_period_start>=approval.effective_from
              AND v_first_month_end<=COALESCE(approval.effective_through,v_first_month_end)
            ORDER BY term.applicable_from DESC,term.id DESC LIMIT 1;
            IF v_service_id_1 IS NOT NULL THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended('invoice-service:' || v_service_id_1::text,0)
                );
                SELECT rate.id,rate.monthly_rate_usd_cents
                INTO v_service_rate_id_1,v_service_rate_1
                FROM app.service_rates AS rate
                WHERE rate.property_service_id=v_service_id_1
                  AND rate.effective_date<=p_period_start
                  AND rate.occurred_at<=v_source_selection_cutoff
                ORDER BY rate.effective_date DESC,rate.id DESC LIMIT 1;
                IF NOT FOUND THEN RAISE EXCEPTION 'Applicable Trash Collection rate is missing'
                    USING ERRCODE='55000'; END IF;
                v_service_first:=app.calculate_prorated_monthly_usd_cents(
                    v_service_rate_1,p_period_start,v_first_month_end
                );
            END IF;
            IF v_second_start IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1 FROM app.property_services AS service
                    JOIN app.lease_service_terms AS term
                      ON term.property_service_id=service.id AND term.lease_id=p_lease_id
                    JOIN app.property_service_approval_periods AS approval
                      ON approval.id=term.service_approval_period_id
                    WHERE service.property_id=p_property_id
                      AND service.service_code='TRASH_COLLECTION'
                      AND service.configured_at<=v_source_selection_cutoff
                      AND term.recorded_at<=v_source_selection_cutoff
                      AND approval.approved_at<=v_source_selection_cutoff
                      AND term.applicable_from<=v_period_end
                      AND COALESCE(term.applicable_through,v_period_end)>=v_second_start
                      AND approval.effective_from<=v_period_end
                      AND COALESCE(approval.effective_through,v_period_end)>=v_second_start
                ) AND NOT EXISTS (
                    SELECT 1 FROM app.property_services AS service
                    JOIN app.lease_service_terms AS term
                      ON term.property_service_id=service.id AND term.lease_id=p_lease_id
                    JOIN app.property_service_approval_periods AS approval
                      ON approval.id=term.service_approval_period_id
                    WHERE service.property_id=p_property_id
                      AND service.service_code='TRASH_COLLECTION'
                      AND service.configured_at<=v_source_selection_cutoff
                      AND term.recorded_at<=v_source_selection_cutoff
                      AND approval.approved_at<=v_source_selection_cutoff
                      AND v_second_start>=term.applicable_from
                      AND v_period_end<=COALESCE(term.applicable_through,v_period_end)
                      AND v_second_start>=approval.effective_from
                      AND v_period_end<=COALESCE(approval.effective_through,v_period_end)
                ) THEN
                    RAISE EXCEPTION 'Partial-month Trash Collection configuration is unsupported'
                        USING ERRCODE='22023';
                END IF;
                SELECT service.id,term.id,approval.id
                INTO v_service_id_2,v_service_term_id_2,v_service_approval_id_2
                FROM app.property_services AS service
                JOIN app.lease_service_terms AS term
                  ON term.property_service_id=service.id AND term.lease_id=p_lease_id
                JOIN app.property_service_approval_periods AS approval
                  ON approval.id=term.service_approval_period_id
                WHERE service.property_id=p_property_id
                  AND service.service_code='TRASH_COLLECTION'
                  AND service.configured_at<=v_source_selection_cutoff
                  AND term.recorded_at<=v_source_selection_cutoff
                  AND approval.approved_at<=v_source_selection_cutoff
                  AND v_second_start>=term.applicable_from
                  AND v_period_end<=COALESCE(term.applicable_through,v_period_end)
                  AND v_second_start>=approval.effective_from
                  AND v_period_end<=COALESCE(approval.effective_through,v_period_end)
                ORDER BY term.applicable_from DESC,term.id DESC LIMIT 1;
                IF v_service_id_2 IS NOT NULL THEN
                    PERFORM pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(
                            'invoice-service:' || v_service_id_2::text,0
                        )
                    );
                    SELECT rate.id,rate.monthly_rate_usd_cents
                    INTO v_service_rate_id_2,v_service_rate_2
                    FROM app.service_rates AS rate
                    WHERE rate.property_service_id=v_service_id_2
                      AND rate.effective_date<=v_second_start
                      AND rate.occurred_at<=v_source_selection_cutoff
                    ORDER BY rate.effective_date DESC,rate.id DESC LIMIT 1;
                    IF NOT FOUND THEN RAISE EXCEPTION 'Following-month Trash rate is missing'
                        USING ERRCODE='55000'; END IF;
                    v_service_second:=v_service_rate_2;
                END IF;
            END IF;
            v_service_total:=v_service_first+v_service_second;

            INSERT INTO app.invoices(
                id,invoice_number,customer_id,lease_id,source_occupancy_id,
                primary_category,status,invoice_date,due_date,billing_period_start,
                billing_period_end,rent_billing_kind,original_total_usd_cents,
                due_date_rule,due_date_source,created_at,created_by,updated_at,updated_by,
                originating_billing_run_attempt_id
            ) VALUES (
                p_invoice_id,p_invoice_number,v_customer_id,p_lease_id,p_source_occupancy_id,
                'RENT','DRAFT',v_invoice_date,v_due_date,p_period_start,v_period_end,
                p_billing_kind,v_rent_total+v_service_total,
                CASE p_billing_kind WHEN 'INITIAL' THEN 'INITIAL_RENT_SEVEN_DAYS'
                    ELSE 'RECURRING_RENT_FIFTH' END,
                CASE p_billing_kind WHEN 'INITIAL' THEN 'BR-RENT-015'
                    ELSE 'BR-RENT-018' END,
                v_source_selection_cutoff,p_actor_id,
                v_source_selection_cutoff,p_actor_id,
                p_originating_billing_run_attempt_id
            );

            v_rent_line_id:=pg_catalog.gen_random_uuid();
            INSERT INTO app.invoice_lines(
                id,invoice_id,line_sequence,category,description,amount_usd_cents,
                period_start,period_end,source_lease_id,contractual_monthly_usd_cents,
                billable_days,calendar_days,calculation_trace,created_at,created_by
            ) VALUES (
                v_rent_line_id,p_invoice_id,1,'RENT','Rent',v_rent_total,
                p_period_start,v_period_end,p_lease_id,v_lease.monthly_rent_usd_cents,
                CASE WHEN v_second_start IS NULL THEN v_first_days ELSE NULL END,
                CASE WHEN v_second_start IS NULL THEN v_first_calendar_days ELSE NULL END,
                jsonb_build_object(
                    'formula','monthly_usd_cents * inclusive_billable_days / calendar_days',
                    'rounding','half_up_final_usd_cent','billing_kind',p_billing_kind
                ),v_source_selection_cutoff,p_actor_id
            );
            INSERT INTO app.invoice_line_calculation_components(
                id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
                contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,
                calculation_trace,created_at,created_by
            ) VALUES (
                pg_catalog.gen_random_uuid(),v_rent_line_id,1,
                CASE WHEN p_billing_kind='RECURRING' THEN 'FULL_RECURRING_MONTH'
                    ELSE 'PRORATED_MOVE_IN_MONTH' END,
                p_period_start,v_first_month_end,v_lease.monthly_rent_usd_cents,
                v_first_days,v_first_calendar_days,v_rent_first,
                jsonb_build_object('monthly_usd_cents',v_lease.monthly_rent_usd_cents,
                    'billable_days',v_first_days,'calendar_days',v_first_calendar_days,
                    'amount_usd_cents',v_rent_first),v_source_selection_cutoff,p_actor_id
            );
            IF v_second_start IS NOT NULL THEN
                INSERT INTO app.invoice_line_calculation_components(
                    id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
                    contractual_monthly_usd_cents,billable_days,calendar_days,amount_usd_cents,
                    calculation_trace,created_at,created_by
                ) VALUES (
                    pg_catalog.gen_random_uuid(),v_rent_line_id,2,'FULL_FOLLOWING_MONTH',
                    v_second_start,v_period_end,v_lease.monthly_rent_usd_cents,
                    v_second_days,v_second_calendar_days,v_rent_second,
                    jsonb_build_object('monthly_usd_cents',v_lease.monthly_rent_usd_cents,
                        'billable_days',v_second_days,'calendar_days',v_second_calendar_days,
                        'amount_usd_cents',v_rent_second),v_source_selection_cutoff,p_actor_id
                );
            END IF;

            IF v_service_id_1 IS NOT NULL THEN
                v_service_line_id:=pg_catalog.gen_random_uuid();
                INSERT INTO app.invoice_lines(
                    id,invoice_id,line_sequence,category,description,amount_usd_cents,
                    period_start,period_end,source_lease_id,property_service_id,
                    service_rate_id,lease_service_term_id,service_approval_period_id,
                    contractual_monthly_usd_cents,billable_days,calendar_days,
                    calculation_trace,created_at,created_by
                ) VALUES (
                    v_service_line_id,p_invoice_id,v_next_line_sequence,
                    'SERVICE_CHARGES','Trash Collection',v_service_first,
                    p_period_start,v_first_month_end,p_lease_id,v_service_id_1,
                    v_service_rate_id_1,v_service_term_id_1,v_service_approval_id_1,
                    v_service_rate_1,v_first_days,v_first_calendar_days,
                    jsonb_build_object('service_code','TRASH_COLLECTION',
                        'formula','monthly_usd_cents * inclusive_billable_days / calendar_days',
                        'rounding','half_up_final_usd_cent'),
                    v_source_selection_cutoff,p_actor_id
                );
                INSERT INTO app.invoice_line_calculation_components(
                    id,invoice_line_id,component_sequence,component_kind,period_start,period_end,
                    service_rate_id,service_monthly_rate_usd_cents,billable_days,calendar_days,
                    amount_usd_cents,calculation_trace,created_at,created_by
                ) VALUES (
                    pg_catalog.gen_random_uuid(),v_service_line_id,1,
                    CASE WHEN p_billing_kind='RECURRING' THEN 'FULL_RECURRING_MONTH'
                        ELSE 'PRORATED_MOVE_IN_MONTH' END,
                    p_period_start,v_first_month_end,v_service_rate_id_1,v_service_rate_1,
                    v_first_days,v_first_calendar_days,v_service_first,
                    jsonb_build_object('service_rate_id',v_service_rate_id_1,
                        'monthly_usd_cents',v_service_rate_1,'billable_days',v_first_days,
                        'calendar_days',v_first_calendar_days,
                        'amount_usd_cents',v_service_first),
                    v_source_selection_cutoff,p_actor_id
                );
                v_next_line_sequence:=v_next_line_sequence+1;
            END IF;
            IF v_service_id_2 IS NOT NULL THEN
                v_service_line_id:=pg_catalog.gen_random_uuid();
                INSERT INTO app.invoice_lines(
                    id,invoice_id,line_sequence,category,description,amount_usd_cents,
                    period_start,period_end,source_lease_id,property_service_id,
                    service_rate_id,lease_service_term_id,service_approval_period_id,
                    contractual_monthly_usd_cents,billable_days,calendar_days,
                    calculation_trace,created_at,created_by
                ) VALUES (
                    v_service_line_id,p_invoice_id,v_next_line_sequence,
                    'SERVICE_CHARGES','Trash Collection',v_service_second,
                    v_second_start,v_period_end,p_lease_id,v_service_id_2,
                    v_service_rate_id_2,v_service_term_id_2,v_service_approval_id_2,
                    v_service_rate_2,v_second_days,v_second_calendar_days,
                    jsonb_build_object('service_code','TRASH_COLLECTION',
                        'formula','monthly_usd_cents * inclusive_billable_days / calendar_days',
                        'rounding','half_up_final_usd_cent'),
                    v_source_selection_cutoff,p_actor_id
                );
                INSERT INTO app.invoice_line_calculation_components(
                    id,invoice_line_id,component_sequence,component_kind,period_start,
                    period_end,service_rate_id,service_monthly_rate_usd_cents,billable_days,
                    calendar_days,amount_usd_cents,calculation_trace,created_at,created_by
                ) VALUES (
                    pg_catalog.gen_random_uuid(),v_service_line_id,1,'FULL_FOLLOWING_MONTH',
                    v_second_start,v_period_end,v_service_rate_id_2,v_service_rate_2,
                    v_second_days,v_second_calendar_days,v_service_second,
                    jsonb_build_object('service_rate_id',v_service_rate_id_2,
                        'monthly_usd_cents',v_service_rate_2,'billable_days',v_second_days,
                        'calendar_days',v_second_calendar_days,
                        'amount_usd_cents',v_service_second),
                    v_source_selection_cutoff,p_actor_id
                );
            END IF;

            UPDATE app.invoices SET status='UNPAID',
                issued_at=v_source_selection_cutoff,issued_by=p_actor_id,
                version=version+1,updated_at=v_source_selection_cutoff,updated_by=p_actor_id
            WHERE id=p_invoice_id;
            v_result:=app.rent_invoice_snapshot(p_invoice_id);
            v_completed_at:=clock_timestamp();
            INSERT INTO app.rent_billing_commands(
                property_id,actor_id,idempotency_key,request_digest,invoice_id,
                requested_invoice_id,requested_invoice_number,lease_id,
                source_occupancy_id,billing_kind,period_start,period_end,
                requested_issued_at,source_selection_cutoff,
                originating_billing_run_attempt_id,
                result_snapshot,completed_at
            ) VALUES (
                p_property_id,p_actor_id,p_idempotency_key,p_request_digest,p_invoice_id,
                p_invoice_id,p_invoice_number,p_lease_id,p_source_occupancy_id,
                p_billing_kind,p_period_start,v_period_end,p_issued_at,
                v_source_selection_cutoff,
                p_originating_billing_run_attempt_id,v_result,v_completed_at
            );
            IF p_originating_billing_run_attempt_id IS NULL THEN
                SET CONSTRAINTS ALL IMMEDIATE;
            END IF;
            RETURN v_result;
        END $$;

        CREATE TRIGGER rent_billing_commands_append_only
            BEFORE UPDATE OR DELETE ON app.rent_billing_commands
            FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation();
        CREATE TRIGGER rent_billing_commands_reject_truncate
            BEFORE TRUNCATE ON app.rent_billing_commands
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_storage_truncate();
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.rent_billing_commands "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.rent_billing_commands TO prm_runtime, prm_financial")
    for function in (
        "app.calculate_prorated_monthly_usd_cents(bigint,date,date)",
        "app.rent_invoice_snapshot(uuid)",
        "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
        "timestamp with time zone,uuid,uuid)",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.calculate_prorated_monthly_usd_cents(bigint,date,date) "
        "TO prm_runtime, prm_financial"
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.rent_invoice_snapshot(uuid) TO prm_financial")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.generate_rent_service_invoice(uuid,uuid,text,uuid,text,uuid,uuid,text,date,"
        "timestamp with time zone,uuid,uuid) TO prm_financial"
    )


def downgrade() -> None:
    """Refuse rollback that could erase permanent billing-command evidence."""
    raise RuntimeError("Rent and Service billing is forward-only")
