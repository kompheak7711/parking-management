"""Canonical warning/nonpayment routes and minimal authorized staff discovery."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, Protocol, TypeVar, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BeforeValidator, Field

from property_rental.browser_security import require_browser_mutation
from property_rental.financial_context import bind_financial_property, financial_metadata
from property_rental.identity import ActorResolver, AuthenticatedActor
from property_rental.lease_enforcement import (
    NONPAYMENT_EVENT,
    NONPAYMENT_OPEN,
    NONPAYMENT_READ,
    WARNING_CREATE,
    WARNING_READ,
    LeaseEnforcementAuthorizationError,
    LeaseEnforcementConflictError,
    LeaseEnforcementInvalidError,
    LeaseEnforcementKeyReused,
    LeaseEnforcementNotFoundError,
    LeaseEnforcementResponse,
    LeaseEnforcementUnavailableError,
    NonpaymentEventKind,
    OpenRentNonpaymentCase,
    RecordLeaseWarning,
    RecordRentNonpaymentEvent,
)
from property_rental.lease_enforcement_context import (
    ContextKind,
    EnforcementPage,
    EnforcementScope,
    Purpose,
)
from property_rental.payment_api import (
    Evidence,
    Identity,
    Memo,
    PaymentRequestRoute,
    StrictInput,
    _actor,
    _queries,
    _strict_json,
)
from property_rental.settings import Settings


class EnforcementFlow(Protocol):
    def read(
        self,
        property_id: UUID,
        lease_id: UUID,
        kind: Literal["WARNINGS", "CASES", "CASE", "EVENTS"],
        *,
        actor: AuthenticatedActor,
        case_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]: ...
    def record_warning(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: RecordLeaseWarning,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse: ...
    def open_case(
        self,
        property_id: UUID,
        lease_id: UUID,
        command: OpenRentNonpaymentCase,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse: ...
    def record_event(
        self,
        property_id: UUID,
        lease_id: UUID,
        case_id: UUID,
        command: RecordRentNonpaymentEvent,
        *,
        actor: AuthenticatedActor,
        request_id: str,
    ) -> LeaseEnforcementResponse: ...


class EnforcementContextFlow(Protocol):
    def resolve(
        self,
        kind: Literal["LEASE", "CASE"],
        identity: UUID,
        capability: str,
        *,
        actor: AuthenticatedActor,
    ) -> EnforcementScope: ...
    def workspaces(
        self, page: EnforcementPage, *, actor: AuthenticatedActor
    ) -> dict[str, object]: ...
    def read(
        self,
        property_id: UUID,
        kind: ContextKind,
        *,
        actor: AuthenticatedActor,
        lease_id: UUID | None = None,
        case_id: UUID | None = None,
        page: EnforcementPage | None = None,
        purpose: Purpose | None = None,
    ) -> dict[str, object]: ...


def _calendar(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("A calendar date is required")
    return date.fromisoformat(value)


CalendarDate = Annotated[date, BeforeValidator(_calendar)]


class WarningInput(StrictInput):
    warning_sequence: Annotated[int, Field(strict=True, ge=1, le=32767)]
    violation_date: CalendarDate
    warning_date: CalendarDate
    violation_description: Memo
    lease_provision: Memo
    communication_record: Memo
    reason: Evidence


class CaseInput(StrictInput):
    rent_invoice_line_id: Identity
    reason: Evidence


class EventInput(StrictInput):
    event_kind: NonpaymentEventKind
    reason: Evidence
    notice_document_reference: Evidence | None = None
    communication_record: Memo | None = None
    authorization_reference: Evidence | None = None


T = TypeVar("T")


def _invoke(call: Callable[[], T]) -> T:
    try:
        return call()
    except LeaseEnforcementNotFoundError as exc:
        raise HTTPException(404) from exc
    except LeaseEnforcementAuthorizationError as exc:
        raise HTTPException(403) from exc
    except LeaseEnforcementKeyReused:
        raise
    except LeaseEnforcementConflictError as exc:
        raise HTTPException(409) from exc
    except LeaseEnforcementInvalidError as exc:
        raise HTTPException(422) from exc
    except LeaseEnforcementUnavailableError as exc:
        raise HTTPException(503) from exc


def _number(request: Request, name: str, default: int, maximum: int, minimum: int = 0) -> int:
    raw = request.query_params.get(name, str(default))
    if re.fullmatch(r"0|[1-9][0-9]{0,6}", raw) is None or not minimum <= int(raw) <= maximum:
        raise HTTPException(400)
    return int(raw)


def _page(request: Request, extra: set[str] | None = None) -> EnforcementPage:
    _queries(request, {"limit", "cursor"} | (extra or set()))
    limit = _number(request, "limit", 50, 100, 1)
    raw = request.query_params.get("cursor")
    try:
        cursor = None if raw is None else UUID(raw)
        if cursor is not None and (str(cursor) != raw or not cursor.int):
            raise ValueError
        return EnforcementPage(limit, cursor)
    except ValueError as exc:
        raise HTTPException(400) from exc


def create_enforcement_router(
    resolver: ActorResolver,
    flow: EnforcementFlow,
    context: EnforcementContextFlow,
    settings: Settings,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1", tags=["lease enforcement"], route_class=PaymentRequestRoute
    )

    def actor_for(request: Request, *, mutation: bool = False) -> AuthenticatedActor:
        for header in (
            "Idempotency-Key",
            "Origin",
            "X-CSRF-Token",
            "X-Billing-Actor-ID",
            "X-Financial-Property-ID",
        ):
            if len(request.headers.getlist(header)) > 1:
                raise HTTPException(400)
        actor = _actor(request, resolver)
        if mutation:
            _queries(request, set())
            if not request.headers.get("X-CSRF-Token"):
                raise HTTPException(403)
            require_browser_mutation(request, settings)
        return actor

    def scope_for(
        request: Request,
        kind: Literal["LEASE", "CASE"],
        identity: UUID,
        cap: str,
        *,
        mutation: bool = False,
    ) -> tuple[AuthenticatedActor, EnforcementScope]:
        actor = actor_for(request, mutation=mutation)
        scope = _invoke(lambda: context.resolve(kind, identity, cap, actor=actor))
        bind_financial_property(request, scope.property_id)
        return actor, scope

    def envelope(request: Request, data: dict[str, object]) -> dict[str, object]:
        return {"data": data, "meta": financial_metadata(request)}

    def command_reply(
        request: Request, call: Callable[[], LeaseEnforcementResponse]
    ) -> JSONResponse:
        try:
            reply = _invoke(call)
        except LeaseEnforcementKeyReused:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "The command key was used for different input.",
                        "fields": [],
                        "rule_ids": ["API-016"],
                        "current_version": None,
                    },
                    "meta": financial_metadata(request),
                },
            )
        # Persisted data and original request ID survive replay. The verified route
        # Property supplements metadata; current assessment is a separate read.
        meta = reply.body.get("meta")
        if not isinstance(meta, dict) or not isinstance(meta.get("request_id"), str):
            raise HTTPException(503)
        return JSONResponse(
            status_code=reply.status_code,
            content={
                **reply.body,
                "meta": {**meta, "property_id": str(request.state.financial_property_id)},
            },
        )

    def history(
        request: Request, identity: UUID, kind: Literal["WARNINGS", "CASES", "CASE", "EVENTS"]
    ) -> dict[str, object]:
        _queries(request, set() if kind == "CASE" else {"limit", "offset"})
        limit, offset = (
            _number(request, "limit", 50, 100, 1),
            _number(request, "offset", 0, 1_000_000),
        )
        is_case = kind in {"CASE", "EVENTS"}
        actor, scope = scope_for(
            request,
            "CASE" if is_case else "LEASE",
            identity,
            WARNING_READ if kind == "WARNINGS" else NONPAYMENT_READ,
        )
        result = _invoke(
            lambda: flow.read(
                scope.property_id,
                scope.lease_id,
                kind,
                actor=actor,
                case_id=identity if is_case else None,
                limit=limit,
                offset=offset,
            )
        )
        return envelope(request, result)

    @router.get("/leases/{lease_id}/violation-warnings")
    def warnings(lease_id: Identity, request: Request) -> dict[str, object]:
        return history(request, lease_id, "WARNINGS")

    @router.get("/leases/{lease_id}/rent-nonpayment-cases")
    def cases(lease_id: Identity, request: Request) -> dict[str, object]:
        return history(request, lease_id, "CASES")

    @router.get("/rent-nonpayment-cases/{case_id}")
    def case(case_id: Identity, request: Request) -> dict[str, object]:
        return history(request, case_id, "CASE")

    @router.get("/rent-nonpayment-cases/{case_id}/events")
    def events(case_id: Identity, request: Request) -> dict[str, object]:
        return history(request, case_id, "EVENTS")

    @router.post(
        "/leases/{lease_id}/violation-warnings",
        status_code=201,
        dependencies=[Depends(_strict_json)],
    )
    def warning(
        lease_id: Identity,
        body: WarningInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        actor, scope = scope_for(request, "LEASE", lease_id, WARNING_CREATE, mutation=True)
        command = _invoke(
            lambda: RecordLeaseWarning(
                idempotency_key,
                body.warning_sequence,
                body.violation_date,
                body.warning_date,
                body.violation_description,
                body.lease_provision,
                body.communication_record,
                body.reason,
            )
        )
        return command_reply(
            request,
            lambda: flow.record_warning(
                scope.property_id,
                lease_id,
                command,
                actor=actor,
                request_id=request.state.request_id,
            ),
        )

    @router.post(
        "/leases/{lease_id}/rent-nonpayment-cases",
        status_code=201,
        dependencies=[Depends(_strict_json)],
    )
    def open_case(
        lease_id: Identity,
        body: CaseInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        actor, scope = scope_for(request, "LEASE", lease_id, NONPAYMENT_OPEN, mutation=True)
        command = _invoke(
            lambda: OpenRentNonpaymentCase(idempotency_key, body.rent_invoice_line_id, body.reason)
        )
        return command_reply(
            request,
            lambda: flow.open_case(
                scope.property_id,
                lease_id,
                command,
                actor=actor,
                request_id=request.state.request_id,
            ),
        )

    @router.post(
        "/rent-nonpayment-cases/{case_id}/events",
        status_code=201,
        dependencies=[Depends(_strict_json)],
    )
    def record_event(
        case_id: Identity,
        body: EventInput,
        request: Request,
        idempotency_key: Annotated[Identity, Header(alias="Idempotency-Key")],
    ) -> JSONResponse:
        actor, scope = scope_for(request, "CASE", case_id, NONPAYMENT_EVENT, mutation=True)
        command = _invoke(
            lambda: RecordRentNonpaymentEvent(
                idempotency_key,
                body.event_kind,
                body.reason,
                body.notice_document_reference,
                body.communication_record,
                body.authorization_reference,
            )
        )
        return command_reply(
            request,
            lambda: flow.record_event(
                scope.property_id,
                scope.lease_id,
                case_id,
                command,
                actor=actor,
                request_id=request.state.request_id,
            ),
        )

    @router.get("/lease-enforcement-workspaces")
    def workspaces(request: Request) -> dict[str, object]:
        actor = actor_for(request)
        if request.headers.getlist("X-Financial-Property-ID"):
            raise HTTPException(400)
        page = _page(request)
        return {
            "data": _invoke(lambda: context.workspaces(page, actor=actor)),
            "meta": {"request_id": request.state.request_id, "actor_id": actor.actor_id},
        }

    @router.get("/properties/{property_id}/lease-enforcement-leases")
    def leases(property_id: Identity, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        page = _page(request, {"purpose"})
        purpose = request.query_params.get("purpose")
        if purpose not in {"WARNINGS", "NONPAYMENT"}:
            raise HTTPException(400)
        result = _invoke(
            lambda: context.read(
                property_id, "LEASES", actor=actor, page=page, purpose=cast(Purpose, purpose)
            )
        )
        bind_financial_property(request, property_id)
        return envelope(request, result)

    @router.get("/properties/{property_id}/rent-nonpayment-alerts")
    def alerts(property_id: Identity, request: Request) -> dict[str, object]:
        actor = actor_for(request)
        page = _page(request)
        result = _invoke(lambda: context.read(property_id, "ALERTS", actor=actor, page=page))
        bind_financial_property(request, property_id)
        return envelope(request, result)

    def action_context(
        request: Request,
        identity: UUID,
        kind: Literal["SOURCES", "ACTION_CASES", "EVENT_CONTEXT", "WARNING_CONTEXT"],
    ) -> dict[str, object]:
        single = kind in {"EVENT_CONTEXT", "WARNING_CONTEXT"}
        if single:
            _queries(request, set())
        page = EnforcementPage() if single else _page(request)
        cap = (
            WARNING_CREATE
            if kind == "WARNING_CONTEXT"
            else NONPAYMENT_OPEN
            if kind == "SOURCES"
            else NONPAYMENT_EVENT
        )
        actor, scope = scope_for(
            request, "CASE" if kind == "EVENT_CONTEXT" else "LEASE", identity, cap
        )
        result = _invoke(
            lambda: context.read(
                scope.property_id,
                kind,
                actor=actor,
                lease_id=scope.lease_id,
                case_id=identity if kind == "EVENT_CONTEXT" else None,
                page=page,
            )
        )
        return envelope(request, result)

    @router.get("/leases/{lease_id}/violation-warning-context")
    def warning_context(lease_id: Identity, request: Request) -> dict[str, object]:
        return action_context(request, lease_id, "WARNING_CONTEXT")

    @router.get("/leases/{lease_id}/rent-nonpayment-sources")
    def sources(lease_id: Identity, request: Request) -> dict[str, object]:
        return action_context(request, lease_id, "SOURCES")

    @router.get("/leases/{lease_id}/rent-nonpayment-action-cases")
    def action_cases(lease_id: Identity, request: Request) -> dict[str, object]:
        return action_context(request, lease_id, "ACTION_CASES")

    @router.get("/rent-nonpayment-cases/{case_id}/action-context")
    def event_context(case_id: Identity, request: Request) -> dict[str, object]:
        return action_context(request, case_id, "EVENT_CONTEXT")

    return router
