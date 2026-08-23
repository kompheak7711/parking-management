"""Complete Property source fields and configured Payment Methods."""

from alembic import op

revision = "20260823_12"
down_revision = "20260823_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add protected canonical Property business configuration."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM app.property_configuration) THEN
                RAISE EXCEPTION
                    'Property source fields require an operator-supplied forward data migration';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE app.property_configuration
            ADD COLUMN name text,
            ADD COLUMN address_text text,
            ADD COLUMN created_by uuid REFERENCES app.user_accounts(actor_id),
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            ADD COLUMN updated_by uuid REFERENCES app.user_accounts(actor_id),
            ADD CONSTRAINT property_configuration_name_nonblank
                CHECK (length(btrim(name)) > 0),
            ADD CONSTRAINT property_configuration_address_nonblank
                CHECK (address_text IS NULL OR length(btrim(address_text)) > 0)
        """
    )
    op.execute(
        """
        ALTER TABLE app.property_configuration
            ALTER COLUMN name SET NOT NULL,
            ALTER COLUMN created_by SET NOT NULL,
            ALTER COLUMN updated_by SET NOT NULL
        """
    )
    op.execute(
        """
        CREATE TABLE app.payment_methods (
            id uuid PRIMARY KEY,
            code text NOT NULL UNIQUE CHECK (length(btrim(code)) > 0),
            display_name text NOT NULL CHECK (length(btrim(display_name)) > 0),
            accepted boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id)
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.reject_property_configuration_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.singleton_key IS DISTINCT FROM OLD.singleton_key
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.timezone_name IS DISTINCT FROM OLD.timezone_name
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Property identity, fixed configuration, and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_payment_method_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Payment Method history cannot be deleted'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER payment_methods_reject_delete
        BEFORE DELETE ON app.payment_methods
        FOR EACH ROW EXECUTE FUNCTION app.reject_payment_method_delete()
        """
    )
    op.execute(
        """
        CREATE TRIGGER payment_methods_reject_truncate
        BEFORE TRUNCATE ON app.payment_methods
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_payment_method_delete()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.initialize_property(uuid) FROM PUBLIC")
    op.execute("DROP FUNCTION app.initialize_property(uuid)")
    op.execute(
        """
        CREATE FUNCTION app.initialize_property(
            p_property_id uuid,
            p_name text,
            p_address_text text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            property_id uuid,
            name text,
            address_text text,
            timezone_name text,
            version integer
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            INSERT INTO app.property_configuration AS configuration (
                property_id,
                name,
                address_text,
                created_by,
                updated_by
            )
            VALUES (
                p_property_id,
                btrim(p_name),
                NULLIF(btrim(p_address_text), ''),
                p_actor_id,
                p_actor_id
            )
            RETURNING
                configuration.property_id,
                configuration.name,
                configuration.address_text,
                configuration.timezone_name,
                configuration.version;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.update_property_source(
            p_property_id uuid,
            p_name text,
            p_address_text text,
            p_expected_version integer,
            p_actor_id uuid
        )
        RETURNS TABLE(
            property_id uuid,
            name text,
            address_text text,
            timezone_name text,
            version integer
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            UPDATE app.property_configuration AS configuration
            SET name = btrim(p_name),
                address_text = NULLIF(btrim(p_address_text), ''),
                updated_at = statement_timestamp(),
                updated_by = p_actor_id,
                version = configuration.version + 1
            WHERE configuration.property_id = p_property_id
              AND configuration.version = p_expected_version
            RETURNING
                configuration.property_id,
                configuration.name,
                configuration.address_text,
                configuration.timezone_name,
                configuration.version;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.replace_property_payment_methods(
            p_property_id uuid,
            p_methods jsonb,
            p_expected_version integer,
            p_actor_id uuid
        )
        RETURNS TABLE(
            property_id uuid,
            name text,
            address_text text,
            timezone_name text,
            version integer
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF jsonb_typeof(p_methods) <> 'array'
                OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(p_methods) AS method
                    WHERE jsonb_typeof(method) <> 'object'
                       OR NULLIF(btrim(method->>'id'), '') IS NULL
                       OR NULLIF(btrim(method->>'code'), '') IS NULL
                       OR NULLIF(btrim(method->>'display_name'), '') IS NULL
                       OR jsonb_typeof(method->'accepted') <> 'boolean'
                )
                OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(p_methods) AS method
                    GROUP BY btrim(method->>'code')
                    HAVING count(*) > 1
                )
            THEN
                RAISE EXCEPTION 'Payment Method configuration is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM 1
            FROM app.property_configuration AS configuration
            WHERE configuration.property_id = p_property_id
              AND configuration.version = p_expected_version
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            UPDATE app.payment_methods AS existing
            SET accepted = false,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE existing.accepted
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(p_methods) AS method
                  WHERE btrim(method->>'code') = existing.code
              );

            INSERT INTO app.payment_methods AS existing (
                id,
                code,
                display_name,
                accepted,
                created_by,
                updated_by
            )
            SELECT
                (method->>'id')::uuid,
                btrim(method->>'code'),
                btrim(method->>'display_name'),
                (method->>'accepted')::boolean,
                p_actor_id,
                p_actor_id
            FROM jsonb_array_elements(p_methods) AS method
            ON CONFLICT (code) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                accepted = EXCLUDED.accepted,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id;

            RETURN QUERY
            UPDATE app.property_configuration AS configuration
            SET updated_at = statement_timestamp(),
                updated_by = p_actor_id,
                version = configuration.version + 1
            WHERE configuration.property_id = p_property_id
            RETURNING
                configuration.property_id,
                configuration.name,
                configuration.address_text,
                configuration.timezone_name,
                configuration.version;
        END;
        $$
        """
    )
    for function in (
        "app.reject_payment_method_delete()",
        "app.initialize_property(uuid, text, text, uuid)",
        "app.update_property_source(uuid, text, text, integer, uuid)",
        "app.replace_property_payment_methods(uuid, jsonb, integer, uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON TABLE app.property_configuration, app.payment_methods "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute(
        "GRANT SELECT ON TABLE app.property_configuration, app.payment_methods TO prm_runtime"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.initialize_property(uuid, text, text, uuid), "
        "app.update_property_source(uuid, text, text, integer, uuid), "
        "app.replace_property_payment_methods(uuid, jsonb, integer, uuid) "
        "TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback of Property business configuration."""
    raise RuntimeError("Property business configuration migration is forward-only")
