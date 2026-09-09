"""Read-only Customer Account Ledger with separate capability and private responses."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.routing import APIRoute
from pydantic import BeforeValidator

from property_rental.customer_ledger import (
    LedgerFilter,
    LedgerInvalidError,
    LedgerSnapshotChangedError,
)
from property_rental.customer_ledger_query import LEDGER_CAPABILITY, LedgerReadRequest, identity
from property_rental.customer_ledger_read import (
    LedgerAuthorizationError,
    LedgerNotFoundError,
    LedgerUnavailableError,
)
from property_rental.financial_context import (
    PROPERTY_HEADER,
    bind_financial_property,
    financial_metadata,
)
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.payment_api import _actor, _queries, _timestamp


def _customer_identity(value: object) -> UUID:
    # Validate the original path spelling before UUID parsing can normalize it.
    if not isinstance(value, str):
        raise ValueError("A canonical Customer identity is required")
    result = identity(UUID(value))
    if str(result) != value:
        raise ValueError("A canonical Customer identity is required")
    return result


LedgerCustomerIdentity = Annotated[UUID, BeforeValidator(_customer_identity)]


class CustomerLedgerFlow(Protocol):
    def get(
        self,
        customer_id: UUID,
        query: LedgerReadRequest,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]: ...

    def customers(
        self,
        limit: int,
        after: UUID | None,
        *,
        actor: AuthenticatedActor,
        expected_property: UUID | None = None,
    ) -> dict[str, object]: ...


class LedgerReadRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[object, object, Response]]:
        original = super().get_route_handler()

        async def read(request: Request) -> Response:
            # Reject the first body bytes without buffering an unbounded GET body.
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(400)
            return await original(request)

        return read


def _expected_property(request: Request) -> UUID | None:
    values = request.headers.getlist(PROPERTY_HEADER)
    if len(values) > 1:
        raise HTTPException(400)
    try:
        if values:
            value = identity(UUID(values[0]))
            if str(value) != values[0]:
                raise ValueError
            return value
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400) from exc
    return None


def _limit(request: Request) -> int:
    raw = request.query_params.get("limit", "50")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 3 or str(int(raw)) != raw:
        raise HTTPException(400)
    result = int(raw)
    if not 1 <= result <= 100:
        raise HTTPException(400)
    return result


def _invoke(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except LedgerNotFoundError as exc:
        raise HTTPException(404) from exc
    except LedgerAuthorizationError as exc:
        raise HTTPException(403) from exc
    except LedgerInvalidError as exc:
        raise HTTPException(400) from exc
    except LedgerSnapshotChangedError as exc:
        raise HTTPException(409) from exc
    except LedgerUnavailableError as exc:
        raise HTTPException(503) from exc


def create_customer_ledger_router(
    actor_resolver: ActorResolver, flow: CustomerLedgerFlow
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", route_class=LedgerReadRoute)

    def actor_for(request: Request) -> AuthenticatedActor:
        if len(request.headers.getlist("X-Billing-Actor-ID")) > 1:
            raise HTTPException(400)
        actor = _actor(request, actor_resolver)
        if not any(
            g.capability == LEDGER_CAPABILITY and g.property_ids for g in actor.capability_grants
        ):
            raise HTTPException(403)
        if request.headers.getlist("Idempotency-Key"):
            raise HTTPException(400)
        return actor

    def metadata(request: Request, actor: AuthenticatedActor, prop: object) -> dict[str, str]:
        try:
            if not isinstance(prop, str) or str(identity(UUID(prop))) != prop:
                raise ValueError
            if not is_authorized(actor, AuthorizationRequirement(LEDGER_CAPABILITY, prop)):
                raise HTTPException(503)
            bind_financial_property(request, UUID(prop))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(503) from exc
        return financial_metadata(request) | {"actor_id": actor.actor_id}

    @router.get("/customers/{customer_id}/account-ledger")
    def get(customer_id: LedgerCustomerIdentity, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        expected = _expected_property(request)
        _queries(
            request,
            {
                "section",
                "limit",
                "cursor",
                "revision",
                "from",
                "through",
                "kind",
                "event_kind",
                "event_id",
            },
        )
        limit = _limit(request)
        params = request.query_params
        try:
            selected = params.get("event_id")
            event_id = identity(UUID(selected)) if selected is not None else None
            if event_id is not None and str(event_id) != selected:
                raise ValueError
            query = LedgerReadRequest(
                params.get("section", "history"),
                limit,
                LedgerFilter(
                    _timestamp(params["from"]) if "from" in params else None,
                    _timestamp(params["through"]) if "through" in params else None,
                    params.get("kind"),
                ),
                params.get("event_kind"),
                event_id,
                params.get("revision"),
                params.get("cursor"),
            )
        except (ValueError, TypeError, AttributeError, OverflowError) as exc:
            raise HTTPException(400) from exc
        result = _invoke(
            lambda: flow.get(customer_id, query, actor=actor, expected_property=expected)
        )
        data = result.get("data")
        if not isinstance(data, dict) or data.get("customer_id") != str(customer_id):
            raise HTTPException(503)
        return {
            "data": data,
            "page": {"limit": limit, "next_cursor": result["next_cursor"]},
            "meta": metadata(request, actor, data.get("property_id")),
        }

    @router.get("/customer-ledger/customers")
    def customers(request: Request) -> dict[str, object]:
        actor = actor_for(request)
        expected = _expected_property(request)
        _queries(request, {"limit", "cursor"})
        limit = _limit(request)
        raw = request.query_params.get("cursor")
        try:
            after = identity(UUID(raw)) if raw is not None else None
            if after is not None and str(after) != raw:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400) from exc
        result = _invoke(
            lambda: flow.customers(limit, after, actor=actor, expected_property=expected)
        )
        return {
            "data": result["items"],
            "page": {"limit": limit, "next_cursor": result["next_cursor"]},
            "meta": metadata(request, actor, result.get("property_id")),
        }

    return router
