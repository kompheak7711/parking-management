# ruff: noqa: E501
"""V1.1 rework part 1 (owner 2026-11-02 "Go", plan of 01/11): Units for rent, places, DB fixes.

Revision ID: 20270408_258
Revises: 20270407_257
Create Date: 2026-11-02

- A Unit feature no longer needs a Feature type: every Unit feature is a place (owner 30/10,
  mock-up v53). The column feature_type_item_id stays for the rows that already have one.
- app.units gets for_rent (Yes/No, default Yes). The warehouse (Unit W01) is not for rent. A Unit
  that is not for rent cannot get a Reservation or a Lease, is left out of the Units counts on
  Home and the meter readings card, and is left out of the Unit occupancy report (owner 31/10:
  not counted as Occupied). app.set_unit_for_rent changes it at the expected Unit version; it
  refuses "not for rent" while the Unit is Reserved or Occupied, or has an active Reservation,
  a draft Lease or a signed Lease.
- Database review of 01/11 (owner yes 02/11), fixes 2, 3 and 5: drop 4 indexes that copy
  another index, add 5 indexes for lists by Lease, Invoice and Customer, and add the checks on
  Lease history (rent above 0, known status) and Receipt numbers (no spaces at the ends).

Technical choices by Claude under the owner's 2026-10-23 22:30 rule (no money rule changes).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270408_258"
down_revision: str | None = "20270407_257"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SET_FOR_RENT = "app.set_unit_for_rent(uuid, integer, boolean, uuid)"
HOME = "app.home_page(uuid,uuid,uuid[],text[])"
OCCUPANCY = "app.report_unit_occupancy(uuid,uuid,uuid[])"

HOME_UNITS_BEFORE = "            FROM app.units unit WHERE unit.property_id=p_property;\n"
HOME_UNITS_AFTER = (
    "            FROM app.units unit WHERE unit.property_id=p_property\n"
    "              -- V1.1 (owner 2026-10-31): a Unit not for rent is not counted.\n"
    "              AND unit.for_rent;\n"
)
HOME_READINGS_BEFORE = (
    "            WHERE unit.property_id=p_property AND meter.deactivated_date IS NULL\n"
)
HOME_READINGS_AFTER = (
    "            WHERE unit.property_id=p_property AND unit.for_rent\n"
    "              AND meter.deactivated_date IS NULL\n"
)
OCCUPANCY_BEFORE = (
    "        WHERE unit.property_id=p_property\n        ORDER BY unit.unit_number, unit.id;"
)
OCCUPANCY_AFTER = (
    "        WHERE unit.property_id=p_property\n"
    "          -- V1.1 (owner 2026-10-31): a Unit not for rent is left out.\n"
    "          AND unit.for_rent\n"
    "        ORDER BY unit.unit_number, unit.id;"
)


def _patch(signature: str, replacements: tuple[tuple[str, str], ...]) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError(f"{signature} does not have the expected text")
        definition = definition.replace(before, after)
    op.execute(text(definition))


def upgrade() -> None:
    op.execute(
        """
        -- Every Unit feature is a place; a Feature type is no longer needed.
        ALTER TABLE app.unit_setup_items
            DROP CONSTRAINT unit_setup_items_feature_type_only_on_features,
            ADD CONSTRAINT unit_setup_items_feature_type_only_on_features CHECK (
                feature_type_item_id IS NULL OR list_kind = 'UNIT_FEATURE'
            );
        CREATE OR REPLACE FUNCTION app.check_unit_feature_type() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.list_kind = 'UNIT_FEATURE' AND NEW.feature_type_item_id IS NOT NULL AND (
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

        ALTER TABLE app.units ADD COLUMN for_rent boolean NOT NULL DEFAULT true;
        COMMENT ON COLUMN app.units.for_rent IS
            'V1.1: No for a Unit that is never rented, such as the warehouse W01';

        -- A Unit that is not for rent gets no Reservation and no Lease.
        CREATE FUNCTION app.check_unit_is_for_rent() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.units AS unit
                WHERE unit.id = NEW.unit_id AND NOT unit.for_rent
            ) THEN
                RAISE EXCEPTION 'Unit is not for rent' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION app.check_unit_is_for_rent() FROM PUBLIC;
        CREATE TRIGGER reservations_unit_for_rent
        BEFORE INSERT OR UPDATE OF unit_id ON app.reservations
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_is_for_rent();
        CREATE TRIGGER leases_unit_for_rent
        BEFORE INSERT OR UPDATE OF unit_id ON app.leases
        FOR EACH ROW EXECUTE FUNCTION app.check_unit_is_for_rent();

        -- Sets For rent at the expected Unit version. Answers the new version, the same version
        -- when nothing changes, or NULL when the Unit is not there or its version moved on.
        CREATE FUNCTION app.set_unit_for_rent(
            p_unit_id uuid,
            p_expected_version integer,
            p_for_rent boolean,
            p_actor_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_unit app.units%ROWTYPE;
        BEGIN
            IF p_for_rent IS NULL OR p_actor_id IS NULL THEN
                RAISE EXCEPTION 'For rent is invalid' USING ERRCODE = '22023';
            END IF;
            SELECT unit.* INTO v_unit FROM app.units AS unit WHERE unit.id = p_unit_id FOR UPDATE;
            IF NOT FOUND OR v_unit.version <> p_expected_version THEN
                RETURN NULL;
            END IF;
            IF v_unit.for_rent = p_for_rent THEN
                RETURN v_unit.version;
            END IF;
            IF NOT p_for_rent AND (
                v_unit.status IN ('RESERVED', 'OCCUPIED')
                OR EXISTS (SELECT 1 FROM app.reservations AS reservation
                    WHERE reservation.unit_id = p_unit_id AND reservation.status = 'ACTIVE')
                OR EXISTS (SELECT 1 FROM app.leases AS lease
                    WHERE lease.unit_id = p_unit_id AND lease.status IN ('DRAFTED', 'SIGNED'))
            ) THEN
                RAISE EXCEPTION 'Unit is in use for renting' USING ERRCODE = '55000';
            END IF;
            UPDATE app.units AS unit
            SET for_rent = p_for_rent,
                version = unit.version + 1,
                updated_at = statement_timestamp(),
                updated_by = p_actor_id
            WHERE unit.id = p_unit_id;
            RETURN v_unit.version + 1;
        END;
        $$;

        -- Database review 01/11, fix 2: these indexes copy another index.
        DROP INDEX app.invoice_lines_invoice_idx;
        DROP INDEX app.service_rates_effective_selection_idx;
        DROP INDEX app.utility_rates_effective_selection_idx;
        DROP INDEX app.settlement_correction_refund_details_correction_idx;

        -- Fix 3: lists by Lease, Invoice and Customer.
        CREATE INDEX payments_lease_idx ON app.payments (lease_id);
        CREATE INDEX invoice_adjustments_invoice_idx ON app.invoice_adjustments (invoice_id);
        CREATE INDEX late_payment_charges_customer_idx ON app.late_payment_charges (customer_id);
        CREATE INDEX receipts_payer_customer_idx ON app.receipts (payer_customer_id);
        CREATE INDEX refunds_recipient_customer_idx ON app.refunds (recipient_customer_id);

        -- Fix 5: the Lease history and Receipt number checks the source tables already keep.
        ALTER TABLE app.lease_revisions
            ADD CONSTRAINT lease_revisions_monthly_rent_positive CHECK (
                monthly_rent_usd_cents IS NULL OR monthly_rent_usd_cents > 0
            ),
            ADD CONSTRAINT lease_revisions_status_check CHECK (
                status IN ('DRAFTED', 'SIGNED', 'CANCELLED', 'TERMINATED')
            );
        ALTER TABLE app.receipts
            ADD CONSTRAINT receipts_receipt_number_normalized CHECK (
                length(btrim(receipt_number)) > 0 AND receipt_number = btrim(receipt_number)
            );
        """
    )
    _patch(
        HOME, ((HOME_UNITS_BEFORE, HOME_UNITS_AFTER), (HOME_READINGS_BEFORE, HOME_READINGS_AFTER))
    )
    _patch(OCCUPANCY, ((OCCUPANCY_BEFORE, OCCUPANCY_AFTER),))
    op.execute(f"REVOKE ALL ON FUNCTION {SET_FOR_RENT} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SET_FOR_RENT} TO prm_runtime")


def downgrade() -> None:
    raise RuntimeError("V1.1 rework part 1 migration is forward-only")
