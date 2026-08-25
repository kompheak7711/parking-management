"""Add transactional Reservation lifecycle and Unit availability services."""

from alembic import op

revision = "20260825_20"
down_revision = "20260825_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the bounded V1-030 lifecycle boundary without financial disposition."""
    op.execute(
        """
        CREATE TABLE app.reservation_lifecycle_events (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            reservation_id uuid NOT NULL
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            event_kind text NOT NULL
                CHECK (event_kind IN ('EXPIRATION', 'CANCELLATION')),
            cancellation_reason_code text NOT NULL,
            cancellation_responsibility text NOT NULL
                CHECK (cancellation_responsibility IN ('CUSTOMER', 'PROPERTY')),
            property_could_provide_unit boolean NOT NULL,
            reason_memo text,
            coordination_reference text,
            authorization_reference text NOT NULL,
            occurred_at timestamptz NOT NULL,
            business_date date NOT NULL,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            expected_version integer NOT NULL CHECK (expected_version > 0),
            resulting_version integer NOT NULL CHECK (resulting_version = expected_version + 1),
            deposit_outcome_state text NOT NULL DEFAULT 'PENDING_V1_031'
                CHECK (deposit_outcome_state = 'PENDING_V1_031'),
            CONSTRAINT reservation_lifecycle_reason_normalized CHECK (
                length(btrim(cancellation_reason_code)) > 0
                AND cancellation_reason_code = btrim(cancellation_reason_code)
                AND (
                    reason_memo IS NULL OR (
                        length(btrim(reason_memo)) > 0
                        AND reason_memo = btrim(reason_memo)
                    )
                )
                AND length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            ),
            CONSTRAINT reservation_lifecycle_classification CHECK (
                (
                    event_kind = 'EXPIRATION'
                    AND cancellation_reason_code = 'RESERVATION_EXPIRED'
                    AND cancellation_responsibility = 'CUSTOMER'
                    AND property_could_provide_unit
                    AND coordination_reference IS NULL
                ) OR (
                    event_kind = 'CANCELLATION'
                    AND cancellation_reason_code <> 'RESERVATION_EXPIRED'
                    AND cancellation_responsibility = 'CUSTOMER'
                    AND property_could_provide_unit
                    AND coordination_reference IS NULL
                ) OR (
                    event_kind = 'CANCELLATION'
                    AND cancellation_reason_code <> 'RESERVATION_EXPIRED'
                    AND cancellation_responsibility = 'PROPERTY'
                    AND NOT property_could_provide_unit
                    AND length(btrim(coordination_reference)) > 0
                    AND coordination_reference = btrim(coordination_reference)
                )
            ),
            CONSTRAINT reservation_lifecycle_one_terminal_event UNIQUE (reservation_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX reservation_lifecycle_history_idx "
        "ON app.reservation_lifecycle_events(reservation_id, occurred_at, id)"
    )
    op.execute(
        """
        CREATE TRIGGER reservation_lifecycle_events_reject_update_or_delete
        BEFORE UPDATE OR DELETE ON app.reservation_lifecycle_events
        FOR EACH ROW EXECUTE FUNCTION app.reject_reservation_append_only_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reservation_lifecycle_events_reject_truncate
        BEFORE TRUNCATE ON app.reservation_lifecycle_events
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_reservation_append_only_mutation()
        """
    )
    op.execute(
        "ALTER TABLE app.reservation_commands DROP CONSTRAINT reservation_commands_action_check"
    )
    op.execute(
        """
        ALTER TABLE app.reservation_commands
        ADD CONSTRAINT reservation_commands_action_check CHECK (
            action IN (
                'reservation.create',
                'reservation.extend',
                'reservation.expire',
                'reservation.cancel'
            )
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.protect_reservation_history()
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
                OR NEW.agreed_monthly_rent_usd_cents
                    IS DISTINCT FROM OLD.agreed_monthly_rent_usd_cents
                OR NEW.original_expiration_date IS DISTINCT FROM OLD.original_expiration_date
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Reservation identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = NEW.status THEN
                IF NEW.cancellation_reason_code IS DISTINCT FROM OLD.cancellation_reason_code
                    OR NEW.cancellation_responsibility
                        IS DISTINCT FROM OLD.cancellation_responsibility
                    OR NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at
                    OR NEW.resulting_lease_id IS DISTINCT FROM OLD.resulting_lease_id
                    OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                THEN
                    RAISE EXCEPTION 'Reservation lifecycle evidence is immutable'
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
            ELSIF NOT (
                OLD.status = 'ACTIVE'
                AND NEW.status = 'CANCELLED'
                AND NEW.effective_expiration_date = OLD.effective_expiration_date
                AND NEW.resulting_lease_id IS NULL
                AND NEW.completed_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Reservation transition is not available in this lifecycle boundary'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_cancellation_event()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF OLD.status = 'ACTIVE' AND NEW.status = 'CANCELLED' AND NOT EXISTS (
                SELECT 1
                FROM app.reservation_lifecycle_events AS event
                WHERE event.reservation_id = NEW.id
                  AND event.cancellation_reason_code = NEW.cancellation_reason_code
                  AND event.cancellation_responsibility = NEW.cancellation_responsibility
                  AND event.occurred_at = NEW.cancelled_at
                  AND event.expected_version = OLD.version
                  AND event.resulting_version = NEW.version
            ) THEN
                RAISE EXCEPTION 'Cancellation requires one matching immutable lifecycle event'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservations_cancellation_event_complete
        AFTER UPDATE ON app.reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_cancellation_event()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_lifecycle_event_applied()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.reservations AS reservation
                WHERE reservation.id = NEW.reservation_id
                  AND reservation.status = 'CANCELLED'
                  AND reservation.cancellation_reason_code = NEW.cancellation_reason_code
                  AND reservation.cancellation_responsibility = NEW.cancellation_responsibility
                  AND reservation.cancelled_at = NEW.occurred_at
                  AND reservation.version = NEW.resulting_version
            ) THEN
                RAISE EXCEPTION 'Lifecycle event requires the matching Reservation transition'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservation_lifecycle_event_applied
        AFTER INSERT ON app.reservation_lifecycle_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_lifecycle_event_applied()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_unit_summary()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_unit_status text;
        BEGIN
            SELECT unit.status INTO STRICT v_unit_status
            FROM app.units AS unit
            WHERE unit.id = NEW.unit_id;
            IF (NEW.status = 'ACTIVE') IS DISTINCT FROM (v_unit_status = 'RESERVED') THEN
                RAISE EXCEPTION 'Reservation status must match its Unit availability'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservations_validate_unit_summary
        AFTER INSERT OR UPDATE OF status, unit_id ON app.reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_unit_summary()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.validate_unit_reservation_summary()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_has_active boolean;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM app.reservations AS reservation
                WHERE reservation.unit_id = NEW.id AND reservation.status = 'ACTIVE'
            ) INTO v_has_active;
            IF (NEW.status = 'RESERVED') IS DISTINCT FROM v_has_active THEN
                RAISE EXCEPTION 'Unit RESERVED status must match its ACTIVE Reservation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER units_validate_reservation_summary
        BEFORE INSERT OR UPDATE OF status ON app.units
        FOR EACH ROW EXECUTE FUNCTION app.validate_unit_reservation_summary()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.extend_reservation_v2(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_notice_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
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
            IF v_reservation.version <> p_expected_version THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
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
            WHERE reservation.id = p_reservation_id
              AND reservation.version = p_expected_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
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
                    'status', 'ACTIVE', 'version', p_expected_version + 1
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
                    'version', p_expected_version
                ),
                jsonb_build_object(
                    'effective_expiration_date', p_new_expiration_date,
                    'version', p_expected_version + 1
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
    lifecycle_result = """
        reservation_id uuid,
        unit_id uuid,
        status text,
        cancellation_reason_code text,
        cancellation_responsibility text,
        effective_expiration_date date,
        version integer,
        unit_status text,
        unit_version integer,
        deposit_id uuid,
        deposit_received_usd_cents bigint,
        deposit_outcome_state text
    """
    op.execute(
        f"""
        CREATE FUNCTION app.cancel_reservation(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
            p_reason_code text,
            p_responsibility text,
            p_property_could_provide_unit boolean,
            p_reason_memo text,
            p_coordination_reference text,
            p_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_timezone text;
            v_business_date date;
            v_occurred_at timestamptz;
            v_deposit_id uuid;
            v_received bigint;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.cancel/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.cancel'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state';
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
            SELECT unit.* INTO STRICT v_unit
            FROM app.units AS unit WHERE unit.id = v_reservation.unit_id FOR UPDATE;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
            v_business_date := timezone(v_timezone, clock_timestamp())::date;
            IF v_reservation.version <> p_expected_version THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            IF v_reservation.status <> 'ACTIVE'
                OR btrim(p_reason_code) = ''
                OR p_reason_code <> btrim(p_reason_code)
                OR p_reason_code = 'RESERVATION_EXPIRED'
                OR p_responsibility NOT IN ('CUSTOMER', 'PROPERTY')
                OR (p_responsibility = 'CUSTOMER' AND NOT p_property_could_provide_unit)
                OR (p_responsibility = 'CUSTOMER' AND p_coordination_reference IS NOT NULL)
                OR (p_responsibility = 'CUSTOMER'
                    AND v_business_date > v_reservation.effective_expiration_date)
                OR (p_responsibility = 'PROPERTY' AND p_property_could_provide_unit)
                OR (p_responsibility = 'PROPERTY'
                    AND COALESCE(btrim(p_coordination_reference), '') = '')
                OR COALESCE(btrim(p_authorization_reference), '') = ''
            THEN
                RAISE EXCEPTION 'Reservation cancellation classification is invalid'
                    USING ERRCODE = '23514';
            END IF;
            v_occurred_at := statement_timestamp();
            SELECT deposit.id, COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO STRICT v_deposit_id, v_received
            FROM app.deposits AS deposit
            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
            WHERE deposit.reservation_id = p_reservation_id
            GROUP BY deposit.id;
            INSERT INTO app.reservation_lifecycle_events (
                id, reservation_id, event_kind, cancellation_reason_code,
                cancellation_responsibility, property_could_provide_unit,
                reason_memo, coordination_reference, authorization_reference,
                occurred_at, business_date, actor_id, expected_version, resulting_version
            ) VALUES (
                p_event_id, p_reservation_id, 'CANCELLATION', p_reason_code,
                p_responsibility, p_property_could_provide_unit,
                nullif(btrim(p_reason_memo), ''),
                CASE WHEN p_responsibility = 'PROPERTY'
                    THEN btrim(p_coordination_reference) ELSE NULL END,
                btrim(p_authorization_reference), v_occurred_at, v_business_date,
                p_actor_id, p_expected_version, p_expected_version + 1
            );
            UPDATE app.reservations AS reservation
            SET status = 'CANCELLED', cancellation_reason_code = p_reason_code,
                cancellation_responsibility = p_responsibility,
                cancelled_at = v_occurred_at, version = reservation.version + 1,
                updated_at = v_occurred_at, updated_by = p_actor_id
            WHERE reservation.id = p_reservation_id
              AND reservation.version = p_expected_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            UPDATE app.units AS unit
            SET status = 'VACANT', version = unit.version + 1,
                updated_at = v_occurred_at, updated_by = p_actor_id
            WHERE unit.id = v_reservation.unit_id AND unit.version = v_unit.version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit version changed during Reservation cancellation'
                    USING ERRCODE = '40001';
            END IF;
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.cancel', p_idempotency_key,
                p_request_digest, p_event_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id, 'unit_id', v_reservation.unit_id,
                    'status', 'CANCELLED', 'cancellation_reason_code', p_reason_code,
                    'cancellation_responsibility', p_responsibility,
                    'effective_expiration_date', v_reservation.effective_expiration_date,
                    'version', p_expected_version + 1, 'unit_status', 'VACANT',
                    'unit_version', v_unit.version + 1, 'deposit_id', v_deposit_id,
                    'deposit_received_usd_cents', v_received,
                    'deposit_outcome_state', 'PENDING_V1_031'
                )
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                customer_id, unit_id
            ) VALUES (
                p_event_id, v_occurred_at, v_business_date, p_actor_id,
                'reservation.cancelled', 'reservation', p_reservation_id,
                COALESCE(nullif(btrim(p_reason_memo), ''), p_reason_code),
                p_authorization_reference, p_property_id,
                jsonb_build_object('status', 'ACTIVE', 'version', p_expected_version),
                jsonb_build_object(
                    'status', 'CANCELLED', 'reason_code', p_reason_code,
                    'responsibility', p_responsibility,
                    'version', p_expected_version + 1,
                    'deposit_outcome_state', 'PENDING_V1_031'
                ),
                p_idempotency_key, 'API', 'SUCCEEDED',
                v_reservation.customer_id, v_reservation.unit_id
            );
            RETURN QUERY SELECT
                p_reservation_id, v_reservation.unit_id, 'CANCELLED'::text,
                p_reason_code, p_responsibility,
                v_reservation.effective_expiration_date, p_expected_version + 1,
                'VACANT'::text, v_unit.version + 1, v_deposit_id, v_received,
                'PENDING_V1_031'::text;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION app.expire_reservation(
            p_property_id uuid,
            p_idempotency_key uuid,
            p_request_digest text,
            p_event_id uuid,
            p_reservation_id uuid,
            p_expected_version integer,
            p_property_could_provide_unit boolean,
            p_authorization_reference text,
            p_actor_id uuid
        )
        RETURNS TABLE({lifecycle_result})
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_command app.reservation_commands%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_timezone text;
            v_business_date date;
            v_occurred_at timestamptz;
            v_deposit_id uuid;
            v_received bigint;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'reservation-command/' || p_actor_id::text || '/'
                    || p_property_id::text || '/reservation.expire/'
                    || p_idempotency_key::text, 0
                )
            );
            SELECT command.* INTO v_command
            FROM app.reservation_commands AS command
            WHERE command.actor_id = p_actor_id
              AND command.property_id = p_property_id
              AND command.action = 'reservation.expire'
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_command.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Reservation idempotency key was reused'
                        USING ERRCODE = 'P0001';
                END IF;
                RETURN QUERY SELECT
                    (v_command.result_snapshot ->> 'reservation_id')::uuid,
                    (v_command.result_snapshot ->> 'unit_id')::uuid,
                    v_command.result_snapshot ->> 'status',
                    v_command.result_snapshot ->> 'cancellation_reason_code',
                    v_command.result_snapshot ->> 'cancellation_responsibility',
                    (v_command.result_snapshot ->> 'effective_expiration_date')::date,
                    (v_command.result_snapshot ->> 'version')::integer,
                    v_command.result_snapshot ->> 'unit_status',
                    (v_command.result_snapshot ->> 'unit_version')::integer,
                    (v_command.result_snapshot ->> 'deposit_id')::uuid,
                    (v_command.result_snapshot ->> 'deposit_received_usd_cents')::bigint,
                    v_command.result_snapshot ->> 'deposit_outcome_state';
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
            SELECT unit.* INTO STRICT v_unit
            FROM app.units AS unit WHERE unit.id = v_reservation.unit_id FOR UPDATE;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
            v_business_date := timezone(v_timezone, clock_timestamp())::date;
            IF v_reservation.version <> p_expected_version THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            IF v_reservation.status <> 'ACTIVE'
                OR v_business_date <= v_reservation.effective_expiration_date
                OR NOT p_property_could_provide_unit
                OR COALESCE(btrim(p_authorization_reference), '') = ''
            THEN
                RAISE EXCEPTION 'Reservation is not eligible for automatic expiration'
                    USING ERRCODE = '23514';
            END IF;
            v_occurred_at := statement_timestamp();
            SELECT deposit.id, COALESCE(sum(receipt.amount_usd_cents), 0)::bigint
            INTO STRICT v_deposit_id, v_received
            FROM app.deposits AS deposit
            LEFT JOIN app.deposit_receipts AS receipt ON receipt.deposit_id = deposit.id
            WHERE deposit.reservation_id = p_reservation_id
            GROUP BY deposit.id;
            INSERT INTO app.reservation_lifecycle_events (
                id, reservation_id, event_kind, cancellation_reason_code,
                cancellation_responsibility, property_could_provide_unit,
                authorization_reference, occurred_at, business_date, actor_id,
                expected_version, resulting_version
            ) VALUES (
                p_event_id, p_reservation_id, 'EXPIRATION', 'RESERVATION_EXPIRED',
                'CUSTOMER', true, btrim(p_authorization_reference), v_occurred_at,
                v_business_date, p_actor_id, p_expected_version, p_expected_version + 1
            );
            UPDATE app.reservations AS reservation
            SET status = 'CANCELLED', cancellation_reason_code = 'RESERVATION_EXPIRED',
                cancellation_responsibility = 'CUSTOMER', cancelled_at = v_occurred_at,
                version = reservation.version + 1, updated_at = v_occurred_at,
                updated_by = p_actor_id
            WHERE reservation.id = p_reservation_id
              AND reservation.version = p_expected_version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation version precondition was not met'
                    USING ERRCODE = '40001';
            END IF;
            UPDATE app.units AS unit
            SET status = 'VACANT', version = unit.version + 1,
                updated_at = v_occurred_at, updated_by = p_actor_id
            WHERE unit.id = v_reservation.unit_id AND unit.version = v_unit.version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit version changed during Reservation expiration'
                    USING ERRCODE = '40001';
            END IF;
            INSERT INTO app.reservation_commands (
                actor_id, property_id, action, idempotency_key, request_digest,
                result_id, result_snapshot
            ) VALUES (
                p_actor_id, p_property_id, 'reservation.expire', p_idempotency_key,
                p_request_digest, p_event_id,
                jsonb_build_object(
                    'reservation_id', p_reservation_id, 'unit_id', v_reservation.unit_id,
                    'status', 'CANCELLED',
                    'cancellation_reason_code', 'RESERVATION_EXPIRED',
                    'cancellation_responsibility', 'CUSTOMER',
                    'effective_expiration_date', v_reservation.effective_expiration_date,
                    'version', p_expected_version + 1, 'unit_status', 'VACANT',
                    'unit_version', v_unit.version + 1, 'deposit_id', v_deposit_id,
                    'deposit_received_usd_cents', v_received,
                    'deposit_outcome_state', 'PENDING_V1_031'
                )
            );
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id,
                previous_state, resulting_state, correlation_id, source, outcome,
                customer_id, unit_id
            ) VALUES (
                p_event_id, v_occurred_at, v_business_date, p_actor_id,
                'reservation.expired', 'reservation', p_reservation_id,
                'Reservation expired after its complete Property-local expiration date',
                p_authorization_reference, p_property_id,
                jsonb_build_object('status', 'ACTIVE', 'version', p_expected_version),
                jsonb_build_object(
                    'status', 'CANCELLED', 'reason_code', 'RESERVATION_EXPIRED',
                    'responsibility', 'CUSTOMER', 'version', p_expected_version + 1,
                    'deposit_outcome_state', 'PENDING_V1_031'
                ),
                p_idempotency_key, 'SCHEDULED', 'SUCCEEDED',
                v_reservation.customer_id, v_reservation.unit_id
            );
            RETURN QUERY SELECT
                p_reservation_id, v_reservation.unit_id, 'CANCELLED'::text,
                'RESERVATION_EXPIRED'::text, 'CUSTOMER'::text,
                v_reservation.effective_expiration_date, p_expected_version + 1,
                'VACANT'::text, v_unit.version + 1, v_deposit_id, v_received,
                'PENDING_V1_031'::text;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.list_due_reservations(p_property_id uuid, p_limit integer)
        RETURNS TABLE(
            reservation_id uuid,
            effective_expiration_date date,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_timezone text;
            v_business_date date;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Due Reservation limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            SELECT property.timezone_name INTO STRICT v_timezone
            FROM app.properties AS property WHERE property.id = p_property_id;
            v_business_date := timezone(v_timezone, clock_timestamp())::date;
            RETURN QUERY
            SELECT reservation.id, reservation.effective_expiration_date,
                   reservation.version
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE unit.property_id = p_property_id
              AND reservation.status = 'ACTIVE'
              AND reservation.effective_expiration_date < v_business_date
            ORDER BY reservation.effective_expiration_date, reservation.id
            LIMIT p_limit;
        END;
        $$
        """
    )
    functions = (
        "app.assert_reservation_cancellation_event()",
        "app.assert_lifecycle_event_applied()",
        "app.assert_reservation_unit_summary()",
        "app.validate_unit_reservation_summary()",
        "app.extend_reservation_v2(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)",
        "app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)",
        "app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)",
        "app.list_due_reservations(uuid,integer)",
    )
    for function in functions:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_bootstrap")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "app.extend_reservation(uuid,uuid,text,uuid,uuid,date,timestamptz,text,text,uuid) "
        "FROM prm_runtime"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.reservation_lifecycle_events "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.reservation_lifecycle_events TO prm_runtime")
    for function in (
        "app.extend_reservation_v2(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)",
        "app.cancel_reservation(uuid,uuid,text,uuid,uuid,integer,text,text,boolean,text,text,text,uuid)",
        "app.expire_reservation(uuid,uuid,text,uuid,uuid,integer,boolean,text,uuid)",
        "app.list_due_reservations(uuid,integer)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse rollback that could erase Reservation lifecycle history."""
    raise RuntimeError("Reservation lifecycle migration is forward-only")
