"""Unit setup lists and Unit details (V1-058 R2a; DL-075 answer 10, DL-078 answer 1).

DL-075 answer 10 and DL-078 answer 1 (owner, 2026-10-20), with the owner's go-ahead of
2026-10-24 19:24 for the two stricter checks (decision card "Allow the two stricter Unit checks in
the rebuild?": "Yes, add both checks"); technical points decided by Claude under the owner's
2026-10-23 22:30 rule.

- `app.unit_setup_items`: the Floors, Unit Types, Views, Kitchens and Room features lists, each
  item with a fixed code, an English name, an optional Khmer name and an order. An item is never
  deleted; it is removed (hidden from new picks) only while no Unit uses it. Every change is
  written to the audit history.
- A new Property gets the default Unit Types (the four types of BR-UNIT-001) and the Balcony
  Room feature; the Property that already exists gets them now, with a Floor item for each Floor
  its Units use, linked to those Units.
- `app.units` gains the Floor item, size in m2, bedrooms, bathrooms, View item, Kitchen item and
  notes; `app.unit_room_features` holds a Unit's Room features.
- Owner-approved stricter checks: the Unit number cannot change after creation, and a Unit Type
  must be a Unit Types item of the Property (replaces the fixed four-type CHECK). Existing Units
  already meet both (their types are the four seeded items).
- New overloads of `app.create_unit` and `app.update_unit` save the details; the update has no
  Unit number. The earlier functions stay; an update through them may not change the number.
"""

from alembic import op

revision = "20270209_197"
down_revision = "20270208_196"
branch_labels = None
depends_on = None

TRIM = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
    r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
)

UNIT_RESULT = """RETURNS TABLE (
            id uuid,
            property_id uuid,
            unit_number text,
            floor text,
            unit_type text,
            status text,
            version integer,
            floor_item_id uuid,
            size_square_metres numeric,
            bedrooms smallint,
            bathrooms smallint,
            view_item_id uuid,
            kitchen_item_id uuid,
            notes text,
            room_feature_ids uuid[]
        )"""

ITEM_RESULT = """RETURNS TABLE (
            id uuid,
            property_id uuid,
            list_kind text,
            code text,
            name_en text,
            name_km text,
            sort_order integer,
            removed_at timestamptz,
            version integer
        )"""

SIGNATURES = (
    "app.create_unit_setup_item(uuid, uuid, text, text, text, integer, uuid)",
    "app.update_unit_setup_item(uuid, text, text, integer, integer, uuid)",
    "app.remove_unit_setup_item(uuid, integer, uuid)",
    "app.create_unit(uuid, uuid, text, uuid, text, text, uuid, "
    "numeric, smallint, smallint, uuid, uuid, text, uuid[])",
    "app.update_unit("
    "uuid, uuid, text, text, integer, uuid, numeric, smallint, smallint, uuid, uuid, text, uuid[])",
)


