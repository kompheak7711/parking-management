"""The capability catalog names every capability the application checks (login sub-slice L1b-1).

SEC-001 to SEC-003, SEC-021, API-080, DL-074, DL-081: a capability string that the code checks but
the catalog does not name would be a capability no bundle could ever give (or a typo that denies
for ever), so every dotted string constant in `backend/src` is either a catalog capability or one of
the request-digest, audit-action, log-event and function labels listed here.
"""

import ast
import re
import uuid
from pathlib import Path

import pytest

from property_rental.access_control import (
    BUNDLE_CAPABILITIES,
    CAPABILITY_CATALOG,
    IDENTITY_MANAGE_ACCESS_CAPABILITY,
    OPERATIONS_STATUS_READ_CAPABILITY,
    OWNER_CLASS_CAPABILITIES,
    PER_USER_CAPABILITIES,
    PROPERTY_READ_CAPABILITY,
    SERVICE_PRINCIPAL_CAPABILITIES,
    SETTINGS_MANAGE_CAPABILITY,
    STAFF_DEFAULT_BUNDLE_CAPABILITIES,
    UNITS_READ_CAPABILITY,
    CapabilityCatalogMismatch,
    PostgresCapabilityGrantReader,
    capability_grant_path,
)
from property_rental.identity import CapabilityGrant

SOURCE = Path(__file__).parents[1] / "src" / "property_rental"
DOTTED = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
# Dotted strings that are not capabilities: request-digest and audit-action labels, log events
# and database function names (V1-059 part A adds its log events, configuration field names and
# work file names). A new label is added here; a new capability goes in the catalog.
NON_CAPABILITY_LABELS = frozenset(
    {
        "alerts.disk_paths",
        "alerts.telegram",
        "alerts.telegram.api_host",
        "app.utility_catch_up_invoice_create",
        "app.utility_final_invoice_create",
        "application.started",
        "application.stopping",
        "backup.config_invalid",
        "backup.database_url_file",
        "backup.directory",
        "backup.encryption_key_file",
        "backup.offhost_copy_succeeded",
        "backup.pgdump",
        "backup.skipped",
        "backup.succeeded",
        "backup.tool_failed",
        "backup.verified",
        "deposit.pet.create",
        "deposit.pet_departure.record",
        "deposit.pet_refund.review",
        "deposit.receipt.record",
        "deposit.required.adjust",
        "deposit.security.create",
        "http.request",
        "lease.cancel",
        "lease.draft",
        "lease.draft.update",
        "lease.inspection.record",
        "lease.move_out.final_inputs.record",
        "lease.move_out.record",
        "lease.notice.record",
        "lease.sign",
        "lease.signer.add",
        "lease.signer.remove",
        "lease.signer.sign",
        "lease.terminate",
        "log_retention.completed",
        "log_retention.config_invalid",
        "logs.directory",
        "opened.pgdump",
        "operations_check.completed",
        "operations_check.config_invalid",
        "operations_check.migration_recorded",
        "request.completed",
        "request.exception",
        "reservation.cancel",
        "reservation.create",
        "reservation.expire",
        "reservation.extend",
        "restore.pgdump",
        "restore_test.counts_differ",
        "restore_test.succeeded",
        "security.protected_key_file_missing",
        "unit.created",
        "unit.updated",
        "unit.status_changed",
        "unit.rent_terms_changed",
        "unpaid_initial.moved_in_credit",
        "unpaid_initial.never_moved_in",
        "utility.baseline.record",
        "utility.catch_up_invoice.create",
        "utility.final_invoice.create",
        # The sign-in clean-up command's log events (V1-056 slice 12c), not capabilities.
        "sign_in_prune.completed",
        "sign_in_prune.config_invalid",
        "sign_in_prune.failed",
        "sign_in_prune.usage",
    }
)


def dotted_constants(path: Path) -> set[str]:
    return {
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and DOTTED.fullmatch(node.value)
    }


def application_constants() -> set[str]:
    found: set[str] = set()
    for path in SOURCE.rglob("*.py"):
        if path.name != "access_control.py":
            found |= dotted_constants(path)
    return found


