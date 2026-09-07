"""Explicit Allocation/Receipt HTTP commands over the accepted financial services."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, TypeVar, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import AfterValidator, Field
from starlette.types import Message, Receive, Scope, Send

from property_rental.allocation_read import AllocationHistoryPage, AllocationReadService
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.payment_allocation import (
    AllocationAuthorizationError,
    AllocationConflictError,
    AllocationIdempotencyKeyReused,
    AllocationInvalidError,
    AllocationNotFoundError,
    AllocationUnavailableError,
    PaymentAllocationService,
    PostAllocationsCommand,
    ReverseAllocationCommand,
    ReversePaymentCommand,
    _reason,
    _uuid,
)
from property_rental.payment_api import (
    Identity,
    StrictInput,
    _actor,
    _authorize,
    _cursor,
    _queries,
)
from property_rental.receipt import (
    ReceiptAuthorizationError,
    ReceiptIdempotencyKeyReused,
    ReceiptInvalidError,
    ReceiptNotFoundError,
    ReceiptService,
    ReceiptUnavailableError,
    ReprintReceiptCommand,
)
from property_rental.settings import Settings


def _normalized_reason(value: str) -> str:
    _reason(value)
    return value


Resource = Literal["payment", "allocation", "receipt"]
Reason = Annotated[
    str, Field(strict=True, min_length=1, max_length=1000), AfterValidator(_normalized_reason)
]
MAX_ALLOCATION_RECEIPT_BODY_BYTES = 262_144
T = TypeVar("T")


class AllocationInput(StrictInput):
    intent: Annotated[dict[str, object], Field(strict=True)]


class ReversalInput(StrictInput):
    reason: Reason


class PaymentReversalInput(ReversalInput):
    expected_status: Literal["RECEIVED"]


class ReprintInput(ReversalInput):
    delivery_reference: Annotated[str, Field(strict=True, min_length=1, max_length=500)] | None = (
        None
    )


class AllocationReceiptFlow(Protocol):
    def resolve(
        self,
        resource: Resource,
        identity: UUID,
        capability: str,
        *,
        actor: AuthenticatedActor,
    ) -> UUID: ...
    def proposal(
        self, prop: UUID, payment: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def history(
        self,
        prop: UUID,
        payment: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
        allocation_id: UUID | None,
    ) -> dict[str, object]: ...
    def post(
        self,
        prop: UUID,
        payment: UUID,
        command: PostAllocationsCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def reverse_allocation(
        self,
        prop: UUID,
        allocation: UUID,
        command: ReverseAllocationCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def reverse_payment(
        self,
        prop: UUID,
        payment: UUID,
        command: ReversePaymentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def receipt(
        self, prop: UUID, identity: UUID, *, actor: AuthenticatedActor, by_payment: bool
    ) -> dict[str, object]: ...
    def receipt_history(
        self,
        prop: UUID,
        receipt: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def reprint(
        self,
        prop: UUID,
        receipt: UUID,
        command: ReprintReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


_SCOPE_QUERIES = {
    "payment": "SELECT property_id FROM app.payments WHERE id=%s AND property_id=ANY(%s::uuid[])",
    "allocation": (
        "SELECT payment.property_id FROM app.payment_allocations allocation "
        "JOIN app.payments payment ON payment.id=allocation.payment_id "
        "WHERE allocation.id=%s AND payment.property_id=ANY(%s::uuid[])"
    ),
    "receipt": (
        "SELECT payment.property_id FROM app.receipts receipt "
        "JOIN app.payments payment ON payment.id=receipt.payment_id "
        "WHERE receipt.id=%s AND payment.property_id=ANY(%s::uuid[])"
    ),
}


@dataclass(frozen=True, slots=True)
class PostgresAllocationReceiptFlow:
    database_url: str | None
    financial_database_url: str | None

    def _runtime(self) -> str:
        if self.database_url is None:
            raise AllocationUnavailableError("Financial reads are unavailable")
        return self.database_url

    def _financial(self) -> str:
        if self.financial_database_url is None:
            raise AllocationUnavailableError("Financial commands are unavailable")
        return self.financial_database_url

    def resolve(
        self,
        resource: Resource,
        identity: UUID,
        capability: str,
        *,
        actor: AuthenticatedActor,
    ) -> UUID:
        _uuid(identity)
        try:
            actor_id = UUID(actor.actor_id)
            _uuid(actor_id)
            properties = sorted(
                {
                    UUID(value)
                    for grant in actor.capability_grants
                    if grant.capability == capability
                    for value in grant.property_ids
                }
            )
            for prop in properties:
                _uuid(prop)
        except (ValueError, TypeError, AttributeError) as exc:
            raise AllocationAuthorizationError("Financial action is not authorized") from exc
        if not properties:
            raise AllocationNotFoundError("Financial resource was not found")
        try:
            with psycopg.connect(self._runtime(), connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                fresh = connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM app.user_accounts account "
                    "JOIN app.actor_identities identity ON identity.actor_id=account.actor_id "
                    "WHERE account.actor_id=%s AND account.lifecycle_state='active' "
                    "AND identity.identity_kind='HUMAN')",
                    (actor_id,),
                ).fetchone()
                if fresh != (True,):
                    raise AllocationAuthorizationError("Financial actor is not active")
                row = connection.execute(
                    _SCOPE_QUERIES[resource], (identity, properties)
                ).fetchone()
        except psycopg.Error as exc:
            if exc.sqlstate == "42501":
                raise AllocationAuthorizationError("Financial action is not authorized") from exc
            raise AllocationUnavailableError("Financial resource is unavailable") from exc
        if row is None:
            raise AllocationNotFoundError("Financial resource was not found")
        return cast(UUID, row[0])

    def proposal(
        self, prop: UUID, payment: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return AllocationReadService(self._runtime()).proposal(prop, payment, actor=actor)

    def history(
        self,
        prop: UUID,
        payment: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
        allocation_id: UUID | None,
    ) -> dict[str, object]:
        return AllocationReadService(self._runtime()).history(
            prop, payment, page, actor=actor, allocation_id=allocation_id
        )

    def post(
        self,
        prop: UUID,
        payment: UUID,
        command: PostAllocationsCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentAllocationService(self._runtime(), self._financial()).post(
            prop, payment, command, actor=actor
        )

    def reverse_allocation(
        self,
        prop: UUID,
        allocation: UUID,
        command: ReverseAllocationCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentAllocationService(self._runtime(), self._financial()).reverse_allocation(
            prop, allocation, command, actor=actor
        )

    def reverse_payment(
        self,
        prop: UUID,
        payment: UUID,
        command: ReversePaymentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return PaymentAllocationService(self._runtime(), self._financial()).reverse_payment(
            prop, payment, command, actor=actor
        )

    def receipt(
        self, prop: UUID, identity: UUID, *, actor: AuthenticatedActor, by_payment: bool
    ) -> dict[str, object]:
        # The accepted receipt read locks Payment FOR SHARE. Retain its normal
        # transaction; a READ ONLY wrapper would reject that lock. This empty
        # mutation URL is deliberately unusable: reads never borrow a writer.
        reader = ReceiptService(self._runtime(), "")
        if by_payment:
            return reader.for_payment(prop, identity, actor=actor)
        return reader.get(prop, identity, actor=actor)

    def receipt_history(
        self,
        prop: UUID,
        receipt: UUID,
        page: AllocationHistoryPage,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return ReceiptService(self._runtime(), "").history(
            prop, receipt, actor=actor, after_id=page.after_id, limit=page.limit
        )

    def reprint(
        self,
        prop: UUID,
        receipt: UUID,
        command: ReprintReceiptCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        return ReceiptService(self._runtime(), self._financial()).reprint(
            prop, receipt, command, actor=actor
        )


def _invoke(call: Callable[[], T], *, query: bool = False) -> T:
    try:
        return call()
    except (AllocationIdempotencyKeyReused, ReceiptIdempotencyKeyReused):
        raise
    except (
        AllocationNotFoundError,
        ReceiptNotFoundError,
        AllocationAuthorizationError,
        ReceiptAuthorizationError,
    ) as exc:
        # All these routes address opaque objects. Do not disclose existence.
        raise HTTPException(404) from exc
    except (AllocationInvalidError, ReceiptInvalidError) as exc:
        raise HTTPException(400 if query else 422) from exc
    except AllocationConflictError as exc:
        raise HTTPException(409) from exc
    except (AllocationUnavailableError, ReceiptUnavailableError) as exc:
        raise HTTPException(503) from exc


def _history_page(
    limit: int,
    cursor: str | None,
    *,
    resource_id: UUID,
    allocation_id: UUID | None = None,
    receipt: bool = False,
) -> AllocationHistoryPage:
    if cursor is None:
        return AllocationHistoryPage(limit)
    try:
        if len(cursor) > 512 or not cursor.isascii():
            raise ValueError
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        binding = (
            {"receipt_id": str(resource_id)}
            if receipt
            else {
                "payment_id": str(resource_id),
                "allocation_id": str(allocation_id) if allocation_id is not None else None,
            }
        )
        if (
            not isinstance(value, dict)
            or set(value) != {*binding, "after_id"}
            or _cursor(value) != cursor
        ):
            raise ValueError
        if any(value[key] != expected for key, expected in binding.items()):
            raise ValueError
        identity = value["after_id"]
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError
        return AllocationHistoryPage(limit, UUID(identity))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HTTPException(400) from exc


class AllocationReceiptRequestRoute(APIRoute):
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] != "POST":
            await super().handle(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_ALLOCATION_RECEIPT_BODY_BYTES:
                    raise HTTPException(400)
            return message

        try:
            await super().handle(scope, bounded_receive, send)
        except (RecursionError, UnicodeError) as exc:
            raise HTTPException(400) from exc


async def _strict_json(request: Request) -> None:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid_constant(_: str) -> object:
        raise ValueError

    try:
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise ValueError
        body = await request.body()
        if len(body) > MAX_ALLOCATION_RECEIPT_BODY_BYTES:
            raise ValueError
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400) from exc


def _mutation(request: Request, settings: Settings) -> None:
    for header in ("Idempotency-Key", "Origin", "X-CSRF-Token", "X-Billing-Actor-ID"):
        if len(request.headers.getlist(header)) > 1:
            raise HTTPException(400)
    if not request.headers.get("X-CSRF-Token"):
        raise HTTPException(403)
    require_browser_mutation(request, settings)


def create_allocation_receipt_router(
    resolver: ActorResolver, flow: AllocationReceiptFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        tags=["allocations", "receipts"],
        route_class=AllocationReceiptRequestRoute,
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

    @router.get("/payments/{payment_id}/allocation-proposal")
    def proposal(payment_id: Identity, request: Request) -> dict[str, object]:
        _queries(request, set())
        actor, prop = context(request, "payment", payment_id, "payments.allocate")
        result = _invoke(lambda: flow.proposal(prop, payment_id, actor=actor))
        if result.get("property_id") != str(prop) or result.get("payment_id") != str(payment_id):
            raise HTTPException(404)
        return envelope(request, result)

    @router.get("/payments/{payment_id}/allocations")
    def history(
        payment_id: Identity,
        request: Request,
        allocation_id: Identity | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        _queries(request, {"allocation_id", "limit", "cursor"})
        page = _history_page(limit, cursor, resource_id=payment_id, allocation_id=allocation_id)
        if "limit" in request.query_params and request.query_params["limit"] != str(limit):
            raise HTTPException(400)
        actor, prop = context(request, "payment", payment_id, "payments.read")
        result = _invoke(
            lambda: flow.history(prop, payment_id, page, actor=actor, allocation_id=allocation_id),
            query=True,
        )
        if result.get("property_id") != str(prop) or result.get("payment_id") != str(payment_id):
            raise HTTPException(404)
        data = (
            result["items"]
            if allocation_id is None
            else {"allocation": result["allocation"], "details": result["items"]}
        )
        return {
            **envelope(request, data),
            "page": {"limit": limit, "next_cursor": _cursor(result["next_cursor"])},
        }

    @router.post(
        "/payments/{payment_id}/allocations",
        status_code=201,
        dependencies=[Depends(_strict_json)],
    )
    def post(
        payment_id: Identity,
        body: AllocationInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _queries(request, set())
        actor, prop = context(request, "payment", payment_id, "payments.allocate")
        command = _invoke(lambda: PostAllocationsCommand(idempotency_key, body.intent))
        result = _invoke(lambda: flow.post(prop, payment_id, command, actor=actor))
        response.headers["Location"] = f"/api/v1/payments/{payment_id}/allocations"
        return envelope(request, result)

    @router.post(
        "/payment-allocations/{allocation_id}/reverse",
        dependencies=[Depends(_strict_json)],
    )
    def reverse_allocation(
        allocation_id: Identity,
        body: ReversalInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _queries(request, set())
        actor, prop = context(request, "allocation", allocation_id, "payments.allocations.reverse")
        command = _invoke(lambda: ReverseAllocationCommand(idempotency_key, body.reason))
        return envelope(
            request,
            _invoke(lambda: flow.reverse_allocation(prop, allocation_id, command, actor=actor)),
        )

    @router.post("/payments/{payment_id}/reverse", dependencies=[Depends(_strict_json)])
    def reverse_payment(
        payment_id: Identity,
        body: PaymentReversalInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _queries(request, set())
        actor, prop = context(request, "payment", payment_id, "payments.reverse")
        command = _invoke(
            lambda: ReversePaymentCommand(idempotency_key, body.reason, body.expected_status)
        )
        return envelope(
            request,
            _invoke(lambda: flow.reverse_payment(prop, payment_id, command, actor=actor)),
        )

    def read_receipt(
        identity: UUID,
        request: Request,
        limit: int,
        cursor: str | None,
        *,
        by_payment: bool,
    ) -> dict[str, object]:
        _queries(request, {"limit", "cursor"})
        if "limit" in request.query_params and request.query_params["limit"] != str(limit):
            raise HTTPException(400)
        actor, prop = context(
            request, "payment" if by_payment else "receipt", identity, "receipts.read"
        )
        result = _invoke(lambda: flow.receipt(prop, identity, actor=actor, by_payment=by_payment))
        receipt = cast(dict[str, object], result["receipt"])
        payment = cast(dict[str, object], result["payment"])
        if payment.get("property_id") != str(prop) or (
            payment.get("id") if by_payment else receipt.get("id")
        ) != str(identity):
            raise HTTPException(404)
        receipt_id = UUID(str(receipt["id"]))
        page = _history_page(limit, cursor, resource_id=receipt_id, receipt=True)
        history = _invoke(
            lambda: flow.receipt_history(prop, receipt_id, page, actor=actor),
            query=True,
        )
        events = cast(list[dict[str, object]], history["events"])
        next_cursor = (
            {"receipt_id": str(receipt_id), "after_id": str(events[-1]["id"])}
            if history["has_more"]
            else None
        )
        return envelope(
            request,
            {
                **result,
                "reprints": {
                    "items": events,
                    "page": {"limit": limit, "next_cursor": _cursor(next_cursor)},
                },
            },
        )

    @router.get("/payments/{payment_id}/receipt")
    def receipt_for_payment(
        payment_id: Identity,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        return read_receipt(payment_id, request, limit, cursor, by_payment=True)

    @router.get("/receipts/{receipt_id}")
    def receipt(
        receipt_id: Identity,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> dict[str, object]:
        return read_receipt(receipt_id, request, limit, cursor, by_payment=False)

    @router.post("/receipts/{receipt_id}/reprints", dependencies=[Depends(_strict_json)])
    def reprint(
        receipt_id: Identity,
        body: ReprintInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        _queries(request, set())
        actor, prop = context(request, "receipt", receipt_id, "receipts.reprint")
        command = _invoke(
            lambda: ReprintReceiptCommand(idempotency_key, body.reason, body.delivery_reference)
        )
        result = _invoke(lambda: flow.reprint(prop, receipt_id, command, actor=actor))
        return envelope(request, result)

    return router
