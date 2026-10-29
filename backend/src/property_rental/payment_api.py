"""Protected Payment HTTP adapters; accepted services own every financial effect."""

from __future__ import annotations

import base64
import binascii
import builtins
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol, TypeVar, cast
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field
from starlette.types import Message, Receive, Scope, Send

from property_rental.api import require_billing_actor
from property_rental.browser_security import require_browser_mutation
from property_rental.configuration_api import ExchangeRateProvider, UnavailableExchangeRateProvider
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.khr_payment_confirmation import (
    ConfirmKhrPaymentCommand,
    KhrChannelEvidence,
    KhrPaymentConfirmationService,
    ManualKhrReference,
)
from property_rental.payment_confirmation import (
    ConfirmUsdPaymentCommand,
    PaymentConfirmationAuthorizationError,
    PaymentConfirmationConflictError,
    PaymentConfirmationInvalidError,
    PaymentConfirmationKeyReused,
    PaymentConfirmationNotFoundError,
    PaymentConfirmationService,
    PaymentConfirmationUnavailableError,
    _instant,
    _text,
    _uuid,
)
from property_rental.payment_read import (
    SUMMARY_MAX_DAYS,
    PaymentFilters,
    PaymentPage,
    PaymentReadAuthorizationError,
    PaymentReadInvalidError,
    PaymentReadNotFoundError,
    PaymentReadService,
    PaymentReadUnavailableError,
    late_charge_card,
    receipt_lines,
    summarize_period,
)
from property_rental.receive_payment import (
    PaysTarget,
    ReceivePaymentChanged,
    ReceivePaymentCommand,
    ReceivePaymentLeftWhileOwing,
    ReceivePaymentService,
    ReceivePaymentTooMany,
    read_payable,
)
from property_rental.settings import Settings


def _identity(value: UUID) -> UUID:
    _uuid(value)
    return value


def _evidence(value: str) -> str:
    _text(value, 2000)
    return value


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
            value,
        )
        is None
    ):
        raise ValueError("An explicit RFC3339 timestamp is required")
    return _instant(datetime.fromisoformat(value))


Identity = Annotated[UUID, AfterValidator(_identity)]
Evidence = Annotated[
    str, Field(strict=True, min_length=1, max_length=500), AfterValidator(_evidence)
]
Memo = Annotated[str, Field(strict=True, min_length=1, max_length=2000), AfterValidator(_evidence)]
Instant = Annotated[datetime, BeforeValidator(_timestamp)]
MinorUnits = Annotated[int, Field(strict=True, gt=0, le=9_000_000_000_000_000)]
# Rates travel as exact decimal strings, never JSON floating point.
Rate = Annotated[
    str, Field(strict=True, max_length=21, pattern=r"^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$")
]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UsdAmount(StrictInput):
    currency: Literal["USD"]
    minor_units: MinorUnits


class KhrAmount(StrictInput):
    currency: Literal["KHR"]
    minor_units: MinorUnits


class ManualReferenceInput(StrictInput):
    reference_rate_khr_per_usd: Rate
    source_reference: Evidence
    applicable_at: Instant
    fallback_reason: Evidence

    def command(self) -> ManualKhrReference:
        return ManualKhrReference(
            Decimal(self.reference_rate_khr_per_usd),
            self.source_reference,
            self.applicable_at,
            self.fallback_reason,
        )


class ChannelEvidenceInput(StrictInput):
    transaction_reference: Evidence
    confirmed_at: Instant
    actual_currency: Literal["KHR"] | None = None
    actual_amount_minor: MinorUnits | None = None
    actual_usd_value_cents: MinorUnits | None = None
    actual_rate_khr_per_usd: Rate | None = None

    def command(self) -> KhrChannelEvidence:
        return KhrChannelEvidence(
            self.transaction_reference,
            self.confirmed_at,
            self.actual_currency,
            self.actual_amount_minor,
            self.actual_usd_value_cents,
            Decimal(self.actual_rate_khr_per_usd)
            if self.actual_rate_khr_per_usd is not None
            else None,
        )