def upgrade() -> None:
    op.execute(
        rf"""
        CREATE TABLE app.unit_setup_items (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            property_id uuid NOT NULL REFERENCES app.properties(id) ON DELETE RESTRICT,
            list_kind text NOT NULL,
            code text NOT NULL,
            name_en text NOT NULL,
            name_km text,
            sort_order integer NOT NULL DEFAULT 0,
            removed_at timestamptz,
            removed_by uuid REFERENCES app.user_accounts(actor_id),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            created_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_by uuid NOT NULL REFERENCES app.user_accounts(actor_id),
            CONSTRAINT unit_setup_items_kind_supported CHECK (
                list_kind IN ('FLOOR', 'UNIT_TYPE', 'VIEW', 'KITCHEN', 'ROOM_FEATURE')
            ),
            CONSTRAINT unit_setup_items_code_format CHECK (code ~ '^[A-Z0-9][A-Z0-9_]{{0,39}}$'),
            CONSTRAINT unit_setup_items_name_en_normalized CHECK (
                name_en = btrim(name_en, {TRIM}) AND length(name_en) BETWEEN 1 AND 100
            ),
            CONSTRAINT unit_setup_items_name_km_normalized CHECK (
                name_km IS NULL
                OR (name_km = btrim(name_km, {TRIM}) AND length(name_km) BETWEEN 1 AND 100)
            ),
            CONSTRAINT unit_setup_items_sort_order_range CHECK (sort_order BETWEEN 0 AND 10000),
            CONSTRAINT unit_setup_items_removed_pair CHECK (
                (removed_at IS NULL) = (removed_by IS NULL)
            ),
            CONSTRAINT unit_setup_items_code_unique UNIQUE (property_id, list_kind, code)
        );
        CREATE INDEX unit_setup_items_property_kind_idx
            ON app.unit_setup_items(property_id, list_kind, sort_order);
        REVOKE ALL ON TABLE app.unit_setup_items FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_setup_items TO prm_runtime;

        ALTER TABLE app.units
            ADD COLUMN floor_item_id uuid REFERENCES app.unit_setup_items(id),
            ADD COLUMN size_square_metres numeric(7, 2),
            ADD COLUMN bedrooms smallint,
            ADD COLUMN bathrooms smallint,
            ADD COLUMN view_item_id uuid REFERENCES app.unit_setup_items(id),
            ADD COLUMN kitchen_item_id uuid REFERENCES app.unit_setup_items(id),
            ADD COLUMN notes text,
            ADD CONSTRAINT units_size_range CHECK (
                size_square_metres IS NULL
                OR (size_square_metres > 0 AND size_square_metres <= 10000)
            ),
            ADD CONSTRAINT units_bedrooms_range CHECK (
                bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20
            ),
            ADD CONSTRAINT units_bathrooms_range CHECK (
                bathrooms IS NULL OR bathrooms BETWEEN 0 AND 20
            ),
            ADD CONSTRAINT units_notes_normalized CHECK (
                notes IS NULL OR (notes = btrim(notes, {TRIM}) AND length(notes) BETWEEN 1 AND 2000)
            ),
            DROP CONSTRAINT units_unit_type_supported,
            ADD CONSTRAINT units_unit_type_code_format CHECK (
                unit_type ~ '^[A-Z0-9][A-Z0-9_]{{0,39}}$'
            );

        CREATE TABLE app.unit_room_features (
            unit_id uuid NOT NULL REFERENCES app.units(id) ON DELETE RESTRICT,
            item_id uuid NOT NULL REFERENCES app.unit_setup_items(id) ON DELETE RESTRICT,
            PRIMARY KEY (unit_id, item_id)
        );
        CREATE INDEX unit_room_features_item_idx ON app.unit_room_features(item_id);
        REVOKE ALL ON TABLE app.unit_room_features FROM PUBLIC, prm_runtime, prm_bootstrap;
        GRANT SELECT ON TABLE app.unit_room_features TO prm_runtime;
        """
    )
    op.execute(
        """
        -- An item of one list for one Property that may be picked now (not removed). The row is
        -- locked FOR SHARE, so a removal waits for the Unit save and then sees the Unit.
        CREATE FUNCTION app.assert_unit_setup_item(
            p_property_id uuid, p_list_kind text, p_item_id uuid
        ) RETURNS app.unit_setup_items
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_item app.unit_setup_items%ROWTYPE;
        BEGIN
            SELECT item.* INTO v_item FROM app.unit_setup_items AS item
            WHERE item.id = p_item_id FOR SHARE;
            IF NOT FOUND OR v_item.property_id <> p_property_id
                OR v_item.list_kind <> p_list_kind OR v_item.removed_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'Unit setup item is not in the % list', p_list_kind
                    USING ERRCODE = '22023';
            END IF;
            RETURN v_item;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.assert_unit_setup_item(uuid, text, uuid) FROM PUBLIC;

        CREATE FUNCTION app.check_unit_setup_references() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_item_id uuid;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.unit_number IS DISTINCT FROM OLD.unit_number THEN
                RAISE EXCEPTION 'The Unit number cannot change after the Unit is created'
                    USING ERRCODE = '55000';
            END IF;
            -- The earlier update_unit writes Floor text only: a Floor that no longer matches the
            -- linked item's name drops the link, so the text and the link never disagree.
            IF TG_OP = 'UPDATE' AND NEW.floor_item_id IS NOT NULL
                AND NEW.floor_item_id IS NOT DISTINCT FROM OLD.floor_item_id
                AND NEW.floor IS DISTINCT FROM OLD.floor
                AND NEW.floor IS DISTINCT FROM (
                    SELECT item.name_en FROM app.unit_setup_items AS item
                    WHERE item.id = NEW.floor_item_id
                )
            THEN
                NEW.floor_item_id := NULL;
            END IF;
            IF TG_OP = 'INSERT' OR NEW.unit_type IS DISTINCT FROM OLD.unit_type THEN
                SELECT item.id INTO v_item_id FROM app.unit_setup_items AS item
                WHERE item.property_id = NEW.property_id AND item.list_kind = 'UNIT_TYPE'
                  AND item.code = NEW.unit_type;
                IF v_item_id IS NULL THEN
                    RAISE EXCEPTION 'Unit Type is not in the Unit Types list'
                        USING ERRCODE = '22023';
                END IF;
                PERFORM app.assert_unit_setup_item(NEW.property_id, 'UNIT_TYPE', v_item_id);
            END IF;
            IF NEW.floor_item_id IS NOT NULL AND (
                TG_OP = 'INSERT' OR NEW.floor_item_id IS DISTINCT FROM OLD.floor_item_id
            ) THEN
                PERFORM app.assert_unit_setup_item(NEW.property_id, 'FLOOR', NEW.floor_item_id);
            END IF;
            IF NEW.view_item_id IS NOT NULL AND (
                TG_OP = 'INSERT' OR NEW.view_item_id IS DISTINCT FROM OLD.view_item_id
            ) THEN
                PERFORM app.assert_unit_setup_item(NEW.property_id, 'VIEW', NEW.view_item_id);
            END IF;
            IF NEW.kitchen_item_id IS NOT NULL AND (
                TG_OP = 'INSERT' OR NEW.kitchen_item_id IS DISTINCT FROM OLD.kitchen_item_id
            ) THEN
                PERFORM app.assert_unit_setup_item(
                    NEW.property_id, 'KITCHEN', NEW.kitchen_item_id
                );
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_setup_references() FROM PUBLIC;
        CREATE TRIGGER units_check_setup_references
        BEFORE INSERT OR UPDATE ON app.units
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_setup_references();

        CREATE FUNCTION app.check_unit_room_feature() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM app.assert_unit_setup_item(
                    (SELECT unit.property_id FROM app.units AS unit WHERE unit.id = NEW.unit_id),
                    'ROOM_FEATURE',
                    NEW.item_id
                );
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'A Unit Room feature row is added or taken away, never changed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN OLD;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_room_feature() FROM PUBLIC;
        CREATE TRIGGER unit_room_features_check
        BEFORE INSERT OR UPDATE OR DELETE ON app.unit_room_features
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_room_feature();

        CREATE FUNCTION app.unit_setup_item_in_use(p_item app.unit_setup_items)
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
                ELSE EXISTS (
                    SELECT 1 FROM app.unit_room_features AS feature
                    WHERE feature.item_id = p_item.id
                )
            END
        $$;
        REVOKE ALL ON FUNCTION app.unit_setup_item_in_use(app.unit_setup_items) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.unit_setup_item_in_use(app.unit_setup_items)
            TO prm_runtime;

        CREATE FUNCTION app.protect_unit_setup_item() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE'
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.property_id IS DISTINCT FROM OLD.property_id
                OR NEW.list_kind IS DISTINCT FROM OLD.list_kind
                OR NEW.code IS DISTINCT FROM OLD.code
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.version <> OLD.version + 1
                OR NEW.updated_at < OLD.updated_at
                OR (OLD.removed_at IS NOT NULL AND (
                    NEW.removed_at IS DISTINCT FROM OLD.removed_at
                    OR NEW.removed_by IS DISTINCT FROM OLD.removed_by
                ))
            THEN
                RAISE EXCEPTION 'Unit setup item identity and history are protected'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.removed_at IS NULL AND NEW.removed_at IS NOT NULL
                AND app.unit_setup_item_in_use(NEW)
            THEN
                RAISE EXCEPTION 'A Unit setup item used by a Unit cannot be removed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.protect_unit_setup_item() FROM PUBLIC;
        CREATE TRIGGER unit_setup_items_protect
        BEFORE UPDATE OR DELETE ON app.unit_setup_items
        FOR EACH ROW EXECUTE FUNCTION app.protect_unit_setup_item();
        CREATE TRIGGER unit_setup_items_reject_truncate
        BEFORE TRUNCATE ON app.unit_setup_items
        FOR EACH STATEMENT EXECUTE FUNCTION app.protect_unit_setup_item();
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.unit_setup_item_state(p_item app.unit_setup_items) RETURNS jsonb
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
            )
        $$;
        REVOKE ALL ON FUNCTION app.unit_setup_item_state(app.unit_setup_items) FROM PUBLIC;

        CREATE FUNCTION app.audit_unit_setup_item(
            p_action text,
            p_actor_id uuid,
            p_previous app.unit_setup_items,
            p_item app.unit_setup_items
        ) RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_event_id uuid := gen_random_uuid();
        BEGIN
            INSERT INTO app.audit_events (
                id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                reason, property_id, previous_state, resulting_state, correlation_id, source,
                outcome
            ) VALUES (
                v_event_id, statement_timestamp(),
                timezone('Asia/Phnom_Penh', statement_timestamp())::date,
                p_actor_id, p_action, 'unit_setup_item', p_item.id,
                'Unit setup list changed in Settings', p_item.property_id,
                CASE WHEN p_previous.id IS NULL THEN NULL
                     ELSE app.unit_setup_item_state(p_previous) END,
                app.unit_setup_item_state(p_item),
                v_event_id, 'API', 'SUCCEEDED'
            );
        END;
        $$;
        REVOKE ALL ON FUNCTION
            app.audit_unit_setup_item(text, uuid, app.unit_setup_items, app.unit_setup_items)
            FROM PUBLIC;

        -- A code made from the English name: capitals, digits and _, unique in its list.
        CREATE FUNCTION app.next_unit_setup_code(
            p_property_id uuid, p_list_kind text, p_name_en text
        ) RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_base text := left(btrim(
                regexp_replace(upper(p_name_en), '[^A-Z0-9]+', '_', 'g'), '_'
            ), 32);
            v_code text;
            v_number integer := 1;
        BEGIN
            IF v_base = '' THEN
                v_base := 'ITEM';
            END IF;
            v_code := v_base;
            WHILE EXISTS (
                SELECT 1 FROM app.unit_setup_items AS item
                WHERE item.property_id = p_property_id AND item.list_kind = p_list_kind
                  AND item.code = v_code
            ) LOOP
                v_number := v_number + 1;
                v_code := v_base || '_' || v_number::text;
            END LOOP;
            RETURN v_code;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.next_unit_setup_code(uuid, text, text) FROM PUBLIC;
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
            p_actor_id uuid
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
                created_by, updated_by
            ) VALUES (
                p_id, p_property_id, p_list_kind,
                app.next_unit_setup_code(p_property_id, p_list_kind, btrim(p_name_en, {TRIM})),
                btrim(p_name_en, {TRIM}),
                nullif(btrim(p_name_km, {TRIM}), ''),
                p_sort_order, p_actor_id, p_actor_id
            ) RETURNING item.* INTO v_item;
            PERFORM app.audit_unit_setup_item(
                'unit_setup_item.created', p_actor_id, v_none, v_item
            );
            RETURN QUERY SELECT v_item.id, v_item.property_id, v_item.list_kind, v_item.code,
                v_item.name_en, v_item.name_km, v_item.sort_order, v_item.removed_at,
                v_item.version;
        END;
        $$;

        CREATE FUNCTION app.update_unit_setup_item(
            p_id uuid,
            p_name_en text,
            p_name_km text,
            p_sort_order integer,
            p_expected_version integer,
            p_actor_id uuid
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
                v_item.version;
        END;
        $$;

        CREATE FUNCTION app.remove_unit_setup_item(
            p_id uuid,
            p_expected_version integer,
            p_actor_id uuid
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
                RAISE EXCEPTION 'The Unit setup item is already removed'
                    USING ERRCODE = '22023';
            END IF;
            UPDATE app.unit_setup_items AS item
            SET removed_at = statement_timestamp(),
                removed_by = p_actor_id,
                version = item.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE item.id = p_id
            RETURNING item.* INTO v_item;
            PERFORM app.audit_unit_setup_item(
                'unit_setup_item.removed', p_actor_id, v_previous, v_item
            );
            RETURN QUERY SELECT v_item.id, v_item.property_id, v_item.list_kind, v_item.code,
                v_item.name_en, v_item.name_km, v_item.sort_order, v_item.removed_at,
                v_item.version;
        END;
        $$;
        """
    )
    op.execute(
        rf"""
        CREATE FUNCTION app.unit_with_details(p_unit_id uuid) {UNIT_RESULT}
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $$
            SELECT unit.id, unit.property_id, unit.unit_number,
                   coalesce(floor_item.name_en, unit.floor), unit.unit_type, unit.status,
                   unit.version, unit.floor_item_id, unit.size_square_metres, unit.bedrooms,
                   unit.bathrooms, unit.view_item_id, unit.kitchen_item_id, unit.notes,
                   coalesce(
                       (SELECT array_agg(feature.item_id ORDER BY feature.item_id)
                        FROM app.unit_room_features AS feature
                        WHERE feature.unit_id = unit.id),
                       ARRAY[]::uuid[]
                   )
            FROM app.units AS unit
            LEFT JOIN app.unit_setup_items AS floor_item ON floor_item.id = unit.floor_item_id
            WHERE unit.id = p_unit_id
        $$;
        REVOKE ALL ON FUNCTION app.unit_with_details(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.unit_with_details(uuid) TO prm_runtime;

        CREATE FUNCTION app.replace_unit_room_features(p_unit_id uuid, p_item_ids uuid[])
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            DELETE FROM app.unit_room_features AS feature
            WHERE feature.unit_id = p_unit_id
              AND NOT (feature.item_id = ANY (coalesce(p_item_ids, ARRAY[]::uuid[])));
            INSERT INTO app.unit_room_features (unit_id, item_id)
            SELECT p_unit_id, item_id
            FROM unnest(coalesce(p_item_ids, ARRAY[]::uuid[])) AS chosen(item_id)
            ON CONFLICT DO NOTHING;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.replace_unit_room_features(uuid, uuid[]) FROM PUBLIC;

        CREATE FUNCTION app.create_unit(
            p_id uuid,
            p_property_id uuid,
            p_unit_number text,
            p_floor_item_id uuid,
            p_unit_type text,
            p_status text,
            p_actor_id uuid,
            p_size_square_metres numeric,
            p_bedrooms smallint,
            p_bathrooms smallint,
            p_view_item_id uuid,
            p_kitchen_item_id uuid,
            p_notes text,
            p_room_feature_ids uuid[]
        ) {UNIT_RESULT}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_floor app.unit_setup_items%ROWTYPE;
        BEGIN
            v_floor := app.assert_unit_setup_item(p_property_id, 'FLOOR', p_floor_item_id);
            INSERT INTO app.units (
                id, property_id, unit_number, floor, unit_type, status, created_by, updated_by,
                floor_item_id, size_square_metres, bedrooms, bathrooms, view_item_id,
                kitchen_item_id, notes
            ) VALUES (
                p_id, p_property_id, btrim(p_unit_number, {TRIM}), v_floor.name_en,
                p_unit_type, p_status, p_actor_id, p_actor_id, p_floor_item_id,
                p_size_square_metres, p_bedrooms, p_bathrooms, p_view_item_id,
                p_kitchen_item_id, nullif(btrim(p_notes, {TRIM}), '')
            );
            PERFORM app.replace_unit_room_features(p_id, p_room_feature_ids);
            RETURN QUERY SELECT * FROM app.unit_with_details(p_id);
        END;
        $$;

        CREATE FUNCTION app.update_unit(
            p_id uuid,
            p_floor_item_id uuid,
            p_unit_type text,
            p_status text,
            p_expected_version integer,
            p_actor_id uuid,
            p_size_square_metres numeric,
            p_bedrooms smallint,
            p_bathrooms smallint,
            p_view_item_id uuid,
            p_kitchen_item_id uuid,
            p_notes text,
            p_room_feature_ids uuid[]
        ) {UNIT_RESULT}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
            v_floor_name text;
        BEGIN
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_id FOR UPDATE;
            IF NOT FOUND OR v_unit.version <> p_expected_version THEN
                RETURN;
            END IF;
            IF p_floor_item_id IS DISTINCT FROM v_unit.floor_item_id THEN
                v_floor_name := (
                    app.assert_unit_setup_item(v_unit.property_id, 'FLOOR', p_floor_item_id)
                ).name_en;
            ELSE
                v_floor_name := coalesce(
                    (SELECT item.name_en FROM app.unit_setup_items AS item
                     WHERE item.id = p_floor_item_id),
                    v_unit.floor
                );
            END IF;
            UPDATE app.units AS unit
            SET floor = v_floor_name,
                floor_item_id = p_floor_item_id,
                unit_type = p_unit_type,
                status = p_status,
                size_square_metres = p_size_square_metres,
                bedrooms = p_bedrooms,
                bathrooms = p_bathrooms,
                view_item_id = p_view_item_id,
                kitchen_item_id = p_kitchen_item_id,
                notes = nullif(btrim(p_notes, {TRIM}), ''),
                version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_id;
            PERFORM app.replace_unit_room_features(p_id, p_room_feature_ids);
            RETURN QUERY SELECT * FROM app.unit_with_details(p_id);
        END;
        $$;
        """
    )
    op.execute(
        """
        -- The default lists of a Property: the four Unit Types of BR-UNIT-001 and Balcony. Khmer
        -- names need the native check.
        CREATE FUNCTION app.seed_unit_setup_items(p_property_id uuid, p_actor_id uuid)
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
                ('ROOM_FEATURE', 'BALCONY', 'Balcony', 'រានហាល', 10)
            ) AS defaults(list_kind, code, name_en, name_km, sort_order)
            ON CONFLICT (property_id, list_kind, code) DO NOTHING
            RETURNING *
            LOOP
                PERFORM app.audit_unit_setup_item(
                    'unit_setup_item.created', p_actor_id, NULL::app.unit_setup_items, v_item
                );
            END LOOP;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.seed_unit_setup_items(uuid, uuid) FROM PUBLIC;

        CREATE FUNCTION app.seed_unit_setup_items_for_property() RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM app.seed_unit_setup_items(NEW.id, NEW.created_by);
            RETURN NULL;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.seed_unit_setup_items_for_property() FROM PUBLIC;
        CREATE TRIGGER properties_seed_unit_setup_items
        AFTER INSERT ON app.properties
        FOR EACH ROW EXECUTE FUNCTION app.seed_unit_setup_items_for_property();
        """
    )
    # The Property that already exists: the defaults, then a Floor item for each Floor its Units
    # use, linked to those Units. Linking adds a reference without changing what the Unit says,
    # so the version and audit history are left as they are.
    op.execute(
        rf"""
        SELECT app.seed_unit_setup_items(property.id, property.created_by)
        FROM app.properties AS property;

        INSERT INTO app.unit_setup_items (
            id, property_id, list_kind, code, name_en, sort_order, created_by, updated_by
        )
        SELECT gen_random_uuid(), floors.property_id, 'FLOOR',
               'F' || lpad(floors.position::text, 3, '0'), floors.floor,
               floors.position * 10, property.created_by, property.created_by
        FROM (
            SELECT used.property_id, used.floor,
                   row_number() OVER (PARTITION BY used.property_id ORDER BY used.floor)
                       AS position
            FROM (SELECT DISTINCT unit.property_id, btrim(left(unit.floor, 100), {TRIM}) AS floor
                  FROM app.units AS unit) AS used
        ) AS floors
        JOIN app.properties AS property ON property.id = floors.property_id;

        SELECT app.audit_unit_setup_item(
            'unit_setup_item.created', item.created_by, NULL::app.unit_setup_items, item
        )
        FROM app.unit_setup_items AS item
        WHERE item.list_kind = 'FLOOR';

        ALTER TABLE app.units DISABLE TRIGGER units_protect_history;
        ALTER TABLE app.units DISABLE TRIGGER units_check_setup_references;
        UPDATE app.units AS unit
        SET floor_item_id = item.id
        FROM app.unit_setup_items AS item
        WHERE item.property_id = unit.property_id AND item.list_kind = 'FLOOR'
          AND item.name_en = btrim(left(unit.floor, 100), {TRIM});
        ALTER TABLE app.units ENABLE TRIGGER units_check_setup_references;
        ALTER TABLE app.units ENABLE TRIGGER units_protect_history;
        """
    )
    for signature in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO prm_runtime")


def downgrade() -> None:
    """Forward-only: removing the lists would lose Unit details and their history."""
    raise RuntimeError("Unit setup lists migration is forward-only")
