"""Deterministic unit coverage for the V1-037 Deposit domain boundary."""

from datetime import date, datetime
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.deposit import (
    DEPOSIT_MANAGE_CAPABILITY,
    PAYMENT_ALLOCATE_CAPABILITY,
    AdjustDepositRequiredAmountCommand,
    CreateLeaseSecurityDepositCommand,
    CreatePetDepositCommand,
    DepositAdjustmentType,
    DepositAuthorizationError,
    DepositServiceUnavailableError,
    PetDepositAssessment,
    PostgresDepositService,
    RecordDepositDispositionCommand,
    RecordDepositReceiptCommand,
    deposit_request_digest,
)
from property_rental.identity import AuthenticatedActor, CapabilityGrant


def test_pet_deposit_assessment_requires_both_approved_conditions() -> None:
    matrix = {
        (False, False): False,
        (False, True): False,
        (True, False): False,
        (True, True): True,
    }
    for (approved, required_by_terms), expected in matrix.items():
        assessment = PetDepositAssessment(approved, required_by_terms)
        assert assessment.deposit_required is expected
        assert assessment.violation_requires_warning_only is (not approved)
    assert not PetDepositAssessment(True, True, pet_permanently_departed=True).deposit_required


def test_deposit_commands_validate_money_time_and_identity() -> None:
    with pytest.raises(ValueError, match="positive"):
        CreatePetDepositCommand(uuid4(), uuid4(), uuid4(), uuid4(), 0, date.today(), "reason")
    with pytest.raises(ValueError, match="positive"):
        RecordDepositDispositionCommand(
            uuid4(), uuid4(), uuid4(), uuid4(), 0, date.today(), "disposition"
        )
    with pytest.raises(ValueError, match="nil UUID"):
        AdjustDepositRequiredAmountCommand(
            uuid4(),
            UUID(int=0),
            uuid4(),
            DepositAdjustmentType.INCREASE,
            100,
            date.today(),
            "adjustment",
        )


def test_deposit_digest_binds_every_normalized_command_field() -> None:
    command = CreatePetDepositCommand(
        uuid4(), uuid4(), uuid4(), uuid4(), 20_000, date(2027, 1, 1), "approved terms"
    )
    assert deposit_request_digest("deposit.pet.create", command) == deposit_request_digest(
        "deposit.pet.create", command
    )
    changed = CreatePetDepositCommand(
        command.idempotency_key,
        command.deposit_id,
        command.lease_id,
        command.pet_approval_id,
        20_001,
        command.required_effective_date,
        command.reason,
    )
    assert deposit_request_digest("deposit.pet.create", command) != deposit_request_digest(
        "deposit.pet.create", changed
    )


def test_service_rejects_actor_or_property_capability_mismatch_before_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresDepositService("postgresql://unused", property_id, actor_id)
    command = CreatePetDepositCommand(
        uuid4(), uuid4(), uuid4(), uuid4(), 20_000, date(2027, 1, 1), "approved terms"
    )
    wrong_actor = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            {CapabilityGrant(DEPOSIT_MANAGE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(DepositAuthorizationError):
        service.create_pet_deposit(command, actor=wrong_actor)


@pytest.mark.parametrize("amount", [True, False, 1.0, 1.25, "100", None, 2**63])
def test_lease_disposition_rejects_non_integer_or_out_of_range_cents(amount: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        RecordDepositDispositionCommand(
            uuid4(), uuid4(), uuid4(), uuid4(), cast(int, amount), date(2027, 1, 1), "Approved"
        )


@pytest.mark.parametrize("effective", [None, "2027-01-01", 1, datetime(2027, 1, 1)])
def test_lease_disposition_rejects_non_date_effective_values(effective: object) -> None:
    with pytest.raises(ValueError, match="date"):
        RecordDepositDispositionCommand(
            uuid4(), uuid4(), uuid4(), uuid4(), 100, cast(date, effective), "Approved"
        )


@pytest.mark.parametrize("amount", [0, -1, True, 1.0, "100", None, 2**63])
def test_deposit_receipt_command_takes_only_positive_integer_cents(amount: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        RecordDepositReceiptCommand(
            uuid4(), uuid4(), uuid4(), uuid4(), cast(int, amount), "Pet Deposit paid"
        )


def test_deposit_receipt_command_validates_identity_and_reason() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), UUID(int=0), 100, "Paid")
    for reason in ("", " Paid", "x" * 1_001):
        with pytest.raises(ValueError, match="reason"):
            RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), uuid4(), 100, reason)
    command = RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), uuid4(), 100, "x" * 1_000)
    assert command.authorization_reference == PAYMENT_ALLOCATE_CAPABILITY
    changed = RecordDepositReceiptCommand(
        command.idempotency_key,
        command.receipt_id,
        command.deposit_id,
        command.payment_id,
        101,
        command.reason,
    )
    assert deposit_request_digest("deposit.receipt.record", command) != deposit_request_digest(
        "deposit.receipt.record", changed
    )


