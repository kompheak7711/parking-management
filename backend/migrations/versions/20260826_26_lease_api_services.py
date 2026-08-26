"""Add the bounded API-facing Lease draft update command."""

from alembic import op

revision = "20260826_26"
down_revision = "20260826_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Expose one idempotent optimistic command for mutable draft terms."""
    op.execute("ALTER TABLE app.lease_commands DROP CONSTRAINT lease_commands_action_check")
    op.execute(
        """
        ALTER TABLE app.lease_commands ADD CONSTRAINT lease_commands_action_check
        CHECK (action IN (
            'lease.draft', 'lease.draft.update', 'lease.signer.add',
            'lease.signer.sign', 'lease.signer.remove', 'lease.sign',
            'lease.cancel', 'lease.terminate'
        ))
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.validate_lease_service_term()
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
            WHERE approval.id = NEW.service_approval_period_id FOR SHARE;
            IF v_status NOT IN ('DRAFTED', 'SIGNED', 'TERMINATED')
                OR v_start IS NULL OR v_end IS NULL
                OR v_unit_property <> v_service_property
                OR v_approval_service <> NEW.property_service_id
                OR NEW.applicable_from < v_start
                OR COALESCE(NEW.applicable_through, v_end) > v_end
                OR NEW.applicable_from < v_approval_from
                OR (v_approval_through IS NOT NULL
                    AND COALESCE(NEW.applicable_through, v_end) > v_approval_through)
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
        CREATE FUNCTION app.create_lease_draft_with_terms(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_unit_id uuid,
            p_primary_tenant_id uuid, p_primary_signer_id uuid,
            p_start_date date, p_end_date date, p_monthly_rent_usd_cents bigint,
            p_predecessor_lease_id uuid, p_additional_signers jsonb,
            p_planned_occupants jsonb, p_service_terms jsonb, p_pet_term jsonb,
            p_security_deposit_id uuid, p_reason text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_result jsonb;
            v_item jsonb;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.draft', p_idempotency_key,
                p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_event_id IS NULL OR p_lease_id IS NULL OR p_unit_id IS NULL
                OR p_primary_tenant_id IS NULL OR p_primary_signer_id IS NULL
                OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
                OR (p_start_date IS NULL) <> (p_end_date IS NULL)
                OR (p_start_date IS NOT NULL AND p_end_date <= p_start_date)
                OR (p_monthly_rent_usd_cents IS NOT NULL
                    AND p_monthly_rent_usd_cents <= 0)
                OR jsonb_typeof(p_additional_signers) <> 'array'
                OR jsonb_array_length(p_additional_signers) > 19
                OR jsonb_typeof(p_planned_occupants) <> 'array'
                OR jsonb_array_length(p_planned_occupants) > 20
                OR jsonb_typeof(p_service_terms) <> 'array'
                OR jsonb_array_length(p_service_terms) > 20
                OR (p_pet_term IS NOT NULL AND jsonb_typeof(p_pet_term) <> 'object')
            THEN
                RAISE EXCEPTION 'Lease draft source evidence is invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM 1 FROM app.units
            WHERE id = p_unit_id AND property_id = p_property_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit was not found in Property scope' USING ERRCODE = 'P0002';
            END IF;
            IF p_security_deposit_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.deposits AS deposit
                JOIN app.reservations AS reservation ON reservation.id = deposit.reservation_id
                JOIN app.units AS unit ON unit.id = reservation.unit_id
                WHERE deposit.id = p_security_deposit_id
                  AND deposit.deposit_type = 'SECURITY'
                  AND deposit.customer_id = p_primary_tenant_id
                  AND unit.property_id = p_property_id
                  AND reservation.unit_id = p_unit_id
                  AND deposit.lease_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Security Deposit source was not found in Property scope'
                    USING ERRCODE = 'P0002';
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
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_additional_signers)
            LOOP
                INSERT INTO app.lease_signers(id, lease_id, customer_id, added_by)
                VALUES (
                    (v_item->>'signer_id')::uuid, p_lease_id,
                    (v_item->>'customer_id')::uuid, p_actor_id
                );
            END LOOP;
            IF EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(p_planned_occupants) AS item(value)
                LEFT JOIN app.customers AS customer ON customer.id = item.value::uuid
                WHERE customer.id IS NULL
            ) THEN
                RAISE EXCEPTION 'Planned Occupant was not found in Property scope'
                    USING ERRCODE = 'P0002';
            END IF;
            FOR v_item IN SELECT value FROM jsonb_array_elements(p_service_terms)
            LOOP
                INSERT INTO app.lease_service_terms(
                    id, lease_id, property_service_id, applicable_from,
                    applicable_through, service_approval_period_id, terms_reference,
                    recorded_at, recorded_by
                ) VALUES (
                    (v_item->>'term_id')::uuid, p_lease_id,
                    (v_item->>'property_service_id')::uuid,
                    (v_item->>'applicable_from')::date,
                    NULLIF(v_item->>'applicable_through', '')::date,
                    (v_item->>'service_approval_period_id')::uuid,
                    btrim(v_item->>'terms_reference'), statement_timestamp(), p_actor_id
                );
            END LOOP;
            IF p_pet_term IS NOT NULL THEN
                INSERT INTO app.lease_pet_approvals(
                    id, lease_id, approved_date, deposit_required_by_signed_terms,
                    pet_description, approved_at, approved_by
                ) VALUES (
                    (p_pet_term->>'approval_id')::uuid, p_lease_id,
                    (p_pet_term->>'approved_date')::date,
                    (p_pet_term->>'deposit_required_by_signed_terms')::boolean,
                    NULLIF(btrim(p_pet_term->>'pet_description'), ''),
                    statement_timestamp(), p_actor_id
                );
            END IF;
            SET CONSTRAINTS app.lease_service_terms_validate IMMEDIATE;
            v_result := app.lease_snapshot(p_lease_id) || jsonb_build_object(
                'planned_occupant_customer_ids', p_planned_occupants,
                'security_deposit_id', p_security_deposit_id,
                'service_term_ids', (
                    SELECT COALESCE(jsonb_agg(value->>'term_id'), '[]'::jsonb)
                    FROM jsonb_array_elements(p_service_terms) AS source(value)
                ),
                'pet_term_id', CASE WHEN p_pet_term IS NULL
                    THEN NULL ELSE p_pet_term->>'approval_id' END
            );
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.draft',
                p_idempotency_key, p_request_digest, p_lease_id, 'leases.draft',
                p_reason, NULL, NULL, v_result, statement_timestamp()
            );
            RETURN v_result;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.update_lease_draft(
            p_property_id uuid, p_idempotency_key uuid, p_request_digest text,
            p_event_id uuid, p_lease_id uuid, p_expected_version integer,
            p_start_date date, p_end_date date, p_monthly_rent_usd_cents bigint,
            p_reason text, p_authorization_reference text, p_actor_id uuid
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_replay jsonb;
            v_before jsonb;
            v_result jsonb;
            v_status text;
            v_version integer;
        BEGIN
            v_replay := app.replay_lease_command(
                p_property_id, p_actor_id, 'lease.draft.update',
                p_idempotency_key, p_request_digest
            );
            IF v_replay IS NOT NULL THEN RETURN v_replay; END IF;
            IF p_authorization_reference <> 'leases.draft'
                OR p_event_id IS NULL OR p_idempotency_key IS NULL
                OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_expected_version < 1
                OR (p_start_date IS NULL) <> (p_end_date IS NULL)
                OR (p_start_date IS NOT NULL AND p_end_date <= p_start_date)
                OR (p_monthly_rent_usd_cents IS NOT NULL
                    AND p_monthly_rent_usd_cents <= 0)
                OR p_reason IS NULL OR p_reason = '' OR p_reason <> btrim(p_reason)
            THEN
                RAISE EXCEPTION 'Lease draft update evidence is invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT lease.status, lease.version INTO v_status, v_version
            FROM app.leases AS lease
            JOIN app.units AS unit ON unit.id = lease.unit_id
            WHERE lease.id = p_lease_id AND unit.property_id = p_property_id
            FOR UPDATE OF lease;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Lease was not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_version <> p_expected_version THEN
                RAISE EXCEPTION 'Lease version is stale' USING ERRCODE = '40001';
            END IF;
            IF v_status <> 'DRAFTED' THEN
                RAISE EXCEPTION 'Only a drafted Lease may be updated'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1 FROM app.lease_service_terms AS term
                JOIN app.property_service_approval_periods AS approval
                  ON approval.id = term.service_approval_period_id
                WHERE term.lease_id = p_lease_id
                  AND (
                    p_start_date IS NULL OR p_end_date IS NULL
                    OR term.applicable_from < p_start_date
                    OR COALESCE(term.applicable_through, p_end_date) > p_end_date
                    OR term.applicable_from < approval.effective_from
                    OR (approval.effective_through IS NOT NULL
                        AND COALESCE(term.applicable_through, p_end_date)
                            > approval.effective_through)
                  )
            ) THEN
                RAISE EXCEPTION 'Lease draft update would invalidate approved Service terms'
                    USING ERRCODE = '23514';
            END IF;
            v_before := app.lease_snapshot(p_lease_id);
            UPDATE app.leases
            SET start_date = p_start_date,
                end_date = p_end_date,
                monthly_rent_usd_cents = p_monthly_rent_usd_cents,
                version = version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE id = p_lease_id;
            SET CONSTRAINTS app.leases_validate_relationships IMMEDIATE;
            v_result := app.lease_snapshot(p_lease_id);
            PERFORM app.record_lease_command(
                p_event_id, p_property_id, p_actor_id, 'lease.draft.update',
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
        CREATE FUNCTION app.enforce_lease_signer_limit()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM app.leases WHERE id = NEW.lease_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Lease was not found' USING ERRCODE = '23503';
            END IF;
            IF (SELECT count(*) FROM app.lease_signers WHERE lease_id = NEW.lease_id) >= 20
            THEN
                RAISE EXCEPTION 'A Lease may have at most twenty Signers'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER lease_signers_enforce_limit
        BEFORE INSERT ON app.lease_signers
        FOR EACH ROW EXECUTE FUNCTION app.enforce_lease_signer_limit();
        """
    )
    signature = (
        "app.update_lease_draft(uuid,uuid,text,uuid,uuid,integer,date,date,bigint,text,text,uuid)"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, prm_runtime, prm_bootstrap")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")
    draft_signature = (
        "app.create_lease_draft_with_terms(uuid,uuid,text,uuid,uuid,uuid,uuid,uuid,"
        "date,date,bigint,uuid,jsonb,jsonb,jsonb,jsonb,uuid,text,uuid)"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {draft_signature} FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {draft_signature} TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback of Lease command history."""
    raise RuntimeError("Lease API service migration is forward-only")
