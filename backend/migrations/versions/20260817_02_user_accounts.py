"""Add bounded DB-AUTH-001 local human-account storage."""

from alembic import op

revision = "20260817_02"
down_revision = "20260813_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the local human-account identity and policy record."""
    op.execute(
        """
        CREATE TABLE app.user_accounts (
            actor_id uuid PRIMARY KEY,
            normalized_username text NOT NULL UNIQUE
                CHECK (
                    normalized_username = lower(btrim(normalized_username))
                    AND length(normalized_username) > 0
                ),
            display_name text NOT NULL CHECK (length(btrim(display_name)) > 0),
            audit_name text NOT NULL CHECK (length(btrim(audit_name)) > 0),
            lifecycle_state text NOT NULL
                CHECK (lifecycle_state IN ('active', 'disabled')),
            mfa_policy_class text NOT NULL
                CHECK (mfa_policy_class IN ('required', 'optional')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by_actor_id uuid,
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_user_account_actor_id_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.actor_id IS DISTINCT FROM OLD.actor_id THEN
                RAISE EXCEPTION 'user account actor identity is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.updated_at = statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER user_accounts_protect_identity_and_timestamp
        BEFORE UPDATE ON app.user_accounts
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_user_account_actor_id_change()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.reject_user_account_actor_id_change() FROM PUBLIC")
    op.execute("GRANT SELECT ON app.user_accounts TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-001 migration is forward-only")
