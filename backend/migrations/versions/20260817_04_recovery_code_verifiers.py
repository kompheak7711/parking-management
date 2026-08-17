"""Add bounded DB-AUTH-003 recovery-code verifier persistence."""

from alembic import op

revision = "20260817_04"
down_revision = "20260817_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create constrained recovery-code set and opaque verifier storage."""
    op.execute(
        """
        CREATE FUNCTION app.valid_recovery_code_work_factor_metadata(metadata jsonb)
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
        CREATE TABLE app.recovery_code_sets (
            set_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0),
            invalidated_at timestamptz,
            invalidated_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            invalidation_provenance text,
            CHECK (
                (invalidated_at IS NULL
                 AND invalidated_by_actor_id IS NULL
                 AND invalidation_provenance IS NULL)
                OR
                (invalidated_at IS NOT NULL
                 AND invalidated_by_actor_id IS NOT NULL
                 AND length(btrim(invalidation_provenance)) > 0)
            ),
            CHECK (invalidated_at IS NULL OR invalidated_at >= created_at)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.recovery_codes (
            code_id uuid PRIMARY KEY,
            set_id uuid NOT NULL
                REFERENCES app.recovery_code_sets (set_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            verifier_encoding text NOT NULL UNIQUE
                CHECK (
                    verifier_encoding = btrim(verifier_encoding)
                    AND verifier_encoding !~ '[[:space:][:cntrl:]]'
                    AND verifier_encoding ~ '^\\$[A-Za-z0-9._-]+\\$.+\\$.+$'
                ),
            algorithm text NOT NULL
                CHECK (
                    algorithm = lower(btrim(algorithm))
                    AND algorithm ~ '^[a-z0-9][a-z0-9._-]*$'
                    AND verifier_encoding LIKE '$' || algorithm || '$%'
                ),
            work_factor_metadata jsonb NOT NULL
                CHECK (
                    app.valid_recovery_code_work_factor_metadata(work_factor_metadata)
                ),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0),
            consumed_at timestamptz,
            consumed_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            consumption_provenance text,
            invalidated_at timestamptz,
            invalidated_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            invalidation_provenance text,
            CHECK (
                (consumed_at IS NULL
                 AND consumed_by_actor_id IS NULL
                 AND consumption_provenance IS NULL)
                OR
                (consumed_at IS NOT NULL
                 AND consumed_by_actor_id IS NOT NULL
                 AND length(btrim(consumption_provenance)) > 0)
            ),
            CHECK (
                (invalidated_at IS NULL
                 AND invalidated_by_actor_id IS NULL
                 AND invalidation_provenance IS NULL)
                OR
                (invalidated_at IS NOT NULL
                 AND invalidated_by_actor_id IS NOT NULL
                 AND length(btrim(invalidation_provenance)) > 0)
            ),
            CHECK (consumed_at IS NULL OR consumed_at >= created_at),
            CHECK (invalidated_at IS NULL OR invalidated_at >= created_at)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_recovery_code_set_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.set_id IS DISTINCT FROM OLD.set_id
               OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.created_by_actor_id IS DISTINCT FROM OLD.created_by_actor_id
               OR NEW.provenance IS DISTINCT FROM OLD.provenance THEN
                RAISE EXCEPTION 'recovery-code set identity and creation provenance are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.invalidated_at IS NOT NULL
               AND (NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at
                    OR NEW.invalidated_by_actor_id IS DISTINCT FROM OLD.invalidated_by_actor_id
                    OR NEW.invalidation_provenance IS DISTINCT FROM OLD.invalidation_provenance) THEN
                RAISE EXCEPTION 'recovery-code set invalidation is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.invalidated_at IS NULL AND NEW.invalidated_at IS NULL THEN
                RAISE EXCEPTION 'recovery-code set update must invalidate the set'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_recovery_code_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.code_id IS DISTINCT FROM OLD.code_id
               OR NEW.set_id IS DISTINCT FROM OLD.set_id
               OR NEW.verifier_encoding IS DISTINCT FROM OLD.verifier_encoding
               OR NEW.algorithm IS DISTINCT FROM OLD.algorithm
               OR NEW.work_factor_metadata IS DISTINCT FROM OLD.work_factor_metadata
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.provenance IS DISTINCT FROM OLD.provenance THEN
                RAISE EXCEPTION 'recovery-code identity and verifier provenance are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.consumed_at IS NOT NULL
               AND (NEW.consumed_at IS DISTINCT FROM OLD.consumed_at
                    OR NEW.consumed_by_actor_id IS DISTINCT FROM OLD.consumed_by_actor_id
                    OR NEW.consumption_provenance IS DISTINCT FROM OLD.consumption_provenance) THEN
                RAISE EXCEPTION 'recovery-code consumption is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.invalidated_at IS NOT NULL
               AND (NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at
                    OR NEW.invalidated_by_actor_id IS DISTINCT FROM OLD.invalidated_by_actor_id
                    OR NEW.invalidation_provenance IS DISTINCT FROM OLD.invalidation_provenance) THEN
                RAISE EXCEPTION 'recovery-code invalidation is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.invalidated_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at THEN
                RAISE EXCEPTION 'invalidated recovery code cannot be consumed'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.consumed_at IS NULL AND OLD.invalidated_at IS NULL
               AND NEW.consumed_at IS NOT NULL AND NEW.invalidated_at IS NOT NULL THEN
                RAISE EXCEPTION 'recovery code cannot be consumed and invalidated together'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.consumed_at IS NOT DISTINCT FROM OLD.consumed_at
               AND NEW.invalidated_at IS NOT DISTINCT FROM OLD.invalidated_at THEN
                RAISE EXCEPTION 'recovery-code update must advance lifecycle state'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER recovery_code_sets_protect_lifecycle
        BEFORE UPDATE ON app.recovery_code_sets
        FOR EACH ROW
        EXECUTE FUNCTION app.protect_recovery_code_set_lifecycle()
        """
    )
    op.execute(
        """
        CREATE TRIGGER recovery_codes_protect_lifecycle
        BEFORE UPDATE ON app.recovery_codes
        FOR EACH ROW
        EXECUTE FUNCTION app.protect_recovery_code_lifecycle()
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.valid_recovery_code_work_factor_metadata(jsonb) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.valid_recovery_code_work_factor_metadata(jsonb) "
        "TO prm_runtime"
    )
    op.execute("REVOKE ALL ON FUNCTION app.protect_recovery_code_set_lifecycle() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION app.protect_recovery_code_lifecycle() FROM PUBLIC")
    op.execute("REVOKE ALL ON app.recovery_code_sets FROM PUBLIC, prm_runtime")
    op.execute("REVOKE ALL ON app.recovery_codes FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (
            set_id, actor_id, created_at, created_by_actor_id, provenance,
            invalidated_at, invalidated_by_actor_id, invalidation_provenance
        ) ON app.recovery_code_sets TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (set_id, actor_id, created_by_actor_id, provenance)
        ON app.recovery_code_sets TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT UPDATE (
            invalidated_at, invalidated_by_actor_id, invalidation_provenance
        ) ON app.recovery_code_sets TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT SELECT (
            code_id, set_id, verifier_encoding, algorithm, work_factor_metadata,
            created_at, provenance, consumed_at, consumed_by_actor_id,
            consumption_provenance, invalidated_at, invalidated_by_actor_id,
            invalidation_provenance
        ) ON app.recovery_codes TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (
            code_id, set_id, verifier_encoding, algorithm, work_factor_metadata, provenance
        ) ON app.recovery_codes TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT UPDATE (
            consumed_at, consumed_by_actor_id, consumption_provenance,
            invalidated_at, invalidated_by_actor_id, invalidation_provenance
        ) ON app.recovery_codes TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-003 recovery-code migration is forward-only")
