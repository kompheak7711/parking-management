# ruff: noqa: E501
"""V1.1 part 3 (owner 2026-11-03 "Continue your task"): roles and permissions.

The V1.1 rework plan (part 3) and the owner's answers of 01/11/2026 (GL Q5: full control of
users, roles and permissions; the Owner role always keeps "Users and roles") and 02/11/2026
(E2 only the Owner manages users at the start; E4 the Settings access ticks become the role
right "Change business rules"; PR-HR-002 a user may have several roles). Mock-up v76, Users and
access > Roles. Technical choices by Claude under the owner's 2026-10-23 22:30 rule.

1. A permissions list: ``permission_groups`` and ``permissions`` with English and Khmer names,
   each permission giving a set of the existing capabilities (``permission_capabilities``).
   Every bundle capability belongs to exactly one permission, so the Owner, Manager and Staff
   roles are each a set of whole permissions. ``BASIC`` (sign in, see the Property, its Units
   and its setup) is in every role and is not shown. ``USERS`` (Users and roles) stays the
   Owner's own (``identity.manage_access`` by the Owner class) and is shown locked.
2. A role has a Khmer name and can be turned off. A role with users cannot be turned off, a
   turned-off role cannot be given and gives nothing, and the Owner role is never renamed or
   turned off. One Owner: the Owner role is given only to the Owner, who always keeps it.
   The name, the Khmer name, the state and the new ``settings_access`` flag are
   kept on every version.
3. "Change business rules" is a role right (``settings_access`` on the role version, giving
   ``settings.manage``), with the DL-081 rule kept: for a Staff account it works only while its
   sign-in code is set up, and a Staff account gets such a role only after setting the code
   up. The Owner role gets it. Each person who had the old per-user Settings access gets a new
   role "Change business rules" in its place (their rights do not change) and the old grant is
   removed with a reason. The old per-user path still works for a grant given later through
   the old API; the screen no longer gives one.
4. New Owner reads ``admin_roles`` and ``admin_role_assignments`` and changes
   ``admin_create_role`` and ``admin_change_role``; ``permission_catalog`` for the screen.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20270423_273"
down_revision: str | None = "20270422_272"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE = "v1-1-roles-permissions"
REASON = "Owner answer 2026-11-02 E4: Settings access is now the role right Change business rules"

GROUPS = (
    ("OPERATIONS", "Operations", "ប្រតិបត្តិការ"),
    ("LEASING", "Leasing", "ការជួល"),
    ("PROPERTY", "Property", "អចលនទ្រព្យ"),
    ("MONEY", "Money approval", "ការអនុម័តប្រាក់"),
    ("LEDGER", "Ledger", "សៀវភៅបញ្ជី"),
    ("ADMIN", "Administration", "រដ្ឋបាល"),
)

# (code, group, English, Khmer, capabilities). BASIC has no group: it is in every role.
PERMISSIONS: tuple[tuple[str, str | None, str, str, tuple[str, ...]], ...] = (
    (
        "BASIC",
        None,
        "Sign in and see the Property, its Units and its setup",
        "ចូលប្រើ និងមើលអចលនទ្រព្យ បន្ទប់ និងការកំណត់",
        ("configuration.read", "identity.read_self", "property.read", "units.read"),
    ),
    (
        "PAY_OPEN",
        "OPERATIONS",
        "Open Payments, Receipts and Customer accounts",
        "បើកការទូទាត់ បង្កាន់ដៃ និងគណនីអតិថិជន",
        (
            "credits.read",
            "customer_ledger.read",
            "deposits.read",
            "payments.read",
            "receipts.read",
            "receipts.reprint",
            "refunds.read",
        ),
    ),
    (
        "PAY_RECV",
        "OPERATIONS",
        "Receive payment",
        "ទទួលប្រាក់",
        ("payments.allocate", "payments.record"),
    ),
    ("INV_OPEN", "OPERATIONS", "Open Invoices", "បើកវិក្កយបត្រ", ("invoices.read",)),
    (
        "INV_MAKE",
        "OPERATIONS",
        "Make and issue Invoices, run billing",
        "ធ្វើ និងចេញវិក្កយបត្រ ដំណើរការការចេញវិក្កយបត្រ",
        ("billing.generate", "damage_charges.bill", "invoices.create", "invoices.issue"),
    ),
    (
        "UTIL",
        "OPERATIONS",
        "Utilities and meter readings",
        "ទឹកភ្លើង និងការអានកុងទ័រ",
        ("utility.calculate", "utility.read", "utility_readings.record"),
    ),
    (
        "UTIL_FIX",
        "OPERATIONS",
        "Correct meter readings and estimate use",
        "កែការអានកុងទ័រ និងប៉ាន់ស្មានការប្រើប្រាស់",
        ("utility.estimate", "utility_readings.correct"),
    ),
    (
        "RES",
        "LEASING",
        "Reservations",
        "ការកក់",
        (
            "reservations.cancel",
            "reservations.complete",
            "reservations.create",
            "reservations.read",
        ),
    ),
    ("RES_EXTEND", "LEASING", "Extend a Reservation", "ពន្យារការកក់", ("reservations.extend",)),
    (
        "LEASE",
        "LEASING",
        "Leases, move-out and unpaid Rent cases",
        "កិច្ចសន្យាជួល ការចេញ និងករណីមិនបង់ថ្លៃជួល",
        (
            "final_settlements.prepare",
            "lease_signers.manage",
            "leases.draft",
            "leases.inspect",
            "leases.move_out",
            "leases.read",
            "rent_nonpayment.case_manage",
            "rent_nonpayment.event_post",
            "rent_nonpayment.read",
        ),
    ),
    (
        "LEASE_SIGN",
        "LEASING",
        "Sign, warn and end Leases",
        "ចុះហត្ថលេខា ព្រមាន និងបញ្ចប់កិច្ចសន្យាជួល",
        ("leases.sign", "leases.terminate", "leases.warn"),
    ),
    ("CUST", "LEASING", "Customers", "អតិថិជន", ("customers.manage", "customers.read")),
    (
        "SETUP",
        "PROPERTY",
        "Property details, Units, rates and meters",
        "ព័ត៌មានអចលនទ្រព្យ បន្ទប់ អត្រា និងកុងទ័រ",
        (
            "exchange_rates.manage",
            "property.manage",
            "service_rates.manage",
            "utility_meters.manage",
            "utility_rates.manage",
        ),
    ),
    ("DRAFT", "MONEY", "Prepare drafts", "រៀបចំសេចក្តីព្រាង", ("refunds.create",)),
    (
        "APPROVE",
        "MONEY",
        "Approve financial records (void, adjust, waive, settle, refund)",
        "អនុម័តកំណត់ត្រាហិរញ្ញវត្ថុ (ទុកជាមោឃៈ កែតម្រូវ លើកលែង ទូទាត់ សងប្រាក់)",
        (
            "credits.applications.reverse",
            "credits.apply",
            "credits.recognize",
            "credits.reverse",
            "deposits.correct",
            "deposits.dispose",
            "deposits.manage",
            "deposits.refund.qualify",
            "financial.approve",
            "invoices.adjust",
            "invoices.void",
            "late_payment.charge_correction",
            "late_payment.final_decision",
            "late_payment.review",
            "payments.allocations.reverse",
            "payments.reverse",
            "refunds.correct",
            "refunds.corrections.reverse",
            "rent.below_default",
            "reservation_deposits.correct",
            "reservation_deposits.dispose",
            "reservation_deposits.override",
            "reservation_deposits.refund",
        ),
    ),
    (
        "GL_REQ",
        "LEDGER",
        "Send an Expense request or report",
        "ផ្ញើសំណើ ឬរបាយការណ៍ចំណាយ",
        ("expenses.request",),
    ),
    (
        "GL_REQOK",
        "LEDGER",
        "Approve up to the Expense limit, top up petty cash",
        "អនុម័តរហូតដល់កម្រិតចំណាយ បំពេញសាច់ប្រាក់តូចតាច",
        ("expenses.approve", "ledger.petty_cash"),
    ),
    (
        "GL_SEE",
        "LEDGER",
        "See the ledger and its reports",
        "មើលសៀវភៅបញ្ជី និងរបាយការណ៍",
        ("ledger.read",),
    ),
    (
        "GL_EXP",
        "LEDGER",
        "Record a bill, give an advance, pay staff back",
        "កត់ត្រាវិក្កយបត្រ ផ្ដល់ប្រាក់បុរេប្រទាន សងប្រាក់បុគ្គលិក",
        (
            "expenses.record",
            "ledger.cash_count",
            "ledger.money_move",
            "supplier_bills.manage",
            "supplier_bills.pay",
        ),
    ),
    (
        "GL_EXPOK",
        "LEDGER",
        "Approve above the Expense limit",
        "អនុម័តលើសកម្រិតចំណាយ",
        ("expenses.approve_over_limit",),
    ),
    (
        "GL_MANUAL",
        "LEDGER",
        "Adjusting entries",
        "ធាតុកែតម្រូវ",
        ("ledger.adjustments.approve", "ledger.adjustments.prepare"),
    ),
    (
        "GL_ACCT",
        "LEDGER",
        "Accounts, opening balances, fixed assets and budgets",
        "គណនី សមតុល្យដើមគ្រា ទ្រព្យសកម្មថេរ និងថវិកា",
        (
            "ledger.accounts.manage",
            "ledger.budgets.approve",
            "ledger.budgets.prepare",
            "ledger.fixed_assets",
            "ledger.opening_balances",
        ),
    ),
    (
        "GL_CLOSE",
        "LEDGER",
        "Close a month, reconcile the bank",
        "បិទខែ ផ្ទៀងផ្ទាត់ធនាគារ",
        ("ledger.close", "ledger.reconcile"),
    ),
    (
        "GL_OWNER",
        "LEDGER",
        "Owner money and writing off debt",
        "ប្រាក់ម្ចាស់ និងការលុបបំណុល",
        ("ledger.owner_money", "ledger.write_off"),
    ),
    (
        "REPORTS",
        "ADMIN",
        "Reports and exports",
        "របាយការណ៍ និងការនាំចេញ",
        ("data.export", "reports.read"),
    ),
    ("HISTORY", "ADMIN", "Audit log", "កំណត់ហេតុសវនកម្ម", ("audit.export", "audit.view")),
    ("RULES", "ADMIN", "Change business rules", "ប្ដូរច្បាប់អាជីវកម្ម", ("settings.manage",)),
    ("HEALTH", "ADMIN", "System health", "សុខភាពប្រព័ន្ធ", ("operations.status.read",)),
    ("USERS", "ADMIN", "Users and roles", "អ្នកប្រើ និងតួនាទី", ("identity.manage_access",)),
)

ROLE_NAMES_KH = (("owner", "ម្ចាស់"), ("manager", "អ្នកគ្រប់គ្រង"), ("staff", "បុគ្គលិក"))
RULES_ROLE = ("Change business rules", "ប្ដូរច្បាប់អាជីវកម្ម")


def _text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    codes = [code for code, *_ in PERMISSIONS]
    every = [name for *_, names in PERMISSIONS for name in names]
    assert len(set(codes)) == len(codes) and len(set(every)) == len(every)
    group_rows = ",\n            ".join(
        f"({_text(code)}, {number}, {_text(en)}, {_text(kh)})"
        for number, (code, en, kh) in enumerate(GROUPS, start=1)
    )
    permission_rows = ",\n            ".join(
        f"({_text(code)}, {'NULL' if group is None else _text(group)}, {number}, {_text(en)}, {_text(kh)})"
        for number, (code, group, en, kh, _names) in enumerate(PERMISSIONS, start=1)
    )
    capability_rows = ",\n            ".join(
        f"({_text(code)}, {_text(name)})" for code, *_, names in PERMISSIONS for name in names
    )
    names_kh = " ".join(
        f"WHEN seeded.{kind}_bundle_id THEN {_text(kh)}" for kind, kh in ROLE_NAMES_KH
    )
    op.execute(
        f"""
        -- 1. The permissions list.
        CREATE FUNCTION app.reject_permission_catalog_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'the permissions list only grows' USING ERRCODE = 'integrity_constraint_violation';
        END $$;
        REVOKE ALL ON FUNCTION app.reject_permission_catalog_change() FROM PUBLIC;

        CREATE TABLE app.permission_groups (
            group_code text PRIMARY KEY CHECK (group_code ~ '^[A-Z][A-Z_]{{1,19}}$'),
            sort_order integer NOT NULL UNIQUE CHECK (sort_order > 0),
            name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 80),
            name_kh text NOT NULL CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 80),
            added_at timestamptz NOT NULL DEFAULT pg_catalog.statement_timestamp(),
            provenance text NOT NULL CHECK (length(btrim(provenance)) BETWEEN 1 AND 200)
        );
        CREATE TABLE app.permissions (
            permission_code text PRIMARY KEY CHECK (permission_code ~ '^[A-Z][A-Z_]{{1,29}}$'),
            group_code text REFERENCES app.permission_groups (group_code)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            sort_order integer NOT NULL UNIQUE CHECK (sort_order > 0),
            name_en text NOT NULL CHECK (name_en = btrim(name_en) AND length(name_en) BETWEEN 1 AND 120),
            name_kh text NOT NULL CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 120),
            added_at timestamptz NOT NULL DEFAULT pg_catalog.statement_timestamp(),
            provenance text NOT NULL CHECK (length(btrim(provenance)) BETWEEN 1 AND 200),
            -- BASIC alone has no group: it is in every role and is not shown.
            CONSTRAINT permissions_basic_alone_has_no_group
                CHECK ((group_code IS NULL) = (permission_code = 'BASIC'))
        );
        CREATE TABLE app.permission_capabilities (
            permission_code text NOT NULL REFERENCES app.permissions (permission_code)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            capability_id text NOT NULL UNIQUE REFERENCES app.capabilities (capability_id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            added_at timestamptz NOT NULL DEFAULT pg_catalog.statement_timestamp(),
            provenance text NOT NULL CHECK (length(btrim(provenance)) BETWEEN 1 AND 200),
            PRIMARY KEY (permission_code, capability_id)
        );
        CREATE TRIGGER permission_groups_only_grow BEFORE UPDATE OR DELETE ON app.permission_groups
            FOR EACH ROW EXECUTE FUNCTION app.reject_permission_catalog_change();
        CREATE TRIGGER permission_groups_reject_truncate BEFORE TRUNCATE ON app.permission_groups
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_permission_catalog_change();
        CREATE TRIGGER permissions_only_grow BEFORE UPDATE OR DELETE ON app.permissions
            FOR EACH ROW EXECUTE FUNCTION app.reject_permission_catalog_change();
        CREATE TRIGGER permissions_reject_truncate BEFORE TRUNCATE ON app.permissions
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_permission_catalog_change();
        CREATE TRIGGER permission_capabilities_only_grow BEFORE UPDATE OR DELETE ON app.permission_capabilities
            FOR EACH ROW EXECUTE FUNCTION app.reject_permission_catalog_change();
        CREATE TRIGGER permission_capabilities_reject_truncate BEFORE TRUNCATE ON app.permission_capabilities
            FOR EACH STATEMENT EXECUTE FUNCTION app.reject_permission_catalog_change();
        REVOKE ALL ON app.permission_groups, app.permissions, app.permission_capabilities FROM PUBLIC;

        INSERT INTO app.permission_groups (group_code, sort_order, name_en, name_kh, provenance)
        SELECT code, sort_order, name_en, name_kh, '{PROVENANCE}' FROM (VALUES
            {group_rows}
        ) AS listed (code, sort_order, name_en, name_kh);
        INSERT INTO app.permissions (permission_code, group_code, sort_order, name_en, name_kh, provenance)
        SELECT code, group_code, sort_order, name_en, name_kh, '{PROVENANCE}' FROM (VALUES
            {permission_rows}
        ) AS listed (code, group_code, sort_order, name_en, name_kh);
        INSERT INTO app.permission_capabilities (permission_code, capability_id, provenance)
        SELECT code, capability_id, '{PROVENANCE}' FROM (VALUES
            {capability_rows}
        ) AS listed (code, capability_id);

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM app.capabilities AS catalog
                WHERE catalog.grant_path <> 'service_principal'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.permission_capabilities AS listed
                      WHERE listed.capability_id = catalog.capability_id)
            ) THEN
                RAISE EXCEPTION 'every capability a person can hold must be in one permission';
            END IF;
        END $$;

        CREATE FUNCTION app.permission_catalog()
        RETURNS TABLE (permission_code text, group_code text, group_sort integer,
            group_name_en text, group_name_kh text, sort_order integer, name_en text,
            name_kh text, capability_ids text[])
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT permission.permission_code, permission.group_code, grouped.sort_order,
                   grouped.name_en, grouped.name_kh, permission.sort_order, permission.name_en,
                   permission.name_kh,
                   (SELECT pg_catalog.array_agg(listed.capability_id ORDER BY listed.capability_id)
                    FROM app.permission_capabilities AS listed
                    WHERE listed.permission_code = permission.permission_code)
            FROM app.permissions AS permission
            LEFT JOIN app.permission_groups AS grouped ON grouped.group_code = permission.group_code
            ORDER BY permission.sort_order
        $$;
        REVOKE ALL ON FUNCTION app.permission_catalog() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.permission_catalog() TO prm_runtime;

        -- 2 and 3. Khmer name, turned off and Change business rules on every role version.
        ALTER TABLE app.role_bundles
            ADD COLUMN name_kh text CHECK (name_kh = btrim(name_kh) AND length(name_kh) BETWEEN 1 AND 128
                AND name_kh !~ '[[:cntrl:]]'),
            ADD COLUMN turned_off boolean NOT NULL DEFAULT false,
            ADD COLUMN settings_access boolean NOT NULL DEFAULT false;
        ALTER TABLE app.role_bundle_versions
            ADD COLUMN name_kh text,
            ADD COLUMN turned_off boolean NOT NULL DEFAULT false,
            ADD COLUMN settings_access boolean NOT NULL DEFAULT false;
        CREATE OR REPLACE FUNCTION app.record_role_bundle_version()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO app.role_bundle_versions (role_bundle_id, version, name, name_kh,
                turned_off, settings_access)
            VALUES (NEW.role_bundle_id, NEW.version, NEW.name, NEW.name_kh, NEW.turned_off,
                NEW.settings_access);
            RETURN NULL;
        END $$;
        CREATE OR REPLACE FUNCTION app.require_role_bundle_version_of_bundle()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NOT EXISTS (
                   SELECT 1
                   FROM app.role_bundles AS bundle
                   WHERE bundle.role_bundle_id = NEW.role_bundle_id
                     AND bundle.version = NEW.version
                     AND bundle.name = NEW.name
                     AND bundle.name_kh IS NOT DISTINCT FROM NEW.name_kh
                     AND bundle.turned_off = NEW.turned_off
                     AND bundle.settings_access = NEW.settings_access
               )
               OR NEW.recorded_transaction IS DISTINCT FROM pg_catalog.pg_current_xact_id()
               OR NEW.recorded_transaction_started_at
                  IS DISTINCT FROM pg_catalog.transaction_timestamp() THEN
                RAISE EXCEPTION 'a role bundle version is written only with its bundle'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END $$;

        -- What a person may do: a turned-off role gives nothing; Change business rules on a
        -- role keeps the DL-081 rule for a Staff account.
        CREATE OR REPLACE FUNCTION app.actor_capability_grants(p_actor_id uuid)
        RETURNS TABLE (capability_id text, property_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            WITH account AS (
                SELECT classification.account_class
                FROM app.user_accounts AS account
                JOIN app.user_account_classes AS classification
                  ON classification.actor_id = account.actor_id
                WHERE account.actor_id = p_actor_id
                  AND account.lifecycle_state = 'active'
            ),
            held AS (
                SELECT bundle.role_bundle_id, bundle.property_id, bundle.version,
                       bundle.settings_access
                FROM account
                CROSS JOIN app.user_role_assignments AS assignment
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id = assignment.role_bundle_id
                 AND bundle.property_id = assignment.property_id
                WHERE assignment.actor_id = p_actor_id
                  AND NOT bundle.turned_off
                  AND NOT EXISTS (
                      SELECT 1
                      FROM app.user_role_assignment_removals AS removal
                      WHERE removal.assignment_id = assignment.assignment_id
                  )
            )
            SELECT bundle_capability.capability_id, held.property_id
            FROM held
            JOIN app.role_bundle_capabilities AS bundle_capability
              ON bundle_capability.role_bundle_id = held.role_bundle_id
             AND bundle_capability.version = held.version
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = bundle_capability.capability_id
             AND catalog.grant_path = 'bundle'
            UNION
            SELECT catalog.capability_id, held.property_id
            FROM held
            CROSS JOIN account
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = 'settings.manage'
             AND catalog.grant_path = 'per_user'
            WHERE held.settings_access
              AND (
                  account.account_class IN ('owner', 'manager')
                  OR (
                      account.account_class = 'staff'
                      AND app.staff_sign_in_code_is_set_up(p_actor_id)
                  )
              )
            UNION
            SELECT catalog.capability_id, property.id
            FROM account
            CROSS JOIN app.properties AS property
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = 'identity.manage_access'
             AND catalog.grant_path = 'owner_class'
            WHERE account.account_class = 'owner'
            UNION
            SELECT catalog.capability_id, property.id
            FROM account
            CROSS JOIN app.properties AS property
            JOIN app.capabilities AS catalog
              ON catalog.capability_id = 'settings.manage'
             AND catalog.grant_path = 'per_user'
            WHERE account.account_class = 'owner'
               OR (
                   EXISTS (
                       SELECT 1
                       FROM app.user_capability_grants AS given
                       WHERE given.actor_id = p_actor_id
                         AND given.capability_id = catalog.capability_id
                         AND NOT EXISTS (
                             SELECT 1
                             FROM app.user_capability_grant_removals AS removal
                             WHERE removal.grant_id = given.grant_id
                         )
                   )
                   -- Owner rule of 2026-10-21 (DL-081): a Staff account's Settings access
                   -- works only while its sign-in code is set up, whatever path changed it.
                   AND (
                       account.account_class = 'manager'
                       OR (
                           account.account_class = 'staff'
                           AND app.staff_sign_in_code_is_set_up(p_actor_id)
                       )
                   )
               )
        $$;

        -- 4. The Owner's reads.
        CREATE FUNCTION app.admin_roles(p_owner_id uuid)
        RETURNS TABLE (role_bundle_id uuid, property_id uuid, name text, name_kh text,
            version integer, turned_off boolean, owner_role boolean, capability_ids text[],
            holders integer)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            RETURN QUERY
            SELECT bundle.role_bundle_id, bundle.property_id, bundle.name, bundle.name_kh,
                   bundle.version, bundle.turned_off,
                   EXISTS (SELECT 1 FROM app.default_role_bundles AS seeded
                           WHERE seeded.owner_bundle_id = bundle.role_bundle_id),
                   COALESCE((
                       SELECT pg_catalog.array_agg(listed ORDER BY listed)
                       FROM (
                           SELECT held.capability_id AS listed
                           FROM app.role_bundle_capabilities AS held
                           WHERE held.role_bundle_id = bundle.role_bundle_id
                             AND held.version = bundle.version
                           UNION
                           SELECT 'settings.manage' WHERE bundle.settings_access
                       ) AS every_one
                   ), '{{}}'),
                   (SELECT pg_catalog.count(*)::integer
                    FROM app.user_role_assignments AS assignment
                    WHERE assignment.role_bundle_id = bundle.role_bundle_id
                      AND NOT EXISTS (
                          SELECT 1 FROM app.user_role_assignment_removals AS removal
                          WHERE removal.assignment_id = assignment.assignment_id))
            FROM app.role_bundles AS bundle
            ORDER BY bundle.created_at, bundle.role_bundle_id;
        END $$;
        REVOKE ALL ON FUNCTION app.admin_roles(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.admin_roles(uuid) TO prm_runtime;

        CREATE FUNCTION app.admin_role_assignments(p_owner_id uuid)
        RETURNS TABLE (actor_id uuid, role_bundle_id uuid)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            RETURN QUERY
            SELECT assignment.actor_id, assignment.role_bundle_id
            FROM app.user_role_assignments AS assignment
            WHERE NOT EXISTS (
                SELECT 1 FROM app.user_role_assignment_removals AS removal
                WHERE removal.assignment_id = assignment.assignment_id)
            ORDER BY assignment.actor_id, assignment.assigned_at, assignment.role_bundle_id;
        END $$;
        REVOKE ALL ON FUNCTION app.admin_role_assignments(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.admin_role_assignments(uuid) TO prm_runtime;

        -- The capabilities a role keeps: every one it is given, plus BASIC; Change business
        -- rules is the role's flag, never a bundle row.
        CREATE FUNCTION app.role_capability_set(p_capabilities text[])
        RETURNS text[] LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
            SELECT app.bundle_capability_set(ARRAY(
                SELECT given FROM pg_catalog.unnest(p_capabilities) AS given
                WHERE given IS DISTINCT FROM 'settings.manage'
                UNION
                SELECT listed.capability_id FROM app.permission_capabilities AS listed
                WHERE listed.permission_code = 'BASIC'
            ))
        $$;
        REVOKE ALL ON FUNCTION app.role_capability_set(text[]) FROM PUBLIC;

        CREATE FUNCTION app.refuse_staff_rules_role_without_code(p_actor_id uuid)
        RETURNS void LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
        BEGIN
            IF EXISTS (
                   SELECT 1 FROM app.user_account_classes AS classification
                   WHERE classification.actor_id = p_actor_id
                     AND classification.account_class = 'staff')
               AND NOT app.staff_sign_in_code_is_set_up(p_actor_id) THEN
                RAISE EXCEPTION
                    'a Staff account gets Change business rules only after it has set up its sign-in code'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
        END $$;
        REVOKE ALL ON FUNCTION app.refuse_staff_rules_role_without_code(uuid) FROM PUBLIC;

        CREATE FUNCTION app.admin_create_role(p_owner_id uuid, p_property_id uuid, p_name text,
            p_name_kh text, p_capabilities text[], p_correlation_id uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_bundle_id uuid := pg_catalog.gen_random_uuid();
            v_set text[];
            v_rules boolean;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            IF p_property_id IS DISTINCT FROM app.administered_property() THEN
                RAISE EXCEPTION 'the Property does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            IF p_capabilities IS NULL THEN
                RAISE EXCEPTION 'only bundle capabilities can be in a role bundle'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            v_set := app.role_capability_set(p_capabilities);
            v_rules := 'settings.manage' = ANY (p_capabilities);
            INSERT INTO app.role_bundles (role_bundle_id, property_id, name, name_kh, version,
                settings_access, provenance)
            VALUES (v_bundle_id, p_property_id, p_name, p_name_kh, 1, v_rules,
                'owner-role-create');
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT v_bundle_id, 1, given FROM pg_catalog.unnest(v_set) AS given;
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_bundle.created', 'role_bundle', v_bundle_id,
                'Owner created the role', NULL,
                pg_catalog.jsonb_build_object(
                    'name', p_name, 'name_kh', p_name_kh, 'version', 1,
                    'settings_access', v_rules, 'turned_off', false,
                    'capability_ids', pg_catalog.to_jsonb(v_set)),
                p_correlation_id);
            RETURN v_bundle_id;
        END $$;
        REVOKE ALL ON FUNCTION app.admin_create_role(uuid, uuid, text, text, text[], uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.admin_create_role(uuid, uuid, text, text, text[], uuid) TO prm_runtime;

        CREATE FUNCTION app.admin_change_role(p_owner_id uuid, p_role_bundle_id uuid,
            p_expected_version integer, p_name text, p_name_kh text, p_capabilities text[],
            p_turned_off boolean, p_correlation_id uuid)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            v_bundle app.role_bundles%ROWTYPE;
            v_old text[];
            v_new text[];
            v_rules boolean;
            v_owner_role boolean;
            v_holder uuid;
            v_revoked integer := 0;
        BEGIN
            PERFORM app.assert_access_administrator(p_owner_id);
            IF p_name IS NULL OR p_capabilities IS NULL OR p_turned_off IS NULL THEN
                RAISE EXCEPTION 'a role is saved with its name, its rights and its state'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            SELECT bundle.* INTO v_bundle FROM app.role_bundles AS bundle
            WHERE bundle.role_bundle_id = p_role_bundle_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'the role bundle does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            IF p_expected_version IS DISTINCT FROM v_bundle.version THEN
                RAISE EXCEPTION 'the role bundle changed since it was read'
                    USING ERRCODE = 'serialization_failure';
            END IF;
            v_owner_role := EXISTS (SELECT 1 FROM app.default_role_bundles AS seeded
                                    WHERE seeded.owner_bundle_id = p_role_bundle_id);
            IF v_owner_role AND (p_turned_off OR p_name IS DISTINCT FROM v_bundle.name
                                 OR p_name_kh IS DISTINCT FROM v_bundle.name_kh) THEN
                RAISE EXCEPTION 'the Owner role is never renamed or turned off'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF p_turned_off AND NOT v_bundle.turned_off AND EXISTS (
                   SELECT 1 FROM app.user_role_assignments AS assignment
                   WHERE assignment.role_bundle_id = p_role_bundle_id
                     AND NOT EXISTS (
                         SELECT 1 FROM app.user_role_assignment_removals AS removal
                         WHERE removal.assignment_id = assignment.assignment_id)) THEN
                RAISE EXCEPTION 'a role with users cannot be turned off; give them another role first'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            SELECT COALESCE(pg_catalog.array_agg(held.capability_id ORDER BY held.capability_id), '{{}}')
            INTO v_old
            FROM app.role_bundle_capabilities AS held
            WHERE held.role_bundle_id = p_role_bundle_id AND held.version = v_bundle.version;
            v_new := app.role_capability_set(p_capabilities);
            v_rules := 'settings.manage' = ANY (p_capabilities);
            IF v_rules AND NOT v_bundle.settings_access THEN
                FOR v_holder IN
                    SELECT DISTINCT assignment.actor_id
                    FROM app.user_role_assignments AS assignment
                    WHERE assignment.role_bundle_id = p_role_bundle_id
                      AND NOT EXISTS (
                          SELECT 1 FROM app.user_role_assignment_removals AS removal
                          WHERE removal.assignment_id = assignment.assignment_id)
                LOOP
                    PERFORM app.refuse_staff_rules_role_without_code(v_holder);
                END LOOP;
            END IF;
            UPDATE app.role_bundles
            SET name = p_name, name_kh = p_name_kh, turned_off = p_turned_off,
                settings_access = v_rules, version = version + 1
            WHERE role_bundle_id = p_role_bundle_id;
            INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
            SELECT p_role_bundle_id, v_bundle.version + 1, given FROM pg_catalog.unnest(v_new) AS given;
            -- DL-057, SEC-017: a material privilege reduction revokes the applicable sessions.
            IF EXISTS (SELECT 1 FROM pg_catalog.unnest(v_old) AS given WHERE NOT given = ANY (v_new))
               OR (v_bundle.settings_access AND NOT v_rules) THEN
                FOR v_holder IN
                    SELECT DISTINCT assignment.actor_id
                    FROM app.user_role_assignments AS assignment
                    WHERE assignment.role_bundle_id = p_role_bundle_id
                      AND NOT EXISTS (
                          SELECT 1 FROM app.user_role_assignment_removals AS removal
                          WHERE removal.assignment_id = assignment.assignment_id)
                    ORDER BY assignment.actor_id
                LOOP
                    v_revoked := v_revoked + app.revoke_live_sessions(
                        v_holder, p_owner_id, 'material_privilege_reduction',
                        'access-admin-role-bundle-reduced');
                END LOOP;
            END IF;
            PERFORM app.record_access_administration(
                p_owner_id, 'identity.role_bundle.updated', 'role_bundle', p_role_bundle_id,
                'Owner changed the role',
                pg_catalog.jsonb_build_object(
                    'name', v_bundle.name, 'name_kh', v_bundle.name_kh, 'version', v_bundle.version,
                    'settings_access', v_bundle.settings_access, 'turned_off', v_bundle.turned_off,
                    'capability_ids', pg_catalog.to_jsonb(v_old)),
                pg_catalog.jsonb_build_object(
                    'name', p_name, 'name_kh', p_name_kh, 'version', v_bundle.version + 1,
                    'settings_access', v_rules, 'turned_off', p_turned_off,
                    'capability_ids', pg_catalog.to_jsonb(v_new), 'sessions_revoked', v_revoked),
                p_correlation_id);
            RETURN v_bundle.version + 1;
        END $$;
        REVOKE ALL ON FUNCTION app.admin_change_role(uuid, uuid, integer, text, text, text[], boolean, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.admin_change_role(uuid, uuid, integer, text, text, text[], boolean, uuid) TO prm_runtime;
        """
    )
    # A turned-off role is never given; a Staff account gets a Change business rules role only
    # with its sign-in code set up (DL-081).
    _patch(ASSIGN, ASSIGN_BEFORE, ASSIGN_AFTER)
    _patch(REMOVE, REMOVE_BEFORE, REMOVE_AFTER)
    _patch(SEED, SEED_BEFORE, SEED_AFTER)
    op.execute(
        f"""
        DO $$
        DECLARE
            v_default record;
            v_owner uuid;
            v_timezone text;
            v_at timestamptz := pg_catalog.statement_timestamp();
            v_rules_role uuid;
            v_given record;
            v_property uuid;
        BEGIN
            SELECT classification.actor_id INTO v_owner
            FROM app.user_account_classes AS classification
            WHERE classification.account_class = 'owner';
            -- The default roles get their Khmer names; the Owner role gets Change business rules.
            FOR v_default IN
                SELECT seeded.property_id, bundle.role_bundle_id, bundle.version,
                    CASE bundle.role_bundle_id {names_kh} END AS name_kh,
                    bundle.role_bundle_id = seeded.owner_bundle_id AS owner_role
                FROM app.default_role_bundles AS seeded
                JOIN app.role_bundles AS bundle
                  ON bundle.role_bundle_id IN (
                      seeded.owner_bundle_id, seeded.manager_bundle_id, seeded.staff_bundle_id)
                ORDER BY seeded.property_id, bundle.role_bundle_id
                FOR UPDATE OF bundle
            LOOP
                UPDATE app.role_bundles
                SET version = v_default.version + 1, name_kh = v_default.name_kh,
                    settings_access = v_default.owner_role
                WHERE role_bundle_id = v_default.role_bundle_id;
                INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                SELECT v_default.role_bundle_id, v_default.version + 1, held.capability_id
                FROM app.role_bundle_capabilities AS held
                WHERE held.role_bundle_id = v_default.role_bundle_id
                  AND held.version = v_default.version;
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
                        {_text(REASON)}, 'identity.manage_access', v_default.property_id,
                        pg_catalog.jsonb_build_object('version', v_default.version),
                        pg_catalog.jsonb_build_object(
                            'version', v_default.version + 1, 'name_kh', v_default.name_kh,
                            'settings_access', v_default.owner_role),
                        pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED'
                    );
                END IF;
            END LOOP;
            -- Each person with the old Settings access gets the role Change business rules.
            FOR v_given IN
                SELECT given.grant_id, given.actor_id
                FROM app.user_capability_grants AS given
                JOIN app.user_account_classes AS classification
                  ON classification.actor_id = given.actor_id
                 AND classification.account_class IN ('manager', 'staff')
                WHERE given.capability_id = 'settings.manage'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.user_capability_grant_removals AS removal
                      WHERE removal.grant_id = given.grant_id)
                ORDER BY given.given_at, given.grant_id
            LOOP
                SELECT property.id, property.timezone_name INTO v_property, v_timezone
                FROM app.properties AS property;
                IF v_rules_role IS NULL THEN
                    v_rules_role := pg_catalog.gen_random_uuid();
                    INSERT INTO app.role_bundles (role_bundle_id, property_id, name, name_kh,
                        version, settings_access, provenance)
                    VALUES (v_rules_role, v_property, {_text(RULES_ROLE[0])}, {_text(RULES_ROLE[1])},
                        1, true, '{PROVENANCE}');
                    INSERT INTO app.role_bundle_capabilities (role_bundle_id, version, capability_id)
                    SELECT v_rules_role, 1, listed.capability_id
                    FROM app.permission_capabilities AS listed
                    WHERE listed.permission_code = 'BASIC';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM app.user_role_assignments AS assignment
                    WHERE assignment.actor_id = v_given.actor_id
                      AND assignment.role_bundle_id = v_rules_role
                ) THEN
                    INSERT INTO app.user_role_assignments (
                        assignment_id, actor_id, role_bundle_id, property_id,
                        assigned_by_actor_id, provenance
                    ) VALUES (
                        pg_catalog.gen_random_uuid(), v_given.actor_id, v_rules_role, v_property,
                        v_owner, '{PROVENANCE}');
                END IF;
                INSERT INTO app.user_capability_grant_removals (
                    grant_id, removed_by_actor_id, reason, provenance)
                VALUES (v_given.grant_id, v_owner, {_text(REASON)}, '{PROVENANCE}');
                INSERT INTO app.audit_events (
                    id, occurred_at, business_date, actor_id, action, entity_type, entity_id,
                    reason, authorization_reference, property_id, previous_state,
                    resulting_state, correlation_id, source, outcome
                ) VALUES (
                    pg_catalog.gen_random_uuid(), v_at, pg_catalog.timezone(v_timezone, v_at)::date,
                    v_owner, 'identity.role_assignment.created', 'user_account', v_given.actor_id,
                    {_text(REASON)}, 'identity.manage_access', v_property,
                    pg_catalog.jsonb_build_object('settings_access_grant_id', v_given.grant_id),
                    pg_catalog.jsonb_build_object('role_bundle_id', v_rules_role),
                    pg_catalog.gen_random_uuid(), 'ADMINISTRATIVE', 'SUCCEEDED');
            END LOOP;
        END $$;
        """
    )


ASSIGN = "app.admin_assign_role_bundle(uuid,uuid,uuid,uuid)"
ASSIGN_BEFORE = """            IF v_property_id IS NULL THEN
                RAISE EXCEPTION 'the role bundle does not exist' USING ERRCODE = 'no_data_found';
            END IF;"""
ASSIGN_AFTER = """            IF v_property_id IS NULL THEN
                RAISE EXCEPTION 'the role bundle does not exist' USING ERRCODE = 'no_data_found';
            END IF;
            -- V1.1 part 3: a turned-off role is never given; Change business rules needs a Staff
            -- account's sign-in code (DL-081).
            IF EXISTS (SELECT 1 FROM app.role_bundles AS bundle
                       WHERE bundle.role_bundle_id = p_role_bundle_id AND bundle.turned_off) THEN
                RAISE EXCEPTION 'a turned-off role cannot be given'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            IF EXISTS (SELECT 1 FROM app.role_bundles AS bundle
                       WHERE bundle.role_bundle_id = p_role_bundle_id AND bundle.settings_access) THEN
                PERFORM app.refuse_staff_rules_role_without_code(p_actor_id);
            END IF;
            -- One Owner: the Owner role is only for the Owner account.
            IF EXISTS (SELECT 1 FROM app.default_role_bundles AS seeded
                       WHERE seeded.owner_bundle_id = p_role_bundle_id)
               AND NOT EXISTS (SELECT 1 FROM app.user_account_classes AS classification
                               WHERE classification.actor_id = p_actor_id
                                 AND classification.account_class = 'owner') THEN
                RAISE EXCEPTION 'the Owner role is only for the Owner'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;"""

REMOVE = "app.admin_remove_role_assignment(uuid,uuid,uuid,text,uuid)"
REMOVE_BEFORE = """            IF v_assignment_id IS NULL THEN
                RAISE EXCEPTION 'this account does not have that role bundle'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;"""
REMOVE_AFTER = """            IF v_assignment_id IS NULL THEN
                RAISE EXCEPTION 'this account does not have that role bundle'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            -- V1.1 part 3: the Owner always keeps the Owner role.
            IF EXISTS (SELECT 1 FROM app.default_role_bundles AS seeded
                       WHERE seeded.owner_bundle_id = p_role_bundle_id)
               AND EXISTS (SELECT 1 FROM app.user_account_classes AS classification
                           WHERE classification.actor_id = p_actor_id
                             AND classification.account_class = 'owner') THEN
                RAISE EXCEPTION 'the Owner always keeps the Owner role'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;"""


SEED = "app.seed_default_role_bundles(uuid)"
SEED_BEFORE = """            INSERT INTO app.role_bundles (role_bundle_id, property_id, name, version, provenance)
            VALUES
                (v_owner, p_property_id, 'Owner', 1, 'login-slice-default-bundles'),
                (v_manager, p_property_id, 'Manager', 1, 'login-slice-default-bundles'),
                (v_staff, p_property_id, 'Staff', 1, 'login-slice-default-bundles');"""
SEED_AFTER = """            -- V1.1 part 3: Khmer names; the Owner role has Change business rules.
            INSERT INTO app.role_bundles (role_bundle_id, property_id, name, name_kh, version,
                settings_access, provenance)
            VALUES
                (v_owner, p_property_id, 'Owner', 'ម្ចាស់', 1, true, 'login-slice-default-bundles'),
                (v_manager, p_property_id, 'Manager', 'អ្នកគ្រប់គ្រង', 1, false,
                 'login-slice-default-bundles'),
                (v_staff, p_property_id, 'Staff', 'បុគ្គលិក', 1, false,
                 'login-slice-default-bundles');"""


def _patch(signature: str, before: str, after: str) -> None:
    definition = str(
        op.get_bind()
        .execute(
            text("SELECT pg_catalog.pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": signature},
        )
        .scalar_one()
    )
    if definition.count(before) != 1:
        raise RuntimeError(f"{signature} does not have the expected text")
    op.execute(text(definition.replace(before, after)))


def downgrade() -> None:
    raise RuntimeError("V1.1 part 3 migration is forward-only")
