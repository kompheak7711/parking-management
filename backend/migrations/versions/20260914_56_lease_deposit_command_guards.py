"""Serialize Lease Deposit commands and preserve financial/audit admission."""

from alembic import op

revision = "20260914_56"
down_revision = "20260914_55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION app.record_lease_deposit_disposition(
            p_property_id uuid, p_actor_id uuid, p_idempotency_key uuid,
            p_request_digest text, p_disposition_id uuid, p_deposit_id uuid,
            p_governing_lease_id uuid, p_amount_usd_cents bigint,
            p_effective_date date, p_reason text, p_authorization_reference text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE v_result jsonb;
        BEGIN
            IF p_property_id IS NULL OR p_actor_id IS NULL OR p_idempotency_key IS NULL
                OR p_request_digest IS NULL OR p_request_digest !~ '^[0-9a-f]{64}$'
                OR p_authorization_reference IS DISTINCT FROM 'deposits.dispose'
            THEN RAISE EXCEPTION 'Deposit command identity or authorization is invalid'
                USING ERRCODE='22023'; END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                p_property_id::text || ':' || p_actor_id::text ||
                '-deposit.disposition.record-' || p_idempotency_key::text, 0));
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Lease Deposit disposition actor is not active'
                USING ERRCODE='42501'; END IF;
            v_result := app.replay_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.record',p_idempotency_key,p_request_digest);
            IF v_result IS NOT NULL THEN RETURN v_result; END IF;
            IF p_amount_usd_cents IS NULL OR p_amount_usd_cents <= 0
                OR p_effective_date IS NULL OR COALESCE(btrim(p_reason),'') = ''
            THEN RAISE EXCEPTION 'Deposit disposition evidence is invalid'
                USING ERRCODE='22023'; END IF;
            PERFORM 1 FROM app.deposits WHERE id=p_deposit_id FOR UPDATE;
            IF NOT FOUND OR app.deposit_property_id(p_deposit_id) IS DISTINCT FROM p_property_id
            THEN RAISE EXCEPTION 'Deposit was not found' USING ERRCODE='P0002'; END IF;
            IF NOT EXISTS(SELECT 1 FROM app.user_accounts account
                JOIN app.actor_identities identity ON identity.actor_id=account.actor_id
                WHERE account.actor_id=p_actor_id AND account.lifecycle_state='active'
                    AND identity.identity_kind='HUMAN')
            THEN RAISE EXCEPTION 'Lease Deposit disposition actor is not active'
                USING ERRCODE='42501'; END IF;
            INSERT INTO app.deposit_dispositions(
                id,deposit_id,amount_usd_cents,governing_reservation_id,
                source_lifecycle_event_id,governing_lease_id,effective_date,reason,
                occurred_at,actor_id,authorization_reference
            ) VALUES (
                p_disposition_id,p_deposit_id,p_amount_usd_cents,NULL,NULL,
                p_governing_lease_id,p_effective_date,btrim(p_reason),
                statement_timestamp(),p_actor_id,p_authorization_reference
            );
            v_result := app.deposit_snapshot(p_deposit_id)
                || jsonb_build_object('deposit_disposition_id',p_disposition_id);
            PERFORM app.record_deposit_audit(
                p_disposition_id,'deposit.disposition.recorded','deposit_disposition',
                p_disposition_id,p_deposit_id,p_reason,p_authorization_reference,
                p_actor_id,p_idempotency_key,v_result);
            PERFORM app.record_deposit_command(p_property_id,p_actor_id,
                'deposit.disposition.record',p_idempotency_key,p_request_digest,
                p_deposit_id,p_reason,p_authorization_reference,v_result);
            RETURN v_result;
        END;
        $$;
    """)


def downgrade() -> None:
    raise RuntimeError("forward-only financial command migration; preserve recorded history")
