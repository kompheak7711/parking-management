# ruff: noqa: E501
"""Complete the Reservation and occupy the Unit at Lease signing; move-in only starts Occupancy."""

from alembic import op
from sqlalchemy import text

revision = "20261005_69"
down_revision = "20261004_68"
branch_labels = None
depends_on = None

SIGNING_FLAG = "COALESCE(current_setting('app.lease_signing_lease_id', true), '')"

PATCHES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "app.protect_reservation_history()",
        (
            (
                "OR COALESCE(current_setting('app.move_in_event_id', true), '') = ''",
                "OR (COALESCE(current_setting('app.move_in_event_id', true), '') = ''\n"
                f"                        AND {SIGNING_FLAG} <> NEW.resulting_lease_id::text)",
            ),
        ),
    ),
    (
        "app.assert_reservation_move_in_event()",
        (
            (
                "IF OLD.status = 'ACTIVE' AND NEW.status = 'COMPLETED' AND NOT EXISTS (",
                "IF OLD.status = 'ACTIVE' AND NEW.status = 'COMPLETED' AND NOT EXISTS (\n"
                "                SELECT 1 FROM app.lease_signing_outcomes AS outcome\n"
                "                WHERE outcome.reservation_id = NEW.id\n"
                "                  AND outcome.lease_id = NEW.resulting_lease_id\n"
                "            ) AND NOT EXISTS (",
            ),
        ),
    ),
    (
        "app.reject_deposit_history_loss()",
        (
            (
                "AND current_setting('app.move_in_event_id', true) <> ''",
                "AND (current_setting('app.move_in_event_id', true) <> ''\n"
                f"                    OR {SIGNING_FLAG} = NEW.lease_id::text)",
            ),
        ),
    ),
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"Lease signing source contract changed: {signature}")
        definition = definition.replace(before, after)
    # CREATE OR REPLACE keeps the function identity, owner and privileges.
    op.execute(definition)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.lease_signing_outcomes (
            lease_id uuid PRIMARY KEY REFERENCES app.leases(id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            reservation_id uuid UNIQUE REFERENCES app.reservations(id) ON DELETE RESTRICT,
            deposit_id uuid UNIQUE REFERENCES app.deposits(id) ON DELETE RESTRICT,
            previous_unit_status text NOT NULL,
            resulting_unit_status text NOT NULL CHECK (resulting_unit_status = 'OCCUPIED'),
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            audit_event_id uuid NOT NULL UNIQUE REFERENCES app.audit_events(id) ON DELETE RESTRICT,
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            CONSTRAINT lease_signing_outcomes_deposit_needs_reservation
                CHECK (deposit_id IS NULL OR reservation_id IS NOT NULL)
        );
        CREATE TABLE app.lease_move_ins (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            idempotency_key uuid NOT NULL CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'),
            request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL UNIQUE REFERENCES app.lease_signing_outcomes(lease_id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            actual_move_in_date date NOT NULL CHECK (isfinite(actual_move_in_date)),
            reason text NOT NULL CHECK (reason = btrim(reason) AND length(reason) BETWEEN 1 AND 500),
            authorization_reference text NOT NULL CHECK (authorization_reference = 'reservations.complete'),
            result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
            occurred_at timestamptz NOT NULL CHECK (isfinite(occurred_at)),
            CONSTRAINT lease_move_ins_idempotency_unique UNIQUE (property_id, actor_id, idempotency_key)
        );
        CREATE TABLE app.lease_move_in_occupancy_links (
            lease_move_in_id uuid NOT NULL REFERENCES app.lease_move_ins(id) ON DELETE RESTRICT,
            occupancy_id uuid NOT NULL UNIQUE REFERENCES app.occupancies(id) ON DELETE RESTRICT,
            PRIMARY KEY (lease_move_in_id, occupancy_id)
        );

        -- DL-064/DL-066: at signing the Reservation (if any) is COMPLETED, its holding deposit
        -- continues as the Security Deposit, and the Unit becomes OCCUPIED. Physical move-in
        -- later only starts the Occupancy.
        CREATE FUNCTION app.sign_lease_with_reservation(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_expected_version integer,
            p_signed_at timestamptz, p_reason text, p_actor_id uuid, p_reservation_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_replay jsonb; v_result jsonb; v_lease app.leases%ROWTYPE; v_unit app.units%ROWTYPE;
            v_reservation app.reservations%ROWTYPE; v_deposit_id uuid; v_audit uuid; v_now timestamptz;
            v_business_date date;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.sign', p_idempotency_key, p_request_digest);
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            v_result := app.sign_lease(p_property_id, p_idempotency_key, p_request_digest, p_event_id,
                p_lease_id, p_expected_version, p_signed_at, p_reason, p_actor_id);
            SELECT * INTO STRICT v_lease FROM app.leases WHERE id = p_lease_id;
            SELECT * INTO STRICT v_unit FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            v_now := statement_timestamp();
            SELECT timezone(property.timezone_name, v_now)::date INTO STRICT v_business_date
            FROM app.properties AS property WHERE property.id = p_property_id;
            PERFORM set_config('app.lease_signing_lease_id', p_lease_id::text, true);
            IF p_reservation_id IS NOT NULL THEN
                SELECT reservation.* INTO v_reservation FROM app.reservations AS reservation
                WHERE reservation.id = p_reservation_id FOR UPDATE;
                IF NOT FOUND THEN RAISE EXCEPTION 'Reservation was not found' USING ERRCODE = 'P0002'; END IF;
                IF v_reservation.status <> 'ACTIVE' OR v_reservation.unit_id <> v_lease.unit_id
                    OR v_reservation.customer_id <> v_lease.primary_tenant_id
                    OR v_business_date > v_reservation.effective_expiration_date
                    OR v_unit.status <> 'RESERVED'
                THEN RAISE EXCEPTION 'Reservation cannot be completed by this signing'
                    USING ERRCODE = '23514'; END IF;
                SELECT deposit.id INTO v_deposit_id FROM app.deposits AS deposit
                WHERE deposit.reservation_id = v_reservation.id AND deposit.deposit_type = 'SECURITY'
                  AND deposit.lease_id IS NULL FOR UPDATE;
                UPDATE app.reservations SET status = 'COMPLETED', resulting_lease_id = v_lease.id,
                    completed_at = v_now, version = version + 1, updated_at = v_now,
                    updated_by = p_actor_id WHERE id = v_reservation.id;
                IF v_deposit_id IS NOT NULL THEN
                    UPDATE app.deposits SET lease_id = v_lease.id, version = version + 1,
                        updated_at = v_now, updated_by = p_actor_id WHERE id = v_deposit_id;
                END IF;
            ELSIF v_unit.status = 'RESERVED' OR v_unit.status = 'OUT_OF_SERVICE'
                OR (v_unit.status = 'OCCUPIED' AND v_lease.predecessor_lease_id IS NULL)
            THEN RAISE EXCEPTION 'Unit cannot be occupied by this signing' USING ERRCODE = '23514';
            END IF;
            IF v_unit.status <> 'OCCUPIED' THEN
                UPDATE app.units SET status = 'OCCUPIED', version = version + 1,
                    updated_at = v_now, updated_by = p_actor_id WHERE id = v_unit.id;
            END IF;
            v_audit := gen_random_uuid();
            INSERT INTO app.audit_events(id,occurred_at,business_date,actor_id,action,entity_type,entity_id,
                reason,authorization_reference,property_id,previous_state,resulting_state,correlation_id,
                source,outcome,authorization_evidence,customer_id,lease_id,unit_id)
            VALUES(v_audit,v_now,v_business_date,p_actor_id,'lease.signing_outcome.recorded',
                'lease_signing_outcome',v_lease.id,p_reason,'leases.sign',p_property_id,
                jsonb_build_object('unit_status',v_unit.status,'reservation_id',p_reservation_id),
                jsonb_build_object('unit_status','OCCUPIED','reservation_status',
                    CASE WHEN p_reservation_id IS NULL THEN NULL ELSE 'COMPLETED' END,
                    'deposit_id',v_deposit_id),
                p_event_id,'API','SUCCEEDED',jsonb_build_object('capability','leases.sign'),
                v_lease.primary_tenant_id,v_lease.id,v_unit.id);
            INSERT INTO app.lease_signing_outcomes(lease_id,property_id,unit_id,reservation_id,deposit_id,
                previous_unit_status,resulting_unit_status,actor_id,audit_event_id,occurred_at)
            VALUES(v_lease.id,p_property_id,v_unit.id,p_reservation_id,v_deposit_id,v_unit.status,
                'OCCUPIED',p_actor_id,v_audit,v_now);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;

        -- DL-066: physical move-in of a Lease signed through the new path starts the Occupancy only;
        -- it has no payment gate. Leases signed before migration 69 keep complete_reservation_move_in.
        CREATE FUNCTION app.record_signed_lease_move_in(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text, p_event_id uuid,
            p_lease_id uuid, p_expected_lease_version integer, p_actual_move_in_date date,
            p_occupants jsonb, p_reason text, p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_prior app.lease_move_ins%ROWTYPE; v_lease app.leases%ROWTYPE; v_unit app.units%ROWTYPE;
            v_timezone text; v_business_date date; v_item jsonb; v_occupancy_id uuid; v_customer_id uuid;
            v_occupancy_ids jsonb := '[]'::jsonb; v_result jsonb;
        BEGIN
            IF p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference IS DISTINCT FROM 'reservations.complete'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR p_actual_move_in_date IS NULL OR jsonb_typeof(p_occupants) IS DISTINCT FROM 'array'
                OR jsonb_array_length(p_occupants) NOT BETWEEN 1 AND 20
            THEN RAISE EXCEPTION 'Move-in command evidence is invalid' USING ERRCODE = '22023'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || '|' || p_actor_id::text || '|lease-move-in|' || p_idempotency_key::text, 0));
            SELECT * INTO v_prior FROM app.lease_move_ins AS event
            WHERE event.property_id = p_property_id AND event.actor_id = p_actor_id
              AND event.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_prior.request_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Move-in idempotency key was reused' USING ERRCODE = '23505';
                END IF;
                RETURN v_prior.result_snapshot;
            END IF;
            SELECT lease.* INTO v_lease FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            SELECT * INTO STRICT v_unit FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_lease_version THEN
                RAISE EXCEPTION 'Move-in version is stale' USING ERRCODE = '40001'; END IF;
            SELECT property.timezone_name, timezone(property.timezone_name, statement_timestamp())::date
            INTO STRICT v_timezone, v_business_date FROM app.properties AS property WHERE property.id = p_property_id;
            IF NOT EXISTS (SELECT 1 FROM app.lease_signing_outcomes WHERE lease_id = v_lease.id)
                OR EXISTS (SELECT 1 FROM app.lease_move_ins WHERE lease_id = v_lease.id)
                OR v_lease.status <> 'SIGNED' OR v_unit.status <> 'OCCUPIED'
                OR p_actual_move_in_date < v_lease.start_date OR p_actual_move_in_date > v_lease.end_date
                OR timezone(v_timezone, v_lease.signed_at)::date > p_actual_move_in_date
                OR p_actual_move_in_date > v_business_date
            THEN RAISE EXCEPTION 'Move-in lifecycle prerequisites are not satisfied' USING ERRCODE = '23514'; END IF;
            IF EXISTS (
                SELECT 1 FROM app.occupancies AS occupancy JOIN app.leases AS lease ON lease.id = occupancy.lease_id
                WHERE lease.unit_id = v_unit.id AND occupancy.move_out_date IS NULL
            ) THEN RAISE EXCEPTION 'Unit has an open Occupancy' USING ERRCODE = '23P01'; END IF;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_occupants) AS element(value) LOOP
                IF jsonb_typeof(v_item) <> 'object' OR NOT (v_item ? 'occupancy_id' AND v_item ? 'customer_id')
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
                    OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_occupants) AS duplicate(value)
                        WHERE duplicate.value->>'customer_id' = v_customer_id::text
                        GROUP BY duplicate.value->>'customer_id' HAVING count(*) > 1)
                THEN RAISE EXCEPTION 'Occupant identity is invalid or duplicated' USING ERRCODE = '23514'; END IF;
                INSERT INTO app.occupancies(id, lease_id, customer_id, move_in_date, created_by, updated_by)
                VALUES (v_occupancy_id, v_lease.id, v_customer_id, p_actual_move_in_date, p_actor_id, p_actor_id);
                v_occupancy_ids := v_occupancy_ids || jsonb_build_array(v_occupancy_id);
            END LOOP;
            UPDATE app.leases SET version = version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id WHERE id = v_lease.id;
            v_result := jsonb_build_object('event_id', p_event_id, 'property_id', p_property_id,
                'lease_id', v_lease.id, 'lease_version', v_lease.version + 1, 'unit_id', v_unit.id,
                'actual_move_in_date', p_actual_move_in_date, 'occupancy_ids', v_occupancy_ids);
            INSERT INTO app.lease_move_ins(id, property_id, actor_id, idempotency_key, request_digest, lease_id,
                unit_id, actual_move_in_date, reason, authorization_reference, result_snapshot, occurred_at)
            VALUES (p_event_id, p_property_id, p_actor_id, p_idempotency_key, p_request_digest, v_lease.id,
                v_unit.id, p_actual_move_in_date, p_reason, p_authorization_reference, v_result, statement_timestamp());
            INSERT INTO app.lease_move_in_occupancy_links(lease_move_in_id, occupancy_id)
            SELECT p_event_id, (value #>> '{}')::uuid FROM jsonb_array_elements(v_occupancy_ids);
            SET CONSTRAINTS ALL IMMEDIATE;
            RETURN v_result;
        END $$;
    """)
    for signature, replacements in PATCHES:
        _patch(signature, replacements)
    for table in ("lease_signing_outcomes", "lease_move_ins", "lease_move_in_occupancy_links"):
        op.execute(
            f"CREATE TRIGGER {table}_reject_mutation BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_storage_truncate()"
        )
        op.execute(
            f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO prm_runtime")
    sign = "app.sign_lease_with_reservation(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid,uuid)"
    move_in = "app.record_signed_lease_move_in(uuid,uuid,text,uuid,uuid,integer,date,jsonb,text,text,uuid)"
    for function in (sign, move_in):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_financial, prm_bootstrap"
        )
    op.execute(f"GRANT EXECUTE ON FUNCTION {sign}, {move_in} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("Lease signing outcome migration is forward-only")
