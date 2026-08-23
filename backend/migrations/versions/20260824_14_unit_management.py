"""Add the version-checked Unit source-data update boundary."""

from alembic import op

revision = "20260824_14"
down_revision = "20260823_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Expose one least-privilege, optimistic-concurrency Unit update."""
    op.execute(
        r"""
        CREATE FUNCTION app.update_unit(
            p_id uuid,
            p_unit_number text,
            p_floor text,
            p_unit_type text,
            p_status text,
            p_expected_version integer,
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
            UPDATE app.units AS unit
            SET
                unit_number = btrim(
                    p_unit_number,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                ),
                floor = btrim(
                    p_floor,
                    U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
                ),
                unit_type = p_unit_type,
                status = p_status,
                version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_id
              AND unit.version = p_expected_version
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
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "app.update_unit(uuid, text, text, text, text, integer, uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "app.update_unit(uuid, text, text, text, text, integer, uuid) TO prm_runtime"
    )


def downgrade() -> None:
    """Refuse a rollback that could strand a published Unit API contract."""
    raise RuntimeError("Unit management migration is forward-only")
