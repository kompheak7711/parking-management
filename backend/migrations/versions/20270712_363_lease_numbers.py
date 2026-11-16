"""UI v81 (owner 08/11/2026 08:14): every Lease gets a Lease number.

The owner's rule: Unit number + "L" + a 4-digit running number, e.g. U101L0026 (design v81).
One running number per Property. A new Lease takes the next number when it is drafted (design
v81, owner 21/10/2026); the Leases already recorded are numbered in order of Start Date (then
the day they were drafted). The number is written once and never changes, even if the Unit is
renamed later; a cancelled draft keeps its number, so the numbers may have gaps.

Additive only: two new tables (the numbers, append-only, and one counter per Property) and an
AFTER INSERT trigger on app.leases. No existing row is changed; the existing Leases only get
their number added.

Revision ID: 20270712_363
Revises: 20270711_362
"""

from __future__ import annotations

from alembic import op

revision = "20270712_363"
down_revision = "20270711_362"
branch_labels = None
depends_on = None

TABLES_SQL = """
    CREATE TABLE app.lease_numbers (
        lease_id uuid PRIMARY KEY REFERENCES app.leases(id) ON DELETE RESTRICT,
        property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
        running_number integer NOT NULL CHECK (running_number > 0),
        lease_number text NOT NULL CHECK (lease_number ~ '^.+L[0-9]{4,}$'),
        assigned_at timestamptz NOT NULL DEFAULT statement_timestamp(),
        CONSTRAINT lease_numbers_running_unique UNIQUE (property_id, running_number),
        CONSTRAINT lease_numbers_number_unique UNIQUE (property_id, lease_number)
    );
    CREATE TABLE app.lease_number_counters (
        property_id uuid PRIMARY KEY REFERENCES app.properties(id) ON DELETE RESTRICT,
        last_number integer NOT NULL CHECK (last_number > 0)
    );
"""

GUARDS_SQL = """
    CREATE FUNCTION app.reject_lease_number_change()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
    AS $$
    BEGIN
        RAISE EXCEPTION 'a Lease number is written once and never changed'
            USING ERRCODE = 'integrity_constraint_violation';
    END;
    $$;
    CREATE TRIGGER lease_numbers_reject_mutation
    BEFORE UPDATE OR DELETE ON app.lease_numbers
    FOR EACH ROW EXECUTE FUNCTION app.reject_lease_number_change();
    CREATE TRIGGER lease_numbers_reject_truncate
    BEFORE TRUNCATE ON app.lease_numbers
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_number_change();

    CREATE FUNCTION app.check_lease_number_counter()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog
    AS $$
    BEGIN
        IF TG_OP = 'UPDATE' AND NEW.property_id = OLD.property_id
           AND NEW.last_number = OLD.last_number + 1 THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'a Lease number counter only moves up by one'
            USING ERRCODE = 'integrity_constraint_violation';
    END;
    $$;
    CREATE TRIGGER lease_number_counters_only_up
    BEFORE UPDATE OR DELETE ON app.lease_number_counters
    FOR EACH ROW EXECUTE FUNCTION app.check_lease_number_counter();
    CREATE TRIGGER lease_number_counters_reject_truncate
    BEFORE TRUNCATE ON app.lease_number_counters
    FOR EACH STATEMENT EXECUTE FUNCTION app.reject_lease_number_change();
"""

FORMAT_SQL = """
    CREATE FUNCTION app.lease_number_text(p_unit_number text, p_running integer)
    RETURNS text
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog
    AS $$
        SELECT p_unit_number || 'L' ||
            CASE WHEN p_running < 10000 THEN lpad(p_running::text, 4, '0')
                 ELSE p_running::text END
    $$;
"""

ASSIGN_SQL = """
    CREATE FUNCTION app.assign_lease_number()
    RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
        v_property uuid;
        v_unit text;
        v_next integer;
    BEGIN
        SELECT unit.property_id, unit.unit_number INTO STRICT v_property, v_unit
        FROM app.units AS unit WHERE unit.id = NEW.unit_id;
        -- The counter row is locked by the upsert, so two drafts never share a number.
        INSERT INTO app.lease_number_counters AS counter (property_id, last_number)
        VALUES (v_property, 1)
        ON CONFLICT (property_id) DO UPDATE SET last_number = counter.last_number + 1
        RETURNING counter.last_number INTO v_next;
        INSERT INTO app.lease_numbers (lease_id, property_id, running_number, lease_number)
        VALUES (NEW.id, v_property, v_next, app.lease_number_text(v_unit, v_next));
        RETURN NULL;
    END;
    $$;
    CREATE TRIGGER leases_assign_number
    AFTER INSERT ON app.leases
    FOR EACH ROW EXECUTE FUNCTION app.assign_lease_number();
"""

# The Leases recorded before this migration, in order of Start Date (a draft without one last),
# then the day they were drafted. Only rows are added; app.leases is not touched.
BACKFILL_SQL = """
    INSERT INTO app.lease_numbers (lease_id, property_id, running_number, lease_number)
    SELECT ordered.id, ordered.property_id, ordered.running,
           app.lease_number_text(ordered.unit_number, ordered.running)
    FROM (
        SELECT lease.id, unit.property_id, unit.unit_number,
               row_number() OVER (
                   PARTITION BY unit.property_id
                   ORDER BY lease.start_date NULLS LAST, lease.created_at, lease.id
               )::integer AS running
        FROM app.leases AS lease
        JOIN app.units AS unit ON unit.id = lease.unit_id
    ) AS ordered;
    INSERT INTO app.lease_number_counters (property_id, last_number)
    SELECT property_id, max(running_number) FROM app.lease_numbers GROUP BY property_id;
"""

GRANTS_SQL = """
    REVOKE ALL ON app.lease_numbers, app.lease_number_counters FROM PUBLIC;
    GRANT SELECT ON app.lease_numbers TO prm_runtime;
    REVOKE ALL ON FUNCTION app.assign_lease_number() FROM PUBLIC;
    REVOKE ALL ON FUNCTION app.reject_lease_number_change() FROM PUBLIC;
    REVOKE ALL ON FUNCTION app.check_lease_number_counter() FROM PUBLIC;
    REVOKE ALL ON FUNCTION app.lease_number_text(text, integer) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(TABLES_SQL)
    op.execute(FORMAT_SQL)
    op.execute(BACKFILL_SQL)
    op.execute(GUARDS_SQL)
    op.execute(ASSIGN_SQL)
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    """Refuse rollback; Lease numbers are written once."""
    raise RuntimeError("UI v81 Lease number migration is forward-only")
