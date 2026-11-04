"""Office > Invoices > Quotations (V1.1 part 6, DL-123, API-QT-001).

`GET /api/v1/properties/{property_id}/quotations` lists the latest Quotations and
`GET .../quotations/{quotation_id}` reads one (`quotations.read`). `POST .../quotations` makes a
Quotation, or a new one that replaces a waiting one (`quotations.make`; a price below the list
price also needs `quotations.lower_price` and a reason). `POST .../quotations/{id}/sign` records
"Customer signed" at the version in If-Match: the Products Invoice is issued at once and the Items
leave stock from the places given. `POST .../quotations/{id}/refuse` records that the Customer
refused, with a reason.

The database functions check the rights again and keep a Quotation unchanged; signing runs on
the financial connection because it issues an Invoice.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Protocol
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Request, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver
from property_rental.products_api import (
    REFUSED,
    Id,
    Json,
    ProductNotFound,
    ProductUnavailable,
    _expected_version,
    _http,
    _refusal,
    _require,
)
from property_rental.settings import Settings

QUOTATIONS_READ = "quotations.read"
QUOTATIONS_MAKE = "quotations.make"
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class QuotationFlow(Protocol):
    def quotations(self, property_id: UUID, *, actor_id: str) -> list[Json]: ...

    def quotation(self, property_id: UUID, quotation_id: UUID, *, actor_id: str) -> Json: ...

    def make(self, property_id: UUID, quotation: Json, *, actor_id: str) -> UUID: ...

    def sign(
        self, property_id: UUID, quotation_id: UUID, version: int, signature: Json, *, actor_id: str
    ) -> Json: ...

    def refuse(
        self, property_id: UUID, quotation_id: UUID, version: int, reason: str, *, actor_id: str
    ) -> None: ...


class UnavailableQuotationFlow:
    def quotations(self, property_id: UUID, **_: object) -> list[Json]:
        raise ProductUnavailable

    def quotation(self, property_id: UUID, quotation_id: UUID, **_: object) -> Json:
        raise ProductUnavailable

    def make(self, property_id: UUID, quotation: Json, **_: object) -> UUID:
        raise ProductUnavailable

    def sign(
        self, property_id: UUID, quotation_id: UUID, version: int, signature: Json, **_: object
    ) -> Json:
        raise ProductUnavailable

    def refuse(
        self, property_id: UUID, quotation_id: UUID, version: int, reason: str, **_: object
    ) -> None:
        raise ProductUnavailable


def _json(value: object) -> Json:
    if not isinstance(value, dict):
        raise ProductUnavailable("Quotation persistence is unavailable")
    return {str(key): item for key, item in value.items()}


class PostgresQuotationFlow:
    def __init__(self, database_url: str, financial_database_url: str | None) -> None:
        self._database_url = database_url
        self._financial_database_url = financial_database_url

    def _one(self, url: str | None, query: str, parameters: tuple[object, ...]) -> object:
        if url is None:
            raise ProductUnavailable("Quotation persistence is unavailable")
        try:
            with psycopg.connect(url) as connection:
                row = connection.execute(query, parameters).fetchone()
        except psycopg.Error as exc:
            raise _refusal(exc) from exc
        return None if row is None else row[0]

    def quotations(self, property_id: UUID, *, actor_id: str) -> list[Json]:
        found = self._one(
            self._database_url,
            "SELECT app.quotations_read(%s, %s)",
            (property_id, UUID(actor_id)),
        )
        if not isinstance(found, list):
            raise ProductUnavailable("Quotation persistence is unavailable")
        return [_json(item) for item in found]

    def quotation(self, property_id: UUID, quotation_id: UUID, *, actor_id: str) -> Json:
        return _json(
            self._one(
                self._database_url,
                "SELECT app.quotation_read(%s, %s, %s)",
                (property_id, quotation_id, UUID(actor_id)),
            )
        )

    def make(self, property_id: UUID, quotation: Json, *, actor_id: str) -> UUID:
        made = self._one(
            self._database_url,
            "SELECT app.make_quotation(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                property_id,
                quotation["customer_id"],
                quotation["lease_id"],
                quotation["note"],
                quotation["replaces_id"],
                quotation["lowered_reason"],
                Jsonb(quotation["lines"]),
                UUID(actor_id),
                uuid4(),
            ),
        )
        return UUID(str(made))

    def sign(
        self, property_id: UUID, quotation_id: UUID, version: int, signature: Json, *, actor_id: str
    ) -> Json:
        takes = signature["takes"]
        assert isinstance(takes, list)
        return _json(
            self._one(
                self._financial_database_url,
                "SELECT app.sign_quotation(%s, %s, %s, %s, %s, %s, %s)",
                (
                    property_id,
                    quotation_id,
                    version,
                    signature["signed_on"],
                    Jsonb(
                        {
                            str(take["position"]): {
                                "unit_id": str(take["unit_id"]),
                                "item_id": str(take["item_id"]),
                                "number": take["number"],
                            }
                            for take in takes
                        }
                    ),
                    UUID(actor_id),
                    uuid4(),
                ),
            )
        )

    def refuse(
        self, property_id: UUID, quotation_id: UUID, version: int, reason: str, *, actor_id: str
    ) -> None:
        self._one(
            self._database_url,
            "SELECT app.refuse_quotation(%s, %s, %s, %s, %s, %s)",
            (property_id, quotation_id, version, reason, UUID(actor_id), uuid4()),
        )


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuotationLine(_Body):
    product_id: Id
    quantity: Annotated[int, Field(ge=1, le=999)]
    price_usd_cents: Annotated[int, Field(gt=0, le=999_999_999)]


class NewQuotation(_Body):
    customer_id: Id
    lease_id: Id | None = None
    note: Note | None = None
    replaces_id: Id | None = None
    lowered_reason: Reason | None = None
    lines: Annotated[list[QuotationLine], Field(min_length=1, max_length=20)]


class Take(_Body):
    position: Annotated[int, Field(ge=1, le=20)]
    unit_id: Id
    item_id: Id
    number: Annotated[int, Field(ge=1, le=9)]


class Signature(_Body):
    signed_on: Annotated[date, Field(strict=False)]
    takes: Annotated[list[Take], Field(max_length=20)]


class Refusal(_Body):
    reason: Reason


def create_quotations_router(
    resolver: ActorResolver, flow: QuotationFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", tags=["quotations"])

    def envelope(request: Request, data: object) -> Json:
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    def one(property_id: UUID, quotation_id: UUID, actor_id: str, request: Request) -> Json:
        try:
            return envelope(request, flow.quotation(property_id, quotation_id, actor_id=actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/quotations")
    def list_quotations(property_id: UUID, request: Request, response: Response) -> Json:
        actor = _require(request, resolver, QUOTATIONS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        try:
            return envelope(request, flow.quotations(property_id, actor_id=actor.actor_id))
        except REFUSED as exc:
            raise _http(exc) from exc

    @router.get("/quotations/{quotation_id}")
    def read_quotation(
        property_id: UUID, quotation_id: UUID, request: Request, response: Response
    ) -> Json:
        actor = _require(request, resolver, QUOTATIONS_READ, property_id)
        response.headers["Cache-Control"] = "private, no-store"
        return one(property_id, quotation_id, actor.actor_id, request)

    @router.post("/quotations", status_code=status.HTTP_201_CREATED)
    def make_quotation(property_id: UUID, quotation: NewQuotation, request: Request) -> Json:
        actor = _require(request, resolver, QUOTATIONS_MAKE, property_id)
        require_browser_mutation(request, settings)
        body: Json = quotation.model_dump()
        body["lines"] = [
            {
                "product_id": str(line.product_id),
                "quantity": line.quantity,
                "price_usd_cents": line.price_usd_cents,
            }
            for line in quotation.lines
        ]
        try:
            made = flow.make(property_id, body, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, made, actor.actor_id, request)

    @router.post("/quotations/{quotation_id}/sign")
    def sign_quotation(
        property_id: UUID, quotation_id: UUID, signature: Signature, request: Request
    ) -> Json:
        actor = _require(request, resolver, QUOTATIONS_MAKE, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            signed = flow.sign(
                property_id,
                quotation_id,
                version,
                signature.model_dump(),
                actor_id=actor.actor_id,
            )
        except REFUSED as exc:
            raise _http(exc) from exc
        return envelope(request, signed)

    @router.post("/quotations/{quotation_id}/refuse")
    def refuse_quotation(
        property_id: UUID, quotation_id: UUID, refusal: Refusal, request: Request
    ) -> Json:
        actor = _require(request, resolver, QUOTATIONS_MAKE, property_id)
        require_browser_mutation(request, settings)
        version = _expected_version(request)
        try:
            flow.refuse(property_id, quotation_id, version, refusal.reason, actor_id=actor.actor_id)
        except REFUSED as exc:
            raise _http(exc) from exc
        return one(property_id, quotation_id, actor.actor_id, request)

    return router


__all__ = [
    "NewQuotation",
    "PostgresQuotationFlow",
    "ProductNotFound",
    "QuotationFlow",
    "UnavailableQuotationFlow",
    "create_quotations_router",
]
