"""Finite action-source reads with independent action capability checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from property_rental.financial_action_context import (
    ACTION_CAPABILITIES,
    FinancialActionContextChanged,
    FinancialActionContextRequest,
)
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


class FinancialActionContextFlow(Protocol):
    def get(
        self,
        property_id: UUID,
        request: FinancialActionContextRequest,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


ACTION_CONTEXT_PATHS = {
    "allocation": "/payments/{source_id}/allocation-context",
    "allocation_reversal": "/payment-allocations/{source_id}/reversal-context",
    "receipt_reprint": "/receipts/{source_id}/reprint-context",
    "credit_recognition": "/payments/{source_id}/credit-recognition-context",
    "credit_reversal": "/customer-credits/{source_id}/reversal-context",
    "credit_application": "/customer-credits/{source_id}/application-context",
    "credit_application_reversal": "/credit-applications/{source_id}/reversal-context",
    "refund_return": "/refunds/{source_id}/verified-return-context",
    "refund_correction_reversal": "/refunds/{refund_id}/corrections/{source_id}/reversal-context",
}


def create_financial_action_context_router(
    actor_resolver: ActorResolver, flow: FinancialActionContextFlow
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/properties/{property_id}", route_class=PaymentRequestRoute)

    def read(
        purpose: str,
        property_id: UUID,
        source_id: UUID,
        request: Request,
        refund_id: UUID | None = None,
    ) -> dict[str, object]:
        actor = _actor(request, actor_resolver)
        _authorize(actor, property_id, ACTION_CAPABILITIES[purpose])
        bind_financial_property(request, property_id)
        allowed = {"limit", "cursor"}
        if purpose in {"allocation", "credit_application"}:
            allowed |= {"target_kind", "target_id"}
        _queries(request, allowed)
        if request.headers.getlist("Idempotency-Key"):
            raise HTTPException(400)
        raw = request.query_params.get("limit", "50")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 3 or str(int(raw)) != raw:
            raise HTTPException(400)
        target = request.query_params.get("target_id")
        try:
            target_id = UUID(target) if target is not None else None
            if target_id is not None and str(target_id) != target:
                raise ValueError
            checked = FinancialActionContextRequest(
                purpose,
                source_id,
                request.query_params.get("target_kind"),
                target_id,
                refund_id,
                int(raw),
                request.query_params.get("cursor"),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400) from exc

        def invoke() -> dict[str, object]:
            try:
                return flow.get(property_id, checked, actor=actor)
            except FinancialActionContextChanged as exc:
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

    def endpoint(purpose: str) -> Callable[[UUID, UUID, Request], dict[str, object]]:
        def get(property_id: Identity, source_id: Identity, request: Request) -> dict[str, object]:
            return read(purpose, property_id, source_id, request)

        return get

    for purpose, path in ACTION_CONTEXT_PATHS.items():
        if purpose != "refund_correction_reversal":
            router.add_api_route(
                path, endpoint(purpose), methods=["GET"], name=purpose + "_context"
            )

    @router.get(ACTION_CONTEXT_PATHS["refund_correction_reversal"])
    def correction(
        property_id: Identity, refund_id: Identity, source_id: Identity, request: Request
    ) -> dict[str, object]:
        return read("refund_correction_reversal", property_id, source_id, request, refund_id)

    return router
