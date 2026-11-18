"""Parking Step 7: remove the home Unit Types and Balcony (owner 2026-11-18).

Revision ID: 20270811_434_parking
Revises: 20270810_433_parking
Create Date: 2026-11-18

Property Rental's migrations 20270308_227 and 20270405_255 seed their home Unit Types (Studio,
1 bedroom, 2 bedrooms, 3 bedrooms) and Balcony (Room feature and Unit feature) into every Property
that already exists. On Parking that put them into pkm's Parking Type list. The owner first chose
to have staff remove them in Settings, then (18 Nov 2026, "yes start the code fix") chose that
Parking removes them itself.

Each one still there is marked removed exactly as Remove in Settings does it
(`app.remove_unit_setup_item`): removed_at and removed_by set, version + 1, updated_at and
updated_by set, and one `unit_setup_item.removed` audit row through
`app.audit_unit_setup_item`, so History keeps the record. The actor is the user who made the
Property, the same actor the seed uses. Nothing is deleted.

If any of them is used (`app.unit_setup_item_in_use`: a Parking space of that type, or a Parking
space with that feature), that one is left as it is and the upgrade output names it (a NOTICE);
the others are removed and the upgrade carries on (owner's choice A, 18 Nov 2026). Staff can
remove it in Settings once nothing uses it.

Safe to run again: only items not yet removed are touched. A removed item cannot come back: the
protect trigger of 227 refuses to clear removed_at, and Property Rental's seeds use
ON CONFLICT DO NOTHING on (property, list, code), so they cannot add a second copy. A new Property
never gets them: Parking's seed (20270808_431) has only the four Parking Types and no Balcony.
Forward-only.
"""

from alembic import op

revision = "20270811_434_parking"
down_revision = "20270810_433_parking"
branch_labels = None
depends_on = None

REMOVE_HOME_ITEMS = """
DO $$
DECLARE
    v_in_use text;
    v_previous app.unit_setup_items%ROWTYPE;
    v_item app.unit_setup_items%ROWTYPE;
BEGIN
    SELECT string_agg(item.list_kind || ' ' || item.code, ', '
                      ORDER BY item.list_kind, item.code)
    INTO v_in_use
    FROM app.unit_setup_items AS item
    WHERE item.removed_at IS NULL
      AND (item.list_kind, item.code) IN (
          ('UNIT_TYPE', 'STUDIO'), ('UNIT_TYPE', 'ONE_BEDROOM'),
          ('UNIT_TYPE', 'TWO_BEDROOM'), ('UNIT_TYPE', 'THREE_BEDROOM'),
          ('ROOM_FEATURE', 'BALCONY'), ('UNIT_FEATURE', 'BALCONY'))
      AND app.unit_setup_item_in_use(item);
    IF v_in_use IS NOT NULL THEN
        RAISE NOTICE 'Parking Step 7: home items still in use, left as they are: %', v_in_use;
    END IF;

    FOR v_previous IN
        SELECT item.* FROM app.unit_setup_items AS item
        WHERE item.removed_at IS NULL
          AND (item.list_kind, item.code) IN (
              ('UNIT_TYPE', 'STUDIO'), ('UNIT_TYPE', 'ONE_BEDROOM'),
              ('UNIT_TYPE', 'TWO_BEDROOM'), ('UNIT_TYPE', 'THREE_BEDROOM'),
              ('ROOM_FEATURE', 'BALCONY'), ('UNIT_FEATURE', 'BALCONY'))
          AND NOT app.unit_setup_item_in_use(item)
        ORDER BY item.property_id, item.list_kind, item.code
        FOR UPDATE
    LOOP
        UPDATE app.unit_setup_items AS item
        SET removed_at = statement_timestamp(),
            removed_by = property.created_by,
            version = item.version + 1,
            updated_at = statement_timestamp(),
            updated_by = property.created_by
        FROM app.properties AS property
        WHERE item.id = v_previous.id AND property.id = item.property_id
        RETURNING item.* INTO v_item;
        PERFORM app.audit_unit_setup_item(
            'unit_setup_item.removed', v_item.removed_by, v_previous, v_item
        );
    END LOOP;
END;
$$;
"""


def upgrade() -> None:
    op.execute(REMOVE_HOME_ITEMS)


def downgrade() -> None:
    raise RuntimeError("Parking home Unit Types removal migration is forward-only")