def test_the_capability_catalog_names_every_capability_the_code_checks() -> None:
    found = application_constants()
    assert found - NON_CAPABILITY_LABELS <= set(CAPABILITY_CATALOG)
    assert not NON_CAPABILITY_LABELS & set(CAPABILITY_CATALOG)
    # Every label listed is still used, so the list cannot hide a removed capability.
    assert NON_CAPABILITY_LABELS <= found
    # The 68 capabilities the application checks today are all in the catalog (login sub-slice
    # L5: `service_rates.manage` and `utility_rates.manage` no longer open a route), with the
    # three V1-057 report and export rights, and V1-061 `rent.below_default`.
    assert len(found - NON_CAPABILITY_LABELS) == 71
    # Review round 1: a capability constant added to the catalog module itself is a catalog name.
    assert dotted_constants(SOURCE / "access_control.py") - set(CAPABILITY_CATALOG) == set()


def test_the_catalog_holds_the_approved_new_names() -> None:
    assert len(CAPABILITY_CATALOG) == 79
    assert list(CAPABILITY_CATALOG) == sorted(CAPABILITY_CATALOG)
    assert all(DOTTED.fullmatch(name) and len(name) <= 128 for name in CAPABILITY_CATALOG)
    assert all(description.strip() for description in CAPABILITY_CATALOG.values())
    assert {
        SETTINGS_MANAGE_CAPABILITY,
        OPERATIONS_STATUS_READ_CAPABILITY,
        PROPERTY_READ_CAPABILITY,
        UNITS_READ_CAPABILITY,
        "rent_nonpayment.evaluate",
    } <= set(CAPABILITY_CATALOG)
    assert {
        SETTINGS_MANAGE_CAPABILITY,
        OPERATIONS_STATUS_READ_CAPABILITY,
        PROPERTY_READ_CAPABILITY,
        UNITS_READ_CAPABILITY,
        "rent_nonpayment.evaluate",
    } & application_constants() == set()


def test_each_capability_has_one_grant_path() -> None:
    """Q-2026-10-21-151 (a), Q-2026-10-21-161 (a) and Q-2026-10-21-162 (b)."""
    sets = (PER_USER_CAPABILITIES, OWNER_CLASS_CAPABILITIES, SERVICE_PRINCIPAL_CAPABILITIES)
    # Review round 2: the sets do not overlap, so no capability can silently take the first path.
    assert sum(len(found) for found in sets) == len(frozenset().union(*sets))
    paths = {capability: capability_grant_path(capability) for capability in CAPABILITY_CATALOG}
    assert {capability for capability, path in paths.items() if path != "bundle"} == {
        SETTINGS_MANAGE_CAPABILITY,
        IDENTITY_MANAGE_ACCESS_CAPABILITY,
        "rent_nonpayment.evaluate",
    }
    assert paths[SETTINGS_MANAGE_CAPABILITY] == "per_user"
    assert paths[IDENTITY_MANAGE_ACCESS_CAPABILITY] == "owner_class"
    assert paths["rent_nonpayment.evaluate"] == "service_principal"
    assert paths["billing.generate"] == "bundle"
    assert BUNDLE_CAPABILITIES == {c for c, path in paths.items() if path == "bundle"}
    assert len(BUNDLE_CAPABILITIES) == 76
    with pytest.raises(KeyError):
        capability_grant_path("reports.export")


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        assert "app.actor_capability_grants" in query and len(parameters) == 1

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self.rows)


def test_the_grant_reader_groups_property_ids_and_refuses_names_it_may_not_give() -> None:
    reader = PostgresCapabilityGrantReader(
        _FakeConnection([("leases.read", "p1"), ("leases.read", "p2"), ("units.read", "p1")])
    )
    assert reader.grants_for(uuid.uuid4()) == frozenset(
        {
            CapabilityGrant("leases.read", frozenset({"p1", "p2"})),
            CapabilityGrant("units.read", frozenset({"p1"})),
        }
    )
    assert PostgresCapabilityGrantReader(_FakeConnection([])).grants_for(uuid.uuid4()) == (
        frozenset()
    )
    for refused_name in ("reports.export", "rent_nonpayment.evaluate"):
        # Review round 1: also a catalog name the reader may not give (a service principal's;
        # the per-user Settings access is given from sub-slice L1d).
        with pytest.raises(CapabilityCatalogMismatch):
            PostgresCapabilityGrantReader(
                _FakeConnection([("leases.read", "p1"), (refused_name, "p1")])
            ).grants_for(uuid.uuid4())
    assert PostgresCapabilityGrantReader(
        _FakeConnection([("identity.manage_access", "p1"), ("settings.manage", "p1")])
    ).grants_for(uuid.uuid4()) == frozenset(
        {
            CapabilityGrant("identity.manage_access", frozenset({"p1"})),
            CapabilityGrant("settings.manage", frozenset({"p1"})),
        }
    )


