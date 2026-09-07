"""Explicit USD Credit/Refund HTTP adapters over the accepted financial services."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Protocol, TypeVar, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import Field, model_validator
from starlette.types import Receive, Scope, Send

from property_rental.allocation_receipt_api import (
    AllocationReceiptRequestRoute,
    ReversalInput,
    _mutation,
    _strict_json,
)
from property_rental.credit import (
    CREDIT_EVENT_KINDS,
    ApplyCreditCommand,
    CreditAuthorizationError,
    CreditConflictError,
    CreditIdempotencyKeyReused,
    CreditInvalidError,
    CreditLedgerPage,
    CreditNotFoundError,
    CreditPage,
    CreditUnavailableError,
    CustomerCreditService,
    RecognizeCreditCommand,
    ReverseCreditApplicationCommand,
    ReverseCreditCommand,
)
from property_rental.credit_refund_read import (
    CreditRefundReadService,
    FinancialReadAuthorizationError,
    FinancialReadInvalidError,
    FinancialReadNotFoundError,
    FinancialReadUnavailableError,
    Resource,
)
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.payment_api import (
    Evidence,
    Identity,
    Instant,
    MinorUnits,
    StrictInput,
    _actor,
    _authorize,
    _cursor,
    _queries,
    _timestamp,
)
from property_rental.refund import (
    CreatePetRefundCommand,
    CreateUsdRefundCommand,
    RefundAuthorizationError,
    RefundIdempotencyKeyReused,
    RefundInvalidError,
    RefundNotFoundError,
    RefundPage,
    RefundService,
    RefundUnavailableError,
    ReverseRefundCorrectionCommand,
    VerifyUsdRefundReturnCommand,
)
from property_rental.settings import Settings

T = TypeVar("T")
SourceType = Literal["PAYMENT", "CREDIT", "PET_DEPOSIT"]
Binding = dict[str, str | None]
PageLimit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Key = Annotated[Identity, Header(alias="Idempotency-Key")]


class RecognizeInput(ReversalInput):
    currency: Literal["USD"]
    amount_usd_cents: MinorUnits
    payer_authorization_reference: Evidence


class ApplyInput(StrictInput):
    currency: Literal["USD"]
    intent: Annotated[dict[str, object], Field(strict=True)]


class CreateRefundInput(ReversalInput):
    currency: Literal["USD"]
    source_type: SourceType
    source_id: Identity
    amount_usd_cents: MinorUnits
    pet_refund_review_id: Identity | None = None

    @model_validator(mode="after")
    def matching_review(self) -> CreateRefundInput:
        if (self.source_type == "PET_DEPOSIT") != (self.pet_refund_review_id is not None):
            raise ValueError("Only Pet sources require a matching qualifying review")
        return self


class VerifiedReturnInput(ReversalInput):
    currency: Literal["USD"]
    returned_amount_minor: MinorUnits
    returned_at: Instant
    return_method_reference: Evidence
    evidence_reference: Evidence


class CorrectionReversalInput(ReversalInput):
    evidence_reference: Evidence


class CreditRefundFlow(Protocol):
    def resolve(
        self, resource: Resource, identity: UUID, capability: str, *, actor: AuthenticatedActor
    ) -> UUID: ...
    def credits(self, *, mutation: bool = False) -> CustomerCreditService: ...
    def refunds(self, *, mutation: bool = False) -> RefundService: ...
    def source_audit(
        self,
        prop: UUID,
        kind: Literal["PAYMENT", "CREDIT"],
        identity: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PostgresCreditRefundFlow:
    database_url: str | None
    financial_database_url: str | None

    def _runtime(self) -> str:
        if self.database_url is None:
            raise FinancialReadUnavailableError("Financial reads are unavailable")
        return self.database_url

    def _financial(self) -> str:
        if self.financial_database_url is None:
            raise FinancialReadUnavailableError("Financial commands are unavailable")
        return self.financial_database_url

    def resolve(
        self, resource: Resource, identity: UUID, capability: str, *, actor: AuthenticatedActor
    ) -> UUID:
        return CreditRefundReadService(self.database_url).resolve(
            resource, identity, capability, actor=actor
        )

    def credits(self, *, mutation: bool = False) -> CustomerCreditService:
        # Read methods retain the accepted normal transactions and source SHARE
        # locks. No writer credential is used or required for reads. Every command
        # explicitly requests mutation=True and requires the separate writer URL.
        return CustomerCreditService(self._runtime(), self._financial() if mutation else "")

    def refunds(self, *, mutation: bool = False) -> RefundService:
        return RefundService(self._runtime(), self._financial() if mutation else "")

    def source_audit(
        self,
        prop: UUID,
        kind: Literal["PAYMENT", "CREDIT"],
        identity: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return CreditRefundReadService(self.database_url).source_audit(
            prop, kind, identity, actor=actor
        )


def _invoke(call: Callable[[], T], *, query: bool = False) -> T:
    try:
        return call()
    except (CreditIdempotencyKeyReused, RefundIdempotencyKeyReused):
        raise
    except (
        CreditNotFoundError,
        RefundNotFoundError,
        FinancialReadNotFoundError,
        CreditAuthorizationError,
        RefundAuthorizationError,
        FinancialReadAuthorizationError,
    ) as exc:
        raise HTTPException(404) from exc
    except (CreditInvalidError, RefundInvalidError, FinancialReadInvalidError) as exc:
        raise HTTPException(400 if query else 422) from exc
    except CreditConflictError as exc:
        raise HTTPException(409) from exc
    except (CreditUnavailableError, RefundUnavailableError, FinancialReadUnavailableError) as exc:
        raise HTTPException(503) from exc


def _binding(collection: str, prop: UUID, resource: UUID, customer: UUID | None = None) -> Binding:
    return {
        "collection": collection,
        "property_id": str(prop),
        "resource_id": str(resource),
        "customer_id": str(customer) if customer is not None else None,
    }


def _decode_cursor(
    cursor: str | None, binding: Binding, *, ledger: bool = False
) -> tuple[datetime | None, str | None, UUID | None]:
    if cursor is None:
        return None, None, None
    try:
        if not cursor.isascii() or len(cursor) > 1024:
            raise ValueError
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        keys = {*binding, "occurred_at", "id"} | ({"event_kind"} if ledger else set())
        if not isinstance(value, dict) or set(value) != keys or _cursor(value) != cursor:
            raise ValueError
        if any(value[key] != expected for key, expected in binding.items()):
            raise ValueError
        at = _timestamp(value["occurred_at"])
        identity = value["id"]
        if (
            not isinstance(identity, str)
            or str(UUID(identity)) != identity
            or UUID(identity).int == 0
        ):
            raise ValueError
        kind = value.get("event_kind")
        if ledger and (not isinstance(kind, str) or kind not in CREDIT_EVENT_KINDS):
            raise ValueError
        return at, cast(str | None, kind), UUID(identity)
    except (
        ValueError,
        TypeError,
        binascii.Error,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as exc:
        raise HTTPException(400) from exc


def _next_cursor(value: object, binding: Binding, *, ledger: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(503)
    keys = {"occurred_at", "id"} | ({"event_kind"} if ledger else set())
    if set(value) != keys:
        raise HTTPException(503)
    try:
        encoded = _cursor({**value, **binding})
        _decode_cursor(encoded, binding, ledger=ledger)
        return encoded
    except (HTTPException, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(503) from exc


def _collection(
    value: object, limit: int, binding: Binding, *, ledger: bool = False
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"items", "next_cursor"}:
        raise HTTPException(503)
    items = value["items"]
    if (
        not isinstance(items, list)
        or len(items) > limit
        or any(not isinstance(item, dict) for item in items)
    ):
        raise HTTPException(503)
    return {
        "items": items,
        "page": {
            "limit": limit,
            "next_cursor": _next_cursor(value["next_cursor"], binding, ledger=ledger),
        },
    }


def _refund_result(
    result: dict[str, object], prop: UUID, *, expected: UUID | None = None, limit: int = 50
) -> dict[str, object]:
    refund, source = result.get("refund"), result.get("source")
    if (
        not isinstance(refund, dict)
        or not isinstance(source, dict)
        or source.get("property_id") != str(prop)
    ):
        raise HTTPException(503)
    try:
        identity = UUID(str(refund["id"]))
        if identity.int == 0 or (expected is not None and identity != expected):
            raise ValueError
    except (ValueError, KeyError) as exc:
        raise HTTPException(503) from exc
    return {
        **result,
        "corrections": _collection(
            result.get("corrections"), limit, _binding("refund-corrections", prop, identity)
        ),
    }


def _source_resource(source_type: SourceType) -> Resource:
    if source_type == "PAYMENT":
        return "payment"
    if source_type == "CREDIT":
        return "credit"
    return "deposit"


async def _financial_json(request: Request) -> None:
    await _strict_json(request)
    # JSON permits escaped NUL but PostgreSQL text does not. Reject it before
    # constructing or dispatching any financial command, including nested intent.
    pending: list[object] = [await request.json()]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                raise HTTPException(422)
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


class CreditRefundRequestRoute(AllocationReceiptRequestRoute):
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.methods or scope["method"] in self.methods:
            # Reject malformed query envelopes before FastAPI parses individual
            # values. Keep unsupported-method handling and inherited body bounds.
            _queries(
                Request(scope),
                {parameter.alias for parameter in self.dependant.query_params},
            )
        await super().handle(scope, receive, send)


def create_credit_refund_router(
    resolver: ActorResolver, flow: CreditRefundFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["credits", "refunds"], route_class=CreditRefundRequestRoute
    )

    def context(
        request: Request, resource: Resource, identity: UUID, capability: str
    ) -> tuple[AuthenticatedActor, UUID]:
        actor = _actor(request, resolver)
        if request.method == "POST":
            _mutation(request, settings)
        prop = _invoke(lambda: flow.resolve(resource, identity, capability, actor=actor))
        _authorize(actor, prop, capability, hide=True)
        return actor, prop

    def envelope(request: Request, result: object) -> dict[str, object]:
        return {"data": result, "meta": {"request_id": request.state.request_id}}

    def queries(request: Request, allowed: set[str], limit: int | None = None) -> None:
        _queries(request, allowed)
        if (
            limit is not None
            and "limit" in request.query_params
            and request.query_params["limit"] != str(limit)
        ):
            raise HTTPException(400)

    @router.get("/customers/{customer_id}/credits")
    def credits(
        customer_id: Identity, request: Request, limit: PageLimit = 50, cursor: Cursor = None
    ) -> dict[str, object]:
        queries(request, {"limit", "cursor"}, limit)
        actor, prop = context(request, "customer", customer_id, "credits.read")
        binding = _binding("customer-credits", prop, customer_id)
        at, _, identity = _decode_cursor(cursor, binding)
        page = CreditPage(limit, at, identity)
        result = _invoke(
            lambda: flow.credits().list(prop, customer_id, page, actor=actor), query=True
        )
        collection = _collection(result, limit, binding)
        return {**envelope(request, collection["items"]), "page": collection["page"]}

    @router.get("/customer-credits/{credit_id}")
    def credit(credit_id: Identity, request: Request) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "credit", credit_id, "credits.read")
        return envelope(request, _invoke(lambda: flow.credits().get(prop, credit_id, actor=actor)))

    @router.get("/customer-credits/{credit_id}/ledger")
    def ledger(
        credit_id: Identity, request: Request, limit: PageLimit = 50, cursor: Cursor = None
    ) -> dict[str, object]:
        queries(request, {"limit", "cursor"}, limit)
        actor, prop = context(request, "credit", credit_id, "credits.read")
        binding = _binding("credit-ledger", prop, credit_id)
        at, kind, identity = _decode_cursor(cursor, binding, ledger=True)
        page = CreditLedgerPage(limit, at, kind, identity)
        result = _invoke(
            lambda: flow.credits().ledger(prop, credit_id, page, actor=actor), query=True
        )
        return envelope(
            request,
            {**result, "history": _collection(result.get("history"), limit, binding, ledger=True)},
        )

    @router.post(
        "/payments/{payment_id}/credit-recognitions",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def recognize(
        payment_id: Identity,
        body: RecognizeInput,
        request: Request,
        response: Response,
        idempotency_key: Key,
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "payment", payment_id, "credits.recognize")
        command = _invoke(
            lambda: RecognizeCreditCommand(
                idempotency_key,
                body.amount_usd_cents,
                body.payer_authorization_reference,
                body.reason,
            )
        )
        result = _invoke(
            lambda: flow.credits(mutation=True).recognize(prop, payment_id, command, actor=actor)
        )
        header = result.get("credit")
        if not isinstance(header, dict) or not isinstance(header.get("id"), str):
            raise HTTPException(503)
        response.headers["Location"] = f"/api/v1/customer-credits/{header['id']}"
        return envelope(request, result)

    @router.post("/customer-credits/{credit_id}/reverse", dependencies=[Depends(_financial_json)])
    def reverse_credit(
        credit_id: Identity, body: ReversalInput, request: Request, idempotency_key: Key
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "credit", credit_id, "credits.reverse")
        command = _invoke(lambda: ReverseCreditCommand(idempotency_key, body.reason))
        return envelope(
            request,
            _invoke(
                lambda: flow.credits(mutation=True).reverse(prop, credit_id, command, actor=actor)
            ),
        )

    @router.get("/customer-credits/{credit_id}/application-proposal")
    def proposal(
        credit_id: Identity,
        request: Request,
        invoice_id: Identity,
        amount_usd_cents: Annotated[int, Query(gt=0, le=9_000_000_000_000_000)],
    ) -> dict[str, object]:
        queries(request, {"invoice_id", "amount_usd_cents"})
        if request.query_params["amount_usd_cents"] != str(amount_usd_cents):
            raise HTTPException(400)
        actor, prop = context(request, "credit", credit_id, "credits.apply")
        return envelope(
            request,
            _invoke(
                lambda: flow.credits().application_proposal(
                    prop, credit_id, invoice_id, amount_usd_cents, actor=actor
                ),
                query=True,
            ),
        )

    @router.post(
        "/customer-credits/{credit_id}/applications",
        status_code=201,
        dependencies=[Depends(_financial_json)],
    )
    def apply(
        credit_id: Identity,
        body: ApplyInput,
        request: Request,
        response: Response,
        idempotency_key: Key,
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "credit", credit_id, "credits.apply")
        command = _invoke(lambda: ApplyCreditCommand(idempotency_key, body.intent))
        result = _invoke(
            lambda: flow.credits(mutation=True).apply(prop, credit_id, command, actor=actor)
        )
        header = result.get("application")
        if not isinstance(header, dict) or not isinstance(header.get("id"), str):
            raise HTTPException(503)
        response.headers["Location"] = f"/api/v1/credit-applications/{header['id']}"
        return envelope(request, result)

    @router.get("/credit-applications/{application_id}")
    def application(application_id: Identity, request: Request) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "credit_application", application_id, "credits.read")
        return envelope(
            request,
            _invoke(lambda: flow.credits().get_application(prop, application_id, actor=actor)),
        )

    @router.post(
        "/credit-applications/{application_id}/reverse", dependencies=[Depends(_financial_json)]
    )
    def reverse_application(
        application_id: Identity, body: ReversalInput, request: Request, idempotency_key: Key
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(
            request, "credit_application", application_id, "credits.applications.reverse"
        )
        command = _invoke(lambda: ReverseCreditApplicationCommand(idempotency_key, body.reason))
        return envelope(
            request,
            _invoke(
                lambda: flow.credits(mutation=True).reverse_application(
                    prop, application_id, command, actor=actor
                )
            ),
        )

    @router.get("/properties/{property_id}/refunds")
    def refunds(
        property_id: Identity,
        request: Request,
        customer_id: Identity | None = None,
        limit: PageLimit = 50,
        cursor: Cursor = None,
    ) -> dict[str, object]:
        queries(request, {"customer_id", "limit", "cursor"}, limit)
        actor, prop = context(request, "property", property_id, "refunds.read")
        binding = _binding("refunds", prop, property_id, customer_id)
        at, _, identity = _decode_cursor(cursor, binding)
        page = RefundPage(limit, at, identity)
        result = _invoke(
            lambda: flow.refunds().list(prop, actor=actor, customer_id=customer_id, page=page),
            query=True,
        )
        collection = _collection(result, limit, binding)
        return {**envelope(request, collection["items"]), "page": collection["page"]}

    @router.get("/refunds/{refund_id}")
    def refund(
        refund_id: Identity, request: Request, limit: PageLimit = 50, cursor: Cursor = None
    ) -> dict[str, object]:
        queries(request, {"limit", "cursor"}, limit)
        actor, prop = context(request, "refund", refund_id, "refunds.read")
        binding = _binding("refund-corrections", prop, refund_id)
        at, _, identity = _decode_cursor(cursor, binding)
        page = RefundPage(limit, at, identity)
        result = _invoke(
            lambda: flow.refunds().get(prop, refund_id, actor=actor, page=page), query=True
        )
        return envelope(request, _refund_result(result, prop, expected=refund_id, limit=limit))

    @router.get("/refund-sources/{source_type}/{source_id}")
    def source(
        source_type: SourceType,
        source_id: Identity,
        request: Request,
        pet_refund_review_id: Identity | None = None,
    ) -> dict[str, object]:
        queries(request, {"pet_refund_review_id"})
        if (source_type == "PET_DEPOSIT") != (pet_refund_review_id is not None):
            raise HTTPException(400)
        actor, prop = context(request, _source_resource(source_type), source_id, "refunds.create")
        if source_type == "PET_DEPOSIT":
            assert pet_refund_review_id is not None
            result = _invoke(
                lambda: flow.refunds().pet_source(
                    prop, source_id, pet_refund_review_id, actor=actor
                ),
                query=True,
            )
        else:
            result = _invoke(
                lambda: flow.refunds().usd_source(prop, source_type, source_id, actor=actor),
                query=True,
            )
            audit = _invoke(
                lambda: flow.source_audit(prop, source_type, source_id, actor=actor), query=True
            )
            result = {**result, **audit}
        if result.get("property_id") != str(prop) or result.get("source_id") != str(source_id):
            raise HTTPException(503)
        return envelope(request, result)

    @router.post("/refunds", status_code=201, dependencies=[Depends(_financial_json)])
    def create_refund(
        body: CreateRefundInput, request: Request, response: Response, idempotency_key: Key
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(
            request, _source_resource(body.source_type), body.source_id, "refunds.create"
        )
        if body.source_type == "PET_DEPOSIT":
            review_id = body.pet_refund_review_id
            assert review_id is not None
            pet_command = _invoke(
                lambda: CreatePetRefundCommand(
                    idempotency_key,
                    body.source_id,
                    review_id,
                    body.amount_usd_cents,
                    body.reason,
                )
            )
            result = _invoke(
                lambda: flow.refunds(mutation=True).create_pet(prop, pet_command, actor=actor)
            )
        else:
            usd_command = _invoke(
                lambda: CreateUsdRefundCommand(
                    idempotency_key,
                    body.source_type,
                    body.source_id,
                    body.amount_usd_cents,
                    body.reason,
                )
            )
            result = _invoke(
                lambda: flow.refunds(mutation=True).create_usd(prop, usd_command, actor=actor)
            )
        result = _refund_result(result, prop)
        header = cast(dict[str, object], result["refund"])
        response.headers["Location"] = f"/api/v1/refunds/{header['id']}"
        return envelope(request, result)

    @router.post("/refunds/{refund_id}/verified-returns", dependencies=[Depends(_financial_json)])
    def verified_return(
        refund_id: Identity, body: VerifiedReturnInput, request: Request, idempotency_key: Key
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "refund", refund_id, "refunds.correct")
        command = _invoke(
            lambda: VerifyUsdRefundReturnCommand(
                idempotency_key,
                body.returned_amount_minor,
                body.returned_at,
                body.return_method_reference,
                body.evidence_reference,
                body.reason,
            )
        )
        result = _invoke(
            lambda: flow.refunds(mutation=True).verify_usd_return(
                prop, refund_id, command, actor=actor
            )
        )
        return envelope(request, _refund_result(result, prop, expected=refund_id))

    @router.post(
        "/refunds/{refund_id}/verified-returns/{correction_id}/reverse",
        dependencies=[Depends(_financial_json)],
    )
    def reverse_correction(
        refund_id: Identity,
        correction_id: Identity,
        body: CorrectionReversalInput,
        request: Request,
        idempotency_key: Key,
    ) -> dict[str, object]:
        queries(request, set())
        actor, prop = context(request, "refund", refund_id, "refunds.corrections.reverse")
        command = _invoke(
            lambda: ReverseRefundCorrectionCommand(
                idempotency_key, body.evidence_reference, body.reason
            )
        )
        result = _invoke(
            lambda: flow.refunds(mutation=True).reverse_correction(
                prop, refund_id, correction_id, command, actor=actor
            )
        )
        return envelope(request, _refund_result(result, prop, expected=refund_id))

    return router
