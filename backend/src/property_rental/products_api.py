"""Building > Products: products, prices, stock movements and Locations (V1.1 part 4, DL-121).

`GET /api/v1/properties/{property_id}/products` lists the products with their stock, the
categories and the price rules (`products.read`). `POST .../products` adds one and
`PUT .../products/{product_id}` changes it at the version in If-Match (`products.manage`).
`PUT .../products/{product_id}/mark-ups` changes the mark-up, minimum and maximum
(`products.prices`, the Owner by default). `PUT .../products/{product_id}/service-cost` types a
Service's cost (`products.manage`). `GET .../products/{product_id}/prices` is the price history.

`GET .../stock-movements` lists the latest movements and `POST .../stock-movements` records a
Purchase (`stock.purchase`), a Transfer (`stock.transfer`) or an Adjustment (`stock.adjust`).
`POST .../stock-movements/batch` records up to 20 of them together, all or none, for the Unit
inventory form (V1.1 part 5, DL-122); it needs the right of every kind in it.
`GET .../locations` lists each place (a Unit plus one of its Unit features) with its stock, and
`POST .../units/{unit_id}/places` adds a place to a Unit (`products.manage`).

The database functions check the rights again, write the rows and the History, and keep stock
from going below 0; the program never writes the tables itself.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

PRODUCTS_READ = "products.read"
PRODUCTS_MANAGE = "products.manage"
PRODUCTS_PRICES = "products.prices"
STOCK_RIGHT = {
    "PURCHASE": "stock.purchase",
    "TRANSFER": "stock.transfer",
    "ADJUSTMENT_IN": "stock.adjust",
    "ADJUSTMENT_OUT": "stock.adjust",
}
QUANTITY = re.compile(r"^[0-9]{1,9}(\.[0-9]{1,3})?$")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Code = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z_]{1,40}$")]
BasisPoints = Annotated[int, Field(ge=0, le=100000)]
Cents = Annotated[int, Field(gt=0, le=100_000_000)]
Count = Annotated[int, Field(ge=0, le=1_000_000)]
Json = dict[str, object]
Id = Annotated[UUID, Field(strict=False)]


class ProductNotFound(LookupError):
    """The Property, product, Unit or place is not there."""


class ProductRefused(ValueError):
    """The change is refused (a field, a rule or the stock)."""


class ProductConflict(RuntimeError):
    """The name is taken, the stock is short or the product is discontinued."""


class ProductStale(RuntimeError):
    """The product changed since it was read."""


class ProductForbidden(PermissionError):
    """The database says this account may not do this."""


class ProductUnavailable(RuntimeError):
    """Persistence is unavailable."""


class ProductFlow(Protocol):
    def catalogue(self, property_id: UUID) -> Json: ...

    def create(self, property_id: UUID, change: Json, *, actor_id: str) -> UUID: ...

    def change(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None: ...

    def set_mark_ups(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None: ...

    def set_service_cost(
        self, property_id: UUID, product_id: UUID, version: int, cost: int, *, actor_id: str
    ) -> None: ...

    def prices(self, property_id: UUID, product_id: UUID) -> list[Json]: ...

    def movements(self, property_id: UUID, product_id: UUID | None) -> list[Json]: ...

    def record_movement(self, property_id: UUID, movement: Json, *, actor_id: str) -> str: ...

    def record_movements(
        self, property_id: UUID, movements: list[Json], *, actor_id: str
    ) -> list[str]: ...

    def locations(self, property_id: UUID) -> Json: ...

    def add_place(
        self, property_id: UUID, unit_id: UUID, item_id: UUID, *, actor_id: str
    ) -> int: ...


class UnavailableProductFlow:
    def catalogue(self, property_id: UUID) -> Json:
        raise ProductUnavailable

    def create(self, property_id: UUID, change: Json, **_: object) -> UUID:
        raise ProductUnavailable

    def change(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, **_: object
    ) -> None:
        raise ProductUnavailable

    def set_mark_ups(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, **_: object
    ) -> None:
        raise ProductUnavailable

    def set_service_cost(
        self, property_id: UUID, product_id: UUID, version: int, cost: int, **_: object
    ) -> None:
        raise ProductUnavailable

    def prices(self, property_id: UUID, product_id: UUID) -> list[Json]:
        raise ProductUnavailable

    def movements(self, property_id: UUID, product_id: UUID | None) -> list[Json]:
        raise ProductUnavailable

    def record_movement(self, property_id: UUID, movement: Json, **_: object) -> str:
        raise ProductUnavailable

    def record_movements(self, property_id: UUID, movements: list[Json], **_: object) -> list[str]:
        raise ProductUnavailable

    def locations(self, property_id: UUID) -> Json:
        raise ProductUnavailable

    def add_place(self, property_id: UUID, unit_id: UUID, item_id: UUID, **_: object) -> int:
        raise ProductUnavailable


def _refusal(exc: psycopg.Error) -> Exception:
    message = str(exc).splitlines()[0] if str(exc) else ""
    state = exc.sqlstate or ""
    if state == "42501":
        return ProductForbidden(message)
    if state == "40001":
        return ProductStale(message)
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return ProductConflict("Another product already has this name")
    if state == "55000":
        return ProductConflict(message)
    if state == "22023" and ("does not exist" in message or "No product category" in message):
        return ProductNotFound(message)
    if state in {"22023", "23514", "22003", "23502"}:
        return ProductRefused(message)
    return ProductUnavailable("Product persistence is unavailable")


def _money(value: object) -> int | None:
    return None if value is None else int(str(value))


def _iso(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _quantity(value: object) -> str:
    return format(Decimal(str(value)).normalize(), "f")


MOVE = (
    "SELECT app.record_stock_movement(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s)"
)
# Stock that comes in; a Sale returned by a voided Invoice too (V1.1 part 6, DL-123).
IN_KINDS = "'PURCHASE', 'ADJUSTMENT_IN', 'TRANSFER_IN', 'SALE_RETURN'"
PRODUCT_COLUMNS = f"""
    product.id, product.sku, product.name_en, product.name_kh, product.description,
    category.code, category.kind, product.measure_unit, product.cost_usd_cents,
    product.mark_up_basis_points, product.min_mark_up_basis_points,
    product.max_mark_up_basis_points, product.price_usd_cents, product.reorder_level,
    product.reorder_quantity, product.discontinued, product.version, product.updated_at,
    COALESCE((SELECT sum(CASE WHEN movement.kind IN ({IN_KINDS})
                              THEN movement.quantity ELSE -movement.quantity END)
              FROM app.product_transactions AS movement
              WHERE movement.product_id = product.id), 0)
