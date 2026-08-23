"""Add the single-Property identity and versioned configuration."""

from alembic import op

revision = "20260823_11"
down_revision = "20260823_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the one-row Property identity and timezone configuration."""
    op.execute(
        """
        CREATE TABLE app.property_configuration (
            singleton_key boolean PRIMARY KEY DEFAULT true,
            property_id uuid NOT NULL UNIQUE,
            timezone_name text NOT NULL DEFAULT 'Asia/Phnom_Penh',
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT property_configuration_singleton_key CHECK (singleton_key),
            CONSTRAINT property_configuration_property_id_nonzero CHECK (
                property_id <> '00000000-0000-0000-0000-000000000000'::uuid
            ),
            CONSTRAINT property_configuration_timezone_authoritative CHECK (
                timezone_name = 'Asia/Phnom_Penh'
            ),
            CONSTRAINT property_configuration_version_positive CHECK (
                version > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_property_configuration_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.singleton_key IS DISTINCT FROM OLD.singleton_key
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.version <> OLD.version + 1
            THEN
                RAISE EXCEPTION 'Property identity or version transition is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.reject_property_configuration_mutation() FROM PUBLIC"
    )
    op.execute(
        """
        CREATE TRIGGER reject_property_configuration_update_or_delete
        BEFORE UPDATE OR DELETE ON app.property_configuration
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_property_configuration_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reject_property_configuration_truncate
        BEFORE TRUNCATE ON app.property_configuration
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_property_configuration_mutation()
        """
    )
    op.execute(
        "ALTER TABLE app.property_configuration ENABLE ALWAYS TRIGGER "
        "reject_property_configuration_update_or_delete"
    )
    op.execute(
        "ALTER TABLE app.property_configuration ENABLE ALWAYS TRIGGER "
        "reject_property_configuration_truncate"
    )
    op.execute(
        """
        CREATE FUNCTION app.initialize_property(p_property_id uuid)
        RETURNS TABLE(property_id uuid, timezone_name text, version integer)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            INSERT INTO app.property_configuration AS configuration (property_id)
            VALUES (p_property_id)
            RETURNING
                configuration.property_id,
                configuration.timezone_name,
                configuration.version;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.initialize_property(uuid) FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON TABLE app.property_configuration "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT, UPDATE ON TABLE app.property_configuration TO prm_runtime"
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.initialize_property(uuid) TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback of the authoritative Property identity."""
    raise RuntimeError("Property configuration migration is forward-only")
