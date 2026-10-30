"""Vehicle routes (Parking Step 4, owner 2026-10-30): a vehicle is a record under a Customer.

Reading needs `customers.read`; adding or correcting needs `customers.manage`. The plate lookup
answers every vehicle whose plate matches without spaces, dashes, dots and case, so the screen
can warn about a duplicate; nothing is merged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.customer import Customer
from property_rental.customer_api import CustomerRecord
from property_rental.identity import AuthenticatedActor
from property_rental.vehicle import (
    Vehicle,
    VehicleCreateCommand,
    VehicleNotFoundError,
    VehicleUpdateCommand,
    VehicleVersionConflictError,
)
from test_customer_api import InMemoryCustomerFlow, manager, mutation_headers, reader


@dataclass
class InMemoryVehicleFlow:
    vehicles: dict[UUID, Vehicle] = field(default_factory=dict)
    names: dict[UUID, str] = field(default_factory=dict)
    created_by: UUID | None = None

    def get(self, vehicle_id: UUID) -> Vehicle:
        try:
            return self.vehicles[vehicle_id]
        except KeyError as exc:
            raise VehicleNotFoundError from exc

    def of_customer(self, customer_id: UUID) -> tuple[Vehicle, ...]:
        return tuple(v for v in self.vehicles.values() if v.customer_id == customer_id)

    def find_by_plate(self, plate_text: str) -> tuple[Vehicle, ...]:
        key = "".join(ch for ch in plate_text.upper() if ch not in " -.")
        return tuple(
            v
            for v in self.vehicles.values()
            if "".join(ch for ch in v.plate_text.upper() if ch not in " -.") == key
        )

    def create(self, command: VehicleCreateCommand, *, actor_id: UUID) -> Vehicle:
        self.created_by = actor_id
        vehicle = Vehicle(
            command.vehicle_id,
            command.customer_id,
            self.names[command.customer_id],
            command.vehicle_type,
            command.plate_text,
            1,
        )
        self.vehicles[vehicle.vehicle_id] = vehicle
        return vehicle

    def update(self, command: VehicleUpdateCommand, *, actor_id: UUID) -> Vehicle:
        del actor_id
        current = self.get(command.vehicle_id)
        if current.version != command.expected_version:
            raise VehicleVersionConflictError
        vehicle = replace(
            current,
            vehicle_type=command.vehicle_type,
            plate_text=command.plate_text,
            version=current.version + 1,
        )
        self.vehicles[vehicle.vehicle_id] = vehicle
        return vehicle


def client(
    customers: InMemoryCustomerFlow, vehicles: InMemoryVehicleFlow, actor: AuthenticatedActor
) -> TestClient:
    return TestClient(
        create_app(
            actor_resolver=lambda _: actor,
            customer_resource_flow=customers,
            vehicle_flow=vehicles,
        )
    )


def customer(property_id: UUID, name: str, *, active: bool = True) -> CustomerRecord:
    return CustomerRecord(
        Customer(uuid4(), name),
        property_id,
        deactivated_at=None if active else datetime(2026, 1, 1, tzinfo=UTC),
        deactivation_reason=None if active else "Left",
    )


def test_vehicle_routes_need_the_customer_rights_and_check_the_body() -> None:
    property_id = uuid4()
    dara = customer(property_id, "Sok Dara")
    gone = customer(property_id, "Pich Rina", active=False)
    customers = InMemoryCustomerFlow(
        property_id, {dara.customer.customer_id: dara, gone.customer.customer_id: gone}
    )
    vehicles = InMemoryVehicleFlow(names={dara.customer.customer_id: "Sok Dara"})
    path = f"/api/v1/customers/{dara.customer.customer_id}/vehicles"
    body = {"vehicle_id": str(uuid4()), "vehicle_type": "CAR", "plate_text": "1AB-1234"}

    nobody = client(customers, vehicles, AuthenticatedActor(str(uuid4()), frozenset()))
    assert nobody.get(path).status_code == 404
    reading = client(customers, vehicles, reader(property_id))
    assert reading.get(path).json()["data"] == []
    assert reading.post(path, headers=mutation_headers(), json=body).status_code == 404
    assert vehicles.vehicles == {}

    who = manager(property_id)
    managing = client(customers, vehicles, who)
    for wrong in (
        {**body, "vehicle_type": "BOAT"},
        {**body, "plate_text": ""},
        {**body, "plate_text": "x" * 33},
        {**body, "plate_text": " 1AB-1234 "},
        {**body, "photo": "x"},
    ):
        assert managing.post(path, headers=mutation_headers(), json=wrong).status_code == 422
    assert vehicles.vehicles == {}
    missing = f"/api/v1/customers/{uuid4()}/vehicles"
    assert managing.post(missing, headers=mutation_headers(), json=body).status_code == 404
    inactive = f"/api/v1/customers/{gone.customer.customer_id}/vehicles"
    assert managing.post(inactive, headers=mutation_headers(), json=body).status_code == 409

    made = managing.post(path, headers=mutation_headers(), json=body)
    assert made.status_code == 201, made.text
    assert made.headers["etag"] == '"1"'
    assert made.json()["data"] == {
        **body,
        "customer_id": str(dara.customer.customer_id),
        "customer_name": "Sok Dara",
        "version": 1,
    }
    assert vehicles.created_by == UUID(who.actor_id)
    assert reading.get(path).json()["data"] == [made.json()["data"]]

    edit = f"/api/v1/vehicles/{body['vehicle_id']}"
    change = {"vehicle_type": "FOOD_CART", "plate_text": "1AB-1235"}
    assert reading.patch(edit, headers=mutation_headers(1), json=change).status_code == 404
    assert managing.patch(edit, headers=mutation_headers(), json=change).status_code == 428
    assert managing.patch(edit, headers=mutation_headers(2), json=change).status_code == 412
    assert (
        managing.patch(
            f"/api/v1/vehicles/{uuid4()}", headers=mutation_headers(1), json=change
        ).status_code
        == 404
    )
    corrected = managing.patch(edit, headers=mutation_headers(1), json=change)
    assert corrected.status_code == 200, corrected.text
    assert corrected.headers["etag"] == '"2"'
    assert corrected.json()["data"]["plate_text"] == "1AB-1235"
    assert corrected.json()["data"]["version"] == 2


def test_the_plate_lookup_names_every_owner_with_that_plate() -> None:
    property_id = uuid4()
    dara = customer(property_id, "Sok Dara")
    vanna = customer(property_id, "Chan Vanna")
    customers = InMemoryCustomerFlow(
        property_id, {dara.customer.customer_id: dara, vanna.customer.customer_id: vanna}
    )
    vehicles = InMemoryVehicleFlow(
        {
            (first := uuid4()): Vehicle(
                first, dara.customer.customer_id, "Sok Dara", "CAR", "1AB-1234", 1
            ),
            (second := uuid4()): Vehicle(
                second, vanna.customer.customer_id, "Chan Vanna", "MOTORBIKE", "1ab 1234", 1
            ),
            (other := uuid4()): Vehicle(
                other, vanna.customer.customer_id, "Chan Vanna", "CAR", "9ZZ-0000", 1
            ),
        }
    )
    path = f"/api/v1/properties/{property_id}/vehicles"
    assert (
        client(customers, vehicles, reader(uuid4()))
        .get(path, params={"plate": "1AB1234"})
        .status_code
        == 404
    )
    api = client(customers, vehicles, reader(property_id))
    assert api.get(path).status_code == 422
    assert api.get(path, params={"plate": ""}).status_code == 422
    assert api.get(path, params={"plate": "x" * 33}).status_code == 422
    found = api.get(path, params={"plate": "1.AB.1234"})
    assert found.status_code == 200, found.text
    assert {item["vehicle_id"] for item in found.json()["data"]} == {str(first), str(second)}
    assert {item["customer_name"] for item in found.json()["data"]} == {"Sok Dara", "Chan Vanna"}
    assert api.get(path, params={"plate": "nothing"}).json()["data"] == []
