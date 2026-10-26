"""Domain and service tests for Property-scoped Units."""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4

import pytest

from property_rental.unit import (
    SignedLeasePeriod,
    Unit,
    UnitAvailabilityFacts,
    UnitNumberAlreadyExistsError,
    UnitOutsidePropertyScopeError,
    UnitService,
    UnitStatus,
    UnitType,
    evaluate_unit_availability,
    restored_unit_status,
)


@dataclass
class InMemoryUnitRepository:
    """Minimal identity-preserving Unit repository for service tests."""

    units: dict[tuple[UUID, str], Unit] = field(default_factory=dict)

    def get_by_unit_number(self, property_id: UUID, unit_number: str) -> Unit | None:
        return self.units.get((property_id, unit_number))

    def add(self, unit: Unit) -> None:
        key = (unit.property_id, unit.unit_number)
        if key in self.units:
            raise UnitNumberAlreadyExistsError(unit.unit_number)
        self.units[key] = unit


@pytest.mark.parametrize(
    "unit_type",
    [
        UnitType.STUDIO,
        UnitType.ONE_BEDROOM,
        UnitType.TWO_BEDROOM,
        UnitType.THREE_BEDROOM,
    ],
)
def test_unit_accepts_each_supported_type(unit_type: UnitType) -> None:
    unit = Unit(
        unit_id=uuid4(),
        property_id=uuid4(),
        unit_number="101",
        floor="1",
        unit_type=unit_type,
        status=UnitStatus.VACANT,
    )

    assert unit.unit_type is unit_type


