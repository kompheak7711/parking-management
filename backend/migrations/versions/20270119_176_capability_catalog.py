"""Add the capability catalog (login slice sub-slice L1b-1).

SEC-001 to SEC-003, SEC-020, SEC-021, API-080, DL-074, DL-081 (owner answers (a) to
Q-2026-10-21-151, Q-2026-10-21-158 and Q-2026-10-21-160): every capability the server checks has one
append-only catalog row. Seeded with the 71 capabilities checked today (70 in the application,
`rent_nonpayment.evaluate` in the database) and the four approved new names `settings.manage`,
`operations.status.read`, `property.read` and `units.read`. Each row has one grant path:
`bundle`, `per_user` (`settings.manage`, Q-2026-10-21-151), `owner_class`
(`identity.manage_access`, Q-2026-10-21-162 (b)) or `service_principal`
(`rent_nonpayment.evaluate`); `billing.generate` is a bundle capability (Q-2026-10-21-161 (a)).
`UNIQUE (capability_id, grant_path)` lets a later role-bundle relation refer to bundle
capabilities only. A new relation only: no lock on any existing table.
"""

from alembic import op
from sqlalchemy import text

revision = "20270119_176"
down_revision = "20270118_175"
branch_labels = None
depends_on = None

# (capability, description, grant path); the same rows as
# `property_rental.access_control.CAPABILITY_CATALOG` when this migration was written.
CAPABILITIES = (
    ("audit.view", "Search and read the audit history", "bundle"),
    ("billing.generate", "Start a Rent or Utility billing run and read its status", "bundle"),
    ("configuration.read", "Read the Property configuration and rates", "bundle"),
    ("credits.applications.reverse", "Reverse a Customer Credit application", "bundle"),
    ("credits.apply", "Apply Customer Credit to an Invoice", "bundle"),
    ("credits.read", "Read Customer Credit", "bundle"),
    ("credits.recognize", "Recognize unallocated Payment value as Customer Credit", "bundle"),
    ("credits.reverse", "Reverse a Customer Credit", "bundle"),
    ("customer_ledger.read", "Read the Customer ledger", "bundle"),
    ("customers.manage", "Create and update Customers", "bundle"),
    ("customers.read", "Read Customers", "bundle"),
    ("damage_charges.bill", "Bill move-out damage charges", "bundle"),
    ("deposits.correct", "Correct a Deposit disposition", "bundle"),
    ("deposits.dispose", "Record a Deposit disposition or forfeiture draft", "bundle"),
    ("deposits.manage", "Create Deposits and record Deposit receipts and adjustments", "bundle"),
    ("deposits.read", "Read Deposits", "bundle"),
    ("deposits.refund.qualify", "Review a Pet Deposit for its Refund", "bundle"),
    ("exchange_rates.manage", "Confirm exchange rates", "bundle"),
    ("final_settlements.prepare", "Prepare Final Settlement and correction drafts", "bundle"),
    ("financial.approve", "Confirm financial drafts", "bundle"),
    ("identity.manage_access", "Manage user accounts, role bundles and assignments", "owner_class"),
    ("identity.read_self", "Read the signed-in account", "bundle"),
    ("invoices.adjust", "Adjust an Invoice", "bundle"),
    ("invoices.create", "Create Invoices and one-time charges", "bundle"),
    ("invoices.issue", "Issue Invoices", "bundle"),
    ("invoices.read", "Read Invoices", "bundle"),
    ("invoices.void", "Void an Invoice", "bundle"),
    ("late_payment.charge_correction", "Correct a late-payment charge", "bundle"),
    ("late_payment.final_decision", "Record a final late-payment decision", "bundle"),
    ("late_payment.review", "Review late payments", "bundle"),
    ("lease_signers.manage", "Add and remove Lease Signers", "bundle"),
    ("leases.draft", "Draft and update Leases", "bundle"),
    ("leases.inspect", "Record the move-out inspection", "bundle"),
    ("leases.move_out", "Record the physical move-out and its final Utility inputs", "bundle"),
    ("leases.read", "Read Leases", "bundle"),
    ("leases.sign", "Sign a Lease", "bundle"),
    ("leases.terminate", "Terminate a Lease", "bundle"),
    ("leases.warn", "Record a Lease violation warning", "bundle"),
    ("operations.status.read", "Read the operations health page", "bundle"),
    ("payments.allocate", "Allocate Payments to Invoices", "bundle"),
    ("payments.allocations.reverse", "Reverse a Payment allocation", "bundle"),
    ("payments.read", "Read Payments", "bundle"),
    ("payments.record", "Record Payments", "bundle"),
    ("payments.reverse", "Reverse or return a Payment", "bundle"),
    ("property.manage", "Update the Property and create and update Units", "bundle"),
    ("property.read", "Read the Property", "bundle"),
    ("receipts.read", "Read Receipts", "bundle"),
    ("receipts.reprint", "Reprint a Receipt", "bundle"),
    ("refunds.correct", "Correct a Refund", "bundle"),
    ("refunds.corrections.reverse", "Reverse a Refund correction", "bundle"),
    ("refunds.create", "Record Refund drafts", "bundle"),
    ("refunds.read", "Read Refunds", "bundle"),
    ("rent_nonpayment.case_manage", "Open and manage Rent nonpayment cases", "bundle"),
    (
        "rent_nonpayment.evaluate",
        "Evaluate Rent nonpayment (evaluation principal only)",
        "service_principal",
    ),
    ("rent_nonpayment.event_post", "Post Rent nonpayment events", "bundle"),
    ("rent_nonpayment.read", "Read Rent nonpayment cases", "bundle"),
    ("reservation_deposits.correct", "Correct a Reservation Deposit outcome", "bundle"),
    ("reservation_deposits.dispose", "Record a Reservation Deposit outcome draft", "bundle"),
    ("reservation_deposits.override", "Override a Reservation Deposit outcome", "bundle"),
    ("reservation_deposits.refund", "Refund a Reservation Deposit", "bundle"),
    ("reservations.cancel", "Cancel a Reservation", "bundle"),
    ("reservations.complete", "Complete a Reservation with the move-in", "bundle"),
    ("reservations.create", "Create Reservations", "bundle"),
    ("reservations.extend", "Extend a Reservation", "bundle"),
    ("reservations.read", "Read Reservations", "bundle"),
    ("service_rates.manage", "Change Service rates", "bundle"),
    ("settings.manage", "Change the Settings (given per user by the Owner only)", "per_user"),
    ("units.read", "Read Units and their history", "bundle"),
    ("utility.calculate", "Run the Utility calculation", "bundle"),
    ("utility.estimate", "Record a broken-Meter estimate", "bundle"),
    ("utility.read", "Read Utility readings and periods", "bundle"),
    ("utility_meters.manage", "Manage Utility Meters", "bundle"),
    ("utility_rates.manage", "Change Utility Rates", "bundle"),
    ("utility_readings.correct", "Correct a Utility Reading", "bundle"),
    ("utility_readings.record", "Record Utility Readings", "bundle"),
)


