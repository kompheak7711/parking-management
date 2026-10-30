"""Migration 20270406_256 (Parking Step 4, owner 2026-10-30): Vehicles.

A vehicle is a record under a Customer (type, plate as typed). A Lease of a Parking holds one
vehicle at a time: the vehicle, not a person, moves in; Change vehicle ends the old vehicle's
row and starts the new one the same day; the only vehicle never moves out alone (Termination
and the Move-out page end it). Each vehicle type parks only in its own kind of place.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from property_rental.billing import month_end
from property_rental.lease import LEASE_SIGN_CAPABILITY, LeaseDraftSigner, LeaseSignCommand
from property_rental.lease_api import PostgresLeaseResourceFlow
from property_rental.lease_vehicle import (
    ChangeLeaseVehicleCommand,
    PostgresLeaseVehicleService,
    RecordLeaseVehicleMoveInCommand,
    VehicleRefusedError,
)
from property_rental.move_in import (
    MOVE_IN_CAPABILITY,
    MoveInConflictError,
    MoveInVersionConflictError,
    OccupantMoveOutCommand,
    OccupantMoveOutRefusedError,
    PostgresMoveInService,
)
from property_rental.physical_move_out import EndedOccupancy, RecordPhysicalMoveOut
from property_rental.vehicle import (
    PostgresVehicleService,
    VehicleCreateCommand,
    VehicleInvalidError,
    VehicleUpdateCommand,
    VehicleVersionConflictError,
)
from test_lease_lifecycle_migration import actor, database_now, draft_command, signature_command
from test_lease_occupant_addition_migration import _customer, _walk_in
from test_lease_signing_reservation_migration import business_date, leases
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_physical_move_out_migration import record as hand_back
from test_termination_deposit_migration import terminate

MOVE_IN = (
    "app.record_lease_vehicle_move_in("
    "uuid,uuid,text,uuid,uuid,integer,date,uuid,uuid,text,text,uuid)"
)
CHANGE = "app.change_lease_vehicle(uuid,uuid,text,uuid,uuid,integer,uuid,uuid,date,text,text,uuid)"
CREATE = "app.create_vehicle(uuid,uuid,text,text,uuid)"
UPDATE = "app.update_vehicle(uuid,integer,text,text,uuid)"


def vehicles() -> PostgresVehicleService:
    return PostgresVehicleService(runtime_database_url())


def make(customer: UUID, actor_id: UUID, vehicle_type: str, plate: str) -> UUID:
    vehicle_id = uuid4()
    vehicles().create(
        VehicleCreateCommand(vehicle_id, customer, vehicle_type, plate), actor_id=actor_id
    )
    return vehicle_id


class Garage:
    """A signed Lease of a Covered Parking (the first seeded Parking Type) with a Primary
    Tenant, a Joint Signer and a friend who signed nothing; nothing moved in yet."""

    def __init__(self, url: str, *, tenant: UUID | None = None) -> None:
        self.url = url
        self.actor, self.prop, self.unit, made = _walk_in(url)
        self.tenant = made if tenant is None else tenant
        self.joint = _customer(url, self.actor, "Joint Signer")
        self.friend = _customer(url, self.actor, "Friend")
        service, who = leases(self.actor, self.prop)
        self.today = business_date(url, self.prop)
        draft = replace(
            draft_command(
                self.unit,
                self.tenant,
                start_date=self.today - timedelta(days=10),
                end_date=month_end(self.today + timedelta(days=365)),
            ),
            additional_signers=(LeaseDraftSigner(uuid4(), self.joint),),
        )
        service.draft_with_terms(draft, actor=who)
        self.lease = draft.lease_id
        version = 1
        for signer in [draft.primary_signer_id, draft.additional_signers[0].signer_id]:
            service.record_signature(signature_command(draft.lease_id, signer, version), actor=who)
            version += 1
        service.sign(
            LeaseSignCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=draft.lease_id,
                expected_version=version,
                signed_at=database_now(),
                reason="Lease signed",
                authorization_reference=LEASE_SIGN_CAPABILITY,
                reservation_id=None,
            ),
            actor=who,
        )
        self.version = version + 1
        self.tenant_car = make(self.tenant, self.actor, "CAR", "1AB-1234")
        self.tenant_moto = make(self.tenant, self.actor, "MOTORBIKE", "1AB-5678")
        self.joint_car = make(self.joint, self.actor, "CAR", "2CD-5678")
        self.friend_car = make(self.friend, self.actor, "CAR", "3EF-9012")

    def service(self) -> PostgresLeaseVehicleService:
        return PostgresLeaseVehicleService(runtime_database_url(), self.prop, self.actor)

    def move_in_command(
        self, vehicle: UUID, day: date | None = None, *, key: UUID | None = None
    ) -> RecordLeaseVehicleMoveInCommand:
        return RecordLeaseVehicleMoveInCommand(
            idempotency_key=uuid4() if key is None else key,
            event_id=uuid4(),
            lease_id=self.lease,
            expected_lease_version=self.version,
            actual_move_in_date=self.today if day is None else day,
            occupancy_id=uuid4(),
            vehicle_id=vehicle,
            reason="Vehicle moved in",
            authorization_reference=MOVE_IN_CAPABILITY,
        )

    def change_command(
        self, vehicle: UUID, day: date | None = None, *, key: UUID | None = None
    ) -> ChangeLeaseVehicleCommand:
        return ChangeLeaseVehicleCommand(
            idempotency_key=uuid4() if key is None else key,
            event_id=uuid4(),
            lease_id=self.lease,
            expected_lease_version=self.version,
            change_date=self.today if day is None else day,
            occupancy_id=uuid4(),
            vehicle_id=vehicle,
            reason="Sold the old car",
            authorization_reference=MOVE_IN_CAPABILITY,
        )

    def move_in(self, command: RecordLeaseVehicleMoveInCommand) -> dict[str, object]:
        result = self.service().record_lease_vehicle_move_in(
            command, actor=actor(self.actor, self.prop, MOVE_IN_CAPABILITY)
        )
        self.version = int(str(result["lease_version"]))
        return result

    def change(self, command: ChangeLeaseVehicleCommand) -> dict[str, object]:
        result = self.service().change_lease_vehicle(
            command, actor=actor(self.actor, self.prop, MOVE_IN_CAPABILITY)
        )
        self.version = int(str(result["lease_version"]))
        return result

    def refused_move_in(self, command: RecordLeaseVehicleMoveInCommand) -> str:
        with pytest.raises(VehicleRefusedError) as refused:
            self.move_in(command)
        return refused.value.reason

    def refused_change(self, command: ChangeLeaseVehicleCommand) -> str:
        with pytest.raises(VehicleRefusedError) as refused:
            self.change(command)
        return refused.value.reason

    def rows(self) -> list[tuple[object, ...]]:
        with psycopg.connect(self.url) as connection:
            return connection.execute(
                "SELECT customer_id, vehicle_id, move_in_date, move_out_date FROM app.occupancies "
                "WHERE lease_id = %s ORDER BY move_in_date, move_out_date NULLS LAST, created_at",
                (self.lease,),
            ).fetchall()


def test_a_vehicle_is_made_under_a_customer_with_its_type_and_plate_as_typed(
    migrated_database_url: str,
) -> None:
    actor_id, _prop, _unit, customer = _walk_in(migrated_database_url)
    other = _customer(migrated_database_url, actor_id, "Other Owner")
    car = make(customer, actor_id, "CAR", "1AB-1234")
    khmer = make(customer, actor_id, "TUK_TUK", "ភ្នំពេញ 1AB 1234")
    listed = vehicles().of_customer(customer)
    assert [(v.vehicle_id, v.vehicle_type, v.plate_text, v.version) for v in listed] == [
        (car, "CAR", "1AB-1234", 1),
        (khmer, "TUK_TUK", "ភ្នំពេញ 1AB 1234", 1),
    ]
    # The plate is matched without spaces, dashes, dots and case; two vehicles may share a
    # plate (the screen warns, nothing is merged), and the match names each owner.
    twin = make(other, actor_id, "MOTORBIKE", "1ab 1234")
    found = vehicles().find_by_plate("1.AB.1234")
    assert {v.vehicle_id for v in found} == {car, twin}
    assert {v.customer_name for v in found if v.vehicle_id == twin} == {"Other Owner"}
    assert {v.vehicle_id for v in vehicles().find_by_plate("1AB1234")} == {car, twin}
    assert vehicles().find_by_plate("9ZZ-0000") == ()


def test_a_wrong_type_or_plate_is_refused_and_a_correction_keeps_the_history(
    migrated_database_url: str,
) -> None:
    actor_id, _prop, _unit, customer = _walk_in(migrated_database_url)
    for vehicle_type, plate in (
        ("BOAT", "1AB-1234"),
        ("CAR", ""),
        ("CAR", " 1AB-1234"),
        ("CAR", "x" * 33),
        ("car", "1AB-1234"),
    ):
        with pytest.raises(VehicleInvalidError):
            vehicles().create(
                VehicleCreateCommand(uuid4(), customer, vehicle_type, plate), actor_id=actor_id
            )
    car = make(customer, actor_id, "CAR", "1AB-1234")
    with pytest.raises(VehicleVersionConflictError):
        vehicles().update(VehicleUpdateCommand(car, 2, "CAR", "1AB-1235"), actor_id=actor_id)
    corrected = vehicles().update(
        VehicleUpdateCommand(car, 1, "FOOD_CART", "1AB-1235"), actor_id=actor_id
    )
    assert (corrected.vehicle_type, corrected.plate_text, corrected.version) == (
        "FOOD_CART",
        "1AB-1235",
        2,
    )
    with psycopg.connect(migrated_database_url) as connection:
        audit = connection.execute(
            "SELECT action, customer_id FROM app.audit_events WHERE entity_type = 'vehicle' "
            "AND entity_id = %s ORDER BY occurred_at",
            (car,),
        ).fetchall()
    assert audit == [("vehicle.created", customer), ("vehicle.updated", customer)]


def test_a_vehicle_is_never_deleted_and_only_the_functions_write_it(
    migrated_database_url: str,
) -> None:
    actor_id, _prop, _unit, customer = _walk_in(migrated_database_url)
    car = make(customer, actor_id, "CAR", "1AB-1234")
    with psycopg.connect(runtime_database_url()) as connection:
        for statement in (
            "UPDATE app.vehicles SET plate_text = 'x' WHERE id = %s",
            "DELETE FROM app.vehicles WHERE id = %s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement, (car,))
            connection.rollback()
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM app.vehicles WHERE id = %s", (car,))
        connection.rollback()
        grants = connection.execute(
            "SELECT has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('prm_runtime', %s, 'EXECUTE'), "
            "has_function_privilege('prm_financial', %s, 'EXECUTE')",
            (CREATE, UPDATE, MOVE_IN, CHANGE, CHANGE),
        ).fetchone()
    assert grants == (True, True, True, True, False)


def test_each_vehicle_type_parks_only_in_its_own_kind_of_place(
    migrated_database_url: str,
) -> None:
    """Owner 2026-10-30: Car → Covered or Uncovered; Motorbike → Motorbike; Tuk-tuk and food
    cart → Tuk-Tuk/Food Cart. Matched by the Parking Type code; a code the rule does not know
    (a Parking Type added later in Settings) allows no vehicle type until it is added here."""
    allowed = {
        ("CAR", "COVERED"),
        ("CAR", "UNCOVERED"),
        ("MOTORBIKE", "MOTORBIKE"),
        ("TUK_TUK", "TUK_TUK_FOOD_CART"),
        ("FOOD_CART", "TUK_TUK_FOOD_CART"),
    }
    with psycopg.connect(migrated_database_url) as connection:
        for vehicle_type in ("CAR", "MOTORBIKE", "TUK_TUK", "FOOD_CART"):
            for code in ("COVERED", "UNCOVERED", "MOTORBIKE", "TUK_TUK_FOOD_CART", "VIP"):
                row = connection.execute(
                    "SELECT app.vehicle_type_allowed(%s, %s)", (vehicle_type, code)
                ).fetchone()
                assert row == (((vehicle_type, code) in allowed),), (vehicle_type, code)


def test_the_vehicle_of_a_signer_moves_in_and_a_second_vehicle_is_refused(
    migrated_database_url: str,
) -> None:
    case = Garage(migrated_database_url)
    assert case.refused_move_in(case.move_in_command(case.friend_car)) == "VEHICLE_NOT_OF_LEASE"
    assert case.refused_move_in(case.move_in_command(case.tenant_moto)) == "VEHICLE_TYPE"
    assert case.rows() == []

    command = case.move_in_command(case.tenant_car)
    result = case.move_in(command)
    assert case.version == result["lease_version"]
    assert case.rows() == [(case.tenant, case.tenant_car, case.today, None)]
    replayed = case.service().record_lease_vehicle_move_in(
        command, actor=actor(case.actor, case.prop, MOVE_IN_CAPABILITY)
    )
    assert replayed == result
    with pytest.raises(MoveInConflictError):
        case.move_in(replace(command, reason="Another reason"))
    assert case.refused_move_in(case.move_in_command(case.joint_car)) == "VEHICLE_SECOND"
    assert case.rows() == [(case.tenant, case.tenant_car, case.today, None)]
    # A stale version is a conflict (reload), not a vehicle refusal.
    with pytest.raises(MoveInVersionConflictError):
        case.move_in(replace(case.move_in_command(case.joint_car), expected_lease_version=1))
    # The only vehicle never moves out alone. Property Rental's per-person move-out already
    # refuses the owner's row (PRIMARY_TENANT or LAST_SIGNER); the guard trigger refuses any
    # other end of a vehicle row while the Lease runs, even a direct write.
    with pytest.raises(OccupantMoveOutRefusedError):
        PostgresMoveInService(
            runtime_database_url(), case.prop, case.actor
        ).move_out_lease_occupant(
            OccupantMoveOutCommand(
                idempotency_key=uuid4(),
                event_id=uuid4(),
                lease_id=case.lease,
                expected_lease_version=case.version,
                occupancy_id=UUID(str(cast(list[object], result["occupancy_ids"])[0])),
                move_out_date=case.today,
                agreed_signer_customer_ids=(case.joint,),
                reason="Gone",
                authorization_reference=MOVE_IN_CAPABILITY,
            ),
            actor=actor(case.actor, case.prop, MOVE_IN_CAPABILITY),
        )
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error) as ended:
            connection.execute(
                "UPDATE app.occupancies SET move_out_date = %s, version = version + 1 "
                "WHERE id = %s",
                (case.today, UUID(str(cast(list[object], result["occupancy_ids"])[0]))),
            )
        assert ended.value.diag.message_hint == "VEHICLE_ONLY_ONE"
        connection.rollback()
    assert case.rows() == [(case.tenant, case.tenant_car, case.today, None)]

    lease = PostgresLeaseResourceFlow(runtime_database_url()).get(case.lease)
    parked = [o for o in lease.occupancies if o.move_out_date is None]
    assert [(o.customer_id, o.vehicle_id, o.vehicle_type, o.plate_text) for o in parked] == [
        (case.tenant, case.tenant_car, "CAR", "1AB-1234")
    ]
    assert [event.event_kind for event in lease.timeline].count("lease.move_in") == 1
    # The vehicle of a row never changes; only its dates do (Change vehicle, Move-out).
    with psycopg.connect(migrated_database_url) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE app.occupancies SET vehicle_id = %s, version = version + 1 WHERE id = %s",
                (case.joint_car, parked[0].occupancy_id),
            )
        connection.rollback()


def test_change_vehicle_keeps_both_rows_and_the_lease(migrated_database_url: str) -> None:
    case = Garage(migrated_database_url)
    assert case.refused_change(case.change_command(case.joint_car)) == "VEHICLE_NONE_IN"
    case.move_in(case.move_in_command(case.tenant_car))

    assert case.refused_change(case.change_command(case.tenant_car)) == "VEHICLE_SAME"
    assert case.refused_change(case.change_command(case.friend_car)) == "VEHICLE_NOT_OF_LEASE"
    assert case.refused_change(case.change_command(case.tenant_moto)) == "VEHICLE_TYPE"
    for day in (case.today + timedelta(days=1), case.today - timedelta(days=1)):
        assert case.refused_change(case.change_command(case.joint_car, day)) == "VEHICLE_DATE"
    with pytest.raises(MoveInVersionConflictError):
        case.change(replace(case.change_command(case.joint_car), expected_lease_version=1))

    command = case.change_command(case.joint_car)
    result = case.change(command)
    assert case.rows() == [
        (case.tenant, case.tenant_car, case.today, case.today),
        (case.joint, case.joint_car, case.today, None),
    ]
    replayed = case.service().change_lease_vehicle(
        command, actor=actor(case.actor, case.prop, MOVE_IN_CAPABILITY)
    )
    assert replayed == result
    with pytest.raises(MoveInConflictError):
        case.change(replace(command, reason="Another reason"))
    lease = PostgresLeaseResourceFlow(runtime_database_url()).get(case.lease)
    assert lease.version == case.version
    changed = [e for e in lease.timeline if e.event_kind == "lease.vehicle_changed"]
    assert [e.reason for e in changed] == ["1AB-1234 → 2CD-5678: Sold the old car"]
    # The same owner's two vehicles hand over on the same day too (the people-only
    # exclusion does not refuse it), and a vehicle that left may come back.
    tenant_second = make(case.tenant, case.actor, "CAR", "1AB-0001")
    case.change(case.change_command(tenant_second))
    case.change(case.change_command(case.tenant_car))
    assert [row[1] for row in case.rows()] == [
        case.tenant_car,
        case.joint_car,
        tenant_second,
        case.tenant_car,
    ]


def test_a_vehicle_parks_under_one_lease_at_a_time(migrated_database_url: str) -> None:
    first = Garage(migrated_database_url)
    first.move_in(first.move_in_command(first.tenant_car))
    second = Garage(migrated_database_url, tenant=first.tenant)
    assert second.refused_move_in(second.move_in_command(first.tenant_car)) == "VEHICLE_PARKED"
    second.move_in(second.move_in_command(second.tenant_car))
    assert second.refused_change(second.change_command(first.tenant_car)) == "VEHICLE_PARKED"


def test_termination_and_the_move_out_page_end_the_vehicle_row(
    migrated_database_url: str,
) -> None:
    case = Garage(migrated_database_url)
    moved = case.move_in(case.move_in_command(case.tenant_car))
    occupancy_id = UUID(str(cast(list[object], moved["occupancy_ids"])[0]))
    termination = terminate(migrated_database_url, case.actor, case.prop, case.lease, case.today)
    with psycopg.connect(migrated_database_url) as connection:
        row = connection.execute(
            "SELECT l.version, u.version FROM app.leases l JOIN app.units u ON u.id = l.unit_id "
            "WHERE l.id = %s",
            (case.lease,),
        ).fetchone()
    assert row is not None
    hand_back(
        case.prop,
        case.lease,
        case.actor,
        RecordPhysicalMoveOut(
            uuid4(),
            uuid4(),
            termination,
            int(row[0]),
            int(row[1]),
            case.today,
            "CLEANING",
            (EndedOccupancy(occupancy_id, 1),),
            "Vehicle left",
            "Authorized move-out",
            "Keys returned",
        ),
    )
    assert case.rows() == [(case.tenant, case.tenant_car, case.today, case.today)]


def test_vehicles_migration_is_head_and_forward_only() -> None:
    script = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    assert script.get_current_head() == "20270407_257"
    revision = script.get_revision("20270406_256")
    assert revision is not None
    assert revision.down_revision == "20270405_255"
    with pytest.raises(RuntimeError, match="forward-only"):
        revision.module.downgrade()