@pytest.mark.parametrize("status", list(UnitStatus))
def test_unit_accepts_each_supported_status(status: UnitStatus) -> None:
    unit = Unit(
        unit_id=uuid4(),
        property_id=uuid4(),
        unit_number="101",
        floor="1",
        unit_type=UnitType.STUDIO,
        status=status,
    )

    assert unit.status is status


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("unit_id", UUID(int=0), "unit_id must not be the nil UUID"),
        ("property_id", UUID(int=0), "property_id must not be the nil UUID"),
        ("unit_number", "  ", "unit_number must not be blank"),
        ("unit_number", " 101 ", "unit_number must not have surrounding whitespace"),
        ("floor", "  ", "floor must not be blank"),
        ("floor", " 1 ", "floor must not have surrounding whitespace"),
        # A Unit Type is a list code (V1-058 R2a); the database checks the list itself.
        ("unit_type", "commercial", "unit_type is not supported"),
        ("status", "AVAILABLE", "status is not supported"),
    ],
)
def test_unit_rejects_invalid_identity_or_attributes(
    field_name: str, value: object, message: str
) -> None:
    values: dict[str, object] = {
        "unit_id": uuid4(),
        "property_id": uuid4(),
        "unit_number": "101",
        "floor": "1",
        "unit_type": UnitType.STUDIO,
        "status": UnitStatus.VACANT,
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        Unit(**values)  # type: ignore[arg-type]


def test_service_normalizes_and_persists_unit_with_stable_identity() -> None:
    property_id = uuid4()
    unit_id = uuid4()
    repository = InMemoryUnitRepository()
    service = UnitService(property_id, repository)

    created = service.create(
        unit_id,
        property_id=property_id,
        unit_number=" 101 ",
        floor=" 1 ",
        unit_type=UnitType.ONE_BEDROOM,
        status=UnitStatus.CLEANING,
    )

    assert created == Unit(
        unit_id=unit_id,
        property_id=property_id,
        unit_number="101",
        floor="1",
        unit_type=UnitType.ONE_BEDROOM,
        status=UnitStatus.CLEANING,
    )
    assert repository.units[(property_id, "101")] is created


def test_service_rejects_unit_outside_authoritative_property_scope() -> None:
    service = UnitService(uuid4(), InMemoryUnitRepository())

    with pytest.raises(UnitOutsidePropertyScopeError):
        service.create(
            uuid4(),
            property_id=uuid4(),
            unit_number="101",
            floor="1",
            unit_type=UnitType.STUDIO,
            status=UnitStatus.VACANT,
        )


def test_service_rejects_duplicate_unit_number_within_property() -> None:
    property_id = uuid4()
    repository = InMemoryUnitRepository()
    service = UnitService(property_id, repository)
    service.create(
        uuid4(),
        property_id=property_id,
        unit_number="101",
        floor="1",
        unit_type=UnitType.STUDIO,
        status=UnitStatus.VACANT,
    )

    with pytest.raises(UnitNumberAlreadyExistsError):
        service.create(
            uuid4(),
            property_id=property_id,
            unit_number=" 101 ",
            floor="2",
            unit_type=UnitType.TWO_BEDROOM,
            status=UnitStatus.UNDER_MAINTENANCE,
        )


def availability_unit(status: UnitStatus = UnitStatus.VACANT) -> Unit:
    """Build a Unit whose stored status may differ from authoritative facts."""
    return Unit(
        unit_id=uuid4(),
        property_id=uuid4(),
        unit_number="101",
        floor="1",
        unit_type=UnitType.STUDIO,
        status=status,
    )


def availability_facts(**overrides: object) -> UnitAvailabilityFacts:
    """Build an explicit, ready requested period with selected authoritative facts."""
    values: dict[str, object] = {
        "requested_starts_on": date(2026, 9, 1),
        "requested_ends_on": date(2026, 9, 30),
        "is_ready_for_rental": True,
    }
    values.update(overrides)
    return UnitAvailabilityFacts(**values)  # type: ignore[arg-type]


def test_availability_rejects_active_reservation() -> None:
    decision = evaluate_unit_availability(
        availability_unit(), availability_facts(has_active_reservation=True)
    )

    assert decision.is_available is False
    assert decision.status is UnitStatus.RESERVED
    assert decision.blockers == ("ACTIVE_RESERVATION",)


def test_availability_rejects_overlapping_signed_lease() -> None:
    decision = evaluate_unit_availability(
        availability_unit(UnitStatus.RESERVED),
        availability_facts(
            signed_lease_periods=(SignedLeasePeriod(date(2026, 9, 15), date(2026, 10, 15)),)
        ),
    )

    assert decision.is_available is False
    assert decision.status is UnitStatus.RESERVED
    assert decision.blockers == ("SIGNED_LEASE_OVERLAP",)


def test_availability_allows_non_overlapping_signed_lease() -> None:
    decision = evaluate_unit_availability(
        availability_unit(),
        availability_facts(
            signed_lease_periods=(SignedLeasePeriod(date(2026, 8, 1), date(2026, 8, 31)),)
        ),
    )

    assert decision.is_available is True
    assert decision.status is UnitStatus.VACANT
    assert decision.blockers == ()


def test_availability_rejects_invalid_requested_or_lease_period() -> None:
    with pytest.raises(ValueError, match="requested period"):
        UnitAvailabilityFacts(date(2026, 9, 2), date(2026, 9, 1), True)
    with pytest.raises(ValueError, match="signed Lease period"):
        SignedLeasePeriod(date(2026, 9, 2), date(2026, 9, 1))


def test_availability_rejects_actual_occupancy() -> None:
    decision = evaluate_unit_availability(
        availability_unit(), availability_facts(is_actually_occupied=True)
    )

    assert decision.is_available is False
    assert decision.status is UnitStatus.OCCUPIED
    assert decision.blockers == ("ACTUAL_OCCUPANCY",)


@pytest.mark.parametrize(
    ("facts", "expected_status", "expected_blocker"),
    [
        (
            availability_facts(is_under_maintenance=True),
            UnitStatus.UNDER_MAINTENANCE,
            "UNDER_MAINTENANCE",
        ),
        (
            availability_facts(requires_cleaning=True),
            UnitStatus.CLEANING,
            "CLEANING",
        ),
        (
            availability_facts(is_out_of_service=True),
            UnitStatus.OUT_OF_SERVICE,
            "OUT_OF_SERVICE",
        ),
    ],
)
def test_availability_rejects_operational_blockers(
    facts: UnitAvailabilityFacts,
    expected_status: UnitStatus,
    expected_blocker: str,
) -> None:
    decision = evaluate_unit_availability(availability_unit(), facts)

    assert decision.is_available is False
    assert decision.status is expected_status
    assert decision.blockers == (expected_blocker,)


@pytest.mark.parametrize("stored_status", list(UnitStatus))
def test_status_alone_never_authorizes_conflict(stored_status: UnitStatus) -> None:
    decision = evaluate_unit_availability(
        availability_unit(stored_status),
        availability_facts(has_active_reservation=True),
    )

    assert decision.is_available is False
    expected_status = (
        stored_status
        if stored_status in {UnitStatus.UNDER_MAINTENANCE, UnitStatus.OUT_OF_SERVICE}
        else UnitStatus.RESERVED
    )
    assert decision.status is expected_status


@pytest.mark.parametrize(
    ("facts", "expected_status"),
    [
        (availability_facts(), UnitStatus.VACANT),
        (
            availability_facts(has_active_reservation=True),
            UnitStatus.RESERVED,
        ),
        (availability_facts(is_actually_occupied=True), UnitStatus.OCCUPIED),
        (availability_facts(requires_cleaning=True), UnitStatus.CLEANING),
    ],
)
def test_restoration_derives_status_from_authoritative_facts(
    facts: UnitAvailabilityFacts, expected_status: UnitStatus
) -> None:
    assert restored_unit_status(availability_unit(), facts) is expected_status


@pytest.mark.parametrize(
    "stored_status",
    [UnitStatus.UNDER_MAINTENANCE, UnitStatus.OUT_OF_SERVICE],
)
def test_protected_status_requires_authorized_restoration(
    stored_status: UnitStatus,
) -> None:
    decision = evaluate_unit_availability(availability_unit(stored_status), availability_facts())

    assert decision.is_available is False
    assert decision.status is stored_status
    assert decision.blockers == ("AUTHORIZED_RESTORATION_REQUIRED",)

    conflicting_facts = (
        availability_facts(has_active_reservation=True),
        availability_facts(
            signed_lease_periods=(SignedLeasePeriod(date(2026, 9, 15), date(2026, 10, 15)),)
        ),
        availability_facts(is_actually_occupied=True),
        availability_facts(requires_cleaning=True),
        availability_facts(is_under_maintenance=True),
        availability_facts(is_out_of_service=True),
    )
    for facts in conflicting_facts:
        protected_decision = evaluate_unit_availability(availability_unit(stored_status), facts)

        assert protected_decision.is_available is False
        assert protected_decision.status is stored_status


@pytest.mark.parametrize(
    "stored_status",
    [UnitStatus.UNDER_MAINTENANCE, UnitStatus.OUT_OF_SERVICE],
)
def test_authorized_restoration_uses_current_facts(
    stored_status: UnitStatus,
) -> None:
    decision = evaluate_unit_availability(
        availability_unit(stored_status),
        availability_facts(restoration_authorized=True),
    )

    assert decision.is_available is True
    assert decision.status is UnitStatus.VACANT
    assert decision.blockers == ()

    leased_decision = evaluate_unit_availability(
        availability_unit(stored_status),
        availability_facts(
            restoration_authorized=True,
            signed_lease_periods=(SignedLeasePeriod(date(2026, 9, 15), date(2026, 10, 15)),),
        ),
    )

    assert leased_decision.is_available is False
    assert leased_decision.status is UnitStatus.RESERVED
    assert leased_decision.blockers == ("SIGNED_LEASE_OVERLAP",)


def test_missing_readiness_is_not_available() -> None:
    decision = evaluate_unit_availability(
        availability_unit(), availability_facts(is_ready_for_rental=False)
    )

    assert decision.is_available is False
    assert decision.status is UnitStatus.VACANT
    assert decision.blockers == ("NOT_READY_FOR_RENTAL",)


def test_state_decisions_preserve_unit_identity() -> None:
    unit = availability_unit(UnitStatus.OUT_OF_SERVICE)

    decision = evaluate_unit_availability(unit, availability_facts(restoration_authorized=True))

    assert decision.unit_id == unit.unit_id
    assert decision.property_id == unit.property_id
    assert decision.status is UnitStatus.VACANT
    assert unit.status is UnitStatus.OUT_OF_SERVICE
