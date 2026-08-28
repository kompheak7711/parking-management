# ruff: noqa: E501
"""Add protected Invoice, adjustment, late-charge, and billing-run persistence."""

from alembic import op

revision = "20260827_29"
down_revision = "20260826_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-039 financial persistence boundary."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        r"""
        LOCK TABLE app.user_accounts IN SHARE ROW EXCLUSIVE MODE;

        CREATE TABLE app.actor_identities (
            actor_id uuid PRIMARY KEY CHECK (
                actor_id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            identity_kind text NOT NULL CHECK (identity_kind IN ('HUMAN','SERVICE')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
        );
        INSERT INTO app.actor_identities(actor_id,identity_kind,created_at)
            SELECT actor_id,'HUMAN',created_at FROM app.user_accounts;

        CREATE TABLE app.billing_service_principals (
            actor_id uuid PRIMARY KEY REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            capability text NOT NULL CHECK (capability='billing.generate'),
            lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('active','disabled')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            disabled_at timestamptz,
            disabled_by uuid REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            CONSTRAINT billing_service_principals_scope_unique UNIQUE(actor_id,property_id),
            CONSTRAINT billing_service_principals_lifecycle_shape CHECK (
                (lifecycle_state='active' AND disabled_at IS NULL AND disabled_by IS NULL)
                OR (lifecycle_state='disabled' AND disabled_at IS NOT NULL
                    AND disabled_at>=created_at AND disabled_by IS NOT NULL)
            )
        );

        CREATE TABLE app.invoices (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_number text NOT NULL UNIQUE CHECK (
                length(btrim(invoice_number)) > 0 AND invoice_number = btrim(invoice_number)
            ),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            source_occupancy_id uuid REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            primary_category text NOT NULL CHECK (primary_category IN (
                'RENT','UTILITIES','SERVICE_CHARGES','DAMAGE_CHARGES','MISCELLANEOUS_CHARGES'
            )),
            status text NOT NULL DEFAULT 'DRAFT' CHECK (
                status IN ('DRAFT','UNPAID','PARTIALLY_PAID','PAID','VOID')
            ),
            invoice_date date NOT NULL,
            due_date date NOT NULL,
            billing_period_start date,
            billing_period_end date,
            rent_billing_kind text CHECK (rent_billing_kind IN ('INITIAL','RECURRING')),
            original_total_usd_cents bigint NOT NULL CHECK (original_total_usd_cents >= 0),
            due_date_rule text NOT NULL CHECK (due_date_rule IN (
                'INITIAL_RENT_SEVEN_DAYS','RECURRING_RENT_FIFTH','GOVERNING_SOURCE'
            )),
            due_date_source text NOT NULL CHECK (
                length(btrim(due_date_source)) > 0 AND due_date_source = btrim(due_date_source)
            ),
            issued_at timestamptz,
            issued_by uuid REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT invoices_lease_identity_unique UNIQUE (id, lease_id),
            CONSTRAINT invoices_period_shape CHECK (
                (billing_period_start IS NULL AND billing_period_end IS NULL)
                OR (billing_period_start IS NOT NULL AND billing_period_end IS NOT NULL
                    AND billing_period_end >= billing_period_start)
            ),
            CONSTRAINT invoices_issuance_shape CHECK (
                (status='DRAFT' AND issued_at IS NULL AND issued_by IS NULL)
                OR (status='VOID' AND issued_at IS NULL AND issued_by IS NULL)
                OR (status<>'DRAFT' AND issued_at IS NOT NULL AND issued_by IS NOT NULL
                    AND issued_at>=created_at AND updated_at>=issued_at)
            ),
            CONSTRAINT invoices_rent_shape CHECK (
                (primary_category='RENT' AND lease_id IS NOT NULL
                    AND billing_period_start IS NOT NULL AND rent_billing_kind IS NOT NULL
                    AND ((rent_billing_kind='INITIAL' AND source_occupancy_id IS NOT NULL)
                        OR (rent_billing_kind='RECURRING' AND source_occupancy_id IS NULL))
                    AND due_date_rule = CASE rent_billing_kind
                        WHEN 'INITIAL' THEN 'INITIAL_RENT_SEVEN_DAYS'
                        ELSE 'RECURRING_RENT_FIFTH' END)
                OR (primary_category<>'RENT' AND rent_billing_kind IS NULL
                    AND source_occupancy_id IS NULL
                    AND due_date_rule='GOVERNING_SOURCE')
            ),
            CONSTRAINT invoices_provenance CHECK (
                due_date>=invoice_date AND updated_at>=created_at
            )
        );

        CREATE INDEX invoices_fifo_idx
            ON app.invoices(customer_id,status,due_date,issued_at,invoice_number);
        CREATE INDEX invoices_lease_history_idx
            ON app.invoices(lease_id,invoice_date,id) WHERE lease_id IS NOT NULL;

        CREATE TABLE app.authorized_nonrecurring_obligations (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            category text NOT NULL CHECK (category IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')),
            inspection_damage_finding_id uuid,
            description text NOT NULL CHECK (
                length(btrim(description)) > 0 AND description=btrim(description)
            ),
            authorized_amount_usd_cents bigint NOT NULL CHECK (authorized_amount_usd_cents > 0),
            governing_due_date date NOT NULL,
            due_date_source text NOT NULL CHECK (
                length(btrim(due_date_source)) > 0 AND due_date_source=btrim(due_date_source)
            ),
            source_reference text NOT NULL CHECK (
                length(btrim(source_reference)) > 0 AND source_reference=btrim(source_reference)
            ),
            authorized_at timestamptz NOT NULL,
            authorized_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            ),
            CONSTRAINT authorized_nonrecurring_source_shape CHECK (
                (category='DAMAGE_CHARGES' AND inspection_damage_finding_id IS NOT NULL)
                OR (category='MISCELLANEOUS_CHARGES' AND inspection_damage_finding_id IS NULL)
            ),
            CONSTRAINT authorized_nonrecurring_damage_source_deferred CHECK (
                category<>'DAMAGE_CHARGES'
            ),
            CONSTRAINT authorized_nonrecurring_due_date_chronology CHECK (
                governing_due_date>=timezone('Asia/Phnom_Penh',authorized_at)::date
            ),
            CONSTRAINT authorized_nonrecurring_source_unique
                UNIQUE(customer_id,category,source_reference)
        );

        CREATE TABLE app.invoice_lines (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            line_sequence smallint NOT NULL CHECK (line_sequence > 0),
            category text NOT NULL CHECK (category IN (
                'RENT','UTILITIES','SERVICE_CHARGES','DAMAGE_CHARGES','MISCELLANEOUS_CHARGES'
            )),
            description text NOT NULL CHECK (
                length(btrim(description)) > 0 AND description=btrim(description)
            ),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            period_start date,
            period_end date,
            source_lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            utility_consumption_period_id uuid UNIQUE,
            utility_rate_id uuid REFERENCES app.utility_rates(id) ON DELETE RESTRICT,
            property_service_id uuid REFERENCES app.property_services(id) ON DELETE RESTRICT,
            service_rate_id uuid REFERENCES app.service_rates(id) ON DELETE RESTRICT,
            lease_service_term_id uuid REFERENCES app.lease_service_terms(id) ON DELETE RESTRICT,
            service_approval_period_id uuid
                REFERENCES app.property_service_approval_periods(id) ON DELETE RESTRICT,
            authorized_obligation_id uuid
                REFERENCES app.authorized_nonrecurring_obligations(id) ON DELETE RESTRICT,
            contractual_monthly_usd_cents bigint CHECK (contractual_monthly_usd_cents > 0),
            billable_days smallint CHECK (billable_days > 0),
            calendar_days smallint CHECK (calendar_days BETWEEN 28 AND 31),
            quantity numeric(20,6) CHECK (quantity > 0),
            unit_rate_usd numeric(20,8) CHECK (unit_rate_usd > 0),
            calculation_trace jsonb NOT NULL CHECK (jsonb_typeof(calculation_trace)='object'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            last_changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            last_changed_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT invoice_lines_sequence_unique UNIQUE(invoice_id,line_sequence),
            CONSTRAINT invoice_lines_invoice_identity_unique UNIQUE(id,invoice_id),
            CONSTRAINT invoice_lines_period_shape CHECK (
                (period_start IS NULL AND period_end IS NULL)
                OR (period_start IS NOT NULL AND period_end IS NOT NULL
                    AND period_end >= period_start)
            ),
            CONSTRAINT invoice_lines_change_chronology CHECK (last_changed_at>=created_at),
            CONSTRAINT invoice_lines_typed_source_shape CHECK (
                (category='RENT'
                    AND source_lease_id IS NOT NULL
                    AND utility_consumption_period_id IS NULL AND utility_rate_id IS NULL
                    AND property_service_id IS NULL AND service_rate_id IS NULL
                    AND lease_service_term_id IS NULL AND service_approval_period_id IS NULL
                    AND authorized_obligation_id IS NULL
                    AND contractual_monthly_usd_cents IS NOT NULL
                    AND quantity IS NULL AND unit_rate_usd IS NULL)
                OR (category='UTILITIES'
                    AND utility_consumption_period_id IS NOT NULL AND utility_rate_id IS NOT NULL
                    AND property_service_id IS NULL AND service_rate_id IS NULL
                    AND lease_service_term_id IS NULL AND service_approval_period_id IS NULL
                    AND authorized_obligation_id IS NULL
                    AND contractual_monthly_usd_cents IS NULL
                    AND billable_days IS NULL AND calendar_days IS NULL
                    AND quantity IS NOT NULL AND unit_rate_usd IS NOT NULL)
                OR (category='SERVICE_CHARGES'
                    AND source_lease_id IS NOT NULL
                    AND utility_consumption_period_id IS NULL AND utility_rate_id IS NULL
                    AND property_service_id IS NOT NULL
                    AND lease_service_term_id IS NOT NULL
                    AND service_approval_period_id IS NOT NULL
                    AND authorized_obligation_id IS NULL
                    AND quantity IS NULL AND unit_rate_usd IS NULL)
                OR (category IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')
                    AND period_start IS NULL AND period_end IS NULL
                    AND source_lease_id IS NULL
                    AND utility_consumption_period_id IS NULL AND utility_rate_id IS NULL
                    AND property_service_id IS NULL AND service_rate_id IS NULL
                    AND lease_service_term_id IS NULL AND service_approval_period_id IS NULL
                    AND authorized_obligation_id IS NOT NULL
                    AND contractual_monthly_usd_cents IS NULL
                    AND billable_days IS NULL AND calendar_days IS NULL
                    AND quantity IS NULL AND unit_rate_usd IS NULL)
            ),
            CONSTRAINT invoice_lines_utility_source_deferred CHECK (category<>'UTILITIES')
        );
        CREATE INDEX invoice_lines_invoice_idx ON app.invoice_lines(invoice_id,line_sequence);
        CREATE INDEX invoice_lines_authorized_obligation_idx
            ON app.invoice_lines(authorized_obligation_id)
            WHERE authorized_obligation_id IS NOT NULL;
        CREATE INDEX invoice_lines_rent_period_idx ON app.invoice_lines USING gist (
            source_lease_id, daterange(period_start,period_end,'[]')
        ) WHERE (category='RENT');
        CREATE INDEX invoice_lines_service_period_idx ON app.invoice_lines USING gist (
            source_lease_id, property_service_id, daterange(period_start,period_end,'[]')
        ) WHERE (category='SERVICE_CHARGES');

        CREATE TABLE app.active_invoice_source_claims (
            invoice_line_id uuid PRIMARY KEY
                REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            category text NOT NULL CHECK (category IN (
                'RENT','SERVICE_CHARGES','DAMAGE_CHARGES','MISCELLANEOUS_CHARGES'
            )),
            source_lease_id uuid REFERENCES app.leases(id) ON DELETE RESTRICT,
            property_service_id uuid REFERENCES app.property_services(id) ON DELETE RESTRICT,
            authorized_obligation_id uuid
                REFERENCES app.authorized_nonrecurring_obligations(id) ON DELETE RESTRICT,
            period_start date,
            period_end date,
            CONSTRAINT active_invoice_source_claim_shape CHECK (
                (category='RENT' AND source_lease_id IS NOT NULL
                    AND property_service_id IS NULL AND authorized_obligation_id IS NULL
                    AND period_start IS NOT NULL AND period_end>=period_start)
                OR (category='SERVICE_CHARGES' AND source_lease_id IS NOT NULL
                    AND property_service_id IS NOT NULL AND authorized_obligation_id IS NULL
                    AND period_start IS NOT NULL AND period_end>=period_start)
                OR (category IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES')
                    AND source_lease_id IS NULL AND property_service_id IS NULL
                    AND authorized_obligation_id IS NOT NULL
                    AND period_start IS NULL AND period_end IS NULL)
            ),
            CONSTRAINT active_rent_source_claim_exclusion EXCLUDE USING gist (
                source_lease_id WITH =, daterange(period_start,period_end,'[]') WITH &&
            ) WHERE (category='RENT'),
            CONSTRAINT active_service_source_claim_exclusion EXCLUDE USING gist (
                source_lease_id WITH =, property_service_id WITH =,
                daterange(period_start,period_end,'[]') WITH &&
            ) WHERE (category='SERVICE_CHARGES')
        );
        CREATE UNIQUE INDEX active_authorized_obligation_claim_unique
            ON app.active_invoice_source_claims(authorized_obligation_id)
            WHERE authorized_obligation_id IS NOT NULL;
        CREATE INDEX active_invoice_source_claims_invoice_idx
            ON app.active_invoice_source_claims(invoice_id,invoice_line_id);

        CREATE TABLE app.invoice_serialization_guards (
            guard_key text PRIMARY KEY CHECK (
                length(btrim(guard_key)) > 0 AND guard_key=btrim(guard_key)
            ),
            revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
        );
        INSERT INTO app.invoice_serialization_guards(guard_key)
            SELECT 'invoice-lease:' || id::text FROM app.leases
            UNION
            SELECT 'invoice-service:' || id::text FROM app.property_services
            UNION
            SELECT 'invoice-obligation:' || id::text
                FROM app.authorized_nonrecurring_obligations
            UNION
            SELECT 'billing-run-eligibility:' || id::text FROM app.properties;

        CREATE TABLE app.invoice_line_calculation_components (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_line_id uuid NOT NULL REFERENCES app.invoice_lines(id) ON DELETE RESTRICT,
            component_sequence smallint NOT NULL CHECK (component_sequence > 0),
            component_kind text NOT NULL CHECK (component_kind IN (
                'PRORATED_MOVE_IN_MONTH','FULL_FOLLOWING_MONTH',
                'FULL_RECURRING_MONTH','OTHER_APPROVED_COMPONENT'
            )),
            period_start date NOT NULL,
            period_end date NOT NULL CHECK (period_end >= period_start),
            contractual_monthly_usd_cents bigint CHECK (contractual_monthly_usd_cents > 0),
            service_rate_id uuid REFERENCES app.service_rates(id) ON DELETE RESTRICT,
            service_monthly_rate_usd_cents bigint CHECK (service_monthly_rate_usd_cents > 0),
            billable_days smallint CHECK (billable_days > 0),
            calendar_days smallint CHECK (calendar_days BETWEEN 28 AND 31),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            calculation_trace jsonb NOT NULL CHECK (jsonb_typeof(calculation_trace)='object'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            last_changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            last_changed_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            CONSTRAINT invoice_line_components_change_chronology
                CHECK (last_changed_at>=created_at),
            CONSTRAINT invoice_line_components_sequence_unique
                UNIQUE(invoice_line_id,component_sequence),
            CONSTRAINT invoice_line_components_period_no_overlap EXCLUDE USING gist (
                invoice_line_id WITH =, daterange(period_start,period_end,'[]') WITH &&
            )
        );

        CREATE TABLE app.invoice_draft_revision_events (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            entity_kind text NOT NULL CHECK (entity_kind IN ('INVOICE','LINE','COMPONENT')),
            entity_id uuid NOT NULL,
            operation text NOT NULL CHECK (operation IN ('UPDATE','DELETE')),
            before_state jsonb NOT NULL CHECK (jsonb_typeof(before_state)='object'),
            after_state jsonb CHECK (after_state IS NULL OR jsonb_typeof(after_state)='object'),
            reason text NOT NULL CHECK (
                length(btrim(reason))>0 AND length(reason)<=500 AND reason=btrim(reason)
            ),
            changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            changed_by uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            transaction_id bigint NOT NULL,
            CONSTRAINT invoice_draft_revision_operation_shape CHECK (
                (operation='UPDATE' AND after_state IS NOT NULL)
                OR (operation='DELETE' AND after_state IS NULL)
            )
        );
        CREATE INDEX invoice_draft_revision_history_idx
            ON app.invoice_draft_revision_events(invoice_id,changed_at,id);

        CREATE TABLE app.invoice_adjustments (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_id uuid NOT NULL REFERENCES app.invoices(id) ON DELETE RESTRICT,
            invoice_line_id uuid NOT NULL,
            adjustment_type text NOT NULL CHECK (adjustment_type IN ('DEBIT','CREDIT')),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            source_reference text NOT NULL CHECK (
                length(btrim(source_reference)) > 0 AND source_reference=btrim(source_reference)
            ),
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason=btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            ),
            CONSTRAINT invoice_adjustments_source_unique
                UNIQUE(invoice_line_id,source_reference),
            CONSTRAINT invoice_adjustments_line_invoice_fkey
                FOREIGN KEY(invoice_line_id,invoice_id)
                REFERENCES app.invoice_lines(id,invoice_id) ON DELETE RESTRICT
        );

        CREATE TABLE app.invoice_adjustment_reversals (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_adjustment_id uuid NOT NULL UNIQUE
                REFERENCES app.invoice_adjustments(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason=btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            )
        );

        CREATE TABLE app.invoice_void_events (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason=btrim(reason)),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.actor_identities(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            )
        );

        CREATE TABLE app.late_payment_decisions (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            source_invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            source_due_date date NOT NULL,
            overdue_balance_at_assessment_usd_cents bigint NOT NULL CHECK (
                overdue_balance_at_assessment_usd_cents > 0
            ),
            default_rate_basis_points smallint NOT NULL CHECK (default_rate_basis_points=1000),
            calculated_default_amount_usd_cents bigint NOT NULL CHECK (
                calculated_default_amount_usd_cents >= 0
            ),
            decision_outcome text NOT NULL CHECK (
                decision_outcome IN ('CONFIRMED_DEFAULT','REDUCED','WAIVED')
            ),
            approved_amount_usd_cents bigint NOT NULL CHECK (approved_amount_usd_cents >= 0),
            assessed_at timestamptz NOT NULL,
            finalized_at timestamptz NOT NULL CHECK (finalized_at >= assessed_at),
            finalized_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason=btrim(reason)),
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            ),
            calculation_trace jsonb NOT NULL CHECK (jsonb_typeof(calculation_trace)='object'),
            CONSTRAINT late_payment_decisions_outcome_amount CHECK (
                (decision_outcome='WAIVED' AND approved_amount_usd_cents=0)
                OR (decision_outcome='CONFIRMED_DEFAULT'
                    AND approved_amount_usd_cents=calculated_default_amount_usd_cents
                    AND approved_amount_usd_cents>0)
                OR (decision_outcome='REDUCED' AND approved_amount_usd_cents>0
                    AND approved_amount_usd_cents<calculated_default_amount_usd_cents)
            )
        );

        CREATE TABLE app.late_payment_charges (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            source_invoice_id uuid NOT NULL UNIQUE REFERENCES app.invoices(id) ON DELETE RESTRICT,
            late_payment_decision_id uuid NOT NULL UNIQUE
                REFERENCES app.late_payment_decisions(id) ON DELETE RESTRICT,
            original_amount_usd_cents bigint NOT NULL CHECK (original_amount_usd_cents > 0),
            payable_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL,
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT
        );

        CREATE TABLE app.late_payment_charge_corrections (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            late_payment_charge_id uuid NOT NULL REFERENCES app.late_payment_charges(id) ON DELETE RESTRICT,
            correction_kind text NOT NULL CHECK (
                correction_kind IN ('REDUCTION','CHARGE_REVERSAL','REDUCTION_REVERSAL')
            ),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            reverses_correction_id uuid UNIQUE
                REFERENCES app.late_payment_charge_corrections(id) ON DELETE RESTRICT,
            reason text NOT NULL CHECK (length(btrim(reason)) > 0 AND reason=btrim(reason)),
            previous_obligation_usd_cents bigint NOT NULL CHECK (previous_obligation_usd_cents >= 0),
            resulting_obligation_usd_cents bigint NOT NULL CHECK (resulting_obligation_usd_cents >= 0),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference=btrim(authorization_reference)
            ),
            correlation_id uuid NOT NULL,
            CONSTRAINT late_charge_corrections_correlation_unique
                UNIQUE(late_payment_charge_id,correlation_id),
            CONSTRAINT late_charge_correction_reversal_shape CHECK (
                (correction_kind='REDUCTION_REVERSAL' AND reverses_correction_id IS NOT NULL)
                OR (correction_kind<>'REDUCTION_REVERSAL' AND reverses_correction_id IS NULL)
            )
        );

        CREATE TABLE app.billing_runs (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            run_kind text NOT NULL CHECK (run_kind IN ('RENT','UTILITIES')),
            logical_run_key text NOT NULL CHECK (
                length(btrim(logical_run_key)) > 0 AND logical_run_key=btrim(logical_run_key)
            ),
            business_date date NOT NULL,
            period_start date,
            period_end date,
            idempotency_key uuid NOT NULL,
            system_actor_id uuid NOT NULL,
            predecessor_run_id uuid UNIQUE REFERENCES app.billing_runs(id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
            started_at timestamptz NOT NULL,
            completed_at timestamptz,
            failure_code text,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            CONSTRAINT billing_runs_logical_unique UNIQUE(property_id,run_kind,logical_run_key),
            CONSTRAINT billing_runs_idempotency_unique UNIQUE(property_id,idempotency_key),
            CONSTRAINT billing_runs_service_principal_fkey
                FOREIGN KEY(system_actor_id,property_id)
                REFERENCES app.billing_service_principals(actor_id,property_id)
                ON DELETE RESTRICT,
            CONSTRAINT billing_runs_period_shape CHECK (
                period_start IS NOT NULL AND period_end IS NOT NULL
                AND period_end >= period_start
            ),
            CONSTRAINT billing_runs_utility_source_deferred CHECK (run_kind<>'UTILITIES'),
            CONSTRAINT billing_runs_completion_shape CHECK (
                (status='RUNNING' AND completed_at IS NULL AND failure_code IS NULL)
                OR (status='SUCCEEDED' AND completed_at IS NOT NULL
                    AND completed_at>=started_at AND failure_code IS NULL)
                OR (status='FAILED' AND completed_at IS NOT NULL
                    AND completed_at>=started_at AND failure_code IS NOT NULL
                    AND length(btrim(failure_code))>0 AND failure_code=btrim(failure_code))
            )
        );
        CREATE UNIQUE INDEX billing_runs_root_semantic_unique
            ON app.billing_runs(property_id,run_kind,period_start,period_end)
            WHERE predecessor_run_id IS NULL;
        CREATE INDEX billing_runs_history_idx
            ON app.billing_runs(property_id,run_kind,business_date DESC,id DESC);
        ALTER TABLE app.billing_runs ADD CONSTRAINT billing_runs_period_no_overlap
            EXCLUDE USING gist (
                property_id WITH =,run_kind WITH =,
                daterange(period_start,period_end,'[]') WITH &&
            ) WHERE (status<>'FAILED');

        CREATE TABLE app.billing_run_eligible_sources (
            billing_run_id uuid NOT NULL REFERENCES app.billing_runs(id) ON DELETE RESTRICT,
            source_kind text NOT NULL CHECK (source_kind='LEASE_PERIOD'),
            source_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            source_period_start date NOT NULL,
            source_period_end date NOT NULL CHECK (source_period_end>=source_period_start),
            snapshotted_at timestamptz NOT NULL,
            PRIMARY KEY (
                billing_run_id,source_kind,source_id,source_period_start,source_period_end
            )
        );

        CREATE TABLE app.billing_run_attempts (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            billing_run_id uuid NOT NULL REFERENCES app.billing_runs(id) ON DELETE RESTRICT,
            attempt_number smallint NOT NULL CHECK (attempt_number>0),
            started_at timestamptz NOT NULL,
            completed_at timestamptz,
            outcome text NOT NULL CHECK (outcome IN ('RUNNING','SUCCEEDED','FAILED')),
            diagnostic_code text,
            CONSTRAINT billing_run_attempts_identity_unique UNIQUE(id,billing_run_id),
            CONSTRAINT billing_run_attempts_number_unique UNIQUE(billing_run_id,attempt_number),
            CONSTRAINT billing_run_attempts_shape CHECK (
                (outcome='RUNNING' AND completed_at IS NULL AND diagnostic_code IS NULL)
                OR (outcome='SUCCEEDED' AND completed_at IS NOT NULL
                    AND completed_at>=started_at AND diagnostic_code IS NULL)
                OR (outcome='FAILED' AND completed_at IS NOT NULL
                    AND completed_at>=started_at AND diagnostic_code IS NOT NULL
                    AND length(btrim(diagnostic_code))>0 AND diagnostic_code=btrim(diagnostic_code))
            )
        );

        CREATE TABLE app.billing_run_items (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            billing_run_id uuid NOT NULL REFERENCES app.billing_runs(id) ON DELETE RESTRICT,
            billing_run_attempt_id uuid NOT NULL,
            source_kind text NOT NULL CHECK (source_kind IN ('LEASE_PERIOD','UTILITY_PERIOD')),
            source_id uuid NOT NULL,
            source_period_start date NOT NULL,
            source_period_end date NOT NULL CHECK (source_period_end>=source_period_start),
            outcome text NOT NULL CHECK (outcome IN ('GENERATED','SKIPPED','CONFLICT','ERROR')),
            invoice_id uuid REFERENCES app.invoices(id) ON DELETE RESTRICT,
            diagnostic_code text,
            recorded_at timestamptz NOT NULL,
            CONSTRAINT billing_run_items_attempt_fkey
                FOREIGN KEY(billing_run_attempt_id,billing_run_id)
                REFERENCES app.billing_run_attempts(id,billing_run_id) ON DELETE RESTRICT,
            CONSTRAINT billing_run_items_source_unique UNIQUE(
                billing_run_attempt_id,source_kind,source_id,source_period_start,source_period_end
            ),
            CONSTRAINT billing_run_items_outcome_shape CHECK (
                (outcome='GENERATED' AND invoice_id IS NOT NULL AND diagnostic_code IS NULL)
                OR (outcome='SKIPPED' AND (
                    (invoice_id IS NOT NULL
                        AND diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS')
                    OR (invoice_id IS NULL
                        AND diagnostic_code='SOURCE_NO_LONGER_ELIGIBLE')
                ))
                OR (outcome IN ('CONFLICT','ERROR') AND invoice_id IS NULL
                    AND diagnostic_code IS NOT NULL
                    AND length(btrim(diagnostic_code))>0 AND diagnostic_code=btrim(diagnostic_code))
            )
        );
        CREATE UNIQUE INDEX billing_run_items_generated_invoice_unique
            ON app.billing_run_items(invoice_id) WHERE outcome='GENERATED';

        ALTER TABLE app.invoices ADD COLUMN originating_billing_run_attempt_id uuid
            REFERENCES app.billing_run_attempts(id) ON DELETE RESTRICT;

        COMMENT ON COLUMN app.invoice_lines.utility_consumption_period_id IS
            'Stable DB-UTIL-006 identity; rows remain prohibited until its FK is installed by V1-042';
        COMMENT ON COLUMN app.authorized_nonrecurring_obligations.inspection_damage_finding_id IS
            'Stable inspection-finding identity; Damage rows remain prohibited until its FK is installed';
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.protect_actor_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP='INSERT' AND pg_catalog.pg_trigger_depth()>1 THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'Actor identity registry is internal and append-only'
                USING ERRCODE='55000';
        END $$;

        CREATE FUNCTION app.sync_human_actor_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            INSERT INTO app.actor_identities(actor_id,identity_kind,created_at)
            VALUES (NEW.actor_id,'HUMAN',NEW.created_at);
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.assert_active_financial_actor(
            p_actor_id uuid,p_property_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_identity_kind text;
        BEGIN
            SELECT identity_kind INTO v_identity_kind
            FROM app.actor_identities WHERE actor_id=p_actor_id;
            IF v_identity_kind='HUMAN' THEN
                PERFORM 1 FROM app.user_accounts AS account
                WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                FOR SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Financial action requires an active human actor'
                        USING ERRCODE='55000';
                END IF;
                RETURN;
            END IF;
            IF v_identity_kind='SERVICE' AND p_property_id IS NOT NULL THEN
                PERFORM 1 FROM app.billing_service_principals AS principal
                WHERE principal.actor_id=p_actor_id
                  AND principal.property_id=p_property_id
                  AND principal.capability='billing.generate'
                  AND principal.lifecycle_state='active'
                FOR SHARE;
                IF FOUND THEN RETURN; END IF;
            END IF;
            RAISE EXCEPTION 'Financial action requires an active scoped actor'
                USING ERRCODE='55000';
        END $$;

        CREATE FUNCTION app.enforce_active_human_financial_actor()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_actor_id uuid;
        BEGIN
            v_actor_id:=CASE TG_TABLE_NAME
                WHEN 'authorized_nonrecurring_obligations'
                    THEN (to_jsonb(NEW)->>'authorized_by')::uuid
                WHEN 'invoice_adjustments' THEN (to_jsonb(NEW)->>'actor_id')::uuid
                WHEN 'invoice_adjustment_reversals' THEN (to_jsonb(NEW)->>'actor_id')::uuid
                WHEN 'late_payment_decisions' THEN (to_jsonb(NEW)->>'finalized_by')::uuid
                WHEN 'late_payment_charges' THEN (to_jsonb(NEW)->>'created_by')::uuid
                WHEN 'late_payment_charge_corrections'
                    THEN (to_jsonb(NEW)->>'actor_id')::uuid
            END;
            IF v_actor_id IS NULL THEN
                RAISE EXCEPTION 'Financial event actor is required' USING ERRCODE='55000';
            END IF;
            PERFORM app.assert_active_financial_actor(v_actor_id,NULL);
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_billing_service_principal()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.lifecycle_state<>'active' OR NEW.disabled_at IS NOT NULL
                    OR NEW.disabled_by IS NOT NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM app.user_accounts AS account
                        WHERE account.actor_id=NEW.created_by
                          AND account.lifecycle_state='active'
                    )
                THEN RAISE EXCEPTION 'Billing service principal registration is invalid'
                    USING ERRCODE='23514'; END IF;
                INSERT INTO app.actor_identities(actor_id,identity_kind)
                VALUES (NEW.actor_id,'SERVICE');
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' OR OLD.lifecycle_state<>'active'
                OR NEW.actor_id<>OLD.actor_id OR NEW.property_id<>OLD.property_id
                OR NEW.capability<>OLD.capability OR NEW.created_at<>OLD.created_at
                OR NEW.created_by<>OLD.created_by OR NEW.lifecycle_state<>'disabled'
                OR NEW.disabled_at IS NULL OR NEW.disabled_by IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM app.user_accounts AS account
                    WHERE account.actor_id=NEW.disabled_by
                      AND account.lifecycle_state='active'
                )
            THEN RAISE EXCEPTION 'Billing service principal history is protected'
                USING ERRCODE='55000'; END IF;
            IF EXISTS (
                SELECT 1 FROM app.billing_runs AS run
                WHERE run.system_actor_id=OLD.actor_id
                  AND run.property_id=OLD.property_id
                  AND run.status='RUNNING'
            ) THEN RAISE EXCEPTION
                'Billing service principal cannot be disabled while a run is active'
                USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_invoice_draft_revision_event()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP='INSERT' AND pg_catalog.pg_trigger_depth()>1 THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'Invoice DRAFT revision history is internal and append-only'
                USING ERRCODE='55000';
        END $$;

        CREATE FUNCTION app.record_invoice_draft_revision(
            p_invoice_id uuid,p_entity_kind text,p_entity_id uuid,p_operation text,
            p_before_state jsonb,p_after_state jsonb,p_row_actor_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_reason text; v_actor_text text; v_actor_id uuid;
        BEGIN
            v_reason:=NULLIF(btrim(current_setting('app.draft_correction_reason',true)),'');
            v_actor_text:=NULLIF(
                btrim(current_setting('app.draft_correction_actor_id',true)),''
            );
            IF v_reason IS NULL OR length(v_reason)>500 OR v_actor_text IS NULL
                OR v_actor_text !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            THEN RAISE EXCEPTION 'Invoice DRAFT correction requires bounded reason and actor context'
                USING ERRCODE='55000'; END IF;
            v_actor_id:=v_actor_text::uuid;
            IF NOT EXISTS (
                SELECT 1 FROM app.user_accounts AS account
                WHERE account.actor_id=v_actor_id AND account.lifecycle_state='active'
            ) OR (p_row_actor_id IS NOT NULL AND p_row_actor_id<>v_actor_id)
            THEN RAISE EXCEPTION 'Invoice DRAFT correction actor is invalid'
                USING ERRCODE='55000'; END IF;
            INSERT INTO app.invoice_draft_revision_events(
                invoice_id,entity_kind,entity_id,operation,before_state,after_state,
                reason,changed_by,transaction_id
            ) VALUES (
                p_invoice_id,p_entity_kind,p_entity_id,p_operation,p_before_state,
                p_after_state,v_reason,v_actor_id,pg_catalog.txid_current()
            );
        END $$;

        CREATE FUNCTION app.invoice_adjusted_line_obligation(p_line_id uuid)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT line.amount_usd_cents + COALESCE(sum(
                CASE adjustment.adjustment_type WHEN 'DEBIT' THEN adjustment.amount_usd_cents
                    ELSE -adjustment.amount_usd_cents END
            ) FILTER (WHERE reversal.id IS NULL),0)::bigint
            FROM app.invoice_lines AS line
            LEFT JOIN app.invoice_adjustments AS adjustment ON adjustment.invoice_line_id=line.id
            LEFT JOIN app.invoice_adjustment_reversals AS reversal
                ON reversal.invoice_adjustment_id=adjustment.id
            WHERE line.id=p_line_id GROUP BY line.amount_usd_cents
        $$;

        CREATE FUNCTION app.invoice_adjusted_line_obligation_at(
            p_line_id uuid,
            p_as_of timestamptz
        )
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
            SELECT line.amount_usd_cents + COALESCE(sum(
                CASE adjustment.adjustment_type WHEN 'DEBIT' THEN adjustment.amount_usd_cents
                    ELSE -adjustment.amount_usd_cents END
            ) FILTER (
                WHERE adjustment.occurred_at<=p_as_of
                  AND (reversal.id IS NULL OR reversal.occurred_at>p_as_of)
            ),0)::bigint
            FROM app.invoice_lines AS line
            LEFT JOIN app.invoice_adjustments AS adjustment ON adjustment.invoice_line_id=line.id
            LEFT JOIN app.invoice_adjustment_reversals AS reversal
                ON reversal.invoice_adjustment_id=adjustment.id
            WHERE line.id=p_line_id GROUP BY line.amount_usd_cents
        $$;

        CREATE FUNCTION app.lease_is_billable_for_recurring_period(
            p_lease_id uuid,p_period_start date,p_period_end date,p_as_of timestamptz
        ) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.leases AS lease
                JOIN LATERAL (
                    SELECT min(occupancy.move_in_date) AS first_move_in
                    FROM app.occupancies AS occupancy
                    WHERE occupancy.lease_id=lease.id
                      AND occupancy.created_at<=p_as_of
                ) AS move_in ON move_in.first_move_in IS NOT NULL
                WHERE lease.id=p_lease_id
                  AND lease.status IN ('SIGNED','TERMINATED')
                  AND p_period_start=date_trunc('month',p_period_start)::date
                  AND p_period_end=(date_trunc('month',p_period_start)
                      + interval '1 month - 1 day')::date
                  AND p_period_start>(
                      date_trunc('month',move_in.first_move_in)::date
                      + CASE WHEN extract(day FROM move_in.first_move_in)<=20
                          THEN interval '1 month - 1 day'
                          ELSE interval '2 months - 1 day' END
                  )::date
                  AND lease.start_date<=p_period_start
                  AND (
                      (lease.status='SIGNED' AND lease.end_date>=p_period_end)
                      OR (lease.status='TERMINATED' AND lease.terminated_at>p_as_of
                          AND lease.end_date>=p_period_end)
                      OR (lease.status='TERMINATED' AND lease.terminated_at<=p_as_of
                          AND (
                              lease.actual_termination_date>=p_period_end
                              OR (
                                  lease.actual_termination_date>=p_period_start
                                  AND p_period_end=(date_trunc(
                                      'month',lease.actual_termination_date
                                  ) + interval '1 month - 1 day')::date
                                  AND EXISTS (
                                      SELECT 1 FROM app.lease_commands AS command
                                      WHERE command.lease_id=lease.id
                                        AND command.action='lease.terminate'
                                        AND command.governing_event_reference='BR-LEASE-021'
                                        AND command.occurred_at=lease.terminated_at
                                        AND command.reason=lease.termination_reason
                                        AND command.result_snapshot->>'status'='TERMINATED'
                                        AND command.result_snapshot
                                            ->>'actual_termination_date'
                                            =lease.actual_termination_date::text
                                  )
                              )
                          ))
                  )
            )
        $$;

        CREATE FUNCTION app.validate_invoice_record()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_total bigint; v_count bigint;
        DECLARE v_move_in date; v_draft_void boolean; v_validate_sources boolean;
        BEGIN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=NEW.id;
            v_draft_void:=v_invoice.status='VOID' AND v_invoice.issued_at IS NULL;
            v_validate_sources:=TG_OP='INSERT' OR (
                TG_OP='UPDATE' AND OLD.status='DRAFT'
            );
            IF v_validate_sources AND NOT v_draft_void
                AND v_invoice.lease_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.lease_signers AS signer
                WHERE signer.lease_id=v_invoice.lease_id
                  AND signer.customer_id=v_invoice.customer_id AND signer.signed_at IS NOT NULL
                  AND (v_invoice.status='DRAFT' OR signer.signed_at<=v_invoice.issued_at)
            ) THEN RAISE EXCEPTION 'Invoice Customer is not a signed Lease Customer'
                USING ERRCODE='23514'; END IF;
            IF v_validate_sources AND NOT v_draft_void
                AND v_invoice.primary_category='RENT' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM app.leases AS lease WHERE lease.id=v_invoice.lease_id
                      AND lease.status IN ('SIGNED','TERMINATED')
                          AND v_invoice.billing_period_start>=lease.start_date
                          AND (
                              (lease.status='SIGNED'
                                  AND v_invoice.billing_period_end<=lease.end_date)
                              OR (lease.status='TERMINATED'
                                  AND lease.terminated_at>v_invoice.issued_at
                                  AND v_invoice.billing_period_end<=lease.end_date)
                              OR (lease.status='TERMINATED'
                              AND v_invoice.billing_period_start<=lease.actual_termination_date
                              AND (
                                  v_invoice.billing_period_end<=lease.actual_termination_date
                                  OR (
                                      v_invoice.billing_period_end=(date_trunc(
                                          'month',lease.actual_termination_date
                                      ) + interval '1 month - 1 day')::date
                                      AND v_invoice.due_date_source='BR-RENT-024'
                                      AND (v_invoice.status='DRAFT'
                                          OR lease.terminated_at<=v_invoice.issued_at)
                                      AND EXISTS (
                                          SELECT 1 FROM app.lease_commands AS command
                                          WHERE command.lease_id=lease.id
                                            AND command.action='lease.terminate'
                                            AND command.governing_event_reference='BR-LEASE-021'
                                            AND command.occurred_at=lease.terminated_at
                                            AND command.reason=lease.termination_reason
                                            AND command.result_snapshot->>'status'='TERMINATED'
                                            AND command.result_snapshot
                                                ->>'actual_termination_date'
                                                =lease.actual_termination_date::text
                                      )
                                  )
                              ))
                      )
                ) THEN RAISE EXCEPTION 'Rent Invoice requires an applicable signed Lease'
                    USING ERRCODE='23514'; END IF;
                IF v_invoice.rent_billing_kind='RECURRING' AND (
                    v_invoice.due_date<>date_trunc(
                        'month',v_invoice.billing_period_start
                    )::date+4
                    OR NOT app.lease_is_billable_for_recurring_period(
                        v_invoice.lease_id,v_invoice.billing_period_start,
                        v_invoice.billing_period_end,
                        CASE WHEN v_invoice.status='DRAFT' THEN statement_timestamp()
                            ELSE v_invoice.issued_at END
                    )
                ) THEN RAISE EXCEPTION 'Recurring Rent period or Due Date is invalid'
                    USING ERRCODE='23514'; END IF;
                IF v_invoice.rent_billing_kind='INITIAL' THEN
                    SELECT occupancy.move_in_date INTO v_move_in
                    FROM app.occupancies AS occupancy
                    WHERE occupancy.id=v_invoice.source_occupancy_id
                      AND occupancy.lease_id=v_invoice.lease_id
                      AND occupancy.customer_id=v_invoice.customer_id;
                    IF v_move_in IS NULL OR v_invoice.billing_period_start<>v_move_in
                        OR EXISTS (
                            SELECT 1 FROM app.occupancies AS earlier
                            WHERE earlier.lease_id=v_invoice.lease_id
                              AND earlier.move_in_date<v_move_in
                              AND (v_invoice.status='DRAFT'
                                  OR earlier.created_at<=v_invoice.issued_at)
                        )
                        OR v_invoice.due_date<>v_move_in+7
                        OR v_invoice.billing_period_end<>(
                            date_trunc('month',v_move_in)::date
                            + CASE WHEN extract(day FROM v_move_in)<=20
                                THEN interval '1 month - 1 day' ELSE interval '2 months - 1 day' END
                        )::date
                    THEN RAISE EXCEPTION 'Initial Rent period or Due Date is invalid'
                        USING ERRCODE='23514'; END IF;
                END IF;
            END IF;
            IF v_invoice.status<>'DRAFT' AND NOT v_draft_void THEN
                SELECT count(*),COALESCE(sum(amount_usd_cents),0) INTO v_count,v_total
                FROM app.invoice_lines WHERE invoice_id=v_invoice.id;
                IF v_count=0 OR v_total<>v_invoice.original_total_usd_cents THEN
                    RAISE EXCEPTION 'Issued Invoice requires reconciled immutable lines'
                        USING ERRCODE='23514';
                END IF;
                IF v_invoice.primary_category='RENT' AND (
                    SELECT count(*) FROM app.invoice_lines
                    WHERE invoice_id=v_invoice.id AND category='RENT'
                )<>1 THEN RAISE EXCEPTION 'Issued Rent Invoice requires exactly one Rent line'
                    USING ERRCODE='23514'; END IF;
                IF v_invoice.originating_billing_run_attempt_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM app.billing_run_items AS item
                    WHERE item.billing_run_attempt_id=v_invoice.originating_billing_run_attempt_id
                      AND item.invoice_id=v_invoice.id AND item.outcome='GENERATED'
                ) THEN RAISE EXCEPTION 'Generated Invoice requires its Billing Run item'
                    USING ERRCODE='23514'; END IF;
                IF EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    JOIN app.authorized_nonrecurring_obligations AS obligation
                      ON obligation.id=line.authorized_obligation_id
                    WHERE line.invoice_id=v_invoice.id
                      AND obligation.authorized_at>v_invoice.issued_at
                ) THEN RAISE EXCEPTION 'Invoice predates its obligation authorization'
                    USING ERRCODE='23514'; END IF;
            END IF;
            IF v_invoice.status='VOID' AND NOT EXISTS (
                SELECT 1 FROM app.invoice_void_events WHERE invoice_id=v_invoice.id
            ) THEN RAISE EXCEPTION 'VOID Invoice requires its authorized event'
                USING ERRCODE='23514'; END IF;
            IF v_invoice.status<>'VOID' AND EXISTS (
                SELECT 1 FROM app.invoice_void_events WHERE invoice_id=v_invoice.id
            ) THEN RAISE EXCEPTION 'Invoice VOID event requires terminal VOID status'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_invoice_line()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_obligation app.authorized_nonrecurring_obligations%ROWTYPE;
        DECLARE v_component_count bigint; v_component_total bigint; v_min date; v_max date;
        BEGIN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=NEW.invoice_id;
            IF NOT (NEW.category=v_invoice.primary_category
                OR (v_invoice.primary_category='RENT' AND NEW.category='SERVICE_CHARGES')) THEN
                RAISE EXCEPTION 'Invoice and line categories are inconsistent' USING ERRCODE='23514';
            END IF;
            IF NEW.category='RENT' THEN
                IF NEW.source_lease_id IS DISTINCT FROM v_invoice.lease_id
                    OR NEW.period_start IS NULL OR NEW.contractual_monthly_usd_cents IS NULL
                    OR NEW.period_start<>v_invoice.billing_period_start
                    OR NEW.period_end<>v_invoice.billing_period_end
                    OR NEW.contractual_monthly_usd_cents IS DISTINCT FROM (
                        SELECT monthly_rent_usd_cents FROM app.leases WHERE id=NEW.source_lease_id
                    )
                    OR NEW.utility_consumption_period_id IS NOT NULL
                    OR NEW.property_service_id IS NOT NULL OR NEW.authorized_obligation_id IS NOT NULL
                THEN RAISE EXCEPTION 'Rent line source is invalid' USING ERRCODE='23514'; END IF;
            ELSIF NEW.category='UTILITIES' THEN
                IF NEW.utility_consumption_period_id IS NULL OR NEW.utility_rate_id IS NULL
                    OR NEW.quantity IS NULL OR NEW.unit_rate_usd IS NULL OR NEW.period_start IS NULL
                    OR NEW.amount_usd_cents<>round(NEW.quantity*NEW.unit_rate_usd*100,0)::bigint
                    OR NEW.source_lease_id IS DISTINCT FROM v_invoice.lease_id
                    OR NEW.property_service_id IS NOT NULL OR NEW.authorized_obligation_id IS NOT NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM app.utility_rates AS rate WHERE rate.id=NEW.utility_rate_id
                          AND rate.rate_usd_per_unit=NEW.unit_rate_usd
                          AND rate.effective_date<=v_invoice.invoice_date
                          AND (v_invoice.lease_id IS NULL OR rate.property_id=(
                              SELECT unit.property_id FROM app.leases AS lease
                              JOIN app.units AS unit ON unit.id=lease.unit_id
                              WHERE lease.id=v_invoice.lease_id
                          ))
                          AND NOT EXISTS (
                              SELECT 1 FROM app.utility_rates AS later
                              WHERE later.property_id=rate.property_id
                                AND later.utility_type=rate.utility_type
                                AND later.measurement_unit_code=rate.measurement_unit_code
                                AND later.effective_date<=v_invoice.invoice_date
                                AND later.effective_date>rate.effective_date
                          )
                    )
                THEN RAISE EXCEPTION 'Utility line source is invalid' USING ERRCODE='23514'; END IF;
            ELSIF NEW.category='SERVICE_CHARGES' THEN
                IF NEW.source_lease_id IS NULL OR NEW.source_lease_id IS DISTINCT FROM v_invoice.lease_id
                    OR NEW.property_service_id IS NULL OR NEW.lease_service_term_id IS NULL
                    OR NEW.service_approval_period_id IS NULL OR NEW.period_start IS NULL
                    OR NEW.authorized_obligation_id IS NOT NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM app.lease_service_terms AS term
                        WHERE term.id=NEW.lease_service_term_id
                          AND term.lease_id=NEW.source_lease_id
                          AND term.property_service_id=NEW.property_service_id
                          AND term.service_approval_period_id=NEW.service_approval_period_id
                          AND NEW.period_start>=term.applicable_from
                          AND NEW.period_end<=COALESCE(term.applicable_through,NEW.period_end)
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM app.property_service_approval_periods AS approval
                        WHERE approval.id=NEW.service_approval_period_id
                          AND approval.property_service_id=NEW.property_service_id
                          AND NEW.period_start>=approval.effective_from
                          AND NEW.period_end<=COALESCE(approval.effective_through,NEW.period_end)
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM app.leases AS lease
                        WHERE lease.id=NEW.source_lease_id
                          AND NEW.period_start>=lease.start_date
                          AND (
                              (lease.status='SIGNED' AND NEW.period_end<=lease.end_date)
                              OR (lease.status='TERMINATED'
                                  AND lease.terminated_at>v_invoice.issued_at
                                  AND NEW.period_end<=lease.end_date)
                              OR (
                                  lease.status='TERMINATED'
                                  AND NEW.period_start<=lease.actual_termination_date
                                  AND (
                                      NEW.period_end<=lease.actual_termination_date
                                      OR (
                                          NEW.period_end=(date_trunc(
                                              'month',lease.actual_termination_date
                                          ) + interval '1 month - 1 day')::date
                                          AND (v_invoice.status='DRAFT'
                                              OR lease.terminated_at<=v_invoice.issued_at)
                                          AND EXISTS (
                                              SELECT 1 FROM app.lease_commands AS command
                                              WHERE command.lease_id=lease.id
                                                AND command.action='lease.terminate'
                                                AND command.governing_event_reference
                                                    ='BR-LEASE-021'
                                                AND command.occurred_at=lease.terminated_at
                                                AND command.reason=lease.termination_reason
                                                AND command.result_snapshot->>'status'
                                                    ='TERMINATED'
                                                AND command.result_snapshot
                                                    ->>'actual_termination_date'
                                                    =lease.actual_termination_date::text
                                          )
                                      )
                                  )
                              )
                          )
                    )
                    OR (NEW.service_rate_id IS NOT NULL AND (
                        NEW.contractual_monthly_usd_cents IS NULL OR NOT EXISTS (
                            SELECT 1 FROM app.service_rates AS rate
                            WHERE rate.id=NEW.service_rate_id
                              AND rate.property_service_id=NEW.property_service_id
                              AND rate.monthly_rate_usd_cents=NEW.contractual_monthly_usd_cents
                              AND (v_invoice.status='DRAFT'
                                  OR rate.occurred_at<=v_invoice.issued_at)
                              AND rate.effective_date<=NEW.period_start
                              AND NOT EXISTS (
                                  SELECT 1 FROM app.service_rates AS later
                                  WHERE later.property_service_id=rate.property_service_id
                                    AND (v_invoice.status='DRAFT'
                                        OR later.occurred_at<=v_invoice.issued_at)
                                    AND later.effective_date<=NEW.period_start
                                    AND later.effective_date>rate.effective_date
                              )
                        )
                    ))
                THEN RAISE EXCEPTION 'Service line source is invalid' USING ERRCODE='23514'; END IF;
            ELSE
                IF NEW.authorized_obligation_id IS NULL OR NEW.source_lease_id IS NOT NULL
                    OR NEW.utility_consumption_period_id IS NOT NULL OR NEW.property_service_id IS NOT NULL
                THEN RAISE EXCEPTION 'Non-recurring line source is invalid' USING ERRCODE='23514'; END IF;
                SELECT * INTO v_obligation FROM app.authorized_nonrecurring_obligations
                    WHERE id=NEW.authorized_obligation_id;
                IF v_obligation.customer_id<>v_invoice.customer_id
                    OR v_obligation.lease_id IS DISTINCT FROM v_invoice.lease_id
                    OR v_obligation.category<>NEW.category
                    OR v_obligation.authorized_amount_usd_cents<>NEW.amount_usd_cents
                    OR v_obligation.description<>NEW.description
                    OR v_obligation.governing_due_date<>v_invoice.due_date
                    OR v_obligation.due_date_source<>v_invoice.due_date_source
                    OR (v_invoice.status<>'DRAFT'
                        AND v_obligation.authorized_at>v_invoice.issued_at)
                THEN RAISE EXCEPTION 'Authorized obligation does not match Invoice line'
                    USING ERRCODE='23514'; END IF;
            END IF;
            IF NEW.period_start IS NOT NULL AND (
                v_invoice.billing_period_start IS NULL
                OR NEW.period_start<v_invoice.billing_period_start
                OR NEW.period_end>v_invoice.billing_period_end
            ) THEN RAISE EXCEPTION 'Invoice line period exceeds its Invoice period'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.serialize_invoice_line_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_source_key text; v_old_source_key text; v_lock_key text;
        DECLARE v_origin_attempt_id uuid; v_system_actor_id uuid;
        BEGIN
            IF TG_OP='INSERT' THEN
                SELECT originating_billing_run_attempt_id INTO v_origin_attempt_id
                FROM app.invoices WHERE id=NEW.invoice_id;
                IF v_origin_attempt_id IS NOT NULL THEN
                    SELECT run.system_actor_id INTO v_system_actor_id
                    FROM app.billing_run_attempts AS attempt
                    JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                    WHERE attempt.id=v_origin_attempt_id;
                    IF NEW.created_by<>v_system_actor_id THEN
                        RAISE EXCEPTION 'Generated Invoice detail is actor-bound'
                            USING ERRCODE='55000';
                    END IF;
                END IF;
            END IF;
            v_source_key:=CASE NEW.category
                WHEN 'RENT' THEN 'rent:' || NEW.source_lease_id::text
                WHEN 'UTILITIES' THEN 'utility:' || NEW.utility_consumption_period_id::text
                WHEN 'SERVICE_CHARGES' THEN 'service:' || NEW.source_lease_id::text || ':'
                    || NEW.property_service_id::text
                ELSE 'obligation:' || NEW.authorized_obligation_id::text
            END;
            IF TG_OP='UPDATE' THEN
                v_old_source_key:=CASE OLD.category
                    WHEN 'RENT' THEN 'rent:' || OLD.source_lease_id::text
                    WHEN 'UTILITIES' THEN 'utility:' || OLD.utility_consumption_period_id::text
                    WHEN 'SERVICE_CHARGES' THEN 'service:' || OLD.source_lease_id::text || ':'
                        || OLD.property_service_id::text
                    ELSE 'obligation:' || OLD.authorized_obligation_id::text
                END;
            END IF;
            FOR v_lock_key IN
                SELECT DISTINCT source_key
                FROM unnest(ARRAY[v_source_key,v_old_source_key]) AS source_keys(source_key)
                WHERE source_key IS NOT NULL ORDER BY source_key
            LOOP
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(v_lock_key,0)
                );
            END LOOP;
            IF NEW.category='RENT' THEN
                PERFORM 1 FROM app.invoice_lines AS line
                JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                WHERE line.id<>NEW.id AND line.category='RENT'
                  AND line.source_lease_id=NEW.source_lease_id
                  AND daterange(line.period_start,line.period_end,'[]')
                      && daterange(NEW.period_start,NEW.period_end,'[]')
                  AND invoice.status<>'VOID'
                FOR KEY SHARE OF invoice;
                IF FOUND THEN RAISE EXCEPTION 'Active Rent Invoice source period overlaps'
                    USING ERRCODE='23P01'; END IF;
            ELSIF NEW.category='SERVICE_CHARGES' THEN
                PERFORM 1 FROM app.invoice_lines AS line
                JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                WHERE line.id<>NEW.id AND line.category='SERVICE_CHARGES'
                  AND line.source_lease_id=NEW.source_lease_id
                  AND line.property_service_id=NEW.property_service_id
                  AND daterange(line.period_start,line.period_end,'[]')
                      && daterange(NEW.period_start,NEW.period_end,'[]')
                  AND invoice.status<>'VOID'
                FOR KEY SHARE OF invoice;
                IF FOUND THEN RAISE EXCEPTION 'Active Service Invoice source period overlaps'
                    USING ERRCODE='23P01'; END IF;
            ELSE
                PERFORM 1 FROM app.invoice_lines AS line
                JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                WHERE line.id<>NEW.id
                  AND line.authorized_obligation_id=NEW.authorized_obligation_id
                  AND invoice.status<>'VOID'
                FOR KEY SHARE OF invoice;
                IF FOUND THEN RAISE EXCEPTION 'Authorized obligation already has an active Invoice'
                    USING ERRCODE='23P01'; END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_active_invoice_source_claim()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF pg_catalog.pg_trigger_depth()<2 THEN
                RAISE EXCEPTION 'Active Invoice source claims are trigger-managed'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.sync_active_invoice_source_claim()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_status text;
        BEGIN
            IF TG_OP='DELETE' THEN
                DELETE FROM app.active_invoice_source_claims
                WHERE invoice_line_id=OLD.id;
                RETURN OLD;
            END IF;
            SELECT status INTO STRICT v_status
            FROM app.invoices WHERE id=NEW.invoice_id;
            IF v_status='VOID' OR NEW.category='UTILITIES' THEN
                DELETE FROM app.active_invoice_source_claims
                WHERE invoice_line_id=NEW.id;
            ELSE
                INSERT INTO app.active_invoice_source_claims(
                    invoice_line_id,invoice_id,category,source_lease_id,
                    property_service_id,authorized_obligation_id,period_start,period_end
                ) VALUES (
                    NEW.id,NEW.invoice_id,NEW.category,NEW.source_lease_id,
                    NEW.property_service_id,NEW.authorized_obligation_id,
                    NEW.period_start,NEW.period_end
                )
                ON CONFLICT (invoice_line_id) DO UPDATE SET
                    invoice_id=EXCLUDED.invoice_id,
                    category=EXCLUDED.category,
                    source_lease_id=EXCLUDED.source_lease_id,
                    property_service_id=EXCLUDED.property_service_id,
                    authorized_obligation_id=EXCLUDED.authorized_obligation_id,
                    period_start=EXCLUDED.period_start,
                    period_end=EXCLUDED.period_end;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.release_active_invoice_source_claims()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF OLD.status<>'VOID' AND NEW.status='VOID' THEN
                DELETE FROM app.active_invoice_source_claims
                WHERE invoice_id=NEW.id;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_invoice_issuance_lines()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice_id uuid; v_invoice app.invoices%ROWTYPE;
        DECLARE v_line app.invoice_lines%ROWTYPE;
        DECLARE v_obligation app.authorized_nonrecurring_obligations%ROWTYPE;
        DECLARE v_count bigint; v_total bigint; v_min date; v_max date; v_days bigint;
        BEGIN
            IF TG_TABLE_NAME='invoices' THEN
                v_invoice_id:=NEW.id;
                IF TG_OP<>'UPDATE' OR OLD.status<>'DRAFT' OR NEW.status='DRAFT' THEN
                    RETURN NEW;
                END IF;
            ELSE
                v_invoice_id:=NEW.invoice_id;
            END IF;
            SELECT * INTO v_invoice FROM app.invoices WHERE id=v_invoice_id;
            IF v_invoice.status<>'DRAFT'
                AND NOT (v_invoice.status='VOID' AND v_invoice.issued_at IS NULL)
            THEN
                FOR v_line IN SELECT * FROM app.invoice_lines WHERE invoice_id=v_invoice_id LOOP
                    IF v_line.created_at<v_invoice.created_at
                        OR v_line.created_at>v_invoice.issued_at
                        OR v_line.last_changed_at>v_invoice.issued_at
                    THEN RAISE EXCEPTION 'Invoice line chronology contradicts final Invoice'
                        USING ERRCODE='23514'; END IF;
                    IF EXISTS (
                        SELECT 1 FROM app.invoice_line_calculation_components AS component
                        WHERE component.invoice_line_id=v_line.id
                          AND component.last_changed_at>v_invoice.issued_at
                    ) THEN RAISE EXCEPTION
                        'Invoice component chronology contradicts final Invoice'
                        USING ERRCODE='23514'; END IF;
                    IF NOT (v_line.category=v_invoice.primary_category
                        OR (v_invoice.primary_category='RENT'
                            AND v_line.category='SERVICE_CHARGES'))
                    THEN RAISE EXCEPTION 'Invoice and line categories are inconsistent at issuance'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='RENT' AND (
                        v_line.source_lease_id IS DISTINCT FROM v_invoice.lease_id
                        OR v_line.period_start IS DISTINCT FROM v_invoice.billing_period_start
                        OR v_line.period_end IS DISTINCT FROM v_invoice.billing_period_end
                    ) THEN RAISE EXCEPTION 'Rent line contradicts final Invoice header'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='SERVICE_CHARGES' AND (
                        v_line.source_lease_id IS DISTINCT FROM v_invoice.lease_id
                        OR v_invoice.billing_period_start IS NULL
                        OR v_line.period_start<v_invoice.billing_period_start
                        OR v_line.period_end>v_invoice.billing_period_end
                        OR NOT EXISTS (
                            SELECT 1 FROM app.lease_service_terms AS term
                            JOIN app.property_service_approval_periods AS approval
                              ON approval.id=term.service_approval_period_id
                            WHERE term.id=v_line.lease_service_term_id
                              AND term.service_approval_period_id
                                  =v_line.service_approval_period_id
                              AND term.recorded_at<=v_invoice.issued_at
                              AND approval.approved_at<=v_invoice.issued_at
                        )
                        OR NOT EXISTS (
                            SELECT 1 FROM app.leases AS lease
                            WHERE lease.id=v_line.source_lease_id
                              AND v_line.period_start>=lease.start_date
                              AND (
                                  (lease.status='SIGNED'
                                      AND v_line.period_end<=lease.end_date)
                                  OR (lease.status='TERMINATED'
                                      AND lease.terminated_at>v_invoice.issued_at
                                      AND v_line.period_end<=lease.end_date)
                                  OR (
                                      lease.status='TERMINATED'
                                      AND v_line.period_start<=lease.actual_termination_date
                                      AND (
                                          v_line.period_end<=lease.actual_termination_date
                                          OR (
                                          v_line.period_end=(date_trunc(
                                              'month',lease.actual_termination_date
                                          ) + interval '1 month - 1 day')::date
                                              AND v_invoice.due_date_source='BR-SVC-013'
                                              AND lease.terminated_at<=v_invoice.issued_at
                                              AND EXISTS (
                                                  SELECT 1 FROM app.lease_commands AS command
                                                  WHERE command.lease_id=lease.id
                                                    AND command.action='lease.terminate'
                                                    AND command.governing_event_reference
                                                        ='BR-LEASE-021'
                                                    AND command.occurred_at=lease.terminated_at
                                                    AND command.reason=lease.termination_reason
                                                    AND command.result_snapshot->>'status'
                                                        ='TERMINATED'
                                                    AND command.result_snapshot
                                                        ->>'actual_termination_date'
                                                        =lease.actual_termination_date::text
                                              )
                                          )
                                      )
                                  )
                              )
                        )
                    ) THEN RAISE EXCEPTION 'Service line contradicts final Invoice evidence'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category IN ('RENT','SERVICE_CHARGES') AND EXISTS (
                        SELECT 1 FROM app.invoice_lines AS prior_line
                        JOIN app.invoices AS prior_invoice
                          ON prior_invoice.id=prior_line.invoice_id
                        LEFT JOIN app.invoice_void_events AS void_event
                          ON void_event.invoice_id=prior_invoice.id
                        WHERE prior_line.id<>v_line.id AND prior_invoice.status='VOID'
                          AND prior_line.category=v_line.category
                          AND prior_line.source_lease_id=v_line.source_lease_id
                          AND (
                              v_line.category='RENT'
                              OR prior_line.property_service_id=v_line.property_service_id
                          )
                          AND daterange(prior_line.period_start,prior_line.period_end,'[]')
                              && daterange(v_line.period_start,v_line.period_end,'[]')
                          AND (void_event.occurred_at IS NULL
                              OR void_event.occurred_at>=v_invoice.issued_at)
                    ) THEN RAISE EXCEPTION 'Replacement Invoice predates prior source VOID'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category IN ('DAMAGE_CHARGES','MISCELLANEOUS_CHARGES') THEN
                        SELECT * INTO v_obligation FROM app.authorized_nonrecurring_obligations
                        WHERE id=v_line.authorized_obligation_id;
                        IF v_obligation.customer_id<>v_invoice.customer_id
                            OR v_obligation.lease_id IS DISTINCT FROM v_invoice.lease_id
                            OR v_obligation.category<>v_line.category
                            OR v_obligation.authorized_amount_usd_cents<>v_line.amount_usd_cents
                            OR v_obligation.description<>v_line.description
                            OR v_obligation.governing_due_date<>v_invoice.due_date
                            OR v_obligation.due_date_source<>v_invoice.due_date_source
                            OR v_obligation.authorized_at>v_invoice.issued_at
                        THEN RAISE EXCEPTION
                            'Non-recurring line contradicts final Invoice evidence'
                            USING ERRCODE='23514'; END IF;
                        IF EXISTS (
                            SELECT 1 FROM app.invoice_lines AS prior_line
                            JOIN app.invoices AS prior_invoice
                              ON prior_invoice.id=prior_line.invoice_id
                            LEFT JOIN app.invoice_void_events AS void_event
                              ON void_event.invoice_id=prior_invoice.id
                            WHERE prior_line.id<>v_line.id
                              AND prior_line.authorized_obligation_id
                                  =v_line.authorized_obligation_id
                              AND prior_invoice.status='VOID'
                              AND (void_event.occurred_at IS NULL
                                  OR void_event.occurred_at>=v_invoice.issued_at)
                        ) THEN RAISE EXCEPTION
                            'Replacement Invoice predates prior obligation VOID'
                            USING ERRCODE='23514'; END IF;
                    END IF;
                    SELECT count(*),COALESCE(sum(amount_usd_cents),0),min(period_start),max(period_end),
                        COALESCE(sum(period_end-period_start+1),0)
                    INTO v_count,v_total,v_min,v_max,v_days
                    FROM app.invoice_line_calculation_components
                    WHERE invoice_line_id=v_line.id;
                    IF v_line.category IN ('RENT','SERVICE_CHARGES') AND (
                        v_count=0 OR v_total<>v_line.amount_usd_cents
                        OR v_min<>v_line.period_start OR v_max<>v_line.period_end
                        OR v_days<>(v_line.period_end-v_line.period_start+1)
                    ) THEN RAISE EXCEPTION 'Invoice line components do not reconcile'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category NOT IN ('RENT','SERVICE_CHARGES') AND v_count<>0 THEN
                        RAISE EXCEPTION 'Invoice line category cannot have calculation components'
                            USING ERRCODE='23514'; END IF;
                    IF v_line.category='RENT' AND EXISTS (
                        SELECT 1 FROM app.invoice_line_calculation_components AS component
                        WHERE component.invoice_line_id=v_line.id AND (
                            component.contractual_monthly_usd_cents
                                IS DISTINCT FROM v_line.contractual_monthly_usd_cents
                            OR component.billable_days IS NULL
                            OR component.calendar_days IS NULL
                            OR date_trunc('month',component.period_start)
                                <>date_trunc('month',component.period_end)
                            OR component.billable_days
                                <>component.period_end-component.period_start+1
                            OR component.calendar_days<>extract(day FROM (
                                date_trunc('month',component.period_start)
                                + interval '1 month - 1 day'
                            ))::smallint
                            OR component.amount_usd_cents<>round(
                                component.contractual_monthly_usd_cents::numeric
                                * component.billable_days / component.calendar_days,0
                            )::bigint
                            OR (component.component_kind IN (
                                'FULL_FOLLOWING_MONTH','FULL_RECURRING_MONTH'
                            ) AND (
                                component.period_start
                                    <>date_trunc('month',component.period_start)::date
                                OR component.billable_days<>component.calendar_days
                            ))
                            OR component.service_rate_id IS NOT NULL
                            OR component.service_monthly_rate_usd_cents IS NOT NULL
                        )
                    ) THEN RAISE EXCEPTION 'Rent component source is invalid'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='RENT' AND (
                            (v_count=1 AND NOT EXISTS (
                                SELECT 1
                                FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id
                                  AND v_line.billable_days
                                      IS NOT DISTINCT FROM component.billable_days
                                  AND v_line.calendar_days
                                      IS NOT DISTINCT FROM component.calendar_days
                            ))
                            OR (v_count=2 AND (
                                v_line.billable_days IS NOT NULL
                                OR v_line.calendar_days IS NOT NULL
                            ))
                        )
                    THEN RAISE EXCEPTION 'Rent line snapshots contradict components'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='RENT' AND (
                        (v_invoice.rent_billing_kind='RECURRING' AND (
                            v_count<>1 OR EXISTS (
                                SELECT 1 FROM app.invoice_line_calculation_components
                                WHERE invoice_line_id=v_line.id
                                  AND component_kind<>'FULL_RECURRING_MONTH'
                            )
                        ))
                        OR (v_invoice.rent_billing_kind='INITIAL' AND (
                            v_count<>CASE WHEN date_trunc(
                                'month',v_invoice.billing_period_start
                            )=date_trunc('month',v_invoice.billing_period_end) THEN 1 ELSE 2 END
                            OR EXISTS (
                                SELECT 1
                                FROM app.invoice_line_calculation_components
                                WHERE invoice_line_id=v_line.id
                                GROUP BY date_trunc('month',period_start)
                                HAVING count(*)>1
                            ) OR EXISTS (
                                SELECT 1 FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id AND NOT (
                                    (
                                        component.component_kind='PRORATED_MOVE_IN_MONTH'
                                        AND component.component_sequence=1
                                        AND component.period_start=v_invoice.billing_period_start
                                        AND component.period_end=LEAST(
                                            v_invoice.billing_period_end,
                                            (date_trunc(
                                                'month',v_invoice.billing_period_start
                                            ) + interval '1 month - 1 day')::date
                                        )
                                    ) OR (
                                        component.component_kind='FULL_FOLLOWING_MONTH'
                                        AND component.component_sequence=2
                                        AND date_trunc('month',v_invoice.billing_period_start)
                                            <>date_trunc('month',v_invoice.billing_period_end)
                                        AND component.period_start=(date_trunc(
                                            'month',v_invoice.billing_period_start
                                        ) + interval '1 month')::date
                                        AND component.period_end=v_invoice.billing_period_end
                                    )
                                )
                            )
                        ))
                    ) THEN RAISE EXCEPTION 'Rent component pattern is invalid'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='SERVICE_CHARGES' AND EXISTS (
                        SELECT 1 FROM app.invoice_line_calculation_components AS component
                        WHERE component.invoice_line_id=v_line.id AND (
                            component.service_rate_id IS NULL
                            OR component.contractual_monthly_usd_cents IS NOT NULL
                            OR component.service_monthly_rate_usd_cents IS NULL
                            OR component.billable_days IS NULL
                            OR component.calendar_days IS NULL
                            OR date_trunc('month',component.period_start)
                                <>date_trunc('month',component.period_end)
                            OR component.billable_days
                                <>component.period_end-component.period_start+1
                            OR component.calendar_days<>extract(day FROM (
                                date_trunc('month',component.period_start)
                                + interval '1 month - 1 day'
                            ))::smallint
                            OR component.amount_usd_cents<>round(
                                component.service_monthly_rate_usd_cents::numeric
                                * component.billable_days / component.calendar_days,0
                            )::bigint
                            OR (component.component_kind IN (
                                'FULL_FOLLOWING_MONTH','FULL_RECURRING_MONTH'
                            ) AND (
                                component.period_start
                                    <>date_trunc('month',component.period_start)::date
                                OR component.billable_days<>component.calendar_days
                            ))
                            OR NOT EXISTS (
                                SELECT 1 FROM app.service_rates AS rate
                                WHERE rate.id=component.service_rate_id
                                  AND rate.property_service_id=v_line.property_service_id
                                  AND rate.monthly_rate_usd_cents
                                      =component.service_monthly_rate_usd_cents
                                  AND rate.occurred_at<=v_invoice.issued_at
                                  AND rate.effective_date<=component.period_start
                                  AND NOT EXISTS (
                                      SELECT 1 FROM app.service_rates AS later
                                      WHERE later.property_service_id=rate.property_service_id
                                        AND later.occurred_at<=v_invoice.issued_at
                                        AND later.effective_date<=component.period_start
                                        AND later.effective_date>rate.effective_date
                                  )
                            )
                        )
                    ) THEN RAISE EXCEPTION 'Service component source is invalid'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='SERVICE_CHARGES' AND (
                        (v_count=1 AND NOT EXISTS (
                            SELECT 1
                            FROM app.invoice_line_calculation_components AS component
                            WHERE component.invoice_line_id=v_line.id
                              AND v_line.service_rate_id
                                  IS NOT DISTINCT FROM component.service_rate_id
                              AND v_line.contractual_monthly_usd_cents
                                  IS NOT DISTINCT FROM component.service_monthly_rate_usd_cents
                              AND v_line.billable_days
                                  IS NOT DISTINCT FROM component.billable_days
                              AND v_line.calendar_days
                                  IS NOT DISTINCT FROM component.calendar_days
                        ))
                        OR (v_count=2 AND (
                            v_line.billable_days IS NOT NULL
                            OR v_line.calendar_days IS NOT NULL
                            OR (
                                (SELECT count(DISTINCT (
                                    component.service_rate_id,
                                    component.service_monthly_rate_usd_cents
                                )) FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id)=1
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM app.invoice_line_calculation_components AS component
                                    WHERE component.invoice_line_id=v_line.id
                                      AND v_line.service_rate_id
                                          IS NOT DISTINCT FROM component.service_rate_id
                                      AND v_line.contractual_monthly_usd_cents
                                          IS NOT DISTINCT FROM
                                              component.service_monthly_rate_usd_cents
                                )
                            ) OR (
                                (SELECT count(DISTINCT (
                                    component.service_rate_id,
                                    component.service_monthly_rate_usd_cents
                                )) FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id)>1
                                AND (
                                    v_line.service_rate_id IS NOT NULL
                                    OR v_line.contractual_monthly_usd_cents IS NOT NULL
                                )
                            )
                        ))
                    ) THEN RAISE EXCEPTION 'Service line snapshots contradict components'
                        USING ERRCODE='23514'; END IF;
                    IF v_line.category='SERVICE_CHARGES' AND (
                        v_count NOT IN (1,2)
                        OR EXISTS (
                            SELECT 1
                            FROM app.invoice_line_calculation_components
                            WHERE invoice_line_id=v_line.id
                            GROUP BY date_trunc('month',period_start)
                            HAVING count(*)>1
                        )
                        OR (v_count=1 AND EXISTS (
                            SELECT 1
                            FROM app.invoice_line_calculation_components AS component
                            WHERE component.invoice_line_id=v_line.id AND NOT (
                                component.component_sequence=1
                                AND component.period_start=v_line.period_start
                                AND component.period_end=v_line.period_end
                                AND (
                                    (v_invoice.rent_billing_kind='INITIAL' AND (
                                        (
                                            component.component_kind='PRORATED_MOVE_IN_MONTH'
                                            AND date_trunc('month',component.period_start)
                                                =date_trunc(
                                                    'month',v_invoice.billing_period_start
                                                )
                                        ) OR (
                                            component.component_kind='FULL_FOLLOWING_MONTH'
                                            AND component.period_start=(date_trunc(
                                                'month',v_invoice.billing_period_start
                                            ) + interval '1 month')::date
                                        )
                                    ))
                                    OR (v_invoice.rent_billing_kind='RECURRING'
                                        AND component.component_kind='FULL_RECURRING_MONTH')
                                    OR (v_invoice.rent_billing_kind IS NULL
                                        AND component.component_kind IN (
                                            'FULL_RECURRING_MONTH','OTHER_APPROVED_COMPONENT'
                                        ))
                                )
                            )
                        ))
                        OR (v_count=2 AND (
                            v_invoice.rent_billing_kind IS DISTINCT FROM 'INITIAL'
                            OR NOT EXISTS (
                                SELECT 1
                                FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id
                                  AND component.component_sequence=1
                                  AND component.component_kind='PRORATED_MOVE_IN_MONTH'
                                  AND component.period_start=v_line.period_start
                                  AND component.period_end=(date_trunc(
                                      'month',v_line.period_start
                                  ) + interval '1 month - 1 day')::date
                            )
                            OR NOT EXISTS (
                                SELECT 1
                                FROM app.invoice_line_calculation_components AS component
                                WHERE component.invoice_line_id=v_line.id
                                  AND component.component_sequence=2
                                  AND component.component_kind='FULL_FOLLOWING_MONTH'
                                  AND component.period_start=(date_trunc(
                                      'month',v_line.period_start
                                  ) + interval '1 month')::date
                                  AND component.period_end=v_line.period_end
                            )
                        ))
                    ) THEN RAISE EXCEPTION 'Service component pattern is invalid'
                        USING ERRCODE='23514'; END IF;
                END LOOP;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_invoice_serialization_guard()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF pg_catalog.pg_trigger_depth()<2 THEN
                RAISE EXCEPTION 'Invoice serialization guards are internal'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.advance_invoice_serialization_guard(p_guard_key text)
        RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            INSERT INTO app.invoice_serialization_guards(guard_key,revision,updated_at)
            VALUES (p_guard_key,1,statement_timestamp())
            ON CONFLICT (guard_key) DO UPDATE
            SET revision=app.invoice_serialization_guards.revision+1,
                updated_at=statement_timestamp();
        END $$;

        CREATE FUNCTION app.lock_invoice_source_evidence(
            p_invoice_id uuid,p_final_lease_id uuid
        )
        RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_key text;
        BEGIN
            FOR v_key IN
                SELECT DISTINCT source_key FROM (
                    SELECT 'invoice-lease:' || p_final_lease_id::text AS source_key
                    WHERE p_final_lease_id IS NOT NULL
                    UNION ALL
                    SELECT 'invoice-service:' || line.property_service_id::text
                    FROM app.invoice_lines AS line
                    WHERE line.invoice_id=p_invoice_id
                      AND line.property_service_id IS NOT NULL
                    UNION ALL
                    SELECT 'invoice-obligation:' || line.authorized_obligation_id::text
                    FROM app.invoice_lines AS line
                    WHERE line.invoice_id=p_invoice_id
                      AND line.authorized_obligation_id IS NOT NULL
                ) AS source_keys
                ORDER BY source_key
            LOOP
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(v_key,0)
                );
                PERFORM app.advance_invoice_serialization_guard(v_key);
            END LOOP;
        END $$;

        CREATE FUNCTION app.serialize_authorized_invoice_obligation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_key text;
        BEGIN
            v_key:='invoice-obligation:' || NEW.id::text;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(v_key,0)
            );
            PERFORM app.advance_invoice_serialization_guard(v_key);
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.serialize_invoice_source_write()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_key text; v_property_id uuid;
        DECLARE v_new_lease_id uuid; v_old_lease_id uuid;
        BEGIN
            IF TG_TABLE_NAME='occupancies' THEN
                IF TG_OP<>'DELETE' THEN v_new_lease_id:=NEW.lease_id; END IF;
                IF TG_OP<>'INSERT' THEN v_old_lease_id:=OLD.lease_id; END IF;
                FOR v_key IN
                    SELECT DISTINCT source_key FROM (
                        SELECT 'invoice-lease:' || lease_id::text AS source_key
                        FROM unnest(ARRAY[v_new_lease_id,v_old_lease_id]) AS lease_ids(lease_id)
                        WHERE lease_id IS NOT NULL
                        UNION ALL
                        SELECT 'billing-run-eligibility:' || unit.property_id::text
                        FROM unnest(ARRAY[v_new_lease_id,v_old_lease_id]) AS lease_ids(lease_id)
                        JOIN app.leases AS lease ON lease.id=lease_ids.lease_id
                        JOIN app.units AS unit ON unit.id=lease.unit_id
                        WHERE lease_ids.lease_id IS NOT NULL
                    ) AS source_keys
                    WHERE source_key IS NOT NULL ORDER BY source_key
                LOOP
                    PERFORM pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(v_key,0)
                    );
                    PERFORM app.advance_invoice_serialization_guard(v_key);
                END LOOP;
                IF TG_OP='INSERT' AND EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    JOIN app.occupancies AS source ON source.id=invoice.source_occupancy_id
                    WHERE invoice.lease_id=NEW.lease_id
                      AND invoice.rent_billing_kind='INITIAL'
                      AND invoice.issued_at IS NOT NULL
                      AND NEW.move_in_date<source.move_in_date
                ) THEN RAISE EXCEPTION
                    'Occupancy would invalidate issued Initial Rent source evidence'
                    USING ERRCODE='23514'; END IF;
                IF TG_OP='UPDATE'
                    AND (NEW.lease_id IS DISTINCT FROM OLD.lease_id
                        OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                        OR NEW.move_in_date IS DISTINCT FROM OLD.move_in_date)
                    AND EXISTS (
                        SELECT 1 FROM app.invoices AS invoice
                        JOIN app.occupancies AS source
                          ON source.id=invoice.source_occupancy_id
                        WHERE invoice.rent_billing_kind='INITIAL'
                          AND invoice.issued_at IS NOT NULL
                          AND (
                              invoice.source_occupancy_id=OLD.id
                              OR (invoice.lease_id=NEW.lease_id
                                  AND NEW.move_in_date<source.move_in_date)
                          )
                    )
                THEN RAISE EXCEPTION
                    'Occupancy would invalidate issued Initial Rent source evidence'
                    USING ERRCODE='23514'; END IF;
            ELSIF TG_TABLE_NAME='leases' THEN
                SELECT unit.property_id INTO STRICT v_property_id
                FROM app.units AS unit WHERE unit.id=NEW.unit_id;
                FOR v_key IN
                    SELECT source_key FROM unnest(ARRAY[
                        'invoice-lease:' || NEW.id::text,
                        'billing-run-eligibility:' || v_property_id::text
                    ]) AS source_keys(source_key)
                    ORDER BY source_key
                LOOP
                    PERFORM pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(v_key,0)
                    );
                    PERFORM app.advance_invoice_serialization_guard(v_key);
                END LOOP;
                IF TG_OP='UPDATE' AND NEW.status='TERMINATED'
                    AND (NEW.status IS DISTINCT FROM OLD.status
                        OR NEW.terminated_at IS DISTINCT FROM OLD.terminated_at
                        OR NEW.actual_termination_date IS DISTINCT FROM OLD.actual_termination_date)
                    AND EXISTS (
                        SELECT 1 FROM app.invoices AS invoice
                        JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
                        WHERE invoice.lease_id=NEW.id AND invoice.issued_at IS NOT NULL
                          AND NEW.terminated_at<=invoice.issued_at
                          AND (
                              line.period_start>NEW.actual_termination_date
                              OR (line.period_end>NEW.actual_termination_date AND NOT (
                                  line.period_end=(date_trunc(
                                      'month',NEW.actual_termination_date
                                  ) + interval '1 month - 1 day')::date
                                  AND ((line.category='SERVICE_CHARGES'
                                          AND invoice.due_date_source='BR-SVC-013')
                                      OR (line.category='RENT'
                                          AND invoice.due_date_source='BR-RENT-024'))
                              ))
                          )
                    )
                THEN RAISE EXCEPTION
                    'Lease termination would invalidate issued Invoice source evidence'
                    USING ERRCODE='23514'; END IF;
            ELSIF TG_TABLE_NAME='service_rates' THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                    'invoice-service:' || NEW.property_service_id::text,0
                ));
                PERFORM app.advance_invoice_serialization_guard(
                    'invoice-service:' || NEW.property_service_id::text
                );
                IF EXISTS (
                    SELECT 1
                    FROM app.invoice_line_calculation_components AS component
                    JOIN app.invoice_lines AS line ON line.id=component.invoice_line_id
                    JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                    JOIN app.service_rates AS selected ON selected.id=component.service_rate_id
                    WHERE line.property_service_id=NEW.property_service_id
                      AND invoice.issued_at IS NOT NULL
                      AND NEW.occurred_at<=invoice.issued_at
                      AND NEW.effective_date<=component.period_start
                      AND NEW.effective_date>selected.effective_date
                ) THEN RAISE EXCEPTION
                    'Retroactive Service rate would invalidate issued Invoice source evidence'
                    USING ERRCODE='23514'; END IF;
            ELSIF TG_TABLE_NAME='property_service_approval_periods' THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                    'invoice-service:' || NEW.property_service_id::text,0
                ));
                PERFORM app.advance_invoice_serialization_guard(
                    'invoice-service:' || NEW.property_service_id::text
                );
                IF TG_OP='UPDATE' AND NEW.effective_through IS NOT NULL AND EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                    WHERE line.service_approval_period_id=NEW.id
                      AND invoice.issued_at IS NOT NULL
                      AND line.period_end>NEW.effective_through
                ) THEN RAISE EXCEPTION
                    'Service approval closure would invalidate issued Invoice source evidence'
                    USING ERRCODE='23514'; END IF;
            ELSIF TG_TABLE_NAME='lease_service_terms' THEN
                FOR v_key IN SELECT source_key FROM (VALUES
                    ('invoice-lease:' || NEW.lease_id::text),
                    ('invoice-service:' || NEW.property_service_id::text)
                ) AS source_keys(source_key) ORDER BY source_key
                LOOP
                    PERFORM pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(v_key,0)
                    );
                    PERFORM app.advance_invoice_serialization_guard(v_key);
                END LOOP;
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_invoice_lease_source_write()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NEW.status='TERMINATED'
                AND (NEW.status IS DISTINCT FROM OLD.status
                    OR NEW.terminated_at IS DISTINCT FROM OLD.terminated_at
                    OR NEW.actual_termination_date IS DISTINCT FROM OLD.actual_termination_date)
                AND EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
                    WHERE invoice.lease_id=NEW.id AND invoice.issued_at IS NOT NULL
                      AND NEW.terminated_at<=invoice.issued_at
                      AND (
                          line.period_start>NEW.actual_termination_date
                          OR (line.period_end>NEW.actual_termination_date AND NOT (
                              line.period_end=(date_trunc(
                                  'month',NEW.actual_termination_date
                              ) + interval '1 month - 1 day')::date
                              AND ((line.category='SERVICE_CHARGES'
                                      AND invoice.due_date_source='BR-SVC-013')
                                  OR (line.category='RENT'
                                      AND invoice.due_date_source='BR-RENT-024'))
                              AND EXISTS (
                                  SELECT 1 FROM app.lease_commands AS command
                                  WHERE command.lease_id=NEW.id
                                    AND command.action='lease.terminate'
                                    AND command.governing_event_reference='BR-LEASE-021'
                                    AND command.occurred_at=NEW.terminated_at
                                    AND command.reason=NEW.termination_reason
                                    AND command.result_snapshot->>'status'='TERMINATED'
                                    AND command.result_snapshot->>'actual_termination_date'
                                        =NEW.actual_termination_date::text
                              )
                          ))
                      )
                )
            THEN RAISE EXCEPTION
                'Lease termination contradicts issued Invoice source evidence'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_invoice_header_history()
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
                PERFORM app.assert_active_financial_actor(
                    NEW.created_by,v_invoice_property_id
                );
                PERFORM app.assert_active_financial_actor(
                    NEW.updated_by,v_invoice_property_id
                );
                PERFORM app.advance_invoice_serialization_guard(
                    'invoice-financial:' || NEW.id::text
                );
                IF NEW.status<>'DRAFT' THEN
                    RAISE EXCEPTION 'Invoice must begin in DRAFT status'
                        USING ERRCODE='23514';
                END IF;
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
                        OR v_run_kind<>'RENT' OR NEW.primary_category<>'RENT'
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
                        OR NOT EXISTS (
                            SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                            JOIN app.billing_run_attempts AS source_attempt
                              ON source_attempt.billing_run_id=eligible.billing_run_id
                            WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                              AND eligible.source_kind='LEASE_PERIOD'
                              AND eligible.source_id=NEW.lease_id
                              AND eligible.source_period_start=NEW.billing_period_start
                              AND eligible.source_period_end=NEW.billing_period_end
                        )
                    THEN RAISE EXCEPTION 'Generated Invoice requires an active Billing Run attempt'
                        USING ERRCODE='55000'; END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Invoice history cannot be deleted'
                USING ERRCODE='55000'; END IF;
            PERFORM app.assert_active_financial_actor(
                NEW.updated_by,v_invoice_property_id
            );
            IF OLD.status='DRAFT' AND NEW.status NOT IN ('DRAFT','VOID') THEN
                PERFORM app.assert_active_financial_actor(
                    NEW.issued_by,v_invoice_property_id
                );
            END IF;
            IF NEW.originating_billing_run_attempt_id IS NULL AND EXISTS (
                SELECT 1 FROM app.actor_identities AS identity
                WHERE identity.identity_kind='SERVICE'
                  AND identity.actor_id IN (NEW.updated_by,NEW.issued_by)
            ) THEN RAISE EXCEPTION
                'Service-authored Invoice requires an active Billing Run attempt'
                USING ERRCODE='55000'; END IF;
            IF NEW.id<>OLD.id OR NEW.created_at<>OLD.created_at OR NEW.created_by<>OLD.created_by
                OR NEW.version<>OLD.version+1 OR NEW.updated_at<OLD.updated_at
            THEN RAISE EXCEPTION 'Invoice identity and provenance are protected'
                USING ERRCODE='55000'; END IF;
            IF NEW.originating_billing_run_attempt_id
                IS DISTINCT FROM OLD.originating_billing_run_attempt_id
            THEN RAISE EXCEPTION 'Billing Run provenance is write-once'
                USING ERRCODE='55000'; END IF;
            IF NEW.originating_billing_run_attempt_id IS NOT NULL
                AND OLD.status='DRAFT' AND NEW.status='DRAFT'
            THEN
                RAISE EXCEPTION 'Generated DRAFT identity and detail are immutable'
                    USING ERRCODE='55000';
            END IF;
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
                        OR EXISTS (
                            SELECT 1 FROM app.invoice_lines AS line
                            WHERE line.invoice_id=NEW.id
                              AND line.created_by<>v_run_system_actor_id
                        )
                    OR v_run_kind<>'RENT' OR NEW.primary_category<>'RENT'
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
                    OR NOT EXISTS (
                        SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                        JOIN app.billing_run_attempts AS source_attempt
                          ON source_attempt.billing_run_id=eligible.billing_run_id
                        WHERE source_attempt.id=NEW.originating_billing_run_attempt_id
                          AND eligible.source_kind='LEASE_PERIOD'
                          AND eligible.source_id=NEW.lease_id
                          AND eligible.source_period_start=NEW.billing_period_start
                          AND eligible.source_period_end=NEW.billing_period_end
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
            THEN
                PERFORM app.lock_invoice_source_evidence(NEW.id,NEW.lease_id);
            END IF;
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
                OR NEW.due_date_rule<>OLD.due_date_rule OR NEW.due_date_source<>OLD.due_date_source
                OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                OR NEW.issued_by IS DISTINCT FROM OLD.issued_by
            ) THEN RAISE EXCEPTION 'Issued Invoice facts are immutable' USING ERRCODE='55000'; END IF;
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

        CREATE FUNCTION app.stamp_invoice_detail_change()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_TABLE_NAME='invoice_lines' THEN
                IF TG_OP='INSERT' THEN NEW.last_changed_by:=NEW.created_by; END IF;
                NEW.last_changed_at:=GREATEST(statement_timestamp(),NEW.created_at);
            ELSE
                IF TG_OP='INSERT' THEN
                    NEW.created_at:=statement_timestamp();
                    NEW.last_changed_by:=NEW.created_by;
                END IF;
                NEW.last_changed_at:=GREATEST(statement_timestamp(),NEW.created_at);
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_invoice_detail_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_status text; v_parent_id uuid; v_invoice_id uuid; v_origin_attempt_id uuid;
        DECLARE v_system_actor_id uuid; v_line_actor_id uuid; v_invoice_actor_id uuid;
        DECLARE v_invoice_property_id uuid;
        BEGIN
            IF TG_TABLE_NAME='invoice_lines' THEN
                IF TG_OP='UPDATE' AND (
                    NEW.id<>OLD.id OR NEW.invoice_id<>OLD.invoice_id
                    OR NEW.created_at<>OLD.created_at OR NEW.created_by<>OLD.created_by
                ) THEN RAISE EXCEPTION 'Invoice line identity and parent are protected'
                    USING ERRCODE='55000'; END IF;
                IF TG_OP='INSERT' THEN v_parent_id:=NEW.invoice_id;
                ELSE v_parent_id:=OLD.invoice_id; END IF;
                SELECT status,originating_billing_run_attempt_id,updated_by
                    INTO v_status,v_origin_attempt_id,v_invoice_actor_id FROM app.invoices
                    WHERE id=v_parent_id FOR UPDATE;
                v_invoice_id:=v_parent_id;
            ELSE
                IF TG_OP='UPDATE' AND (
                    NEW.id<>OLD.id OR NEW.invoice_line_id<>OLD.invoice_line_id
                    OR NEW.created_at<>OLD.created_at OR NEW.created_by<>OLD.created_by
                ) THEN RAISE EXCEPTION 'Invoice component identity and parent are protected'
                    USING ERRCODE='55000'; END IF;
                IF TG_OP='INSERT' THEN v_parent_id:=NEW.invoice_line_id;
                ELSE v_parent_id:=OLD.invoice_line_id; END IF;
                SELECT invoice.id,invoice.status,invoice.originating_billing_run_attempt_id,
                    line.created_by,invoice.updated_by
                    INTO v_invoice_id,v_status,v_origin_attempt_id,v_line_actor_id,
                        v_invoice_actor_id
                    FROM app.invoice_lines AS line
                JOIN app.invoices AS invoice ON invoice.id=line.invoice_id
                WHERE line.id=v_parent_id FOR UPDATE OF invoice;
            END IF;
            IF v_status<>'DRAFT' THEN RAISE EXCEPTION 'Issued Invoice detail is immutable'
                USING ERRCODE='55000'; END IF;
            SELECT unit.property_id INTO v_invoice_property_id
            FROM app.invoices AS invoice
            JOIN app.leases AS lease ON lease.id=invoice.lease_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE invoice.id=v_invoice_id;
            IF TG_OP='DELETE' THEN
                PERFORM app.assert_active_financial_actor(
                    v_invoice_actor_id,v_invoice_property_id
                );
            ELSE
                PERFORM app.assert_active_financial_actor(
                    NEW.last_changed_by,v_invoice_property_id
                );
                IF TG_OP='INSERT' THEN
                    PERFORM app.assert_active_financial_actor(
                        NEW.created_by,v_invoice_property_id
                    );
                END IF;
            END IF;
            IF TG_OP<>'DELETE' AND NEW.last_changed_by IS DISTINCT FROM v_invoice_actor_id THEN
                RAISE EXCEPTION 'Invoice detail editor must match the Invoice updater'
                    USING ERRCODE='55000';
            END IF;
            IF v_origin_attempt_id IS NOT NULL THEN
                SELECT run.system_actor_id INTO v_system_actor_id
                FROM app.billing_run_attempts AS attempt
                JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                WHERE attempt.id=v_origin_attempt_id;
                IF TG_OP<>'INSERT' THEN
                    RAISE EXCEPTION 'Generated Invoice detail is immutable and actor-bound'
                        USING ERRCODE='55000';
                END IF;
                IF TG_TABLE_NAME='invoice_lines' THEN
                    IF NEW.created_by<>v_system_actor_id THEN
                        RAISE EXCEPTION 'Generated Invoice detail is immutable and actor-bound'
                            USING ERRCODE='55000';
                    END IF;
                ELSIF NEW.created_by<>v_system_actor_id
                    OR v_line_actor_id<>v_system_actor_id
                THEN
                    RAISE EXCEPTION 'Generated Invoice detail is immutable and actor-bound'
                        USING ERRCODE='55000';
                END IF;
            END IF;
            IF TG_OP IN ('UPDATE','DELETE') THEN
                PERFORM app.record_invoice_draft_revision(
                    v_invoice_id,
                    CASE TG_TABLE_NAME WHEN 'invoice_lines' THEN 'LINE' ELSE 'COMPONENT' END,
                    OLD.id,TG_OP,to_jsonb(OLD),
                    CASE WHEN TG_OP='UPDATE' THEN to_jsonb(NEW) ELSE NULL END,
                    CASE WHEN TG_OP='UPDATE' THEN NEW.last_changed_by
                        ELSE v_invoice_actor_id END
                );
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.reject_invoice_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Financial event history is append-only' USING ERRCODE='55000'; END $$;

        CREATE FUNCTION app.validate_invoice_adjustment_effect()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_status text; v_line_id uuid; v_invoice_id uuid;
        DECLARE v_issued_at timestamptz; v_updated_at timestamptz; v_source_at timestamptz;
        DECLARE v_event_effect bigint; v_prior_event_obligation bigint;
        DECLARE v_source_type text; v_source_amount bigint;
        DECLARE v_line_obligation bigint; v_invoice_obligation bigint;
        DECLARE v_event_invoice_obligation bigint;
        BEGIN
            IF TG_TABLE_NAME='invoice_adjustments' THEN
                v_line_id:=NEW.invoice_line_id;
                v_event_effect:=CASE NEW.adjustment_type
                    WHEN 'DEBIT' THEN NEW.amount_usd_cents ELSE -NEW.amount_usd_cents END;
            ELSE
                SELECT invoice_line_id,occurred_at,adjustment_type,amount_usd_cents
                    INTO v_line_id,v_source_at,v_source_type,v_source_amount
                    FROM app.invoice_adjustments
                    WHERE id=NEW.invoice_adjustment_id;
                IF NEW.occurred_at<v_source_at THEN
                    RAISE EXCEPTION 'Invoice Adjustment reversal predates its source'
                        USING ERRCODE='23514'; END IF;
                v_event_effect:=CASE v_source_type
                    WHEN 'DEBIT' THEN -v_source_amount ELSE v_source_amount END;
            END IF;
            SELECT invoice.id,invoice.status,invoice.issued_at,invoice.updated_at
            INTO v_invoice_id,v_status,v_issued_at,v_updated_at
            FROM app.invoice_lines AS line
            JOIN app.invoices AS invoice ON invoice.id=line.invoice_id WHERE line.id=v_line_id;
            SELECT app.invoice_adjusted_line_obligation_at(v_line_id,NEW.occurred_at)
            INTO v_line_obligation;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation_at(id,NEW.occurred_at)),0)
            INTO v_event_invoice_obligation FROM app.invoice_lines WHERE invoice_id=v_invoice_id;
            v_prior_event_obligation:=v_event_invoice_obligation-v_event_effect;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation(id)),0)
            INTO v_invoice_obligation FROM app.invoice_lines WHERE invoice_id=v_invoice_id;
            IF v_status NOT IN ('UNPAID','PAID')
                OR NEW.occurred_at<v_issued_at
                OR v_line_obligation<0
                OR v_prior_event_obligation<0
                OR (
                    (v_event_invoice_obligation=0)
                        IS DISTINCT FROM (v_prior_event_obligation=0)
                    AND v_updated_at<NEW.occurred_at
                )
                OR (((v_event_invoice_obligation=0)
                        IS DISTINCT FROM (v_prior_event_obligation=0)) AND EXISTS (
                    SELECT 1 FROM (
                        SELECT adjustment.occurred_at AS event_at
                        FROM app.invoice_adjustments AS adjustment
                        WHERE adjustment.invoice_id=v_invoice_id
                        UNION ALL
                        SELECT reversal.occurred_at
                        FROM app.invoice_adjustments AS adjustment
                        JOIN app.invoice_adjustment_reversals AS reversal
                          ON reversal.invoice_adjustment_id=adjustment.id
                        WHERE adjustment.invoice_id=v_invoice_id
                    ) AS later_event
                    WHERE later_event.event_at>NEW.occurred_at
                ))
                OR (v_invoice_obligation=0 AND v_status<>'PAID')
                OR (v_invoice_obligation>0 AND v_status<>'UNPAID')
            THEN RAISE EXCEPTION 'Invoice Adjustment would violate the issued obligation'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.serialize_invoice_adjustment_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_line_id uuid; v_invoice_id uuid; v_latest_at timestamptz;
        DECLARE v_decision_finalized_at timestamptz;
        BEGIN
            IF TG_TABLE_NAME='invoice_adjustments' THEN
                v_line_id:=NEW.invoice_line_id; v_invoice_id:=NEW.invoice_id;
            ELSE
                SELECT invoice_line_id,invoice_id INTO v_line_id,v_invoice_id
                    FROM app.invoice_adjustments
                    WHERE id=NEW.invoice_adjustment_id;
            END IF;
            PERFORM 1 FROM app.invoices WHERE id=v_invoice_id FOR UPDATE;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('invoice-adjustment:' || v_line_id::text,0)
            );
            PERFORM app.advance_invoice_serialization_guard(
                'invoice-financial:' || v_invoice_id::text
            );
            IF TG_TABLE_NAME='invoice_adjustments' THEN
                IF EXISTS (
                    SELECT 1 FROM app.invoice_adjustments
                    WHERE invoice_line_id=NEW.invoice_line_id
                      AND source_reference=NEW.source_reference
                ) THEN RETURN NEW; END IF;
            ELSE
                IF EXISTS (
                    SELECT 1 FROM app.invoice_adjustment_reversals
                    WHERE invoice_adjustment_id=NEW.invoice_adjustment_id
                ) THEN RETURN NEW; END IF;
            END IF;
            SELECT max(event_at) INTO v_latest_at FROM (
                SELECT adjustment.occurred_at AS event_at
                FROM app.invoice_adjustments AS adjustment
                WHERE adjustment.invoice_id=v_invoice_id
                UNION ALL
                SELECT reversal.occurred_at
                FROM app.invoice_adjustments AS adjustment
                JOIN app.invoice_adjustment_reversals AS reversal
                  ON reversal.invoice_adjustment_id=adjustment.id
                WHERE adjustment.invoice_id=v_invoice_id
            ) AS financial_events;
            SELECT finalized_at INTO v_decision_finalized_at
            FROM app.late_payment_decisions WHERE source_invoice_id=v_invoice_id;
            IF NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)
                OR NEW.occurred_at<=COALESCE(v_decision_finalized_at,'-infinity'::timestamptz)
            THEN RAISE EXCEPTION 'Invoice Adjustment chronology is invalid'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_invoice_void_event()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_status text; v_issued_at timestamptz; v_created_at timestamptz;
        DECLARE v_updated_at timestamptz; v_origin_attempt_id uuid;
        DECLARE v_attempt_outcome text;
        DECLARE v_run_status text; v_run_completed_at timestamptz;
        DECLARE v_invoice_property_id uuid;
        BEGIN
            SELECT status,issued_at,created_at,updated_at,originating_billing_run_attempt_id
                INTO v_status,v_issued_at,v_created_at,v_updated_at,v_origin_attempt_id
                FROM app.invoices
                WHERE id=NEW.invoice_id FOR UPDATE;
            SELECT unit.property_id INTO v_invoice_property_id
            FROM app.invoices AS invoice
            JOIN app.leases AS lease ON lease.id=invoice.lease_id
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE invoice.id=NEW.invoice_id;
            PERFORM app.assert_active_financial_actor(
                NEW.actor_id,v_invoice_property_id
            );
            IF v_origin_attempt_id IS NOT NULL THEN
                SELECT attempt.outcome,run.status,run.completed_at
                    INTO v_attempt_outcome,v_run_status,v_run_completed_at
                FROM app.billing_run_attempts AS attempt
                JOIN app.billing_runs AS run ON run.id=attempt.billing_run_id
                WHERE attempt.id=v_origin_attempt_id;
            END IF;
            IF v_status<>'VOID'
                OR (v_issued_at IS NULL AND NEW.occurred_at<v_created_at)
                OR (v_issued_at IS NOT NULL AND NEW.occurred_at<=v_issued_at)
                OR v_updated_at<NEW.occurred_at
                OR EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    WHERE line.invoice_id=NEW.invoice_id
                      AND (line.created_at>=NEW.occurred_at
                          OR line.last_changed_at>=NEW.occurred_at)
                )
                OR EXISTS (
                    SELECT 1 FROM app.invoice_lines AS line
                    JOIN app.invoice_line_calculation_components AS component
                      ON component.invoice_line_id=line.id
                    WHERE line.invoice_id=NEW.invoice_id
                      AND (component.created_at>=NEW.occurred_at
                          OR component.last_changed_at>=NEW.occurred_at)
                )
                OR EXISTS (
                    SELECT 1 FROM app.billing_run_items AS item
                    WHERE item.invoice_id=NEW.invoice_id
                      AND item.recorded_at>=NEW.occurred_at
                )
                OR EXISTS (
                    SELECT 1
                    FROM app.billing_runs AS run
                    JOIN LATERAL (
                        SELECT attempt.attempt_number,attempt.outcome
                        FROM app.billing_run_attempts AS attempt
                        WHERE attempt.billing_run_id=run.id
                        ORDER BY attempt.attempt_number DESC
                        LIMIT 1
                    ) AS latest_attempt ON latest_attempt.outcome='SUCCEEDED'
                    WHERE EXISTS (
                        SELECT 1
                        FROM app.billing_run_eligible_sources AS eligible
                        JOIN LATERAL (
                            SELECT item.invoice_id,item.outcome
                            FROM app.billing_run_items AS item
                            JOIN app.billing_run_attempts AS attempt
                              ON attempt.id=item.billing_run_attempt_id
                            WHERE item.billing_run_id=run.id
                              AND attempt.attempt_number<=latest_attempt.attempt_number
                              AND item.source_kind=eligible.source_kind
                              AND item.source_id=eligible.source_id
                              AND item.source_period_start=eligible.source_period_start
                              AND item.source_period_end=eligible.source_period_end
                            ORDER BY attempt.attempt_number DESC
                            LIMIT 1
                        ) AS latest_item ON latest_item.outcome IN ('GENERATED','SKIPPED')
                        WHERE eligible.billing_run_id=run.id
                          AND latest_item.invoice_id=NEW.invoice_id
                    ) AND (
                        run.status<>'SUCCEEDED'
                        OR run.completed_at IS NULL
                        OR NEW.occurred_at<=run.completed_at
                    )
                )
                OR (v_attempt_outcome='SUCCEEDED' AND v_run_status<>'SUCCEEDED')
                OR (v_run_status='SUCCEEDED' AND (
                    v_run_completed_at IS NULL OR NEW.occurred_at<=v_run_completed_at
                ))
                OR EXISTS (
                    SELECT 1 FROM app.invoice_adjustments AS adjustment
                    WHERE adjustment.invoice_id=NEW.invoice_id
                      AND adjustment.occurred_at>=NEW.occurred_at
                )
                OR EXISTS (
                    SELECT 1 FROM app.invoice_adjustments AS adjustment
                    JOIN app.invoice_adjustment_reversals AS reversal
                      ON reversal.invoice_adjustment_id=adjustment.id
                    WHERE adjustment.invoice_id=NEW.invoice_id
                      AND reversal.occurred_at>=NEW.occurred_at
                )
                OR EXISTS (SELECT 1 FROM app.invoice_adjustments AS adjustment
                    LEFT JOIN app.invoice_adjustment_reversals AS reversal
                      ON reversal.invoice_adjustment_id=adjustment.id
                    WHERE adjustment.invoice_id=NEW.invoice_id AND reversal.id IS NULL)
                OR EXISTS (
                    SELECT 1 FROM app.late_payment_decisions AS decision
                    WHERE decision.source_invoice_id=NEW.invoice_id
                      AND decision.finalized_at>=NEW.occurred_at
                )
                OR EXISTS (
                    SELECT 1 FROM app.late_payment_charges AS charge
                    WHERE charge.source_invoice_id=NEW.invoice_id
                      AND (charge.created_at>=NEW.occurred_at OR NOT EXISTS (
                          SELECT 1 FROM app.late_payment_charge_corrections AS correction
                          WHERE correction.late_payment_charge_id=charge.id
                            AND correction.correction_kind='CHARGE_REVERSAL'
                      ) OR EXISTS (
                          SELECT 1 FROM app.late_payment_charge_corrections AS correction
                          WHERE correction.late_payment_charge_id=charge.id
                            AND correction.occurred_at>=NEW.occurred_at
                      ))
                )
            THEN RAISE EXCEPTION 'Invoice VOID dependencies are not resolved'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_late_payment_decision()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice app.invoices%ROWTYPE; v_balance bigint; v_default bigint;
        BEGIN
            SELECT * INTO v_invoice FROM app.invoices WHERE id=NEW.source_invoice_id FOR UPDATE;
            SELECT COALESCE(sum(app.invoice_adjusted_line_obligation_at(id,NEW.assessed_at)),0)
                INTO v_balance FROM app.invoice_lines WHERE invoice_id=v_invoice.id;
            v_default:=(v_balance+5)/10;
            IF v_invoice.customer_id<>NEW.customer_id OR v_invoice.due_date<>NEW.source_due_date
                OR v_invoice.lease_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM app.leases AS lease
                    WHERE lease.id=v_invoice.lease_id
                      AND lease.status IN ('SIGNED','TERMINATED')
                )
                OR v_invoice.status<>'UNPAID'
                OR NEW.assessed_at<v_invoice.issued_at
                OR v_balance<>NEW.overdue_balance_at_assessment_usd_cents
                OR v_default<>NEW.calculated_default_amount_usd_cents
                OR NEW.source_due_date>=timezone('Asia/Phnom_Penh',NEW.assessed_at)::date
                OR EXISTS (
                    SELECT 1 FROM app.invoice_adjustments AS adjustment
                    WHERE adjustment.invoice_id=NEW.source_invoice_id
                      AND adjustment.occurred_at>=NEW.assessed_at
                      AND adjustment.occurred_at<=NEW.finalized_at
                )
                OR EXISTS (
                    SELECT 1 FROM app.invoice_adjustments AS adjustment
                    JOIN app.invoice_adjustment_reversals AS reversal
                      ON reversal.invoice_adjustment_id=adjustment.id
                    WHERE adjustment.invoice_id=NEW.source_invoice_id
                      AND reversal.occurred_at>=NEW.assessed_at
                      AND reversal.occurred_at<=NEW.finalized_at
                )
            THEN RAISE EXCEPTION 'Late-payment assessment snapshot is invalid'
                USING ERRCODE='23514'; END IF;
            IF NEW.approved_amount_usd_cents>0 AND NOT EXISTS (
                SELECT 1 FROM app.late_payment_charges AS charge
                WHERE charge.late_payment_decision_id=NEW.id
                  AND charge.source_invoice_id=NEW.source_invoice_id
                  AND charge.customer_id=NEW.customer_id
                  AND charge.original_amount_usd_cents=NEW.approved_amount_usd_cents
                  AND charge.payable_at=NEW.finalized_at
            ) THEN RAISE EXCEPTION 'Positive late-payment decision requires its Charge'
                USING ERRCODE='23514'; END IF;
            IF NEW.approved_amount_usd_cents=0 AND EXISTS (
                SELECT 1 FROM app.late_payment_charges WHERE late_payment_decision_id=NEW.id
            ) THEN RAISE EXCEPTION 'Waived late-payment decision cannot create a Charge'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.serialize_late_payment_source()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice_id uuid; v_charge_id uuid; v_key text;
        BEGIN
            v_invoice_id:=NEW.source_invoice_id;
            IF TG_TABLE_NAME='late_payment_charges' THEN v_charge_id:=NEW.id; END IF;
            PERFORM 1 FROM app.invoices WHERE id=v_invoice_id FOR UPDATE;
            FOR v_key IN SELECT guard_key FROM (VALUES
                ('invoice-financial:' || v_invoice_id::text),
                (CASE WHEN v_charge_id IS NOT NULL
                    THEN 'late-charge:' || v_charge_id::text END)
            ) AS guard_keys(guard_key)
            WHERE guard_key IS NOT NULL ORDER BY guard_key
            LOOP
                PERFORM app.advance_invoice_serialization_guard(v_key);
            END LOOP;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_late_payment_charge()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_decision app.late_payment_decisions%ROWTYPE;
        BEGIN
            SELECT * INTO v_decision FROM app.late_payment_decisions
                WHERE id=NEW.late_payment_decision_id;
            IF v_decision.approved_amount_usd_cents<=0
                OR v_decision.source_invoice_id<>NEW.source_invoice_id
                OR v_decision.customer_id<>NEW.customer_id
                OR v_decision.approved_amount_usd_cents<>NEW.original_amount_usd_cents
                OR v_decision.finalized_at<>NEW.payable_at
                OR NEW.created_at<v_decision.finalized_at
            THEN RAISE EXCEPTION 'Late-payment Charge does not match its final decision'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.validate_late_charge_correction()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_original bigint; v_current bigint; v_invoice_id uuid; v_invoice_status text;
        DECLARE v_charge_created_at timestamptz;
        DECLARE v_source app.late_payment_charge_corrections%ROWTYPE;
        BEGIN
            SELECT source_invoice_id,created_at INTO v_invoice_id,v_charge_created_at
            FROM app.late_payment_charges WHERE id=NEW.late_payment_charge_id;
            SELECT status INTO v_invoice_status FROM app.invoices
                WHERE id=v_invoice_id FOR UPDATE;
            SELECT original_amount_usd_cents INTO v_original FROM app.late_payment_charges
                WHERE id=NEW.late_payment_charge_id FOR UPDATE;
            IF v_invoice_status='VOID' OR NEW.occurred_at<v_charge_created_at THEN
                RAISE EXCEPTION 'Late-payment Charge correction chronology is invalid'
                    USING ERRCODE='23514'; END IF;
            SELECT v_original + COALESCE(sum(CASE correction_kind
                WHEN 'REDUCTION' THEN -amount_usd_cents WHEN 'CHARGE_REVERSAL' THEN -amount_usd_cents
                ELSE amount_usd_cents END),0) INTO v_current
            FROM app.late_payment_charge_corrections
            WHERE late_payment_charge_id=NEW.late_payment_charge_id
              AND occurred_at<NEW.occurred_at;
            IF EXISTS (
                SELECT 1 FROM app.late_payment_charge_corrections
                WHERE late_payment_charge_id=NEW.late_payment_charge_id
                  AND correction_kind='CHARGE_REVERSAL' AND occurred_at<NEW.occurred_at
            ) THEN RAISE EXCEPTION 'A reversed late-payment Charge is terminal'
                USING ERRCODE='55000'; END IF;
            IF v_current<>NEW.previous_obligation_usd_cents THEN
                RAISE EXCEPTION 'Late-payment correction previous balance is stale'
                    USING ERRCODE='40001'; END IF;
            IF NEW.correction_kind='REDUCTION_REVERSAL' THEN
                SELECT * INTO v_source FROM app.late_payment_charge_corrections
                    WHERE id=NEW.reverses_correction_id;
                IF v_source.late_payment_charge_id<>NEW.late_payment_charge_id
                    OR v_source.correction_kind<>'REDUCTION'
                    OR v_source.amount_usd_cents<>NEW.amount_usd_cents
                    OR NEW.occurred_at<v_source.occurred_at
                THEN RAISE EXCEPTION 'Reduction reversal source is invalid'
                    USING ERRCODE='23514'; END IF;
            END IF;
            IF NEW.correction_kind='CHARGE_REVERSAL'
                AND (NEW.amount_usd_cents<>v_current OR NEW.resulting_obligation_usd_cents<>0)
            THEN RAISE EXCEPTION 'Charge reversal must reverse the complete current obligation'
                USING ERRCODE='23514'; END IF;
            v_current:=v_current+CASE WHEN NEW.correction_kind='REDUCTION_REVERSAL'
                THEN NEW.amount_usd_cents ELSE -NEW.amount_usd_cents END;
            IF (NEW.correction_kind='REDUCTION' AND v_current=0)
                OR v_current<>NEW.resulting_obligation_usd_cents
                OR v_current<0 OR v_current>v_original
            THEN RAISE EXCEPTION 'Late-payment correction resulting balance is invalid'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.serialize_late_charge_correction()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_invoice_id uuid; v_charge_created_at timestamptz; v_latest_at timestamptz;
        DECLARE v_key text;
        BEGIN
            SELECT source_invoice_id,created_at INTO v_invoice_id,v_charge_created_at
            FROM app.late_payment_charges WHERE id=NEW.late_payment_charge_id FOR UPDATE;
            PERFORM 1 FROM app.invoices WHERE id=v_invoice_id FOR UPDATE;
            FOR v_key IN SELECT guard_key FROM (VALUES
                ('invoice-financial:' || v_invoice_id::text),
                ('late-charge:' || NEW.late_payment_charge_id::text)
            ) AS guard_keys(guard_key) ORDER BY guard_key
            LOOP
                PERFORM app.advance_invoice_serialization_guard(v_key);
            END LOOP;
            IF EXISTS (
                SELECT 1 FROM app.late_payment_charge_corrections
                WHERE late_payment_charge_id=NEW.late_payment_charge_id
                  AND correlation_id=NEW.correlation_id
            ) THEN RETURN NEW; END IF;
            SELECT max(occurred_at) INTO v_latest_at
            FROM app.late_payment_charge_corrections
            WHERE late_payment_charge_id=NEW.late_payment_charge_id;
            IF NEW.occurred_at<v_charge_created_at
                OR NEW.occurred_at<=COALESCE(v_latest_at,'-infinity'::timestamptz)
            THEN RAISE EXCEPTION 'Late-payment Charge correction chronology is invalid'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.billing_run_has_unresolved_sources(
            p_billing_run_id uuid,p_through_attempt_number integer
        ) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.billing_run_items AS failed_item
                JOIN app.billing_run_attempts AS failed_attempt
                  ON failed_attempt.id=failed_item.billing_run_attempt_id
                WHERE failed_item.billing_run_id=p_billing_run_id
                  AND failed_attempt.attempt_number<=p_through_attempt_number
                  AND failed_item.outcome IN ('CONFLICT','ERROR')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM app.billing_run_items AS resolution
                      JOIN app.billing_run_attempts AS resolution_attempt
                        ON resolution_attempt.id=resolution.billing_run_attempt_id
                      WHERE resolution.billing_run_id=p_billing_run_id
                        AND resolution_attempt.attempt_number>failed_attempt.attempt_number
                        AND resolution_attempt.attempt_number<=p_through_attempt_number
                        AND resolution.source_kind=failed_item.source_kind
                        AND resolution.source_id=failed_item.source_id
                        AND resolution.source_period_start
                            IS NOT DISTINCT FROM failed_item.source_period_start
                        AND resolution.source_period_end
                            IS NOT DISTINCT FROM failed_item.source_period_end
                        AND resolution.outcome IN ('GENERATED','SKIPPED')
                  )
            )
        $$;

        CREATE FUNCTION app.billing_run_has_missing_eligible_sources(
            p_billing_run_id uuid,p_through_attempt_number integer
        ) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
            SELECT EXISTS (
                SELECT 1
                FROM app.billing_run_eligible_sources AS eligible
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
                          ORDER BY attempt.attempt_number DESC
                          LIMIT 1
                      ) AS latest
                      WHERE latest.outcome IN ('GENERATED','SKIPPED')
                        AND (
                            (latest.invoice_id IS NULL
                                AND latest.diagnostic_code='SOURCE_NO_LONGER_ELIGIBLE')
                            OR EXISTS (
                                SELECT 1 FROM app.invoices AS invoice
                                WHERE invoice.id=latest.invoice_id AND invoice.status<>'VOID'
                            )
                        )
                  )
            )
        $$;

        CREATE FUNCTION app.snapshot_billing_run_eligible_sources()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NEW.predecessor_run_id IS NOT NULL THEN
                INSERT INTO app.billing_run_eligible_sources(
                    billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                    snapshotted_at
                )
                SELECT NEW.id,source_kind,source_id,source_period_start,source_period_end,
                    statement_timestamp()
                FROM app.billing_run_eligible_sources
                WHERE billing_run_id=NEW.predecessor_run_id;
                RETURN NEW;
            END IF;
            INSERT INTO app.billing_run_eligible_sources(
                billing_run_id,source_kind,source_id,source_period_start,source_period_end,
                snapshotted_at
            )
            SELECT NEW.id,'LEASE_PERIOD',lease.id,NEW.period_start,NEW.period_end,
                statement_timestamp()
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id=lease.unit_id
            WHERE NEW.run_kind='RENT' AND unit.property_id=NEW.property_id
              AND app.lease_is_billable_for_recurring_period(
                  lease.id,NEW.period_start,NEW.period_end,statement_timestamp()
              );
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_billing_run_eligible_source_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF TG_OP='INSERT' AND pg_catalog.pg_trigger_depth()=2 THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Billing Run eligible-source snapshot is sealed'
                USING ERRCODE='55000';
        END $$;

        CREATE FUNCTION app.protect_billing_run_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_latest_attempt_id uuid; v_latest_attempt_number integer; v_latest_outcome text;
        DECLARE v_latest_completed_at timestamptz; v_latest_diagnostic text;
        DECLARE v_latest_item_at timestamptz;
        DECLARE v_predecessor app.billing_runs%ROWTYPE;
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM app.actor_identities AS identity
                    WHERE identity.actor_id=NEW.system_actor_id
                      AND identity.identity_kind='SERVICE'
                ) THEN RAISE EXCEPTION
                    'Billing Run requires a scoped service principal'
                    USING ERRCODE='55000'; END IF;
                PERFORM app.assert_active_financial_actor(
                    NEW.system_actor_id,NEW.property_id
                );
                IF NEW.status<>'RUNNING' THEN
                    RAISE EXCEPTION 'Billing Run must begin in RUNNING status'
                        USING ERRCODE='23514'; END IF;
                IF NEW.run_kind='RENT' AND (
                    extract(day FROM NEW.business_date)<>25
                    OR NEW.period_start<>(date_trunc('month',NEW.business_date)::date
                        + interval '1 month')::date
                    OR NEW.period_end<>(date_trunc('month',NEW.business_date)::date
                        + interval '2 months - 1 day')::date
                    OR timezone('Asia/Phnom_Penh',NEW.started_at)::date<NEW.business_date
                ) THEN RAISE EXCEPTION 'Rent Billing Run schedule and period are invalid'
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
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(
                        'billing-run:' || NEW.property_id::text || ':' || NEW.run_kind,
                        0
                    )
                );
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
                EXISTS (
                    SELECT 1 FROM app.billing_run_items
                    WHERE billing_run_attempt_id=v_latest_attempt_id
                      AND outcome IN ('CONFLICT','ERROR')
                ) OR app.billing_run_has_unresolved_sources(OLD.id,v_latest_attempt_number)
                  OR app.billing_run_has_missing_eligible_sources(
                      OLD.id,v_latest_attempt_number
                  )
            ) THEN RAISE EXCEPTION 'Successful Billing Run cannot retain unresolved errors'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_billing_run_attempt_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_parent_status text; v_parent_started_at timestamptz; v_expected_attempt integer;
        DECLARE v_previous_completed_at timestamptz; v_previous_outcome text;
        DECLARE v_latest_item_at timestamptz;
        DECLARE v_property_id uuid; v_system_actor_id uuid;
        DECLARE v_referenced_invoice_id uuid;
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Billing Run attempt history cannot be deleted'
                USING ERRCODE='55000'; END IF;
            SELECT status,started_at,property_id,system_actor_id
                INTO v_parent_status,v_parent_started_at,v_property_id,v_system_actor_id
                FROM app.billing_runs
                WHERE id=COALESCE(NEW.billing_run_id,OLD.billing_run_id) FOR UPDATE;
            IF v_parent_status<>'RUNNING' THEN
                RAISE EXCEPTION 'Terminal Billing Run evidence cannot be changed'
                    USING ERRCODE='55000'; END IF;
            IF TG_OP='INSERT' THEN
                PERFORM app.assert_active_financial_actor(
                    v_system_actor_id,v_property_id
                );
                SELECT COALESCE(max(attempt_number),0)+1 INTO v_expected_attempt
                FROM app.billing_run_attempts WHERE billing_run_id=NEW.billing_run_id;
                SELECT completed_at,outcome INTO v_previous_completed_at,v_previous_outcome
                FROM app.billing_run_attempts WHERE billing_run_id=NEW.billing_run_id
                ORDER BY attempt_number DESC LIMIT 1;
                IF NEW.outcome<>'RUNNING'
                    OR NEW.completed_at IS NOT NULL OR NEW.diagnostic_code IS NOT NULL
                    OR NEW.started_at<v_parent_started_at
                    OR NEW.attempt_number<>v_expected_attempt
                    OR (v_expected_attempt>1 AND (
                        v_previous_completed_at IS NULL
                        OR v_previous_outcome<>'FAILED'
                        OR NEW.started_at<v_previous_completed_at
                    ))
                    OR EXISTS (
                        SELECT 1 FROM app.billing_run_attempts
                        WHERE billing_run_id=NEW.billing_run_id AND outcome='RUNNING'
                    )
                THEN RAISE EXCEPTION 'Billing Run attempt sequence or chronology is invalid'
                    USING ERRCODE='23514'; END IF;
            END IF;
            IF TG_OP='UPDATE' AND (
                OLD.outcome<>'RUNNING' OR NEW.id<>OLD.id
                OR NEW.billing_run_id<>OLD.billing_run_id
                OR NEW.attempt_number<>OLD.attempt_number OR NEW.started_at<>OLD.started_at
                OR NEW.outcome='RUNNING'
            ) THEN RAISE EXCEPTION 'Billing Run attempt identity and terminal history are protected'
                USING ERRCODE='55000'; END IF;
            IF TG_OP='UPDATE' THEN
                FOR v_referenced_invoice_id IN
                    SELECT DISTINCT invoice_id FROM (
                        SELECT invoice.id AS invoice_id
                        FROM app.invoices AS invoice
                        WHERE invoice.originating_billing_run_attempt_id=NEW.id
                        UNION ALL
                        SELECT latest.invoice_id
                        FROM app.billing_run_eligible_sources AS eligible
                        JOIN LATERAL (
                            SELECT item.invoice_id,item.outcome
                            FROM app.billing_run_items AS item
                            JOIN app.billing_run_attempts AS attempt
                              ON attempt.id=item.billing_run_attempt_id
                            WHERE item.billing_run_id=NEW.billing_run_id
                              AND attempt.attempt_number<=NEW.attempt_number
                              AND item.source_kind=eligible.source_kind
                              AND item.source_id=eligible.source_id
                              AND item.source_period_start=eligible.source_period_start
                              AND item.source_period_end=eligible.source_period_end
                            ORDER BY attempt.attempt_number DESC
                            LIMIT 1
                        ) AS latest ON latest.outcome IN ('GENERATED','SKIPPED')
                        WHERE eligible.billing_run_id=NEW.billing_run_id
                          AND latest.invoice_id IS NOT NULL
                    ) AS referenced_invoices
                    ORDER BY invoice_id
                LOOP
                    PERFORM app.advance_invoice_serialization_guard(
                        'invoice-financial:' || v_referenced_invoice_id::text
                    );
                END LOOP;
            END IF;
            IF TG_OP='UPDATE' AND NEW.outcome='SUCCEEDED' AND (
                EXISTS (
                    SELECT 1 FROM app.billing_run_items
                    WHERE billing_run_attempt_id=NEW.id AND outcome IN ('CONFLICT','ERROR')
                ) OR app.billing_run_has_unresolved_sources(
                    NEW.billing_run_id,NEW.attempt_number
                ) OR app.billing_run_has_missing_eligible_sources(
                    NEW.billing_run_id,NEW.attempt_number
                )
            ) THEN RAISE EXCEPTION 'Successful Billing Run attempt cannot retain unresolved errors'
                USING ERRCODE='23514'; END IF;
            IF TG_OP='UPDATE' THEN
                SELECT max(recorded_at) INTO v_latest_item_at
                FROM app.billing_run_items WHERE billing_run_attempt_id=NEW.id;
                IF NEW.completed_at<COALESCE(v_latest_item_at,'-infinity'::timestamptz)
                    OR EXISTS (
                        SELECT 1 FROM app.invoices AS invoice
                        WHERE invoice.originating_billing_run_attempt_id=NEW.id
                          AND (
                              (NEW.outcome='SUCCEEDED' AND invoice.status='VOID')
                              OR (
                                  invoice.status<>'VOID'
                                  AND NOT EXISTS (
                                      SELECT 1 FROM app.billing_run_items AS item
                                      WHERE item.billing_run_attempt_id=NEW.id
                                        AND item.invoice_id=invoice.id
                                        AND item.outcome='GENERATED'
                                  )
                              )
                          )
                    )
                THEN
                    RAISE EXCEPTION 'Billing Run attempt completes before its evidence'
                        USING ERRCODE='23514'; END IF;
            END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.protect_billing_run_item_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE v_parent_status text; v_attempt_status text; v_run_kind text;
        DECLARE v_property_id uuid; v_attempt_started_at timestamptz;
        DECLARE v_system_actor_id uuid;
        DECLARE v_attempt_run_id uuid;
        DECLARE v_run_period_start date; v_run_period_end date;
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
            PERFORM app.assert_active_financial_actor(
                v_system_actor_id,v_property_id
            );
            IF v_parent_status IS DISTINCT FROM 'RUNNING'
                OR v_attempt_status IS DISTINCT FROM 'RUNNING'
                OR v_attempt_run_id IS DISTINCT FROM NEW.billing_run_id
                OR NEW.recorded_at<v_attempt_started_at
                OR NEW.source_period_start<>v_run_period_start
                OR NEW.source_period_end<>v_run_period_end
            THEN
                RAISE EXCEPTION 'Terminal Billing Run evidence cannot be changed'
                    USING ERRCODE='55000'; END IF;
            IF (v_run_kind='RENT' AND NEW.source_kind<>'LEASE_PERIOD')
                OR (v_run_kind='UTILITIES' AND NEW.source_kind<>'UTILITY_PERIOD')
            THEN RAISE EXCEPTION 'Billing Run item source kind contradicts its run'
                USING ERRCODE='23514'; END IF;
            IF v_run_kind='RENT' AND NOT EXISTS (
                SELECT 1 FROM app.billing_run_eligible_sources AS eligible
                WHERE eligible.billing_run_id=NEW.billing_run_id
                  AND eligible.source_kind=NEW.source_kind
                  AND eligible.source_id=NEW.source_id
                  AND eligible.source_period_start=NEW.source_period_start
                  AND eligible.source_period_end=NEW.source_period_end
            ) THEN RAISE EXCEPTION 'Rent Billing Run item Lease source is invalid'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='SKIPPED'
                AND NEW.diagnostic_code='ACTIVE_INVOICE_ALREADY_EXISTS'
                AND NOT EXISTS (
                SELECT 1 FROM app.invoices AS invoice
                WHERE invoice.id=NEW.invoice_id AND invoice.status<>'VOID'
                  AND invoice.issued_at IS NOT NULL
                  AND invoice.issued_at<=NEW.recorded_at
                  AND invoice.primary_category='RENT'
                  AND invoice.lease_id=NEW.source_id
                  AND invoice.billing_period_start=NEW.source_period_start
                  AND invoice.billing_period_end=NEW.source_period_end
                  AND invoice.originating_billing_run_attempt_id
                      IS DISTINCT FROM NEW.billing_run_attempt_id
            ) THEN RAISE EXCEPTION 'Skipped source requires one matching active Invoice'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='SKIPPED'
                AND NEW.diagnostic_code='SOURCE_NO_LONGER_ELIGIBLE'
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
                  AND NOT EXISTS (
                      SELECT 1 FROM app.invoice_lines AS line
                      WHERE line.invoice_id=invoice.id
                        AND line.created_by<>v_system_actor_id
                  )
            ) THEN RAISE EXCEPTION 'Generated Invoice was not created by this Billing Run attempt'
                USING ERRCODE='23514'; END IF;
            IF NEW.outcome='GENERATED' AND (
                (v_run_kind='RENT' AND NOT EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    WHERE invoice.id=NEW.invoice_id AND invoice.status='UNPAID'
                      AND invoice.primary_category='RENT' AND invoice.lease_id=NEW.source_id
                      AND invoice.invoice_date=(
                          SELECT run.business_date FROM app.billing_runs AS run
                          WHERE run.id=NEW.billing_run_id
                      )
                      AND invoice.billing_period_start=NEW.source_period_start
                      AND invoice.billing_period_end=NEW.source_period_end
                ))
                OR (v_run_kind='UTILITIES' AND NOT EXISTS (
                    SELECT 1 FROM app.invoices AS invoice
                    JOIN app.invoice_lines AS line ON line.invoice_id=invoice.id
                    JOIN app.utility_rates AS rate ON rate.id=line.utility_rate_id
                    WHERE invoice.id=NEW.invoice_id AND invoice.status='UNPAID'
                      AND invoice.primary_category='UTILITIES'
                      AND line.utility_consumption_period_id=NEW.source_id
                      AND line.period_start=NEW.source_period_start
                      AND line.period_end=NEW.source_period_end
                      AND rate.property_id=v_property_id
                ))
            ) THEN RAISE EXCEPTION 'Generated Billing Run item Invoice provenance is invalid'
                USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;

        CREATE FUNCTION app.reject_invoice_storage_truncate()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Financial storage cannot be truncated' USING ERRCODE='55000'; END $$;
        """
    )
    op.execute(
        r"""
        CREATE TRIGGER actor_identities_protect BEFORE INSERT OR UPDATE OR DELETE
            ON app.actor_identities FOR EACH ROW EXECUTE FUNCTION app.protect_actor_identity();
        CREATE TRIGGER user_accounts_sync_actor_identity AFTER INSERT ON app.user_accounts
            FOR EACH ROW EXECUTE FUNCTION app.sync_human_actor_identity();
        CREATE TRIGGER billing_service_principals_protect BEFORE INSERT OR UPDATE OR DELETE
            ON app.billing_service_principals FOR EACH ROW
            EXECUTE FUNCTION app.protect_billing_service_principal();
        CREATE TRIGGER invoice_draft_revision_events_protect BEFORE INSERT OR UPDATE OR DELETE
            ON app.invoice_draft_revision_events FOR EACH ROW
            EXECUTE FUNCTION app.protect_invoice_draft_revision_event();
        CREATE TRIGGER authorized_nonrecurring_obligations_active_actor
            BEFORE INSERT ON app.authorized_nonrecurring_obligations FOR EACH ROW
            EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER invoice_adjustments_active_actor BEFORE INSERT ON app.invoice_adjustments
            FOR EACH ROW EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER invoice_adjustment_reversals_active_actor
            BEFORE INSERT ON app.invoice_adjustment_reversals FOR EACH ROW
            EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER late_payment_decisions_active_actor
            BEFORE INSERT ON app.late_payment_decisions FOR EACH ROW
            EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER late_payment_charges_active_actor
            BEFORE INSERT ON app.late_payment_charges FOR EACH ROW
            EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER late_payment_charge_corrections_active_actor
            BEFORE INSERT ON app.late_payment_charge_corrections FOR EACH ROW
            EXECUTE FUNCTION app.enforce_active_human_financial_actor();
        CREATE TRIGGER leases_00_serialize_invoice_source BEFORE INSERT OR UPDATE ON app.leases
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_source_write();
        CREATE TRIGGER occupancies_00_serialize_invoice_source
            BEFORE INSERT OR UPDATE OR DELETE ON app.occupancies
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_source_write();
        CREATE CONSTRAINT TRIGGER leases_validate_invoice_source
            AFTER UPDATE ON app.leases DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_lease_source_write();
        CREATE TRIGGER service_rates_00_serialize_invoice_source BEFORE INSERT ON app.service_rates
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_source_write();
        CREATE TRIGGER property_service_approval_periods_00_serialize_invoice_source
            BEFORE INSERT OR UPDATE ON app.property_service_approval_periods
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_source_write();
        CREATE TRIGGER lease_service_terms_00_serialize_invoice_source
            BEFORE INSERT ON app.lease_service_terms
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_source_write();
        CREATE TRIGGER authorized_nonrecurring_obligations_00_serialize_source
            BEFORE INSERT ON app.authorized_nonrecurring_obligations
            FOR EACH ROW EXECUTE FUNCTION app.serialize_authorized_invoice_obligation();
        CREATE TRIGGER invoices_protect_history BEFORE INSERT OR UPDATE OR DELETE ON app.invoices
            FOR EACH ROW EXECUTE FUNCTION app.protect_invoice_header_history();
        CREATE TRIGGER invoices_release_active_source_claims AFTER UPDATE OF status ON app.invoices
            FOR EACH ROW EXECUTE FUNCTION app.release_active_invoice_source_claims();
        CREATE CONSTRAINT TRIGGER invoices_validate AFTER INSERT OR UPDATE ON app.invoices
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_record();
        CREATE CONSTRAINT TRIGGER invoices_validate_lines AFTER INSERT OR UPDATE ON app.invoices
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_issuance_lines();
        CREATE TRIGGER invoice_lines_00_serialize_source BEFORE INSERT OR UPDATE ON app.invoice_lines
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_line_source();
        CREATE TRIGGER invoice_lines_05_stamp_change BEFORE INSERT OR UPDATE ON app.invoice_lines
            FOR EACH ROW EXECUTE FUNCTION app.stamp_invoice_detail_change();
        CREATE TRIGGER invoice_lines_10_protect_history BEFORE INSERT OR UPDATE OR DELETE ON app.invoice_lines
            FOR EACH ROW EXECUTE FUNCTION app.protect_invoice_detail_history();
        CREATE TRIGGER invoice_lines_20_delete_source_claim BEFORE DELETE ON app.invoice_lines
            FOR EACH ROW EXECUTE FUNCTION app.sync_active_invoice_source_claim();
        CREATE TRIGGER invoice_lines_20_sync_source_claim AFTER INSERT OR UPDATE ON app.invoice_lines
            FOR EACH ROW EXECUTE FUNCTION app.sync_active_invoice_source_claim();
        CREATE CONSTRAINT TRIGGER invoice_lines_validate AFTER INSERT OR UPDATE ON app.invoice_lines
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_line();
        CREATE CONSTRAINT TRIGGER invoice_lines_validate_issuance AFTER INSERT OR UPDATE ON app.invoice_lines
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_issuance_lines();
        CREATE TRIGGER invoice_components_00_stamp_change BEFORE INSERT OR UPDATE
            ON app.invoice_line_calculation_components FOR EACH ROW
            EXECUTE FUNCTION app.stamp_invoice_detail_change();
        CREATE TRIGGER invoice_components_10_protect_history BEFORE INSERT OR UPDATE OR DELETE
            ON app.invoice_line_calculation_components FOR EACH ROW
            EXECUTE FUNCTION app.protect_invoice_detail_history();
        CREATE CONSTRAINT TRIGGER invoice_adjustments_validate AFTER INSERT ON app.invoice_adjustments
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_adjustment_effect();
        CREATE TRIGGER invoice_adjustments_serialize_source BEFORE INSERT ON app.invoice_adjustments
            FOR EACH ROW EXECUTE FUNCTION app.serialize_invoice_adjustment_source();
        CREATE CONSTRAINT TRIGGER invoice_adjustment_reversals_validate
            AFTER INSERT ON app.invoice_adjustment_reversals DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_adjustment_effect();
        CREATE TRIGGER invoice_adjustment_reversals_serialize_source
            BEFORE INSERT ON app.invoice_adjustment_reversals FOR EACH ROW
            EXECUTE FUNCTION app.serialize_invoice_adjustment_source();
        CREATE CONSTRAINT TRIGGER invoice_void_events_validate AFTER INSERT ON app.invoice_void_events
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_invoice_void_event();
        CREATE TRIGGER late_payment_decisions_serialize_source
            BEFORE INSERT ON app.late_payment_decisions FOR EACH ROW
            EXECUTE FUNCTION app.serialize_late_payment_source();
        CREATE CONSTRAINT TRIGGER late_payment_decisions_validate AFTER INSERT ON app.late_payment_decisions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_late_payment_decision();
        CREATE TRIGGER late_payment_charges_serialize_source
            BEFORE INSERT ON app.late_payment_charges FOR EACH ROW
            EXECUTE FUNCTION app.serialize_late_payment_source();
        CREATE CONSTRAINT TRIGGER late_payment_charges_validate AFTER INSERT ON app.late_payment_charges
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_late_payment_charge();
        CREATE CONSTRAINT TRIGGER late_charge_corrections_validate
            AFTER INSERT ON app.late_payment_charge_corrections DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION app.validate_late_charge_correction();
        CREATE TRIGGER late_charge_corrections_serialize_source
            BEFORE INSERT ON app.late_payment_charge_corrections FOR EACH ROW
            EXECUTE FUNCTION app.serialize_late_charge_correction();
        CREATE TRIGGER billing_runs_protect_history BEFORE INSERT OR UPDATE OR DELETE ON app.billing_runs
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_history();
        CREATE TRIGGER billing_runs_snapshot_eligible_sources AFTER INSERT ON app.billing_runs
            FOR EACH ROW EXECUTE FUNCTION app.snapshot_billing_run_eligible_sources();
        CREATE TRIGGER billing_run_eligible_sources_protect_history
            BEFORE INSERT OR UPDATE OR DELETE ON app.billing_run_eligible_sources
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_eligible_source_history();
        CREATE TRIGGER billing_run_attempts_protect_history
            BEFORE INSERT OR UPDATE OR DELETE ON app.billing_run_attempts
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_attempt_history();
        CREATE TRIGGER billing_run_items_protect_history
            BEFORE INSERT OR UPDATE OR DELETE ON app.billing_run_items
            FOR EACH ROW EXECUTE FUNCTION app.protect_billing_run_item_history();
        CREATE TRIGGER active_invoice_source_claims_protect
            BEFORE INSERT OR UPDATE OR DELETE ON app.active_invoice_source_claims
            FOR EACH ROW EXECUTE FUNCTION app.protect_active_invoice_source_claim();
        CREATE TRIGGER invoice_serialization_guards_protect
            BEFORE INSERT OR UPDATE OR DELETE ON app.invoice_serialization_guards
            FOR EACH ROW EXECUTE FUNCTION app.protect_invoice_serialization_guard();
        """
    )
    append_only_tables = (
        "authorized_nonrecurring_obligations",
        "invoice_adjustments",
        "invoice_adjustment_reversals",
        "invoice_void_events",
        "late_payment_decisions",
        "late_payment_charges",
        "late_payment_charge_corrections",
    )
    all_tables = (
        "actor_identities",
        "billing_service_principals",
        "invoices",
        "authorized_nonrecurring_obligations",
        "invoice_lines",
        "active_invoice_source_claims",
        "invoice_line_calculation_components",
        "invoice_draft_revision_events",
        "invoice_adjustments",
        "invoice_adjustment_reversals",
        "invoice_void_events",
        "late_payment_decisions",
        "late_payment_charges",
        "late_payment_charge_corrections",
        "billing_runs",
        "billing_run_eligible_sources",
        "billing_run_attempts",
        "billing_run_items",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_invoice_append_only_mutation()"
        )
    for table in all_tables:
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_invoice_storage_truncate()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime, prm_financial")
    op.execute(
        "CREATE TRIGGER invoice_serialization_guards_reject_truncate "
        "BEFORE TRUNCATE ON app.invoice_serialization_guards FOR EACH STATEMENT "
        "EXECUTE FUNCTION app.reject_invoice_storage_truncate()"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.invoice_serialization_guards "
        "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
    )
    for function in (
        "app.protect_actor_identity()",
        "app.sync_human_actor_identity()",
        "app.assert_active_financial_actor(uuid,uuid)",
        "app.enforce_active_human_financial_actor()",
        "app.protect_billing_service_principal()",
        "app.protect_invoice_draft_revision_event()",
        "app.record_invoice_draft_revision(uuid,text,uuid,text,jsonb,jsonb,uuid)",
        "app.invoice_adjusted_line_obligation(uuid)",
        "app.invoice_adjusted_line_obligation_at(uuid,timestamp with time zone)",
        "app.lease_is_billable_for_recurring_period(uuid,date,date,timestamp with time zone)",
        "app.validate_invoice_record()",
        "app.validate_invoice_line()",
        "app.serialize_invoice_line_source()",
        "app.protect_invoice_serialization_guard()",
        "app.advance_invoice_serialization_guard(text)",
        "app.protect_active_invoice_source_claim()",
        "app.sync_active_invoice_source_claim()",
        "app.release_active_invoice_source_claims()",
        "app.validate_invoice_issuance_lines()",
        "app.lock_invoice_source_evidence(uuid,uuid)",
        "app.serialize_authorized_invoice_obligation()",
        "app.serialize_invoice_source_write()",
        "app.validate_invoice_lease_source_write()",
        "app.protect_invoice_header_history()",
        "app.stamp_invoice_detail_change()",
        "app.protect_invoice_detail_history()",
        "app.reject_invoice_append_only_mutation()",
        "app.validate_invoice_adjustment_effect()",
        "app.serialize_invoice_adjustment_source()",
        "app.validate_invoice_void_event()",
        "app.validate_late_payment_decision()",
        "app.serialize_late_payment_source()",
        "app.validate_late_payment_charge()",
        "app.validate_late_charge_correction()",
        "app.serialize_late_charge_correction()",
        "app.billing_run_has_unresolved_sources(uuid,integer)",
        "app.billing_run_has_missing_eligible_sources(uuid,integer)",
        "app.snapshot_billing_run_eligible_sources()",
        "app.protect_billing_run_eligible_source_history()",
        "app.protect_billing_run_history()",
        "app.protect_billing_run_attempt_history()",
        "app.protect_billing_run_item_history()",
        "app.reject_invoice_storage_truncate()",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} "
            "FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.invoice_adjusted_line_obligation(uuid) "
        "TO prm_runtime, prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.invoice_adjusted_line_obligation_at(uuid,timestamp with time zone) "
        "TO prm_runtime, prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.assert_active_financial_actor(uuid,uuid) TO prm_financial"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.lease_is_billable_for_recurring_period(uuid,date,date,timestamp with time zone) "
        "TO prm_financial"
    )


def downgrade() -> None:
    """Refuse rollback that could erase permanent financial history."""
    raise RuntimeError("Invoice and billing-run persistence is forward-only")
