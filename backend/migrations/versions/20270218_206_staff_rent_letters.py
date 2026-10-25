"""Staff may record the day-20 and day-30 Rent letters (V1-058 R3, owner answer 2026-10-25).

The owner answered "Yes, staff may record letters" on 25/10/2026, in line with the 24/10/2026
round 8 answer (DESIGN.md Letters: Staff may record the day-20 and day-30 letters; only the
Termination notice needs the Owner or a Manager). The default Staff bundle gains
`rent_nonpayment.case_manage` (open the Rent case) and `rent_nonpayment.event_post` (record a
letter on it).

- The seed function now seeds new Properties with the longer Staff list.
- A Property's default Staff bundle that is still exactly as seeded (version 1 with the L1c list)
  gets version 2 with the two rights, through the normal bundle version history, and an audit
  event names the owner answer. A Staff bundle the Owner already changed stays as it is.

Additive only: a new function body and new bundle versions; nothing is removed.
"""

import re

from alembic import op

revision = "20270218_206"
down_revision = "20270217_205"
branch_labels = None
depends_on = None

L1C_STAFF_CAPABILITIES = (
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

LETTER_CAPABILITIES = ("rent_nonpayment.case_manage", "rent_nonpayment.event_post")
STAFF_CAPABILITIES = tuple(sorted(L1C_STAFF_CAPABILITIES + LETTER_CAPABILITIES))
REASON = "Owner answer 2026-10-25: Staff may record the day-20 and day-30 Rent letters"


def upgrade() -> None:
    """Seed new Properties with the letter rights and add them to untouched Staff defaults."""
    assert all(re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name) for name in STAFF_CAPABILITIES)
    staff = ", ".join(f"'{capability}'" for capability in STAFF_CAPABILITIES)
    l1c = ", ".join(f"'{capability}'" for capability in L1C_STAFF_CAPABILITIES)
    letters = ", ".join(f"'{capability}'" for capability in LETTER_CAPABILITIES)
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.seed_default_role_bundles(p_property_id uuid)
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
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id = seeded.staff_bundle_id
                WHERE bundle.version = 1
                  AND (
                      SELECT pg_catalog.array_agg(held.capability_id ORDER BY held.capability_id)
                      FROM app.role_bundle_capabilities AS held
                      WHERE held.role_bundle_id = bundle.role_bundle_id AND held.version = 1
                  ) = (
                      SELECT pg_catalog.array_agg(listed ORDER BY listed)
                      FROM pg_catalog.unnest(ARRAY[{l1c}]::text[]) AS listed
                  )
                ORDER BY seeded.property_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = 2
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, 2, listed
                FROM pg_catalog.unnest(ARRAY[{staff}]::text[]) AS listed;
                -- The audit names the Owner whose answer this is, when the Owner account exists.
                SELECT classification.actor_id INTO v_owner
                FROM app.user_account_classes AS classification
                WHERE classification.account_class = 'owner';
                SELECT property.timezone_name INTO v_timezone
                FROM app.properties AS property WHERE property.id = v_default.property_id;
                IF v_owner IS NOT NULL THEN
                    INSERT INTO app.audit_events (
                        id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                        reason, authorization_reference, property_id, previous_state,
                        resulting_state, correlation_id, source, outcome
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_at,
                        pg_catalog.timezone(v_timezone, v_at)::date, v_owner,
                        'identity.role_bundle.updated', 'role_bundle', v_default.role_bundle_id,
                        '{REASON}', 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', 1),
                        pg_catalog.jsonb_build_object(
                            'version', 2,
                            'added_capability_ids', pg_catalog.to_jsonb(ARRAY[{letters}]::text[])
                        ),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END;
        $$
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("Staff Rent letter rights migration is forward-only")
