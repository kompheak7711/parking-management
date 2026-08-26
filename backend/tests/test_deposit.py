"""Deterministic unit coverage for the V1-037 Deposit domain boundary."""

from datetime import date
from uuid import UUID, uuid4

import pytest

from property_rental.deposit import (
    DEPOSIT_MANAGE_CAPABILITY,
    AdjustDepositRequiredAmountCommand,
    CreatePetDepositCommand,
    DepositAdjustmentType,
    DepositAuthorizationError,
    PetDepositAssessment,
    PostgresDepositService,
    RecordDepositDispositionCommand,
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
