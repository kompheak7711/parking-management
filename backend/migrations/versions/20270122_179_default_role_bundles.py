"""Seed the default Owner, Manager and Staff role bundles (login slice sub-slice L1c).

DL-074 answer 1, DL-080 item 2, DL-081 (owner answers (a) to Q-2026-10-21-150 and
Q-2026-10-21-164, G7, (a) to Q-2026-10-21-161 and (b) to Q-2026-10-21-162), SEC-021, SEC-022,
API-080, DB-AUTH-009: each Property gets its three default bundles once, as configurable data.
The Owner and Manager bundles hold every catalog capability whose grant path is `bundle`; the
Staff bundle holds the approved daily-work list only. The Owner-class account, which the
bootstrap makes before the Property exists, is given the Owner bundle. A relation records which
bundles are a Property's defaults; seeding again changes nothing. New relation and function
only; the existing Property, if any, is seeded by this migration.
"""

import re

from alembic import op

revision = "20270122_179"
down_revision = "20270121_178"
branch_labels = None
depends_on = None

SEED = "app.seed_default_role_bundles(uuid)"
# Owner answer (a) to Q-2026-10-21-150 with G7 (DL-081); the owner answer (a) to
# Q-2026-10-21-164 keeps the nine unnamed capabilities out of it.
STAFF_CAPABILITIES = (
    "configuration.read",
    "credits.read",
    "customer_ledger.read",
    "customers.manage",
    "customers.read",
    "deposits.read",
    "final_settlements.prepare",
    "identity.read_self",
    "invoices.read",
    "lease_signers.manage",
    "leases.draft",
    "leases.inspect",
    "leases.move_out",
    "leases.read",
    "payments.allocate",
    "payments.read",
    "payments.record",
    "property.read",
    "receipts.read",
    "receipts.reprint",
    "refunds.create",
    "refunds.read",
    "rent_nonpayment.read",
    "reservations.cancel",
    "reservations.complete",
    "reservations.create",
    "reservations.read",
    "units.read",
    "utility.calculate",
    "utility.read",
    "utility_readings.record",
)


def upgrade() -> None:
    """Create the default bundle record and its seed function, then seed every Property."""
    op.execute(
        """
        CREATE TABLE app.default_role_bundles (
            property_id uuid PRIMARY KEY
                REFERENCES app.properties (id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            owner_bundle_id uuid NOT NULL,
            manager_bundle_id uuid NOT NULL,
            staff_bundle_id uuid NOT NULL,
            seeded_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(seeded_at)),
            provenance text NOT NULL
                CHECK (length(btrim(provenance)) > 0 AND length(provenance) <= 500),
            CHECK (
                owner_bundle_id <> manager_bundle_id
                AND owner_bundle_id <> staff_bundle_id
                AND manager_bundle_id <> staff_bundle_id
            ),
            CONSTRAINT default_role_bundles_owner_fkey
                FOREIGN KEY (owner_bundle_id, property_id)
                REFERENCES app.role_bundles (role_bundle_id, property_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            CONSTRAINT default_role_bundles_manager_fkey
                FOREIGN KEY (manager_bundle_id, property_id)
                REFERENCES app.role_bundles (role_bundle_id, property_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT,
            CONSTRAINT default_role_bundles_staff_fkey
                FOREIGN KEY (staff_bundle_id, property_id)
                REFERENCES app.role_bundles (role_bundle_id, property_id)
                ON UPDATE RESTRICT
                ON DELETE RESTRICT
        )
        """
    )
    # The L1b-2 append-only function, so a TRUNCATE that cascades from the bundles reports the
    # same message whichever trigger runs first.
    op.execute(
        """
        CREATE TRIGGER default_role_bundles_are_append_only
        BEFORE UPDATE OR DELETE ON app.default_role_bundles
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_role_bundle_history_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER default_role_bundles_reject_truncate
        BEFORE TRUNCATE ON app.default_role_bundles
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_role_bundle_history_change()
        """
    )
    # Review round 1 note: the list is written into the function text, so each name must stay
    # a plain catalog-form name.
    assert all(re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name) for name in STAFF_CAPABILITIES)
    staff = ", ".join(f"'{capability}'" for capability in STAFF_CAPABILITIES)
    op.execute(
        f"""
        CREATE FUNCTION app.seed_default_role_bundles(p_property_id uuid)
        RETURNS TABLE (owner_bundle_id uuid, manager_bundle_id uuid, staff_bundle_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            v_owner uuid := pg_catalog.gen_random_uuid();
            v_manager uuid := pg_catalog.gen_random_uuid();
            v_staff uuid := pg_catalog.gen_random_uuid();
        BEGIN
            -- Under REPEATABLE READ or SERIALIZABLE the check below could read a snapshot older
            -- than defaults committed while this call waited for the lock (fail closed, as in
            -- login sub-slices L1a and L1b-2).
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'default role bundles are seeded only at READ COMMITTED'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('default-role-bundles:' || p_property_id::text, 0)
            );
            IF NOT EXISTS (
                SELECT 1 FROM app.properties AS property WHERE property.id = p_property_id
            ) THEN
                RAISE EXCEPTION 'the Property does not exist'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            -- Seeding again changes nothing: the defaults are made once per Property, and a
            -- later catalog row is never added to an existing bundle by itself.
            RETURN QUERY
            SELECT seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id
            FROM app.default_role_bundles AS seeded
            WHERE seeded.property_id = p_property_id;
            IF FOUND THEN
                RETURN;
            END IF;
            INSERT INTO app.role_bundles (role_bundle_id, property_id, name, version, provenance)
            VALUES
                (v_owner, p_property_id, 'Owner', 1, 'login-slice-default-bundles'),
                (v_manager, p_property_id, 'Manager', 1, 'login-slice-default-bundles'),
                (v_staff, p_property_id, 'Staff', 1, 'login-slice-default-bundles');
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT bundle.role_bundle_id, 1, catalog.capability_id
            FROM (VALUES (v_owner), (v_manager)) AS bundle (role_bundle_id)
            CROSS JOIN app.capabilities AS catalog
            WHERE catalog.grant_path = 'bundle';
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT v_staff, 1, staff.capability_id
            FROM pg_catalog.unnest(ARRAY[{staff}]::text[]) AS staff (capability_id);
            INSERT INTO app.default_role_bundles (
                property_id, owner_bundle_id, manager_bundle_id, staff_bundle_id, provenance
            ) VALUES (
                p_property_id, v_owner, v_manager, v_staff, 'login-slice-default-bundles'
            );
            -- The bootstrapped Owner exists before the Property; Manager and Staff accounts
            -- get their class's default bundle when they are created (sub-slice L2).
            INSERT INTO app.user_role_assignments (
                assignment_id, actor_id, role_bundle_id, property_id, provenance
            )
            SELECT pg_catalog.gen_random_uuid(), classification.actor_id, v_owner,
                   p_property_id, 'login-slice-default-bundles'
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            RETURN QUERY SELECT v_owner, v_manager, v_staff;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SEED} FROM PUBLIC")
    op.execute("REVOKE ALL ON app.default_role_bundles FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SEED} TO prm_runtime")
    op.execute("SELECT app.seed_default_role_bundles(property.id) FROM app.properties AS property")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("default role bundles migration is forward-only")