def upgrade() -> None:
    """Create the append-only catalog, seed it and let the runtime role read it."""
    op.execute(
        """
        CREATE TABLE app.capabilities (
            capability_id text PRIMARY KEY
                CHECK (
                    length(capability_id) <= 128
                    AND capability_id ~ '^[a-z][a-z_]*(\\.[a-z][a-z_]*)+$'
                ),
            family text NOT NULL
                CHECK (family = pg_catalog.split_part(capability_id, '.', 1)),
            description text NOT NULL CHECK (length(btrim(description)) > 0),
            grant_path text NOT NULL
                CHECK (grant_path IN ('bundle', 'per_user', 'owner_class', 'service_principal')),
            added_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(added_at)),
            provenance text NOT NULL CHECK (length(btrim(provenance)) > 0),
            CONSTRAINT capabilities_capability_grant_path_key UNIQUE (capability_id, grant_path)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.reject_capability_catalog_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'capability catalog is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER capabilities_are_append_only
        BEFORE UPDATE OR DELETE ON app.capabilities
        FOR EACH ROW
        EXECUTE FUNCTION app.reject_capability_catalog_change()
        """
    )
    op.execute(
        """
        CREATE TRIGGER capabilities_reject_truncate
        BEFORE TRUNCATE ON app.capabilities
        FOR EACH STATEMENT
        EXECUTE FUNCTION app.reject_capability_catalog_change()
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.reject_capability_catalog_change() FROM PUBLIC")
    insert = text(
        "INSERT INTO app.capabilities "
        "(capability_id, family, description, grant_path, provenance) "
        "VALUES (:capability, pg_catalog.split_part(:capability, '.', 1), :description, "
        ":grant_path, 'login-slice-capability-catalog')"
    )
    for capability, description, grant_path in CAPABILITIES:
        op.get_bind().execute(
            insert,
            {"capability": capability, "description": description, "grant_path": grant_path},
        )
    op.execute("REVOKE ALL ON app.capabilities FROM PUBLIC")
    op.execute("GRANT SELECT ON app.capabilities TO prm_runtime")


def downgrade() -> None:
    """Refuse destructive rollback; recovery requires a reviewed forward fix."""
    raise RuntimeError("capability catalog migration is forward-only")
