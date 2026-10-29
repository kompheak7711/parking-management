"""Capability catalog of the login slice (sub-slice L1b-1; DL-074, DL-081).

Every capability the server checks has one catalog row in `app.capabilities` (migration
`20270119_176`), with the same identifier and description as here. A role name gives no power by
itself (SEC-021); a bundle or a per-user grant gives capabilities only from this catalog. The
catalog adds names and never renames one. Each capability has one grant path: `bundle` (a role
bundle may hold it), `per_user` (given to one user by the Owner, Q-2026-10-21-151),
`owner_class` (only the Owner account class has it, Q-2026-10-21-162) or `service_principal`
(only a service principal has it).
"""

from typing import Final, Literal, Protocol
from uuid import UUID

from property_rental.identity import CapabilityGrant

IDENTITY_MANAGE_ACCESS_CAPABILITY: Final = "identity.manage_access"
SETTINGS_MANAGE_CAPABILITY: Final = "settings.manage"
OPERATIONS_STATUS_READ_CAPABILITY: Final = "operations.status.read"
PROPERTY_READ_CAPABILITY: Final = "property.read"
UNITS_READ_CAPABILITY: Final = "units.read"
# V1-061 (owner 2026-10-29, DL-110): a Rent below the Unit's default Rent.
RENT_BELOW_DEFAULT_CAPABILITY: Final = "rent.below_default"

CAPABILITY_CATALOG: Final[dict[str, str]] = {
    "audit.export": "Export the audit history",
    "audit.view": "Search and read the audit history",
    "billing.generate": "Start a Rent or Utility billing run and read its status",
    "configuration.read": "Read the Property configuration and rates",
    "credits.applications.reverse": "Reverse a Customer Credit application",
    "credits.apply": "Apply Customer Credit to an Invoice",
    "credits.read": "Read Customer Credit",
    "credits.recognize": "Recognize unallocated Payment value as Customer Credit",
    "credits.reverse": "Reverse a Customer Credit",
    "customer_ledger.read": "Read the Customer ledger",
    "customers.manage": "Create and update Customers",
    "customers.read": "Read Customers",
    "damage_charges.bill": "Bill move-out damage charges",
    "data.export": "Export report data",
    "deposits.correct": "Correct a Deposit disposition",
    "deposits.dispose": "Record a Deposit disposition or forfeiture draft",
    "deposits.manage": "Create Deposits and record Deposit receipts and adjustments",
    "deposits.read": "Read Deposits",
    "deposits.refund.qualify": "Review a Pet Deposit for its Refund",
    "exchange_rates.manage": "Confirm exchange rates",
    "final_settlements.prepare": "Prepare Final Settlement and correction drafts",
    "financial.approve": "Confirm financial drafts",
    "identity.manage_access": "Manage user accounts, role bundles and assignments",
    "identity.read_self": "Read the signed-in account",
    "invoices.adjust": "Adjust an Invoice",
    "invoices.create": "Create Invoices and one-time charges",
    "invoices.issue": "Issue Invoices",
    "invoices.read": "Read Invoices",
    "invoices.void": "Void an Invoice",
    "late_payment.charge_correction": "Correct a late-payment charge",
    "late_payment.final_decision": "Record a final late-payment decision",
    "late_payment.review": "Review late payments",
    "lease_signers.manage": "Add and remove Lease Signers",
    "leases.draft": "Draft and update Leases",
    "leases.inspect": "Record the move-out inspection",
    "leases.move_out": "Record the physical move-out and its final Utility inputs",
    "leases.read": "Read Leases",
    "leases.sign": "Sign a Lease",
    "leases.terminate": "Terminate a Lease",
    "leases.warn": "Record a Lease violation warning",
    "operations.status.read": "Read the operations health page",
    "payments.allocate": "Allocate Payments to Invoices",
    "payments.allocations.reverse": "Reverse a Payment allocation",
    "payments.read": "Read Payments",
    "payments.record": "Record Payments",
    "payments.reverse": "Reverse or return a Payment",
    "property.manage": "Update the Property and create and update Units",
    "property.read": "Read the Property",
    "receipts.read": "Read Receipts",
    "receipts.reprint": "Reprint a Receipt",
    "refunds.correct": "Correct a Refund",
    "refunds.corrections.reverse": "Reverse a Refund correction",
    "refunds.create": "Record Refund drafts",
    "refunds.read": "Read Refunds",
    "rent.below_default": "Agree a Rent below the Unit's default Rent",
    "rent_nonpayment.case_manage": "Open and manage Rent nonpayment cases",
    "rent_nonpayment.evaluate": "Evaluate Rent nonpayment (evaluation principal only)",
    "rent_nonpayment.event_post": "Post Rent nonpayment events",
    "rent_nonpayment.read": "Read Rent nonpayment cases",
    "reports.read": "Read the money reports and the totals by Unit and month",
    "reservation_deposits.correct": "Correct a Reservation Deposit outcome",
    "reservation_deposits.dispose": "Record a Reservation Deposit outcome draft",
    "reservation_deposits.override": "Override a Reservation Deposit outcome",
    "reservation_deposits.refund": "Refund a Reservation Deposit",
    "reservations.cancel": "Cancel a Reservation",
    "reservations.complete": "Complete a Reservation with the move-in",
    "reservations.create": "Create Reservations",
    "reservations.extend": "Extend a Reservation",
    "reservations.read": "Read Reservations",
    "service_rates.manage": "Change Service rates",
    "settings.manage": "Change the Settings (given per user by the Owner only)",
    "units.read": "Read Units and their history",
    "utility.calculate": "Run the Utility calculation",
    "utility.estimate": "Record a broken-Meter estimate",
    "utility.read": "Read Utility readings and periods",
    "utility_meters.manage": "Manage Utility Meters",
    "utility_rates.manage": "Change Utility Rates",
    "utility_readings.correct": "Correct a Utility Reading",
    "utility_readings.record": "Record Utility Readings",
}

