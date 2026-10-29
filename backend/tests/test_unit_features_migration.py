"""Migration 20270405_255 (V1.1 part 1, owner 2026-10-29, DL-115 (I)): Unit features, Feature
types and Item types.

- Each Property has the default Feature types, Unit features and Item types; each Unit feature
  names a Feature type of its Property.
- A Manager or the Owner sets how many of each Unit feature a Unit has (1 to 9) at the Unit's
  version; each change is kept in the Unit's History.
- A Unit feature in use, or a Feature type a Unit feature names, cannot be removed.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnitResourceInvalid,
    UnitSetupItemInUse,
    UnitVersionConflict,
)
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_api_migration import runtime_database_url
from test_lease_migration import setup_sources


def _setup(url: str) -> dict[str, UUID]:
    with psycopg.connect(url) as connection:
        actor, prop, unit, _, _ = setup_sources(connection)
        connection.commit()
    return {"actor": actor, "prop": prop, "unit": unit}


def _items(flow: PostgresUnitResourceFlow, prop: UUID, kind: str) -> dict[str, UUID]:
    return {
        item.code: item.item_id
        for item in flow.setup_lists(prop, include_removed=False).items
        if item.list_kind == kind
    }


def test_each_property_has_the_default_lists(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    lists = flow.setup_lists(case["prop"], include_removed=False).items
    types = {item.item_id: item.code for item in lists if item.list_kind == "FEATURE_TYPE"}
    assert set(types.values()) >= {"ROOM", "BATHROOM", "KITCHEN", "OUTDOOR", "BUILT_IN"}
    features = {
        item.code: types[item.feature_type_item_id]
        for item in lists
        if item.list_kind == "UNIT_FEATURE" and item.feature_type_item_id is not None
    }
    assert features["BEDROOM"] == "ROOM"
    assert features["MAIN_ROOM"] == "ROOM"
    assert features["BATHROOM"] == "BATHROOM"
    assert features["KITCHENETTE"] == "KITCHEN"
    assert features["BALCONY"] == "OUTDOOR"
    assert features["WALL_AIR_CONDITIONER"] == "BUILT_IN"
    assert set(_items(flow, case["prop"], "ITEM_TYPE")) >= {
        "FURNITURE",
        "APPLIANCE",
        "ELECTRONICS",
        "LINEN",
        "KEYS",
    }


def test_unit_features_are_set_at_the_unit_version_and_kept_in_history(
    migrated_database_url: str,
) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    features = _items(flow, case["prop"], "UNIT_FEATURE")
    views = _items(flow, case["prop"], "UNIT_TYPE")
    actor = str(case["actor"])
    before = flow.get(case["unit"])
    assert before.features == ()
    wanted = ((features["BEDROOM"], 2), (features["BATHROOM"], 1))
    updated = flow.set_features(
        case["unit"], features=wanted, expected_version=before.version, actor_id=actor
    )
    assert updated.version == before.version + 1
    assert set(updated.features) == set(wanted)
    with pytest.raises(UnitVersionConflict):
        flow.set_features(
            case["unit"], features=(), expected_version=before.version, actor_id=actor
        )
    for wrong in (
        ((features["BEDROOM"], 0),),
        ((features["BEDROOM"], 10),),
        ((next(iter(views.values())), 1),),
        ((uuid4(), 1),),
    ):
        with pytest.raises(UnitResourceInvalid):
            flow.set_features(
                case["unit"], features=wrong, expected_version=updated.version, actor_id=actor
            )
    changed = flow.set_features(
        case["unit"],
        features=((features["BEDROOM"], 3), (features["BALCONY"], 1)),
        expected_version=updated.version,
        actor_id=actor,
    )
    assert set(changed.features) == {(features["BEDROOM"], 3), (features["BALCONY"], 1)}
    with psycopg.connect(migrated_database_url) as connection:
        history = connection.execute(
            "SELECT previous_state->'features', resulting_state->'features' "
            "FROM app.audit_events WHERE entity_id=%s AND action='unit.features_changed' "
            "ORDER BY occurred_at",
            (case["unit"],),
        ).fetchall()
    assert len(history) == 2
    assert history[0][0] == []
    assert {entry["count"] for entry in history[1][1]} == {3, 1}


def test_a_unit_feature_in_use_and_its_feature_type_cannot_be_removed(
    migrated_database_url: str,
) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    actor = str(case["actor"])
    room = _items(flow, case["prop"], "FEATURE_TYPE")["ROOM"]
    study = flow.create_setup_item(
        case["prop"],
        list_kind="UNIT_FEATURE",
        name_en="Study",
        name_km=None,
        sort_order=5,
        actor_id=actor,
        feature_type_item_id=room,
    )
    assert study.feature_type_item_id == room
    unit = flow.get(case["unit"])
    flow.set_features(
        case["unit"], features=((study.item_id, 1),), expected_version=unit.version, actor_id=actor
    )
    with pytest.raises(UnitSetupItemInUse):
        flow.remove_setup_item(study.item_id, expected_version=study.version, actor_id=actor)
    room_item = flow.get_setup_item(room)
    assert room_item.in_use is True
    with pytest.raises(UnitSetupItemInUse):
        flow.remove_setup_item(room, expected_version=room_item.version, actor_id=actor)


def test_a_unit_feature_needs_a_feature_type_of_its_property(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    actor = str(case["actor"])
    other = next(iter(_items(flow, case["prop"], "UNIT_TYPE").values()))
    for type_id in (None, other, uuid4()):
        with pytest.raises(UnitResourceInvalid):
            flow.create_setup_item(
                case["prop"],
                list_kind="UNIT_FEATURE",
                name_en="Loft",
                name_km=None,
                sort_order=1,
                actor_id=actor,
                feature_type_item_id=type_id,
            )
    room = _items(flow, case["prop"], "FEATURE_TYPE")["ROOM"]
    with pytest.raises(UnitResourceInvalid):
        flow.create_setup_item(
            case["prop"],
            list_kind="VIEW",
            name_en="Garden",
            name_km=None,
            sort_order=1,
            actor_id=actor,
            feature_type_item_id=room,
        )


def test_runtime_role_cannot_write_unit_features_directly(migrated_database_url: str) -> None:
    case = _setup(migrated_database_url)
    flow = PostgresUnitResourceFlow(runtime_database_url())
    bedroom = _items(flow, case["prop"], "UNIT_FEATURE")["BEDROOM"]
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "INSERT INTO app.unit_features(unit_id,item_id,feature_count) VALUES (%s,%s,1)",
            (case["unit"], bedroom),
        )
