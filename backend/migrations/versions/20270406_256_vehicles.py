# ruff: noqa: E501
"""Vehicles (Parking Step 4, owner 2026-10-30).

Revision ID: 20270406_256
Revises: 20270405_255
Create Date: 2026-10-30

A Lease of a Parking holds one vehicle at a time. The vehicle takes the Occupancy slot: an
Occupancy row with a `vehicle_id` says "this vehicle is parked here under this Lease from day X
to day Y"; its `customer_id` is the vehicle's owner, who is the Primary Tenant or a Signer.
Hidden names stay Property Rental's (`occupancy`, `occupant`); only vehicle parts are new.

- `app.vehicles`: a record under a Customer (type, plate as typed in Khmer or Latin, never
  deleted); `plate_match_key` ignores spaces, dashes, dots and case so the screen can warn about
  a duplicate plate (never merged). Written only by `app.create_vehicle` / `app.update_vehicle`,
  audited in `app.audit_events` so the Customer's History shows them.
- `app.record_lease_vehicle_move_in` checks the vehicle (owner on the Lease, type allowed in
  the Parking's type, not parked elsewhere, nothing moved in yet) and then calls Property
  Rental's `app.record_signed_lease_move_in` as it is, with the owner as the one occupant; a
  BEFORE INSERT trigger fills `vehicle_id` from the transaction setting
  `app.occupancy_vehicle_id` (the precedent of `app.lease_signer_actor_id`).
- `app.change_lease_vehicle` ends the old vehicle's row and starts the new one the same day in
  one transaction; both rows stay; the Lease goes on (version + 1); one append-only row of
  `app.lease_vehicle_changes` shows in the Lease History.
- `app.vehicle_type_allowed`: each vehicle type parks only in its own kind of place, matched by
  the Parking Type code (Settings cannot change a code): Car → COVERED or UNCOVERED; Motorbike →
  MOTORBIKE; Tuk-tuk and food cart → TUK_TUK_FOOD_CART. A code the function does not know (a
  Parking Type added later) allows no vehicle type until it is added here.
- The only vehicle never moves out alone: the guard trigger refuses an end of a vehicle row of a
  SIGNED Lease unless Change vehicle set `app.occupancy_vehicle_change`; the Move-out page ends it
  after Termination (Property Rental's `physical_move_out_record`, unchanged).
- The one Property Rental object edited: `occupancies_customer_lease_period_exclusive` now
  covers people only (`WHERE vehicle_id IS NULL`), so the same owner's two vehicles hand over
  on the same day.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20270406_256"
down_revision: str | None = "20270405_255"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE = "app.create_vehicle(uuid,uuid,text,text,uuid)"
UPDATE = "app.update_vehicle(uuid,integer,text,text,uuid)"
MOVE_IN = "app.record_lease_vehicle_move_in(uuid,uuid,text,uuid,uuid,integer,date,uuid,uuid,text,text,uuid)"
CHANGE = "app.change_lease_vehicle(uuid,uuid,text,uuid,uuid,integer,uuid,uuid,date,text,text,uuid)"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.vehicles (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            customer_id uuid NOT NULL REFERENCES app.customers(id) ON DELETE RESTRICT,
            vehicle_type text NOT NULL
                CHECK (vehicle_type IN ('CAR', 'MOTORBIKE', 'TUK_TUK', 'FOOD_CART')),
            plate_text text NOT NULL
                CHECK (plate_text = btrim(plate_text) AND length(plate_text) BETWEEN 1 AND 32),
            plate_match_key text NOT NULL GENERATED ALWAYS AS (
                upper(regexp_replace(plate_text, '[[:space:].-]', '', 'g'))
            ) STORED,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id)
        );
        CREATE INDEX vehicles_customer_idx ON app.vehicles(customer_id, created_at, id);
        CREATE INDEX vehicles_plate_match_idx ON app.vehicles(plate_match_key);
        COMMENT ON TABLE app.vehicles IS
            'Parking Step 4: a vehicle under a Customer; plate as typed, matched without spaces, dashes, dots and case; never deleted';

        CREATE FUNCTION app.reject_vehicle_delete() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'A vehicle is corrected, never deleted' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER vehicles_reject_delete BEFORE DELETE ON app.vehicles
            FOR EACH ROW EXECUTE FUNCTION app.reject_vehicle_delete();
        CREATE TRIGGER vehicles_reject_truncate BEFORE TRUNCATE ON app.vehicles
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_vehicle_delete();

        CREATE FUNCTION app.vehicle_type_allowed(p_vehicle_type text, p_unit_type text)
        RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT CASE upper(p_unit_type)
                WHEN 'COVERED' THEN p_vehicle_type = 'CAR'
                WHEN 'UNCOVERED' THEN p_vehicle_type = 'CAR'
                WHEN 'MOTORBIKE' THEN p_vehicle_type = 'MOTORBIKE'
                WHEN 'TUK_TUK_FOOD_CART' THEN p_vehicle_type IN ('TUK_TUK', 'FOOD_CART')
                ELSE false END
        $$;

        CREATE FUNCTION app.vehicle_json(p_vehicle app.vehicles) RETURNS jsonb
        LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object('vehicle_id', p_vehicle.id, 'customer_id', p_vehicle.customer_id,
                'customer_name', (SELECT legal_name FROM app.customers WHERE id = p_vehicle.customer_id),
                'vehicle_type', p_vehicle.vehicle_type, 'plate_text', p_vehicle.plate_text,
                'version', p_vehicle.version)
        $$;

        CREATE FUNCTION app.audit_vehicle(p_action text, p_actor_id uuid, p_previous app.vehicles,
            p_vehicle app.vehicles) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_property app.properties%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT v_property FROM app.properties LIMIT 1;
            INSERT INTO app.audit_events(id, occurred_at, business_date, actor_id, action, entity_type,
                entity_id, reason, authorization_reference, property_id, previous_state, resulting_state,
                correlation_id, source, outcome, authorization_evidence, customer_id)
            VALUES (gen_random_uuid(), statement_timestamp(),
                timezone(v_property.timezone_name, statement_timestamp())::date, p_actor_id, p_action,
                'vehicle', p_vehicle.id,
                CASE p_action WHEN 'vehicle.created' THEN 'Vehicle added' ELSE 'Vehicle corrected' END,
                'customers.manage', v_property.id,
                CASE WHEN p_previous.id IS NULL THEN NULL ELSE app.vehicle_json(p_previous) END,
                app.vehicle_json(p_vehicle), gen_random_uuid(), 'API', 'SUCCEEDED',
                jsonb_build_object('capability', 'customers.manage'), p_vehicle.customer_id);
        END $$;

        CREATE FUNCTION app.create_vehicle(p_vehicle_id uuid, p_customer_id uuid, p_vehicle_type text,
            p_plate_text text, p_actor_id uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_vehicle app.vehicles%ROWTYPE;
        BEGIN
            IF p_vehicle_id IS NULL OR p_customer_id IS NULL OR p_actor_id IS NULL
                OR p_vehicle_type IS NULL OR p_vehicle_type NOT IN ('CAR', 'MOTORBIKE', 'TUK_TUK', 'FOOD_CART')
                OR p_plate_text IS NULL OR p_plate_text <> btrim(p_plate_text)
                OR length(p_plate_text) NOT BETWEEN 1 AND 32
            THEN RAISE EXCEPTION 'Vehicle evidence is invalid' USING ERRCODE = '22023'; END IF;
            IF NOT EXISTS (SELECT 1 FROM app.customers WHERE id = p_customer_id AND deactivated_at IS NULL)
            THEN RAISE EXCEPTION 'Customer was not found' USING ERRCODE = 'P0002'; END IF;
            SELECT * INTO v_vehicle FROM app.vehicles WHERE id = p_vehicle_id;
            IF FOUND THEN
                -- The same vehicle sent again (a retry) is answered again; another one is refused.
                IF v_vehicle.customer_id <> p_customer_id OR v_vehicle.vehicle_type <> p_vehicle_type
                    OR v_vehicle.plate_text <> p_plate_text
                THEN RAISE EXCEPTION 'Vehicle identity was reused' USING ERRCODE = '23505'; END IF;
                RETURN app.vehicle_json(v_vehicle);
            END IF;
            INSERT INTO app.vehicles(id, customer_id, vehicle_type, plate_text, created_by, updated_by)
            VALUES (p_vehicle_id, p_customer_id, p_vehicle_type, p_plate_text, p_actor_id, p_actor_id)
            RETURNING * INTO v_vehicle;
            PERFORM app.audit_vehicle('vehicle.created', p_actor_id, NULL::app.vehicles, v_vehicle);
            RETURN app.vehicle_json(v_vehicle);
        END $$;

        CREATE FUNCTION app.update_vehicle(p_vehicle_id uuid, p_expected_version integer,
            p_vehicle_type text, p_plate_text text, p_actor_id uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior app.vehicles%ROWTYPE; v_vehicle app.vehicles%ROWTYPE;
        BEGIN
            IF p_vehicle_id IS NULL OR p_actor_id IS NULL OR p_expected_version IS NULL
                OR p_vehicle_type IS NULL OR p_vehicle_type NOT IN ('CAR', 'MOTORBIKE', 'TUK_TUK', 'FOOD_CART')
                OR p_plate_text IS NULL OR p_plate_text <> btrim(p_plate_text)
                OR length(p_plate_text) NOT BETWEEN 1 AND 32
            THEN RAISE EXCEPTION 'Vehicle evidence is invalid' USING ERRCODE = '22023'; END IF;
            SELECT * INTO v_prior FROM app.vehicles WHERE id = p_vehicle_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Vehicle was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_prior.version <> p_expected_version THEN
                RAISE EXCEPTION 'Vehicle version is stale' USING ERRCODE = '40001'; END IF;
            IF v_prior.vehicle_type = p_vehicle_type AND v_prior.plate_text = p_plate_text THEN
                RETURN app.vehicle_json(v_prior); END IF;
            UPDATE app.vehicles SET vehicle_type = p_vehicle_type, plate_text = p_plate_text,
                version = version + 1, updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_vehicle_id RETURNING * INTO v_vehicle;
            PERFORM app.audit_vehicle('vehicle.updated', p_actor_id, v_prior, v_vehicle);
            RETURN app.vehicle_json(v_vehicle);
        END $$;

        -- The vehicle takes the Occupancy slot: the owner's row carries the vehicle.
        ALTER TABLE app.occupancies
            ADD COLUMN vehicle_id uuid REFERENCES app.vehicles(id) ON DELETE RESTRICT;
        CREATE UNIQUE INDEX occupancies_one_open_vehicle_per_lease
            ON app.occupancies(lease_id) WHERE move_out_date IS NULL AND vehicle_id IS NOT NULL;
        ALTER TABLE app.occupancies
            ADD CONSTRAINT occupancies_vehicle_period_exclusive EXCLUDE USING gist (
                vehicle_id WITH =, daterange(move_in_date, move_out_date, '[)') WITH &&
            ) WHERE (vehicle_id IS NOT NULL) DEFERRABLE INITIALLY IMMEDIATE;
        -- People only: the same owner's two vehicles may hand over on the same day.
        ALTER TABLE app.occupancies
            DROP CONSTRAINT occupancies_customer_lease_period_exclusive,
            ADD CONSTRAINT occupancies_customer_lease_period_exclusive EXCLUDE USING gist (
                lease_id WITH =, customer_id WITH =,
                daterange(move_in_date, move_out_date, '[]') WITH &&
            ) WHERE (vehicle_id IS NULL) DEFERRABLE INITIALLY IMMEDIATE;

        CREATE FUNCTION app.guard_occupancy_vehicle() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.vehicle_id IS NULL THEN
                    NEW.vehicle_id := NULLIF(current_setting('app.occupancy_vehicle_id', true), '')::uuid;
                END IF;
            ELSIF NEW.vehicle_id IS DISTINCT FROM OLD.vehicle_id THEN
                RAISE EXCEPTION 'The vehicle of an Occupancy never changes' USING ERRCODE = '55000';
            ELSIF OLD.vehicle_id IS NOT NULL AND OLD.move_out_date IS NULL AND NEW.move_out_date IS NOT NULL
                AND current_setting('app.occupancy_vehicle_change', true) IS DISTINCT FROM 'on'
                AND EXISTS (SELECT 1 FROM app.leases WHERE id = OLD.lease_id AND status = 'SIGNED')
            THEN
                -- The only vehicle never moves out alone: only Change vehicle ends a vehicle row of
                -- a running Lease; the Move-out page ends it after Termination.
                RAISE EXCEPTION 'The only vehicle never moves out alone'
                    USING ERRCODE = '23514', HINT = 'VEHICLE_ONLY_ONE';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER occupancies_guard_vehicle BEFORE INSERT OR UPDATE ON app.occupancies
            FOR EACH ROW EXECUTE FUNCTION app.guard_occupancy_vehicle();

        CREATE TABLE app.lease_vehicle_changes (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            old_occupancy_id uuid NOT NULL UNIQUE REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            new_occupancy_id uuid NOT NULL UNIQUE REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            old_vehicle_id uuid NOT NULL REFERENCES app.vehicles(id) ON DELETE RESTRICT,
            new_vehicle_id uuid NOT NULL REFERENCES app.vehicles(id) ON DELETE RESTRICT,
            change_date date NOT NULL CHECK (isfinite(change_date)),
            reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            authorization_reference text NOT NULL
                CHECK (authorization_reference = 'reservations.complete'),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            CONSTRAINT lease_vehicle_changes_idempotency_unique
                UNIQUE (property_id, actor_id, idempotency_key)
        );
        CREATE INDEX lease_vehicle_changes_lease_idx
            ON app.lease_vehicle_changes(lease_id, occurred_at, id);
        COMMENT ON TABLE app.lease_vehicle_changes IS
            'Parking Step 4: Change vehicle ended the old vehicle''s row and started the new one the same day; the Lease goes on';
        CREATE TRIGGER lease_vehicle_changes_reject_mutation BEFORE UPDATE OR DELETE
            ON app.lease_vehicle_changes
            FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation();
        CREATE TRIGGER lease_vehicle_changes_reject_truncate BEFORE TRUNCATE
            ON app.lease_vehicle_changes
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate();

        -- The vehicle checks shared by the move-in and Change vehicle. Raises with a HINT the
        -- API turns into a coded refusal.
        CREATE FUNCTION app.check_lease_vehicle(p_lease app.leases, p_vehicle app.vehicles) RETURNS void
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE v_unit_type text;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.lease_signers AS signer
                WHERE signer.lease_id = p_lease.id AND signer.customer_id = p_vehicle.customer_id)
            THEN RAISE EXCEPTION 'The vehicle belongs to nobody on this Lease'
                USING ERRCODE = '23514', HINT = 'VEHICLE_NOT_OF_LEASE'; END IF;
            SELECT unit_type INTO STRICT v_unit_type FROM app.units WHERE id = p_lease.unit_id;
            IF NOT app.vehicle_type_allowed(p_vehicle.vehicle_type, v_unit_type)
            THEN RAISE EXCEPTION 'This vehicle type cannot park in this Parking Type'
                USING ERRCODE = '23514', HINT = 'VEHICLE_TYPE'; END IF;
            IF EXISTS (SELECT 1 FROM app.occupancies AS occupancy
                WHERE occupancy.vehicle_id = p_vehicle.id AND occupancy.move_out_date IS NULL)
            THEN RAISE EXCEPTION 'This vehicle is parked under another Lease'
                USING ERRCODE = '23514', HINT = 'VEHICLE_PARKED'; END IF;
        END $$;

        CREATE FUNCTION app.record_lease_vehicle_move_in(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text, p_event_id uuid,
            p_lease_id uuid, p_expected_lease_version integer, p_actual_move_in_date date,
            p_occupancy_id uuid, p_vehicle_id uuid, p_reason text, p_authorization_reference text,
            p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_lease app.leases%ROWTYPE; v_vehicle app.vehicles%ROWTYPE; v_result jsonb;
        BEGIN
            IF p_vehicle_id IS NULL OR p_occupancy_id IS NULL OR p_lease_id IS NULL OR p_property_id IS NULL
            THEN RAISE EXCEPTION 'Vehicle move-in evidence is invalid' USING ERRCODE = '22023'; END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            SELECT * INTO v_vehicle FROM app.vehicles WHERE id = p_vehicle_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Vehicle was not found' USING ERRCODE = 'P0002'; END IF;
            -- A replay of the same move-in is answered again by Property Rental's function;
            -- the checks below only run for a move-in that is not recorded yet.
            IF NOT EXISTS (SELECT 1 FROM app.lease_move_ins AS event
                WHERE event.property_id = p_property_id AND event.actor_id = p_actor_id
                  AND event.idempotency_key = p_idempotency_key)
            THEN
                -- A stale version is a conflict (the screen reloads), never a vehicle refusal.
                IF v_lease.version <> p_expected_lease_version THEN
                    RAISE EXCEPTION 'Move-in version is stale' USING ERRCODE = '40001'; END IF;
                PERFORM app.check_lease_vehicle(v_lease, v_vehicle);
                IF EXISTS (SELECT 1 FROM app.occupancies AS occupancy JOIN app.leases AS lease
                    ON lease.id = occupancy.lease_id
                    WHERE lease.unit_id = v_lease.unit_id AND occupancy.move_out_date IS NULL)
                THEN RAISE EXCEPTION 'A vehicle is already moved in on this Parking'
                    USING ERRCODE = '23514', HINT = 'VEHICLE_SECOND'; END IF;
            END IF;
            -- Transaction-local: an error ends the transaction and the setting with it.
            PERFORM set_config('app.occupancy_vehicle_id', p_vehicle_id::text, true);
            v_result := app.record_signed_lease_move_in(p_property_id, p_idempotency_key,
                p_request_digest, p_event_id, p_lease_id, p_expected_lease_version,
                p_actual_move_in_date,
                jsonb_build_array(jsonb_build_object('occupancy_id', p_occupancy_id,
                    'customer_id', v_vehicle.customer_id)),
                p_reason, p_authorization_reference, p_actor_id);
            PERFORM set_config('app.occupancy_vehicle_id', '', true);
            RETURN v_result;
        END $$;

        CREATE FUNCTION app.change_lease_vehicle(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text, p_event_id uuid,
            p_lease_id uuid, p_expected_lease_version integer, p_occupancy_id uuid, p_vehicle_id uuid,
            p_change_date date, p_reason text, p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior app.lease_vehicle_changes%ROWTYPE; v_lease app.leases%ROWTYPE;
            v_old app.occupancies%ROWTYPE; v_vehicle app.vehicles%ROWTYPE; v_business_date date;
            v_result jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_idempotency_key IS NULL OR p_event_id IS NULL
                OR p_lease_id IS NULL OR p_occupancy_id IS NULL OR p_vehicle_id IS NULL OR p_actor_id IS NULL
                OR p_change_date IS NULL OR NOT isfinite(p_change_date)
                OR p_expected_lease_version IS NULL OR p_expected_lease_version < 1
                OR p_idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_event_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_occupancy_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference IS DISTINCT FROM 'reservations.complete'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR length(p_reason) > 500
            THEN RAISE EXCEPTION 'Vehicle change evidence is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || '|' || p_actor_id::text || '|lease-vehicle-change|'
                    || p_idempotency_key::text, 0));
            SELECT * INTO v_prior FROM app.lease_vehicle_changes AS change
            WHERE change.property_id = p_property_id AND change.actor_id = p_actor_id
              AND change.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_prior.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Vehicle change idempotency key was reused' USING ERRCODE = '23505';
                END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            PERFORM 1 FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_lease_version THEN
                RAISE EXCEPTION 'Vehicle change version is stale' USING ERRCODE = '40001'; END IF;
            SELECT * INTO v_vehicle FROM app.vehicles WHERE id = p_vehicle_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Vehicle was not found' USING ERRCODE = 'P0002'; END IF;
            SELECT occupancy.* INTO v_old FROM app.occupancies AS occupancy
            WHERE occupancy.lease_id = v_lease.id AND occupancy.move_out_date IS NULL
              AND occupancy.vehicle_id IS NOT NULL FOR UPDATE;
            IF NOT FOUND OR v_lease.status <> 'SIGNED' THEN
                RAISE EXCEPTION 'No vehicle is moved in on this Lease'
                    USING ERRCODE = '23514', HINT = 'VEHICLE_NONE_IN'; END IF;
            IF v_old.vehicle_id = p_vehicle_id THEN
                RAISE EXCEPTION 'This vehicle is the one already moved in'
                    USING ERRCODE = '23514', HINT = 'VEHICLE_SAME'; END IF;
            PERFORM app.check_lease_vehicle(v_lease, v_vehicle);
            SELECT timezone(property.timezone_name, statement_timestamp())::date INTO STRICT v_business_date
            FROM app.properties AS property WHERE property.id = p_property_id;
            IF p_change_date < v_old.move_in_date OR p_change_date > v_business_date
                OR p_change_date > v_lease.end_date
            THEN RAISE EXCEPTION 'Vehicle change date is not allowed'
                USING ERRCODE = '23514', HINT = 'VEHICLE_DATE'; END IF;
            PERFORM set_config('app.occupancy_vehicle_change', 'on', true);
            UPDATE app.occupancies SET move_out_date = p_change_date, version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = v_old.id;
            PERFORM set_config('app.occupancy_vehicle_change', '', true);
            INSERT INTO app.occupancies(id, lease_id, customer_id, move_in_date, vehicle_id, created_by, updated_by)
            VALUES (p_occupancy_id, v_lease.id, v_vehicle.customer_id, p_change_date, p_vehicle_id,
                p_actor_id, p_actor_id);
            UPDATE app.leases SET version = version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id WHERE id = v_lease.id;
            v_result := jsonb_build_object('event_id', p_event_id, 'property_id', p_property_id,
                'lease_id', v_lease.id, 'lease_version', v_lease.version + 1,
                'old_occupancy_id', v_old.id, 'old_vehicle_id', v_old.vehicle_id,
                'new_occupancy_id', p_occupancy_id, 'new_vehicle_id', p_vehicle_id,
                'customer_id', v_vehicle.customer_id, 'change_date', p_change_date);
            INSERT INTO app.lease_vehicle_changes(id, property_id, actor_id, idempotency_key,
                request_digest, lease_id, old_occupancy_id, new_occupancy_id, old_vehicle_id,
                new_vehicle_id, change_date, reason, authorization_reference, result_snapshot, occurred_at)
            VALUES (p_event_id, p_property_id, p_actor_id, p_idempotency_key, p_request_digest,
                v_lease.id, v_old.id, p_occupancy_id, v_old.vehicle_id, p_vehicle_id, p_change_date,
                p_reason, p_authorization_reference, v_result, statement_timestamp());
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;
    """)
    for table in ("vehicles", "lease_vehicle_changes"):
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime")
    for function in (CREATE, UPDATE, MOVE_IN, CHANGE):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Vehicles migration is forward-only")
