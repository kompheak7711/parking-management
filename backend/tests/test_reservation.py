"""Domain tests for the bounded Reservation lifecycle service contract."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from property_rental.reservation import (
    CancellationResponsibility,
    PostgresReservationService,
    ReservationCancelCommand,
    ReservationCreateCommand,
    ReservationExpireCommand,
    ReservationStatus,
    reservation_request_digest,
)


def create_command() -> ReservationCreateCommand:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    return ReservationCreateCommand(
        idempotency_key=uuid4(),
        reservation_id=uuid4(),
        unit_id=uuid4(),
        customer_id=uuid4(),
        reservation_date=date(2026, 8, 25),
        agreed_monthly_rent_usd_cents=50_000,
        original_expiration_date=date(2026, 9, 4),
        acceptance_id=uuid4(),
        accepted_required_amount_usd_cents=10_000,
        acceptance_kind="NORMAL_SUGGESTION",
        accepted_at=now,
        acceptance_reason="Explicitly accepted initial Security Deposit",
        authorization_reference="reservations.manage",
        calculation_trace={
            "agreed_monthly_rent_usd_cents": 50_000,
            "suggested_rate_basis_points": 2000,
            "suggested_amount_usd_cents": 10_000,
        },
        deposit_id=uuid4(),
        required_deposit_usd_cents=50_000,
        receipt_id=uuid4(),
        payment_id=uuid4(),
        received_at=now,
    )


def test_reservation_status_vocabulary_has_no_expired_or_moved_in_state() -> None:
    assert {status.value for status in ReservationStatus} == {
        "ACTIVE",
        "CANCELLED",
        "COMPLETED",
    }


def test_request_digest_is_stable_and_binds_every_command_input() -> None:
    command = create_command()

    first = reservation_request_digest("reservation.create", command)
    second = reservation_request_digest("reservation.create", command)
    changed = reservation_request_digest(
        "reservation.create",
        replace(command, required_deposit_usd_cents=60_000),
    )

    assert first == second
    assert len(first) == 64
    assert changed != first


def test_customer_cancellation_requires_property_availability_and_no_coordination() -> None:
    def command(
        *,
        property_could_provide_unit: bool = True,
        coordination_reference: str | None = None,
    ) -> ReservationCancelCommand:
        return ReservationCancelCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=uuid4(),
            expected_version=1,
            reason_code="CUSTOMER_WITHDREW",
            responsibility=CancellationResponsibility.CUSTOMER,
            property_could_provide_unit=property_could_provide_unit,
            reason_memo="Customer requested cancellation",
            coordination_reference=coordination_reference,
            authorization_reference="reservations.cancel",
        )

    valid = command()

    assert valid.responsibility is CancellationResponsibility.CUSTOMER
    with pytest.raises(ValueError, match="classification"):
        command(property_could_provide_unit=False)
    with pytest.raises(ValueError, match="classification"):
        command(coordination_reference="CASE-1")


def test_property_cancellation_requires_coordination_and_preserves_v1_031_boundary() -> None:
    command = ReservationCancelCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        reservation_id=uuid4(),
        expected_version=2,
        reason_code="PROPERTY_UNABLE_TO_PROVIDE_UNIT",
        responsibility=CancellationResponsibility.PROPERTY,
        property_could_provide_unit=False,
        reason_memo="Customer rejected the coordinated alternative",
        coordination_reference="CASE-2026-001",
        authorization_reference="reservations.cancel",
    )

    assert command.coordination_reference == "CASE-2026-001"
    assert not hasattr(command, "refund_id")
    assert not hasattr(command, "disposition_id")


def test_expiration_refuses_property_inability_instead_of_misclassification() -> None:
    with pytest.raises(ValueError, match="coordinated cancellation"):
        ReservationExpireCommand(
            idempotency_key=uuid4(),
            event_id=uuid4(),
            reservation_id=uuid4(),
            expected_version=1,
            property_could_provide_unit=False,
            authorization_reference="reservation-expiry-job",
        )


def test_due_query_is_strictly_bounded_before_database_access() -> None:
    service = PostgresReservationService(
        "postgresql://unused",
        property_id=uuid4(),
        actor_id=uuid4(),
    )

    with pytest.raises(ValueError, match="between 1 and 100"):
        service.list_due(limit=0)
    with pytest.raises(ValueError, match="between 1 and 100"):
        service.list_due(limit=101)
