# ruff: noqa: E501
"""V1.1 part 1 (owner 2026-10-29, DL-115 (I)): Unit features, Feature types and Item types.

Owner answers of 2026-10-29 07:15 to 10:04: a **Unit feature** is what the place is or has built
in (it stays and does not move); each Unit feature has a **Feature type**. A shop or office lists
only what it has, for example "Main room x1". **Item types** (Furniture, Appliance, ...) group the
Unit inventory (used by the inventory part). Technical points decided by Claude under the owner's
2026-10-23 22:30 rule (no money).

Additive and forward-only:
1. `app.unit_setup_items` takes three more lists: FEATURE_TYPE, UNIT_FEATURE and ITEM_TYPE, and
   the column `feature_type_item_id`: a UNIT_FEATURE item must name a FEATURE_TYPE item of its
   Property; no other item may name one.
2. `app.unit_features`: how many of each Unit feature a Unit has (1 to 9). It is changed only by
   `app.set_unit_features(unit, version, features, actor)`, which moves the Unit version on; the
   application writes the change to the Unit's audit history.
3. `app.unit_feature_counts(unit)`: a Unit's features as a JSON list of {item_id, count}.
4. A Unit feature or Feature type in use cannot be removed (`app.unit_setup_item_in_use`).
5. Each Property gets the default Feature types, Unit features and Item types (Khmer names need
   the native check). The old Kitchens and Room features fold into Unit features: each of their
   items gets a Unit feature with the same code and names, and each Unit's bedrooms, bathrooms,
   Kitchen and Room features are carried into its Unit features. The old columns and lists stay
   as they were (nothing is dropped); the screens no longer offer them.
6. New overloads of `app.create_unit_setup_item` and `app.update_unit_setup_item` take the
   Feature type; the earlier ones stay.
"""

from alembic import op

revision = "20270405_255"
down_revision = "20270404_254"
branch_labels = None
depends_on = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

ITEM_RESULT = """RETURNS TABLE (
            id uuid,
            property_id uuid,
            list_kind text,
            code text,
            name_en text,
            name_km text,
            sort_order integer,
            removed_at timestamptz,
            version integer,
            feature_type_item_id uuid
        )"""