"""


def _product(row: tuple[object, ...]) -> Json:
    (
        product_id,
        sku,
        name_en,
        name_kh,
        description,
        category,
        kind,
        measure_unit,
        cost,
        mark_up,
        minimum,
        maximum,
        price,
        reorder_level,
        reorder_quantity,
        discontinued,
        version,
        updated_at,
        stock,
    ) = row
    cost_cents = _money(cost)
    price_cents = _money(price)
    real = (
        None
        if cost_cents is None or price_cents is None
        else (price_cents - cost_cents) * 10000 // cost_cents
    )
    stock_text = _quantity(stock)
    return {
        "product_id": str(product_id),
        "sku": str(sku),
        "name_en": str(name_en),
        "name_kh": None if name_kh is None else str(name_kh),
        "description": None if description is None else str(description),
        "category_code": str(category),
        "kind": str(kind),
        "measure_unit": str(measure_unit),
        "cost_usd_cents": cost_cents,
        "mark_up_basis_points": int(str(mark_up)),
        "min_mark_up_basis_points": int(str(minimum)),
        "max_mark_up_basis_points": None if maximum is None else int(str(maximum)),
        "price_usd_cents": price_cents,
        "real_mark_up_basis_points": real,
        "reorder_level": None if reorder_level is None else int(str(reorder_level)),
        "reorder_quantity": None if reorder_quantity is None else int(str(reorder_quantity)),
        "discontinued": bool(discontinued),
        "version": int(str(version)),
        "updated_at": _iso(updated_at),
        "stock": stock_text,
        "low_stock": reorder_level is not None
        and Decimal(stock_text) <= Decimal(str(reorder_level)),
    }


class PostgresProductFlow:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._database_url)

    @staticmethod
    def _owned(
        connection: psycopg.Connection[tuple[object, ...]], property_id: UUID, product_id: UUID
    ) -> None:
        found = connection.execute(
            "SELECT 1 FROM app.products WHERE id = %s AND property_id = %s",
            (product_id, property_id),
        ).fetchone()
        if found is None:
            raise ProductNotFound("The product was not found")

    def _write(
        self,
        query: str,
        parameters: tuple[object, ...],
        owned: UUID | None = None,
        property_id: UUID | None = None,
    ) -> object:
        try:
            with self._connect() as connection:
                if owned is not None and property_id is not None:
                    self._owned(connection, property_id, owned)
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def catalogue(self, property_id: UUID) -> Json:
        try:
            with self._connect() as connection:
                day = connection.execute(
                    "SELECT timezone(timezone_name, statement_timestamp())::date "
                    "FROM app.properties WHERE id = %s",
                    (property_id,),
                ).fetchone()
                if day is None:
                    raise ProductNotFound("The Property was not found")
                rules = connection.execute(
                    "SELECT app.product_rule('PRODUCT_MARK_UP', %(d)s), "
                    "app.product_rule('PRODUCT_MIN_MARK_UP', %(d)s), "
                    "app.product_rule('PRODUCT_MAX_MARK_UP', %(d)s), "
                    "app.product_rule('PRICE_ROUND_UP', %(d)s)",
                    {"d": day[0]},
                ).fetchone()
                categories = connection.execute(
                    "SELECT code, name_en, name_kh, kind FROM app.product_categories "
                    "ORDER BY sort_order, code"
                ).fetchall()
                products = connection.execute(
                    f"SELECT {PRODUCT_COLUMNS} FROM app.products AS product "
                    "JOIN app.product_categories AS category ON category.id = product.category_id "
                    "WHERE product.property_id = %s ORDER BY product.sku",
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise ProductUnavailable from exc
        assert rules is not None
        mark_up, minimum, maximum, step = rules
        return {
            "rules": {
                "mark_up_basis_points": _money(mark_up),
                "min_mark_up_basis_points": _money(minimum),
                "max_mark_up_basis_points": _money(maximum),
                "price_round_up_usd_cents": _money(step),
            },
            "categories": [
                {
                    "code": str(code),
                    "name_en": str(name_en),
                    "name_kh": None if name_kh is None else str(name_kh),
                    "kind": str(kind),
                }
                for code, name_en, name_kh, kind in categories
            ],
            "products": [_product(row) for row in products],
        }

    def create(self, property_id: UUID, change: Json, *, actor_id: str) -> UUID:
        created = self._write(
            "SELECT app.create_product(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                property_id,
                change["name_en"],
                change.get("name_kh"),
                change.get("description"),
                change["category_code"],
                change["measure_unit"],
                change.get("reorder_level"),
                change.get("reorder_quantity"),
                change.get("service_cost_usd_cents"),
                UUID(actor_id),
                uuid4(),
            ),
        )
        return UUID(str(created))

    def change(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None:
        self._write(
            "SELECT app.change_product(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                product_id,
                version,
                change["name_en"],
                change.get("name_kh"),
                change.get("description"),
                change["category_code"],
                change["measure_unit"],
                change.get("reorder_level"),
                change.get("reorder_quantity"),
                change["discontinued"],
                UUID(actor_id),
                uuid4(),
            ),
            owned=product_id,
            property_id=property_id,
        )

    def set_mark_ups(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None:
        self._write(
            "SELECT app.set_product_mark_ups(%s, %s, %s, %s, %s, %s, %s)",
            (
                product_id,
                version,
                change["mark_up_basis_points"],
                change["min_mark_up_basis_points"],
                change.get("max_mark_up_basis_points"),
                UUID(actor_id),
                uuid4(),
            ),
            owned=product_id,
            property_id=property_id,
        )

    def set_service_cost(
        self, property_id: UUID, product_id: UUID, version: int, cost: int, *, actor_id: str
    ) -> None:
        self._write(
            "SELECT app.set_service_cost(%s, %s, %s, %s, %s)",
            (product_id, version, cost, UUID(actor_id), uuid4()),
            owned=product_id,
            property_id=property_id,
        )

    def prices(self, property_id: UUID, product_id: UUID) -> list[Json]:
        try:
            with self._connect() as connection:
                self._owned(connection, property_id, product_id)
                rows = connection.execute(
                    "SELECT history.price_usd_cents, history.cost_usd_cents, "
                    "history.mark_up_basis_points, history.cause, history.created_at, "
                    "account.display_name FROM app.product_price_history AS history "
                    "LEFT JOIN app.user_accounts AS account "
                    "ON account.actor_id = history.created_by "
                    "WHERE history.product_id = %s ORDER BY history.created_at DESC, history.id",
                    (product_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise ProductUnavailable from exc
        return [
            {
                "price_usd_cents": _money(price),
                "cost_usd_cents": _money(cost),
                "mark_up_basis_points": int(str(mark_up)),
                "cause": str(cause),
                "created_at": _iso(created_at),
                "created_by_name": None if by is None else str(by),
            }
            for price, cost, mark_up, cause, created_at, by in rows
        ]

    def movements(self, property_id: UUID, product_id: UUID | None) -> list[Json]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT movement.movement_number, movement.kind, product.id, product.sku,
                        product.name_en, product.measure_unit, movement.quantity, unit.id,
                        unit.unit_number, item.id, item.name_en, item.name_km,
                        movement.place_number, movement.unit_cost_usd_cents, movement.supplier,
                        movement.receipt_reference, movement.reason, movement.business_date,
                        movement.recorded_at, account.display_name
                    FROM app.product_transactions AS movement
                    JOIN app.products AS product ON product.id = movement.product_id
                    JOIN app.units AS unit ON unit.id = movement.unit_id
                    JOIN app.unit_setup_items AS item ON item.id = movement.place_item_id
                    LEFT JOIN app.user_accounts AS account
                        ON account.actor_id = movement.recorded_by
                    WHERE product.property_id = %s AND (%s::uuid IS NULL OR product.id = %s)
                    ORDER BY movement.recorded_at DESC, movement.movement_number DESC,
                        movement.kind
                    LIMIT 300
                    """,
                    (property_id, product_id, product_id),
                ).fetchall()
        except psycopg.Error as exc:
            raise ProductUnavailable from exc
        return [
            {
                "movement_number": str(number),
                "kind": str(kind),
                "product_id": str(product),
                "sku": str(sku),
                "product_name_en": str(product_name),
                "measure_unit": str(measure_unit),
                "quantity": _quantity(quantity),
                "unit_id": str(unit),
                "unit_number": str(unit_number),
                "place_item_id": str(item),
                "place_name_en": str(item_en),
                "place_name_kh": None if item_kh is None else str(item_kh),
                "place_number": int(str(place_number)),
                "unit_cost_usd_cents": _money(cost),
                "supplier": None if supplier is None else str(supplier),
                "receipt_reference": None if receipt is None else str(receipt),
                "reason": None if reason is None else str(reason),
                "business_date": _iso(day),
                "recorded_at": _iso(recorded_at),
                "recorded_by_name": None if by is None else str(by),
            }
            for (
                number,
                kind,
                product,
                sku,
                product_name,
                measure_unit,
                quantity,
                unit,
                unit_number,
                item,
                item_en,
                item_kh,
                place_number,
                cost,
                supplier,
                receipt,
                reason,
                day,
                recorded_at,
                by,
            ) in rows
        ]

    @staticmethod
    def _movement_parameters(
        property_id: UUID, movement: Json, actor_id: str
    ) -> tuple[object, ...]:
        source = movement.get("from")
        target = movement.get("to")
        place_from = source if isinstance(source, dict) else {}
        place_to = target if isinstance(target, dict) else {}
        return (
            property_id,
            movement["kind"],
            movement["product_id"],
            Decimal(str(movement["quantity"])),
            place_from.get("unit_id"),
            place_from.get("item_id"),
            place_from.get("number"),
            place_to.get("unit_id"),
            place_to.get("item_id"),
            place_to.get("number"),
            movement.get("unit_cost_usd_cents"),
            movement.get("supplier"),
            movement.get("receipt_reference"),
            movement.get("reason"),
            UUID(actor_id),
            uuid4(),
        )

    def record_movement(self, property_id: UUID, movement: Json, *, actor_id: str) -> str:
        return self.record_movements(property_id, [movement], actor_id=actor_id)[0]

    def record_movements(
        self, property_id: UUID, movements: list[Json], *, actor_id: str
    ) -> list[str]:
        """Every movement or none (V1.1 part 5: the Unit inventory form saves its rows at once)."""
        numbers: list[str] = []
        try:
            with self._connect() as connection:
                for movement in movements:
                    row = connection.execute(
                        MOVE, self._movement_parameters(property_id, movement, actor_id)
                    ).fetchone()
                    assert row is not None
                    numbers.append(str(row[0]))
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return numbers

    def locations(self, property_id: UUID) -> Json:
        try:
            with self._connect() as connection:
                places = connection.execute(
                    """
                    SELECT unit.id, unit.unit_number, unit.for_rent, item.id, item.name_en,
                        item.name_km, place.number
                    FROM app.units AS unit
                    JOIN app.unit_features AS feature ON feature.unit_id = unit.id
                    JOIN app.unit_setup_items AS item ON item.id = feature.item_id
                    CROSS JOIN LATERAL generate_series(1, feature.feature_count) AS place(number)
                    WHERE unit.property_id = %s
                    ORDER BY unit.for_rent, unit.unit_number, item.sort_order, item.name_en,
                        place.number
                    """,
                    (property_id,),
                ).fetchall()
                stock = connection.execute(
                    f"""
                    SELECT movement.unit_id, movement.place_item_id, movement.place_number,
                        product.id, product.sku, product.name_en, product.measure_unit,
                        sum(CASE WHEN movement.kind IN ({IN_KINDS})
                                 THEN movement.quantity ELSE -movement.quantity END)
                    FROM app.product_transactions AS movement
                    JOIN app.products AS product ON product.id = movement.product_id
                    WHERE product.property_id = %s
                    GROUP BY movement.unit_id, movement.place_item_id, movement.place_number,
                        product.id, product.sku, product.name_en, product.measure_unit
                    HAVING sum(CASE WHEN movement.kind IN ({IN_KINDS})
                                    THEN movement.quantity ELSE -movement.quantity END) <> 0
                    ORDER BY product.sku
                    """,
                    (property_id,),
                ).fetchall()
                features = connection.execute(
                    "SELECT id, name_en, name_km FROM app.unit_setup_items "
                    "WHERE property_id = %s AND list_kind = 'UNIT_FEATURE' AND removed_at IS NULL "
                    "ORDER BY sort_order, name_en",
                    (property_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise ProductUnavailable from exc
        held: dict[tuple[str, str, int], list[Json]] = {}
        for unit, item, number, product, sku, name, measure_unit, quantity in stock:
            held.setdefault((str(unit), str(item), int(str(number))), []).append(
                {
                    "product_id": str(product),
                    "sku": str(sku),
                    "name_en": str(name),
                    "measure_unit": str(measure_unit),
                    "quantity": _quantity(quantity),
                }
            )
        return {
            "places": [
                {
                    "unit_id": str(unit),
                    "unit_number": str(unit_number),
                    "for_rent": bool(for_rent),
                    "item_id": str(item),
                    "name_en": str(name_en),
                    "name_kh": None if name_kh is None else str(name_kh),
                    "number": int(str(number)),
                    "stock": held.get((str(unit), str(item), int(str(number))), []),
                }
                for unit, unit_number, for_rent, item, name_en, name_kh, number in places
            ],
            "features": [
                {
                    "item_id": str(item),
                    "name_en": str(name_en),
                    "name_kh": None if name_kh is None else str(name_kh),
                }
                for item, name_en, name_kh in features
            ],
        }

    def add_place(self, property_id: UUID, unit_id: UUID, item_id: UUID, *, actor_id: str) -> int:
        try:
            with self._connect() as connection:
                found = connection.execute(
                    "SELECT 1 FROM app.units WHERE id = %s AND property_id = %s",
                    (unit_id, property_id),
                ).fetchone()
                if found is None:
                    raise ProductNotFound("The Unit was not found")
                row = connection.execute(
                    "SELECT app.add_unit_place(%s, %s, %s, %s)",
                    (unit_id, item_id, UUID(actor_id), uuid4()),
                ).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        assert row is not None
        return int(str(row[0]))


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProductFields(_Body):
    name_en: Name
    name_kh: Name | None = None
    description: Text | None = None
    category_code: Code
    measure_unit: Code
    reorder_level: Count | None = None
    reorder_quantity: Annotated[int, Field(gt=0, le=1_000_000)] | None = None


class NewProduct(ProductFields):
    service_cost_usd_cents: Cents | None = None


class ProductChange(ProductFields):
    discontinued: bool


class MarkUpChange(_Body):
    mark_up_basis_points: BasisPoints
    min_mark_up_basis_points: BasisPoints
    max_mark_up_basis_points: BasisPoints | None = None


class ServiceCostChange(_Body):
    cost_usd_cents: Cents


class Place(_Body):
    unit_id: Id
    item_id: Id
    number: Annotated[int, Field(ge=1, le=9)]


class StockMovement(_Body):
    kind: Literal["PURCHASE", "TRANSFER", "ADJUSTMENT_IN", "ADJUSTMENT_OUT"]
    product_id: Id
    quantity: Annotated[str, StringConstraints(pattern=QUANTITY.pattern)]
    from_place: Place | None = Field(default=None, alias="from")
    to_place: Place | None = Field(default=None, alias="to")
    unit_cost_usd_cents: Cents | None = None
    supplier: Short | None = None
    receipt_reference: Reference | None = None
    reason: Text | None = None


class StockMovements(_Body):
    movements: Annotated[list[StockMovement], Field(min_length=1, max_length=20)]


class NewPlace(_Body):
    item_id: Id


def _require(
    request: Request, resolver: ActorResolver, capability: str, property_id: UUID
) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return actor


def _expected_version(request: Request) -> int:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED)
    normalized = raw.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    if not normalized.isascii() or not normalized.isdigit() or int(normalized) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    return int(normalized)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, ProductNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or None)
    if isinstance(exc, ProductForbidden):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, ProductStale):
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="The product changed since it was read. Reload it.",
        )
    if isinstance(exc, ProductConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ProductRefused):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


