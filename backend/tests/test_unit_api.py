"""Contract tests for the authenticated Unit API and timeline."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import ActorResolver, AuthenticatedActor, CapabilityGrant
from property_rental.unit import Unit, UnitStatus, UnitType
from property_rental.unit_api import (
    UnitDetails,
    UnitPage,
    UnitResourceNotFound,
    UnitSetupItem,
    UnitSetupItemInUse,
    UnitSetupLists,
    UnitTimelineEvent,
    UnitTimelinePage,
    UnitVersionConflict,
)

FLOOR_ONE = UUID(int=1)
FLOOR_TWO = UUID(int=2)


@dataclass(slots=True)
class InMemoryUnitFlow:
    units: dict[UUID, Unit] = field(default_factory=dict)
    events: dict[UUID, tuple[UnitTimelineEvent, ...]] = field(default_factory=dict)
    last_filter: tuple[UnitStatus | None, bool | None, int, str | None] | None = None
    setup_items: dict[UUID, UnitSetupItem] = field(default_factory=dict)

    def list(
        self,
        property_id: UUID,
        *,
        unit_status: UnitStatus | None,
        attention: bool | None,
        limit: int,
        cursor: str | None,
    ) -> UnitPage:
        self.last_filter = (unit_status, attention, limit, cursor)
        items = tuple(unit for unit in self.units.values() if unit.property_id == property_id)
        return UnitPage(items[:limit], "next" if len(items) > limit else None)

    def get(self, unit_id: UUID) -> Unit:
        try:
            return self.units[unit_id]
        except KeyError as exc:
            raise UnitResourceNotFound from exc

    def create(
        self,
        property_id: UUID,
        *,
        unit_number: str,
        floor_item_id: UUID,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        actor_id: str,
    ) -> Unit:
        del actor_id
        unit = Unit(
            uuid4(),
            property_id,
            unit_number,
            str(floor_item_id.int),
            unit_type,
            unit_status,
            floor_item_id=floor_item_id,
            size_square_metres=details.size_square_metres,
            bedrooms=details.bedrooms,
            bathrooms=details.bathrooms,
            view_item_id=details.view_item_id,
            kitchen_item_id=details.kitchen_item_id,
            notes=details.notes,
            room_feature_ids=details.room_feature_ids,
        )
        self.units[unit.unit_id] = unit
        return unit

    def patch(
        self,
        unit_id: UUID,
        *,
        floor_item_id: UUID | None,
        unit_type: str,
        unit_status: UnitStatus,
        details: UnitDetails,
        expected_version: int,
        actor_id: str,
    ) -> Unit:
        del actor_id
        current = self.get(unit_id)
        if current.version != expected_version:
            raise UnitVersionConflict(current.version)
        updated = replace(
            current,
            floor=current.floor if floor_item_id is None else str(floor_item_id.int),
            floor_item_id=floor_item_id,
            unit_type=unit_type,
            status=unit_status,
            version=current.version + 1,
            size_square_metres=details.size_square_metres,
            bedrooms=details.bedrooms,
            bathrooms=details.bathrooms,
            view_item_id=details.view_item_id,
            kitchen_item_id=details.kitchen_item_id,
            notes=details.notes,
            room_feature_ids=details.room_feature_ids,
        )
        self.units[unit_id] = updated
        return updated

    def timeline(self, unit_id: UUID, *, limit: int, cursor: str | None) -> UnitTimelinePage:
        del cursor
        self.get(unit_id)
        return UnitTimelinePage(self.events.get(unit_id, ())[:limit], None)

    def setup_lists(self, property_id: UUID, *, include_removed: bool) -> UnitSetupLists:
        return UnitSetupLists(
            tuple(
                item
                for item in self.setup_items.values()
                if item.property_id == property_id and (include_removed or not item.removed)
            )
        )

    def create_setup_item(
        self,
        property_id: UUID,
        *,
        list_kind: str,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        actor_id: str,
    ) -> UnitSetupItem:
        del actor_id
        item = UnitSetupItem(
            uuid4(), property_id, list_kind, name_en.upper(), name_en, name_km, sort_order, False, 1
        )
        self.setup_items[item.item_id] = item
        return item

    def get_setup_item(self, item_id: UUID) -> UnitSetupItem:
        try:
            return self.setup_items[item_id]
        except KeyError as exc:
            raise UnitResourceNotFound from exc

    def update_setup_item(
        self,
        item_id: UUID,
        *,
        name_en: str,
        name_km: str | None,
        sort_order: int,
        expected_version: int,
        actor_id: str,
    ) -> UnitSetupItem:
        del actor_id
        current = self.get_setup_item(item_id)
        if current.version != expected_version:
            raise UnitVersionConflict(current.version)
        updated = replace(
            current,
            name_en=name_en,
            name_km=name_km,
            sort_order=sort_order,
            version=current.version + 1,
        )
        self.setup_items[item_id] = updated
        return updated

    def remove_setup_item(
        self, item_id: UUID, *, expected_version: int, actor_id: str
    ) -> UnitSetupItem:
        del actor_id
        current = self.get_setup_item(item_id)
        if current.version != expected_version:
            raise UnitVersionConflict(current.version)
        if current.in_use:
            raise UnitSetupItemInUse
        removed = replace(current, removed=True, version=current.version + 1)
        self.setup_items[item_id] = removed
        return removed


def resolving(actor: AuthenticatedActor) -> ActorResolver:
    return lambda _: actor


def actor_with(property_id: UUID, *capabilities: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=capability, property_ids=frozenset({str(property_id)}))
            for capability in capabilities
        ),
    )


def manager(property_id: UUID) -> AuthenticatedActor:
    # Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): reading Units needs
    # `units.read`; creating and updating them still needs `property.manage`.
    return actor_with(property_id, "property.manage", "units.read")


# Login sub-slice L5: every change needs the configured Origin and the CSRF pair.
BROWSER = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=csrf-test-token",
    "X-CSRF-Token": "csrf-test-token",
}


def sample_unit(property_id: UUID, *, version: int = 1) -> Unit:
    return Unit(
        uuid4(),
        property_id,
        "101",
        "1",
        UnitType.ONE_BEDROOM,
        UnitStatus.UNDER_MAINTENANCE,
        version,
    )


def test_unit_list_is_authenticated_bounded_filtered_and_capability_sensitive() -> None:
    property_id = uuid4()
    unit = sample_unit(property_id)
    flow = InMemoryUnitFlow({unit.unit_id: unit})
    unauthenticated = TestClient(create_app(unit_resource_flow=flow))

    assert unauthenticated.get(f"/properties/{property_id}/units").status_code == 401

    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), unit_resource_flow=flow)
    )
    response = client.get(
        f"/properties/{property_id}/units?status=UNDER_MAINTENANCE&attention=true&limit=1"
    )

    assert response.status_code == 200
    assert flow.last_filter == (UnitStatus.UNDER_MAINTENANCE, True, 1, None)
    assert response.json()["data"]["can_manage"] is True
    assert response.json()["data"]["items"][0]["operational_alerts"] == ["UNDER_MAINTENANCE"]


def test_unit_create_rejects_unscoped_actor_and_unknown_fields() -> None:
    property_id = uuid4()
    flow = InMemoryUnitFlow()
    reader = TestClient(
        create_app(
            actor_resolver=lambda _: AuthenticatedActor(actor_id=str(uuid4())),
            unit_resource_flow=flow,
        )
    )
    payload = {
        "unit_number": "101",
        "floor_item_id": str(FLOOR_ONE),
        "unit_type": "STUDIO",
        "status": "VACANT",
    }

    assert (
        reader.post(f"/properties/{property_id}/units", json=payload, headers=BROWSER).status_code
        == 403
    )

    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), unit_resource_flow=flow)
    )
    payload["customer_type"] = "TENANT"
    response = client.post(f"/properties/{property_id}/units", json=payload, headers=BROWSER)

    assert response.status_code == 422
    assert flow.units == {}


def test_unit_create_detail_and_version_checked_patch() -> None:
    property_id = uuid4()
    flow = InMemoryUnitFlow()
    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), unit_resource_flow=flow)
    )

    created = client.post(
        f"/properties/{property_id}/units",
        headers=BROWSER,
        json={
            "unit_number": "101",
            "floor_item_id": str(FLOOR_ONE),
            "unit_type": "STUDIO",
            "status": "VACANT",
        },
    )
    unit_id = created.json()["data"]["unit_id"]

    assert created.status_code == 201
    assert created.headers["etag"] == '"1"'
    detail = client.get(f"/units/{unit_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["can_manage"] is True

    stale = client.patch(
        f"/units/{unit_id}",
        headers={**BROWSER, "If-Match": '"0"'},
        json={"floor_item_id": str(FLOOR_TWO)},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["current_version"] == 1

    explicit_null = client.patch(
        f"/units/{unit_id}", headers={**BROWSER, "If-Match": '"1"'}, json={"floor_item_id": None}
    )
    assert explicit_null.status_code == 422

    updated = client.patch(
        f"/units/{unit_id}",
        headers={**BROWSER, "If-Match": '"1"'},
        json={"floor_item_id": str(FLOOR_TWO), "status": "CLEANING"},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == '"2"'
    assert updated.json()["data"]["floor"] == "2"
    assert updated.json()["data"]["status"] == "CLEANING"


def test_unit_timeline_preserves_event_identity_and_has_no_delete_route() -> None:
    property_id = uuid4()
    unit = sample_unit(property_id)
    event = UnitTimelineEvent(
        event_id=uuid4(),
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        actor_id=uuid4(),
        action="unit.updated",
        entity_type="unit",
        reason="Authorized source update",
        previous_state={"status": "VACANT"},
        resulting_state={"status": "UNDER_MAINTENANCE"},
        correlation_id=uuid4(),
        outcome="SUCCEEDED",
    )
    flow = InMemoryUnitFlow({unit.unit_id: unit}, {unit.unit_id: (event,)})
    client = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(property_id, "units.read"),
            unit_resource_flow=flow,
        )
    )

    response = client.get(f"/units/{unit.unit_id}/timeline")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0] == {
        "event_id": str(event.event_id),
        "occurred_at": "2026-08-24T00:00:00+00:00",
        "actor_id": str(event.actor_id),
        "action": "unit.updated",
        "entity_type": "unit",
        "reason": "Authorized source update",
        "previous_state": {"status": "VACANT"},
        "resulting_state": {"status": "UNDER_MAINTENANCE"},
        "correlation_id": str(event.correlation_id),
        "outcome": "SUCCEEDED",
    }
    assert client.delete(f"/units/{unit.unit_id}").status_code == 405


def test_unit_reads_need_units_read_for_the_units_property() -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): the Unit list, a Unit and its
    timeline need `units.read` for the Unit's Property; without any `units.read` a missing
    Unit is refused the same way as a present one, so nothing tells which Units exist."""
    property_id = uuid4()
    unit = sample_unit(property_id)
    flow = InMemoryUnitFlow({unit.unit_id: unit})
    paths = (
        f"/properties/{property_id}/units",
        f"/units/{unit.unit_id}",
        f"/units/{unit.unit_id}/timeline",
    )
    for actor in (
        actor_with(property_id, "property.manage", "property.read"),
        actor_with(uuid4(), "units.read"),
    ):
        client = TestClient(create_app(actor_resolver=resolving(actor), unit_resource_flow=flow))
        for path in paths:
            assert client.get(path).status_code == 403, path
    nobody = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(property_id, "property.read"),
            unit_resource_flow=flow,
        )
    )
    assert nobody.get(f"/units/{uuid4()}").status_code == 403
    assert nobody.get(f"/units/{uuid4()}/timeline").status_code == 403
    reader = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(property_id, "units.read"),
            unit_resource_flow=flow,
        )
    )
    for path in paths:
        assert reader.get(path).status_code == 200, path
    assert reader.get(f"/units/{uuid4()}").status_code == 404
    assert reader.get(f"/properties/{property_id}/units").json()["data"]["can_manage"] is False