def test_deposit_receipt_needs_payments_allocate_before_the_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresDepositService("postgresql://unused", property_id, actor_id)
    command = RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), uuid4(), 100, "Paid")
    for capability in (DEPOSIT_MANAGE_CAPABILITY, "payments.allocations.reverse"):
        manager = AuthenticatedActor(
            actor_id=str(actor_id),
            capability_grants=frozenset(
                {CapabilityGrant(capability, frozenset({str(property_id)}))}
            ),
        )
        with pytest.raises(DepositAuthorizationError):
            service.record_receipt(command, actor=manager)
    allocator = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(PAYMENT_ALLOCATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    elsewhere = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(PAYMENT_ALLOCATE_CAPABILITY, frozenset({str(uuid4())}))}
        ),
    )
    with pytest.raises(DepositAuthorizationError):
        service.record_receipt(command, actor=elsewhere)
    with pytest.raises(DepositAuthorizationError):
        service.record_receipt(
            RecordDepositReceiptCommand(
                uuid4(), uuid4(), uuid4(), uuid4(), 100, "Paid", DEPOSIT_MANAGE_CAPABILITY
            ),
            actor=allocator,
        )


@pytest.mark.parametrize("required", [0, -1, True, 1.0, "100", None, 2**63])
def test_lease_security_deposit_command_takes_only_positive_integer_cents(
    required: object,
) -> None:
    with pytest.raises(ValueError, match="integer"):
        CreateLeaseSecurityDepositCommand(
            uuid4(), uuid4(), uuid4(), cast(int, required), "Lease terms"
        )


def test_lease_security_deposit_command_validates_identity_and_reason() -> None:
    with pytest.raises(ValueError, match="nil UUID"):
        CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), UUID(int=0), 100, "Lease terms")
    for reason in ("", " Lease terms", "x" * 1_001):
        with pytest.raises(ValueError, match="reason"):
            CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), uuid4(), 100, reason)
    command = CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), uuid4(), 100, "x" * 1_000)
    assert command.authorization_reference == DEPOSIT_MANAGE_CAPABILITY
    changed = CreateLeaseSecurityDepositCommand(
        command.idempotency_key, command.deposit_id, command.lease_id, 101, command.reason
    )
    assert deposit_request_digest("deposit.security.create", command) != (
        deposit_request_digest("deposit.security.create", changed)
    )


def test_lease_security_deposit_needs_deposits_manage_before_the_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresDepositService("postgresql://unused", property_id, actor_id)
    command = CreateLeaseSecurityDepositCommand(uuid4(), uuid4(), uuid4(), 100, "Lease terms")
    for capability, scope in (
        (PAYMENT_ALLOCATE_CAPABILITY, str(property_id)),
        (DEPOSIT_MANAGE_CAPABILITY, str(uuid4())),
    ):
        refused = AuthenticatedActor(
            actor_id=str(actor_id),
            capability_grants=frozenset({CapabilityGrant(capability, frozenset({scope}))}),
        )
        with pytest.raises(DepositAuthorizationError):
            service.create_lease_security_deposit(command, actor=refused)
    manager = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(DEPOSIT_MANAGE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(DepositAuthorizationError):
        service.create_lease_security_deposit(
            CreateLeaseSecurityDepositCommand(
                uuid4(), uuid4(), uuid4(), 100, "Lease terms", PAYMENT_ALLOCATE_CAPABILITY
            ),
            actor=manager,
        )


def test_a_receipt_is_replayed_after_a_nowait_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-slice 10e-2b-4d (review round 1; DL-067, owner decision 2026-10-03): the receipt
    writer's excess check takes its locks NOWAIT, so the service replays the same receipt command
    after 55P03, at most three times (four attempts in all, each on its own connection), and
    answers unavailable after the last attempt."""
    property_id = uuid4()
    actor_id = uuid4()
    attempts: list[None] = []

    def refuse(*_arguments: object, **_options: object) -> None:
        attempts.append(None)
        raise psycopg.errors.LockNotAvailable("could not obtain lock")

    monkeypatch.setattr("property_rental.deposit.psycopg.connect", refuse)
    monkeypatch.setattr("property_rental.lock_retry._pause", lambda _seconds: None)
    service = PostgresDepositService("postgresql://unused", property_id, actor_id)
    allocator = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(PAYMENT_ALLOCATE_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(DepositServiceUnavailableError):
        service.record_receipt(
            RecordDepositReceiptCommand(uuid4(), uuid4(), uuid4(), uuid4(), 100, "Paid"),
            actor=allocator,
        )
    assert len(attempts) == 4
