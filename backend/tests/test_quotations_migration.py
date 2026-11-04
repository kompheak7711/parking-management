"""Quotations and the Products Invoice on the real database (migration 20270425_275, V1.1 part 6,
DL-123).

A Quotation keeps its prices and is never changed: a new one replaces it. A price is never above
the list price and a lower price needs its right and a reason. "Customer signed" issues the
Invoice at once and takes the Items out of stock, all or nothing; a voided Invoice puts them back.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from test_default_role_bundles_migration import SEED_QUERY
from test_invoice_migration import financial_database_url
from test_migrations import _run_alembic, _temporary_migration_database, _url_with_database
from test_move_in_migration import migrated_database_url as migrated_database_url
from test_move_in_migration import runtime_database_url
from test_role_bundle_migration import add_account, the_property

REVISION = "20270425_275"
GRANTS = "SELECT capability_id FROM app.actor_capability_grants(%s)"
RIGHTS = {"quotations.read", "quotations.make", "quotations.lower_price"}
CREATE = "SELECT app.create_product(%s, %s, NULL, NULL, %s, %s, NULL, NULL, %s, %s, NULL)"
PURCHASE = (
    "SELECT app.record_stock_movement(%s, 'PURCHASE', %s, %s, NULL, NULL, NULL, %s, %s, %s, "
    "%s, 'ABC Shop', 'R-1', NULL, %s, NULL)"
)
MAKE = "SELECT app.make_quotation(%s, %s, NULL, %s, %s, %s, %s::jsonb, %s, NULL)"
SIGN = "SELECT app.sign_quotation(%s, %s, %s, %s, %s::jsonb, %s, NULL)"
REFUSE = "SELECT app.refuse_quotation(%s, %s, %s, %s, %s, NULL)"
READ = "SELECT app.quotation_read(%s, %s, %s)"


@dataclass(frozen=True)
class QuotationDatabase:
    owner_url: str
    runtime_url: str
    financial_url: str
    property_id: uuid.UUID
    owner: uuid.UUID
    manager: uuid.UUID
    staff: uuid.UUID
    warehouse: uuid.UUID
    cabinet: uuid.UUID
    customer: uuid.UUID


@pytest.fixture(scope="module")
def quotation_database(migrated_database_url: str) -> Iterator[QuotationDatabase]:
    assert migrated_database_url
    with _temporary_migration_database("prm_quotations") as temporary:
        assert _run_alembic("upgrade", "head").returncode == 0
        name = urlsplit(temporary).path.lstrip("/")
        runtime_url = _url_with_database(runtime_database_url(), name)
        financial_url = _url_with_database(financial_database_url(), name)
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
            cabinet = setup.execute(
                "SELECT id FROM app.unit_setup_items WHERE property_id = %s "
                "AND list_kind = 'UNIT_FEATURE' AND code = 'BEDROOM'",
                (property_id,),
            ).fetchone()
            assert cabinet is not None
            warehouse = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.units (id, property_id, unit_number, floor, unit_type, "
                "status, for_rent, created_by, updated_by) "
                "VALUES (%s, %s, 'W01', '1', 'ONE_BEDROOM', 'VACANT', false, %s, %s)",
                (warehouse, property_id, owner, owner),
            )
            setup.execute(
                "INSERT INTO app.unit_features (unit_id, item_id, feature_count)"
                " VALUES (%s, %s, 2)",
                (warehouse, cabinet[0]),
            )
            customer = uuid.uuid4()
            setup.execute(
                "INSERT INTO app.customers (id, legal_name, phone_number, created_by, updated_by) "
                "VALUES (%s, 'Keo Vannak', '012 345 678', %s, %s)",
                (customer, owner, owner),
            )
            setup.commit()
        yield QuotationDatabase(
            temporary,
            runtime_url,
            financial_url,
            property_id,
            owner,
            manager,
            staff,
            warehouse,
            uuid.UUID(str(cabinet[0])),
            customer,
        )


def run(url: str, sql: str, *params: Any) -> Any:
    with psycopg.connect(url) as connection:
        row = connection.execute(sql, params).fetchone()
        assert row is not None
        return row[0]


def refused(url: str, state: str, sql: str, *params: Any) -> None:
    with pytest.raises(psycopg.Error) as caught:
        run(url, sql, *params)
    assert caught.value.sqlstate == state, caught.value


def lines(*rows: tuple[uuid.UUID, int, int]) -> str:
    return json.dumps(
        [
            {"product_id": str(product), "quantity": quantity, "price_usd_cents": price}
            for product, quantity, price in rows
        ]
    )


def products(database: QuotationDatabase) -> tuple[uuid.UUID, uuid.UUID]:
    """A Fan bought at $25.00 (price $30.00) and a cleaning Service at $12.50 (price $15.00)."""
    suffix = uuid.uuid4().hex[:6]
    fan = run(
        database.runtime_url,
        CREATE,
        database.property_id,
        f"Fan {suffix}",
        "APPLIANCES",
        "PIECE",
        None,
        database.manager,
    )
    cleaning = run(
        database.runtime_url,
        CREATE,
        database.property_id,
        f"Cleaning {suffix}",
        "SERVICES",
        "TIME",
        1250,
        database.manager,
    )
    return fan, cleaning


def buy(database: QuotationDatabase, product: uuid.UUID, quantity: str) -> None:
    run(
        database.runtime_url,
        PURCHASE,
        database.property_id,
        product,
        quantity,
        database.warehouse,
        database.cabinet,
        1,
        2500,
        database.manager,
    )


def stock(database: QuotationDatabase, product: uuid.UUID) -> int:
    return int(
        run(
            database.owner_url,
            "SELECT app.stock_at(%s, %s, %s, 1)",
            product,
            database.warehouse,
            database.cabinet,
        )
    )


def read(database: QuotationDatabase, quotation: uuid.UUID) -> dict[str, Any]:
    found = run(database.runtime_url, READ, database.property_id, quotation, database.staff)
    assert isinstance(found, dict)
    return found


def take(database: QuotationDatabase, position: int = 1) -> str:
    return json.dumps(
        {
            str(position): {
                "unit_id": str(database.warehouse),
                "item_id": str(database.cabinet),
                "number": 1,
            }
        }
    )


def test_migration_275_follows_the_products() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    migration = scripts.get_revision(REVISION)
    assert migration is not None
    assert migration.down_revision == "20270424_274"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


def test_the_default_roles_get_the_quotation_rights(
    quotation_database: QuotationDatabase,
) -> None:
    def grants(actor: uuid.UUID) -> set[str]:
        with psycopg.connect(quotation_database.owner_url) as connection:
            return {str(row[0]) for row in connection.execute(GRANTS, (actor,)).fetchall()}

    assert RIGHTS <= grants(quotation_database.owner)
    assert RIGHTS <= grants(quotation_database.manager)
    assert grants(quotation_database.staff) & RIGHTS == {"quotations.read"}
    with psycopg.connect(quotation_database.owner_url) as connection:
        assert connection.execute(
            "SELECT format FROM app.number_rules WHERE document_type = 'QUOTATION' LIMIT 1"
        ).fetchone() == ("QTyy000n",)


def test_a_quotation_keeps_its_prices_and_a_new_one_replaces_it(
    quotation_database: QuotationDatabase,
) -> None:
    database = quotation_database
    fan, cleaning = products(database)
    buy(database, fan, "1")
    # Staff see Quotations but do not make them; a price is never above the list price.
    rows = lines((fan, 2, 3000), (cleaning, 1, 1500))
    refused(
        database.runtime_url,
        "42501",
        MAKE,
        database.property_id,
        database.customer,
        None,
        None,
        None,
        rows,
        database.staff,
    )
    refused(
        database.runtime_url,
        "22023",
        MAKE,
        database.property_id,
        database.customer,
        None,
        None,
        None,
        lines((fan, 1, 3010)),
        database.manager,
    )
    first = run(
        database.runtime_url,
        MAKE,
        database.property_id,
        database.customer,
        "Fan and one cleaning",
        None,
        None,
        rows,
        database.manager,
    )
    made = read(database, first)
    assert made["quotation_number"].startswith("QT")
    assert made["state"] == "WAITING" and made["total_usd_cents"] == 7500
    assert date.fromisoformat(made["valid_until"]) - date.fromisoformat(made["made_on"]) == (
        timedelta(days=7)
    )
    assert [line["list_price_usd_cents"] for line in made["lines"]] == [3000, 1500]
    # A lower price needs a reason; the new Quotation replaces the old one.
    lower = lines((fan, 2, 3000), (cleaning, 1, 1200))
    refused(
        database.runtime_url,
        "22023",
        MAKE,
        database.property_id,
        database.customer,
        None,
        first,
        None,
        lower,
        database.manager,
    )
    second = run(
        database.runtime_url,
        MAKE,
        database.property_id,
        database.customer,
        None,
        first,
        "Long-time tenant",
        lower,
        database.manager,
    )
    old, new = read(database, first), read(database, second)
    assert old["state"] == "REPLACED" and old["replaced_by_number"] == new["quotation_number"]
    assert new["replaces_number"] == old["quotation_number"]
    assert new["total_usd_cents"] == 7200 and new["lowered_reason"] == "Long-time tenant"
    assert new["lines"][1]["list_price_usd_cents"] == 1500
    assert new["lines"][1]["price_usd_cents"] == 1200
    refused(
        database.runtime_url,
        "55000",
        MAKE,
        database.property_id,
        database.customer,
        None,
        first,
        None,
        rows,
        database.manager,
    )
    # A Quotation is never changed or removed.
    with psycopg.connect(database.owner_url) as connection, pytest.raises(psycopg.Error) as caught:
        connection.execute(
            "UPDATE app.quotation_lines SET price_usd_cents = 1 WHERE quotation_id = %s",
            (second,),
        )
    assert caught.value.sqlstate == "55000"
    with psycopg.connect(database.owner_url) as connection, pytest.raises(psycopg.Error) as caught:
        connection.execute("DELETE FROM app.quotations WHERE id = %s", (second,))
    assert caught.value.sqlstate == "55000"
    # The Customer refused: a reason is needed.
    refused(
        database.runtime_url,
        "22023",
        REFUSE,
        database.property_id,
        second,
        1,
        " ",
        database.manager,
    )
    assert (
        run(
            database.runtime_url,
            REFUSE,
            database.property_id,
            second,
            1,
            "Too dear",
            database.manager,
        )
        == 2
    )
    assert read(database, second)["state"] == "REFUSED"


def test_customer_signed_issues_the_invoice_and_a_void_puts_the_items_back(
    quotation_database: QuotationDatabase,
) -> None:
    database = quotation_database
    fan, cleaning = products(database)
    buy(database, fan, "1")
    quotation = run(
        database.runtime_url,
        MAKE,
        database.property_id,
        database.customer,
        None,
        None,
        None,
        lines((fan, 2, 3000), (cleaning, 1, 1500)),
        database.manager,
    )
    today = date.fromisoformat(read(database, quotation)["made_on"])
    # Only 1 is in stock: the Quotation waits, and nothing is recorded.
    refused(
        database.financial_url,
        "55000",
        SIGN,
        database.property_id,
        quotation,
        1,
        today,
        take(database),
        database.manager,
    )
    waiting = read(database, quotation)
    assert waiting["state"] == "WAITING" and waiting["invoice_id"] is None
    buy(database, fan, "2")
    # Staff without "Make Quotations" cannot record the signature; the day is not in the future.
    refused(
        database.financial_url,
        "42501",
        SIGN,
        database.property_id,
        quotation,
        1,
        today,
        take(database),
        database.staff,
    )
    refused(
        database.financial_url,
        "22023",
        SIGN,
        database.property_id,
        quotation,
        1,
        today + timedelta(days=1),
        take(database),
        database.manager,
    )
    signed = run(
        database.financial_url,
        SIGN,
        database.property_id,
        quotation,
        1,
        today,
        take(database),
        database.manager,
    )
    assert signed["state"] == "SIGNED" and signed["invoice_status"] == "UNPAID"
    assert signed["invoice_number"].startswith("INV")
    assert signed["lines"][0]["taken_from"]["movement_number"].startswith("SM")
    assert signed["lines"][1]["taken_from"] is None
    assert stock(database, fan) == 1
    with psycopg.connect(database.owner_url) as connection:
        invoice = connection.execute(
            "SELECT invoice.status, invoice.original_total_usd_cents, invoice.due_date, "
            "invoice.invoice_date + app.one_time_charge_due_days(%s, invoice.invoice_date), "
            "(SELECT count(*) FROM app.invoice_lines AS line WHERE line.invoice_id = invoice.id), "
            "invoice.version FROM app.invoices AS invoice WHERE invoice.id = %s",
            (database.property_id, signed["invoice_id"]),
        ).fetchone()
        assert invoice is not None
        assert invoice[:2] == ("UNPAID", 7500)
        assert invoice[2] == invoice[3] and invoice[4] == 2
        kinds = connection.execute(
            "SELECT DISTINCT kind FROM app.report_income_facts(%s, %s, ARRAY[%s]::uuid[])",
            (database.owner, database.property_id, database.property_id),
        ).fetchall()
        assert ("PRODUCT_CHARGES",) in kinds
        version = int(invoice[5])
    # Signed once only.
    refused(
        database.financial_url,
        "55000",
        SIGN,
        database.property_id,
        quotation,
        2,
        today,
        take(database),
        database.manager,
    )
    # A voided Invoice puts the Items back where they were taken from.
    run(
        database.financial_url,
        "SELECT app.void_invoice(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        database.property_id,
        signed["invoice_id"],
        database.owner,
        uuid.uuid4(),
        "a" * 64,
        version,
        "Customer changed their mind",
        uuid.uuid4(),
        uuid.uuid4(),
    )
    assert stock(database, fan) == 3
    after = read(database, quotation)
    assert after["state"] == "SIGNED" and after["invoice_status"] == "VOID"
    with psycopg.connect(database.owner_url) as connection:
        assert connection.execute(
            "SELECT kind, quantity FROM app.product_transactions WHERE quotation_id = %s "
            "ORDER BY recorded_at, kind",
            (quotation,),
        ).fetchall() == [("SALE", 2), ("SALE_RETURN", 2)]


def test_the_regular_services_became_service_products(
    quotation_database: QuotationDatabase,
) -> None:
    with psycopg.connect(quotation_database.owner_url) as connection:
        missing = connection.execute(
            "SELECT count(*) FROM app.regular_services AS service WHERE service.removed_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM app.products AS product "
            "JOIN app.product_categories AS category ON category.id = product.category_id "
            "WHERE lower(product.name_en) = lower(service.name_en))"
        ).fetchone()
    assert missing == (0,)


def test_the_quotation_flow_reads_and_writes_through_the_functions(
    quotation_database: QuotationDatabase,
) -> None:
    from property_rental.products_api import ProductConflict, ProductStale
    from property_rental.quotations_api import PostgresQuotationFlow

    database = quotation_database
    flow = PostgresQuotationFlow(database.runtime_url, database.financial_url)
    fan, cleaning = products(database)
    buy(database, fan, "1")
    made = flow.make(
        database.property_id,
        {
            "customer_id": database.customer,
            "lease_id": None,
            "note": "Fan for the bedroom",
            "replaces_id": None,
            "lowered_reason": None,
            "lines": [
                {"product_id": str(fan), "quantity": 2, "price_usd_cents": 3000},
                {"product_id": str(cleaning), "quantity": 1, "price_usd_cents": 1500},
            ],
        },
        actor_id=str(database.manager),
    )
    found = flow.quotation(database.property_id, made, actor_id=str(database.staff))
    assert found["state"] == "WAITING" and found["total_usd_cents"] == 7500
    assert any(
        item["quotation_id"] == str(made)
        for item in flow.quotations(database.property_id, actor_id=str(database.staff))
    )
    signature = {
        "signed_on": date.fromisoformat(str(found["made_on"])),
        "takes": [
            {
                "position": 1,
                "unit_id": database.warehouse,
                "item_id": database.cabinet,
                "number": 1,
            }
        ],
    }
    with pytest.raises(ProductStale):
        flow.sign(database.property_id, made, 9, signature, actor_id=str(database.manager))
    # 1 in stock for 2 quoted: the Quotation waits.
    with pytest.raises(ProductConflict):
        flow.sign(database.property_id, made, 1, signature, actor_id=str(database.manager))
    buy(database, fan, "1")
    signed = flow.sign(database.property_id, made, 1, signature, actor_id=str(database.manager))
    assert signed["state"] == "SIGNED" and str(signed["invoice_number"]).startswith("INV")
    other = flow.make(
        database.property_id,
        {
            "customer_id": database.customer,
            "lease_id": None,
            "note": None,
            "replaces_id": None,
            "lowered_reason": None,
            "lines": [{"product_id": str(cleaning), "quantity": 2, "price_usd_cents": 1500}],
        },
        actor_id=str(database.manager),
    )
    flow.refuse(database.property_id, other, 1, "Too dear", actor_id=str(database.manager))
    refused_one = flow.quotation(database.property_id, other, actor_id=str(database.staff))
    assert refused_one["state"] == "REFUSED" and refused_one["refused_reason"] == "Too dear"
