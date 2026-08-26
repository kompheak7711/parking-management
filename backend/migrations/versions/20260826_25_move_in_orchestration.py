"""Add atomic Reservation-to-Lease move-in orchestration."""

from alembic import op

revision = "20260826_25"
down_revision = "20260826_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-035 orchestration boundary."""
    op.execute(
        """
        ALTER TABLE app.deposits
        DROP CONSTRAINT deposits_reservation_security_shape,
        ADD CONSTRAINT deposits_reservation_security_shape CHECK (
            deposit_type = 'SECURITY'
            AND reservation_id IS NOT NULL
            AND pet_approval_id IS NULL
        ),
        ADD CONSTRAINT deposits_lease_fkey
            FOREIGN KEY (lease_id) REFERENCES app.leases(id) ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        CREATE TABLE app.move_in_events (
            id uuid PRIMARY KEY
                CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            reservation_id uuid NOT NULL UNIQUE
                REFERENCES app.reservations(id) ON DELETE RESTRICT,
            lease_id uuid NOT NULL UNIQUE REFERENCES app.leases(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            deposit_id uuid NOT NULL UNIQUE REFERENCES app.deposits(id) ON DELETE RESTRICT,
            actual_move_in_date date NOT NULL,
            expected_reservation_version integer NOT NULL CHECK (expected_reservation_version > 0),
            resulting_reservation_version integer NOT NULL
                CHECK (resulting_reservation_version = expected_reservation_version + 1),
            expected_lease_version integer NOT NULL CHECK (expected_lease_version > 0),
            resulting_lease_version integer NOT NULL
                CHECK (resulting_lease_version = expected_lease_version + 1),
            expected_unit_version integer NOT NULL CHECK (expected_unit_version > 0),
            resulting_unit_version integer NOT NULL
                CHECK (resulting_unit_version = expected_unit_version + 1),
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            authorization_reference text NOT NULL CHECK (
                authorization_reference = 'reservations.complete'
            ),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            CONSTRAINT move_in_events_idempotency_unique
                UNIQUE (property_id, actor_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX move_in_events_history_idx "
        "ON app.move_in_events(reservation_id, occurred_at, id)"
    )
    op.execute(
        """
        CREATE TABLE app.move_in_occupancy_links (
            move_in_event_id uuid NOT NULL
                REFERENCES app.move_in_events(id) ON DELETE RESTRICT,
            occupancy_id uuid NOT NULL UNIQUE
                REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            PRIMARY KEY (move_in_event_id, occupancy_id)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.protect_reservation_history()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
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
                        SELECT 1 FROM app.reservation_extension_notices AS notice
                        WHERE notice.reservation_id = OLD.id
                          AND notice.original_expiration_date = OLD.original_expiration_date
                          AND notice.previous_expiration_date = OLD.effective_expiration_date
                          AND notice.new_expiration_date = NEW.effective_expiration_date
                    )
                THEN
                    RAISE EXCEPTION 'Reservation expiration requires an immutable Extension Notice'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF OLD.status = 'ACTIVE' AND NEW.status = 'CANCELLED' THEN
                IF NEW.effective_expiration_date <> OLD.effective_expiration_date
                    OR NEW.resulting_lease_id IS NOT NULL OR NEW.completed_at IS NOT NULL
                THEN
                    RAISE EXCEPTION 'Reservation cancellation evidence is invalid'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF OLD.status = 'ACTIVE' AND NEW.status = 'COMPLETED' THEN
                IF NEW.effective_expiration_date <> OLD.effective_expiration_date
                    OR NEW.resulting_lease_id IS NULL OR NEW.completed_at IS NULL
                    OR NEW.cancellation_reason_code IS NOT NULL
                    OR NEW.cancellation_responsibility IS NOT NULL
                    OR NEW.cancelled_at IS NOT NULL
                    OR COALESCE(current_setting('app.move_in_event_id', true), '') = ''
                THEN
                    RAISE EXCEPTION 'Reservation completion evidence is invalid'
                        USING ERRCODE = '55000';
                END IF;
            ELSE
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
        CREATE OR REPLACE FUNCTION app.reject_deposit_history_loss()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
                AND current_setting('app.move_in_event_id', true) <> ''
                AND OLD.lease_id IS NULL AND NEW.lease_id IS NOT NULL
                AND NEW.id = OLD.id AND NEW.deposit_type = OLD.deposit_type
                AND NEW.customer_id = OLD.customer_id
                AND NEW.reservation_id = OLD.reservation_id
                AND NEW.pet_approval_id IS NOT DISTINCT FROM OLD.pet_approval_id
                AND NEW.required_usd_cents = OLD.required_usd_cents
                AND NEW.required_effective_date = OLD.required_effective_date
                AND NEW.version = OLD.version + 1
                AND NEW.created_at = OLD.created_at AND NEW.created_by = OLD.created_by
                AND NEW.updated_at >= OLD.updated_at
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Deposit identity and obligation history are protected'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_reservation_move_in_event()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF OLD.status = 'ACTIVE' AND NEW.status = 'COMPLETED' AND NOT EXISTS (
                SELECT 1 FROM app.move_in_events AS event
                WHERE event.reservation_id = NEW.id
                  AND event.lease_id = NEW.resulting_lease_id
                  AND event.expected_reservation_version = OLD.version
                  AND event.resulting_reservation_version = NEW.version
            ) THEN
                RAISE EXCEPTION 'Completion requires one matching immutable move-in event'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER reservations_move_in_event_complete
        AFTER UPDATE ON app.reservations DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_reservation_move_in_event()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.assert_move_in_event_applied()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM app.reservations AS reservation
                JOIN app.leases AS lease ON lease.id = NEW.lease_id
                JOIN app.units AS unit ON unit.id = NEW.unit_id
                JOIN app.deposits AS deposit ON deposit.id = NEW.deposit_id
                WHERE reservation.id = NEW.reservation_id
                  AND reservation.status = 'COMPLETED'
                  AND reservation.resulting_lease_id = NEW.lease_id
                  AND reservation.version = NEW.resulting_reservation_version
                  AND lease.unit_id = NEW.unit_id
                  AND lease.status = 'SIGNED'
                  AND lease.version = NEW.resulting_lease_version
                  AND unit.status = 'OCCUPIED'
                  AND unit.version = NEW.resulting_unit_version
                  AND deposit.reservation_id = NEW.reservation_id
                  AND deposit.lease_id = NEW.lease_id
            ) OR NOT EXISTS (
                SELECT 1 FROM app.move_in_occupancy_links AS link
                WHERE link.move_in_event_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'Move-in event requires the complete coordinated transition'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER move_in_event_applied
        AFTER INSERT ON app.move_in_events DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION app.assert_move_in_event_applied()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.complete_reservation_move_in(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_reservation_id uuid, p_lease_id uuid,
            p_expected_reservation_version integer, p_expected_lease_version integer,
            p_expected_unit_version integer, p_actual_move_in_date date,
            p_occupants jsonb, p_reason text, p_authorization_reference text,
            p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_prior app.move_in_events%ROWTYPE;
            v_reservation app.reservations%ROWTYPE;
            v_lease app.leases%ROWTYPE;
            v_unit app.units%ROWTYPE;
            v_deposit app.deposits%ROWTYPE;
            v_timezone text;
            v_business_date date;
            v_received bigint;
            v_item jsonb;
            v_occupancy_id uuid;
            v_customer_id uuid;
            v_occupancy_ids jsonb := '[]'::jsonb;
            v_result jsonb;
        BEGIN
            IF p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference <> 'reservations.complete'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR p_actual_move_in_date IS NULL
                OR jsonb_typeof(p_occupants) <> 'array'
                OR jsonb_array_length(p_occupants) < 1
                OR jsonb_array_length(p_occupants) > 20
            THEN
                RAISE EXCEPTION 'Move-in command evidence is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || '|' || p_actor_id::text || '|move-in|'
                || p_idempotency_key::text, 0
            ));
            SELECT * INTO v_prior FROM app.move_in_events AS event
            WHERE event.property_id = p_property_id AND event.actor_id = p_actor_id
              AND event.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_prior.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Move-in idempotency key was reused' USING ERRCODE = '23505';
                END IF;
                RETURN v_prior.result_snapshot;
            END IF;

            SELECT reservation.* INTO v_reservation
            FROM app.reservations AS reservation
            JOIN app.units AS unit ON unit.id = reservation.unit_id
            WHERE reservation.id = p_reservation_id AND unit.property_id = p_property_id
            FOR UPDATE OF reservation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Reservation was not found' USING ERRCODE = 'P0002';
            END IF;
            SELECT * INTO STRICT v_unit FROM app.units WHERE id = v_reservation.unit_id FOR UPDATE;
            SELECT * INTO v_lease FROM app.leases WHERE id = p_lease_id FOR UPDATE;
            IF NOT FOUND OR v_lease.unit_id <> v_unit.id
                OR v_lease.primary_tenant_id <> v_reservation.customer_id
            THEN
                RAISE EXCEPTION 'Lease source does not match Reservation'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_reservation.version <> p_expected_reservation_version
                OR v_lease.version <> p_expected_lease_version
                OR v_unit.version <> p_expected_unit_version
            THEN RAISE EXCEPTION 'Move-in version is stale' USING ERRCODE = '40001'; END IF;
            SELECT property.timezone_name,
                   timezone(property.timezone_name, statement_timestamp())::date
            INTO STRICT v_timezone, v_business_date FROM app.properties AS property
            WHERE property.id = p_property_id;
            IF v_reservation.status <> 'ACTIVE' OR v_unit.status <> 'RESERVED'
                OR v_lease.status <> 'SIGNED'
                OR p_actual_move_in_date < v_reservation.reservation_date
                OR p_actual_move_in_date < v_lease.start_date
                OR p_actual_move_in_date > v_lease.end_date
                OR timezone(v_timezone, v_lease.signed_at)::date > p_actual_move_in_date
                OR p_actual_move_in_date > v_business_date
                OR v_business_date > v_reservation.effective_expiration_date
            THEN RAISE EXCEPTION 'Move-in lifecycle prerequisites are not satisfied'
                USING ERRCODE = '23514'; END IF;
            IF EXISTS (
                SELECT 1 FROM app.occupancies AS occupancy
                JOIN app.leases AS lease ON lease.id = occupancy.lease_id
                WHERE lease.unit_id = v_unit.id AND occupancy.move_out_date IS NULL
            ) THEN RAISE EXCEPTION 'Unit has an open Occupancy' USING ERRCODE = '23P01'; END IF;
            SELECT deposit.* INTO v_deposit
            FROM app.deposits AS deposit
            WHERE deposit.reservation_id = v_reservation.id AND deposit.deposit_type = 'SECURITY'
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Required Security Deposit was not found'
                    USING ERRCODE = '23514';
            END IF;
            SELECT COALESCE(sum(receipt.amount_usd_cents), 0) INTO v_received
            FROM app.deposit_receipts AS receipt
            WHERE receipt.deposit_id = v_deposit.id
              AND timezone(v_timezone, receipt.occurred_at)::date <= p_actual_move_in_date;
            IF v_deposit.lease_id IS NOT NULL
                OR v_received <> v_deposit.required_usd_cents
            THEN RAISE EXCEPTION 'Required Security Deposit is not fully paid and unlinked'
                USING ERRCODE = '23514'; END IF;
            IF EXISTS (
                SELECT 1 FROM app.lease_pet_approvals AS approval
                WHERE approval.lease_id = v_lease.id
                  AND approval.approved_date <= p_actual_move_in_date
                  AND approval.deposit_required_by_signed_terms
                  AND NOT EXISTS (
                      SELECT 1 FROM app.deposits AS pet_deposit
                      WHERE pet_deposit.deposit_type = 'PET'
                        AND pet_deposit.lease_id = v_lease.id
                        AND pet_deposit.pet_approval_id = approval.id
                        AND (
                            SELECT COALESCE(sum(receipt.amount_usd_cents), 0)
                            FROM app.deposit_receipts AS receipt
                            WHERE receipt.deposit_id = pet_deposit.id
                              AND timezone(v_timezone, receipt.occurred_at)::date
                                  <= p_actual_move_in_date
                        ) = pet_deposit.required_usd_cents
                  )
            ) THEN
                RAISE EXCEPTION 'Required Pet Deposit is not fully paid'
                    USING ERRCODE = '23514';
            END IF;

            FOR v_item IN SELECT value FROM jsonb_array_elements(p_occupants) AS element(value)
            LOOP
                IF jsonb_typeof(v_item) <> 'object'
                    OR NOT (v_item ? 'occupancy_id' AND v_item ? 'customer_id')
                    OR (SELECT count(*) FROM jsonb_object_keys(v_item)) <> 2
                THEN RAISE EXCEPTION 'Occupant evidence is invalid' USING ERRCODE = '22023'; END IF;
                BEGIN
                    v_occupancy_id := (v_item->>'occupancy_id')::uuid;
                    v_customer_id := (v_item->>'customer_id')::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'Occupant identity is invalid' USING ERRCODE = '22023';
                END;
                IF v_occupancy_id = '00000000-0000-0000-0000-000000000000'::uuid
                    OR v_customer_id = '00000000-0000-0000-0000-000000000000'::uuid
                    OR NOT EXISTS (SELECT 1 FROM app.customers WHERE id = v_customer_id)
                    OR v_occupancy_ids @> jsonb_build_array(v_occupancy_id)
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(p_occupants) AS duplicate(value)
                        WHERE duplicate.value->>'customer_id' = v_customer_id::text
                        GROUP BY duplicate.value->>'customer_id' HAVING count(*) > 1
                    )
                THEN RAISE EXCEPTION 'Occupant identity is invalid or duplicated'
                    USING ERRCODE = '23514'; END IF;
                INSERT INTO app.occupancies(
                    id, lease_id, customer_id, move_in_date, created_by, updated_by
                ) VALUES (
                    v_occupancy_id, v_lease.id, v_customer_id,
                    p_actual_move_in_date, p_actor_id, p_actor_id
                );
                v_occupancy_ids := v_occupancy_ids || jsonb_build_array(v_occupancy_id);
            END LOOP;

            PERFORM set_config('app.move_in_event_id', p_event_id::text, true);
            UPDATE app.reservations SET status = 'COMPLETED', resulting_lease_id = v_lease.id,
                completed_at = statement_timestamp(), version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_reservation.id;
            UPDATE app.units SET status = 'OCCUPIED', version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_unit.id;
            UPDATE app.leases SET version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_lease.id;
            UPDATE app.deposits SET lease_id = v_lease.id, version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_deposit.id;

            v_result := jsonb_build_object(
                'event_id', p_event_id, 'property_id', p_property_id,
                'reservation_id', v_reservation.id,
                'reservation_version', v_reservation.version + 1,
                'lease_id', v_lease.id, 'lease_version', v_lease.version + 1,
                'unit_id', v_unit.id, 'unit_version', v_unit.version + 1,
                'deposit_id', v_deposit.id, 'deposit_version', v_deposit.version + 1,
                'actual_move_in_date', p_actual_move_in_date,
                'occupancy_ids', v_occupancy_ids
            );
            INSERT INTO app.move_in_events(
                id, property_id, actor_id, idempotency_key, request_digest,
                reservation_id, lease_id, unit_id, deposit_id, actual_move_in_date,
                expected_reservation_version, resulting_reservation_version,
                expected_lease_version, resulting_lease_version,
                expected_unit_version, resulting_unit_version,
                reason, authorization_reference, result_snapshot
            ) VALUES (
                p_event_id, p_property_id, p_actor_id, p_idempotency_key, p_request_digest,
                v_reservation.id, v_lease.id, v_unit.id, v_deposit.id, p_actual_move_in_date,
                v_reservation.version, v_reservation.version + 1,
                v_lease.version, v_lease.version + 1,
                v_unit.version, v_unit.version + 1,
                p_reason, p_authorization_reference, v_result
            );
            INSERT INTO app.move_in_occupancy_links(move_in_event_id, occupancy_id)
            SELECT p_event_id, (value #>> '{}')::uuid
            FROM jsonb_array_elements(v_occupancy_ids);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END;
        $$
        """
    )
    for table in ("move_in_events", "move_in_occupancy_links"):
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
    op.execute(
        "REVOKE ALL ON TABLE app.move_in_events, app.move_in_occupancy_links "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT ON TABLE app.move_in_events, app.move_in_occupancy_links TO prm_runtime"
    )
    for function in (
        "app.assert_reservation_move_in_event()",
        "app.assert_move_in_event_applied()",
        "app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,integer,date,jsonb,text,text,uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.complete_reservation_move_in(uuid,uuid,text,uuid,uuid,uuid,integer,integer,"
        "integer,date,jsonb,text,text,uuid) "
        "TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback of move-in and Occupancy history."""
    raise RuntimeError("Move-in orchestration migration is forward-only")
