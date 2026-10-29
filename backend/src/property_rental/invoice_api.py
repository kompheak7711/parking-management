"""Protected Invoice resources and explicit lifecycle commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Final, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.api import require_billing_actor
from property_rental.api_refusals import (
    CLEANING_CHARGE_ALREADY_RECORDED,
    CLEANING_CHARGE_NEEDS_MOVE_OUT,
    CLEANING_CHARGE_NOT_MOVED_IN,
    CLEANING_RATE_CHANGED,
    CLEANING_RATE_NOT_SET,
    CLEANING_RATE_ZERO,
    FINAL_SETTLEMENT_CLOSED,
    HAND_BACK_ALREADY_RESOLVED,
    HAND_BACK_ASSESSMENT_CHANGED,
    HAND_BACK_INVOICE_NOT_ISSUED,
    HAND_BACK_MONTH_NOT_COVERED,
    HAND_BACK_MOVE_OUT_UNCLEAR,
    HAND_BACK_NEEDS_MOVE_OUT,
    HAND_BACK_NOT_EARLY_TERMINATION,
    HAND_BACK_NOT_MONTHLY_RENT,
    HAND_BACK_PAID_INVOICE_KEPT,
    HAND_BACK_VOID_BLOCKED,
    IDEMPOTENCY_KEY_REUSED,
    Refusal,
    RefusedRequest,
    database_refusal,
)
from property_rental.billing import SetInitialRentDueDateCommand
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.invoice import (
    DAMAGE_CHARGE_BILL_CAPABILITY,
    INVOICE_ADJUST_CAPABILITY,
    INVOICE_CREATE_CAPABILITY,
    INVOICE_ISSUE_CAPABILITY,
    INVOICE_READ_CAPABILITY,
    INVOICE_VOID_CAPABILITY,
    LEASE_READ_CAPABILITY,
    MAX_INVOICE_EXPECTED_VERSION,
    MAX_INVOICE_ITEM_QUANTITY,
    MAX_INVOICE_ITEM_UNIT_PRICE_USD_CENTS,
    MAX_INVOICE_ITEMS,
    MAX_INVOICE_PAGE_SIZE,
    ONE_TIME_CHARGE_CAPABILITIES,
    PROPERTY_MANAGE_CAPABILITY,
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    CreateItemsInvoiceDraftCommand,
    CreateServicesInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceIdempotencyKeyReused,
    InvoiceInvalidError,
    InvoiceItem,
    InvoiceLineFullyPaid,
    InvoiceNotFoundError,
    InvoicePage,
    InvoiceServiceUnavailableError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
    RecordUnitCleaningChargeCommand,
    ReplaceInvoiceDraftItemsCommand,
    ResolveHandBackRentCommand,
    ServiceInvoiceItem,
    SetOneTimeChargeDueDaysCommand,
    SetUnitCleaningRateCommand,
    VoidInvoiceCommand,
    validate_invoice_cursor,
)
from property_rental.settings import Settings

InvoiceStatus = Literal["DRAFT", "UNPAID", "PARTIALLY_PAID", "PAID", "VOID"]
InvoiceCategory = Literal[
    "RENT", "UTILITIES", "SERVICE_CHARGES", "DAMAGE_CHARGES", "MISCELLANEOUS_CHARGES"
]


class InvoiceFlow(Protocol):
    def list(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
        status_filter: str | None,
        category: str | None,
        customer_id: UUID | None,
        lease_id: UUID | None,
        limit: int,
        cursor: str | None,
        descending: bool,
    ) -> InvoicePage: ...

    def get(self, invoice_id: UUID, *, actor: AuthenticatedActor) -> dict[str, object]: ...

    def property_for_invoice(self, invoice_id: UUID) -> UUID: ...

    def create_draft(
        self,
        property_id: UUID,
        command: CreateInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def correct_draft(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: CorrectInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def create_items_draft(
        self,
        property_id: UUID,
        command: CreateItemsInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def create_services_draft(
        self,
        property_id: UUID,
        command: CreateServicesInvoiceDraftCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def replace_draft_items(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: ReplaceInvoiceDraftItemsCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def issue(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: IssueInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def adjust(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: AdjustInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def void(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: VoidInvoiceCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def record_one_time_charge(
        self,
        property_id: UUID,
        command: RecordOneTimeChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def set_one_time_charge_due_days(
        self,
        property_id: UUID,
        command: SetOneTimeChargeDueDaysCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def get_one_time_charge_due_days(
        self,
        property_id: UUID,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def set_initial_rent_due_date(
        self,
        property_id: UUID,
        command: SetInitialRentDueDateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


class UnavailableInvoiceFlow:
    def __getattr__(self, _: str) -> object:
        raise InvoiceServiceUnavailableError("Invoice persistence is unavailable")


class AuthorizedObligationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorized_nonrecurring_obligation_id: UUID


class DraftCorrectionInput(AuthorizedObligationInput):
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class InvoiceItemInput(BaseModel):
    """DL-103: one typed item; the server works out the amount as quantity times unit price."""

    model_config = ConfigDict(extra="forbid")

    charge_id: UUID
    description: str = Field(min_length=1, max_length=1000, pattern=r"^\S(?:.*\S)?$")
    quantity: int = Field(strict=True, ge=1, le=MAX_INVOICE_ITEM_QUANTITY)
    unit_price_usd_cents: int = Field(strict=True, ge=1, le=MAX_INVOICE_ITEM_UNIT_PRICE_USD_CENTS)


class ItemsInvoiceDraftInput(BaseModel):
    """DL-103: one Miscellaneous Invoice of 1 to 20 items, with one reason and one approval."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    lease_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")
    evidence_reference: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")
    items: list[InvoiceItemInput] = Field(min_length=1, max_length=MAX_INVOICE_ITEMS)


