"""Protected Invoice resources and explicit lifecycle commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.invoice import (
    INVOICE_ADJUST_CAPABILITY,
    INVOICE_CREATE_CAPABILITY,
    INVOICE_ISSUE_CAPABILITY,
    INVOICE_READ_CAPABILITY,
    INVOICE_VOID_CAPABILITY,
    MAX_INVOICE_PAGE_SIZE,
    AdjustInvoiceCommand,
    AdjustmentType,
    CorrectInvoiceDraftCommand,
    CreateInvoiceDraftCommand,
    InvoiceAuthorizationError,
    InvoiceConflictError,
    InvoiceIdempotencyKeyReused,
    InvoiceInvalidError,
    InvoiceNotFoundError,
    InvoicePage,
    InvoiceServiceUnavailableError,
    InvoiceVersionConflict,
    IssueInvoiceCommand,
    VoidInvoiceCommand,
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


class UnavailableInvoiceFlow:
    def __getattr__(self, _: str) -> object:
        raise InvoiceServiceUnavailableError("Invoice persistence is unavailable")


class AuthorizedObligationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorized_obligation_id: UUID


class DraftCorrectionInput(AuthorizedObligationInput):
    reason: str = Field(min_length=1, max_length=500, pattern=r"^\S(?:.*\S)?$")


class IssueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
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
    if not candidate.isdigit() or int(candidate) < 1:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED)
    return int(candidate)


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


def create_invoice_router(
    resolver: ActorResolver,
    flow: InvoiceFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["invoices"])

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
            "meta": {"request_id": request.state.request_id},
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
                CreateInvoiceDraftCommand(idempotency_key, body.authorized_obligation_id),
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
        resource = _invoke(
            lambda: flow.correct_draft(
                property_id,
                invoice_id,
                CorrectInvoiceDraftCommand(
                    idempotency_key,
                    body.authorized_obligation_id,
                    body.reason,
                    _version(if_match),
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
        del body
        actor, property_id = command_context(invoice_id, request, INVOICE_ISSUE_CAPABILITY)
        resource = _invoke(
            lambda: flow.issue(
                property_id,
                invoice_id,
                IssueInvoiceCommand(idempotency_key, _version(if_match)),
                actor=actor,
            )
        )
        _etag(response, resource)
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
                    _version(if_match),
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
        resource = _invoke(
            lambda: flow.void(
                property_id,
                invoice_id,
                VoidInvoiceCommand(idempotency_key, body.reason, _version(if_match)),
                actor=actor,
            )
        )
        _etag(response, resource)
        return _envelope(resource, request)

    return router
