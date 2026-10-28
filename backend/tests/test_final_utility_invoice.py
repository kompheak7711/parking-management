"""Final and catch-up Utility Invoice command validation without a database."""

from datetime import date
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.final_utility_invoice import (
    CATCH_UP_CAPABILITIES,
    FINAL_CAPABILITIES,
    CatchUpUtilityInvoice,
    CreateFinalUtilityInvoice,
    FinalUtilityInvoiceAuthorizationError,
    FinalUtilityInvoiceConflictError,
    FinalUtilityInvoiceInvalidError,
    PostgresFinalUtilityInvoiceService,
    utility_invoice_digest,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant

NIL = UUID(int=0)


def test_final_invoice_needs_the_issue_and_calculate_capabilities_and_catch_up_only_issue() -> None:
    assert FINAL_CAPABILITIES == ("invoices.issue", "utility.calculate")
    assert CATCH_UP_CAPABILITIES == ("invoices.issue",)


def test_commands_require_nonzero_identities() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    for args in ((NIL, b, c), (a, NIL, c), (a, b, NIL)):
        with pytest.raises(FinalUtilityInvoiceInvalidError):
            CreateFinalUtilityInvoice(*args)
        with pytest.raises(FinalUtilityInvoiceInvalidError):
            CatchUpUtilityInvoice(*args)


def test_due_date_override_needs_a_date_and_a_normalized_reason_together() -> None:
    base = (uuid4(), uuid4(), uuid4())
    with pytest.raises(FinalUtilityInvoiceInvalidError):
        CreateFinalUtilityInvoice(*base, due_date=date(2026, 10, 9))
    with pytest.raises(FinalUtilityInvoiceInvalidError):
        CreateFinalUtilityInvoice(*base, due_date_reason="Owner agreed")
    for reason in ("", " padded", "x" * 501, "bad\x00"):
        with pytest.raises(FinalUtilityInvoiceInvalidError):
            CatchUpUtilityInvoice(*base, due_date=date(2026, 10, 9), due_date_reason=reason)
    with pytest.raises(FinalUtilityInvoiceInvalidError):
        CatchUpUtilityInvoice(*base, due_date="2026-10-09", due_date_reason="Owner agreed")  # type: ignore[arg-type]
    value = CatchUpUtilityInvoice(*base, due_date=date(2026, 10, 9), due_date_reason="Owner agreed")
    assert value.intent()["due_date"] == "2026-10-09"
    assert CatchUpUtilityInvoice(*base).intent()["due_date"] is None


def test_digest_binds_the_action_scope_and_intent() -> None:
    prop, lease = uuid4(), uuid4()
    intent = CreateFinalUtilityInvoice(uuid4(), uuid4(), uuid4()).intent()
    digest = utility_invoice_digest("utility.final_invoice.create", prop, lease, intent)
    assert digest == utility_invoice_digest(
        "utility.final_invoice.create", prop, lease, dict(intent)
    )
    assert digest != utility_invoice_digest("utility.catch_up_invoice.create", prop, lease, intent)
    assert digest != utility_invoice_digest("utility.final_invoice.create", prop, uuid4(), intent)
    assert digest != utility_invoice_digest("utility.final_invoice.create", uuid4(), lease, intent)


def test_service_checks_capabilities_before_touching_the_database() -> None:
    prop, lease = uuid4(), uuid4()
    only_issue = AuthenticatedActor(
        str(uuid4()), frozenset({CapabilityGrant("invoices.issue", frozenset({str(prop)}))})
    )
    service = PostgresFinalUtilityInvoiceService("postgresql://unreachable.invalid/none")
    with pytest.raises(FinalUtilityInvoiceAuthorizationError):
        service.create_final(
            prop,
            lease,
            CreateFinalUtilityInvoice(uuid4(), uuid4(), uuid4()),
            actor=only_issue,
            request_id="unit-test",
        )


def _refusal(sqlstate: str, message: str) -> psycopg.Error:
    diag = SimpleNamespace(message_primary=message)
    return cast(psycopg.Error, SimpleNamespace(sqlstate=sqlstate, diag=diag))


def test_a_missing_generation_date_rate_has_its_own_stable_reason() -> None:
    """V1-060 B6 (DL-105): no Utility Rate in effect on the generation date has its own code."""
    error = PostgresFinalUtilityInvoiceService._error(
        _refusal("P0002", "Generation-date Utility Rate was not found")
    )
    assert type(error) is FinalUtilityInvoiceInvalidError
    assert error.reason == "UTILITY_RATE_NOT_IN_EFFECT"
    named = PostgresFinalUtilityInvoiceService._error(_refusal("P5N02", "UTILITY_NOTHING_TO_BILL"))
    assert type(named) is FinalUtilityInvoiceInvalidError
    assert named.reason == "UTILITY_NOTHING_TO_BILL"
    other = PostgresFinalUtilityInvoiceService._error(_refusal("P0002", "Another row is missing"))
    assert type(other) is FinalUtilityInvoiceInvalidError and other.reason is None
    busy = PostgresFinalUtilityInvoiceService._error(_refusal("P5N03", "Source is in use"))
    assert type(busy) is FinalUtilityInvoiceConflictError and busy.reason is None
