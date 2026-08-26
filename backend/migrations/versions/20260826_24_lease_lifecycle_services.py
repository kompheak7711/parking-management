"""Add protected Lease lifecycle command services."""

from alembic import op

revision = "20260826_24"
down_revision = "20260826_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the bounded V1-034 lifecycle and authorization boundary."""
    op.execute(
        "ALTER FUNCTION app.validate_lease_relationships() SECURITY DEFINER"
    )
    op.execute(
        "ALTER FUNCTION app.validate_lease_relationships() SET search_path = pg_catalog"
    )
    op.execute(
        """
        CREATE TABLE app.lease_commands (
            event_id uuid PRIMARY KEY
                CHECK (event_id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            actor_id uuid NOT NULL REFERENCES app.user_accounts(actor_id) ON DELETE RESTRICT,
            action text NOT NULL CHECK (action IN (
                'lease.draft', 'lease.signer.add', 'lease.signer.sign',
                'lease.signer.remove', 'lease.sign', 'lease.cancel', 'lease.terminate'
            )),
            idempotency_key uuid NOT NULL
                CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'::uuid),
            request_digest text NOT NULL
                CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            lease_id uuid NOT NULL REFERENCES app.leases(id) ON DELETE RESTRICT,
            authorization_reference text NOT NULL CHECK (
                length(btrim(authorization_reference)) > 0
                AND authorization_reference = btrim(authorization_reference)
            ),
            reason text NOT NULL CHECK (
                length(btrim(reason)) > 0 AND reason = btrim(reason)
            ),
            governing_event_reference text CHECK (
                governing_event_reference IS NULL OR (
                    length(btrim(governing_event_reference)) > 0
                    AND governing_event_reference = btrim(governing_event_reference)
                )
            ),
            previous_snapshot jsonb,
            result_snapshot jsonb NOT NULL,
            occurred_at timestamptz NOT NULL,
            CONSTRAINT lease_commands_idempotency_unique
                UNIQUE (property_id, actor_id, action, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX lease_commands_lease_history_idx "
        "ON app.lease_commands(lease_id, occurred_at, event_id)"
    )
    op.execute(
        """
        CREATE FUNCTION app.lease_snapshot(p_lease_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT jsonb_build_object(
                'lease_id', lease.id,
                'property_id', unit.property_id,
                'unit_id', lease.unit_id,
                'primary_tenant_id', lease.primary_tenant_id,
                'status', lease.status,
                'start_date', lease.start_date,
                'end_date', lease.end_date,
                'monthly_rent_usd_cents', lease.monthly_rent_usd_cents,
                'predecessor_lease_id', lease.predecessor_lease_id,
                'signed_at', lease.signed_at,
                'terminated_at', lease.terminated_at,
                'actual_termination_date', lease.actual_termination_date,
                'version', lease.version,
                'signer_count', (
                    SELECT count(*) FROM app.lease_signers AS signer
                    WHERE signer.lease_id = lease.id
                ),
                'signed_signer_count', (
                    SELECT count(*) FROM app.lease_signers AS signer
                    WHERE signer.lease_id = lease.id AND signer.signed_at IS NOT NULL
                ),
                'occupant_count', (
                    SELECT count(*) FROM app.occupancies AS occupancy
                    WHERE occupancy.lease_id = lease.id AND occupancy.move_out_date IS NULL
                )
            )
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.replay_lease_command(
            p_property_id uuid, p_actor_id uuid, p_action text,
            p_idempotency_key uuid, p_request_digest text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_digest text;
            v_snapshot jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_property_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_actor_id = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
                OR p_request_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Lease command identity is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                p_property_id::text || ':' || p_actor_id::text || ':' || p_action || ':'
                || p_idempotency_key::text, 0
            ));
            SELECT command.request_digest, command.result_snapshot
            INTO v_digest, v_snapshot
            FROM app.lease_commands AS command
            WHERE command.property_id = p_property_id
              AND command.actor_id = p_actor_id
              AND command.action = p_action
              AND command.idempotency_key = p_idempotency_key;
            IF FOUND THEN
                IF v_digest <> p_request_digest THEN
                    RAISE EXCEPTION 'Lease idempotency key was reused'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_snapshot;
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_lease_command(
            p_event_id uuid, p_property_id uuid, p_actor_id uuid, p_action text,
            p_idempotency_key uuid, p_request_digest text, p_lease_id uuid,
            p_authorization_reference text, p_reason text,
            p_governing_event_reference text, p_previous_snapshot jsonb,
            p_result_snapshot jsonb, p_occurred_at timestamptz
        ) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
            INSERT INTO app.lease_commands(
                event_id, property_id, actor_id, action, idempotency_key,
                request_digest, lease_id, authorization_reference, reason,
                governing_event_reference, previous_snapshot, result_snapshot, occurred_at
            ) VALUES (
                p_event_id, p_property_id, p_actor_id, p_action, p_idempotency_key,
                p_request_digest, p_lease_id, p_authorization_reference, p_reason,
                p_governing_event_reference, p_previous_snapshot, p_result_snapshot,
                p_occurred_at
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.create_lease_draft(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_unit_id uuid,
            p_primary_tenant_id uuid, p_primary_signer_id uuid,
            p_start_date date, p_end_date date, p_monthly_rent_usd_cents bigint,
            p_predecessor_lease_id uuid, p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_result jsonb;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.draft', p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_event_id IS NULL OR p_lease_id IS NULL OR p_unit_id IS NULL
                OR p_primary_tenant_id IS NULL OR p_primary_signer_id IS NULL
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR p_reason = ''
                OR (p_start_date IS NULL) <> (p_end_date IS NULL)
                OR (p_start_date IS NOT NULL AND p_end_date <= p_start_date)
                OR (p_monthly_rent_usd_cents IS NOT NULL AND p_monthly_rent_usd_cents <= 0)
            THEN
                RAISE EXCEPTION 'Lease draft input is invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM 1 FROM app.units
            WHERE id = p_unit_id AND property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit was not found in Property scope' USING ERRCODE = 'P0002';
            END IF;
            INSERT INTO app.leases(
                id, unit_id, primary_tenant_id, start_date, end_date,
                monthly_rent_usd_cents, predecessor_lease_id, created_by, updated_by
            ) VALUES (
                p_lease_id, p_unit_id, p_primary_tenant_id, p_start_date, p_end_date,
                p_monthly_rent_usd_cents, p_predecessor_lease_id, p_actor_id, p_actor_id
            );
            INSERT INTO app.lease_signers(id, lease_id, customer_id, added_by)
            VALUES (p_primary_signer_id, p_lease_id, p_primary_tenant_id, p_actor_id);
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.draft', p_idempotency_key,
                p_request_digest, p_lease_id, 'leases.draft', p_reason, NULL, NULL,
                v_result, statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.add_lease_signer(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_signer_id uuid, p_customer_id uuid,
            p_expected_version integer, p_reason text,
            p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_status text;
            v_version integer;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.signer.add',
                p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_authorization_reference <> 'lease_signers.manage'
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR p_reason = ''
            THEN
                RAISE EXCEPTION 'Signer authorization evidence is invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT lease.status, lease.version INTO v_status, v_version
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease accepts signers' USING ERRCODE = '55000';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            INSERT INTO app.lease_signers(id, lease_id, customer_id, added_by)
            VALUES (p_signer_id, p_lease_id, p_customer_id, p_actor_id);
            UPDATE app.leases SET version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_lease_id;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.signer.add',
                p_idempotency_key, p_request_digest, p_lease_id,
                p_authorization_reference, p_reason, NULL, v_before, v_result,
                statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_lease_signature(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_signer_id uuid,
            p_expected_version integer, p_signed_at timestamptz,
            p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_status text;
            v_version integer;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.signer.sign',
                p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_signed_at IS NULL OR p_signed_at > statement_timestamp()
                OR p_reason IS NULL
                OR p_reason <> btrim(p_reason) OR p_reason = ''
            THEN RAISE EXCEPTION 'Signature evidence is invalid' USING ERRCODE = '22023'; END IF;
            SELECT lease.status, lease.version INTO v_status, v_version
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease accepts signatures' USING ERRCODE = '55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.lease_signers
                WHERE id = p_signer_id AND lease_id = p_lease_id AND signed_at IS NULL
                  AND added_at <= p_signed_at
            ) THEN
                RAISE EXCEPTION 'Unsigned Lease signer was not found' USING ERRCODE = '55000';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            PERFORM app.sign_draft_lease_signer(p_signer_id, p_signed_at, p_actor_id);
            UPDATE app.leases SET version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_lease_id;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.signer.sign',
                p_idempotency_key, p_request_digest, p_lease_id, 'leases.sign',
                p_reason, NULL, v_before, v_result, statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.remove_lease_signer(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_signer_id uuid,
            p_expected_version integer, p_reason text,
            p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_status text;
            v_version integer;
            v_primary_tenant_id uuid;
            v_signer_customer_id uuid;
            v_signed_at timestamptz;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.signer.remove',
                p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_authorization_reference <> 'lease_signers.manage'
                OR p_reason IS NULL OR p_reason <> btrim(p_reason) OR p_reason = ''
            THEN
                RAISE EXCEPTION 'Signer authorization evidence is invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT lease.status, lease.version, lease.primary_tenant_id
            INTO v_status, v_version, v_primary_tenant_id
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease accepts signer removal'
                    USING ERRCODE = '55000';
            END IF;
            SELECT customer_id, signed_at INTO v_signer_customer_id, v_signed_at
            FROM app.lease_signers WHERE id = p_signer_id AND lease_id = p_lease_id;
            IF NOT FOUND OR v_signed_at IS NOT NULL
                OR v_signer_customer_id = v_primary_tenant_id
            THEN
                RAISE EXCEPTION 'Only an unsigned non-primary signer may be removed'
                    USING ERRCODE = '55000';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            PERFORM app.remove_draft_lease_signer(p_signer_id, p_actor_id);
            UPDATE app.leases SET version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_lease_id;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.signer.remove',
                p_idempotency_key, p_request_digest, p_lease_id,
                p_authorization_reference, p_reason, NULL, v_before, v_result,
                statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.sign_lease(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_expected_version integer,
            p_signed_at timestamptz, p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_lease app.leases%ROWTYPE;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.sign', p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_signed_at IS NULL OR p_signed_at > statement_timestamp()
                OR p_reason IS NULL
                OR p_reason <> btrim(p_reason) OR p_reason = ''
            THEN RAISE EXCEPTION 'Signing evidence is invalid' USING ERRCODE = '22023'; END IF;
            SELECT lease.* INTO v_lease
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            PERFORM 1 FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_lease.status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease may be signed' USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM app.occupancies AS occupancy
                JOIN app.leases AS occupied_lease ON occupied_lease.id = occupancy.lease_id
                WHERE occupied_lease.unit_id = v_lease.unit_id
                  AND occupancy.move_out_date IS NULL
                  AND (
                      v_lease.predecessor_lease_id IS NULL
                      OR occupancy.lease_id <> v_lease.predecessor_lease_id
                  )
            ) THEN
                RAISE EXCEPTION 'Unit has an open Occupancy' USING ERRCODE = '23P01';
            END IF;
            IF v_lease.start_date IS NULL OR v_lease.end_date IS NULL
                OR v_lease.end_date <= v_lease.start_date
                OR v_lease.monthly_rent_usd_cents IS NULL
            THEN RAISE EXCEPTION 'Lease terms are incomplete' USING ERRCODE = '23514'; END IF;
            IF NOT EXISTS (
                SELECT 1 FROM app.lease_signers
                WHERE lease_id = p_lease_id AND customer_id = v_lease.primary_tenant_id
                  AND signed_at IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM app.lease_signers
                WHERE lease_id = p_lease_id
                  AND (signed_at IS NULL OR signed_at > p_signed_at)
            ) THEN
                RAISE EXCEPTION 'Every Lease signer, including the Primary Tenant, must sign'
                    USING ERRCODE = '23514';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            UPDATE app.leases SET status = 'SIGNED', signed_at = p_signed_at,
                version = version + 1, updated_at = statement_timestamp(),
                updated_by = p_actor_id WHERE id = p_lease_id;
            SET CONSTRAINTS app.leases_signed_period_exclusive IMMEDIATE;
            SET CONSTRAINTS app.leases_validate_relationships IMMEDIATE;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.sign', p_idempotency_key,
                p_request_digest, p_lease_id, 'leases.sign', p_reason, NULL, v_before,
                v_result, p_signed_at
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.cancel_draft_lease(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_expected_version integer,
            p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_status text;
            v_version integer;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.cancel', p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_reason IS NULL OR p_reason <> btrim(p_reason) OR p_reason = '' THEN
                RAISE EXCEPTION 'Cancellation reason is invalid' USING ERRCODE = '22023';
            END IF;
            SELECT lease.status, lease.version INTO v_status, v_version
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            IF v_version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease may be cancelled' USING ERRCODE = '55000';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            UPDATE app.leases SET status = 'CANCELLED', version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_lease_id;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.cancel', p_idempotency_key,
                p_request_digest, p_lease_id, 'leases.draft', p_reason, NULL, v_before,
                v_result, statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.terminate_lease(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_expected_version integer,
            p_actual_termination_date date, p_occurred_at timestamptz,
            p_governing_event_reference text, p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_lease app.leases%ROWTYPE;
            v_business_date date;
            v_occurred_business_date date;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.terminate',
                p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_actual_termination_date IS NULL OR p_occurred_at IS NULL
                OR p_governing_event_reference IS NULL
                OR p_governing_event_reference <> btrim(p_governing_event_reference)
                OR p_governing_event_reference = '' OR p_reason IS NULL
                OR p_reason <> btrim(p_reason) OR p_reason = ''
            THEN RAISE EXCEPTION 'Termination evidence is invalid' USING ERRCODE = '22023'; END IF;
            SELECT lease.* INTO v_lease
            FROM app.leases AS lease JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002'; END IF;
            PERFORM 1 FROM app.units WHERE id = v_lease.unit_id FOR UPDATE;
            IF v_lease.version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_lease.status <> 'SIGNED' THEN
                RAISE EXCEPTION 'Only a signed Lease may be terminated' USING ERRCODE = '55000';
            END IF;
            SELECT timezone(property.timezone_name, statement_timestamp())::date,
                   timezone(property.timezone_name, p_occurred_at)::date
            INTO v_business_date, v_occurred_business_date
            FROM app.properties AS property
            WHERE property.id = p_property_id;
            IF p_actual_termination_date < v_lease.start_date
                OR p_occurred_at < v_lease.signed_at
                OR p_occurred_at > statement_timestamp()
                OR p_actual_termination_date > v_business_date
                OR p_actual_termination_date > v_occurred_business_date
            THEN
                RAISE EXCEPTION 'Termination chronology is invalid' USING ERRCODE = '23514';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            UPDATE app.leases SET status = 'TERMINATED', terminated_at = p_occurred_at,
                actual_termination_date = p_actual_termination_date,
                termination_reason = p_reason, version = version + 1,
                updated_at = statement_timestamp(), updated_by = p_actor_id
            WHERE id = p_lease_id;
            SET CONSTRAINTS app.leases_signed_period_exclusive IMMEDIATE;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.terminate',
                p_idempotency_key, p_request_digest, p_lease_id, 'leases.terminate',
                p_reason, p_governing_event_reference, v_before, v_result, p_occurred_at
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER lease_commands_reject_mutation BEFORE UPDATE OR DELETE "
        "ON app.lease_commands FOR EACH ROW "
        "EXECUTE FUNCTION app.reject_lease_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER lease_commands_reject_truncate BEFORE TRUNCATE "
        "ON app.lease_commands FOR EACH STATEMENT "
        "EXECUTE FUNCTION app.reject_lease_storage_truncate()"
    )
    op.execute("REVOKE ALL ON TABLE app.lease_commands FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute("GRANT SELECT ON TABLE app.lease_commands TO prm_runtime")
    for function in (
        "app.lease_snapshot(uuid)",
        "app.replay_lease_command(uuid,uuid,text,uuid,text)",
        "app.record_lease_command(uuid,uuid,uuid,text,uuid,text,uuid,text,text,text,jsonb,jsonb,timestamptz)",
        "app.create_lease_draft(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,uuid,text,uuid)",
        "app.add_lease_signer(uuid,uuid,text,uuid,uuid,uuid,uuid,integer,text,text,uuid)",
        "app.record_lease_signature(uuid,uuid,text,uuid,uuid,uuid,integer,timestamptz,text,uuid)",
        "app.remove_lease_signer(uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid)",
        "app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)",
        "app.cancel_draft_lease(uuid,uuid,text,uuid,uuid,integer,text,uuid)",
        "app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION app.sign_draft_lease_signer(uuid,timestamptz,uuid) "
        "FROM prm_runtime"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION app.remove_draft_lease_signer(uuid,uuid) FROM prm_runtime"
    )
    for function in (
        "app.create_lease_draft(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,date,date,bigint,uuid,text,uuid)",
        "app.add_lease_signer(uuid,uuid,text,uuid,uuid,uuid,uuid,integer,text,text,uuid)",
        "app.record_lease_signature(uuid,uuid,text,uuid,uuid,uuid,integer,timestamptz,text,uuid)",
        "app.remove_lease_signer(uuid,uuid,text,uuid,uuid,uuid,integer,text,text,uuid)",
        "app.sign_lease(uuid,uuid,text,uuid,uuid,integer,timestamptz,text,uuid)",
        "app.cancel_draft_lease(uuid,uuid,text,uuid,uuid,integer,text,uuid)",
        "app.terminate_lease(uuid,uuid,text,uuid,uuid,integer,date,timestamptz,text,text,uuid)",
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback of Lease command history."""
    raise RuntimeError("Lease lifecycle service migration is forward-only")
