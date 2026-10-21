"""The capability catalog names every capability the application checks (login sub-slice L1b-1).

SEC-001 to SEC-003, SEC-021, API-080, DL-074, DL-081: a capability string that the code checks but
the catalog does not name would be a capability no bundle could ever give (or a typo that denies
for ever), so every dotted string constant in `backend/src` is either a catalog capability or one of
the request-digest, audit-action, log-event and function labels listed here.
"""

import ast
import re
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
    UNITS_READ_CAPABILITY,
    capability_grant_path,
)

SOURCE = Path(__file__).parents[1] / "src" / "property_rental"
DOTTED = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
# Dotted strings that are not capabilities: request-digest and audit-action labels, log events
# and database function names. A new label is added here; a new capability goes in the catalog.
NON_CAPABILITY_LABELS = frozenset(
    {
        "app.utility_catch_up_invoice_create",
        "app.utility_final_invoice_create",
        "application.started",
        "application.stopping",
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
        "request.completed",
        "request.exception",
        "reservation.cancel",
        "reservation.create",
        "reservation.expire",
        "reservation.extend",
        "unit.created",
        "unit.updated",
        "unpaid_initial.moved_in_credit",
        "unpaid_initial.never_moved_in",
        "utility.baseline.record",
        "utility.catch_up_invoice.create",
        "utility.final_invoice.create",
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
    # The 70 capabilities the application checks today are all in the catalog.
    assert len(found - NON_CAPABILITY_LABELS) == 70
    # Review round 1: a capability constant added to the catalog module itself is a catalog name.
    assert dotted_constants(SOURCE / "access_control.py") - set(CAPABILITY_CATALOG) == set()


def test_the_catalog_holds_the_approved_new_names() -> None:
    assert len(CAPABILITY_CATALOG) == 75
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
    assert len(BUNDLE_CAPABILITIES) == 72
    with pytest.raises(KeyError):
        capability_grant_path("reports.export")
