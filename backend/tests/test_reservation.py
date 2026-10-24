"""Domain tests for the bounded Reservation lifecycle service contract."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.reservation import (
    CancellationResponsibility,
    PostgresReservationService,
    ReservationAuthorizationError,
    ReservationCancelCommand,
    ReservationCreateCommand,
    ReservationExpireCommand,
    ReservationStatus,
    reservation_request_digest,
)
from property_rental.reservation_deposit_draft import (
    RecordReservationDepositCorrectionDraftCommand,
    ReservationDepositDraftInvalidError,
    reservation_deposit_draft_id,
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

    # V1-056 slice 3b: the Refund number belongs to the Refund draft, not the cancellation.
    assert command.coordination_reference == "CASE-2026-001"


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


def test_outcome_correction_digest_binds_replacement_and_evidence() -> None:
    # V1-056 slice 3b: an outcome correction is a draft; the database binds every input of the
    # draft to its id, which is derived from the Property, the preparer and the command key.
    command = RecordReservationDepositCorrectionDraftCommand(
        idempotency_key=uuid4(),
        reservation_id=uuid4(),
        expected_outcome_id=uuid4(),
        correction_id=uuid4(),
        replacement_outcome_id=uuid4(),
        reason="Correct external Refund reference",
        evidence_reference="CASE-2026-004",
    )
    property_id, actor_id = uuid4(), uuid4()

    draft_id = reservation_deposit_draft_id(property_id, actor_id, command.idempotency_key)

    assert draft_id == reservation_deposit_draft_id(property_id, actor_id, command.idempotency_key)
    assert draft_id != reservation_deposit_draft_id(uuid4(), actor_id, command.idempotency_key)
    assert draft_id != reservation_deposit_draft_id(property_id, uuid4(), command.idempotency_key)
    with pytest.raises(ReservationDepositDraftInvalidError):
        replace(command, replacement_outcome_id=command.correction_id)
    with pytest.raises(ReservationDepositDraftInvalidError):
        replace(command, evidence_reference=" padded ")


def test_financial_commands_require_trusted_separate_capabilities() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresReservationService(
        "postgresql://ordinary-connection-must-not-be-used",
        property_id=property_id,
        actor_id=actor_id,
        financial_database_url="postgresql://financial-connection-must-not-be-used",
    )
    command = ReservationCancelCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        reservation_id=uuid4(),
        expected_version=1,
        reason_code="CUSTOMER_WITHDREW",
        responsibility=CancellationResponsibility.CUSTOMER,
        property_could_provide_unit=True,
        reason_memo="Customer requested cancellation",
        coordination_reference=None,
        authorization_reference="reservations.cancel",
    )
    property_scope = frozenset({str(property_id)})
    # V1-056 slice 3b: cancellation needs only reservations.cancel; the Deposit decision is a
    # separate draft, so a Deposit capability alone does not allow cancellation.
    cancel_only = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant("reservation_deposits.dispose", property_scope)}
        ),
    )
    wrong_actor = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {
                CapabilityGrant("reservations.cancel", property_scope),
                CapabilityGrant("reservation_deposits.dispose", property_scope),
            }
        ),
    )

    with pytest.raises(ReservationAuthorizationError, match="not authorized"):
        service.cancel(command, actor=cancel_only)
    with pytest.raises(ReservationAuthorizationError, match="does not match"):
        service.cancel(command, actor=wrong_actor)
    with pytest.raises(ReservationAuthorizationError, match="not authoritative"):
        service.cancel(
            replace(command, authorization_reference="untrusted.claim"),
            actor=AuthenticatedActor(
                actor_id=str(actor_id),
                capability_grants=frozenset(
                    {
                        CapabilityGrant("reservations.cancel", property_scope),
                        CapabilityGrant("reservation_deposits.dispose", property_scope),
                    }
                ),
            ),
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
