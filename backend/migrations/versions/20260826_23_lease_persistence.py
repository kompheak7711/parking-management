"""Add protected Lease, signer, and occupancy persistence."""

from alembic import op

revision = "20260826_23"
down_revision = "20260826_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-033 persistence and concurrency boundary."""
    op.execute(
        """
        CREATE TABLE app.leases (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            primary_tenant_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            status text NOT NULL DEFAULT 'DRAFTED'
                CHECK (status IN ('DRAFTED', 'SIGNED', 'CANCELLED', 'TERMINATED')),
            start_date date,
            end_date date,
            monthly_rent_usd_cents bigint CHECK (monthly_rent_usd_cents > 0),
            predecessor_lease_id uuid UNIQUE
                REFERENCES app.leases(id) ON DELETE RESTRICT,
            signed_at timestamptz,
            terminated_at timestamptz,
            actual_termination_date date,
            termination_reason text,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT leases_period_valid CHECK (
                start_date IS NULL OR end_date IS NULL OR end_date > start_date
            ),
            CONSTRAINT leases_predecessor_not_self CHECK (
                predecessor_lease_id IS NULL OR predecessor_lease_id <> id
            ),
            CONSTRAINT leases_termination_reason_normalized CHECK (
                termination_reason IS NULL OR (
                    length(btrim(termination_reason)) > 0
                    AND termination_reason = btrim(termination_reason)
                )
            ),
            CONSTRAINT leases_lifecycle_shape CHECK (
                (
                    status = 'DRAFTED'
                    AND signed_at IS NULL
                    AND terminated_at IS NULL
                    AND actual_termination_date IS NULL
                    AND termination_reason IS NULL
                ) OR (
                    status = 'SIGNED'
                    AND start_date IS NOT NULL
                    AND end_date IS NOT NULL
                    AND monthly_rent_usd_cents IS NOT NULL
                    AND signed_at IS NOT NULL
                    AND terminated_at IS NULL
                    AND actual_termination_date IS NULL
                    AND termination_reason IS NULL
                ) OR (
                    status = 'CANCELLED'
                    AND signed_at IS NULL
                    AND terminated_at IS NULL
                    AND actual_termination_date IS NULL
                    AND termination_reason IS NULL
                ) OR (
                    status = 'TERMINATED'
                    AND start_date IS NOT NULL
                    AND end_date IS NOT NULL
                    AND monthly_rent_usd_cents IS NOT NULL
                    AND signed_at IS NOT NULL
                    AND terminated_at IS NOT NULL
                    AND actual_termination_date IS NOT NULL
                    AND termination_reason IS NOT NULL
                )
            ),
            CONSTRAINT leases_signed_period_exclusive
                EXCLUDE USING gist (
                    unit_id WITH =,
                    daterange(
                        start_date,
                        CASE WHEN status = 'TERMINATED'
                            THEN actual_termination_date ELSE end_date END,
                        '[]'
                    ) WITH &&
                ) WHERE (status IN ('SIGNED', 'TERMINATED'))
                DEFERRABLE INITIALLY IMMEDIATE
        )
        """
    )
    op.execute("CREATE INDEX leases_unit_status_idx ON app.leases(unit_id, status)")
    op.execute(
        "CREATE INDEX leases_primary_tenant_history_idx "
        "ON app.leases(primary_tenant_id, start_date DESC, id DESC)"
    )
    op.execute(
        """
        CREATE TABLE app.lease_signers (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            signed_at timestamptz,
            added_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            added_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT lease_signers_lease_customer_unique UNIQUE (lease_id, customer_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX lease_signers_customer_history_idx "
        "ON app.lease_signers(customer_id, added_at DESC, id DESC)"
    )
    op.execute(
        """
        CREATE TABLE app.occupancies (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            move_in_date date NOT NULL,
            move_out_date date,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT occupancies_period_valid CHECK (
                move_out_date IS NULL OR move_out_date >= move_in_date
            ),
            CONSTRAINT occupancies_customer_lease_period_exclusive
                EXCLUDE USING gist (
                    lease_id WITH =,
                    customer_id WITH =,
                    daterange(move_in_date, move_out_date, '[]') WITH &&
                ) DEFERRABLE INITIALLY IMMEDIATE
        )
        """
    )
    op.execute(
        "CREATE INDEX occupancies_lease_open_idx ON app.occupancies(lease_id, move_out_date)"
    )
    op.execute(
        "CREATE INDEX occupancies_customer_history_idx "
        "ON app.occupancies(customer_id, move_in_date DESC, id DESC)"
    )
    op.execute(
        """
        CREATE TABLE app.termination_notices (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            notice_date date NOT NULL,
            intended_termination_date date,
            notice_text text NOT NULL CHECK (
                length(btrim(notice_text)) > 0 AND notice_text = btrim(notice_text)
            ),
            governing_lease_provision text NOT NULL CHECK (
                length(btrim(governing_lease_provision)) > 0
                AND governing_lease_provision = btrim(governing_lease_provision)
            ),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX termination_notices_lease_history_idx "
        "ON app.termination_notices(lease_id, notice_date, id)"
    )
    op.execute(
        """
        CREATE TABLE app.lease_violation_warnings (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            warning_sequence smallint NOT NULL CHECK (warning_sequence > 0),
            violation_date date NOT NULL,
            warning_date date NOT NULL,
            violation_description text NOT NULL CHECK (
                length(btrim(violation_description)) > 0
                AND violation_description = btrim(violation_description)
            ),
            lease_provision text NOT NULL CHECK (
                length(btrim(lease_provision)) > 0 AND lease_provision = btrim(lease_provision)
            ),
            communication_record text NOT NULL CHECK (
                length(btrim(communication_record)) > 0
                AND communication_record = btrim(communication_record)
            ),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT lease_violation_warning_sequence_unique
                UNIQUE (lease_id, warning_sequence)
        )
        """
    )
    op.execute(
        "CREATE INDEX lease_violation_warnings_history_idx "
        "ON app.lease_violation_warnings(lease_id, warning_date, id)"
    )
    op.execute(
        """
        CREATE TABLE app.lease_pet_approvals (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            approved_date date NOT NULL,
            deposit_required_by_signed_terms boolean NOT NULL,
            pet_description text CHECK (
                pet_description IS NULL OR (
                    length(btrim(pet_description)) > 0 AND pet_description = btrim(pet_description)
                )
            ),
            approved_at timestamptz NOT NULL,
            approved_by uuid NOT NULL REFERENCES app.user_accounts(actor_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX lease_pet_approvals_history_idx "
        "ON app.lease_pet_approvals(lease_id, approved_date, id)"
    )
    op.execute(
        """
        CREATE TABLE app.lease_service_terms (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            property_service_id uuid NOT NULL
                REFERENCES app.property_services(id) ON DELETE RESTRICT,
            applicable_from date NOT NULL,
            applicable_through date,
            service_approval_period_id uuid NOT NULL
                REFERENCES app.property_service_approval_periods(id) ON DELETE RESTRICT,
            terms_reference text NOT NULL CHECK (
                length(btrim(terms_reference)) > 0 AND terms_reference = btrim(terms_reference)
            ),
            recorded_at timestamptz NOT NULL,
            recorded_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT lease_service_terms_period_valid CHECK (
                applicable_through IS NULL OR applicable_through >= applicable_from
            ),
            CONSTRAINT lease_service_terms_effective_unique
                UNIQUE (lease_id, property_service_id, applicable_from)
        )
        """
    )
    op.execute(
        "CREATE INDEX lease_service_terms_history_idx "
        "ON app.lease_service_terms(lease_id, applicable_from, id)"
    )
    op.execute(
        """
        CREATE TABLE app.lease_pet_departures (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            pet_approval_id uuid NOT NULL UNIQUE
                REFERENCES app.lease_pet_approvals(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            permanently_left_date date NOT NULL,
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.pet_deposit_refund_reviews (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            pet_departure_id uuid NOT NULL UNIQUE
                REFERENCES app.lease_pet_departures(id) ON DELETE RESTRICT,
            pet_deposit_id uuid NOT NULL UNIQUE
                REFERENCES app.deposits(id) ON DELETE RESTRICT,
            obligations_reviewed_usd_cents bigint NOT NULL
                CHECK (obligations_reviewed_usd_cents >= 0),
            review_findings text NOT NULL CHECK (
                length(btrim(review_findings)) > 0 AND review_findings = btrim(review_findings)
            ),
            all_pet_obligations_resolved boolean NOT NULL
                CHECK (all_pet_obligations_resolved = true),
            resolution_reference text NOT NULL CHECK (
                length(btrim(resolution_reference)) > 0
                AND resolution_reference = btrim(resolution_reference)
            ),
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            reviewed_at timestamptz NOT NULL,
            reviewed_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.lease_revisions (
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            version integer NOT NULL CHECK (version > 0),
            status text NOT NULL,
            unit_id uuid NOT NULL,
            primary_tenant_id uuid NOT NULL,
            start_date date,
            end_date date,
            monthly_rent_usd_cents bigint,
            predecessor_lease_id uuid,
            signed_at timestamptz,
            terminated_at timestamptz,
            actual_termination_date date,
            termination_reason text,
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            recorded_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            PRIMARY KEY (lease_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.lease_signer_history (
            signer_id uuid NOT NULL,
            history_sequence bigint GENERATED ALWAYS AS IDENTITY,
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            signed_at timestamptz,
            operation text NOT NULL CHECK (operation IN ('ADDED', 'SIGNED', 'REMOVED')),
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            PRIMARY KEY (signer_id, history_sequence)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.occupancy_revisions (
            occupancy_id uuid NOT NULL REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            version integer NOT NULL CHECK (version > 0),
            lease_id uuid NOT NULL,
            customer_id uuid NOT NULL,
            move_in_date date NOT NULL,
            move_out_date date,
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            recorded_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            PRIMARY KEY (occupancy_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_lease_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Lease history is permanent' USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'DRAFTED' AND NEW.status = 'SIGNED' THEN
                PERFORM 1 FROM app.units WHERE id = NEW.unit_id FOR UPDATE;
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR OLD.status IN ('CANCELLED', 'TERMINATED')
                OR (OLD.status = 'DRAFTED' AND NEW.status NOT IN ('DRAFTED', 'SIGNED', 'CANCELLED'))
                OR (OLD.status = 'SIGNED' AND NEW.status NOT IN ('SIGNED', 'TERMINATED'))
                OR (OLD.status <> 'DRAFTED' AND (
                    NEW.primary_tenant_id IS DISTINCT FROM OLD.primary_tenant_id
                    OR NEW.start_date IS DISTINCT FROM OLD.start_date
                    OR NEW.end_date IS DISTINCT FROM OLD.end_date
                    OR NEW.monthly_rent_usd_cents IS DISTINCT FROM OLD.monthly_rent_usd_cents
                    OR NEW.predecessor_lease_id IS DISTINCT FROM OLD.predecessor_lease_id
                    OR NEW.signed_at IS DISTINCT FROM OLD.signed_at
                ))
            THEN
                RAISE EXCEPTION 'Lease identity, legal transitions, and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_lease_relationships()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_lease app.leases%ROWTYPE;
            v_predecessor app.leases%ROWTYPE;
        BEGIN
            SELECT * INTO v_lease FROM app.leases WHERE id = NEW.id;
            IF v_lease.predecessor_lease_id IS NOT NULL THEN
                SELECT * INTO STRICT v_predecessor
                FROM app.leases
                WHERE id = v_lease.predecessor_lease_id
                FOR SHARE;
                IF v_predecessor.status NOT IN ('SIGNED', 'TERMINATED')
                    OR v_predecessor.unit_id <> v_lease.unit_id
                    OR v_predecessor.start_date IS NULL
                    OR v_predecessor.end_date IS NULL
                    OR v_lease.start_date IS NULL
                    OR v_lease.start_date <= v_predecessor.end_date
                THEN
                    RAISE EXCEPTION
                        'Lease predecessor must be a stable prior signed or terminated Lease for the same Unit'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF v_lease.status IN ('SIGNED', 'TERMINATED') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM app.lease_signers
                    WHERE lease_id = v_lease.id
                      AND customer_id = v_lease.primary_tenant_id
                      AND signed_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'The Primary Tenant must be a signed Lease Signer'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_lease_signer()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_status text;
            v_actor_id uuid;
        BEGIN
            SELECT status INTO STRICT v_status
            FROM app.leases WHERE id = COALESCE(NEW.lease_id, OLD.lease_id) FOR UPDATE;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Lease Signers are immutable after signing'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                BEGIN
                    v_actor_id := nullif(
                        current_setting('app.lease_signer_actor_id', true), ''
                    )::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    v_actor_id := NULL;
                END;
                IF v_actor_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM app.user_accounts WHERE actor_id = v_actor_id
                ) THEN
                    RAISE EXCEPTION 'Lease Signer mutations require an attributed bounded command'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            IF TG_OP = 'UPDATE' AND (
                NEW.id IS DISTINCT FROM OLD.id
                OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.added_at IS DISTINCT FROM OLD.added_at
                OR NEW.added_by IS DISTINCT FROM OLD.added_by
                OR OLD.signed_at IS NOT NULL
                OR NEW.signed_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Lease Signer identity and signature history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_occupancy_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Occupancy history is permanent' USING ERRCODE = '55000';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR (
                    NEW.move_in_date IS NOT DISTINCT FROM OLD.move_in_date
                    AND NEW.move_out_date IS NOT DISTINCT FROM OLD.move_out_date
                )
            THEN
                RAISE EXCEPTION 'Occupancy identity, dates, and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_lease_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Lease event and revision history is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_lease_service_term()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_start date;
            v_end date;
            v_status text;
            v_unit_property uuid;
            v_service_property uuid;
            v_approval_from date;
            v_approval_through date;
            v_approval_service uuid;
        BEGIN
            SELECT lease.start_date, lease.end_date, lease.status, unit.property_id
            INTO STRICT v_start, v_end, v_status, v_unit_property
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = NEW.lease_id;
            SELECT service.property_id INTO STRICT v_service_property
            FROM app.property_services AS service WHERE service.id = NEW.property_service_id;
            SELECT approval.property_service_id, approval.effective_from,
                   approval.effective_through
            INTO STRICT v_approval_service, v_approval_from, v_approval_through
            FROM app.property_service_approval_periods AS approval
            WHERE approval.id = NEW.service_approval_period_id
            FOR SHARE;
            IF v_status NOT IN ('SIGNED', 'TERMINATED')
                OR v_start IS NULL OR v_end IS NULL
                OR v_unit_property <> v_service_property
                OR v_approval_service <> NEW.property_service_id
                OR NEW.applicable_from < v_start
                OR COALESCE(NEW.applicable_through, v_end) > v_end
                OR NEW.applicable_from < v_approval_from
                OR (
                    v_approval_through IS NOT NULL
                    AND COALESCE(NEW.applicable_through, v_end) > v_approval_through
                )
            THEN
                RAISE EXCEPTION 'Lease Service terms must stay within the Lease and approval period'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_lease_pet_departure()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app.lease_pet_approvals
                WHERE id = NEW.pet_approval_id AND lease_id = NEW.lease_id
            ) THEN
                RAISE EXCEPTION 'Pet departure must match its Lease approval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.guard_service_approval_period_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
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
            IF EXISTS (
                SELECT 1
                FROM app.lease_service_terms AS term
                JOIN app.leases AS lease ON lease.id = term.lease_id
                WHERE term.service_approval_period_id = OLD.id
                  AND COALESCE(term.applicable_through, lease.end_date) > NEW.effective_through
            ) THEN
                RAISE EXCEPTION 'Service approval closure cannot invalidate signed Lease terms'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_pet_deposit_refund_review()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.lease_pet_departures AS departure
                JOIN app.lease_pet_approvals AS approval
                  ON approval.id = departure.pet_approval_id
                 AND approval.lease_id = departure.lease_id
                JOIN app.leases AS lease ON lease.id = departure.lease_id
                JOIN app.deposits AS deposit ON deposit.id = NEW.pet_deposit_id
                WHERE departure.id = NEW.pet_departure_id
                  AND lease.status = 'SIGNED'
                  AND deposit.deposit_type = 'PET'
                  AND deposit.lease_id = lease.id
                  AND deposit.pet_approval_id = approval.id
                  AND deposit.customer_id = lease.primary_tenant_id
            ) THEN
                RAISE EXCEPTION 'Pet Deposit review sources must match an active signed Lease'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_lease_revision()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO app.lease_revisions(
                lease_id, version, status, unit_id, primary_tenant_id, start_date,
                end_date, monthly_rent_usd_cents, predecessor_lease_id, signed_at,
                terminated_at, actual_termination_date, termination_reason, recorded_by
            ) VALUES (
                NEW.id, NEW.version, NEW.status, NEW.unit_id, NEW.primary_tenant_id,
                NEW.start_date, NEW.end_date, NEW.monthly_rent_usd_cents,
                NEW.predecessor_lease_id, NEW.signed_at, NEW.terminated_at,
                NEW.actual_termination_date, NEW.termination_reason, NEW.updated_by
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_lease_signer_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO app.lease_signer_history(
                signer_id, lease_id, customer_id, signed_at, operation, actor_id
            ) VALUES (
                COALESCE(NEW.id, OLD.id), COALESCE(NEW.lease_id, OLD.lease_id),
                COALESCE(NEW.customer_id, OLD.customer_id), COALESCE(NEW.signed_at, OLD.signed_at),
                CASE WHEN TG_OP = 'INSERT' THEN 'ADDED'
                     WHEN TG_OP = 'DELETE' THEN 'REMOVED' ELSE 'SIGNED' END,
                CASE WHEN TG_OP = 'INSERT' THEN NEW.added_by
                     ELSE current_setting('app.lease_signer_actor_id')::uuid END
            );
            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.sign_draft_lease_signer(
            p_signer_id uuid, p_signed_at timestamptz, p_actor_id uuid
        ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior text;
        BEGIN
            IF p_signed_at IS NULL OR p_actor_id IS NULL THEN
                RAISE EXCEPTION 'Signer signature attribution is required' USING ERRCODE = '22023';
            END IF;
            v_prior := current_setting('app.lease_signer_actor_id', true);
            PERFORM set_config('app.lease_signer_actor_id', p_actor_id::text, true);
            BEGIN
                UPDATE app.lease_signers SET signed_at = p_signed_at
                WHERE id = p_signer_id AND signed_at IS NULL;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Unsigned draft Lease Signer was not found'
                        USING ERRCODE = '55000';
                END IF;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('app.lease_signer_actor_id', COALESCE(v_prior, ''), true);
                RAISE;
            END;
            PERFORM set_config('app.lease_signer_actor_id', COALESCE(v_prior, ''), true);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.remove_draft_lease_signer(p_signer_id uuid, p_actor_id uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior text;
        BEGIN
            IF p_actor_id IS NULL THEN
                RAISE EXCEPTION 'Signer removal attribution is required' USING ERRCODE = '22023';
            END IF;
            v_prior := current_setting('app.lease_signer_actor_id', true);
            PERFORM set_config('app.lease_signer_actor_id', p_actor_id::text, true);
            BEGIN
                DELETE FROM app.lease_signers WHERE id = p_signer_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Draft Lease Signer was not found' USING ERRCODE = '55000';
                END IF;
            EXCEPTION WHEN OTHERS THEN
                PERFORM set_config('app.lease_signer_actor_id', COALESCE(v_prior, ''), true);
                RAISE;
            END;
            PERFORM set_config('app.lease_signer_actor_id', COALESCE(v_prior, ''), true);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_occupancy_revision()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO app.occupancy_revisions(
                occupancy_id, version, lease_id, customer_id, move_in_date,
                move_out_date, recorded_by
            ) VALUES (
                NEW.id, NEW.version, NEW.lease_id, NEW.customer_id, NEW.move_in_date,
                NEW.move_out_date, NEW.updated_by
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_lease_storage_truncate()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'Lease and occupancy history is permanent'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER leases_protect_history BEFORE UPDATE OR DELETE ON app.leases "
        "FOR EACH ROW EXECUTE FUNCTION app.protect_lease_history()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER leases_validate_relationships "
        "AFTER INSERT OR UPDATE ON app.leases DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION app.validate_lease_relationships()"
    )
    op.execute(
        "CREATE TRIGGER leases_record_revision AFTER INSERT OR UPDATE ON app.leases "
        "FOR EACH ROW EXECUTE FUNCTION app.record_lease_revision()"
    )
    op.execute(
        "CREATE TRIGGER lease_signers_guard BEFORE INSERT OR UPDATE OR DELETE ON app.lease_signers "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_lease_signer()"
    )
    op.execute(
        "CREATE TRIGGER lease_signers_record_history "
        "AFTER INSERT OR UPDATE OR DELETE ON app.lease_signers "
        "FOR EACH ROW EXECUTE FUNCTION app.record_lease_signer_history()"
    )
    op.execute(
        "CREATE TRIGGER occupancies_protect_history BEFORE UPDATE OR DELETE ON app.occupancies "
        "FOR EACH ROW EXECUTE FUNCTION app.protect_occupancy_history()"
    )
    op.execute(
        "CREATE TRIGGER occupancies_record_revision AFTER INSERT OR UPDATE ON app.occupancies "
        "FOR EACH ROW EXECUTE FUNCTION app.record_occupancy_revision()"
    )
    for table in (
        "termination_notices",
        "lease_violation_warnings",
        "lease_pet_approvals",
        "lease_service_terms",
        "lease_pet_departures",
        "pet_deposit_refund_reviews",
        "lease_revisions",
        "lease_signer_history",
        "occupancy_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
    op.execute(
        "CREATE CONSTRAINT TRIGGER lease_service_terms_validate "
        "AFTER INSERT ON app.lease_service_terms DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION app.validate_lease_service_term()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER lease_pet_departures_validate "
        "AFTER INSERT ON app.lease_pet_departures DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION app.validate_lease_pet_departure()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER pet_deposit_refund_reviews_validate "
        "AFTER INSERT ON app.pet_deposit_refund_reviews DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION app.validate_pet_deposit_refund_review()"
    )
    for table in (
        "leases",
        "lease_signers",
        "occupancies",
        "termination_notices",
        "lease_violation_warnings",
        "lease_pet_approvals",
        "lease_service_terms",
        "lease_pet_departures",
        "pet_deposit_refund_reviews",
        "lease_revisions",
        "lease_signer_history",
        "occupancy_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
    op.execute(
        """
        ALTER TABLE app.reservations
        ADD CONSTRAINT reservations_resulting_lease_fkey
        FOREIGN KEY (resulting_lease_id) REFERENCES app.leases(id) ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        REVOKE ALL ON TABLE
            app.leases, app.lease_signers, app.occupancies,
            app.termination_notices, app.lease_violation_warnings,
            app.lease_pet_approvals, app.lease_service_terms,
            app.lease_pet_departures, app.pet_deposit_refund_reviews,
            app.lease_revisions, app.lease_signer_history, app.occupancy_revisions
        FROM PUBLIC, prm_runtime, prm_bootstrap
        """
    )
    op.execute(
        """
        GRANT SELECT ON TABLE
            app.leases, app.lease_signers, app.occupancies,
            app.termination_notices, app.lease_violation_warnings,
            app.lease_pet_approvals, app.lease_service_terms,
            app.lease_pet_departures, app.pet_deposit_refund_reviews,
            app.lease_revisions, app.lease_signer_history, app.occupancy_revisions
        TO prm_runtime
        """
    )
    for function in (
        "app.protect_lease_history()",
        "app.validate_lease_relationships()",
        "app.guard_lease_signer()",
        "app.protect_occupancy_history()",
        "app.reject_lease_append_only_mutation()",
        "app.validate_lease_service_term()",
        "app.validate_lease_pet_departure()",
        "app.validate_pet_deposit_refund_review()",
        "app.record_lease_revision()",
        "app.record_lease_signer_history()",
        "app.sign_draft_lease_signer(uuid, timestamptz, uuid)",
        "app.remove_draft_lease_signer(uuid, uuid)",
        "app.record_occupancy_revision()",
        "app.reject_lease_storage_truncate()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.sign_draft_lease_signer(uuid, timestamptz, uuid) "
        "TO prm_runtime"
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.remove_draft_lease_signer(uuid, uuid) TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback of Lease and occupancy history."""
    raise RuntimeError("Lease, signer, and occupancy migration is forward-only")
