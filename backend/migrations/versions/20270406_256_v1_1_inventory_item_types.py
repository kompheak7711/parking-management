"""V1.1 part 1 (owner 2026-10-29, DL-115 (I)): the Unit inventory by Item type and place.

Owner answers of 2026-10-29 07:15 to 10:04 (image 3): Edit inventory has the columns Item type,
Item name, Where, How many and Remove. "Where" is optional and names one of the Unit's own
features, for example Bedroom 2. Furniture and Appliances are Item types; Kitchen and Bathroom are
places. Technical points decided by Claude under the owner's 2026-10-23 22:30 rule (no money).

Additive and forward-only:
1. `app.unit_inventory_items`: the lines of a V1.1 inventory record: an Item type (an ITEM_TYPE
   item of the Unit's Property), a name, an optional place (a UNIT_FEATURE item and which one, 1
   to 9) and a quantity. Append-only, like the V1-058 lines.
2. `app.unit_inventory_items_json(record)`: a record's lines in the V1.1 form. A record saved
   before V1.1 is read in the V1.1 form: Furniture is Furniture, Appliances is Appliance, the
   Kitchen group is Appliance in the Unit's kitchen and the Bathroom group is Furniture in its
   bathroom (when the Unit has one).
3. `app.record_unit_inventory_items(...)` saves a V1.1 record; the V1-058 function stays.
4. Each Unit whose current inventory was saved before V1.1 gets one new record holding the same
   items in the V1.1 form, with a `unit.inventory_updated` History event; nothing is changed or
   deleted.
5. An Item type in a Unit's current inventory cannot be removed.
"""

from alembic import op

revision = "20270406_256"
down_revision = "20270405_255"
branch_labels = None
depends_on = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

