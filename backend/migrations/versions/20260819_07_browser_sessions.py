"""Add bounded DB-AUTH-004 browser-session persistence."""

from alembic import op

revision = "20260819_07"
down_revision = "20260819_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create bounded protected browser-session storage."""
    op.execute(
        """
        CREATE TABLE app.browser_sessions (
            session_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            token_verifier bytea NOT NULL
                CHECK (octet_length(token_verifier) = 32),
            verifier_algorithm text NOT NULL
                CHECK (verifier_algorithm = 'sha256'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            last_activity_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            idle_expires_at timestamptz NOT NULL
                DEFAULT statement_timestamp() + interval '30 minutes',
            absolute_expires_at timestamptz NOT NULL
                DEFAULT statement_timestamp() + interval '24 hours',
            creation_provenance text NOT NULL
                CHECK (length(btrim(creation_provenance)) > 0),
            revoked_at timestamptz,
            revoked_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            revocation_reason text,
            revocation_provenance text,
            UNIQUE (token_verifier),
            CHECK (last_activity_at >= created_at),
            CHECK (absolute_expires_at = created_at + interval '24 hours'),
            CHECK (last_activity_at < absolute_expires_at),
            CHECK (revoked_at IS NULL OR revoked_at >= last_activity_at),
            CHECK (
                idle_expires_at = LEAST(
                    last_activity_at + interval '30 minutes',
                    absolute_expires_at
                )
            ),
            CHECK (
                (revoked_at IS NULL
                 AND revoked_by_actor_id IS NULL
                 AND revocation_reason IS NULL
                 AND revocation_provenance IS NULL)
                OR
                (revoked_at IS NOT NULL
                 AND revoked_by_actor_id IS NOT NULL
                 AND revocation_reason IN (
                     'logout',
                     'password_reset',
                     'mfa_reset',
                     'mfa_recovery',
                     'account_disabled',
                     'material_privilege_reduction'
                 )
                 AND length(btrim(revocation_provenance)) > 0)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX browser_sessions_actor_lifecycle
        ON app.browser_sessions (actor_id, revoked_at, idle_expires_at, absolute_expires_at)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_browser_session_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            operation_time timestamptz := statement_timestamp();
        BEGIN
            IF NEW.session_id IS DISTINCT FROM OLD.session_id
               OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
               OR NEW.token_verifier IS DISTINCT FROM OLD.token_verifier
               OR NEW.verifier_algorithm IS DISTINCT FROM OLD.verifier_algorithm
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.absolute_expires_at IS DISTINCT FROM OLD.absolute_expires_at
               OR NEW.creation_provenance IS DISTINCT FROM OLD.creation_provenance THEN
                RAISE EXCEPTION
                    'browser-session identity, verifier, and creation provenance are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'revoked browser session is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.last_activity_at IS DISTINCT FROM OLD.last_activity_at THEN
                IF NEW.idle_expires_at IS DISTINCT FROM OLD.idle_expires_at
                   OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                   OR NEW.revoked_by_actor_id IS DISTINCT FROM OLD.revoked_by_actor_id
                   OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
                   OR NEW.revocation_provenance IS DISTINCT FROM OLD.revocation_provenance
                   OR operation_time <= OLD.last_activity_at
                   OR operation_time >= OLD.idle_expires_at
                   OR operation_time >= OLD.absolute_expires_at THEN
                    RAISE EXCEPTION 'invalid browser-session activity transition'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                NEW.last_activity_at = operation_time;
                NEW.idle_expires_at = LEAST(
                    operation_time + interval '30 minutes',
                    OLD.absolute_expires_at
                );
                RETURN NEW;
            END IF;

            IF NEW.revoked_by_actor_id IS DISTINCT FROM OLD.revoked_by_actor_id
               OR NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason
               OR NEW.revocation_provenance IS DISTINCT FROM OLD.revocation_provenance THEN
                IF NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                   OR NEW.idle_expires_at IS DISTINCT FROM OLD.idle_expires_at
                   OR NEW.revoked_by_actor_id IS NULL
                   OR NEW.revocation_reason IS NULL
                   OR NEW.revocation_provenance IS NULL
                   OR length(btrim(NEW.revocation_provenance)) = 0 THEN
                    RAISE EXCEPTION
                        'browser-session revocation requires actor, reason, and provenance'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                NEW.revoked_at = operation_time;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'browser-session update must record activity or revocation'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER browser_sessions_protect_lifecycle
        BEFORE UPDATE ON app.browser_sessions
        FOR EACH ROW
        EXECUTE FUNCTION app.protect_browser_session_lifecycle()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_browser_session_history_destruction()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'browser-session history cannot be deleted or truncated'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER browser_sessions_reject_delete
        BEFORE DELETE ON app.browser_sessions
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_browser_session_history_destruction()
        """
    )
    op.execute(
        """
        CREATE TRIGGER browser_sessions_reject_truncate
        BEFORE TRUNCATE ON app.browser_sessions
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_browser_session_history_destruction()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.protect_browser_session_lifecycle() FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION app.reject_browser_session_history_destruction() FROM PUBLIC"
    )
    op.execute("REVOKE ALL ON app.browser_sessions FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (
            session_id, actor_id, token_verifier, verifier_algorithm,
            created_at, last_activity_at, idle_expires_at, absolute_expires_at,
            revoked_at, revocation_reason
        ) ON app.browser_sessions TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (
            session_id, actor_id, token_verifier, verifier_algorithm, creation_provenance
        ) ON app.browser_sessions TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT UPDATE (
            last_activity_at, revoked_by_actor_id, revocation_reason, revocation_provenance
        ) ON app.browser_sessions TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-004 browser-session migration is forward-only")