REFUSED = (
    ProductNotFound,
    ProductRefused,
    ProductConflict,
    ProductStale,
    ProductForbidden,
    ProductUnavailable,
)


def create_products_router(
    resolver: ActorResolver, flow: ProductFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["products"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def catalogue(property_id: UUID, request: Request) -> Json:
        try:
            return envelope(request, flow.catalogue(property_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/products")
    def list_products(property_id: UUID, request: Request, response: Response) -> Json:
        _require(request, resolver, PRODUCTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return catalogue(property_id, request)

    @router.post("/products", status_code=status.HTTP_201_CREATED)
    def add_product(property_id: UUID, change: NewProduct, request: Request) -> Json:
        actor = _require(request, resolver, PRODUCTS_MANAGE, property_id)
        require_browser_mutation(request, settings)
        try:
            flow.create(property_id, change.model_dump(), actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return catalogue(property_id, request)

    @router.put("/products/{product_id}")
    def change_product(
        property_id: UUID, product_id: UUID, change: ProductChange, request: Request
    ) -> Json:
        actor = _require(request, resolver, PRODUCTS_MANAGE, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.change(
                property_id, product_id, version, change.model_dump(), actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return catalogue(property_id, request)

    @router.put("/products/{product_id}/mark-ups")
    def change_mark_ups(
        property_id: UUID, product_id: UUID, change: MarkUpChange, request: Request
    ) -> Json:
        actor = _require(request, resolver, PRODUCTS_PRICES, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.set_mark_ups(
                property_id, product_id, version, change.model_dump(), actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return catalogue(property_id, request)

    @router.put("/products/{product_id}/service-cost")
    def change_service_cost(
        property_id: UUID, product_id: UUID, change: ServiceCostChange, request: Request
    ) -> Json:
        actor = _require(request, resolver, PRODUCTS_MANAGE, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.set_service_cost(
                property_id, product_id, version, change.cost_usd_cents, actor_id=actor.actor_id
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return catalogue(property_id, request)

    @router.get("/products/{product_id}/prices")
    def list_prices(
        property_id: UUID, product_id: UUID, request: Request, response: Response
    ) -> Json:
        _require(request, resolver, PRODUCTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.prices(property_id, product_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/stock-movements")
    def list_movements(
        property_id: UUID,
        request: Request,
        response: Response,
        product_id: UUID | None = None,
    ) -> Json:
        _require(request, resolver, PRODUCTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.movements(property_id, product_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/stock-movements", status_code=status.HTTP_201_CREATED)
    def record_movement(property_id: UUID, movement: StockMovement, request: Request) -> Json:
        actor = _require(request, resolver, STOCK_RIGHT[movement.kind], property_id)
        require_browser_mutation(request, settings)
        body: Json = movement.model_dump(by_alias=True)
        try:
            number = flow.record_movement(property_id, body, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return envelope(request, {"movement_number": number})

    @router.post("/stock-movements/batch", status_code=status.HTTP_201_CREATED)
    def record_movements(property_id: UUID, batch: StockMovements, request: Request) -> Json:
        """V1.1 part 5: the rows of the Unit inventory form, saved together or not at all."""
        actor = None
        for capability in sorted({STOCK_RIGHT[movement.kind] for movement in batch.movements}):
            actor = _require(request, resolver, capability, property_id)
        assert actor is not None
        require_browser_mutation(request, settings)
        bodies: list[Json] = [movement.model_dump(by_alias=True) for movement in batch.movements]
        try:
            numbers = flow.record_movements(property_id, bodies, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return envelope(request, {"movement_numbers": numbers})

    @router.get("/locations")
    def list_locations(property_id: UUID, request: Request, response: Response) -> Json:
        _require(request, resolver, PRODUCTS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.locations(property_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.post("/units/{unit_id}/places", status_code=status.HTTP_201_CREATED)
    def add_place(property_id: UUID, unit_id: UUID, place: NewPlace, request: Request) -> Json:
        actor = _require(request, resolver, PRODUCTS_MANAGE, property_id)
        require_browser_mutation(request, settings)
        try:
            number = flow.add_place(property_id, unit_id, place.item_id, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return envelope(request, {"number": number})

    return router
