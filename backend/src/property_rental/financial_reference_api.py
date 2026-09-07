"""Protected reference discovery and provisional calculations; no financial writes."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from property_rental.browser_security import require_browser_mutation
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.financial_reference import ReferencePage
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.khr_payment_confirmation import ManualKhrReference
from property_rental.payment_api import (
    Identity,
    ManualReferenceInput,
    MinorUnits,
    PaymentRequestRoute,
    StrictInput,
    _actor,
    _authorize,
    _invoke,
    _queries,
    _strict_json,
)
from property_rental.settings import Settings


class KhrPreviewInput(StrictInput):
    usd_amount_cents: MinorUnits
    manual_reference: ManualReferenceInput | None = None


class FinancialReferenceFlow(Protocol):
    def workspaces(
        self, page: ReferencePage, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def capability_view(
        self, property_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def methods(
        self, property_id: UUID, page: ReferencePage, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def preview(
        self,
        property_id: UUID,
        usd_amount_cents: int,
        manual: ManualKhrReference | None,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


def _page(request: Request) -> ReferencePage:
    _queries(request, {"limit", "cursor"})
    raw = request.query_params.get("limit", "50")
    cursor = request.query_params.get("cursor")
    try:
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 3:
            raise ValueError
        limit = int(raw)
        if str(limit) != raw or not 1 <= limit <= 100:
            raise ValueError
        after = None if cursor is None else UUID(cursor)
        if after is not None and (str(after) != cursor or not after.int):
            raise ValueError
        return ReferencePage(limit, after)
    except ValueError as exc:
        raise HTTPException(400) from exc


def create_financial_reference_router(
    resolver: ActorResolver, flow: FinancialReferenceFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["financial references"], route_class=PaymentRequestRoute
    )

    def actor_for(request: Request) -> AuthenticatedActor:
        actor = _actor(request, resolver)
        if len(request.headers.getlist("X-Billing-Actor-ID")) > 1:
            raise HTTPException(400)
        return actor

    def metadata(
        request: Request, actor: AuthenticatedActor, scoped: bool = True
    ) -> dict[str, str]:
        return {
            **(financial_metadata(request) if scoped else {"request_id": request.state.request_id}),
            "actor_id": actor.actor_id,
        }

    @router.get("/financial-workspaces")
    def workspaces(request: Request) -> dict[str, object]:
        actor = actor_for(request)
        if request.headers.getlist("X-Financial-Property-ID"):
            raise HTTPException(400)
        page = _page(request)
        result = _invoke(lambda: flow.workspaces(page, actor=actor))
        return {
            "data": result["items"],
            "page": {"limit": page.limit, "next_cursor": result["next_cursor"]},
            "meta": metadata(request, actor, False),
        }

    @router.get("/properties/{property_id}/financial-capabilities")
    def capability_view(property_id: Identity, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        bind_financial_property(request, property_id)
        _queries(request, set())
        result = _invoke(lambda: flow.capability_view(property_id, actor=actor))
        return {"data": result, "meta": metadata(request, actor)}

    @router.get("/properties/{property_id}/payment-methods")
    def methods(property_id: Identity, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        _authorize(actor, property_id, "payments.record")
        bind_financial_property(request, property_id)
        page = _page(request)
        result = _invoke(lambda: flow.methods(property_id, page, actor=actor))
        return {
            "data": result["items"],
            "page": {"limit": page.limit, "next_cursor": result["next_cursor"]},
            "meta": metadata(request, actor),
        }

    @router.post(
        "/properties/{property_id}/payments/khr-preview", dependencies=[Depends(_strict_json)]
    )
    def preview(
        property_id: Identity, body: KhrPreviewInput, request: Request
    ) -> dict[str, object]:
        actor = actor_for(request)
        _authorize(actor, property_id, "payments.record")
        bind_financial_property(request, property_id)
        _queries(request, set())
        if request.headers.getlist("Idempotency-Key"):
            raise HTTPException(400)
        for header in ("Origin", "X-CSRF-Token"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(400)
        if not request.headers.get("X-CSRF-Token"):
            raise HTTPException(403)
        require_browser_mutation(request, settings)
        if body.manual_reference is not None:
            _authorize(actor, property_id, "exchange_rates.manage")
        manual = (
            _invoke(body.manual_reference.command) if body.manual_reference is not None else None
        )
        result = _invoke(
            lambda: flow.preview(property_id, body.usd_amount_cents, manual, actor=actor)
        )
        return {"data": result, "meta": metadata(request, actor)}

    return router