# Owner answer (a) to Q-2026-10-21-150 (DL-081): what Staff get, with G7's two payment lines.
STAFF_APPROVED = frozenset(
    {
        "identity.read_self",
        "customers.read",
        "customers.manage",
        "reservations.read",
        "reservations.create",
        "utility.read",
        "utility_readings.record",
        "payments.read",
        "payments.record",
        "payments.allocate",
        "receipts.read",
        "final_settlements.prepare",
        "leases.read",
        "invoices.read",
        "deposits.read",
        "credits.read",
        "refunds.read",
        "customer_ledger.read",
        "rent_nonpayment.read",
        # Owner answer 2026-10-25: Staff record the day-20 and day-30 Rent letters.
        "rent_nonpayment.case_manage",
        "rent_nonpayment.event_post",
        "configuration.read",
        "units.read",
        "property.read",
        "reservations.cancel",
        "reservations.complete",
        "leases.draft",
        "lease_signers.manage",
        "leases.inspect",
        "leases.move_out",
        "utility.calculate",
        "receipts.reprint",
        "refunds.create",
    }
)
# What Staff never get (DL-081, Q-150 (a) with the owner's note, DL-080 item 2, Q-161 (a)); the
# names that are not bundle capabilities can never be in any bundle.
STAFF_NEVER = frozenset(
    {
        "financial.approve",
        "invoices.void",
        "audit.view",
        # DL-072 answer 5: no money reports, no audit export and no data export for Staff.
        "reports.read",
        "audit.export",
        "data.export",
        "operations.status.read",
        "leases.warn",
        "utility_readings.correct",
        "utility_meters.manage",
        "utility.estimate",
        "invoices.create",
        "invoices.issue",
        "invoices.adjust",
        "damage_charges.bill",
        "deposits.manage",
        "deposits.refund.qualify",
        "reservation_deposits.refund",
        "payments.reverse",
        "payments.allocations.reverse",
        "credits.recognize",
        "credits.apply",
        "credits.reverse",
        "credits.applications.reverse",
        "late_payment.review",
        "exchange_rates.manage",
        "leases.sign",
        "reservations.extend",
        "leases.terminate",
        "billing.generate",
        "property.manage",
    }
)
# Owner answer (a) to Q-2026-10-21-164: none of these nine is in the Staff bundle.
STAFF_NOT_NAMED = frozenset(
    {
        "deposits.dispose",
        "deposits.correct",
        "reservation_deposits.dispose",
        "reservation_deposits.correct",
        "reservation_deposits.override",
        "refunds.correct",
        "refunds.corrections.reverse",
        "late_payment.charge_correction",
        "late_payment.final_decision",
        # V1-061 (owner 2026-10-29, DL-110): a Rent below the Unit's default needs a Manager.
        "rent.below_default",
    }
)
# Replaced by `settings.manage` in sub-slice L5 (Q-2026-10-21-151 (a)); not in the Staff bundle.
RATE_CAPABILITIES = frozenset({"service_rates.manage", "utility_rates.manage"})


def test_the_default_staff_bundle_holds_exactly_the_approved_daily_work() -> None:
    assert STAFF_DEFAULT_BUNDLE_CAPABILITIES == STAFF_APPROVED
    assert len(STAFF_APPROVED) == 33
    assert STAFF_APPROVED <= BUNDLE_CAPABILITIES
    groups = (STAFF_APPROVED, STAFF_NEVER, STAFF_NOT_NAMED, RATE_CAPABILITIES)
    # Every bundle capability is in exactly one group, so a new bundle capability must be
    # placed by the owner before the Staff list can be called complete.
    assert sum(len(group) for group in groups) == len(BUNDLE_CAPABILITIES)
    assert frozenset().union(*groups) == BUNDLE_CAPABILITIES
    assert not STAFF_APPROVED & (
        OWNER_CLASS_CAPABILITIES | PER_USER_CAPABILITIES | SERVICE_PRINCIPAL_CAPABILITIES
    )
