"""Add stable, Property-scoped Unit identity and persistence."""

from alembic import op

revision = "20260823_13"
down_revision = "20260823_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the protected Unit store and its constrained creation boundary."""
    op.execute("ALTER TABLE app.property_configuration RENAME TO properties")
    op.execute("ALTER TABLE app.properties RENAME COLUMN property_id TO id")
    op.execute(
        "ALTER TABLE app.properties DROP CONSTRAINT property_configuration_pkey"
    )
    op.execute(
        "ALTER TABLE app.properties "
        "DROP CONSTRAINT property_configuration_property_id_key"
    )
    op.execute(
        "ALTER TABLE app.properties ADD CONSTRAINT properties_pkey PRIMARY KEY (id)"
    )
    op.execute(
        "ALTER TABLE app.properties ADD CONSTRAINT properties_singleton_key_unique "
        "UNIQUE (singleton_key)"
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
                OR NEW.id IS DISTINCT FROM OLD.id
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
        CREATE VIEW app.property_configuration
        WITH (security_invoker = true)
        AS
        SELECT
            singleton_key,
            id AS property_id,
            timezone_name,
            version,
            created_at,
            name,
            address_text,
            created_by,
            updated_at,
            updated_by
        FROM app.properties
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE app.property_configuration "
        "FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.property_configuration TO prm_runtime")
    op.execute(
        r"""
        CREATE TABLE app.units (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL
                REFERENCES app.properties(id) ON DELETE RESTRICT,
            unit_number text NOT NULL,
            floor text NOT NULL,
            unit_type text NOT NULL,
            status text NOT NULL,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT units_unit_number_nonblank
                CHECK (length(btrim(
                    unit_number,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                )) > 0),
            CONSTRAINT units_unit_number_normalized
                CHECK (unit_number = btrim(
                    unit_number,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                )),
            CONSTRAINT units_floor_nonblank
                CHECK (length(btrim(
                    floor,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                )) > 0),
            CONSTRAINT units_floor_normalized
                CHECK (floor = btrim(
                    floor,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                )),
            CONSTRAINT units_unit_type_supported
                CHECK (unit_type IN (
                    'STUDIO',
                    'ONE_BEDROOM',
                    'TWO_BEDROOM',
                    'THREE_BEDROOM'
                )),
            CONSTRAINT units_status_supported
                CHECK (status IN (
                    'VACANT',
                    'RESERVED',
                    'OCCUPIED',
                    'UNDER_MAINTENANCE',
                    'CLEANING',
                    'OUT_OF_SERVICE'
                )),
            CONSTRAINT units_property_unit_number_unique
                UNIQUE (property_id, unit_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX units_property_status_idx ON app.units(property_id, status)"
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_unit_history_loss()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
            THEN
                RAISE EXCEPTION 'Unit identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER units_protect_history
        BEFORE UPDATE OR DELETE ON app.units
        FOR EACH ROW EXECUTE FUNCTION app.reject_unit_history_loss()
        """
    )
    op.execute(
        """
        CREATE TRIGGER units_reject_truncate
        BEFORE TRUNCATE ON app.units
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_unit_history_loss()
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION app.create_unit(
            p_id uuid,
            p_property_id uuid,
            p_unit_number text,
            p_floor text,
            p_unit_type text,
            p_status text,
            p_actor_id uuid
        )
        RETURNS TABLE(
            id uuid,
            property_id uuid,
            unit_number text,
            floor text,
            unit_type text,
            status text,
            version integer
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            INSERT INTO app.units AS unit (
                id,
                property_id,
                unit_number,
                floor,
                unit_type,
                status,
                created_by,
                updated_by
            )
            VALUES (
                p_id,
                p_property_id,
                btrim(
                    p_unit_number,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                ),
                btrim(
                    p_floor,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                ),
                p_unit_type,
                p_status,
                p_actor_id,
                p_actor_id
            )
            RETURNING
                unit.id,
                unit.property_id,
                unit.unit_number,
                unit.floor,
                unit.unit_type,
                unit.status,
                unit.version;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.reject_unit_history_loss() FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.create_unit(uuid, uuid, text, text, text, text, uuid) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON TABLE app.units FROM PUBLIC, prm_runtime, prm_bootstrap"
    )
    op.execute("GRANT SELECT ON TABLE app.units TO prm_runtime")
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.create_unit(uuid, uuid, text, text, text, text, uuid) TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse destructive rollback of stable Unit identity and history."""
    raise RuntimeError("Unit identity and history migration is forward-only")
