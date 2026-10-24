"""Protected Invoice resources and explicit lifecycle commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.access_control import SETTINGS_MANAGE_CAPABILITY
from property_rental.api import require_billing_actor
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
    MAX_INVOICE_EXPECTED_VERSION,
    MAX_INVOICE_PAGE_SIZE,
    ONE_TIME_CHARGE_CAPABILITIES,
    PROPERTY_MANAGE_CAPABILITY,
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceIdempotencyKeyReused,
    InvoiceInvalidError,
    InvoiceLineFullyPaid,
    InvoiceNotFoundError,
    InvoicePage,
    InvoiceServiceUnavailableError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    RecordOneTimeChargeCommand,
    SetOneTimeChargeDueDaysCommand,
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
    if request.method in {"POST", "PATCH"}:
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