SIGNATURES = (
    "app.create_unit_setup_item(uuid, uuid, text, text, text, integer, uuid, uuid)",
    "app.update_unit_setup_item(uuid, text, text, integer, integer, uuid, uuid)",
    "app.set_unit_features(uuid, integer, jsonb, uuid)",
    "app.unit_feature_counts(uuid)",
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.unit_setup_items
            DROP CONSTRAINT unit_setup_items_kind_supported,
            ADD CONSTRAINT unit_setup_items_kind_supported CHECK (
                list_kind IN (
                    'FLOOR', 'UNIT_TYPE', 'VIEW', 'KITCHEN', 'ROOM_FEATURE',
                    'FEATURE_TYPE', 'UNIT_FEATURE', 'ITEM_TYPE'
                )
            ),
            ADD COLUMN feature_type_item_id uuid REFERENCES app.unit_setup_items(id),
            ADD CONSTRAINT unit_setup_items_feature_type_only_on_features CHECK (
                (list_kind = 'UNIT_FEATURE') = (feature_type_item_id IS NOT NULL)
            );
        CREATE INDEX unit_setup_items_feature_type_idx
            ON app.unit_setup_items(feature_type_item_id)
            WHERE feature_type_item_id IS NOT NULL;

        CREATE TABLE app.unit_features (
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            item_id uuid NOT NULL REFERENCES app.unit_setup_items(id) ON DELETE RESTRICT,
            feature_count smallint NOT NULL
                CONSTRAINT unit_features_count_range CHECK (feature_count BETWEEN 1 AND 9),
            PRIMARY KEY (unit_id, item_id)
        );
        CREATE INDEX unit_features_item_idx ON app.unit_features(item_id);
        REVOKE ALL ON TABLE app.unit_features FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_features TO prm_runtime;

        -- A Unit feature names a Feature type of its own Property that may be picked now.
        CREATE FUNCTION app.check_unit_feature_type() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.list_kind = 'UNIT_FEATURE' AND (
                TG_OP = 'INSERT'
                OR NEW.feature_type_item_id IS DISTINCT FROM OLD.feature_type_item_id
            ) THEN
                PERFORM app.assert_unit_setup_item(
                    NEW.property_id, 'FEATURE_TYPE', NEW.feature_type_item_id
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_feature_type() FROM PUBLIC;
        CREATE TRIGGER unit_setup_items_check_feature_type
        BEFORE INSERT OR UPDATE ON app.unit_setup_items
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_feature_type();

        -- A Unit's feature row names a Unit feature of the Unit's Property; a new or changed
        -- pick must not be removed. Rows are written only by app.set_unit_features.
        CREATE FUNCTION app.check_unit_feature_row() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.item_id IS DISTINCT FROM OLD.item_id
                OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
            THEN
                PERFORM app.assert_unit_setup_item(
                    (SELECT unit.property_id FROM app.units AS unit WHERE unit.id = NEW.unit_id),
                    'UNIT_FEATURE',
                    NEW.item_id
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_feature_row() FROM PUBLIC;
        CREATE TRIGGER unit_features_check
        BEFORE INSERT OR UPDATE ON app.unit_features
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_feature_row();

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
                ELSE false
            END
        $$;

        CREATE OR REPLACE FUNCTION app.unit_setup_item_state(p_item app.unit_setup_items)
        RETURNS jsonb
        LANGUAGE sql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $$
            SELECT jsonb_build_object(
                'item_id', p_item.id,
                'list_kind', p_item.list_kind,
                'code', p_item.code,
                'name_en', p_item.name_en,
                'name_km', p_item.name_km,
                'sort_order', p_item.sort_order,
                'removed', p_item.removed_at IS NOT NULL,
                'version', p_item.version
            ) || CASE WHEN p_item.feature_type_item_id IS NULL THEN '{}'::jsonb
                      ELSE jsonb_build_object('feature_type_item_id', p_item.feature_type_item_id)
                 END
        $$;

        CREATE FUNCTION app.unit_feature_counts(p_unit_id uuid) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT coalesce(
                jsonb_agg(
                    jsonb_build_object('item_id', feature.item_id, 'count', feature.feature_count)
                    ORDER BY feature.item_id
                ),
                '[]'::jsonb
            )
            FROM app.unit_features AS feature
            WHERE feature.unit_id = p_unit_id
        $$;
        """
    )
    op.execute(
        rf"""
        CREATE FUNCTION app.create_unit_setup_item(
            p_id uuid,
            p_property_id uuid,
            p_list_kind text,
            p_name_en text,
            p_name_km text,
            p_sort_order integer,
            p_actor_id uuid,
            p_feature_type_item_id uuid
        ) {ITEM_RESULT}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_item app.unit_setup_items%ROWTYPE;
            v_none app.unit_setup_items%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('unit-setup:' || p_property_id::text || ':' || p_list_kind, 0)
            );
            INSERT INTO app.unit_setup_items AS item (
                id, property_id, list_kind, code, name_en, name_km, sort_order,
                created_by, updated_by, feature_type_item_id
            ) VALUES (
                p_id, p_property_id, p_list_kind,
                app.next_unit_setup_code(p_property_id, p_list_kind, btrim(p_name_en, {TRIM})),
                btrim(p_name_en, {TRIM}),
                nullif(btrim(p_name_km, {TRIM}), ''),
                p_sort_order, p_actor_id, p_actor_id, p_feature_type_item_id
            ) RETURNING item.* INTO v_item;
            PERFORM app.audit_unit_setup_item(
                'unit_setup_item.created', p_actor_id, v_none, v_item
            );
            RETURN QUERY SELECT v_item.id, v_item.property_id, v_item.list_kind, v_item.code,
                v_item.name_en, v_item.name_km, v_item.sort_order, v_item.removed_at,
                v_item.version, v_item.feature_type_item_id;
        END;
        $$;

        CREATE FUNCTION app.update_unit_setup_item(
            p_id uuid,
            p_name_en text,
            p_name_km text,
            p_sort_order integer,
            p_expected_version integer,
            p_actor_id uuid,
            p_feature_type_item_id uuid
        ) {ITEM_RESULT}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_previous app.unit_setup_items%ROWTYPE;
            v_item app.unit_setup_items%ROWTYPE;
        BEGIN
            SELECT item.* INTO v_previous FROM app.unit_setup_items AS item
            WHERE item.id = p_id FOR UPDATE;
            IF NOT FOUND OR v_previous.version <> p_expected_version THEN
                RETURN;
            END IF;
            IF v_previous.removed_at IS NOT NULL THEN
                RAISE EXCEPTION 'A removed Unit setup item cannot be changed'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE app.unit_setup_items AS item
            SET name_en = btrim(p_name_en, {TRIM}),
                name_km = nullif(btrim(p_name_km, {TRIM}), ''),
                sort_order = p_sort_order,
                feature_type_item_id = CASE
                    WHEN item.list_kind = 'UNIT_FEATURE'
                        THEN coalesce(p_feature_type_item_id, item.feature_type_item_id)
                    ELSE p_feature_type_item_id
                END,
                version = item.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE item.id = p_id
            RETURNING item.* INTO v_item;
            PERFORM app.audit_unit_setup_item(
                'unit_setup_item.updated', p_actor_id, v_previous, v_item
            );
            RETURN QUERY SELECT v_item.id, v_item.property_id, v_item.list_kind, v_item.code,
                v_item.name_en, v_item.name_km, v_item.sort_order, v_item.removed_at,
                v_item.version, v_item.feature_type_item_id;
        END;
        $$;

        -- Sets a Unit's features at the expected Unit version: p_features is a JSON list of
        -- {{"item_id": uuid, "count": 1..9}}, each feature once, at most 50. Answers the new
        -- version, or NULL when the Unit is not there or its version moved on.
        CREATE FUNCTION app.set_unit_features(
            p_unit_id uuid,
            p_expected_version integer,
            p_features jsonb,
            p_actor_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
        BEGIN
            IF p_features IS NULL OR jsonb_typeof(p_features) <> 'array'
                OR jsonb_array_length(p_features) > 50
                OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(p_features) AS given(value)
                    WHERE jsonb_typeof(given.value) <> 'object'
                       OR jsonb_typeof(given.value -> 'item_id') <> 'string'
                       OR jsonb_typeof(given.value -> 'count') <> 'number'
                       OR (given.value ->> 'count') !~ '^[1-9]$'
                       OR (given.value ->> 'item_id') !~
                          '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
                )
                OR jsonb_array_length(p_features) <> (
                    SELECT count(DISTINCT given.value ->> 'item_id')
                    FROM jsonb_array_elements(p_features) AS given(value)
                )
            THEN
                RAISE EXCEPTION 'Unit features are invalid' USING ERRCODE = '22023';
            END IF;
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_unit_id FOR UPDATE;
            IF NOT FOUND OR v_unit.version <> p_expected_version THEN
                RETURN NULL;
            END IF;
            UPDATE app.units AS unit
            SET version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_unit_id;
            DELETE FROM app.unit_features AS feature
            WHERE feature.unit_id = p_unit_id
              AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(p_features) AS given(value)
                WHERE (given.value ->> 'item_id')::uuid = feature.item_id
              );
            INSERT INTO app.unit_features AS feature (unit_id, item_id, feature_count)
            SELECT p_unit_id, (given.value ->> 'item_id')::uuid,
                   (given.value ->> 'count')::smallint
            FROM jsonb_array_elements(p_features) AS given(value)
            ON CONFLICT (unit_id, item_id) DO UPDATE
                SET feature_count = EXCLUDED.feature_count
                WHERE feature.feature_count IS DISTINCT FROM EXCLUDED.feature_count;
            RETURN v_unit.version + 1;
        END;
        $$;
        """
    )
    op.execute(
        """
        -- The default lists of a Property. Khmer names need the native check.
        CREATE OR REPLACE FUNCTION app.seed_unit_setup_items(p_property_id uuid, p_actor_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_item app.unit_setup_items%ROWTYPE;
        BEGIN
            FOR v_item IN
            INSERT INTO app.unit_setup_items (
                id, property_id, list_kind, code, name_en, name_km, sort_order,
                created_by, updated_by
            )
            SELECT gen_random_uuid(), p_property_id, defaults.list_kind, defaults.code,
                   defaults.name_en, defaults.name_km, defaults.sort_order,
                   p_actor_id, p_actor_id
            FROM (VALUES
                ('UNIT_TYPE', 'STUDIO', 'Studio', 'ស្ទូឌីយោ', 10),
                ('UNIT_TYPE', 'ONE_BEDROOM', '1 bedroom', 'បន្ទប់គេង ១', 20),
                ('UNIT_TYPE', 'TWO_BEDROOM', '2 bedrooms', 'បន្ទប់គេង ២', 30),
                ('UNIT_TYPE', 'THREE_BEDROOM', '3 bedrooms', 'បន្ទប់គេង ៣', 40),
                ('ROOM_FEATURE', 'BALCONY', 'Balcony', 'រានហាល', 10),
                ('FEATURE_TYPE', 'ROOM', 'Room', 'បន្ទប់', 10),
                ('FEATURE_TYPE', 'BATHROOM', 'Bathroom', 'បន្ទប់ទឹក', 20),
                ('FEATURE_TYPE', 'KITCHEN', 'Kitchen', 'ផ្ទះបាយ', 30),
                ('FEATURE_TYPE', 'OUTDOOR', 'Outdoor', 'ខាងក្រៅ', 40),
                ('FEATURE_TYPE', 'BUILT_IN', 'Built-in', 'ភ្ជាប់ជាប់', 50),
                ('ITEM_TYPE', 'FURNITURE', 'Furniture', 'គ្រឿងសង្ហារឹម', 10),
                ('ITEM_TYPE', 'APPLIANCE', 'Appliance', 'គ្រឿងប្រើប្រាស់អគ្គិសនី', 20),
                ('ITEM_TYPE', 'ELECTRONICS', 'Electronics', 'គ្រឿងអេឡិចត្រូនិក', 30),
                ('ITEM_TYPE', 'LINEN', 'Linen', 'ក្រណាត់', 40),
                ('ITEM_TYPE', 'KEYS', 'Keys and remotes', 'សោ និងតេឡេបញ្ជា', 50)
            ) AS defaults(list_kind, code, name_en, name_km, sort_order)
            ON CONFLICT (property_id, list_kind, code) DO NOTHING
            RETURNING *
            LOOP
                PERFORM app.audit_unit_setup_item(
                    'unit_setup_item.created', p_actor_id, NULL::app.unit_setup_items, v_item
                );
            END LOOP;
            FOR v_item IN
            INSERT INTO app.unit_setup_items (
                id, property_id, list_kind, code, name_en, name_km, sort_order,
                created_by, updated_by, feature_type_item_id
            )
            SELECT gen_random_uuid(), p_property_id, 'UNIT_FEATURE', defaults.code,
                   defaults.name_en, defaults.name_km, defaults.sort_order,
                   p_actor_id, p_actor_id, kind.id
            FROM (VALUES
                ('BEDROOM', 'Bedroom', 'បន្ទប់គេង', 10, 'ROOM'),
                ('LIVING_ROOM', 'Living room', 'បន្ទប់ទទួលភ្ញៀវ', 20, 'ROOM'),
                ('MAIN_ROOM', 'Main room (shop or office)', 'បន្ទប់ធំ (ហាង ឬការិយាល័យ)', 30, 'ROOM'),
                ('BATHROOM', 'Bathroom', 'បន្ទប់ទឹក', 40, 'BATHROOM'),
                ('KITCHEN', 'Kitchen', 'ផ្ទះបាយ', 50, 'KITCHEN'),
                ('KITCHENETTE', 'Kitchenette', 'ផ្ទះបាយតូច', 60, 'KITCHEN'),
                ('BALCONY', 'Balcony', 'រានហាល', 70, 'OUTDOOR'),
                ('BUILT_IN_WARDROBE', 'Built-in wardrobe', 'ទូខោអាវភ្ជាប់ជញ្ជាំង', 80, 'BUILT_IN'),
                ('WALL_AIR_CONDITIONER', 'Wall air conditioner', 'ម៉ាស៊ីនត្រជាក់ភ្ជាប់ជញ្ជាំង', 90, 'BUILT_IN')
            ) AS defaults(code, name_en, name_km, sort_order, type_code)
            JOIN app.unit_setup_items AS kind
              ON kind.property_id = p_property_id AND kind.list_kind = 'FEATURE_TYPE'
             AND kind.code = defaults.type_code
            ON CONFLICT (property_id, list_kind, code) DO NOTHING
            RETURNING *
            LOOP
                PERFORM app.audit_unit_setup_item(
                    'unit_setup_item.created', p_actor_id, NULL::app.unit_setup_items, v_item
                );
            END LOOP;
        END;
        $$;
        """
    )
    # The Properties that already exist: the new defaults, then a Unit feature for each old
    # Kitchen and Room feature item (same code and names; Balcony and Terrace are Outdoor, other
    # Room features Built-in, Kitchens Kitchen), then each Unit's old details carried into its
    # Unit features. Carrying them adds rows without changing what the Unit says, so the Unit
    # version and audit history are left as they are.
    op.execute(
        """
        SELECT app.seed_unit_setup_items(property.id, property.created_by)
        FROM app.properties AS property;

        WITH added AS (
            INSERT INTO app.unit_setup_items (
                id, property_id, list_kind, code, name_en, name_km, sort_order,
                created_by, updated_by, feature_type_item_id
            )
            SELECT gen_random_uuid(), old.property_id, 'UNIT_FEATURE', old.code, old.name_en,
                   old.name_km, 100 + old.sort_order, old.created_by, old.created_by, kind.id
            FROM app.unit_setup_items AS old
            JOIN app.unit_setup_items AS kind
              ON kind.property_id = old.property_id AND kind.list_kind = 'FEATURE_TYPE'
             AND kind.code = CASE
                    WHEN old.list_kind = 'KITCHEN' THEN 'KITCHEN'
                    WHEN old.code IN ('BALCONY', 'TERRACE') THEN 'OUTDOOR'
                    ELSE 'BUILT_IN'
                 END
            WHERE old.list_kind IN ('KITCHEN', 'ROOM_FEATURE') AND old.removed_at IS NULL
            ON CONFLICT (property_id, list_kind, code) DO NOTHING
            RETURNING *
        )
        SELECT app.audit_unit_setup_item(
            'unit_setup_item.created', added.created_by, NULL::app.unit_setup_items, added
        )
        FROM added;

        INSERT INTO app.unit_features (unit_id, item_id, feature_count)
        SELECT carried.unit_id, carried.item_id, max(carried.feature_count)
        FROM (
            SELECT unit.id AS unit_id, feature.id AS item_id,
                   least(unit.bedrooms, 9)::smallint AS feature_count
            FROM app.units AS unit
            JOIN app.unit_setup_items AS feature
              ON feature.property_id = unit.property_id AND feature.list_kind = 'UNIT_FEATURE'
             AND feature.code = 'BEDROOM'
            WHERE unit.bedrooms > 0
            UNION ALL
            SELECT unit.id, feature.id, least(unit.bathrooms, 9)::smallint
            FROM app.units AS unit
            JOIN app.unit_setup_items AS feature
              ON feature.property_id = unit.property_id AND feature.list_kind = 'UNIT_FEATURE'
             AND feature.code = 'BATHROOM'
            WHERE unit.bathrooms > 0
            UNION ALL
            SELECT unit.id, feature.id, 1::smallint
            FROM app.units AS unit
            JOIN app.unit_setup_items AS kitchen ON kitchen.id = unit.kitchen_item_id
            JOIN app.unit_setup_items AS feature
              ON feature.property_id = unit.property_id AND feature.list_kind = 'UNIT_FEATURE'
             AND feature.code = kitchen.code
            UNION ALL
            SELECT room.unit_id, feature.id, 1::smallint
            FROM app.unit_room_features AS room
            JOIN app.unit_setup_items AS old ON old.id = room.item_id
            JOIN app.unit_setup_items AS feature
              ON feature.property_id = old.property_id AND feature.list_kind = 'UNIT_FEATURE'
             AND feature.code = old.code
        ) AS carried
        GROUP BY carried.unit_id, carried.item_id
        ON CONFLICT DO NOTHING;
        """
    )
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Forward-only: removing Unit features would lose what each Unit has."""
    raise RuntimeError("V1.1 Unit features migration is forward-only")