GrantPath = Literal["bundle", "per_user", "owner_class", "service_principal"]

PER_USER_CAPABILITIES: Final = frozenset({SETTINGS_MANAGE_CAPABILITY})
OWNER_CLASS_CAPABILITIES: Final = frozenset({IDENTITY_MANAGE_ACCESS_CAPABILITY})
SERVICE_PRINCIPAL_CAPABILITIES: Final = frozenset({"rent_nonpayment.evaluate"})


def capability_grant_path(capability: str) -> GrantPath:
    """Return how a catalog capability can be given; an unknown name is refused."""
    if capability not in CAPABILITY_CATALOG:
        raise KeyError(capability)
    if capability in PER_USER_CAPABILITIES:
        return "per_user"
    if capability in OWNER_CLASS_CAPABILITIES:
        return "owner_class"
    if capability in SERVICE_PRINCIPAL_CAPABILITIES:
        return "service_principal"
    return "bundle"


BUNDLE_CAPABILITIES: Final = frozenset(
    capability for capability in CAPABILITY_CATALOG if capability_grant_path(capability) == "bundle"
)

# The default Staff bundle as sub-slice L1c seeded it (migration `20270122_179`): owner answer
# (a) to Q-2026-10-21-150 with G7, and (a) to Q-2026-10-21-164 (DL-081). The default Owner and
# Manager bundles hold every bundle capability of the catalog when they are seeded.
STAFF_L1C_BUNDLE_CAPABILITIES: Final = frozenset(
    {
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
    }
)

# Owner answer 2026-10-25 (V1-058 R3, DESIGN.md Letters): Staff may record the day-20 and day-30
# Rent letters, so they may open the Rent case and post its letter events (migration
# `20270310_229`). The Termination notice and Terminate stay with the Owner and Managers.
STAFF_RENT_LETTER_CAPABILITIES: Final = frozenset(
    {"rent_nonpayment.case_manage", "rent_nonpayment.event_post"}
)
STAFF_DEFAULT_BUNDLE_CAPABILITIES: Final = (
    STAFF_L1C_BUNDLE_CAPABILITIES | STAFF_RENT_LETTER_CAPABILITIES
)


class GrantCursor(Protocol):
    """Bounded cursor operations used by the grant reader."""

    def __enter__(self) -> "GrantCursor": ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str, parameters: tuple[object, ...]) -> None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class GrantConnection(Protocol):
    """Runtime persistence connection used by the grant reader."""

    def cursor(self) -> GrantCursor: ...


class CapabilityCatalogMismatch(RuntimeError):
    """The database granted a capability the catalog does not name or give that way."""


# The grant paths the reader may return (review round 1 of sub-slice L1b-2): bundle
# capabilities, the Owner account class capability and, from sub-slice L1d, the per-user
# Settings access; never a service principal's capability.
READER_GRANT_PATHS: Final = frozenset({"bundle", "owner_class", "per_user"})


class PostgresCapabilityGrantReader:
    """Read an actor's effective capabilities with their Property scopes (sub-slice L1b-2).

    `app.actor_capability_grants` returns rows only for an active, classified account: the
    current capabilities of its assigned bundles, `identity.manage_access` for the Owner account
    class, and `settings.manage` for the Owner account class and an account given it (L1d; a Staff
    account only while its sign-in code is set up, L1e). A
    name outside the catalog, or one the catalog gives by another grant path, refuses every
    grant (fail closed).
    """

    def __init__(self, connection: GrantConnection) -> None:
        self._connection = connection

    def grants_for(self, actor_id: UUID) -> frozenset[CapabilityGrant]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT capability_id, property_id::text FROM app.actor_capability_grants(%s)",
                (actor_id,),
            )
            rows = cursor.fetchall()
        properties: dict[str, set[str]] = {}
        for capability, property_id in rows:
            if (
                capability not in CAPABILITY_CATALOG
                or capability_grant_path(str(capability)) not in READER_GRANT_PATHS
            ):
                raise CapabilityCatalogMismatch
            properties.setdefault(str(capability), set()).add(str(property_id))
        return frozenset(
            CapabilityGrant(capability=capability, property_ids=frozenset(property_ids))
            for capability, property_ids in properties.items()
        )
