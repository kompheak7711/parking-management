"""Office > Invoices > Quotations API (V1.1 part 6, DL-123, API-QT-001).

Reading needs `quotations.read`; making, signing and refusing need `quotations.make`; each change
needs the browser mutation checks, and signing and refusing need If-Match. The database refusals
map to 403, 404, 409, 412 and 422.
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
    ProductForbidden,
    ProductNotFound,
    ProductStale,
)

HEADERS = {
    "Origin": "https://localhost",
    "Cookie": "__Host-prm_csrf=quotations-token",
    "X-CSRF-Token": "quotations-token",
}


@dataclass
class InMemoryQuotations:
    property_id: UUID = field(default_factory=uuid4)
    quotation_id: UUID = field(default_factory=uuid4)
    version: int = 1
    stock: int = 0
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _check(self, property_id: UUID, quotation_id: UUID | None = None) -> None:
        if property_id != self.property_id or quotation_id not in (None, self.quotation_id):
            raise ProductNotFound("the Quotation does not exist")

    def _quotation(self) -> Json:
        return {
            "quotation_id": str(self.quotation_id),
            "quotation_number": "QT260001",
            "state": "SIGNED" if self.version > 1 else "WAITING",
            "version": self.version,
        }

    def quotations(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        self._check(property_id)
        return [self._quotation()]

    def quotation(self, property_id: UUID, quotation_id: UUID, *, actor_id: str) -> Json:
        self._check(property_id, quotation_id)
        return self._quotation()

    def make(self, property_id: UUID, quotation: Json, *, actor_id: str) -> UUID:
        self._check(property_id)
        lines = quotation["lines"]
        assert isinstance(lines, list)
        if (
            any(line["price_usd_cents"] < 3000 for line in lines)
            and not quotation["lowered_reason"]
        ):
            raise ProductForbidden("this account may not do this")
        self.calls.append(("make", quotation))
        return self.quotation_id

    def sign(
        self, property_id: UUID, quotation_id: UUID, version: int, signature: Json, *, actor_id: str
    ) -> Json:
        self._check(property_id, quotation_id)
        if version != self.version:
            raise ProductStale
        if self.stock < 2:
            raise ProductConflict("An Item is not in stock at that place; the Quotation waits")
        self.version += 1
        self.calls.append(("sign", signature))
        return self._quotation()

    def refuse(
        self, property_id: UUID, quotation_id: UUID, version: int, reason: str, *, actor_id: str
    ) -> None:
        self._check(property_id, quotation_id)
        if version != self.version:
            raise ProductStale
        self.calls.append(("refuse", reason))


def client(flow: InMemoryQuotations, *capabilities: str) -> TestClient:
    who = AuthenticatedActor(
        actor_id=str(uuid4()),
        capability_grants=frozenset(
            CapabilityGrant(capability=name, property_ids=frozenset({str(flow.property_id)}))
            for name in capabilities
        ),
    )
    return TestClient(create_app(actor_resolver=lambda _: who, quotation_flow=flow))


def base(flow: InMemoryQuotations) -> str:
    return f"/api/v1/properties/{flow.property_id}/quotations"


def new(flow: InMemoryQuotations, price: int = 3000) -> Json:
    return {
        "customer_id": str(uuid4()),
        "note": " Fan for the bedroom ",
        "lines": [{"product_id": str(uuid4()), "quantity": 2, "price_usd_cents": price}],
    }


def test_reading_quotations_needs_quotations_read() -> None:
    flow = InMemoryQuotations()
    for url in (base(flow), f"{base(flow)}/{flow.quotation_id}"):
        assert client(flow).get(url).status_code == 403
        answer = client(flow, "quotations.read").get(url)
        assert answer.status_code == 200, url
        assert answer.headers["Cache-Control"] == "private, no-store"
    assert client(flow, "quotations.read").get(f"{base(flow)}/{uuid4()}").status_code == 404
    other = f"/api/v1/properties/{uuid4()}/quotations"
    assert client(flow, "quotations.read").get(other).status_code == 403


def test_making_a_quotation_needs_quotations_make_and_a_lower_price_its_reason() -> None:
    flow = InMemoryQuotations()
    url = base(flow)
    assert client(flow, "quotations.read").post(
        url, json=new(flow), headers=HEADERS
    ).status_code == (403)
    maker = client(flow, "quotations.read", "quotations.make")
    assert maker.post(url, json=new(flow)).status_code == 403
    assert maker.post(url, json={**new(flow), "lines": []}, headers=HEADERS).status_code == 422
    bad = {**new(flow), "lines": [{**new(flow)["lines"][0], "quantity": 0}]}  # type: ignore[index]
    assert maker.post(url, json=bad, headers=HEADERS).status_code == 422
    assert maker.post(url, json=new(flow, 2500), headers=HEADERS).status_code == 403
    lower = {**new(flow, 2500), "lowered_reason": "Long-time tenant"}
    made = maker.post(url, json=lower, headers=HEADERS)
    assert made.status_code == 201 and made.json()["data"]["quotation_number"] == "QT260001"
    saved = flow.calls[-1][1]
    assert isinstance(saved, dict) and saved["note"] == "Fan for the bedroom"


def test_customer_signed_needs_if_match_and_waits_for_stock() -> None:
    flow = InMemoryQuotations()
    url = f"{base(flow)}/{flow.quotation_id}/sign"
    body = {
        "signed_on": "2026-11-04",
        "takes": [{"position": 1, "unit_id": str(uuid4()), "item_id": str(uuid4()), "number": 1}],
    }
    reader = client(flow, "quotations.read")
    assert reader.post(url, json=body, headers={**HEADERS, "If-Match": "1"}).status_code == 403
    maker = client(flow, "quotations.read", "quotations.make")
    assert maker.post(url, json=body, headers=HEADERS).status_code == 428
    assert maker.post(url, json=body, headers={**HEADERS, "If-Match": '"7"'}).status_code == 412
    waits = maker.post(url, json=body, headers={**HEADERS, "If-Match": "1"})
    assert waits.status_code == 409 and waits.json()["error"]["code"] == "CONFLICT"
    flow.stock = 2
    signed = maker.post(url, json=body, headers={**HEADERS, "If-Match": '"1"'})
    assert signed.status_code == 200 and signed.json()["data"]["state"] == "SIGNED"
    sent = flow.calls[-1][1]
    assert isinstance(sent, dict) and str(sent["signed_on"]) == "2026-11-04"


def test_refusing_needs_a_reason() -> None:
    flow = InMemoryQuotations()
    url = f"{base(flow)}/{flow.quotation_id}/refuse"
    maker = client(flow, "quotations.read", "quotations.make")
    headers = {**HEADERS, "If-Match": "1"}
    assert maker.post(url, json={"reason": " "}, headers=headers).status_code == 422
    answer = maker.post(url, json={"reason": "Too dear"}, headers=headers)
    assert answer.status_code == 200 and flow.calls[-1] == ("refuse", "Too dear")
