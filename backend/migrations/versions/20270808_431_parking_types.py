# ruff: noqa: E501
"""Parking Type seeds (Parking Step 3b).

Revision ID: 20270808_431_parking
Revises: 20270807_424
Create Date: 2026-10-29

Owner answers of 2026-10-29 (Parking Step 3, Q1 and Q3): a new Property starts with the owner's
four Parking Types (Covered, Uncovered, Motorbike, Tuk-Tuk/Food Cart) with their Khmer names,
instead of the four Unit Types of BR-UNIT-001, and the Balcony Room feature is no longer seeded.
A Property that already exists gets the four Parking Types added; nothing is removed or renamed.

Only the seed function changes; the default Rent column and `app.set_unit_rent_terms` come from
Property Rental's migration 20270401_251 (V1-061), which Parking takes as it is.

Parking Step 6 (owner 2026-11-17): moved after Property Rental's head 20270807_424 (it was
20270405_255, the same id as Property Rental's V1.1 Unit features migration) and rebuilt on
Property Rental's V1.1 seed function, which also seeds Feature types, Unit features and Item
types (hidden on Parking). Safe to run again: CREATE OR REPLACE and ON CONFLICT DO NOTHING.
"""

from alembic import op

revision = "20270808_431_parking"
down_revision = "20270807_424"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- The default lists of a Property on Parking: Property Rental's lists of migration
        -- 20270405_255 (V1.1), with the owner's four Parking Types (2026-10-29) instead of the
        -- home Unit Types, and no Balcony (Room feature or Unit feature).
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
                ('UNIT_TYPE', 'TUK_TUK_FOOD_CART', 'Tuk-Tuk/Food Cart', 'តុកតុក/រទេះលក់ម្ហូប', 40),
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

        SELECT app.seed_unit_setup_items(property.id, property.created_by)
        FROM app.properties AS property;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Parking Type seeds migration is forward-only")
