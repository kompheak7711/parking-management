# ruff: noqa: E501
"""Parking Type seeds (Parking Step 3b).

Revision ID: 20270405_255
Revises: 20270404_254
Create Date: 2026-10-29

Owner answers of 2026-10-29 (Parking Step 3, Q1 and Q3): a new Property starts with the owner's
four Parking Types (Covered, Uncovered, Motorbike, Tuk-Tuk/Food Cart) with their Khmer names,
instead of the four Unit Types of BR-UNIT-001, and the Balcony Room feature is no longer seeded.
A Property that already exists gets the four Parking Types added; nothing is removed or renamed.

Only the seed function changes; the default Rent column and `app.set_unit_rent_terms` come from
Property Rental's migration 20270401_251 (V1-061), which Parking takes as it is.
"""

from alembic import op

revision = "20270405_255"
down_revision = "20270404_254"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    raise RuntimeError("Parking Type seeds migration is forward-only")
