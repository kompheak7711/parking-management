"""Unit inventory with dated history (V1-058 R2b; DL-078 answer 2).

DL-078 answer 2 (owner, 2026-10-20): a list of the items in the Unit, each with a quantity, grouped
as Furniture, Appliances, Kitchen and Bathroom. Each change is dated and kept in History. The
inventory charges nothing by itself. Technical points decided by Claude under the owner's
2026-10-23 22:30 rule.

- `app.unit_inventory_records`: one row per save of a Unit's inventory, numbered 1, 2, 3 for the
  Unit, with the time and the person. The latest record is the current inventory.
- `app.unit_inventory_lines`: the items of one record (group, name, quantity 1 to 999). An item
  left out of a save is no longer in the Unit.
- Both tables are append-only. `app.record_unit_inventory` is the one way to save: it checks the
  record number the person saw, writes the new record and its lines, and writes a
  `unit.inventory_updated` event to the Unit's audit history with the previous and new items.
"""

from alembic import op

revision = "20270217_205"
down_revision = "20270216_204"
branch_labels = None
depends_on = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

SIGNATURE = "app.record_unit_inventory(uuid, uuid, integer, jsonb, uuid)"


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.unit_inventory_records (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            record_number integer NOT NULL CHECK (record_number > 0),
            recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            recorded_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT unit_inventory_records_number_unique UNIQUE (unit_id, record_number)
        );
        REVOKE ALL ON TABLE app.unit_inventory_records FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_inventory_records TO prm_runtime;

        CREATE TABLE app.unit_inventory_lines (
            record_id uuid NOT NULL REFERENCES app.unit_inventory_records(id) ON DELETE RESTRICT,
            item_group text NOT NULL,
            item_name text NOT NULL,
            quantity integer NOT NULL,
            CONSTRAINT unit_inventory_lines_group_supported CHECK (
                item_group IN ('FURNITURE', 'APPLIANCES', 'KITCHEN', 'BATHROOM')
            ),
            CONSTRAINT unit_inventory_lines_name_normalized CHECK (
                item_name = btrim(item_name, {TRIM}) AND length(item_name) BETWEEN 1 AND 100
            ),
            CONSTRAINT unit_inventory_lines_quantity_range CHECK (quantity BETWEEN 1 AND 999),
            PRIMARY KEY (record_id, item_group, item_name)
        );
        CREATE UNIQUE INDEX unit_inventory_lines_name_unique
            ON app.unit_inventory_lines(record_id, item_group, lower(item_name));
        REVOKE ALL ON TABLE app.unit_inventory_lines FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_inventory_lines TO prm_runtime;

        CREATE FUNCTION app.reject_unit_inventory_change() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'Unit inventory history is append-only' USING ERRCODE = '55000';
        END;
        $$;
        REVOKE ALL ON FUNCTION app.reject_unit_inventory_change() FROM PUBLIC;
        CREATE TRIGGER unit_inventory_records_append_only
        BEFORE UPDATE OR DELETE ON app.unit_inventory_records
        FOR EACH ROW EXECUTE FUNCTION app.reject_unit_inventory_change();
        CREATE TRIGGER unit_inventory_records_reject_truncate
        BEFORE TRUNCATE ON app.unit_inventory_records
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_unit_inventory_change();
        CREATE TRIGGER unit_inventory_lines_append_only
        BEFORE UPDATE OR DELETE ON app.unit_inventory_lines
        FOR EACH ROW EXECUTE FUNCTION app.reject_unit_inventory_change();
        CREATE TRIGGER unit_inventory_lines_reject_truncate
        BEFORE TRUNCATE ON app.unit_inventory_lines
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_unit_inventory_change();

        -- The items of one record in a fixed order, for the audit history and the API.
        CREATE FUNCTION app.unit_inventory_lines_json(p_record_id uuid) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT coalesce(
                jsonb_agg(
                    jsonb_build_object(
                        'item_group', line.item_group,
                        'item_name', line.item_name,
                        'quantity', line.quantity
                    )
                    ORDER BY array_position(
                        ARRAY['FURNITURE', 'APPLIANCES', 'KITCHEN', 'BATHROOM'], line.item_group
                    ), lower(line.item_name)
                ),
                '[]'::jsonb
            )
            FROM app.unit_inventory_lines AS line
            WHERE line.record_id = p_record_id
        $$;
        REVOKE ALL ON FUNCTION app.unit_inventory_lines_json(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.unit_inventory_lines_json(uuid) TO prm_runtime;

        CREATE FUNCTION app.record_unit_inventory(
            p_id uuid,
            p_unit_id uuid,
            p_expected_record_number integer,
            p_lines jsonb,
            p_actor_id uuid
        ) RETURNS TABLE (
            record_id uuid,
            unit_id uuid,
            property_id uuid,
            record_number integer,
            recorded_at timestamptz,
            recorded_by uuid,
            lines jsonb
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_property_id uuid;
            v_previous app.unit_inventory_records%ROWTYPE;
            v_record app.unit_inventory_records%ROWTYPE;
            v_event_id uuid := gen_random_uuid();
        BEGIN
            IF p_expected_record_number IS NULL
                OR jsonb_typeof(p_lines) IS DISTINCT FROM 'array'
                OR jsonb_array_length(p_lines) > 200
                OR EXISTS (
                    SELECT 1
                    FROM jsonb_to_recordset(p_lines)
                        AS given(item_group text, item_name text, quantity integer)
                    WHERE given.item_group IS NULL OR given.item_name IS NULL
                       OR given.quantity IS NULL
                )
            THEN
                RAISE EXCEPTION 'Unit inventory lines must be a list of at most 200 whole items'
                    USING ERRCODE = '22023';
            END IF;
            -- The Unit row lock puts saves of one Unit in a line without blocking new rows
            -- that refer to the Unit.
            SELECT unit.property_id INTO v_property_id FROM app.units AS unit
            WHERE unit.id = p_unit_id FOR NO KEY UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unit was not found' USING ERRCODE = 'P0002';
            END IF;
            SELECT record.* INTO v_previous FROM app.unit_inventory_records AS record
            WHERE record.unit_id = p_unit_id
            ORDER BY record.record_number DESC
            LIMIT 1;
            IF coalesce(v_previous.record_number, 0) IS DISTINCT FROM p_expected_record_number THEN
                RETURN;
            END IF;
            INSERT INTO app.unit_inventory_records AS record (
                id, unit_id, property_id, record_number, recorded_by
            ) VALUES (
                p_id, p_unit_id, v_property_id, coalesce(v_previous.record_number, 0) + 1,
                p_actor_id
            ) RETURNING record.* INTO v_record;
            INSERT INTO app.unit_inventory_lines (record_id, item_group, item_name, quantity)
            SELECT v_record.id, given.item_group, btrim(given.item_name, {TRIM}), given.quantity
            FROM jsonb_to_recordset(p_lines)
                AS given(item_group text, item_name text, quantity integer);
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                reason, property_id, previous_state, resulting_state, correlation_id, source,
                outcome, unit_id
            ) VALUES (
                v_event_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, 'unit.inventory_updated', 'unit', p_unit_id,
                'Unit inventory saved', v_property_id,
                CASE WHEN v_previous.id IS NULL THEN NULL ELSE jsonb_build_object(
                    'record_number', v_previous.record_number,
                    'lines', app.unit_inventory_lines_json(v_previous.id)
                ) END,
                jsonb_build_object(
                    'record_number', v_record.record_number,
                    'lines', app.unit_inventory_lines_json(v_record.id)
                ),
                v_event_id, 'API', 'SUCCEEDED', p_unit_id
            );
            RETURN QUERY SELECT v_record.id, v_record.unit_id, v_record.property_id,
                v_record.record_number, v_record.recorded_at, v_record.recorded_by,
                app.unit_inventory_lines_json(v_record.id);
        END;
        $$;
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO prm_runtime")


def downgrade() -> None:
    """Forward-only: removing the tables would lose the inventory history."""
    raise RuntimeError("Unit inventory migration is forward-only")
