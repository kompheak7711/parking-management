"""Add effective-dated configuration and append-preserved rate history."""

from alembic import op

revision = "20260825_17"
down_revision = "20260824_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-027 configuration persistence stores."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        CREATE TABLE app.property_services (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL
                REFERENCES app.properties(id) ON DELETE RESTRICT,
            service_code text NOT NULL,
            display_name text NOT NULL,
            configured_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            configured_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT property_services_code_nonblank
                CHECK (length(btrim(service_code)) > 0),
            CONSTRAINT property_services_code_normalized
                CHECK (service_code = btrim(service_code)),
            CONSTRAINT property_services_name_nonblank
                CHECK (length(btrim(display_name)) > 0),
            CONSTRAINT property_services_name_normalized
                CHECK (display_name = btrim(display_name)),
            CONSTRAINT property_services_configuration_provenance
                CHECK (
                    configured_at = created_at
                    AND configured_by = created_by
                    AND updated_at >= created_at
                ),
            CONSTRAINT property_services_property_code_unique
                UNIQUE (property_id, service_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.service_rates (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_service_id uuid NOT NULL
                REFERENCES app.property_services(id) ON DELETE RESTRICT,
            monthly_rate_usd_cents bigint NOT NULL
                CHECK (monthly_rate_usd_cents > 0),
            effective_date date NOT NULL,
            source_memo text,
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT service_rates_source_memo_nonblank
                CHECK (source_memo IS NULL OR length(btrim(source_memo)) > 0),
            CONSTRAINT service_rates_source_memo_normalized
                CHECK (source_memo IS NULL OR source_memo = btrim(source_memo)),
            CONSTRAINT service_rates_service_effective_unique
                UNIQUE (property_service_id, effective_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_rates_effective_selection_idx
        ON app.service_rates (property_service_id, effective_date DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE app.property_service_approval_periods (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_service_id uuid NOT NULL
                REFERENCES app.property_services(id) ON DELETE RESTRICT,
            effective_from date NOT NULL,
            effective_through date,
            approval_reference text NOT NULL,
            approved_at timestamptz NOT NULL,
            approved_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            reason text NOT NULL,
            CONSTRAINT property_service_approval_period_valid
                CHECK (
                    effective_through IS NULL
                    OR effective_through >= effective_from
                ),
            CONSTRAINT property_service_approval_reference_nonblank
                CHECK (
                    length(btrim(approval_reference)) > 0
                    AND approval_reference = btrim(approval_reference)
                ),
            CONSTRAINT property_service_approval_reason_nonblank
                CHECK (length(btrim(reason)) > 0 AND reason = btrim(reason)),
            CONSTRAINT property_service_approval_periods_no_overlap
                EXCLUDE USING gist (
                    property_service_id WITH =,
                    daterange(effective_from, effective_through, '[]') WITH &&
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX property_service_approval_selection_idx
        ON app.property_service_approval_periods (
            property_service_id, effective_from DESC
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.utility_rates (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL
                REFERENCES app.properties(id) ON DELETE RESTRICT,
            utility_type text NOT NULL
                CHECK (utility_type IN ('ELECTRICITY', 'WATER')),
            measurement_unit_code text NOT NULL,
            rate_usd_per_unit numeric(20,8) NOT NULL
                CHECK (rate_usd_per_unit > 0),
            effective_date date NOT NULL,
            notice_at timestamptz NOT NULL,
            notice_evidence text NOT NULL,
            source_memo text,
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT utility_rates_measurement_unit_nonblank
                CHECK (
                    length(btrim(measurement_unit_code)) > 0
                    AND measurement_unit_code = btrim(measurement_unit_code)
                ),
            CONSTRAINT utility_rates_notice_precedes_effective_date
                CHECK (
                    timezone('Asia/Phnom_Penh', notice_at)::date < effective_date
                ),
            CONSTRAINT utility_rates_notice_evidence_nonblank
                CHECK (
                    length(btrim(notice_evidence)) > 0
                    AND notice_evidence = btrim(notice_evidence)
                ),
            CONSTRAINT utility_rates_source_memo_nonblank
                CHECK (source_memo IS NULL OR length(btrim(source_memo)) > 0),
            CONSTRAINT utility_rates_source_memo_normalized
                CHECK (source_memo IS NULL OR source_memo = btrim(source_memo)),
            CONSTRAINT utility_rates_property_type_effective_unique
                UNIQUE (property_id, utility_type, effective_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX utility_rates_effective_selection_idx
        ON app.utility_rates (property_id, utility_type, effective_date DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE app.exchange_rate_records (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            reference_rate_khr_per_usd numeric(20,6) NOT NULL
                CHECK (reference_rate_khr_per_usd > 0),
            markup_basis_points smallint NOT NULL CHECK (markup_basis_points = 50),
            system_rate_khr_per_usd bigint NOT NULL CHECK (system_rate_khr_per_usd > 0),
            rate_source text NOT NULL
                CHECK (rate_source IN ('ABA_AUTOMATIC', 'ABA_EQUIVALENT_MANUAL')),
            source_reference text,
            applicable_at timestamptz NOT NULL,
            entered_by uuid REFERENCES app.user_accounts(actor_id),
            channel_actual_currency text
                CHECK (channel_actual_currency IN ('USD', 'KHR')),
            channel_actual_amount_minor bigint
                CHECK (channel_actual_amount_minor > 0),
            channel_actual_usd_value_cents bigint
                CHECK (channel_actual_usd_value_cents > 0),
            channel_actual_rate_khr_per_usd numeric(20,6)
                CHECK (channel_actual_rate_khr_per_usd > 0),
            channel_transaction_reference text,
            channel_confirmed_at timestamptz,
            calculation_trace jsonb NOT NULL,
            CONSTRAINT exchange_rate_system_formula CHECK (
                system_rate_khr_per_usd
                    = ceil(reference_rate_khr_per_usd * 1.005)::bigint
            ),
            CONSTRAINT exchange_rate_manual_actor_required CHECK (
                rate_source <> 'ABA_EQUIVALENT_MANUAL' OR entered_by IS NOT NULL
            ),
            CONSTRAINT exchange_rate_source_reference_nonblank CHECK (
                source_reference IS NULL OR length(btrim(source_reference)) > 0
            ),
            CONSTRAINT exchange_rate_source_reference_normalized CHECK (
                source_reference IS NULL OR source_reference = btrim(source_reference)
            ),
            CONSTRAINT exchange_rate_channel_reference_complete CHECK (
                (
                    channel_actual_currency IS NULL
                    AND channel_actual_amount_minor IS NULL
                    AND channel_actual_usd_value_cents IS NULL
                    AND channel_actual_rate_khr_per_usd IS NULL
                    AND channel_transaction_reference IS NULL
                    AND channel_confirmed_at IS NULL
                ) OR (
                    (
                        channel_actual_currency IS NOT NULL
                        OR channel_actual_amount_minor IS NOT NULL
                        OR channel_actual_usd_value_cents IS NOT NULL
                        OR channel_actual_rate_khr_per_usd IS NOT NULL
                    )
                    AND channel_transaction_reference IS NOT NULL
                    AND length(btrim(channel_transaction_reference)) > 0
                    AND channel_transaction_reference = btrim(channel_transaction_reference)
                    AND channel_confirmed_at IS NOT NULL
                )
            ),
            CONSTRAINT exchange_rate_calculation_trace_object CHECK (
                jsonb_typeof(calculation_trace) = 'object'
                AND calculation_trace <> '{}'::jsonb
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX exchange_rate_records_applicable_idx
        ON app.exchange_rate_records (applicable_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_append_only_configuration_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Effective-dated configuration history is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in (
        "property_services",
        "service_rates",
        "utility_rates",
        "exchange_rate_records",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.reject_append_only_configuration_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_append_only_configuration_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION app.guard_service_approval_period_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR OLD.effective_through IS NOT NULL
                OR NEW.effective_through IS NULL
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_service_id IS DISTINCT FROM OLD.property_service_id
                OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                OR NEW.approval_reference IS DISTINCT FROM OLD.approval_reference
                OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                OR NEW.reason IS DISTINCT FROM OLD.reason
            THEN
                RAISE EXCEPTION 'Service approval history is append-preserved'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER property_service_approval_periods_guard_history
        BEFORE UPDATE OR DELETE ON app.property_service_approval_periods
        FOR EACH ROW EXECUTE FUNCTION app.guard_service_approval_period_history()
        """
    )
    op.execute(
        """
        CREATE TRIGGER property_service_approval_periods_reject_truncate
        BEFORE TRUNCATE ON app.property_service_approval_periods
        FOR EACH STATEMENT EXECUTE FUNCTION app.guard_service_approval_period_history()
        """
    )
    for function in (
        "app.reject_append_only_configuration_mutation()",
        "app.guard_service_approval_period_history()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        """
        REVOKE ALL ON TABLE
            app.property_services,
            app.service_rates,
            app.property_service_approval_periods,
            app.utility_rates,
            app.exchange_rate_records
        FROM PUBLIC, prm_runtime, prm_bootstrap
        """
    )
    op.execute(
        """
        GRANT SELECT ON TABLE
            app.property_services,
            app.service_rates,
            app.property_service_approval_periods,
            app.utility_rates,
            app.exchange_rate_records
        TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback of append-preserved configuration history."""
    raise RuntimeError("V1-027 configuration persistence is forward-only")
