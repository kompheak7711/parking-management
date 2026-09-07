"""Purpose-bound Payment reversal context; the existing action grant is sufficient."""

from __future__ import annotations

from typing import Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.payment_api import (
    Identity,
    PaymentRequestRoute,
    _actor,
    _authorize,
    _invoke,
    _queries,
)
from property_rental.payment_read import PaymentReadInvalidError
from property_rental.payment_reversal_context import (
    PaymentReversalContextChanged,
    ReversalContextPage,
)


class PaymentReversalContextFlow(Protocol):
    def get(
        self,
        property_id: UUID,
        payment_id: UUID,
        page: ReversalContextPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


def create_payment_reversal_context_router(
    actor_resolver: ActorResolver, flow: PaymentReversalContextFlow
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", route_class=PaymentRequestRoute)

    @router.get("/properties/{property_id}/payments/{payment_id}/reversal-context")
    def get(property_id: Identity, payment_id: Identity, request: Request) -> dict[str, object]:
        actor = _actor(request, actor_resolver)
        _authorize(actor, property_id, "payments.reverse")
        bind_financial_property(request, property_id)
        _queries(request, {"view", "limit", "cursor"})
        if request.headers.getlist("Idempotency-Key"):
            raise HTTPException(400)
        raw = request.query_params.get("limit", "50")
        view = request.query_params.get("view", "impact")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 3 or str(int(raw)) != raw:
            raise HTTPException(400)
        try:
            page = ReversalContextPage(
                cast(Literal["impact", "result"], view),
                int(raw),
                request.query_params.get("cursor"),
            )
        except PaymentReadInvalidError as exc:
            raise HTTPException(400) from exc

        def read() -> dict[str, object]:
            try:
                return flow.get(property_id, payment_id, page, actor=actor)
            except PaymentReversalContextChanged as exc:
                raise HTTPException(409) from exc
            except PaymentReadInvalidError as exc:
                raise HTTPException(400) from exc

        result = _invoke(read)
        metadata = financial_metadata(request)
        metadata["actor_id"] = actor.actor_id
        return {
            "data": result["data"],
            "page": {"limit": page.limit, "next_cursor": result["next_cursor"]},
            "meta": metadata,
        }

    return router
