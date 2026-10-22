"""A session revocation time is never before its last activity (login slice sub-slice L3a-2).

DL-057, DB-AUTH-004, SEC-017. From sub-slice L3a-2 every signed-in request records its session's
activity. A revocation (sign-out, an Owner's disable, MFA change, bundle reduction or assignment
removal, a password or MFA reset) took its time from the start of its statement, so an activity
that a parallel request committed after that start made the revocation break
`CHECK (revoked_at IS NULL OR revoked_at >= last_activity_at)` and roll back: a person who kept
using the app could stop their own revocation (review round 1, security). The lifecycle trigger
function `app.protect_browser_session_lifecycle` is replaced with the same signature, owner,
privileges and attributes; the only change is that a revocation records the later of its
statement time and the session's last activity. A relaxing change: a revocation that failed now
succeeds; nothing else changes.
"""

from alembic import op

revision = "20270127_184"
down_revision = "20270126_183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace the session lifecycle trigger function."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.protect_browser_session_lifecycle()
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
                -- Login sub-slice L3a-2 (review round 1): a revocation never records a time
                -- before the last activity, which a parallel request may have committed after
                -- this statement started.
                NEW.revoked_at = GREATEST(operation_time, OLD.last_activity_at);
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'browser-session update must record activity or revocation'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("session revocation time migration is forward-only")
