"""Add the bounded DB-AUTH-005 initial Owner bootstrap closure guard."""

from alembic import op

revision = "20260818_05"
down_revision = "20260817_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a transactional one-time closure guard and immutable audit evidence."""
    op.execute(
        """
        CREATE TABLE app.initial_owner_bootstrap_closure (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            established_actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED,
            established_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            correlation_id uuid NOT NULL UNIQUE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.initial_owner_bootstrap_audit_events (
            event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            target_actor_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            procedure_identity text NOT NULL
                CHECK (procedure_identity = 'protected_initial_owner_bootstrap'),
            correlation_id uuid NOT NULL,
            outcome text NOT NULL CHECK (outcome IN ('completed', 'rejected')),
            reason text NOT NULL
                CHECK (reason IN (
                    'initial_owner_established',
                    'bootstrap_closed'
                )),
            previous_state text NOT NULL CHECK (previous_state IN ('open', 'closed')),
            resulting_state text NOT NULL CHECK (resulting_state IN ('open', 'closed')),
            established_actor_id uuid,
            CHECK (
                (outcome = 'completed'
                 AND reason = 'initial_owner_established'
                 AND previous_state = 'open'
                 AND resulting_state = 'closed'
                 AND established_actor_id = target_actor_id)
                OR
                (outcome = 'rejected'
                 AND reason = 'bootstrap_closed'
                 AND previous_state = 'closed'
                 AND resulting_state = 'closed'
                 AND established_actor_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_initial_owner_bootstrap_history_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'initial Owner bootstrap history is immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER initial_owner_bootstrap_closure_is_immutable
        BEFORE UPDATE OR DELETE ON app.initial_owner_bootstrap_closure
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_initial_owner_bootstrap_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER initial_owner_bootstrap_closure_rejects_truncate
        BEFORE TRUNCATE ON app.initial_owner_bootstrap_closure
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_initial_owner_bootstrap_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER initial_owner_bootstrap_audit_is_immutable
        BEFORE UPDATE OR DELETE ON app.initial_owner_bootstrap_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_initial_owner_bootstrap_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER initial_owner_bootstrap_audit_rejects_truncate
        BEFORE TRUNCATE ON app.initial_owner_bootstrap_audit_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_initial_owner_bootstrap_history_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.attempt_initial_owner_bootstrap_closure(
            p_target_actor_id uuid,
            p_correlation_id uuid
        )
        RETURNS TABLE (established boolean)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            existing_actor_id uuid;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(120120059);

            SELECT closure.established_actor_id
            INTO existing_actor_id
            FROM app.initial_owner_bootstrap_closure AS closure
            WHERE closure.singleton;

            IF existing_actor_id IS NOT NULL THEN
                INSERT INTO app.initial_owner_bootstrap_audit_events (
                    target_actor_id,
                    procedure_identity,
                    correlation_id,
                    outcome,
                    reason,
                    previous_state,
                    resulting_state,
                    established_actor_id
                ) VALUES (
                    p_target_actor_id,
                    'protected_initial_owner_bootstrap',
                    p_correlation_id,
                    'rejected',
                    'bootstrap_closed',
                    'closed',
                    'closed',
                    existing_actor_id
                );
                RETURN QUERY SELECT false;
                RETURN;
            END IF;

            INSERT INTO app.initial_owner_bootstrap_closure (
                established_actor_id,
                correlation_id
            ) VALUES (
                p_target_actor_id,
                p_correlation_id
            );
            INSERT INTO app.initial_owner_bootstrap_audit_events (
                target_actor_id,
                procedure_identity,
                correlation_id,
                outcome,
                reason,
                previous_state,
                resulting_state,
                established_actor_id
            ) VALUES (
                p_target_actor_id,
                'protected_initial_owner_bootstrap',
                p_correlation_id,
                'completed',
                'initial_owner_established',
                'open',
                'closed',
                p_target_actor_id
            );
            RETURN QUERY SELECT true;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.reject_initial_owner_bootstrap_history_change() FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.attempt_initial_owner_bootstrap_closure(uuid, uuid) "
        "FROM PUBLIC, prm_runtime"
    )
    op.execute("REVOKE ALL ON app.initial_owner_bootstrap_closure FROM PUBLIC, prm_runtime")
    op.execute("REVOKE ALL ON app.initial_owner_bootstrap_audit_events FROM PUBLIC, prm_runtime")
    op.execute(
        "REVOKE ALL ON SEQUENCE app.initial_owner_bootstrap_audit_events_event_id_seq "
        "FROM PUBLIC, prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-005 bootstrap-closure migration is forward-only")
