"""Domain tests for the bounded V1-035 move-in contract."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest

from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    AddLeaseOccupantCommand,
    CompleteMoveInCommand,
    MoveInAuthorizationError,
    MoveInOccupant,
    PostgresMoveInService,
    move_in_request_digest,
)


def command() -> CompleteMoveInCommand:
    return CompleteMoveInCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        reservation_id=uuid4(),
        lease_id=uuid4(),
        expected_reservation_version=1,
        expected_lease_version=2,
        expected_unit_version=2,
        actual_move_in_date=date(2026, 8, 26),
        occupants=(MoveInOccupant(uuid4(), uuid4()),),
        reason="Verified move-in prerequisites",
        authorization_reference=MOVE_IN_CAPABILITY,
    )


def test_move_in_command_is_bounded_unique_and_digest_stable() -> None:
    value = command()
    assert move_in_request_digest(value) == move_in_request_digest(value)
    assert move_in_request_digest(value) != move_in_request_digest(
        replace(value, actual_move_in_date=date(2026, 8, 25))
    )
    with pytest.raises(ValueError, match="at least one"):
        replace(value, occupants=())
    with pytest.raises(ValueError, match="only once"):
        replace(
            value,
            occupants=(
                MoveInOccupant(uuid4(), value.occupants[0].customer_id),
                MoveInOccupant(uuid4(), value.occupants[0].customer_id),
            ),
        )


def test_service_rejects_actor_scope_and_untrusted_authorization_before_database() -> None:
    property_id = uuid4()
    actor_id = uuid4()
    value = command()
    service = PostgresMoveInService(
        "postgresql://must-not-be-used", property_id=property_id, actor_id=actor_id
    )
    with pytest.raises(MoveInAuthorizationError, match="does not match"):
        service.complete(value, actor=AuthenticatedActor(actor_id=str(uuid4())))
    with pytest.raises(MoveInAuthorizationError, match="not authorized"):
        service.complete(value, actor=AuthenticatedActor(actor_id=str(actor_id)))
    authorized = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(MOVE_IN_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(MoveInAuthorizationError, match="not authoritative"):
        service.complete(replace(value, authorization_reference="leases.sign"), actor=authorized)


def test_add_occupant_command_pairs_the_occupancy_with_its_date_and_checks_authority_first() -> (
    None
):
    """V1-060 B6 (DL-102): a planned person has no Occupancy and no date; a person added after
    the move-in has both. Authority is checked before the database is reached."""
    planned = AddLeaseOccupantCommand(
        idempotency_key=uuid4(),
        event_id=uuid4(),
        lease_id=uuid4(),
        expected_lease_version=3,
        customer_id=uuid4(),
        occupancy_id=None,
        move_in_date=None,
        reason="A friend moves in with the Lease",
        authorization_reference=MOVE_IN_CAPABILITY,
    )
    dated = replace(planned, occupancy_id=uuid4(), move_in_date=date(2026, 10, 28))
    assert move_in_request_digest(dated) == move_in_request_digest(dated)
    assert move_in_request_digest(dated) != move_in_request_digest(planned)
    for wrong in (
        {"occupancy_id": uuid4()},
        {"move_in_date": date(2026, 10, 28)},
    ):
        with pytest.raises(ValueError, match="come together"):
            replace(planned, **wrong)
    with pytest.raises(ValueError, match="positive"):
        replace(planned, expected_lease_version=0)
    with pytest.raises(ValueError):
        replace(planned, reason=" ")

    property_id = uuid4()
    actor_id = uuid4()
    service = PostgresMoveInService(
        "postgresql://must-not-be-used", property_id=property_id, actor_id=actor_id
    )
    with pytest.raises(MoveInAuthorizationError, match="does not match"):
        service.add_lease_occupant(dated, actor=AuthenticatedActor(actor_id=str(uuid4())))
    with pytest.raises(MoveInAuthorizationError, match="not authorized"):
        service.add_lease_occupant(dated, actor=AuthenticatedActor(actor_id=str(actor_id)))
    authorized = AuthenticatedActor(
        actor_id=str(actor_id),
        capability_grants=frozenset(
            {CapabilityGrant(MOVE_IN_CAPABILITY, frozenset({str(property_id)}))}
        ),
    )
    with pytest.raises(MoveInAuthorizationError, match="not authorized"):
        service.add_lease_occupant(
            replace(dated, authorization_reference="leases.sign"), actor=authorized
        )
