"""Add bounded DB-AUTH-002 password-credential storage."""

from alembic import op

revision = "20260817_03"
down_revision = "20260817_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create constrained adaptive password-verifier storage."""
    op.execute(
        """
        CREATE FUNCTION app.valid_password_work_factor_metadata(metadata jsonb)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        STRICT
        AS $$
            SELECT
                jsonb_typeof(metadata) = 'object'
                AND metadata <> '{}'::jsonb
                AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_each(metadata) AS item(key, value)
                    WHERE length(btrim(key)) = 0
                       OR CASE
                            WHEN jsonb_typeof(value) = 'number'
                            THEN (value #>> '{}')::numeric <= 0
                              OR trunc((value #>> '{}')::numeric)
                                 <> (value #>> '{}')::numeric
                            ELSE true
                          END
                )
        $$
        """
    )
    op.execute(
        """
        CREATE TABLE app.password_credentials (
            actor_id uuid PRIMARY KEY
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            verifier_encoding text NOT NULL
                CHECK (
                    verifier_encoding = btrim(verifier_encoding)
                    AND verifier_encoding !~ '[[:space:][:cntrl:]]'
                    AND verifier_encoding ~ '^\$[A-Za-z0-9._-]+\$.+\$.+$'
                ),
            algorithm text NOT NULL
                CHECK (
                    algorithm = lower(btrim(algorithm))
                    AND algorithm ~ '^[a-z0-9][a-z0-9._-]*$'
                    AND verifier_encoding LIKE '$' || algorithm || '$%'
                ),
            work_factor_metadata jsonb NOT NULL
                CHECK (app.valid_password_work_factor_metadata(work_factor_metadata)),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            changed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            changed_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0),
            CHECK (changed_at >= created_at)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_password_credential_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.actor_id IS DISTINCT FROM OLD.actor_id THEN
                RAISE EXCEPTION 'password credential actor identity is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'password credential creation time is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.verifier_encoding IS NOT DISTINCT FROM OLD.verifier_encoding
               AND NEW.algorithm IS NOT DISTINCT FROM OLD.algorithm
               AND NEW.work_factor_metadata IS NOT DISTINCT FROM OLD.work_factor_metadata THEN
                RAISE EXCEPTION 'password credential updates require new verifier material'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.changed_by_actor_id IS NULL
               OR NEW.provenance IS NOT DISTINCT FROM OLD.provenance THEN
                RAISE EXCEPTION 'password credential updates require actor and new provenance'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.changed_at = statement_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER password_credentials_protect_lifecycle
        BEFORE UPDATE ON app.password_credentials
        FOR EACH ROW
        EXECUTE FUNCTION app.protect_password_credential_lifecycle()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.valid_password_work_factor_metadata(jsonb) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION app.protect_password_credential_lifecycle() FROM PUBLIC")
    op.execute("REVOKE ALL ON app.password_credentials FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (actor_id, verifier_encoding, algorithm, work_factor_metadata)
        ON app.password_credentials TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-002 migration is forward-only")
