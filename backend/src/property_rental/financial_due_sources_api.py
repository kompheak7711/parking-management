"""Finite authorized dated-source choices before explicit financial confirmation."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.financial_due_sources import (
    DUE_SOURCE_CAPABILITIES,
    FinancialDueSourcesChanged,
    FinancialDueSourcesRequest,
)
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


class FinancialDueSourcesFlow(Protocol):
    def get(
        self, property_id: UUID, request: FinancialDueSourcesRequest, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...


def create_financial_due_sources_router(
    actor_resolver: ActorResolver, flow: FinancialDueSourcesFlow
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", route_class=PaymentRequestRoute)

    @router.get("/financial-due-sources")
    def get(property_id: Identity, request: Request) -> dict[str, object]:
        actor = _actor(request, actor_resolver)
        if len(request.headers.getlist("X-Billing-Actor-ID")) > 1:
            raise HTTPException(400)
        _queries(
            request, {"purpose", "source_id", "invoice_id", "invoice_line_id", "limit", "cursor"}
        )
        purpose = request.query_params.get("purpose")
        if purpose is None or purpose not in DUE_SOURCE_CAPABILITIES:
            raise HTTPException(400)
        _authorize(actor, property_id, DUE_SOURCE_CAPABILITIES[purpose])
        bind_financial_property(request, property_id)
        if request.headers.getlist("Idempotency-Key"):
            raise HTTPException(400)
        raw_limit = request.query_params.get("limit", "50")
        if (
            not raw_limit.isascii()
            or not raw_limit.isdecimal()
            or len(raw_limit) > 3
            or str(int(raw_limit)) != raw_limit
        ):
            raise HTTPException(400)
        try:
            identities = [
                request.query_params[key] for key in ("source_id", "invoice_id", "invoice_line_id")
            ]
            parsed = [UUID(value) for value in identities]
            if any(
                str(identity) != value for identity, value in zip(parsed, identities, strict=True)
            ):
                raise ValueError
            checked = FinancialDueSourcesRequest(
                purpose,
                parsed[0],
                parsed[1],
                parsed[2],
                int(raw_limit),
                request.query_params.get("cursor"),
            )
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400) from exc

        def invoke() -> dict[str, object]:
            try:
                return flow.get(property_id, checked, actor=actor)
            except FinancialDueSourcesChanged as exc:
                raise HTTPException(409) from exc
            except PaymentReadInvalidError as exc:
                raise HTTPException(400) from exc

        result = _invoke(invoke)
        metadata = financial_metadata(request)
        metadata["actor_id"] = actor.actor_id
        return {
            "data": result["data"],
            "page": {"limit": checked.limit, "next_cursor": result["next_cursor"]},
            "meta": metadata,
        }

    return router
