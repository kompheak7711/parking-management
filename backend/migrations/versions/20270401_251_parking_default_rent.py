# ruff: noqa: E501
"""Parking default monthly price and the Parking Type seeds (Parking Step 3).

Revision ID: 20270401_251
Revises: 20270331_250
Create Date: 2026-10-29

Owner brief of 2026-10-29 (docs/replica/step-3-brief.md) and the owner's answers of the same day:

- `app.units` gains `default_monthly_rent_usd_cents` (whole USD cents, empty allowed, above zero).
  The price fills a new Lease's Monthly Rent on the Lease form; it is copied, so a later change
  never touches a Lease, an Invoice or a Reservation.
- `app.set_unit_default_rent` sets it with the Parking's version check (same shape as
  `app.update_unit`); the API writes the History row with who, the reason, the old and the new
  price, as for every other Parking change.
- `app.unit_with_details`, `app.create_unit` and `app.update_unit` are re-created so the Parking
  row they return carries the price as its last column.
- A new Property starts with the owner's four Parking Types (Covered, Uncovered, Motorbike,
  Tuk-Tuk/Food Cart) instead of the four Unit Types of BR-UNIT-001; the Balcony Room feature is
  no longer seeded. A Property that already exists gets the four Parking Types added; nothing is
  removed.
"""

from alembic import op

revision = "20270401_251"
down_revision = "20270331_250"
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
            room_feature_ids uuid[],
            default_monthly_rent_usd_cents bigint
        )"""

CREATE_UNIT = (
    "app.create_unit(uuid, uuid, text, uuid, text, text, uuid, numeric, smallint, smallint, "
    "uuid, uuid, text, uuid[])"
)
UPDATE_UNIT = (
    "app.update_unit(uuid, uuid, text, text, integer, uuid, numeric, smallint, smallint, uuid, "
    "uuid, text, uuid[])"
)
SET_RENT = "app.set_unit_default_rent(uuid, bigint, integer, uuid)"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.units
            ADD COLUMN default_monthly_rent_usd_cents bigint,
            ADD CONSTRAINT units_default_rent_positive CHECK (
                default_monthly_rent_usd_cents IS NULL OR default_monthly_rent_usd_cents > 0
            );
        """
    )
    op.execute(
        rf"""
        DROP FUNCTION {CREATE_UNIT};
        DROP FUNCTION {UPDATE_UNIT};
        DROP FUNCTION app.unit_with_details(uuid);

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
                   ),
                   unit.default_monthly_rent_usd_cents
            FROM app.units AS unit
            LEFT JOIN app.unit_setup_items AS floor_item ON floor_item.id = unit.floor_item_id
            WHERE unit.id = p_unit_id
        $$;
        REVOKE ALL ON FUNCTION app.unit_with_details(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.unit_with_details(uuid) TO prm_runtime;

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
        REVOKE ALL ON FUNCTION {CREATE_UNIT} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {CREATE_UNIT} TO prm_runtime;

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
        REVOKE ALL ON FUNCTION {UPDATE_UNIT} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {UPDATE_UNIT} TO prm_runtime;

        -- The default monthly price: set with the Parking's version check; nothing else changes.
        CREATE FUNCTION app.set_unit_default_rent(
            p_id uuid,
            p_cents bigint,
            p_expected_version integer,
            p_actor_id uuid
        ) {UNIT_RESULT}
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
        BEGIN
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_id FOR UPDATE;
            IF NOT FOUND OR v_unit.version <> p_expected_version THEN
                RETURN;
            END IF;
            UPDATE app.units AS unit
            SET default_monthly_rent_usd_cents = p_cents,
                version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_id;
            RETURN QUERY SELECT * FROM app.unit_with_details(p_id);
        END;
        $$;
        REVOKE ALL ON FUNCTION {SET_RENT} FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION {SET_RENT} TO prm_runtime;
        """
    )
    op.execute(
        """
        -- The default list of a Property: the owner's four Parking Types (2026-10-29).
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
                ('UNIT_TYPE', 'COVERED', 'Covered', 'ចំណតមានដំបូល', 10),
                ('UNIT_TYPE', 'UNCOVERED', 'Uncovered', 'ចំណតគ្មានដំបូល', 20),
                ('UNIT_TYPE', 'MOTORBIKE', 'Motorbike', 'ម៉ូតូ', 30),
                ('UNIT_TYPE', 'TUK_TUK_FOOD_CART', 'Tuk-Tuk/Food Cart', 'តុកតុក/រទេះលក់ម្ហូប', 40)
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

        SELECT app.seed_unit_setup_items(property.id, property.created_by)
        FROM app.properties AS property;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Parking default price migration is forward-only")
