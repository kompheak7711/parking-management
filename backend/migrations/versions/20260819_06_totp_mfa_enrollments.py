"""Add bounded DB-AUTH-003 protected TOTP enrollment persistence."""

from alembic import op

revision = "20260819_06"
down_revision = "20260818_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create constrained protected TOTP material and forward-only enrollment state."""
    op.execute(
        """
        CREATE TABLE app.totp_mfa_enrollments (
            enrollment_id uuid PRIMARY KEY,
            actor_id uuid NOT NULL
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            secret_ciphertext bytea NOT NULL
                CHECK (octet_length(secret_ciphertext) >= 36),
            secret_nonce bytea NOT NULL
                CHECK (octet_length(secret_nonce) = 12),
            key_identifier text NOT NULL
                CHECK (key_identifier ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
            protection_algorithm text NOT NULL
                CHECK (protection_algorithm = 'aes-256-gcm'),
            totp_algorithm text NOT NULL
                CHECK (totp_algorithm = 'sha1'),
            digits smallint NOT NULL DEFAULT 6 CHECK (digits = 6),
            period_seconds integer NOT NULL DEFAULT 30 CHECK (period_seconds = 30),
            enrollment_state text NOT NULL DEFAULT 'pending'
                CHECK (enrollment_state IN ('pending', 'active', 'disabled')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0),
            activated_at timestamptz,
            activated_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            activation_provenance text,
            disabled_at timestamptz,
            disabled_by_actor_id uuid
                REFERENCES app.user_accounts (actor_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            disablement_provenance text,
            CHECK (
                (enrollment_state = 'pending'
                 AND activated_at IS NULL
                 AND activated_by_actor_id IS NULL
                 AND activation_provenance IS NULL
                 AND disabled_at IS NULL
                 AND disabled_by_actor_id IS NULL
                 AND disablement_provenance IS NULL)
                OR
                (enrollment_state = 'active'
                 AND activated_at IS NOT NULL
                 AND activated_by_actor_id IS NOT NULL
                 AND length(btrim(activation_provenance)) > 0
                 AND disabled_at IS NULL
                 AND disabled_by_actor_id IS NULL
                 AND disablement_provenance IS NULL)
                OR
                (enrollment_state = 'disabled'
                 AND disabled_at IS NOT NULL
                 AND disabled_by_actor_id IS NOT NULL
                 AND length(btrim(disablement_provenance)) > 0
                 AND (
                     (activated_at IS NULL
                      AND activated_by_actor_id IS NULL
                      AND activation_provenance IS NULL)
                     OR
                     (activated_at IS NOT NULL
                      AND activated_by_actor_id IS NOT NULL
                      AND length(btrim(activation_provenance)) > 0)
                 ))
            ),
            CHECK (activated_at IS NULL OR activated_at >= created_at),
            CHECK (disabled_at IS NULL OR disabled_at >= created_at),
            CHECK (disabled_at IS NULL OR activated_at IS NULL OR disabled_at >= activated_at)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX totp_mfa_enrollments_one_live_per_actor
        ON app.totp_mfa_enrollments (actor_id)
        WHERE enrollment_state IN ('pending', 'active')
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX totp_mfa_enrollments_unique_nonce_per_key
        ON app.totp_mfa_enrollments (key_identifier, secret_nonce)
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.protect_totp_mfa_enrollment_lifecycle()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.enrollment_id IS DISTINCT FROM OLD.enrollment_id
               OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
               OR NEW.secret_ciphertext IS DISTINCT FROM OLD.secret_ciphertext
               OR NEW.secret_nonce IS DISTINCT FROM OLD.secret_nonce
               OR NEW.key_identifier IS DISTINCT FROM OLD.key_identifier
               OR NEW.protection_algorithm IS DISTINCT FROM OLD.protection_algorithm
               OR NEW.totp_algorithm IS DISTINCT FROM OLD.totp_algorithm
               OR NEW.digits IS DISTINCT FROM OLD.digits
               OR NEW.period_seconds IS DISTINCT FROM OLD.period_seconds
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.created_by_actor_id IS DISTINCT FROM OLD.created_by_actor_id
               OR NEW.provenance IS DISTINCT FROM OLD.provenance THEN
                RAISE EXCEPTION 'TOTP enrollment identity, verifier material, and provenance are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.enrollment_state = 'disabled' THEN
                RAISE EXCEPTION 'disabled TOTP enrollment is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.enrollment_state = 'pending' AND NEW.enrollment_state = 'active' THEN
                IF NEW.activated_by_actor_id IS NULL
                   OR length(btrim(NEW.activation_provenance)) = 0 THEN
                    RAISE EXCEPTION 'TOTP activation requires actor and provenance'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF NEW.disabled_at IS NOT NULL
                   OR NEW.disabled_by_actor_id IS NOT NULL
                   OR NEW.disablement_provenance IS NOT NULL THEN
                    RAISE EXCEPTION 'TOTP activation cannot disable enrollment'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                NEW.activated_at = statement_timestamp();
                RETURN NEW;
            END IF;

            IF NEW.enrollment_state = 'disabled'
               AND OLD.enrollment_state IN ('pending', 'active') THEN
                IF NEW.disabled_by_actor_id IS NULL
                   OR length(btrim(NEW.disablement_provenance)) = 0 THEN
                    RAISE EXCEPTION 'TOTP disablement requires actor and provenance'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF OLD.enrollment_state = 'active'
                   AND (NEW.activated_at IS DISTINCT FROM OLD.activated_at
                        OR NEW.activated_by_actor_id IS DISTINCT FROM OLD.activated_by_actor_id
                        OR NEW.activation_provenance IS DISTINCT FROM OLD.activation_provenance) THEN
                    RAISE EXCEPTION 'TOTP activation evidence is immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF OLD.enrollment_state = 'pending'
                   AND (NEW.activated_at IS NOT NULL
                        OR NEW.activated_by_actor_id IS NOT NULL
                        OR NEW.activation_provenance IS NOT NULL) THEN
                    RAISE EXCEPTION 'pending TOTP enrollment cannot invent activation evidence'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                NEW.disabled_at = statement_timestamp();
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid TOTP enrollment lifecycle transition'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER totp_mfa_enrollments_protect_lifecycle
        BEFORE UPDATE ON app.totp_mfa_enrollments
        FOR EACH ROW
        EXECUTE FUNCTION app.protect_totp_mfa_enrollment_lifecycle()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_totp_mfa_enrollment_history_destruction()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'TOTP enrollment history cannot be deleted or truncated'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER totp_mfa_enrollments_reject_delete
        BEFORE DELETE ON app.totp_mfa_enrollments
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_totp_mfa_enrollment_history_destruction()
        """
    )
    op.execute(
        """
        CREATE TRIGGER totp_mfa_enrollments_reject_truncate
        BEFORE TRUNCATE ON app.totp_mfa_enrollments
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_totp_mfa_enrollment_history_destruction()
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.protect_totp_mfa_enrollment_lifecycle() FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.reject_totp_mfa_enrollment_history_destruction() FROM PUBLIC"
    )
    op.execute("REVOKE ALL ON app.totp_mfa_enrollments FROM PUBLIC, prm_runtime")
    op.execute(
        """
        GRANT SELECT (
            enrollment_id, actor_id, secret_ciphertext, secret_nonce, key_identifier,
            protection_algorithm, totp_algorithm, digits, period_seconds,
            enrollment_state, created_at, activated_at, disabled_at
        ) ON app.totp_mfa_enrollments TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT INSERT (
            enrollment_id, actor_id, secret_ciphertext, secret_nonce, key_identifier,
            protection_algorithm, totp_algorithm, digits, period_seconds,
            created_by_actor_id, provenance
        ) ON app.totp_mfa_enrollments TO prm_runtime
        """
    )
    op.execute(
        """
        GRANT UPDATE (
            enrollment_state, activated_at, activated_by_actor_id, activation_provenance,
            disabled_at, disabled_by_actor_id, disablement_provenance
        ) ON app.totp_mfa_enrollments TO prm_runtime
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("DB-AUTH-003 TOTP enrollment migration is forward-only")
