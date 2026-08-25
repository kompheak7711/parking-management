"""Add protected Reservation and reservation-deposit persistence."""

from alembic import op

revision = "20260825_19"
down_revision = "20260825_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-029 persistence and concurrency boundary."""
    op.execute(
        """
        CREATE TABLE app.reservations (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            reservation_date date NOT NULL,
            agreed_monthly_rent_usd_cents bigint NOT NULL
                CHECK (agreed_monthly_rent_usd_cents > 0),
            original_expiration_date date NOT NULL,
            effective_expiration_date date NOT NULL,
            status text NOT NULL CHECK (status IN ('ACTIVE', 'CANCELLED', 'COMPLETED')),
            resulting_lease_id uuid UNIQUE,
            cancellation_reason_code text,
            cancellation_responsibility text
                CHECK (cancellation_responsibility IN ('CUSTOMER', 'PROPERTY')),
            cancelled_at timestamptz,
            completed_at timestamptz,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT reservations_initial_period_valid CHECK (
                original_expiration_date >= reservation_date
                AND original_expiration_date <= reservation_date + 21
            ),
            CONSTRAINT reservations_effective_expiration_valid CHECK (
                effective_expiration_date >= original_expiration_date
            ),
            CONSTRAINT reservations_cancellation_reason_normalized CHECK (
                cancellation_reason_code IS NULL OR (
                    length(btrim(cancellation_reason_code)) > 0
                    AND cancellation_reason_code = btrim(cancellation_reason_code)
                )
            ),
            CONSTRAINT reservations_lifecycle_shape CHECK (
                (
                    status = 'ACTIVE'
                    AND cancellation_reason_code IS NULL
                    AND cancellation_responsibility IS NULL
                    AND cancelled_at IS NULL
                    AND completed_at IS NULL
                ) OR (
                    status = 'CANCELLED'
                    AND cancellation_reason_code IS NOT NULL
                    AND cancellation_responsibility IS NOT NULL
                    AND cancelled_at IS NOT NULL
                    AND resulting_lease_id IS NULL
                    AND completed_at IS NULL
                ) OR (
                    status = 'COMPLETED'
                    AND cancellation_reason_code IS NULL
                    AND cancellation_responsibility IS NULL
                    AND cancelled_at IS NULL
                    AND resulting_lease_id IS NOT NULL
                    AND completed_at IS NOT NULL
                )
            ),
            CONSTRAINT reservations_resulting_lease_non_nil CHECK (
                resulting_lease_id IS NULL
                OR resulting_lease_id <> '00000000-0000-0000-0000-000000000000'::uuid
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX reservations_one_active_per_unit "
        "ON app.reservations(unit_id) WHERE status = 'ACTIVE'"
    )
    op.execute(
        "CREATE INDEX reservations_customer_history_idx "
        "ON app.reservations(customer_id, reservation_date DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX reservations_expiration_idx "
        "ON app.reservations(status, effective_expiration_date, id)"
    )
    op.execute(
        "COMMENT ON COLUMN app.reservations.resulting_lease_id IS "
        "'Stable resulting Lease UUID; its FK and completion checks are added by the bounded Lease and move-in tranches'"
    )
    op.execute(
        """
        CREATE TABLE app.reservation_extension_notices (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            reservation_id uuid NOT NULL UNIQUE
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            original_expiration_date date NOT NULL,
            previous_expiration_date date NOT NULL,
            new_expiration_date date NOT NULL,
            approved_at timestamptz NOT NULL,
            approved_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            reason_memo text,
            authorization_reference text NOT NULL,
            CONSTRAINT reservation_extension_forward_and_bounded CHECK (
                new_expiration_date > previous_expiration_date
                AND new_expiration_date <= previous_expiration_date + 14
            ),
            CONSTRAINT reservation_extension_reason_normalized CHECK (
                reason_memo IS NULL OR (
                    length(btrim(reason_memo)) > 0
                    AND reason_memo = btrim(reason_memo)
                )
            ),
            CONSTRAINT reservation_extension_authorization_nonblank CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX reservation_extension_history_idx "
        "ON app.reservation_extension_notices(reservation_id, approved_at, id)"
    )
    op.execute(
        """
        CREATE TABLE app.reservation_deposit_acceptances (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            reservation_id uuid NOT NULL UNIQUE
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            suggested_rate_basis_points smallint NOT NULL
                CHECK (suggested_rate_basis_points = 2000),
            suggested_amount_usd_cents bigint NOT NULL
                CHECK (suggested_amount_usd_cents > 0),
            accepted_required_amount_usd_cents bigint NOT NULL
                CHECK (accepted_required_amount_usd_cents > 0),
            acceptance_kind text NOT NULL
                CHECK (acceptance_kind IN ('NORMAL_SUGGESTION', 'AUTHORIZED_VARIANCE')),
            accepted_at timestamptz NOT NULL,
            accepted_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            reason text NOT NULL,
            authorization_reference text NOT NULL,
            calculation_trace jsonb NOT NULL,
            CONSTRAINT reservation_deposit_acceptance_reason_nonblank CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            CONSTRAINT reservation_deposit_acceptance_authorization_nonblank CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            ),
            CONSTRAINT reservation_deposit_acceptance_trace_object CHECK (
                jsonb_typeof(calculation_trace) = 'object'
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.deposits (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_type text NOT NULL CHECK (deposit_type = 'SECURITY'),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            reservation_id uuid NOT NULL UNIQUE
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            lease_id uuid,
            pet_approval_id uuid,
            required_usd_cents bigint NOT NULL CHECK (required_usd_cents > 0),
            required_effective_date date NOT NULL,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT deposits_reservation_security_shape CHECK (
                deposit_type = 'SECURITY'
                AND reservation_id IS NOT NULL
                AND lease_id IS NULL
                AND pet_approval_id IS NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX deposits_customer_history_idx "
        "ON app.deposits(customer_id, required_effective_date, id)"
    )
    op.execute(
        """
        CREATE TABLE app.deposit_receipts (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            deposit_id uuid NOT NULL REFERENCES app.deposits(id) ON DELETE RESTRICT,
            payment_id uuid NOT NULL
                CHECK (payment_id <> '00000000-0000-0000-0000-000000000000'::uuid),
            amount_usd_cents bigint NOT NULL CHECK (amount_usd_cents > 0),
            occurred_at timestamptz NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT deposit_receipts_deposit_payment_unique UNIQUE (deposit_id, payment_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX deposit_receipts_history_idx "
        "ON app.deposit_receipts(deposit_id, occurred_at, id)"
    )
    op.execute(
        "COMMENT ON COLUMN app.deposit_receipts.payment_id IS "
        "'Stable source Payment UUID; the FK is added and validated by the bounded Payment persistence tranche'"
    )
    op.execute(
        """
        CREATE TABLE app.reservation_commands (
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (
                action IN ('reservation.create', 'reservation.extend')
            ),
            idempotency_key uuid NOT NULL,
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            result_id uuid NOT NULL,
            result_snapshot jsonb NOT NULL
                CHECK (jsonb_typeof(result_snapshot) = 'object'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (actor_id, property_id, action, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_reservation_append_only_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Reservation history is append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in (
        "reservation_extension_notices",
        "reservation_deposit_acceptances",
        "deposit_receipts",
        "reservation_commands",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_update_or_delete
            BEFORE UPDATE OR DELETE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.reject_reservation_append_only_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON app.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_reservation_append_only_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION app.validate_reservation_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.status <> 'ACTIVE'
                OR NEW.resulting_lease_id IS NOT NULL
                OR NEW.cancellation_reason_code IS NOT NULL
                OR NEW.cancellation_responsibility IS NOT NULL
                OR NEW.cancelled_at IS NOT NULL
                OR NEW.completed_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'A new Reservation must begin as ACTIVE'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservations_validate_insert
        BEFORE INSERT ON app.reservations
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_reservation_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'DELETE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
                OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
                OR NEW.reservation_date IS DISTINCT FROM OLD.reservation_date
                OR NEW.agreed_monthly_rent_usd_cents IS DISTINCT FROM OLD.agreed_monthly_rent_usd_cents
                OR NEW.original_expiration_date IS DISTINCT FROM OLD.original_expiration_date
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Reservation identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> NEW.status THEN
                RAISE EXCEPTION 'Reservation transition requires a later coordinated lifecycle boundary'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.effective_expiration_date IS DISTINCT FROM OLD.effective_expiration_date
                AND NOT EXISTS (
                    SELECT 1
                    FROM app.reservation_extension_notices AS notice
                    WHERE notice.reservation_id = OLD.id
                      AND notice.original_expiration_date = OLD.original_expiration_date
                      AND notice.previous_expiration_date = OLD.effective_expiration_date
                      AND notice.new_expiration_date = NEW.effective_expiration_date
                )
            THEN
                RAISE EXCEPTION 'Reservation expiration requires an immutable Extension Notice'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservations_protect_history
        BEFORE UPDATE OR DELETE ON app.reservations
        FOR EACH ROW EXECUTE FUNCTION app.protect_reservation_history()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservations_reject_truncate
        BEFORE TRUNCATE ON app.reservations
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_reservation_append_only_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_deposit_history_loss()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Deposit identity and obligation history are protected'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER deposits_reject_update_or_delete
        BEFORE UPDATE OR DELETE ON app.deposits
        FOR EACH ROW EXECUTE FUNCTION app.reject_deposit_history_loss()
        """
    )
    op.execute(
        """
        CREATE TRIGGER deposits_reject_truncate
        BEFORE TRUNCATE ON app.deposits
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_deposit_history_loss()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_reservation_extension_notice()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_reservation app.reservations%ROWTYPE;
            v_timezone text;
            v_business_date date;
        BEGIN
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            WHERE reservation.id = NEW.reservation_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found' USING ERRCODE = '23503';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.units AS unit
            JOIN app.properties AS property ON property.id = unit.property_id
            WHERE unit.id = v_reservation.unit_id;
            v_business_date := timezone(v_timezone, clock_timestamp())::date;
            IF NEW.approved_at > clock_timestamp() + interval '5 seconds'
                OR NEW.approved_at < v_reservation.created_at
                OR v_reservation.status <> 'ACTIVE'
                OR v_business_date > v_reservation.effective_expiration_date
                OR v_reservation.effective_expiration_date - v_business_date >= 14
                OR NEW.original_expiration_date <> v_reservation.original_expiration_date
                OR NEW.previous_expiration_date <> v_reservation.effective_expiration_date
            THEN
                RAISE EXCEPTION 'Reservation is not eligible for this extension'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_extension_notices_validate
        BEFORE INSERT ON app.reservation_extension_notices
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_extension_notice()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_extension_applied()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.reservations AS reservation
                WHERE reservation.id = NEW.reservation_id
                  AND reservation.status = 'ACTIVE'
                  AND reservation.original_expiration_date = NEW.original_expiration_date
                  AND reservation.effective_expiration_date = NEW.new_expiration_date
            ) THEN
                RAISE EXCEPTION 'Extension Notice requires the matching Reservation update'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservation_extension_notice_applied
        AFTER INSERT ON app.reservation_extension_notices
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_extension_applied()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_reservation_deposit_acceptance()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_rent bigint;
            v_suggestion bigint;
        BEGIN
            SELECT reservation.agreed_monthly_rent_usd_cents INTO v_rent
            FROM app.reservations AS reservation
            WHERE reservation.id = NEW.reservation_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found' USING ERRCODE = '23503';
            END IF;
            v_suggestion := (v_rent + 2) / 5;
            IF NEW.accepted_at > clock_timestamp() + interval '5 seconds'
                OR NEW.suggested_amount_usd_cents <> v_suggestion
                OR NOT (NEW.calculation_trace @> jsonb_build_object(
                    'agreed_monthly_rent_usd_cents', v_rent,
                    'suggested_rate_basis_points', 2000,
                    'suggested_amount_usd_cents', v_suggestion
                ))
                OR (
                    NEW.accepted_required_amount_usd_cents = v_suggestion
                    AND NEW.acceptance_kind <> 'NORMAL_SUGGESTION'
                )
                OR (
                    NEW.accepted_required_amount_usd_cents <> v_suggestion
                    AND NEW.acceptance_kind <> 'AUTHORIZED_VARIANCE'
                )
            THEN
                RAISE EXCEPTION 'Reservation Deposit acceptance calculation is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_deposit_acceptances_validate
        BEFORE INSERT ON app.reservation_deposit_acceptances
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_deposit_acceptance()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_reservation_security_deposit()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_reservation app.reservations%ROWTYPE;
            v_accepted bigint;
        BEGIN
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            WHERE reservation.id = NEW.reservation_id;
            SELECT acceptance.accepted_required_amount_usd_cents INTO v_accepted
            FROM app.reservation_deposit_acceptances AS acceptance
            WHERE acceptance.reservation_id = NEW.reservation_id;
            IF v_reservation.id IS NULL OR v_accepted IS NULL
                OR NEW.customer_id <> v_reservation.customer_id
                OR NEW.required_effective_date <> v_reservation.reservation_date
                OR NEW.required_usd_cents < v_accepted
            THEN
                RAISE EXCEPTION 'Reservation Security Deposit continuity is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER deposits_validate_reservation_security
        BEFORE INSERT ON app.deposits
        FOR EACH ROW EXECUTE FUNCTION app.validate_reservation_security_deposit()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_deposit_receipt()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_deposit app.deposits%ROWTYPE;
            v_received bigint;
            v_accepted bigint;
            v_accepted_at timestamptz;
        BEGIN
            SELECT deposit.* INTO v_deposit
            FROM app.deposits AS deposit
            WHERE deposit.id = NEW.deposit_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Deposit was not found' USING ERRCODE = '23503';
            END IF;
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0) INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = NEW.deposit_id;
            SELECT acceptance.accepted_required_amount_usd_cents, acceptance.accepted_at
            INTO v_accepted, v_accepted_at
            FROM app.reservation_deposit_acceptances AS acceptance
            WHERE acceptance.reservation_id = v_deposit.reservation_id;
            IF NEW.occurred_at > clock_timestamp() + interval '5 seconds'
                OR NEW.occurred_at < v_accepted_at
                OR (v_received = 0 AND NEW.amount_usd_cents <> v_accepted)
                OR v_received + NEW.amount_usd_cents > v_deposit.required_usd_cents
            THEN
                RAISE EXCEPTION 'Deposit receipt does not preserve the accepted or required amount'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER deposit_receipts_validate
        BEFORE INSERT ON app.deposit_receipts
        FOR EACH ROW EXECUTE FUNCTION app.validate_deposit_receipt()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_activation_bundle()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_acceptance_count integer;
            v_deposit_count integer;
            v_received bigint;
            v_accepted bigint;
            v_unit_status text;
        BEGIN
            SELECT count(*), max(accepted_required_amount_usd_cents)
            INTO v_acceptance_count, v_accepted
            FROM app.reservation_deposit_acceptances
            WHERE reservation_id = NEW.id;
            SELECT count(DISTINCT deposit.id), COALESCE(sum(receipt.amount_usd_cents), 0)
            INTO v_deposit_count, v_received
            FROM app.deposits AS deposit
            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
            WHERE deposit.reservation_id = NEW.id;
            SELECT unit.status INTO v_unit_status
            FROM app.units AS unit
            WHERE unit.id = NEW.unit_id;
            IF NEW.status <> 'ACTIVE'
                OR v_acceptance_count <> 1
                OR v_deposit_count <> 1
                OR v_received <> v_accepted
                OR v_unit_status <> 'RESERVED'
            THEN
                RAISE EXCEPTION 'ACTIVE Reservation requires one accepted and received Security Deposit bundle'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservations_activation_bundle_complete
        AFTER INSERT ON app.reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_activation_bundle()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.create_reservation(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_reservation_id uuid,
            p_unit_id uuid,
            p_customer_id uuid,
            p_reservation_date date,
            p_agreed_monthly_rent_usd_cents bigint,
            p_original_expiration_date date,
            p_acceptance_id uuid,
            p_accepted_required_amount_usd_cents bigint,
            p_acceptance_kind text,
            p_accepted_at timestamptz,
            p_acceptance_reason text,
            p_authorization_reference text,
            p_calculation_trace jsonb,
            p_deposit_id uuid,
            p_required_deposit_usd_cents bigint,
            p_receipt_id uuid,
            p_payment_id uuid,
            p_received_at timestamptz,
            p_actor_id uuid
        )
        RETURNS TABLE(
            reservation_id uuid,
            unit_id uuid,
            customer_id uuid,
            status text,
            effective_expiration_date date,
            deposit_id uuid,
            received_usd_cents bigint,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_timezone text;
            v_suggestion bigint;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.create/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.create'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    (v_command.result_snapshot ->> 'customer_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'received_usd_cents')::bigint,
                    (v_command.result_snapshot ->> 'version')::integer;
                RETURN;
            END IF;
            SELECT unit.* INTO v_unit
            FROM app.units AS unit
            WHERE unit.id = p_unit_id AND unit.property_id = p_property_id
            FOR UPDATE OF unit;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit was not found in the Property' USING ERRCODE = 'P0002';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property
            WHERE property.id = p_property_id;
            IF p_reservation_date <> timezone(v_timezone, clock_timestamp())::date
                OR p_accepted_at > clock_timestamp() + interval '5 seconds'
                OR p_received_at > clock_timestamp() + interval '5 seconds'
                OR p_received_at < p_accepted_at
            THEN
                RAISE EXCEPTION 'Reservation activation dates are invalid'
                    USING ERRCODE = '23514';
            END IF;
            IF v_unit.status <> 'VACANT' THEN
                RAISE EXCEPTION 'Unit is not available for Reservation' USING ERRCODE = 'P0001';
            END IF;
            PERFORM 1 FROM app.customers AS customer WHERE customer.id = p_customer_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Customer was not found' USING ERRCODE = 'P0002';
            END IF;
            v_suggestion := (p_agreed_monthly_rent_usd_cents + 2) / 5;
            INSERT INTO app.reservations (
                id, unit_id, customer_id, reservation_date,
                agreed_monthly_rent_usd_cents, original_expiration_date,
                effective_expiration_date, status, created_by, updated_by
            ) VALUES (
                p_reservation_id, p_unit_id, p_customer_id, p_reservation_date,
                p_agreed_monthly_rent_usd_cents, p_original_expiration_date,
                p_original_expiration_date, 'ACTIVE', p_actor_id, p_actor_id
            );
            INSERT INTO app.reservation_deposit_acceptances (
                id, reservation_id, suggested_rate_basis_points,
                suggested_amount_usd_cents, accepted_required_amount_usd_cents,
                acceptance_kind, accepted_at, accepted_by, reason,
                authorization_reference, calculation_trace
            ) VALUES (
                p_acceptance_id, p_reservation_id, 2000, v_suggestion,
                p_accepted_required_amount_usd_cents, p_acceptance_kind,
                p_accepted_at, p_actor_id, btrim(p_acceptance_reason),
                btrim(p_authorization_reference), p_calculation_trace
            );
            INSERT INTO app.deposits (
                id, deposit_type, customer_id, reservation_id,
                required_usd_cents, required_effective_date,
                created_by, updated_by
            ) VALUES (
                p_deposit_id, 'SECURITY', p_customer_id, p_reservation_id,
                p_required_deposit_usd_cents, p_reservation_date,
                p_actor_id, p_actor_id
            );
            INSERT INTO app.deposit_receipts (
                id, deposit_id, payment_id, amount_usd_cents, occurred_at, actor_id
            ) VALUES (
                p_receipt_id, p_deposit_id, p_payment_id,
                p_accepted_required_amount_usd_cents, p_received_at, p_actor_id
            );
            UPDATE app.units AS unit
            SET status = 'RESERVED', version = unit.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE unit.id = p_unit_id;
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.create',
                p_idempotency_key, p_request_digest, p_reservation_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'unit_id', p_unit_id,
                    'customer_id', p_customer_id,
                    'status', 'ACTIVE',
                    'effective_expiration_date', p_original_expiration_date,
                    'deposit_id', p_deposit_id,
                    'received_usd_cents', p_accepted_required_amount_usd_cents,
                    'version', 1
                )
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                resulting_state, correlation_id, source, outcome, customer_id, unit_id
            ) VALUES
            (
                p_reservation_id, statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date,
                p_actor_id, 'reservation.activated', 'reservation', p_reservation_id,
                'Reservation activated after accepted Security Deposit receipt',
                p_authorization_reference, p_property_id,
                jsonb_build_object(
                    'status', 'ACTIVE',
                    'reservation_date', p_reservation_date,
                    'effective_expiration_date', p_original_expiration_date
                ),
                p_idempotency_key, 'API', 'SUCCEEDED', p_customer_id, p_unit_id
            ),
            (
                p_acceptance_id, statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date,
                p_actor_id, 'reservation.deposit_acceptance.recorded',
                'reservation_deposit_acceptance', p_acceptance_id,
                p_acceptance_reason, p_authorization_reference, p_property_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'suggested_amount_usd_cents', v_suggestion,
                    'accepted_required_amount_usd_cents', p_accepted_required_amount_usd_cents,
                    'acceptance_kind', p_acceptance_kind
                ),
                p_idempotency_key, 'API', 'SUCCEEDED', p_customer_id, p_unit_id
            ),
            (
                p_deposit_id, statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date,
                p_actor_id, 'reservation.security_deposit.created', 'deposit', p_deposit_id,
                'One continuing Security Deposit obligation created for Reservation',
                p_authorization_reference, p_property_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'required_usd_cents', p_required_deposit_usd_cents
                ),
                p_idempotency_key, 'API', 'SUCCEEDED', p_customer_id, p_unit_id
            ),
            (
                p_receipt_id, statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date,
                p_actor_id, 'reservation.security_deposit.received',
                'deposit_receipt', p_receipt_id,
                'Accepted Reservation-stage Security Deposit amount received',
                p_authorization_reference, p_property_id,
                jsonb_build_object(
                    'deposit_id', p_deposit_id,
                    'payment_id', p_payment_id,
                    'amount_usd_cents', p_accepted_required_amount_usd_cents
                ),
                p_idempotency_key, 'API', 'SUCCEEDED', p_customer_id, p_unit_id
            );
            RETURN QUERY
            SELECT reservation.id, reservation.unit_id, reservation.customer_id,
                   reservation.status, reservation.effective_expiration_date,
                   deposit.id, COALESCE(sum(receipt.amount_usd_cents), 0)::bigint,
                   reservation.version
            FROM app.reservations AS reservation
            JOIN app.deposits AS deposit ON deposit.reservation_id = reservation.id
            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
            WHERE reservation.id = p_reservation_id
            GROUP BY reservation.id, deposit.id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.extend_reservation(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_notice_id uuid,
            p_reservation_id uuid,
            p_new_expiration_date date,
            p_approved_at timestamptz,
            p_reason_memo text,
            p_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            reservation_id uuid,
            original_expiration_date date,
            previous_expiration_date date,
            effective_expiration_date date,
            status text,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_timezone text;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.extend/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.extend'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'original_expiration_date')::date,
                    (v_command.result_snapshot ->> 'previous_expiration_date')::date,
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    v_command.result_snapshot ->> 'status',
                    (v_command.result_snapshot ->> 'version')::integer;
                RETURN;
            END IF;
            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE reservation.id = p_reservation_id
              AND unit.property_id = p_property_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found in the Property'
                    USING ERRCODE = 'P0002';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property
            WHERE property.id = p_property_id;
            INSERT INTO app.reservation_extension_notices (
                id, reservation_id, original_expiration_date,
                previous_expiration_date, new_expiration_date,
                approved_at, approved_by, reason_memo, authorization_reference
            ) VALUES (
                p_notice_id, p_reservation_id, v_reservation.original_expiration_date,
                v_reservation.effective_expiration_date, p_new_expiration_date,
                p_approved_at, p_actor_id, nullif(btrim(p_reason_memo), ''),
                btrim(p_authorization_reference)
            );
            UPDATE app.reservations AS reservation
            SET effective_expiration_date = p_new_expiration_date,
                version = reservation.version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE reservation.id = p_reservation_id;
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.extend',
                p_idempotency_key, p_request_digest, p_notice_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id,
                    'original_expiration_date', v_reservation.original_expiration_date,
                    'previous_expiration_date', v_reservation.effective_expiration_date,
                    'effective_expiration_date', p_new_expiration_date,
                    'status', 'ACTIVE',
                    'version', v_reservation.version + 1
                )
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                customer_id, unit_id
            ) VALUES (
                p_notice_id, statement_timestamp(),
                timezone(v_timezone, statement_timestamp())::date,
                p_actor_id, 'reservation.extended', 'reservation', p_reservation_id,
                COALESCE(nullif(btrim(p_reason_memo), ''), 'Authorized Reservation extension'),
                p_authorization_reference, p_property_id,
                jsonb_build_object(
                    'effective_expiration_date', v_reservation.effective_expiration_date,
                    'version', v_reservation.version
                ),
                jsonb_build_object(
                    'effective_expiration_date', p_new_expiration_date,
                    'version', v_reservation.version + 1
                ),
                p_idempotency_key, 'API', 'SUCCEEDED',
                v_reservation.customer_id, v_reservation.unit_id
            );
            RETURN QUERY
            SELECT reservation.id, notice.original_expiration_date,
                   notice.previous_expiration_date,
                   reservation.effective_expiration_date,
                   reservation.status, reservation.version
            FROM app.reservation_extension_notices AS notice
            JOIN app.reservations AS reservation ON reservation.id = notice.reservation_id
            WHERE notice.id = p_notice_id;
        END;
        $$
        """
    )
    for function in (
        "app.reject_reservation_append_only_mutation()",
        "app.validate_reservation_insert()",
        "app.protect_reservation_history()",
        "app.reject_deposit_history_loss()",
        "app.validate_reservation_extension_notice()",
        "app.assert_reservation_extension_applied()",
        "app.validate_reservation_deposit_acceptance()",
        "app.validate_reservation_security_deposit()",
        "app.validate_deposit_receipt()",
        "app.assert_reservation_activation_bundle()",
        "app.create_reservation(uuid, uuid, text, uuid, uuid, uuid, date, bigint, date, uuid, bigint, text, timestamptz, text, text, jsonb, uuid, bigint, uuid, uuid, timestamptz, uuid)",
        "app.extend_reservation(uuid, uuid, text, uuid, uuid, date, timestamptz, text, text, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_bootstrap")
    op.execute(
        """
        REVOKE ALL ON TABLE
            app.reservations,
            app.reservation_extension_notices,
            app.reservation_deposit_acceptances,
            app.deposits,
            app.deposit_receipts,
            app.reservation_commands
        FROM PUBLIC, prm_runtime, prm_bootstrap
        """
    )
    op.execute(
        """
        GRANT SELECT ON TABLE
            app.reservations,
            app.reservation_extension_notices,
            app.reservation_deposit_acceptances,
            app.deposits,
            app.deposit_receipts
        TO prm_runtime
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.create_reservation(uuid, uuid, text, uuid, uuid, uuid, date, bigint, date, uuid, bigint, text, timestamptz, text, text, jsonb, uuid, bigint, uuid, uuid, timestamptz, uuid) "
        "TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.extend_reservation(uuid, uuid, text, uuid, uuid, date, timestamptz, text, text, uuid) "
        "TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback of Reservation and Deposit history."""
    raise RuntimeError("Reservation and reservation-deposit migration is forward-only")
