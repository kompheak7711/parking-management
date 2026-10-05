"""V1-056 sub-slice 8e-1: a closed Final Settlement's refusal reaches each service as a conflict."""

from datetime import UTC, date, datetime
from uuid import uuid4

import psycopg
import pytest

from property_rental.billing import (
    BILLING_GENERATE_CAPABILITY,
    BillingConflictError,
    GenerateRentInvoiceCommand,
    PostgresRentBillingService,
    RentBillingKind,
)
from property_rental.final_utility_invoice import (
    FinalUtilityInvoiceConflictError,
    PostgresFinalUtilityInvoiceService,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.invoice import InvoiceConflictError, PostgresInvoiceService
from property_rental.late_payment import LatePaymentConflictError, PostgresLatePaymentService
from property_rental.unpaid_initial_termination import (
    PostgresUnpaidInitialTerminationService,
    UnpaidInitialTerminationConflictError,
)

CLOSED = "P5S01"


def closed_failure() -> psycopg.Error:
    class Failure(psycopg.Error):
        pass

    failure = Failure("A closed Final Settlement changes only through a post-settlement correction")
    failure.sqlstate = CLOSED
    return failure


def test_invoice_late_payment_and_final_utility_services_report_a_conflict() -> None:
    """Business state reaches the user as a conflict (owner answer, plan slice 11c)."""
    assert isinstance(PostgresInvoiceService._map_error(closed_failure()), InvoiceConflictError)
    assert isinstance(
        PostgresLatePaymentService._map_error(closed_failure()), LatePaymentConflictError
    )
    assert isinstance(
        PostgresFinalUtilityInvoiceService._error(closed_failure()),
        FinalUtilityInvoiceConflictError,
    )


def test_rent_billing_and_unpaid_initial_resolutions_report_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = closed_failure()

    def connect(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(psycopg, "connect", connect)
    property_id, actor_id = uuid4(), uuid4()
    command = GenerateRentInvoiceCommand(
        idempotency_key=uuid4(),
        invoice_id=uuid4(),
        invoice_number="INV-2027-0001",
        lease_id=uuid4(),
        billing_kind=RentBillingKind.INITIAL,
        period_start=date(2027, 7, 27),
        issued_at=datetime(2027, 7, 27, 1, tzinfo=UTC),
        source_occupancy_id=None,
    )
    actor = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(BILLING_GENERATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(BillingConflictError) as billing:
        PostgresRentBillingService("postgresql://unused", property_id, actor_id).generate(
            command, actor=actor
        )
    assert billing.value.__cause__ is failure
    with pytest.raises(UnpaidInitialTerminationConflictError) as resolution:
        PostgresUnpaidInitialTerminationService("postgresql://unused", property_id)._execute(
            "SELECT 1", ()
        )
    assert resolution.value.__cause__ is failure
