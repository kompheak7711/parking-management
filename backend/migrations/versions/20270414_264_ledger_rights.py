# ruff: noqa: E501
"""General Ledger rights for each role (phase 6 step 1; owner 03/11/2026 06:56, plan L1).

The owner approved the ledger rights table of the phase 6 plan. The Owner does the accountant's
work until one is hired (U1, 02/11/2026). On 03/11/2026 07:03 the owner chose "Manager approves to
the limit": a Manager may approve an Expense request or report up to the Expense limit business
rule and may top up petty cash; above the limit only the Owner approves.

1. Twenty-one new bundle rights in the catalog (provenance ``v1-1-ledger``).
2. ``app.seed_default_role_bundles`` gives a new Property's Owner bundle every bundle right, its
   Manager bundle every bundle right except the Owner-only ledger rights, and its Staff bundle the
   approved list plus ``expenses.request``. Until now the Owner and Manager bundles were the same
   (Q-2026-10-21-162 (b)); the Owner-only ledger rights are the first difference.
3. Each existing default bundle gets a new version with its rights added, and one audit event.

Forward-only, as every other change to the role bundles.
"""

import re

from alembic import op

revision = "20270414_264"
down_revision = "20270413_263"
branch_labels = None
depends_on = None

PROVENANCE = "v1-1-ledger"
# Owner, Manager and Staff.
EVERY_ROLE = (("expenses.request", "Send an Expense request or an Expense report"),)
# Owner and Manager.
OWNER_AND_MANAGER = (
    ("expenses.approve", "Approve or refuse Expense requests and reports up to the Expense limit"),
    ("expenses.record", "Record Expenses, give staff advances and pay staff back"),
    ("ledger.cash_count", "Record a cash count"),
    ("ledger.money_move", "Move money between cash and bank accounts"),
    ("ledger.petty_cash", "Top up petty cash"),
    ("ledger.read", "See the ledger and its reports"),
    ("supplier_bills.manage", "Add Suppliers and record Supplier bills"),
    ("supplier_bills.pay", "Pay a Supplier bill and reverse a bill payment"),
)
# The Owner only (the accountant's work, U1).
OWNER_ONLY = (
    ("expenses.approve_over_limit", "Approve an Expense above the Expense limit"),
    ("ledger.accounts.manage", "Add a ledger account or turn one off"),
    ("ledger.adjustments.approve", "Approve an adjusting entry"),
    ("ledger.adjustments.prepare", "Prepare an adjusting entry"),
    ("ledger.budgets.approve", "Approve a Budget"),
    ("ledger.budgets.prepare", "Prepare a Budget"),
    ("ledger.close", "Close a month or the year"),
    ("ledger.fixed_assets", "Add, depreciate and dispose of Fixed assets"),
    ("ledger.opening_balances", "Enter the Opening balances"),
    ("ledger.owner_money", "Record Owner money put in or taken out"),
    ("ledger.reconcile", "Reconcile a bank account"),
    ("ledger.write_off", "Write off Customer debt"),
)
NEW_CAPABILITIES = EVERY_ROLE + OWNER_AND_MANAGER + OWNER_ONLY

# The default Staff bundle before this change (migration `20270310_229`).
STAFF_BEFORE = (
    "configuration.read", "credits.read", "customer_ledger.read", "customers.manage",
    "customers.read", "deposits.read", "final_settlements.prepare", "identity.read_self",
    "invoices.read", "lease_signers.manage", "leases.draft", "leases.inspect", "leases.move_out",
    "leases.read", "payments.allocate", "payments.read", "payments.record", "property.read",
    "receipts.read", "receipts.reprint", "refunds.create", "refunds.read",
    "rent_nonpayment.case_manage", "rent_nonpayment.event_post", "rent_nonpayment.read",
    "reservations.cancel", "reservations.complete", "reservations.create", "reservations.read",
    "units.read", "utility.calculate", "utility.read", "utility_readings.record",
)
STAFF_AFTER = tuple(sorted(STAFF_BEFORE + tuple(name for name, _ in EVERY_ROLE)))
REASON = (
    "Owner answer 2026-11-03 (General Ledger phase 6 plan L1): ledger rights for the Owner, "
    "Manager and Staff"
)


def _array(names: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{name}'" for name in names) + "]::text[]"


def upgrade() -> None:
    names = tuple(name for name, _ in NEW_CAPABILITIES)
    assert all(re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name) for name in names + STAFF_AFTER)
    assert len(set(names)) == len(names) == 21
    for capability, description in NEW_CAPABILITIES:
        op.execute(
            "INSERT INTO app.capabilities "
            "(capability_id, family, description, grant_path, provenance) VALUES "
            f"('{capability}', pg_catalog.split_part('{capability}', '.', 1), "
            f"'{description.replace(chr(39), chr(39) * 2)}', 'bundle', '{PROVENANCE}')"
        )
    owner_only = _array(tuple(name for name, _ in OWNER_ONLY))
    staff = _array(STAFF_AFTER)
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
            SELECT v_owner, 1, catalog.capability_id
            FROM app.capabilities AS catalog
            WHERE catalog.grant_path = 'bundle';
            -- General Ledger (owner 2026-11-03): the accountant's other rights stay with the
            -- Owner.
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT v_manager, 1, catalog.capability_id
            FROM app.capabilities AS catalog
            WHERE catalog.grant_path = 'bundle'
              AND NOT catalog.capability_id = ANY({owner_only});
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT v_staff, 1, staff.capability_id
            FROM pg_catalog.unnest({staff}) AS staff (capability_id);
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
    every = _array(names)
    manager = _array(tuple(name for name, _ in EVERY_ROLE + OWNER_AND_MANAGER))
    for_staff = _array(tuple(name for name, _ in EVERY_ROLE))
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id
                        WHEN seeded.owner_bundle_id THEN {every}
                        WHEN seeded.manager_bundle_id THEN {manager}
                        ELSE {for_staff}
                    END AS added
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles SET version = v_default.version + 1
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, given
                FROM (
                    SELECT held.capability_id AS given FROM app.role_bundle_capabilities AS held
                    WHERE held.role_bundle_id = v_default.role_bundle_id
                      AND held.version = v_default.version
                    UNION
                    SELECT listed FROM pg_catalog.unnest(v_default.added) AS listed
                ) AS next_set;
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
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1,
                            'added_capability_ids', pg_catalog.to_jsonb(v_default.added)
                        ),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("General Ledger rights are forward-only")
