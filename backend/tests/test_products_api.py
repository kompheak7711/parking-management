"""Building > Products API (V1.1 part 4, DL-121, API-PS-001).

Reading needs `products.read`; adding and changing a product needs `products.manage`; mark-ups
need `products.prices`; a Purchase needs `stock.purchase`, a Transfer `stock.transfer` and an
Adjustment `stock.adjust`. Each change needs the browser mutation checks, and a product change
needs If-Match. The database refusals map to 403, 404, 409, 412 and 422.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from property_rental.app import create_app
from property_rental.identity import AuthenticatedActor, CapabilityGrant
from property_rental.products_api import (
    Json,
    ProductConflict,
    ProductNotFound,
    ProductStale,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=products-token",
    "X-CSRF-Token": "products-token",
}


@dataclass
class InMemoryProducts:
    property_id: UUID = field(default_factory=uuid4)
    product_id: UUID = field(default_factory=uuid4)
    version: int = 1
    calls: list[tuple[str, object]] = field(default_factory=list)
    stock: int = 0

    def _check(self, property_id: UUID, product_id: UUID | None = None) -> None:
        if property_id != self.property_id or product_id not in (None, self.product_id):
            raise ProductNotFound("not found")

    def _versioned(self, property_id: UUID, product_id: UUID, version: int) -> None:
        self._check(property_id, product_id)
        if version != self.version:
            raise ProductStale
        self.version += 1

    def catalogue(self, property_id: UUID) -> Json:
        self._check(property_id)
        return {
            "rules": {"mark_up_basis_points": 2000},
            "categories": [],
            "products": [{"product_id": str(self.product_id), "version": self.version}],
        }

    def create(self, property_id: UUID, change: Json, *, actor_id: str) -> UUID:
        self._check(property_id)
        if change["name_en"] == "Kettle":
            raise ProductConflict("Another product already has this name")
        self.calls.append(("create", change))
        return uuid4()

    def change(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None:
        self._versioned(property_id, product_id, version)
        self.calls.append(("change", change))

    def set_mark_ups(
        self, property_id: UUID, product_id: UUID, version: int, change: Json, *, actor_id: str
    ) -> None:
        self._versioned(property_id, product_id, version)
        self.calls.append(("mark-ups", change))

    def set_service_cost(
        self, property_id: UUID, product_id: UUID, version: int, cost: int, *, actor_id: str
    ) -> None:
        self._versioned(property_id, product_id, version)
        self.calls.append(("cost", cost))

    def prices(self, property_id: UUID, product_id: UUID) -> list[Json]:
        self._check(property_id, product_id)
        return [{"price_usd_cents": 1200}]

    def movements(self, property_id: UUID, product_id: UUID | None) -> list[Json]:
        self._check(property_id)
        return [{"movement_number": "SM260001", "product_id": str(product_id)}]

    def record_movement(self, property_id: UUID, movement: Json, *, actor_id: str) -> str:
        self._check(property_id, UUID(str(movement["product_id"])))
        quantity = int(str(movement["quantity"]))
        if movement["kind"] in {"PURCHASE", "ADJUSTMENT_IN"}:
            self.stock += quantity
        elif quantity > self.stock:
            raise ProductConflict("There is not enough stock at this place")
        self.calls.append(("move", movement))
        return "SM260001"

    def locations(self, property_id: UUID) -> Json:
        self._check(property_id)
        return {"places": [], "features": []}

    def add_place(self, property_id: UUID, unit_id: UUID, item_id: UUID, *, actor_id: str) -> int:
        self._check(property_id)
        return 3


def client(flow: InMemoryProducts, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, product_flow=flow))


def base(flow: InMemoryProducts) -> str:
    return f"/api/v1/properties/{flow.property_id}"


NEW = {"name_en": "Fan", "category_code": "APPLIANCES", "measure_unit": "PIECE"}


def test_reading_products_stock_and_locations_needs_products_read() -> None:
    flow = InMemoryProducts()
    urls = (
        "/products",
        f"/products/{flow.product_id}/prices",
        "/stock-movements",
        f"/stock-movements?product_id={flow.product_id}",
        "/locations",
    )
    for url in urls:
        assert client(flow).get(base(flow) + url).status_code == 403
        answer = client(flow, "products.read").get(base(flow) + url)
        assert answer.status_code == 200, url
        assert answer.headers["Cache-Control"] == "private, no-store"
    other = f"/api/v1/properties/{uuid4()}/products"
    assert client(flow, "products.read").get(other).status_code == 403
    missing = f"{base(flow)}/products/{uuid4()}/prices"
    assert client(flow, "products.read").get(missing).status_code == 404


def test_adding_and_changing_a_product_needs_products_manage_and_if_match() -> None:
    flow = InMemoryProducts()
    url = base(flow) + "/products"
    assert client(flow, "products.read").post(url, json=NEW, headers=HEADERS).status_code == 403
    manager = client(flow, "products.read", "products.manage")
    assert manager.post(url, json=NEW).status_code == 403
    assert manager.post(url, json={**NEW, "price": 5}, headers=HEADERS).status_code == 422
    assert manager.post(url, json={**NEW, "name_en": " "}, headers=HEADERS).status_code == 422
    assert manager.post(url, json={**NEW, "name_en": "Kettle"}, headers=HEADERS).status_code == 409
    added = manager.post(url, json={**NEW, "name_en": " Fan "}, headers=HEADERS)
    assert added.status_code == 201 and added.json()["data"]["products"]
    assert flow.calls[-1][1]["name_en"] == "Fan"  # type: ignore[index]
    change = {**NEW, "discontinued": True}
    product = f"{url}/{flow.product_id}"
    assert manager.put(product, json=change, headers=HEADERS).status_code == 428
    stale = {**HEADERS, "If-Match": '"7"'}
    assert manager.put(product, json=change, headers=stale).status_code == 412
    fresh = {**HEADERS, "If-Match": '"1"'}
    assert manager.put(product, json=change, headers=fresh).status_code == 200
    assert flow.version == 2
    cost = {**HEADERS, "If-Match": "2"}
    answer = manager.put(f"{product}/service-cost", json={"cost_usd_cents": 333}, headers=cost)
    assert answer.status_code == 200 and flow.calls[-1] == ("cost", 333)


def test_mark_ups_need_products_prices() -> None:
    flow = InMemoryProducts()
    url = f"{base(flow)}/products/{flow.product_id}/mark-ups"
    body = {"mark_up_basis_points": 3000, "min_mark_up_basis_points": 1500}
    headers = {**HEADERS, "If-Match": "1"}
    manager = client(flow, "products.read", "products.manage")
    assert manager.put(url, json=body, headers=headers).status_code == 403
    owner = client(flow, "products.read", "products.prices")
    assert (
        owner.put(url, json={**body, "mark_up_basis_points": -1}, headers=headers).status_code
        == 422
    )
    assert owner.put(url, json=body, headers=headers).status_code == 200
    assert flow.calls[-1] == ("mark-ups", {**body, "max_mark_up_basis_points": None})


def test_each_kind_of_stock_movement_needs_its_own_right() -> None:
    flow = InMemoryProducts()
    url = base(flow) + "/stock-movements"
    place = {"unit_id": str(uuid4()), "item_id": str(uuid4()), "number": 1}
    other = {**place, "number": 2}
    purchase = {
        "kind": "PURCHASE",
        "product_id": str(flow.product_id),
        "quantity": "3",
        "to": place,
        "unit_cost_usd_cents": 1000,
    }
    transfer = {
        "kind": "TRANSFER",
        "product_id": str(flow.product_id),
        "quantity": "2",
        "from": place,
        "to": other,
    }
    adjust = {
        "kind": "ADJUSTMENT_OUT",
        "product_id": str(flow.product_id),
        "quantity": "1",
        "from": place,
        "reason": "Broken",
    }
    staff = client(flow, "products.read", "stock.purchase", "stock.transfer")
    assert staff.post(url, json=purchase).status_code == 403
    assert staff.post(url, json={**purchase, "quantity": "-1"}, headers=HEADERS).status_code == 422
    assert staff.post(url, json={**purchase, "kind": "SALE"}, headers=HEADERS).status_code == 422
    bought = staff.post(url, json=purchase, headers=HEADERS)
    assert bought.status_code == 201
    assert bought.json()["data"] == {"movement_number": "SM260001"}
    moved = flow.calls[-1][1]
    assert moved["to"]["number"] == 1 and moved["from"] is None  # type: ignore[index]
    assert staff.post(url, json=transfer, headers=HEADERS).status_code == 201
    assert staff.post(url, json={**transfer, "quantity": "9"}, headers=HEADERS).status_code == 409
    assert staff.post(url, json=adjust, headers=HEADERS).status_code == 403
    manager = client(flow, "products.read", "stock.adjust")
    assert manager.post(url, json=adjust, headers=HEADERS).status_code == 201
    assert manager.post(url, json=purchase, headers=HEADERS).status_code == 403


def test_adding_a_place_needs_products_manage() -> None:
    flow = InMemoryProducts()
    url = f"{base(flow)}/units/{uuid4()}/places"
    body = {"item_id": str(uuid4())}
    assert client(flow, "products.read").post(url, json=body, headers=HEADERS).status_code == 403
    manager = client(flow, "products.manage")
    answer = manager.post(url, json=body, headers=HEADERS)
    assert answer.status_code == 201 and answer.json()["data"] == {"number": 3}
