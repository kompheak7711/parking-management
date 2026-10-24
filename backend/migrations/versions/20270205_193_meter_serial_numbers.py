"""Meter serial numbers unique across the Property (V1-059 part B; DL-071 answer 12).

DL-071 answer 12, DB-UTIL-001, TCD-DB-004; technical points decided by Claude under the owner's
2026-10-23 22:30 rule; the owner's go-ahead for this tightening check: V1-059 part B.

- `app.meter_serial_match_key(text)`: the compared form of a serial number: spaces and dashes
  removed, capital letters ignored (the same reading as the ID number rule of DL-071 answer 11).
- `app.guard_utility_meter_serial()` on every new Meter, the replacement Meter included: no
  other Meter of the same Property, whatever its Utility Type, current or replaced, has the same
  serial. The check takes a transaction lock per Property, after the Property-type lock that
  `app.guard_utility_meter()` already takes (trigger order by name), so two Meters with the
  same serial cannot both be saved. The serial of a Meter never changes (guard_utility_meter).

Meters recorded before keep their serial (DL-071 transition); a new Meter is compared with all
of them. A new function and a new trigger; no stored row changes.
"""

from alembic import op

revision = "20270205_193"
down_revision = "20270204_192"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.meter_serial_match_key(p_serial_number text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
            SELECT pg_catalog.lower(
                pg_catalog.regexp_replace(p_serial_number, '[[:space:]-]', '', 'g')
            )
        $$;

        CREATE FUNCTION app.guard_utility_meter_serial() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE v_property_id uuid;
        BEGIN
            SELECT unit.property_id INTO STRICT v_property_id
            FROM app.units AS unit WHERE unit.id=NEW.unit_id;
            PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
                'utility-meter-serial:' || v_property_id::text, 0
            ));
            IF EXISTS (
                SELECT 1
                FROM app.utility_meters AS meter
                JOIN app.units AS unit ON unit.id=meter.unit_id
                WHERE unit.property_id=v_property_id
                  AND meter.id<>NEW.id
                  AND app.meter_serial_match_key(meter.serial_number)
                      =app.meter_serial_match_key(NEW.serial_number)
            ) THEN
                RAISE EXCEPTION 'Meter serial number is already used in this Property'
                    USING ERRCODE='23505';
            END IF;
            RETURN NEW;
        END
        $$;

        REVOKE ALL ON FUNCTION app.meter_serial_match_key(text) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.guard_utility_meter_serial() FROM PUBLIC;

        CREATE TRIGGER utility_meters_serial_unique
            BEFORE INSERT ON app.utility_meters
            FOR EACH ROW EXECUTE FUNCTION app.guard_utility_meter_serial();
        """
    )


def downgrade() -> None:
    """Forward-only: removing the check would allow a used serial again."""
    raise RuntimeError("meter serial number migration is forward-only")
