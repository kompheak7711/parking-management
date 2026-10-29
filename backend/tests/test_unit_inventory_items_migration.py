"""Migration 20270406_256 (V1.1 part 1, owner 2026-10-29, DL-115 (I)): the Unit inventory by Item
type and place.

- A line names an Item type of the Unit's Property and, optionally, a place: one of the Property's
  Unit features and which one (1 to 9). The same item may be in two places.
- A record saved before V1.1 reads in the V1.1 form; an Item type in a Unit's current inventory
  cannot be removed; the lines are append-only.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from property_rental.unit_api import (
    PostgresUnitResourceFlow,
    UnitResourceInvalid,
    UnitSetupItemInUse,
)
from property_rental.unit_inventory_api import PostgresUnitInventoryFlow, UnitInventoryLine
from test_lease_api_migration import migrated_database_url as migrated_database_url
from test_lease_api_migration import runtime_database_url
from test_lease_migration import setup_sources


def _case(url: str) -> dict[str, UUID]:
    with psycopg.connect(url) as connection:
        actor, prop, unit, _, _ = setup_sources(connection)
        connection.commit()
    items = PostgresUnitResourceFlow(runtime_database_url()).setup_lists(
        prop, include_removed=False
    )
    case = {"actor": actor, "prop": prop, "unit": unit}
    for item in items.items:
        if item.list_kind in {"ITEM_TYPE", "UNIT_FEATURE", "VIEW"}:
            case.setdefault(f"{item.list_kind}:{item.code}", item.item_id)
    return case


def test_lines_name_an_item_type_and_an_optional_place(migrated_database_url: str) -> None:
    case = _case(migrated_database_url)
    flow = PostgresUnitInventoryFlow(runtime_database_url())
    actor = str(case["actor"])
    furniture = case["ITEM_TYPE:FURNITURE"]
    bedroom = case["UNIT_FEATURE:BEDROOM"]
    current = flow.current(case["unit"])
    lines = [
        UnitInventoryLine(furniture, "Chair", 2, bedroom, 1),
        UnitInventoryLine(furniture, "Chair", 1, bedroom, 2),
        UnitInventoryLine(furniture, "Chair", 3),
    ]
    saved = flow.record(
        case["unit"],
        lines=lines,
        expected_record_number=current.record_number,
        actor_id=actor,
    )
    assert set(saved.lines) == set(lines)
    for wrong in (
        UnitInventoryLine(case["UNIT_FEATURE:BEDROOM"], "Chair", 1),
        UnitInventoryLine(furniture, "Chair", 1, case["ITEM_TYPE:LINEN"], 1),
        UnitInventoryLine(furniture, "Chair", 1, bedroom, 10),
        UnitInventoryLine(uuid4(), "Chair", 1),
    ):
        with pytest.raises(UnitResourceInvalid):
            flow.record(
                case["unit"],
                lines=[wrong],
                expected_record_number=saved.record_number,
                actor_id=actor,
            )
    units = PostgresUnitResourceFlow(runtime_database_url())
    in_use = units.get_setup_item(furniture)
    assert in_use.in_use is True
    with pytest.raises(UnitSetupItemInUse):
        units.remove_setup_item(furniture, expected_version=in_use.version, actor_id=actor)


def test_a_record_saved_before_v1_1_reads_in_the_v1_1_form(migrated_database_url: str) -> None:
    case = _case(migrated_database_url)
    actor = case["actor"]
    with psycopg.connect(runtime_database_url()) as connection:
        version = connection.execute(
            "SELECT version FROM app.units WHERE id=%s", (case["unit"],)
        ).fetchone()
        assert version is not None
        connection.execute(
            "SELECT app.set_unit_features(%s, %s, %s::jsonb, %s)",
            (
                case["unit"],
                version[0],
                f'[{{"item_id": "{case["UNIT_FEATURE:KITCHEN"]}", "count": 1}}]',
                actor,
            ),
        )
        connection.execute(
            "SELECT * FROM app.record_unit_inventory(%s, %s, 0, %s::jsonb, %s)",
            (
                uuid4(),
                case["unit"],
                '[{"item_group": "KITCHEN", "item_name": "Kettle", "quantity": 1},'
                ' {"item_group": "APPLIANCES", "item_name": "Fan", "quantity": 2}]',
                actor,
            ),
        )
        connection.commit()
    read = PostgresUnitInventoryFlow(runtime_database_url()).current(case["unit"])
    assert set(read.lines) == {
        UnitInventoryLine(
            case["ITEM_TYPE:APPLIANCE"], "Kettle", 1, case["UNIT_FEATURE:KITCHEN"], 1
        ),
        UnitInventoryLine(case["ITEM_TYPE:APPLIANCE"], "Fan", 2),
    }


def test_runtime_role_cannot_write_inventory_items_directly(migrated_database_url: str) -> None:
    case = _case(migrated_database_url)
    flow = PostgresUnitInventoryFlow(runtime_database_url())
    saved = flow.record(
        case["unit"],
        lines=[UnitInventoryLine(case["ITEM_TYPE:KEYS"], "Door key", 2)],
        expected_record_number=flow.current(case["unit"]).record_number,
        actor_id=str(case["actor"]),
    )
    with psycopg.connect(migrated_database_url) as connection:
        record = connection.execute(
            "SELECT id FROM app.unit_inventory_records WHERE unit_id=%s AND record_number=%s",
            (case["unit"], saved.record_number),
        ).fetchone()
        assert record is not None
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE app.unit_inventory_items SET quantity = 3 WHERE record_id = %s",
                (record[0],),
            )
    with (
        psycopg.connect(runtime_database_url()) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "INSERT INTO app.unit_inventory_items("
            "record_id,line_number,item_type_item_id,item_name,quantity) "
            "VALUES (%s,9,%s,'Spare key',1)",
            (record[0], case["ITEM_TYPE:KEYS"]),
        )