def test_unit_changes_need_the_origin_and_the_csrf_pair() -> None:
    """Login sub-slice L5 (owner answer (a) to Q-2026-10-21-160): creating or changing a Unit
    without the configured Origin or the CSRF pair is refused and changes nothing."""
    property_id = uuid4()
    unit = sample_unit(property_id)
    flow = InMemoryUnitFlow({unit.unit_id: unit})
    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), unit_resource_flow=flow)
    )
    payload = {"unit_number": "102", "floor": "1", "unit_type": "STUDIO", "status": "VACANT"}
    for headers in (
        {},
        {**BROWSER, "Origin": "https://elsewhere.example"},
        {key: value for key, value in BROWSER.items() if key != "X-CSRF-Token"},
    ):
        created = client.post(f"/properties/{property_id}/units", json=payload, headers=headers)
        assert created.status_code == 403
        changed = client.patch(
            f"/units/{unit.unit_id}",
            json={"floor": "2"},
            headers={**headers, "If-Match": '"1"'},
        )
        assert changed.status_code == 403
    assert list(flow.units) == [unit.unit_id]
    assert flow.units[unit.unit_id].floor == "1"


def test_unit_details_are_saved_kept_and_cleared_and_the_unit_number_never_changes() -> None:
    """DL-078 answer 1 and the owner's 2026-10-24 answer (V1-058 R2a)."""
    property_id = uuid4()
    flow = InMemoryUnitFlow()
    client = TestClient(
        create_app(actor_resolver=lambda _: manager(property_id), unit_resource_flow=flow)
    )
    view, feature = uuid4(), uuid4()
    created = client.post(
        f"/properties/{property_id}/units",
        headers=BROWSER,
        json={
            "unit_number": "204",
            "floor_item_id": str(FLOOR_TWO),
            "unit_type": "ONE_BEDROOM",
            "size_square_metres": "42.5",
            "bedrooms": 1,
            "bathrooms": 1,
            "view_item_id": str(view),
            "notes": "  Corner Unit  ",
            "room_feature_ids": [str(feature)],
        },
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert (data["size_square_metres"], data["bedrooms"], data["notes"]) == (
        "42.50",
        1,
        "Corner Unit",
    )
    assert data["room_feature_ids"] == [str(feature)] and data["view_item_id"] == str(view)
    unit_path = f"/units/{data['unit_id']}"
    for refused in (
        {"unit_number": "205"},
        {"unit_type": None},
        {"room_feature_ids": None},
        {"bedrooms": 21},
        {"bedrooms": "2"},
        {"size_square_metres": "0"},
        {"size_square_metres": "10000.01"},
        {"size_square_metres": "40.123"},
        {"unit_type": "one bedroom"},
        {"room_feature_ids": [str(feature), str(feature)]},
        {"notes": "x" * 2001},
    ):
        response = client.patch(unit_path, headers={**BROWSER, "If-Match": '"1"'}, json=refused)
        assert response.status_code == 422, refused
    same_number = client.patch(
        unit_path, headers={**BROWSER, "If-Match": '"1"'}, json={"unit_number": "204"}
    )
    assert same_number.status_code == 200
    kept = client.patch(
        unit_path, headers={**BROWSER, "If-Match": '"2"'}, json={"status": "CLEANING"}
    )
    assert kept.json()["data"]["size_square_metres"] == "42.50"
    assert kept.json()["data"]["room_feature_ids"] == [str(feature)]
    cleared = client.patch(
        unit_path,
        headers={**BROWSER, "If-Match": '"3"'},
        json={"view_item_id": None, "notes": None, "room_feature_ids": []},
    )
    cleared_data = cleared.json()["data"]
    assert (cleared_data["view_item_id"], cleared_data["notes"]) == (None, None)
    assert cleared_data["room_feature_ids"] == [] and cleared_data["bedrooms"] == 1
    old_contract = client.post(
        f"/properties/{property_id}/units",
        headers=BROWSER,
        json={"unit_number": "301", "floor": "3", "unit_type": "STUDIO"},
    )
    assert old_contract.status_code == 422


def test_unit_setup_lists_are_read_with_units_read_and_changed_only_with_settings_access() -> None:
    """DL-075 answer 10 and DL-074 answer 2 (V1-058 R2a)."""
    property_id = uuid4()
    flow = InMemoryUnitFlow()
    owner = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(property_id, "settings.manage", "units.read"),
            unit_resource_flow=flow,
        )
    )
    reader = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(property_id, "units.read", "property.manage"),
            unit_resource_flow=flow,
        )
    )
    stranger = TestClient(
        create_app(
            actor_resolver=lambda _: actor_with(uuid4(), "settings.manage", "units.read"),
            unit_resource_flow=flow,
        )
    )
    items_url = f"/properties/{property_id}/unit-setup/items"
    created = owner.post(
        items_url,
        headers=BROWSER,
        json={"list_kind": "VIEW", "name_en": " River ", "name_km": "ទន្លេ", "sort_order": 5},
    )
    assert created.status_code == 201
    item = created.json()["data"]
    assert (item["name_en"], item["list_kind"], item["removed"]) == ("River", "VIEW", False)
    for refused in (
        {"list_kind": "PARKING", "name_en": "Garage"},
        {"list_kind": "VIEW", "name_en": "   "},
        {"list_kind": "VIEW", "name_en": "x" * 101},
        {"list_kind": "VIEW", "name_en": "Sea", "sort_order": -1},
    ):
        assert owner.post(items_url, headers=BROWSER, json=refused).status_code == 422, refused
    assert (
        reader.post(items_url, headers=BROWSER, json={"list_kind": "VIEW", "name_en": "Sea"})
    ).status_code == 403
    listed = reader.get(f"/properties/{property_id}/unit-setup")
    assert listed.status_code == 200
    assert listed.json()["data"]["can_manage"] is False
    assert [entry["name_en"] for entry in listed.json()["data"]["lists"]["VIEW"]] == ["River"]
    assert set(listed.json()["data"]["lists"]) == {
        "FLOOR",
        "UNIT_TYPE",
        "VIEW",
        "KITCHEN",
        "ROOM_FEATURE",
    }
    assert stranger.get(f"/properties/{property_id}/unit-setup").status_code == 403
    item_url = f"/unit-setup/items/{item['item_id']}"
    assert (
        reader.patch(item_url, headers={**BROWSER, "If-Match": '"1"'}, json={"name_en": "Sea"})
    ).status_code == 403
    renamed = owner.patch(
        item_url, headers={**BROWSER, "If-Match": '"1"'}, json={"name_en": "River view"}
    )
    assert renamed.status_code == 200 and renamed.json()["data"]["name_km"] == "ទន្លេ"
    assert (
        owner.patch(item_url, headers={**BROWSER, "If-Match": '"1"'}, json={"name_en": "Old"})
    ).status_code == 412
    flow.setup_items[UUID(item["item_id"])] = replace(
        flow.setup_items[UUID(item["item_id"])], in_use=True
    )
    used = owner.post(f"{item_url}/remove", headers={**BROWSER, "If-Match": '"2"'})
    assert used.status_code == 409
    flow.setup_items[UUID(item["item_id"])] = replace(
        flow.setup_items[UUID(item["item_id"])], in_use=False
    )
    removed = owner.post(f"{item_url}/remove", headers={**BROWSER, "If-Match": '"2"'})
    assert removed.status_code == 200 and removed.json()["data"]["removed"] is True
    assert owner.get(f"/properties/{property_id}/unit-setup").json()["data"]["lists"]["VIEW"] == []
    with_removed = owner.get(f"/properties/{property_id}/unit-setup?include_removed=true")
    assert len(with_removed.json()["data"]["lists"]["VIEW"]) == 1