class ServiceInvoiceItemInput(BaseModel):
    """DL-115 (I): one Regular service and How many; the price comes from Settings."""

    model_config = ConfigDict(extra="forbid")

    charge_id: UUID
    regular_service_id: UUID
    quantity: int = Field(strict=True, ge=1, le=MAX_INVOICE_ITEM_QUANTITY)


class ServicesInvoiceDraftInput(BaseModel):
    """DL-115 (I): a Services Invoice of 1 to 20 Regular services."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    lease_id: UUID | None = None
    items: list[ServiceInvoiceItemInput] = Field(min_length=1, max_length=MAX_INVOICE_ITEMS)


class InvoiceItemsChangeInput(ItemsInvoiceDraftInput):
    change_reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


def _invoice_items(items: list[InvoiceItemInput]) -> tuple[InvoiceItem, ...]:
    return tuple(
        InvoiceItem(item.charge_id, item.description, item.quantity, item.unit_price_usd_cents)
        for item in items
    )


class IssueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_date: date | None = None
    due_date_reason: str | None = Field(
        default=None, min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$"
    )


class OneTimeChargeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_id: UUID
    category: Literal["DAMAGE_CHARGES", "MISCELLANEOUS_CHARGES"]
    customer_id: UUID
    lease_id: UUID | None = None
    inspection_damage_finding_id: UUID | None = None
    description: str = Field(min_length=1, max_length=1000, pattern=r"^\S(?:.*\S)?$")
    amount_usd_cents: int = Field(ge=1, le=9_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")
    evidence_reference: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class InitialRentDueDateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    override_id: UUID
    due_date: date
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class OneTimeChargeDueDaysInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=90)
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class MoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"]
    minor_units: int = Field(strict=True, gt=0, le=9_000_000_000_000_000)


class AdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_line_id: UUID
    adjustment_type: AdjustmentType
    amount: MoneyInput
    source_reference: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class VoidInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


def invoice_idempotency_key_reused_response(request: Request) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was already used for different input.",
                "fields": [],
                "rule_ids": ["API-016"],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def invoice_line_fully_paid_response(request: Request) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "INVOICE_LINE_FULLY_PAID",
                "message": "A debit Adjustment needs a positive line balance.",
                "fields": [],
                "rule_ids": ["BR-INV-044"],
                "current_version": None,
            },
            "meta": {"request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if request.method in {"POST", "PATCH", "PUT"}:
        require_billing_actor(request, actor)
    return actor


def _authorize(
    actor: AuthenticatedActor, property_id: UUID, capability: str, *, hide: bool = False
) -> None:
    if is_authorized(
        actor,
        AuthorizationRequirement(capability=capability, property_id=str(property_id)),
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND if hide else status.HTTP_403_FORBIDDEN
    )


def _version(value: str | None) -> int:
    if value is None:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    candidate = value.strip()
    if candidate.startswith('"') and candidate.endswith('"'):
        candidate = candidate[1:-1]
    if (
        len(candidate) > len(str(MAX_INVOICE_EXPECTED_VERSION))
        or not candidate.isascii()
        or not candidate.isdecimal()
    ):
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    version = int(candidate)
    if not 1 <= version <= MAX_INVOICE_EXPECTED_VERSION:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    return version


def _invoke(command: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return command()
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except InvoiceAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
    except InvoiceVersionConflict:
        raise
    except InvoiceIdempotencyKeyReused:
        raise
    except InvoiceLineFullyPaid:
        raise
    except InvoiceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from exc
    except InvoiceInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    except InvoiceServiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc


def _envelope(resource: dict[str, object], request: Request) -> dict[str, object]:
    return {"data": resource, "meta": {"request_id": request.state.request_id}}


def _etag(response: Response, resource: dict[str, object]) -> None:
    response.headers["ETag"] = f'"{int(str(resource["version"]))}"'


def billing_capabilities(actor: AuthenticatedActor, property_id: UUID) -> list[str]:
    """Visibility only; each route and service retain authoritative authorization."""
    return [
        capability
        for capability in (
            INVOICE_CREATE_CAPABILITY,
            INVOICE_ISSUE_CAPABILITY,
            INVOICE_ADJUST_CAPABILITY,
            INVOICE_VOID_CAPABILITY,
            "billing.generate",
            DAMAGE_CHARGE_BILL_CAPABILITY,
            PROPERTY_MANAGE_CAPABILITY,
            SETTINGS_MANAGE_CAPABILITY,
            "late_payment.review",
            "late_payment.final_decision",
            "late_payment.charge_correction",
        )
        if is_authorized(
            actor,
            AuthorizationRequirement(capability=capability, property_id=str(property_id)),
        )
    ]


def create_invoice_router(
    resolver: ActorResolver,
    flow: InvoiceFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["invoices"])

    @router.get("/properties/{property_id}/billing-capabilities")
    def get_billing_capabilities(property_id: UUID, request: Request) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        return _envelope(
            {
                "property_id": str(property_id),
                "billing_capabilities": billing_capabilities(actor, property_id),
            },
            request,
        )

    @router.get("/properties/{property_id}/invoices")
    def list_invoices(
        property_id: UUID,
        request: Request,
        status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
        category: InvoiceCategory | None = None,
        customer_id: UUID | None = None,
        lease_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_INVOICE_PAGE_SIZE)] = 50,
        cursor: str | None = None,
        sort: Literal["invoice_date", "-invoice_date"] = "-invoice_date",
    ) -> dict[str, object]:
        allowed = {"status", "category", "customer_id", "lease_id", "limit", "cursor", "sort"}
        if any(key not in allowed for key in request.query_params):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_READ_CAPABILITY)
        try:
            validate_invoice_cursor(cursor)
            page = flow.list(
                property_id,
                actor=actor,
                status_filter=status_filter,
                category=category,
                customer_id=customer_id,
                lease_id=lease_id,
                limit=limit,
                cursor=cursor,
                descending=sort.startswith("-"),
            )
        except InvoiceAuthorizationError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc
        except InvoiceNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except InvoiceInvalidError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
        except InvoiceServiceUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        return {
            "data": list(page.items),
            "page": {"next_cursor": page.next_cursor, "limit": limit},
            "meta": {
                "request_id": request.state.request_id,
                "billing_capabilities": billing_capabilities(actor, property_id),
            },
        }

    @router.post("/properties/{property_id}/invoices", status_code=status.HTTP_201_CREATED)
    def create_invoice(
        property_id: UUID,
        body: AuthorizedObligationInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _invoke(
            lambda: flow.create_draft(
                property_id,
                CreateInvoiceDraftCommand(
                    idempotency_key, body.authorized_nonrecurring_obligation_id
                ),
                actor=actor,
            )
        )
        response.headers["Location"] = f"/api/v1/invoices/{resource['id']}"
        _etag(response, resource)
        return _envelope(resource, request)

    @router.post("/properties/{property_id}/invoices/drafts", status_code=status.HTTP_201_CREATED)
    def create_items_invoice(
        property_id: UUID,
        body: ItemsInvoiceDraftInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """DL-103: record every item's charge and one Miscellaneous DRAFT in one step."""
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _invoke(
            lambda: flow.create_items_draft(
                property_id,
                CreateItemsInvoiceDraftCommand(
                    idempotency_key,
                    body.customer_id,
                    body.lease_id,
                    body.reason,
                    body.evidence_reference,
                    _invoice_items(body.items),
                ),
                actor=actor,
            )
        )
        response.headers["Location"] = f"/api/v1/invoices/{resource['id']}"
        _etag(response, resource)
        return _envelope(resource, request)

    @router.post(
        "/properties/{property_id}/invoices/services-drafts", status_code=status.HTTP_201_CREATED
    )
    def create_services_invoice(
        property_id: UUID,
        body: ServicesInvoiceDraftInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        """DL-115 (I): a DRAFT of Regular services at their Settings price, How many each."""
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        require_browser_mutation(request, settings)
        items = tuple(
            ServiceInvoiceItem(item.charge_id, item.regular_service_id, item.quantity)
            for item in body.items
        )
        resource = _invoke(
            lambda: flow.create_services_draft(
                property_id,
                CreateServicesInvoiceDraftCommand(
                    idempotency_key, body.customer_id, body.lease_id, items
                ),
                actor=actor,
            )
        )
        response.headers["Location"] = f"/api/v1/invoices/{resource['id']}"
        _etag(response, resource)
        return _envelope(resource, request)

    @router.get("/invoices/{invoice_id}")
    def get_invoice(invoice_id: UUID, request: Request, response: Response) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        resource = _invoke(lambda: flow.get(invoice_id, actor=actor))
        _authorize(
            actor,
            UUID(str(resource["property_id"])),
            INVOICE_READ_CAPABILITY,
            hide=True,
        )
        _etag(response, resource)
        return _envelope(resource, request)

    def command_context(
        invoice_id: UUID,
        request: Request,
        capability: str,
    ) -> tuple[AuthenticatedActor, UUID]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_for_invoice(invoice_id)
        except (InvoiceNotFoundError, InvoiceAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except InvoiceServiceUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        _authorize(actor, property_id, capability, hide=True)
        require_browser_mutation(request, settings)
        return actor, property_id

    @router.patch("/invoices/{invoice_id}")
    def correct_invoice(
        invoice_id: UUID,
        body: DraftCorrectionInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor, property_id = command_context(invoice_id, request, INVOICE_CREATE_CAPABILITY)
        expected_version = _version(if_match)
        resource = _invoke(
            lambda: flow.correct_draft(
                property_id,
                invoice_id,
                CorrectInvoiceDraftCommand(
                    idempotency_key,
                    body.authorized_nonrecurring_obligation_id,
                    body.reason,
                    expected_version,
                ),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    @router.put("/invoices/{invoice_id}/items")
    def replace_invoice_items(
        invoice_id: UUID,
        body: InvoiceItemsChangeInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        """DL-103: Edit items on a DRAFT made from typed items, with the reason for the change."""
        actor, property_id = command_context(invoice_id, request, INVOICE_CREATE_CAPABILITY)
        expected_version = _version(if_match)
        resource = _invoke(
            lambda: flow.replace_draft_items(
                property_id,
                invoice_id,
                ReplaceInvoiceDraftItemsCommand(
                    idempotency_key,
                    body.customer_id,
                    body.lease_id,
                    body.reason,
                    body.evidence_reference,
                    body.change_reason,
                    _invoice_items(body.items),
                    expected_version,
                ),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    @router.post("/invoices/{invoice_id}/issue")
    def issue_invoice(
        invoice_id: UUID,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        body: IssueInput | None = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor, property_id = command_context(invoice_id, request, INVOICE_ISSUE_CAPABILITY)
        expected_version = _version(if_match)
        due_date = body.due_date if body is not None else None
        due_reason = body.due_date_reason if body is not None else None
        resource = _invoke(
            lambda: flow.issue(
                property_id,
                invoice_id,
                IssueInvoiceCommand(idempotency_key, expected_version, due_date, due_reason),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    @router.post("/properties/{property_id}/one-time-charges", status_code=status.HTTP_201_CREATED)
    def create_one_time_charge(
        property_id: UUID,
        body: OneTimeChargeInput,
        request: Request,
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, ONE_TIME_CHARGE_CAPABILITIES[body.category])
        require_browser_mutation(request, settings)
        resource = _invoke(
            lambda: flow.record_one_time_charge(
                property_id,
                RecordOneTimeChargeCommand(
                    body.charge_id,
                    body.category,
                    body.customer_id,
                    body.lease_id,
                    body.inspection_damage_finding_id,
                    body.description,
                    body.amount_usd_cents,
                    body.reason,
                    body.evidence_reference,
                ),
                actor=actor,
            )
        )
        return _envelope(resource, request)

    @router.get("/properties/{property_id}/one-time-charge-due-days")
    def get_one_time_charge_due_days(property_id: UUID, request: Request) -> dict[str, object]:
        """V1-058 R7b-4: the Settings Business tab shows the days and changes them with the
        version (the Property's version)."""
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, SETTINGS_MANAGE_CAPABILITY)
        resource = _invoke(lambda: flow.get_one_time_charge_due_days(property_id, actor=actor))
        return _envelope(resource, request)

    @router.post("/properties/{property_id}/one-time-charge-due-days")
    def set_one_time_charge_due_days(
        property_id: UUID,
        body: OneTimeChargeDueDaysInput,
        request: Request,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        # Login sub-slice L5 (owner answer (a) to Q-2026-10-21-151): a Settings item.
        _authorize(actor, property_id, SETTINGS_MANAGE_CAPABILITY)
        require_browser_mutation(request, settings)
        expected_version = _version(if_match)
        resource = _invoke(
            lambda: flow.set_one_time_charge_due_days(
                property_id,
                SetOneTimeChargeDueDaysCommand(body.days, body.reason, expected_version),
                actor=actor,
            )
        )
        return _envelope(resource, request)

    @router.post("/properties/{property_id}/leases/{lease_id}/initial-rent-due-date")
    def set_initial_rent_due_date(
        property_id: UUID,
        lease_id: UUID,
        body: InitialRentDueDateInput,
        request: Request,
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_ISSUE_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _invoke(
            lambda: flow.set_initial_rent_due_date(
                property_id,
                SetInitialRentDueDateCommand(
                    body.override_id, lease_id, body.due_date, body.reason
                ),
                actor=actor,
            )
        )
        return _envelope(resource, request)

    @router.post("/invoices/{invoice_id}/adjustments")
    def adjust_invoice(
        invoice_id: UUID,
        body: AdjustmentInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor, property_id = command_context(invoice_id, request, INVOICE_ADJUST_CAPABILITY)
        expected_version = _version(if_match)
        resource = _invoke(
            lambda: flow.adjust(
                property_id,
                invoice_id,
                AdjustInvoiceCommand(
                    idempotency_key,
                    body.invoice_line_id,
                    body.adjustment_type,
                    body.amount.minor_units,
                    body.source_reference,
                    body.reason,
                    expected_version,
                ),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    @router.post("/invoices/{invoice_id}/void")
    def void_invoice(
        invoice_id: UUID,
        body: VoidInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        actor, property_id = command_context(invoice_id, request, INVOICE_VOID_CAPABILITY)
        expected_version = _version(if_match)
        resource = _invoke(
            lambda: flow.void(
                property_id,
                invoice_id,
                VoidInvoiceCommand(idempotency_key, body.reason, expected_version),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    return router


# V1-056 slice 11a: the move-out cleaning charge (BR-UNIT-014, BR-MOVEOUT-013) and the
# hand-back month actions (BR-RENT-030). Each database refusal of business state below
# answers 409 with its own code (owner answer of 2026-10-05); no database text is shown.
REFUSALS_BY_DATABASE_MESSAGE: Final[dict[str, Refusal]] = {
    "No Unit cleaning charge: the Customer never moved in": CLEANING_CHARGE_NOT_MOVED_IN,
    "Unit cleaning charge needs a recorded move-out": CLEANING_CHARGE_NEEDS_MOVE_OUT,
    "The Unit cleaning charge is already recorded for this Lease": (
        CLEANING_CHARGE_ALREADY_RECORDED
    ),
    "The Unit has no cleaning rate": CLEANING_RATE_NOT_SET,
    "The Unit cleaning rate is zero; there is no cleaning charge": CLEANING_RATE_ZERO,
    "Unit cleaning rate changed": CLEANING_RATE_CHANGED,
    "The hand-back rule covers only monthly Rent Invoices generated on the 25th": (
        HAND_BACK_NOT_MONTHLY_RENT
    ),
    "The hand-back rule covers only an issued Invoice that is not VOID": (
        HAND_BACK_INVOICE_NOT_ISSUED
    ),
    "The hand-back rule covers only a verified voluntary early termination": (
        HAND_BACK_NOT_EARLY_TERMINATION
    ),
    "The hand-back rule needs a recorded move-out": HAND_BACK_NEEDS_MOVE_OUT,
    "The current move-out record is ambiguous": HAND_BACK_MOVE_OUT_UNCLEAR,
    "The Invoice month is not covered by the hand-back date": HAND_BACK_MONTH_NOT_COVERED,
    "The Invoice already has a hand-back resolution": HAND_BACK_ALREADY_RESOLVED,
    "A fully paid hand-back Invoice is kept as issued": HAND_BACK_PAID_INVOICE_KEPT,
    "The hand-back assessment changed": HAND_BACK_ASSESSMENT_CHANGED,
    # Raised by app.void_invoice inside the hand-back VOID; reason and status are already valid.
    "Invoice VOID dependencies are not resolved": HAND_BACK_VOID_BLOCKED,
    # Migration 92 and its later forms: nothing changes a closed Final Settlement's records.
    "A closed Final Settlement changes only through a post-settlement correction": (
        FINAL_SETTLEMENT_CLOSED
    ),
    "A Deposit application paid this obligation at Final Settlement": FINAL_SETTLEMENT_CLOSED,
    # The identity is the idempotency key of these commands (API-016).
    "Unit cleaning rate identity was reused": IDEMPOTENCY_KEY_REUSED,
    "Unit cleaning charge identity was reused": IDEMPOTENCY_KEY_REUSED,
    "One-time charge identity was reused": IDEMPOTENCY_KEY_REUSED,
}


class MoveOutBillingFlow(Protocol):
    def property_for_invoice(self, invoice_id: UUID) -> UUID: ...

    def unit_cleaning_rate(
        self, property_id: UUID, unit_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object] | None: ...

    def set_unit_cleaning_rate(
        self,
        property_id: UUID,
        command: SetUnitCleaningRateCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def record_unit_cleaning_charge(
        self,
        property_id: UUID,
        command: RecordUnitCleaningChargeCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...

    def hand_back_rent_assessment(
        self, property_id: UUID, invoice_id: UUID, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...

    def resolve_hand_back_rent(
        self,
        property_id: UUID,
        invoice_id: UUID,
        command: ResolveHandBackRentCommand,
        *,
        actor: AuthenticatedActor,
    ) -> dict[str, object]: ...


class CleaningRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_id: UUID
    # Required, and null only for a Unit that has no rate yet: the rate the screen showed.
    expected_current_rate_id: UUID | None
    rate_usd_cents: int = Field(strict=True, ge=0, le=9_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class CleaningChargeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charge_id: UUID
    expected_rate_id: UUID


class HandBackResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["VOID", "CREDIT_ADJUSTMENT"]
    expected_outstanding_usd_cents: int = Field(strict=True, ge=1, le=9_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


def _move_out_invoke(command: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return _invoke(command)
    except HTTPException as exc:
        refusal = (
            database_refusal(exc.__cause__, REFUSALS_BY_DATABASE_MESSAGE)
            if exc.__cause__ is not None
            else None
        )
        if refusal is not None:
            raise RefusedRequest(refusal) from exc
        raise


def create_move_out_billing_router(
    resolver: ActorResolver,
    flow: MoveOutBillingFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["invoices"])

    @router.get("/properties/{property_id}/units/{unit_id}/cleaning-rate")
    def get_unit_cleaning_rate(
        property_id: UUID, unit_id: UUID, request: Request
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        # The cleaning charge form reads it (invoices.create); so does the rate form.
        if not any(
            is_authorized(
                actor,
                AuthorizationRequirement(capability=capability, property_id=str(property_id)),
            )
            for capability in (INVOICE_CREATE_CAPABILITY, PROPERTY_MANAGE_CAPABILITY)
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        current = _invoke(
            lambda: {"rate": flow.unit_cleaning_rate(property_id, unit_id, actor=actor)}
        )
        return {
            "data": {
                "property_id": str(property_id),
                "unit_id": str(unit_id),
                "rate": current["rate"],
            },
            "meta": {"request_id": request.state.request_id},
        }

    @router.post(
        "/properties/{property_id}/units/{unit_id}/cleaning-rates",
        status_code=status.HTTP_201_CREATED,
    )
    def set_unit_cleaning_rate(
        property_id: UUID, unit_id: UUID, body: CleaningRateInput, request: Request
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        # DL-075 and the L5 entry of docs/010: property.manage sets the per-Unit rate until
        # the Settings screens move cleaning rates to Unit Type rate groups.
        _authorize(actor, property_id, PROPERTY_MANAGE_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _move_out_invoke(
            lambda: flow.set_unit_cleaning_rate(
                property_id,
                SetUnitCleaningRateCommand(
                    body.rate_id,
                    unit_id,
                    body.expected_current_rate_id,
                    body.rate_usd_cents,
                    body.reason,
                ),
                actor=actor,
            )
        )
        return _envelope(resource, request)

    @router.post(
        "/properties/{property_id}/leases/{lease_id}/cleaning-charge",
        status_code=status.HTTP_201_CREATED,
    )
    def record_unit_cleaning_charge(
        property_id: UUID, lease_id: UUID, body: CleaningChargeInput, request: Request
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        _authorize(actor, property_id, INVOICE_CREATE_CAPABILITY)
        require_browser_mutation(request, settings)
        resource = _move_out_invoke(
            lambda: flow.record_unit_cleaning_charge(
                property_id,
                RecordUnitCleaningChargeCommand(body.charge_id, lease_id, body.expected_rate_id),
                actor=actor,
            )
        )
        return _envelope(resource, request)

    def invoice_property(invoice_id: UUID) -> UUID:
        try:
            return flow.property_for_invoice(invoice_id)
        except (InvoiceNotFoundError, InvoiceAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except InvoiceServiceUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    @router.get("/invoices/{invoice_id}/hand-back-assessment")
    def get_hand_back_assessment(invoice_id: UUID, request: Request) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        property_id = invoice_property(invoice_id)
        # The answer shows the Lease's termination basis, so it needs leases.read too.
        _authorize(actor, property_id, INVOICE_READ_CAPABILITY, hide=True)
        _authorize(actor, property_id, LEASE_READ_CAPABILITY, hide=True)
        resource = _move_out_invoke(
            lambda: flow.hand_back_rent_assessment(property_id, invoice_id, actor=actor)
        )
        return _envelope(resource, request)

    @router.post("/invoices/{invoice_id}/hand-back-resolution")
    def resolve_hand_back_rent(
        invoice_id: UUID,
        body: HandBackResolutionInput,
        request: Request,
        response: Response,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        property_id = invoice_property(invoice_id)
        capability = INVOICE_VOID_CAPABILITY if body.action == "VOID" else INVOICE_ADJUST_CAPABILITY
        _authorize(actor, property_id, capability, hide=True)
        require_browser_mutation(request, settings)
        expected_version = _version(if_match)
        resource = _move_out_invoke(
            lambda: flow.resolve_hand_back_rent(
                property_id,
                invoice_id,
                ResolveHandBackRentCommand(
                    idempotency_key,
                    body.action,
                    body.expected_outstanding_usd_cents,
                    body.reason,
                    expected_version,
                ),
                actor=actor,
            )
        )
        invoice = resource.get("invoice")
        if isinstance(invoice, dict) and "version" in invoice:
            _etag(response, invoice)
        return _envelope(resource, request)

    return router
