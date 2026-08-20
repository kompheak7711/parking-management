"""Add bounded DB-AUTH-005 account-recovery audit persistence."""

from alembic import op

revision = "20260819_08"
down_revision = "20260819_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create immutable evidence and security-definer-only recovery mutation boundaries."""
    op.execute(
        """
        CREATE TABLE app.account_recovery_audit_events (
            event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            actor_id uuid,
            target_actor_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            correlation_id uuid NOT NULL,
            recovery_mode text NOT NULL
                CHECK (recovery_mode IN ('recovery_code', 'administrative', 'emergency')),
            procedure_identity text,
            reason text NOT NULL CHECK (
                reason IN (
                    'mfa_recovery', 'authorized_account_recovery',
                    'documented_emergency_recovery', 'authorization_denied',
                    'authorization_unavailable', 'invalid_recovery_path', 'rate_limited'
                )
            ),
            outcome text NOT NULL CHECK (outcome IN ('completed', 'rejected', 'failed')),
            previous_state jsonb NOT NULL CHECK (
                jsonb_typeof(previous_state) = 'object'
                AND octet_length(previous_state::text) <= 1024
            ),
            resulting_state jsonb NOT NULL CHECK (
                jsonb_typeof(resulting_state) = 'object'
                AND octet_length(resulting_state::text) <= 1024
            ),
            password_changed boolean NOT NULL DEFAULT false,
            mfa_disabled boolean NOT NULL DEFAULT false,
            recovery_code_consumed boolean NOT NULL DEFAULT false,
            sessions_revoked integer NOT NULL DEFAULT 0 CHECK (sessions_revoked >= 0),
            CHECK (
                (recovery_mode = 'emergency'
                 AND actor_id IS NULL
                 AND procedure_identity ~ '^[a-z][a-z0-9_-]{0,63}$')
                OR
                (recovery_mode <> 'emergency'
                 AND actor_id IS NOT NULL
                 AND procedure_identity IS NULL)
            ),
            CHECK (
                outcome <> 'completed'
                OR password_changed
                OR mfa_disabled
                OR recovery_code_consumed
                OR sessions_revoked > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX account_recovery_audit_target_time
        ON app.account_recovery_audit_events (target_actor_id, occurred_at, event_id)
        """
    )
    op.execute(
        """
        CREATE INDEX account_recovery_audit_correlation
        ON app.account_recovery_audit_events (correlation_id)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_account_recovery_audit_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'account-recovery audit history cannot be changed or destroyed'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_recovery_audit_rejects_change
        BEFORE UPDATE OR DELETE ON app.account_recovery_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_account_recovery_audit_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_recovery_audit_rejects_truncate
        BEFORE TRUNCATE ON app.account_recovery_audit_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_account_recovery_audit_history_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.record_account_recovery_rejection(
            p_actor_id uuid,
            p_target_actor_id uuid,
            p_occurred_at timestamptz,
            p_correlation_id uuid,
            p_recovery_mode text,
            p_procedure_identity text,
            p_reason text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF p_recovery_mode NOT IN ('recovery_code', 'administrative', 'emergency')
               OR p_reason NOT IN (
                   'authorization_denied', 'authorization_unavailable',
                   'invalid_recovery_path', 'rate_limited'
               )
               OR (p_recovery_mode = 'emergency' AND (
                   p_actor_id IS NOT NULL
                   OR p_procedure_identity !~ '^[a-z][a-z0-9_-]{0,63}$'
               ))
               OR (p_recovery_mode <> 'emergency' AND (
                   p_actor_id IS NULL OR p_procedure_identity IS NOT NULL
               )) THEN
                RAISE EXCEPTION 'invalid account recovery rejection evidence'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            INSERT INTO app.account_recovery_audit_events (
                actor_id, target_actor_id, occurred_at, correlation_id,
                recovery_mode, procedure_identity, reason, outcome,
                previous_state, resulting_state
            ) VALUES (
                p_actor_id, p_target_actor_id, p_occurred_at, p_correlation_id,
                p_recovery_mode, p_procedure_identity, p_reason, 'rejected',
                '{"account_state":"unresolved"}'::jsonb,
                '{"account_state":"unchanged"}'::jsonb
            );
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.perform_account_recovery(
            p_actor_id uuid,
            p_target_actor_id uuid,
            p_correlation_id uuid,
            p_recovery_mode text,
            p_procedure_identity text,
            p_reason text,
            p_verifier_encoding text,
            p_algorithm text,
            p_work_factor_metadata jsonb,
            p_reset_mfa boolean,
            p_recovery_code_id uuid
        ) RETURNS TABLE (
            password_changed boolean,
            mfa_disabled boolean,
            recovery_code_consumed boolean,
            sessions_revoked integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            operation_actor_id uuid := COALESCE(p_actor_id, p_target_actor_id);
            password_present_before boolean;
            active_mfa_before integer;
            active_sessions_before integer;
            code_available_before boolean := false;
            mutation_provenance text;
            previous_state_document jsonb;
            resulting_state_document jsonb;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app.user_accounts
                WHERE actor_id = p_target_actor_id AND lifecycle_state = 'active'
            ) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;
            IF p_recovery_mode = 'administrative' THEN
                IF p_actor_id IS NULL OR p_actor_id = p_target_actor_id
                   OR p_procedure_identity IS NOT NULL
                   OR p_reason <> 'authorized_account_recovery'
                   OR (p_verifier_encoding IS NULL AND NOT p_reset_mfa)
                   OR p_recovery_code_id IS NOT NULL THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            ELSIF p_recovery_mode = 'recovery_code' THEN
                IF p_actor_id IS DISTINCT FROM p_target_actor_id
                   OR p_procedure_identity IS NOT NULL
                   OR p_reason <> 'mfa_recovery'
                   OR p_verifier_encoding IS NOT NULL OR p_reset_mfa
                   OR p_recovery_code_id IS NULL THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            ELSIF p_recovery_mode = 'emergency' THEN
                IF p_actor_id IS NOT NULL
                   OR p_procedure_identity IS NULL
                   OR p_procedure_identity !~ '^[a-z][a-z0-9_-]{0,63}$'
                   OR p_reason <> 'documented_emergency_recovery'
                   OR (p_verifier_encoding IS NULL AND NOT p_reset_mfa)
                   OR p_recovery_code_id IS NOT NULL THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            ELSE
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;
            IF p_verifier_encoding IS NOT NULL AND (
                p_algorithm IS NULL OR p_work_factor_metadata IS NULL
                OR NOT app.valid_password_work_factor_metadata(p_work_factor_metadata)
            ) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;

            SELECT EXISTS (
                SELECT 1 FROM app.password_credentials WHERE actor_id = p_target_actor_id
            ) INTO password_present_before;
            SELECT count(*)::integer INTO active_mfa_before
            FROM app.totp_mfa_enrollments
            WHERE actor_id = p_target_actor_id AND enrollment_state IN ('pending', 'active');
            SELECT count(*)::integer INTO active_sessions_before
            FROM app.browser_sessions
            WHERE actor_id = p_target_actor_id AND revoked_at IS NULL
              AND idle_expires_at > statement_timestamp()
              AND absolute_expires_at > statement_timestamp();

            IF p_recovery_mode = 'recovery_code' THEN
                SELECT true INTO code_available_before
                FROM app.recovery_codes AS recovery_code
                JOIN app.recovery_code_sets AS recovery_set USING (set_id)
                WHERE recovery_code.code_id = p_recovery_code_id
                  AND recovery_set.actor_id = p_target_actor_id
                  AND recovery_code.consumed_at IS NULL
                  AND recovery_code.invalidated_at IS NULL
                  AND recovery_set.invalidated_at IS NULL
                FOR UPDATE OF recovery_code, recovery_set;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            previous_state_document := jsonb_build_object(
                'password_credential_present', password_present_before,
                'active_mfa_enrollments', active_mfa_before,
                'active_sessions', active_sessions_before,
                'recovery_code_available', code_available_before
            );
            mutation_provenance := jsonb_build_object(
                'action', 'account_recovery',
                'correlation_id', p_correlation_id,
                'mode', p_recovery_mode,
                'procedure_identity', p_procedure_identity,
                'reason', p_reason
            )::text;

            password_changed := false;
            IF p_verifier_encoding IS NOT NULL THEN
                UPDATE app.password_credentials
                SET verifier_encoding = p_verifier_encoding,
                    algorithm = p_algorithm,
                    work_factor_metadata = p_work_factor_metadata,
                    changed_by_actor_id = operation_actor_id,
                    provenance = mutation_provenance
                WHERE actor_id = p_target_actor_id;
                password_changed := FOUND;
                IF NOT password_changed THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            mfa_disabled := false;
            IF p_reset_mfa THEN
                UPDATE app.totp_mfa_enrollments
                SET enrollment_state = 'disabled',
                    disabled_by_actor_id = operation_actor_id,
                    disablement_provenance = mutation_provenance
                WHERE actor_id = p_target_actor_id
                  AND enrollment_state IN ('pending', 'active');
                mfa_disabled := FOUND;
            END IF;

            recovery_code_consumed := false;
            IF p_recovery_code_id IS NOT NULL THEN
                UPDATE app.recovery_codes
                SET consumed_at = statement_timestamp(),
                    consumed_by_actor_id = operation_actor_id,
                    consumption_provenance = mutation_provenance
                WHERE code_id = p_recovery_code_id
                  AND consumed_at IS NULL AND invalidated_at IS NULL;
                recovery_code_consumed := FOUND;
                IF NOT recovery_code_consumed THEN
                    RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
                END IF;
            END IF;

            IF p_recovery_mode <> 'recovery_code' AND NOT (password_changed OR mfa_disabled) THEN
                RAISE EXCEPTION 'account recovery rejected' USING ERRCODE = 'P0001';
            END IF;

            UPDATE app.browser_sessions
            SET revoked_by_actor_id = operation_actor_id,
                revocation_reason = CASE
                    WHEN p_recovery_mode = 'recovery_code' THEN 'mfa_recovery'
                    WHEN password_changed THEN 'password_reset'
                    ELSE 'mfa_reset'
                END,
                revocation_provenance = mutation_provenance
            WHERE actor_id = p_target_actor_id
              AND revoked_at IS NULL
              AND idle_expires_at > statement_timestamp()
              AND absolute_expires_at > statement_timestamp();
            GET DIAGNOSTICS sessions_revoked = ROW_COUNT;

            resulting_state_document := jsonb_build_object(
                'password_changed', password_changed,
                'active_mfa_enrollments',
                    active_mfa_before
                    - CASE WHEN mfa_disabled THEN active_mfa_before ELSE 0 END,
                'active_sessions', active_sessions_before - sessions_revoked,
                'recovery_code_consumed', recovery_code_consumed
            );
            INSERT INTO app.account_recovery_audit_events (
                actor_id, target_actor_id, correlation_id, recovery_mode,
                procedure_identity, reason, outcome, previous_state,
                resulting_state, password_changed, mfa_disabled,
                recovery_code_consumed, sessions_revoked
            ) VALUES (
                p_actor_id, p_target_actor_id, p_correlation_id, p_recovery_mode,
                p_procedure_identity, p_reason, 'completed', previous_state_document,
                resulting_state_document, password_changed, mfa_disabled,
                recovery_code_consumed, sessions_revoked
            );
            RETURN NEXT;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.reject_account_recovery_audit_history_change() FROM PUBLIC"
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.record_account_recovery_rejection(
            uuid, uuid, timestamptz, uuid, text, text, text
        ) FROM PUBLIC, prm_runtime
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION app.perform_account_recovery(
            uuid, uuid, uuid, text, text, text, text, text, jsonb, boolean, uuid
        ) FROM PUBLIC, prm_runtime
        """
    )
    op.execute("REVOKE ALL ON app.account_recovery_audit_events FROM PUBLIC, prm_runtime")
    op.execute(
        "REVOKE ALL ON SEQUENCE app.account_recovery_audit_events_event_id_seq "
        "FROM PUBLIC, prm_runtime"
    )
    op.execute(
        """
        REVOKE UPDATE (
            verifier_encoding, algorithm, work_factor_metadata,
            changed_by_actor_id, provenance
        ) ON app.password_credentials FROM prm_runtime
        """
    )
    op.execute(
        """
        GRANT EXECUTE ON FUNCTION app.record_account_recovery_rejection(
            uuid, uuid, timestamptz, uuid, text, text, text
        ) TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT EXECUTE ON FUNCTION app.perform_account_recovery(
            uuid, uuid, uuid, text, text, text, text, text, jsonb, boolean, uuid
        ) TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-005 account-recovery migration is forward-only")