class PaymentInput(StrictInput):
    payer_customer_id: Identity
    payment_method_id: Identity
    received_at: Instant
    evidence_reference: Evidence
    payment_scope_kind: Literal["NORMAL_CUSTOMER", "THIRD_PARTY_IDENTIFIED"] = "NORMAL_CUSTOMER"
    lease_id: Identity | None = None
    identified_invoice_id: Identity | None = None
    identified_late_payment_charge_id: Identity | None = None
    payer_intent_memo: Memo | None = None
    channel_transaction_reference: Evidence | None = None


class UsdPaymentInput(PaymentInput):
    amount: UsdAmount

    def command(self, key: UUID) -> ConfirmUsdPaymentCommand:
        return ConfirmUsdPaymentCommand(
            key,
            self.payer_customer_id,
            self.payment_method_id,
            self.amount.minor_units,
            self.received_at,
            self.evidence_reference,
            self.payment_scope_kind,
            self.lease_id,
            self.identified_invoice_id,
            self.identified_late_payment_charge_id,
            self.payer_intent_memo,
            self.channel_transaction_reference,
        )


class OwnMoneyInput(StrictInput):
    """V1-061 (DL-112): money a Customer pays for their own Reservation or Lease, in USD. The
    payer is the Reservation's Customer or the Lease's Primary Tenant, so the screen names none."""

    payment_method_id: Identity
    received_at: Instant
    evidence_reference: Evidence
    payer_intent_memo: Memo | None = None
    amount: UsdAmount

    def intent(self, key: UUID, payer_customer_id: UUID) -> dict[str, object]:
        return ConfirmUsdPaymentCommand(
            key,
            payer_customer_id,
            self.payment_method_id,
            self.amount.minor_units,
            self.received_at,
            self.evidence_reference,
            payer_intent_memo=self.payer_intent_memo,
        ).intent()


class KhrPaymentInput(PaymentInput):
    amount: KhrAmount
    usd_accounting_amount: UsdAmount
    manual_reference: ManualReferenceInput | None = None
    channel_evidence: ChannelEvidenceInput | None = None

    def command(self, key: UUID) -> ConfirmKhrPaymentCommand:
        return ConfirmKhrPaymentCommand(
            key,
            self.payer_customer_id,
            self.payment_method_id,
            self.amount.minor_units,
            self.usd_accounting_amount.minor_units,
            self.received_at,
            self.evidence_reference,
            self.payment_scope_kind,
            self.lease_id,
            self.identified_invoice_id,
            self.identified_late_payment_charge_id,
            self.payer_intent_memo,
            self.channel_transaction_reference,
            self.manual_reference.command() if self.manual_reference is not None else None,
            self.channel_evidence.command() if self.channel_evidence is not None else None,
        )


Confirmation = ConfirmUsdPaymentCommand | ConfirmKhrPaymentCommand


class PaysTargetInput(StrictInput):
    """One tick on Receive payment: an Invoice or a late-payment charge and what it gets."""

    invoice_id: Identity | None = None
    late_payment_charge_id: Identity | None = None
    amount_usd_cents: MinorUnits

    def command(self) -> PaysTarget:
        if (self.invoice_id is None) == (self.late_payment_charge_id is None):
            raise PaymentConfirmationInvalidError("A tick names an Invoice or a charge")
        if self.invoice_id is not None:
            return PaysTarget("INVOICE", self.invoice_id, self.amount_usd_cents)
        assert self.late_payment_charge_id is not None
        return PaysTarget("LATE_PAYMENT_CHARGE", self.late_payment_charge_id, self.amount_usd_cents)


class PaysInput(StrictInput):
    """What the money pays (DL-077): the oldest-first ticks shown, or what the payer named."""

    mode: Literal["OLDEST_FIRST", "NAMED"]
    targets: Annotated[list[PaysTargetInput], Field(max_length=100)]

    def command(self, confirmation: Confirmation) -> ReceivePaymentCommand:
        return ReceivePaymentCommand(
            confirmation, self.mode, tuple(target.command() for target in self.targets)
        )


class ReceiveUsdPaymentInput(UsdPaymentInput):
    pays: PaysInput


class ReceiveKhrPaymentInput(KhrPaymentInput):
    pays: PaysInput