SIGNATURES = (
    "app.unit_inventory_items_json(uuid)",
    "app.record_unit_inventory_items(uuid, uuid, integer, jsonb, uuid)",
)


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.unit_inventory_items (
            record_id uuid NOT NULL REFERENCES app.unit_inventory_records(id) ON DELETE RESTRICT,
            line_number smallint NOT NULL CHECK (line_number BETWEEN 1 AND 200),
            item_type_item_id uuid NOT NULL REFERENCES app.unit_setup_items(id),
            item_name text NOT NULL,
            where_item_id uuid REFERENCES app.unit_setup_items(id),
            where_number smallint CHECK (where_number BETWEEN 1 AND 9),
            quantity integer NOT NULL,
            CONSTRAINT unit_inventory_items_name_normalized CHECK (
                item_name = btrim(item_name, {TRIM}) AND length(item_name) BETWEEN 1 AND 100
            ),
            CONSTRAINT unit_inventory_items_quantity_range CHECK (quantity BETWEEN 1 AND 999),
            CONSTRAINT unit_inventory_items_where_whole CHECK (
                (where_item_id IS NULL) = (where_number IS NULL)
            ),
            PRIMARY KEY (record_id, line_number)
        );
        CREATE UNIQUE INDEX unit_inventory_items_unique
            ON app.unit_inventory_items(
                record_id, item_type_item_id, lower(item_name),
                coalesce(where_item_id, '00000000-0000-0000-0000-000000000000'::uuid),
                coalesce(where_number, 0)
            );
        CREATE INDEX unit_inventory_items_type_idx
            ON app.unit_inventory_items(item_type_item_id);
        REVOKE ALL ON TABLE app.unit_inventory_items FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_inventory_items TO prm_runtime;
        CREATE TRIGGER unit_inventory_items_append_only
        BEFORE UPDATE OR DELETE ON app.unit_inventory_items
        FOR EACH ROW EXECUTE FUNCTION app.reject_unit_inventory_change();
        CREATE TRIGGER unit_inventory_items_reject_truncate
        BEFORE TRUNCATE ON app.unit_inventory_items
        FOR EACH STATEMENT EXECUTE FUNCTION app.reject_unit_inventory_change();

        -- A line names an Item type, and an optional place, of the Unit's own Property.
        CREATE FUNCTION app.check_unit_inventory_item() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_property_id uuid;
        BEGIN
            SELECT record.property_id INTO v_property_id
            FROM app.unit_inventory_records AS record WHERE record.id = NEW.record_id;
            PERFORM app.assert_unit_setup_item(v_property_id, 'ITEM_TYPE', NEW.item_type_item_id);
            IF NEW.where_item_id IS NOT NULL THEN
                PERFORM app.assert_unit_setup_item(
                    v_property_id, 'UNIT_FEATURE', NEW.where_item_id
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_inventory_item() FROM PUBLIC;
        CREATE TRIGGER unit_inventory_items_check
        BEFORE INSERT ON app.unit_inventory_items
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_inventory_item();

        -- The Item type of the Property with this code, or its first Item type.
        CREATE FUNCTION app.unit_item_type_for(p_property_id uuid, p_code text) RETURNS uuid
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT item.id FROM app.unit_setup_items AS item
            WHERE item.property_id = p_property_id AND item.list_kind = 'ITEM_TYPE'
              AND item.removed_at IS NULL
            ORDER BY item.code = p_code DESC, item.sort_order, item.id
            LIMIT 1
        $$;
        REVOKE ALL ON FUNCTION app.unit_item_type_for(uuid, text) FROM PUBLIC;

        -- The Unit's feature with one of these codes (the first by the Settings order), or NULL.
        CREATE FUNCTION app.unit_place_for(p_unit_id uuid, p_codes text[]) RETURNS uuid
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT item.id FROM app.unit_features AS feature
            JOIN app.unit_setup_items AS item ON item.id = feature.item_id
            WHERE feature.unit_id = p_unit_id AND item.code = ANY(p_codes)
            ORDER BY array_position(p_codes, item.code), item.sort_order, item.id
            LIMIT 1
        $$;
        REVOKE ALL ON FUNCTION app.unit_place_for(uuid, text[]) FROM PUBLIC;

        -- A record's lines in the V1.1 form, for the API and the History.
        CREATE FUNCTION app.unit_inventory_items_json(p_record_id uuid) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
            WITH record AS (
                SELECT record.id, record.unit_id, record.property_id
                FROM app.unit_inventory_records AS record WHERE record.id = p_record_id
            ),
            lines AS (
                SELECT line.item_type_item_id, line.item_name, line.where_item_id,
                       line.where_number, line.quantity
                FROM app.unit_inventory_items AS line WHERE line.record_id = p_record_id
                UNION ALL
                SELECT old.type_id, min(old.item_name),
                       old.place_id, CASE WHEN old.place_id IS NULL THEN NULL ELSE 1 END,
                       least(sum(old.quantity), 999)::integer
                FROM (
                    SELECT app.unit_item_type_for(
                               record.property_id,
                               CASE line.item_group
                                   WHEN 'FURNITURE' THEN 'FURNITURE'
                                   WHEN 'BATHROOM' THEN 'FURNITURE'
                                   ELSE 'APPLIANCE'
                               END
                           ) AS type_id,
                           CASE line.item_group
                               WHEN 'KITCHEN' THEN app.unit_place_for(
                                   record.unit_id, ARRAY['KITCHEN', 'KITCHENETTE']
                               )
                               WHEN 'BATHROOM' THEN app.unit_place_for(
                                   record.unit_id, ARRAY['BATHROOM']
                               )
                           END AS place_id,
                           line.item_name, line.quantity
                    FROM app.unit_inventory_lines AS line, record
                    WHERE line.record_id = p_record_id
                ) AS old
                GROUP BY old.type_id, lower(old.item_name), old.place_id
            )
            SELECT coalesce(
                jsonb_agg(
                    jsonb_build_object(
                        'item_type_item_id', lines.item_type_item_id,
                        'item_name', lines.item_name,
                        'where_item_id', lines.where_item_id,
                        'where_number', lines.where_number,
                        'quantity', lines.quantity
                    )
                    ORDER BY kind.sort_order, lower(lines.item_name), place.sort_order NULLS FIRST,
                             lines.where_number NULLS FIRST
                ),
                '[]'::jsonb
            )
            FROM lines
            JOIN app.unit_setup_items AS kind ON kind.id = lines.item_type_item_id
            LEFT JOIN app.unit_setup_items AS place ON place.id = lines.where_item_id
        $$;

        CREATE FUNCTION app.record_unit_inventory_items(
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
                    FROM jsonb_to_recordset(p_lines) AS given(
                        item_type_item_id uuid, item_name text, where_item_id uuid,
                        where_number integer, quantity integer
                    )
                    WHERE given.item_type_item_id IS NULL OR given.item_name IS NULL
                       OR given.quantity IS NULL
                )
            THEN
                RAISE EXCEPTION 'Unit inventory lines must be a list of at most 200 whole items'
                    USING ERRCODE = '22023';
            END IF;
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
            INSERT INTO app.unit_inventory_items (
                record_id, line_number, item_type_item_id, item_name, where_item_id,
                where_number, quantity
            )
            SELECT v_record.id, given.ordinality, given.item_type_item_id,
                   btrim(given.item_name, {TRIM}), given.where_item_id, given.where_number,
                   given.quantity
            FROM ROWS FROM (
                jsonb_to_recordset(p_lines) AS (
                    item_type_item_id uuid, item_name text, where_item_id uuid,
                    where_number integer, quantity integer
                )
            ) WITH ORDINALITY AS given(
                item_type_item_id, item_name, where_item_id, where_number, quantity, ordinality
            );
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
                    'lines', app.unit_inventory_items_json(v_previous.id)
                ) END,
                jsonb_build_object(
                    'record_number', v_record.record_number,
                    'lines', app.unit_inventory_items_json(v_record.id)
                ),
                v_event_id, 'API', 'SUCCEEDED', p_unit_id
            );
            RETURN QUERY SELECT v_record.id, v_record.unit_id, v_record.property_id,
                v_record.record_number, v_record.recorded_at, v_record.recorded_by,
                app.unit_inventory_items_json(v_record.id);
        END;
        $$;

        CREATE OR REPLACE FUNCTION app.unit_setup_item_in_use(p_item app.unit_setup_items)
        RETURNS boolean
        LANGUAGE sql
        SET search_path = pg_catalog
        AS $$
            SELECT CASE p_item.list_kind
                WHEN 'UNIT_TYPE' THEN EXISTS (
                    SELECT 1 FROM app.units AS unit
                    WHERE unit.property_id = p_item.property_id AND unit.unit_type = p_item.code
                )
                WHEN 'FLOOR' THEN EXISTS (
                    SELECT 1 FROM app.units AS unit WHERE unit.floor_item_id = p_item.id
                )
                WHEN 'VIEW' THEN EXISTS (
                    SELECT 1 FROM app.units AS unit WHERE unit.view_item_id = p_item.id
                )
                WHEN 'KITCHEN' THEN EXISTS (
                    SELECT 1 FROM app.units AS unit WHERE unit.kitchen_item_id = p_item.id
                )
                WHEN 'ROOM_FEATURE' THEN EXISTS (
                    SELECT 1 FROM app.unit_room_features AS feature
                    WHERE feature.item_id = p_item.id
                )
                WHEN 'FEATURE_TYPE' THEN EXISTS (
                    SELECT 1 FROM app.unit_setup_items AS feature
                    WHERE feature.feature_type_item_id = p_item.id
                      AND feature.removed_at IS NULL
                )
                WHEN 'UNIT_FEATURE' THEN EXISTS (
                    SELECT 1 FROM app.unit_features AS feature WHERE feature.item_id = p_item.id
                )
                -- An Item type in a Unit's current inventory (its latest record).
                WHEN 'ITEM_TYPE' THEN EXISTS (
                    SELECT 1 FROM app.unit_inventory_items AS line
                    JOIN app.unit_inventory_records AS record ON record.id = line.record_id
                    WHERE line.item_type_item_id = p_item.id
                      AND record.record_number = (
                        SELECT max(latest.record_number) FROM app.unit_inventory_records AS latest
                        WHERE latest.unit_id = record.unit_id
                      )
                )
                ELSE false
            END
        $$;
        """
    )
    # Each Unit whose current inventory was saved before V1.1 gets one record in the V1.1 form.
    op.execute(
        """
        DO $$
        DECLARE
            v_old record;
            v_id uuid;
            v_event_id uuid;
        BEGIN
            FOR v_old IN
                SELECT latest.* FROM app.unit_inventory_records AS latest
                WHERE latest.record_number = (
                    SELECT max(other.record_number) FROM app.unit_inventory_records AS other
                    WHERE other.unit_id = latest.unit_id
                )
                AND EXISTS (
                    SELECT 1 FROM app.unit_inventory_lines AS line WHERE line.record_id = latest.id
                )
                ORDER BY latest.unit_id
            LOOP
                v_id := gen_random_uuid();
                v_event_id := gen_random_uuid();
                INSERT INTO app.unit_inventory_records (
                    id, unit_id, property_id, record_number, recorded_by
                ) VALUES (
                    v_id, v_old.unit_id, v_old.property_id, v_old.record_number + 1,
                    v_old.recorded_by
                );
                INSERT INTO app.unit_inventory_items (
                    record_id, line_number, item_type_item_id, item_name, where_item_id,
                    where_number, quantity
                )
                SELECT v_id, given.ordinality, (given.value ->> 'item_type_item_id')::uuid,
                       given.value ->> 'item_name', (given.value ->> 'where_item_id')::uuid,
                       (given.value ->> 'where_number')::smallint,
                       (given.value ->> 'quantity')::integer
                FROM jsonb_array_elements(app.unit_inventory_items_json(v_old.id))
                    WITH ORDINALITY AS given(value, ordinality);
                INSERT INTO app.audit_events (
                    id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                    reason, property_id, previous_state, resulting_state, correlation_id,
                    source, outcome, unit_id
                ) VALUES (
                    v_event_id, statement_timestamp(),
                    timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                    v_old.recorded_by, 'unit.inventory_updated', 'unit', v_old.unit_id,
                    'V1.1: the same items, now by Item type and place (DL-115 (I))',
                    v_old.property_id,
                    jsonb_build_object(
                        'record_number', v_old.record_number,
                        'lines', app.unit_inventory_lines_json(v_old.id)
                    ),
                    jsonb_build_object(
                        'record_number', v_old.record_number + 1,
                        'lines', app.unit_inventory_items_json(v_id)
                    ),
                    v_event_id, 'ADMINISTRATIVE', 'SUCCEEDED', v_old.unit_id
                );
            END LOOP;
        END $$;
        """
    )
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Forward-only: removing the V1.1 lines would lose the inventory history."""
    raise RuntimeError("V1.1 inventory item types migration is forward-only")
