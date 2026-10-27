"""What a Lease owes at signing, the draft's Security Deposit and the Initial Rent Invoice.

V1-060 B6, DL-100 (owner 27/10/2026): a walk-in draft Lease carries the Security Deposit the
customer will pay, so its printed draft shows it; Sign Lease first receives the full money due at
signing (the rest of the Security Deposit and the Initial Rent Invoice), signs, then makes the
Initial Rent Invoice at once so the money just received pays it. The amounts come from
app.lease_signing_preview (migration 20270325_244), which reads the Invoice generator's own rules;
the Invoice is made by app.generate_rent_service_invoice, as billing makes every Rent Invoice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Final, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from psycopg import IsolationLevel
from pydantic import BaseModel, ConfigDict, Field

from property_rental.api_refusals import Refusal, RefusedRequest
from property_rental.browser_security import require_browser_mutation
from property_rental.identity import (
    ActorResolver,
    AuthenticatedActor,
    AuthorizationRequirement,
    is_authorized,
)
from property_rental.settings import Settings

LEASE_READ_CAPABILITY: Final = "leases.read"
LEASE_DRAFT_CAPABILITY: Final = "leases.draft"
LEASE_SIGN_CAPABILITY: Final = "leases.sign"
CONNECT_TIMEOUT_SECONDS: Final = 3
LOCK_TIMEOUT_MS: Final = 3_000
QUERY_TIMEOUT_MS: Final = 5_000
MAX_CENTS: Final = 9_000_000_000_000_000

# The database's own refusal texts, answered with a plain message the screen shows.
REFUSALS: Final[dict[str, Refusal]] = {
    "Only a drafted Lease takes a planned Security Deposit": Refusal(
        409,
        "PLANNED_DEPOSIT_NOT_DRAFT",
        "Only a draft Lease takes a planned Security Deposit.",
    ),
    "A Lease from a Reservation keeps the Reservation's Security Deposit": Refusal(
        409,
        "PLANNED_DEPOSIT_FROM_RESERVATION",
        "A Lease from a Reservation keeps the Reservation's Security Deposit.",
        ("BR-DEP-005",),
    ),
    "A renewal Lease keeps the Security Deposit it carries": Refusal(
        409,
        "PLANNED_DEPOSIT_RENEWAL",
        "A renewal Lease keeps the Security Deposit it carries.",
    ),
    "Initial Rent Due Date precedes the issue date; record an authorized Due Date": Refusal(
        409,
        "INITIAL_RENT_DUE_DATE_PASSED",
        "The Initial Rent Due Date (Start Date + 5 days) has passed. "
        "Ask the Owner or a Manager to set a new Due Date first.",
        ("BR-RENT-009",),
    ),
    "Rent billing requires an applicable signed Lease": Refusal(
        409, "INITIAL_RENT_NOT_SIGNED", "The Lease is not signed yet."
    ),
}
PARTIAL_SERVICE = Refusal(
    409,
    "INITIAL_RENT_SERVICE_PART_MONTH",
    "A Service on this Lease covers only part of a month or has no rate. "
    "Fix the Service dates or its rate first.",
    ("BR-SVC-012",),
)


class LeaseSigningNotFound(LookupError):
    pass


class LeaseSigningUnavailable(RuntimeError):
    pass


class LeaseSigningInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InitialRentInvoice:
    invoice_id: UUID
    created: bool


class LeaseSigningFlow(Protocol):
    def property_of(self, lease_id: UUID) -> UUID: ...

    def preview(self, property_id: UUID, lease_id: UUID) -> dict[str, object]: ...

    def set_planned_deposit(
        self,
        property_id: UUID,
        lease_id: UUID,
        plan_id: UUID,
        actor_id: UUID,
        required_usd_cents: int,
        reason: str,
    ) -> int: ...

    def initial_invoice(
        self, property_id: UUID, lease_id: UUID, idempotency_key: UUID, actor_id: UUID
    ) -> InitialRentInvoice: ...


class UnavailableLeaseSigningFlow:
    def property_of(self, lease_id: UUID) -> UUID:
        raise LeaseSigningUnavailable(str(lease_id))

    def preview(self, property_id: UUID, lease_id: UUID) -> dict[str, object]:
        raise LeaseSigningUnavailable(str(lease_id))

    def set_planned_deposit(
        self,
        property_id: UUID,
        lease_id: UUID,
        plan_id: UUID,
        actor_id: UUID,
        required_usd_cents: int,
        reason: str,
    ) -> int:
        raise LeaseSigningUnavailable(str(lease_id))

    def initial_invoice(
        self, property_id: UUID, lease_id: UUID, idempotency_key: UUID, actor_id: UUID
    ) -> InitialRentInvoice:
        raise LeaseSigningUnavailable(str(lease_id))


def initial_request_digest(
    *,
    idempotency_key: UUID,
    invoice_id: UUID,
    invoice_number: str,
    lease_id: UUID,
    period_start: date,
    issued_at: datetime,
) -> str:
    payload = json.dumps(
        {
            "authorization_reference": LEASE_SIGN_CAPABILITY,
            "billing_kind": "INITIAL",
            "idempotency_key": str(idempotency_key),
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "issued_at": issued_at.astimezone(UTC).isoformat(),
            "lease_id": str(lease_id),
            "period_start": period_start.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class PostgresLeaseSigningFlow:
    def __init__(self, database_url: str, financial_database_url: str | None) -> None:
        self._database_url = database_url
        self._financial_database_url = financial_database_url

    def _connect(self, url: str) -> psycopg.Connection[tuple[object, ...]]:
        connection = psycopg.connect(url, connect_timeout=CONNECT_TIMEOUT_SECONDS)
        connection.isolation_level = IsolationLevel.READ_COMMITTED
        connection.execute(
            "SELECT pg_catalog.set_config('lock_timeout',%s,true)", (str(LOCK_TIMEOUT_MS),)
        )
        connection.execute(
            "SELECT pg_catalog.set_config('statement_timeout',%s,true)", (str(QUERY_TIMEOUT_MS),)
        )
        return connection

    @staticmethod
    def _raise(exc: psycopg.Error) -> None:
        if exc.sqlstate == "P0002":
            raise LeaseSigningNotFound from exc
        if (exc.diag.message_primary or "") in REFUSALS:
            raise RefusedRequest(REFUSALS[exc.diag.message_primary or ""]) from exc
        if exc.sqlstate in {"22023", "23514"}:
            if "Partial-month" in str(exc) or "rate is missing" in str(exc):
                raise RefusedRequest(PARTIAL_SERVICE) from exc
            raise LeaseSigningInvalid from exc
        raise LeaseSigningUnavailable from exc

    def property_of(self, lease_id: UUID) -> UUID:
        try:
            with self._connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT unit.property_id FROM app.leases AS lease "
                    "JOIN app.units AS unit ON unit.id=lease.unit_id WHERE lease.id=%s",
                    (lease_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise LeaseSigningUnavailable from exc
        if row is None:
            raise LeaseSigningNotFound
        return UUID(str(row[0]))

    def preview(self, property_id: UUID, lease_id: UUID) -> dict[str, object]:
        try:
            with self._connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT app.lease_signing_preview(%s,%s)", (property_id, lease_id)
                ).fetchone()
        except psycopg.Error as exc:
            self._raise(exc)
            raise
        if row is None:
            raise LeaseSigningUnavailable
        return cast(dict[str, object], row[0])

    def set_planned_deposit(
        self,
        property_id: UUID,
        lease_id: UUID,
        plan_id: UUID,
        actor_id: UUID,
        required_usd_cents: int,
        reason: str,
    ) -> int:
        try:
            with self._connect(self._database_url) as connection:
                row = connection.execute(
                    "SELECT app.set_lease_planned_security_deposit(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        property_id,
                        lease_id,
                        plan_id,
                        actor_id,
                        required_usd_cents,
                        reason,
                        LEASE_DRAFT_CAPABILITY,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            self._raise(exc)
            raise
        if row is None or row[0] is None:
            raise LeaseSigningUnavailable
        return int(str(row[0]))

    def initial_invoice(
        self, property_id: UUID, lease_id: UUID, idempotency_key: UUID, actor_id: UUID
    ) -> InitialRentInvoice:
        initial = cast(dict[str, object] | None, self.preview(property_id, lease_id)["initial"])
        if initial is None:
            raise LeaseSigningInvalid("The Lease has no Start Date or Rent")
        if initial.get("invoice_id") is not None:
            return InitialRentInvoice(UUID(str(initial["invoice_id"])), created=False)
        if initial.get("problem") is not None:
            raise RefusedRequest(PARTIAL_SERVICE)
        if self._financial_database_url is None:
            raise LeaseSigningUnavailable
        start = date.fromisoformat(str(initial["period_start"]))
        invoice_id = uuid4()
        invoice_number = f"RENT-I-{start:%Y%m}-{lease_id.hex[:12]}"
        issued_at = datetime.now(UTC)
        digest = initial_request_digest(
            idempotency_key=idempotency_key,
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            lease_id=lease_id,
            period_start=start,
            issued_at=issued_at,
        )
        try:
            with self._connect(self._financial_database_url) as connection:
                row = connection.execute(
                    "SELECT app.generate_rent_service_invoice"
                    "(%s,%s,%s,%s,%s,%s,NULL,'INITIAL',%s,%s,%s,NULL)",
                    (
                        property_id,
                        idempotency_key,
                        digest,
                        invoice_id,
                        invoice_number,
                        lease_id,
                        start,
                        issued_at,
                        actor_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            self._raise(exc)
            raise
        if row is None:
            raise LeaseSigningUnavailable
        made = cast(dict[str, object], row[0])
        return InitialRentInvoice(UUID(str(made["invoice_id"])), created=True)


class PlannedDepositSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    plan_id: UUID = Field(strict=False)
    required_usd_cents: int = Field(ge=1, le=MAX_CENTS)
    reason: str = Field(min_length=1, max_length=500)


def _actor(request: Request, resolver: ActorResolver) -> AuthenticatedActor:
    actor = resolver(request)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return actor


def _actor_id(actor: AuthenticatedActor) -> UUID:
    try:
        return UUID(actor.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc


def _require(actor: AuthenticatedActor, property_id: UUID, capability: str) -> None:
    if not is_authorized(
        actor, AuthorizationRequirement(capability=capability, property_id=str(property_id))
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _translate(exc: Exception) -> HTTPException | RefusedRequest:
    if isinstance(exc, (HTTPException, RefusedRequest)):
        return exc
    if isinstance(exc, LeaseSigningNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, LeaseSigningInvalid):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def create_lease_signing_router(
    resolver: ActorResolver, flow: LeaseSigningFlow, settings: Settings
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["leases"])

    @router.get("/leases/{lease_id}/signing-preview")
    def signing_preview(lease_id: UUID, request: Request, response: Response) -> dict[str, object]:
        if request.query_params:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_of(lease_id)
            _require(actor, property_id, LEASE_READ_CAPABILITY)
            data = flow.preview(property_id, lease_id)
        except Exception as exc:
            raise _translate(exc) from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"data": data, "meta": {"request_id": request.state.request_id}}

    @router.put("/leases/{lease_id}/planned-security-deposit")
    def planned_security_deposit(
        lease_id: UUID, source: PlannedDepositSource, request: Request
    ) -> dict[str, object]:
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_of(lease_id)
            _require(actor, property_id, LEASE_DRAFT_CAPABILITY)
            require_browser_mutation(request, settings)
            amount = flow.set_planned_deposit(
                property_id,
                lease_id,
                source.plan_id,
                _actor_id(actor),
                source.required_usd_cents,
                source.reason,
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": {"planned_security_deposit_usd_cents": amount},
            "meta": {"request_id": request.state.request_id},
        }

    @router.post("/leases/{lease_id}/initial-rent-invoice")
    def initial_rent_invoice(
        lease_id: UUID,
        request: Request,
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        actor = _actor(request, resolver)
        try:
            property_id = flow.property_of(lease_id)
            _require(actor, property_id, LEASE_SIGN_CAPABILITY)
            require_browser_mutation(request, settings)
            made = flow.initial_invoice(property_id, lease_id, idempotency_key, _actor_id(actor))
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "data": {"invoice_id": str(made.invoice_id), "created": made.created},
            "meta": {"request_id": request.state.request_id},
        }

    return router
