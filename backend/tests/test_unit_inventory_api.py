"""HTTP tests for the Unit inventory (V1-058 R2b; DL-078 answer 2)."""

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


@dataclass
class InMemoryInventoryFlow:
    units: dict[UUID, UUID]
    records: dict[UUID, list[UnitInventory]] = field(default_factory=dict)

    def current(self, unit_id: UUID) -> UnitInventory:
        if unit_id not in self.units:
            raise UnitResourceNotFound("Unit was not found")
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
            UnitInventoryItemName(line.item_group, line.item_name)
            for unit_id, records in self.records.items()
            if self.units[unit_id] == property_id
            for record in records
            for line in record.lines
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
                {"item_group": "FURNITURE", "item_name": " Bed ", "quantity": 1},
                {"item_group": "FURNITURE", "item_name": "Dining chair", "quantity": 4},
                {"item_group": "APPLIANCES", "item_name": "Air conditioner", "quantity": 2},
            ]
        },
    )
    assert first.status_code == 200
    assert first.headers["ETag"] == '"1"'
    body = first.json()["data"]
    assert body["lines"][0] == {"item_group": "FURNITURE", "item_name": "Bed", "quantity": 1}
    assert body["counts"] == {"FURNITURE": 5, "APPLIANCES": 2, "KITCHEN": 0, "BATHROOM": 0}

    second = manager.put(
        url,
        headers={**BROWSER, "If-Match": '"1"'},
        json={"lines": [{"item_group": "FURNITURE", "item_name": "Bed", "quantity": 1}]},
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
    assert {"item_group": "FURNITURE", "item_name": "Dining chair"} in known
    assert len(known) == len(STARTER_ITEMS)
    assert stranger.get(url).status_code == 403
    assert reader.get(f"/units/{uuid4()}/inventory").status_code == 404


def test_only_a_unit_manager_saves_and_bad_lines_are_refused() -> None:
    property_id = uuid4()
    unit_id = uuid4()
    flow = InMemoryInventoryFlow({unit_id: property_id})
    manager, reader, stranger = clients(property_id, flow)
    url = f"/units/{unit_id}/inventory"
    good = {"lines": [{"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 1}]}

    assert reader.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=good).status_code == 403
    assert stranger.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=good).status_code == 403
    assert manager.put(url, headers={"If-Match": '"0"'}, json=good).status_code == 403
    assert manager.put(url, headers=BROWSER, json=good).status_code == 412
    for refused in (
        {"lines": [{"item_group": "GARDEN", "item_name": "Hose", "quantity": 1}]},
        {"lines": [{"item_group": "KITCHEN", "item_name": "  ", "quantity": 1}]},
        {"lines": [{"item_group": "KITCHEN", "item_name": "x" * 101, "quantity": 1}]},
        {"lines": [{"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 0}]},
        {"lines": [{"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 1000}]},
        {"lines": [{"item_group": "KITCHEN", "item_name": "Kettle", "quantity": "2"}]},
        {
            "lines": [
                {"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 1},
                {"item_group": "KITCHEN", "item_name": "KETTLE", "quantity": 2},
            ]
        },
        {
            "lines": [
                {"item_group": "KITCHEN", "item_name": f"Item {index}", "quantity": 1}
                for index in range(201)
            ]
        },
        {"lines": [], "note": "extra"},
    ):
        response = manager.put(url, headers={**BROWSER, "If-Match": '"0"'}, json=refused)
        assert response.status_code == 422, refused
    assert unit_id not in flow.records
