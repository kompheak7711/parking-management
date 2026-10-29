"""HTTP tests for the Unit inventory (V1-058 R2b; DL-078 answer 2; V1.1 Item types and places,
DL-115 (I))."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.unit_api import UnitResourceNotFound, UnitVersionConflict
from property_rental.unit_inventory_api import (
    STARTER_ITEMS,
    UnitInventory,
    UnitInventoryItemName,
    UnitInventoryLine,
    _merge_known,
)
from test_unit_api import BROWSER, actor_with

FURNITURE = UUID(int=11)
APPLIANCE = UUID(int=12)
KITCHEN = UUID(int=21)
TYPES = (("FURNITURE", FURNITURE), ("APPLIANCE", APPLIANCE))


def line(kind: UUID, name: object, quantity: object = 1, **place: object) -> dict[str, object]:
    return {"item_type_item_id": str(kind), "item_name": name, "quantity": quantity, **place}


@dataclass
class InMemoryInventoryFlow:
    units: dict[UUID, UUID]
    records: dict[UUID, list[UnitInventory]] = field(default_factory=dict)

    def current(self, unit_id: UUID) -> UnitInventory:
        if unit_id not in self.units:
            raise UnitResourceNotFound("Parking was not found")
        saved = self.records.get(unit_id, [])
        if saved:
            return saved[-1]
        return UnitInventory(unit_id, self.units[unit_id], 0, None, None, ())

    def record(
        self,
        unit_id: UUID,
        *,
        lines: Sequence[UnitInventoryLine],
        expected_record_number: int,
        actor_id: str,
    ) -> UnitInventory:
        current = self.current(unit_id)
        if current.record_number != expected_record_number:
            raise UnitVersionConflict(current.record_number)
        saved = UnitInventory(
            unit_id,
            self.units[unit_id],
            current.record_number + 1,
            datetime(2026, 10, 24, tzinfo=UTC),
            UUID(actor_id),
            tuple(lines),
        )
        self.records.setdefault(unit_id, []).append(saved)
        return saved

    def known_items(self, property_id: UUID) -> tuple[UnitInventoryItemName, ...]:
        return _merge_known(
            TYPES,
            (
                UnitInventoryItemName(line.item_type_item_id, line.item_name)
                for unit_id, records in self.records.items()
                if self.units[unit_id] == property_id
                for record in records
                for line in record.lines
            ),
        )


def clients(
    property_id: UUID, flow: InMemoryInventoryFlow
) -> tuple[TestClient, TestClient, TestClient]:
    def client(*capabilities: str, scope: UUID = property_id) -> TestClient:
        return TestClient(
            create_app(
                actor_resolver=lambda _: actor_with(scope, *capabilities),
                unit_inventory_flow=flow,
            )
        )

    return (
        client("property.manage", "units.read"),
        client("units.read"),
        client("property.manage", "units.read", scope=uuid4()),
    )


def test_the_inventory_is_saved_as_numbered_records_and_an_item_left_out_is_gone() -> None:
    property_id = uuid4()
    unit_id = uuid4()
    flow = InMemoryInventoryFlow({unit_id: property_id})
    manager, reader, stranger = clients(property_id, flow)
    url = f"/units/{unit_id}/inventory"

    empty = reader.get(url)
    assert empty.status_code == 200
    assert empty.headers["ETag"] == '"0"'
    assert empty.json()["data"]["record_number"] == 0
    assert empty.json()["data"]["lines"] == []
    assert empty.json()["data"]["can_manage"] is False

    first = manager.put(
        url,
        headers={**BROWSER, "If-Match": '"0"'},
        json={
            "lines": [
                line(FURNITURE, " Bed "),
                line(FURNITURE, "Dining chair", 4),
                line(APPLIANCE, "Kettle", 2, where_item_id=str(KITCHEN), where_number=1),
            ]
        },
    )
    assert first.status_code == 200
    assert first.headers["ETag"] == '"1"'
    body = first.json()["data"]
    assert body["lines"][0] == {
        **line(FURNITURE, "Bed"),
        "where_item_id": None,
        "where_number": None,
    }
    assert body["lines"][2] == line(
        APPLIANCE, "Kettle", 2, where_item_id=str(KITCHEN), where_number=1
    )
    assert body["counts"] == {str(FURNITURE): 5, str(APPLIANCE): 2}

    second = manager.put(
        url,
        headers={**BROWSER, "If-Match": '"1"'},
        json={"lines": [line(FURNITURE, "Bed")]},
    )
    assert second.status_code == 200
    assert second.json()["data"]["record_number"] == 2
    assert [line.item_name for line in flow.records[unit_id][-1].lines] == ["Bed"]
    assert len(flow.records[unit_id]) == 2

    stale = manager.put(
        url,
        headers={**BROWSER, "If-Match": '"1"'},
        json={"lines": []},
    )
    assert stale.status_code == 412
    assert len(flow.records[unit_id]) == 2

    known = reader.get(f"/properties/{property_id}/unit-inventory-items").json()["data"]["items"]
    assert {"item_type_item_id": str(FURNITURE), "item_name": "Dining chair"} in known
    assert len(known) == len([code for code, _ in STARTER_ITEMS if code in dict(TYPES)])
    assert stranger.get(url).status_code == 403
    assert reader.get(f"/units/{uuid4()}/inventory").status_code == 404


def test_only_a_unit_manager_saves_and_bad_lines_are_refused() -> None:
    property_id = uuid4()
    unit_id = uuid4()
    flow = InMemoryInventoryFlow({unit_id: property_id})
    manager, reader, stranger = clients(property_id, flow)
    url = f"/units/{unit_id}/inventory"
    good = {"lines": [line(APPLIANCE, "Kettle")]}

    assert reader.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=good).status_code == 403
    assert stranger.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=good).status_code == 403
    assert manager.put(url, headers={"If-Match": '"0"'}, json=good).status_code == 403
    assert manager.put(url, headers=BROWSER, json=good).status_code == 412
    for refused in (
        {"lines": [{"item_type_item_id": "GARDEN", "item_name": "Hose", "quantity": 1}]},
        {"lines": [line(APPLIANCE, "  ")]},
        {"lines": [line(APPLIANCE, "x" * 101)]},
        {"lines": [line(APPLIANCE, "Kettle", 0)]},
        {"lines": [line(APPLIANCE, "Kettle", 1000)]},
        {"lines": [line(APPLIANCE, "Kettle", "2")]},
        {"lines": [line(APPLIANCE, "Kettle", where_item_id=str(KITCHEN))]},
        {"lines": [line(APPLIANCE, "Kettle", where_number=1)]},
        {"lines": [line(APPLIANCE, "Kettle", where_item_id=str(KITCHEN), where_number=10)]},
        {"lines": [line(APPLIANCE, "Kettle"), line(APPLIANCE, "KETTLE", 2)]},
        {"lines": [line(APPLIANCE, f"Item {index}") for index in range(201)]},
        {"lines": [], "note": "extra"},
    ):
        response = manager.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=refused)
        assert response.status_code == 422, refused
    assert unit_id not in flow.records


def test_the_same_item_may_be_in_two_places() -> None:
    """V1.1 (DL-115 (I)): Where tells two lines of the same item apart."""
    property_id = uuid4()
    unit_id = uuid4()
    flow = InMemoryInventoryFlow({unit_id: property_id})
    manager, _, _ = clients(property_id, flow)
    saved = manager.put(
        f"/units/{unit_id}/inventory",
        headers={**BROWSER, "If-Match": '"0"'},
        json={
            "lines": [
                line(FURNITURE, "Chair", 2, where_item_id=str(KITCHEN), where_number=1),
                line(FURNITURE, "Chair", 1, where_item_id=str(KITCHEN), where_number=2),
                line(FURNITURE, "Chair", 3),
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["counts"] == {str(FURNITURE): 6}
