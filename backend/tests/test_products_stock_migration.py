"""Products, prices and stock on the real database (migration 20270424_274, V1.1 part 4, DL-121).

The price follows the cost and the mark-up (round 19); stock movements are append-only and
stock never goes below 0; each kind of movement needs its right; a place that holds stock stays
in its Unit.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_default_role_bundles_migration import SEED_QUERY
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

REVISION = "20270424_274"
GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"
NEW_RIGHTS = {
    "products.read",
    "products.manage",
    "products.prices",
    "stock.purchase",
    "stock.transfer",
    "stock.adjust",
}
CREATE = "SELECT app.create_product(%s, %s, NULL, NULL, %s, %s, NULL, NULL, %s, %s, NULL)"
MOVE = (
    "SELECT app.record_stock_movement(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, NULL)"
)


@dataclass(frozen=True)
class StockDatabase:
    owner_url: str
    runtime_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    warehouse: uuid.UUID
    room: uuid.UUID
    bedroom: uuid.UUID


@pytest.fixture(scope="module")
def stock_database(migrated_database_url: str) -> Iterator[StockDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_products_stock") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        runtime_url = _url_with_database(
            runtime_database_url(), urlsplit(temporary).path.lstrip("/")
        )
        with psycopg.connect(temporary) as setup:
            property_id = the_property(setup)
            owner = add_account(setup, "owner")
            manager = add_account(setup, "manager")
            staff = add_account(setup, "staff")
            seeded = setup.execute(SEED_QUERY, (property_id,)).fetchone()
            assert seeded is not None
            for actor, bundle in ((manager, seeded[1]), (staff, seeded[2])):
                setup.execute(
                    "INSERT INTO app.user_role_assignments (assignment_id, actor_id, "
                    "role_bundle_id, property_id, provenance) VALUES (%s, %s, %s, %s, 'test')",
                    (uuid.uuid4(), actor, bundle, property_id),
                )
            bedroom = setup.execute(
                "SELECT id FROM app.unit_setup_items WHERE property_id = %s "
                "AND list_kind = 'UNIT_FEATURE' AND code = 'BEDROOM'",
                (property_id,),
            ).fetchone()
            assert bedroom is not None
            units = []
            for number, for_rent in (("W01", False), ("U101", True)):
                unit_id = uuid.uuid4()
                setup.execute(
                    "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, "
                    "status, for_rent, created_by, updated_by) "
                    "VALUES (%s, %s, %s, '1', 'ONE_BEDROOM', 'VACANT', %s, %s, %s)",
                    (unit_id, property_id, number, for_rent, owner, owner),
                )
                setup.execute(
                    "INSERT INTO app.unit_features (unit_id, item_id, feature_count) "
                    "VALUES (%s, %s, 2)",
                    (unit_id, bedroom[0]),
                )
                units.append(unit_id)
            setup.commit()
        yield StockDatabase(
            temporary,
            runtime_url,
            property_id,
            owner,
            manager,
            staff,
            units[0],
            units[1],
            uuid.UUID(str(bedroom[0])),
        )


def grants(database: StockDatabase, actor: uuid.UUID) -> set[str]:
    with psycopg.connect(database.owner_url) as connection:
        return {str(row[0]) for row in connection.execute(GRANTS, (actor,)).fetchall()}


def run(database: StockDatabase, sql: str, *params: Any) -> Any:
    with psycopg.connect(database.runtime_url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(database: StockDatabase, state: str, sql: str, *params: Any) -> None:
    with pytest.raises(psycopg.Error) as caught:
        run(database, sql, *params)
    assert caught.value.sqlstate == state, caught.value


def product(database: StockDatabase, product_id: uuid.UUID) -> dict[str, Any]:
    with psycopg.connect(database.owner_url) as connection:
        found = connection.execute(
            "SELECT sku, cost_usd_cents, price_usd_cents, mark_up_basis_points, "
            "min_mark_up_basis_points, max_mark_up_basis_points, version, discontinued "
            "FROM app.products WHERE id = %s",
            (product_id,),
        ).fetchone()
    assert found is not None
    keys = ("sku", "cost", "price", "mark_up", "min", "max", "version", "discontinued")
    return dict(zip(keys, found, strict=True))


def move(
    database: StockDatabase,
    actor: uuid.UUID,
    kind: str,
    product_id: uuid.UUID,
    quantity: str,
    *,
    source: tuple[uuid.UUID, int] | None = None,
    target: tuple[uuid.UUID, int] | None = None,
    cost: int | None = None,
    reason: str | None = None,
) -> tuple[Any, ...]:
    return (
        MOVE,
        database.property_id,
        kind,
        product_id,
        quantity,
        None if source is None else source[0],
        None if source is None else database.bedroom,
        None if source is None else source[1],
        None if target is None else target[0],
        None if target is None else database.bedroom,
        None if target is None else target[1],
        cost,
        "ABC Shop" if kind == "PURCHASE" else None,
        "R-1" if kind == "PURCHASE" else None,
        reason,
        actor,
    )


def stock(database: StockDatabase, product_id: uuid.UUID, unit: uuid.UUID, number: int) -> int:
    with psycopg.connect(database.owner_url) as connection:
        found = connection.execute(
            "SELECT app.stock_at(%s, %s, %s, %s)", (product_id, unit, database.bedroom, number)
        ).fetchone()
    assert found is not None
    return int(found[0])


def test_migration_274_follows_the_roles() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270423_273"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def test_the_default_roles_get_the_product_rights(stock_database: StockDatabase) -> None:
    database = stock_database
    assert NEW_RIGHTS <= grants(database, database.owner)
    assert grants(database, database.manager) & NEW_RIGHTS == NEW_RIGHTS - {"products.prices"}
    assert grants(database, database.staff) & NEW_RIGHTS == {
        "products.read",
        "stock.purchase",
        "stock.transfer",
    }
    with psycopg.connect(database.owner_url) as connection:
        mapped = connection.execute(
            "SELECT capability_id, permission_code FROM app.permission_capabilities "
            "WHERE capability_id = ANY(%s)",
            (sorted(NEW_RIGHTS),),
        ).fetchall()
        rule = connection.execute(
            "SELECT format FROM app.number_rules WHERE document_type = 'STOCK_MOVEMENT'"
        ).fetchone()
        categories = connection.execute(
            "SELECT code, kind FROM app.product_categories ORDER BY sort_order"
        ).fetchall()
    assert {str(row[0]) for row in mapped} == NEW_RIGHTS
    assert rule is not None and rule[0] == "SMyy000n"
    assert [tuple(row) for row in categories] == [
        ("FURNITURE", "ITEM"),
        ("APPLIANCES", "ITEM"),
        ("BEDDING", "ITEM"),
        ("KEYS", "ITEM"),
        ("SERVICES", "SERVICE"),
    ]


def test_the_price_follows_the_cost_and_the_mark_up(stock_database: StockDatabase) -> None:
    database = stock_database
    bed = run(
        database,
        CREATE,
        database.property_id,
        "Bed frame",
        "FURNITURE",
        "PIECE",
        None,
        database.manager,
    )
    first = product(database, bed)
    assert first["sku"].startswith("P") and first["price"] is None and first["cost"] is None
    # The business rules: mark-up 20%, minimum 15%, no maximum, round up to $0.10.
    assert (first["mark_up"], first["min"], first["max"]) == (2000, 1500, None)
    warehouse = (database.warehouse, 1)
    run(
        database, *move(database, database.staff, "PURCHASE", bed, "3", target=warehouse, cost=1000)
    )
    assert (product(database, bed)["cost"], product(database, bed)["price"]) == (1000, 1200)
    # $10.50: the real mark-up of $12.00 is 14.3%, below the minimum, so the price is set again.
    run(
        database, *move(database, database.staff, "PURCHASE", bed, "1", target=warehouse, cost=1050)
    )
    assert product(database, bed)["price"] == 1260
    # $10.00 again: 26% is in range (no maximum), so the price stays.
    run(
        database, *move(database, database.staff, "PURCHASE", bed, "1", target=warehouse, cost=1000)
    )
    assert (product(database, bed)["cost"], product(database, bed)["price"]) == (1000, 1260)
    version = product(database, bed)["version"]
    # Only the Owner changes a mark-up; the price is set again at once.
    refused(
        database,
        "42501",
        "SELECT app.set_product_mark_ups(%s, %s, 3000, 1500, NULL, %s, NULL)",
        bed,
        version,
        database.manager,
    )
    refused(
        database,
        "22023",
        "SELECT app.set_product_mark_ups(%s, %s, 1000, 1500, NULL, %s, NULL)",
        bed,
        version,
        database.owner,
    )
    refused(
        database,
        "40001",
        "SELECT app.set_product_mark_ups(%s, %s, 3000, 1500, NULL, %s, NULL)",
        bed,
        version - 1,
        database.owner,
    )
    run(
        database,
        "SELECT app.set_product_mark_ups(%s, %s, 3000, 1500, 4000, %s, NULL)",
        bed,
        version,
        database.owner,
    )
    assert product(database, bed)["price"] == 1300
    # A price above the maximum after a cheaper Purchase is set again too.
    run(database, *move(database, database.staff, "PURCHASE", bed, "1", target=warehouse, cost=800))
    assert product(database, bed)["price"] == 1040
    with psycopg.connect(database.owner_url) as connection:
        history = connection.execute(
            "SELECT price_usd_cents, cause FROM app.product_price_history "
            "WHERE product_id = %s ORDER BY created_at",
            (bed,),
        ).fetchall()
    assert [tuple(row) for row in history] == [
        (1200, "PURCHASE"),
        (1260, "PURCHASE"),
        (1300, "MARK_UP"),
        (1040, "PURCHASE"),
    ]

    # A Service: its cost is typed, rounded up to the next $0.10.
    cleaning = run(
        database,
        CREATE,
        database.property_id,
        "Room cleaning",
        "SERVICES",
        "TIME",
        333,
        database.manager,
    )
    assert product(database, cleaning)["price"] == 400
    refused(
        database,
        "22023",
        CREATE,
        database.property_id,
        "Fan",
        "APPLIANCES",
        "PIECE",
        500,
        database.manager,
    )
    refused(
        database,
        "22023",
        CREATE,
        database.property_id,
        "Repair",
        "SERVICES",
        "PIECE",
        500,
        database.manager,
    )
    refused(
        database,
        "42501",
        CREATE,
        database.property_id,
        "Lamp",
        "FURNITURE",
        "PIECE",
        None,
        database.staff,
    )
    refused(
        database,
        "23505",
        CREATE,
        database.property_id,
        "bed frame",
        "FURNITURE",
        "PIECE",
        None,
        database.manager,
    )
    service_version = product(database, cleaning)["version"]
    run(
        database,
        "SELECT app.set_service_cost(%s, %s, 1000, %s, NULL)",
        cleaning,
        service_version,
        database.manager,
    )
    assert product(database, cleaning)["price"] == 1200


def test_stock_never_goes_below_zero_and_each_movement_needs_its_right(
    stock_database: StockDatabase,
) -> None:
    database = stock_database
    fan = run(
        database,
        CREATE,
        database.property_id,
        "Ceiling fan",
        "APPLIANCES",
        "PIECE",
        None,
        database.manager,
    )
    shelf = (database.warehouse, 2)
    room = (database.room, 1)
    number = run(
        database, *move(database, database.staff, "PURCHASE", fan, "2", target=shelf, cost=2500)
    )
    assert str(number).startswith("SM")
    refused(
        database,
        "55000",
        *move(database, database.staff, "TRANSFER", fan, "3", source=shelf, target=room),
    )
    transfer = run(
        database, *move(database, database.staff, "TRANSFER", fan, "2", source=shelf, target=room)
    )
    assert (stock(database, fan, *shelf), stock(database, fan, *room)) == (0, 2)
    with psycopg.connect(database.owner_url) as connection:
        pair = connection.execute(
            "SELECT kind FROM app.product_transactions WHERE movement_number = %s ORDER BY kind",
            (transfer,),
        ).fetchall()
    assert [row[0] for row in pair] == ["TRANSFER_IN", "TRANSFER_OUT"]
    # Rules for each kind.
    refused(
        database,
        "42501",
        *move(database, database.staff, "ADJUSTMENT_OUT", fan, "1", source=room, reason="Broken"),
    )
    refused(
        database,
        "22023",
        *move(database, database.manager, "ADJUSTMENT_OUT", fan, "1", source=room),
    )
    refused(
        database,
        "22023",
        *move(database, database.staff, "PURCHASE", fan, "1.5", target=shelf, cost=2500),
    )
    refused(
        database,
        "22023",
        *move(database, database.staff, "PURCHASE", fan, "1", target=(database.room, 3), cost=2500),
    )
    refused(
        database,
        "22023",
        *move(database, database.staff, "TRANSFER", fan, "1", source=room, target=room),
    )
    run(
        database,
        *move(database, database.manager, "ADJUSTMENT_OUT", fan, "1", source=room, reason="Broken"),
    )
    assert stock(database, fan, *room) == 1
    # A discontinued product is not bought again, but its stock still moves.
    version = product(database, fan)["version"]
    run(
        database,
        "SELECT app.change_product(%s, %s, 'Ceiling fan', NULL, NULL, 'APPLIANCES', 'PIECE', "
        "NULL, NULL, true, %s, NULL)",
        fan,
        version,
        database.manager,
    )
    refused(
        database,
        "55000",
        *move(database, database.staff, "PURCHASE", fan, "1", target=shelf, cost=2500),
    )
    run(database, *move(database, database.staff, "TRANSFER", fan, "1", source=room, target=shelf))
    # A Service has no stock.
    service = run(
        database, CREATE, database.property_id, "Laundry", "SERVICES", "BAG", 200, database.manager
    )
    refused(
        database,
        "22023",
        *move(database, database.staff, "PURCHASE", service, "1", target=shelf, cost=100),
    )


def test_movements_are_append_only_and_a_place_with_stock_stays(
    stock_database: StockDatabase,
) -> None:
    database = stock_database
    lamp = run(
        database,
        CREATE,
        database.property_id,
        "Desk lamp",
        "FURNITURE",
        "PIECE",
        None,
        database.manager,
    )
    run(
        database,
        *move(database, database.staff, "PURCHASE", lamp, "1", target=(database.room, 2), cost=900),
    )
    with psycopg.connect(database.owner_url) as connection:
        for sql in (
            "UPDATE app.product_transactions SET quantity = 5 WHERE product_id = %s",
            "DELETE FROM app.product_transactions WHERE product_id = %s",
            "DELETE FROM app.products WHERE id = %s",
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(sql, (lamp,))
            connection.rollback()
        # Bedroom 2 of U101 holds the lamp: the Unit keeps two bedrooms.
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE app.unit_features SET feature_count = 1 WHERE unit_id = %s",
                (database.room,),
            )
        connection.rollback()
    with psycopg.connect(database.runtime_url) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM app.product_transactions")
    # Add place gives the next number, at most 9.
    for expected in range(3, 10):
        assert (
            run(
                database,
                "SELECT app.add_unit_place(%s, %s, %s, NULL)",
                database.warehouse,
                database.bedroom,
                database.manager,
            )
            == expected
        )
    refused(
        database,
        "22023",
        "SELECT app.add_unit_place(%s, %s, %s, NULL)",
        database.warehouse,
        database.bedroom,
        database.manager,
    )
    refused(
        database,
        "42501",
        "SELECT app.add_unit_place(%s, %s, %s, NULL)",
        database.room,
        database.bedroom,
        database.staff,
    )


def test_the_product_flow_reads_and_writes_through_the_functions(
    stock_database: StockDatabase,
) -> None:
    """API-PS-001: the Postgres flow of Building > Products on the real database."""
    from property_rental.products_api import (
        PostgresProductFlow,
        ProductConflict,
        ProductForbidden,
        ProductNotFound,
        ProductStale,
    )

    database = stock_database
    flow = PostgresProductFlow(database.runtime_url)
    owner, staff = str(database.owner), str(database.staff)
    fields = {
        "name_en": "Kettle flow",
        "category_code": "APPLIANCES",
        "measure_unit": "PIECE",
        "reorder_level": 1,
    }
    product_id = flow.create(database.property_id, fields, actor_id=owner)
    with pytest.raises(ProductConflict):
        flow.create(database.property_id, fields, actor_id=owner)
    with pytest.raises(ProductForbidden):
        flow.create(database.property_id, {**fields, "name_en": "Other"}, actor_id=staff)
    warehouse = {"unit_id": database.warehouse, "item_id": database.bedroom, "number": 1}
    room = {"unit_id": database.room, "item_id": database.bedroom, "number": 2}
    purchase = {
        "kind": "PURCHASE",
        "product_id": product_id,
        "quantity": "3",
        "from": None,
        "to": warehouse,
        "unit_cost_usd_cents": 1000,
        "supplier": "Market",
        "receipt_reference": "R-1",
    }
    number = flow.record_movement(database.property_id, purchase, actor_id=staff)
    assert number.startswith("SM")
    transfer = {"kind": "TRANSFER", "product_id": product_id, "quantity": "2"}
    flow.record_movement(
        database.property_id, {**transfer, "from": warehouse, "to": room}, actor_id=staff
    )
    with pytest.raises(ProductConflict, match="not enough stock"):
        flow.record_movement(
            database.property_id, {**transfer, "from": warehouse, "to": room}, actor_id=staff
        )
    catalogue: Any = flow.catalogue(database.property_id)
    found = next(row for row in catalogue["products"] if row["product_id"] == str(product_id))
    assert found["stock"] == "3" and found["price_usd_cents"] == 1200
    assert found["real_mark_up_basis_points"] == 2000 and found["low_stock"] is False
    version = found["version"]
    with pytest.raises(ProductStale):
        flow.set_mark_ups(
            database.property_id,
            product_id,
            version + 5,
            {"mark_up_basis_points": 3000, "min_mark_up_basis_points": 1500},
            actor_id=owner,
        )
    flow.set_mark_ups(
        database.property_id,
        product_id,
        version,
        {"mark_up_basis_points": 3000, "min_mark_up_basis_points": 1500},
        actor_id=owner,
    )
    assert [row["price_usd_cents"] for row in flow.prices(database.property_id, product_id)] == [
        1300,
        1200,
    ]
    with pytest.raises(ProductNotFound):
        flow.prices(uuid.uuid4(), product_id)
    moves = flow.movements(database.property_id, product_id)
    assert [row["kind"] for row in moves][-1] == "PURCHASE" and len(moves) == 3
    locations: Any = flow.locations(database.property_id)
    held = {
        (row["unit_id"], row["number"]): {
            line["product_id"]: line["quantity"] for line in row["stock"]
        }
        for row in locations["places"]
    }
    assert held[(str(database.room), 2)][str(product_id)] == "2"
    assert held[(str(database.warehouse), 1)][str(product_id)] == "1"
    assert (
        flow.add_place(database.property_id, database.room, database.bedroom, actor_id=owner) == 3
    )


def test_the_unit_inventory_rows_are_saved_all_or_none(stock_database: StockDatabase) -> None:
    """V1.1 part 5 (DL-122): a refused row leaves no movement from the same save."""
    from property_rental.products_api import PostgresProductFlow, ProductConflict

    database = stock_database
    flow = PostgresProductFlow(database.runtime_url)
    owner, staff = str(database.owner), str(database.staff)
    product_id = flow.create(
        database.property_id,
        {"name_en": "Bed batch", "category_code": "FURNITURE", "measure_unit": "PIECE"},
        actor_id=owner,
    )
    warehouse = {"unit_id": database.warehouse, "item_id": database.bedroom, "number": 2}
    rooms = [{"unit_id": database.room, "item_id": database.bedroom, "number": n} for n in (1, 2)]
    flow.record_movement(
        database.property_id,
        {
            "kind": "PURCHASE",
            "product_id": product_id,
            "quantity": "2",
            "to": warehouse,
            "unit_cost_usd_cents": 5000,
        },
        actor_id=staff,
    )
    move = {"kind": "TRANSFER", "product_id": product_id, "from": warehouse}
    with pytest.raises(ProductConflict, match="not enough stock"):
        flow.record_movements(
            database.property_id,
            [{**move, "quantity": "1", "to": rooms[0]}, {**move, "quantity": "2", "to": rooms[1]}],
            actor_id=staff,
        )
    assert len(flow.movements(database.property_id, product_id)) == 1
    numbers = flow.record_movements(
        database.property_id,
        [{**move, "quantity": "1", "to": room} for room in rooms],
        actor_id=staff,
    )
    assert len(set(numbers)) == 2
    assert len(flow.movements(database.property_id, product_id)) == 5