class PaymentFlow(Protocol):
    def list(
        self,
        property_id: UUID,
        page: PaymentPage,
        filters: PaymentFilters,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...
    def get(self, payment_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]: ...
    def confirm(
        self, property_id: UUID, command: Confirmation, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def receive(
        self, property_id: UUID, command: ReceivePaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def payable(
        self, property_id: UUID, customer_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def summary(
        self, property_id: UUID, start: date, end: date, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def receipt_lines(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def late_charge_card(
        self, property_id: UUID, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class PostgresPaymentFlow:
    database_url: str | None
    financial_database_url: str | None
    exchange_rate_provider: ExchangeRateProvider | None = None

    def _reader(self) -> PaymentReadService:
        if self.database_url is None:
            raise PaymentReadUnavailableError("Payment reads are unavailable")
        return PaymentReadService(self.database_url)

    def list(
        self,
        property_id: UUID,
        page: PaymentPage,
        filters: PaymentFilters,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]:
        result = self._reader().list(property_id, page, filters, actor=actor)
        return {
            **result,
            "items": self._with_evidence(
                property_id, cast(list[dict[str, object]], result["items"])
            ),
        }

    def _with_evidence(
        self, property_id: UUID, items: builtins.list[dict[str, object]]
    ) -> builtins.list[dict[str, object]]:
        if not items:
            return []
        if len(items) > 100:
            raise PaymentReadUnavailableError("Payment evidence is unavailable")
        identities = [UUID(str(cast(dict[str, object], item["payment"])["id"])) for item in items]
        try:
            with psycopg.connect(self._reader().database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                rows = connection.execute(
                    "SELECT payment_id,received_at,evidence_reference "
                    "FROM app.payment_receipt_evidence "
                    "WHERE property_id=%s AND payment_id=ANY(%s::uuid[])",
                    (property_id, identities),
                ).fetchall()
        except psycopg.Error as exc:
            raise PaymentReadUnavailableError("Payment evidence is unavailable") from exc
        evidence = {
            str(row[0]): {"received_at": row[1], "evidence_reference": row[2]} for row in rows
        }
        if set(evidence) != {str(identity) for identity in identities}:
            raise PaymentReadUnavailableError("Payment evidence is unavailable")
        # These two original facts are immutable. A separate bounded read cannot
        # mix a later mutable balance into the accepted reader's coherent snapshot.
        return [
            {**item, "confirmation_evidence": evidence[str(identity)]}
            for item, identity in zip(items, identities, strict=True)
        ]

    def get(self, payment_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]:
        _uuid(payment_id)
        # Locate ONLY within the provider-established allowed Properties; callers
        # cannot supply scope. Then the accepted reader freshly checks the human
        # and exact Property, and retrieves the exact immutable Payment identity.
        try:
            properties = sorted(
                {
                    UUID(value)
                    for grant in actor.capability_grants
                    if grant.capability == "payments.read"
                    for value in grant.property_ids
                }
            )
            for property_id in properties:
                _uuid(property_id)
        except ValueError as exc:
            raise PaymentReadAuthorizationError("Payment read is not authorized") from exc
        if not properties:
            raise PaymentReadNotFoundError("Payment was not found")
        reader = self._reader()
        try:
            with psycopg.connect(reader.database_url, connect_timeout=3) as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL lock_timeout='3000ms'")
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                row = connection.execute(
                    "SELECT property_id FROM app.payments "
                    "WHERE id=%s AND property_id=ANY(%s::uuid[])",
                    (payment_id, properties),
                ).fetchone()
        except psycopg.Error as exc:
            raise PaymentReadUnavailableError("Payment read is unavailable") from exc
        if row is None:
            raise PaymentReadNotFoundError("Payment was not found")
        property_id = cast(UUID, row[0])
        result = reader.get(property_id, payment_id, actor=actor)
        return self._with_evidence(property_id, [result])[0]

    def confirm(
        self, property_id: UUID, command: Confirmation, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        if self.financial_database_url is None:
            raise PaymentConfirmationUnavailableError("Payment confirmation is unavailable")
        if isinstance(command, ConfirmKhrPaymentCommand):
            return KhrPaymentConfirmationService(
                self.financial_database_url,
                self.exchange_rate_provider or UnavailableExchangeRateProvider(),
            ).confirm_khr(property_id, command, actor=actor)
        return PaymentConfirmationService(self.financial_database_url).confirm_usd(
            property_id,
            command,
            actor=actor,
        )

    def receive(
        self, property_id: UUID, command: ReceivePaymentCommand, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        if self.financial_database_url is None:
            raise PaymentConfirmationUnavailableError("Receive payment is unavailable")
        return ReceivePaymentService(
            self.financial_database_url,
            self.exchange_rate_provider or UnavailableExchangeRateProvider(),
        ).receive(property_id, command, actor=actor)

    def payable(
        self, property_id: UUID, customer_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        if self.database_url is None:
            raise PaymentConfirmationUnavailableError("What is owed is unavailable")
        return read_payable(self.database_url, property_id, customer_id, actor=actor)

    def summary(
        self, property_id: UUID, start: date, end: date, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return summarize_period(self._reader(), property_id, start, end, actor=actor)

    def receipt_lines(
        self, property_id: UUID, payment_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]:
        return receipt_lines(self._reader(), property_id, payment_id, actor=actor)

    def late_charge_card(
        self, property_id: UUID, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object] | None:
        return late_charge_card(self._reader(), property_id, invoice_id, actor=actor)


def payment_key_reused_response(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was already used for different input.",
                "fields": [],
                "rule_ids": ["API-016"],
                "current_version": None,
            },
            "meta": {"request_id": request.state.request_id},
        },
        headers={"X-Request-ID": request.state.request_id},
    )


def receive_refused_response(
    request: Request, error: PaymentConfirmationConflictError
) -> JSONResponse:
    """The two Receive payment refusals the screen explains in its own words (DL-077)."""
    if isinstance(error, ReceivePaymentLeftWhileOwing):
        code, message = (
            "RECEIVE_PAYMENT_LEFT_WHILE_OWING",
            "Money is left while other Invoices are still unpaid. Tick another Invoice.",
        )
    elif isinstance(error, ReceivePaymentTooMany):
        code, message = (
            "RECEIVE_PAYMENT_TOO_MANY",
            "This Customer owes more than 100 items. Name what this money pays.",
        )
    else:
        code, message = (
            "RECEIVE_PAYMENT_CHANGED",
            "What this money pays changed. Read the Customer's Invoices again.",
        )
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": [],
                "rule_ids": ["DL-077"],
                "current_version": None,
            },
            "meta": {"request_id": request.state.request_id},
        },
        headers={"X-Request-ID": request.state.request_id, "Cache-Control": "private, no-store"},
    )


T = TypeVar("T")


def _invoke(call: Callable[[], T], *, hide: bool = False) -> T:
    try:
        return call()
    except (
        PaymentConfirmationKeyReused,
        ReceivePaymentChanged,
        ReceivePaymentLeftWhileOwing,
        ReceivePaymentTooMany,
    ):
        raise
    except (PaymentReadNotFoundError, PaymentConfirmationNotFoundError) as exc:
        raise HTTPException(404) from exc
    except (PaymentReadAuthorizationError, PaymentConfirmationAuthorizationError) as exc:
        raise HTTPException(404 if hide else 403) from exc
    except (PaymentReadInvalidError, PaymentConfirmationInvalidError) as exc:
        raise HTTPException(422) from exc
    except PaymentConfirmationConflictError as exc:
        raise HTTPException(409) from exc
    except (PaymentReadUnavailableError, PaymentConfirmationUnavailableError) as exc:
        raise HTTPException(503) from exc


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(401)
    try:
        _uuid(UUID(actor.actor_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(403) from exc
    require_billing_actor(request, actor)
    return actor


def _authorize(
    actor: AuthenticatedActor, property_id: UUID, capability: str, *, hide: bool = False
) -> None:
    if not is_authorized(actor, AuthorizationRequirement(capability, str(property_id))):
        raise HTTPException(404 if hide else 403)


def _queries(request: Request, allowed: set[str]) -> None:
    if any(
        key not in allowed or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        raise HTTPException(400)


def _cursor(value: object) -> str | None:
    if value is None:
        return None
    return base64.urlsafe_b64encode(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


def _page(limit: int, cursor: str | None) -> PaymentPage:
    if cursor is None:
        return PaymentPage(limit)
    try:
        if len(cursor) > 256 or not cursor.isascii():
            raise ValueError
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(value, dict)
            or set(value) != {"payment_date", "id"}
            or _cursor(value) != cursor
        ):
            raise ValueError
        day, identity = value["payment_date"], value["id"]
        if not isinstance(day, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
            raise ValueError
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError
        return PaymentPage(limit, date.fromisoformat(day), UUID(identity))
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HTTPException(400) from exc


MAX_PAYMENT_BODY_BYTES = 32_768


class PaymentRequestRoute(APIRoute):
    """Bound incoming bytes before FastAPI buffers or decodes a Payment body."""

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
                if received > MAX_PAYMENT_BODY_BYTES:
                    # Reject before forwarding this chunk to Request.body(). Never
                    # drain the remainder or trust a missing/incorrect Content-Length.
                    raise HTTPException(400)
            return message

        await super().handle(scope, bounded_receive, send)


async def _strict_json(request: Request) -> None:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        body = await request.body()
        if len(body) > MAX_PAYMENT_BODY_BYTES:
            raise ValueError
        # JSON bytes otherwise auto-detect UTF-16/32, contrary to API-002.
        json.loads(body.decode("utf-8"), object_pairs_hook=pairs)
    except ValueError as exc:
        raise HTTPException(400) from exc


def create_payment_router(
    resolver: ActorResolver, flow: PaymentFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["payments"], route_class=PaymentRequestRoute)

    @router.get("/properties/{property_id}/payments")
    def list_payments(
        property_id: Identity,
        request: Request,
        customer_id: Identity | None = None,
        status_filter: Annotated[
            Literal["RECEIVED", "REVERSED"] | None, Query(alias="status")
        ] = None,
        payment_method_id: Identity | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query(max_length=256)] = None,
        sort: Literal["-payment_date"] = "-payment_date",
    ) -> dict[str, object]:
        del sort
        actor = _actor(request, resolver)
        _authorize(actor, property_id, "payments.read")
        bind_financial_property(request, property_id)
        _queries(request, {"customer_id", "status", "payment_method_id", "limit", "cursor", "sort"})
        page = _page(limit, cursor)
        if "limit" in request.query_params and request.query_params["limit"] != str(limit):
            raise HTTPException(400)
        result = _invoke(
            lambda: flow.list(
                property_id,
                page,
                PaymentFilters(customer_id, status_filter, payment_method_id),
                actor=actor,
            )
        )
        return {
            "data": result["items"],
            "page": {"limit": limit, "next_cursor": _cursor(result["next_cursor"])},
            "meta": financial_metadata(request),
        }

    @router.get("/properties/{property_id}/payments/payable")
    def payable(
        property_id: Identity, customer_id: Identity, request: Request
    ) -> dict[str, object]:
        """V1-058 R5c-1: the Receive payment list, in the order oldest-first ticks pay it."""
        actor = _actor(request, resolver)
        _authorize(actor, property_id, "payments.record")
        bind_financial_property(request, property_id)
        _queries(request, {"customer_id"})
        result = _invoke(lambda: flow.payable(property_id, customer_id, actor=actor))
        return {"data": result, "meta": financial_metadata(request)}

    @router.get("/properties/{property_id}/payments/summary")
    def summary(
        property_id: Identity,
        request: Request,
        start: Annotated[date, Query(alias="from")],
        end: Annotated[date, Query(alias="to")],
    ) -> dict[str, object]:
        """V1-058 R5c-3a: the Payments page cards and list for one period."""
        actor = _actor(request, resolver)
        _authorize(actor, property_id, "payments.read")
        bind_financial_property(request, property_id)
        _queries(request, {"from", "to"})
        if start > end or (end - start).days > SUMMARY_MAX_DAYS:
            raise HTTPException(422)
        result = _invoke(lambda: flow.summary(property_id, start, end, actor=actor))
        return {"data": result, "meta": financial_metadata(request)}

    @router.get("/properties/{property_id}/payments/{payment_id}/receipt-lines")
    def payment_receipt_lines(
        property_id: Identity, payment_id: Identity, request: Request
    ) -> dict[str, object]:
        """V1-058 R5c-3a: what the printed Receipt shows for one payment."""
        actor = _actor(request, resolver)
        _authorize(actor, property_id, "receipts.read")
        bind_financial_property(request, property_id)
        _queries(request, set())
        result = _invoke(
            lambda: flow.receipt_lines(property_id, payment_id, actor=actor), hide=True
        )
        return {"data": result, "meta": financial_metadata(request)}

    @router.get("/properties/{property_id}/invoices/{invoice_id}/late-charge")
    def invoice_late_charge(
        property_id: Identity, invoice_id: Identity, request: Request
    ) -> dict[str, object]:
        """V1-058 R5d: the late-payment card of one Invoice; data is null without a charge."""
        actor = _actor(request, resolver)
        _authorize(actor, property_id, "invoices.read")
        bind_financial_property(request, property_id)
        _queries(request, set())
        result = _invoke(lambda: flow.late_charge_card(property_id, invoice_id, actor=actor))
        return {"data": result, "meta": financial_metadata(request)}

    @router.get("/payments/{payment_id}")
    def get_payment(payment_id: Identity, request: Request) -> dict[str, object]:
        actor = _actor(request, resolver)
        _queries(request, set())
        result = _invoke(lambda: flow.get(payment_id, actor=actor), hide=True)
        payment = cast(dict[str, object], result["payment"])
        _authorize(actor, UUID(str(payment["property_id"])), "payments.read", hide=True)
        if str(payment["id"]) != str(payment_id):
            raise HTTPException(404)
        bind_financial_property(request, UUID(str(payment["property_id"])))
        return {"data": result, "meta": financial_metadata(request)}

    @router.post(
        "/properties/{property_id}/payments", status_code=201, dependencies=[Depends(_strict_json)]
    )
    def confirm_payment(
        property_id: Identity,
        body: UsdPaymentInput | KhrPaymentInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _actor(request, resolver)
        _queries(request, set())
        _authorize(actor, property_id, "payments.record")
        for header in ("Idempotency-Key", "Origin", "X-CSRF-Token", "X-Billing-Actor-ID"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(400)
        if not request.headers.get("X-CSRF-Token"):
            raise HTTPException(403)
        require_browser_mutation(request, settings)
        if isinstance(body, KhrPaymentInput) and body.manual_reference is not None:
            _authorize(actor, property_id, "exchange_rates.manage")
        bind_financial_property(request, property_id)
        command = _invoke(lambda: body.command(idempotency_key))
        result = _invoke(lambda: flow.confirm(property_id, command, actor=actor))
        payment = cast(dict[str, object], result["payment"])
        response.headers["Location"] = f"/api/v1/payments/{payment['id']}"
        return {"data": result, "meta": financial_metadata(request)}

    @router.post(
        "/properties/{property_id}/payments/receive",
        status_code=201,
        dependencies=[Depends(_strict_json)],
        response_model=None,
    )
    def receive_payment(
        property_id: Identity,
        body: ReceiveUsdPaymentInput | ReceiveKhrPaymentInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> dict[str, object] | JSONResponse:
        """V1-058 R5c-1 (DL-077): the payment, its Receipt and what it pays, saved together."""
        actor = _actor(request, resolver)
        _queries(request, set())
        _authorize(actor, property_id, "payments.record")
        if body.pays.targets:
            _authorize(actor, property_id, "payments.allocate")
        for header in ("Idempotency-Key", "Origin", "X-CSRF-Token", "X-Billing-Actor-ID"):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(400)
        if not request.headers.get("X-CSRF-Token"):
            raise HTTPException(403)
        require_browser_mutation(request, settings)
        if isinstance(body, ReceiveKhrPaymentInput) and body.manual_reference is not None:
            _authorize(actor, property_id, "exchange_rates.manage")
        bind_financial_property(request, property_id)
        command = _invoke(lambda: body.pays.command(body.command(idempotency_key)))
        try:
            result = _invoke(lambda: flow.receive(property_id, command, actor=actor))
        except (
            ReceivePaymentChanged,
            ReceivePaymentLeftWhileOwing,
            ReceivePaymentTooMany,
        ) as error:
            return receive_refused_response(request, error)
        payment = cast(dict[str, object], result["payment"])
        response.headers["Location"] = f"/api/v1/payments/{payment['id']}"
        return {"data": result, "meta": financial_metadata(request)}

    return router
